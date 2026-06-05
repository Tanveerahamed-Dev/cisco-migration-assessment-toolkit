"""PHASE 2.7 step 1: the cisco_toolkit package extraction.

Guards the extraction boundary - the leaf text helpers live in
cisco_toolkit.textutils and the monolith re-exports the *same* objects (so a
future accidental re-definition in the monolith would break the identity check).
"""


def test_textutils_importable_standalone():
    from cisco_toolkit.textutils import normalize_ifname, is_valid_iface, normalize_mac
    assert normalize_ifname("GigabitEthernet1/0/1") == "Gi1/0/1"
    assert is_valid_iface("Gi1/0/1") is True
    assert is_valid_iface("garbage") is False
    assert normalize_mac("00:11:22:33:44:55") == "0011.2233.4455"
    from cisco_toolkit.textutils import _split_macs
    assert _split_macs("aaaa.bbbb.cccc, dddd.eeee.ffff") == ["aaaa.bbbb.cccc", "dddd.eeee.ffff"]
    assert _split_macs("") == []


def test_monolith_reexports_the_package_objects(cp):
    from cisco_toolkit import textutils
    # identity, not equality: the monolith must use the package's functions/regex,
    # not a re-defined copy.
    assert cp.normalize_ifname is textutils.normalize_ifname
    assert cp.detect_link_type is textutils.detect_link_type
    # is_valid_iface is now used only inside the package (its monolith callers moved out)
    assert callable(textutils.is_valid_iface)
    # PHYSICAL_IFACE_RE is still re-exported (monolith uses it); IFACE_TOKEN_RE / VALID_IFACE_RE
    # went package-internal in step 17 (their last monolith users, the phy parsers, moved to parse).
    assert cp.PHYSICAL_IFACE_RE is textutils.PHYSICAL_IFACE_RE
    assert not hasattr(cp, "VALID_IFACE_RE") and not hasattr(cp, "IFACE_TOKEN_RE")
    assert cp._split_macs is textutils._split_macs


def test_parse_module_reexported_and_functional(cp):
    from cisco_toolkit import parse
    # primitives live in the package; the monolith no longer references them
    # directly now that the table parsers moved out (so it doesn't import them).
    assert callable(parse.extract_fixed_cols) and callable(parse.slice_col)
    # parsers the monolith still calls are re-exported as the SAME object.
    assert cp.parse_ospf_neighbors is parse.parse_ospf_neighbors
    assert cp.parse_bgp_summary is parse.parse_bgp_summary
    assert cp.parse_show_interface_status is parse.parse_show_interface_status
    # functional smoke straight from the package
    rows = parse.parse_ospf_neighbors("10.0.0.2  1  FULL/DR  00:00:35  10.0.0.2  Gi0/1")
    assert rows and rows[0]["state"] == "FULL/DR" and rows[0]["interface"] == "Gi0/1"
    # _parse_fhrp joined the parser layer in step 16 (shared by analyze + the L3-fwd sheet).
    assert cp._parse_fhrp is parse._parse_fhrp
    assert parse._parse_fhrp("HSRP grp 1 Active VIP 10.0.10.1") == ("HSRP", "Active", "10.0.10.1", "1")
    # physical-port parsers joined the parser layer in step 17.
    for name in ("_is_physical_port", "_classify_media", "parse_interface_phy", "_parse_poe_watts"):
        assert getattr(cp, name) is getattr(parse, name)
    assert parse._is_physical_port("Gi1/0/1") is True and parse._is_physical_port("Vlan10") is False
    assert parse._classify_media("media type is 10/100/1000BaseTX") == "copper"
    phy = parse.parse_interface_phy(
        "GigabitEthernet1/0/1 is up\n  Full-duplex, 1000Mb/s, media type is 10/100/1000BaseTX\n")
    assert phy["Gi1/0/1"]["duplex"] == "Full" and phy["Gi1/0/1"]["media"] == "copper"


def test_model_reexported_and_functional(cp):
    from cisco_toolkit import model
    # identity, not equality: the monolith must construct the package's classes,
    # not a re-defined copy (every layer passes these records around).
    assert cp.InterfaceData is model.InterfaceData
    assert cp.DevicePhysical is model.DevicePhysical
    # functional smoke straight from the package: fields + defaults intact.
    iface = model.InterfaceData(port="Gi1/0/1", status="connected")
    assert iface.port == "Gi1/0/1" and iface.status == "connected"
    assert iface.vlan == "" and iface.neighbor_platform == ""
    dp = model.DevicePhysical(hostname="core1")
    assert dp.hostname == "core1" and dp.num_power_supplies == 0


def test_analyze_reexported_and_functional(cp):
    from cisco_toolkit import analyze
    # identity, not equality: the compute_* functions still in the monolith must use
    # the package's ScoringConfig/SCORING/helpers, not a re-defined copy.
    # _health_band stays re-exported (write_health_scores_sheet uses it); ScoringConfig /
    # SCORING / _host_role went package-internal in step 15 (their last monolith users, the
    # scoring compute_*, moved out).
    assert cp._health_band is analyze._health_band
    assert callable(analyze.ScoringConfig) and analyze.SCORING is not None and callable(analyze._host_role)
    for gone in ("ScoringConfig", "SCORING", "_host_role"):
        assert not hasattr(cp, gone)
    # the default config reproduces the documented hard-coded tunables.
    assert analyze.SCORING.caps == {"L1": 30, "L3": 30, "XL": 45, "PROTO": 25}
    assert analyze.SCORING.l1_weights["single-fiber-uplink"] == 10
    # band thresholds + the gateway-SVI role heuristic, straight from the package.
    assert analyze._health_band(95) == ("Excellent", "36E08A")
    assert analyze._health_band(50) == ("Poor", "FF9F45")
    gw = analyze.InterfaceData(port="Vlan10", svi_ip="10.0.0.1")
    assert analyze._host_role({"Vlan10": gw}) == "distribution"
    assert analyze._host_role({"Gi1/0/1": analyze.InterfaceData(port="Gi1/0/1")}) == "access"
    # move-group computation joined the analyze layer (step 11).
    assert cp.compute_move_groups is analyze.compute_move_groups
    # MOVEGROUP_EXCLUDED_VLANS went package-internal in step 12: its last monolith user
    # (compute_findings) moved out, so the monolith no longer re-exports it.
    assert analyze.MOVEGROUP_EXCLUDED_VLANS == {1}
    assert not hasattr(cp, "MOVEGROUP_EXCLUDED_VLANS")
    # two switches sharing VLAN 20 (via access ports) collapse into one move group.
    ID = analyze.InterfaceData
    ifaces = {
        "sw1": {"Gi1/0/1": ID(port="Gi1/0/1", switchport_mode="Access", vlan="20")},
        "sw2": {"Gi1/0/1": ID(port="Gi1/0/1", switchport_mode="Access", vlan="20")},
    }
    groups = analyze.compute_move_groups(ifaces)
    assert len(groups) == 1 and groups[0]["switches"] == ["sw1", "sw2"]
    # topology-links + findings cluster joined the analyze layer (step 12).
    for name in ("compute_topology_links", "compute_findings"):
        assert getattr(cp, name) is getattr(analyze, name)
    # _canon_host / _canon_host_map went package-internal in step 13 (build_network_model,
    # their last monolith user, moved out, so the monolith no longer re-exports them).
    assert callable(analyze._canon_host) and callable(analyze._canon_host_map)
    assert not hasattr(cp, "_canon_host") and not hasattr(cp, "_canon_host_map")
    assert analyze._canon_host("Switch1.example.com (FOC123)") == "switch1"
    # two switches that see each other over CDP -> one link confirmed from both ends.
    tl = {
        "sw1": {"Gi1/0/1": ID(port="Gi1/0/1", cdp_neighbor="sw2", neighbor_port="Gi1/0/1", endpoint_type="Switch")},
        "sw2": {"Gi1/0/1": ID(port="Gi1/0/1", cdp_neighbor="sw1", neighbor_port="Gi1/0/1", endpoint_type="Switch")},
    }
    links = analyze.compute_topology_links(tl)
    assert len(links) == 1 and links[0]["confirmation"] == "Both ends"
    # two SVIs for VLAN 20 with no FHRP -> a High "Gateway redundancy" finding.
    fi = {"sw1": {"Vlan20": ID(port="Vlan20")}, "sw2": {"Vlan20": ID(port="Vlan20")}}
    assert any(sev == "High" and cat == "Gateway redundancy"
               for (sev, cat, scope, detail) in analyze.compute_findings(fi))
    # network-model / blast-radius cluster joined the analyze layer (step 13).
    for name in ("build_network_model", "compute_causality_chains", "compute_failure_impact"):
        assert getattr(cp, name) is getattr(analyze, name)
    # _vlan_components (step 18) + _link_carries (step 19) went package-internal as their
    # last monolith users (build_dependency_map / _bfs_forwarding_path) moved out.
    for gone in ("_vlan_components", "_link_carries"):
        assert hasattr(analyze, gone) and not hasattr(cp, gone)
    nm = {
        "sw1": {"Vlan20": ID(port="Vlan20")},   # sole gateway for VLAN 20, no FHRP
        "sw2": {"Gi1/0/1": ID(port="Gi1/0/1", switchport_mode="Access", vlan="20",
                              end_host_mac="aaaa.bbbb.cccc")},
    }
    model = analyze.build_network_model(nm)
    assert model["hosts"] == ["sw1", "sw2"] and 20 in model["vlans"]
    assert model["access_presence"].get(20) == {"sw2"}
    # removing the sole gateway (sw1) hard-partitions VLAN 20's endpoints -> High severity.
    impact = {r["host"]: r for r in analyze.compute_failure_impact(nm)}
    assert impact["sw1"]["severity"] == "High"
    # scoring + readiness synthesis joined the analyze layer (step 15).
    for name in ("compute_data_quality", "compute_health_scores",
                 "compute_score_sensitivity", "compute_migration_readiness"):
        assert getattr(cp, name) is getattr(analyze, name)
    # empty inputs -> a perfect, deduction-free score.
    hs = analyze.compute_health_scores({"sw1": {}}, [], [], [], [])
    assert hs == [{"switch": "sw1", "score": 100, "band": "Excellent", "deductions": []}]
    # data-quality fraction: no collected files -> 0.0; no hosts -> empty.
    assert analyze.compute_data_quality({}) == {}
    assert analyze.compute_data_quality({"sw1": {}}) == {"sw1": 0.0}
    # protocol-health joined the analyze layer (step 16); its STP/EC/VTP sub-parsers are
    # package-internal, and _parse_fhrp moved to parse.py (shared with the L3-fwd sheet).
    assert cp.compute_protocol_health is analyze.compute_protocol_health
    for internal in ("_parse_stp_mode", "_parse_stp_tcn", "_parse_etherchannel_member_states", "_parse_vtp_full"):
        assert callable(getattr(analyze, internal)) and not hasattr(cp, internal)
    ph = analyze.compute_protocol_health(
        {"sw1": {"Vlan10": ID(port="Vlan10", hsrp_behavior="HSRP grp 1 Active VIP 10.0.10.1")}}, {})
    assert any(r["protocol"] == "FHRP" and r["severity"] == "Info" for r in ph)
    # physical-health compute helpers joined the analyze layer (step 17).
    assert cp._poe_device_util is analyze._poe_device_util
    assert cp._physical_uplink_index is analyze._physical_uplink_index
    DP = analyze.DevicePhysical
    assert analyze._poe_device_util([DP(hostname="sw1", power_capacity_w="1000", power_drawn_w="250")]) == {"sw1": 25.0}
    # a single non-port-channel inter-switch link -> a single-fiber uplink on both ends.
    up, sf = analyze._physical_uplink_index(
        {"links": [{"a": "sw1", "ap": "Gi1/0/1", "b": "sw2", "bp": "Gi1/0/1", "is_pc": False}]})
    assert ("sw1", "Gi1/0/1") in sf and ("sw2", "Gi1/0/1") in sf
    # dependency-map + cross-layer correlations joined the analyze layer (step 18).
    assert cp.build_dependency_map is analyze.build_dependency_map
    assert cp.compute_cross_layer_correlations is analyze.compute_cross_layer_correlations
    for internal in ("all_hosts", "_CL_RANK"):  # package-internal, not re-exported
        assert hasattr(analyze, internal) and not hasattr(cp, internal)
    cl_ai = {"sw1": {"Vlan20": ID(port="Vlan20")},
             "sw2": {"Gi1/0/1": ID(port="Gi1/0/1", switchport_mode="Access", vlan="20")}}
    dep = analyze.build_dependency_map(
        cl_ai, [], [{"vlan": 20, "switch": "sw1", "risk": "single-gateway", "fhrp": "none"}])
    assert dep["sole_gw"] == {20: "sw1"}   # sole-gateway VLAN, no FHRP
    assert any(f["id"] == "CL-03" for f in analyze.compute_cross_layer_correlations(dep))
    # flow-trace joined the analyze layer (step 19); its helpers are package-internal.
    assert cp.trace_full_flow is analyze.trace_full_flow
    for internal in ("_ip_in_prefix", "_find_endpoint_by_ip", "_find_gateways_for", "_bfs_forwarding_path"):
        assert hasattr(analyze, internal) and not hasattr(cp, internal)
    assert analyze._ip_in_prefix("10.0.10.5", "10.0.10.0/24") is True
    assert analyze._ip_in_prefix("10.0.99.5", "10.0.10.0/24") is False
    # same-subnet flow between two located endpoints in VLAN 10 -> an L2 (same subnet) path.
    flow = analyze.trace_full_flow("10.0.10.5", "10.0.10.6", {
        "sw1": {"Gi1/0/1": ID(port="Gi1/0/1", switchport_mode="Access", vlan="10", end_host_ip="10.0.10.5"),
                "Gi1/0/2": ID(port="Gi1/0/2", switchport_mode="Access", vlan="10", end_host_ip="10.0.10.6")}})
    assert flow["summary"]["flow_type"] == "L2 (same subnet)" and flow["summary"]["src_ip"] == "10.0.10.5"


def test_cmdio_reexported_and_functional(cp, tmp_path):
    from cisco_toolkit import cmdio
    # identity: the ~50 monolith call sites must use the package's helpers.
    assert cp._load_cmd_output is cmdio._load_cmd_output
    assert cp._safe_parse is cmdio._safe_parse
    assert cp._CISCO_ERRORS is cmdio._CISCO_ERRORS
    # _safe_parse: happy path returns the value; a raising parser falls back to _default.
    assert cmdio._safe_parse(lambda x: {"k": x}, 1) == {"k": 1}
    def _boom(_):
        raise ValueError("bad section")
    assert cmdio._safe_parse(_boom, "x") == {}
    assert cmdio._safe_parse(_boom, "x", _default=[]) == []
    # _load_cmd_output: returns file content; skips an empty/Cisco-error capture + absent cmds.
    good = tmp_path / "good.txt"; good.write_text("Gi1/0/1 connected\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"; bad.write_text("% Invalid input detected at '^' marker.\n", encoding="utf-8")
    c2f = {"show a": str(good), "show b": str(bad)}
    assert cmdio._load_cmd_output(c2f, "show a").strip() == "Gi1/0/1 connected"
    assert cmdio._load_cmd_output(c2f, "show b") == ""        # captured Cisco error skipped
    assert cmdio._load_cmd_output(c2f, "show missing") == ""  # absent command
    # variant fallthrough: first variant errored, second is good.
    assert cmdio._load_cmd_output(c2f, "show b", "show a").strip() == "Gi1/0/1 connected"


def test_excel_reexported_and_functional(cp):
    from cisco_toolkit import excel
    # the sheet/header helpers main() + the write_* builders use are re-exported as-is.
    for name in ("_census_header", "_census_autofit", "find_header_row", "ensure_headers", "sortkey"):
        assert getattr(cp, name) is getattr(excel, name)
    # norm_header / HEADER_TO_FIELD are package-internal (only find_header_row uses them).
    assert callable(excel.norm_header) and not hasattr(cp, "norm_header")
    assert isinstance(excel.HEADER_TO_FIELD, dict) and not hasattr(cp, "HEADER_TO_FIELD")
    # functional smokes straight from the package.
    assert excel.norm_header("  Switchport  Mode ") == "switchport mode"
    assert excel.HEADER_TO_FIELD["fhrp behavior"] == "hsrp_behavior"
    # port-row sort: port-channels first, then Eth/Fa/Gi... by number (not lexical).
    ports = ["Gi1/0/2", "Po1", "Gi1/0/10", "Gi1/0/1"]
    assert sorted(ports, key=excel.sortkey) == ["Po1", "Gi1/0/1", "Gi1/0/2", "Gi1/0/10"]
