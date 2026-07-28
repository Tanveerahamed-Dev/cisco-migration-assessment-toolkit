"""Regression guards for the 2026-07-28 whole-repo review, design-brain tranche
(docs/review-findings-2026-07-28.md findings #38, #39, #40, #41, #42, #43, #50).

Every one of these is the same defect class the repo's doctrine forbids outright: an absent capture, an
unparsed field or an unrecognised token turned into a positive claim about the network -- here mostly in
the "not observed becomes observed BROKEN" direction, which drives a High design decision (and the BoM,
the LLD subnet sizing and the deck) off evidence that was never collected. Each test FAILS on the
pre-fix code, so reverting the fix regresses here.
"""
import cisco_toolkit.design_advisor as da


# ------------------------------------------------------------------ #38 BPDU-Guard on an ABSENT field
def test_bpdu_guard_arm_abstains_when_run_config_was_not_collected():
    """#38 `stp_bpduguard` is populated ONLY from `show running-config interface` (build.build_interfaces
    step 4) while the fields that GATE the same loop (end_host_mac from the MAC table, cdp_neighbor from
    CDP) come from other commands. A collection without run-config therefore leaves the field empty on
    every port -- and the old predicate read that emptiness as "BPDU-Guard is not enabled", reporting
    every endpoint-bearing access port in the estate as an OBSERVED unprotected edge. archreview's L2-2
    tracks `bpdu_data` and grades not-assessable for exactly this; the advisor must abstain the same way:
    zero unguarded ports, and the gap disclosed as a Coverage-gap collect-this item (silence would be the
    false-CLEAN twin of the same bug)."""
    no_runcfg = {"interfaces": {"sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                                    "end_host_mac": "00:11:22:33:44:55"}}}}
    sig = da._signals(no_runcfg)
    assert sig["bpdu_unguarded"] == 0, "an absent field is not an observed unguarded port"
    assert sig["bpdu_unguarded_nsw"] == 0 and sig["bpdu_unguarded_hosts"] == []
    assert sig["bpdu_not_assessed"] == 1 and sig["bpdu_not_assessed_hosts"] == ["sw1"]
    dec = da._d_stp_det(no_runcfg, sig)
    assert dec is not None, "the coverage gap must still surface -- silence is the false-clean twin"
    assert dec["confidence"] == "Coverage-gap"
    assert dec["evidence"]["summary"].startswith("COVERAGE GAP: BPDU-Guard state was NOT CAPTURED")
    assert "have no BPDU-Guard" not in dec["evidence"]["summary"], "must not claim an observed gap"
    assert "not deterministic" not in dec["evidence"]["summary"], "no observed verdict on unassessed ports"

    # POSITIVE control: the run-config DID land on this host (a sibling port carries the field), and the
    # endpoint-bearing edge port is genuinely unguarded -> a real, Observed finding.
    collected = {"interfaces": {"sw1": {
        "Gi1/0/1": {"switchport_mode": "Access", "vlan": "10", "end_host_mac": "00:11:22:33:44:55"},
        "Gi1/0/2": {"switchport_mode": "Access", "stp_bpduguard": "Enable"}}}}
    sig2 = da._signals(collected)
    assert sig2["bpdu_unguarded"] == 1 and sig2["bpdu_not_assessed"] == 0
    dec2 = da._d_stp_det(collected, sig2)
    assert dec2["confidence"] == "Observed" and "have no BPDU-Guard" in dec2["evidence"]["summary"]

    # and a guarded edge on a collected host stays silent (no cry-wolf)
    guarded = {"interfaces": {"sw1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                                  "end_host_mac": "00:11:22:33:44:55",
                                                  "stp_bpduguard": "enable"}}}}
    assert da._d_stp_det(guarded, da._signals(guarded)) is None


# ------------------------------------------------------------------ #39 single-VRF asserted from absence
def test_single_vrf_is_not_asserted_from_an_absent_segmentation_block():
    """#39 `len(vrfs) <= 1` was True for the EMPTY list an absent `segmentation` block yields, so absence
    asserted "the estate runs one global VRF" and drove a High flat-L2 decision whose own citation list
    points at `segmentation.vrfs` -- a path that does not exist on the snapshot that produced it.
    analyze.compute_segmentation always lists at least the "(global)" bucket once any gateway SVI is
    observed, so an empty list means the axis saw nothing."""
    vlans = {"l3_forwarding": [{"switch": "d1", "vlan": str(v), "svi_ip": f"10.0.{v}.1"} for v in range(10, 40)]}
    sig = da._signals(vlans)
    assert sig["vlans"] >= da._LARGE_L2_VLANS, "pre-condition: enough VLANs to trip the flat-L2 threshold"
    assert sig["vrf_observed"] is False and sig["single_vrf"] is False
    assert da._d_flat_l2(vlans, sig) is None, "must not assert a flat single-VRF estate from an absent block"
    # ...and the narrative must not flip to the OPPOSITE fabrication ('multiple VRFs') either
    card = {e["axis"]: e for e in da._scorecard(vlans, sig)}
    assert "not-collected VRF" in card["scalability"]["evidence"]
    dim = next(d for d in da.compute_target_state(vlans)["dimensions"]
               if d["area"] == "Layer-2 / Layer-3 boundary")
    assert "uncollected VRF posture" in dim["current"]

    # POSITIVE control: the axis WAS collected and reports one (global) VRF -> the decision is honest
    collected = dict(vlans, segmentation={"vrfs": [{"vrf": "(global)", "gateway_count": 30}]})
    sigc = da._signals(collected)
    assert sigc["vrf_observed"] is True and sigc["single_vrf"] is True
    assert da._d_flat_l2(collected, sigc) is not None
    # ...and a genuinely multi-VRF estate stays silent
    multi = dict(vlans, segmentation={"vrfs": [{"vrf": "(global)"}, {"vrf": "RED"}]})
    assert da._d_flat_l2(multi, da._signals(multi)) is None


# ------------------------------------------------------------------ #40 switchport-mode predicate drift
def test_vlan_host_counts_matches_uploaded_switchport_mode_spellings():
    """#40 `_vlan_host_counts` matched an EXACT, case-SENSITIVE `== "Access"`, while the same file used
    `.lower() == "access"` two other places -- the divergence textutils.is_trunk_mode exists to end. A
    webapp-uploaded snapshot carries "static access" / "dynamic access", so a VLAN with 300 endpoints
    sized as 0 hosts: the LLD allocated it a /24, never raised the needs->/24 flag, and the missing VLAN
    was explained away by the n_unsizable note as a querier-only VLAN on an uncollected core -- a
    FABRICATED cause for a delta the predicate itself created."""
    for mode in ("Access", "access", "static access", "dynamic access"):
        snap = {"interfaces": {"sw1": {f"Gi1/0/{i}": {"switchport_mode": mode, "vlan": "300"}
                                       for i in range(1, 301)}}}
        assert da._vlan_host_counts(snap) == {300: 300}, f"{mode!r} must count as an access port"
        plan = da._addressing_plan(snap, {"address_space": "10.0.0.0/16"})
        row = next(z for z in plan["subnets"] if str(z.get("vlan")) == "300")
        assert row["hosts"] == 300, f"{mode!r}: 300 endpoints must size the subnet"
        assert ">/24" in str(row.get("note") or ""), f"{mode!r}: 300 endpoints overflow a /24 -- must flag it"
        assert plan["n_unsizable"] == 0, f"{mode!r}: no fabricated 'unsizable VLAN' delta"
    # a trunk is still NOT an access port (the predicate must not swallow the whole port table)
    trunk = {"interfaces": {"sw1": {"Eth1/1": {"switchport_mode": "dynamic trunk", "vlan": "300"}}}}
    assert da._vlan_host_counts(trunk) == {}


# ------------------------------------------------------------------ #41 coverage guard off with no census
def test_scorecard_coverage_guard_fires_when_the_census_is_missing():
    """#41 the guard was `bool(sig["not_collected"])`, which is 0 BOTH when the whole estate was collected
    AND when the collection_completeness census is missing entirely. With no census the guard was OFF, so
    axes that infer health from "nothing bad observed" certified 'Strong' -- from ZERO collected devices,
    with no caveat. Reachable on an uploaded snapshot and whenever the census phase fails soft."""
    nocensus = {"fhrp": [], "failure_impact": [], "topology_links": [], "move_groups": []}
    sig = da._signals(nocensus)
    assert sig["collected"] == 0 and sig["not_collected"] == 0, "pre-condition: the ambiguous zero"
    assert sig["census_known"] is False
    card = {e["axis"]: e for e in da._scorecard(nocensus, sig)}
    for axis in ("availability", "load_balancing", "convergence", "security",
                 "scalability", "modularity", "simplicity", "cost", "manageability"):
        assert card[axis]["posture"] != "Strong", f"{axis} certified Strong from an absent census"
        assert card[axis]["score"] <= 3, f"{axis} scored uncapped from an absent census"
        assert "census" in card[axis]["evidence"].lower(), f"{axis} must DISCLOSE the missing census"

    # POSITIVE control (no over-correction): a census proving full collection may still read Strong.
    full = dict(nocensus, collection_completeness={"summary": {"inventory": 10, "complete": 10,
                                                               "not_collected": 0}})
    cardf = {e["axis"]: e for e in da._scorecard(full, da._signals(full))}
    assert cardf["availability"]["posture"] == "Strong" and "census" not in cardf["availability"]["evidence"]


# ------------------------------------------------------------------ #42 fabricated stratum evidence
def test_unparsed_ntp_stratum_is_never_rendered_as_the_literal_16():
    """#42 an unsynchronised device whose stratum was never parsed rendered `stratum 16` -- a specific,
    unobserved value stated as collected evidence and carried verbatim into the design doc and the deck.
    Secondary: the trigger compared `_st == 16` as an int, so a stratum parsed as the STRING '16' (foreign
    / uploaded snapshots) failed the test entirely."""
    unparsed = {"ntp": {"core1": {"synchronized": False}}}
    sig = da._signals(unparsed)
    assert sig["ntp_unsynced"] == ["core1 (stratum not reported)"]
    dec = da._d_ntp_sync(unparsed, sig)
    assert "stratum 16" not in dec["evidence"]["summary"].split("--")[0], "no fabricated per-device value"
    assert "core1 (stratum not reported)" in dec["evidence"]["summary"]
    # an OBSERVED stratum is reported verbatim, int or str
    assert da._signals({"ntp": {"c": {"synchronized": False, "stratum": 9}}})["ntp_unsynced"] == \
        ["c (stratum 9)"]
    assert da._signals({"ntp": {"c": {"stratum": "16"}}})["ntp_unsynced"] == ["c (stratum 16)"], \
        "a string '16' is the same observed state as an int 16"
    assert da._signals({"ntp": {"c": {"stratum": 16}}})["ntp_unsynced"] == ["c (stratum 16)"]
    # unchanged: a device with no definitive sync verdict is NOT flagged
    assert da._signals({"ntp": {"c": {"stratum": 3, "synchronized": True}}})["ntp_unsynced"] == []
    assert da._signals({"ntp": {"c": {}}})["ntp_unsynced"] == []


# ------------------------------------------------------------------ #43 uncomputed subset relation
def test_dhcpv6_guard_clause_reports_the_real_intersection_not_a_parallel_count():
    """#43 the RA-Guard-open and DHCPv6-Guard-open sets are accumulated INDEPENDENTLY over the same
    switches, yet the sentence said "{dhcp} of them" -- rendering "1 dual-stack access switch(es) ... 2 of
    them also have no DHCPv6-Guard" while evidence.devices named a switch that was already DHCPv6-Guard
    compliant. The engineer fixes a compliant box and leaves the exposed ones untouched."""
    ifs = {h: {"Gi0/1": {"switchport_mode": "Access"}} for h in ("a1", "a2", "a3")}
    snap = {"interfaces": ifs, "ipv6_fhs": {
        "a1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False, "dhcp_guard_present": True},
        "a2": {"dualstack": True, "ipv6_svi_vlans": [20], "ra_guard_present": True, "dhcp_guard_present": False},
        "a3": {"dualstack": True, "ipv6_svi_vlans": [30], "ra_guard_present": True, "dhcp_guard_present": False}}}
    sig = da._signals(snap)
    assert sig["ipv6_fhs_open_hosts"] == ["a1"] and sig["ipv6_fhs_open_dhcp"] == 2   # the two parallel counts
    assert sig["ipv6_fhs_open_both"] == 0, "a1 HAS DHCPv6-Guard -> the intersection is empty"
    assert sig["ipv6_fhs_dhcp_only_hosts"] == ["a2", "a3"]
    text = da._d_ipv6_fhs(snap, sig)["evidence"]["summary"]
    assert "2 of them" not in text, "the subset claim was never computed"
    assert "a2, a3" in text, "the actually-exposed switches must be NAMED"

    # a real intersection IS reported as one, with the host named
    both = {"interfaces": ifs, "ipv6_fhs": {
        "a1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False,
               "dhcp_guard_present": False}}}
    sig2 = da._signals(both)
    assert sig2["ipv6_fhs_open_both"] == 1 and sig2["ipv6_fhs_open_both_hosts"] == ["a1"]
    t2 = da._d_ipv6_fhs(both, sig2)["evidence"]["summary"]
    assert "1 of them (a1) also have no DHCPv6-Guard" in t2
    assert "A further" not in t2, "no phantom second population"


# ------------------------------------------------------------------ #50 Past-EoS counted two ways
def test_past_eos_is_one_disposition_across_the_bom_and_the_narrative():
    """#50 Past-EoS (past end-of-SALE, still supported) landed in _replacement_bom's `refresh_soon`
    (procure a replacement) while sig['near'] matched only "near" and `retain = collected - eol` counted
    the SAME device as a supportable asset to carry forward. Procurement ordered to one number and the
    migration plan assumed the other, in ONE blueprint. The three dispositions must PARTITION the
    lifecycle-assessed fleet."""
    snap = {"lifecycle_risk": {"per_device": [
                {"host": "a", "band": "Past-LDoS", "model": "WS-C4948E"},
                {"host": "b", "band": "Past-EoS", "model": "WS-C2960X"},
                {"host": "c", "band": "Past-EoS", "model": "WS-C2960X"},
                {"host": "d", "band": "Near-LDoS", "model": "N5K"},
                {"host": "e", "band": "Active", "model": "C9300"}]},
            "collection_completeness": {"summary": {"inventory": 5, "complete": 5, "not_collected": 0}}}
    sig = da._signals(snap)
    bom = da._replacement_bom(snap)
    assert sig["eol"] == 1 == bom["n_replace"], "replace class: Past-LDoS only"
    assert sig["near"] == 3 == bom["n_refresh"], "refresh class must match the BoM (Near-LDoS + Past-EoS)"
    dim = next(d for d in da.compute_target_state(snap)["dimensions"]
               if d["area"] == "Hardware lifecycle disposition")
    assert "carry ~1 fully-supported asset(s) forward" in dim["target"], dim["target"]
    # the partition holds: replace + refresh + retain == the lifecycle-assessed fleet, no device twice
    assert sig["eol"] + sig["near"] + 1 == sig["lifecycle_assessed"] == 5
    assert "3 approaching-LDoS or past-EoS" in dim["current"], dim["current"]
