"""Source-bound configured FHRP group truth for a deliberately narrow scope.

The legacy interface projection stores one FHRP behavior string per interface.
That shape cannot retain multiple groups on one SVI and cannot reconcile a
configured group that is absent from the operational summary.  This owner reads
the captured interface configuration and subtype summaries directly, preserving
one normalized row per local group without serializing raw configuration, capture
paths, authentication material, or arbitrary device text.

V1 covers direct literal default/global IPv4 groups in IOS/IOS-XE flat HSRP,
VRRP, and GLBP interface syntax plus NX-OS nested HSRP syntax.  Everything that
may be relevant but is outside that grammar withholds a positive verdict.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cisco_toolkit.input_custody import read_text as read_custodied_text
from cisco_toolkit.textutils import normalize_ifname


FHRP_CONFIGURED_GROUP_SCHEMA = "fhrp_configured_group_baseline/1"

_PROTOCOLS = ("HSRP", "VRRP", "GLBP")
_SCOPE = {
    "routing_instance": "default",
    "afi": "ipv4",
    "group_kind": "direct_literal_local",
}
_STATUS_ORDER = {
    "degraded": 0,
    "review": 1,
    "not_verified": 2,
    "assessed": 3,
    "administratively_disabled": 4,
}
_COVERAGE_STATUS_ORDER = {
    "degraded": 0,
    "review": 1,
    "not_verified": 2,
    "assessed": 3,
    "not_applicable": 4,
}
_CONFIG_VARIANTS = (
    "show running-config | section ^interface",
    "show running-config interface",
    "show running-config",
)
_RUNTIME_VARIANTS = {
    "HSRP": (
        "show standby brief", "show hsrp brief", "show standby all", "show hsrp all",
    ),
    "VRRP": ("show vrrp brief",),
    "GLBP": ("show glbp brief",),
}
_SAFE_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt", "unreadable",
    "not_observed", "inspection_missing", "inspection_duplicate",
}
_PARSER_STATUSES = {"complete", "review", "not_verified", "rejected"}
_MAX_HOSTS = 4096
_MAX_LINES = 100_000
_MAX_GROUPS = 20_000
_MAX_FINDINGS = 8192

_ROW_KEYS = {
    "switch", "protocol", "interface", "group", "group_key", "scope",
    "configured", "configured_vip", "activation", "runtime_observed",
    "runtime_vip", "runtime_state_raw", "runtime_state", "status", "command",
    "acceptance", "source_key", "projection_custody", "findings",
}
_COVERAGE_KEYS = {
    "switch", "protocol", "platform", "subject", "status", "config_command",
    "config_capture_status", "config_parser_status", "runtime_command",
    "runtime_capture_status", "runtime_parser_status", "config_candidate_count",
    "configured_group_count", "config_rejected_count", "excluded_scope_count",
    "unsupported_relevant_count", "runtime_candidate_count", "runtime_parsed_count",
    "runtime_rejected_count", "config_sha256", "runtime_sha256",
    "projection_sha256", "finding_codes",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_coverage_cells", "n_subject_hosts", "n_subject_cells",
    "n_configured_groups", "n_active_groups", "n_runtime_groups", "n_assessed",
    "n_degraded", "n_review", "n_not_verified", "n_disabled", "by_status",
    "by_coverage_status", "baseline_sha256",
}

_HEALTHY_STATES = {
    "HSRP": {"ACTIVE", "STANDBY", "LISTEN", "SPEAK"},
    "VRRP": {"MASTER", "BACKUP"},
    "GLBP": {"ACTIVE", "STANDBY", "LISTEN"},
}
_DEGRADED_STATES = {
    "HSRP": {"INIT", "LEARN", "DISABLED", "DOWN"},
    "VRRP": {"INIT", "INITIALIZE", "DISABLED", "DOWN", "FAULT"},
    "GLBP": {"INIT", "DISABLED", "DOWN"},
}
_LEADER_STATES = {"HSRP": "ACTIVE", "VRRP": "MASTER", "GLBP": "ACTIVE"}
_ELECTION_FINDING_CODES = frozenset({
    "election_multiple_leaders_observed",
    "election_no_leader_observed",
})
_GROUP_LIMITS = {"HSRP": (0, 4095), "VRRP": (1, 255), "GLBP": (0, 1023)}


class _CurrentRunFhrpConfiguredGroupBaseline(dict):
    """Process-local custody marker deliberately lost at a JSON boundary."""


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


def _bounded_config_rows(rows: Iterable[dict]) -> List[dict]:
    bounded = [{
        "interface": row["interface"],
        "group": row["group"],
        "configured_vip": row["configured_vip"],
        "activation": row["activation"],
    } for row in rows if row.get("configured")]
    return sorted(bounded, key=lambda row: (row["interface"].casefold(), int(row["group"])))


def _bounded_runtime_rows(rows: Iterable[dict]) -> List[dict]:
    bounded = [{
        "interface": row["interface"],
        "group": row["group"],
        "runtime_vip": row["runtime_vip"],
        "runtime_state_raw": row["runtime_state_raw"],
        "runtime_state": row["runtime_state"],
    } for row in rows if row.get("runtime_observed")]
    return sorted(bounded, key=lambda row: (row["interface"].casefold(), int(row["group"])))


def _coverage_receipt_hashes(cell: dict, rows: Iterable[dict]) -> Tuple[str, str, str]:
    """Seal only normalized bounded receipts; opaque capture bodies are never hashed."""
    cell_rows = list(rows)
    config_rows = _bounded_config_rows(cell_rows)
    runtime_rows = _bounded_runtime_rows(cell_rows)
    config_hash = _sha({
        "protocol": cell["protocol"],
        "command": cell["config_command"],
        "capture_status": cell["config_capture_status"],
        "parser_status": cell["config_parser_status"],
        "candidate_count": cell["config_candidate_count"],
        "configured_group_count": cell["configured_group_count"],
        "rejected_count": cell["config_rejected_count"],
        "excluded_scope_count": cell["excluded_scope_count"],
        "unsupported_relevant_count": cell["unsupported_relevant_count"],
        "rows": config_rows,
    })
    runtime_hash = _sha({
        "protocol": cell["protocol"],
        "command": cell["runtime_command"],
        "capture_status": cell["runtime_capture_status"],
        "parser_status": cell["runtime_parser_status"],
        "candidate_count": cell["runtime_candidate_count"],
        "parsed_count": cell["runtime_parsed_count"],
        "rejected_count": cell["runtime_rejected_count"],
        "rows": runtime_rows,
    })
    projection_hash = _sha({"config": config_rows, "runtime": runtime_rows})
    return config_hash, runtime_hash, projection_hash


def _text(value: Any, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    return value.strip()[:limit]


def _ipv4(value: Any) -> str:
    token = _text(value, 64)
    try:
        address = ipaddress.ip_address(token)
    except ValueError:
        return ""
    return str(address) if address.version == 4 else ""


def _group(protocol: str, value: Any) -> str:
    token = _text(value, 16)
    if not re.fullmatch(r"\d+", token):
        return ""
    number = int(token)
    low, high = _GROUP_LIMITS[protocol]
    return str(number) if low <= number <= high else ""


def _safe_interface(value: Any) -> str:
    token = _text(value, 80)
    if not token or any(ord(char) < 32 for char in token):
        return ""
    return _text(normalize_ifname(token), 80)


def _platforms(devices: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(devices, list):
        rows: Iterable[Any] = devices
    elif isinstance(devices, dict):
        rows = [
            dict(value, hostname=key) if isinstance(value, dict)
            else {"hostname": key, "platform": value}
            for key, value in devices.items() if isinstance(key, str)
        ]
    else:
        rows = ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        host = _text(row.get("hostname") or row.get("switch"), 128)
        if host:
            out[host] = _text(row.get("platform"), 80)
    return out


def _is_nxos(platform: str, mapping: Optional[dict] = None) -> bool:
    token = (platform or "").casefold()
    if "nx" in token or "nexus" in token:
        return True
    if token and any(name in token for name in ("ios", "ios-xe", "iosxe")):
        return False
    return bool(mapping and any(command.startswith("show hsrp") for command in mapping))


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    index: Dict[Tuple[str, str], str] = {}
    duplicates: set = set()
    source = capture_integrity if isinstance(capture_integrity, dict) else {}
    inspections = source.get("inspections")
    if not isinstance(inspections, list) or len(inspections) > 1_000_000:
        return {}, set()
    for row in inspections:
        if not isinstance(row, dict):
            continue
        host = _text(row.get("host"), 128)
        command = _text(row.get("command"), 128)
        status = _text(row.get("status"), 32)
        if not host or not command or status not in _SAFE_CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture_status(index: Dict[Tuple[str, str], str], duplicates: set,
                    host: str, command: str) -> str:
    if not command:
        return "not_observed"
    key = (host, command)
    if key in duplicates:
        return "inspection_duplicate"
    return index.get(key, "inspection_missing")


def _read_capture(mapping: dict, command: str) -> Tuple[str, str]:
    path = mapping.get(command)
    if not isinstance(path, (str, bytes)):
        return "", "not_observed"
    try:
        return read_custodied_text(path, encoding="utf-8", errors="ignore"), "ok"
    except Exception:
        return "", "unreadable"


def _select_config_command(mapping: dict, platform: str, host: str,
                           inspections: Dict[Tuple[str, str], str], duplicates: set) -> str:
    nxos = _is_nxos(platform, mapping)
    variants = (
        ("show running-config interface", "show running-config",
         "show running-config | section ^interface") if nxos else
        ("show running-config | section ^interface", "show running-config",
         "show running-config interface")
    )
    present = [command for command in variants if command in mapping]
    for command in present:
        if _capture_status(inspections, duplicates, host, command) == "ok":
            return command
    if present:
        return present[0]
    return variants[0]


def _select_runtime_command(protocol: str, mapping: dict, platform: str, host: str,
                            inspections: Dict[Tuple[str, str], str], duplicates: set) -> str:
    variants = _RUNTIME_VARIANTS[protocol]
    if protocol == "HSRP":
        if _is_nxos(platform, mapping):
            variants = ("show hsrp brief", "show hsrp all", "show standby brief", "show standby all")
        else:
            variants = ("show standby brief", "show standby all", "show hsrp brief", "show hsrp all")
    present = [command for command in variants if command in mapping]
    for command in present:
        if _capture_status(inspections, duplicates, host, command) == "ok":
            return command
    if present:
        return present[0]
    return variants[0]


def _line_indent(raw: str) -> int:
    expanded = raw.expandtabs(8)
    return len(expanded) - len(expanded.lstrip())


def _blank_parser(status: str = "complete") -> dict:
    return {
        "status": status,
        "rows": [],
        "findings": [],
        "candidate_count": 0,
        "rejected_count": 0,
        "excluded_scope_count": 0,
        "unsupported_relevant_count": 0,
    }


def _interface_blocks(body: str) -> Tuple[List[Tuple[int, str, List[Tuple[int, int, str]]]], bool]:
    lines = (body or "").splitlines()
    if len(lines) > _MAX_LINES:
        return [], False
    blocks: List[Tuple[int, str, List[Tuple[int, int, str]]]] = []
    current: Optional[Tuple[int, str, List[Tuple[int, int, str]]]] = None
    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        match = re.match(r"^interface\s+(\S+)\s*$", stripped, re.IGNORECASE)
        if match and _line_indent(raw) == 0:
            if current is not None:
                blocks.append(current)
            current = (line_no, match.group(1), [])
            continue
        if current is None:
            continue
        indent = _line_indent(raw)
        if stripped.lower() == "end" or (
                stripped and stripped != "!" and indent == 0):
            blocks.append(current)
            current = None
            continue
        if stripped and stripped != "!":
            current[2].append((line_no, indent, stripped))
    if current is not None:
        blocks.append(current)
    return blocks, True


def _parse_config(body: str, platform: str, mapping: dict) -> Dict[str, dict]:
    """Return one bounded parser result per subtype."""
    result = {protocol: _blank_parser() for protocol in _PROTOCOLS}
    blocks, within_limit = _interface_blocks(body)
    if not within_limit:
        for protocol in _PROTOCOLS:
            result[protocol] = _blank_parser("rejected")
            result[protocol]["rejected_count"] = 1
            result[protocol]["unsupported_relevant_count"] = 1
            result[protocol]["candidate_count"] = 1
            result[protocol]["findings"] = [_finding(
                "review", "resource_limit", "Configuration exceeded the bounded parser line limit.")]
        return result

    nxos = _is_nxos(platform, mapping)
    stores: Dict[str, Dict[Tuple[str, str], dict]] = {protocol: {} for protocol in _PROTOCOLS}

    def parser_finding(protocol: str, code: str, issue: str) -> None:
        state = result[protocol]
        state["unsupported_relevant_count"] += 1
        state["rejected_count"] += 1
        state["findings"].append(_finding("review", code, issue))

    def ensure(protocol: str, interface: str, group: str, line_no: int) -> dict:
        return stores[protocol].setdefault((interface, group), {
            "protocol": protocol,
            "interface": interface,
            "group": group,
            "configured_vip": "",
            "group_shutdown": False,
            "interface_shutdown": False,
            "source_line": line_no,
            "findings": [],
        })

    def set_vip(row: dict, vip: str) -> None:
        if row["configured_vip"] and row["configured_vip"] != vip:
            row["findings"].append(_finding(
                "review", "configured_vip_conflict",
                "Conflicting literal virtual IPv4 addresses were configured for this group."))
        else:
            row["configured_vip"] = vip

    for _interface_line, raw_interface, entries in blocks:
        interface = _safe_interface(raw_interface)
        if not interface:
            continue
        direct_indent = min((indent for _n, indent, _t in entries), default=1)
        vrf_scoped = any(re.match(
            r"^(?:ip\s+vrf\s+forwarding|vrf\s+(?:member|forwarding))\s+(?!default\b|global\b)\S+",
            text, re.IGNORECASE) for _n, indent, text in entries if indent == direct_indent)
        interface_shutdown = False
        for _n, indent, text in entries:
            if indent != direct_indent:
                continue
            if text.casefold() == "shutdown":
                interface_shutdown = True
            elif text.casefold() == "no shutdown":
                interface_shutdown = False

        if vrf_scoped:
            for _line_no, _indent, text in entries:
                match = re.match(r"^(?:no\s+)?(standby|hsrp|vrrp|glbp)\s+(\d+)\b", text, re.IGNORECASE)
                if match:
                    protocol = "HSRP" if match.group(1).casefold() in {"standby", "hsrp"} else match.group(1).upper()
                    result[protocol]["excluded_scope_count"] += 1
            continue

        nested: Optional[Tuple[int, str, dict]] = None
        for line_no, indent, text in entries:
            low = text.casefold()
            if nested and indent <= nested[0]:
                nested = None

            if nxos and indent == direct_indent:
                header = re.match(r"^hsrp\s+(\S+)(?:\s+(.*))?$", text, re.IGNORECASE)
                if header:
                    group = _group("HSRP", header.group(1))
                    if not group:
                        if header.group(1).casefold() not in {"version", "delay"}:
                            parser_finding("HSRP", "unsupported_group_identity",
                                           "An NX-OS HSRP group identifier was outside the bounded numeric range.")
                        continue
                    row = ensure("HSRP", interface, group, line_no)
                    row["interface_shutdown"] = interface_shutdown
                    tail = _text(header.group(2), 120)
                    if tail and tail.casefold() not in {"ipv4"}:
                        row["findings"].append(_finding(
                            "review", "unsupported_nested_group_header",
                            "The NX-OS HSRP group header used syntax outside the bounded nested form."))
                    nested = (indent, group, row)
                    continue
                unsupported = re.match(r"^(vrrp|glbp)\s+\d+\b", text, re.IGNORECASE)
                if unsupported:
                    parser_finding(unsupported.group(1).upper(), "unsupported_nxos_subtype_syntax",
                                   "This NX-OS VRRP/GLBP configuration form is outside the v1 denominator.")
                    continue

            if nxos and nested and indent > nested[0]:
                row = nested[2]
                vip_match = re.match(r"^ip\s+(\S+)(?:\s+(secondary))?\s*$", text, re.IGNORECASE)
                if vip_match:
                    vip = _ipv4(vip_match.group(1))
                    if not vip:
                        row["findings"].append(_finding(
                            "review", "configured_vip_invalid",
                            "The nested HSRP virtual address was not a literal IPv4 address."))
                    elif vip_match.group(2):
                        row["findings"].append(_finding(
                            "review", "secondary_vip_unsupported",
                            "Secondary virtual addresses are outside the single-primary v1 contract."))
                    else:
                        set_vip(row, vip)
                    continue
                if low == "shutdown":
                    row["group_shutdown"] = True
                    continue
                if low == "no shutdown":
                    row["group_shutdown"] = False
                    continue
                if low.startswith("ipv6"):
                    result["HSRP"]["excluded_scope_count"] += 1
                    continue
                # Timers, priority, preempt, tracking, and authentication do not alter the
                # bounded group/VIP/activation claim and may contain secrets; ignore them.
                if re.match(r"^(priority|preempt|timers|track|authentication|name|mac-address|delay)\b", low):
                    continue
                if low.startswith(("ip ", "address ")):
                    row["findings"].append(_finding(
                        "review", "unsupported_relevant_group_syntax",
                        "Relevant nested HSRP address syntax was outside the bounded parser."))
                continue

            if nxos or indent != direct_indent:
                continue
            match = re.match(r"^(no\s+)?(standby|vrrp|glbp)\s+(.+)$", text, re.IGNORECASE)
            if not match:
                continue
            negative = bool(match.group(1))
            token = match.group(2).casefold()
            protocol = "HSRP" if token == "standby" else token.upper()
            tail = match.group(3).strip()
            parts = tail.split()
            if protocol == "HSRP" and parts and parts[0].casefold() == "ip":
                group = "0"
                action = parts[0].casefold()
                rest = parts[1:]
            else:
                group = _group(protocol, parts[0] if parts else "")
                if not group:
                    # Known interface-wide knobs do not establish a group subject.
                    if protocol == "HSRP" and parts and parts[0].casefold() in {"version", "delay"}:
                        continue
                    parser_finding(protocol, "unsupported_group_identity",
                                   "A relevant FHRP command used an unsupported group identifier.")
                    continue
                action = parts[1].casefold() if len(parts) > 1 else ""
                rest = parts[2:]
            if negative and action == "shutdown":
                row = ensure(protocol, interface, group, line_no)
                row["interface_shutdown"] = interface_shutdown
                row["group_shutdown"] = False
                continue
            if negative:
                parser_finding(protocol, "negated_group_syntax",
                               "A negated FHRP group command cannot establish current literal intent.")
                continue
            row = ensure(protocol, interface, group, line_no)
            row["interface_shutdown"] = interface_shutdown
            if action in {"ip", "address"}:
                vip = _ipv4(rest[0] if rest else "")
                secondary = any(part.casefold() == "secondary" for part in rest[1:])
                if not vip:
                    row["findings"].append(_finding(
                        "review", "configured_vip_invalid",
                        "The configured virtual address was not a literal IPv4 address."))
                elif secondary:
                    row["findings"].append(_finding(
                        "review", "secondary_vip_unsupported",
                        "Secondary virtual addresses are outside the single-primary v1 contract."))
                else:
                    set_vip(row, vip)
            elif action == "shutdown":
                row["group_shutdown"] = True
            elif action in {
                    "priority", "preempt", "timers", "track", "authentication", "name",
                    "mac-address", "redirects", "use-bia", "load-balancing", "weighting"}:
                continue
            else:
                row["findings"].append(_finding(
                    "review", "unsupported_relevant_group_syntax",
                    "Relevant FHRP group syntax was outside the bounded parser."))

    for protocol in _PROTOCOLS:
        state = result[protocol]
        rows: List[dict] = []
        for (_interface, _group_id), row in sorted(
                stores[protocol].items(), key=lambda item: (item[0][0].casefold(), int(item[0][1]))):
            if not row["configured_vip"]:
                row["findings"].append(_finding(
                    "review", "configured_vip_missing",
                    "No primary literal virtual IPv4 address was resolved for this group."))
            rows.append({
                "interface": row["interface"],
                "group": row["group"],
                "configured_vip": row["configured_vip"],
                "activation": "disabled" if (
                    row["interface_shutdown"] or row["group_shutdown"]) else "active",
                "source_line": int(row["source_line"]),
                "findings": row["findings"],
            })
        state["rows"] = rows
        state["candidate_count"] = len(rows) + int(state["rejected_count"])
        if state["findings"] or state["rejected_count"] or any(row["findings"] for row in rows):
            state["status"] = "review"
    return result


def _state(protocol: str, raw: str) -> Tuple[str, str]:
    canonical = " ".join(_text(raw, 64).upper().replace("_", "-").split())
    if canonical in _HEALTHY_STATES[protocol]:
        return canonical, "assessed"
    if canonical in _DEGRADED_STATES[protocol]:
        return canonical, "degraded"
    return "UNCLASSIFIED", "review"


def _parse_hsrp_detail(lines: List[str]) -> Tuple[List[dict], int, bool, List[dict]]:
    rows: List[dict] = []
    rejected = 0
    recognized = False
    findings: List[dict] = []
    current: Optional[dict] = None

    def finish() -> None:
        nonlocal rejected
        if current is None:
            return
        if not current["runtime_state_raw"]:
            current["findings"].append(_finding(
                "review", "runtime_state_missing", "The HSRP detail block had no recognized local state."))
        if not current["runtime_vip"]:
            current["findings"].append(_finding(
                "review", "runtime_vip_missing", "The HSRP detail block had no literal virtual IPv4 address."))
        rows.append(current.copy())

    for line_no, raw in enumerate(lines, 1):
        text = raw.strip()
        header = re.match(r"^(\S+)\s+-\s+Group\s+(\d+)\b", text, re.IGNORECASE)
        if header:
            finish()
            recognized = True
            interface = _safe_interface(header.group(1))
            group = _group("HSRP", header.group(2))
            if not interface or not group:
                rejected += 1
                current = None
            else:
                current = {
                    "interface": interface, "group": group, "runtime_vip": "",
                    "runtime_state_raw": "", "source_line": line_no, "findings": [],
                }
            continue
        if current is None:
            continue
        state_match = re.match(r"^(?:Local state|State) is\s+(\w+)", text, re.IGNORECASE)
        if state_match:
            current["runtime_state_raw"] = state_match.group(1)
            continue
        vip_match = re.search(r"Virtual IP address is\s+(\S+)", text, re.IGNORECASE)
        if vip_match:
            current["runtime_vip"] = _ipv4(vip_match.group(1))
    finish()
    if rejected:
        findings.append(_finding(
            "review", "runtime_candidate_rejected",
            "One or more HSRP detail group blocks had an invalid identity."))
    return rows, rejected, recognized, findings


def _parse_runtime(body: str, protocol: str, command: str) -> dict:
    lines = (body or "").splitlines()
    if len(lines) > _MAX_LINES:
        out = _blank_parser("rejected")
        out.update(candidate_count=1, rejected_count=1)
        out["findings"] = [_finding(
            "review", "resource_limit", "Runtime summary exceeded the bounded parser line limit.")]
        return out
    if protocol == "HSRP" and command in {"show standby all", "show hsrp all"}:
        rows, rejected, header, findings = _parse_hsrp_detail(lines)
    else:
        rows = []
        rejected = 0
        findings = []
        state_column: Optional[int] = None
        header = False
        for line in lines:
            tokens = line.strip().split()
            folded = [token.casefold() for token in tokens]
            if "interface" in folded and ("state" in folded or "active" in folded):
                header = True
                if "state" in folded:
                    state_column = folded.index("state")
                break
        no_group_name = r"(?:hsrp|standby)" if protocol == "HSRP" else protocol.casefold()
        header = header or any(re.search(
            rf"no\s+{no_group_name}\s+(?:groups?\s+)?configured", line,
            re.IGNORECASE) for line in lines)
        for line_no, raw in enumerate(lines, 1):
            text = raw.strip()
            if not text or text.casefold().startswith(("interface", "----")):
                continue
            parts = text.split()
            if len(parts) < 2 or not _safe_interface(parts[0]) or not parts[1].isdigit():
                continue
            interface = _safe_interface(parts[0])
            group = _group(protocol, parts[1])
            if not group:
                rejected += 1
                continue
            if protocol == "GLBP" and (len(parts) < 3 or parts[2] != "-"):
                # GLBP forwarder rows have a numeric Fwd column and are not group identities.
                continue
            known_states = _HEALTHY_STATES[protocol] | _DEGRADED_STATES[protocol]
            state_index = next((index for index, token in enumerate(parts[2:], 2)
                                if token.upper() in known_states), None)
            if state_index is None and state_column is not None and \
                    2 <= state_column < len(parts):
                state_index = state_column
            if state_index is None:
                # A valid interface/group-shaped row is relevant even when its state is new.
                state_index = next((index for index, token in enumerate(parts[2:], 2)
                                    if token.isalpha()), None)
            if state_index is None:
                rejected += 1
                continue
            state_raw = parts[state_index]
            ips = [_ipv4(token) for token in parts[state_index + 1:]]
            ips = [token for token in ips if token]
            vip = ips[0] if protocol == "GLBP" and ips else (ips[-1] if ips else "")
            row_findings: List[dict] = []
            if not vip:
                row_findings.append(_finding(
                    "review", "runtime_vip_missing",
                    "The runtime group row had no literal virtual IPv4 address."))
            rows.append({
                "interface": interface, "group": group, "runtime_vip": vip,
                "runtime_state_raw": state_raw, "source_line": line_no,
                "findings": row_findings,
            })
    unique: Dict[Tuple[str, str], dict] = {}
    for row in rows:
        key = (row["interface"], row["group"])
        if key in unique:
            rejected += 1
            findings.append(_finding(
                "review", "runtime_duplicate_group",
                "The runtime summary repeated a local interface/group identity."))
            continue
        state, state_status = _state(protocol, row["runtime_state_raw"])
        row["runtime_state"] = state
        row["state_status"] = state_status
        unique[key] = row
    if not header:
        findings.append(_finding(
            "review", "runtime_header_missing",
            "The runtime summary header or explicit no-groups result was not recognized."))
    if rejected and not any(item["code"] == "runtime_candidate_rejected" for item in findings):
        findings.append(_finding(
            "review", "runtime_candidate_rejected",
            "One or more group-like runtime rows could not be parsed completely."))
    if any(row["findings"] for row in unique.values()):
        findings.append(_finding(
            "review", "runtime_row_incomplete",
            "One or more runtime group rows lacked a required bounded field."))
    status = "complete" if header and not rejected and not findings else "review"
    return {
        "status": status,
        "rows": list(unique.values()),
        "findings": findings,
        "candidate_count": len(unique) + rejected,
        "rejected_count": rejected,
        "excluded_scope_count": 0,
        "unsupported_relevant_count": 0,
    }


def _acceptance(row: dict) -> str:
    identity = f"{row['protocol']} {row['interface']} group {row['group']}"
    if row["status"] == "degraded":
        if row["runtime_observed"]:
            return (
                f"PRE-CUTOVER DEGRADED — BLOCKER: configured-active {identity} was observed "
                f"in local state {row['runtime_state_raw'] or 'not acceptable'}. Restore the "
                "local group to an acceptable subtype state or explicitly disposition the "
                "baseline before the window; matching this degraded state is NOT ACCEPTANCE."
            )
        return (
            f"PRE-CUTOVER DEGRADED — BLOCKER: configured-active {identity} was not observed "
            "in the complete applicable summary. Restore the local group or explicitly "
            "disposition removal before the window."
        )
    if row["status"] == "review":
        election_finding = next(
            (finding for finding in row.get("findings", [])
             if finding.get("code") in _ELECTION_FINDING_CODES),
            None,
        )
        if election_finding:
            return (
                f"PRE-CUTOVER REVIEW — BLOCKER: {election_finding['issue']} Matching the "
                "conflicting or unresolved sequential roles is NOT ACCEPTANCE."
            )
        return (
            f"PRE-CUTOVER REVIEW — BLOCKER: {identity} could not be reconciled inside the "
            "bounded default/global IPv4 literal-group contract. Review configuration, VIP, "
            "subtype, and local runtime identity before acceptance."
        )
    if row["status"] == "not_verified":
        return (
            "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER: configuration intent and the "
            f"applicable {row['protocol']} summary could not be source-reconciled. Re-collect "
            "interface configuration and the subtype summary before acceptance."
        )
    if row["status"] == "administratively_disabled":
        return (
            f"{identity} is explicitly disabled in the bounded configured denominator; no "
            "runtime role, peer, or election-health claim is made."
        )
    return (
        f"Require configured-active {identity} VIP {row['configured_vip']} to preserve local "
        f"state {row['runtime_state']}. This is a local group-state check only; no expected "
        "member count, simultaneous election, failover, or convergence claim is made."
    )


def _canonical_switch_identity(value: Any) -> str:
    """Return the comparison key for one displayed capture-host identity."""
    return _text(value, 128).casefold()


def _row_identity(row: dict) -> Tuple[str, str, str, str]:
    """Return the canonical identity while retaining raw row display fields."""
    protocol = row.get("protocol")
    interface = _safe_interface(row.get("interface"))
    group = _group(protocol, row.get("group")) if protocol in _PROTOCOLS else ""
    return (
        _canonical_switch_identity(row.get("switch")), protocol,
        interface.casefold(), group,
    )


def _election_candidate_identity(row: dict) -> Optional[tuple]:
    """Return the exact cross-host join key for an individually reconciled row."""
    protocol = row.get("protocol")
    if protocol not in _PROTOCOLS:
        return None
    if not (
        row.get("scope") == "default/ipv4"
        and row.get("configured") is True
        and row.get("activation") == "active"
        and row.get("runtime_observed") is True
        and row.get("configured_vip") == row.get("runtime_vip") != ""
        and row.get("runtime_state") in _HEALTHY_STATES[protocol]
    ):
        return None
    interface = _safe_interface(row.get("interface"))
    group = _group(protocol, row.get("group"))
    configured_vip = _ipv4(row.get("configured_vip"))
    runtime_vip = _ipv4(row.get("runtime_vip"))
    if not interface or not group or not configured_vip or not runtime_vip:
        return None
    return (
        # Both VIP leaves remain in the identity even though eligible rows require
        # equality, so validation cannot silently weaken the configured/runtime join.
        row["scope"], protocol, interface.casefold(), group,
        configured_vip, runtime_vip,
    )


def _election_issue(identity: tuple, members: List[dict], code: str) -> str:
    scope, protocol, _interface_key, group, configured_vip, _runtime_vip = identity
    interface = sorted(
        {_safe_interface(row["interface"]) for row in members},
        key=lambda value: (value.casefold(), value),
    )[0]
    roles = Counter(row["runtime_state"] for row in members)
    composition = ", ".join(
        f"{role}={roles[role]}" for role in sorted(roles)
    )
    leader = _LEADER_STATES[protocol]
    candidate = (
        f"Exact sequential candidate scope {scope}, {protocol} interface {interface} "
        f"group {group}, configured/runtime VIP {configured_vip}"
    )
    observed = (
        f"observed role composition {composition} across {len(members)} distinct hosts"
    )
    if code == "election_multiple_leaders_observed":
        discrepancy = (
            f"multiple {leader} leaders were observed in sequential captures"
        )
    else:
        discrepancy = f"no {leader} leader was observed in sequential captures"
    return (
        f"{candidate}, {observed}: {discrepancy}. Capture timing is not simultaneous "
        "evidence, and candidate scope may be incomplete; verify the intended candidates "
        "simultaneously and explicitly disposition the election before acceptance."
    )


def _expected_election_findings(rows: List[dict]) -> Dict[tuple, dict]:
    """Recompute every review required by exact sequential candidate evidence."""
    candidates: Dict[tuple, List[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = _election_candidate_identity(row)
        if identity is not None:
            candidates.setdefault(identity, []).append(row)

    expected: Dict[tuple, dict] = {}
    for identity in sorted(candidates):
        candidate_rows = sorted(candidates[identity], key=lambda item: (
            item["switch"].casefold(), item["switch"], item["interface"], item["group"],
        ))
        members_by_host: Dict[str, dict] = {}
        for row in candidate_rows:
            host_key = _canonical_switch_identity(row.get("switch"))
            if host_key:
                members_by_host.setdefault(host_key, row)
        members = list(members_by_host.values())
        # Candidate evidence and role composition count canonical host identities,
        # never repeated or case-variant rows from one displayed capture host.
        if len(members) < 2:
            continue
        leader = _LEADER_STATES[identity[1]]
        leader_count = sum(row["runtime_state"] == leader for row in members)
        if leader_count == 1:
            continue
        code = (
            "election_no_leader_observed" if leader_count == 0
            else "election_multiple_leaders_observed"
        )
        finding = _finding("review", code, _election_issue(identity, members, code))
        for row in candidate_rows:
            expected[_row_identity(row)] = finding
    return expected


def _coverage_status(cell: dict, cell_rows: List[dict]) -> str:
    statuses = Counter(row["status"] for row in cell_rows)
    if statuses["degraded"]:
        return "degraded"
    if statuses["review"] or cell["unsupported_relevant_count"]:
        return "review"
    if statuses["not_verified"]:
        return "not_verified"
    if cell["subject"]:
        return "assessed"
    if cell["config_capture_status"] != "ok":
        return "not_verified"
    if cell["config_parser_status"] != "complete":
        return "review"
    return "not_applicable"


def _apply_election_reconciliation(rows: List[dict], coverage: List[dict],
                                   global_findings: List[dict]) -> None:
    """Mutate existing rows and derived coverage; never synthesize a group row."""
    expected = _expected_election_findings(rows)
    for row in rows:
        finding = expected.get(_row_identity(row))
        if finding is None:
            continue
        row["status"] = "review"
        row["findings"] = sorted(
            [*row["findings"], dict(finding)],
            key=lambda item: (item["code"], item["issue"]),
        )
        row["acceptance"] = _acceptance(row)

    codes_by_cell: Dict[Tuple[str, str], set] = {}
    for finding in global_findings:
        codes_by_cell.setdefault(
            (_canonical_switch_identity(finding["switch"]), finding["protocol"]), set()
        ).add(finding["code"])
    rows_by_cell: Dict[Tuple[str, str], List[dict]] = {}
    for row in rows:
        key = (_canonical_switch_identity(row["switch"]), row["protocol"])
        rows_by_cell.setdefault(key, []).append(row)
        codes_by_cell.setdefault(key, set()).update(
            finding["code"] for finding in row["findings"]
            if finding["code"] in _ELECTION_FINDING_CODES
        )
    for cell in coverage:
        key = (_canonical_switch_identity(cell["switch"]), cell["protocol"])
        cell["status"] = _coverage_status(cell, rows_by_cell.get(key, []))
        cell["finding_codes"] = sorted(codes_by_cell.get(key, set()))


def _baseline_digest_payload(result: dict) -> dict:
    """Project the receipt without recursively copying untrusted leaves."""
    if not isinstance(result, dict):
        raise TypeError("baseline digest input must be an object")
    payload = dict(result)
    summary = result.get("summary")
    if isinstance(summary, dict):
        summary = dict(summary)
        summary.pop("baseline_sha256", None)
        payload["summary"] = summary
    return payload


def _baseline_digest(result: Any) -> str:
    try:
        return _sha(_baseline_digest_payload(result))
    except (TypeError, ValueError, RecursionError, MemoryError):
        return ""


def compute_fhrp_configured_group_baseline(all_cmd_to_files: Any,
                                           capture_integrity: Any,
                                           devices: Any = None) -> dict:
    """Build the current-run local-group denominator from exact captured inputs."""
    mappings = all_cmd_to_files if isinstance(all_cmd_to_files, dict) else {}
    platforms = _platforms(devices)
    inspections, duplicates = _inspection_index(capture_integrity)
    hosts = sorted(
        {host for host in mappings if isinstance(host, str) and _text(host, 128)} | set(platforms),
        key=lambda value: (value.casefold(), value),
    )[:_MAX_HOSTS]
    if not hosts:
        # With no captured host there is no evidence boundary inside which absence
        # could be classified.  Return the same deliberately non-validating
        # abstention used for invalid embedded input, never a current-run N/A marker.
        return embedded_fhrp_configured_group_baseline(None)

    rows: List[dict] = []
    coverage: List[dict] = []
    global_findings: List[dict] = []
    for host in hosts:
        mapping = mappings.get(host)
        mapping = mapping if isinstance(mapping, dict) else {}
        platform = platforms.get(host, "")
        config_command = _select_config_command(
            mapping, platform, host, inspections, duplicates)
        config_capture = _capture_status(
            inspections, duplicates, host, config_command)
        config_body, config_read = _read_capture(mapping, config_command)
        if config_capture == "ok" and config_read != "ok":
            config_capture = config_read
        config_all = (_parse_config(config_body, platform, mapping)
                      if config_capture == "ok"
                      else {protocol: _blank_parser("not_verified") for protocol in _PROTOCOLS})

        for protocol in _PROTOCOLS:
            cfg = config_all[protocol]
            runtime_command = _select_runtime_command(
                protocol, mapping, platform, host, inspections, duplicates)
            runtime_capture = _capture_status(
                inspections, duplicates, host, runtime_command)
            runtime_body, runtime_read = _read_capture(mapping, runtime_command)
            if runtime_capture == "ok" and runtime_read != "ok":
                runtime_capture = runtime_read
            runtime = (_parse_runtime(runtime_body, protocol, runtime_command)
                       if runtime_capture == "ok" else _blank_parser("not_verified"))

            configured = {
                (row["interface"], row["group"]): row for row in cfg["rows"]
            }
            observed = {
                (row["interface"], row["group"]): row for row in runtime["rows"]
            }
            cell_rows: List[dict] = []
            for interface, group in sorted(
                    set(configured) | set(observed), key=lambda item: (item[0].casefold(), int(item[1]))):
                config_row = configured.get((interface, group))
                runtime_row = observed.get((interface, group))
                findings: List[dict] = []
                activation = config_row["activation"] if config_row else "ambiguous"
                status = "review"
                if config_row is None:
                    if config_capture != "ok":
                        status = "not_verified"
                        findings.append(_finding(
                            "not_verified", "config_not_verified",
                            "The runtime group could not be joined to an integrity-ok configuration denominator."))
                    else:
                        status = "review"
                        findings.append(_finding(
                            "review", "runtime_group_not_in_bounded_config",
                            "The observed local group was not present in the bounded literal configuration set."))
                elif config_row["findings"]:
                    status = "review"
                    findings.extend(config_row["findings"])
                elif activation == "disabled":
                    if runtime_row is not None:
                        status = "review"
                        findings.append(_finding(
                            "review", "disabled_group_observed",
                            "An explicitly disabled local group was nevertheless observed at runtime."))
                    else:
                        status = "administratively_disabled"
                elif runtime_capture != "ok":
                    status = "not_verified"
                    findings.append(_finding(
                        "not_verified", "runtime_capture_not_verified",
                        "The applicable subtype summary was not integrity-ok."))
                elif runtime_row is not None and runtime_row["state_status"] == "degraded":
                    status = "degraded"
                    findings.append(_finding(
                        "degraded", "runtime_state_degraded",
                        "The configured-active group was observed in a subtype-specific degraded local state."))
                elif cfg["status"] != "complete" or runtime["status"] != "complete":
                    status = "review"
                    findings.append(_finding(
                        "review", "parser_scope_incomplete",
                        "Configuration or runtime group candidate reconciliation was incomplete."))
                elif runtime_row is None:
                    status = "degraded"
                    findings.append(_finding(
                        "degraded", "configured_group_not_observed",
                        "The configured-active group was not observed in the complete applicable summary."))
                elif runtime_row["runtime_vip"] != config_row["configured_vip"]:
                    status = "review"
                    findings.append(_finding(
                        "review", "virtual_ip_mismatch",
                        "Configured and runtime virtual IPv4 addresses differ."))
                elif runtime_row["state_status"] == "review":
                    status = "review"
                    findings.append(_finding(
                        "review", "runtime_state_unclassified",
                        "The local runtime state was outside the subtype-specific bounded vocabulary."))
                else:
                    status = "assessed"

                row = {
                    "switch": host,
                    "protocol": protocol,
                    "interface": interface,
                    "group": group,
                    "group_key": f"{protocol}:{interface}:{group}",
                    "scope": "default/ipv4",
                    "configured": config_row is not None,
                    "configured_vip": (config_row or {}).get("configured_vip") or "",
                    "activation": activation,
                    "runtime_observed": runtime_row is not None,
                    "runtime_vip": (runtime_row or {}).get("runtime_vip") or "",
                    "runtime_state_raw": (runtime_row or {}).get("runtime_state_raw") or "",
                    "runtime_state": (runtime_row or {}).get("runtime_state") or "NOT_OBSERVED",
                    "status": status,
                    "command": runtime_command,
                    "acceptance": "",
                    "source_key": (
                        f"{config_command}#line:{(config_row or {}).get('source_line', 0)} + "
                        f"{runtime_command}"
                    ),
                    "projection_custody": "current_run_source_bound",
                    "findings": findings,
                }
                row["acceptance"] = _acceptance(row)
                cell_rows.append(row)

            subject = bool(
                cfg["candidate_count"] or cfg["unsupported_relevant_count"]
                or runtime["candidate_count"] or cell_rows
            )
            statuses = Counter(row["status"] for row in cell_rows)
            if statuses["degraded"]:
                coverage_status = "degraded"
            elif statuses["review"] or cfg["unsupported_relevant_count"]:
                coverage_status = "review"
            elif statuses["not_verified"]:
                coverage_status = "not_verified"
            elif subject:
                coverage_status = "assessed"
            elif config_capture != "ok":
                coverage_status = "not_verified"
            elif cfg["status"] != "complete":
                coverage_status = "review"
            else:
                coverage_status = "not_applicable"

            parser_findings = cfg["findings"] + runtime["findings"]
            global_findings.extend({
                **finding, "switch": host, "protocol": protocol,
            } for finding in parser_findings)
            coverage_cell = {
                "switch": host,
                "protocol": protocol,
                "platform": platform,
                "subject": subject,
                "status": coverage_status,
                "config_command": config_command,
                "config_capture_status": config_capture,
                "config_parser_status": cfg["status"],
                "runtime_command": runtime_command,
                "runtime_capture_status": runtime_capture,
                "runtime_parser_status": runtime["status"],
                "config_candidate_count": int(cfg["candidate_count"]),
                "configured_group_count": len(cfg["rows"]),
                "config_rejected_count": int(cfg["rejected_count"]),
                "excluded_scope_count": int(cfg["excluded_scope_count"]),
                "unsupported_relevant_count": int(cfg["unsupported_relevant_count"]),
                "runtime_candidate_count": int(runtime["candidate_count"]),
                "runtime_parsed_count": len(runtime["rows"]),
                "runtime_rejected_count": int(runtime["rejected_count"]),
                "config_sha256": "",
                "runtime_sha256": "",
                "projection_sha256": "",
                "finding_codes": sorted({finding["code"] for finding in parser_findings}),
            }
            (coverage_cell["config_sha256"], coverage_cell["runtime_sha256"],
             coverage_cell["projection_sha256"]) = _coverage_receipt_hashes(
                 coverage_cell, cell_rows)
            coverage.append(coverage_cell)
            rows.extend(cell_rows)

    _apply_election_reconciliation(rows, coverage, global_findings)
    rows.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"], _PROTOCOLS.index(row["protocol"]),
        row["interface"].casefold(), int(row["group"]),
    ))
    coverage.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"], _PROTOCOLS.index(row["protocol"]),
    ))
    global_findings.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"],
        _PROTOCOLS.index(row["protocol"]), row["code"], row["issue"],
    ))
    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    subject_cells = [cell for cell in coverage if cell["subject"]]
    if counts["degraded"]:
        verdict = "BLOCKED"
    elif counts["review"] or counts["not_verified"] or any(
            cell["status"] in {"review", "not_verified"} for cell in coverage):
        verdict = "INDETERMINATE"
    elif counts["assessed"]:
        verdict = "CLEAR"
    else:
        verdict = "NOT_APPLICABLE"
    assessed = verdict in {"CLEAR", "BLOCKED"} and not (
        counts["review"] or counts["not_verified"])
    result = {
        "schema": FHRP_CONFIGURED_GROUP_SCHEMA,
        "scope": dict(_SCOPE),
        "verdict": verdict,
        "assessed": bool(assessed),
        "projection_custody": "current_run_source_bound",
        "rows": rows,
        "coverage": coverage,
        "findings": global_findings,
        "summary": {
            "n_hosts": len({cell["switch"] for cell in coverage}),
            "n_coverage_cells": len(coverage),
            "n_subject_hosts": len({cell["switch"] for cell in subject_cells}),
            "n_subject_cells": len(subject_cells),
            "n_configured_groups": sum(row["configured"] for row in rows),
            "n_active_groups": sum(
                row["configured"] and row["activation"] == "active" for row in rows),
            "n_runtime_groups": sum(row["runtime_observed"] for row in rows),
            "n_assessed": counts["assessed"],
            "n_degraded": counts["degraded"],
            "n_review": counts["review"],
            "n_not_verified": counts["not_verified"],
            "n_disabled": counts["administratively_disabled"],
            "by_status": {status: int(counts[status]) for status in _STATUS_ORDER},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUS_ORDER
            },
            "baseline_sha256": "",
        },
        "limitations": [
            "Scope is direct literal local HSRP, VRRP, and GLBP groups in default/global IPv4 only.",
            "IOS/IOS-XE flat interface syntax and NX-OS nested HSRP are the supported configuration forms; VRFs, IPv6, templates, and inherited or dynamic constructs are excluded.",
            "Sequential exact-candidate role consistency is reviewed across distinct hosts; capture timing is not simultaneous election evidence. Timers, authentication, preemption, tracking behavior, secondary VIPs, expected member count, simultaneous election state, failover, convergence, freshness, and interoperability are not validated.",
            "A configured-active group missing from a complete applicable summary is reported as not observed; it is not asserted administratively or physically down.",
            "NOT_APPLICABLE means no in-scope literal local group subject was identified; it is not proof that FHRP is absent or that configuration coverage is complete.",
        ],
    }
    result["summary"]["baseline_sha256"] = _baseline_digest(result)
    marked = _CurrentRunFhrpConfiguredGroupBaseline(result)
    valid, _reason = _structural_validation(marked)
    return marked if valid else embedded_fhrp_configured_group_baseline(None)


def _safe_string(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and _text(value, limit) == value.strip()


def _valid_finding(value: Any, *, global_row: bool = False) -> bool:
    keys = {"kind", "code", "issue"}
    if global_row:
        keys |= {"switch", "protocol"}
    return bool(
        isinstance(value, dict) and set(value) == keys
        and value.get("kind") in {"degraded", "review", "not_verified"}
        and _safe_string(value.get("code"), 96)
        and _safe_string(value.get("issue"), 500)
        and (not global_row or (
            _safe_string(value.get("switch"), 128) and value.get("protocol") in _PROTOCOLS))
    )


def _sha_token(value: Any, *, empty_ok: bool = True) -> bool:
    return isinstance(value, str) and bool(
        (empty_ok and value == "") or re.fullmatch(r"[0-9a-f]{64}", value))


def _structural_validation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "baseline_not_object"
    required = {
        "schema", "scope", "verdict", "assessed", "projection_custody", "rows",
        "coverage", "findings", "summary", "limitations",
    }
    if set(value) != required or value.get("schema") != FHRP_CONFIGURED_GROUP_SCHEMA:
        return False, "baseline_schema_or_keys_invalid"
    if value.get("scope") != _SCOPE or value.get("verdict") not in {
            "CLEAR", "BLOCKED", "INDETERMINATE", "NOT_APPLICABLE"}:
        return False, "baseline_scope_or_verdict_invalid"
    if type(value.get("assessed")) is not bool:
        return False, "baseline_assessed_invalid"
    custody = value.get("projection_custody")
    if custody not in {"current_run_source_bound", "embedded_unverified"}:
        return False, "baseline_custody_invalid"
    rows = value.get("rows")
    coverage = value.get("coverage")
    summary = value.get("summary")
    if not isinstance(rows, list) or len(rows) > _MAX_GROUPS or not isinstance(coverage, list) or \
            len(coverage) > _MAX_HOSTS * len(_PROTOCOLS) or not isinstance(summary, dict) or \
            set(summary) != _SUMMARY_KEYS:
        return False, "baseline_denominator_invalid"
    expected_digest = _baseline_digest(value)
    if not expected_digest or summary.get("baseline_sha256") != expected_digest:
        return False, "baseline_digest_mismatch"

    # Reject capture-host aliases before any per-cell reconciliation can treat
    # case variants as separate devices or produce an incidental count failure.
    canonical_coverage_cells = set()
    for cell in coverage:
        if not isinstance(cell, dict):
            continue
        cell_host = _text(cell.get("switch"), 128)
        cell_protocol = cell.get("protocol")
        if not cell_host or cell_protocol not in _PROTOCOLS:
            continue
        cell_identity = (cell_host.casefold(), cell_protocol)
        if cell_identity in canonical_coverage_cells:
            return False, "baseline_coverage_identity_invalid"
        canonical_coverage_cells.add(cell_identity)

    identities = set()
    rows_by_cell: Dict[Tuple[str, str], List[dict]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "baseline_row_invalid"
        host = _text(row.get("switch"), 128)
        protocol = row.get("protocol")
        interface = _safe_interface(row.get("interface"))
        group = _group(protocol, row.get("group")) if protocol in _PROTOCOLS else ""
        if not host or protocol not in _PROTOCOLS or not interface or not group:
            return False, "baseline_row_identity_invalid"
        identity = (host.casefold(), protocol, interface.casefold(), group)
        if identity in identities or row.get("group_key") != f"{protocol}:{interface}:{group}":
            return False, "baseline_duplicate_or_key_invalid"
        identities.add(identity)
        if row.get("status") not in _STATUS_ORDER or row.get("activation") not in {
                "active", "disabled", "ambiguous"} or type(row.get("configured")) is not bool or \
                type(row.get("runtime_observed")) is not bool:
            return False, "baseline_row_semantics_invalid"
        if row.get("scope") != "default/ipv4" or row.get("projection_custody") != custody:
            return False, "baseline_row_scope_or_custody_invalid"
        if not all(_safe_string(row.get(field), limit) for field, limit in (
                ("switch", 128), ("protocol", 8), ("interface", 80), ("group", 16),
                ("group_key", 120), ("scope", 32), ("configured_vip", 64),
                ("activation", 16), ("runtime_vip", 64), ("runtime_state_raw", 64),
                ("runtime_state", 64), ("status", 32), ("command", 128),
                ("acceptance", 1600), ("source_key", 400), ("projection_custody", 40))):
            return False, "baseline_row_text_invalid"
        if row["configured_vip"] and not _ipv4(row["configured_vip"]):
            return False, "baseline_configured_vip_invalid"
        if row["runtime_vip"] and not _ipv4(row["runtime_vip"]):
            return False, "baseline_runtime_vip_invalid"
        if not isinstance(row.get("findings"), list) or len(row["findings"]) > 64 or \
                not all(_valid_finding(finding) for finding in row["findings"]):
            return False, "baseline_row_findings_invalid"
        status = row["status"]
        if row["acceptance"] != _acceptance(row):
            return False, "baseline_row_acceptance_invalid"
        if row["configured"] is (row["activation"] == "ambiguous") or \
                (not row["configured"] and row["configured_vip"]):
            return False, "baseline_config_activation_contradiction"
        if not row["runtime_observed"] and (
                row["runtime_vip"] or row["runtime_state_raw"]
                or row["runtime_state"] != "NOT_OBSERVED"):
            return False, "baseline_runtime_absence_contradiction"
        finding_kinds = {finding["kind"] for finding in row["findings"]}
        expected_finding_kind = {
            "degraded": "degraded", "review": "review",
            "not_verified": "not_verified",
        }.get(status)
        if (expected_finding_kind and (
                not row["findings"] or finding_kinds != {expected_finding_kind})) or \
                (not expected_finding_kind and row["findings"]):
            return False, "baseline_row_finding_status_mismatch"
        if status == "assessed" and not (
                row["configured"] and row["activation"] == "active"
                and row["runtime_observed"] and row["runtime_state"] in _HEALTHY_STATES[protocol]
                and row["configured_vip"] == row["runtime_vip"] != ""):
            return False, "baseline_assessed_row_contradiction"
        if status == "administratively_disabled" and not (
                row["configured"] and row["activation"] == "disabled"
                and not row["runtime_observed"]):
            return False, "baseline_disabled_row_contradiction"
        if status == "degraded" and not (
                row["configured"] and row["activation"] == "active"
                and (not row["runtime_observed"] or
                     row["runtime_state"] in _DEGRADED_STATES[protocol])):
            return False, "baseline_degraded_row_contradiction"
        rows_by_cell.setdefault((host.casefold(), protocol), []).append(row)

    coverage_cells = set()
    coverage_by_cell: Dict[Tuple[str, str], dict] = {}
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
            return False, "baseline_coverage_invalid"
        host = _text(cell.get("switch"), 128)
        protocol = cell.get("protocol")
        key = (host.casefold(), protocol)
        if not host or protocol not in _PROTOCOLS or key in coverage_cells:
            return False, "baseline_coverage_identity_invalid"
        coverage_cells.add(key)
        coverage_by_cell[key] = cell
        if type(cell.get("subject")) is not bool or cell.get("status") not in _COVERAGE_STATUS_ORDER:
            return False, "baseline_coverage_status_invalid"
        if cell["subject"] and cell["status"] == "not_applicable":
            return False, "baseline_coverage_subject_status_invalid"
        if cell.get("config_command") not in _CONFIG_VARIANTS or \
                cell.get("runtime_command") not in _RUNTIME_VARIANTS[protocol]:
            return False, "baseline_coverage_command_invalid"
        if cell.get("config_capture_status") not in _SAFE_CAPTURE_STATUSES or \
                cell.get("runtime_capture_status") not in _SAFE_CAPTURE_STATUSES or \
                cell.get("config_parser_status") not in _PARSER_STATUSES or \
                cell.get("runtime_parser_status") not in _PARSER_STATUSES:
            return False, "baseline_coverage_receipt_invalid"
        if not all(_safe_string(cell.get(field), limit) for field, limit in (
                ("switch", 128), ("protocol", 8), ("platform", 80),
                ("config_command", 128), ("config_capture_status", 32),
                ("config_parser_status", 32), ("runtime_command", 128),
                ("runtime_capture_status", 32), ("runtime_parser_status", 32))):
            return False, "baseline_coverage_text_invalid"
        count_fields = (
            "config_candidate_count", "configured_group_count", "config_rejected_count",
            "excluded_scope_count", "unsupported_relevant_count", "runtime_candidate_count",
            "runtime_parsed_count", "runtime_rejected_count",
        )
        if any(type(cell.get(field)) is not int or not 0 <= cell[field] <= _MAX_LINES
               for field in count_fields):
            return False, "baseline_coverage_count_invalid"
        cell_rows = rows_by_cell.get(key, [])
        if cell["configured_group_count"] != sum(row["configured"] for row in cell_rows) or \
                cell["runtime_parsed_count"] != sum(row["runtime_observed"] for row in cell_rows) or \
                cell["config_candidate_count"] != (
                    cell["configured_group_count"] + cell["config_rejected_count"]) or \
                cell["runtime_candidate_count"] != (
                    cell["runtime_parsed_count"] + cell["runtime_rejected_count"]):
            return False, "baseline_coverage_count_mismatch"
        if not _sha_token(cell.get("config_sha256"), empty_ok=False) or \
                not _sha_token(cell.get("runtime_sha256"), empty_ok=False) or \
                not _sha_token(cell.get("projection_sha256"), empty_ok=False):
            return False, "baseline_coverage_hash_invalid"
        expected_hashes = _coverage_receipt_hashes(cell, cell_rows)
        if expected_hashes != (
                cell["config_sha256"], cell["runtime_sha256"],
                cell["projection_sha256"]):
            return False, "baseline_coverage_receipt_hash_mismatch"
        codes = cell.get("finding_codes")
        if not isinstance(codes, list) or codes != sorted(set(codes)) or \
                not all(_safe_string(code, 96) for code in codes):
            return False, "baseline_coverage_findings_invalid"
        expected_subject = bool(
            cell["config_candidate_count"] or cell["unsupported_relevant_count"]
            or cell["runtime_candidate_count"] or cell_rows)
        if cell["subject"] is not expected_subject:
            return False, "baseline_coverage_subject_mismatch"
        expected_status = _coverage_status(cell, cell_rows)
        if cell["status"] != expected_status:
            return False, "baseline_coverage_status_mismatch"

    hosts = {host for host, _protocol in coverage_cells}
    if coverage_cells != {(host, protocol) for host in hosts for protocol in _PROTOCOLS}:
        return False, "baseline_coverage_matrix_incomplete"
    if set(rows_by_cell) - coverage_cells:
        return False, "baseline_row_without_coverage"
    for key, cell_rows in rows_by_cell.items():
        cell = coverage_by_cell[key]
        source_pattern = re.compile(
            rf"^{re.escape(cell['config_command'])}#line:\d+ \+ "
            rf"{re.escape(cell['runtime_command'])}$"
        )
        if any(row["command"] != cell["runtime_command"] or
               not source_pattern.fullmatch(row["source_key"])
               for row in cell_rows):
            return False, "baseline_row_receipt_mismatch"
    for host in hosts:
        host_cells = [coverage_by_cell[(host, protocol)] for protocol in _PROTOCOLS]
        config_receipts = {
            (cell["platform"], cell["config_command"], cell["config_capture_status"])
            for cell in host_cells
        }
        if len(config_receipts) != 1:
            return False, "baseline_host_config_receipt_mismatch"

    expected_elections = _expected_election_findings(rows)
    for row in rows:
        actual = [
            finding for finding in row["findings"]
            if finding["code"] in _ELECTION_FINDING_CODES
        ]
        expected_finding = expected_elections.get(_row_identity(row))
        if actual != ([expected_finding] if expected_finding else []) or \
                (expected_finding is not None and row["status"] != "review"):
            return False, "baseline_election_reconciliation_mismatch"

    findings = value.get("findings")
    limitations = value.get("limitations")
    if not isinstance(findings, list) or len(findings) > _MAX_FINDINGS or \
            not all(_valid_finding(finding, global_row=True) for finding in findings):
        return False, "baseline_findings_invalid"
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 32 or \
            not all(_safe_string(item, 900) for item in limitations):
        return False, "baseline_limitations_invalid"
    codes_by_cell: Dict[Tuple[str, str], set] = {}
    for finding in findings:
        codes_by_cell.setdefault(
            (_canonical_switch_identity(finding["switch"]), finding["protocol"]), set()
        ).add(finding["code"])
    for row in rows:
        codes_by_cell.setdefault(
            (_canonical_switch_identity(row["switch"]), row["protocol"]), set()
        ).update(
            finding["code"] for finding in row["findings"]
            if finding["code"] in _ELECTION_FINDING_CODES
        )
    for key, cell in coverage_by_cell.items():
        if cell["finding_codes"] != sorted(codes_by_cell.get(key, set())):
            return False, "baseline_finding_code_mismatch"

    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    subject_cells = [cell for cell in coverage if cell["subject"]]
    expected = {
        "n_hosts": len(hosts),
        "n_coverage_cells": len(coverage),
        "n_subject_hosts": len({
            _canonical_switch_identity(cell["switch"]) for cell in subject_cells
        }),
        "n_subject_cells": len(subject_cells),
        "n_configured_groups": sum(row["configured"] for row in rows),
        "n_active_groups": sum(
            row["configured"] and row["activation"] == "active" for row in rows),
        "n_runtime_groups": sum(row["runtime_observed"] for row in rows),
        "n_assessed": counts["assessed"],
        "n_degraded": counts["degraded"],
        "n_review": counts["review"],
        "n_not_verified": counts["not_verified"],
        "n_disabled": counts["administratively_disabled"],
        "by_status": {status: int(counts[status]) for status in _STATUS_ORDER},
        "by_coverage_status": {
            status: int(coverage_counts[status]) for status in _COVERAGE_STATUS_ORDER
        },
    }
    if any(summary.get(key) != expected_value for key, expected_value in expected.items()):
        return False, "baseline_summary_mismatch"
    if not isinstance(summary.get("by_status"), dict) or list(summary["by_status"]) != list(_STATUS_ORDER) or \
            not isinstance(summary.get("by_coverage_status"), dict) or \
            list(summary["by_coverage_status"]) != list(_COVERAGE_STATUS_ORDER):
        return False, "baseline_summary_census_invalid"
    if counts["degraded"]:
        expected_verdict = "BLOCKED"
    elif counts["review"] or counts["not_verified"] or any(
            cell["status"] in {"review", "not_verified"} for cell in coverage):
        expected_verdict = "INDETERMINATE"
    elif counts["assessed"]:
        expected_verdict = "CLEAR"
    else:
        expected_verdict = "NOT_APPLICABLE"
    expected_assessed = expected_verdict in {"CLEAR", "BLOCKED"} and not (
        counts["review"] or counts["not_verified"])
    if value.get("verdict") != expected_verdict or value.get("assessed") is not expected_assessed:
        return False, "baseline_verdict_mismatch"
    return True, "ok"


def validate_fhrp_configured_group_baseline(value: Any,
                                             *, require_current_run: bool = False) -> dict:
    """Validate the closed receipt and optionally require process-local custody."""
    present = value is not None
    valid, reason = _structural_validation(value)
    source_bound = valid and isinstance(value, _CurrentRunFhrpConfiguredGroupBaseline)
    if require_current_run and not source_bound:
        valid = False
        reason = "baseline_not_current_run_source_bound"
    if not valid:
        return {
            "present": present, "valid": False, "reason": reason,
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }
    baseline = copy.deepcopy(dict(value))
    rows = baseline["rows"]
    return {
        "present": True,
        "valid": True,
        "reason": "ok",
        "source_bound": source_bound,
        "rows": rows,
        "index": {
            (row["switch"], row["protocol"], row["interface"], row["group"]): row
            for row in rows
        },
        "baseline": baseline,
    }


def embedded_fhrp_configured_group_baseline(value: Any) -> dict:
    """Return a JSON-safe audit projection unable to self-authorize current-run use."""
    view = validate_fhrp_configured_group_baseline(value)
    if not view["valid"]:
        return {
            "schema": FHRP_CONFIGURED_GROUP_SCHEMA,
            "scope": dict(_SCOPE),
            "verdict": "INDETERMINATE",
            "assessed": False,
            "projection_custody": "embedded_unverified",
            "rows": [],
            "coverage": [],
            "findings": [],
            "summary": {
                "n_hosts": 0, "n_coverage_cells": 0, "n_subject_hosts": 0,
                "n_subject_cells": 0, "n_configured_groups": 0, "n_active_groups": 0,
                "n_runtime_groups": 0, "n_assessed": 0, "n_degraded": 0,
                "n_review": 0, "n_not_verified": 0, "n_disabled": 0,
                "by_status": {status: 0 for status in _STATUS_ORDER},
                "by_coverage_status": {
                    status: 0 for status in _COVERAGE_STATUS_ORDER
                },
                "baseline_sha256": "",
            },
            "limitations": [
                "The current-run FHRP configured-group baseline was unavailable.",
            ],
        }
    result = view["baseline"]
    result["projection_custody"] = "embedded_unverified"
    for row in result["rows"]:
        row["projection_custody"] = "embedded_unverified"
    result["summary"]["baseline_sha256"] = ""
    result["summary"]["baseline_sha256"] = _baseline_digest(result)
    return result


__all__ = [
    "FHRP_CONFIGURED_GROUP_SCHEMA",
    "compute_fhrp_configured_group_baseline",
    "validate_fhrp_configured_group_baseline",
    "embedded_fhrp_configured_group_baseline",
]
