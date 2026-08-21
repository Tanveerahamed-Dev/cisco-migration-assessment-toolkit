"""Source-bound FHRP redundancy-domain composition baseline.

The configured-group owner proves bounded local group truth.  This module joins
that receipt to the current in-memory SVI projection and answers a different
question: within an *observed* VLAN/VRF/IPv4-subnet domain, are the in-scope
gateway SVIs accounted for by compatible FHRP candidate sets?

It deliberately does not infer off-scan peers or intended membership.  A
fully-evidenced SVI with no FHRP beside a positive participant is therefore a
REVIEW condition, not a definite configuration fault.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from cisco_toolkit.fhrp_intent import (
    FHRP_CONFIGURED_GROUP_SCHEMA,
    embedded_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)
from cisco_toolkit.textutils import normalize_ifname


FHRP_REDUNDANCY_DOMAIN_SCHEMA = "fhrp_redundancy_domain_baseline/1"

_SCOPE = {
    "domain_identity": "vlan/normalized-vrf/observed-ipv4-subnet",
    "candidate_identity": "protocol/group/virtual-ip",
    "upstream_schema": FHRP_CONFIGURED_GROUP_SCHEMA,
}
_CUSTODIES = {"current_run_projection_bound", "embedded_unverified"}
_STATUSES = ("degraded", "review", "not_verified", "assessed")
_STATUS_RANK = {"assessed": 0, "review": 1, "not_verified": 2, "degraded": 3}
_VERDICTS = {"BLOCKED", "INDETERMINATE", "CLEAR", "NOT_APPLICABLE"}
_PARTICIPATION = {"positive", "nonparticipant", "not_verified"}
_PROTOCOLS = ("HSRP", "VRRP", "GLBP")
_GROUP_LIMITS = {"HSRP": (0, 4095), "VRRP": (1, 255), "GLBP": (0, 1023)}
_COMMANDS = {
    "HSRP": {"show standby brief", "show standby all", "show hsrp brief", "show hsrp all"},
    "VRRP": {"show vrrp brief"},
    "GLBP": {"show glbp brief"},
}
_LEADERS = {"HSRP": "ACTIVE", "VRRP": "MASTER", "GLBP": "ACTIVE"}
_BACKUPS = {
    "HSRP": {"STANDBY"},
    "VRRP": {"BACKUP"},
    "GLBP": {"STANDBY", "LISTEN"},
}

_MAX_HOSTS = 4096
_MAX_ROWS = 20_000
_MAX_DOMAINS = 4096
_MAX_FINDINGS = 8192
_MAX_TEXT = 2000

_ROOT_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody",
    "source_receipt", "rows", "domains", "findings", "summary", "limitations",
}
_SOURCE_KEYS = {
    "schema", "valid", "source_bound", "configured_baseline_sha256",
    "svi_projection_sha256",
}
_ROW_KEYS = {
    "switch", "interface", "svi_ip", "vlan", "vrf", "subnet", "domain_key",
    "candidate_key", "participation", "protocol", "group", "virtual_ip", "role",
    "status", "check", "command", "acceptance", "why", "source_key",
    "projection_custody", "findings",
}
_DOMAIN_KEYS = {
    "vlan", "vrf", "subnet", "domain_key", "status", "assessed", "member_count",
    "participant_count", "leader_count", "backup_count", "protocol", "group",
    "virtual_ip", "members", "findings", "acceptance",
}
_MEMBER_KEYS = {
    "switch", "interface", "svi_ip", "participation", "protocol", "group",
    "virtual_ip", "role", "local_status", "source_group_key",
    "projection_custody", "findings",
}
_FINDING_KEYS = {"kind", "code", "issue"}
_TOP_FINDING_KEYS = _FINDING_KEYS | {"domain_key"}
_SUMMARY_KEYS = {
    "n_domains", "n_rows", "n_members", "n_participants", "n_assessed",
    "n_degraded", "n_review", "n_not_verified", "by_status", "baseline_sha256",
}

_FINDING_TEXT = {
    "source_receipt_not_verified": (
        "not_verified",
        "The current-run configured-group receipt was unavailable or not source-bound; no "
        "caller-supplied group leaves were accepted.",
    ),
    "subnet_unobserved": (
        "review",
        "An exact observed IPv4 subnet could not be established for every candidate member.",
    ),
    "duplicate_gateway_identity": (
        "review",
        "Canonical host/interface identity collided inside the observed domain.",
    ),
    "local_group_degraded": (
        "degraded",
        "A source-bound local configured/runtime FHRP group is definitely degraded.",
    ),
    "local_group_review": (
        "review",
        "A source-bound local configured/runtime FHRP group requires review.",
    ),
    "local_group_not_verified": (
        "not_verified",
        "A local configured/runtime FHRP group could not be verified.",
    ),
    "member_evidence_not_verified": (
        "not_verified",
        "All three subtype configuration/runtime receipts were not simultaneously integrity-ok, "
        "parser-complete, rejection-free, and exact-zero for this apparent nonparticipant.",
    ),
    "nonparticipant_intent_unresolved": (
        "review",
        "An evidenced gateway SVI shares the exact observed domain with a positive FHRP "
        "participant, but intended redundancy membership is not established.",
    ),
    "candidate_set_mismatch": (
        "review",
        "In-scope gateway SVIs do not expose the same bounded protocol/group/virtual-IP candidate set.",
    ),
    "multiple_leaders_observed": (
        "review",
        "More than one sequential leader role was observed for one exact FHRP candidate.",
    ),
    "no_leader_observed": (
        "review",
        "No sequential leader role was observed for one exact FHRP candidate.",
    ),
    "no_backup_observed": (
        "review",
        "No accepted sequential backup role was observed for one exact FHRP candidate.",
    ),
}

_LIMITATIONS = [
    "Subjects are exact observed VLAN + normalized VRF + observed IPv4 subnet domains with at "
    "least two in-scope gateway SVIs and at least one positive FHRP participant.",
    "A same-domain SVI with zero FHRP participation is a review of unresolved intent, not proof "
    "that the SVI is misconfigured or should join the group.",
    "Sequential captures are not simultaneous split-brain, failover, or convergence evidence.",
    "No off-scan peer, intended member count, timer, authentication, tracking, preemption, policy, "
    "or convergence claim is made.",
    "current_run_projection_bound binds the normalized in-process SVI projection and the validated "
    "configured-group receipt; it is not raw-capture cryptographic custody.",
]


class _CurrentRunFhrpRedundancyDomainBaseline(dict):
    """Process-local decision marker deliberately lost at a JSON boundary."""

    _authorized_baseline_sha256: str

    def __deepcopy__(self, memo: dict) -> dict:
        """A copy is audit data, never a second current-run authority token."""
        copied = copy.deepcopy(dict(self), memo)
        memo[id(self)] = copied
        return copied


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        return ""
    return value


def _field(value: Any, name: str) -> Any:
    try:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)
    except Exception:
        return None


def _finding(code: str) -> dict:
    kind, issue = _FINDING_TEXT[code]
    return {"kind": kind, "code": code, "issue": issue}


def _finding_sort_key(value: dict) -> tuple:
    return (value.get("kind", ""), value.get("code", ""), value.get("issue", ""))


def _unique_findings(values: Iterable[dict]) -> List[dict]:
    out: List[dict] = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = (value.get("kind"), value.get("code"), value.get("issue"))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(value))
    return sorted(out, key=_finding_sort_key)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    try:
        return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError, MemoryError):
        return ""


def _digest_payload(value: dict) -> dict:
    payload = dict(value)
    summary = dict(payload.get("summary") or {})
    summary["baseline_sha256"] = ""
    payload["summary"] = summary
    return payload


def _baseline_digest(value: dict) -> str:
    return _sha(_digest_payload(value))


def _normalize_vrf(value: Any) -> str:
    text = _text(value, 128)
    if not text or text.casefold() in {"default", "global"}:
        return "global"
    return text.casefold()


def _svi_identity(host: str, interface: str) -> tuple:
    return (host.casefold(), normalize_ifname(interface).casefold())


def _ipv4_interface(value: Any) -> Tuple[str, str]:
    text = _text(value, 128)
    if not text:
        return "", "(subnet-unobserved)"
    parts = text.split()
    token = parts[0]
    if len(parts) >= 2:
        try:
            if ipaddress.ip_address(parts[0]).version == 4:
                # IOS stores the primary SVI as ``address dotted-mask`` while
                # NX-OS commonly retains CIDR.  Both must converge on one
                # observed subnet identity before a cross-platform join.
                token = f"{parts[0]}/{parts[1]}"
        except (ValueError, TypeError):
            pass
    try:
        parsed = ipaddress.ip_interface(token)
    except (ValueError, TypeError):
        return "", "(subnet-unobserved)"
    if parsed.version != 4 or parsed.network.prefixlen == 32:
        return str(parsed), "(subnet-unobserved)"
    return str(parsed), str(parsed.network)


def _domain_key(vlan: int, vrf: str, subnet: str) -> str:
    return f"vlan={vlan}|vrf={vrf}|subnet={subnet}"


def _candidate_key(protocol: str, group: str, virtual_ip: str) -> str:
    if not protocol or not group or not virtual_ip:
        return f"{protocol or 'UNRESOLVED'}:{group or 'UNRESOLVED'}:{virtual_ip or 'UNRESOLVED'}"
    return f"{protocol}:{group}:{virtual_ip}"


def _normalized_svis(all_interfaces: Any) -> Tuple[List[dict], set]:
    if not isinstance(all_interfaces, dict):
        return [], set()
    rows_by_identity: Dict[tuple, dict] = {}
    duplicate_ids = set()
    host_keys = [value for value in all_interfaces if isinstance(value, str)]
    for raw_host in sorted(host_keys, key=lambda value: (value.casefold(), value))[:_MAX_HOSTS]:
        host = _text(raw_host, 128)
        mapping = all_interfaces.get(raw_host)
        if not host or not isinstance(mapping, dict):
            continue
        interface_keys = [value for value in mapping if isinstance(value, str)]
        for raw_interface in sorted(
                interface_keys, key=lambda value: (value.casefold(), value)):
            interface = normalize_ifname(_text(raw_interface, 128))
            match = re.fullmatch(r"Vlan(\d+)", interface, flags=re.IGNORECASE)
            if not match:
                continue
            value = mapping.get(raw_interface)
            svi_ip, subnet = _ipv4_interface(_field(value, "svi_ip"))
            hsrp_behavior = _text(_field(value, "hsrp_behavior"), 500)
            if not svi_ip and not hsrp_behavior:
                continue
            vlan = int(match.group(1))
            if not 1 <= vlan <= 4094:
                continue
            raw_vrf = _field(value, "vrf")
            if raw_vrf is not None and not isinstance(raw_vrf, str):
                continue
            vrf = _normalize_vrf(raw_vrf)
            identity = _svi_identity(host, interface)
            if identity in rows_by_identity:
                duplicate_ids.add(identity)
                # One deterministic representative prevents a case/abbreviation
                # alias from becoming a second gateway or an invalid duplicate
                # output row.  ``duplicate_ids`` still withholds assessment.
                continue
            rows_by_identity[identity] = {
                "switch": host,
                "interface": normalize_ifname(interface),
                "svi_ip": svi_ip,
                "vlan": vlan,
                "vrf": vrf,
                "subnet": subnet,
                "domain_key": _domain_key(vlan, vrf, subnet),
                "positive_interface_hint": bool(hsrp_behavior),
            }
            if len(rows_by_identity) >= _MAX_ROWS:
                break
        if len(rows_by_identity) >= _MAX_ROWS:
            break
    rows = list(rows_by_identity.values())
    rows.sort(key=lambda row: (
        row["vlan"], row["vrf"], row["subnet"], row["switch"].casefold(),
        row["switch"], row["interface"].casefold(), row["interface"],
    ))
    return rows, duplicate_ids


def _svi_projection_hash(rows: List[dict]) -> str:
    return _sha([{key: row[key] for key in (
        "switch", "interface", "svi_ip", "vlan", "vrf", "subnet", "domain_key",
    )} for row in rows])


def _coverage_index(baseline: dict) -> Dict[tuple, dict]:
    return {
        (str(cell.get("switch", "")).casefold(), str(cell.get("protocol", ""))): cell
        for cell in baseline.get("coverage", []) if isinstance(cell, dict)
    }


def _complete_negative(host: str, coverage: Dict[tuple, dict]) -> bool:
    for protocol in _PROTOCOLS:
        cell = coverage.get((host.casefold(), protocol))
        if not isinstance(cell, dict):
            return False
        if (
            cell.get("config_capture_status") != "ok"
            or cell.get("config_parser_status") != "complete"
            or cell.get("runtime_capture_status") != "ok"
            or cell.get("runtime_parser_status") != "complete"
            or cell.get("config_rejected_count") != 0
            or cell.get("runtime_rejected_count") != 0
            or cell.get("unsupported_relevant_count") != 0
            or cell.get("config_candidate_count") != 0
            or cell.get("configured_group_count") != 0
            or cell.get("runtime_candidate_count") != 0
            or cell.get("runtime_parsed_count") != 0
        ):
            return False
    return True


def _member_evidence_complete(host: str, coverage: Dict[tuple, dict]) -> bool:
    """Require complete, integrity-ok config/runtime evidence for every subtype.

    Counts may be positive here: a participating member necessarily contributes
    rows.  The stricter exact-zero denominator remains in ``_complete_negative``.
    """
    for protocol in _PROTOCOLS:
        cell = coverage.get((host.casefold(), protocol))
        if not isinstance(cell, dict) or (
            cell.get("config_capture_status") != "ok"
            or cell.get("config_parser_status") != "complete"
            or cell.get("runtime_capture_status") != "ok"
            or cell.get("runtime_parser_status") != "complete"
            or cell.get("config_rejected_count") != 0
            or cell.get("runtime_rejected_count") != 0
            or cell.get("unsupported_relevant_count") != 0
        ):
            return False
    return True


def _candidate_virtual_ip(row: dict) -> str:
    configured = _text(row.get("configured_vip"), 64)
    runtime = _text(row.get("runtime_vip"), 64)
    if configured and runtime and configured == runtime:
        return configured
    return configured or runtime


def _local_findings(row: dict) -> List[dict]:
    status = row.get("status")
    if status == "degraded":
        return [_finding("local_group_degraded")]
    if status == "review":
        return [_finding("local_group_review")]
    if status == "not_verified":
        return [_finding("local_group_not_verified")]
    return []


def _worst_status(statuses: Iterable[str]) -> str:
    status = "assessed"
    for value in statuses:
        if value in _STATUS_RANK and _STATUS_RANK[value] > _STATUS_RANK[status]:
            status = value
    return status


def _domain_semantics(members: Iterable[dict], subnet: str) -> dict:
    """Derive every domain claim from the bounded member projection.

    Both the producer and validator call this routine.  That makes a re-sealed
    edit to a role, candidate set, local status, or participation state fail
    unless all derived findings and censuses still describe the edited facts.
    """
    values = list(members)
    findings: List[dict] = []
    if subnet == "(subnet-unobserved)":
        findings.append(_finding("subnet_unobserved"))

    candidate_sets: Dict[tuple, set] = defaultdict(set)
    candidate_records: Dict[str, List[dict]] = defaultdict(list)
    member_ids = set()
    participant_ids = set()
    for member in values:
        identity = _svi_identity(member["switch"], member["interface"])
        member_ids.add(identity)
        participation = member["participation"]
        if participation == "positive":
            participant_ids.add(identity)
            findings.extend(_local_findings({"status": member["local_status"]}))
            key = _candidate_key(
                member["protocol"], member["group"], member["virtual_ip"])
            candidate_sets[identity].add(key)
            candidate_records[key].append(member)
        elif participation == "nonparticipant":
            candidate_sets.setdefault(identity, set())
            findings.append(_finding("nonparticipant_intent_unresolved"))
        else:
            candidate_sets.setdefault(identity, set())
            findings.append(_finding("member_evidence_not_verified"))

    all_candidates = set().union(*candidate_sets.values()) if candidate_sets else set()
    if candidate_sets and any(keys != all_candidates for keys in candidate_sets.values()):
        findings.append(_finding("candidate_set_mismatch"))

    leader_count = 0
    backup_count = 0
    for key in sorted(candidate_records):
        records = candidate_records[key]
        protocol = records[0]["protocol"]
        leaders = {
            member["switch"].casefold() for member in records
            if member["role"] == _LEADERS.get(protocol)
        }
        backups = {
            member["switch"].casefold() for member in records
            if member["role"] in _BACKUPS.get(protocol, set())
        }
        leader_count += len(leaders)
        backup_count += len(backups)
        if len(leaders) > 1:
            findings.append(_finding("multiple_leaders_observed"))
        elif not leaders:
            findings.append(_finding("no_leader_observed"))
        if not backups:
            findings.append(_finding("no_backup_observed"))

    findings = _unique_findings(findings)
    protocols = sorted(
        {member["protocol"] for member in values if member["protocol"]},
        key=lambda value: _PROTOCOLS.index(value),
    )
    groups = sorted(
        {member["group"] for member in values if member["group"]},
        key=lambda value: (int(value) if value.isdigit() else 10**9, value),
    )
    virtual_ips = sorted(
        {member["virtual_ip"] for member in values if member["virtual_ip"]},
        key=lambda value: ipaddress.ip_address(value),
    )
    return {
        "findings": findings,
        "status": _worst_status(finding["kind"] for finding in findings),
        "member_count": len(member_ids),
        "participant_count": len(participant_ids),
        "leader_count": leader_count,
        "backup_count": backup_count,
        "candidate_count": len(all_candidates),
        "protocol": "/".join(protocols),
        "group": "/".join(groups),
        "virtual_ip": "/".join(virtual_ips),
    }


def _check(vlan: int, vrf: str, subnet: str) -> str:
    return f"FHRP redundancy-domain composition — VLAN {vlan} / {vrf} / {subnet}"


def _why(findings: Iterable[dict]) -> str:
    return "; ".join(finding["issue"] for finding in findings)


def _acceptance(status: str, *, vlan: int, vrf: str, subnet: str,
                member_count: int, candidate_count: int) -> str:
    identity = f"VLAN {vlan} / VRF {vrf} / observed IPv4 subnet {subnet}"
    boundary = (
        "Sequential captures are not simultaneous election evidence. No off-scan or intended peer "
        "count, timer, authentication, tracking, preemption, failover, or convergence claim is made."
    )
    if status == "degraded":
        return (
            f"PRE-CUTOVER DEGRADED — BLOCKER: {identity} contains a source-bound local FHRP "
            "configured/runtime fault. Restore the local group and re-collect every in-scope member; "
            f"matching the degraded state is NOT ACCEPTANCE. {boundary}"
        )
    if status == "not_verified":
        return (
            f"FHRP REDUNDANCY DOMAIN NOT VERIFIED — BLOCKER: {identity} could not be reconciled "
            "from complete source-bound subtype evidence. Re-collect configuration and all applicable "
            f"FHRP summaries before acceptance. {boundary}"
        )
    if status == "review":
        return (
            f"PRE-CUTOVER REVIEW — BLOCKER: {identity} has unresolved FHRP domain composition "
            f"across {member_count} in-scope gateway SVI(s) and {candidate_count} bounded candidate "
            "set(s). Verify intended domain membership and simultaneous roles, or explicitly disposition "
            f"independent gateways; matching this unresolved composition is NOT ACCEPTANCE. {boundary}"
        )
    return (
        f"Observed {identity} is boundedly assessed across {member_count} in-scope gateway SVI(s) "
        f"and {candidate_count} protocol/group/virtual-IP candidate set(s): each candidate has one "
        f"sequential leader and at least one accepted backup. Re-run every cited command and retain the "
        f"same exact healthy member/candidate identities. {boundary}"
    )


def _source_receipt(valid: bool, source_bound: bool, upstream_digest: str,
                    svi_digest: str) -> dict:
    return {
        "schema": FHRP_CONFIGURED_GROUP_SCHEMA,
        "valid": bool(valid),
        "source_bound": bool(source_bound),
        "configured_baseline_sha256": upstream_digest if valid else "",
        "svi_projection_sha256": svi_digest if valid else "",
    }


def _summary(domains: List[dict], rows: List[dict]) -> dict:
    counts = Counter(domain["status"] for domain in domains)
    members = {
        (row["domain_key"], row["switch"].casefold(), row["interface"].casefold())
        for row in rows
    }
    participants = {
        (row["domain_key"], row["switch"].casefold(), row["interface"].casefold())
        for row in rows if row["participation"] == "positive"
    }
    return {
        "n_domains": len(domains),
        "n_rows": len(rows),
        "n_members": len(members),
        "n_participants": len(participants),
        "n_assessed": counts["assessed"],
        "n_degraded": counts["degraded"],
        "n_review": counts["review"],
        "n_not_verified": counts["not_verified"],
        "by_status": {status: int(counts[status]) for status in _STATUSES},
        "baseline_sha256": "",
    }


def _verdict(domains: List[dict], source_valid: bool) -> Tuple[str, bool]:
    if not source_valid:
        return "INDETERMINATE", False
    statuses = Counter(domain["status"] for domain in domains)
    if statuses["degraded"]:
        return "BLOCKED", not (statuses["review"] or statuses["not_verified"])
    if statuses["review"] or statuses["not_verified"]:
        return "INDETERMINATE", False
    if statuses["assessed"]:
        return "CLEAR", True
    return "NOT_APPLICABLE", False


def _invalid_baseline() -> dict:
    finding = _finding("source_receipt_not_verified")
    top_finding = {**finding, "domain_key": ""}
    result: dict = {
        "schema": FHRP_REDUNDANCY_DOMAIN_SCHEMA,
        "scope": dict(_SCOPE),
        "verdict": "INDETERMINATE",
        "assessed": False,
        "projection_custody": "embedded_unverified",
        "source_receipt": _source_receipt(False, False, "", ""),
        "rows": [],
        "domains": [],
        "findings": [top_finding],
        "summary": _summary([], []),
        "limitations": list(_LIMITATIONS),
    }
    result["summary"]["baseline_sha256"] = _baseline_digest(result)
    return result


def scope_fhrp_redundancy_domains(all_interfaces: Any,
                                  fhrp_configured_group_baseline: Any) -> List[dict]:
    """Return only safe current SVI identities for potential subject domains.

    This helper never copies an invalid upstream leaf.  It is intentionally
    weaker than the decision owner and exists only so consumers can emit static
    NOT VERIFIED fallbacks without reimplementing domain grouping.
    """
    svis, _duplicates = _normalized_svis(all_interfaces)
    if not svis:
        return []
    positive = {
        _svi_identity(row["switch"], row["interface"])
        for row in svis if row["positive_interface_hint"]
    }
    view = validate_fhrp_configured_group_baseline(fhrp_configured_group_baseline)
    if view.get("valid"):
        for row in view.get("rows", []):
            if row.get("status") != "administratively_disabled" and (
                row.get("configured") or row.get("runtime_observed")
            ):
                positive.add(_svi_identity(row["switch"], row["interface"]))
    by_domain: Dict[str, List[dict]] = defaultdict(list)
    for row in svis:
        by_domain[row["domain_key"]].append(row)
    scoped: List[dict] = []
    for members in by_domain.values():
        if len({row["switch"].casefold() for row in members}) < 2:
            continue
        if not any(_svi_identity(row["switch"], row["interface"]) in positive for row in members):
            continue
        for row in members:
            scoped.append({key: row[key] for key in (
                "switch", "interface", "svi_ip", "vlan", "vrf", "subnet", "domain_key",
            )})
    scoped.sort(key=lambda row: (
        row["domain_key"], row["switch"].casefold(), row["switch"],
        row["interface"].casefold(), row["interface"],
    ))
    return scoped[:_MAX_ROWS]


def compute_fhrp_redundancy_domain_baseline(
        all_interfaces: Any, fhrp_configured_group_baseline: Any) -> dict:
    """Compute the current-run exact-domain FHRP composition receipt."""
    upstream = validate_fhrp_configured_group_baseline(
        fhrp_configured_group_baseline, require_current_run=True)
    svis, duplicate_ids = _normalized_svis(all_interfaces)
    if not upstream.get("valid"):
        return _invalid_baseline()

    upstream_baseline = upstream["baseline"]
    source_digest = _text(
        (upstream_baseline.get("summary") or {}).get("baseline_sha256"), 64)
    svi_digest = _svi_projection_hash(svis)
    if not source_digest or not svi_digest:
        return _invalid_baseline()

    source_rows: Dict[tuple, List[dict]] = defaultdict(list)
    for row in upstream.get("rows", []):
        if row.get("configured") or row.get("runtime_observed"):
            source_rows[_svi_identity(row["switch"], row["interface"])].append(row)
    for values in source_rows.values():
        values.sort(key=lambda row: (
            _PROTOCOLS.index(row["protocol"]), int(row["group"]),
        ))
    coverage = _coverage_index(upstream_baseline)

    by_domain: Dict[str, List[dict]] = defaultdict(list)
    for svi in svis:
        by_domain[svi["domain_key"]].append(svi)

    domains: List[dict] = []
    flat_rows: List[dict] = []
    top_findings: List[dict] = []
    custody = "current_run_projection_bound"

    for domain_key in sorted(by_domain, key=str.casefold):
        svi_members = by_domain[domain_key]
        if len({member["switch"].casefold() for member in svi_members}) < 2:
            continue
        member_sources = {
            _svi_identity(member["switch"], member["interface"]):
                source_rows.get(_svi_identity(member["switch"], member["interface"]), [])
            for member in svi_members
        }
        if not any(
                source.get("status") != "administratively_disabled"
                for sources in member_sources.values() for source in sources):
            continue

        local_member_rows: List[dict] = []
        for svi in svi_members:
            identity = _svi_identity(svi["switch"], svi["interface"])
            sources = member_sources[identity]
            member_complete = (
                identity not in duplicate_ids
                and _member_evidence_complete(svi["switch"], coverage)
            )
            if sources:
                for source in sources:
                    protocol = source["protocol"]
                    group = str(source["group"])
                    virtual_ip = _candidate_virtual_ip(source)
                    candidate_key = _candidate_key(protocol, group, virtual_ip)
                    role = _text(source.get("runtime_state"), 64)
                    local_status = (
                        ("review" if source["status"] == "administratively_disabled"
                         else source["status"])
                        if member_complete else "not_verified"
                    )
                    findings = _local_findings({"status": local_status})
                    local = {
                        "switch": svi["switch"],
                        "interface": svi["interface"],
                        "svi_ip": svi["svi_ip"],
                        "participation": "positive",
                        "protocol": protocol,
                        "group": group,
                        "virtual_ip": virtual_ip,
                        "role": role,
                        "local_status": local_status,
                        "source_group_key": f"{protocol}:{svi['interface']}:{group}",
                        "projection_custody": custody,
                        "findings": findings,
                        "candidate_key": candidate_key,
                        "command": source["command"],
                        "source_key": (
                            f"fhrp_configured_group_baseline.rows[{svi['switch']},{protocol},"
                            f"{svi['interface']},{group}] + interfaces[{svi['switch']},"
                            f"{svi['interface']}].svi_ip/vrf"
                        ),
                    }
                    local_member_rows.append(local)
            else:
                verified = (
                    identity not in duplicate_ids
                    and _complete_negative(svi["switch"], coverage)
                )
                code = (
                    "nonparticipant_intent_unresolved" if verified
                    else "member_evidence_not_verified"
                )
                finding = _finding(code)
                local_member_rows.append({
                    "switch": svi["switch"],
                    "interface": svi["interface"],
                    "svi_ip": svi["svi_ip"],
                    "participation": "nonparticipant" if verified else "not_verified",
                    "protocol": "",
                    "group": "",
                    "virtual_ip": "",
                    "role": "",
                    "local_status": "review" if verified else "not_verified",
                    "source_group_key": "",
                    "projection_custody": custody,
                    "findings": [finding],
                    "candidate_key": "",
                    "command": f"show running-config interface {svi['interface']}",
                    "source_key": (
                        f"interfaces[{svi['switch']},{svi['interface']}].svi_ip/vrf + "
                        f"fhrp_configured_group_baseline.coverage[{svi['switch']},HSRP|VRRP|GLBP]"
                    ),
                })
        vlan = svi_members[0]["vlan"]
        vrf = svi_members[0]["vrf"]
        subnet = svi_members[0]["subnet"]
        semantics = _domain_semantics(local_member_rows, subnet)
        domain_findings = semantics["findings"]
        status = semantics["status"]
        acceptance = _acceptance(
            status, vlan=vlan, vrf=vrf, subnet=subnet,
            member_count=semantics["member_count"],
            candidate_count=semantics["candidate_count"],
        )

        nested_members: List[dict] = []
        why = _why(domain_findings)
        for local in sorted(local_member_rows, key=lambda row: (
            row["switch"].casefold(), row["switch"], row["interface"].casefold(),
            row["candidate_key"],
        )):
            findings = [dict(finding) for finding in domain_findings]
            nested_members.append({
                key: copy.deepcopy(local[key]) for key in _MEMBER_KEYS
            } | {"findings": findings})
            flat_rows.append({
                "switch": local["switch"],
                "interface": local["interface"],
                "svi_ip": local["svi_ip"],
                "vlan": vlan,
                "vrf": vrf,
                "subnet": subnet,
                "domain_key": domain_key,
                "candidate_key": local["candidate_key"],
                "participation": local["participation"],
                "protocol": local["protocol"],
                "group": local["group"],
                "virtual_ip": local["virtual_ip"],
                "role": local["role"],
                "status": status,
                "check": _check(vlan, vrf, subnet),
                "command": local["command"],
                "acceptance": acceptance,
                "why": why,
                "source_key": local["source_key"],
                "projection_custody": custody,
                "findings": findings,
            })

        domain = {
            "vlan": vlan,
            "vrf": vrf,
            "subnet": subnet,
            "domain_key": domain_key,
            "status": status,
            "assessed": status in {"assessed", "degraded"},
            "member_count": semantics["member_count"],
            "participant_count": semantics["participant_count"],
            "leader_count": semantics["leader_count"],
            "backup_count": semantics["backup_count"],
            "protocol": semantics["protocol"],
            "group": semantics["group"],
            "virtual_ip": semantics["virtual_ip"],
            "members": nested_members,
            "findings": [dict(finding) for finding in domain_findings],
            "acceptance": acceptance,
        }
        domains.append(domain)
        top_findings.extend({**finding, "domain_key": domain_key}
                            for finding in domain_findings)

    domains.sort(key=lambda domain: (
        domain["vlan"], domain["vrf"], domain["subnet"], domain["domain_key"],
    ))
    flat_rows.sort(key=lambda row: (
        row["domain_key"], row["switch"].casefold(), row["switch"],
        row["interface"].casefold(), row["candidate_key"],
    ))
    top_findings.sort(key=lambda finding: (
        finding["domain_key"], finding["kind"], finding["code"], finding["issue"],
    ))
    verdict, assessed = _verdict(domains, True)
    result = _CurrentRunFhrpRedundancyDomainBaseline({
        "schema": FHRP_REDUNDANCY_DOMAIN_SCHEMA,
        "scope": dict(_SCOPE),
        "verdict": verdict,
        "assessed": assessed,
        "projection_custody": custody,
        "source_receipt": _source_receipt(True, True, source_digest, svi_digest),
        "rows": flat_rows,
        "domains": domains,
        "findings": top_findings[:_MAX_FINDINGS],
        "summary": _summary(domains, flat_rows),
        "limitations": list(_LIMITATIONS),
    })
    result["summary"]["baseline_sha256"] = _baseline_digest(result)
    valid, _reason = _structural_validation(result)
    if not valid:
        return _invalid_baseline()
    result._authorized_baseline_sha256 = result["summary"]["baseline_sha256"]
    return result


def _valid_finding(value: Any, *, top: bool = False) -> bool:
    keys = _TOP_FINDING_KEYS if top else _FINDING_KEYS
    if not isinstance(value, dict) or set(value) != keys:
        return False
    code = value.get("code")
    if code not in _FINDING_TEXT:
        return False
    kind, issue = _FINDING_TEXT[code]
    if value.get("kind") != kind or value.get("issue") != issue:
        return False
    if not top:
        return True
    domain_key = value.get("domain_key")
    if not isinstance(domain_key, str) or len(domain_key) > 500 \
            or any(ord(ch) < 32 for ch in domain_key):
        return False
    return (code == "source_receipt_not_verified") is (domain_key == "")


def _valid_text_fields(value: dict, fields: Iterable[str], limit: int = _MAX_TEXT,
                       *, allow_empty: bool = False) -> bool:
    for name in fields:
        item = value.get(name)
        if not isinstance(item, str) or len(item) > limit or any(ord(ch) < 32 for ch in item):
            return False
        if not allow_empty and not item:
            return False
    return True


def _structural_validation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != _ROOT_KEYS:
        return False, "baseline_root_invalid"
    if value.get("schema") != FHRP_REDUNDANCY_DOMAIN_SCHEMA or value.get("scope") != _SCOPE:
        return False, "baseline_scope_invalid"
    custody = value.get("projection_custody")
    if custody not in _CUSTODIES or value.get("verdict") not in _VERDICTS \
            or type(value.get("assessed")) is not bool:
        return False, "baseline_authority_invalid"
    source = value.get("source_receipt")
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        return False, "baseline_source_receipt_invalid"
    if source.get("schema") != FHRP_CONFIGURED_GROUP_SCHEMA \
            or type(source.get("valid")) is not bool or type(source.get("source_bound")) is not bool:
        return False, "baseline_source_receipt_invalid"
    for field in ("configured_baseline_sha256", "svi_projection_sha256"):
        token = source.get(field)
        if not isinstance(token, str) or (token and not re.fullmatch(r"[0-9a-f]{64}", token)):
            return False, "baseline_source_receipt_invalid"
    has_both_hashes = bool(
        source["configured_baseline_sha256"] and source["svi_projection_sha256"])
    if source["valid"] != has_both_hashes or (
            not source["valid"] and (
                source["configured_baseline_sha256"] or source["svi_projection_sha256"])):
        return False, "baseline_source_receipt_invalid"
    if source["source_bound"] and (custody != "current_run_projection_bound" or not source["valid"]):
        return False, "baseline_source_receipt_invalid"

    rows = value.get("rows")
    domains = value.get("domains")
    findings = value.get("findings")
    limitations = value.get("limitations")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        return False, "baseline_rows_invalid"
    if not isinstance(domains, list) or len(domains) > _MAX_DOMAINS:
        return False, "baseline_domains_invalid"
    if not isinstance(findings, list) or len(findings) > _MAX_FINDINGS \
            or not all(_valid_finding(item, top=True) for item in findings):
        return False, "baseline_findings_invalid"
    if limitations != _LIMITATIONS:
        return False, "baseline_limitations_invalid"

    domain_index: Dict[str, dict] = {}
    nested_by_domain: Dict[str, Dict[tuple, dict]] = {}
    host_spellings: Dict[str, str] = {}
    total_members = 0
    for domain in domains:
        if not isinstance(domain, dict) or set(domain) != _DOMAIN_KEYS:
            return False, "baseline_domain_invalid"
        if not _valid_text_fields(domain, ("vrf", "subnet", "domain_key", "acceptance")):
            return False, "baseline_domain_invalid"
        if not _valid_text_fields(domain, ("protocol", "group", "virtual_ip"), 500, allow_empty=True):
            return False, "baseline_domain_invalid"
        if type(domain.get("vlan")) is not int or not 1 <= domain["vlan"] <= 4094 \
                or domain.get("status") not in _STATUSES or type(domain.get("assessed")) is not bool:
            return False, "baseline_domain_invalid"
        for field in ("member_count", "participant_count", "leader_count", "backup_count"):
            if type(domain.get(field)) is not int or not 0 <= domain[field] <= _MAX_ROWS:
                return False, "baseline_domain_invalid"
        if domain["domain_key"] in domain_index:
            return False, "baseline_domain_duplicate"
        if domain["domain_key"] != _domain_key(domain["vlan"], domain["vrf"], domain["subnet"]):
            return False, "baseline_domain_identity_invalid"
        if _normalize_vrf(domain["vrf"]) != domain["vrf"]:
            return False, "baseline_domain_identity_invalid"
        if domain["subnet"] != "(subnet-unobserved)":
            try:
                network = ipaddress.ip_network(domain["subnet"], strict=True)
            except (ValueError, TypeError):
                return False, "baseline_domain_identity_invalid"
            if network.version != 4 or network.prefixlen == 32 \
                    or str(network) != domain["subnet"]:
                return False, "baseline_domain_identity_invalid"
        if domain["assessed"] is not (domain["status"] in {"assessed", "degraded"}):
            return False, "baseline_domain_status_invalid"
        domain_findings = domain.get("findings")
        members = domain.get("members")
        if not isinstance(domain_findings, list) or len(domain_findings) > 64 \
                or not all(_valid_finding(item) for item in domain_findings):
            return False, "baseline_domain_findings_invalid"
        if not isinstance(members, list) or len(members) > _MAX_ROWS:
            return False, "baseline_domain_members_invalid"
        total_members += len(members)
        if total_members > _MAX_ROWS:
            return False, "baseline_domain_members_invalid"
        nested_rows: Dict[tuple, dict] = {}
        member_hosts = set()
        participation_by_member: Dict[tuple, set] = defaultdict(set)
        groups_by_member: set = set()
        for member in members:
            if not isinstance(member, dict) or set(member) != _MEMBER_KEYS:
                return False, "baseline_domain_member_invalid"
            if not _valid_text_fields(member, ("switch", "interface")):
                return False, "baseline_domain_member_invalid"
            if not _valid_text_fields(member, (
                    "svi_ip", "protocol", "group", "virtual_ip", "role", "source_group_key"), 500,
                    allow_empty=True):
                return False, "baseline_domain_member_invalid"
            if member.get("participation") not in _PARTICIPATION \
                    or member.get("local_status") not in _STATUSES \
                    or member.get("projection_custody") != custody:
                return False, "baseline_domain_member_invalid"
            if not isinstance(member.get("findings"), list) or len(member["findings"]) > 64 \
                    or not all(_valid_finding(item) for item in member["findings"]):
                return False, "baseline_domain_member_invalid"
            host_key = member["switch"].casefold()
            if host_key in host_spellings and host_spellings[host_key] != member["switch"]:
                return False, "baseline_domain_member_identity_invalid"
            host_spellings[host_key] = member["switch"]
            interface = normalize_ifname(member["interface"])
            if interface != member["interface"] or not re.fullmatch(
                    rf"Vlan0*{domain['vlan']}", interface, flags=re.IGNORECASE):
                return False, "baseline_domain_member_identity_invalid"
            normalized_ip, member_subnet = _ipv4_interface(member["svi_ip"])
            if normalized_ip != member["svi_ip"] or member_subnet != domain["subnet"]:
                return False, "baseline_domain_member_identity_invalid"
            participation = member["participation"]
            member_identity = (host_key, interface.casefold())
            participation_by_member[member_identity].add(participation)
            if participation == "positive":
                protocol = member["protocol"]
                group = member["group"]
                if protocol not in _PROTOCOLS or not group.isdigit():
                    return False, "baseline_domain_member_candidate_invalid"
                low, high = _GROUP_LIMITS[protocol]
                if not low <= int(group) <= high or str(int(group)) != group:
                    return False, "baseline_domain_member_candidate_invalid"
                vip = member["virtual_ip"]
                if vip:
                    try:
                        parsed_vip = ipaddress.ip_address(vip)
                    except ValueError:
                        return False, "baseline_domain_member_candidate_invalid"
                    if parsed_vip.version != 4 or str(parsed_vip) != vip:
                        return False, "baseline_domain_member_candidate_invalid"
                if member["source_group_key"] != f"{protocol}:{interface}:{group}":
                    return False, "baseline_domain_member_candidate_invalid"
                local_group_identity = (*member_identity, protocol, group)
                if local_group_identity in groups_by_member:
                    return False, "baseline_domain_member_candidate_invalid"
                groups_by_member.add(local_group_identity)
                candidate_key = _candidate_key(protocol, group, vip)
            else:
                if any(member[field] for field in (
                        "protocol", "group", "virtual_ip", "role", "source_group_key")):
                    return False, "baseline_domain_member_candidate_invalid"
                if participation == "nonparticipant" and member["local_status"] != "review":
                    return False, "baseline_domain_member_candidate_invalid"
                if participation == "not_verified" and member["local_status"] != "not_verified":
                    return False, "baseline_domain_member_candidate_invalid"
                candidate_key = ""
            nested_key = (host_key, interface.casefold(), candidate_key)
            if nested_key in nested_rows:
                return False, "baseline_domain_member_duplicate"
            nested_rows[nested_key] = member
            member_hosts.add(host_key)
        if any(len(modes) != 1 for modes in participation_by_member.values()):
            return False, "baseline_domain_member_candidate_invalid"
        if len(member_hosts) < 2:
            return False, "baseline_domain_member_count_invalid"
        nested_by_domain[domain["domain_key"]] = nested_rows
        domain_index[domain["domain_key"]] = domain

    if any(finding["domain_key"] and finding["domain_key"] not in domain_index
           for finding in findings):
        return False, "baseline_findings_invalid"

    row_ids = set()
    by_domain_rows: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            return False, "baseline_row_invalid"
        if not _valid_text_fields(row, (
                "switch", "interface", "vrf", "subnet", "domain_key", "status",
                "check", "command", "acceptance", "source_key", "projection_custody")):
            return False, "baseline_row_invalid"
        if not _valid_text_fields(row, (
                "svi_ip", "candidate_key", "protocol", "group", "virtual_ip", "role", "why"),
                allow_empty=True):
            return False, "baseline_row_invalid"
        if type(row.get("vlan")) is not int or not 1 <= row["vlan"] <= 4094 \
                or row.get("participation") not in _PARTICIPATION \
                or row.get("status") not in _STATUSES or row.get("projection_custody") != custody:
            return False, "baseline_row_invalid"
        if row["domain_key"] not in domain_index \
                or row["domain_key"] != _domain_key(row["vlan"], row["vrf"], row["subnet"]):
            return False, "baseline_row_domain_invalid"
        if not isinstance(row.get("findings"), list) or len(row["findings"]) > 64 \
                or not all(_valid_finding(item) for item in row["findings"]):
            return False, "baseline_row_findings_invalid"
        domain = domain_index[row["domain_key"]]
        if (row["vlan"], row["vrf"], row["subnet"]) != (
                domain["vlan"], domain["vrf"], domain["subnet"]):
            return False, "baseline_row_domain_invalid"
        host_key = row["switch"].casefold()
        if host_key in host_spellings and host_spellings[host_key] != row["switch"]:
            return False, "baseline_row_identity_invalid"
        host_spellings[host_key] = row["switch"]
        interface = normalize_ifname(row["interface"])
        if interface != row["interface"] or not re.fullmatch(
                rf"Vlan0*{row['vlan']}", interface, flags=re.IGNORECASE):
            return False, "baseline_row_identity_invalid"
        normalized_ip, row_subnet = _ipv4_interface(row["svi_ip"])
        if normalized_ip != row["svi_ip"] or row_subnet != row["subnet"]:
            return False, "baseline_row_identity_invalid"
        if row["participation"] == "positive":
            protocol = row["protocol"]
            group = row["group"]
            if protocol not in _PROTOCOLS or not group.isdigit():
                return False, "baseline_row_candidate_invalid"
            low, high = _GROUP_LIMITS[protocol]
            if not low <= int(group) <= high or str(int(group)) != group:
                return False, "baseline_row_candidate_invalid"
            vip = row["virtual_ip"]
            if vip:
                try:
                    parsed_vip = ipaddress.ip_address(vip)
                except ValueError:
                    return False, "baseline_row_candidate_invalid"
                if parsed_vip.version != 4 or str(parsed_vip) != vip:
                    return False, "baseline_row_candidate_invalid"
            expected_candidate_key = _candidate_key(protocol, group, vip)
            if row["candidate_key"] != expected_candidate_key \
                    or row["command"] not in _COMMANDS[protocol]:
                return False, "baseline_row_candidate_invalid"
            expected_source_key = (
                f"fhrp_configured_group_baseline.rows[{row['switch']},{protocol},"
                f"{interface},{group}] + interfaces[{row['switch']},"
                f"{interface}].svi_ip/vrf"
            )
        else:
            if row["candidate_key"] or any(row[field] for field in (
                    "protocol", "group", "virtual_ip", "role")):
                return False, "baseline_row_candidate_invalid"
            if row["command"] != f"show running-config interface {interface}":
                return False, "baseline_row_candidate_invalid"
            expected_source_key = (
                f"interfaces[{row['switch']},{interface}].svi_ip/vrf + "
                f"fhrp_configured_group_baseline.coverage[{row['switch']},HSRP|VRRP|GLBP]"
            )
        if row["source_key"] != expected_source_key \
                or row["check"] != _check(row["vlan"], row["vrf"], row["subnet"]):
            return False, "baseline_row_receipt_invalid"
        row_id = (
            row["domain_key"], row["switch"].casefold(),
            normalize_ifname(row["interface"]).casefold(), row["candidate_key"],
        )
        if row_id in row_ids:
            return False, "baseline_row_duplicate"
        row_ids.add(row_id)
        by_domain_rows[row["domain_key"]].append(row)

    for domain_key, domain in domain_index.items():
        domain_rows = by_domain_rows.get(domain_key, [])
        if not domain_rows or any(row["status"] != domain["status"] for row in domain_rows):
            return False, "baseline_domain_row_status_mismatch"
        semantics = _domain_semantics(domain["members"], domain["subnet"])
        if any(domain[field] != semantics[field] for field in (
                "status", "member_count", "participant_count", "leader_count",
                "backup_count", "protocol", "group", "virtual_ip")):
            return False, "baseline_domain_semantics_mismatch"
        if domain["findings"] != semantics["findings"]:
            return False, "baseline_domain_findings_mismatch"
        expected_acceptance = _acceptance(
            domain["status"], vlan=domain["vlan"], vrf=domain["vrf"],
            subnet=domain["subnet"], member_count=domain["member_count"],
            candidate_count=semantics["candidate_count"],
        )
        if domain["acceptance"] != expected_acceptance:
            return False, "baseline_domain_acceptance_invalid"
        nested_rows = nested_by_domain[domain_key]
        flat_rows_for_domain = {
            (row["switch"].casefold(), row["interface"].casefold(), row["candidate_key"]): row
            for row in domain_rows
        }
        if set(flat_rows_for_domain) != set(nested_rows):
            return False, "baseline_domain_member_row_mismatch"
        expected_why = _why(semantics["findings"])
        for identity, member in nested_rows.items():
            row = flat_rows_for_domain[identity]
            for field in (
                    "switch", "interface", "svi_ip", "participation", "protocol",
                    "group", "virtual_ip", "role", "projection_custody", "findings"):
                if row[field] != member[field]:
                    return False, "baseline_domain_member_row_mismatch"
            if member["findings"] != semantics["findings"] \
                    or row["findings"] != semantics["findings"]:
                return False, "baseline_domain_findings_mismatch"
            if row["acceptance"] != expected_acceptance \
                    or row["why"] != expected_why:
                return False, "baseline_domain_acceptance_mismatch"

    expected_top_findings = sorted(
        [
            {**finding, "domain_key": domain["domain_key"]}
            for domain in domains for finding in domain["findings"]
        ],
        key=lambda finding: (
            finding["domain_key"], finding["kind"],
            finding["code"], finding["issue"],
        ),
    )
    if source["valid"]:
        if findings != expected_top_findings:
            return False, "baseline_findings_mismatch"
    else:
        expected_invalid = [{**_finding("source_receipt_not_verified"), "domain_key": ""}]
        if custody != "embedded_unverified" or source["source_bound"] \
                or rows or domains or findings != expected_invalid:
            return False, "baseline_unverified_source_leaves_invalid"

    summary = value.get("summary")
    if not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        return False, "baseline_summary_invalid"
    for field in _SUMMARY_KEYS - {"by_status", "baseline_sha256"}:
        if type(summary.get(field)) is not int or not 0 <= summary[field] <= _MAX_ROWS:
            return False, "baseline_summary_invalid"
    if not isinstance(summary.get("by_status"), dict) \
            or list(summary["by_status"]) != list(_STATUSES) \
            or any(type(summary["by_status"].get(status)) is not int
                   or summary["by_status"][status] < 0 for status in _STATUSES):
        return False, "baseline_summary_invalid"
    expected_summary = _summary(domains, rows)
    for field in _SUMMARY_KEYS - {"baseline_sha256"}:
        if summary.get(field) != expected_summary[field]:
            return False, "baseline_summary_mismatch"

    expected_verdict, expected_assessed = _verdict(domains, source["valid"])
    if value.get("verdict") != expected_verdict or value.get("assessed") is not expected_assessed:
        return False, "baseline_verdict_mismatch"
    digest = summary.get("baseline_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or digest != _baseline_digest(value):
        return False, "baseline_digest_mismatch"
    return True, "ok"


def validate_fhrp_redundancy_domain_baseline(
        value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the closed receipt and optionally require process-local custody."""
    present = value is not None
    try:
        valid, reason = _structural_validation(value)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        valid, reason = False, "baseline_validation_failed"
    source_bound = (
        valid
        and isinstance(value, _CurrentRunFhrpRedundancyDomainBaseline)
        and getattr(value, "_authorized_baseline_sha256", "")
        == (value.get("summary") or {}).get("baseline_sha256")
        and value.get("projection_custody") == "current_run_projection_bound"
        and (value.get("source_receipt") or {}).get("source_bound") is True
    )
    if require_current_run and not source_bound:
        valid = False
        reason = "baseline_not_current_run_source_bound"
    if not valid:
        return {
            "present": present,
            "valid": False,
            "reason": reason,
            "source_bound": False,
            "rows": [],
            "index": {},
            "domains": [],
            "domain_index": {},
            "baseline": {},
        }
    baseline = copy.deepcopy(dict(value))
    rows = baseline["rows"]
    domains = baseline["domains"]
    return {
        "present": True,
        "valid": True,
        "reason": "ok",
        "source_bound": source_bound,
        "rows": rows,
        "index": {
            (row["switch"], row["interface"], row["domain_key"], row["candidate_key"]): row
            for row in rows
        },
        "domains": domains,
        "domain_index": {domain["domain_key"]: domain for domain in domains},
        "baseline": baseline,
    }


def validate_fhrp_redundancy_domain_snapshot_evidence(
        value: Any, all_interfaces: Any) -> dict:
    """Reconcile one stored domain receipt to its co-published SVI source.

    Structural validation proves the receipt is internally self-consistent, but
    comparison custody also requires the exact normalized SVI projection that
    produced it.  Reuse the producer's normalization and digest routines so a
    valid receipt generated from a different or truncated ``interfaces`` tree
    cannot be grafted beside the admitted snapshot source.
    """
    view = validate_fhrp_redundancy_domain_baseline(value)
    if view.get("valid") is not True:
        return view
    # The process-local owner object already binds this exact normalized source
    # projection and supports legacy in-process callers that do not serialize
    # the full interface tree.  Stored JSON loses that authority and must prove
    # reconciliation to the co-published snapshot source below.
    if view.get("source_bound") is True:
        return view

    def invalid(reason: str) -> dict:
        return {
            "present": True,
            "valid": False,
            "reason": reason,
            "source_bound": False,
            "rows": [],
            "index": {},
            "domains": [],
            "domain_index": {},
            "baseline": {},
        }

    if not isinstance(all_interfaces, dict):
        return invalid("snapshot_interfaces_missing_or_malformed")
    try:
        svis, _duplicate_ids = _normalized_svis(all_interfaces)
        expected_digest = _svi_projection_hash(svis)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        return invalid("snapshot_svi_projection_normalization_failed")
    baseline = view.get("baseline")
    source = baseline.get("source_receipt") if isinstance(baseline, dict) else None
    if not isinstance(source, dict) or source.get("svi_projection_sha256") != expected_digest:
        return invalid("snapshot_svi_projection_digest_mismatch")
    return view


def embedded_fhrp_redundancy_domain_baseline(
        value: Any, *, configured_group_baseline: Any = None) -> dict:
    """Return a JSON-safe audit projection unable to authorize a decision.

    When the current-run configured-group owner is supplied, first prove it is
    the exact upstream receipt consumed by ``value`` and then bind the embedded
    domain receipt to that owner's deterministic embedded digest.  This keeps
    the two co-published JSON projections reconcilable without allowing an
    arbitrary embedded object or digest string to re-authorize the domain.
    """
    view = validate_fhrp_redundancy_domain_baseline(value)
    if not view.get("valid"):
        return _invalid_baseline()
    result = view["baseline"]
    if configured_group_baseline is not None:
        configured = validate_fhrp_configured_group_baseline(
            configured_group_baseline, require_current_run=True)
        configured_value = configured.get("baseline") \
            if configured.get("valid") is True else {}
        configured_summary = configured_value.get("summary") \
            if isinstance(configured_value, dict) else {}
        current_digest = configured_summary.get("baseline_sha256") \
            if isinstance(configured_summary, dict) else None
        source = result.get("source_receipt")
        if (not isinstance(source, dict) or source.get("valid") is not True
                or source.get("configured_baseline_sha256") != current_digest):
            return _invalid_baseline()
        embedded_configured = embedded_fhrp_configured_group_baseline(
            configured_group_baseline)
        embedded_view = validate_fhrp_configured_group_baseline(
            embedded_configured)
        embedded_value = embedded_view.get("baseline") \
            if embedded_view.get("valid") is True else {}
        embedded_summary = embedded_value.get("summary") \
            if isinstance(embedded_value, dict) else {}
        embedded_digest = embedded_summary.get("baseline_sha256") \
            if isinstance(embedded_summary, dict) else None
        if not isinstance(embedded_digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", embedded_digest):
            return _invalid_baseline()
        source["configured_baseline_sha256"] = embedded_digest
    result["projection_custody"] = "embedded_unverified"
    result["source_receipt"]["source_bound"] = False
    for row in result["rows"]:
        row["projection_custody"] = "embedded_unverified"
    for domain in result["domains"]:
        for member in domain["members"]:
            member["projection_custody"] = "embedded_unverified"
    result["summary"]["baseline_sha256"] = ""
    result["summary"]["baseline_sha256"] = _baseline_digest(result)
    return result


__all__ = [
    "FHRP_REDUNDANCY_DOMAIN_SCHEMA",
    "compute_fhrp_redundancy_domain_baseline",
    "validate_fhrp_redundancy_domain_baseline",
    "validate_fhrp_redundancy_domain_snapshot_evidence",
    "embedded_fhrp_redundancy_domain_baseline",
    "scope_fhrp_redundancy_domains",
]
