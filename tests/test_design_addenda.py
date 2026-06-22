"""Per-detector contract + coverage-honesty tests for the 2026-06 mega-wave actionable detectors.

Each detector reads collected-but-previously-unused snapshot evidence and emits a firing, traceable target-state
design decision. These tests pin, for every detector: (1) it FIRES on real evidence with the measured count;
(2) REFUTATION -- it returns None on clean evidence (a design claim is never asserted from absence); (3) the
backing principle is engine_actionable and actually emitted (no overstated coverage); and (4) the
device-attribution root-fix populates evidence.devices for the host-attributable detectors.
"""
from cisco_toolkit import design_kb
from cisco_toolkit.design_advisor import compute_design_blueprint


def _by(snap):
    return {d["id"]: d for d in compute_design_blueprint(snap)["decisions"]}


# ----------------------------------------------------------------- #1 one-VLAN-one-subnet integrity
def test_vlan_subnet_integrity_fires_and_honest():
    fire = {"subnet_intelligence": {"per_device": [
        {"served_subnets": [{"vlan": "20", "subnet": "10.10.20.0/24", "gateway": "a"}]},
        {"served_subnets": [{"vlan": "20", "subnet": "10.202.20.0/24", "gateway": "b"}]}]}}
    d = _by(fire).get("addressing-one-vlan-one-subnet-integrity")
    assert d and d["evidence"]["count"] == 1
    assert "subnet_intelligence.per_device[].served_subnets[].vlan" in d["evidence"]["fields"]
    assert set(d["evidence"]["devices"]) == {"a", "b"}
    # clean: the SAME subnet on two gateways (a legitimately stretched VLAN) must NOT fire
    clean = {"subnet_intelligence": {"per_device": [
        {"served_subnets": [{"vlan": "20", "subnet": "10.10.20.0/24", "gateway": "a"}]},
        {"served_subnets": [{"vlan": "20", "subnet": "10.10.20.0/24", "gateway": "b"}]}]}}
    assert "addressing-one-vlan-one-subnet-integrity" not in _by(clean)


# ----------------------------------------------------------------- #2 STP root determinism
def test_stp_root_determinism_fires_and_honest():
    fire = {"stp_roots": {"sw1": {"100": {"is_root": True, "root_priority": 32868},   # 32768 + 100 -> accidental
                                  "200": {"is_root": True, "root_priority": 24576}}}}  # engineered -> not counted
    d = _by(fire).get("dc-stp-root-determinism")
    assert d and d["evidence"]["count"] == 1 and d["evidence"]["devices"] == ["sw1"]
    assert "stp_roots[].root_priority" in d["evidence"]["fields"]
    # clean: an explicitly-engineered root (non-default priority) must NOT fire
    clean = {"stp_roots": {"sw1": {"100": {"is_root": True, "root_priority": 24576}}}}
    assert "dc-stp-root-determinism" not in _by(clean)


# ----------------------------------------------------------------- #3 reserved-range VLAN SVI
def test_reserved_vlan_fires_and_honest():
    fire = {"l3_forwarding": [{"switch": "ds17", "vlan": 4094, "svi_ip": "5.5.5.1/30"}]}
    d = _by(fire).get("addressing-reserved-vlan-range-hygiene")
    assert d and d["evidence"]["count"] == 1 and d["evidence"]["devices"] == ["ds17"]
    # clean: a user-range VLAN SVI must NOT fire; a reserved VLAN with no SVI must NOT fire
    assert "addressing-reserved-vlan-range-hygiene" not in _by(
        {"l3_forwarding": [{"switch": "ds17", "vlan": 100, "svi_ip": "10.0.0.1"}]})
    assert "addressing-reserved-vlan-range-hygiene" not in _by(
        {"l3_forwarding": [{"switch": "ds17", "vlan": 4094, "svi_ip": ""}]})


# ----------------------------------------------------------------- #4 static (mode on) EtherChannel
def test_static_etherchannel_fires_and_honest():
    fire = {"interfaces": {"sw1": {
        "Gi1/0/1": {"port_channel": "Po1", "port_channel_protocol": "ON"},
        "Gi1/0/2": {"port_channel": "Po1", "port_channel_protocol": "ON"}}}}
    d = _by(fire).get("dc-lacp-over-static-etherchannel")
    assert d and d["evidence"]["count"] == 1 and d["evidence"]["devices"] == ["sw1"]
    # clean: an LACP-negotiated bundle must NOT fire
    assert "dc-lacp-over-static-etherchannel" not in _by({"interfaces": {"sw1": {
        "Gi1/0/1": {"port_channel": "Po1", "port_channel_protocol": "LACP"},
        "Gi1/0/2": {"port_channel": "Po1", "port_channel_protocol": "LACP"}}}})
    # clean: a single-member bundle must NOT fire (no member to silently blackhole against)
    assert "dc-lacp-over-static-etherchannel" not in _by({"interfaces": {"sw1": {
        "Gi1/0/1": {"port_channel": "Po1", "port_channel_protocol": "ON"}}}})
    # clean: FEX-HIF (Eth>=100/x/y) is legitimately mode-on and must be EXCLUDED
    assert "dc-lacp-over-static-etherchannel" not in _by({"interfaces": {"sw1": {
        "Eth100/1/1": {"port_channel": "Po1", "port_channel_protocol": "ON"},
        "Eth100/1/2": {"port_channel": "Po1", "port_channel_protocol": "ON"}}}})


# ----------------------------------------------------------------- #5 power-supply redundancy
def test_power_redundancy_fires_and_honest():
    fire = {"devices": {"ds02": {"num_power_supplies": 18, "ps_status": "OK / FAIL"}}}
    d = _by(fire).get("dc-power-supply-redundancy")
    assert d and d["evidence"]["count"] == 1 and d["evidence"]["devices"] == ["ds02"]
    # clean: a single-PSU-by-design box must NOT fire (no redundancy to lose)
    assert "dc-power-supply-redundancy" not in _by({"devices": {"x": {"num_power_supplies": 1, "ps_status": "FAIL"}}})
    # clean: a multi-PSU box with all supplies OK must NOT fire
    assert "dc-power-supply-redundancy" not in _by({"devices": {"x": {"num_power_supplies": 2, "ps_status": "OK / OK"}}})


# ----------------------------------------------------------------- #8 gateway-move-last order
def test_gateway_cutover_order_fires_and_honest():
    fire = {"l3_forwarding": [{"switch": "d", "vlan": "64", "svi_ip": "10.0.64.1"}],
            "endpoint_identity": [{"vlan": "64", "host": "a"}, {"vlan": "64", "host": "b"}]}
    d = _by(fire).get("migration-gateway-cutover-order")
    assert d and d["evidence"]["count"] == 1
    # clean: a subnet whose endpoints sit on ONE switch is not move-order-constrained
    clean = {"l3_forwarding": [{"switch": "d", "vlan": "64", "svi_ip": "10.0.64.1"}],
             "endpoint_identity": [{"vlan": "64", "host": "a"}]}
    assert "migration-gateway-cutover-order" not in _by(clean)


# ----------------------------------------------------------------- #9 oversized L2 subnet
def test_oversized_l2_subnet_fires_and_honest():
    # FIRE: a VERIFIED single broadcast domain (exactly one collected subnet) with >254 endpoints overflows a /24.
    fire = {"endpoint_identity": [{"vlan": "208", "host": f"h{i}"} for i in range(255)],
            "l3_forwarding": [{"switch": "d", "vlan": "208", "svi_ip": "10.0.208.1", "primary_subnet": "10.0.208.0/24"}]}
    d = _by(fire).get("dc-size-l2-subnet-to-endpoint-count")
    assert d and d["evidence"]["count"] == 1
    # CLEAN 1: a VLAN at the /24 boundary (254 endpoints) still fits and must NOT fire
    clean = {"endpoint_identity": [{"vlan": "208", "host": f"h{i}"} for i in range(254)],
             "l3_forwarding": [{"switch": "d", "vlan": "208", "svi_ip": "10.0.208.1", "primary_subnet": "10.0.208.0/24"}]}
    assert "dc-size-l2-subnet-to-endpoint-count" not in _by(clean)
    # CLEAN 2 (review catch): a VLAN ID REUSED across two subnets/sites is NOT one broadcast domain -- its endpoint
    # sum is two independent /24s, so it must NOT fire as "oversized" (that is _d_vlan_subnet_integrity's renumber
    # territory, not a resize). 255 endpoints summed across two distinct /24s.
    reuse = {"endpoint_identity": [{"vlan": "64", "host": f"h{i}"} for i in range(255)],
             "l3_forwarding": [{"switch": "a", "vlan": "64", "svi_ip": "10.200.64.1", "primary_subnet": "10.200.64.0/24"},
                               {"switch": "b", "vlan": "64", "svi_ip": "10.203.64.1", "primary_subnet": "10.203.64.0/24"}]}
    assert "dc-size-l2-subnet-to-endpoint-count" not in _by(reuse)
    # CLEAN 3 (coverage-honest): a VLAN whose subnet was NOT collected (gateway on the uncollected core) cannot be
    # asserted to be a single domain -> must NOT fire on the bare endpoint count.
    unknown = {"endpoint_identity": [{"vlan": "208", "host": f"h{i}"} for i in range(255)]}
    assert "dc-size-l2-subnet-to-endpoint-count" not in _by(unknown)


# ----------------------------------------------------------------- #6 BPDU-Guard arm folds into determinism
def test_bpdu_guard_arm_fires_determinism_standalone():
    # No legacy STP, no VTP -- ONLY an unguarded endpoint-bearing access edge must still trigger edge-protection.
    fire = {"interfaces": {"sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                               "end_host_mac": "00:11:22:33:44:55"}}}}
    d = _by(fire).get("dc-stp-determinism-edge-protection")
    assert d and "interfaces[host][port].stp_bpduguard" in d["evidence"]["fields"]
    assert d["evidence"]["devices"] == ["sw1"]
    # clean: a BPDU-Guard-enabled edge (no legacy/VTP) must NOT fire
    clean = {"interfaces": {"sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                                "end_host_mac": "00:11:22:33:44:55", "stp_bpduguard": "enable"}}}}
    assert "dc-stp-determinism-edge-protection" not in _by(clean)
    # clean: an UPLINK (has a CDP neighbour) must NOT count as an unguarded endpoint edge
    uplink = {"interfaces": {"sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                                 "end_host_mac": "00:11:22:33:44:55", "cdp_neighbor": "core1"}}}}
    assert "dc-stp-determinism-edge-protection" not in _by(uplink)


# ----------------------------------------------------------------- coverage-honesty: addendum is actionable + emitted
def _fires_all():
    """One snapshot that trips every mega-wave detector at once."""
    return {
        "subnet_intelligence": {"per_device": [
            {"served_subnets": [{"vlan": "20", "subnet": "10.10.20.0/24", "gateway": "a"}]},
            {"served_subnets": [{"vlan": "20", "subnet": "10.202.20.0/24", "gateway": "b"}]}]},
        "stp_roots": {"sw1": {"100": {"is_root": True, "root_priority": 32868}}},
        "l3_forwarding": [{"switch": "ds17", "vlan": 4094, "svi_ip": "5.5.5.1/30"},
                          {"switch": "d", "vlan": "64", "svi_ip": "10.0.64.1"},
                          {"switch": "d2", "vlan": "208", "svi_ip": "10.0.208.1", "primary_subnet": "10.0.208.0/24"}],
        "interfaces": {"sw1": {"Gi1/0/1": {"port_channel": "Po1", "port_channel_protocol": "ON"},
                               "Gi1/0/2": {"port_channel": "Po1", "port_channel_protocol": "ON"}},
                       "acc9": {"Gi0/2": {"switchport_mode": "Access", "vlan": "10"}}},
        "devices": {"ds02": {"num_power_supplies": 18, "ps_status": "OK / FAIL"}},
        "endpoint_identity": [{"vlan": "64", "host": "a"}, {"vlan": "64", "host": "b"}]
        + [{"vlan": "208", "host": f"h{i}"} for i in range(255)],
        # build-wave engine_actionable principles: PIM running but no RP learned -> _d_pim_rp_health
        "pim": {"sw1": {"rp_mapping": {"present": True, "rp_count": 0, "rps": [], "groups": [], "ssm_only": False},
                        "neighbors": [{"neighbor": "10.0.255.2", "interface": "Gi1/0/1", "uptime": "1d"}]}},
        # dual-stack access switch w/o RA-Guard -> _d_ipv6_fhs
        "ipv6_fhs": {"acc9": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_policies": [],
                              "dhcp_guard_policies": [], "ra_guard_ifaces": [], "dhcp_guard_ifaces": [],
                              "ra_guard_present": False, "dhcp_guard_present": False}},
        # an infra router CDP neighbour absent from the inventory (devices above) -> _d_shadow_infra
        "shadow_infra": {"sw1": [{"device_id": "wan-edge-rtr9.corp", "platform": "cisco ASR1001-X",
                                  "capabilities": "Router", "proto": "cdp", "local_intf": "Gi0/0/0"}]},
    }


def test_actionable_detector_addendum_complete_actionable_and_emitted():
    add = design_kb._ACTIONABLE_DETECTOR_ADDENDUM
    assert isinstance(add, list) and len(add) == 10, "the actionable-detector addendum must hold the 7 mega-wave principles + the 3 build-wave (pim, ipv6-fhs, shadow-infra)"
    ids = [p["id"] for p in add]
    assert len(ids) == len(set(ids)), f"duplicate ids in the actionable addendum: {ids}"
    _FIELDS = ("id", "domain", "title", "priority", "engine_actionable", "design_intent",
               "tradeoffs", "trigger", "observable", "recommended_action", "alternatives", "citation")
    for p in add:
        for f in _FIELDS:
            assert p.get(f) not in (None, ""), f"{p['id']} missing/empty field {f!r}"
        assert p["engine_actionable"] is True, f"{p['id']} backs a firing detector -> must be engine_actionable"
    # no overstated coverage: every one is actually emitted by the advisor on evidence that trips it
    emitted = {d["id"] for d in compute_design_blueprint(_fires_all())["decisions"]}
    assert set(ids) <= emitted, f"actionable principles never emitted by the advisor: {set(ids) - emitted}"


# ----------------------------------------------------------------- #7 device-attribution root-fix
def test_device_attribution_populates_previously_empty_decisions():
    """Detectors that inspect specific hosts now carry evidence.devices (was [] -> the explorer dimmed the whole
    canvas while setHint() claimed 'Affected devices highlighted'). Recovered from the data they already read."""
    snap = {
        "addressing_conflicts": {"dup_ip": [{"ip": "1.1.1.1", "where": [["h1", "g0", None], ["h2", "g0", None]]}],
                                 "dup_subnet": []},
        "endpoint_dependencies": {"dual_homed": [{"endpoint": "e", "switches": ["s1", "s2"]}]},
        "config_hygiene": {"h3": {"summary": {"unused": 2, "undefined": 0}}},
        "move_groups": [{"switches": ["w1", "w2"], "spanning_vlans": [[124, "BC", 9]]}],
    }
    by = _by(snap)
    assert set(by["addressing-resolve-overlaps-before-merge"]["evidence"]["devices"]) == {"h1", "h2"}
    assert set(by["migration-preserve-dual-homed-endpoints"]["evidence"]["devices"]) == {"s1", "s2"}
    assert by["security-device-hardening-baseline"]["evidence"]["devices"] == ["h3"]
    assert set(by["dc-bound-layer2-failure-domain"]["evidence"]["devices"]) == {"w1", "w2"}
