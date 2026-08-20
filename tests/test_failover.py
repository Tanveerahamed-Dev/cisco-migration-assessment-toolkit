"""Tests for the L2 failover twin (MASTER_PLAN §4.1) — STP root re-election + FHRP takeover.

Uses small SYNTHETIC snapshots (never the golden fixture's exact values) so the assertions are stable
against a re-bless. Coverage-honest paths (single-bridge / single-member abstention, VIP stranded) are
first-class assertions, not afterthoughts.
"""
import pytest

from cisco_toolkit import failover


# ------------------------------------------------------------------ STP re-election ---

def _stp_snap():
    """core1 is the VLAN-10 root (priority 4096); dist1 (16384) and dist2 (8192) are alternates with DISTINCT
    own bridge priorities, so dist2 wins the re-election on priority (a provable winner — the realistic case,
    where every collected bridge advertises the SAME root_address for the incumbent). VLAN-20 root is core1
    (priority 4096) with a single sole alternate dist1 at the DEFAULT priority 32768.

    Note the root_address on the alternates is the incumbent core1's advertised MAC (identical across them),
    matching real 'show spanning-tree' output — the per-bridge OWN MAC is NOT in this data, which is why a
    genuine bridge-priority tie is unbreakable and must abstain (see test_stp_priority_tie_abstains)."""
    return {"stp_roots": {
        "core1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                         "is_mst": False, "bridge_priority": 4096},
                  "20": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                         "is_mst": False, "bridge_priority": 4096}},
        "dist1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                         "is_mst": False, "bridge_priority": 16384},
                  "20": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                         "is_mst": False, "bridge_priority": 32768}},
        "dist2": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                         "is_mst": False, "bridge_priority": 8192, }},
    }}


def test_stp_reelection_picks_lowest_priority_new_root():
    snap = _stp_snap()
    rows = failover.compute_stp_failover(snap, ["core1"])
    v10 = next(r for r in rows if r["vlan"] == "10")
    # dist2 (8192) beats dist1 (16384) on its OWN bridge priority — a provable winner, no mac tiebreak needed.
    assert v10["old_root"] == "core1"
    assert v10["new_root"] == "dist2"
    assert v10["new_root_won_by"] == "lower-priority"
    assert v10["new_root_priority"] == 8192
    assert v10["is_default_election"] is False
    assert v10["indeterminate"] is False
    assert v10["ports_expected_to_transition"] == "(topology-scan-bound — lower bound)"


def test_stp_reelection_lower_priority_wins():
    # give dist1 a strictly lower priority than dist2 so it wins on priority
    snap = _stp_snap()
    snap["stp_roots"]["dist1"]["10"]["bridge_priority"] = 4097
    rows = failover.compute_stp_failover(snap, ["core1"])
    v10 = next(r for r in rows if r["vlan"] == "10")
    assert v10["new_root"] == "dist1"
    assert v10["new_root_won_by"] == "lower-priority"


def test_stp_priority_tie_abstains():
    # REALISTIC schema (adversarial-review #5/#7): both alternates share the incumbent's advertised
    # root_address (their OWN bridge MACs are not collected), and sit at an EQUAL own bridge priority.
    # The 802.1D tiebreak needs each bridge's own MAC — absent here — so the engine must ABSTAIN, never
    # fabricate a winner on the (identical) root_address field.
    snap = {"stp_roots": {
        "core1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                         "bridge_priority": 4096}},
        "a": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                     "bridge_priority": 8192}},
        "b": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                     "bridge_priority": 8192}},
    }}
    rows = failover.compute_stp_failover(snap, ["core1"])
    v10 = next(r for r in rows if r["vlan"] == "10")
    assert v10["indeterminate"] is True
    assert v10["new_root"] is None
    assert "tie" in v10["reason"].lower() and "not collected" in v10["reason"].lower()


def test_stp_offscan_root_is_not_fabricated():
    # adversarial-review #1: no collected bridge reports itself as root (is_root all False) — the real root
    # is off-scan. Failing a collected non-root switch must NOT fabricate a re-election (the real root
    # survives off-scan); _current_root abstains, so no VLAN-10 row is produced for the removal.
    snap = {"stp_roots": {
        "acc1": {"10": {"root_priority": 4096, "root_address": "ffff.0000.0009", "is_root": False,
                        "bridge_priority": 8192}},
        "acc2": {"10": {"root_priority": 4096, "root_address": "ffff.0000.0009", "is_root": False,
                        "bridge_priority": 16384}},
    }}
    rows = failover.compute_stp_failover(snap, ["acc1"])
    assert len(rows) == 1 and rows[0]["indeterminate"] is True
    assert rows[0]["new_root"] is None and "uniquely" in rows[0]["reason"]
    rd = failover.compute_failover_readiness(snap)
    assert rd["n_stp_roots"] == 0                           # no collected bridge is provably a root


def test_multiple_stp_root_claimants_are_explicitly_indeterminate():
    snap = {"stp_roots": {
        "a": {"10": {"is_root": True, "bridge_priority": 4096}},
        "b": {"10": {"is_root": True, "bridge_priority": 8192}},
    }}
    rows = failover.compute_stp_failover(snap, ["a"])
    assert len(rows) == 1 and rows[0]["indeterminate"] is True
    assert "multiple" in rows[0]["reason"].lower()


def test_stp_missing_survivor_priority_abstains():
    # adversarial-review #4/#11: a surviving bridge whose OWN bridge_priority was not collected could hold
    # any value (an uncollected priority could undercut the apparent winner) -> abstain, never launder the
    # missing priority into a fabricated default-election via a sentinel.
    snap = {"stp_roots": {
        "core1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                         "bridge_priority": 4096}},
        "dist1": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False,
                         "bridge_priority": 8192}},
        "dist2": {"10": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": False}},
    }}
    rows = failover.compute_stp_failover(snap, ["core1"])
    v10 = next(r for r in rows if r["vlan"] == "10")
    assert v10["indeterminate"] is True
    assert v10["new_root"] is None
    assert v10["is_default_election"] is False             # never a fabricated default-election
    assert "priority" in v10["reason"].lower()


def test_stp_default_election_flagged():
    snap = _stp_snap()
    rows = failover.compute_stp_failover(snap, ["core1"])
    v20 = next(r for r in rows if r["vlan"] == "20")
    # VLAN 20's only survivor (dist1) sits at the default priority 32768 -> flagged as an unmanaged election
    assert v20["new_root"] == "dist1"
    assert v20["is_default_election"] is True
    assert v20["new_root_won_by"] == "default-election(>=32768)"
    assert v20["indeterminate"] is False


def test_stp_single_bridge_abstains():
    snap = {"stp_roots": {"solo": {"99": {"root_priority": 4096, "root_address": "aaaa.0000.0001",
                                          "is_root": True, "bridge_priority": 4096}}}}
    rows = failover.compute_stp_failover(snap, ["solo"])
    assert len(rows) == 1
    r = rows[0]
    assert r["indeterminate"] is True
    assert r["new_root"] is None
    assert "INDETERMINATE" in r["reason"]


def test_stp_surviving_root_is_not_reported():
    # failing a NON-root bridge must not produce a re-election row for that VLAN
    snap = _stp_snap()
    rows = failover.compute_stp_failover(snap, ["dist2"])
    assert not any(r["vlan"] == "10" and not r["indeterminate"] for r in rows) or \
        all(r["old_root"] != "dist2" for r in rows)
    # concretely: dist2 is not the root of any VLAN, so nothing re-roots
    assert rows == []


def test_stp_all_survivors_failed_abstains():
    snap = _stp_snap()
    rows = failover.compute_stp_failover(snap, ["core1", "dist1", "dist2"])
    v10 = next(r for r in rows if r["vlan"] == "10")
    assert v10["indeterminate"] is True
    assert "failed set" in v10["reason"]


# ------------------------------------------------------------------ FHRP takeover ---

def _fhrp_snap():
    """Vlan10 group 10: core1 Active/prio 110/preempt, core2 Standby/prio 100/preempt.
    Vlan20 group 20: core1 Active/prio 110 preempt OFF, core2 Standby/prio 100.
    Vlan30 group 30: core1 Active/prio 110 — SINGLE member collected (single-homed, not provable)."""
    return {"fhrp_detail": {
        "core1": [
            {"ifname": "Vlan10", "group": "10", "state": "Active", "priority": 110, "preempt": True,
             "vip": "10.0.10.1", "version": 2},
            {"ifname": "Vlan20", "group": "20", "state": "Active", "priority": 110, "preempt": False,
             "vip": "10.0.20.1", "version": 2},
            {"ifname": "Vlan30", "group": "30", "state": "Active", "priority": 110, "preempt": True,
             "vip": "10.0.30.1", "version": 2},
        ],
        "core2": [
            {"ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 100, "preempt": True,
             "vip": "10.0.10.1", "version": 2},
            {"ifname": "Vlan20", "group": "20", "state": "Standby", "priority": 100, "preempt": True,
             "vip": "10.0.20.1", "version": 2},
        ],
    }}


def test_fhrp_takeover_picks_highest_surviving_priority():
    snap = _fhrp_snap()
    rows = failover.compute_fhrp_failover(snap, ["core1"])
    g10 = next(r for r in rows if r["group"] == "10")
    assert g10["old_active"] == "core1"
    assert g10["new_active"] == "core2"
    assert g10["new_active_priority"] == 100
    assert g10["split_brain_risk"] is False
    assert g10["indeterminate"] is False


def test_fhrp_split_brain_when_takeover_member_preempt_off():
    # Vlan20: the survivor core2 HAS preempt on by default, so failing core1 there is NOT split-brain.
    # Build the smell: make the takeover member itself preempt-off.
    snap2 = _fhrp_snap()
    snap2["fhrp_detail"]["core2"][1]["preempt"] = False     # core2's Vlan20 member: no reclaim
    rows2 = failover.compute_fhrp_failover(snap2, ["core1"])
    g20 = next(r for r in rows2 if r["group"] == "20")
    assert g20["new_active"] == "core2"
    assert g20["split_brain_risk"] is True
    assert "does not reclaim" in g20["reason"]


def test_fhrp_single_member_abstains():
    snap = _fhrp_snap()
    rows = failover.compute_fhrp_failover(snap, ["core1"])
    g30 = next(r for r in rows if r["group"] == "30")
    assert g30["indeterminate"] is True
    assert g30["new_active"] is None
    assert "single member" in g30["reason"].lower()


def test_json_infinity_priority_degrades_instead_of_crashing():
    """`json.loads` accepts the bare JSON `Infinity` as `float('inf')`, and `int(float('inf'))`
    raises OverflowError — which `_int_or`'s `(TypeError, ValueError)` pair did NOT catch, so one
    poisoned bridge_priority / FHRP priority crashed the whole L2 failover twin (reachable from the
    read-only MCP failover tools and every cutover_sim dry-run step). Every sibling coercer in this
    repo lists OverflowError; this one did not. The field must degrade — and on the STP side the
    degraded value is None, which the caller reads as 'not collected' and ABSTAINS on rather than
    fabricating a winner."""
    import json

    assert failover._int_or(float("inf"), None) is None
    assert failover._int_or(float("-inf"), -1) == -1
    assert failover._int_or(float("nan"), None) is None          # NaN still rejected (ValueError)
    assert failover._int_or(8192, None) == 8192                  # a good value still coerces

    stp = _stp_snap()
    stp["stp_roots"]["dist2"]["10"]["bridge_priority"] = json.loads("Infinity")
    rows = failover.compute_stp_failover(stp, ["core1"])         # must not raise
    v10 = next(r for r in rows if r["vlan"] == "10")
    assert v10["indeterminate"] is True and v10["new_root"] is None
    assert "without a collected bridge priority" in v10["reason"] and "dist2" in v10["reason"]

    fh = _fhrp_snap()
    fh["fhrp_detail"]["core2"][0]["priority"] = json.loads("Infinity")
    g10 = next(r for r in failover.compute_fhrp_failover(fh, ["core1"]) if r["group"] == "10")
    assert g10["indeterminate"] is True
    assert g10["new_active"] is None and g10["new_active_priority"] is None

    # and the orchestrator (the surface both MCP tools and cutover_sim call) survives end to end
    both = {"stp_roots": stp["stp_roots"], "fhrp_detail": fh["fhrp_detail"]}
    out = failover.compute_failover_twin(both, [{"type": "node", "id": "core1"}])
    assert out["schema"] == "failover_twin/1" and out["summary"]["n_indeterminate"] >= 1


def test_fhrp_vip_stranded_when_no_survivor():
    # fail BOTH members of group 10 -> the VIP is stranded, flagged (not a clean takeover, not indeterminate)
    snap = _fhrp_snap()
    rows = failover.compute_fhrp_failover(snap, ["core1", "core2"])
    g10 = next(r for r in rows if r["group"] == "10")
    assert g10["new_active"] is None
    assert g10["split_brain_risk"] is True
    assert g10["indeterminate"] is False
    assert "STRANDED" in g10["reason"]


def test_fhrp_surviving_active_is_not_reported():
    # failing the STANDBY (core2) must not produce a takeover row (the Active core1 survives)
    snap = _fhrp_snap()
    rows = failover.compute_fhrp_failover(snap, ["core2"])
    assert rows == []


def test_fhrp_offscan_active_is_not_fabricated():
    # adversarial-review #2: the real Active/Master (core1, prio 110) is OFF-SCAN; only Standby members were
    # collected. Failing a collected Standby must NOT promote another Standby to a fabricated 'current active'
    # and claim a takeover — the VIP is still served by the off-scan Active, unaffected by this failure.
    snap = {"fhrp_detail": {
        "core2": [{"ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 100, "preempt": True,
                   "vip": "10.0.10.1", "version": 2}],
        "core3": [{"ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 90, "preempt": True,
                   "vip": "10.0.10.1", "version": 2}],
    }}
    rows = failover.compute_fhrp_failover(snap, ["core2"])
    assert len(rows) == 1 and rows[0]["indeterminate"] is True
    assert rows[0]["new_active"] is None and "uniquely" in rows[0]["reason"]
    rd = failover.compute_failover_readiness(snap)
    assert rd["n_fhrp_actives"] == 0                        # no collected member is provably the forwarder


def test_multiple_fhrp_actives_are_explicit_split_brain_and_indeterminate():
    snap = {"fhrp_detail": {
        "a": [{"ifname": "Vlan10", "group": "10", "state": "Active", "priority": 110,
               "preempt": True, "vip": "10.0.10.1", "version": 2}],
        "b": [{"ifname": "Vlan10", "group": "10", "state": "Active", "priority": 100,
               "preempt": True, "vip": "10.0.10.1", "version": 2}],
    }}
    rows = failover.compute_fhrp_failover(snap, ["a"])
    assert len(rows) == 1 and rows[0]["indeterminate"] is True
    assert rows[0]["split_brain_risk"] is True
    assert "multiple" in rows[0]["reason"].lower()


@pytest.mark.parametrize("bad_priority", [True, False, 100.9, -1, "100.5", "not-a-priority"])
def test_malformed_election_priorities_abstain(bad_priority):
    stp = _stp_snap()
    stp["stp_roots"]["dist1"]["10"]["bridge_priority"] = bad_priority
    stp_row = next(r for r in failover.compute_stp_failover(stp, ["core1"]) if r["vlan"] == "10")
    assert stp_row["indeterminate"] is True and stp_row["new_root"] is None

    fhrp = _fhrp_snap()
    fhrp["fhrp_detail"]["core2"][0]["priority"] = bad_priority
    fhrp_row = next(r for r in failover.compute_fhrp_failover(fhrp, ["core1"]) if r["group"] == "10")
    assert fhrp_row["indeterminate"] is True and fhrp_row["new_active"] is None


def test_equal_priority_fhrp_survivors_require_protocol_tiebreak_evidence():
    snap = _fhrp_snap()
    snap["fhrp_detail"]["core3"] = [{
        "ifname": "Vlan10", "group": "10", "state": "Standby", "priority": 100,
        "preempt": True, "vip": "10.0.10.1", "version": 2,
    }]
    row = next(r for r in failover.compute_fhrp_failover(snap, ["core1"]) if r["group"] == "10")
    assert row["indeterminate"] is True and row["new_active"] is None
    assert "tiebreak" in row["reason"].lower()


@pytest.mark.parametrize("mutation", ["down", "vip", "version", "duplicate"])
def test_fhrp_takeover_requires_eligible_compatible_unique_members(mutation):
    snap = _fhrp_snap()
    survivor = snap["fhrp_detail"]["core2"][0]
    if mutation == "down":
        survivor["state"] = "Down"
    elif mutation == "vip":
        survivor["vip"] = "10.0.10.254"
    elif mutation == "version":
        survivor["version"] = 1
    else:
        snap["fhrp_detail"]["core2"].append(dict(survivor))
    row = next(r for r in failover.compute_fhrp_failover(snap, ["core1"]) if r["group"] == "10")
    assert row["indeterminate"] is True and row["new_active"] is None


# ------------------------------------------------------------------ orchestrator ---

def test_orchestrator_summary_reconciles():
    snap = {**_stp_snap(), **_fhrp_snap()}
    tw = failover.compute_failover_twin(snap, [{"type": "node", "id": "core1"}])
    assert tw["schema"] == "failover_twin/1"
    assert tw["failed_hosts"] == ["core1"]
    s = tw["summary"]
    # STP: VLAN10 re-roots (non-default), VLAN20 re-roots but default-election -> 2 rerooted, 1 default.
    assert s["n_vlans_rerooted"] == 2
    assert s["n_default_election_roots"] == 1
    # FHRP: group10 takeover (clean), group20 takeover (clean here, preempt on), group30 indeterminate.
    assert s["n_fhrp_takeovers"] == 2
    assert s["n_split_brain_risks"] == 0
    # indeterminate = FHRP group30 single-member (STP has none here).
    assert s["n_indeterminate"] == 1
    # buckets reconcile with the row lists
    assert s["n_vlans_rerooted"] == sum(1 for r in tw["stp"] if not r["indeterminate"])
    assert s["n_indeterminate"] == (sum(1 for r in tw["stp"] if r["indeterminate"])
                                    + sum(1 for r in tw["fhrp"] if r["indeterminate"]))


def test_orchestrator_accepts_bare_list_and_scenario_dict():
    snap = _fhrp_snap()
    a = failover.compute_failover_twin(snap, [{"type": "node", "id": "core1"}])
    b = failover.compute_failover_twin(snap, {"failures": [{"type": "node", "id": "core1"}]})
    assert a["failed_hosts"] == b["failed_hosts"] == ["core1"]


def test_orchestrator_site_substring_match():
    snap = {"stp_roots": {
        "SW-NYC-1": {"5": {"root_priority": 4096, "root_address": "aaaa.0000.0001", "is_root": True,
                           "bridge_priority": 4096}},
        "SW-NYC-2": {"5": {"root_priority": 4096, "root_address": "aaaa.0000.0002", "is_root": False,
                           "bridge_priority": 8192}},
        "SW-LAX-1": {"5": {"root_priority": 4096, "root_address": "aaaa.0000.0003", "is_root": False,
                           "bridge_priority": 8192}},
    }}
    tw = failover.compute_failover_twin(snap, [{"type": "site", "id": "NYC"}])
    assert tw["failed_hosts"] == ["SW-NYC-1", "SW-NYC-2"]
    v5 = next(r for r in tw["stp"] if r["vlan"] == "5")
    assert v5["new_root"] == "SW-LAX-1"                     # the only survivor


def test_orchestrator_no_match_is_empty_not_error():
    snap = _stp_snap()
    tw = failover.compute_failover_twin(snap, [{"type": "node", "id": "does-not-exist"}])
    assert tw["failed_hosts"] == []
    assert tw["stp"] == [] and tw["fhrp"] == []
    assert tw["summary"]["n_vlans_rerooted"] == 0


def test_snapshot_is_not_mutated():
    import copy
    snap = {**_stp_snap(), **_fhrp_snap()}
    before = copy.deepcopy(snap)
    failover.compute_failover_twin(snap, [{"type": "node", "id": "core1"}])
    failover.compute_failover_readiness(snap)
    assert snap == before                                   # read-only: the input is untouched


# ------------------------------------------------------------------ readiness rollup ---

def test_readiness_counts_backups_and_blind_spots():
    snap = {**_stp_snap(), **_fhrp_snap()}
    rd = failover.compute_failover_readiness(snap)
    assert rd["schema"] == "failover_readiness/1"
    # STP roots observed: core1 is root of VLAN 10 and 20 -> 2 roots.
    assert rd["n_stp_roots"] == 2
    # VLAN10 has a clean backup; VLAN20's only backup is a default election -> 1 backup, 1 default.
    assert rd["n_stp_roots_with_backup"] == 1
    assert rd["n_stp_default_election"] == 1
    # FHRP actives observed: core1 on groups 10, 20, 30 -> 3 actives.
    assert rd["n_fhrp_actives"] == 3
    assert rd["n_fhrp_with_backup"] == 2                    # groups 10 and 20 have a proven survivor
    assert rd["n_fhrp_indeterminate"] == 1                 # group 30 single-member
    # at_risk names the blind spots (VLAN20 default election, group30 single-member)
    kinds = {(r["kind"], r.get("vlan") or r.get("group")) for r in rd["at_risk"]}
    assert ("stp", "20") in kinds
    assert ("fhrp", "30") in kinds


def test_readiness_empty_snapshot_is_zeros():
    rd = failover.compute_failover_readiness({})
    assert rd["n_stp_roots"] == 0 and rd["n_fhrp_actives"] == 0
    assert rd["at_risk"] == []
