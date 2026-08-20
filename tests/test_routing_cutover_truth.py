"""Receipt-gated routing baselines preserve observed state without inventing health."""

import json

import pytest

from cisco_toolkit.analyze import (
    PROTOCOL_ASSESSABILITY_FAMILIES,
    PROTOCOL_ASSESSABILITY_STATES,
    compute_validation_plan,
    normalize_routing_adjacency_state,
    summarize_routing_baseline,
)


FAMILIES = tuple(family["protocol"] for family in PROTOCOL_ASSESSABILITY_FAMILIES)
INPUTS = {
    family["protocol"]: tuple(item["id"] for item in family["inputs"])
    for family in PROTOCOL_ASSESSABILITY_FAMILIES
}


def _receipt(host_states):
    rows = []
    by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for host in sorted(host_states):
        states = host_states[host]
        for protocol in FAMILIES:
            state = states.get(protocol, "not_collected")
            capture = {
                "assessed": "usable",
                "partial": "missing",
                "captured_no_record": "usable",
                "captured_empty": "empty",
                "capture_error": "error",
                "not_collected": "missing",
                "analysis_unavailable": "missing",
            }[state]
            emitted = state in ("assessed", "partial")
            rows.append({
                "switch": host,
                "protocol": protocol,
                "input_states": {name: capture for name in INPUTS[protocol]},
                "capture_state": capture,
                "health_row_emitted": emitted,
                "state": state,
                "reason": f"fixture: {state}",
            })
            by_state[state] += 1
    complete = sum(
        all(host_states[host].get(protocol, "not_collected") == "assessed"
            for protocol in FAMILIES)
        for host in host_states
    )
    return {
        "schema": "protocol_assessability/1",
        "families": [{"protocol": protocol} for protocol in FAMILIES],
        "rows": rows,
        "summary": {
            "n_devices": len(host_states),
            "n_families": len(FAMILIES),
            "n_cells": len(rows),
            "n_health_rows": sum(row["health_row_emitted"] for row in rows),
            "n_complete_devices": complete,
            "by_state": by_state,
        },
        "limitations": ["fixture receipt"],
    }


def _ospf(peer, state="FULL/DR", interface="Po1"):
    return {"neighbor": peer, "state": state, "address": peer, "interface": interface}


def _bgp(peer, state="0", remote_as="65001"):
    return {"neighbor": peer, "state": state, "as": remote_as}


def _eigrp(peer, state="up 00:12:00", interface="Gi0/1"):
    return {"neighbor": peer, "state": state, "interface": interface}


def test_routing_baseline_classifies_exact_subtype_states_and_is_json_ready():
    receipt = _receipt({"core1": {"OSPF": "assessed", "BGP": "assessed", "EIGRP": "assessed"}})
    routing = {"core1": {
        "ospf": [_ospf("10.0.0.2"), _ospf("10.0.0.9", "EXSTART/DROTHER", "Vlan40")],
        "bgp": [_bgp("192.0.2.2", "0")],
        "eigrp": [_eigrp("10.0.0.3")],
    }}

    baseline = summarize_routing_baseline(routing, receipt)
    rows = {row["protocol"]: row for row in baseline["rows"]}

    json.dumps(baseline, sort_keys=True)
    assert baseline["schema"] == "routing_adjacency_baseline/1"
    assert baseline["scope"] == "baseline_observed"
    assert baseline["status"] == "degraded"
    assert baseline["assessed"] is True
    assert baseline["projection_custody"] == "embedded_unverified"
    assert baseline["summary"] == {
        "n_subject_cells": 3,
        "n_peers": 4,
        "n_degraded_peers": 1,
        "n_rejected_records": 0,
        "by_status": {"assessed": 2, "degraded": 1, "review": 0, "not_verified": 0},
    }

    assert rows["OSPF"]["status"] == "degraded"
    assert "10.0.0.9 state EXSTART/DROTHER" in rows["OSPF"]["baseline"]
    assert rows["OSPF"]["acceptance"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "NOT ACCEPTANCE" in rows["OSPF"]["acceptance"]
    assert rows["OSPF"]["command"] == "show ip ospf neighbor"
    assert rows["BGP"]["status"] == "assessed"
    assert rows["BGP"]["peers"][0]["state"] == "ESTABLISHED"
    assert "Established (observed prefix count 0" in rows["BGP"]["baseline"]
    assert "prefix-count change is informational and is not pinned" in rows["BGP"]["acceptance"]
    assert rows["EIGRP"]["status"] == "assessed"
    assert rows["EIGRP"]["peers"][0]["state"] == "UP"
    assert "UP/present (observed uptime 00:12:00" in rows["EIGRP"]["baseline"]
    assert "uptime change is informational and is not pinned" in rows["EIGRP"]["acceptance"]
    assert all(" + protocol_assessability.rows[" in row["source_key"] for row in baseline["rows"])


def test_assessed_zero_is_review_not_a_zero_peer_health_claim():
    receipt = _receipt({"core1": {"OSPF": "assessed"}})
    baseline = summarize_routing_baseline(
        {"core1": {"ospf": [], "bgp": [], "eigrp": []}}, receipt
    )

    assert baseline["status"] == "review" and baseline["assessed"] is False
    assert len(baseline["rows"]) == 1
    row = baseline["rows"][0]
    assert row["protocol"] == "OSPF" and row["peer_count"] == 0
    assert row["status"] == "review"
    assert {finding["code"] for finding in row["findings"]} == {"assessed_zero_projection"}
    assert "zero peers" in row["issue"]
    assert row["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")


def test_nonempty_subject_without_receipt_is_not_verified_and_never_idealized():
    baseline = summarize_routing_baseline(
        {"core1": {"ospf": [_ospf("10.0.0.2")]}}, None
    )

    assert baseline["status"] == "not_verified"
    assert baseline["receipt"] == {
        "present": False, "valid": False, "reason": "protocol assessability receipt is missing"
    }
    row = baseline["rows"][0]
    assert row["status"] == "not_verified"
    assert row["peers"][0]["status"] == "not_verified"
    assert "receipt_missing" in {finding["code"] for finding in row["findings"]}
    assert "10.0.0.2 state FULL/DR" in row["baseline"]
    assert row["baseline"].startswith("Embedded/apparent unverified projection")
    assert row["acceptance"].startswith("ROUTING BASELINE NOT VERIFIED — BLOCKER:")
    assert "in FULL" not in row["acceptance"]


def test_duplicate_canonical_peer_identity_is_review_not_silently_deduplicated():
    receipt = _receipt({"edge1": {"BGP": "assessed"}})
    routing = {"edge1": {"bgp": [
        _bgp("2001:db8::1", "7"),
        _bgp("2001:0db8:0:0:0:0:0:1", "9"),
    ]}}

    baseline = summarize_routing_baseline(routing, receipt)
    row = baseline["rows"][0]

    assert row["status"] == "review"
    assert row["peer_count"] == 1 and row["rejected_record_count"] == 1
    assert baseline["summary"]["n_rejected_records"] == 1
    assert "duplicate_peer_identity" in {finding["code"] for finding in row["findings"]}
    assert "VRF, process, or address-family" in row["issue"]
    assert row["peers"][0]["status"] == "review"
    assert row["baseline"].startswith("Embedded/apparent unverified projection")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda receipt: receipt["summary"].__setitem__("n_health_rows", 99),
        lambda receipt: receipt["summary"]["by_state"].__setitem__("assessed", 0),
        lambda receipt: receipt["summary"]["by_state"].__setitem__("assessed", True),
        lambda receipt: next(row for row in receipt["rows"] if row["protocol"] == "OSPF").__setitem__(
            "capture_state", "missing"
        ),
        lambda receipt: next(row for row in receipt["rows"] if row["protocol"] == "OSPF")[
            "input_states"
        ].__setitem__("neighbors", "empty"),
    ],
)
def test_strict_receipt_reconciliation_fails_closed(mutation):
    receipt = _receipt({"core1": {"OSPF": "assessed"}})
    mutation(receipt)

    baseline = summarize_routing_baseline(
        {"core1": {"ospf": [_ospf("10.0.0.2")]}}, receipt
    )

    assert baseline["receipt"]["valid"] is False
    assert baseline["status"] == "review"
    assert baseline["rows"][0]["status"] == "review"
    assert "receipt_invalid" in {finding["code"] for finding in baseline["rows"][0]["findings"]}


def test_eigrp_unclassified_state_is_review_and_normalizer_is_anchored():
    assert normalize_routing_adjacency_state("EIGRP", "up 00:12:00") == ("UP", True)
    assert normalize_routing_adjacency_state("EIGRP", "upside-down") == ("UPSIDE-DOWN", None)
    receipt = _receipt({"core1": {"EIGRP": "assessed"}})

    baseline = summarize_routing_baseline(
        {"core1": {"eigrp": [_eigrp("10.0.0.3", "upside-down")]}}, receipt
    )

    row = baseline["rows"][0]
    assert row["status"] == "review"
    assert "unclassified_state" in {finding["code"] for finding in row["findings"]}
    assert not any(finding["kind"] == "degraded" for finding in row["findings"])


def test_clean_empty_nonassessed_routing_cells_emit_no_pure_l2_subject():
    receipt = _receipt({"access1": {
        "OSPF": "captured_empty",
        "BGP": "captured_no_record",
        "EIGRP": "not_collected",
    }})

    baseline = summarize_routing_baseline(
        {"access1": {"ospf": [], "bgp": [], "eigrp": []}}, receipt
    )

    assert baseline["rows"] == []
    assert baseline["status"] == "not_verified"
    assert baseline["assessed"] is False
    assert baseline["summary"]["n_subject_cells"] == 0
    assert "not proof" in baseline["limitations"][1]


@pytest.mark.parametrize("routing, receipt", [(None, None), (7, "bad"), ([], {}), ({"core1": 7}, 7)])
def test_routing_baseline_is_total_on_malformed_roots(routing, receipt):
    baseline = summarize_routing_baseline(routing, receipt)

    assert isinstance(baseline, dict) and isinstance(baseline["rows"], list)
    json.dumps(baseline, sort_keys=True)


def test_scopable_malformed_host_projection_emits_review_rows_not_false_no_subject():
    baseline = summarize_routing_baseline({"core1": 7}, None)

    assert baseline["status"] == "review"
    assert {row["protocol"] for row in baseline["rows"]} == {"OSPF", "BGP", "EIGRP"}
    assert all(row["status"] == "review" for row in baseline["rows"])
    assert all("projection_malformed" in {finding["code"] for finding in row["findings"]}
               for row in baseline["rows"])


def test_validation_plan_consumes_degraded_baseline_and_publishes_custody_fields():
    receipt = _receipt({"core1": {"OSPF": "assessed"}})
    routing = {"core1": {"ospf": [
        _ospf("10.0.99.2", "FULL/DR"),
        _ospf("10.0.99.9", "EXSTART/DROTHER", "Vlan40"),
    ]}}

    plan = compute_validation_plan(
        {"core1": {}},
        move_groups=[{"switches": ["core1"]}],
        routing_neighbors=routing,
        devices={"core1": {"platform": "ios"}},
        protocol_assessability=receipt,
    )
    row = next(item for item in plan["items"] if item["category"] == "Routing")

    assert row["check"] == "OSPF degraded adjacency baseline"
    assert row["command"] == "show ip ospf neighbor"
    assert row["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "10.0.99.2 state FULL/DR" in row["expect"]
    assert "10.0.99.9 state EXSTART/DROTHER" in row["expect"]
    assert "2 neighbor(s) in FULL" not in row["expect"]
    assert row["evidence_state"] == "degraded"
    assert row["projection_custody"] == "embedded_unverified"
    assert row["source_key"] == (
        "routing_neighbors.core1.ospf + protocol_assessability.rows[core1,OSPF]"
    )


def test_bgp_idle_is_a_definite_degraded_baseline():
    receipt = _receipt({"edge1": {"BGP": "assessed"}})
    row = summarize_routing_baseline(
        {"edge1": {"bgp": [_bgp("192.0.2.2", "Idle")]}}, receipt
    )["rows"][0]

    assert row["status"] == "degraded"
    assert row["peers"][0]["state"] == "IDLE"
    assert row["peers"][0]["status"] == "degraded"
    assert "bgp_not_established" in {finding["code"] for finding in row["findings"]}
