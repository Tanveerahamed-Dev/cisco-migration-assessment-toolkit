"""Native longest-prefix-match RIB -> FIB resolver (universal-best roadmap W2-1).

The seam that upgrades reachability from L2 topology-BFS (a 'lower bound', analyze.py:2186) to a COMPUTED L3
forwarding resolution over the already-parsed per-host routes (snap['routes'] = {host: [{prefix, source,
next_hop, out_intf}]}, COLLECT_PARSE_V3_23_0.py:2324). Pure stdlib (ipaddress) -- fully OFFLINE, no new
dependency, no egress; an opt-in pybatfish power-mode is a deliberately SEPARATE future concern, never wired in
here. COVERAGE-HONEST by construction: a resolved lookup is computed from the collected routes; a destination
with NO matching route returns None ('no route observed' -- a lower bound, never a fabricated 'reachable').
"""
import ipaddress
from typing import List, Optional, Tuple


def _ip(s) -> Optional["ipaddress._BaseAddress"]:
    """Parse an IP that may carry a Cisco zone-id / scope suffix and return an ip_address, or None (never raises).
    Cisco prints an IPv6 link-local next-hop with the egress interface as a zone-id ('fe80::2%Gi0/1') -- and a '/'
    in the interface name ('Gi0/1','Te1/0/1','Eth1/1') makes ipaddress.ip_address RAISE on Python 3.9+, while a
    slash-free one ('%Vlan10','%Port-channel1') parses. So the zone is stripped UNCONDITIONALLY (the engine has no
    per-zone interface-IP data to use it anyway) -- otherwise a routed-over-link-local v6 fabric (the OSPFv3 /
    IS-IS / BGP-over-LLA norm) would silently lose reachability recall, intermittently by interface type."""
    try:
        return ipaddress.ip_address(str(s).split("%", 1)[0].strip())
    except ValueError:
        return None


def _admin_distance(source: str) -> int:
    """Cisco administrative distance for a route source (lower wins on an equal-length prefix). Used only as the
    tie-breaker between same-prefix routes; longest-prefix-match always dominates. Tolerant of BOTH the expanded
    names parse_ip_routes emits ('connected','static','ospf') AND the raw route-codes that survive on some entries
    ('s*' static+candidate-default, 'o*ia' ospf-inter-area, 'c','l','b','d','i','r') -- the '*' candidate-default
    marker and spaces are stripped first. Unknown / blank sources sort last (255). [verified vs real [HISTORY-REDACTED] sources]"""
    s = str(source or "").strip().lower().replace("*", "").replace(" ", "")
    if not s:
        return 255
    if "connect" in s or s in ("c", "l", "local"):
        return 0
    if "static" in s or s in ("s", "su"):
        return 1
    if "bgp" in s or s == "b":
        return 20            # eBGP default (iBGP 200 is indistinguishable from the parsed code, so use the lower)
    if "eigrp" in s or s == "d":
        return 170 if "ex" in s or "external" in s else 90
    # OSPF family BEFORE isis: 'oia'/'on1'/'oe2' (and the bare inter/nssa/ext codes) start with the same letters
    if "ospf" in s or s.startswith("o") or s in ("ia", "n1", "n2", "e1", "e2"):
        return 110
    if "isis" in s or s == "i":
        return 115
    if "rip" in s or s == "r":
        return 120
    return 255


def _is_connected(source: str) -> bool:
    """A directly-attached route (connected/local), in either the expanded-name or raw-code form."""
    return _admin_distance(source) == 0


# A FIB is a list of (network, admin_distance, route_dict), sorted longest-prefix-first then lowest-AD.
Fib = List[Tuple["ipaddress._BaseNetwork", int, dict]]


def compute_fib(routes) -> Fib:
    """Build a longest-prefix-match FIB from a host's parsed route list. Tolerant: a non-dict / blank-prefix /
    unparseable-prefix entry is skipped (never raises); None -> []. The result is consumed by fib_lookup()."""
    entries: Fib = []
    for r in (routes or []):
        if not isinstance(r, dict):
            continue
        prefix = str(r.get("prefix", "")).strip()
        if not prefix:
            continue
        try:
            net = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        entries.append((net, _admin_distance(r.get("source")), dict(r)))
    # longest prefix first; on an equal-length prefix, the lower administrative distance wins
    entries.sort(key=lambda e: (-e[0].prefixlen, e[1]))
    return entries


def fib_lookup(fib: Fib, dst_ip: str) -> Optional[dict]:
    """The longest-prefix-match route for `dst_ip`, or None if NO route is observed for it (the coverage-honest
    lower bound -- absence of a route is never silently turned into reachability). Returns a copy of the matching
    route dict annotated with {'match': <prefix>, 'computed': True}. Total: a bad dst returns None, never raises."""
    ip = _ip(dst_ip)
    if ip is None:
        return None
    for net, _ad, r in (fib or []):
        if ip.version == net.version and ip in net:
            return {**r, "match": str(net), "computed": True}
    return None


def _connected_index(routes_by_host) -> dict:
    """{host: [connected networks]} -- which subnets each host is directly attached to (its connected/local
    routes), used to find which collected host a next-hop IP lives behind."""
    idx: dict = {}
    for host, routes in (routes_by_host or {}).items():
        nets = []
        for r in (routes or []):
            if isinstance(r, dict) and _is_connected(r.get("source")):
                try:
                    nets.append(ipaddress.ip_network(str(r.get("prefix", "")).strip(), strict=False))
                except ValueError:
                    pass
        idx[host] = nets
    return idx


def _hosts_owning_ip(connected_idx: dict, ip_str: str, exclude: str = None) -> list:
    """The collected host(s) whose LONGEST connected subnet contains `ip_str` (so a /30 transit link beats an
    enclosing summary), optionally excluding one host. Returns a sorted list -- usually one host, but a transit
    subnet is connected on BOTH ends and a multi-access segment on several, so the caller must treat >1 as
    genuinely ambiguous (a next-hop IP cannot be pinned to one host without interface-IP data) rather than guess."""
    ip = _ip(ip_str)             # tolerates an IPv6 link-local zone-id ('fe80::2%Gi0/1') -- see _ip()
    if ip is None:
        return []
    matches = []   # (prefixlen, host)
    for host, nets in (connected_idx or {}).items():
        if host == exclude:
            continue
        for net in nets:
            if ip.version == net.version and ip in net:
                matches.append((net.prefixlen, host))
    if not matches:
        return []
    best = max(pl for pl, _ in matches)
    return sorted({h for pl, h in matches if pl == best})


def trace_fib_path(snap, src_ip: str, dst_ip: str, max_hops: int = 32) -> dict:
    """Compute the L3 forwarding path src_ip -> dst_ip by walking FIB lookups host-to-host over snap['routes'] --
    the COMPUTED upgrade to the L2 topology 'lower bound' (analyze.py trace_full_flow). At each host the dst is
    resolved by longest-prefix-match; the next-hop IP locates the next collected host via its connected subnets.

    COVERAGE-HONEST: the walk STOPS and labels the reason rather than fabricating reachability -- a hop with no
    matching route ('no_route'), a next-hop whose host was not collected ('next_hop_not_collected'), a routing
    loop ('loop'), or the source host not found. `computed` is True only when the path resolved end-to-end from
    the collected routes; otherwise the result is an explicit lower bound. Pure/offline; total on bad input.

    Returns {src, dst, hops:[{host, match, next_hop, out_intf, source}], status, computed:bool, reached:bool}."""
    snap = snap if isinstance(snap, dict) else {}
    routes_by_host = snap.get("routes") if isinstance(snap.get("routes"), dict) else {}
    fibs = {h: compute_fib(r) for h, r in routes_by_host.items()}
    connected = _connected_index(routes_by_host)

    def _result(hops, status, reached):
        return {"src": src_ip, "dst": dst_ip, "hops": hops, "status": status,
                "computed": status.startswith("computed"), "reached": reached}

    src_hosts = _hosts_owning_ip(connected, src_ip)
    if not src_hosts:
        return _result([], "lower_bound:src_host_not_found", False)
    cur = src_hosts[0]

    hops, visited, status = [], set(), "lower_bound:max_hops"
    while cur and cur not in visited and len(hops) < max_hops:
        visited.add(cur)
        m = fib_lookup(fibs.get(cur, []), dst_ip)
        if not m:
            # the COLLECTED router has no matching route and no default -> per its RIB it definitively DROPS.
            # This is a COMPUTED unreachable (a definitive verdict about the collected evidence), distinct from
            # the lower-bound stops below where the trail is lost to incomplete collection.
            status = "computed:unreachable"
            break
        hops.append({"host": cur, "match": m["match"], "next_hop": str(m.get("next_hop", "") or ""),
                     "out_intf": str(m.get("out_intf", "") or ""), "source": str(m.get("source", "") or "")})
        if _is_connected(m.get("source")):
            return _result(hops, "computed:reached", True)          # dst is directly attached here
        nh = str(m.get("next_hop", "")).strip()
        nxts = _hosts_owning_ip(connected, nh, exclude=cur) if nh else []
        if not nxts:
            status = "lower_bound:next_hop_not_collected"
            break
        if len(nxts) > 1:                                            # multi-access: cannot pin without iface IPs
            status = "lower_bound:ambiguous_next_hop"
            break
        cur = nxts[0]
    else:
        status = "lower_bound:loop" if cur in visited else "lower_bound:max_hops"
    return _result(hops, status, False)


def reachability_diff(old_snap, new_snap, pairs) -> dict:
    """Differential what-if over two snapshots (the cisco-assess --compare flow): for each (src_ip, dst_ip) pair,
    classify how COMPUTED forwarding reachability changed -- the pre-cutover proof that a migration preserves (or
    breaks) reachability, which Batfish/Forward sell as their flagship and which the engine now does natively and
    offline.

    COVERAGE-HONEST: a definitive verdict requires BOTH traces to be computed end-to-end (reached, or a
    definitive computed:unreachable). If EITHER side is a lower bound -- the trail lost to incomplete collection
    (next_hop_not_collected / ambiguous_next_hop / loop / src_host_not_found) -- the verdict is 'inconclusive',
    never a false 'preserved' or 'newly_blocked'. Verdicts: preserved | newly_blocked (a REGRESSION: a
    previously-working flow now drops) | newly_reachable | both_unreachable | inconclusive.

    Returns {pairs:[{src,dst,old_status,new_status,verdict}], summary:{verdict:count}}. Pure/offline; total."""
    rows, summary = [], {}
    for pair in (pairs or []):
        try:
            src, dst = pair[0], pair[1]
        except (TypeError, IndexError, KeyError):
            continue
        o = trace_fib_path(old_snap, src, dst)
        n = trace_fib_path(new_snap, src, dst)
        if not (o["computed"] and n["computed"]):
            v = "inconclusive"
        elif o["reached"] and n["reached"]:
            v = "preserved"
        elif o["reached"] and not n["reached"]:
            v = "newly_blocked"
        elif not o["reached"] and n["reached"]:
            v = "newly_reachable"
        else:
            v = "both_unreachable"
        rows.append({"src": src, "dst": dst, "old_status": o["status"], "new_status": n["status"], "verdict": v})
        summary[v] = summary.get(v, 0) + 1
    return {"pairs": rows, "summary": summary}
