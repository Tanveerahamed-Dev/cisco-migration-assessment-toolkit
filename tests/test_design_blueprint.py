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


# --------------------------------------------------------------------------- newly-wired detectors
def test_timesync_logging_detector_evidence_gated():
    """no-ntp / no-logging => an operational time-sync + centralised-logging baseline decision,
    distinct from attack-surface hardening; absent the finding the decision must disappear."""
    snap = _snap(security={
        "d0": {"findings": [{"id": "no-ntp", "status": "fail"}]},
        "d1": {"findings": [{"id": "no-logging", "status": "fail"}, {"id": "no-ntp", "status": "fail"}]},
    })
    by = {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}
    assert "mgmt-time-sync-logging-baseline" in by
    d = by["mgmt-time-sync-logging-baseline"]
    assert d["evidence"]["count"] == 2 and {"d0", "d1"} == set(d["evidence"]["devices"])
    # REFUTATION: NTP+logging healthy everywhere -> no time-sync decision.
    healthy = compute_design_blueprint(_snap(security={
        "d0": {"findings": [{"id": "no-ntp", "status": "pass"}, {"id": "no-logging", "status": "pass"}]}}))
    assert "mgmt-time-sync-logging-baseline" not in {d["id"] for d in healthy["decisions"]}


def test_voice_qos_detector_evidence_gated():
    """A device with voice/real-time edge ports but no QoS policy => no bounded priority queue
    (RFC 4594). Gated on n_voice_if>0 AND mode 'none'; otherwise silent (coverage honesty)."""
    snap = _snap(qos_audit={"per_device": [
        {"host": "d0", "assessable": True, "mode": "none", "n_voice_if": 4},
        {"host": "d1", "assessable": True, "mode": "none", "n_voice_if": 0},   # no voice -> not voice-gated
        {"host": "d2", "assessable": True, "mode": "MQC", "n_voice_if": 8},    # has QoS -> bounded
    ]})
    by = {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}
    assert "qos-voice-priority-bounded" in by
    assert by["qos-voice-priority-bounded"]["evidence"]["count"] == 1            # only d0
    assert by["qos-voice-priority-bounded"]["evidence"]["devices"] == ["d0"]
    # REFUTATION: no voice edge ports anywhere -> no voice-priority decision (even with mode none).
    novoice = compute_design_blueprint(_snap(qos_audit={"per_device": [
        {"host": "d0", "assessable": True, "mode": "none", "n_voice_if": 0}]}))
    assert "qos-voice-priority-bounded" not in {d["id"] for d in novoice["decisions"]}


def test_phased_cutover_detector_evidence_gated():
    """Computed move-groups => the cutover must be phased build-before-break, not big-bang;
    no move-groups (e.g. nothing collected) => no planning claim."""
    snap = _snap(move_groups=[{"switches": ["d0", "d1"]}, {"switches": ["d2"]}])
    by = {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}
    assert "scenario-build-before-break-phased-cutover" in by
    assert by["scenario-build-before-break-phased-cutover"]["evidence"]["count"] == 2
    # REFUTATION: no move-groups -> no phased-cutover decision.
    nomg = compute_design_blueprint(_snap(move_groups=[]))
    assert "scenario-build-before-break-phased-cutover" not in {d["id"] for d in nomg["decisions"]}


def test_l2_failure_domain_detector_evidence_gated():
    """A user VLAN spanning many switches => an oversized Layer-2 failure domain (a bridged VLAN is a
    single failure domain -- ipSpace/Pepelnjak; Cisco CCDA). Read from the engine's canonical
    move_groups[].spanning_vlans; remove the wide span and the decision disappears."""
    snap = _snap(move_groups=[{"switches": ["a", "b", "c"],
                               "spanning_vlans": [[124, "BC_ENG", 11], [200, "OOB", 4]],
                               "vlan1_spans": True}])
    by = {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}
    assert "dc-bound-layer2-failure-domain" in by
    d = by["dc-bound-layer2-failure-domain"]
    assert d["evidence"]["count"] == 1            # only VLAN 124 (11>=8); VLAN 200 (4) is below threshold
    assert "124" in d["evidence"]["summary"]
    # REFUTATION: no wide span and no VLAN-1 spread -> no failure-domain decision
    narrow = compute_design_blueprint(_snap(move_groups=[
        {"switches": ["a"], "spanning_vlans": [[50, "X", 3]], "vlan1_spans": False}]))
    assert "dc-bound-layer2-failure-domain" not in {x["id"] for x in narrow["decisions"]}


def test_public_sourced_principles_present_and_honest():
    """The two public-sourced additions (B) exist, carry a citation, and declare actionability honestly:
    the L2-failure-domain principle is wired (engine_actionable); the minimize-complexity doctrine is not."""
    fd = design_kb.by_id("dc-bound-layer2-failure-domain")
    cx = design_kb.by_id("methodology-minimize-accidental-complexity")
    assert fd and cx, "both public-sourced principles must exist in the KB"
    assert fd.get("citation") and cx.get("citation"), "every principle must cite its source"
    assert fd.get("engine_actionable") is True       # emitted by _d_l2_faildomain
    assert cx.get("engine_actionable") is False       # doctrine; no clean auto-trigger -> honest


def test_firewall_design_principles_present_and_honest():
    """Firewall-in-different-designs doctrine (perimeter/DMZ topology, DC east-west microsegmentation,
    stateful flow-symmetry/insertion) is in the KB, cited, carries a recommended action, and is honestly
    NON-actionable -- the L1-L4 switch/router assessment does not collect firewall state, so these inform
    the HLD/design narrative and the design chat, not auto-emitted decisions."""
    fw = ["security-firewall-perimeter-dmz-topology",
          "security-firewall-dc-eastwest-microsegmentation",
          "security-firewall-flow-symmetry-insertion"]
    for pid in fw:
        p = design_kb.by_id(pid)
        assert p, f"missing firewall principle {pid}"
        assert p.get("citation"), f"{pid} must cite its source"
        assert p.get("recommended_action"), f"{pid} must carry a recommended action"
        assert p.get("engine_actionable") is False, f"{pid} honest non-actionable (no firewall evidence collected)"
    assert set(fw) <= {p["id"] for p in design_kb.by_domain("security")}, "firewall principles are security-domain"


def _maximal_snap():
    """A snapshot seeded to trigger EVERY evidence-gated detector at once (no requirements supplied,
    so the requirement-gated open questions also surface)."""
    return _snap(
        security={
            "d0": {"findings": [{"id": "vty-hardening", "status": "fail"},
                                {"id": "insecure-snmp", "status": "fail"},
                                {"id": "no-aaa", "status": "fail"},
                                {"id": "no-ntp", "status": "fail"},
                                {"id": "risky-services", "status": "fail"}]},
            "d1": {"findings": [{"id": "no-logging", "status": "fail"},
                                {"id": "no-banner", "status": "fail"}]},
        },
        qos_audit={"per_device": [
            {"host": "d0", "assessable": True, "mode": "none", "n_voice_if": 4},
            {"host": "d1", "assessable": True, "mode": "none", "n_voice_if": 0},
        ]},
        move_groups=[{"switches": ["d0", "d1"], "spanning_vlans": [[124, "BC_ENG", 9]],
                      "vlan1_spans": True}, {"switches": ["d2"]}],
        multicast_intelligence={"querier": {"n_querier_vlans": 5, "gap_vlans": [148, 611]},
                                "risks": [{"kind": "no-querier"}]},
        l3_forwarding=[{"switch": "dist1", "vlan": str(v), "svi_ip": f"10.0.{v}.1",
                        "fhrp": "none", "risk": "no-FHRP"} for v in range(10, 32)],
        interfaces={f"acc{v}": {f"Gi1/0/{v}": {"switchport_mode": "Access", "vlan": str(v)}}
                    for v in range(10, 32)},
        segmentation={"vrfs": [{"vrf": "(global)", "gateway_count": 22}]},
    )


def test_dc_fabric_choices_are_requirement_gated():
    """Collapsed-core vs three-tier, and spine-leaf/EVPN vs collapsed-core, are scale/growth/east-west
    CHOICES the engine cannot OBSERVE (only a requirements register can decide). So they surface as open
    design questions, and flip to recommended once a growth horizon is supplied -- design top-down from
    the WHY, never assume the fabric. (Grounded in Cisco campus/DC CVD + leaf-spine design guidance.)"""
    base = compute_design_blueprint(_snap())
    open_ids = {d["id"] for d in base["decisions"] if d["status"] == "needs-requirement"}
    assert {"dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed"} <= open_ids
    bp = compute_design_blueprint(_snap(), requirements={"growth_horizon": "3y +60% east-west"})
    by = {d["id"]: d for d in bp["decisions"]}
    for pid in ("dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed"):
        assert by[pid]["status"] == "recommended", f"{pid} must flip to recommended once growth is given"
    # re-promoted: both are once again engine_actionable principles (and now honestly emitted)
    ea = {p["id"] for p in design_kb.engine_actionable()}
    assert {"dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed"} <= ea


def test_every_engine_actionable_principle_is_emitted():
    """COVERAGE-HONESTY LOCK: `engine_actionable` must mean the advisor actually emits a decision for
    that principle's trigger. If a principle claims engine-actionability the advisor can't deliver
    (or a new detector goes un-wired), this fails -- the design brain may not overstate its coverage."""
    bp = compute_design_blueprint(_maximal_snap())            # no requirements -> needs-requirement decisions too
    emitted = {d["id"] for d in bp["decisions"]}
    ea = {p["id"] for p in design_kb.engine_actionable()}
    missing = ea - emitted
    assert not missing, f"engine_actionable principles never emitted by the advisor: {sorted(missing)}"
    # and conversely every emitted, evidence-grounded decision must be a known KB principle
    assert emitted <= _KB_IDS


# ----------------------------------------------------------- A: requirements register input (the WHY)
def test_load_requirements_parses_register_and_is_defensive(tmp_path):
    """`load_requirements` reads a design requirements register (JSON) into the recognised keys, accepts
    a {"requirements": {...}} wrapper, drops unknown/empty keys, and degrades to {} on missing/malformed
    input (non-fatal -- the design then surfaces the open questions rather than assuming)."""
    import json
    from cisco_toolkit.design_advisor import load_requirements, REQUIREMENTS_KEYS
    assert set(REQUIREMENTS_KEYS) == {"availability_tier", "critical_apps", "convergence_budget_ms",
                                      "growth_horizon", "constraints", "data_classification", "address_space",
                                      "vlan_zones"}
    p = tmp_path / "req.json"
    p.write_text(json.dumps({"availability_tier": "gold", "critical_apps": ["voice"],
                             "growth_horizon": "3y +50%", "junk": "ignored", "constraints": []}), encoding="utf-8")
    req = load_requirements(str(p))
    assert req["availability_tier"] == "gold" and req["critical_apps"] == ["voice"]
    assert "junk" not in req and "constraints" not in req            # unknown + empty dropped
    wrap = tmp_path / "w.json"
    wrap.write_text(json.dumps({"requirements": {"availability_tier": "silver"}}), encoding="utf-8")
    assert load_requirements(str(wrap)) == {"availability_tier": "silver"}
    assert load_requirements(None) == {}                              # defensive
    assert load_requirements(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"; bad.write_text("{not json", encoding="utf-8")
    assert load_requirements(str(bad)) == {}


def test_requirements_register_closes_the_loop():
    """The whole point of A: a supplied register right-sizes the blueprint -- effective_priority on every
    decision, and the growth-gated DC-fabric choices flip from open-question to recommended."""
    snap = _snap()
    base = compute_design_blueprint(snap)
    assert not any("effective_priority" in d for d in base["decisions"])   # no register -> no right-sizing
    bp = compute_design_blueprint(snap, {"growth_horizon": "3y +60%", "availability_tier": "gold"})
    assert all("effective_priority" in d for d in bp["decisions"])
    by = {d["id"]: d for d in bp["decisions"]}
    assert by["dc-three-tier-vs-collapsed-core"]["status"] == "recommended"
    assert bp["requirements_model"]["provided"] is True


# ------------------------------------------------------- B: full doctrine surfaced (not just decisions)
def test_blueprint_carries_full_doctrine_catalogue():
    """B: the blueprint publishes the FULL design doctrine grouped by domain -- so every surface can
    reason with all principles, not only the ~23 the collected evidence happens to trigger. Each entry
    carries a citation + recommended action + its honest engine_actionable flag."""
    bp = compute_design_blueprint(_snap())
    doc = bp.get("doctrine")
    assert isinstance(doc, dict) and doc, "blueprint must carry a doctrine catalogue"
    flat = [p for items in doc.values() for p in items]
    assert len(flat) == len(design_kb.all_principles()), "doctrine must surface EVERY KB principle"
    for p in flat:
        assert p.get("title") and p.get("citation") and "engine_actionable" in p
    # the firewall doctrine (non-actionable -> never a decision) is still surfaced as reference doctrine
    titles = {p["title"] for p in flat}
    assert any("screened-subnet" in t or "DMZ" in t for t in titles), "firewall doctrine must be surfaced"
    # determinism (doctrine is a stable projection of the KB)
    import json
    assert json.dumps(compute_design_blueprint(_snap()).get("doctrine"), sort_keys=True) == json.dumps(doc, sort_keys=True)


# ----------------------------------------------- C: generated candidate target-state architecture
def test_target_state_is_evidence_grounded_and_requirement_gated():
    """C: the blueprint proposes a CANDIDATE target-state architecture, dimension by dimension, each
    tracing to evidence + a principle. The tier-model dimension is requirement-gated on growth (honest:
    a scale-driven CHOICE the L1-L4 evidence can't settle); supplying growth resolves it to a concrete
    recommendation. Evidence-backed dimensions (resilience/lifecycle/migration) are stated outright."""
    snap = _snap(move_groups=[{"switches": ["a", "b"], "spanning_vlans": [[124, "X", 9]], "vlan1_spans": True}])
    ts = compute_design_blueprint(snap)["target_state"]
    assert ts and isinstance(ts.get("dimensions"), list) and ts["dimensions"]
    areas = {d["area"]: d for d in ts["dimensions"]}
    assert "Topology / tier model" in areas
    assert areas["Topology / tier model"].get("requirement_needed") == "growth_horizon"   # gated w/o growth
    assert areas["Topology / tier model"]["confidence"] == "Requirement-needed"
    for d in ts["dimensions"]:                                                              # every dim is traceable
        assert d.get("area") and d.get("target") and d.get("rationale") and d.get("confidence")
    assert any("FHRP" in (d.get("current", "") + d.get("target", "")) for d in ts["dimensions"])  # no-FHRP evidence
    assert any("phase" in d.get("target", "").lower() for d in ts["dimensions"])           # migration waves
    # REFUTATION / requirement resolution: supply growth -> tier model resolves to a concrete target
    ts2 = compute_design_blueprint(snap, {"growth_horizon": "3y +50%"})["target_state"]
    tier2 = {d["area"]: d for d in ts2["dimensions"]}["Topology / tier model"]
    assert not tier2.get("requirement_needed") and tier2.get("target")
    assert tier2["confidence"] != "Requirement-needed"
    # coverage honesty: uncollected devices are surfaced, never assumed designed
    assert ts.get("coverage")


def test_target_state_replacement_bom_and_segmentation_plan():
    """C next-layer: the target-state carries a REPLACEMENT BoM (past/near-LDoS by current model, grounded
    in lifecycle_risk -- a successor SKU is chosen at detailed design, not invented) and a segmentation
    plan (observed VRF/VLAN state + a zone map that is REQUIREMENT-GATED on data_classification -- zones
    are never fabricated)."""
    snap = _snap(lifecycle_risk={"per_device": [
        {"host": "a", "band": "Past-LDoS", "model": "WS-C4948E"},
        {"host": "b", "band": "Past-LDoS", "model": "WS-C4948E"},
        {"host": "c", "band": "Near-LDoS", "model": "N5K-C56128P"},
        {"host": "d", "band": "Active", "model": "C9300"}]})
    ts = compute_design_blueprint(snap)["target_state"]
    bom = ts["replacement_bom"]
    assert bom["n_replace"] == 2 and ["WS-C4948E", 2] in bom["replace_now"]
    assert bom["n_refresh"] == 1 and ["N5K-C56128P", 1] in bom["refresh_soon"]
    seg = ts["segmentation_plan"]
    assert seg["status"] == "needs-requirement" and seg["requirement_needed"] == "data_classification"
    assert "target_zones" not in seg                                 # zones NOT invented absent the requirement
    # supply data_classification -> candidate zone map (no longer gated)
    ts2 = compute_design_blueprint(snap, {"data_classification": ["PCI", "corp", "OT"]})["target_state"]
    seg2 = ts2["segmentation_plan"]
    assert seg2["status"] == "candidate" and seg2["target_zones"] == ["PCI", "corp", "OT"]
    # REFUTATION: an all-active fleet yields an empty replacement BoM
    ts3 = compute_design_blueprint(_snap(lifecycle_risk={"per_device": [
        {"host": "x", "band": "Active", "model": "C9300"}]}))["target_state"]
    assert ts3["replacement_bom"]["n_replace"] == 0 and ts3["replacement_bom"]["replace_now"] == []


def test_addressing_plan_requirement_gated_and_allocates():
    """F1: the net-new IP plan is REQUIREMENT-GATED on address_space (never fabricates subnets); supply a
    supernet and it allocates a candidate per-VLAN /24 from within it, sized/flagged by observed host count."""
    import ipaddress
    snap = _snap()                                                   # vlans 10 (+access) and 20
    ap = compute_design_blueprint(snap)["target_state"]["addressing_plan"]
    assert ap["status"] == "needs-requirement" and ap["requirement_needed"] == "address_space"
    assert "subnets" not in ap                                       # no fabricated subnets absent the supernet
    ts2 = compute_design_blueprint(snap, {"address_space": "10.0.0.0/16"})["target_state"]
    ap2 = ts2["addressing_plan"]
    assert ap2["status"] == "candidate" and ap2["subnets"]
    net = ipaddress.ip_network("10.0.0.0/16")
    for s in ap2["subnets"]:
        assert ipaddress.ip_network(s["subnet"]).subnet_of(net)      # every allocation is from the supernet
        assert "vlan" in s and "subnet" in s
    # distinct allocations (no overlap collisions for the seeded small fleet)
    assert len({s["subnet"] for s in ap2["subnets"]}) == len(ap2["subnets"])


def test_addressing_zone_aware_summarizes_per_zone():
    """F1 (Mode B): an explicit vlan_zones map -> each zone gets ONE contiguous summarizable block; every
    VLAN's subnet sits inside its zone's block, zone blocks do NOT overlap, and a zone's summary is one prefix."""
    import ipaddress
    snap = _snap(l3_forwarding=[{"switch": "d", "vlan": str(v), "svi_ip": f"10.0.{v}.1"} for v in (10, 20, 30)])
    ts = compute_design_blueprint(snap, {"address_space": "10.80.0.0/16",
                                         "vlan_zones": {10: "PCI", 20: "corp", 30: "PCI"}})["target_state"]
    ap = ts["addressing_plan"]
    assert ap["status"] == "candidate" and ap["mode"] == "zone-aware"
    zones = {z["zone"]: z for z in ap["zones"]}
    assert set(zones) == {"PCI", "corp"} and ap["n_zones"] == 2
    blk = {z: ipaddress.ip_network(zones[z]["summary"]) for z in zones}
    assert not blk["PCI"].overlaps(blk["corp"])                       # zone blocks disjoint
    for s in ap["subnets"]:
        assert ipaddress.ip_network(s["subnet"]).subnet_of(blk[s["zone"]])   # subnet inside its zone block
    assert {s["vlan"] for s in ap["subnets"] if s["zone"] == "PCI"} == {10, 30}


def test_addressing_zone_gating_no_fabrication():
    """F1 HONESTY refutation: data_classification (zone NAMES) but NO vlan_zones -> the engine must NOT
    fabricate a zone assignment; it stays non-zone-aware and surfaces that an explicit map is needed."""
    snap = _snap()
    ap = compute_design_blueprint(snap, {"address_space": "10.0.0.0/16",
                                         "data_classification": ["PCI", "corp", "OT"]})["target_state"]["addressing_plan"]
    assert ap["status"] == "candidate" and ap["mode"] != "zone-aware"
    assert all("zone" not in s for s in ap["subnets"])                # no fabricated zone on any row
    assert "vlan_zones" in (ap.get("zone_caveat") or "")              # tells the user what's needed


def test_addressing_unmapped_vlans_surfaced():
    """F1 coverage-honesty: a partial vlan_zones map -> unmapped VLANs are listed and placed in a residual
    block, never silently dropped nor force-assigned to a real zone."""
    snap = _snap(l3_forwarding=[{"switch": "d", "vlan": str(v), "svi_ip": f"10.0.{v}.1"} for v in (10, 20, 30)])
    ap = compute_design_blueprint(snap, {"address_space": "10.90.0.0/16",
                                         "vlan_zones": {10: "PCI"}})["target_state"]["addressing_plan"]
    assert ap["mode"] == "zone-aware"
    assert 20 in ap["unmapped_vlans"] and 30 in ap["unmapped_vlans"] and 10 not in ap["unmapped_vlans"]
    placed = {s["vlan"] for s in ap["subnets"]}
    assert {10, 20, 30} <= placed                                     # unmapped still allocated (residual), not dropped


def test_requirements_vlan_zones_roundtrip(tmp_path):
    """F1: vlan_zones round-trips through both register loaders, normalised to {int(vid): str(zone)};
    empty/absent is dropped (stays non-zone-aware)."""
    import json
    from cisco_toolkit.design_advisor import load_requirements, requirements_from_interview
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"address_space": "10.0.0.0/16", "vlan_zones": {"10": "PCI", "20": "corp"}}), encoding="utf-8")
    assert load_requirements(str(p))["vlan_zones"] == {10: "PCI", 20: "corp"}
    assert requirements_from_interview({"vlan_zones": {"30": "OT"}})["vlan_zones"] == {30: "OT"}
    assert "vlan_zones" not in requirements_from_interview({"vlan_zones": {}})


def test_addressing_too_small_supernet_overflows_without_crash():
    """AUDIT: an undersized supernet overflows gracefully — VLANs reported in n_overflow, never dropped
    silently nor crashing; the zone-aware too-small guard returns no subnets + full overflow."""
    snap = _snap(l3_forwarding=[{"switch": "d", "vlan": str(v), "svi_ip": f"10.0.{v}.1"} for v in (10, 20, 30)])
    flat = compute_design_blueprint(snap, {"address_space": "10.0.0.0/30"})["target_state"]["addressing_plan"]
    assert flat["status"] == "candidate" and flat["n_overflow"] > 0          # didn't fit, reported
    zone = compute_design_blueprint(snap, {"address_space": "10.0.0.0/28",
                                           "vlan_zones": {10: "A", 20: "B", 30: "C"}})["target_state"]["addressing_plan"]
    assert zone["mode"] == "zone-aware" and zone["subnets"] == [] and zone["n_overflow"] == 3


def test_addressing_reconciliation_fields_present():
    """AUDIT FIX: the IP plan discloses the census-vs-sized delta (n_census_vlans / n_unsizable) so §5.3's
    count reconciles with §5.2's VLAN census instead of a silent drop."""
    from cisco_toolkit.analyze import vlan_inventory
    snap = _snap(l3_forwarding=[{"switch": "d", "vlan": str(v), "svi_ip": f"10.0.{v}.1"} for v in (10, 20, 30)])
    ap = compute_design_blueprint(snap, {"address_space": "10.0.0.0/16"})["target_state"]["addressing_plan"]
    assert ap["n_census_vlans"] == len(vlan_inventory(snap))
    assert ap["n_unsizable"] == max(0, ap["n_census_vlans"] - ap["n_allocated"])
    if ap["n_unsizable"]:
        assert "carry no auto-sized subnet" in ap["note"]                    # disclosed, never silent


def test_wave_plan_subdivides_oversized_groups_and_batches_small():
    """F2: the wave plan turns raw move-groups into realistic waves -- an oversized L2-coupled group is
    sliced into <=cap SEQUENCED sub-waves; independent small groups are BATCHED. compute_move_groups is
    NOT touched (the coupling is still reported); this is an additive planning layer. Every switch placed once."""
    big = [f"SW{i:03d}" for i in range(95)]                       # one 95-switch coupled group
    smalls = [{"switches": [f"X{j}"]} for j in range(10)]         # 10 standalone singletons
    snap = _snap(move_groups=[{"switches": big, "spanning_vlans": [[124, "X", 95]]}] + smalls)
    wp = compute_design_blueprint(snap)["target_state"]["wave_plan"]
    assert wp["largest_group"] == 95 and wp["n_subdivided_groups"] == 1
    coupled = [w for w in wp["waves"] if w["kind"] == "coupled-subwave"]
    batched = [w for w in wp["waves"] if w["kind"] == "independent-batch"]
    assert len(coupled) == 3                                       # 95 / 40 -> 3 sub-waves
    assert all(w["n_switches"] <= wp["wave_cap"] for w in wp["waves"])
    assert sum(w["n_switches"] for w in batched) == 10            # all singletons placed (batched)
    placed = [h for w in wp["waves"] for h in w["switches"]]
    assert len(placed) == 105 and len(set(placed)) == 105        # every switch placed exactly once


def test_requirements_from_interview_maps_and_normalises():
    """F3: the interview->requirements bridge normalises a TYPED answers dict into the register (coercing
    list/int/tier shapes), drops unknown/empty keys, and ignores non-dict input -- it maps typed
    requirement answers, never inventing a requirement from a qualitative go/no-go. One normalisation path:
    the produced register drives the blueprint exactly like a file/CLI register."""
    from cisco_toolkit.design_advisor import requirements_from_interview
    ans = {"availability_tier": "Gold", "critical_apps": "voice, video , ERP",
           "convergence_budget_ms": "200", "data_classification": ["PCI", "corp"],
           "growth_horizon": " 3y +50% ", "address_space": "10.0.0.0/14",
           "unknown_key": "ignored", "constraints": ""}
    reg = requirements_from_interview(ans)
    assert reg["availability_tier"] == "gold"
    assert reg["critical_apps"] == ["voice", "video", "ERP"]      # comma-split + trimmed
    assert reg["convergence_budget_ms"] == 200                    # coerced to int
    assert reg["data_classification"] == ["PCI", "corp"]
    assert reg["growth_horizon"] == "3y +50%" and reg["address_space"] == "10.0.0.0/14"
    assert "unknown_key" not in reg and "constraints" not in reg  # unknown + empty dropped
    assert requirements_from_interview("nope") == {} and requirements_from_interview(None) == {}
    bp = compute_design_blueprint(_snap(), reg)
    assert bp["requirements_model"]["provided"] is True and all("effective_priority" in d for d in bp["decisions"])


def test_questionnaire_requirement_tags_are_valid():
    """F3: the engagement interview is requirements-aware -- the requirement-bearing questions are tagged
    with a `requirement_key` that resolves to a real register key, so an interview answer can flow through
    requirements_from_interview into the blueprint. (Tags are hints; only genuinely-typed answers map.)"""
    import os, json
    from cisco_toolkit.design_advisor import REQUIREMENTS_KEYS
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    q = json.load(open(os.path.join(root, "questionnaire.json"), encoding="utf-8"))
    tagged = {it["id"]: it["requirement_key"] for it in q if it.get("requirement_key")}
    assert tagged, "interview must tag its requirement-bearing questions"
    assert all(v in REQUIREMENTS_KEYS for v in tagged.values()), f"invalid requirement_key tag(s): {tagged}"
    assert {"availability_tier", "critical_apps", "growth_horizon", "data_classification"} <= set(tagged.values())


def test_summary_n_critical_counts_recommended_only_single_source():
    """SSOT: `summary.n_critical` counts Critical decisions that are ALSO `recommended` -- the exact
    population the headline and every surface (HLD §4.2 table, deck cards, explorer/webapp stat) render.
    Refutes the dual-encoding drift the audit found: previously n_critical counted ALL Critical (incl.
    requirement-gated ones), so the deck/explorer/webapp showed 5 while the HLD headline showed 4 for the
    same design. There must be ONE canonical 'critical design-decision' number."""
    bp = compute_design_blueprint(_snap())
    dec = bp["decisions"]
    rec_crit = [d for d in dec if d["priority"] == "Critical" and d["status"] == "recommended"]
    needs_crit = [d for d in dec if d["priority"] == "Critical" and d["status"] == "needs-requirement"]
    # the fixture surfaces a Critical *needs-requirement* decision (defense-in-depth segmentation), so the
    # recommended-critical population genuinely differs from the all-status total -- this is what makes the
    # assertion a real refutation rather than a tautology.
    assert needs_crit, "fixture must surface a Critical needs-requirement decision to prove the distinction"
    assert bp["summary"]["n_critical"] == len(rec_crit)
    assert bp["summary"]["n_critical"] != len(rec_crit) + len(needs_crit)  # the OLD buggy all-status total
    # the headline embeds the SAME number -> no surface can disagree with another
    assert f"{len(rec_crit)} critical recommended" in bp["summary"]["headline"]


def test_no_decision_cites_an_unloadable_requirement_key():
    """Every `requirements_needed` key a decision cites must be a key some register loader can actually
    supply (it must live in REQUIREMENTS_KEYS). Refutes the dead requirement_key class the audit found:
    `application_matrix` was cited by qos-class-model-from-app-profile but absent from REQUIREMENTS_KEYS,
    so no file/CLI/interview path could supply it -- dead interactive surface."""
    from cisco_toolkit.design_advisor import REQUIREMENTS_KEYS
    bp = compute_design_blueprint(_snap())
    for d in bp["decisions"]:
        for k in d.get("requirements_needed", []):
            assert k in REQUIREMENTS_KEYS, \
                f"decision {d['id']} cites requirement '{k}' absent from REQUIREMENTS_KEYS (unsupply-able)"


def test_compute_design_nrfu_generates_acceptance_items_from_decisions():
    """NRFU FRONTIER: compute_design_nrfu() bridges design intent to acceptance tests — one structured
    NRFU item per recommended design decision, each traceable to the decision ID / CCDE principle /
    affected devices. Only recommended decisions generate items (needs-requirement decisions are not
    testable until the requirement is supplied). Items must carry: decision_id, title, priority, phase,
    description, pass_criteria, devices, principle_citation. A design with no recommended decisions
    yields an empty but structurally valid result (no crash). The function is deterministic."""
    from cisco_toolkit.design_advisor import compute_design_nrfu
    bp = compute_design_blueprint(_snap())
    result = compute_design_nrfu(bp)

    # structural contract
    assert isinstance(result, dict)
    for k in ("items", "n_items", "note"):
        assert k in result, f"compute_design_nrfu result missing '{k}'"
    assert result["n_items"] == len(result["items"])

    # every item has the required keys
    required_keys = {"decision_id", "title", "priority", "phase", "description",
                     "pass_criteria", "devices", "principle_citation"}
    for item in result["items"]:
        missing = required_keys - set(item)
        assert not missing, f"NRFU item {item.get('decision_id')} missing keys: {missing}"

    # only recommended decisions produce items (needs-requirement are not testable yet)
    rec_ids = {d["id"] for d in bp["decisions"] if d["status"] == "recommended"}
    nrfu_ids = {it["decision_id"] for it in result["items"]}
    assert nrfu_ids <= rec_ids, (
        f"NRFU items must trace only to recommended decisions; unexpected: {nrfu_ids - rec_ids}"
    )
    # every recommended decision must produce exactly one item
    assert nrfu_ids == rec_ids, (
        f"every recommended decision must map to an NRFU item; missing: {rec_ids - nrfu_ids}"
    )

    # devices on each item match the decision's evidence.devices
    by_id = {d["id"]: d for d in bp["decisions"]}
    for item in result["items"]:
        dec = by_id[item["decision_id"]]
        assert item["devices"] == (dec.get("evidence") or {}).get("devices", []), (
            f"NRFU item {item['decision_id']} devices must match decision evidence.devices"
        )

    # determinism
    import json
    assert json.dumps(compute_design_nrfu(bp), sort_keys=True) == json.dumps(result, sort_keys=True)

    # empty blueprint yields empty, valid result (no crash)
    empty = compute_design_nrfu(compute_design_blueprint({}))
    assert isinstance(empty["items"], list)


def test_requirements_model_surfaces_all_requirement_keys():
    """SSOT gap fix: requirements_model.fields must surface EVERY REQUIREMENTS_KEY — including
    address_space and vlan_zones, which are the two keys that unlock the net-new IP addressing plan
    (target_state.addressing_plan). Absent them, no UI or API caller knows to prompt for them, so
    the addressing plan stays permanently in the needs-requirement state with no actionable path to
    resolve it. Refutes the regression where 6 of 8 keys were exposed and the IP-plan requirements
    were invisible to every interactive surface."""
    from cisco_toolkit.design_advisor import REQUIREMENTS_KEYS
    bp = compute_design_blueprint(_snap())
    field_keys = {f["key"] for f in bp["requirements_model"]["fields"]}
    missing = set(REQUIREMENTS_KEYS) - field_keys
    assert not missing, (
        f"requirements_model.fields is missing REQUIREMENTS_KEYS: {sorted(missing)} "
        f"— these cannot be supplied by any interactive surface (webapp form / interview / CLI hint)"
    )


def test_addressing_plan_has_census_vlans_when_needs_requirement():
    """SSOT gap fix: n_census_vlans and n_unsizable must be present in the addressing_plan even
    when status='needs-requirement' (no address_space supplied) — not only in the candidate path.
    Every surface (explorer needs-requirement block, webapp IP plan section) should be able to
    display 'N census VLANs total; M have no access port/SVI and will need manual sizing' as a
    context-setting disclosure, even before the engineer provides an address space. Refutes the
    early-return bug that omitted both fields and caused the live AJ addressing_plan to show
    n_census_vlans: None and n_unsizable: None."""
    snap = _snap()
    ap = compute_design_blueprint(snap)["target_state"]["addressing_plan"]
    assert ap["status"] == "needs-requirement", "pre-condition: no address_space -> needs-requirement"
    assert "n_census_vlans" in ap, (
        "n_census_vlans must be present in the needs-requirement addressing_plan so surfaces can "
        "disclose the full VLAN census count before the IP plan is requested"
    )
    assert "n_unsizable" in ap, (
        "n_unsizable must be present in the needs-requirement addressing_plan"
    )
    assert isinstance(ap["n_census_vlans"], int) and ap["n_census_vlans"] >= 0
    assert isinstance(ap["n_unsizable"], int) and ap["n_unsizable"] >= 0
    # Refutation: with address_space supplied both fields must still be present (they were already)
    ap2 = compute_design_blueprint(snap, {"address_space": "10.0.0.0/16"})["target_state"]["addressing_plan"]
    assert ap2["status"] == "candidate"
    assert "n_census_vlans" in ap2 and "n_unsizable" in ap2


def test_eol_signal_and_bom_separate_past_ldos_from_supported_past_eos():
    """REVIEW #3: still-supported Past-EoS devices (past end-of-SALE, in support until LDoS -- the engine
    emits this band, see test_lifecycle) must NOT be counted/labelled as past-LDoS/unsupported nor placed
    in the replace-now BoM. sig['eol'] / the EoL decision / dim-4 label count Past-LDoS only; Past-EoS is
    refresh-class."""
    snap = _snap(lifecycle_risk={"per_device": [
        {"host": "a", "band": "Past-LDoS", "model": "WS-C4948E"},
        {"host": "b", "band": "Past-LDoS", "model": "WS-C4948E"},
        {"host": "e", "band": "Past-EoS", "model": "WS-C2960X-48FPD-L"},   # supported -> NOT replace, NOT eol
        {"host": "c", "band": "Near-LDoS", "model": "N5K-C56128P"},
        {"host": "d", "band": "Active", "model": "C9300"}]})
    bp = compute_design_blueprint(snap)
    eol = next(d for d in bp["decisions"] if d["id"] == "lifecycle-eol-out-of-critical-roles")
    assert eol["evidence"]["count"] == 2, eol["evidence"]["count"]              # the 2 Past-LDoS, NOT 3
    assert "2 device(s) are past last-day-of-support" in eol["evidence"]["summary"]
    bom = bp["target_state"]["replacement_bom"]
    assert bom["n_replace"] == 2 and ["WS-C4948E", 2] in bom["replace_now"]
    assert ["WS-C2960X-48FPD-L", 1] not in bom["replace_now"]                   # Past-EoS is NOT replace-now
    assert ["WS-C2960X-48FPD-L", 1] in bom["refresh_soon"]                      # ...it is refresh
    assert bom["n_refresh"] == 2                                                # Near-LDoS + Past-EoS
    dim = next(d for d in bp["target_state"]["dimensions"] if d.get("area") == "Hardware lifecycle disposition")
    assert "2 past-LDoS" in dim["current"], dim["current"]


def test_alloc_zone_aware_sizes_blocks_by_demand_not_uniformly():
    """REVIEW #5: zone blocks must be sized to EACH zone's VLAN demand, not uniformly by zone count. An
    uneven zone must not overflow when the supernet has ample room; uniform sizing overflowed zone A."""
    import ipaddress
    from cisco_toolkit.design_advisor import _alloc_zone_aware
    supernet = ipaddress.ip_network("10.0.0.0/20")                 # 16 /24s
    vids = list(range(10, 21))                                     # 11 vlans (10..20)
    counts = {v: 5 for v in vids}
    vlan_zones = {v: ("A" if v <= 16 else ("B" if v <= 18 else "C")) for v in vids}  # A:7  B:2  C:2
    plan = _alloc_zone_aware(supernet, vids, counts, vlan_zones)
    assert plan["n_overflow"] == 0, plan["n_overflow"]            # uniform-by-count sizing overflows zone A
    assert plan["n_allocated"] == 11
    nets = [ipaddress.ip_network(z["summary"]) for z in plan["zones"]]
    for i in range(len(nets)):                                     # every zone summarises to ONE disjoint prefix
        for j in range(i + 1, len(nets)):
            assert not nets[i].overlaps(nets[j]), (nets[i], nets[j])
    by_zone = {z["zone"]: ipaddress.ip_network(z["summary"]) for z in plan["zones"]}
    assert by_zone["A"].prefixlen < by_zone["B"].prefixlen        # A (7 VLANs) gets a bigger block than B (2)


def test_alloc_flat_supernet_smaller_than_24_is_honest():
    """REVIEW #10: a supernet smaller than /24 cannot give a /24 per VLAN; report honest overflow and do
    NOT emit the supernet itself as a bogus '/24' subnet."""
    import ipaddress
    from cisco_toolkit.design_advisor import _alloc_flat
    plan = _alloc_flat(ipaddress.ip_network("10.0.0.0/25"), [10, 20], {10: 5, 20: 5})
    assert plan["n_allocated"] == 0 and plan["n_overflow"] == 2
    assert all(s.get("subnet") != "10.0.0.0/25" for s in plan["subnets"])


def test_addressing_plan_ipv6_address_space_is_honest():
    """REVIEW #10: an IPv6 address_space is not handled by the IPv4 /24-per-VLAN allocator; surface that
    honestly (no fabricated subnets), not a single degraded block."""
    ap = compute_design_blueprint(_snap(), {"address_space": "2001:db8::/48"})["target_state"]["addressing_plan"]
    assert ap["status"] == "needs-requirement"
    assert "ipv6" in (ap.get("note") or "").lower()
    assert not ap.get("subnets")


def test_requirements_from_interview_preserves_zero_convergence():
    """REVIEW #11: convergence_budget_ms of 0 must coerce to int 0, not be clobbered to the raw value by
    `_as_int(v) or v`; an unparseable value still falls back to the raw string."""
    from cisco_toolkit.design_advisor import requirements_from_interview
    assert requirements_from_interview({"convergence_budget_ms": "0"}).get("convergence_budget_ms") == 0
    assert requirements_from_interview({"convergence_budget_ms": 250}).get("convergence_budget_ms") == 250
    assert requirements_from_interview({"convergence_budget_ms": "fast"}).get("convergence_budget_ms") == "fast"


def test_signals_computed_once_and_no_dead_fields(monkeypatch):
    """REVIEW #15: _signals must be computed ONCE per blueprint (compute_target_state must not recompute it
    when the caller already built it), and dead signal fields (bridge_links/gw_count -- no readers) are gone."""
    import cisco_toolkit.design_advisor as da
    sig = da._signals(_snap())
    assert "bridge_links" not in sig and "gw_count" not in sig
    calls = {"n": 0}
    real = da._signals

    def _counting(snap, *a, **k):
        calls["n"] += 1
        return real(snap, *a, **k)

    monkeypatch.setattr(da, "_signals", _counting)
    da.compute_design_blueprint(_snap())
    assert calls["n"] == 1, calls["n"]                            # was 2 (blueprint + target_state)


# ===================================================================== DC-fabric corpus enrichment
# The design brain learns the modern DC target vocabulary (EVPN/VXLAN leaf-spine, Multi-Site, DCI,
# active-active, cloud/SDDC, L4-L7 services) mined from the AJ reference corpus + the real AJMN SDD.
# Coverage-honest: the L1-L4 assessment collects no fabric/cloud state, so these are DOCTRINE the HLD
# §4.4 catalogue + design-chat cite -- NOT auto-emitted decisions -- EXCEPT the Multi-Site-vs-stretched
# choice, which (like the other DC-fabric choices) is a requirement-gated open decision.
_DC_CORPUS_IDS = {
    "dc-fabric": ["dc-fabric-vxlan-evpn-control-plane", "dc-fabric-underlay-overlay-separation",
                  "dc-fabric-distributed-anycast-gateway-irb", "dc-fabric-bum-replication-ingress-default",
                  "dc-fabric-clos-sizing-oversubscription-ecmp", "dc-fabric-ecmp-equal-capacity-no-core-summarization",
                  "dc-fabric-fabric-drops-bpdu-single-l2-handoff", "dc-fabric-multicast-underlay-now-trm-later"],
    "dc-multisite": ["dc-multisite-interconnect-fabrics-as-isolated-sites", "dc-multisite-route-server-and-anycast-bgw",
                     "dc-multisite-prefer-l3-dci-bound-any-stretch", "dc-multisite-mobility-trombone-and-split-brain",
                     "dc-multisite-dr-and-active-active-from-rto-rpo"],
    "dc-services": ["dc-services-load-balancer-vip-pool-and-insertion-mode",
                    "dc-services-shared-border-firewall-and-service-insertion",
                    "dc-services-tenant-isolation-vrf-acl-and-vrflite-ceiling",
                    "dc-services-anycast-gateway-dhcp-relay-giaddr"],
    "cloud": ["cloud-standardized-pod-as-availability-zone", "cloud-decouple-overlay-from-stable-ip-underlay",
              "cloud-east-west-flattens-tiering-vswitch-and-server-attach"],
}
# enrichments placed in EXISTING domains (not new ones)
_DC_CORPUS_EXTRA = ["dc-switching-unified-fabric-io-consolidation",
                    "dc-switching-capacity-from-measured-traffic-not-average",
                    "management-oob-must-not-transit-the-fabric",
                    "wan-vpn-make-vs-buy-and-test-before-buy-sp-transparency",
                    "wan-vpn-bgp-everywhere-and-mtu-headroom-on-coexistence"]
# the ONE corpus principle promoted to a requirement-gated decision (Multi-Site vs stretched fabric)
_DC_CORPUS_ACTIONABLE = "dc-multisite-interconnect-fabrics-as-isolated-sites"


def test_dc_corpus_doctrine_present_cited_and_honest():
    """Every mined DC-fabric/multi-site/services/cloud principle exists, lives in its intended domain,
    carries a citation + recommended action, and declares engine_actionability HONESTLY: all are doctrine
    (engine_actionable False) EXCEPT the Multi-Site-vs-stretched choice (a requirement-gated decision)."""
    all_new = [pid for ids in _DC_CORPUS_IDS.values() for pid in ids] + _DC_CORPUS_EXTRA
    assert len(all_new) == 25 and len(set(all_new)) == 25, "25 distinct new principles"
    for pid in all_new:
        p = design_kb.by_id(pid)
        assert p, f"missing corpus principle {pid}"
        assert p.get("citation"), f"{pid} must cite its source"
        assert p.get("recommended_action"), f"{pid} must carry a recommended action"
        assert p.get("design_intent"), f"{pid} must carry the design intent (the WHY)"
        should_act = pid == _DC_CORPUS_ACTIONABLE
        assert bool(p.get("engine_actionable")) is should_act, \
            f"{pid} actionability must be {should_act} (doctrine unless it is the requirement-gated Multi-Site choice)"
    # the 4 NEW domains exist with the expected membership (by_domain surfaces them automatically)
    for dom, ids in _DC_CORPUS_IDS.items():
        got = {p["id"] for p in design_kb.by_domain(dom)}
        assert set(ids) <= got, f"domain {dom} must contain {set(ids) - got}"
        assert len(got) == len(ids), f"domain {dom}: expected {len(ids)} principles, got {len(got)}"
    # citation ACCURACY (the adversarial standards pass): EVPN ctrl-plane is MPLS-EVPN(7432) over VXLAN/NVO
    # (8365) with IP-prefix RT-5 (9136); anycast GW is EVPN-IRB (9135); TRM routed-multicast is ngMVPN (6513)
    cp = design_kb.by_id("dc-fabric-vxlan-evpn-control-plane")["citation"]
    assert "7432" in cp and "8365" in cp and "9136" in cp, "EVPN control-plane must cite 7432 + 8365 + 9136"
    assert "9135" in design_kb.by_id("dc-fabric-distributed-anycast-gateway-irb")["citation"]
    assert "6513" in design_kb.by_id("dc-fabric-multicast-underlay-now-trm-later")["citation"]


def test_dc_multisite_choice_is_requirement_gated():
    """Multi-Site-vs-stretched-fabric is a scale/containment CHOICE the L1-L4 evidence cannot decide, so it
    surfaces as an open design question and flips to recommended once a growth horizon is supplied -- exactly
    like the other DC-fabric choices. It is engine_actionable (emitted via _NEEDS), keeping the lock green."""
    base = compute_design_blueprint(_snap())
    open_ids = {d["id"] for d in base["decisions"] if d["status"] == "needs-requirement"}
    assert _DC_CORPUS_ACTIONABLE in open_ids, "Multi-Site choice must be an open question without growth"
    bp = compute_design_blueprint(_snap(), requirements={"growth_horizon": "3y, +2 sites, +60% east-west"})
    by = {d["id"]: d for d in bp["decisions"]}
    assert by[_DC_CORPUS_ACTIONABLE]["status"] == "recommended", "must flip to recommended once growth is given"
    assert _DC_CORPUS_ACTIONABLE in {p["id"] for p in design_kb.engine_actionable()}


def test_aj_engagement_profile_rightsizes_to_the_real_target():
    """The SDD-derived AJMN engagement register (requirements.aj.json, grounded in the human-authored
    Solution Design) right-sizes the blueprint so it concretely recommends the real target: the DC-fabric +
    Multi-Site choices flip to recommended (growth supplied), defense-in-depth flips (data_classification
    supplied), and effective_priority is computed -- while the un-supplied keys stay honest open questions."""
    import os
    from cisco_toolkit.design_advisor import load_requirements
    path = os.path.join(os.path.dirname(__file__), "..", "requirements.aj.json")
    reg = load_requirements(path)
    assert reg.get("growth_horizon") and reg.get("data_classification"), "AJ register must carry growth + zones"
    assert "convergence_budget_ms" not in reg and "address_space" not in reg, \
        "AJ register must NOT fabricate a convergence budget or supernet the SDD does not state"
    bp = compute_design_blueprint(_snap(), requirements=reg)
    by = {d["id"]: d for d in bp["decisions"]}
    for pid in ("dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed",
                _DC_CORPUS_ACTIONABLE, "security-defense-in-depth-segmentation"):
        assert by[pid]["status"] == "recommended", f"{pid} must flip to recommended under the AJ register"
    assert all("effective_priority" in d for d in bp["decisions"])
    assert bp["requirements_model"]["provided"] is True
