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
    # Connected / directly-attached: EXACT codes + the 'directly connected' / NX-OS 'direct' / 'attached' forms.
    # NOT a bare 'connect' substring -- that misread 'redistribute connected' / 'disconnected' / 'interconnect'
    # as directly-attached, fabricating a reached destination (adversarial-wave #4).
    if s in ("c", "l", "local", "connected", "direct", "attached") or s.startswith(("connected", "directlyconnected", "direct", "local")):
        return 0
    if "static" in s or s in ("s", "su"):
        return 1
    if "bgp" in s or s == "b":
        return 20            # eBGP default (iBGP 200 is indistinguishable from the parsed code, so use the lower)
    if "eigrp" in s or s == "d" or s.startswith("dex"):
        return 170 if "ex" in s else 90       # 'D EX' -> 'dex' (EIGRP external) = 170, internal 'D'/'eigrp' = 90
    if s == "odr":
        return 160                            # on-demand routing -- BEFORE the OSPF startswith('o') branch
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


def _is_discard(out_intf) -> bool:
    """A discard / blackhole egress -- a route to Null0 (also abbreviated Nu0) or an explicit 'discard'. Such a
    route is a FULLY-COLLECTED definitive drop (the router silently discards the packet), NOT a missing next hop:
    a cutover that leaves a drop route or summary-blackholes a more-specific must read as computed:unreachable,
    never as a coverage-honest lower bound. No real forwarding interface name begins 'nu'."""
    s = str(out_intf or "").strip().lower().replace(" ", "")
    return s.startswith("nu") or s == "discard"


# A FIB is a list of (network, admin_distance, route_dict), sorted longest-prefix-first then lowest-AD.
Fib = List[Tuple["ipaddress._BaseNetwork", int, dict]]


def compute_fib(routes) -> Fib:
    """Build a longest-prefix-match FIB from a host's parsed route list. Tolerant: a non-dict / blank-prefix /
    unparseable-prefix entry is skipped (never raises); None / a non-list scalar -> []. Consumed by fib_lookup()."""
    entries: Fib = []
    if not isinstance(routes, (list, tuple)):
        return entries                       # total: a host mapped to a scalar/None yields an empty FIB, not a raise
    for r in routes:
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


def fib_lookup_all(fib: Fib, dst_ip: str) -> List[dict]:
    """ALL equal-cost routes at the longest matching prefix for `dst_ip` (the installed ECMP set), or [] if NO
    route is observed. A real router installs every equal-cost (same-prefix, same-AD) leg and load-balances, so a
    flow can take ANY of them -- the path tracer must consider all, not just the first (adversarial-wave #1/#2).
    Same-prefix routes with a WORSE admin distance are shadowed (not installed) and excluded. Coverage-honest:
    absence of a route is [] (never fabricated reachability). Total: a bad dst returns [], never raises."""
    ip = _ip(dst_ip)
    if ip is None:
        return []
    key = None
    out: List[dict] = []
    for net, ad, r in (fib or []):          # fib is sorted (-prefixlen, ad): the first match is longest + lowest-AD
        if ip.version != net.version or ip not in net:
            continue
        if key is None:
            key = (net.prefixlen, ad)
        if (net.prefixlen, ad) == key:
            out.append({**r, "match": str(net), "computed": True})
        else:
            break                           # less-specific or higher-AD than the installed set -> shadowed
    return out


def fib_lookup(fib: Fib, dst_ip: str) -> Optional[dict]:
    """The longest-prefix-match route for `dst_ip` (the first of any equal-cost set), or None if NO route is
    observed (the coverage-honest lower bound -- absence is never silently turned into reachability). Returns a
    copy of the matching route dict annotated with {'match': <prefix>, 'computed': True}. Total; never raises."""
    matches = fib_lookup_all(fib, dst_ip)
    return matches[0] if matches else None


def _connected_index(routes_by_host) -> dict:
    """{host: [connected networks]} -- which subnets each host is directly attached to (its connected/local
    routes), used to find which collected host a next-hop IP lives behind."""
    idx: dict = {}
    for host, routes in (routes_by_host or {}).items():
        nets = []
        for r in (routes if isinstance(routes, (list, tuple)) else []):
            if isinstance(r, dict) and _is_connected(r.get("source")):
                try:
                    nets.append(ipaddress.ip_network(str(r.get("prefix", "")).strip(), strict=False))
                except ValueError:
                    pass
        idx[host] = nets
    return idx


def _hosts_owning_ip(connected_idx: dict, ip_str: str, exclude: str = None) -> list:
    """EVERY collected host whose connected subnets contain `ip_str` (sorted, optionally excluding one host).
    Returns ALL distinct owners regardless of mask -- usually one, but a transit subnet is connected on BOTH ends
    and a multi-access (or mask-mismatched) segment on several. The caller MUST treat >1 as genuinely ambiguous
    (a next-hop/host IP cannot be pinned to one router without interface-IP data) rather than pick the
    most-specific owner -- doing so silently chose a dead-end co-owner and fabricated a definitive drop
    (adversarial-wave #6). Tolerates an IPv6 link-local zone-id ('fe80::2%Gi0/1') -- see _ip()."""
    ip = _ip(ip_str)
    if ip is None:
        return []
    hosts = set()
    for host, nets in (connected_idx or {}).items():
        if host == exclude:
            continue
        for net in nets:
            if ip.version == net.version and ip in net:
                hosts.add(host)
                break
    return sorted(hosts)


def trace_fib_path(snap, src_ip: str, dst_ip: str, max_hops: int = 32) -> dict:
    """Compute the L3 forwarding path src_ip -> dst_ip by resolving FIB lookups host-to-host over snap['routes'] --
    the COMPUTED upgrade to the L2 topology 'lower bound' (analyze.py trace_full_flow). At each host the dst is
    resolved by longest-prefix-match; ALL equal-cost (ECMP) legs are explored; the next-hop IP locates the next
    collected host via its connected subnets.

    COVERAGE-HONEST -- a definitive verdict is never fabricated from incomplete exploration:
      * computed:reached    -- some path resolved end-to-end to a directly-attached dst (computed=True).
      * computed:unreachable -- EVERY equal-cost leg from a collected router definitively drops per its RIB
                                (no matching route + no default anywhere reachable) (computed=True).
      * lower_bound:*       -- the trail is lost to incomplete collection or genuine ambiguity, so neither a
                                reach nor a definitive drop can be asserted (computed=False): next_hop_not_collected,
                                ambiguous_next_hop (a next-hop IP shared by >1 collected host), ambiguous_src (a
                                source IP on a shared/transit subnet), cross_family (a v4<->v6 flow), src_host_not_found,
                                bad_address, loop, max_hops.
    Reach wins over any lower bound, which wins over a definitive drop -- so one inconclusive leg prevents a false
    computed:unreachable. Pure/offline; total on bad input.

    Returns {src, dst, hops:[{host, match, next_hop, out_intf, source}], status, computed:bool, reached:bool}."""
    fibs, connected = _build(snap)
    return _trace(fibs, connected, src_ip, dst_ip)


def _build(snap):
    """(fibs, connected) for a snapshot -- the per-host FIBs + the connected-subnet index. Built ONCE so a
    reachability matrix over many pairs (reachability_diff/reachability_delta) doesn't recompute them per trace."""
    snap = snap if isinstance(snap, dict) else {}
    routes_by_host = snap.get("routes") if isinstance(snap.get("routes"), dict) else {}
    fibs = {h: compute_fib(r) for h, r in routes_by_host.items()}
    connected = _connected_index(routes_by_host)
    return fibs, connected


def _trace(fibs, connected, src_ip, dst_ip):
    """Core trace over PREBUILT (fibs, connected); coverage-honest semantics per trace_fib_path()."""

    def _result(hops, status, reached):
        return {"src": src_ip, "dst": dst_ip, "hops": hops, "status": status,
                "computed": status.startswith("computed"), "reached": reached}

    sip, dip = _ip(src_ip), _ip(dst_ip)
    if sip is None or dip is None:
        return _result([], "lower_bound:bad_address", False)
    if sip.version != dip.version:                          # a v4<->v6 flow is impossible -- never certify reached
        return _result([], "lower_bound:cross_family", False)

    src_hosts = _hosts_owning_ip(connected, src_ip)
    if not src_hosts:
        return _result([], "lower_bound:src_host_not_found", False)

    def _rank(status):                                      # reach > any lower bound > a definitive drop
        return 2 if status.startswith("computed:reached") else (1 if status.startswith("lower_bound") else 0)

    memo, computing = {}, set()                             # per-trace; the verdict-from-a-host is intrinsic

    def _cache(host, res):
        if not (res[0].endswith(":loop") or res[0].endswith(":max_hops")):
            memo[host] = res                                # cache only path-INDEPENDENT verdicts (not loop/cutoff)
        return res

    def _explore_set(hosts, amb_status):
        """Resolve forwarding from a SET of candidate hosts for ONE unknown-but-fixed hop -- a next-hop IP or the
        source IP shared by >1 collected host (a transit/multi-access subnet, where the exact owner can't be pinned
        without interface-IP data). Definitive ONLY when every candidate agrees: all reach -> reached; all
        definitively drop -> unreachable; any disagreement or lower bound -> the ambiguous lower bound. This keeps
        recall (the common case: every possible forwarder routes the dst alike) without guessing which is real."""
        if len(hosts) == 1:
            return _explore(hosts[0])
        results = [_explore(h) for h in hosts]
        if all(r[1] for r in results):
            return ("computed:reached", True, results[0][2])          # every possible forwarder reaches
        if all(r[0] == "computed:unreachable" for r in results):
            return ("computed:unreachable", False, results[0][2])     # every possible forwarder definitively drops
        return (amb_status, False, [])                                # disagreement / a lower bound -> ambiguous

    def _explore(host):
        """(status, reached, hops_from_host) for the dst from `host`, exploring every equal-cost (ECMP) leg -- a
        router load-balances so the flow can take any leg: reach if ANY leg reaches. MEMOIZED per host (the verdict
        is intrinsic to the host, not to how it was reached), so a shared-subnet fan-out is linear, not exponential;
        an in-progress host is a forwarding loop (returned but never cached)."""
        if host in memo:
            return memo[host]
        if host in computing:
            return ("lower_bound:loop", False, [])         # cycle back-edge -- path-dependent, do not cache
        legs = fib_lookup_all(fibs.get(host, []), dst_ip)
        if not legs:
            return _cache(host, ("computed:unreachable", False, []))  # no route + no default -> definitive drop
        computing.add(host)
        best = None
        for m in legs:
            hop = {"host": host, "match": m["match"], "next_hop": str(m.get("next_hop", "") or ""),
                   "out_intf": str(m.get("out_intf", "") or ""), "source": str(m.get("source", "") or "")}
            if _is_connected(m.get("source")):
                best = ("computed:reached", True, [hop])              # dst is directly attached on this leg
                break
            if _is_discard(m.get("out_intf")):                       # Null0/discard egress -> definitive drop
                cand = ("computed:unreachable", False, [hop])
            else:
                nh = str(m.get("next_hop", "")).strip()
                nxts = _hosts_owning_ip(connected, nh, exclude=host) if nh else []
                if not nxts:
                    cand = ("lower_bound:next_hop_not_collected", False, [hop])
                else:
                    sub = _explore_set(nxts, "lower_bound:ambiguous_next_hop")
                    cand = (sub[0], sub[1], [hop] + sub[2])
            if cand[1]:
                best = cand                                          # ECMP existential: any leg reaches
                break
            if best is None or _rank(cand[0]) > _rank(best[0]):
                best = cand                                          # most informative: lower_bound beats a drop
        computing.discard(host)
        return _cache(host, best)

    try:
        status, reached, hops = _explore_set(src_hosts, "lower_bound:ambiguous_src")
    except RecursionError:                                  # pathological deep chain -- stay total
        return _result([], "lower_bound:max_hops", False)
    return _result(hops, status, reached)


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
    of, nf = _build(old_snap), _build(new_snap)            # build each snapshot's FIB ONCE, not per pair
    rows, summary = [], {}
    for pair in (pairs or []):
        try:
            src, dst = pair[0], pair[1]
        except (TypeError, IndexError, KeyError):
            continue
        o = _trace(of[0], of[1], src, dst)
        n = _trace(nf[0], nf[1], src, dst)
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


def subnet_reps(snap, limit: int = 24) -> list:
    """A bounded, deterministic [(network_str, representative_host_ip)] -- one usable host IP per collected
    CONNECTED subnet (the subnet's first host), sorted by (version, network) and capped at `limit`. Skips /32 &
    /128 host routes (not a subnet to test) and unusable prefixes. Used to auto-derive the inter-subnet flows the
    --compare reachability what-if checks. Pure/offline; total."""
    snap = snap if isinstance(snap, dict) else {}
    rbh = snap.get("routes") if isinstance(snap.get("routes"), dict) else {}
    nets: dict = {}
    for _host, routes in rbh.items():
        for r in (routes if isinstance(routes, (list, tuple)) else []):
            if not (isinstance(r, dict) and _is_connected(r.get("source"))):
                continue
            try:
                net = ipaddress.ip_network(str(r.get("prefix", "")).strip(), strict=False)
            except ValueError:
                continue
            if net.prefixlen == 0 or net.num_addresses < 2:   # skip the default route and /32,/128 host routes
                continue
            key = str(net)
            if key not in nets:
                try:
                    nets[key] = str(next(net.hosts()))
                except StopIteration:
                    continue
    ordered = sorted(nets.items(), key=lambda kv: (ipaddress.ip_network(kv[0]).version, ipaddress.ip_network(kv[0])))
    return ordered[:max(0, int(limit))]


def default_pairs(snap, limit: int = 24, max_pairs: int = 400) -> list:
    """Representative inter-subnet flows to test: each collected connected subnet's first host -> every OTHER
    subnet's first host (both directions), bounded (limit subnets, max_pairs total) and deterministic. Pure."""
    reps = [ip for _net, ip in subnet_reps(snap, limit)]
    pairs = []
    for i, a in enumerate(reps):
        for j, b in enumerate(reps):
            if i != j:
                pairs.append((a, b))
                if len(pairs) >= max_pairs:
                    return pairs
    return pairs


def reachability_delta(old_snap, new_snap, pairs=None, limit: int = 24) -> dict:
    """The differential reachability what-if for the --compare cutover validation: classify how COMPUTED
    reachability changed across a representative set of inter-subnet flows (auto-derived from the OLD/baseline
    snapshot when `pairs` is None, so it reflects the pre-change topology). COVERAGE-HONEST: only DEFINITIVE
    verdicts count -- ambiguous / incomplete-collection pairs are 'inconclusive', never a fabricated regression.

    Returns {summary, newly_blocked, newly_reachable, preserved, inconclusive, pairs_tested, subnets_tested,
    subnets_total, assessed, capped}. The headline is newly_blocked -- a flow the change definitively broke. The
    sample is BOUNDED (subnets_total vs subnets_tested, capped) and ONE representative host per subnet -- the
    caller MUST disclose that (a no-silent-caps requirement), so subnets_total/capped/assessed are explicit.
    Pure; total."""
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 24
    all_reps = subnet_reps(old_snap, limit=10 ** 9)            # every connected subnet (uncapped) -> the true total
    subnets_total = len(all_reps)
    subnets_tested = min(subnets_total, limit)
    if pairs is None:
        pairs = default_pairs(old_snap, limit)
    diff = reachability_diff(old_snap, new_snap, pairs)
    summary = diff["summary"]
    pairs_possible = subnets_tested * (subnets_tested - 1) if subnets_tested > 1 else 0
    return {
        "summary": summary,
        "newly_blocked": [p for p in diff["pairs"] if p["verdict"] == "newly_blocked"],
        "newly_reachable": [p for p in diff["pairs"] if p["verdict"] == "newly_reachable"],
        "preserved": summary.get("preserved", 0),
        "inconclusive": summary.get("inconclusive", 0),
        "pairs_tested": len(diff["pairs"]),
        "subnets_tested": subnets_tested,
        "subnets_total": subnets_total,
        "assessed": len(diff["pairs"]) > 0,
        "capped": subnets_total > subnets_tested or len(pairs) < pairs_possible,   # DISCLOSED, never silent
    }
