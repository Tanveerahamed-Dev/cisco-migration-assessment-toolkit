r"""portable/make_stick.ps1 — the stick layout/update script (ADR-0004 P2/P3).

The field-critical promise under test: an UPDATE replaces the app wholesale but NEVER touches the
top-level data\ (client evidence) — while nested dirs that happen to be named 'data'
(_internal\cisco_toolkit\data — the KB packs) still copy. A bare robocopy '/XD data' violates the
second half silently; the script pins the exclusion to the absolute top-level path."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows-only stick layout script (robocopy/powershell)")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "portable" / "make_stick.ps1"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
        capture_output=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=120)


def _fake_bundle(tmp_path: Path) -> Path:
    src = tmp_path / "built" / "Atlas"
    (src / "_internal" / "cisco_toolkit" / "data").mkdir(parents=True)
    (src / "Atlas.exe").write_bytes(b"MZ fake exe")
    (src / "_internal" / "app.pyz").write_bytes(b"payload")
    (src / "_internal" / "cisco_toolkit" / "data" / "oui_registry.tsv.gz").write_bytes(b"kb")
    return src


def test_first_copy_lays_out_atlas_including_nested_data_dirs(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    p = _run("-Dest", str(dest), "-Source", str(src))
    assert p.returncode == 0, p.stdout + p.stderr
    target = dest / "Atlas"
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe"
    # the trap: only the TOP-LEVEL data\ is the writable store — nested KB data dirs MUST copy
    assert (target / "_internal" / "cisco_toolkit" / "data" / "oui_registry.tsv.gz").exists()


def test_update_replaces_app_wholesale_but_never_touches_data(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"

    # field state accumulates: client evidence in data\, plus a stale file an old app version left
    (target / "data").mkdir()
    (target / "data" / "assesshub.db").write_bytes(b"CLIENT EVIDENCE")
    (target / "_internal" / "stale.old").write_bytes(b"from-old-version")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")

    p = _run("-Dest", str(dest), "-Source", str(src))
    assert p.returncode == 0, p.stdout + p.stderr
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe v2"  # app replaced
    assert (target / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"  # SURVIVES
    assert not (target / "_internal" / "stale.old").exists()  # /MIR removed the stale remnant
    assert "data\\ preserved" in p.stdout


def test_missing_bundle_fails_loud_with_build_hint(tmp_path):
    p = _run("-Dest", str(tmp_path), "-Source", str(tmp_path / "never-built"))
    assert p.returncode == 1
    assert "build" in (p.stdout + p.stderr).lower()
