"""NEW-V3.23.145: migration-campaign trend across a SERIES of snapshots. Pins the trajectory verdict
(IMPROVING / REGRESSING / INSUFFICIENT), the per-metric directions, the per-step findings burndown
(reusing compute_snapshot_delta), and the trend workbook's sheets."""
from openpyxl import load_workbook

from cisco_toolkit.html import compute_campaign_trend, write_campaign_workbook


def _snap(date, avg, bands, punch, not_ready, ldos):
    """bands: {band: count} -> health_scores with stable switch names; punch: list of (severity, title).
    ldos = n_past_ldos (past last-day-of-support = the engine's canonical "past end-of-support", the
    migration-critical unsupported count the brief/deck/explorer headline). n_past_eos (past end-of-SALE,
    still supported) is PINNED to 0 here so the 'Past end-of-support' trajectory metric can read as
    'improving' ONLY if it sources n_past_ldos, never n_past_eos -- guards the EoS/LDoS silent-drop class
    (a fleet can be 0 past-EoS yet have 152 past-LDoS; reading the wrong field hides every unsupported box)."""
    hs, i = [], 0
    for band, cnt in bands.items():
        for _ in range(cnt):
            hs.append({"switch": f"sw{i}", "score": avg, "band": band}); i += 1
    return {
        "generated_at": date + "T00:00:00", "script_version": "V3.23.0",
        "devices": {h["switch"]: {} for h in hs}, "interfaces": {},
        "health_scores": hs,
        "punchlist": [{"severity": s, "category": "X", "title": t, "devices": ["sw0"]} for (s, t) in punch],
        "migration_readiness": [{"readiness": "NOT READY", "switches": ["sw0"]} for _ in range(not_ready)],
        "lifecycle_risk": {"summary": {"n_past_ldos": ldos, "n_past_eos": 0}},
        "executive_brief": {"posture": {"avg_health": avg}},
    }


C1 = _snap("2026-01-01", 50, {"Critical": 2, "Fair": 1, "Good": 1},
           [("Critical", "A"), ("High", "B"), ("High", "C"), ("Low", "D")], 2, 4)
C2 = _snap("2026-02-01", 65, {"Critical": 1, "Fair": 2, "Good": 1},
           [("High", "B"), ("Low", "D")], 1, 2)
C3 = _snap("2026-03-01", 80, {"Good": 2, "Excellent": 2},
           [("Low", "D")], 0, 0)


def test_improving_campaign_verdict():
    t = compute_campaign_trend([C1, C2, C3])
    assert t["verdict"] == "IMPROVING"
    assert len(t["timeline"]) == 3
    dirs = {r["metric"]: r["direction"] for r in t["trajectory"]}
    assert dirs["Avg health / 100"] == "improving"
    assert dirs["Critical-band switches"] == "improving"
    assert dirs["Critical/High findings"] == "improving"
    assert dirs["Past end-of-support"] == "improving"
    assert t["timeline"][0]["avg_health"] == 50 and t["timeline"][-1]["avg_health"] == 80
    assert t["timeline"][0]["n_critical"] == 2 and t["timeline"][-1]["n_critical"] == 0


def test_burndown_resolves_findings_per_step():
    t = compute_campaign_trend([C1, C2, C3])
    assert len(t["steps"]) == 2
    s1 = t["steps"][0]
    assert s1["from"] == "C1" and s1["to"] == "C2"
    assert s1["resolved"] >= 2 and s1["opened"] == 0   # C1->C2 cleared the Critical A + High C findings


def test_regressing_campaign():
    t = compute_campaign_trend([C3, C1])               # reversed series = the network getting worse
    assert t["verdict"] == "REGRESSING"


def test_insufficient_single_snapshot():
    t = compute_campaign_trend([C1])
    assert t["verdict"] == "INSUFFICIENT" and t["trajectory"] == [] and t["steps"] == []


def test_campaign_workbook_sheets(tmp_path):
    out = tmp_path / "trend.xlsx"
    write_campaign_workbook([C1, C2, C3], str(out))
    wb = load_workbook(str(out))
    assert wb.sheetnames == ["Campaign Summary", "Timeline", "Burndown"]
    summ = wb["Campaign Summary"]
    assert summ.cell(2, 1).value == "CAMPAIGN VERDICT" and summ.cell(2, 2).value == "IMPROVING"
    tl = wb["Timeline"]
    assert tl.cell(1, 1).value == "Collection" and tl.max_row == 4    # header + 3 collections
    bd = wb["Burndown"]
    assert bd.cell(1, 1).value == "Step" and bd.max_row == 3          # header + 2 steps


def test_campaign_trend_not_improving_when_a_device_goes_dark():
    """[audit-2 #4] a device present then ABSENT across the campaign (gone dark) makes a rising avg-health
    survivorship-biased; the verdict must NOT read IMPROVING -- it downgrades to MIXED and discloses the dark
    device (else a failed / decommissioned-without-record device silently reads as improvement)."""
    from cisco_toolkit.html import compute_campaign_trend
    def snap(devs, scores):
        return {"devices": {d: {} for d in devs}, "interfaces": {d: {} for d in devs},
                "health_scores": [{"switch": s, "band": b, "score": sc} for s, b, sc in scores],
                "punchlist": [], "executive_brief": {"scale": {"n_devices": len(devs)}}}
    old = snap(["core1", "core2", "acc1"], [("core1", "Good", 90), ("core2", "Good", 88), ("acc1", "Fair", 70)])
    new = snap(["core1", "acc1"], [("core1", "Good", 90), ("acc1", "Good", 80)])   # core2 went dark
    t = compute_campaign_trend([old, new])
    assert t["verdict"] != "IMPROVING"
    assert "dark" in t["verdict_note"].lower()


def test_cutover_diff_insufficient_data_is_coverage_not_health_improvement():
    """[audit-4 #5 false-health] 'Insufficient Data' ranked WORSE than Critical, so a dark device re-collected and
    found Critical classified as 'improved' + CLEAN -- the single most safety-critical gate reading a newly-online
    Critical box as an improvement. Insufficient Data is a COVERAGE state, not a health-scale point."""
    from cisco_toolkit import html
    base = {"devices": {"A": {}}, "interfaces": {"A": {}}, "punchlist": []}
    dark = dict(base, health_scores=[{"switch": "A", "band": "Insufficient Data", "score": 90}])
    crit = dict(base, health_scores=[{"switch": "A", "band": "Critical", "score": 12}])
    d = html.compute_snapshot_delta(dark, crit)        # newly collected, found Critical
    assert d["health"]["n_improved"] == 0 and d["verdict"] != "CLEAN"
    d2 = html.compute_snapshot_delta(crit, dark)       # went dark = coverage loss
    assert d2["health"]["n_improved"] == 0 and d2["verdict"] != "CLEAN"
    good = dict(base, health_scores=[{"switch": "A", "band": "Good", "score": 85}])
    d3 = html.compute_snapshot_delta(crit, good)       # genuine health improvement still counts
    assert d3["health"]["n_improved"] == 1


def test_cutover_diff_survives_null_list_rows():
    """[audit-4 #15 totality] a null element in health_scores/punchlist (hand-trimmed / older-schema snapshot fed
    to --compare/--trend) crashed compute_snapshot_delta with AttributeError instead of degrading."""
    from cisco_toolkit import html
    old = {"devices": {"A": {}}, "interfaces": {"A": {}},
           "health_scores": [None, {"switch": "A", "band": "Good", "score": 80}], "punchlist": [None]}
    new = {"devices": {"A": {}}, "interfaces": {"A": {}}, "health_scores": [], "punchlist": []}
    assert isinstance(html.compute_snapshot_delta(old, new), dict)   # must not raise


def test_delta_title_rename_alias_prevents_false_churn():
    """PR-#396 review: comparing an OLD-engine baseline against a NEW-engine snapshot of an IDENTICAL
    network reported the native-VLAN-1 title rename as 1 opened + 1 resolved and flipped the cutover
    verdict CLEAN -> REVIEW. html._finding_key now aliases the pre-rename wording onto the current one
    (_TITLE_RENAMES); a GENUINE scope change (different count) must still churn honestly."""
    from cisco_toolkit.html import compute_snapshot_delta

    base = {"devices": {}, "interfaces": {}}
    row = {"severity": "Low", "category": "False-health", "devices": ["acc1", "core1"]}
    old = dict(base, punchlist=[dict(row, title="Native VLAN 1 on 4 inter-switch trunk(s)")])
    new = dict(base, punchlist=[dict(row, title="Native VLAN 1 on 4 operationally-trunking port(s)")])
    d = compute_snapshot_delta(old, new)
    assert d["findings"]["n_opened"] == 0 and d["findings"]["n_resolved"] == 0
    assert d["verdict"] == "CLEAN"
    # a genuine scope change (count moved 4 -> 5) still shows honestly as resolved+opened
    new2 = dict(base, punchlist=[dict(row, title="Native VLAN 1 on 5 operationally-trunking port(s)")])
    d2 = compute_snapshot_delta(old, new2)
    assert d2["findings"]["n_opened"] == 1 and d2["findings"]["n_resolved"] == 1
