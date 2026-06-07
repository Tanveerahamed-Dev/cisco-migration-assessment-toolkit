"""NEW-V3.23.98: the migration scenario framework — per move-group cutover recommendation."""
from cisco_toolkit.analyze import compute_migration_scenarios


def test_migration_scenarios_recommends_per_group():
    mr = [
        {"group": "G1", "switches": ["a", "b", "c", "d", "e"], "endpoints": 50, "readiness": "READY", "n_fail": 0},
        {"group": "G2", "switches": ["x", "y"], "endpoints": 5, "readiness": "NOT READY", "n_fail": 2},
    ]
    ws = [
        {"group": "G1", "make_before_break": ["a", "b", "c", "d"], "hard_cutover": ["e"], "hard_cutover_endpoints": 2},
        {"group": "G2", "make_before_break": [], "hard_cutover": ["x", "y"], "hard_cutover_endpoints": 5},
    ]
    hs = [{"band": "Critical"}] * 7 + [{"band": "Good"}] * 3   # 70% Poor/Critical
    out = compute_migration_scenarios(mr, ws, hs)
    pg = {g["group"]: g for g in out["per_group"]}
    # G1: 5 switches, 80% dual-homed, READY, few at-risk -> parallel-run (build beside, cut leg-by-leg)
    assert pg["G1"]["recommended_scenario"] == "parallel-run" and pg["G1"]["dual_homed_pct"] == 80
    assert "pre" in pg["G1"]["playbook"] and "validate" in pg["G1"]["playbook"]
    # G2: NOT READY -> phased (resolve blockers first)
    assert pg["G2"]["recommended_scenario"] == "phased"
    # fleet broadly degraded -> greenfield consideration; scenario counts tallied
    assert "GREENFIELD" in out["fleet_recommendation"]
    assert out["scenario_counts"].get("parallel-run") == 1 and out["scenario_counts"].get("phased") == 1


def test_migration_scenarios_hard_cutover_forces_phased():
    # a READY, large, mostly-dual-homed group but with many single-homed at-risk endpoints -> phased
    mr = [{"group": "G", "switches": list("abcdef"), "endpoints": 20, "readiness": "READY", "n_fail": 0}]
    ws = [{"group": "G", "make_before_break": list("abcde"), "hard_cutover": ["f"], "hard_cutover_endpoints": 8}]
    out = compute_migration_scenarios(mr, ws, [])
    assert out["per_group"][0]["recommended_scenario"] == "phased"   # 8 >= 20*0.2 at-risk -> phased
    assert out["fleet_recommendation"] == ""                          # no health data -> no fleet note


def test_migration_scenarios_empty():
    out = compute_migration_scenarios([], [], [])
    assert out["per_group"] == [] and out["scenario_counts"] == {}
