"""Presentation-only state transitions; never owns server, Store or engine lifetime.

The dependency/native-API gate remains closed until accepted wheel, frozen payload
and native proof are available. Importing this module never imports pywebview/CLR.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from portable.native_origin import NativeRefusal


class State(str, Enum):
    WAIT_SERVER = "WAIT_SERVER"
    SERVER_READY = "SERVER_READY"
    GUI_STARTING = "GUI_STARTING"
    POLICY_ADMITTED = "POLICY_ADMITTED"
    NATIVE = "NATIVE"
    WAIT_DOWNLOAD = "WAIT_DOWNLOAD"
    RETIRING = "RETIRING"
    CLOSED = "CLOSED"
    BROWSER = "BROWSER"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    PRESENTATION_STOPPED = "PRESENTATION_STOPPED"


class Effect(str, Enum):
    START_GUI = "START_GUI"
    SHOW_GUI = "SHOW_GUI"
    RETIRE_GUI = "RETIRE_GUI"
    OPEN_BROWSER = "OPEN_BROWSER"
    PRINT_URL = "PRINT_URL"
    WAIT_DOWNLOAD = "WAIT_DOWNLOAD"


@dataclass(frozen=True)
class Transition:
    state: State
    effects: tuple[Effect, ...] = ()


class NativePresentationSupervisor:
    """Single-owner machine; its caller serializes GUI/IPC notifications.

    No effect can stop the server, close a Store, alter backend admission, pass a
    token or replay work. Effects are instructions, never proof of their success.
    """

    def __init__(self):
        self.state = State.WAIT_SERVER
        self.download_active = False
        self.intent = None
        self.gui_absent = True
        self.opener_pending = False

    def _result(self, state, *effects):
        self.state = state
        return Transition(state, effects)

    def _open(self):
        if not self.gui_absent:
            return self._result(State.MANUAL_REQUIRED, Effect.PRINT_URL)
        if self.opener_pending:
            return self._result(self.state)
        self.opener_pending = True
        self.intent = "browser"
        # Commit the choice before issuing the asynchronous effect. SERVER_READY
        # must not also admit START_NATIVE while the browser result is pending.
        state = State.BROWSER if self.state == State.BROWSER else State.RETIRING
        return self._result(state, Effect.OPEN_BROWSER)

    def _retire(self, intent):
        self.intent = intent
        return self._result(State.RETIRING, Effect.RETIRE_GUI)

    def notify(self, event: str) -> Transition:
        if type(event) is not str:
            raise NativeRefusal("presentation_event")
        if self.state == State.PRESENTATION_STOPPED:
            return self._result(self.state)
        if event == "SERVER_EXIT":
            self.opener_pending = False
            return self._result(State.PRESENTATION_STOPPED,
                                *((Effect.RETIRE_GUI,) if not self.gui_absent else ()))
        if self.opener_pending and event not in {"OPENER_ACCEPTED", "OPENER_FAILED"}:
            if event in {"CLOSE", "FAULT", "GUI_RETIRED", "TEARDOWN_UNPROVED", "BROWSER_REQUEST"}:
                return self._result(self.state)
            # An already-issued OS launch cannot be undone by a late native or
            # manual eligibility result. Keep the printed URL as manual escape.
            raise NativeRefusal("presentation_event_order")
        if event == "SERVER_READY" and self.state == State.WAIT_SERVER:
            return self._result(State.SERVER_READY)
        if event == "START_NATIVE" and self.state == State.SERVER_READY:
            self.gui_absent = False  # creation/containment failure still requires retirement observation
            return self._result(State.GUI_STARTING, Effect.START_GUI)
        if event == "USE_BROWSER" and self.state == State.SERVER_READY:
            return self._open()
        if event == "MANUAL" and self.state in {State.SERVER_READY, State.CLOSED, State.MANUAL_REQUIRED}:
            return self._result(State.MANUAL_REQUIRED, Effect.PRINT_URL)
        if event == "POLICY_ADMITTED" and self.state == State.GUI_STARTING:
            return self._result(State.POLICY_ADMITTED)
        if event == "DOCUMENT_READY" and self.state == State.POLICY_ADMITTED:
            return self._result(State.NATIVE, Effect.SHOW_GUI)
        if event == "DOWNLOAD_ACTIVE" and self.state == State.NATIVE and not self.download_active:
            self.download_active = True
            return self._result(self.state)
        if event == "DOWNLOAD_SETTLED" and self.state in {State.NATIVE, State.WAIT_DOWNLOAD}:
            if not self.download_active:
                raise NativeRefusal("download_state")
            self.download_active = False
            if self.state == State.WAIT_DOWNLOAD:
                return self._retire(self.intent)
            return self._result(self.state)
        if event in {"CLOSE", "BROWSER_REQUEST"} and self.state == State.NATIVE:
            self.intent = "close" if event == "CLOSE" else "browser"
            if self.download_active:
                return self._result(State.WAIT_DOWNLOAD, Effect.WAIT_DOWNLOAD)
            return self._retire(self.intent)
        if event in {"CLOSE", "BROWSER_REQUEST"} and self.state == State.WAIT_DOWNLOAD:
            return self._result(self.state)  # preserve the first intent; no second download admission
        if event == "FAULT" and self.state in {
            State.GUI_STARTING, State.POLICY_ADMITTED, State.NATIVE, State.WAIT_DOWNLOAD,
        }:
            # The download owner records INCOMPLETE before acting on RETIRE_GUI.
            self.download_active = False
            return self._retire("fallback")
        if event in {"FAULT", "CLOSE", "BROWSER_REQUEST", "TEARDOWN_UNPROVED"} and self.state == State.RETIRING:
            if event == "TEARDOWN_UNPROVED":
                return self._result(State.MANUAL_REQUIRED, Effect.PRINT_URL)
            return self._result(self.state)
        if event == "GUI_RETIRED" and self.state in {State.RETIRING, State.MANUAL_REQUIRED}:
            self.gui_absent = True
            if self.state == State.MANUAL_REQUIRED:
                return self._result(self.state)  # late exit does not auto-launch a second presenter
            if self.intent == "close":
                return self._result(State.CLOSED, Effect.PRINT_URL)
            return self._open()
        if event in {"OPENER_ACCEPTED", "OPENER_FAILED"}:
            if not self.opener_pending:
                raise NativeRefusal("unexpected_opener_result")
            self.opener_pending = False
            if event == "OPENER_ACCEPTED":
                return self._result(State.BROWSER)
            state = State.BROWSER if self.state == State.BROWSER else State.MANUAL_REQUIRED
            return self._result(state, Effect.PRINT_URL)
        if event == "BROWSER_REQUEST" and self.state in {State.CLOSED, State.BROWSER, State.MANUAL_REQUIRED}:
            return self._open()
        if event in {"CLOSE", "FAULT", "GUI_RETIRED", "TEARDOWN_UNPROVED"} and self.state in {
            State.CLOSED, State.BROWSER, State.MANUAL_REQUIRED,
        }:
            return self._result(self.state)  # stale GUI events cannot resurrect a presenter
        raise NativeRefusal("presentation_event_order")


def require_native_release_admission() -> None:
    """Owner-held dependency publication is not replaced by an environment switch.

    This first slice cannot start native code even if an ambient webview package
    happens to be installed. Replace this refusal only with accepted immutable
    wheel/lock/payload admission and the approved frozen native proof.
    """
    raise NativeRefusal("native_dependency_publication_pending")
