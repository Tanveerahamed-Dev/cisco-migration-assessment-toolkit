"""Private Win32 DEBUG_PROCESS event engine for the R2.0 incomplete collector.

The engine owns only the creator-thread Wait/Continue state machine.  It does not build Atlas
evidence, decide coverage, read remote pointers, claim operating-system losslessness, or supply
authority.  The public owner in :mod:`transition_runtime_discovery` tokenizes and validates the
returned primitive records before any evidence can be sealed.
"""

from __future__ import annotations

import ctypes
import platform
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import NoReturn


DEBUG_PROCESS_CREATION_FLAG = 0x00000001
DEBUG_ONLY_THIS_PROCESS_CREATION_FLAG = 0x00000002

_EXCEPTION_DEBUG_EVENT = 1
_CREATE_THREAD_DEBUG_EVENT = 2
_CREATE_PROCESS_DEBUG_EVENT = 3
_EXIT_THREAD_DEBUG_EVENT = 4
_EXIT_PROCESS_DEBUG_EVENT = 5
_LOAD_DLL_DEBUG_EVENT = 6
_UNLOAD_DLL_DEBUG_EVENT = 7
_OUTPUT_DEBUG_STRING_EVENT = 8
_RIP_EVENT = 9

_EXCEPTION_BREAKPOINT = 0x80000003
_DBG_CONTINUE = 0x00010002
_DBG_EXCEPTION_NOT_HANDLED = 0x80010001
_ERROR_SEM_TIMEOUT = 121

_MAX_DEBUG_EVENTS = 16_384
_MAX_DEBUG_PROCESSES = 256
_MAX_DEBUG_THREADS = 4_096
_MAX_DEBUG_IMAGE_MAPPINGS = 16_384


class _ExceptionRecord(ctypes.Structure):
    pass


_ExceptionRecord._fields_ = [
    ("ExceptionCode", wintypes.DWORD),
    ("ExceptionFlags", wintypes.DWORD),
    ("ExceptionRecord", ctypes.POINTER(_ExceptionRecord)),
    ("ExceptionAddress", wintypes.LPVOID),
    ("NumberParameters", wintypes.DWORD),
    ("ExceptionInformation", ctypes.c_size_t * 15),
]


class _ExceptionDebugInfo(ctypes.Structure):
    _fields_ = [
        ("ExceptionRecord", _ExceptionRecord),
        ("dwFirstChance", wintypes.DWORD),
    ]


class _CreateThreadDebugInfo(ctypes.Structure):
    _fields_ = [
        ("hThread", wintypes.HANDLE),
        ("lpThreadLocalBase", wintypes.LPVOID),
        ("lpStartAddress", wintypes.LPVOID),
    ]


class _CreateProcessDebugInfo(ctypes.Structure):
    _fields_ = [
        ("hFile", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("lpBaseOfImage", wintypes.LPVOID),
        ("dwDebugInfoFileOffset", wintypes.DWORD),
        ("nDebugInfoSize", wintypes.DWORD),
        ("lpThreadLocalBase", wintypes.LPVOID),
        ("lpStartAddress", wintypes.LPVOID),
        ("lpImageName", wintypes.LPVOID),
        ("fUnicode", wintypes.WORD),
    ]


class _ExitThreadDebugInfo(ctypes.Structure):
    _fields_ = [("dwExitCode", wintypes.DWORD)]


class _ExitProcessDebugInfo(ctypes.Structure):
    _fields_ = [("dwExitCode", wintypes.DWORD)]


class _LoadDllDebugInfo(ctypes.Structure):
    _fields_ = [
        ("hFile", wintypes.HANDLE),
        ("lpBaseOfDll", wintypes.LPVOID),
        ("dwDebugInfoFileOffset", wintypes.DWORD),
        ("nDebugInfoSize", wintypes.DWORD),
        ("lpImageName", wintypes.LPVOID),
        ("fUnicode", wintypes.WORD),
    ]


class _UnloadDllDebugInfo(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", wintypes.LPVOID)]


class _OutputDebugStringInfo(ctypes.Structure):
    _fields_ = [
        ("lpDebugStringData", wintypes.LPVOID),
        ("fUnicode", wintypes.WORD),
        ("nDebugStringLength", wintypes.WORD),
    ]


class _RipInfo(ctypes.Structure):
    _fields_ = [("dwError", wintypes.DWORD), ("dwType", wintypes.DWORD)]


class _DebugEventUnion(ctypes.Union):
    _fields_ = [
        ("Exception", _ExceptionDebugInfo),
        ("CreateThread", _CreateThreadDebugInfo),
        ("CreateProcessInfo", _CreateProcessDebugInfo),
        ("ExitThread", _ExitThreadDebugInfo),
        ("ExitProcess", _ExitProcessDebugInfo),
        ("LoadDll", _LoadDllDebugInfo),
        ("UnloadDll", _UnloadDllDebugInfo),
        ("DebugString", _OutputDebugStringInfo),
        ("RipInfo", _RipInfo),
    ]


class _DebugEvent(ctypes.Structure):
    _fields_ = [
        ("dwDebugEventCode", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
        ("u", _DebugEventUnion),
    ]


class DebugEventEngineError(RuntimeError):
    """Stable, non-echoing failure from the private debugger engine."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise DebugEventEngineError(code)


@dataclass(frozen=True)
class DebugEventRecord:
    """One copied primitive event; it contains no live ctypes views or raw handles."""

    sequence: int
    event: str
    event_code: int
    process_id: int
    thread_id: int
    mapping_base: int | None
    mapping_kind: str | None
    continue_status: str
    exception_code: int | None
    exception_disposition: str | None
    first_chance: bool | None
    exit_code: int | None
    file_handle_present: bool | None
    debug_string_code_units: int | None
    debug_string_unicode: bool | None
    implicit_unmap_bases: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class DebugEventCapture:
    """Completed internal debugger ledger; raw IDs never leave the public owner."""

    root_process_id: int
    records: tuple[DebugEventRecord, ...]
    created_process_ids: tuple[int, ...]
    exited_process_ids: tuple[int, ...]
    initial_breakpoint_process_ids: tuple[int, ...]
    continued_event_count: int
    wait_failure_count: int
    continue_failure_count: int
    handle_close_failure_count: int


def _assert_amd64_layout() -> None:
    if (
        ctypes.sizeof(ctypes.c_void_p) != 8
        or platform.machine().upper() not in {"AMD64", "X86_64"}
        or ctypes.sizeof(_ExceptionRecord) != 152
        or _ExceptionRecord.ExceptionInformation.offset != 32
        or ctypes.sizeof(_ExceptionDebugInfo) != 160
        or _ExceptionDebugInfo.dwFirstChance.offset != 152
        or ctypes.sizeof(_CreateThreadDebugInfo) != 24
        or ctypes.sizeof(_CreateProcessDebugInfo) != 72
        or _CreateProcessDebugInfo.fUnicode.offset != 64
        or ctypes.sizeof(_LoadDllDebugInfo) != 40
        or _LoadDllDebugInfo.fUnicode.offset != 32
        or ctypes.sizeof(_OutputDebugStringInfo) != 16
        or ctypes.sizeof(_DebugEventUnion) != 160
        or ctypes.sizeof(_DebugEvent) != 176
        or _DebugEvent.u.offset != 16
    ):
        _fail("WINDOWS_DEBUG_AMD64_ABI_REQUIRED")


def _positive_dword(value: int, code: str) -> int:
    checked = int(value)
    if checked <= 0 or checked > 0xFFFFFFFF:
        _fail(code)
    return checked


def _pointer_value(value: object, code: str) -> int:
    try:
        checked = int(value or 0)
    except (TypeError, ValueError):
        _fail(code)
    if checked <= 0 or checked > 0xFFFFFFFFFFFFFFFF:
        _fail(code)
    return checked


class WindowsDebugEventSession:
    """Creator-thread DEBUG_PROCESS event ledger for one already-created root process."""

    __slots__ = (
        "_active_mappings",
        "_close_failures",
        "_continue_failures",
        "_continued",
        "_created",
        "_creator_thread",
        "_exited",
        "_fatal_error",
        "_initial_breakpoints",
        "_kernel32",
        "_kill_on_exit_configured",
        "_live_processes",
        "_live_threads",
        "_records",
        "_root_pid",
        "_seen_threads",
        "_wait_failures",
    )

    def __init__(self, root_process_id: int) -> None:
        _assert_amd64_layout()
        if type(root_process_id) is not int:
            _fail("WINDOWS_DEBUG_ROOT_PROCESS_INVALID")
        root_pid = _positive_dword(root_process_id, "WINDOWS_DEBUG_ROOT_PROCESS_INVALID")
        self._initialize(root_pid)
        self._configure_kill_on_exit()

    @classmethod
    def prepare(cls) -> WindowsDebugEventSession:
        """Bind the debug API before launch; configure kill-on-exit only after root creation."""

        _assert_amd64_layout()
        prepared = object.__new__(cls)
        prepared._initialize(None)
        return prepared

    def _initialize(self, root_process_id: int | None) -> None:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.WaitForDebugEventEx.argtypes = (
                ctypes.POINTER(_DebugEvent),
                wintypes.DWORD,
            )
            kernel32.WaitForDebugEventEx.restype = wintypes.BOOL
            kernel32.ContinueDebugEvent.argtypes = (
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            kernel32.ContinueDebugEvent.restype = wintypes.BOOL
            kernel32.DebugSetProcessKillOnExit.argtypes = (wintypes.BOOL,)
            kernel32.DebugSetProcessKillOnExit.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
        except (AttributeError, OSError):
            _fail("WINDOWS_DEBUG_API_UNAVAILABLE")
        self._kernel32 = kernel32
        self._root_pid = root_process_id
        self._creator_thread = threading.get_ident()
        self._records: list[DebugEventRecord] = []
        self._created: set[int] = set()
        self._exited: set[int] = set()
        self._live_processes: set[int] = set()
        self._seen_threads: set[int] = set()
        self._live_threads: dict[int, int] = {}
        self._active_mappings: dict[tuple[int, int], str] = {}
        self._initial_breakpoints: set[int] = set()
        self._continued = 0
        self._wait_failures = 0
        self._continue_failures = 0
        self._close_failures = 0
        self._fatal_error: str | None = None
        self._kill_on_exit_configured = False

    def _configure_kill_on_exit(self) -> None:
        self._require_creator_thread()
        if self._root_pid is None or self._kill_on_exit_configured:
            _fail("WINDOWS_DEBUG_KILL_ON_EXIT_CONFIGURATION_FAILED")
        if not self._kernel32.DebugSetProcessKillOnExit(True):
            self._fatal_error = "WINDOWS_DEBUG_KILL_ON_EXIT_CONFIGURATION_FAILED"
            _fail("WINDOWS_DEBUG_KILL_ON_EXIT_CONFIGURATION_FAILED")
        self._kill_on_exit_configured = True

    def bind_root_process(self, root_process_id: int) -> None:
        """Bind one prepared, unused session to the process created with DEBUG_PROCESS."""

        self._require_creator_thread()
        if type(root_process_id) is not int:
            _fail("WINDOWS_DEBUG_ROOT_PROCESS_INVALID")
        root_pid = _positive_dword(root_process_id, "WINDOWS_DEBUG_ROOT_PROCESS_INVALID")
        if (
            self._root_pid is not None
            or self._records
            or self._created
            or self._continued
            or self._fatal_error is not None
        ):
            _fail("WINDOWS_DEBUG_ROOT_PROCESS_ALREADY_BOUND")
        self._root_pid = root_pid
        self._configure_kill_on_exit()

    def _require_creator_thread(self) -> None:
        if threading.get_ident() != self._creator_thread:
            _fail("WINDOWS_DEBUG_CREATOR_THREAD_REQUIRED")

    @property
    def root_create_observed(self) -> bool:
        return self._root_pid is not None and self._root_pid in self._created

    @property
    def all_processes_exited(self) -> bool:
        return bool(self._created) and not self._live_processes

    @property
    def live_process_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._live_processes))

    def process_created(self, process_id: int) -> bool:
        return type(process_id) is int and process_id in self._created

    def initial_breakpoint_observed(self, process_id: int) -> bool:
        return type(process_id) is int and process_id in self._initial_breakpoints

    def detach_for_abort(self, process_ids: tuple[int, ...]) -> bool:
        """Best-effort bounded-failure detach; never contributes to sealable evidence."""

        self._require_creator_thread()
        if type(process_ids) is not tuple or any(type(item) is not int for item in process_ids):
            _fail("WINDOWS_DEBUG_ABORT_PROCESS_SET_INVALID")
        candidates = set(process_ids) | self._created | self._live_processes
        if self._root_pid is not None:
            candidates.add(self._root_pid)
        try:
            stop = self._kernel32.DebugActiveProcessStop
            stop.argtypes = (wintypes.DWORD,)
            stop.restype = wintypes.BOOL
        except AttributeError:
            return False
        detached = False
        for process_id in sorted(candidates):
            if 0 < process_id <= 0xFFFFFFFF and stop(wintypes.DWORD(process_id)):
                detached = True
        return detached

    def _close_event_file(self, handle: int) -> bool:
        if not handle:
            return True
        if not self._kernel32.CloseHandle(wintypes.HANDLE(handle)):
            self._close_failures += 1
            return False
        return True

    def _record_for_event(
        self, event: _DebugEvent
    ) -> tuple[DebugEventRecord, int, int, bool, str | None]:
        code = int(event.dwDebugEventCode)
        pid = _positive_dword(int(event.dwProcessId), "WINDOWS_DEBUG_EVENT_PROCESS_INVALID")
        tid = _positive_dword(int(event.dwThreadId), "WINDOWS_DEBUG_EVENT_THREAD_INVALID")
        sequence = len(self._records)
        if sequence >= _MAX_DEBUG_EVENTS:
            _fail("WINDOWS_DEBUG_EVENT_CEILING_EXCEEDED")
        mapping_base: int | None = None
        mapping_kind: str | None = None
        exception_code: int | None = None
        disposition: str | None = None
        first_chance: bool | None = None
        exit_code: int | None = None
        file_present: bool | None = None
        string_bytes: int | None = None
        string_unicode: bool | None = None
        implicit: tuple[tuple[int, str], ...] = ()
        status = _DBG_CONTINUE
        status_name = "DBG_CONTINUE"
        event_name: str
        event_file_handle = 0
        fatal_after_continue: str | None = None

        if code == _CREATE_PROCESS_DEBUG_EVENT:
            event_name = "CREATE_PROCESS"
            if (
                pid in self._created
                or pid in self._exited
                or tid in self._seen_threads
                or len(self._created) >= _MAX_DEBUG_PROCESSES
                or len(self._seen_threads) >= _MAX_DEBUG_THREADS
            ):
                _fail("WINDOWS_DEBUG_PROCESS_LIFECYCLE_INVALID")
            if not self._records and pid != self._root_pid:
                _fail("WINDOWS_DEBUG_ROOT_CREATE_EVENT_REQUIRED")
            if self._records and pid == self._root_pid:
                _fail("WINDOWS_DEBUG_ROOT_CREATE_EVENT_REQUIRED")
            mapping_base = _pointer_value(
                event.u.CreateProcessInfo.lpBaseOfImage,
                "WINDOWS_DEBUG_IMAGE_BASE_INVALID",
            )
            key = (pid, mapping_base)
            if key in self._active_mappings or len(self._active_mappings) >= _MAX_DEBUG_IMAGE_MAPPINGS:
                _fail("WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID")
            event_file_handle = int(event.u.CreateProcessInfo.hFile or 0)
            file_present = bool(event_file_handle)
            mapping_kind = "PROCESS_IMAGE"
            self._created.add(pid)
            self._live_processes.add(pid)
            self._seen_threads.add(tid)
            self._live_threads[tid] = pid
            self._active_mappings[key] = mapping_kind
        elif code == _CREATE_THREAD_DEBUG_EVENT:
            event_name = "CREATE_THREAD"
            if (
                pid not in self._live_processes
                or tid in self._seen_threads
                or len(self._seen_threads) >= _MAX_DEBUG_THREADS
            ):
                _fail("WINDOWS_DEBUG_THREAD_LIFECYCLE_INVALID")
            self._seen_threads.add(tid)
            self._live_threads[tid] = pid
        elif code == _EXIT_THREAD_DEBUG_EVENT:
            event_name = "EXIT_THREAD"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_THREAD_LIFECYCLE_INVALID")
            exit_code = int(event.u.ExitThread.dwExitCode)
            del self._live_threads[tid]
        elif code == _EXCEPTION_DEBUG_EVENT:
            event_name = "EXCEPTION"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_EXCEPTION_LIFECYCLE_INVALID")
            record = event.u.Exception.ExceptionRecord
            if int(record.NumberParameters) > 15:
                _fail("WINDOWS_DEBUG_EXCEPTION_RECORD_INVALID")
            exception_code = int(record.ExceptionCode)
            first_chance = bool(event.u.Exception.dwFirstChance)
            if (
                first_chance
                and exception_code == _EXCEPTION_BREAKPOINT
                and pid not in self._initial_breakpoints
            ):
                self._initial_breakpoints.add(pid)
                disposition = "INITIAL_BREAKPOINT_HANDLED"
            else:
                status = _DBG_EXCEPTION_NOT_HANDLED
                status_name = "DBG_EXCEPTION_NOT_HANDLED"
                disposition = "PASSED_TO_DEBUGGEE"
                if not first_chance:
                    fatal_after_continue = "WINDOWS_DEBUG_SECOND_CHANCE_EXCEPTION"
        elif code == _LOAD_DLL_DEBUG_EVENT:
            event_name = "LOAD_DLL"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID")
            mapping_base = _pointer_value(
                event.u.LoadDll.lpBaseOfDll, "WINDOWS_DEBUG_IMAGE_BASE_INVALID"
            )
            key = (pid, mapping_base)
            if key in self._active_mappings or len(self._active_mappings) >= _MAX_DEBUG_IMAGE_MAPPINGS:
                _fail("WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID")
            event_file_handle = int(event.u.LoadDll.hFile or 0)
            file_present = bool(event_file_handle)
            mapping_kind = "DLL_IMAGE"
            self._active_mappings[key] = mapping_kind
        elif code == _UNLOAD_DLL_DEBUG_EVENT:
            event_name = "UNLOAD_DLL"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID")
            mapping_base = _pointer_value(
                event.u.UnloadDll.lpBaseOfDll, "WINDOWS_DEBUG_IMAGE_BASE_INVALID"
            )
            key = (pid, mapping_base)
            if self._active_mappings.get(key) != "DLL_IMAGE":
                _fail("WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID")
            mapping_kind = "DLL_IMAGE"
            del self._active_mappings[key]
        elif code == _OUTPUT_DEBUG_STRING_EVENT:
            event_name = "OUTPUT_DEBUG_STRING"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_STRING_LIFECYCLE_INVALID")
            string_bytes = int(event.u.DebugString.nDebugStringLength)
            string_unicode = bool(event.u.DebugString.fUnicode)
        elif code == _EXIT_PROCESS_DEBUG_EVENT:
            event_name = "EXIT_PROCESS"
            if pid not in self._live_processes or self._live_threads.get(tid) != pid:
                _fail("WINDOWS_DEBUG_PROCESS_LIFECYCLE_INVALID")
            exit_code = int(event.u.ExitProcess.dwExitCode)
            implicit = tuple(sorted(
                (base, kind)
                for (owner, base), kind in self._active_mappings.items()
                if owner == pid
            ))
            for base, _kind in implicit:
                del self._active_mappings[(pid, base)]
            for thread_id, owner in tuple(self._live_threads.items()):
                if owner == pid:
                    del self._live_threads[thread_id]
            self._live_processes.remove(pid)
            self._exited.add(pid)
            if exit_code != 0:
                fatal_after_continue = "WINDOWS_DEBUG_PROCESS_EXIT_FAILED"
        elif code == _RIP_EVENT:
            event_name = "RIP"
            fatal_after_continue = "WINDOWS_DEBUG_RIP_EVENT"
        else:
            event_name = "UNKNOWN"
            fatal_after_continue = "WINDOWS_DEBUG_EVENT_CODE_INVALID"

        copied = DebugEventRecord(
            sequence=sequence,
            event=event_name,
            event_code=code,
            process_id=pid,
            thread_id=tid,
            mapping_base=mapping_base,
            mapping_kind=mapping_kind,
            continue_status=status_name,
            exception_code=exception_code,
            exception_disposition=disposition,
            first_chance=first_chance,
            exit_code=exit_code,
            file_handle_present=file_present,
            debug_string_code_units=string_bytes,
            debug_string_unicode=string_unicode,
            implicit_unmap_bases=implicit,
        )
        return copied, status, event_file_handle, bool(event_file_handle), fatal_after_continue

    def pump(self, timeout_milliseconds: int) -> bool:
        """Wait for and continue at most one event; return false only for a real timeout."""

        self._require_creator_thread()
        if (
            type(timeout_milliseconds) is not int
            or not 0 <= timeout_milliseconds <= 60_000
        ):
            _fail("WINDOWS_DEBUG_WAIT_TIMEOUT_INVALID")
        event = _DebugEvent()
        ctypes.set_last_error(0)
        if not self._kernel32.WaitForDebugEventEx(
            ctypes.byref(event), wintypes.DWORD(timeout_milliseconds)
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_SEM_TIMEOUT:
                return False
            self._wait_failures += 1
            self._fatal_error = "WINDOWS_DEBUG_WAIT_FAILED"
            _fail("WINDOWS_DEBUG_WAIT_FAILED")
        copied: DebugEventRecord | None = None
        status = _DBG_CONTINUE
        code = int(event.dwDebugEventCode)
        event_file_handle = (
            int(event.u.CreateProcessInfo.hFile or 0)
            if code == _CREATE_PROCESS_DEBUG_EVENT
            else int(event.u.LoadDll.hFile or 0)
            if code == _LOAD_DLL_DEBUG_EVENT
            else 0
        )
        fatal_after_continue: str | None = None
        record_error: str | None = None
        close_ok = True
        try:
            copied, status, _returned_handle, _present, fatal_after_continue = (
                self._record_for_event(event)
            )
            if _returned_handle != event_file_handle:
                _fail("WINDOWS_DEBUG_EVENT_HANDLE_INVALID")
        except DebugEventEngineError as error:
            record_error = error.code
            status = (
                _DBG_EXCEPTION_NOT_HANDLED
                if code == _EXCEPTION_DEBUG_EVENT
                else _DBG_CONTINUE
            )
        finally:
            if event_file_handle:
                close_ok = self._close_event_file(event_file_handle)
        if copied is not None:
            self._records.append(copied)
        if not self._kernel32.ContinueDebugEvent(
            wintypes.DWORD(event.dwProcessId),
            wintypes.DWORD(event.dwThreadId),
            wintypes.DWORD(status),
        ):
            self._continue_failures += 1
            self._fatal_error = "WINDOWS_DEBUG_CONTINUE_FAILED"
            _fail("WINDOWS_DEBUG_CONTINUE_FAILED")
        self._continued += 1
        if not close_ok:
            self._fatal_error = "WINDOWS_DEBUG_EVENT_HANDLE_CLOSE_FAILED"
            _fail("WINDOWS_DEBUG_EVENT_HANDLE_CLOSE_FAILED")
        if record_error is not None:
            self._fatal_error = record_error
            _fail(record_error)
        if fatal_after_continue is not None:
            self._fatal_error = fatal_after_continue
            _fail(fatal_after_continue)
        return True

    def snapshot(self) -> DebugEventCapture:
        """Return a detached immutable ledger only after every created process exited."""

        self._require_creator_thread()
        if (
            not self._created
            or self._root_pid is None
            or self._root_pid not in self._created
            or self._created != self._exited
            or self._initial_breakpoints != self._created
            or self._live_processes
            or self._live_threads
            or self._active_mappings
            or self._continued != len(self._records)
            or self._wait_failures
            or self._continue_failures
            or self._close_failures
            or self._fatal_error is not None
            or not self._kill_on_exit_configured
        ):
            _fail("WINDOWS_DEBUG_CAPTURE_INCOMPLETE")
        return DebugEventCapture(
            root_process_id=self._root_pid,
            records=tuple(self._records),
            created_process_ids=tuple(sorted(self._created)),
            exited_process_ids=tuple(sorted(self._exited)),
            initial_breakpoint_process_ids=tuple(sorted(self._initial_breakpoints)),
            continued_event_count=self._continued,
            wait_failure_count=self._wait_failures,
            continue_failure_count=self._continue_failures,
            handle_close_failure_count=self._close_failures,
        )


__all__ = [
    "DEBUG_ONLY_THIS_PROCESS_CREATION_FLAG",
    "DEBUG_PROCESS_CREATION_FLAG",
    "DebugEventCapture",
    "DebugEventEngineError",
    "DebugEventRecord",
    "WindowsDebugEventSession",
]
