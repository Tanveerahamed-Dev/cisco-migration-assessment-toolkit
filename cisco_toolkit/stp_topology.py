"""Typed, namespace-aware STP topology evidence for cutover assurance.

The historic STP projections intentionally remain unchanged: ``stp_roots`` is keyed by a
numeric VLAN/instance token and ``InterfaceData`` collapses role information into forwarding and
blocked ranges.  This module is an additive source owner for the information those projections
cannot retain.  It binds one local ``show spanning-tree`` observation to its matching
``show spanning-tree detail`` counters, preserves the PVST/MST namespace, and publishes a strict
embedded baseline that comparison code can reconcile to exact stored snapshot bytes.

It does not claim configured topology intent, loop freedom, convergence, or service survival.
Malformed, partial, duplicated, or missing required evidence remains ``not_verified``.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping, Tuple

from .parse import (
    parse_spanning_tree_role_rows,
    parse_spanning_tree_root,
    parse_spanning_tree_topology_changes,
)
from .textutils import is_valid_iface


STP_TOPOLOGY_OBSERVATION_SCHEMA = "stp_topology_observation/1"
STP_TOPOLOGY_BASELINE_SCHEMA = "stp_topology_baseline/1"

_CAPTURE_STATES = {"usable", "empty", "error", "missing"}
_NAMESPACES = {"pvst_vlan", "mst_instance"}
_ROLES = {"root", "designated", "alternate", "backup", "boundary", "master"}
_STATES = {"forwarding", "blocked", "listening", "learning", "disabled"}
_ROW_STATUSES = ("assessed", "degraded", "not_verified")
_COVERAGE_STATUSES = (*_ROW_STATUSES, "not_applicable")
_MAX_HOSTS = 4096
_MAX_INSTANCES = 4095
_MAX_PORT_ROWS = 262_144
_MAX_COUNTER = (1 << 64) - 1

_OBSERVATION_KEYS = {
    "schema", "state_capture_state", "detail_capture_state", "explicit_no_subject",
    "state_instance_count", "role_candidate_count", "role_parsed_count",
    "detail_instance_count", "counter_candidate_count", "counter_parsed_count",
    "roots", "roles", "topology_changes", "finding_codes",
}
_ROOT_KEYS = {
    "namespace", "instance", "root_address", "root_priority", "bridge_priority",
    "is_root",
}
_ROLE_KEYS = {"namespace", "instance", "interface", "role", "state"}
_COUNTER_KEYS = {"namespace", "instance", "count", "last_change"}
_BASELINE_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody", "rows",
    "coverage", "summary", "limitations",
}
_BASELINE_ROW_KEYS = {
    "switch", "namespace", "instance", "root_address", "root_priority",
    "bridge_priority", "is_root", "port_roles", "forwarding_paths", "blocked_paths",
    "topology_change_count", "topology_change_last_change", "status", "finding_codes",
    "source_key", "projection_custody",
}
_COVERAGE_KEYS = {
    "switch", "status", "state_capture_state", "detail_capture_state",
    "explicit_no_subject", "state_instance_count", "role_candidate_count",
    "role_parsed_count", "detail_instance_count", "counter_candidate_count",
    "counter_parsed_count", "finding_codes", "projection_sha256",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_subject_hosts", "n_rows", "n_assessed", "n_degraded",
    "n_not_verified", "by_status", "by_coverage_status", "baseline_sha256",
}
_SCOPE = {
    "commands": ["show spanning-tree", "show spanning-tree detail"],
    "subject": "observed_local_pvst_or_mst_instance",
    "identity": ["switch", "namespace", "instance"],
}
_LIMITATIONS = [
    "The baseline covers observed local PVST VLAN or MST instance roots, port roles/states, and topology-change counters from paired captures.",
    "It does not establish configured topology intent, complete VLAN-to-MST mapping, timers, loop freedom, convergence time, or simultaneous multi-device state.",
    "Forwarding and blocked paths are current local STP states, not proof of end-to-end service or failure survival.",
    "A topology-change counter is monotonic observed state; an increase is a cutover regression signal but does not attribute cause.",
]

_FINDING_CODES = {
    "state_capture_missing", "state_capture_empty", "state_capture_error",
    "detail_capture_missing", "detail_capture_empty", "detail_capture_error",
    "state_instance_missing", "state_instance_duplicate", "mixed_namespace",
    "root_evidence_incomplete", "role_row_malformed", "role_subject_duplicate",
    "role_evidence_missing", "detail_instance_missing", "detail_instance_extra",
    "detail_instance_duplicate", "topology_counter_malformed",
    "topology_counter_duplicate", "topology_counter_missing",
    "observation_malformed", "invalid_role_state", "transitional_port_state",
    "no_forwarding_path", "root_path_missing", "unexpected_root_path",
}

_INSTANCE_HEADER = re.compile(r"^(?:#+\s*)?(VLAN|MST)0*(\d+)\b", re.IGNORECASE)
_ROLE_LINE = re.compile(
    r"^(\S+)\s+(Root|Desg|Altn|Back|Boun|Mstr)\*?\s+"
    r"(FWD|BLK|LIS|LRN|DIS|BKN)\b",
    re.IGNORECASE,
)
_ROLE_TABLE_HEADER = re.compile(
    r"^Interface\s+Role\s+Sts(?:\s+.*)?$",
    re.IGNORECASE,
)
_ROLE_TABLE_SEPARATOR = re.compile(
    r"^-{3,}\s+-{3,}\s+-{3,}(?:\s+.*)?$",
)
_COUNTER_LINE = re.compile(
    r"number\s+of\s+topology\s+changes\s+(\d+)"
    r"(?:\s+last\s+change\s+occurred\s+(.+?))?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_NO_SUBJECT = (
    re.compile(r"no spanning tree instance exists[.!]?", re.IGNORECASE),
    re.compile(r"no spanning tree instances exist[.!]?", re.IGNORECASE),
    re.compile(r"spanning tree is not enabled[.!]?", re.IGNORECASE),
)

# Stable role/state combinations.  Learning/listening are syntactically valid but are treated as
# current degradation below because they are transitional, not steady forwarding evidence.
_ROLE_STATES = {
    "root": {"forwarding", "learning", "listening"},
    "designated": {"forwarding", "learning", "listening", "disabled"},
    "alternate": {"blocked"},
    "backup": {"blocked"},
    "boundary": {"forwarding", "blocked", "learning", "listening", "disabled"},
    "master": {"forwarding", "learning", "listening"},
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    try:
        return hashlib.sha256(_json_bytes(value)).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, MemoryError):
        return ""


def _text(value: Any, limit: int = 256) -> str:
    if not isinstance(value, str) or len(value) > limit:
        return ""
    result = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in result):
        return ""
    return result


def _safe_string(value: Any, limit: int = 256) -> bool:
    return isinstance(value, str) and value == _text(value, limit)


def _namespace(token: str) -> str:
    return "pvst_vlan" if token.upper() == "VLAN" else "mst_instance"


def _instance_valid(namespace: Any, instance: Any) -> bool:
    if namespace not in _NAMESPACES or not isinstance(instance, str) \
            or not re.fullmatch(r"0|[1-9]\d{0,3}", instance):
        return False
    numeric = int(instance)
    return (1 <= numeric <= 4094) if namespace == "pvst_vlan" else (0 <= numeric <= 4094)


def _explicit_no_subject(body: Any) -> bool:
    if not isinstance(body, str):
        return False
    meaningful = [line.strip() for line in body.splitlines() if line.strip()]
    return len(meaningful) == 1 and any(
        pattern.fullmatch(meaningful[0]) for pattern in _EXPLICIT_NO_SUBJECT
    )


def _headers(body: Any) -> Tuple[list[Tuple[str, str]], bool]:
    rows: list[Tuple[str, str]] = []
    duplicate = False
    seen: set[Tuple[str, str]] = set()
    if not isinstance(body, str):
        return rows, duplicate
    for raw in body.splitlines():
        match = _INSTANCE_HEADER.match(raw.strip())
        if not match:
            continue
        key = (_namespace(match.group(1)), str(int(match.group(2))))
        if key in seen:
            duplicate = True
        else:
            seen.add(key)
            rows.append(key)
    return rows, duplicate


def _role_candidates(body: Any) -> Tuple[int, bool]:
    """Count every framed role-table row and flag duplicate parsed subjects."""
    if not isinstance(body, str):
        return 0, False
    current: Tuple[str, str] | None = None
    table_header_seen = False
    table_body = False
    candidates = 0
    seen: set[Tuple[str, str, str]] = set()
    duplicate = False
    for raw in body.splitlines():
        line = raw.strip()
        header = _INSTANCE_HEADER.match(line)
        if header:
            current = (_namespace(header.group(1)), str(int(header.group(2))))
            table_header_seen = False
            table_body = False
            continue
        if current is None:
            continue

        if _ROLE_TABLE_HEADER.fullmatch(line):
            table_header_seen = True
            table_body = False
            continue
        if table_header_seen and not table_body:
            if _ROLE_TABLE_SEPARATOR.fullmatch(line):
                table_body = True
            continue
        if not table_body:
            continue
        if not line:
            table_header_seen = False
            table_body = False
            continue

        # Once the Interface/Role/Sts table is framed, every nonblank body row belongs to
        # the observed denominator.  Counting only parseable interfaces or role/state tokens
        # lets a row with two malformed required leaves disappear from both the parser and the
        # candidate count, which can turn a truncated capture into a clean baseline.
        candidates += 1
        match = _ROLE_LINE.match(line)
        if not match:
            continue
        key = (*current, match.group(1).casefold())
        if key in seen:
            duplicate = True
        seen.add(key)
    return candidates, duplicate


def _counter_candidates(body: Any) -> Tuple[int, bool]:
    if not isinstance(body, str):
        return 0, False
    current: Tuple[str, str] | None = None
    candidates = 0
    seen: set[Tuple[str, str]] = set()
    duplicate = False
    for raw in body.splitlines():
        line = raw.strip()
        header = _INSTANCE_HEADER.match(line)
        if header:
            current = (_namespace(header.group(1)), str(int(header.group(2))))
            continue
        if "topology changes" not in line.casefold():
            continue
        candidates += 1
        if current is None or not _COUNTER_LINE.search(line):
            continue
        if current in seen:
            duplicate = True
        seen.add(current)
    return candidates, duplicate


def produce_stp_topology_observation(
        state_output: Any,
        detail_output: Any,
        *,
        state_capture_state: Any,
        detail_capture_state: Any) -> dict:
    """Build one strict path-free observation from already-custodied command text."""
    state_capture = state_capture_state if state_capture_state in _CAPTURE_STATES else "missing"
    detail_capture = detail_capture_state if detail_capture_state in _CAPTURE_STATES else "missing"
    state_body = state_output if isinstance(state_output, str) else ""
    detail_body = detail_output if isinstance(detail_output, str) else ""
    explicit_none = bool(
        state_capture == detail_capture == "usable"
        and _explicit_no_subject(state_body)
        and _explicit_no_subject(detail_body)
    )

    state_headers, duplicate_state = _headers(state_body)
    detail_headers, duplicate_detail = _headers(detail_body)
    parsed_roles = parse_spanning_tree_role_rows(state_body)
    parsed_counters = parse_spanning_tree_topology_changes(detail_body)
    parsed_roots = parse_spanning_tree_root(state_body)
    role_candidates, duplicate_roles = _role_candidates(state_body)
    counter_candidates, duplicate_counters = _counter_candidates(detail_body)

    roots = []
    for namespace, instance in sorted(state_headers):
        raw = parsed_roots.get(instance)
        raw = raw if isinstance(raw, dict) else {}
        roots.append({
            "namespace": namespace,
            "instance": instance,
            "root_address": _text(raw.get("root_address"), 64),
            "root_priority": raw.get("root_priority")
            if type(raw.get("root_priority")) is int else None,
            "bridge_priority": raw.get("bridge_priority")
            if type(raw.get("bridge_priority")) is int else None,
            "is_root": raw.get("is_root") if type(raw.get("is_root")) is bool else False,
        })

    roles = sorted(
        [dict(row) for row in parsed_roles if isinstance(row, dict)],
        key=lambda row: (
            str(row.get("namespace")), str(row.get("instance")),
            str(row.get("interface")).casefold(), str(row.get("interface")),
        ),
    )
    counters = sorted(
        [dict(row) for row in parsed_counters if isinstance(row, dict)],
        key=lambda row: (str(row.get("namespace")), str(row.get("instance"))),
    )

    findings: set[str] = set()
    if state_capture != "usable":
        findings.add(f"state_capture_{state_capture}")
    if not explicit_none:
        if not state_headers:
            findings.add("state_instance_missing")
        if duplicate_state:
            findings.add("state_instance_duplicate")
        if len({namespace for namespace, _instance in state_headers}) > 1:
            findings.add("mixed_namespace")
        if role_candidates != len(roles):
            findings.add("role_row_malformed")
        if duplicate_roles:
            findings.add("role_subject_duplicate")

        root_index = {(row["namespace"], row["instance"]): row for row in roots}
        role_instances = {
            (str(row.get("namespace")), str(row.get("instance"))) for row in roles
        }
        for key in state_headers:
            root = root_index.get(key, {})
            if type(root.get("root_priority")) is not int \
                    or type(root.get("bridge_priority")) is not int \
                    or not _text(root.get("root_address"), 64):
                findings.add("root_evidence_incomplete")
            if key not in role_instances:
                findings.add("role_evidence_missing")

        if detail_capture != "usable":
            findings.add(f"detail_capture_{detail_capture}")
        if duplicate_detail:
            findings.add("detail_instance_duplicate")
        state_set, detail_set = set(state_headers), set(detail_headers)
        if state_set - detail_set:
            findings.add("detail_instance_missing")
        if detail_set - state_set:
            findings.add("detail_instance_extra")
        if counter_candidates != len(counters):
            findings.add("topology_counter_malformed")
        if duplicate_counters:
            findings.add("topology_counter_duplicate")
        counter_instances = {
            (str(row.get("namespace")), str(row.get("instance"))) for row in counters
        }
        if state_set - counter_instances:
            findings.add("topology_counter_missing")

    return {
        "schema": STP_TOPOLOGY_OBSERVATION_SCHEMA,
        "state_capture_state": state_capture,
        "detail_capture_state": detail_capture,
        "explicit_no_subject": explicit_none,
        "state_instance_count": len(state_headers),
        "role_candidate_count": role_candidates,
        "role_parsed_count": len(roles),
        "detail_instance_count": len(detail_headers),
        "counter_candidate_count": counter_candidates,
        "counter_parsed_count": len(counters),
        "roots": roots,
        "roles": roles,
        "topology_changes": counters,
        "finding_codes": sorted(findings),
    }


def _valid_root(row: Any) -> bool:
    if not isinstance(row, dict) or set(row) != _ROOT_KEYS \
            or not _instance_valid(row.get("namespace"), row.get("instance")) \
            or type(row.get("is_root")) is not bool:
        return False
    for field in ("root_priority", "bridge_priority"):
        value = row.get(field)
        if value is not None and (type(value) is not int or not 0 <= value <= 65_535):
            return False
    address = row.get("root_address")
    return _safe_string(address, 64) and (
        not address or bool(re.fullmatch(r"[0-9a-fA-F.:-]{4,64}", address))
    )


def _valid_role(row: Any) -> bool:
    return bool(
        isinstance(row, dict) and set(row) == _ROLE_KEYS
        and _instance_valid(row.get("namespace"), row.get("instance"))
        and _safe_string(row.get("interface"), 128) and is_valid_iface(row["interface"])
        and row.get("role") in _ROLES and row.get("state") in _STATES
    )


def _valid_counter(row: Any) -> bool:
    return bool(
        isinstance(row, dict) and set(row) == _COUNTER_KEYS
        and _instance_valid(row.get("namespace"), row.get("instance"))
        and type(row.get("count")) is int and 0 <= row["count"] <= _MAX_COUNTER
        and _safe_string(row.get("last_change"), 128)
    )


def validate_stp_topology_observation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != _OBSERVATION_KEYS \
            or value.get("schema") != STP_TOPOLOGY_OBSERVATION_SCHEMA:
        return False, "observation_schema_or_keys_invalid"
    if value.get("state_capture_state") not in _CAPTURE_STATES \
            or value.get("detail_capture_state") not in _CAPTURE_STATES \
            or type(value.get("explicit_no_subject")) is not bool:
        return False, "observation_capture_state_invalid"
    for field in (
            "state_instance_count", "role_candidate_count", "role_parsed_count",
            "detail_instance_count", "counter_candidate_count", "counter_parsed_count"):
        count = value.get(field)
        ceiling = _MAX_PORT_ROWS if "role" in field else _MAX_INSTANCES
        if type(count) is not int or not 0 <= count <= ceiling:
            return False, "observation_count_invalid"
    roots, roles, counters = value.get("roots"), value.get("roles"), value.get("topology_changes")
    if not isinstance(roots, list) or len(roots) > _MAX_INSTANCES \
            or not isinstance(roles, list) or len(roles) > _MAX_PORT_ROWS \
            or not isinstance(counters, list) or len(counters) > _MAX_INSTANCES:
        return False, "observation_denominator_invalid"
    if value["state_instance_count"] != len(roots) \
            or value["role_parsed_count"] != len(roles) \
            or value["counter_parsed_count"] != len(counters):
        return False, "observation_count_mismatch"
    if not all(_valid_root(row) for row in roots) \
            or not all(_valid_role(row) for row in roles) \
            or not all(_valid_counter(row) for row in counters):
        return False, "observation_row_invalid"
    root_keys = [(row["namespace"], row["instance"]) for row in roots]
    role_keys = [(row["namespace"], row["instance"], row["interface"].casefold()) for row in roles]
    counter_keys = [(row["namespace"], row["instance"]) for row in counters]
    if len(set(root_keys)) != len(root_keys) or len(set(role_keys)) != len(role_keys) \
            or len(set(counter_keys)) != len(counter_keys):
        return False, "observation_duplicate_subject"
    if roots != sorted(roots, key=lambda row: (row["namespace"], row["instance"])) \
            or roles != sorted(roles, key=lambda row: (
                row["namespace"], row["instance"], row["interface"].casefold(), row["interface"])) \
            or counters != sorted(counters, key=lambda row: (row["namespace"], row["instance"])):
        return False, "observation_order_invalid"
    codes = value.get("finding_codes")
    if not isinstance(codes, list) or codes != sorted(set(codes)) \
            or not set(codes) <= _FINDING_CODES:
        return False, "observation_findings_invalid"
    capture_codes = {
        "state_capture_missing", "state_capture_empty", "state_capture_error",
        "detail_capture_missing", "detail_capture_empty", "detail_capture_error",
    }
    expected_capture_codes = set()
    if value["state_capture_state"] != "usable":
        expected_capture_codes.add(f"state_capture_{value['state_capture_state']}")
    if value["detail_capture_state"] != "usable":
        expected_capture_codes.add(f"detail_capture_{value['detail_capture_state']}")
    if set(codes) & capture_codes != expected_capture_codes:
        return False, "observation_capture_findings_mismatch"
    if ("role_row_malformed" in codes) is not (
            value["role_candidate_count"] != value["role_parsed_count"]):
        return False, "observation_role_count_findings_mismatch"
    if ("topology_counter_malformed" in codes) is not (
            value["counter_candidate_count"] != value["counter_parsed_count"]):
        return False, "observation_counter_count_findings_mismatch"
    if value["explicit_no_subject"]:
        if value["state_capture_state"] != "usable" or any((roots, roles, counters)) \
                or set(codes) != expected_capture_codes \
                or any(value[field] for field in (
                    "state_instance_count", "role_candidate_count", "role_parsed_count",
                    "detail_instance_count", "counter_candidate_count", "counter_parsed_count")):
            return False, "observation_no_subject_mismatch"
    return True, "ok"


def _device_roster(devices: Any) -> Tuple[set[str], bool]:
    if isinstance(devices, dict):
        candidates: Iterable[Any] = devices.keys()
    elif isinstance(devices, list):
        candidates = [
            row.get("hostname") or row.get("switch") if isinstance(row, dict) else None
            for row in devices
        ]
    elif devices is None:
        return set(), True
    else:
        return set(), False
    roster: set[str] = set()
    folded: set[str] = set()
    for raw in candidates:
        host = _text(raw, 128)
        if not host or host != raw or host.casefold() in folded:
            return set(), False
        roster.add(host)
        folded.add(host.casefold())
    return roster, len(roster) <= _MAX_HOSTS


def _unavailable_baseline() -> dict:
    result = {
        "schema": STP_TOPOLOGY_BASELINE_SCHEMA,
        "scope": deepcopy(_SCOPE),
        "verdict": "INDETERMINATE",
        "assessed": False,
        "projection_custody": "embedded_unverified",
        "rows": [],
        "coverage": [],
        "summary": {
            "n_hosts": 0,
            "n_subject_hosts": 0,
            "n_rows": 0,
            "n_assessed": 0,
            "n_degraded": 0,
            "n_not_verified": 0,
            "by_status": {status: 0 for status in _ROW_STATUSES},
            "by_coverage_status": {status: 0 for status in _COVERAGE_STATUSES},
            "baseline_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    return result


def _baseline_payload(value: Mapping[str, Any]) -> dict:
    summary = dict(value.get("summary") or {})
    summary.pop("baseline_sha256", None)
    return {
        "schema": value.get("schema"),
        "scope": value.get("scope"),
        "verdict": value.get("verdict"),
        "assessed": value.get("assessed"),
        "projection_custody": value.get("projection_custody"),
        "rows": value.get("rows"),
        "coverage": value.get("coverage"),
        "summary": summary,
        "limitations": value.get("limitations"),
    }


def _semantic_findings(root: Mapping[str, Any], roles: list[dict]) -> set[str]:
    findings: set[str] = set()
    for role in roles:
        if role["state"] not in _ROLE_STATES[role["role"]]:
            findings.add("invalid_role_state")
        if role["state"] in {"learning", "listening"}:
            findings.add("transitional_port_state")
    forwarding = [row for row in roles if row["state"] == "forwarding"]
    if not forwarding:
        findings.add("no_forwarding_path")
    root_paths = [row for row in roles if row["role"] in {"root", "master"}]
    if root.get("is_root") is True and root_paths:
        findings.add("unexpected_root_path")
    if root.get("is_root") is False and not root_paths:
        findings.add("root_path_missing")
    return findings


def compute_stp_topology_baseline(observations: Any, devices: Any = None) -> dict:
    """Normalize a complete per-host observation set into one strict embedded baseline."""
    source = observations if isinstance(observations, dict) else {}
    source_roster, source_roster_valid = _device_roster(source)
    roster, roster_valid = _device_roster(devices)
    if devices is None:
        roster, roster_valid = source_roster, source_roster_valid
    source_by_fold = {
        host.casefold(): source[host] for host in source_roster
    } if source_roster_valid else {}
    roster_folded = {host.casefold() for host in roster}
    if not roster_valid or not source_roster_valid or len(source) > _MAX_HOSTS \
            or set(source_by_fold) - roster_folded:
        return _unavailable_baseline()
    if not roster and source:
        return _unavailable_baseline()

    rows: list[dict] = []
    coverage: list[dict] = []
    for host in sorted(roster, key=lambda item: (item.casefold(), item)):
        observation = source_by_fold.get(host.casefold())
        valid, _reason = validate_stp_topology_observation(observation)
        if not valid:
            cell = {
                "switch": host,
                "status": "not_verified",
                "state_capture_state": "missing",
                "detail_capture_state": "missing",
                "explicit_no_subject": False,
                "state_instance_count": 0,
                "role_candidate_count": 0,
                "role_parsed_count": 0,
                "detail_instance_count": 0,
                "counter_candidate_count": 0,
                "counter_parsed_count": 0,
                "finding_codes": ["observation_malformed"],
                "projection_sha256": _sha({"switch": host, "valid": False}),
            }
            coverage.append(cell)
            continue

        if observation["explicit_no_subject"]:
            finding_codes = sorted(set(observation["finding_codes"]))
            coverage.append({
                "switch": host,
                "status": "not_verified" if finding_codes else "not_applicable",
                "state_capture_state": observation["state_capture_state"],
                "detail_capture_state": observation["detail_capture_state"],
                "explicit_no_subject": True,
                "state_instance_count": 0,
                "role_candidate_count": 0,
                "role_parsed_count": 0,
                "detail_instance_count": 0,
                "counter_candidate_count": 0,
                "counter_parsed_count": 0,
                "finding_codes": finding_codes,
                "projection_sha256": _sha(observation),
            })
            continue

        roots = {
            (row["namespace"], row["instance"]): row for row in observation["roots"]
        }
        roles: Dict[Tuple[str, str], list[dict]] = {}
        for role in observation["roles"]:
            roles.setdefault((role["namespace"], role["instance"]), []).append(role)
        counters = {
            (row["namespace"], row["instance"]): row
            for row in observation["topology_changes"]
        }
        host_statuses = []
        for key in sorted(roots):
            root = roots[key]
            instance_roles = sorted(
                roles.get(key, []),
                key=lambda row: (row["interface"].casefold(), row["interface"]),
            )
            counter = counters.get(key)
            finding_codes = set(observation["finding_codes"])
            if type(root.get("root_priority")) is not int \
                    or type(root.get("bridge_priority")) is not int \
                    or not root.get("root_address"):
                finding_codes.add("root_evidence_incomplete")
            if not instance_roles:
                finding_codes.add("role_evidence_missing")
            if counter is None:
                finding_codes.add("topology_counter_missing")
            semantic = _semantic_findings(root, instance_roles)
            finding_codes.update(semantic)
            coverage_findings = finding_codes - {
                "invalid_role_state", "transitional_port_state", "no_forwarding_path",
                "root_path_missing", "unexpected_root_path",
            }
            status = (
                "not_verified" if coverage_findings else
                "degraded" if semantic else
                "assessed"
            )
            host_statuses.append(status)
            port_roles = [
                {
                    "interface": role["interface"],
                    "role": role["role"],
                    "state": role["state"],
                }
                for role in instance_roles
            ]
            rows.append({
                "switch": host,
                "namespace": key[0],
                "instance": key[1],
                "root_address": root["root_address"],
                "root_priority": root["root_priority"],
                "bridge_priority": root["bridge_priority"],
                "is_root": root["is_root"],
                "port_roles": port_roles,
                "forwarding_paths": sorted(
                    role["interface"] for role in instance_roles
                    if role["state"] == "forwarding"
                ),
                "blocked_paths": sorted(
                    role["interface"] for role in instance_roles
                    if role["state"] == "blocked"
                ),
                "topology_change_count": counter["count"] if counter else None,
                "topology_change_last_change": counter["last_change"] if counter else "",
                "status": status,
                "finding_codes": sorted(finding_codes),
                "source_key": f"stp_topology_observations.{host}.{key[0]}.{key[1]}",
                "projection_custody": "embedded_unverified",
            })

        status = (
            "not_verified" if "not_verified" in host_statuses
            or bool(observation["finding_codes"]) else
            "degraded" if "degraded" in host_statuses else
            "assessed" if host_statuses else
            "not_verified"
        )
        coverage.append({
            "switch": host,
            "status": status,
            "state_capture_state": observation["state_capture_state"],
            "detail_capture_state": observation["detail_capture_state"],
            "explicit_no_subject": False,
            "state_instance_count": observation["state_instance_count"],
            "role_candidate_count": observation["role_candidate_count"],
            "role_parsed_count": observation["role_parsed_count"],
            "detail_instance_count": observation["detail_instance_count"],
            "counter_candidate_count": observation["counter_candidate_count"],
            "counter_parsed_count": observation["counter_parsed_count"],
            "finding_codes": sorted(set(observation["finding_codes"])),
            "projection_sha256": _sha(observation),
        })

    rows.sort(key=lambda row: (
        row["switch"].casefold(), row["switch"], row["namespace"], row["instance"]
    ))
    coverage.sort(key=lambda row: (row["switch"].casefold(), row["switch"]))
    row_counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    if coverage_counts["not_verified"] or row_counts["not_verified"]:
        verdict = "INDETERMINATE"
    elif coverage_counts["degraded"] or row_counts["degraded"]:
        verdict = "DEGRADED"
    elif row_counts["assessed"]:
        verdict = "CLEAR"
    elif coverage and coverage_counts["not_applicable"] == len(coverage):
        verdict = "NOT_APPLICABLE"
    else:
        verdict = "INDETERMINATE"
    result = {
        "schema": STP_TOPOLOGY_BASELINE_SCHEMA,
        "scope": deepcopy(_SCOPE),
        "verdict": verdict,
        "assessed": verdict in {"CLEAR", "DEGRADED"},
        "projection_custody": "embedded_unverified",
        "rows": rows,
        "coverage": coverage,
        "summary": {
            "n_hosts": len(coverage),
            "n_subject_hosts": sum(cell["status"] != "not_applicable" for cell in coverage),
            "n_rows": len(rows),
            "n_assessed": row_counts["assessed"],
            "n_degraded": row_counts["degraded"],
            "n_not_verified": row_counts["not_verified"],
            "by_status": {status: int(row_counts[status]) for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
            },
            "baseline_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    valid, _reason = _validate_baseline_structure(result)
    return result if valid else _unavailable_baseline()


def _valid_port_role(row: Any) -> bool:
    return bool(
        isinstance(row, dict) and set(row) == {"interface", "role", "state"}
        and _safe_string(row.get("interface"), 128) and is_valid_iface(row["interface"])
        and row.get("role") in _ROLES and row.get("state") in _STATES
    )


def _validate_baseline_structure(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != _BASELINE_KEYS \
            or value.get("schema") != STP_TOPOLOGY_BASELINE_SCHEMA:
        return False, "baseline_schema_or_keys_invalid"
    if value.get("scope") != _SCOPE or value.get("limitations") != _LIMITATIONS \
            or value.get("verdict") not in {
                "CLEAR", "DEGRADED", "INDETERMINATE", "NOT_APPLICABLE"
            } or type(value.get("assessed")) is not bool \
            or value.get("projection_custody") != "embedded_unverified":
        return False, "baseline_metadata_invalid"
    rows, coverage, summary = value.get("rows"), value.get("coverage"), value.get("summary")
    if not isinstance(rows, list) or len(rows) > _MAX_PORT_ROWS \
            or not isinstance(coverage, list) or len(coverage) > _MAX_HOSTS \
            or not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "baseline_denominator_invalid"
    digest = summary.get("baseline_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or digest != _sha(_baseline_payload(value)):
        return False, "baseline_digest_mismatch"

    row_keys = []
    row_counts = Counter()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _BASELINE_ROW_KEYS \
                or not _safe_string(row.get("switch"), 128) \
                or not _instance_valid(row.get("namespace"), row.get("instance")) \
                or row.get("status") not in _ROW_STATUSES \
                or row.get("projection_custody") != "embedded_unverified" \
                or type(row.get("is_root")) is not bool:
            return False, "baseline_row_invalid"
        for field in ("root_priority", "bridge_priority"):
            leaf = row.get(field)
            if leaf is not None and (type(leaf) is not int or not 0 <= leaf <= 65_535):
                return False, "baseline_root_priority_invalid"
        if not _safe_string(row.get("root_address"), 64) \
                or not _safe_string(row.get("topology_change_last_change"), 128):
            return False, "baseline_row_text_invalid"
        counter = row.get("topology_change_count")
        if counter is not None and (type(counter) is not int or not 0 <= counter <= _MAX_COUNTER):
            return False, "baseline_counter_invalid"
        port_roles = row.get("port_roles")
        if not isinstance(port_roles, list) or len(port_roles) > _MAX_PORT_ROWS \
                or not all(_valid_port_role(item) for item in port_roles):
            return False, "baseline_port_role_invalid"
        role_interfaces = [item["interface"] for item in port_roles]
        if len({item.casefold() for item in role_interfaces}) != len(role_interfaces) \
                or port_roles != sorted(port_roles, key=lambda item: (
                    item["interface"].casefold(), item["interface"])):
            return False, "baseline_port_role_identity_invalid"
        forwarding, blocked = row.get("forwarding_paths"), row.get("blocked_paths")
        if not isinstance(forwarding, list) or not isinstance(blocked, list) \
                or forwarding != sorted(set(forwarding)) or blocked != sorted(set(blocked)) \
                or forwarding != sorted(
                    item["interface"] for item in port_roles if item["state"] == "forwarding") \
                or blocked != sorted(
                    item["interface"] for item in port_roles if item["state"] == "blocked"):
            return False, "baseline_path_projection_invalid"
        codes = row.get("finding_codes")
        if not isinstance(codes, list) or codes != sorted(set(codes)) \
                or not set(codes) <= _FINDING_CODES:
            return False, "baseline_row_findings_invalid"
        expected_source = (
            f"stp_topology_observations.{row['switch']}.{row['namespace']}.{row['instance']}"
        )
        if row.get("source_key") != expected_source:
            return False, "baseline_row_source_invalid"
        row_keys.append((row["switch"].casefold(), row["namespace"], row["instance"]))
        row_counts[row["status"]] += 1
    if len(set(row_keys)) != len(row_keys) or rows != sorted(rows, key=lambda row: (
            row["switch"].casefold(), row["switch"], row["namespace"], row["instance"])):
        return False, "baseline_row_identity_or_order_invalid"

    coverage_hosts = []
    coverage_counts = Counter()
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS \
                or not _safe_string(cell.get("switch"), 128) \
                or cell.get("status") not in _COVERAGE_STATUSES \
                or cell.get("state_capture_state") not in _CAPTURE_STATES \
                or cell.get("detail_capture_state") not in _CAPTURE_STATES \
                or type(cell.get("explicit_no_subject")) is not bool:
            return False, "baseline_coverage_invalid"
        for field in (
                "state_instance_count", "role_candidate_count", "role_parsed_count",
                "detail_instance_count", "counter_candidate_count", "counter_parsed_count"):
            if type(cell.get(field)) is not int or cell[field] < 0:
                return False, "baseline_coverage_count_invalid"
        codes = cell.get("finding_codes")
        if not isinstance(codes, list) or codes != sorted(set(codes)) \
                or not set(codes) <= _FINDING_CODES \
                or not isinstance(cell.get("projection_sha256"), str) \
                or not re.fullmatch(r"[0-9a-f]{64}", cell["projection_sha256"]):
            return False, "baseline_coverage_findings_or_digest_invalid"
        coverage_hosts.append(cell["switch"].casefold())
        coverage_counts[cell["status"]] += 1
    if len(set(coverage_hosts)) != len(coverage_hosts) \
            or coverage != sorted(coverage, key=lambda row: (
                row["switch"].casefold(), row["switch"])):
        return False, "baseline_coverage_identity_or_order_invalid"
    if set(host for host, _namespace_value, _instance in row_keys) - set(coverage_hosts):
        return False, "baseline_row_outside_coverage"

    if summary != {
            "n_hosts": len(coverage),
            "n_subject_hosts": sum(cell["status"] != "not_applicable" for cell in coverage),
            "n_rows": len(rows),
            "n_assessed": row_counts["assessed"],
            "n_degraded": row_counts["degraded"],
            "n_not_verified": row_counts["not_verified"],
            "by_status": {status: int(row_counts[status]) for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
            },
            "baseline_sha256": digest,
    }:
        return False, "baseline_summary_mismatch"
    if value["assessed"] is not (value["verdict"] in {"CLEAR", "DEGRADED"}):
        return False, "baseline_assessed_mismatch"
    return True, "ok"


def _legacy_roots_reconcile(baseline: Mapping[str, Any], legacy_roots: Any) -> bool:
    """Require the additive root rows to agree with the unchanged legacy root owner."""
    if not isinstance(legacy_roots, dict):
        return False
    expected = {}
    for row in baseline.get("rows", []):
        if not isinstance(row, dict):
            return False
        expected[(row["switch"], row["namespace"], row["instance"])] = {
            "root_address": row["root_address"],
            "root_priority": row["root_priority"],
            "bridge_priority": row["bridge_priority"],
            "is_root": row["is_root"],
        }
    actual = {}
    for host_value, instances in legacy_roots.items():
        host = _text(host_value, 128)
        if not host or not isinstance(instances, dict):
            return False
        for instance_value, raw in instances.items():
            instance = _text(instance_value, 8)
            if not instance or not isinstance(raw, dict) or type(raw.get("is_mst")) is not bool:
                return False
            actual[(
                host,
                "mst_instance" if raw["is_mst"] else "pvst_vlan",
                instance,
            )] = {
                "root_address": _text(raw.get("root_address"), 64),
                "root_priority": raw.get("root_priority")
                if type(raw.get("root_priority")) is int else None,
                "bridge_priority": raw.get("bridge_priority")
                if type(raw.get("bridge_priority")) is int else None,
                "is_root": raw.get("is_root") if type(raw.get("is_root")) is bool else False,
            }
    return actual == expected


def validate_stp_topology_baseline(
        value: Any,
        *,
        observations: Any = None,
        legacy_roots: Any = None,
        devices: Any = None) -> dict:
    """Validate, and optionally reconcile, one serialized STP topology baseline."""
    present = value is not None
    valid, reason = _validate_baseline_structure(value)
    if valid and observations is not None:
        expected = compute_stp_topology_baseline(observations, devices)
        if value != expected:
            valid, reason = False, "baseline_does_not_reconcile_to_observations"
    if valid and legacy_roots is not None and not _legacy_roots_reconcile(value, legacy_roots):
        valid, reason = False, "baseline_does_not_reconcile_to_legacy_roots"
    baseline = deepcopy(value) if valid else {}
    rows = baseline.get("rows", []) if valid else []
    index = {
        (row["switch"], row["namespace"], row["instance"]): row
        for row in rows
    } if valid else {}
    return {
        "present": present,
        "valid": valid,
        "reason": reason,
        "source_bound": False,
        "baseline": baseline,
        "rows": rows,
        "index": index,
        "coverage": baseline.get("coverage", []) if valid else [],
        "projection_sha256": (
            "sha256:" + baseline["summary"]["baseline_sha256"] if valid else ""
        ),
    }


__all__ = [
    "STP_TOPOLOGY_BASELINE_SCHEMA",
    "STP_TOPOLOGY_OBSERVATION_SCHEMA",
    "compute_stp_topology_baseline",
    "produce_stp_topology_observation",
    "validate_stp_topology_baseline",
    "validate_stp_topology_observation",
]
