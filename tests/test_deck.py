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
