"""Frozen Atlas installation and journaled update entry points.

The transaction remains the field-tested Windows PowerShell implementation. Only
the installed executable verifies incoming code. A private copy of that executable
continues maintenance after the launching executable exits, releasing Windows DLL
and working-directory handles before the whole-directory switch.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path


COMMANDS = frozenset({"--install", "--update", "--rollback", "--recover", "--maintenance-worker"})
RESULT_SCHEMA = "atlas.maintenance-result/1"


def _physical(path: Path) -> None:
    """Reject redirects in every existing ancestor, including the selected root."""
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        value = item.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("maintenance paths must not contain links or reparse points")


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
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


@contextlib.contextmanager
def _handoff_lock(root: Path):
    """OS-owned exclusive handle: process death cannot leave a stale logical lock."""
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
    script = executable.parent / "_internal" / "portable" / "update_transaction.ps1"
    _physical(script)
    process = subprocess.run(
        [str(_powershell()), "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-VerifierExe", str(executable), *arguments],
        cwd=str(executable.parent.parent), check=False, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    output = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
    if output and outcome is None:
        print(output)
    if outcome is not None and process.returncode:
        outcome["error"] = output[-2048:]
    return process.returncode


def _result_path(root: Path, selected: str | None, nonce: str) -> Path:
    path = Path(selected).absolute() if selected else root / f"Atlas.maintenance-result.{nonce}.json"
    _physical(path)
    if (not re.fullmatch(r"Atlas\.maintenance-result\.[0-9a-f]{32}\.json", path.name)
            or (path.is_relative_to(root) and path.parent != root)):
        raise ValueError("result must be a fresh Atlas.maintenance-result.<32-hex>.json outside application slots")
    if os.path.lexists(path):
        raise ValueError("maintenance result already exists; choose a fresh path")
    return path


def _retire_helpers(root: Path, current: Path) -> None:
    """Retire only old code helpers after selecting the new durable recovery copy."""
    from portable.release_contract import _installed_tree_entries

    if (root / "Atlas.update-state.json").exists():
        return  # interrupted-source custody takes precedence over reclaiming space
    for candidate in root.iterdir():
        if candidate == current or not re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}", candidate.name):
            continue
        if candidate.parent != root or not candidate.is_absolute():
            raise ValueError("refusing helper removal outside the maintenance destination")
        _physical(candidate)
        request = candidate / "request.json"
        if not request.is_file():
            continue
        prior = json.loads(request.read_text(encoding="utf-8"))
        prior_result = Path(prior.get("result", ""))
        if not prior_result.is_file():
            continue  # unfinished helper custody is never discarded
        if os.path.lexists(candidate / "Atlas" / "data"):
            raise ValueError("refusing to remove a maintenance helper containing client data")
        _installed_tree_entries(candidate)  # complete no-reparse census before recursive removal
        try:
            shutil.rmtree(candidate)
        except OSError:
            # A completed helper may still be exiting. Leave its remaining code for
            # the next invocation; never kill a process or relax file sharing.
            pass


def _copy_installed_application(source: Path, destination: Path) -> None:
    """Copy code only; never traverse or copy the installed client data directory."""
    from portable.release_contract import _installed_tree_entries, _same_read

    _physical(source)
    destination.mkdir()
    entries = []
    for child in source.iterdir():
        if child.name.casefold() == "data":
            continue
        _physical(child)
        metadata = child.lstat()
        entries.append((child.name, child, metadata))
        if stat.S_ISDIR(metadata.st_mode):
            children, _directories = _installed_tree_entries(child)
            entries.extend((f"{child.name}/{relative}", path, value)
                           for relative, path, value in children)
    entries.sort(key=lambda row: row[0])
    for relative, path, metadata in entries:
        target = destination.joinpath(*relative.split("/"))
        if stat.S_ISDIR(metadata.st_mode):
            target.mkdir(exist_ok=True)
        else:
            if getattr(metadata, "st_nlink", 1) != 1:
                raise ValueError("maintenance application contains a multiply-linked file")
            raw, current = _same_read(path)
            if (current.st_size, current.st_mtime_ns, current.st_ino) != (
                metadata.st_size, metadata.st_mtime_ns, metadata.st_ino
            ):
                raise ValueError("installed application changed during maintenance copy")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    from portable.release_contract import verify_installed_bundle

    verify_installed_bundle(destination)


def _wait_for_parent(pid: int) -> None:
    """Wait on the real launching process handle; never kill the user's application."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # already exited, no process by that id
            return
        raise OSError(ctypes.get_last_error(), "cannot wait for Atlas to close")
    try:
        if kernel.WaitForSingleObject(handle, 300_000) != 0:
            raise TimeoutError("Atlas did not release its application directory within 300 seconds")
    finally:
        kernel.CloseHandle(handle)


def _worker(request_path: Path) -> int:
    """Private installed-code handoff; the outer result never asserts publisher identity."""
    executable = Path(sys.executable).absolute()
    _physical(request_path)
    if request_path != executable.parent.parent / "request.json":
        raise ValueError("maintenance request must be beside its private application copy")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if (set(request) != {"schema", "parent_pid", "arguments", "result", "nonce"}
            or request["schema"] != "atlas.maintenance-request/1"
            or not isinstance(request["parent_pid"], int)
            or request["parent_pid"] <= 0
            or not isinstance(request["arguments"], list)
            or not all(isinstance(item, str) for item in request["arguments"])
            or request["nonce"] != request_path.parent.name.removeprefix("Atlas.maintenance-")):
        raise ValueError("unsupported maintenance handoff")
    result_path = Path(request["result"])
    outcome: dict = {
        "schema": RESULT_SCHEMA, "status": "refused", "exit_code": 1,
        "verifier_origin": "installed_atlas",
        "verification_policy": "sha256_bound_runtime_extension",
        "authentication": "operator_selected_digest_not_publisher_authentication",
        "nonce": request["nonce"],
    }
    try:
        _wait_for_parent(request["parent_pid"])
        root = request_path.parent.parent
        with _handoff_lock(root):
            pointer = json.loads((root / "Atlas.maintenance.json").read_text(encoding="utf-8"))
            if (pointer.get("worker_pid") != os.getpid()
                    or pointer.get("helper") != executable.relative_to(root).as_posix()
                    or pointer.get("request_sha256") != hashlib.sha256(request_path.read_bytes()).hexdigest()):
                raise ValueError("maintenance handoff was superseded or changed before worker activation")
            rc = _transaction(executable, request["arguments"], outcome)
        outcome.update(exit_code=rc, status="complete" if rc == 0 else "refused")
    except (OSError, ValueError, TimeoutError) as exc:
        outcome["error"] = str(exc)
    _write_result(result_path, outcome)
    return outcome["exit_code"]


def _recover(executable: Path, root: Path, result: Path | None) -> int:
    _physical(root)
    pointer_path = root / "Atlas.maintenance.json"
    _physical(pointer_path)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    helper = pointer.get("helper", "")
    if (pointer.get("schema") != "atlas.maintenance-recovery/1"
            or not isinstance(helper, str)
            or not re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe", helper)
            or executable != root.joinpath(*helper.split("/"))
            or hashlib.sha256(executable.read_bytes()).hexdigest() != pointer.get("helper_exe_sha256")):
        raise ValueError("recovery must use the recorded installed-version helper")
    request = executable.parent.parent / "request.json"
    _physical(request)
    if hashlib.sha256(request.read_bytes()).hexdigest() != pointer.get("request_sha256"):
        raise ValueError("recorded recovery request identity changed")
    value = json.loads(request.read_text(encoding="utf-8"))
    arguments = value.get("arguments", [])
    if (value.get("schema") != "atlas.maintenance-request/1"
            or not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments)
            or arguments[:2] != ["-Dest", str(root)]
            or not (root / "Atlas.update-state.json").is_file()):
        raise ValueError("no matching journaled maintenance request to recover")
    if "-TestFailAfter" in arguments:
        index = arguments.index("-TestFailAfter")
        arguments = arguments[:index] + arguments[index + 2:]
    if result is not None:
        result = _result_path(root, str(result), uuid.uuid4().hex)
    outcome: dict = {
        "schema": RESULT_SCHEMA, "verifier_origin": "installed_atlas",
        "verification_policy": "sha256_bound_runtime_extension",
        "authentication": "operator_selected_digest_not_publisher_authentication",
    }
    with _handoff_lock(root):
        rc = _transaction(executable, arguments, outcome)
    outcome.update(status="complete" if rc == 0 else "refused", exit_code=rc)
    if result is not None:
        _write_result(result, outcome)
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install, update or roll back portable Atlas")
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
    args = parser.parse_args(argv)
    try:
        if os.name != "nt" or not getattr(sys, "frozen", False):
            raise ValueError("installation and updates require the bundled Windows Atlas.exe")
        if args.maintenance_worker:
            return _worker(Path(args.maintenance_worker).absolute())
        executable = Path(sys.executable).absolute()
        if args.recover:
            return _recover(executable, Path(args.recover).absolute(),
                            Path(args.maintenance_result).absolute() if args.maintenance_result else None)
        source = executable.parent
        root = Path(args.install or args.dest or source.parent).absolute()
        _physical(root)
        if root == source or (source.is_relative_to(root / "Atlas") and args.install):
            raise ValueError("first installation must run from a separately extracted Atlas folder")
        if args.package and not args.install:
            raise ValueError("--package requires --install")
        if args.restore_pre_update_database and not args.rollback:
            raise ValueError("--restore-pre-update-database requires --rollback")
        package = args.package if args.install else args.update
        if not args.rollback:
            if not package:
                raise ValueError("--install requires --package ZIP and its published --expected-sha256")
            digest = args.expected_sha256 or ""
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("supply the published lowercase --expected-sha256 for this ZIP")
            package_path = Path(package).absolute()
            _physical(package_path)
            from portable.release_contract import _read_zip_path

            if hashlib.sha256(_read_zip_path(package_path)).hexdigest() != digest:
                raise ValueError("package SHA-256 differs from the published SHA-256 expectation")
        root.mkdir(parents=True, exist_ok=True)
        transaction_args = ["-Dest", str(root)]
        if args.rollback:
            transaction_args.append("-Rollback")
            if args.restore_pre_update_database:
                transaction_args.append("-RestorePreUpdateDatabase")
        else:
            transaction_args.extend(["-Package", str(package_path), "-ExpectedSha256", digest])
        if args.test_fail_after:
            transaction_args.extend(["-TestFailAfter", args.test_fail_after])
        if args.install:
            if (root / "Atlas.update-state.json").exists():
                journal = root / "Atlas.update-state.json"
                _physical(journal)
                state = json.loads(journal.read_text(encoding="utf-8"))
                if (state.get("schema") != "atlas.portable-transaction/2"
                        or state.get("operation") != "update" or state.get("had_active") is not False
                        or state.get("candidate_identity", {}).get("package_sha256") != digest):
                    raise ValueError("existing update journal requires its recorded installed-version recovery helper")
                return _transaction(executable, transaction_args)
            if (root / "Atlas").exists():
                raise ValueError("Atlas already exists here; use that installed Atlas.exe --update")
            return _transaction(executable, transaction_args)
        if source != root / "Atlas":
            raise ValueError("update and rollback must be launched by the installed Atlas.exe")
        # Leave the active executable and its DLLs before renaming any application slot.
        # A unique result path makes dispatch success distinct from transaction completion.
        nonce = uuid.uuid4().hex
        result = _result_path(root, args.maintenance_result, nonce)
        with _handoff_lock(root):
            helper = root / f"Atlas.maintenance-{nonce}"
            helper.mkdir()
            copied = helper / "Atlas"
            _copy_installed_application(source, copied)
            request = helper / "request.json"
            _write_result(request, {
                "schema": "atlas.maintenance-request/1", "parent_pid": os.getpid(),
                "arguments": transaction_args, "result": str(result), "nonce": nonce,
            })
            pointer = {
                "schema": "atlas.maintenance-recovery/1",
                "helper": (copied / "Atlas.exe").relative_to(root).as_posix(),
                "helper_exe_sha256": hashlib.sha256((copied / "Atlas.exe").read_bytes()).hexdigest(),
                "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
            }
            _write_result(root / "Atlas.maintenance.json", pointer)
            _retire_helpers(root, helper)
            worker = subprocess.Popen(
                [str(copied / "Atlas.exe"), "--maintenance-worker", str(request)],
                cwd=str(helper), close_fds=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
            pointer["worker_pid"] = worker.pid
            _write_result(root / "Atlas.maintenance.json", pointer)
        print(json.dumps({"status": "scheduled", "result": str(result),
                          "message": "Atlas is closing; wait for status complete in the result file."}))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Atlas maintenance REFUSED: {exc}", file=sys.stderr)
        return 1
