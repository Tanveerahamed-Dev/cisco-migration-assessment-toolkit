"""Strict additive VTP/VLAN database evidence for Release-1 cutover assurance.

The protected ``vtp_safety_baseline/1`` owner remains unchanged.  This owner adds the
source-bound leaves that owner deliberately did not claim: a canonical VLAN database
digest, pruning configuration state, and authentication *presence*.  Raw command text,
capture paths, VTP passwords, password hashes, and device-reported authentication digests
are never serialized.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from cisco_toolkit.input_custody import read_text as read_custodied_text


VTP_EXTENDED_EVIDENCE_SCHEMA = "vtp_extended_evidence/1"
VTP_EXTENDED_OWNER_VERSION = "1"

_COMMANDS = ("show vtp status", "show vlan brief", "show running-config")
_HIGH_REVISION_THRESHOLD = 100
_MAX_HOSTS = 4096
_MAX_INSPECTIONS = 1_000_000
_MAX_BODY_CHARS = 8_000_000
_MAX_LINES = 100_000
_MAX_VLANS = 4094

_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt", "unreadable",
    "not_observed", "inspection_missing", "inspection_duplicate",
}
_PARSER_STATUSES = {"complete", "explicit_no_subject", "not_verified", "rejected"}
_ROW_STATUSES = {"healthy", "unsafe", "not_verified"}
_PRUNING_STATES = {"configured_enabled", "configured_disabled", "not_configured"}
_MODES = {"server", "client", "transparent", "off"}
_FINDING_CODES = {
    "platform_unsupported",
    "capture_not_verified",
    "vtp_status_parser_not_verified",
    "vlan_database_parser_not_verified",
    "running_config_parser_not_verified",
    "active_mode_fields_not_verified",
    "high_revision_server",
    "authentication_contradiction",
    "vlan_database_digest_contradiction",
}
_ROOT_KEYS = {
    "schema", "owner_version", "family", "owns_score", "owns_verdict",
    "projection_custody", "rows", "coverage", "summary", "limitations",
}
_ROW_KEYS = {
    "switch", "platform", "status", "mode", "mode_present", "domain",
    "domain_present", "version", "version_present", "revision",
    "revision_present", "database_identity", "vlan_database_digest", "vlan_count",
    "pruning_state", "authentication_configured", "projection_custody", "findings",
}
_COVERAGE_KEYS = {
    "switch", "platform", "status", "commands", "projection_sha256", "finding_codes",
}
_COMMAND_RECEIPT_KEYS = {
    "capture_status", "parser_status", "candidate_count", "parsed_count",
    "rejected_count", "source_sha256",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_healthy", "n_unsafe", "n_not_verified", "n_active",
    "n_high_revision_servers", "n_authentication_contradictions",
    "n_vlan_digest_contradictions", "by_status", "baseline_sha256",
}
_LIMITATIONS = [
    "IOS/IOS-XE and NX-OS text variants are supported only when all three exact command captures have unique integrity-ok receipts.",
    "The VLAN database digest is derived from sorted VLAN id/name/status rows; it does not prove advertisement reachability, convergence, or per-port membership.",
    "Authentication records configured presence only. Passwords, password hashes, and device-reported authentication digests are never retained.",
    "A revision decrease is only an observation; only exact-subject revision_reset intent in cutover_change_intent/1 may classify and reconcile it as a planned reset.",
]

_EXPLICIT_NO_VTP = (
    re.compile(r"^vtp is disabled[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp feature is disabled[.!]?$", re.IGNORECASE),
    re.compile(r"^(?:feature )?vtp (?:feature )?is not enabled[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp is not supported on this platform[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp (?:feature )?(?:is )?not supported[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp feature (?:is )?not available[.!]?$", re.IGNORECASE),
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    try:
        return hashlib.sha256(_json_bytes(value)).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, MemoryError):
        return ""


def _body_sha(body: str) -> str:
    try:
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    except (UnicodeEncodeError, MemoryError):
        return ""


def _text(value: Any, limit: int = 256) -> str:
    if not isinstance(value, str) or len(value) > limit:
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    result = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in result):
        return ""
    return result


def _safe_text(value: Any, limit: int = 256) -> bool:
    return isinstance(value, str) and value == _text(value, limit)


def _finding(code: str, note: str) -> dict:
    return {"code": code, "note": note}


def _platforms(devices: Any) -> Tuple[Dict[str, str], bool]:
    if devices is None:
        return {}, True
    if isinstance(devices, Mapping):
        source: Iterable[Any] = [
            {"hostname": key, **(dict(value) if isinstance(value, Mapping) else {})}
            for key, value in devices.items()
        ]
    elif isinstance(devices, list):
        source = devices
    else:
        return {}, False
    result: Dict[str, str] = {}
    for item in source:
        if not isinstance(item, Mapping):
            return {}, False
        host = _text(item.get("hostname") or item.get("switch"), 128)
        if not host:
            return {}, False
        if host.casefold() in {value.casefold() for value in result}:
            return {}, False
        result[host] = _text(item.get("platform"), 80)
    return result, len(result) <= _MAX_HOSTS


def _platform_variant(value: Any) -> str:
    platform = re.sub(r"[^a-z0-9]", "", _text(value, 80).casefold())
    if platform in {"nxos", "cisconxos", "nexus"}:
        return "nxos"
    if platform in {"ios", "iosxe", "ciscoios", "ciscoiosxe", "ciscoxe"}:
        return "ios"
    return ""


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    receipt = capture_integrity if isinstance(capture_integrity, Mapping) else {}
    inspections = receipt.get("inspections")
    if not isinstance(inspections, list) or len(inspections) > _MAX_INSPECTIONS:
        return {}, set()
    index: Dict[Tuple[str, str], str] = {}
    duplicates: set = set()
    for raw in inspections:
        if not isinstance(raw, Mapping):
            continue
        host = _text(raw.get("host"), 128)
        command = _text(raw.get("command"), 128)
        status = _text(raw.get("status"), 32)
        if not host or command not in _COMMANDS or status not in _CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture_status(index: Mapping[Tuple[str, str], str], duplicates: set,
                    host: str, command: str, attempted: bool) -> str:
    if not attempted:
        return "not_observed"
    key = (host, command)
    if key in duplicates:
        return "inspection_duplicate"
    return index.get(key, "inspection_missing")


def _read(mapping: Mapping[str, Any], command: str) -> Tuple[str, str]:
    path = mapping.get(command)
    if not isinstance(path, (str, bytes)):
        return "", "not_observed"
    try:
        body = read_custodied_text(path, encoding="utf-8", errors="ignore")
    except Exception:
        return "", "unreadable"
    if not isinstance(body, str) or len(body) > _MAX_BODY_CHARS:
        return "", "unreadable"
    return body, "ok"


def _label_value(line: str, labels: Tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.match(rf"^{re.escape(label)}\b(.*)$", line, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            return value[1:].strip() if value.startswith(":") else value
    return None


def _parse_vtp_status(body: str) -> dict:
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return {"parser_status": "rejected", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 1}
    meaningful = [line.strip() for line in lines if line.strip()]
    if len(meaningful) == 1 and any(pattern.fullmatch(meaningful[0])
                                    for pattern in _EXPLICIT_NO_VTP):
        return {
            "parser_status": "explicit_no_subject", "candidate_count": 1,
            "parsed_count": 1, "rejected_count": 0, "mode": "off",
            "mode_present": True, "domain": "", "domain_present": False,
            "version": "", "version_present": False, "revision": 0,
            "revision_present": False,
        }

    labels = {
        "mode": ("VTP Operating Mode", "Operating Mode"),
        "domain": ("VTP Domain Name", "Domain Name"),
        "version": ("VTP version running",),
        "revision": ("Configuration Revision",),
    }
    values: Dict[str, List[str]] = {field: [] for field in labels}
    for raw in meaningful:
        for field, variants in labels.items():
            value = _label_value(raw, variants)
            if value is not None:
                values[field].append(value)
                break
    candidate_count = sum(bool(items) for items in values.values())
    if any(len(items) != 1 for items in values.values()):
        return {"parser_status": "rejected", "candidate_count": candidate_count,
                "parsed_count": 0, "rejected_count": 1}
    raw_mode = values["mode"][0].casefold().split(None, 1)[0]
    mode = raw_mode if raw_mode in _MODES else ""
    raw_domain = values["domain"][0]
    if raw_domain.casefold() in {"null", "none", "(none)", "not configured"}:
        raw_domain = ""
    domain_ok = not raw_domain or bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", raw_domain))
    version_match = re.fullmatch(r"([123])(?:\s+.*)?", values["version"][0])
    revision_ok = bool(re.fullmatch(r"\d{1,10}", values["revision"][0]))
    revision = int(values["revision"][0]) if revision_ok else 0
    revision_ok = revision_ok and revision <= 4_294_967_295
    if not mode or not domain_ok or not version_match or not revision_ok:
        return {"parser_status": "rejected", "candidate_count": candidate_count,
                "parsed_count": 0, "rejected_count": 1}
    return {
        "parser_status": "complete", "candidate_count": candidate_count,
        "parsed_count": 1, "rejected_count": 0, "mode": mode,
        "mode_present": True, "domain": raw_domain, "domain_present": True,
        "version": version_match.group(1), "version_present": True,
        "revision": revision, "revision_present": True,
    }


_VLAN_HEADER = re.compile(r"^VLAN\s+Name\s+Status\s+Ports\s*$", re.IGNORECASE)
_VLAN_ROW = re.compile(
    r"^\s*(\d{1,4})\s+(\S{1,64})\s+(active|act/unsup|suspended?|shutdown|unsupported)\b",
    re.IGNORECASE,
)


def _parse_vlan_brief(body: str) -> dict:
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return {"parser_status": "rejected", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 1, "vlans": []}
    header_indexes = [index for index, line in enumerate(lines)
                      if _VLAN_HEADER.fullmatch(line.strip())]
    if len(header_indexes) != 1:
        return {"parser_status": "rejected", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 1, "vlans": []}
    rows: List[dict] = []
    candidates = rejected = 0
    for raw in lines[header_indexes[0] + 1:]:
        stripped = raw.strip()
        if not stripped or set(stripped) == {"-"}:
            continue
        if re.match(r"^(?:VLAN\s+Type|Remote SPAN|Primary\s+Secondary)\b", stripped,
                    re.IGNORECASE):
            break
        if not re.match(r"^\d", stripped):
            continue
        candidates += 1
        match = _VLAN_ROW.match(raw)
        if not match:
            rejected += 1
            continue
        vlan_id = int(match.group(1))
        name = match.group(2)
        status = match.group(3).casefold()
        if not 1 <= vlan_id <= 4094 or not _safe_text(name, 64):
            rejected += 1
            continue
        rows.append({"vlan_id": vlan_id, "name": name, "status": status})
    unique = {row["vlan_id"] for row in rows}
    if not rows or rejected or len(unique) != len(rows) or len(rows) > _MAX_VLANS:
        return {"parser_status": "rejected", "candidate_count": candidates,
                "parsed_count": 0, "rejected_count": max(1, rejected), "vlans": []}
    rows.sort(key=lambda row: row["vlan_id"])
    return {"parser_status": "complete", "candidate_count": candidates,
            "parsed_count": len(rows), "rejected_count": 0, "vlans": rows}


def _parse_running_config(body: str, platform_variant: str = "") -> dict:
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return {"parser_status": "rejected", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 1}
    pruning: List[bool] = []
    authentication: List[bool] = []
    rejected = candidates = 0
    hostname_count = sum(
        bool(re.fullmatch(r"hostname\s+\S+", line.strip(), re.IGNORECASE))
        for line in lines
    )
    end_count = sum(line.strip().casefold() == "end" for line in lines)
    command_headers = [
        line.strip() for line in lines
        if line.strip().casefold().startswith("!command:")
    ]
    nxos_headers = [
        line for line in command_headers
        if re.fullmatch(
            r"!command:\s*show\s+(?:run|running-config)\s*",
            line,
            re.IGNORECASE,
        )
    ]
    # IOS/IOS-XE full configurations have one terminal ``end``.  NX-OS owns a
    # different full-capture envelope: an exact ``!Command: show running-config``
    # header and no column-zero ``end`` (capture_integrity.py pins that real
    # output).  Bind the envelope to the declared supported platform so an IOS
    # body cannot borrow the NX-OS truncation exception, and reject concatenated
    # captures rather than treating their union as one observation.
    nxos_envelope = len(nxos_headers) == 1
    expected_nxos = platform_variant == "nxos"
    expected_ios = platform_variant == "ios"
    envelope_invalid = (
        hostname_count != 1
        or len(command_headers) != len(nxos_headers)
        or len(nxos_headers) > 1
        or (expected_nxos and (not nxos_envelope or end_count != 0))
        or (expected_ios and (nxos_envelope or end_count != 1))
        or (not expected_nxos and not expected_ios
            and ((nxos_envelope and end_count != 0)
                 or (not nxos_envelope and end_count != 1)))
    )
    if envelope_invalid:
        return {"parser_status": "rejected", "candidate_count": 0,
                "parsed_count": 0, "rejected_count": 1}
    for raw in lines:
        line = raw.strip()
        folded = line.casefold()
        if folded == "vtp pruning":
            candidates += 1
            pruning.append(True)
        elif folded == "no vtp pruning":
            candidates += 1
            pruning.append(False)
        elif folded.startswith("vtp pruning") or folded.startswith("no vtp pruning"):
            candidates += 1
            rejected += 1
        elif re.fullmatch(r"vtp\s+password\s+\S+(?:\s+\S+)*", line, re.IGNORECASE):
            candidates += 1
            authentication.append(True)
        elif folded == "no vtp password":
            candidates += 1
            authentication.append(False)
        elif folded.startswith("vtp password") or folded.startswith("no vtp password"):
            candidates += 1
            rejected += 1
    pruning_values = set(pruning)
    authentication_values = set(authentication)
    if rejected or len(pruning) > 1 or len(authentication) > 1 \
            or len(pruning_values) > 1 or len(authentication_values) > 1:
        return {"parser_status": "rejected", "candidate_count": candidates,
                "parsed_count": 0, "rejected_count": max(1, rejected)}
    pruning_state = (
        "configured_enabled" if pruning_values == {True}
        else "configured_disabled" if pruning_values == {False}
        else "not_configured"
    )
    return {
        "parser_status": "complete", "candidate_count": candidates,
        "parsed_count": candidates, "rejected_count": 0,
        "pruning_state": pruning_state,
        "authentication_configured": authentication_values == {True},
    }


def _command_receipt(capture_status: str, parsed: Mapping[str, Any], body: str) -> dict:
    parser_status = _text(parsed.get("parser_status"), 32) or "not_verified"
    return {
        "capture_status": capture_status,
        "parser_status": parser_status,
        "candidate_count": parsed.get("candidate_count", 0)
        if type(parsed.get("candidate_count", 0)) is int else 0,
        "parsed_count": parsed.get("parsed_count", 0)
        if type(parsed.get("parsed_count", 0)) is int else 0,
        "rejected_count": parsed.get("rejected_count", 0)
        if type(parsed.get("rejected_count", 0)) is int else 0,
        "source_sha256": _body_sha(body) if capture_status == "ok" and body else "",
    }


def _row_projection(row: Mapping[str, Any]) -> dict:
    return {key: copy.deepcopy(row[key]) for key in sorted(_ROW_KEYS - {"projection_custody"})}


def _baseline_payload(value: Mapping[str, Any]) -> dict:
    payload = copy.deepcopy(dict(value))
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("baseline_sha256", None)
    return payload


def _set_row_unsafe(row: dict, code: str, note: str) -> None:
    if row["status"] == "not_verified":
        return
    if not any(item.get("code") == code for item in row["findings"]):
        row["findings"].append(_finding(code, note))
    row["findings"].sort(key=lambda item: item["code"])
    row["status"] = "unsafe"


def _empty_row(host: str, platform: str) -> dict:
    return {
        "switch": host, "platform": platform, "status": "not_verified",
        "mode": "off", "mode_present": False, "domain": "", "domain_present": False,
        "version": "", "version_present": False, "revision": 0,
        "revision_present": False, "database_identity": "",
        "vlan_database_digest": "", "vlan_count": 0,
        "pruning_state": "not_configured", "authentication_configured": False,
        "projection_custody": "current_run_source_bound", "findings": [],
    }


def _unavailable_evidence() -> dict:
    result = {
        "schema": VTP_EXTENDED_EVIDENCE_SCHEMA,
        "owner_version": VTP_EXTENDED_OWNER_VERSION,
        "family": "vtp_safety", "owns_score": False, "owns_verdict": False,
        "projection_custody": "embedded_unverified", "rows": [], "coverage": [],
        "summary": {
            "n_hosts": 0, "n_healthy": 0, "n_unsafe": 0, "n_not_verified": 0,
            "n_active": 0, "n_high_revision_servers": 0,
            "n_authentication_contradictions": 0,
            "n_vlan_digest_contradictions": 0,
            "by_status": {"healthy": 0, "unsafe": 0, "not_verified": 0},
            "baseline_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    return result


class _CurrentRunVtpExtendedEvidence(dict):
    """Process-local source marker whose original semantic digest cannot be re-sealed."""

    def __init__(self, value: dict):
        super().__init__(value)
        self._original_digest = value.get("summary", {}).get("baseline_sha256", "")

    def __copy__(self):
        return embedded_vtp_extended_evidence(self)

    def __deepcopy__(self, memo):
        result = embedded_vtp_extended_evidence(self)
        memo[id(self)] = result
        return result


def compute_vtp_extended_evidence(all_cmd_to_files: Any, capture_integrity: Any,
                                  devices: Any = None) -> dict:
    """Compute the strict, path-free, secret-free three-command VTP evidence owner."""
    if not isinstance(all_cmd_to_files, Mapping):
        return _unavailable_evidence()
    platforms, device_valid = _platforms(devices)
    mapping_hosts: List[str] = []
    for host, mapping in all_cmd_to_files.items():
        if not isinstance(host, str) or _text(host, 128) != host or not isinstance(mapping, Mapping):
            return _unavailable_evidence()
        mapping_hosts.append(host)
    hosts = sorted(set(platforms) | set(mapping_hosts), key=lambda value: (value.casefold(), value))
    if (not device_valid or len(hosts) > _MAX_HOSTS
            or len({host.casefold() for host in hosts}) != len(hosts)):
        return _unavailable_evidence()

    inspections, duplicates = _inspection_index(capture_integrity)
    rows: List[dict] = []
    coverage: List[dict] = []
    for host in hosts:
        mapping = all_cmd_to_files.get(host)
        mapping = mapping if isinstance(mapping, Mapping) else {}
        parsed: Dict[str, dict] = {}
        receipts: Dict[str, dict] = {}
        for command in _COMMANDS:
            attempted = command in mapping
            capture_status = _capture_status(inspections, duplicates, host, command, attempted)
            body, read_status = _read(mapping, command)
            if read_status != "ok":
                capture_status = read_status
            if capture_status != "ok":
                result = {"parser_status": "not_verified", "candidate_count": 0,
                          "parsed_count": 0, "rejected_count": 0}
            elif command == "show vtp status":
                result = _parse_vtp_status(body)
            elif command == "show vlan brief":
                result = _parse_vlan_brief(body)
            else:
                result = _parse_running_config(
                    body, _platform_variant(platforms.get(host, "")))
            parsed[command] = result
            receipts[command] = _command_receipt(capture_status, result, body)

        row = _empty_row(host, platforms.get(host, ""))
        failures: List[dict] = []
        if not _platform_variant(row["platform"]):
            failures.append(_finding(
                "platform_unsupported",
                "This subject is outside the declared IOS/IOS-XE and NX-OS source variants.",
            ))
        for command, code, label in (
            ("show vtp status", "vtp_status_parser_not_verified", "VTP status"),
            ("show vlan brief", "vlan_database_parser_not_verified", "VLAN database"),
            ("show running-config", "running_config_parser_not_verified", "running configuration"),
        ):
            receipt = receipts[command]
            if receipt["capture_status"] != "ok":
                failures.append(_finding(
                    "capture_not_verified",
                    f"{label} evidence lacks one unique integrity-ok {command} receipt.",
                ))
            elif receipt["parser_status"] not in {"complete", "explicit_no_subject"}:
                failures.append(_finding(code, f"The strict {label} parser withheld this subject."))

        if not failures:
            status = parsed["show vtp status"]
            vlan = parsed["show vlan brief"]
            config = parsed["show running-config"]
            for field in (
                "mode", "mode_present", "domain", "domain_present", "version",
                "version_present", "revision", "revision_present",
            ):
                row[field] = status[field]
            row["database_identity"] = (
                f"domain={row['domain']};version={row['version']}"
                if row["domain_present"] and row["version_present"] else "vtp=disabled"
            )
            row["vlan_database_digest"] = "sha256:" + _sha({"vlans": vlan["vlans"]})
            row["vlan_count"] = len(vlan["vlans"])
            row["pruning_state"] = config["pruning_state"]
            row["authentication_configured"] = config["authentication_configured"]
            if row["mode"] in {"server", "client"} and not all((
                    row["domain_present"], bool(row["domain"]), row["version_present"],
                    row["revision_present"])):
                failures.append(_finding(
                    "active_mode_fields_not_verified",
                    "Active VTP mode lacks explicit domain, running-version, or revision evidence.",
                ))
            if not failures:
                row["status"] = "healthy"
                if row["mode"] == "server" and row["revision"] >= _HIGH_REVISION_THRESHOLD:
                    _set_row_unsafe(
                        row, "high_revision_server",
                        "The current VTP Server revision is at or above the bounded safety threshold.",
                    )
        if failures:
            row["status"] = "not_verified"
            row["findings"] = sorted(
                {item["code"]: item for item in failures}.values(), key=lambda item: item["code"])
        rows.append(row)
        coverage.append({
            "switch": host, "platform": platforms.get(host, ""), "status": row["status"],
            "commands": receipts, "projection_sha256": "", "finding_codes": [],
        })

    active_groups: Dict[str, List[dict]] = {}
    for row in rows:
        if row["status"] != "not_verified" and row["mode"] in {"server", "client"}:
            active_groups.setdefault(row["database_identity"], []).append(row)
    for identity, members in active_groups.items():
        if len(members) < 2:
            continue
        if len({row["authentication_configured"] for row in members}) > 1:
            for row in members:
                _set_row_unsafe(
                    row, "authentication_contradiction",
                    f"Active peers in {identity} disagree on authentication configured-presence.",
                )
        if len({row["vlan_database_digest"] for row in members}) > 1:
            for row in members:
                _set_row_unsafe(
                    row, "vlan_database_digest_contradiction",
                    f"Active peers in {identity} have contradictory canonical VLAN database digests.",
                )

    row_index = {row["switch"]: row for row in rows}
    for cell in coverage:
        row = row_index[cell["switch"]]
        cell["status"] = row["status"]
        cell["finding_codes"] = [item["code"] for item in row["findings"]]
        cell["projection_sha256"] = "sha256:" + _sha(_row_projection(row))

    counts = Counter(row["status"] for row in rows)
    finding_counts = Counter(
        item["code"] for row in rows for item in row["findings"]
    )
    result = {
        "schema": VTP_EXTENDED_EVIDENCE_SCHEMA,
        "owner_version": VTP_EXTENDED_OWNER_VERSION,
        "family": "vtp_safety", "owns_score": False, "owns_verdict": False,
        "projection_custody": "current_run_source_bound", "rows": rows,
        "coverage": coverage,
        "summary": {
            "n_hosts": len(rows), "n_healthy": counts["healthy"],
            "n_unsafe": counts["unsafe"], "n_not_verified": counts["not_verified"],
            "n_active": sum(row["mode"] in {"server", "client"} for row in rows),
            "n_high_revision_servers": finding_counts["high_revision_server"],
            "n_authentication_contradictions": finding_counts["authentication_contradiction"],
            "n_vlan_digest_contradictions": finding_counts["vlan_database_digest_contradiction"],
            "by_status": {token: counts[token] for token in ("healthy", "unsafe", "not_verified")},
            "baseline_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    return _CurrentRunVtpExtendedEvidence(result)


def _valid_sha(value: Any, *, prefixed: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    pattern = r"sha256:[0-9a-f]{64}" if prefixed else r"[0-9a-f]{64}"
    return bool(re.fullmatch(pattern, value))


def _structural_validation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != _ROOT_KEYS:
        return False, "extended_vtp_root_missing_or_malformed"
    if (value.get("schema") != VTP_EXTENDED_EVIDENCE_SCHEMA
            or value.get("owner_version") != VTP_EXTENDED_OWNER_VERSION
            or value.get("family") != "vtp_safety"
            or value.get("owns_score") is not False
            or value.get("owns_verdict") is not False
            or value.get("projection_custody") not in {
                "current_run_source_bound", "embedded_unverified"}):
        return False, "extended_vtp_owner_semantics_invalid"
    if value.get("limitations") != _LIMITATIONS:
        return False, "extended_vtp_limitations_invalid"
    rows, coverage, summary = value.get("rows"), value.get("coverage"), value.get("summary")
    if (not isinstance(rows, list) or not isinstance(coverage, list)
            or len(rows) > _MAX_HOSTS or len(rows) != len(coverage)):
        return False, "extended_vtp_denominator_invalid"
    if not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "extended_vtp_summary_invalid"

    row_hosts: List[str] = []
    validated_rows: List[dict] = []
    counts = Counter()
    finding_counts = Counter()
    active = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "extended_vtp_row_missing_or_malformed"
        host = row.get("switch")
        if (not _safe_text(host, 128) or not _safe_text(row.get("platform"), 80)
                or row.get("status") not in _ROW_STATUSES
                or row.get("mode") not in _MODES
                or type(row.get("mode_present")) is not bool
                or not _safe_text(row.get("domain"), 64)
                or type(row.get("domain_present")) is not bool
                or row.get("version") not in {"", "1", "2", "3"}
                or type(row.get("version_present")) is not bool
                or type(row.get("revision")) is not int or not 0 <= row["revision"] <= 4_294_967_295
                or type(row.get("revision_present")) is not bool
                or not _safe_text(row.get("database_identity"), 160)
                or (row.get("vlan_database_digest") != ""
                    and not _valid_sha(row.get("vlan_database_digest"), prefixed=True))
                or type(row.get("vlan_count")) is not int
                or not 0 <= row["vlan_count"] <= _MAX_VLANS
                or row.get("pruning_state") not in _PRUNING_STATES
                or type(row.get("authentication_configured")) is not bool
                or row.get("projection_custody") != value["projection_custody"]
                or not isinstance(row.get("findings"), list)):
            return False, "extended_vtp_row_identity_or_state_invalid"
        if row["status"] != "not_verified" and (
                not row["mode_present"] or not row["vlan_database_digest"]
                or not row["database_identity"] or row["vlan_count"] <= 0):
            return False, "extended_vtp_assessed_row_evidence_invalid"
        if row["mode"] in {"server", "client"} and row["status"] != "not_verified" and not all((
                row["domain_present"], row["domain"], row["version_present"],
                row["revision_present"])):
            return False, "extended_vtp_active_row_evidence_invalid"
        codes: List[str] = []
        for finding in row["findings"]:
            if (not isinstance(finding, dict) or set(finding) != {"code", "note"}
                    or finding.get("code") not in _FINDING_CODES
                    or not _safe_text(finding.get("note"), 500)):
                return False, "extended_vtp_finding_invalid"
            codes.append(finding["code"])
            finding_counts[finding["code"]] += 1
        if codes != sorted(set(codes)):
            return False, "extended_vtp_finding_order_invalid"
        platform_supported = bool(_platform_variant(row["platform"]))
        if (("platform_unsupported" in codes) is platform_supported
                or (not platform_supported and row["status"] != "not_verified")):
            return False, "extended_vtp_platform_support_invalid"
        unsafe_codes = {
            "high_revision_server", "authentication_contradiction",
            "vlan_database_digest_contradiction",
        }
        if (row["status"] == "unsafe") is not bool(set(codes) & unsafe_codes):
            return False, "extended_vtp_unsafe_state_invalid"
        if row["status"] == "healthy" and codes:
            return False, "extended_vtp_healthy_state_invalid"
        if row["status"] == "not_verified" and not codes:
            return False, "extended_vtp_not_verified_finding_invalid"
        expected_identity = (
            f"domain={row['domain']};version={row['version']}"
            if row["domain_present"] and row["version_present"] else "vtp=disabled"
        )
        if row["status"] != "not_verified" and row["database_identity"] != expected_identity:
            return False, "extended_vtp_database_identity_invalid"
        row_hosts.append(host)
        validated_rows.append(row)
        counts[row["status"]] += 1
        active += row["mode"] in {"server", "client"}
    canonical_hosts = sorted(row_hosts, key=lambda item: (item.casefold(), item))
    if row_hosts != canonical_hosts or len({host.casefold() for host in row_hosts}) != len(row_hosts):
        return False, "extended_vtp_row_identity_invalid"

    active_groups: Dict[str, List[dict]] = {}
    for row in validated_rows:
        if row["status"] != "not_verified" and row["mode"] in {"server", "client"}:
            active_groups.setdefault(row["database_identity"], []).append(row)
    for row in validated_rows:
        codes = {item["code"] for item in row["findings"]}
        if row["status"] == "not_verified":
            continue
        group = active_groups.get(row["database_identity"], [])
        expected_high = bool(
            row["mode"] == "server" and row["revision"] >= _HIGH_REVISION_THRESHOLD)
        expected_auth = bool(
            len(group) >= 2
            and len({member["authentication_configured"] for member in group}) > 1)
        expected_digest = bool(
            len(group) >= 2
            and len({member["vlan_database_digest"] for member in group}) > 1)
        if (("high_revision_server" in codes) is not expected_high
                or ("authentication_contradiction" in codes) is not expected_auth
                or ("vlan_database_digest_contradiction" in codes) is not expected_digest):
            return False, "extended_vtp_safety_findings_do_not_reconcile"

    coverage_hosts: List[str] = []
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
            return False, "extended_vtp_coverage_missing_or_malformed"
        host = cell.get("switch")
        commands = cell.get("commands")
        if (not _safe_text(host, 128) or not _safe_text(cell.get("platform"), 80)
                or cell.get("status") not in _ROW_STATUSES
                or not isinstance(commands, dict) or set(commands) != set(_COMMANDS)
                or not _valid_sha(cell.get("projection_sha256"), prefixed=True)
                or not isinstance(cell.get("finding_codes"), list)):
            return False, "extended_vtp_coverage_state_invalid"
        for command in _COMMANDS:
            receipt = commands.get(command)
            if (not isinstance(receipt, dict) or set(receipt) != _COMMAND_RECEIPT_KEYS
                    or receipt.get("capture_status") not in _CAPTURE_STATUSES
                    or receipt.get("parser_status") not in _PARSER_STATUSES
                    or any(type(receipt.get(key)) is not int or receipt[key] < 0
                           for key in ("candidate_count", "parsed_count", "rejected_count"))
                    or (receipt.get("source_sha256") != ""
                        and not _valid_sha(receipt.get("source_sha256"), prefixed=True))):
                return False, "extended_vtp_command_receipt_invalid"
            if receipt["capture_status"] == "ok" and not receipt["source_sha256"]:
                return False, "extended_vtp_command_source_digest_invalid"
            if receipt["capture_status"] != "ok" and (
                    receipt["parser_status"] != "not_verified"
                    or receipt["source_sha256"]):
                return False, "extended_vtp_command_custody_invalid"
        coverage_hosts.append(host)
    if coverage_hosts != row_hosts:
        return False, "extended_vtp_coverage_denominator_invalid"
    for row, cell in zip(rows, coverage, strict=True):
        if (cell["platform"] != row["platform"] or cell["status"] != row["status"]
                or cell["finding_codes"] != [item["code"] for item in row["findings"]]
                or cell["projection_sha256"] != "sha256:" + _sha(_row_projection(row))):
            return False, "extended_vtp_coverage_projection_mismatch"
        complete = bool(_platform_variant(row["platform"])) and all(
            cell["commands"][command]["capture_status"] == "ok"
            and cell["commands"][command]["parser_status"] in {"complete", "explicit_no_subject"}
            for command in _COMMANDS
        )
        if (row["status"] != "not_verified") is not complete:
            return False, "extended_vtp_coverage_authority_mismatch"

    expected_summary = {
        "n_hosts": len(rows), "n_healthy": counts["healthy"],
        "n_unsafe": counts["unsafe"], "n_not_verified": counts["not_verified"],
        "n_active": active,
        "n_high_revision_servers": finding_counts["high_revision_server"],
        "n_authentication_contradictions": finding_counts["authentication_contradiction"],
        "n_vlan_digest_contradictions": finding_counts["vlan_database_digest_contradiction"],
        "by_status": {token: counts[token] for token in ("healthy", "unsafe", "not_verified")},
        "baseline_sha256": summary.get("baseline_sha256"),
    }
    if summary != expected_summary or not _valid_sha(summary.get("baseline_sha256")):
        return False, "extended_vtp_summary_census_invalid"
    if summary["baseline_sha256"] != _sha(_baseline_payload(value)):
        return False, "extended_vtp_baseline_digest_mismatch"
    return True, "ok"


def validate_vtp_extended_evidence(value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the complete typed owner without trusting caller-controlled status leaves."""
    try:
        valid, reason = _structural_validation(value)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        valid, reason = False, "extended_vtp_validation_failed"
    if not valid:
        return {"present": value is not None, "valid": False, "reason": reason,
                "source_bound": False, "rows": [], "index": {}, "baseline": {}}
    digest = value["summary"]["baseline_sha256"]
    source_bound = bool(
        isinstance(value, _CurrentRunVtpExtendedEvidence)
        and value._original_digest == digest
        and value.get("projection_custody") == "current_run_source_bound"
    )
    if require_current_run and not source_bound:
        return {"present": True, "valid": False,
                "reason": "extended_vtp_not_current_run_source_bound",
                "source_bound": False, "rows": [], "index": {}, "baseline": {}}
    rows = list(value["rows"])
    return {"present": True, "valid": True, "reason": "ok",
            "source_bound": source_bound, "rows": rows,
            "index": {row["switch"]: row for row in rows}, "baseline": value,
            "projection_sha256": "sha256:" + digest}


def embedded_vtp_extended_evidence(value: Any) -> dict:
    """Return a JSON-safe audit projection with process-local source authority erased."""
    try:
        valid, _reason = _structural_validation(value)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        valid = False
    if not valid:
        return _unavailable_evidence()
    result = copy.deepcopy(dict(value))
    result["projection_custody"] = "embedded_unverified"
    for row in result["rows"]:
        row["projection_custody"] = "embedded_unverified"
    for row, cell in zip(result["rows"], result["coverage"], strict=True):
        cell["projection_sha256"] = "sha256:" + _sha(_row_projection(row))
    result["summary"]["baseline_sha256"] = ""
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    return result
