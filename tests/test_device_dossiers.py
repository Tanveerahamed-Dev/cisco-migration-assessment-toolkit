"""Tests for the V3.23.172 Device Risk Register: compute_device_dossiers (the per-asset
cross-axis synthesis), its compound patterns + band floor, the punch-list fold, the
executive-brief axis, and the workbook sheet writer."""
from cisco_toolkit.analyze import (compute_device_dossiers, compute_executive_brief,
                                   compute_migration_punchlist)


def _dossiers_severe_core():
    """A core box stacking three independent risks: Critical health, past-LDoS hardware,
    High blast radius (230 stranded endpoints) -- the CR-01/CR-02 textbook case."""
    return compute_device_dossiers(
        health_scores=[{"switch": "core1", "score": 18, "band": "Critical",
                        "role": "distribution", "criticality": 1.0, "deductions": []}],
        failure_impact=[{"host": "core1", "severity": "High", "stranded": 230,
                         "vlans_impacted": 12, "hard": 3, "backup": 0, "fhrp": 0,
                         "detail": "VLAN 10: Hard partition (230 ep)"}],
        lifecycle_risk={"per_device": [{"host": "core1", "model": "WS-C4506-E",
                                        "platform": "cat4500", "sw_version": "15.2(2)E",
                                        "band": "Past-LDoS"}]},
        move_groups=[{"group": "Group 1", "switches": ["core1"]}])


def test_empty_inputs_yield_empty_register():
    dd = compute_device_dossiers()
    assert dd["per_device"] == []
    assert dd["summary"]["n_devices"] == 0
    assert dd["summary"]["bands"] == {"Severe": 0, "Elevated": 0, "Guarded": 0, "Low": 0, "Unassessed": 0}
    assert "not assessed" in dd["note"]


def test_healthy_device_lands_low_and_na_axes_never_count():
    dd = compute_device_dossiers(
        health_scores=[{"switch": "acc1", "score": 96, "band": "Excellent",
                        "role": "access", "criticality": 1.0, "deductions": []}],
        syslog_intelligence={"per_device": [{"host": "acc1", "collected": False}],
                             "detections": []},
        platform_health={"per_device": [{"host": "acc1", "collected": False,
                                         "band": "Unknown"}]})
    (d,) = dd["per_device"]
    assert d["risk_band"] == "Low" and d["risk_index"] == 0
    assert d["exposure_score"] == 0          # na axes contribute nothing
    states = {e["axis"]: e["state"] for e in d["exposures"]}
    assert states["Operational logs"] == "na"
    assert states["Control plane"] == "na"
    assert states["Health"] == "ok"
    assert d["n_na"] >= 5                    # most axes carry no evidence here
    assert d["verdict"].startswith("No stacked risk")


def test_fully_unassessed_device_is_not_a_clean_bill_of_health():
    """Coverage-honesty: a device with NO collected evidence (health band 'Insufficient Data', every
    risk axis n/a, no risk/watch signal) must NOT be labeled 'No stacked risk — routine migration
    handling' / Low — that reads a collection GAP as a clean assessment (the exact false-health the
    doctrine forbids). It gets a distinct 'Unassessed' band + an honest verdict. On Meridian this is the 50
    not-collected devices. Distinct from the assessed-clean case above (band 'Excellent', Health=ok)."""
    dd = compute_device_dossiers(
        health_scores=[{"switch": "darkbox", "score": None, "band": "Insufficient Data",
                        "role": "access", "criticality": 1.0, "deductions": []}])
    (d,) = dd["per_device"]
    assert d["health_band"] == "Insufficient Data"
    assert d["n_risk"] == 0 and d["n_watch"] == 0
    assert d["risk_band"] == "Unassessed", d["risk_band"]
    assert not d["verdict"].startswith("No stacked risk")
    assert ("not assess" in d["verdict"].lower()) or ("collection gap" in d["verdict"].lower())
    assert dd["summary"]["bands"].get("Unassessed") == 1


def test_compound_eol_keystone_fires_and_floors_the_band():
    dd = _dossiers_severe_core()
    (d,) = dd["per_device"]
    codes = {c["code"] for c in d["compound"]}
    assert "CR-01" in codes                  # past-LDoS x High blast radius
    assert "CR-02" in codes                  # past-LDoS x Critical health
    cr01 = next(c for c in d["compound"] if c["code"] == "CR-01")
    assert cr01["severity"] == "Critical"
    assert "230 endpoint" in cr01["basis"]
    assert d["risk_band"] == "Severe"        # Critical compound floors the band
    assert d["verdict"].startswith("Stabilize or replace")
    assert d["wave"] == "Group 1"
    assert dd["summary"]["worst"] == ["core1"]
    assert dd["summary"]["n_compound"] == 2


def test_near_ldos_compounds_do_not_claim_support_is_already_lost():
    dd = compute_device_dossiers(
        health_scores=[{"switch": "near1", "score": 18, "band": "Critical", "role": "distribution"}],
        failure_impact=[{"host": "near1", "severity": "High", "stranded": 230,
                         "vlans_impacted": 12}],
        lifecycle_risk={"per_device": [{"host": "near1", "model": "M", "band": "Near-LDoS"}]})
    compounds = dd["per_device"][0]["compound"]
    assert {c["code"] for c in compounds} >= {"CR-01", "CR-02"}
    text = " ".join(c["title"] + " " + c["basis"] for c in compounds)
    assert "within one year" in text
    assert "support entitlement is not inferred" in text
    assert "unsupportable" not in text
    assert "no TAC escalation path" not in text


def test_unscanned_host_is_na_not_clean():
    # known only through EoL evidence -> physical/protocol must be 'na', never silently ok
    dd = compute_device_dossiers(
        lifecycle_risk={"per_device": [{"host": "wan1", "model": "ISR4451", "platform": "isr4k",
                                        "sw_version": "16.9", "band": "Active"}]})
    (d,) = dd["per_device"]
    states = {e["axis"]: e["state"] for e in d["exposures"]}
    hardware = next(e for e in d["exposures"] if e["axis"] == "Hardware EoL")
    assert states["Physical"] == "na" and states["Protocol"] == "na"
    assert states["Hardware EoL"] == "ok"
    assert "pre-EoS date position" in hardware["label"]
    assert "support entitlement not assessed" in hardware["label"]
    assert "supported" not in hardware["label"].lower()


def test_unknown_hardware_band_names_both_authority_failure_paths():
    dd = compute_device_dossiers(
        lifecycle_risk={"per_device": [{"host": "wan1", "model": "ISR4451", "band": "Unknown"}]})
    hardware = next(e for e in dd["per_device"][0]["exposures"] if e["axis"] == "Hardware EoL")
    assert hardware["state"] == "na"
    assert "no exact EoX row matched" in hardware["label"]
    assert "source/date authority was withheld" in hardware["label"]
    assert "model not in the EoL KB" not in hardware["label"]


def test_ranking_is_band_then_index_then_host():
    dd = compute_device_dossiers(
        health_scores=[
            {"switch": "bad1", "score": 20, "band": "Critical", "role": "distribution"},
            {"switch": "ok1", "score": 90, "band": "Good", "role": "access"}],
        failure_impact=[{"host": "bad1", "severity": "High", "stranded": 60,
                         "vlans_impacted": 4, "detail": ""}])
    hosts = [d["host"] for d in dd["per_device"]]
    assert hosts == ["bad1", "ok1"]
    assert dd["per_device"][0]["risk_index"] > dd["per_device"][1]["risk_index"]


def test_memory_only_hot_control_plane_label_never_says_cpu_none():
    """V3.23.175 review fix: a device banded Hot from MEMORY alone (no CPU sample) must cite
    the memory figure, never render 'CPU None%' -- the label flows into verdict sentences."""
    dd = compute_device_dossiers(
        health_scores=[{"switch": "sw1", "score": 90, "band": "Excellent", "role": "access"}],
        platform_health={"per_device": [{"host": "sw1", "collected": True, "cpu_5min": None,
                                         "mem_free_pct": 3.2, "band": "Hot"}],
                         "findings": []})
    (d,) = dd["per_device"]
    cp = next(e for e in d["exposures"] if e["axis"] == "Control plane")
    assert cp["state"] == "risk"
    assert "None" not in cp["label"]
    assert "memory 3.2% free" in cp["label"]


def test_punchlist_folds_compound_patterns_once():
    dd = _dossiers_severe_core()
    base = ([], {}, {}, [], [], [], {}, [], [])
    with_fold = compute_migration_punchlist(*base, device_dossiers=dd)
    comp = [i for i in with_fold if i["category"] == "Compound risk"]
    assert len(comp) == 2
    assert any(i["title"].startswith("CR-01:") for i in comp)
    assert comp[0]["devices"] == ["core1"]
    # back-compat: omitting the register changes nothing
    assert [i for i in compute_migration_punchlist(*base)
            if i["category"] == "Compound risk"] == []


def test_brief_gains_asset_risk_axis_with_worst_asset_framing():
    dd = _dossiers_severe_core()
    brief = compute_executive_brief(
        health_scores=[{"switch": "core1", "score": 18, "band": "Critical"}],
        device_dossiers=dd)
    axis = next(a for a in brief["axes"] if a["axis"] == "Asset risk register")
    assert axis["severity"] == "Critical"
    assert "1 Severe" in axis["headline"] and "core1" in axis["headline"]
    # back-compat: no register -> no axis
    brief2 = compute_executive_brief(
        health_scores=[{"switch": "core1", "score": 18, "band": "Critical"}])
    assert all(a["axis"] != "Asset risk register" for a in brief2["axes"])


def test_device_risk_sheet_writer():
    openpyxl = __import__("pytest").importorskip("openpyxl")
    from cisco_toolkit.excel import DEVICE_RISK_SHEET_NAME, write_device_risk_sheet
    wb = openpyxl.Workbook()
    write_device_risk_sheet(wb, _dossiers_severe_core())
    ws = wb[DEVICE_RISK_SHEET_NAME]
    assert ws.cell(4, 1).value == "Device"
    assert ws.cell(5, 1).value == "core1"
    assert ws.cell(5, 6).value == "Severe"
    assert "CR-01" in str(ws.cell(5, 15).value)
    # empty register still writes an honest sheet
    wb2 = openpyxl.Workbook()
    write_device_risk_sheet(wb2, {})
    assert "nothing to register" in str(wb2[DEVICE_RISK_SHEET_NAME].cell(5, 1).value)


def test_dossier_critical_health_not_routine_on_info_blast_radius():
    """[audit-3 #11 false-health] a Critical-health / multi-red-axis switch banded 'Low / No stacked risk —
    routine' whenever its modeled blast radius was Info (impact=1 collapsed risk_index). Floor by red-axis count."""
    from cisco_toolkit.analyze import compute_device_dossiers
    fi = [{"host": "edge9", "severity": "Info", "stranded": 0, "vlans_impacted": 0, "detail": "No reachability impact."}]
    dA = compute_device_dossiers(health_scores=[{"switch": "edge9", "band": "Critical", "score": 12, "role": "access"}],
                                 failure_impact=fi)["per_device"][0]
    assert dA["risk_band"] != "Low" and "routine" not in dA["verdict"].lower()       # Critical health -> not routine
    dB = compute_device_dossiers(
        health_scores=[{"switch": "edge9", "band": "Good", "score": 80, "role": "access"}], failure_impact=fi,
        lifecycle_risk={"per_device": [{"host": "edge9", "model": "WS-C3560", "band": "Past-LDoS"}]},
        software_risk={"per_device": [{"host": "edge9", "train_band": "Replace/Upgrade", "config_assessable": True}],
                       "findings": [{"host": "edge9", "severity": "High"}]},
        security={"edge9": {"findings": [{"status": "fail", "severity": "high"}]}})["per_device"][0]
    assert dB["risk_band"] in ("Elevated", "Severe") and "routine" not in dB["verdict"].lower()   # 3 red axes
