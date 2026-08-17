"""NRFU STP-consistency cases project the shared receipt-gated owner verbatim."""

from __future__ import annotations

from copy import deepcopy

from cisco_toolkit.analyze import (
    PROTOCOL_ASSESSABILITY_FAMILIES,
    PROTOCOL_ASSESSABILITY_STATES,
    summarize_stp_consistency_baseline,
)
from cisco_toolkit.nrfu_export import NRFU_BANNER, compute_nrfu_commands


def test_banner_names_stp_consistency_not_verified_as_recollection_blocker():
    assert (
        "STP CONSISTENCY BASELINE NOT VERIFIED row requires re-collection"
        in NRFU_BANNER
    )


def _receipt(
    *,
    host: str = "sw1",
    state_input: str = "usable",
    blocked_input: str = "usable",
    inconsistent_input: str = "usable",
    emitted: bool = True,
) -> dict:
    rows = []
    by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for family in PROTOCOL_ASSESSABILITY_FAMILIES:
        protocol = family["protocol"]
        if protocol == "STP":
            input_states = {
                "state": state_input,
                "blocked_ports": blocked_input,
                "inconsistent_ports": inconsistent_input,
                "topology_changes": "missing",
            }
            required = [
                input_states[item["id"]]
                for item in family["inputs"]
                if item["required"]
            ]
            capture_state = (
                "usable" if "usable" in required else
                "error" if "error" in required else
                "empty" if "empty" in required else "missing"
            )
            incomplete = any(value != "usable" for value in required)
            if emitted:
                state = "partial" if incomplete else "assessed"
            elif capture_state == "usable" and incomplete:
                state = "partial"
            elif capture_state == "usable":
                state = "captured_no_record"
            elif capture_state == "error":
                state = "capture_error"
            elif capture_state == "empty":
                state = "captured_empty"
            else:
                state = "not_collected"
        else:
            input_states = {item["id"]: "missing" for item in family["inputs"]}
            capture_state = "missing"
            state = "not_collected"
        rows.append({
            "switch": host,
            "protocol": protocol,
            "input_states": input_states,
            "capture_state": capture_state,
            "health_row_emitted": emitted if protocol == "STP" else False,
            "state": state,
            "reason": f"fixture: {state}",
        })
        by_state[state] += 1

    return {
        "schema": "protocol_assessability/1",
        "families": [
            {"protocol": family["protocol"]}
            for family in PROTOCOL_ASSESSABILITY_FAMILIES
        ],
        "rows": rows,
        "summary": {
            "n_devices": 1,
            "n_families": len(PROTOCOL_ASSESSABILITY_FAMILIES),
            "n_cells": len(rows),
            "n_health_rows": sum(row["health_row_emitted"] for row in rows),
            "n_complete_devices": 0,
            "by_state": by_state,
        },
        "limitations": ["fixture"],
    }


def _health(severity: str = "Info", inconsistent: int = 0) -> list[dict]:
    return [{
        "switch": "sw1",
        "protocol": "STP",
        "severity": severity,
        "summary": f"mode rapid-pvst; 0 blocked, {inconsistent} inconsistent",
        "detail": "inconsistent: Gi1/0/1" if inconsistent else "",
    }]


def _snap(*, receipt: dict, health: list[dict], roots: bool = False) -> dict:
    snap = {
        "devices": {"sw1": {"platform": "ios"}},
        "interfaces": {"sw1": {}},
        "protocol_health": health,
        "protocol_assessability": receipt,
    }
    if roots:
        snap["stp_roots"] = {
            "sw1": {"10": {"is_root": True, "root_priority": 24586}}
        }
    return snap


def _stp_cases(output: dict) -> list[dict]:
    return [
        case
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "STP"
    ]


def _owner_row(snap: dict) -> dict:
    owner = summarize_stp_consistency_baseline(
        snap.get("protocol_health"), snap.get("protocol_assessability"),
        all_interfaces=snap.get("interfaces"), stp_roots=snap.get("stp_roots"),
    )
    assert len(owner["rows"]) == 1
    return owner["rows"][0]


def _assert_exact_projection(snap: dict, expected_state: str) -> tuple[dict, dict]:
    owner = _owner_row(snap)
    output = compute_nrfu_commands(snap)
    cases = _stp_cases(output)
    assert len(cases) == 1
    case = cases[0]
    assert owner["status"] == case["evidence_state"] == expected_state
    assert owner["command"] == case["command"]
    assert owner["acceptance"] == case["expected"]
    assert owner["source_key"] == case["source_key"]
    assert owner["projection_custody"] == case["projection_custody"]
    return case, output


def test_partial_inconsistent_port_evidence_is_a_blocker_not_a_zero_claim():
    snap = _snap(
        receipt=_receipt(inconsistent_input="empty"),
        health=_health(),
        roots=True,
    )

    owner = _owner_row(snap)
    case, output = _assert_exact_projection(snap, "review")

    assert case["expected"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "inconsistent" in case["expected"].lower()
    assert "0 inconsistent" not in case["expected"].lower()
    assert output["summary"]["n_stp_consistency_cases"] == 1
    assert output["summary"]["n_stp_consistency_blockers"] == 1
    assert output["summary"]["stp_consistency_by_evidence_state"] == {
        "review": 1
    }
    assert output["summary"]["stp_consistency_by_projection_custody"] == {
        owner["projection_custody"]: 1
    }
    # The independently supported root identity remains in Phase II; the new case complements it.
    all_commands = {
        case["command"]
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
    }
    assert "show spanning-tree vlan 10" in all_commands


def test_claim_specific_consistency_can_pass_when_only_blocked_port_input_is_partial():
    snap = _snap(
        receipt=_receipt(blocked_input="empty", inconsistent_input="usable"),
        health=_health(),
    )

    case, output = _assert_exact_projection(snap, "assessed")

    assert case["command"] == "show spanning-tree inconsistentports"
    assert "BLOCKER:" not in case["expected"]
    assert output["summary"]["n_stp_consistency_blockers"] == 0


def test_observed_inconsistency_is_degraded_and_never_idealized():
    snap = _snap(receipt=_receipt(), health=_health("High", inconsistent=1))

    case, output = _assert_exact_projection(snap, "degraded")

    assert case["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "STP High condition" in case["expected"]
    assert "no inconsistent ports" not in case["expected"].lower()
    assert output["summary"]["n_stp_consistency_blockers"] == 1


def test_no_stp_subject_is_neutral_and_input_is_not_mutated():
    snap = _snap(receipt=_receipt(emitted=False), health=[])
    before = deepcopy(snap)

    output = compute_nrfu_commands(snap)

    assert _stp_cases(output) == []
    assert output["summary"]["n_stp_consistency_cases"] == 0
    assert output["summary"]["n_stp_consistency_blockers"] == 0
    assert output["summary"]["stp_consistency_by_evidence_state"] == {}
    assert output["summary"]["stp_consistency_by_projection_custody"] == {}
    assert snap == before


def test_positive_l2_subject_with_uncollected_stp_emits_not_verified_blocker():
    snap = _snap(
        receipt=_receipt(
            state_input="missing",
            blocked_input="missing",
            inconsistent_input="missing",
            emitted=False,
        ),
        health=[],
    )
    snap["interfaces"] = {
        "sw1": {
            "Gi1/0/1": {
                "port": "Gi1/0/1",
                "switchport_mode": "Trunk",
                "stp_fwd_vlans": "10",
            }
        }
    }

    case, output = _assert_exact_projection(snap, "not_verified")

    assert case["expected"].startswith(
        "STP CONSISTENCY BASELINE NOT VERIFIED — BLOCKER:"
    )
    assert output["summary"]["n_stp_consistency_blockers"] == 1
