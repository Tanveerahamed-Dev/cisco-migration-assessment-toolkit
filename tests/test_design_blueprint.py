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
from cisco_toolkit.design_advisor import compute_design_blueprint, compute_design_nrfu

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


def test_vpc_peer_fabric_health_detector_fires_and_refutes():
    """vPC/MLAG peer-fabric integrity (marquee mega-wave detector): a 'down*' member leg, a per-vPC
    consistency mismatch, or a domain-level peer/keepalive/peer-link fault means the dual-homing the
    design implies is NOT actually in service. Fires on unhealthy vpc evidence; remove the fault and
    the decision disappears (refutation); absent vpc evidence stays silent (coverage-honest)."""
    unhealthy = {"p1": {"domain_id": 1, "peer_status": "peer adjacency formed ok",
                        "keepalive_status": "peer is alive", "consistency": "success",
                        "peer_link": {"status": "up"},
                        "vpcs": [{"id": "10", "status": "down*", "consistency": "success"},
                                 {"id": "11", "status": "up", "consistency": "failed"}]}}
    by = {d["id"]: d for d in compute_design_blueprint(_snap(vpc=unhealthy))["decisions"]}
    d = by.get("dc-vpc-mlag-peer-fabric-integrity")
    assert d is not None and d["status"] == "recommended" and d["priority"] == "High"
    assert "down*" in d["evidence"]["summary"]                       # the real member-leg finding
    assert "p1" in d["evidence"]["devices"]
    # refutation: an all-healthy fabric emits nothing
    healthy = {"p1": {"peer_status": "peer adjacency formed ok", "keepalive_status": "peer is alive",
                      "consistency": "success", "peer_link": {"status": "up"},
                      "vpcs": [{"id": "10", "status": "up", "consistency": "success"}]}}
    assert "dc-vpc-mlag-peer-fabric-integrity" not in {
        d["id"] for d in compute_design_blueprint(_snap(vpc=healthy))["decisions"]}
    # coverage-honest: no vpc evidence at all -> silent
    assert "dc-vpc-mlag-peer-fabric-integrity" not in {
        d["id"] for d in compute_design_blueprint(_snap())["decisions"]}


def test_vpc_decision_produces_a_proper_precutover_nrfu_item():
    """The vPC peer-fabric decision must carry a REAL (non-fallback) NRFU acceptance item in the
    pre-cutover phase -- the fabric is reconciled and re-verified before the target is baselined on
    it, mirroring the fhrp-not-observed / lifecycle pre-cutover gates."""
    unhealthy = {"p1": {"peer_status": "peer adjacency formed ok", "keepalive_status": "peer is alive",
                        "consistency": "success", "peer_link": {"status": "up"},
                        "vpcs": [{"id": "10", "status": "down*", "consistency": "success"}]}}
    nrfu = compute_design_nrfu(compute_design_blueprint(_snap(vpc=unhealthy)))
    item = next((i for i in nrfu["items"] if i["decision_id"] == "dc-vpc-mlag-peer-fabric-integrity"), None)
    assert item is not None
    assert item["phase"] == "pre-cutover"
    assert "vPC/MLAG domain is healthy" in item["description"]          # real desc, not the driver fallback
    assert "down*" in item["pass_criteria"]                            # real pass criteria


def test_design_nrfu_items_carry_setup_preconditions():
    """N31: every design-NRFU acceptance item carries a `setup` (preconditions) field — phase-driven by
    default so a functional test reads as 'in service' and a pre-cutover gate as a readiness check."""
    nrfu = compute_design_nrfu(compute_design_blueprint(_maximal_snap()))
    assert nrfu["items"]
    for it in nrfu["items"]:
        assert it.get("setup"), it["decision_id"]                       # every item carries preconditions
    assert any("carrying production traffic" in it["setup"] for it in nrfu["items"])   # functional-phase default


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
                        "fhrp": "none", "risk": "no-FHRP"} for v in range(10, 32)]
        + [{"switch": "dist1", "vlan": 4094, "svi_ip": "5.5.5.1/30", "primary_subnet": "5.5.5.0/30"},
           # VLAN 208 with ONE collected subnet -> _d_oversized_l2_subnet (single broadcast domain >254 endpoints)
           {"switch": "dist1", "vlan": "208", "svi_ip": "10.0.208.1", "primary_subnet": "10.0.208.0/24"}],
        interfaces={**{f"acc{v}": {f"Gi1/0/{v}": {"switchport_mode": "Access", "vlan": str(v)}}
                       for v in range(10, 32)},
                    "trunk0": {"Eth1/1": {"switchport_mode": "trunk", "trunk_native_vlan": "1"}},
                    # static (mode on) multi-member EtherChannel -> _d_static_etherchannel
                    "ec0": {"Gi1/0/1": {"port_channel": "Po1", "port_channel_protocol": "ON"},
                            "Gi1/0/2": {"port_channel": "Po1", "port_channel_protocol": "ON"}},
                    # endpoint-bearing access edge with no BPDU-Guard -> _d_stp_det BPDU arm
                    "edge0": {"Gi1/0/3": {"switchport_mode": "Access", "vlan": "10",
                                          "end_host_mac": "00:11:22:33:44:55"}}},
        segmentation={"vrfs": [{"vrf": "(global)", "gateway_count": 22}],
                      "summary": {"n_oncrit_exposed": 1, "gateway_acl_coverage": 0.0, "n_gateways": 22},
                      "domains": [{"domain": "Media Fabric (SMPTE ST 2110)", "tier": "On-air critical",
                                   "isolated": False, "gateways": 22}]},
        # v2 evidence-grounded detector triggers (addressing / physical / capacity / multi-homing)
        addressing_conflicts={"dup_ip": [{"ip": "1.1.1.1", "where": [["d0", "mgmt0", None]]}], "dup_subnet": []},
        physical_health=[{"switch": "d0", "port": "Gi1/0/1", "crc_errors": 3, "input_errors": 0,
                          "duplex": "half", "status": "connected"}],
        capacity=[{"hostname": "d0", "port_util": 90.0, "free_ports": 4, "poe_util": 0.0}],
        endpoint_dependencies={"dual_homed": [{"endpoint": "e1", "switches": ["d0", "d1"]}],
                               "clusters": [], "shared_ip": []},
        operational_drift=[{"severity": "High", "category": "False-health", "devices": ["d0"],
                            "title": "Temporary L2 bridge on d0"}],
        protocol_intelligence=[{"switch": "d0", "protocol": "EtherChannel", "state": "D",
                                "severity": "High", "meaning": "Member port is down."}],
        # mega-wave 2026-06 detector triggers (collected-but-unused evidence -> firing decisions)
        subnet_intelligence={"per_device": [
            {"served_subnets": [{"vlan": "10", "subnet": "10.0.10.0/24", "gateway": "g1"}]},
            {"served_subnets": [{"vlan": "10", "subnet": "10.9.10.0/24", "gateway": "g2"}]}]},
        stp_roots={"d0": {"10": {"is_root": True, "root_priority": 32778}}},   # 32768 + vlan 10 -> accidental
        devices={"d0": {"hostname": "d0", "num_power_supplies": 2, "ps_status": "OK / FAIL"},
                 "d1": {"hostname": "d1"}, "d2": {"hostname": "d2"}, "d3": {"hostname": "d3"}},
        endpoint_identity=[{"vlan": "10", "host": "d0"}, {"vlan": "10", "host": "d1"}]   # straddle -> gateway-move-last
        + [{"vlan": "208", "host": f"sw{i % 5}"} for i in range(255)],                   # >254 -> oversized /24
        # vPC/MLAG peer fabric with a down* member leg + a consistency mismatch -> _d_vpc_health
        vpc={"p0": {"domain_id": 1, "role": "primary", "peer_status": "peer adjacency formed ok",
                    "keepalive_status": "peer is alive", "consistency": "success",
                    "peer_link": {"status": "up"},
                    "vpcs": [{"id": "10", "status": "down*", "consistency": "success"},
                             {"id": "11", "status": "up", "consistency": "failed"}]}},
        # active L2 instability: a syslog mac-flap detection -> _d_active_l2_instability
        syslog_intelligence={"detections": [{"host": "d0", "kind": "mac-flap", "severity": "High",
                                             "count": 2, "label": "MAC address flapping"}]},
        # static default route (no dynamic reconvergence) -> _d_static_default_dependency
        routes={"d0": [{"prefix": "0.0.0.0/0", "source": "s*", "next_hop": "10.0.0.1"}]},
        # architecture-coverage slices (build-wave) — each engine_actionable principle must emit here:
        # PIM running but no RP learned -> _d_pim_rp_health
        pim={"d0": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [], "groups": [], "ssm_only": False},
                    "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]}},
        # dual-stack access switch (acc10 owns an Access port above) with NO RA-Guard -> _d_ipv6_fhs
        ipv6_fhs={"acc10": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_policies": [],
                            "dhcp_guard_policies": [], "ra_guard_ifaces": [], "dhcp_guard_ifaces": [],
                            "ra_guard_present": False, "dhcp_guard_present": False}},
        # an infra (router) CDP neighbour not in the inventory -> _d_shadow_infra
        shadow_infra={"d0": [{"device_id": "wan-edge-rtr1.corp", "platform": "cisco ASR1001-X",
                              "capabilities": "Router", "proto": "cdp", "local_intf": "Gi0/0/0",
                              "mgmt_ip": "10.0.0.254", "remote_port": "Gi0/0/1"}]},
    )


def _arch_fire_snap():
    """A snapshot seeded to trigger EVERY universal-architecture detector at once (NX-OS VXLAN-EVPN
    overlay, CoPP, MPLS LDP/L3VPN/L2VPN, LISP, CTS, DMVPN, BFD, IPv6 DAD/routing, IPsec, APIC/ACI,
    Catalyst SD-WAN, firewall HA + capacity, Cisco ISE, Cisco FMC, storm-control, QoS-runtime, FHRP detail/
    state). These detectors read architecture axes the [HISTORY-REDACTED] estate doesn't run (so they are coverage-honest-
    SILENT on [HISTORY-REDACTED]); this fixture proves each emits its decision when present, so the emit-invariant covers all 36.
    Verified: fires all 36 KB-backed universal-arch detectors."""
    return {
        "overlay": {"leaf1": {"nve_peers": [{"interface": "nve1", "peer_ip": "10.0.0.2", "state": "Down", "learn_type": "CP"}],
                              "nve_vni": [{"vni": "10010", "state": "Down"}],
                              "evpn_neighbors": [{"neighbor": "10.0.0.3", "state": "Idle"}]}},
        "copp": {"sw1": [{"class": "copp-system-critical", "drops": 50000, "exceeded": 50000, "violated": 0}]},
        # MULTI-VENDOR (Arista EOS MLAG): a configured-but-config-inconsistent domain -> _d_arista_mlag_degraded
        "arista": {"spine1": {"mlag": {"state": "active", "neg_status": "connected", "config_sanity": "inconsistent",
                                       "peer_link_status": "up", "local_intf_status": "up",
                                       "ports_inactive": 0, "ports_active_partial": 0}}},
        "mpls": {"pe1": {"ldp_neighbors": [{"neighbor": "1.1.1.1", "state": "Down"}],
                         "vpnv4_neighbors": [{"neighbor": "2.2.2.2", "state": "Idle"}],
                         "l2vpn_vcs": [{"vc_id": "100", "status": "DOWN"}]}},
        "lisp": {"x1": {"sessions": [{"total": 2, "established": 0}]}},
        "cts": {"sw1": {"environment_data": {"state": "incomplete"}}},
        "dmvpn": {"hub1": {"peers": [{"peer": "10.1.1.1", "state": "NHRP", "tunnel": "Tu0"}]}},
        "bfd": {"r1": {"sessions": [{"neighbor": "10.0.0.1", "state": "Down"}]}},
        "ipv6_nd": {"sw1": {"interfaces": [{"interface": "Gi0/1", "global": [{"addr": "2001:db8::1", "dad_state": "DUPLICATE"}], "link_local_dup": False}]}},
        "ipv6_routing": {"sw1": {"ospfv3_neighbors": [{"neighbor": "1.1.1.1", "state": "DOWN"}], "bgp_ipv6_neighbors": []}},
        "crypto": {"r1": {"sessions": [{"interface": "Tu1", "peer": "1.1.1.1", "status": "DOWN"}]}},
        "aci": {"apic1": {"faults": [{"severity": "critical", "lc": "raised", "ack": "no", "code": "F1234"}],
                          "health": {"cur": 50}, "nodes": [{"id": "101", "name": "leaf101", "fabric_st": "inactive"}],
                          "vrfs": [{"tenant": "t1", "name": "v1", "pc_enf_pref": "unenforced"}]}},
        "sdwan": {"vm1": {"control_connections": [{"system_ip": "1.1.1.1", "peer_type": "vsmart", "state": "down"}],
                          "devices": [{"system_ip": "2.2.2.2", "reachability": "unreachable"}],
                          "omp_counters": [{"system_ip": "1.1.1.1", "omp_down": 1}]}},
        "firewall": {"fw1": {"failover": {"enabled": True, "units": [
            {"host": "this", "role": "Primary", "state": "Active"},
            {"host": "other", "role": "Secondary", "state": "Failed"}]},
            "resource_usage": [{"resource": "Conns", "current": 250000, "peak": 270000, "limit": 280000, "denied": 120, "context": "System"}]}},
        "ise": {"ise-pan1": {"nodes": [
            {"hostname": "ise-pan1", "roles": ["PrimaryAdmin", "PrimaryMonitoring"], "services": ["Session"], "node_status": "Connected"},
            {"hostname": "ise-psn-dead", "roles": [], "services": [], "node_status": "Disconnected"}]}},
        "fmc": {"fmc1": {
            "devices": [{"name": "FTD-DEAD", "is_connected": False, "health_status": "red", "sw_version": "7.2.5"}],
            "ha_pairs": [{"name": "HA-EDGE", "primary_status": "Active", "secondary_status": "Failed"}],
            "deployable": [{"name": "FTD-DRIFT", "can_be_deployed": True, "up_to_date": False}],
            "ha_status": {"ha_role": "Active", "ha_status": "Degraded", "sync_status": "Synchronization incomplete", "peer_reachability": "reachable"},
            "server_version": {"server_version": "7.0.0 (build 94)"}}},
        "storm_control": {"a1": [{"interface": "Gi0/2", "traffic": "broadcast", "action": "None", "configured": True},
                                 {"interface": "Gi0/5", "traffic": "broadcast", "filter_state": "Blocking", "current": "2m", "configured": True}]},
        "qos_runtime": {"wan1": [{"interface": "Gi0/0/0", "policy": "WAN", "class": "VOICE", "priority": True,
                                  "drop_pkts": 1840521, "output_pkts": 24817400, "police_drop_pkts": 0}]},
        "fhrp_detail": {"core1": [{"ifname": "Vlan10", "group": "10", "state": "Active", "preempt": True, "track": []}]},
        "fhrp": [{"vid": 10, "issues": ["split-brain"], "members": [{"host": "a"}, {"host": "b"}]}],
    }


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
    # the universal-architecture detectors (ACI/VXLAN-EVPN/MPLS/SD-WAN/LISP/...) fire ONLY when that
    # architecture's collected state is present, so they are coverage-honest-silent on an [HISTORY-REDACTED]-style switch
    # fleet. Union the maximal switch snapshot with _arch_fire_snap (which seeds every architecture axis)
    # so the invariant exercises the FULL engine_actionable set, including those 36 principles.
    emitted = {d["id"] for d in compute_design_blueprint(_maximal_snap())["decisions"]}  # no requirements -> needs-requirement too
    emitted |= {d["id"] for d in compute_design_blueprint(_arch_fire_snap())["decisions"]}
    ea = {p["id"] for p in design_kb.engine_actionable()}
    missing = ea - emitted
    assert not missing, f"engine_actionable principles never emitted by the advisor: {sorted(missing)}"
    # and conversely every emitted, evidence-grounded decision must be a known KB principle
    assert emitted <= _KB_IDS


def test_wave2_gap_addendum_is_honest_reference_doctrine():
    """The 2026-06-21 mega-wave gap addendum enriches KB-thin/absent design domains (optical /
    storage / DDI / observability are brand-new; EVPN / SP-L2VPN / SP-MVPN / cloud / ACI-multisite &
    -services enriched). It is REFERENCE doctrine: every principle is engine_actionable=False (the
    L1-L4 assessment collects no live state for these), carries a real citation + design_intent, has
    a unique registered id, and NONE is ever emitted as a firing decision (no overstated coverage).
    The four brand-new domains are present."""
    add = design_kb._WAVE2_GAP_ADDENDUM
    assert len(add) >= 50
    kb_ids = {p["id"] for p in design_kb.DOCTRINE}
    for p in add:
        assert p.get("engine_actionable") is False, p["id"]
        assert (p.get("citation") or "").strip(), p["id"]
        assert (p.get("design_intent") or "").strip(), p["id"]
        assert p["id"] in kb_ids, p["id"]
    assert {"optical-transport", "storage-fabric", "ddi-ipam", "observability"} <= {p["domain"] for p in add}
    # coverage-honesty: none of this reference doctrine is ever emitted as a firing decision
    emitted = {d["id"] for d in compute_design_blueprint(_maximal_snap())["decisions"]}
    assert not (emitted & {p["id"] for p in add}), "reference doctrine must not be emitted as a decision"


# ----------------------------------------------------------- A: requirements register input (the WHY)
def test_load_requirements_parses_register_and_is_defensive(tmp_path):
    """`load_requirements` reads a design requirements register (JSON) into the recognised keys, accepts
    a {"requirements": {...}} wrapper, drops unknown/empty keys, and degrades to {} on missing/malformed
    input (non-fatal -- the design then surfaces the open questions rather than assuming)."""
    import json
    from cisco_toolkit.design_advisor import load_requirements, REQUIREMENTS_KEYS
    assert set(REQUIREMENTS_KEYS) == {"availability_tier", "critical_apps", "convergence_budget_ms",
                                      "growth_horizon", "constraints", "data_classification", "address_space",
                                      "vlan_zones", "fabric_operating_model"}
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


def test_media_timing_fabric_dimension_is_evidence_gated():
    """Broadcast media fabric (the [HISTORY-REDACTED] estate): PTP-capable switches with no operational/redundant grandmaster
    plus AV multicast groups surface a 'Media / timing fabric' target-state dimension grounded in SMPTE ST
    2059-2. Refutation: with no PTP/AV evidence the dimension must NOT appear (no fabricated media plane for a
    non-broadcast estate). Its driver principle is real KB doctrine and honestly engine_actionable=False."""
    from cisco_toolkit.design_advisor import compute_target_state
    snap = _snap(multicast_intelligence={
        "ptp": {"n_clocks": 13, "n_operational": 0, "grandmasters": [], "dormant": ["s1", "s2"]},
        "summary": {"n_av_groups": 45, "n_groups": 73},
        "querier": {"gap_vlans": []}, "risks": []})
    dim = next((d for d in compute_target_state(snap)["dimensions"]
                if d["area"] == "Media / timing fabric"), None)
    assert dim, "13 PTP clocks + 45 AV groups must surface the media/timing dimension"
    assert "2059" in dim["target"] and "grandmaster" in dim["target"].lower()
    assert "13" in dim["current"] and "0 grandmaster" in dim["current"]
    kb_ids = {p["id"] for p in design_kb.DOCTRINE}
    assert dim["drivers"] and all(drv in kb_ids for drv in dim["drivers"])
    media_p = design_kb.by_id("multicast-media-fabric-ptp-timing")
    assert media_p and media_p["engine_actionable"] is False     # surfaced via the dimension, not a firing detector
    # refutation: base snapshot (no ptp clocks, no AV groups) -> no media dimension
    assert not any(d["area"] == "Media / timing fabric"
                   for d in compute_target_state(_snap())["dimensions"])


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


def test_segmentation_plan_seeds_candidate_from_observed_tiers():
    """#10: when the estate ALREADY classifies its broadcast domains into >1 sensitivity TIER (evidence the
    engine derived, NOT a supplied requirement), the segmentation plan emits a CANDIDATE macro-segmentation
    (one zone per observed tier) instead of punting entirely to data_classification. Coverage-honest: the
    tiers are a SEED to confirm; supplying data_classification still firms the per-VLAN map and takes precedence."""
    from cisco_toolkit.design_advisor import compute_target_state
    snap = _snap(segmentation={"vrfs": [{"vrf": "(global)"}], "summary": {"n_gateways": 10},
                              "domains": [{"domain": "Media", "tier": "On-air critical", "gateways": 3},
                                          {"domain": "Corp", "tier": "Production", "gateways": 4},
                                          {"domain": "Mgmt", "tier": "Support", "gateways": 3}]})
    sp = compute_target_state(snap)["segmentation_plan"]
    assert sp["status"] == "candidate" and sp.get("mode") == "tier-seeded"
    assert sp.get("n_macro_zones") == 3
    assert set(sp.get("target_zones", [])) == {"On-air critical", "Production", "Support"}
    assert "tier" in sp["target"].lower() and "data_classification" in sp["target"]   # seed invites firm-up
    # refutation 1: a single tier is not a macro-segmentation -> stays needs-requirement (no fabricated zones)
    one = _snap(segmentation={"vrfs": [{"vrf": "(global)"}],
                              "domains": [{"domain": "A", "tier": "On-air critical", "gateways": 3}]})
    assert compute_target_state(one)["segmentation_plan"]["status"] == "needs-requirement"
    # refutation 2: an explicit data_classification still takes precedence (firm declared zones, not the tier seed)
    dc = compute_target_state(snap, {"data_classification": ["PCI", "corp"]})["segmentation_plan"]
    assert dc["status"] == "candidate" and set(dc["target_zones"]) == {"PCI", "corp"} and dc.get("mode") != "tier-seeded"


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
    early-return bug that omitted both fields and caused the live [HISTORY-REDACTED] addressing_plan to show
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


def test_phys_dirty_counts_tx_side_faults_on_up_ports_only():
    """DET-intf-errors-002: a port clean on CRC/input-errors but carrying late_collisions (duplex/cable) or
    output_errors (marginal optic) on an UP port counts as dirty-L1 and surfaces in the remediation
    decision; stale cumulative counters on a DOWN ('notconnect') port must NOT flag."""
    import cisco_toolkit.design_advisor as da
    snap = {"physical_health": [
        {"switch": "s1", "port": "Te1/1", "status": "connected", "crc_errors": 0, "input_errors": 0,
         "late_collisions": 3, "output_errors": 0, "duplex": "full"},
        {"switch": "s2", "port": "Te1/2", "status": "connected", "crc_errors": 0, "input_errors": 0,
         "late_collisions": 0, "output_errors": 9, "duplex": "full"},
        {"switch": "s3", "port": "Te1/3", "status": "notconnect", "crc_errors": 0, "input_errors": 0,
         "late_collisions": 50, "output_errors": 50, "duplex": "full"},      # DOWN -> stale counters, NOT dirty
        {"switch": "s4", "port": "Te1/4", "status": "connected", "crc_errors": 0, "input_errors": 0,
         "late_collisions": 0, "output_errors": 0, "duplex": "full"},        # clean
    ]}
    sig = da._signals(snap)
    assert sig["phy_latecoll"] == 1 and sig["phy_outerr"] == 1
    assert sig["phy_dirty"] == 2                                             # s1 + s2 only
    assert set(sig["phy_dirty_hosts"]) == {"s1", "s2"}
    dec = da._d_phys_remediation(snap, sig)
    assert dec is not None and "late-collision" in str(dec) and "output-error" in str(dec)


def test_d_nve_vni_health_flags_down_vni():
    """Universality (VXLAN VNI): a VNI not Up strands its segment -> _d_nve_vni_health fires; silent when all Up."""
    import cisco_toolkit.design_advisor as da
    snap = {"overlay": {"leaf1": {"nve_vni": [
        {"vni": "10010", "state": "Up", "mode": "CP", "type": "L2"},
        {"vni": "50000", "state": "Down", "mode": "CP", "type": "L3"},
    ]}}}
    sig = da._signals(snap)
    assert sig["nve_vni_down"] == ["leaf1 VNI 50000"]
    dec = da._d_nve_vni_health(snap, sig)
    assert dec is not None and "not Up" in str(dec)
    ok = {"overlay": {"leaf1": {"nve_vni": [{"vni": "10010", "state": "Up", "mode": "CP", "type": "L2"}]}}}
    assert da._d_nve_vni_health(ok, da._signals(ok)) is None


def test_d_evpn_rr_health_flags_down_rr():
    """Universality (VXLAN-EVPN control plane): a BGP-EVPN neighbor not Established -> _d_evpn_rr_health fires
    (overlay control plane dark). Silent when all Established or no EVPN."""
    import cisco_toolkit.design_advisor as da
    snap = {"overlay": {"leaf1": {"evpn_neighbors": [
        {"neighbor": "10.0.0.254", "as": "65001", "state": "Established", "prefixes": 240},
        {"neighbor": "10.0.0.253", "as": "65001", "state": "Idle", "prefixes": 0},
    ]}}}
    sig = da._signals(snap)
    assert sig["evpn_down"] == ["leaf1 10.0.0.253"]
    dec = da._d_evpn_rr_health(snap, sig)
    assert dec is not None and "not Established" in str(dec)
    ok = {"overlay": {"leaf1": {"evpn_neighbors": [{"neighbor": "10.0.0.254", "as": "65001", "state": "Established", "prefixes": 240}]}}}
    assert da._d_evpn_rr_health(ok, da._signals(ok)) is None


def test_d_copp_drops_fires_on_dropping_class_only():
    """Universality (control-plane policing): a CoPP class actively dropping (drops > 0) fires _d_copp_drops;
    an armed-but-clean policer (every class drops == 0) and an ABSENT copp axis are both silent (coverage-honest
    -- 'CoPP configured, nothing dropping' is the NORMAL state, not a finding)."""
    import cisco_toolkit.design_advisor as da
    dropping = {"copp": {"core2": [
        {"class": "copp-system-p-class-critical", "conformed": 177446058, "exceeded": 0, "violated": 4521, "dropped": 0, "drops": 4521},
        {"class": "copp-system-p-class-normal", "conformed": 88231005, "exceeded": 0, "violated": 0, "dropped": 0, "drops": 0},
    ]}}
    sig = da._signals(dropping)
    assert sig["copp_drop_classes"] == 1 and sig["copp_drop_pkts"] == 4521 and sig["copp_drop_hosts"] == ["core2"]
    dec = da._d_copp_drops(dropping, sig)
    assert dec is not None and "CoPP" in str(dec) and "dropping" in str(dec)
    assert "core2" in dec["evidence"]["devices"] and dec["priority"] == "High"
    clean = {"copp": {"core2": [{"class": "c", "conformed": 5, "exceeded": 0, "violated": 0, "dropped": 0, "drops": 0}]}}
    assert da._d_copp_drops(clean, da._signals(clean)) is None
    assert da._d_copp_drops({}, da._signals({})) is None


def test_d_mpls_ldp_health_fires_on_non_oper_session_only():
    """Universality (SP/MPLS LDP underlay): a device with an LDP neighbor NOT in state 'Oper' fires
    _d_mpls_ldp_health (no transport labels exchanged -> LSPs blackhole). Refutation: all sessions
    Oper (normal healthy state) and absent mpls axis both stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"mpls": {"pe1": {
        "ldp_neighbors": [
            {"peer": "10.0.255.2", "label_space": "0", "state": "Oper"},
            {"peer": "10.0.255.9", "label_space": "0", "state": "Nonexistent"},
        ]}}}
    sig = da._signals(fire)
    assert "10.0.255.9" in " ".join(sig.get("mpls_ldp_down", []))
    dec = da._d_mpls_ldp_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "LDP" in str(dec)
    assert "pe1" in dec["evidence"]["devices"]
    clean = {"mpls": {"pe1": {"ldp_neighbors": [{"peer": "10.0.255.2", "label_space": "0", "state": "Oper"}]}}}
    assert da._d_mpls_ldp_health(clean, da._signals(clean)) is None
    assert da._d_mpls_ldp_health({}, da._signals({})) is None


def test_d_mpls_l3vpn_health_fires_on_non_established_vpnv4_only():
    """Universality (SP/MPLS L3VPN): a device with a VPNv4 MP-BGP neighbor not Established fires
    _d_mpls_l3vpn_health (no VPN routes exchanged -> remote VRF sites blackhole). Refutation: all
    VPNv4 neighbors Established and absent mpls axis both stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"mpls": {"pe1": {
        "vpnv4_neighbors": [
            {"neighbor": "10.0.255.2", "as": "65000", "state": "Established", "prefixes": 6},
            {"neighbor": "10.0.255.9", "as": "65000", "state": "Idle", "prefixes": 0},
        ]}}}
    sig = da._signals(fire)
    assert "10.0.255.9" in " ".join(sig.get("mpls_vpnv4_down", []))
    dec = da._d_mpls_l3vpn_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "VPNv4" in str(dec)
    assert "pe1" in dec["evidence"]["devices"]
    clean = {"mpls": {"pe1": {"vpnv4_neighbors": [{"neighbor": "10.0.255.2", "as": "65000", "state": "Established", "prefixes": 6}]}}}
    assert da._d_mpls_l3vpn_health(clean, da._signals(clean)) is None
    assert da._d_mpls_l3vpn_health({}, da._signals({})) is None


def test_d_mpls_l2vpn_health_fires_on_down_vc_only():
    """Universality (SP/MPLS L2VPN/pseudowire): a device with a VC in state DOWN fires
    _d_mpls_l2vpn_health (customer L2 circuit broken). Refutation: UP and STANDBY VCs (healthy
    states) and absent mpls axis both stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"mpls": {"pe1": {
        "l2vpn_vcs": [
            {"local_intf": "Gi1/0/2", "dest": "10.0.255.2", "vc_id": "200", "status": "UP"},
            {"local_intf": "Gi1/0/3", "dest": "10.0.255.9", "vc_id": "300", "status": "DOWN"},
        ]}}}
    sig = da._signals(fire)
    assert "300" in " ".join(sig.get("mpls_l2vc_down", []))
    dec = da._d_mpls_l2vpn_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "pseudowire" in str(dec).lower()
    assert "pe1" in dec["evidence"]["devices"]
    standby = {"mpls": {"pe1": {"l2vpn_vcs": [{"local_intf": "Gi1/0/4", "dest": "10.0.255.2", "vc_id": "201", "status": "STANDBY"}]}}}
    assert da._d_mpls_l2vpn_health(standby, da._signals(standby)) is None
    up = {"mpls": {"pe1": {"l2vpn_vcs": [{"local_intf": "Gi1/0/2", "dest": "10.0.255.2", "vc_id": "200", "status": "UP"}]}}}
    assert da._d_mpls_l2vpn_health(up, da._signals(up)) is None
    assert da._d_mpls_l2vpn_health({}, da._signals({})) is None


def test_d_lisp_fabric_session_down_fires_on_zero_established_vrf_only():
    """Universality (SD-Access LISP fabric control plane): a VRF with sessions configured (total>=1) but ZERO
    established fires _d_lisp_fabric_session_down (the node cannot register/resolve EID-to-RLOC -> overlay
    partition). Refutation -- ALL THREE must stay silent: (a) a healthy VRF (established>=1); (b) the BENIGN
    partial-Down case (an idle border/edge: one peer Down but established>=1 -- a lone Down session is normal
    per Cisco's TS guide and must not cry wolf); (c) the absent lisp axis."""
    import cisco_toolkit.design_advisor as da
    fire = {"lisp": {"edge1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 2,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Up"}]},
        {"vrf": "red", "total": 2, "established": 0,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Down"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Down"}]},
    ]}}}
    sig = da._signals(fire)
    assert any("VRF red" in x for x in sig.get("lisp_fabric_partition", []))
    dec = da._d_lisp_fabric_session_down(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "LISP" in str(dec)
    assert "edge1" in dec["evidence"]["devices"]
    # (a) healthy: every VRF has established >= 1
    healthy = {"lisp": {"edge1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 2,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Up"}]}]}}}
    assert da._d_lisp_fabric_session_down(healthy, da._signals(healthy)) is None
    # (b) benign partial-Down: a Down peer but established >= 1 -> must NOT fire (no cry-wolf)
    benign = {"lisp": {"border1": {"sessions": [
        {"vrf": "default", "total": 2, "established": 1,
         "peers": [{"peer": "10.0.255.2", "port": "4342", "state": "Up"},
                   {"peer": "10.0.255.3", "port": "4342", "state": "Down"}]}]}}}
    assert da._d_lisp_fabric_session_down(benign, da._signals(benign)) is None
    # (c) absent axis
    assert da._d_lisp_fabric_session_down({}, da._signals({})) is None


def test_d_cts_environment_data_health_fires_on_non_complete_only():
    """Universality (Cisco TrustSec / CTS segmentation): a device whose CTS environment-data 'Current state'
    is not COMPLETE fires _d_cts_environment_data_health (no SGT->policy map downloaded -> group-based
    segmentation blind/unenforced). Refutation (coverage-honest): a COMPLETE state -- EVEN WITH dead RADIUS
    servers -- stays silent, and an absent cts axis stays silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"cts": {"core1": {"environment_data": {
        "state": "WAITING_RESPONSE", "last_status": "Failed", "sgt_count": 0, "server_count": 0}}}}
    sig = da._signals(fire)
    assert "core1" in " ".join(sig.get("cts_env_stale", []))
    dec = da._d_cts_environment_data_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "TrustSec" in str(dec)
    assert "core1" in dec["evidence"]["devices"]
    # Healthy COMPLETE (servers DEAD on purpose) must NOT fire -- a cached COMPLETE set survives dead servers.
    clean = {"cts": {"core1": {"environment_data": {
        "state": "COMPLETE", "last_status": "Successful", "sgt_count": 7, "server_count": 2}}}}
    assert da._d_cts_environment_data_health(clean, da._signals(clean)) is None
    # Absent CTS axis must NOT fire (coverage-honest).
    assert da._d_cts_environment_data_health({}, da._signals({})) is None


def test_d_dmvpn_tunnel_health_fires_on_non_up_peer_only():
    """Universality (DMVPN WAN overlay mGRE/NHRP): a device with a DMVPN tunnel peer NOT in the UP state fires
    _d_dmvpn_tunnel_health (NHRP/IKE/down -> no overlay forwarding to that spoke/hub site). Refutation: every
    peer UP (normal healthy state) and an absent dmvpn axis both stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"dmvpn": {"hub1": {"peers": [
        {"interface": "Tunnel1", "nbma": "27.27.27.2", "tunnel_ip": "10.0.1.2", "state": "UP", "attrb": "D"},
        {"interface": "Tunnel1", "nbma": "37.37.37.3", "tunnel_ip": "10.0.1.3", "state": "NHRP", "attrb": "D"},
        {"interface": "Tunnel1", "nbma": "47.47.47.4", "tunnel_ip": "10.0.1.4", "state": "IKE", "attrb": "D"},
    ]}}}
    sig = da._signals(fire)
    assert "10.0.1.3" in " ".join(sig.get("dmvpn_down", []))
    assert "10.0.1.4" in " ".join(sig.get("dmvpn_down", []))
    dec = da._d_dmvpn_tunnel_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "DMVPN" in str(dec)
    assert dec["evidence"]["count"] == 2 and "hub1" in dec["evidence"]["devices"]
    # Healthy: every peer UP -> silent (no over-firing).
    clean = {"dmvpn": {"hub1": {"peers": [
        {"interface": "Tunnel1", "nbma": "27.27.27.2", "tunnel_ip": "10.0.1.2", "state": "UP", "attrb": "D"}]}}}
    assert da._d_dmvpn_tunnel_health(clean, da._signals(clean)) is None
    # Absent: no dmvpn axis -> silent.
    assert da._d_dmvpn_tunnel_health({}, da._signals({})) is None


def test_d_crypto_session_health_fires_on_down_session_only():
    """Universality (IPsec encrypted WAN): a device with a crypto session whose status begins with DOWN
    (DOWN / DOWN-NEGOTIATING -> no established IKE/IPsec SA) fires _d_crypto_session_health. Refutation: every
    UP-* status (UP-ACTIVE passing data, UP-IDLE established-idle, UP-NO-IKE IPsec-up-while-IKE-rekeys) and an
    absent crypto axis all stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"crypto": {"hub1": {"sessions": [
        {"interface": "Tunnel0", "peer": "10.0.255.2", "status": "UP-ACTIVE"},
        {"interface": "Tunnel1", "peer": "10.0.255.9", "status": "DOWN-NEGOTIATING"},
    ]}}}
    sig = da._signals(fire)
    assert "10.0.255.9" in " ".join(sig.get("crypto_sessions_down", []))
    dec = da._d_crypto_session_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "crypto session" in str(dec).lower()
    assert "hub1" in dec["evidence"]["devices"]
    # healthy: UP-ACTIVE, UP-IDLE and UP-NO-IKE are all established tunnels -> silent (no cry-wolf)
    for _ok in ("UP-ACTIVE", "UP-IDLE", "UP-NO-IKE"):
        clean = {"crypto": {"hub1": {"sessions": [{"interface": "Tunnel0", "peer": "10.0.255.2", "status": _ok}]}}}
        assert da._d_crypto_session_health(clean, da._signals(clean)) is None
    # plain DOWN also fires (not only DOWN-NEGOTIATING)
    hard = {"crypto": {"hub1": {"sessions": [{"interface": "Tunnel2", "peer": "10.0.255.8", "status": "DOWN"}]}}}
    assert da._d_crypto_session_health(hard, da._signals(hard)) is not None
    # absent crypto axis -> silent
    assert da._d_crypto_session_health({}, da._signals({})) is None


def test_d_bfd_session_health_fires_on_down_session_only():
    """Universality (BFD fast-failover): a device with a BFD session in the Down state fires
    _d_bfd_session_health (sub-second failover gone -> client falls back to slow native timers). Refutation:
    an all-Up device, an AdminDown-only device (operator-disabled, intentional -- must NOT cry-wolf), and an
    absent bfd axis all stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.2", "local_disc": "11", "remote_disc": "10", "state": "Up", "interface": "Gi1/0/1"},
        {"neighbor": "10.0.255.9", "local_disc": "12", "remote_disc": "0", "state": "Down", "interface": "Gi1/0/3"},
    ]}}}
    sig = da._signals(fire)
    assert "10.0.255.9" in " ".join(sig.get("bfd_down", []))
    dec = da._d_bfd_session_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "BFD" in str(dec)
    assert "core1" in dec["evidence"]["devices"]
    # healthy: every session Up -> silent
    clean = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.2", "local_disc": "11", "remote_disc": "10", "state": "Up", "interface": "Gi1/0/1"}]}}}
    assert da._d_bfd_session_health(clean, da._signals(clean)) is None
    # AdminDown (operator-disabled) is intentional, not a forwarding failure -> must stay silent
    admin = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.9", "local_disc": "12", "remote_disc": "0", "state": "AdminDown", "interface": "Gi1/0/3"}]}}}
    assert da._d_bfd_session_health(admin, da._signals(admin)) is None
    # absent axis -> silent
    assert da._d_bfd_session_health({}, da._signals({})) is None


def test_d_ipv6_dad_duplicate_fires_on_duplicate_state_only():
    """Universality (IPv6 addressing / ND): a device with a global IPv6 address in the DUPLICATE state fires
    _d_ipv6_dad_duplicate (DAD disabled the address -> the dual-stack interface is dark for IPv6). Refutation:
    a clean (unmarked) address, a transient TENTATIVE address, and an absent ipv6_nd axis ALL stay silent
    (coverage-honest -- a settled duplicate is the only firing state)."""
    import cisco_toolkit.design_advisor as da
    fire = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "admin_up": True, "proto_up": True, "ipv6_enabled": True,
         "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::1", "subnet": "2001:DB8:10::/64", "dad_state": "ok"}]},
        {"interface": "Vl30", "admin_up": True, "proto_up": True, "ipv6_enabled": True,
         "link_local": "FE80::30", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:30::1", "subnet": "2001:DB8:30::/64", "dad_state": "duplicate"}]},
    ]}}}
    sig = da._signals(fire)
    assert any("2001:DB8:30::1" in x for x in sig.get("ipv6_dad_duplicate", []))
    dec = da._d_ipv6_dad_duplicate(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "DUPLICATE" in str(dec)
    assert dec["principle"]["id"] == "ipv6-duplicate-address-dad-failure"
    assert "core1" in dec["evidence"]["devices"]
    # clean: every address dad_state 'ok' -> silent
    clean = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "ipv6_enabled": True, "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::1", "subnet": "2001:DB8:10::/64", "dad_state": "ok"}]}]}}}
    assert da._d_ipv6_dad_duplicate(clean, da._signals(clean)) is None
    # transient TENTATIVE (DAD in progress) -> silent
    tentative = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "ipv6_enabled": True, "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::9", "subnet": "2001:DB8:10::/64", "dad_state": "tentative"}]}]}}}
    assert da._d_ipv6_dad_duplicate(tentative, da._signals(tentative)) is None
    # absent axis -> silent
    assert da._d_ipv6_dad_duplicate({}, da._signals({})) is None


def test_d_ipv6_routing_adjacency_fires_on_stuck_adjacency_only():
    """Universality (IPv6 routing plane / dual-stack reachability): a device with an OSPFv3 neighbor stuck in a
    transient state (NOT FULL / NOT 2WAY) OR an IPv6 BGP peer not Established fires _d_ipv6_routing_adjacency
    (dual-stack reachability dark while IPv4 stays Up). Refutation, coverage-honest: a FULL + 2WAY OSPFv3 pair
    and an Established (numeric-PfxRcd) IPv6 BGP peer (all healthy resting states), and an absent ipv6_routing
    axis, all stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"ipv6_routing": {"sw1": {
        "ospfv3_neighbors": [
            {"neighbor_id": "10.0.0.1", "pri": "1", "state": "FULL", "role": "DR", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.7", "pri": "1", "state": "2WAY", "role": "DROTHER", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.9", "pri": "0", "state": "EXSTART", "role": "-", "interface": "Gi0/1"},
        ],
        "bgp_ipv6_neighbors": [
            {"neighbor": "2001:DB8:0:1::1", "as": "65001", "state": "Established", "prefixes": 12},
            {"neighbor": "2001:DB8:0:9::9", "as": "65009", "state": "Active", "prefixes": 0},
        ]}}}
    sig = da._signals(fire)
    assert "10.0.0.9" in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "EXSTART" in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "2001:DB8:0:9::9" in " ".join(sig.get("ipv6_bgp_down", []))
    # the two healthy OSPFv3 neighbors must NOT appear in the stuck list (FULL + 2WAY are resting states)
    assert "10.0.0.1" not in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "10.0.0.7" not in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    dec = da._d_ipv6_routing_adjacency(fire, sig)
    assert dec is not None and dec["priority"] == "High"
    assert "OSPFv3" in str(dec) and "sw1" in dec["evidence"]["devices"]
    # all-healthy: FULL + 2WAY OSPFv3, Established IPv6 BGP -> silent
    clean = {"ipv6_routing": {"sw1": {
        "ospfv3_neighbors": [
            {"neighbor_id": "10.0.0.1", "pri": "1", "state": "FULL", "role": "BDR", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.7", "pri": "1", "state": "2WAY", "role": "DROTHER", "interface": "Vlan10"},
        ],
        "bgp_ipv6_neighbors": [
            {"neighbor": "2001:DB8:0:1::1", "as": "65001", "state": "Established", "prefixes": 0}]}}}
    assert da._d_ipv6_routing_adjacency(clean, da._signals(clean)) is None
    # absent axis -> silent
    assert da._d_ipv6_routing_adjacency({}, da._signals({})) is None


def test_d_aci_critical_faults_fires_on_raised_unacked_only():
    """Universality (Cisco ACI / JSON-ingestion channel): a raised, unacknowledged critical/major faultInst
    fires _d_aci_critical_faults. Refutation (coverage-honest): a minor fault, an acknowledged fault, a
    cleared (lc != raised) fault, and an absent aci axis ALL stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"aci": {"apic1": {"faults": [
        {"code": "F1394", "severity": "critical", "lc": "raised", "ack": "no", "dn": "d1", "descr": "port down"},
        {"code": "F1234", "severity": "minor", "lc": "raised", "ack": "no", "dn": "d2", "descr": "minor"},
        {"code": "F3083", "severity": "major", "lc": "raised", "ack": "yes", "dn": "d3", "descr": "acked"},
        {"code": "F9", "severity": "critical", "lc": "raised-clearing", "ack": "no", "dn": "d4", "descr": "clearing"},
    ]}}}
    sig = da._signals(fire)
    assert len(sig.get("aci_faults", [])) == 1 and any("F1394" in x for x in sig["aci_faults"])
    dec = da._d_aci_critical_faults(fire, sig)
    assert dec is not None and dec["priority"] == "Critical" and "ACI" in str(dec)
    assert "apic1" in dec["evidence"]["devices"]
    clean = {"aci": {"apic1": {"faults": [
        {"code": "F1234", "severity": "minor", "lc": "raised", "ack": "no", "dn": "d", "descr": "m"}]}}}
    assert da._d_aci_critical_faults(clean, da._signals(clean)) is None
    assert da._d_aci_critical_faults({}, da._signals({})) is None


def test_d_aci_node_not_active_fires_on_nonactive_fabricst_only():
    """Universality (Cisco ACI): a fabricNode with fabricSt not active (decommissioned/inactive/disabled)
    fires _d_aci_node_not_active. An all-active fabric and an absent aci axis stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"aci": {"apic1": {"nodes": [
        {"id": "101", "name": "leaf-101", "fabric_st": "active", "ad_st": "on"},
        {"id": "102", "name": "leaf-102-OLD", "fabric_st": "decommissioned", "ad_st": "off"},
    ]}}}
    sig = da._signals(fire)
    assert any("102" in x for x in sig.get("aci_ghost_nodes", []))
    dec = da._d_aci_node_not_active(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "apic1" in dec["evidence"]["devices"]
    clean = {"aci": {"apic1": {"nodes": [{"id": "101", "name": "leaf-101", "fabric_st": "active", "ad_st": "on"}]}}}
    assert da._d_aci_node_not_active(clean, da._signals(clean)) is None
    assert da._d_aci_node_not_active({}, da._signals({})) is None


def test_d_aci_fabric_health_degraded_fires_below_90_only():
    """Universality (Cisco ACI): fabricHealthTotal.cur below 90 fires _d_aci_fabric_health_degraded; cur>=90
    and an absent aci axis stay silent (a measured score, never inferred from absence)."""
    import cisco_toolkit.design_advisor as da
    fire = {"aci": {"apic1": {"health": {"cur": 82, "max_sev": "critical"}}}}
    sig = da._signals(fire)
    assert sig.get("aci_health_degraded")
    dec = da._d_aci_fabric_health_degraded(fire, sig)
    assert dec is not None and dec["priority"] == "Medium" and "apic1" in dec["evidence"]["devices"]
    healthy = {"aci": {"apic1": {"health": {"cur": 96, "max_sev": "cleared"}}}}
    assert da._d_aci_fabric_health_degraded(healthy, da._signals(healthy)) is None
    assert da._d_aci_fabric_health_degraded({}, da._signals({})) is None


def test_d_sdwan_control_connection_down_fires_on_down_or_deficit_only():
    """Universality (Cisco Catalyst SD-WAN): a control connection state=down OR actual<expected fires
    _d_sdwan_control_connection_down. Refutation: an up, full-count connection and an absent sdwan axis stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"sdwan": {"mgr1": {"control_connections": [
        {"system_ip": "10.10.1.13", "host_name": "BR13", "peer_type": "vsmart", "state": "down", "expected": 2, "actual": 0},
        {"system_ip": "10.10.1.14", "host_name": "BR14", "peer_type": "vbond", "state": "up", "expected": 1, "actual": 1},
    ]}}}
    sig = da._signals(fire)
    assert any("BR13" in x for x in sig.get("sdwan_control_down", []))
    dec = da._d_sdwan_control_connection_down(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "mgr1" in dec["evidence"]["devices"]
    # deficit-only (state up but actual < expected) must also fire
    deficit = {"sdwan": {"mgr1": {"control_connections": [
        {"system_ip": "x", "host_name": "BR15", "peer_type": "vsmart", "state": "up", "expected": 2, "actual": 1}]}}}
    assert da._d_sdwan_control_connection_down(deficit, da._signals(deficit)) is not None
    # all up + full count -> silent
    clean = {"sdwan": {"mgr1": {"control_connections": [
        {"system_ip": "x", "host_name": "BR16", "peer_type": "vbond", "state": "up", "expected": 1, "actual": 1}]}}}
    assert da._d_sdwan_control_connection_down(clean, da._signals(clean)) is None
    assert da._d_sdwan_control_connection_down({}, da._signals({})) is None


def test_d_sdwan_device_unreachable_fires_on_unreachable_only():
    """Universality (Cisco Catalyst SD-WAN): a device with reachability=unreachable fires
    _d_sdwan_device_unreachable; a reachable device and an absent sdwan axis stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"sdwan": {"mgr1": {"devices": [
        {"system_ip": "10.10.1.1", "host_name": "DC1", "reachability": "reachable"},
        {"system_ip": "10.10.1.99", "host_name": "BR99", "reachability": "unreachable"},
    ]}}}
    sig = da._signals(fire)
    assert any("BR99" in x for x in sig.get("sdwan_unreachable", []))
    dec = da._d_sdwan_device_unreachable(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "mgr1" in dec["evidence"]["devices"]
    clean = {"sdwan": {"mgr1": {"devices": [{"system_ip": "x", "host_name": "DC1", "reachability": "reachable"}]}}}
    assert da._d_sdwan_device_unreachable(clean, da._signals(clean)) is None
    assert da._d_sdwan_device_unreachable({}, da._signals({})) is None


def test_compute_architecture_coverage_observed_vs_not():
    """Architecture-coverage SSOT: an axis present + a fired detector -> 'finding'; present + no finding ->
    'clean'; absent -> 'not-observed' (coverage-honest -- NEVER 'healthy'). Channels are tallied (ssh vs json)."""
    import cisco_toolkit.design_advisor as da
    snap = {
        "aci": {"core2": {"faults": [{"severity": "critical", "lc": "raised", "ack": "no"}]}},
        "bfd": {"core1": {"sessions": [{"state": "Up"}]}},   # observed but clean (no detector fired)
        "design_blueprint": {"decisions": [{"id": "aci-critical-fault-raised"}]},
    }
    cov = da.compute_architecture_coverage(snap)
    by = {c["key"]: c for c in cov["classes"]}
    assert by["aci"]["observed"] and by["aci"]["status"] == "finding" and by["aci"]["channel"] == "json"
    assert "aci-critical-fault-raised" in by["aci"]["findings"]
    assert by["bfd"]["observed"] and by["bfd"]["status"] == "clean" and by["bfd"]["findings"] == []
    assert by["sdwan"]["observed"] is False and by["sdwan"]["status"] == "not-observed"
    assert cov["summary"]["n_classes"] == 24
    assert cov["summary"]["by_channel"] == {"ssh": 20, "json": 4}
    assert cov["summary"]["n_with_findings"] == 1 and cov["summary"]["n_clean"] == 1
    # empty snapshot: every class not-observed, nothing fired (the coverage-honest baseline -- never 'healthy')
    empty = da.compute_architecture_coverage({})
    assert empty["summary"]["n_observed"] == 0 and empty["summary"]["n_not_observed"] == 24


def test_d_sdwan_omp_peer_down_fires_on_omp_down_only():
    """Universality (Cisco Catalyst SD-WAN OMP / deeper modeling): an edge with ompPeersDown>0 fires
    _d_sdwan_omp_peer_down (overlay routing degraded -- missing TLOCs/prefixes even with the control plane up).
    Refutation: a fully-peered edge (ompPeersDown 0) and an absent sdwan axis stay silent. Distinct signal
    from control-connection-down."""
    import cisco_toolkit.design_advisor as da
    fire = {"sdwan": {"mgr1": {"omp_counters": [
        {"system_ip": "10.10.1.13", "host_name": "BR13", "omp_up": 1, "omp_down": 1},
        {"system_ip": "10.10.1.1", "host_name": "DC1", "omp_up": 2, "omp_down": 0},
    ]}}}
    sig = da._signals(fire)
    assert any("BR13" in x for x in sig.get("sdwan_omp_down", []))
    dec = da._d_sdwan_omp_peer_down(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "OMP" in str(dec) and "mgr1" in dec["evidence"]["devices"]
    clean = {"sdwan": {"mgr1": {"omp_counters": [{"system_ip": "x", "host_name": "DC1", "omp_up": 2, "omp_down": 0}]}}}
    assert da._d_sdwan_omp_peer_down(clean, da._signals(clean)) is None
    assert da._d_sdwan_omp_peer_down({}, da._signals({})) is None


def test_d_aci_vrf_unenforced_fires_on_unenforced_only():
    """Universality (Cisco ACI logical / segmentation posture): a VRF with pcEnfPref=unenforced fires
    _d_aci_vrf_unenforced (no contracts between EPGs -> default-permit -> segmentation off). Refutation: an
    enforced VRF and an absent aci axis stay silent (coverage-honest -- fires only on the explicit attribute)."""
    import cisco_toolkit.design_advisor as da
    fire = {"aci": {"apic1": {"vrfs": [
        {"name": "prod-vrf", "tenant": "PROD", "pc_enf_pref": "enforced"},
        {"name": "legacy-vrf", "tenant": "LEGACY", "pc_enf_pref": "unenforced"},
    ]}}}
    sig = da._signals(fire)
    assert any("legacy-vrf" in x for x in sig.get("aci_vrf_unenforced", []))
    dec = da._d_aci_vrf_unenforced(fire, sig)
    assert dec is not None and dec["priority"] == "Medium" and "unenforced" in str(dec).lower()
    assert "apic1" in dec["evidence"]["devices"]
    clean = {"aci": {"apic1": {"vrfs": [{"name": "prod-vrf", "tenant": "PROD", "pc_enf_pref": "enforced"}]}}}
    assert da._d_aci_vrf_unenforced(clean, da._signals(clean)) is None
    assert da._d_aci_vrf_unenforced({}, da._signals({})) is None


def test_aci_move_groups_tenant_grouping():
    """ACI migration move-groups: the published logical census groups BY TENANT (the ACI migration boundary);
    EPGs are the finest unit; a tenant with an unenforced VRF carries a segmentation_gap; the biggest move
    group (most EPGs) leads. No ACI inventory -> {} (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    snap = {"aci": {"apic1": {
        "tenants": [{"name": "PROD", "dn": "uni/tn-PROD"}, {"name": "LEGACY", "dn": "uni/tn-LEGACY"}],
        "vrfs": [{"name": "prod-vrf", "tenant": "PROD", "pc_enf_pref": "enforced"},
                 {"name": "legacy-vrf", "tenant": "LEGACY", "pc_enf_pref": "unenforced"}],
        "bds": [{"name": "prod-bd", "tenant": "PROD"}],
        "epgs": [{"name": "web", "tenant": "PROD"}, {"name": "db", "tenant": "PROD"}, {"name": "old", "tenant": "LEGACY"}],
    }}}
    mg = da._aci_move_groups(snap)
    by = {g["tenant"]: g for g in mg["groups"]}
    assert mg["n_tenants"] == 2 and mg["n_epgs"] == 3
    assert by["PROD"]["n_epgs"] == 2 and by["PROD"]["segmentation_gap"] is False
    assert by["LEGACY"]["segmentation_gap"] is True and "legacy-vrf" in by["LEGACY"]["unenforced_vrfs"]
    assert mg["n_segmentation_gaps"] == 1
    assert mg["groups"][0]["tenant"] == "PROD"   # 2 EPGs leads LEGACY's 1
    assert da._aci_move_groups({}) == {}


# ============================ architecture-coverage slices (build wave) =========================== #
def test_d_pim_rp_health_fires_on_running_pim_without_rp_only():
    """Multicast PIM-SM: a device with PIM sparse-mode RUNNING (a live neighbor) whose rp-mapping WAS collected
    but learned ZERO RP and is not SSM-only fires _d_pim_rp_health (broken ASM forwarding, RFC 7761). Refutation:
    RP learned, SSM-only, PIM not running (no neighbor), and rp-mapping not collected ALL stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"pim": {"core1": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [], "groups": [], "ssm_only": False},
                              "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]}}}
    sig = da._signals(fire)
    assert sig["pim_no_rp"] == ["core1"] and sig["pim_running"] == ["core1"]
    dec = da._d_pim_rp_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "RP" in str(dec)
    assert dec["principle"]["id"] == "multicast-pim-rp-resilience" and dec["evidence"]["devices"] == ["core1"]
    rp = {"pim": {"core1": {"rp_mapping": {"present": True, "rp_count": 1, "ssm_only": False},
                            "neighbors": [{"neighbor": "x", "interface": "Gi1", "uptime": "1d"}]}}}
    assert da._d_pim_rp_health(rp, da._signals(rp)) is None
    ssm = {"pim": {"core1": {"rp_mapping": {"present": True, "rp_count": 0, "groups": ["232.0.0.0/8"], "ssm_only": True},
                            "neighbors": [{"neighbor": "x", "interface": "Gi1", "uptime": "1d"}]}}}
    assert da._d_pim_rp_health(ssm, da._signals(ssm)) is None
    notrun = {"pim": {"core1": {"rp_mapping": {"present": True, "rp_count": 0, "ssm_only": False}, "neighbors": []}}}
    assert da._d_pim_rp_health(notrun, da._signals(notrun)) is None
    notcoll = {"pim": {"core1": {"rp_mapping": {}, "neighbors": [{"neighbor": "x", "interface": "Gi1", "uptime": "1d"}]}}}
    assert da._d_pim_rp_health(notcoll, da._signals(notcoll)) is None
    assert da._d_pim_rp_health({}, da._signals({})) is None


def test_d_ipv6_fhs_fires_on_dualstack_access_without_raguard():
    """IPv6 first-hop security: a switch that is OBSERVABLY dual-stack (>=1 IPv6 SVI) with host-facing access
    ports but NO RA-Guard fires _d_ipv6_fhs (rogue-RA gateway hijack, RFC 6104). Refutation: RA-Guard present,
    pure-IPv4 (not dual-stack), no access ports (core/transit), and an absent axis ALL stay silent."""
    import cisco_toolkit.design_advisor as da
    access_if = {"acc1": {"Gi0/2": {"switchport_mode": "Access", "vlan": "10"}}}
    fire = {"interfaces": access_if,
            "ipv6_fhs": {"acc1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False,
                                  "dhcp_guard_present": False, "ra_guard_policies": [], "ra_guard_ifaces": []}}}
    sig = da._signals(fire)
    assert sig["ipv6_fhs_open"] == 1 and sig["ipv6_fhs_open_hosts"] == ["acc1"]
    assert sig["ipv6_fhs_vlans"] == [10] and sig["ipv6_fhs_open_dhcp"] == 1
    dec = da._d_ipv6_fhs(fire, sig)
    assert dec is not None and "RA-Guard" in str(dec) and "RFC 6104" in str(dec)
    assert dec["principle"]["id"] == "ipv6-first-hop-security-suite-at-access-edge" and dec["priority"] == "High"
    guarded = {"interfaces": access_if,
               "ipv6_fhs": {"acc1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": True,
                                     "dhcp_guard_present": True}}}
    assert da._d_ipv6_fhs(guarded, da._signals(guarded)) is None
    v4only = {"interfaces": access_if,
              "ipv6_fhs": {"acc1": {"dualstack": False, "ipv6_svi_vlans": [], "ra_guard_present": False}}}
    assert da._d_ipv6_fhs(v4only, da._signals(v4only)) is None
    coreonly = {"interfaces": {"core1": {"Po1": {"switchport_mode": "Trunk"}}},
                "ipv6_fhs": {"core1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False}}}
    assert da._d_ipv6_fhs(coreonly, da._signals(coreonly)) is None
    assert da._d_ipv6_fhs({}, da._signals({})) is None


def test_d_ntp_sync_fires_on_unsynchronized_clock_not_absence():
    """OPERATIONAL clock-sync: a DEFINITIVELY-unsynchronized clock (synchronized False or stratum 16) fires
    _d_ntp_sync -- the complement to the config-only no-ntp check. Refutation: a synchronized clock, a clock
    whose sync state was never observed (synchronized None), and an absent NTP axis ALL stay silent."""
    import cisco_toolkit.design_advisor as da
    snap = {"ntp": {
        "core1": {"synchronized": False, "stratum": 16, "reference": "", "source": "ios-status"},
        "core2": {"synchronized": True, "stratum": 2, "reference": "10.255.0.254", "source": "nxos-peer-status"},
        "access1": {"synchronized": True, "stratum": 3, "reference": "10.0.10.2", "source": "ios-status"},
    }}
    sig = da._signals(snap)
    assert sig["ntp_unsynced"] == ["core1 (stratum 16)"]
    dec = da._d_ntp_sync(snap, sig)
    assert dec is not None and "UNSYNCHRONIZED" in str(dec) and "core1" in str(dec)
    assert dec["priority"] == "High" and dec["principle"]["id"] == "mgmt-time-sync-logging-baseline"
    s16 = {"ntp": {"r1": {"synchronized": None, "stratum": 16, "reference": "", "source": "nxos-peer-status"}}}
    assert da._d_ntp_sync(s16, da._signals(s16)) is not None
    ok = {"ntp": {"core1": {"synchronized": True, "stratum": 2, "reference": "1.2.3.4", "source": "ios-status"}}}
    assert da._d_ntp_sync(ok, da._signals(ok)) is None
    unk = {"ntp": {"core1": {"synchronized": None, "stratum": None, "reference": "", "source": ""}}}
    assert da._d_ntp_sync(unk, da._signals(unk)) is None
    assert da._d_ntp_sync({}, da._signals({})) is None


def test_d_port_security_errdisable_fires_on_secure_shutdown_not_restrict_count():
    """Access-edge port-security: a secured access port currently err-disabled (Port Status 'secure-shutdown')
    is a live outage -> _d_port_security_errdisable fires, naming the offending MAC. Non-cry-wolf: a restrict-mode
    port that stays 'secure-up' while accumulating a violation COUNT is SILENT; an absent axis is silent too."""
    import cisco_toolkit.design_advisor as da
    snap = {"port_security": {"access1": {
        "Gi0/2":  {"port_status": "secure-up",       "violation_mode": "Shutdown", "violation_count": 0,  "last_src": "aabb.ccdd.ee01"},
        "Gi0/3":  {"port_status": "secure-shutdown", "violation_mode": "Shutdown", "violation_count": 3,  "last_src": "0011.22aa.0099"},
        "Gi0/10": {"port_status": "secure-up",       "violation_mode": "Restrict", "violation_count": 17, "last_src": "aabb.ccdd.ee10"},
    }}}
    sig = da._signals(snap)
    assert sig["psec_errdisabled"] == ["access1 Gi0/3 (offender 0011.22aa.0099)"]
    dec = da._d_port_security_errdisable(snap, sig)
    assert dec is not None and "Secure-shutdown" in str(dec) and "0011.22aa.0099" in str(dec)
    assert dec["priority"] == "High" and dec["evidence"]["devices"] == ["access1"]
    restrict_only = {"port_security": {"access1": {"Gi0/10": {"port_status": "secure-up", "violation_mode": "Restrict", "violation_count": 99}}}}
    assert da._d_port_security_errdisable(restrict_only, da._signals(restrict_only)) is None
    assert da._d_port_security_errdisable({}, da._signals({})) is None


def test_d_storm_control_action_flags_configured_noaction_only():
    """Storm-control: a CONFIGURED rule whose action is 'None' (drops a storm silently) fires
    _d_storm_control_action. Refutation: a rule with a real action (Shutdown/Trap), an UN-configured row, and an
    absent storm_control axis are all silent -- the toothless-rule STATE, never blanket absence."""
    import cisco_toolkit.design_advisor as da
    snap = {"storm_control": {"access1": [
        {"interface": "Gi0/2", "traffic": "broadcast", "action": "None", "configured": True},
        {"interface": "Gi0/2", "traffic": "multicast", "action": "None", "configured": True},
        {"interface": "Gi0/3", "traffic": "broadcast", "action": "Shutdown", "configured": True},
        {"interface": "Gi0/4", "traffic": "broadcast", "action": "None", "configured": False},
    ]}}
    sig = da._signals(snap)
    assert sig["storm_noaction"] == ["access1 Gi0/2 broadcast", "access1 Gi0/2 multicast"]
    assert sig["storm_noaction_devices"] == ["access1"]
    dec = da._d_storm_control_action(snap, sig)
    assert dec is not None and "action 'None'" in str(dec) and "Gi0/2" in str(dec) and dec["priority"] == "Medium"
    ok = {"storm_control": {"access1": [{"interface": "Gi0/2", "traffic": "broadcast", "action": "Trap", "configured": True}]}}
    assert da._d_storm_control_action(ok, da._signals(ok)) is None
    assert da._d_storm_control_action({}, da._signals({})) is None


def test_d_storm_control_active_flags_blocking_only():
    """Storm-control ACTIVE suppression: a port whose Filter State is 'Blocking' is dropping a live broadcast/
    multicast storm RIGHT NOW -> _d_storm_control_active fires (directly observed, so it works even on the
    Catalyst 'show storm-control' form that omits the Action column). Refutation: a 'Forwarding' port, an absent
    storm_control axis, and a port with no filter_state all stay silent -- only the observed Blocking state fires."""
    import cisco_toolkit.design_advisor as da
    snap = {"storm_control": {"access1": [
        {"interface": "Gi0/5", "traffic": "broadcast", "filter_state": "Blocking", "current": "2.08m", "configured": True},
        {"interface": "Gi0/6", "traffic": "multicast", "filter_state": "Forwarding", "current": "0", "configured": True}]}}
    sig = da._signals(snap)
    assert any("Gi0/5" in x for x in sig["storm_blocking"]) and sig["storm_blocking_devices"] == ["access1"]
    dec = da._d_storm_control_active(snap, sig)
    assert dec is not None and "Blocking" in str(dec) and "Gi0/5" in str(dec) and dec["priority"] == "High"
    assert "Gi0/6" not in str(dec)   # the Forwarding port is NOT flagged (coverage-honest)
    fwd = {"storm_control": {"access1": [{"interface": "Gi0/6", "traffic": "broadcast", "filter_state": "Forwarding", "configured": True}]}}
    assert da._d_storm_control_active(fwd, da._signals(fwd)) is None
    assert da._d_storm_control_active({}, da._signals({})) is None


def test_d_qos_runtime_drops_fires_and_refutes_cry_wolf():
    """QoS RUNTIME: an egress class actually SHEDDING traffic fires _d_qos_runtime_drops -- HIGH if a priority/LLQ
    class is congestion-dropped, MEDIUM for a data-only over-threshold class. CRY-WOLF GUARD: a busy data class
    tail-dropping a handful of packets (<1%) and a class just below the ratio stay silent; an absent axis silent."""
    import cisco_toolkit.design_advisor as da
    bad = {"qos_runtime": {"wan1": [
        {"interface": "Gi0/0/0", "policy": "WAN", "class": "VOICE", "priority": True,
         "drop_pkts": 1840521, "output_pkts": 24817400, "police_drop_pkts": 0},
        {"interface": "Gi0/0/0", "policy": "WAN", "class": "BULK", "priority": False,
         "drop_pkts": 50000, "output_pkts": 500000, "police_drop_pkts": 0}]}}
    dec = da._d_qos_runtime_drops(bad, da._signals(bad))
    assert dec is not None and dec["priority"] == "High" and "VOICE" in str(dec) and "LLQ" in str(dec)
    assert dec["evidence"]["devices"] == ["wan1"]
    data_only = {"qos_runtime": {"sw1": [{"interface": "Gi1", "policy": "P", "class": "D", "priority": False,
                                          "drop_pkts": 20000, "output_pkts": 200000, "police_drop_pkts": 0}]}}
    assert da._d_qos_runtime_drops(data_only, da._signals(data_only))["priority"] == "Medium"
    noisy = {"qos_runtime": {"sw1": [
        {"interface": "Gi1", "policy": "P", "class": "BULK", "priority": False,
         "drop_pkts": 250, "output_pkts": 3000000, "police_drop_pkts": 0},
        {"interface": "Gi1", "policy": "P", "class": "VOICE", "priority": True,
         "drop_pkts": 0, "output_pkts": 99, "police_drop_pkts": 0}]}}
    assert da._d_qos_runtime_drops(noisy, da._signals(noisy)) is None
    edge = {"qos_runtime": {"sw1": [{"interface": "Gi1", "policy": "P", "class": "D", "priority": False,
                                     "drop_pkts": 1000, "output_pkts": 1000000, "police_drop_pkts": 0}]}}
    assert da._d_qos_runtime_drops(edge, da._signals(edge)) is None
    pol = {"qos_runtime": {"sw1": [{"interface": "Gi1", "policy": "P", "class": "EF", "priority": True,
                                    "drop_pkts": 0, "output_pkts": 50000, "police_drop_pkts": 5000}]}}
    assert da._d_qos_runtime_drops(pol, da._signals(pol)) is not None
    assert da._d_qos_runtime_drops({}, da._signals({})) is None


def test_d_shadow_infra_flags_undocumented_switch_router_only():
    """Undocumented (shadow) infrastructure: an infra CDP/LLDP neighbour whose canonical hostname is NOT an
    assessed device fires _d_shadow_infra. Coverage-honest: an in-scope neighbour (even advertised by its
    FQDN/serial) does NOT fire, and the axis being absent is silent."""
    import cisco_toolkit.design_advisor as da
    snap = {
        "health_scores": [{"switch": "core1"}, {"switch": "core2"}],
        "devices": {"core1": {"hostname": "core1"}, "core2": {"hostname": "core2"}},
        "shadow_infra": {"core2": [
            {"device_id": "wan-edge-rtr1.lab", "platform": "cisco ASR1001-X", "capabilities": "Router",
             "proto": "cdp", "local_intf": "Eth1/47"},
            {"device_id": "core1.lab(FOC1234ABCD)", "platform": "cisco WS-C3850", "capabilities": "Router Switch",
             "proto": "cdp", "local_intf": "Po1"}]},
    }
    sig = da._signals(snap)
    names = [s["name"] for s in sig["shadow_infra"]]
    assert names == ["wan-edge-rtr1.lab"]
    assert sig["shadow_infra"][0]["seen_from"] == ["core2"] and sig["shadow_infra"][0]["via"] == ["core2:Eth1/47"]
    assert sig["shadow_infra_devices"] == ["core2"]
    dec = da._d_shadow_infra(snap, sig)
    assert dec is not None and "undocumented infrastructure" in str(dec) and "wan-edge-rtr1.lab" in str(dec)
    assert dec["priority"] == "High" and dec["principle"]["id"] == "discover-undocumented-infrastructure-before-cutover"
    clean = {"health_scores": [{"switch": "core1"}, {"switch": "core2"}], "devices": {},
             "shadow_infra": {"core2": [{"device_id": "core1.lab", "capabilities": "Router Switch",
                                         "proto": "cdp", "local_intf": "Po1"}]}}
    assert da._d_shadow_infra(clean, da._signals(clean)) is None
    assert da._d_shadow_infra({}, da._signals({})) is None


def test_d_nve_peer_health_flags_down_vtep():
    """Universality (NX-OS VXLAN-EVPN): a DOWN VTEP (NVE) peer partitions the overlay -> _d_nve_peer_health
    fires; silent when all peers Up or no NVE. The engine's OWN target fabric, previously blind."""
    import cisco_toolkit.design_advisor as da
    snap = {"overlay": {"leaf1": {"nve_peers": [
        {"interface": "nve1", "peer_ip": "10.0.0.1", "state": "Up", "learn_type": "CP"},
        {"interface": "nve1", "peer_ip": "10.0.0.2", "state": "Down", "learn_type": "CP"},
    ]}}}
    sig = da._signals(snap)
    assert sig["nve_peers_down"] == ["leaf1 10.0.0.2"]
    dec = da._d_nve_peer_health(snap, sig)
    assert dec is not None and "DOWN" in str(dec) and "10.0.0.2" in str(dec)
    allup = {"overlay": {"leaf1": {"nve_peers": [{"interface": "nve1", "peer_ip": "10.0.0.1", "state": "Up", "learn_type": "CP"}]}}}
    assert da._d_nve_peer_health(allup, da._signals(allup)) is None
    assert da._d_nve_peer_health({}, da._signals({})) is None


def test_d_fhrp_resilience_flags_untracked_or_no_preempt_active_gateways():
    """Universality (FHRP): an ACTIVE gateway with no interface tracking (black-holes on uplink loss) or
    no preempt (non-deterministic primary) fires _d_fhrp_resilience; a clean active gateway and an absent
    fhrp_detail axis are silent. [HISTORY-REDACTED] runs no FHRP -> first health check proven on a non-[HISTORY-REDACTED] architecture."""
    import cisco_toolkit.design_advisor as da
    fragile = {"fhrp_detail": {"core1": [
        {"ifname": "Vlan10", "group": "10", "state": "Active", "preempt": True, "track": []},               # no tracking
        {"ifname": "Vlan20", "group": "20", "state": "Active", "preempt": False, "track": [{"obj": "1"}]},   # no preempt
        {"ifname": "Vlan99", "group": "99", "state": "Standby", "preempt": False, "track": []},              # standby -> ignored
    ]}}
    sig = da._signals(fragile)
    assert sig["fhrp_no_track"] == ["core1 Vlan10 grp 10"] and sig["fhrp_no_preempt"] == ["core1 Vlan20 grp 20"]
    dec = da._d_fhrp_resilience(fragile, sig)
    assert dec is not None and "NO interface tracking" in str(dec) and "preemption DISABLED" in str(dec)
    clean = {"fhrp_detail": {"core1": [{"ifname": "Vlan10", "group": "10", "state": "Active", "preempt": True, "track": [{"obj": "1"}]}]}}
    assert da._d_fhrp_resilience(clean, da._signals(clean)) is None
    assert da._d_fhrp_resilience({}, da._signals({})) is None


def test_d_fhrp_state_fires_on_broken_not_absent_fhrp():
    """DET-fhrp-state-01: broken-but-PRESENT FHRP (split-brain / mixed protocol / mismatched group|VIP) fires
    _d_fhrp_state; pure FHRP-ABSENCE ('no FHRP') does NOT (that is _d_fhrp's Critical domain). Coverage-honest
    -- on a fleet running no FHRP at all (e.g. [HISTORY-REDACTED]) this correctly stays silent."""
    import cisco_toolkit.design_advisor as da
    broken = {"fhrp": [
        {"vid": 10, "issues": ["two active routers (a, b) — split-brain"], "members": [{"host": "a"}, {"host": "b"}]},
        {"vid": 20, "issues": ["mixed FHRP protocols (HSRP vs VRRP)"], "members": [{"host": "c"}]},
    ]}
    sig = da._signals(broken)
    assert sig["fhrp_broken"] == 2 and set(sig["fhrp_broken_vids"]) == {10, 20}
    dec = da._d_fhrp_state(broken, sig)
    assert dec is not None and "split-brain" in str(dec) and "CONFIGURED BUT BROKEN" in str(dec)
    # pure absence must NOT trigger the broken-state detector (that is _d_fhrp's domain)
    absent = {"fhrp": [{"vid": 30, "issues": ["3 gateways but no FHRP — no first-hop redundancy"], "members": [{"host": "d"}]}]}
    sig2 = da._signals(absent)
    assert sig2["fhrp_broken"] == 0 and da._d_fhrp_state(absent, sig2) is None


# ===================================================================== DC-fabric corpus enrichment
# The design brain learns the modern DC target vocabulary (EVPN/VXLAN leaf-spine, Multi-Site, DCI,
# active-active, cloud/SDDC, L4-L7 services) mined from the [HISTORY-REDACTED] reference corpus + the real [HISTORY-REDACTED] SDD.
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
    # the 4 NEW domains exist with the expected membership (by_domain surfaces them automatically). dc-fabric is
    # now SHARED: the ACI-corpus addendum adds the fabric operating-model CHOICE to it -- allow that one
    # documented extra, but nothing else may creep into a DC-corpus domain undetected.
    _ACI_ADDENDUM_EXTRA = {"dc-fabric": {"dc-fabric-aci-vs-nxos-evpn-operating-model"}}
    # the 2026-06-21 mega-wave gap addendum documents its OWN additions to KB-thin DC-corpus domains
    # (cloud / aci-multisite / aci-services); allow exactly those, still guarding undocumented creep.
    _WAVE2_BY_DOM = {}
    for p in design_kb._WAVE2_GAP_ADDENDUM:
        _WAVE2_BY_DOM.setdefault(p["domain"], set()).add(p["id"])
    for dom, ids in _DC_CORPUS_IDS.items():
        got = {p["id"] for p in design_kb.by_domain(dom)}
        assert set(ids) <= got, f"domain {dom} must contain {set(ids) - got}"
        unexpected = got - set(ids) - _ACI_ADDENDUM_EXTRA.get(dom, set()) - _WAVE2_BY_DOM.get(dom, set())
        assert not unexpected, f"domain {dom}: unexpected principles {unexpected}"
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


def test_[HISTORY-REDACTED]_engagement_profile_rightsizes_to_the_real_target():
    """The SDD-derived [HISTORY-REDACTED] engagement register (requirements.[HISTORY-REDACTED].json, grounded in the human-authored
    Solution Design) right-sizes the blueprint so it concretely recommends the real target: the DC-fabric +
    Multi-Site choices flip to recommended (growth supplied), defense-in-depth flips (data_classification
    supplied), and effective_priority is computed -- while the un-supplied keys stay honest open questions."""
    import os
    from cisco_toolkit.design_advisor import load_requirements
    path = os.path.join(os.path.dirname(__file__), "..", "requirements.[HISTORY-REDACTED].json")
    reg = load_requirements(path)
    assert reg.get("growth_horizon") and reg.get("data_classification"), "[HISTORY-REDACTED] register must carry growth + zones"
    assert "convergence_budget_ms" not in reg and "address_space" not in reg, \
        "[HISTORY-REDACTED] register must NOT fabricate a convergence budget or supernet the SDD does not state"
    bp = compute_design_blueprint(_snap(), requirements=reg)
    by = {d["id"]: d for d in bp["decisions"]}
    for pid in ("dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed",
                _DC_CORPUS_ACTIONABLE, "security-defense-in-depth-segmentation"):
        assert by[pid]["status"] == "recommended", f"{pid} must flip to recommended under the [HISTORY-REDACTED] register"
    assert all("effective_priority" in d for d in bp["decisions"])
    assert bp["requirements_model"]["provided"] is True


# ============================================================ evidence-grounded actionable detectors
# Two NEW actionable detectors over already-collected evidence (a follow-up to the doctrine enrichment),
# grounded + refutation-verified against the real [HISTORY-REDACTED] snapshot: (1) rapid-PVST at high VLAN scale -> MST,
# (2) on-air-critical application tiers left L3-exposed -> macro-segment. Both must stay coverage-honest.
_ACTIONABLE_NEW = {
    "dc-stp-mst-instance-scale": "dc-switching",
    "security-isolate-oncritical-application-tier": "security",
}


def test_new_actionable_detector_principles_present_and_honest():
    """Both new detector principles exist, are cited, carry a recommended action, live in their domain,
    and are engine_actionable=True -- which the emit-invariant separately proves they actually deliver."""
    for pid, dom in _ACTIONABLE_NEW.items():
        p = design_kb.by_id(pid)
        assert p, f"missing actionable principle {pid}"
        assert p.get("citation") and p.get("recommended_action") and p.get("design_intent")
        assert p.get("engine_actionable") is True, f"{pid} is wired to a detector -> must be actionable"
        assert pid in {x["id"] for x in design_kb.by_domain(dom)}, f"{pid} must be in domain {dom}"


def test_stp_mst_scale_detector_is_rapid_pvst_scoped():
    """Rapid-PVST across a high VLAN count is flagged for MST (control-plane instance scale) -- but the
    detector is RAPID-PVST-scoped: the legacy (non-rapid) PVST switches belong exclusively to
    _d_stp_det (dc-stp-determinism-edge-protection), so counting them here would be a double-count.
    Refutation: legacy-pvst-only must NOT emit it; below the VLAN threshold must NOT emit it."""
    fires = {d["id"] for d in compute_design_blueprint(_maximal_snap())["decisions"]}
    assert "dc-stp-mst-instance-scale" in fires, "rapid-PVST + 22 VLANs (>= threshold) must emit it"
    # below threshold: base _snap has rapid-PVST but only 2 VLANs -> must NOT fire
    base = {d["id"] for d in compute_design_blueprint(_snap())["decisions"]}
    assert "dc-stp-mst-instance-scale" not in base, "must not fire below the VLAN-count threshold"
    # legacy-pvst-ONLY at high VLAN count -> determinism fires, MST-scale must NOT (no double-count)
    legacy = _snap(
        protocol_health=[{"switch": "d0", "protocol": "STP",
                          "summary": "mode pvst; 0 blocked, 0 inconsistent; max TCN 1"}],
        l3_forwarding=[{"switch": "dist1", "vlan": str(v), "svi_ip": f"10.0.{v}.1",
                        "fhrp": "none", "risk": "no-FHRP"} for v in range(10, 32)],
        interfaces={f"acc{v}": {f"Gi1/0/{v}": {"switchport_mode": "Access", "vlan": str(v)}}
                    for v in range(10, 32)})
    leg_ids = {d["id"] for d in compute_design_blueprint(legacy)["decisions"]}
    assert "dc-stp-determinism-edge-protection" in leg_ids, "legacy PVST must still trigger determinism"
    assert "dc-stp-mst-instance-scale" not in leg_ids, "legacy PVST must NOT be double-counted as MST-scale"


def test_oncritical_segmentation_exposure_detector_evidence_gated():
    """When the segmentation axis observes on-air-critical application tiers left L3-reachable
    (summary.n_oncrit_exposed > 0), a macro-segmentation decision is emitted naming them; remove the
    observation and it disappears (it is grounded, never assumed)."""
    snap = _snap(segmentation={
        "summary": {"n_oncrit_exposed": 2, "gateway_acl_coverage": 0.0, "n_gateways": 50, "n_vrfs": 1},
        "gateway_acl": {"n_gateways": 50, "n_with_acl": 0, "coverage_pct": 0.0},
        "domains": [{"domain": "Media Fabric (SMPTE ST 2110)", "tier": "On-air critical",
                     "isolated": False, "gateways": 40},
                    {"domain": "Audio over IP (Dante / AES67)", "tier": "On-air critical",
                     "isolated": False, "gateways": 10}],
        "vrfs": [{"vrf": "(global)"}]})
    d = next((x for x in compute_design_blueprint(snap)["decisions"]
              if x["id"] == "security-isolate-oncritical-application-tier"), None)
    assert d, "exposed on-air-critical tiers must emit the macro-segmentation decision"
    assert "Media Fabric" in d["evidence"]["summary"], "decision must name the observed exposed tier(s)"
    # refutation: no observed exposure -> no decision
    none = {x["id"] for x in compute_design_blueprint(_snap())["decisions"]}
    assert "security-isolate-oncritical-application-tier" not in none


# ===================================================== net-new evidence-grounded design detectors (v2)
# Five MORE actionable detectors over already-collected-but-unused evidence axes, grounded + refutation-
# verified against the real [HISTORY-REDACTED] snapshot: addressing overlaps (renumber-before-merge), physical-layer
# faults (remediate-before-cutover), port/PoE capacity headroom, dual-homing/cluster preservation across
# the migration, and native-VLAN-1 on inter-switch trunks (VLAN-hopping). All coverage-honest: each reads
# a populated snapshot axis and DISAPPEARS when that evidence is absent (proven below by refutation).
_ACTIONABLE_NEW2 = {
    "addressing-resolve-overlaps-before-merge": "methodology",
    "physical-remediate-l1-faults-before-cutover": "methodology",
    "capacity-size-target-with-growth-headroom": "methodology",
    "migration-preserve-dual-homed-endpoints": "scenario-pattern",
    "l2-dedicated-native-vlan-on-trunks": "security",
    "design-resolve-false-health-masks-before-baseline": "methodology",
    "dc-restore-degraded-portchannel-members-before-cutover": "dc-switching",
}


def test_evidence_detector_principles_v2_present_and_honest():
    """Each v2 detector principle exists, is fully authored (intent/tradeoffs/alternatives/observable),
    cited, lives in its domain, and is engine_actionable=True -- which the emit-invariant separately
    proves the advisor actually delivers."""
    for pid, dom in _ACTIONABLE_NEW2.items():
        p = design_kb.by_id(pid)
        assert p, f"missing actionable principle {pid}"
        for field in ("citation", "recommended_action", "design_intent", "alternatives",
                      "tradeoffs", "observable", "trigger"):
            assert p.get(field), f"{pid} missing {field}"
        assert p.get("engine_actionable") is True, f"{pid} is wired to a detector -> must be actionable"
        assert pid in {x["id"] for x in design_kb.by_domain(dom)}, f"{pid} must be in domain {dom}"


def _snap_v2(**over):
    """_snap seeded with the five v2 detector trigger axes."""
    base = dict(
        addressing_conflicts={"dup_ip": [{"ip": "1.1.1.1", "where": [["d0", "mgmt0", None],
                                                                       ["d1", "mgmt0", None]]},
                                          {"ip": "10.0.0.1", "where": [["d2", "Vlan10", None],
                                                                       ["d3", "Vlan10", None]]}],
                              "dup_subnet": [{"subnet": "10.0.0.0/24", "where": ["d0", "d1"]}]},
        physical_health=[{"switch": "d0", "port": "Gi1/0/1", "crc_errors": 5, "input_errors": 9,
                          "duplex": "half", "status": "connected"},
                         {"switch": "d1", "port": "Gi1/0/2", "crc_errors": 0, "input_errors": 0,
                          "duplex": "full", "status": "err-disabled"}],
        capacity=[{"hostname": "d0", "port_util": 95.0, "free_ports": 2, "poe_util": 10.0},
                  {"hostname": "d1", "port_util": 40.0, "free_ports": 30, "poe_util": 0.0}],
        # clusters is seeded but must be IGNORED (it's a vendor/class affinity analytic, not an HA cluster)
        endpoint_dependencies={"dual_homed": [{"endpoint": "e1"}, {"endpoint": "e2"}],
                               "clusters": [{"vendor": "HP", "count": 600}], "shared_ip": [{"ip": "10.0.0.9"}]},
        # operational_drift false-health: 2 High (mask true state) + 1 Low (already covered) -> High-gated to 2
        operational_drift=[{"severity": "High", "category": "False-health", "devices": ["dx"],
                            "title": "Temporary L2 bridge on dx"},
                           {"severity": "High", "category": "False-health", "devices": ["dy"],
                            "title": "PoE fault on powered endpoint(s) on dy"},
                           {"severity": "Low", "category": "False-health", "devices": ["dz"],
                            "title": "Native VLAN 1 on 99 inter-switch trunk(s)"}],
        interfaces={"acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10"}},
                    "trunkA": {"Eth1/1": {"switchport_mode": "trunk", "trunk_native_vlan": "1"}},
                    "trunkB": {"Eth1/2": {"switchport_mode": "trunk", "trunk_native_vlan": "99"}}},
        # protocol_intelligence EtherChannel member anomalies: 2 High (down/suspended) + 1 Low -> gated to 2
        protocol_intelligence=[{"switch": "dh1", "protocol": "EtherChannel", "state": "D",
                                "severity": "High", "meaning": "Member port is down."},
                               {"switch": "dh2", "protocol": "EtherChannel", "state": "s",
                                "severity": "High", "meaning": "Member is suspended."},
                               {"switch": "dh3", "protocol": "EtherChannel", "state": "P",
                                "severity": "Low", "meaning": "Member bundled OK."}],
    )
    base.update(over)
    return _snap(**base)


def test_v2_detectors_fire_when_seeded_and_read_numbers_from_evidence():
    """All five fire on seeded evidence and the summaries carry the COUNTS read from the snapshot
    (not hardcoded): 2 dup-IP + 1 dup-subnet, 2 dirty ports, 1 hot switch (port_util 95% >= 85%; the 40%
    switch excluded), 2 dual-homed (the seeded affinity 'cluster' is IGNORED), 1 native-VLAN-1 trunk
    (trunkB on VLAN 99 is correctly excluded)."""
    fires = {d["id"]: d for d in compute_design_blueprint(_snap_v2())["decisions"]}
    for pid in _ACTIONABLE_NEW2:
        assert pid in fires, f"{pid} must fire on seeded evidence"
    assert "2 duplicate IP" in fires["addressing-resolve-overlaps-before-merge"]["evidence"]["summary"]
    assert "1 overlapping subnet" in fires["addressing-resolve-overlaps-before-merge"]["evidence"]["summary"]
    assert "1 inter-switch trunk(s) across 1 switch" in \
        fires["l2-dedicated-native-vlan-on-trunks"]["evidence"]["summary"]
    cap = fires["capacity-size-target-with-growth-headroom"]["evidence"]["summary"]
    assert "1 of 2 switch" in cap and ">= 85% port" in cap
    dh = fires["migration-preserve-dual-homed-endpoints"]
    assert "2 dual-homed endpoint" in dh["evidence"]["summary"]
    assert "cluster" not in dh["evidence"]["summary"].lower()    # the affinity 'cluster' must NOT leak in
    assert dh["evidence"]["count"] == 2                          # count is dual_homed only, not + clusters


def test_v2_detectors_are_evidence_gated():
    """Refutation: strip each axis and the matching decision DISAPPEARS -- not hardcoded, never asserted
    from absence (coverage-honesty)."""
    bare = {d["id"] for d in compute_design_blueprint(
        _snap_v2(addressing_conflicts={}, physical_health=[], capacity=[], endpoint_dependencies={},
                 operational_drift=[], protocol_intelligence=[],
                 interfaces={"acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10"}}}))["decisions"]}
    for pid in _ACTIONABLE_NEW2:
        assert pid not in bare, f"{pid} must DISAPPEAR when its evidence is absent"


def test_v2_native_vlan_count_matches_canonical_interface_evidence():
    """SSOT cross-lock: the native-VLAN-1 detector counts the SAME trunk+native==1 ports the rest of the
    engine keys off (model.trunk_native_vlan), so its emitted count can't drift from the canonical figure."""
    snap = _snap_v2()
    expect = sum(1 for ports in snap["interfaces"].values() for pd in ports.values()
                 if "trunk" in str(pd.get("switchport_mode", "")).lower()
                 and str(pd.get("trunk_native_vlan", "")).strip() == "1")
    d = next(x for x in compute_design_blueprint(snap)["decisions"]
             if x["id"] == "l2-dedicated-native-vlan-on-trunks")
    assert d["evidence"]["count"] == expect == 1


def test_v2_false_health_detector_is_high_severity_gated():
    """The operational_drift false-health detector fires on HIGH-severity masks only (temporary L2 bridges,
    masked faults that hide the true redundancy/health state), and excludes the Low rows (e.g. the
    native-VLAN row already owned by l2-dedicated-native-vlan-on-trunks -> no double-count). Refutation:
    Low-only or empty must NOT fire."""
    d = next((x for x in compute_design_blueprint(_snap_v2())["decisions"]
              if x["id"] == "design-resolve-false-health-masks-before-baseline"), None)
    assert d, "2 High false-health items must emit the baseline-integrity decision"
    assert d["evidence"]["count"] == 2, "High-gated count (the Low native-VLAN row is excluded)"
    assert "Temporary L2 bridge" in d["evidence"]["summary"]
    # refutation: only Low false-health -> no decision (not asserted from a non-masking drift)
    low_only = compute_design_blueprint(_snap_v2(operational_drift=[
        {"severity": "Low", "category": "False-health", "devices": ["dz"], "title": "Multi-year uptime"}]))
    assert not any(x["id"] == "design-resolve-false-health-masks-before-baseline"
                   for x in low_only["decisions"])
    # refutation: axis absent -> no decision
    gone = compute_design_blueprint(_snap_v2(operational_drift=[]))
    assert not any(x["id"] == "design-resolve-false-health-masks-before-baseline"
                   for x in gone["decisions"])


def test_v2_bundle_health_detector_is_severity_gated():
    """Degraded EtherChannel/port-channel members (down/suspended/standalone, the engine's High-severity
    protocol_intelligence findings) emit a restore-before-cutover decision; the gate reads the engine's
    OWN severity (SSOT, not re-derived), so a Low/bundled-OK row is excluded. Refutation: Low-only or
    empty must NOT fire."""
    d = next((x for x in compute_design_blueprint(_snap_v2())["decisions"]
              if x["id"] == "dc-restore-degraded-portchannel-members-before-cutover"), None)
    assert d, "High EtherChannel member anomalies must emit the bundle-restore decision"
    assert d["evidence"]["count"] == 2, "2 High; the Low (bundled-OK) row is excluded by the severity gate"
    assert "2 degraded EtherChannel" in d["evidence"]["summary"]   # records, not "members" (count is per-finding)
    low = compute_design_blueprint(_snap_v2(protocol_intelligence=[
        {"switch": "x", "protocol": "EtherChannel", "state": "P", "severity": "Low", "meaning": "ok"}]))
    assert not any(x["id"] == "dc-restore-degraded-portchannel-members-before-cutover"
                   for x in low["decisions"])
    gone = compute_design_blueprint(_snap_v2(protocol_intelligence=[]))
    assert not any(x["id"] == "dc-restore-degraded-portchannel-members-before-cutover"
                   for x in gone["decisions"])


# ----------------------------------------- ACI vs standalone NX-OS VXLAN-EVPN fabric operating-model choice
def _dc_scale_snap(**over):
    """A DC-scale snapshot (>= _LARGE_L2_VLANS VLANs in one VRF, large inventory) so a spine-leaf fabric is
    genuinely a candidate target and the operating-model realisation choice is in scope."""
    base = {
        "l3_forwarding": [{"switch": "dist1", "vlan": str(v), "svi_ip": f"10.0.{v}.1",
                           "fhrp": "none", "risk": "no-FHRP"} for v in range(10, 26)],   # 16 VLANs
        "collection_completeness": {"summary": {"inventory": 40, "complete": 35, "not_collected": 5}},
    }
    base.update(over)
    return _snap(**base)


def test_fabric_operating_model_is_a_recognised_requirement_key():
    """The new fabric_operating_model WHY-key is recognised on every register path and canonicalised to one
    of {'aci','nxos-evpn'} (free text in, two stable values out); nonsense is dropped, not guessed."""
    from cisco_toolkit.design_advisor import (REQUIREMENTS_KEYS, requirements_from_interview,
                                              load_requirements)
    import json
    assert "fabric_operating_model" in REQUIREMENTS_KEYS
    for raw, want in [("ACI", "aci"), ("apic", "aci"), ("NX-OS EVPN", "nxos-evpn"),
                      ("vxlan-evpn", "nxos-evpn"), ("NDFC", "nxos-evpn"), ("nonsense", None)]:
        got = requirements_from_interview({"fabric_operating_model": raw}).get("fabric_operating_model")
        assert got == want, f"interview {raw!r} -> {got!r} (want {want!r})"


def test_fabric_operating_model_choice_is_requirement_gated_and_resolves():
    """The DC fabric OPERATING-MODEL realisation (Cisco ACI vs standalone NX-OS VXLAN-EVPN) is a top-down
    CHOICE, never assumed from brownfield evidence. Absent the requirement it is an open question that
    presents BOTH and assumes NEITHER; supplied, the target-state dimension resolves to the chosen model
    and the gated decision flips to recommended. (Refutation of a silent default.)"""
    from cisco_toolkit.design_advisor import compute_target_state, compute_design_blueprint
    from cisco_toolkit import design_kb
    snap = _dc_scale_snap()

    ts0 = compute_target_state(snap)                                      # no requirements
    dim = next((d for d in ts0["dimensions"] if d.get("requirement_needed") == "fabric_operating_model"), None)
    assert dim is not None and "operating model" in dim["area"].lower()
    low = dim["target"].lower()
    assert "aci" in low and "evpn" in low                                # presents both, picks neither

    ev = compute_target_state(snap, {"fabric_operating_model": "nxos-evpn"})
    de = next(d for d in ev["dimensions"] if "operating model" in d["area"].lower())
    assert not de.get("requirement_needed") and de["confidence"] == "Candidate"
    assert "evpn" in de["target"].lower()                                # resolved to standalone NX-OS-EVPN

    ac = compute_target_state(snap, {"fabric_operating_model": "aci"})
    da = next(d for d in ac["dimensions"] if "operating model" in d["area"].lower())
    assert not da.get("requirement_needed") and "aci" in da["target"].lower()

    pid = "dc-fabric-aci-vs-nxos-evpn-operating-model"
    d0 = {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}
    d1 = {d["id"]: d for d in compute_design_blueprint(snap, {"fabric_operating_model": "aci"})["decisions"]}
    assert d0[pid]["status"] == "needs-requirement" and d1[pid]["status"] == "recommended"
    # the driver principle exists and is traceable; emitted via _NEEDS => engine_actionable like its siblings
    p = design_kb.by_id(pid)
    assert p and p["engine_actionable"] is True and p["domain"] == "dc-fabric"


def test_fabric_operating_model_dimension_absent_for_small_non_dc_estate():
    """Coverage-honesty: the operating-model TARGET-STATE dimension must not present a fabric realisation for
    a small estate where no spine-leaf fabric is a candidate -- that would be noise, not a recommendation."""
    from cisco_toolkit.design_advisor import compute_target_state
    small = _snap(collection_completeness={"summary": {"inventory": 6, "complete": 6, "not_collected": 0}},
                  l3_forwarding=[{"switch": "d", "vlan": "10", "svi_ip": "10.0.0.1", "fhrp": "hsrp"}])
    ts = compute_target_state(small)
    assert not any("operating model" in d["area"].lower() for d in ts["dimensions"])


def test_target_state_dimension_drivers_are_real_kb_principles():
    """Every principle id a target-state dimension cites as a 'driver' must exist in the KB -- a dangling
    driver would render as an un-tooltipped id in the HLD/explorer and break decision->doctrine traceability."""
    from cisco_toolkit.design_advisor import compute_target_state
    kb_ids = {p["id"] for p in design_kb.DOCTRINE}
    for req in (None, {"fabric_operating_model": "aci"},
                {"fabric_operating_model": "nxos-evpn", "growth_horizon": "3y +60%"}):
        ts = compute_target_state(_dc_scale_snap(), req)
        for d in ts["dimensions"]:
            for drv in d.get("drivers", []):
                assert drv in kb_ids, f"dimension {d['area']!r} cites unknown driver principle {drv!r}"


def test_aci_corpus_addendum_cited_complete_and_coverage_honest():
    """COVERAGE-HONESTY LOCK for the ACI/EVPN/SP design-corpus addendum (mined from the real ACI HLD/LLD/NIP
    + EVPN/SP deep-dives). Iterates the addendum GENERICALLY so it validates whatever is appended: every
    principle is complete + cites its source, ids are unique, and -- since the L1-L4 assessment collects NO
    ACI/APIC/controller/EPG/contract/policy state -- the ONLY principle that may claim engine_actionable is
    the requirement-gated fabric operating-model CHOICE (emitted via _NEEDS). Everything else is doctrine."""
    add = design_kb._ACI_CORPUS_ADDENDUM
    assert isinstance(add, list) and add, "the ACI corpus addendum must exist and be non-empty"
    ids = [p["id"] for p in add]
    assert len(ids) == len(set(ids)), f"duplicate ids in the ACI addendum: {ids}"
    _FIELDS = ("id", "domain", "title", "priority", "engine_actionable", "design_intent",
               "tradeoffs", "trigger", "observable", "recommended_action", "alternatives", "citation")
    for p in add:
        for f in _FIELDS:
            assert p.get(f) not in (None, ""), f"{p.get('id')} missing/empty field {f!r}"
        if p["engine_actionable"]:
            assert p["id"] == "dc-fabric-aci-vs-nxos-evpn-operating-model", \
                f"{p['id']} claims engine_actionable, but only the requirement-gated fabric operating-model " \
                "CHOICE may -- ACI/controller state is not collected, so the rest must be honest doctrine"
            # and an actionable addendum principle must actually be EMITTED (no overstated coverage)
            emitted = {d["id"] for d in compute_design_blueprint(_maximal_snap())["decisions"]}
            assert p["id"] in emitted, f"{p['id']} is engine_actionable but the advisor never emits it"


def test_sp_corpus_addendum_cited_complete_and_coverage_honest():
    """COVERAGE-HONESTY LOCK for the Service-Provider / Segment-Routing addendum (mined from the D:\\ SP
    corpus: SR-MPLS/SRv6, inter-AS L3VPN, L2VPN, ngMVPN, MPLS-QoS, transport hygiene). Iterates generically:
    every principle complete + cited + unique id, and -- because an L1-L4 ENTERPRISE brownfield assessment
    collects NO SR/LDP/RSVP/MP-BGP-VPN/MVPN/L2VPN control-plane state -- EVERY SP principle is doctrine
    (engine_actionable=False), with NO exception. The new SP domains are registered + surface via by_domain."""
    add = design_kb._SP_CORPUS_ADDENDUM
    assert isinstance(add, list) and len(add) >= 12, "the SP-transport corpus addendum must exist and be substantial"
    ids = [p["id"] for p in add]
    assert len(ids) == len(set(ids)), f"duplicate ids in the SP addendum: {ids}"
    _FIELDS = ("id", "domain", "title", "priority", "engine_actionable", "design_intent",
               "tradeoffs", "trigger", "observable", "recommended_action", "alternatives", "citation")
    for p in add:
        for f in _FIELDS:
            assert p.get(f) not in (None, ""), f"{p.get('id')} missing/empty field {f!r}"
        assert p["engine_actionable"] is False, \
            f"{p['id']} must be doctrine (engine_actionable=False) -- no SR/MPLS-VPN/MVPN core state is collected"
    # the new SP domains exist and surface generically (so HLD §4.4 / explorer / chat reason with them)
    for dom in ("segment-routing", "sp-transport", "sp-l2vpn", "sp-mvpn"):
        assert design_kb.by_domain(dom), f"new SP domain {dom!r} must contain principles"


def test_sdwan_corpus_addendum_cited_complete_and_coverage_honest():
    """COVERAGE-HONESTY LOCK for the SD-WAN / modern-WAN addendum (Catalyst SD-WAN: 4-plane controller fabric,
    OMP, TLOC/transport-independence, app-aware SLA, centralized policy, segmentation, SASE/SIG, multi-region).
    Iterates generically: complete + cited + unique id, and -- because an L1-L4 enterprise assessment collects
    NO SD-WAN overlay/controller/OMP/policy state -- EVERY SD-WAN principle is doctrine (engine_actionable=False),
    no exception. The sd-wan domain is registered + surfaces via by_domain."""
    add = design_kb._SDWAN_CORPUS_ADDENDUM
    assert isinstance(add, list) and len(add) >= 10, "the SD-WAN corpus addendum must exist and be substantial"
    ids = [p["id"] for p in add]
    assert len(ids) == len(set(ids)), f"duplicate ids in the SD-WAN addendum: {ids}"
    _FIELDS = ("id", "domain", "title", "priority", "engine_actionable", "design_intent",
               "tradeoffs", "trigger", "observable", "recommended_action", "alternatives", "citation")
    for p in add:
        for f in _FIELDS:
            assert p.get(f) not in (None, ""), f"{p.get('id')} missing/empty field {f!r}"
        assert p["engine_actionable"] is False, \
            f"{p['id']} must be doctrine (engine_actionable=False) -- no SD-WAN overlay/controller state is collected"
    assert design_kb.by_domain("sd-wan"), "the sd-wan domain must contain principles"


def test_mega_corpus_addendum_cited_complete_and_coverage_honest():
    """COVERAGE-HONESTY LOCK for the multi-domain mega addendum (SD-Access/campus-fabric, wireless, network
    automation/telemetry, DC-compute/storage, cloud-native/container, IPv6 depth, ACI-advanced). Iterates
    generically: complete + cited + unique id, and -- because an L1-L4 IOS/NX-OS assessment collects no
    wireless / SD-Access / automation-controller / container / UCS / cloud / ACI-controller state -- EVERY
    principle is doctrine (engine_actionable=False), no exception. New domains registered + surface via by_domain."""
    add = design_kb._MEGA_CORPUS_ADDENDUM
    assert isinstance(add, list) and len(add) >= 24, "the mega addendum must exist and be substantial"
    ids = [p["id"] for p in add]
    assert len(ids) == len(set(ids)), f"duplicate ids in the mega addendum: {ids}"
    _FIELDS = ("id", "domain", "title", "priority", "engine_actionable", "design_intent",
               "tradeoffs", "trigger", "observable", "recommended_action", "alternatives", "citation")
    for p in add:
        for f in _FIELDS:
            assert p.get(f) not in (None, ""), f"{p.get('id')} missing/empty field {f!r}"
        assert p["engine_actionable"] is False, \
            f"{p['id']} must be doctrine (engine_actionable=False) -- none of this state is collected"
    for dom in ("campus-fabric", "wireless", "automation", "dc-compute", "cloud-native"):
        assert design_kb.by_domain(dom), f"new domain {dom!r} must contain principles"
