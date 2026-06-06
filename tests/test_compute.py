"""Unit tests for the intelligence-layer pure functions:
compute_move_groups, compute_cross_layer_correlations, compute_health_scores,
compute_migration_readiness, and compute_protocol_health.

Inputs are constructed directly (not fixture-derived) so each rule/cap/verdict
is exercised in isolation and the assertions are unambiguous.
"""


def _dep(**over):
    """Full dependency-map skeleton with empty defaults; override per test."""
    d = {
        "single_fiber": set(), "uplink_ports": set(), "sole_gw": {},
        "access_by_vlan": {}, "articulation": set(), "fhrp_vlans": set(),
        "tracked_down": set(), "errored_up": set(), "halfdup_up": set(),
        "single_member_pc": set(), "errdis": set(), "gw_switches": set(),
        "orphan": set(), "model": {"hosts": set()},
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# compute_move_groups
# --------------------------------------------------------------------------- #
def test_move_groups_shared_vlan_couples_switches(cp):
    def access(port, vlan):
        d = cp.InterfaceData(port=port)
        d.switchport_mode = "Access"; d.vlan = vlan
        return d

    all_interfaces = {
        "swA": {"Gi0/1": access("Gi0/1", "10"), "Vlan10": cp.InterfaceData(port="Vlan10")},
        "swB": {"Gi0/1": access("Gi0/1", "10")},
        "swC": {"Gi0/1": access("Gi0/1", "99")},  # isolated VLAN -> own group
    }
    groups = cp.compute_move_groups(all_interfaces)
    sets = [set(g["switches"]) for g in groups]
    assert {"swA", "swB"} in sets
    assert {"swC"} in sets


def test_move_groups_excludes_vlan1(cp):
    def access(port, vlan):
        d = cp.InterfaceData(port=port)
        d.switchport_mode = "Access"; d.vlan = vlan
        return d
    # VLAN 1 must NOT couple switches (it would collapse everything into one group)
    all_interfaces = {
        "swA": {"Gi0/1": access("Gi0/1", "1")},
        "swB": {"Gi0/1": access("Gi0/1", "1")},
    }
    groups = cp.compute_move_groups(all_interfaces)
    assert sorted(set(g["switches"][0] for g in groups)) == ["swA", "swB"]
    assert len(groups) == 2


# --------------------------------------------------------------------------- #
# compute_cross_layer_correlations
# --------------------------------------------------------------------------- #
def test_cross_layer_single_fiber_to_sole_gateway(cp):
    dep = _dep(
        sole_gw={30: "core1"},
        access_by_vlan={30: {"access1"}},
        single_fiber={("access1", "Gi0/1")},
        gw_switches={"core1"},
        model={"hosts": {"core1", "access1"}},
    )
    out = cp.compute_cross_layer_correlations(dep)
    by_id = {f["id"]: f for f in out}
    # CL-01: single-fiber uplink fronting a sole gateway = Critical
    assert "CL-01" in by_id and by_id["CL-01"]["severity"] == "Critical"
    assert set(by_id["CL-01"]["hosts"]) >= {"core1", "access1"}
    # CL-03: sole gateway, no FHRP = High
    assert "CL-03" in by_id and by_id["CL-03"]["severity"] == "High"


def test_cross_layer_orphan_vlan(cp):
    dep = _dep(orphan={40}, access_by_vlan={40: {"acc"}}, model={"hosts": {"acc"}})
    out = cp.compute_cross_layer_correlations(dep)
    by_id = {f["id"]: f for f in out}
    assert "CL-10" in by_id and by_id["CL-10"]["severity"] == "Medium"


def test_cross_layer_clean_dep_yields_nothing(cp):
    assert cp.compute_cross_layer_correlations(_dep()) == []


# --------------------------------------------------------------------------- #
# compute_health_scores
# --------------------------------------------------------------------------- #
def test_health_clean_host_is_perfect(cp):
    recs = cp.compute_health_scores({"clean": {}}, [], [], [], [])
    assert recs == [{"switch": "clean", "score": 100, "band": "Excellent",
                     "role": "access", "criticality": 1.0, "deductions": []}]


def test_health_l1_category_is_capped(cp):
    # 5 err-disabled ports * 8 = 40, but L1 cap is 30 -> score 70 (Fair), not 60.
    ph = [{"switch": "h", "port": f"Gi0/{i}", "risk": "err-disabled"} for i in range(5)]
    recs = cp.compute_health_scores({"h": {}}, ph, [], [], [])
    assert recs[0]["score"] == 70
    assert recs[0]["band"] == "Fair"


def test_health_cross_layer_critical_weight(cp):
    xl = [{"id": "CL-01", "severity": "Critical", "hosts": ["h"]}]
    recs = cp.compute_health_scores({"h": {}}, [], [], xl, [])
    assert recs[0]["score"] == 82          # 100 - 18
    assert recs[0]["band"] == "Good"


def test_health_scores_spread_across_bands(cp):
    all_if = {"good": {}, "mid": {}, "bad": {}}
    ph = [{"switch": "mid", "port": "Gi0/1", "risk": "single-fiber-uplink"}]   # -10
    l3 = [{"switch": "bad", "vlan": 30, "risk": "single-gateway"}]             # -10
    xl = [{"id": "CL-09", "severity": "Critical", "hosts": ["bad"]},           # -18
          {"id": "CL-01", "severity": "Critical", "hosts": ["bad"]}]           # -18 (XL cap 45)
    pr = [{"switch": "mid", "protocol": "VTP", "severity": "Medium"},          # -4  -> mid 86 (Good)
          {"switch": "bad", "protocol": "OSPF", "severity": "High"}]           # -10
    recs = {r["switch"]: r for r in cp.compute_health_scores(all_if, ph, l3, xl, pr)}
    assert recs["good"]["band"] == "Excellent"      # 100
    assert recs["mid"]["band"] == "Good"            # 100-14 = 86
    assert recs["bad"]["band"] == "Poor"            # 100-(10+36+10) = 44
    bands = {r["band"] for r in recs.values()}
    assert len(bands) == 3                           # genuine spread, not all-Critical


def test_health_security_deductions_capped(cp):
    # NEW-V3.23.60: a FAILED CIS config-hardening check deducts via sec_weights (high 8 / med 3 / low 1);
    # pass/info/na are ignored. {"h": {}} has no SVI -> access role (x1.0), so no criticality scaling.
    sec = {"h": {"findings": [
        {"id": "telnet-enabled", "severity": "high", "status": "fail"},       # -8
        {"id": "insecure-snmp", "severity": "high", "status": "fail"},        # -8
        {"id": "no-ntp", "severity": "low", "status": "fail"},                # -1
        {"id": "password-encryption", "severity": "info", "status": "pass"},  # ignored
    ]}}
    base = cp.compute_health_scores({"h": {}}, [], [], [], [])[0]["score"]
    withsec = cp.compute_health_scores({"h": {}}, [], [], [], [], security=sec)[0]["score"]
    assert base == 100 and withsec == 100 - (8 + 8 + 1)                       # only fails count


def test_health_security_missing_data_not_penalized(cp):
    # a host with no captured run-config (absent from the security dict) gets NO SEC deduction --
    # missing posture must never be scored as 'bad' (distinct from present-and-hardened).
    recs = cp.compute_health_scores({"x": {}}, [], [], [], [], security={})
    assert recs[0]["score"] == 100


def test_health_security_category_capped(cp):
    # SEC is capped at 18: six high-severity fails (6 * 8 = 48) deduct only -18.
    sec = {"h": {"findings": [{"id": f"c{i}", "severity": "high", "status": "fail"} for i in range(6)]}}
    rec = cp.compute_health_scores({"h": {}}, [], [], [], [], security=sec)[0]
    assert rec["score"] == 100 - 18


def test_score_sensitivity_sweeps_security_group(cp):
    sec = {"h": {"findings": [{"id": "telnet-enabled", "severity": "high", "status": "fail"}]}}
    rows = cp.compute_score_sensitivity({"h": {}}, [], [], [], [], security=sec)
    assert any(r["group"] == "sec_weights" for r in rows)


def test_stp_root_findings(cp):
    # VLAN30 is rooted on the default priority (32768+30) AND on a switch (acc1) that doesn't host its
    # gateway (core1 does) -> accidental + misaligned. VLAN10's root (core1) is deliberate + hosts the gateway.
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData
    stp = {"core1": {"10": {"is_root": True, "root_priority": 24586},
                     "30": {"is_root": False, "root_priority": 32798}},
           "acc1":  {"10": {"is_root": False, "root_priority": 24586},
                     "30": {"is_root": True, "root_priority": 32798}}}
    ifaces = {"core1": {"Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1"),
                        "Vlan30": InterfaceData(port="Vlan30", svi_ip="10.0.30.1")},
              "acc1": {}}
    f = analyze.stp_root_findings(stp, ifaces)
    assert any(a["vlan"] == "30" and a["host"] == "acc1" for a in f["accidental"])   # default-priority root
    assert not any(a["vlan"] == "10" for a in f["accidental"])                       # 24586 is deliberate
    assert any(m["vlan"] == "30" and m["root"] == "acc1" and "core1" in m["gateways"]
               for m in f["misaligned"])                                             # root acc1 != gateway core1
    assert not any(m["vlan"] == "10" for m in f["misaligned"])                       # root core1 hosts the gateway


def test_compute_migration_punchlist(cp):
    # the consolidated roll-up pulls from every source, ranks Critical->Low, tags the wave, and
    # excludes non-fail security findings.
    from cisco_toolkit import analyze
    cross_layer = [{"severity": "Critical", "hosts": ["a"], "id": "CL-01", "title": "stacked SPOF", "detail": "x"}]
    security = {"a": {"findings": [
        {"id": "telnet-enabled", "severity": "high", "status": "fail",
         "title": "VTY telnet", "detail": "y", "remediation": "ssh"},
        {"id": "no-ntp", "severity": "low", "status": "pass"}]}}
    hygiene = {"a": {"undefined": [{"kind": "acl", "name": "7", "context": "nat list 7"}], "unused": []}}
    physical = [{"switch": "a", "risk": "err-disabled"}]
    l3 = [{"switch": "b", "risk": "single-gateway"}]
    proto = [{"switch": "a", "protocol": "OSPF", "severity": "High", "detail": "stuck"}]
    stp = {"accidental": [{"vlan": "30", "host": "b"}],
           "misaligned": [{"vlan": "30", "root": "b", "gateways": ["a"]}]}
    health = [{"switch": "b", "band": "Critical", "score": 20}]
    groups = [{"group": "Wave 1", "switches": ["a", "b"]}]
    pl = analyze.compute_migration_punchlist(cross_layer, security, hygiene, physical, l3,
                                             proto, stp, health, groups)
    cats = {i["category"] for i in pl}
    assert {"Cross-layer", "Security", "Config hygiene", "L1", "L3", "Protocol", "STP", "Health"} <= cats
    assert pl[0]["severity"] == "Critical" and pl[0]["priority"] == 1                 # ranked, 1-based
    assert [i["rank"] for i in pl] == sorted((i["rank"] for i in pl), reverse=True)   # Critical -> Low
    assert not any("no-ntp" in (i.get("title") or "") for i in pl)                    # pass findings excluded
    assert all(i["wave"] == "Wave 1" for i in pl)                                     # tagged from the move-group
    t = [i for i in pl if i["category"] == "Security" and "VTY" in i["title"]][0]
    assert t["remediation"] == "ssh" and t["severity"] == "High"
    # V3.23.64: the cross-switch L2 checks fold in via the `l2` arg (addressing / FHRP / trunk / link)
    l2 = {"addressing": {"dup_ip": [{"ip": "10.0.0.1", "where": [("a", "Vlan10", 10), ("b", "Vlan20", 20)]}],
                         "dup_subnet": []},
          "fhrp": [{"vid": 20, "issues": ["different FHRP groups"], "members": [{"host": "a"}, {"host": "b"}]}],
          "trunk_native": [{"a_host": "a", "a_port": "Gi0/1", "a_native": "1",
                            "b_host": "b", "b_port": "Gi0/2", "b_native": "99"}],
          "link_phy": [{"a_host": "a", "a_port": "Gi0/3", "b_host": "b", "b_port": "Gi0/4",
                        "duplex": ("full", "half"), "speed": None}]}
    pl2 = analyze.compute_migration_punchlist(cross_layer, security, hygiene, physical, l3, proto,
                                              stp, health, groups, l2=l2)
    assert {"Addressing", "FHRP", "Trunk", "Link L1"} <= {i["category"] for i in pl2}
    assert len(pl2) == len(pl) + 4                                                    # exactly the 4 L2 items added
    assert all(i["wave"] == "Wave 1" for i in pl2 if i["category"] in ("Addressing", "FHRP", "Trunk", "Link L1"))
    # V3.23.68: inventory-name vs configured-hostname mismatches fold in via hostname_mismatches
    pl3 = analyze.compute_migration_punchlist(cross_layer, security, hygiene, physical, l3, proto,
                                              stp, health, groups,
                                              hostname_mismatches=[{"inventory": "a", "reported": "a-real"}])
    inv = [i for i in pl3 if i["category"] == "Inventory"]
    assert len(inv) == 1 and inv[0]["severity"] == "Medium"
    assert "a-real" in inv[0]["title"] and inv[0]["wave"] == "Wave 1"   # device 'a' is in Wave 1


def test_compute_hostname_mismatches(cp):
    from cisco_toolkit import analyze
    DP = analyze.DevicePhysical
    devs = [
        DP(hostname="AS01-BC", reported_hostname="AS01-BC"),                  # match -> no finding
        DP(hostname="AS08--BC-CR03R13", reported_hostname="AS08-BC-CR03R13"), # double-dash typo -> finding
        DP(hostname="CORE1", reported_hostname="core1.example.com"),          # FQDN/case -> canon-equal, no finding
        DP(hostname="AS09", reported_hostname=""),                            # unknown reported -> skipped
    ]
    out = analyze.compute_hostname_mismatches(devs)
    assert len(out) == 1
    assert out[0] == {"inventory": "AS08--BC-CR03R13", "reported": "AS08-BC-CR03R13"}


# --------------------------------------------------------------------------- #
# write_executive_summary_sheet (V3.23.75) — one-page landing synthesis
# --------------------------------------------------------------------------- #
def test_executive_summary_sheet_is_first_and_synthesizes(cp):
    from openpyxl import Workbook
    health_scores = [
        {"switch": "GW-CORE", "score": 0, "band": "Critical"},
        {"switch": "ACC1", "score": 80, "band": "Good"},
        {"switch": "ACC2", "score": 55, "band": "Fair"},
    ]
    punchlist = [
        {"severity": "Critical", "category": "Cross-layer", "devices": ["GW-CORE"]},
        {"severity": "High", "category": "FHRP", "devices": ["GW-CORE"]},
        {"severity": "Medium", "category": "STP", "devices": ["ACC1"]},
    ]
    migration_readiness = [{"group": "Group 1", "readiness": "NOT READY",
                            "switches": ["GW-CORE", "ACC1", "ACC2"], "endpoints": 2,
                            "n_fail": 1, "n_warn": 1}]
    wb = Workbook(); wb.active.title = "Pre-Existing"   # prove our sheet lands ahead of it
    cp.write_executive_summary_sheet(wb, health_scores, punchlist, migration_readiness, {})
    assert wb.sheetnames[0] == "Executive Summary"      # moved to the FRONT of the workbook
    ws = wb["Executive Summary"]
    text = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    # the four synthesis sections + the consumed inputs are all present
    for needle in ("Executive Summary", "Fleet posture", "Migration punch-list",
                   "Keystone devices", "Where to start", "Cross-layer", "Group 1"):
        assert needle in text, needle
    assert "3" in text   # 3 switches assessed / 3 punch-list items


# --------------------------------------------------------------------------- #
# compute_migration_readiness
# --------------------------------------------------------------------------- #
def test_readiness_not_ready_on_hard_fails(cp):
    move_groups = [{"switches": ["a", "b"], "endpoints": 3}]
    health = [{"switch": "a", "band": "Critical"}, {"switch": "b", "band": "Excellent"}]
    dep = _dep(sole_gw={30: "a"}, model={"hosts": {"a", "b"}})
    xl = [{"id": "CL-01", "severity": "Critical", "hosts": ["a"]}]
    pr = [{"switch": "a", "protocol": "OSPF", "severity": "High"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], xl, pr, dep)
    assert out[0]["readiness"] == "NOT READY"
    assert out[0]["n_fail"] >= 1


def test_readiness_ready_when_clean(cp):
    move_groups = [{"switches": ["c"], "endpoints": 0}]
    health = [{"switch": "c", "band": "Excellent"}]
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], _dep())
    assert out[0]["readiness"] == "READY"
    assert out[0]["n_fail"] == 0 and out[0]["n_warn"] == 0


def test_readiness_caution_on_warn_only(cp):
    # single-fiber uplink is a WARN (not a fail) -> CAUTION
    move_groups = [{"switches": ["a"], "endpoints": 1}]
    health = [{"switch": "a", "band": "Good"}]
    dep = _dep(single_fiber={("a", "Gi0/1")}, model={"hosts": {"a"}})
    out = cp.compute_migration_readiness({}, move_groups, health, [], [], [], [], dep)
    assert out[0]["readiness"] == "CAUTION"


# --------------------------------------------------------------------------- #
# compute_protocol_health (integration on the synthetic fixtures)
# --------------------------------------------------------------------------- #
def test_protocol_health_flags_down_ospf(cp, built):
    all_interfaces, all_cmd_to_files = built
    recs = cp.compute_protocol_health(all_interfaces, all_cmd_to_files)
    ospf = [r for r in recs if r["switch"] == "core1" and r["protocol"] == "OSPF"]
    assert ospf and ospf[0]["severity"] == "High"
    # core2 has no OSPF neighbors collected -> no OSPF row
    assert not [r for r in recs if r["switch"] == "core2" and r["protocol"] == "OSPF"]


# --------------------------------------------------------------------------- #
# Route-aware reachability: scope_routes / inscope_subnets (build-layer helpers)
# --------------------------------------------------------------------------- #
def test_scope_routes_keeps_relevant_drops_noise():
    from cisco_toolkit.build import scope_routes
    inscope = {"10.0.10.0/24", "10.0.20.0/24"}
    route_db = {
        "0.0.0.0/0":       {"entries": [{"prefix": "0.0.0.0/0",       "source": "static",    "next_hop": "10.0.0.254",  "out_intf": ""}]},
        "10.0.0.0/16":     {"entries": [{"prefix": "10.0.0.0/16",     "source": "static",    "next_hop": "10.0.30.254", "out_intf": ""}]},
        "10.0.10.0/24":    {"entries": [{"prefix": "10.0.10.0/24",    "source": "connected", "next_hop": "",            "out_intf": "Vlan10"}]},
        "10.0.10.2/32":    {"entries": [{"prefix": "10.0.10.2/32",    "source": "local",     "next_hop": "",            "out_intf": "Vlan10"}]},
        "192.168.99.0/24": {"entries": [{"prefix": "192.168.99.0/24", "source": "static",    "next_hop": "10.0.10.254", "out_intf": ""}]},
    }
    got = {r["prefix"] for r in scope_routes(route_db, inscope)}
    assert "0.0.0.0/0" in got           # default route is always relevant
    assert "10.0.0.0/16" in got         # supernet that covers an in-scope subnet
    assert "10.0.10.0/24" in got        # connected in-scope subnet (covers itself)
    assert "10.0.10.2/32" not in got    # host (/32 local) noise dropped
    assert "192.168.99.0/24" not in got # out-of-scope prefix dropped


def test_inscope_subnets_from_svis():
    from cisco_toolkit.build import inscope_subnets
    from cisco_toolkit.model import InterfaceData
    ifaces = {"sw1": {
        "Vlan10":  InterfaceData(port="Vlan10",  svi_ip="10.0.10.1 255.255.255.0"),
        "Vlan20":  InterfaceData(port="Vlan20",  svi_ip="10.0.20.1 255.255.255.0"),
        "Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan="10"),   # access port, not an SVI -> ignored
    }}
    assert inscope_subnets(ifaces) == {"10.0.10.0/24", "10.0.20.0/24"}


def test_protocol_boundaries_sheet():
    # workbook surfacing of the protocol-to-protocol analysis: per device protocols + redistribution edges,
    # with a MUTUAL-redistribution risk flag (ospf<->bgp both ways).
    from openpyxl import Workbook
    from cisco_toolkit.excel import write_protocol_boundaries_sheet, PROTOCOL_BOUNDARIES_SHEET_NAME
    wb = Workbook()
    rn = {"core1": {"ospf": [{"neighbor": "1.1.1.1", "state": "FULL"}], "eigrp": [], "bgp": []}}
    rd = {"core1": [
        {"into_proto": "ospf", "into_id": "1", "from_proto": "bgp", "from_id": "65001", "route_map": "", "raw": ""},
        {"into_proto": "bgp", "into_id": "65001", "from_proto": "ospf", "from_id": "1", "route_map": "RM", "raw": ""},
    ]}
    write_protocol_boundaries_sheet(wb, rn, rd)
    ws = wb[PROTOCOL_BOUNDARIES_SHEET_NAME]
    assert [c.value for c in ws[1]] == ["Switch", "Protocols", "Redistribution (from -> into)", "Route-map(s)", "Mutual"]
    row = [c.value for c in ws[2]]
    assert row[0] == "core1"
    assert "OSPF" in row[1] and "BGP" in row[1]
    assert row[3] == "RM"
    assert row[4] == "BGP/OSPF"   # two-way ospf<->bgp -> mutual-redistribution risk flagged


def test_compute_addressing_conflicts():
    # workbook surfacing of the addressing-integrity finding: duplicate IP + overlapping subnet (same VRF),
    # while a cross-VRF overlap and a normal FHRP pair (same VLAN, different IPs) are NOT flagged.
    from cisco_toolkit.excel import compute_addressing_conflicts
    from cisco_toolkit.model import InterfaceData
    ifaces = {
        "sw1": {
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.2 255.255.255.0"),
            "Vlan99": InterfaceData(port="Vlan99", svi_ip="10.0.99.2 255.255.255.0"),   # dup IP with sw2 Vlan99
            "Vlan50": InterfaceData(port="Vlan50", svi_ip="10.0.77.1 255.255.255.0"),   # overlap w/ Vlan51 (same VRF)
            "Vlan51": InterfaceData(port="Vlan51", svi_ip="10.0.77.2 255.255.255.0"),
            "Vlan60": InterfaceData(port="Vlan60", svi_ip="10.0.88.1 255.255.255.0", vrf="RED"),   # cross-VRF overlap -> NOT flagged
            "Vlan61": InterfaceData(port="Vlan61", svi_ip="10.0.88.2 255.255.255.0", vrf="BLUE"),
        },
        "sw2": {
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.3 255.255.255.0"),   # FHRP pair (same VLAN, diff IP) -> NOT flagged
            "Vlan99": InterfaceData(port="Vlan99", svi_ip="10.0.99.2 255.255.255.0"),
        },
    }
    c = compute_addressing_conflicts(ifaces)
    dup_ips = {d["ip"] for d in c["dup_ip"]}
    overlaps = {d["net"] for d in c["dup_subnet"]}
    assert dup_ips == {"10.0.99.2"}                 # same physical IP on sw1+sw2 Vlan99
    assert overlaps == {"10.0.77.0/24"}             # two VLANs share a subnet in the same VRF
    assert "10.0.88.0/24" not in overlaps           # same subnet but different VRFs -> intentional, not flagged


def test_compute_fhrp_consistency():
    # workbook surfacing of the FHRP finding: a different-group VLAN flagged; a consistent VLAN not flagged.
    from cisco_toolkit.excel import compute_fhrp_consistency
    from cisco_toolkit.model import InterfaceData
    ifaces = {
        "core1": {
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.2 255.255.255.0", hsrp_behavior="HSRP grp 10 Active VIP 10.0.10.1"),
            "Vlan20": InterfaceData(port="Vlan20", svi_ip="10.0.20.2 255.255.255.0", hsrp_behavior="HSRP grp 20 Active VIP 10.0.20.1"),
        },
        "core2": {
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.3 255.255.255.0", hsrp_behavior="HSRP grp 10 Standby VIP 10.0.10.1"),
            "Vlan20": InterfaceData(port="Vlan20", svi_ip="10.0.20.3 255.255.255.0", hsrp_behavior="HSRP grp 21 Standby VIP 10.0.20.1"),  # wrong group
        },
    }
    rows = compute_fhrp_consistency(ifaces)
    flagged = {r["vid"] for r in rows}
    assert 20 in flagged and 10 not in flagged          # VLAN 20 grp 20 vs 21 -> flagged; VLAN 10 consistent
    v20 = [r for r in rows if r["vid"] == 20][0]
    assert any("different FHRP groups" in i for i in v20["issues"])


def test_compute_trunk_native_mismatches():
    # workbook surfacing of the trunk native-VLAN finding: a CDP link whose two ends disagree on native VLAN.
    from cisco_toolkit.excel import compute_trunk_native_mismatches
    from cisco_toolkit.model import InterfaceData
    ifaces = {
        "core1": {"Po1": InterfaceData(port="Po1", cdp_neighbor="core2", neighbor_port="Po1",
                                       switchport_mode="Trunk", trunk_native_vlan="99")},   # native 99…
        "core2": {"Po1": InterfaceData(port="Po1", cdp_neighbor="core1", neighbor_port="Po1",
                                       switchport_mode="Trunk")},                            # …vs default 1
    }
    rows = compute_trunk_native_mismatches(ifaces)
    assert len(rows) == 1
    assert {rows[0]["a_native"], rows[0]["b_native"]} == {"99", "1"}   # explicit-on-one-end still a mismatch


def test_compute_duplex_speed_mismatches():
    # workbook surfacing of the link L1 finding: a CDP link whose two ends report a different duplex.
    from cisco_toolkit.excel import compute_duplex_speed_mismatches
    from cisco_toolkit.model import InterfaceData
    ifaces = {
        "core1": {"Gi1/0/1": InterfaceData(port="Gi1/0/1", cdp_neighbor="acc1", neighbor_port="Gi0/1",
                                           switchport_mode="Trunk", duplex="Full-duplex", speed="1000Mb/s")},
        "acc1": {"Gi0/1": InterfaceData(port="Gi0/1", cdp_neighbor="core1", neighbor_port="Gi1/0/1",
                                        switchport_mode="Trunk", duplex="Half-duplex", speed="1000Mb/s")},
    }
    rows = compute_duplex_speed_mismatches(ifaces)
    assert len(rows) == 1
    assert rows[0]["duplex"] is not None and set(rows[0]["duplex"]) == {"full", "half"}
    assert rows[0]["speed"] is None        # same speed -> no false speed flag


def test_build_routing_neighbors(tmp_path):
    # protocol-to-protocol analysis: OSPF/EIGRP/BGP adjacencies parsed from already-collected output,
    # keeping the full state token so the explorer can tell a healthy (FULL) from a stuck (EXSTART) peer.
    from cisco_toolkit.build import build_routing_neighbors
    ospf = tmp_path / "ospf.txt"
    ospf.write_text(
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        "10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1\n"
        "10.0.99.9         1   EXSTART/DROTHER 00:00:31    10.0.40.9       Vlan40\n",
        encoding="utf-8")
    rn = build_routing_neighbors({"show ip ospf neighbor": str(ospf)})
    assert len(rn["ospf"]) == 2
    states = {n["state"] for n in rn["ospf"]}
    assert "FULL/DR" in states and "EXSTART/DROTHER" in states   # healthy + stuck adjacency both captured
    assert rn["eigrp"] == [] and rn["bgp"] == []                 # protocols not running -> empty list, never absent


# --------------------------------------------------------------------------- #
# Scoring calibration: compute_calibration_report (fleet band-discrimination)
# --------------------------------------------------------------------------- #
def test_calibration_report_flags_poor_discrimination():
    from cisco_toolkit.analyze import compute_calibration_report
    # 10 switches all banded 'Good' -> the bands don't discriminate -> poor + a re-banding suggestion
    hs = [{"switch": f"sw{i}", "score": 76 + (i % 5), "band": "Good"} for i in range(10)]
    rep = compute_calibration_report(hs)
    assert rep["n"] == 10
    assert rep["modal_band"] == "Good" and rep["modal_pct"] == 100
    assert rep["discrimination"] == 0.0                 # all one band -> zero entropy
    assert rep["discrimination_quality"] == "poor"
    assert rep["suggested_bands"] is not None
    assert rep["suggested_bands"][-1]["threshold"] == 0  # bottom band always floors at 0
    assert all(0 <= s["threshold"] <= 100 for s in rep["suggested_bands"])


def test_calibration_report_good_discrimination_excludes_insufficient_data():
    from cisco_toolkit.analyze import compute_calibration_report
    # one switch per band -> well spread; the 'Insufficient Data' switch must be excluded from stats
    hs = [{"switch": "a", "score": 95, "band": "Excellent"},
          {"switch": "b", "score": 80, "band": "Good"},
          {"switch": "c", "score": 65, "band": "Fair"},
          {"switch": "d", "score": 45, "band": "Poor"},
          {"switch": "e", "score": 20, "band": "Critical"},
          {"switch": "f", "score": 88, "band": "Insufficient Data", "data_quality": 0.3}]
    rep = compute_calibration_report(hs)
    assert rep["n"] == 5                                 # Insufficient-Data switch excluded
    assert rep["discrimination"] == 1.0                  # uniform across all 5 bands -> max entropy
    assert rep["discrimination_quality"] == "good"
    assert rep["suggested_bands"] is None                # good discrimination -> no re-banding offered


def test_calibration_report_empty():
    from cisco_toolkit.analyze import compute_calibration_report
    rep = compute_calibration_report([])
    assert rep["n"] == 0 and rep["suggested_bands"] is None


def test_link_centrality_bridge_and_betweenness():
    """A hangs off B; B-C-D form a triangle (redundant). A-B is the only bridge; its betweenness
    (serves A-B, A-C, A-D = 3 pairs) is highest, and removing it severs {A} from {B,C,D} = 3 pairs.
    The triangle links are NOT bridges (each pair has an alternate equal path)."""
    from cisco_toolkit.model import InterfaceData
    from cisco_toolkit.analyze import compute_link_centrality

    def sw(*links):
        return {p: InterfaceData(port=p, cdp_neighbor=nb, neighbor_port=npt, endpoint_type="Switch")
                for (p, nb, npt) in links}

    ai = {
        "A": sw(("Gi0/1", "B", "Gi0/1")),
        "B": sw(("Gi0/1", "A", "Gi0/1"), ("Gi0/2", "C", "Gi0/1"), ("Gi0/3", "D", "Gi0/2")),
        "C": sw(("Gi0/1", "B", "Gi0/2"), ("Gi0/2", "D", "Gi0/1")),
        "D": sw(("Gi0/1", "C", "Gi0/2"), ("Gi0/2", "B", "Gi0/3")),
    }
    recs = compute_link_centrality(ai)
    by = {frozenset((r["a_host"], r["b_host"])): r for r in recs}
    ab = by[frozenset(("A", "B"))]
    assert ab["is_bridge"] is True
    assert ab["pairs_cut"] == 3            # {A} vs {B,C,D}
    assert ab["betweenness"] == 3.0        # on the shortest path of A-B, A-C, A-D
    assert ab["rank"] == 1                 # highest betweenness
    assert by[frozenset(("C", "D"))]["is_bridge"] is False   # triangle edge is redundant
    assert sum(1 for r in recs if r["is_bridge"]) == 1       # exactly one bridge


def test_link_centrality_empty_when_no_links():
    from cisco_toolkit.model import InterfaceData
    from cisco_toolkit.analyze import compute_link_centrality
    assert compute_link_centrality({"lonely": {"Gi0/1": InterfaceData(port="Gi0/1")}}) == []


def test_wave_sequencing_classifies_cutover():
    """A dual-homed switch (>=2 uplinks) is make-before-break; a single-homed switch (1 uplink) is a hard
    cutover, and its endpoints are counted as at-risk during the window."""
    from cisco_toolkit.model import InterfaceData
    from cisco_toolkit.analyze import compute_wave_sequencing

    def link(p, nb, npt):
        return InterfaceData(port=p, cdp_neighbor=nb, neighbor_port=npt, endpoint_type="Switch")

    def ep(p, mac):
        return InterfaceData(port=p, switchport_mode="Access", vlan="10", end_host_mac=mac)

    ai = {
        "DIST1": {"Gi0/1": link("Gi0/1", "ACC1", "Gi0/24"), "Gi0/2": link("Gi0/2", "ACC2", "Gi0/24")},
        "ACC1": {"Gi0/24": link("Gi0/24", "DIST1", "Gi0/1"),
                 "Gi0/1": ep("Gi0/1", "aaaa.0000.0001"), "Gi0/2": ep("Gi0/2", "aaaa.0000.0002")},
        "ACC2": {"Gi0/24": link("Gi0/24", "DIST1", "Gi0/2"), "Gi0/1": ep("Gi0/1", "aaaa.0000.0003")},
    }
    seq = compute_wave_sequencing(ai, [{"switches": ["ACC1", "ACC2", "DIST1"]}])[0]
    assert seq["make_before_break"] == ["DIST1"]          # degree 2 -> dual-homed
    assert seq["hard_cutover"] == ["ACC1", "ACC2"]        # degree 1 -> single-homed
    assert seq["hard_cutover_endpoints"] == 3             # 2 on ACC1 + 1 on ACC2
