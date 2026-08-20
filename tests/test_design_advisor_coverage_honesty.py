"""Regression guards for the 2026-07-28 whole-repo review, design-brain tranche
(docs/review-findings-2026-07-28.md findings #38, #39, #40, #41, #42, #43, #50).

Every one of these is the same defect class the repo's doctrine forbids outright: an absent capture, an
unparsed field or an unrecognised token turned into a positive claim about the network -- here mostly in
the "not observed becomes observed BROKEN" direction, which drives a High design decision (and the BoM,
the LLD subnet sizing and the deck) off evidence that was never collected. Each test FAILS on the
pre-fix code, so reverting the fix regresses here.
"""
import cisco_toolkit.design_advisor as da
from cisco_toolkit import analyze   # real-producer fixtures for the multicast authority tests below


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
    """#50 Past-EoS (after end-of-SALE but before recorded LDoS) landed in _replacement_bom's `refresh_soon`
    (procure a replacement) while sig['near'] matched only "near" and `retain = collected - eol` counted
    the SAME device as a carry-forward asset. Procurement ordered to one number and the
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
    assert "identify ~1 pre-EoS date-band asset(s) as carry-forward candidates" in dim["target"], dim["target"]
    assert "support entitlement not assessed" in dim["target"], dim["target"]
    assert "fully-supported" not in dim["target"]
    # the partition holds: replace + refresh + retain == the lifecycle-assessed fleet, no device twice
    assert sig["eol"] + sig["near"] + 1 == sig["lifecycle_assessed"] == 5
    assert "3 approaching-LDoS or past-EoS" in dim["current"], dim["current"]


# ------------------------------------------- lifecycle-band coverage is NOT collection coverage (cost axis)
def _cost_axis(bands):
    """Scorecard `cost` entry for a FULLY COLLECTED fleet with the given lifecycle bands."""
    snap = {"collection_completeness": {"summary": {"not_collected": 0, "inventory": len(bands),
                                                    "complete": len(bands)}},
            "lifecycle_risk": {"per_device": [{"host": f"h{i}", "band": b, "model": "WS-C6509-E"}
                                              for i, b in enumerate(bands)]}}
    return next(a for a in da._scorecard(snap, da._signals(snap)) if a["axis"] == "cost")


def test_cost_axis_cannot_read_Comfortable_when_the_fleet_was_never_lifecycle_banded():
    """The scorecard already clamped `cost` on `coverage_gap` -- but that measures COLLECTION coverage,
    a different axis from lifecycle-band coverage.

    A fleet can be 100% collected (census taken, `not_collected == 0`, so `coverage_gap` is False) and
    still have every platform unmatched by the offline EoX KB. `eol` and `near` then both count 0, and
    the axis scored a top 4/4 'Comfortable' emitting "0 past-LDoS + 0 near-LDoS/past-EoS asset(s)" --
    byte-for-byte the same score, posture and evidence sentence as a fully-assessed healthy fleet. The
    reader had nothing to distinguish "no refresh CapEx is due" from "we could not tell".

    Refresh CapEx is not comfortable when the lifecycle of the assets it would be spent on is unknown.
    """
    unknown = _cost_axis(["Unknown"] * 3)
    assert unknown["posture"] != "Comfortable", "an undetermined fleet was certified affordable"
    assert unknown["score"] <= 2, unknown
    assert "could NOT be lifecycle-banded" in unknown["evidence"], "the gap is not disclosed to the reader"
    assert "no exact EoX match" in unknown["evidence"]
    assert "source/date authority was withheld" in unknown["evidence"]

    # Non-vacuity: the clamp must be driven by the unknowns, not always-on. A genuinely assessed,
    # fully pre-EoS-date-banded fleet must keep its top score -- otherwise the axis is uninformative in the
    # other direction and the guard proves nothing.
    healthy = _cost_axis(["Active"] * 3)
    assert healthy["posture"] == "Comfortable" and healthy["score"] == 4, healthy
    assert "could NOT be lifecycle-banded" not in healthy["evidence"]

    # The two cases must now be DISTINGUISHABLE, which is the whole point.
    assert (unknown["score"], unknown["evidence"]) != (healthy["score"], healthy["evidence"])


def test_cost_axis_still_reports_real_end_of_life_pressure_undiluted():
    """A real past-LDoS asset must keep driving the axis on its own evidence, not the coverage note."""
    real = _cost_axis(["Past-LDoS", "Active"])
    assert real["score"] <= 2 and "1 past-LDoS" in real["evidence"]
    assert "could NOT be lifecycle-banded" not in real["evidence"], "no unknowns here to disclose"


# ------------------------------------ "never assessed" is not "assessed and supported" (cost axis, #2)
def _cost_axis_snap(snap):
    return next(a for a in da._scorecard(snap, da._signals(snap)) if a["axis"] == "cost")


_FULL_CENSUS = {"summary": {"not_collected": 0, "inventory": 3, "complete": 3}}
_THREE_DEVICES = {f"h{i}": {"model": "WS-C6509-E"} for i in range(3)}


def test_cost_axis_cannot_read_Comfortable_when_the_lifecycle_axis_produced_NOTHING():
    """`lifecycle_unknown` is derived from len(per_device), so it is 0 both when every device banded
    Active AND when the axis emitted no rows at all -- and the clamp keyed on it therefore fell open
    on the second case. Both are reachable with no exception raised: COLLECT_PARSE runs the phase
    under `_run_phase(..., _default={})`, and a collection whose parse yields no device rows gives
    `per_device: []` outright.

    Measured before the fix, on a FULLY COLLECTED fleet (coverage_gap False):
        lifecycle_risk ABSENT -> score 4 "Comfortable"
        per_device EMPTY      -> score 4 "Comfortable"
    byte-identical to the healthy control below. The existing control `_cost_axis(["Active"]*3)`
    cannot catch this: it asserts exactly the value the defect produces.
    """
    absent = _cost_axis_snap({"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES})
    empty = _cost_axis_snap({"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES,
                             "lifecycle_risk": {"per_device": []}})
    for label, a in (("lifecycle_risk absent", absent), ("per_device empty", empty)):
        assert a["posture"] != "Comfortable", f"{label}: an unassessed fleet was certified affordable"
        assert a["score"] <= 2, (label, a)
        assert "never assessed by the lifecycle axis" in a["evidence"], (label, a["evidence"])

    # NON-VACUITY 1: a fleet that WAS assessed into the pre-EoS date band keeps the top score and gains
    # no disclosure -- the clamp is not always-on.
    healthy = _cost_axis_snap({"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES,
                               "lifecycle_risk": {"per_device": [
                                   {"host": f"h{i}", "band": "Active"} for i in range(3)]}})
    assert healthy["posture"] == "Comfortable" and healthy["score"] == 4, healthy
    assert "could NOT be lifecycle-banded" not in healthy["evidence"], healthy["evidence"]

    # NON-VACUITY 2: the two never-assessed cases must be DISTINGUISHABLE from the healthy one,
    # which is the entire point -- and from the banded-Unknown case, which is a different fact.
    assert (absent["score"], absent["evidence"]) != (healthy["score"], healthy["evidence"])
    unknown = _cost_axis_snap({"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES,
                               "lifecycle_risk": {"per_device": [
                                   {"host": f"h{i}", "band": "Unknown"} for i in range(3)]}})
    assert "never assessed by the lifecycle axis" not in unknown["evidence"], unknown["evidence"]
    assert "could NOT be lifecycle-banded" in unknown["evidence"], unknown["evidence"]


def test_target_state_still_speaks_about_lifecycle_when_the_axis_produced_nothing():
    """The Hardware-lifecycle target-state dimension was gated on eol/near/not_collected/unknown --
    all 0 when the axis produced no rows -- so the dimension vanished entirely and the reader infers
    there is nothing to say about refresh."""
    snap = {"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES}
    dim = next((d for d in da.compute_target_state(snap)["dimensions"]
                if d["area"] == "Hardware lifecycle disposition"), None)
    assert dim is not None, "the lifecycle dimension disappeared for an unassessed fleet"
    assert "NOT lifecycle-assessed at all" in dim["current"], dim["current"]
    assert "never lifecycle-assessed" in dim["target"], dim["target"]

    # NON-VACUITY: a fully-banded pre-EoS date-position fleet must not acquire the never-assessed
    # clause; this fixture does not make a support-entitlement claim.
    ok = {"collection_completeness": _FULL_CENSUS, "devices": _THREE_DEVICES,
          "lifecycle_risk": {"per_device": [{"host": f"h{i}", "band": "Active"} for i in range(3)]}}
    dim_ok = next((d for d in da.compute_target_state(ok)["dimensions"]
                   if d["area"] == "Hardware lifecycle disposition"), None)
    assert dim_ok is None or "NOT lifecycle-assessed at all" not in dim_ok["current"], dim_ok


def test_replacement_bom_includes_devices_that_received_no_lifecycle_row():
    """No-row assets need a visible evidence-resolution quantity; they are not an empty/healthy BoM."""
    snap = {
        "collection_completeness": {"summary": {"inventory": 2, "complete": 2, "not_collected": 0}},
        "devices": {"a": {"model": "MODEL-A"}, "b": {"model": "MODEL-B"}},
        "lifecycle_risk": {"per_device": []},
    }
    bom = da._replacement_bom(snap)
    assert bom["n_replace"] == 0 and bom["n_refresh"] == 0
    assert bom["n_undetermined"] == 2 and bom["n_not_assessed"] == 2
    assert bom["undetermined"] == [["MODEL-A", 1], ["MODEL-B", 1]]
    assert "no lifecycle row" in bom["note"]


# ---------------------------------------- r9 EXITS B/C: a CURATED on-air classification, said in its own voice
# `analyze.compute_multicast_intelligence` classifies a group as on-air / Broadcast-AV from the OFFLINE
# registry's CURATED media semantics; on the shipped pack NOTHING is authoritative (n_av_groups_authoritative
# == 0), and that same curated flag is what escalates a MAC-alias risk from Medium to High. design_advisor
# authors two sentences off that judgement -- the "Media / timing fabric" target-state dimension (rendered
# verbatim by design.py:895-899 under a column headed "Current (observed)", and by the explorer at
# blast_radius_explorer.html:7381) and the `_d_mcast` evidence summary (design.py:765 / :774). Both must say
# what the number rests on. Fixture policy: every `multicast_intelligence` below comes from the REAL producer.

_AV_ALIAS = ["224.0.1.129", "239.128.1.129"]      # both -> MAC 01:00:5e:00:01:81; 224.0.1.129 is registry Broadcast-AV
_PLAIN_ALIAS = ["239.127.0.1", "239.255.0.1"]     # both -> MAC 01:00:5e:7f:00:01; neither is classified on-air
# What an AUTHORITATIVE pack would publish for the same overlap. Still the real producer -- it derives on_air,
# on_air_authoritative, has_av_authoritative and the whole summary census itself from these registry labels.
_AUTH_GROUPS = [
    {"group": "224.0.1.129", "name": "PTP-primary", "category": "Broadcast-AV", "broadcast": True,
     "source": "IANA", "assignment_authoritative": True, "semantics_authoritative": True,
     "overlay_status": "iana", "assignment_source": "IANA", "semantics_source": "IANA"},
    {"group": "239.128.1.129", "name": "", "category": "Multicast", "broadcast": False,
     "source": "observed", "assignment_authoritative": False, "semantics_authoritative": False,
     "overlay_status": "curated-only"},
]


def _mi(igmp_groups=None, ptp=None, classified_groups=None):
    """`multicast_intelligence` straight from analyze.compute_multicast_intelligence (no hand-shaped dicts):
    either driven through the shipped offline registry via compute_service_map, or handed classified-group
    records carrying the registry authority labels. The producer computes every authority field under test."""
    if classified_groups is not None:
        sm = {"multicast": {"classified_groups": classified_groups, "ptp": dict(ptp or {})}}
    else:
        sm = analyze.compute_service_map({}, {}, igmp_groups=list(igmp_groups or []), ptp=dict(ptp or {}))
    return analyze.compute_multicast_intelligence(sm, {})


def _media_dim(mi):
    return next((d for d in da.compute_target_state({"multicast_intelligence": mi})["dimensions"]
                 if d["area"] == "Media / timing fabric"), None)


def test_multicast_risk_count_states_what_the_severities_it_folds_in_rest_on():
    """EXIT C. `sig["mcast_risks"]` is a bare len() over `multicast_intelligence.risks`, and _d_mcast renders
    it as "N multicast risk(s) were observed" -- one number mixing risks that are arithmetic on observed group
    addresses with a High whose promotion comes ENTIRELY from the registry's curated Broadcast-AV label. The
    count may stay (disclosure, not re-scoring); the reader must be able to see what it rests on."""
    mi = _mi(_AV_ALIAS)
    # the shipped-pack reality this exit is about: one on-air group, ZERO of them authoritative
    assert mi["summary"]["n_av_groups"] == 1 and mi["summary"]["n_av_groups_authoritative"] == 0
    assert [r["severity"] for r in mi["risks"]] == ["High"]
    snap = {"multicast_intelligence": mi}
    sig = da._signals(snap)
    assert sig["mcast_risks"] == 1 and sig["mcast_av_escalations"] == 1
    dec = da._d_mcast(snap, sig)
    ev = dec["evidence"]["summary"]
    assert "1 multicast risk(s) were observed" in ev, ev
    assert "High ONLY because a member group is classified Broadcast-AV" in ev, ev
    assert "CURATED offline-registry semantics, NOT an authoritative source" in ev, ev
    assert "arithmetic on the observed group addresses" in ev, ev
    # the field citation must point at the flag the disclosure rests on, not just at `risks`
    assert "multicast_intelligence.mac_aliases[].has_av_authoritative" in dec["evidence"]["fields"], dec
    assert dec["priority"] == "High" and dec["evidence"]["count"] == 1   # DISCLOSURE, not re-scoring

    # NON-VACUITY 1: a MAC overlap with no on-air member is observed fact end to end -> no caveat is added,
    # and the citation list stays exactly as it was. A caveat that is always on says nothing.
    plain = {"multicast_intelligence": _mi(_PLAIN_ALIAS)}
    sig_p = da._signals(plain)
    assert sig_p["mcast_risks"] == 1 and sig_p["mcast_av_escalations"] == 0
    assert sig_p["mcast_risk_basis"] == ""
    dec_p = da._d_mcast(plain, sig_p)
    assert "Broadcast-AV" not in dec_p["evidence"]["summary"], dec_p["evidence"]["summary"]
    assert "CURATED" not in dec_p["evidence"]["summary"], dec_p["evidence"]["summary"]
    assert dec_p["evidence"]["fields"] == ["multicast_intelligence.querier.gap_vlans",
                                           "multicast_intelligence.risks"]

    # NON-VACUITY 2: a fleet with no multicast estate at all keeps the detector silent (no new cry-wolf).
    empty = {"multicast_intelligence": _mi([])}
    assert da._d_mcast(empty, da._signals(empty)) is None

    # NON-VACUITY 3: an AUTHORITATIVE pack reports the SAME High risk in a different voice -- the disclosure
    # tracks the evidence, it is not a blanket "everything here is curated" disclaimer.
    auth = {"multicast_intelligence": _mi(classified_groups=_AUTH_GROUPS)}
    sig_a = da._signals(auth)
    ev_a = da._d_mcast(auth, sig_a)["evidence"]["summary"]
    assert sig_a["mcast_av_escalations"] == 1
    assert "1 on an AUTHORITATIVE registry source" in ev_a, ev_a
    assert "CURATED" not in ev_a, ev_a


def test_multicast_risk_basis_fails_closed_when_the_authority_flag_is_absent_or_malformed():
    """The fail-open shape this repo keeps re-finding: keying on key PRESENCE plus a coercion that maps
    absent/None/str to a confident zero -- here it would read "no escalation is authoritative" (a claim) or,
    worse, count a truthy non-bool as authoritative. Only a real `True` may read as authoritative."""
    for label, mangle in (("key stripped", lambda a: a.pop("has_av_authoritative")),
                          ("null", lambda a: a.update(has_av_authoritative=None)),
                          ("int 1", lambda a: a.update(has_av_authoritative=1)),
                          ("string", lambda a: a.update(has_av_authoritative="yes"))):
        mi = _mi(_AV_ALIAS)
        for a in mi["mac_aliases"]:
            mangle(a)
        basis = da._signals({"multicast_intelligence": mi})["mcast_risk_basis"]
        assert "authority is NOT ASSESSED in this snapshot" in basis, (label, basis)
        assert "AUTHORITATIVE registry source" not in basis, (label, basis)

    # INCOHERENT census: an escalated alias is published but the risk list is not -- refuse to state a ratio
    # a reader cannot check (mirrors runbook._av_authority's incoherence branch) rather than render "1 of 0".
    mi = _mi(_AV_ALIAS)
    mi["risks"] = []
    mi["querier"]["gap_vlans"] = ["10"]           # so the detector still fires and the disclosure is rendered
    snap = {"multicast_intelligence": mi}
    sig = da._signals(snap)
    assert sig["mcast_risks"] == 0 and sig["mcast_av_escalations"] == 1
    ev = da._d_mcast(snap, sig)["evidence"]["summary"]
    assert "BASIS INCOHERENT" in ev, ev
    assert "High ONLY because" not in ev, ev


def test_media_timing_dimension_qualifies_its_curated_on_air_count():
    """EXIT B. The dimension detail said "... N audio/video multicast group(s) on the flat fabric." and was
    labelled Observed, while N is a curated registry judgement -- and the dimension's own GATE
    (n_clocks > 0 or n_av > 0) fires on that curated count alone. Chosen fix: keep the gate (the groups ARE
    joined on the fabric; suppressing the dimension would hide a real media estate) but qualify the count and
    stop calling a classification-only dimension "Observed"."""
    dim = _media_dim(_mi(_AV_ALIAS))
    assert dim, "an AV multicast estate must still raise the media/timing dimension"
    assert "NONE of them classified on-air by an authoritative source" in dim["current"], dim["current"]
    assert "CURATED offline-registry classification, not a measurement" in dim["current"], dim["current"]
    assert "raised by that multicast classification ALONE" in dim["current"], dim["current"]
    assert dim["confidence"] == "Curated-classification", dim
    assert dim["confidence"] != "Observed", "a curated hint must not be rendered as observed evidence"

    # NON-VACUITY 1: a PTP-only media estate (real observed clocks, no AV groups) gets NO on-air caveat and
    # stays Observed -- the qualifier attaches to the AV count, not to the dimension.
    ptp_only = _media_dim(_mi([], ptp={"sw1": {"operational": True, "grandmaster": "gm1"},
                                       "sw2": {"operational": False, "grandmaster": ""}}))
    assert ptp_only and ptp_only["confidence"] == "Observed", ptp_only
    assert "2 PTP-capable switch(es)" in ptp_only["current"], ptp_only["current"]
    assert "CURATED" not in ptp_only["current"] and "NOT ASSESSED" not in ptp_only["current"], ptp_only
    assert "raised by that multicast classification ALONE" not in ptp_only["current"], ptp_only

    # NON-VACUITY 2: a fleet with no media estate at all raises no dimension (unchanged).
    assert _media_dim(_mi([])) is None

    # NON-VACUITY 3: an authoritative pack states the ratio and keeps Observed.
    auth = _media_dim(_mi(classified_groups=_AUTH_GROUPS))
    assert auth and auth["confidence"] == "Observed", auth
    assert "1 of 1 on-air classification(s) rest on an authoritative source" in auth["current"], auth["current"]
    assert "raised by that multicast classification ALONE" not in auth["current"], auth["current"]


def test_media_dimension_av_authority_fails_closed_on_an_unusable_census():
    """Same fail-open shape on the summary census: absent / null / string / bool must read NOT ASSESSED, never
    as the assertion "zero of them are authoritative" and never as authoritative."""
    for label, value in (("absent", KeyError), ("null", None), ("string", "many"), ("bool", True),
                         ("nan", float("nan"))):
        mi = _mi(_AV_ALIAS)
        if value is KeyError:
            mi["summary"].pop("n_av_groups_authoritative")
        else:
            mi["summary"]["n_av_groups_authoritative"] = value
        dim = _media_dim(mi)
        assert "authority NOT ASSESSED in this snapshot" in dim["current"], (label, dim["current"])
        assert "rest on an authoritative source" not in dim["current"], (label, dim["current"])
        assert dim["confidence"] == "Curated-classification", (label, dim)

    # ...and the same on an INCOHERENT pair: refuse the ratio instead of rendering "7 of 1".
    mi = _mi(_AV_ALIAS)
    mi["summary"]["n_av_groups_authoritative"] = 7
    dim = _media_dim(mi)
    assert "census INCOHERENT" in dim["current"], dim["current"]
    assert "7 classification(s) reported as authoritative out of 1 on-air group(s)" in dim["current"], dim["current"]


def test_the_oncritical_isolation_decision_discloses_that_its_tier_is_curated():
    """`_d_oncrit_seg` raises a **High** decision off `segmentation.domains[].tier == on-air-critical`.

    The L3 reachability and the gateway-ACL coverage in that sentence ARE measured. Which domains are
    "on-air-critical" is NOT: that tier derives from the same CURATED offline-registry media semantics
    as every other on-air claim, and it is what makes this High. Stating all three in one voice lets a
    reader take the curated part for an observed one.

    Asserted on `evidence.summary` because that is where `_decision`'s second positional lands
    (design_advisor.py:1729 `_decision(pid, summary, ...)` -> `evidence: {"summary": summary, ...}`) --
    NOT a top-level string field. Three consumers render it: blast_radius_explorer.html:7422 (decision
    card), :8481 (causal-flow trigger) and webapp/frontend/src/components/DesignBlueprint.tsx:45.
    """
    sig = {"oncrit_exposed": 2, "oncrit_domains": ["Studio-A", "Studio-B"], "gw_acl_cov": 0.0,
           "gw_acl_cov_known": False, "n_gateways": 0, "n_gateways_known": False}

    def summary_for(mi):
        return da._d_oncrit_seg({"multicast_intelligence": mi}, sig)["evidence"]["summary"]

    # the measured/curated split must be stated in every authority state, including the good one
    for mi in ({}, {"summary": {"n_av_groups": 5, "n_av_groups_authoritative": 0}},
               {"summary": {"n_av_groups": 5, "n_av_groups_authoritative": 2}}):
        s = summary_for(mi)
        assert "ARE measured" in s and "on-air tiering is not" in s, s

    # and the authority qualifier itself must track the census
    assert "NOT ASSESSED" in summary_for({})
    assert "NONE of them" in summary_for({"summary": {"n_av_groups": 5, "n_av_groups_authoritative": 0}})
    assert "2 of 5" in summary_for({"summary": {"n_av_groups": 5, "n_av_groups_authoritative": 2}})

    # NON-VACUITY: the decision must still not fire when nothing is exposed, or the disclosure is
    # attached to a decision that should not exist at all.
    assert da._d_oncrit_seg({"multicast_intelligence": {}}, {**sig, "oncrit_exposed": 0}) is None


def test_the_av_authority_census_rejects_a_numeric_STRING():
    """`_as_int` delegates to `textutils._as_num`, which does `float(x)` -- so the JSON string "1"
    parsed to 1 and the census read USABLE AND AUTHORITATIVE off a malformed field, while this
    module's own docstring promised strings yield `assessed=False`.

    The earlier probe missed it by testing with "many", which fails `float()` and therefore passes for
    the wrong reason: a malformed-value probe must include the malformed values that PARSE.
    """
    def assessed(raw):
        return da._av_auth_census({"summary": {"n_av_groups": 5, "n_av_groups_authoritative": raw}})[2]

    for raw in ("1", "0", "3", " 2 ", "many", True, False, None, {}, [], -1,
                3.5, float("inf"), float("nan")):
        assert assessed(raw) is False, f"{raw!r} was accepted as a usable census"

    # NON-VACUITY: real counts must still read as measured, including JSON's integral-float wire form
    # (JSON has no int/float distinction, so 3.0 is a legitimate spelling of 3 -- 3.5 is not).
    for raw in (0, 1, 5, 3.0):
        assert assessed(raw) is True, f"{raw!r} was rejected but is a valid census"


def test_the_media_dimension_gate_and_its_qualifier_share_one_definition_of_usable():
    """Two guards in this file disagreed about whether an INCOHERENT census counts as authority.

    `_av_authority` refuses to state a ratio when `n_auth > n_av` ("the authority split cannot be
    stated for this snapshot"), but the target-state gate inlined `_assessed and _n_auth > 0`, which
    is TRUE for that same pair. So a snapshot reporting 7 authoritative out of 3 groups rendered
    confidence "Observed" with no disclaimer, directly beside a sentence saying the split could not be
    stated. A census the module has already declared unusable cannot also be evidence of authority.

    Pinned as an AGREEMENT property between the two, not as two separate expectations: that is the
    defect shape, and a future change to either side fails here.
    """
    def state(n_auth, n_av, clocks=0):
        mi = {"summary": {"n_av_groups": n_av, "n_av_groups_authoritative": n_auth},
              "ptp": {"n_clocks": clocks, "n_operational": 0, "grandmasters": []}}
        d = next(x for x in da.compute_target_state({"multicast_intelligence": mi})["dimensions"]
                 if x["area"] == "Media / timing fabric")
        return d["confidence"], da._av_authority(mi)

    for n_auth, n_av in ((7, 3), (0, 5), (None, 5), ("1", 5)):
        conf, note = state(n_auth, n_av)
        assert conf == "Curated-classification", (
            f"census {n_auth!r}/{n_av!r}: the qualifier says {note.strip()[:60]!r} but the dimension "
            f"is marked {conf!r}")
        assert not da._av_auth_backed({"summary": {"n_av_groups": n_av,
                                                   "n_av_groups_authoritative": n_auth}})

    # NON-VACUITY, both directions -- otherwise the gate is always-on and says nothing.
    for n_auth, n_av in ((2, 5), (5, 5)):
        conf, _ = state(n_auth, n_av)
        assert conf == "Observed", f"a coherent {n_auth} of {n_av} census must stay Observed"
    # and OBSERVED PTP evidence keeps the dimension Observed even on a wholly curated census: the
    # gate exists for a dimension raised by the classification ALONE.
    assert state(0, 5, clocks=3)[0] == "Observed"
