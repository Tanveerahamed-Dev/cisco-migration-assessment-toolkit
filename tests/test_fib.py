"""Native longest-prefix-match RIB->FIB resolver (universal-best roadmap W2-1).

The marquee 'universal & best' seam: upgrade reachability from L2 topology-BFS (a 'lower bound', analyze.py:2186)
to a COMPUTED L3 forwarding resolution over the already-parsed per-host routes (snap['routes'] =
{host: [{prefix, source, next_hop, out_intf}]}). Pure stdlib (ipaddress), fully offline, coverage-honest: a
resolved lookup is 'computed from collected routes'; a dst with no matching route returns None ('no route
observed' -- a lower bound, never a fabricated 'reachable').
"""
from cisco_toolkit import fib


def _routes():
    return [
        {"prefix": "0.0.0.0/0", "next_hop": "10.0.0.1", "out_intf": "Gi0/1", "source": "static"},
        {"prefix": "10.1.0.0/16", "next_hop": "10.0.0.2", "out_intf": "Gi0/2", "source": "ospf"},
        {"prefix": "10.1.2.0/24", "next_hop": "10.0.0.3", "out_intf": "Gi0/3", "source": "connected"},
    ]


def test_longest_prefix_match_wins():
    f = fib.compute_fib(_routes())
    assert fib.fib_lookup(f, "10.1.2.5")["next_hop"] == "10.0.0.3"     # /24 beats /16 beats /0
    assert fib.fib_lookup(f, "10.1.2.5")["match"] == "10.1.2.0/24"
    assert fib.fib_lookup(f, "10.1.5.5")["next_hop"] == "10.0.0.2"     # /16
    assert fib.fib_lookup(f, "8.8.8.8")["next_hop"] == "10.0.0.1"      # default route
    assert fib.fib_lookup(f, "8.8.8.8")["computed"] is True


def test_no_matching_route_is_coverage_honest_none():
    f = fib.compute_fib([{"prefix": "10.1.2.0/24", "next_hop": "10.0.0.3", "source": "connected"}])
    assert fib.fib_lookup(f, "10.1.2.5") is not None                  # in the connected /24
    assert fib.fib_lookup(f, "8.8.8.8") is None                       # NO route + no default -> None, not 'reachable'


def test_tie_on_same_prefix_prefers_lower_admin_distance():
    f = fib.compute_fib([
        {"prefix": "10.1.2.0/24", "next_hop": "10.0.0.9", "source": "bgp"},        # AD 20
        {"prefix": "10.1.2.0/24", "next_hop": "10.0.0.3", "source": "connected"},  # AD 0 -> wins
    ])
    assert fib.fib_lookup(f, "10.1.2.5")["next_hop"] == "10.0.0.3"
    # ospf (110) loses to static (1) on the same prefix
    f2 = fib.compute_fib([
        {"prefix": "172.16.0.0/16", "next_hop": "1.1.1.1", "source": "ospf"},
        {"prefix": "172.16.0.0/16", "next_hop": "2.2.2.2", "source": "static"},
    ])
    assert fib.fib_lookup(f2, "172.16.5.5")["next_hop"] == "2.2.2.2"


def test_total_on_bad_input():
    f = fib.compute_fib([{"prefix": "garbage"}, {"prefix": "10.0.0.0/8", "next_hop": "1.1.1.1", "source": "static"},
                         None, {}, {"prefix": ""}])
    assert fib.fib_lookup(f, "10.5.5.5")["next_hop"] == "1.1.1.1"     # the one valid route still resolves
    assert fib.compute_fib(None) == []                               # total
    assert fib.fib_lookup(fib.compute_fib(None), "1.2.3.4") is None
    assert fib.fib_lookup(f, "not-an-ip") is None                    # bad dst -> None, no raise


def test_ipv6_supported():
    f = fib.compute_fib([{"prefix": "2001:db8::/32", "next_hop": "fe80::1", "source": "connected"}])
    assert fib.fib_lookup(f, "2001:db8::5")["match"] == "2001:db8::/32"
    assert fib.fib_lookup(f, "2001:dead::1") is None


def _two_router_snap():
    """R1 (access 10.1.1.0/24) --transit 10.0.12.0/24-- R2 (access 10.2.2.0/24). R1 default-routes via R2."""
    return {"routes": {
        "R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "out_intf": "Vlan1", "source": "connected"},
               {"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
               {"prefix": "0.0.0.0/0", "next_hop": "10.0.12.2", "out_intf": "Gi0/1", "source": "static"}],
        "R2": [{"prefix": "10.0.12.0/24", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
               {"prefix": "10.2.2.0/24", "next_hop": "", "out_intf": "Vlan2", "source": "connected"}],
    }}


def test_trace_computes_path_across_hosts():
    """R1 --default--> R2 (the OTHER host on the transit link, not R1 itself) --connected--> dst reached. The
    next-hop 10.0.12.2 is in BOTH routers' connected /24, so the resolver must exclude the current host (R1) to
    avoid a self-loop and land on R2."""
    t = fib.trace_fib_path(_two_router_snap(), "10.1.1.5", "10.2.2.9")
    assert [h["host"] for h in t["hops"]] == ["R1", "R2"]
    assert t["status"] == "computed:reached" and t["computed"] is True and t["reached"] is True
    assert t["hops"][0]["match"] == "0.0.0.0/0" and t["hops"][1]["source"] == "connected"


def test_trace_no_route_at_collected_host_is_computed_unreachable():
    """A collected router with no matching route AND no default definitively DROPS (per its RIB) — that's a
    COMPUTED unreachable verdict, not a lower bound. (Distinct from next_hop_not_collected, where the trail is
    genuinely lost to incomplete collection.)"""
    snap = {"routes": {"R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "source": "connected"}]}}
    t = fib.trace_fib_path(snap, "10.1.1.5", "8.8.8.8")      # no default at R1
    assert t["status"] == "computed:unreachable" and t["computed"] is True and t["reached"] is False


def test_trace_fhrp_vip_self_via_local_is_reached():
    """[audit-5 #12] An FHRP virtual IP is installed as a self-referential local host route 'X/32 via X, VlanN,
    [0/0], vrrp_engine|hsrp|glbp' -- locally TERMINATED on the master (the packet is delivered). It must read as
    computed:reached, not an unresolvable next-hop lower bound."""
    snap = {"routes": {"CORE": [
        {"prefix": "10.203.12.0/24", "next_hop": "", "source": "connected"},
        {"prefix": "10.203.12.1/32", "next_hop": "10.203.12.1", "source": "vrrp_engine"}]}}
    t = fib.trace_fib_path(snap, "10.203.12.2", "10.203.12.1")   # src on the /24, dst = the VIP
    assert t["status"] == "computed:reached" and t["reached"] is True


def test_trace_stops_when_next_hop_host_not_collected():
    """R1 routes to a next-hop whose owning router was never collected -> explicit lower bound, not 'reachable'."""
    snap = {"routes": {"R1": [
        {"prefix": "10.1.1.0/24", "next_hop": "", "source": "connected"},
        {"prefix": "0.0.0.0/0", "next_hop": "172.31.99.1", "source": "static"}]}}   # 172.31.99.1 behind nobody collected
    t = fib.trace_fib_path(snap, "10.1.1.5", "8.8.8.8")
    assert t["computed"] is False and t["status"] == "lower_bound:next_hop_not_collected"
    assert [h["host"] for h in t["hops"]] == ["R1"]                                 # got one computed hop, then honest stop


def test_trace_resolves_ipv6_link_local_next_hop_with_zone_id():
    """Cisco prints IPv6 LLA next-hops with an interface zone-id ('fe80::2%Gi0/1'); the '/' in the interface name
    makes ipaddress.ip_address raise on Python 3.9+ -> the next-hop's host was silently lost
    (next_hop_not_collected) on any OSPFv3/IS-IS/BGP-over-link-local fabric (the NORMAL case for v6). The zone-id
    carries no usable info here (no per-zone interface-IP data) and MUST be stripped so the trace reaches
    end-to-end. (user-reported regression; intermittent by interface type — '%Vlan10' parsed, '%Gi0/1' did not.)"""
    snap = {"routes": {
        "R1": [{"prefix": "2001:db8:1::/64", "next_hop": "", "source": "connected"},
               {"prefix": "fe80::/64", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
               {"prefix": "::/0", "next_hop": "fe80::2%Gi0/1", "out_intf": "Gi0/1", "source": "static"}],
        "R2": [{"prefix": "fe80::/64", "next_hop": "", "out_intf": "Gi0/1", "source": "connected"},
               {"prefix": "2001:db8:2::/64", "next_hop": "", "source": "connected"}],
    }}
    t = fib.trace_fib_path(snap, "2001:db8:1::5", "2001:db8:2::9")
    assert [h["host"] for h in t["hops"]] == ["R1", "R2"]
    assert t["status"] == "computed:reached" and t["reached"] is True
    # consistency: a slash-bearing zone ('%Gi0/1') and a slash-free one ('%Vlan10') must resolve identically
    ci = fib._connected_index(snap["routes"])
    assert fib._hosts_owning_ip(ci, "fe80::2%Gi0/1") == fib._hosts_owning_ip(ci, "fe80::2%Vlan10")
    assert fib._hosts_owning_ip(ci, "fe80::2%Gi0/1") == fib._hosts_owning_ip(ci, "fe80::2")
    # a zoned DST is also parseable (fib_lookup must strip too)
    assert fib.fib_lookup(fib.compute_fib(snap["routes"]["R2"]), "fe80::2%Te1/0/1")["match"] == "fe80::/64"


def test_trace_total_on_bad_input():
    assert fib.trace_fib_path(None, "1.1.1.1", "2.2.2.2")["computed"] is False
    assert fib.trace_fib_path({}, "1.1.1.1", "2.2.2.2")["status"] == "lower_bound:src_host_not_found"
    assert fib.trace_fib_path({"routes": "oops"}, "1.1.1.1", "2.2.2.2")["computed"] is False


def test_reachability_diff_detects_newly_blocked_regression():
    """W2-2: the pre-cutover proof. A change that removes R1's default route turns a previously-reachable flow
    into a definitive drop -> 'newly_blocked' (a regression the what-if catches BEFORE the maintenance window)."""
    import copy
    before = _two_router_snap()                                    # R1 --default--> R2 reaches 10.2.2.0/24
    after = copy.deepcopy(before)
    after["routes"]["R1"] = [r for r in after["routes"]["R1"] if r["prefix"] != "0.0.0.0/0"]   # drop R1 default
    pairs = [("10.1.1.5", "10.2.2.9")]
    d = fib.reachability_diff(before, after, pairs)
    assert d["pairs"][0]["verdict"] == "newly_blocked" and d["summary"] == {"newly_blocked": 1}
    assert fib.reachability_diff(before, before, pairs)["summary"] == {"preserved": 1}   # unchanged -> preserved


def test_reachability_diff_is_inconclusive_on_a_lower_bound():
    """If either trace is a lower bound (next hop's host not collected), the verdict is 'inconclusive' — the
    what-if must never assert preserved/broken on evidence it doesn't have."""
    s = {"routes": {"R1": [{"prefix": "10.1.1.0/24", "source": "connected"},
                           {"prefix": "0.0.0.0/0", "next_hop": "172.31.99.1", "source": "static"}]}}
    assert fib.reachability_diff(s, s, [("10.1.1.5", "8.8.8.8")])["pairs"][0]["verdict"] == "inconclusive"


def test_reachability_diff_total_on_bad_pairs():
    assert fib.reachability_diff({}, {}, None)["summary"] == {}
    assert fib.reachability_diff({}, {}, [None, ("only-one",), 5])["summary"] == {}   # malformed pairs skipped


# ---------------------------------------------------------------------------------------------------------------
# Adversarial-wave findings (12 confirmed; fib-adversarial-verify wave). Each asserts the COVERAGE-HONEST behavior:
# a definitive computed:reached / computed:unreachable / diff verdict must never be fabricated from incomplete
# exploration -- when the routes don't support a definitive answer, the result is an explicit lower bound.
# ---------------------------------------------------------------------------------------------------------------

def _ecmp_snap(bad_first):
    """R1 has TWO equal-cost (ospf/AD110) legs to 10.9.9.0/24: one dead-ends at collected R3 (no route), one
    reaches via R2 (dst connected). A real router installs both and load-balances, so the flow CAN take the
    working leg -- exploring only the first leg and asserting a definitive drop is false-health."""
    g = {"prefix": "10.9.9.0/24", "source": "ospf", "next_hop": "10.0.12.2"}   # good leg via R2
    b = {"prefix": "10.9.9.0/24", "source": "ospf", "next_hop": "10.0.13.3"}   # dead-end leg via R3
    legs = [b, g] if bad_first else [g, b]
    return {"routes": {
        "R1": legs + [{"prefix": "10.0.12.0/30", "source": "connected"},
                      {"prefix": "10.0.13.0/30", "source": "connected"},
                      {"prefix": "10.0.1.0/24", "source": "connected"}],
        "R2": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.9.9.0/24", "source": "connected"}],
        "R3": [{"prefix": "10.0.13.0/30", "source": "connected"}]}}


def test_ecmp_reaches_via_an_equal_cost_alternate_leg():
    """[wave #1 HIGH moat] trace must explore ALL equal-cost legs; the dst is deliverable via R2 regardless of
    which leg compute_fib happens to order first -> computed:reached, never a fabricated computed:unreachable."""
    for bad_first in (False, True):
        t = fib.trace_fib_path(_ecmp_snap(bad_first), "10.0.1.5", "10.9.9.5")
        assert t["status"] == "computed:reached" and t["reached"] is True, f"bad_first={bad_first} -> {t['status']}"


def test_ecmp_reachability_diff_is_order_independent():
    """[wave #2 HIGH moat] Two set-identical ECMP fabrics differing only in leg insertion order must NOT diff as a
    newly_blocked regression (route reordering happens across re-collections / IOS-vs-NXOS show ordering)."""
    d = fib.reachability_diff(_ecmp_snap(False), _ecmp_snap(True), [("10.0.1.5", "10.9.9.5")])
    assert d["pairs"][0]["verdict"] == "preserved", d["pairs"][0]


def test_eigrp_external_admin_distance():
    """[wave #3] 'D EX' (EIGRP external, true AD 170) must not fall through to 255 (a spurious tie with junk)."""
    assert fib._admin_distance("D EX") == 170 and fib._admin_distance("eigrp-external") == 170
    f = fib.compute_fib([{"prefix": "10.5.5.0/24", "source": "frobnicate", "next_hop": "10.0.99.99"},
                         {"prefix": "10.5.5.0/24", "source": "D EX", "next_hop": "10.0.12.2"}])
    assert fib.fib_lookup(f, "10.5.5.5")["next_hop"] == "10.0.12.2"      # AD 170 beats unknown 255


def test_is_connected_is_not_fooled_by_a_substring():
    """[wave #4 moat] 'redistribute connected' / 'disconnected' / 'interconnect' are NOT directly-attached; the
    old `'connect' in s` substring test fabricated a connected dst -> false computed:reached + false diff verdict."""
    for s in ("redistribute connected", "bgp redistributed connected", "disconnected", "interconnect", "Not connected"):
        assert fib._is_connected(s) is False, s
    new = {"routes": {"R1": [{"prefix": "10.0.0.0/30", "source": "connected"},
                             {"prefix": "10.99.99.0/24", "source": "redistribute connected", "next_hop": "10.0.0.2"}]}}
    t = fib.trace_fib_path(new, "10.0.0.1", "10.99.99.5")
    assert t["reached"] is False and t["status"] != "computed:reached"  # dst is NOT attached at R1
    old = {"routes": {"R1": [{"prefix": "10.0.0.0/30", "source": "connected"}]}}
    assert fib.reachability_diff(old, new, [("10.0.0.1", "10.99.99.5")])["pairs"][0]["verdict"] == "inconclusive"


def test_nxos_direct_and_attached_are_connected():
    """[wave #5] NX-OS 'show ip route' labels a directly-attached subnet 'direct' (and the /32 'local'); these
    must be recognized as connected or genuinely-attached destinations are missed (reachable read as lower_bound)."""
    assert fib._is_connected("direct") is True and fib._is_connected("attached") is True
    snap = {"routes": {"R1": [{"prefix": "10.0.0.0/30", "source": "connected"},
                              {"prefix": "192.168.1.0/24", "source": "direct"}]}}
    assert fib.trace_fib_path(snap, "10.0.0.1", "192.168.1.50")["status"] == "computed:reached"


def test_transit_mask_mismatch_is_ambiguous_not_a_fabricated_drop():
    """[wave #6 HIGH moat] When two collected hosts both have a connected route covering the next-hop IP but at
    DIFFERENT masks (/30 vs /24 on the same wire), the next hop cannot be pinned -> ambiguous lower bound, NOT a
    definitive computed:unreachable / newly_blocked (the most-specific owner might be the dead-end)."""
    snap = {"routes": {
        "A": [{"prefix": "10.0.0.0/24", "source": "connected"}, {"prefix": "10.255.1.0/30", "source": "connected"},
              {"prefix": "9.9.9.9/32", "source": "static", "next_hop": "10.255.1.2"}],
        "GW": [{"prefix": "10.255.1.0/24", "source": "connected"}, {"prefix": "9.9.9.9/32", "source": "connected"}],
        "DEADEND": [{"prefix": "10.255.1.0/30", "source": "connected"}]}}
    t = fib.trace_fib_path(snap, "10.0.0.5", "9.9.9.9")
    assert t["computed"] is False and t["status"] == "lower_bound:ambiguous_next_hop"


def test_ambiguous_source_ip_is_a_lower_bound_not_a_verdict():
    """[wave #8/#12 HIGH moat] A src IP owned by >1 collected host (a transit /30, connected on both ends) must
    not be silently resolved via sorted src_hosts[0] -> the verdict would flip on hostname order alone."""
    snap = {"routes": {
        "R1": [{"prefix": "192.168.0.0/30", "source": "connected"}, {"prefix": "172.16.0.0/24", "source": "connected"}],
        "R2": [{"prefix": "192.168.0.0/30", "source": "connected"}]}}
    t = fib.trace_fib_path(snap, "192.168.0.1", "172.16.0.5")
    assert t["computed"] is False and t["status"] == "lower_bound:ambiguous_src"
    # and the diff must not fabricate a verdict off that ambiguous source
    new = {"routes": {"R1": [{"prefix": "192.168.0.0/30", "source": "connected"}],
                      "R2": [{"prefix": "192.168.0.0/30", "source": "connected"}]}}
    assert fib.reachability_diff(snap, new, [("192.168.0.1", "172.16.0.5")])["pairs"][0]["verdict"] == "inconclusive"


def test_cross_family_pair_is_never_reached():
    """[wave #9 HIGH moat] A v6-src / v4-dst flow is physically impossible; it must never be certified
    computed:reached (which fed the flagship diff a fabricated 'preserved')."""
    snap = {"routes": {
        "R1": [{"prefix": "2001:db8:1::/64", "source": "connected"}, {"prefix": "10.0.1.0/24", "source": "connected"},
               {"prefix": "10.0.2.0/24", "source": "ospf", "next_hop": "10.0.1.2"}],
        "R2": [{"prefix": "10.0.1.0/24", "source": "connected"}, {"prefix": "10.0.2.0/24", "source": "connected"}]}}
    t = fib.trace_fib_path(snap, "2001:db8:1::9", "10.0.2.9")
    assert t["reached"] is False and t["status"] == "lower_bound:cross_family"
    assert fib.reachability_diff(snap, snap, [("2001:db8:1::9", "10.0.2.9")])["pairs"][0]["verdict"] == "inconclusive"


def test_trace_and_diff_are_total_on_scalar_routes():
    """[wave #10/#11] A host mapping to a non-iterable scalar must not raise -- the module promises total fns."""
    assert fib.compute_fib(5) == [] and fib.compute_fib("oops") == []
    assert fib.trace_fib_path({"routes": {"R1": 5}}, "1.1.1.1", "2.2.2.2")["computed"] is False
    assert fib.reachability_diff({"routes": {"R1": 5}}, {"routes": {"R2": None}},
                                 [("1.1.1.1", "2.2.2.2")])["pairs"][0]["verdict"] == "inconclusive"


def test_odr_admin_distance():
    """[wave L1] ODR has true AD 160, not OSPF's 110 (it was misread via the startswith('o') branch)."""
    assert fib._admin_distance("ODR") == 160


def test_forwarding_loop_without_escape_is_a_lower_bound():
    """A routing loop (R1 default->R2, R2 default->R1) must resolve to lower_bound:loop -- never computed:reached
    and never a fabricated computed:unreachable. (Locks the memoized cycle-detection rewrite.)"""
    loop = {"routes": {
        "R1": [{"prefix": "10.1.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
               {"prefix": "0.0.0.0/0", "source": "static", "next_hop": "10.0.12.2"}],
        "R2": [{"prefix": "10.0.12.0/30", "source": "connected"},
               {"prefix": "0.0.0.0/0", "source": "static", "next_hop": "10.0.12.1"}]}}
    t = fib.trace_fib_path(loop, "10.1.1.5", "8.8.8.8")
    assert t["status"] == "lower_bound:loop" and t["reached"] is False and t["computed"] is False


def test_ecmp_escape_leg_reaches_despite_a_looping_sibling_leg():
    """One ECMP leg loops back, the other escapes to the dst -> reached via the escape (R1->R3), since a router
    load-balances and the flow can take the working leg."""
    esc = {"routes": {
        "R1": [{"prefix": "10.1.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
               {"prefix": "10.0.13.0/30", "source": "connected"},
               {"prefix": "9.9.9.0/24", "source": "ospf", "next_hop": "10.0.12.2"},
               {"prefix": "9.9.9.0/24", "source": "ospf", "next_hop": "10.0.13.3"}],
        "R2": [{"prefix": "10.0.12.0/30", "source": "connected"},
               {"prefix": "9.9.9.0/24", "source": "static", "next_hop": "10.0.12.1"}],   # loops back to R1
        "R3": [{"prefix": "10.0.13.0/30", "source": "connected"}, {"prefix": "9.9.9.0/24", "source": "connected"}]}}
    t = fib.trace_fib_path(esc, "10.1.1.5", "9.9.9.9")
    assert t["status"] == "computed:reached" and [h["host"] for h in t["hops"]] == ["R1", "R3"]


def test_reachability_delta_flags_a_cutover_regression():
    """W2 live: reachability_delta auto-derives representative inter-subnet pairs from the baseline and flags a
    flow that a change definitively broke -> the pre-cutover proof, surfaced in the --compare verdict."""
    before = {"routes": {
        "R1": [{"prefix": "10.1.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
               {"prefix": "10.2.2.0/24", "source": "ospf", "next_hop": "10.0.12.2"}],
        "R2": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.2.2.0/24", "source": "connected"}]}}
    after = {"routes": {
        "R1": [{"prefix": "10.1.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"}],
        "R2": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.2.2.0/24", "source": "connected"}]}}
    d = fib.reachability_delta(before, after)
    assert d["summary"].get("newly_blocked", 0) >= 1
    assert any(p["verdict"] == "newly_blocked" and p["src"] == "10.1.1.1" and p["dst"] == "10.2.2.1"
               for p in d["newly_blocked"])
    assert d["pairs_tested"] >= 1 and d["subnets_tested"] >= 2


def test_reachability_delta_empty_and_total_without_routes():
    """No routes -> empty (zero pairs), never a crash and never a fabricated regression."""
    d = fib.reachability_delta({"devices": {"x": {}}}, {"devices": {"x": {}}})
    assert d["summary"] == {} and d["pairs_tested"] == 0 and d["newly_blocked"] == []
    assert fib.reachability_delta(None, None)["pairs_tested"] == 0


def test_default_pairs_are_deterministic_and_bounded():
    snap = {"routes": {f"H{i}": [{"prefix": f"10.{i}.0.0/24", "source": "connected"}] for i in range(40)}}
    p1 = fib.default_pairs(snap, limit=8)
    p2 = fib.default_pairs(snap, limit=8)
    assert p1 == p2                                   # deterministic
    assert 0 < len(p1) <= 2 * 8 * (2 * 8 - 1)          # bounded by limit subnets x 2 reps each (inter-subnet only)
    assert all(isinstance(a, str) and isinstance(b, str) and a != b for a, b in p1)


def test_null0_discard_route_is_a_definitive_drop():
    """[w2-live wave #1 HIGH moat] A Null0/discard route is a FULLY-COLLECTED definitive drop (the router
    discards the packet), not a lower bound -> computed:unreachable. Distinct from a real-egress interface route
    (blank next-hop, non-discard interface) which stays a coverage-honest lower bound. Without this a cutover that
    leaves a blackhole / summary-blackholes a more-specific reads CLEAN."""
    drop = {"routes": {"R1": [{"prefix": "10.0.1.0/24", "source": "connected"},
                              {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Null0"}]}}
    t = fib.trace_fib_path(drop, "10.0.1.1", "10.2.2.5")
    assert t["status"] == "computed:unreachable" and t["computed"] is True and t["reached"] is False
    # the BGP blackhole form 'via 0.0.0.0, Null0' (non-blank next-hop) is also a definitive drop
    bgp = {"routes": {"R1": [{"prefix": "10.0.1.0/24", "source": "connected"},
                             {"prefix": "10.5.0.0/16", "source": "bgp", "next_hop": "0.0.0.0", "out_intf": "Null0"}]}}
    assert fib.trace_fib_path(bgp, "10.0.1.1", "10.5.1.1")["status"] == "computed:unreachable"
    # a real-egress interface route (blank next-hop, NON-discard intf) stays a lower bound -- coverage-honest
    egress = {"routes": {"R1": [{"prefix": "10.0.1.0/24", "source": "connected"},
                                {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "", "out_intf": "Gi0/3"}]}}
    assert fib.trace_fib_path(egress, "10.0.1.1", "10.2.2.5")["status"] == "lower_bound:next_hop_not_collected"


def test_reachability_delta_catches_an_upper_half_more_specific_drop():
    """[w2-live wave #2 recall] a cutover that black-holes the UPPER half of a /24 (a more-specific /25 -> Null0)
    breaks flows to that half but NOT to .1; sampling first+last host per subnet catches it (the .1-only sample
    silently missed it). The common 'summary/aggregate blackholes part of a subnet' regression class."""
    base = {"R1": [{"prefix": "10.1.1.0/24", "source": "connected"}, {"prefix": "10.0.12.0/30", "source": "connected"},
                   {"prefix": "10.2.2.0/24", "source": "static", "next_hop": "10.0.12.2"}],
            "R2": [{"prefix": "10.0.12.0/30", "source": "connected"}, {"prefix": "10.2.2.0/24", "source": "connected"}]}
    after = {k: list(v) for k, v in base.items()}
    after["R2"] = after["R2"] + [{"prefix": "10.2.2.128/25", "source": "static", "next_hop": "", "out_intf": "Null0"}]
    d = fib.reachability_delta({"routes": base}, {"routes": after})
    assert any(p["dst"] == "10.2.2.254" and p["verdict"] == "newly_blocked" for p in d["newly_blocked"])


def test_subnet_reps_samples_first_and_last_host():
    """Each subnet contributes its first AND last usable host (deduped), so an upper- or lower-half drop is
    sampled. /30 -> .1 and .2; /24 -> .1 and .254; a /31 -> its two addresses."""
    snap = {"routes": {"R1": [{"prefix": "10.2.2.0/24", "source": "connected"},
                              {"prefix": "10.0.12.0/30", "source": "connected"}]}}
    reps = fib.subnet_reps(snap)
    ips = {ip for _net, ip in reps}
    assert {"10.2.2.1", "10.2.2.254"} <= ips and {"10.0.12.1", "10.0.12.2"} <= ips


def test_subnet_reps_skips_default_route():
    """[w2-live wave L3] a 0.0.0.0/0 / ::/0 'connected' route is not a probeable subnet -- it must not produce a
    synthetic 0.0.0.1 rep (which made default-route REMOVAL look like a concrete newly_blocked flow)."""
    snap = {"routes": {"R1": [{"prefix": "0.0.0.0/0", "source": "connected"},          # a /0 tagged connected
                              {"prefix": "10.1.1.0/24", "source": "connected"}]}}
    reps = fib.subnet_reps(snap)
    assert all(net not in ("0.0.0.0/0", "::/0") for net, _ip in reps)
    assert any(net == "10.1.1.0/24" for net, _ip in reps)


def test_reachability_delta_discloses_bounded_coverage():
    """[w2-live wave #5/#6/#7/#8 moat] the subnet cap must be DISCLOSED (no silent caps): subnets_total reflects
    the true count, capped is True, and assessed says whether any flow was actually computed."""
    snap = {"routes": {f"H{i}": [{"prefix": f"10.{i}.0.0/24", "source": "connected"}] for i in range(30)}}
    d = fib.reachability_delta(snap, snap, limit=8)
    assert d["subnets_total"] == 30 and d["subnets_tested"] == 8 and d["capped"] is True and d["assessed"] is True
    d2 = fib.reachability_delta({"routes": {}}, {"routes": {}})
    assert d2["assessed"] is False and d2["subnets_total"] == 0 and d2["capped"] is False


def test_real_route_source_codes_map_correctly():
    """Format-fidelity vs REAL [HISTORY-REDACTED] snapshot source values (a mix of expanded names AND raw codes with the '*'
    candidate-default marker): 's*' is static, 'o*ia' is OSPF inter-area, '' is unknown. _is_connected and the
    admin-distance must not be fooled by the code/marker form (the recurring self-authored-fixture defect class)."""
    assert fib._admin_distance("s*") == 1            # static + candidate-default
    assert fib._admin_distance("o*ia") == 110        # ospf inter-area
    assert fib._admin_distance("connected") == 0 and fib._admin_distance("ospf") == 110
    assert fib._admin_distance("") == 255 and fib._admin_distance(None) == 255
    assert fib._is_connected("connected") and fib._is_connected("c") and fib._is_connected("local")
    assert not fib._is_connected("s*") and not fib._is_connected("o*ia") and not fib._is_connected("")
    # a host whose connected route carries the bare 'c' code is still indexed as a subnet owner
    snap = {"routes": {"X": [{"prefix": "10.9.9.0/24", "source": "c"}]}}
    assert fib._hosts_owning_ip(fib._connected_index(snap["routes"]), "10.9.9.5") == ["X"]
