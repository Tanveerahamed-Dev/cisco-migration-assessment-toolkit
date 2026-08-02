#!/usr/bin/env python
"""One-command dev mode for AssessHub: FastAPI + Vite (HMR), together.

    python webapp/dev.py

Backend on http://127.0.0.1:8000, UI on http://localhost:5173 (hot-reloads on frontend changes
and proxies /api -> :8000). Ctrl+C stops both. On POSIX the backend also auto-reloads; Windows
avoids Uvicorn's reloader parent/child split so teardown cannot strand a server process.

For a production-style single-origin run instead, build the frontend (`npm run build` in
webapp/frontend) and serve only uvicorn — see webapp/README.md.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FRONTEND = os.path.join(HERE, "frontend")
_WINDOWS_JOB_ATTR = "_assesshub_job_handle"


def _is_windows() -> bool:
    return os.name == "nt"


def _assign_windows_job(proc: subprocess.Popen) -> None:
    """Own a Windows child tree even if its launcher exits before cleanup.

    ``CREATE_NEW_PROCESS_GROUP`` alone is not lifecycle ownership: once npm.cmd exits, taskkill
    can no longer discover its surviving Node descendants. A kill-on-close Job Object retains
    every descendant and is terminable through our saved handle independently of the leader PID.
    """
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(
                job, wintypes.HANDLE(proc._handle)):  # type: ignore[attr-defined]
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        kernel32.CloseHandle(job)
        raise
    setattr(proc, _WINDOWS_JOB_ATTR, job)


def _terminate_windows_job(proc: subprocess.Popen) -> bool:
    """Terminate and close an owned Job Object; true when this process had one."""
    handle = getattr(proc, _WINDOWS_JOB_ATTR, None)
    if not handle:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    try:
        kernel32.TerminateJobObject(handle, 1)
    finally:
        kernel32.CloseHandle(handle)
        setattr(proc, _WINDOWS_JOB_ATTR, None)
    return True


def _taskkill(proc: subprocess.Popen) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _spawn(cmd: list[str], cwd: str) -> subprocess.Popen:
    """Start each tool in a killable process tree."""
    kwargs = {}
    if _is_windows():
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=cwd, **kwargs)
    if _is_windows():
        try:
            _assign_windows_job(proc)
        except Exception:
            # A tree we cannot own must not be left running after a half-started dev launch.
            _taskkill(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            raise
    return proc


def _stop_tree(proc: subprocess.Popen) -> None:
    if _is_windows():
        # Job ownership remains valid after npm/Vite's launcher exits, unlike a PID tree lookup.
        if not _terminate_windows_job(proc):
            if proc.poll() is not None:
                return
            _taskkill(proc)
    else:
        # The process group can outlive its leader, so signal the saved PGID even after poll().
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if _is_windows():
            _taskkill(proc)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main() -> int:
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        print("frontend deps missing — run:  cd webapp/frontend && npm install", file=sys.stderr)
        return 1

    npm = "npm.cmd" if _is_windows() else "npm"
    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.app:create_default_app",
                   "--factory", "--app-dir", HERE, "--port", "8000"]
    if not _is_windows():
        backend_cmd.append("--reload")
    frontend_cmd = [npm, "run", "dev"]

    procs: list[subprocess.Popen] = []
    try:
        # cwd=REPO so both `backend.*` (via --app-dir) and `cisco_toolkit` resolve on sys.path.
        procs.append(_spawn(backend_cmd, REPO))
        procs.append(_spawn(frontend_cmd, FRONTEND))
        print("\n  AssessHub dev mode")
        reload_note = "   (autoreload)" if not _is_windows() else ""
        print(f"  API : http://127.0.0.1:8000{reload_note}")
        print("  UI  : http://localhost:5173   (HMR, proxies /api -> :8000)")
        print("  Ctrl+C to stop both.\n")
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"\n[dev] a process exited (code {p.returncode}); shutting down.", file=sys.stderr)
                    return p.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[dev] stopping…")
        return 0
    finally:
        for p in procs:
            _stop_tree(p)


if __name__ == "__main__":
    raise SystemExit(main())
