"""Typed, source-bound single-chassis EtherChannel operational evidence.

The established ``etherchannel_projection/1`` and ``etherchannel_baseline/1`` owners retain
their exact schemas and observed-summary semantics.  This additive owner supplies the decision
dimensions those owners deliberately do not claim: configured member/mode intent, explicit LACP
partner aggregation identity, min-links, count/bandwidth capacity, configured hashing, bounded
physical counters, and a local single-member-loss rehearsal.

Only Cisco IOS/IOS-XE and NX-OS show-text variants are declared.  Every conclusion is local to one
chassis.  In particular, a passing rehearsal is not service-path survival and is never promoted to
multichassis evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .analyze import (
    _canonical_physical_interface,
    _canonical_port_channel,
    _validate_etherchannel_projection,
)
from .input_custody import read_bytes as read_custodied_bytes
from .parse import (
    parse_nxos_lacp_neighbors,
    parse_show_interface_counters,
    parse_show_interface_status,
)
from .textutils import normalize_mac


ETHERCHANNEL_OPERATIONAL_EVIDENCE_SCHEMA = "etherchannel_operational_evidence/1"
ETHERCHANNEL_MEMBER_FAILURE_SCHEMA = "etherchannel_single_member_failure/1"

_SCOPE = {
    "subject": "single_chassis_local_aggregation_group",
    "platforms": ["ios", "nxos"],
    "configured_modes": ["active", "passive", "desirable", "auto", "on"],
    "counter_fields": ["input_errors", "crc", "output_errors", "output_drops"],
}
_LIMITATIONS = [
    "Only Cisco IOS/IOS-XE and NX-OS show-text variants are implemented; no other vendor parity is inferred.",
    "LACP partner identity is asserted only when every observed local member carries one explicit partner system and operational aggregation key.",
    "Counters are bounded cumulative observations, not rates; any non-zero bounded fault counter blocks acceptance until disposition and recollection.",
    "The single-member-loss rehearsal proves only local count/min-links eligibility and bounded remaining bandwidth when member speeds are explicit.",
    "A local rehearsal does not prove convergence, hashing distribution, remote forwarding, traffic continuity, or service-path survival.",
    "This owner is distinct from multichassis LAG and never asserts a peer pair or dual-homed attachment.",
]

_PLATFORM_COMMANDS = {
    "ios": {
        "summary": ("show etherchannel summary",),
        "full_config": ("show running-config",),
        "scoped_config": ("show running-config | section ^interface",),
        "partner": ("show lacp neighbor",),
        "interface_status": ("show interface status",),
        "interface_counters": ("show interfaces",),
    },
    "nxos": {
        "summary": ("show port-channel summary", "show etherchannel summary"),
        "full_config": ("show running-config",),
        "scoped_config": ("show running-config interface",),
        "partner": ("show lacp neighbor",),
        "interface_status": ("show interface status",),
        "interface_counters": ("show interface",),
    },
}
_PLATFORM_ALIASES = {
    "ios": frozenset({
        "ios", "ios-xe", "iosxe", "cisco-ios", "cisco-ios-xe",
        "cisco-iosxe", "cisco-xe",
    }),
    "nxos": frozenset({
        "nxos", "nx-os", "cisco-nxos", "cisco-nx-os", "nexus",
    }),
}
_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt", "unreadable",
    "not_observed", "inspection_missing", "inspection_duplicate",
}
_ROW_STATUSES = ("assessed", "degraded", "review", "not_verified")
_COVERAGE_STATUSES = (*_ROW_STATUSES, "not_applicable")
_MODES = {"active", "passive", "desirable", "auto", "on"}
_MODE_PROTOCOL = {
    "active": "lacp", "passive": "lacp",
    "desirable": "pagp", "auto": "pagp", "on": "static",
}
_PROTOCOLS = {"lacp", "pagp", "static", "unknown"}
_COUNTER_FIELDS = tuple(_SCOPE["counter_fields"])
_MAX_HOSTS = 4096
_MAX_GROUPS = 16384
_MAX_MEMBERS = 65536
_MAX_INSPECTIONS = 1_000_000
_MAX_BODY_BYTES = 16_000_000
_MAX_LINES = 200_000

_ROOT_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody", "rows",
    "coverage", "summary", "limitations",
}
_ROW_KEYS = {
    "switch", "platform", "group", "group_id", "status", "protocol",
    "configured_members", "runtime_members", "member_metrics", "partner",
    "min_links", "capacity", "hashing", "counter_evidence",
    "member_failure_rehearsal", "source_key", "projection_custody", "findings",
}
_CONFIGURED_MEMBER_KEYS = {"interface", "mode"}
_RUNTIME_MEMBER_KEYS = {"interface", "flags", "state", "forwarding"}
_MEMBER_METRIC_KEYS = {"interface", "speed_mbps", "counters"}
_PARTNER_KEYS = {"status", "system_id", "aggregation_id", "member_count"}
_MIN_LINKS_KEYS = {"status", "configured", "value"}
_CAPACITY_KEYS = {
    "status", "configured_member_count", "runtime_member_count",
    "forwarding_member_count", "configured_bandwidth_mbps",
    "forwarding_bandwidth_mbps",
}
_HASHING_KEYS = {"status", "algorithm"}
_COUNTER_KEYS = {"status", "fields", "fault_total", "fault_members"}
_REHEARSAL_KEYS = {
    "schema", "scenario", "status", "claim", "before_forwarding_members",
    "after_forwarding_members", "min_links", "count_survives",
    "before_bandwidth_mbps", "after_worst_case_bandwidth_mbps",
    "service_path_survival",
}
_FINDING_KEYS = {"kind", "code", "issue"}
_COVERAGE_KEYS = {
    "switch", "platform", "subject", "absence_verified", "status", "subject_group_count",
    "source_receipts", "source_sha256", "projection_sha256", "finding_codes",
}
_SOURCE_RECEIPT_KEYS = {"role", "command", "capture_status", "source_sha256", "bytes"}
_SUMMARY_KEYS = {
    "n_hosts", "n_subject_hosts", "n_groups", "n_assessed", "n_degraded",
    "n_review", "n_not_verified", "n_counter_fault_groups",
    "n_member_failure_pass", "n_member_failure_fail", "by_status",
    "by_coverage_status", "evidence_sha256",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    try:
        return "sha256:" + hashlib.sha256(_json_bytes(value)).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError, MemoryError):
        return ""


def _text(value: Any, limit: int = 256) -> str:
    if not isinstance(value, str) or len(value) > limit:
        return ""
    try:
        value.encode("utf-8")
    except UnicodeError:
        return ""
    token = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in token):
        return ""
    return token


def _plain_copy(value: Mapping[str, Any]) -> dict:
    return {key: copy.deepcopy(item) for key, item in dict(value).items()}


def _evidence_payload(value: Mapping[str, Any]) -> dict:
    payload = copy.deepcopy(dict(value))
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("evidence_sha256", None)
    return payload


def _embed_plain(value: Mapping[str, Any]) -> dict:
    result = _plain_copy(value)
    result["projection_custody"] = "embedded_unverified"
    for row in result.get("rows", []):
        if isinstance(row, dict):
            row["projection_custody"] = "embedded_unverified"
    for cell in result.get("coverage", []):
        if isinstance(cell, dict):
            host_rows = [
                row for row in result.get("rows", [])
                if isinstance(row, dict) and row.get("switch") == cell.get("switch")
            ]
            cell["projection_sha256"] = _sha(host_rows)
    summary = result.get("summary")
    if isinstance(summary, dict):
        summary["evidence_sha256"] = ""
        summary["evidence_sha256"] = _sha(_evidence_payload(result))
    return result


class _CurrentRunEtherChannelOperationalEvidence(dict):
    """Process-local marker whose semantic receipt cannot be re-sealed after mutation."""

    def __init__(self, value: dict):
        super().__init__(value)
        self._original_digest = value.get("summary", {}).get("evidence_sha256", "")

    def __copy__(self):
        return _embed_plain(self)

    def __deepcopy__(self, memo):
        result = _embed_plain(self)
        memo[id(self)] = result
        return result


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _add_finding(findings: List[dict], kind: str, code: str, issue: str) -> None:
    item = _finding(kind, code, issue)
    if not any(old.get("code") == code and old.get("issue") == issue for old in findings):
        findings.append(item)


def _platforms(devices: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
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
        platform = re.sub(
            r"[\s_]+", "-",
            _text(row.get("platform") or row.get("device_type"), 80).casefold(),
        )
        if not host:
            continue
        result[host] = next(
            (
                family for family, aliases in _PLATFORM_ALIASES.items()
                if platform in aliases
            ),
            "unsupported",
        )
    return result


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    root = capture_integrity if isinstance(capture_integrity, dict) else {}
    inspections = root.get("inspections")
    if not isinstance(inspections, list) or len(inspections) > _MAX_INSPECTIONS:
        return {}, set()
    index: Dict[Tuple[str, str], str] = {}
    duplicates = set()
    for item in inspections:
        if not isinstance(item, dict):
            continue
        host = _text(item.get("host"), 128)
        command = _text(item.get("command"), 160)
        status = _text(item.get("status"), 32)
        if not host or not command or status not in _CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture(
        *, host: str, mapping: Mapping[str, Any], role: str, commands: Iterable[str],
        inspections: Mapping[Tuple[str, str], str], duplicates: set) -> Tuple[dict, str]:
    candidates = [command for command in commands if command in mapping]
    command = next(
        (candidate for candidate in candidates
         if inspections.get((host, candidate)) == "ok" and (host, candidate) not in duplicates),
        candidates[0] if candidates else "",
    )
    if not command:
        return {
            "role": role, "command": "", "capture_status": "not_observed",
            "source_sha256": "", "bytes": 0,
        }, ""
    key = (host, command)
    status = "inspection_duplicate" if key in duplicates else inspections.get(
        key, "inspection_missing")
    body = ""
    digest = ""
    byte_count = 0
    if status == "ok":
        path = mapping.get(command)
        if not isinstance(path, (str, bytes)):
            status = "unreadable"
        else:
            try:
                payload = read_custodied_bytes(path)
                if len(payload) > _MAX_BODY_BYTES:
                    status = "incomplete"
                else:
                    body = payload.decode("utf-8", errors="strict")
                    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
                    byte_count = len(payload)
            except Exception:
                status = "unreadable"
    return {
        "role": role, "command": command, "capture_status": status,
        "source_sha256": digest, "bytes": byte_count,
    }, body


def _group_number(value: Any) -> str:
    group = _canonical_port_channel(value)
    return str(int(group[2:])) if group else ""


def _parse_config(body: Any) -> dict:
    """Parse exact interface member modes, min-links, and the global hash algorithm."""
    if not isinstance(body, str) or len(body.encode("utf-8", errors="ignore")) > _MAX_BODY_BYTES:
        return {"groups": {}, "hash_algorithm": "", "rejections": ["config_body_invalid"]}
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return {"groups": {}, "hash_algorithm": "", "rejections": ["config_line_limit"]}
    groups: Dict[str, dict] = {}
    rejections: List[str] = []
    current = ""
    current_kind = ""
    hash_values: List[str] = []

    def group(name: str) -> dict:
        return groups.setdefault(name, {"members": {}, "min_links": None})

    for raw in lines:
        stripped = raw.strip()
        lower = stripped.casefold()
        if re.match(r"^interface\s+range\b", stripped, re.IGNORECASE):
            # Interface-range expansion is platform/configuration dependent.  Do not
            # guess which physical subjects a following channel-group line owns.
            current = ""
            current_kind = "range"
            continue
        header = re.match(r"^interface\s+(\S+)\s*$", stripped, re.IGNORECASE)
        if header:
            current = ""
            current_kind = ""
            interface = header.group(1)
            physical = _canonical_physical_interface(interface)
            port_channel = _canonical_port_channel(interface)
            if physical:
                current, current_kind = physical, "physical"
            elif port_channel:
                current, current_kind = port_channel, "port_channel"
            continue
        if lower == "!":
            current = ""
            current_kind = ""
            continue

        if "load-balance" in lower and not lower.startswith("no "):
            match = re.fullmatch(
                r"(?:port-channel|etherchannel)\s+load-balance\s+([a-z0-9-]+(?:\s+[a-z0-9-]+)?)",
                lower,
            )
            if match:
                hash_values.append(" ".join(match.group(1).split()))
            else:
                rejections.append("hash_algorithm_malformed")

        if "channel-group" in lower:
            match = re.fullmatch(
                r"channel-group\s+(\d+)\s+mode\s+(active|passive|desirable|auto|on)",
                lower,
            )
            if current_kind != "physical" or not current or not match:
                rejections.append("configured_member_mode_malformed")
                continue
            name = f"Po{int(match.group(1))}"
            members = group(name)["members"]
            prior = members.get(current)
            if prior is not None and prior != match.group(2):
                rejections.append("configured_member_mode_conflict")
            else:
                members[current] = match.group(2)

        if "min-links" in lower:
            match = re.fullmatch(r"(?:lacp|port-channel)\s+min-links\s+(\d+)", lower)
            if current_kind != "port_channel" or not current or not match:
                rejections.append("min_links_malformed")
                continue
            value = int(match.group(1))
            if value < 1 or value > _MAX_MEMBERS:
                rejections.append("min_links_out_of_range")
                continue
            target = group(current)
            if target["min_links"] is not None and target["min_links"] != value:
                rejections.append("min_links_conflict")
            else:
                target["min_links"] = value

    unique_hashes = sorted(set(hash_values))
    if len(unique_hashes) > 1:
        rejections.append("hash_algorithm_conflict")
    normalized = {
        name: {
            "members": [
                {"interface": interface, "mode": mode}
                for interface, mode in sorted(
                    data["members"].items(), key=lambda item: (item[0].casefold(), item[0])
                )
            ],
            "min_links": data["min_links"],
        }
        for name, data in sorted(groups.items(), key=lambda item: int(item[0][2:]))
    }
    return {
        "groups": normalized,
        "hash_algorithm": unique_hashes[0] if len(unique_hashes) == 1 else "",
        "rejections": sorted(set(rejections)),
    }


def _aggregation_id(value: Any) -> str:
    token = _text(value, 32).casefold()
    if not token:
        return ""
    try:
        number = int(token, 16) if token.startswith("0x") else int(token, 10)
    except ValueError:
        return ""
    return str(number) if 0 <= number <= 4_294_967_295 else ""


def _parse_ios_lacp_neighbors(body: str) -> dict:
    rows: List[dict] = []
    rejected = 0
    group = ""
    for raw in (body or "").splitlines():
        section = re.match(r"^\s*Channel\s+group\s+(\d+)\s+neighbors?\s*$", raw, re.IGNORECASE)
        if section:
            group = f"Po{int(section.group(1))}"
            continue
        tokens = raw.split()
        if not tokens:
            continue
        member = _canonical_physical_interface(tokens[0])
        if not member or not group:
            continue
        # IOS/IOS-XE table: Port Flags Priority Dev-ID Age Admin-key Oper-key Port State.
        if len(tokens) < 9:
            rejected += 1
            continue
        system_id = normalize_mac(tokens[3])
        oper_key = _aggregation_id(tokens[6])
        if not system_id or not oper_key:
            rejected += 1
            continue
        rows.append({
            "port_channel": group,
            "local_member": member,
            "partner_system_id": system_id,
            "partner_oper_key": oper_key,
        })
    return {"rows": rows, "rejected_count": rejected}


def _parse_partner(platform: str, body: str) -> dict:
    if platform == "ios":
        parsed = _parse_ios_lacp_neighbors(body)
        source_rows = parsed["rows"]
        rejected = parsed["rejected_count"]
    elif platform == "nxos":
        try:
            source_rows = parse_nxos_lacp_neighbors(body)
        except Exception:
            source_rows = []
        rejected = 0
    else:
        return {"index": {}, "rejected_count": 0}
    index: Dict[Tuple[str, str], dict] = {}
    for raw in source_rows if isinstance(source_rows, list) else []:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        group = _canonical_port_channel(raw.get("port_channel"))
        member = _canonical_physical_interface(raw.get("local_member"))
        system_id = normalize_mac(_text(raw.get("partner_system_id"), 64))
        aggregation_id = _aggregation_id(raw.get("partner_oper_key"))
        key = (group, member)
        if not group or not member or not system_id or not aggregation_id or key in index:
            rejected += 1
            continue
        index[key] = {
            "system_id": system_id,
            "aggregation_id": aggregation_id,
        }
    return {"index": index, "rejected_count": rejected}


def _speed_mbps(value: Any) -> Optional[int]:
    token = _text(value, 32).upper().replace(" ", "")
    if not token or token in {"AUTO", "A-AUTO", "--"}:
        return None
    match = re.fullmatch(r"(\d+)([GMK]?)", token)
    if not match:
        return None
    number = int(match.group(1))
    multiplier = {"": 1, "K": 0.001, "M": 1, "G": 1000}[match.group(2)]
    result = int(number * multiplier)
    return result if result > 0 else None


def _status_from_findings(findings: Iterable[Mapping[str, Any]]) -> str:
    kinds = {item.get("kind") for item in findings if isinstance(item, Mapping)}
    if "block" in kinds:
        return "degraded"
    if "review" in kinds:
        return "review"
    if "not_verified" in kinds:
        return "not_verified"
    return "assessed"


def _member_failure_rehearsal(
        forwarding_members: List[str], min_links: Optional[int],
        speed_by_member: Mapping[str, Optional[int]]) -> dict:
    before_count = len(forwarding_members)
    after_count = max(0, before_count - 1)
    known_speeds = [speed_by_member.get(member) for member in forwarding_members]
    before_bandwidth = (
        sum(int(value) for value in known_speeds)
        if known_speeds and all(type(value) is int and value > 0 for value in known_speeds)
        else None
    )
    after_bandwidth = (
        before_bandwidth - max(int(value) for value in known_speeds)
        if before_bandwidth is not None else None
    )
    count_survives = after_count >= min_links if type(min_links) is int else None
    status = (
        "pass" if count_survives is True and after_count > 0 else
        "fail" if count_survives is False or (count_survives is True and after_count == 0) else
        "not_verified"
    )
    return {
        "schema": ETHERCHANNEL_MEMBER_FAILURE_SCHEMA,
        "scenario": "single_forwarding_member_loss",
        "status": status,
        "claim": "local_count_min_links_and_worst_case_bandwidth_only",
        "before_forwarding_members": before_count,
        "after_forwarding_members": after_count,
        "min_links": min_links,
        "count_survives": count_survives,
        "before_bandwidth_mbps": before_bandwidth,
        "after_worst_case_bandwidth_mbps": after_bandwidth,
        "service_path_survival": "not_verified",
    }


def _unavailable() -> dict:
    result = {
        "schema": ETHERCHANNEL_OPERATIONAL_EVIDENCE_SCHEMA,
        "scope": copy.deepcopy(_SCOPE),
        "verdict": "INDETERMINATE",
        "assessed": False,
        "projection_custody": "embedded_unverified",
        "rows": [],
        "coverage": [],
        "summary": {
            "n_hosts": 0, "n_subject_hosts": 0, "n_groups": 0,
            "n_assessed": 0, "n_degraded": 0, "n_review": 0,
            "n_not_verified": 0, "n_counter_fault_groups": 0,
            "n_member_failure_pass": 0, "n_member_failure_fail": 0,
            "by_status": {status: 0 for status in _ROW_STATUSES},
            "by_coverage_status": {status: 0 for status in _COVERAGE_STATUSES},
            "evidence_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["evidence_sha256"] = _sha(_evidence_payload(result))
    return result


def compute_etherchannel_operational_evidence(
        all_cmd_to_files: Any, capture_integrity: Any, etherchannel_projection: Any,
        devices: Any = None) -> dict:
    """Build the strict current-run IOS/NX-OS single-chassis evidence receipt."""
    mappings = all_cmd_to_files if isinstance(all_cmd_to_files, dict) else {}
    platforms = _platforms(devices)
    projection_view = _validate_etherchannel_projection(etherchannel_projection)
    projection_rows = projection_view.get("index") if projection_view.get("valid") else {}
    hosts = set(platforms) | {
        host for host in mappings if isinstance(host, str) and _text(host, 128) == host
    }
    if (not isinstance(projection_rows, dict) or len(hosts) > _MAX_HOSTS
            or len({host.casefold() for host in hosts}) != len(hosts)):
        return _unavailable()
    inspections, duplicates = _inspection_index(capture_integrity)
    rows: List[dict] = []
    coverage: List[dict] = []

    for host in sorted(hosts, key=lambda item: (item.casefold(), item)):
        mapping = mappings.get(host)
        mapping = mapping if isinstance(mapping, dict) else {}
        platform = platforms.get(host, "unsupported")
        projection_row = projection_rows.get(host)
        groups = projection_row.get("groups", []) if isinstance(projection_row, dict) else []

        if platform not in _PLATFORM_COMMANDS:
            host_rows = []
            for runtime in groups:
                if not isinstance(runtime, dict):
                    continue
                group_name = _canonical_port_channel(runtime.get("group"))
                if not group_name:
                    continue
                findings = [_finding(
                    "not_verified", "platform_unsupported",
                    "This positive EtherChannel subject is outside the declared IOS/NX-OS source variants.",
                )]
                host_rows.append({
                    "switch": host, "platform": "unsupported", "group": group_name,
                    "group_id": _group_number(group_name), "status": "not_verified",
                    "protocol": "unknown", "configured_members": [], "runtime_members": [],
                    "member_metrics": [],
                    "partner": {"status": "not_verified", "system_id": "",
                                "aggregation_id": "", "member_count": 0},
                    "min_links": {"status": "not_verified", "configured": False, "value": None},
                    "capacity": {"status": "not_verified", "configured_member_count": 0,
                                 "runtime_member_count": 0, "forwarding_member_count": 0,
                                 "configured_bandwidth_mbps": None,
                                 "forwarding_bandwidth_mbps": None},
                    "hashing": {"status": "not_verified", "algorithm": ""},
                    "counter_evidence": {"status": "not_verified", "fields": list(_COUNTER_FIELDS),
                                         "fault_total": 0, "fault_members": []},
                    "member_failure_rehearsal": _member_failure_rehearsal([], None, {}),
                    "source_key": "unsupported platform; no command parity inferred",
                    "projection_custody": "current_run_source_bound", "findings": findings,
                })
            rows.extend(host_rows)
            coverage.append({
                "switch": host, "platform": "unsupported", "subject": bool(host_rows),
                "absence_verified": False,
                "status": "not_verified", "subject_group_count": len(host_rows),
                "source_receipts": [], "source_sha256": _sha([]),
                "projection_sha256": _sha(host_rows),
                "finding_codes": sorted({
                    finding["code"] for row in host_rows for finding in row["findings"]
                } if host_rows else {"absence_not_verified"}),
            })
            continue

        commands = _PLATFORM_COMMANDS[platform]
        summary_commands = commands["summary"]
        projection_command = _text(
            projection_row.get("source_command") if isinstance(projection_row, dict) else "", 160)
        if projection_command in summary_commands:
            summary_commands = (projection_command, *(
                command for command in summary_commands if command != projection_command
            ))
        bodies: Dict[str, str] = {}
        receipts: List[dict] = []
        for role in (
                "summary", "full_config", "scoped_config", "partner",
                "interface_status", "interface_counters"):
            receipt, body = _capture(
                host=host, mapping=mapping, role=role,
                commands=summary_commands if role == "summary" else commands[role],
                inspections=inspections, duplicates=duplicates,
            )
            receipts.append(receipt)
            bodies[role] = body

        receipt_by_role = {item["role"]: item for item in receipts}
        full_config = _parse_config(bodies["full_config"]) \
            if receipt_by_role["full_config"]["capture_status"] == "ok" else {
                "groups": {}, "hash_algorithm": "", "rejections": []}
        scoped_config = _parse_config(bodies["scoped_config"]) \
            if receipt_by_role["scoped_config"]["capture_status"] == "ok" else {
                "groups": {}, "hash_algorithm": "", "rejections": []}
        if (receipt_by_role["full_config"]["capture_status"] == "ok"
                and not any(
                    line.strip().casefold() == "end"
                    for line in bodies["full_config"].splitlines()
                )):
            full_config["rejections"].append("full_config_terminator_missing")
        scoped_lines = [
            line.strip().casefold()
            for line in bodies["scoped_config"].splitlines() if line.strip()
        ]
        if (receipt_by_role["scoped_config"]["capture_status"] == "ok"
                and (not scoped_lines or scoped_lines[-1] not in {"!", "end"})):
            scoped_config["rejections"].append("scoped_config_terminator_missing")
        try:
            status_rows = parse_show_interface_status(bodies["interface_status"]) \
                if receipt_by_role["interface_status"]["capture_status"] == "ok" else {}
        except Exception:
            status_rows = {}
        try:
            counter_rows = parse_show_interface_counters(bodies["interface_counters"]) \
                if receipt_by_role["interface_counters"]["capture_status"] == "ok" else {}
        except Exception:
            counter_rows = {}
        partner_view = _parse_partner(platform, bodies["partner"]) \
            if receipt_by_role["partner"]["capture_status"] == "ok" else {
                "index": {}, "rejected_count": 0}

        runtime_by_group = {
            _canonical_port_channel(item.get("group")): item
            for item in groups if isinstance(item, dict) and _canonical_port_channel(item.get("group"))
        }
        configured_group_names = set(full_config["groups"]) | set(scoped_config["groups"])
        group_names = sorted(
            set(runtime_by_group) | configured_group_names,
            key=lambda name: int(name[2:]),
        )
        host_rows: List[dict] = []

        for group_name in group_names:
            findings: List[dict] = []
            runtime = runtime_by_group.get(group_name)
            full_group = full_config["groups"].get(group_name)
            scoped_group = scoped_config["groups"].get(group_name)

            for role in ("summary", "full_config", "scoped_config",
                         "interface_status", "interface_counters"):
                status = receipt_by_role[role]["capture_status"]
                if status != "ok":
                    _add_finding(
                        findings, "not_verified", f"{role}_capture_{status}",
                        f"Required {role.replace('_', ' ')} evidence is {status.replace('_', ' ')}.",
                    )
            for code in sorted(set(full_config["rejections"] + scoped_config["rejections"])):
                _add_finding(
                    findings, "not_verified", code,
                    "A relevant running-configuration line could not be normalized without guessing.",
                )
            if full_config["groups"] != scoped_config["groups"]:
                _add_finding(
                    findings, "not_verified", "config_scope_mismatch",
                    "Full and interface-scoped running configuration do not reconcile for EtherChannel intent.",
                )

            configured_members = (
                copy.deepcopy(full_group["members"]) if full_group is not None else
                copy.deepcopy(scoped_group["members"]) if scoped_group is not None else []
            )
            if full_group is None or scoped_group is None:
                _add_finding(
                    findings, "not_verified", "configured_group_not_reconciled",
                    "The group is not present in both full and interface-scoped configuration evidence.",
                )

            runtime_members = []
            runtime_protocol = "unknown"
            if runtime is None:
                _add_finding(
                    findings, "block", "configured_group_not_operational",
                    "A configured EtherChannel group has no reconciled runtime summary group.",
                )
            else:
                runtime_protocol = {
                    "LACP": "lacp", "PAGP": "pagp", "NONE": "static",
                }.get(_text(runtime.get("protocol"), 16).upper(), "unknown")
                for member in runtime.get("members", []):
                    if not isinstance(member, dict):
                        continue
                    interface = _canonical_physical_interface(member.get("interface"))
                    if not interface:
                        continue
                    state = _text(member.get("state"), 48)
                    runtime_members.append({
                        "interface": interface,
                        "flags": _text(member.get("flags"), 16),
                        "state": state,
                        "forwarding": state in {"forwarding_observed", "delay_lacp_up"},
                    })
                runtime_members.sort(key=lambda item: (item["interface"].casefold(), item["interface"]))
                runtime_status = _text(runtime.get("status"), 32)
                if runtime_status == "degraded":
                    _add_finding(
                        findings, "block", "runtime_group_degraded",
                        "The existing summary owner reports current local group/member degradation.",
                    )
                elif runtime_status != "assessed":
                    _add_finding(
                        findings, "not_verified", "runtime_group_unverified",
                        "The existing summary owner does not authorize an assessed runtime group.",
                    )

            configured_protocols = {
                _MODE_PROTOCOL[item["mode"]] for item in configured_members
                if item.get("mode") in _MODE_PROTOCOL
            }
            configured_protocol = next(iter(configured_protocols)) \
                if len(configured_protocols) == 1 else "unknown"
            if len(configured_protocols) > 1:
                _add_finding(
                    findings, "block", "configured_mode_protocol_conflict",
                    "Configured member modes mix incompatible LACP, PAgP, or static protocols.",
                )
            protocol = runtime_protocol if runtime_protocol != "unknown" else configured_protocol
            if (runtime_protocol != "unknown" and configured_protocol != "unknown"
                    and runtime_protocol != configured_protocol):
                _add_finding(
                    findings, "block", "configured_runtime_protocol_mismatch",
                    "Configured member modes do not reconcile to the observed aggregation protocol.",
                )

            configured_set = {item["interface"] for item in configured_members}
            runtime_set = {item["interface"] for item in runtime_members}
            if configured_set != runtime_set:
                _add_finding(
                    findings, "block", "configured_runtime_member_mismatch",
                    "Configured and runtime member identities do not exactly reconcile.",
                )

            metric_interfaces = sorted(
                configured_set | runtime_set, key=lambda item: (item.casefold(), item))
            member_metrics = []
            for interface in metric_interfaces:
                speed = _speed_mbps(
                    status_rows.get(interface, {}).get("speed")
                    if isinstance(status_rows.get(interface), dict) else None
                )
                raw_counters = counter_rows.get(interface)
                counters = {
                    field: (
                        raw_counters.get(field)
                        if isinstance(raw_counters, dict)
                        and type(raw_counters.get(field)) is int
                        and raw_counters.get(field) >= 0 else None
                    )
                    for field in _COUNTER_FIELDS
                }
                member_metrics.append({
                    "interface": interface, "speed_mbps": speed, "counters": counters,
                })
            speed_by_member = {item["interface"]: item["speed_mbps"] for item in member_metrics}
            configured_speeds = [speed_by_member.get(member) for member in configured_set]
            forwarding_members = [
                item["interface"] for item in runtime_members if item["forwarding"]
            ]
            forwarding_speeds = [speed_by_member.get(member) for member in forwarding_members]
            configured_bandwidth = (
                sum(int(value) for value in configured_speeds)
                if configured_speeds and all(type(value) is int and value > 0
                                             for value in configured_speeds) else None
            )
            forwarding_bandwidth = (
                sum(int(value) for value in forwarding_speeds)
                if forwarding_speeds and all(type(value) is int and value > 0
                                             for value in forwarding_speeds) else None
            )
            capacity_status = "assessed" if (
                configured_bandwidth is not None and forwarding_bandwidth is not None
            ) else "not_verified"
            if capacity_status != "assessed":
                _add_finding(
                    findings, "not_verified", "member_bandwidth_not_verified",
                    "At least one configured/runtime member has no bounded numeric speed evidence.",
                )
            capacity = {
                "status": capacity_status,
                "configured_member_count": len(configured_members),
                "runtime_member_count": len(runtime_members),
                "forwarding_member_count": len(forwarding_members),
                "configured_bandwidth_mbps": configured_bandwidth,
                "forwarding_bandwidth_mbps": forwarding_bandwidth,
            }

            all_counter_values = [
                value for metric in member_metrics for value in metric["counters"].values()
            ]
            counters_assessed = bool(member_metrics) and all(
                type(value) is int and value >= 0 for value in all_counter_values
            )
            fault_members = sorted({
                metric["interface"] for metric in member_metrics
                if any(type(value) is int and value > 0 for value in metric["counters"].values())
            }, key=lambda item: (item.casefold(), item))
            fault_total = sum(
                int(value) for value in all_counter_values if type(value) is int and value > 0
            )
            counter_evidence = {
                "status": "assessed" if counters_assessed else "not_verified",
                "fields": list(_COUNTER_FIELDS), "fault_total": fault_total,
                "fault_members": fault_members,
            }
            if not counters_assessed:
                _add_finding(
                    findings, "not_verified", "member_counters_not_verified",
                    "Every bounded physical counter leaf was not captured for every member.",
                )
            elif fault_total:
                _add_finding(
                    findings, "block", "member_counter_fault",
                    "One or more bounded cumulative member fault counters are non-zero.",
                )

            full_min = full_group.get("min_links") if isinstance(full_group, dict) else None
            scoped_min = scoped_group.get("min_links") if isinstance(scoped_group, dict) else None
            min_links_value = full_min if type(full_min) is int and full_min == scoped_min else None
            min_links = {
                "status": "assessed" if min_links_value is not None else "not_verified",
                "configured": min_links_value is not None,
                "value": min_links_value,
            }
            if min_links_value is None:
                _add_finding(
                    findings, "not_verified", "min_links_not_verified",
                    "An explicit, reconciled min-links value is required for local failure assurance.",
                )
            elif len(forwarding_members) < min_links_value:
                _add_finding(
                    findings, "block", "current_min_links_unsatisfied",
                    "Current forwarding member count is below the configured min-links threshold.",
                )

            hash_algorithm = full_config.get("hash_algorithm") \
                if receipt_by_role["full_config"]["capture_status"] == "ok" else ""
            hashing = {
                "status": "assessed" if hash_algorithm else "not_verified",
                "algorithm": hash_algorithm,
            }
            if not hash_algorithm:
                _add_finding(
                    findings, "not_verified", "hashing_algorithm_not_verified",
                    "No exact configured port-channel load-balance algorithm was normalized.",
                )

            partner = {"status": "not_applicable", "system_id": "",
                       "aggregation_id": "", "member_count": 0}
            if protocol == "lacp":
                partner_capture = receipt_by_role["partner"]["capture_status"]
                identities = [
                    partner_view["index"].get((group_name, member))
                    for member in runtime_set
                ]
                complete = bool(runtime_set) and all(isinstance(item, dict) for item in identities)
                systems = {item["system_id"] for item in identities if isinstance(item, dict)}
                aggregations = {
                    item["aggregation_id"] for item in identities if isinstance(item, dict)
                }
                if partner_capture != "ok" or not complete:
                    partner["status"] = "not_verified"
                    _add_finding(
                        findings, "not_verified", "lacp_partner_not_verified",
                        "Every runtime LACP member does not carry an explicit partner system and aggregation key.",
                    )
                elif partner_view["rejected_count"] or len(systems) != 1 or len(aggregations) != 1:
                    partner["status"] = "degraded"
                    _add_finding(
                        findings, "block", "lacp_partner_identity_conflict",
                        "Runtime members do not reconcile to one remote LACP system/aggregation identity.",
                    )
                else:
                    partner = {
                        "status": "assessed", "system_id": next(iter(systems)),
                        "aggregation_id": next(iter(aggregations)),
                        "member_count": len(identities),
                    }

            rehearsal = _member_failure_rehearsal(
                forwarding_members, min_links_value, speed_by_member)
            if rehearsal["status"] == "fail":
                _add_finding(
                    findings, "block", "single_member_failure_unsafe",
                    "One forwarding-member loss violates local min-links eligibility or leaves no forwarding member.",
                )
            elif rehearsal["status"] == "not_verified":
                _add_finding(
                    findings, "not_verified", "single_member_failure_not_verified",
                    "Local one-member-loss eligibility cannot be reconciled without explicit min-links.",
                )

            findings.sort(key=lambda item: (item["code"], item["issue"]))
            row_status = _status_from_findings(findings)
            host_rows.append({
                "switch": host, "platform": platform, "group": group_name,
                "group_id": _group_number(group_name), "status": row_status,
                "protocol": protocol, "configured_members": configured_members,
                "runtime_members": runtime_members, "member_metrics": member_metrics,
                "partner": partner, "min_links": min_links, "capacity": capacity,
                "hashing": hashing, "counter_evidence": counter_evidence,
                "member_failure_rehearsal": rehearsal,
                "source_key": (
                    f"{host}:{group_name}#running-config+summary+partner+interface-status+counters"
                ),
                "projection_custody": "current_run_source_bound", "findings": findings,
            })

        host_rows.sort(key=lambda item: int(item["group_id"]))
        rows.extend(host_rows)
        row_statuses = {row["status"] for row in host_rows}
        absence_verified = bool(
            not host_rows
            and all(receipt_by_role[role]["capture_status"] == "ok"
                    for role in ("summary", "full_config", "scoped_config"))
            and not full_config["rejections"] and not scoped_config["rejections"]
            and full_config["groups"] == scoped_config["groups"] == {}
        )
        coverage_status = (
            "degraded" if "degraded" in row_statuses else
            "review" if "review" in row_statuses else
            "not_verified" if "not_verified" in row_statuses else
            "assessed" if host_rows else
            "not_applicable" if absence_verified else "not_verified"
        )
        coverage.append({
            "switch": host, "platform": platform, "subject": bool(host_rows),
            "absence_verified": absence_verified,
            "status": coverage_status, "subject_group_count": len(host_rows),
            "source_receipts": receipts,
            "source_sha256": _sha(receipts),
            "projection_sha256": _sha(host_rows),
            "finding_codes": sorted(
                {finding["code"] for row in host_rows for finding in row["findings"]}
                if host_rows else
                ({"absence_not_verified"} if not absence_verified else set())
            ),
        })

    rows.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"], int(row["group_id"])))
    coverage.sort(key=lambda cell: (cell["switch"].casefold(), cell["switch"]))
    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    verdict = (
        "BLOCKED" if counts["degraded"] else
        "INDETERMINATE" if counts["review"] or counts["not_verified"]
        or any(cell["status"] in {"review", "not_verified"} for cell in coverage) else
        "CLEAR" if rows else "NOT_APPLICABLE"
    )
    result = {
        "schema": ETHERCHANNEL_OPERATIONAL_EVIDENCE_SCHEMA,
        "scope": copy.deepcopy(_SCOPE), "verdict": verdict,
        "assessed": verdict in {"CLEAR", "BLOCKED"},
        "projection_custody": "current_run_source_bound",
        "rows": rows, "coverage": coverage,
        "summary": {
            "n_hosts": len(coverage),
            "n_subject_hosts": sum(cell["subject"] for cell in coverage),
            "n_groups": len(rows), "n_assessed": counts["assessed"],
            "n_degraded": counts["degraded"], "n_review": counts["review"],
            "n_not_verified": counts["not_verified"],
            "n_counter_fault_groups": sum(
                row["counter_evidence"]["fault_total"] > 0 for row in rows),
            "n_member_failure_pass": sum(
                row["member_failure_rehearsal"]["status"] == "pass" for row in rows),
            "n_member_failure_fail": sum(
                row["member_failure_rehearsal"]["status"] == "fail" for row in rows),
            "by_status": {status: int(counts[status]) for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
            },
            "evidence_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["evidence_sha256"] = _sha(_evidence_payload(result))
    valid, _reason = _structural_validation(result)
    if not valid:
        return _unavailable()
    return _CurrentRunEtherChannelOperationalEvidence(result)


def _valid_finding(value: Any) -> bool:
    return bool(
        isinstance(value, dict) and set(value) == _FINDING_KEYS
        and value.get("kind") in {"block", "review", "not_verified"}
        and _text(value.get("code"), 96) == value.get("code")
        and _text(value.get("issue"), 600) == value.get("issue")
    )


def _valid_sha(value: Any, *, empty: bool = False) -> bool:
    return bool((empty and value == "") or (
        isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
    ))


def _structural_validation_impl(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != _ROOT_KEYS:
        return False, "evidence_root_invalid"
    if value.get("schema") != ETHERCHANNEL_OPERATIONAL_EVIDENCE_SCHEMA \
            or value.get("scope") != _SCOPE or value.get("limitations") != _LIMITATIONS:
        return False, "evidence_schema_scope_invalid"
    if value.get("verdict") not in {"CLEAR", "BLOCKED", "INDETERMINATE", "NOT_APPLICABLE"} \
            or type(value.get("assessed")) is not bool \
            or value.get("projection_custody") not in {
                "current_run_source_bound", "embedded_unverified"}:
        return False, "evidence_verdict_or_custody_invalid"
    rows, coverage, summary = value.get("rows"), value.get("coverage"), value.get("summary")
    if (not isinstance(rows, list) or len(rows) > _MAX_GROUPS
            or not isinstance(coverage, list) or len(coverage) > _MAX_HOSTS
            or not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS):
        return False, "evidence_denominator_invalid"
    if summary.get("evidence_sha256") != _sha(_evidence_payload(value)):
        return False, "evidence_digest_mismatch"

    row_index: Dict[Tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "evidence_row_shape_invalid"
        host = _text(row.get("switch"), 128)
        group = _canonical_port_channel(row.get("group"))
        if (not host or group != row.get("group") or row.get("group_id") != _group_number(group)
                or row.get("platform") not in {"ios", "nxos", "unsupported"}
                or row.get("status") not in _ROW_STATUSES
                or row.get("protocol") not in _PROTOCOLS
                or row.get("projection_custody") != value.get("projection_custody")
                or not _text(row.get("source_key"), 300)):
            return False, "evidence_row_identity_invalid"
        identity = (host.casefold(), group.casefold())
        if identity in row_index:
            return False, "evidence_row_duplicate"

        configured = row.get("configured_members")
        runtime = row.get("runtime_members")
        metrics = row.get("member_metrics")
        if not all(isinstance(items, list) and len(items) <= _MAX_MEMBERS
                   for items in (configured, runtime, metrics)):
            return False, "evidence_members_invalid"
        configured_ids = []
        for item in configured:
            if (not isinstance(item, dict) or set(item) != _CONFIGURED_MEMBER_KEYS
                    or _canonical_physical_interface(item.get("interface")) != item.get("interface")
                    or item.get("mode") not in _MODES):
                return False, "evidence_configured_member_invalid"
            configured_ids.append(item["interface"])
        runtime_ids = []
        forwarding_ids = []
        for item in runtime:
            if (not isinstance(item, dict) or set(item) != _RUNTIME_MEMBER_KEYS
                    or _canonical_physical_interface(item.get("interface")) != item.get("interface")
                    or not _text(item.get("flags"), 16) or not _text(item.get("state"), 48)
                    or type(item.get("forwarding")) is not bool):
                return False, "evidence_runtime_member_invalid"
            runtime_ids.append(item["interface"])
            if item["forwarding"]:
                forwarding_ids.append(item["interface"])
        metric_ids = []
        metric_by_interface = {}
        for item in metrics:
            if (not isinstance(item, dict) or set(item) != _MEMBER_METRIC_KEYS
                    or _canonical_physical_interface(item.get("interface")) != item.get("interface")
                    or (item.get("speed_mbps") is not None
                        and (type(item.get("speed_mbps")) is not int or item["speed_mbps"] <= 0))
                    or not isinstance(item.get("counters"), dict)
                    or set(item["counters"]) != set(_COUNTER_FIELDS)
                    or any(value is not None and (type(value) is not int or value < 0)
                           for value in item["counters"].values())):
                return False, "evidence_member_metric_invalid"
            metric_ids.append(item["interface"])
            metric_by_interface[item["interface"]] = item
        for identities in (configured_ids, runtime_ids, metric_ids):
            if identities != sorted(set(identities), key=lambda item: (item.casefold(), item)):
                return False, "evidence_member_order_or_duplicate"
        if set(metric_ids) != set(configured_ids) | set(runtime_ids):
            return False, "evidence_member_metric_denominator_mismatch"

        partner, min_links, capacity, hashing, counter_evidence, rehearsal = (
            row.get("partner"), row.get("min_links"), row.get("capacity"),
            row.get("hashing"), row.get("counter_evidence"),
            row.get("member_failure_rehearsal"),
        )
        if not isinstance(partner, dict) or set(partner) != _PARTNER_KEYS \
                or partner.get("status") not in {
                    "assessed", "degraded", "not_verified", "not_applicable"} \
                or type(partner.get("member_count")) is not int \
                or partner["member_count"] < 0:
            return False, "evidence_partner_invalid"
        if row["protocol"] == "lacp" and partner["status"] == "assessed":
            if not normalize_mac(partner.get("system_id")) \
                    or partner.get("system_id") != normalize_mac(partner.get("system_id")) \
                    or not partner.get("aggregation_id", "").isdigit() \
                    or partner["member_count"] != len(runtime_ids):
                return False, "evidence_partner_identity_invalid"
        elif partner["status"] == "not_applicable":
            if row["protocol"] == "lacp" or partner["system_id"] \
                    or partner["aggregation_id"] or partner["member_count"]:
                return False, "evidence_partner_applicability_invalid"

        if (not isinstance(min_links, dict) or set(min_links) != _MIN_LINKS_KEYS
                or min_links.get("status") not in {"assessed", "not_verified"}
                or type(min_links.get("configured")) is not bool
                or (min_links.get("value") is not None
                    and (type(min_links["value"]) is not int or min_links["value"] < 1))
                or min_links["configured"] is not (min_links["value"] is not None)
                or min_links["status"] != (
                    "assessed" if min_links["value"] is not None else "not_verified")):
            return False, "evidence_min_links_invalid"

        if not isinstance(capacity, dict) or set(capacity) != _CAPACITY_KEYS \
                or capacity.get("status") not in {"assessed", "not_verified"}:
            return False, "evidence_capacity_invalid"
        counts = {
            "configured_member_count": len(configured_ids),
            "runtime_member_count": len(runtime_ids),
            "forwarding_member_count": len(forwarding_ids),
        }
        if any(capacity.get(key) != expected for key, expected in counts.items()):
            return False, "evidence_capacity_count_mismatch"
        configured_speeds = [metric_by_interface[item]["speed_mbps"] for item in configured_ids]
        forwarding_speeds = [metric_by_interface[item]["speed_mbps"] for item in forwarding_ids]
        expected_configured_bandwidth = (
            sum(configured_speeds) if configured_speeds and all(
                type(item) is int for item in configured_speeds) else None)
        expected_forwarding_bandwidth = (
            sum(forwarding_speeds) if forwarding_speeds and all(
                type(item) is int for item in forwarding_speeds) else None)
        expected_capacity_status = "assessed" if (
            expected_configured_bandwidth is not None
            and expected_forwarding_bandwidth is not None) else "not_verified"
        if (capacity["configured_bandwidth_mbps"] != expected_configured_bandwidth
                or capacity["forwarding_bandwidth_mbps"] != expected_forwarding_bandwidth
                or capacity["status"] != expected_capacity_status):
            return False, "evidence_capacity_reconciliation_failed"

        if (not isinstance(hashing, dict) or set(hashing) != _HASHING_KEYS
                or hashing.get("status") not in {"assessed", "not_verified"}
                or not isinstance(hashing.get("algorithm"), str)
                or hashing["status"] != ("assessed" if hashing["algorithm"] else "not_verified")
                or (hashing["algorithm"] and not re.fullmatch(
                    r"[a-z0-9-]+(?:\s+[a-z0-9-]+)?", hashing["algorithm"]
                ))):
            return False, "evidence_hashing_invalid"

        all_counters = [
            counter for metric in metrics for counter in metric["counters"].values()
        ]
        counters_assessed = bool(metrics) and all(type(item) is int for item in all_counters)
        expected_fault_members = sorted({
            metric["interface"] for metric in metrics
            if any(type(item) is int and item > 0 for item in metric["counters"].values())
        }, key=lambda item: (item.casefold(), item))
        expected_fault_total = sum(
            item for item in all_counters if type(item) is int and item > 0)
        if (not isinstance(counter_evidence, dict) or set(counter_evidence) != _COUNTER_KEYS
                or counter_evidence.get("fields") != list(_COUNTER_FIELDS)
                or counter_evidence.get("status") != (
                    "assessed" if counters_assessed else "not_verified")
                or counter_evidence.get("fault_total") != expected_fault_total
                or counter_evidence.get("fault_members") != expected_fault_members):
            return False, "evidence_counter_reconciliation_failed"

        expected_rehearsal = _member_failure_rehearsal(
            forwarding_ids, min_links["value"], {
                interface: metric_by_interface[interface]["speed_mbps"]
                for interface in metric_by_interface
            })
        if not isinstance(rehearsal, dict) or set(rehearsal) != _REHEARSAL_KEYS \
                or rehearsal != expected_rehearsal:
            return False, "evidence_rehearsal_reconciliation_failed"

        findings = row.get("findings")
        if (not isinstance(findings, list) or not all(_valid_finding(item) for item in findings)
                or findings != sorted(findings, key=lambda item: (item["code"], item["issue"]))
                or len({(item["code"], item["issue"]) for item in findings}) != len(findings)
                or row["status"] != _status_from_findings(findings)):
            return False, "evidence_findings_or_status_invalid"
        if row["status"] == "assessed":
            configured_protocols = {
                _MODE_PROTOCOL[item["mode"]] for item in configured
            }
            partner_healthy = (
                partner["status"] == "assessed"
                if row["protocol"] == "lacp" else
                partner["status"] == "not_applicable"
            )
            if (len(configured_protocols) != 1
                    or row["protocol"] != next(iter(configured_protocols))
                    or set(configured_ids) != set(runtime_ids)
                    or not partner_healthy
                    or min_links["status"] != "assessed"
                    or capacity["status"] != "assessed"
                    or hashing["status"] != "assessed"
                    or counter_evidence["status"] != "assessed"
                    or counter_evidence["fault_total"] != 0
                    or rehearsal["status"] != "pass"):
                return False, "evidence_assessed_semantics_invalid"
        row_index[identity] = row
    if rows != sorted(rows, key=lambda row: (
            row["switch"].casefold(), row["switch"], int(row["group_id"]))):
        return False, "evidence_row_order_invalid"

    coverage_hosts = set()
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
            return False, "evidence_coverage_shape_invalid"
        host = _text(cell.get("switch"), 128)
        if (not host or host.casefold() in coverage_hosts
                or cell.get("platform") not in {"ios", "nxos", "unsupported"}
                or type(cell.get("subject")) is not bool
                or type(cell.get("absence_verified")) is not bool
                or cell.get("status") not in _COVERAGE_STATUSES
                or type(cell.get("subject_group_count")) is not int
                or cell["subject_group_count"] < 0):
            return False, "evidence_coverage_identity_invalid"
        coverage_hosts.add(host.casefold())
        receipts = cell.get("source_receipts")
        if not isinstance(receipts, list):
            return False, "evidence_source_receipts_invalid"
        expected_roles = (
            "summary", "full_config", "scoped_config", "partner",
            "interface_status", "interface_counters",
        )
        if cell["platform"] == "unsupported":
            if receipts:
                return False, "evidence_unsupported_source_receipts_invalid"
        elif ([receipt.get("role") for receipt in receipts] != list(expected_roles)
              or len(receipts) != len(expected_roles)):
            return False, "evidence_source_receipt_roster_invalid"
        for receipt in receipts:
            role = receipt.get("role") if isinstance(receipt, dict) else None
            allowed_commands = _PLATFORM_COMMANDS.get(
                cell["platform"], {}).get(role, ())
            if (not isinstance(receipt, dict) or set(receipt) != _SOURCE_RECEIPT_KEYS
                    or role not in expected_roles
                    or receipt.get("command") not in {"", *allowed_commands}
                    or receipt.get("capture_status") not in _CAPTURE_STATUSES
                    or type(receipt.get("bytes")) is not int or receipt["bytes"] < 0
                    or not _valid_sha(receipt.get("source_sha256"), empty=True)
                    or ((receipt["capture_status"] == "ok") is not bool(
                        receipt["source_sha256"] and receipt["bytes"] > 0))):
                return False, "evidence_source_receipt_invalid"
        host_rows = [row for row in rows if row["switch"] == host]
        if (cell["subject_group_count"] != len(host_rows)
                or any(row["platform"] != cell["platform"] for row in host_rows)
                or cell["source_sha256"] != _sha(receipts)
                or cell["projection_sha256"] != _sha(host_rows)
                or cell.get("finding_codes") != sorted(
                    {finding["code"] for row in host_rows for finding in row["findings"]}
                    if host_rows else
                    ({"absence_not_verified"} if not cell["absence_verified"] else set())
                )):
            return False, "evidence_coverage_reconciliation_failed"
        if not cell["subject"]:
            expected_absence_status = (
                "not_applicable" if cell["absence_verified"] else "not_verified")
            if cell["status"] != expected_absence_status or host_rows:
                return False, "evidence_not_applicable_mismatch"
            if cell["absence_verified"] and (
                    cell["platform"] == "unsupported"
                    or any(
                        receipt["capture_status"] != "ok"
                        for receipt in receipts
                        if receipt["role"] in {
                            "summary", "full_config", "scoped_config",
                        }
                    )):
                return False, "evidence_absence_source_invalid"
        else:
            if cell["absence_verified"]:
                return False, "evidence_positive_absence_mismatch"
            statuses = {row["status"] for row in host_rows}
            expected_status = (
                "degraded" if "degraded" in statuses else
                "review" if "review" in statuses else
                "not_verified" if "not_verified" in statuses or not host_rows else
                "assessed"
            )
            if cell["status"] != expected_status:
                return False, "evidence_coverage_status_mismatch"
    if coverage != sorted(coverage, key=lambda cell: (
            cell["switch"].casefold(), cell["switch"])):
        return False, "evidence_coverage_order_invalid"

    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    expected_summary = {
        "n_hosts": len(coverage),
        "n_subject_hosts": sum(cell["subject"] for cell in coverage),
        "n_groups": len(rows), "n_assessed": counts["assessed"],
        "n_degraded": counts["degraded"], "n_review": counts["review"],
        "n_not_verified": counts["not_verified"],
        "n_counter_fault_groups": sum(
            row["counter_evidence"]["fault_total"] > 0 for row in rows),
        "n_member_failure_pass": sum(
            row["member_failure_rehearsal"]["status"] == "pass" for row in rows),
        "n_member_failure_fail": sum(
            row["member_failure_rehearsal"]["status"] == "fail" for row in rows),
        "by_status": {status: int(counts[status]) for status in _ROW_STATUSES},
        "by_coverage_status": {
            status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
        },
    }
    if any(summary.get(key) != expected for key, expected in expected_summary.items()):
        return False, "evidence_summary_mismatch"
    expected_verdict = (
        "BLOCKED" if counts["degraded"] else
        "INDETERMINATE" if counts["review"] or counts["not_verified"]
        or any(cell["status"] in {"review", "not_verified"} for cell in coverage) else
        "CLEAR" if rows else "NOT_APPLICABLE"
    )
    if value["verdict"] != expected_verdict \
            or value["assessed"] is not (expected_verdict in {"CLEAR", "BLOCKED"}):
        return False, "evidence_verdict_mismatch"
    return True, "ok"


def _structural_validation(value: Any) -> Tuple[bool, str]:
    try:
        return _structural_validation_impl(value)
    except (Exception, MemoryError):
        return False, "evidence_validation_failed"


def validate_etherchannel_operational_evidence(
        value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the complete closed contract and optional process-local source authority."""
    present = value is not None
    valid, reason = _structural_validation(value)
    source_bound = bool(
        valid and isinstance(value, _CurrentRunEtherChannelOperationalEvidence)
        and getattr(value, "_original_digest", "")
        == value.get("summary", {}).get("evidence_sha256")
    )
    if require_current_run and not source_bound:
        valid, reason = False, "evidence_not_current_run_source_bound"
    if not valid:
        return {
            "present": present, "valid": False, "reason": reason,
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }
    baseline = _plain_copy(value)
    rows = baseline["rows"]
    return {
        "present": True, "valid": True, "reason": "ok", "source_bound": source_bound,
        "rows": rows,
        "index": {(row["switch"], row["group"]): row for row in rows},
        "baseline": baseline,
    }


def embedded_etherchannel_operational_evidence(value: Any) -> dict:
    """Return the JSON-safe audit projection; serialization erases current-run authority."""
    view = validate_etherchannel_operational_evidence(value)
    if not view["valid"]:
        return _unavailable()
    return _embed_plain(view["baseline"])


__all__ = [
    "ETHERCHANNEL_OPERATIONAL_EVIDENCE_SCHEMA",
    "ETHERCHANNEL_MEMBER_FAILURE_SCHEMA",
    "compute_etherchannel_operational_evidence",
    "validate_etherchannel_operational_evidence",
    "embedded_etherchannel_operational_evidence",
]
