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


def test_trace_stops_coverage_honest_when_no_route():
    snap = {"routes": {"R1": [{"prefix": "10.1.1.0/24", "next_hop": "", "source": "connected"}]}}
    t = fib.trace_fib_path(snap, "10.1.1.5", "8.8.8.8")      # no default at R1 -> no route
    assert t["computed"] is False and t["reached"] is False and t["status"] == "lower_bound:no_route"


def test_trace_stops_when_next_hop_host_not_collected():
    """R1 routes to a next-hop whose owning router was never collected -> explicit lower bound, not 'reachable'."""
    snap = {"routes": {"R1": [
        {"prefix": "10.1.1.0/24", "next_hop": "", "source": "connected"},
        {"prefix": "0.0.0.0/0", "next_hop": "172.31.99.1", "source": "static"}]}}   # 172.31.99.1 behind nobody collected
    t = fib.trace_fib_path(snap, "10.1.1.5", "8.8.8.8")
    assert t["computed"] is False and t["status"] == "lower_bound:next_hop_not_collected"
    assert [h["host"] for h in t["hops"]] == ["R1"]                                 # got one computed hop, then honest stop


def test_trace_total_on_bad_input():
    assert fib.trace_fib_path(None, "1.1.1.1", "2.2.2.2")["computed"] is False
    assert fib.trace_fib_path({}, "1.1.1.1", "2.2.2.2")["status"] == "lower_bound:src_host_not_found"
    assert fib.trace_fib_path({"routes": "oops"}, "1.1.1.1", "2.2.2.2")["computed"] is False


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
