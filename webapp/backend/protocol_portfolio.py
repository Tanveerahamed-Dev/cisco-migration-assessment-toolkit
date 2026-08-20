"""Source-bound single-snapshot Protocol Assurance portfolio.

This module is an operator projection over already-published protocol owners.  It does not
recompute a cutover verdict, derive runtime support from the capability catalog, or claim that
AssessHub retained the original upload bytes.  The source boundary is the exact JSON blob stored in
``snapshots.snapshot_json`` and returned by :meth:`Store.get_bound_snapshot`.
"""

from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

from cisco_toolkit.analyze import (
    summarize_routing_baseline,
    summarize_stp_consistency_baseline,
    validate_etherchannel_baseline,
)
from cisco_toolkit.bgp_intent import validate_bgp_configured_peer_baseline
from cisco_toolkit.fhrp_intent import validate_fhrp_configured_group_baseline
from cisco_toolkit.fhrp_redundancy import validate_fhrp_redundancy_domain_baseline
from cisco_toolkit.ipv6_routing import validate_ipv6_routing_adjacency_baseline
from cisco_toolkit.multichassis_lag import validate_multichassis_lag_snapshot_evidence
from cisco_toolkit.protocol_deltas import reconcile_native_owner_subject_roster
from cisco_toolkit.protocol_assurance import (
    bound_snapshot_source,
    canonical_sha256,
    protocol_support_profiles,
)
from cisco_toolkit.vtp_safety import validate_vtp_safety_baseline


SECTION_KEY = "protocol_assurance"
RECEIPT_SCHEMA = "protocol_single_snapshot_receipt/1"
EXPORT_SCHEMA = "protocol_single_snapshot_export/1"
OWNER_VERSION = "1"
SUBJECT_RENDER_CAP = 100
PERSISTED_SOURCE = "persisted snapshots.snapshot_json blob"

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_UNAVAILABLE_STATES = {
    "analysis_unavailable",
    "capture_error",
    "captured_empty",
    "captured_no_record",
    "invalid",
    "missing",
    "not_collected",
    "not_verified",
    "unavailable",
    "unknown",
}
_REVIEW_STATES = {"partial", "review"}
_DETAIL_FIELDS = (
    "switch",
    "protocol",
    "interface",
    "peer",
    "group",
    "domain_key",
    "record_type",
    "attachment_id",
    "pair_id",
    "role",
    "operational_state",
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list:
    return value if isinstance(value, list) else []


def _count_map(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): count
        for key, count in value.items()
        if isinstance(key, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
    }


def _subject(
        family: str,
        subject: str,
        state: Any,
        contract: str,
        *,
        kind: str = "subject",
        row: Any = None) -> dict:
    detail = {
        field: row[field]
        for field in _DETAIL_FIELDS
        if isinstance(row, dict) and field in row and row[field] not in (None, "", [], {})
    }
    return {
        "family": family,
        "subject": subject,
        "kind": kind,
        "evidence_state": _text(state) or "not_verified",
        "source_contract": contract,
        "detail": detail,
    }


def _row_subjects(
        family: str,
        rows: Iterable[Any],
        contract: str,
        identity: Callable[[Mapping[str, Any]], str],
        *,
        state_field: str = "status",
        kind: str = "subject") -> List[dict]:
    subjects: List[dict] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        subject = _text(identity(raw))
        folded = subject.casefold()
        if not subject or folded in seen:
            continue
        seen.add(folded)
        subjects.append(
            _subject(family, subject, raw.get(state_field), contract, kind=kind, row=raw)
        )
    return sorted(subjects, key=lambda item: (item["subject"].casefold(), item["subject"]))


def _coverage_counts(baseline: Any) -> Dict[str, int]:
    summary = _mapping(_mapping(baseline).get("summary"))
    return _count_map(summary.get("by_coverage_status"))


def _producer_counts(baseline: Any, subjects: Sequence[dict]) -> Dict[str, int]:
    summary = _mapping(_mapping(baseline).get("summary"))
    reported = _count_map(summary.get("by_status"))
    if reported:
        return reported
    return dict(sorted(Counter(row["evidence_state"] for row in subjects).items()))


def _evidence_status(
        *,
        valid: bool,
        subjects: Sequence[dict],
        coverage: Mapping[str, int],
        force_partial: bool = False) -> str:
    if not valid:
        return "not_verified"
    states = [_text(row.get("evidence_state")).casefold() for row in subjects]
    unavailable = sum(state in _UNAVAILABLE_STATES for state in states)
    review = sum(state in _REVIEW_STATES for state in states)
    coverage_unavailable = sum(
        count for state, count in coverage.items() if state.casefold() in _UNAVAILABLE_STATES
    )
    coverage_review = sum(
        count for state, count in coverage.items() if state.casefold() in _REVIEW_STATES
    )
    if not subjects:
        applicable = sum(
            count for state, count in coverage.items()
            if state.casefold() != "not_applicable"
        )
        not_applicable = coverage.get("not_applicable", 0)
        if not_applicable and not applicable:
            return "not_applicable"
        return "not_verified"
    if unavailable == len(subjects) and not review:
        return "not_verified"
    if unavailable or review or coverage_unavailable or coverage_review or force_partial:
        return "partial"
    return "observed"


def _view(
        *,
        valid: bool,
        present: bool,
        reason: str,
        baseline: Any,
        subjects: Sequence[dict],
        force_partial: bool = False) -> dict:
    coverage = _coverage_counts(baseline)
    status = _evidence_status(
        valid=valid,
        subjects=subjects,
        coverage=coverage,
        force_partial=force_partial,
    )
    if not valid:
        producer_reason = reason.replace("_", " ") if reason else ""
        status_reason = (
            "Required family evidence is malformed"
            if present else "Required family evidence is missing"
        )
        status_reason += f" ({producer_reason})." if producer_reason else "."
    elif status == "not_applicable":
        status_reason = "The validated producer coverage identifies no applicable subject."
    elif status == "not_verified":
        status_reason = "No validated subject or complete applicability denominator was published."
    elif status == "partial":
        status_reason = "Validated producer evidence is present, but at least one required leaf remains review or not verified."
    else:
        status_reason = "Validated bounded producer evidence is present in the persisted snapshot."
    return {
        "present": present,
        "valid": valid,
        "evidence_status": status,
        "status_reason": status_reason,
        "source_custody": _text(_mapping(baseline).get("projection_custody")) or "not_reported",
        "producer_summary": dict(_mapping(_mapping(baseline).get("summary"))),
        "producer_state_counts": _producer_counts(baseline, subjects),
        "coverage_state_counts": coverage,
        "subjects": list(subjects),
    }


def _validated_baseline_view(
        snapshot: Mapping[str, Any],
        *,
        family: str,
        key: str,
        contract: str,
        validate: Callable[[Any], Mapping[str, Any]],
        identity: Callable[[Mapping[str, Any]], str],
        row_key: str = "rows",
        state_field: str = "status") -> dict:
    value = snapshot.get(key)
    try:
        validated = dict(validate(value))
    except (Exception, MemoryError):
        validated = {
            "present": value is not None,
            "valid": False,
            "reason": "family baseline validation failed",
        }
    baseline = _mapping(validated.get("baseline"))
    rows = validated.get(row_key)
    if not isinstance(rows, list):
        rows = baseline.get(row_key)
    coverage = baseline.get("coverage")
    validated = reconcile_native_owner_subject_roster(
        validated,
        snapshot,
        family=family,
        coverage_hosts=[
            cell.get("switch") if isinstance(cell, Mapping) else None
            for cell in coverage
        ] if isinstance(coverage, list) else None,
        subject_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in rows
        ] if isinstance(rows, list) else None,
    )
    baseline = _mapping(validated.get("baseline"))
    rows = validated.get(row_key)
    if not isinstance(rows, list):
        rows = baseline.get(row_key)
    subjects = _row_subjects(
        family,
        _rows(rows),
        contract,
        identity,
        state_field=state_field,
    )
    return _view(
        valid=validated.get("valid") is True,
        present=validated.get("present") is True,
        reason=_text(validated.get("reason")),
        baseline=baseline,
        subjects=subjects,
    )


def _routing_view(snapshot: Mapping[str, Any]) -> dict:
    family, contract = "ipv4_routing_adjacency", "routing_adjacency_baseline/1"
    present = "routing_neighbors" in snapshot or "protocol_assessability" in snapshot
    try:
        baseline = summarize_routing_baseline(
            snapshot.get("routing_neighbors"), snapshot.get("protocol_assessability")
        )
        valid = (
            isinstance(baseline, dict)
            and baseline.get("schema") == contract
            and isinstance(baseline.get("rows"), list)
        )
    except (Exception, MemoryError):
        baseline, valid = {}, False
    receipt = _mapping(_mapping(baseline).get("receipt"))
    receipt_rows = _mapping(snapshot.get("protocol_assessability")).get("rows")
    owner_view = reconcile_native_owner_subject_roster(
        {
            "valid": valid,
            "reason": (
                "routing adjacency owner sources are missing or malformed"
                if not valid else ""
            ),
            "baseline": baseline,
            "rows": _rows(_mapping(baseline).get("rows")),
        },
        snapshot,
        family=family,
        coverage_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in receipt_rows
        ] if receipt.get("valid") is True and isinstance(receipt_rows, list) else None,
        subject_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in _rows(_mapping(baseline).get("rows"))
        ],
    )
    baseline = _mapping(owner_view.get("baseline"))
    subjects: List[dict] = []
    if owner_view.get("valid") is True:
        for host_row in baseline["rows"]:
            if not isinstance(host_row, dict):
                continue
            host = _text(host_row.get("switch"))
            protocol = _text(host_row.get("protocol"))
            for peer in _rows(host_row.get("peers")):
                if not isinstance(peer, dict):
                    continue
                peer_key = _text(peer.get("peer_key")) or _text(peer.get("peer"))
                if host and protocol and peer_key:
                    subjects.append(_subject(
                        family,
                        "|".join((host, protocol, peer_key)),
                        peer.get("status"),
                        contract,
                        kind="observed_peer",
                        row={**peer, "switch": host, "protocol": protocol},
                    ))
    subjects.sort(key=lambda item: (item["subject"].casefold(), item["subject"]))
    return _view(
        valid=owner_view.get("valid") is True,
        present=present,
        reason=_text(owner_view.get("reason")),
        baseline=baseline,
        subjects=subjects,
    )


def _stp_consistency_view(snapshot: Mapping[str, Any]) -> dict:
    family, contract = "stp_consistency", "stp_consistency_baseline/1"
    present = any(
        key in snapshot
        for key in (
            "stp_consistency_baseline",
            "protocol_health",
            "protocol_assessability",
            "interfaces",
            "stp_roots",
        )
    )
    try:
        baseline = summarize_stp_consistency_baseline(
            snapshot.get("protocol_health"),
            snapshot.get("protocol_assessability"),
            all_interfaces=snapshot.get("interfaces"),
            stp_roots=snapshot.get("stp_roots"),
        )
        published = snapshot.get("stp_consistency_baseline")
        valid = (
            isinstance(baseline, dict)
            and baseline.get("schema") == contract
            and isinstance(baseline.get("rows"), list)
            and (published is None or published == baseline)
        )
    except (Exception, MemoryError):
        baseline, valid = {}, False
    receipt = _mapping(_mapping(baseline).get("receipt"))
    receipt_rows = _mapping(snapshot.get("protocol_assessability")).get("rows")
    owner_view = reconcile_native_owner_subject_roster(
        {
            "valid": valid,
            "reason": (
                "STP consistency owner sources are missing, malformed, or do not reconcile"
                if not valid else ""
            ),
            "baseline": baseline,
            "rows": _rows(_mapping(baseline).get("rows")),
        },
        snapshot,
        family=family,
        coverage_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in receipt_rows
        ] if receipt.get("valid") is True and isinstance(receipt_rows, list) else None,
        subject_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in _rows(_mapping(baseline).get("rows"))
        ],
    )
    baseline = _mapping(owner_view.get("baseline"))
    subjects = _row_subjects(
        family,
        _rows(_mapping(baseline).get("rows")),
        contract,
        lambda row: _text(row.get("switch")),
    )
    return _view(
        valid=owner_view.get("valid") is True,
        present=present,
        reason=_text(owner_view.get("reason")),
        baseline=baseline,
        subjects=subjects,
    )


def _stp_topology_view(snapshot: Mapping[str, Any]) -> dict:
    family, contract = "stp_topology", "stp_roots + interfaces projections"
    roots = snapshot.get("stp_roots")
    interfaces = snapshot.get("interfaces")
    present = "stp_roots" in snapshot or "interfaces" in snapshot
    valid = isinstance(roots, dict) and isinstance(interfaces, dict)
    subjects: List[dict] = []
    subject_hosts: List[str] = []
    malformed = False
    if valid:
        for host_value, instances in roots.items():
            host = _text(host_value)
            if not host or not isinstance(instances, dict):
                malformed = True
                continue
            for instance_value, row in instances.items():
                instance = _text(instance_value)
                if not instance or not isinstance(row, dict):
                    malformed = True
                    continue
                namespace = "mst_instance" if row.get("is_mst") is True else "vlan_instance"
                subjects.append(_subject(
                    family,
                    f"root|{host}|{namespace}|{instance}",
                    "observed",
                    contract,
                    kind="root",
                    row={**row, "switch": host},
                ))
                subject_hosts.append(host)
        for host_value, rows in interfaces.items():
            host = _text(host_value)
            if not host or not isinstance(rows, dict):
                malformed = True
                continue
            for interface_value, row in rows.items():
                interface = _text(interface_value)
                if not interface or not isinstance(row, dict):
                    continue
                forwarding, blocked = row.get("stp_fwd_vlans"), row.get("stp_blk_vlans")
                if not any(value not in (None, "") for value in (forwarding, blocked)):
                    continue
                if any(value not in (None, "") and not isinstance(value, str)
                       for value in (forwarding, blocked)):
                    malformed = True
                    subjects.append(_subject(
                        family,
                        f"path|{host}|{interface}",
                        "not_verified",
                        contract,
                        kind="path",
                        row={"switch": host, "interface": interface},
                    ))
                    subject_hosts.append(host)
                    continue
                subjects.append(_subject(
                    family,
                    f"path|{host}|{interface}",
                    "observed",
                    contract,
                    kind="path",
                    row={"switch": host, "interface": interface},
                ))
                subject_hosts.append(host)
    subjects.sort(key=lambda item: (item["subject"].casefold(), item["subject"]))
    baseline = {
        "projection_custody": "persisted_snapshot_projection",
        "summary": {"by_status": dict(Counter(row["evidence_state"] for row in subjects))},
    }
    owner_view = reconcile_native_owner_subject_roster(
        {
            "valid": valid and not malformed,
            "reason": (
                "STP root or interface projection is missing or malformed"
                if not (valid and not malformed) else ""
            ),
            "baseline": baseline,
            "rows": [],
        },
        snapshot,
        family=family,
        coverage_hosts=list(interfaces) if isinstance(interfaces, dict) else None,
        subject_hosts=subject_hosts,
    )
    if owner_view.get("valid") is not True:
        baseline = {}
        subjects = []
    return _view(
        valid=owner_view.get("valid") is True,
        present=present,
        reason=_text(owner_view.get("reason")),
        baseline=baseline,
        subjects=subjects if valid else [],
        # The current owner explicitly withholds complete roles and topology-change counters.
        force_partial=bool(subjects),
    )


def _etherchannel_view(snapshot: Mapping[str, Any]) -> dict:
    family, contract = "etherchannel", "etherchannel_baseline/1"
    value = snapshot.get("etherchannel_baseline")
    try:
        validated = validate_etherchannel_baseline(
            value,
            projection=snapshot.get("etherchannel_projection"),
            protocol_assessability=snapshot.get("protocol_assessability"),
            devices=snapshot.get("devices"),
        )
    except (Exception, MemoryError):
        validated = {"present": value is not None, "valid": False, "reason": "EtherChannel validation failed"}
    source_projection = snapshot.get("etherchannel_projection")
    projection_rows = _mapping(source_projection).get("rows")
    receipt_rows = _mapping(snapshot.get("protocol_assessability")).get("rows")
    subject_hosts = [
        row.get("switch") if isinstance(row, Mapping) else None
        for row in _rows(validated.get("rows"))
    ]
    validated = reconcile_native_owner_subject_roster(
        validated,
        snapshot,
        family="etherchannel projection",
        coverage_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in projection_rows
        ] if isinstance(projection_rows, list) else None,
        subject_hosts=subject_hosts,
    )
    validated = reconcile_native_owner_subject_roster(
        validated,
        snapshot,
        family="etherchannel receipt",
        coverage_hosts=[
            row.get("switch") if isinstance(row, Mapping) else None
            for row in receipt_rows
        ] if isinstance(receipt_rows, list) else None,
        subject_hosts=subject_hosts,
    )
    subjects: List[dict] = []
    for host_row in _rows(validated.get("rows")):
        if not isinstance(host_row, dict):
            continue
        host = _text(host_row.get("switch"))
        for group in _rows(host_row.get("groups")):
            if not isinstance(group, dict):
                continue
            name = _text(group.get("group"))
            if host and name:
                subjects.append(_subject(
                    family,
                    f"{host}|{name}",
                    group.get("status") or host_row.get("status"),
                    contract,
                    kind="local_group",
                    row={**group, "switch": host},
                ))
    baseline = value if validated.get("valid") is True and isinstance(value, dict) else {}
    subjects.sort(key=lambda item: (item["subject"].casefold(), item["subject"]))
    return _view(
        valid=validated.get("valid") is True,
        present=validated.get("present") is True,
        reason=_text(validated.get("reason")),
        baseline=baseline,
        subjects=subjects,
    )


def _multichassis_view(snapshot: Mapping[str, Any]) -> dict:
    family, contract = "multichassis_lag", "multichassis_lag_domain_baseline/1"
    value = snapshot.get("multichassis_lag_domain_baseline")
    try:
        validated = validate_multichassis_lag_snapshot_evidence(
            value,
            snapshot.get("multichassis_lag_typed_observations"),
            snapshot.get("devices"),
        )
    except (Exception, MemoryError):
        validated = {
            "valid": False,
            "reason": "multichassis snapshot evidence reconciliation failed",
            "baseline": {},
        }
    baseline = _mapping(validated.get("baseline"))
    subjects: List[dict] = []
    for key in (
        "local_observations",
        "reciprocal_peer_pairs",
        "local_legs",
        "reconciled_attachments",
    ):
        kind = key[:-1] if key.endswith("s") else key
        for record in _rows(baseline.get(key)):
            if not isinstance(record, dict):
                continue
            subject_id = _text(record.get("subject_id"))
            if subject_id:
                subjects.append(_subject(
                    family,
                    subject_id,
                    record.get("health_state"),
                    contract,
                    kind=kind,
                    row=record,
                ))
    subjects.sort(key=lambda item: (item["subject"].casefold(), item["subject"]))
    present = value is not None or "multichassis_lag_typed_observations" in snapshot
    reason = _text(validated.get("reason"))
    if value is None and "multichassis_lag_typed_observations" in snapshot:
        reason = "Typed observations are present, but the producer-owned domain baseline is absent"
    return _view(
        valid=validated.get("valid") is True,
        present=present,
        reason=reason,
        baseline=baseline,
        subjects=subjects,
    )


def _fhrp_domain_view(snapshot: Mapping[str, Any]) -> dict:
    """Project exact FHRP domains only when their configured-group roster still binds."""
    family, contract = "fhrp_redundancy_domain", "fhrp_redundancy_domain_baseline/1"
    value = snapshot.get("fhrp_redundancy_domain_baseline")
    try:
        validated = dict(validate_fhrp_redundancy_domain_baseline(value))
    except (Exception, MemoryError):
        validated = {
            "present": value is not None,
            "valid": False,
            "reason": "FHRP redundancy-domain validation failed",
            "baseline": {},
            "rows": [],
            "domains": [],
        }

    if validated.get("valid") is True:
        source = _mapping(_mapping(validated.get("baseline")).get("source_receipt"))
        configured_value = snapshot.get("fhrp_configured_group_baseline")
        try:
            configured = dict(validate_fhrp_configured_group_baseline(configured_value))
        except (Exception, MemoryError):
            configured = {"valid": False, "reason": "configured-group validation failed"}
        configured_baseline = _mapping(configured.get("baseline"))
        coverage = configured_baseline.get("coverage")
        configured_rows = configured.get("rows")
        configured = reconcile_native_owner_subject_roster(
            configured,
            snapshot,
            family=family,
            coverage_hosts=[
                cell.get("switch") if isinstance(cell, Mapping) else None
                for cell in coverage
            ] if isinstance(coverage, list) else None,
            subject_hosts=[
                row.get("switch") if isinstance(row, Mapping) else None
                for row in configured_rows
            ] if isinstance(configured_rows, list) else None,
        )
        configured_baseline = _mapping(configured.get("baseline"))
        configured_summary = _mapping(configured_baseline.get("summary"))
        expected_digest = configured_summary.get("baseline_sha256")
        if configured.get("valid") is not True:
            validated = {
                **validated,
                "valid": False,
                "reason": (
                    "fhrp_redundancy_domain configured-group source roster does not "
                    "reconcile to snapshot devices"
                ),
                "baseline": {},
                "rows": [],
                "domains": [],
            }
        elif source.get("configured_baseline_sha256") != expected_digest:
            validated = {
                **validated,
                "valid": False,
                "reason": (
                    "fhrp_redundancy_domain source receipt does not reconcile to the "
                    "co-published configured-group baseline"
                ),
                "baseline": {},
                "rows": [],
                "domains": [],
            }
        else:
            domain_rows = validated.get("rows")
            validated = reconcile_native_owner_subject_roster(
                validated,
                snapshot,
                family=family,
                coverage_hosts=[
                    cell.get("switch") if isinstance(cell, Mapping) else None
                    for cell in coverage
                ] if isinstance(coverage, list) else None,
                subject_hosts=[
                    row.get("switch") if isinstance(row, Mapping) else None
                    for row in domain_rows
                ] if isinstance(domain_rows, list) else None,
            )

    baseline = _mapping(validated.get("baseline"))
    subjects = _row_subjects(
        family,
        _rows(validated.get("domains")),
        contract,
        lambda row: _text(row.get("domain_key")),
    )
    return _view(
        valid=validated.get("valid") is True,
        present=validated.get("present") is True,
        reason=_text(validated.get("reason")),
        baseline=baseline,
        subjects=subjects,
    )


def _family_view(snapshot: Mapping[str, Any], family: str) -> dict:
    if family == "ipv4_routing_adjacency":
        return _routing_view(snapshot)
    if family == "ipv6_routing_adjacency":
        return _validated_baseline_view(
            snapshot,
            family=family,
            key="ipv6_routing_adjacency_baseline",
            contract="ipv6_routing_adjacency_baseline/1",
            validate=validate_ipv6_routing_adjacency_baseline,
            identity=lambda row: "|".join((
                _text(row.get("switch")), _text(row.get("protocol")), _text(row.get("peer_key")),
            )),
        )
    if family == "bgp_configured_peer":
        return _validated_baseline_view(
            snapshot,
            family=family,
            key="bgp_configured_peer_baseline",
            contract="bgp_configured_peer_baseline/1",
            validate=validate_bgp_configured_peer_baseline,
            identity=lambda row: "|".join((_text(row.get("switch")), _text(row.get("peer_key")))),
        )
    if family == "stp_consistency":
        return _stp_consistency_view(snapshot)
    if family == "stp_topology":
        return _stp_topology_view(snapshot)
    if family == "etherchannel":
        return _etherchannel_view(snapshot)
    if family == "vtp_safety":
        return _validated_baseline_view(
            snapshot,
            family=family,
            key="vtp_safety_baseline",
            contract="vtp_safety_baseline/1",
            validate=validate_vtp_safety_baseline,
            identity=lambda row: _text(row.get("switch")),
        )
    if family == "fhrp_configured_group":
        return _validated_baseline_view(
            snapshot,
            family=family,
            key="fhrp_configured_group_baseline",
            contract="fhrp_configured_group_baseline/1",
            validate=validate_fhrp_configured_group_baseline,
            identity=lambda row: "|".join((
                _text(row.get("switch")), _text(row.get("protocol")),
                _text(row.get("interface")), _text(row.get("group")),
            )),
        )
    if family == "fhrp_redundancy_domain":
        return _fhrp_domain_view(snapshot)
    if family == "multichassis_lag":
        return _multichassis_view(snapshot)
    return _view(
        valid=False,
        present=False,
        reason="No single-snapshot adapter is registered for this executable family owner",
        baseline={},
        subjects=[],
    )


def supported_family_count() -> int:
    """Count the closed executable profiles; never consult the capability catalog."""
    return len(protocol_support_profiles())


def _binding_failures(snapshot: Mapping[str, Any], binding: Mapping[str, Any]) -> List[str]:
    failures: List[str] = []
    source_marker = bound_snapshot_source(snapshot)
    if source_marker.get("source_bound") is not True:
        failures.append("exact persisted snapshot byte authority is unavailable")
    if binding.get("source") != PERSISTED_SOURCE:
        failures.append("persisted snapshot source owner is missing or unsupported")
    digest = binding.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        failures.append("persisted snapshot SHA-256 is missing or malformed")
    byte_count = binding.get("bytes")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
        failures.append("persisted snapshot byte count is missing or malformed")
    if source_marker.get("source_bound") is True and (
            digest != source_marker.get("sha256")
            or byte_count != source_marker.get("bytes")):
        failures.append("persisted snapshot binding does not match exact parsed source bytes")
    for field in ("snapshot_id", "campaign_id"):
        value = binding.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            failures.append(f"{field.replace('_', ' ')} is missing or malformed")
    if not _text(binding.get("engagement_id")):
        failures.append("engagement identity is missing or malformed")
    stored_owner = _text(binding.get("script_version"))
    snapshot_owner = _text(snapshot.get("script_version"))
    if not stored_owner or not snapshot_owner or stored_owner != snapshot_owner:
        failures.append("stored script owner does not match snapshot.script_version")
    return list(dict.fromkeys(failures))


def build_protocol_single_snapshot_bundle(
        snapshot: Any,
        binding: Mapping[str, Any],
        *,
        subject_cap: int = SUBJECT_RENDER_CAP) -> dict:
    """Return a capped receipt plus its complete, separately hashed JSON export payload."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    cap = subject_cap if isinstance(subject_cap, int) and not isinstance(subject_cap, bool) else 0
    cap = max(0, min(cap, 10_000))
    profiles = [dict(profile) for profile in protocol_support_profiles() if isinstance(profile, dict)]
    profiles.sort(key=lambda profile: (_text(profile.get("family")).casefold(), _text(profile.get("family"))))
    binding_copy = dict(binding) if isinstance(binding, Mapping) else {}
    custody_failures = _binding_failures(snap, binding_copy)

    complete_families: List[dict] = []
    rendered_families: List[dict] = []
    for profile in profiles:
        family = _text(profile.get("family"))
        evidence = _family_view(snap, family)
        if custody_failures:
            evidence = dict(evidence)
            evidence["evidence_status"] = "not_verified"
            evidence["status_reason"] = "Persisted-source custody is not verified for this receipt."
        all_subjects = list(evidence.pop("subjects"))
        contracts = profile.get("evidence_contracts")
        if not isinstance(contracts, list):
            contracts = ["multichassis_lag_domain_baseline/1"] if family == "multichassis_lag" else []
        common = {
            "family": family,
            "owner_schema": _text(profile.get("owner_schema")),
            "assurance_level": _text(profile.get("assurance_level")) or "not_verified",
            "evidence_contracts": list(contracts),
            "evidence_status": evidence["evidence_status"],
            "status_reason": evidence["status_reason"],
            "source_custody": evidence["source_custody"],
            "producer_summary": evidence["producer_summary"],
            "producer_state_counts": evidence["producer_state_counts"],
            "coverage_state_counts": evidence["coverage_state_counts"],
            "subject_total": len(all_subjects),
            "limitations": list(profile.get("limitations"))
            if isinstance(profile.get("limitations"), list) else [],
        }
        complete_families.append({**common, "subjects": all_subjects})
        rendered = all_subjects[:cap]
        rendered_families.append({
            **common,
            "subjects": {
                "total": len(all_subjects),
                "rendered": len(rendered),
                "omitted": len(all_subjects) - len(rendered),
                "rows": rendered,
            },
        })

    by_status = dict(sorted(Counter(family["evidence_status"] for family in complete_families).items()))
    summary = {
        "n_families": len(complete_families),
        "n_subjects_total": sum(family["subject_total"] for family in complete_families),
        "by_evidence_status": by_status,
    }
    script_owner = {
        "source": "snapshot.script_version + snapshots.script_version column",
        "snapshot_value": _text(snap.get("script_version")),
        "stored_value": _text(binding_copy.get("script_version")),
        "status": "bound" if not any("script owner" in item for item in custody_failures) else "not_verified",
    }
    complete_export = {
        "schema": EXPORT_SCHEMA,
        "owner_version": OWNER_VERSION,
        "owns_score": False,
        "owns_verdict": False,
        "custody_status": "bound" if not custody_failures else "not_verified",
        "custody_failures": custody_failures,
        "source_binding": binding_copy,
        "script_owner": script_owner,
        "support_profiles": profiles,
        "summary": summary,
        "families": complete_families,
        "custody_note": (
            "This export binds the exact persisted snapshots.snapshot_json bytes. AssessHub does not "
            "retain or claim the original upload bytes, and this receipt does not authenticate raw device captures."
        ),
    }
    export_sha256 = canonical_sha256(complete_export)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "owner_version": OWNER_VERSION,
        "owns_score": False,
        "owns_verdict": False,
        "custody_status": "bound" if not custody_failures else "not_verified",
        "custody_failures": custody_failures,
        "source_binding": binding_copy,
        "script_owner": script_owner,
        "support_profiles": profiles,
        "summary": summary,
        "families": rendered_families,
        "render_cap": cap,
        "complete_export": {
            "schema": EXPORT_SCHEMA,
            "sha256": export_sha256,
            "media_type": "application/json",
        },
        "custody_note": complete_export["custody_note"],
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return {"receipt": receipt, "complete_export": complete_export}


def canonical_export_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize an uncapped export deterministically for the download endpoint."""
    return json.dumps(
        dict(value),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "SECTION_KEY",
    "RECEIPT_SCHEMA",
    "EXPORT_SCHEMA",
    "SUBJECT_RENDER_CAP",
    "build_protocol_single_snapshot_bundle",
    "canonical_export_bytes",
    "supported_family_count",
]
