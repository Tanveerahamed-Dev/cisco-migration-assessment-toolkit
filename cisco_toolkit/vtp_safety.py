"""Source-bound, coverage-honest VTP cutover-safety baseline.

The sparse protocol-health projection already recognizes local VTP mode, domain,
and revision, but it is an advisory surface rather than an acceptance artifact.
This module owns the bounded current-run receipt used to decide whether that local
observation may be carried into a cutover gate.  It never publishes raw command
text or capture paths and never treats a matching high revision as acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cisco_toolkit.input_custody import read_text as read_custodied_text


VTP_SAFETY_SCHEMA = "vtp_safety_baseline/1"
VTP_SAFETY_SUBJECT_SCOPE_SCHEMA = "vtp_safety_subject_scope/1"

_COMMAND = "show vtp status"
_THRESHOLD = 100
_SCOPE = {
    "command": _COMMAND,
    "subject": "observed_local_vtp_status",
    "high_revision_threshold": _THRESHOLD,
}
_LIMITATIONS = [
    "The baseline covers one local show vtp status observation per host; it does not prove domain-wide VLAN-database equality or advertisement reachability.",
    "A configuration revision is an observed counter, not a freshness, correctness, or safe-to-match target; matching a high revision is not acceptance.",
    "VTP passwords, database contents, pruning behavior, per-VLAN propagation, simultaneous state, failover, and cutover authorization remain outside this receipt.",
    "NOT_APPLICABLE means no positive local VTP-status subject was identified in the bounded input; it is not proof that VTP is absent from the platform or network.",
]

_MODES = {"server", "client", "transparent", "off", "unknown"}
_ROW_STATUSES = ("review", "not_verified", "assessed")
_COVERAGE_STATUSES = ("review", "not_verified", "assessed", "not_applicable")
_PARSER_STATUSES = {"complete", "review", "not_verified", "explicit_no_subject", "rejected"}
_SAFE_CAPTURE_STATUSES = {
    "ok", "incomplete", "error", "empty", "unverified_prompt", "unreadable",
    "not_observed", "inspection_missing", "inspection_duplicate",
}
_MAX_HOSTS = 4096
_MAX_INSPECTIONS = 1_000_000
_MAX_LINES = 100_000
_MAX_BODY_CHARS = 8_000_000
_MAX_FINDINGS_PER_ROW = 16

_ROOT_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody",
    "rows", "coverage", "findings", "summary", "limitations",
}
_ROW_KEYS = {
    "switch", "platform", "mode", "mode_present", "domain", "domain_present",
    "revision", "revision_present", "version", "version_present", "status",
    "command", "acceptance", "source_key", "projection_custody", "findings",
}
_COVERAGE_KEYS = {
    "switch", "platform", "subject", "status", "command", "capture_status",
    "parser_status", "candidate_count", "parsed_count", "rejected_count",
    "explicit_no_subject", "source_sha256", "projection_sha256", "finding_codes",
}
_SUMMARY_KEYS = {
    "n_hosts", "n_subject_hosts", "n_rows", "n_assessed", "n_review",
    "n_not_verified", "n_high_revision_servers", "by_status",
    "by_coverage_status", "baseline_sha256",
}

_EXPLICIT_NO_SUBJECT = (
    re.compile(r"^vtp is disabled[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp feature is disabled[.!]?$", re.IGNORECASE),
    re.compile(r"^(?:feature )?vtp (?:feature )?is not enabled[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp is not supported on this platform[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp (?:feature )?(?:is )?not supported[.!]?$", re.IGNORECASE),
    re.compile(r"^vtp feature (?:is )?not available[.!]?$", re.IGNORECASE),
)


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
    if any(ord(char) < 32 or ord(char) == 127 for char in result):
        return ""
    return result


def _safe_string(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and _text(value, limit) == value


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
    for item in rows:
        if not isinstance(item, dict):
            continue
        host = _text(item.get("hostname") or item.get("switch"), 128)
        if host:
            out[host] = _text(item.get("platform"), 80)
    return out


def _has_casefold_collision(values: Iterable[str]) -> bool:
    seen = set()
    for value in values:
        folded = value.casefold()
        if folded in seen:
            return True
        seen.add(folded)
    return False


def _inspection_index(capture_integrity: Any) -> Tuple[Dict[Tuple[str, str], str], set]:
    index: Dict[Tuple[str, str], str] = {}
    duplicates: set = set()
    source = capture_integrity if isinstance(capture_integrity, dict) else {}
    inspections = source.get("inspections")
    if not isinstance(inspections, list) or len(inspections) > _MAX_INSPECTIONS:
        return {}, set()
    for item in inspections:
        if not isinstance(item, dict):
            continue
        host = _text(item.get("host"), 128)
        command = _text(item.get("command"), 128)
        status = _text(item.get("status"), 32)
        if not host or not command or status not in _SAFE_CAPTURE_STATUSES:
            continue
        key = (host, command)
        if key in index:
            duplicates.add(key)
        else:
            index[key] = status
    return index, duplicates


def _capture_status(index: Dict[Tuple[str, str], str], duplicates: set,
                    host: str, attempted: bool) -> str:
    if not attempted:
        return "not_observed"
    key = (host, _COMMAND)
    if key in duplicates:
        return "inspection_duplicate"
    return index.get(key, "inspection_missing")


def _read_capture(mapping: dict) -> Tuple[str, str]:
    path = mapping.get(_COMMAND)
    if not isinstance(path, (str, bytes)):
        return "", "not_observed"
    try:
        return read_custodied_text(path, encoding="utf-8", errors="ignore"), "ok"
    except Exception:
        return "", "unreadable"


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _label_value(line: str, label: str) -> Optional[str]:
    match = re.match(rf"^{re.escape(label)}\b(.*)$", line, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    if value.startswith(":"):
        value = value[1:].strip()
    return value


def _explicit_no_subject(body: str) -> bool:
    if not isinstance(body, str) or len(body) > _MAX_BODY_CHARS:
        return False
    meaningful = [line.strip() for line in (body or "").splitlines() if line.strip()]
    if len(meaningful) > _MAX_LINES:
        return False
    return len(meaningful) == 1 and any(
        pattern.fullmatch(meaningful[0]) for pattern in _EXPLICIT_NO_SUBJECT
    )


def _parse_status(body: str) -> dict:
    if len(body) > _MAX_BODY_CHARS:
        return {
            "parser_status": "rejected", "mode": "unknown", "mode_present": False,
            "domain": "", "domain_present": False, "revision": 0,
            "revision_present": False, "version": "", "version_present": False,
            "parsed_count": 0, "rejected_count": 1,
        }
    lines = body.splitlines()
    if len(lines) > _MAX_LINES:
        return {
            "parser_status": "rejected", "mode": "unknown", "mode_present": False,
            "domain": "", "domain_present": False, "revision": 0,
            "revision_present": False, "version": "", "version_present": False,
            "parsed_count": 0, "rejected_count": 1,
        }

    values: Dict[str, List[str]] = {"mode": [], "domain": [], "revision": [], "version": []}
    labels = (
        ("mode", ("VTP Operating Mode", "Operating Mode")),
        ("domain", ("VTP Domain Name", "Domain Name")),
        ("revision", ("Configuration Revision",)),
        ("version", ("VTP version running",)),
    )
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        for field, variants in labels:
            found = None
            for label in variants:
                found = _label_value(line, label)
                if found is not None:
                    break
            if found is not None:
                values[field].append(found)
                break

    conflict = any(len(set(items)) > 1 for items in values.values())
    raw_mode = values["mode"][0] if values["mode"] else ""
    mode_label_present = bool(values["mode"])
    mode_token = raw_mode.casefold().split(None, 1)[0] if raw_mode else ""
    aliases = {"server": "server", "client": "client", "transparent": "transparent", "off": "off"}
    mode = aliases.get(mode_token, "unknown")
    mode_present = mode != "unknown"

    domain_present = bool(values["domain"])
    raw_domain = values["domain"][0] if values["domain"] else ""
    if raw_domain.casefold() in {"null", "none", "(none)", "not configured"}:
        raw_domain = ""
    domain = raw_domain if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", raw_domain or "") else ""
    domain_invalid = bool(raw_domain and not domain)

    revision_present = bool(values["revision"])
    raw_revision = values["revision"][0] if values["revision"] else ""
    revision_valid = bool(re.fullmatch(r"\d{1,10}", raw_revision))
    revision = int(raw_revision) if revision_valid else 0
    if revision > 4_294_967_295:
        revision_valid = False
        revision = 0

    version_present = bool(values["version"])
    raw_version = values["version"][0] if values["version"] else ""
    version_match = re.match(r"^([123])(?:\b|$)", raw_version)
    version = version_match.group(1) if version_match else ""
    version_invalid = bool(version_present and raw_version and not version)

    rejected = bool(conflict or domain_invalid or version_invalid
                    or (revision_present and not revision_valid)
                    or (mode_label_present and mode == "unknown"))
    parser_status = "rejected" if rejected else (
        "complete" if mode_present else "not_verified"
    )
    return {
        "parser_status": parser_status,
        "mode": mode, "mode_present": mode_present,
        "domain": domain, "domain_present": domain_present,
        "revision": revision, "revision_present": revision_present and revision_valid,
        "version": version, "version_present": version_present and bool(version),
        "parsed_count": 1 if mode_present else 0,
        "rejected_count": 1 if rejected else 0,
    }


def _semantic_result(row: dict, capture_status: str, parser_status: str) -> Tuple[str, List[dict]]:
    if capture_status != "ok":
        return "not_verified", [_finding(
            "not_verified", "capture_not_verified",
            "The show vtp status capture did not have one unique integrity-ok inspection receipt.",
        )]
    if parser_status in {"not_verified", "rejected"}:
        return "not_verified", [_finding(
            "not_verified", "parser_not_verified",
            "The bounded VTP mode/domain/revision parser could not authorize this local status record.",
        )]
    if parser_status == "review":
        return "review", [_finding(
            "review", "parser_scope_review",
            "The bounded VTP status record requires live review before it can be used for acceptance.",
        )]
    mode = row["mode"]
    if mode in {"server", "client"}:
        if not row["domain_present"] or not row["revision_present"]:
            return "not_verified", [_finding(
                "not_verified", "active_mode_fields_not_verified",
                "Active VTP mode was observed without both explicit domain and numeric revision fields.",
            )]
        findings: List[dict] = []
        if not row["domain"]:
            findings.append(_finding(
                "review", "active_mode_domain_empty",
                "Active VTP mode was observed with an explicitly empty domain value.",
            ))
        if mode == "server" and row["revision"] >= _THRESHOLD:
            findings.append(_finding(
                "review", "high_revision_server",
                "VTP Server mode carries an observed configuration revision at or above 100.",
            ))
        if findings:
            return "review", findings
    return "assessed", []


def _acceptance(row: dict) -> str:
    if row["status"] == "not_verified":
        return (
            f"VTP SAFETY BASELINE NOT VERIFIED — BLOCKER: No integrity-complete, parse-complete "
            f"local VTP mode/domain/revision baseline is authorized for {row['switch']}. Re-collect "
            "show vtp status before cutover; do not treat an absent row or matching unknown state "
            "as acceptance."
        )
    domain = row["domain"] if row["domain"] else "<empty/not reported>"
    revision = str(row["revision"]) if row["revision_present"] else "<not reported>"
    version = row["version"] if row["version_present"] else "<not reported>"
    observed = (
        f"Observed bounded VTP baseline on {row['switch']}: mode {row['mode']}, domain {domain}, "
        f"configuration revision {revision}, running version {version}."
    )
    if row["status"] == "review":
        return (
            "PRE-CUTOVER REVIEW — BLOCKER: " + observed + " A matching revision after cutover is "
            "NOT ACCEPTANCE. Before connecting or staging a switch, back up and reconcile the VLAN "
            "database, confirm the intended VTP domain/version/mode, and reset the incoming switch "
            "revision. This local observation does not prove database equality, advertisement "
            "reachability, or cutover safety."
        )
    return (
        observed + " Preserve or explicitly explain changes. This is local status only; it does not "
        "prove VLAN-database equality, advertisement reachability, revision-reset safety, or cutover "
        "authorization."
    )


def _source_payload(cell: dict, row: Optional[dict]) -> dict:
    facts = {} if row is None else {
        key: row[key] for key in (
            "mode", "mode_present", "domain", "domain_present", "revision",
            "revision_present", "version", "version_present",
        )
    }
    return {
        "command": cell["command"], "capture_status": cell["capture_status"],
        "parser_status": cell["parser_status"], "candidate_count": cell["candidate_count"],
        "parsed_count": cell["parsed_count"], "rejected_count": cell["rejected_count"],
        "explicit_no_subject": cell["explicit_no_subject"], "facts": facts,
    }


def _projection_payload(cell: dict, row: Optional[dict]) -> dict:
    if row is None:
        return {"switch": cell["switch"], "subject": False,
                "explicit_no_subject": cell["explicit_no_subject"]}
    return {
        key: row[key] for key in (
            "switch", "platform", "mode", "mode_present", "domain", "domain_present",
            "revision", "revision_present", "version", "version_present", "status", "findings",
        )
    }


def _baseline_payload(value: dict) -> dict:
    payload = copy.deepcopy(dict(value))
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("baseline_sha256", None)
    return payload


def _plain_copy(value: dict) -> dict:
    return {key: copy.deepcopy(item) for key, item in dict(value).items()}


def _embed_plain(value: dict) -> dict:
    result = _plain_copy(value)
    result["projection_custody"] = "embedded_unverified"
    for row in result.get("rows", []):
        if isinstance(row, dict):
            row["projection_custody"] = "embedded_unverified"
    if isinstance(result.get("summary"), dict):
        result["summary"]["baseline_sha256"] = ""
        result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    return result


class _CurrentRunVtpSafetyBaseline(dict):
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


def compute_vtp_safety_subject_scope(all_cmd_to_files: Any,
                                     devices: Any = None) -> dict:
    """Return a path-free receipt that distinguishes no attempt from rejected scope.

    The receipt is blocker-only context: it never authorizes a positive VTP acceptance row.  A
    rejected attempted scope therefore carries no caller-controlled host leaves, but remains
    distinguishable from a valid empty/no-subject collection.
    """
    if not isinstance(all_cmd_to_files, dict):
        return {
            "schema": VTP_SAFETY_SUBJECT_SCOPE_SCHEMA,
            "valid": False,
            "attempted": False,
            "reason": "scope_input_invalid",
            "rows": [],
        }
    mappings = all_cmd_to_files
    platforms = _platforms(devices)
    attempted = [
        (key, mapping) for key, mapping in mappings.items()
        if isinstance(mapping, dict) and _COMMAND in mapping
    ]
    if not attempted:
        return {
            "schema": VTP_SAFETY_SUBJECT_SCOPE_SCHEMA,
            "valid": True,
            "attempted": False,
            "reason": "ok",
            "rows": [],
        }
    candidate_hosts = [key for key, _mapping in attempted
                       if isinstance(key, str) and _text(key, 128) == key]
    identities = set(candidate_hosts) | set(platforms)
    reason = ""
    if len(candidate_hosts) != len(attempted):
        reason = "scope_identity_invalid"
    elif len(candidate_hosts) > _MAX_HOSTS or len(identities) > _MAX_HOSTS:
        reason = "scope_host_cap_exceeded"
    elif _has_casefold_collision(identities):
        reason = "scope_identity_collision"
    if reason:
        return {
            "schema": VTP_SAFETY_SUBJECT_SCOPE_SCHEMA,
            "valid": False,
            "attempted": True,
            "reason": reason,
            "rows": [],
        }
    rows = []
    for host in sorted(
            candidate_hosts,
            key=lambda item: (item.casefold(), item)):
        mapping = mappings.get(host)
        if isinstance(mapping, dict) and _COMMAND in mapping:
            rows.append({"switch": host, "platform": platforms.get(host, ""),
                         "command": _COMMAND})
        if len(rows) >= _MAX_HOSTS:
            break
    return {
        "schema": VTP_SAFETY_SUBJECT_SCOPE_SCHEMA,
        "valid": True,
        "attempted": True,
        "reason": "ok",
        "rows": rows,
    }


def scope_vtp_safety_subjects(all_cmd_to_files: Any, devices: Any = None) -> dict:
    """Return the closed path-free VTP subject-scope receipt.

    This named entry point is retained for discoverability, but deliberately does not expose a
    lossy rows-only projection: callers must preserve the valid/attempted distinction.
    """
    return compute_vtp_safety_subject_scope(all_cmd_to_files, devices)


def _unavailable_baseline() -> dict:
    return {
        "schema": VTP_SAFETY_SCHEMA, "scope": dict(_SCOPE),
        "verdict": "INDETERMINATE", "assessed": False,
        "projection_custody": "embedded_unverified", "rows": [], "coverage": [],
        "findings": [], "summary": {
            "n_hosts": 0, "n_subject_hosts": 0, "n_rows": 0, "n_assessed": 0,
            "n_review": 0, "n_not_verified": 0, "n_high_revision_servers": 0,
            "by_status": {status: 0 for status in _ROW_STATUSES},
            "by_coverage_status": {status: 0 for status in _COVERAGE_STATUSES},
            "baseline_sha256": "",
        }, "limitations": ["The current-run VTP safety baseline was unavailable."],
    }


def compute_vtp_safety_baseline(all_cmd_to_files: Any, capture_integrity: Any,
                                devices: Any = None) -> dict:
    """Compute the strict current-run local VTP safety baseline."""
    mappings = all_cmd_to_files if isinstance(all_cmd_to_files, dict) else {}
    platforms = _platforms(devices)
    host_names = {
        host for host in mappings
        if isinstance(host, str) and _text(host, 128) == host
    } | set(platforms)
    if len(host_names) > _MAX_HOSTS or _has_casefold_collision(host_names):
        return _unavailable_baseline()
    inspections, duplicates = _inspection_index(capture_integrity)

    rows: List[dict] = []
    coverage: List[dict] = []
    global_findings: List[dict] = []
    for host in sorted(host_names, key=lambda item: (item.casefold(), item)):
        mapping = mappings.get(host)
        mapping = mapping if isinstance(mapping, dict) else {}
        platform = platforms.get(host, "")
        attempted = _COMMAND in mapping
        capture_status = _capture_status(inspections, duplicates, host, attempted)
        body, read_status = _read_capture(mapping) if attempted else ("", "not_observed")
        if capture_status == "ok" and read_status != "ok":
            capture_status = read_status
        explicit_no_subject = (
            capture_status == "ok" and read_status == "ok" and _explicit_no_subject(body)
        )
        row: Optional[dict] = None
        parser_status = "explicit_no_subject" if explicit_no_subject else "not_verified"
        parsed_count = rejected_count = 0
        subject = bool(attempted and not explicit_no_subject)

        if subject:
            parsed = _parse_status(body) if capture_status == "ok" else {
                "parser_status": "not_verified", "mode": "unknown", "mode_present": False,
                "domain": "", "domain_present": False, "revision": 0,
                "revision_present": False, "version": "", "version_present": False,
                "parsed_count": 0, "rejected_count": 0,
            }
            parser_status = parsed["parser_status"]
            parsed_count = parsed["parsed_count"]
            rejected_count = parsed["rejected_count"]
            row = {
                "switch": host, "platform": platform,
                "mode": parsed["mode"], "mode_present": parsed["mode_present"],
                "domain": parsed["domain"], "domain_present": parsed["domain_present"],
                "revision": parsed["revision"], "revision_present": parsed["revision_present"],
                "version": parsed["version"], "version_present": parsed["version_present"],
                "status": "not_verified", "command": _COMMAND, "acceptance": "",
                "source_key": "show vtp status#mode/domain/revision/version",
                "projection_custody": "current_run_source_bound", "findings": [],
            }
            status, findings = _semantic_result(row, capture_status, parser_status)
            row["status"] = status
            row["findings"] = sorted(findings, key=lambda item: (item["code"], item["issue"]))
            row["acceptance"] = _acceptance(row)
            rows.append(row)
            global_findings.extend(dict(item, switch=host) for item in row["findings"])

        coverage_status = row["status"] if row is not None else "not_applicable"
        cell = {
            "switch": host, "platform": platform, "subject": subject,
            "status": coverage_status, "command": _COMMAND,
            "capture_status": capture_status, "parser_status": parser_status,
            "candidate_count": 1 if subject else 0,
            "parsed_count": parsed_count, "rejected_count": rejected_count,
            "explicit_no_subject": explicit_no_subject,
            "source_sha256": "", "projection_sha256": "",
            "finding_codes": sorted({item["code"] for item in (row or {}).get("findings", [])}),
        }
        cell["source_sha256"] = _sha(_source_payload(cell, row))
        cell["projection_sha256"] = _sha(_projection_payload(cell, row))
        coverage.append(cell)

    rows.sort(key=lambda row: (row["switch"].casefold(), row["switch"]))
    coverage.sort(key=lambda row: (row["switch"].casefold(), row["switch"]))
    global_findings.sort(key=lambda row: (row["switch"].casefold(), row["switch"],
                                           row["code"], row["issue"]))
    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    if counts["review"] or counts["not_verified"]:
        verdict = "INDETERMINATE"
    elif counts["assessed"]:
        verdict = "CLEAR"
    else:
        verdict = "NOT_APPLICABLE"
    result = {
        "schema": VTP_SAFETY_SCHEMA, "scope": dict(_SCOPE), "verdict": verdict,
        "assessed": verdict == "CLEAR", "projection_custody": "current_run_source_bound",
        "rows": rows, "coverage": coverage, "findings": global_findings,
        "summary": {
            "n_hosts": len(coverage), "n_subject_hosts": sum(cell["subject"] for cell in coverage),
            "n_rows": len(rows), "n_assessed": counts["assessed"],
            "n_review": counts["review"], "n_not_verified": counts["not_verified"],
            "n_high_revision_servers": sum(
                row["mode"] == "server" and row["revision_present"]
                and row["revision"] >= _THRESHOLD for row in rows
            ),
            "by_status": {status: int(counts[status]) for status in _ROW_STATUSES},
            "by_coverage_status": {
                status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
            }, "baseline_sha256": "",
        },
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _sha(_baseline_payload(result))
    valid, _reason = _structural_validation(result)
    if not valid:
        return _unavailable_baseline()
    return _CurrentRunVtpSafetyBaseline(result)


def _valid_finding(item: Any, *, global_row: bool = False) -> bool:
    keys = {"kind", "code", "issue"} | ({"switch"} if global_row else set())
    return bool(
        isinstance(item, dict) and set(item) == keys
        and item.get("kind") in {"review", "not_verified"}
        and _safe_string(item.get("code"), 96)
        and _safe_string(item.get("issue"), 500)
        and (not global_row or _safe_string(item.get("switch"), 128))
    )


def _structural_validation_impl(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "baseline_not_object"
    if set(value) != _ROOT_KEYS or value.get("schema") != VTP_SAFETY_SCHEMA:
        return False, "baseline_schema_or_keys_invalid"
    if value.get("scope") != _SCOPE or value.get("verdict") not in {
            "CLEAR", "INDETERMINATE", "NOT_APPLICABLE"}:
        return False, "baseline_scope_or_verdict_invalid"
    if type(value.get("assessed")) is not bool:
        return False, "baseline_assessed_invalid"
    custody = value.get("projection_custody")
    if custody not in {"current_run_source_bound", "embedded_unverified"}:
        return False, "baseline_custody_invalid"
    rows, coverage, findings, summary = (
        value.get("rows"), value.get("coverage"), value.get("findings"), value.get("summary")
    )
    if not isinstance(rows, list) or len(rows) > _MAX_HOSTS or not isinstance(coverage, list) \
            or len(coverage) > _MAX_HOSTS or not isinstance(findings, list) \
            or len(findings) > _MAX_HOSTS * _MAX_FINDINGS_PER_ROW \
            or not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "baseline_denominator_invalid"
    digest = summary.get("baseline_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or digest != _sha(_baseline_payload(value)):
        return False, "baseline_digest_mismatch"
    if value.get("limitations") != _LIMITATIONS:
        return False, "baseline_limitations_invalid"

    rows_by_host: Dict[str, dict] = {}
    row_identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "baseline_row_invalid"
        host = _text(row.get("switch"), 128)
        folded_host = host.casefold()
        if not host or folded_host in row_identities or row.get("mode") not in _MODES \
                or row.get("status") not in _ROW_STATUSES:
            return False, "baseline_row_identity_or_status_invalid"
        if not all(type(row.get(key)) is bool for key in (
                "mode_present", "domain_present", "revision_present", "version_present")):
            return False, "baseline_row_presence_invalid"
        if type(row.get("revision")) is not int or not 0 <= row["revision"] <= 4_294_967_295:
            return False, "baseline_row_revision_invalid"
        if not all(_safe_string(row.get(field), limit) for field, limit in (
                ("switch", 128), ("platform", 80), ("mode", 16), ("domain", 64),
                ("version", 8), ("status", 32), ("command", 128), ("acceptance", 1800),
                ("source_key", 160), ("projection_custody", 40))):
            return False, "baseline_row_text_invalid"
        if row["command"] != _COMMAND or row["source_key"] != \
                "show vtp status#mode/domain/revision/version" or row["projection_custody"] != custody:
            return False, "baseline_row_source_or_custody_invalid"
        if row["mode_present"] is not (row["mode"] != "unknown"):
            return False, "baseline_row_mode_presence_invalid"
        if (not row["domain_present"] and row["domain"]) \
                or (not row["revision_present"] and row["revision"] != 0) \
                or (not row["version_present"] and row["version"]):
            return False, "baseline_row_field_presence_invalid"
        if row["domain"] and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", row["domain"]):
            return False, "baseline_row_domain_invalid"
        if row["version"] and row["version"] not in {"1", "2", "3"}:
            return False, "baseline_row_version_invalid"
        row_findings = row.get("findings")
        if not isinstance(row_findings, list) or len(row_findings) > _MAX_FINDINGS_PER_ROW \
                or not all(_valid_finding(item) for item in row_findings) \
                or row_findings != sorted(row_findings, key=lambda item: (item["code"], item["issue"])):
            return False, "baseline_row_findings_invalid"
        rows_by_host[host] = row
        row_identities.add(folded_host)
    if rows != sorted(rows, key=lambda row: (row["switch"].casefold(), row["switch"])):
        return False, "baseline_row_order_invalid"

    coverage_by_host: Dict[str, dict] = {}
    coverage_identities = set()
    for cell in coverage:
        if not isinstance(cell, dict) or set(cell) != _COVERAGE_KEYS:
            return False, "baseline_coverage_invalid"
        host = _text(cell.get("switch"), 128)
        folded_host = host.casefold()
        if not host or folded_host in coverage_identities:
            return False, "baseline_coverage_identity_invalid"
        if type(cell.get("subject")) is not bool or type(cell.get("explicit_no_subject")) is not bool \
                or cell.get("status") not in _COVERAGE_STATUSES \
                or cell.get("capture_status") not in _SAFE_CAPTURE_STATUSES \
                or cell.get("parser_status") not in _PARSER_STATUSES:
            return False, "baseline_coverage_semantics_invalid"
        if not all(_safe_string(cell.get(field), limit) for field, limit in (
                ("switch", 128), ("platform", 80), ("status", 32), ("command", 128),
                ("capture_status", 32), ("parser_status", 32),
                ("source_sha256", 64), ("projection_sha256", 64))):
            return False, "baseline_coverage_text_invalid"
        if cell["command"] != _COMMAND or not re.fullmatch(r"[0-9a-f]{64}", cell["source_sha256"]) \
                or not re.fullmatch(r"[0-9a-f]{64}", cell["projection_sha256"]):
            return False, "baseline_coverage_source_invalid"
        for field in ("candidate_count", "parsed_count", "rejected_count"):
            if type(cell.get(field)) is not int or cell[field] not in {0, 1}:
                return False, "baseline_coverage_count_invalid"
        codes = cell.get("finding_codes")
        if not isinstance(codes, list) or len(codes) > _MAX_FINDINGS_PER_ROW \
                or codes != sorted(set(codes)) or not all(_safe_string(code, 96) for code in codes):
            return False, "baseline_coverage_findings_invalid"
        row = rows_by_host.get(host)
        if cell["subject"] is not (row is not None):
            return False, "baseline_coverage_subject_mismatch"
        if row is None:
            if cell["status"] != "not_applicable" or cell["candidate_count"] != 0 \
                    or cell["parsed_count"] != 0 or cell["rejected_count"] != 0 \
                    or cell["finding_codes"]:
                return False, "baseline_coverage_not_applicable_mismatch"
            if cell["explicit_no_subject"] is not (cell["parser_status"] == "explicit_no_subject"):
                return False, "baseline_coverage_explicit_no_subject_mismatch"
            if cell["explicit_no_subject"]:
                if cell["capture_status"] != "ok":
                    return False, "baseline_coverage_no_subject_source_mismatch"
            elif cell["capture_status"] != "not_observed" \
                    or cell["parser_status"] != "not_verified":
                return False, "baseline_coverage_no_subject_source_mismatch"
        else:
            if cell["status"] != row["status"] or cell["candidate_count"] != 1 \
                    or cell["parsed_count"] != int(row["mode_present"]) \
                    or cell["rejected_count"] != int(cell["parser_status"] == "rejected") \
                    or cell["explicit_no_subject"] or cell["platform"] != row["platform"]:
                return False, "baseline_coverage_row_mismatch"
            if cell["capture_status"] != "ok":
                if cell["parser_status"] != "not_verified" or any((
                        row["mode_present"], row["domain_present"], row["revision_present"],
                        row["version_present"], bool(row["domain"]), bool(row["revision"]),
                        bool(row["version"]), row["mode"] != "unknown")):
                    return False, "baseline_coverage_parser_source_mismatch"
            elif cell["parser_status"] == "complete" and not row["mode_present"]:
                return False, "baseline_coverage_parser_source_mismatch"
            elif cell["parser_status"] == "not_verified" and row["mode_present"]:
                return False, "baseline_coverage_parser_source_mismatch"
            expected_status, expected_findings = _semantic_result(
                row, cell["capture_status"], cell["parser_status"])
            expected_findings = sorted(expected_findings,
                                       key=lambda item: (item["code"], item["issue"]))
            if row["status"] != expected_status or row["findings"] != expected_findings \
                    or row["acceptance"] != _acceptance(row) \
                    or cell["finding_codes"] != [item["code"] for item in expected_findings]:
                return False, "baseline_row_semantics_mismatch"
        if cell["source_sha256"] != _sha(_source_payload(cell, row)) \
                or cell["projection_sha256"] != _sha(_projection_payload(cell, row)):
            return False, "baseline_coverage_hash_mismatch"
        coverage_by_host[host] = cell
        coverage_identities.add(folded_host)
    if coverage != sorted(
            coverage, key=lambda cell: (cell["switch"].casefold(), cell["switch"])):
        return False, "baseline_coverage_order_invalid"

    if set(rows_by_host) - set(coverage_by_host):
        return False, "baseline_row_without_coverage"
    expected_findings = sorted(
        [dict(item, switch=host) for host, row in rows_by_host.items() for item in row["findings"]],
        key=lambda item: (item["switch"].casefold(), item["switch"], item["code"], item["issue"]),
    )
    if findings != expected_findings or not all(_valid_finding(item, global_row=True) for item in findings):
        return False, "baseline_global_findings_mismatch"

    counts = Counter(row["status"] for row in rows)
    coverage_counts = Counter(cell["status"] for cell in coverage)
    expected_summary = {
        "n_hosts": len(coverage), "n_subject_hosts": sum(cell["subject"] for cell in coverage),
        "n_rows": len(rows), "n_assessed": counts["assessed"],
        "n_review": counts["review"], "n_not_verified": counts["not_verified"],
        "n_high_revision_servers": sum(
            row["mode"] == "server" and row["revision_present"]
            and row["revision"] >= _THRESHOLD for row in rows
        ),
        "by_status": {status: int(counts[status]) for status in _ROW_STATUSES},
        "by_coverage_status": {
            status: int(coverage_counts[status]) for status in _COVERAGE_STATUSES
        },
    }
    if not isinstance(summary.get("by_status"), dict) or set(summary["by_status"]) != set(_ROW_STATUSES) \
            or not isinstance(summary.get("by_coverage_status"), dict) \
            or set(summary["by_coverage_status"]) != set(_COVERAGE_STATUSES):
        return False, "baseline_summary_census_invalid"
    scalar_counts = _SUMMARY_KEYS - {"by_status", "by_coverage_status", "baseline_sha256"}
    if any(type(summary.get(key)) is not int or not 0 <= summary[key] <= _MAX_HOSTS
           for key in scalar_counts) or any(
               type(summary["by_status"].get(status)) is not int
               or not 0 <= summary["by_status"][status] <= _MAX_HOSTS
               for status in _ROW_STATUSES
           ) or any(
               type(summary["by_coverage_status"].get(status)) is not int
               or not 0 <= summary["by_coverage_status"][status] <= _MAX_HOSTS
               for status in _COVERAGE_STATUSES):
        return False, "baseline_summary_census_invalid"
    if any(summary.get(key) != expected for key, expected in expected_summary.items()):
        return False, "baseline_summary_mismatch"
    expected_verdict = "INDETERMINATE" if counts["review"] or counts["not_verified"] else (
        "CLEAR" if counts["assessed"] else "NOT_APPLICABLE"
    )
    if value["verdict"] != expected_verdict or value["assessed"] is not (expected_verdict == "CLEAR"):
        return False, "baseline_verdict_mismatch"
    return True, "ok"


def _structural_validation(value: Any) -> Tuple[bool, str]:
    try:
        return _structural_validation_impl(value)
    except (Exception, MemoryError):
        return False, "baseline_validation_failed"


def validate_vtp_safety_baseline(value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the closed contract and optionally require process-local source custody."""
    present = value is not None
    valid, reason = _structural_validation(value)
    source_bound = bool(
        valid and isinstance(value, _CurrentRunVtpSafetyBaseline)
        and getattr(value, "_original_digest", "") == value["summary"]["baseline_sha256"]
    )
    if require_current_run and not source_bound:
        valid = False
        reason = "baseline_not_current_run_source_bound"
    if not valid:
        return {
            "present": present, "valid": False, "reason": reason,
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }
    baseline = _plain_copy(value)
    rows = baseline["rows"]
    return {
        "present": True, "valid": True, "reason": "ok", "source_bound": source_bound,
        "rows": rows, "index": {row["switch"]: row for row in rows}, "baseline": baseline,
    }


def embedded_vtp_safety_baseline(value: Any) -> dict:
    """Return a JSON-safe audit projection that cannot authorize current-run decisions."""
    view = validate_vtp_safety_baseline(value)
    if not view["valid"]:
        return _unavailable_baseline()
    return _embed_plain(view["baseline"])


__all__ = [
    "VTP_SAFETY_SCHEMA", "VTP_SAFETY_SUBJECT_SCOPE_SCHEMA",
    "compute_vtp_safety_baseline", "validate_vtp_safety_baseline",
    "embedded_vtp_safety_baseline", "compute_vtp_safety_subject_scope",
    "scope_vtp_safety_subjects",
]
