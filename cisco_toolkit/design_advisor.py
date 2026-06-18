"""The automated senior-network-DESIGN-engineer brain: turn collected assessment evidence into a
canonical, CCDE-grounded target-state DESIGN BLUEPRINT.

`compute_design_blueprint(snap, requirements=None)` is the single source of truth for design intent.
It reads the engine's already-computed evidence (it never re-derives it) and matches it against the
`engine_actionable` principles in `design_kb`, emitting traceable design DECISIONS at the altitude a
senior designer reasons at: each decision names its driver (the WHY), cites the observed EVIDENCE
(snapshot fields), cites the CCDE PRINCIPLE, states the recommended target pattern, the alternatives a
designer would weigh, and the trade-off AXES it spends from. It also produces a per-axis trade-off
scorecard, a coverage caveat, and -- per the doctrine's first principle, design top-down from the WHY
-- a requirements model: absent a requirements register it surfaces the open questions rather than
assuming; supplied one, it right-sizes (re-scores) every decision.

Discipline (mirrors the engine's coverage-honesty rules): every detector is EVIDENCE-GATED -- remove
the condition from the snapshot and the decision disappears. A design claim is never asserted from
absent evidence ("not observed" is not "healthy"); not-collected devices are an explicit unknown.
"""
import re

from . import design_kb

PRANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
_SCORE = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Info": 0}

# Security-finding ids (config-security / CIS axis) that bear on the MANAGEMENT plane vs general
# device hardening -- kept aligned with the auditor's emitted ids.
_MGMT_FAIL_IDS = {"vty-hardening", "insecure-snmp", "no-aaa", "telnet-enabled",
                  "weak-user-pw", "weak-enable", "password-encryption"}
_HARDEN_FAIL_IDS = {"risky-services", "no-banner", "no-logging", "no-ntp"}

_LARGE_L2_VLANS = 12  # a flat estate carrying this many VLANs in one (global) VRF is an oversized fault domain


# ----------------------------------------------------------------------------- defensive coercers
def _as_list(x):
    return x if isinstance(x, list) else []


def _as_dict(x):
    return x if isinstance(x, dict) else {}


def _as_int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _vlan_count(snap):
    try:
        from .analyze import vlan_inventory
        return len(vlan_inventory(snap))
    except Exception:
        vids = set()
        for r in _as_list(snap.get("l3_forwarding")):
            vids.add(str(r.get("vlan")))
        return len([v for v in vids if v and v != "None"])


# ----------------------------------------------------------------------------- evidence signals
def _no_fhrp_vlans(snap):
    out = []
    for g in _as_list(snap.get("fhrp")):
        issues = [str(i).lower() for i in _as_list(g.get("issues"))]
        if any(("no fhrp" in i) or ("first-hop" in i) or ("first hop" in i) for i in issues):
            out.append(g)
    return out


def _signals(snap):
    sig = {}
    bad_fhrp = _no_fhrp_vlans(snap)
    sig["no_fhrp"] = len(bad_fhrp)
    devs = []
    for g in bad_fhrp:
        for m in _as_list(g.get("members")):
            h = m.get("host")
            if h and h not in devs:
                devs.append(h)
    sig["no_fhrp_devices"] = devs

    links = _as_list(snap.get("link_centrality"))
    bridges = [x for x in links if x.get("is_bridge")]
    sig["bridges"] = len(bridges)
    sig["bridge_links"] = [f"{x.get('a_host')}<->{x.get('b_host')}" for x in bridges[:12]]
    bh = []
    for x in bridges:
        for h in (x.get("a_host"), x.get("b_host")):
            if h and h not in bh:
                bh.append(h)
    sig["bridge_hosts"] = bh

    fi = _as_list(snap.get("failure_impact"))
    sig["nobackup_high"] = sum(1 for x in fi if x.get("severity") == "High" and not _as_int(x.get("backup")))

    life = _as_list(_as_dict(snap.get("lifecycle_risk")).get("per_device"))
    sig["eol"] = sum(1 for d in life if str(d.get("band", "")).lower().startswith("past"))
    sig["near"] = sum(1 for d in life if "near" in str(d.get("band", "")).lower())
    sig["eol_devices"] = [d.get("host") for d in life if str(d.get("band", "")).lower().startswith("past")][:12]

    qos = _as_list(_as_dict(snap.get("qos_audit")).get("per_device"))
    sig["qos_assessable"] = sum(1 for d in qos if d.get("assessable"))
    sig["qos_none"] = sum(1 for d in qos if d.get("assessable") and d.get("mode") == "none")
    sig["qos_none_hosts"] = [d.get("host") for d in qos if d.get("assessable") and d.get("mode") == "none"]

    fail_hosts = {}
    for host, v in _as_dict(snap.get("security")).items():
        for f in _as_list(_as_dict(v).get("findings")):
            if f.get("status") == "fail":
                fail_hosts.setdefault(f.get("id"), set()).add(host)
    sig["mgmt_hosts"] = sorted({h for fid in _MGMT_FAIL_IDS for h in fail_hosts.get(fid, set())})
    sig["mgmt_devices"] = len(sig["mgmt_hosts"])
    harden = {h for fid in _HARDEN_FAIL_IDS for h in fail_hosts.get(fid, set())}
    for host, v in _as_dict(snap.get("config_hygiene")).items():
        s = _as_dict(_as_dict(v).get("summary"))
        if _as_int(s.get("unused")) or _as_int(s.get("undefined")):
            harden.add(host)
    sig["harden_devices"] = len(harden)
    sig["mgmt_fail_ids"] = sorted(fid for fid in _MGMT_FAIL_IDS if fail_hosts.get(fid))

    sig["vlans"] = _vlan_count(snap)
    vrfs = _as_list(_as_dict(snap.get("segmentation")).get("vrfs"))
    sig["single_vrf"] = len(vrfs) <= 1
    sig["gw_count"] = sum(_as_int(v.get("gateway_count")) for v in vrfs)

    stp = [x for x in _as_list(snap.get("protocol_health")) if x.get("protocol") == "STP"]
    sig["stp_blocked"] = sum(1 for x in stp if _stp_blocked(x))
    sig["stp_legacy"] = sum(1 for x in stp if _stp_legacy(x))
    sig["vtp_server"] = any(x.get("protocol") == "VTP" and "server" in str(x.get("summary", "")).lower()
                            for x in _as_list(snap.get("protocol_health")))

    igps = set()
    for _h, d in _as_dict(snap.get("routing_neighbors")).items():
        for proto, peers in _as_dict(d).items():
            if proto in ("ospf", "isis", "eigrp", "rip") and _as_list(peers):
                igps.add(proto)
    sig["igps"] = sorted(igps)

    q = _as_dict(_as_dict(snap.get("multicast_intelligence")).get("querier"))
    sig["querier_gaps"] = len(_as_list(q.get("gap_vlans")))
    sig["mcast_risks"] = len(_as_list(_as_dict(snap.get("multicast_intelligence")).get("risks")))

    cc = _as_dict(_as_dict(snap.get("collection_completeness")).get("summary"))
    sig["not_collected"] = _as_int(cc.get("not_collected"))
    sig["inventory"] = _as_int(cc.get("inventory"))
    sig["collected"] = _as_int(cc.get("complete"))
    return sig


def _stp_blocked(row):
    m = re.search(r"(\d+)\s+blocked", str(row.get("summary", "")))
    return bool(m) and int(m.group(1)) > 0


def _stp_legacy(row):
    s = str(row.get("summary", "")).lower()
    return ("pvst" in s and "rapid" not in s) or "802.1d" in s or "mode pvst" in s


# ----------------------------------------------------------------------------- decision builder
def _decision(pid, summary, count, axes, fields, priority=None, status="recommended",
              confidence="Observed", driver="", devices=None, requirements_needed=None):
    p = design_kb.by_id(pid) or {}
    return {
        "id": pid,
        "title": p.get("title", pid),
        "domain": p.get("domain", ""),
        "priority": priority or p.get("priority", "Medium"),
        "status": status,
        "confidence": confidence,
        "driver": driver or (p.get("design_intent", "")[:200]),
        "evidence": {"summary": summary, "count": count,
                     "devices": list(devices or [])[:12], "fields": list(fields)},
        "principle": {"id": pid, "title": p.get("title", ""), "citation": p.get("citation", "")},
        "recommended_action": p.get("recommended_action", ""),
        "alternatives": p.get("alternatives", ""),
        "tradeoffs": p.get("tradeoffs", ""),
        "axes": list(axes),
        "requirements_needed": list(requirements_needed or []),
    }


# ----------------------------------------------------------------------------- detectors (evidence-gated)
def _d_fhrp(snap, sig):
    if sig["no_fhrp"] <= 0:
        return None
    return _decision(
        "fhrp-first-hop-gateway-redundancy",
        f"{sig['no_fhrp']} gateway VLAN(s) have a single gateway and no first-hop redundancy "
        f"(HSRP/VRRP/GLBP) -- each is a per-VLAN single point of failure.",
        sig["no_fhrp"], ["availability", "convergence"],
        ["fhrp[].issues", "l3_forwarding[].fhrp", "failure_impact[].fhrp"],
        priority="Critical", driver="Gateway resilience: a VLAN must survive loss of its distribution switch.",
        devices=sig["no_fhrp_devices"])


def _d_spof(snap, sig):
    if sig["bridges"] <= 0:
        return None
    return _decision(
        "topology-triangles-not-squares-rings",
        f"{sig['bridges']} link(s) are cut-edges (their loss partitions the topology); "
        f"{sig['nobackup_high']} device(s) strand endpoints with no backup path on failure.",
        sig["bridges"], ["availability", "convergence"],
        ["link_centrality[].is_bridge", "failure_impact[].backup", "failure_impact[].stranded"],
        priority="High", driver="Physical redundancy: recovery should not depend on a single link or node.",
        devices=sig["bridge_hosts"])


def _d_eol(snap, sig):
    if sig["eol"] <= 0:
        return None
    extra = f" ({sig['near']} more approaching LDoS)" if sig["near"] else ""
    return _decision(
        "lifecycle-eol-out-of-critical-roles",
        f"{sig['eol']} device(s) are past last-day-of-support{extra} -- unsupported hardware/software "
        f"in forwarding roles cannot be safely relied on in the target design.",
        sig["eol"], ["availability", "cost"],
        ["lifecycle_risk.per_device[].band", "software_risk.per_device[].train_band"],
        priority="Critical", driver="Supportability: the target fabric must not inherit end-of-support assets.",
        devices=sig["eol_devices"])


def _d_qos(snap, sig):
    if sig["qos_none"] <= 0:
        return None
    return _decision(
        "qos-trust-boundary-end-to-end",
        f"{sig['qos_none']} of {sig['qos_assessable']} assessable device(s) carry no QoS configuration "
        f"-- there is no trust boundary at the access/voice edge and all traffic is best-effort.",
        sig["qos_none"], ["availability", "manageability"],
        ["qos_audit.per_device[].mode", "qos_audit.findings"],
        priority="High", driver="Application performance: real-time traffic needs a trust boundary and queuing.",
        devices=sig["qos_none_hosts"])


def _d_mgmt(snap, sig):
    if sig["mgmt_devices"] <= 0:
        return None
    ids = ", ".join(sig["mgmt_fail_ids"][:6]) or "management-plane"
    return _decision(
        "mgmt-secure-protocols-and-rbac",
        f"{sig['mgmt_devices']} device(s) fail management-plane hardening ({ids}).",
        sig["mgmt_devices"], ["security", "manageability"],
        ["security[host].findings[].status", "security[host].findings[].id"],
        priority="Critical", driver="Management-plane integrity: secure access, SNMPv3 and AAA/RBAC.",
        devices=sig["mgmt_hosts"])


def _d_harden(snap, sig):
    if sig["harden_devices"] <= 0:
        return None
    return _decision(
        "security-device-hardening-baseline",
        f"{sig['harden_devices']} device(s) deviate from the device-hardening baseline "
        f"(risky services, logging/NTP/banner, or unused/undefined config structures).",
        sig["harden_devices"], ["security", "manageability"],
        ["security[host].findings", "config_hygiene[host].summary"],
        priority="High", driver="Reduce the control-plane attack surface to a CIS-style baseline.")


def _d_coverage(snap, sig):
    if sig["not_collected"] <= 0:
        return None
    return _decision(
        "fhrp-not-observed-is-not-healthy",
        f"{sig['not_collected']} of {sig['inventory']} inventoried device(s) were not collected -- their "
        f"role and redundancy are UNKNOWN. The design must collect them (incl. any uncollected core) "
        f"before asserting target-state resilience; absence of evidence is not redundancy.",
        sig["not_collected"], ["availability", "manageability"],
        ["collection_completeness.summary.not_collected"],
        priority="Critical", confidence="Coverage-gap",
        driver="Coverage honesty: do not design resilience on devices you have not seen.")


def _d_flat_l2(snap, sig):
    if sig["vlans"] < _LARGE_L2_VLANS or not sig["single_vrf"]:
        return None
    return _decision(
        "dc-restrict-vlan-span-routed-access",
        f"{sig['vlans']} VLANs ride a single (global) VRF across the estate -- an oversized, flat L2 "
        f"fault domain whose failover and blast radius are bounded only by spanning tree.",
        sig["vlans"], ["scalability", "modularity", "convergence"],
        ["vlan_inventory", "segmentation.vrfs", "executive_brief.scale.n_vlans"],
        priority="High", driver="Bound the L2 fault domain: restrict VLAN span / move L3 toward the access edge.")


def _d_stp_lag(snap, sig):
    if sig["stp_blocked"] <= 0:
        return None
    return _decision(
        "dc-multichassis-lag-over-stp",
        f"{sig['stp_blocked']} device(s) have spanning-tree-blocked redundant link(s) sitting idle -- "
        f"capacity is wasted and failover depends on STP reconvergence.",
        sig["stp_blocked"], ["load_balancing", "availability", "convergence"],
        ["protocol_health[STP].summary"],
        priority="High", driver="Use both uplinks: multi-chassis LAG (vPC/VSS/SVL/MLAG) instead of STP blocking.")


def _d_stp_det(snap, sig):
    if not (sig["stp_legacy"] or sig["vtp_server"]):
        return None
    bits = []
    if sig["stp_legacy"]:
        bits.append(f"{sig['stp_legacy']} device(s) run legacy (non-rapid) spanning tree")
    if sig["vtp_server"]:
        bits.append("VTP server mode is active (a fleet-wide VLAN-change blast radius)")
    return _decision(
        "dc-stp-determinism-edge-protection",
        "; ".join(bits) + " -- L2 control is not deterministic.",
        sig["stp_legacy"], ["availability", "manageability", "convergence"],
        ["protocol_health[STP].summary", "protocol_health[VTP].summary"],
        priority="High", driver="Deterministic L2: rapid-PVST/MST, aligned roots, edge protection, VTP off/transparent.")


def _d_igp(snap, sig):
    if len(sig["igps"]) < 2:
        return None
    return _decision(
        "igp-link-state-default",
        f"Multiple IGPs are in use ({', '.join(sig['igps'])}) -- mixed control planes mean redistribution "
        f"boundaries, route-feedback risk and added operational complexity.",
        len(sig["igps"]), ["simplicity", "optimal_routing", "convergence"],
        ["routing_neighbors[host]"],
        priority="High", driver="Rationalise the IGP: prefer one link-state protocol with a hierarchy.")


def _d_mcast(snap, sig):
    if sig["querier_gaps"] <= 0 and sig["mcast_risks"] <= 0:
        return None
    return _decision(
        "multicast-security-and-l2-edge",
        f"{sig['querier_gaps']} active multicast VLAN(s) lack an IGMP querier and {sig['mcast_risks']} "
        f"multicast risk(s) were observed -- multicast may be flooded or stranded at cutover.",
        sig["querier_gaps"] + sig["mcast_risks"], ["security", "scalability"],
        ["multicast_intelligence.querier.gap_vlans", "multicast_intelligence.risks"],
        priority="High", driver="L2 multicast hygiene: snooping + a querier per active VLAN, and an edge boundary.")


_DETECTORS = [_d_fhrp, _d_spof, _d_eol, _d_qos, _d_mgmt, _d_harden, _d_coverage,
              _d_flat_l2, _d_stp_lag, _d_stp_det, _d_igp, _d_mcast]


# ----------------------------------------------------------------------------- requirement-gated decisions
_NEEDS = [
    ("availability-right-sized-per-tier", ["availability", "cost"], ["availability_tier"],
     "Redundancy posture is observable, but right-sizing it (which tiers warrant which availability) "
     "needs a per-class availability/SLA target."),
    ("scenario-match-redundancy-to-convergence-requirement", ["convergence", "availability"],
     ["convergence_budget_ms", "critical_apps"],
     "Convergence posture is observable, but whether it is over- or under-built needs the per-application "
     "convergence budget (e.g. voice/video tolerance)."),
    ("security-defense-in-depth-segmentation", ["security", "modularity"], ["data_classification"],
     "A flat L2 / single-VRF posture is observable, but the target zoning needs a data-security "
     "classification (which assets must be isolated from which)."),
    ("qos-class-model-from-app-profile", ["manageability"], ["application_matrix", "critical_apps"],
     "Absent/ad-hoc QoS marking is observable, but the target class model needs the application traffic "
     "matrix (which apps, which delay/loss budgets)."),
]


def _needs_requirement(snap, sig, req):
    out = []
    for pid, axes, needed, summary in _NEEDS:
        out.append(_decision(pid, summary, 0, axes,
                             ["requirements_register"], status="needs-requirement",
                             confidence="Requirement-needed",
                             driver="Design top-down from the WHY: gather the requirement, then decide.",
                             requirements_needed=needed))
    if not req:
        out.append(_decision(
            "scenario-ask-missing-requirements-no-assumptions",
            "No requirements register supplied. Decisions that depend on SLA / application / growth / "
            "constraints are surfaced as questions, not assumed -- supply the register to right-size "
            "the blueprint.",
            0, [], ["requirements_register"],
            status="needs-requirement", confidence="Requirement-needed",
            driver="A design is good only if it meets requirements; gather them before deciding.",
            requirements_needed=["availability_tier", "critical_apps", "convergence_budget_ms",
                                 "growth_horizon", "constraints"]))
    return out


# ----------------------------------------------------------------------------- trade-off scorecard
def _axis_entry(key, score, posture, evidence):
    a = design_kb.axis(key) or {}
    return {"axis": key, "label": a.get("label", key), "score": score,
            "posture": posture, "evidence": evidence}


def _clamp(v):
    return max(0, min(4, v))


def _scorecard(snap, sig):
    out = []
    # availability
    av = 4 - (2 if sig["no_fhrp"] else 0) - (1 if sig["bridges"] else 0) - (1 if sig["nobackup_high"] else 0)
    out.append(_axis_entry("availability", _clamp(av),
               "Weak" if av <= 1 else ("Moderate" if av <= 2 else "Strong"),
               f"{sig['no_fhrp']} no-FHRP VLAN(s); {sig['bridges']} cut-edge link(s); "
               f"{sig['nobackup_high']} node(s) with no backup path."))
    # convergence
    cv = 4 - (1 if sig["no_fhrp"] else 0) - (1 if sig["stp_blocked"] else 0) - (1 if sig["eol"] else 0)
    out.append(_axis_entry("convergence", _clamp(cv), "Weak" if cv <= 1 else "Moderate",
               "First-hop, STP and platform age all bound failover time."))
    # scalability
    sc = 4 - (2 if sig["vlans"] >= 64 else (1 if sig["vlans"] >= _LARGE_L2_VLANS else 0)) - (1 if sig["single_vrf"] else 0)
    out.append(_axis_entry("scalability", _clamp(sc), "Weak" if sc <= 1 else "Moderate",
               f"{sig['vlans']} VLAN(s); {'single' if sig['single_vrf'] else 'multiple'} VRF."))
    # modularity
    md = 4 - (1 if sig["single_vrf"] else 0) - (1 if sig["vlans"] >= _LARGE_L2_VLANS else 0)
    out.append(_axis_entry("modularity", _clamp(md), "Moderate" if md >= 2 else "Weak",
               "Fault-domain boundaries are bounded mostly by spanning tree, not by L3 modularity."))
    # security
    secpen = (2 if sig["mgmt_devices"] else 0) + (1 if sig["harden_devices"] else 0)
    se = _clamp(4 - secpen)
    out.append(_axis_entry("security", se, "Weak" if se <= 1 else "Moderate",
               f"{sig['mgmt_devices']} mgmt-plane and {sig['harden_devices']} device-hardening deviation(s)."))
    # simplicity
    si = 3 - (1 if len(sig["igps"]) >= 2 else 0) - (1 if sig["vtp_server"] else 0)
    out.append(_axis_entry("simplicity", _clamp(si), "Moderate",
               ("mixed IGP; " if len(sig["igps"]) >= 2 else "") + ("VTP active" if sig["vtp_server"] else "")
               or "no obvious accidental complexity observed."))
    # optimal_routing (limited evidence)
    out.append(_axis_entry("optimal_routing", 2, "Limited evidence",
               "Path optimality needs end-to-end routing/forwarding evidence not fully collected."))
    # load_balancing
    lb = _clamp(4 - (2 if sig["stp_blocked"] else 0))
    out.append(_axis_entry("load_balancing", lb, "Weak" if lb <= 2 else "Strong",
               f"{sig['stp_blocked']} device(s) with idle STP-blocked redundant links."))
    # manageability
    mg = _clamp(4 - (1 if sig["mgmt_devices"] else 0) - (1 if sig["vtp_server"] else 0)
                - (1 if sig["not_collected"] else 0))
    out.append(_axis_entry("manageability", mg, "Weak" if mg <= 1 else "Moderate",
               "AAA/time/logging, VTP exposure and collection coverage drive operability."))
    # cost
    co = _clamp(4 - (2 if sig["eol"] else 0) - (1 if sig["near"] else 0))
    out.append(_axis_entry("cost", co, "Pressure" if co <= 2 else "Comfortable",
               f"{sig['eol']} past-LDoS + {sig['near']} near-LDoS asset(s) imply refresh CapEx."))
    return out


# ----------------------------------------------------------------------------- requirements overlay
def _req_axis_weights(req):
    w = {a["key"]: 1.0 for a in design_kb.TRADEOFF_AXES}
    tier = str(req.get("availability_tier", "")).lower()
    if tier == "gold":
        w["availability"], w["convergence"] = 2.0, 1.6
    elif tier == "silver":
        w["availability"], w["convergence"] = 1.4, 1.2
    apps = [str(a).lower() for a in _as_list(req.get("critical_apps"))]
    if any(a in ("voice", "video", "real-time", "realtime", "telephony", "media") for a in apps):
        w["convergence"] = max(w["convergence"], 1.6)
        w["manageability"] = max(w["manageability"], 1.4)
        w["availability"] = max(w["availability"], 1.3)
    if req.get("convergence_budget_ms"):
        w["convergence"] = max(w["convergence"], 1.5)
    if req.get("growth_horizon"):
        w["scalability"], w["modularity"] = 1.6, max(w["modularity"], 1.4)
    cons = [str(c).lower() for c in _as_list(req.get("constraints"))]
    if any(("budget" in c) or ("cost" in c) for c in cons):
        w["cost"], w["simplicity"] = 1.6, max(w["simplicity"], 1.4)
    if any(("secur" in c) or ("compli" in c) or ("pci" in c) or ("regul" in c) for c in cons):
        w["security"] = max(w["security"], 1.7)
    if req.get("data_classification"):
        w["security"] = max(w["security"], 1.6)
    return w


def _req_satisfies(decision, req):
    for key in decision.get("requirements_needed", []):
        if req.get(key):
            return True
    return False


def _apply_requirements(decisions, scorecard, req):
    w = _req_axis_weights(req)
    for d in decisions:
        base = _SCORE.get(d.get("priority"), 2)
        mult = max([w.get(a, 1.0) for a in d.get("axes", [])] or [1.0])
        d["effective_priority"] = round(base * mult, 2)
        if d.get("status") == "needs-requirement" and _req_satisfies(d, req):
            d["status"] = "recommended"
            d["confidence"] = "Requirement-driven"
    for s in scorecard:
        s["target_weight"] = w.get(s.get("axis"), 1.0)


# ----------------------------------------------------------------------------- requirements model + coverage
def _requirements_model(decisions, req):
    req = req or {}
    fields = [
        {"key": "availability_tier", "label": "Target availability tier",
         "options": ["gold", "silver", "bronze"], "value": req.get("availability_tier")},
        {"key": "critical_apps", "label": "Business-critical applications",
         "example": ["voice", "video", "ERP"], "value": req.get("critical_apps")},
        {"key": "convergence_budget_ms", "label": "Max tolerable convergence (ms)",
         "value": req.get("convergence_budget_ms")},
        {"key": "growth_horizon", "label": "Growth horizon / forecast", "value": req.get("growth_horizon")},
        {"key": "constraints", "label": "Fixed constraints (budget / installed-base / regulatory)",
         "value": req.get("constraints")},
        {"key": "data_classification", "label": "Data-security classification / zones",
         "value": req.get("data_classification")},
    ]
    open_q = [{"id": d["id"], "title": d["title"], "needs": d.get("requirements_needed", [])}
              for d in decisions if d.get("status") == "needs-requirement"]
    return {
        "fields": fields,
        "open_questions": open_q,
        "provided": bool(req),
        "note": "Design top-down from the WHY: supply this register and the blueprint right-sizes each "
                "decision and scores the trade-off axes against it; absent, the engine surfaces the "
                "questions rather than assuming an answer.",
    }


def _coverage(snap):
    cc = _as_dict(_as_dict(snap.get("collection_completeness")).get("summary"))
    return {
        "inventory": _as_int(cc.get("inventory")),
        "collected": _as_int(cc.get("complete")),
        "not_collected": _as_int(cc.get("not_collected")),
        "caveat": "Design decisions are grounded only in collected evidence; not-collected devices "
                  "(including any uncollected core) are an explicit unknown -- their role and redundancy "
                  "are not assumed.",
    }


def _headline(decisions):
    if not decisions:
        return "No design decisions surfaced from the available evidence."
    crit = [d for d in decisions if d["priority"] == "Critical" and d["status"] == "recommended"]
    n = len(crit)
    lead = decisions[0]["title"]
    if n:
        return f"{n} critical target-state design decision(s); leading: {lead}."
    return f"Leading target-state design decision: {lead}."


# ----------------------------------------------------------------------------- public entrypoint
def compute_design_blueprint(snap, requirements=None):
    """Canonical, CCDE-grounded target-state design blueprint for a snapshot.

    Reads only already-computed evidence; every decision is evidence-gated and cites a `design_kb`
    principle. `requirements` (optional dict: availability_tier, critical_apps, convergence_budget_ms,
    growth_horizon, constraints, data_classification) right-sizes the decisions when supplied.
    """
    snap = _as_dict(snap)
    req = _as_dict(requirements) if requirements else None
    sig = _signals(snap)

    decisions = []
    for det in _DETECTORS:
        d = det(snap, sig)
        if d:
            decisions.append(d)
    decisions += _needs_requirement(snap, sig, req)

    # de-duplicate by id, keeping the highest-priority instance
    uniq = {}
    for d in decisions:
        ex = uniq.get(d["id"])
        if ex is None or PRANK.get(d["priority"], 9) < PRANK.get(ex["priority"], 9):
            uniq[d["id"]] = d
    decisions = list(uniq.values())

    scorecard = _scorecard(snap, sig)

    if req:
        _apply_requirements(decisions, scorecard, req)
        decisions.sort(key=lambda d: (-d.get("effective_priority", 0.0),
                                       PRANK.get(d["priority"], 9), d["id"]))
    else:
        decisions.sort(key=lambda d: (PRANK.get(d["priority"], 9),
                                      -_as_int(_as_dict(d.get("evidence")).get("count")), d["id"]))

    by_domain = {}
    for d in decisions:
        by_domain[d["domain"]] = by_domain.get(d["domain"], 0) + 1
    summary = {
        "n_decisions": len(decisions),
        "n_recommended": sum(1 for d in decisions if d["status"] == "recommended"),
        "n_needs_requirement": sum(1 for d in decisions if d["status"] == "needs-requirement"),
        "n_critical": sum(1 for d in decisions if d["priority"] == "Critical"),
        "by_domain": by_domain,
        "requirements_provided": bool(req),
        "headline": _headline(decisions),
    }
    return {
        "decisions": decisions,
        "tradeoff_scorecard": scorecard,
        "requirements_model": _requirements_model(decisions, req),
        "methodology": (design_kb.METHODOLOGY or "")[:1400],
        "axes": design_kb.TRADEOFF_AXES,
        "summary": summary,
        "coverage": _coverage(snap),
    }
