r"""portable/make_stick.ps1 — the stick layout/update script (ADR-0004 P2/P3).

The field-critical promise under test: an UPDATE replaces the app wholesale but NEVER touches the
top-level data\ (client evidence) — while nested dirs that happen to be named 'data'
(_internal\cisco_toolkit\data — the KB packs) still copy. A bare robocopy '/XD data' violates the
second half silently; the script pins the exclusion to the absolute top-level path."""

import re
import subprocess
import sys
import time
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


def test_a_data_dir_in_the_SOURCE_never_overwrites_the_sticks_evidence(tmp_path):
    """The /MIR exclusion protecting `data\\` was pinned on the DESTINATION path only, so it could not
    match a SOURCE `data\\`. That directory exists on the build box the moment anyone double-clicks
    the built `dist\\Atlas\\Atlas.exe` to smoke-check it — the frozen app defaults its store to
    `<exe dir>\\data\\assesshub.db` and writes boot backups beside it. The next `make_stick.ps1` then
    mirrored the DEV BOX's store over the field store and PURGED `data\\backups\\`, under the
    script's own '[ok] ... data\\ preserved - client evidence untouched' line.

    The sibling test above cannot see this: its source bundle has no `data\\`, which is exactly the
    condition under which the destination-only exclusion works."""
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"

    # the stick has been to a client site
    (target / "data" / "backups").mkdir(parents=True)
    (target / "data" / "assesshub.db").write_bytes(b"CLIENT EVIDENCE")
    (target / "data" / "backups" / "b1.db").write_bytes(b"FIELD BACKUP")
    # ...and the bundle was launched in place on the build box, so the SOURCE now has a store too
    (src / "data" / "backups").mkdir(parents=True)
    (src / "data" / "assesshub.db").write_bytes(b"DEV BOX STORE")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")

    p = _run("-Dest", str(dest), "-Source", str(src))
    assert p.returncode == 0, p.stdout + p.stderr
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe v2", "the app must still update"
    assert (target / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE", \
        "the dev box's store overwrote the field evidence the script says it preserved"
    assert (target / "data" / "backups" / "b1.db").read_bytes() == b"FIELD BACKUP", \
        "/MIR purged the rotating backups under data\\"
    # the KB packs that live BELOW _internal must still be mirrored — a name-based '/XD data' would
    # have suppressed those too, which is why the exclusion is path-pinned rather than by name
    assert (target / "_internal" / "cisco_toolkit" / "data" / "oui_registry.tsv.gz").is_file()


def test_missing_bundle_fails_loud_with_build_hint(tmp_path):
    p = _run("-Dest", str(tmp_path), "-Source", str(tmp_path / "never-built"))
    assert p.returncode == 1
    assert "build" in (p.stdout + p.stderr).lower()


def test_robocopy_retries_are_bounded():
    """Robocopy's DEFAULTS are /R:1000000 /W:30 - a million retries 30s apart. Combined with this
    script's quiet switches that is a SILENT ~347-day hang on a single in-use file, which really
    happened (2026-07-21: the browser Atlas opened held DLLs on the stick; the copy sat retrying
    for ~5 hours with no output). The script MUST pin small values."""
    # Read the flags off the INVOCATION line only — the surrounding comment quotes robocopy's
    # awful defaults, and matching those would make this test pass while the script hangs.
    invocation = next(ln for ln in SCRIPT.read_text(encoding="ascii").splitlines()
                      if ln.startswith("robocopy "))
    assert "/R:" in invocation and "/W:" in invocation, "make_stick.ps1 must pin retry limits"
    retries = int(re.search(r"/R:(\d+)", invocation).group(1))
    wait = int(re.search(r"/W:(\d+)", invocation).group(1))
    assert retries <= 5, f"/R:{retries} is a silent-hang risk in the field"
    assert wait <= 10, f"/W:{wait} is a silent-hang risk in the field"


def test_in_use_destination_fails_fast_and_names_the_cause(tmp_path):
    """The field symptom: a file on the stick is held open (Atlas or the browser it opened). The
    script must fail in seconds with an actionable message - never retry into oblivion."""
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")  # force a rewrite of the locked file

    # A plain open() would NOT reproduce this: Python opens with full sharing on Windows, so
    # robocopy copies straight over it. msvcrt.locking takes a real mandatory byte-range lock,
    # which is what makes robocopy fail and retry the way an in-use stick file does.
    import msvcrt

    size = (target / "Atlas.exe").stat().st_size
    held = open(target / "Atlas.exe", "rb+")
    try:
        msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, size)
        start = time.monotonic()
        p = _run("-Dest", str(dest), "-Source", str(src))
        elapsed = time.monotonic() - start
    finally:
        held.close()  # closing releases the lock; an explicit unlock can race the size change

    assert p.returncode == 1, p.stdout + p.stderr
    out = (p.stdout + p.stderr).lower()
    assert "in use" in out and "browser" in out, out
    assert elapsed < 90, f"took {elapsed:.0f}s - retries are not bounded"
