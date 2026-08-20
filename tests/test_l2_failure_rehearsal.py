"""Bounded L2 rehearsal composition over the existing simulation/delta owners."""

from __future__ import annotations

import copy
import dataclasses
import json

from cisco_toolkit import traffic_assurance
from cisco_toolkit.analyze import summarize_etherchannel_baseline
from cisco_toolkit.l2_rehearsal import (
    L2_FAILURE_REHEARSAL_SCHEMA,
    compute_l2_failure_rehearsal,
)
from cisco_toolkit.multichassis_lag import compute_multichassis_lag_domain_baseline
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    cutover_operator_evidence,
)
from tests.test_etherchannel_cutover_truth import _project, _receipt
from tests.test_multichassis_lag import _nxos_pair
from tests.test_stp_consistency_truth import _stp_run
from tests.test_traffic_assurance import _intent, _symmetric_snapshot


def _bind(value: dict):
    raw = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")
    return bind_snapshot_json_bytes(raw)


def _family(value: dict, name: str) -> list[dict]:
    return [row for row in value["scenarios"] if row["family"] == name]


def _assert_no_decision_owner(value) -> None:
    if isinstance(value, dict):
        assert "score" not in value
        assert "verdict" not in value
        for child in value.values():
            _assert_no_decision_owner(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_decision_owner(child)


def _ether_snapshot(tmp_path, body: str, *, host: str = "dist1") -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    projection, _interfaces, _commands = _project(tmp_path, host, body)
    receipt = _receipt({host: {"EtherChannel": "assessed"}})
    baseline = summarize_etherchannel_baseline(projection, receipt)
    return {
        "devices": {host: {}},
        "etherchannel_projection": projection,
        "protocol_assessability": receipt,
        "etherchannel_baseline": baseline,
    }


def _multichassis_snapshot(*, degraded: bool = False, partner: bool = True) -> dict:
    raw = _nxos_pair(second_status="down" if degraded else "up")
    if not partner:
        raw["observations"][1]["legs"][0]["lacp_partner_system_id"] = ""
    baseline = compute_multichassis_lag_domain_baseline(raw)
    return {
        "devices": {"leaf-a": {}, "leaf-b": {}},
        "multichassis_lag_typed_observations": {
            "observations": [dict(row) for row in raw["observations"]],
        },
        "multichassis_lag_domain_baseline": baseline,
    }


def _traffic_failure_snapshot() -> dict:
    snapshot = _symmetric_snapshot()
    intent = {**_intent(), "id": "erp-forward"}
    snapshot["traffic_assurance"] = traffic_assurance.assess_flows(snapshot, [{
        **intent,
        "failure": {"action": "fail_node", "id": "R2"},
    }])
    return snapshot


def _forged_preserved_traffic_snapshot() -> dict:
    """Build an internally tidy but producer-impossible v1 preservation claim for negatives."""
    snapshot = _traffic_failure_snapshot()
    traffic_set = snapshot["traffic_assurance"]
    result = traffic_set["results"][0]
    baseline = traffic_assurance.assess_flow(snapshot, result["intent"])
    failure = result["failure"]
    simulation = failure["cutover_evidence"]
    step = simulation["steps"][0]
    step.update({
        "newly_lost_flows": [],
        "recovered_flows": [],
        "stp_reroots": [],
        "fhrp_takeovers": [],
        "split_brain_risks": [],
        "l2_continuity": {
            "applicable": False,
            "assessed": None,
            "verdict": "not_applicable",
            "election_projection_count": 0,
            "affected_member_count": 0,
            "affected_member_hosts": [],
            "reason": "no L2-affecting mutation or election projection was requested",
        },
        "n_stp_election_candidates": 0,
        "n_fhrp_election_candidates": 0,
        "indeterminate": 0,
        "valid": True,
        "validation_errors": [],
        "is_noop": False,
        "narrative": "Synthetic failure retained the declared service path.",
    })
    simulation.update({
        "valid": True,
        "validation_errors": [],
        "worst_step": None,
        "summary": {
            "n_steps": 1,
            "total_newly_lost": 0,
            "total_recovered": 0,
            "total_stp_reroots": 0,
            "total_fhrp_takeovers": 0,
            "total_stp_election_candidates": 0,
            "total_fhrp_election_candidates": 0,
            "total_split_brain_risks": 0,
            "total_indeterminate": 0,
            "n_noop_steps": 0,
            "n_invalid_steps": 0,
            "n_input_errors": 0,
        },
    })
    result["dimensions"]["path"].update({"symmetric": True, "asymmetry": []})
    failure.update({
        "status": "preserved",
        "verdict": "proven",
        "baseline_verdict": "proven",
        "post_verdict": "proven",
        "post_dimensions": copy.deepcopy(result["dimensions"]),
        "cutover_gate": {
            "verdict": "proven",
            "n_indeterminate": 0,
            "n_split_brain_risks": 0,
            "continuity_assessed": True,
            "continuity_gaps": [],
        },
    })
    result["verdict"] = "proven"
    result["verdict_reasons"] = baseline["verdict_reasons"]
    for claim in result["claims"]:
        if claim["predicate"] in {
            "selected_rib_forwarding_projection", "stateless_acl_assurance",
        }:
            claim["verdict"] = claim["baseline_verdict"]
            claim["applicability"] = "applicable"
        elif claim["predicate"] in {
            "declared_scope_assurance", "requested_failure_assurance",
        }:
            claim["verdict"] = "proven"
    traffic_set["summary"].update({
        "proven": 1,
        "refuted": 0,
        "not_observed": 0,
        "indeterminate": 0,
    })
    return snapshot


def test_projection_reuses_existing_owners_and_never_owns_a_decision(tmp_path):
    snapshot = _ether_snapshot(
        tmp_path,
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(P)\n",
    )
    snapshot["stp_roots"] = {
        "dist1": {"10": {
            "root_priority": 4096, "root_address": "aaaa.0000.0001",
            "is_root": True, "is_mst": False, "bridge_priority": 4096,
        }},
        "dist2": {"10": {
            "root_priority": 4096, "root_address": "aaaa.0000.0001",
            "is_root": False, "is_mst": False, "bridge_priority": 8192,
        }},
    }
    result = compute_l2_failure_rehearsal(_bind(snapshot))

    assert result["schema"] == L2_FAILURE_REHEARSAL_SCHEMA
    assert result["owns_score"] is result["owns_verdict"] is False
    assert result["assurance_level"] == "not_verified"
    ether = _family(result, "etherchannel")[0]
    assert ether["disposition"] == "simulation_only"
    assert ether["evidence"]["observed_forwarding_capacity_units"] == 2
    assert ether["evidence"]["remaining_observed_units_after_loss"] == 1
    assert "min-links" in ether["note"] and "service-path survival" in ether["note"]
    stp = _family(result, "stp")[0]
    assert stp["source_owner"] == "failover_readiness/1 + stp_consistency_delta/1"
    assert stp["evidence"]["n_root_subjects"] == 1
    assert stp["evidence"]["n_candidate_backups"] == 1
    assert "convergence" in stp["note"] and stp["assurance_level"] == "not_verified"
    assert result["status"] == "not_verified"  # missing MCLAG/path evidence is not masked
    _assert_no_decision_owner(result)


def test_current_stp_and_etherchannel_faults_remain_explicit(tmp_path):
    (tmp_path / "stp").mkdir()
    ifaces, health, receipt = _stp_run(tmp_path / "stp", inconsistent="Gi1/0/7\n")
    snapshot = _ether_snapshot(
        tmp_path / "ether",
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(D)\n",
        host="sw1",
    )
    snapshot.update({
        "interfaces": ifaces,
        "protocol_health": health,
        "protocol_assessability": receipt,
        "stp_roots": {
            "sw1": {"10": {
                "root_priority": 4096, "root_address": "aaaa.0000.0001",
                "is_root": True, "is_mst": False, "bridge_priority": 4096,
            }},
        },
    })
    # Rebuild the EtherChannel owner against the final receipt. The STP helper's receipt deliberately
    # does not claim an EtherChannel cell, so the owner must not be relabelled as healthy by stale input.
    snapshot["etherchannel_baseline"] = summarize_etherchannel_baseline(
        snapshot["etherchannel_projection"], receipt, devices=snapshot["devices"],
    )
    result = compute_l2_failure_rehearsal(_bind(snapshot))

    stp = _family(result, "stp")[0]
    assert stp["disposition"] == "current_fault"
    assert stp["current_fault"] is True
    assert stp["evidence"]["n_current_faults"] == 1
    assert "sw1" in stp["evidence"]["current_fault_subjects"]
    # The existing EtherChannel owner retains its local degraded group even though the replacement
    # receipt changes its coverage context; it cannot become a favorable rehearsal result.
    ether = _family(result, "etherchannel")[0]
    assert ether["disposition"] == "current_fault"
    assert result["summary"]["n_current_faults"] >= 2


def test_current_etherchannel_fault_is_not_laundered_by_single_member_arithmetic(tmp_path):
    snapshot = _bind(_ether_snapshot(
        tmp_path,
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(D)\n",
    ))
    result = compute_l2_failure_rehearsal(snapshot)

    row = _family(result, "etherchannel")[0]
    assert row["disposition"] == "current_fault"
    assert row["current_fault"] is True
    assert row["evidence"]["observed_forwarding_capacity_units"] == 1
    assert row["evidence"]["remaining_observed_units_after_loss"] == 0
    assert cutover_operator_evidence(snapshot)["rehearsal"]["status"] == "current_fault"


def test_single_healthy_etherchannel_member_is_projected_risk_not_survival(tmp_path):
    snapshot = _bind(_ether_snapshot(
        tmp_path,
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P)\n",
    ))
    result = compute_l2_failure_rehearsal(snapshot)

    row = _family(result, "etherchannel")[0]
    assert row["current_fault"] is False
    assert row["disposition"] == "projected_risk"
    assert row["evidence"]["observed_forwarding_capacity_units"] == 1
    assert row["evidence"]["remaining_observed_units_after_loss"] == 0
    assert row["assurance_level"] == "not_verified"
    assert result["status"] == "projected_risk"
    assert result["summary"]["n_projected_risks"] == 1
    assert cutover_operator_evidence(snapshot)["rehearsal"]["status"] == "projected_risk"


def test_multichassis_rehearsal_requires_typed_attachment_identity_and_retains_faults():
    healthy = compute_l2_failure_rehearsal(_bind(_multichassis_snapshot()))
    row = _family(healthy, "multichassis_lag")[0]
    assert row["disposition"] == "simulation_only"
    assert row["evidence"] == {
        "transition": "unchanged_healthy",
        "reconciled_local_leg_count": 2,
        "remaining_observed_legs_after_loss": 1,
        "reciprocal_peer_evidenced": True,
        "matching_lacp_partner_evidenced": True,
    }
    assert "does not prove" in row["note"]

    degraded = compute_l2_failure_rehearsal(_bind(_multichassis_snapshot(degraded=True)))
    fault = _family(degraded, "multichassis_lag")[0]
    assert fault["disposition"] == "current_fault"
    assert fault["current_fault"] is True

    missing_partner = compute_l2_failure_rehearsal(_bind(
        _multichassis_snapshot(partner=False)))
    gap = _family(missing_partner, "multichassis_lag")[0]
    assert gap["disposition"] == "not_verified"
    assert "reciprocal peers" in gap["note"] and "LACP" in gap["note"]


def test_multichassis_baseline_must_reconcile_to_complete_copublished_observations():
    missing = _multichassis_snapshot()
    missing.pop("multichassis_lag_typed_observations")
    one_sided = _multichassis_snapshot()
    one_sided["multichassis_lag_typed_observations"]["observations"].pop()

    for label, snapshot in (("missing", missing), ("one-sided", one_sided)):
        row = _family(
            compute_l2_failure_rehearsal(_bind(snapshot)), "multichassis_lag",
        )[0]
        assert row["disposition"] == "not_verified", label
        assert row["evidence"] == {}, label
        assert "co-published typed observation" in row["note"], label


def test_detached_or_mutated_snapshot_cannot_authorize_failure_projection(tmp_path):
    raw = _ether_snapshot(
        tmp_path,
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(P)\n",
    )
    detached = compute_l2_failure_rehearsal(raw)
    assert detached["source_bound"] is False
    assert {row["disposition"] for row in detached["scenarios"]} == {"not_verified"}

    bound = _bind(raw)
    bound["devices"]["unexpected"] = {}
    mutated = compute_l2_failure_rehearsal(bound)
    assert mutated["source_bound"] is False
    assert {row["disposition"] for row in mutated["scenarios"]} == {"not_verified"}


def test_operator_evidence_binds_complete_l2_projection_without_claiming_rehearsal(tmp_path):
    snapshot = _bind(_ether_snapshot(
        tmp_path,
        "Group Port-channel Protocol Ports\n"
        "1 Po1(SU) LACP Gi1/0/1(P) Gi1/0/2(P)\n",
    ))
    evidence = cutover_operator_evidence(snapshot)
    l2 = evidence["rehearsal"]["l2_failure_rehearsal"]

    assert l2["schema"] == L2_FAILURE_REHEARSAL_SCHEMA
    assert l2["summary"]["n_scenarios"] == len(l2["scenarios"])
    assert evidence["rehearsal"]["assurance_level"] == "not_verified"
    assert "operator rehearsal" in evidence["rehearsal"]["note"]


def test_v1_l2_affecting_failure_cannot_be_forged_into_preserved_simulation():
    snapshot = _bind(_forged_preserved_traffic_snapshot())
    post = snapshot["traffic_assurance"]["results"][0]["failure"]["post_dimensions"]
    assert "R2" in {
        hop["host"] for direction in ("forward", "reverse")
        for hop in post["path"][direction]["hops"]
    }
    result = compute_l2_failure_rehearsal(snapshot)
    row = _family(result, "service_path")[0]

    assert row["subject"] == "erp-forward"
    assert row["source_owner"] == "traffic_assurance_set/1 -> cutover_sim/1"
    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}
    assert "malformed" in row["note"]
    assert row["assurance_level"] == "not_verified"


def test_favorable_service_projection_requires_complete_outer_owner_custody_and_claims():
    mutations = (
        ("missing custody", lambda row: row.pop("custody_trust")),
        ("unverified custody", lambda row: row.__setitem__("custody_trust", "not_evaluated")),
        ("missing dimensions", lambda row: row.__setitem__("dimensions", {})),
        ("missing claims", lambda row: row.__setitem__("claims", [])),
        ("unsupported", lambda row: row.__setitem__("supported", False)),
    )
    for label, mutate in mutations:
        snapshot = _traffic_failure_snapshot()
        mutate(snapshot["traffic_assurance"]["results"][0])
        row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]
        assert row["disposition"] == "not_verified", label
        assert row["evidence"] == {}, label


def test_dimension_claim_contradiction_cannot_retain_producer_evidence():
    contradicted = _traffic_failure_snapshot()
    result = contradicted["traffic_assurance"]["results"][0]
    for dimensions in (result["dimensions"], result["failure"]["post_dimensions"]):
        for axis in ("path", "policy", "mtu", "ecmp"):
            for direction in ("forward", "reverse"):
                dimensions[axis][direction]["verdict"] = "refuted"
    row = _family(compute_l2_failure_rehearsal(_bind(contradicted)), "service_path")[0]
    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}

def test_observed_drop_path_cannot_be_relabelled_as_proven_preservation():
    snapshot = _traffic_failure_snapshot()
    result = snapshot["traffic_assurance"]["results"][0]
    for dimensions in (result["dimensions"], result["failure"]["post_dimensions"]):
        dimensions["path"]["forward"].update({
            "verdict": "proven",
            "state": "observed_drop",
            "status": "computed:unreachable",
            "reached": False,
            "drop_evidence": "observed_discard",
            "ecmp_dropping_legs": [{"drop_evidence": "observed_discard"}],
        })

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_reached_path_requires_hop_owners_and_claim_boundary_reconciliation():
    snapshot = _traffic_failure_snapshot()
    result = snapshot["traffic_assurance"]["results"][0]
    for dimensions in (result["dimensions"], result["failure"]["post_dimensions"]):
        dimensions["path"]["forward"]["hops"] = []

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_proven_acl_stage_requires_closed_native_permit_semantics():
    snapshot = _traffic_failure_snapshot()
    result = snapshot["traffic_assurance"]["results"][0]
    for dimensions in (result["dimensions"], result["failure"]["post_dimensions"]):
        stage = dimensions["policy"]["forward"]["stages"][0]
        stage.update({
            "native_result": "PROVEN_NONE",
            "detail": "the exact tuple is denied (the implicit deny is included)",
        })

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_traffic_axis_custody_requires_complete_owner_receipts():
    snapshot = _traffic_failure_snapshot()
    result = snapshot["traffic_assurance"]["results"][0]
    for dimensions in (result["dimensions"], result["failure"]["post_dimensions"]):
        for direction in ("forward", "reverse"):
            dimensions["mtu"][direction]["interface_custody"] = {
                "verdict": "proven", "gaps": [],
            }
            dimensions["ecmp"][direction]["route_custody"] = {
                "verdict": "proven", "gaps": [],
            }

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_cutover_action_and_removed_subjects_are_revalidated_by_existing_owner():
    snapshot = _traffic_failure_snapshot()
    failure = snapshot["traffic_assurance"]["results"][0]["failure"]
    failure["mutation"]["removed_hosts"] = ["R3"]
    failure["cutover_evidence"]["steps"][0]["removed_hosts"] = ["R3"]

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_forged_preservation_cannot_coexist_with_newly_lost_requested_flow():
    snapshot = _forged_preserved_traffic_snapshot()
    result = snapshot["traffic_assurance"]["results"][0]
    step = result["failure"]["cutover_evidence"]["steps"][0]
    step["newly_lost_flows"] = [{
        "src": result["intent"]["src"],
        "dst": result["intent"]["dst"],
        "kind": "path_lost",
    }]
    simulation = result["failure"]["cutover_evidence"]
    simulation["summary"]["total_newly_lost"] = 1
    simulation["worst_step"] = 0

    row = _family(compute_l2_failure_rehearsal(_bind(snapshot)), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}


def test_current_traffic_failure_continuity_gap_is_explicit_not_verified():
    row = _family(
        compute_l2_failure_rehearsal(_bind(_traffic_failure_snapshot())),
        "service_path",
    )[0]

    assert row["subject"] == "erp-forward"
    assert row["disposition"] == "not_verified"
    assert row["evidence"]["producer_status"] == "l2_failover_not_proven"
    assert row["evidence"]["n_steps"] == 1
    assert row["evidence"]["n_indeterminate"] >= 1


def test_malformed_stored_cutover_simulation_cannot_claim_favorable_projection():
    snapshot = _traffic_failure_snapshot()
    # One stored row cannot reconcile to an asserted 99-step simulation.
    snapshot["traffic_assurance"]["results"][0]["failure"]["cutover_evidence"][
        "summary"
    ]["n_steps"] = 99
    snapshot = _bind(snapshot)
    row = _family(compute_l2_failure_rehearsal(snapshot), "service_path")[0]

    assert row["disposition"] == "not_verified"
    assert "malformed" in row["note"]


def test_invalid_cutover_step_and_forged_zero_summary_cannot_claim_preservation():
    snapshot = _traffic_failure_snapshot()
    step = snapshot["traffic_assurance"]["results"][0]["failure"]["cutover_evidence"][
        "steps"
    ][0]
    step.update({
        "newly_lost_flows": [{}],
        "split_brain_risks": [{}],
        "indeterminate": 7,
        "valid": False,
    })
    # Preserve the forged favorable producer summary/gate: validation must derive from the closed step,
    # not trust these zero counters or the apparent top-level proven verdict.
    row = _family(
        compute_l2_failure_rehearsal(_bind(snapshot)),
        "service_path",
    )[0]

    assert row["subject"] == "erp-forward"
    assert row["disposition"] == "not_verified"
    assert row["evidence"] == {}
    assert "malformed" in row["note"]
