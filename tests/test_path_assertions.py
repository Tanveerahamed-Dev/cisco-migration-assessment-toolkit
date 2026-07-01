"""Tests for named, persisted segmentation/path assertions (roadmap G3, Forward/IP-Fabric saved path-checks).

A committed catalog of {id, src, dst, expect: REACHES | ISOLATED | status==<x>} evaluated over the EXISTING
fib.trace_fib_path. The coverage-honest crux (the critic's binding guard): ISOLATED is an EXISTENTIAL
NEGATIVE — a single computed-unreachable proves it, a reach refutes it, but a LOWER-BOUND trace can NEVER
prove isolation -> NOT_OBSERVED (never a false 'isolated holds'). Same for REACHES on a lower bound.
"""
from cisco_toolkit import path_assertions as pa


SNAP = {"routes": {
    "A": [{"prefix": "10.0.1.0/24", "source": "connected"},
          {"prefix": "10.0.2.0/24", "source": "static", "next_hop": "10.0.12.2"}],
    "X": [{"prefix": "10.0.12.0/24", "source": "connected"},
          {"prefix": "10.0.2.0/24", "source": "connected"}],
    "R": [{"prefix": "10.0.3.0/24", "source": "connected"},
          {"prefix": "10.0.4.0/24", "source": "static", "next_hop": "10.0.3.254"}],  # a static route -> R is an L3 router with NO route to 10.0.9.0/24
}}


def _verdict(asrt):
    return pa.evaluate_path_assertions(SNAP, [asrt])["results"][0]["verdict"]


def test_reaches_pass():
    assert _verdict({"id": "r1", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "REACHES"}) == "pass"


def test_reaches_fail_when_definitively_unreachable():
    # R is L3 with no covering route -> computed:unreachable -> REACHES fails (definitive)
    assert _verdict({"id": "r2", "src": "10.0.3.1", "dst": "10.0.9.9", "expect": "REACHES"}) == "fail"


def test_isolated_pass_when_definitively_unreachable():
    assert _verdict({"id": "i1", "src": "10.0.3.1", "dst": "10.0.9.9", "expect": "ISOLATED"}) == "pass"


def test_isolated_fail_when_reachable():
    assert _verdict({"id": "i2", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "ISOLATED"}) == "fail"


def test_lower_bound_is_not_observed_for_both_directions():
    # an un-owned source -> lower_bound:src_host_not_found -> we cannot prove REACH or ISOLATION
    assert _verdict({"id": "lb1", "src": "10.0.99.1", "dst": "10.0.2.5", "expect": "REACHES"}) == "not_observed"
    assert _verdict({"id": "lb2", "src": "10.0.99.1", "dst": "10.0.2.5", "expect": "ISOLATED"}) == "not_observed"


def test_summary_counts_and_citation():
    out = pa.evaluate_path_assertions(SNAP, [
        {"id": "r1", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "REACHES"},
        {"id": "i2", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "ISOLATED"},
    ])
    assert out["summary"]["pass"] == 1 and out["summary"]["fail"] == 1
    assert all(r.get("citation") for r in out["results"])


def test_revalidate_pass_to_not_observed_is_coverage_lost_not_regression():
    # removing X loses the computed path (pass -> not_observed). A collection gap is NOT a regression (that
    # would overclaim 'not observed' as a definite breach); it is surfaced separately as coverage_lost.
    new = {"routes": {k: v for k, v in SNAP["routes"].items() if k != "X"}}
    out = pa.revalidate(SNAP, new, [{"id": "r1", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "REACHES"}])
    row = out["results"][0]
    assert row["old_verdict"] == "pass" and row["new_verdict"] == "not_observed"
    assert row["regressed"] is False and row["coverage_lost"] is True
    assert out["summary"]["regressed"] == 0 and out["summary"]["coverage_lost"] == 1


def test_revalidate_newly_proven_failure_is_a_regression():
    # OLD: src owner is L2-only -> lower bound -> not_observed. NEW: src owner becomes a router with no covering
    # route -> computed:unreachable -> REACHES fail. The not_observed -> fail breach must be caught.
    old = {"routes": {"S": [{"prefix": "10.0.1.0/24", "source": "connected"}]}}
    new = {"routes": {"S": [{"prefix": "10.0.1.0/24", "source": "connected"},
                            {"prefix": "10.0.99.0/24", "source": "static", "next_hop": "10.0.1.254"}]}}
    out = pa.revalidate(old, new, [{"id": "r", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": "REACHES"}])
    row = out["results"][0]
    assert row["old_verdict"] == "not_observed" and row["new_verdict"] == "fail"
    assert row["regressed"] is True


def test_status_eq_abstains_on_lower_bound():
    assert pa._classify({"status": "lower_bound:loop", "computed": False, "reached": False}, "status==lower_bound:loop") == "not_observed"
    assert pa._classify({"status": "computed:reached", "computed": True, "reached": True}, "status==computed:reached") == "pass"


def test_blank_or_typo_expect_abstains():
    for e in (None, "", 0, False, " ", "ISOLAT", "status=="):
        assert _verdict({"id": "x", "src": "10.0.1.1", "dst": "10.0.2.5", "expect": e}) == "not_observed"
