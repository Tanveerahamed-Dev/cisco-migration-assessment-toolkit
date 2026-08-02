# slice: dmvpn -> dmvpn-tunnel-peer-down
arch: DMVPN WAN overlay (mGRE/NHRP) — IOS / IOS-XE hub-and-spoke / spoke-to-spoke tunnels over an mGRE interface, with NHRP next-hop resolution and (typically) IPsec protection. The `show dmvpn` command lists every NHRP/tunnel peer with a per-peer State; UP is the only fully-established/healthy state, while NHRP (stuck resolving next-hop), IKE (stuck in IPsec/IKE negotiation) and down each mean that spoke/hub DMVPN tunnel is broken.
viable: True | fixture_device: core1 | snap_key: dmvpn
commands: show dmvpn[ios]
firing: snap['dmvpn'][host]['peers'][] contains at least one entry whose 'state' is present and not equal to 'UP' (case-insensitive) — i.e. NHRP, IKE, or down. Drives sig['dmvpn_down']; _d_dmvpn_tunnel_health returns a High decision (id dmvpn-tunnel-peer-down) listing the affected device(s) and tunnel IP(s). Returns None when sig['dmvpn_down'] is empty.
coverage_honesty: DMVPN is IOS/IOS-XE-only, so a device that runs no DMVPN has no 'show dmvpn' capture: _load_cmd_output returns "" (also when the box answers '% Incomplete command', filtered by _CISCO_ERRORS), parse_dmvpn_peers returns [], build_dmvpn returns {}, and the host never appears in snap['dmvpn'] (build site only stores truthy results). The signal loop only appends peers whose state is present AND not UP, so an all-UP hub/spoke contributes nothing and the detector returns None (no decision). It therefore stays SILENT on both absence and health, and fires exactly once (one grouped decision) on any observed not-UP peer — a false 'broken overlay' claim (worse than no detector) cannot arise from a healthy or DMVPN-free fleet (e.g. the Meridian reference fleet, which runs no DMVPN, stays at 0).
confidence: HIGH confidence; the slice is viable and coverage-honest. State semantics are confirmed from multiple primary/authoritative sources: UP is the only fully-established state; NHRP (next-hop unresolved), IKE (IPsec/IKE negotiating) and down each mean a broken tunnel. Exact column layout ('# Ent / Peer NBMA Addr / Peer Tunnel Add / State / UpDn Tm / Attrb') is grounded verbatim in the Ciscozine hub/spoke captures, and a real not-UP row (State=IKE) is grounded verbatim in the Network Direction capture; the parser_sample_input is a faithful multi-state composite of those Cisco-format outputs.

Design choices and caveats for the integrator to verify on the real tree:
1) PARSER ANCHOR: rows are matched by 'two addresses + alpha State + HH:MM:SS UpDn time', which cleanly rejects the legend, the 'Type:Hub/Spoke, NHRP Peers:N' line, the column header and the dashed separator (none carry a HH:MM:SS time). The leading '# Ent' count is OPTIONAL (continuation rows for multi-network peers omit it — seen in Cisco 'show dmvpn detail'), so the regex does not require it. I deliberately did NOT model the 'show dmvpn detail' Target-Network column (it only adds rows, never new States) — the base 'show dmvpn' is the primary command and the detail variant's peer rows still parse (extra trailing tokens after Attrb are ignored).
2) HEALTHY GATE: the only healthy State is UP; the detector flags everything else. This is intentional and safe — a tunnel that is administratively/operationally not UP is genuinely not forwarding overlay traffic. If a future capture shows an 'NHRP' transient that self-heals, that is still a real, report-worthy not-UP observation at assessment time (point-in-time evidence), consistent with the engine's other state detectors (LDP not-Oper, VPNv4 not-Established, VC DOWN). No down-by-silence: absence => {} => silent.
3) IPv6 NBMA: Cisco docs show IPv6 NBMA addresses (e.g. 2001:DB8:0:ABCD::1) on dual-stack DMVPN; the address class permits ':' so those rows parse, with a '.'-or-':' guard preventing a stray two-word alpha line from matching. The sample itself is IPv4 (matching the engine's 10.0.x.x convention).
4) PLATFORM: DMVPN is IOS/IOS-XE-only (no NX-OS), so a single primary command is correct; no NX-OS variant exists. The build site stores only truthy build_dmvpn results, so non-DMVPN devices never appear in snap['dmvpn'] (mirrors build_mpls/build_overlay).
5) PRIORITY: High (a down WAN-overlay tunnel = a remote site unreachable across the WAN), matching the SP/MPLS availability detectors. axes=['availability'].
The integrator should add build_dmvpn to the build.py import-from-cmdio sites it needs (re-uses existing _safe_parse/_load_cmd_output), wire build_dmvpn into the COLLECT_PARSE assembly loop (collect into all_dmvpn, publish snap_dict['dmvpn']=all_dmvpn) alongside build_mpls, add 'show dmvpn' to the IOS base command list(s), register _d_dmvpn_tunnel_health in _DETECTORS, and confirm the golden snapshot/sheet-schema treat snap['dmvpn'] consistently with the other per-device axis dicts.
sources: https://www.cisco.com/c/en/us/support/docs/security/dynamic-multipoint-vpn-dmvpn/111976-dmvpn-troubleshoot-00.html (Cisco — Troubleshoot Common DMVPN Issues: show dmvpn legend Attrb S/D/I/N/L/X, NHS Status E/R/W, UpDn Time; tunnel stuck in NHRP = next-hop unresolved) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/s1/sec-s1-cr-book/sec-cr-s4.html (Cisco IOS Security Command Reference S-Z — 'show dmvpn' command reference: hub State UP; spoke State IKE example; Crypto Session Status UP-ACTIVE) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_dmvpn/configuration/15-mt/sec-conn-dmvpn-15-mt-book/sec-conn-dmvpn-dmvpn.html (Cisco — Dynamic Multipoint VPN Configuration Guide 15M&T) | https://www.cisco.com/c/en/us/support/docs/security/dynamic-multipoint-vpn-dmvpn/221665-troubleshoot-dmvpn-phase-2-spoke-to-spok.html (Cisco — Troubleshoot DMVPN Phase 2 Spoke-to-Spoke: show dmvpn per-tunnel session info) | https://community.cisco.com/t5/vpn/dmvpn-tunnel-stuck-at-nhrp-state/td-p/4756635 (Cisco Community — show dmvpn State stuck at NHRP) | https://www.ciscozine.com/dmvpn-phase-3-troubleshoot/ (CiscoZine — verbatim 'show dmvpn' hub & spoke output: legend, column headers '# Ent / Peer NBMA Addr / Peer Tunnel Add / State / UpDn Tm / Attrb', UP rows, and 'show dmvpn detail' with continuation rows omitting the # Ent count — used to ground exact column layout) | https://networkdirection.net/articles/routingandswitching/dmvpn/troubleshooting-dmvpn/ (Network Direction — verbatim 'show dmvpn detail' row '1 200.1.1.21 192.168.250.1 IKE 00:16:28 S' confirming the broken-state State=IKE row format)

## parser_sample_input
```
Spoke2#show dmvpn
Legend: Attrb --> S - Static, D - Dynamic, I - Incomplete
        N - NATed, L - Local, X - No Socket
        # Ent --> Number of NHRP entries with same NBMA peer
        NHS Status: E --> Expecting Replies, R --> Responding, W --> Waiting
        UpDn Time --> Up or Down Time for a Tunnel
==========================================================================

Interface: Tunnel1, IPv4 NHRP Details
Type:Spoke, NHRP Peers:3,

 # Ent  Peer NBMA Addr Peer Tunnel Add State  UpDn Tm Attrb
 ----- --------------- --------------- ----- -------- -----
     1 17.17.17.1             10.0.1.1    UP 00:27:26     S
     1 27.27.27.2             10.0.1.2   IKE 00:16:28     S
     1 37.37.37.3             10.0.1.3  NHRP 00:00:04     D

Spoke2#
```

## parser_code
```
def parse_dmvpn_peers(output: str) -> list:
    """'show dmvpn' (IOS / IOS-XE DMVPN mGRE/NHRP overlay) -> [{interface, nbma, tunnel_ip, state, attrb}]
    per NHRP/tunnel peer entry. 'State' is the per-peer tunnel session state: UP is the ONLY fully-established
    (healthy) state; NHRP (stuck resolving the next-hop), IKE (stuck in IPsec/IKE negotiation) and down each
    mean that spoke/hub DMVPN tunnel is broken (no overlay forwarding to that peer). Each data row carries two
    addresses (Peer NBMA Addr, Peer Tunnel Add) followed by State and the UpDn time (HH:MM:SS); the State token
    is anchored to the immediately-following HH:MM:SS time, which lets the legend / column-header / dashed-
    separator lines (none of which carry a HH:MM:SS time) be skipped. The leading '# Ent' count is optional
    (continuation rows for multi-network peers omit it), so it is not required by the row regex; 'interface' is
    carried from the most recent 'Interface: TunnelN' header. [] when the device runs no DMVPN ('show dmvpn'
    absent / '% Incomplete command' / no peer rows). Tolerant; never raises."""
    out = []
    cur_if = ""
    # Peer NBMA / Peer Tunnel are IPv4 (sample) or IPv6 NBMA on dual-stack; match either, then anchor State to
    # the UpDn HH:MM:SS time so only real peer rows match.  Attrb (trailing letters) is optional / best-effort.
    addr = r"[0-9A-Fa-f:.]+"
    row = re.compile(
        r"^\s*(?:\d+\s+)?(" + addr + r")\s+(" + addr + r")\s+"   # Peer NBMA Addr, Peer Tunnel Add
        r"([A-Za-z]+)\s+"                                          # State (UP / NHRP / IKE / down)
        r"\d{1,2}:\d{2}:\d{2}"                                     # UpDn Tm  HH:MM:SS  (anchor)
        r"(?:\s+([A-Za-z0-9]+))?")                                 # Attrb (optional)
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        h = re.match(r"^Interface:\s*(\S+?),", s, re.IGNORECASE)   # 'Interface: Tunnel1, IPv4 NHRP Details'
        if h:
            cur_if = h.group(1)
            continue
        m = row.match(s)
        if not m:
            continue
        nbma, tun, state = m.group(1), m.group(2), m.group(3)
        # Guard: at least one of the two address columns must look like a real NBMA/tunnel address (contain a
        # '.' or ':'), so a stray two-word alpha line can never be mistaken for a peer row.
        if "." not in (nbma + tun) and ":" not in (nbma + tun):
            continue
        out.append({"interface": cur_if, "nbma": nbma, "tunnel_ip": tun,
                    "state": state, "attrb": (m.group(4) or "")})
    return out
```

## build_code
```
def build_dmvpn(cmd_to_file: Dict[str, str]) -> dict:
    """DMVPN WAN-overlay (mGRE/NHRP) state for THIS device -> {peers: [{interface, nbma, tunnel_ip, state,
    attrb}]}. Reads 'show dmvpn' (IOS / IOS-XE only -- DMVPN is not an NX-OS feature, so a Nexus box simply has
    no capture and publishes {}). A peer whose State is not UP (NHRP / IKE / down) is a broken spoke/hub tunnel:
    no overlay forwarding to that site. {} when the device runs no DMVPN. Fail-soft via _safe_parse."""
    peers = _safe_parse(parse_dmvpn_peers, _load_cmd_output(cmd_to_file, "show dmvpn")) or []
    out = {}
    if peers:
        out["peers"] = peers
    return out
```

## signal_code
```
    # DMVPN WAN-overlay (mGRE/NHRP) health (snap['dmvpn'] from build_dmvpn): a per-peer tunnel State that is not
    # UP. UP is the only fully-established state; NHRP (stuck resolving next-hop), IKE (stuck in IPsec/IKE
    # negotiation) and down each mean that spoke/hub DMVPN tunnel is broken (no overlay forwarding to that peer).
    # Coverage-honest: a device running no DMVPN publishes {} and never fires; only an OBSERVED not-UP peer is
    # surfaced (an all-UP hub/spoke stays silent).
    _dmvpn = _as_dict(snap.get("dmvpn"))
    _dmvpn_down = []
    for _dh, _df in sorted(_dmvpn.items()):
        for _p in _as_list(_as_dict(_df).get("peers")):
            _p = _as_dict(_p)
            _st = str(_p.get("state", "")).strip()
            if _st and _st.upper() != "UP":
                _dmvpn_down.append(f"{_dh} {_p.get('tunnel_ip', '?')} ({_st})")
    sig["dmvpn_down"] = _dmvpn_down
```

## detector_code
```
def _d_dmvpn_tunnel_health(snap, sig):
    """DMVPN WAN overlay (mGRE/NHRP): an NHRP/tunnel peer not in the UP state (parse_dmvpn_peers ->
    snap['dmvpn'].peers). 'show dmvpn' lists every spoke/hub tunnel peer with a per-peer State; UP is the only
    fully-established state, while NHRP (stuck resolving the next-hop), IKE (stuck in IPsec/IKE negotiation) and
    down each mean that DMVPN tunnel is broken -- there is no overlay forwarding to that site. Coverage-honest:
    fires ONLY on an OBSERVED not-UP peer; a box with no DMVPN (no 'show dmvpn' capture), or with every peer UP,
    stays silent."""
    down = sig.get("dmvpn_down") or []
    if not down:
        return None
    return _decision(
        "dmvpn-tunnel-peer-down",
        f"{len(down)} DMVPN tunnel peer(s) are NOT in the UP state (e.g. {', '.join(down[:6])}). DMVPN carries "
        "the WAN overlay over an mGRE interface with NHRP next-hop resolution and IPsec protection; UP is the "
        "only fully-established state, so a peer stuck in NHRP (next-hop unresolved), IKE (IPsec/IKE still "
        "negotiating) or down has no overlay forwarding to that spoke/hub -- the remote site is unreachable "
        "across the WAN even while the tunnel interface and underlay may appear up. Confirm NBMA reachability "
        "to the NHS, NHRP registration / authentication, and the IKE/IPsec profile to the peer before relying "
        "on the overlay at cutover.",
        len(down), ["availability"],
        ["dmvpn.peers[].state (parse_dmvpn_peers / show dmvpn)"],
        priority="High",
        driver="DMVPN WAN overlay: a tunnel peer not in UP (NHRP/IKE/down) has no overlay forwarding to that "
               "spoke/hub site -- the remote location is unreachable across the WAN.",
        devices=sorted({d.split()[0] for d in down})[:12])
```

## fixture_block
```
    # DMVPN WAN-overlay universality (mGRE/NHRP): core1 acts as a DMVPN hub. Tunnel1 peer 10.0.1.3 (NBMA
    # 37.37.37.3) is stuck in NHRP state and 10.0.1.4 (NBMA 47.47.47.4) is stuck in IKE -> _d_dmvpn_tunnel_health
    # FIRES (broken spoke tunnels: no overlay forwarding to those sites). The healthy peers (10.0.1.2 UP) prove
    # coverage-honest silence -- an all-UP hub never over-fires.
    "show dmvpn": """\
Legend: Attrb --> S - Static, D - Dynamic, I - Incomplete
        N - NATed, L - Local, X - No Socket
        # Ent --> Number of NHRP entries with same NBMA peer
        NHS Status: E --> Expecting Replies, R --> Responding, W --> Waiting
        UpDn Time --> Up or Down Time for a Tunnel
==========================================================================

Interface: Tunnel1, IPv4 NHRP Details
Type:Hub, NHRP Peers:3,

 # Ent  Peer NBMA Addr Peer Tunnel Add State  UpDn Tm Attrb
 ----- --------------- --------------- ----- -------- -----
     1 27.27.27.2             10.0.1.2    UP 00:28:32     D
     1 37.37.37.3             10.0.1.3  NHRP 00:00:04     D
     1 47.47.47.4             10.0.1.4   IKE 00:00:09     D
""",
```

## parser_test
```
def test_parse_dmvpn_peers_states(cp):
    """Universality (DMVPN WAN overlay): parse_dmvpn_peers reads 'show dmvpn' so a tunnel peer NOT in the UP
    state (NHRP / IKE / down -> no overlay forwarding to that spoke/hub) is detectable. The State token is
    anchored to the UpDn HH:MM:SS time, so the legend, the column-header row and the dashed separator (none of
    which carry a time) never create phantom peers; the leading '# Ent' count is optional; 'interface' is
    carried from the 'Interface: TunnelN' header."""
    out = (
        "Legend: Attrb --> S - Static, D - Dynamic, I - Incomplete\n"
        "        N - NATed, L - Local, X - No Socket\n"
        "        # Ent --> Number of NHRP entries with same NBMA peer\n"
        "==========================================================================\n"
        "\n"
        "Interface: Tunnel1, IPv4 NHRP Details\n"
        "Type:Spoke, NHRP Peers:3,\n"
        "\n"
        " # Ent  Peer NBMA Addr Peer Tunnel Add State  UpDn Tm Attrb\n"
        " ----- --------------- --------------- ----- -------- -----\n"
        "     1 17.17.17.1             10.0.1.1    UP 00:27:26     S\n"
        "     1 27.27.27.2             10.0.1.2   IKE 00:16:28     S\n"
        "     1 37.37.37.3             10.0.1.3  NHRP 00:00:04     D\n")
    r = parse.parse_dmvpn_peers(out)
    assert len(r) == 3
    assert r[0] == {"interface": "Tunnel1", "nbma": "17.17.17.1", "tunnel_ip": "10.0.1.1", "state": "UP", "attrb": "S"}
    assert r[1]["tunnel_ip"] == "10.0.1.2" and r[1]["state"] == "IKE"
    assert r[2]["tunnel_ip"] == "10.0.1.3" and r[2]["state"] == "NHRP"
    # Legend / header / dashed-separator lines must NOT become peers (only the 3 real rows).
    assert [p["state"] for p in r] == ["UP", "IKE", "NHRP"]
    assert parse.parse_dmvpn_peers("") == []
    assert parse.parse_dmvpn_peers("% Incomplete command.") == []
```

## detector_test
```
def test_d_dmvpn_tunnel_health_fires_on_non_up_peer_only():
    """Universality (DMVPN WAN overlay mGRE/NHRP): a device with a DMVPN tunnel peer NOT in the UP state fires
    _d_dmvpn_tunnel_health (NHRP/IKE/down -> no overlay forwarding to that spoke/hub site). Refutation: every
    peer UP (normal healthy state) and an absent dmvpn axis both stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"dmvpn": {"hub1": {"peers": [
        {"interface": "Tunnel1", "nbma": "27.27.27.2", "tunnel_ip": "10.0.1.2", "state": "UP", "attrb": "D"},
        {"interface": "Tunnel1", "nbma": "37.37.37.3", "tunnel_ip": "10.0.1.3", "state": "NHRP", "attrb": "D"},
        {"interface": "Tunnel1", "nbma": "47.47.47.4", "tunnel_ip": "10.0.1.4", "state": "IKE", "attrb": "D"},
    ]}}}
    sig = da._signals(fire)
    assert "10.0.1.3" in " ".join(sig.get("dmvpn_down", []))
    assert "10.0.1.4" in " ".join(sig.get("dmvpn_down", []))
    dec = da._d_dmvpn_tunnel_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "DMVPN" in str(dec)
    assert dec["evidence"]["count"] == 2 and "hub1" in dec["evidence"]["devices"]
    # Healthy: every peer UP -> silent (no over-firing).
    clean = {"dmvpn": {"hub1": {"peers": [
        {"interface": "Tunnel1", "nbma": "27.27.27.2", "tunnel_ip": "10.0.1.2", "state": "UP", "attrb": "D"}]}}}
    assert da._d_dmvpn_tunnel_health(clean, da._signals(clean)) is None
    # Absent: no dmvpn axis -> silent.
    assert da._d_dmvpn_tunnel_health({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (DMVPN WAN overlay mGRE/NHRP): core1 acts as a DMVPN hub with two spoke tunnels not in UP
    # (10.0.1.3 NHRP, 10.0.1.4 IKE) while 10.0.1.2 is UP.  The detector must fire end-to-end; the UP peer proves
    # no over-firing.
    assert isinstance(snap.get("dmvpn"), dict) and snap["dmvpn"].get("core1", {}).get("peers"), \
        "snapshot must publish per-device DMVPN state (build_dmvpn -> parse_dmvpn_peers)"
    assert any(d.get("id") == "dmvpn-tunnel-peer-down" for d in _bp.get("decisions", [])), \
        "engine must assess the DMVPN WAN overlay: a not-UP tunnel peer (NHRP/IKE) must fire _d_dmvpn_tunnel_health"
```