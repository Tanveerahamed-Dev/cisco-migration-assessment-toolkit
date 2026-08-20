"""Verdict-free L2 failure-rehearsal projections from existing assurance owners.

This module is a composer, not a path or protocol simulator.  It reuses:

* :mod:`cisco_toolkit.failover` for bounded STP root-failure candidates;
* the native EtherChannel and multichassis self-deltas for validated current state; and
* stored ``traffic_assurance_set/1`` results for any requested bounded service failure.

The result deliberately remains ``not_verified`` assurance. Candidate elections plus typed local
count, min-links, and worst-case bandwidth projections do not prove forwarding, convergence,
hashing distribution, service-path survival, or an operator rehearsal. The sole cutover verdict
owner remains ``cutover_gate/1``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, List, Mapping

from . import cutover_sim, failover, traffic_assurance
from .etherchannel import validate_etherchannel_operational_evidence
from .multichassis_lag import (
    compute_multichassis_lag_delta,
    validate_multichassis_lag_snapshot_evidence,
)
from .protocol_assurance import bound_snapshot_source
from .protocol_deltas import (
    compute_etherchannel_delta,
    compute_stp_consistency_delta,
    compute_stp_topology_delta,
)
from .traffic_assurance import TRAFFIC_ASSURANCE_OWNER, TRAFFIC_ASSURANCE_SET_SCHEMA
from .textutils import normalize_mac


L2_FAILURE_REHEARSAL_SCHEMA = "l2_failure_rehearsal/1"

_DISPOSITIONS = (
    "simulation_only",
    "projected_risk",
    "current_fault",
    "not_verified",
)
_GATE_FAMILIES = ("stp", "etherchannel", "multichassis_lag")
_SCENARIO_FAMILIES = frozenset((*_GATE_FAMILIES, "service_path"))
_SCENARIO_FIELDS = frozenset({
    "family", "subject", "failure_scenario", "disposition", "assurance_level",
    "source_owner", "current_fault", "evidence", "note",
})
_ROOT_FIELDS = frozenset({
    "schema", "owner", "owns_score", "owns_verdict", "status", "assurance_level",
    "source_bound", "applicability", "summary", "scenarios", "limitations",
})
_SUMMARY_FIELDS = frozenset({
    "n_scenarios", "n_current_faults", "n_projected_risks", "n_not_verified",
    "n_applicable_families", "by_disposition",
})
_MAX_STP_RECORDS = 16_384
_MAX_SCENARIOS = 16_384
_TRAFFIC_FAILURE_PARAMS = {
    "fail_node": frozenset({"id"}),
    "fail_site": frozenset({"id"}),
    "shut_link": frozenset({"host", "interface"}),
}
_CUTOVER_STEP_FIELDS = frozenset({
    "step_index", "action", "params", "ignored_field_count", "removed_hosts",
    "newly_lost_flows", "recovered_flows", "stp_reroots", "fhrp_takeovers",
    "split_brain_risks", "l2_continuity", "n_stp_election_candidates",
    "n_fhrp_election_candidates", "indeterminate", "valid", "validation_errors",
    "is_noop", "narrative",
})
_CUTOVER_SUMMARY_FIELDS = frozenset({
    "n_steps", "total_newly_lost", "total_recovered", "total_stp_reroots",
    "total_fhrp_takeovers", "total_stp_election_candidates",
    "total_fhrp_election_candidates", "total_split_brain_risks",
    "total_indeterminate", "n_noop_steps", "n_invalid_steps", "n_input_errors",
})
_L2_CONTINUITY_FIELDS = frozenset({
    "applicable", "assessed", "verdict", "election_projection_count",
    "affected_member_count", "affected_member_hosts", "reason",
})
_TRAFFIC_RESULT_FIELDS = frozenset({
    "schema", "owner", "intent", "valid", "validation_errors", "supported",
    "unsupported_semantics", "custody_trust", "verdict", "verdict_reasons", "dimensions",
    "failure", "claims", "nrfu_test_ids", "sources", "limitations",
})
_TRAFFIC_INTENT_FIELDS = frozenset({
    "id", "title", "src", "dst", "protocol", "src_port", "dst_port", "expected",
    "return_required", "required_mtu", "vrf",
})
_TRAFFIC_SOURCES = [
    "routes", "interfaces", "acls", "object_groups", "nat", "stp_roots", "fhrp_detail",
    "traffic_evidence_custody",
]
_INTERFACE_CUSTODY_BASIS = (
    "traffic_evidence_custody.hosts.*.interface_attachments + "
    "traffic_evidence_custody.hosts.*.global_forwarding_config"
)
_ROUTE_CUSTODY_BASIS = (
    "traffic_evidence_custody.hosts.*.routing_table + live reconciliation against "
    "scoped_route_projection/1"
)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _exact_fields(value: Any, fields: frozenset[str]) -> bool:
    return type(value) is dict and frozenset(value) == fields


def _bounded_dict_rows(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= _MAX_SCENARIOS and all(
        type(row) is dict for row in value
    )


def _bounded_text_rows(value: Any, *, empty_ok: bool = False) -> bool:
    return isinstance(value, list) and len(value) <= _MAX_SCENARIOS and all(
        isinstance(row, str) and (empty_ok or bool(_text(row))) for row in value
    )


def _scenario(
        *, family: str, subject: str, failure_scenario: str, disposition: str,
        source_owner: str, current_fault: bool, evidence: Mapping[str, Any], note: str) -> dict:
    if disposition not in _DISPOSITIONS:
        raise ValueError(f"unsupported L2 rehearsal disposition: {disposition}")
    return {
        "family": family,
        "subject": subject,
        "failure_scenario": failure_scenario,
        "disposition": disposition,
        "assurance_level": "not_verified",
        "source_owner": source_owner,
        "current_fault": current_fault,
        "evidence": dict(evidence),
        "note": note,
    }


def _gap(family: str, source_owner: str, note: str) -> dict:
    return _scenario(
        family=family,
        subject=f"{family}|coverage",
        failure_scenario="single_failure",
        disposition="not_verified",
        source_owner=source_owner,
        current_fault=False,
        evidence={},
        note=note,
    )


def _gate_family_applicability(snapshot: Mapping[str, Any]) -> dict:
    """Reuse native-family applicability without promoting placeholder gaps."""
    from .protocol_assurance import (
        _etherchannel_positive_or_malformed,
        _stp_positive_or_malformed,
    )

    try:
        stp = _stp_positive_or_malformed(snapshot)
    except (Exception, MemoryError):
        stp = any(key in snapshot for key in (
            "stp_roots", "stp_topology_baseline", "stp_topology_observations",
            "stp_consistency_baseline", "protocol_health",
        ))
    try:
        etherchannel = _etherchannel_positive_or_malformed(snapshot)
    except (Exception, MemoryError):
        etherchannel = any(key in snapshot for key in (
            "etherchannel_baseline", "etherchannel_projection",
            "etherchannel_operational_evidence",
        ))
    multichassis = (
        any(key in snapshot for key in (
            "multichassis_lag_typed_observations",
            "multichassis_lag_domain_baseline",
        ))
        or bool(snapshot.get("vpc"))
        or bool(snapshot.get("arista"))
    )
    return {
        "stp": bool(stp),
        "etherchannel": bool(etherchannel),
        "multichassis_lag": bool(multichassis),
    }


def _same_snapshot_binding(source: Mapping[str, Any]) -> dict:
    binding = {"sha256": _text(source.get("sha256"))}
    return {"before": binding, "after": dict(binding)}


def _stp_record_count(value: Any) -> int | None:
    if not isinstance(value, dict) or len(value) > _MAX_STP_RECORDS:
        return None
    total = 0
    for host, instances in value.items():
        if not _text(host) or not isinstance(instances, dict):
            return None
        total += len(instances)
        if total > _MAX_STP_RECORDS:
            return None
    return total


def _valid_failover_readiness(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != "failover_readiness/1":
        return False
    fields = (
        "n_stp_roots",
        "n_stp_roots_with_backup",
        "n_stp_default_election",
        "n_stp_indeterminate",
        "n_fhrp_actives",
        "n_fhrp_with_backup",
        "n_fhrp_split_brain",
        "n_fhrp_indeterminate",
    )
    if any(_count(value.get(field)) is None for field in fields):
        return False
    if value["n_stp_roots"] != sum(
            value[field] for field in (
                "n_stp_roots_with_backup", "n_stp_default_election", "n_stp_indeterminate")):
        return False
    risks = value.get("at_risk")
    return isinstance(risks, list) and len(risks) <= _MAX_SCENARIOS and all(
        isinstance(row, dict) for row in risks
    )


def _stp_scenarios(snapshot: Mapping[str, Any], source: Mapping[str, Any]) -> List[dict]:
    owner = "failover_readiness/1 + stp_consistency_delta/1 + stp_topology_delta/1"
    if source.get("source_bound") is not True:
        return [_gap(
            "stp", owner,
            "The snapshot is not bound to exact source bytes; STP failure candidates are not verified.",
        )]

    stp_records = _stp_record_count(snapshot.get("stp_roots"))
    if stp_records is None:
        return [_gap(
            "stp", owner,
            "The STP root projection is missing, malformed, or exceeds the bounded rehearsal limit.",
        )]

    binding = _same_snapshot_binding(source)
    try:
        consistency = compute_stp_consistency_delta(
            snapshot,
            snapshot,
            comparison_source_binding=binding,
        )
    except (Exception, MemoryError):
        return [_gap(
            "stp", owner,
            "The existing STP consistency owner could not reconcile the bounded current-state projection.",
        )]
    current_fault_subjects = sorted(
        row["subject"] for row in _list(consistency.get("changes"))
        if isinstance(row, dict)
        and row.get("transition") == "unchanged_degraded"
        and _text(row.get("subject"))
    )
    consistency_gap_subjects = sorted(
        row["subject"] for row in _list(consistency.get("changes"))
        if isinstance(row, dict)
        and row.get("transition") in {"coverage_lost", "not_comparable"}
        and _text(row.get("subject"))
    )
    try:
        topology = compute_stp_topology_delta(
            snapshot,
            snapshot,
            comparison_source_binding=binding,
        )
    except (Exception, MemoryError):
        return [_gap(
            "stp", owner,
            "The typed STP topology owner could not reconcile root, role/path, and counter evidence.",
        )]
    topology_changes = [
        row for row in _list(topology.get("changes")) if isinstance(row, dict)
    ]
    topology_fault_subjects = sorted(
        _text(row.get("subject")) for row in topology_changes
        if row.get("decision_effect") == "block" and _text(row.get("subject"))
    )
    topology_gap_subjects = sorted(
        _text(row.get("subject")) for row in topology_changes
        if row.get("transition") in {"coverage_lost", "not_comparable"}
        and _text(row.get("subject"))
    )
    topology_role_rows = [
        row for row in topology_changes if _text(row.get("subject")).startswith("path|")
    ]
    topology_counter_rows = [
        row for row in topology_changes if _text(row.get("subject")).startswith("counter|")
    ]
    topology_root_rows = [
        row for row in topology_changes if _text(row.get("subject")).startswith("root|")
    ]
    forwarding_paths = sum(
        _text(_dict(row.get("after_state")).get("state")) == "forwarding"
        for row in topology_role_rows
    )
    blocked_paths = sum(
        _text(_dict(row.get("after_state")).get("state")) == "blocked"
        for row in topology_role_rows
    )
    try:
        readiness = failover.compute_failover_readiness(dict(snapshot))
    except (Exception, MemoryError):
        return [_gap(
            "stp", owner,
            "The existing failover-readiness owner could not evaluate the bounded STP projection.",
        )]
    if not _valid_failover_readiness(readiness):
        return [_gap(
            "stp", owner,
            "The existing failover-readiness receipt is malformed or does not reconcile.",
        )]

    n_roots = readiness["n_stp_roots"]
    n_backup = readiness["n_stp_roots_with_backup"]
    n_default = readiness["n_stp_default_election"]
    n_indeterminate = readiness["n_stp_indeterminate"]
    all_current_faults = sorted(set(current_fault_subjects + topology_fault_subjects))
    all_coverage_gaps = sorted(set(consistency_gap_subjects + topology_gap_subjects))
    if all_current_faults:
        disposition = "current_fault"
    elif all_coverage_gaps or not n_roots or n_indeterminate:
        disposition = "not_verified"
    elif n_default:
        disposition = "projected_risk"
    else:
        disposition = "simulation_only"

    return [_scenario(
        family="stp",
        subject="stp|observed_current_roots",
        failure_scenario="single_proven_root_host_loss",
        disposition=disposition,
        source_owner=owner,
        current_fault=bool(all_current_faults),
        evidence={
            "n_root_subjects": n_roots,
            "n_candidate_backups": n_backup,
            "n_default_elections": n_default,
            "n_indeterminate": n_indeterminate,
            "n_current_faults": len(all_current_faults),
            "current_fault_subjects": all_current_faults,
            "n_consistency_not_verified": len(consistency_gap_subjects),
            "consistency_not_verified_subjects": consistency_gap_subjects,
            "n_topology_root_subjects": len(topology_root_rows),
            "n_topology_role_subjects": len(topology_role_rows),
            "n_forwarding_paths": forwarding_paths,
            "n_blocked_paths": blocked_paths,
            "n_topology_counter_subjects": len(topology_counter_rows),
            "n_topology_not_verified": len(topology_gap_subjects),
            "topology_not_verified_subjects": topology_gap_subjects,
            "n_source_records": stp_records,
        },
        note=(
            "The existing failover twin projects only a root-election candidate after one observed root "
            "host fails. Typed role/state and topology-change-counter coverage describes the current "
            "local precondition only; post-failure roles, loop freedom, convergence time, and service "
            "continuity remain not verified."
        ),
    )]


def _etherchannel_scenarios(
        snapshot: Mapping[str, Any], source: Mapping[str, Any]) -> List[dict]:
    owner = "etherchannel_delta/1"
    if source.get("source_bound") is not True:
        return [_gap(
            "etherchannel", owner,
            "The snapshot is not bound to exact source bytes; local member-failure capacity is not verified.",
        )]
    try:
        delta = compute_etherchannel_delta(
            snapshot,
            snapshot,
            comparison_source_binding=_same_snapshot_binding(source),
        )
    except (Exception, MemoryError):
        return [_gap(
            "etherchannel", owner,
            "The existing EtherChannel owner could not reconcile the bounded current-state projection.",
        )]
    changes = _list(delta.get("changes"))
    if len(changes) > _MAX_SCENARIOS:
        return [_gap(
            "etherchannel", owner,
            "The validated EtherChannel subject count exceeds the bounded rehearsal limit.",
        )]

    scenarios: List[dict] = []
    for row in changes:
        if not isinstance(row, dict):
            continue
        subject = _text(row.get("subject"))
        transition = _text(row.get("transition"))
        state = _dict(row.get("after_state"))
        capacity = _dict(state.get("capacity"))
        rehearsal = _dict(state.get("member_failure_rehearsal"))
        units = _count(capacity.get("forwarding_member_count"))
        rehearsal_status = _text(rehearsal.get("status"))
        if not subject or units is None or rehearsal_status not in {
                "pass", "fail", "not_verified"} or transition not in {
                "unchanged_healthy", "unchanged_degraded"}:
            scenarios.append(_scenario(
                family="etherchannel",
                subject=subject or "etherchannel|owner_receipt",
                failure_scenario="single_observed_forwarding_member_loss",
                disposition="not_verified",
                source_owner=owner,
                current_fault=False,
                evidence={"transition": transition or "not_comparable"},
                note=(
                    "The EtherChannel owner did not provide one comparable local group with a bounded "
                    "forwarding-member/min-links rehearsal; member-failure capacity is not verified."
                ),
            ))
            continue

        finding_codes = {
            _text(code) for code in _list(state.get("finding_codes")) if _text(code)
        }
        current_fault = bool(
            transition == "unchanged_degraded"
            and finding_codes - {"single_member_failure_unsafe"}
        )
        disposition = (
            "current_fault" if current_fault else
            "projected_risk" if rehearsal_status == "fail" else
            "simulation_only" if rehearsal_status == "pass" else
            "not_verified"
        )
        scenarios.append(_scenario(
            family="etherchannel",
            subject=subject,
            failure_scenario="single_observed_forwarding_member_loss",
            disposition=disposition,
            source_owner=owner,
            current_fault=current_fault,
            evidence={
                "protocol": _text(state.get("protocol")),
                "group_id": _text(state.get("group_id")),
                "observed_forwarding_member_count": units,
                "remaining_forwarding_members_after_loss": _count(
                    rehearsal.get("after_forwarding_members")),
                "configured_member_count": len(_list(state.get("configured_members"))),
                "runtime_member_count": len(_list(state.get("runtime_members"))),
                "configured_min_links": rehearsal.get("min_links"),
                "count_survives": rehearsal.get("count_survives"),
                "observed_forwarding_bandwidth_mbps": capacity.get(
                    "forwarding_bandwidth_mbps"),
                "remaining_worst_case_bandwidth_mbps": rehearsal.get(
                    "after_worst_case_bandwidth_mbps"),
                "partner_status": _text(_dict(state.get("partner")).get("status")),
                "counter_status": _text(
                    _dict(state.get("counter_evidence")).get("status")),
                "counter_fault_total": _count(
                    _dict(state.get("counter_evidence")).get("fault_total")),
                "service_path_survival": rehearsal.get("service_path_survival"),
            },
            note=(
                "This is local count/min-links and worst-case remaining-bandwidth evidence from the "
                "typed EtherChannel owner. Convergence, hashing distribution, remote forwarding, traffic "
                "continuity, and service-path survival remain not verified."
            ),
        ))
    return scenarios or [_gap(
        "etherchannel", owner,
        "No comparable validated local EtherChannel group was available; absence is not failure survival.",
    )]


def _multichassis_scenarios(
        snapshot: Mapping[str, Any], source: Mapping[str, Any]) -> List[dict]:
    owner = "multichassis_lag_delta/1"
    declared = any(bool(snapshot.get(key)) for key in (
        "multichassis_lag_domain_baseline", "multichassis_lag_typed_observations", "vpc", "arista"))
    if not declared:
        return [_gap(
            "multichassis_lag", owner,
            "No typed multichassis baseline is present; peer/attachment failure survival is not verified.",
        )]
    if source.get("source_bound") is not True:
        return [_gap(
            "multichassis_lag", owner,
            "The snapshot is not bound to exact source bytes; multichassis failure survival is not verified.",
        )]

    baseline = snapshot.get("multichassis_lag_domain_baseline")
    try:
        view = validate_multichassis_lag_snapshot_evidence(
            baseline,
            snapshot.get("multichassis_lag_typed_observations"),
            snapshot.get("devices"),
            legacy_vpc=snapshot.get("vpc"),
            legacy_arista=snapshot.get("arista"),
        )
        baseline_value = _dict(view.get("baseline"))
        if view.get("valid") is not True:
            return [_gap(
                "multichassis_lag", owner,
                "The stored baseline is not reconciled to the complete co-published typed observation set; "
                "peer-pair and dual-homed attachment failure survival is not verified.",
            )]
        summary = _dict(_dict(baseline).get("summary"))
        digest = _text(summary.get("baseline_sha256"))
        delta = compute_multichassis_lag_delta(
            baseline,
            baseline,
            source_binding={
                "custody": "persisted_snapshot_bytes_bound",
                "before_snapshot_sha256": _text(source.get("sha256")),
                "after_snapshot_sha256": _text(source.get("sha256")),
                "before_baseline_sha256": digest,
                "after_baseline_sha256": digest,
            },
        )
    except (Exception, MemoryError):
        return [_gap(
            "multichassis_lag", owner,
            "The existing typed multichassis owner could not reconcile the bounded current-state projection.",
        )]
    changes = _list(delta.get("changes"))
    if not view.get("valid") or delta.get("comparison_failures") or len(changes) > _MAX_SCENARIOS:
        failures = _list(delta.get("comparison_failures"))
        return [_scenario(
            family="multichassis_lag",
            subject="multichassis_lag|owner_receipt",
            failure_scenario="single_peer_or_local_leg_loss",
            disposition="not_verified",
            source_owner=owner,
            current_fault=False,
            evidence={
                "baseline_reason": _text(view.get("reason")),
                "comparison_failure_count": len(failures),
            },
            note=(
                "The typed multichassis baseline is missing, malformed, incompatible, or outside the "
                "bounded rehearsal limit; domain IDs and local vPC IDs are not failure evidence."
            ),
        )]

    attachment_index = {
        _text(row.get("subject_id")): row
        for row in _list(baseline_value.get("reconciled_attachments"))
        if isinstance(row, dict) and _text(row.get("subject_id"))
    }
    local_leg_index = {
        _text(row.get("subject_id")): row
        for row in _list(baseline_value.get("local_legs"))
        if isinstance(row, dict) and _text(row.get("subject_id"))
    }
    etherchannel_view = validate_etherchannel_operational_evidence(
        snapshot.get("etherchannel_operational_evidence"))
    etherchannel_index = (
        etherchannel_view.get("index")
        if etherchannel_view.get("valid") is True
        and isinstance(etherchannel_view.get("index"), dict) else {}
    )
    attachment_changes = [
        row for row in changes
        if isinstance(row, dict) and row.get("record_type") == "reconciled_attachment"
    ]
    scenarios: List[dict] = []
    current_fault_rows = [
        row for row in changes
        if isinstance(row, dict) and row.get("transition") == "unchanged_degraded"
    ]
    if current_fault_rows:
        scenarios.append(_scenario(
            family="multichassis_lag",
            subject="multichassis_lag|current_state",
            failure_scenario="current_state_precondition",
            disposition="current_fault",
            source_owner=owner,
            current_fault=True,
            evidence={
                "n_current_faults": len(current_fault_rows),
                "record_types": sorted({
                    _text(row.get("record_type")) for row in current_fault_rows
                    if _text(row.get("record_type"))
                }),
                "subjects": sorted(
                    _text(row.get("subject_id")) for row in current_fault_rows
                    if _text(row.get("subject_id"))
                ),
            },
            note=(
                "A typed multichassis degradation is already present. A projected surviving leg and a "
                "clean before/after transition cannot make the current fault acceptable."
            ),
        ))
    for observation in _list(baseline_value.get("local_observations")):
        if not isinstance(observation, dict) or _text(observation.get("platform")) != "nxos":
            continue
        switch = _text(observation.get("switch"))
        orphan = observation.get("orphan_evidence")
        if not isinstance(orphan, dict) or orphan.get("status") != "assessed":
            scenarios.append(_scenario(
                family="multichassis_lag",
                subject=f"multichassis_lag|orphan|{switch or 'unknown'}|coverage",
                failure_scenario="single_peer_or_local_device_loss",
                disposition="not_verified",
                source_owner=owner,
                current_fault=False,
                evidence={
                    "switch": switch,
                    "orphan_evidence_status": _text(_dict(orphan).get("status")),
                    "service_path_survival": "not_verified",
                },
                note=(
                    "NX-OS orphan-port table/config evidence is missing or incomplete; orphan behavior "
                    "during peer, peer-link, or local-device loss is not verified."
                ),
            ))
            continue
        for orphan_port in _list(orphan.get("ports")):
            if not isinstance(orphan_port, dict):
                continue
            interface = _text(orphan_port.get("interface"))
            suspended = orphan_port.get("suspend_on_peer_link_loss")
            scenarios.append(_scenario(
                family="multichassis_lag",
                subject=f"multichassis_lag|orphan|{switch}|{interface}",
                failure_scenario="single_peer_or_local_device_loss",
                disposition="projected_risk",
                source_owner=owner,
                current_fault=False,
                evidence={
                    "switch": switch,
                    "interface": interface,
                    "vlans": list(orphan_port.get("vlans", [])),
                    "suspend_on_peer_link_loss": suspended,
                    "peer_link_loss_behavior": (
                        "configured_suspend" if suspended is True else
                        "configured_no_suspend" if suspended is False else "not_verified"
                    ),
                    "service_path_survival": "not_verified",
                },
                note=(
                    "This explicitly observed orphan port is a projected local risk under peer or local-device "
                    "loss. Peer-link loss is configured to suspend the port; traffic continuity and service-path "
                    "survival remain not verified."
                    if suspended is True else
                    "This explicitly observed orphan port is a projected local risk under peer or local-device "
                    "loss. Peer-link behavior is disclosed from configuration only; traffic continuity and "
                    "service-path survival remain not verified."
                ),
            ))
    for row in attachment_changes:
        subject = _text(row.get("subject_id"))
        attachment = _dict(attachment_index.get(subject))
        legs = _list(attachment.get("leg_subject_ids"))
        transition = _text(row.get("transition"))
        leg_rows = [_dict(local_leg_index.get(leg_id)) for leg_id in legs]
        local_capacity = []
        join_valid = bool(etherchannel_index) and len(leg_rows) == 2
        for leg in leg_rows:
            switch, port_channel = _text(leg.get("switch")), _text(
                leg.get("local_port_channel"))
            ether_row = _dict(etherchannel_index.get((switch, port_channel)))
            partner = _dict(ether_row.get("partner"))
            rehearsal = _dict(ether_row.get("member_failure_rehearsal"))
            capacity = _dict(ether_row.get("capacity"))
            finding_codes = sorted({
                _text(finding.get("code"))
                for finding in _list(ether_row.get("findings"))
                if isinstance(finding, dict) and _text(finding.get("code"))
            })
            current_fault_codes = [
                code for code in finding_codes
                if code != "single_member_failure_unsafe"
            ]
            partner_matches = bool(
                partner.get("status") == "assessed"
                and normalize_mac(_text(partner.get("system_id")))
                == normalize_mac(_text(leg.get("lacp_partner_system_id")))
                and _text(partner.get("aggregation_id"))
                == _text(leg.get("lacp_partner_aggregation_id"))
            )
            leg_valid = bool(
                switch and port_channel and ether_row
                and _text(ether_row.get("status")) in {"assessed", "degraded"}
                and rehearsal.get("status") in {"pass", "fail"}
                and partner_matches
            )
            join_valid = join_valid and leg_valid
            local_capacity.append({
                "switch": switch,
                "port_channel": port_channel,
                "join_status": "reconciled" if leg_valid else "not_verified",
                "etherchannel_status": _text(ether_row.get("status")),
                "forwarding_member_count": capacity.get("forwarding_member_count"),
                "forwarding_bandwidth_mbps": capacity.get("forwarding_bandwidth_mbps"),
                "min_links": rehearsal.get("min_links"),
                "remaining_members_after_loss": rehearsal.get("after_forwarding_members"),
                "remaining_worst_case_bandwidth_mbps": rehearsal.get(
                    "after_worst_case_bandwidth_mbps"),
                "member_loss_status": rehearsal.get("status"),
                "current_fault_codes": current_fault_codes,
                "service_path_survival": "not_verified",
            })
        local_capacity.sort(key=lambda item: (
            item["switch"].casefold(), item["switch"], item["port_channel"]))
        if not subject or len(legs) != 2 or transition not in {
                "unchanged_healthy", "unchanged_degraded"}:
            disposition, current_fault = "not_verified", False
        elif not join_valid:
            disposition, current_fault = "not_verified", False
        else:
            typed_current_fault = any(
                item["etherchannel_status"] == "degraded"
                and bool(item["current_fault_codes"])
                for item in local_capacity
            )
            current_fault = transition == "unchanged_degraded" or typed_current_fault
            disposition = (
                "current_fault" if current_fault else
                "projected_risk" if any(
                    item["member_loss_status"] == "fail" for item in local_capacity) else
                "simulation_only"
            )
        scenarios.append(_scenario(
            family="multichassis_lag",
            subject=subject or "multichassis_lag|attachment",
            failure_scenario="single_reciprocal_peer_or_local_leg_loss",
            disposition=disposition,
            source_owner=owner,
            current_fault=current_fault,
            evidence={
                "transition": transition or "not_comparable",
                "reconciled_local_leg_count": len(legs),
                "remaining_observed_legs_after_loss": max(0, len(legs) - 1),
                "reciprocal_peer_evidenced": bool(_text(attachment.get("pair_id"))),
                "matching_lacp_partner_evidenced": bool(
                    _text(attachment.get("lacp_partner_system_id"))
                    and _text(attachment.get("lacp_partner_aggregation_id"))
                ),
                "etherchannel_local_leg_join": local_capacity,
                "etherchannel_local_leg_join_status": (
                    "reconciled" if join_valid else "not_verified"),
                "service_path_survival": "not_verified",
            },
            note=(
                "The typed multichassis owner proves the reciprocal pair/attachment identity; each local "
                "leg is separately joined to typed EtherChannel count, min-links, bandwidth, and member-loss "
                "evidence. Neither owner proves convergence, hashing distribution, remote forwarding, traffic "
                "continuity, orphan behavior, or service-path survival."
            ),
        ))
    return scenarios or [_gap(
        "multichassis_lag", owner,
        "Typed multichassis evidence did not reconcile a dual-homed attachment with reciprocal peers and "
        "matching LACP partner/aggregation identity; single-peer survival is not verified.",
    )]


def _valid_flow_rows(value: Any, kind: str) -> bool:
    return _bounded_dict_rows(value) and all(
        _text(row.get("src"))
        and _text(row.get("dst"))
        and row.get("kind") == kind
        for row in value
    )


def _valid_loss_rows(value: Any) -> bool:
    return _bounded_dict_rows(value) and all(
        _text(row.get("src"))
        and _text(row.get("dst"))
        and row.get("kind") in {"blocked", "path_lost"}
        for row in value
    )


def _valid_stp_rows(value: Any) -> bool:
    if not _bounded_dict_rows(value):
        return False
    for row in value:
        indeterminate = row.get("indeterminate")
        new_root = row.get("new_root")
        if type(indeterminate) is not bool \
                or row.get("election_candidate_only") is not True \
                or row.get("continuity_assessed") is not False \
                or not isinstance(row.get("reason"), str) \
                or (indeterminate and new_root is not None) \
                or (not indeterminate and not _text(new_root)):
            return False
    return True


def _valid_fhrp_rows(value: Any, *, split_brain: bool) -> bool:
    if not _bounded_dict_rows(value):
        return False
    for row in value:
        if type(row.get("indeterminate")) is not bool \
                or type(row.get("split_brain_risk")) is not bool \
                or row.get("election_candidate_only") is not True \
                or row.get("continuity_assessed") is not False \
                or not isinstance(row.get("reason"), str):
            return False
        if split_brain:
            if row.get("split_brain_risk") is not True:
                return False
        elif row.get("indeterminate") is not False or not _text(row.get("new_active")):
            return False
    return True


def _valid_l2_continuity(value: Any, *, stp_candidates: int, fhrp_candidates: int) -> bool:
    if not _exact_fields(value, _L2_CONTINUITY_FIELDS):
        return False
    applicable = value.get("applicable")
    assessed = value.get("assessed")
    verdict = value.get("verdict")
    projections = _count(value.get("election_projection_count"))
    affected = _count(value.get("affected_member_count"))
    hosts = value.get("affected_member_hosts")
    if type(applicable) is not bool \
            or projections is None or projections < stp_candidates + fhrp_candidates \
            or affected is None \
            or not _bounded_text_rows(hosts) \
            or hosts != sorted(set(hosts)) \
            or affected != len(hosts) \
            or not _text(value.get("reason")):
        return False
    if applicable:
        return assessed is False and verdict == "INDETERMINATE"
    return (
        assessed is None
        and verdict == "not_applicable"
        and projections == 0
        and affected == 0
    )


def _valid_cutover_step(value: Any, index: int, snapshot: Mapping[str, Any]) -> bool:
    if not _exact_fields(value, _CUTOVER_STEP_FIELDS) \
            or type(value.get("step_index")) is not int \
            or value.get("step_index") != index \
            or value.get("action") not in _TRAFFIC_FAILURE_PARAMS \
            or _count(value.get("ignored_field_count")) != 0 \
            or value.get("valid") is not True \
            or value.get("validation_errors") != [] \
            or value.get("is_noop") is not False \
            or not _text(value.get("narrative")):
        return False

    params = value.get("params")
    action = value["action"]
    if type(params) is not dict \
            or frozenset(params) != _TRAFFIC_FAILURE_PARAMS[action] \
            or any(not _text(item) for item in params.values()):
        return False
    try:
        _mutated, canonical_mutation = cutover_sim.apply_cutover_step(
            dict(snapshot), {"action": action, **params},
        )
    except (Exception, MemoryError):
        return False
    if canonical_mutation != {
        "action": action,
        "params": params,
        "valid": True,
        "validation_errors": [],
        "is_noop": False,
        "removed_hosts": value.get("removed_hosts"),
        "ignored_field_count": 0,
    }:
        return False
    removed = value.get("removed_hosts")
    if not _bounded_text_rows(removed) or removed != sorted(set(removed)):
        return False
    if not _valid_loss_rows(value.get("newly_lost_flows")) \
            or not _valid_flow_rows(value.get("recovered_flows"), "recovered") \
            or not _valid_stp_rows(value.get("stp_reroots")) \
            or not _valid_fhrp_rows(value.get("fhrp_takeovers"), split_brain=False) \
            or not _valid_fhrp_rows(value.get("split_brain_risks"), split_brain=True):
        return False

    stp_candidates = _count(value.get("n_stp_election_candidates"))
    fhrp_candidates = _count(value.get("n_fhrp_election_candidates"))
    indeterminate = _count(value.get("indeterminate"))
    stp_rows = value["stp_reroots"]
    fhrp_rows = value["fhrp_takeovers"]
    split_rows = value["split_brain_risks"]
    if not _valid_l2_continuity(
            value.get("l2_continuity"),
            stp_candidates=stp_candidates or 0,
            fhrp_candidates=fhrp_candidates or 0,
    ):
        return False
    continuity = value["l2_continuity"]
    # Every valid current-v1 node/site/link mutation has an unresolved L2-continuity denominator.
    # A stored receipt that labels one not-applicable is not a producer result and cannot claim survival.
    if continuity["applicable"] is not True:
        return False
    expected_stp = sum(
        row["indeterminate"] is False and bool(_text(row.get("new_root"))) for row in stp_rows
    )
    visible_indeterminate = (
        sum(row["indeterminate"] is True for row in stp_rows)
        + sum(row["indeterminate"] is True for row in split_rows)
        + (1 if continuity["applicable"] is True else 0)
    )
    return (
        stp_candidates == expected_stp
        and fhrp_candidates == len(fhrp_rows)
        and indeterminate is not None
        and indeterminate >= visible_indeterminate
    )


def _validated_cutover_simulation(
        value: Any, snapshot: Mapping[str, Any]) -> dict | None:
    top_fields = frozenset({"schema", "valid", "validation_errors", "steps", "worst_step", "summary"})
    if not _exact_fields(value, top_fields) \
            or value.get("schema") != "cutover_sim/1" \
            or value.get("valid") is not True \
            or value.get("validation_errors") != []:
        return None
    steps = value.get("steps")
    summary = value.get("summary")
    if not isinstance(steps, list) or len(steps) != 1 \
            or not _exact_fields(summary, _CUTOVER_SUMMARY_FIELDS) \
            or not all(
                _valid_cutover_step(step, index, snapshot) for index, step in enumerate(steps)
            ):
        return None
    if any(_count(summary.get(field)) is None for field in _CUTOVER_SUMMARY_FIELDS):
        return None

    expected = {
        "n_steps": len(steps),
        "total_newly_lost": sum(len(step["newly_lost_flows"]) for step in steps),
        "total_recovered": sum(len(step["recovered_flows"]) for step in steps),
        "total_stp_reroots": 0,
        "total_fhrp_takeovers": 0,
        "total_stp_election_candidates": sum(
            step["n_stp_election_candidates"] for step in steps
        ),
        "total_fhrp_election_candidates": sum(
            step["n_fhrp_election_candidates"] for step in steps
        ),
        "total_split_brain_risks": sum(len(step["split_brain_risks"]) for step in steps),
        "total_indeterminate": sum(step["indeterminate"] for step in steps),
        "n_noop_steps": 0,
        "n_invalid_steps": 0,
        "n_input_errors": 0,
    }
    worst_step = next((
        step["step_index"] for step in steps if len(step["newly_lost_flows"]) == max(
            len(item["newly_lost_flows"]) for item in steps
        )
    ), None) if expected["total_newly_lost"] else None
    if summary != expected \
            or (worst_step is None and value.get("worst_step") is not None) \
            or (worst_step is not None and (
                type(value.get("worst_step")) is not int or value.get("worst_step") != worst_step
            )):
        return None
    return {"steps": steps, "summary": summary}


def _validated_failure_receipt(
        value: Any, snapshot: Mapping[str, Any]) -> dict | None:
    fields = frozenset({
        "requested", "action", "mutation", "cutover_evidence", "verdict", "status",
        "baseline_verdict", "post_verdict", "post_dimensions", "cutover_gate",
    })
    mutation_fields = frozenset({
        "action", "params", "valid", "validation_errors", "is_noop", "removed_hosts",
        "ignored_field_count",
    })
    if not _exact_fields(value, fields) or value.get("requested") is not True:
        return None
    simulation = _validated_cutover_simulation(value.get("cutover_evidence"), snapshot)
    mutation = value.get("mutation")
    if simulation is None or not _exact_fields(mutation, mutation_fields):
        return None
    step = simulation["steps"][0]
    if mutation != {
        "action": step["action"],
        "params": step["params"],
        "valid": step["valid"],
        "validation_errors": step["validation_errors"],
        "is_noop": step["is_noop"],
        "removed_hosts": step["removed_hosts"],
        "ignored_field_count": step["ignored_field_count"],
    } or value.get("action") != step["action"]:
        return None

    summary = simulation["summary"]
    gaps = [{
        "step_index": row["step_index"],
        "election_projection_count": row["l2_continuity"]["election_projection_count"],
        "reason": row["l2_continuity"]["reason"],
    } for row in simulation["steps"] if row["l2_continuity"]["applicable"] is True]
    expected_gate = {
        "verdict": "proven" if not summary["total_indeterminate"]
        and not summary["total_split_brain_risks"] and not gaps else "indeterminate",
        "n_indeterminate": summary["total_indeterminate"],
        "n_split_brain_risks": summary["total_split_brain_risks"],
        "continuity_assessed": not gaps,
        "continuity_gaps": gaps,
    }
    if value.get("cutover_gate") != expected_gate:
        return None

    verdicts = {"proven", "refuted", "not_observed", "indeterminate"}
    baseline = value.get("baseline_verdict")
    post = value.get("post_verdict")
    if baseline not in verdicts or post not in verdicts or not isinstance(value.get("post_dimensions"), dict):
        return None
    status = (
        "baseline_not_proven" if baseline != "proven" else
        "l2_failover_not_proven" if expected_gate["verdict"] != "proven" else
        "preserved" if post == "proven" else
        "failed" if post == "refuted" else
        "coverage_lost"
    )
    failure_verdict = (
        "proven" if status == "preserved" else
        "refuted" if status == "failed" else
        "indeterminate"
    )
    if value.get("status") != status or value.get("verdict") != failure_verdict \
            or (status == "preserved" and summary["total_newly_lost"] != 0):
        return None
    return summary


def _valid_traffic_intent(value: Any) -> bool:
    if not _exact_fields(value, _TRAFFIC_INTENT_FIELDS) \
            or not all(_text(value.get(field)) for field in ("id", "src", "dst")) \
            or not isinstance(value.get("title"), str) \
            or value.get("protocol") not in {"tcp", "udp"} \
            or value.get("expected") not in {"permit", "deny"} \
            or type(value.get("return_required")) is not bool \
            or value.get("vrf") is not None:
        return False
    for field in ("src_port", "dst_port"):
        port = _count(value.get(field))
        if port is None or port > 65_535:
            return False
    required_mtu = value.get("required_mtu")
    if required_mtu is not None and (_count(required_mtu) in {None, 0}):
        return False
    return not (
        value["expected"] == "deny"
        and (value["return_required"] is True or required_mtu is not None)
    )


def _valid_path_dimension_row(value: Any, fields: frozenset[str]) -> bool:
    if type(value) is not dict or not fields.issubset(value):
        return False
    if value.get("scope") != "selected_rib_forwarding_projection" \
            or value.get("endpoint_attachment") != "not_assessed" \
            or value.get("l2_delivery") != "not_assessed" \
            or type(value.get("overlay_tunnel_forwarding")) is not bool \
            or value.get("tunnel_underlay") != (
                "not_assessed" if value["overlay_tunnel_forwarding"] else "not_applicable"
            ) \
            or type(value.get("reached")) is not bool \
            or value.get("drop_evidence") not in {"", "observed_discard", "no_route_observed"} \
            or not _bounded_dict_rows(value.get("ecmp_dropping_legs")) \
            or not _bounded_dict_rows(value.get("ambiguous_candidate_sets")) \
            or not _bounded_dict_rows(value.get("hops")):
        return False

    status = _text(value.get("status"))
    reached = value["reached"]
    drop = value["drop_evidence"]
    if status == "computed:reached" and reached and not drop:
        projected_verdict, state = "proven", "reached"
    elif status == "computed:unreachable" and not reached and drop == "observed_discard":
        projected_verdict, state = "refuted", "observed_drop"
    elif status == "computed:unreachable" and not reached and drop in {"", "no_route_observed"}:
        projected_verdict, state = "not_observed", "no_route_in_scoped_projection"
    elif status.startswith("lower_bound:") and not reached and not drop:
        projected_verdict, state = "not_observed", "unresolved"
    else:
        return False
    if value.get("state") != state:
        return False
    if value.get("verdict") == projected_verdict:
        return True
    # The producer may weaken positive selected-RIB evidence when its route/interface denominator
    # is incomplete.  Preserve that canonical abstention, but never allow the inverse promotion.
    return (
        value.get("verdict") == "indeterminate"
        and value.get("selected_projection_verdict") == projected_verdict
        and bool(_text(value.get("reason")))
    )


def _canonical_subject_roster(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not value \
            or any(not _text(item) for item in value) \
            or value != sorted(set(value)):
        return None
    return value


def _proven_interface_custody(value: Any, path_hosts: list[str]) -> bool:
    return (
        type(value) is dict
        and frozenset(value) == frozenset({"verdict", "hosts_checked", "gaps", "basis"})
        and value.get("verdict") == "proven"
        and _canonical_subject_roster(value.get("hosts_checked")) == path_hosts
        and value.get("gaps") == []
        and value.get("basis") == _INTERFACE_CUSTODY_BASIS
    )


def _proven_route_custody(
        value: Any, *, destination: str, source_host: str) -> bool:
    if type(value) is not dict or frozenset(value) != frozenset({
            "verdict", "hosts_checked", "destination", "gaps", "basis"}):
        return False
    hosts = _canonical_subject_roster(value.get("hosts_checked"))
    return (
        value.get("verdict") == "proven"
        and hosts is not None
        and source_host in hosts
        and value.get("destination") == destination
        and value.get("gaps") == []
        and value.get("basis") == _ROUTE_CUSTODY_BASIS
    )


def _favorable_policy_stage(value: Any) -> bool:
    fields = frozenset({
        "host", "interface", "direction", "role", "acl", "verdict", "native_result",
        "matched_by", "detail", "basis",
    })
    if not _exact_fields(value, fields) or value.get("verdict") != "proven" \
            or not _text(value.get("host")) or not _text(value.get("interface")):
        return False
    direction = value.get("direction")
    allowed_roles = {
        "in": {"source_ingress", "transit_ingress"},
        "out": {"transit_egress", "destination_egress"},
    }
    if direction not in allowed_roles or value.get("role") not in allowed_roles[direction]:
        return False
    acl = _text(value.get("acl"))
    if acl:
        return (
            value.get("native_result") == "WITNESS"
            and bool(_text(value.get("matched_by")))
            and value.get("detail")
            == "the exact tuple is permitted by first-match ACL evaluation"
            and value.get("basis") == f"acls.{value['host']}.{acl}"
        )
    return (
        value.get("acl") is None
        and value.get("native_result") == "NO_ACL_ATTACHED"
        and value.get("matched_by") == "collected interface attachment"
        and value.get("detail") == "no stateless ACL is attached in this direction"
        and value.get("basis")
        == f"interfaces.{value['host']}.{value['interface']}.acl_{direction}"
    )


def _valid_policy_stage(value: Any) -> bool:
    fields = frozenset({
        "host", "interface", "direction", "role", "acl", "verdict", "native_result",
        "matched_by", "detail", "basis",
    })
    if type(value) is not dict or not fields.issubset(value) \
            or value.get("verdict") not in {
                "proven", "refuted", "not_observed", "indeterminate",
            }:
        return False
    if value.get("verdict") == "proven":
        return _favorable_policy_stage(value)
    if value.get("verdict") == "refuted":
        acl = _text(value.get("acl"))
        return (
            frozenset(value) == fields
            and bool(_text(value.get("host")))
            and bool(_text(value.get("interface")))
            and bool(acl)
            and value.get("native_result") == "PROVEN_NONE"
            and value.get("detail") == "the exact tuple is denied (the implicit deny is included)"
            and value.get("basis") == f"acls.{value['host']}.{acl}"
        )
    expected_native = "INDETERMINATE" if value.get("verdict") == "indeterminate" \
        else "NOT_OBSERVED"
    return value.get("native_result") == expected_native and isinstance(value.get("detail"), str)


def _valid_policy_dimension_row(value: Any, direction: str) -> bool:
    if not isinstance(value, dict) or value.get("direction") != direction \
            or type(value.get("requested")) is not bool \
            or not _bounded_dict_rows(value.get("stages")) \
            or not all(_valid_policy_stage(stage) for stage in value["stages"]) \
            or not isinstance(value.get("reason"), str):
        return False
    summary = value.get("summary")
    if summary is None:
        return not value["stages"]
    if type(summary) is not dict or frozenset(summary) != frozenset({
            "n_stages", "n_attached", "n_denied", "n_unresolved",
    }):
        return False
    return summary == {
        "n_stages": len(value["stages"]),
        "n_attached": sum(bool(row.get("acl")) for row in value["stages"]),
        "n_denied": sum(row.get("verdict") == "refuted" for row in value["stages"]),
        "n_unresolved": sum(
            row.get("verdict") in {"not_observed", "indeterminate"}
            for row in value["stages"]
        ),
    }


def _valid_custody_receipt(value: Any, *, route: bool) -> bool:
    fields = {"verdict", "hosts_checked", "gaps", "basis"}
    if route:
        fields.add("destination")
    if type(value) is not dict or set(value) != fields \
            or value.get("verdict") not in {"proven", "not_observed"} \
            or not isinstance(value.get("hosts_checked"), list) \
            or any(not _text(host) for host in value["hosts_checked"]) \
            or value["hosts_checked"] != sorted(set(value["hosts_checked"])) \
            or not _bounded_dict_rows(value.get("gaps")):
        return False
    if value.get("basis") != (_ROUTE_CUSTODY_BASIS if route else _INTERFACE_CUSTODY_BASIS):
        return False
    if route and not _text(value.get("destination")):
        return False
    if value.get("verdict") == "proven":
        return bool(value["hosts_checked"]) and value["gaps"] == []
    return True


def _favorable_policy_row(value: Any, direction: str) -> bool:
    if not isinstance(value, dict) or value.get("direction") != direction \
            or value.get("requested") is not True or value.get("verdict") != "proven" \
            or value.get("reason") != "" or not _bounded_dict_rows(value.get("stages")) \
            or not value["stages"]:
        return False
    stages = value["stages"]
    summary = value.get("summary")
    return (
        all(_favorable_policy_stage(row) for row in stages)
        and type(summary) is dict
        and frozenset(summary) == frozenset({
            "n_stages", "n_attached", "n_denied", "n_unresolved",
        })
        and summary == {
            "n_stages": len(stages),
            "n_attached": sum(bool(row.get("acl")) for row in stages),
            "n_denied": 0,
            "n_unresolved": 0,
        }
    )


def _favorable_mtu_row(
        value: Any, required_mtu: Any, path_hosts: list[str]) -> bool:
    if not isinstance(value, dict) or value.get("required_mtu") != required_mtu \
            or not _proven_interface_custody(value.get("interface_custody"), path_hosts) \
            or any(value.get(field) != [] for field in (
                "unobserved_hops", "below_required_hops", "provenance_gaps",
            )):
        return False
    if required_mtu is None:
        return value.get("verdict") == "not_requested"
    observed_min = _count(value.get("observed_min"))
    native = _text(value.get("native_verdict"))
    return (
        value.get("verdict") == "proven"
        and observed_min is not None
        and observed_min >= required_mtu
        and not native.startswith(("below_required", "INDETERMINATE"))
    )


def _favorable_ecmp_row(
        value: Any, *, destination: str, source_host: str) -> bool:
    empty_evidence_fields = (
        "mtu_divergence", "acl_divergence", "forwarding_divergence", "unobserved_legs",
        "mtu_unobserved_legs", "forwarding_unresolved_legs", "unassessed_branch_points",
        "selected_rib_observed_dropping_legs", "observed_dropping_legs",
        "dropping_leg_gate_gaps", "reached_leg_gate_gaps", "scoped_absence_legs",
        "selected_rib_mtu_below_required_legs", "mtu_below_required_legs",
        "mtu_provenance_gaps", "mtu_leg_gate_gaps", "acl_provenance_gaps",
    )
    units = _count(value.get("leg_count")) if isinstance(value, dict) else None
    return (
        isinstance(value, dict)
        and value.get("verdict") == "proven"
        and value.get("native_verdict") in {"consistent", "not_ecmp"}
        and value.get("scope")
        == "source-owner ECMP consistency plus selected-path branch-point census"
        and units is not None and units > 0
        and value.get("branch_complete") is True
        and value.get("host") == source_host
        and value.get("dst") == destination
        and _proven_route_custody(
            value.get("route_custody"), destination=destination, source_host=source_host,
        )
        and all(value.get(field) == [] for field in empty_evidence_fields)
    )


def _favorable_traffic_dimensions(intent: Mapping[str, Any], value: Mapping[str, Any]) -> bool:
    directions = ["forward"] + (["reverse"] if intent.get("return_required") is True else [])
    required_mtu = intent.get("required_mtu")
    for direction in directions:
        path = _dict(_dict(value.get("path")).get(direction))
        hops = path.get("hops")
        if not _bounded_dict_rows(hops) or not hops \
                or any(not _text(hop.get("host")) for hop in hops):
            return False
        path_hosts = sorted({_text(hop.get("host")) for hop in hops})
        destination = _text(intent.get("dst" if direction == "forward" else "src"))
        source_host = _text(hops[0].get("host"))
        if path.get("verdict") != "proven" \
                or path.get("state") != "reached" \
                or path.get("status") != "computed:reached" \
                or path.get("reached") is not True \
                or path.get("drop_evidence") != "" \
                or path.get("ecmp_dropping_legs") != [] \
                or path.get("ambiguous_candidate_sets") != [] \
                or not _favorable_policy_row(_dict(value.get("policy")).get(direction), direction) \
                or not _favorable_mtu_row(
                    _dict(value.get("mtu")).get(direction), required_mtu, path_hosts,
                ) \
                or not _favorable_ecmp_row(
                    _dict(value.get("ecmp")).get(direction),
                    destination=destination,
                    source_host=source_host,
                ):
            return False
    return True


def _removed_hosts_absent_from_post_dimensions(
        intent: Mapping[str, Any], failure: Mapping[str, Any]) -> bool:
    removed = {
        _text(host).casefold() for host in _list(_dict(failure.get("mutation")).get("removed_hosts"))
        if _text(host)
    }
    if not removed:
        return True
    dimensions = _dict(failure.get("post_dimensions"))
    directions = ["forward"] + (["reverse"] if intent.get("return_required") is True else [])
    subjects = set()
    for direction in directions:
        path = _dict(_dict(dimensions.get("path")).get(direction))
        subjects.update(
            _text(hop.get("host")).casefold() for hop in _list(path.get("hops"))
            if isinstance(hop, dict) and _text(hop.get("host"))
        )
        mtu = _dict(_dict(dimensions.get("mtu")).get(direction))
        subjects.update(
            _text(host).casefold()
            for host in _list(_dict(mtu.get("interface_custody")).get("hosts_checked"))
            if _text(host)
        )
        ecmp = _dict(_dict(dimensions.get("ecmp")).get(direction))
        if _text(ecmp.get("host")):
            subjects.add(_text(ecmp.get("host")).casefold())
        subjects.update(
            _text(host).casefold()
            for host in _list(_dict(ecmp.get("route_custody")).get("hosts_checked"))
            if _text(host)
        )
    return removed.isdisjoint(subjects)


def _valid_traffic_dimensions(value: Any) -> bool:
    if type(value) is not dict or frozenset(value) != frozenset({"path", "policy", "mtu", "ecmp"}):
        return False
    required = {
        "path": frozenset({
            "verdict", "state", "scope", "endpoint_attachment", "l2_delivery",
            "overlay_tunnel_forwarding", "tunnel_underlay", "status", "reached", "drop_evidence",
            "ecmp_dropping_legs", "ambiguous_candidate_sets", "hops",
        }),
        "policy": frozenset({"direction", "requested", "verdict", "stages", "reason"}),
        "mtu": frozenset({
            "verdict", "native_verdict", "required_mtu", "observed_min", "bottleneck_hop",
            "unobserved_hops", "below_required_hops", "provenance_gaps", "interface_custody",
        }),
        "ecmp": frozenset({
            "host", "dst", "leg_count", "verdict", "native_verdict", "scope", "route_custody",
            "branch_complete", "unassessed_branch_points", "observed_dropping_legs",
            "mtu_below_required_legs", "mtu_provenance_gaps",
        }),
    }
    verdicts = {
        "path": {"proven", "refuted", "not_observed", "indeterminate"},
        "policy": {"proven", "refuted", "not_observed", "indeterminate", "not_requested"},
        "mtu": {"proven", "refuted", "not_observed", "indeterminate", "not_requested"},
        "ecmp": {"proven", "refuted", "not_observed", "indeterminate"},
    }
    for axis, fields in required.items():
        dimension = value.get(axis)
        if not isinstance(dimension, dict):
            return False
        for direction in ("forward", "reverse"):
            row = dimension.get(direction)
            if type(row) is not dict or not fields.issubset(row) \
                    or row.get("verdict") not in verdicts[axis]:
                return False
            if axis == "path" and not _valid_path_dimension_row(row, fields):
                return False
            if axis == "policy" and (
                    not _valid_policy_dimension_row(row, direction)):
                return False
            if axis == "mtu" and not _valid_custody_receipt(
                    row.get("interface_custody"), route=False):
                return False
            if axis == "ecmp" and (
                    _count(row.get("leg_count")) is None
                    or type(row.get("branch_complete")) is not bool
                    or not _valid_custody_receipt(row.get("route_custody"), route=True)):
                return False
    path = value["path"]
    return (
        path.get("rpf_verdict") in {"PROVEN", "REFUTED", "NOT_OBSERVED", "INDETERMINATE"}
        and type(path.get("symmetric")) is bool
        and isinstance(path.get("asymmetry"), list)
    )


def _traffic_dimension_custody_reconciles(
        intent: Mapping[str, Any], value: Mapping[str, Any]) -> bool:
    for direction, destination in (
            ("forward", _text(intent.get("dst"))),
            ("reverse", _text(intent.get("src")))):
        path = _dict(_dict(value.get("path")).get(direction))
        path_hosts = sorted({
            _text(hop.get("host")) for hop in _list(path.get("hops"))
            if isinstance(hop, dict) and _text(hop.get("host"))
        })
        mtu_custody = _dict(_dict(_dict(value.get("mtu")).get(direction)).get(
            "interface_custody"
        ))
        if mtu_custody.get("hosts_checked") != path_hosts:
            return False
        ecmp = _dict(_dict(value.get("ecmp")).get(direction))
        route_custody = _dict(ecmp.get("route_custody"))
        if route_custody.get("destination") != destination:
            return False
        source_host = _text(ecmp.get("host"))
        if source_host and (
                not path_hosts or source_host != _text(_list(path.get("hops"))[0].get("host"))
                or source_host not in route_custody.get("hosts_checked", [])):
            return False
        if not source_host and path_hosts:
            return False
    return True


def _valid_traffic_claims(
        value: Any, *, intent: Mapping[str, Any], dimensions: Mapping[str, Any],
        row_verdict: str, failure: Mapping[str, Any]) -> bool:
    if not isinstance(value, list) or len(value) != 4 or not all(type(row) is dict for row in value):
        return False
    intent_id = _text(intent.get("id"))
    by_predicate = {row.get("predicate"): row for row in value}
    predicates = {
        "selected_rib_forwarding_projection",
        "stateless_acl_assurance",
        "declared_scope_assurance",
        "requested_failure_assurance",
    }
    if frozenset(by_predicate) != predicates:
        return False
    common = {
        "selected_rib_forwarding_projection": (f"{intent_id}.path", "fib.trace_bidirectional"),
        "stateless_acl_assurance": (f"{intent_id}.policy", "aclcheck.search_filters"),
        "declared_scope_assurance": (f"{intent_id}.overall", TRAFFIC_ASSURANCE_OWNER),
        "requested_failure_assurance": (
            f"{intent_id}.failure", "cisco_toolkit.cutover_sim.apply_cutover_step",
        ),
    }
    verdicts = {"proven", "refuted", "not_observed", "indeterminate"}
    for predicate, row in by_predicate.items():
        expected_id, expected_basis = common[predicate]
        if row.get("id") != expected_id or row.get("subject") != intent_id \
                or row.get("basis") != expected_basis or row.get("verdict") not in verdicts:
            return False
    overall = by_predicate["declared_scope_assurance"]
    failure_claim = by_predicate["requested_failure_assurance"]
    if overall.get("verdict") != row_verdict \
            or failure_claim.get("verdict") != failure.get("verdict") \
            or failure_claim.get("applicability") != "applicable":
        return False
    path = dimensions["path"]
    policy = dimensions["policy"]
    ecmp = dimensions["ecmp"]
    selected_path, directions = traffic_assurance._required_verdict(dict(intent), path)
    observed_ecmp, _ = traffic_assurance._required_verdict(dict(intent), ecmp)
    observed_path = traffic_assurance._conjunctive_verdict(selected_path, observed_ecmp)
    observed_policy, _ = traffic_assurance._required_verdict(dict(intent), policy)
    if intent.get("expected") == "deny":
        baseline_path_claim = (
            "proven" if selected_path == "refuted" and observed_ecmp == "proven"
            else "indeterminate"
        )
    else:
        baseline_path_claim = observed_path
    baseline_policy_claim = traffic_assurance._requested_claim_verdict(
        str(intent.get("expected")), observed_policy, "policy",
    )
    applicability = "applicable" if failure.get("verdict") == "proven" \
        else "requested_failure_not_proven"
    effective_path = baseline_path_claim if failure.get("verdict") == "proven" else "indeterminate"
    effective_policy = baseline_policy_claim if failure.get("verdict") == "proven" else "indeterminate"
    path_claim = by_predicate["selected_rib_forwarding_projection"]
    policy_claim = by_predicate["stateless_acl_assurance"]
    projection_boundaries = {}
    for direction in directions:
        hops = [row for row in _list(_dict(path.get(direction)).get("hops"))
                if isinstance(row, dict)]
        projection_boundaries[direction] = {
            "first_collected_l3_owner": _text(hops[0].get("host")) or None if hops else None,
            "last_collected_l3_owner": _text(hops[-1].get("host")) or None if hops else None,
            "endpoint_attachment": "not_assessed",
            "l2_delivery": "not_assessed",
        }
    if path_claim.get("scenario_scope") != "baseline_plus_requested_failure" \
            or path_claim.get("baseline_verdict") != baseline_path_claim \
            or path_claim.get("verdict") != effective_path \
            or path_claim.get("observed_verdict") != observed_path \
            or path_claim.get("selected_path_observed_verdict") != selected_path \
            or path_claim.get("ecmp_observed_verdict") != observed_ecmp \
            or path_claim.get("directions") != directions \
            or path_claim.get("applicability") != applicability \
            or path_claim.get("endpoint_delivery_assessed") is not False \
            or path_claim.get("projection_boundaries") != projection_boundaries:
        return False
    if policy_claim.get("scenario_scope") != "baseline_plus_requested_failure" \
            or policy_claim.get("baseline_verdict") != baseline_policy_claim \
            or policy_claim.get("verdict") != effective_policy \
            or policy_claim.get("observed_verdict") != observed_policy \
            or policy_claim.get("directions") != directions \
            or policy_claim.get("applicability") != applicability:
        return False
    return True


def _validated_traffic_result(
        value: Any, snapshot: Mapping[str, Any]) -> dict | None:
    if not _exact_fields(value, _TRAFFIC_RESULT_FIELDS) \
            or value.get("schema") != "traffic_assurance/1" \
            or value.get("owner") != TRAFFIC_ASSURANCE_OWNER \
            or value.get("valid") is not True \
            or value.get("validation_errors") != [] \
            or value.get("supported") is not True \
            or value.get("unsupported_semantics") != [] \
            or value.get("custody_trust") != "current_run_verified" \
            or not _valid_traffic_intent(value.get("intent")) \
            or not _bounded_text_rows(value.get("verdict_reasons")) \
            or not _bounded_text_rows(value.get("limitations")) \
            or value.get("sources") != _TRAFFIC_SOURCES:
        return None
    failure = value.get("failure")
    summary = _validated_failure_receipt(failure, snapshot)
    dimensions = value.get("dimensions")
    post_dimensions = failure.get("post_dimensions") if isinstance(failure, dict) else None
    if summary is None \
            or not _valid_traffic_dimensions(dimensions) \
            or not _valid_traffic_dimensions(post_dimensions) \
            or not _traffic_dimension_custody_reconciles(value["intent"], dimensions) \
            or not _traffic_dimension_custody_reconciles(value["intent"], post_dimensions):
        return None
    intent = value["intent"]
    if failure.get("status") == "preserved" \
            and not _removed_hosts_absent_from_post_dimensions(intent, failure):
        return None
    try:
        baseline_verdict, baseline_reasons = traffic_assurance._decision(
            intent, dimensions["path"], dimensions["policy"], dimensions["mtu"], dimensions["ecmp"],
        )
        post_verdict, _post_reasons = traffic_assurance._decision(
            intent,
            post_dimensions["path"],
            post_dimensions["policy"],
            post_dimensions["mtu"],
            post_dimensions["ecmp"],
        )
    except (Exception, MemoryError):
        return None
    if failure.get("baseline_verdict") != baseline_verdict \
            or failure.get("post_verdict") != post_verdict:
        return None
    row_verdict = value.get("verdict")
    expected_verdict = baseline_verdict
    expected_reasons = baseline_reasons
    if baseline_verdict == "proven" and failure["verdict"] == "refuted":
        expected_verdict = "refuted"
        expected_reasons = ["the requested synthetic failure refutes the baseline assurance"]
    elif baseline_verdict == "proven" and failure["verdict"] != "proven":
        expected_verdict = "indeterminate"
        expected_reasons = [
            "the requested synthetic failure is invalid, unmatched, or loses assurance coverage"
        ]
    nrfu_ids = value.get("nrfu_test_ids")
    expected_nrfu_count = 2 if intent["return_required"] else 1
    if row_verdict != expected_verdict \
            or value.get("verdict_reasons") != expected_reasons \
            or not _valid_traffic_claims(
                value.get("claims"), intent=intent, dimensions=dimensions,
                row_verdict=row_verdict, failure=failure,
            ) \
            or not _bounded_text_rows(nrfu_ids) \
            or len(nrfu_ids) != expected_nrfu_count \
            or len(set(nrfu_ids)) != len(nrfu_ids) \
            or not all(row.startswith("NRFU-") for row in nrfu_ids):
        return None
    return {
        **summary,
        "_favorable_evidence_coherent": (
            _favorable_traffic_dimensions(intent, dimensions)
            and _favorable_traffic_dimensions(intent, post_dimensions)
            and (
                intent["return_required"] is False
                or (
                    dimensions["path"].get("symmetric") is True
                    and dimensions["path"].get("asymmetry") == []
                    and post_dimensions["path"].get("symmetric") is True
                    and post_dimensions["path"].get("asymmetry") == []
                )
            )
        ),
    }


def _valid_traffic_set(value: Any) -> bool:
    if not isinstance(value, dict) \
            or value.get("schema") != TRAFFIC_ASSURANCE_SET_SCHEMA \
            or value.get("owner") != TRAFFIC_ASSURANCE_OWNER:
        return False
    results = value.get("results")
    summary = value.get("summary")
    if not isinstance(results, list) or len(results) > _MAX_SCENARIOS \
            or not isinstance(summary, dict) \
            or not all(isinstance(row, dict) for row in results):
        return False
    verdicts = ("proven", "refuted", "not_observed", "indeterminate")
    if any(
        row.get("schema") != "traffic_assurance/1"
        or row.get("owner") != TRAFFIC_ASSURANCE_OWNER
        or row.get("verdict") not in verdicts
        or type(row.get("valid")) is not bool
        or not _bounded_text_rows(row.get("validation_errors"), empty_ok=True)
        or (row.get("valid") is True and row.get("validation_errors") != [])
        for row in results
    ):
        return False
    expected = Counter(row["verdict"] for row in results)
    return (
        _count(summary.get("n")) == len(results)
        and _count(summary.get("invalid")) == sum(row["valid"] is False for row in results)
        and all(_count(summary.get(token)) == expected[token] for token in verdicts)
    )


def _service_path_scenarios(
        snapshot: Mapping[str, Any], source: Mapping[str, Any]) -> List[dict]:
    owner = "traffic_assurance_set/1 -> cutover_sim/1"
    if source.get("source_bound") is not True:
        return [_gap(
            "service_path", owner,
            "The snapshot is not bound to exact source bytes; stored bounded-failure path evidence is not verified.",
        )]
    value = snapshot.get("traffic_assurance")
    if not _valid_traffic_set(value):
        return [_gap(
            "service_path", owner,
            "No valid traffic_assurance_set/1 receipt is present; no competing path simulation was run.",
        )]

    scenarios: List[dict] = []
    for index, result in enumerate(value["results"]):
        row = _dict(result)
        failure = _dict(row.get("failure"))
        if failure.get("requested") is not True:
            continue
        intent = _dict(row.get("intent"))
        intent_id = _text(intent.get("id"))
        summary = _validated_traffic_result(row, snapshot)
        if not intent_id or summary is None:
            scenarios.append(_scenario(
                family="service_path",
                subject=intent_id or f"traffic_intent|{index}",
                failure_scenario=_text(failure.get("action")) or "bounded_failure",
                disposition="not_verified",
                source_owner=owner,
                current_fault=False,
                evidence={},
                note="The stored traffic-assurance failure receipt is malformed; it was not recomputed or trusted.",
            ))
            continue
        status = _text(failure.get("status"))
        disposition = (
            "simulation_only" if status == "preserved"
            and failure.get("verdict") == "proven" and row.get("verdict") == "proven"
            and summary.get("_favorable_evidence_coherent") is True else
            "projected_risk" if status == "failed" and failure.get("verdict") == "refuted" else
            "not_verified"
        )
        scenarios.append(_scenario(
            family="service_path",
            subject=intent_id,
            failure_scenario=_text(failure.get("action")) or "bounded_failure",
            disposition=disposition,
            source_owner=owner,
            current_fault=False,
            evidence={
                "producer_status": status or "not_verified",
                "n_steps": _count(summary.get("n_steps")) or 0,
                "n_newly_lost": _count(summary.get("total_newly_lost")) or 0,
                "n_split_brain_risks": _count(summary.get("total_split_brain_risks")) or 0,
                "n_indeterminate": _count(summary.get("total_indeterminate")) or 0,
            },
            note=(
                "This projects the stored traffic-assurance/cutover-simulation result without rerunning "
                "a path engine. Synthetic preservation is not an operator or field rehearsal."
            ),
        ))
    return scenarios or [_gap(
        "service_path", owner,
        "Traffic assurance contains no requested bounded failure; service/path failure survival is not verified.",
    )]


def compute_l2_failure_rehearsal(snapshot: Any) -> dict:
    """Compose bounded L2 failure evidence without emitting a score or overall verdict."""
    snap = _dict(snapshot)
    source = bound_snapshot_source(snapshot)
    applicability = _gate_family_applicability(snap)
    scenarios = [
        *_stp_scenarios(snap, source),
        *_etherchannel_scenarios(snap, source),
        *_multichassis_scenarios(snap, source),
        *_service_path_scenarios(snap, source),
    ]
    scenarios.sort(key=lambda row: (
        row["family"].casefold(), row["family"], row["subject"].casefold(), row["subject"]
    ))
    counts = Counter(row["disposition"] for row in scenarios)
    by_disposition = {token: int(counts[token]) for token in _DISPOSITIONS}
    status = (
        "current_fault" if by_disposition["current_fault"] else
        "projected_risk" if by_disposition["projected_risk"] else
        "not_verified" if by_disposition["not_verified"] else
        "simulation_only"
    )
    return {
        "schema": L2_FAILURE_REHEARSAL_SCHEMA,
        "owner": "reference_only_composition",
        "owns_score": False,
        "owns_verdict": False,
        "status": status,
        "assurance_level": "not_verified",
        "source_bound": source.get("source_bound") is True,
        "applicability": applicability,
        "summary": {
            "n_scenarios": len(scenarios),
            "n_current_faults": by_disposition["current_fault"],
            "n_projected_risks": by_disposition["projected_risk"],
            "n_not_verified": by_disposition["not_verified"],
            "n_applicable_families": sum(applicability.values()),
            "by_disposition": by_disposition,
        },
        "scenarios": scenarios,
        "limitations": [
            "This receipt owns neither a score nor the overall cutover verdict.",
            "Simulation candidates and observed member/leg counts are not field or operator rehearsal.",
            "No new path engine is implemented; service/path evidence is projected only from traffic_assurance_set/1.",
            "Unsupported or malformed evidence remains explicit not_verified.",
        ],
    }


def validate_l2_failure_rehearsal(value: Any) -> dict:
    """Validate the closed, source-bound local rehearsal receipt for gate use.

    The returned ``gate_status`` is derived only from applicable STP,
    EtherChannel, and multichassis scenarios. Service-path rows and placeholder
    gaps for absent families remain disclosure evidence and never become a
    service-survival or runtime-support claim.
    """
    invalid = {
        "valid": False,
        "reason": "l2_failure_rehearsal is missing or malformed",
        "gate_status": "not_verified",
        "applicable_families": [],
        "n_current_faults": 0,
        "n_projected_risks": 0,
        "n_not_verified": 0,
    }
    if not isinstance(value, dict) or frozenset(value) != _ROOT_FIELDS:
        return invalid
    if (value.get("schema") != L2_FAILURE_REHEARSAL_SCHEMA
            or value.get("owner") != "reference_only_composition"
            or value.get("owns_score") is not False
            or value.get("owns_verdict") is not False
            or value.get("assurance_level") != "not_verified"
            or value.get("source_bound") is not True):
        return invalid

    applicability = value.get("applicability")
    if (not isinstance(applicability, dict)
            or frozenset(applicability) != frozenset(_GATE_FAMILIES)
            or any(type(applicability.get(family)) is not bool
                   for family in _GATE_FAMILIES)):
        return invalid
    applicable = [family for family in _GATE_FAMILIES if applicability[family]]

    scenarios = value.get("scenarios")
    if (not isinstance(scenarios, list) or len(scenarios) > _MAX_SCENARIOS
            or any(not isinstance(row, dict) for row in scenarios)):
        return invalid
    previous_key = None
    counts = Counter()
    by_family = {family: [] for family in _GATE_FAMILIES}
    for row in scenarios:
        disposition = row.get("disposition")
        family = row.get("family")
        subject = row.get("subject")
        if (frozenset(row) != _SCENARIO_FIELDS
                or family not in _SCENARIO_FAMILIES
                or disposition not in _DISPOSITIONS
                or row.get("assurance_level") != "not_verified"
                or type(row.get("current_fault")) is not bool
                or row.get("current_fault") is not (disposition == "current_fault")
                or not _text(subject)
                or not _text(row.get("failure_scenario"))
                or not _text(row.get("source_owner"))
                or not isinstance(row.get("evidence"), dict)
                or not _text(row.get("note"))):
            return invalid
        key = (family.casefold(), family, subject.casefold(), subject)
        if previous_key is not None and key < previous_key:
            return invalid
        previous_key = key
        counts[disposition] += 1
        if family in by_family:
            by_family[family].append(row)

    summary = value.get("summary")
    by_disposition = summary.get("by_disposition") if isinstance(summary, dict) else None
    expected_by_disposition = {
        disposition: int(counts[disposition]) for disposition in _DISPOSITIONS
    }
    summary_counts = {
        field: _count(summary.get(field))
        for field in (
            "n_scenarios",
            "n_current_faults",
            "n_projected_risks",
            "n_not_verified",
            "n_applicable_families",
        )
    } if isinstance(summary, dict) else {}
    supplied_by_disposition = {
        disposition: _count(by_disposition.get(disposition))
        for disposition in _DISPOSITIONS
    } if isinstance(by_disposition, dict) else {}
    if (not isinstance(summary, dict) or frozenset(summary) != _SUMMARY_FIELDS
            or not isinstance(by_disposition, dict)
            or frozenset(by_disposition) != frozenset(_DISPOSITIONS)
            or any(value is None for value in summary_counts.values())
            or any(value is None for value in supplied_by_disposition.values())
            or supplied_by_disposition != expected_by_disposition
            or summary_counts.get("n_scenarios") != len(scenarios)
            or summary_counts.get("n_current_faults") != counts["current_fault"]
            or summary_counts.get("n_projected_risks") != counts["projected_risk"]
            or summary_counts.get("n_not_verified") != counts["not_verified"]
            or summary_counts.get("n_applicable_families") != len(applicable)):
        return invalid
    expected_status = (
        "current_fault" if counts["current_fault"] else
        "projected_risk" if counts["projected_risk"] else
        "not_verified" if counts["not_verified"] else
        "simulation_only"
    )
    limitations = value.get("limitations")
    if (value.get("status") != expected_status
            or not isinstance(limitations, list) or not limitations
            or any(not _text(row) for row in limitations)):
        return invalid

    applicable_rows = [row for family in applicable for row in by_family[family]]
    if any(not by_family[family] for family in applicable):
        gate_status = "not_verified"
        missing = len([family for family in applicable if not by_family[family]])
    else:
        missing = 0
        gate_counts = Counter(row["disposition"] for row in applicable_rows)
        gate_status = (
            "current_fault" if gate_counts["current_fault"] else
            "not_verified" if gate_counts["not_verified"] else
            "projected_risk" if gate_counts["projected_risk"] else
            "simulation_only" if applicable else
            "not_applicable"
        )
    gate_counts = Counter(row["disposition"] for row in applicable_rows)
    return {
        "valid": True,
        "reason": "ok",
        "gate_status": gate_status,
        "applicable_families": applicable,
        "n_current_faults": int(gate_counts["current_fault"]),
        "n_projected_risks": int(gate_counts["projected_risk"]),
        "n_not_verified": int(gate_counts["not_verified"] + missing),
    }


__all__ = [
    "L2_FAILURE_REHEARSAL_SCHEMA",
    "compute_l2_failure_rehearsal",
    "validate_l2_failure_rehearsal",
]
