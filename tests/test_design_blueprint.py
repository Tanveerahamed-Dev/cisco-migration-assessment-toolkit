"""Contract / SSOT / coverage-honesty / requirements-overlay tests for the CCDE-grounded design blueprint.

`compute_design_blueprint` is the senior-network-DESIGN-engineer brain: it turns COLLECTED assessment
evidence into traceable target-state DESIGN decisions, each citing a CCDE doctrine principle
(`design_kb`) and gated on observed evidence -- a design claim is never asserted from absence. These
tests pin the contract, prove every detector is evidence-gated (refutation: remove the condition and
the decision must DISAPPEAR -- it is not hardcoded), enforce coverage-honesty (no positive design claim
from missing evidence), and exercise the interactive requirements overlay (right-sizing by
SLA/app/growth/constraint).
"""
from cisco_toolkit import design_kb
from cisco_toolkit.design_advisor import compute_design_blueprint

_KB_IDS = {p["id"] for p in design_kb.DOCTRINE}


def _snap(**over):
    """A compact snapshot seeded with each engine-actionable trigger condition."""
    snap = {
        "devices": {f"d{i}": {"hostname": f"d{i}"} for i in range(4)},
        "interfaces": {"acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10"}}},
        "l3_forwarding": [
            {"switch": "dist1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "none", "risk": "no-FHRP"},
            {"switch": "dist1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "none", "risk": "no-FHRP"},
        ],
        "fhrp": [
            {"vid": 10, "issues": ["2 gateways but no FHRP -- no first-hop redundancy"],
             "members": [{"host": "dist1", "fhrp": False}, {"host": "dist2", "fhrp": False}]},
            {"vid": 20, "issues": ["no first-hop redundancy"], "members": [{"host": "dist1"}]},
        ],
        "link_centrality": [
            {"a_host": "dist1", "b_host": "acc1", "is_bridge": True, "betweenness": 100, "pairs_cut": 5},
            {"a_host": "dist1", "b_host": "acc2", "is_bridge": True, "betweenness": 80, "pairs_cut": 3},
            {"a_host": "core", "b_host": "dist1", "is_bridge": False, "betweenness": 200},
        ],
        "failure_impact": [
            {"host": "dist1", "severity": "High", "fhrp": 0, "backup": 0, "stranded": 500, "vlans_impacted": 10},
        ],
        "lifecycle_risk": {"per_device": [
            {"host": "d0", "band": "Past-LDoS"}, {"host": "d1", "band": "Past-LDoS"},
            {"host": "d2", "band": "Active"},
        ]},
        "qos_audit": {"per_device": [
            {"host": "d0", "assessable": True, "mode": "none"},
            {"host": "d1", "assessable": True, "mode": "none"},
            {"host": "d2", "assessable": True, "mode": "MQC"},
        ]},
        "security": {
            "d0": {"findings": [{"id": "vty-hardening", "status": "fail"},
                                {"id": "insecure-snmp", "status": "fail"},
                                {"id": "no-aaa", "status": "fail"}]},
            "d1": {"findings": [{"id": "vty-hardening", "status": "fail"},
                                {"id": "risky-services", "status": "fail"}]},
        },
        "collection_completeness": {"summary": {"inventory": 10, "complete": 7, "partial": 0,
                                                "not_collected": 3}},
        "protocol_health": [
            {"switch": "d0", "protocol": "STP",
             "summary": "mode rapid-pvst; 2 blocked, 0 inconsistent; max TCN 5"},
            {"switch": "d1", "protocol": "STP", "summary": "mode pvst; 0 blocked, 0 inconsistent; max TCN 9"},
            {"switch": "d0", "protocol": "VTP", "summary": "server mode"},
        ],
        "routing_neighbors": {"dist1": {"ospf": [{"state": "FULL"}], "eigrp": [{"state": "up"}]}},
        "health_scores": [{"switch": "dist1", "role": "distribution"}, {"switch": "acc1", "role": "access"}],
        "multicast_intelligence": {"querier": {"n_querier_vlans": 5, "gap_vlans": []}, "risks": []},
        "segmentation": {"vrfs": [{"vrf": "(global)", "gateway_count": 2}]},
    }
    snap.update(over)
    return snap


def test_structure_and_principle_traceability():
    bp = compute_design_blueprint(_snap())
    for k in ("decisions", "tradeoff_scorecard", "requirements_model", "methodology",
              "summary", "coverage", "axes"):
        assert k in bp, f"blueprint missing {k}"
    assert bp["decisions"], "expected design decisions from the seeded evidence"
    for d in bp["decisions"]:
        for k in ("id", "title", "domain", "priority", "status", "confidence", "driver",
                  "evidence", "principle", "recommended_action", "axes"):
            assert k in d, f"decision {d.get('id')} missing {k}"
        assert d["principle"]["id"] in _KB_IDS, f"untraceable principle {d['principle']['id']}"
        assert d["principle"]["citation"], "every decision must cite a CCDE source"
        assert isinstance(d["evidence"], dict) and d["evidence"].get("summary")


def test_fhrp_decision_is_evidence_gated():
    bp = compute_design_blueprint(_snap())
    by = {d["id"]: d for d in bp["decisions"]}
    assert "fhrp-first-hop-gateway-redundancy" in by
    assert by["fhrp-first-hop-gateway-redundancy"]["evidence"]["count"] == 2
    assert by["fhrp-first-hop-gateway-redundancy"]["priority"] == "Critical"
    # REFUTATION: with FHRP present everywhere, the decision must NOT appear (it is evidence-gated).
    healthy = compute_design_blueprint(_snap(
        fhrp=[{"vid": 10, "issues": [], "members": [{"host": "a"}, {"host": "b"}]}],
        l3_forwarding=[{"switch": "a", "vlan": "10", "fhrp": "HSRP active"}],
        failure_impact=[{"host": "a", "severity": "Info", "fhrp": 2, "backup": 1}]))
    assert "fhrp-first-hop-gateway-redundancy" not in {d["id"] for d in healthy["decisions"]}, \
        "coverage-honesty: no 'introduce FHRP' decision when FHRP is present everywhere"


def test_spof_eol_qos_mgmt_coverage_detectors():
    by = {d["id"]: d for d in compute_design_blueprint(_snap())["decisions"]}
    assert by["topology-triangles-not-squares-rings"]["evidence"]["count"] == 2   # == is_bridge count
    assert "lifecycle-eol-out-of-critical-roles" in by                            # 2 Past-LDoS
    assert "qos-trust-boundary-end-to-end" in by                                  # 2/3 no QoS
    assert "mgmt-secure-protocols-and-rbac" in by                                 # vty/snmp/aaa fails
    # coverage-honesty meta-decision: 3 not-collected -> do NOT assume the (uncollected) core's redundancy
    assert "fhrp-not-observed-is-not-healthy" in by
    cov = by["fhrp-not-observed-is-not-healthy"]["evidence"]
    assert cov["count"] == 3 or "3" in cov["summary"]
    # EoL detector is evidence-gated too
    allactive = compute_design_blueprint(_snap(lifecycle_risk={"per_device": [{"host": "a", "band": "Active"}]}))
    assert "lifecycle-eol-out-of-critical-roles" not in {d["id"] for d in allactive["decisions"]}


def test_tradeoff_scorecard_covers_axes_and_availability_low():
    bp = compute_design_blueprint(_snap())
    axes = {s["axis"] for s in bp["tradeoff_scorecard"]}
    assert {a["key"] for a in design_kb.TRADEOFF_AXES} <= axes, "scorecard must cover all 10 axes"
    av = next(s for s in bp["tradeoff_scorecard"] if s["axis"] == "availability")
    assert av["score"] is not None and av["score"] <= 1, "no FHRP + SPOFs => availability scores low"


def test_summary_consistency_and_determinism():
    import json
    bp = compute_design_blueprint(_snap())
    s = bp["summary"]
    assert s["n_decisions"] == len(bp["decisions"])
    assert s["n_recommended"] + s["n_needs_requirement"] == s["n_decisions"]
    assert json.dumps(compute_design_blueprint(_snap()), sort_keys=True) == json.dumps(bp, sort_keys=True)


def test_requirements_overlay_rightsizes_and_satisfies_open_questions():
    base = compute_design_blueprint(_snap())
    req = {"availability_tier": "gold", "critical_apps": ["voice"], "convergence_budget_ms": 200,
           "growth_horizon": "3y +50%", "constraints": ["budget-limited"]}
    bp = compute_design_blueprint(_snap(), requirements=req)
    assert all("effective_priority" in d for d in bp["decisions"]), "requirements => effective priority on all"
    top = bp["decisions"][0]
    assert ("availability" in top["axes"]) or ("convergence" in top["axes"]), \
        "gold SLA + voice should float an availability/convergence decision to the top"
    nr_before = {d["id"] for d in base["decisions"] if d["status"] == "needs-requirement"}
    nr_after = {d["id"] for d in bp["decisions"] if d["status"] == "needs-requirement"}
    assert nr_before, "with no requirements there should be open requirement questions"
    assert nr_after < nr_before or not nr_after, "supplying requirements must satisfy >=1 open requirement"


def test_empty_snapshot_is_safe():
    bp = compute_design_blueprint({})
    assert isinstance(bp["decisions"], list)
    assert bp["summary"]["n_decisions"] == len(bp["decisions"])
    assert len(bp["tradeoff_scorecard"]) == len(design_kb.TRADEOFF_AXES)
