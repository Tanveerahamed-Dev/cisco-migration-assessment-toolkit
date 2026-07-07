"""Tests for the self-healing nerve (cisco_toolkit.self_healing) — Phase 4, propose-only drift triage.

Distinct from tests/test_remediation.py (which pins analyze.compute_remediation_plan, the config-snippet
generator). Load-bearing properties here:

- drift is extracted from grounded fields (health_scores score/band, architecture_coverage status), with a
  severity, and is coverage-honest (a small drop or an 'Insufficient Data' side is NOT a regression; a
  not-observed→finding is flagged but marked possibly-new-visibility);
- each item routes to the right specialist and the plan is PROPOSE-ONLY (root-cause owner ≠ MOP author ≠
  verifier; a rollback to the baseline; intent is a MOP, never a device command);
- no drift is reported as "nothing to remediate", never as "healthy"; inputs are never mutated.
"""
import copy

from cisco_toolkit import self_healing as R


def _snap(health=None, coverage=None):
    s = {}
    if health is not None:
        s["health_scores"] = health
    if coverage is not None:
        s["architecture_coverage"] = {"classes": coverage}
    return s


def _h(switch, score, band="Good"):
    return {"switch": switch, "score": score, "band": band}


def _c(key, status, label=None, findings=None):
    return {"key": key, "status": status, "label": label or key,
            "findings": findings or [], "observed": status != "not-observed"}


# --- drift extraction --------------------------------------------------------------------------

def test_health_regression_detected_with_severity():
    d = R.extract_drift(_snap(health=[_h("sw1", 90, "Good")]), _snap(health=[_h("sw1", 70, "Fair")]))
    assert len(d) == 1 and d[0]["kind"] == "health" and d[0]["subject"] == "sw1"
    assert d[0]["severity"] == "Medium"          # delta 20 -> Medium


def test_small_health_drop_is_not_drift():
    assert R.extract_drift(_snap(health=[_h("sw1", 90)]), _snap(health=[_h("sw1", 85)])) == []   # 5 < 10


def test_critical_band_is_critical_severity():
    d = R.extract_drift(_snap(health=[_h("sw1", 90, "Good")]), _snap(health=[_h("sw1", 40, "Critical")]))
    assert d[0]["severity"] == "Critical"


def test_insufficient_data_is_not_a_regression():
    d = R.extract_drift(_snap(health=[_h("sw1", 90, "Good")]),
                        _snap(health=[_h("sw1", 10, "Insufficient Data")]))
    assert d == []                                # data-quality, not a health regression (coverage-honest)


def test_coverage_clean_to_finding_is_high():
    old = _snap(coverage=[_c("aci", "clean")])
    new = _snap(coverage=[_c("aci", "finding", label="Cisco ACI", findings=["aci-node-not-active"])])
    d = R.extract_drift(old, new)
    assert len(d) == 1 and d[0]["severity"] == "High" and d[0]["kind"] == "coverage"


def test_coverage_not_observed_to_finding_is_medium_and_flagged_as_visibility():
    d = R.extract_drift(_snap(coverage=[_c("mpls", "not-observed")]),
                        _snap(coverage=[_c("mpls", "finding", findings=["mpls-ldp-session-down"])]))
    assert d[0]["severity"] == "Medium" and "new visibility" in d[0]["detail"]


def test_severity_sorted_worst_first():
    old = _snap(health=[_h("sw1", 90), _h("sw2", 90, "Good")], coverage=[_c("aci", "clean")])
    new = _snap(health=[_h("sw1", 70, "Fair"), _h("sw2", 40, "Critical")], coverage=[_c("aci", "finding")])
    sevs = [x["severity"] for x in R.extract_drift(old, new)]
    assert sevs == sorted(sevs, key=lambda s: R.SEV_ORDER.index(s)) and sevs[0] == "Critical"


# --- routing + propose-only plan ---------------------------------------------------------------

def test_routing_security_vs_dc():
    dc = R.propose_remediation(_snap(coverage=[_c("aci", "clean")]),
                               _snap(coverage=[_c("aci", "finding")]))["plan"][0]
    sec = R.propose_remediation(_snap(coverage=[_c("ise", "clean")]),
                                _snap(coverage=[_c("ise", "finding")]))["plan"][0]
    assert dc["root_cause_owner"] == "topology-reachability-analyst"       # aci -> dc pack
    assert sec["root_cause_owner"] == "config-security-auditor"            # ise -> sec pack


def test_plan_is_propose_only():
    p = R.propose_remediation(_snap(coverage=[_c("aci", "clean")]),
                              _snap(coverage=[_c("aci", "finding")]), baseline_id="base-2026")["plan"][0]
    assert p["mop_author"] == "mop-change-author" and p["verifier"] == "nrfu-validator"
    assert p["root_cause_owner"] != p["mop_author"] != p["verifier"]       # proposer != verifier
    assert "base-2026" in p["rollback"] and "CAB" in p["rollback"]
    assert "MOP" in p["proposed_intent"] and "device" in p["proposed_intent"].lower()   # never a device write


def test_no_drift_is_honest_not_healthy():
    res = R.propose_remediation(_snap(health=[_h("sw1", 90)]), _snap(health=[_h("sw1", 90)]))
    assert res["plan"] == [] and "nothing to remediate" in res["note"]
    assert "not an assertion that the network is healthy" in res["note"]


def test_inputs_not_mutated():
    old, new = _snap(coverage=[_c("aci", "clean")]), _snap(coverage=[_c("aci", "finding")])
    o2, n2 = copy.deepcopy(old), copy.deepcopy(new)
    R.propose_remediation(old, new)
    assert old == o2 and new == n2
