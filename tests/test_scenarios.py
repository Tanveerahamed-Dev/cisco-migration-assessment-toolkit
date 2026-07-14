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


def test_migration_scenarios_pct_excludes_uncollected_devices():
    """[audit-6 correctness] The Poor/Critical share drives the greenfield-vs-in-place fleet recommendation at
    a 60% gate. An 'Insufficient Data' row is an UNCOLLECTED device (no evidence -> no deductions -> never
    banded Poor/Critical); counting it in the denominator DILUTES the degradation % and can flip the verdict.
    Here 4 of 6 ASSESSED switches are Poor/Critical (67% -> GREENFIELD), but 4 uncollected devices would drag
    it to 4/10 = 40% -> in-place. The recommendation must be computed over assessed switches only, matching
    the executive-brief convention. NON-VACUOUS: before the fix the output says '40%' / 'in-place' and these
    assertions fail."""
    hs = ([{"band": "Critical"}] * 3 + [{"band": "Poor"}] * 1 +      # 4 Poor/Critical assessed ...
          [{"band": "Good"}] * 2 +                                    # + 2 Good assessed -> 4/6 = 67%
          [{"band": "Insufficient Data"}] * 4)                        # 4 uncollected (must NOT dilute)
    rec = compute_migration_scenarios([], [], hs)["fleet_recommendation"]
    assert "67%" in rec and "GREENFIELD" in rec, rec                  # assessed-only 67%, not diluted 40%
    assert "in-place" not in rec
    # an ALL-uncollected fleet has no assessed switches -> no percentage claimed at all (never a false '0%')
    allunk = compute_migration_scenarios([], [], [{"band": "Insufficient Data"}] * 5)["fleet_recommendation"]
    assert allunk == ""
