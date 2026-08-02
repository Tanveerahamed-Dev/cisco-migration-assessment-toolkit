# slice: ipv6_routing -> ipv6-routing-adjacency-down
arch: IPv6 routing plane (dual-stack reachability) — OSPFv3 / BGP-IPv6-unicast adjacency health, with `show ipv6 route summary` as the IPv6-routing-active coverage gate.
viable: True | fixture_device: access1 | snap_key: ipv6_routing
commands: show ipv6 route summary[both], show ospfv3 neighbor[ios], show bgp ipv6 unicast summary[both]
firing: Fires when snap['ipv6_routing'] for any device contains either (a) an OSPFv3 neighbor whose state (left of the '/' role suffix) is anything other than FULL or 2WAY — i.e. INIT/ATTEMPT/EXSTART/EXCHANGE/LOADING/DOWN — or (b) an IPv6 BGP peer whose State/PfxRcd is a state word rather than a numeric prefix count (Idle/Active/Connect/OpenSent/OpenConfirm). In the fixture, access1's `show ospfv3 neighbor` has 10.0.0.9 in EXSTART (fires) and its `show bgp ipv6 unicast summary` has 2001:DB8:0:9::9 Active (fires); 10.0.0.1 FULL/DR, 10.0.0.7 2WAY/DROTHER, and 2001:DB8:0:1::1 (PfxRcd 12) are healthy and prove no over-firing.
coverage_honesty: Three layers of silence. (1) ABSENT: a pure-IPv4 device returns no output for any of the three commands, build_ipv6_routing returns {}, it is not added to all_ipv6_routing, so snap['ipv6_routing'] has no entry for it and the signal loop never touches it — no cry-wolf on the IPv4-only fleet. (2) HEALTHY: FULL and 2WAY are explicitly whitelisted as the two legitimate OSPFv3 resting states (2WAY is the *intended* DROTHER↔DROTHER state on a broadcast/LAN segment — firing on it would cry wolf on every multi-access link), and a BGP peer is treated as down ONLY when its State/PfxRcd is non-numeric, so an Established peer (numeric PfxRcd, even 0) stays silent. (3) NON-FAULT GATE: `show ipv6 route summary` is parsed for context/census only; the detector deliberately does NOT use 'no ::/0 default route' as a firing signal because a missing IPv6 default is legitimate on a transit/IGP-full/egress box — that heuristic was rejected as ambiguous (a false positive is worse than no detector). Only genuinely-stuck adjacencies fire.
confidence: HIGH confidence; viable=true. The chosen fault — a stuck OSPFv3 adjacency (state left-of-'/' not in {FULL, 2WAY}) or a not-Established IPv6 BGP peer (non-numeric State/PfxRcd) — is the SAME proven, unambiguous pattern as the shipped MPLS LDP/VPNv4 and IPv4-routing-neighbor detectors, transposed to the IPv6 plane. It fires only on a genuinely-broken observed state and is silent when IPv6 routing is absent (build returns {}) or healthy.

KEY COVERAGE-HONESTY DECISION (deliberate): I REJECTED the prompt's alternative candidate "IPv6 routing enabled + global v6 address but no ::/0 default = island/no-egress" as a firing signal. A missing IPv6 default route is legitimate on transit cores, IGP-full boxes, and the egress device itself, so it would cry wolf — a false positive is worse than no detector. `show ipv6 route summary` is therefore parsed for census/context and used only as the routing-active GATE, never as a fault trigger.

The second subtle trap I handled: 2WAY is NOT a fault. Two DROTHER routers on a broadcast/LAN segment intentionally rest in 2-Way and never reach FULL (verified against Cisco's OSPF-neighbor-states doc). FULL and 2WAY are both whitelisted; only the never-resting transient states (INIT/ATTEMPT/EXSTART/EXCHANGE/LOADING/DOWN) fire. The fixture explicitly includes a 2WAY/DROTHER neighbor as the over-firing guard.

CAVEATS / integration notes for the main session: (1) Register `_d_ipv6_routing_adjacency` in `_DETECTORS` (design_advisor.py ~line 1722, alongside the MPLS detectors) and add a `design_kb` principle entry for pid `ipv6-routing-adjacency-down` (title/citation/recommended_action/alternatives/tradeoffs/domain) so `_decision`'s `by_id` lookup is populated — without it the decision still emits but title/driver fall back to the pid. (2) Wire `build_ipv6_routing` into COLLECT_PARSE_V3_23_0.py near line 1625 with an `all_ipv6_routing` accumulator and attach it to the snapshot as `snap['ipv6_routing']` (mirroring the `mpls`/`ipv6_fhs` blocks), and ensure it is stripped from the frozen golden snapshot like the other per-device service axes. (3) The BGP-IPv6 parser handles the common single-line form; IOS wraps a long IPv6 Neighbor onto its own line with the numeric/state column on the next line — if the real Meridian/customer capture shows the wrapped form, the parser needs a small two-line-join follow-up (noted, not built, to avoid ungrounded regex). (4) On NX-OS the equivalent neighbor command is `show ipv6 ospf neighbor` (already in the build's fallback list) — `show ospfv3 neighbor` is the IOS/IOS-XE form. All regex is grounded verbatim in parser_sample_input.
sources: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/command/ipv6-cr-book/ipv6-s5.html (show ipv6 route summary — 'IPv6 Routing Table - N entries' + per-source breakdown; route-type codes C/L/S/B/R/O/OI/OE1...) | https://www.cisco.com/c/en/us/support/docs/ip/ip-version-6-ipv6/112100-ospfv3-config-guide.html (Use OSPFv3 Configuration Example — 'show ospfv3 neighbor' / OSPFv3 process header + Neighbor ID/Pri/State/Dead Time/Interface ID/Interface columns, FULL/DR, FULL/BDR, FULL/- rows) | https://www.cisco.com/c/en/us/support/docs/ip/open-shortest-path-first-ospf/13685-13.html (Understand OSPF Neighbor States — Down/Attempt/Init/2-Way/Exstart/Exchange/Loading/Full; 2-Way is the stable DROTHER<->DROTHER state, FULL is full adjacency) | https://www.cisco.com/c/en/us/support/docs/ip/open-shortest-path-first-ospf/13684-12.html (Troubleshoot OSPF stuck in Exstart/Exchange — MTU mismatch is the classic cause of a neighbor stuck below FULL) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/command/ipv6-cr-book/ipv6-s1.html (show bgp ipv6 unicast summary — Neighbor/V/AS/MsgRcvd/MsgSent/TblVer/InQ/OutQ/Up/Down/State-PfxRcd; numeric PfxRcd = Established, state word e.g. Active/Idle = not Established) | https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-routing/b-ip-routing/m_ip6-route-ospfv3-xe.html (IOS-XE 17.x OSPFv3 IPv6 routing config guide — confirms 'show ospfv3 neighbor' address-family output form)

## parser_sample_input
```
--- show ipv6 route summary (IOS / IOS-XE) ---
IPv6 Routing Table - default - 8 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
static          0           0           0           0
ospf 1          1           0           96          144
bgp 65001       1           0           96          144
Total           10          0           960         1440

--- show ospfv3 neighbor (IOS-XE) ---
            OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)

Neighbor ID     Pri   State           Dead Time   Interface ID    Interface
10.0.0.1          1   FULL/DR         00:00:37    16              Vlan10
10.0.0.7          1   2WAY/DROTHER    00:00:35    18              Vlan10
10.0.0.9          0   EXSTART/  -     00:00:33    20              GigabitEthernet0/1

--- show bgp ipv6 unicast summary (IOS / IOS-XE) ---
BGP router identifier 10.0.0.4, local AS number 65001
BGP table version is 15, main routing table version 15
Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd
2001:DB8:0:1::1           4      65001     3421     3418      15    0    0 1d02h          12
2001:DB8:0:9::9           4      65009        0        0       0    0    0 never    Active
```

## parser_code
```
def parse_ipv6_route_summary(output: str) -> dict:
    """'show ipv6 route summary' (IOS / IOS-XE / NX-OS) -> {present, total, by_source:{name:count}, has_default}.
    The summary header is 'IPv6 Routing Table - <vrf>? - N entries' followed by per-source 'name: N (subnets|total)'
    lines (connected/local/static/RIP/OSPF/BGP/EIGRP/...). This is the IPv6-routing-active GATE, not a fault by
    itself: a device that runs no IPv6 routing emits nothing -> {} so the detector never cries wolf. has_default is
    True only if an explicit '::/0' line is present in the source breakdown (most boxes summarise without it, so it
    is NOT used as a firing signal -- recorded for context only). Tolerant; never raises; {} when absent."""
    out = {"present": False, "total": 0, "by_source": {}, "has_default": False}
    txt = output or ""
    if not txt.strip():
        return {}
    # Header: 'IPv6 Routing Table - 21 entries' or 'IPv6 Routing Table - default - 21 entries'
    mh = re.search(r"IPv6 Routing Table.*?-\s*(\d+)\s+entries", txt, re.IGNORECASE)
    if not mh:
        return {}
    out["present"] = True
    out["total"] = int(mh.group(1))
    # Inline form: '... entries: 4 connected, 2 static, 0 RIP, 1 OSPF, 0 BGP'
    tail = txt[mh.end():]
    minl = re.match(r"\s*:\s*(.+)", tail.splitlines()[0] if tail.splitlines() else "")
    if minl:
        for piece in minl.group(1).split(","):
            m = re.match(r"\s*(\d+)\s+([A-Za-z][\w /-]*?)\s*$", piece)
            if m:
                out["by_source"][m.group(2).strip().lower()] = int(m.group(1))
    # Block form: 'connected: 4' / 'local: 6' / 'static: 2 (5 subnets)' on their own lines
    for raw in tail.splitlines():
        m = re.match(r"\s*([A-Za-z][\w /-]*?)\s*:\s*(\d+)\b", raw)
        if m and "entries" not in m.group(1).lower():
            out["by_source"][m.group(1).strip().lower()] = int(m.group(2))
    if "::/0" in txt:
        out["has_default"] = True
    return out


def parse_ospfv3_neighbors(output: str) -> list:
    """'show ospfv3 neighbor' / 'show ipv6 ospf neighbor' (IOS / IOS-XE) -> [{neighbor_id, pri, state, role,
    interface}] per OSPFv3 adjacency. The State column carries a role suffix: 'FULL/DR', 'FULL/BDR', 'FULL/  -',
    '2WAY/DROTHER', 'EXSTART/  -', etc.; state is the token LEFT of '/', role the token right of it (normalised,
    '-' kept). FULL and 2WAY are the two healthy resting states (2WAY is the intentional DROTHER<->DROTHER state on
    a broadcast segment); INIT/ATTEMPT/EXSTART/EXCHANGE/LOADING/DOWN are transient-stuck (broken/forming adjacency,
    e.g. MTU mismatch sticks EXSTART, a one-way hello sticks INIT). The OSPFv3 process header line and the column
    header never create phantom neighbors (their first token is not a router-id). [] when no OSPFv3 is configured.
    Tolerant; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or re.match(r"^(OSPFv3|Neighbor ID)\b", s, re.IGNORECASE):
            continue
        # <router-id> <pri> <STATE/ROLE> <dead-time> <if-id> <interface>
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\d+)\s+([A-Za-z0-9-]+)\s*/\s*([A-Za-z0-9-]+)\s+\S+\s+\S+\s+(\S+)", s)
        if not m:
            continue
        out.append({"neighbor_id": m.group(1), "pri": m.group(2),
                    "state": m.group(3).upper(), "role": m.group(4),
                    "interface": m.group(5)})
    return out


def parse_bgp_ipv6_summary(output: str) -> list:
    """'show bgp ipv6 unicast summary' (IOS / IOS-XE / NX-OS) -> [{neighbor, as, state, prefixes}] per IPv6 BGP
    peer. The session is Established ONLY when the final 'State/PfxRcd' column is NUMERIC (the accepted-prefix
    count); any state WORD there (Idle / Active / Connect / OpenSent / OpenConfirm / Idle(Admin)) means the peer
    is not Established and exchanges no IPv6 routes. The 'Neighbor' value is an IPv6 address (may wrap to its own
    line on IOS when long, but the common single-line form is parsed here). Header / identifier lines are skipped
    (their first token is not an IPv6 address). [] when no IPv6 BGP is configured. Tolerant; never raises."""
    out = []
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("neighbor") or not re.match(r"^[0-9A-Fa-f:]+:", s):
            continue
        toks = s.split()
        # need at least: nbr V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
        if len(toks) < 10:
            continue
        nbr, last = toks[0], toks[-1]
        asn = toks[2] if toks[2].isdigit() else ""
        if last.isdigit():
            out.append({"neighbor": nbr, "as": asn, "state": "Established", "prefixes": int(last)})
        else:
            out.append({"neighbor": nbr, "as": asn, "state": last, "prefixes": 0})
    return out
```

## build_code
```
def build_ipv6_routing(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 routing-plane state for THIS device -> {route_summary, ospfv3_neighbors, bgp_ipv6_neighbors}. Covers the
    dual-stack reachability control plane: the IPv6 RIB census ('show ipv6 route summary', the routing-active GATE),
    OSPFv3 adjacencies ('show ospfv3 neighbor'), and IPv6 BGP peers ('show bgp ipv6 unicast summary'). {} when the
    device runs no IPv6 routing at all -> a pure-IPv4 box contributes nothing and the detector never cries wolf. An
    OSPFv3 neighbor stuck in a transient state (not FULL and not 2WAY), or an IPv6 BGP peer not Established, each
    means that dual-stack adjacency exchanges no IPv6 routes. Fail-soft via _safe_parse."""
    rsum = _safe_parse(parse_ipv6_route_summary,
                       _load_cmd_output(cmd_to_file, "show ipv6 route summary")) or {}
    ospfv3 = _safe_parse(parse_ospfv3_neighbors,
                         _load_cmd_output(cmd_to_file, "show ospfv3 neighbor", "show ipv6 ospf neighbor")) or []
    bgp6 = _safe_parse(parse_bgp_ipv6_summary,
                       _load_cmd_output(cmd_to_file, "show bgp ipv6 unicast summary")) or []
    out = {}
    if rsum:
        out["route_summary"] = rsum
    if ospfv3:
        out["ospfv3_neighbors"] = ospfv3
    if bgp6:
        out["bgp_ipv6_neighbors"] = bgp6
    return out
```

## signal_code
```
    # IPv6 routing-plane adjacency health (snap['ipv6_routing'] from build_ipv6_routing): two independent break
    # conditions across dual-stack reachability. Coverage-honest: a device running no IPv6 routing publishes {} and
    # never fires; only an OBSERVED stuck OSPFv3 neighbor (NOT FULL and NOT 2WAY -- the two healthy resting states;
    # 2WAY is the intentional DROTHER<->DROTHER state on a broadcast segment) or a not-Established IPv6 BGP peer is
    # surfaced. 'show ipv6 route summary' is the routing-active GATE only (no '::/0'-absence heuristic -- a missing
    # default is legitimate on a transit/IGP-full box, so it is never a firing signal).
    _v6r = _as_dict(snap.get("ipv6_routing"))
    _ospfv3_stuck, _bgp6_down = [], []
    _OSPFV3_HEALTHY = {"FULL", "2WAY"}
    for _vh, _vf in sorted(_v6r.items()):
        _vf = _as_dict(_vf)
        for _n in _as_list(_vf.get("ospfv3_neighbors")):
            _st = str(_as_dict(_n).get("state", "")).upper().strip()
            if _st and _st not in _OSPFV3_HEALTHY:
                _ospfv3_stuck.append(f"{_vh} {_as_dict(_n).get('neighbor_id', '?')} ({_st})")
        for _n in _as_list(_vf.get("bgp_ipv6_neighbors")):
            if str(_as_dict(_n).get("state", "")) != "Established":
                _bgp6_down.append(f"{_vh} {_as_dict(_n).get('neighbor', '?')}")
    sig["ipv6_ospfv3_stuck"] = _ospfv3_stuck
    sig["ipv6_bgp_down"] = _bgp6_down
```

## detector_code
```
def _d_ipv6_routing_adjacency(snap, sig):
    """IPv6 routing plane (dual-stack reachability): an OSPFv3 neighbor stuck in a transient state (NOT FULL and NOT
    2WAY -> parse_ospfv3_neighbors / 'show ospfv3 neighbor') or an IPv6 BGP peer not Established (parse_bgp_ipv6_summary
    / 'show bgp ipv6 unicast summary'), read from snap['ipv6_routing']. A stuck OSPFv3 adjacency (e.g. EXSTART from an
    MTU mismatch, INIT from a one-way hello) or a not-Established IPv6 BGP session exchanges no IPv6 routes, so the
    dual-stack reachability that depends on it is dark even while the parallel IPv4 plane stays Up -- a silent
    half-failure at cutover. Coverage-honest: fires ONLY on an OBSERVED stuck/not-Established adjacency. FULL and 2WAY
    OSPFv3 neighbors (2WAY is the intentional DROTHER<->DROTHER steady state on a broadcast segment) and Established
    IPv6 BGP peers never fire, and a box with no IPv6 routing publishes {} and stays silent."""
    stuck = sig.get("ipv6_ospfv3_stuck") or []
    bgp_down = sig.get("ipv6_bgp_down") or []
    if not stuck and not bgp_down:
        return None
    parts = []
    if stuck:
        parts.append(f"{len(stuck)} OSPFv3 neighbor(s) stuck in a transient (non-FULL/non-2WAY) state "
                     f"(e.g. {', '.join(stuck[:6])})")
    if bgp_down:
        parts.append(f"{len(bgp_down)} IPv6 BGP peer(s) not Established (e.g. {', '.join(bgp_down[:6])})")
    devs = {d.split()[0] for d in stuck} | {d.split()[0] for d in bgp_down}
    return _decision(
        "ipv6-routing-adjacency-down",
        "; ".join(parts) + ". OSPFv3 settles in FULL (or 2WAY between DROTHERs); any other state is a forming/stuck "
        "adjacency, and an IPv6 BGP peer is Established only when it advertises a prefix count -- a peer in "
        "Idle/Active/Connect exchanges no IPv6 routes. The dual-stack reachability riding that adjacency is dark even "
        "while the parallel IPv4 plane is Up, so the failure is invisible to an IPv4-only check. Confirm interface "
        "MTU and IPv6 link-local reachability for OSPFv3, and update-source / AS / address-family activation for IPv6 "
        "BGP, before dual-stack is trusted at cutover.",
        len(stuck) + len(bgp_down), ["availability", "convergence"],
        ["ipv6_routing.ospfv3_neighbors[].state (parse_ospfv3_neighbors / show ospfv3 neighbor)",
         "ipv6_routing.bgp_ipv6_neighbors[].state (parse_bgp_ipv6_summary / show bgp ipv6 unicast summary)"],
        priority="High",
        driver="IPv6 routing plane: a stuck OSPFv3 adjacency or a not-Established IPv6 BGP peer blackholes dual-stack "
               "reachability while the IPv4 plane stays Up -- a silent half-failure unless explicitly checked.",
        devices=sorted(devs)[:12])
```

## fixture_block
```
# IPv6 routing plane (dual-stack reachability): access1 is already dual-stack (ipv6 unicast-routing + IPv6 SVIs
# in its run-config). It runs OSPFv3 and IPv6 BGP. _d_ipv6_routing_adjacency FIRES on TWO observed stuck
# adjacencies: OSPFv3 neighbor 10.0.0.9 is EXSTART (MTU-mismatch stuck -> no IPv6 LSDB sync) and IPv6 BGP peer
# 2001:DB8:0:9::9 is Active (never Established -> no IPv6 routes). The healthy companions prove coverage-honest
# silence: 10.0.0.1 FULL/DR and 10.0.0.7 2WAY/DROTHER (2WAY is the INTENTIONAL DROTHER<->DROTHER steady state,
# must NOT fire) and IPv6 BGP peer 2001:DB8:0:1::1 with PfxRcd 12 (Established). 'show ipv6 route summary' is the
# routing-active GATE (census only -- never a firing signal). core1/core2 emit none of these -> {} (silent), so
# EXACTLY ONE switch fires.
"show ipv6 route summary": """\
IPv6 Routing Table - default - 8 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
static          0           0           0           0
ospf 1          1           0           96          144
bgp 65001       1           0           96          144
Total           10          0           960         1440
""",
"show ospfv3 neighbor": """\
            OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)

Neighbor ID     Pri   State           Dead Time   Interface ID    Interface
10.0.0.1          1   FULL/DR         00:00:37    16              Vlan10
10.0.0.7          1   2WAY/DROTHER    00:00:35    18              Vlan10
10.0.0.9          0   EXSTART/  -     00:00:33    20              GigabitEthernet0/1
""",
"show bgp ipv6 unicast summary": """\
BGP router identifier 10.0.0.4, local AS number 65001
BGP table version is 15, main routing table version 15
Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd
2001:DB8:0:1::1           4      65001     3421     3418      15    0    0 1d02h          12
2001:DB8:0:9::9           4      65009        0        0       0    0    0 never    Active
""",
```

## parser_test
```
def test_parse_ipv6_routing_plane(cp):
    """Universality (IPv6 routing plane / dual-stack reachability): the three IPv6 control-plane parsers.
    parse_ospfv3_neighbors splits the State/role column on '/' so FULL/2WAY (healthy resting states) are
    distinguishable from a stuck EXSTART; the process header + column header create no phantom neighbors.
    parse_bgp_ipv6_summary treats a numeric State/PfxRcd as Established and a state WORD (Active) as down.
    parse_ipv6_route_summary reads the 'N entries' header (the IPv6-routing-active gate). All three return
    []/{} on empty input (a pure-IPv4 box) and never raise."""
    ospf = (
        "            OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)\n"
        "\n"
        "Neighbor ID     Pri   State           Dead Time   Interface ID    Interface\n"
        "10.0.0.1          1   FULL/DR         00:00:37    16              Vlan10\n"
        "10.0.0.7          1   2WAY/DROTHER    00:00:35    18              Vlan10\n"
        "10.0.0.9          0   EXSTART/  -     00:00:33    20              GigabitEthernet0/1\n")
    r = parse.parse_ospfv3_neighbors(ospf)
    assert len(r) == 3
    assert r[0] == {"neighbor_id": "10.0.0.1", "pri": "1", "state": "FULL", "role": "DR", "interface": "Vlan10"}
    assert r[1]["state"] == "2WAY" and r[1]["role"] == "DROTHER"
    assert r[2]["neighbor_id"] == "10.0.0.9" and r[2]["state"] == "EXSTART"
    assert parse.parse_ospfv3_neighbors("") == []

    bgp = (
        "BGP router identifier 10.0.0.4, local AS number 65001\n"
        "Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "2001:DB8:0:1::1           4      65001     3421     3418      15    0    0 1d02h          12\n"
        "2001:DB8:0:9::9           4      65009        0        0       0    0    0 never    Active\n")
    b = parse.parse_bgp_ipv6_summary(bgp)
    assert len(b) == 2
    assert b[0] == {"neighbor": "2001:DB8:0:1::1", "as": "65001", "state": "Established", "prefixes": 12}
    assert b[1]["neighbor"] == "2001:DB8:0:9::9" and b[1]["state"] == "Active" and b[1]["prefixes"] == 0
    assert parse.parse_bgp_ipv6_summary("") == []

    summ = parse.parse_ipv6_route_summary(
        "IPv6 Routing Table - default - 8 entries\n"
        "connected       4           0           384         576\n"
        "ospf 1          1           0           96          144\n")
    assert summ["present"] is True and summ["total"] == 8
    assert summ["by_source"].get("connected") == 4
    assert parse.parse_ipv6_route_summary("") == {}
```

## detector_test
```
def test_d_ipv6_routing_adjacency_fires_on_stuck_adjacency_only():
    """Universality (IPv6 routing plane / dual-stack reachability): a device with an OSPFv3 neighbor stuck in a
    transient state (NOT FULL / NOT 2WAY) OR an IPv6 BGP peer not Established fires _d_ipv6_routing_adjacency
    (dual-stack reachability dark while IPv4 stays Up). Refutation, coverage-honest: a FULL + 2WAY OSPFv3 pair
    and an Established (numeric-PfxRcd) IPv6 BGP peer (all healthy resting states), and an absent ipv6_routing
    axis, all stay silent."""
    import cisco_toolkit.design_advisor as da
    fire = {"ipv6_routing": {"sw1": {
        "ospfv3_neighbors": [
            {"neighbor_id": "10.0.0.1", "pri": "1", "state": "FULL", "role": "DR", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.7", "pri": "1", "state": "2WAY", "role": "DROTHER", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.9", "pri": "0", "state": "EXSTART", "role": "-", "interface": "Gi0/1"},
        ],
        "bgp_ipv6_neighbors": [
            {"neighbor": "2001:DB8:0:1::1", "as": "65001", "state": "Established", "prefixes": 12},
            {"neighbor": "2001:DB8:0:9::9", "as": "65009", "state": "Active", "prefixes": 0},
        ]}}}
    sig = da._signals(fire)
    assert "10.0.0.9" in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "EXSTART" in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "2001:DB8:0:9::9" in " ".join(sig.get("ipv6_bgp_down", []))
    # the two healthy OSPFv3 neighbors must NOT appear in the stuck list (FULL + 2WAY are resting states)
    assert "10.0.0.1" not in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    assert "10.0.0.7" not in " ".join(sig.get("ipv6_ospfv3_stuck", []))
    dec = da._d_ipv6_routing_adjacency(fire, sig)
    assert dec is not None and dec["priority"] == "High"
    assert "OSPFv3" in str(dec) and "sw1" in dec["evidence"]["devices"]
    # all-healthy: FULL + 2WAY OSPFv3, Established IPv6 BGP -> silent
    clean = {"ipv6_routing": {"sw1": {
        "ospfv3_neighbors": [
            {"neighbor_id": "10.0.0.1", "pri": "1", "state": "FULL", "role": "BDR", "interface": "Vlan10"},
            {"neighbor_id": "10.0.0.7", "pri": "1", "state": "2WAY", "role": "DROTHER", "interface": "Vlan10"},
        ],
        "bgp_ipv6_neighbors": [
            {"neighbor": "2001:DB8:0:1::1", "as": "65001", "state": "Established", "prefixes": 0}]}}}
    assert da._d_ipv6_routing_adjacency(clean, da._signals(clean)) is None
    # absent axis -> silent
    assert da._d_ipv6_routing_adjacency({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (IPv6 routing plane / dual-stack reachability): access1 is dual-stack and runs OSPFv3 + IPv6 BGP
    # with one OSPFv3 neighbor stuck EXSTART (10.0.0.9) and one IPv6 BGP peer Active (2001:DB8:0:9::9). The IPv6
    # routing-adjacency detector must fire end-to-end; the healthy companions (FULL/DR, 2WAY/DROTHER, Established
    # PfxRcd 12) prove no over-firing.
    assert isinstance(snap.get("ipv6_routing"), dict) and snap["ipv6_routing"].get("access1", {}).get("ospfv3_neighbors"), \
        "snapshot must publish per-device IPv6 routing state (build_ipv6_routing -> parse_ospfv3_neighbors)"
    assert any(d.get("id") == "ipv6-routing-adjacency-down" for d in _bp.get("decisions", [])), \
        "engine must assess the IPv6 routing plane: a stuck OSPFv3 adjacency / not-Established IPv6 BGP peer must fire _d_ipv6_routing_adjacency"
```