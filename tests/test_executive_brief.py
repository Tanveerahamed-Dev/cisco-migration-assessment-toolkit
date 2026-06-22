"""NEW-V3.23.120: the cross-axis executive brief -- one headline per assessment axis rolled up into one
decision-grade synthesis. Pure read of layer summaries; deterministic given inputs (no date math here)."""
import json

from cisco_toolkit.analyze import compute_executive_brief

_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _full():
    return dict(
        health_scores=[{"band": "Critical", "score": 10}, {"band": "Good", "score": 80}],
        punchlist=[{"severity": "Critical"}, {"severity": "High"}],
        migration_readiness=[{"readiness": "NOT READY"}, {"readiness": "READY"}],
        application_intelligence={"summary": {"n_domains": 11, "n_on_air_critical": 4, "n_high_risk": 2,
                                              "n_edges": 31, "keystone_domain": "General",
                                              "pilot_domain": "Investigative", "last_domain": "Media Fabric"},
                                  "domains": [{"endpoint_count": 100}, {"endpoint_count": 50}]},
        lifecycle_risk={"summary": {"n_devices": 200, "n_past_ldos": 151, "n_near": 9}},
        segmentation={"summary": {"n_gateways": 232, "flat": True, "n_oncrit_exposed": 3,
                                  "gateway_acl_coverage": 0.0}},
        multicast_intelligence={"summary": {"n_groups": 73, "n_av_groups": 44, "n_mac_clashes": 1,
                                            "n_ptp_clocks": 13, "n_ptp_dormant": 13, "n_querier_gaps": 0}},
        remediation_plan={"summary": {"n_items": 891, "n_devices": 255}})


def test_axes_headlines_and_severity():
    b = compute_executive_brief(**_full())
    axes = {a["axis"]: a for a in b["axes"]}
    assert axes["Hardware lifecycle (EoL)"]["severity"] == "Critical"
    assert "151 past end-of-support" in axes["Hardware lifecycle (EoL)"]["headline"]
    assert axes["Segmentation"]["severity"] == "High" and "flat L3" in axes["Segmentation"]["headline"]
    assert axes["Multicast / timing"]["severity"] == "High"          # the MAC clash
    assert "Media Fabric" in axes["Cutover sequence"]["headline"]
    assert axes["Remediation"]["severity"] == "Info"
    assert b["scale"] == {"n_devices": 2, "n_domains": 11, "n_endpoints": 150}


def test_axes_ranked_and_top_gating_is_high_only():
    b = compute_executive_brief(**_full())
    ranks = [_RANK[a["severity"]] for a in b["axes"]]
    assert ranks == sorted(ranks)                                     # severity-ranked
    high_heads = {a["headline"] for a in b["axes"] if a["severity"] in ("Critical", "High")}
    low_heads = {a["headline"] for a in b["axes"] if a["severity"] in ("Medium", "Low", "Info")}
    assert b["top_gating"] and set(b["top_gating"]) <= high_heads
    assert not (set(b["top_gating"]) & low_heads)


def test_posture_statement_assembles_from_flags():
    ps = compute_executive_brief(**_full())["posture_statement"]
    assert "end-of-support" in ps and "flat" in ps and "boundary-clocked" in ps and "MAC-address clash" in ps


def test_clean_fleet_has_no_blockers():
    b = compute_executive_brief(
        health_scores=[{"band": "Good", "score": 85}],
        segmentation={"summary": {"n_gateways": 5, "flat": False, "n_oncrit_exposed": 0,
                                  "gateway_acl_coverage": 100.0}})
    assert "no top-tier blockers" in b["posture_statement"]
    assert b["top_gating"] == []


def test_avg_health_excludes_insufficient_data():
    """Coverage-honesty: an 'Insufficient Data' device (absent evidence -> no deductions -> a near-perfect
    score) must NOT inflate the fleet average-health headline; the average is over genuinely-scored rows."""
    b = compute_executive_brief(health_scores=[
        {"switch": "a", "band": "Critical", "score": 20},
        {"switch": "b", "band": "Good", "score": 80},
        {"switch": "c", "band": "Insufficient Data", "score": 99}])   # uncollected — must be excluded
    assert b["posture"]["avg_health"] == 50            # (20+80)/2, NOT (20+80+99)/3 == 66
    assert b["scale"]["n_devices"] == 3                # but the device COUNT still reflects all inventoried


def test_empty_and_deterministic():
    out = compute_executive_brief()
    assert out["axes"] and out["scale"]["n_devices"] == 0            # health + punch-list axes always present
    a = compute_executive_brief(**_full())
    c = compute_executive_brief(**_full())
    assert json.dumps(a, sort_keys=True) == json.dumps(c, sort_keys=True)
