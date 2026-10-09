"""Stored, evidence-qualified VLAN carriage over supplied cable identities.

This additive owner does not alter the legacy reachability predicate or rebuild a cable map.
It visits only the supplied VLAN-row/cable Cartesian product.  Namespace-aware PVST states
and explicit trunk allowances are distinct bases; neither is a data-plane observation.
Unknown ends, namespace/identity ambiguity and malformed evidence never become exclusion.
The validator admits this closed stored shape; it does not authenticate its provenance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
import re

from .analyze import _canon_host
from .model import InterfaceData
from .stp_topology import validate_stp_topology_observation
from .textutils import is_valid_iface, normalize_ifname

SCHEMA = "vlan_carriage/1"
RELATIONS = ("forwarding", "stp_blocked", "not_carried")
STATES = ("published", "collected_but_empty", "not_collected", "unverified", "analysis_unavailable")
END_SIGNALS = ("forwarding", "blocked", "allowed", "excluded")
BASES = ("none", "typed_pvst", "stored_trunk_allowance", "member_consensus")
EVIDENCE_SHAPES = ("both_ends", "one_end_only", "no_evidence", "unverified")
SOURCES = ("cable_map", "interfaces", "stp_topology_observations", "vlan_cutover")
LIMITATIONS = (
    "Relations concern the supplied stored cable/member and VLAN-row universe, not every possible cable or VLAN.",
    "PVST port states are observations from separate captures, not simultaneous forwarding or data-plane delivery.",
    "Mutual stored trunk allowance is a configured-carriage model, not observed STP forwarding or traffic.",
    "MST instances have no admitted VLAN mapping here; legacy namespace-free interface STP ranges are never used.",
    "Bundle relations require agreement of every member; no first member represents an incomplete or mixed bundle.",
    "Source pointers and closed-shape validation are not authenticated capture custody or collection completeness.",
)
_ISSUES = {
    "missing_source": "not collected: a required source is absent",
    "malformed_source": "unverified: a supplied source has an unsupported shape",
    "failed_source": "analysis unavailable: the caller records a failed input source",
    "failed_sources_invalid": "unverified: failed-source declarations are outside the closed input contract",
    "vlan_unreadable": "unverified: this VLAN row has no integer VLAN identity in 1..4094",
    "vlan_duplicate": "unverified: more than one supplied VLAN row names this VLAN",
    "cable_unreadable": "unverified: this cable has no complete readable endpoint/member identity",
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
_RANGE_SEPARATOR = r"(?: *, *| +)"
_RANGE = re.compile(r"[0-9]+(?:-[0-9]+)?(?:" + _RANGE_SEPARATOR + r"[0-9]+(?:-[0-9]+)?)*\Z")
_INTERFACE_FIELDS = ("port", "cdp_neighbor", "neighbor_port", "switchport_mode",
                     "trunk_allowed_vlans", "trunk_native_vlan", "port_channel")


def _pointer(*parts: object) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _text(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def _port(value: Any) -> str | None:
    return normalize_ifname(value) if _text(value) and is_valid_iface(value) else None


def _physical_identity(a: Any, ap: Any, b: Any, bp: Any) -> tuple | None:
    """Count every readable pair witness, even inside an otherwise refused record.

    Producer and stored validator use the same census. Unsupported extra keys or an
    inconsistent outer cable cannot make its readable member cease to conflict with another.
    """
    if not _text(a) or not _text(b) or _port(ap) is None or _port(bp) is None:
        return None
    return tuple(sorted(((a, _port(ap)), (b, _port(bp)))))


def _channel(value: Any) -> str | None:
    """The interface field's actual PoN/Port-channelN forms, never a physical port."""
    normalized = _port(value)
    match = re.fullmatch(r"Po([0-9]+)", normalized or "", flags=re.IGNORECASE)
    if match is None:
        return None
    number = match[1].lstrip("0")
    return "Po" + number if number else None


def _interface_values(raw: Any) -> dict[str, str] | None:
    """Admit every supplied record's relevant field types, joined or not."""
    if type(raw) is dict:
        values = {name: raw.get(name, "") for name in _INTERFACE_FIELDS}
    elif isinstance(raw, InterfaceData):
        values = {name: getattr(raw, name) for name in _INTERFACE_FIELDS}
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


def _allowance(value: Any, vid: int | None, *, native: bool = False) -> tuple[bool, bool | None]:
    """Strict admission and membership, without expanding a VLAN range.

    Blank/--/n/a are missing, whereas literal 'none' is an explicit exclusion.
    Invalid tokens never disappear beside valid tokens as in a permissive range reader.
    A None selector checks syntax only for the complete input-record census.
    """
    if type(value) is not str:
        return False, None
    value = value.strip().lower()
    if value in ("", "--", "n/a"):
        return True, None
    if native:
        if not re.fullmatch(r"[0-9]{1,4}", value) or not 1 <= int(value) <= 4094:
            return False, None
        # A different native VLAN is not an exclusion of this VLAN from the trunk.
        return True, True if vid is not None and int(value) == vid else None
    if value == "all":
        return True, True if vid is not None else None
    if value == "none":
        return True, False if vid is not None else None
    if not _RANGE.fullmatch(value):
        return False, None
    matched = False
    for token in re.split(_RANGE_SEPARATOR, value):
        pair = token.split("-")
        if any(len(number) > 4 for number in pair):
            return False, None
        lo, hi = int(pair[0]), int(pair[-1])
        if not 1 <= lo <= hi <= 4094:
            return False, None
        if vid is not None:
            matched |= lo <= vid <= hi
    return True, matched if vid is not None else None


def _issue(code: str, pointer: str, state: str = "unverified") -> dict:
    return {"state": state, "reason": _ISSUES[code], "pointer": pointer}


def _verdict(state: str, code: str | None, *, relation: str | None = None,
             basis: str = "none", shape: str = "unverified") -> dict:
    return {"state": state, "relation": relation, "reason": _ISSUES[code] if code else None,
            "basis": basis, "evidence_shape": shape}


def carriage_observation_admission(observation: Any) -> tuple[str, str | None, Any]:
    """Admit one declared stored STP record under the carriage owner's existing rules.

    This is eligibility, not carriage computation or election. The second result is
    the existing reason code, and the third is the same admitted record (never a copy).
    Absent host/section and declared source failure remain the caller's environment.
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
            or set(observation["finding_codes"]) & {
                "state_instance_duplicate", "mixed_namespace", "role_row_malformed", "role_subject_duplicate"}):
        return "unverified", "stp_unreadable", observation
    if any(row["namespace"] == "mst_instance" for row in observation["roots"] + observation["roles"]):
        return "unverified", "mst_unmapped", observation
    return "published", None, observation


class _Inputs:
    def __init__(self, interfaces: Any, observations: Any, failed: set[str]):
        self.interfaces, self.observations, self.failed = interfaces, observations, failed
        self.hosts: dict[str, list[str]] = defaultdict(list)
        self.ports: dict[str, dict[str, list[str]]] = {}
        self.stp: dict[str, tuple[str, str | None, Any]] = {}
        for host, records in (interfaces.items() if type(interfaces) is dict else ()):
            if not _text(host):
                continue
            self.hosts[_canon_host(host)].append(host)
            ports: dict[str, list[str]] = defaultdict(list)
            for key in (records if type(records) is dict else ()):
                normalized = _port(key)
                if normalized:
                    ports[normalized].append(key)
            self.ports[host] = ports

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

    def end(self, host: Any, port: Any, other_host: Any, other_port: Any, vid: int) -> dict:
        out = {"host": host if _text(host) else None, "port": port if _text(port) else None,
               "interface_pointer": None, "state": "unverified", "signal": None,
               "basis": "none", "reason": None, "refs": []}

        def hold(code: str, state: str = "unverified") -> dict:
            out.update(state=state, signal=None, basis="none", reason=_ISSUES[code])
            return out

        if "interfaces" in self.failed:
            return hold("failed_source", "analysis_unavailable")
        if not _text(host) or _port(port) is None:
            return hold("member_unreadable")
        if type(self.interfaces) is not dict:
            return hold("missing_interface" if self.interfaces is None else "malformed_source",
                        "not_collected" if self.interfaces is None else "unverified")
        if len(self.hosts.get(_canon_host(host), [])) > 1:
            return hold("host_collision")
        if host not in self.interfaces:
            return hold("missing_interface", "not_collected")
        records = self.interfaces[host]
        if type(records) is not dict:
            return hold("interface_unreadable")
        keys = self.ports.get(host, {}).get(_port(port), [])
        if len(keys) > 1:
            return hold("port_collision")
        if not keys:
            return hold("missing_interface", "not_collected")
        key = keys[0]
        raw = records[key]
        pointer = _pointer("interfaces", host, key)
        out["interface_pointer"] = pointer
        out["refs"] = [pointer]
        values = _interface_values(raw)
        if values is None:
            return hold("interface_unreadable")
        if values["port"] and _port(values["port"]) != _port(port):
            return hold("endpoint_mismatch")
        if values["cdp_neighbor"] and _canon_host(values["cdp_neighbor"]) != _canon_host(other_host):
            return hold("endpoint_mismatch")
        if values["neighbor_port"] and _port(values["neighbor_port"]) != _port(other_port):
            return hold("endpoint_mismatch")
        allowed_ok, allowed = _allowance(values["trunk_allowed_vlans"], vid)
        native_ok, native = _allowance(values["trunk_native_vlan"], vid, native=True)
        if not allowed_ok or not native_ok:
            out["refs"].extend(_pointer("interfaces", host, key, name) for name, valid in
                               (("trunk_allowed_vlans", allowed_ok), ("trunk_native_vlan", native_ok)) if not valid)
            return hold("range_unreadable")
        if native is True:
            if allowed is False:
                return hold("evidence_conflict")
            allowed = True
        state, why, observation = self.observation(host)
        if observation is not None:
            out["refs"].append(_pointer("stp_topology_observations", host))
        if state in ("unverified", "analysis_unavailable"):
            return hold(why or "stp_unreadable", state)
        hits = [(i, row) for i, row in enumerate(observation["roles"] if state == "published" else [])
                if row["namespace"] == "pvst_vlan" and int(row["instance"]) == vid
                and _port(row["interface"]) == _port(port)]
        if len(hits) > 1:
            return hold("role_ambiguous")
        if hits:
            index, role = hits[0]
            out["refs"].append(_pointer("stp_topology_observations", host, "roles", index))
            compatible = ((role["state"] == "forwarding" and role["role"] in ("root", "designated", "boundary"))
                          or (role["state"] == "blocked" and role["role"] in ("alternate", "backup", "boundary")))
            if not compatible:
                return hold("role_unstable")
            if role["state"] == "forwarding" and allowed is False:
                return hold("evidence_conflict")
            out.update(state="published", signal=role["state"], basis="typed_pvst")
            return out
        if allowed is not None:
            mode = values["switchport_mode"].strip().casefold()
            if mode != "trunk":
                return hold("trunk_mode_missing" if not mode else "trunk_mode_conflict",
                            "not_collected" if not mode else "unverified")
            out["refs"].extend(_pointer("interfaces", host, key, name) for name in
                               ("trunk_allowed_vlans", "trunk_native_vlan", "switchport_mode") if values[name].strip())
            out.update(state="published", signal="allowed" if allowed else "excluded", basis="stored_trunk_allowance")
            return out
        return hold("no_evidence", "not_collected")

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
            if type(records) is not dict or len(keys) != 1 or len(self.hosts.get(_canon_host(other), [])) > 1:
                continue
            values = _interface_values(records[keys[0]])
            if (values is not None and _text(values["cdp_neighbor"]) and _port(values["neighbor_port"]) is not None
                    and _canon_host(values["cdp_neighbor"]) == _canon_host(other)
                    and _port(values["neighbor_port"]) == _port(other_port)):
                witnessed[side] = [_pointer("interfaces", host, keys[0], field)
                                   for field in ("cdp_neighbor", "neighbor_port")]
        return witnessed


def _member_relation(a: dict, b: dict) -> dict:
    for state in ("analysis_unavailable", "unverified"):
        bad = next((end for end in (a, b) if end["state"] == state), None)
        if bad:
            return {**_verdict(state, "mixed_basis"), "reason": bad["reason"]}
    known = sum(end["state"] == "published" for end in (a, b))
    if known < 2:
        return _verdict("not_collected", "one_end_only" if known else "both_ends_missing",
                        shape="one_end_only" if known else "no_evidence")
    signals = {a["signal"], b["signal"]}
    if "blocked" in signals:
        return _verdict("published", None, relation="stp_blocked", basis="typed_pvst", shape="both_ends")
    if "excluded" in signals:
        return _verdict("published", None, relation="not_carried", basis="stored_trunk_allowance", shape="both_ends")
    if signals == {"forwarding"}:
        return _verdict("published", None, relation="forwarding", basis="typed_pvst", shape="both_ends")
    if signals == {"allowed"}:
        return _verdict("published", None, relation="forwarding", basis="stored_trunk_allowance", shape="both_ends")
    return _verdict("unverified", "mixed_basis", shape="both_ends")


def _cable_identity(raw: Any) -> tuple[dict, list, bool]:
    ends = {key: raw.get(key) if type(raw) is dict else None for key in ("a", "a_port", "b", "b_port", "is_pc")}
    good = (_text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
            and _port(ends["a_port"]) is not None and _port(ends["b_port"]) is not None
            and type(ends["is_pc"]) is bool)
    members = raw.get("members") if type(raw) is dict else None
    if type(members) is not list:
        return {k: v if (type(v) is bool if k == "is_pc" else _text(v)) else None for k, v in ends.items()}, [], False
    good = good and bool(members) and (ends["is_pc"] or len(members) == 1)
    if members and type(members[0]) is dict:
        good = good and all(_port(members[0].get(k)) == _port(ends[k]) for k in ("a_port", "b_port"))
    else:
        good = False
    clean = {k: v if (type(v) is bool if k == "is_pc" else _text(v)) else None for k, v in ends.items()}
    return clean, members, bool(good)


def compute_vlan_carriage(cable_map: Any, interfaces: Any, stp_topology_observations: Any,
                          vlan_rows: Any, *, failed_sources: Any = ()) -> dict:
    """Produce a new closed stored section without parsing command text or mutating inputs.

    ``vlan_rows`` is the explicit existing vlan_cutover row list, not a discovered/expanded
    range. ``failed_sources`` names only SOURCES; callers retain their own phase receipts.
    Malformed source rows remain indexed in the emitted pair census. Their issues qualify
    the section even when another individual row has usable evidence.
    """
    issues = []
    failed: set[str] = set()
    if (type(failed_sources) not in (list, tuple) or any(type(s) is not str or s not in SOURCES for s in failed_sources)
            or len(set(failed_sources)) != len(failed_sources)):
        issues.append(_issue("failed_sources_invalid", "/"))
    else:
        failed = set(failed_sources)
        issues.extend(_issue("failed_source", _pointer(s), "analysis_unavailable") for s in sorted(failed))
    cables = cable_map.get("cables") if type(cable_map) is dict else None
    for name, value, expected in (("cable_map", cable_map, dict), ("interfaces", interfaces, dict),
                                  ("stp_topology_observations", stp_topology_observations, dict),
                                  ("vlan_cutover", vlan_rows, list)):
        if value is not None and type(value) is not expected:
            issues.append(_issue("malformed_source", _pointer(name)))
        elif value is None and name != "stp_topology_observations":
            issues.append(_issue("missing_source", _pointer(name), "not_collected"))
    if type(cable_map) is dict and type(cables) is not list:
        issues.append(_issue("malformed_source", "/cable_map/cables"))
    for host, records in (interfaces.items() if type(interfaces) is dict else ()):
        if not _text(host) or type(records) is not dict:
            issues.append(_issue("malformed_source", _pointer("interfaces", host) if _text(host) else "/interfaces"))
            continue
        for port, record in records.items():
            values = _interface_values(record)
            witness = _pointer("interfaces", host, port) if _text(port) else _pointer("interfaces", host)
            if (_port(port) is None or values is None
                    or (values["port"] and _port(values["port"]) != _port(port))
                    or (values["port_channel"] and _channel(values["port_channel"]) is None)):
                issues.append(_issue("interface_unreadable", witness))
            if values is not None:
                for field, native in (("trunk_allowed_vlans", False), ("trunk_native_vlan", True)):
                    if not _allowance(values[field], None, native=native)[0]:
                        issues.append(_issue("range_unreadable", witness + "/" + field if _text(port) else witness))
    for host in (stp_topology_observations if type(stp_topology_observations) is dict else ()):
        if not _text(host):
            issues.append(_issue("malformed_source", "/stp_topology_observations"))
    vlans = [vlan_row_identity(row) for row in vlan_rows] if type(vlan_rows) is list else []
    duplicates = Counter(v for v in vlans if v is not None)
    identities = [_cable_identity(raw) for raw in cables] if type(cables) is list else []
    member_owners: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for ci, (ends, members, good) in enumerate(identities):
        if not good:
            issues.append(_issue("cable_unreadable", _pointer("cable_map", "cables", ci)))
        for mi, member in enumerate(members):
            if (type(member) is not dict or set(member) != {"a_port", "b_port"}
                    or not all(_port(member[k]) for k in ("a_port", "b_port"))):
                issues.append(_issue("member_unreadable", _pointer("cable_map", "cables", ci, "members", mi)))
            pair = (_physical_identity(ends["a"], member.get("a_port"), ends["b"], member.get("b_port"))
                    if type(member) is dict else None)
            if pair is not None:
                member_owners[pair].append((ci, mi))
    repeated = {owner for owners in member_owners.values() if len(owners) > 1 for owner in owners}
    ctx = _Inputs(interfaces, stp_topology_observations, failed)
    for hosts in ctx.hosts.values():
        if len(hosts) > 1:
            issues.extend(_issue("host_collision", _pointer("interfaces", host)) for host in hosts)
    for host, ports in ctx.ports.items():
        for keys in ports.values():
            if len(keys) > 1:
                issues.extend(_issue("port_collision", _pointer("interfaces", host, key)) for key in keys)
    # Even an unjoined observation is part of the supplied evidence census. It cannot
    # silently disappear merely because no current cable names its host.
    for host in (stp_topology_observations if type(stp_topology_observations) is dict else ()):
        if _text(host):
            status, why, _ = ctx.observation(host)
            if status in ("unverified", "analysis_unavailable"):
                issues.append(_issue(why or "stp_unreadable", _pointer("stp_topology_observations", host), status))
    rows = []
    for vi, vid in enumerate(vlans):
        invalid_vlan = "vlan_unreadable" if vid is None else "vlan_duplicate" if duplicates[vid] > 1 else None
        if invalid_vlan:
            issues.append(_issue(invalid_vlan, _pointer("vlan_cutover", vi, "vlan")))
        for ci, (ends, members, good) in enumerate(identities):
            pointer = _pointer("cable_map", "cables", ci)
            results = []
            for mi, member in enumerate(members):
                mp = pointer + "/members/" + str(mi)
                ports_ok = (type(member) is dict and set(member) == {"a_port", "b_port"}
                            and all(_port(member[k]) for k in member))
                ap, bp = (member.get("a_port"), member.get("b_port")) if type(member) is dict else (None, None)
                if vid is None:
                    def unknown_end(host, port):
                        return {"host": host, "port": port if _text(port) else None,
                                "interface_pointer": None, "state": "unverified", "signal": None,
                                "basis": "none", "reason": _ISSUES["vlan_unreadable"], "refs": []}
                    a, b = unknown_end(ends["a"], ap), unknown_end(ends["b"], bp)
                else:
                    a = ctx.end(ends["a"], ap, ends["b"], bp, vid)
                    b = ctx.end(ends["b"], bp, ends["a"], ap, vid)
                if ends["is_pc"] is True:
                    orientation = ctx.member_orientation(ends, member)
                    for side, end in (("a", a), ("b", b)):
                        end["refs"].extend(ref for ref in orientation.get(side, []) if ref not in end["refs"])
                        if not orientation and end["state"] == "published":
                            end.update(state="unverified", signal=None, basis="none", reason=_ISSUES["bundle_orientation"])
                            end["refs"].append(mp)
                verdict = _member_relation(a, b)
                if not ports_ok or not good:
                    verdict = _verdict("unverified", "member_unreadable")
                if (ci, mi) in repeated:
                    verdict = _verdict("unverified", "member_duplicate")
                if invalid_vlan:
                    verdict = _verdict("unverified", invalid_vlan)
                results.append({"index": mi, "pointer": mp, **verdict, "a": a, "b": b})
            if not good:
                verdict = _verdict("unverified", "cable_unreadable")
            elif invalid_vlan:
                verdict = _verdict("unverified", invalid_vlan)
            elif ends["is_pc"] and not ctx.bundle(ends, members):
                verdict = _verdict("unverified", "lag_ambiguous")
            elif len(results) == 1:
                verdict = {key: results[0][key] for key in ("state", "relation", "reason", "basis", "evidence_shape")}
            elif results and all(m["state"] == "published" for m in results) and len({m["relation"] for m in results}) == 1:
                verdict = _verdict("published", None, relation=results[0]["relation"],
                                   basis="member_consensus", shape="both_ends")
            else:
                verdict = _verdict("unverified", "mixed_members")
            if "cable_map" in failed or "vlan_cutover" in failed:
                verdict = _verdict("analysis_unavailable", "failed_source")
            rows.append({"index": len(rows), "vlan_index": vi, "vlan": vid,
                         "vlan_pointer": _pointer("vlan_cutover", vi), "cable_index": ci,
                         "cable_pointer": pointer, "ends": dict(ends), **verdict, "members": results})
    states = [issue["state"] for issue in issues] + [row["state"] for row in rows]
    state = next((s for s in ("analysis_unavailable", "unverified", "not_collected") if s in states),
                 "published" if rows else "collected_but_empty")
    reason = (next((issue["reason"] for issue in issues if issue["state"] == state), None)
              or next((row["reason"] for row in rows if row["state"] == state), None))
    if state == "collected_but_empty":
        reason = _ISSUES["empty_universe"]
    return {"schema": SCHEMA, "state": state, "reason": reason,
            "basis": "cisco_toolkit.vlan_carriage:compute_vlan_carriage",
            "coverage": {"vlan_rows": len(vlans) if type(vlan_rows) is list else None,
                         "cable_rows": len(identities) if type(cables) is list else None,
                         "requested_pairs": len(vlans) * len(identities) if type(vlan_rows) is list and type(cables) is list else None,
                         "emitted_pairs": len(rows), "by_state": {s: sum(row["state"] == s for row in rows) for s in STATES},
                         "input_census_complete": not issues, "capture_completeness_claim": False},
            "issues": issues, "rows": rows, "limitations": list(LIMITATIONS)}


def validate_vlan_carriage(value: Any) -> tuple[bool, str]:
    """Validate only the closed stored representation/census, never recompute or authenticate it."""
    common = {"state", "relation", "reason", "basis", "evidence_shape"}
    end_keys = {"host", "port", "interface_pointer", "state", "signal", "basis", "reason", "refs"}

    def keys(row: Any, names: set[str]) -> bool:
        return type(row) is dict and set(row) == names

    def pointer(raw: Any) -> bool:
        return type(raw) is str and raw.startswith("/") and not re.search(r"~(?![01])", raw)

    def interface_join(end: dict) -> bool:
        path = end["interface_pointer"]
        if path is None:
            return True
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]
        return (len(parts) == 3 and parts[:2] == ["interfaces", end["host"]]
                and _port(end["port"]) is not None and _port(parts[2]) == _port(end["port"])
                and path in end["refs"])

    def reason(row: dict) -> bool:
        return ((row["state"] == "published" and row["reason"] is None)
                or (row["state"] != "published" and row["reason"] in _ISSUES.values()))

    def verdict(row: dict) -> bool:
        return (row["state"] in STATES and row["state"] != "collected_but_empty" and reason(row)
                and row["basis"] in BASES and row["evidence_shape"] in EVIDENCE_SHAPES
                and (row["relation"] in RELATIONS and row["basis"] != "none" and row["evidence_shape"] == "both_ends"
                     if row["state"] == "published" else row["relation"] is None and row["basis"] == "none")
                and (row["state"] == "not_collected" if row["evidence_shape"] in ("one_end_only", "no_evidence") else True))

    try:
        if not keys(value, {"schema", "state", "reason", "basis", "coverage", "issues", "rows", "limitations"}):
            return False, "section_keys"
        if (value["schema"] != SCHEMA or value["state"] not in STATES or not reason(value)
                or value["basis"] != "cisco_toolkit.vlan_carriage:compute_vlan_carriage"
                or value["limitations"] != list(LIMITATIONS)):
            return False, "section_contract"
        cov = value["coverage"]
        if not keys(cov, {"vlan_rows", "cable_rows", "requested_pairs", "emitted_pairs", "by_state",
                          "input_census_complete", "capture_completeness_claim"}):
            return False, "coverage_keys"
        if any(cov[k] is not None and (type(cov[k]) is not int or cov[k] < 0)
               for k in ("vlan_rows", "cable_rows", "requested_pairs")):
            return False, "coverage_counts"
        rows, issues = value["rows"], value["issues"]
        if type(rows) is not list or type(issues) is not list:
            return False, "section_lists"
        if any(not keys(i, {"state", "reason", "pointer"}) or i["state"] not in STATES[2:]
               or not reason(i) or not pointer(i["pointer"]) for i in issues):
            return False, "issues"
        expected = cov["vlan_rows"] * cov["cable_rows"] if cov["vlan_rows"] is not None and cov["cable_rows"] is not None else None
        if (cov["requested_pairs"] != expected or type(cov["emitted_pairs"]) is not int
                or cov["emitted_pairs"] != len(rows) or (expected is not None and len(rows) != expected)
                or (expected is None and rows)
                or cov["capture_completeness_claim"] is not False
                or type(cov["input_census_complete"]) is not bool
                or cov["input_census_complete"] != (not issues)):
            return False, "coverage_census"
        seen_vlans: dict[int, Any] = {}
        seen_cables: dict[int, Any] = {}
        seen_members: dict[tuple, list[dict]] = defaultdict(list)
        for index, row in enumerate(rows):
            if not keys(row, common | {"index", "vlan_index", "vlan", "vlan_pointer", "cable_index", "cable_pointer", "ends", "members"}):
                return False, "row_keys"
            if (type(row["index"]) is not int or row["index"] != index or not verdict(row)
                    or type(row["vlan_index"]) is not int or type(row["cable_index"]) is not int
                    or cov["cable_rows"] is None or cov["cable_rows"] == 0
                    or (row["vlan_index"], row["cable_index"]) != divmod(index, cov["cable_rows"])
                    or row["vlan_pointer"] != _pointer("vlan_cutover", row["vlan_index"])
                    or row["cable_pointer"] != _pointer("cable_map", "cables", row["cable_index"])
                    or (row["vlan"] is not None and (type(row["vlan"]) is not int or not 1 <= row["vlan"] <= 4094))):
                return False, "row_identity_or_verdict"
            if not keys(row["ends"], {"a", "b", "a_port", "b_port", "is_pc"}) or type(row["members"]) is not list:
                return False, "row_endpoints"
            if any(v is not None and (type(v) is not bool if k == "is_pc" else not _text(v)) for k, v in row["ends"].items()):
                return False, "row_endpoint_types"
            for mi, member in enumerate(row["members"]):
                if (not keys(member, common | {"index", "pointer", "a", "b"}) or type(member["index"]) is not int
                        or member["index"] != mi or member["pointer"] != row["cable_pointer"] + "/members/" + str(mi)
                        or not verdict(member)):
                    return False, "member_contract"
                for end in (member["a"], member["b"]):
                    if (not keys(end, end_keys) or end["state"] not in STATES or not reason(end)
                            or end["state"] == "collected_but_empty" or end["basis"] not in BASES
                            or any(end[k] is not None and not _text(end[k]) for k in ("host", "port"))
                            or (end["interface_pointer"] is not None and not pointer(end["interface_pointer"]))
                            or type(end["refs"]) is not list or not all(pointer(ref) for ref in end["refs"])
                            or (end["signal"] not in END_SIGNALS if end["state"] == "published" else end["signal"] is not None)):
                        return False, "end_contract"
                    if not interface_join(end):
                        return False, "end_interface_join"
                    if end["state"] == "published":
                        if (end["interface_pointer"] is None or end["interface_pointer"] not in end["refs"]
                                or end["host"] is None or _port(end["port"]) is None
                                or end["basis"] not in ("typed_pvst", "stored_trunk_allowance")
                                or (end["signal"] not in ("forwarding", "blocked") if end["basis"] == "typed_pvst"
                                    else end["signal"] not in ("allowed", "excluded"))):
                            return False, "end_basis"
                        if end["basis"] == "typed_pvst" and not any(
                                ref.startswith(_pointer("stp_topology_observations", end["host"], "roles") + "/")
                                for ref in end["refs"]):
                            return False, "end_stp_witness"
                    elif end["basis"] != "none":
                        return False, "end_held_basis"
                if member["a"]["host"] != row["ends"]["a"] or member["b"]["host"] != row["ends"]["b"]:
                    return False, "member_host_join"
                if member["state"] == "published":
                    expected_member = _member_relation(member["a"], member["b"])
                    if any(member[k] != expected_member[k] for k in common):
                        return False, "member_contradiction"
                pair = _physical_identity(member["a"]["host"], member["a"]["port"],
                                          member["b"]["host"], member["b"]["port"])
                if pair is not None:
                    seen_members[(row["vlan_index"], pair)].append(member)
                if row["ends"]["is_pc"] is True and member["state"] == "published" and not any(
                        end["interface_pointer"] is not None
                        and all(end["interface_pointer"] + "/" + field in end["refs"]
                                for field in ("cdp_neighbor", "neighbor_port"))
                        for end in (member["a"], member["b"])):
                    return False, "bundle_orientation_witness"
            members, ends = row["members"], row["ends"]
            identity_ok = (bool(members) and _text(ends["a"]) and _text(ends["b"]) and ends["a"] != ends["b"]
                           and type(ends["is_pc"]) is bool and (ends["is_pc"] or len(members) == 1)
                           and all(_port(ends[side + "_port"]) is not None
                                   and _port(ends[side + "_port"]) == _port(members[0][side]["port"])
                                   for side in ("a", "b")))
            if not identity_ok and (row["state"] == "published" or any(m["state"] == "published" for m in members)):
                return False, "outer_member_identity"
            if row["state"] == "published":
                if (row["vlan"] is None or not members or any(v is None for v in row["ends"].values())
                        or any(m["state"] != "published" or m["relation"] != row["relation"] for m in members)
                        or row["basis"] != (members[0]["basis"] if len(members) == 1 else "member_consensus")
                        or (len(members) > 1 and row["ends"]["is_pc"] is not True)):
                    return False, "cable_contradiction"
            vi, ci = row["vlan_index"], row["cable_index"]
            cable_identity = (row["ends"], [(m["a"]["port"], m["b"]["port"]) for m in row["members"]])
            if ((vi in seen_vlans and seen_vlans[vi] != row["vlan"])
                    or (ci in seen_cables and seen_cables[ci] != cable_identity)):
                return False, "cross_row_identity"
            seen_vlans[vi], seen_cables[ci] = row["vlan"], cable_identity
        duplicate_vlans = {v for v, count in Counter(v for v in seen_vlans.values() if v is not None).items() if count > 1}
        for row in rows:
            if row["vlan"] in duplicate_vlans:
                witness = _issue("vlan_duplicate", _pointer("vlan_cutover", row["vlan_index"], "vlan"))
                if (row["state"] not in ("unverified", "analysis_unavailable") or witness not in issues
                        or any(m["state"] != "unverified" for m in row["members"])):
                    return False, "duplicate_vlan_admission"
        if any(len(members) > 1 and any(m["state"] != "unverified" for m in members)
               for members in seen_members.values()):
            return False, "duplicate_member_admission"
        counts = {s: sum(row["state"] == s for row in rows) for s in STATES}
        if not keys(cov["by_state"], set(STATES)) or any(type(v) is not int for v in cov["by_state"].values()) or cov["by_state"] != counts:
            return False, "state_census"
        states = [issue["state"] for issue in issues] + [row["state"] for row in rows]
        expected_state = next((s for s in ("analysis_unavailable", "unverified", "not_collected") if s in states),
                              "published" if rows else "collected_but_empty")
        if value["state"] != expected_state:
            return False, "section_state"
        return True, "ok"
    except (TypeError, ValueError, KeyError, RecursionError):
        return False, "malformed_value"
