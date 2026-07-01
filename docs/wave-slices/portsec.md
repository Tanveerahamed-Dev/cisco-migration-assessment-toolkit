## buildable
needs-collection

## unit_tests_green
True

## firing_condition
An access port whose `show port-security interface` detail reports `Port Status : Secure-shutdown` -- i.e. a port-security-secured port currently err-disabled by a violation (shutdown-mode). This is a live access outage: ALL traffic on the port is dropped incl. the authorized endpoint, with an evidenced offending MAC (Last Source Address). It deliberately does NOT fire on a nonzero `Security Violation Count` alone, because Restrict/Protect modes keep the port Secure-up and legitimately accumulate violations while forwarding -- only the Shutdown STATE is a fault, not the counter.

## collection_command
show port-security interface

## snapshot_axis
port_security

## fixture_device
access1

## notes
WORKTREE COMMIT MISMATCH (resolved): the task said HEAD=fa9739e, but the worktree was actually checked out at the OLDER divergent commit 1a7f889 (#267), where design_advisor.py / parse_hsrp_detail / build_fhrp_detail did NOT exist. I confirmed fa9739e exists in the object store, that it is the 'feat(assess): multi-architecture coverage -- FHRP + full VXLAN-EVPN' commit holding the reference slices, and `git checkout fa9739e`'d the worktree to it before building. The orchestrator should integrate against fa9739e (or its descendant), not 1a7f889. Side-effect: CLAUDE.md was restored to its full doctrine form by the checkout (it had been stripped in 1a7f889).

VALIDATION: ran the two new tests green individually; full suite = 575 passed / 0 failed after I regenerated the golden (UPDATE_GOLDEN=1) -- the ONLY pipeline-golden delta is the single additive top-level key 'port_security' (+28 lines, 0 deletions, zero churn to any pre-existing section). I left the regenerated tests/golden/snapshot.json in the worktree so it is fully green; if the orchestrator prefers to own the regen it can `git checkout tests/golden/snapshot.json` and re-run UPDATE_GOLDEN=1 -- the result is deterministic. Proven end-to-end via a real `--no-collect` subprocess: snap['port_security'] is published AND snap['design_blueprint'].decisions contains the new 'security-l2-access-edge-suite' decision (High/security, 25 decisions total), with the [PSEC] collection log line firing.

DESIGN CHOICES: (1) reused the EXISTING design_kb principle 'security-l2-access-edge-suite' as the _decision pid -- title/citation/recommended_action/alternatives/tradeoffs are pulled from it automatically, exactly like _d_fhrp cites 'fhrp-first-hop-gateway-redundancy'. (2) That principle is currently engine_actionable=False (in the _NOT_YET_AUTO_DETECTED set, comment 'no port-security ... finding collected'). I intentionally did NOT flip it true: my detector fires on a narrow sub-symptom (a single port-security err-disable), not the full L2-edge suite the principle describes (DHCP-snooping + DAI + IPSG + storm-control + 802.1X), so auto-marking the whole principle actionable would over-claim. The orchestrator can optionally remove it from _NOT_YET_AUTO_DETECTED and refresh that now-partially-stale comment. (3) The pre-existing parse_port_security (summary) + excel.py Security-Posture sheet are untouched and complementary -- they lack the Port-Status column, which is precisely the gap this detail slice fills. (4) Both COMMANDS_NXOS and COMMANDS_IOS got the new command because the offline --no-collect path unions both lists and maps each base-list command to its on-disk filename (`show port-security interface` -> show_port-security_interface.txt); a command only in one list would be invisible offline for the other platform.

## sources
['https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/s1/sec-s1-cr-book/sec-cr-s6.html', 'https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst6500/ios/15-4SY/config_guide/sup6T/15_3_sy_swcg_6T/port_security.pdf', 'https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/7-x/security/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_Security_Configuration_Guide_7x/b_Cisco_Nexus_9000_Series_NX-OS_Security_Configuration_Guide_7x_chapter_010101.html', 'https://study-ccna.com/cisco-port-security-violation-configuration/', 'https://learningnetwork.cisco.com/s/question/0D53i00000Kt1EvCAJ/port-status-in-the-output-of-show-portsecurity']

## parser_code
```python
def parse_port_security_detail(output: str) -> Dict[str, dict]:
    """Per-interface 'show port-security interface [<if>]' DETAIL -> {ifname: {enabled, port_status,
    violation_mode, violation_count, last_src, last_vlan}}. The summary parser (parse_port_security)
    keeps only max/current/violations/action and -- critically -- has NO port-status column, so it
    cannot tell an err-disabled (Secure-shutdown) port from a healthy one. This detail form carries
    the operational state a senior access-edge audit needs: a violation in 'shutdown' mode err-disables
    the port (Port Status -> 'Secure-shutdown'), stopping ALL traffic incl. authorized devices, whereas
    'restrict'/'protect' keep the port up (Secure-up) and merely drop+count -- so only Secure-shutdown
    is a live outage, not a raw nonzero counter (which restrict/protect legitimately accumulate).

    Each block starts at the 'Port Security :' line; the interface identity is taken from the nearest
    preceding interface header (a bare interface token, or a 'Port:' / 'Secure Port:' / 'Interface:'
    label) -- the detail body itself does not echo the interface name. Tolerant: {} on empty /
    non-detail input; never raises. port_status is lower-cased canonical ('secure-shutdown',
    'secure-up', 'secure-down')."""
    res: Dict[str, dict] = {}
    cur: Optional[str] = None      # interface name carried forward from the most recent header
    pend: Optional[str] = None     # an interface header seen but not yet bound to a block
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        # An interface header may arrive as a bare token (e.g. a collector that prefixes each block
        # with the port) or as 'Port:'/'Secure Port:'/'Interface: <if>'. Remember it until the block
        # body (the 'Port Security :' line) opens, so the body's fields attach to the right port.
        hm = re.match(r"^(?:Secure\s+Port|Port|Interface)\s*[:=]\s*(\S+)\s*$", s, re.IGNORECASE)
        if hm and is_valid_iface(hm.group(1)):
            pend = normalize_ifname(hm.group(1)); continue
        bare = re.match(r"^(\S+)$", s)
        if bare and is_valid_iface(bare.group(1)) and PHYSICAL_IFACE_RE.match(normalize_ifname(bare.group(1))):
            pend = normalize_ifname(bare.group(1)); continue
        m = re.match(r"^Port\s+Security\s*[:=]\s*(\w+)", s, re.IGNORECASE)
        if m:
            cur = pend or cur
            pend = None
            if cur is None:
                continue
            res.setdefault(cur, {"enabled": False, "port_status": "", "violation_mode": "",
                                 "violation_count": 0, "last_src": "", "last_vlan": ""})
            res[cur]["enabled"] = m.group(1).strip().lower() == "enabled"
            continue
        if cur is None or cur not in res:
            continue
        r = res[cur]
        m = re.match(r"^Port\s+Status\s*[:=]\s*(\S+)", s, re.IGNORECASE)
        if m: r["port_status"] = m.group(1).strip().lower(); continue
        m = re.match(r"^Violation\s+Mode\s*[:=]\s*(\w+)", s, re.IGNORECASE)
        if m: r["violation_mode"] = m.group(1).strip().capitalize(); continue
        m = re.match(r"^Security\s+Violation\s+Count\s*[:=]\s*(\d+)", s, re.IGNORECASE)
        if m: r["violation_count"] = int(m.group(1)); continue
        m = re.match(r"^Last\s+Source\s+Address(?::Vlan)?\s*[:=]\s*([0-9a-fA-F.:]+?)(?::(\d+))?\s*$", s, re.IGNORECASE)
        if m:
            r["last_src"] = m.group(1)
            if m.group(2): r["last_vlan"] = m.group(2)
            continue
    return res
```

## build_code
```python
def build_port_security_detail(cmd_to_file: Dict[str, str]) -> dict:
    """Access-edge port-security state for THIS device from 'show port-security interface' DETAIL
    (parse_port_security_detail): {ifname: {enabled, port_status, violation_mode, violation_count,
    last_src, last_vlan}}. {} when the device runs no port-security or the detail form was not
    collected. The summary form (build's excel Security-Posture sheet) keeps only max/current/
    violations/action and has NO port-status column, so an err-disabled (Secure-shutdown) secured
    port -- a live access outage -- was previously invisible to the design layer. Fail-soft via
    _safe_parse."""
    return _safe_parse(parse_port_security_detail,
                       _load_cmd_output(cmd_to_file, "show port-security interface")) or {}

# build.py import line also updated (added to the existing `from cisco_toolkit.parse import (...)` block):
#     parse_port_security_detail,                                      # access-edge port-security DETAIL (Secure-shutdown)
```

## signal_code
```python
# inserted in design_advisor._signals(), immediately after the sig["nve_vni_down"] block:
    # ACCESS-EDGE port-security from the published detail axis (parse_port_security_detail ->
    # snap['port_security']): a secured port currently err-disabled by a violation (Port Status
    # 'secure-shutdown') is a LIVE access outage -- all traffic stopped, incl. authorized hosts.
    # Coverage-honest + non-cry-wolf: a raw violation COUNT is NOT flagged (restrict/protect modes
    # keep the port up and legitimately accumulate violations); only the shutdown state fires. Empty
    # when the detail axis is absent.
    sig["psec_errdisabled"] = []
    _ps = snap.get("port_security")
    for _host, _ports in (_ps.items() if isinstance(_ps, dict) else []):
        for _if, _pd in (_ports.items() if isinstance(_ports, dict) else []):
            if str((_pd or {}).get("port_status", "")).lower() == "secure-shutdown":
                _mac = (_pd or {}).get("last_src") or "?"
                sig["psec_errdisabled"].append(f"{_host} {_if} (offender {_mac})")
```

## detector_code
```python
def _d_port_security_errdisable(snap, sig):
    """Access-edge port-security red flag from the 'show port-security interface' DETAIL
    (parse_port_security_detail -> snap['port_security']): a secured access port currently in the
    'Secure-shutdown' (err-disabled) state because a port-security violation tripped a shutdown-mode
    port -- ALL traffic on that port is dropped, including the authorized endpoint, so it is a live
    access outage that must be triaged (and the offending MAC investigated) before cutover, not
    carried into the target design. Coverage-honest + non-cry-wolf: silent when the detail axis is
    absent or every secured port is up; a raw nonzero violation counter is deliberately NOT flagged
    here -- restrict/protect modes keep the port forwarding while counting, so only the shutdown
    STATE is a fault, not the count."""
    bad = sig.get("psec_errdisabled") or []
    if not bad:
        return None
    return _decision(
        "security-l2-access-edge-suite",
        f"{len(bad)} access port(s) are ERR-DISABLED by a port-security violation (Port Status "
        f"Secure-shutdown): {', '.join(bad[:8])}. A shutdown-mode violation drops ALL traffic on the "
        f"port -- including the authorized endpoint -- so each is a live access outage with an evidenced "
        f"offending MAC. Triage the violation (rogue device, MAC move, or a too-tight max), clear "
        f"err-disable, and right-size port-security (sticky/MAC limits) before the migration baseline.",
        len(bad), ["security", "availability"],
        ["port_security[host][if].port_status (parse_port_security_detail / show port-security interface)",
         "port_security[host][if].last_src"],
        priority="High",
        driver="Access-edge integrity: a port-security shutdown is a real outage of a user/endpoint port; "
               "an unexplained violation may also be an active L2 attack (MAC flooding / rogue device).",
        devices=sorted({b.split()[0] for b in bad})[:12])

# registered in _DETECTORS, immediately after _d_nve_vni_health:
# _DETECTORS = [_d_fhrp, _d_fhrp_state, _d_fhrp_resilience, _d_nve_peer_health, _d_evpn_rr_health,
#               _d_nve_vni_health, _d_port_security_errdisable, _d_spof, _d_eol, ...]
```

## fixture_block
```python
    # ACCESS-EDGE port-security DETAIL (universality): Gi0/3 (the phone port) is ERR-DISABLED by a
    # shutdown-mode violation -> Port Status 'Secure-shutdown' -> _d_port_security_errdisable FIRES,
    # naming the offending MAC. Gi0/2 is a clean Secure-up port, and Gi0/10 is in RESTRICT mode with a
    # nonzero violation COUNT but stays Secure-up -- it must NOT fire (proves the detector keys on the
    # shutdown STATE, not the counter; restrict/protect legitimately accumulate violations while up).
    # The interface name precedes each block (collector convention; the detail body omits it).
    "show port-security interface": """\
Port: GigabitEthernet0/2
Port Security              : Enabled
Port Status                : Secure-up
Violation Mode             : Shutdown
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 2
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : aabb.ccdd.ee01:10
Security Violation Count   : 0

Port: GigabitEthernet0/3
Port Security              : Enabled
Port Status                : Secure-shutdown
Violation Mode             : Shutdown
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 1
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : 0011.22aa.0099:10
Security Violation Count   : 3

Port: GigabitEthernet0/10
Port Security              : Enabled
Port Status                : Secure-up
Violation Mode             : Restrict
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 1
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : aabb.ccdd.ee10:30
Security Violation Count   : 17
""",
```

## test_code
```python
# --- tests/test_parsers.py (appended after test_parse_nve_vni_states) ---
def test_parse_port_security_detail_secure_shutdown_vs_restrict(cp):
    """Universality (access-edge port-security): the summary parser has NO port-status column, so an
    err-disabled secured port is invisible. parse_port_security_detail reads 'show port-security
    interface' DETAIL so the operational state is captured: a shutdown-mode violation -> Port Status
    'secure-shutdown' (a live outage with an offending MAC), distinct from a restrict-mode port that
    stays 'secure-up' while merely counting violations. The interface name precedes each block."""
    out = (
        "Port: GigabitEthernet0/3\n"
        "Port Security              : Enabled\n"
        "Port Status                : Secure-shutdown\n"
        "Violation Mode             : Shutdown\n"
        "Maximum MAC Addresses      : 1\n"
        "Last Source Address:Vlan   : 0011.22aa.0099:10\n"
        "Security Violation Count   : 3\n"
        "Port: GigabitEthernet0/10\n"
        "Port Security              : Enabled\n"
        "Port Status                : Secure-up\n"
        "Violation Mode             : Restrict\n"
        "Last Source Address:Vlan   : aabb.ccdd.ee10:30\n"
        "Security Violation Count   : 17\n")
    r = parse.parse_port_security_detail(out)
    assert set(r) == {"Gi0/3", "Gi0/10"}
    g3 = r["Gi0/3"]
    # the senior red flag: a secured access port currently err-disabled by a shutdown-mode violation
    assert g3["enabled"] is True and g3["port_status"] == "secure-shutdown"
    assert g3["violation_mode"] == "Shutdown" and g3["violation_count"] == 3
    assert g3["last_src"] == "0011.22aa.0099" and g3["last_vlan"] == "10"
    # the non-cry-wolf control: restrict mode stays UP and just counts -> must read secure-up, not a fault
    g10 = r["Gi0/10"]
    assert g10["port_status"] == "secure-up" and g10["violation_mode"] == "Restrict" and g10["violation_count"] == 17
    assert parse.parse_port_security_detail("") == {}
    assert parse.parse_port_security_detail("random noise\nnot a detail block") == {}


# --- tests/test_design_blueprint.py (appended after test_d_fhrp_resilience...) ---
def test_d_port_security_errdisable_fires_on_secure_shutdown_not_on_restrict_count():
    """Universality (access-edge port-security): a secured access port currently err-disabled by a
    shutdown-mode violation (Port Status 'secure-shutdown') is a live outage -> _d_port_security_errdisable
    fires, naming the offending MAC. Non-cry-wolf: a restrict-mode port that stays 'secure-up' while merely
    accumulating a violation COUNT must be SILENT (the counter is not a fault); an absent axis is silent too."""
    import cisco_toolkit.design_advisor as da
    snap = {"port_security": {"access1": {
        "Gi0/2":  {"port_status": "secure-up",       "violation_mode": "Shutdown", "violation_count": 0,  "last_src": "aabb.ccdd.ee01"},  # clean
        "Gi0/3":  {"port_status": "secure-shutdown",  "violation_mode": "Shutdown", "violation_count": 3,  "last_src": "0011.22aa.0099"},  # err-disabled
        "Gi0/10": {"port_status": "secure-up",        "violation_mode": "Restrict", "violation_count": 17, "last_src": "aabb.ccdd.ee10"},  # restrict, up -> NOT a fault
    }}}
    sig = da._signals(snap)
    assert sig["psec_errdisabled"] == ["access1 Gi0/3 (offender 0011.22aa.0099)"]
    dec = da._d_port_security_errdisable(snap, sig)
    assert dec is not None and "Secure-shutdown" in str(dec) and "0011.22aa.0099" in str(dec)
    assert dec["priority"] == "High" and dec["evidence"]["devices"] == ["access1"]
    # non-cry-wolf: a restrict/protect port with a large violation count but still up -> silent
    restrict_only = {"port_security": {"access1": {"Gi0/10": {"port_status": "secure-up", "violation_mode": "Restrict", "violation_count": 99}}}}
    assert da._d_port_security_errdisable(restrict_only, da._signals(restrict_only)) is None
    # coverage-honest: the axis absent entirely -> silent
    assert da._d_port_security_errdisable({}, da._signals({})) is None
```
