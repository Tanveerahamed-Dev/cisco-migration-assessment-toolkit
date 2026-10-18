"""Hosted-only counterexamples for the single pre-change wave decision owner."""
from copy import deepcopy
import sys
from pathlib import Path

import pytest

from cisco_toolkit import analyze, mop


def _snapshot():
    row = {
        "device": "sw1", "platform": "ios", "wave": "G1", "category": "Routing",
        "severity": "High", "check": "Observed adjacency", "command": "show ip ospf neighbor",
        "expect": "Peer remains FULL", "why": "Detect regression", "evidence_state": "assessed",
        "projection_custody": "embedded_unverified", "source_key": "routing.sw1",
    }
    return {
        "devices": {"sw1": {}},
        "migration_readiness": [{
            "group": "G1", "switches": ["sw1"], "readiness": "READY", "n_fail": 0, "n_warn": 0,
            "checks": [{"check": "Baseline capture", "status": "pass", "note": "Counters observed"},
                       {"check": "Rollback plan documented", "status": "info", "note": "manual: confirm rollback"}],
        }],
        "wave_sequencing": [{"group": "G1", "make_before_break": ["sw1"], "hard_cutover": [],
                             "hard_cutover_endpoints": 0}],
        "move_groups": [{"group": "G1", "switches": ["sw1"], "endpoints": 0}],
        "health_scores": [{"switch": "sw1", "band": "Good", "data_quality": 1.0}],
        "cross_layer": [], "punchlist": [], "remediation_plan": {"items": [], "by_device": {}},
        "validation_plan": {"items": [row], "by_wave": {"G1": [deepcopy(row)]},
                            "summary": {"n_items": 1, "n_waves": 1, "by_category": {"Routing": 1}, "n_high": 1}},
    }


def _decision(snapshot):
    return analyze.compute_wave_cutover_gate(snapshot, ["G1"], ["sw1"])


def test_positive_control_is_bounded_go_and_does_not_mutate_source():
    snap = _snapshot()
    before = deepcopy(snap)
    result = _decision(snap)
    assert result["verdict"] == "GO"
    assert result["coverage"] == {"complete": True, "gaps": []}
    assert result["current_baseline"]["verdict"] == "CLEAR"
    assert snap == before
    result["scope"]["switches"].append("foreign")
    assert _decision(snap)["scope"]["switches"] == ["sw1"]


@pytest.mark.parametrize("counterexample", ["ready_critical", "not_ready_zero", "ready_failing_check"])
def test_previously_divergent_rule_sets_keep_every_negative_witness(counterexample):
    snap = _snapshot()
    if counterexample == "ready_critical":
        # Old MOP: READY; old AssessHub: NO-GO.
        snap["cross_layer"] = [{"severity": "Critical", "hosts": ["sw1"]}]
    elif counterexample == "not_ready_zero":
        # Old AssessHub count-only path: GO; old MOP: NOT READY.
        snap["migration_readiness"][0]["readiness"] = "NOT READY"
    else:
        # A stale zero count cannot erase an actual failing check.
        snap["migration_readiness"][0]["checks"][0]["status"] = "fail"
    assert _decision(snap)["verdict"] == "NO-GO"


@pytest.mark.parametrize("count", ["1", 1.0, 1.5, True])
def test_legacy_coercible_positive_count_remains_a_negative_witness(count):
    snap = _snapshot()
    snap["migration_readiness"][0]["n_fail"] = count
    result = _decision(snap)
    assert result["verdict"] == "NO-GO"
    assert result["coverage"]["complete"] is False


def test_legacy_lowercase_negative_label_cannot_become_a_weaker_gate():
    snap = _snapshot()
    snap["migration_readiness"][0]["readiness"] = "not ready"
    assert _decision(snap)["verdict"] == "NO-GO"


@pytest.mark.parametrize("section", ["devices", "migration_readiness", "health_scores", "cross_layer",
                                     "remediation_plan", "punchlist", "validation_plan"])
@pytest.mark.parametrize("replacement", [None, 17, "unreadable", {}])
def test_missing_or_malformed_evidence_never_becomes_go(section, replacement):
    snap = _snapshot()
    snap[section] = replacement
    result = _decision(snap)
    assert result["verdict"] != "GO"
    assert result["coverage"]["complete"] is False


@pytest.mark.parametrize("mutation", ["unknown_label", "missing_count", "bool_count", "unknown_check",
                                     "empty_checks", "bare_pass", "unobserved_info", "all_info", "duplicate"])
def test_readiness_requires_recognized_nonvacuous_evidence(mutation):
    snap = _snapshot()
    row = snap["migration_readiness"][0]
    if mutation == "unknown_label":
        row["readiness"] = "future-ready"
    elif mutation == "missing_count":
        del row["n_fail"]
    elif mutation == "bool_count":
        row["n_fail"] = False
    elif mutation == "unknown_check":
        row["checks"][0]["status"] = "unknown"
    elif mutation == "empty_checks":
        row["checks"] = []
    elif mutation == "bare_pass":
        row["checks"] = [{"status": "pass"}]
    elif mutation == "unobserved_info":
        row["checks"][1]["note"] = "NOT ASSESSABLE — no topology collected"
    elif mutation == "all_info":
        row["checks"][0]["status"] = "info"
    else:
        snap["migration_readiness"].append(deepcopy(row))
    assert _decision(snap)["verdict"] == "CONDITIONAL GO"


@pytest.mark.parametrize("bad_scope", [[["sw1"]], ["sw1", {}], 12, None])
def test_malformed_critical_scope_is_never_a_clean_disjoint_row(bad_scope):
    snap = _snapshot()
    snap["cross_layer"] = [{"severity": "Critical", "hosts": bad_scope}]
    result = _decision(snap)
    assert result["verdict"] == "NO-GO"
    assert result["coverage"]["complete"] is False


def test_remediation_mirror_is_not_a_second_finding_but_real_duplicates_survive():
    snap = _snapshot()
    item = {"device": "sw1", "severity": "High", "title": "Repair uplink"}
    snap["remediation_plan"] = {"items": [item], "by_device": {"sw1": [deepcopy(item)]}}
    result = _decision(snap)
    assert result["counts"]["n_high_remediation"] == 1
    assert result["verdict"] == "CONDITIONAL GO"
    snap["remediation_plan"]["items"].append(deepcopy(item))
    snap["remediation_plan"]["by_device"]["sw1"].append(deepcopy(item))
    assert _decision(snap)["counts"]["n_high_remediation"] == 2


def test_punchlist_uses_canonical_device_scope_without_gating_disjoint_wave():
    snap = _snapshot()
    snap["punchlist"] = [{"devices": ["elsewhere"], "severity": "High"}]
    assert _decision(snap)["verdict"] == "GO"
    snap["punchlist"][0]["devices"] = ["sw1"]
    assert _decision(snap)["verdict"] == "CONDITIONAL GO"


@pytest.mark.parametrize("quality", [0, 0.5, 2, True, None, float("nan"), float("inf")])
def test_unobserved_partial_or_invalid_collection_is_not_complete(quality):
    snap = _snapshot()
    snap["health_scores"][0]["data_quality"] = quality
    result = _decision(snap)
    assert result["verdict"] == "CONDITIONAL GO"
    assert result["coverage"]["complete"] is False


def test_unbound_baseline_blocker_holds_every_window_and_rollup():
    snap = _snapshot()
    row = snap["validation_plan"]["items"][0]
    row.update(device="unscheduled", wave="unbound", evidence_state="degraded")
    snap["validation_plan"]["by_wave"] = {"unbound": [deepcopy(row)]}
    assert _decision(snap)["verdict"] == "NO-GO"
    assert analyze.rollup_wave_cutover_gates(snap, [("wave", ["sw1"], "move-group", ["G1"])])["verdict"] == "NO-GO"


def test_split_group_cannot_apportion_its_blocker_out_of_another_slice():
    snap = _snapshot()
    row = snap["migration_readiness"][0]
    row.update(switches=["sw1", "sw2"], n_fail=1, readiness="NOT READY")
    row["checks"].append({"check": "Topology", "status": "fail", "note": "sw1 lacks uplink"})
    for hosts in (["sw1"], ["sw2"], ["sw1", "sw2"]):
        assert analyze.compute_wave_cutover_gate(snap, ["G1"], hosts)["verdict"] == "NO-GO"


@pytest.mark.parametrize("integrity", [5, {"failed_phases": {}}, {"failed_phases": ["unknown-phase"]},
                                       {"cross_layer": "compute_failed"}])
def test_failed_phase_fallback_is_not_a_clean_empty_findings_set(integrity):
    snap = _snapshot()
    snap["assessment_integrity"] = integrity
    assert _decision(snap)["verdict"] == "CONDITIONAL GO"
    assert _decision(snap)["coverage"]["complete"] is False


def test_empty_scope_and_empty_schedule_are_not_assessed():
    assert analyze.compute_wave_cutover_gate({}, [], [])["verdict"] == "NOT ASSESSED"
    assert analyze.rollup_wave_cutover_gates({}, [])["verdict"] == "NOT ASSESSED"


def test_assesshub_and_mop_display_identical_owner_verdict_for_identical_scope(tmp_path):
    docx = pytest.importorskip("docx")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
    from backend import cutover, engine
    from backend.cutover_docx import write_cutover_docx

    snap = _snapshot()
    snap["cross_layer"] = [{"severity": "Critical", "hosts": ["sw1"]}]
    expected = _decision(snap)
    plan = cutover.build_plan(snap)
    assert engine.wave_cutover(snap, ["G1"], ["sw1"]) == expected
    assert plan["waves"][0]["gate_evidence"] == expected
    assert plan["waves"][0]["gate"] == plan["summary"]["verdict"] == expected["verdict"]
    for writer, filename, label in ((mop.write_mop_docx, "mop.docx", "Engine cutover gate"),
                                    (write_cutover_docx, "cutover.docx", "Gate:")):
        path = tmp_path / filename
        writer(str(path), snap, "Synthetic gate parity")
        document = docx.Document(path)
        text = "\n".join([p.text for p in document.paragraphs] +
                         [c.text for t in document.tables for r in t.rows for c in r.cells])
        assert label in text and "NO-GO" in text
        assert expected["reasons"][0] in text
