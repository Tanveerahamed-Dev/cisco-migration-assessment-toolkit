"""Decision-grade PVST/MST topology evidence, delta, rehearsal, and portfolio coverage."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from cisco_toolkit.html import compute_cutover_gate
from cisco_toolkit.l2_rehearsal import compute_l2_failure_rehearsal
from cisco_toolkit.parse import parse_spanning_tree_root
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    bound_snapshot_source,
    protocol_family_change_set,
)
from cisco_toolkit.protocol_deltas import compute_stp_topology_delta
from cisco_toolkit.stp_topology import (
    STP_TOPOLOGY_BASELINE_SCHEMA,
    compute_stp_topology_baseline,
    produce_stp_topology_observation,
    validate_stp_topology_baseline,
    validate_stp_topology_observation,
)
from webapp.backend import protocol_portfolio


# Anonymized real IOS-XE Rapid-PVST output shape: full Root/Bridge ID blocks and the
# per-VLAN Role/Sts table are retained verbatim in structure.
PVST_STATE = """\
VLAN0010
  Spanning tree enabled protocol rstp
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             This bridge is the root
  Bridge ID  Priority    24586  (priority 24576 sys-id-ext 10)
             Address     aaaa.0001.0001
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Gi1/0/1          Desg FWD 4         128.1    P2p
Gi1/0/24         Altn BLK 19        128.24   P2p
"""

PVST_DETAIL = """\
VLAN0010 is executing the rstp compatible Spanning Tree protocol
  Number of topology changes 2 last change occurred 00:01:12 ago
"""

# Anonymized real IOS-XE MST output shape.  MST0 and MST2 remain instance namespaces, not VLAN IDs.
MST_STATE = """\
MST0000
  Spanning tree enabled protocol mstp
  Root ID    Priority    24576
             Address     0011.2233.4455
             Cost        20000
  Bridge ID  Priority    32768
             Address     00aa.bbcc.ddee
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Po10             Root FWD 20000     128.10   P2p
Gi1/0/48         Altn BLK 20000     128.48   P2p

MST0002
  Spanning tree enabled protocol mstp
  Root ID    Priority    24578
             Address     0011.2233.4455
             Cost        20000
  Bridge ID  Priority    32770
             Address     00aa.bbcc.ddee
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Po10             Root FWD 20000     128.10   P2p
Gi1/0/47         Desg FWD 20000     128.47   P2p
"""

MST_DETAIL = """\
###### MST0000 vlans mapped:   1-9,11-19
  Number of topology changes 7 last change occurred 1d02h ago
###### MST0002 vlans mapped:   10,20-29
  Number of topology changes 3 last change occurred 00:12:03 ago
"""


def _snapshot(state: str, detail: str, *, host: str = "dist1") -> dict:
    observation = produce_stp_topology_observation(
        state,
        detail,
        state_capture_state="usable",
        detail_capture_state="usable",
    )
    observations = {host: observation}
    devices = {host: {"platform": "iosxe"}}
    roots = {host: parse_spanning_tree_root(state)}
    return {
        "script_version": "V3.23.0",
        "devices": devices,
        "stp_topology_observations": observations,
        "stp_topology_baseline": compute_stp_topology_baseline(observations, devices),
        "stp_roots": roots,
    }


def _bound(value: dict) -> tuple[dict, dict]:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    snapshot = bind_snapshot_json_bytes(raw)
    return snapshot, {
        "sha256": bound_snapshot_source(snapshot)["sha256"],
        "bytes": len(raw),
    }


def _delta(before: dict, after: dict) -> dict:
    bound_before, before_binding = _bound(before)
    bound_after, after_binding = _bound(after)
    return compute_stp_topology_delta(
        bound_before,
        bound_after,
        comparison_source_binding={
            "before": before_binding,
            "after": after_binding,
        },
    )


def _gate(native: dict, expected_changes=()) -> dict:
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 1},
        "changes": [],
        "coverage_gaps": [],
    }
    family_set = protocol_family_change_set(
        ipv4,
        {"expected_changes": list(expected_changes)},
        native_deltas=[native],
    )
    delta = {
        "verdict": "CLEAN",
        "verdict_display": "NO DELTA REGRESSION OBSERVED",
        "verdict_note": "clean",
        "protocol_adjacencies": {
            "gate": "PASS",
            "summary": {
                "n_state_regressed": 0,
                "n_coverage_gaps": 0,
                "n_baseline_peers": 1,
            },
        },
    }
    return compute_cutover_gate(
        delta,
        {"verdict": "PASS", "verdict_note": "clean"},
        protocol_family_changes=family_set,
    )


@pytest.mark.parametrize(
    ("state", "detail", "expected_namespaces", "expected_rows"),
    (
        (PVST_STATE, PVST_DETAIL, {"pvst_vlan"}, 1),
        (MST_STATE, MST_DETAIL, {"mst_instance"}, 2),
    ),
)
def test_real_pvst_and_mst_evidence_preserves_namespace_roles_paths_and_counters(
        state, detail, expected_namespaces, expected_rows):
    snapshot = _snapshot(state, detail)
    observation = snapshot["stp_topology_observations"]["dist1"]
    baseline = snapshot["stp_topology_baseline"]

    assert observation["finding_codes"] == []
    assert baseline["schema"] == STP_TOPOLOGY_BASELINE_SCHEMA
    assert baseline["verdict"] == "CLEAR"
    assert len(baseline["rows"]) == expected_rows
    assert {row["namespace"] for row in baseline["rows"]} == expected_namespaces
    assert all(row["forwarding_paths"] for row in baseline["rows"])
    assert all(type(row["topology_change_count"]) is int for row in baseline["rows"])
    assert validate_stp_topology_baseline(
        baseline,
        observations=snapshot["stp_topology_observations"],
        legacy_roots=snapshot["stp_roots"],
        devices=snapshot["devices"],
    )["valid"] is True


def test_complete_typed_self_comparison_has_no_synthetic_role_or_counter_gap():
    snapshot = _snapshot(PVST_STATE, PVST_DETAIL)
    result = _delta(snapshot, deepcopy(snapshot))

    assert result["assurance_level"] == "local_safety_preservation"
    assert result["assessed"] is True
    assert result["summary"]["by_transition"]["coverage_lost"] == 0
    assert result["summary"]["by_transition"]["not_comparable"] == 0
    subjects = {row["subject"] for row in result["changes"]}
    assert "root|dist1|pvst_vlan|10" in subjects
    assert "path|dist1|pvst_vlan|10|Gi1/0/1" in subjects
    assert "path|dist1|pvst_vlan|10|Gi1/0/24" in subjects
    assert "counter|dist1|pvst_vlan|10" in subjects
    assert not any(subject.endswith(("port_roles", "topology_change_counters"))
                   for subject in subjects)


def test_counter_increase_and_current_invalid_role_state_block_the_canonical_gate():
    before = _snapshot(PVST_STATE, PVST_DETAIL)
    after_counter = _snapshot(
        PVST_STATE,
        PVST_DETAIL.replace("topology changes 2", "topology changes 3"),
    )
    counter_delta = _delta(before, after_counter)
    counter = next(
        row for row in counter_delta["changes"] if row["subject"].startswith("counter|")
    )
    assert counter["transition"] == "regressed"
    assert counter["decision_effect"] == "block"
    assert _gate(counter_delta)["verdict"] == "REGRESSED"
    assert _gate(counter_delta, [{
        "family": "stp_topology",
        "transitions": ["regressed"],
        "subjects": [counter["subject"]],
    }])["verdict"] == "REGRESSED"

    invalid = _snapshot(PVST_STATE.replace("Altn BLK", "Altn FWD"), PVST_DETAIL)
    invalid_delta = _delta(invalid, deepcopy(invalid))
    health = next(
        row for row in invalid_delta["changes"] if row["subject"].startswith("health|")
    )
    assert health["transition"] == "unchanged_degraded"
    assert health["decision_effect"] == "block"
    assert _gate(invalid_delta)["verdict"] == "REGRESSED"
    assert _gate(invalid_delta, [{
        "family": "stp_topology",
        "transitions": ["unchanged_degraded"],
        "subjects": [health["subject"]],
    }])["verdict"] == "REGRESSED"

    transitional = _snapshot(PVST_STATE.replace("Desg FWD", "Desg LRN", 1), PVST_DETAIL)
    transitional_delta = _delta(transitional, deepcopy(transitional))
    transitional_health = next(
        row for row in transitional_delta["changes"]
        if row["subject"].startswith("health|")
    )
    assert transitional_health["transition"] == "unchanged_degraded"
    assert transitional_health["decision_effect"] == "block"
    assert _gate(transitional_delta, [{
        "family": "stp_topology",
        "transitions": ["unchanged_degraded"],
        "subjects": [transitional_health["subject"]],
    }])["verdict"] == "REGRESSED"


def test_root_and_role_movement_remain_explicit_intent_review():
    before = _snapshot(PVST_STATE, PVST_DETAIL)
    after_state = PVST_STATE.replace(
        "aaaa.0001.0001", "bbbb.0002.0002",
    ).replace(
        "Gi1/0/24         Altn BLK", "Gi1/0/24         Desg FWD",
    )
    result = _delta(before, _snapshot(after_state, PVST_DETAIL))

    root = next(row for row in result["changes"] if row["subject"].startswith("root|"))
    role = next(
        row for row in result["changes"]
        if row["subject"].endswith("|Gi1/0/24")
    )
    assert (root["transition"], root["decision_effect"]) == ("intent_changed", "review")
    assert (role["transition"], role["decision_effect"]) == ("intent_changed", "review")


@pytest.mark.parametrize(
    "mutation",
    (
        lambda snap: snap["stp_topology_baseline"].pop("coverage"),
        lambda snap: snap["stp_topology_baseline"].__setitem__("schema", "renamed/1"),
        lambda snap: snap["stp_topology_observations"]["dist1"].pop("role_parsed_count"),
        lambda snap: snap["stp_topology_observations"]["dist1"].__setitem__("roles", "truncated"),
    ),
    ids=("missing-leaf", "renamed-schema", "observation-leaf-missing", "truncated-rows"),
)
def test_required_baseline_or_observation_mutation_cannot_pass(mutation):
    before = _snapshot(PVST_STATE, PVST_DETAIL)
    after = deepcopy(before)
    mutation(after)

    result = _delta(before, after)

    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert result["summary"]["by_transition"]["coverage_lost"] \
        + result["summary"]["by_transition"]["not_comparable"] >= 1
    assert _gate(result)["verdict"] == "INDETERMINATE"


@pytest.mark.parametrize(
    ("state", "detail", "code"),
    (
        (PVST_STATE.replace("Altn BLK", "Unknown BLK"), PVST_DETAIL, "role_row_malformed"),
        (PVST_STATE, "VLAN0010\n", "topology_counter_missing"),
        (PVST_STATE, PVST_DETAIL.replace("topology changes 2", "topology events two"),
         "topology_counter_missing"),
    ),
    ids=("renamed-role", "truncated-detail", "renamed-counter-leaf"),
)
def test_malformed_or_truncated_capture_stays_coverage_lost(state, detail, code):
    snapshot = _snapshot(state, detail)
    observation = snapshot["stp_topology_observations"]["dist1"]
    assert code in observation["finding_codes"]

    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["coverage_lost"] >= 1
    assert _gate(result)["verdict"] == "INDETERMINATE"


def test_rehearsal_reports_exact_typed_role_counter_coverage_without_service_claim():
    first = _snapshot(PVST_STATE, PVST_DETAIL, host="dist1")
    second_state = PVST_STATE.replace(
        "             This bridge is the root\n", "             Cost        4\n",
    ).replace("Gi1/0/1          Desg", "Gi1/0/1          Root")
    second = _snapshot(second_state, PVST_DETAIL, host="dist2")
    observations = {
        **first["stp_topology_observations"],
        **second["stp_topology_observations"],
    }
    devices = {**first["devices"], **second["devices"]}
    roots = {**first["stp_roots"], **second["stp_roots"]}
    snapshot = {
        "script_version": "V3.23.0",
        "devices": devices,
        "stp_topology_observations": observations,
        "stp_topology_baseline": compute_stp_topology_baseline(observations, devices),
        "stp_roots": roots,
    }

    result = compute_l2_failure_rehearsal(_bound(snapshot)[0])
    row = next(item for item in result["scenarios"] if item["family"] == "stp")

    assert row["evidence"]["n_topology_root_subjects"] == 2
    assert row["evidence"]["n_topology_role_subjects"] == 4
    assert row["evidence"]["n_forwarding_paths"] == 2
    assert row["evidence"]["n_blocked_paths"] == 2
    assert row["evidence"]["n_topology_counter_subjects"] == 2
    assert row["evidence"]["n_topology_not_verified"] == 0
    assert "convergence time" in row["note"] and "service continuity" in row["note"]
    assert row["assurance_level"] == "not_verified"


def test_single_snapshot_portfolio_exposes_root_role_path_and_counter_subjects():
    snapshot = _snapshot(PVST_STATE, PVST_DETAIL)
    view = protocol_portfolio._stp_topology_view(snapshot)

    assert view["valid"] is True
    assert view["evidence_status"] == "observed"
    assert {row["kind"] for row in view["subjects"]} == {"root", "path", "counter"}
    path = next(row for row in view["subjects"] if row["kind"] == "path")
    assert path["detail"]["namespace"] == "pvst_vlan"
    assert path["detail"]["role"] in {"designated", "alternate"}
    assert path["detail"]["state"] in {"forwarding", "blocked"}

    mutated = deepcopy(snapshot)
    mutated["stp_topology_baseline"]["rows"][0]["port_roles"] = []
    invalid = protocol_portfolio._stp_topology_view(mutated)
    assert invalid["valid"] is False
    assert invalid["evidence_status"] == "not_verified"
    assert invalid["subjects"] == []


def test_explicit_no_subject_requires_the_paired_detail_capture() -> None:
    observation = produce_stp_topology_observation(
        "Spanning tree is not enabled.",
        "",
        state_capture_state="usable",
        detail_capture_state="missing",
    )
    assert validate_stp_topology_observation(observation) == (True, "ok")
    assert observation["explicit_no_subject"] is False
    assert set(observation["finding_codes"]) >= {
        "detail_capture_missing", "state_instance_missing",
    }
    devices = {"dist1": {"platform": "iosxe"}}
    snapshot = {
        "script_version": "V3.23.0",
        "devices": devices,
        "stp_topology_observations": {"dist1": observation},
        "stp_topology_baseline": compute_stp_topology_baseline(
            {"dist1": observation}, devices),
        "stp_roots": {"dist1": {}},
    }
    assert snapshot["stp_topology_baseline"]["verdict"] == "INDETERMINATE"
    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert _gate(result)["verdict"] == "INDETERMINATE"


def test_explicit_no_subject_rejects_usable_but_unrecognized_detail_output() -> None:
    observation = produce_stp_topology_observation(
        "Spanning tree is not enabled.",
        "unexpected renamed output",
        state_capture_state="usable",
        detail_capture_state="usable",
    )
    assert observation["explicit_no_subject"] is False
    assert "state_instance_missing" in observation["finding_codes"]
    devices = {"dist1": {"platform": "iosxe"}}
    snapshot = {
        "script_version": "V3.23.0",
        "devices": devices,
        "stp_topology_observations": {"dist1": observation},
        "stp_topology_baseline": compute_stp_topology_baseline(
            {"dist1": observation}, devices),
        "stp_roots": {"dist1": {}},
    }
    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert _gate(result)["verdict"] == "INDETERMINATE"


def test_malformed_interface_row_is_counted_before_parser_rejection() -> None:
    state = PVST_STATE.replace("Gi1/0/24         Altn BLK", "BADPORT          Altn BLK")
    snapshot = _snapshot(state, PVST_DETAIL)
    observation = snapshot["stp_topology_observations"]["dist1"]

    assert observation["role_candidate_count"] == 2
    assert observation["role_parsed_count"] == 1
    assert "role_row_malformed" in observation["finding_codes"]
    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert _gate(result)["verdict"] == "INDETERMINATE"


def test_role_table_row_with_multiple_malformed_leaves_cannot_disappear() -> None:
    state = PVST_STATE.replace(
        "Gi1/0/24         Altn BLK 19        128.24   P2p",
        "BADPORT          Unknown XXX 19        128.24   P2p",
    )
    snapshot = _snapshot(state, PVST_DETAIL)
    observation = snapshot["stp_topology_observations"]["dist1"]

    assert observation["role_candidate_count"] == 2
    assert observation["role_parsed_count"] == 1
    assert "role_row_malformed" in observation["finding_codes"]
    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["coverage_lost"] > 0
    assert _gate(result)["verdict"] == "INDETERMINATE"


def test_extra_off_roster_observation_cannot_disappear_from_the_denominator() -> None:
    snapshot = _snapshot(PVST_STATE, PVST_DETAIL)
    snapshot["stp_topology_observations"]["rogue"] = {"malformed": "ignored"}
    snapshot["stp_topology_baseline"] = compute_stp_topology_baseline(
        snapshot["stp_topology_observations"], snapshot["devices"]
    )

    assert snapshot["stp_topology_baseline"]["verdict"] == "INDETERMINATE"
    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert _gate(result)["verdict"] == "INDETERMINATE"


@pytest.mark.parametrize(
    ("field", "value"),
    (("state_capture_state", "missing"), ("detail_capture_state", "error")),
)
def test_persisted_capture_state_contradiction_cannot_remain_clear(field, value) -> None:
    snapshot = _snapshot(PVST_STATE, PVST_DETAIL)
    snapshot["stp_topology_observations"]["dist1"][field] = value
    snapshot["stp_topology_observations"]["dist1"]["finding_codes"] = []
    snapshot["stp_topology_baseline"] = compute_stp_topology_baseline(
        snapshot["stp_topology_observations"], snapshot["devices"]
    )

    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert _gate(result)["verdict"] == "INDETERMINATE"


@pytest.mark.parametrize("missing_key", ("devices", "stp_roots"))
def test_typed_decision_requires_device_denominator_and_legacy_root_co_owner(
        missing_key) -> None:
    snapshot = _snapshot(PVST_STATE, PVST_DETAIL)
    snapshot.pop(missing_key)

    result = _delta(snapshot, deepcopy(snapshot))
    assert result["assessed"] is False
    assert result["summary"]["by_transition"]["unchanged_healthy"] == 0
    assert _gate(result)["verdict"] == "INDETERMINATE"
