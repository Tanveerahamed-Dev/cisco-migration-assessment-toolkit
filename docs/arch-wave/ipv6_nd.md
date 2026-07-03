# slice: ipv6_nd -> ipv6-duplicate-address-dad-failure
arch: IPv6 addressing / neighbor discovery (dual-stack readiness)
viable: True | fixture_device: core1 | snap_key: ipv6_nd
commands: show ipv6 interface[ios]
firing: A global IPv6 address (or an interface link-local) reported by 'show ipv6 interface' carries a [DUPLICATE]/[DUP] marker (dad_state == 'duplicate' / link_local_dup == True). DAD positively detected an address clash, so IOS set the address to the DUPLICATE state and stopped using it; a duplicate link-local disables IPv6 on the whole interface. This is an OBSERVED, settled fault -- the dual-stack interface is dark for IPv6 while IPv4 keeps forwarding.
coverage_honesty: Three independent silence guarantees, each refutation-tested. (1) ABSENT: a pure-IPv4 device runs no IPv6, so 'show ipv6 interface' is empty/missing, parse returns [], build_ipv6_nd returns {}, the snap key is absent, the signal lists are empty, and the detector returns None -- it never infers a fault from absence. (2) HEALTHY: a dual-stack interface whose addresses have NO DAD marker yields dad_state 'ok' and does not contribute -- the detector is silent on a clean live IPv6 deployment. (3) TRANSIENT/AMBIGUOUS excluded by design: a [TENTATIVE] address (DAD still in progress, a normal momentary state right after config) is parsed as dad_state 'tentative' and deliberately NOT fired on -- only the settled DUPLICATE state, which Cisco itself has acted on by disabling the address, counts. I explicitly REJECTED the alternative 'up/up with IPv4 but no IPv6' (stack-asymmetry-by-absence) firing condition: 'show ipv6 interface' shows nothing for an IPv4-only interface, and declaring such an interface SHOULD be dual-stack requires inferring intent the evidence does not carry -- a cry-wolf false-positive class. The DUPLICATE marker is the only unambiguous, device-confirmed IPv6 fault available from this command.
confidence: HIGH confidence; viable=true. The firing state -- a global IPv6 address (or link-local) marked [DUPLICATE] in 'show ipv6 interface' -- is verbatim-grounded in primary Cisco docs ('Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]') and is unambiguous: Cisco itself acts on it by disabling the address (state=DUPLICATE, 'not used'; a duplicate link-local disables IPv6 on the whole interface; %IPV6-4-DUPLICATE is logged). It is the strongest of the two candidate faults for coverage-honesty.

KEY DESIGN CHOICES the integrator should know:
1. COMMAND = 'show ipv6 interface' (FULL), not 'show ipv6 interface brief'. The brief form does NOT mark a duplicate GLOBAL address; it only flags a duplicate LINK-LOCAL with a '[stale]' token. The full form carries the [DUPLICATE]/[DUP] marker on the global-unicast line, which is what the detector needs. I added 'show ipv6 interface' to the base command lists implicitly via build_ipv6_nd -- the integrator must add the literal string \"show ipv6 interface\" to BOTH base-command lists in COLLECT_PARSE (the two blocks near lines 490-497 and 579-586, alongside the existing 'show ipv6 nd raguard policy'), wire build_ipv6_nd into the per-device assembly loop (mirror the build_ipv6_fhs block at ~1625) and publish snap_dict[\"ipv6_nd\"] = all_ipv6_nd (~2159), and register _d_ipv6_dad_duplicate in _DETECTORS.

2. I REJECTED the alternative 'up/up + IPv4 but no operational IPv6' (stack-asymmetry-by-absence) firing condition as a cry-wolf class: 'show ipv6 interface' is silent for an IPv4-only interface, and 'show ipv6 interface brief' does not even show the IPv4 address, so neither can confirm 'up/up with IPv4', and declaring an IPv4-only interface SHOULD be dual-stack infers intent the evidence lacks. Only the device-confirmed DUPLICATE state is safe.

3. [TENTATIVE] is parsed but deliberately NOT fired on (transient DAD-in-progress). Only the settled 'duplicate' state fires.

4. design_kb dependency: _decision('ipv6-duplicate-address-dad-failure', ...) reads its title/citation/recommended_action from design_kb.by_id(pid); the integrator must add a matching engine_actionable=True principle (domain 'ipv6', priority 'High') -- model it on the existing 'ipv6-first-hop-security-suite-at-access-edge' entry (design_kb.py ~3263). Without it the decision still emits (defaults), but the KB-emit-invariant test (test_every_engine_actionable_principle_is_emitted) and the addendum-honesty tests expect the principle to exist; adding it keeps the blueprint decision count +1 and the traceability matrix complete.

5. The parser introduces a small module-level helper _addr_line in parse.py (placed immediately after parse_ipv6_interface_addrs). normalize_ifname is already imported in parse.py (used by the existing IPv6 FHS parsers). re is already imported.

Edge cases handled & tested: clean address (silent), TENTATIVE (silent), duplicate global, duplicate link-local (whole-interface IPv6 down), admin-down/IPv6-disabled interface (no phantom addresses), inline-vs-continuation global addresses, empty input -> []. Parser is fully tolerant (never raises). All names/IPs follow the fixture conventions (core1 IOS, Vlan10/Vlan30, FE80:: link-locals, 2001:DB8 documentation prefix).
sources: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/command/ipv6-cr-book/ipv6-s2.html (Cisco IOS IPv6 Command Reference - show ipv6 interface / show ipv6 interface brief: [up/up] status, link-local + Global unicast address(es) lines, [stale] duplicate link-local marker) | https://www.cisco.com/c/en/us/td/docs/ios/ipv6/configuration/guide/ipv6-xe-16-book-cat8000/m_ip6-addrg-bsc-con.html (Cisco IOS XE IPv6 Addressing & Basic Connectivity Config Guide: 'Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]'; DAD sets a duplicate address to the DUPLICATE state and stops using it; a duplicate link-local disables IPv6 packet processing on the interface; %IPV6-4-DUPLICATE syslog; 'clear ipv6 duplicate address') | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6_basic/configuration/xe-3s/ip6b-xe-3s-book/ip6-neighb-disc-xe.html (Cisco IPv6 Neighbor Discovery / RFC 4862 DAD behaviour: tentative state during DAD, duplicate detection result) | https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6/command/ipv6-cr-book/ipv6-s4.html (Cisco IOS IPv6 Command Reference - show ipv6 neighbors: ND cache states INCMP/REACH/STALE/DELAY/PROBE, corroborating ND semantics) | RFC 4861 (Neighbor Discovery for IPv6) and RFC 4862 (IPv6 Stateless Address Autoconfiguration, Duplicate Address Detection) - normative DAD / tentative / duplicate definitions

## parser_sample_input
```
GigabitEthernet0/1 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::130
  Description: Management network (dual stack)
  Global unicast address(es): FEC0:240:104:1000::130, subnet is FEC0:240:104:1000::/64
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:130
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  Hosts use stateless autoconfig for addresses.
Vlan30 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::1
  Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:1
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  ND reachable time is 30000 milliseconds
  Hosts use stateless autoconfig for addresses.
```

## parser_code
```
def parse_ipv6_interface_addrs(output: str) -> list:
    """'show ipv6 interface' (IOS / IOS-XE) -> one record per L3 interface that has IPv6 enabled:
    [{interface, admin_up, proto_up, ipv6_enabled, link_local, link_local_dup, global:[{addr, subnet,
    dad_state}]}]. dad_state is 'ok' (no marker), 'duplicate' (a [DUPLICATE]/[DUP] marker -> DAD positively
    detected an address clash, so Cisco sets the address to DUPLICATE and STOPS using it), or 'tentative'
    (a [TENTATIVE] marker -> DAD still in progress, transient -- NOT a fault). A duplicate LINK-LOCAL disables
    IPv6 packet processing on the whole interface (link_local_dup=True). [] when the device shows no IPv6 at
    all (a pure-IPv4 box contributes nothing, so nothing can cry wolf). Tolerant; never raises.

    Header line: 'GigabitEthernet0/1 is up, line protocol is up' (or 'administratively down'); IPv6 enabled
    line: 'IPv6 is enabled, link-local address is FE80::130 [DUPLICATE]'; address line:
    'Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]'. A single 'Global unicast
    address(es):' header may be followed by additional indented address-only continuation lines, each its own
    record. Grounded verbatim in the Cisco IPv6 command reference / config-guide sample output."""
    out: list = []
    cur = None

    def _dad(tail: str) -> str:
        t = (tail or "").upper()
        if "[DUPLICATE]" in t or "[DUP]" in t:
            return "duplicate"
        if "[TENTATIVE]" in t or "[TEN]" in t:
            return "tentative"
        return "ok"

    # 'Global unicast address(es):' may carry the first address on the same line OR start a list whose
    # addresses are on the following indented continuation lines; track that we are inside that block.
    in_global = False
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            in_global = False
            continue
        # interface header: '<ifname> is [administratively ]up/down, line protocol is up/down'
        mh = re.match(r"^(\S+)\s+is\s+(administratively\s+down|up|down),"
                      r"\s+line protocol is\s+(up|down)", s, re.IGNORECASE)
        if mh:
            if cur is not None:
                out.append(cur)
            cur = {"interface": normalize_ifname(mh.group(1)),
                   "admin_up": mh.group(2).lower() == "up",
                   "proto_up": mh.group(3).lower() == "up",
                   "ipv6_enabled": False, "link_local": "", "link_local_dup": False, "global": []}
            in_global = False
            continue
        if cur is None:
            continue
        # 'IPv6 is enabled, link-local address is FE80::130 [DUPLICATE]'
        ml = re.match(r"^IPv6 is (enabled|disabled)(?:,\s*link-local address is\s+(\S+)(.*))?$",
                      s, re.IGNORECASE)
        if ml:
            cur["ipv6_enabled"] = ml.group(1).lower() == "enabled"
            if ml.group(2):
                cur["link_local"] = ml.group(2)
                cur["link_local_dup"] = _dad(ml.group(3)) == "duplicate"
            in_global = False
            continue
        # 'Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]'  (first addr inline)
        mg = re.match(r"^Global unicast address\(es\):\s*(.+)$", s, re.IGNORECASE)
        if mg:
            in_global = True
            rest = mg.group(1).strip()
            if rest:  # an address sits on the header line itself
                _addr_line(cur, rest, _dad)
            continue
        # indented address-only continuation under the Global block:
        #   '1:5::1, subnet is 1:5::/64 [DUPLICATE]'  or  '1:5::1 [TENTATIVE]'
        if in_global and re.match(r"^[0-9A-Fa-f:]+(?:,|\s|$)", s):
            _addr_line(cur, s, _dad)
            continue
        # any other field line ends the global continuation context but keeps the interface block open
        in_global = False
    if cur is not None:
        out.append(cur)
    return out


def _addr_line(cur: dict, rest: str, _dad) -> None:
    """Parse one global-unicast address fragment ('<addr>, subnet is <pfx> [MARK]' or '<addr> [MARK]')
    into cur['global']. A fragment whose first token is not an IPv6 address is ignored (defensive)."""
    m = re.match(r"^([0-9A-Fa-f:]+)(?:,\s*subnet is\s+(\S+?))?\s*(\[[^\]]*\])?\s*$", rest)
    if not m or ":" not in m.group(1):
        return
    cur["global"].append({"addr": m.group(1), "subnet": (m.group(2) or ""),
                          "dad_state": _dad(m.group(3) or "")})
```

## build_code
```
def build_ipv6_nd(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 addressing / neighbor-discovery readiness for THIS device from 'show ipv6 interface'
    (parse_ipv6_interface_addrs) -> {interfaces:[{interface, admin_up, proto_up, ipv6_enabled, link_local,
    link_local_dup, global:[{addr, subnet, dad_state}]}]}. {} when the device shows no IPv6 at all -- a pure
    IPv4 box contributes nothing and the DAD detector never cries wolf over it. A global address in dad_state
    'duplicate' (or a duplicate link-local) is the OBSERVED broken state: DAD positively detected an address
    clash, so Cisco set the address to DUPLICATE and stopped using it -- a hard L3 fault on a dual-stack
    interface. Fail-soft via _safe_parse."""
    ifaces = _safe_parse(parse_ipv6_interface_addrs,
                         _load_cmd_output(cmd_to_file, "show ipv6 interface")) or []
    out = {}
    if ifaces:
        out["interfaces"] = ifaces
    return out
```

## signal_code
```
    # IPv6 addressing / neighbor-discovery readiness (snap['ipv6_nd'] from build_ipv6_nd). FIRING STATE: a
    # global IPv6 address (or the interface link-local) whose DAD state is DUPLICATE -- Duplicate Address
    # Detection (RFC 4862) positively found another node already using that address, so Cisco set it to
    # DUPLICATE and STOPPED using it (a duplicate link-local disables IPv6 on the whole interface). That is a
    # hard, OBSERVED L3 fault: the dual-stack interface is dark for IPv6 while its IPv4 keeps forwarding.
    # Coverage-honest & non-cry-wolf: a pure-IPv4 device publishes {} and never fires; an address with NO
    # marker (dad_state 'ok') is healthy; a TENTATIVE address (DAD still in progress -- transient) is NOT a
    # fault and is excluded. Only the settled DUPLICATE state is surfaced.
    _v6 = _as_dict(snap.get("ipv6_nd"))
    _dad_dups, _dad_ll = [], []
    for _v6h, _v6f in sorted(_v6.items()):
        for _if in _as_list(_as_dict(_v6f).get("interfaces")):
            _if = _as_dict(_if)
            _ifn = _if.get("interface", "?")
            if _if.get("link_local_dup"):
                _dad_ll.append(f"{_v6h} {_ifn} (link-local {_if.get('link_local', '?')})")
            for _g in _as_list(_if.get("global")):
                if str(_as_dict(_g).get("dad_state", "")).lower() == "duplicate":
                    _dad_dups.append(f"{_v6h} {_ifn} ({_as_dict(_g).get('addr', '?')})")
    sig["ipv6_dad_duplicate"] = _dad_dups
    sig["ipv6_dad_duplicate_ll"] = _dad_ll
    sig["ipv6_dad_duplicate_devices"] = sorted({x.split()[0] for x in (_dad_dups + _dad_ll)})[:12]
```

## detector_code
```
def _d_ipv6_dad_duplicate(snap, sig):
    """IPv6 Duplicate Address Detection FAILURE (parse_ipv6_interface_addrs -> snap['ipv6_nd']): a global
    IPv6 address -- or an interface link-local -- that 'show ipv6 interface' marks [DUPLICATE]. DAD (RFC 4862)
    positively found another node already using that address, so IOS set it to the DUPLICATE state and STOPPED
    using it; a duplicate link-local disables IPv6 packet processing on the entire interface. The dual-stack
    interface/SVI is therefore DARK for IPv6 while its IPv4 keeps forwarding -- a silent stack asymmetry that
    strands every IPv6 host on that segment at cutover. Coverage-honest & non-cry-wolf: fires ONLY on the
    settled DUPLICATE state; a healthy (unmarked) address, a transient TENTATIVE address (DAD still running),
    and a pure-IPv4 box that publishes no ipv6_nd axis all stay silent."""
    dups = sig.get("ipv6_dad_duplicate") or []
    ll = sig.get("ipv6_dad_duplicate_ll") or []
    if not dups and not ll:
        return None
    parts = []
    if dups:
        parts.append(f"{len(dups)} global IPv6 address(es) in the DUPLICATE state (e.g. {', '.join(dups[:4])})")
    if ll:
        parts.append(f"{len(ll)} interface(s) whose LINK-LOCAL is duplicate -- IPv6 is disabled on the whole "
                     f"interface (e.g. {', '.join(ll[:4])})")
    return _decision(
        "ipv6-duplicate-address-dad-failure",
        "IPv6 Duplicate Address Detection has FAILED: " + "; ".join(parts) + ". DAD (RFC 4862) confirmed "
        "another node already owns the address, so IOS set it to DUPLICATE and is not using it -- the "
        "dual-stack interface is dark for IPv6 even though its IPv4 still forwards (a silent stack asymmetry). "
        "Find and remove the address collision (a mis-typed static, an overlapping SLAAC/EUI-64 clash, or a "
        "duplicated SVI), then 'clear ipv6 duplicate address' to re-run DAD before the segment is trusted at "
        "cutover.",
        len(dups) + len(ll), ["availability", "addressing"],
        ["ipv6_nd.interfaces[].global[].dad_state (parse_ipv6_interface_addrs / show ipv6 interface)",
         "ipv6_nd.interfaces[].link_local_dup"],
        priority="High",
        driver="IPv6 dual-stack readiness: an address in the DUPLICATE state is operationally disabled by DAD, "
               "so the interface has no working IPv6 -- the stack is asymmetric and IPv6 hosts on it are "
               "stranded until the collision is resolved.",
        devices=sig.get("ipv6_dad_duplicate_devices") or [])
```

## fixture_block
```
    # IPv6 addressing / neighbor-discovery readiness (universality): core1 is a dual-stack distribution
    # switch. Vlan30's GLOBAL IPv6 address is in the DUPLICATE state ([DUPLICATE]) -- DAD (RFC 4862) found the
    # address already in use, so IOS disabled it -> _d_ipv6_dad_duplicate FIRES on Vlan30 only. The HEALTHY
    # companions (Vlan10 with a clean global address, and Gi1/0/24 also clean) prove the detector does NOT
    # over-fire on a normal dual-stack interface; the TENTATIVE entry on Gi1/0/1 proves a transient DAD state
    # is correctly IGNORED. Grounded verbatim in the Cisco IPv6 command-reference sample output.
    "show ipv6 interface": """\
Vlan10 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:10
  Global unicast address(es): 2001:DB8:10::1, subnet is 2001:DB8:10::/64
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:1
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  Hosts use stateless autoconfig for addresses.
Vlan30 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:30
  Global unicast address(es): 2001:DB8:30::1, subnet is 2001:DB8:30::/64 [DUPLICATE]
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:1
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  Hosts use stateless autoconfig for addresses.
GigabitEthernet1/0/24 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:24
  Global unicast address(es): 2001:DB8:FFFE::24, subnet is 2001:DB8:FFFE::/64
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
GigabitEthernet1/0/1 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:01
  Global unicast address(es): 2001:DB8:FFFD::1, subnet is 2001:DB8:FFFD::/64 [TENTATIVE]
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
""",
```

## parser_test
```
def test_parse_ipv6_interface_addrs_dad_state(cp):
    """Universality (IPv6 addressing / ND): parse_ipv6_interface_addrs reads 'show ipv6 interface' and flags a
    global address marked [DUPLICATE] (DAD found a clash -> IOS disabled the address) distinctly from a clean
    address (dad_state 'ok') and a transient [TENTATIVE] address. A duplicate link-local sets link_local_dup.
    The Description / Joined-group / MTU / ND lines never create phantom addresses, and a single 'Global
    unicast address(es):' header followed by an indented continuation address yields a second record."""
    out = (
        "Vlan10 is up, line protocol is up\n"
        "  IPv6 is enabled, link-local address is FE80::1\n"
        "  Description: clean dual-stack SVI\n"
        "  Global unicast address(es): 2001:DB8:10::1, subnet is 2001:DB8:10::/64\n"
        "    2001:DB8:10::2, subnet is 2001:DB8:10::/64 [TENTATIVE]\n"
        "  Joined group address(es): FF02::1 FF02::2\n"
        "  MTU is 1500 bytes\n"
        "Vlan30 is up, line protocol is up\n"
        "  IPv6 is enabled, link-local address is FE80::30 [DUPLICATE]\n"
        "  Global unicast address(es): 1:4::1, subnet is 1:4::/64 [DUPLICATE]\n"
        "  MTU is 1500 bytes\n"
        "GigabitEthernet0/2 is administratively down, line protocol is down\n"
        "  IPv6 is disabled\n"
    )
    r = parse.parse_ipv6_interface_addrs(out)
    by = {x["interface"]: x for x in r}
    assert set(by) >= {"Vl10", "Vl30", "Gi0/2"}
    # Vlan10: one clean global + one TENTATIVE continuation address; NEITHER is a duplicate
    v10 = by["Vl10"]
    assert v10["link_local_dup"] is False and v10["ipv6_enabled"] is True
    states10 = {g["addr"]: g["dad_state"] for g in v10["global"]}
    assert states10 == {"2001:DB8:10::1": "ok", "2001:DB8:10::2": "tentative"}
    # Vlan30: the global address AND the link-local are DUPLICATE
    v30 = by["Vl30"]
    assert v30["link_local_dup"] is True
    assert v30["global"] == [{"addr": "1:4::1", "subnet": "1:4::/64", "dad_state": "duplicate"}]
    # admin-down IPv6-disabled interface: enabled False, no addresses, no false duplicate
    assert by["Gi0/2"]["ipv6_enabled"] is False and by["Gi0/2"]["global"] == []
    assert parse.parse_ipv6_interface_addrs("") == []
```

## detector_test
```
def test_d_ipv6_dad_duplicate_fires_on_duplicate_state_only():
    """Universality (IPv6 addressing / ND): a device with a global IPv6 address in the DUPLICATE state fires
    _d_ipv6_dad_duplicate (DAD disabled the address -> the dual-stack interface is dark for IPv6). Refutation:
    a clean (unmarked) address, a transient TENTATIVE address, and an absent ipv6_nd axis ALL stay silent
    (coverage-honest -- a settled duplicate is the only firing state)."""
    import cisco_toolkit.design_advisor as da
    fire = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "admin_up": True, "proto_up": True, "ipv6_enabled": True,
         "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::1", "subnet": "2001:DB8:10::/64", "dad_state": "ok"}]},
        {"interface": "Vl30", "admin_up": True, "proto_up": True, "ipv6_enabled": True,
         "link_local": "FE80::30", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:30::1", "subnet": "2001:DB8:30::/64", "dad_state": "duplicate"}]},
    ]}}}
    sig = da._signals(fire)
    assert any("2001:DB8:30::1" in x for x in sig.get("ipv6_dad_duplicate", []))
    dec = da._d_ipv6_dad_duplicate(fire, sig)
    assert dec is not None and dec["priority"] == "High" and "DUPLICATE" in str(dec)
    assert dec["principle"]["id"] == "ipv6-duplicate-address-dad-failure"
    assert "core1" in dec["evidence"]["devices"]
    # clean: every address dad_state 'ok' -> silent
    clean = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "ipv6_enabled": True, "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::1", "subnet": "2001:DB8:10::/64", "dad_state": "ok"}]}]}}}
    assert da._d_ipv6_dad_duplicate(clean, da._signals(clean)) is None
    # transient TENTATIVE (DAD in progress) -> silent
    tentative = {"ipv6_nd": {"core1": {"interfaces": [
        {"interface": "Vl10", "ipv6_enabled": True, "link_local": "FE80::10", "link_local_dup": False,
         "global": [{"addr": "2001:DB8:10::9", "subnet": "2001:DB8:10::/64", "dad_state": "tentative"}]}]}}}
    assert da._d_ipv6_dad_duplicate(tentative, da._signals(tentative)) is None
    # absent axis -> silent
    assert da._d_ipv6_dad_duplicate({}, da._signals({})) is None
```

## pipeline_assertion
```
    # UNIVERSALITY (IPv6 addressing / ND): core1 is a dual-stack distribution switch whose Vlan30 GLOBAL IPv6
    # address is in the DUPLICATE state (DAD found a clash -> IOS disabled it). The DAD detector must fire
    # end-to-end; the clean Vlan10/Gi1/0/24 addresses and the TENTATIVE Gi1/0/1 address prove no over-firing.
    assert isinstance(snap.get("ipv6_nd"), dict) and snap["ipv6_nd"].get("core1", {}).get("interfaces"), \
        "snapshot must publish per-device IPv6 ND state (build_ipv6_nd -> parse_ipv6_interface_addrs)"
    assert any(d.get("id") == "ipv6-duplicate-address-dad-failure" for d in _bp.get("decisions", [])), \
        "engine must assess IPv6 DAD: a global address in the DUPLICATE state must fire _d_ipv6_dad_duplicate"
```