"""Protocol ordering with synthetic peers/time; no Windows or renderer required."""

from dataclasses import replace

import pytest

from portable.native_endpoint import Phase, PresentationEndpoint
from portable.native_ipc import PeerIdentity, PresentationChannel
from portable.native_origin import NativeOrigin, NativeRefusal


PARENT = PeerIdentity(101, 201, "S-1-5-5-301-401", 0x2000)
CHILD = PeerIdentity(102, 202, PARENT.logon_sid, 0x2000)
KEY = b"s" * 32
SESSION = "a" * 32
POLICY = "b" * 64
INSTANCE = "c" * 32


def test_peer_diagnostics_do_not_include_the_logon_sid_or_process_identity():
    assert PARENT.logon_sid not in repr(PARENT)
    assert str(PARENT.creation_time) not in repr(PARENT)
    assert str(PARENT.pid) not in repr(PARENT)


def endpoint(role):
    return PresentationEndpoint(role=role, capability=KEY, session=SESSION, parent=PARENT, child=CHILD,
                                origin=NativeOrigin.from_bound_url("http://127.0.0.1:8479/"),
                                policy_sha256=POLICY, instance=INSTANCE)


def exchange(sender, receiver, kind, payload=None, *, stamp=0):
    peer = CHILD if sender._role == "child" else PARENT
    return receiver.receive(sender.send(kind, payload or {}), observed_peer=peer, now=stamp)


def authenticated():
    parent, child = endpoint("parent"), endpoint("child")
    assert not child.native_imports_admitted
    exchange(child, parent, "HELLO")
    assert not child.native_imports_admitted
    exchange(parent, child, "HELLO_ACK")
    assert child.native_imports_admitted
    assert not parent.native_imports_admitted
    return parent, child


def visible():
    parent, child = authenticated()
    exchange(child, parent, "POLICY_ADMITTED", {"policy_sha256": POLICY})
    exchange(child, parent, "DOCUMENT_READY", {"navigation_id": 1, "instance": INSTANCE})
    exchange(parent, child, "SHOW")
    assert parent.phase == child.phase == Phase.VISIBLE
    return parent, child


@pytest.mark.parametrize("kind,payload", [
    ("POLICY_ADMITTED", {"policy_sha256": POLICY}),
    ("DOCUMENT_READY", {"navigation_id": 1, "instance": INSTANCE}),
    ("CLOSE_REQUEST", {}), ("DOWNLOAD_STATE", {"state": "ACTIVE"}),
])
def test_valid_mac_at_sequence_one_cannot_bypass_the_hello_handshake(kind, payload):
    attacker = PresentationChannel(capability=KEY, session=SESSION, peer=PARENT, sender="child")
    parent = endpoint("parent")
    with pytest.raises(NativeRefusal, match="endpoint_receive_refused"):
        parent.receive(attacker.frame(kind, payload), observed_peer=CHILD, now=0)
    assert parent.phase == Phase.CLOSED
    assert not parent.native_imports_admitted


def test_only_verified_ack_admits_child_native_imports_and_reused_pid_is_refused():
    parent, child = endpoint("parent"), endpoint("child")
    exchange(child, parent, "HELLO")
    raw = parent.send("HELLO_ACK", {})
    with pytest.raises(NativeRefusal):
        child.receive(raw, observed_peer=replace(PARENT, creation_time=999), now=0)
    assert child.phase == Phase.CLOSED and not child.native_imports_admitted


def test_policy_digest_and_actual_server_instance_are_not_selected_by_the_child():
    parent, _child = authenticated()
    producer = PresentationChannel(capability=KEY, session=SESSION, peer=PARENT, sender="child")
    producer.frame("HELLO", {})
    with pytest.raises(NativeRefusal):
        parent.receive(producer.frame("POLICY_ADMITTED", {"policy_sha256": "f" * 64}),
                       observed_peer=CHILD, now=0)
    assert parent.phase == Phase.CLOSED
    parent, child = authenticated()
    exchange(child, parent, "POLICY_ADMITTED", {"policy_sha256": POLICY})
    with pytest.raises(NativeRefusal):
        exchange(child, parent, "DOCUMENT_READY", {"navigation_id": 1, "instance": "f" * 32})
    assert child.phase == Phase.CLOSED


def test_show_requires_policy_then_document_and_cannot_be_repeated():
    parent, child = authenticated()
    with pytest.raises(NativeRefusal):
        parent.send("SHOW", {})
    assert parent.phase == Phase.CLOSED
    parent, child = visible()
    with pytest.raises(NativeRefusal):
        parent.send("SHOW", {})
    assert parent.phase == Phase.CLOSED


def test_normal_retirement_cannot_short_circuit_an_active_native_download():
    parent, child = visible()
    exchange(child, parent, "DOWNLOAD_STATE", {"state": "ACTIVE"})
    exchange(child, parent, "CLOSE_REQUEST")
    assert parent.download_active and child.download_active
    with pytest.raises(NativeRefusal):
        parent.send("RETIRE_GUI", {})
    assert parent.phase == Phase.CLOSED and parent.unsettled_download


@pytest.mark.parametrize("terminal", ["PUBLISHED", "INCOMPLETE_SETTLED"])
def test_download_settlement_then_retirement_is_gui_only(terminal):
    parent, child = visible()
    exchange(child, parent, "DOWNLOAD_STATE", {"state": "ACTIVE"})
    exchange(child, parent, "DOWNLOAD_STATE", {"state": terminal})
    exchange(parent, child, "RETIRE_GUI")
    exchange(child, parent, "GUI_STOPPED")
    assert parent.phase == child.phase == Phase.CLOSED
    assert not parent.download_active


def test_presentation_fault_retains_unsettled_state_without_claiming_a_drain():
    parent, child = visible()
    exchange(child, parent, "DOWNLOAD_STATE", {"state": "ACTIVE"})
    exchange(child, parent, "FAULT", {"reason": "process"})
    assert parent.unsettled_download and child.unsettled_download
    exchange(parent, child, "RETIRE_GUI")
    assert parent.unsettled_download and child.unsettled_download
    child.transport_lost()
    parent.transport_lost()
    assert parent.phase == child.phase == Phase.CLOSED
    assert parent.unsettled_download and child.unsettled_download


def test_independently_sequenced_fault_burst_coalesces_through_graceful_retirement():
    parent, child = visible()
    exchange(child, parent, "DOWNLOAD_STATE", {"state": "ACTIVE"})
    exchange(child, parent, "FAULT", {"reason": "process"})
    exchange(child, parent, "FAULT", {"reason": "ipc"})
    assert parent.phase == child.phase == Phase.FAULT
    assert parent.unsettled_download and child.unsettled_download
    exchange(parent, child, "RETIRE_GUI")
    exchange(child, parent, "FAULT", {"reason": "process"})
    assert parent.phase == child.phase == Phase.RETIRING
    assert parent.unsettled_download and child.unsettled_download
    exchange(child, parent, "GUI_STOPPED")
    assert parent.phase == child.phase == Phase.CLOSED
    assert parent.unsettled_download and child.unsettled_download
