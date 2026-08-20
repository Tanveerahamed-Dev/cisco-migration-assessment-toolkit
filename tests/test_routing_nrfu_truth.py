"""NRFU routing cases are projections of the receipt-gated adjacency-baseline owner."""

from __future__ import annotations

from copy import deepcopy

from cisco_toolkit.analyze import (
    PROTOCOL_ASSESSABILITY_FAMILIES,
    PROTOCOL_ASSESSABILITY_STATES,
    summarize_routing_baseline,
)
from cisco_toolkit.nrfu_export import compute_nrfu_commands, write_nrfu_pack


ROUTING_COMMANDS = {
    "OSPF": "show ip ospf neighbor",
    "BGP": "show ip bgp summary",
    "EIGRP": "show ip eigrp neighbors",
}


def _receipt(host: str = "r1", states: dict[str, str] | None = None) -> dict:
    states = states or {}
    rows = []
    by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for family in PROTOCOL_ASSESSABILITY_FAMILIES:
        protocol = family["protocol"]
        state = states.get(protocol, "not_collected")
        emitted = state in ("assessed", "partial")
        if state in ("assessed", "captured_no_record"):
            input_value = "usable"
        elif state == "captured_empty":
            input_value = "empty"
        elif state == "capture_error":
            input_value = "error"
        else:
            input_value = "missing"
        input_states = {item["id"]: input_value for item in family["inputs"]}
        required = [input_states[item["id"]] for item in family["inputs"] if item["required"]]
        capture_state = (
            "usable" if "usable" in required else
            "error" if "error" in required else
            "empty" if "empty" in required else "missing"
        )
        rows.append({
            "switch": host,
            "protocol": protocol,
            "input_states": input_states,
            "capture_state": capture_state,
            "health_row_emitted": emitted,
            "state": state,
            "reason": f"fixture: {state}",
        })
        by_state[state] += 1

    complete = int(all(row["state"] == "assessed" for row in rows))
    return {
        "schema": "protocol_assessability/1",
        "families": [{"protocol": family["protocol"]}
                     for family in PROTOCOL_ASSESSABILITY_FAMILIES],
        "rows": rows,
        "summary": {
            "n_devices": 1,
            "n_families": len(PROTOCOL_ASSESSABILITY_FAMILIES),
            "n_cells": len(rows),
            "n_health_rows": sum(row["health_row_emitted"] for row in rows),
            "n_complete_devices": complete,
            "by_state": by_state,
        },
        "limitations": ["fixture"],
    }


def _ospf(peer: str, state: str) -> dict:
    return {
        "neighbor": peer,
        "state": state,
        "address": peer,
        "interface": "Po1",
    }


def _bgp(peer: str, state: str) -> dict:
    return {"neighbor": peer, "as": "65002", "state": state}


def _eigrp(peer: str, state: str) -> dict:
    return {"neighbor": peer, "interface": "Gi0/1", "state": state}


def _snap(routing: dict, receipt=...) -> dict:
    snap = {
        "devices": {"r1": {"platform": "ios"}},
        "interfaces": {"r1": {}},
        "routing_neighbors": {"r1": {
            "ospf": list(routing.get("ospf") or []),
            "bgp": list(routing.get("bgp") or []),
            "eigrp": list(routing.get("eigrp") or []),
        }},
    }
    if receipt is ...:
        snap["protocol_assessability"] = _receipt(states={
            protocol: "assessed"
            for protocol, key in (("OSPF", "ospf"), ("BGP", "bgp"), ("EIGRP", "eigrp"))
            if routing.get(key)
        })
    elif receipt is not None:
        snap["protocol_assessability"] = receipt
    return snap


def _routing_cases(output: dict) -> dict[str, dict]:
    return {
        case["command"]: case
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case["command"] in set(ROUTING_COMMANDS.values())
    }


def _owner_rows(snap: dict) -> dict[str, dict]:
    owner = summarize_routing_baseline(
        snap.get("routing_neighbors"), snap.get("protocol_assessability")
    )
    return {row["command"]: row for row in owner["rows"]}


def test_assessed_nrfu_cases_reuse_exact_baseline_acceptance_and_custody():
    snap = _snap({
        "ospf": [_ospf("10.0.0.2", "FULL/DR"), _ospf("10.0.0.3", "2WAY/DROTHER")],
        "bgp": [_bgp("192.0.2.2", "12")],
        "eigrp": [_eigrp("10.0.0.4", "up 01:22:33")],
    })

    output = compute_nrfu_commands(snap)
    cases = _routing_cases(output)
    owner_rows = _owner_rows(snap)

    assert set(cases) == set(ROUTING_COMMANDS.values())
    for command, case in cases.items():
        owner = owner_rows[command]
        if command == "show ip bgp summary":
            # A serialized/legacy snapshot has no process-local configured-peer marker.  Runtime
            # presence alone cannot authorize a positive configured-denominator target.
            assert case["expected"].startswith(
                "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:")
            assert case["evidence_state"] == "not_verified"
        else:
            assert case["expected"] == owner["acceptance"]
            assert case["evidence_state"] == "assessed"
        assert case["projection_custody"] == "embedded_unverified"
        if command != "show ip bgp summary":
            assert case["source_key"] == owner["source_key"]
    assert "2WAY/DROTHER" in cases["show ip ospf neighbor"]["expected"]
    assert "in FULL" not in cases["show ip ospf neighbor"]["expected"]
    bgp_expected = cases["show ip bgp summary"]["expected"]
    eigrp_expected = cases["show ip eigrp neighbors"]["expected"]
    assert "do not infer Established from a numeric summary token" in bgp_expected
    assert "uptime is informational" in eigrp_expected and "not pinned" in eigrp_expected
    assert output["summary"]["n_routing_cases"] == 3
    assert output["summary"]["n_routing_blockers"] == 1
    assert output["summary"]["routing_by_evidence_state"] == {
        "assessed": 2, "not_verified": 1,
    }
    assert output["summary"]["routing_by_projection_custody"] == {
        "embedded_unverified": 3
    }


def test_degraded_ospf_and_bgp_are_blockers_not_idealized_healthy_targets():
    snap = _snap({
        "ospf": [_ospf("10.0.0.2", "EXSTART/DROTHER")],
        "bgp": [_bgp("192.0.2.2", "Idle")],
    })

    cases = _routing_cases(compute_nrfu_commands(snap))

    ospf = cases["show ip ospf neighbor"]
    assert ospf["evidence_state"] == "degraded"
    assert ospf["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "EXSTART/DROTHER" in ospf["expected"]
    assert "matching this degraded state after cutover is not acceptance" in ospf["expected"].lower()
    bgp = cases["show ip bgp summary"]
    assert bgp["evidence_state"] == "not_verified"
    assert bgp["expected"].startswith("BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:")
    assert "do not infer Established" in bgp["expected"]
    assert "neighbor(s) in FULL" not in cases["show ip ospf neighbor"]["expected"]
    assert "neighbor(s) Established" not in cases["show ip bgp summary"]["expected"]


def test_partial_and_legacy_receipts_emit_not_verified_cases_instead_of_health_claims():
    routing = {"ospf": [_ospf("10.0.0.2", "FULL/DR")]}
    partial = _snap(routing, _receipt(states={"OSPF": "partial"}))
    legacy = _snap(routing, None)

    for snap in (partial, legacy):
        case = _routing_cases(compute_nrfu_commands(snap))["show ip ospf neighbor"]
        assert case["evidence_state"] == "not_verified"
        assert case["expected"].startswith("ROUTING BASELINE NOT VERIFIED — BLOCKER:")
        assert "10.0.0.2" in case["expected"]
        assert "neighbor(s) in FULL" not in case["expected"]


def test_assessed_zero_projection_is_an_explicit_review_case_not_an_omission():
    snap = _snap({}, _receipt(states={"OSPF": "assessed"}))

    case = _routing_cases(compute_nrfu_commands(snap))["show ip ospf neighbor"]

    assert case["evidence_state"] == "review"
    assert case["expected"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "zero peers" in case["expected"]


def test_malformed_receipt_and_projection_fail_closed_and_remain_total():
    routing = {"bgp": [_bgp("192.0.2.2", "12")]}
    malformed_receipt = _receipt(states={"BGP": "assessed"})
    malformed_receipt["summary"]["n_cells"] -= 1
    bad_receipt_snap = _snap(routing, malformed_receipt)

    bad_receipt_case = _routing_cases(
        compute_nrfu_commands(bad_receipt_snap)
    )["show ip bgp summary"]
    assert bad_receipt_case["evidence_state"] == "not_verified"
    assert bad_receipt_case["expected"].startswith(
        "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:")

    bad_projection_snap = _snap(
        {"bgp": [{"neighbor": "192.0.2.2", "as": "65002"}]},
        _receipt(states={"BGP": "assessed"}),
    )
    bad_projection_case = _routing_cases(
        compute_nrfu_commands(bad_projection_snap)
    )["show ip bgp summary"]
    assert bad_projection_case["evidence_state"] == "not_verified"
    assert bad_projection_case["expected"].startswith(
        "BGP CONFIGURED PEER NOT VERIFIED — BLOCKER:")
    assert "do not infer Established from a numeric summary token" in bad_projection_case["expected"]


def test_unscoped_empty_protocol_cells_do_not_invent_configured_protocol_blockers():
    snap = _snap({}, _receipt())
    assert _routing_cases(compute_nrfu_commands(snap)) == {}


def test_input_snapshot_is_not_mutated():
    snap = _snap({"ospf": [_ospf("10.0.0.2", "FULL/DR")]})
    before = deepcopy(snap)
    compute_nrfu_commands(snap)
    assert snap == before


def test_text_pack_discloses_routing_evidence_state_and_projection_custody(tmp_path):
    snap = _snap({"ospf": [_ospf("10.0.0.2", "EXSTART/DROTHER")]})

    written = write_nrfu_pack(snap, str(tmp_path))
    body = open(written[0], encoding="utf-8").read()

    assert "evidence_state: degraded" in body
    assert "projection_custody: embedded_unverified" in body
    assert "PRE-CUTOVER DEGRADED" in body
    assert "published receipt does not cryptographically bind projected peers" in body
