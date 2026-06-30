"""Tests for per-feature ConfigCompliance decomposition (roadmap I2).

compute_golden_drift gives ONE compliance number + a flat missing[] per device. Nautobot Golden Config
decomposes that into per-FEATURE rows (aaa / ntp / snmp / logging / …) so a reviewer sees *which* policy
area drifted. This is a pure projection over the existing golden-drift output — no new collection, no
change to compute_golden_drift itself.
"""
from cisco_toolkit import feature_compliance as fc


DRIFT = {
    "mode": "majority",
    "baseline": ["aaa new-model", "ntp server 1.1.1.1", "logging host 2.2.2.2",
                 "spanning-tree mode rapid-pvst", "snmp-server community public ro"],
    "per_device": [
        {"host": "sw1", "compliance_pct": 80, "n_missing": 1, "missing": ["ntp server 1.1.1.1"]},
        {"host": "sw2", "compliance_pct": 60, "n_missing": 2,
         "missing": ["aaa new-model", "snmp-server community public ro"]},
        {"host": "sw3", "compliance_pct": 100, "n_missing": 0, "missing": []},
    ],
    "summary": {"mode": "majority", "n_devices": 3, "n_baseline": 5, "n_drifting": 2, "avg_compliance_pct": 80},
}


def test_buckets_lines_into_features():
    out = fc.compute_feature_compliance(DRIFT)
    by = {(r["host"], r["feature"]): r for r in out["per_device_feature"]}
    assert by[("sw1", "ntp")]["status"] == "drift" and by[("sw1", "ntp")]["n_missing"] == 1
    assert by[("sw1", "aaa")]["status"] == "compliant"
    assert by[("sw2", "aaa")]["status"] == "drift"
    assert by[("sw2", "snmp")]["status"] == "drift"
    assert by[("sw3", "ntp")]["status"] == "compliant"


def test_feature_rollup_counts_drifting_devices():
    out = fc.compute_feature_compliance(DRIFT)
    feats = {f["feature"]: f for f in out["features"]}
    assert feats["ntp"]["n_drifting"] == 1
    assert feats["aaa"]["n_drifting"] == 1
    assert feats["snmp"]["n_drifting"] == 1
    assert feats["logging"]["n_drifting"] == 0
    # every baseline line landed in exactly one feature (5 baseline lines -> 5 features here)
    assert sum(f["n_baseline"] for f in out["features"]) == 5


def test_empty_drift_is_safe():
    out = fc.compute_feature_compliance({})
    assert out["per_device_feature"] == [] and out["features"] == []


def test_unknown_line_falls_into_other():
    drift = {"baseline": ["foobar wibble"], "per_device": [{"host": "x", "missing": ["foobar wibble"]}]}
    out = fc.compute_feature_compliance(drift)
    assert any(r["feature"] == "other" and r["status"] == "drift" for r in out["per_device_feature"])


def test_golden_file_re_prefix_classified_to_feature():
    # golden-file requirements use the 're:<pattern>' form; the feature must be read past the re: prefix.
    drift = {"baseline": [r"re:ntp server \S+", r"re:logging host \S+", "aaa new-model"],
             "per_device": [{"host": "c1", "missing": [r"re:ntp server \S+", r"re:logging host \S+"]}]}
    out = fc.compute_feature_compliance(drift)
    feats = {f["feature"] for f in out["features"]}
    assert "ntp" in feats and "logging" in feats and "other" not in feats   # was: all three landed in 'other'
