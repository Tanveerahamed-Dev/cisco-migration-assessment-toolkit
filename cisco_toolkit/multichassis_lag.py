"""Typed, source-explicit multichassis LAG assurance owners.

The legacy NX-OS vPC and EOS MLAG projections are useful local observations, but neither one is an
authoritative pair or attachment model.  This module deliberately accepts a bounded *typed* input
instead of reading command files; collector integration is a later step.  Its input shape is::

    {"observations": [{
        "switch": "leaf-a", "vendor": "cisco", "platform": "nxos",
        "collection_mode": "live", "peer_identity": "leaf-b", "domain_id": "10",
        "domain_state": {"peer_status": "peer adjacency formed ok", ...},
        "source": {
            "schema": "multichassis_lag_typed_source_receipt/1",
            "capture_status": "ok", "projection_custody": "current_run_source_bound",
            "source_sha256": "sha256:<64 hex>", "owner_version": "fixture-v1",
            "commands": ["show vpc", "show lacp neighbor"],
        },
        "legs": [{
            "attachment_id": "20", "local_port_channel": "Po20", "status": "up",
            "consistency": "success", "lacp_partner_system_id": "0011.2233.4455",
            "lacp_partner_aggregation_id": "42",
        }],
    }]}

Four claims remain separate throughout: local observation, reciprocal peer pair, local leg, and
reconciled dual-homed attachment.  A domain ID is only an observed attribute.  A pair requires A to
name B and B to name A explicitly.  An attachment additionally requires one leg on each proven peer
with the same normalized attachment ID, remote LACP system ID, and remote aggregation/key identity.

These owners are compositional and own no overall score or cutover verdict.  The canonical cutover
gate remains elsewhere.  Missing, unsupported, malformed, one-sided, or ambiguous evidence stays
``not_verified`` (or ``degraded`` when a definite bad state is observed); it never becomes healthy.
"""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from cisco_toolkit.protocol_assurance import (
    ASSURANCE_LEVELS,
    CHANGE_VOCABULARY,
    SUPPORT_PROFILE_SCHEMA,
    canonical_sha256,
)


MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA = "multichassis_lag_subject_scope/1"
MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA = "multichassis_lag_domain_baseline/1"
MULTICHASSIS_LAG_DELTA_SCHEMA = "multichassis_lag_delta/1"
MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA = "multichassis_lag_typed_source_receipt/1"
MULTICHASSIS_LAG_OWNER_VERSION = "1"

_FAMILY = "multichassis_lag"
_RECORD_TYPES = (
    "local_observation",
    "reciprocal_peer_pair",
    "local_leg",
    "reconciled_attachment",
)
_HEALTH_STATES = ("healthy", "degraded", "not_verified")
_FINDING_KINDS = {"degraded", "not_verified"}
_CUSTODIES = {"current_run_source_bound", "embedded_unverified"}
_CAPTURE_STATES = {"ok", "missing", "empty", "error", "unreadable", "incomplete"}
_MAX_OBSERVATIONS = 4096
_MAX_LEGS_PER_OBSERVATION = 4096
_MAX_TEXT = 256

_NXOS_REQUIRED_STATES = {
    "peer_status": ({"peer adjacency formed ok"}, {"peer adjacency not formed"}),
    "keepalive_status": ({"peer is alive"}, {"peer is not alive"}),
    "consistency": ({"success"}, {"failed"}),
    "peer_link_status": ({"up"}, {"down"}),
}
_EOS_REQUIRED_STATES = {
    "state": ({"active", "primary", "secondary"}, {"inactive"}),
    "neg_status": ({"connected"}, {"disconnected"}),
    "config_sanity": ({"consistent"}, {"inconsistent"}),
    "peer_link_status": ({"up"}, {"down"}),
    "local_intf_status": ({"up"}, {"down"}),
}
_LEG_REQUIRED_STATES = {
    "status": ({"up"}, {"down", "down*"}),
    "consistency": ({"success"}, {"failed"}),
}

_TRANSITION_DECISION_EFFECT = {
    "unchanged_healthy": "none",
    "unchanged_degraded": "block",
    "recovered": "none",
    "regressed": "block",
    "appeared": "review",
    "disappeared": "block",
    "intent_changed": "review",
    "coverage_lost": "not_verified",
    "not_comparable": "not_verified",
}
_TRANSITION_NOTES = {
    "unchanged_healthy": "The subject remains healthy under comparable evidence.",
    "unchanged_degraded": "The subject remains degraded; a clean delta does not clear a current fault.",
    "recovered": "The subject recovered from a degraded or previously unverified state.",
    "regressed": "The subject moved from healthy to a definite degraded state.",
    "appeared": "A newly observed subject requires expected-change reconciliation.",
    "disappeared": "A previously observed subject is absent from otherwise comparable evidence.",
    "intent_changed": "The subject identity is stable but its typed attachment intent changed.",
    "coverage_lost": "Required evidence was present before and is no longer verified after the change.",
    "not_comparable": "The subject cannot be compared with the available typed evidence.",
}

_LIMITATIONS = [
    "Catalog presence and parser availability are not runtime support evidence.",
    "The module validates caller-supplied typed observations and receipts; it does not collect or parse device commands.",
    "NX-OS is supported for live or offline typed evidence; EOS is supported only for offline typed evidence.",
    "No IOS, IOS-XE, Junos, VSS, StackWise Virtual, or other vendor/platform parity is inferred.",
    "Domain ID, vPC/MLAG ID, same-MAC learning, and topology proximity never establish a peer pair or attachment.",
    "Capacity, hashing, orphan behavior, dual-active exclusion, counters, and failure rehearsal remain outside this bounded owner.",
]


class _CurrentRunMultichassisLagBaseline(dict):
    """Process-local marker; JSON/deep reconstruction cannot self-authorize current-run custody."""


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or len(value) > limit:
        return ""
    text = value.strip()
    if not text or any(ord(ch) < 32 for ch in text):
        return ""
    try:
        text.encode("utf-8")
    except UnicodeError:
        return ""
    return text


def _token(value: Any) -> str:
    text = _text(value)
    return " ".join(text.casefold().split()) if text else ""


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list:
    return value if isinstance(value, list) else []


def _sha256(value: Any) -> bool:
    return bool(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def _finding(kind: str, code: str, issue: str) -> dict:
    return {"kind": kind, "code": code, "issue": issue}


def _dedupe_findings(findings: Iterable[dict]) -> List[dict]:
    unique = {
        (item.get("kind"), item.get("code"), item.get("issue")): item
        for item in findings
        if isinstance(item, dict)
        and item.get("kind") in _FINDING_KINDS
        and _text(item.get("code"))
        and _text(item.get("issue"), 1000)
    }
    return [unique[key] for key in sorted(unique)]


def _add(record: dict, kind: str, code: str, issue: str) -> None:
    record.setdefault("findings", []).append(_finding(kind, code, issue))


def _health(findings: Iterable[dict]) -> str:
    kinds = {item.get("kind") for item in findings if isinstance(item, dict)}
    if "degraded" in kinds:
        return "degraded"
    if "not_verified" in kinds:
        return "not_verified"
    return "healthy"


def _refresh(record: dict, assurance: str) -> None:
    record["findings"] = _dedupe_findings(record.get("findings", []))
    record["health_state"] = _health(record["findings"])
    record["assurance_level"] = (
        "not_verified" if record["health_state"] == "not_verified" else assurance
    )


def _stable_id(kind: str, payload: Any) -> str:
    return f"{kind}:{canonical_sha256(payload)[7:]}"


def _platform(value: Any) -> str:
    compact = re.sub(r"[^a-z0-9]", "", _token(value))
    if compact in {"nxos", "cisconxos"}:
        return "nxos"
    if compact in {"eos", "aristaeos"}:
        return "eos"
    return ""


def _domain_id(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return _text(value)


def _numeric_or_text(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    text = _text(value)
    if text.isdigit():
        return str(int(text))
    return _token(text)


def _port_channel(value: Any) -> str:
    text = _text(value)
    match = re.fullmatch(r"(?:po|port-channel)\s*0*(\d+)", text, re.IGNORECASE)
    return f"Po{int(match.group(1))}" if match else ""


def _system_id(value: Any) -> str:
    text = _text(value)
    compact = re.sub(r"[.:-]", "", text).casefold()
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        return ""
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _support(platform: str, vendor: str, collection_mode: str) -> bool:
    return (
        platform == "nxos" and vendor == "cisco" and collection_mode in {"live", "offline"}
    ) or (
        platform == "eos" and vendor == "arista" and collection_mode == "offline"
    )


def multichassis_lag_support_profile() -> dict:
    """Return the closed executable support profile; catalog presence is intentionally irrelevant."""
    return {
        "schema": SUPPORT_PROFILE_SCHEMA,
        "family": _FAMILY,
        "owner_schema": MULTICHASSIS_LAG_DELTA_SCHEMA,
        "implementation_state": "implemented",
        "assurance_level": "intent_reconciled_survival",
        "evidence_contracts": [
            MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA,
            MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA,
            MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA,
        ],
        "scope": {
            "pair_identity": "explicit_reciprocal_switch_identity",
            "attachment_identity": (
                "both_local_legs_plus_matching_remote_lacp_system_and_aggregation_key"
            ),
            "record_types": list(_RECORD_TYPES),
        },
        "variants": [
            {
                "vendor": "cisco",
                "platform": "nxos",
                "collection_modes": ["live", "offline"],
                "required_typed_evidence": ["vpc_domain_state", "explicit_peer_identity", "lacp_partner_identity"],
            },
            {
                "vendor": "arista",
                "platform": "eos",
                "collection_modes": ["offline"],
                "required_typed_evidence": ["mlag_domain_state", "explicit_peer_identity", "lacp_partner_identity"],
            },
        ],
        "runtime_support_claim": "typed_source_receipt_required_per_local_observation",
        "limitations": list(_LIMITATIONS),
    }


def _source_receipt(value: Any) -> dict:
    raw = _mapping(value)
    failures: List[str] = []
    schema = _text(raw.get("schema"))
    capture = _token(raw.get("capture_status"))
    custody = _token(raw.get("projection_custody"))
    digest = raw.get("source_sha256") if _sha256(raw.get("source_sha256")) else ""
    owner = _text(raw.get("owner_version"))
    commands_raw = raw.get("commands")
    commands: List[str] = []
    if schema != MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA:
        failures.append("source receipt schema is missing or unsupported")
    if capture not in _CAPTURE_STATES:
        failures.append("source receipt capture status is missing or unsupported")
    if custody not in _CUSTODIES:
        failures.append("source receipt custody is missing or unsupported")
    if not digest:
        failures.append("source receipt SHA-256 is missing or malformed")
    if not owner:
        failures.append("source receipt owner version is missing")
    if not isinstance(commands_raw, list) or not commands_raw or len(commands_raw) > 32:
        failures.append("source receipt commands are missing or malformed")
    else:
        for command in commands_raw:
            normalized = _text(command)
            if not normalized:
                failures.append("source receipt command identity is malformed")
            elif normalized not in commands:
                commands.append(normalized)
    valid = not failures
    source_bound = valid and capture == "ok" and custody == "current_run_source_bound"
    return {
        "schema": MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA,
        "valid": valid,
        "source_bound": source_bound,
        "capture_status": capture if capture in _CAPTURE_STATES else "",
        "projection_custody": custody if custody in _CUSTODIES else "embedded_unverified",
        "source_sha256": digest,
        "owner_version": owner,
        "commands": sorted(commands, key=lambda item: (item.casefold(), item)),
        "failures": list(dict.fromkeys(failures)),
    }


def _classify_required(record: dict, field: str, value: str,
                       good: set, bad: set, label: str) -> None:
    if value in good:
        return
    if value in bad:
        _add(record, "degraded", f"{field}_degraded", f"Observed {label} is a closed known-bad state.")
    elif not value:
        _add(record, "not_verified", f"{field}_missing", f"Required {label} was not observed.")
    else:
        _add(record, "not_verified", f"{field}_unknown", f"Observed {label} is outside the closed state vocabulary.")


def _normalize_observation(raw: Any, index: int) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    switch = _text(raw.get("switch"))
    if not switch:
        return None
    vendor = _token(raw.get("vendor"))
    platform = _platform(raw.get("platform"))
    collection_mode = _token(raw.get("collection_mode"))
    peer_identity = _text(raw.get("peer_identity"))
    domain_id = _domain_id(raw.get("domain_id"))
    source = _source_receipt(raw.get("source"))
    state_raw = _mapping(raw.get("domain_state"))
    state_rules = _NXOS_REQUIRED_STATES if platform == "nxos" else (
        _EOS_REQUIRED_STATES if platform == "eos" else {}
    )
    domain_state = {field: _token(state_raw.get(field)) for field in state_rules}
    legs_raw = raw.get("legs", [])
    record = {
        "record_type": "local_observation",
        "subject_id": _stable_id("local", {"switch": switch.casefold()}),
        "switch": switch,
        "vendor": vendor,
        "platform": platform,
        "collection_mode": collection_mode,
        "peer_identity": peer_identity,
        "domain_id": domain_id,
        "domain_state": domain_state,
        "reciprocal_pair_id": "",
        "leg_count": len(legs_raw) if isinstance(legs_raw, list) else 0,
        "source_custody": "current_run_source_bound" if source["source_bound"] else "embedded_unverified",
        "source_receipt": source,
        "findings": [],
        "_index": index,
        "_legs_raw": legs_raw if isinstance(legs_raw, list) else [],
        "_eligible": True,
        "_scope_findings": [],
    }
    if not _support(platform, vendor, collection_mode):
        issue = "The vendor/platform/collection-mode tuple is outside the closed support profile."
        _add(record, "not_verified", "support_profile_not_implemented", issue)
        record["_scope_findings"].append(_finding("not_verified", "support_profile_not_implemented", issue))
    if not source["source_bound"]:
        issue = "The typed observation is not backed by a complete current-run source receipt."
        _add(record, "not_verified", "source_receipt_not_bound", issue)
        record["_scope_findings"].append(_finding("not_verified", "source_receipt_not_bound", issue))
    if not peer_identity:
        issue = "An explicit peer identity was not supplied."
        _add(record, "not_verified", "peer_identity_missing", issue)
        record["_scope_findings"].append(_finding("not_verified", "peer_identity_missing", issue))
    if not domain_id:
        issue = "The locally observed domain ID is missing; it is never inferred from another device."
        _add(record, "not_verified", "domain_id_missing", issue)
        record["_scope_findings"].append(_finding("not_verified", "domain_id_missing", issue))
    if not isinstance(legs_raw, list) or len(record["_legs_raw"]) > _MAX_LEGS_PER_OBSERVATION:
        issue = "The local-leg projection is malformed or exceeds the bounded input limit."
        _add(record, "not_verified", "local_leg_projection_invalid", issue)
        record["_scope_findings"].append(_finding("not_verified", "local_leg_projection_invalid", issue))
        record["_legs_raw"] = []
        record["leg_count"] = 0
    for field, (good, bad) in state_rules.items():
        _classify_required(record, field, domain_state[field], good, bad,
                           f"{platform or 'unsupported'} {field.replace('_', ' ')}")
    _refresh(record, "local_safety_preservation")
    return record


def _prepare(value: Any) -> Tuple[List[dict], List[dict]]:
    findings: List[dict] = []
    raw_rows = value.get("observations") if isinstance(value, dict) else None
    if not isinstance(raw_rows, list):
        return [], [_finding("not_verified", "observation_root_invalid",
                             "The typed multichassis observation root is missing or malformed.")]
    if len(raw_rows) > _MAX_OBSERVATIONS:
        return [], [_finding("not_verified", "observation_limit_exceeded",
                             "The typed multichassis observation count exceeds the bounded owner limit.")]
    prepared = []
    for index, raw in enumerate(raw_rows):
        row = _normalize_observation(raw, index)
        if row is None:
            findings.append(_finding(
                "not_verified", "local_observation_identity_invalid",
                "A local observation has no usable switch identity and was not accepted.",
            ))
        else:
            prepared.append(row)
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in prepared:
        grouped[row["switch"].casefold()].append(row)
    collapsed: List[dict] = []
    for key in sorted(grouped):
        group = grouped[key]
        row = group[0]
        if len(group) > 1:
            issue = "Multiple local observations collide on one case-insensitive switch identity."
            _add(row, "not_verified", "local_observation_identity_duplicate", issue)
            row["_scope_findings"].append(
                _finding("not_verified", "local_observation_identity_duplicate", issue)
            )
            row["_eligible"] = False
            row["_legs_raw"] = []
            row["leg_count"] = 0
            _refresh(row, "local_safety_preservation")
        collapsed.append(row)
    if not collapsed and not findings:
        findings.append(_finding("not_verified", "observations_missing",
                                 "No typed multichassis local observation was supplied."))
    return collapsed, _dedupe_findings(findings)


def _public_observation(row: dict) -> dict:
    return {key: copy.deepcopy(row[key]) for key in (
        "record_type", "subject_id", "switch", "vendor", "platform", "collection_mode",
        "peer_identity", "domain_id", "domain_state", "reciprocal_pair_id", "leg_count",
        "health_state", "assurance_level", "source_custody", "source_receipt", "findings",
    )}


def _scope_from_prepared(prepared: List[dict], findings: List[dict]) -> dict:
    rows = []
    for row in prepared:
        scope_findings = _dedupe_findings(row.get("_scope_findings", []))
        rows.append({
            "subject_id": row["subject_id"],
            "switch": row["switch"],
            "vendor": row["vendor"],
            "platform": row["platform"],
            "collection_mode": row["collection_mode"],
            "peer_identity_present": bool(row["peer_identity"]),
            "domain_id_present": bool(row["domain_id"]),
            "local_leg_candidate_count": row["leg_count"],
            "status": "not_verified" if scope_findings else "in_scope",
            "assurance_level": "not_verified",
            "source_custody": row["source_custody"],
            "source_receipt": copy.deepcopy(row["source_receipt"]),
            "findings": scope_findings,
        })
    rows.sort(key=lambda item: (item["switch"].casefold(), item["switch"]))
    summary = {
        "n_local_subjects": len(rows),
        "n_in_scope": sum(row["status"] == "in_scope" for row in rows),
        "n_not_verified": sum(row["status"] == "not_verified" for row in rows),
        "scope_sha256": "",
    }
    result = {
        "schema": MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA,
        "owner_version": MULTICHASSIS_LAG_OWNER_VERSION,
        "family": _FAMILY,
        "owns_score": False,
        "owns_verdict": False,
        "support_profile": multichassis_lag_support_profile(),
        "rows": rows,
        "findings": copy.deepcopy(findings),
        "summary": summary,
        "limitations": list(_LIMITATIONS),
    }
    summary["scope_sha256"] = canonical_sha256({**result, "summary": {**summary, "scope_sha256": ""}})
    return result


def compute_multichassis_lag_subject_scope(value: Any) -> dict:
    """Return the bounded local subject denominator without making a pair or health claim."""
    try:
        prepared, findings = _prepare(value)
        return _scope_from_prepared(prepared, findings)
    except (Exception, MemoryError):
        return _scope_from_prepared([], [_finding(
            "not_verified", "subject_scope_failed",
            "The typed multichassis subject scope could not be normalized.",
        )])


def _pair_id(a: str, b: str) -> str:
    switches = sorted((a.casefold(), b.casefold()))
    return _stable_id("pair", {"switches": switches})


def _attachment_id(pair_id: str, local_attachment_id: str) -> str:
    return _stable_id("attachment", {
        "pair_id": pair_id,
        "local_attachment_id": local_attachment_id,
    })


def _leg_id(switch: str, attachment_id: str, port_channel: str, index: int) -> str:
    payload = {
        "switch": switch.casefold(),
        "attachment_id": attachment_id,
        "local_port_channel": port_channel.casefold(),
    }
    if not attachment_id or not port_channel:
        payload["invalid_index"] = index
    return _stable_id("leg", payload)


def _reconcile_pairs(prepared: List[dict]) -> List[dict]:
    index = {row["switch"].casefold(): row for row in prepared if row.get("_eligible")}
    pair_members: Dict[str, Tuple[dict, dict]] = {}
    for row in prepared:
        if not row.get("_eligible"):
            continue
        peer_key = row["peer_identity"].casefold() if row["peer_identity"] else ""
        peer = index.get(peer_key)
        reciprocal = (
            peer is not None
            and peer is not row
            and peer.get("peer_identity", "").casefold() == row["switch"].casefold()
        )
        if not reciprocal:
            _add(row, "not_verified", "peer_identity_not_reciprocal",
                 "The named peer did not explicitly and uniquely name this switch in return.")
            continue
        pair_id = _pair_id(row["switch"], peer["switch"])
        row["reciprocal_pair_id"] = pair_id
        pair_members[pair_id] = tuple(sorted((row, peer), key=lambda item: item["switch"].casefold()))

    by_domain: Dict[str, set] = defaultdict(set)
    for row in prepared:
        if row["domain_id"]:
            by_domain[row["domain_id"].casefold()].add(row["switch"].casefold())
    reused_domains = {domain for domain, switches in by_domain.items() if len(switches) > 2}
    for row in prepared:
        if row["domain_id"].casefold() in reused_domains:
            _add(row, "not_verified", "domain_id_reused",
                 "The same domain ID appears on more than one possible two-node domain; it is not pair identity.")
        _refresh(row, "local_safety_preservation")

    pairs = []
    for pair_id, members in sorted(pair_members.items()):
        a, b = members
        findings: List[dict] = []
        if a["health_state"] == "degraded" or b["health_state"] == "degraded":
            findings.append(_finding("degraded", "local_domain_degraded",
                                     "At least one reciprocal peer has a definite local domain fault."))
        elif a["health_state"] == "not_verified" or b["health_state"] == "not_verified":
            findings.append(_finding("not_verified", "local_domain_not_verified",
                                     "At least one reciprocal peer's local domain evidence is not verified."))
        if not a["domain_id"] or not b["domain_id"]:
            findings.append(_finding("not_verified", "pair_domain_id_missing",
                                     "A reciprocal pair lacks a locally observed domain ID on one or both peers."))
        elif a["domain_id"].casefold() != b["domain_id"].casefold():
            findings.append(_finding("degraded", "pair_domain_id_mismatch",
                                     "Explicit reciprocal peers report different domain IDs."))
        if a["platform"] != b["platform"] or a["vendor"] != b["vendor"]:
            findings.append(_finding("not_verified", "mixed_platform_pair_unsupported",
                                     "Cross-vendor or cross-platform multichassis pair semantics are unsupported."))
        if a["domain_id"].casefold() in reused_domains or b["domain_id"].casefold() in reused_domains:
            findings.append(_finding("not_verified", "domain_id_reused",
                                     "The pair's domain ID is reused elsewhere and is not accepted as unique identity."))
        pair = {
            "record_type": "reciprocal_peer_pair",
            "subject_id": pair_id,
            "pair_id": pair_id,
            "switches": [a["switch"], b["switch"]],
            "peer_evidence": [
                {"switch": a["switch"], "peer_identity": a["peer_identity"]},
                {"switch": b["switch"], "peer_identity": b["peer_identity"]},
            ],
            "platforms": [a["platform"], b["platform"]],
            "domain_ids": [a["domain_id"], b["domain_id"]],
            "source_custody": (
                "current_run_source_bound"
                if a["source_custody"] == b["source_custody"] == "current_run_source_bound"
                else "embedded_unverified"
            ),
            "findings": findings,
        }
        _refresh(pair, "intent_reconciled_survival")
        pairs.append(pair)
    return pairs


def _normalize_leg(observation: dict, raw: Any, index: int, pair_index: Mapping[str, dict]) -> dict:
    value = raw if isinstance(raw, dict) else {}
    attachment_id = _numeric_or_text(value.get("attachment_id"))
    port_channel = _port_channel(value.get("local_port_channel"))
    status = _token(value.get("status"))
    consistency = _token(value.get("consistency"))
    partner_system = _system_id(value.get("lacp_partner_system_id"))
    partner_aggregation = _numeric_or_text(value.get("lacp_partner_aggregation_id"))
    pair_id = observation["reciprocal_pair_id"]
    attachment_subject_id = _attachment_id(pair_id, attachment_id) if pair_id and attachment_id else ""
    leg = {
        "record_type": "local_leg",
        "subject_id": _leg_id(observation["switch"], attachment_id, port_channel, index),
        "switch": observation["switch"],
        "pair_id": pair_id,
        "attachment_subject_id": attachment_subject_id,
        "attachment_id": attachment_id,
        "local_port_channel": port_channel,
        "status": status,
        "consistency": consistency,
        "lacp_partner_system_id": partner_system,
        "lacp_partner_aggregation_id": partner_aggregation,
        "source_custody": observation["source_custody"],
        "findings": [],
    }
    if not isinstance(raw, dict):
        _add(leg, "not_verified", "local_leg_shape_invalid",
             "A local attachment-leg row is malformed.")
    if not attachment_id:
        _add(leg, "not_verified", "attachment_id_missing",
             "The local vPC/MLAG attachment ID is missing or malformed.")
    if not port_channel:
        _add(leg, "not_verified", "local_port_channel_missing",
             "The local port-channel identity is missing or malformed.")
    for field, (good, bad) in _LEG_REQUIRED_STATES.items():
        _classify_required(leg, field, leg[field], good, bad,
                           f"local leg {field.replace('_', ' ')}")
    if not partner_system:
        _add(leg, "not_verified", "lacp_partner_system_missing",
             "A normalized remote LACP system identity was not observed.")
    if not partner_aggregation:
        _add(leg, "not_verified", "lacp_partner_aggregation_missing",
             "A normalized remote LACP aggregation/key identity was not observed.")
    pair = pair_index.get(pair_id)
    if pair is None:
        _add(leg, "not_verified", "reciprocal_pair_missing",
             "The local leg is not bound to an explicitly reciprocal peer pair.")
    elif pair["health_state"] == "degraded":
        _add(leg, "degraded", "reciprocal_pair_degraded",
             "The proven peer pair carrying this local leg is degraded.")
    elif pair["health_state"] == "not_verified":
        _add(leg, "not_verified", "reciprocal_pair_not_verified",
             "The proven peer pair carrying this local leg is not fully verified.")
    _refresh(leg, "local_safety_preservation")
    return leg


def _reconcile_attachments(local_legs: List[dict], pairs: List[dict]) -> List[dict]:
    pair_index = {pair["pair_id"]: pair for pair in pairs}
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for leg in local_legs:
        if leg["attachment_subject_id"]:
            grouped[leg["attachment_subject_id"]].append(leg)
    attachments = []
    for subject_id, legs in sorted(grouped.items()):
        pair = pair_index.get(legs[0]["pair_id"])
        expected_switches = {switch.casefold() for switch in (pair or {}).get("switches", [])}
        actual_switches = {leg["switch"].casefold() for leg in legs}
        complete = len(legs) == 2 and actual_switches == expected_switches and len(actual_switches) == 2
        if not complete:
            for leg in legs:
                _add(leg, "not_verified", "attachment_legs_not_reciprocal",
                     "The attachment does not have exactly one local leg on each proven peer.")
                _refresh(leg, "local_safety_preservation")
            continue
        partner_systems = {leg["lacp_partner_system_id"] for leg in legs if leg["lacp_partner_system_id"]}
        partner_aggregations = {
            leg["lacp_partner_aggregation_id"] for leg in legs if leg["lacp_partner_aggregation_id"]
        }
        partner_complete = all(
            leg["lacp_partner_system_id"] and leg["lacp_partner_aggregation_id"] for leg in legs
        )
        if not partner_complete:
            for leg in legs:
                _add(leg, "not_verified", "attachment_partner_identity_incomplete",
                     "Both local legs require complete remote LACP system and aggregation identities.")
                _refresh(leg, "local_safety_preservation")
            continue
        if len(partner_systems) != 1 or len(partner_aggregations) != 1:
            for leg in legs:
                _add(leg, "degraded", "attachment_partner_identity_mismatch",
                     "Matching local attachment IDs report different remote LACP partner identities.")
                _refresh(leg, "local_safety_preservation")
            continue
        component_states = [pair["health_state"]] + [leg["health_state"] for leg in legs]
        if "degraded" in component_states:
            state = "degraded"
            findings = [_finding("degraded", "attachment_component_degraded",
                                 "The reconciled attachment has a degraded pair or local leg.")]
        elif "not_verified" in component_states:
            state = "not_verified"
            findings = [_finding("not_verified", "attachment_component_not_verified",
                                 "The attachment identity reconciles, but a pair or local leg is not fully verified.")]
        else:
            state = "healthy"
            findings = []
        attachment = {
            "record_type": "reconciled_attachment",
            "subject_id": subject_id,
            "pair_id": pair["pair_id"],
            "attachment_id": legs[0]["attachment_id"],
            "switches": list(pair["switches"]),
            "leg_subject_ids": sorted(leg["subject_id"] for leg in legs),
            "lacp_partner_system_id": next(iter(partner_systems)),
            "lacp_partner_aggregation_id": next(iter(partner_aggregations)),
            "health_state": state,
            "assurance_level": "not_verified" if state == "not_verified" else "intent_reconciled_survival",
            "source_custody": (
                "current_run_source_bound"
                if pair["source_custody"] == "current_run_source_bound"
                and all(leg["source_custody"] == "current_run_source_bound" for leg in legs)
                else "embedded_unverified"
            ),
            "findings": findings,
        }
        attachments.append(attachment)
    return attachments


def _baseline_digest(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    summary = _mapping(payload.get("summary"))
    summary["baseline_sha256"] = ""
    payload["summary"] = summary
    return canonical_sha256(payload)


def _summary(local: List[dict], pairs: List[dict], legs: List[dict],
             attachments: List[dict], findings: List[dict]) -> dict:
    records = local + pairs + legs + attachments
    by_type = Counter(record["record_type"] for record in records)
    by_health = Counter(record["health_state"] for record in records)
    return {
        "n_local_observations": len(local),
        "n_reciprocal_peer_pairs": len(pairs),
        "n_local_legs": len(legs),
        "n_reconciled_attachments": len(attachments),
        "n_findings": len(findings) + sum(len(record["findings"]) for record in records),
        "by_record_type": {record_type: int(by_type[record_type]) for record_type in _RECORD_TYPES},
        "by_health_state": {state: int(by_health[state]) for state in _HEALTH_STATES},
        "baseline_sha256": "",
    }


def compute_multichassis_lag_domain_baseline(value: Any) -> dict:
    """Build the source-explicit four-record multichassis domain/attachment baseline."""
    try:
        prepared, findings = _prepare(value)
        subject_scope = _scope_from_prepared(prepared, findings)
        pairs = _reconcile_pairs(prepared)
        pair_index = {pair["pair_id"]: pair for pair in pairs}
        legs: List[dict] = []
        for observation in prepared:
            for index, raw_leg in enumerate(observation.get("_legs_raw", [])):
                legs.append(_normalize_leg(observation, raw_leg, index, pair_index))
        by_leg_id: Dict[str, List[dict]] = defaultdict(list)
        for leg in legs:
            by_leg_id[leg["subject_id"]].append(leg)
        for duplicates in by_leg_id.values():
            if len(duplicates) > 1:
                for leg in duplicates:
                    _add(leg, "not_verified", "local_leg_identity_duplicate",
                         "Multiple local legs collide on one canonical leg identity.")
                    _refresh(leg, "local_safety_preservation")
        attachments = _reconcile_attachments(legs, pairs)
        local = [_public_observation(row) for row in prepared]
        local.sort(key=lambda item: (item["switch"].casefold(), item["switch"]))
        legs.sort(key=lambda item: (item["switch"].casefold(), item["attachment_id"], item["subject_id"]))
        attachments.sort(key=lambda item: item["subject_id"])
        custody = (
            "current_run_source_bound"
            if local and all(row["source_receipt"]["source_bound"] for row in local)
            else "embedded_unverified"
        )
        summary = _summary(local, pairs, legs, attachments, findings)
        result = _CurrentRunMultichassisLagBaseline({
            "schema": MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA,
            "owner_version": MULTICHASSIS_LAG_OWNER_VERSION,
            "family": _FAMILY,
            "owns_score": False,
            "owns_verdict": False,
            "support_profile": multichassis_lag_support_profile(),
            "subject_scope": subject_scope,
            "projection_custody": custody,
            "local_observations": local,
            "reciprocal_peer_pairs": pairs,
            "local_legs": legs,
            "reconciled_attachments": attachments,
            "findings": findings,
            "summary": summary,
            "limitations": list(_LIMITATIONS),
        })
        summary["baseline_sha256"] = _baseline_digest(result)
        result._authorized_baseline_sha256 = summary["baseline_sha256"]
        return result
    except (Exception, MemoryError):
        prepared: List[dict] = []
        findings = [_finding("not_verified", "baseline_failed",
                             "The typed multichassis baseline could not be normalized.")]
        scope = _scope_from_prepared(prepared, findings)
        summary = _summary([], [], [], [], findings)
        result = _CurrentRunMultichassisLagBaseline({
            "schema": MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA,
            "owner_version": MULTICHASSIS_LAG_OWNER_VERSION,
            "family": _FAMILY,
            "owns_score": False,
            "owns_verdict": False,
            "support_profile": multichassis_lag_support_profile(),
            "subject_scope": scope,
            "projection_custody": "embedded_unverified",
            "local_observations": [],
            "reciprocal_peer_pairs": [],
            "local_legs": [],
            "reconciled_attachments": [],
            "findings": findings,
            "summary": summary,
            "limitations": list(_LIMITATIONS),
        })
        summary["baseline_sha256"] = _baseline_digest(result)
        result._authorized_baseline_sha256 = summary["baseline_sha256"]
        return result


def _valid_finding(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"kind", "code", "issue"}
        and value.get("kind") in _FINDING_KINDS
        and bool(_text(value.get("code")))
        and bool(_text(value.get("issue"), 1000))
    )


def _record_common(record: Any, record_type: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("record_type") == record_type
        and _text(record.get("subject_id")) == record.get("subject_id")
        and record.get("health_state") in _HEALTH_STATES
        and record.get("assurance_level") in ASSURANCE_LEVELS
        and record.get("source_custody") in _CUSTODIES
        and isinstance(record.get("findings"), list)
        and all(_valid_finding(item) for item in record["findings"])
        and not (record["health_state"] == "not_verified"
                 and record["assurance_level"] != "not_verified")
    )


def _domain_states_healthy(record: Mapping[str, Any]) -> bool:
    rules = _NXOS_REQUIRED_STATES if record.get("platform") == "nxos" else (
        _EOS_REQUIRED_STATES if record.get("platform") == "eos" else {}
    )
    state = _mapping(record.get("domain_state"))
    return bool(rules) and set(state) == set(rules) and all(state.get(field) in good for field, (good, _) in rules.items())


def _structural_validation(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, dict) or value.get("schema") != MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA:
        return False, "baseline_schema_invalid"
    if value.get("owner_version") != MULTICHASSIS_LAG_OWNER_VERSION \
            or value.get("family") != _FAMILY \
            or value.get("owns_score") is not False \
            or value.get("owns_verdict") is not False:
        return False, "baseline_owner_invalid"
    if value.get("support_profile") != multichassis_lag_support_profile() \
            or value.get("projection_custody") not in _CUSTODIES \
            or value.get("limitations") != _LIMITATIONS:
        return False, "baseline_contract_invalid"
    arrays = {
        "local_observation": value.get("local_observations"),
        "reciprocal_peer_pair": value.get("reciprocal_peer_pairs"),
        "local_leg": value.get("local_legs"),
        "reconciled_attachment": value.get("reconciled_attachments"),
    }
    if any(not isinstance(rows, list) for rows in arrays.values()):
        return False, "baseline_record_arrays_invalid"
    if any(len(rows) > _MAX_OBSERVATIONS * _MAX_LEGS_PER_OBSERVATION for rows in arrays.values()):
        return False, "baseline_record_limit_invalid"
    local_index: Dict[str, dict] = {}
    local_by_switch: Dict[str, dict] = {}
    for record in arrays["local_observation"]:
        if not _record_common(record, "local_observation"):
            return False, "baseline_local_observation_invalid"
        switch = _text(record.get("switch"))
        if not switch or record["subject_id"] != _stable_id("local", {"switch": switch.casefold()}):
            return False, "baseline_local_identity_invalid"
        if record["subject_id"] in local_index or switch.casefold() in local_by_switch:
            return False, "baseline_local_identity_duplicate"
        source = record.get("source_receipt")
        if not isinstance(source, dict) or set(source) != {
            "schema", "valid", "source_bound", "capture_status", "projection_custody",
            "source_sha256", "owner_version", "commands", "failures",
        }:
            return False, "baseline_source_receipt_invalid"
        if record["health_state"] == "healthy" and (
                not source.get("source_bound")
                or not _support(record.get("platform"), record.get("vendor"), record.get("collection_mode"))
                or not _domain_states_healthy(record)
                or not _text(record.get("peer_identity"))
                or not _domain_id(record.get("domain_id"))
                or not _text(record.get("reciprocal_pair_id"))):
            return False, "baseline_local_false_health"
        local_index[record["subject_id"]] = record
        local_by_switch[switch.casefold()] = record
    domain_members: Dict[str, set] = defaultdict(set)
    for record in local_index.values():
        if record.get("domain_id"):
            domain_members[str(record["domain_id"]).casefold()].add(record["switch"].casefold())
    reused = {domain for domain, members in domain_members.items() if len(members) > 2}

    pair_index: Dict[str, dict] = {}
    for record in arrays["reciprocal_peer_pair"]:
        if not _record_common(record, "reciprocal_peer_pair"):
            return False, "baseline_pair_invalid"
        switches = record.get("switches")
        evidence = record.get("peer_evidence")
        if not isinstance(switches, list) or len(switches) != 2 or len({str(s).casefold() for s in switches}) != 2:
            return False, "baseline_pair_identity_invalid"
        if any(str(s).casefold() not in local_by_switch for s in switches):
            return False, "baseline_pair_member_invalid"
        expected_id = _pair_id(str(switches[0]), str(switches[1]))
        if record.get("pair_id") != expected_id or record["subject_id"] != expected_id:
            return False, "baseline_pair_identity_invalid"
        if not isinstance(evidence, list) or len(evidence) != 2:
            return False, "baseline_pair_evidence_invalid"
        evidence_map = {
            _text(item.get("switch")).casefold(): _text(item.get("peer_identity")).casefold()
            for item in evidence if isinstance(item, dict)
        }
        switch_keys = {str(s).casefold() for s in switches}
        if set(evidence_map) != switch_keys or any(evidence_map[switch] not in switch_keys - {switch} for switch in switch_keys):
            return False, "baseline_pair_evidence_invalid"
        for switch in switch_keys:
            if local_by_switch[switch].get("reciprocal_pair_id") != expected_id:
                return False, "baseline_pair_member_invalid"
        if record["health_state"] == "healthy":
            members = [local_by_switch[str(s).casefold()] for s in switches]
            domains = {member["domain_id"].casefold() for member in members}
            if any(member["health_state"] != "healthy" for member in members) \
                    or len(domains) != 1 or next(iter(domains), "") in reused \
                    or len({member["platform"] for member in members}) != 1:
                return False, "baseline_pair_false_health"
        if expected_id in pair_index:
            return False, "baseline_pair_duplicate"
        pair_index[expected_id] = record

    leg_index: Dict[str, dict] = {}
    legs_by_attachment: Dict[str, List[dict]] = defaultdict(list)
    for record in arrays["local_leg"]:
        if not _record_common(record, "local_leg"):
            return False, "baseline_local_leg_invalid"
        switch = _text(record.get("switch"))
        if switch.casefold() not in local_by_switch:
            return False, "baseline_local_leg_identity_invalid"
        if record["subject_id"] in leg_index:
            return False, "baseline_local_leg_duplicate"
        if record["health_state"] == "healthy" and (
                record.get("pair_id") not in pair_index
                or record.get("status") != "up"
                or record.get("consistency") != "success"
                or not _system_id(record.get("lacp_partner_system_id"))
                or not _numeric_or_text(record.get("lacp_partner_aggregation_id"))
                or pair_index[record["pair_id"]]["health_state"] != "healthy"):
            return False, "baseline_local_leg_false_health"
        attachment_subject = record.get("attachment_subject_id")
        if attachment_subject:
            if attachment_subject != _attachment_id(record.get("pair_id", ""), record.get("attachment_id", "")):
                return False, "baseline_local_leg_attachment_invalid"
            legs_by_attachment[attachment_subject].append(record)
        leg_index[record["subject_id"]] = record

    attachment_index: Dict[str, dict] = {}
    for record in arrays["reconciled_attachment"]:
        if not _record_common(record, "reconciled_attachment"):
            return False, "baseline_attachment_invalid"
        subject = record["subject_id"]
        pair = pair_index.get(record.get("pair_id"))
        legs = legs_by_attachment.get(subject, [])
        if pair is None or subject != _attachment_id(record["pair_id"], record.get("attachment_id", "")):
            return False, "baseline_attachment_identity_invalid"
        if len(legs) != 2 or {leg["switch"].casefold() for leg in legs} != {
                switch.casefold() for switch in pair["switches"]}:
            return False, "baseline_attachment_legs_invalid"
        if sorted(record.get("leg_subject_ids", [])) != sorted(leg["subject_id"] for leg in legs):
            return False, "baseline_attachment_legs_invalid"
        if any(
                leg["lacp_partner_system_id"] != record.get("lacp_partner_system_id")
                or leg["lacp_partner_aggregation_id"] != record.get("lacp_partner_aggregation_id")
                for leg in legs):
            return False, "baseline_attachment_partner_invalid"
        component_states = [pair["health_state"]] + [leg["health_state"] for leg in legs]
        expected_state = "degraded" if "degraded" in component_states else (
            "not_verified" if "not_verified" in component_states else "healthy"
        )
        if record["health_state"] != expected_state or subject in attachment_index:
            return False, "baseline_attachment_state_invalid"
        attachment_index[subject] = record

    findings = value.get("findings")
    if not isinstance(findings, list) or not all(_valid_finding(item) for item in findings):
        return False, "baseline_findings_invalid"
    summary = value.get("summary")
    if not isinstance(summary, dict) or not _sha256(summary.get("baseline_sha256")):
        return False, "baseline_summary_invalid"
    expected = _summary(
        arrays["local_observation"], arrays["reciprocal_peer_pair"], arrays["local_leg"],
        arrays["reconciled_attachment"], findings,
    )
    if any(summary.get(key) != expected[key] for key in expected if key != "baseline_sha256"):
        return False, "baseline_summary_mismatch"
    if summary["baseline_sha256"] != _baseline_digest(value):
        return False, "baseline_digest_mismatch"
    if not isinstance(value.get("subject_scope"), dict) \
            or value["subject_scope"].get("schema") != MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA:
        return False, "baseline_subject_scope_invalid"
    return True, "ok"


def validate_multichassis_lag_domain_baseline(
        value: Any, *, require_current_run: bool = False) -> dict:
    """Validate the closed baseline and optionally require its process-local source marker."""
    present = value is not None
    try:
        valid, reason = _structural_validation(value)
    except (Exception, MemoryError):
        valid, reason = False, "baseline_validation_failed"
    source_bound = bool(
        valid
        and isinstance(value, _CurrentRunMultichassisLagBaseline)
        and getattr(value, "_authorized_baseline_sha256", "")
        == _mapping(value.get("summary")).get("baseline_sha256")
        and value.get("projection_custody") == "current_run_source_bound"
    )
    if require_current_run and not source_bound:
        valid, reason = False, "baseline_not_current_run_source_bound"
    if not valid:
        return {
            "present": present,
            "valid": False,
            "source_bound": False,
            "reason": reason,
            "baseline": {},
        }
    return {
        "present": True,
        "valid": True,
        "source_bound": source_bound,
        "reason": "ok",
        "baseline": copy.deepcopy(dict(value)),
    }


def _source_binding(value: Any, before_digest: str, after_digest: str) -> Tuple[dict, List[str]]:
    raw = _mapping(value)
    failures = []
    result = {
        "custody": _token(raw.get("custody")),
        "before_snapshot_sha256": raw.get("before_snapshot_sha256") if _sha256(raw.get("before_snapshot_sha256")) else "",
        "after_snapshot_sha256": raw.get("after_snapshot_sha256") if _sha256(raw.get("after_snapshot_sha256")) else "",
        "before_baseline_sha256": raw.get("before_baseline_sha256") if _sha256(raw.get("before_baseline_sha256")) else "",
        "after_baseline_sha256": raw.get("after_baseline_sha256") if _sha256(raw.get("after_baseline_sha256")) else "",
    }
    if result["custody"] != "persisted_snapshot_bytes_bound":
        failures.append("comparison source custody is missing or unsupported")
    for side in ("before", "after"):
        if not result[f"{side}_snapshot_sha256"]:
            failures.append(f"{side} snapshot SHA-256 is missing or malformed")
        if not result[f"{side}_baseline_sha256"]:
            failures.append(f"{side} baseline SHA-256 is missing or malformed")
    if result["before_baseline_sha256"] != before_digest:
        failures.append("before baseline digest does not match the source binding")
    if result["after_baseline_sha256"] != after_digest:
        failures.append("after baseline digest does not match the source binding")
    return result, failures


def _semantic_projection(record: Mapping[str, Any]) -> dict:
    excluded = {
        "health_state", "assurance_level", "source_custody", "source_receipt", "findings",
    }
    return {key: copy.deepcopy(value) for key, value in record.items() if key not in excluded}


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[str]:
    before_semantic = _semantic_projection(before)
    after_semantic = _semantic_projection(after)
    return sorted(
        key for key in set(before_semantic) | set(after_semantic)
        if before_semantic.get(key) != after_semantic.get(key)
    )


def _transition(before: Optional[dict], after: Optional[dict], *,
                before_candidate: bool = False, after_candidate: bool = False) -> str:
    if before is None:
        if after is not None and after.get("health_state") == "not_verified":
            return "not_comparable"
        return "recovered" if before_candidate else "appeared"
    if after is None:
        if after_candidate:
            candidate_state = "degraded" if after_candidate == "degraded" else "not_verified"
            return "regressed" if candidate_state == "degraded" else "coverage_lost"
        return "disappeared"
    before_state = before.get("health_state")
    after_state = after.get("health_state")
    if after_state == "not_verified":
        return "not_comparable" if before_state == "not_verified" else "coverage_lost"
    if before_state == "not_verified":
        return "recovered"
    if before_state == "healthy" and after_state == "degraded":
        return "regressed"
    if before_state == "degraded" and after_state == "healthy":
        return "recovered"
    if _changed_fields(before, after):
        return "intent_changed"
    return "unchanged_healthy" if after_state == "healthy" else "unchanged_degraded"


def _not_comparable_delta(source_binding: dict, failures: List[str]) -> dict:
    counts = {token: 0 for token in CHANGE_VOCABULARY}
    counts["not_comparable"] = 1
    return {
        "schema": MULTICHASSIS_LAG_DELTA_SCHEMA,
        "owner_version": MULTICHASSIS_LAG_OWNER_VERSION,
        "family": _FAMILY,
        "owns_score": False,
        "owns_verdict": False,
        "assurance_level": "not_verified",
        "support_profile": multichassis_lag_support_profile(),
        "source_binding": source_binding,
        "comparison_failures": list(dict.fromkeys(failures)),
        "changes": [],
        "summary": {
            "n_subjects": 0,
            "n_changes": 0,
            "by_transition": counts,
        },
        "limitations": list(_LIMITATIONS),
    }


def compute_multichassis_lag_delta(
        before: Any, after: Any, *, source_binding: Any = None) -> dict:
    """Compare two exact typed baselines without owning an overall score or verdict."""
    before_view = validate_multichassis_lag_domain_baseline(before)
    after_view = validate_multichassis_lag_domain_baseline(after)
    failures = []
    if not before_view["valid"]:
        failures.append(f"before baseline is invalid: {before_view['reason']}")
    if not after_view["valid"]:
        failures.append(f"after baseline is invalid: {after_view['reason']}")
    before_digest = _mapping(_mapping(before).get("summary")).get("baseline_sha256", "")
    after_digest = _mapping(_mapping(after).get("summary")).get("baseline_sha256", "")
    binding, binding_failures = _source_binding(source_binding, before_digest, after_digest)
    failures.extend(binding_failures)
    if failures:
        return _not_comparable_delta(binding, failures)

    before_baseline = before_view["baseline"]
    after_baseline = after_view["baseline"]
    if _mapping(before_baseline.get("summary")).get("n_local_observations") == 0:
        failures.append("before baseline has no typed local multichassis observation")
    if _mapping(after_baseline.get("summary")).get("n_local_observations") == 0:
        failures.append("after baseline has no typed local multichassis observation")
    if failures:
        return _not_comparable_delta(binding, failures)
    arrays = (
        ("local_observation", "local_observations"),
        ("reciprocal_peer_pair", "reciprocal_peer_pairs"),
        ("local_leg", "local_legs"),
        ("reconciled_attachment", "reconciled_attachments"),
    )
    before_candidates: Dict[str, str] = {}
    after_candidates: Dict[str, str] = {}
    for side, target in ((before_baseline, before_candidates), (after_baseline, after_candidates)):
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for leg in side["local_legs"]:
            if leg.get("attachment_subject_id"):
                grouped[leg["attachment_subject_id"]].append(leg)
        for subject, legs in grouped.items():
            states = {leg["health_state"] for leg in legs}
            target[subject] = "degraded" if "degraded" in states else "not_verified"

    changes = []
    counts = {token: 0 for token in CHANGE_VOCABULARY}
    order = {record_type: index for index, record_type in enumerate(_RECORD_TYPES)}
    for record_type, key in arrays:
        before_index = {record["subject_id"]: record for record in before_baseline[key]}
        after_index = {record["subject_id"]: record for record in after_baseline[key]}
        for subject in sorted(set(before_index) | set(after_index)):
            before_record = before_index.get(subject)
            after_record = after_index.get(subject)
            before_candidate = record_type == "reconciled_attachment" and subject in before_candidates
            after_candidate_state = (
                after_candidates.get(subject, "") if record_type == "reconciled_attachment" else ""
            )
            transition = _transition(
                before_record,
                after_record,
                before_candidate=before_candidate,
                after_candidate=after_candidate_state,
            )
            counts[transition] += 1
            assurance = (after_record or before_record or {}).get("assurance_level", "not_verified")
            if transition in {"coverage_lost", "not_comparable"}:
                assurance = "not_verified"
            changes.append({
                "family": _FAMILY,
                "record_type": record_type,
                "subject": subject,
                "subject_id": subject,
                "transition": transition,
                "decision_effect": _TRANSITION_DECISION_EFFECT[transition],
                "assurance_level": assurance,
                "before_state": before_record.get("health_state") if before_record else "absent",
                "after_state": (
                    after_record.get("health_state") if after_record else
                    (after_candidate_state or "absent")
                ),
                "note": _TRANSITION_NOTES[transition],
                "changed_fields": (
                    _changed_fields(before_record, after_record)
                    if before_record is not None and after_record is not None else []
                ),
            })
    changes.sort(key=lambda row: (
        order.get(row["record_type"], 99), row["subject_id"], row["transition"]
    ))
    assurance = "not_verified" if counts["coverage_lost"] or counts["not_comparable"] else (
        "intent_reconciled_survival"
        if any(row["record_type"] in {"reciprocal_peer_pair", "reconciled_attachment"} for row in changes)
        else "local_safety_preservation"
    )
    return {
        "schema": MULTICHASSIS_LAG_DELTA_SCHEMA,
        "owner_version": MULTICHASSIS_LAG_OWNER_VERSION,
        "family": _FAMILY,
        "owns_score": False,
        "owns_verdict": False,
        "assurance_level": assurance,
        "support_profile": multichassis_lag_support_profile(),
        "source_binding": binding,
        "comparison_failures": [],
        "changes": changes,
        "summary": {
            "n_subjects": len(changes),
            "n_changes": sum(
                count for transition, count in counts.items()
                if transition not in {"unchanged_healthy", "unchanged_degraded"}
            ),
            "by_transition": counts,
        },
        "limitations": list(_LIMITATIONS),
    }


__all__ = [
    "MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA",
    "MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA",
    "MULTICHASSIS_LAG_DELTA_SCHEMA",
    "MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA",
    "MULTICHASSIS_LAG_OWNER_VERSION",
    "multichassis_lag_support_profile",
    "compute_multichassis_lag_subject_scope",
    "compute_multichassis_lag_domain_baseline",
    "validate_multichassis_lag_domain_baseline",
    "compute_multichassis_lag_delta",
]
