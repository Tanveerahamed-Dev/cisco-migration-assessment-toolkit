"""Source-bound IPv6 routing-adjacency cutover baseline.

This module deliberately owns its public contract independently of the legacy
``build_ipv6_routing`` snapshot projection.  The implementation is completed
below in this file; keeping the API here also gives decision consumers one
stable import boundary while the legacy parser remains backward compatible.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from cisco_toolkit.capture_integrity import inspect_capture
from cisco_toolkit.input_custody import read_text as read_custodied_text


IPV6_ROUTING_ADJACENCY_SCHEMA = "ipv6_routing_adjacency_baseline/1"
IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA = "ipv6_routing_subject_scope/1"

_SCOPE = {
    "routing_instance": "default",
    "address_family": "ipv6",
    "protocols": ["OSPFv3", "BGPv6"],
    "denominator": "observed_runtime_adjacencies",
}
_LIMITATIONS = [
    "The baseline covers observed default/global IPv6 OSPFv3 and BGPv6 runtime adjacencies; it is not a configured or expected-peer denominator.",
    "An empty or NOT_APPLICABLE result is not proof that IPv6 routing, another VRF, another address family, or an expected peer is absent.",
    "OSPFv3 process, area, network type, timers, authentication, LSDB correctness, persistence, and convergence history are incomplete or outside this receipt.",
    "BGPv6 policy, activation intent, route correctness, other VRFs/address families, and configured-but-unobserved peers remain outside this receipt.",
    "IPv6 route-summary counts are point-in-time census context; BGP prefix counts are informational and are not pinned acceptance targets.",
    "An embedded_unverified projection is an audit receipt only and cannot authorize a current-run positive cutover decision.",
]

_ROOT_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody",
    "rows", "coverage", "findings", "summary", "limitations",
}
_ROW_KEYS = {
    "switch", "platform", "protocol", "routing_instance", "process",
    "peer", "peer_key", "interface", "remote_as", "role", "state_raw",
    "state", "prefix_count", "prefix_count_present", "status", "command",
    "acceptance", "source_key", "projection_custody", "findings",
}
_COVERAGE_KEYS = {
    "switch", "platform", "input", "protocol", "subject", "status",
    "selected_command", "capture_status", "parser_status",
    "candidate_count", "parsed_count", "rejected_count",
    "active_route_count", "source_sha256", "projection_sha256",
    "finding_codes",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_subject_hosts", "n_rows", "n_ospfv3_rows",
    "n_bgpv6_rows", "n_assessed", "n_degraded", "n_review",
    "n_not_verified", "by_status", "by_coverage_status",
    "baseline_sha256",
}
_ROW_STATUSES = ("degraded", "review", "not_verified", "assessed")
_COVERAGE_STATUSES = _ROW_STATUSES + ("not_applicable",)
_PARSER_STATUSES = {
    "complete", "review", "rejected", "not_verified",
    "explicit_no_subject",
}
_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt",
    "unreadable", "not_observed", "inspection_missing",
    "inspection_duplicate",
}
_INPUTS = (
    ("route_summary", "IPv6"),
    ("ospfv3_neighbors", "OSPFv3"),
    ("bgp_ipv6_neighbors", "BGPv6"),
)
_ROUTE_COMMAND = "show ipv6 route summary"
_BGP_COMMANDS = ("show bgp ipv6 unicast summary",)
_OSPF_IOS_COMMANDS = (
    "show ospfv3 neighbor", "show ipv6 ospf neighbor",
    "show ospfv3 neighbors", "show ipv6 ospfv3 neighbors",
    "show ipv6 ospfv3 neighbor", "show ipv6 ospf neighbors",
)
_OSPF_NXOS_COMMANDS = (
    "show ipv6 ospfv3 neighbors", "show ospfv3 neighbors",
    "show ipv6 ospfv3 neighbor", "show ospfv3 neighbor",
    "show ipv6 ospf neighbor", "show ipv6 ospf neighbors",
)
_RECOGNIZED_COMMANDS = frozenset(
    (_ROUTE_COMMAND,) + _BGP_COMMANDS + _OSPF_IOS_COMMANDS +
    _OSPF_NXOS_COMMANDS
)

_MAX_HOSTS = 4096
_MAX_ROWS = 20_000
_MAX_CANDIDATES = 8192
_MAX_INSPECTIONS = 1_000_000
_MAX_LINES = 100_000
_MAX_BODY_CHARS = 8_000_000
_MAX_AGGREGATE_BODY_CHARS = 64_000_000
_MAX_FINDINGS_PER_ROW = 16
_MAX_ACTIVE_ROUTES = 4_294_967_295
_MAX_BGP_COUNTER = 18_446_744_073_709_551_615

_ROUTE_NEUTRAL_SOURCES = frozenset({
    "connected", "local", "static", "rip", "ripng", "isis", "is-is",
    "eigrp", "nd", "ndp", "mobile", "nat", "lisp", "application",
    "discard", "odr",
})

_CLI_ERROR_PREFIXES = (
    "% invalid input", "% incomplete command", "% ambiguous command",
    "% unknown command", "% type help", "% bad", "% authorization failed",
    "% error", "% permission denied for the role",
    "command authorization failed",
)
_OSPF_HEALTHY = {"FULL", "2WAY"}
_OSPF_DEGRADED = {
    "DOWN", "ATTEMPT", "INIT", "EXSTART", "EXCHANGE", "LOADING",
}
_BGP_DEGRADED = {
    "IDLE", "IDLE(ADMIN)", "CONNECT", "ACTIVE", "OPENSENT",
    "OPENCONFIRM", "IDLE(ADMIN-SHUT)",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    try:
        return hashlib.sha256(_json_bytes(value)).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, MemoryError):
        return ""


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    result = value.strip()
    if result != value or any(ord(char) < 32 or ord(char) == 127 for char in result):
        return ""
    return result


def _safe_string(value: Any, limit: int, *, empty: bool = True) -> bool:
    return bool(
        isinstance(value, str) and len(value) <= limit
        and (empty or value) and _text(value, limit) == value
    )


def _safe_ascii_string(value: Any, limit: int, *, empty: bool = True) -> bool:
    return bool(
        _safe_string(value, limit, empty=empty)
        and (not value or value.isascii())
    )


def _has_casefold_collision(values: Iterable[str]) -> bool:
    seen = set()
    for value in values:
        folded = value.casefold()
        if folded in seen:
            return True
        seen.add(folded)
    return False


def _platforms(devices: Any) -> Tuple[Dict[str, str], str]:
    result: Dict[str, str] = {}
    if devices is None:
        return result, ""
    if isinstance(devices, list):
        items: Iterable[Any] = devices
    elif isinstance(devices, dict):
        items = [
            dict(value, hostname=key) if isinstance(value, dict)
            else {"hostname": key, "platform": value}
            for key, value in devices.items()
        ]
    else:
        return {}, "scope_input_invalid"
    for item in items:
        if not isinstance(item, dict):
            return {}, "scope_identity_invalid"
        raw_host = item.get("hostname") or item.get("switch")
        host = _text(raw_host, 128)
        platform = _text(item.get("platform", ""), 80)
        if not host or (item.get("platform", "") and not platform):
            return {}, "scope_identity_invalid"
        if host in result and result[host] != platform:
            return {}, "scope_identity_collision"
        result[host] = platform
    if len(result) > _MAX_HOSTS:
        return {}, "scope_host_cap_exceeded"
    if _has_casefold_collision(result):
        return {}, "scope_identity_collision"
    if any(not host.isascii() or (platform and not platform.isascii())
           for host, platform in result.items()):
        return {}, "scope_identity_invalid"
    return result, ""


def _plain_copy(value: dict) -> dict:
    return {key: copy.deepcopy(item) for key, item in dict(value).items()}


def _baseline_payload(value: dict) -> dict:
    payload = _plain_copy(value)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("baseline_sha256", None)
    return payload


def _body_is_cli_error(body: str) -> bool:
    meaningful = [line.strip() for line in body.splitlines() if line.strip()]
    return bool(meaningful) and all(
        any(line.casefold().startswith(prefix) for prefix in _CLI_ERROR_PREFIXES)
        for line in meaningful
    )


def _read_path(path: Any, budget: Optional[List[int]] = None,
               command: str = "") -> Tuple[str, str]:
    if not isinstance(path, (str, bytes)):
        return "", "unreadable"
    try:
        size = int(os.stat(path).st_size)
        if size > _MAX_BODY_CHARS:
            return "", "unreadable"
        if budget is not None:
            if budget[0] + size > _MAX_AGGREGATE_BODY_CHARS:
                return "", "unreadable"
            budget[0] += size
        body = read_custodied_text(path, encoding="utf-8", errors="strict")
    except Exception:
        return "", "unreadable"
    if len(body) > _MAX_BODY_CHARS or len(body.splitlines()) > _MAX_LINES:
        return "", "unreadable"
    if not body.strip():
        return body, "empty"
    if _body_is_cli_error(body):
        return body, "error"
    if command:
        exact_status = inspect_capture(command, body).get("status")
        if exact_status in {"incomplete", "error", "empty"}:
            return body, exact_status
    return body, "ok"


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    index: Dict[Tuple[str, str], str] = {}
    duplicates = set()
    inspections = capture_integrity.get("inspections") \
        if isinstance(capture_integrity, dict) else None
    if not isinstance(inspections, list) or len(inspections) > _MAX_INSPECTIONS:
        return index, duplicates
    for item in inspections:
        if not isinstance(item, dict):
            continue
        host = _text(item.get("host"), 128)
        command = _text(item.get("command"), 128)
        status = _text(item.get("status"), 32)
        if not host or not command or status not in _CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture_status(index: Dict[Tuple[str, str], str], duplicates: set,
                    host: str, command: str, attempted: bool,
                    read_status: str = "") -> str:
    if not attempted:
        return "not_observed"
    key = (host, command)
    status = "inspection_duplicate" if key in duplicates else \
        index.get(key, "inspection_missing")
    if status == "ok" and read_status and read_status != "ok":
        return read_status
    return status


def _commands(platform: str, input_name: str) -> Tuple[str, ...]:
    if input_name == "route_summary":
        return (_ROUTE_COMMAND,)
    if input_name == "bgp_ipv6_neighbors":
        return _BGP_COMMANDS
    return _OSPF_NXOS_COMMANDS if platform.casefold() in {
        "nxos", "nx-os", "nexus", "n9k"
    } else _OSPF_IOS_COMMANDS


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _canonical_as(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{1,10}", value):
        number = int(value)
        return str(number) if number <= 4_294_967_295 else ""
    match = re.fullmatch(r"(\d{1,5})\.(\d{1,5})", value)
    if not match:
        return ""
    high, low = (int(part) for part in match.groups())
    return f"{high}.{low}" if high <= 65535 and low <= 65535 else ""


def _canonical_ipv6(value: str) -> Tuple[str, str]:
    raw = value.strip()
    address, separator, zone = raw.partition("%")
    if separator and not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", zone):
        return "", ""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return "", ""
    if parsed.version != 6:
        return "", ""
    canonical = str(parsed)
    return (canonical + ("%" + zone if separator else ""), zone)


def _parse_route_summary(body: str) -> dict:
    """Parse one bounded default/global IPv6 RIB census without merging contexts."""
    empty = {
        "parser_status": "not_verified", "candidate_count": 0,
        "parsed_count": 0, "rejected_count": 0,
        "counts": {"OSPFv3": 0, "BGPv6": 0}, "header": False,
        "finding_codes": [],
    }
    if not isinstance(body, str) or not body.strip():
        return empty
    if len(body) > _MAX_BODY_CHARS:
        return dict(empty, parser_status="rejected", rejected_count=1,
                    finding_codes=["route_census_rejected"])
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return dict(empty, parser_status="rejected", rejected_count=1,
                    finding_codes=["route_census_rejected"])

    header_rows: List[Tuple[str, int, bool, str, int]] = []
    header_re = re.compile(
        r"^\s*IPv6\s+Routing\s+Table(?P<summary>\s+Summary)?"
        r"(?:\s+for\s+VRF\s+(?P<vrf>\"[^\"]{1,128}\"|"
        r"'[^']{1,128}'|[A-Za-z0-9_.-]{1,128}))?\s*-\s*"
        r"(?:(?P<context>[A-Za-z0-9_.-]{1,128})\s*-\s*)?"
        r"(?P<entries>\d{1,10})\s+entries"
        r"(?P<inline>\s*:\s*.+)?\s*$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = header_re.fullmatch(line)
        if not match:
            continue
        vrf = (match.group("vrf") or "").strip("\"'")
        context = vrf or (match.group("context") or "default")
        inline = (match.group("inline") or "").strip()
        summary_hint = bool(match.group("summary") or inline)
        entries = int(match.group("entries"))
        header_rows.append((context, index, summary_hint, inline, entries))
    if not header_rows:
        return dict(empty, parser_status="rejected", candidate_count=1,
                    rejected_count=1, finding_codes=["route_census_rejected"])

    context_review = len(header_rows) != 1 or any(
        context.casefold() not in {"default", "global"}
        for context, _index, _summary_hint, _inline, _entries in header_rows
    )
    if any(entries > _MAX_ACTIVE_ROUTES
           for _context, _index, _summary_hint, _inline, entries in header_rows):
        return dict(empty, parser_status="rejected", candidate_count=1,
                    rejected_count=1, header=True,
                    finding_codes=["route_census_rejected"])
    # Never merge across tables.  The first header remains observable, but the
    # context conflict prevents a positive CLEAR decision.
    start = header_rows[0][1] + 1
    end = header_rows[1][1] if len(header_rows) > 1 else len(lines)
    inline = header_rows[0][3]
    source_values: Dict[str, List[int]] = {"OSPFv3": [], "BGPv6": []}
    normalized_values: Dict[str, List[int]] = {}
    aggregate_counts: List[int] = []
    grammar_rows = 0
    hard_rejected = False

    def record(label: str, count_text: str) -> None:
        nonlocal grammar_rows, hard_rejected
        low = re.sub(r"\s+", " ", label.strip().casefold())
        try:
            count = int(count_text)
        except ValueError:
            hard_rejected = True
            return
        if count > _MAX_ACTIVE_ROUTES:
            hard_rejected = True
            return
        if low == "total":
            return
        protocol = ""
        normalized_source = ""
        if re.fullmatch(r"(?:ospf|ospfv3)(?:\s+[A-Za-z0-9_.-]{1,32})?", low):
            protocol = "OSPFv3"
            normalized_source = "ospfv3"
        elif low.startswith(("ospf", "ospfv3")):
            hard_rejected = True
            return
        else:
            bgp_match = re.fullmatch(r"bgp(?:\s+(\S{1,16}))?", low)
            if bgp_match and (
                    not bgp_match.group(1)
                    or _canonical_as(bgp_match.group(1))):
                protocol = "BGPv6"
                normalized_source = "bgpv6"
            elif low.startswith("bgp"):
                hard_rejected = True
                return
        if not protocol:
            neutral = low if low in _ROUTE_NEUTRAL_SOURCES else ""
            tagged = re.fullmatch(
                r"(rip|ripng|isis|is-is|eigrp)\s+[A-Za-z0-9_.-]{1,32}",
                low,
            )
            if tagged:
                neutral = tagged.group(1)
            if not neutral:
                hard_rejected = True
                return
            normalized_source = neutral
        grammar_rows += 1
        aggregate_counts.append(count)
        normalized_values.setdefault(normalized_source, []).append(count)
        if protocol:
            source_values[protocol].append(count)

    def number_first_list(text: str) -> bool:
        nonlocal hard_rejected
        pieces = text.split(",")
        matches = [re.fullmatch(
            r"\s*(\d{1,10})\s+([A-Za-z][A-Za-z0-9_. /-]{0,63})\s*",
            piece,
        ) for piece in pieces]
        if not pieces or not all(matches):
            hard_rejected = True
            return False
        for match in matches:
            assert match is not None
            record(match.group(2), match.group(1))
        return True

    grammar_proof = False
    if inline:
        grammar_proof = number_first_list(inline.lstrip(":").strip())

    column_header = False
    for raw in lines[start:end]:
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(
                r"Route\s+Source\s+Networks\s+Subnets\s+Overhead\s+"
                r"Memory(?:\s+\(bytes\))?", line, re.IGNORECASE):
            column_header = True
            continue
        colon = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_. /-]{0,63})\s*:\s*(\d{1,10})"
            r"(?:\s+\(\d{1,10}\s+(?:subnets?|total)\))?\s*",
            line, re.IGNORECASE,
        )
        if colon:
            record(colon.group(1), colon.group(2))
            grammar_proof = True
            continue
        column = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_. /-]{0,63})\s+(\d{1,10})\s+"
            r"\d{1,10}\s+\d{1,10}\s+\d{1,10}\s*",
            line, re.IGNORECASE,
        )
        if column and column_header:
            record(column.group(1), column.group(2))
            grammar_proof = True
            continue
        # IOS also emits the number-first census after the ordinary (non-
        # ``Summary``) table header.  Route-list rows do not match this exact
        # comma-separated grammar, so accepting it does not turn a generic RIB
        # listing into a census.
        if re.match(r"^\d+\s+", line):
            grammar_proof = number_first_list(line) or grammar_proof

    duplicates = any(len(values) > 1 for values in normalized_values.values())
    conflicts = any(len(set(values)) > 1 for values in source_values.values())
    counts = {
        protocol: (values[0] if values else 0)
        for protocol, values in source_values.items()
    }
    aggregate_overflow = sum(aggregate_counts) > _MAX_ACTIVE_ROUTES
    if hard_rejected or not grammar_proof or not grammar_rows or aggregate_overflow:
        return dict(
            empty, parser_status="rejected", candidate_count=1,
            rejected_count=1, header=bool(header_rows),
            finding_codes=["route_census_rejected"],
        )

    ambiguity = duplicates or conflicts
    rejected_count = int(context_review) + int(ambiguity)
    review = context_review or ambiguity
    codes = ["route_context_review"] if context_review else []
    if ambiguity:
        codes.append("route_census_conflict")
    return {
        "parser_status": "review" if review else "complete",
        "candidate_count": min(1 + rejected_count, _MAX_CANDIDATES),
        "parsed_count": 1,
        "rejected_count": min(rejected_count, _MAX_CANDIDATES),
        "counts": counts, "header": True,
        "finding_codes": sorted(set(codes)),
    }


def _ospf_process_context(body: str) -> Tuple[str, bool, bool]:
    processes = set()
    named_context = False
    non_ipv6_af = False
    patterns = (
        re.compile(r"\bOSPFv3\s+(?:Process\s+ID\s+)?([A-Za-z0-9_.-]+)", re.I),
        re.compile(r"\bRouting Process\s+\"?ospfv3\s+([A-Za-z0-9_.-]+)", re.I),
    )
    for line in body.splitlines():
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                token = match.group(1)
                if token.casefold() not in {"neighbor", "neighbors"}:
                    processes.add(token)
                break
        vrf = re.search(r"\bVRF\s+[\"']?([A-Za-z0-9_.-]+)", line, re.I)
        if vrf and vrf.group(1).casefold() not in {"default", "global"}:
            named_context = True
        af = re.search(r"\baddress-family\s+(\S+)", line, re.I)
        if af and af.group(1).casefold() != "ipv6":
            non_ipv6_af = True
    process = sorted(processes, key=lambda value: (value.casefold(), value))[0] \
        if processes else ""
    return process, len(processes) > 1 or named_context or non_ipv6_af, bool(processes)


def _valid_ospf_dead_time(value: str) -> bool:
    match = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2})", value)
    return bool(match and int(match.group(2)) < 60 and int(match.group(3)) < 60)


def _valid_decimal(value: str, maximum: int) -> bool:
    return bool(
        re.fullmatch(rf"\d{{1,{len(str(maximum))}}}", value)
        and int(value) <= maximum
    )


def _valid_bgp_up_down(value: str) -> bool:
    if value.casefold() == "never":
        return True
    clock = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})", value)
    if clock:
        hours, minutes, seconds = (int(part) for part in clock.groups())
        return hours < 24 and minutes < 60 and seconds < 60
    compact = re.fullmatch(
        r"(\d{1,3})([ywdhms])(?:([0-9]{1,2})([wdhms]))?",
        value, re.IGNORECASE,
    )
    if not compact:
        return False
    _first, first_unit, second, second_unit = compact.groups()
    if not second_unit:
        return True
    subordinate = {
        "y": ("w", 52), "w": ("d", 6), "d": ("h", 23),
        "h": ("m", 59), "m": ("s", 59),
    }
    expected = subordinate.get(first_unit.casefold())
    return bool(
        expected and second_unit.casefold() == expected[0]
        and second is not None and int(second) <= expected[1]
    )


def _canonical_bgp_state(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value.strip()).casefold()
    states = {
        "idle": "IDLE",
        "idle (admin)": "IDLE(ADMIN)",
        "idle(admin)": "IDLE(ADMIN)",
        "idle (admin-shut)": "IDLE(ADMIN-SHUT)",
        "idle(admin-shut)": "IDLE(ADMIN-SHUT)",
        "connect": "CONNECT",
        "active": "ACTIVE",
        "opensent": "OPENSENT",
        "openconfirm": "OPENCONFIRM",
    }
    return states.get(collapsed, "")


def _parse_ospfv3(body: str) -> dict:
    empty = {
        "parser_status": "not_verified", "candidate_count": 0,
        "parsed_count": 0, "rejected_count": 0, "rows": [],
        "header": False, "finding_codes": [],
    }
    if not isinstance(body, str) or not body.strip():
        return empty
    if len(body) > _MAX_BODY_CHARS or len(body.splitlines()) > _MAX_LINES:
        return dict(empty, parser_status="rejected", rejected_count=1,
                    finding_codes=["ospfv3_parser_rejected"])
    process, context_review, process_present = _ospf_process_context(body)
    header_re = re.compile(
        r"^\s*Neighbor\s+ID\s+Pri\s+State\s+Dead\s+Time\s+"
        r"Interface\s+ID\s+Interface\s*$", re.IGNORECASE)
    header_count = sum(bool(header_re.fullmatch(line)) for line in body.splitlines())
    header = header_count == 1
    context_review = context_review or header_count > 1
    rows: List[dict] = []
    candidate_count = rejected_count = 0
    duplicate = False
    identities: Dict[str, dict] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}\s+", line):
            continue
        candidate_count += 1
        if candidate_count > _MAX_CANDIDATES:
            return dict(empty, parser_status="rejected",
                        candidate_count=_MAX_CANDIDATES,
                        rejected_count=_MAX_CANDIDATES,
                        header=header,
                        finding_codes=["ospfv3_candidate_cap_exceeded"])
        match = re.fullmatch(
            r"^(\S+)\s+(\d+)\s+([A-Za-z0-9_-]+)\s*/\s*"
            r"([A-Za-z0-9_-]+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", line,
        )
        if not match:
            rejected_count += 1
            continue
        peer_raw, priority, state_raw, role, dead_time, interface_id, interface = (
            match.groups())
        try:
            peer = str(ipaddress.IPv4Address(peer_raw))
        except ValueError:
            rejected_count += 1
            continue
        if not re.fullmatch(r"\d{1,5}", priority) or int(priority) > 65_535 \
                or not _valid_ospf_dead_time(dead_time) \
                or not re.fullmatch(r"\d{1,10}", interface_id) \
                or int(interface_id) > _MAX_ACTIVE_ROUTES:
            rejected_count += 1
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9./:_-]{0,127}", interface):
            rejected_count += 1
            continue
        state = state_raw.upper()
        role = role.upper()
        identity = (
            f"ospfv3|default|{process.casefold() or '-'}|"
            f"{peer}|{interface.casefold()}"
        )
        row = {
            "process": process, "peer": peer, "peer_key": identity,
            "interface": interface, "remote_as": "", "role": role,
            "state_raw": f"{state_raw}/{role}", "state": state,
            "prefix_count": 0, "prefix_count_present": False,
        }
        prior = identities.get(identity)
        if prior is not None:
            duplicate = True
            rejected_count += 1
            # Retain the most conservative observable state under the one
            # identity rather than emitting duplicate owner rows.
            def rank(item: dict) -> int:
                return 0 if item["state"] in _OSPF_DEGRADED else (
                    1 if item["state"] not in _OSPF_HEALTHY else 2)
            if rank(row) < rank(prior):
                identities[identity] = row
            continue
        identities[identity] = row
    rows = list(identities.values())
    if rows and not header:
        rejected_count += 1
    if context_review:
        rejected_count += 1
    if len(rows) + rejected_count > _MAX_CANDIDATES:
        return dict(empty, parser_status="rejected",
                    candidate_count=_MAX_CANDIDATES,
                    rejected_count=_MAX_CANDIDATES, header=header,
                    finding_codes=["ospfv3_candidate_cap_exceeded"])
    review = context_review or duplicate or rejected_count > 0
    codes = []
    if context_review:
        codes.append("ospfv3_context_review")
    if duplicate:
        codes.append("ospfv3_duplicate_identity")
    if rejected_count and not duplicate:
        codes.append("ospfv3_candidate_rejected")
    parser_status = (
        "review" if rows and review else
        "complete" if rows else
        "rejected" if rejected_count else
        "complete" if header else "rejected"
    )
    if parser_status == "rejected" and not codes:
        codes.append("ospfv3_parser_rejected")
        rejected_count = max(1, rejected_count)
    return {
        "parser_status": parser_status,
        "candidate_count": len(rows) + rejected_count,
        "parsed_count": len(rows), "rejected_count": rejected_count,
        "rows": rows, "header": header,
        "finding_codes": sorted(set(codes)),
    }


def _parse_bgpv6(body: str) -> dict:
    empty = {
        "parser_status": "not_verified", "candidate_count": 0,
        "parsed_count": 0, "rejected_count": 0, "rows": [],
        "header": False, "finding_codes": [],
    }
    if not isinstance(body, str) or not body.strip():
        return empty
    lines = body.splitlines()
    if len(body) > _MAX_BODY_CHARS or len(lines) > _MAX_LINES:
        return dict(empty, parser_status="rejected", rejected_count=1,
                    finding_codes=["bgpv6_parser_rejected"])
    header_re = re.compile(
        r"^\s*Neighbor\s+V\s+AS\s+MsgRcvd\s+MsgSent\s+TblVer\s+"
        r"InQ\s+OutQ\s+Up/Down\s+State/PfxRcd\s*$",
        re.IGNORECASE,
    )
    header_count = sum(bool(header_re.fullmatch(line)) for line in lines)
    header = header_count == 1

    process_matches = list(re.finditer(
        r"(?im)^\s*BGP router identifier\b.*?local AS number\s+(\S+)", body))
    processes = [
        canonical for match in process_matches
        if (canonical := _canonical_as(match.group(1)))
    ]
    process = processes[0] if processes else ""

    nx_context_re = re.compile(
        r"^\s*BGP summary information for VRF\s+"
        r"(?P<vrf>\"[^\"]{1,128}\"|'[^']{1,128}'|[A-Za-z0-9_.-]{1,128})"
        r"\s*,\s*address family\s+(?P<af>[A-Za-z0-9_. -]{1,64})\s*$",
        re.IGNORECASE,
    )
    nx_contexts = []
    nx_context_lines = 0
    for line in lines:
        if re.match(r"^\s*BGP summary information for VRF\b", line,
                    re.IGNORECASE):
            nx_context_lines += 1
        match = nx_context_re.fullmatch(line)
        if match:
            vrf = match.group("vrf").strip("\"'").casefold()
            af = re.sub(r"\s+", " ", match.group("af").strip()).casefold()
            nx_contexts.append((vrf, af))
    context_review = bool(
        header_count > 1
        or nx_context_lines != len(nx_contexts)
        or len(process_matches) != len(processes)
        or len(set(processes)) > 1
        or len(nx_contexts) > 1
        or any(vrf not in {"default", "global"} or af != "ipv6 unicast"
               for vrf, af in nx_contexts)
        or re.search(
            r"(?im)^\s*(?:VRF|Routing instance)\s*[: ]\s*"
            r"(?!default\b|global\b)\S+",
            body,
        )
    )

    logical: List[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if re.fullmatch(r"[0-9A-Fa-f:.]+(?:%[A-Za-z0-9_.:/-]+)?", stripped) \
                and index + 1 < len(lines):
            following = lines[index + 1].strip()
            if following and re.match(r"^\d+\s+\S+(?:\s+|$)", following):
                logical.append(stripped + " " + following)
                index += 2
                continue
        logical.append(stripped)
        index += 1

    identities: Dict[str, dict] = {}
    candidate_count = rejected_count = 0
    duplicate = False
    for line in logical:
        if not line:
            continue
        tokens = line.split()
        first = tokens[0]
        # Count both IPv4 and IPv6-looking table candidates so a wrong-family
        # row cannot silently disappear from an IPv6 receipt.
        try:
            ipaddress.ip_address(first.partition("%")[0])
        except ValueError:
            if re.match(r"^[0-9A-Fa-f][^\s]*:", first):
                candidate_count += 1
                rejected_count += 1
            continue
        candidate_count += 1
        if candidate_count > _MAX_CANDIDATES:
            return dict(empty, parser_status="rejected",
                        candidate_count=_MAX_CANDIDATES,
                        rejected_count=_MAX_CANDIDATES,
                        header=header,
                        finding_codes=["bgpv6_candidate_cap_exceeded"])
        if len(tokens) not in {10, 11}:
            rejected_count += 1
            continue
        peer, zone = _canonical_ipv6(tokens[0])
        remote_as = _canonical_as(tokens[2])
        if not peer or tokens[1] != "4" or not remote_as:
            rejected_count += 1
            continue
        if not all(_valid_decimal(token, _MAX_BGP_COUNTER)
                   for token in tokens[3:8]) \
                or not _valid_bgp_up_down(tokens[8]):
            rejected_count += 1
            continue
        state_tokens = tokens[9:]
        state_raw = " ".join(state_tokens)
        prefix_present = _valid_decimal(state_raw, _MAX_ACTIVE_ROUTES)
        if prefix_present:
            prefix_count = int(state_raw)
            if tokens[8].casefold() == "never":
                rejected_count += 1
                continue
            state = "ESTABLISHED"
        else:
            prefix_count = 0
            state = _canonical_bgp_state(state_raw)
            if not state:
                rejected_count += 1
                continue
        identity = f"bgpv6|default|{peer.casefold()}"
        row = {
            "process": process, "peer": peer, "peer_key": identity,
            "interface": zone, "remote_as": remote_as, "role": "",
            "state_raw": state_raw, "state": state,
            "prefix_count": prefix_count,
            "prefix_count_present": prefix_present,
        }
        prior = identities.get(identity)
        if prior is not None:
            duplicate = True
            rejected_count += 1
            def rank(item: dict) -> int:
                return 0 if item["state"] in _BGP_DEGRADED else (
                    2 if item["state"] == "ESTABLISHED" else 1)
            if rank(row) < rank(prior):
                identities[identity] = row
            continue
        identities[identity] = row
    rows = list(identities.values())
    malformed = rejected_count > int(duplicate)
    if rows and not header:
        rejected_count += 1
        malformed = True
    if context_review:
        rejected_count += 1
    if len(rows) + rejected_count > _MAX_CANDIDATES:
        return dict(empty, parser_status="rejected",
                    candidate_count=_MAX_CANDIDATES,
                    rejected_count=_MAX_CANDIDATES, header=header,
                    finding_codes=["bgpv6_candidate_cap_exceeded"])
    review = context_review or duplicate or rejected_count > 0
    codes = []
    if context_review:
        codes.append("bgpv6_context_review")
    if duplicate:
        codes.append("bgpv6_duplicate_identity")
    if malformed or (rows and not header):
        codes.append("bgpv6_candidate_rejected")
    parser_status = (
        "review" if context_review and (header_count or nx_contexts) else
        "review" if rows and review else
        "complete" if rows else
        "rejected" if rejected_count else
        "complete" if header else "rejected"
    )
    if parser_status == "rejected" and not codes:
        codes.append("bgpv6_parser_rejected")
        rejected_count = max(1, rejected_count)
    return {
        "parser_status": parser_status,
        "candidate_count": len(rows) + rejected_count,
        "parsed_count": len(rows), "rejected_count": rejected_count,
        "rows": rows, "header": header,
        "finding_codes": sorted(set(codes)),
    }


def _parse_family(input_name: str, body: str) -> dict:
    return _parse_ospfv3(body) if input_name == "ospfv3_neighbors" \
        else _parse_bgpv6(body)


def _parser_projection(parsed: dict) -> dict:
    return {
        "rows": parsed.get("rows", []), "header": parsed.get("header", False),
        "parser_status": parsed.get("parser_status"),
        "candidate_count": parsed.get("candidate_count", 0),
        "parsed_count": parsed.get("parsed_count", 0),
        "rejected_count": parsed.get("rejected_count", 0),
    }


def _select_capture(host: str, platform: str, input_name: str, mapping: dict,
                    inspections: Dict[Tuple[str, str], str], duplicates: set,
                    budget: Optional[List[int]] = None) -> dict:
    candidates = []
    for command in _commands(platform, input_name):
        if command not in mapping:
            continue
        body, read_status = _read_path(
            mapping.get(command), budget, command=command)
        status = _capture_status(
            inspections, duplicates, host, command, True, read_status)
        candidates.append((command, body, status))
    if not candidates:
        return {
            "command": _commands(platform, input_name)[0], "body": "",
            "capture_status": "not_observed", "parser": None,
            "variant_conflict": False,
        }
    selected = next((item for item in candidates if item[2] == "ok"), candidates[0])
    command, body, status = selected
    parser = None
    conflict = False
    if status == "ok":
        parser = _parse_route_summary(body) if input_name == "route_summary" \
            else _parse_family(input_name, body)
        comparable = []
        for other_command, other_body, other_status in candidates:
            if other_status != "ok":
                continue
            other = _parse_route_summary(other_body) \
                if input_name == "route_summary" else \
                _parse_family(input_name, other_body)
            comparable.append(_parser_projection(other) if input_name != "route_summary" else {
                key: other[key] for key in (
                    "parser_status", "candidate_count", "parsed_count",
                    "rejected_count", "counts", "header",
                )
            })
        conflict = len({_sha(item) for item in comparable}) > 1
        if conflict:
            parser = dict(parser)
            parser["parser_status"] = "review"
            parser["rejected_count"] = max(1, parser.get("rejected_count", 0))
            parser["candidate_count"] = (
                parser.get("parsed_count", 0) + parser["rejected_count"])
            parser["finding_codes"] = sorted(set(
                parser.get("finding_codes", []) + ["command_variant_conflict"]
            ))
    return {
        "command": command, "body": body, "capture_status": status,
        "parser": parser, "variant_conflict": conflict,
    }


def compute_ipv6_routing_adjacency_baseline(
        all_cmd_to_files: Any, capture_integrity: Any, devices: Any = None) -> dict:
    """Compute the current-run, source-bound IPv6 adjacency baseline."""
    return _compute_ipv6_routing_adjacency_baseline(
        all_cmd_to_files, capture_integrity, devices)


def validate_ipv6_routing_adjacency_baseline(
        value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the closed receipt and optionally require current-run custody."""
    return _validate_ipv6_routing_adjacency_baseline(
        value, require_current_run=require_current_run)


def embedded_ipv6_routing_adjacency_baseline(value: Any) -> dict:
    """Return the JSON-safe audit projection, with current-run authority erased."""
    return _embedded_ipv6_routing_adjacency_baseline(value)


def compute_ipv6_routing_subject_scope(
        all_cmd_to_files: Any, devices: Any = None) -> dict:
    """Return the path-free, blocker-only IPv6 routing subject scope."""
    return _compute_ipv6_routing_subject_scope(all_cmd_to_files, devices)


_CODE_INFO = {
    "ospfv3_state_degraded": (
        "degraded", "The observed OSPFv3 adjacency is in a known transient or down state."),
    "bgpv6_state_degraded": (
        "degraded", "The observed BGPv6 peer is in a known non-Established FSM state."),
    "ospfv3_state_review": (
        "review", "The observed OSPFv3 state is outside the bounded state vocabulary."),
    "bgpv6_state_review": (
        "review", "The observed BGPv6 state is outside the bounded state vocabulary."),
    "family_capture_not_verified": (
        "not_verified", "The selected protocol-family capture did not have one integrity-ok inspection receipt."),
    "family_parser_not_verified": (
        "not_verified", "The selected protocol-family capture did not yield a usable bounded adjacency projection."),
    "family_parser_review": (
        "review", "The selected protocol-family capture has rejected, duplicate, conflicting, or non-default context."),
    "route_census_not_verified": (
        "not_verified", "No integrity-ok, parse-complete default/global IPv6 route-summary census is bound to this row."),
    "positive_route_source_without_runtime_rows": (
        "not_verified", "The IPv6 route census positively identifies this protocol but no usable runtime adjacency row was observed."),
    "runtime_adjacency_not_verified": (
        "not_verified", "Positive protocol-family evidence was observed without a usable runtime adjacency row."),
    "command_variant_conflict": (
        "review", "Multiple integrity-ok command variants produced conflicting normalized projections."),
    "route_context_review": (
        "review", "The IPv6 route-summary capture contains multiple or non-default routing contexts."),
    "route_census_conflict": (
        "review", "The IPv6 route-summary capture reports conflicting dynamic-route source counts."),
    "route_census_rejected": (
        "not_verified", "The IPv6 route-summary capture did not yield a bounded default/global census."),
    "ospfv3_context_review": (
        "review", "The OSPFv3 capture contains multiple process, VRF, or address-family contexts."),
    "ospfv3_duplicate_identity": (
        "review", "The OSPFv3 capture repeats one normalized adjacency identity."),
    "ospfv3_candidate_rejected": (
        "review", "At least one OSPFv3 neighbor-shaped row failed bounded validation."),
    "ospfv3_parser_rejected": (
        "not_verified", "The OSPFv3 capture did not yield a bounded runtime adjacency projection."),
    "ospfv3_candidate_cap_exceeded": (
        "not_verified", "The OSPFv3 capture exceeded the bounded candidate denominator."),
    "bgpv6_context_review": (
        "review", "The BGPv6 capture contains multiple or non-default routing contexts."),
    "bgpv6_duplicate_identity": (
        "review", "The BGPv6 capture repeats one normalized peer identity."),
    "bgpv6_candidate_rejected": (
        "review", "At least one BGP neighbor-shaped row failed IPv6 peer or autonomous-system validation."),
    "bgpv6_parser_rejected": (
        "not_verified", "The BGPv6 capture did not yield a bounded runtime peer projection."),
    "bgpv6_candidate_cap_exceeded": (
        "not_verified", "The BGPv6 capture exceeded the bounded candidate denominator."),
}


def _findings(codes: Iterable[str]) -> List[dict]:
    rows = []
    for code in sorted(set(codes)):
        detail = _CODE_INFO.get(code)
        if detail:
            rows.append(_finding(detail[0], code, detail[1]))
    return rows[:_MAX_FINDINGS_PER_ROW]


def _base_row_status(protocol: str, state: str) -> Tuple[str, str]:
    if protocol == "OSPFv3":
        if state in _OSPF_HEALTHY:
            return "assessed", ""
        if state in _OSPF_DEGRADED:
            return "degraded", "ospfv3_state_degraded"
        return "review", "ospfv3_state_review"
    if state == "ESTABLISHED":
        return "assessed", ""
    if state in _BGP_DEGRADED:
        return "degraded", "bgpv6_state_degraded"
    return "review", "bgpv6_state_review"


def _row_semantics(row: dict, family_cell: dict, route_cell: dict,
                   *, static: bool = False) -> Tuple[str, List[dict]]:
    codes: List[str] = []
    if static:
        if family_cell["capture_status"] != "ok":
            codes.append("family_capture_not_verified")
            status = "not_verified"
        elif family_cell["parser_status"] == "review":
            codes.extend(family_cell.get("_parser_codes", []))
            codes.append("family_parser_review")
            status = "review"
        elif family_cell["parser_status"] != "complete":
            codes.append("family_parser_not_verified")
            status = "not_verified"
        elif family_cell["active_route_count"] > 0:
            codes.append("positive_route_source_without_runtime_rows")
            status = "not_verified"
        else:
            codes.append("runtime_adjacency_not_verified")
            status = "not_verified"
        return status, _findings(codes)

    status, state_code = _base_row_status(row["protocol"], row["state"])
    if state_code:
        codes.append(state_code)
    if family_cell["capture_status"] != "ok":
        codes.append("family_capture_not_verified")
        if status == "assessed":
            status = "not_verified"
    elif family_cell["parser_status"] == "review":
        codes.extend(family_cell.get("_parser_codes", []))
        codes.append("family_parser_review")
        if status == "assessed":
            status = "review"
    elif family_cell["parser_status"] != "complete":
        codes.append("family_parser_not_verified")
        if status == "assessed":
            status = "not_verified"
    route_usable = (
        route_cell["capture_status"] == "ok"
        and route_cell["parser_status"] == "complete"
    )
    if not route_usable:
        codes.append("route_census_not_verified")
        if status == "assessed":
            status = "not_verified"
    return status, _findings(codes)


def _acceptance(row: dict) -> str:
    host, protocol = row["switch"], row["protocol"]
    if row["status"] == "not_verified":
        return (
            "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER: No integrity-complete, "
            f"parse-complete default/global {protocol} runtime adjacency baseline is authorized "
            f"for {host}. Re-collect the selected family command and show ipv6 route summary; "
            "an absent row is not proof of absence and is not acceptance."
        )
    observed = (
        f"Observed {protocol} runtime adjacency on {host}: peer {row['peer']}, "
        f"state {row['state_raw']}"
    )
    if row["interface"]:
        observed += f", interface {row['interface']}"
    if row["remote_as"]:
        observed += f", remote AS {row['remote_as']}"
    if row["prefix_count_present"]:
        observed += f", observed PfxRcd {row['prefix_count']}"
    observed += "."
    if row["status"] == "degraded":
        return (
            "PRE-CUTOVER DEGRADED — BLOCKER: " + observed +
            " Matching this degraded observation after cutover is NOT ACCEPTANCE; resolve or "
            "explicitly disposition it before the window."
        )
    if row["status"] == "review":
        return (
            "PRE-CUTOVER REVIEW — BLOCKER: " + observed +
            " Live simultaneous verification and explicit disposition are required before "
            "this adjacency can be used for acceptance."
        )
    return (
        observed + " Preserve the normalized peer identity and settled state or explicitly "
        "explain the change. The denominator is observed runtime adjacencies, not configured "
        "or expected peers; BGP prefix counts are informational and are not pinned targets."
    )


def _source_key(family_command: str) -> str:
    return (
        f"{family_command}#default_ipv6_runtime_adjacencies+"
        f"{_ROUTE_COMMAND}#default_ipv6_dynamic_route_census"
    )


def _new_row(host: str, platform: str, protocol: str, command: str,
             facts: Optional[dict] = None) -> dict:
    facts = facts or {}
    return {
        "switch": host, "platform": platform, "protocol": protocol,
        "routing_instance": "default", "process": facts.get("process", ""),
        "peer": facts.get("peer", ""), "peer_key": facts.get("peer_key", ""),
        "interface": facts.get("interface", ""),
        "remote_as": facts.get("remote_as", ""), "role": facts.get("role", ""),
        "state_raw": facts.get("state_raw", "NOT_VERIFIED"),
        "state": facts.get("state", "NOT_VERIFIED"),
        "prefix_count": facts.get("prefix_count", 0),
        "prefix_count_present": facts.get("prefix_count_present", False),
        "status": "not_verified", "command": command, "acceptance": "",
        "source_key": _source_key(command),
        "projection_custody": "current_run_source_bound", "findings": [],
    }


def _coverage_source_payload(cell: dict) -> dict:
    return {
        key: cell[key] for key in _COVERAGE_KEYS
        if key not in {"source_sha256", "projection_sha256"}
    }


def _row_projection(row: dict) -> dict:
    return {
        key: row[key] for key in (
            "switch", "platform", "protocol", "routing_instance", "process",
            "peer", "peer_key", "interface", "remote_as", "role", "state_raw",
            "state", "prefix_count", "prefix_count_present", "status", "findings",
        )
    }


def _coverage_projection_payload(cell: dict, rows: Sequence[dict]) -> dict:
    projected = [] if cell["input"] == "route_summary" else [
        _row_projection(row) for row in rows if row["switch"] == cell["switch"]
        and row["protocol"] == cell["protocol"]
    ]
    return {
        "switch": cell["switch"], "input": cell["input"],
        "protocol": cell["protocol"], "subject": cell["subject"],
        "status": cell["status"],
        "active_route_count": cell["active_route_count"], "rows": projected,
    }


def _scope_receipt(valid: bool, attempted: bool, reason: str,
                   rows: Optional[List[dict]] = None) -> dict:
    return {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA, "valid": bool(valid),
        "attempted": bool(attempted), "reason": reason,
        "rows": rows if valid else [],
    }


def _compute_ipv6_routing_subject_scope(
        all_cmd_to_files: Any, devices: Any = None) -> dict:
    if not isinstance(all_cmd_to_files, dict):
        return _scope_receipt(False, False, "scope_input_invalid")
    attempted = any(
        isinstance(mapping, dict) and any(command in mapping for command in _RECOGNIZED_COMMANDS)
        for mapping in all_cmd_to_files.values()
    )
    platforms, platform_error = _platforms(devices)
    if platform_error:
        return _scope_receipt(False, attempted, platform_error)
    if len(all_cmd_to_files) > _MAX_HOSTS:
        return _scope_receipt(False, attempted, "scope_host_cap_exceeded")
    hosts: List[str] = []
    for raw_host, mapping in all_cmd_to_files.items():
        if not _safe_ascii_string(raw_host, 128, empty=False):
            return _scope_receipt(False, attempted, "scope_identity_invalid")
        if not isinstance(mapping, dict):
            return _scope_receipt(False, attempted, "scope_input_invalid")
        hosts.append(raw_host)
    identities = set(hosts) | set(platforms)
    if len(identities) > _MAX_HOSTS:
        return _scope_receipt(False, attempted, "scope_host_cap_exceeded")
    if _has_casefold_collision(identities):
        return _scope_receipt(False, attempted, "scope_identity_collision")
    if not attempted:
        return _scope_receipt(True, False, "ok", [])

    budget = [0]
    rows = []
    for host in sorted(set(hosts), key=lambda item: (item.casefold(), item)):
        mapping = all_cmd_to_files[host]
        protocols = set()
        for command in sorted(
                (key for key in mapping if key in _RECOGNIZED_COMMANDS),
                key=lambda item: item.casefold()):
            body, status = _read_path(
                mapping.get(command), budget, command=command)
            if status in {"unreadable", "incomplete"}:
                return _scope_receipt(False, True, "scope_evidence_rejected")
            if status in {"empty", "error"}:
                continue
            if command == _ROUTE_COMMAND:
                parsed = _parse_route_summary(body)
                if parsed["parser_status"] == "rejected":
                    return _scope_receipt(False, True, "scope_evidence_rejected")
                protocols.update(
                    protocol for protocol, count in parsed["counts"].items() if count > 0)
            elif command in _BGP_COMMANDS:
                parsed = _parse_bgpv6(body)
                if parsed["parser_status"] == "rejected":
                    return _scope_receipt(False, True, "scope_evidence_rejected")
                if parsed["header"] or parsed["candidate_count"] or parsed["rows"]:
                    protocols.add("BGPv6")
            else:
                parsed = _parse_ospfv3(body)
                if parsed["parser_status"] == "rejected":
                    return _scope_receipt(False, True, "scope_evidence_rejected")
                if parsed["header"] or parsed["candidate_count"] or parsed["rows"]:
                    protocols.add("OSPFv3")
        ordered = [protocol for protocol in ("OSPFv3", "BGPv6") if protocol in protocols]
        if ordered:
            rows.append({
                "switch": host, "platform": platforms.get(host, ""),
                "protocols": ordered,
            })
    return _scope_receipt(True, True, "ok", rows)


class _CurrentRunIpv6RoutingAdjacencyBaseline(dict):
    """Process-local marker whose original semantic digest cannot be re-sealed."""

    def __init__(self, value: dict):
        super().__init__(value)
        self._original_digest = value.get("summary", {}).get("baseline_sha256", "")

    def __copy__(self):
        return _embed_plain(self)

    def __deepcopy__(self, memo):
        result = _embed_plain(self)
        memo[id(self)] = result
        return result

    def __reduce_ex__(self, protocol):
        # Serialization is an external custody boundary.  Rehydrate only an
        # ordinary embedded receipt, never this process-local authority marker.
        return dict, (_embed_plain(self),)


def _compute_ipv6_routing_adjacency_baseline(
        all_cmd_to_files: Any, capture_integrity: Any, devices: Any = None) -> dict:
    if not isinstance(all_cmd_to_files, dict):
        return _unavailable_baseline()
    scope_receipt = _compute_ipv6_routing_subject_scope(all_cmd_to_files, devices)
    if not scope_receipt["valid"]:
        return _unavailable_baseline()
    platforms, error = _platforms(devices)
    if error:
        return _unavailable_baseline()
    host_names = set(platforms)
    for host, mapping in all_cmd_to_files.items():
        if not _safe_ascii_string(host, 128, empty=False) \
                or not isinstance(mapping, dict):
            return _unavailable_baseline()
        host_names.add(host)
    if len(host_names) > _MAX_HOSTS or _has_casefold_collision(host_names):
        return _unavailable_baseline()
    scope_protocols = {
        row["switch"]: set(row["protocols"]) for row in scope_receipt["rows"]
    }
    inspections, duplicates = _inspection_index(capture_integrity)
    budget = [0]
    all_rows: List[dict] = []
    all_cells: List[dict] = []

    for host in sorted(host_names, key=lambda item: (item.casefold(), item)):
        platform = platforms.get(host, "")
        mapping = all_cmd_to_files.get(host, {})
        route_selected = _select_capture(
            host, platform, "route_summary", mapping, inspections, duplicates, budget)
        route_parser = route_selected["parser"] or {
            "parser_status": "not_verified", "candidate_count": 0,
            "parsed_count": 0, "rejected_count": 0,
            "counts": {"OSPFv3": 0, "BGPv6": 0}, "finding_codes": [],
        }
        route_counts = route_parser.get("counts", {"OSPFv3": 0, "BGPv6": 0})
        family_selected = {
            "OSPFv3": _select_capture(
                host, platform, "ospfv3_neighbors", mapping,
                inspections, duplicates, budget),
            "BGPv6": _select_capture(
                host, platform, "bgp_ipv6_neighbors", mapping,
                inspections, duplicates, budget),
        }
        family_cells: Dict[str, dict] = {}
        host_rows: List[dict] = []
        family_subjects: Dict[str, bool] = {}
        for protocol, input_name in (
                ("OSPFv3", "ospfv3_neighbors"),
                ("BGPv6", "bgp_ipv6_neighbors")):
            selected = family_selected[protocol]
            parsed = selected["parser"] or {
                "parser_status": "not_verified", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 0, "rows": [],
                "header": False, "finding_codes": [],
            }
            subject = bool(
                protocol in scope_protocols.get(host, set())
                or parsed.get("rows") or parsed.get("header")
                or route_counts.get(protocol, 0) > 0
            )
            family_subjects[protocol] = subject
            cell = {
                "switch": host, "platform": platform, "input": input_name,
                "protocol": protocol, "subject": subject,
                "status": "not_applicable",
                "selected_command": selected["command"],
                "capture_status": selected["capture_status"],
                "parser_status": parsed["parser_status"],
                "candidate_count": parsed["candidate_count"],
                "parsed_count": parsed["parsed_count"],
                "rejected_count": parsed["rejected_count"],
                "active_route_count": int(route_counts.get(protocol, 0)),
                "source_sha256": "", "projection_sha256": "",
                "finding_codes": [],
                "_parser_codes": list(parsed.get("finding_codes", [])),
            }
            family_cells[protocol] = cell
            if not subject:
                continue
            facts_rows = parsed.get("rows", []) \
                if selected["capture_status"] == "ok" else []
            if facts_rows:
                for facts in facts_rows:
                    row = _new_row(host, platform, protocol, selected["command"], facts)
                    status, findings = _row_semantics(row, cell, {
                        "capture_status": route_selected["capture_status"],
                        "parser_status": route_parser["parser_status"],
                    })
                    row["status"], row["findings"] = status, findings
                    row["acceptance"] = _acceptance(row)
                    host_rows.append(row)
            else:
                row = _new_row(host, platform, protocol, selected["command"])
                status, findings = _row_semantics(row, cell, {
                    "capture_status": route_selected["capture_status"],
                    "parser_status": route_parser["parser_status"],
                }, static=True)
                row["status"], row["findings"] = status, findings
                row["acceptance"] = _acceptance(row)
                host_rows.append(row)

        route_subject = any(family_subjects.values())
        route_codes = list(route_parser.get("finding_codes", []))
        if route_subject and (
                route_selected["capture_status"] != "ok"
                or route_parser["parser_status"] not in {"complete", "review"}):
            route_codes.append("route_census_not_verified")
        route_status = "not_applicable"
        if route_subject:
            route_status = "assessed" if (
                route_selected["capture_status"] == "ok"
                and route_parser["parser_status"] == "complete"
            ) else ("review" if route_selected["capture_status"] == "ok"
                    and route_parser["parser_status"] == "review" else "not_verified")
        route_cell = {
            "switch": host, "platform": platform, "input": "route_summary",
            "protocol": "IPv6", "subject": route_subject, "status": route_status,
            "selected_command": route_selected["command"],
            "capture_status": route_selected["capture_status"],
            "parser_status": route_parser["parser_status"],
            "candidate_count": route_parser["candidate_count"],
            "parsed_count": route_parser["parsed_count"],
            "rejected_count": route_parser["rejected_count"],
            "active_route_count": sum(int(route_counts.get(protocol, 0))
                                      for protocol in ("OSPFv3", "BGPv6")),
            "source_sha256": "", "projection_sha256": "",
            "finding_codes": sorted(set(route_codes))[:_MAX_FINDINGS_PER_ROW],
        }
        # Route census context can downgrade a healthy row but never erase a
        # definite degraded observation.  Recompute now that the exact route
        # cell is available (the earlier compact view carries the same fields).
        for row in host_rows:
            cell = family_cells[row["protocol"]]
            status, findings = _row_semantics(
                row, cell, route_cell, static=not bool(row["peer_key"]))
            row["status"], row["findings"] = status, findings
            row["acceptance"] = _acceptance(row)
        for protocol, cell in family_cells.items():
            protocol_rows = [row for row in host_rows if row["protocol"] == protocol]
            counts = Counter(row["status"] for row in protocol_rows)
            if not cell["subject"]:
                cell["status"] = "not_applicable"
            elif counts["degraded"]:
                cell["status"] = "degraded"
            elif counts["review"]:
                cell["status"] = "review"
            elif counts["not_verified"]:
                cell["status"] = "not_verified"
            else:
                cell["status"] = "assessed"
            cell["finding_codes"] = sorted({
                finding["code"] for row in protocol_rows
                for finding in row["findings"]
            })[:_MAX_FINDINGS_PER_ROW]
            cell.pop("_parser_codes", None)
        all_rows.extend(host_rows)
        all_cells.extend([route_cell, family_cells["OSPFv3"], family_cells["BGPv6"]])
        if len(all_rows) > _MAX_ROWS:
            return _unavailable_baseline()

    protocol_order = {"OSPFv3": 0, "BGPv6": 1}
    all_rows.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"], protocol_order[row["protocol"]],
        row["peer_key"].casefold(), row["peer_key"],
    ))
    input_order = {name: index for index, (name, _protocol) in enumerate(_INPUTS)}
    all_cells.sort(key=lambda cell: (
        cell["switch"].casefold(), cell["switch"], input_order[cell["input"]],
    ))
    for cell in all_cells:
        cell["source_sha256"] = _sha(_coverage_source_payload(cell))
        cell["projection_sha256"] = _sha(
            _coverage_projection_payload(cell, all_rows))

    global_findings = sorted([
        {
            "switch": row["switch"], "protocol": row["protocol"],
            "peer_key": row["peer_key"], **finding,
        }
        for row in all_rows for finding in row["findings"]
    ], key=lambda item: (
        item["switch"].casefold(), item["switch"],
        protocol_order[item["protocol"]], item["peer_key"].casefold(),
        item["code"], item["issue"],
    ))
    if len(global_findings) > _MAX_ROWS:
        return _unavailable_baseline()
    row_counts = Counter(row["status"] for row in all_rows)
    coverage_counts = Counter(cell["status"] for cell in all_cells)
    if row_counts["degraded"]:
        verdict = "BLOCKED"
    elif row_counts["review"] or row_counts["not_verified"]:
        verdict = "INDETERMINATE"
    elif row_counts["assessed"]:
        verdict = "CLEAR"
    else:
        verdict = "NOT_APPLICABLE"
    assessed = bool(
        verdict in {"CLEAR", "BLOCKED"}
        and not row_counts["review"] and not row_counts["not_verified"]
        and not any(
            finding["kind"] in {"review", "not_verified"}
            for finding in global_findings)
        and all(
            not cell["subject"] or (
                cell["status"] in {"assessed", "degraded"}
                and cell["parser_status"] == "complete")
            for cell in all_cells))
    result = {
        "schema": IPV6_ROUTING_ADJACENCY_SCHEMA, "scope": copy.deepcopy(_SCOPE),
        "verdict": verdict, "assessed": assessed,
        "projection_custody": "current_run_source_bound", "rows": all_rows,
        "coverage": all_cells, "findings": global_findings,
        "summary": {
            "n_hosts": len(host_names),
            "n_subject_hosts": len({
                cell["switch"] for cell in all_cells if cell["subject"]}),
            "n_rows": len(all_rows),
            "n_ospfv3_rows": sum(row["protocol"] == "OSPFv3" for row in all_rows),
            "n_bgpv6_rows": sum(row["protocol"] == "BGPv6" for row in all_rows),
            "n_assessed": row_counts["assessed"],
            "n_degraded": row_counts["degraded"],
            "n_review": row_counts["review"],
            "n_not_verified": row_counts["not_verified"],
            "by_status": {status: int(row_counts[status]) for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
            }, "baseline_sha256": "",
        }, "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    if not result["summary"]["baseline_sha256"]:
        return _unavailable_baseline()
    valid, _reason = _structural_validation(result)
    if not valid:
        return _unavailable_baseline()
    return _CurrentRunIpv6RoutingAdjacencyBaseline(result)


def _bounded_receipt_tree(value: Any) -> bool:
    """Iteratively reject deep/oversized input before copying or JSON encoding."""
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 2_000_000 or depth > 12:
            return False
        if isinstance(item, dict):
            if len(item) > 64:
                return False
            stack.extend((key, depth + 1) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > max(_MAX_ROWS, _MAX_HOSTS * 3):
                return False
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > 2000:
                return False
        elif item is None or type(item) in {bool, int}:
            continue
        else:
            return False
    return True


def _valid_finding(item: Any, *, global_row: bool = False) -> bool:
    keys = {"kind", "code", "issue"} | (
        {"switch", "protocol", "peer_key"} if global_row else set())
    if not isinstance(item, dict) or set(item) != keys:
        return False
    code = item.get("code")
    detail = _CODE_INFO.get(code)
    if not detail or item.get("kind") != detail[0] or item.get("issue") != detail[1]:
        return False
    if global_row and (
            not _safe_ascii_string(item.get("switch"), 128, empty=False)
            or item.get("protocol") not in {"OSPFv3", "BGPv6"}
            or not _safe_ascii_string(item.get("peer_key"), 512)):
        return False
    return True


def _valid_natural(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _validate_row_shape(row: Any, custody: str) -> Tuple[bool, str]:
    if not isinstance(row, dict) or set(row) != _ROW_KEYS:
        return False, "baseline_row_invalid"
    if row.get("protocol") not in {"OSPFv3", "BGPv6"} \
            or row.get("routing_instance") != "default" \
            or row.get("status") not in _ROW_STATUSES \
            or row.get("projection_custody") != custody:
        return False, "baseline_row_scope_or_status_invalid"
    text_limits = {
        "switch": 128, "platform": 80, "protocol": 16,
        "routing_instance": 16, "process": 64, "peer": 160,
        "peer_key": 512, "interface": 128, "remote_as": 16, "role": 32,
        "state_raw": 96, "state": 32, "status": 32, "command": 128,
        "acceptance": 1800, "source_key": 512, "projection_custody": 40,
    }
    if any(not _safe_string(row.get(field), limit)
           for field, limit in text_limits.items()):
        return False, "baseline_row_text_invalid"
    ascii_fields = {
        "switch", "platform", "protocol", "routing_instance", "process",
        "peer", "peer_key", "interface", "remote_as", "role", "state_raw",
        "state", "status", "command", "source_key", "projection_custody",
    }
    if any(not _safe_ascii_string(row.get(field), text_limits[field])
           for field in ascii_fields):
        return False, "baseline_row_text_invalid"
    if not _valid_natural(row.get("prefix_count"), _MAX_ACTIVE_ROUTES) \
            or type(row.get("prefix_count_present")) is not bool:
        return False, "baseline_row_prefix_invalid"
    row_findings = row.get("findings")
    if not isinstance(row_findings, list) or len(row_findings) > _MAX_FINDINGS_PER_ROW \
            or not all(_valid_finding(item) for item in row_findings) \
            or row_findings != sorted(
                row_findings, key=lambda item: (item["code"], item["issue"])):
        return False, "baseline_row_findings_invalid"
    static = not row["peer_key"]
    if static:
        if any(row[field] for field in (
                "process", "peer", "interface", "remote_as", "role")) \
                or row["state_raw"] != "NOT_VERIFIED" \
                or row["state"] != "NOT_VERIFIED" \
                or row["prefix_count"] != 0 or row["prefix_count_present"] \
                or row["status"] not in {"review", "not_verified"}:
            return False, "baseline_static_row_invalid"
    elif row["protocol"] == "OSPFv3":
        try:
            peer = str(ipaddress.IPv4Address(row["peer"]))
        except ValueError:
            return False, "baseline_ospfv3_identity_invalid"
        if peer != row["peer"] or not row["interface"] \
                or (row["process"] and not re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,64}", row["process"])) \
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9./:_-]{0,127}", row["interface"]) \
                or row["remote_as"] or not row["role"] \
                or not re.fullmatch(r"[A-Z0-9_-]{1,32}", row["role"]) \
                or "/" not in row["state_raw"] \
                or row["state_raw"].split("/", 1)[0].upper() != row["state"] \
                or row["state_raw"].split("/", 1)[1] != row["role"] \
                or row["prefix_count"] or row["prefix_count_present"]:
            return False, "baseline_ospfv3_facts_invalid"
        expected_key = (
            f"ospfv3|default|{row['process'].casefold() or '-'}|"
            f"{row['peer']}|{row['interface'].casefold()}"
        )
        if row["peer_key"] != expected_key:
            return False, "baseline_ospfv3_identity_invalid"
    else:
        peer, zone = _canonical_ipv6(row["peer"])
        if not peer or peer != row["peer"] or zone != row["interface"] \
                or not row["remote_as"] \
                or _canonical_as(row["remote_as"]) != row["remote_as"] \
                or (row["process"] and _canonical_as(row["process"]) != row["process"]) \
                or row["role"] or row["peer_key"] != \
                f"bgpv6|default|{row['peer'].casefold()}":
            return False, "baseline_bgpv6_identity_invalid"
        if row["prefix_count_present"]:
            if row["state"] != "ESTABLISHED" \
                    or not re.fullmatch(r"\d+", row["state_raw"]) \
                    or int(row["state_raw"]) != row["prefix_count"]:
                return False, "baseline_bgpv6_state_invalid"
        elif row["prefix_count"] != 0 or row["state"] == "ESTABLISHED" \
                or _canonical_bgp_state(row["state_raw"]) != row["state"]:
            return False, "baseline_bgpv6_state_invalid"
    expected_commands = _commands(
        row["platform"], "ospfv3_neighbors" if row["protocol"] == "OSPFv3"
        else "bgp_ipv6_neighbors")
    if row["command"] not in expected_commands \
            or row["source_key"] != _source_key(row["command"]):
        return False, "baseline_row_source_invalid"
    return True, "ok"


def _validate_coverage_shape(cell: Any) -> Tuple[bool, str]:
    if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
        return False, "baseline_coverage_invalid"
    if cell.get("input") not in {item[0] for item in _INPUTS} \
            or cell.get("protocol") not in {item[1] for item in _INPUTS} \
            or type(cell.get("subject")) is not bool \
            or cell.get("status") not in _COVERAGE_STATUSES \
            or cell.get("capture_status") not in _CAPTURE_STATUSES \
            or cell.get("parser_status") not in _PARSER_STATUSES:
        return False, "baseline_coverage_semantics_invalid"
    text_limits = {
        "switch": 128, "platform": 80, "input": 32, "protocol": 16,
        "status": 32, "selected_command": 128, "capture_status": 32,
        "parser_status": 32, "source_sha256": 64, "projection_sha256": 64,
    }
    if any(not _safe_string(cell.get(field), limit)
           for field, limit in text_limits.items()):
        return False, "baseline_coverage_text_invalid"
    if any(not _safe_ascii_string(cell.get(field), limit)
           for field, limit in text_limits.items()):
        return False, "baseline_coverage_text_invalid"
    if not re.fullmatch(r"[0-9a-f]{64}", cell["source_sha256"]) \
            or not re.fullmatch(r"[0-9a-f]{64}", cell["projection_sha256"]):
        return False, "baseline_coverage_digest_invalid"
    for field in ("candidate_count", "parsed_count", "rejected_count"):
        if not _valid_natural(cell.get(field), _MAX_CANDIDATES):
            return False, "baseline_coverage_count_invalid"
    if cell["candidate_count"] != cell["parsed_count"] + cell["rejected_count"] \
            or not _valid_natural(cell.get("active_route_count"), _MAX_ACTIVE_ROUTES):
        return False, "baseline_coverage_count_invalid"
    codes = cell.get("finding_codes")
    if not isinstance(codes, list) or len(codes) > _MAX_FINDINGS_PER_ROW \
            or codes != sorted(set(codes)) \
            or not all(code in _CODE_INFO for code in codes):
        return False, "baseline_coverage_findings_invalid"
    expected_protocol = dict(_INPUTS)[cell["input"]]
    if cell["protocol"] != expected_protocol:
        return False, "baseline_coverage_input_protocol_invalid"
    if cell["selected_command"] not in _commands(cell["platform"], cell["input"]):
        return False, "baseline_coverage_command_invalid"
    if cell["capture_status"] != "ok":
        if cell["parser_status"] != "not_verified" \
                or any(cell[field] for field in (
                    "candidate_count", "parsed_count", "rejected_count")):
            return False, "baseline_coverage_source_parser_invalid"
    elif cell["parser_status"] == "complete" and cell["rejected_count"]:
        return False, "baseline_coverage_parser_count_invalid"
    elif cell["parser_status"] == "review" and not cell["rejected_count"]:
        return False, "baseline_coverage_parser_count_invalid"
    elif cell["parser_status"] == "rejected" and (
            cell["parsed_count"] or not cell["rejected_count"]):
        return False, "baseline_coverage_parser_count_invalid"
    elif cell["parser_status"] in {"not_verified", "explicit_no_subject"} \
            and any(cell[field] for field in (
                "candidate_count", "parsed_count", "rejected_count")):
        return False, "baseline_coverage_parser_count_invalid"
    return True, "ok"


def _structural_validation_impl(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "baseline_not_object"
    if set(value) != _ROOT_KEYS or value.get("schema") != IPV6_ROUTING_ADJACENCY_SCHEMA:
        return False, "baseline_schema_or_keys_invalid"
    if not _bounded_receipt_tree(value):
        return False, "baseline_denominator_invalid"
    if value.get("scope") != _SCOPE or value.get("limitations") != _LIMITATIONS:
        return False, "baseline_scope_or_limitations_invalid"
    if value.get("verdict") not in {
            "BLOCKED", "INDETERMINATE", "CLEAR", "NOT_APPLICABLE"} \
            or type(value.get("assessed")) is not bool:
        return False, "baseline_verdict_invalid"
    custody = value.get("projection_custody")
    if custody not in {"current_run_source_bound", "embedded_unverified"}:
        return False, "baseline_custody_invalid"
    rows, coverage, findings, summary = (
        value.get("rows"), value.get("coverage"), value.get("findings"),
        value.get("summary"))
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS \
            or not isinstance(coverage, list) or len(coverage) > _MAX_HOSTS * 3 \
            or len(coverage) % 3 \
            or not isinstance(findings, list) or len(findings) > _MAX_ROWS \
            or not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "baseline_denominator_invalid"
    digest = summary.get("baseline_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or digest != _sha(_baseline_payload(value)):
        return False, "baseline_digest_mismatch"

    row_identities = set()
    rows_by_family: Dict[Tuple[str, str], List[dict]] = {}
    host_platforms: Dict[str, str] = {}
    for row in rows:
        valid, reason = _validate_row_shape(row, custody)
        if not valid:
            return valid, reason
        folded_host = row["switch"].casefold()
        known_platform = host_platforms.setdefault(folded_host, row["platform"])
        if known_platform != row["platform"]:
            return False, "baseline_platform_mismatch"
        identity = (folded_host, row["protocol"], row["peer_key"].casefold())
        if identity in row_identities:
            return False, "baseline_row_identity_collision"
        row_identities.add(identity)
        rows_by_family.setdefault((row["switch"], row["protocol"]), []).append(row)
    protocol_order = {"OSPFv3": 0, "BGPv6": 1}
    expected_row_order = sorted(rows, key=lambda row: (
        row["switch"].casefold(), row["switch"], protocol_order[row["protocol"]],
        row["peer_key"].casefold(), row["peer_key"],
    ))
    if rows != expected_row_order:
        return False, "baseline_row_order_invalid"

    cells_by_host: Dict[str, Dict[str, dict]] = {}
    coverage_identities = set()
    coverage_host_spellings = set()
    for cell in coverage:
        valid, reason = _validate_coverage_shape(cell)
        if not valid:
            return valid, reason
        identity = (cell["switch"].casefold(), cell["input"])
        if identity in coverage_identities:
            return False, "baseline_coverage_identity_collision"
        coverage_identities.add(identity)
        coverage_host_spellings.add((cell["switch"].casefold(), cell["switch"]))
        known_platform = host_platforms.setdefault(
            cell["switch"].casefold(), cell["platform"])
        if known_platform != cell["platform"]:
            return False, "baseline_platform_mismatch"
        cells_by_host.setdefault(cell["switch"], {})[cell["input"]] = cell
    if len(cells_by_host) > _MAX_HOSTS \
            or len({folded for folded, _host in coverage_host_spellings}) != len(cells_by_host):
        return False, "baseline_host_identity_collision"
    if any(set(cells) != {item[0] for item in _INPUTS}
           for cells in cells_by_host.values()):
        return False, "baseline_coverage_denominator_incomplete"
    input_order = {name: index for index, (name, _protocol) in enumerate(_INPUTS)}
    if coverage != sorted(coverage, key=lambda cell: (
            cell["switch"].casefold(), cell["switch"], input_order[cell["input"]])):
        return False, "baseline_coverage_order_invalid"
    if any(row["switch"] not in cells_by_host for row in rows):
        return False, "baseline_row_without_coverage"

    route_parser_codes = {
        "command_variant_conflict", "route_context_review",
        "route_census_conflict", "route_census_rejected",
    }
    family_parser_codes = {
        "OSPFv3": {
            "command_variant_conflict", "ospfv3_context_review",
            "ospfv3_duplicate_identity", "ospfv3_candidate_rejected",
            "ospfv3_parser_rejected", "ospfv3_candidate_cap_exceeded",
        },
        "BGPv6": {
            "command_variant_conflict", "bgpv6_context_review",
            "bgpv6_duplicate_identity", "bgpv6_candidate_rejected",
            "bgpv6_parser_rejected", "bgpv6_candidate_cap_exceeded",
        },
    }
    for host, cells in cells_by_host.items():
        route_cell = cells["route_summary"]
        ospf_cell = cells["ospfv3_neighbors"]
        bgp_cell = cells["bgp_ipv6_neighbors"]
        if route_cell["subject"] is not (ospf_cell["subject"] or bgp_cell["subject"]):
            return False, "baseline_route_subject_mismatch"
        if route_cell["active_route_count"] != (
                ospf_cell["active_route_count"] + bgp_cell["active_route_count"]):
            return False, "baseline_route_census_mismatch"
        expected_route_status = "not_applicable"
        if route_cell["subject"]:
            expected_route_status = "assessed" if (
                route_cell["capture_status"] == "ok"
                and route_cell["parser_status"] == "complete"
            ) else ("review" if route_cell["capture_status"] == "ok"
                    and route_cell["parser_status"] == "review" else "not_verified")
        if route_cell["status"] != expected_route_status:
            return False, "baseline_route_coverage_status_mismatch"
        parser_codes = [
            code for code in route_cell["finding_codes"] if code in route_parser_codes]
        expected_route_codes = list(parser_codes)
        if route_cell["subject"] and (
                route_cell["capture_status"] != "ok"
                or route_cell["parser_status"] not in {"complete", "review"}):
            expected_route_codes.append("route_census_not_verified")
        if route_cell["finding_codes"] != sorted(set(expected_route_codes)):
            return False, "baseline_route_findings_mismatch"
        if route_cell["parser_status"] == "complete" and parser_codes \
                or route_cell["parser_status"] == "review" and not parser_codes \
                or route_cell["parser_status"] in {
                    "not_verified", "explicit_no_subject"} and parser_codes:
            return False, "baseline_route_parser_findings_mismatch"

        for protocol, input_name in (
                ("OSPFv3", "ospfv3_neighbors"),
                ("BGPv6", "bgp_ipv6_neighbors")):
            cell = cells[input_name]
            family_rows = rows_by_family.get((host, protocol), [])
            nonstatic = [row for row in family_rows if row["peer_key"]]
            if cell["parsed_count"] != len(nonstatic):
                return False, "baseline_family_parsed_census_mismatch"
            if cell["subject"] is not bool(family_rows):
                return False, "baseline_family_subject_mismatch"
            if not cell["subject"]:
                if cell["status"] != "not_applicable" or cell["active_route_count"]:
                    return False, "baseline_family_not_applicable_mismatch"
            else:
                status_counts = Counter(row["status"] for row in family_rows)
                expected = "degraded" if status_counts["degraded"] else (
                    "review" if status_counts["review"] else
                    "not_verified" if status_counts["not_verified"] else "assessed")
                if cell["status"] != expected:
                    return False, "baseline_family_coverage_status_mismatch"
            parser_codes = [
                code for code in cell["finding_codes"]
                if code in family_parser_codes[protocol]
            ]
            if cell["parser_status"] == "complete" and parser_codes \
                    or cell["parser_status"] == "review" and not parser_codes \
                    or cell["parser_status"] in {
                        "not_verified", "explicit_no_subject"} and parser_codes:
                return False, "baseline_family_parser_findings_mismatch"
            semantic_cell = dict(cell, _parser_codes=parser_codes)
            for row in family_rows:
                expected_status, expected_findings = _row_semantics(
                    row, semantic_cell, route_cell, static=not bool(row["peer_key"]))
                if row["status"] != expected_status \
                        or row["findings"] != expected_findings \
                        or row["command"] != cell["selected_command"] \
                        or row["source_key"] != _source_key(cell["selected_command"]) \
                        or row["acceptance"] != _acceptance(row):
                    return False, "baseline_row_semantics_mismatch"
            expected_codes = sorted({
                finding["code"] for row in family_rows for finding in row["findings"]
            })
            if cell["finding_codes"] != expected_codes:
                return False, "baseline_family_findings_mismatch"

    for cell in coverage:
        if cell["source_sha256"] != _sha(_coverage_source_payload(cell)) \
                or cell["projection_sha256"] != _sha(
                    _coverage_projection_payload(cell, rows)):
            return False, "baseline_coverage_hash_mismatch"

    expected_findings = sorted([
        {
            "switch": row["switch"], "protocol": row["protocol"],
            "peer_key": row["peer_key"], **finding,
        }
        for row in rows for finding in row["findings"]
    ], key=lambda item: (
        item["switch"].casefold(), item["switch"],
        protocol_order[item["protocol"]], item["peer_key"].casefold(),
        item["code"], item["issue"],
    ))
    if findings != expected_findings \
            or not all(_valid_finding(item, global_row=True) for item in findings):
        return False, "baseline_global_findings_mismatch"

    row_counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    expected_summary = {
        "n_hosts": len(cells_by_host),
        "n_subject_hosts": len({
            cell["switch"] for cell in coverage if cell["subject"]}),
        "n_rows": len(rows),
        "n_ospfv3_rows": sum(row["protocol"] == "OSPFv3" for row in rows),
        "n_bgpv6_rows": sum(row["protocol"] == "BGPv6" for row in rows),
        "n_assessed": row_counts["assessed"],
        "n_degraded": row_counts["degraded"],
        "n_review": row_counts["review"],
        "n_not_verified": row_counts["not_verified"],
        "by_status": {status: int(row_counts[status]) for status in _ROW_STATUSES},
        "by_coverage_status": {
            status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES},
    }
    if not isinstance(summary.get("by_status"), dict) \
            or set(summary["by_status"]) != set(_ROW_STATUSES) \
            or not isinstance(summary.get("by_coverage_status"), dict) \
            or set(summary["by_coverage_status"]) != set(_COVERAGE_STATUSES):
        return False, "baseline_summary_census_invalid"
    for key in _SUMMARY_KEYS - {"by_status", "by_coverage_status", "baseline_sha256"}:
        cap = _MAX_HOSTS if key in {"n_hosts", "n_subject_hosts"} else _MAX_ROWS
        if not _valid_natural(summary.get(key), cap):
            return False, "baseline_summary_census_invalid"
    if any(not _valid_natural(summary["by_status"].get(status), _MAX_ROWS)
           for status in _ROW_STATUSES) \
            or any(not _valid_natural(
                summary["by_coverage_status"].get(status), _MAX_HOSTS * 3)
                for status in _COVERAGE_STATUSES):
        return False, "baseline_summary_census_invalid"
    if any(summary.get(key) != expected for key, expected in expected_summary.items()):
        return False, "baseline_summary_mismatch"
    expected_verdict = "BLOCKED" if row_counts["degraded"] else (
        "INDETERMINATE" if row_counts["review"] or row_counts["not_verified"] else
        "CLEAR" if row_counts["assessed"] else "NOT_APPLICABLE")
    expected_assessed = bool(
        expected_verdict in {"CLEAR", "BLOCKED"}
        and not row_counts["review"] and not row_counts["not_verified"]
        and not any(
            finding["kind"] in {"review", "not_verified"}
            for finding in expected_findings)
        and all(
            not cell["subject"] or (
                cell["status"] in {"assessed", "degraded"}
                and cell["parser_status"] == "complete")
            for cell in coverage))
    if value["verdict"] != expected_verdict or value["assessed"] is not expected_assessed:
        return False, "baseline_verdict_mismatch"
    return True, "ok"


def _structural_validation(value: Any) -> Tuple[bool, str]:
    try:
        return _structural_validation_impl(value)
    except (Exception, MemoryError, RecursionError):
        return False, "baseline_validation_failed"


def _validate_ipv6_routing_adjacency_baseline(
        value: Any, *, require_current_run: bool = False) -> dict:
    present = value is not None
    valid, reason = _structural_validation(value)
    source_bound = bool(
        valid and isinstance(value, _CurrentRunIpv6RoutingAdjacencyBaseline)
        and getattr(value, "_original_digest", "")
        == value["summary"]["baseline_sha256"])
    if require_current_run and not source_bound:
        valid, reason = False, "baseline_not_current_run_source_bound"
    if not valid:
        return {
            "present": present, "valid": False, "reason": reason,
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }
    baseline = _plain_copy(value)
    rows = baseline["rows"]
    return {
        "present": True, "valid": True, "reason": "ok",
        "source_bound": source_bound, "rows": rows,
        "index": {
            (row["switch"], row["protocol"], row["peer_key"]): row
            for row in rows
        }, "baseline": baseline,
    }


def _embedded_ipv6_routing_adjacency_baseline(value: Any) -> dict:
    view = _validate_ipv6_routing_adjacency_baseline(value)
    if not view["valid"]:
        return _unavailable_baseline()
    return _embed_plain(view["baseline"])


def _embed_plain(value: dict) -> dict:
    result = _plain_copy(value)
    result["projection_custody"] = "embedded_unverified"
    for row in result.get("rows", []):
        if isinstance(row, dict):
            row["projection_custody"] = "embedded_unverified"
    summary = result.get("summary")
    if isinstance(summary, dict):
        summary["baseline_sha256"] = ""
        summary["baseline_sha256"] = _sha(_baseline_payload(result))
    return result


def _unavailable_baseline() -> dict:
    return {
        "schema": IPV6_ROUTING_ADJACENCY_SCHEMA,
        "scope": {
            "routing_instance": "default", "address_family": "ipv6",
            "protocols": ["OSPFv3", "BGPv6"],
            "denominator": "observed_runtime_adjacencies",
        },
        "verdict": "INDETERMINATE", "assessed": False,
        "projection_custody": "embedded_unverified",
        "rows": [], "coverage": [], "findings": [],
        "summary": {
            "n_hosts": 0, "n_subject_hosts": 0, "n_rows": 0,
            "n_ospfv3_rows": 0, "n_bgpv6_rows": 0,
            "n_assessed": 0, "n_degraded": 0, "n_review": 0,
            "n_not_verified": 0,
            "by_status": {status: 0 for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: 0 for status in _COVERAGE_STATUSES},
            "baseline_sha256": "",
        },
        "limitations": ["The current-run IPv6 routing-adjacency baseline was unavailable."],
    }


__all__ = [
    "IPV6_ROUTING_ADJACENCY_SCHEMA", "IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA",
    "compute_ipv6_routing_adjacency_baseline",
    "validate_ipv6_routing_adjacency_baseline",
    "embedded_ipv6_routing_adjacency_baseline",
    "compute_ipv6_routing_subject_scope",
]
