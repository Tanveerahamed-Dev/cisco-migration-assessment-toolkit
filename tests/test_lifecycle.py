"""NEW-V3.23.117: hardware lifecycle (EoL / End-of-Support) risk. eoldb family matching + band
classification relative to a FIXED assessment date (deterministic). The pipeline golden excludes the
date-dependent lifecycle_risk section; this file pins the logic."""
import json

from cisco_toolkit import eoldb
from cisco_toolkit.analyze import compute_lifecycle_risk

ASOF = "2026-06-07"


def test_eoldb_family_matching_longest_prefix():
    assert eoldb.lifecycle_for("WS-C4948E-F")["platform"] == "Catalyst 4948E"
    assert eoldb.lifecycle_for("WS-C4948")["platform"] == "Catalyst 4948"          # shorter family, not 4948E
    assert eoldb.lifecycle_for("N5K-C56128P")["platform"] == "Nexus 5600"
    assert eoldb.lifecycle_for("C9300-48T")["conf"] == "active"
    assert eoldb.lifecycle_for("N9K-C93180YC-EX")["conf"] == "active"
    assert eoldb.lifecycle_for("") is None and eoldb.lifecycle_for("TOTALLY-MADE-UP") is None


def _dev(model, sw="x"):
    return {"sw1": {"model": model, "sw_version": sw}}


def test_bands_past_ldos_near_active_pasteos_unknown():
    def band(model):
        return compute_lifecycle_risk(_dev(model), asof=ASOF)["per_device"][0]["band"]
    assert band("WS-C4948E-F") == "Past-LDoS"        # LDoS 2022-10-31
    assert band("WS-C3850-48P") == "Near-LDoS"       # LDoS 2026-10-31 (within 1yr of 2026-06)
    assert band("C9300-48T") == "Active"             # no EoL announced
    assert band("WS-C2960X-48FPD-L") == "Past-EoS"   # EoS 2025-04, LDoS 2030 -> past sale, still in support
    assert band("WeirdModel-X") == "Unknown"


def test_derived_tag_and_status_string():
    d = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)["per_device"][0]
    assert d["conf"] == "derived" and "Past end-of-support" in d["status"] and d["source"]
    assert d["ldos"] == "2022-10-31"


def test_risks_and_summary_rollup():
    devs = {"a": {"model": "WS-C4948E-F"}, "b": {"model": "WS-C3850-48P"},
            "c": {"model": "C9300-48T"}, "d": {"model": ""}}
    out = compute_lifecycle_risk(devs, asof=ASOF)
    s = out["summary"]
    assert s["n_devices"] == 4
    assert (s["n_past_ldos"], s["n_near"], s["n_active"], s["n_unknown"]) == (1, 1, 1, 1)
    kinds = {r["severity"]: r for r in out["risks"]}
    assert kinds["Critical"]["devices"] == ["a"] and kinds["High"]["devices"] == ["b"]
    assert out["asof"] == ASOF and out["note"]
    assert s["by_platform"][0]["band"] == "Past-LDoS"      # worst-first


def test_empty_and_deterministic():
    assert compute_lifecycle_risk(None)["per_device"] == []
    assert compute_lifecycle_risk({})["summary"]["n_devices"] == 0
    a = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    b = compute_lifecycle_risk(_dev("WS-C4948E-F"), asof=ASOF)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
