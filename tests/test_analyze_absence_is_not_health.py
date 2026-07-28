"""[review 2026-07-28 · analyze.py tranche] absence of evidence must never render as health.

One test per finding (#12–#17, #51, #52). Every case plants the real shape of a MISSING capture and
asserts the engine says "not assessed" — never `pass` / `ok` / "no impact". Each test fails on the
pre-fix code; the docstrings record what it looked like then.
"""
from cisco_toolkit import analyze
from cisco_toolkit.model import InterfaceData


def _dep_skeleton(**over):
    """A dependency map with every key compute_cross_layer_correlations reads."""
    d = {"single_fiber": set(), "uplink_ports": set(), "sole_gw": {}, "nofhrp_vlans": {},
         "errored_up": set(), "halfdup_up": set(), "errdis": set(), "tracked_down": set(),
         "tracked_down_vlans": {}, "fhrp_hosts": set(), "fhrp_vlans": set(),
         "gw_switches": set(), "access_by_vlan": {}, "orphan": set(), "articulation": set(),
         "single_member_pc": set(), "model": {"hosts": set()}}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #12
def test_readiness_stp_and_portchannel_abstain_when_never_collected():
    """[#12] Readiness checks 5 (STP consistency) and 6 (Port-channels healthy) can only FAIL off a
    protocol_health row, and neither `show spanning-tree` nor `show etherchannel summary` is an
    essential command — so a switch with ZERO STP / bundle evidence emitted an affirmative
    'pass — no inconsistent ports' / 'all members bundled' and its group reached READY. The adjacent
    routing check carries a `routing_collected` coverage set for exactly this reason."""
    ifaces = {"sw1": {"Gi0/1": InterfaceData(port="Gi0/1", port_channel="Po1")},
              "core1": {"Gi0/1": InterfaceData(port="Gi0/1", port_channel="Po1")}}
    # the fleet WAS asked for both commands -- core1 answered, sw1 did not.
    ph = [{"switch": "core1", "protocol": "STP", "severity": "Info",
           "summary": "mode rstp; 0 blocked, 0 inconsistent", "detail": ""},
          {"switch": "core1", "protocol": "EtherChannel", "severity": "Info",
           "summary": "1 bundle(s), 2 member(s)", "detail": ""}]
    dep = analyze.build_dependency_map(ifaces, [], [])

    def checks(group_switches):
        out = analyze.compute_migration_readiness(
            ifaces, [{"group": "G", "switches": group_switches}],
            [{"switch": h, "band": "Good"} for h in group_switches],
            [], [], [], ph, dep)
        return {c["check"]: c for c in out[0]["checks"]}, out[0]["readiness"]

    blind, blind_verdict = checks(["sw1"])          # no evidence for THIS group's switch
    seen, _ = checks(["core1"])                     # evidence present for this group's switch

    assert blind["STP consistency"]["status"] == "warn"
    assert "not assessable" in blind["STP consistency"]["note"]
    assert blind["Port-channels healthy"]["status"] == "warn"
    assert "not assessable" in blind["Port-channels healthy"]["note"]
    assert blind_verdict != "READY"                 # a blind group is not a ready group
    # ...and the check still PASSES where the evidence exists (no cry-wolf, and the gate still works)
    assert seen["STP consistency"]["status"] == "pass"
    assert seen["Port-channels healthy"]["status"] == "pass"
    assert blind["STP consistency"] != seen["STP consistency"]


def test_readiness_does_not_cry_wolf_when_nothing_was_collected_anywhere():
    """[#12 guard] The coverage set must not fire on a run that collected STP/bundle state NOWHERE
    (mirrors the `if routing_collected` / `if baseline_hosts` guards on the sibling checks), and a
    switch with no port-channel members has nothing to abstain about."""
    out = analyze.compute_migration_readiness(
        {"sw1": {"Gi0/1": InterfaceData(port="Gi0/1")}},
        [{"group": "G", "switches": ["sw1"]}], [{"switch": "sw1", "band": "Excellent"}],
        [], [], [], [], analyze.build_dependency_map({"sw1": {}}, [], []))
    by = {c["check"]: c for c in out[0]["checks"]}
    assert by["STP consistency"]["status"] == "pass"
    assert by["Port-channels healthy"]["status"] == "pass"
    # ...but the note may not ASSERT a clean spanning tree that was never looked at
    assert "not collected" in by["STP consistency"]["note"]


# --------------------------------------------------------------------------- #13
def test_failure_impact_no_trunk_evidence_is_indeterminate_not_no_impact():
    """[#13] `_link_carries` returns the same '' for 'positively not carried' and 'no evidence at
    all', so a sole L2 transit switch whose trunk/STP output was never collected contributed no
    forwarding edge, stranded nobody, and was reported 'No reachability impact from removing this
    switch (within the scan)' at severity Info — a clean bill written from missing evidence."""
    def isl(port, nbr, nbr_port, **kw):
        return InterfaceData(port=port, cdp_neighbor=nbr, neighbor_port=nbr_port,
                             endpoint_type="Switch", **kw)
    # access1 -- transit1 -- core1(VLAN 10 gateway); NO trunk/STP evidence anywhere.
    blind = {
        "access1": {"Gi1/0/1": isl("Gi1/0/1", "transit1", "Gi1/0/1"),
                    "Gi1/0/2": InterfaceData(port="Gi1/0/2", switchport_mode="Access", vlan="10",
                                             end_host_mac="aaaa.bbbb.cccc")},
        "transit1": {"Gi1/0/1": isl("Gi1/0/1", "access1", "Gi1/0/1"),
                     "Gi1/0/2": isl("Gi1/0/2", "core1", "Gi1/0/1")},
        "core1": {"Gi1/0/1": isl("Gi1/0/1", "transit1", "Gi1/0/2"),
                  "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.1")},
    }
    rec = {r["host"]: r for r in analyze.compute_failure_impact(blind)}["transit1"]
    assert "No reachability impact" not in rec["detail"]
    assert "INDETERMINATE" in rec["detail"] and "not assessable" in rec["detail"]

    # With the trunk evidence present, the same topology resolves normally again (no cry-wolf):
    seen = {h: {p: InterfaceData(**{**vars(d), "trunk_allowed_vlans": "10"})
                if d.cdp_neighbor else d for p, d in ports.items()}
            for h, ports in blind.items()}
    rec2 = {r["host"]: r for r in analyze.compute_failure_impact(seen)}["transit1"]
    assert "INDETERMINATE" not in rec2["detail"]


# --------------------------------------------------------------------------- #14
def test_single_fiber_uplink_to_an_uncollected_core_is_still_single_homed():
    """[#14] build_network_model keeps only links whose BOTH ends resolve to a scanned host, and
    `_physical_uplink_index` read `model['links']` alone — so an access switch whose only uplink
    faces an uncollected core contributed nothing, `single_fiber` came back empty and readiness
    check 1 reported 'no single-homed switch' over the commonest real topology."""
    ifaces = {"access1": {"Gi1/0/1": InterfaceData(
        port="Gi1/0/1", cdp_neighbor="core-not-collected", neighbor_port="Gi1/0/24",
        endpoint_type="Switch", switchport_mode="Trunk", trunk_status="trunking")}}
    model = analyze.build_network_model(ifaces)
    assert model["links"] == []                                  # far end unscanned, as before
    uplinks, single_fiber = analyze._physical_uplink_index(model)
    assert ("access1", "Gi1/0/1") in uplinks
    assert ("access1", "Gi1/0/1") in single_fiber
    dep = analyze.build_dependency_map(ifaces, [], [])
    out = analyze.compute_migration_readiness(
        ifaces, [{"group": "G", "switches": ["access1"]}],
        [{"switch": "access1", "band": "Good"}], [], [], [], [], dep)
    chk = {c["check"]: c for c in out[0]["checks"]}["Redundant uplinks"]
    assert chk["status"] != "pass" and "access1" in chk["note"]


def test_offscan_edge_peer_does_not_manufacture_a_phantom_uplink():
    """[#14 counter-case] CDP-speaking IP phones / APs are admitted by compute_topology_links, so
    an unfiltered off-scan uplink index would credit an ACCESS port to a phone as a second uplink —
    which does not merely add noise, it makes a genuinely single-homed switch read dual-homed and
    SUPPRESSES its single-fiber finding. Only positive switching evidence may count."""
    ifaces = {"access1": {
        "Gi1/0/1": InterfaceData(port="Gi1/0/1", cdp_neighbor="core-not-collected",
                                 neighbor_port="Gi1/0/24", endpoint_type="Switch",
                                 switchport_mode="Trunk", trunk_status="trunking"),
        "Gi1/0/2": InterfaceData(port="Gi1/0/2", cdp_neighbor="AP-floor1", neighbor_port="Gi0",
                                 endpoint_type="Switch", switchport_mode="Access", vlan="10")}}
    model = analyze.build_network_model(ifaces)
    assert [l["port"] for l in model["offscan_links"]] == ["Gi1/0/1"]
    _up, single_fiber = analyze._physical_uplink_index(model)
    assert single_fiber == {("access1", "Gi1/0/1")}


# --------------------------------------------------------------------------- #15
def test_health_score_never_fabricates_data_quality_for_an_unmeasured_host():
    """[#15] `dq = data_quality.get(h, 1.0)` published a perfect completeness score for a host the
    measurement never covered (compute_data_quality keys off all_cmd_to_files, and the phase falls
    back to `{}` on failure) — an affirmative 'all four essential commands returned usable output'
    claim about a measurement never taken, on which `dq < threshold` could never fire."""
    ifaces = {"measured": {"Gi0/1": InterfaceData(port="Gi0/1")},
              "unmeasured": {"Gi0/1": InterfaceData(port="Gi0/1")}}
    by = {r["switch"]: r for r in analyze.compute_health_scores(
        ifaces, [], [], [], [], data_quality={"measured": 1.0})}
    assert by["unmeasured"]["data_quality"] is None
    assert by["unmeasured"]["band"] == "Insufficient Data"
    assert by["measured"]["data_quality"] == 1.0 and by["measured"]["band"] != "Insufficient Data"
    # the whole-fleet case: the data-quality phase failed and fell back to {}
    allblind = analyze.compute_health_scores(ifaces, [], [], [], [], data_quality={})
    assert all(r["band"] == "Insufficient Data" and r["data_quality"] is None for r in allblind)
    # and the opt-out (no argument at all) still emits no data_quality key -- back-compat
    assert "data_quality" not in analyze.compute_health_scores(ifaces, [], [], [], [])[0]


# --------------------------------------------------------------------------- #16
def test_dossier_insufficient_data_host_renders_na_not_clean():
    """[#16] The dossier's `scanned` guard was INERT for the case it targets: a host banded
    'Insufficient Data' still HAS a health-score row, so scanned was True and the Physical /
    Protocol axes rendered 'ok — no L1 findings' / 'protocol health clean' right beside the same
    device's own 'Health: na — collection gap'."""
    d = analyze.compute_device_dossiers(
        health_scores=[{"switch": "gapbox", "score": 100, "band": "Insufficient Data",
                        "data_quality": 0.25, "role": "access"}])["per_device"][0]
    state = {e["axis"]: e["state"] for e in d["exposures"]}
    assert state["Health"] == "na"
    assert state["Physical"] == "na" and state["Protocol"] == "na"
    # a genuinely scored host still gets its 'ok' by silence (the guard is not a blanket mute)
    ok = analyze.compute_device_dossiers(
        health_scores=[{"switch": "goodbox", "score": 95, "band": "Excellent",
                        "data_quality": 1.0, "role": "access"}])["per_device"][0]
    ok_state = {e["axis"]: e["state"] for e in ok["exposures"]}
    assert ok_state["Physical"] == "ok" and ok_state["Protocol"] == "ok"


# --------------------------------------------------------------------------- #17
def test_trunk_capture_gaps_fail_closed_when_state_is_undeterminable():
    """[#17] compute_trunk_capture_gaps wrapped each host in a bare `except Exception: continue`,
    dropping any host whose capture state could not be determined — so its native-VLAN-1 exposure
    read clean, the exact absence-reads-as-no-exposure failure this detector exists to prevent. The
    swallow was unbounded: every host could raise and it would still return []."""
    class Undeterminable(dict):
        def values(self):
            raise RuntimeError("malformed port map")

    ports = Undeterminable({"Gi0/1": InterfaceData(port="Gi0/1", switchport_mode="Trunk")})
    assert analyze.compute_trunk_capture_gaps({"sw1": ports}, {"sw1": {}}) == ["sw1"]
    # a device with no switchport evidence at all (a router) stays out of scope -- no cry-wolf
    assert analyze.compute_trunk_capture_gaps(
        {"rtr1": {"Gi0/0": InterfaceData(port="Gi0/0")}}, {"rtr1": {}}) == []


# --------------------------------------------------------------------------- #51
def test_cl04_joins_tracked_down_on_vlan_instead_of_multiplying():
    """[#51] CL-04 paired the FLEET-WIDE `tracked_down` host set against EVERY FHRP VLAN without
    joining on VLAN, so ONE device fault became N identical High findings, N punch-list rows and N
    XL deductions that saturate the cross-layer cap in compute_health_scores."""
    l3 = [{"vlan": 10, "switch": "core1", "risk": "tracked-object-down", "fhrp": "HSRP"},
          {"vlan": 20, "switch": "core1", "risk": "ok", "fhrp": "HSRP"},
          {"vlan": 30, "switch": "core1", "risk": "ok", "fhrp": "HSRP"}]
    dep = analyze.build_dependency_map({"core1": {}}, [], l3)
    assert dep["fhrp_vlans"] == {10, 20, 30}
    assert dep["tracked_down"] == {"core1"}                 # host set kept for CL-09
    cl04 = [f for f in analyze.compute_cross_layer_correlations(dep) if f["id"] == "CL-04"]
    assert len(cl04) == 1 and "VLAN 10" in cl04[0]["title"]

    # a hand-built dep map with the fleet-wide set but no VLAN join key must not re-inflate
    legacy = _dep_skeleton(fhrp_vlans={10, 20, 30}, tracked_down={"core1"})
    legacy.pop("tracked_down_vlans")
    assert not [f for f in analyze.compute_cross_layer_correlations(legacy) if f["id"] == "CL-04"]


# --------------------------------------------------------------------------- #52
def test_etherchannel_advisory_covers_minlinks_failed_and_combined_flags():
    """[#52] `_extract_protocol_states` matched member flags with `\\(([sDIwH])\\)` — a
    single-character class omitting 'M' (min-links not met) and 'f' (failed to allocate aggregator)
    that could not match a combined token like '(RM)' at all. compute_protocol_health rates all of
    those High off `_EC_BAD_FLAGS`, so the states the engine itself called DOWN produced no
    advisory: the protocol-intelligence surface read clean for a broken bundle."""
    detail = "Gi1/0/1(M); Gi1/0/2(RM); Gi1/0/3(f); Gi1/0/4(sD); Gi1/0/5(P)"
    states = analyze._extract_protocol_states("EtherChannel", "", detail)
    assert set(states) == {"M", "f", "s", "D"}          # 'P' (bundled/healthy) stays out
    rows = analyze.compute_protocol_intelligence(
        [{"switch": "sw1", "protocol": "EtherChannel", "severity": "High",
          "summary": "1 bundle(s), 5 member(s); 4 not bundled", "detail": detail}])
    by = {r["state"]: r for r in rows}
    assert set(by) == {"M", "f", "s", "D"}
    assert by["M"]["severity"] == "High" and by["f"]["severity"] == "High"
    # the KB carries no entry for M/f, so the CAUSE must be marked not-derived, never invented
    assert "NOT ASSESSED" in by["M"]["likely_cause"]
    assert "NOT assessed" in by["M"]["confidence"]
    # the flag alphabet is ONE source of truth shared with the severity rater
    assert "M" in analyze._EC_BAD_FLAGS and "f" in analyze._EC_BAD_FLAGS
