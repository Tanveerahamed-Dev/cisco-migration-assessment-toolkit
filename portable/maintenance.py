"""Installed-code maintenance, with durable and explicit journal recovery."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path


COMMANDS = frozenset({"--install", "--update", "--rollback", "--recover", "--maintenance-worker"})
RESULT_SCHEMA = "atlas.maintenance-result/1"
_HELPER = re.compile(r"Atlas\.maintenance-([0-9a-f]{32})")
_RESULT = re.compile(r"Atlas\.maintenance-result\.([0-9a-f]{32})\.json")
_ERRORS = (OSError, ValueError, RuntimeError, TypeError, KeyError)


def _normal(value: str | Path) -> Path:
    # Lexical normalization preserves aliases for the physical-path rejection.
    return Path(os.path.abspath(os.path.normpath(os.fspath(value))))


def _physical(path: Path) -> None:
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        value = item.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("maintenance paths must not contain links or reparse points")


def _object(path: Path) -> tuple[dict, bytes]:
    from portable.release_contract import _read_bounded_regular

    _physical(path)
    raw = _read_bounded_regular(path, 64 * 1024, "maintenance protocol file")
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError("maintenance protocol file must contain an object")
    return value, raw


def _write_result(path: Path, value: dict) -> None:
    _physical(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _powershell() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@contextlib.contextmanager
def _handoff_lock(root: Path):
    """OS-owned handle; a dead process cannot leave a stale logical lock."""
    import ctypes
    from ctypes import wintypes

    path = root / ".Atlas.maintenance.lock"
    _physical(path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "another Atlas maintenance process holds the handoff lock")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _transaction(executable: Path, arguments: list[str], outcome: dict | None = None) -> int:
    script = executable.parent / "_internal/portable/update_transaction.ps1"
    _physical(script)
    process = subprocess.run(
        [str(_powershell()), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-VerifierExe", str(executable), *arguments],
        cwd=str(executable.parent.parent), check=False, capture_output=True,
        encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
    if output and outcome is None:
        print(output)
    if outcome is not None and process.returncode:
        outcome["error"] = output[-2048:]
    return process.returncode


def _result_path(root: Path, selected: str | None, nonce: str) -> Path:
    path = _normal(selected) if selected else root / f"Atlas.maintenance-result.{nonce}.json"
    _physical(path)
    if (not _RESULT.fullmatch(path.name)
            or (path.is_relative_to(root) and path.parent != root)):
        raise ValueError("result must be a fresh Atlas.maintenance-result.<32-hex>.json outside application slots")
    if os.path.lexists(path):
        raise ValueError("maintenance result already exists; choose a fresh path")
    if not path.parent.is_dir():
        raise ValueError("maintenance result parent must already exist")
    return path


def _outcome(nonce: str) -> dict:
    return {"schema": RESULT_SCHEMA, "status": "refused", "exit_code": 1,
            "verifier_origin": "installed_atlas", "verification_policy": "sha256_bound_runtime_extension",
            "authentication": "operator_selected_digest_not_publisher_authentication", "nonce": nonce}


def _process_identity(pid: int) -> int | None:
    """Creation time of a live OS process; PID reuse cannot inherit handoff ownership."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00101000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return None
        raise OSError(error, "cannot establish maintenance process identity")
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        if state == 0:
            return None
        if state != 258:
            raise OSError(ctypes.get_last_error(), "cannot establish maintenance process liveness")
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise OSError(ctypes.get_last_error(), "cannot bind maintenance process creation time")
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def _pending_handoff(root: Path) -> None:
    """Admission under the handoff lock, including the pre-journal worker window."""
    path = root / "Atlas.maintenance.json"
    if not os.path.lexists(path):
        return
    pointer, _raw = _object(path)
    relative, selected = pointer.get("helper"), pointer.get("result")
    match = re.fullmatch(r"Atlas\.maintenance-([0-9a-f]{32})/Atlas/Atlas\.exe", relative or "")
    if (pointer.get("schema") != "atlas.maintenance-recovery/1" or match is None
            or not isinstance(selected, str)):
        raise ValueError("cannot establish pending handoff ownership; preserve its pointer")
    nonce = match.group(1)
    result_path = _normal(selected)
    _physical(result_path)
    if (result_path.name != f"Atlas.maintenance-result.{nonce}.json"
            or (result_path.is_relative_to(root) and result_path.parent != root)):
        raise ValueError("recorded handoff result has an unsafe or unbound location")
    if os.path.lexists(result_path):
        result, _raw = _object(result_path)
        code = result.get("exit_code")
        if (result.get("schema") != RESULT_SCHEMA or result.get("nonce") != nonce
                or type(code) is not int or code < 0
                or result.get("status") != ("complete" if code == 0 else "refused")
                or result.get("verifier_origin") != "installed_atlas"
                or result.get("verification_policy") != "sha256_bound_runtime_extension"
                or result.get("authentication") != "operator_selected_digest_not_publisher_authentication"):
            raise ValueError("recorded handoff has no valid terminal result; preserve its evidence")
        return
    _executable, pointer, request = _recorded_helper(root)
    worker_pid, worker_creation = pointer.get("worker_pid"), pointer.get("worker_creation")
    if type(worker_pid) is int and worker_pid > 0 and type(worker_creation) is int and worker_creation > 0:
        if _process_identity(worker_pid) == worker_creation:
            raise ValueError("recorded maintenance worker is still active; preserve its pointer and wait for its result")
    else:
        launcher_pid, launcher_creation = pointer.get("launcher_pid"), pointer.get("launcher_creation")
        if (type(launcher_pid) is not int or launcher_pid <= 0 or type(launcher_creation) is not int
                or launcher_creation <= 0):
            raise ValueError("cannot prove recorded handoff is inactive; preserve its pointer and inspect")
        if _process_identity(launcher_pid) == launcher_creation:
            raise ValueError("recorded maintenance launcher is still active; preserve its pointer")
        # A worker lacking its own published creation identity refuses before it
        # may mutate state, so a dead launcher cannot leave a runnable stale request.
    outcome = _outcome(nonce)
    outcome["error"] = "recorded handoff ended before a journal or terminal result; no request was replayed"
    _finish(_result_path(root, str(result_path), nonce), outcome)
    raise ValueError(f"inactive handoff was recorded as refused; inspect {result_path} before requesting maintenance again")


def _restore_owned_pointer(path: Path, published: bytes | None, previous: bytes | None) -> None:
    """Restore only our exact published pointer; never erase a superseding writer."""
    if published is None or not os.path.lexists(path):
        return
    _value, current = _object(path)
    if current != published:
        return
    if previous is None:
        path.unlink()
        return
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(previous)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _finish(path: Path, outcome: dict) -> int:
    try:
        if os.path.lexists(path):
            raise ValueError("refusing to overwrite an existing maintenance result")
        _write_result(path, outcome)
    except _ERRORS as exc:
        print(f"Atlas maintenance REFUSED: {exc}; result could not be saved at {path}", file=sys.stderr)
        return 1
    if outcome["exit_code"]:
        print(f"Atlas maintenance REFUSED: {outcome.get('error', 'transaction failed')}; result: {path}",
              file=sys.stderr)
    else:
        print(json.dumps({"status": "complete", "result": str(path)}))
    return outcome["exit_code"]


def _validate_request(value: dict, root: Path, nonce: str) -> None:
    if (set(value) != {"schema", "parent_pid", "arguments", "result", "nonce"}
            or value["schema"] != "atlas.maintenance-request/1" or value["nonce"] != nonce
            or type(value["parent_pid"]) is not int or value["parent_pid"] <= 0
            or not isinstance(value["result"], str) or not isinstance(value["arguments"], list)
            or not all(isinstance(item, str) for item in value["arguments"])):
        raise ValueError("unsupported maintenance handoff")
    result = _normal(value["result"])
    if (result.name != f"Atlas.maintenance-result.{nonce}.json"
            or (result.is_relative_to(root) and result.parent != root)):
        raise ValueError("maintenance request result does not match its helper nonce")
    arguments = value["arguments"][:]
    if "-TestFailAfter" in arguments:
        index = arguments.index("-TestFailAfter")
        if index != len(arguments) - 2 or not arguments[-1]:
            raise ValueError("unsupported maintenance fault-injection arguments")
        arguments = arguments[:index]
    if len(arguments) < 3 or arguments[0].casefold() != "-dest" or _normal(arguments[1]) != root:
        raise ValueError("maintenance request destination differs from its helper")
    if arguments[2] == "-Rollback":
        if arguments[3:] not in ([], ["-RestorePreUpdateDatabase"]):
            raise ValueError("unsupported rollback request arguments")
    elif (len(arguments) != 6 or arguments[2] != "-Package" or arguments[4] != "-ExpectedSha256"
          or not re.fullmatch(r"[0-9a-f]{64}", arguments[5])):
        raise ValueError("unsupported package request arguments")


def _entry_identity(entries: list) -> list:
    from portable.release_contract import _installed_stat_identity

    return [(relative, _installed_stat_identity(metadata), digest)
            for relative, _path, metadata, digest in entries]


def _remove_created(files: list[tuple[Path, os.stat_result]], directories: list[Path]) -> None:
    """Never recursively delete unknown content after a copy failure."""
    from portable.release_contract import _installed_file_identity

    for path, expected in reversed(files):
        try:
            _physical(path)
            if not os.path.lexists(path):
                continue
            if _installed_file_identity(path.lstat()) != _installed_file_identity(expected):
                continue  # a replaced/changed file is no longer ours to remove
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    for path in reversed(directories):
        try:
            _physical(path)
            path.rmdir()
        except (OSError, ValueError):
            pass


def _copy_installed_application(source: Path, destination: Path) -> list:
    from portable.release_contract import (
        MAX_ZIP_MEMBER_BYTES, _installed_stat_identity, _read_installed_regular,
        verified_application_entries, verify_installed_bundle,
    )

    _physical(source)
    entries = verified_application_entries(source)  # BEFORE creating any copy or reading unowned bytes
    created_files: list[tuple[Path, os.stat_result]] = []
    created_directories: list[Path] = []
    try:
        destination.mkdir()
        created_directories.append(destination)
        for relative, path, metadata, expected_digest in entries:
            target = destination.joinpath(*relative.split("/"))
            _physical(path)
            if stat.S_ISDIR(metadata.st_mode):
                if _installed_stat_identity(path.lstat()) != _installed_stat_identity(metadata):
                    raise ValueError("installed application directory changed during maintenance copy")
                target.mkdir()
                created_directories.append(target)
            else:
                raw = _read_installed_regular(
                    path, metadata, MAX_ZIP_MEMBER_BYTES, "installed maintenance application member",
                )
                if hashlib.sha256(raw).hexdigest() != expected_digest:
                    raise ValueError("installed application changed during maintenance copy")
                with target.open("xb") as stream:
                    created_files.append((target, os.fstat(stream.fileno())))
                    try:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    finally:
                        # Bind our partial file too if write/flush/fsync fails.
                        # Buffered bytes must reach the descriptor before fstat.
                        try:
                            stream.flush()
                        finally:
                            created_files[-1] = (target, os.fstat(stream.fileno()))
        if _entry_identity(verified_application_entries(source)) != _entry_identity(entries):
            raise ValueError("installed application census changed during maintenance copy")
        verify_installed_bundle(destination)
        return [(relative, destination.joinpath(*relative.split("/")),
                 destination.joinpath(*relative.split("/")).lstat(), digest)
                for relative, _path, _metadata, digest in entries]
    except BaseException:
        _remove_created(created_files, created_directories)
        raise


def _helper_contents(helper: Path) -> tuple[list, dict, bytes]:
    from portable.release_contract import verified_application_entries, verify_installed_bundle

    _physical(helper)
    if not _HELPER.fullmatch(helper.name) or not helper.is_dir():
        raise ValueError("unsupported maintenance helper namespace")
    if {path.name for path in helper.iterdir()} != {"Atlas", "request.json"}:
        raise ValueError("maintenance helper contains unowned root entries; preserve it")
    atlas = helper / "Atlas"
    _physical(atlas)
    if any(path.name.casefold() == "data" for path in atlas.iterdir()):
        raise ValueError("maintenance helper contains client data; preserve it")
    verify_installed_bundle(atlas)  # default verifier forbids data and rechecks every member
    entries = verified_application_entries(atlas)
    request, raw = _object(helper / "request.json")
    _validate_request(request, helper.parent, helper.name.removeprefix("Atlas.maintenance-"))
    return entries, request, raw


def _retire_helper(candidate: Path) -> None:
    """Delete only one completed helper whose complete ownership was verified."""
    entries, request, request_raw = _helper_contents(candidate)
    result_path = _normal(request["result"])
    if not os.path.lexists(result_path):
        return
    result, _result_raw = _object(result_path)
    code = result.get("exit_code")
    if (result.get("schema") != RESULT_SCHEMA or result.get("nonce") != request["nonce"]
            or type(code) is not int or code < 0
            or result.get("status") != ("complete" if code == 0 else "refused")
            or result.get("verifier_origin") != "installed_atlas"
            or result.get("verification_policy") != "sha256_bound_runtime_extension"
            or result.get("authentication") != "operator_selected_digest_not_publisher_authentication"):
        raise ValueError("maintenance helper lacks a matching terminal result; preserve it")
    if code != 0:
        return  # recovery's separate receipt never erases the original refusal
    # Delete only exact verified members; an inserted unknown file survives and
    # prevents directory removal rather than being swept up by recursive deletion.
    _entries, _request, confirmed_raw = _helper_contents(candidate)
    from portable.release_contract import _installed_file_identity, _same_read

    request_path = candidate / "request.json"
    _physical(request_path)
    bound_raw, request_metadata = _same_read(request_path)
    if bound_raw != request_raw or confirmed_raw != request_raw:
        raise ValueError("maintenance helper request changed before retirement; preserve it")
    files = [(candidate / "Atlas" / relative, metadata) for relative, _path, metadata, _sha in entries
             if not stat.S_ISDIR(metadata.st_mode)]
    directories = [candidate / "Atlas"] + [candidate / "Atlas" / relative
                   for relative, _path, metadata, _sha in entries if stat.S_ISDIR(metadata.st_mode)]
    _remove_created(files, directories)
    remaining = {path.name for path in candidate.iterdir()}
    if remaining == {"request.json"}:
        _physical(request_path)
        current_raw, current_metadata = _same_read(request_path)
        if (current_raw != request_raw
                or _installed_file_identity(current_metadata) != _installed_file_identity(request_metadata)):
            raise ValueError("maintenance helper request changed during retirement; preserve it")
        request_path.unlink()
        candidate.rmdir()


def _retire_helpers(root: Path, current: Path) -> None:
    if os.path.lexists(root / "Atlas.update-state.json"):
        return
    pointer_path = root / "Atlas.maintenance.json"
    referenced = _object(pointer_path)[0].get("helper") if os.path.lexists(pointer_path) else None
    for candidate in root.iterdir():
        if candidate == current or not _HELPER.fullmatch(candidate.name):
            continue
        if referenced == f"{candidate.name}/Atlas/Atlas.exe":
            continue  # preserve the old pointer's subject until a new handoff exists
        try:
            _retire_helper(candidate)
        except _ERRORS as exc:
            # Unknown/unfinished content is preserved without blocking a new,
            # separately verified maintenance operation.
            print(f"Atlas retained maintenance helper {candidate}: {exc}", file=sys.stderr)


def _cleanup_prepared_helper(helper: Path, entries: list, request_identity: os.stat_result | None) -> None:
    files = [(helper / "Atlas" / relative, metadata) for relative, _path, metadata, _sha in entries
             if not stat.S_ISDIR(metadata.st_mode)]
    if request_identity is not None:
        files.append((helper / "request.json", request_identity))
    directories = [helper, helper / "Atlas"] + [helper / "Atlas" / relative
                   for relative, _path, metadata, _sha in entries if stat.S_ISDIR(metadata.st_mode)]
    _remove_created(files, directories)


def _wait_for_parent(pid: int, creation: int | None = None) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00101000 if creation is not None else 0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise OSError(ctypes.get_last_error(), "cannot wait for Atlas to close")
    try:
        if creation is not None:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                          ctypes.byref(kernel_time), ctypes.byref(user_time)):
                raise OSError(ctypes.get_last_error(), "cannot bind recovery caller creation time")
            if ((created.dwHighDateTime << 32) | created.dwLowDateTime) != creation:
                raise ValueError("recovery caller process identity changed")
        if kernel.WaitForSingleObject(handle, 300_000) != 0:
            raise TimeoutError("Atlas did not release its application directory within 300 seconds")
    finally:
        kernel.CloseHandle(handle)


def _recorded_helper(root: Path) -> tuple[Path, dict, dict]:
    pointer, _raw = _object(root / "Atlas.maintenance.json")
    relative = pointer.get("helper")
    if (pointer.get("schema") != "atlas.maintenance-recovery/1" or not isinstance(relative, str)
            or not re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe", relative)):
        raise ValueError("unsupported recorded maintenance helper")
    executable = root.joinpath(*relative.split("/"))
    _entries, request, raw = _helper_contents(executable.parent.parent)
    from portable.release_contract import _same_read

    if (hashlib.sha256(_same_read(executable)[0]).hexdigest() != pointer.get("helper_exe_sha256")
            or hashlib.sha256(raw).hexdigest() != pointer.get("request_sha256")
            or pointer.get("result") != request["result"]):
        raise ValueError("recorded helper code, request or result identity changed")
    return executable, pointer, request


def _worker(request_path: Path) -> int:
    executable = _normal(sys.executable)
    helper = executable.parent.parent
    match = _HELPER.fullmatch(helper.name)
    if not match or executable.parent.name != "Atlas" or executable.name != "Atlas.exe":
        raise ValueError("worker must run from a canonical installed-code helper")
    root, nonce = helper.parent, match.group(1)
    result = _result_path(root, None, nonce)  # safe fallback BEFORE any request parsing
    outcome = _outcome(nonce)
    try:
        # Only the pointer, independent of malformed request bytes, may select an
        # external result. Its basename is tied to this helper's nonce.
        pointer, _raw = _object(root / "Atlas.maintenance.json")
        if pointer.get("helper") == executable.relative_to(root).as_posix():
            selected = _result_path(root, pointer.get("result"), nonce)
            if selected.name != result.name:
                raise ValueError("recorded worker result nonce differs")
            result = selected
        if _normal(request_path) != helper / "request.json":
            raise ValueError("maintenance request must be beside its private application copy")
        request, _raw = _object(request_path)
        _validate_request(request, root, nonce)
        _wait_for_parent(request["parent_pid"])
        with _handoff_lock(root):
            recorded, pointer, request = _recorded_helper(root)
            if (recorded != executable or pointer.get("worker_pid") != os.getpid()
                    or pointer.get("worker_creation") != _process_identity(os.getpid())):
                raise ValueError("maintenance handoff was superseded before worker activation")
            rc = _transaction(executable, request["arguments"], outcome)
        outcome.update(exit_code=rc, status="complete" if rc == 0 else "refused")
    except _ERRORS as exc:
        outcome["error"] = str(exc)
    return _finish(result, outcome)


def _recovery_parent(pid: int | None, creation: int | None) -> bool:
    if pid is None and creation is None:
        return False
    if (type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or pid == os.getpid()
            or type(creation) is not int or not 0 < creation <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError("recovery parent PID/creation must be paired positive identities and must not wait on itself")
    return True


def _recover(executable: Path, root: Path, result: Path | None,
             *, parent_pid: int | None = None, parent_creation: int | None = None) -> int:
    root, executable = _normal(root), _normal(executable)
    nonce = uuid.uuid4().hex
    result_path = _result_path(root, str(result) if result else None, nonce)
    nonce = _RESULT.fullmatch(result_path.name).group(1)
    outcome = _outcome(nonce)
    try:
        receiving = _recovery_parent(parent_pid, parent_creation)
        if receiving:
            # A receiver cannot acquire the handoff lock while its launching
            # process owns it. Establish the intended helper without mutation,
            # then wait on that actual caller's OS handle outside every lock.
            pointer, authority_raw = _object(root / "Atlas.maintenance.json")
            relative = pointer.get("helper")
            if (pointer.get("schema") != "atlas.maintenance-recovery/1" or not isinstance(relative, str)
                    or not re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe", relative)
                    or executable != root.joinpath(*relative.split("/"))):
                raise ValueError("recovery receiver must be the recorded original helper")
            _value, request_raw = _object(executable.parent.parent / "request.json")
            if hashlib.sha256(request_raw).hexdigest() != pointer.get("request_sha256"):
                raise ValueError("recorded recovery request changed before waiting")
            _wait_for_parent(parent_pid, parent_creation)
        with _handoff_lock(root):
            if receiving:
                if (_object(root / "Atlas.maintenance.json")[1] != authority_raw
                        or _object(executable.parent.parent / "request.json")[1] != request_raw):
                    raise ValueError("recorded recovery authority changed while waiting for its caller")
            if not os.path.lexists(root / "Atlas.update-state.json"):
                raise ValueError("no journaled maintenance request to recover")
            _physical(root / "Atlas.update-state.json")
            recorded, _pointer, request = _recorded_helper(root)
            arguments = request["arguments"][:]
            if "-TestFailAfter" in arguments:
                arguments = arguments[:arguments.index("-TestFailAfter")]
            arguments.append("-RecoverOnly")
            if receiving:
                if executable != recorded:
                    raise ValueError("recorded recovery helper changed while waiting for its caller")
                rc = _transaction(recorded, arguments, outcome)
                outcome.update(exit_code=rc, status="complete" if rc == 0 else "refused")
                return _finish(result_path, outcome)
            caller_pid = os.getpid()
            caller_creation = _process_identity(caller_pid)
            if caller_creation is None:
                raise ValueError("cannot establish recovery caller identity")
            subprocess.Popen(
                [str(recorded), "--recover", str(root), "--maintenance-result", str(result_path),
                 "--recover-parent-pid", str(caller_pid), "--recover-parent-creation", str(caller_creation)],
                cwd=str(root), close_fds=True,
                creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                               | getattr(subprocess, "DETACHED_PROCESS", 0)),
            )
        print(json.dumps({"status": "scheduled", "result": str(result_path),
                          "message": "Atlas is closing; wait for recovery's terminal result."}))
        return 0
    except _ERRORS as exc:
        outcome["error"] = str(exc)
    return _finish(result_path, outcome)


def _require_runtime() -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise ValueError("installation and updates require the bundled Windows Atlas.exe")


def _validate_options(args) -> None:
    if args.recover_parent_pid is not None or args.recover_parent_creation is not None:
        if not args.recover:
            raise ValueError("recovery parent identities apply only to --recover")
        _recovery_parent(args.recover_parent_pid, args.recover_parent_creation)
    if args.recover or args.maintenance_worker:
        if (args.package or args.expected_sha256 or args.dest or args.restore_pre_update_database
                or args.test_fail_after or (args.maintenance_worker and args.maintenance_result)):
            raise ValueError("recovery/worker mode cannot ignore install, update or rollback options")
    if args.install and args.dest:
        raise ValueError("--dest cannot be combined with --install")
    if args.package and not args.install:
        raise ValueError("--package requires --install")
    if args.restore_pre_update_database and not args.rollback:
        raise ValueError("--restore-pre-update-database requires --rollback")
    if args.rollback and args.expected_sha256:
        raise ValueError("--expected-sha256 does not apply to --rollback")
    if args.install and args.maintenance_result:
        raise ValueError("--maintenance-result applies only to asynchronous maintenance and recovery")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install, update or explicitly recover portable Atlas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", metavar="DEST")
    group.add_argument("--update", metavar="ZIP")
    group.add_argument("--rollback", action="store_true")
    group.add_argument("--recover", metavar="ROOT")
    group.add_argument("--maintenance-worker", help=argparse.SUPPRESS)
    parser.add_argument("--package", metavar="ZIP")
    parser.add_argument("--expected-sha256", metavar="SHA256")
    parser.add_argument("--dest", metavar="ROOT")
    parser.add_argument("--restore-pre-update-database", action="store_true")
    parser.add_argument("--maintenance-result", metavar="FILE")
    parser.add_argument("--test-fail-after", help=argparse.SUPPRESS)
    parser.add_argument("--recover-parent-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--recover-parent-creation", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        _require_runtime()
        _validate_options(args)
        if args.maintenance_worker:
            return _worker(_normal(args.maintenance_worker))
        executable = _normal(sys.executable)
        if args.recover:
            return _recover(executable, _normal(args.recover),
                            _normal(args.maintenance_result) if args.maintenance_result else None,
                            parent_pid=args.recover_parent_pid, parent_creation=args.recover_parent_creation)
        source = executable.parent
        root = _normal(args.install or args.dest or source.parent)
        _physical(root)
        if root == source or (args.install and (source.is_relative_to(root / "Atlas")
                                               or root.is_relative_to(source))):
            raise ValueError("first installation must run from a separately extracted Atlas folder")
        package = args.package if args.install else args.update
        if not args.rollback:
            if not package or not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256 or ""):
                raise ValueError("supply --package/--update ZIP and its published lowercase --expected-sha256")
            digest = args.expected_sha256
            package_path = _normal(package)
            _physical(package_path)
            from portable.release_contract import _read_zip_path

            if hashlib.sha256(_read_zip_path(package_path)).hexdigest() != digest:
                raise ValueError("package SHA-256 differs from the published SHA-256 expectation")
        root.mkdir(parents=True, exist_ok=True)
        arguments = ["-Dest", str(root)]
        if args.rollback:
            arguments.append("-Rollback")
            if args.restore_pre_update_database:
                arguments.append("-RestorePreUpdateDatabase")
        else:
            arguments.extend(["-Package", str(package_path), "-ExpectedSha256", digest])
        if args.test_fail_after:
            arguments.extend(["-TestFailAfter", args.test_fail_after])
        with _handoff_lock(root):
            journal = root / "Atlas.update-state.json"
            if os.path.lexists(journal):
                if not args.install:
                    raise ValueError("journaled maintenance is incomplete; use explicit --recover ROOT")
                state, _raw = _object(journal)
                identity = state.get("candidate_identity")
                if (state.get("schema") != "atlas.portable-transaction/2" or state.get("operation") != "update"
                        or state.get("had_active") is not False or not isinstance(identity, dict)
                        or identity.get("package_sha256") != digest):
                    raise ValueError("existing journal requires its recorded installed-version recovery helper")
                return _transaction(executable, arguments)
            if args.install:
                if os.path.lexists(root / "Atlas"):
                    raise ValueError("Atlas already exists here; use that installed Atlas.exe --update")
                return _transaction(executable, arguments)
            if source != root / "Atlas":
                raise ValueError("update and rollback must be launched by the installed Atlas.exe")
            _pending_handoff(root)
            result = _result_path(root, args.maintenance_result, uuid.uuid4().hex)
            nonce = _RESULT.fullmatch(result.name).group(1)
            helper = root / f"Atlas.maintenance-{nonce}"
            _retire_helpers(root, helper)  # before publishing any new helper or pointer
            helper.mkdir()
            prepared_entries: list = []
            request_identity = None
            worker = None
            pointer_path = root / "Atlas.maintenance.json"
            previous_pointer = _object(pointer_path)[1] if os.path.lexists(pointer_path) else None
            published_pointer = None
            try:
                copied = helper / "Atlas"
                prepared_entries = _copy_installed_application(source, copied)
                request_path = helper / "request.json"
                _write_result(request_path, {"schema": "atlas.maintenance-request/1", "parent_pid": os.getpid(),
                                            "arguments": arguments, "result": str(result), "nonce": nonce})
                request_identity = request_path.lstat()
                pointer = {"schema": "atlas.maintenance-recovery/1",
                           "helper": (copied / "Atlas.exe").relative_to(root).as_posix(),
                           "helper_exe_sha256": hashlib.sha256((copied / "Atlas.exe").read_bytes()).hexdigest(),
                           "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "result": str(result),
                           "launcher_pid": os.getpid(), "launcher_creation": _process_identity(os.getpid())}
                if pointer["launcher_creation"] is None:
                    raise ValueError("cannot establish current maintenance launcher identity")
                published_pointer = (json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                _write_result(pointer_path, pointer)
                worker = subprocess.Popen(
                    [str(copied / "Atlas.exe"), "--maintenance-worker", str(request_path)], cwd=str(helper), close_fds=True,
                    creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "DETACHED_PROCESS", 0)),
                )
                pointer["worker_pid"] = worker.pid
                pointer["worker_creation"] = _process_identity(worker.pid)
                if pointer["worker_creation"] is None:
                    raise ValueError("maintenance worker exited before its creation identity could be published")
                _write_result(pointer_path, pointer)
            except BaseException:
                if worker is None:
                    try:
                        _restore_owned_pointer(pointer_path, published_pointer, previous_pointer)
                    finally:
                        _cleanup_prepared_helper(helper, prepared_entries, request_identity)
                raise
        print(json.dumps({"status": "scheduled", "result": str(result),
                          "message": "Atlas is closing; wait for status complete in the result file."}))
        return 0
    except _ERRORS as exc:
        print(f"Atlas maintenance REFUSED: {exc}", file=sys.stderr)
        return 1
