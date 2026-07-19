"""Atlas P1 — production entry module, frozen-aware engine dispatch, folder ingest, --selftest.

ADR-0004 (docs/decisions/0004-atlas-portable-app-p0.md) Consequences: the portable one-folder build
needs a production entry (`uvicorn.run(app)`, `freeze_support()`, no reload/workers), a frozen-aware
dispatch in backend/ingest.py (inside a PyInstaller exe `sys.executable` IS the app — relaunching it
on a repo-root .py respawns the server, not the engine), ingest-from-folder beside ZIP ingest, and a
`--selftest` that fails LOUD on the silent-degrade assets (explorer template, OUI/port KBs,
docx/pptx extras, frontend dist).

Same harness discipline as the sibling files: in-process via TestClient / direct calls, the engine
subprocess is always faked (a stub that writes the snapshot the dispatcher expects), no real DB.
"""

import io
import json
import sys
import types
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

import backend.ingest as ing  # noqa: E402
import backend.serve as serve  # noqa: E402
from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token DNS-rebinding guard.
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _campaign(client, name="c"):
    r = client.post("/api/campaigns", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _zip_bytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _fake_engine_run(record: dict):
    """A subprocess.run stand-in that behaves like a successful engine run: records the argv/cwd it
    was given and writes the snapshot file the dispatcher harvests next to --output."""

    def run(cmd, cwd=None, **kw):
        record["cmd"] = list(cmd)
        record["cwd"] = cwd
        out = Path(cmd[cmd.index("--output") + 1])
        snap = {"devices": {"core1": {"model": "C9300"}},
                "interfaces": [{"switch": "core1", "port": "Gi1/0/1"}]}
        Path(str(out)[: -len(".xlsx")] + ".snapshot.json").write_text(json.dumps(snap),
                                                                      encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="engine ok", stderr="")

    return run


def _collection_dir(tmp_path) -> Path:
    d = tmp_path / "fleet"
    (d / "core1").mkdir(parents=True)
    (d / "core1" / "show_version.txt").write_text("Cisco IOS XE Software", encoding="utf-8")
    return d


# ── frozen-aware engine dispatch ────────────────────────────────────────────────
def test_engine_argv_unfrozen_is_interpreter_plus_script():
    assert ing._engine_argv() == [sys.executable, str(ing._ENGINE_SCRIPT)]


def test_engine_argv_frozen_reinvokes_exe_with_sentinel(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert ing._engine_argv() == [sys.executable, serve.ENGINE_SENTINEL]


def test_run_collection_zip_frozen_dispatch_skips_script_check(monkeypatch, tmp_path):
    """Frozen build: the repo-root .py does not exist on disk — dispatch must re-invoke the exe with
    the sentinel instead of failing the script-existence guard (or worse, respawning the app)."""
    record = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine_run(record))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(ing, "_ENGINE_SCRIPT", tmp_path / "not-there.py")
    snap, report = ing.run_collection_zip(
        _zip_bytes({"fleet/core1/show_version.txt": "Cisco IOS XE Software"}))
    assert record["cmd"][:2] == [sys.executable, serve.ENGINE_SENTINEL]
    assert "--no-collect" in record["cmd"]
    assert snap["devices"] and report["n_device_dirs"] == 1


def test_run_collection_zip_unfrozen_missing_script_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(ing, "_ENGINE_SCRIPT", tmp_path / "gone.py")
    with pytest.raises(ing.EngineRunError):
        ing.run_collection_zip(_zip_bytes({"fleet/core1/show_version.txt": "x"}))


# ── entry module: sentinel child dispatch ───────────────────────────────────────
def test_main_run_engine_sentinel_dispatches_before_argparse(monkeypatch):
    """`Atlas.exe --run-engine <engine args>` must become the engine CLI verbatim — engine flags are
    NOT the entry module's argparse surface, so the sentinel has to short-circuit first."""
    seen = {}

    def fake_engine_main():
        seen["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(serve, "_load_engine_main", lambda: fake_engine_main)
    monkeypatch.setattr(sys, "argv", ["atlas"])  # auto-restored
    rc = serve.main([serve.ENGINE_SENTINEL, "--no-collect", "--totally-unknown-flag"])
    assert rc == 0
    assert seen["argv"] == ["cisco-assess", "--no-collect", "--totally-unknown-flag"]


def test_main_calls_freeze_support_before_engine_dispatch(monkeypatch):
    """PyInstaller multiprocessing children re-enter main(); freeze_support() must run before any
    dispatch or the child re-executes the whole app."""
    calls = []
    monkeypatch.setattr(serve.multiprocessing, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(serve, "_load_engine_main",
                        lambda: lambda: (calls.append("engine"), 0)[1])
    monkeypatch.setattr(sys, "argv", ["atlas"])
    assert serve.main([serve.ENGINE_SENTINEL]) == 0
    assert calls == ["freeze", "engine"]


# ── entry module: production server invocation ──────────────────────────────────
def _fake_uvicorn(rec: dict):
    return types.SimpleNamespace(run=lambda app, **kw: rec.update(app=app, kw=kw))


def test_main_serves_app_object_without_reload_or_workers(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setitem(sys.modules, "uvicorn", _fake_uvicorn(rec))
    monkeypatch.setattr(serve, "_schedule_browser_open", lambda url: rec.setdefault("browser", url))
    rc = serve.main(["--db", str(tmp_path / "a.db"), "--port", "8123", "--no-browser"])
    assert rc == 0
    from fastapi import FastAPI

    assert isinstance(rec["app"], FastAPI)  # object, not an import string: reload is impossible
    assert "reload" not in rec["kw"] and "workers" not in rec["kw"]
    assert rec["kw"]["host"] == "127.0.0.1" and rec["kw"]["port"] == 8123
    assert "browser" not in rec  # --no-browser honoured


def test_main_schedules_browser_open_by_default(monkeypatch, tmp_path):
    rec = {}
    monkeypatch.setitem(sys.modules, "uvicorn", _fake_uvicorn(rec))
    monkeypatch.setattr(serve, "_schedule_browser_open", lambda url: rec.setdefault("browser", url))
    assert serve.main(["--db", str(tmp_path / "a.db"), "--port", "8124"]) == 0
    assert rec["browser"] == "http://127.0.0.1:8124/"


def test_version_flag_prints_brand_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        serve.main(["--version"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "Atlas" in out and "Tanveer Ahamed" in out
    # From a checkout the version must be the CHECKOUT's pyproject release, never the (possibly
    # stale) pip-installed dist metadata — the installed-vs-worktree confusion class.
    assert "(checkout)" in out


def test_brand_tokens_own_the_app_identity():
    """ADR-0004 D1: the name lives in ONE brand constant — a rename is a one-line change there."""
    from cisco_toolkit import brand_tokens as bt

    assert bt.APP_NAME == "Atlas"
    assert bt.APP_BYLINE == "by Tanveer Ahamed"
    assert bt.APP_NAME in bt.APP_TITLE and bt.APP_BYLINE in bt.APP_TITLE


# ── --selftest: fail LOUD on the silent-degrade assets ──────────────────────────
def test_selftest_green_on_dev_checkout(tmp_path, capsys):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>", encoding="utf-8")
    rc = serve.run_selftest(dist_dir=dist, db_path=str(tmp_path / "data" / "hub.db"))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS" in out


def test_selftest_fails_loud_on_missing_frontend_dist(tmp_path, capsys):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    rc = serve.run_selftest(dist_dir=tmp_path / "nodist", db_path=str(tmp_path / "a.db"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "frontend" in out.lower()


def test_selftest_fails_when_explorer_template_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(serve, "_explorer_template_path", lambda: tmp_path / "absent.html")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>", encoding="utf-8")
    rc = serve.run_selftest(dist_dir=dist, db_path=str(tmp_path / "a.db"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "explorer" in out.lower()


def test_selftest_fails_when_oui_kb_degraded(monkeypatch, tmp_path, capsys):
    """The OUI pack silently degrades to ''-lookups when the tsv.gz is missing — exactly the class
    --selftest exists to catch. Simulate the degrade at the lookup the check probes."""
    from cisco_toolkit import ouidb

    monkeypatch.setattr(ouidb, "vendor_for_mac", lambda mac: "")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>", encoding="utf-8")
    rc = serve.run_selftest(dist_dir=dist, db_path=str(tmp_path / "a.db"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "oui" in out.lower()


def test_selftest_flag_exits_with_failure_code(tmp_path):
    rc = serve.main(["--selftest", "--dist", str(tmp_path / "nodist"),
                     "--db", str(tmp_path / "a.db")])
    assert rc == 1


# ── create_app(dist_dir=…): the frozen/package serving hook ─────────────────────
def test_create_app_serves_provided_dist_dir(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ATLAS-DIST-MARKER</html>", encoding="utf-8")
    (dist / "assets" / "x.js").write_text("js-payload", encoding="utf-8")
    app = create_app(db_path=str(tmp_path / "t.db"), dist_dir=str(dist))
    with TestClient(app, base_url="http://localhost") as c:
        assert "ATLAS-DIST-MARKER" in c.get("/campaigns/view/3").text  # deep-link fallback
        assert c.get("/assets/x.js").text == "js-payload"
        # containment survives the parametrisation: an escaping path falls back to index.html
        assert "ATLAS-DIST-MARKER" in c.get("/../../pyproject.toml").text


def test_create_app_missing_dist_dir_stays_api_only(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), dist_dir=str(tmp_path / "never-built"))
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/campaigns").status_code == 200
        assert c.get("/anything").status_code == 404  # no SPA catch-all registered


# ── ingest from folder ──────────────────────────────────────────────────────────
def test_run_collection_folder_happy_path(monkeypatch, tmp_path):
    record = {}
    monkeypatch.setattr(ing.subprocess, "run", _fake_engine_run(record))
    folder = _collection_dir(tmp_path)
    snap, report = ing.run_collection_folder(str(folder))
    assert snap["devices"]
    assert report["n_device_dirs"] == 1 and report["devices"] == ["core1"]
    assert report["devices_json"] == "synthesized"
    # engine reads the user's folder IN PLACE…
    coll = Path(record["cmd"][record["cmd"].index("--collection-dir") + 1])
    assert coll == folder.resolve()
    # …but every output lands in a private temp workdir, never in the user's tree
    assert Path(record["cwd"]).resolve() != folder.resolve()
    assert not (folder / "ingest.xlsx").exists() and not (folder / "devices.json").exists()


def test_run_collection_folder_rejects_missing_or_non_dir(tmp_path):
    with pytest.raises(ing.IngestError):
        ing.run_collection_folder(str(tmp_path / "absent"))
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ing.IngestError):
        ing.run_collection_folder(str(f))


def test_run_collection_folder_enforces_file_count_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(ing, "MAX_FILES", 1)
    folder = _collection_dir(tmp_path)
    (folder / "core1" / "show_interface_status.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ing.IngestError):
        ing.run_collection_folder(str(folder))


def test_ingest_folder_route_stores_snapshot_with_report(client, monkeypatch):
    monkeypatch.setattr(ing, "run_collection_folder",
                        lambda p: ({"devices": {"c1": {}}, "interfaces": [1]},
                                   {"n_device_dirs": 1, "devices": ["c1"]}))
    cid = _campaign(client)
    r = client.post(f"/api/campaigns/{cid}/ingest-folder",
                    json={"path": "C:/collections/siteA", "label": "field run"})
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "field run"
    assert r.json()["ingest"]["n_device_dirs"] == 1


def test_ingest_folder_route_defaults_label_to_folder_name(client, monkeypatch):
    monkeypatch.setattr(ing, "run_collection_folder",
                        lambda p: ({"devices": {"c1": {}}, "interfaces": [1]}, {}))
    cid = _campaign(client)
    r = client.post(f"/api/campaigns/{cid}/ingest-folder", json={"path": "C:/collections/siteA"})
    assert r.status_code == 201
    assert r.json()["label"] == "siteA"


def test_ingest_folder_route_404_unknown_campaign(client, monkeypatch):
    monkeypatch.setattr(ing, "run_collection_folder",
                        lambda p: ({"devices": {"c1": {}}, "interfaces": [1]}, {}))
    assert client.post("/api/campaigns/99999/ingest-folder",
                       json={"path": "C:/x"}).status_code == 404


def test_ingest_folder_route_maps_ingest_error_to_400(client, monkeypatch):
    def _bad(path):
        raise ing.IngestError("not a directory")

    monkeypatch.setattr(ing, "run_collection_folder", _bad)
    cid = _campaign(client)
    r = client.post(f"/api/campaigns/{cid}/ingest-folder", json={"path": "C:/nope"})
    assert r.status_code == 400
    assert "directory" in r.json()["detail"]


def test_ingest_folder_route_blocks_cross_site_writes(client):
    """The new POST must sit behind the same blind-CSRF guard as every other write — a cross-site
    request dies at the middleware, before the path is even looked at."""
    r = client.post("/api/campaigns/1/ingest-folder", json={"path": "C:/x"},
                    headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
