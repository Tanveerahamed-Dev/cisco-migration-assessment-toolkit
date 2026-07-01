"""NEW-V3.23.143: cutover validation / test-plan generator. Pins the per-category checks (gateway / FHRP /
reachability / routing / STP / port-channel), the platform-specific command dialect, the wave assignment,
and empty-input tolerance. Each item carries the EXPECTED good result captured from the pre-cutover state."""
from cisco_toolkit.analyze import compute_validation_plan
from cisco_toolkit.model import InterfaceData


def _svi(key, ip="", fhrp=""):
    return InterfaceData(port=key, svi_ip=ip, hsrp_behavior=fhrp)


def _access(port, vlan, mac="aa.bb.cc.dd.ee.01"):
    return InterfaceData(port=port, switchport_mode="Access", vlan=vlan, end_host_mac=mac)


def _trunk(port, nb, npt, fwd="10,20", pc=""):
    return InterfaceData(port=port, cdp_neighbor=nb, neighbor_port=npt, stp_fwd_vlans=fwd, port_channel=pc)


# A small redundant-gateway fabric: distA + distB are an FHRP pair for VLAN 10; acc1 is a client edge.
def _fabric():
    return {
        "distA": {"Vlan10": _svi("Vlan10", ip="10.0.10.1", fhrp="HSRP grp10 active vIP 10.0.10.254"),
                  "Vlan20": _svi("Vlan20", ip="10.0.20.1"),
                  "Gi1/0/1": _trunk("Gi1/0/1", "distB", "Gi1/0/1"),
                  "Gi1/0/2": _trunk("Gi1/0/2", "acc1", "Gi1/0/24")},
        "distB": {"Vlan10": _svi("Vlan10", ip="10.0.10.2", fhrp="HSRP grp10 standby vIP 10.0.10.254"),
                  "Gi1/0/1": _trunk("Gi1/0/1", "distA", "Gi1/0/1")},
        "acc1": {"Gi1/0/24": _trunk("Gi1/0/24", "distA", "Gi1/0/2", pc="Po1"),
                 "Gi1/0/5": _access("Gi1/0/5", "10")},
    }


def _ctx():
    move_groups = [{"switches": ["acc1", "distA", "distB"]}]
    routing_neighbors = {"distA": {"ospf": [{"neighbor": "10.0.0.2", "state": "FULL"}], "eigrp": [], "bgp": []}}
    stp_roots = {"distA": {"10": {"is_root": True, "root_priority": "24576"}}}
    devices = {"distA": {"platform": "ios"}, "distB": {"platform": "nxos"}, "acc1": {"platform": "ios"}}
    return move_groups, routing_neighbors, stp_roots, devices


def _items(out, **match):
    return [it for it in out["items"]
            if all(it.get(k) == v for k, v in match.items())]


def test_gateway_and_reachability_checks():
    mg, rn, stp, devs = _ctx()
    out = compute_validation_plan(_fabric(), mg, rn, stp, devs)
    # Gateway-up check per SVI, with the SVI IP baked into the expected result.
    gw = _items(out, category="Gateway", device="distA")
    assert any("VLAN 10" in it["check"] and "10.0.10.1" in it["expect"] for it in gw)
    assert any("VLAN 20" in it["check"] for it in gw)            # IP-only SVI still gets a gateway check
    # Reachability ping from the client edge (acc1), targeting a gateway SVI IP, expecting 100% success.
    reach = _items(out, category="Reachability")
    assert reach and reach[0]["device"] == "acc1"
    assert reach[0]["command"].startswith("ping 10.0.10.")
    assert "100 percent" in reach[0]["expect"]


def test_fhrp_check_is_platform_specific():
    mg, rn, stp, devs = _ctx()
    out = compute_validation_plan(_fabric(), mg, rn, stp, devs)
    fhrp = {it["device"]: it for it in _items(out, category="FHRP")}
    assert set(fhrp) == {"distA", "distB"}                       # both peers of the redundant VLAN 10
    assert fhrp["distA"]["command"] == "show standby brief"      # IOS dialect
    assert fhrp["distB"]["command"] == "show hsrp brief"         # NX-OS dialect
    assert "Active" in fhrp["distA"]["expect"] and "Standby" in fhrp["distA"]["expect"]


def test_routing_stp_and_portchannel_checks():
    mg, rn, stp, devs = _ctx()
    out = compute_validation_plan(_fabric(), mg, rn, stp, devs)
    rt = _items(out, category="Routing", device="distA")
    assert rt and rt[0]["command"] == "show ip ospf neighbor" and "10.0.0.2" in rt[0]["expect"]
    st = _items(out, category="STP", device="distA")
    assert st and "VLAN 10" in st[0]["check"] and "root" in st[0]["expect"].lower()
    pc = _items(out, category="Link", device="acc1")
    assert pc and pc[0]["command"] == "show etherchannel summary" and "Po1" in pc[0]["expect"]


def test_waves_and_summary():
    mg, rn, stp, devs = _ctx()
    out = compute_validation_plan(_fabric(), mg, rn, stp, devs)
    assert all(it["wave"] == "Group 1" for it in out["items"])
    assert set(out["by_wave"]) == {"Group 1"}
    s = out["summary"]
    assert s["n_items"] == len(out["items"]) and s["n_waves"] == 1
    assert s["n_high"] >= 1 and "Gateway" in s["by_category"]
    assert out["banner"]


def test_portchannel_check_discloses_a_pre_existing_down_member():
    """[audit-5 NRFU #18] The port-channel NRFU baseline must not assert 'all members in (P)/bundled' when a
    member is ALREADY down/suspended pre-cutover -- that bakes a degraded bundle into the accepted good state, so
    the post-cutover ATP would certify a broken uplink as healthy. When protocol_health (the EtherChannel SSOT)
    reports a non-Info bundle for the host, the expect string discloses the bad member(s) and the check is High."""
    mg, rn, stp, devs = _ctx()
    ph = [{"switch": "acc1", "protocol": "EtherChannel", "severity": "High",
           "summary": "1 bundle(s), 2 member(s); 1 not bundled", "detail": "Gi1/0/25(D)"}]
    out = compute_validation_plan(_fabric(), mg, rn, stp, devs, protocol_health=ph)
    pc = _items(out, category="Link", device="acc1")
    assert pc, "port-channel check still present"
    expect = pc[0]["expect"]
    assert "Gi1/0/25(D)" in expect or "not bundled" in expect.lower()   # discloses the degraded baseline
    assert "all members in (P)" not in expect                           # NOT the false-healthy assertion
    assert pc[0]["severity"] == "High"                                  # a degraded baseline is High, not a clean Medium
    # control: with no protocol_health (or a healthy bundle) the optimistic all-(P) assertion is unchanged.
    out2 = compute_validation_plan(_fabric(), mg, rn, stp, devs)
    pc2 = _items(out2, category="Link", device="acc1")
    assert "all members in (P)" in pc2[0]["expect"] and pc2[0]["severity"] == "Medium"
    healthy = [{"switch": "acc1", "protocol": "EtherChannel", "severity": "Info", "summary": "1 bundle(s), 2 member(s)", "detail": ""}]
    out3 = compute_validation_plan(_fabric(), mg, rn, stp, devs, protocol_health=healthy)
    pc3 = _items(out3, category="Link", device="acc1")
    assert "all members in (P)" in pc3[0]["expect"] and pc3[0]["severity"] == "Medium"


def test_empty_inputs_are_tolerated():
    out = compute_validation_plan({})
    assert out["items"] == [] and out["by_wave"] == {}
    assert out["summary"]["n_items"] == 0
    # protocol_health is optional and a malformed value must be tolerated, never raise
    assert compute_validation_plan({}, protocol_health="oops")["items"] == []
