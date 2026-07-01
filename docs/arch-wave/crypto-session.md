# slice: crypto-session -> ipsec-crypto-session-down
arch: IPsec VPN / encrypted WAN (site-to-site crypto-map / VTI tunnels; IOS / IOS-XE control-plane via show crypto session)
viable: True | fixture_device: core1 | snap_key: crypto
commands: show crypto session[ios]
firing: A crypto session's 'Session status' begins with DOWN (i.e. DOWN or DOWN-NEGOTIATING) -> no established IKE/IPsec SA -> the encrypted tunnel is down. Registered by adding _d_crypto_session_health to the _DETECTORS list in design_advisor.py (alongside the SP/MPLS detectors).
coverage_honesty: Three-way honesty, mirroring _d_mpls_l2vpn_health. (1) ABSENT: a device running no IPsec parses [] sessions, build_crypto returns {}, snap['crypto'] has no entry for it -> the signal list is empty -> detector returns None. (2) HEALTHY: every UP-* status is an established tunnel and is deliberately NOT flagged -- not just UP-ACTIVE but also UP-IDLE (established but no data crossing right now) and UP-NO-IKE (IPsec SAs still up while IKE re-keys after a peer reload). Firing on UP-IDLE/UP-NO-IKE would be a false 'tunnel down', which is worse than no detector, so the gate is the strict startswith('DOWN') test, not 'anything but UP-ACTIVE'. (3) BROKEN: only a status literally beginning with DOWN (DOWN / DOWN-NEGOTIATING) fires -- the one unambiguous state where the SA is genuinely not established. The signal also records device+interface+peer so the decision cites exact evidence rather than a bare count.
confidence: HIGH that this slice is correct and coverage-honest. Field layout and the full Session status value set (UP-ACTIVE / UP-IDLE / UP-NO-IKE / DOWN / DOWN-NEGOTIATING) are confirmed across the Cisco IOS Security Command Reference, the IP Security VPN Monitoring config guide, and the Arista Cisco-compatible mirror (the latter fetched VERBATIM: 'Interface: Tunnel0 / Session status: UP-ACTIVE / Peer: 1.0.0.1 port 500 ... / IKEv1 SA: ... Active / IPSEC FLOW: ... / Active SAs: 2, origin: crypto map'). The parser is grounded exactly in that block. Note cisco.com itself returns HTTP 403 to the fetch tool, so the verbatim quoting leans on the Arista mirror + multiple Cisco search snippets that agree; the field names and status table are unambiguous and consistent across all of them. KEY COVERAGE-HONESTY CHOICE: I deliberately scope the broken-state to status.startswith('DOWN') rather than the task's looser 'not UP-ACTIVE'. UP-IDLE (established, momentarily no data) and UP-NO-IKE (IPsec SAs up while IKE re-keys after a peer reload) are NOT broken tunnels -- firing on them would be a false 'tunnel down', worse than no detector. DOWN and DOWN-NEGOTIATING are the only unambiguous not-established states, so they are the firing set; this is the safest reading and still matches the intent (no established IKE/IPsec SA = tunnel down). Caveats / integration notes for the main session: (1) build_crypto must be wired into COLLECT_PARSE like build_mpls -- add an all_crypto dict, call crypto = build_crypto(cmd_to_file) inside the per-device loop with `if crypto: all_crypto[hostname] = crypto`, publish snap_dict['crypto'] = all_crypto, and add 'show crypto session' to BOTH base command lists (IOS and NX-OS sections, though it is an IOS/IOS-XE command). (2) Register _d_crypto_session_health in the _DETECTORS list. (3) The pid 'ipsec-crypto-session-down' has no design_kb entry (by design, exactly like 'mpls-ldp-session-down'); _decision falls back to pid-as-title with my explicit driver/priority, so no design_kb change is required -- but if the team prefers, a design_kb principle under a 'wan-encryption' domain could be added later. (4) NX-OS does not implement 'show crypto session' (IPsec there is via the IPsec service / different CLI), so this axis is IOS/IOS-XE-only -- correctly silent on NX-OS via the empty-parse path. (5) Priority High matches the SP/MPLS availability detectors (a down encrypted WAN tunnel is a hard site outage). The double-quoted Python string literals in parser_code/build_code/signal_code/detector_code/parser_test/detector_test use escaped quotes for JSON transport -- unescape to real triple-quoted docstrings on integration.
sources: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/s1/sec-s1-cr-book/sec-cr-s3.html (Cisco IOS Security Command Reference S to Z -> 'show crypto session': output fields Interface / Session status / Peer / IKEv1|IKEv2 SA / IPSEC FLOW / Active SAs, and the Session status value table UP-ACTIVE / UP-IDLE / UP-NO-IKE / DOWN / DOWN-NEGOTIATING) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_imgmt/configuration/xe-16-12/sec-ipsec-management-xe-16-12-book/sec-ip-security-vpn.html (IPsec Management Configuration Guide, IOS XE 16.12 -> IP Security VPN Monitoring: 'show crypto session' / 'show crypto session detail' example output and Session status meanings; UP-ACTIVE = IPsec SA up/active transferring data, DOWN-NEGOTIATING = SAs down or being brought back up) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_conn_imgmt/configuration/xe-3s/sec-ipsec-management-xe-3s-book/sec-ip-security-vpn.html (same IP Security VPN Monitoring chapter, IOS XE 3S -> corroborates the Session status status-list and verbatim 'Interface:/Session status:/Peer:/IKE SA:/IPSEC FLOW:/Active SAs:' layout) | https://www.arista.com/en/cg-veos-router/veos-router-ipsec-support (Arista veOS Router IPsec, Cisco-compatible -> reproduces the exact 'show crypto session detail' block: 'Interface: Tunnel0 / Session status: UP-ACTIVE / Peer: x port 500 / IKEv1 SA: ... Active / IPSEC FLOW: ... / Active SAs: 2, origin: crypto map' confirming field order and indentation)

## parser_sample_input
```
Crypto session current status

Interface: Tunnel0
Session status: UP-ACTIVE
Peer: 10.0.255.2 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.2/500 Active
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.20.0/255.255.255.0
        Active SAs: 2, origin: crypto map
Interface: Tunnel1
Session status: DOWN-NEGOTIATING
Peer: 10.0.255.9 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.9/500 Inactive
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.30.0/255.255.255.0
        Active SAs: 0, origin: crypto map
```

## parser_code
```
def parse_crypto_sessions(output: str) -> list:
    \"\"\"'show crypto session' (IOS / IOS-XE site-to-site IPsec) -> [{interface, peer, status}] per crypto
    session. A crypto session is the IKE + IPsec SA bundle to one peer; the operational health is the
    'Session status:' field. UP-ACTIVE (passing data) / UP-IDLE (established, idle) / UP-NO-IKE (IPsec SAs
    up, IKE re-keying) are all UP states -- the encrypted tunnel exists. DOWN and DOWN-NEGOTIATING mean the
    IKE/IPsec SA is not established, so the tunnel is down and carries nothing. Each 'Interface:' opens a new
    record; 'Peer:' (first token after the label, before any 'port') and 'Session status:' fill it. [] when
    the device runs no IPsec / the command produced nothing. Tolerant; never raises.\"\"\"
    out = []
    cur = None
    for raw in (output or \"\").splitlines():
        s = raw.strip()
        m = re.match(r\"^Interface:\\s*(\\S+)\", s, re.IGNORECASE)
        if m:
            if cur is not None:
                out.append(cur)
            cur = {\"interface\": m.group(1), \"peer\": \"\", \"status\": \"\"}
            continue
        if cur is None:
            continue
        st = re.match(r\"^Session status:\\s*(\\S+)\", s, re.IGNORECASE)
        if st:
            cur[\"status\"] = st.group(1).upper()
            continue
        pr = re.match(r\"^Peer:\\s*(\\d+\\.\\d+\\.\\d+\\.\\d+)\", s, re.IGNORECASE)
        if pr and not cur[\"peer\"]:
            cur[\"peer\"] = pr.group(1)
    if cur is not None:
        out.append(cur)
    return out
```

## build_code
```
def build_crypto(cmd_to_file: Dict[str, str]) -> dict:
    \"\"\"IPsec encrypted-WAN session state for THIS device -> {sessions: [{interface, peer, status}]}. Reads
    'show crypto session' (IOS / IOS-XE site-to-site IPsec, crypto-map or VTI). Each entry is one IKE/IPsec
    peering; a status that begins with DOWN (DOWN / DOWN-NEGOTIATING) means the IKE/IPsec SA is not
    established, so the encrypted tunnel is down. {} when the device runs no IPsec (no sessions parsed).
    Fail-soft via _safe_parse.\"\"\"
    sessions = _safe_parse(parse_crypto_sessions, _load_cmd_output(cmd_to_file, \"show crypto session\")) or []
    out = {}
    if sessions:
        out[\"sessions\"] = sessions
    return out
```

## signal_code
```
    # IPsec encrypted-WAN session health (snap['crypto'] from build_crypto): a site-to-site crypto session
    # whose 'Session status' begins with DOWN (DOWN / DOWN-NEGOTIATING) has no established IKE/IPsec SA, so
    # the encrypted tunnel is down and carries no traffic. Coverage-honest: a device with no IPsec publishes
    # {} and never fires; every UP-* status (UP-ACTIVE passing data, UP-IDLE established-idle, UP-NO-IKE
    # IPsec-up-while-IKE-rekeys) is treated as healthy and stays silent -- only an OBSERVED DOWN* session is
    # surfaced (a false 'tunnel down' is worse than no detector).
    _crypto = _as_dict(snap.get(\"crypto\"))
    _crypto_down = []
    for _ch, _cf in sorted(_crypto.items()):
        for _se in _as_list(_as_dict(_cf).get(\"sessions\")):
            _se = _as_dict(_se)
            if str(_se.get(\"status\", \"\")).strip().upper().startswith(\"DOWN\"):
                _crypto_down.append(f\"{_ch} {_se.get('interface', '?')} -> {_se.get('peer', '?')}\")
    sig[\"crypto_sessions_down\"] = _crypto_down
```

## detector_code
```
def _d_crypto_session_health(snap, sig):
    \"\"\"IPsec encrypted-WAN tunnel health: a site-to-site crypto session whose 'Session status' begins with
    DOWN -- DOWN or DOWN-NEGOTIATING (parse_crypto_sessions -> snap['crypto'].sessions). The status is the
    IKE+IPsec SA state to that peer; DOWN / DOWN-NEGOTIATING means the SA is not established, so the encrypted
    tunnel is down and forwards no protected traffic (the WAN/overlay site behind it is cut off). Coverage-
    honest: fires ONLY on an OBSERVED DOWN* session -- every UP-* status (UP-ACTIVE / UP-IDLE / UP-NO-IKE) is
    an established tunnel and stays silent, and a device with no IPsec stays silent.\"\"\"
    down = sig.get(\"crypto_sessions_down\") or []
    if not down:
        return None
    return _decision(
        \"ipsec-crypto-session-down\",
        f\"{len(down)} IPsec crypto session(s) are DOWN / DOWN-NEGOTIATING (e.g. {', '.join(down[:6])}). \"
        \"The session status is the IKE + IPsec SA state to that peer; a session that is not in an UP state \"
        \"has no established SA, so the encrypted tunnel forwards no traffic and every site / prefix reachable \"
        \"only across that VPN is cut off. Confirm peer reachability and the ISAKMP/IKEv2 policy, pre-shared \"
        \"key or certificate trustpoint, transform-set / proposal, and the crypto ACL or VTI route match on \"
        \"both ends before the encrypted WAN is relied on at cutover.\",
        len(down), [\"availability\"],
        [\"crypto.sessions[].status (parse_crypto_sessions / show crypto session)\"],
        priority=\"High\",
        driver=\"IPsec encrypted WAN: a crypto session in DOWN / DOWN-NEGOTIATING has no IKE/IPsec SA, so the \"
               \"tunnel is hard down and the sites behind it are unreachable; UP-ACTIVE / UP-IDLE / UP-NO-IKE \"
               \"are established and are not flagged.\",
        devices=sorted({d.split()[0] for d in down})[:12])
```

## fixture_block
```
    # IPsec encrypted-WAN universality: core1 is an IOS site-to-site IPsec hub with two crypto sessions.
    # _d_crypto_session_health FIRES: Tunnel1 -> 10.0.255.9 is DOWN-NEGOTIATING (no established IKE/IPsec SA,
    # the spoke behind it is cut off). The healthy companion Tunnel0 -> 10.0.255.2 is UP-ACTIVE and must NOT
    # fire (proves coverage-honest silence on an established tunnel).
    "show crypto session": """\
Crypto session current status

Interface: Tunnel0
Session status: UP-ACTIVE
Peer: 10.0.255.2 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.2/500 Active
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.20.0/255.255.255.0
        Active SAs: 2, origin: crypto map
Interface: Tunnel1
Session status: DOWN-NEGOTIATING
Peer: 10.0.255.9 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.9/500 Inactive
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.30.0/255.255.255.0
        Active SAs: 0, origin: crypto map
""",
```

## parser_test
```
def test_parse_crypto_sessions_states(cp):
    \"\"\"Universality (IPsec encrypted WAN): parse_crypto_sessions reads 'show crypto session' so a session
    whose 'Session status' begins with DOWN (no established IKE/IPsec SA -> tunnel down) is detectable. Each
    'Interface:' opens a new record; the indented IKE SA / IPSEC FLOW / Active SAs lines never create phantom
    sessions, and the peer is captured without the trailing 'port 500'.\"\"\"
    out = (
        \"Crypto session current status\\n\"
        \"\\n\"
        \"Interface: Tunnel0\\n\"
        \"Session status: UP-ACTIVE\\n\"
        \"Peer: 10.0.255.2 port 500\\n\"
        \"  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.2/500 Active\\n\"
        \"  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.20.0/255.255.255.0\\n\"
        \"        Active SAs: 2, origin: crypto map\\n\"
        \"Interface: Tunnel1\\n\"
        \"Session status: DOWN-NEGOTIATING\\n\"
        \"Peer: 10.0.255.9 port 500\\n\"
        \"  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.9/500 Inactive\\n\"
        \"        Active SAs: 0, origin: crypto map\\n\")
    r = parse.parse_crypto_sessions(out)
    assert len(r) == 2
    assert r[0] == {\"interface\": \"Tunnel0\", \"peer\": \"10.0.255.2\", \"status\": \"UP-ACTIVE\"}
    assert r[1][\"interface\"] == \"Tunnel1\" and r[1][\"peer\"] == \"10.0.255.9\" and r[1][\"status\"] == \"DOWN-NEGOTIATING\"
    assert parse.parse_crypto_sessions(\"\") == []
```

## detector_test
```
def test_d_crypto_session_health_fires_on_down_session_only():
    \"\"\"Universality (IPsec encrypted WAN): a device with a crypto session whose status begins with DOWN
    (DOWN / DOWN-NEGOTIATING -> no established IKE/IPsec SA) fires _d_crypto_session_health. Refutation: every
    UP-* status (UP-ACTIVE passing data, UP-IDLE established-idle, UP-NO-IKE IPsec-up-while-IKE-rekeys) and an
    absent crypto axis all stay silent (coverage-honest).\"\"\"
    import cisco_toolkit.design_advisor as da
    fire = {\"crypto\": {\"hub1\": {\"sessions\": [
        {\"interface\": \"Tunnel0\", \"peer\": \"10.0.255.2\", \"status\": \"UP-ACTIVE\"},
        {\"interface\": \"Tunnel1\", \"peer\": \"10.0.255.9\", \"status\": \"DOWN-NEGOTIATING\"},
    ]}}}
    sig = da._signals(fire)
    assert \"10.0.255.9\" in \" \".join(sig.get(\"crypto_sessions_down\", []))
    dec = da._d_crypto_session_health(fire, sig)
    assert dec is not None and dec[\"priority\"] == \"High\" and \"crypto session\" in str(dec).lower()
    assert \"hub1\" in dec[\"evidence\"][\"devices\"]
    # healthy: UP-ACTIVE, UP-IDLE and UP-NO-IKE are all established tunnels -> silent (no cry-wolf)
    for _ok in (\"UP-ACTIVE\", \"UP-IDLE\", \"UP-NO-IKE\"):
        clean = {\"crypto\": {\"hub1\": {\"sessions\": [{\"interface\": \"Tunnel0\", \"peer\": \"10.0.255.2\", \"status\": _ok}]}}}
        assert da._d_crypto_session_health(clean, da._signals(clean)) is None
    # plain DOWN also fires (not only DOWN-NEGOTIATING)
    hard = {\"crypto\": {\"hub1\": {\"sessions\": [{\"interface\": \"Tunnel2\", \"peer\": \"10.0.255.8\", \"status\": \"DOWN\"}]}}}
    assert da._d_crypto_session_health(hard, da._signals(hard)) is not None
    # absent crypto axis -> silent
    assert da._d_crypto_session_health({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (IPsec encrypted WAN): core1 acts as an IOS site-to-site IPsec hub with a DOWN-NEGOTIATING
    # crypto session (Tunnel1 -> 10.0.255.9). The detector must fire end-to-end; the healthy companion
    # (UP-ACTIVE Tunnel0 -> 10.0.255.2) proves no over-firing.
    assert isinstance(snap.get("crypto"), dict) and snap["crypto"].get("core1", {}).get("sessions"), \
        "snapshot must publish per-device IPsec crypto state (build_crypto -> parse_crypto_sessions)"
    assert any(d.get("id") == "ipsec-crypto-session-down" for d in _bp.get("decisions", [])), \
        "engine must assess IPsec encrypted WAN: a DOWN-NEGOTIATING crypto session must fire _d_crypto_session_health"
```