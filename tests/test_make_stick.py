r"""portable/make_stick.ps1 — the stick layout/update script (ADR-0004 P2/P3).

The field-critical promise under test: an UPDATE replaces the app wholesale but NEVER touches the
top-level data\ (client evidence) — while nested dirs that happen to be named 'data'
(_internal\cisco_toolkit\data — the KB packs) still copy. A bare robocopy '/XD data' violates the
second half silently; the script pins the exclusion to the absolute top-level path."""

import contextlib
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows-only stick layout script (robocopy/powershell)")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "portable" / "make_stick.ps1"


def _command(*args: str, skip_selftest: bool = True) -> list[str]:
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        *args,
    ]
    if skip_selftest:
        command.append("-SkipSelftest")
    return command


def _run(*args: str, skip_selftest: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        _command(*args, skip_selftest=skip_selftest),
        capture_output=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=120)


def _fake_bundle(tmp_path: Path) -> Path:
    src = tmp_path / "built" / "Atlas"
    (src / "_internal" / "cisco_toolkit" / "data").mkdir(parents=True)
    (src / "Atlas.exe").write_bytes(b"MZ fake exe")
    (src / "_internal" / "app.pyz").write_bytes(b"payload")
    (src / "_internal" / "cisco_toolkit" / "data" / "oui_registry.tsv.gz").write_bytes(b"kb")
    return src


def _two_versions(tmp_path: Path) -> tuple[Path, Path]:
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"
    (target / "data" / "assesshub.db").write_bytes(b"CLIENT EVIDENCE")
    (target / "data" / "evidence.bin").write_bytes(b"SECOND CLIENT FILE")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")
    (src / "_internal" / "app.pyz").write_bytes(b"payload-v2")
    updated = _run("-Dest", str(dest), "-Source", str(src))
    assert updated.returncode == 0, updated.stdout + updated.stderr
    return src, dest


def _app_tree_hash(root: Path) -> str:
    rows = []
    for path in root.rglob("*"):
        if not path.is_file() or path.relative_to(root).parts[0].casefold() == "data":
            continue
        relative = path.relative_to(root).as_posix()
        rows.append(
            f"{relative}\0{path.stat().st_size}\0{hashlib.sha256(path.read_bytes()).hexdigest()}"
        )
    payload = ("\n".join(sorted(rows)) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_rollback_slot(dest: Path, *, backup_receipt: str = "", backup_sha256: str = "") -> dict:
    active = dest / "Atlas"
    previous = dest / "Atlas.previous"
    slot = {
        "schema": "atlas.portable-rollback-slot/1",
        "status": "prepared",
        "update_run_id": "b" * 32,
        "active_exe_sha256": hashlib.sha256((active / "Atlas.exe").read_bytes()).hexdigest(),
        "active_tree_sha256": _app_tree_hash(active),
        "previous_exe_sha256": hashlib.sha256((previous / "Atlas.exe").read_bytes()).hexdigest(),
        "previous_tree_sha256": _app_tree_hash(previous),
        "database_backup_receipt": backup_receipt,
        "database_backup_receipt_sha256": backup_sha256,
        "candidate_identity": {"kind": "test", "app_tree_sha256": _app_tree_hash(active)},
        "authentication": "none_local_consistency_only",
    }
    (dest / "Atlas.rollback-slot.json").write_text(
        json.dumps(slot, separators=(",", ":")) + "\n", encoding="utf-8",
    )
    return slot


@contextlib.contextmanager
def _no_share_handle(path: Path):
    """Hold a Windows file with share mode zero, including delete/rename denial."""
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise OSError(ctypes.get_last_error(), f"could not lock {path}")
    try:
        yield
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


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
    (target / "data").mkdir(exist_ok=True)
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
    invocation = next(ln.strip() for ln in SCRIPT.read_text(encoding="ascii").splitlines()
                      if ln.strip().startswith("robocopy "))
    assert "/R:" in invocation and "/W:" in invocation, "make_stick.ps1 must pin retry limits"
    retries = int(re.search(r"/R:(\d+)", invocation).group(1))
    wait = int(re.search(r"/W:(\d+)", invocation).group(1))
    assert retries <= 5, f"/R:{retries} is a silent-hang risk in the field"
    assert wait <= 10, f"/W:{wait} is a silent-hang risk in the field"


def test_database_preflight_request_vocabulary_matches_frozen_owner():
    from webapp.backend import serve

    text = SCRIPT.read_text(encoding="ascii")
    assert f'$env:{serve.DATABASE_PREFLIGHT_ENV}' in text
    assert f'"{serve.DATABASE_PREFLIGHT_MARKER}"' in text
    for token in (
        "atlas.database-preflight-request/1",
        "schema", "nonce", "database_name", "input_copy_sha256", "input_copy_bytes",
        "requested_action", "request_sha256", "request_nonce", "input_copy_binding",
        "caller_supplied_database_modified", "authority_effect",
    ):
        assert token in text


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

    # The failure may occur after data moved into the staged tree. A retry must recover it before
    # doing any new work, then complete the same update without losing a byte.
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr


@pytest.mark.parametrize(
    "phase",
    [
        "staging", "staged", "prepared", "data_moved", "active_moved", "activated",
        "data_attach_pending", "data_attached",
        "rollback_slot_prepared", "rollback_slot_receipted",
    ],
)
def test_interruption_at_every_activation_checkpoint_recovers_old_or_new(tmp_path, phase):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"
    (target / "data" / "assesshub.db").write_bytes(b"CLIENT EVIDENCE")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")
    (src / "_internal" / "app.pyz").write_bytes(b"payload-v2")

    interrupted = _run(
        "-Dest", str(dest), "-Source", str(src), "-TestFailAfter", phase,
    )
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    # At every checkpoint a complete old or complete new executable tree is present or the
    # journal names the recoverable incoming/previous pair. A retry must converge to new.
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe v2"
    assert (target / "_internal" / "app.pyz").read_bytes() == b"payload-v2"
    assert (target / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert not (dest / "Atlas.update-state.json").exists()
    assert not (dest / "Atlas.incoming").exists()


def test_explicit_rollback_switches_complete_tree_and_preserves_data(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    target = dest / "Atlas"
    (target / "data" / "assesshub.db").write_bytes(b"CLIENT EVIDENCE")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe v2"

    rolled = _run("-Dest", str(dest), "-Rollback")
    assert rolled.returncode == 0, rolled.stdout + rolled.stderr
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe"
    assert (target / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert list(dest.glob("Atlas.failed-*")), "newer app tree should be retained for evidence"


@pytest.mark.parametrize(
    "phase", [
        "staging", "staged", "prepared", "data_moved", "active_moved", "activated",
        "data_attach_pending", "data_attached",
    ],
)
def test_first_install_interruption_recovers_and_retries(tmp_path, phase):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    interrupted = _run(
        "-Dest", str(dest), "-Source", str(src), "-TestFailAfter", phase,
    )
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (dest / "Atlas" / "Atlas.exe").read_bytes() == b"MZ fake exe"
    assert (dest / "Atlas" / "_internal" / "app.pyz").read_bytes() == b"payload"
    assert (dest / "Atlas" / "data").is_dir()
    assert not (dest / "Atlas.incoming").exists()
    assert not (dest / "Atlas.update-state.json").exists()


@pytest.mark.parametrize(
    "phase",
    [
        "rollback_prepared",
        "rollback_data_moved",
        "rollback_database_restored",
        "rollback_active_moved",
        "rollback_activated",
        "rollback_data_attached",
    ],
)
def test_rollback_interruption_recovers_without_losing_data(tmp_path, phase):
    _src, dest = _two_versions(tmp_path)
    interrupted = _run("-Dest", str(dest), "-Rollback", "-TestFailAfter", phase)
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    retry = _run("-Dest", str(dest), "-Rollback")
    assert retry.returncode == 0, retry.stdout + retry.stderr
    target = dest / "Atlas"
    assert (target / "Atlas.exe").read_bytes() == b"MZ fake exe"
    assert (target / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert (target / "data" / "evidence.bin").read_bytes() == b"SECOND CLIENT FILE"
    assert not (dest / "Atlas.update-state.json").exists()


def test_staging_failure_keeps_existing_rollback_slot(tmp_path):
    src, dest = _two_versions(tmp_path)
    prior = dest / "Atlas.previous"
    prior_rows = {
        path.relative_to(prior).as_posix(): path.read_bytes()
        for path in prior.rglob("*") if path.is_file()
    }
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v3")
    locked = src / "_internal" / "app.pyz"
    locked.write_bytes(b"payload-v3")
    with _no_share_handle(locked):
        failed = _run("-Dest", str(dest), "-Source", str(src))
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert {
        path.relative_to(prior).as_posix(): path.read_bytes()
        for path in prior.rglob("*") if path.is_file()
    } == prior_rows
    assert (dest / "Atlas" / "Atlas.exe").read_bytes() == b"MZ fake exe v2"


def test_interruption_after_previous_retirement_restores_then_updates(tmp_path):
    src, dest = _two_versions(tmp_path)
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v3")
    (src / "_internal" / "app.pyz").write_bytes(b"payload-v3")
    interrupted = _run(
        "-Dest", str(dest), "-Source", str(src),
        "-TestFailAfter", "previous_retired",
    )
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    assert (dest / "Atlas.retired" / "Atlas.exe").read_bytes() == b"MZ fake exe"
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (dest / "Atlas" / "Atlas.exe").read_bytes() == b"MZ fake exe v3"
    assert (dest / "Atlas.previous" / "Atlas.exe").read_bytes() == b"MZ fake exe v2"
    assert (dest / "Atlas" / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert not (dest / "Atlas.retired").exists()


def test_identical_candidate_activation_recovery_uses_topology_not_exe_hash(tmp_path):
    src, dest = _two_versions(tmp_path)
    interrupted = _run(
        "-Dest", str(dest), "-Source", str(src), "-TestFailAfter", "activated",
    )
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (dest / "Atlas" / "Atlas.exe").read_bytes() == b"MZ fake exe v2"
    assert (dest / "Atlas" / "_internal" / "app.pyz").read_bytes() == b"payload-v2"
    assert (dest / "Atlas" / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert not (dest / "Atlas.update-state.json").exists()
    assert not (dest / "Atlas.retired").exists()


def test_data_directory_move_is_atomic_when_a_child_is_locked(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(src)).returncode == 0
    data = dest / "Atlas" / "data"
    (data / "one.bin").write_bytes(b"ONE")
    (data / "two.bin").write_bytes(b"TWO")
    (src / "Atlas.exe").write_bytes(b"MZ fake exe v2")
    with _no_share_handle(data / "two.bin"):
        failed = _run("-Dest", str(dest), "-Source", str(src))
        assert failed.returncode == 1, failed.stdout + failed.stderr
        assert (data / "one.bin").read_bytes() == b"ONE"
        assert (data / "two.bin").is_file()
        assert not (dest / "Atlas.incoming" / "data").exists()
    assert (data / "two.bin").read_bytes() == b"TWO"
    retry = _run("-Dest", str(dest), "-Source", str(src))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (dest / "Atlas" / "data" / "one.bin").read_bytes() == b"ONE"
    assert (dest / "Atlas" / "data" / "two.bin").read_bytes() == b"TWO"


def test_destination_lock_refuses_a_second_updater(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    first = subprocess.Popen(
        _command(
            "-Dest", str(dest), "-Source", str(src),
            "-TestHoldLockMilliseconds", "2000",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (dest / ".Atlas.update.lock").exists():
            time.sleep(0.02)
        time.sleep(0.15)
        second = _run("-Dest", str(dest), "-Source", str(src))
        stdout, stderr = first.communicate(timeout=30)
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=10)
    assert first.returncode == 0, stdout + stderr
    assert second.returncode == 1
    assert "destination lock" in (second.stdout + second.stderr).lower()
    assert (dest / "Atlas" / "_internal" / "app.pyz").read_bytes() == b"payload"


def test_unreceipted_future_named_database_is_never_restored(tmp_path):
    _src, dest = _two_versions(tmp_path)
    data = dest / "Atlas" / "data"
    backup_root = data / "release-backups"
    backup_root.mkdir()
    (backup_root / "pre-update-99999999999999999999999999999999.db").write_bytes(
        b"UNVERIFIED INJECTED DATABASE"
    )
    result = _run("-Dest", str(dest), "-Rollback", "-RestorePreUpdateDatabase")
    assert result.returncode == 1
    assert "no verified pre-update" in (result.stdout + result.stderr).lower()
    assert (dest / "Atlas" / "data" / "assesshub.db").read_bytes() == b"CLIENT EVIDENCE"
    assert (dest / "Atlas" / "Atlas.exe").read_bytes() == b"MZ fake exe v2"


def test_hash_bound_database_restore_preserves_newer_database(tmp_path):
    _src, dest = _two_versions(tmp_path)
    data = dest / "Atlas" / "data"
    backup_root = data / "release-backups"
    backup_root.mkdir()
    run_id = "a" * 32
    backup_name = f"pre-update-{run_id}.db"
    backup = backup_root / backup_name
    backup.write_bytes(b"OLD PRE-UPDATE DATABASE")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    previous_hash = hashlib.sha256((dest / "Atlas.previous" / "Atlas.exe").read_bytes()).hexdigest()
    slot = json.loads((dest / "Atlas.rollback-slot.json").read_text(encoding="utf-8"))
    receipt = {
        "schema": "atlas.pre-update-database-backup/1",
        "run_id": run_id,
        "created_at": "2026-09-05T00:00:00Z",
        "backup_name": backup_name,
        "bytes": backup.stat().st_size,
        "sha256": digest,
        "source_database_sha256": digest,
        "previous_exe_sha256": previous_hash,
        "candidate_identity": slot["candidate_identity"],
        "authentication": "none_local_consistency_only",
    }
    receipt_path = backup_root / f"pre-update-{run_id}.json"
    receipt_path.write_text(
        json.dumps(receipt, separators=(",", ":")) + "\n", encoding="utf-8",
    )
    slot["update_run_id"] = run_id
    slot["database_backup_receipt"] = receipt_path.name
    slot["database_backup_receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (dest / "Atlas.rollback-slot.json").write_text(
        json.dumps(slot, separators=(",", ":")) + "\n", encoding="utf-8",
    )
    result = _run("-Dest", str(dest), "-Rollback", "-RestorePreUpdateDatabase")
    assert result.returncode == 0, result.stdout + result.stderr
    active_data = dest / "Atlas" / "data"
    assert (active_data / "assesshub.db").read_bytes() == b"OLD PRE-UPDATE DATABASE"
    preserved = list((active_data / "release-backups").glob("rollback-preserved-*.db"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == b"CLIENT EVIDENCE"


def test_restore_database_flag_requires_rollback(tmp_path):
    src = _fake_bundle(tmp_path)
    dest = tmp_path / "stick"
    dest.mkdir()
    result = _run(
        "-Dest", str(dest), "-Source", str(src), "-RestorePreUpdateDatabase",
    )
    assert result.returncode == 1
    assert "requires -Rollback" in result.stdout + result.stderr
    assert not (dest / "Atlas").exists()


def test_source_reparse_point_is_refused_before_staging(tmp_path):
    src = _fake_bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.bin").write_bytes(b"OUTSIDE")
    link = src / "_internal" / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        link_ps = str(link).replace("'", "''")
        outside_ps = str(outside).replace("'", "''")
        junction = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                f"New-Item -ItemType Junction -Path '{link_ps}' -Target '{outside_ps}' | Out-Null",
            ],
            capture_output=True, text=True, check=False,
        )
        if junction.returncode:
            pytest.skip(f"directory reparse creation unavailable: {exc}; {junction.stderr}")
    dest = tmp_path / "stick"
    dest.mkdir()
    result = _run("-Dest", str(dest), "-Source", str(src))
    assert result.returncode == 1
    assert "reparse" in (result.stdout + result.stderr).lower()
    assert not (dest / "Atlas").exists()
    assert (outside / "payload.bin").read_bytes() == b"OUTSIDE"


def _compile_test_exe(source: Path, output: Path) -> None:
    framework = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not framework.is_file():
        pytest.skip(".NET Framework csc.exe is unavailable")
    result = subprocess.run(
        [str(framework), "/nologo", "/target:exe", "/platform:x64", f"/out:{output}", str(source)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _protocol_bundle(tmp_path: Path, *, fail_in_atlas: bool = False) -> Path:
    bundle = tmp_path / "protocol-bundle"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "_internal" / "version.txt").write_text("v1", encoding="ascii")
    source = tmp_path / "protocol-atlas.cs"
    program = r'''using System;
using System.IO;
using System.Security.Cryptography;
class P {
  static string H(byte[] b) {
    using (SHA256 s = SHA256.Create()) {
      return BitConverter.ToString(s.ComputeHash(b)).Replace("-", "").ToLowerInvariant();
    }
  }
  static int Main(string[] a) {
    if (Array.IndexOf(a, "--selftest") >= 0) {
      /*PATH_GUARD*/
      Console.WriteLine("SELFTEST: PASS");
      return 0;
    }
    int i = Array.IndexOf(a, "--database-preflight");
    if (i >= 0 && i + 1 < a.Length) {
      string db = a[i + 1];
      string marker = Path.Combine(Path.GetDirectoryName(db), "atlas-db-preflight.json");
      byte[] d = File.ReadAllBytes(db);
      byte[] m = File.ReadAllBytes(marker);
      string n = Environment.GetEnvironmentVariable("ATLAS_PORTABLE_DATABASE_PREFLIGHT") ?? "";
      string dh = H(d);
      Console.WriteLine("{\"authority_effect\":\"NONE\",\"caller_supplied_database_modified\":false," +
        "\"input_copy_binding\":{\"bytes\":" + d.Length + ",\"database_name\":\"assesshub.db\",\"sha256\":\"" + dh + "\"}," +
        "\"migrated_copy_bytes\":" + d.Length + ",\"migrated_copy_sha256\":\"" + dh + "\"," +
        "\"quick_check\":\"ok\",\"request_nonce\":\"" + n + "\",\"request_sha256\":\"" + H(m) + "\"," +
        "\"row_counts\":{},\"schema\":\"atlas.database-preflight/1\",\"status\":\"pass\"}");
      return 0;
    }
    return 0;
  }
}'''
    path_guard = ""
    if fail_in_atlas:
        path_guard = (
            "string leaf=new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\')).Name; "
            "if (String.Equals(leaf, \"Atlas\", StringComparison.OrdinalIgnoreCase)) return 7;"
        )
    source.write_text(program.replace("/*PATH_GUARD*/", path_guard), encoding="ascii")
    _compile_test_exe(source, bundle / "Atlas.exe")
    return bundle


def _protocol_two_versions(tmp_path: Path) -> tuple[Path, Path]:
    src = _protocol_bundle(tmp_path)
    dest = tmp_path / "protocol-stick"
    dest.mkdir()
    first = _run("-Dest", str(dest), "-Source", str(src), skip_selftest=False)
    assert first.returncode == 0, first.stdout + first.stderr
    data = dest / "Atlas" / "data"
    (data / "assesshub.db").write_bytes(b"CURRENT DATABASE BYTES")
    (data / "evidence.bin").write_bytes(b"CLIENT EVIDENCE")
    (src / "_internal" / "version.txt").write_text("v2", encoding="ascii")
    update = _run("-Dest", str(dest), "-Source", str(src), skip_selftest=False)
    assert update.returncode == 0, update.stdout + update.stderr
    return src, dest


def test_real_updater_preflight_protocol_creates_bound_backup_and_slot(tmp_path):
    _src, dest = _protocol_two_versions(tmp_path)
    data = dest / "Atlas" / "data"
    backups = list((data / "release-backups").glob("pre-update-*.db"))
    receipts = list((data / "release-backups").glob("pre-update-*.json"))
    assert len(backups) == len(receipts) == 1
    assert backups[0].read_bytes() == b"CURRENT DATABASE BYTES"
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["sha256"] == hashlib.sha256(backups[0].read_bytes()).hexdigest()
    slot = json.loads((dest / "Atlas.rollback-slot.json").read_text(encoding="utf-8"))
    assert slot["database_backup_receipt"] == receipts[0].name
    assert slot["database_backup_receipt_sha256"] == hashlib.sha256(receipts[0].read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "phase",
    [
        "rollback_prepared",
        "rollback_data_moved",
        "rollback_database_restored",
        "rollback_active_moved",
        "rollback_activated",
        "rollback_data_attached",
    ],
)
def test_receipted_database_restore_survives_every_rollback_interruption(tmp_path, phase):
    _src, dest = _protocol_two_versions(tmp_path)
    active_db = dest / "Atlas" / "data" / "assesshub.db"
    active_db.write_bytes(b"NEWER POST-UPDATE DATABASE")
    interrupted = _run(
        "-Dest", str(dest), "-Rollback", "-RestorePreUpdateDatabase",
        "-TestFailAfter", phase, skip_selftest=False,
    )
    assert interrupted.returncode == 70, interrupted.stdout + interrupted.stderr
    retry = _run(
        "-Dest", str(dest), "-Rollback", "-RestorePreUpdateDatabase", skip_selftest=False,
    )
    assert retry.returncode == 0, retry.stdout + retry.stderr
    data = dest / "Atlas" / "data"
    assert (data / "assesshub.db").read_bytes() == b"CURRENT DATABASE BYTES"
    preserved = list((data / "release-backups").glob("rollback-preserved-*.db"))
    assert preserved
    assert all(path.read_bytes() == b"NEWER POST-UPDATE DATABASE" for path in preserved)


def test_failed_receipted_database_rollback_restores_newer_active_database(tmp_path):
    _src, dest = _protocol_two_versions(tmp_path)
    active = dest / "Atlas"
    previous = dest / "Atlas.previous"
    active_db = active / "data" / "assesshub.db"
    active_db.write_bytes(b"NEWER POST-UPDATE DATABASE")

    failing = _protocol_bundle(tmp_path / "failing", fail_in_atlas=True)
    shutil.copy2(failing / "Atlas.exe", previous / "Atlas.exe")
    slot_path = dest / "Atlas.rollback-slot.json"
    slot = json.loads(slot_path.read_text(encoding="utf-8"))
    receipt_path = active / "data" / "release-backups" / slot["database_backup_receipt"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    previous_exe_hash = hashlib.sha256((previous / "Atlas.exe").read_bytes()).hexdigest()
    receipt["previous_exe_sha256"] = previous_exe_hash
    receipt_path.write_text(json.dumps(receipt, separators=(",", ":")) + "\n", encoding="utf-8")
    slot["previous_exe_sha256"] = previous_exe_hash
    slot["previous_tree_sha256"] = _app_tree_hash(previous)
    slot["database_backup_receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    slot_path.write_text(json.dumps(slot, separators=(",", ":")) + "\n", encoding="utf-8")

    result = _run(
        "-Dest", str(dest), "-Rollback", "-RestorePreUpdateDatabase", skip_selftest=False,
    )
    assert result.returncode == 1
    assert "restored the pre-rollback active tree" in (result.stdout + result.stderr).lower()
    assert (dest / "Atlas" / "data" / "assesshub.db").read_bytes() == b"NEWER POST-UPDATE DATABASE"
    assert (dest / "Atlas" / "_internal" / "version.txt").read_text(encoding="ascii") == "v2"
    assert (dest / "Atlas.previous" / "Atlas.exe").read_bytes() == (failing / "Atlas.exe").read_bytes()
    assert not (dest / "Atlas.update-state.json").exists()


def _release_package(tmp_path: Path) -> Path:
    from portable import release_contract as release

    repository = tmp_path / "package-repo"
    repository.mkdir()
    environment = dict(os.environ)
    environment.update({
        "GIT_AUTHOR_NAME": "Atlas Test",
        "GIT_AUTHOR_EMAIL": "atlas@example.invalid",
        "GIT_COMMITTER_NAME": "Atlas Test",
        "GIT_COMMITTER_EMAIL": "atlas@example.invalid",
    })

    def git(*args: str) -> None:
        result = subprocess.run(
            ["git", *args], cwd=repository, env=environment,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr

    git("init", "-q")
    git("remote", "add", "origin", "https://example.invalid/owner/atlas.git")
    (repository / "pyproject.toml").write_text(
        '[project]\nname="atlas-package-test"\nversion="9.9.9"\n', encoding="utf-8",
    )
    (repository / "webapp" / "frontend").mkdir(parents=True)
    (repository / "webapp" / "frontend" / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (repository / "portable").mkdir()
    (repository / "portable" / "windows-x64-requirements.lock").write_text("# fixture\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "fixture")

    bundle = tmp_path / "package-bundle"
    (bundle / "_internal").mkdir(parents=True)
    source = tmp_path / "package-atlas.cs"
    source.write_text(
        "using System; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) Console.WriteLine(\"SELFTEST: PASS\"); return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, bundle / "Atlas.exe")
    (bundle / "README-FIELD.txt").write_text("ATLAS FIELD GUIDE\n", encoding="ascii")
    (bundle / "LICENSE").write_text("fixture license\n", encoding="ascii")
    (bundle / "_internal" / "runtime.bin").write_bytes(b"runtime")
    source_identity = release.source_identity(repository)
    qualification = {
        "schema": release.QUALIFICATION_SCHEMA,
        "status": "AUTOMATED_PASS_EXTERNAL_GATES_PENDING",
        "source": source_identity,
        "bundle_member_set_digest": release.digest_object(release.collect_members(bundle)),
        "checks": [
            {"id": name, "status": "pass"}
            for name in sorted(release.REQUIRED_AUTOMATED_CHECKS)
        ],
        "pyinstaller_warning_report": {
            "raw_bytes": 0,
            "raw_sha256": hashlib.sha256(b"").hexdigest(),
            "sanitized_content": "synthetic warning fixture\n",
            "sanitized_bytes": len(b"synthetic warning fixture\n"),
            "sanitized_sha256": hashlib.sha256(b"synthetic warning fixture\n").hexdigest(),
            "nonblank_lines": 1,
            "status": "disclosed_optional_import_report_not_silently_discarded",
            "sanitization": "known build roots replaced; LF-normalized; remaining drive paths refused",
            "builder_console_log": release.WARNING_LOG_BOUNDARY,
        },
        "python_absence_evidence": release.PYTHON_ABSENCE_BOUNDARY,
        "internet_absence_evidence": release.INTERNET_ABSENCE_BOUNDARY,
        "field_qualified": False,
        "external_pending": sorted(release.REQUIRED_EXTERNAL_GATES),
    }
    output = tmp_path / "package-output"
    index = release.build_portable_release(repository, bundle, output, qualification)
    return output / index["zip"]["name"]


def test_release_package_is_copied_verified_extracted_and_reverified(tmp_path):
    package = _release_package(tmp_path)
    dest = tmp_path / "package-stick"
    dest.mkdir()
    result = _run("-Dest", str(dest), "-Package", str(package), skip_selftest=False)
    assert result.returncode == 0, result.stdout + result.stderr
    target = dest / "Atlas"
    assert (target / "Atlas.exe").is_file()
    assert (target / "release-metadata" / "SHA256SUMS").is_file()
    assert (target / "data").is_dir()
    assert not (dest / ".Atlas.update-package.zip").exists()
    assert not (dest / ".Atlas.update-extract").exists()


def test_path_sensitive_rollback_failure_restores_original_tree_and_data(tmp_path):
    dest = tmp_path / "stick"
    active = dest / "Atlas"
    previous = dest / "Atlas.previous"
    (active / "_internal").mkdir(parents=True)
    (previous / "_internal").mkdir(parents=True)
    (active / "data").mkdir()
    (active / "data" / "evidence.bin").write_bytes(b"CLIENT")
    active_source = tmp_path / "active.cs"
    active_source.write_text(
        "using System; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) Console.WriteLine(\"SELFTEST: PASS\"); return 0; } }",
        encoding="ascii",
    )
    rollback_source = tmp_path / "rollback.cs"
    rollback_source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") < 0) return 0; "
        "string n=new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\')).Name; "
        "if (String.Equals(n, \"Atlas\", StringComparison.OrdinalIgnoreCase)) return 7; "
        "Console.WriteLine(\"SELFTEST: PASS\"); return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(active_source, active / "Atlas.exe")
    _compile_test_exe(rollback_source, previous / "Atlas.exe")
    (active / "_internal" / "version.txt").write_text("active", encoding="ascii")
    (previous / "_internal" / "version.txt").write_text("rollback", encoding="ascii")
    active_hash = hashlib.sha256((active / "Atlas.exe").read_bytes()).hexdigest()
    _write_rollback_slot(dest)

    result = _run("-Dest", str(dest), "-Rollback", skip_selftest=False)
    assert result.returncode == 1
    assert "restored the pre-rollback active tree" in (result.stdout + result.stderr).lower()
    assert hashlib.sha256((active / "Atlas.exe").read_bytes()).hexdigest() == active_hash
    assert (active / "_internal" / "version.txt").read_text(encoding="ascii") == "active"
    assert (active / "data" / "evidence.bin").read_bytes() == b"CLIENT"
    assert (previous / "_internal" / "version.txt").read_text(encoding="ascii") == "rollback"
    assert not (dest / "Atlas.update-state.json").exists()


def test_hung_candidate_is_terminated_and_destination_lock_is_released(tmp_path):
    src = tmp_path / "slow" / "Atlas"
    (src / "_internal").mkdir(parents=True)
    source = tmp_path / "slow.cs"
    source.write_text(
        "using System; using System.Threading; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) Thread.Sleep(10000); return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, src / "Atlas.exe")
    dest = tmp_path / "slow-stick"
    dest.mkdir()
    started = time.monotonic()
    result = _run(
        "-Dest", str(dest), "-Source", str(src),
        "-TestProcessTimeoutSeconds", "1", skip_selftest=False,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 1
    assert "timed out after 1 seconds" in (result.stdout + result.stderr).lower()
    assert elapsed < 8

    good = _fake_bundle(tmp_path / "good")
    retry = _run("-Dest", str(dest), "-Source", str(good))
    assert retry.returncode == 0, retry.stdout + retry.stderr


def test_first_install_final_selftest_failure_never_leaves_failing_active_tree(tmp_path):
    src = tmp_path / "path-sensitive" / "bundle"
    (src / "_internal").mkdir(parents=True)
    source = tmp_path / "first-path-sensitive.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") < 0) return 0; "
        "string n=new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\')).Name; "
        "if (String.Equals(n, \"Atlas\", StringComparison.OrdinalIgnoreCase)) return 7; "
        "Console.WriteLine(\"SELFTEST: PASS\"); return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, src / "Atlas.exe")
    dest = tmp_path / "first-path-stick"
    dest.mkdir()
    result = _run("-Dest", str(dest), "-Source", str(src), skip_selftest=False)
    assert result.returncode == 1
    assert not (dest / "Atlas").exists()
    assert not (dest / "Atlas.update-state.json").exists()
    failed = list(dest.glob("Atlas.failed-update-*"))
    assert len(failed) == 1 and (failed[0] / "Atlas.exe").is_file()


def test_first_install_selftest_created_data_is_quarantined_and_recoverable(tmp_path):
    src = tmp_path / "selftest-data" / "bundle"
    (src / "_internal").mkdir(parents=True)
    source = tmp_path / "selftest-data.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "if (String.Equals(new DirectoryInfo(root).Name, \"Atlas\", StringComparison.OrdinalIgnoreCase)) { "
        "Directory.CreateDirectory(Path.Combine(root, \"data\")); "
        "File.WriteAllText(Path.Combine(root, \"data\", \"selftest.db\"), \"unexpected\"); } "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, src / "Atlas.exe")
    dest = tmp_path / "selftest-data-stick"
    dest.mkdir()
    result = _run("-Dest", str(dest), "-Source", str(src), skip_selftest=False)
    assert result.returncode == 1
    assert not (dest / "Atlas").exists()
    assert not (dest / "Atlas.update-state.json").exists()
    failed = list(dest.glob("Atlas.failed-update-*"))
    assert len(failed) == 1
    assert (failed[0] / "data" / "selftest.db").read_text() == "unexpected"

    good = _fake_bundle(tmp_path / "replacement")
    retry = _run("-Dest", str(dest), "-Source", str(good))
    assert retry.returncode == 0, retry.stdout + retry.stderr


def _staged_data_creator_bundle(tmp_path: Path) -> Path:
    src = tmp_path / "staged-data" / "bundle"
    (src / "_internal").mkdir(parents=True)
    source = tmp_path / "staged-data.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "Directory.CreateDirectory(Path.Combine(root, \"data\")); "
        "File.WriteAllText(Path.Combine(root, \"data\", \"selftest.db\"), \"candidate-owned\"); "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, src / "Atlas.exe")
    return src


def test_staged_selftest_data_is_quarantined_on_first_install(tmp_path):
    bad = _staged_data_creator_bundle(tmp_path)
    dest = tmp_path / "staged-first-stick"
    dest.mkdir()
    first = _run("-Dest", str(dest), "-Source", str(bad), skip_selftest=False)
    assert first.returncode == 1
    assert (dest / "Atlas.incoming" / "data" / "selftest.db").is_file()

    good = _fake_bundle(tmp_path / "clean-first")
    retry = _run("-Dest", str(dest), "-Source", str(good))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    quarantined = list(dest.glob("Atlas.failed-update-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "data" / "selftest.db").read_text() == "candidate-owned"


def test_staged_selftest_data_never_displaces_existing_client_data(tmp_path):
    good = _fake_bundle(tmp_path / "base")
    dest = tmp_path / "staged-update-stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(good)).returncode == 0
    evidence = dest / "Atlas" / "data" / "evidence.bin"
    evidence.write_bytes(b"CLIENT")
    bad = _staged_data_creator_bundle(tmp_path / "bad-update")
    failed = _run("-Dest", str(dest), "-Source", str(bad), skip_selftest=False)
    assert failed.returncode == 1
    assert evidence.read_bytes() == b"CLIENT"

    (good / "Atlas.exe").write_bytes(b"MZ clean v2")
    retry = _run("-Dest", str(dest), "-Source", str(good))
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert (dest / "Atlas" / "data" / "evidence.bin").read_bytes() == b"CLIENT"


def test_successful_selftest_that_mutates_candidate_is_quarantined(tmp_path):
    src = tmp_path / "mutating" / "bundle"
    (src / "_internal").mkdir(parents=True)
    source = tmp_path / "mutating.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "if (String.Equals(new DirectoryInfo(root).Name, \"Atlas\", StringComparison.OrdinalIgnoreCase)) "
        "File.WriteAllText(Path.Combine(root, \"_internal\", \"post-verify-mutation.bin\"), \"changed\"); "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, src / "Atlas.exe")
    dest = tmp_path / "mutating-stick"
    dest.mkdir()
    result = _run("-Dest", str(dest), "-Source", str(src), skip_selftest=False)
    assert result.returncode == 1
    assert "application member set changed" in (result.stdout + result.stderr).lower()
    assert not (dest / "Atlas").exists()
    failed = list(dest.glob("Atlas.failed-update-*"))
    assert len(failed) == 1
    assert (failed[0] / "_internal" / "post-verify-mutation.bin").read_text() == "changed"
    assert not (dest / "Atlas.update-state.json").exists()


def test_candidate_never_executes_adjacent_to_client_data(tmp_path):
    base = _fake_bundle(tmp_path)
    dest = tmp_path / "detached-data-stick"
    dest.mkdir()
    assert _run("-Dest", str(dest), "-Source", str(base)).returncode == 0
    evidence = dest / "Atlas" / "data" / "evidence.bin"
    evidence.write_bytes(b"ORIGINAL CLIENT EVIDENCE")

    candidate = tmp_path / "data-mutator"
    (candidate / "_internal").mkdir(parents=True)
    source = tmp_path / "data-mutator.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "string data=Path.Combine(root, \"data\"); "
        "if (Directory.Exists(data)) File.WriteAllText(Path.Combine(data, \"evidence.bin\"), \"MUTATED\"); "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, candidate / "Atlas.exe")
    result = _run("-Dest", str(dest), "-Source", str(candidate), skip_selftest=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (dest / "Atlas" / "data" / "evidence.bin").read_bytes() == b"ORIGINAL CLIENT EVIDENCE"


def test_rollback_candidate_never_executes_adjacent_to_client_data(tmp_path):
    _src, dest = _two_versions(tmp_path)
    data = dest / "Atlas" / "data"
    (data / "assesshub.db").unlink()
    evidence = data / "evidence.bin"
    evidence.write_bytes(b"ORIGINAL CLIENT EVIDENCE")

    previous = dest / "Atlas.previous"
    source = tmp_path / "rollback-data-mutator.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "string data=Path.Combine(root, \"data\"); "
        "if (Directory.Exists(data)) File.WriteAllText(Path.Combine(data, \"evidence.bin\"), \"MUTATED\"); "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, previous / "Atlas.exe")
    slot_path = dest / "Atlas.rollback-slot.json"
    slot = json.loads(slot_path.read_text(encoding="utf-8"))
    slot["previous_exe_sha256"] = hashlib.sha256((previous / "Atlas.exe").read_bytes()).hexdigest()
    slot["previous_tree_sha256"] = _app_tree_hash(previous)
    slot_path.write_text(json.dumps(slot, separators=(",", ":")) + "\n", encoding="utf-8")

    result = _run("-Dest", str(dest), "-Rollback", skip_selftest=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (dest / "Atlas" / "data" / "evidence.bin").read_bytes() == b"ORIGINAL CLIENT EVIDENCE"


def test_rollback_candidate_created_data_is_quarantined_and_original_restored(tmp_path):
    _src, dest = _two_versions(tmp_path)
    data = dest / "Atlas" / "data"
    (data / "assesshub.db").unlink()
    evidence = data / "evidence.bin"
    evidence.write_bytes(b"ORIGINAL CLIENT EVIDENCE")

    previous = dest / "Atlas.previous"
    source = tmp_path / "rollback-data-creator.cs"
    source.write_text(
        "using System; using System.IO; class P { static int Main(string[] a) { "
        "if (Array.IndexOf(a, \"--selftest\") >= 0) { "
        "string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\\\'); "
        "if (String.Equals(new DirectoryInfo(root).Name, \"Atlas\", StringComparison.OrdinalIgnoreCase)) { "
        "Directory.CreateDirectory(Path.Combine(root, \"data\")); "
        "File.WriteAllText(Path.Combine(root, \"data\", \"candidate.db\"), \"candidate-owned\"); } "
        "Console.WriteLine(\"SELFTEST: PASS\"); } return 0; } }",
        encoding="ascii",
    )
    _compile_test_exe(source, previous / "Atlas.exe")
    slot_path = dest / "Atlas.rollback-slot.json"
    slot = json.loads(slot_path.read_text(encoding="utf-8"))
    slot["previous_exe_sha256"] = hashlib.sha256((previous / "Atlas.exe").read_bytes()).hexdigest()
    slot["previous_tree_sha256"] = _app_tree_hash(previous)
    slot_path.write_text(json.dumps(slot, separators=(",", ":")) + "\n", encoding="utf-8")

    result = _run("-Dest", str(dest), "-Rollback", skip_selftest=False)
    assert result.returncode == 1
    assert "restored the pre-rollback active tree" in (result.stdout + result.stderr).lower()
    assert (dest / "Atlas" / "data" / "evidence.bin").read_bytes() == b"ORIGINAL CLIENT EVIDENCE"
    quarantined = list(dest.glob("Atlas.failed-rollback-data-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "candidate.db").read_text() == "candidate-owned"
    assert not (dest / "Atlas.update-state.json").exists()
