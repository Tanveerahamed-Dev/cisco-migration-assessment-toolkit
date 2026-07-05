"""Tests for the cutover dry-run simulator (MASTER_PLAN §4.2).

Small SYNTHETIC snapshots (never the golden fixture) so assertions are stable across a re-bless. The
headline scenario: an ordered 3-step wave where a MIDDLE step strands a flow and a LATER step restores a
flow — the narrative names the window; the input snapshot is proven unchanged after the run (deep-copy).
"""
import copy

from cisco_toolkit import cutover_sim


def _l3_snap():
    """A reaches 10.0.9.0/24 via X, but a Null0 /25 blackholes 10.0.9.128/25 (so 10.0.9.200 is unreachable at
    baseline). A reaches 10.0.5.0/24 via Y. Shutting A->Y strands 10.0.5.x; removing the Null0 restores
    10.0.9.200 — a clean strand-then-restore across the wave."""
    return {"routes": {
        "A": [{"prefix": "10.0.1.0/24", "source": "connected", "out_intf": "Vlan1"},
              {"prefix": "10.0.9.0/24", "source": "static", "next_hop": "10.0.12.2", "out_intf": "Gi0/0"},
              {"prefix": "10.0.9.128/25", "source": "static", "next_hop": "", "out_intf": "Null0"},
              {"prefix": "10.0.5.0/24", "source": "static", "next_hop": "10.0.13.2", "out_intf": "Gi0/1"}],
        "X": [{"prefix": "10.0.12.0/24", "source": "connected", "out_intf": "Gi0/0"},
              {"prefix": "10.0.9.0/24", "source": "connected", "out_intf": "Gi0/2"}],
        "Y": [{"prefix": "10.0.13.0/24", "source": "connected", "out_intf": "Gi0/0"},
              {"prefix": "10.0.5.0/24", "source": "connected", "out_intf": "Gi0/2"}],
    }}


_PAIRS = [("10.0.1.1", "10.0.9.200"), ("10.0.1.1", "10.0.5.50")]


def test_three_step_strand_then_restore_with_named_window():
    snap = _l3_snap()
    steps = [
        {"action": "fail_node", "id": "__nope__"},                 # step 0: no-op
        {"action": "shut_link", "host": "A", "interface": "Gi0/1"},  # step 1 (middle): strands 10.0.5.50
        {"action": "shut_link", "host": "A", "interface": "Null0"},  # step 2 (later): restores 10.0.9.200
    ]
    res = cutover_sim.simulate_cutover(snap, steps, pairs=_PAIRS)
    assert res["schema"] == "cutover_sim/1"
    s0, s1, s2 = res["steps"]

    # step 0 is a genuine no-op (matched no host)
    assert s0["is_noop"] is True
    assert s0["newly_lost_flows"] == [] and s0["recovered_flows"] == []

    # step 1 (the middle step) strands the 10.0.5.50 flow
    assert s1["is_noop"] is False
    lost1 = {(p["src"], p["dst"]) for p in s1["newly_lost_flows"]}
    assert ("10.0.1.1", "10.0.5.50") in lost1
    assert s1["recovered_flows"] == []

    # step 2 (the later step) restores the 10.0.9.200 flow the blackhole had stranded
    rec2 = {(p["src"], p["dst"]) for p in s2["recovered_flows"]}
    assert ("10.0.1.1", "10.0.9.200") in rec2

    # the narrative names the window in plain English
    assert "recover" in s2["narrative"].lower()
    assert "lose their path" in s1["narrative"].lower()

    # worst_step is the middle step (the one with the most newly-lost flows)
    assert res["worst_step"] == 1
    assert res["summary"]["total_newly_lost"] == 1
    assert res["summary"]["total_recovered"] == 1
    assert res["summary"]["n_noop_steps"] == 1


def test_snapshot_is_deep_copied_and_never_mutated():
    snap = _l3_snap()
    before = copy.deepcopy(snap)
    steps = [
        {"action": "shut_link", "host": "A", "interface": "Gi0/1"},
        {"action": "fail_node", "id": "X"},
        {"action": "shut_link", "host": "A", "interface": "Null0"},
    ]
    cutover_sim.simulate_cutover(snap, steps, pairs=_PAIRS)
    assert snap == before                                   # deep-copy proof: the input is byte-for-byte intact


def test_noop_step_is_flagged_and_reachability_unchanged():
    snap = _l3_snap()
    # a shut_link on an interface that owns no route changes nothing
    res = cutover_sim.simulate_cutover(
        snap, [{"action": "shut_link", "host": "A", "interface": "Gi9/9"}], pairs=_PAIRS)
    s = res["steps"][0]
    assert s["is_noop"] is True
    assert s["newly_lost_flows"] == [] and s["recovered_flows"] == []
    assert "no effect" in s["narrative"].lower()
    assert res["worst_step"] is None                        # nothing lost -> no worst step


def test_unknown_action_is_reported_noop_not_silent():
    snap = _l3_snap()
    res = cutover_sim.simulate_cutover(snap, [{"action": "teleport_switch", "id": "A"}], pairs=_PAIRS)
    s = res["steps"][0]
    assert s["is_noop"] is True
    assert s["action"] == "teleport_switch"                 # surfaced verbatim, never swallowed
    assert res["summary"]["n_noop_steps"] == 1


def test_worst_step_selection_picks_max_loss_earliest_on_tie():
    snap = _l3_snap()
    # two steps each strand one flow; worst_step must be the EARLIEST on a tie
    steps = [
        {"action": "shut_link", "host": "A", "interface": "Gi0/1"},  # strands 10.0.5.50
        {"action": "shut_link", "host": "A", "interface": "Gi0/0"},  # strands 10.0.9.10 (via X)
    ]
    pairs = [("10.0.1.1", "10.0.5.50"), ("10.0.1.1", "10.0.9.10")]
    res = cutover_sim.simulate_cutover(snap, steps, pairs=pairs)
    assert len(res["steps"][0]["newly_lost_flows"]) == 1
    assert len(res["steps"][1]["newly_lost_flows"]) == 1
    assert res["worst_step"] == 0                           # tie -> earliest


# ------------------------------------------------------------------ L2 integration ---

def _l2_snap():
    """core1 is the VLAN-10 root and the group-10 Active; dist1 is the alternate/standby with preempt on."""
    return {
        "routes": {"core1": [{"prefix": "10.0.10.0/24", "source": "connected", "out_intf": "Vlan10"}],
                   "dist1": [{"prefix": "10.0.10.0/24", "source": "connected", "out_intf": "Vlan10"}]},
        "stp_roots": {
            "core1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                             "bridge_priority": 4096}},
            "dist1": {"10": {"root_priority": 4096, "root_address": "bbbb.0000.0002", "is_root": False,
                             "bridge_priority": 8192}},
        },
        "fhrp_detail": {
            "core1": [{"ifname": "Vlan10", "group": "10", "state": "Active", "priority": 110,
                       "preempt": True, "vip": "10.0.10.1", "version": 2}],
            "dist1": [{"ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 100,
                       "preempt": True, "vip": "10.0.10.1", "version": 2}],
        },
    }


def test_fail_node_step_reports_stp_reroot_and_fhrp_takeover():
    snap = _l2_snap()
    res = cutover_sim.simulate_cutover(snap, [{"action": "fail_node", "id": "core1"}])
    s = res["steps"][0]
    assert s["removed_hosts"] == ["core1"]
    # STP: VLAN 10 re-roots to dist1
    assert any(r["vlan"] == "10" and r["new_root"] == "dist1" and not r["indeterminate"]
               for r in s["stp_reroots"])
    # FHRP: group 10 takes over to dist1
    assert any(r["group"] == "10" and r["new_active"] == "dist1" for r in s["fhrp_takeovers"])
    assert "re-root" in s["narrative"] or "take over" in s["narrative"]


def test_move_fhrp_active_flips_state_without_touching_routes():
    snap = _l2_snap()
    res = cutover_sim.simulate_cutover(
        snap, [{"action": "move_fhrp_active", "ifname": "Vlan10", "group": "10", "to_host": "dist1"}])
    s = res["steps"][0]
    assert s["is_noop"] is False                            # the fhrp_detail state changed
    assert s["newly_lost_flows"] == []                      # L2-only: the VIP does not move, routes intact
    # the input snapshot's fhrp state is untouched (deep copy) — core1 is still Active in the ORIGINAL
    assert snap["fhrp_detail"]["core1"][0]["state"] == "Active"


def test_move_fhrp_active_single_member_is_noop():
    snap = _l2_snap()
    del snap["fhrp_detail"]["dist1"]                        # only one member left -> nowhere to move
    res = cutover_sim.simulate_cutover(
        snap, [{"action": "move_fhrp_active", "ifname": "Vlan10", "group": "10", "to_host": "dist1"}])
    assert res["steps"][0]["is_noop"] is True


def test_empty_wave_is_total():
    res = cutover_sim.simulate_cutover(_l3_snap(), [], pairs=_PAIRS)
    assert res["steps"] == []
    assert res["worst_step"] is None
    assert res["summary"]["n_steps"] == 0


def test_fail_site_removes_by_substring_across_l2_and_l3():
    snap = {
        "routes": {"SW-NYC-1": [{"prefix": "10.0.1.0/24", "source": "connected"}],
                   "SW-LAX-1": [{"prefix": "10.0.2.0/24", "source": "connected"}]},
        "stp_roots": {"SW-NYC-1": {"5": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                                         "is_root": True, "bridge_priority": 4096}},
                      "SW-LAX-1": {"5": {"root_priority": 4096, "root_address": "bbbb.0000.0002",
                                         "is_root": False, "bridge_priority": 8192}}},
    }
    res = cutover_sim.simulate_cutover(snap, [{"action": "fail_site", "id": "NYC"}], pairs=[])
    s = res["steps"][0]
    assert s["removed_hosts"] == ["SW-NYC-1"]
    assert any(r["vlan"] == "5" and r["new_root"] == "SW-LAX-1" for r in s["stp_reroots"])
