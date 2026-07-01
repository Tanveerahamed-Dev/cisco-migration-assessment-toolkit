"""Tests for the offline ACL line-reachability / shadow proof (roadmap G1).

Pins the Batfish-`filterLineReachability` contract, recast offline over our already-parsed ACL rules:
a line is BLOCKING_LINES (dead) only when its header-space is PROVABLY covered by the union of earlier
lines; INDEPENDENTLY_UNMATCHABLE when its own match-space is empty; UNDEFINED_/CYCLICAL_REFERENCE for
bad object-groups; and — the coverage-honest core — INDETERMINATE whenever an unevaluable earlier line
might overlap (never a false 'dead'/'reachable'). `Different_Action` flags the dangerous case: a PERMIT
silently shadowed by an earlier DENY (or vice-versa).
"""
from cisco_toolkit import aclcheck

ANY = {"ip": "0.0.0.0", "wild": "255.255.255.255"}


def net(ip, wild):
    return {"ip": ip, "wild": wild}


def host(ip):
    return {"ip": ip, "wild": "0.0.0.0"}


def port(op, val, val2=None):
    p = {"op": op, "val": val}
    if val2 is not None:
        p["val2"] = val2
    return p


def rule(action, proto="ip", src=None, dst=None, sport=None, dport=None, **extra):
    r = {"action": action, "proto": proto, "src": src or ANY, "dst": dst or ANY,
         "sport": sport, "dport": dport, "raw": f"{action} {proto}"}
    r.update(extra)
    return r


def by_idx(findings):
    return {f["line_index"]: f for f in findings}


# 1. a permit silently shadowed by an earlier broader deny -> dead + Different_Action -----------------
def test_permit_shadowed_by_earlier_deny():
    rules = [
        rule("deny", "ip", ANY, net("10.1.1.0", "0.0.0.255")),
        rule("permit", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
    ]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert 0 not in f                               # the deny is reachable -> no finding
    assert f[1]["reason"] == "BLOCKING_LINES"
    assert f[1]["blocking_lines"] == [0]
    assert f[1]["different_action"] is True         # permit hidden behind a deny = a silently-blocked service


# 2. a redundant duplicate (same action) -> dead, but NOT a different-action alarm --------------------
def test_redundant_duplicate_same_action():
    rules = [
        rule("permit", "tcp", ANY, ANY, dport=port("eq", 80)),
        rule("permit", "tcp", ANY, ANY, dport=port("eq", 80)),
    ]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[1]["reason"] == "BLOCKING_LINES"
    assert f[1]["different_action"] is False


# 3. genuinely-reachable lines (disjoint dst) -> no findings -----------------------------------------
def test_disjoint_lines_all_reachable():
    rules = [
        rule("permit", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
        rule("permit", "tcp", ANY, net("10.1.2.0", "0.0.0.255"), dport=port("eq", 22)),
    ]
    assert aclcheck.analyze_acl(rules) == []


# 3b. union coverage: two earlier lines together cover a third ---------------------------------------
def test_union_of_two_earlier_lines_covers_third():
    rules = [
        rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.0.255"), dport=port("eq", 22)),  # 10.1.0.0/24
        rule("permit", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),  # 10.1.1.0/24
        rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.1.255"), dport=port("eq", 22)),  # 10.1.0.0/23 = union of the two
    ]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[2]["reason"] == "BLOCKING_LINES"
    assert sorted(f[2]["blocking_lines"]) == [0, 1]


# 4. an independently-unmatchable line (empty port range) -------------------------------------------
def test_independently_unmatchable_empty_range():
    rules = [rule("permit", "tcp", ANY, ANY, dport=port("range", 100, 50))]   # lo > hi -> empty
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[0]["reason"] == "INDEPENDENTLY_UNMATCHABLE"


# 5. an unevaluable earlier line that might overlap -> INDETERMINATE, never a false 'dead' -----------
def test_unevaluable_earlier_forces_indeterminate():
    rules = [
        rule("permit", "ip", ANY, ANY, unevaluable=True),
        rule("permit", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
    ]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[0]["reason"] == "INDETERMINATE"        # the line is itself unevaluable
    assert f[1]["reason"] == "INDETERMINATE"        # cannot prove it dead behind an unknown line


# 6. an undefined object-group reference ------------------------------------------------------------
def test_undefined_group_reference():
    rules = [rule("permit", "ip", {"group": "NOPE"}, ANY)]
    f = by_idx(aclcheck.analyze_acl(rules, object_groups={}))
    assert f[0]["reason"] == "UNDEFINED_REFERENCE"


# 7. a cyclic object-group reference ----------------------------------------------------------------
def test_cyclic_group_reference():
    ogs = {"A": {"kind": "network", "members": [{"group": "B"}]},
           "B": {"kind": "network", "members": [{"group": "A"}]}}
    rules = [rule("permit", "ip", {"group": "A"}, ANY)]
    f = by_idx(aclcheck.analyze_acl(rules, object_groups=ogs))
    assert f[0]["reason"] == "CYCLICAL_REFERENCE"


# 8. search_filters: a concrete witness packet, or a proof none exists -------------------------------
def test_search_filters_witness_or_proof():
    rules = [
        rule("deny", "tcp", ANY, host("10.0.0.1"), dport=port("eq", 22)),
        rule("permit", "ip", ANY, ANY),
    ]
    # ssh to 10.0.0.1 is denied first -> nothing permitted matches that exact flow
    proven = aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.1", "dport": 22}, action="permit")
    assert proven["result"] == "PROVEN_NONE"
    # ssh on a different port IS permitted -> a witness exists
    witness = aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.1", "dport": 23}, action="permit")
    assert witness["result"] == "WITNESS"
    assert witness["flow"]["dport"] == 23


# 9. the snapshot wrapper threads host/acl/source_command -------------------------------------------
def test_compute_over_snapshot():
    snap = {"acls": {"sw1": {"BLOCK": [
        rule("deny", "ip", ANY, net("10.1.1.0", "0.0.0.255")),
        rule("permit", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
    ]}}}
    out = aclcheck.compute_filter_line_reachability(snap)
    rows = out["findings"]
    assert len(rows) == 1
    assert rows[0]["host"] == "sw1" and rows[0]["acl"] == "BLOCK"
    assert rows[0]["reason"] == "BLOCKING_LINES" and rows[0]["different_action"] is True
    assert rows[0]["source_command"] == "show running-config"
    assert out["summary"]["n_shadowed"] == 1 and out["summary"]["n_different_action"] == 1


# --- review-wave-1 regression tests (defects found by the adversarial review) ----------------------

def test_ipv6_rule_abstains_never_crashes():
    rules = [rule("permit", "tcp", ANY, host("10.0.0.1"), dport=port("eq", 22)),
             rule("permit", "ip", ANY, {"rangeStart": "2001:db8::1", "rangeEnd": "2001:db8::5"})]
    f = by_idx(aclcheck.analyze_acl(rules))                 # must not raise (was: cross-version TypeError)
    assert f[1]["reason"] == "INDETERMINATE"
    out = aclcheck.compute_filter_line_reachability({"acls": {"sw1": {"A": rules}}})   # whole-snapshot pass must survive
    assert any(r["reason"] == "INDETERMINATE" for r in out["findings"])


def test_ipv6_ip_wild_abstains_not_mangled():
    prefixes, status = aclcheck._addr_prefixes({"ip": "2001:db8::1", "wild": "::ff"}, {}, None)
    assert prefixes is None and status == "unevaluable"     # was: silently mangled to an IPv4 /24


def test_search_filters_witness_proto_is_admitted():
    rules = [rule("permit", "tcp", ANY, ANY, dport=port("eq", 22))]
    w = aclcheck.search_filters(rules, {}, action="permit")
    assert w["result"] == "WITNESS" and w["flow"]["proto"] == "tcp"   # was: 'ip' (a flow the line doesn't permit)


def test_search_filters_returns_proven_witness_before_abstaining():
    rules = [rule("permit", "ip", ANY, host("10.0.0.1")),
             rule("permit", "ip", ANY, net("10.0.0.0", "0.0.255.0"))]   # line 1 non-contiguous wild -> unevaluable
    w = aclcheck.search_filters(rules, {}, action="permit")
    assert w["result"] == "WITNESS" and w["flow"]["dst"] == "10.0.0.1"  # was: INDETERMINATE (discarded the proof)


def test_blocking_detail_names_the_different_action_line():
    rules = [rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.0.255"), dport=port("eq", 22)),
             rule("deny", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
             rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.1.255"), dport=port("eq", 22))]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[2]["different_action"] is True
    assert "deny" in f[2]["detail"]                          # was: named the benign earlier permit
