## buildable
yes

## unit_tests_green
True

## firing_condition
A switch that is OBSERVABLY dual-stack (>=1 IPv6-addressed SVI in running-config) AND owns at least one host-facing access port (switchport_mode=='Access') AND has NO RA-Guard applied anywhere on the device (no global RA-Guard policy attached to a PORT/VLAN target, and no interface-level 'ipv6 nd raguard'). This is a broken security STATE on a live IPv6 access segment (rogue-RA default-gateway hijack -> MITM/DoS, RFC 6104), not blanket absence: pure-IPv4 switches and dual-stack switches that already have RA-Guard stay silent. DHCPv6-Guard absence is reported as a secondary signal (sig['ipv6_fhs_open_dhcp']) but RA-Guard is the gating primary.

## collection_command
show ipv6 nd raguard policy
show ipv6 dhcp guard policy

## snapshot_axis
ipv6_fhs

## fixture_device
access1

## notes
BUILDABLE=yes and SHIPPED end-to-end in the worktree. Full suite re-run is 100% GREEN after the golden was regenerated (UPDATE_GOLDEN=1): 0 failures, exit 0. The 5 new/guarding tests pass in isolation (2 parser + 1 detector with 4 refutation arms + emit-invariant + actionable-addendum guard).

KEY DISCOVERY — this is an ACTIONABLE PIVOT, not a brand-new principle. The KB already shipped `ipv6-first-hop-security-suite-at-access-edge` as reference doctrine (engine_actionable=false, "Not collected by an L1-L4 assessment"). The slice makes it FIRE. Two coverage-honesty LOCKS guard the KB and both had to be satisfied (the orchestrator must keep these green when integrating):
  1. test_every_engine_actionable_principle_is_emitted — every engine_actionable principle must be emitted on _maximal_snap(); I added an ipv6_fhs record to _maximal_snap (host acc10 already has an Access port).
  2. test_mega_corpus_addendum_..._coverage_honest — asserts EVERY _MEGA_CORPUS_ADDENDUM principle is engine_actionable=False. The FHS principle lived there, so I MOVED it into _ACTIONABLE_DETECTOR_ADDENDUM (all True) and bumped that addendum's guard test from len==7 to ==8 and seeded its _fires_all() fixture. (These two design_kb/test edits are part of the slice and are reflected in the diff; an orchestrator that regenerates from a clean fa9739e tree must re-apply them, or simply take the whole worktree diff.)

NON-CRY-WOLF design rationale (web-grounded, RFC 6104 / RFC 4861): "no RA-Guard anywhere" alone would fire on every legacy IPv4 fleet that never deployed IPv6 — pure noise. The gate is therefore (dualstack via an observed IPv6 SVI) AND (host-facing access ports) AND (no RA-Guard attached anywhere). A defined-but-UNATTACHED policy is correctly treated as NOT protecting. Verified silence on: pure-IPv4 switch, RA-Guard-present switch, core/transit (no access ports), and absent axis.

EXPECTED GOLDEN DRIFT (regenerated, verified to be ONLY this): snapshot.json gains the `ipv6_fhs` top-level key + access1's FHS record; sheet_schema.json QoS-Audit + Software-risk headers move "1 of 3" -> "2 of 3" device(s) because access1 now carries a full `show running-config` (it needed one for the dual-stack evidence; it previously had only the |section ^interface slice), making it config-assessable. No logic drift.

PLATFORM HONESTY: the parser tolerates IOS/IOS-XE policy output AND the NX-OS form; NX-OS RA-Guard is platform-limited (e.g. N9300-GX from 10.1(1), ingress/hardware only), so the run-config-based dual-stack + interface-attach path is the robust signal and the slice degrades gracefully when the dedicated show-commands are unsupported/uncollected. COLLECT_PARSE wiring added both commands to COMMANDS_IOS and COMMANDS_NXOS, plus the import + accumulator init/loop/publish (all four sites mirror all_overlay).

The Meridian reference fleet runs no observed IPv6 SVIs in the canonical snapshot, so on Meridian this detector correctly stays silent (coverage-honest) — it adds a new capability proven on the synthetic fixture (access1), exactly like _d_fhrp_resilience/_d_nve_peer_health were first proven off-Meridian.

## sources
['https://networklessons.com/ipv6/ipv6-ra-guard', 'https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/xe-3e/dhcp-xe-3e-book/DHCPv6-Guard.html', 'https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipv6_fhsec/configuration/15-s/ip6f-15-s-book/ip6-snooping.html', 'https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/security/cisco-nexus-9000-series-nx-os-security-configuration-guide-release-104x/m-configuring-ipv6-first-hop-security.html', 'https://www.rfc-editor.org/rfc/rfc6104.html', 'https://oneuptime.com/blog/post/2026-03-20-ndp-first-hop-security-cisco/view']

## parser_code
```python
def parse_ipv6_raguard_policy(output: str) -> list:
    """'show ipv6 nd raguard policy' (IOS / IOS-XE / NX-OS IPv6 first-hop security) ->
    [{policy, device_role, trusted, targets:[{name, type}]}]. RA-Guard blocks rogue / spoofed Router
    Advertisements at the L2 access edge -- without it a single bogus RA hijacks the default gateway for the
    whole segment (RFC 6104 / RFC 4861 gateway-hijack -> MITM/DoS). The 'host'/'monitor'-role policy applied
    to a host-facing PORT/VLAN is the protection; a 'router'-role + trusted-port policy marks the real uplink.

    Two output shapes are tolerated (Cisco varies the wording by train):
        Policy HOSTS configuration:
          device-role host
        Policy HOSTS is applied on the following targets:
        Target               Type  Policy               Feature        Target range
        Gi0/2                PORT  HOSTS                RA guard       vlan all
    [] when the device runs no RA-Guard (or the command is unsupported -> '% Invalid ...'). Tolerant; never
    raises. normalize_ifname canonicalises PORT targets so they join snap['interfaces']."""
    out: list = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        # 'Policy NAME configuration:'  (also tolerate 'RA guard policy NAME configuration:')
        m = re.match(r"^(?:RA guard )?Policy\s+(\S+)\s+configuration\s*:?\s*$", s, re.IGNORECASE)
        if m:
            cur = {"policy": m.group(1), "device_role": "", "trusted": False, "targets": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^device-role\s+(\S+)", s, re.IGNORECASE)
        if m:
            cur["device_role"] = m.group(1).lower(); continue
        if re.match(r"^trusted-port\b", s, re.IGNORECASE):
            cur["trusted"] = True; continue
        # the applied-targets table rows: 'Gi0/2  PORT  HOSTS  RA guard  vlan all'  /  'vlan 10  VLAN ...'
        mt = re.match(r"^(\S+(?:\s+\d[\d,\- ]*)?)\s+(PORT|VLAN)\s+(\S+)\s+RA guard\b", s, re.IGNORECASE)
        if mt:
            ttype = mt.group(2).upper()
            tname = mt.group(1).strip()
            name = normalize_ifname(tname) if ttype == "PORT" else tname
            # the policy a target row names may differ from the header block (no-arg form lists every policy);
            # attribute the target to the policy named in the row so attach evidence is exact.
            owner = next((p for p in out if p["policy"] == mt.group(3)), cur)
            owner["targets"].append({"name": name, "type": ttype})
    return out


def parse_ipv6_dhcp_guard_policy(output: str) -> list:
    """'show ipv6 dhcp guard policy' (IPv6 first-hop security) -> [{policy, device_role, targets:[{name,type}]}].
    DHCPv6-Guard blocks DHCPv6 reply/advertise messages from unauthorised servers/relays at the access edge
    (rogue-DHCPv6 -> address theft / MITM). A 'server'/'relay'-role policy marks the trusted upstream; a
    'client'-role policy on host ports drops server-sourced DHCPv6. Output shape:
        Dhcp guard policy: default
          Device Role: dhcp client
          Target: Et0/3
        Dhcp guard policy: test1
          Device Role: dhcp server
          Target: vlan 0 vlan 1 vlan 2
    [] when no DHCPv6-Guard. Tolerant; never raises."""
    out: list = []
    cur = None
    for raw in (output or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^Dhcp guard policy\s*:?\s*(\S+)", s, re.IGNORECASE)
        if m:
            cur = {"policy": m.group(1), "device_role": "", "targets": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^Device Role\s*:?\s*(?:dhcp\s+)?(\S+)", s, re.IGNORECASE)
        if m:
            cur["device_role"] = m.group(1).lower(); continue
        m = re.match(r"^Target\s*:?\s*(.+)$", s, re.IGNORECASE)
        if m:
            rest = m.group(1).strip()
            # 'vlan 0 vlan 1 vlan 2' -> VLAN targets; otherwise a list of interface tokens.
            vlans = re.findall(r"vlan\s+(\d+)", rest, re.IGNORECASE)
            if vlans:
                for v in vlans:
                    cur["targets"].append({"name": v, "type": "VLAN"})
            else:
                for tok in rest.split():
                    cur["targets"].append({"name": normalize_ifname(tok), "type": "PORT"})
    return out
```

## build_code
```python
def build_ipv6_fhs(cmd_to_file: Dict[str, str]) -> dict:
    """IPv6 first-hop-security posture for THIS device, fusing the dedicated FHS show-commands
    ('show ipv6 nd raguard policy', 'show ipv6 dhcp guard policy') with the already-collected
    'show running-config' (the most reliable, platform-agnostic evidence of dual-stack + per-interface
    attachment). Returns:
        {dualstack: bool,                 # >=1 IPv6-addressed SVI -> IPv6 is actively DEPLOYED (not merely capable)
         ipv6_svi_vlans: [vid,...],       # the VLANs with an IPv6 gateway (the segments at risk)
         ra_guard_policies: [..],         # global RA-Guard policy names defined
         dhcp_guard_policies: [..],
         ra_guard_ifaces: [ifname,..],    # interfaces with RA-Guard attached (global policy OR bare 'ipv6 nd raguard')
         dhcp_guard_ifaces: [ifname,..],
         ra_guard_present: bool,          # RA-Guard exists ANYWHERE on the device (policy attached to a port/vlan)
         dhcp_guard_present: bool}
    {} when the device shows no IPv6 at all (no IPv6 SVI and no FHS) -> coverage-honest: a pure-IPv4 device
    contributes nothing and the detector never cries wolf over it. Fail-soft via _safe_parse."""
    rag = _safe_parse(parse_ipv6_raguard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 nd raguard policy")) or []
    dhg = _safe_parse(parse_ipv6_dhcp_guard_policy,
                      _load_cmd_output(cmd_to_file, "show ipv6 dhcp guard policy")) or []
    run = _load_cmd_output(cmd_to_file, "show running-config") or ""

    ipv6_svi_vlans: List[int] = []
    ra_if: Set[str] = set()
    dhg_if: Set[str] = set()
    cur_if = ""
    cur_is_svi = False
    cur_has_v6 = False
    for raw in run.splitlines():
        m = re.match(r"^\s*interface\s+(\S+)", raw, re.IGNORECASE)
        if m:
            cur_if = normalize_ifname(m.group(1))
            cur_is_svi = bool(re.match(r"^(Vlan|Vl)\d+$", m.group(1), re.IGNORECASE))
            cur_has_v6 = False
            continue
        if not cur_if:
            continue
        low = raw.strip().lower()
        # IPv6 address on an SVI = the segment has an IPv6 default gateway -> dual-stack & at rogue-RA risk.
        # 'ipv6 address ...' but NOT 'no ...' and not the link-local-only 'ipv6 enable' (handled below).
        if low.startswith("ipv6 address ") and "autoconfig" not in low:
            if cur_is_svi and not cur_has_v6:
                mvid = re.match(r"^(?:Vlan|Vl)(\d+)$", cur_if, re.IGNORECASE)
                if mvid:
                    ipv6_svi_vlans.append(int(mvid.group(1)))
                cur_has_v6 = True
        # interface-level FHS attach: 'ipv6 nd raguard [attach-policy NAME]' / 'ipv6 dhcp guard [attach-policy NAME]'
        if re.match(r"^ipv6 nd raguard\b", low):
            ra_if.add(cur_if)
        if re.match(r"^ipv6 dhcp guard\b", low):
            dhg_if.add(cur_if)

    # ports the FHS show-commands report as attached (PORT-type targets) also count as protected
    for pol in rag:
        for t in pol.get("targets", []):
            if t.get("type") == "PORT" and t.get("name"):
                ra_if.add(t["name"])
    for pol in dhg:
        for t in pol.get("targets", []):
            if t.get("type") == "PORT" and t.get("name"):
                dhg_if.add(t["name"])

    ra_policy_names = sorted({p.get("policy") for p in rag if p.get("policy")})
    dhg_policy_names = sorted({p.get("policy") for p in dhg if p.get("policy")})
    # VLAN-scoped attachment also protects (RA-Guard applied to 'vlan all' / a VLAN range covers host ports).
    ra_vlan_attached = any(t.get("type") == "VLAN" for p in rag for t in p.get("targets", []))
    dhg_vlan_attached = any(t.get("type") == "VLAN" for p in dhg for t in p.get("targets", []))

    ra_present = bool(ra_if) or ra_vlan_attached
    dhg_present = bool(dhg_if) or dhg_vlan_attached
    dualstack = bool(ipv6_svi_vlans)

    # coverage-honest: emit nothing for a device with no IPv6 footprint at all (no v6 SVI, no FHS config).
    if not dualstack and not ra_present and not dhg_present and not ra_policy_names and not dhg_policy_names:
        return {}
    return {
        "dualstack": dualstack,
        "ipv6_svi_vlans": sorted(set(ipv6_svi_vlans)),
        "ra_guard_policies": ra_policy_names,
        "dhcp_guard_policies": dhg_policy_names,
        "ra_guard_ifaces": sorted(ra_if),
        "dhcp_guard_ifaces": sorted(dhg_if),
        "ra_guard_present": ra_present,
        "dhcp_guard_present": dhg_present,
    }

# NOTE: build.py import line also extended:
#   from cisco_toolkit.parse import (... parse_nve_vni,
#       parse_ipv6_raguard_policy, parse_ipv6_dhcp_guard_policy,   # IPv6 first-hop security (RA-Guard / DHCPv6-Guard)
#       ...)
# `Set` is already imported in build.py: from typing import Any, Dict, List, Optional, Set, Tuple
```

## signal_code
```python
# --- IPv6 first-hop security at the access edge (snap['ipv6_fhs'] from build_ipv6_fhs). FIRES ONLY on a
# switch that is OBSERVABLY dual-stack (>=1 IPv6-addressed SVI -> IPv6 actively DEPLOYED, not merely
# capable) AND owns host-facing ACCESS ports, yet has NO RA-Guard applied anywhere (no global policy on a
# port/vlan, no interface 'ipv6 nd raguard'). That is a broken SECURITY STATE on a live IPv6 segment
# (rogue-RA -> default-gateway hijack / MITM, RFC 6104), NOT blanket absence: a pure-IPv4 switch (no IPv6
# SVI) and a dual-stack switch that HAS RA-Guard both stay silent. DHCPv6-Guard absence is reported as a
# secondary gap (rogue-DHCPv6 -> address theft) but RA-Guard is the gate (the gateway-hijack vector).
# Coverage-honest: empty when the ipv6_fhs axis is absent (command not collected / no IPv6 anywhere).
# (Insert just before `return sig` in _signals(snap), after sig["l2_wide_hosts"].)
fhs = _as_dict(snap.get("ipv6_fhs"))
ifaces = _as_dict(snap.get("interfaces"))
fhs_open, fhs_open_dhcp, fhs_open_vlans = [], [], set()
for host, f in fhs.items():
    f = _as_dict(f)
    if not f.get("dualstack"):
        continue                                    # not a live IPv6 deployment -> never cry wolf
    has_access = any(str(_as_dict(pd).get("switchport_mode", "")).lower() == "access"
                     for pd in _as_dict(ifaces.get(host)).values())
    if not has_access:
        continue                                    # no host-facing edge on this switch -> not the FHS scope
    if not f.get("ra_guard_present"):
        fhs_open.append(host)
        for v in _as_list(f.get("ipv6_svi_vlans")):
            fhs_open_vlans.add(v)
    if not f.get("dhcp_guard_present"):
        fhs_open_dhcp.append(host)
sig["ipv6_fhs_open"] = len(fhs_open)
sig["ipv6_fhs_open_hosts"] = sorted(fhs_open)[:12]
sig["ipv6_fhs_open_dhcp"] = len(fhs_open_dhcp)
sig["ipv6_fhs_vlans"] = sorted(fhs_open_vlans)[:12]
```

## detector_code
```python
def _d_ipv6_fhs(snap, sig):
    """IPv6 first-hop security GAP at the access edge: a switch that is OBSERVABLY dual-stack (has IPv6 SVIs)
    and owns host-facing access ports, but applies NO RA-Guard anywhere -> a single rogue/spoofed Router
    Advertisement hijacks the default gateway for the whole segment (RFC 6104 / RFC 4861: NDP is trust-on-the-
    wire like ARP) -> MITM / DoS. Coverage-honest & non-cry-wolf: fires only on a LIVE IPv6 deployment missing
    the control (a pure-IPv4 switch, or a dual-stack switch that already has RA-Guard, stays silent); silent
    when the ipv6_fhs axis is absent (command not collected / no IPv6). Gated on access ports to scope it to
    the host-facing edge where rogue RAs originate."""
    n = sig.get("ipv6_fhs_open", 0)
    if n <= 0:
        return None
    vids = sig.get("ipv6_fhs_vlans") or []
    dhcp = sig.get("ipv6_fhs_open_dhcp", 0)
    dhcp_part = (f" {dhcp} of them also have no DHCPv6-Guard (rogue-DHCPv6 -> address theft)."
                 if dhcp else "")
    return _decision(
        "ipv6-first-hop-security-suite-at-access-edge",
        f"{n} dual-stack access switch(es) have IPv6 gateways"
        + (f" (VLAN(s) {', '.join(str(v) for v in vids)})" if vids else "")
        + " but NO RA-Guard on the host-facing edge -- a single rogue or fat-fingered Router Advertisement "
        f"hijacks the default gateway for the whole segment (RFC 6104 -> MITM/DoS).{dhcp_part} Enable RA-Guard "
        "+ DHCPv6-Guard on every host-facing access port (trust only the real router/server uplinks), then "
        "layer ND inspection / device-tracking and IPv6 Source Guard.",
        n, ["security", "availability"],
        ["ipv6_fhs.dualstack", "ipv6_fhs.ra_guard_present", "ipv6_fhs.ipv6_svi_vlans",
         "interfaces[host][port].switchport_mode (access-edge gate)"],
        priority="High",
        driver="IPv6 access-edge security: an unguarded dual-stack segment lets a rogue RA seize the default "
               "gateway (NDP is as spoofable as ARP); RA-Guard/DHCPv6-Guard is the L2-edge countermeasure.",
        devices=sig.get("ipv6_fhs_open_hosts") or [])

# Registered in _DETECTORS (appended after _d_vpc_health):
#   _d_vpc_health,
#   # IPv6 first-hop security (RA-Guard / DHCPv6-Guard) at the access edge -> rogue-RA gateway hijack
#   _d_ipv6_fhs]
#
# design_kb.py: the principle 'ipv6-first-hop-security-suite-at-access-edge' was MOVED out of
# _MEGA_CORPUS_ADDENDUM (all engine_actionable=False reference doctrine) and appended to
# _ACTIONABLE_DETECTOR_ADDENDUM (all engine_actionable=True), with engine_actionable flipped to True and an
# honest `observable` describing build_ipv6_fhs + _d_ipv6_fhs and the non-cry-wolf gate. This keeps both
# honesty locks green: test_every_engine_actionable_principle_is_emitted (the principle is now emitted on
# _maximal_snap) and test_mega_corpus_addendum_..._coverage_honest (MEGA stays all-non-actionable).
```

## fixture_block
```python
# Added to access1 (tests/synthetic_fixtures.py) — access1 already has access ports (Gi0/2/3 in VLAN 10,
# Gi0/10 in VLAN 30). It previously had only 'show running-config | section ^interface'; build_ipv6_fhs reads
# the FULL 'show running-config' for the dual-stack signal, so a full run-config is added with an IPv6 SVI on
# Vlan10 (=> dualstack) and NO RA-Guard, plus the two FHS show-commands returning a defined-but-UNATTACHED
# policy (which does NOT protect). core1's run-config is IPv4-only and core2 has no full run-config -> both
# return {} (silent), so EXACTLY ONE switch fires. Verified: build_ipv6_fhs -> core1={} core2={}
# access1={'dualstack': True, 'ipv6_svi_vlans': [10], 'ra_guard_present': False, ...}.

    "show running-config": """\
!
hostname access1
!
ipv6 unicast-routing
!
interface GigabitEthernet0/1
 description uplink-to-core1
 switchport trunk encapsulation dot1q
 switchport mode trunk
interface GigabitEthernet0/2
 description ap-floor1
 switchport access vlan 10
 switchport mode access
 spanning-tree portfast
interface GigabitEthernet0/3
 description phone-201
 switchport access vlan 10
 switchport mode access
interface GigabitEthernet0/10
 description srv-backup
 switchport access vlan 30
 switchport mode access
interface Vlan10
 description USERS
 ip address 10.0.10.4 255.255.255.0
 ipv6 address 2001:DB8:10::4/64
interface Vlan30
 description SERVERS
 ip address 10.0.30.4 255.255.255.0
!
line vty 0 4
 transport input ssh
!
""",
    # RA-Guard / DHCPv6-Guard are NOT configured -> the dedicated show-commands return the no-policy banner.
    "show ipv6 nd raguard policy": """\
RA guard configured policies:

Policy default configuration:
  device-role host
""",
    "show ipv6 dhcp guard policy": """\
DHCP guard configured policies:

Dhcp guard policy: default
  Device Role: dhcp client
""",
```

## test_code
```python
# ---- tests/test_parsers.py (after test_parse_nve_vni_states) ----
def test_parse_ipv6_raguard_policy(cp):
    """IPv6 first-hop security: 'show ipv6 nd raguard policy' (verbatim IOS-XE format) -> policy name,
    device-role, trusted-port, and the applied PORT/VLAN targets. A 'host'-role policy on a host-facing
    PORT is the rogue-RA (gateway-hijack) protection; the 'router'-role + trusted-port policy marks the
    real uplink. Tolerant: [] on empty / unsupported."""
    out = textwrap.dedent("""\
        Policy HOSTS configuration:
          device-role host
        Policy HOSTS is applied on the following targets:
        Target               Type  Policy               Feature        Target range
        Gi0/2                PORT  HOSTS                RA guard       vlan all
        Policy UPLINK configuration:
          device-role router
          trusted-port
        Policy UPLINK is applied on the following targets:
        Target               Type  Policy               Feature        Target range
        Gi0/1                PORT  UPLINK               RA guard       vlan all
        """)
    r = parse.parse_ipv6_raguard_policy(out)
    assert len(r) == 2
    hosts = {p["policy"]: p for p in r}
    assert hosts["HOSTS"]["device_role"] == "host" and hosts["HOSTS"]["trusted"] is False
    assert hosts["HOSTS"]["targets"] == [{"name": "Gi0/2", "type": "PORT"}]   # normalize_ifname canonical form
    assert hosts["UPLINK"]["device_role"] == "router" and hosts["UPLINK"]["trusted"] is True
    assert hosts["UPLINK"]["targets"] == [{"name": "Gi0/1", "type": "PORT"}]
    assert parse.parse_ipv6_raguard_policy("") == []
    assert parse.parse_ipv6_raguard_policy("% Invalid input detected at '^' marker.") == []


def test_parse_ipv6_dhcp_guard_policy(cp):
    """IPv6 first-hop security: 'show ipv6 dhcp guard policy' (verbatim Cisco format) -> policy name,
    device-role (dhcp client/server/relay) and the applied targets (interface tokens or 'vlan N' list).
    A 'server'/'relay'-role marks the trusted upstream; 'client' on host ports drops rogue DHCPv6.
    Tolerant: [] on empty."""
    out = textwrap.dedent("""\
        Dhcp guard policy: default
          Device Role: dhcp client
          Target: Et0/3
        Dhcp guard policy: test1
          Device Role: dhcp server
          Target: vlan 0 vlan 1 vlan 2
          Max Preference: 200
          Min Preference: 0
        Dhcp guard policy: test2
          Device Role: dhcp relay
          Target: Et0/0 Et0/1
        """)
    r = parse.parse_ipv6_dhcp_guard_policy(out)
    assert len(r) == 3
    by = {p["policy"]: p for p in r}
    assert by["default"]["device_role"] == "client" and by["default"]["targets"] == [{"name": "Et0/3", "type": "PORT"}]
    assert by["test1"]["device_role"] == "server"
    assert by["test1"]["targets"] == [{"name": "0", "type": "VLAN"}, {"name": "1", "type": "VLAN"}, {"name": "2", "type": "VLAN"}]
    assert by["test2"]["device_role"] == "relay" and len(by["test2"]["targets"]) == 2
    assert parse.parse_ipv6_dhcp_guard_policy("") == []


# ---- tests/test_design_blueprint.py (after test_d_fhrp_resilience...) ----
def test_d_ipv6_fhs_fires_on_dualstack_access_without_raguard():
    """DET-ipv6-fhs-01: a switch that is OBSERVABLY dual-stack (>=1 IPv6 SVI) with host-facing access ports but
    NO RA-Guard fires _d_ipv6_fhs (rogue-RA gateway hijack, RFC 6104). NON-CRY-WOLF refutation:
      - a dual-stack switch that already HAS RA-Guard -> silent,
      - a pure-IPv4 switch (no IPv6 SVI, even if it had no FHS) -> silent (never cry wolf on legacy IPv4),
      - a dual-stack switch with NO access ports (core/transit only) -> silent (out of the access-edge scope),
      - an absent ipv6_fhs axis (command not collected) -> silent (coverage-honest)."""
    import cisco_toolkit.design_advisor as da
    access_if = {"acc1": {"Gi0/2": {"switchport_mode": "Access", "vlan": "10"}}}
    # FIRES: dual-stack access switch, IPv6 gateway on VLAN 10, RA-Guard absent everywhere
    fire = {"interfaces": access_if,
            "ipv6_fhs": {"acc1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False,
                                  "dhcp_guard_present": False, "ra_guard_policies": [], "ra_guard_ifaces": []}}}
    sig = da._signals(fire)
    assert sig["ipv6_fhs_open"] == 1 and sig["ipv6_fhs_open_hosts"] == ["acc1"]
    assert sig["ipv6_fhs_vlans"] == [10] and sig["ipv6_fhs_open_dhcp"] == 1
    dec = da._d_ipv6_fhs(fire, sig)
    assert dec is not None and "RA-Guard" in str(dec) and "RFC 6104" in str(dec)
    assert dec["id"] == "ipv6-first-hop-security-suite-at-access-edge" and dec["priority"] == "High"
    # SILENT: RA-Guard already present on the dual-stack access switch
    guarded = {"interfaces": access_if,
               "ipv6_fhs": {"acc1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": True,
                                     "dhcp_guard_present": True}}}
    assert da._d_ipv6_fhs(guarded, da._signals(guarded)) is None
    # SILENT: pure IPv4 switch (not dual-stack) -> no IPv6 deployment to cry wolf about
    v4only = {"interfaces": access_if,
              "ipv6_fhs": {"acc1": {"dualstack": False, "ipv6_svi_vlans": [], "ra_guard_present": False}}}
    assert da._d_ipv6_fhs(v4only, da._signals(v4only)) is None
    # SILENT: dual-stack but no access ports (a routed core/transit device is out of the access-edge scope)
    coreonly = {"interfaces": {"core1": {"Po1": {"switchport_mode": "Trunk"}}},
                "ipv6_fhs": {"core1": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_present": False}}}
    assert da._d_ipv6_fhs(coreonly, da._signals(coreonly)) is None
    # SILENT: axis absent entirely (command not collected) -> coverage-honest
    assert da._d_ipv6_fhs({}, da._signals({})) is None

# Also required to keep the two coverage-honesty locks green (done in the worktree):
#  - tests/test_design_blueprint.py::_maximal_snap() gains:
#      ipv6_fhs={"acc10": {"dualstack": True, "ipv6_svi_vlans": [10], "ra_guard_policies": [],
#                          "dhcp_guard_policies": [], "ra_guard_ifaces": [], "dhcp_guard_ifaces": [],
#                          "ra_guard_present": False, "dhcp_guard_present": False}},
#    (acc10 already owns an Access port in _maximal_snap's interfaces) -> emit-invariant stays green.
#  - tests/test_design_addenda.py::_fires_all() gains an "acc9" Access port + the same ipv6_fhs record, and
#    test_actionable_detector_addendum_complete_actionable_and_emitted's `len(add) == 7` is bumped to `== 8`.
```
