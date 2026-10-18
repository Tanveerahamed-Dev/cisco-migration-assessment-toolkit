"""Bounded presentation message codec; Windows transport must supply verified peers.

MAC possession is necessary, not OS process identity. This codec cannot admit a
named pipe by itself. No page-callable bridge or general command payload exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re

from portable.native_origin import NativeRefusal


SCHEMA = "atlas.presentation-ipc/1"
MAX_FRAME = 4096
MAX_RATE = 10
_PARENT = {"HELLO_ACK", "SHOW", "RETIRE_GUI"}
_CHILD = {"HELLO", "POLICY_ADMITTED", "DOCUMENT_READY", "CLOSE_REQUEST", "BROWSER_REQUEST",
          "DOWNLOAD_STATE", "FAULT", "GUI_STOPPED"}
_EMPTY = {"HELLO", "HELLO_ACK", "SHOW", "RETIRE_GUI", "CLOSE_REQUEST", "BROWSER_REQUEST", "GUI_STOPPED"}
FAULT_REASONS = frozenset({"startup", "policy", "navigation", "process", "ipc", "profile", "download"})


@dataclass(frozen=True)
class PeerIdentity:
    pid: int
    creation_time: int
    logon_sid: str
    integrity: int

    def __post_init__(self):
        if (type(self.pid) is not int or self.pid <= 0 or type(self.creation_time) is not int
                or self.creation_time <= 0 or type(self.logon_sid) is not str
                or re.fullmatch(r"S-1-5-5-[0-9]+-[0-9]+", self.logon_sid) is None
                or type(self.integrity) is not int or self.integrity != 0x2000):
            raise NativeRefusal("ipc_peer_shape")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise NativeRefusal("ipc_duplicate_key")
        value[key] = item
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("ascii")


def _payload(kind, value):
    if type(value) is not dict:
        raise NativeRefusal("ipc_payload")
    if kind in _EMPTY and value == {}:
        return
    if kind == "POLICY_ADMITTED" and set(value) == {"policy_sha256"}:
        digest = value["policy_sha256"]
        if type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest):
            return
    if kind == "DOCUMENT_READY" and set(value) == {"navigation_id", "instance"}:
        if (type(value["navigation_id"]) is int and 0 < value["navigation_id"] < 2**64
                and type(value["instance"]) is str
                and re.fullmatch(r"[0-9a-f]{32}", value["instance"])):
            return
    if kind == "DOWNLOAD_STATE" and set(value) == {"state"}:
        if type(value["state"]) is str and value["state"] in {"ACTIVE", "PUBLISHED", "INCOMPLETE_SETTLED"}:
            return
    if kind == "FAULT" and set(value) == {"reason"}:
        if type(value["reason"]) is str and value["reason"] in FAULT_REASONS:
            return
    raise NativeRefusal("ipc_payload")


class PresentationChannel:
    """One direction, bound to a held, OS-verified medium-integrity logon peer.

    The transport must verify the live OS pipe peer, held process handle/creation
    identity, logon SID/integrity, and GUI job membership before every receive.
    It passes that observed identity; payloads never choose it. A 32-byte random
    per-session bootstrap capability is independent of all HTTP credentials.
    """

    def __init__(self, *, capability: bytes, session: str, peer: PeerIdentity, sender: str):
        if (type(capability) is not bytes or len(capability) != 32
                or type(session) is not str or re.fullmatch(r"[0-9a-f]{32}", session) is None
                or type(peer) is not PeerIdentity or type(sender) is not str
                or sender not in {"parent", "child"}):
            raise NativeRefusal("ipc_bootstrap")
        self._capability = capability
        self._session = session
        self._peer = peer
        self._types = _PARENT if sender == "parent" else _CHILD
        self._sequence = 0
        self._window = []
        self._last_time = None

    def frame(self, kind: str, payload: dict) -> bytes:
        """Encode the next frame; use a separate instance for each direction/end."""
        if type(kind) is not str or kind not in self._types:
            raise NativeRefusal("ipc_type")
        _payload(kind, payload)
        value = {"schema": SCHEMA, "session": self._session, "sequence": self._sequence + 1,
                 "type": kind, "payload": payload}
        value["mac"] = hmac.new(self._capability, _canonical(value), hashlib.sha256).hexdigest()
        raw = _canonical(value)
        if len(raw) > MAX_FRAME:
            raise NativeRefusal("ipc_size")
        self._sequence += 1
        return raw

    def receive(self, raw: bytes, *, observed_peer: PeerIdentity, now: float) -> tuple[str, dict]:
        if (type(observed_peer) is not PeerIdentity or observed_peer != self._peer
                or type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME
                or type(now) not in {int, float} or not math.isfinite(now) or now < 0
                or self._last_time is not None and now < self._last_time):
            raise NativeRefusal("ipc_transport")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(NativeRefusal("ipc_number")))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise NativeRefusal("ipc_json") from error
        if type(value) is not dict or set(value) != {"schema", "session", "sequence", "type", "payload", "mac"}:
            raise NativeRefusal("ipc_schema")
        if (value["schema"] != SCHEMA or value["session"] != self._session
                or type(value["sequence"]) is not int or value["sequence"] != self._sequence + 1
                or type(value["type"]) is not str or value["type"] not in self._types
                or type(value["mac"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["mac"]) is None):
            raise NativeRefusal("ipc_binding")
        supplied_mac = value.pop("mac")
        _payload(value["type"], value["payload"])
        expected_mac = hmac.new(self._capability, _canonical(value), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_mac, expected_mac):
            raise NativeRefusal("ipc_mac")
        recent = [stamp for stamp in self._window if now - stamp < 1.0]
        if len(recent) >= MAX_RATE:
            raise NativeRefusal("ipc_rate")
        self._window = [*recent, now]
        self._last_time = now
        self._sequence += 1
        return value["type"], value["payload"]
