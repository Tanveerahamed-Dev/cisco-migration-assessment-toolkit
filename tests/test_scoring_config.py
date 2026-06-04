"""PHASE 2.1: ScoringConfig externalization.

Two things to lock in:
  1. the default config reproduces the prior hard-coded baseline, and
  2. the config is actually *wired* - a custom config changes the output (so a
     later refactor can't silently disconnect it).
"""
from cisco_toolkit import analyze   # ScoringConfig / SCORING live here since PHASE 2.7 step 15


def test_default_config_matches_baseline(cp):
    s = analyze.SCORING
    assert s.l1_weights == {"err-disabled": 8, "single-fiber-uplink": 10,
                            "error-rate-high": 5, "half-duplex": 8}
    assert s.l3_weights == {"single-gateway": 10, "no-FHRP": 3, "tracked-object-down": 12}
    assert s.xl_weights == {"Critical": 18, "High": 10, "Medium": 4, "Low": 2}
    assert s.proto_weights == {"High": 10, "Medium": 4}
    assert s.caps == {"L1": 30, "L3": 30, "XL": 45, "PROTO": 25}
    assert s.bands == [(90, "Excellent", "36E08A"), (75, "Good", "7ADB8F"),
                       (60, "Fair", "FFE566"), (40, "Poor", "FF9F45"), (0, "Critical", "FF5775")]
    assert s.readiness["gateway_redundancy"] == "fail"
    assert s.readiness["redundant_uplinks"] == "warn"


def test_custom_weight_changes_score(cp):
    ph = [{"switch": "h", "port": "Gi0/1", "risk": "single-fiber-uplink"}]
    base = cp.compute_health_scores({"h": {}}, ph, [], [], [])
    assert base[0]["score"] == 90                       # default -10
    cfg = analyze.ScoringConfig(l1_weights={"single-fiber-uplink": 25})
    custom = cp.compute_health_scores({"h": {}}, ph, [], [], [], config=cfg)
    assert custom[0]["score"] == 75                     # now -25


def test_custom_cap_changes_capping(cp):
    ph = [{"switch": "h", "port": f"Gi0/{i}", "risk": "err-disabled"} for i in range(5)]  # 5*8=40
    assert cp.compute_health_scores({"h": {}}, ph, [], [], [])[0]["score"] == 70   # L1 cap 30
    cfg = analyze.ScoringConfig(caps={"L1": 50, "L3": 30, "XL": 45, "PROTO": 25})
    assert cp.compute_health_scores({"h": {}}, ph, [], [], [], config=cfg)[0]["score"] == 60  # 40 uncapped


def test_custom_bands_change_label(cp):
    # Stricter bands: 90 is no longer "Excellent".
    cfg = analyze.ScoringConfig(bands=[(95, "Excellent", "x"), (0, "Critical", "y")])
    ph = [{"switch": "h", "port": "p", "risk": "single-fiber-uplink"}]   # -10 -> 90
    rec = cp.compute_health_scores({"h": {}}, ph, [], [], [], config=cfg)[0]
    assert rec["score"] == 90 and rec["band"] == "Critical"


def test_readiness_rule_is_configurable(cp):
    move_groups = [{"switches": ["a"], "endpoints": 0}]
    health = [{"switch": "a", "band": "Excellent"}]
    dep = cp._empty_dep_map()
    dep["sole_gw"] = {30: "a"}                            # triggers gateway-redundancy check
    base = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], dep)
    assert base[0]["readiness"] == "NOT READY"           # default: gateway_redundancy = fail
    cfg = analyze.ScoringConfig(readiness={**analyze.SCORING.readiness, "gateway_redundancy": "warn"})
    custom = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], dep, config=cfg)
    assert custom[0]["readiness"] == "CAUTION"            # downgraded fail -> warn
