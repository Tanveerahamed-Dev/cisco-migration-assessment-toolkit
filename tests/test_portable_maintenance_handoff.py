"""Adversarial maintenance ownership and durable refusal regressions (hosted gate)."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from portable import maintenance, release_contract
from test_portable_release_contract import _installed_bundle


@contextmanager
def unlocked(_root):
    yield


def entries(root):
    return [(path.relative_to(root).as_posix(), path, path.stat(),
             None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(root.rglob("*")) if "data" not in path.relative_to(root).parts]


def fake_verified(monkeypatch):
    monkeypatch.setattr(release_contract, "verified_application_entries", entries)
    monkeypatch.setattr(release_contract, "verify_installed_bundle", lambda _root: None)
    monkeypatch.setattr(maintenance, "_process_identity", lambda pid: pid + 1000)


def helper_paths(root):
    return sorted(path for path in root.iterdir() if maintenance._HELPER.fullmatch(path.name))


def bound_helper(root, monkeypatch, *, nonce="a" * 32, result_parent=None):
    fake_verified(monkeypatch)
    helper = root / f"Atlas.maintenance-{nonce}"
    atlas = helper / "Atlas"
    atlas.mkdir(parents=True)
    executable = atlas / "Atlas.exe"
    executable.write_bytes(b"synthetic installed application")
    result = (result_parent or root) / f"Atlas.maintenance-result.{nonce}.json"
    request = {"schema": "atlas.maintenance-request/1", "parent_pid": 1, "nonce": nonce,
               "arguments": ["-Dest", str(root), "-Rollback"], "result": str(result)}
    request_path = helper / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    pointer = {"schema": "atlas.maintenance-recovery/1",
               "helper": executable.relative_to(root).as_posix(), "worker_pid": maintenance.os.getpid(),
               "worker_creation": maintenance.os.getpid() + 1000,
               "launcher_pid": 1, "launcher_creation": 1001,
               "helper_exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
               "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "result": str(result)}
    (root / "Atlas.maintenance.json").write_text(json.dumps(pointer), encoding="utf-8")
    return helper, executable, result


def test_real_installed_copy_excludes_data_and_verifies_before_destination_exists(tmp_path):
    source = _installed_bundle(tmp_path)
    data = source / "data"
    data.mkdir()
    (data / "synthetic-evidence.txt").write_bytes(b"preserve original client-shaped bytes")
    destination = tmp_path / "verified-copy"
    maintenance._copy_installed_application(source, destination)
    assert not (destination / "data").exists()
    assert (data / "synthetic-evidence.txt").read_bytes() == b"preserve original client-shaped bytes"
    release_contract.verify_installed_bundle(destination)
    (source / "unmanifested-evidence.txt").write_bytes(b"must never enter helper")
    refused = tmp_path / "refused-copy"
    with pytest.raises(release_contract.PortableReleaseError):
        maintenance._copy_installed_application(source, refused)
    assert not refused.exists()


def test_copy_fsyncs_each_allowlisted_file_and_recensuses_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "_internal").mkdir(parents=True)
    (source / "Atlas.exe").write_bytes(b"exe")
    (source / "_internal/runtime.bin").write_bytes(b"runtime")
    fake_verified(monkeypatch)
    snapshots, flushes = [], []

    def verified(root):
        snapshots.append(root)
        return entries(root)

    monkeypatch.setattr(release_contract, "verified_application_entries", verified)
    monkeypatch.setattr(maintenance.os, "fsync", lambda descriptor: flushes.append(descriptor))
    maintenance._copy_installed_application(source, tmp_path / "copy")
    assert snapshots == [source, source]
    assert len(flushes) == 2


def test_copy_refuses_changed_source_bytes_before_writing_them(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    member = source / "Atlas.exe"
    member.write_bytes(b"approved bytes")
    snapshot = entries(source)
    monkeypatch.setattr(release_contract, "verified_application_entries", lambda _root: snapshot)
    member.write_bytes(b"substituted bytes")
    destination = tmp_path / "copy"
    with pytest.raises(release_contract.PortableReleaseError, match="changed before open"):
        maintenance._copy_installed_application(source, destination)
    assert not destination.exists()


def test_failed_copy_cleanup_preserves_unknown_destination_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Atlas.exe").write_bytes(b"approved")
    fake_verified(monkeypatch)

    def reject(root):
        (root / "unowned.txt").write_bytes(b"never remove unknown content")
        raise ValueError("destination changed")

    monkeypatch.setattr(release_contract, "verify_installed_bundle", reject)
    destination = tmp_path / "copy"
    with pytest.raises(ValueError, match="destination changed"):
        maintenance._copy_installed_application(source, destination)
    assert (destination / "unowned.txt").read_bytes() == b"never remove unknown content"
    assert not (destination / "Atlas.exe").exists()


def test_copy_keeps_windows_handle_and_path_attribute_identities_separate(tmp_path, monkeypatch):
    """Windows FSTAT can omit path attributes without changing the opened file."""
    source = tmp_path / "source"
    source.mkdir()
    member = source / "Atlas.exe"
    member.write_bytes(b"synthetic application bytes")
    fake_verified(monkeypatch)
    original_fstat = maintenance.os.fstat
    observed = []

    def windows_handle_metadata(descriptor):
        actual = original_fstat(descriptor)
        attributes = {name: getattr(actual, name) for name in dir(actual) if name.startswith("st_")}
        attributes["st_file_attributes"] = getattr(actual, "st_file_attributes", 0) ^ 0x20
        proxy = SimpleNamespace(**attributes)
        assert release_contract._installed_file_identity(proxy) == release_contract._installed_file_identity(actual)
        assert release_contract._installed_stat_identity(proxy) != release_contract._installed_stat_identity(actual)
        observed.append(descriptor)
        return proxy

    monkeypatch.setattr(maintenance.os, "fstat", windows_handle_metadata)
    destination = tmp_path / "copy"
    maintenance._copy_installed_application(source, destination)
    assert observed
    assert (destination / "Atlas.exe").read_bytes() == member.read_bytes()


@pytest.mark.parametrize("unexpected", ["root-file", "root-directory", "data", "DATA"])
def test_retirement_refuses_unknown_root_entries_and_anycase_data(tmp_path, monkeypatch, unexpected):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.maintenance.json").unlink()
    receipt = maintenance._outcome("a" * 32)
    receipt.update(status="complete", exit_code=0)
    result.write_text(json.dumps(receipt), encoding="utf-8")
    unknown = helper / unexpected if unexpected.startswith("root") else helper / "Atlas" / unexpected
    if unexpected == "root-file":
        unknown.write_bytes(b"preserved")
    else:
        unknown.mkdir()
    maintenance._retire_helpers(tmp_path, tmp_path / "current")
    assert unknown.exists()
    assert (helper / "Atlas/Atlas.exe").is_file()


@pytest.mark.parametrize("receipt", [None, {}, {"schema": maintenance.RESULT_SCHEMA, "status": "scheduled"}])
def test_retirement_never_treats_result_presence_as_terminal_completion(tmp_path, monkeypatch, receipt):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.maintenance.json").unlink()
    if receipt is None:
        maintenance._retire_helpers(tmp_path, tmp_path / "current")
    else:
        result.write_text(json.dumps(receipt), encoding="utf-8")
        maintenance._retire_helpers(tmp_path, tmp_path / "current")
    assert helper.is_dir()


def test_retirement_removes_only_exact_verified_completed_helper(tmp_path, monkeypatch):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    receipt = maintenance._outcome("a" * 32)
    receipt.update(status="complete", exit_code=0)
    result.write_text(json.dumps(receipt), encoding="utf-8")
    (tmp_path / "Atlas.maintenance.json").unlink()  # no longer the current pointer's subject
    maintenance._retire_helpers(tmp_path, tmp_path / "current")
    assert not helper.exists()
    assert result.is_file()


def test_original_refusal_receipt_retains_helper_after_separate_recovery(tmp_path, monkeypatch):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.maintenance.json").unlink()
    refused = maintenance._outcome("a" * 32)
    refused.update(exit_code=70, error="injected interruption")
    original = json.dumps(refused)
    result.write_text(original, encoding="utf-8")
    maintenance._retire_helpers(tmp_path, tmp_path / "current")
    assert helper.is_dir()
    assert result.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("malformed", ["not JSON", "[]", "null", '{"parent_pid":true}'])
def test_malformed_worker_request_uses_independent_pointer_bound_refusal(tmp_path, monkeypatch, capsys, malformed):
    output = tmp_path.parent / (tmp_path.name + "-outside")
    output.mkdir()
    assert not output.is_relative_to(tmp_path)
    helper, executable, result = bound_helper(tmp_path, monkeypatch, result_parent=output)
    (helper / "request.json").write_text(malformed, encoding="utf-8")
    monkeypatch.setattr(maintenance.sys, "executable", str(executable))
    monkeypatch.setattr(maintenance, "_transaction", lambda *args: pytest.fail("untrusted request executed"))
    assert maintenance._worker(helper / "request.json") == 1
    receipt = json.loads(result.read_text(encoding="utf-8"))
    assert receipt["status"] == "refused" and receipt["exit_code"] == 1
    assert receipt["nonce"] == "a" * 32
    assert str(result) in capsys.readouterr().err


def test_changed_recovery_helper_dependency_refuses_before_dispatch(tmp_path, monkeypatch):
    helper, executable, _result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.update-state.json").write_text("preserved journal", encoding="ascii")
    pointer = (tmp_path / "Atlas.maintenance.json").read_bytes()

    def refuse(_root):
        raise release_contract.PortableReleaseError("dependency checksum mismatch")

    monkeypatch.setattr(release_contract, "verify_installed_bundle", refuse)
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(maintenance.subprocess, "Popen", lambda *a, **kw: pytest.fail("changed helper launched"))
    assert maintenance._recover(executable, tmp_path, None) == 1
    receipts = list(tmp_path.glob("Atlas.maintenance-result.*.json"))
    assert len(receipts) == 1
    assert "dependency checksum mismatch" in json.loads(receipts[0].read_text())["error"]
    assert (tmp_path / "Atlas.maintenance.json").read_bytes() == pointer
    assert (helper / "request.json").exists()


def test_active_version_schedules_original_helper_and_exits_before_recovery(tmp_path, monkeypatch, capsys):
    helper, original, _result = bound_helper(tmp_path, monkeypatch)
    active = tmp_path / "Atlas/Atlas.exe"
    active.parent.mkdir()
    active.write_bytes(b"new version, not recovery authority")
    (tmp_path / "Atlas.update-state.json").write_text("interrupted", encoding="ascii")
    pointer = (tmp_path / "Atlas.maintenance.json").read_bytes()
    request = (helper / "request.json").read_bytes()
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    calls = []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(maintenance.subprocess, "Popen", spawn)
    monkeypatch.setattr(maintenance.subprocess, "run", lambda *a, **kw: pytest.fail("active caller waited on child"))
    monkeypatch.setattr(maintenance, "_transaction", lambda *a: pytest.fail("active image still owns directory"))
    monkeypatch.setattr(maintenance, "_wait_for_parent", lambda *a: pytest.fail("launcher must exit, not wait"))
    assert maintenance._recover(active, tmp_path, None) == 0
    argv, options = calls[0]
    assert argv[:3] == [str(original), "--recover", str(tmp_path)]
    assert argv[argv.index("--recover-parent-pid") + 1] == str(maintenance.os.getpid())
    assert argv[argv.index("--recover-parent-creation") + 1] == str(maintenance.os.getpid() + 1000)
    assert options["close_fds"] is True and options["cwd"] == str(tmp_path)
    assert options["creationflags"] == (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                        | getattr(subprocess, "DETACHED_PROCESS", 0))
    result = Path(argv[argv.index("--maintenance-result") + 1])
    assert not result.exists()  # scheduled never masquerades as transaction completion
    assert json.loads(capsys.readouterr().out)["status"] == "scheduled"
    assert (tmp_path / "Atlas.maintenance.json").read_bytes() == pointer
    assert (helper / "request.json").read_bytes() == request


@pytest.mark.parametrize("mode", ["--update", "--rollback"])
def test_journal_refusal_happens_under_lock_before_copy_or_pointer_rewrite(tmp_path, monkeypatch, mode):
    source = tmp_path / "Atlas"
    source.mkdir()
    pointer = tmp_path / "Atlas.maintenance.json"
    pointer.write_bytes(b"original recovery authority")
    (tmp_path / "Atlas.update-state.json").write_bytes(b"malformed but preserved")
    package = tmp_path / "candidate.zip"
    package.write_bytes(b"selected bytes")
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance.sys, "executable", str(source / "Atlas.exe"))
    monkeypatch.setattr(maintenance, "_copy_installed_application", lambda *args: pytest.fail("copied before recovery"))
    held = []

    @contextmanager
    def lock(root):
        held.append(root)
        yield

    monkeypatch.setattr(maintenance, "_handoff_lock", lock)
    argv = [mode]
    if mode == "--update":
        argv += [str(package), "--expected-sha256", hashlib.sha256(package.read_bytes()).hexdigest()]
    assert maintenance.main(argv) == 1
    assert held == [tmp_path]
    assert pointer.read_bytes() == b"original recovery authority"
    assert not helper_paths(tmp_path)


@pytest.mark.parametrize("argv", [
    ["--recover", "unused", "--expected-sha256", "0" * 64],
    ["--recover", "unused", "--dest", "ignored"],
    ["--rollback", "--expected-sha256", "0" * 64],
    ["--install", "unused", "--dest", "ignored"],
    ["--maintenance-worker", "unused", "--maintenance-result", "ignored"],
])
def test_ignored_options_refuse_before_any_transaction(monkeypatch, argv):
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance, "_transaction", lambda *args: pytest.fail("ignored flags executed"))
    assert maintenance.main(argv) == 1


def test_wrapper_demands_explicit_recovery_and_does_not_spawn_visible_powershell():
    root = Path(__file__).resolve().parents[1]
    wrapper = (root / "portable/make_stick.ps1").read_text(encoding="ascii")
    assert "[switch]$Recover" in wrapper
    assert '-not $Recover' in wrapper and 'explicitly use -Recover' in wrapper
    assert wrapper.index('cannot ignore requested') < wrapper.index('$journal =')
    source = (root / "portable/maintenance.py").read_text(encoding="utf-8")
    assert 'getattr(subprocess, "CREATE_NO_WINDOW", 0)' in source
    assert 'shutil.rmtree' not in source


def test_request_destination_flag_case_and_lexical_aliases_are_normalized(tmp_path):
    nonce = "a" * 32
    value = {"schema": "atlas.maintenance-request/1", "parent_pid": 1, "nonce": nonce,
             "arguments": ["-dEsT", str(tmp_path / "unused" / ".."), "-Rollback"],
             "result": str(tmp_path / f"Atlas.maintenance-result.{nonce}.json")}
    maintenance._validate_request(value, tmp_path, nonce)


@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_copy_cleans_its_partial_file_after_write_or_fsync_failure(tmp_path, monkeypatch, failure):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Atlas.exe").write_bytes(b"approved synthetic bytes")
    fake_verified(monkeypatch)
    if failure == "fsync":
        def fail_fsync(_descriptor):
            raise OSError("synthetic flush failure")
        monkeypatch.setattr(maintenance.os, "fsync", fail_fsync)
    else:
        original = Path.open

        class PartialWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def write(self, raw):
                self.stream.write(raw[:3])
                raise OSError("synthetic partial write")

        def opened(path, mode="r", *args, **kwargs):
            stream = original(path, mode, *args, **kwargs)
            return PartialWriter(stream) if mode == "xb" else stream

        monkeypatch.setattr(Path, "open", opened)
    destination = tmp_path / "partial"
    with pytest.raises(OSError, match="synthetic"):
        maintenance._copy_installed_application(source, destination)
    assert not destination.exists()


def test_preparation_source_refusal_leaves_no_helper_then_repair_retries(tmp_path, monkeypatch):
    source = tmp_path / "Atlas"
    source.mkdir()
    (source / "Atlas.exe").write_bytes(b"approved synthetic application")
    package = tmp_path / "candidate.zip"
    package.write_bytes(b"selected package bytes")
    fake_verified(monkeypatch)
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(maintenance.sys, "executable", str(source / "Atlas.exe"))
    monkeypatch.setattr(maintenance.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123))

    def invalid(_root):
        raise ValueError("source needs repair")

    monkeypatch.setattr(release_contract, "verified_application_entries", invalid)
    argv = ["--update", str(package), "--expected-sha256", hashlib.sha256(package.read_bytes()).hexdigest()]
    assert maintenance.main(argv) == 1
    assert not helper_paths(tmp_path)
    assert not (tmp_path / "Atlas.maintenance.json").exists()
    monkeypatch.setattr(release_contract, "verified_application_entries", entries)
    assert maintenance.main(argv) == 0
    assert len(helper_paths(tmp_path)) == 1


def test_partial_retirement_never_blocks_next_safe_maintenance(tmp_path, monkeypatch, capsys):
    helper, executable, result = bound_helper(tmp_path, monkeypatch)
    (executable.parent / "resource.bin").write_bytes(b"verified resource")
    complete = maintenance._outcome("a" * 32)
    complete.update(status="complete", exit_code=0)
    result.write_text(json.dumps(complete), encoding="utf-8")
    (tmp_path / "Atlas.maintenance.json").unlink()
    original_unlink = Path.unlink

    def in_use(path, *args, **kwargs):
        if path == executable:
            raise PermissionError("synthetic still-exiting executable")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", in_use)
    maintenance._retire_helpers(tmp_path, tmp_path / "current")
    assert helper.is_dir() and executable.is_file()
    assert not (executable.parent / "resource.bin").exists()

    def refused(root):
        if root == executable.parent:
            raise ValueError("incomplete retained code helper")
        return entries(root)

    monkeypatch.setattr(release_contract, "verified_application_entries", refused)
    maintenance._retire_helpers(tmp_path, tmp_path / "next")
    assert "retained maintenance helper" in capsys.readouterr().err
    assert helper.is_dir() and executable.is_file() and result.is_file()


@pytest.mark.parametrize("failed_name", ["request.json", "Atlas.maintenance.json"])
def test_preparation_metadata_failure_cleans_only_new_verified_code(tmp_path, monkeypatch, failed_name):
    source = tmp_path / "Atlas"
    source.mkdir()
    (source / "Atlas.exe").write_bytes(b"approved application")
    (source / "data").mkdir()
    evidence = source / "data/synthetic-evidence.bin"
    evidence.write_bytes(b"retained data")
    package = tmp_path / "candidate.zip"
    package.write_bytes(b"selected package")
    fake_verified(monkeypatch)
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(maintenance.sys, "executable", str(source / "Atlas.exe"))
    original_write = maintenance._write_result

    def refused(path, value):
        if path.name == failed_name:
            raise OSError("synthetic metadata failure")
        return original_write(path, value)

    monkeypatch.setattr(maintenance, "_write_result", refused)
    monkeypatch.setattr(maintenance.subprocess, "Popen", lambda *a, **kw: pytest.fail("failed preparation launched"))
    assert maintenance.main(["--update", str(package), "--expected-sha256",
                             hashlib.sha256(package.read_bytes()).hexdigest()]) == 1
    assert not helper_paths(tmp_path)
    assert evidence.read_bytes() == b"retained data"
    assert (source / "Atlas.exe").read_bytes() == b"approved application"


def main_update(root, monkeypatch):
    active = root / "Atlas"
    active.mkdir(exist_ok=True)
    (active / "Atlas.exe").write_bytes(b"synthetic active application")
    package = root / "candidate.zip"
    package.write_bytes(b"selected candidate")
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(maintenance.sys, "executable", str(active / "Atlas.exe"))
    return ["--update", str(package), "--expected-sha256", hashlib.sha256(package.read_bytes()).hexdigest()]


def test_live_prejournal_worker_refuses_second_launch_before_copy_or_pointer_change(tmp_path, monkeypatch):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    argv = main_update(tmp_path, monkeypatch)
    original_pointer = (tmp_path / "Atlas.maintenance.json").read_bytes()
    original_request = (helper / "request.json").read_bytes()
    monkeypatch.setattr(maintenance, "_copy_installed_application", lambda *a: pytest.fail("live worker superseded"))
    monkeypatch.setattr(maintenance, "_retire_helpers", lambda *a: pytest.fail("retired before admission"))
    assert maintenance.main(argv) == 1
    assert not result.exists()
    assert (tmp_path / "Atlas.maintenance.json").read_bytes() == original_pointer
    assert (helper / "request.json").read_bytes() == original_request
    assert len(helper_paths(tmp_path)) == 1


@pytest.mark.parametrize("stage", ["worker", "launcher", "reused-pid"])
def test_dead_prejournal_handoff_records_refusal_without_replay_or_permanent_lock(tmp_path, monkeypatch, stage):
    helper, _exe, result = bound_helper(tmp_path, monkeypatch)
    pointer_path = tmp_path / "Atlas.maintenance.json"
    if stage == "launcher":
        pointer = json.loads(pointer_path.read_text())
        del pointer["worker_pid"]
        del pointer["worker_creation"]
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    original = pointer_path.read_bytes()
    monkeypatch.setattr(maintenance, "_process_identity", lambda _pid: 777 if stage == "reused-pid" else None)
    monkeypatch.setattr(maintenance, "_transaction", lambda *a: pytest.fail("stale request replayed"))
    with pytest.raises(ValueError, match="inactive handoff"):
        maintenance._pending_handoff(tmp_path)
    receipt = json.loads(result.read_text())
    assert receipt["status"] == "refused" and receipt["exit_code"] == 1
    assert "no request was replayed" in receipt["error"]
    assert pointer_path.read_bytes() == original and helper.is_dir()
    maintenance._pending_handoff(tmp_path)  # terminal refusal allows a separately requested new operation
    assert pointer_path.read_bytes() == original


@pytest.mark.parametrize("previous", [False, True])
def test_spawn_failure_restores_only_this_attempt_pointer_and_allows_retry(tmp_path, monkeypatch, previous):
    fake_verified(monkeypatch)
    prior = None
    old_helper = None
    prior_receipt = None
    old_result = None
    if previous:
        old_helper, _exe, result = bound_helper(tmp_path, monkeypatch)
        complete = maintenance._outcome("a" * 32)
        complete.update(status="complete", exit_code=0)
        result.write_text(json.dumps(complete), encoding="utf-8")
        old_result, prior_receipt = result, result.read_bytes()
        prior = (tmp_path / "Atlas.maintenance.json").read_bytes()
    argv = main_update(tmp_path, monkeypatch)

    def spawn_failed(*args, **kwargs):
        raise OSError("synthetic spawn refusal")

    monkeypatch.setattr(maintenance.subprocess, "Popen", spawn_failed)
    assert maintenance.main(argv) == 1
    pointer_path = tmp_path / "Atlas.maintenance.json"
    assert pointer_path.read_bytes() == prior if previous else not pointer_path.exists()
    assert helper_paths(tmp_path) == ([old_helper] if previous else [])
    if previous:
        assert old_result.read_bytes() == prior_receipt
    monkeypatch.setattr(maintenance.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123))
    assert maintenance.main(argv) == 0
    pointer = json.loads(pointer_path.read_text())
    assert pointer["worker_pid"] == 123 and pointer["worker_creation"] == 1123
    if previous:
        assert old_result.read_bytes() == prior_receipt


def test_pointer_cleanup_does_not_erase_a_superseding_writer(tmp_path):
    pointer = tmp_path / "Atlas.maintenance.json"
    newer = b'{"schema":"different owned pointer"}\n'
    pointer.write_bytes(newer)
    maintenance._restore_owned_pointer(pointer, b'{"schema":"our attempt"}\n', None)
    assert pointer.read_bytes() == newer


def test_recovery_only_completes_recorded_request_without_mutating_its_arguments(tmp_path, monkeypatch):
    helper, executable, _result = bound_helper(tmp_path, monkeypatch)
    request_path = helper / "request.json"
    request = json.loads(request_path.read_text())
    request["arguments"] += ["-TestFailAfter", "rollback_active_moved"]
    request_path.write_text(json.dumps(request), encoding="utf-8")
    pointer_path = tmp_path / "Atlas.maintenance.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["request_sha256"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    original_request, original_pointer = request_path.read_bytes(), pointer_path.read_bytes()
    (tmp_path / "Atlas.update-state.json").write_bytes(b"recorded transaction")
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(maintenance, "_wait_for_parent", lambda pid, creation: None)
    calls = []
    monkeypatch.setattr(maintenance, "_transaction", lambda exe, args, outcome: calls.append((exe, args)) or 0)
    assert maintenance._recover(executable, tmp_path, None,
                                parent_pid=maintenance.os.getpid() + 1, parent_creation=42) == 0
    assert calls == [(executable, ["-Dest", str(tmp_path), "-Rollback", "-RecoverOnly"])]
    assert request_path.read_bytes() == original_request
    assert pointer_path.read_bytes() == original_pointer


@pytest.mark.parametrize("replacement", ["changed-bytes", "same-bytes-new-file"])
def test_retirement_preserves_request_changed_or_replaced_after_code_cleanup(tmp_path, monkeypatch, replacement):
    helper, _executable, result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.maintenance.json").unlink()
    complete = maintenance._outcome("a" * 32)
    complete.update(status="complete", exit_code=0)
    result.write_text(json.dumps(complete), encoding="utf-8")
    request_path = helper / "request.json"
    original_request = request_path.read_bytes()
    preserved = b"unowned substituted request bytes" if replacement == "changed-bytes" else original_request
    original_cleanup = maintenance._remove_created

    def changed(files, directories):
        original_cleanup(files, directories)
        substitute = tmp_path / "replacement-request.json"
        substitute.write_bytes(preserved)
        maintenance.os.replace(substitute, request_path)

    monkeypatch.setattr(maintenance, "_remove_created", changed)
    maintenance._retire_helpers(tmp_path, tmp_path / "next")
    assert helper.is_dir()
    assert request_path.read_bytes() == preserved


def test_recovery_receiver_waits_outside_lock_then_verifies_before_transaction(tmp_path, monkeypatch):
    _helper, executable, _result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.update-state.json").write_bytes(b"recorded journal")
    events = []
    held = [False]
    caller_pid = maintenance.os.getpid() + 1

    def wait(pid, creation):
        assert not held[0] and (pid, creation) == (caller_pid, 42)
        events.append("caller_exited")

    @contextmanager
    def lock(_root):
        assert events == ["caller_exited"]
        held[0] = True
        events.append("locked")
        try:
            yield
        finally:
            held[0] = False

    def verified(_root):
        assert held[0] and "caller_exited" in events
        events.append("verified")

    def transact(exe, arguments, outcome):
        assert held[0] and exe == executable and events[-1] == "verified"
        assert arguments[-1] == "-RecoverOnly"
        events.append("transaction")
        return 0

    monkeypatch.setattr(maintenance, "_wait_for_parent", wait)
    monkeypatch.setattr(maintenance, "_handoff_lock", lock)
    monkeypatch.setattr(release_contract, "verify_installed_bundle", verified)
    monkeypatch.setattr(maintenance, "_transaction", transact)
    assert maintenance._recover(executable, tmp_path, None, parent_pid=caller_pid, parent_creation=42) == 0
    assert events == ["caller_exited", "locked", "verified", "transaction"]


@pytest.mark.parametrize("changed", ["pointer", "request", "dependency"])
def test_recovery_receiver_refuses_corruption_or_authority_change_during_wait(tmp_path, monkeypatch, changed):
    helper, executable, _result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.update-state.json").write_bytes(b"preserved journal")
    dependency = executable.parent / "runtime.bin"
    dependency.write_bytes(b"approved runtime")

    def wait(_pid, _creation):
        if changed == "dependency":
            dependency.write_bytes(b"changed runtime")
        else:
            path = tmp_path / "Atlas.maintenance.json" if changed == "pointer" else helper / "request.json"
            path.write_bytes(path.read_bytes() + b"\n")

    def verified(_root):
        if dependency.read_bytes() != b"approved runtime":
            raise release_contract.PortableReleaseError("runtime checksum mismatch")

    monkeypatch.setattr(maintenance, "_wait_for_parent", wait)
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)
    monkeypatch.setattr(release_contract, "verify_installed_bundle", verified)
    monkeypatch.setattr(maintenance, "_transaction", lambda *a: pytest.fail("corrupt recovery state executed"))
    assert maintenance._recover(executable, tmp_path, None,
                                parent_pid=maintenance.os.getpid() + 1, parent_creation=42) == 1
    receipts = list(tmp_path.glob("Atlas.maintenance-result.*.json"))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())["status"] == "refused"
    assert (tmp_path / "Atlas.update-state.json").read_bytes() == b"preserved journal"


@pytest.mark.parametrize("pid,creation", [
    (None, 1), (1, None), (0, 1), (-1, 1), (0x100000000, 1), (1, 0), (1, 0x10000000000000000),
])
def test_recovery_parent_identity_pair_rejects_missing_or_out_of_range_values(pid, creation):
    with pytest.raises(ValueError, match="paired positive"):
        maintenance._recovery_parent(pid, creation)


def test_recovery_parent_identity_never_waits_on_itself():
    with pytest.raises(ValueError, match="itself"):
        maintenance._recovery_parent(maintenance.os.getpid(), 42)


def test_recovery_parent_flags_refuse_an_active_nonhelper_receiver(tmp_path, monkeypatch):
    _helper, _original, _result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.update-state.json").write_bytes(b"journal")
    active = tmp_path / "Atlas/Atlas.exe"
    active.parent.mkdir()
    active.write_bytes(b"active application")
    monkeypatch.setattr(maintenance, "_wait_for_parent", lambda *a: pytest.fail("wrong receiver waited"))
    monkeypatch.setattr(maintenance, "_transaction", lambda *a: pytest.fail("wrong receiver executed"))
    assert maintenance._recover(active, tmp_path, None,
                                parent_pid=maintenance.os.getpid() + 1, parent_creation=42) == 1


@pytest.mark.parametrize("argv", [
    ["--rollback", "--recover-parent-pid", "1", "--recover-parent-creation", "42"],
    ["--recover", "unused", "--recover-parent-pid", "1"],
    ["--recover", "unused", "--recover-parent-creation", "42"],
])
def test_hidden_recovery_identity_flags_cannot_be_ignored_or_split(monkeypatch, argv):
    monkeypatch.setattr(maintenance, "_require_runtime", lambda: None)
    monkeypatch.setattr(maintenance, "_recover", lambda *a, **kw: pytest.fail("invalid identity dispatched"))
    assert maintenance.main(argv) == 1


def test_recovery_spawn_failure_saves_refusal_without_mutating_original_authority(tmp_path, monkeypatch):
    helper, executable, _result = bound_helper(tmp_path, monkeypatch)
    (tmp_path / "Atlas.update-state.json").write_bytes(b"journal")
    pointer = (tmp_path / "Atlas.maintenance.json").read_bytes()
    request = (helper / "request.json").read_bytes()
    monkeypatch.setattr(maintenance, "_handoff_lock", unlocked)

    def fail(*args, **kwargs):
        raise OSError("synthetic detached recovery failure")

    monkeypatch.setattr(maintenance.subprocess, "Popen", fail)
    assert maintenance._recover(executable, tmp_path, None) == 1
    receipts = list(tmp_path.glob("Atlas.maintenance-result.*.json"))
    assert len(receipts) == 1
    assert "synthetic detached recovery failure" in json.loads(receipts[0].read_text())["error"]
    assert (tmp_path / "Atlas.maintenance.json").read_bytes() == pointer
    assert (helper / "request.json").read_bytes() == request


def test_wrapper_recovery_and_update_share_terminal_receipt_wait_with_unchanged_budget():
    root = Path(__file__).resolve().parents[1]
    wrapper = (root / "portable/make_stick.ps1").read_text(encoding="ascii")
    assert '@("--recover", $destRoot, "--maintenance-result", $result)' in wrapper
    assert "& $commandExe @arguments" in wrapper
    assert wrapper.index("Wait-MaintenanceResult $result $nonce") > wrapper.index("& $commandExe @arguments")
    assert wrapper.count("AddMinutes(30)") == 1 and wrapper.count("Start-Sleep -Milliseconds 250") == 1
    assert '$receipt.nonce -cne $nonce' in wrapper and '$receipt.exit_code -is [int]' in wrapper
    assert '$receipt.status -ne $(if ($receipt.exit_code -eq 0)' in wrapper
    assert 'exit ([int]$receipt.exit_code)' in wrapper
