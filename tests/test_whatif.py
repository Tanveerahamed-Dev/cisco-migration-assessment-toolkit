"""Tests for single-snapshot failure-injection what-if (roadmap G4 / Selector 'what-if', recast offline).

reachability_diff/_delta need TWO real snapshots; this synthesizes the second by deep-mutating ONE — remove
a node / site in memory, re-run the FIB. Coverage-honest: removing a transit node makes the flows that
traversed it resolve to lower_bound:next_hop_not_collected -> 'inconclusive', so we report them as PATH
LOST (was reached, now unprovable), NEVER as a fabricated definitive block.
"""
from cisco_toolkit import whatif


SNAP = {"routes": {
    "A": [{"prefix": "10.0.1.0/24", "source": "connected", "out_intf": "Vlan1"},
          {"prefix": "10.0.9.0/24", "source": "static", "next_hop": "10.0.12.2"}],
    "X": [{"prefix": "10.0.12.0/24", "source": "connected", "out_intf": "Gi0/0"},
          {"prefix": "10.0.9.0/24", "source": "connected", "out_intf": "Gi0/1"}],
    "C": [{"prefix": "10.0.5.0/24", "source": "connected", "out_intf": "Vlan5"},
          {"prefix": "10.0.6.0/24", "source": "connected", "out_intf": "Vlan6"}],
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
    snap = {"routes": {
        "R": [{"prefix": "10.0.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
              {"prefix": "10.0.8.0/24", "source": "static", "out_intf": "Null0"}],   # 10.0.8.0/24 -> Null0 (both-unreachable)
        "N": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.0.9.0/24", "source": "connected"}]}}
    r = whatif.run_scenario(snap, {"failures": [{"type": "node", "id": "N"}]}, pairs=[("10.0.1.1", "10.0.8.5")])
    s = r["summary"]
    assert s["blocked"] + s["lost_path"] + s["preserved"] + s["inconclusive_other"] + s["other"] == s["pairs_tested"]
