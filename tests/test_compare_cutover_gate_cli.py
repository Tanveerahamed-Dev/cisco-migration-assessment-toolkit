"""One combined --compare verdict owns workbook, terminal, and opt-in exit behavior."""
import json
import os
import subprocess
import sys

import pytest
from openpyxl import load_workbook

from cisco_toolkit.html import (compute_cutover_gate, compute_snapshot_delta,
                                write_diff_workbook)
from cisco_toolkit.precert import compute_precert


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")
FAMILIES = ("STP", "EtherChannel", "VTP", "OSPF", "BGP", "EIGRP", "FHRP")


def _routes():
    return {
        "R1": [
            {"prefix": "10.1.1.0/24", "source": "connected", "out_intf": "Vlan10"},
            {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
            {"prefix": "10.2.2.0/24", "source": "ospf", "next_hop": "10.0.12.2",
             "out_intf": "Gi0/1"},
        ],
        "R2": [
            {"prefix": "10.2.2.0/24", "source": "connected", "out_intf": "Vlan20"},
            {"prefix": "10.0.12.0/30", "source": "connected", "out_intf": "Gi0/1"},
            {"prefix": "10.1.1.0/24", "source": "ospf", "next_hop": "10.0.12.1",
             "out_intf": "Gi0/1"},
        ],
    }


def _interfaces():
    return {
        "R1": {"Vlan10": {"svi_ip": "10.1.1.1/24"},
               "Gi0/1": {"svi_ip": "10.0.12.1/30"}},
        "R2": {"Gi0/1": {"svi_ip": "10.0.12.2/30"},
               "Vlan20": {"svi_ip": "10.2.2.1/24"}},
    }


def _receipt():
    rows = []
    for family in FAMILIES:
        assessed = family == "OSPF"
        rows.append({
            "switch": "R1",
            "protocol": family,
            "state": "assessed" if assessed else "not_collected",
            "health_row_emitted": assessed,
        })
    return {
        "schema": "protocol_assessability/1",
        "families": [{"protocol": family} for family in FAMILIES],
        "rows": rows,
        "summary": {"n_devices": 1, "n_families": len(FAMILIES), "n_cells": len(rows)},
    }


def _clean_validation_plan():
    item = {
        "device": "R1", "platform": "ios", "wave": "Group 1",
        "category": "Gateway", "severity": "High", "check": "Gateway remains up",
        "command": "show ip interface brief", "expect": "Vlan10 remains up/up",
        "why": "Preserve the observed gateway.",
    }
    return {
        "items": [item], "by_wave": {"Group 1": [item]},
        "summary": {"n_items": 1, "n_waves": 1, "by_category": {"Gateway": 1}, "n_high": 1},
        "banner": "bounded plan",
    }


def _degraded_validation_plan():
    item = {
        "device": "R1", "platform": "ios", "wave": "Group 1",
        "category": "Routing", "severity": "High", "check": "OSPF degraded adjacency baseline",
        "command": "show ip ospf neighbor",
        "expect": ("PRE-CUTOVER DEGRADED — BLOCKER: OSPF peer 10.0.12.2 is EXSTART/DR. "
                   "Matching this degraded state is NOT ACCEPTANCE."),
        "why": "The current observed adjacency is already degraded.",
        "evidence_state": "degraded", "projection_custody": "embedded_unverified",
        "source_key": "routing_neighbors.R1.ospf + protocol_assessability.rows[R1,OSPF]",
    }
    return {
        "items": [item], "by_wave": {"Group 1": [item]},
        "summary": {"n_items": 1, "n_waves": 1, "by_category": {"Routing": 1}, "n_high": 1},
        "banner": "bounded plan",
    }


def _snapshot(ospf_state, generated_at):
    return {
        "schema": "collect_parse_snapshot/1",
        "script_version": "V3.23.0",
        "generated_at": generated_at,
        "devices": {"R1": {}, "R2": {}},
        "interfaces": _interfaces(),
        "routes": _routes(),
        "segmentation": {
            "vrfs": [{"vrf": "(global)", "gateway_count": 1},
                     {"vrf": "PCI", "gateway_count": 2}],
            "domains": [{"domain": "payments", "tier": "on-air-critical", "isolated": True,
                         "exposure": "Every gateway has a dedicated VRF or a gateway ACL."}],
        },
        "health_scores": [
            {"switch": "R1", "band": "Good", "score": 92},
            {"switch": "R2", "band": "Good", "score": 92},
        ],
        "punchlist": [],
        "validation_plan": _clean_validation_plan(),
        "protocol_assessability": _receipt(),
        "routing_neighbors": {
            "R1": {"ospf": [{"neighbor": "10.0.12.2", "state": ospf_state,
                               "interface": "Gi0/1", "address": "10.0.12.2"}]},
        },
    }


def _workbook_gate(path):
    ws = load_workbook(path, read_only=True)["Summary"]
    rows = {ws.cell(row, 1).value: ws.cell(row, 3).value for row in range(2, ws.max_row + 1)}
    return rows["CUTOVER GATE VERDICT"]


@pytest.mark.parametrize(
    ("delta_verdict", "certificate_verdict", "expected"),
    [
        ("REGRESSED", "FAIL", "REGRESSED"),
        ("CLEAN", "FAIL", "FAIL"),
        ("INDETERMINATE", "FAIL", "FAIL"),
        ("INDETERMINATE", "PASS", "INDETERMINATE"),
        ("REVIEW", "CONDITIONAL", "REVIEW"),
        ("CLEAN", "CONDITIONAL", "CONDITIONAL"),
        ("CLEAN", "PASS", "PASS"),
    ],
)
def test_compute_cutover_gate_preserves_precedence(delta_verdict, certificate_verdict, expected):
    protocol_gate = ("REGRESSED" if delta_verdict == "REGRESSED" else
                     "REVIEW" if delta_verdict == "REVIEW" else "PASS")
    protocol_regressions = 2 if protocol_gate == "REGRESSED" else 0
    protocol_coverage_gaps = 1 if protocol_gate == "REVIEW" else 0
    protocol_baseline_peers = 2 if protocol_gate != "PASS" else 0
    delta = {
        "verdict": delta_verdict,
        "verdict_display": "NO DELTA REGRESSION OBSERVED" if delta_verdict == "CLEAN" else delta_verdict,
        "verdict_note": "delta note",
        "protocol_adjacencies": {
            "gate": protocol_gate,
            "summary": {"n_state_regressed": protocol_regressions,
                        "n_coverage_gaps": protocol_coverage_gaps,
                        "n_baseline_peers": protocol_baseline_peers},
        },
    }
    certificate = {"verdict": certificate_verdict, "verdict_note": "certificate note"}
    decision = compute_cutover_gate(delta, certificate)

    assert decision == {
        "schema": "cutover_gate/1",
        "verdict": expected,
        "note": (f"Delta observation: {delta['verdict_display']}. Delta basis: delta note "
                 f"Pre-Change Certificate: {certificate_verdict}. "
                 "Certificate basis: certificate note"),
        "operator_note": decision["operator_note"],
        "delta_verdict": delta_verdict,
        "delta_display": delta["verdict_display"],
        "delta_note": "delta note",
        "certificate_verdict": certificate_verdict,
        "certificate_note": "certificate note",
        "protocol_gate": protocol_gate,
        "protocol_baseline_peers": protocol_baseline_peers,
        "protocol_regressions": protocol_regressions,
        "protocol_coverage_gaps": protocol_coverage_gaps,
    }
    assert decision["operator_note"].startswith(f"Overall before/after cutover decision: {expected}.")


@pytest.mark.parametrize(
    ("protocol_gate", "regressions", "expected"),
    [("REGRESSED", 1, "REGRESSED"), ("PASS", 1, "REGRESSED"), ("REVIEW", 0, "REVIEW")],
)
def test_cutover_gate_never_passes_over_a_stricter_nested_protocol_result(
        protocol_gate, regressions, expected):
    decision = compute_cutover_gate(
        {
            "verdict": "CLEAN",
            "verdict_display": "NO DELTA REGRESSION OBSERVED",
            "verdict_note": "contradictory outer delta",
            "protocol_adjacencies": {
                "gate": protocol_gate,
                "summary": {"n_baseline_peers": 1, "n_state_regressed": regressions,
                            "n_coverage_gaps": 0},
            },
        },
        {"verdict": "PASS", "verdict_note": "bounded certificate"},
    )

    assert decision["verdict"] == expected
    assert decision["delta_verdict"] == expected
    assert decision["delta_display"] == expected


def test_cutover_gate_keeps_integrity_indeterminate_over_an_apparent_protocol_regression():
    decision = compute_cutover_gate(
        {
            "verdict": "INDETERMINATE",
            "verdict_display": "INDETERMINATE",
            "verdict_note": "Cross-schema comparison; observations are apparent only.",
            "protocol_adjacencies": {
                "gate": "REGRESSED",
                "summary": {"n_baseline_peers": 1, "n_state_regressed": 1,
                            "n_coverage_gaps": 0},
            },
        },
        {"verdict": "CONDITIONAL", "verdict_note": "schema mismatch"},
    )

    assert decision["verdict"] == "INDETERMINATE"
    assert decision["delta_verdict"] == "INDETERMINATE"
    assert "proven" not in decision["operator_note"]


def test_cutover_gate_withholds_pass_for_legacy_receipt_when_baseline_peers_exist():
    decision = compute_cutover_gate(
        {
            "verdict": "CLEAN",
            "verdict_display": "NO DELTA REGRESSION OBSERVED",
            "verdict_note": "other axes clean",
            "protocol_adjacencies": {
                "gate": "NOT_ASSESSED",
                "assessed": False,
                "summary": {"n_baseline_peers": 1, "n_state_regressed": 0,
                            "n_coverage_gaps": 1},
            },
        },
        {"verdict": "PASS", "verdict_note": "bounded certificate"},
    )

    assert decision["verdict"] == "INDETERMINATE"
    assert decision["protocol_baseline_peers"] == 1
    assert "re-collect protocol evidence" in decision["operator_note"]


def test_write_diff_workbook_returns_the_exact_public_decision(tmp_path):
    before = _snapshot("FULL/DR", "2026-08-15T00:00:00")
    after = _snapshot("EXSTART/DR", "2026-08-15T00:05:00")
    certificate = compute_precert(before, after)
    delta = compute_snapshot_delta(before, after)
    expected = compute_cutover_gate(delta, certificate)
    out = tmp_path / "returned-gate.xlsx"

    actual = write_diff_workbook(before, after, str(out), precert=certificate)

    assert actual == expected
    assert actual["certificate_verdict"] == "PASS"
    assert actual["verdict"] == "REGRESSED"
    assert actual["protocol_baseline_peers"] == 1
    assert actual["protocol_regressions"] == 1
    assert _workbook_gate(str(out)) == actual["verdict"]


def test_compare_cli_enforcement_rejects_an_unchanged_degraded_current_baseline(tmp_path):
    before = _snapshot("EXSTART/DR", "2026-08-15T00:00:00")
    after = _snapshot("EXSTART/DR", "2026-08-15T00:05:00")
    before["validation_plan"] = _degraded_validation_plan()
    after["validation_plan"] = _degraded_validation_plan()
    before_path = tmp_path / "unchanged-before.snapshot.json"
    after_path = tmp_path / "unchanged-after.snapshot.json"
    output = tmp_path / "unchanged-degraded.xlsx"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    after_path.write_text(json.dumps(after), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, SCRIPT, "--compare", str(before_path), str(after_path),
         "--output", str(output), "--fail-on-compare-gate"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
    )
    terminal = process.stdout + process.stderr

    assert process.returncode == 2, terminal
    assert output.exists()
    assert _workbook_gate(str(output)) == "FAIL"
    assert "[CUTOVER GATE: FAIL]" in terminal
    assert "current-baseline degradation" in terminal


def test_compare_cli_reports_combined_gate_and_enforces_only_when_requested(tmp_path):
    before = _snapshot("FULL/DR", "2026-08-15T00:00:00")
    regressed = _snapshot("EXSTART/DR", "2026-08-15T00:05:00")
    clean = _snapshot("FULL/BDR", "2026-08-15T00:05:00")
    before_path = tmp_path / "before.snapshot.json"
    regressed_path = tmp_path / "regressed.snapshot.json"
    clean_path = tmp_path / "clean.snapshot.json"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    regressed_path.write_text(json.dumps(regressed), encoding="utf-8")
    clean_path.write_text(json.dumps(clean), encoding="utf-8")

    def run(after_path, name, enforce=False, before=before_path, extra_args=()):
        out = tmp_path / f"{name}.xlsx"
        cmd = [sys.executable, SCRIPT, "--compare", str(before), str(after_path),
               "--output", str(out)]
        cmd.extend(extra_args)
        if enforce:
            cmd.append("--fail-on-compare-gate")
        proc = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
        return proc, out, tmp_path / f"{name}.precert.json"

    default_proc, default_out, default_cert_path = run(regressed_path, "default-regression")
    default_terminal = default_proc.stdout + default_proc.stderr
    assert default_proc.returncode == 0, default_terminal
    assert default_out.exists() and default_cert_path.exists()
    assert json.loads(default_cert_path.read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert _workbook_gate(str(default_out)) == "REGRESSED"
    assert "[CUTOVER GATE: REGRESSED]" in default_terminal
    scope = ("[CERTIFICATE SCOPE] Pre-Change Certificate: PASS. It covers bounded FIB/path-intent "
             "checks only and cannot override the overall cutover gate.")
    assert scope in default_terminal
    assert default_terminal.index("[CUTOVER GATE: REGRESSED]") < default_terminal.index(scope)

    enforced_proc, enforced_out, enforced_cert_path = run(
        regressed_path, "enforced-regression", enforce=True)
    enforced_terminal = enforced_proc.stdout + enforced_proc.stderr
    assert enforced_proc.returncode == 2, enforced_terminal
    assert enforced_out.exists() and enforced_cert_path.exists(), "enforcement happens after artifact writes"
    assert _workbook_gate(str(enforced_out)) == "REGRESSED"
    assert "[COMPARE GATE ENFORCED] Artifacts were written" in enforced_terminal

    clean_proc, clean_out, clean_cert_path = run(clean_path, "enforced-pass", enforce=True)
    clean_terminal = clean_proc.stdout + clean_proc.stderr
    assert clean_proc.returncode == 0, clean_terminal
    assert clean_out.exists() and clean_cert_path.exists()
    assert _workbook_gate(str(clean_out)) == "PASS"
    assert "[CUTOVER GATE: PASS]" in clean_terminal

    legacy_before = _snapshot("FULL/DR", "2026-08-15T00:00:00")
    legacy_after = _snapshot("FULL/DR", "2026-08-15T00:05:00")
    legacy_before.pop("protocol_assessability")
    legacy_after.pop("protocol_assessability")
    legacy_before_path = tmp_path / "legacy-before.snapshot.json"
    legacy_after_path = tmp_path / "legacy-after.snapshot.json"
    legacy_before_path.write_text(json.dumps(legacy_before), encoding="utf-8")
    legacy_after_path.write_text(json.dumps(legacy_after), encoding="utf-8")
    legacy_proc, legacy_out, legacy_cert_path = run(
        legacy_after_path, "enforced-legacy", enforce=True, before=legacy_before_path)
    legacy_terminal = legacy_proc.stdout + legacy_proc.stderr
    assert legacy_proc.returncode == 2, legacy_terminal
    assert legacy_out.exists() and legacy_cert_path.exists()
    assert _workbook_gate(str(legacy_out)) == "INDETERMINATE"
    assert "[CUTOVER GATE: INDETERMINATE]" in legacy_terminal

    mismatched = _snapshot("EXSTART/DR", "2026-08-15T00:05:00")
    mismatched["script_version"] = "V9.9.9"
    mismatched_path = tmp_path / "mismatched.snapshot.json"
    mismatched_path.write_text(json.dumps(mismatched), encoding="utf-8")
    mismatch_proc, mismatch_out, mismatch_cert_path = run(
        mismatched_path, "enforced-mismatch", enforce=True,
        extra_args=("--allow-schema-mismatch",))
    mismatch_terminal = mismatch_proc.stdout + mismatch_proc.stderr
    assert mismatch_proc.returncode == 2, mismatch_terminal
    assert mismatch_out.exists() and mismatch_cert_path.exists()
    assert _workbook_gate(str(mismatch_out)) == "INDETERMINATE"
    assert "[CUTOVER GATE: INDETERMINATE]" in mismatch_terminal

    health_regressed = _snapshot("FULL/DR", "2026-08-15T00:05:00")
    health_regressed["health_scores"][0].update({"band": "Poor", "score": 45})
    health_regressed_path = tmp_path / "health-regressed.snapshot.json"
    health_regressed_path.write_text(json.dumps(health_regressed), encoding="utf-8")
    health_proc, health_out, health_cert_path = run(
        health_regressed_path, "health-regression")
    health_terminal = health_proc.stdout + health_proc.stderr
    assert health_proc.returncode == 0, health_terminal
    assert health_out.exists() and health_cert_path.exists()
    assert _workbook_gate(str(health_out)) == "REGRESSED"
    assert "[CUTOVER GATE: REGRESSED]" in health_terminal
    assert "Delta basis:" in health_terminal
    assert "1 switch(es) dropped a health band" in health_terminal


def test_fail_on_compare_gate_requires_compare(tmp_path):
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--fail-on-compare-gate"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    assert "--fail-on-compare-gate requires --compare OLD_SNAPSHOT NEW_SNAPSHOT" in (
        proc.stdout + proc.stderr)
