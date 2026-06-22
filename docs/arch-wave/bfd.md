# slice: bfd -> bfd-session-down-failover-degraded
arch: BFD fast-failover (universal sub-second failure detection for OSPF/BGP/HSRP/EIGRP/static client protocols, any architecture)
viable: True | fixture_device: core1 | snap_key: bfd
commands: show bfd neighbors[both]
firing: A BFD session whose State column reads exactly "Down" (case-insensitive) on any device. Reported per-host with neighbor IP and interface; count = number of Down sessions. AdminDown and Up never fire.
coverage_honesty: Three silence guarantees, each mirrored from the MPLS/overlay detectors: (1) ABSENT -- a device with no BFD returns nothing / '% BFD is not enabled' -> parse_bfd_neighbors returns [] -> build_bfd returns {} -> the host is omitted from snap['bfd'] -> sig['bfd_down'] is empty -> detector returns None. (2) HEALTHY -- every session Up -> no Down match -> empty signal -> None. (3) INTENTIONAL -- AdminDown is an operator-disabled state (BFD shut for maintenance / suppressed during a window), NOT a forwarding-path failure; firing on it would cry-wolf, so the signal matches state == 'down' ONLY and explicitly excludes 'admindown'. The parser reads the State column BY HEADER POSITION, so the co-located 'RH/RS' column (which is itself literally Up/Down) can never be misread as a Down session and manufacture a false positive. A false positive here is worse than no detector, so only the unambiguous Down state fires.
confidence: High confidence and viable. The Down state is the cleanest unambiguous broken-state for BFD: it is a forwarding-path failure that removes sub-second failover, directly matching the intended firing condition, and it is verbatim-attested (an actual 'Down' data row) in the primary Cisco DevNet NX-OS reference. Coverage-honesty is strong on all three axes (absent box -> {}; all-Up -> silent; AdminDown -> deliberately excluded as intentional/maintenance, preventing cry-wolf). The one real subtlety -- which I designed around -- is that 'show bfd neighbors' has a 'RH/RS' column that is ALSO literally 'Up'/'Down'; a token-based parser would misread it, so the parser anchors on the header line and reads the 'State' column BY POSITION via the repo's own extract_fixed_cols/slice_col primitives, and the parser_test explicitly asserts the healthy row's RH/RS 'Up' does not get mistaken for State. The parser handles both the IOS layout (NeighAddr-first, no Holdown) and the IOS-XE/NX-OS layout (OurAddr-first, with Holdown + trailing Vrf/Type, possibly-blank Int for multihop). Caveats for the integrator: (1) 'show bfd neighbors' is not yet in the COLLECT_PARSE base command lists (NXOS_COMMANDS ~line 486 + the IOS list ~line 579) -- add it there so live/offline collection captures it, and add build_bfd to the imports (~line 421) + invoke it in the per-device loop (~line 1614, mirroring build_mpls: all_bfd[hostname]=bfd) and publish snap_dict['bfd']=all_bfd (~line 2157). (2) Register _d_bfd_session_health in _DETECTORS (~line 1722). (3) The slug PID 'bfd-session-down-failover-degraded' has no design_kb principle yet; _decision degrades gracefully (uses the pid as title, empty citation/action) exactly as written, and the tests assert on the detector's own summary -- but adding a matching KB principle (domain 'availability'/'convergence', priority High) would enrich the HLD/LLD rendering, optional and non-blocking. No false-positive path identified; the only residual risk is an exotic platform whose header omits the literal 'State' token, in which case the parser safely returns [] (silent) rather than guessing.
sources: https://developer.cisco.com/docs/nx-api-cli-reference-for-the-cisco-nexus-7000-series-platform/bfd-commands/ (Cisco DevNet NX-API/NX-OS BFD command reference -- verbatim 'show bfd neighbors' with OurAddr/NeighAddr/LD/RD/RH/RS/Holdown(mult)/State/Int/Vrf/Type columns and BOTH an Up and a Down data row; documented State values Up/Down/AdminDown) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bfd/configuration/15-mt/irb-15-mt-book/irb-bi-fwd-det.html (Cisco IOS 15M&T BFD Configuration Guide -- 'show bfd neighbors' / 'show bfd neighbors details' examples; IOS layout NeighAddr/LD/RD/RH/RS/State/Int) | https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/16-9/command_reference/b_169_9500_cr/bidirectional_forwarding_detection_commands.html (Cisco Catalyst 9500 IOS-XE 16.9 BFD command reference -- show bfd neighbors field definitions) | https://www.cisco.com/c/en/us/support/docs/ip/ip-routing/220364-troubleshoot-bidirectional-forwarding-de.html (Cisco IOS-XE BFD troubleshooting -- 'BFD session ... going Down Reason: RX DOWN' and the Down-state failover-delay semantics that motivate firing on Down)

## parser_sample_input
```
switch# show bfd neighbors

OurAddr         NeighAddr       LD/RD                 RH/RS           Holdown(mult)     State       Int               Vrf                       Type
10.0.255.1      10.0.255.2      1090519041/0          Up              N/A(3)            Up          Po10              default                   SH
10.0.255.1      10.0.255.9      1090519042/0          Down            N/A(3)            Down        Eth8/2            default                   SH
10.0.0.1        10.0.0.2        1090519045/1090519044 Up              5273(3)           Up          Vlan10            default                   SH
```

## parser_code
```
def parse_bfd_neighbors(output: str) -> list:
    \"\"\"'show bfd neighbors' (IOS / IOS-XE / NX-OS) -> [{neighbor, local_disc, remote_disc, state, interface}]
    per BFD session. BFD gives a client protocol (OSPF/BGP/EIGRP/HSRP/static) sub-second forwarding-path
    failure detection; a session in the Up state is protecting its clients. A session in the Down state means
    the fast-failover path is broken -- the client falls back to its native (multi-second) timers, so a link
    failure no longer converges in milliseconds. AdminDown (operator-disabled) is captured but is NOT a
    forwarding failure.

    Two real on-the-wire layouts exist and BOTH are handled by anchoring on the header line and reading the
    'State' column BY POSITION (never the FIRST Up/Down token, because the 'RH/RS' column is also literally
    'Up'/'Down' and would otherwise be misread):
      * IOS:            'NeighAddr  LD/RD  RH/RS  State  Int'
      * IOS-XE / NX-OS: 'OurAddr  NeighAddr  LD/RD  RH/RS  Holdown(mult)  State  Int [Vrf  Type]'
    NX-OS adds trailing Vrf/Type (SH/MH) columns and may leave Int blank for a multihop session. [] when the
    device runs no BFD ('% BFD is not enabled' / no header / empty). Tolerant; never raises.\"\"\"
    lines = (output or \"\").splitlines()
    hdr_idx = -1
    cols = {}
    for i, raw in enumerate(lines):
        # The header is the line carrying both 'NeighAddr' and 'State' (case-insensitive).
        if re.search(r\"NeighAddr\", raw, re.IGNORECASE) and re.search(r\"\\bState\\b\", raw, re.IGNORECASE):
            cols = extract_fixed_cols(raw, [
                (\"OurAddr\", \"ouraddr\"), (\"NeighAddr\", \"neighaddr\"), (\"LD/RD\", \"ldrd\"),
                (\"RH/RS\", \"rhrs\"), (\"Holdown\", \"holdown\"), (\"State\", \"state\"),
                (\"Int\", \"interface\"), (\"Vrf\", \"vrf\"), (\"Type\", \"type\"),
            ])
            hdr_idx = i
            break
    out = []
    if hdr_idx < 0 or \"state\" not in cols or \"neighaddr\" not in cols:
        return out
    ip_re = re.compile(r\"^(?:\\d+\\.\\d+\\.\\d+\\.\\d+|[0-9A-Fa-f:]+:[0-9A-Fa-f:]+)$\")
    for raw in lines[hdr_idx + 1:]:
        if not raw.strip() or set(raw.strip()) <= {\"-\"}:
            continue
        s0, e0 = cols[\"neighaddr\"]
        neigh = slice_col(raw, s0, e0).split()[0] if slice_col(raw, s0, e0) else \"\"
        if not ip_re.match(neigh):                      # skip wrapped/continuation/non-data lines
            continue
        st_s, st_e = cols[\"state\"]
        state = (slice_col(raw, st_s, st_e).split() or [\"\"])[0]
        ldrd = slice_col(raw, *cols[\"ldrd\"]).split()[0] if \"ldrd\" in cols and slice_col(raw, *cols[\"ldrd\"]) else \"\"
        ld, _, rd = ldrd.partition(\"/\")
        iface = \"\"
        if \"interface\" in cols:
            itoks = slice_col(raw, *cols[\"interface\"]).split()
            iface = normalize_ifname(itoks[0]) if itoks else \"\"
        out.append({\"neighbor\": neigh, \"local_disc\": ld, \"remote_disc\": rd,
                    \"state\": state, \"interface\": iface})
    return out
```

## build_code
```
def build_bfd(cmd_to_file: Dict[str, str]) -> dict:
    \"\"\"BFD fast-failover session state for THIS device -> {sessions: [{neighbor, local_disc, remote_disc,
    state, interface}]}. BFD provides sub-second forwarding-path failure detection for its client protocols
    (OSPF/BGP/EIGRP/HSRP/static); a session in the Down state means that fast-failover is broken and the
    client has fallen back to its native (multi-second) convergence timers. {} when the device runs no BFD
    (so a non-BFD box never publishes the axis and the detector stays silent). Fail-soft via _safe_parse.\"\"\"
    sessions = _safe_parse(parse_bfd_neighbors, _load_cmd_output(cmd_to_file, \"show bfd neighbors\")) or []
    out = {}
    if sessions:
        out[\"sessions\"] = sessions
    return out
```

## signal_code
```
    # BFD fast-failover health (snap['bfd'] from build_bfd): a BFD session in the Down state means sub-second
    # forwarding-path failure detection is broken for its client protocol (OSPF/BGP/EIGRP/HSRP/static) -- the
    # client reverts to its native (multi-second) convergence timers, so a link failure no longer fails over in
    # milliseconds. Coverage-honest: a device running no BFD publishes {} and never fires; an UP session is
    # healthy; AdminDown is an OPERATOR-DISABLED (intentional / maintenance) state, NOT a forwarding failure,
    # so it is deliberately EXCLUDED (firing on it would cry-wolf during a maintenance window).
    _bfd = _as_dict(snap.get("bfd"))
    _bfd_down = []
    for _bh, _bf in sorted(_bfd.items()):
        for _s in _as_list(_as_dict(_bf).get("sessions")):
            _st = str(_as_dict(_s).get("state", "")).strip().lower()
            if _st == "down":
                _bfd_down.append(f"{_bh} {_as_dict(_s).get('neighbor', '?')}"
                                 + (f" ({_as_dict(_s).get('interface')})" if _as_dict(_s).get('interface') else ""))
    sig["bfd_down"] = _bfd_down
    sig["bfd_down_devices"] = sorted({d.split()[0] for d in _bfd_down})[:12]
```

## detector_code
```
def _d_bfd_session_health(snap, sig):
    \"\"\"BFD fast-failover: a BFD session in the Down state (parse_bfd_neighbors -> snap['bfd'].sessions). BFD
    gives its client protocol (OSPF/BGP/EIGRP/HSRP/static) sub-second forwarding-path failure detection; a
    session that is Down means that protection is gone and the client has reverted to its native multi-second
    convergence timers, so a link failure no longer fails over in milliseconds -- the exact resilience a
    migration is supposed to preserve. Coverage-honest: fires ONLY on an OBSERVED Down session; an Up session,
    an AdminDown (operator-disabled / maintenance) session, and a box with no BFD all stay silent.\"\"\"
    down = sig.get(\"bfd_down\") or []
    if not down:
        return None
    return _decision(
        \"bfd-session-down-failover-degraded\",
        f\"{len(down)} BFD session(s) are in the Down state (e.g. {', '.join(down[:6])}). BFD provides \"
        \"sub-second forwarding-path failure detection for its client protocol (OSPF/BGP/EIGRP/HSRP/static); a \"
        \"session that is Down means that fast-failover is broken and the client has fallen back to its native \"
        \"(multi-second) convergence timers, so a link or next-hop failure no longer converges in milliseconds. \"
        \"Confirm the L1/L2 path and IGP/BGP adjacency to the neighbor, matching BFD interval/multiplier and \"
        \"echo settings on both ends, and any platform BFD-offload limit before the fast-convergence design is \"
        \"trusted at cutover.\",
        len(down), [\"availability\", \"convergence\"],
        [\"bfd.sessions[].state (parse_bfd_neighbors / show bfd neighbors)\"],
        priority=\"High\",
        driver=\"Fast failover: a BFD session in the Down state removes sub-second failure detection for its \"
               \"client protocol, dropping convergence back to slow native timers (AdminDown / Up are not flagged).\",
        devices=sig.get(\"bfd_down_devices\") or [])
```

## fixture_block
```
    # BFD fast-failover (universality): core1 runs BFD with one session DOWN and one UP -> _d_bfd_session_health
    # fires on the Down session only. The Down session (10.0.255.9 on Gi1/0/3) means sub-second failover for its
    # client protocol is broken; the Up session (10.0.255.2 on Gi1/0/1) is the healthy companion that proves the
    # detector does NOT over-fire. Note the 'RH/RS' column is also literally Up/Down -- the parser must read the
    # later 'State' column by position, not the first Up/Down token, or it would misread the healthy row.
    "show bfd neighbors": """\
OurAddr         NeighAddr       LD/RD                 RH/RS           Holdown(mult)     State       Int
10.0.255.1      10.0.255.2      1090519041/1090519040 Up              583(3)            Up          Gi1/0/1
10.0.255.1      10.0.255.9      1090519042/0          Down            N/A(3)            Down        Gi1/0/3
""",
```

## parser_test
```
def test_parse_bfd_neighbors_state_by_column_not_rhrs(cp):
    """Universality (BFD fast-failover): parse_bfd_neighbors reads 'show bfd neighbors' and MUST take the
    State value from the State COLUMN, not the first Up/Down token -- the 'RH/RS' column is also literally
    Up/Down, so a naive first-token match would misread a healthy row. Covers the NX-OS/IOS-XE layout (with
    Holdown + trailing Vrf/Type) and proves a Down session is detectable while the Up row stays Up. Empty /
    'not enabled' input yields []."""
    out = (
        "switch# show bfd neighbors\n"
        "\n"
        "OurAddr         NeighAddr       LD/RD                 RH/RS           Holdown(mult)     State       Int               Vrf                       Type\n"
        "10.0.255.1      10.0.255.2      1090519041/1090519040 Up              583(3)            Up          Po10              default                   SH\n"
        "10.0.255.1      10.0.255.9      1090519042/0          Down            N/A(3)            Down        Eth8/2            default                   SH\n")
    r = parse.parse_bfd_neighbors(out)
    assert len(r) == 2
    by_n = {x["neighbor"]: x for x in r}
    assert by_n["10.0.255.2"]["state"] == "Up"      # RH/RS Up did NOT bleed into a phantom; real State is Up
    assert by_n["10.0.255.9"]["state"] == "Down"    # the genuinely broken session
    assert by_n["10.0.255.2"]["interface"] == "Po10"
    assert by_n["10.0.255.9"]["local_disc"] == "1090519042" and by_n["10.0.255.9"]["remote_disc"] == "0"
    # older IOS layout (no OurAddr/Holdown, NeighAddr first) still parses the State column correctly
    ios = (
        "NeighAddr                         LD/RD    RH/RS     State     Int\n"
        "10.0.0.2                           1/1     Up        Up        Fa0/0\n")
    ri = parse.parse_bfd_neighbors(ios)
    assert len(ri) == 1 and ri[0]["neighbor"] == "10.0.0.2" and ri[0]["state"] == "Up" and ri[0]["interface"] == "Fa0/0"
    assert parse.parse_bfd_neighbors("") == []
    assert parse.parse_bfd_neighbors("% BFD is not enabled\n") == []
```

## detector_test
```
def test_d_bfd_session_health_fires_on_down_session_only():
    """Universality (BFD fast-failover): a device with a BFD session in the Down state fires
    _d_bfd_session_health (sub-second failover gone -> client falls back to slow native timers). Refutation:
    an all-Up device, an AdminDown-only device (operator-disabled, intentional -- must NOT cry-wolf), and an
    absent bfd axis all stay silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    fire = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.2", "local_disc": "11", "remote_disc": "10", "state": "Up", "interface": "Gi1/0/1"},
        {"neighbor": "10.0.255.9", "local_disc": "12", "remote_disc": "0", "state": "Down", "interface": "Gi1/0/3"},
    ]}}}
    sig = da._signals(fire)
    assert "10.0.255.9" in " ".join(sig.get("bfd_down", []))
    dec = da._d_bfd_session_health(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "BFD" in str(dec)
    assert "core1" in dec["evidence"]["devices"]
    # healthy: every session Up -> silent
    clean = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.2", "local_disc": "11", "remote_disc": "10", "state": "Up", "interface": "Gi1/0/1"}]}}}
    assert da._d_bfd_session_health(clean, da._signals(clean)) is None
    # AdminDown (operator-disabled) is intentional, not a forwarding failure -> must stay silent
    admin = {"bfd": {"core1": {"sessions": [
        {"neighbor": "10.0.255.9", "local_disc": "12", "remote_disc": "0", "state": "AdminDown", "interface": "Gi1/0/3"}]}}}
    assert da._d_bfd_session_health(admin, da._signals(admin)) is None
    # absent axis -> silent
    assert da._d_bfd_session_health({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (BFD fast-failover): core1 runs BFD with one session DOWN (10.0.255.9 on Gi1/0/3) and one
    # UP (10.0.255.2 on Gi1/0/1).  The detector must fire end-to-end; the healthy Up session (whose RH/RS
    # column is also 'Up') proves no over-firing and proves the parser reads State by column, not first token.
    assert isinstance(snap.get("bfd"), dict) and snap["bfd"].get("core1", {}).get("sessions"), \
        "snapshot must publish per-device BFD state (build_bfd -> parse_bfd_neighbors)"
    assert any(d.get("id") == "bfd-session-down-failover-degraded" for d in _bp.get("decisions", [])), \
        "engine must assess BFD fast-failover: a Down BFD session must fire _d_bfd_session_health"
```