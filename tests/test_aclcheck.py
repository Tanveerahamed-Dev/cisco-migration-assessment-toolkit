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


# --- review-wave 2026-07-28 regressions (#29 #30 #31 #82) -------------------------------------------
# These drive the REAL producer (parse.parse_acls / parse.parse_object_groups) rather than hand-built rule
# dicts: three of the four defects below were INVISIBLE to a hand-built fixture, because the fixture
# omitted exactly the field the parser emits (`'proto': '6'`, `unevaluable: True`) — the analyzer agreed
# with itself. Anything asserting a shadow/witness claim over parsed ACLs belongs in this section.

def _parsed(cfg, name):
    from cisco_toolkit import parse
    return parse.parse_acls(cfg)[name]


def test_numeric_protocol_ace_shadows_its_keyword_sibling():
    """[#29] Cisco accepts the IANA protocol NUMBER as well as the keyword, and the parser stores it
    verbatim ('proto': '6'). Compared as raw strings, `deny 6` and `permit tcp` modelled as DISJOINT: the
    permit was not reported shadowed at all (an empty 'ACL Shadow Analysis' sheet) and search_filters
    handed back a WITNESS asserting ssh to 10.0.0.1 is permitted when line 0 denies every TCP packet to it."""
    rules = _parsed("ip access-list extended NUMPROTO\n"
                    " deny   6 any host 10.0.0.1\n"
                    " permit tcp any host 10.0.0.1 eq 22\n", "NUMPROTO")
    assert rules[0]["proto"] == "6" and rules[1]["proto"] == "tcp"      # the REAL producer's shape
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[1]["reason"] == "BLOCKING_LINES" and f[1]["blocking_lines"] == [0]
    assert f[1]["different_action"] is True
    proven = aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.1", "dport": 22}, action="permit")
    assert proven["result"] == "PROVEN_NONE"                            # was: a witness for a denied packet
    # the numeric form is also matched from the QUERY side
    assert aclcheck.search_filters(rules, {"proto": "6", "dst": "10.0.0.1", "dport": 22},
                                   action="permit")["result"] == "PROVEN_NONE"
    # and unrelated protocols stay disjoint (no over-canonicalising)
    assert aclcheck._proto_inter(aclcheck._proto_of("47"), aclcheck._proto_of("tcp")) == ("only", frozenset())


_OG_CFG = """
object-group network WEB_SERVERS
 host 10.1.1.10
 10.1.2.0 255.255.255.0
!
ip access-list extended OG
 permit tcp any object-group WEB_SERVERS eq 443
 permit tcp any object-group WEB_SERVERS eq 443
 permit ip any any
"""


def test_object_group_ace_is_resolved_not_blanket_indeterminate():
    """[#30] parse.py sets `unevaluable: True` on EVERY object-group address spec — including ones this
    module resolves perfectly — and _rule_box honored the flag unconditionally. So _group_prefixes /
    _addr_prefixes were DEAD CODE on real snapshots: every object-group ACE landed in n_indeterminate and
    the surfaced reason blamed a 'non-contiguous wildcard'. Here the exact duplicate must be proven dead."""
    from cisco_toolkit import parse
    ogs = parse.parse_object_groups(_OG_CFG)
    rules = parse.parse_acls(_OG_CFG)["OG"]
    assert rules[0].get("unevaluable") is True and rules[0]["dst"] == {"group": "WEB_SERVERS"}
    out = aclcheck.compute_filter_line_reachability({"acls": {"sw1": {"OG": rules}},
                                                     "object_groups": {"sw1": ogs}})
    assert out["summary"]["n_indeterminate"] == 0                       # was: 3 of 3 lines
    assert out["summary"]["n_shadowed"] == 1
    assert out["findings"][0]["line_index"] == 1 and out["findings"][0]["reason"] == "BLOCKING_LINES"


def test_unreadable_address_token_still_abstains():
    """[#30, the other side] The parser substitutes `any` for an address token it cannot read and the
    `unevaluable` flag is then the ONLY signal — dropping the flag outright would silently widen that
    line's box to the whole address space and let it declare later lines dead. Group-free rules keep it."""
    rules = _parsed("ip access-list extended BAD\n"
                    " permit tcp @@@ host 10.0.0.1 eq 22\n"
                    " permit tcp any host 10.0.0.1 eq 22\n", "BAD")
    assert rules[0].get("unevaluable") is True and rules[0]["src"] == {"ip": "0.0.0.0", "wild": "255.255.255.255"}
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[0]["reason"] == "INDETERMINATE"
    assert "could not read" in f[0]["detail"] or "unevaluable" in f[0]["detail"]   # names the real cause
    assert f[1]["reason"] == "INDETERMINATE"          # cannot prove it dead behind an unknown line


def test_object_group_reference_missing_from_the_snapshot_is_a_bad_reference():
    """Companion to the two above (it holds on both sides of the #30 fix, since a bad reference is decided
    before the unevaluable flag is consulted): the group-resolution path is reachable from REAL parser
    output, so an undefined group is named as UNDEFINED_REFERENCE rather than tallied as 'indeterminate'."""
    rules = _parsed("ip access-list extended OG2\n permit tcp any object-group NOPE eq 443\n", "OG2")
    f = by_idx(aclcheck.analyze_acl(rules, object_groups={}))
    assert f[0]["reason"] == "UNDEFINED_REFERENCE"


def test_search_filters_models_the_implicit_deny_ip_any_any():
    """[#31] Every Cisco ACL ends in an implicit `deny ip any any`. Without it, an ACL with no explicit
    deny was 'proven' (PROVEN_NONE) to deny nothing — a formal proof of 'no' for a filter that in reality
    blocks everything but its permits."""
    rules = _parsed("ip access-list extended PERMITONLY\n permit tcp any host 10.0.0.1 eq 22\n", "PERMITONLY")
    denied = aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.9", "dport": 80}, action="deny")
    assert denied["result"] == "WITNESS"
    assert denied["matched_by"] == "implicit deny ip any any"
    assert denied["flow"]["dst"] == "10.0.0.9" and denied["flow"]["dport"] == 80
    # the explicitly permitted flow is NOT denied, and the permit witness still comes from the real line
    assert aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.1", "dport": 22},
                                   action="deny")["result"] == "PROVEN_NONE"
    w = aclcheck.search_filters(rules, {"proto": "tcp", "dst": "10.0.0.1", "dport": 22}, action="permit")
    assert w["result"] == "WITNESS" and w["matched_by"] == "explicit line"


def test_search_filters_abstains_on_an_ipv6_query_instead_of_crashing_or_answering_in_v4():
    """[#82] The IPv4-family guard exists on the RULE side (_addr_prefixes) and was missing on the header
    side: a v6 CIDR raised TypeError out of _pref_inter, and — worse — a BARE v6 address fell through the
    `str(v) + '/32'` branch into 0.0.0.0/0, answering the v6 question over the whole IPv4 space."""
    rules = _parsed("ip access-list extended V4ONLY\n permit tcp any host 10.0.0.1 eq 22\n", "V4ONLY")
    for headers in ({"src": "2001:db8::/64"}, {"src": "2001:db8::1"}, {"dst": "fd00::9"}):
        out = aclcheck.search_filters(rules, headers, action="permit")   # must not raise
        assert out["result"] == "INDETERMINATE", (headers, out)
        assert "IPv6" in out["detail"]
    # v4 queries are unaffected
    assert aclcheck.search_filters(rules, {"dst": "10.0.0.1", "dport": 22},
                                   action="permit")["result"] == "WITNESS"


def test_blocking_detail_names_the_different_action_line():
    rules = [rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.0.255"), dport=port("eq", 22)),
             rule("deny", "tcp", ANY, net("10.1.1.0", "0.0.0.255"), dport=port("eq", 22)),
             rule("permit", "tcp", ANY, net("10.1.0.0", "0.0.1.255"), dport=port("eq", 22))]
    f = by_idx(aclcheck.analyze_acl(rules))
    assert f[2]["different_action"] is True
    assert "deny" in f[2]["detail"]                          # was: named the benign earlier permit
