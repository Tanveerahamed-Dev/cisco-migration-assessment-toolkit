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
_HARDEN_FAIL_IDS = {"risky-services", "no-banner"}
# Time-sync + centralised-logging operational baseline: NTP-disciplined, correlated timestamps for
# troubleshooting and forensic reconstruction across devices -- a distinct design concern from
# attack-surface hardening (Cisco IOS/NX-OS/IOS-XE hardening guides; RFC 5905 NTP authentication).
_TIMESYNC_FAIL_IDS = {"no-ntp", "no-logging"}

_LARGE_L2_VLANS = 12  # a flat estate carrying this many VLANs in one (global) VRF is an oversized fault domain
_L2_SPAN_SWITCHES = 8  # a single user VLAN touching this many switches is an oversized L2 failure (bridging) domain
_WAVE_CAP = 40  # max switches per candidate migration wave (a maintenance-window-sized batch)
_PORT_UTIL_HOT = 85.0  # PERCENT: a switch at/above this port- (or PoE-) utilisation has < 15% headroom (capacity[].port_util/poe_util are percentages)


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


def _as_float(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _svi_network(svi):
    """The network (CIDR str) of an SVI address, or None. Handles 'ip/prefix' and 'ip mask' forms (the two
    shapes l3_forwarding.svi_ip is collected in); a bare IP with no mask is unknown -> None. Used to recover a
    VLAN's subnet when l3_forwarding.primary_subnet is empty (108/231 AJ rows) so VLAN-ID reuse across sites is
    not silently read as one broadcast domain."""
    import ipaddress
    s = str(svi or "").strip()
    if not s:
        return None
    try:
        if "/" in s:
            return str(ipaddress.ip_interface(s).network)
        parts = s.split()
        if len(parts) == 2:
            return str(ipaddress.ip_interface(f"{parts[0]}/{parts[1]}").network)
    except ValueError:
        return None
    return None


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
    bh = []
    for x in bridges:
        for h in (x.get("a_host"), x.get("b_host")):
            if h and h not in bh:
                bh.append(h)
    sig["bridge_hosts"] = bh

    fi = _as_list(snap.get("failure_impact"))
    sig["nobackup_high"] = sum(1 for x in fi if x.get("severity") == "High" and not _as_int(x.get("backup")))

    life = _as_list(_as_dict(snap.get("lifecycle_risk")).get("per_device"))
    # Past-LDoS = unsupported (no TAC / no fixes) -> "eol"/replace. Past-EoS (past end-of-SALE but STILL
    # supported until LDoS -- analyze emits both bands) is DISTINCT and refresh-class; matching the band
    # exactly (not startswith "past") keeps supported gear from being mislabelled unsupported/past-LDoS.
    sig["eol"] = sum(1 for d in life if str(d.get("band", "")).strip().lower() == "past-ldos")
    sig["near"] = sum(1 for d in life if "near" in str(d.get("band", "")).lower())
    sig["eol_devices"] = [d.get("host") for d in life
                          if str(d.get("band", "")).strip().lower() == "past-ldos"][:12]

    qos = _as_list(_as_dict(snap.get("qos_audit")).get("per_device"))
    sig["qos_assessable"] = sum(1 for d in qos if d.get("assessable"))
    sig["qos_none"] = sum(1 for d in qos if d.get("assessable") and d.get("mode") == "none")
    sig["qos_none_hosts"] = [d.get("host") for d in qos if d.get("assessable") and d.get("mode") == "none"]
    # voice / real-time edge ports present but no QoS policy => no bounded low-delay (priority) queue
    sig["voice_noqos_hosts"] = [d.get("host") for d in qos if d.get("assessable")
                                and _as_int(d.get("n_voice_if")) > 0 and d.get("mode") == "none"]
    sig["voice_noqos"] = len(sig["voice_noqos_hosts"])

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
    sig["harden_hosts"] = sorted(harden)[:12]
    sig["mgmt_fail_ids"] = sorted(fid for fid in _MGMT_FAIL_IDS if fail_hosts.get(fid))
    sig["timesync_hosts"] = sorted({h for fid in _TIMESYNC_FAIL_IDS for h in fail_hosts.get(fid, set())})
    sig["timesync_devices"] = len(sig["timesync_hosts"])

    sig["vlans"] = _vlan_count(snap)
    seg = _as_dict(snap.get("segmentation"))
    vrfs = _as_list(seg.get("vrfs"))
    sig["single_vrf"] = len(vrfs) <= 1
    # on-air-critical / high-value tiers the segmentation axis already classified as L3-exposed
    seg_sum = _as_dict(seg.get("summary"))
    sig["oncrit_exposed"] = _as_int(seg_sum.get("n_oncrit_exposed"))
    sig["gw_acl_cov"] = float(seg_sum.get("gateway_acl_coverage") or 0.0)
    sig["n_gateways"] = _as_int(seg_sum.get("n_gateways"))
    sig["oncrit_domains"] = [d.get("domain") for d in _as_list(seg.get("domains"))
                             if d.get("tier") == "On-air critical" and not d.get("isolated")
                             and _as_int(d.get("gateways")) > 0][:6]

    stp = [x for x in _as_list(snap.get("protocol_health")) if x.get("protocol") == "STP"]
    sig["stp_blocked"] = sum(1 for x in stp if _stp_blocked(x))
    sig["stp_legacy"] = sum(1 for x in stp if _stp_legacy(x))
    # Rapid-PVST switches ONLY (mode 'rapid-pvst'): the per-VLAN-STP instance-scale population, scoped to
    # EXCLUDE the legacy (non-rapid) PVST switches already owned by _d_stp_det (no double-count).
    sig["stp_pvst"] = sum(1 for x in stp if "rapid-pvst" in str(x.get("summary", "")).lower())
    sig["stp_pvst_hosts"] = [x.get("switch") for x in stp
                             if "rapid-pvst" in str(x.get("summary", "")).lower()][:12]
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

    mg = _as_list(snap.get("move_groups"))
    sig["move_groups"] = len(mg)
    sig["move_switches"] = sum(len(_as_list(g.get("switches"))) for g in mg if isinstance(g, dict))

    # per-VLAN L2 failure-domain breadth (canonical: move_groups[].spanning_vlans = [vid, name, nswitches])
    wide = {}
    vlan1_spans = False
    for g in mg:
        if not isinstance(g, dict):
            continue
        vlan1_spans = vlan1_spans or bool(g.get("vlan1_spans"))
        for entry in _as_list(g.get("spanning_vlans")):
            try:
                vid, name, n = entry[0], entry[1], _as_int(entry[2])
            except (IndexError, TypeError, KeyError):
                continue
            if isinstance(vid, int) and vid > 1 and n >= _L2_SPAN_SWITCHES:
                if vid not in wide or n > wide[vid][1]:
                    wide[vid] = (name, n)
    sig["l2_wide_vlans"] = len(wide)
    sig["l2_vlan1_spans"] = vlan1_spans
    sig["l2_widest"] = sorted(([vid, nm, n] for vid, (nm, n) in wide.items()), key=lambda t: -t[2])[:5]

    # --- net-new evidence-grounded design signals (read already-computed axes the design brain didn't use) ---
    # addressing collisions: observed duplicate IPs / overlapping subnets -> a merge cannot proceed over them
    ac = _as_dict(snap.get("addressing_conflicts"))
    sig["dup_ip"] = len(_as_list(ac.get("dup_ip")))
    sig["dup_subnet"] = len(_as_list(ac.get("dup_subnet")))

    # physical-layer faults: CRC/input-errors, half-duplex (mismatch), err-disable -> remediate before cutover
    phy = [p for p in _as_list(snap.get("physical_health")) if isinstance(p, dict)]

    def _phy_dirty(p):
        return (_as_int(p.get("crc_errors")) > 0 or _as_int(p.get("input_errors")) > 0
                or str(p.get("duplex", "")).strip().lower() == "half"
                or ("err" in str(p.get("status", "")).lower() and "dis" in str(p.get("status", "")).lower()))
    sig["phy_crc"] = sum(1 for p in phy if _as_int(p.get("crc_errors")) > 0)
    sig["phy_inerr"] = sum(1 for p in phy if _as_int(p.get("input_errors")) > 0)
    sig["phy_halfduplex"] = sum(1 for p in phy if str(p.get("duplex", "")).strip().lower() == "half")
    sig["phy_errdisable"] = sum(1 for p in phy if "err" in str(p.get("status", "")).lower()
                                and "dis" in str(p.get("status", "")).lower())
    sig["phy_dirty"] = sum(1 for p in phy if _phy_dirty(p))
    sig["phy_dirty_hosts"] = sorted({p.get("switch") for p in phy if _phy_dirty(p) and p.get("switch")})[:12]

    # capacity headroom: switches at/above the high port- (or PoE-) utilisation threshold
    cap = [c for c in _as_list(snap.get("capacity")) if isinstance(c, dict)]
    sig["cap_total"] = len(cap)
    sig["cap_hot"] = sum(1 for c in cap if _as_float(c.get("port_util")) >= _PORT_UTIL_HOT)
    sig["cap_hot_hosts"] = [c.get("hostname") for c in cap
                            if _as_float(c.get("port_util")) >= _PORT_UTIL_HOT][:12]
    sig["cap_poe_hot"] = sum(1 for c in cap if _as_float(c.get("poe_util")) >= _PORT_UTIL_HOT)

    # dual-homing: an endpoint MAC on two switches whose second path a switch-by-switch move would break.
    # (endpoint_dependencies.clusters is a vendor/class affinity analytic, NOT an HA cluster -> not used here.)
    ed = _as_dict(snap.get("endpoint_dependencies"))
    sig["dual_homed"] = len(_as_list(ed.get("dual_homed")))
    sig["shared_ip"] = len(_as_list(ed.get("shared_ip")))

    # native-VLAN-1 on inter-switch trunks (double-tag / VLAN-hopping) -- same field the workbook/archreview key off
    n1_trunks, n1_sw = 0, set()
    for host, ports in _as_dict(snap.get("interfaces")).items():
        hit = False
        for _pn, pd in _as_dict(ports).items():
            if isinstance(pd, dict) and ("trunk" in str(pd.get("switchport_mode", "")).lower()
                    and str(pd.get("trunk_native_vlan", "")).strip() == "1"):
                n1_trunks += 1
                hit = True
        if hit:
            n1_sw.add(host)
    sig["native1_trunks"] = n1_trunks
    sig["native1_switches"] = len(n1_sw)
    sig["native1_hosts"] = sorted(n1_sw)[:12]

    # high-severity false-health (operational_drift) that MASKS the true state -> resolve before baselining.
    # HIGH only: the LOW rows (native-VLAN-1, long uptime) are owned by other detectors / informational.
    od_high = [d for d in _as_list(snap.get("operational_drift"))
               if isinstance(d, dict) and str(d.get("severity", "")).strip().lower() == "high"]
    sig["false_health_high"] = len(od_high)
    sig["false_health_titles"] = [str(d.get("title", "")) for d in od_high if d.get("title")][:6]
    fh_devs = []
    for d in od_high:
        for h in _as_list(d.get("devices")):
            if h and h not in fh_devs:
                fh_devs.append(h)
    sig["false_health_devices"] = fh_devs[:12]

    # degraded EtherChannel/port-channel members (down/suspended/standalone) -> restore before cutover.
    # Reads the engine's OWN High/Critical severity rating (SSOT), not re-derived.
    pi_bad = [r for r in _as_list(snap.get("protocol_intelligence"))
              if isinstance(r, dict) and str(r.get("protocol", "")) == "EtherChannel"
              and str(r.get("severity", "")) in ("High", "Critical")]
    sig["bundle_degraded"] = len(pi_bad)
    bd_sw = {r.get("switch") for r in pi_bad if r.get("switch")}
    sig["bundle_degraded_nsw"] = len(bd_sw)
    sig["bundle_degraded_hosts"] = sorted(bd_sw)[:12]

    # ---- 2026-06 mega-wave: collected-but-unused evidence -> firing design decisions (refutation-gated) ----
    l3f = _as_list(snap.get("l3_forwarding"))

    # #1 one-VLAN-one-subnet integrity: a single VLAN bound to >1 distinct subnet across >1 gateway (the same
    #    broadcast domain carrying conflicting L3 identities) -> any L2 merge collides. subnet_intelligence is the
    #    richest source; l3_forwarding.primary_subnet corroborates (containment/mask-mismatch arm).
    v2sub, v2gw = {}, {}
    for dev in _as_list(_as_dict(snap.get("subnet_intelligence")).get("per_device")):
        for ss in _as_list(_as_dict(dev).get("served_subnets")):
            ss = _as_dict(ss)
            vid, sub, gw = ss.get("vlan"), ss.get("subnet"), ss.get("gateway")
            if vid is not None and sub:
                v2sub.setdefault(str(vid), set()).add(sub)
                if gw:
                    v2gw.setdefault(str(vid), set()).add(gw)
    # l3_forwarding corroborates AND extends: VLAN-ID reuse across sites is frequently visible ONLY here, not in
    # subnet_intelligence (e.g. AJ VLAN 64 = 10.200.64.0/24 at one site + 10.203.64.0/24 at another, the latter
    # recoverable only from svi_ip since primary_subnet is empty). Subnet = primary_subnet, else derived from the
    # SVI ip+mask; gateway = the switch. This is also the single-broadcast-domain authority for #9 below.
    for r in _as_list(snap.get("l3_forwarding")):
        r = _as_dict(r)
        vid = r.get("vlan")
        if vid is None:
            continue
        sub = str(r.get("primary_subnet") or "").strip() or _svi_network(r.get("svi_ip"))
        if sub:
            v2sub.setdefault(str(vid), set()).add(sub)
            if r.get("switch"):
                v2gw.setdefault(str(vid), set()).add(r.get("switch"))
    vsi = [v for v in v2sub if len(v2sub[v]) >= 2 and len(v2gw.get(v, set())) >= 2]
    sig["vlan_multi_subnet"] = len(vsi)
    sig["vlan_multi_subnet_vids"] = sorted(vsi, key=lambda v: (len(v), v))[:8]
    sig["vlan_multi_subnet_hosts"] = sorted({g for v in vsi for g in v2gw.get(v, set())})[:12]

    # #2 STP root determinism: a VLAN whose root won at the DEFAULT priority (32768 + vid) -> accidental root, not
    #    engineered (won on the MAC tiebreak). Same stp_roots evidence analyze.stp_root_findings feeds the punch-list.
    acc, acc_hosts = 0, set()
    for host, vmap in _as_dict(snap.get("stp_roots")).items():
        for vid, row in _as_dict(vmap).items():
            row = _as_dict(row)
            if not row.get("is_root"):
                continue
            try:
                if int(row.get("root_priority")) == 32768 + int(vid):
                    acc += 1
                    acc_hosts.add(host)
            except (TypeError, ValueError):
                continue
    sig["stp_accidental_roots"] = acc
    sig["stp_accidental_nsw"] = len(acc_hosts)
    sig["stp_accidental_hosts"] = sorted(acc_hosts)[:12]

    # #3 reserved-range VLAN carrying a production SVI: Nexus reserves 3968-4095 for internal use -> the target
    #    refuses the SVI and the L3 link breaks silently at cutover unless renumbered into the user range.
    res = [r for r in l3f if isinstance(r, dict) and isinstance(r.get("vlan"), int)
           and 3968 <= r["vlan"] <= 4095 and str(r.get("svi_ip") or "").strip()]
    sig["reserved_vlan_svis"] = len(res)
    sig["reserved_vlan_vids"] = sorted({r["vlan"] for r in res})
    sig["reserved_vlan_hosts"] = sorted({r.get("switch") or r.get("host") for r in res
                                         if r.get("switch") or r.get("host")})[:12]

    # #4 static (mode on) multi-member EtherChannels: no LACP negotiation -> a miscabled/one-way member is admitted
    #    and blackholes its hash share. Exclude FEX-HIF (Eth>=100/x/y) and the Po self-listing artifact.
    on_bundles = {}
    for host, ports in _as_dict(snap.get("interfaces")).items():
        for pn, pdt in _as_dict(ports).items():
            pdt = _as_dict(pdt)
            if str(pdt.get("port_channel_protocol") or "").upper() != "ON":
                continue
            pc = pdt.get("port_channel")
            if not pc or str(pn).lower().startswith("po"):
                continue
            m = re.match(r"(?:eth|ethernet)\s*(\d+)/\d+/\d+", str(pn).lower())
            if m and int(m.group(1)) >= 100:
                continue
            on_bundles[(host, str(pc))] = on_bundles.get((host, str(pc)), 0) + 1
    static_b = [k for k, n in on_bundles.items() if n >= 2]
    sig["static_ec_bundles"] = len(static_b)
    sig["static_ec_nsw"] = len({h for h, _ in static_b})
    sig["static_ec_hosts"] = sorted({h for h, _ in static_b})[:12]

    # #5 lost PSU redundancy: a multi-PSU chassis reporting a FAILED supply is now single-corded (N+1 lost).
    psf = []
    for host, dv in _as_dict(snap.get("devices")).items():
        dv = _as_dict(dv)
        try:
            n = int(dv.get("num_power_supplies"))
        except (TypeError, ValueError):
            n = 0
        if n > 1 and "fail" in str(dv.get("ps_status") or "").lower():
            psf.append(host)
    sig["psu_fail"] = len(psf)
    sig["psu_fail_hosts"] = sorted(psf)[:12]

    # #6 BPDU-Guard edge-protection gap (the unfired arm of dc-stp-determinism-edge-protection): endpoint-bearing
    #    access ports with BPDU-Guard NOT enabled. Scoped to the real access edge (non-FEX, access mode, has an
    #    end-host MAC, no CDP neighbour/uplink, not a port-channel member) to avoid the FEX-HIF inheritance artifact.
    bpdu_sw = {}
    for host, ports in _as_dict(snap.get("interfaces")).items():
        for pn, pdt in _as_dict(ports).items():
            pdt = _as_dict(pdt)
            if str(pdt.get("switchport_mode") or "").lower() != "access":
                continue
            if not pdt.get("end_host_mac") or pdt.get("cdp_neighbor") or pdt.get("port_channel"):
                continue
            m = re.match(r"(?:eth|ethernet)\s*(\d+)/\d+/\d+", str(pn).lower())
            if m and int(m.group(1)) >= 100:
                continue
            if str(pdt.get("stp_bpduguard") or "").strip().lower() not in ("enable", "enabled", "true", "on"):
                bpdu_sw[host] = bpdu_sw.get(host, 0) + 1
    sig["bpdu_unguarded"] = sum(bpdu_sw.values())
    sig["bpdu_unguarded_nsw"] = len(bpdu_sw)
    sig["bpdu_unguarded_hosts"] = sorted(bpdu_sw)[:12]

    # #8 gateway-move-last: a subnet whose endpoints straddle >=2 switches constrains its SVI move order.
    # #9 oversized L2 subnet: a SINGLE-SUBNET VLAN (one broadcast domain) with >254 endpoints overflows a /24
    #    -- subnet-gated below so VLAN-ID reuse across sites is never summed into a false oversize.
    ei_vlan_hosts, ei_vlan_n = {}, {}
    for e in _as_list(snap.get("endpoint_identity")):
        e = _as_dict(e)
        v, h = e.get("vlan"), e.get("host")
        if v in (None, 1, "1"):
            continue
        ei_vlan_n[str(v)] = ei_vlan_n.get(str(v), 0) + 1
        if h:
            ei_vlan_hosts.setdefault(str(v), set()).add(h)
    gwc, gwc_vlans = 0, set()
    for r in l3f:
        r = _as_dict(r)
        v = r.get("vlan")
        if v is None or not str(r.get("svi_ip") or "").strip():
            continue
        if len(ei_vlan_hosts.get(str(v), set())) >= 2:
            gwc += 1
            gwc_vlans.add(str(v))
    sig["gw_move_last"] = gwc
    sig["gw_move_last_vlans"] = len(gwc_vlans)
    # #9 single-broadcast-domain gate: a VLAN's endpoints overflow a /24 ONLY if they are ONE broadcast domain.
    # VLAN IDs are locally significant and reused across sites, so summing endpoints by VLAN-ID alone conflates
    # independent /24s (the project's #1 false-attribution class). Reuse v2sub (the comprehensive vlan->subnets
    # map built above from subnet_intelligence + l3_forwarding incl. svi-derived): EXACTLY 1 subnet = one domain
    # (can overflow); >1 = VLAN-ID reuse -> _d_vlan_subnet_integrity's renumber territory, NOT a resize; 0 =
    # subnet not collected (gateway on the uncollected core) -> cannot assert one domain, coverage-honestly exclude.
    over = sorted(((v, n) for v, n in ei_vlan_n.items()
                   if n > 254 and len(v2sub.get(v, set())) == 1), key=lambda t: -t[1])
    sig["oversized_l2"] = len(over)
    sig["oversized_l2_top"] = [[v, n] for v, n in over[:5]]

    # ---- #7 device attribution: recover the host lists the device-less detectors already inspect, so every surface
    #    can spotlight them (was: empty evidence.devices dimmed the explorer canvas while claiming 'highlighted').
    ovh = set()
    _ac = _as_dict(snap.get("addressing_conflicts"))
    for grp in _as_list(_ac.get("dup_ip")) + _as_list(_ac.get("dup_subnet")):
        for w in _as_list(_as_dict(grp).get("where")):
            if isinstance(w, (list, tuple)) and w and w[0]:
                ovh.add(w[0])
    sig["addr_overlap_hosts"] = sorted(ovh)[:12]
    dhh = set()
    for rr in _as_list(_as_dict(snap.get("endpoint_dependencies")).get("dual_homed")):
        for sw in _as_list(_as_dict(rr).get("switches")):
            if sw:
                dhh.add(sw)
    sig["dual_homed_hosts"] = sorted(dhh)[:12]
    sig["stp_blocked_hosts"] = [x.get("switch") for x in _as_list(snap.get("protocol_health"))
                                if x.get("protocol") == "STP" and _stp_blocked(x) and x.get("switch")][:12]
    wh = set()
    for g in _as_list(snap.get("move_groups")):
        g = _as_dict(g)
        wide_hit = bool(g.get("vlan1_spans"))
        for entry in _as_list(g.get("spanning_vlans")):
            try:
                if isinstance(entry[0], int) and entry[0] > 1 and _as_int(entry[2]) >= _L2_SPAN_SWITCHES:
                    wide_hit = True
            except (IndexError, TypeError, KeyError):
                continue
        if wide_hit:
            for sw in _as_list(g.get("switches")):
                if sw:
                    wh.add(sw)
    sig["l2_wide_hosts"] = sorted(wh)[:12]

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
        priority="High", driver="Reduce the control-plane attack surface to a CIS-style baseline.",
        devices=sig["harden_hosts"])


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
        priority="High", driver="Use both uplinks: multi-chassis LAG (vPC/VSS/SVL/MLAG) instead of STP blocking.",
        devices=sig["stp_blocked_hosts"])


def _d_stp_det(snap, sig):
    # Edge protection is part of L2 determinism: fire on legacy STP, VTP server mode, OR an unguarded access edge
    # (the BPDU-Guard arm, previously unfired -- it contributed zero to any decision though the evidence existed).
    if not (sig["stp_legacy"] or sig["vtp_server"] or sig["bpdu_unguarded"]):
        return None
    bits = []
    if sig["stp_legacy"]:
        bits.append(f"{sig['stp_legacy']} device(s) run legacy (non-rapid) spanning tree")
    if sig["vtp_server"]:
        bits.append("VTP server mode is active (a fleet-wide VLAN-change blast radius)")
    if sig["bpdu_unguarded"]:
        bits.append(f"{sig['bpdu_unguarded']} endpoint-bearing access port(s) across "
                    f"{sig['bpdu_unguarded_nsw']} switch(es) have no BPDU-Guard (an unprotected L2 edge)")
    return _decision(
        "dc-stp-determinism-edge-protection",
        "; ".join(bits) + " -- L2 control is not deterministic and the edge is not protected.",
        sig["stp_legacy"] + (1 if sig["vtp_server"] else 0) + sig["bpdu_unguarded_nsw"],
        ["availability", "manageability", "convergence"],
        ["protocol_health[STP].summary", "protocol_health[VTP].summary", "interfaces[host][port].stp_bpduguard"],
        priority="High",
        driver="Deterministic L2: rapid-PVST/MST, aligned roots, edge protection (BPDU-Guard), VTP off/transparent.",
        devices=sig["bpdu_unguarded_hosts"])


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


def _d_timesync(snap, sig):
    if sig["timesync_devices"] <= 0:
        return None
    return _decision(
        "mgmt-time-sync-logging-baseline",
        f"{sig['timesync_devices']} device(s) lack authenticated time sync and/or centralised logging "
        f"(no-ntp/no-logging) -- without NTP-disciplined, correlated timestamps the fleet cannot be "
        f"reliably troubleshot or forensically reconstructed across devices.",
        sig["timesync_devices"], ["manageability", "security"],
        ["security[host].findings[id in {no-ntp,no-logging}]"],
        priority="High", driver="Operational baseline: NTP-authenticated time + centralised syslog for correlation/forensics.",
        devices=sig["timesync_hosts"])


def _d_voice_qos(snap, sig):
    if sig["voice_noqos"] <= 0:
        return None
    return _decision(
        "qos-voice-priority-bounded",
        f"{sig['voice_noqos']} device(s) carry voice/real-time edge ports but no QoS policy -- real-time "
        f"traffic gets no low-delay priority queue, and (RFC 4594) an unbounded priority class can starve "
        f"other traffic; it needs a bounded LLQ with a policer/admission.",
        sig["voice_noqos"], ["availability", "convergence"],
        ["qos_audit.per_device[].n_voice_if", "qos_audit.per_device[].mode"],
        priority="High", driver="Real-time performance: voice needs a bounded priority (LLQ) queue, policed against starvation.",
        devices=sig["voice_noqos_hosts"])


def _d_phased(snap, sig):
    if sig["move_groups"] <= 0:
        return None
    return _decision(
        "scenario-build-before-break-phased-cutover",
        f"{sig['move_groups']} migration move-group(s) span {sig['move_switches']} switch(es) -- the "
        f"cutover must be phased build-before-break (stand the target up in parallel, validate per wave, "
        f"then cut over and decommission), never a single big-bang change, to preserve rollback.",
        sig["move_groups"], ["availability", "manageability"],
        ["move_groups[].switches"],
        priority="Medium", confidence="Planning",
        driver="Migration safety: a parallel target + per-wave validation + rollback beats a big-bang cutover.")


def _d_l2_faildomain(snap, sig):
    if sig["l2_wide_vlans"] <= 0 and not sig["l2_vlan1_spans"]:
        return None
    lead = ""
    if sig["l2_widest"]:
        vid, nm, n = sig["l2_widest"][0]
        lead = f" widest: VLAN {vid}{(' ' + nm) if nm else ''} across {n} switches;"
    v1 = " VLAN 1 (the default) spans the fabric;" if sig["l2_vlan1_spans"] else ""
    return _decision(
        "dc-bound-layer2-failure-domain",
        f"{sig['l2_wide_vlans']} user VLAN(s) each span >= {_L2_SPAN_SWITCHES} switches "
        f"({lead.strip() or 'see spanning_vlans'}{v1}) -- a transparently-bridged VLAN is a single failure "
        f"domain, so a broadcast storm, STP topology change or flood on any of these reaches every switch "
        f"and endpoint in its span.",
        sig["l2_wide_vlans"], ["availability", "scalability", "convergence", "modularity"],
        ["move_groups[].spanning_vlans", "move_groups[].vlan1_spans"],
        priority="High",
        driver="Bound the L2 blast radius: a bridged VLAN is one fault domain -- confine VLAN span, route "
               "between blocks, isolate any required stretch.",
        devices=sig["l2_wide_hosts"])


def _d_stp_mst_scale(snap, sig):
    # Rapid-PVST-scoped (sig["stp_pvst"] excludes the legacy PVST owned by _d_stp_det -> no double-count).
    if sig["stp_pvst"] <= 0 or sig["vlans"] < _LARGE_L2_VLANS:
        return None
    return _decision(
        "dc-stp-mst-instance-scale",
        f"{sig['stp_pvst']} switch(es) run Rapid-PVST (per-VLAN spanning tree) across {sig['vlans']} VLANs "
        f"-- up to one STP instance per VLAN multiplies CPU, BPDU and topology-change load and the per-VLAN "
        f"root-placement chore; MST collapses them onto a few instances.",
        sig["stp_pvst"], ["scalability", "convergence", "manageability"],
        ["protocol_health[STP].summary (mode)", "executive_brief.scale.n_vlans"],
        priority="Medium",
        driver="Control-plane scale: one STP instance per VLAN does not scale -- map VLANs to a few MST instances.",
        devices=sig["stp_pvst_hosts"])


def _d_oncrit_seg(snap, sig):
    if sig["oncrit_exposed"] <= 0:
        return None
    names = ", ".join(sig["oncrit_domains"][:3]) or "named on-air-critical domain(s)"
    return _decision(
        "security-isolate-oncritical-application-tier",
        f"{sig['oncrit_exposed']} on-air-critical broadcast domain(s) ({names}) are L3-reachable (not "
        f"isolated) and gateway-ACL coverage is {sig['gw_acl_cov']:.0f}% across {sig['n_gateways']} "
        f"gateway(s) -- a compromise or misconfiguration anywhere on the flat L3 can reach the on-air media fabric.",
        sig["oncrit_exposed"], ["security", "modularity", "availability"],
        ["segmentation.summary.n_oncrit_exposed", "segmentation.gateway_acl.coverage_pct",
         "segmentation.domains[].tier"],
        priority="High",
        driver="Macro-segment the on-air-critical tiers: a dedicated VRF/zone behind enforced gateway ACLs, off the flat global L3.",
        devices=sig["oncrit_domains"])


def _d_addr_overlap(snap, sig):
    if sig["dup_ip"] <= 0 and sig["dup_subnet"] <= 0:
        return None
    return _decision(
        "addressing-resolve-overlaps-before-merge",
        f"{sig['dup_ip']} duplicate IP address(es) and {sig['dup_subnet']} overlapping subnet(s) exist in "
        f"scope -- any target that merges or collapses these L3 domains will collide (non-deterministic "
        f"forwarding, broken management reachability), so the addressing plan must renumber or NAT them first.",
        sig["dup_ip"] + sig["dup_subnet"], ["manageability", "availability", "optimal_routing"],
        ["addressing_conflicts.dup_ip", "addressing_conflicts.dup_subnet"],
        priority="Critical",
        driver="Addressing integrity: overlapping/duplicate L3 space cannot be merged -- resolve before cutover.",
        devices=sig["addr_overlap_hosts"])


def _d_phys_remediation(snap, sig):
    if sig["phy_dirty"] <= 0:
        return None
    return _decision(
        "physical-remediate-l1-faults-before-cutover",
        f"{sig['phy_dirty']} port(s) show physical-layer faults ({sig['phy_crc']} CRC, {sig['phy_inerr']} "
        f"input-error, {sig['phy_halfduplex']} half-duplex, {sig['phy_errdisable']} err-disabled) -- a dirty "
        f"L1 is migrated into the new fabric on the same cable/optic and corrupts the NRFU baseline; remediate "
        f"cabling/optics/duplex/err-disable and re-baseline counters before cutover.",
        sig["phy_dirty"], ["availability", "manageability"],
        ["physical_health[].crc_errors", "physical_health[].input_errors",
         "physical_health[].duplex", "physical_health[].status"],
        priority="High",
        driver="Clean baseline: do not carry CRC/duplex/err-disable faults across the migration, or NRFU cannot certify it.",
        devices=sig["phy_dirty_hosts"])


def _d_capacity(snap, sig):
    if sig["cap_hot"] <= 0:
        return None
    free = 100 - int(_PORT_UTIL_HOT)
    extra = f" and {sig['cap_poe_hot']} near the PoE budget" if sig["cap_poe_hot"] else ""
    return _decision(
        "capacity-size-target-with-growth-headroom",
        f"{sig['cap_hot']} of {sig['cap_total']} switch(es) run at >= {int(_PORT_UTIL_HOT)}% port "
        f"utilisation (< {free}% free ports){extra} -- size THOSE switches' replacements for current load "
        f"plus a growth headroom (and the build-before-break overhead), not 1:1, or they are born full.",
        sig["cap_hot"], ["scalability", "cost"],
        ["capacity[].port_util", "capacity[].free_ports", "capacity[].poe_util"],
        priority="Medium",
        driver="Capacity headroom: the few near-full switches must not be ported 1:1 -- design in runway.",
        devices=sig["cap_hot_hosts"])


def _d_dualhome(snap, sig):
    if sig["dual_homed"] <= 0:
        return None
    sip = f"; and reconcile {sig['shared_ip']} shared-IP set(s) (FHRP VIP vs conflict)" if sig["shared_ip"] else ""
    return _decision(
        "migration-preserve-dual-homed-endpoints",
        f"{sig['dual_homed']} dual-homed endpoint(s) (a MAC present on two switches) depend on both "
        f"attachment points staying up -- the move-group plan must move both attachment switches of each in "
        f"the same wave{sip}, or the migration silently single-homes them during the most fragile phase.",
        sig["dual_homed"], ["availability", "modularity"],
        ["endpoint_dependencies.dual_homed", "endpoint_dependencies.shared_ip"],
        priority="High",
        driver="Preserve redundancy: a migration must not transiently collapse a dual-homed endpoint to one path.",
        devices=sig["dual_homed_hosts"])


def _d_native_vlan(snap, sig):
    if sig["native1_trunks"] <= 0:
        return None
    return _decision(
        "l2-dedicated-native-vlan-on-trunks",
        f"{sig['native1_trunks']} inter-switch trunk(s) across {sig['native1_switches']} switch(es) carry "
        f"VLAN 1 as the native (untagged) VLAN -- a double-tagging / VLAN-hopping exposure and a hygiene gap; "
        f"the target L2 edge must use a dedicated, unused native VLAN (and prune VLAN 1).",
        sig["native1_trunks"], ["security", "manageability"],
        ["interfaces[host][port].switchport_mode", "interfaces[host][port].trunk_native_vlan"],
        priority="High",
        driver="L2 edge hygiene: a dedicated native VLAN on trunks closes the VLAN-hopping/double-tag vector.",
        devices=sig["native1_hosts"])


def _d_false_health(snap, sig):
    if sig["false_health_high"] <= 0:
        return None
    egs = "; ".join(sig["false_health_titles"][:3]) or "see operational_drift"
    return _decision(
        "design-resolve-false-health-masks-before-baseline",
        f"{sig['false_health_high']} high-severity false-health condition(s) mask the true current state "
        f"({egs}) -- a temporary bridge or masked fault hides the real redundancy/topology/health the target "
        f"design must be built from; resolve and re-baseline before designing or cutting over.",
        sig["false_health_high"], ["manageability", "availability"],
        ["operational_drift[].severity", "operational_drift[].title", "operational_drift[].devices"],
        priority="High",
        driver="Baseline integrity: design from the true state, not one a temporary workaround or false-health is masking.",
        devices=sig["false_health_devices"])


def _d_bundle_health(snap, sig):
    if sig["bundle_degraded"] <= 0:
        return None
    return _decision(
        "dc-restore-degraded-portchannel-members-before-cutover",
        f"{sig['bundle_degraded']} EtherChannel/port-channel member anomalie(s) across "
        f"{sig['bundle_degraded_nsw']} switch(es) -- members are down/suspended/standalone, so the bundle "
        f"runs degraded (reduced bandwidth + lost link-level redundancy, often while 'show' still reads Up). "
        f"Restore full membership before baselining and cutover, or the target is built on degraded uplinks.",
        sig["bundle_degraded"], ["availability", "load_balancing"],
        ["protocol_intelligence[].protocol", "protocol_intelligence[].state", "protocol_intelligence[].severity"],
        priority="High",
        driver="Bundle redundancy: a port-channel with down/suspended members has degraded capacity and resilience.",
        devices=sig["bundle_degraded_hosts"])


# --------------------------------------------------- mega-wave detectors (collected-but-unused evidence, 2026-06)
def _d_vlan_subnet_integrity(snap, sig):
    if sig["vlan_multi_subnet"] <= 0:
        return None
    vids = ", ".join(sig["vlan_multi_subnet_vids"][:6]) or "see served_subnets"
    return _decision(
        "addressing-one-vlan-one-subnet-integrity",
        f"{sig['vlan_multi_subnet']} VLAN(s) (e.g. {vids}) are each bound to >= 2 distinct IP subnets across "
        f">= 2 gateway switches -- the same broadcast domain carries conflicting L3 identities, so any target that "
        f"merges or stretches these VLANs forwards non-deterministically. Reconcile each VLAN to a single subnet first.",
        sig["vlan_multi_subnet"], ["manageability", "availability", "optimal_routing"],
        ["subnet_intelligence.per_device[].served_subnets[].vlan",
         "subnet_intelligence.per_device[].served_subnets[].subnet",
         "l3_forwarding[].primary_subnet", "l3_forwarding[].svi_ip"],
        priority="High",
        driver="Addressing integrity: one VLAN must map to exactly one subnet, or the L2 merge is non-deterministic.",
        devices=sig["vlan_multi_subnet_hosts"])


def _d_stp_root_determinism(snap, sig):
    if sig["stp_accidental_roots"] <= 0:
        return None
    return _decision(
        "dc-stp-root-determinism",
        f"{sig['stp_accidental_roots']} spanning-tree root election(s) across {sig['stp_accidental_nsw']} "
        f"switch(es) were won at the DEFAULT bridge priority (32768 + VLAN id) on the MAC tiebreak -- the root is "
        f"accidental, not engineered, so a newly-introduced switch with a lower MAC can silently steal the root at "
        f"cutover and move the L2 topology. Set explicit 'root primary/secondary' co-located with the active gateway.",
        sig["stp_accidental_roots"], ["availability", "convergence", "manageability"],
        ["stp_roots[].is_root", "stp_roots[].root_priority"],
        priority="High",
        driver="Deterministic L2: the STP root must be explicitly placed, never left to a MAC-address tiebreak.",
        devices=sig["stp_accidental_hosts"])


def _d_reserved_vlan(snap, sig):
    if sig["reserved_vlan_svis"] <= 0:
        return None
    vids = ", ".join(str(v) for v in sig["reserved_vlan_vids"]) or "the reserved range"
    return _decision(
        "addressing-reserved-vlan-range-hygiene",
        f"{sig['reserved_vlan_svis']} production SVI(s) live on platform-reserved VLAN id(s) {vids} "
        f"(3968-4095 is reserved for internal use on Nexus) -- the target platform refuses an SVI there, so each of "
        f"these L3 links breaks silently at migration unless its VLAN is renumbered into the user range first.",
        sig["reserved_vlan_svis"], ["availability", "manageability", "optimal_routing"],
        ["l3_forwarding[].vlan", "l3_forwarding[].svi_ip"],
        priority="High",
        driver="Platform hygiene: renumber reserved-range SVIs into the user VLAN range before migrating to Nexus.",
        devices=sig["reserved_vlan_hosts"])


def _d_static_etherchannel(snap, sig):
    if sig["static_ec_bundles"] <= 0:
        return None
    return _decision(
        "dc-lacp-over-static-etherchannel",
        f"{sig['static_ec_bundles']} multi-member EtherChannel(s) across {sig['static_ec_nsw']} switch(es) run "
        f"static 'mode on' with no LACP -- a static bundle does no member negotiation, so a miscabled or one-way "
        f"member is admitted and silently blackholes its share of the hash; convert these to LACP (mode active).",
        sig["static_ec_bundles"], ["availability", "convergence", "load_balancing"],
        ["interfaces[host][port].port_channel", "interfaces[host][port].port_channel_protocol"],
        priority="High",
        driver="Bundle integrity: LACP detects the miscabling/one-way members that static 'mode on' silently admits.",
        devices=sig["static_ec_hosts"])


def _d_power_redundancy(snap, sig):
    if sig["psu_fail"] <= 0:
        return None
    return _decision(
        "dc-power-supply-redundancy",
        f"{sig['psu_fail']} multi-PSU chassis report a FAILED power supply -- N+1 redundancy is already lost and the "
        f"chassis is single-corded, so the next power event is a full-chassis outage. Restore the failed supply (and "
        f"dual-feed/dual-grid the keystone distribution/core nodes) before cutover.",
        sig["psu_fail"], ["availability", "cost"],
        ["devices[host].ps_status", "devices[host].num_power_supplies"],
        priority="High",
        driver="Power resilience: a multi-PSU chassis running on one good supply is a silent single point of failure.",
        devices=sig["psu_fail_hosts"])


def _d_gateway_cutover_order(snap, sig):
    if sig["gw_move_last"] <= 0:
        return None
    return _decision(
        "migration-gateway-cutover-order",
        f"{sig['gw_move_last']} gateway SVI(s) across {sig['gw_move_last_vlans']} VLAN(s) serve endpoints that "
        f"straddle >= 2 switches -- the subnet's default gateway must move LAST (keep the legacy SVI live and the "
        f"target BD flooding/anycast ready until all workloads are across), or trailing endpoints lose their gateway "
        f"mid-cutover. Sequence each move-group so the SVI is the final step.",
        sig["gw_move_last"], ["availability", "manageability"],
        ["l3_forwarding[].vlan", "l3_forwarding[].svi_ip", "endpoint_identity[].vlan", "endpoint_identity[].host"],
        priority="Medium", confidence="Planning",
        driver="Cutover order: move the default gateway after the workloads, never before -- gateway-move-last per subnet.")


def _d_oversized_l2_subnet(snap, sig):
    if sig["oversized_l2"] <= 0:
        return None
    top = ", ".join(f"VLAN {v} ({n} endpoints)" for v, n in sig["oversized_l2_top"][:3]) or "see census"
    return _decision(
        "dc-size-l2-subnet-to-endpoint-count",
        f"{sig['oversized_l2']} single-subnet VLAN(s) carry more than 254 evidenced endpoints ({top}) -- one "
        f"broadcast domain that size cannot live in a single /24, so the target must size a larger prefix (/23, /22) "
        f"or split the domain. (VLAN IDs reused across sites are excluded -- those are an addressing-integrity "
        f"renumber, not a resize.) Visible from the endpoint census, independent of any supplied address requirement.",
        sig["oversized_l2"], ["scalability", "manageability"],
        ["endpoint_identity[].vlan", "endpoint_identity[].host"],
        priority="Medium",
        driver="Subnet sizing: a >254-endpoint VLAN overflows a /24 -- size the prefix to the endpoint count or segment it.")


_DETECTORS = [_d_fhrp, _d_spof, _d_eol, _d_qos, _d_mgmt, _d_harden, _d_coverage,
              _d_flat_l2, _d_stp_lag, _d_stp_det, _d_igp, _d_mcast,
              _d_timesync, _d_voice_qos, _d_phased, _d_l2_faildomain,
              _d_stp_mst_scale, _d_oncrit_seg,
              _d_addr_overlap, _d_phys_remediation, _d_capacity, _d_dualhome, _d_native_vlan,
              _d_false_health, _d_bundle_health,
              # mega-wave 2026-06 (collected-but-unused evidence -> firing decisions):
              _d_vlan_subnet_integrity, _d_stp_root_determinism, _d_reserved_vlan, _d_static_etherchannel,
              _d_power_redundancy, _d_gateway_cutover_order, _d_oversized_l2_subnet]


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
    ("qos-class-model-from-app-profile", ["manageability"], ["critical_apps"],
     "Absent/ad-hoc QoS marking is observable, but the target class model needs the application traffic "
     "profile (which apps, which delay/loss budgets) -- supplied via the critical_apps requirement."),
    # Target-state TOPOLOGY/FABRIC choices: the current collapse is observable, but the choice is
    # scale/growth/traffic-driven (not an observation) -- so design top-down from the WHY, don't assume.
    ("dc-three-tier-vs-collapsed-core", ["scalability", "modularity", "cost"], ["growth_horizon"],
     "The current core/distribution collapse is observable, but a dedicated core vs a collapsed core is a "
     "SCALE choice: a dedicated core earns its cost past ~3 distribution blocks, multi-building reach, or "
     "tighter fault-isolation; collapsed core suits a small, single-site, low-growth footprint. Needs the "
     "growth horizon + closet/block count to right-size."),
    ("dc-spine-leaf-evpn-vs-collapsed", ["scalability", "modularity", "load_balancing"],
     ["growth_horizon", "data_classification"],
     "Whether the target DC becomes a spine-leaf VXLAN-EVPN fabric or stays collapsed-core + vPC is an "
     "east-west-scale / multi-tenancy choice, not an observable: spine-leaf earns its complexity with "
     "east-west growth and segmentation; a small/static footprint should not take on EVPN it does not need. "
     "Needs the growth horizon + traffic/tenancy profile."),
    ("dc-multisite-interconnect-fabrics-as-isolated-sites", ["availability", "scalability", "modularity"],
     ["growth_horizon"],
     "Once the estate spans multiple rooms/buildings/fabrics, whether to interconnect them as ISOLATED "
     "Multi-Site domains (a Border Gateway per site re-originates the overlay, eBGP between sites, per-site "
     "BUM/storm-control -- a fault, storm or gray failure is contained to one site) or stretch one fabric "
     "(Multi-Pod -- simpler, but one shared failure domain) is a scale/containment CHOICE, not an observable. "
     "Needs the growth horizon (site count / multi-building reach / fault-containment intent) to decide."),
    ("dc-fabric-aci-vs-nxos-evpn-operating-model", ["manageability", "security", "scalability"],
     ["fabric_operating_model"],
     "Once a DC spine-leaf fabric is the target, its OPERATING MODEL -- standalone NX-OS VXLAN BGP-EVPN "
     "(controller-less, open-standards, Nexus Dashboard/NDFC-managed; the 2026 default for new builds) vs "
     "Cisco ACI (APIC-controlled, application-centric EPG/contract policy fabric) -- is a top-down "
     "operating-model CHOICE, not a brownfield observable. Both deliver the same distributed-anycast-gateway "
     "VXLAN outcome; the difference is how the fabric is policed and operated. Needs the fabric_operating_model "
     "requirement (plus any existing-ACI-estate / identity-micro-segmentation mandate)."),
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
    fm = _norm_fabric_model(req.get("fabric_operating_model"))
    if fm == "aci":
        w["manageability"] = max(w["manageability"], 1.5)   # single declarative policy controller (intent)
        w["security"] = max(w["security"], 1.5)             # controller-native identity micro-segmentation
    elif fm == "nxos-evpn":
        w["simplicity"] = max(w["simplicity"], 1.3)         # open standards, no controller dependency
        w["scalability"] = max(w["scalability"], 1.4)       # east-west scale-out on open EVPN
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
        {"key": "fabric_operating_model",
         "label": "DC fabric operating model (standalone NX-OS VXLAN-EVPN vs Cisco ACI)",
         "options": ["nxos-evpn", "aci"], "value": req.get("fabric_operating_model")},
        {"key": "constraints", "label": "Fixed constraints (budget / installed-base / regulatory)",
         "value": req.get("constraints")},
        {"key": "data_classification", "label": "Data-security classification / zones",
         "value": req.get("data_classification")},
        # IP plan requirements — gated by _addressing_plan but must be surfaced here so every
        # interactive path (webapp form / interview / explorer CLI hint) knows to prompt for them.
        {"key": "address_space", "label": "Target address space (supernet, e.g. 10.0.0.0/16)",
         "value": req.get("address_space")},
        {"key": "vlan_zones", "label": "VLAN-to-zone map ({zone: [vlan_ids]}) for zone-aware IP allocation",
         "value": req.get("vlan_zones")},
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
        return f"{n} critical recommended target-state design decision(s); leading: {lead}."
    return f"Leading target-state design decision: {lead}."


# ----------------------------------------------------------------- full doctrine catalogue (surfacing)
def _doctrine_catalog():
    """The full design KB as a compact reference catalogue grouped by domain. Published in the blueprint
    so every surface can reason with ALL doctrine -- including the principles the L1-L4 assessment cannot
    auto-trigger (firewall, BGP, MPLS-TE, IPv6, ...) -- not just the evidence-emitted decisions. Stable
    order => deterministic."""
    by_dom = {}
    for p in design_kb.all_principles():
        by_dom.setdefault(p.get("domain", "other"), []).append({
            "id": p.get("id", ""),
            "title": p.get("title", ""),
            "priority": p.get("priority", "Medium"),
            "engine_actionable": bool(p.get("engine_actionable")),
            "recommended_action": p.get("recommended_action", ""),
            "citation": p.get("citation", ""),
        })
    return {dom: sorted(by_dom[dom], key=lambda x: (PRANK.get(x["priority"], 9), x["id"]))
            for dom in sorted(by_dom)}


# ----------------------------------------------------------------------- requirements register (the WHY)
REQUIREMENTS_KEYS = ("availability_tier", "critical_apps", "convergence_budget_ms",
                     "growth_horizon", "constraints", "data_classification", "address_space",
                     "vlan_zones", "fabric_operating_model")


def _norm_fabric_model(v):
    """Canonicalise the fabric_operating_model WHY-key to one of {'aci', 'nxos-evpn'} or '' (unknown).

    'aci' = Cisco ACI (APIC-controlled, application-centric policy fabric); 'nxos-evpn' = standalone
    NX-OS VXLAN BGP-EVPN (controller-less, Nexus Dashboard / NDFC-managed). Free text in, two stable
    values out; anything unrecognised is '' so the design surfaces the choice as an open question rather
    than guessing a fabric operating model the customer never stated."""
    s = str(v or "").strip().lower()
    if not s:
        return ""
    if "aci" in s or "apic" in s:
        return "aci"
    if any(t in s for t in ("evpn", "vxlan", "nxos", "nx-os", "ndfc", "standalone", "nexus")):
        return "nxos-evpn"
    return ""


def load_requirements(path):
    """Load a design REQUIREMENTS REGISTER (the WHY) from a JSON file into the recognised keys.

    Accepts a flat dict or a {"requirements": {...}} wrapper; keeps only REQUIREMENTS_KEYS that carry a
    non-empty value. Returns {} on missing/unreadable/malformed input -- non-fatal, mirroring the engine's
    coverage-honesty discipline: absence of a requirement stays an explicit open question (surfaced by
    compute_design_blueprint), never a silent guess.
    """
    if not path:
        return {}
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if isinstance(_as_dict(raw).get("requirements"), dict):
        raw = raw["requirements"]
    raw = _as_dict(raw)
    reg = {k: raw[k] for k in REQUIREMENTS_KEYS if raw.get(k) not in (None, "", [], {})}
    if "vlan_zones" in reg:                                          # normalise the explicit VLAN->zone map (or drop if unusable)
        nz = _norm_vlan_zones(reg["vlan_zones"])
        if nz:
            reg["vlan_zones"] = nz
        else:
            reg.pop("vlan_zones", None)
    if "fabric_operating_model" in reg:                             # canonicalise to {'aci','nxos-evpn'} or drop
        nm = _norm_fabric_model(reg["fabric_operating_model"])
        if nm:
            reg["fabric_operating_model"] = nm
        else:
            reg.pop("fabric_operating_model", None)
    return reg


def requirements_from_interview(answers):
    """Bridge the engagement interview to the design WHY: normalise a TYPED answers dict (keyed by the
    requirement keys -- the same keys `requirements_model.fields` / questionnaire `requirement_key` tags
    expose) into the requirements register, coercing list/int/tier shapes. Unknown keys ignored, empty
    dropped, non-dict -> {}. It maps the requirement answers the interview captures; it never invents a
    requirement from a qualitative go/no-go answer. One normalisation path: the result drives
    compute_design_blueprint exactly like a file/CLI register.

    PUBLIC integration entry point (no internal caller by design): a UI/CLI that captures the interview's
    requirement answers calls this, then passes the result as `requirements` to compute_design_blueprint
    (mirrors how COLLECT_PARSE uses load_requirements for the --requirements file path)."""
    a = _as_dict(answers)

    def _to_list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return [p.strip() for p in str(v).split(",") if p.strip()]

    out = {}
    for k in REQUIREMENTS_KEYS:
        v = a.get(k)
        if v in (None, "", [], {}):
            continue
        if k == "availability_tier":
            out[k] = str(v).strip().lower()
        elif k in ("critical_apps", "constraints", "data_classification"):
            out[k] = _to_list(v)
        elif k == "convergence_budget_ms":
            iv = _as_int(v, None)                  # keep a legitimate 0; fall back to raw only if unparseable
            out[k] = iv if iv is not None else v
        elif k == "vlan_zones":
            nz = _norm_vlan_zones(v)
            if nz:
                out[k] = nz
        elif k == "fabric_operating_model":
            nm = _norm_fabric_model(v)
            if nm:
                out[k] = nm
        else:                                                    # growth_horizon, address_space
            out[k] = str(v).strip()
    return out


# ---------------------------------------------------------------- candidate target-state architecture
def _role_counts(snap):
    roles = {}
    for r in _as_list(snap.get("health_scores")):
        role = str(r.get("role") or "").lower() or "unknown"
        roles[role] = roles.get(role, 0) + 1
    return roles


def _ts_dim(area, current, target, rationale, confidence, drivers=None, requirement_needed=None):
    d = {"area": area, "current": current, "target": target, "rationale": rationale,
         "confidence": confidence, "drivers": list(drivers or [])}
    if requirement_needed:
        d["requirement_needed"] = requirement_needed
    return d


def _replacement_bom(snap):
    """Target procurement: assets at/near end-of-support that must be replaced/refreshed, grouped by their
    CURRENT model. Read straight from lifecycle_risk.per_device (band + model). A supported successor SKU
    is chosen at detailed design -- not invented here. Supportable assets carry forward."""
    life = _as_list(_as_dict(snap.get("lifecycle_risk")).get("per_device"))
    replace, refresh = {}, {}
    for d in life:
        band = str(d.get("band", "")).strip().lower()
        model = d.get("model") or "Unknown"
        if band == "past-ldos":                          # unsupported (no TAC/fixes) -> must replace now
            replace[model] = replace.get(model, 0) + 1
        elif "near" in band or band == "past-eos":       # approaching LDoS, or past-sale but STILL supported
            refresh[model] = refresh.get(model, 0) + 1    # -> refresh, NOT replace-now
    def _rows(m):
        return sorted(([model, qty] for model, qty in m.items()), key=lambda r: (-r[1], r[0]))
    return {
        "replace_now": _rows(replace),
        "refresh_soon": _rows(refresh),
        "n_replace": sum(replace.values()),
        "n_refresh": sum(refresh.values()),
        "note": "Quantities are the current models at/near end-of-support; a supported successor SKU is "
                "selected at detailed design (not auto-chosen here). Supportable assets carry forward.",
    }


def _tier_zones(seg):
    """Distinct observed sensitivity tiers that have >=1 gateway, ordered by total gateway weight desc then
    name. Each is a candidate macro-segmentation zone -- evidence-derived from segmentation.domains[].tier
    (the engine's OWN classification of the broadcast domains), not a fabricated security assignment."""
    weight = {}
    for d in _as_list(_as_dict(seg).get("domains")):
        d = _as_dict(d)
        tier = str(d.get("tier") or "").strip()
        g = _as_int(d.get("gateways"))
        if tier and g > 0:
            weight[tier] = weight.get(tier, 0) + g
    return sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))


def _segmentation_plan(snap, req, census=None):
    """Target L3 segmentation intent. The observed VRF/VLAN state is grounded; the zone DEFINITIONS need a
    data classification -- absent it this stays an open question (zones are never fabricated). `census` (the
    canonical vlan_inventory count) may be passed in to avoid recomputing the inventory walk."""
    seg = _as_dict(snap.get("segmentation"))
    vrfs = _as_list(seg.get("vrfs"))
    n_vlans = _vlan_count(snap) if census is None else census
    dc = _as_list(req.get("data_classification")) if req else []
    plan = {
        "observed": (f"{n_vlans} VLAN(s) across "
                     + (f"{len(vrfs)} VRFs -- partially segmented." if len(vrfs) > 1
                        else "a single global VRF -- L3-unsegmented.")),
        "principle": "security-defense-in-depth-segmentation",
    }
    if dc:
        plan["status"] = "candidate"
        plan["target_zones"] = list(dc)
        plan["target"] = (f"Map VLANs to the {len(dc)} declared zone(s) ({', '.join(map(str, dc))}); enforce "
                          "inter-zone policy at a firewall/VRF boundary, default-deny between zones (confirm "
                          "the per-VLAN assignment with the customer).")
    else:
        tiers = _tier_zones(seg)
        if len(tiers) > 1:
            # Evidence-derived SEED: the engine already classified the broadcast domains into >1 sensitivity
            # tier -> a starting macro-segmentation is one zone per observed tier (NOT a fabricated assignment;
            # the per-VLAN map is still firmed by data_classification, which takes precedence above).
            plan["status"] = "candidate"
            plan["mode"] = "tier-seeded"
            plan["target_zones"] = [t for t, _ in tiers]
            plan["n_macro_zones"] = len(tiers)
            tier_desc = ", ".join(f"{t} ({g} gw)" for t, g in tiers)
            plan["target"] = (f"The estate already classifies its broadcast domains into {len(tiers)} sensitivity "
                              f"tier(s) ({tier_desc}); a starting macro-segmentation is ONE security zone per "
                              f"observed tier -- enforce inter-zone policy at a firewall/VRF boundary, default-deny "
                              f"between zones. The tiers are an evidence-derived SEED: supply data_classification to "
                              f"firm the per-VLAN zone map (the assignment is not assumed here).")
        else:
            plan["status"] = "needs-requirement"
            plan["requirement_needed"] = "data_classification"
            plan["target"] = ("Segment into security zones aligned to a data classification (which assets must be "
                              "isolated from which); supply data_classification to propose the VLAN->zone map -- "
                              "zones are not assumed here.")
    return plan


def _vlan_host_counts(snap):
    counts = {}
    for _host, ports in _as_dict(snap.get("interfaces")).items():
        if not isinstance(ports, dict):
            continue
        for _p, a in ports.items():
            if isinstance(a, dict) and (a.get("switchport_mode") or "") == "Access" and str(a.get("vlan") or "").isdigit():
                vid = int(a["vlan"])
                counts[vid] = counts.get(vid, 0) + 1
    return counts


def _norm_vlan_zones(v):
    """Normalise an explicit VLAN->zone map to {int(vid): str(zone)}. Accepts {vid: zone} or {zone: [vids]};
    drops non-numeric VIDs and malformed entries. Returns {} for anything unusable -- the ONLY gate for
    zone-aware allocation, so a bad/absent map degrades safely to non-zone-aware (never fabricated)."""
    if not isinstance(v, dict) or not v:
        return {}
    out = {}
    if any(isinstance(val, (list, tuple)) for val in v.values()):    # {zone: [vids]}
        for zone, vids in v.items():
            for vid in (vids if isinstance(vids, (list, tuple)) else [vids]):
                if str(vid).strip().isdigit():
                    out[int(vid)] = str(zone)
    else:                                                            # {vid: zone}
        for vid, zone in v.items():
            if str(vid).strip().isdigit():
                out[int(vid)] = str(zone)
    return out


def _target_vids(snap):
    counts = _vlan_host_counts(snap)
    vids = {v for v in counts if v and v != 1}
    for r in _as_list(snap.get("l3_forwarding")):
        v = r.get("vlan")
        if str(v).isdigit() and int(v) != 1:
            vids.add(int(v))
    return sorted(vids), counts


def _alloc_flat(supernet, vids, counts):
    """Mode A: a flat /24 per VLAN, sequentially from the supernet (the whole plan summarises to the
    supernet). Sized from observed access-port counts; oversized (>254) and overflow are reported."""
    if supernet.prefixlen > 24:                          # smaller than a /24 -> cannot give a /24 per VLAN
        return {"status": "candidate", "mode": "flat", "supernet": str(supernet), "subnets": [],
                "n_allocated": 0, "n_overflow": len(vids), "oversized_vlans": [],
                "note": f"address_space {supernet} is smaller than a /24; the /24-per-VLAN scheme needs at "
                        "least a /24 -- supply a larger supernet."}
    pool = supernet.subnets(new_prefix=24)
    subnets, overflow, oversized = [], 0, []
    for vid in vids:
        hosts = counts.get(vid, 0)
        try:
            block = next(pool)
        except StopIteration:
            overflow += 1
            continue
        rec = {"vlan": vid, "hosts": hosts, "subnet": str(block)}
        if hosts > 254:
            rec["note"] = "needs >/24 — allocate a larger block manually"
            oversized.append(vid)
        subnets.append(rec)
    return {
        "status": "candidate", "mode": "flat", "supernet": str(supernet), "subnets": subnets,
        "n_allocated": len(subnets), "n_overflow": overflow, "oversized_vlans": oversized,
        "note": "Candidate /24-per-VLAN allocation, each VLAN a contiguous /24 allocated sequentially "
                "within the supplied supernet, sized from observed access-port counts; confirm growth "
                "headroom and reconcile with any retained addressing. "
                + (f"{overflow} VLAN(s) did not fit the supernet (enlarge it). " if overflow else "")
                + (f"{len(oversized)} VLAN(s) exceed a /24 and need a larger block. " if oversized else ""),
    }


def _alloc_zone_aware(supernet, vids, counts, vlan_zones):
    """Mode B: one CONTIGUOUS, summarisable block per zone, SIZED TO EACH ZONE'S /24 DEMAND (one /24 per
    VLAN, rounded up to a power-of-two span so the block is a single aligned, summarisable prefix) -- NOT a
    uniform split by zone count, which overflows an uneven zone while another wastes space. Blocks are
    carved greedily from the supernet (largest first, alignment-correct); per-VLAN /24 within the owning
    zone's block. VLANs with no mapping go to a residual '(unzoned)' block AND are listed in unmapped_vlans
    -- never force-fit into a real zone. Each zone summarises to ONE prefix. IPv4 only (the caller rejects
    IPv6 before this point)."""
    import ipaddress
    import math
    zones, unmapped = {}, []
    for vid in vids:
        z = vlan_zones.get(vid)
        (zones.setdefault(z, []).append(vid) if z is not None else unmapped.append(vid))
    order = sorted(zones)
    if unmapped:
        zones["(unzoned)"] = sorted(unmapped)
        order = order + ["(unzoned)"]
    real_zones = [z for z in order if z != "(unzoned)"]
    base = {"status": "candidate", "mode": "zone-aware", "supernet": str(supernet),
            "n_zones": len(real_zones), "unmapped_vlans": sorted(unmapped)}

    def _zone_prefix(n):
        # one /24 per VLAN, rounded up to a power-of-two /24 count -> a single aligned summarisable prefix;
        # never longer (smaller) than the supernet itself.
        span = 1 << max(0, math.ceil(math.log2(max(1, n))))
        return max(supernet.prefixlen, 24 - (span.bit_length() - 1))

    # Carve a right-sized block per zone, greedily from the supernet, largest block first (so alignment
    # never strands space a smaller block could have used).
    net_start, net_end = int(supernet.network_address), int(supernet.broadcast_address)
    cursor = net_start
    block_of, overflow = {}, 0
    for zname, p in sorted(((z, _zone_prefix(len(zones[z]))) for z in order), key=lambda t: t[1]):
        size = 1 << (32 - p)
        aligned = (cursor + size - 1) // size * size                # next size-aligned slot at/after cursor
        if aligned + size - 1 <= net_end:
            block_of[zname] = ipaddress.ip_network((aligned, p))
            cursor = aligned + size
        else:
            overflow += len(zones[zname])                           # this zone does not fit the supernet
    if not any(block_of.values()):
        return {**base, "subnets": [], "zones": [], "n_allocated": 0, "n_overflow": len(vids),
                "oversized_vlans": [],
                "note": f"address_space {supernet} too small for the {len(order)} zone block(s) -- enlarge it."}

    subnets, zone_recs, oversized = [], [], []
    for zname in order:                                             # stable output order (sorted zones, unzoned last)
        zblock = block_of.get(zname)
        if zblock is None:
            continue
        if zblock.prefixlen > 24:                       # a sub-/24 block cannot host a /24 per VLAN -> overflow
            overflow += len(zones[zname])
            continue
        zone_recs.append({"zone": zname, "summary": str(zblock), "n_vlans": len(zones[zname])})
        pool = zblock.subnets(new_prefix=24)
        for vid in zones[zname]:
            hosts = counts.get(vid, 0)
            try:
                sub = next(pool)
            except StopIteration:
                overflow += 1
                continue
            rec = {"vlan": vid, "hosts": hosts, "subnet": str(sub), "zone": zname}
            if hosts > 254:
                rec["note"] = "needs >/24 — allocate a larger block manually"
                oversized.append(vid)
            subnets.append(rec)
    return {**base, "subnets": subnets, "zones": zone_recs, "n_allocated": len(subnets),
            "n_overflow": overflow, "oversized_vlans": oversized,
            "note": "Zone-aware candidate: each zone is one contiguous, summarisable block sized to its own "
                    "VLAN demand (one prefix), per-VLAN /24 within it. Unmapped VLANs sit in a residual "
                    "'(unzoned)' block -- assign them explicitly. Sized from observed access-port counts; "
                    "confirm growth headroom."
                    + (f" {overflow} VLAN(s) overflowed the supernet (enlarge it)." if overflow else "")}


def _addressing_plan(snap, req, census=None):
    """Net-new IP plan. REQUIREMENT-GATED on address_space -- absent/invalid it returns needs-requirement
    and fabricates NO subnets. Supplied + an explicit vlan_zones map -> ZONE-AWARE allocation (one
    summarisable block per zone); supplied alone -> flat /24-per-VLAN (Mode A). data_classification NAMES
    alone NEVER infer a VLAN->zone map (that would fabricate a security assignment) -- they only set a
    caveat pointing to vlan_zones. `census` (the canonical vlan_inventory count) may be passed in to avoid
    recomputing the full inventory walk; it falls back to computing it when absent."""
    space = (req or {}).get("address_space")
    vids, counts = _target_vids(snap)
    # Always compute the full census and the unsizable delta — needed for honest disclosure on ALL paths
    # (including the needs-requirement early returns) so every surface can show the context note
    # "N census VLANs; M have no access port/SVI" before an address_space is even supplied.
    census = _vlan_count(snap) if census is None else census
    n_unsizable = max(0, census - len(vids))
    if not space:
        return {"status": "needs-requirement", "requirement_needed": "address_space",
                "observed_vlans": len(vids),
                "n_census_vlans": census,
                "n_unsizable": n_unsizable,
                "note": "Supply an address_space (supernet, e.g. 10.0.0.0/16) to allocate target subnets; "
                        "a net-new IP plan is not fabricated without one."}
    import ipaddress
    try:
        supernet = ipaddress.ip_network(str(space).split(",")[0].strip(), strict=False)
    except ValueError:
        return {"status": "needs-requirement", "requirement_needed": "address_space",
                "observed_vlans": len(vids),
                "n_census_vlans": census,
                "n_unsizable": n_unsizable,
                "note": f"address_space '{space}' is not a valid network; supply e.g. 10.0.0.0/16."}
    if supernet.version != 4:                            # the candidate /24-per-VLAN allocator is IPv4-only
        return {"status": "needs-requirement", "requirement_needed": "address_space",
                "observed_vlans": len(vids), "n_census_vlans": census, "n_unsizable": n_unsizable,
                "note": f"address_space '{space}' is IPv6; the candidate /24-per-VLAN allocator is IPv4-only "
                        "-- size IPv6 prefixes (typically a /64 per VLAN) at detailed design."}
    vlan_zones = _norm_vlan_zones((req or {}).get("vlan_zones"))
    if vlan_zones:
        plan = _alloc_zone_aware(supernet, vids, counts, vlan_zones)
    else:
        plan = _alloc_flat(supernet, vids, counts)
        if (req or {}).get("data_classification"):
            plan["zone_caveat"] = ("zone blocks need an explicit VLAN->zone map (supply vlan_zones); zones are "
                                   "NOT inferred from VLAN IDs or data_classification names")
    # Reconcile against the canonical VLAN census (vlan_inventory, the count §5.2 prints): disclose the
    # delta so 202-vs-N is never a silent drop. Only VLANs with an observed access port or L3 SVI can be
    # sized; VLAN 1 + querier-only VLANs whose SVI sits on an uncollected core have nothing to size from.
    # census / n_unsizable are already computed at function entry for the needs-requirement paths; reuse them.
    plan["n_census_vlans"] = census
    plan["n_unsizable"] = max(0, census - len(vids))
    if plan["n_unsizable"]:
        plan["note"] += (f" Sized for the {len(vids)} VLAN(s) with an observed access port or L3 SVI; "
                         f"{plan['n_unsizable']} further census VLAN(s) (VLAN 1 + querier-only VLANs whose SVI "
                         f"is on an uncollected core) carry no auto-sized subnet -- confirm at detailed design.")
    return plan


def _wave_plan(snap, cap=_WAVE_CAP):
    """Turn raw move-groups (L2-coupling connected-components) into realistic migration WAVES. An oversized
    coupled group is sliced into <=cap name-clustered SEQUENCED sub-waves (they share VLANs, so the shared
    VLANs must be coordinated across sub-waves); independent small groups are bin-packed into combined
    waves (parallelizable). Additive -- compute_move_groups (the coupling) is unchanged; every switch is
    placed exactly once."""
    groups = [g for g in _as_list(snap.get("move_groups"))
              if isinstance(g, dict) and _as_list(g.get("switches"))]
    big_subwaves, small = [], []
    n_subdivided = 0
    for gi, g in enumerate(groups):
        sw = sorted(_as_list(g.get("switches")))                     # alpha sort clusters by site/building/rack
        if len(sw) > cap:
            n_subdivided += 1
            for i in range(0, len(sw), cap):
                big_subwaves.append({"switches": sw[i:i + cap], "kind": "coupled-subwave", "source_groups": [gi]})
        else:
            small.append((gi, sw))
    packed, cur, cur_n = [], [], 0                                   # bin-pack independent small groups
    for gi, sw in sorted(small, key=lambda t: (-len(t[1]), t[1][0])):
        if cur and cur_n + len(sw) > cap:
            packed.append(cur); cur, cur_n = [], 0
        cur.append((gi, sw)); cur_n += len(sw)
    if cur:
        packed.append(cur)
    small_waves = [{"switches": [h for _, s in grp for h in s], "kind": "independent-batch",
                    "source_groups": [gi for gi, _ in grp]} for grp in packed]
    waves = big_subwaves + small_waves
    for n, w in enumerate(waves, 1):
        w["wave"] = n
        w["n_switches"] = len(w["switches"])
    largest = max((len(_as_list(g.get("switches"))) for g in groups), default=0)
    return {
        "waves": waves, "n_waves": len(waves), "wave_cap": cap,
        "n_move_groups": len(groups), "largest_group": largest, "n_subdivided_groups": n_subdivided,
        "note": (f"Candidate migration waves (<= {cap} switches each). 'coupled-subwave' = a slice of one "
                 "oversized L2-coupled move-group -- these share VLANs, so they are a SEQUENCE and the shared "
                 "VLANs must be extended/coordinated across sub-waves until the group fully migrates. "
                 "'independent-batch' = unrelated small groups packed together (parallelizable). The full "
                 "per-wave member switch lists and ordered cutover steps are in the per-wave MOP (one "
                 "section per candidate wave)."),
    }


def compute_target_state(snap, requirements=None, sig=None):
    """A CANDIDATE target-state architecture synthesised from current-state evidence + the requirements
    register + doctrine. Dimension-by-dimension (current -> target -> rationale -> confidence), each
    traceable to a principle; the tier-model CHOICE is requirement-gated on growth (never asserted from
    absent evidence), and uncollected devices stay an explicit unknown. This is architecture-level only --
    a full IP / VLAN-VRF addressing plan and BoM are the next design layer, deliberately not fabricated.
    `sig` (the _signals bundle) may be passed in to avoid recomputing it when the caller already built one.
    """
    snap = _as_dict(snap)
    req = _as_dict(requirements) if requirements else {}
    sig = _signals(snap) if sig is None else sig
    roles = _role_counts(snap)
    wp = _wave_plan(snap)
    dims = []

    # 1. Topology / tier model -- a scale/growth-driven CHOICE -> requirement-gated on growth
    scale_note = (f"{sig['inventory']} inventoried / {sig['collected']} collected device(s); "
                  f"roles {', '.join(f'{k}:{v}' for k, v in sorted(roles.items())) or 'n/a'}; "
                  f"{sig['l2_wide_vlans']} VLAN(s) span >= {_L2_SPAN_SWITCHES} switches; "
                  f"{'single global VRF' if sig['single_vrf'] else 'multiple VRFs'}.")
    if not req.get("growth_horizon"):
        dims.append(_ts_dim(
            "Topology / tier model", scale_note,
            "(needs growth horizon) -- collapsed-core vs 3-tier vs spine-leaf is a scale/growth CHOICE",
            "Collapsed core suits a small, single-site, low-growth footprint; a dedicated core / 3-tier "
            "earns its cost past ~3 distribution blocks or multi-building growth; spine-leaf (VXLAN-EVPN) "
            "for east-west DC scale. The L1-L4 evidence shows current scale, not the growth intent.",
            "Requirement-needed",
            drivers=["dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed"],
            requirement_needed="growth_horizon"))
    else:
        big = (sig["inventory"] >= 60 or sig["l2_wide_vlans"] >= 8
               or (roles.get("core", 0) + roles.get("distribution", 0)) >= 6)
        target = (("3-tier hierarchy (core / distribution / access) with routed access -- distribution/core "
                   "on L3, access VLANs bounded per switch; for the data centre, a routed leaf-spine "
                   "(folded-Clos) VXLAN BGP-EVPN fabric sized by oversubscription, and where the estate spans "
                   "multiple rooms/sites interconnect them as isolated Multi-Site domains (Border Gateway per "
                   "site) rather than one stretched fabric") if big else
                  ("collapsed core + multi-chassis LAG (vPC/SVL) -- distribution doubles as core for a small/"
                   "static footprint, fully meshed with STP root + FHRP co-located there"))
        dims.append(_ts_dim(
            "Topology / tier model", scale_note, target,
            f"Right-sized to the stated growth ('{str(req.get('growth_horizon'))[:60]}') and observed scale; "
            "bounds L2 failure domains and scales by adding blocks (or spines/leaves + sites).",
            "Candidate", drivers=["dc-three-tier-vs-collapsed-core", "dc-spine-leaf-evpn-vs-collapsed",
                                  "dc-fabric-clos-sizing-oversubscription-ecmp",
                                  "dc-multisite-interconnect-fabrics-as-isolated-sites"]))

    # 1b. DC fabric OPERATING MODEL / realisation -- a top-down CHOICE (controller-based Cisco ACI vs standalone
    # NX-OS VXLAN-EVPN), requirement-gated on fabric_operating_model. Only in scope when a spine-leaf fabric is
    # genuinely a candidate target (scale / wide-L2 / many VLANs, or the customer has stated a model) -- never
    # noise for a small non-DC estate. Same forwarding outcome either way; the choice is how the fabric is operated.
    fm = _norm_fabric_model(req.get("fabric_operating_model"))
    fabric_candidate = (sig["l2_wide_vlans"] or sig["vlans"] >= _LARGE_L2_VLANS
                        or sig["inventory"] >= 30 or bool(fm))
    if fabric_candidate:
        if not fm:
            dims.append(_ts_dim(
                "DC fabric operating model", scale_note,
                "(needs fabric_operating_model) -- Cisco ACI (APIC-controlled, application-centric EPG/contract "
                "policy fabric) vs standalone NX-OS VXLAN BGP-EVPN (controller-less, Nexus Dashboard/NDFC-managed). "
                "Both realise the same spine-leaf + distributed-anycast-gateway VXLAN outcome; the difference is "
                "the OPERATING MODEL.",
                "A top-down operating-model decision, not a brownfield observable: default to NX-OS VXLAN-EVPN for "
                "new builds (open RFC 7432/8365 standards, portable multivendor skills, Nexus Dashboard/NDFC ops "
                "incl. IP Fabric for Media) unless an existing ACI estate or an application-centric end-to-end "
                "identity micro-segmentation mandate justifies ACI's single declarative policy controller. Supply "
                "fabric_operating_model to resolve it.",
                "Requirement-needed",
                drivers=["dc-fabric-aci-vs-nxos-evpn-operating-model", "dc-fabric-vxlan-evpn-control-plane",
                         "aci-policy-epg-contract-whitelist-default-deny", "evpn-esi-all-active-multihoming"],
                requirement_needed="fabric_operating_model"))
        elif fm == "aci":
            dims.append(_ts_dim(
                "DC fabric operating model", scale_note + " fabric_operating_model = Cisco ACI.",
                "Cisco ACI: an APIC-controlled spine-leaf fabric (3-node controller cluster, quorum 2-of-3, "
                "sharded config DB) with a declarative application-centric policy model -- tenants / application "
                "profiles / EPGs / contracts as a whitelist, a pervasive (distributed anycast) gateway, and a "
                "service graph + PBR for L4-L7 insertion; micro-segmentation by EPG identity end-to-end.",
                "Chosen for a single declarative policy controller and identity-based micro-segmentation at scale "
                "(or to extend an existing ACI estate); the trade-off is product-coupled skills + a controller "
                "dependency against open-standards portability.",
                "Candidate", drivers=["dc-fabric-aci-vs-nxos-evpn-operating-model",
                                      "dc-fabric-distributed-anycast-gateway-irb",
                                      "aci-policy-network-centric-onramp-then-application-centric",
                                      "aci-policy-epg-contract-whitelist-default-deny",
                                      "aci-fabric-controller-cluster-odd-quorum-sharding",
                                      "aci-services-servicegraph-pbr-symmetric-insertion"]))
        else:  # nxos-evpn
            dims.append(_ts_dim(
                "DC fabric operating model", scale_note + " fabric_operating_model = NX-OS VXLAN-EVPN.",
                "Standalone NX-OS VXLAN BGP-EVPN: a controller-less, open-standards (RFC 7432 EVPN / RFC 8365 "
                "VXLAN / RFC 9135 IRB) spine-leaf fabric managed by Nexus Dashboard (NDFC), with a distributed "
                "anycast gateway and a BGP-EVPN control plane -- and, for broadcast/media estates, IP Fabric for "
                "Media (IPFM). Segmentation via VRF/VNI plus VXLAN GPO group policy where micro-segmentation is "
                "required.",
                "The 2026 default for new builds: open standards, portable multivendor operations and no single-"
                "controller dependency; the trade-off vs ACI is decentralised policy for operational familiarity "
                "and standards-portability.",
                "Candidate", drivers=["dc-fabric-aci-vs-nxos-evpn-operating-model",
                                      "dc-fabric-vxlan-evpn-control-plane", "dc-fabric-distributed-anycast-gateway-irb",
                                      "evpn-esi-all-active-multihoming", "evpn-bum-df-election-split-horizon"]))

    # 2. Layer-2 / Layer-3 boundary & failure domains -- strong evidence
    if sig["l2_wide_vlans"] or sig["vlans"] >= _LARGE_L2_VLANS or sig["single_vrf"]:
        dims.append(_ts_dim(
            "Layer-2 / Layer-3 boundary",
            f"{sig['l2_wide_vlans']} oversized bridging domain(s); {sig['vlans']} VLAN(s) in "
            f"{'one global VRF' if sig['single_vrf'] else 'multiple VRFs'}.",
            "Push the L3 boundary toward the edge (routed access, or a per-block distribution SVI) and confine "
            "each VLAN to one access switch/block; in the target VXLAN-EVPN fabric, Layer-2 is bounded to the "
            "leaf edge with a BGP-EVPN control plane (control-plane MAC/IP learning, not flood-and-learn); "
            "segment into VRFs/zones so a broadcast or STP event stays local.",
            "A transparently-bridged VLAN is one failure domain; bounding its span limits blast radius and "
            "improves convergence and scale.",
            "Recommended", drivers=["dc-bound-layer2-failure-domain", "dc-restrict-vlan-span-routed-access",
                                    "dc-fabric-vxlan-evpn-control-plane"]))

    # 3. Gateway / first-hop resilience -- strong evidence
    if sig["no_fhrp"]:
        dims.append(_ts_dim(
            "Gateway / first-hop resilience",
            f"{sig['no_fhrp']} gateway VLAN(s) single-homed, no FHRP.",
            "Provide first-hop redundancy: in a classic distribution, dual gateways with FHRP (HSRP/VRRP) and "
            "the STP root co-located with the active gateway; in the target VXLAN-EVPN fabric, a DISTRIBUTED "
            "ANYCAST GATEWAY -- the same gateway IP/MAC on every leaf, so first-hop routing is local at the "
            "ingress leaf and survives any single node (the EVPN replacement for centralized FHRP, seamless on "
            "host mobility).",
            "First-hop redundancy is structural HA; a single gateway is a per-VLAN single point of failure.",
            "Recommended", drivers=["fhrp-first-hop-gateway-redundancy", "dc-fabric-distributed-anycast-gateway-irb",
                                    "stp-root-fhrp-active-colocation"]))

    # 4. Hardware lifecycle disposition -- strong evidence
    if sig["eol"] or sig["near"] or sig["not_collected"]:
        retain = max(0, sig["collected"] - sig["eol"])
        dims.append(_ts_dim(
            "Hardware lifecycle disposition",
            f"{sig['eol']} past-LDoS, {sig['near']} approaching-LDoS, {sig['not_collected']} not-collected "
            f"of {sig['inventory']} inventoried.",
            f"Replace the {sig['eol']} past-LDoS asset(s); plan refresh for the {sig['near']} approaching LDoS; "
            f"carry ~{retain} supportable asset(s) forward; collect the {sig['not_collected']} un-assessed "
            f"device(s) before finalising -- do not design resilience on unseen gear.",
            "The target fabric must not inherit end-of-support hardware; coverage gaps are unknowns, not health.",
            "Recommended", drivers=["lifecycle-eol-out-of-critical-roles", "fhrp-not-observed-is-not-healthy"]))

    # 5. Migration approach -- planning, from move-groups + the derived wave plan
    if sig["move_groups"]:
        dims.append(_ts_dim(
            "Migration approach",
            f"{wp['n_move_groups']} move-group(s) (largest is a {wp['largest_group']}-switch L2-coupled group) "
            f"across {sig['move_switches']} switch(es).",
            f"Phased build-before-break in {wp['n_waves']} candidate wave(s) of <= {wp['wave_cap']} switches "
            f"({wp['n_subdivided_groups']} oversized group(s) sliced into sequenced sub-waves, the rest "
            "batched); stand the target up in parallel, validate (NRFU) per wave, cut over, then decommission "
            "-- preserving rollback at each wave. Bridge legacy<->fabric with a SINGLE logical L2 link per VLAN "
            "(the EVPN fabric does not forward STP BPDUs) and move each VLAN's default gateway to the fabric "
            "anycast gateway once its endpoints are migrated, then shut the legacy SVI.",
            "A parallel target with right-sized, per-wave-validated waves beats both a big-bang cutover and "
            "an unmanageable single 251-switch 'wave'.",
            "Planning", drivers=["scenario-build-before-break-phased-cutover",
                                 "dc-fabric-fabric-drops-bpdu-single-l2-handoff"]))

    # 6. Media / timing fabric -- broadcast (ST 2110) timing plane, from observed PTP + AV-multicast evidence.
    #    Gated on the media estate actually being present (PTP-capable switches OR AV multicast groups) so it is
    #    never noise for a non-broadcast network. Coverage-honest: states the observed PTP/grandmaster posture.
    mi = _as_dict(snap.get("multicast_intelligence"))
    ptp = _as_dict(mi.get("ptp"))
    n_clocks = _as_int(ptp.get("n_clocks"))
    n_av = _as_int(_as_dict(mi.get("summary")).get("n_av_groups"))
    if n_clocks > 0 or n_av > 0:
        n_op = _as_int(ptp.get("n_operational"))
        n_gm = len(_as_list(ptp.get("grandmasters")))
        dims.append(_ts_dim(
            "Media / timing fabric",
            f"{n_clocks} PTP-capable switch(es), {n_op} operational / {n_gm} grandmaster; "
            f"{n_av} audio/video multicast group(s) on the flat fabric.",
            "Run SMPTE ST 2059-2 (the broadcast PTP profile) with a boundary clock on every media-path switch, "
            "locked to a REDUNDANT grandmaster pair in one PTP domain (sub-microsecond, ~1 us accuracy); carry the "
            "AV essence flows as IGMPv3/SSM and isolate the media plane in a dedicated VRF/zone off the flat global L3.",
            f"A professional media (ST 2110) fabric lives or dies on timing: PTP-capable switches with "
            f"{'no operational grandmaster' if n_gm == 0 else 'a single grandmaster'} have no resilient time "
            f"reference, so a clock loss silently corrupts every audio/video essence flow.",
            "Observed",
            drivers=["multicast-media-fabric-ptp-timing", "security-isolate-oncritical-application-tier"]))

    n_gated = sum(1 for d in dims if d.get("requirement_needed"))
    headline = (f"Candidate target-state across {len(dims)} dimension(s)"
                + (f"; {n_gated} await a requirement" if n_gated else "")
                + " -- a proposal to validate, not a final design.")
    return {
        "dimensions": dims,
        "replacement_bom": _replacement_bom(snap),
        "segmentation_plan": _segmentation_plan(snap, req, census=sig["vlans"]),
        "addressing_plan": _addressing_plan(snap, req, census=sig["vlans"]),
        "wave_plan": wp,
        "coverage": _coverage(snap),
        "summary": {"n_dimensions": len(dims), "n_requirement_gated": n_gated, "headline": headline},
        "scope_note": "Architecture + LLD detail (tier model, L2/L3 boundary, resilience, lifecycle "
                      "disposition + replacement BoM, target segmentation, net-new IP plan, migration). "
                      "The IP plan and zone map are requirement-gated (address_space / data_classification) "
                      "so nothing is fabricated; supply those to firm them up.",
    }


# ----------------------------------------------------------------------------- public entrypoint
def compute_design_blueprint(snap, requirements=None):
    """Canonical, CCDE-grounded target-state design blueprint for a snapshot.

    Reads only already-computed evidence; every decision is evidence-gated and cites a `design_kb`
    principle. `requirements` (optional dict: availability_tier, critical_apps, convergence_budget_ms,
    growth_horizon, constraints, data_classification, address_space, vlan_zones) right-sizes the decisions
    and the target-state (IP plan / zones) when supplied.
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
        # SSOT: the user-facing "critical" count is Critical AND recommended -- the same population the
        # headline (_headline) and every surface's decision cards render (HLD §4.2 / deck / explorer /
        # webapp). Counting ALL Critical (incl. requirement-gated open questions) made the deck/explorer/
        # webapp show 5 while the HLD headline showed 4 for the same design (a cross-surface drift). The
        # requirement-gated Critical decisions are surfaced as open questions, not as recommended critical.
        "n_critical": sum(1 for d in decisions if d["priority"] == "Critical" and d["status"] == "recommended"),
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
        "doctrine": _doctrine_catalog(),
        "target_state": compute_target_state(snap, req, sig=sig),
    }


# ----------------------------------------------------------------------------- design-driven NRFU
# Per-decision NRFU descriptions: what to verify after the decision's recommended action is applied.
# Grounded in Cisco IOS/IOS-XE/NX-OS verification commands; not invented from thin air.
_NRFU_DESC = {
    "fhrp-first-hop-gateway-redundancy":
        "Verify HSRP/VRRP/GLBP or an anycast gateway is configured and active on EVERY gateway VLAN "
        "— no VLAN should have a single active gateway after the migration.",
    "topology-triangles-not-squares-rings":
        "Verify all physical redundant uplinks are ACTIVE (not STP-blocked); confirm multi-chassis LAG "
        "(vPC/VSS/SVL/MLAG) is in service on every dual-homed device pair.",
    "lifecycle-eol-out-of-critical-roles":
        "Verify every past-LDoS device has been replaced with a supported successor and is NOT in the "
        "forwarding path; 'show version' must confirm supported model and active SW contract.",
    "qos-trust-boundary-end-to-end":
        "Verify a QoS trust boundary (DSCP/CoS mark-and-trust) is applied at the access edge on ALL "
        "access switches; confirm class-based forwarding end-to-end — no traffic should be best-effort.",
    "mgmt-secure-protocols-and-rbac":
        "Verify SSHv2 on ALL VTYs (no telnet); SNMPv3 auth/priv configured (no SNMPv1/v2c community "
        "strings in service); AAA/TACACS+/RADIUS configured and server reachable.",
    "security-device-hardening-baseline":
        "Verify CIS/Cisco hardening baseline on all devices: no risky services (TCP small-servers, "
        "finger, BOOTP, MOP); MOTD login banner present; syslog host configured and receiving.",
    "fhrp-not-observed-is-not-healthy":
        "Verify ALL previously-uncollected devices are now reachable, collected, and their roles and "
        "redundancy are documented — 'unreachable' must not be accepted as a healthy state.",
    "dc-restrict-vlan-span-routed-access":
        "Verify each user VLAN is confined to ONE access/distribution block; 'show vlan' on distribution "
        "switches should list only VLANs local to that building/block (no fleet-wide VLAN sprawl).",
    "dc-multichassis-lag-over-stp":
        "Verify NO STP-blocked redundant uplinks remain on any device; 'show etherchannel summary' must "
        "show all bundled ports in P (in-port-channel) state; no uplink in STP Blocking/Discarding.",
    "dc-stp-determinism-edge-protection":
        "Verify rapid-PVST or MST is running on ALL devices ('show spanning-tree summary'); confirm "
        "STP root is pinned at the distribution tier (priority ≤ 4096); PortFast + BPDU Guard on all "
        "edge/access ports ('show spanning-tree interface detail').",
    "igp-link-state-default":
        "Verify a SINGLE IGP (OSPF or EIGRP) carries all prefixes; 'show ip route' must show no "
        "redistribution from a second protocol; 'show ip ospf neighbor'/'show ip eigrp neighbor' shows "
        "Full/UP adjacencies on all routed links.",
    "multicast-security-and-l2-edge":
        "Verify IGMP snooping enabled on all multicast VLANs; 'show ip igmp snooping querier' confirms "
        "a querier on every active multicast VLAN; no unexplained multicast flooding on access links.",
    "mgmt-time-sync-logging-baseline":
        "Verify authenticated NTP is configured and SYNCHRONISED on all devices ('show ntp status' → "
        "clock synchronized); centralised syslog server receives messages from all devices.",
    "qos-voice-priority-bounded":
        "Verify a QoS policy with a BOUNDED LLQ (EF/CS3 class) AND a policer is applied on ALL access "
        "switch interfaces with voice/real-time ports; 'show policy-map interface' confirms the queue.",
    "scenario-build-before-break-phased-cutover":
        "Verify each migration wave was executed build-before-break: target gear operational + NRFU "
        "passed BEFORE the legacy decommission; rollback plan remained available and was NOT invoked; "
        "per-wave NRFU sign-off recorded.",
    "dc-bound-layer2-failure-domain":
        "Verify no user VLAN spans more switches than the approved maximum; 'show mac address-table "
        "count vlan <N>' on each switch should show only local MACs for each bounded VLAN.",
}

_NRFU_PASS = {
    "fhrp-first-hop-gateway-redundancy":
        "'show standby brief' / 'show vrrp brief' / 'show glbp brief' on distribution switches shows "
        "Active + Standby pairs on EVERY gateway VLAN — no VLAN has a single active forwarder.",
    "topology-triangles-not-squares-rings":
        "'show etherchannel summary' shows all uplink bundle members in P state; 'show spanning-tree "
        "active' shows zero Blocking/Discarding uplinks; failover test passes within the SLA window.",
    "lifecycle-eol-out-of-critical-roles":
        "'show version' on every replacement confirms a Cisco model with an active support contract; "
        "no past-LDoS device appears in 'show cdp neighbors' or the management inventory.",
    "qos-trust-boundary-end-to-end":
        "'show policy-map interface <access-port>' shows DSCP trust and class queuing applied; a DSCP "
        "EF-marked packet traverses the campus and exits at the same DSCP value.",
    "mgmt-secure-protocols-and-rbac":
        "'show line vty 0 15' shows only SSH transport; 'show snmp user' shows SNMPv3 auth/priv users "
        "only; 'aaa test' confirms RADIUS/TACACS+ authentication succeeds.",
    "security-device-hardening-baseline":
        "CIS scan or 'show running-config | include service' confirms no risky services; 'show banner "
        "login' shows MOTD; 'show logging' confirms syslog host is configured.",
    "fhrp-not-observed-is-not-healthy":
        "All devices respond to ICMP/SSH and appear in 'show cdp neighbors'; the assessment re-run "
        "collection-completeness.summary.not_collected == 0.",
    "dc-restrict-vlan-span-routed-access":
        "'show vlan brief' on each distribution switch lists ONLY VLANs for that access block; no VLAN "
        "bridges between buildings without an explicit documented justification.",
    "dc-multichassis-lag-over-stp":
        "'show vpc' / 'show etherchannel summary' shows all peer-links active; 'show spanning-tree' "
        "shows zero uplinks in Blocking/Discarding state across the entire fabric.",
    "dc-stp-determinism-edge-protection":
        "'show spanning-tree summary' shows Mode RSTP or MST; 'show spanning-tree root' on all "
        "distribution switches shows they are root for their local VLANs; 'show spanning-tree "
        "interface <edge-port> detail' shows PortFast + BPDU Guard Enabled.",
    "igp-link-state-default":
        "'show ip route summary' shows a single routing protocol prefix; no 'R' (RIP) or dual 'D'+'O' "
        "redistribution; all L3 links show OSPF Full / EIGRP Up adjacencies.",
    "multicast-security-and-l2-edge":
        "'show ip igmp snooping querier' lists a querier IP on every active multicast VLAN; "
        "'show ip igmp snooping groups' shows learnt group memberships (no flood entries).",
    "mgmt-time-sync-logging-baseline":
        "'show ntp associations' shows '*' (synced) stratum; syslog server receives a test log "
        "message from each device within 60 seconds of the 'logging on' verification check.",
    "qos-voice-priority-bounded":
        "'show policy-map interface <voice-port>' shows EF/CS3 class with a bandwidth guarantee AND a "
        "policer rate; MOS score for a test call meets the configured threshold.",
    "scenario-build-before-break-phased-cutover":
        "All per-wave NRFU checklists are signed off and archived; change management system shows "
        "each wave's change request closed with 'implemented successfully'; no emergency rollback "
        "was triggered.",
    "dc-bound-layer2-failure-domain":
        "'show spanning-tree vlan <N> detail' confirms each bounded VLAN bridges across fewer than the "
        "approved maximum number of switches; a synthetic broadcast test stays within the block.",
}

# Phase assignment: where in the cutover sequence this acceptance test runs
_NRFU_PHASE = {
    "fhrp-not-observed-is-not-healthy": "pre-cutover",          # must verify BEFORE wave executes
    "lifecycle-eol-out-of-critical-roles": "pre-cutover",
    "scenario-build-before-break-phased-cutover": "post-cutover-operational",
    "mgmt-time-sync-logging-baseline": "post-cutover-operational",
    "security-device-hardening-baseline": "post-cutover-operational",
    "mgmt-secure-protocols-and-rbac": "post-cutover-operational",
}
_NRFU_PHASE_DEFAULT = "post-cutover-functional"


def compute_design_nrfu(design_blueprint):
    """Bridge the design blueprint to a design-driven NRFU/ATP acceptance test checklist.

    Generates one structured acceptance-test item for every RECOMMENDED design decision in the
    blueprint. Each item is traceable to:
      - the design decision ID (and through it the CCDE principle and the evidence that triggered it)
      - the specific devices the NRFU engineer must verify (from decision.evidence.devices)
      - a human-readable description of what to verify and the concrete pass criteria

    Items are phased into three cutover stages:
      pre-cutover         — must pass BEFORE the wave executes (collection coverage, EoL inventory)
      post-cutover-functional — the core functional acceptance (FHRP, QoS, L2, routing, multicast)
      post-cutover-operational — operational baseline (hardening, time, logging, MOP governance)

    Only RECOMMENDED decisions generate items; needs-requirement decisions are not included (they are
    not testable until the requirement is supplied). Coverage-honest: the count reflects only what the
    assessment observed. The returned structure is deterministic (stable sort by phase priority then ID).
    """
    _PHASE_ORDER = {"pre-cutover": 0, "post-cutover-functional": 1, "post-cutover-operational": 2}
    decs = [d for d in _as_list(design_blueprint.get("decisions"))
            if isinstance(d, dict) and d.get("status") == "recommended"]
    items = []
    for d in decs:
        pid = d.get("id", "")
        phase = _NRFU_PHASE.get(pid, _NRFU_PHASE_DEFAULT)
        items.append({
            "decision_id": pid,
            "title": d.get("title", pid),
            "priority": d.get("priority", "Medium"),
            "phase": phase,
            "description": _NRFU_DESC.get(pid, d.get("recommended_action", d.get("driver", ""))[:400]),
            "pass_criteria": _NRFU_PASS.get(pid,
                "Verify the recommended pattern is operational as described in the design blueprint."),
            "devices": _as_list(_as_dict(d.get("evidence")).get("devices")),
            "principle_citation": _as_dict(d.get("principle")).get("citation", ""),
        })
    items.sort(key=lambda x: (_PHASE_ORDER.get(x["phase"], 9), PRANK.get(x["priority"], 9), x["decision_id"]))
    return {
        "items": items,
        "n_items": len(items),
        "note": (
            f"Design-driven NRFU/ATP checklist: {len(items)} acceptance-test item(s), one per recommended "
            "design decision, each traceable to the CCDE principle and the evidence that triggered it. "
            "Run after each migration wave; the pass/fail verdict for each item is independent of the "
            "design authors (proposer ≠ verifier). Items phased: pre-cutover → post-cutover-functional "
            "→ post-cutover-operational."
        ),
    }
