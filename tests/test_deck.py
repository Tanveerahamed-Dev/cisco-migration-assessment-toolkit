"""NEW-V3.23.144: executive presentation deck (.pptx). Pins the slide count, the signature content drawn
from each snapshot axis, the 'Â·' mojibake cleanup, and graceful degradation on a sparse snapshot.
python-pptx is an optional dependency — these tests skip when it isn't installed (CI installs it)."""
import pytest

pytest.importorskip("pptx", reason="python-pptx not installed (optional deck dependency)")

from pptx import Presentation                                   # noqa: E402
from cisco_toolkit.deck import write_executive_deck_pptx        # noqa: E402


def _rich_snap():
    return {
        "executive_brief": {
            "scale": {"n_devices": 12, "n_domains": 3, "n_endpoints": 840},
            "posture": {"avg_health": 61, "n_critical": 2, "n_poor": 1, "worst_band": "Critical"},
            "posture_statement": "Migration posture: 2 switches Critical; hardware EoL a primary driver.",
            "axes": [
                {"axis": "Fleet health", "severity": "Critical", "headline": "61/100 avg · 2 Critical"},
                {"axis": "Punch-list", "severity": "High", "headline": "30 items · 2 Critical, 11 High"},
            ],
            "top_gating": ["61/100 avg · 2 Critical", "30 items · 2 Critical, 11 High", "40% past/near EoS"],
        },
        "health_scores": [
            {"switch": "core1", "score": 12, "band": "Critical"},
            {"switch": "core2", "score": 55, "band": "Fair"},
            {"switch": "acc1", "score": 88, "band": "Excellent"},
        ],
        "punchlist": [
            {"severity": "Critical", "category": "Cross-layer", "title": "VLAN 30 single-fiber uplink",
             "devices": ["core1", "acc1"]},
            {"severity": "High", "category": "STP", "title": "Accidental root on VLAN 10", "devices": ["acc1"]},
        ] + [{"severity": "Low", "category": "Hygiene", "title": f"unused acl {i}", "devices": ["x"]}
             for i in range(8)],
        "failure_impact": [
            {"host": "core1", "severity": "High", "vlans_impacted": 4, "stranded": 220, "hard": 180,
             "detail": "VLAN 10 hard partition"},
            {"host": "core2", "severity": "Medium", "vlans_impacted": 2, "stranded": 40, "hard": 0,
             "detail": "backup-covered"},
        ],
        "lifecycle_risk": {"summary": {"n_devices": 12, "by_band": {"Past-EoS": 3, "Near-LDoS": 2, "Active": 7},
                                       "n_past_eos": 3, "n_past_ldos": 0, "n_near": 2, "n_active": 7,
                                       "n_unknown": 0}},
        "migration_readiness": [
            {"group": "Group 1", "readiness": "NOT READY", "n_fail": 3, "n_warn": 2},
            {"group": "Group 2", "readiness": "READY", "n_fail": 0, "n_warn": 0},
        ],
        "move_groups": [{"switches": ["core1", "acc1"]}, {"switches": ["core2"]}],
    }


def _deck(path):
    p = Presentation(path)
    n = len(p.slides._sldIdLst)
    txt = "\n".join(sh.text_frame.text for sl in p.slides for sh in sl.shapes if sh.has_text_frame)
    return n, txt


def test_deck_has_all_slides_and_key_content(tmp_path):
    out = tmp_path / "deck.pptx"
    write_executive_deck_pptx(str(out), _rich_snap(), "Test fleet")
    assert out.is_file()
    n, txt = _deck(str(out))
    assert n == 7, f"expected 7 slides, got {n}"
    assert "Network Migration" in txt                                  # 1 title
    assert "Fleet posture" in txt and "61" in txt                      # 2 posture + avg health
    assert "Top migration risks" in txt and "VLAN 30 single-fiber uplink" in txt   # 3 risks
    assert "core1" in txt and "220" in txt                             # 4 keystone + stranded count
    assert "end-of-support" in txt.lower()                             # 5 lifecycle
    assert "NOT READY" in txt and "Group 1" in txt                     # 6 waves
    assert "Where to start" in txt                                     # 7 recommendation


def test_deck_lifecycle_past_end_of_support_is_ldos_not_eos(tmp_path):
    """A3 (SSOT/coverage-honesty): the 'past end-of-support' headline must read n_past_ldos ALONE
    (matching the canonical executive_brief lifecycle axis, analyze.py:5018), NOT n_past_eos +
    n_past_ldos. Past-EoS is end-of-SALE (support window still open). Fixture: 152 LDoS + 40 EoS +
    61 near of 303 → headline 152 and 70% past/nearing; the old conflation rendered 192 / 83%."""
    snap = _rich_snap()
    snap["lifecycle_risk"] = {"summary": {
        "n_devices": 303, "n_past_ldos": 152, "n_past_eos": 40, "n_near": 61, "n_active": 50,
        "by_band": {"Past-LDoS": 152, "Past-EoS": 40, "Near-LDoS": 61, "Active": 50}}}
    out = tmp_path / "deck.pptx"
    write_executive_deck_pptx(str(out), snap, "Test fleet")
    n, txt = _deck(str(out))
    assert "152" in txt and "70%" in txt           # n_past_ldos headline + (152+61)/303 pct
    assert "192" not in txt and "83%" not in txt    # old n_past_eos+n_past_ldos conflation gone


def test_deck_gains_riskiest_assets_slide_with_register(tmp_path):
    """NEW-V3.23.174: a snapshot carrying the Device Risk Register renders the extra
    'riskiest assets' slide (8 total); the back-compat 7-slide pin above proves the
    slide is data-gated, never empty filler."""
    snap = _rich_snap()
    snap["device_dossiers"] = {
        "per_device": [
            {"host": "core1", "risk_band": "Severe", "risk_index": 60, "impact_score": 10,
             "exposure_score": 6,
             "compound": [{"code": "CR-01", "title": "End-of-support keystone", "severity": "Critical",
                           "basis": "EoL x blast radius"}],
             "verdict": "Stabilize or replace before migration — open advisory surface."},
            {"host": "acc1", "risk_band": "Low", "risk_index": 2, "impact_score": 2,
             "exposure_score": 1, "compound": [], "verdict": "No stacked risk."},
        ],
        "summary": {"n_devices": 2, "bands": {"Severe": 1, "Elevated": 0, "Guarded": 0, "Low": 1},
                    "n_compound": 1, "worst": ["core1"]}}
    out = tmp_path / "deck_rr.pptx"
    write_executive_deck_pptx(str(out), snap, "Test fleet")
    n, txt = _deck(str(out))
    assert n == 8, f"expected 8 slides with the register, got {n}"
    assert "worry an engineer most" in txt
    assert "CR-01" in txt and "Stabilize or replace" in txt


def test_deck_gains_target_state_design_slide(tmp_path):
    """NEW: a snapshot carrying the design_blueprint renders the extra 'target-state design' slide (8
    total); the back-compat 7-slide pin above proves the slide is data-gated (the design engine's
    compute_design_blueprint), never empty filler — the SAME blueprint behind the HLD/LLD and dashboards."""
    snap = _rich_snap()
    snap["design_blueprint"] = {
        "summary": {"n_decisions": 2, "n_recommended": 2, "n_needs_requirement": 1, "n_critical": 1,
                    "headline": "2 design decisions."},
        "tradeoff_scorecard": [{"axis": "availability", "label": "High availability", "score": 0,
                                "posture": "Weak", "evidence": "no FHRP"}],
        "decisions": [
            {"id": "fhrp-first-hop-gateway-redundancy", "title": "Introduce first-hop redundancy",
             "priority": "Critical", "status": "recommended", "evidence": {"summary": "52 VLANs without FHRP"},
             "principle": {"citation": "CCDE In Depth — HA"}, "recommended_action": "HSRP/VRRP"},
            {"id": "x", "title": "Right-size availability", "priority": "High", "status": "needs-requirement",
             "evidence": {"summary": ""}, "principle": {"citation": "CCDE"},
             "requirements_needed": ["availability_tier"]},
        ],
        "coverage": {"caveat": "grounded only in collected evidence"},
    }
    out = tmp_path / "deck_design.pptx"
    write_executive_deck_pptx(str(out), snap, "Test fleet")
    n, txt = _deck(str(out))
    assert n == 8, f"expected 8 slides with the design blueprint, got {n}"
    assert "design the migration should adopt" in txt.lower() or "target state" in txt.lower()
    assert "Introduce first-hop redundancy" in txt


def test_deck_migration_slide_surfaces_honest_wave_count(tmp_path):
    """B1 (audit fix): when the snapshot carries the design wave_plan, the 'How it sequences' slide must
    headline the honest SEQUENCED wave count (design_blueprint.target_state.wave_plan.n_waves) -- not the
    raw move-group count presented as if it were parallelizable waves. A 60-switch L2-coupled domain is
    ONE set sliced into sequenced sub-waves, not 6 parallel waves; the slide must say so."""
    snap = _rich_snap()
    snap["move_groups"] = ([{"switches": [f"s{i}" for i in range(60)]}]
                           + [{"switches": [f"t{j}"]} for j in range(5)])   # 1x60 + 5 singletons = 6 groups
    snap["design_blueprint"] = {
        "summary": {"n_decisions": 1, "n_recommended": 1, "n_needs_requirement": 0, "n_critical": 1,
                    "headline": "1 critical recommended."},
        "tradeoff_scorecard": [], "coverage": {},
        "decisions": [{"id": "fhrp-first-hop-gateway-redundancy", "title": "Introduce FHRP",
                       "priority": "Critical", "status": "recommended",
                       "evidence": {"summary": "x"}, "principle": {"citation": "CCDE"}}],
        "target_state": {"wave_plan": {"n_waves": 3, "n_move_groups": 6, "largest_group": 60,
                                       "wave_cap": 40, "waves": [], "note": "n"}},
    }
    out = tmp_path / "deck_waves.pptx"
    write_executive_deck_pptx(str(out), snap, "Test fleet")
    _n, txt = _deck(str(out))
    low = txt.lower()
    assert "candidate wave" in low, "slide must surface the honest sequenced wave count label"
    # the honest relationship (move-groups -> sequenced waves) must be disclosed, not just the raw 6
    assert "sequence" in low and "60" in txt, "must disclose the largest L2 domain sequences into waves"


def test_deck_cleans_mojibake(tmp_path):
    snap = {"executive_brief": {"axes": [{"axis": "X", "severity": "High", "headline": "a Â· b"}],
                                "top_gating": []}}
    out = tmp_path / "d.pptx"
    write_executive_deck_pptx(str(out), snap, "L")
    _n, txt = _deck(str(out))
    assert "Â·" not in txt and "a · b" in txt


def test_sparse_snapshot_is_tolerated(tmp_path):
    out = tmp_path / "empty.pptx"
    write_executive_deck_pptx(str(out), {}, "Empty")               # no keys at all
    assert out.is_file()
    n, _ = _deck(str(out))
    assert n == 6        # every slide renders except the data-gated lifecycle slide
