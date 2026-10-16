"""Native longest-prefix-match RIB -> FIB resolver (universal-best roadmap W2-1).

The seam that upgrades reachability from L2 topology-BFS (a 'lower bound', analyze.py:2186) to a COMPUTED L3
forwarding resolution over the already-parsed per-host routes (snap['routes'] = {host: [{prefix, source,
next_hop, out_intf}]}, COLLECT_PARSE_V3_23_0.py:2324). Pure stdlib (ipaddress) -- fully OFFLINE, no new
dependency, no egress; an opt-in pybatfish power-mode is a deliberately SEPARATE future concern, never wired in
here. COVERAGE-HONEST by construction: a resolved lookup is computed from the collected routes; a destination
with NO matching route returns None ('no route observed' -- a lower bound, never a fabricated 'reachable').
"""
import ipaddress
import math
import re
from typing import List, Optional, Tuple


def _ip(s) -> Optional["ipaddress._BaseAddress"]:
    """Parse an IP that may carry a Cisco zone-id / scope suffix and return an ip_address, or None (never raises).
    Cisco prints an IPv6 link-local next-hop with the egress interface as a zone-id ('fe80::2%Gi0/1') -- and a '/'
    in the interface name ('Gi0/1','Te1/0/1','Eth1/1') makes ipaddress.ip_address RAISE on Python 3.9+, while a
    slash-free one ('%Vlan10','%Port-channel1') parses. So the zone is stripped UNCONDITIONALLY (the engine has no
    per-zone interface-IP data to use it anyway) -- otherwise a routed-over-link-local v6 fabric (the OSPFv3 /
    IS-IS / BGP-over-LLA norm) would silently lose reachability recall, intermittently by interface type."""
    if not isinstance(s, str):
        return None
    try:
        s.encode("utf-8")
        return ipaddress.ip_address(s.split("%", 1)[0].strip())
    except (ValueError, UnicodeEncodeError):
        return None


def _safe_token(value, *, max_length: int = 256) -> Tuple[str, bool]:
    """Return a bounded Unicode-scalar string without invoking arbitrary ``__str__`` implementations."""
    if value is None:
        return "", True
    if not isinstance(value, str):
        return "", False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return "", False
    stripped = value.strip()
    if len(stripped) > max_length or any(ord(char) < 32 for char in stripped):
        return "", False
    return stripped, True


def _admin_distance(source: str) -> int:
    """Cisco administrative distance for a route source (lower wins on an equal-length prefix). Used only as the
    tie-breaker between same-prefix routes; longest-prefix-match always dominates. Tolerant of BOTH the expanded
    names parse_ip_routes emits ('connected','static','ospf') AND the raw route-codes that survive on some entries
    ('s*' static+candidate-default, 'o*ia' ospf-inter-area, 'c','l','b','d','i','r') -- the '*' candidate-default
    marker and spaces are stripped first. Unknown / blank sources sort last (255). [verified vs real Meridian sources]"""
    source_token, valid = _safe_token(source)
    if not valid:
        return 255
    raw_source = source_token.replace("*", "").replace(" ", "")
    if raw_source == "L":
        return 0
    if raw_source == "l":
        return 115
    s = raw_source.lower()
    if not s:
        return 255
    # Connected / directly-attached: EXACT codes + the 'directly connected' / NX-OS 'direct' / 'attached' forms.
    # NOT a bare 'connect' substring -- that misread 'redistribute connected' / 'disconnected' / 'interconnect'
    # as directly-attached, fabricating a reached destination (adversarial-wave #4).
    if s in ("c", "local", "connected", "direct", "attached") or s.startswith(("connected", "directlyconnected", "direct", "local")):
        return 0
    # FHRP virtual IP: installed as a self-referential local host route 'X/32 via X, VlanN, [0/0], vrrp_engine|
    # hsrp|glbp' -- locally TERMINATED on the master (the packet is delivered, [0/0] + self-via prove it), so it
    # is a CONNECTED/local route (AD 0), not an unresolvable next-hop (audit-5 #12).
    if "vrrp" in s or "hsrp" in s or "glbp" in s:
        return 0
    if "static" in s or s in ("s", "su"):
        return 1
    if "bgp" in s or s == "b":
        return 20            # source-only fallback; an observed route AD distinguishes eBGP 20 from iBGP 200
    if "eigrp" in s or s == "d" or s.startswith("dex"):
        return 170 if "ex" in s else 90       # 'D EX' -> 'dex' (EIGRP external) = 170, internal 'D'/'eigrp' = 90
    if s == "odr":
        return 160                            # on-demand routing -- BEFORE the OSPF startswith('o') branch
    # OSPF family BEFORE isis: 'oia'/'on1'/'oe2' (and the bare inter/nssa/ext codes) start with the same letters
    if "ospf" in s or s.startswith("o") or s in ("ia", "n1", "n2", "e1", "e2"):
        return 110
    if "isis" in s or s == "i":
        return 115
    if "lisp" in s:
        return 115
    if "rip" in s or s == "r":
        return 120
    if "nhrp" in s:
        return 250
    return 255


def _observed_admin_distance(value) -> Optional[int]:
    """Strictly decode an observed non-negative administrative distance.

    Booleans, negative/fractional/non-finite numbers, containers, and malformed text are not observations.
    Integral floats and bounded ASCII integer strings are accepted for compatibility with persisted JSON.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer() or value < 0:
            return None
        return int(value)
    token, valid = _safe_token(value, max_length=32)
    if not valid or not re.fullmatch(r"\+?[0-9]+", token):
        return None
    try:
        return int(token)
    except ValueError:
        return None


def _is_connected(source: str) -> bool:
    """A directly-attached route (connected/local), in either the expanded-name or raw-code form."""
    return _admin_distance(source) == 0


def _is_discard(out_intf) -> bool:
    """A discard / blackhole egress -- a route to Null0 (also abbreviated Nu0) or an explicit 'discard'. Such a
    route is a FULLY-COLLECTED definitive drop (the router silently discards the packet), NOT a missing next hop:
    a cutover that leaves a drop route or summary-blackholes a more-specific must read as computed:unreachable,
    never as a coverage-honest lower bound. Match the actual Null/Nu token rather than every interface that
    happens to begin with those letters."""
    token, valid = _safe_token(out_intf)
    if not valid:
        return False
    s = token.lower().replace(" ", "")
    return bool(re.fullmatch(r"(?:null|nu)\d+(?:\.\d+)?", s)) or s == "discard"


# A FIB is a list of (network, admin_distance, route_dict), sorted longest-prefix-first then lowest-AD.
Fib = List[Tuple["ipaddress._BaseNetwork", int, dict]]


class _FibTable(list):
    """List-compatible FIB plus fixed, non-echoing route-selection gaps."""

    def __init__(self):
        super().__init__()
        self.malformed_admin_distance_networks = []
        self.unknown_source_networks = []


def compute_fib(routes) -> Fib:
    """Build a longest-prefix-match FIB from a host's parsed route list. Tolerant: a non-dict / blank-prefix /
    unparseable-prefix or malformed observed-AD entry is skipped (never raises); None / a non-list scalar -> [].
    A valid observed ``admin_distance`` wins over the source-family default; source fallback is used only when
    that field is absent. Consumed by fib_lookup()."""
    entries = _FibTable()
    if not isinstance(routes, (list, tuple)):
        return entries                       # total: a host mapped to a scalar/None yields an empty FIB, not a raise
    for r in routes:
        if not isinstance(r, dict):
            continue
        prefix, prefix_valid = _safe_token(r.get("prefix"))
        if not prefix_valid or not prefix:
            continue
        try:
            net = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        if "admin_distance" in r:
            admin_distance = _observed_admin_distance(r.get("admin_distance"))
            if admin_distance is None:
                # The prefix itself is valid and retained by the scoped projection, but its observed preference is
                # malformed. Silently deleting it can invert LPM in either direction, so preserve a destination-
                # match taint rather than selecting a sibling/covering route as if this row did not exist.
                entries.malformed_admin_distance_networks.append(net)
                continue
        else:
            source, source_valid = _safe_token(r.get("source"))
            admin_distance = _admin_distance(source)
            if not source_valid or not source or admin_distance == 255:
                entries.unknown_source_networks.append(net)
                continue
        entries.append((net, admin_distance, dict(r)))
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
    selection_gaps = [
        (network, reason)
        for networks, reason in (
            (getattr(fib, "malformed_admin_distance_networks", []), "malformed_admin_distance"),
            (getattr(fib, "unknown_source_networks", []), "unknown_route_source"),
        )
        for network in networks
        if ip.version == network.version and ip in network
    ]
    if selection_gaps:
        network, reason = sorted(
            selection_gaps, key=lambda item: (-item[0].prefixlen, item[1]),
        )[0]
        return [{
            "prefix": str(network), "match": str(network), "computed": False,
            "selection_error": reason, "next_hop": "", "out_intf": "", "source": "",
        }]
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


class _ConnectedIndex(dict):
    """Connected-prefix membership plus positively observed exact interface/local addresses."""

    def __init__(self, *args, exact_by_host=None, invalid_host_key_count=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.exact_by_host = exact_by_host or {}
        self.invalid_host_key_count = invalid_host_key_count


def _connected_index(routes_by_host, interfaces=None) -> dict:
    """{host: [connected networks]} -- which subnets each host is directly attached to (its connected/local
    routes), used to find which collected host a next-hop IP lives behind."""
    idx: dict = {}
    exact: dict = {}
    for host, routes in (routes_by_host or {}).items():
        nets = []
        owned = set()
        for r in (routes if isinstance(routes, (list, tuple)) else []):
            if isinstance(r, dict) and _is_connected(r.get("source")):
                try:
                    prefix, prefix_valid = _safe_token(r.get("prefix"))
                    if not prefix_valid:
                        continue
                    network = ipaddress.ip_network(prefix, strict=False)
                    nets.append(network)
                    # A local/FHRP host route is positive ownership evidence. A connected subnet alone is not:
                    # every router on a shared segment contains the next-hop address, but only one owns it.
                    source, source_valid = _safe_token(r.get("source"))
                    if not source_valid:
                        continue
                    source = source.lower().replace("*", "")
                    local_source = source in {"l", "local"} or source.startswith("local")
                    fhrp_source = any(token in source for token in ("hsrp", "vrrp", "glbp"))
                    route_ip = network.network_address
                    next_hop = _ip(r.get("next_hop"))
                    if network.prefixlen == network.max_prefixlen and (
                            local_source or (fhrp_source and next_hop == route_ip)):
                        owned.add(network.network_address)
                except ValueError:
                    pass
        idx[host] = nets
        exact[host] = owned
    if isinstance(interfaces, dict):
        for host, ports in interfaces.items():
            if not isinstance(ports, dict):
                continue
            owned = exact.setdefault(host, set())
            for record in ports.values():
                values = [_iface_field(record, "svi_ip")]
                all_values = _iface_field(record, "svi_ips")
                if isinstance(all_values, str):
                    values.extend(all_values.split(";"))
                elif isinstance(all_values, (list, tuple)):
                    values.extend(all_values)
                for raw in values:
                    raw_token, raw_valid = _safe_token(raw)
                    if not raw_valid:
                        continue
                    parts = raw_token.split()
                    if not parts:
                        continue
                    token = parts[0].split("/", 1)[0]
                    parsed = _ip(token)
                    if parsed is not None:
                        owned.add(parsed)
    return _ConnectedIndex(idx, exact_by_host=exact)


def _hosts_owning_ip(connected_idx: dict, ip_str: str, exclude: str = None,
                     exact: bool = False) -> list:
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
    if exact:
        exact_by_host = getattr(connected_idx, "exact_by_host", {})
        for host, addresses in exact_by_host.items():
            if host != exclude and ip in addresses:
                hosts.add(host)
        return sorted(hosts)
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
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        val = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            return None
        val = int(raw)
    elif isinstance(raw, str):
        match = re.fullmatch(r"(\d+)(?:\s+bytes?)?", raw.strip(), flags=re.IGNORECASE)
        if not match:
            return None
        val = int(match.group(1))
    else:
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
                if isinstance(p, str) and normalize_ifname(p) == want:
                    rec = r
                    break
    if rec is None:
        return None
    ip_mtu_value = _iface_field(rec, "ip_mtu")
    if ip_mtu_value not in (None, ""):
        # A dedicated IPv4 MTU field is the strongest available layer binding, including older snapshots that
        # predate ``mtu_semantics``. It must outrank a stale/contradictory generic copy.
        return _parse_mtu(ip_mtu_value)
    semantics, semantics_valid = _safe_token(_iface_field(rec, "mtu_semantics"))
    if not semantics_valid or semantics != "effective_ipv4_mtu":
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
        if not isinstance(hop, dict):
            unobserved.append({"host": "", "out_intf": "", "reason": "malformed_hop_evidence"})
            continue
        host, host_valid = _safe_token(hop.get("host"))
        out_intf, out_intf_valid = _safe_token(hop.get("out_intf"))
        if not host_valid or not out_intf_valid:
            unobserved.append({"host": host, "out_intf": out_intf,
                               "reason": "malformed_hop_evidence"})
            continue
        if not out_intf and not _is_discard(hop.get("out_intf")):
            # A reached L3 hop necessarily egresses somewhere. A blank route-interface field is therefore an
            # explicit MTU denominator gap, not evidence that this hop has no MTU to assess.
            unobserved.append({"host": host, "out_intf": "",
                               "reason": "egress_interface_not_observed"})
            continue
        mtu = _hop_mtu(interfaces, host, out_intf)
        if mtu is None:
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
    blind = "MTU not collected on {} of {} hops".format(len(unobserved), total)
    # Verdict precedence (coverage-honest):
    #  - no reached path to audit, or nothing observed at all           -> INDETERMINATE (abstain)
    #  - a PROVEN violation of `required_mtu` on an observed hop        -> below_required (see note)
    #  - any hop's MTU was not collected                                -> INDETERMINATE, disclosing N of M
    #  - a genuine narrowing among the observed hops                    -> bottleneck
    #  - every hop observed AND equal                                   -> uniform
    #
    # below_required comes FIRST because it is the only branch grounded in the caller's requirement rather
    # than in the spread of what happened to be observed: the bottleneck branch fires on mtu_min < mtu_max,
    # which is false exactly when EVERY hop is uniformly too narrow -- the normal shape of the 1500-byte
    # underlay that silently drops VXLAN (this function's docstring calls it "the single most
    # engagement-relevant missing check"), which used to report the clean one-word `uniform`. It outranks
    # the unobserved-hop abstention because a hop measured below the requirement is PROVEN, not inferred;
    # the remaining blind spots are appended to the same string, never dropped.
    if not res.get("reached") or not observed:
        res["mtu_verdict"] = ("INDETERMINATE -- " + blind if unobserved
                              else "INDETERMINATE -- no reached path to audit")
    elif jumbo:
        res["mtu_verdict"] = "below_required -- {} of {} observed hop(s) under the required {} (min {})".format(
            len(jumbo), len(observed), req, res["mtu_min"]) + ("; " + blind if unobserved else "")
    elif unobserved:
        res["mtu_verdict"] = "INDETERMINATE -- " + blind
    elif res.get("mtu_bottleneck_hop") is not None:
        res["mtu_verdict"] = "bottleneck"
    else:
        res["mtu_verdict"] = "uniform"
    return res


def trace_fib_path(snap, src_ip: str, dst_ip: str, max_hops: int = 32, required_mtu=None,
                   disclose: bool = False) -> dict:
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
                               source's) | 'below_required -- N of M observed hop(s) under the required X' (a
                               PROVEN violation of `required_mtu`, including the uniformly-too-narrow path that
                               has no internal spread at all) | 'INDETERMINATE -- MTU not collected on N of M
                               hops' (a missing MTU is ABSTENTION, NEVER a fabricated 1500-byte pass; also
                               INDETERMINATE if the trace did not resolve a reached path to audit).
      * mtu_unobserved_hops -- [{host, out_intf}] the traced hops whose MTU was not collected (the disclosed blind spots).
      * jumbo_blackhole     -- when `required_mtu` is given (e.g. 1550 for VXLAN, 9216 for a jumbo underlay), each
                               OBSERVED hop whose MTU < required as {host, out_intf, mtu, required}. A hop with no
                               collected MTU is disclosed in mtu_unobserved_hops, never asserted a blackhole.

    EVIDENCE DISCLOSURE (`disclose=True`, additive; default off to keep the frozen result shape the
    executed explorer-parity gate compares -- see _trace):
      * drop_evidence       -- on a computed:unreachable, 'observed_discard' (a Null0/discard egress was
                               SEEN) vs 'no_route_observed' (derived from an EMPTY lookup). The latter is
                               NOT proof the device drops the packet: snap['routes'] is scoped by
                               build.scope_routes to prefixes covering in-scope SVI subnets + the default,
                               so a scoped-out route is indistinguishable from an absent one here.
      * ecmp_dropping_legs  -- equal-cost legs PROVEN to blackhole while a sibling leg carries the flow
                               (reached is a genuine existential over the leg set, but ~50% loss must not
                               be swallowed by it).

    Returns {src, dst, hops:[{host, match, next_hop, out_intf, source}], status, computed, reached,
    mtu_min, mtu_bottleneck_hop, mtu_verdict, mtu_unobserved_hops, jumbo_blackhole}."""
    fibs, connected, l3_hosts = _build(snap)
    res = _trace(fibs, connected, l3_hosts, src_ip, dst_ip, disclose=disclose, max_hops=max_hops)
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
    raw_routes = snap.get("routes") if isinstance(snap.get("routes"), dict) else {}
    raw_interfaces = snap.get("interfaces") if isinstance(snap.get("interfaces"), dict) else {}

    def valid_host(host):
        return isinstance(host, str) and bool(_safe_token(host)[0])

    invalid_hosts = sum(1 for host in set(raw_routes) | set(raw_interfaces) if not valid_host(host))
    routes_by_host = {host: rows for host, rows in raw_routes.items() if valid_host(host)}
    interfaces = {host: rows for host, rows in raw_interfaces.items() if valid_host(host)}
    fibs = {h: compute_fib(r) for h, r in routes_by_host.items()}
    connected = _connected_index(routes_by_host, interfaces)
    connected.invalid_host_key_count = invalid_hosts
    l3_hosts = {h for h in routes_by_host if _is_l3_router(h, snap, routes_by_host.get(h))}
    return fibs, connected, l3_hosts


def _resolver(fibs, connected, l3_hosts, dst_ip):
    """The memoized per-host forwarding resolution toward ONE dst -> (explore, explore_set, leg_outcome).

    Each returns the 4-tuple ``(status, reached, hops_from_here, evidence)``. `evidence` carries the two
    facts the status alone cannot express, and both are findings the review named:

      * ``drop_evidence`` -- WHY a `computed:unreachable` was returned. 'observed_discard' is a POSITIVE
        observation (a Null0/discard egress: the router was seen to drop the packet). 'no_route_observed'
        is derived from ABSENCE -- and `snap['routes']` is NOT the device's RIB: `build.scope_routes` keeps
        only routes whose prefix covers an in-scope SVI subnet, plus the default. So an empty lookup is
        equally consistent with "this router drops it" and "that route was scoped out of the snapshot",
        and callers that must not confuse the two (reachability_diff) can now tell them apart.
      * ``ecmp_dropping_legs`` -- equal-cost legs PROVEN to drop while a sibling leg does not. Forwarding
        over an ECMP set is a genuine existential (a flow can hash onto any leg, so ANY leg reaching means
        the dst IS reachable), but a leg that blackholes is ~50% packet loss on the very flows this model
        certifies 'reached'; it must be disclosed rather than swallowed by the existential.

    Shared by _trace (whole path) and ecmp_consistency (per leg) so the two surfaces cannot drift apart."""
    memo, computing = {}, set()

    def _rank(status):                                      # reach > any lower bound > a definitive drop
        return 2 if status.startswith("computed:reached") else (1 if status.startswith("lower_bound") else 0)

    def _cache(key, res):
        if not (res[0].endswith(":loop") or res[0].endswith(":max_hops")):
            memo[key] = res                                 # cache only path-INDEPENDENT verdicts (not loop/cutoff)
        return res

    def explore_set(hosts, amb_status, remaining=None):
        """Resolve forwarding from a SET of candidate hosts for ONE unknown-but-fixed hop -- a next-hop IP or the
        source IP shared by >1 collected host (a transit/multi-access subnet, where the exact owner can't be pinned
        without interface-IP data). Definitive ONLY when every candidate agrees: all reach -> reached; all
        definitively drop -> unreachable; any disagreement or lower bound -> the ambiguous lower bound. This keeps
        recall (the common case: every possible forwarder routes the dst alike) without guessing which is real."""
        if len(hosts) == 1:
            return explore(hosts[0], remaining)
        results = [explore(h, remaining) for h in hosts]
        if all(r[1] for r in results):
            evidence = dict(results[0][3])
            candidate_sets = []
            for result in results:
                candidate_sets.extend(list(result[3].get("ambiguous_candidate_sets") or []))
            candidate_sets.append({"kind": amb_status.split(":")[-1], "candidate_hosts": sorted(hosts)})
            evidence["ambiguous_candidate_sets"] = sorted(
                {(
                    str(row.get("kind") or "ambiguous"),
                    tuple(sorted(str(host) for host in (row.get("candidate_hosts") or []))),
                ) for row in candidate_sets},
                key=lambda item: (item[0], item[1]),
            )
            evidence["ambiguous_candidate_sets"] = [
                {"kind": kind, "candidate_hosts": list(candidates)} for kind, candidates
                in evidence["ambiguous_candidate_sets"]
            ]
            return ("computed:reached", True, results[0][2], evidence)   # every possible forwarder reaches
        if all(r[0] == "computed:unreachable" for r in results):
            # All candidates fail, but the evidence is only as strong as the weakest candidate. A scoped
            # no-route absence at ANY possible owner prevents the ambiguous set from being presented as a
            # positively observed discard merely because the first candidate happened to own a Null0 route.
            kinds = {r[3].get("drop_evidence", "") for r in results}
            evidence = {
                "drop_evidence": "no_route_observed" if "no_route_observed" in kinds
                else ("observed_discard" if kinds == {"observed_discard"} else "")
            }
            return ("computed:unreachable", False, results[0][2], evidence)
        return (amb_status, False, [], {})                            # disagreement / a lower bound -> ambiguous

    def leg_outcome(host, m, remaining=None):
        """ONE installed (equal-cost) leg from `host` -> (hop_record, outcome_4tuple): what a flow that hashes
        onto THIS leg does. A connected match is delivery; a Null0/discard egress is an observed drop; anything
        else defers to the next-hop owner(s)."""
        selection_error = m.get("selection_error")
        if selection_error in {"malformed_admin_distance", "unknown_route_source"}:
            match, _match_valid = _safe_token(m.get("match"))
            invalid_field = "admin_distance" if selection_error == "malformed_admin_distance" else "source"
            hop = {"host": host, "match": match, "next_hop": "", "out_intf": "", "source": "",
                   "invalid_route_fields": [invalid_field]}
            return hop, ("lower_bound:malformed_route_evidence", False, [hop], {})
        next_hop, next_hop_valid = _safe_token(m.get("next_hop"))
        out_intf, out_intf_valid = _safe_token(m.get("out_intf"))
        source, source_valid = _safe_token(m.get("source"))
        hop = {"host": host, "match": m.get("match", ""), "next_hop": next_hop,
               "out_intf": out_intf, "source": source}
        invalid_fields = [name for name, valid in (
            ("next_hop", next_hop_valid), ("out_intf", out_intf_valid), ("source", source_valid),
        ) if not valid]
        if invalid_fields:
            hop["invalid_route_fields"] = invalid_fields
            return hop, ("lower_bound:malformed_route_evidence", False, [hop], {})
        if _is_connected(m.get("source")):
            return hop, ("computed:reached", True, [hop], {})         # dst is directly attached on this leg
        if _is_discard(m.get("out_intf")):                            # Null0/discard egress -> definitive drop
            return hop, ("computed:unreachable", False, [hop], {"drop_evidence": "observed_discard"})
        nh = next_hop
        nh_ip = _ip(nh)
        directly_attached = bool(nh_ip is not None and any(
            nh_ip.version == network.version and nh_ip in network
            for network in connected.get(host, [])
        ))
        if nh and not directly_attached:
            # Recursive resolution must walk the current router's FIB to an immediate adjacency before another
            # host can be selected. Jumping directly to a loopback owner's box skips transit forwarding and ACLs.
            return hop, ("lower_bound:recursive_next_hop_not_modeled", False, [hop], {})
        inferred_nxts = _hosts_owning_ip(connected, nh, exclude=host) if nh else []
        nxts = _hosts_owning_ip(connected, nh, exclude=host, exact=True) if nh else []
        if not nxts:
            status = ("lower_bound:next_hop_owner_not_observed" if inferred_nxts
                      else "lower_bound:next_hop_not_collected")
            return hop, (status, False, [hop], {
                "inferred_next_hop_candidates": inferred_nxts,
            } if inferred_nxts else {})
        if remaining is not None and remaining <= 1:
            return hop, ("lower_bound:max_hops", False, [hop], {})
        sub = explore_set(
            nxts, "lower_bound:ambiguous_next_hop",
            None if remaining is None else remaining - 1,
        )
        return hop, (sub[0], sub[1], [hop] + sub[2], dict(sub[3]))

    def explore(host, remaining=None):
        """(status, reached, hops_from_host, evidence) for the dst from `host`, exploring every equal-cost (ECMP)
        leg -- a router load-balances so the flow can take any leg: reach if ANY leg reaches. MEMOIZED per host
        (the verdict is intrinsic to the host, not to how it was reached), so a shared-subnet fan-out is linear,
        not exponential; an in-progress host is a forwarding loop (returned but never cached)."""
        if remaining is not None and remaining <= 0:
            return ("lower_bound:max_hops", False, [], {})
        key = (host, remaining)
        if key in memo:
            return memo[key]
        if host in computing:
            return ("lower_bound:loop", False, [], {})     # cycle back-edge -- path-dependent, do not cache
        legs = fib_lookup_all(fibs.get(host, []), dst_ip)
        if not legs:
            if host in l3_hosts:                                       # a router: no match + no default -> drop
                # DEFINITIVE per the routes we hold -- but derived from ABSENCE, and snap['routes'] is a SCOPED
                # subset of the RIB (see this function's docstring), so the evidence kind is disclosed.
                return _cache(key, ("computed:unreachable", False, [], {"drop_evidence": "no_route_observed"}))
            # an L2 access switch / device with no L3 evidence forwards to an (uncollected) upstream default-gateway
            # -> its empty match is indeterminate, not a fabricated drop (audit-5 #0).
            return _cache(key, ("lower_bound:no_l3_routing", False, [], {}))
        computing.add(host)
        best, outcomes = None, []
        for m in legs:
            hop, cand = leg_outcome(host, m, remaining)
            outcomes.append((hop, cand))
            if best is None:
                best = cand
            elif not best[1] and (cand[1] or _rank(cand[0]) > _rank(best[0])):
                # the FIRST reaching leg wins (ECMP existential) and is never displaced; among non-reaching
                # legs the most informative wins (a lower bound beats a definitive drop). Unlike the previous
                # version this does NOT break out of the loop: the siblings of a reaching leg are exactly the
                # legs that may be blackholing, and they cannot be disclosed without resolving them.
                best = cand
        computing.discard(host)
        ev = dict(best[3])
        drops = [(h, c) for h, c in outcomes if c[0] == "computed:unreachable"]
        if drops and len(drops) < len(outcomes):            # legs DISAGREE: some proven to drop, some not
            ev["ecmp_dropping_legs"] = [
                {"host": host, "match": h["match"], "next_hop": h["next_hop"], "out_intf": h["out_intf"],
                 "leg_status": c[0], "drop_evidence": c[3].get("drop_evidence", ""),
                 "resolved_hops": list(c[2])} for h, c in drops
            ] + list(ev.get("ecmp_dropping_legs") or [])
        elif drops and best[0] == "computed:unreachable":
            # EVERY leg drops: the host-level verdict is only as positively-evidenced as its weakest leg --
            # one absence-derived leg means the whole drop could be a scoping artifact.
            kinds = {c[3].get("drop_evidence", "") for _h, c in drops}
            ev["drop_evidence"] = ("no_route_observed" if "no_route_observed" in kinds
                                   else ("observed_discard" if "observed_discard" in kinds
                                         else ev.get("drop_evidence", "")))
        return _cache(key, (best[0], best[1], best[2], ev))

    return explore, explore_set, leg_outcome


def _trace(fibs, connected, l3_hosts, src_ip, dst_ip, disclose=False, max_hops=32):
    """Core trace over PREBUILT (fibs, connected, l3_hosts); coverage-honest semantics per trace_fib_path().

    `disclose` adds evidence keys (`drop_evidence`, `ecmp_dropping_legs`, `ambiguous_candidate_sets`; see
    _resolver) to the
    result. It is OFF by default because trace_fib_path's result dict is compared KEY-FOR-KEY against the
    explorer's embedded JS port by the EXECUTED parity gate (tests/test_explorer_js_parity.py), which
    projects out only the named MTU-enrichment keys -- an unconditional new key there would report the two
    surfaces as diverged. reachability_diff, the cutover surface these disclosures exist for, always asks
    for them."""

    safe_src, src_valid = _safe_token(src_ip)
    safe_dst, dst_valid = _safe_token(dst_ip)

    def _result(hops, status, reached, ev=None):
        r = {"src": safe_src, "dst": safe_dst, "hops": hops, "status": status,
             "computed": status.startswith("computed"), "reached": reached}
        if disclose:
            ev = ev or {}
            r["ecmp_dropping_legs"] = list(ev.get("ecmp_dropping_legs") or [])
            r["ambiguous_candidate_sets"] = list(ev.get("ambiguous_candidate_sets") or [])
            r["drop_evidence"] = (str(ev.get("drop_evidence") or "")
                                  if status == "computed:unreachable" else "")
        return r

    sip, dip = _ip(safe_src), _ip(safe_dst)
    if not src_valid or not dst_valid or sip is None or dip is None:
        return _result([], "lower_bound:bad_address", False)
    if sip.version != dip.version:                          # a v4<->v6 flow is impossible -- never certify reached
        return _result([], "lower_bound:cross_family", False)
    if getattr(connected, "invalid_host_key_count", 0):
        return _result([], "lower_bound:malformed_host_identity", False)
    if not isinstance(max_hops, int) or isinstance(max_hops, bool) or max_hops < 0:
        return _result([], "lower_bound:max_hops", False)

    src_hosts = _hosts_owning_ip(connected, safe_src)
    if not src_hosts:
        return _result([], "lower_bound:src_host_not_found", False)

    _explore, _explore_set, _leg = _resolver(fibs, connected, l3_hosts, dst_ip)
    try:
        status, reached, hops, ev = _explore_set(
            src_hosts, "lower_bound:ambiguous_src", max_hops,
        )
    except RecursionError:                                  # pathological deep chain -- stay total
        return _result([], "lower_bound:max_hops", False)
    return _result(hops, status, reached, ev)


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

    Two evidence disclosures ride on every row -- they are what makes these verdicts falsifiable:
      * old_/new_drop_evidence -- 'observed_discard' (a Null0/discard egress was SEEN to drop it) vs
        'no_route_observed' (an EMPTY lookup). When BOTH sides are 'no_route_observed' the pair is
        'inconclusive', NOT 'both_unreachable': neither snapshot ever observed a route for that flow and
        snap['routes'] is a SCOPED subset of the RIB (build.scope_routes keeps only prefixes covering an
        in-scope SVI subnet, plus the default), so counting it as a definitive NON-regression silently
        absorbs a flow the change really broke.
      * ecmp_dropping_legs (the NEW / post-change side) -- equal-cost legs proven to blackhole while a
        sibling still carries the flow. A cutover that blackholes one of two legs is ~50% packet loss and
        used to read 'preserved' with nothing else said; those pairs are also collected into the returned
        `ecmp_partial_drop` list so a caller cannot miss them.

    Returns {pairs:[{src,dst,old_status,new_status,verdict,old_drop_evidence,new_drop_evidence,
    ecmp_dropping_legs}], summary:{verdict:count}, ecmp_partial_drop:[...]}. Pure/offline; total."""
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
        o = _trace(of[0], of[1], l3_union, src, dst, disclose=True)
        n = _trace(nf[0], nf[1], l3_union, src, dst, disclose=True)
        if not (o["computed"] and n["computed"]):
            v = "inconclusive"
        elif o["reached"] and n["reached"]:
            v = "preserved"
        elif o["reached"] and not n["reached"]:
            v = "newly_blocked"
        elif not o["reached"] and n["reached"]:
            v = "newly_reachable"
        elif o["drop_evidence"] == "no_route_observed" and n["drop_evidence"] == "no_route_observed":
            # NEITHER side ever observed a route for this flow. That is not a proven "blocked before and
            # after" (a non-regression) -- with a scoped route set it is equally the shape of a flow whose
            # carrying route is simply not in either snapshot. Abstain rather than certify.
            v = "inconclusive"
        else:
            v = "both_unreachable"
        rows.append({"src": o["src"], "dst": o["dst"], "old_status": o["status"], "new_status": n["status"], "verdict": v,
                     "old_drop_evidence": o["drop_evidence"], "new_drop_evidence": n["drop_evidence"],
                     "ecmp_dropping_legs": n["ecmp_dropping_legs"]})
        summary[v] = summary.get(v, 0) + 1
    return {"pairs": rows, "summary": summary,
            "ecmp_partial_drop": [r for r in rows if r["ecmp_dropping_legs"]]}


def _l3_hops(trace: dict) -> list:
    """The ordered list of collected L3 hosts a trace traversed -- the forwarding-host path, used to compare a
    forward path against its reverse for RPF/return-path symmetry."""
    return [h.get("host", "") for h in (trace.get("hops") or [])]


def trace_bidirectional(snap, a_ip: str, b_ip: str, max_hops: int = 32, required_mtu=None,
                        disclose: bool = False) -> dict:
    """Return-path / RPF asymmetry (§3.4; orchestration :232 -- 'works one way, drops the other'). Pure
    COMPOSITION over two trace_fib_path calls -- forward a->b and reverse b->a -- plus a comparison; NO device
    contact. A one-directional trace cannot see the classic asymmetric-routing black hole where the forward flow
    is delivered but the return is dropped or takes a divergent path that a strict uRPF check would discard.

    Backward-compatible default mode retains the historical host-set path-symmetry heuristic. Assurance callers
    use ``disclose=True``: that mode names the observed ``path_relation`` but keeps ``rpf_verdict``
    INDETERMINATE. A host set cannot prove strict-uRPF behavior because that requires per-hop packet-ingress and
    reverse-route interface correlation, which this snapshot does not currently own. In particular, equal host
    sets over different parallel links are not a symmetric-uRPF proof.

    Returns {forward, reverse, symmetric:bool, asymmetry:[...], rpf_verdict}. In disclosure mode ``symmetric``
    remains False until strict-uRPF evidence exists, and the additive ``path_relation``/``rpf_scope`` fields carry
    the bounded observation. ``disclose=True`` also passes through the underlying trace's evidence-kind fields
    (observed discard vs scoped no-route absence, and ECMP dropping legs). The default remains False so existing
    result-shape contracts stay byte-identical. Total on bad input."""
    fwd = trace_fib_path(snap, a_ip, b_ip, max_hops=max_hops, required_mtu=required_mtu,
                         disclose=disclose)
    rev = trace_fib_path(snap, b_ip, a_ip, max_hops=max_hops, required_mtu=required_mtu,
                         disclose=disclose)

    asymmetry: List[str] = []

    def result(symmetric: bool, verdict: str, relation: str = "indeterminate") -> dict:
        out = {"forward": fwd, "reverse": rev, "symmetric": symmetric,
               "asymmetry": asymmetry, "rpf_verdict": verdict}
        if disclose:
            out["path_relation"] = relation
            out["rpf_scope"] = "strict_u_rpf_not_assessed"
        return out

    # If either direction could not be computed end-to-end, we cannot assert (or refute) asymmetry -> abstain.
    if not (fwd.get("computed") and rev.get("computed")):
        undone = []
        if not fwd.get("computed"):
            undone.append("forward {}".format(fwd.get("status")))
        if not rev.get("computed"):
            undone.append("reverse {}".format(rev.get("status")))
        asymmetry.append("indeterminate: " + "; ".join(undone))
        return result(False, "INDETERMINATE", "incomplete")

    # In disclosure mode, a computed-unreachable derived only from a missing match in the scoped route
    # projection is not positive evidence of a device drop.  Do not let that absence become a definitive
    # RPF/asymmetry statement.  The default mode retains its historical shape and interpretation.
    if disclose:
        ambiguous_directions = [name for name, trace in (("forward", fwd), ("reverse", rev))
                                if trace.get("ambiguous_candidate_sets")]
        if ambiguous_directions:
            asymmetry.append(
                "indeterminate: representative paths cannot decide symmetry across ambiguous forwarding "
                "owners in " + ", ".join(ambiguous_directions)
            )
            return result(False, "INDETERMINATE", "ambiguous_forwarding_owners")
        absence_directions = [name for name, trace in (("forward", fwd), ("reverse", rev))
                              if not trace.get("reached") and trace.get("drop_evidence") != "observed_discard"]
        if absence_directions:
            asymmetry.append(
                "indeterminate: scoped no-route absence is not positive drop evidence in "
                + ", ".join(absence_directions)
            )
            return result(False, "INDETERMINATE", "scoped_absence")

    fwd_reached, rev_reached = bool(fwd.get("reached")), bool(rev.get("reached"))

    # Forward delivered, reverse definitively drops (or vice versa) -> the textbook asymmetric black hole.
    if fwd_reached != rev_reached:
        winner = "forward" if fwd_reached else "reverse"
        loser = "reverse" if fwd_reached else "forward"
        loser_status = rev.get("status") if fwd_reached else fwd.get("status")
        asymmetry.append("{} reaches but {} is a definitive drop ({})".format(winner, loser, loser_status))
        if disclose:
            asymmetry.append(
                "strict uRPF is not assessed without packet-ingress and reverse-interface evidence"
            )
            return result(False, "INDETERMINATE", "one_way_observed")
        return result(False, "asymmetric")

    # Both DEFINITIVELY unreachable in each direction -> no asymmetry (both blocked alike), not an RPF issue.
    if not fwd_reached:
        if disclose:
            asymmetry.append("indeterminate: neither direction delivered a path to compare")
            return result(False, "INDETERMINATE", "both_blocked")
        return result(True, "symmetric")

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
        if disclose:
            asymmetry.append(
                "host-set divergence is a path observation, not strict-uRPF interface proof"
            )
            return result(False, "INDETERMINATE", "host_set_divergent")
        return result(False, "asymmetric")

    if disclose:
        asymmetry.append(
            "aligned forwarding-host sets do not prove reverse-interface symmetry on parallel links"
        )
        return result(False, "INDETERMINATE", "host_set_aligned")
    return result(True, "symmetric")


def _iface_acl(interfaces: dict, host: str, out_intf: str):
    """(acl_in, acl_out) applied to a hop's egress interface, or (None, None) if the interface/fields were not
    collected. A collected-but-empty ACL field is '' (no ACL); a NOT-collected interface is None (a blind spot)."""
    if not out_intf or not isinstance(interfaces, dict):
        return (None, None)
    ports = interfaces.get(host)
    if not isinstance(ports, dict):
        return (None, None)
    rec = ports.get(out_intf)
    if rec is None:
        try:
            from .textutils import normalize_ifname
        except Exception:                    # pragma: no cover
            normalize_ifname = None
        if normalize_ifname is not None:
            want = normalize_ifname(out_intf)
            for p, r in ports.items():
                if isinstance(p, str) and normalize_ifname(p) == want:
                    rec = r
                    break
    if rec is None:
        return (None, None)
    ai, ao = _iface_field(rec, "acl_in"), _iface_field(rec, "acl_out")
    if (ai is not None and not isinstance(ai, str)) or (ao is not None and not isinstance(ao, str)):
        return (None, None)
    return (ai.strip() if isinstance(ai, str) else "", ao.strip() if isinstance(ao, str) else "")


def ecmp_consistency(snap, src_ip: str, dst_ip: str) -> dict:
    """ECMP multipath-consistency (Batfish multipathConsistency analog; §3.4 optional). For the equal-cost leg set
    a router installs toward `dst_ip`, flag when the legs would NOT be treated ALIKE -- a flow that hashes onto one
    leg then behaves differently from a sibling, mimicking intermittent loss. THREE divergence classes are checked
    over the leg set at the FIRST L3 host on the path:
      * mtu  -- the legs' egress MTUs differ (a jumbo flow blackholes only on the narrow leg);
      * acl  -- the legs carry different ingress/egress ACL treatment (one leg filters, another passes);
      * forwarding -- a leg is PROVEN not to deliver the flow (a Null0/discard egress, or a downstream RIB that
        definitively drops it) while a sibling leg is not. Comparing only MTU and ACL NAMES left the loudest
        divergence of all invisible: two legs identical in every attribute where one silently blackholes the
        packets that hash onto it -- the ~50%-loss shape trace_fib_path's ECMP existential reports 'reached'.

    COVERAGE-HONEST: a single-leg (non-ECMP) lookup is 'not_ecmp'; a leg whose egress interface was not collected
    is DISCLOSED in `unobserved_legs`, one whose MTU field was not collected in `mtu_unobserved_legs`, and one
    whose forwarding could not be resolved (next hop behind an uncollected host, an ambiguous owner, a loop) in
    `forwarding_unresolved_legs` -- none of them can prove OR disprove consistency, so with any blind leg the
    verdict is 'INDETERMINATE', never a fabricated 'consistent'. Verdicts: not_ecmp | consistent | inconsistent |
    INDETERMINATE. Returns {host, dst, leg_count, mtu_divergence, acl_divergence, forwarding_divergence,
    unobserved_legs, mtu_unobserved_legs, forwarding_unresolved_legs, verdict}. Pure/offline; total on bad input
    -- resolves the leg set at the source-owning host only (a bounded, local check)."""
    snap = snap if isinstance(snap, dict) else {}
    interfaces = snap.get("interfaces") if isinstance(snap.get("interfaces"), dict) else {}
    fibs, connected, l3_hosts = _build(snap)
    safe_dst, _dst_valid = _safe_token(dst_ip)
    base = {"host": None, "dst": safe_dst, "leg_count": 0, "mtu_divergence": [],
            "acl_divergence": [], "forwarding_divergence": [], "forwarding_reached_legs": [],
            "unobserved_legs": [],
            "mtu_unobserved_legs": [], "forwarding_unresolved_legs": [], "verdict": "not_ecmp"}

    if getattr(connected, "invalid_host_key_count", 0):
        base["verdict"] = "INDETERMINATE"
        return base

    src_hosts = _hosts_owning_ip(connected, src_ip)
    if len(src_hosts) != 1:                   # no owner, or an ambiguous transit/multi-access src -> can't localize
        base["verdict"] = "INDETERMINATE"
        return base
    host = src_hosts[0]
    base["host"] = host
    legs = fib_lookup_all(fibs.get(host, []), dst_ip)
    base["leg_count"] = len(legs)
    if legs and legs[0].get("selection_error") in {"malformed_admin_distance", "unknown_route_source"}:
        base["forwarding_unresolved_legs"] = [{
            "out_intf": "", "next_hop": "", "leg_status": "lower_bound:malformed_route_evidence",
            "resolved_hops": [],
        }]
        base["verdict"] = "INDETERMINATE"
        return base
    if len(legs) < 2:
        base["verdict"] = "not_ecmp"          # a single installed path -> multipath consistency is not applicable
        return base

    # FORWARDING dimension: resolve what a flow hashed onto EACH leg actually does (the same resolver
    # trace_fib_path drives, so the two surfaces cannot disagree about a leg).
    _explore, _explore_set, _leg_outcome = _resolver(fibs, connected, l3_hosts, dst_ip)
    fwd_drop, fwd_ok, fwd_blind = [], [], []
    for leg in legs:
        _hop, (st, reached, _hops, ev) = _leg_outcome(host, leg)
        row = {"out_intf": _safe_token(leg.get("out_intf"))[0],
               "next_hop": _safe_token(leg.get("next_hop"))[0],
               "leg_status": st, "resolved_hops": list(_hops)}
        if st == "computed:unreachable":
            row["drop_evidence"] = ev.get("drop_evidence", "")
            fwd_drop.append(row)                 # PROVEN not to deliver the flow
        elif reached:
            fwd_ok.append(row)
        else:
            fwd_blind.append(row)                # trail lost -> proves nothing either way
    base["forwarding_unresolved_legs"] = fwd_blind
    base["forwarding_reached_legs"] = fwd_ok
    if fwd_drop and len(fwd_drop) < len(legs):
        # at least one leg definitively blackholes while a sibling does not -> the legs are NOT alike.
        base["forwarding_divergence"] = fwd_drop

    resolved_by_leg = {
        (row.get("out_intf", ""), row.get("next_hop", "")): list(row.get("resolved_hops") or [])
        for row in fwd_drop + fwd_ok + fwd_blind
    }
    mtus, acls, iface_blind, mtu_blind = [], [], [], []
    for leg in legs:
        oi = _safe_token(leg.get("out_intf"))[0]
        nh = _safe_token(leg.get("next_hop"))[0]
        if not oi:
            iface_blind.append({"out_intf": oi, "next_hop": nh})
            continue
        mtu = _hop_mtu(interfaces, host, oi)
        ai, ao = _iface_acl(interfaces, host, oi)
        if ai is None and ao is None and mtu is None:
            # _iface_acl returns (None, None) ONLY when the interface RECORD is absent (vs ('','') for a
            # collected record with no ACL). No record at all -> the whole leg is a blind spot.
            iface_blind.append({"out_intf": oi, "next_hop": nh})
            continue
        # The record exists. ACL '' is an OBSERVED "no filter" (not blind). But a missing MTU is its own blind
        # spot for the MTU dimension — it must NOT read as consistent-by-omission (the finding: a leg whose MTU
        # was never collected let the MTU dimension pass silently).
        if mtu is None:
            mtu_blind.append({"out_intf": oi, "next_hop": nh})
        else:
            mtus.append((oi, nh, mtu))
        acls.append((oi, ai or "", ao or ""))

    base["unobserved_legs"] = iface_blind
    base["mtu_unobserved_legs"] = mtu_blind      # additive: legs whose record exists but MTU was not collected

    # MTU divergence: distinct OBSERVED MTUs across legs (a proven divergence — the narrow leg blackholes).
    obs_mtus = {m for _oi, _nh, m in mtus}
    if len(obs_mtus) > 1:
        base["mtu_divergence"] = sorted([
            {"out_intf": oi, "next_hop": nh, "mtu": m,
             "resolved_hops": resolved_by_leg.get((oi, nh), [])}
            for oi, nh, m in mtus
        ], key=lambda d: d["mtu"])
    # ACL divergence: distinct (acl_in, acl_out) tuples across legs whose interface WAS collected.
    obs_acls = {(ai, ao) for _oi, ai, ao in acls}
    if len(obs_acls) > 1:
        base["acl_divergence"] = [{"out_intf": oi, "acl_in": ai, "acl_out": ao} for oi, ai, ao in acls]

    if base["mtu_divergence"] or base["acl_divergence"] or base["forwarding_divergence"]:
        base["verdict"] = "inconsistent"      # a proven divergence dominates -- the legs are NOT treated alike
    elif iface_blind or mtu_blind or fwd_blind:
        base["verdict"] = "INDETERMINATE"     # ANY blind spot (whole leg, its MTU, or its forwarding)
    else:
        base["verdict"] = "consistent"        # every leg fully observed and aligned on MTU + ACL + forwarding
    return base


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

    Returns {summary, newly_blocked, newly_reachable, preserved, inconclusive, inconclusive_pairs,
    ecmp_partial_drop, pairs_tested, subnets_tested,
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
        # flows the change leaves REACHABLE but over an ECMP set with a proven-blackholing leg (~50% loss):
        # a 'preserved' verdict is true and insufficient, so the pairs are named here too. Additive key.
        "ecmp_partial_drop": diff.get("ecmp_partial_drop") or [],
        "preserved": summary.get("preserved", 0),
        "both_unreachable": summary.get("both_unreachable", 0),
        "inconclusive": summary.get("inconclusive", 0),
        "pairs_tested": len(diff["pairs"]),
        "subnets_tested": subnets_tested,
        "subnets_total": subnets_total,
        "assessed": len(diff["pairs"]) > 0,
        "capped": subnets_total > subnets_tested or len(pairs) >= max_pairs,   # DISCLOSED, never silent
    }
