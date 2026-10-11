"""Stored, evidence-qualified VLAN carriage over supplied cable identities (``vlan_carriage/2``).

This additive owner does not alter the legacy reachability predicate or rebuild a cable map. Every supplied
cable is stored once, with its member ends. Every supplied VLAN row stores one code string: for each assessed
cable in order, one cable character, then a member, an a-end and a b-end character per member. Each character
indexes a closed owner alphabet (``VERDICT_CODES`` or ``END_CODES``), so the stored size grows with VLAN rows times
assessed cable characters, never with a repeated per-pair record.

Namespace-aware PVST states and explicit trunk allowances are distinct bases; neither is a data-plane observation.
A bundled member reads its PVST state, allowance and mode through its logical port channel, as IOS and NX-OS
report them, and never falls back to its own member allowance. Unknown ends, namespace/identity ambiguity and
malformed evidence never become exclusion. A cable to a host that is not a scanned ``interfaces`` key is an edge
blind spot: counted, never published. The validator admits this closed stored shape; it does not authenticate its
provenance or recompute it from interfaces.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any
import re

from .analyze import _canon_host
from .model import InterfaceData
from .ssot import ABSTENTION_STATES, ANALYSIS_UNAVAILABLE
from .stp_topology import ROLE_EVIDENCE_INTEGRITY_CODES, validate_stp_topology_observation
from .textutils import is_trunk_mode, is_valid_iface, normalize_ifname

SCHEMA = "vlan_carriage/2"
BASIS = "cisco_toolkit.vlan_carriage:compute_vlan_carriage"
RELATIONS = ("forwarding", "stp_blocked", "not_carried")
_PUB = "published"
_CBE = "collected_but_empty"
_UNVERIFIED = "unverified"
_NOT_COLLECTED = next(state for state in ABSTENTION_STATES if state == "not_collected")
# Keep the stored order while reading the shared presence/failure vocabulary from its owner.
STATES = tuple(state for state in ABSTENTION_STATES if state != ANALYSIS_UNAVAILABLE) + (
    _UNVERIFIED, ANALYSIS_UNAVAILABLE)
_HOLD_PRECEDENCE = (ANALYSIS_UNAVAILABLE, _UNVERIFIED, _NOT_COLLECTED)
END_SIGNALS = ("forwarding", "blocked", "allowed", "excluded")
BASES = ("none", "typed_pvst", "stored_trunk_allowance", "member_consensus")
EVIDENCE_SHAPES = ("both_ends", "one_end_only", "no_evidence", "unverified")
SOURCES = ("cable_map", "interfaces", "stp_topology_observations", "vlan_cutover")
#: How a stored cable takes part: ``assessed`` cables carry codes, ``edge`` cables (an end host that is not a
#: scanned interfaces key) are counted blind spots, and ``unreadable`` cables carry one held verdict.
SCOPES = ("assessed", "edge", "unreadable")
LIMITATIONS = (
    "Relations concern the supplied stored cable/member and VLAN-row universe, not every possible cable or VLAN.",
    "PVST port states are observations from separate captures, not simultaneous forwarding or data-plane delivery.",
    "Mutual stored trunk allowance is a configured-carriage model, not observed STP forwarding or traffic.",
    "MST instances have no admitted VLAN mapping here; legacy namespace-free interface STP ranges are never used.",
    "Bundle relations require agreement of every member; no first member represents an incomplete or mixed bundle.",
    "Source pointers and closed-shape validation are not authenticated capture custody or collection completeness.",
    "A bundled member's PVST state, allowance and mode are read from its logical port channel; a member row beside "
    "a channel row, or a missing or ambiguous channel record, is held rather than replaced by member allowance.",
    "A cable whose end host is not a scanned interfaces device is an edge blind spot: it is counted and never "
    "published, and no VLAN's state is derived from it.",
)
_ISSUES = {
    "missing_source": "not collected: a required source is absent",
    "malformed_source": "unverified: a supplied source has an unsupported shape",
    "failed_source": "analysis unavailable: the caller records a failed input source",
    "failed_sources_invalid": "unverified: failed-source declarations are outside the closed input contract",
    "vlan_unreadable": "unverified: this VLAN row has no integer VLAN identity in 1..4094",
    "vlan_duplicate": "unverified: more than one supplied VLAN row names this VLAN",
    "cable_unreadable": "unverified: this cable has no complete readable endpoint/member identity",
    "edge_uncollected": "not collected: a cable end host is not a scanned interfaces device; this edge is a blind spot",
    "member_unreadable": "unverified: this cable member has no complete readable endpoint identity",
    "member_duplicate": "unverified: a physical member is repeated within or across supplied cables",
    "host_collision": "unverified: scanned host names collide under the cable owner's canonical join",
    "port_collision": "unverified: interface names collide after normalization",
    "missing_interface": "not collected: this exact cable end has no stored interface record",
    "interface_unreadable": "unverified: this interface record or a relevant field is malformed",
    "endpoint_mismatch": "unverified: a stored neighbor identity contradicts this cable member",
    "range_unreadable": "unverified: a trunk VLAN expression is malformed or outside 1..4094",
    "trunk_mode_missing": "not collected: stored allowance has no explicit trunk-mode observation",
    "trunk_mode_conflict": "unverified: stored VLAN allowance conflicts with a non-trunk interface mode",
    "stp_unreadable": "unverified: the typed STP observation is malformed or its role census is incomplete",
    "stp_failed": "analysis unavailable: the typed STP state capture failed",
    "mst_unmapped": "unverified: an MST observation cannot establish VLAN carriage without an admitted mapping",
    "role_ambiguous": "unverified: STP roles do not identify one normalized PVST port/VLAN observation",
    "role_unstable": "unverified: this PVST role/state does not establish stable forwarding or blocking",
    "evidence_conflict": "unverified: this PVST state and explicit trunk exclusion disagree",
    "no_evidence": "not collected: this interface has no admitted PVST state or explicit trunk allowance",
    "one_end_only": "not collected: carriage evidence is available at only one cable end",
    "both_ends_missing": "not collected: neither cable end has admitted carriage evidence",
    "mixed_basis": "unverified: these end observations do not establish a common carriage basis",
    "lag_ambiguous": "unverified: port-channel members do not identify one consistent local bundle at each end",
    "bundle_orientation": "unverified: no stored neighbor observation binds this folded member to its stated host/port orientation",
    "mixed_members": "unverified: cable members disagree or include an unassessed member",
    "empty_members": "not collected: this cable has no member observations",
    "empty_universe": "collected but empty: no pairs exist in the supplied VLAN-row/cable universe",
}
_STATE_PREFIX = {"not collected:": _NOT_COLLECTED, "unverified:": _UNVERIFIED,
                 "analysis unavailable:": ANALYSIS_UNAVAILABLE, "collected but empty:": _CBE}


def _code_state(code: str) -> str:
    """The state a reason code names: its ``_ISSUES`` prefix, as the stored reasons always read."""
    text = _ISSUES[code]
    return next(state for prefix, state in _STATE_PREFIX.items() if text.startswith(prefix))


_SIGNAL_BASIS = {"forwarding": "typed_pvst", "blocked": "typed_pvst",
                 "allowed": "stored_trunk_allowance", "excluded": "stored_trunk_allowance"}
_PUBLISHED_VERDICTS = (("forwarding", "typed_pvst"), ("forwarding", "stored_trunk_allowance"),
                       ("forwarding", "member_consensus"), ("stp_blocked", "typed_pvst"),
                       ("stp_blocked", "member_consensus"), ("not_carried", "stored_trunk_allowance"),
                       ("not_carried", "member_consensus"))
#: Held end codes. Those a VLAN decides (the rest are fixed per stored end and travel in its ``hold``).
_END_HOLDS = ("failed_source", "malformed_source", "member_unreadable", "missing_interface", "host_collision",
              "port_collision", "interface_unreadable", "endpoint_mismatch", "range_unreadable", "stp_unreadable",
              "stp_failed", "mst_unmapped", "bundle_orientation", "role_ambiguous", "role_unstable",
              "evidence_conflict", "trunk_mode_missing", "trunk_mode_conflict", "no_evidence")
_VLAN_END_HOLDS = ("role_ambiguous", "role_unstable", "evidence_conflict", "trunk_mode_missing",
                   "trunk_mode_conflict", "no_evidence")
#: A stored end's own ``hold``: every held code except the ones only a VLAN decides. ``no_evidence`` is both: a
#: bundled member whose channel has no interface record holds it for every VLAN.
_STATIC_END_HOLDS = tuple(code for code in _END_HOLDS if code not in _VLAN_END_HOLDS[:5])
_MEMBER_OVERRIDES = ("member_unreadable", "member_duplicate")
_CABLE_HOLDS = {"assessed": ("lag_ambiguous",), "edge": ("edge_uncollected",), "unreadable": ("cable_unreadable",)}
_VERDICT_HOLDS = ("one_end_only", "both_ends_missing", "mixed_basis", "mixed_members", "lag_ambiguous") + \
    _MEMBER_OVERRIDES + tuple(code for code in _END_HOLDS
                              if _code_state(code) != _NOT_COLLECTED and code not in _MEMBER_OVERRIDES)
#: The closed alphabets every stored code character indexes, in this exact order (stored as ``code_tables``).
VERDICT_CODES = tuple(f"{relation}:{basis}" for relation, basis in _PUBLISHED_VERDICTS) + _VERDICT_HOLDS
END_CODES = END_SIGNALS + _END_HOLDS
CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
#: The reason codes a VLAN row's own ``hold`` may name: an unreadable or repeated selector, or a source hold.
ROW_HOLDS = ("failed_source", "failed_sources_invalid", "malformed_source", "missing_source",
             "vlan_unreadable", "vlan_duplicate")
_SOURCE_HOLDS = ("failed_source", "failed_sources_invalid", "malformed_source", "missing_source")
if len(VERDICT_CODES) > len(CODE_ALPHABET) or len(END_CODES) > len(CODE_ALPHABET):
    raise ValueError("carriage code tables exceed the stored alphabet")


def _verdict_decoded(token: str) -> dict:
    if ":" in token:
        relation, basis = token.split(":")
        return {"state": _PUB, "relation": relation, "basis": basis, "evidence_shape": "both_ends", "reason": None}
    shape = {"one_end_only": "one_end_only", "both_ends_missing": "no_evidence",
             "mixed_basis": "both_ends"}.get(token, "unverified")
    return {"state": _code_state(token), "relation": None, "basis": "none", "evidence_shape": shape,
            "reason": _ISSUES[token]}


def _end_decoded(token: str) -> dict:
    if token in _SIGNAL_BASIS:
        return {"state": _PUB, "signal": token, "basis": _SIGNAL_BASIS[token], "reason": None}
    return {"state": _code_state(token), "signal": None, "basis": "none", "reason": _ISSUES[token]}


_V = {token: CODE_ALPHABET[i] for i, token in enumerate(VERDICT_CODES)}
_E = {token: CODE_ALPHABET[i] for i, token in enumerate(END_CODES)}
_V_TOKEN = {char: token for token, char in _V.items()}
_E_TOKEN = {char: token for token, char in _E.items()}
_V_DECODED = {char: _verdict_decoded(token) for char, token in _V_TOKEN.items()}
_E_DECODED = {char: _end_decoded(token) for char, token in _E_TOKEN.items()}
_V_STATE = {char: decoded["state"] for char, decoded in _V_DECODED.items()}
_V_RELATION = {char: decoded["relation"] for char, decoded in _V_DECODED.items()}
_E_STATE = {char: decoded["state"] for char, decoded in _E_DECODED.items()}
_CONSENSUS = {relation: _V[f"{relation}:member_consensus"] for relation in RELATIONS}


def _member_token(a: str, b: str) -> str:
    """One member's verdict from its two end codes: a failed or unverified end keeps its own reason."""
    states = (_code_state(a) if a not in _SIGNAL_BASIS else _PUB, _code_state(b) if b not in _SIGNAL_BASIS else _PUB)
    for state in (ANALYSIS_UNAVAILABLE, _UNVERIFIED):
        for token, end_state in zip((a, b), states):
            if end_state == state:
                return token
    known = states.count(_PUB)
    if known < 2:
        return "one_end_only" if known else "both_ends_missing"
    signals = {a, b}
    if "blocked" in signals:
        return "stp_blocked:typed_pvst"
    if "excluded" in signals:
        return "not_carried:stored_trunk_allowance"
    if signals == {"forwarding"}:
        return "forwarding:typed_pvst"
    if signals == {"allowed"}:
        return "forwarding:stored_trunk_allowance"
    return "mixed_basis"


_MEMBER_CHAR = {(_E[a], _E[b]): _V[_member_token(a, b)] for a in END_CODES for b in END_CODES}


def decode_verdict(char: str) -> dict:
    """``{state, relation, basis, evidence_shape, reason}`` of one stored cable or member character (a fresh dict)."""
    return dict(_V_DECODED[char])


def decode_end(char: str) -> dict:
    """``{state, signal, basis, reason}`` of one stored end character (a fresh dict)."""
    return dict(_E_DECODED[char])


def carriage_end_char(token: str) -> str:
    """The stored character of one ``END_CODES`` token."""
    return _E[token]


_RANGE_SEPARATOR = r"(?: *, *| +)"
_RANGE = re.compile(r"[0-9]+(?:-[0-9]+)?(?:" + _RANGE_SEPARATOR + r"[0-9]+(?:-[0-9]+)?)*\Z")
#: Every interface field the carriage owner reads. ``trunk_allowed_none`` is the trunk table's literal 'none'
#: allowed list (an explicit exclusion); it and a non-blank ``trunk_allowed_vlans`` together are unreadable.
CARRIAGE_INTERFACE_FIELDS = ("port", "cdp_neighbor", "neighbor_port", "switchport_mode", "trunk_allowed_vlans",
                             "trunk_native_vlan", "trunk_allowed_none", "port_channel")
_INTERFACE_FIELDS = CARRIAGE_INTERFACE_FIELDS


def _pointer(*parts: object) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _text(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def carriage_host_identity(value: Any) -> str:
    """The existing cable-owner host join, without new identity or custody inference."""
    return _canon_host(value)


def carriage_port_identity(value: str) -> str:
    """The existing interface normalization, not the strict port-admission predicate."""
    return normalize_ifname(value)


@lru_cache(maxsize=65536)
def _admitted_port(value: str) -> str | None:
    # A pure function of the text: interface names repeat across every end, VLAN and role row, so the
    # normalization is computed once per distinct name (bounded), never once per pair.
    return carriage_port_identity(value) if _text(value) and is_valid_iface(value) else None


def _port(value: Any) -> str | None:
    return _admitted_port(value) if type(value) is str else None


def _physical_identity(a: Any, ap: Any, b: Any, bp: Any) -> tuple | None:
    """Count every readable pair witness, even inside an otherwise refused record.

    Producer and stored validator use the same census. Unsupported extra keys or an
    inconsistent outer cable cannot make its readable member cease to conflict with another.
    """
    if not _text(a) or not _text(b) or _port(ap) is None or _port(bp) is None:
        return None
    return tuple(sorted(((a, _port(ap)), (b, _port(bp)))))


def _channel(value: Any) -> str | None:
    """The interface field's actual PoN/Port-channelN forms, never a physical port (leading zeros removed)."""
    return _admitted_channel(value) if type(value) is str else None


@lru_cache(maxsize=65536)
def _admitted_channel(value: str) -> str | None:
    normalized = _port(value)
    match = re.fullmatch(r"Po([0-9]+)", normalized or "", flags=re.IGNORECASE)
    if match is None:
        return None
    number = match[1].lstrip("0")
    return "Po" + number if number else None


def carriage_join_interface(value: Any) -> str | None:
    """The PVST join key: a port channel as ``PoN`` (``_channel`` on both sides), any other port by its
    existing normalization. ``None`` for an unreadable name."""
    return _channel(value) or _port(value)


def carriage_role_index(observation: Any) -> dict:
    """Index one admitted observation's role rows once by ``(namespace, instance, joined interface)``."""
    index: dict = defaultdict(list)
    for i, row in enumerate(observation["roles"]):
        key = carriage_join_interface(row["interface"])
        if key is not None:
            index[(row["namespace"], int(row["instance"]), key)].append(i)
    return {key: tuple(value) for key, value in index.items()}


def carriage_role_rows(observation: Any, stp_interface: Any, vid: Any, *, index: Any = None) -> list:
    """The one owner join from a stored end's ``stp_interface`` and a VLAN to the PVST role rows it names.

    Producer and projection share it, so a typed role ref is never stored per VLAN. Returns ``[(i, row)]``
    over the admitted observation's ``roles`` (an empty list for an unreadable key or selector).
    """
    key = carriage_join_interface(stp_interface)
    if key is None or type(vid) is not int:
        return []
    found = (carriage_role_index(observation) if index is None else index).get(("pvst_vlan", vid, key), ())
    return [(i, observation["roles"][i]) for i in found]


def _interface_values(raw: Any) -> dict[str, str] | None:
    """Admit every supplied record's relevant field types, joined or not."""
    if type(raw) is dict:
        values = {name: raw.get(name, "") for name in CARRIAGE_INTERFACE_FIELDS}
    elif isinstance(raw, InterfaceData):
        values = {name: getattr(raw, name) for name in CARRIAGE_INTERFACE_FIELDS}
    else:
        return None
    return values if all(type(value) is str for value in values.values()) else None


def vlan_row_identity(row: Any) -> int | None:
    """The carriage owner's exact supplied-row selector; no generic numeric coercion.

    Projection may use this same admission to join stored rows, without recomputing
    carriage. Digit aliases retain their original row position but join by integer VLAN.
    """
    value = row.get("vlan") if type(row) is dict else None
    if type(value) is int:
        return value if 1 <= value <= 4094 else None
    if type(value) is str and re.fullmatch(r"[0-9]{1,16}", value):
        number = int(value)
        return number if 1 <= number <= 4094 else None
    return None


def _ranges(value: str) -> tuple[bool, str, tuple]:
    """``(admitted, kind, ranges)`` of one allowed-VLAN expression, without expanding a range.

    Blank/--/n/a are missing (``blank``); a literal 'none' is an explicit exclusion. Invalid tokens never
    disappear beside valid tokens as in a permissive range reader.
    """
    text = value.strip().lower()
    if text in ("", "--", "n/a"):
        return True, "blank", ()
    if text in ("all", "none"):
        return True, text, ()
    if not _RANGE.fullmatch(text):
        return False, "blank", ()
    spans = []
    for token in re.split(_RANGE_SEPARATOR, text):
        pair = token.split("-")
        if any(len(number) > 4 for number in pair):
            return False, "blank", ()
        lo, hi = int(pair[0]), int(pair[-1])
        if not 1 <= lo <= hi <= 4094:
            return False, "blank", ()
        spans.append((lo, hi))
    return True, "ranges", tuple(spans)


def _native(value: str) -> tuple[bool, int | None]:
    text = value.strip().lower()
    if text in ("", "--", "n/a"):
        return True, None
    if not re.fullmatch(r"[0-9]{1,4}", text) or not 1 <= int(text) <= 4094:
        return False, None
    return True, int(text)


def _allowance(values: dict[str, str]) -> tuple[list[str], str, tuple, int | None]:
    """``(unreadable fields, kind, ranges, native)`` of one record's allowance evidence.

    A native VLAN only witnesses an explicit-exclusion conflict; it never makes a VLAN allowed. The literal
    'none' and a non-blank allowed list are two answers to one question, so both together are unreadable.
    """
    bad = []
    ok, kind, spans = _ranges(values["trunk_allowed_vlans"])
    if not ok:
        bad.append("trunk_allowed_vlans")
    literal = values["trunk_allowed_none"].strip().lower()
    if literal not in ("", "none"):
        bad.append("trunk_allowed_none")
    elif literal and values["trunk_allowed_vlans"].strip():
        bad.extend(field for field in ("trunk_allowed_vlans", "trunk_allowed_none") if field not in bad)
    elif literal:
        kind, spans = "none", ()
    native_ok, native = _native(values["trunk_native_vlan"])
    if not native_ok:
        bad.append("trunk_native_vlan")
    return bad, kind, spans, native


def _allowed(kind: str, spans: tuple, vid: int) -> bool | None:
    if kind == "blank":
        return None
    if kind in ("all", "none"):
        return kind == "all"
    return any(lo <= vid <= hi for lo, hi in spans)


def _issue(code: str, pointer: str) -> dict:
    return {"state": _code_state(code), "reason": _ISSUES[code], "pointer": pointer}


def carriage_observation_admission(observation: Any) -> tuple[str, str | None, Any]:
    """Admit one declared stored STP record under the carriage owner's existing rules.

    This is eligibility, not carriage computation or election. The second result is
    the existing reason code, and the third is the same admitted record (never a copy).
    Absent host/section and declared source failure remain the caller's environment.
    A role-evidence integrity finding (``stp_topology.ROLE_EVIDENCE_INTEGRITY_CODES``) holds the record.
    """
    try:
        valid, _ = validate_stp_topology_observation(observation)
    except (TypeError, ValueError, AttributeError, RecursionError, OverflowError):
        valid = False
    if not valid:
        return "unverified", "stp_unreadable", None
    if observation["state_capture_state"] == "error":
        return "analysis_unavailable", "stp_failed", observation
    if observation["state_capture_state"] != "usable":
        return "not_collected", None, observation
    if (observation["role_candidate_count"] != observation["role_parsed_count"]
            or set(observation["finding_codes"]) & set(ROLE_EVIDENCE_INTEGRITY_CODES)):
        return "unverified", "stp_unreadable", observation
    if any(row["namespace"] == "mst_instance" for row in observation["roots"] + observation["roles"]):
        return "unverified", "mst_unmapped", observation
    return "published", None, observation


def carriage_role_compatible(role: dict) -> bool:
    return ((role["state"] == "forwarding" and role["role"] in ("root", "designated", "boundary"))
            or (role["state"] == "blocked" and role["role"] in ("alternate", "backup", "boundary")))


class _Inputs:
    def __init__(self, interfaces: Any, observations: Any, failed: set[str]):
        self.interfaces, self.observations, self.failed = interfaces, observations, failed
        self.hosts: dict[str, list[str]] = defaultdict(list)
        self.ports: dict[str, dict[str, list[str]]] = {}
        self.channels: dict[str, dict[str, list[str]]] = {}
        self.stp: dict[str, tuple[str, str | None, Any]] = {}
        self.indexes: dict[str, dict] = {}
        for host, records in (interfaces.items() if type(interfaces) is dict else ()):
            if not _text(host):
                continue
            self.hosts[carriage_host_identity(host)].append(host)
            ports: dict[str, list[str]] = defaultdict(list)
            channels: dict[str, list[str]] = defaultdict(list)
            for key in (records if type(records) is dict else ()):
                normalized = _port(key)
                if normalized:
                    ports[normalized].append(key)
                channel = _channel(key)
                if channel:
                    channels[channel].append(key)
            self.ports[host] = ports
            self.channels[host] = channels

    def observation(self, host: str) -> tuple[str, str | None, Any]:
        if host in self.stp:
            return self.stp[host]
        if "stp_topology_observations" in self.failed:
            result = ("analysis_unavailable", "failed_source", None)
        elif self.observations is None or (type(self.observations) is dict and host not in self.observations):
            result = ("not_collected", None, None)
        elif type(self.observations) is not dict:
            result = ("unverified", "stp_unreadable", None)
        else:
            result = carriage_observation_admission(self.observations[host])
        self.stp[host] = result
        return result

    def role_index(self, host: str, observation: Any) -> dict:
        if host not in self.indexes:
            self.indexes[host] = carriage_role_index(observation)
        return self.indexes[host]

    def end(self, host: Any, port: Any, other_host: Any, other_port: Any, *,
            unscanned: bool = False) -> tuple[dict, Any]:
        """One stored end (fixed for every VLAN) and its private per-VLAN evaluator (``None`` when held)."""
        out = {"host": host if _text(host) else None, "port": port if _text(port) else None,
               "interface_pointer": None, "stp_interface": None, "stp_pointer": None,
               "allowance_pointer": None, "refs": [], "hold": None}

        def hold(code: str) -> tuple[dict, Any]:
            out["hold"] = code
            return out, None

        if "interfaces" in self.failed:
            return hold("failed_source")
        if unscanned:
            # An edge's far end: kept as stored text (an AP 'Gi0' or a phone 'Port 1' need not be an interface name).
            return hold("missing_interface")
        if not _text(host) or _port(port) is None:
            return hold("member_unreadable")
        if type(self.interfaces) is not dict:
            return hold("missing_interface" if self.interfaces is None else "malformed_source")
        if len(self.hosts.get(carriage_host_identity(host), [])) > 1:
            return hold("host_collision")
        if host not in self.interfaces:
            return hold("missing_interface")
        records = self.interfaces[host]
        if type(records) is not dict:
            return hold("interface_unreadable")
        keys = self.ports.get(host, {}).get(_port(port), [])
        if len(keys) > 1:
            return hold("port_collision")
        if not keys:
            return hold("missing_interface")
        pointer = _pointer("interfaces", host, keys[0])
        out["interface_pointer"] = pointer
        out["refs"] = [pointer]
        values = _interface_values(records[keys[0]])
        if values is None:
            return hold("interface_unreadable")
        if values["port"] and _port(values["port"]) != _port(port):
            return hold("endpoint_mismatch")
        if values["cdp_neighbor"] and carriage_host_identity(values["cdp_neighbor"]) != carriage_host_identity(other_host):
            return hold("endpoint_mismatch")
        if values["neighbor_port"] and _port(values["neighbor_port"]) != _port(other_port):
            return hold("endpoint_mismatch")
        channel = _channel(values["port_channel"]) if values["port_channel"].strip() else None
        if values["port_channel"].strip() and channel is None:
            return hold("interface_unreadable")
        source, source_pointer, member_join = values, pointer, None
        if channel is not None and channel != _channel(port):
            # A bundled member supplies identity only: PVST rows, allowance and mode are the channel's.
            channel_keys = self.channels.get(host, {}).get(channel, [])
            if len(channel_keys) > 1:
                return hold("port_collision")
            if not channel_keys:
                return hold("no_evidence")
            source_pointer = _pointer("interfaces", host, channel_keys[0])
            out["refs"].append(source_pointer)
            source = _interface_values(records[channel_keys[0]])
            if source is None or (source["port"].strip() and _channel(source["port"]) != channel):
                return hold("interface_unreadable")
            member_join = _port(port)
            out["stp_interface"] = channel
        else:
            out["stp_interface"] = port
        out["allowance_pointer"] = source_pointer
        bad, kind, spans, native = _allowance(source)
        if bad:
            out["refs"].extend(source_pointer + "/" + field for field in bad)
            return hold("range_unreadable")
        state, why, observation = self.observation(host)
        if state in ("unverified", "analysis_unavailable"):
            if observation is not None:
                out["refs"].append(_pointer("stp_topology_observations", host))
            return hold(why or "stp_unreadable")
        if observation is not None:
            # The observation is cited only as the basis or as the witness that it holds no row.
            out["stp_pointer"] = _pointer("stp_topology_observations", host)
        mode = source["switchport_mode"].strip().casefold()
        mode_char = None if is_trunk_mode(mode) else _E["trunk_mode_missing" if not mode else "trunk_mode_conflict"]
        index = self.role_index(host, observation) if state == "published" else None
        roles = observation["roles"] if index is not None else None
        return out, (index, roles, carriage_join_interface(out["stp_interface"]), member_join, kind, spans,
                     native, mode_char)

    def bundle(self, ends: dict, members: list) -> bool:
        """Only unique, consistently named local port channels admit a bundled aggregate."""
        for side in ("a", "b"):
            channels = set()
            host = ends[side]
            records = self.interfaces.get(host) if type(self.interfaces) is dict else None
            if type(records) is not dict:
                return False
            for member in members:
                if type(member) is not dict or set(member) != {"a_port", "b_port"}:
                    return False
                keys = self.ports.get(host, {}).get(_port(member[side + "_port"]), [])
                if len(keys) != 1:
                    return False
                values = _interface_values(records[keys[0]])
                channel = _channel(values["port_channel"]) if values is not None else None
                if channel is None:
                    return False
                channels.add(channel)
            if len(channels) != 1:
                return False
        return True

    def member_orientation(self, ends: dict, member: Any) -> dict[str, list[str]]:
        """Witness the stored orientation; never swap a legacy folded member to guess a fit.

        One complete neighbor observation is enough; a missing reciprocal observation is
        not invented. The end reader separately refuses any contradictory nonblank side.
        """
        witnessed: dict[str, list[str]] = {}
        if type(member) is not dict:
            return witnessed
        for side, peer in (("a", "b"), ("b", "a")):
            host, other = ends[side], ends[peer]
            port, other_port = member.get(side + "_port"), member.get(peer + "_port")
            if not _text(host) or not _text(other) or _port(port) is None or _port(other_port) is None:
                continue
            records = self.interfaces.get(host) if type(self.interfaces) is dict else None
            keys = self.ports.get(host, {}).get(_port(port), [])
            if type(records) is not dict or len(keys) != 1 or len(self.hosts.get(carriage_host_identity(other), [])) > 1:
                continue
            values = _interface_values(records[keys[0]])
            if (values is not None and _text(values["cdp_neighbor"]) and _port(values["neighbor_port"]) is not None
                    and carriage_host_identity(values["cdp_neighbor"]) == carriage_host_identity(other)
                    and _port(values["neighbor_port"]) == _port(other_port)):
                witnessed[side] = [_pointer("interfaces", host, keys[0], field)
                                   for field in ("cdp_neighbor", "neighbor_port")]
        return witnessed


def _end_char(evaluator: tuple, vid: int) -> str:
    """One unheld end's code for one VLAN; the bundled channel and member rows are joined, never mixed."""
    index, roles, join, member_join, kind, spans, native, mode_char = evaluator
    allowed = _allowed(kind, spans, vid)
    if native == vid and allowed is False:
        return _E["evidence_conflict"]
    if index is not None:
        hits = index.get(("pvst_vlan", vid, join), ())
        if member_join is not None and hits and index.get(("pvst_vlan", vid, member_join)):
            return _E["role_ambiguous"]
        if len(hits) > 1:
            return _E["role_ambiguous"]
        if hits:
            role = roles[hits[0]]
            if not carriage_role_compatible(role):
                return _E["role_unstable"]
            if role["state"] == "forwarding" and allowed is False:
                return _E["evidence_conflict"]
            return _E[role["state"]]
    if allowed is not None:
        return mode_char or _E["allowed" if allowed else "excluded"]
    return _E["no_evidence"]


def _cable_identity(raw: Any) -> tuple[dict, list, bool]:
    ends = {key: raw.get(key) if type(raw) is dict else None for key in ("a", "a_port", "b", "b_port", "is_pc")}
    good = (_text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
            and _port(ends["a_port"]) is not None and _port(ends["b_port"]) is not None
            and type(ends["is_pc"]) is bool)
    members = raw.get("members") if type(raw) is dict else None
    clean = {k: v if (type(v) is bool if k == "is_pc" else _text(v)) else None for k, v in ends.items()}
    if type(members) is not list:
        return clean, [], False
    good = good and bool(members) and (ends["is_pc"] or len(members) == 1)
    if members and type(members[0]) is dict:
        good = good and all(_port(members[0].get(k)) == _port(ends[k]) for k in ("a_port", "b_port"))
    else:
        good = False
    return clean, members, bool(good)


def _strongest(*codes: str | None) -> str | None:
    """The held reason code whose state ranks first under the hold precedence (earlier argument on a tie)."""
    present = [code for code in codes if code is not None]
    for state in _HOLD_PRECEDENCE:
        for code in present:
            if _code_state(code) == state:
                return code
    return present[0] if present else None


def carriage_cable_binding(raw: Any, interfaces: Any) -> tuple[dict, list, str]:
    """The owner's stored identity and scope join, without evaluating VLAN carriage.

    Even edge and unreadable rows must still bind their known endpoint/member identity and scanned-host scope.
    Unsupported identity values remain null; this does not authenticate or repair a supplied cable.
    """
    ends, members, good = _cable_identity(raw)
    edge = (type(interfaces) is dict and _text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
            and (ends["a"] not in interfaces or ends["b"] not in interfaces))
    if edge:
        edge = (type(ends["is_pc"]) is bool and bool(members) and (ends["is_pc"] or len(members) == 1)
                and all(type(member) is dict and set(member) == {"a_port", "b_port"}
                        and all(_port(member[side + "_port"]) is not None if ends[side] in interfaces
                                else _text(member[side + "_port"]) for side in ("a", "b")) for member in members)
                and all(_port(ends[side + "_port"]) == _port(members[0][side + "_port"])
                        if ends[side] in interfaces else ends[side + "_port"] == members[0][side + "_port"]
                        for side in ("a", "b")))
    ports = [{side: member.get(side + "_port") if type(member) is dict and _text(member.get(side + "_port"))
              else None for side in ("a", "b")} for member in members]
    return ends, ports, "edge" if edge else "assessed" if good else "unreadable"


def _first_state(entries: list) -> tuple[str | None, str | None]:
    """``(state, reason)`` of the first held state under the hold precedence, the reason of its first entry."""
    for state in _HOLD_PRECEDENCE:
        for entry_state, reason in entries:
            if entry_state == state:
                return state, reason
    return None, None


def compute_vlan_carriage(cable_map: Any, interfaces: Any, stp_topology_observations: Any,
                          vlan_rows: Any, *, failed_sources: Any = ()) -> dict:
    """Produce a new closed ``vlan_carriage/2`` section without parsing command text or mutating inputs.

    ``vlan_rows`` is the explicit existing vlan_cutover row list, not a discovered/expanded range.
    ``failed_sources`` names only SOURCES; callers retain their own phase receipts. A missing, failed or
    malformed source holds every VLAN row (its codes stay empty). Malformed source rows remain indexed and
    qualify the section even when another individual row has usable evidence.
    """
    issues = []
    failed: set[str] = set()
    if (type(failed_sources) not in (list, tuple) or any(type(s) is not str or s not in SOURCES for s in failed_sources)
            or len(set(failed_sources)) != len(failed_sources)):
        issues.append(_issue("failed_sources_invalid", "/"))
    else:
        failed = set(failed_sources)
        issues.extend(_issue("failed_source", _pointer(s)) for s in sorted(failed))
    cables = cable_map.get("cables") if type(cable_map) is dict else None
    for name, value, expected in (("cable_map", cable_map, dict), ("interfaces", interfaces, dict),
                                  ("stp_topology_observations", stp_topology_observations, dict),
                                  ("vlan_cutover", vlan_rows, list)):
        if value is not None and type(value) is not expected:
            issues.append(_issue("malformed_source", _pointer(name)))
        elif value is None and name != "stp_topology_observations":
            issues.append(_issue("missing_source", _pointer(name)))
    if type(cable_map) is dict and type(cables) is not list:
        issues.append(_issue("malformed_source", "/cable_map/cables"))
    # Every source-level absence, failure or unsupported shape holds every VLAN row: absent is not healthy.
    source_hold = _strongest(*(code for code in _SOURCE_HOLDS
                               if any(issue["reason"] == _ISSUES[code] for issue in issues)))
    flagged: set[tuple[str, str]] = set()
    for host, records in (interfaces.items() if type(interfaces) is dict else ()):
        if not _text(host) or type(records) is not dict:
            issues.append(_issue("malformed_source", _pointer("interfaces", host) if _text(host) else "/interfaces"))
            continue
        for port, record in records.items():
            values = _interface_values(record)
            witness = _pointer("interfaces", host, port) if _text(port) else _pointer("interfaces", host)
            if (_port(port) is None or values is None
                    or (values["port"] and _port(values["port"]) != _port(port))
                    or (values["port_channel"].strip() and _channel(values["port_channel"]) is None)):
                issues.append(_issue("interface_unreadable", witness))
            if values is not None:
                for field in _allowance(values)[0]:
                    issues.append(_issue("range_unreadable", witness + "/" + field if _text(port) else witness))
    for host in (stp_topology_observations if type(stp_topology_observations) is dict else ()):
        if not _text(host):
            issues.append(_issue("malformed_source", "/stp_topology_observations"))
    vlans = [vlan_row_identity(row) for row in vlan_rows] if type(vlan_rows) is list else []
    duplicates = Counter(v for v in vlans if v is not None)
    identities = [_cable_identity(raw) for raw in cables] if type(cables) is list else []
    ctx = _Inputs(interfaces, stp_topology_observations, failed)
    scanned = interfaces if type(interfaces) is dict else None
    scopes = [carriage_cable_binding(raw, interfaces)[2] for raw in cables] if type(cables) is list else []
    member_owners: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for ci, ((ends, members, _good), scope) in enumerate(zip(identities, scopes)):
        if scope == "unreadable":
            issues.append(_issue("cable_unreadable", _pointer("cable_map", "cables", ci)))
        for mi, member in enumerate(members):
            shaped = type(member) is dict and set(member) == {"a_port", "b_port"}
            readable = shaped and (all(_text(member[k]) for k in member) if scope == "edge"
                                   else all(_port(member[k]) for k in member))
            if not readable:
                issues.append(_issue("member_unreadable", _pointer("cable_map", "cables", ci, "members", mi)))
            pair = (_physical_identity(ends["a"], member.get("a_port"), ends["b"], member.get("b_port"))
                    if type(member) is dict else None)
            if pair is not None:
                member_owners[pair].append((ci, mi))
    repeated = {owner for owners in member_owners.values() if len(owners) > 1 for owner in owners}
    for hosts in ctx.hosts.values():
        if len(hosts) > 1:
            issues.extend(_issue("host_collision", _pointer("interfaces", host)) for host in hosts)
    for host in ctx.ports:
        for groups in (ctx.ports[host], ctx.channels[host]):
            for keys in groups.values():
                if len(keys) > 1:
                    for key in keys:
                        if (host, key) not in flagged:
                            flagged.add((host, key))
                            issues.append(_issue("port_collision", _pointer("interfaces", host, key)))
    # Even an unjoined observation is part of the supplied evidence census. It cannot
    # silently disappear merely because no current cable names its host.
    for host in (stp_topology_observations if type(stp_topology_observations) is dict else ()):
        if _text(host):
            status, why, _ = ctx.observation(host)
            if status in ("unverified", "analysis_unavailable"):
                issues.append(_issue(why or "stp_unreadable", _pointer("stp_topology_observations", host)))
    stored_cables, plans = [], []
    for ci, ((ends, members, good), scope) in enumerate(zip(identities, scopes)):
        pointer = _pointer("cable_map", "cables", ci)
        bundle_ok = scope == "assessed" and (not ends["is_pc"] or ctx.bundle(ends, members))
        hold = {"edge": "edge_uncollected", "unreadable": "cable_unreadable"}.get(
            scope, None if bundle_ok else "lag_ambiguous")
        stored_members, member_plans = [], []
        for mi, member in enumerate(members):
            mp = pointer + "/members/" + str(mi)
            ap, bp = (member.get("a_port"), member.get("b_port")) if type(member) is dict else (None, None)
            far = {side: scope == "edge" and ends[side] not in scanned for side in ("a", "b")}
            a, a_eval = ctx.end(ends["a"], ap, ends["b"], bp, unscanned=far["a"])
            b, b_eval = ctx.end(ends["b"], bp, ends["a"], ap, unscanned=far["b"])
            if scope == "assessed" and ends["is_pc"] is True:
                orientation = ctx.member_orientation(ends, member)
                for side, end in (("a", a), ("b", b)):
                    end["refs"].extend(ref for ref in orientation.get(side, []) if ref not in end["refs"])
                    if not orientation and end["hold"] is None:
                        end["hold"] = "bundle_orientation"
                        end["refs"].append(mp)
                if not orientation:
                    a_eval = b_eval = None
            ports_ok = type(member) is dict and set(member) == {"a_port", "b_port"} and all(_port(member[k]) for k in member)
            override = ("member_duplicate" if (ci, mi) in repeated else None if ports_ok else "member_unreadable")
            stored_members.append({"index": mi, "pointer": mp, "a": a, "b": b})
            member_plans.append((_V[override] if override else None,
                                 _E[a["hold"]] if a["hold"] else None, a_eval,
                                 _E[b["hold"]] if b["hold"] else None, b_eval))
        stored_cables.append({"index": ci, "pointer": pointer, "scope": scope, "hold": hold, "ends": dict(ends),
                              "members": stored_members})
        if scope == "assessed":
            plans.append((_V[hold] if hold else None, member_plans))
    issue_entries = [(issue["state"], issue["reason"]) for issue in issues]
    unreadable_entries = [(_code_state("cable_unreadable"), _ISSUES["cable_unreadable"])
                          for scope in scopes if scope == "unreadable"]
    rows, by_state = [], Counter()
    for vi, vid in enumerate(vlans):
        vlan_hold = "vlan_unreadable" if vid is None else "vlan_duplicate" if duplicates[vid] > 1 else None
        row_hold = _strongest(source_hold, vlan_hold)
        chars: list[str] = []
        cable_chars: list[str] = []
        if row_hold is None:
            for cable_hold, member_plans in plans:
                member_chars: list[str] = []
                relations = set()
                published = True
                for override, a_hold, a_eval, b_hold, b_eval in member_plans:
                    a = a_hold or _end_char(a_eval, vid)
                    b = b_hold or _end_char(b_eval, vid)
                    m = override or _MEMBER_CHAR[(a, b)]
                    member_chars += (m, a, b)
                    relations.add(_V_RELATION[m])
                    published = published and _V_STATE[m] == _PUB
                if cable_hold:
                    c = cable_hold
                elif len(member_plans) == 1:
                    c = member_chars[0]
                elif published and len(relations) == 1:
                    c = _CONSENSUS[relations.pop()]
                else:
                    c = _V["mixed_members"]
                chars.append(c)
                chars.extend(member_chars)
                cable_chars.append(c)
        pair_entries = [(_V_STATE[c], _V_DECODED[c]["reason"]) for c in cable_chars]
        by_state.update(state for state, _reason in pair_entries)
        state, reason = _first_state(issue_entries + unreadable_entries + (
            [(_code_state(row_hold), _ISSUES[row_hold])] if row_hold else []) + pair_entries)
        if state is None:
            state, reason = (_PUB, None) if cable_chars else (_CBE, _ISSUES["empty_universe"])
        rows.append({"vlan_index": vi, "vlan": vid, "vlan_pointer": _pointer("vlan_cutover", vi), "hold": row_hold,
                     "state": state, "reason": reason, "codes": "".join(chars)})
    cable_entries = [(_code_state(cable["hold"]), _ISSUES[cable["hold"]]) for cable in stored_cables if cable["hold"]]
    state, reason = _first_state(issue_entries + [(row["state"], row["reason"]) for row in rows] + cable_entries)
    if state is None:
        state, reason = ((_PUB, None) if any(row["state"] == _PUB for row in rows)
                         else (_CBE, _ISSUES["empty_universe"]))
    counted = type(cables) is list
    census = {scope: sum(1 for value in scopes if value == scope) for scope in SCOPES}
    return {"schema": SCHEMA, "state": state, "reason": reason, "basis": BASIS,
            "limitations": list(LIMITATIONS),
            "code_tables": {"verdict": list(VERDICT_CODES), "end": list(END_CODES)},
            "coverage": {"vlan_rows": len(vlans) if type(vlan_rows) is list else None,
                         "cable_rows": len(identities) if counted else None,
                         "assessed_cables": census["assessed"] if counted else None,
                         "edge_cables": census["edge"] if counted else None,
                         "unreadable_cables": census["unreadable"] if counted else None,
                         "requested_pairs": len(vlans) * census["assessed"]
                         if type(vlan_rows) is list and counted else None,
                         "emitted_pairs": sum(by_state.values()),
                         "by_state": {s: by_state.get(s, 0) for s in STATES},
                         "input_census_complete": not issues and all(row["hold"] is None for row in rows),
                         "capture_completeness_claim": False},
            "issues": issues, "cables": stored_cables, "rows": rows}


def carriage_code_offsets(section: dict) -> list[tuple[int, int, int]]:
    """``(cable index, character offset, member count)`` of every assessed cable inside a row's codes."""
    out, offset = [], 0
    for cable in section["cables"]:
        if cable["scope"] == "assessed":
            out.append((cable["index"], offset, len(cable["members"])))
            offset += 1 + 3 * len(cable["members"])
    return out


def carriage_row_cables(section: dict, vlan_index: int, start: int = 0, stop: int | None = None,
                        *, offsets: list | None = None) -> list[tuple[dict, dict, list]]:
    """Decode one stored VLAN row's codes for the assessed cables ``[start:stop]``, never recomputing them.

    Returns ``[(cable, verdict, [(member, member verdict, a end, b end)])]`` of a validated section; a held
    row (empty codes) decodes to no cable.
    """
    codes = section["rows"][vlan_index]["codes"]
    if not codes:
        return []
    window = (carriage_code_offsets(section) if offsets is None else offsets)[start:stop]
    out = []
    for cable_index, offset, count in window:
        cable = section["cables"][cable_index]
        members = []
        for member in cable["members"]:
            position = offset + 1 + 3 * member["index"]
            members.append((member, decode_verdict(codes[position]), decode_end(codes[position + 1]),
                            decode_end(codes[position + 2])))
        out.append((cable, decode_verdict(codes[offset]), members))
    return out


def carriage_row_counts(section: dict, vlan_index: int, offsets: Any = None) -> dict:
    """The relation census of one stored VLAN row's cable characters (a validated, unheld row)."""
    codes = section["rows"][vlan_index]["codes"]
    counts = {relation: 0 for relation in RELATIONS}
    held = 0
    for _cable_index, offset, _count in (carriage_code_offsets(section) if offsets is None else offsets):
        relation = _V_RELATION[codes[offset]]
        if relation is None:
            held += 1
        else:
            counts[relation] += 1
    return {**counts, "held": held}


def validate_vlan_carriage(value: Any) -> tuple[bool, str]:
    """Validate only the closed stored representation/census, never recompute or authenticate it.

    Linear in the stored characters: every row's codes are walked once against per-cable plans derived from the
    stored ends, so a cable, member or end character can never contradict another or its stored end.
    """
    end_keys = {"host", "port", "interface_pointer", "stp_interface", "stp_pointer", "allowance_pointer",
                "refs", "hold"}
    verdict_chars, end_chars = set(_V.values()), set(_E.values())

    def keys(row: Any, names: set[str]) -> bool:
        return type(row) is dict and set(row) == names

    def pointer(raw: Any) -> bool:
        return type(raw) is str and raw.startswith("/") and not re.search(r"~(?![01])", raw)

    def unescape(path: str) -> list[str]:
        return [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]

    def held_reason(state: Any, reason: Any) -> bool:
        if state == _PUB:
            return reason is None
        return (reason in _ISSUES.values()
                and _code_state(next(code for code, text in _ISSUES.items() if text == reason)) == state)

    def end_ok(end: Any) -> bool:
        if (not keys(end, end_keys) or any(end[k] is not None and not _text(end[k]) for k in ("host", "port"))
                or (end["stp_interface"] is not None and not _text(end["stp_interface"]))
                or any(end[k] is not None and not pointer(end[k])
                       for k in ("interface_pointer", "stp_pointer", "allowance_pointer"))
                or type(end["refs"]) is not list or not all(pointer(ref) for ref in end["refs"])
                or (end["hold"] is not None and end["hold"] not in _STATIC_END_HOLDS)):
            return False
        for field in ("interface_pointer", "allowance_pointer"):
            path = end[field]
            if path is not None:
                parts = unescape(path)
                if (len(parts) != 3 or parts[:2] != ["interfaces", end["host"]] or path not in end["refs"]
                        or _port(parts[2]) is None):
                    return False
        if end["interface_pointer"] is not None and (
                _port(end["port"]) is None or _port(unescape(end["interface_pointer"])[2]) != _port(end["port"])):
            return False
        if end["stp_pointer"] is not None and end["stp_pointer"] != _pointer("stp_topology_observations", end["host"]):
            return False
        if end["hold"] is None:
            # An unheld end reached its record, its join key and its allowance record.
            if (end["interface_pointer"] is None or end["allowance_pointer"] is None
                    or carriage_join_interface(end["stp_interface"]) is None):
                return False
            if end["stp_interface"] != end["port"] and (
                    _channel(end["stp_interface"]) is None or end["allowance_pointer"] == end["interface_pointer"]):
                return False
        return True

    try:
        if not keys(value, {"schema", "state", "reason", "basis", "limitations", "code_tables", "coverage",
                            "issues", "cables", "rows"}):
            return False, "section_keys"
        if (value["schema"] != SCHEMA or value["state"] not in STATES or not held_reason(value["state"], value["reason"])
                or value["basis"] != BASIS or value["limitations"] != list(LIMITATIONS)):
            return False, "section_contract"
        if value["code_tables"] != {"verdict": list(VERDICT_CODES), "end": list(END_CODES)}:
            return False, "code_tables"
        cov = value["coverage"]
        if not keys(cov, {"vlan_rows", "cable_rows", "assessed_cables", "edge_cables", "unreadable_cables",
                          "requested_pairs", "emitted_pairs", "by_state", "input_census_complete",
                          "capture_completeness_claim"}):
            return False, "coverage_keys"
        counted = ("vlan_rows", "cable_rows", "assessed_cables", "edge_cables", "unreadable_cables", "requested_pairs")
        if any(cov[k] is not None and (type(cov[k]) is not int or cov[k] < 0) for k in counted):
            return False, "coverage_counts"
        rows, issues, cables = value["rows"], value["issues"], value["cables"]
        if type(rows) is not list or type(issues) is not list or type(cables) is not list:
            return False, "section_lists"
        if any(not keys(i, {"state", "reason", "pointer"}) or i["state"] not in STATES[2:]
               or not held_reason(i["state"], i["reason"]) or not pointer(i["pointer"]) for i in issues):
            return False, "issues"
        scope_counts = Counter()
        if cov["cable_rows"] is None:
            if cables or any(cov[k] is not None for k in ("assessed_cables", "edge_cables", "unreadable_cables")):
                return False, "cable_census"
        elif (len(cables) != cov["cable_rows"]
              or any(type(cov[k]) is not int for k in ("assessed_cables", "edge_cables", "unreadable_cables"))):
            return False, "cable_census"
        plans = []
        seen_members: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
        for index, cable in enumerate(cables):
            if (not keys(cable, {"index", "pointer", "scope", "hold", "ends", "members"})
                    or type(cable["index"]) is not int or cable["index"] != index
                    or cable["pointer"] != _pointer("cable_map", "cables", index) or cable["scope"] not in SCOPES
                    or type(cable["members"]) is not list):
                return False, "cable_contract"
            scope, ends, members = cable["scope"], cable["ends"], cable["members"]
            scope_counts[scope] += 1
            if not keys(ends, {"a", "b", "a_port", "b_port", "is_pc"}) or any(
                    v is not None and (type(v) is not bool if k == "is_pc" else not _text(v)) for k, v in ends.items()):
                return False, "cable_endpoints"
            allowed_holds = _CABLE_HOLDS[scope]
            if (cable["hold"] not in allowed_holds and not (scope == "assessed" and cable["hold"] is None)) or (
                    cable["hold"] == "lag_ambiguous" and ends["is_pc"] is not True):
                return False, "cable_hold"
            for mi, member in enumerate(members):
                if (not keys(member, {"index", "pointer", "a", "b"}) or type(member["index"]) is not int
                        or member["index"] != mi or member["pointer"] != cable["pointer"] + "/members/" + str(mi)
                        or not end_ok(member["a"]) or not end_ok(member["b"])):
                    return False, "member_contract"
                if member["a"]["host"] != ends["a"] or member["b"]["host"] != ends["b"]:
                    return False, "member_host_join"
                pair = _physical_identity(member["a"]["host"], member["a"]["port"],
                                          member["b"]["host"], member["b"]["port"])
                if pair is not None:
                    seen_members[pair].append((index, mi))
            if scope == "edge":
                if not (_text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
                        and type(ends["is_pc"]) is bool and bool(members) and (ends["is_pc"] or len(members) == 1)
                        and all(_text(member[side]["port"]) for member in members for side in ("a", "b"))
                        and all(ends[side + "_port"] == members[0][side]["port"] or (
                            _port(ends[side + "_port"]) is not None
                            and _port(ends[side + "_port"]) == _port(members[0][side]["port"]))
                            for side in ("a", "b"))):
                    return False, "edge_identity"
            if scope == "assessed":
                identity_ok = (bool(members) and _text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
                               and type(ends["is_pc"]) is bool and (ends["is_pc"] or len(members) == 1)
                               and all(_port(ends[side + "_port"]) is not None
                                       and _port(ends[side + "_port"]) == _port(members[0][side]["port"])
                                       for side in ("a", "b")))
                if not identity_ok:
                    return False, "outer_member_identity"
                plans.append(cable)
        if cov["cable_rows"] is not None and any(
                cov[scope + "_cables"] != scope_counts[scope] for scope in SCOPES):
            return False, "cable_census"
        repeated = {owner for owners in seen_members.values() if len(owners) > 1 for owner in owners}
        compiled = []
        for cable in plans:
            member_plans = []
            for member in cable["members"]:
                ends = []
                for side in ("a", "b"):
                    end = member[side]
                    ends.append((_E[end["hold"]] if end["hold"] else None, end["stp_pointer"] is not None))
                witnessed = any(end["interface_pointer"] is not None and all(
                    end["interface_pointer"] + "/" + field in end["refs"] for field in ("cdp_neighbor", "neighbor_port"))
                    for end in (member["a"], member["b"]))
                if cable["ends"]["is_pc"] is True and not witnessed and not (
                        member["a"]["hold"] and member["b"]["hold"]):
                    return False, "bundle_orientation_witness"
                member_plans.append((ends[0], ends[1], (cable["index"], member["index"]) in repeated))
            compiled.append((_V[cable["hold"]] if cable["hold"] else None, member_plans))
        length = sum(1 + 3 * len(members) for _hold, members in compiled)
        if cov["vlan_rows"] is None:
            if rows:
                return False, "row_census"
        elif len(rows) != cov["vlan_rows"]:
            return False, "row_census"
        source_hold = any(issue["reason"] in {_ISSUES[code] for code in _SOURCE_HOLDS} for issue in issues)
        vlan_seen = Counter(row.get("vlan") for row in rows if type(row) is dict and type(row.get("vlan")) is int)
        issue_entries = [(issue["state"], issue["reason"]) for issue in issues]
        unreadable_entries = [(_code_state("cable_unreadable"), _ISSUES["cable_unreadable"])] * scope_counts["unreadable"]
        published_end = {_E[token] for token in END_SIGNALS}
        typed = {_E["forwarding"], _E["blocked"]}
        vlan_end_holds = {_E[token] for token in _VLAN_END_HOLDS}
        overrides = {_V[token] for token in _MEMBER_OVERRIDES}
        by_state, emitted = Counter(), 0
        for vi, row in enumerate(rows):
            if not keys(row, {"vlan_index", "vlan", "vlan_pointer", "hold", "state", "reason", "codes"}):
                return False, "row_keys"
            if (type(row["vlan_index"]) is not int or row["vlan_index"] != vi
                    or row["vlan_pointer"] != _pointer("vlan_cutover", vi)
                    or (row["vlan"] is not None and (type(row["vlan"]) is not int or not 1 <= row["vlan"] <= 4094))
                    or type(row["codes"]) is not str):
                return False, "row_identity"
            hold, codes = row["hold"], row["codes"]
            if hold is not None and hold not in ROW_HOLDS:
                return False, "row_hold"
            expected_vlan_hold = ("vlan_unreadable" if row["vlan"] is None
                                  else "vlan_duplicate" if vlan_seen[row["vlan"]] > 1 else None)
            if hold is None and (source_hold or expected_vlan_hold):
                return False, "row_hold"
            if hold in ("vlan_unreadable", "vlan_duplicate") and hold != expected_vlan_hold:
                return False, "row_hold"
            if hold in _SOURCE_HOLDS and not source_hold:
                return False, "row_hold"
            if hold is not None:
                if codes:
                    return False, "row_codes"
                cable_chars: list[str] = []
            else:
                if len(codes) != length:
                    return False, "row_codes"
                cable_chars = []
                pos = 0
                for cable_hold, member_plans in compiled:
                    c = codes[pos]
                    if c not in verdict_chars:
                        return False, "row_alphabet"
                    pos += 1
                    member_chars = []
                    for (a_hold, a_typed), (b_hold, b_typed), duplicate in member_plans:
                        m, a, b = codes[pos], codes[pos + 1], codes[pos + 2]
                        pos += 3
                        if m not in verdict_chars or a not in end_chars or b not in end_chars:
                            return False, "row_alphabet"
                        for char, end_hold, typed_ok in ((a, a_hold, a_typed), (b, b_hold, b_typed)):
                            if end_hold is not None:
                                if char != end_hold:
                                    return False, "end_hold"
                            elif char not in published_end and char not in vlan_end_holds:
                                return False, "end_code"
                            elif char in typed and not typed_ok:
                                return False, "end_stp_witness"
                        derived = _MEMBER_CHAR[(a, b)]
                        if duplicate:
                            if m != _V["member_duplicate"]:
                                return False, "duplicate_member_admission"
                        elif m != derived and m not in overrides:
                            return False, "member_contradiction"
                        member_chars.append(m)
                    if cable_hold is not None:
                        expected = cable_hold
                    elif len(member_chars) == 1:
                        expected = member_chars[0]
                    elif (all(_V_STATE[m] == _PUB for m in member_chars)
                          and len({_V_RELATION[m] for m in member_chars}) == 1):
                        expected = _CONSENSUS[_V_RELATION[member_chars[0]]]
                    else:
                        expected = _V["mixed_members"]
                    if c != expected:
                        return False, "cable_contradiction"
                    cable_chars.append(c)
            pair_entries = [(_V_STATE[c], _V_DECODED[c]["reason"]) for c in cable_chars]
            by_state.update(state for state, _reason in pair_entries)
            emitted += len(cable_chars)
            state, _reason = _first_state(issue_entries + unreadable_entries + (
                [(_code_state(hold), _ISSUES[hold])] if hold else []) + pair_entries)
            if state is None:
                state = _PUB if cable_chars else _CBE
            if row["state"] != state or not held_reason(row["state"], row["reason"]):
                return False, "row_state"
        requested = (cov["vlan_rows"] * cov["assessed_cables"]
                     if cov["vlan_rows"] is not None and cov["assessed_cables"] is not None else None)
        if (cov["requested_pairs"] != requested or type(cov["emitted_pairs"]) is not int
                or cov["emitted_pairs"] != emitted
                or cov["capture_completeness_claim"] is not False
                or type(cov["input_census_complete"]) is not bool
                or cov["input_census_complete"] != (not issues and all(row["hold"] is None for row in rows))):
            return False, "coverage_census"
        counts = {s: by_state.get(s, 0) for s in STATES}
        if not keys(cov["by_state"], set(STATES)) or any(type(v) is not int for v in cov["by_state"].values()) \
                or cov["by_state"] != counts:
            return False, "state_census"
        cable_entries = [(_code_state(cable["hold"]), _ISSUES[cable["hold"]]) for cable in cables if cable["hold"]]
        expected_state, _reason = _first_state(issue_entries + [(row["state"], row["reason"]) for row in rows]
                                               + cable_entries)
        if expected_state is None:
            expected_state = _PUB if any(row["state"] == _PUB for row in rows) else _CBE
        if value["state"] != expected_state:
            return False, "section_state"
        return True, "ok"
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RecursionError, StopIteration):
        return False, "malformed_value"
