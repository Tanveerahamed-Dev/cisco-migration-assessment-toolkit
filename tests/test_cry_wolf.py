"""PHASE 2.2: cry-wolf fixes - findings dedup, asset-criticality weighting,
and the score-sensitivity sweep."""
from cisco_toolkit import analyze   # ScoringConfig / _host_role live here since PHASE 2.7 steps 10/15


def _errdis(cp, port):
    d = cp.InterfaceData(port=port)
    d.status = "err-disabled"
    return d


# --------------------------------------------------------------------------- #
# Findings dedup
# --------------------------------------------------------------------------- #
def test_findings_deduplicate_errdisabled_per_switch(cp):
    ifaces = {f"Gi0/{i}": _errdis(cp, f"Gi0/{i}") for i in range(1, 7)}   # 6 err-disabled
    findings = analyze.compute_findings({"sw1": ifaces})
    errdis = [f for f in findings if f[1] == "Err-disabled"]
    assert len(errdis) == 1                       # ONE row, not six
    assert "(6)" in errdis[0][2]                  # scope shows the count
    assert "Gi0/1" in errdis[0][3] and "Gi0/6" in errdis[0][3]   # detail lists ports


# --------------------------------------------------------------------------- #
# Asset-criticality role inference + weighting
# --------------------------------------------------------------------------- #
def test_host_role_inference(cp):
    svi = cp.InterfaceData(port="Vlan10"); svi.svi_ip = "10.0.10.1"
    assert analyze._host_role({"Vlan10": svi}) == "distribution"
    assert analyze._host_role({"Gi0/1": cp.InterfaceData(port="Gi0/1")}) == "access"
    assert analyze._host_role({}) == "access"


def test_default_criticality_weights_distribution(cp):
    # Activated 2026-06-06: the DEFAULT config now weights a gateway/distribution switch's
    # deductions by 1.2 (asset criticality) — same finding, harder penalty than an access closet.
    svi = cp.InterfaceData(port="Vlan10"); svi.svi_ip = "10.0.10.1"
    all_if = {"dist": {"Vlan10": svi}, "acc": {"Gi0/1": cp.InterfaceData(port="Gi0/1")}}
    ph = [{"switch": "dist", "port": "Gi0/1", "risk": "err-disabled"},
          {"switch": "acc", "port": "Gi0/1", "risk": "err-disabled"}]
    recs = {r["switch"]: r for r in cp.compute_health_scores(all_if, ph, [], [], [])}
    assert recs["dist"]["score"] == 90 and recs["dist"]["role"] == "distribution"   # 8 * 1.2 -> 10
    assert recs["acc"]["score"] == 92 and recs["acc"]["role"] == "access"           # 8 * 1.0 -> 8
    assert recs["dist"]["criticality"] == 1.2 and recs["acc"]["criticality"] == 1.0


def test_criticality_weights_distribution_more(cp):
    svi = cp.InterfaceData(port="Vlan10"); svi.svi_ip = "10.0.10.1"
    all_if = {"dist": {"Vlan10": svi}, "acc": {"Gi0/1": cp.InterfaceData(port="Gi0/1")}}
    ph = [{"switch": "dist", "port": "Gi0/1", "risk": "err-disabled"},
          {"switch": "acc", "port": "Gi0/1", "risk": "err-disabled"}]
    cfg = analyze.ScoringConfig(criticality_factors={"core": 2.0, "distribution": 2.0, "access": 1.0})
    recs = {r["switch"]: r["score"] for r in cp.compute_health_scores(all_if, ph, [], [], [], config=cfg)}
    assert recs["dist"] == 84            # 8 * 2.0 = 16 deduction
    assert recs["acc"] == 92             # 8 * 1.0 = 8 deduction
    assert recs["dist"] < recs["acc"]    # the gateway switch is penalised harder


# --------------------------------------------------------------------------- #
# Sensitivity sweep
# --------------------------------------------------------------------------- #
def test_sensitivity_sweep_shape_and_flip(cp):
    all_if = {"h": {}}
    xl = [{"id": "CL-01", "severity": "Critical", "hosts": ["h"]}]   # -18 -> 82 (Good)
    recs = cp.compute_score_sensitivity(all_if, [], [], xl, [])
    assert len(recs) == 16                       # 4 weight groups x 4 deltas
    # Halving the cross-layer weight (-18 -> -9) lifts h from Good(82) to Excellent(91).
    xl_50 = [r for r in recs if r["perturbation"] == "XL -50%"][0]
    assert xl_50["switches_changed_band"] >= 1
    assert "h" in xl_50["changed"]


def test_sensitivity_clean_fleet_has_no_flips(cp):
    recs = cp.compute_score_sensitivity({"a": {}, "b": {}}, [], [], [], [])
    assert recs and all(r["switches_changed_band"] == 0 for r in recs)   # all Excellent, nothing flips
