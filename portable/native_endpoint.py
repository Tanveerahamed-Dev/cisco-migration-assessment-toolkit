"""Stateful endpoint above the bounded codec, below the Windows pipe transport.

No renderer may be imported until the child has received HELLO_ACK from its
verified parent. GUI_STOPPED is a protocol notification, not OS exit evidence.
"""

from __future__ import annotations

from enum import Enum
import re

from portable.native_ipc import PeerIdentity, PresentationChannel
from portable.native_origin import NativeOrigin, NativeRefusal


class Phase(str, Enum):
    NEW = "NEW"
    HELLO = "HELLO"
    AUTHENTICATED = "AUTHENTICATED"
    POLICY = "POLICY"
    DOCUMENT = "DOCUMENT"
    VISIBLE = "VISIBLE"
    RETIRING = "RETIRING"
    FAULT = "FAULT"
    CLOSED = "CLOSED"


class PresentationEndpoint:
    """One serialized endpoint bound to the bootstrap's origin and public marker.

    OS pipe/process/logon/job verification is required by the transport before
    calling this endpoint. MAC/handshake acceptance is not that verification.
    """

    def __init__(self, *, role: str, capability: bytes, session: str,
                 parent: PeerIdentity, child: PeerIdentity, origin: NativeOrigin,
                 policy_sha256: str, instance: str):
        if (type(role) is not str or role not in {"parent", "child"}
                or type(parent) is not PeerIdentity or type(child) is not PeerIdentity
                or parent.pid == child.pid or parent.logon_sid != child.logon_sid
                or type(origin) is not NativeOrigin or type(policy_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", policy_sha256) is None
                or type(instance) is not str or re.fullmatch(r"[0-9a-f]{32}", instance) is None):
            raise NativeRefusal("endpoint_bootstrap")
        peer = child if role == "parent" else parent
        self._send = PresentationChannel(capability=capability, session=session, peer=peer, sender=role)
        self._receive = PresentationChannel(capability=capability, session=session, peer=peer,
                                            sender="child" if role == "parent" else "parent")
        self._role = role
        self._origin = origin
        self._policy_sha256 = policy_sha256
        self._instance = instance
        self.phase = Phase.NEW
        self.download_active = False
        self.unsettled_download = False

    @property
    def origin(self):
        return self._origin

    @property
    def native_imports_admitted(self):
        return self._role == "child" and self.phase in {
            Phase.AUTHENTICATED, Phase.POLICY, Phase.DOCUMENT, Phase.VISIBLE,
        }

    def _step(self, kind, payload):
        if kind == "FAULT" and self.phase in {Phase.FAULT, Phase.RETIRING}:
            return  # keep the first failure and any unsettled download; do not abort retirement
        if kind == "HELLO" and self.phase == Phase.NEW:
            self.phase = Phase.HELLO
            return
        if kind == "HELLO_ACK" and self.phase == Phase.HELLO:
            self.phase = Phase.AUTHENTICATED
            return
        if kind == "POLICY_ADMITTED" and self.phase == Phase.AUTHENTICATED:
            if payload["policy_sha256"] != self._policy_sha256:
                raise NativeRefusal("endpoint_policy_binding")
            self.phase = Phase.POLICY
            return
        if kind == "DOCUMENT_READY" and self.phase == Phase.POLICY:
            if payload["instance"] != self._instance:
                raise NativeRefusal("endpoint_instance_binding")
            self.phase = Phase.DOCUMENT
            return
        if kind == "SHOW" and self.phase == Phase.DOCUMENT:
            self.phase = Phase.VISIBLE
            return
        if kind in {"CLOSE_REQUEST", "BROWSER_REQUEST"} and self.phase == Phase.VISIBLE:
            return  # supervisor owns close intent; no server/work admission authority here
        if kind == "DOWNLOAD_STATE" and self.phase == Phase.VISIBLE:
            state = payload["state"]
            if state == "ACTIVE" and not self.download_active:
                self.download_active = True
                return
            if state in {"PUBLISHED", "INCOMPLETE_SETTLED"} and self.download_active:
                self.download_active = False
                return
            raise NativeRefusal("endpoint_download_order")
        if kind == "FAULT" and self.phase in {
            Phase.AUTHENTICATED, Phase.POLICY, Phase.DOCUMENT, Phase.VISIBLE,
        }:
            self.unsettled_download = self.download_active
            self.phase = Phase.FAULT
            return
        if kind == "RETIRE_GUI" and self.phase in {
            Phase.AUTHENTICATED, Phase.POLICY, Phase.DOCUMENT, Phase.VISIBLE, Phase.FAULT,
        }:
            if self.download_active and self.phase != Phase.FAULT:
                raise NativeRefusal("endpoint_active_download")
            self.phase = Phase.RETIRING
            return
        if kind == "GUI_STOPPED" and self.phase in {Phase.RETIRING, Phase.FAULT}:
            self.phase = Phase.CLOSED
            return
        raise NativeRefusal("endpoint_message_order")

    def send(self, kind, payload):
        if self.phase == Phase.CLOSED:
            raise NativeRefusal("endpoint_closed")
        try:
            raw = self._send.frame(kind, payload)
            self._step(kind, payload)
            return raw
        except (ValueError, TypeError, OverflowError):
            self.unsettled_download = self.download_active
            self.phase = Phase.CLOSED
            raise NativeRefusal("endpoint_send_refused") from None

    def receive(self, raw, *, observed_peer, now):
        if self.phase == Phase.CLOSED:
            raise NativeRefusal("endpoint_closed")
        try:
            kind, payload = self._receive.receive(raw, observed_peer=observed_peer, now=now)
            self._step(kind, payload)
            return kind, payload
        except (ValueError, TypeError, OverflowError):
            self.unsettled_download = self.download_active
            self.phase = Phase.CLOSED
            raise NativeRefusal("endpoint_receive_refused") from None

    def transport_lost(self):
        """Caller must retain INCOMPLETE data and prove GUI retirement outside IPC."""
        self.unsettled_download = self.download_active
        self.phase = Phase.CLOSED
