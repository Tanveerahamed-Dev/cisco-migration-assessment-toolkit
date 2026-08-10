"""Tests for single-snapshot failure-injection what-if (roadmap G4 / Selector 'what-if', recast offline).

reachability_diff/_delta need TWO real snapshots; this synthesizes the second by deep-mutating ONE — remove
a node / site in memory, re-run the FIB. Coverage-honest: removing a transit node makes the flows that
traversed it resolve to lower_bound:next_hop_not_collected -> 'inconclusive', so we report them as PATH
LOST (was reached, now unprovable), NEVER as a fabricated definitive block.
"""
from cisco_toolkit import whatif


SNAP = {"routes": {
    "A": [{"prefix": "10.0.1.0/24", "source": "connected", "out_intf": "Vlan1"},
          {"prefix": "10.0.12.0/24", "source": "connected", "out_intf": "Gi0/1"},
          {"prefix": "10.0.9.0/24", "source": "static", "next_hop": "10.0.12.2"}],
    "X": [{"prefix": "10.0.12.0/24", "source": "connected", "out_intf": "Gi0/0"},
          {"prefix": "10.0.9.0/24", "source": "connected", "out_intf": "Gi0/1"}],
    "C": [{"prefix": "10.0.5.0/24", "source": "connected", "out_intf": "Vlan5"},
          {"prefix": "10.0.6.0/24", "source": "connected", "out_intf": "Vlan6"}],
}, "interfaces": {
    "A": {"Gi0/1": {"svi_ip": "10.0.12.1/24"}},
    "X": {"Gi0/1": {"svi_ip": "10.0.12.2/24"}},
}}
PAIRS = [("10.0.1.1", "10.0.9.5"), ("10.0.5.1", "10.0.6.5")]


def test_node_failure_loses_path_for_via_node_flow():
    r = whatif.run_scenario(SNAP, {"failures": [{"type": "node", "id": "X"}]}, pairs=PAIRS)
    assert r["removed_hosts"] == ["X"]
    lost = {(p["src"], p["dst"]) for p in r["lost_flows"]}
    assert ("10.0.1.1", "10.0.9.5") in lost          # the via-X flow: reached -> inconclusive = PATH LOST
    assert r["summary"]["preserved"] == 1            # the independent flow survives
    assert r["summary"]["blocked"] == 0              # we never FABRICATE a definitive block from a removal
    assert r["summary"]["lost_path"] == 1


def test_original_snapshot_is_not_mutated():
    before = len(SNAP["routes"])
    whatif.run_scenario(SNAP, {"failures": [{"type": "node", "id": "X"}]}, pairs=PAIRS)
    assert len(SNAP["routes"]) == before and "X" in SNAP["routes"]   # read-only: the input is untouched


def test_unmatched_scenario_is_noop_and_flagged():
    r = whatif.run_scenario(SNAP, {"failures": [{"type": "node", "id": "NOPE"}]}, pairs=PAIRS)
    assert r["removed_hosts"] == []
    assert r["summary"]["preserved"] == 2
    assert "no device matched" in r["note"].lower()


def test_site_failure_removes_by_substring():
    snap = {"routes": {"SW-CA11-1": [{"prefix": "10.0.1.0/24", "source": "connected"}],
                       "SW-CA22-1": [{"prefix": "10.0.2.0/24", "source": "connected"}]}}
    mutated, removed = whatif.apply_scenario(snap, {"failures": [{"type": "site", "id": "CA11"}]})
    assert removed == ["SW-CA11-1"]
    assert "SW-CA11-1" not in mutated["routes"] and "SW-CA22-1" in mutated["routes"]


# --- review-wave-2 regression tests --------------------------------------------------------------

def test_malformed_failure_entry_does_not_abort_batch():
    snap = {"routes": {"Core-01": [{"prefix": "10.0.1.0/24", "source": "connected"}],
                       "Core-02": [{"prefix": "10.0.2.0/24", "source": "connected"}]}}
    res = whatif.run_scenarios(snap, [{"name": "g1", "failures": [{"type": "node", "id": "Core-01"}]},
                                      {"name": "bad", "failures": ["Core-02"]},        # a bare string, not a dict
                                      {"name": "g2", "failures": [{"type": "node", "id": "Core-02"}]}])
    assert len(res) == 3 and res[1]["removed_hosts"] == []   # was: AttributeError aborted the whole batch


def test_summary_buckets_reconcile_with_pairs_tested():
    """NON-VACUITY (mutation-proved, 2026-07-28). The sum-equals-pairs_tested assertion alone is a
    STRUCTURAL IDENTITY of an if/elif/else chain over `diff["pairs"]` where `pairs_tested` is
    `len(diff["pairs"])`: every pair increments exactly one bucket, so it holds for any input and
    any (mis)classification. Deleting the `newly_blocked` arm outright — so `blocked_flows`, the
    what-if's headline definitive-regression answer, is permanently `[]` — left the whole of
    test_whatif.py GREEN. Pin the DISTRIBUTION as well as the total, on a fixture where the buckets
    differ, so a pair landing in the wrong one is red."""
    snap = {"routes": {
        "R": [{"prefix": "10.0.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
              {"prefix": "10.0.8.0/24", "source": "static", "out_intf": "Null0"}],   # 10.0.8.0/24 -> Null0 (both-unreachable)
        "N": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.0.9.0/24", "source": "connected"}]}}
    r = whatif.run_scenario(snap, {"failures": [{"type": "node", "id": "N"}]}, pairs=[("10.0.1.1", "10.0.8.5")])
    s = r["summary"]
    assert s["blocked"] + s["lost_path"] + s["preserved"] + s["inconclusive_other"] + s["other"] == s["pairs_tested"]
    assert {k: s[k] for k in ("pairs_tested", "blocked", "lost_path", "preserved",
                              "inconclusive_other", "other")} == {
        "pairs_tested": 1, "blocked": 0, "lost_path": 0, "preserved": 0,
        "inconclusive_other": 0, "other": 1}, s


def test_blocked_flows_carries_every_definitive_regression_fib_reports():
    """The `blocked_flows` bucket, which NOTHING else in this file reaches.

    `blocked_flows` is documented as "the DEFINITIVE regressions (fib `newly_blocked`)" and is the
    what-if's headline blast-radius answer, yet every fixture here yields zero of them — and that is
    not an accident of the fixtures. `apply_scenario` can only DELETE whole hosts from
    `snap["routes"]`, so any flow that used a removed device degrades to a lower bound, which
    `fib.reachability_diff` deliberately classifies `inconclusive` rather than fabricating a drop
    (the doctrine `test_node_failure_loses_path_for_via_node_flow` asserts). A definitive
    `newly_blocked` therefore cannot be produced through the shipped scenario surface at all, which
    is exactly why the bucketing arm sat unpinned: deleting it changed no test.

    So drive the classifier's contract directly — given a diff row fib DOES verdict `newly_blocked`,
    run_scenario must route it to `blocked_flows` and count it under `summary["blocked"]`, and must
    NOT silently absorb it into `other`. Stubbing `reachability_diff` is deliberate and disclosed:
    it is the only way to reach this arm, and the arm is what a future scenario type (a link or
    route failure, which CAN produce a definitive drop) would immediately depend on."""
    snap = {"routes": {"R": [{"prefix": "10.0.1.0/24", "source": "connected"}],
                       "N": [{"prefix": "10.0.9.0/24", "source": "connected"}]}}
    rows = [{"src": "10.0.1.1", "dst": "10.0.9.5", "verdict": "newly_blocked",
             "old_status": "computed:reached", "new_status": "computed:unreachable"},
            {"src": "10.0.1.2", "dst": "10.0.9.6", "verdict": "preserved",
             "old_status": "computed:reached", "new_status": "computed:reached"}]
    real = whatif.fib.reachability_diff
    whatif.fib.reachability_diff = lambda *a, **k: {"pairs": rows}
    try:
        r = whatif.run_scenario(snap, {"failures": [{"type": "node", "id": "N"}]},
                                pairs=[("10.0.1.1", "10.0.9.5"), ("10.0.1.2", "10.0.9.6")])
    finally:
        whatif.fib.reachability_diff = real
    assert [(f["src"], f["dst"]) for f in r["blocked_flows"]] == [("10.0.1.1", "10.0.9.5")], \
        "a definitive newly_blocked regression did not reach blocked_flows"
    assert r["summary"]["blocked"] == 1 and r["summary"]["preserved"] == 1
    assert r["summary"]["other"] == 0, "a definitive regression was absorbed into the catch-all"
    assert r["blocked_flows"][0]["new_status"] == "computed:unreachable"
