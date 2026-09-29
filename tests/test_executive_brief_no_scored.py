"""G15: a fleet in which NO device was health-scored must never publish a measured-looking headline.

`compute_executive_brief` averaged only the genuinely-scored rows (an 'Insufficient Data' row keeps
its near-perfect, deduction-free score) but fell back to a hard ``0`` when that set was empty. The
fleet posture then published ``avg_health: 0`` and a "Fleet health" axis of "0/100 avg" at severity
``Low`` -- absence rendered as a measurement -- and the posture statement concluded "no top-tier
blockers ... proceed with the standard wave plan" about a fleet nothing had looked at.

The fix is a CONTRACT, not a one-line default, because three consumers recomputed a fallback mean
over EVERY health row (the 'Insufficient Data' rows included) whenever the canonical value was not a
number: turning the producer's 0 into ``None`` alone would have rendered a fabricated "100 / 100".
These tests pin both halves: the producer abstains, and no consumer re-derives a number from the
unscored rows.

The scored path is pinned too -- it must stay byte-for-byte what it was (the golden snapshot and the
sample fleet are regenerated from it).
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from cisco_toolkit import ssot
from cisco_toolkit.analyze import compute_executive_brief

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPLORER = ROOT / "cisco_toolkit" / "blast_radius_explorer.html"
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
NODE = shutil.which("node")


def _insufficient(n=5, score=100):
    """`n` never-collected rows exactly as compute_health_scores emits them: band 'Insufficient Data'
    with the deduction-free score the scorer still assigns (no evidence -> no deductions)."""
    return [{"switch": f"sw{i}", "band": "Insufficient Data", "score": score} for i in range(n)]


def _axis(brief, name):
    return next(a for a in brief["axes"] if a["axis"] == name)


# --------------------------------------------------------------------------------------------------
# producer: posture + Fleet-health axis
# --------------------------------------------------------------------------------------------------
def test_all_insufficient_fleet_publishes_no_average():
    b = compute_executive_brief(health_scores=_insufficient())
    p = b["posture"]
    assert p["avg_health"] is None, "no device was scored: a 0 (or any number) is a fabricated measurement"
    assert p["worst_band"] is None, "no band was observed: '' is not a published fact"
    assert p["n_critical"] == 0 and p["n_poor"] == 0          # real counts of observed bands (reconciled)
    assert p["n_scored"] == 0
    assert p["not_assessed"] == "all_insufficient_data"
    assert b["scale"]["n_devices"] == 5                        # the inventory is still counted


def test_empty_health_input_publishes_no_average():
    p = compute_executive_brief()["posture"]
    assert p["avg_health"] is None and p["worst_band"] is None
    assert p["n_scored"] == 0 and p["not_assessed"] == "no_health_rows"


def test_fleet_health_axis_is_not_assessed_not_low():
    b = compute_executive_brief(health_scores=_insufficient())
    ax = _axis(b, "Fleet health")
    assert ax["severity"] == "Info", "Low is the clean-fleet value; nothing was measured"
    assert "NOT ASSESSED" in ax["headline"] and "0 of 5" in ax["headline"]
    assert "/100" not in ax["headline"], ax["headline"]
    assert "0 switch(es) assessed" in ax["detail"] and "5 not collected" in ax["detail"]
    empty = _axis(compute_executive_brief(), "Fleet health")
    assert empty["severity"] == "Info" and "NOT ASSESSED" in empty["headline"]
    assert "/100" not in empty["headline"]


@pytest.mark.parametrize("kwargs", [dict(health_scores=_insufficient()), dict()],
                         ids=["all-insufficient", "no-health-rows"])
def test_posture_statement_never_clears_an_unscored_fleet(kwargs):
    ps = compute_executive_brief(**kwargs)["posture_statement"]
    assert "no top-tier blockers" not in ps and "proceed with the standard wave plan" not in ps, ps
    assert "fleet health is NOT ASSESSED" in ps and "not assessed, not clear" in ps, ps


def test_not_assessed_flag_survives_a_crowded_flag_list():
    """The flag must sit inside the rendered flags[:4] even when every other flag fires."""
    b = compute_executive_brief(
        health_scores=_insufficient(3),
        migration_readiness=[{"readiness": "NOT READY"}],
        lifecycle_risk={"summary": {"n_devices": 3, "n_past_ldos": 1, "n_near": 0, "n_unknown": 1}},
        segmentation={"summary": {"n_gateways": 2, "flat": True}},
        multicast_intelligence={"summary": {"n_groups": 4, "n_mac_clashes": 1, "n_ptp_clocks": 2,
                                            "n_ptp_dormant": 2}})
    shown = b["posture_statement"].split("; +")[0]
    assert "fleet health is NOT ASSESSED" in shown, b["posture_statement"]
    assert "wave(s)" not in b["posture_statement"]


def test_no_health_call_keeps_the_not_ready_flag_visible():
    ps = compute_executive_brief(
        migration_readiness=[{"readiness": "NOT READY"}, {"readiness": "READY"}])["posture_statement"]
    assert "move-group(s) are NOT READY" in ps.split("; +")[0]
    assert "wave(s)" not in ps


def test_a_critical_band_without_a_numeric_score_still_leads():
    """An adverse OBSERVED band is still a finding even when its row carried no usable score."""
    b = compute_executive_brief(health_scores=[{"switch": "a", "band": "Critical", "score": None}])
    assert b["posture"]["avg_health"] is None and b["posture"]["worst_band"] == "Critical"
    assert _axis(b, "Fleet health")["severity"] == "Critical"


# --------------------------------------------------------------------------------------------------
# producer: the scored path is unchanged (golden / sample fleet regenerate from it)
# --------------------------------------------------------------------------------------------------
def test_scored_path_shape_and_text_are_unchanged():
    b = compute_executive_brief(health_scores=[
        {"switch": "a", "band": "Critical", "score": 20},
        {"switch": "b", "band": "Good", "score": 80},
        {"switch": "c", "band": "Insufficient Data", "score": 99}])
    assert b["posture"] == {"avg_health": 50, "n_critical": 1, "n_poor": 0, "worst_band": "Critical"}
    ax = _axis(b, "Fleet health")
    assert ax == {"axis": "Fleet health", "severity": "Critical",
                  "headline": "50/100 avg · 1 Critical, 0 Poor band",
                  "detail": "2 switch(es) assessed; 1 not collected (no evidence)."}
    assert set(b) == {"scale", "posture", "axes", "top_gating", "posture_statement"}


def test_sample_fleet_brief_is_reproduced_exactly():
    """The sample fleet's embedded brief was produced by the scored path; nothing here may move it."""
    s = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert s["executive_brief"]["posture"] == {"avg_health": 50, "n_critical": 6, "n_poor": 12,
                                               "worst_band": "Critical"}
    assert ssot.summary(s) == s["executive_brief"]["ssot"]      # n_facts / n_checked unchanged


# --------------------------------------------------------------------------------------------------
# producer: the other zero-for-nothing members of the class inside compute_executive_brief
# --------------------------------------------------------------------------------------------------
def test_lifecycle_share_over_zero_assessable_is_not_a_percentage():
    b = compute_executive_brief(
        health_scores=[{"switch": "a", "band": "Good", "score": 90}],
        lifecycle_risk={"summary": {"n_devices": 4, "n_unknown": 4, "n_past_ldos": 0, "n_near": 0}})
    head = _axis(b, "Hardware lifecycle (EoL)")["headline"]
    assert "0% of 0" not in head and "share not computable" in head, head


def test_lifecycle_flag_never_prints_zero_percent_beside_a_past_ldos_device():
    """A (malformed) rollup whose assessable denominator is 0 while a Past-LDoS count is published:
    the flag stated '(0% past/near)' beside a real finding."""
    b = compute_executive_brief(
        health_scores=[{"switch": "a", "band": "Good", "score": 90}],
        lifecycle_risk={"summary": {"n_devices": 4, "n_unknown": 4, "n_past_ldos": 1, "n_near": 0}})
    ps = b["posture_statement"]
    assert "hardware end-of-support is a primary driver" in ps
    assert "(0% past/near)" not in ps and "share not computable" in ps, ps


def test_lifecycle_share_with_assessable_devices_is_unchanged():
    b = compute_executive_brief(
        health_scores=[{"switch": "a", "band": "Good", "score": 90}],
        lifecycle_risk={"summary": {"n_devices": 10, "n_unknown": 0, "n_past_ldos": 5, "n_near": 0}})
    assert "(50% of 10 assessable)" in _axis(b, "Hardware lifecycle (EoL)")["headline"]
    assert "(50% past/near)" in b["posture_statement"]


def test_asset_register_of_only_unassessed_assets_is_not_low():
    b = compute_executive_brief(
        health_scores=_insufficient(),
        device_dossiers={"summary": {"n_devices": 5, "n_compound": 0, "worst": [],
                                     "bands": {"Severe": 0, "Elevated": 0, "Guarded": 0, "Low": 0,
                                               "Unassessed": 5}}})
    ax = _axis(b, "Asset risk register")
    assert ax["severity"] == "Info", ax
    assert "all 5 asset(s) Unassessed" in ax["headline"], ax["headline"]


def test_asset_register_with_assessed_assets_is_unchanged():
    b = compute_executive_brief(
        health_scores=[{"switch": "a", "band": "Good", "score": 90}],
        device_dossiers={"summary": {"n_devices": 2, "n_compound": 0, "worst": [],
                                     "bands": {"Severe": 0, "Elevated": 0, "Guarded": 0, "Low": 2,
                                               "Unassessed": 0}}})
    ax = _axis(b, "Asset risk register")
    assert ax["severity"] == "Low" and ax["headline"] == "0 Severe, 0 Elevated of 2 asset(s)"


# --------------------------------------------------------------------------------------------------
# ssot.reconcile: the abstention is verified in BOTH directions
# --------------------------------------------------------------------------------------------------
def _snap(health, posture):
    return {"health_scores": health, "executive_brief": {"posture": posture}}


def test_reconcile_flags_a_number_published_for_an_unscored_fleet():
    """The pre-fix producer's output (and every stored snapshot it wrote)."""
    v = ssot.reconcile(_snap(_insufficient(), {"avg_health": 0, "n_critical": 0, "n_poor": 0,
                                               "worst_band": ""}))
    assert any("avg_health" in x for x in v), v


def test_reconcile_flags_an_abstention_published_for_a_scored_fleet():
    v = ssot.reconcile(_snap([{"switch": "a", "band": "Good", "score": 80}],
                             {"avg_health": None, "n_critical": 0, "n_poor": 0, "worst_band": "Good"}))
    assert any("avg_health" in x for x in v), v


def test_reconcile_flags_a_withheld_worst_band_while_a_band_is_observed():
    v = ssot.reconcile(_snap([{"switch": "a", "band": "Poor", "score": 50}],
                             {"avg_health": 50, "n_critical": 0, "n_poor": 1, "worst_band": None}))
    assert any("worst_band" in x for x in v), v


def test_reconcile_accepts_and_counts_the_honest_abstention():
    b = compute_executive_brief(health_scores=_insufficient())
    snap = {"health_scores": _insufficient(), "executive_brief": b}
    ran = []
    assert ssot.reconcile(snap, _ran=ran) == []
    assert "executive_brief.posture.avg_health" in ran     # verified, not skipped
    facts = ssot.canonical_facts(snap)
    assert facts["avg_health"] is None and facts["worst_band"] is None
    assert ssot.summary(snap)["verified"] is True


# --------------------------------------------------------------------------------------------------
# consumers: none may re-derive a number from the unscored rows
# --------------------------------------------------------------------------------------------------
def _unscored_snapshot():
    hs = _insufficient()
    return {"generated_at": "2026-01-01T00:00:00", "script_version": "V3.23.0",
            "devices": {r["switch"]: {} for r in hs}, "health_scores": hs,
            "executive_brief": compute_executive_brief(health_scores=hs)}


def test_trend_point_abstains_on_a_published_abstention():
    from cisco_toolkit.html import _trend_point
    assert _trend_point(_unscored_snapshot())["avg_health"] == ""
    # canonical-first on the KEY: a published abstention is never replaced by a recompute, even when the
    # rows beside it would yield a number (that disagreement is ssot.reconcile's to report, not to paper over)
    mixed = {"health_scores": [{"switch": "a", "band": "Good", "score": 80}],
             "executive_brief": {"posture": {"avg_health": None, "n_scored": 0}}}
    assert _trend_point(mixed)["avg_health"] == ""


def test_trend_point_legacy_fallback_excludes_insufficient_data():
    from cisco_toolkit.html import _trend_point
    snap = {"health_scores": [{"switch": "a", "band": "Good", "score": 80},
                              {"switch": "b", "band": "Insufficient Data", "score": 100}]}
    assert _trend_point(snap)["avg_health"] == 80.0
    only_unscored = {"health_scores": _insufficient()}
    assert _trend_point(only_unscored)["avg_health"] == ""


def _exec_sheet_value(brief, hs, label="Average health score"):
    from openpyxl import Workbook
    import cisco_toolkit.excel as X
    wb = Workbook(); X.harden_workbook(wb)
    X.write_executive_summary_sheet(wb, hs, [], [], [], brief=brief)
    for row in wb[X.EXEC_SUMMARY_SHEET_NAME].iter_rows(values_only=True):
        cells = [c for c in row if c not in (None, "")]
        if cells and str(cells[0]).strip() == label:
            return " ".join(str(c) for c in cells[1:])
    return None


def test_workbook_exec_summary_says_not_assessed():
    snap = _unscored_snapshot()
    val = _exec_sheet_value(snap["executive_brief"], snap["health_scores"])
    assert val is not None and "NOT ASSESSED" in val, val
    assert "/ 100" not in val, val
    mixed = _exec_sheet_value({"posture": {"avg_health": None, "n_scored": 0}},
                              [{"switch": "a", "band": "Good", "score": 80}])
    assert mixed is not None and "NOT ASSESSED" in mixed and "80" not in mixed, mixed


def test_workbook_legacy_fallback_excludes_insufficient_data():
    hs = [{"switch": "a", "band": "Good", "score": 80},
          {"switch": "b", "band": "Insufficient Data", "score": 100}]
    assert _exec_sheet_value(None, hs) == "80 / 100"
    val = _exec_sheet_value(None, _insufficient())
    assert val is not None and "NOT ASSESSED" in val and "100" not in val, val


def test_deck_never_renders_a_literal_none(tmp_path):
    pptx = pytest.importorskip("pptx")
    from cisco_toolkit.deck import write_executive_deck_pptx
    out = tmp_path / "deck.pptx"
    write_executive_deck_pptx(str(out), _unscored_snapshot(), "Fleet")
    prs = pptx.Presentation(str(out))
    txt = "\n".join(sh.text_frame.text for sl in prs.slides for sh in sl.shapes if sh.has_text_frame)
    assert "None" not in txt, txt
    assert "NOT ASSESSED" in txt


def test_at_a_glance_row_says_not_assessed():
    from cisco_toolkit import docmeta
    rows = dict(docmeta._glance_rows(_unscored_snapshot()))
    health = rows["How healthy is the fleet?"]
    assert "NOT ASSESSED" in health and "/100" not in health, health


# --------------------------------------------------------------------------------------------------
# the offline explorer: one reader, decided on key PRESENCE, executed under node
# --------------------------------------------------------------------------------------------------
def _explorer_helper():
    m = re.search(r"/\* FLEET-AVG-HEALTH START \*/(.*?)/\* FLEET-AVG-HEALTH END \*/",
                  EXPLORER.read_text(encoding="utf-8"), re.S)
    assert m, "the explorer's single fleet-average reader (FLEET-AVG-HEALTH block) is missing"
    return m.group(1)


def test_explorer_has_no_all_rows_fallback_left():
    """Every site that showed the fleet average used `posture.avg_health ?? mean(all rows)`: a null
    abstention fell through to a mean that counts the 'Insufficient Data' rows (the fabricated 100)."""
    src = EXPLORER.read_text(encoding="utf-8")
    assert "avg_health??" not in src.replace(" ", "")
    assert src.count("fleetAvgHealth(") >= 4, "modeSummary / narrativeCard / drawer head / Ask-bar"
    _explorer_helper()


@pytest.mark.skipif(not NODE, reason="node is not installed -- executed explorer check skipped")
def test_explorer_fleet_average_reader_executes(tmp_path):
    driver = tmp_path / "drv.js"
    driver.write_text(
        "let SNAP=null;\n" + _explorer_helper() + "\n"
        "const out=[];\n"
        "const ins=[{switch:'a',band:'Insufficient Data',score:100},{switch:'b',band:'Insufficient Data',score:100}];\n"
        "SNAP={executive_brief:{posture:{avg_health:null,n_scored:0}}}; out.push(fleetAvgHealth(ins));\n"
        "SNAP={executive_brief:{posture:{avg_health:41}}}; out.push(fleetAvgHealth(ins));\n"
        "SNAP={}; out.push(fleetAvgHealth([{band:'Good',score:80}].concat(ins)));\n"
        "SNAP={}; out.push(fleetAvgHealth(ins));\n"
        "SNAP={executive_brief:{_unavailable:true}}; out.push(fleetAvgHealth([{band:'Poor',score:40}]));\n"
        "SNAP={executive_brief:{posture:{avg_health:null}}}; out.push(fleetAvgHealth([{band:'Good',score:80}]));\n"
        "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    proc = subprocess.run([NODE, str(driver)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [None, 41, 80, None, 40, None]
