from __future__ import annotations

from collections import deque
from copy import deepcopy
import ctypes
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_runtime_discovery as discovery
from cisco_toolkit import _transition_runtime_debug as debug


ROOT = Path(__file__).resolve().parents[1]
_ROOT_PID = 100
_ROOT_TID = 10
_CHILD_PID = 200
_CHILD_TID = 20
_COMMIT = "a" * 40
_TREE = "b" * 40


def _integer(value: Any) -> int:
    return int(getattr(value, "value", value) or 0)


class _FakeFunction:
    def __init__(self, implementation: Callable[..., int]) -> None:
        self._implementation = implementation
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> int:
        return self._implementation(*args)


class _FakeKernel32:
    def __init__(
        self,
        events: list[debug._DebugEvent],
        last_error: list[int],
        *,
        close_result: bool = True,
        continue_result: bool = True,
    ) -> None:
        self.events = deque(events)
        self.last_error = last_error
        self.close_result = close_result
        self.continue_result = continue_result
        self.closed_handles: list[int] = []
        self.continues: list[tuple[int, int, int]] = []
        self.kill_on_exit_arguments: list[bool] = []
        self.WaitForDebugEventEx = _FakeFunction(self._wait)
        self.ContinueDebugEvent = _FakeFunction(self._continue)
        self.DebugSetProcessKillOnExit = _FakeFunction(self._kill_on_exit)
        self.CloseHandle = _FakeFunction(self._close)

    def _wait(self, event_pointer: Any, _timeout: Any) -> int:
        if not self.events:
            self.last_error[0] = debug._ERROR_SEM_TIMEOUT
            return 0
        event = self.events.popleft()
        ctypes.memmove(event_pointer, ctypes.byref(event), ctypes.sizeof(event))
        self.last_error[0] = 0
        return 1

    def _continue(self, process_id: Any, thread_id: Any, status: Any) -> int:
        self.continues.append(
            (_integer(process_id), _integer(thread_id), _integer(status))
        )
        return int(self.continue_result)

    def _kill_on_exit(self, enabled: Any) -> int:
        self.kill_on_exit_arguments.append(bool(enabled))
        return 1

    def _close(self, handle: Any) -> int:
        self.closed_handles.append(_integer(handle))
        return int(self.close_result)


def _event(
    code: int,
    *,
    pid: int = _ROOT_PID,
    tid: int = _ROOT_TID,
    base: int = 0x1000,
    file_handle: int = 0,
    exception_code: int = debug._EXCEPTION_BREAKPOINT,
    first_chance: bool = True,
    number_parameters: int = 0,
    exit_code: int = 0,
    remote_pointer: int = 0,
) -> debug._DebugEvent:
    event = debug._DebugEvent()
    event.dwDebugEventCode = code
    event.dwProcessId = pid
    event.dwThreadId = tid
    if code == debug._CREATE_PROCESS_DEBUG_EVENT:
        event.u.CreateProcessInfo.hFile = file_handle or None
        event.u.CreateProcessInfo.hProcess = 0x5000 + pid
        event.u.CreateProcessInfo.hThread = 0x6000 + tid
        event.u.CreateProcessInfo.lpBaseOfImage = base
        event.u.CreateProcessInfo.lpImageName = remote_pointer or None
    elif code == debug._CREATE_THREAD_DEBUG_EVENT:
        event.u.CreateThread.hThread = 0x6000 + tid
        event.u.CreateThread.lpThreadLocalBase = remote_pointer or None
        event.u.CreateThread.lpStartAddress = remote_pointer or None
    elif code == debug._EXIT_THREAD_DEBUG_EVENT:
        event.u.ExitThread.dwExitCode = exit_code
    elif code == debug._EXCEPTION_DEBUG_EVENT:
        event.u.Exception.ExceptionRecord.ExceptionCode = exception_code
        event.u.Exception.ExceptionRecord.NumberParameters = number_parameters
        event.u.Exception.ExceptionRecord.ExceptionAddress = remote_pointer or None
        event.u.Exception.dwFirstChance = int(first_chance)
    elif code == debug._LOAD_DLL_DEBUG_EVENT:
        event.u.LoadDll.hFile = file_handle or None
        event.u.LoadDll.lpBaseOfDll = base
        event.u.LoadDll.lpImageName = remote_pointer or None
    elif code == debug._UNLOAD_DLL_DEBUG_EVENT:
        event.u.UnloadDll.lpBaseOfDll = base
    elif code == debug._OUTPUT_DEBUG_STRING_EVENT:
        event.u.DebugString.lpDebugStringData = remote_pointer or None
        event.u.DebugString.fUnicode = 1
        event.u.DebugString.nDebugStringLength = 17
    elif code == debug._EXIT_PROCESS_DEBUG_EVENT:
        event.u.ExitProcess.dwExitCode = exit_code
    return event


def _install_fake_kernel(
    monkeypatch: pytest.MonkeyPatch,
    events: list[debug._DebugEvent],
    *,
    close_result: bool = True,
    continue_result: bool = True,
) -> _FakeKernel32:
    last_error = [0]
    kernel32 = _FakeKernel32(
        events,
        last_error,
        close_result=close_result,
        continue_result=continue_result,
    )
    monkeypatch.setattr(debug, "_assert_amd64_layout", lambda: None)
    monkeypatch.setattr(debug.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
    monkeypatch.setattr(
        debug.ctypes, "set_last_error", lambda value: last_error.__setitem__(0, value), raising=False
    )
    monkeypatch.setattr(debug.ctypes, "get_last_error", lambda: last_error[0], raising=False)
    return kernel32


def _fake_session(
    monkeypatch: pytest.MonkeyPatch,
    events: list[debug._DebugEvent],
    *,
    root_pid: int = _ROOT_PID,
    close_result: bool = True,
    continue_result: bool = True,
) -> tuple[debug.WindowsDebugEventSession, _FakeKernel32]:
    kernel32 = _install_fake_kernel(
        monkeypatch,
        events,
        close_result=close_result,
        continue_result=continue_result,
    )
    session = debug.WindowsDebugEventSession(root_pid)
    assert kernel32.kill_on_exit_arguments == [True]
    return session, kernel32


def _pump_queued(session: debug.WindowsDebugEventSession, kernel32: _FakeKernel32) -> None:
    while kernel32.events:
        assert session.pump(0) is True


def _complete_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[debug.DebugEventCapture, _FakeKernel32]:
    events = [
        _event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=101, base=0x1000),
        _event(debug._EXCEPTION_DEBUG_EVENT),
        _event(
            debug._CREATE_PROCESS_DEBUG_EVENT,
            pid=_CHILD_PID,
            tid=_CHILD_TID,
            file_handle=102,
            base=0x3000,
        ),
        _event(debug._EXCEPTION_DEBUG_EVENT, pid=_CHILD_PID, tid=_CHILD_TID),
        _event(debug._CREATE_THREAD_DEBUG_EVENT, tid=30),
        _event(debug._EXIT_THREAD_DEBUG_EVENT, tid=30),
        _event(
            debug._LOAD_DLL_DEBUG_EVENT,
            pid=_CHILD_PID,
            tid=_CHILD_TID,
            file_handle=103,
            base=0x4000,
        ),
        _event(
            debug._UNLOAD_DLL_DEBUG_EVENT,
            pid=_CHILD_PID,
            tid=_CHILD_TID,
            base=0x4000,
        ),
        _event(
            debug._LOAD_DLL_DEBUG_EVENT,
            pid=_CHILD_PID,
            tid=_CHILD_TID,
            file_handle=104,
            base=0x4000,
        ),
        _event(
            debug._EXIT_PROCESS_DEBUG_EVENT,
            pid=_CHILD_PID,
            tid=_CHILD_TID,
        ),
        _event(debug._EXIT_PROCESS_DEBUG_EVENT),
    ]
    session, kernel32 = _fake_session(monkeypatch, events)
    _pump_queued(session, kernel32)
    assert session.pump(0) is False
    return session.snapshot(), kernel32


@pytest.mark.skipif(
    os.name != "nt"
    or ctypes.sizeof(ctypes.c_void_p) != 8
    or platform.machine().upper() not in {"AMD64", "X86_64"},
    reason="exact Win32 AMD64 ABI only",
)
def test_debug_event_amd64_abi_is_exact() -> None:
    debug._assert_amd64_layout()
    assert ctypes.sizeof(debug._ExceptionRecord) == 152
    assert debug._ExceptionRecord.ExceptionInformation.offset == 32
    assert ctypes.sizeof(debug._ExceptionDebugInfo) == 160
    assert debug._ExceptionDebugInfo.dwFirstChance.offset == 152
    assert ctypes.sizeof(debug._CreateProcessDebugInfo) == 72
    assert debug._CreateProcessDebugInfo.fUnicode.offset == 64
    assert ctypes.sizeof(debug._LoadDllDebugInfo) == 40
    assert debug._LoadDllDebugInfo.fUnicode.offset == 32
    assert ctypes.sizeof(debug._DebugEventUnion) == 160
    assert ctypes.sizeof(debug._DebugEvent) == 176
    assert debug._DebugEvent.u.offset == 16
    assert debug._ExceptionRecord.ExceptionInformation.size == 15 * ctypes.sizeof(ctypes.c_size_t)


def test_debug_event_abi_guard_rejects_a_non_amd64_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(debug.platform, "machine", lambda: "ARM64")
    with pytest.raises(
        debug.DebugEventEngineError, match="^WINDOWS_DEBUG_AMD64_ABI_REQUIRED$"
    ):
        debug._assert_amd64_layout()


def test_prepared_session_configures_kill_on_exit_once_only_when_root_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _install_fake_kernel(monkeypatch, [])
    session = debug.WindowsDebugEventSession.prepare()
    assert kernel32.kill_on_exit_arguments == []

    session.bind_root_process(_ROOT_PID)
    assert kernel32.kill_on_exit_arguments == [True]
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_ROOT_PROCESS_ALREADY_BOUND$",
    ):
        session.bind_root_process(_ROOT_PID + 1)
    assert kernel32.kill_on_exit_arguments == [True]


def test_exception_dispositions_handle_only_the_first_initial_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        _event(debug._CREATE_PROCESS_DEBUG_EVENT),
        _event(debug._EXCEPTION_DEBUG_EVENT),
        _event(debug._EXCEPTION_DEBUG_EVENT),
        _event(debug._EXCEPTION_DEBUG_EVENT, exception_code=0xC0000005),
        _event(debug._EXIT_PROCESS_DEBUG_EVENT),
    ]
    session, kernel32 = _fake_session(monkeypatch, events)
    _pump_queued(session, kernel32)
    capture = session.snapshot()
    exceptions = [record for record in capture.records if record.event == "EXCEPTION"]
    assert [record.exception_disposition for record in exceptions] == [
        "INITIAL_BREAKPOINT_HANDLED",
        "PASSED_TO_DEBUGGEE",
        "PASSED_TO_DEBUGGEE",
    ]
    assert [record.continue_status for record in exceptions] == [
        "DBG_CONTINUE",
        "DBG_EXCEPTION_NOT_HANDLED",
        "DBG_EXCEPTION_NOT_HANDLED",
    ]
    assert [status for _pid, _tid, status in kernel32.continues] == [
        debug._DBG_CONTINUE,
        debug._DBG_CONTINUE,
        debug._DBG_EXCEPTION_NOT_HANDLED,
        debug._DBG_EXCEPTION_NOT_HANDLED,
        debug._DBG_CONTINUE,
    ]


def test_second_chance_exception_is_continued_not_handled_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(
                debug._EXCEPTION_DEBUG_EVENT,
                exception_code=0xC0000005,
                first_chance=False,
            ),
        ],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    with pytest.raises(
        debug.DebugEventEngineError, match="^WINDOWS_DEBUG_SECOND_CHANCE_EXCEPTION$"
    ):
        session.pump(0)
    assert kernel32.continues[-1] == (
        _ROOT_PID,
        _ROOT_TID,
        debug._DBG_EXCEPTION_NOT_HANDLED,
    )
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_nonzero_process_exit_latches_fatal_state_and_snapshot_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._EXIT_PROCESS_DEBUG_EVENT, exit_code=7),
        ],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_PROCESS_EXIT_FAILED$",
    ):
        session.pump(0)
    assert session.all_processes_exited is True
    assert len(kernel32.continues) == 3
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_create_process_file_handle_closes_once_when_event_parsing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, base=0, file_handle=0xABC)],
    )
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_IMAGE_BASE_INVALID$"):
        session.pump(0)
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.root_create_observed is False


def test_omitted_before_continue_observer_matches_explicit_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def complete(*, explicit_none: bool) -> tuple[debug.DebugEventCapture, _FakeKernel32]:
        session, kernel32 = _fake_session(
            monkeypatch,
            [
                _event(
                    debug._CREATE_PROCESS_DEBUG_EVENT,
                    file_handle=0xABC,
                ),
                _event(debug._EXCEPTION_DEBUG_EVENT),
                _event(debug._EXIT_PROCESS_DEBUG_EVENT),
            ],
        )
        while kernel32.events:
            if explicit_none:
                assert session.pump(0, before_continue=None) is True
            else:
                assert session.pump(0) is True
        return session.snapshot(), kernel32

    omitted_capture, omitted_kernel32 = complete(explicit_none=False)
    explicit_capture, explicit_kernel32 = complete(explicit_none=True)

    assert explicit_capture == omitted_capture
    assert explicit_kernel32.closed_handles == omitted_kernel32.closed_handles == [0xABC]
    assert explicit_kernel32.continues == omitted_kernel32.continues


def test_invalid_event_record_never_reaches_before_continue_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, base=0, file_handle=0xABC)],
    )
    observed: list[debug.DebugEventRecord] = []

    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_IMAGE_BASE_INVALID$"):
        session.pump(0, before_continue=observed.append)

    assert observed == []
    assert session.record_count == 0
    assert session.root_create_observed is False
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_before_continue_observer_receives_only_a_detached_suspended_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    observed: list[debug.DebugEventRecord] = []

    def observe(record: debug.DebugEventRecord) -> None:
        assert session.record_count == 0
        assert kernel32.continues == []
        assert kernel32.closed_handles == [0xABC]
        with pytest.raises(FrozenInstanceError):
            record.sequence = 7  # type: ignore[misc]
        observed.append(record)

    assert session.pump(0, before_continue=observe) is True
    assert len(observed) == 1
    assert observed[0].event == "CREATE_PROCESS"
    assert session.record_count == 1
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_before_continue_observer_failure_closes_continues_once_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )

    def fail(_record: debug.DebugEventRecord) -> None:
        raise KeyboardInterrupt

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_OBSERVER_FAILED$",
    ):
        session.pump(0, before_continue=fail)
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.record_count == 1
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_before_continue_observer_is_validated_before_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT)],
    )
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_OBSERVER_INVALID$",
    ):
        session.pump(0, before_continue=object())  # type: ignore[arg-type]
    assert len(kernel32.events) == 1
    assert kernel32.continues == []


def test_continue_failure_never_appends_the_observed_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT)],
        continue_result=False,
    )
    observed: list[debug.DebugEventRecord] = []
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_CONTINUE_FAILED$",
    ):
        session.pump(0, before_continue=observed.append)
    assert len(observed) == 1
    assert session.record_count == 0
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_before_continue_observer_cannot_reenter_the_event_pump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
        ],
    )
    errors: list[str] = []

    def observe(_record: debug.DebugEventRecord) -> None:
        try:
            session.pump(0)
        except debug.DebugEventEngineError as error:
            errors.append(error.code)

    assert session.pump(0, before_continue=observe) is True
    assert errors == ["WINDOWS_DEBUG_EVENT_OBSERVER_REENTRANT"]
    assert len(kernel32.events) == 1
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_event_handle_close_failure_precedes_observer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
        close_result=False,
    )
    observed: list[debug.DebugEventRecord] = []

    def fail(record: debug.DebugEventRecord) -> None:
        observed.append(record)
        raise RuntimeError("must not escape")

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_HANDLE_CLOSE_FAILED$",
    ):
        session.pump(0, before_continue=fail)

    assert len(observed) == 1
    assert session.record_count == 1
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_intrinsic_fatal_event_precedes_observer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._EXIT_PROCESS_DEBUG_EVENT, exit_code=7),
        ],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    observed: list[debug.DebugEventRecord] = []

    def fail(record: debug.DebugEventRecord) -> None:
        observed.append(record)
        raise RuntimeError("must not escape")

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_PROCESS_EXIT_FAILED$",
    ):
        session.pump(0, before_continue=fail)

    assert len(observed) == 1
    assert observed[0].event == "EXIT_PROCESS"
    assert session.record_count == 3
    assert session.all_processes_exited is True
    assert len(kernel32.continues) == 3
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_real_timeout_never_invokes_before_continue_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(monkeypatch, [])
    observed: list[debug.DebugEventRecord] = []

    assert session.pump(0, before_continue=observed.append) is False
    assert observed == []
    assert session.record_count == 0
    assert kernel32.closed_handles == []
    assert kernel32.continues == []


def test_load_dll_file_handle_closes_once_on_duplicate_active_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._LOAD_DLL_DEBUG_EVENT, base=0x2000, file_handle=0xAAA),
            _event(debug._LOAD_DLL_DEBUG_EVENT, base=0x2000, file_handle=0xBBB),
        ],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    assert session.pump(0) is True
    with pytest.raises(
        debug.DebugEventEngineError, match="^WINDOWS_DEBUG_IMAGE_LIFECYCLE_INVALID$"
    ):
        session.pump(0)
    assert kernel32.closed_handles == [0xAAA, 0xBBB]
    assert kernel32.continues[-1] == (_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)


def test_create_process_consumes_and_enforces_the_total_thread_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(debug, "_MAX_DEBUG_THREADS", 1)
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(
                debug._CREATE_PROCESS_DEBUG_EVENT,
                pid=_CHILD_PID,
                tid=_CHILD_TID,
                base=0x3000,
                file_handle=0xCEE,
            ),
        ],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_PROCESS_LIFECYCLE_INVALID$",
    ):
        session.pump(0)
    assert session.process_created(_CHILD_PID) is False
    assert kernel32.closed_handles == [0xCEE]
    assert kernel32.continues[-1] == (_CHILD_PID, _CHILD_TID, debug._DBG_CONTINUE)


def test_complete_ledger_tracks_descendants_threads_and_implicit_unmaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, kernel32 = _complete_capture(monkeypatch)
    assert capture.created_process_ids == (_ROOT_PID, _CHILD_PID)
    assert capture.exited_process_ids == (_ROOT_PID, _CHILD_PID)
    assert capture.initial_breakpoint_process_ids == (_ROOT_PID, _CHILD_PID)
    assert capture.continued_event_count == len(capture.records) == 11
    assert capture.wait_failure_count == 0
    assert capture.continue_failure_count == 0
    assert capture.handle_close_failure_count == 0
    assert kernel32.closed_handles == [101, 102, 103, 104]
    child_exit = next(
        record
        for record in capture.records
        if record.event == "EXIT_PROCESS" and record.process_id == _CHILD_PID
    )
    assert child_exit.implicit_unmap_bases == (
        (0x3000, "PROCESS_IMAGE"),
        (0x4000, "DLL_IMAGE"),
    )
    with pytest.raises(FrozenInstanceError):
        capture.root_process_id = 999  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        capture.records[0].sequence = 999  # type: ignore[misc]


def test_remote_debuggee_pointers_are_never_dereferenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = 0x7FFFDEADBEEF0000

    def reject(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("remote pointer was dereferenced")

    monkeypatch.setattr(debug.ctypes, "string_at", reject)
    monkeypatch.setattr(debug.ctypes, "wstring_at", reject)
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(
                debug._CREATE_PROCESS_DEBUG_EVENT,
                base=0x1000,
                remote_pointer=forbidden,
            ),
            _event(
                debug._EXCEPTION_DEBUG_EVENT,
                remote_pointer=forbidden,
            ),
            _event(
                debug._OUTPUT_DEBUG_STRING_EVENT,
                remote_pointer=forbidden,
            ),
            _event(
                debug._LOAD_DLL_DEBUG_EVENT,
                base=0x2000,
                remote_pointer=forbidden,
            ),
            _event(debug._EXIT_PROCESS_DEBUG_EVENT),
        ],
    )
    _pump_queued(session, kernel32)
    capture = session.snapshot()
    output = next(record for record in capture.records if record.event == "OUTPUT_DEBUG_STRING")
    assert output.debug_string_code_units == 17
    assert output.debug_string_unicode is True


@pytest.mark.parametrize(
    ("reuse_event", "error_code"),
    [
        (
            _event(debug._CREATE_PROCESS_DEBUG_EVENT, base=0x9000, file_handle=0x901),
            "WINDOWS_DEBUG_PROCESS_LIFECYCLE_INVALID",
        ),
        (
            _event(debug._CREATE_THREAD_DEBUG_EVENT, tid=30),
            "WINDOWS_DEBUG_THREAD_LIFECYCLE_INVALID",
        ),
    ],
)
def test_process_and_thread_identifier_reuse_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    reuse_event: debug._DebugEvent,
    error_code: str,
) -> None:
    if int(reuse_event.dwDebugEventCode) == debug._CREATE_PROCESS_DEBUG_EVENT:
        prefix = [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._EXIT_PROCESS_DEBUG_EVENT),
        ]
    else:
        prefix = [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._CREATE_THREAD_DEBUG_EVENT, tid=30),
            _event(debug._EXIT_THREAD_DEBUG_EVENT, tid=30),
        ]
    session, kernel32 = _fake_session(monkeypatch, [*prefix, reuse_event])
    for _ in prefix:
        assert session.pump(0) is True
    with pytest.raises(debug.DebugEventEngineError, match=f"^{error_code}$"):
        session.pump(0)
    assert len(kernel32.continues) == len(prefix) + 1
    if int(reuse_event.dwDebugEventCode) == debug._CREATE_PROCESS_DEBUG_EVENT:
        assert kernel32.closed_handles[-1] == 0x901


def _target() -> dict[str, Any]:
    program_raw = (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes()
    input_raw = (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes()
    receipt_raw = dsl.run_pack_abi("evaluate", program_raw, input_raw)
    return {
        "program_digest": contract.bytes_digest(program_raw),
        "input_digest": contract.bytes_digest(input_raw),
        "receipt_digest": contract.bytes_digest(receipt_raw),
        "receipt": contract.parse_canonical_json_bytes(receipt_raw, require_canonical=True),
        "outcome": "EXECUTED_NONAUTHORITATIVE",
        "authoritative": False,
        "promotion_eligible": False,
        "crypto_provider_module": "cryptography.hazmat.bindings._rust",
        "crypto_provider_path_digest": contract.bytes_digest(b"private crypto path"),
        "crypto_vector": "RFC8032-TEST-1-EMPTY-MESSAGE",
        "crypto_verified": True,
    }


def _debug_common(schema: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "capture_protocol": discovery._fixed_debug_capture_protocol(),
        "platform": discovery._fixed_platform(),
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "claim_boundary": discovery._fixed_debug_claim_boundary(),
        "authority": discovery._fixed_authority(),
    }


def _tokenized_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    capture, _kernel32 = _complete_capture(monkeypatch)
    process_tokens = {
        _ROOT_PID: "process.000000000001",
        _CHILD_PID: "process.000000000002",
    }
    process_rows, image_rows = discovery._tokenize_debug_capture(capture, process_tokens)
    root_token = process_tokens[_ROOT_PID]
    target_token = process_tokens[_CHILD_PID]
    job_events = [
        {
            "sequence": 0,
            "event": "NEW_PROCESS",
            "process_token": root_token,
            "job_message_id": 6,
        },
        {
            "sequence": 1,
            "event": "NEW_PROCESS",
            "process_token": target_token,
            "job_message_id": 6,
        },
        {
            "sequence": 2,
            "event": "EXIT_PROCESS",
            "process_token": target_token,
            "job_message_id": 7,
        },
        {
            "sequence": 3,
            "event": "EXIT_PROCESS",
            "process_token": root_token,
            "job_message_id": 7,
        },
        {
            "sequence": 4,
            "event": "ACTIVE_PROCESS_ZERO",
            "process_token": None,
            "job_message_id": 4,
        },
    ]
    process_trace = {
        **_debug_common(discovery._fixed_debug_process_trace_schema()),
        "limits": discovery._fixed_debug_limits(),
        "target": _target(),
        "target_process_token": target_token,
        "debugger": {
            "wait_api": "WAIT_FOR_DEBUG_EVENT_EX",
            "creation_flags": ["CREATE_NO_WINDOW", "DEBUG_PROCESS"],
            "debug_only_this_process": False,
            "debug_set_process_kill_on_exit": True,
            "creator_thread_only": True,
            "root_process_token": root_token,
            "root_create_observed_before_first_continue": True,
            "descendant_debugging_requested": True,
            "debug_event_count": len(process_rows),
            "continued_event_count": len(process_rows),
            "created_process_count": 2,
            "exited_process_count": 2,
            "initial_breakpoint_count": 2,
        },
        "job": {
            "completion_port_associated": True,
            "kill_on_job_close": True,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "assigned_process_count": 1,
            "observed_process_count": 2,
            "active_process_zero_observed": True,
            "target_exit_code": 0,
            "assignment_completed_before_first_debug_event_pump": True,
            "debug_created_process_set_matches_job": True,
            "debug_exited_process_set_matches_job": True,
            "events": job_events,
        },
        "event_count": len(process_rows),
        "events": process_rows,
    }
    load_count = sum(row["event"] == "LOAD_IMAGE" for row in image_rows)
    explicit_count = sum(row["event"] == "UNLOAD_IMAGE" for row in image_rows)
    implicit_count = sum(
        row["event"] == "PROCESS_EXIT_IMPLICIT_UNMAP" for row in image_rows
    )
    snapshot = {
        "sequence": 0,
        "process_token": target_token,
        "status": "OBSERVED_NONEMPTY",
        "mappings": [{
            "mapping_token": "mapping.k32checkpoint",
            "observed_path_digest": contract.bytes_digest(b"private mapping path"),
            "path_disclosure": "DIGEST_ONLY_NO_RAW_PATH",
            "mapping_kind": "K32_ENUMERATED_IMAGE",
        }],
    }
    image_trace = {
        **_debug_common(discovery._fixed_debug_image_trace_schema()),
        "method": "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_CHECKPOINT/2",
        "semantics": "DEBUG_IMAGE_LIFETIMES_PLUS_POINT_CHECKPOINT_NOT_COMPLETE_MAPPING_HISTORY",
        "history_complete": False,
        "target_process_token": target_token,
        "debug_event_stream_digest": contract.canonical_digest(process_rows),
        "load_event_count": load_count,
        "explicit_unload_event_count": explicit_count,
        "implicit_unmap_count": implicit_count,
        "lifecycle_event_count": len(image_rows),
        "distinct_mapping_count": load_count,
        "snapshot_count": 1,
        "snapshot_mapping_row_count": 1,
        "target_snapshots": [snapshot],
        "events": image_rows,
    }
    loss_trace = {
        **_debug_common(discovery._fixed_debug_loss_trace_schema()),
        "target_process_token": target_token,
        "debug_event_count": len(process_rows),
        "created_process_count": 2,
        "exited_process_count": 2,
        "initial_breakpoint_count": 2,
        "load_event_count": load_count,
        "explicit_unload_event_count": explicit_count,
        "implicit_unmap_count": implicit_count,
        "mapping_snapshot_count": 1,
        "mapping_snapshot_row_count": 1,
        "process_tree_reconciled": True,
        "event_stream_contiguous": False,
        "start_end_snapshot_reconciled": False,
        "counters": {
            "debug_wait_failures": 0,
            "debug_continue_failures": 0,
            "debug_handle_close_failures": 0,
            "job_messages_lost": None,
            "process_events_lost": None,
            "mapping_load_events_lost": None,
            "mapping_unload_events_lost": None,
            "k32_enumeration_failures": 0,
        },
        "limitations": list(discovery._fixed_debug_limitations()),
    }
    return process_trace, image_trace, loss_trace


def _debug_v3_common(schema: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "capture_protocol": discovery._fixed_debug_v3_capture_protocol(),
        "platform": discovery._fixed_platform(),
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "claim_boundary": discovery._fixed_debug_v3_claim_boundary(),
        "authority": discovery._fixed_authority(),
    }


def _checkpoint_mapping(slot: str, path_digest: str) -> dict[str, Any]:
    return {
        "mapping_slot_token": slot,
        "observed_path_digest": path_digest,
        "path_disclosure": "DIGEST_ONLY_NO_RAW_PATH",
        "mapping_kind": "K32_ENUMERATED_IMAGE",
    }


def _tokenized_v3_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    v2_process, _v2_image, _v2_loss = _tokenized_traces(monkeypatch)
    capture, _kernel32 = _complete_capture(monkeypatch)
    process_tokens = {
        _ROOT_PID: "process.000000000001",
        _CHILD_PID: "process.000000000002",
    }
    process_rows, image_rows = discovery._tokenize_debug_capture_v3(capture, process_tokens)
    target_token = process_tokens[_CHILD_PID]
    process_trace = deepcopy(v2_process)
    process_trace.update(_debug_v3_common(discovery._fixed_debug_v3_process_trace_schema()))
    process_trace["events"] = process_rows
    process_trace["event_count"] = len(process_rows)
    process_trace["debugger"]["debug_event_count"] = len(process_rows)
    process_trace["debugger"]["continued_event_count"] = len(process_rows)

    child_create = next(
        row for row in process_rows
        if row["event"] == "CREATE_PROCESS" and row["process_token"] == target_token
    )
    child_dll_loads = [
        row for row in process_rows
        if row["event"] == "LOAD_DLL" and row["process_token"] == target_token
    ]
    assert len(child_dll_loads) == 2
    assert child_dll_loads[0]["mapping_slot_token"] == child_dll_loads[1][
        "mapping_slot_token"
    ]
    assert child_dll_loads[0]["mapping_token"] != child_dll_loads[1]["mapping_token"]
    process_mapping = _checkpoint_mapping(
        child_create["mapping_slot_token"], contract.bytes_digest(b"target process image")
    )
    crypto_mapping = _checkpoint_mapping(
        child_dll_loads[-1]["mapping_slot_token"],
        process_trace["target"]["crypto_provider_path_digest"],
    )
    start_mappings = sorted([process_mapping], key=lambda row: row["mapping_slot_token"])
    end_mappings = sorted(
        [process_mapping, crypto_mapping], key=lambda row: row["mapping_slot_token"]
    )
    checkpoints = [
        {
            "sequence": 0,
            "checkpoint": "START",
            "source_debug_sequence": 3,
            "process_token": target_token,
            "target_state": "SUSPENDED_AT_INITIAL_BREAKPOINT_BEFORE_CONTINUE",
            "reads": [
                {"sequence": index, "status": "OBSERVED_NONEMPTY", "mappings": deepcopy(
                    start_mappings
                )}
                for index in range(2)
            ],
        },
        {
            "sequence": 1,
            "checkpoint": "END",
            "source_debug_sequence": 8,
            "process_token": target_token,
            "target_state": "AFTER_PAYLOAD_BEFORE_STOP_RELEASE",
            "reads": [
                {"sequence": index, "status": "OBSERVED_NONEMPTY", "mappings": deepcopy(
                    end_mappings
                )}
                for index in range(2)
            ],
        },
    ]
    load_count = sum(row["event"] == "LOAD_IMAGE" for row in image_rows)
    explicit_count = sum(row["event"] == "UNLOAD_IMAGE" for row in image_rows)
    implicit_count = sum(
        row["event"] == "PROCESS_EXIT_IMPLICIT_UNMAP" for row in image_rows
    )
    checkpoint_rows = sum(
        len(read["mappings"])
        for checkpoint in checkpoints
        for read in checkpoint["reads"]
    )
    image_trace = {
        **_debug_v3_common(discovery._fixed_debug_v3_image_trace_schema()),
        "method": (
            "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_START_END_STABLE_DOUBLE_READ/3"
        ),
        "semantics": (
            "DEBUG_IMAGE_LIFETIMES_PLUS_TARGET_ONLY_STABLE_K32_ENDPOINT_"
            "RECONCILIATION_NOT_COMPLETE_MAPPING_HISTORY"
        ),
        "history_complete": False,
        "target_process_token": target_token,
        "debug_event_stream_digest": contract.canonical_digest(process_rows),
        "load_event_count": load_count,
        "explicit_unload_event_count": explicit_count,
        "implicit_unmap_count": implicit_count,
        "lifecycle_event_count": len(image_rows),
        "distinct_mapping_count": load_count,
        "target_checkpoint_count": 2,
        "target_checkpoint_read_count": 4,
        "target_checkpoint_mapping_row_count": checkpoint_rows,
        "target_checkpoints": checkpoints,
        "events": image_rows,
    }
    loss_trace = {
        **_debug_v3_common(discovery._fixed_debug_v3_loss_trace_schema()),
        "target_process_token": target_token,
        "debug_event_count": len(process_rows),
        "created_process_count": 2,
        "exited_process_count": 2,
        "initial_breakpoint_count": 2,
        "load_event_count": load_count,
        "explicit_unload_event_count": explicit_count,
        "implicit_unmap_count": implicit_count,
        "mapping_snapshot_count": 2,
        "mapping_snapshot_row_count": len(start_mappings) + len(end_mappings),
        "target_checkpoint_count": 2,
        "target_checkpoint_read_count": 4,
        "target_checkpoint_mapping_row_count": checkpoint_rows,
        "process_tree_reconciled": True,
        "event_stream_contiguous": False,
        "start_end_snapshot_reconciled": False,
        "target_start_end_snapshot_reconciled": True,
        "collector_sequence_kind": "LOCAL_APPEND_ORDINAL",
        "collector_ledger_contiguous": True,
        "collector_sequence_gap_count": 0,
        "os_event_sequence_available": False,
        "os_loss_counter_available": False,
        "counters": {
            "debug_wait_failures": 0,
            "debug_continue_failures": 0,
            "debug_handle_close_failures": 0,
            "job_messages_lost": None,
            "process_events_lost": None,
            "mapping_load_events_lost": None,
            "mapping_unload_events_lost": None,
            "mapping_snapshots_lost": None,
            "collector_loss_count": None,
            "sequence_gap_count": None,
            "unmatched_runtime_event_count": None,
            "k32_enumeration_failures": 0,
        },
        "limitations": list(discovery._fixed_debug_v3_limitations()),
    }
    return process_trace, image_trace, loss_trace


def test_v3_target_checkpoint_reconciliation_is_narrow_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, loss_trace = _tokenized_v3_traces(monkeypatch)
    schema = json.loads(
        (
            ROOT
            / "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    schema_validator = Draft202012Validator(schema)
    for document in (process_trace, image_trace, loss_trace):
        schema_validator.validate(document)
        assert discovery.validate_windows_debug_runtime_discovery_v3_trace(document) == document
        with pytest.raises(discovery.RuntimeDiscoveryError):
            discovery.validate_windows_debug_runtime_discovery_trace(document)
    discovery._validate_debug_v3_checkpoint_projection(process_trace, image_trace)
    assert image_trace["history_complete"] is False
    assert loss_trace["target_start_end_snapshot_reconciled"] is True
    assert loss_trace["event_stream_contiguous"] is False
    assert loss_trace["start_end_snapshot_reconciled"] is False
    assert loss_trace["collector_sequence_gap_count"] == 0
    assert loss_trace["counters"]["sequence_gap_count"] is None


@pytest.mark.parametrize(
    "field",
    ["event", "continue_status", "mapping_kind", "exception_disposition"],
)
def test_v3_rejects_unhashable_process_event_scalar_with_stable_error(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    process_trace, _image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    process_trace["events"][0][field] = []
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_PROCESS_EVENTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(process_trace)


def test_v3_rejects_unhashable_job_event_with_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, _image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    process_trace["job"]["events"][0]["event"] = []
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(process_trace)


def test_v3_rejects_unhashable_image_event_with_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    unload = next(row for row in image_trace["events"] if row["event"] != "LOAD_IMAGE")
    unload["event"] = []
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_EVENTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(image_trace)


def test_v3_rejects_coordinated_unhashable_image_kind_with_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    slot = image_trace["events"][0]["mapping_slot_token"]
    for row in image_trace["events"]:
        if row["mapping_slot_token"] == slot:
            row["mapping_kind"] = []
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_EVENTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(image_trace)


def test_v3_rejects_unstable_k32_reads_and_debug_slot_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    unstable = deepcopy(image_trace)
    unstable["target_checkpoints"][1]["reads"][1]["mappings"].pop()
    unstable["target_checkpoint_mapping_row_count"] -= 1
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_CHECKPOINTS_UNSTABLE$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(unstable)

    mismatch = deepcopy(image_trace)
    replacement = "mapping-slot." + "f" * 64
    for read in mismatch["target_checkpoints"][1]["reads"]:
        read["mappings"][-1]["mapping_slot_token"] = replacement
        read["mappings"].sort(key=lambda row: row["mapping_slot_token"])
    assert discovery.validate_windows_debug_runtime_discovery_v3_trace(mismatch) == mismatch
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_CHECKPOINT_REPLAY_INVALID$",
    ):
        discovery._validate_debug_v3_checkpoint_projection(process_trace, mismatch)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_stream_contiguous", True),
        ("start_end_snapshot_reconciled", True),
        ("target_start_end_snapshot_reconciled", False),
        ("collector_sequence_gap_count", 1),
        ("os_event_sequence_available", True),
        ("os_loss_counter_available", True),
    ],
)
def test_v3_rejects_global_or_os_loss_claims(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    _process_trace, _image_trace, loss_trace = _tokenized_v3_traces(monkeypatch)
    loss_trace[field] = value
    with pytest.raises(discovery.RuntimeDiscoveryError, match="^WINDOWS_DEBUG_V3_LOSS_TRACE_INVALID$"):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(loss_trace)


def test_v3_rejects_boolean_ordinals_and_inconsistent_checkpoint_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, image_trace, loss_trace = _tokenized_v3_traces(monkeypatch)

    boolean_checkpoint = deepcopy(image_trace)
    boolean_checkpoint["target_checkpoints"][0]["sequence"] = False
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_CHECKPOINTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(boolean_checkpoint)

    boolean_read = deepcopy(image_trace)
    boolean_read["target_checkpoints"][0]["reads"][0]["sequence"] = False
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_CHECKPOINTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(boolean_read)

    for field, value in (
        ("collector_sequence_gap_count", False),
        ("mapping_snapshot_count", 1),
        (
            "target_checkpoint_mapping_row_count",
            loss_trace["target_checkpoint_mapping_row_count"] + 2,
        ),
    ):
        forged = deepcopy(loss_trace)
        forged[field] = value
        with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_DEBUG_V3_LOSS_TRACE_INVALID$",
        ):
            discovery.validate_windows_debug_runtime_discovery_v3_trace(forged)


def test_v3_rejects_missing_reversed_wrong_or_late_checkpoint_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)

    missing = deepcopy(image_trace)
    missing["target_checkpoints"].pop()
    missing["target_checkpoint_count"] = 1
    missing["target_checkpoint_read_count"] = 2
    missing["target_checkpoint_mapping_row_count"] = 2
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_TRACE_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(missing)

    reversed_checkpoints = deepcopy(image_trace)
    reversed_checkpoints["target_checkpoints"].reverse()
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_CHECKPOINTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(reversed_checkpoints)

    wrong_target = deepcopy(image_trace)
    wrong_target["target_checkpoints"][0]["process_token"] = "process.wrong"
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_IMAGE_CHECKPOINTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v3_trace(wrong_target)

    wrong_start_anchor = deepcopy(image_trace)
    wrong_start_anchor["target_checkpoints"][0]["source_debug_sequence"] = 2
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V3_START_CHECKPOINT_ANCHOR_INVALID$",
    ):
        discovery._validate_debug_v3_checkpoint_projection(
            process_trace, wrong_start_anchor
        )



def test_v3_serializes_balanced_post_endpoint_teardown_outside_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, _loss_trace = _tokenized_v3_traces(monkeypatch)
    target_token = process_trace["target_process_token"]
    teardown_mapping = "mapping.post-end-teardown"
    teardown_slot = "mapping-slot.post-end-teardown"

    for row in process_trace["events"]:
        if row["sequence"] >= 9:
            row["sequence"] += 2
    load_process = deepcopy(process_trace["events"][8])
    load_process.update({
        "sequence": 9,
        "mapping_token": teardown_mapping,
        "mapping_slot_token": teardown_slot,
    })
    unload_process = deepcopy(process_trace["events"][7])
    unload_process.update({
        "sequence": 10,
        "mapping_token": teardown_mapping,
        "mapping_slot_token": teardown_slot,
    })
    process_trace["events"][9:9] = [load_process, unload_process]
    process_trace["event_count"] += 2
    process_trace["debugger"]["debug_event_count"] += 2
    process_trace["debugger"]["continued_event_count"] += 2

    for row in image_trace["events"]:
        if row["source_debug_sequence"] >= 9:
            row["source_debug_sequence"] += 2
    load_image = deepcopy(next(
        row for row in image_trace["events"]
        if row["source_debug_sequence"] == 8 and row["process_token"] == target_token
    ))
    load_image.update({
        "source_debug_sequence": 9,
        "mapping_token": teardown_mapping,
        "mapping_slot_token": teardown_slot,
    })
    unload_image = deepcopy(load_image)
    unload_image.update({
        "source_debug_sequence": 10,
        "event": "UNLOAD_IMAGE",
        "file_handle_present": None,
    })
    image_trace["events"].extend([load_image, unload_image])
    image_trace["events"].sort(key=lambda row: row["source_debug_sequence"])
    for sequence, row in enumerate(image_trace["events"]):
        row["sequence"] = sequence
    image_trace["debug_event_stream_digest"] = contract.canonical_digest(
        process_trace["events"]
    )
    image_trace["load_event_count"] += 1
    image_trace["explicit_unload_event_count"] += 1
    image_trace["lifecycle_event_count"] += 2
    image_trace["distinct_mapping_count"] += 1

    assert discovery.validate_windows_debug_runtime_discovery_v3_trace(
        process_trace
    ) == process_trace
    assert discovery.validate_windows_debug_runtime_discovery_v3_trace(
        image_trace
    ) == image_trace
    assert discovery._validate_debug_v3_checkpoint_projection(
        process_trace, image_trace
    ) is None


def test_v3_stable_k32_checkpoint_is_exactly_two_normalized_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    rows = [(0x4000, r"C:\Runtime\B.DLL"), (0x1000, r"C:\Runtime\A.EXE")]

    def enumerate_rows(pid: int) -> list[tuple[int, str]]:
        calls.append(pid)
        return list(rows)

    monkeypatch.setattr(discovery, "_windows_process_module_paths", enumerate_rows)
    raw = discovery._stable_debug_mapping_checkpoint(200, "END", 8)
    assert calls == [200, 200]
    assert raw == {
        "checkpoint": "END",
        "target_state": "AFTER_PAYLOAD_BEFORE_STOP_RELEASE",
        "process_id": 200,
        "source_debug_sequence": 8,
        "normalized_reads": (
            (
                (0x1000, contract.bytes_digest(b"c:/runtime/a.exe")),
                (0x4000, contract.bytes_digest(b"c:/runtime/b.dll")),
            ),
            (
                (0x1000, contract.bytes_digest(b"c:/runtime/a.exe")),
                (0x4000, contract.bytes_digest(b"c:/runtime/b.dll")),
            ),
        ),
    }
    sealed = discovery._sealed_debug_mapping_checkpoint(
        raw, "process.000000000002"
    )
    assert set(sealed) == {
        "checkpoint",
        "target_state",
        "source_debug_sequence",
        "process_token",
        "reads",
    }
    assert len(sealed["reads"]) == 2
    assert sealed["reads"][0] == sealed["reads"][1] | {"sequence": 0}
    assert [
        row["mapping_slot_token"] for row in sealed["reads"][0]["mappings"]
    ] == sorted(
        row["mapping_slot_token"] for row in sealed["reads"][0]["mappings"]
    )
    assert "process_id" not in sealed
    assert "normalized_reads" not in sealed


def test_v3_stable_k32_checkpoint_rejects_instability_and_duplicate_bases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            [(0x1000, r"C:\Runtime\A.EXE")],
            [(0x1000, r"C:\Runtime\B.EXE")],
        ]
    )
    monkeypatch.setattr(
        discovery,
        "_windows_process_module_paths",
        lambda _pid: next(responses),
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_K32_CHECKPOINT_UNSTABLE$",
    ):
        discovery._stable_debug_mapping_checkpoint(200, "START", 3)

    monkeypatch.setattr(
        discovery,
        "_windows_process_module_paths",
        lambda _pid: [
            (0x1000, r"C:\Runtime\A.EXE"),
            (0x1000, r"C:\Runtime\A.EXE"),
        ],
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_K32_CHECKPOINT_INVALID$",
    ):
        discovery._stable_debug_mapping_checkpoint(200, "START", 3)


def test_tokenization_generates_new_mapping_token_after_base_reuse_and_v2_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, loss_trace = _tokenized_traces(monkeypatch)
    dll_loads = [
        row
        for row in image_trace["events"]
        if row["event"] == "LOAD_IMAGE" and row["mapping_kind"] == "DLL_IMAGE"
    ]
    assert len(dll_loads) == 2
    assert dll_loads[0]["mapping_token"] != dll_loads[1]["mapping_token"]
    assert all(
        "process_id" not in row and "thread_id" not in row and "mapping_base" not in row
        for row in process_trace["events"]
    )
    assert discovery.validate_windows_debug_runtime_discovery_trace(
        process_trace
    ) == process_trace
    assert discovery.validate_windows_debug_runtime_discovery_trace(image_trace) == image_trace
    assert discovery.validate_windows_debug_runtime_discovery_trace(loss_trace) == loss_trace


@pytest.mark.parametrize(
    ("forgery", "expected_error"),
    [
        ("selected_source", "RUNTIME_DISCOVERY_ENVIRONMENT_SOURCE_JOIN_INVALID"),
        ("cwd", "WINDOWS_DEBUG_OUTER_LAUNCH_RECONCILIATION_FAILED"),
    ],
)
def test_debug_sealer_rejects_internally_consistent_forged_launch_binding(
    monkeypatch: pytest.MonkeyPatch,
    forgery: str,
    expected_error: str,
) -> None:
    process_trace, image_trace, loss_trace = _tokenized_traces(monkeypatch)
    image_trace["target_snapshots"][0]["mappings"][0]["observed_path_digest"] = (
        process_trace["target"]["crypto_provider_path_digest"]
    )
    source_relatives = {
        relative
        for _input_id, _path_token, relative in discovery._LAUNCH_INPUT_SPEC
        if relative is not None
    }
    source_raw_by_relative = {
        relative: (ROOT / relative).read_bytes()
        for relative in source_relatives
    }
    private_root = ROOT / "private-runtime-debug-test"
    launch = discovery._expected_launch_binding(
        Path(sys.executable),
        private_root / "collector-target.py",
        discovery._TARGET_SOURCE.encode("utf-8"),
        ROOT,
        {relative: ROOT / relative for relative in source_relatives},
        ROOT,
        private_root / "pycache",
        {
            "PATH": "",
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPYCACHEPREFIX": str(private_root / "pycache"),
            "PYTHONUTF8": "1",
            "SYSTEMROOT": str(private_root / "windows"),
            "TEMP": str(private_root / "temp"),
            "TMP": str(private_root / "temp"),
            "WINDIR": str(private_root / "windows"),
        },
        discovery._selected_source_manifest_raw(source_raw_by_relative).decode("ascii"),
        source_raw_by_relative,
    )
    outer_expected_launch = deepcopy(launch)
    environment_manifest = {
        "schema": discovery._fixed_debug_environment_manifest_schema(),
        "capture_protocol": discovery._fixed_debug_capture_protocol(),
        "platform": discovery._fixed_platform(),
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "target_process_token": process_trace["target_process_token"],
        "launch": {
            "parent_expected": deepcopy(launch),
            "target_observed": deepcopy(launch),
        },
        "reconciliation": {
            "parent_expected_launch_digest": contract.canonical_digest(launch),
            "target_observed_launch_digest": contract.canonical_digest(launch),
            "exact_match": True,
        },
        "claim_boundary": discovery._fixed_environment_claim_boundary(),
        "authority": discovery._fixed_authority(),
    }

    if forgery == "selected_source":
        forged_raw = b"internally consistent but false selected source bytes"
        forged_digest = contract.bytes_digest(forged_raw)
        forged_input_id = "selected-source-transition-contract"
        for side in ("parent_expected", "target_observed"):
            side_launch = environment_manifest["launch"][side]
            by_id = {row["input_id"]: row for row in side_launch["inputs"]}
            by_id[forged_input_id]["raw_bytes"] = len(forged_raw)
            by_id[forged_input_id]["digest"] = forged_digest
            selected_source_manifest_raw = contract.canonical_json_bytes({
                relative: by_id[input_id]["digest"]
                for input_id, _path_token, relative in discovery._LAUNCH_INPUT_SPEC
                if relative in discovery._TARGET_SOURCE_RELATIVES
            })
            side_launch["argv"][6]["value_digest"] = contract.bytes_digest(
                selected_source_manifest_raw
            )
            side_launch["source_manifest_digest"] = contract.bytes_digest(
                selected_source_manifest_raw
            )
            environment_manifest["reconciliation"][f"{side}_launch_digest"] = (
                contract.canonical_digest(side_launch)
            )
    else:
        assert forgery == "cwd"
        forged_path_digest = contract.bytes_digest(b"internally consistent but false cwd")
        for side in ("parent_expected", "target_observed"):
            side_launch = environment_manifest["launch"][side]
            side_launch["cwd"]["path_digest"] = forged_path_digest
            side_launch["argv"][1]["value_digest"] = forged_path_digest
            environment_manifest["reconciliation"][f"{side}_launch_digest"] = (
                contract.canonical_digest(side_launch)
            )

    assert discovery.validate_windows_debug_execution_environment_manifest(
        environment_manifest
    ) == environment_manifest
    artifact_raw_by_id = {
        artifact_id: (ROOT / relative).read_bytes()
        for artifact_id, _role, _field, relative in discovery._STATIC_ARTIFACTS
    }
    dynamic_by_schema = {
        process_trace["schema"]: process_trace,
        image_trace["schema"]: image_trace,
        loss_trace["schema"]: loss_trace,
    }
    for artifact_id, _role, schema in discovery._DEBUG_DYNAMIC_ARTIFACTS:
        artifact_raw_by_id[artifact_id] = contract.canonical_json_bytes(
            dynamic_by_schema[schema]
        )
    environment_artifact_id = discovery._DEBUG_ENVIRONMENT_ARTIFACT[0]
    artifact_raw_by_id[environment_artifact_id] = contract.canonical_json_bytes(
        environment_manifest
    )
    static_raw_by_relative, inventory, _input_digest = (
        discovery._validate_sealed_static_profile(artifact_raw_by_id)
    )
    sealed_profile = discovery._validate_sealed_debug_dynamic_profile(
        artifact_raw_by_id,
        process_trace["target"]["crypto_provider_path_digest"],
    )
    assert sealed_profile == (
        process_trace,
        image_trace,
        loss_trace,
        environment_manifest,
    )
    evidence = discovery._expected_debug_incomplete_evidence(
        {
            "producer_id": "producer.alpha.001",
            "runtime_collector_id": "collector.bravo.001",
            "structural_tcb_producer_id": "structural.charlie.001",
            "pack_producer_id": "pack.delta.001",
            "budget_proposer_id": "budget.echo.001",
            "release_builder_id": "builder.foxtrot.001",
            "selected_commit": _COMMIT,
            "selected_tree": _TREE,
        },
        artifact_raw_by_id,
        static_raw_by_relative,
        inventory,
        process_trace,
        image_trace,
        loss_trace,
        environment_manifest,
    )
    evidence_raw = contract.canonical_json_bytes(evidence)
    bound = discovery.bind_transition_runtime_closure_evidence_bytes(
        evidence_raw, artifact_raw_by_id
    )

    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match=f"^{expected_error}$",
    ):
        discovery._seal_captured_debug_discovery_result(
            bound,
            evidence_raw,
            artifact_raw_by_id,
            process_trace["target"]["crypto_provider_path_digest"],
            source_raw_by_relative,
            outer_expected_launch,
        )


@pytest.mark.parametrize("reuse_kind", ["process", "thread", "mapping"])
def test_v2_process_trace_rejects_token_reuse(
    monkeypatch: pytest.MonkeyPatch,
    reuse_kind: str,
) -> None:
    process_trace, _image_trace, _loss_trace = _tokenized_traces(monkeypatch)
    mutated = deepcopy(process_trace)
    root_create = mutated["events"][0]
    child_create = next(
        row
        for row in mutated["events"]
        if row["event"] == "CREATE_PROCESS"
        and row["process_token"] != root_create["process_token"]
    )
    if reuse_kind == "process":
        child_create["process_token"] = root_create["process_token"]
    elif reuse_kind == "thread":
        child_create["thread_token"] = root_create["thread_token"]
    else:
        dll_loads = [
            row
            for row in mutated["events"]
            if row["event"] == "LOAD_DLL"
        ]
        dll_loads[1]["mapping_token"] = dll_loads[0]["mapping_token"]
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_PROCESS_EVENTS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_trace(mutated)


def test_v2_validators_refuse_continuity_and_history_claim_inflation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, image_trace, loss_trace = _tokenized_traces(monkeypatch)
    image_trace["history_complete"] = True
    loss_trace["event_stream_contiguous"] = True
    with pytest.raises(discovery.RuntimeDiscoveryError, match="^WINDOWS_DEBUG_IMAGE_TRACE_INVALID$"):
        discovery.validate_windows_debug_runtime_discovery_trace(image_trace)
    with pytest.raises(discovery.RuntimeDiscoveryError, match="^WINDOWS_DEBUG_LOSS_TRACE_INVALID$"):
        discovery.validate_windows_debug_runtime_discovery_trace(loss_trace)


def _renumber_job_events(rows: list[dict[str, Any]]) -> None:
    for sequence, row in enumerate(rows):
        row["sequence"] = sequence


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("fabricated", "WINDOWS_DEBUG_PROCESS_TRACE_RECONCILIATION_INVALID"),
        ("missing", "WINDOWS_DEBUG_PROCESS_TRACE_RECONCILIATION_INVALID"),
        ("reordered", "WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID"),
    ],
)
def test_v2_process_validator_rejects_fabricated_missing_and_reordered_job_rows(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error_code: str,
) -> None:
    process_trace, _image_trace, _loss_trace = _tokenized_traces(monkeypatch)
    rows = process_trace["job"]["events"]
    if mutation == "fabricated":
        rows[2:2] = [
            {
                "sequence": -1,
                "event": "NEW_PROCESS",
                "process_token": "process.fabricated",
                "job_message_id": 6,
            },
            {
                "sequence": -1,
                "event": "EXIT_PROCESS",
                "process_token": "process.fabricated",
                "job_message_id": 7,
            },
        ]
    elif mutation == "missing":
        rows[:] = [
            row
            for row in rows
            if row["process_token"] != process_trace["target_process_token"]
        ]
    else:
        rows[1], rows[2] = rows[2], rows[1]
    _renumber_job_events(rows)
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        discovery.validate_windows_debug_runtime_discovery_trace(process_trace)


def test_v2_projection_rejects_balanced_fabricated_image_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, _loss_trace = _tokenized_traces(monkeypatch)
    fabricated_token = "mapping.fabricated"
    fabricated = [
        {
            "sequence": -1,
            "source_debug_sequence": 1,
            "event": "LOAD_IMAGE",
            "process_token": process_trace["events"][1]["process_token"],
            "mapping_token": fabricated_token,
            "mapping_kind": "DLL_IMAGE",
            "file_handle_present": False,
        },
        {
            "sequence": -1,
            "source_debug_sequence": 1,
            "event": "UNLOAD_IMAGE",
            "process_token": process_trace["events"][1]["process_token"],
            "mapping_token": fabricated_token,
            "mapping_kind": "DLL_IMAGE",
            "file_handle_present": None,
        },
    ]
    rows = image_trace["events"]
    rows[1:1] = fabricated
    for sequence, row in enumerate(rows):
        row["sequence"] = sequence
    image_trace["load_event_count"] += 1
    image_trace["explicit_unload_event_count"] += 1
    image_trace["lifecycle_event_count"] += 2
    image_trace["distinct_mapping_count"] += 1

    # The fabricated pair is internally balanced and therefore passes the standalone image
    # lifecycle validator.  The exact process-to-image projection join must still reject it.
    assert discovery.validate_windows_debug_runtime_discovery_trace(image_trace) == image_trace
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID$",
    ):
        discovery._validate_debug_image_projection(process_trace, image_trace)


@pytest.mark.skipif(
    os.name != "nt"
    or ctypes.sizeof(ctypes.c_void_p) != 8
    or platform.machine().upper() not in {"AMD64", "X86_64"},
    reason="supported native Windows AMD64 debug lane only",
)
def test_live_debug_process_smoke_is_bounded() -> None:
    executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    if not executable.is_file():
        pytest.skip("base CPython executable is unavailable")
    process = subprocess.Popen(
        [str(executable), "-I", "-S", "-B", "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(
            debug.DEBUG_PROCESS_CREATION_FLAG
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ),
    )
    session = debug.WindowsDebugEventSession(process.pid)
    deadline = time.monotonic() + 15
    try:
        while not session.all_processes_exited:
            if time.monotonic() >= deadline:
                pytest.fail("live DEBUG_PROCESS smoke exceeded its 15-second guard")
            session.pump(100)
        capture = session.snapshot()
        assert capture.root_process_id == process.pid
        assert capture.records[0].event == "CREATE_PROCESS"
        assert capture.created_process_ids == capture.exited_process_ids
        assert capture.created_process_ids == capture.initial_breakpoint_process_ids
        assert any(record.event == "LOAD_DLL" for record in capture.records)
        process.wait(timeout=5)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            cleanup_deadline = time.monotonic() + 5
            while not session.all_processes_exited and time.monotonic() < cleanup_deadline:
                try:
                    session.pump(50)
                except debug.DebugEventEngineError:
                    break
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
