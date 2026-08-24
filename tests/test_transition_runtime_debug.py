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


def test_invalid_event_record_never_reaches_event_file_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, base=0, file_handle=0xABC)],
    )
    observed: list[tuple[debug.DebugEventRecord, int]] = []

    def observe_file(record: debug.DebugEventRecord, handle: int) -> None:
        observed.append((record, handle))

    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_IMAGE_BASE_INVALID$"):
        session.pump(0, before_event_file_close=observe_file)

    assert observed == []
    assert session.record_count == 0
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


def test_event_file_observer_borrows_open_handle_before_close_and_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    observed: list[tuple[debug.DebugEventRecord, int]] = []
    before_continue_records: list[debug.DebugEventRecord] = []

    def observe_file(record: debug.DebugEventRecord, handle: int) -> None:
        assert session.record_count == 0
        assert kernel32.closed_handles == []
        assert kernel32.continues == []
        with pytest.raises(FrozenInstanceError):
            record.sequence = 7  # type: ignore[misc]
        observed.append((record, handle))

    def observe_before_continue(record: debug.DebugEventRecord) -> None:
        assert kernel32.closed_handles == [0xABC]
        assert kernel32.continues == []
        before_continue_records.append(record)

    assert session.pump(
        0,
        before_continue=observe_before_continue,
        before_event_file_close=observe_file,
    ) is True
    assert len(observed) == 1
    assert observed[0][0].event == "CREATE_PROCESS"
    assert observed[0][1] == 0xABC
    assert before_continue_records == [observed[0][0]]
    assert session.record_count == 1
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_event_file_observer_receives_create_process_and_load_dll_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [
            _event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xAAA),
            _event(debug._EXCEPTION_DEBUG_EVENT),
            _event(debug._LOAD_DLL_DEBUG_EVENT, file_handle=0xBBB, base=0x2000),
        ],
    )
    observed: list[tuple[str, int]] = []

    def observe_file(record: debug.DebugEventRecord, handle: int) -> None:
        observed.append((record.event, handle))

    while kernel32.events:
        assert session.pump(0, before_event_file_close=observe_file) is True

    assert observed == [("CREATE_PROCESS", 0xAAA), ("LOAD_DLL", 0xBBB)]
    assert kernel32.closed_handles == [0xAAA, 0xBBB]
    assert len(kernel32.continues) == 3


def test_event_file_observer_is_not_called_without_a_nonzero_event_file_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT)],
    )
    observed: list[tuple[debug.DebugEventRecord, int]] = []

    def observe_file(record: debug.DebugEventRecord, handle: int) -> None:
        observed.append((record, handle))

    assert session.pump(0, before_event_file_close=observe_file) is True
    assert observed == []
    assert kernel32.closed_handles == []
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_event_file_observer_failure_closes_continues_once_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    before_continue_records: list[debug.DebugEventRecord] = []

    def fail(_record: debug.DebugEventRecord, _handle: int) -> None:
        raise KeyboardInterrupt

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_FILE_OBSERVER_FAILED$",
    ):
        session.pump(
            0,
            before_continue=before_continue_records.append,
            before_event_file_close=fail,
        )
    assert len(before_continue_records) == 1
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.record_count == 1
    with pytest.raises(debug.DebugEventEngineError, match="^WINDOWS_DEBUG_CAPTURE_INCOMPLETE$"):
        session.snapshot()


def test_event_file_observer_is_validated_before_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_FILE_OBSERVER_INVALID$",
    ):
        session.pump(0, before_event_file_close=object())  # type: ignore[arg-type]
    assert len(kernel32.events) == 1
    assert kernel32.closed_handles == []
    assert kernel32.continues == []


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


def test_event_handle_close_failure_precedes_event_file_observer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
        close_result=False,
    )

    def fail(_record: debug.DebugEventRecord, _handle: int) -> None:
        raise RuntimeError("must not escape")

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_HANDLE_CLOSE_FAILED$",
    ):
        session.pump(0, before_event_file_close=fail)

    assert session.record_count == 1
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


def test_continue_failure_precedes_event_file_observer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
        continue_result=False,
    )

    def fail(_record: debug.DebugEventRecord, _handle: int) -> None:
        raise RuntimeError("must not escape")

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_CONTINUE_FAILED$",
    ):
        session.pump(0, before_event_file_close=fail)

    assert session.record_count == 0
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]


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


def _raw_v4_file_observations(
    capture: debug.DebugEventCapture,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for record in capture.records:
        if record.event not in {"CREATE_PROCESS", "LOAD_DLL"}:
            continue
        digest = contract.bytes_digest(
            f"debug-event-file:{record.sequence}".encode("ascii")
        )
        observations.append({
            "source_debug_sequence": record.sequence,
            "process_id": record.process_id,
            "mapping_base": record.mapping_base,
            "mapping_kind": record.mapping_kind,
            "volume_serial_number_hex": "0000000000000001",
            "file_id_128_hex": f"{record.sequence + 1:032x}",
            "file_size_bytes": record.sequence + 1,
            "read_digests": (digest, digest),
        })
    return observations


def _refresh_v4_file_identity_totals(trace: dict[str, Any]) -> None:
    rows = trace["rows"]
    total_bytes = sum(row["file_size_bytes"] for row in rows)
    trace.update({
        "expected_debug_image_handle_count": len(rows),
        "observed_non_null_handle_count": len(rows),
        "stable_file_identity_count": len(rows),
        "stable_disk_bytes_count": len(rows),
        "unbound_debug_image_handle_count": 0,
        "distinct_file_identity_count": len({
            (
                row["file_identity"]["volume_serial_number_hex"],
                row["file_identity"]["file_id_128_hex"],
            )
            for row in rows
        }),
        "total_stable_disk_bytes": total_bytes,
        "total_same_handle_read_bytes": (
            total_bytes * discovery._DEBUG_FILE_STABLE_READ_PASSES
        ),
    })


def _tokenized_v4_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    process_trace, image_trace, loss_trace = _tokenized_v3_traces(monkeypatch)
    capture, _kernel32 = _complete_capture(monkeypatch)
    process_tokens = {
        _ROOT_PID: "process.000000000001",
        _CHILD_PID: "process.000000000002",
    }
    file_rows = discovery._seal_debug_file_identity_rows(
        capture,
        process_tokens,
        _raw_v4_file_observations(capture),
    )
    schema_updates = (
        (process_trace, discovery._fixed_debug_v4_process_trace_schema()),
        (image_trace, discovery._fixed_debug_v4_image_trace_schema()),
        (loss_trace, discovery._fixed_debug_v4_loss_trace_schema()),
    )
    for document, schema in schema_updates:
        document.update({
            "schema": schema,
            "capture_protocol": discovery._fixed_debug_v4_capture_protocol(),
            "claim_boundary": discovery._fixed_debug_v4_claim_boundary(),
        })
    image_trace["method"] = (
        "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_START_END_"
        "STABLE_DOUBLE_READ/4"
    )
    loss_trace["limitations"] = list(discovery._fixed_debug_v4_limitations())
    file_identity_trace = {
        "schema": discovery._fixed_debug_v4_file_identity_trace_schema(),
        "capture_protocol": discovery._fixed_debug_v4_capture_protocol(),
        "platform": discovery._fixed_platform(),
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "claim_boundary": discovery._fixed_debug_v4_claim_boundary(),
        "authority": discovery._fixed_authority(),
        "method": (
            "WINDOWS_DEBUG_EVENT_BORROWED_HFILE_FILE_ID_INFO_STABLE_DOUBLE_READ"
        ),
        "semantics": (
            "DEBUG_EVENT_IMAGE_HANDLES_TO_PERSISTENT_FILE_ID_AND_STABLE_"
            "SAME_HANDLE_ON_DISK_BYTES_ONLY"
        ),
        "target_process_token": process_trace["target_process_token"],
        "collection_guards": {
            "max_file_bytes": discovery._MAX_DEBUG_FILE_BYTES,
            "max_total_file_bytes": discovery._MAX_DEBUG_TOTAL_FILE_BYTES,
            "read_chunk_bytes": discovery._DEBUG_FILE_READ_CHUNK_BYTES,
            "stable_read_passes": discovery._DEBUG_FILE_STABLE_READ_PASSES,
        },
        "expected_debug_image_handle_count": 0,
        "observed_non_null_handle_count": 0,
        "stable_file_identity_count": 0,
        "stable_disk_bytes_count": 0,
        "unbound_debug_image_handle_count": 0,
        "distinct_file_identity_count": 0,
        "total_stable_disk_bytes": 0,
        "total_same_handle_read_bytes": 0,
        "persistent_file_identity_and_loaded_bytes_bound": False,
        "mapped_or_loaded_memory_bytes_bound": False,
        "rows": file_rows,
    }
    _refresh_v4_file_identity_totals(file_identity_trace)
    return process_trace, image_trace, file_identity_trace, loss_trace


def test_v4_file_identity_trace_is_exact_closed_and_non_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, file_trace, loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    schema = json.loads(
        (
            ROOT
            / "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v4.schema.json"
        ).read_text(encoding="utf-8")
    )
    schema_validator = Draft202012Validator(schema)

    for document in (process_trace, image_trace, file_trace, loss_trace):
        schema_validator.validate(document)
        checked = discovery.validate_windows_debug_runtime_discovery_v4_trace(document)
        assert checked == document
        assert checked is not document
        assert document["authority"] == discovery._fixed_authority()
        assert all(
            document["authority"][field] is False
            for field in (
                "authoritative",
                "complete_exact_runtime_closure",
                "promotion_eligible",
                "release3_included",
            )
        )

    assert file_trace["persistent_file_identity_and_loaded_bytes_bound"] is False
    assert file_trace["mapped_or_loaded_memory_bytes_bound"] is False
    assert image_trace["history_complete"] is False
    assert loss_trace["event_stream_contiguous"] is False
    assert loss_trace["start_end_snapshot_reconciled"] is False
    assert loss_trace["os_event_sequence_available"] is False
    assert loss_trace["os_loss_counter_available"] is False
    assert discovery._validate_debug_v4_file_image_projection(
        process_trace, image_trace, file_trace
    ) is None

    extra = deepcopy(file_trace)
    extra["loaded_memory_digest"] = contract.bytes_digest(b"forbidden claim")
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_TRACE_SHAPE_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(extra)

    for field in (
        "persistent_file_identity_and_loaded_bytes_bound",
        "mapped_or_loaded_memory_bytes_bound",
    ):
        inflated = deepcopy(file_trace)
        inflated[field] = True
        with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_TRACE_INVALID$",
        ):
            discovery.validate_windows_debug_runtime_discovery_v4_trace(inflated)

    authority_injected = deepcopy(file_trace)
    authority_injected["authority"]["authoritative"] = True
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_RUNTIME_TRACE_COMMON_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(
            authority_injected
        )


@pytest.mark.parametrize("mutation", ["coordinated_omission", "token_substitution"])
def test_v4_file_identity_join_is_exactly_one_to_one_with_load_image_rows(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    process_trace, image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    forged = deepcopy(file_trace)
    if mutation == "coordinated_omission":
        forged["rows"].pop()
        _refresh_v4_file_identity_totals(forged)
    else:
        forged["rows"][0]["mapping_token"] = "mapping.forged"

    # Each forgery is internally closed as a standalone file trace.  Only the exact
    # cross-document LOAD_IMAGE projection is able to detect the substitution/omission.
    assert discovery.validate_windows_debug_runtime_discovery_v4_trace(forged) == forged
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IMAGE_JOIN_FAILED$",
    ):
        discovery._validate_debug_v4_file_image_projection(
            process_trace, image_trace, forged
        )


def test_v4_file_identity_join_requires_non_null_handle_facts_in_both_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_trace, image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    forged_process = deepcopy(process_trace)
    forged_image = deepcopy(image_trace)
    for row in forged_process["events"]:
        if row["event"] in {"CREATE_PROCESS", "LOAD_DLL"}:
            row["file_handle_present"] = False
    for row in forged_image["events"]:
        if row["event"] == "LOAD_IMAGE":
            row["file_handle_present"] = False
    forged_image["debug_event_stream_digest"] = contract.canonical_digest(
        forged_process["events"]
    )

    assert discovery.validate_windows_debug_runtime_discovery_v4_trace(
        forged_process
    ) == forged_process
    assert discovery.validate_windows_debug_runtime_discovery_v4_trace(
        forged_image
    ) == forged_image
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IMAGE_JOIN_FAILED$",
    ):
        discovery._validate_debug_v4_file_image_projection(
            forged_process, forged_image, file_trace
        )


@pytest.mark.parametrize(
    ("trace_index", "field", "hostile_value", "error_code"),
    [
        (1, "method", None, "WINDOWS_DEBUG_V4_IMAGE_TRACE_INVALID"),
        (1, "method", [], "WINDOWS_DEBUG_V4_IMAGE_TRACE_INVALID"),
        (3, "limitations", None, "WINDOWS_DEBUG_V4_LOSS_TRACE_INVALID"),
        (3, "limitations", ["ARBITRARY"], "WINDOWS_DEBUG_V4_LOSS_TRACE_INVALID"),
    ],
)
def test_v4_specific_fields_are_checked_before_v3_projection(
    monkeypatch: pytest.MonkeyPatch,
    trace_index: int,
    field: str,
    hostile_value: Any,
    error_code: str,
) -> None:
    traces = _tokenized_v4_traces(monkeypatch)
    forged = deepcopy(traces[trace_index])
    forged[field] = hostile_value
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(forged)


def test_v4_borrowed_file_reader_requires_two_equal_same_handle_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _kernel32 = _complete_capture(monkeypatch)
    record = next(row for row in capture.records if row.event == "CREATE_PROCESS")
    first = contract.bytes_digest(b"first read")
    second = contract.bytes_digest(b"second read")

    class FixtureReader(discovery._BorrowedDebugEventFileReader):
        __slots__ = ("_fixture_digests",)

        def __init__(self, digests: tuple[str, str]) -> None:
            self._kernel32 = None
            self._total_file_bytes = 0
            self._fixture_digests = iter(digests)

        def _identity_and_size(self, _handle: Any) -> tuple[str, str, int]:
            return "0000000000000001", "00000000000000000000000000000002", 7

        def _whole_file_digest(self, _handle: Any, expected_size: int) -> str:
            assert expected_size == 7
            return next(self._fixture_digests)

    stable = FixtureReader((first, first)).observe(record, 101)
    assert stable["read_digests"] == (first, first)
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_FILE_READ_UNSTABLE$",
    ):
        FixtureReader((first, second)).observe(record, 101)


def test_v4_sealer_refuses_missing_null_and_unequal_file_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _kernel32 = _complete_capture(monkeypatch)
    process_tokens = {
        _ROOT_PID: "process.000000000001",
        _CHILD_PID: "process.000000000002",
    }
    observations = _raw_v4_file_observations(capture)

    missing = deepcopy(observations)
    missing.pop()
    null = deepcopy(observations)
    null[0] = None  # type: ignore[assignment]
    for refused in (missing, null):
        with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_DEBUG_V4_FILE_HANDLE_COVERAGE_INCOMPLETE$",
        ):
            discovery._seal_debug_file_identity_rows(
                capture, process_tokens, refused
            )

    unstable = deepcopy(observations)
    unstable[0]["read_digests"] = (
        unstable[0]["read_digests"][0],
        contract.bytes_digest(b"changed second read"),
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_TOKENIZATION_INVALID$",
    ):
        discovery._seal_debug_file_identity_rows(capture, process_tokens, unstable)


@pytest.mark.parametrize(
    ("location", "field", "error_code"),
    [
        ("row", "sequence", "WINDOWS_DEBUG_V4_FILE_IDENTITY_ROWS_INVALID"),
        (
            "row",
            "source_debug_sequence",
            "WINDOWS_DEBUG_V4_FILE_IDENTITY_ROWS_INVALID",
        ),
        ("row", "file_size_bytes", "WINDOWS_DEBUG_V4_FILE_IDENTITY_ROWS_INVALID"),
        (
            "aggregate",
            "unbound_debug_image_handle_count",
            "WINDOWS_DEBUG_V4_FILE_IDENTITY_RECONCILIATION_INVALID",
        ),
    ],
)
def test_v4_file_identity_validator_rejects_boolean_integer_substitution(
    monkeypatch: pytest.MonkeyPatch,
    location: str,
    field: str,
    error_code: str,
) -> None:
    _process_trace, _image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    forged = deepcopy(file_trace)
    target = forged["rows"][0] if location == "row" else forged
    target[field] = False
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(forged)


@pytest.mark.parametrize(
    ("read_index", "field", "hostile_value"),
    [
        (0, "sequence", False),
        (1, "sequence", True),
        (0, "offset", False),
    ],
)
def test_v4_file_identity_validator_rejects_boolean_read_coordinates(
    monkeypatch: pytest.MonkeyPatch,
    read_index: int,
    field: str,
    hostile_value: bool,
) -> None:
    _process_trace, _image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    forged = deepcopy(file_trace)
    forged["rows"][0]["read_passes"][read_index][field] = hostile_value
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_READS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(forged)


def test_v4_file_identity_validator_rejects_boolean_read_size_equal_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, _image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    forged = deepcopy(file_trace)
    row = forged["rows"][0]
    row["file_size_bytes"] = 1
    for read in row["read_passes"]:
        read["raw_bytes"] = 1
    _refresh_v4_file_identity_totals(forged)
    row["read_passes"][0]["raw_bytes"] = True
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_READS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(forged)


def test_v4_sealer_rejects_boolean_debug_sequence_even_when_equal_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _kernel32 = _complete_capture(monkeypatch)
    observations = _raw_v4_file_observations(capture)
    assert observations[0]["source_debug_sequence"] == 0
    observations[0]["source_debug_sequence"] = False
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_TOKENIZATION_INVALID$",
    ):
        discovery._seal_debug_file_identity_rows(
            capture,
            {
                _ROOT_PID: "process.000000000001",
                _CHILD_PID: "process.000000000002",
            },
            observations,
        )


def test_v4_sealer_stabilizes_an_unhashable_read_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _kernel32 = _complete_capture(monkeypatch)
    observations = _raw_v4_file_observations(capture)
    observations[0]["read_digests"] = (
        observations[0]["read_digests"][0],
        [],
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_TOKENIZATION_INVALID$",
    ):
        discovery._seal_debug_file_identity_rows(
            capture,
            {
                _ROOT_PID: "process.000000000001",
                _CHILD_PID: "process.000000000002",
            },
            observations,
        )


def test_v4_validator_stabilizes_an_unhashable_mapping_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process_trace, _image_trace, file_trace, _loss_trace = _tokenized_v4_traces(
        monkeypatch
    )
    file_trace["rows"][0]["mapping_kind"] = []
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IDENTITY_ROWS_INVALID$",
    ):
        discovery.validate_windows_debug_runtime_discovery_v4_trace(file_trace)


def test_v4_projects_to_v3_without_mutating_v2_or_v3_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v2_documents = _tokenized_traces(monkeypatch)
    v3_documents = _tokenized_v3_traces(monkeypatch)
    v3_raw_before = tuple(contract.canonical_json_bytes(row) for row in v3_documents)
    process_v4, image_v4, _file_v4, loss_v4 = _tokenized_v4_traces(monkeypatch)

    for document in v2_documents:
        assert document["capture_protocol"] == discovery._fixed_debug_capture_protocol()
        assert discovery.validate_windows_debug_runtime_discovery_trace(document) == document
    for document in v3_documents:
        assert document["capture_protocol"] == discovery._fixed_debug_v3_capture_protocol()
        assert discovery.validate_windows_debug_runtime_discovery_v3_trace(document) == document
    assert tuple(contract.canonical_json_bytes(row) for row in v3_documents) == v3_raw_before
    assert discovery._project_debug_v4_trace_to_v3(process_v4) == v3_documents[0]
    assert discovery._project_debug_v4_trace_to_v3(image_v4) == v3_documents[1]
    assert discovery._project_debug_v4_trace_to_v3(loss_v4) == v3_documents[2]
    for document in (process_v4, image_v4, loss_v4):
        with pytest.raises(discovery.RuntimeDiscoveryError):
            discovery.validate_windows_debug_runtime_discovery_v3_trace(document)


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


def _install_duplicate_handle_fixture(
    kernel32: _FakeKernel32,
    *,
    failure: BaseException | None = None,
) -> list[tuple[int, int, int, bool, int, int]]:
    calls: list[tuple[int, int, int, bool, int, int]] = []
    next_handle = iter(range(0xD001, 0xD100))
    kernel32.GetCurrentProcess = _FakeFunction(lambda: 0xFFFFFFFF)

    def duplicate(
        source_process: Any,
        source_handle: Any,
        target_process: Any,
        target_pointer: Any,
        desired_access: Any,
        inherit: Any,
        options: Any,
    ) -> int:
        calls.append((
            _integer(source_process),
            _integer(source_handle),
            _integer(target_process),
            bool(inherit),
            _integer(desired_access),
            _integer(options),
        ))
        if failure is not None:
            raise failure
        value = next(next_handle)
        ctypes.cast(target_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = value
        return 1

    kernel32.DuplicateHandle = _FakeFunction(duplicate)
    return calls


def test_v5_memory_observer_uses_fresh_least_privilege_duplicates_and_closes_before_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        _event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xA01, base=0x1000),
        _event(debug._EXCEPTION_DEBUG_EVENT),
        _event(debug._LOAD_DLL_DEBUG_EVENT, file_handle=0xA02, base=0x3000),
        _event(debug._EXIT_PROCESS_DEBUG_EVENT),
    ]
    session, kernel32 = _fake_session(monkeypatch, events)
    duplicate_calls = _install_duplicate_handle_fixture(kernel32)
    order: list[tuple[str, int]] = []
    original_close = kernel32._close
    original_continue = kernel32._continue
    kernel32.CloseHandle = _FakeFunction(
        lambda handle: (order.append(("close", _integer(handle))), original_close(handle))[1]
    )
    kernel32.ContinueDebugEvent = _FakeFunction(
        lambda pid, tid, status: (
            order.append(("continue", _integer(pid))),
            original_continue(pid, tid, status),
        )[1]
    )
    observed: list[tuple[str, int, int]] = []

    def observe(record: debug.DebugEventRecord, file_handle: int, process_handle: int) -> None:
        assert file_handle not in kernel32.closed_handles
        assert process_handle not in kernel32.closed_handles
        observed.append((record.event, file_handle, process_handle))

    while kernel32.events:
        assert session.pump(0, before_event_image_memory_read=observe) is True
    capture = session.snapshot()

    assert [row[:3] for row in duplicate_calls] == [
        (0xFFFFFFFF, 0x5000 + _ROOT_PID, 0xFFFFFFFF),
        (0xFFFFFFFF, 0x5000 + _ROOT_PID, 0xFFFFFFFF),
    ]
    assert all(row[3:] == (False, 0x0410, 0) for row in duplicate_calls)
    assert observed == [
        ("CREATE_PROCESS", 0xA01, 0xD001),
        ("LOAD_DLL", 0xA02, 0xD002),
    ]
    assert kernel32.closed_handles == [0xD001, 0xA01, 0xD002, 0xA02]
    assert 0x5000 + _ROOT_PID not in kernel32.closed_handles
    assert order.index(("close", 0xD001)) < order.index(("close", 0xA01))
    assert order.index(("close", 0xA01)) < order.index(("continue", _ROOT_PID))
    assert capture.created_process_ids == capture.exited_process_ids == (_ROOT_PID,)


def test_v5_duplicate_exception_still_closes_hfile_and_continues_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    _install_duplicate_handle_fixture(kernel32, failure=OSError("injected"))
    observed: list[tuple[debug.DebugEventRecord, int, int]] = []

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_MEMORY_OBSERVER_FAILED$",
    ):
        session.pump(
            0,
            before_event_image_memory_read=lambda *args: observed.append(args),
        )

    assert observed == []
    assert kernel32.closed_handles == [0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.record_count == 1


def test_v5_duplicate_false_after_writing_output_reclaims_it_before_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    kernel32.GetCurrentProcess = _FakeFunction(lambda: 0xFFFFFFFF)

    def false_after_write(
        _source_process: Any,
        _source_handle: Any,
        _target_process: Any,
        target_pointer: Any,
        _desired_access: Any,
        _inherit: Any,
        _options: Any,
    ) -> int:
        ctypes.cast(target_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = 0xD0FF
        return 0

    kernel32.DuplicateHandle = _FakeFunction(false_after_write)
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_MEMORY_OBSERVER_FAILED$",
    ):
        session.pump(0, before_event_image_memory_read=lambda *_args: None)

    assert kernel32.closed_handles == [0xD0FF, 0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.record_count == 1


@pytest.mark.parametrize("raising_handles", [{0xD001}, {0xABC}, {0xD001, 0xABC}])
def test_v5_raising_closehandle_still_attempts_both_closes_and_continues_once(
    monkeypatch: pytest.MonkeyPatch,
    raising_handles: set[int],
) -> None:
    session, kernel32 = _fake_session(
        monkeypatch,
        [_event(debug._CREATE_PROCESS_DEBUG_EVENT, file_handle=0xABC)],
    )
    _install_duplicate_handle_fixture(kernel32)
    attempted: list[int] = []

    def hostile_close(handle: Any) -> int:
        raw = _integer(handle)
        attempted.append(raw)
        if raw in raising_handles:
            raise OSError("injected CloseHandle failure")
        return kernel32._close(handle)

    kernel32.CloseHandle = _FakeFunction(hostile_close)
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_HANDLE_CLOSE_FAILED$",
    ):
        session.pump(0, before_event_image_memory_read=lambda *_args: None)

    assert attempted == [0xD001, 0xABC]
    assert kernel32.continues == [(_ROOT_PID, _ROOT_TID, debug._DBG_CONTINUE)]
    assert session.record_count == 1
    assert kernel32.closed_handles == [
        handle for handle in (0xD001, 0xABC) if handle not in raising_handles
    ]


def test_v5_post_parse_process_handle_error_reaches_neither_observer_nor_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = _event(debug._CREATE_PROCESS_DEBUG_EVENT)
    create.u.CreateProcessInfo.hProcess = None
    session, kernel32 = _fake_session(
        monkeypatch,
        [create, _event(debug._EXCEPTION_DEBUG_EVENT), _event(debug._EXIT_PROCESS_DEBUG_EVENT)],
    )
    assert session.pump(0) is True
    assert session.pump(0) is True
    observed: list[debug.DebugEventRecord] = []

    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_PROCESS_HANDLE_LIFECYCLE_INVALID$",
    ):
        session.pump(
            0,
            before_continue=observed.append,
            before_event_image_memory_read=lambda *_args: None,
        )

    assert observed == []
    assert session.record_count == 2
    assert len(kernel32.continues) == 3


def test_v5_memory_observer_rejects_conflicting_or_noncallable_seams_before_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, kernel32 = _fake_session(monkeypatch, [])
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_OBSERVER_CONFLICT$",
    ):
        session.pump(
            0,
            before_event_file_close=lambda *_args: None,
            before_event_image_memory_read=lambda *_args: None,
        )
    with pytest.raises(
        debug.DebugEventEngineError,
        match="^WINDOWS_DEBUG_EVENT_MEMORY_OBSERVER_INVALID$",
    ):
        session.pump(0, before_event_image_memory_read=1)  # type: ignore[arg-type]
    assert kernel32.continues == []


class _FakeV5MemoryKernel32:
    def __init__(
        self,
        *,
        mapping_base: int,
        payload: bytes,
        regions: list[dict[str, int]],
        query_size_delta: int = 0,
        read_result: bool = True,
        read_count_delta: int = 0,
    ) -> None:
        self.mapping_base = mapping_base
        self.payload = payload
        self.regions = regions
        self.query_size_delta = query_size_delta
        self.read_result = read_result
        self.read_count_delta = read_count_delta
        self.query_calls: list[int] = []
        self.read_calls: list[tuple[int, int]] = []

    def VirtualQueryEx(
        self,
        _process_handle: Any,
        address: Any,
        information_pointer: Any,
        _information_size: int,
    ) -> int:
        query_address = int(address.value)
        row = self.regions[len(self.query_calls)]
        self.query_calls.append(query_address)
        information = information_pointer._obj
        information.BaseAddress = row["base"]
        information.AllocationBase = row["allocation_base"]
        information.AllocationProtect = row["protect"]
        information.PartitionId = 0
        information.RegionSize = row["size"]
        information.State = row["state"]
        information.Protect = row["protect"]
        information.Type = row["type"]
        return ctypes.sizeof(discovery._MemoryBasicInformation) + self.query_size_delta

    def ReadProcessMemory(
        self,
        _process_handle: Any,
        address: Any,
        buffer_pointer: Any,
        requested: int,
        read_count_pointer: Any,
    ) -> bool:
        read_address = int(address.value)
        self.read_calls.append((read_address, requested))
        count = requested + self.read_count_delta
        if self.read_result and count > 0:
            offset = read_address - self.mapping_base
            ctypes.memmove(buffer_pointer, self.payload[offset:offset + count], count)
        read_count_pointer._obj.value = max(count, 0)
        return self.read_result


def _fake_v5_memory_reader(
    kernel32: _FakeV5MemoryKernel32,
) -> discovery._BorrowedDebugEventFileMemoryReader:
    reader = object.__new__(discovery._BorrowedDebugEventFileMemoryReader)
    reader._kernel32 = kernel32
    reader._total_file_bytes = 0
    reader._total_image_memory_bytes = 0
    reader._total_memory_regions = 0
    return reader


def test_v5_memory_reader_reads_one_exact_contiguous_mem_image_partition() -> None:
    base = 0x10000000
    payload = b"MZ" + bytes((index % 251 for index in range(8190)))
    kernel32 = _FakeV5MemoryKernel32(
        mapping_base=base,
        payload=payload,
        regions=[
            {
                "base": base,
                "allocation_base": base,
                "size": 4096,
                "state": 0x1000,
                "protect": 0x02,
                "type": 0x1000000,
            },
            {
                "base": base + 4096,
                "allocation_base": base,
                "size": 4096,
                "state": 0x1000,
                "protect": 0x20,
                "type": 0x1000000,
            },
        ],
    )
    regions, digest, prefix = _fake_v5_memory_reader(kernel32)._memory_pass(
        1, base, len(payload)
    )

    assert kernel32.query_calls == [base, base + 4096]
    assert kernel32.read_calls == [(base, 4096), (base + 4096, 4096)]
    assert [row["rva"] for row in regions] == [0, 4096]
    assert [row["size_bytes"] for row in regions] == [4096, 4096]
    assert [row["protection_hex"] for row in regions] == ["00000002", "00000020"]
    assert digest == contract.bytes_digest(payload)
    assert prefix == payload


def test_v5_memory_reader_bounds_the_pe_span_without_claiming_allocation_exhaustion() -> None:
    base = 0x18000000
    payload = bytes(4096)
    kernel32 = _FakeV5MemoryKernel32(
        mapping_base=base,
        payload=payload,
        regions=[
            {
                "base": base,
                "allocation_base": base,
                "size": 8192,
                "state": 0x1000,
                "protect": 0x02,
                "type": 0x1000000,
            }
        ],
    )
    regions, digest, prefix = _fake_v5_memory_reader(kernel32)._memory_pass(
        1, base, len(payload)
    )

    assert kernel32.query_calls == [base]
    assert kernel32.read_calls == [(base, len(payload))]
    assert len(regions) == 1
    assert regions[0]["size_bytes"] == len(payload)
    assert digest == contract.bytes_digest(payload)
    assert prefix == payload


def test_v5_memory_reader_caps_hostile_tiny_region_partitions() -> None:
    base = 0x19000000
    count = discovery._MAX_DEBUG_MEMORY_REGIONS_PER_IMAGE_PASS + 1
    payload = bytes(count)
    kernel32 = _FakeV5MemoryKernel32(
        mapping_base=base,
        payload=payload,
        regions=[
            {
                "base": base + index,
                "allocation_base": base,
                "size": 1,
                "state": 0x1000,
                "protect": 0x02,
                "type": 0x1000000,
            }
            for index in range(count)
        ],
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V5_MEMORY_REGION_CEILING_EXCEEDED$",
    ):
        _fake_v5_memory_reader(kernel32)._memory_pass(1, base, len(payload))
    assert len(kernel32.query_calls) == discovery._MAX_DEBUG_MEMORY_REGIONS_PER_IMAGE_PASS


def test_v5_memory_reader_enforces_remaining_total_before_the_next_query() -> None:
    base = 0x1A000000
    payload = b"ab"
    kernel32 = _FakeV5MemoryKernel32(
        mapping_base=base,
        payload=payload,
        regions=[
            {
                "base": base + index,
                "allocation_base": base,
                "size": 1,
                "state": 0x1000,
                "protect": 0x02,
                "type": 0x1000000,
            }
            for index in range(2)
        ],
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V5_MEMORY_REGION_TOTAL_CEILING_EXCEEDED$",
    ):
        _fake_v5_memory_reader(kernel32)._memory_pass(
            1, base, len(payload), total_region_allowance=1
        )
    assert kernel32.query_calls == [base]
    assert kernel32.read_calls == [(base, 1)]


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("short_query", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("region_gap", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("wrong_allocation", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("uncommitted", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("not_image", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("zero_protection", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("modifier_only_protection", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("unknown_protection_bit", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("nocache_writecombine", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("cfg_nonexecutable", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("guard", "WINDOWS_DEBUG_V5_MEMORY_REGION_INVALID"),
        ("read_failure", "WINDOWS_DEBUG_V5_MEMORY_READ_FAILED"),
        ("partial_read", "WINDOWS_DEBUG_V5_MEMORY_READ_PARTIAL"),
    ],
)
def test_v5_memory_reader_fails_closed_on_native_region_or_read_anomalies(
    mutation: str,
    error_code: str,
) -> None:
    base = 0x20000000
    payload = bytes(4096)
    region = {
        "base": base,
        "allocation_base": base,
        "size": len(payload),
        "state": 0x1000,
        "protect": 0x02,
        "type": 0x1000000,
    }
    kwargs: dict[str, Any] = {}
    if mutation == "short_query":
        kwargs["query_size_delta"] = -1
    elif mutation == "region_gap":
        region["base"] += 1
    elif mutation == "wrong_allocation":
        region["allocation_base"] += 4096
    elif mutation == "uncommitted":
        region["state"] = 0x2000
    elif mutation == "not_image":
        region["type"] = 0x20000
    elif mutation == "zero_protection":
        region["protect"] = 0
    elif mutation == "modifier_only_protection":
        region["protect"] = 0x200
    elif mutation == "unknown_protection_bit":
        region["protect"] = 0x80000002
    elif mutation == "nocache_writecombine":
        region["protect"] = 0x602
    elif mutation == "cfg_nonexecutable":
        region["protect"] = 0x40000002
    elif mutation == "guard":
        region["protect"] = 0x102
    elif mutation == "read_failure":
        kwargs["read_result"] = False
    elif mutation == "partial_read":
        kwargs["read_count_delta"] = -1
    else:
        raise AssertionError(mutation)
    kernel32 = _FakeV5MemoryKernel32(
        mapping_base=base,
        payload=payload,
        regions=[region],
        **kwargs,
    )
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        _fake_v5_memory_reader(kernel32)._memory_pass(1, base, len(payload))


def _v5_fixture_pe_layout() -> dict[str, Any]:
    return {
        "machine": "AMD64",
        "optional_header_format": "PE32_PLUS",
        "pe_header_offset": 64,
        "number_of_sections": 1,
        "size_of_optional_header": 240,
        "address_of_entry_point_rva": 4096,
        "section_alignment": 4096,
        "file_alignment": 512,
        "size_of_image": 8192,
        "size_of_headers": 512,
        "number_of_rva_and_sizes": 0,
        "data_directories": [],
        "sections": [
            {
                "sequence": 0,
                "virtual_address_rva": 4096,
                "virtual_size_bytes": 1,
                "raw_file_offset": 0,
                "raw_size_bytes": 0,
                "characteristics_hex": "60000020",
            }
        ],
    }


def test_v5_observer_accepts_cow_region_split_with_stable_whole_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _v5_fixture_pe_layout()
    disk_digest = contract.bytes_digest(b"disk")
    memory_digest = contract.bytes_digest(b"memory")
    prefix = b"retained-pe-header"

    def region(
        sequence: int,
        rva: int,
        size_bytes: int,
        protection_hex: str,
    ) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "rva": rva,
            "size_bytes": size_bytes,
            "allocation_base_matches_event_image": True,
            "state": "MEM_COMMIT",
            "type": "MEM_IMAGE",
            "protection_hex": protection_hex,
            "digest": contract.bytes_digest(
                f"region:{sequence}:{rva}:{size_bytes}:{protection_hex}".encode("ascii")
            ),
        }

    memory_passes = iter((
        ((region(0, 0, 8192, "00000008"),), memory_digest, prefix),
        (
            (
                region(0, 0, 4096, "00000008"),
                region(1, 4096, 4096, "00000004"),
            ),
            memory_digest,
            prefix,
        ),
    ))
    reader = object.__new__(discovery._BorrowedDebugEventFileMemoryReader)
    reader._kernel32 = object()
    reader._total_file_bytes = 0
    reader._total_image_memory_bytes = 0
    reader._total_memory_regions = 0
    monkeypatch.setattr(
        discovery._BorrowedDebugEventFileMemoryReader,
        "_identity_and_size",
        lambda _self, _handle: ("0123456789abcdef", "0" * 32, 1024),
    )
    monkeypatch.setattr(
        discovery._BorrowedDebugEventFileMemoryReader,
        "_whole_file_digest_and_prefix",
        lambda _self, _handle, _size, _prefix_size: (disk_digest, prefix),
    )
    monkeypatch.setattr(
        discovery._BorrowedDebugEventFileMemoryReader,
        "_memory_pass",
        lambda _self, *_args, **_kwargs: next(memory_passes),
    )
    monkeypatch.setattr(
        discovery,
        "_parse_debug_amd64_pe_layout",
        lambda _raw, *, disk_file_size: deepcopy(layout),
    )
    record = debug.DebugEventRecord(
        sequence=7,
        event="LOAD_DLL",
        event_code=debug._LOAD_DLL_DEBUG_EVENT,
        process_id=_ROOT_PID,
        thread_id=_ROOT_TID,
        mapping_base=0x400000,
        mapping_kind="DLL_IMAGE",
        continue_status="DBG_CONTINUE",
        exception_code=None,
        exception_disposition=None,
        first_chance=None,
        exit_code=None,
        file_handle_present=True,
        debug_string_code_units=None,
        debug_string_unicode=None,
        implicit_unmap_bases=(),
    )

    observation = reader.observe(record, 0xA01, 0xD01)

    assert [len(item) for item in observation["memory_region_passes"]] == [1, 2]
    assert observation["memory_read_digests"] == (memory_digest, memory_digest)
    assert reader._total_memory_regions == 3


def _raw_v5_file_memory_observations(
    capture: debug.DebugEventCapture,
) -> list[dict[str, Any]]:
    observations = _raw_v4_file_observations(capture)
    for raw in observations:
        sequence = raw["source_debug_sequence"]
        disk_digest = contract.bytes_digest(f"v5-disk:{sequence}".encode("ascii"))
        memory_digest = contract.bytes_digest(f"v5-memory:{sequence}".encode("ascii"))
        memory_regions = (
            {
                "sequence": 0,
                "rva": 0,
                "size_bytes": 4096,
                "allocation_base_matches_event_image": True,
                "state": "MEM_COMMIT",
                "type": "MEM_IMAGE",
                "protection_hex": "00000002",
                "digest": contract.bytes_digest(
                    f"v5-region-0:{sequence}".encode("ascii")
                ),
            },
            {
                "sequence": 1,
                "rva": 4096,
                "size_bytes": 4096,
                "allocation_base_matches_event_image": True,
                "state": "MEM_COMMIT",
                "type": "MEM_IMAGE",
                "protection_hex": "00000020",
                "digest": contract.bytes_digest(
                    f"v5-region-1:{sequence}".encode("ascii")
                ),
            },
        )
        raw.update({
            "file_size_bytes": 1024,
            "read_digests": (disk_digest, disk_digest),
            "pe_layout": _v5_fixture_pe_layout(),
            "memory_size_bytes": 8192,
            "memory_region_passes": (
                memory_regions,
                deepcopy(memory_regions),
            ),
            "memory_read_digests": (memory_digest, memory_digest),
        })
    return observations


def _refresh_v5_file_memory_totals(trace: dict[str, Any]) -> None:
    _refresh_v4_file_identity_totals(trace)
    rows = trace["rows"]
    total = sum(row["memory_size_bytes"] for row in rows)
    trace.update({
        "stable_event_coincident_memory_count": len(rows),
        "total_stable_memory_bytes": total,
        "total_process_memory_read_bytes": (
            total * discovery._DEBUG_MEMORY_STABLE_READ_PASSES
        ),
        "total_memory_region_count": sum(
            len(region_pass["regions"])
            for row in rows
            for region_pass in row["memory_region_passes"]
        ),
    })


def _tokenized_v5_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    process_trace, image_trace, file_trace, loss_trace = _tokenized_v4_traces(monkeypatch)
    capture, _kernel32 = _complete_capture(monkeypatch)
    process_tokens = {
        _ROOT_PID: "process.000000000001",
        _CHILD_PID: "process.000000000002",
    }
    rows = discovery._seal_debug_file_memory_rows(
        capture,
        process_tokens,
        _raw_v5_file_memory_observations(capture),
    )
    schema_updates = (
        (process_trace, discovery._fixed_debug_v5_process_trace_schema()),
        (image_trace, discovery._fixed_debug_v5_image_trace_schema()),
        (loss_trace, discovery._fixed_debug_v5_loss_trace_schema()),
    )
    for document, schema in schema_updates:
        document.update({
            "schema": schema,
            "capture_protocol": discovery._fixed_debug_v5_capture_protocol(),
            "claim_boundary": discovery._fixed_debug_v5_claim_boundary(),
        })
    image_trace["method"] = (
        "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_START_END_"
        "STABLE_DOUBLE_READ/5"
    )
    loss_trace["limitations"] = list(discovery._fixed_debug_v5_limitations())
    file_trace.update({
        "schema": discovery._fixed_debug_v5_file_identity_trace_schema(),
        "capture_protocol": discovery._fixed_debug_v5_capture_protocol(),
        "claim_boundary": discovery._fixed_debug_v5_claim_boundary(),
        "method": (
            "WINDOWS_DEBUG_EVENT_BORROWED_HFILE_AND_DUPLICATED_HPROCESS_"
            "STABLE_DISK_AND_MEM_IMAGE_DOUBLE_READ"
        ),
        "semantics": (
            "RECEIVED_DEBUG_IMAGE_EVENTS_TO_PERSISTENT_FILE_ID_STABLE_DISK_BYTES_"
            "AND_EVENT_COINCIDENT_COMPLETE_PE_SIZE_OF_IMAGE_SPAN"
        ),
        "collection_guards": {
            "max_file_bytes": discovery._MAX_DEBUG_FILE_BYTES,
            "max_total_file_bytes": discovery._MAX_DEBUG_TOTAL_FILE_BYTES,
            "read_chunk_bytes": discovery._DEBUG_FILE_READ_CHUNK_BYTES,
            "stable_read_passes": discovery._DEBUG_FILE_STABLE_READ_PASSES,
            "max_image_memory_bytes": discovery._MAX_DEBUG_IMAGE_MEMORY_BYTES,
            "max_total_image_memory_bytes": discovery._MAX_DEBUG_TOTAL_IMAGE_MEMORY_BYTES,
            "memory_read_chunk_bytes": discovery._DEBUG_MEMORY_READ_CHUNK_BYTES,
            "memory_stable_read_passes": discovery._DEBUG_MEMORY_STABLE_READ_PASSES,
            "max_pe_header_bytes": discovery._MAX_DEBUG_PE_HEADER_BYTES,
            "max_pe_sections": discovery._MAX_DEBUG_PE_SECTIONS,
            "max_memory_regions_per_image_pass": (
                discovery._MAX_DEBUG_MEMORY_REGIONS_PER_IMAGE_PASS
            ),
            "max_total_memory_regions": discovery._MAX_DEBUG_TOTAL_MEMORY_REGIONS,
        },
        "binding_scope": (
            "RECEIVED_DEBUG_IMAGE_EVENTS_AT_SUSPENDED_PRE_CONTINUE_INSTANT"
        ),
        "persistent_file_identity_and_loaded_bytes_bound": False,
        "mapped_or_loaded_memory_bytes_bound": True,
        "event_coincident_mem_image_bytes_bound": True,
        "disk_memory_byte_equality_claimed": False,
        "loader_transformations_interpreted": False,
        "loaded_memory_lifetime_immutability_claimed": False,
        "rows": rows,
    })
    _refresh_v5_file_memory_totals(file_trace)
    return process_trace, image_trace, file_trace, loss_trace


def test_v5_file_memory_trace_is_closed_incomplete_and_projects_exactly_to_v4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = _tokenized_v5_traces(monkeypatch)
    schema = json.loads(
        (
            ROOT
            / "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v5.schema.json"
        ).read_text(encoding="utf-8")
    )
    schema_validator = Draft202012Validator(schema)
    raw_before = tuple(contract.canonical_json_bytes(row) for row in documents)

    for document in documents:
        schema_validator.validate(document)
        assert discovery.validate_windows_debug_runtime_discovery_v5_trace(document) == document
        projected = discovery._project_debug_v5_trace_to_v4(document)
        assert discovery.validate_windows_debug_runtime_discovery_v4_trace(projected) == projected

    process, image, file_trace, loss = documents
    assert tuple(contract.canonical_json_bytes(row) for row in documents) == raw_before
    assert file_trace["persistent_file_identity_and_loaded_bytes_bound"] is False
    assert file_trace["mapped_or_loaded_memory_bytes_bound"] is True
    assert file_trace["event_coincident_mem_image_bytes_bound"] is True
    assert file_trace["disk_memory_byte_equality_claimed"] is False
    assert file_trace["loaded_memory_lifetime_immutability_claimed"] is False
    assert image["history_complete"] is False
    assert loss["event_stream_contiguous"] is False
    assert loss["os_loss_counter_available"] is False
    assert discovery._validate_debug_v5_file_image_projection(
        process, image, file_trace
    ) is None


def test_v5_validator_accepts_independently_complete_pass_specific_topologies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _process, _image, file_trace, _loss = _tokenized_v5_traces(monkeypatch)
    changed = deepcopy(file_trace)
    row = changed["rows"][0]
    second_pass = row["memory_region_passes"][1]
    tail = deepcopy(second_pass["regions"][1])
    tail["sequence"] = 2
    second_pass["regions"] = [
        {
            **deepcopy(second_pass["regions"][0]),
            "size_bytes": 2048,
            "protection_hex": "00000008",
            "digest": contract.bytes_digest(b"cow-before"),
        },
        {
            **deepcopy(second_pass["regions"][0]),
            "sequence": 1,
            "rva": 2048,
            "size_bytes": 2048,
            "protection_hex": "00000004",
            "digest": contract.bytes_digest(b"cow-after"),
        },
        tail,
    ]
    row["binding_digest"] = discovery._debug_v5_binding_digest(row)
    _refresh_v5_file_memory_totals(changed)

    assert discovery.validate_windows_debug_runtime_discovery_v5_trace(changed) == changed
    assert [
        len(region_pass["regions"])
        for region_pass in row["memory_region_passes"]
    ] == [2, 3]
    assert row["memory_read_passes"][0]["digest"] == row["memory_read_passes"][1][
        "digest"
    ]


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("region_gap", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("guard_page", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("memory_digest_drift", "WINDOWS_DEBUG_V5_MEMORY_READS_INVALID"),
        ("binding_digest", "WINDOWS_DEBUG_V5_MEMORY_READS_INVALID"),
        ("boolean_memory_size", "WINDOWS_DEBUG_V5_FILE_MEMORY_ROWS_INVALID"),
        ("boolean_section_count", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("file_alignment_one", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("zero_raw_size_offset", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("virtual_gap", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("zero_mapped_span", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("trailing_image_gap", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("raw_inside_headers", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("raw_reverse", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("low_alignment_offset_mismatch", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("certificate_beyond_file", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("zero_protection", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("modifier_only_protection", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("unknown_protection_bit", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("nocache_writecombine", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("cfg_nonexecutable", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("directory_table_overflow", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("section_table_beyond_headers", "WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID"),
        ("region_pass_sequence", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("region_pass_wrapper_extra", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("region_pass_count", "WINDOWS_DEBUG_V5_MEMORY_REGIONS_INVALID"),
        ("region_total_underreported", "WINDOWS_DEBUG_V5_MEMORY_TOTALS_INVALID"),
        ("persistent_claim", "WINDOWS_DEBUG_V5_FILE_MEMORY_TRACE_INVALID"),
        ("disk_equality_claim", "WINDOWS_DEBUG_V5_FILE_MEMORY_TRACE_INVALID"),
    ],
)
def test_v5_validator_rejects_memory_and_claim_inflation(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error_code: str,
) -> None:
    _process, _image, file_trace, _loss = _tokenized_v5_traces(monkeypatch)
    forged = deepcopy(file_trace)
    row = forged["rows"][0]
    if mutation == "region_gap":
        row["memory_region_passes"][1]["regions"][1]["rva"] += 1
    elif mutation == "guard_page":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "00000102"
    elif mutation == "memory_digest_drift":
        row["memory_read_passes"][1]["digest"] = contract.bytes_digest(b"drift")
    elif mutation == "binding_digest":
        row["binding_digest"] = contract.bytes_digest(b"forged")
    elif mutation == "boolean_memory_size":
        row["memory_size_bytes"] = True
    elif mutation == "boolean_section_count":
        row["pe_layout"]["number_of_sections"] = True
    elif mutation == "file_alignment_one":
        row["pe_layout"]["file_alignment"] = 1
    elif mutation == "zero_raw_size_offset":
        row["pe_layout"]["sections"][0]["raw_file_offset"] = 512
    elif mutation == "virtual_gap":
        row["pe_layout"]["size_of_image"] = 12288
        row["pe_layout"]["sections"][0]["virtual_address_rva"] = 8192
    elif mutation == "zero_mapped_span":
        row["pe_layout"]["sections"][0]["virtual_size_bytes"] = 0
    elif mutation == "trailing_image_gap":
        row["pe_layout"]["size_of_image"] = 12288
    elif mutation == "raw_inside_headers":
        row["pe_layout"]["size_of_headers"] = 1024
        row["pe_layout"]["sections"][0].update({
            "raw_file_offset": 512,
            "raw_size_bytes": 512,
        })
    elif mutation == "raw_reverse":
        row["file_size_bytes"] = 2048
        row["pe_layout"].update({
            "number_of_sections": 2,
            "size_of_image": 12288,
            "sections": [
                {
                    "sequence": 0,
                    "virtual_address_rva": 4096,
                    "virtual_size_bytes": 1,
                    "raw_file_offset": 1024,
                    "raw_size_bytes": 512,
                    "characteristics_hex": "60000020",
                },
                {
                    "sequence": 1,
                    "virtual_address_rva": 8192,
                    "virtual_size_bytes": 1,
                    "raw_file_offset": 512,
                    "raw_size_bytes": 512,
                    "characteristics_hex": "c0000040",
                },
            ],
        })
    elif mutation == "low_alignment_offset_mismatch":
        row["file_size_bytes"] = 2048
        row["pe_layout"].update({
            "section_alignment": 512,
            "file_alignment": 512,
            "size_of_image": 1024,
            "size_of_headers": 512,
        })
        row["pe_layout"]["sections"][0].update({
            "virtual_address_rva": 512,
            "virtual_size_bytes": 512,
            "raw_file_offset": 1024,
            "raw_size_bytes": 512,
        })
    elif mutation == "certificate_beyond_file":
        row["pe_layout"]["number_of_rva_and_sizes"] = 5
        row["pe_layout"]["data_directories"] = [
            {"sequence": sequence, "rva_or_file_offset": 0, "size_bytes": 0}
            for sequence in range(4)
        ] + [{"sequence": 4, "rva_or_file_offset": 2048, "size_bytes": 8}]
    elif mutation == "zero_protection":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "00000000"
    elif mutation == "modifier_only_protection":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "00000200"
    elif mutation == "unknown_protection_bit":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "80000002"
    elif mutation == "nocache_writecombine":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "00000602"
    elif mutation == "cfg_nonexecutable":
        row["memory_region_passes"][1]["regions"][0]["protection_hex"] = "40000002"
    elif mutation == "directory_table_overflow":
        row["pe_layout"]["size_of_optional_header"] = 112
        row["pe_layout"]["number_of_rva_and_sizes"] = 1
        row["pe_layout"]["data_directories"] = [
            {"sequence": 0, "rva_or_file_offset": 0, "size_bytes": 0}
        ]
    elif mutation == "section_table_beyond_headers":
        row["pe_layout"]["pe_header_offset"] = 256
        row["pe_layout"]["size_of_optional_header"] = 240
    elif mutation == "region_pass_sequence":
        row["memory_region_passes"][1]["sequence"] = 0
    elif mutation == "region_pass_wrapper_extra":
        row["memory_region_passes"][1]["unexpected"] = False
    elif mutation == "region_pass_count":
        row["memory_region_passes"].pop()
    elif mutation == "region_total_underreported":
        forged["total_memory_region_count"] -= 1
    elif mutation == "persistent_claim":
        forged["persistent_file_identity_and_loaded_bytes_bound"] = True
    elif mutation == "disk_equality_claim":
        forged["disk_memory_byte_equality_claimed"] = True
    else:
        raise AssertionError(mutation)
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        discovery.validate_windows_debug_runtime_discovery_v5_trace(forged)


def test_v5_file_memory_join_rejects_coordinated_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process, image, file_trace, _loss = _tokenized_v5_traces(monkeypatch)
    forged = deepcopy(file_trace)
    forged["rows"].pop()
    _refresh_v5_file_memory_totals(forged)
    assert discovery.validate_windows_debug_runtime_discovery_v5_trace(forged) == forged
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V4_FILE_IMAGE_JOIN_FAILED$",
    ):
        discovery._validate_debug_v5_file_image_projection(process, image, forged)


@pytest.mark.skipif(
    os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8,
    reason="native Windows AMD64 MEMORY_BASIC_INFORMATION only",
)
def test_v5_memory_basic_information_amd64_layout_is_exact() -> None:
    assert ctypes.sizeof(discovery._MemoryBasicInformation) == 48
    assert discovery._MemoryBasicInformation.BaseAddress.offset == 0
    assert discovery._MemoryBasicInformation.AllocationBase.offset == 8
    assert discovery._MemoryBasicInformation.AllocationProtect.offset == 16
    assert discovery._MemoryBasicInformation.PartitionId.offset == 20
    assert discovery._MemoryBasicInformation.RegionSize.offset == 24
    assert discovery._MemoryBasicInformation.State.offset == 32
    assert discovery._MemoryBasicInformation.Protect.offset == 36
    assert discovery._MemoryBasicInformation.Type.offset == 40


@pytest.mark.skipif(os.name != "nt", reason="PE host executable required")
def test_v5_pe_parser_accepts_host_amd64_image_and_rejects_hostile_offsets() -> None:
    executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    raw = executable.read_bytes()
    layout = discovery._parse_debug_amd64_pe_layout(
        raw[:discovery._MAX_DEBUG_PE_HEADER_BYTES], disk_file_size=len(raw)
    )
    discovery._validate_debug_v5_pe_layout_value(layout, len(raw))
    assert layout["machine"] == "AMD64"
    hostile = bytearray(raw[:discovery._MAX_DEBUG_PE_HEADER_BYTES])
    hostile[0x3C:0x40] = (discovery._MAX_DEBUG_PE_HEADER_BYTES).to_bytes(4, "little")
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID$",
    ):
        discovery._parse_debug_amd64_pe_layout(bytes(hostile), disk_file_size=len(raw))

    invalid_file_alignment = bytearray(raw[:discovery._MAX_DEBUG_PE_HEADER_BYTES])
    pe_offset = int.from_bytes(invalid_file_alignment[0x3C:0x40], "little")
    optional_offset = pe_offset + 24
    invalid_file_alignment[optional_offset + 36:optional_offset + 40] = (1).to_bytes(
        4, "little"
    )
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID$",
    ):
        discovery._parse_debug_amd64_pe_layout(
            bytes(invalid_file_alignment), disk_file_size=len(raw)
        )

    certificate_beyond_file = bytearray(raw[:discovery._MAX_DEBUG_PE_HEADER_BYTES])
    pe_offset = int.from_bytes(certificate_beyond_file[0x3C:0x40], "little")
    optional_offset = pe_offset + 24
    certificate_offset = optional_offset + 112 + 4 * 8
    certificate_beyond_file[certificate_offset:certificate_offset + 4] = (
        len(raw) + 8
    ).to_bytes(4, "little")
    certificate_beyond_file[certificate_offset + 4:certificate_offset + 8] = (
        8
    ).to_bytes(4, "little")
    with pytest.raises(
        discovery.RuntimeDiscoveryError,
        match="^WINDOWS_DEBUG_V5_PE_LAYOUT_INVALID$",
    ):
        discovery._parse_debug_amd64_pe_layout(
            bytes(certificate_beyond_file), disk_file_size=len(raw)
        )
