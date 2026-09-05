from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from webapp.backend import ingest, serve
from webapp.backend.storage import Store


ROOT = Path(__file__).resolve().parents[1]


def _write_database_preflight_marker(database: Path, nonce: str) -> Path:
    raw = database.read_bytes()
    marker = database.with_name(serve.DATABASE_PREFLIGHT_MARKER)
    value = {
        "schema": "atlas.database-preflight-request/1",
        "nonce": nonce,
        "database_name": database.name,
        "input_copy_sha256": hashlib.sha256(raw).hexdigest(),
        "input_copy_bytes": len(raw),
        "requested_action": "open_migrate_copy_and_report",
    }
    marker.write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    return marker


def test_socket_boundary_denies_external_resolution_but_keeps_loopback() -> None:
    code = """
import socket
import os
from portable import network_boundary as n
n.install()
assert n.installed() and not n.live_network_allowed() and n.offline_probe()
assert socket.getaddrinfo('127.0.0.1', 80)
try:
    socket.getaddrinfo('example.com', 443)
except PermissionError:
    pass
else:
    raise SystemExit('external resolution was allowed')
try:
    socket.getnameinfo(('192.0.2.1', 443), 0)
except PermissionError:
    pass
else:
    raise SystemExit('reverse DNS egress was allowed')
for kind in ('tcp', 'connect_ex', 'udp'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if kind == 'udp' else socket.SOCK_STREAM)
    try:
        try:
            if kind == 'udp': sock.sendto(b'x', ('192.0.2.1', 9))
            elif kind == 'connect_ex': sock.connect_ex(('192.0.2.1', 9))
            else: sock.connect(('192.0.2.1', 9))
        except PermissionError:
            pass
        else:
            raise SystemExit(kind + ' egress was allowed')
    finally:
        sock.close()
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    try:
        sock.connect(('localhost', 9))
    except PermissionError:
        pass
    else:
        raise SystemExit('direct localhost connect was allowed without numeric resolution')
finally:
    sock.close()
if os.name == 'nt':
    from asyncio import windows_events
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            windows_events.IocpProactor.connect(object(), sock, ('192.0.2.1', 9))
        except PermissionError:
            pass
        else:
            raise SystemExit('asyncio Proactor egress was allowed')
    finally:
        sock.close()
originals = getattr(socket, n._ORIGINALS_MARKER)
real_getaddrinfo = originals['getaddrinfo']
try:
    originals['getaddrinfo'] = lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('203.0.113.10', 80))
    ]
    try:
        socket.getaddrinfo('localhost', 80)
    except PermissionError:
        pass
    else:
        raise SystemExit('poisoned localhost resolution was allowed')
finally:
    originals['getaddrinfo'] = real_getaddrinfo
# Reinstall is genuinely idempotent and must not erase a flag set by the explicit CLI path.
os.environ[n.ALLOW_ENV] = '1'
n.install()
assert n.live_network_allowed()
"""
    environment = dict(os.environ)
    # Ambient state is hostile input, not an authorization. The runtime hook must clear it.
    environment["ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_frozen_portable_profile_rejects_non_loopback_bind(monkeypatch, capsys) -> None:
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    rc = serve.main(["--host", "0.0.0.0", "--no-browser"])
    assert rc == 2
    assert "loopback-only" in capsys.readouterr().err


def test_frozen_portable_profile_rejects_localhost_name(monkeypatch, capsys) -> None:
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    rc = serve.main(["--host", "localhost", "--no-browser"])
    assert rc == 2
    assert "numeric loopback" in capsys.readouterr().err


def test_numeric_loopback_predicate_is_independent_of_name_resolution() -> None:
    assert serve._bind_is_numeric_loopback("127.0.0.1")
    assert serve._bind_is_numeric_loopback("::1")
    assert not serve._bind_is_numeric_loopback("[::1]")
    assert not serve._bind_is_numeric_loopback("localhost")
    assert not serve._bind_is_numeric_loopback("0.0.0.0")


@pytest.mark.skipif(os.name != "nt", reason="PyInstaller Windows DLL search behavior")
def test_frozen_external_browser_launch_sanitizes_and_restores_dll_search(monkeypatch, tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    original_path = str(bundle) + os.pathsep + str(tmp_path / "system")
    monkeypatch.setenv("PATH", original_path)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    dll_calls = []
    monkeypatch.setattr(
        serve,
        "_set_windows_dll_directory",
        lambda value: dll_calls.append(value) or True,
    )
    observed = {}

    def opener(url):
        observed["url"] = url
        observed["path"] = os.environ["PATH"]
        return True

    assert serve._open_external_url("http://127.0.0.1:8000/", opener=opener) is True
    assert str(bundle) not in observed["path"]
    assert os.environ["PATH"] == original_path
    assert dll_calls == [None, str(bundle)]


def test_explicit_live_flag_is_removed_before_engine_dispatch(monkeypatch) -> None:
    observed = {}
    monkeypatch.delenv("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", raising=False)

    def run_engine(args):
        observed["args"] = args
        return 0

    monkeypatch.setattr(serve, "_run_engine", run_engine)
    assert serve.main(["--allow-live-network", "--run-engine", "--help"]) == 0
    assert observed["args"] == ["--help"]
    assert "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK" not in os.environ


def test_frozen_engine_child_receives_explicit_live_flag(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ATLAS_PORTABLE_ALLOW_LIVE_NETWORK", "1")
    argv = ingest._engine_argv()
    assert argv[1:] == ["--allow-live-network", "--run-engine"]


def test_database_preflight_migrates_only_a_copy(tmp_path, monkeypatch, capsys) -> None:
    active = tmp_path / "active" / "assesshub.db"
    store = Store(active)
    store.create_campaign("Keep", "evidence")
    store.close()
    before = hashlib.sha256(active.read_bytes()).hexdigest()
    candidate_copy = tmp_path / "copy" / "assesshub.db"
    candidate_copy.parent.mkdir()
    shutil.copy2(active, candidate_copy)

    nonce = "a" * 32
    marker = _write_database_preflight_marker(candidate_copy, nonce)
    monkeypatch.setenv(serve.DATABASE_PREFLIGHT_ENV, nonce)
    assert serve.run_database_preflight(str(candidate_copy)) == 0
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["status"] == "pass"
    assert receipt["row_counts"]["campaigns"] == 1
    assert receipt["request_nonce"] == nonce
    assert receipt["request_sha256"] == hashlib.sha256(marker.read_bytes()).hexdigest()
    assert receipt["input_copy_binding"]["sha256"] == before
    assert receipt["input_copy_binding"]["bytes"] > 0
    assert receipt["caller_supplied_database_modified"] is False
    assert receipt["authority_effect"] == "NONE"
    assert receipt["logical_migration"]["status"] == "pass"
    assert all(
        row["status"] == "preserved"
        for row in receipt["logical_migration"]["prior_table_preservation"]
    )
    assert hashlib.sha256(active.read_bytes()).hexdigest() == before


def test_database_preflight_requires_update_workflow_authority(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "db.sqlite"
    candidate.write_bytes(b"")
    monkeypatch.delenv(serve.DATABASE_PREFLIGHT_ENV, raising=False)
    assert serve.run_database_preflight(str(candidate)) == 2


def test_database_preflight_refuses_detached_or_noncanonical_marker(
    tmp_path, monkeypatch, capsys,
) -> None:
    candidate = tmp_path / "copy" / "assesshub.db"
    candidate.parent.mkdir()
    candidate.write_bytes(b"not a database")
    nonce = "b" * 32
    marker = _write_database_preflight_marker(candidate, nonce)
    marker.write_bytes(marker.read_bytes().replace(b'"nonce":"', b'"nonce": "'))
    monkeypatch.setenv(serve.DATABASE_PREFLIGHT_ENV, nonce)
    assert serve.run_database_preflight(str(candidate)) == 1
    assert "request is invalid" in capsys.readouterr().err


def test_database_preflight_refuses_the_frozen_active_store(
    tmp_path, monkeypatch, capsys,
) -> None:
    bundle = tmp_path / "Atlas"
    active = bundle / "data" / "assesshub.db"
    store = Store(active)
    store.close()
    nonce = "c" * 32
    _write_database_preflight_marker(active, nonce)
    monkeypatch.setenv(serve.DATABASE_PREFLIGHT_ENV, nonce)
    monkeypatch.setattr(serve, "_frozen", lambda: True)
    monkeypatch.setattr(serve, "_exe_dir", lambda: bundle)
    assert serve.run_database_preflight(str(active)) == 1
    assert "refuses the active frozen Atlas store" in capsys.readouterr().err


def test_database_preflight_migrates_the_exact_prior_release_fixture(
    tmp_path, monkeypatch, capsys,
) -> None:
    fixture = ROOT / "tests" / "fixtures" / "assesshub-v3.32.1.sql"
    database = tmp_path / "prior" / "assesshub.db"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    try:
        connection.executescript(fixture.read_text(encoding="utf-8"))
    finally:
        connection.close()
    nonce = "d" * 32
    _write_database_preflight_marker(database, nonce)
    monkeypatch.setenv(serve.DATABASE_PREFLIGHT_ENV, nonce)
    assert serve.run_database_preflight(str(database)) == 0
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["caller_supplied_database_modified"] is True
    assert {
        key: receipt["row_counts"][key]
        for key in ("campaigns", "snapshots", "executions", "execution_comparisons")
    } == {"campaigns": 1, "snapshots": 1, "executions": 1, "execution_comparisons": 0}
    logical = receipt["logical_migration"]
    assert logical["before"]["table_count"] == 4
    assert logical["after"]["table_count"] >= 10
    assert len(logical["prior_table_preservation"]) == 4
    assert receipt["quick_check"] == "ok"
