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
    marker and spaces are stripped first. Unknown / blank sources sort last (255). [verified vs real AJ sources]"""
    s = str(source or "").strip().lower().replace("*", "").replace(" ", "")
    if not s:
        return 255
    # Connected / directly-attached: EXACT codes + the 'directly connected' / NX-OS 'direct' / 'attached' forms.
    # NOT a bare 'connect' substring -- that misread 'redistribute connected' / 'disconnected' / 'interconnect'
    # as directly-attached, fabricating a reached destination (adversarial-wave #4).
    if s in ("c", "l", "local", "connected", "direct", "attached") or s.startswith(("connected", "directlyconnected", "direct", "local")):
        return 0
    # FHRP virtual IP: installed as a self-referential local host route 'X/32 via X, VlanN, [0/0], vrrp_engine|
    # hsrp|glbp' -- locally TERMINATED on the master (the packet is delivered, [0/0] + self-via prove it), so it
    # is a CONNECTED/local route (AD 0), not an unresolvable next-hop (audit-5 #12).
    if "vrrp" in s or "hsrp" in s or "glbp" in s:
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


def _iface_field(rec, field: str):
    """Read one field from an interface record that may be a plain dict (the serialized snapshot shape) OR an
    InterfaceData dataclass (the in-process, pre-serialization shape). Total: returns None on anything else."""
    if isinstance(rec, dict):
        return rec.get(field)
    return getattr(rec, field, None)


def _parse_mtu(raw):
    """Coerce a collected MTU value to a positive int, or None when it is BLANK / unparseable. Blank is
    ABSTENTION -- 'not collected' -- never a fabricated default. build.py leaves mtu '' when the device did not
    report a non-default value, and that '' must stay a blind spot, not silently become 1500."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    # tolerate a trailing 'bytes' or stray non-digits Cisco sometimes prints ('9216 bytes')
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    return val if val > 0 else None


def _hop_mtu(interfaces: dict, host: str, out_intf: str):
    """The observed egress MTU (int) for a traced hop's out-interface, or None if not collected / not found. The
    route's out_intf is matched to the interface port key both verbatim AND via the codebase-canonical short form
    (textutils.normalize_ifname) so 'GigabitEthernet0/1' and 'Gi0/1' resolve to the same record."""
    if not out_intf:
        return None                         # a recursive route with no egress interface -> nothing to observe
    ports = interfaces.get(host) if isinstance(interfaces, dict) else None
    if not isinstance(ports, dict):
        return None
    rec = ports.get(out_intf)
    if rec is None:
        try:
            from .textutils import normalize_ifname
        except Exception:                   # pragma: no cover - textutils always importable in-tree
            normalize_ifname = None
        if normalize_ifname is not None:
            want = normalize_ifname(out_intf)
            for p, r in ports.items():
                if normalize_ifname(p) == want:
                    rec = r
                    break
    if rec is None:
        return None
    return _parse_mtu(_iface_field(rec, "mtu"))


def _annotate_mtu(res: dict, snap, required_mtu=None) -> dict:
    """Add the MTU-dimension keys to a trace result (§3.4). COVERAGE-HONEST: a hop with no collected MTU is
    disclosed as unobserved and makes the path-MTU verdict INDETERMINATE -- it is NEVER assumed to be 1500 (or
    any default). Additive + total: the keys are always present, even on a lower-bound / bad-input result."""
    interfaces = snap.get("interfaces") if isinstance(snap, dict) else None
    req = _parse_mtu(required_mtu) if required_mtu is not None else None

    res.setdefault("mtu_min", None)
    res.setdefault("mtu_bottleneck_hop", None)
    res.setdefault("mtu_unobserved_hops", [])
    res.setdefault("jumbo_blackhole", [])

    hops = res.get("hops") or []
    observed = []           # [(host, out_intf, mtu)]
    unobserved = []         # [{host, out_intf}]
    jumbo = []
    for hop in hops:
        host = hop.get("host", "")
        out_intf = str(hop.get("out_intf", "") or "")
        mtu = _hop_mtu(interfaces, host, out_intf)
        if mtu is None:
            # only count a hop as an MTU blind spot if it actually has an egress interface to have measured
            if out_intf:
                unobserved.append({"host": host, "out_intf": out_intf})
            continue
        observed.append((host, out_intf, mtu))
        if req is not None and mtu < req:
            jumbo.append({"host": host, "out_intf": out_intf, "mtu": mtu, "required": req})

    res["mtu_unobserved_hops"] = unobserved
    res["jumbo_blackhole"] = jumbo

    if observed:
        mtu_min = min(m for _h, _i, m in observed)
        mtu_max = max(m for _h, _i, m in observed)
        res["mtu_min"] = mtu_min
        if mtu_min < mtu_max:
            h, i, _m = min(observed, key=lambda t: t[2])
            res["mtu_bottleneck_hop"] = {"host": h, "out_intf": i, "mtu": mtu_min}

    total = len(observed) + len(unobserved)
    # Verdict precedence (coverage-honest):
    #  - no reached path to audit, or nothing observed at all           -> INDETERMINATE (abstain)
    #  - any hop's MTU was not collected                                -> INDETERMINATE, disclosing N of M
    #  - a genuine narrowing among the observed hops                    -> bottleneck
    #  - every hop observed AND equal                                   -> uniform
    if not res.get("reached") or not observed:
        res["mtu_verdict"] = ("INDETERMINATE -- MTU not collected on {} of {} hops".format(len(unobserved), total)
                              if unobserved else "INDETERMINATE -- no reached path to audit")
    elif unobserved:
        res["mtu_verdict"] = "INDETERMINATE -- MTU not collected on {} of {} hops".format(len(unobserved), total)
    elif res.get("mtu_bottleneck_hop") is not None:
        res["mtu_verdict"] = "bottleneck"
    else:
        res["mtu_verdict"] = "uniform"
    return res


def trace_fib_path(snap, src_ip: str, dst_ip: str, max_hops: int = 32, required_mtu=None) -> dict:
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

    MTU DIMENSION (§3.4 -- the EVPN-flagged 'single most engagement-relevant missing check': a 1500-byte underlay
    silently drops VXLAN and mimics random loss). Each traced hop's egress-interface MTU is read from
    snap['interfaces'][host][out_intf]; path_mtu = min OBSERVED MTU. Additive result keys:
      * mtu_min             -- the minimum observed MTU (int), or None if none was collected.
      * mtu_bottleneck_hop  -- {host, out_intf, mtu} of the lowest observed hop when it is below the maximum
                               observed (a genuine narrowing), else None.
      * mtu_verdict         -- 'uniform' (every hop observed AND equal) | 'bottleneck' (a hop is lower than the
                               source's) | 'INDETERMINATE -- MTU not collected on N of M hops' (a missing MTU is
                               ABSTENTION, NEVER a fabricated 1500-byte pass; also INDETERMINATE if the trace did
                               not resolve a reached path to audit).
      * mtu_unobserved_hops -- [{host, out_intf}] the traced hops whose MTU was not collected (the disclosed blind spots).
      * jumbo_blackhole     -- when `required_mtu` is given (e.g. 1550 for VXLAN, 9216 for a jumbo underlay), each
                               OBSERVED hop whose MTU < required as {host, out_intf, mtu, required}. A hop with no
                               collected MTU is disclosed in mtu_unobserved_hops, never asserted a blackhole.

    Returns {src, dst, hops:[{host, match, next_hop, out_intf, source}], status, computed, reached,
    mtu_min, mtu_bottleneck_hop, mtu_verdict, mtu_unobserved_hops, jumbo_blackhole}."""
    fibs, connected, l3_hosts = _build(snap)
    res = _trace(fibs, connected, l3_hosts, src_ip, dst_ip)
    return _annotate_mtu(res, snap, required_mtu)


def _is_l3_router(host, snap, routes) -> bool:
    """Does `host` make its OWN L3 forwarding decisions (a router) rather than hand off to an upstream default-
    gateway (an L2 access switch)? A no-match + no-default verdict is a DEFINITIVE drop only for a router; on an
    L2 access switch the L3 decision belongs to the (usually uncollected) upstream, so it is INDETERMINATE -- a
    lower bound, not a fabricated drop (audit-5 #0: the old blanket computed:unreachable fabricated newly_blocked
    cutover regressions across the L2 access tier). Positive L3 evidence, ANY one suffices:
      - a non-connected route (static / OSPF / BGP / EIGRP / ...) -- the device is actively running IP routing;
      - a connected /30 or /31 -- a point-to-point ROUTER transit link (an L2 access switch carries a mgmt /24, not a /30);
      - a routing-protocol adjacency in snap['routing_neighbors'][host];
      - a gateway SVI for the host in snap['l3_forwarding'].
    Absent ALL of them (only connected subnets wider than /30) the host is L2-or-ambiguous -> not a definitive drop."""
    for r in (routes if isinstance(routes, (list, tuple)) else []):
        if not isinstance(r, dict):
            continue
        if not _is_connected(r.get("source")):
            return True                                   # a learned/static route => the device routes IP
        try:
            if int(str(r.get("prefix", "")).split("/")[1]) >= 30:
                return True                               # a connected /30 or /31 => a router-to-router transit link
        except (IndexError, ValueError):
            pass
    rn = snap.get("routing_neighbors")
    if isinstance(rn, dict):
        peers = rn.get(host)
        if isinstance(peers, dict) and any(peers.get(p) for p in peers):
            return True                                   # OSPF/BGP/EIGRP adjacency => definitely L3
        if isinstance(peers, (list, tuple)) and peers:
            return True
    l3f = snap.get("l3_forwarding")
    if isinstance(l3f, list) and any(isinstance(x, dict) and x.get("switch") == host for x in l3f):
        return True                                       # owns a gateway SVI for a VLAN => routes for that subnet
    return False


def _build(snap):
    """(fibs, connected, l3_hosts) for a snapshot -- the per-host FIBs, the connected-subnet index, and the set of
    hosts that make their own L3 forwarding decisions (audit-5 #0). Built ONCE so a reachability matrix over many
    pairs (reachability_diff/reachability_delta) doesn't recompute them per trace."""
    snap = snap if isinstance(snap, dict) else {}
    routes_by_host = snap.get("routes") if isinstance(snap.get("routes"), dict) else {}
    fibs = {h: compute_fib(r) for h, r in routes_by_host.items()}
    connected = _connected_index(routes_by_host)
    l3_hosts = {h for h in routes_by_host if _is_l3_router(h, snap, routes_by_host.get(h))}
    return fibs, connected, l3_hosts


def _trace(fibs, connected, l3_hosts, src_ip, dst_ip):
    """Core trace over PREBUILT (fibs, connected, l3_hosts); coverage-honest semantics per trace_fib_path()."""

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
            if host in l3_hosts:                                       # a router: no match + no default -> definitive drop
                return _cache(host, ("computed:unreachable", False, []))
            # an L2 access switch / device with no L3 evidence forwards to an (uncollected) upstream default-gateway
            # -> its empty match is indeterminate, not a fabricated drop (audit-5 #0).
            return _cache(host, ("lower_bound:no_l3_routing", False, []))
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
    # audit-5 #0: a device's L2/L3 nature is INTRINSIC -- it does not become an L2 access switch when a cutover
    # removes one of its routes. Classify L3 from the UNION of both snapshots so a router that loses its default/
    # transit route is still treated as a router (its no-match => a definitive drop = newly_blocked), not demoted
    # to an indeterminate lower bound that would swallow the very regression --compare exists to catch.
    l3_union = of[2] | nf[2]
    rows, summary = [], {}
    for pair in (pairs or []):
        try:
            src, dst = pair[0], pair[1]
        except (TypeError, IndexError, KeyError):
            continue
        o = _trace(of[0], of[1], l3_union, src, dst)
        n = _trace(nf[0], nf[1], l3_union, src, dst)
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


def _l3_hops(trace: dict) -> list:
    """The ordered list of collected L3 hosts a trace traversed -- the forwarding-host path, used to compare a
    forward path against its reverse for RPF/return-path symmetry."""
    return [h.get("host", "") for h in (trace.get("hops") or [])]


def trace_bidirectional(snap, a_ip: str, b_ip: str, max_hops: int = 32, required_mtu=None) -> dict:
    """Return-path / RPF asymmetry (§3.4; orchestration :232 -- 'works one way, drops the other'). Pure
    COMPOSITION over two trace_fib_path calls -- forward a->b and reverse b->a -- plus a comparison; NO device
    contact. A one-directional trace cannot see the classic asymmetric-routing black hole where the forward flow
    is delivered but the return is dropped or takes a divergent path that a strict uRPF check would discard.

    COVERAGE-HONEST rpf_verdict:
      * 'symmetric'     -- BOTH directions reach AND traverse the SAME set of collected L3 forwarding hosts
                           (the shared-segment hop-sets align) -> no return-path asymmetry observed.
      * 'asymmetric'    -- forward reaches but the reverse is a DEFINITIVE drop (computed:unreachable), OR both
                           reach yet the traversed host-sets DIVERGE (a path split that a strict uRPF would fail).
                           The divergence is NAMED in `asymmetry`.
      * 'INDETERMINATE' -- either direction is inconclusive / a lower bound (computed=False). Asymmetry cannot be
                           PROVEN from an unprovable trace, so abstain -- never a fabricated 'asymmetric'.

    Returns {forward, reverse, symmetric:bool, asymmetry:[...], rpf_verdict}. `symmetric` is True ONLY for the
    proven-symmetric case (an INDETERMINATE or asymmetric result is False). Total on bad input."""
    fwd = trace_fib_path(snap, a_ip, b_ip, max_hops=max_hops, required_mtu=required_mtu)
    rev = trace_fib_path(snap, b_ip, a_ip, max_hops=max_hops, required_mtu=required_mtu)

    asymmetry: List[str] = []

    # If either direction could not be computed end-to-end, we cannot assert (or refute) asymmetry -> abstain.
    if not (fwd.get("computed") and rev.get("computed")):
        undone = []
        if not fwd.get("computed"):
            undone.append("forward {}".format(fwd.get("status")))
        if not rev.get("computed"):
            undone.append("reverse {}".format(rev.get("status")))
        asymmetry.append("indeterminate: " + "; ".join(undone))
        return {"forward": fwd, "reverse": rev, "symmetric": False,
                "asymmetry": asymmetry, "rpf_verdict": "INDETERMINATE"}

    fwd_reached, rev_reached = bool(fwd.get("reached")), bool(rev.get("reached"))

    # Forward delivered, reverse definitively drops (or vice versa) -> the textbook asymmetric black hole.
    if fwd_reached != rev_reached:
        winner = "forward" if fwd_reached else "reverse"
        loser = "reverse" if fwd_reached else "forward"
        loser_status = rev.get("status") if fwd_reached else fwd.get("status")
        asymmetry.append("{} reaches but {} is a definitive drop ({})".format(winner, loser, loser_status))
        return {"forward": fwd, "reverse": rev, "symmetric": False,
                "asymmetry": asymmetry, "rpf_verdict": "asymmetric"}

    # Both DEFINITIVELY unreachable in each direction -> no asymmetry (both blocked alike), not an RPF issue.
    if not fwd_reached:
        return {"forward": fwd, "reverse": rev, "symmetric": True,
                "asymmetry": [], "rpf_verdict": "symmetric"}

    # Both reach: compare the traversed L3 host-sets. A strict uRPF fails when the return path does not retrace the
    # forward one, so a divergence in the shared forwarding hosts is the asymmetry to flag.
    f_hosts, r_hosts = set(_l3_hops(fwd)), set(_l3_hops(rev))
    if f_hosts != r_hosts:
        only_fwd = sorted(f_hosts - r_hosts)
        only_rev = sorted(r_hosts - f_hosts)
        if only_fwd:
            asymmetry.append("forward-only L3 hop(s): " + ", ".join(only_fwd))
        if only_rev:
            asymmetry.append("reverse-only L3 hop(s): " + ", ".join(only_rev))
        return {"forward": fwd, "reverse": rev, "symmetric": False,
                "asymmetry": asymmetry, "rpf_verdict": "asymmetric"}

    return {"forward": fwd, "reverse": rev, "symmetric": True,
            "asymmetry": [], "rpf_verdict": "symmetric"}


def subnet_reps(snap, limit: int = 24) -> list:
    """A bounded, deterministic [(network_str, representative_host_ip)] -- the FIRST and LAST usable host of each
    collected CONNECTED subnet (so an upper- OR lower-half more-specific drop is sampled, not just .1), sorted by
    (version, network) and capped at `limit` DISTINCT subnets. Skips the default route and /32,/128 host routes.
    Used to auto-derive the inter-subnet flows the --compare reachability what-if checks. Pure/offline; total."""
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
            nets.setdefault(str(net), net)
    ordered = sorted(nets.values(), key=lambda n: (n.version, n))[:max(0, int(limit))]
    reps = []
    for net in ordered:
        if net.num_addresses > 2:                             # first/last USABLE host (avoid network & broadcast)
            ips = [net.network_address + 1, net.broadcast_address - 1]
        else:                                                 # /31, /127 -- both addresses are usable hosts
            ips = [net.network_address, net.broadcast_address]
        seen: set = set()
        for ip in ips:
            s = str(ip)
            if s not in seen:                                 # a degenerate subnet may have first == last
                seen.add(s)
                reps.append((str(net), s))
    return reps


def default_pairs(snap, limit: int = 24, max_pairs: int = 400) -> list:
    """Representative INTER-subnet flows to test: each subnet rep -> every rep in a DIFFERENT subnet (both
    directions), bounded (limit subnets, max_pairs total) and deterministic. Intra-subnet pairs are skipped
    (trivially connected). Pure."""
    reps = subnet_reps(snap, limit)                          # [(net, ip)] -- up to 2 reps per distinct subnet
    pairs = []
    for i, (net_i, a) in enumerate(reps):
        for j, (net_j, b) in enumerate(reps):
            if i != j and net_i != net_j:                    # inter-subnet only
                pairs.append((a, b))
                if len(pairs) >= max_pairs:
                    return pairs
    return pairs


def reachability_delta(old_snap, new_snap, pairs=None, limit: int = 24, max_pairs: int = 400) -> dict:
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
    subnets_total = len({net for net, _ip in all_reps})       # DISTINCT subnets (two reps each)
    subnets_tested = min(subnets_total, limit)
    if pairs is None:
        pairs = default_pairs(old_snap, limit, max_pairs)
    diff = reachability_diff(old_snap, new_snap, pairs)
    summary = diff["summary"]
    return {
        "summary": summary,
        "newly_blocked": [p for p in diff["pairs"] if p["verdict"] == "newly_blocked"],
        "newly_reachable": [p for p in diff["pairs"] if p["verdict"] == "newly_reachable"],
        # the inconclusive PAIRS themselves (not just the count): the pre-change certificate (precert.py)
        # must NAME each blind-spot flow with its lost-trail statuses, never just tally them. Additive key.
        "inconclusive_pairs": [p for p in diff["pairs"] if p["verdict"] == "inconclusive"],
        "preserved": summary.get("preserved", 0),
        "both_unreachable": summary.get("both_unreachable", 0),
        "inconclusive": summary.get("inconclusive", 0),
        "pairs_tested": len(diff["pairs"]),
        "subnets_tested": subnets_tested,
        "subnets_total": subnets_total,
        "assessed": len(diff["pairs"]) > 0,
        "capped": subnets_total > subnets_tested or len(pairs) >= max_pairs,   # DISCLOSED, never silent
    }
