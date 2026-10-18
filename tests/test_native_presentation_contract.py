"""Packaging-only native contracts; no renderer or real-time deadline in this module."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import hmac
import json
import sys

import pytest

from portable.native_ipc import MAX_FRAME, PeerIdentity, PresentationChannel
from portable.native_origin import NATIVE_CSP, NATIVE_HEADER, NativeOrigin, NativeRefusal, NativeResponsePolicy
from portable.native_window import Effect, NativePresentationSupervisor, State, require_native_release_admission


def native():
    machine = NativePresentationSupervisor()
    assert machine.notify("SERVER_READY").state == State.SERVER_READY
    assert machine.notify("START_NATIVE").effects == (Effect.START_GUI,)
    assert machine.notify("POLICY_ADMITTED").state == State.POLICY_ADMITTED
    assert machine.notify("DOCUMENT_READY").effects == (Effect.SHOW_GUI,)
    return machine


@pytest.mark.parametrize("intent", ["CLOSE", "BROWSER_REQUEST", "FAULT"])
def test_retirement_has_only_gui_effects_and_never_backend_ownership(intent):
    machine = native()
    result = machine.notify(intent)
    assert result == replace(result, state=State.RETIRING, effects=(Effect.RETIRE_GUI,))
    for late in ("FAULT", "CLOSE", "BROWSER_REQUEST"):
        assert machine.notify(late).effects == ()
    retired = machine.notify("GUI_RETIRED")
    if intent == "CLOSE":
        assert retired.state == State.CLOSED
        assert retired.effects == (Effect.PRINT_URL,)
    else:
        assert retired.effects == (Effect.OPEN_BROWSER,)
        assert machine.notify("OPENER_ACCEPTED").state == State.BROWSER
    assert {effect.value for effect in Effect} == {
        "START_GUI", "SHOW_GUI", "RETIRE_GUI", "OPEN_BROWSER", "PRINT_URL", "WAIT_DOWNLOAD",
    }


@pytest.mark.parametrize("intent", ["CLOSE", "BROWSER_REQUEST"])
def test_only_active_native_download_defers_gui_close_and_first_intent_survives(intent):
    machine = native()
    machine.notify("DOWNLOAD_ACTIVE")
    assert machine.notify(intent).state == State.WAIT_DOWNLOAD
    other = "CLOSE" if intent == "BROWSER_REQUEST" else "BROWSER_REQUEST"
    assert machine.notify(other).state == State.WAIT_DOWNLOAD
    assert machine.notify("DOWNLOAD_SETTLED").effects == (Effect.RETIRE_GUI,)
    result = machine.notify("GUI_RETIRED")
    assert result.state == (State.CLOSED if intent == "CLOSE" else State.RETIRING)
    assert result.effects == ((Effect.PRINT_URL,) if intent == "CLOSE" else (Effect.OPEN_BROWSER,))


def test_download_fault_does_not_wait_for_backend_or_offer_second_presenter_before_exit():
    machine = native()
    machine.notify("DOWNLOAD_ACTIVE")
    machine.notify("CLOSE")
    assert machine.notify("FAULT").effects == (Effect.RETIRE_GUI,)
    assert machine.notify("TEARDOWN_UNPROVED").state == State.MANUAL_REQUIRED
    assert machine.notify("BROWSER_REQUEST").effects == (Effect.PRINT_URL,)
    assert machine.notify("GUI_RETIRED").effects == ()
    assert machine.state == State.MANUAL_REQUIRED
    assert machine.notify("BROWSER_REQUEST").effects == (Effect.OPEN_BROWSER,)


@pytest.mark.parametrize("browser_accepted", [False, True])
def test_browser_and_manual_modes_never_return_to_a_retired_native_presenter(browser_accepted):
    machine = native()
    machine.notify("FAULT")
    machine.notify("GUI_RETIRED")
    machine.notify("OPENER_ACCEPTED" if browser_accepted else "OPENER_FAILED")
    expected = State.BROWSER if browser_accepted else State.MANUAL_REQUIRED
    for late in ("CLOSE", "FAULT", "GUI_RETIRED", "TEARDOWN_UNPROVED") * 3:
        result = machine.notify(late)
        assert result.state == expected
        assert result.effects == ()
    with pytest.raises(NativeRefusal, match="presentation_event_order"):
        machine.notify("DOCUMENT_READY")
    assert machine.state == expected
    machine.notify("BROWSER_REQUEST")
    assert machine.notify("OPENER_FAILED").state == expected


@pytest.mark.parametrize("stage", [0, 1, 2, 3, 4])
def test_actual_server_exit_is_terminal_and_retires_only_an_owned_gui(stage):
    machine = NativePresentationSupervisor()
    events = ["SERVER_READY", "START_NATIVE", "POLICY_ADMITTED", "DOCUMENT_READY"]
    for event in events[:stage]:
        machine.notify(event)
    result = machine.notify("SERVER_EXIT")
    assert result.state == State.PRESENTATION_STOPPED
    assert result.effects == ((Effect.RETIRE_GUI,) if stage >= 2 else ())
    for event in ("SERVER_EXIT", "FAULT", "GUI_RETIRED", "DOCUMENT_READY"):
        assert machine.notify(event).effects == ()
        assert machine.state == State.PRESENTATION_STOPPED


def test_ineligible_startup_can_continue_in_browser_or_manual_without_creating_gui():
    machine = NativePresentationSupervisor()
    machine.notify("SERVER_READY")
    assert machine.notify("USE_BROWSER").effects == (Effect.OPEN_BROWSER,)
    assert machine.notify("OPENER_FAILED").state == State.MANUAL_REQUIRED
    assert machine.gui_absent


def test_closed_window_can_open_browser_without_restarting_native():
    machine = native()
    machine.notify("CLOSE")
    machine.notify("GUI_RETIRED")
    assert machine.notify("BROWSER_REQUEST").effects == (Effect.OPEN_BROWSER,)
    assert machine.notify("OPENER_ACCEPTED").state == State.BROWSER


def test_dependency_hold_is_not_bypassed_by_an_ambient_webview_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", object())
    monkeypatch.setenv("ATLAS_NATIVE_WINDOW", "1")
    with pytest.raises(NativeRefusal, match="native_dependency_publication_pending"):
        require_native_release_admission()


@pytest.mark.parametrize("uri", [
    "http://localhost:8479/", "http://127.0.0.1.example.invalid:8479/", "http://127.0.0.1:8480/",
    "https://127.0.0.1:8479/", "http://127.0.0.1@192.0.2.1:8479/", "http://user@127.0.0.1:8479/",
    "http://127.0.0.1%00:8479/", "http://127.0.0.1:8479\\@192.0.2.1/", "http://127.0.0.1:8479/\n",
    "http://127.1:8479/", "http://2130706433:8479/", "http://0x7f000001:8479/",
    "file:///app.html", "data:text/html,hello", "blob:http://127.0.0.1:8479/item", "about:blank",
    "http://127.0.0.1:/", "http://127.0.0.1:0/", "http://[::1%25zone]:8479/",
])
def test_navigation_resource_redirect_authority_refusals(uri):
    origin = NativeOrigin.from_bound_url("http://127.0.0.1:8479/")
    with pytest.raises(NativeRefusal):
        origin.require_request(uri)


@pytest.mark.parametrize("uri", ["http://[::1]:8479/", "http://[0:0:0:0:0:0:0:1]:8479/path?q=x"])
def test_ipv6_origin_is_an_address_tuple_not_bracket_spelling(uri):
    origin = NativeOrigin.from_bound_url("http://[::1]:8479/")
    origin.require_request(uri)
    assert origin.url == "http://[::1]:8479/"


def test_blob_download_requires_both_embedded_origin_and_current_document():
    origin = NativeOrigin.from_bound_url("http://127.0.0.1:8479/")
    origin.require_download("blob:http://127.0.0.1:8479/opaque", document=origin.url)
    with pytest.raises(NativeRefusal):
        origin.require_download("blob:http://127.0.0.1:8480/opaque", document=origin.url)
    with pytest.raises(NativeRefusal):
        origin.require_download("blob:http://127.0.0.1:8479/opaque", document="http://192.0.2.1/")


@pytest.mark.parametrize("marked", [False, True])
def test_native_csp_is_additive_and_never_changes_auth_headers_or_scope(marked):
    scope = {"type": "http", "headers": [NATIVE_HEADER] if marked else []}
    original_headers = [(b"content-security-policy", b"default-src 'none'"), (b"x-existing", b"kept")]
    seen = []

    async def app(received_scope, receive, send):
        assert received_scope is scope
        await send({"type": "http.response.start", "status": 200, "headers": original_headers})
        await send({"type": "http.response.body", "body": b"synthetic"})

    async def send(message):
        seen.append(message)

    asyncio.run(NativeResponsePolicy(app)(scope, None, send))
    expected = original_headers + ([(b"content-security-policy", NATIVE_CSP.encode("ascii"))] if marked else [])
    assert seen[0]["headers"] == expected
    assert original_headers == [(b"content-security-policy", b"default-src 'none'"), (b"x-existing", b"kept")]
    assert scope["headers"] == ([NATIVE_HEADER] if marked else [])


KEY = b"s" * 32  # Synthetic capability only; never a field bootstrap.
SESSION = "a" * 32
PEER = PeerIdentity(101, 202, "S-1-5-5-303-404", 0x2000)


def channel(*, key=KEY, session=SESSION, peer=PEER, sender="child"):
    return PresentationChannel(capability=key, session=session, peer=peer, sender=sender)


def test_ipc_peer_mac_sequence_direction_and_closed_payload_are_all_required():
    producer, consumer = channel(), channel()
    raw = producer.frame("HELLO", {})
    with pytest.raises(NativeRefusal, match="ipc_transport"):
        consumer.receive(raw, observed_peer=replace(PEER, creation_time=203), now=0)
    with pytest.raises(NativeRefusal, match="ipc_mac"):
        channel(key=b"x" * 32).receive(raw, observed_peer=PEER, now=0)
    assert consumer.receive(raw, observed_peer=PEER, now=0) == ("HELLO", {})
    with pytest.raises(NativeRefusal, match="ipc_binding"):
        consumer.receive(raw, observed_peer=PEER, now=0.1)
    with pytest.raises(NativeRefusal, match="ipc_binding"):
        channel(sender="parent").receive(raw, observed_peer=PEER, now=0)
    for kind, payload in [("EVAL", {}), ("HELLO", {"command": "not-a-command-channel"}),
                          ("FAULT", {"reason": "arbitrary private text"}),
                          ("DOWNLOAD_STATE", {"state": "ACTIVE", "path": "private"})]:
        with pytest.raises(NativeRefusal):
            producer.frame(kind, payload)


def test_ipc_rate_limit_uses_injected_monotonic_time_without_a_wall_clock_test():
    producer, consumer = channel(), channel()
    for _ in range(10):
        consumer.receive(producer.frame("HELLO", {}), observed_peer=PEER, now=0)
    raw = producer.frame("HELLO", {})
    with pytest.raises(NativeRefusal, match="ipc_rate"):
        consumer.receive(raw, observed_peer=PEER, now=0.999)
    assert consumer.receive(raw, observed_peer=PEER, now=1.0) == ("HELLO", {})
    with pytest.raises(NativeRefusal, match="ipc_transport"):
        consumer.receive(producer.frame("HELLO", {}), observed_peer=PEER, now=0.9)


@pytest.mark.parametrize("raw", [b"x" * (MAX_FRAME + 1), b"", b"[]", b"{}", b"\xff",
                                 b'{"schema":1,"schema":2}', b'{"value":NaN}'])
def test_ipc_malformed_or_unbounded_input_never_admitted(raw):
    with pytest.raises(NativeRefusal):
        channel().receive(raw, observed_peer=PEER, now=0)


def test_even_an_authenticated_message_cannot_add_rpc_payload_fields():
    value = json.loads(channel().frame("HELLO", {}))
    value["payload"] = {"command": "forbidden"}
    del value["mac"]
    def canonical(item):
        return json.dumps(item, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    value["mac"] = hmac.new(KEY, canonical(value), hashlib.sha256).hexdigest()
    with pytest.raises(NativeRefusal, match="ipc_payload"):
        channel().receive(canonical(value), observed_peer=PEER, now=0)
