"""Unit tests for the highest-risk pure show-command parsers.

Inputs are small, format-correct snippets (IOS + NX-OS). These lock in current
parser behavior so later robustness work can't silently regress it.
"""
import textwrap

from cisco_toolkit import parse   # ospf/bgp parsers no longer re-exported by the monolith (step 24)


# ---- interface status ------------------------------------------------------ #
def test_parse_show_interface_status_ios(cp):
    out = textwrap.dedent("""\
        Port      Name               Status       Vlan       Duplex  Speed Type
        Gi1/0/5   srv-app01          connected    10           full  1000  10/100/1000BaseTX
        Gi1/0/9   quarantine         err-disabled 10           auto  auto  10/100/1000BaseTX
    """)
    res = parse.parse_show_interface_status(out)
    assert set(res) == {"Gi1/0/5", "Gi1/0/9"}
    assert res["Gi1/0/5"]["status"].lower() == "connected"
    assert "err" in res["Gi1/0/9"]["status"].lower()
    assert res["Gi1/0/5"]["vlan_raw"] == "10"


# ---- run-config: ACL application (L4/ACL flagging) ------------------------- #
def test_parse_run_config_interface_acl(cp):
    out = textwrap.dedent("""\
        interface Vlan10
         description USERS
         ip address 10.0.10.2 255.255.255.0
        interface Vlan20
         description VOICE
         ip address 10.0.20.2 255.255.255.0
         ip access-group VOICE_FILTER in
        interface Vlan30
         description SERVERS
         ip address 10.0.30.1 255.255.255.0
         ip access-group PROTECT_SERVERS out
    """)
    res = parse.parse_run_config_interfaces(out)
    assert res["Vlan20"]["acl_in"] == "VOICE_FILTER" and res["Vlan20"]["acl_out"] == ""
    assert res["Vlan30"]["acl_out"] == "PROTECT_SERVERS" and res["Vlan30"]["acl_in"] == ""
    # SVI without an access-group keeps empty strings (additive, never absent)
    assert res["Vlan10"]["acl_in"] == "" and res["Vlan10"]["acl_out"] == ""


def test_parse_run_config_interface_vrf(cp):
    # PHASE K (VRF-aware reachability): capture VRF membership across all three syntaxes
    # so the explorer can isolate different-VRF subnets. A bare SVI stays in the global table ('').
    out = textwrap.dedent("""\
        interface Vlan30
         description SERVERS
         vrf forwarding TENANT_RED
         ip address 10.0.30.1 255.255.255.0
        interface Vlan40
         description NX-TENANT
         vrf member TENANT_BLUE
        interface Vlan50
         description LEGACY-IOS
         ip vrf forwarding TENANT_GREEN
        interface Vlan10
         description USERS
         ip address 10.0.10.2 255.255.255.0
    """)
    res = parse.parse_run_config_interfaces(out)
    assert res["Vlan30"]["vrf"] == "TENANT_RED"     # IOS-XE
    assert res["Vlan40"]["vrf"] == "TENANT_BLUE"    # NX-OS
    assert res["Vlan50"]["vrf"] == "TENANT_GREEN"   # legacy IOS
    assert res["Vlan10"]["vrf"] == ""               # global table — never absent


def test_parse_run_config_interface_mtu(cp):
    # PHASE path-MTU: capture interface MTU (L2 'mtu' preferred, 'ip mtu' fallback); default stays blank
    out = textwrap.dedent("""\
        interface Port-channel1
         description core-uplink
         mtu 9216
        interface GigabitEthernet1/0/1
         description routed-l3
         ip mtu 1400
        interface GigabitEthernet1/0/2
         description access
         switchport mode access
    """)
    res = parse.parse_run_config_interfaces(out)
    assert res["Po1"]["mtu"] == "9216"          # L2 jumbo
    assert res["Gi1/0/1"]["mtu"] == "1400"      # 'ip mtu' fallback when no plain 'mtu'
    assert res["Gi1/0/2"]["mtu"] == ""          # default -> blank, never absent


def test_parse_run_config_interface_dhcp_helpers(cp):
    # DHCP-relay reachability: capture 'ip helper-address' (IOS) and 'ip dhcp relay address' (NX-OS),
    # accumulating multiple servers; an SVI with no relay stays blank (never absent).
    out = textwrap.dedent("""\
        interface Vlan10
         description USERS
         ip address 10.0.10.2 255.255.255.0
         ip helper-address 10.0.40.10
         ip helper-address vrf MGMT 10.0.40.11
        interface Vlan20
         description VOICE-NXOS
         ip dhcp relay address 10.0.50.5
        interface Vlan30
         description SERVERS
         ip address 10.0.30.1 255.255.255.0
    """)
    res = parse.parse_run_config_interfaces(out)
    assert res["Vlan10"]["helpers"] == "10.0.40.10,10.0.40.11"   # accumulate; 'vrf NAME' form too
    assert res["Vlan20"]["helpers"] == "10.0.50.5"               # NX-OS relay-address form
    assert res["Vlan30"]["helpers"] == ""                        # no relay -> blank, never absent


def test_parse_nat(cp):
    # NAT inventory: inside/outside roles, pool, static 1:1, static PAT, outside-source, dynamic PAT
    out = textwrap.dedent("""\
        interface Vlan10
         ip nat inside
        interface GigabitEthernet0/1
         ip nat outside
        ip nat pool MIGRATE 203.0.113.10 203.0.113.20 netmask 255.255.255.0
        ip nat inside source static 10.0.30.9 203.0.113.9
        ip nat inside source static tcp 10.0.30.9 443 203.0.113.9 8443
        ip nat inside source list 7 pool MIGRATE overload
        ip nat outside source static 198.51.100.5 10.0.50.5
    """)
    nat = parse.parse_nat(out)
    assert nat["inside"] == ["Vlan10"] and nat["outside"] == ["Gi0/1"]
    assert nat["pools"]["MIGRATE"] == {"start": "203.0.113.10", "end": "203.0.113.20"}
    s1 = [s for s in nat["static"] if s["direction"] == "inside" and not s["proto"]][0]
    assert s1["local"] == "10.0.30.9" and s1["global"] == "203.0.113.9"          # static 1:1
    s2 = [s for s in nat["static"] if s["proto"] == "tcp"][0]
    assert s2["local"] == "10.0.30.9" and s2["local_port"] == "443" \
        and s2["global"] == "203.0.113.9" and s2["global_port"] == "8443"        # static PAT (port forward)
    so = [s for s in nat["static"] if s["direction"] == "outside"][0]
    assert so["global"] == "198.51.100.5" and so["local"] == "10.0.50.5"         # outside-source swaps local/global
    assert nat["dynamic"][0] == {"acl": "7", "kind": "pool", "via": "MIGRATE", "overload": True}


def test_parse_nat_absent(cp):
    assert parse.parse_nat("hostname r1\n!\n") == {}


def test_parse_security(cp):
    # CIS-aligned posture: weak credentials, insecure SNMP/telnet, risky service, missing baseline
    out = textwrap.dedent("""\
        username legacy password 7 070C285F4D06
        enable password cisco123
        snmp-server community S3cr3tCOMM RW
        ip http server
        line vty 0 4
         transport input telnet ssh
         exec-timeout 0 0
    """)
    sec = parse.parse_security(out)
    by = {f["id"]: f for f in sec["findings"]}
    assert by["weak-user-pw"]["status"] == "fail" and "legacy" in by["weak-user-pw"]["detail"]
    assert "070C285F4D06" not in by["weak-user-pw"]["detail"]          # password hash is never echoed
    assert by["weak-enable"]["status"] == "fail"                       # 'enable password' (reversible)
    assert by["insecure-snmp"]["status"] == "fail" and by["insecure-snmp"]["severity"] == "high"
    assert "<redacted>" in by["insecure-snmp"]["detail"]               # community string is redacted
    assert by["telnet-enabled"]["status"] == "fail"
    assert by["vty-hardening"]["status"] == "fail"                     # exec-timeout 0 0, no access-class
    assert by["risky-services"]["status"] == "fail" and "HTTP" in by["risky-services"]["detail"]
    for cid in ("password-encryption", "no-aaa", "no-ntp", "no-logging", "no-banner"):
        assert by[cid]["status"] == "fail"                            # missing baseline controls
    assert sec["summary"]["grade"] == "weak" and sec["summary"]["fail"] >= 8


def test_parse_security_nxos_central_aaa_is_recognized(cp):
    # NX-OS / IOS-XR enable central AAA WITHOUT 'aaa new-model'. The 'no-aaa' control must PASS, not
    # falsely report 'authentication is local-only' (the IOS-only-'aaa new-model' false-health class —
    # a false security finding on every NX-OS device with TACACS+/RADIUS).
    out = textwrap.dedent("""\
        feature tacacs+
        aaa group server tacacs+ ISE
         server 10.0.0.5
        aaa authentication login default group ISE
    """)
    by = {f["id"]: f for f in parse.parse_security(out)["findings"]}
    assert by["no-aaa"]["status"] == "pass", by["no-aaa"]["detail"]
    assert "central AAA" in by["no-aaa"]["detail"]


def test_parse_security_hardened(cp):
    # a hardened config: every control satisfied, no risky services -> all pass, grade 'hardened'
    out = textwrap.dedent("""\
        service password-encryption
        aaa new-model
        enable secret 9 $9$hardenedHASH
        username admin privilege 15 secret 9 $9$adminHASH
        snmp-server group NETADMIN v3 priv
        snmp-server user netops NETADMIN v3 auth sha A priv aes 256 P
        ntp server 10.0.0.10
        logging host 10.0.0.20
        banner login ^C authorized access only ^C
        no ip http server
        line vty 0 4
         access-class MGMT_IN in
         exec-timeout 5 0
         transport input ssh
    """)
    sec = parse.parse_security(out)
    by = {f["id"]: f for f in sec["findings"]}
    assert all(by[cid]["status"] == "pass" for cid in (
        "password-encryption", "no-aaa", "weak-enable", "weak-user-pw", "insecure-snmp",
        "telnet-enabled", "vty-hardening", "risky-services", "no-ntp", "no-logging", "no-banner"))
    assert sec["summary"]["fail"] == 0 and sec["summary"]["grade"] == "hardened"


def test_parse_security_absent(cp):
    assert parse.parse_security("") == {}


def test_parse_config_hygiene(cp):
    # USED_ACL applied (access-group + route-map match) and SRV referenced inside it -> used;
    # GHOST referenced via access-group but never defined; RM_MISSING referenced via redistribute
    # but never defined; DEAD_ACL + RM_OK defined but never referenced.
    out = textwrap.dedent("""\
        object-group network SRV
         host 10.0.0.5
        ip access-list extended USED_ACL
         permit ip object-group SRV any
        ip access-list extended DEAD_ACL
         permit ip any any
        route-map RM_OK permit 10
         match ip address USED_ACL
        interface GigabitEthernet0/1
         ip access-group USED_ACL in
         ip access-group GHOST out
        router bgp 65000
         redistribute ospf 1 route-map RM_MISSING
    """)
    h = parse.parse_config_hygiene(out)
    undef = {(u["kind"], u["name"]) for u in h["undefined"]}
    unused = {(u["kind"], u["name"]) for u in h["unused"]}
    assert ("acl", "GHOST") in undef                  # referenced via access-group, never defined
    assert ("route-map", "RM_MISSING") in undef       # referenced via redistribute, never defined
    assert undef == {("acl", "GHOST"), ("route-map", "RM_MISSING")}   # no false undefined
    assert ("acl", "DEAD_ACL") in unused              # defined, never referenced
    assert ("route-map", "RM_OK") in unused           # defined, never referenced
    assert ("acl", "USED_ACL") not in unused          # applied + matched in a route-map -> used
    assert ("object-group", "SRV") not in unused      # referenced inside USED_ACL's body -> used
    assert h["summary"]["undefined"] == 2


def test_parse_config_hygiene_clean(cp):
    # every reference resolves and every structure is used -> nothing to report
    out = textwrap.dedent("""\
        ip access-list extended FILTER
         permit ip any any
        interface GigabitEthernet0/1
         ip access-group FILTER in
    """)
    h = parse.parse_config_hygiene(out)
    assert h["undefined"] == [] and h["unused"] == [] and h["summary"]["structures"] == 1


def test_parse_config_hygiene_absent(cp):
    assert parse.parse_config_hygiene("hostname r1\n!\n") == {}


def test_parse_spanning_tree_root(cp):
    out = textwrap.dedent("""\
        VLAN0010
          Spanning tree enabled protocol rstp
          Root ID    Priority    24586
                     Address     aaaa.0001.0001
                     This bridge is the root
          Bridge ID  Priority    24586  (priority 24576 sys-id-ext 10)
                     Address     aaaa.0001.0001
        Interface        Role Sts Cost      Prio.Nbr Type
        Po1              Desg FWD 3         128.65   P2p

        VLAN0030
          Spanning tree enabled protocol rstp
          Root ID    Priority    32798
                     Address     cccc.0003.0003
          Bridge ID  Priority    32798  (priority 32768 sys-id-ext 30)
                     Address     aaaa.0001.0001
        Interface        Role Sts Cost      Prio.Nbr Type
        Gi1/0/24         Root FWD 4         128.24   P2p
    """)
    r = parse.parse_spanning_tree_root(out)
    assert r["10"]["is_root"] is True and r["10"]["root_priority"] == 24586     # this switch IS the root for VLAN10
    assert r["30"]["is_root"] is False                                          # root is elsewhere (root addr != bridge addr)
    assert r["30"]["root_address"] == "cccc.0003.0003"
    # the detail/state parser is unaffected by the added Root ID / Bridge ID blocks
    assert parse.parse_spanning_tree_states(out) == {"Po1": "Forwarding", "Gi1/0/24": "Forwarding"}


def test_parse_spanning_tree_root_absent(cp):
    assert parse.parse_spanning_tree_root("") == {}


def test_parse_redistribution(cp):
    # protocol-to-protocol edges: each 'redistribute' under a 'router X' block; a col-0 line ends the block
    out = textwrap.dedent("""\
        router ospf 1
         redistribute bgp 65001 subnets
         redistribute connected
        router bgp 65001
         redistribute ospf 1 route-map OSPF_TO_BGP
        interface Vlan10
         redistribute should-be-ignored
    """)
    rows = parse.parse_redistribution(out)
    edges = {(r["into_proto"], r["from_proto"]) for r in rows}
    assert edges == {("ospf", "bgp"), ("ospf", "connected"), ("bgp", "ospf")}   # interface block's line ignored
    bgp_row = [r for r in rows if r["into_proto"] == "bgp"][0]
    assert bgp_row["from_id"] == "1" and bgp_row["route_map"] == "OSPF_TO_BGP"


def test_parse_redistribution_absent(cp):
    assert parse.parse_redistribution("hostname r1\ninterface Vlan1\n!\n") == []


def test_parse_acl_stateful(cp):
    # stateful-ACL: capture 'established' (TCP return-only) and 'time-range' (time-conditional)
    out = textwrap.dedent("""\
        ip access-list extended INET_RETURN
         permit tcp any any established
         permit tcp 10.0.10.0 0.0.0.255 any eq 443 time-range BUSINESS_HOURS
         deny ip any any
    """)
    rules = parse.parse_acls(out)["INET_RETURN"]
    assert rules[0].get("established") is True              # 'established' captured
    assert "established" not in rules[1]                    # only the established rule carries it
    assert rules[1].get("time_range") == "BUSINESS_HOURS"   # time-range captured
    assert not rules[2].get("established") and not rules[2].get("time_range")   # plain deny: neither


# ---- ACL definitions (L4 allow/deny sim) ----------------------------------- #
def test_parse_acls_forms(cp):
    out = textwrap.dedent("""\
        access-list 10 permit 10.0.0.0 0.0.0.255
        access-list 101 deny tcp host 10.0.0.5 any eq 23
        ip access-list extended PROTECT_SERVERS
         permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443
         deny ip any any
        ip access-list GUEST_NX
         10 permit udp 10.0.20.0/24 any range 16384 32767
         20 deny ip any any
        interface Vlan10
         ip access-group PROTECT_SERVERS out
    """)
    acls = parse.parse_acls(out)
    assert set(acls) == {"10", "101", "PROTECT_SERVERS", "GUEST_NX"}   # application line is NOT a definition
    # numbered standard: src only, proto ip, dst any, fully evaluable (no 'unevaluable' key)
    assert acls["10"][0] == {"action": "permit", "raw": "permit 10.0.0.0 0.0.0.255", "proto": "ip",
                             "src": {"ip": "10.0.0.0", "wild": "0.0.0.255"},
                             "dst": {"ip": "0.0.0.0", "wild": "255.255.255.255"}, "sport": None, "dport": None}
    # numbered extended: host src + eq port
    r = acls["101"][0]
    assert r["action"] == "deny" and r["proto"] == "tcp"
    assert r["src"] == {"ip": "10.0.0.5", "wild": "0.0.0.0"} and r["dport"] == {"op": "eq", "val": 23}
    # named extended: permit then explicit deny
    ps = acls["PROTECT_SERVERS"]
    assert ps[0]["proto"] == "tcp" and ps[0]["dport"] == {"op": "eq", "val": 443}
    assert ps[0]["dst"] == {"ip": "10.0.30.0", "wild": "0.0.0.255"}
    assert ps[1]["action"] == "deny" and ps[1]["proto"] == "ip"
    # NX-OS prefix form + range port, sequence numbers stripped
    g = acls["GUEST_NX"][0]
    assert g["proto"] == "udp" and g["src"] == {"ip": "10.0.20.0", "wild": "0.0.0.255"}
    assert g["dport"] == {"op": "range", "val": 16384, "val2": 32767}


# ---- object-groups (L4 depth) ---------------------------------------------- #
def test_parse_object_groups_forms(cp):
    out = textwrap.dedent("""\
        object-group network MGMT_NETS
         host 10.0.99.10
         10.0.40.0 255.255.255.0
         range 10.0.50.1 10.0.50.9
         group-object CORE_NETS
        object-group ip address NX_NETS
         10 host 10.0.60.1
         20 10.0.61.0/24
        object-group service WEB_SVC
         tcp eq 443
         tcp range 8080 8090
        interface Vlan10
         ip access-group X in
    """)
    g = parse.parse_object_groups(out)
    assert set(g) == {"MGMT_NETS", "NX_NETS", "WEB_SVC"}
    mn = g["MGMT_NETS"]
    assert mn["kind"] == "network"
    assert mn["members"][0] == {"ip": "10.0.99.10", "wild": "0.0.0.0"}            # host
    assert mn["members"][1] == {"ip": "10.0.40.0", "wild": "0.0.0.255"}           # IOS subnet+mask -> wildcard
    assert mn["members"][2] == {"rangeStart": "10.0.50.1", "rangeEnd": "10.0.50.9"}
    assert mn["members"][3] == {"group": "CORE_NETS"}                             # nested group-object
    nx = g["NX_NETS"]["members"]                                                  # NX-OS: seq stripped, prefix -> wildcard
    assert nx[0] == {"ip": "10.0.60.1", "wild": "0.0.0.0"} and nx[1] == {"ip": "10.0.61.0", "wild": "0.0.0.255"}
    ws = g["WEB_SVC"]
    assert ws["kind"] == "service"
    assert ws["members"][0] == {"proto": "tcp", "op": "eq", "val": 443}
    assert ws["members"][1] == {"proto": "tcp", "op": "range", "val": 8080, "val2": 8090}


# ---- ICMP-type awareness (L4 depth) ---------------------------------------- #
def test_parse_acl_icmp_type(cp):
    out = textwrap.dedent("""\
        ip access-list extended PING_POLICY
         permit icmp any 10.0.30.0 0.0.0.255 echo-reply
         permit icmp any any
         deny ip any any
    """)
    p = parse.parse_acls(out)["PING_POLICY"]
    assert p[0]["proto"] == "icmp" and p[0]["icmp_type"] == "echo-reply"
    assert p[0]["dst"] == {"ip": "10.0.30.0", "wild": "0.0.0.255"}
    assert "icmp_type" not in p[1]   # 'permit icmp any any' = any icmp type


# ---- switchport ------------------------------------------------------------ #
def test_parse_switchport_modes(cp):
    out = textwrap.dedent("""\
        Name: Gi1/0/24
        Administrative Mode: trunk
        Operational Mode: trunk
        Trunking Native Mode VLAN: 1 (default)
        Trunking VLANs Enabled: 10,20,30

        Name: Gi1/0/5
        Administrative Mode: static access
        Operational Mode: static access
        Access Mode VLAN: 10 (data)
    """)
    res = parse.parse_show_interface_switchport(out)
    assert res["Gi1/0/24"]["mode"] == "Trunk"
    assert res["Gi1/0/5"]["mode"] == "Access"
    assert res["Gi1/0/5"]["access_vlan"] == "10"


# ---- trunk table (IOS) ----------------------------------------------------- #
def test_parse_trunk_table_ios(cp):
    out = textwrap.dedent("""\
        Port        Mode             Encapsulation  Status        Native vlan
        Gi0/1       on               802.1q         trunking      1

        Port        Vlans allowed on trunk
        Gi0/1       10,20,30
    """)
    res = parse.parse_show_interface_trunk_table(out)
    assert res["Gi0/1"]["status"] == "trunking"
    assert res["Gi0/1"]["native_vlan"] == "1"
    assert res["Gi0/1"]["allowed_vlans"] == "10,20,30"


# ---- vlan brief ------------------------------------------------------------ #
def test_parse_vlan_brief(cp):
    out = textwrap.dedent("""\
        VLAN Name                             Status    Ports
        ---- -------------------------------- --------- ------------------------
        10   USERS                            active    Gi0/2, Gi0/3
        30   SERVERS                          active    Gi0/10
    """)
    res = parse.parse_vlan_brief(out)
    assert res["10"]["name"] == "USERS"
    assert "Gi0/2" in res["10"]["ports"]
    assert res["30"]["name"] == "SERVERS"


# ---- HSRP (down/active states + VIP) --------------------------------------- #
def test_parse_hsrp_summary(cp):
    out = textwrap.dedent("""\
        Interface   Grp  Pri P State    Active          Standby         Virtual IP
        Vl10        10   110 P Active   local           10.0.10.3       10.0.10.1
        Vl20        20   100   Standby  10.0.20.3       local           10.0.20.1
    """)
    res = parse.parse_hsrp_summary(out)
    assert res["Vlan10"] == "HSRP grp 10 Active VIP 10.0.10.1"
    assert res["Vlan20"] == "HSRP grp 20 Standby VIP 10.0.20.1"


# ---- OSPF neighbors (a down neighbor must be visible) ---------------------- #
def test_parse_ospf_neighbors_detects_down(cp):
    out = textwrap.dedent("""\
        Neighbor ID     Pri   State           Dead Time   Address         Interface
        10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1
        10.0.99.9         1   EXSTART/DROTHER 00:00:31    10.0.40.9       Vlan40
    """)
    rows = parse.parse_ospf_neighbors(out)
    states = {r["neighbor"]: r["state"] for r in rows}
    assert states["10.0.99.2"].startswith("FULL")
    assert states["10.0.99.9"].startswith("EXSTART")


# ---- BGP summary (Established = numeric PfxRcd vs a stuck peer) ------------- #
def test_parse_bgp_summary_states(cp):
    out = textwrap.dedent("""\
        Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
        10.0.0.2        4 65001    1200    1199        5    0    0 01:02:03        12
        10.0.0.3        4 65002       0       0        0    0    0 never           Idle
    """)
    rows = parse.parse_bgp_summary(out)
    states = {r["neighbor"]: r["state"] for r in rows}
    assert states["10.0.0.2"] == "12"      # established -> prefix count
    assert states["10.0.0.3"] == "Idle"    # not established


# ---- CDP neighbors detail -------------------------------------------------- #
def test_parse_cdp_detail(cp):
    out = textwrap.dedent("""\
        -------------------------
        Device ID: access1.lab
        Entry address(es):
          IP address: 10.0.99.3
        Platform: cisco WS-C2960X-48,  Capabilities: Switch
        Interface: GigabitEthernet1/0/24,  Port ID (outgoing port): GigabitEthernet0/1
    """)
    res = parse.parse_neighbors_cdp(out)
    assert res["Gi1/0/24"]["device_id"] == "access1.lab"
    assert res["Gi1/0/24"]["remote_port"] == "Gi0/1"
    assert res["Gi1/0/24"]["mgmt_ip"] == "10.0.99.3"


# ---- EtherChannel members -------------------------------------------------- #
def test_parse_etherchannel_members(cp):
    out = textwrap.dedent("""\
        Group  Port-channel  Protocol    Ports
        ------+-------------+-----------+--------------------------------------
        1      Po1(SU)         LACP      Gi1/0/1(P)    Gi1/0/2(P)
    """)
    members = parse.parse_etherchannel_summary_members(out)
    assert members.get("Gi1/0/1") == "Po1"
    assert members.get("Gi1/0/2") == "Po1"


# ---- IP routes (connected subnet for an SVI) ------------------------------- #
def test_parse_ip_routes_connected(cp):
    out = textwrap.dedent("""\
        Codes: C - connected, L - local
        C        10.0.30.0/24 is directly connected, Vlan30
        L        10.0.30.1/32 is directly connected, Vlan30
    """)
    routes = parse.parse_ip_routes(out)
    assert "10.0.30.0/24" in routes
    entry = routes["10.0.30.0/24"]["entries"][0]
    assert entry["source"] == "connected"
    assert entry["out_intf"] == "Vlan30"


# ---- interface counters (errors) ------------------------------------------- #
def test_parse_interface_counters(cp):
    out = textwrap.dedent("""\
        GigabitEthernet1/0/9 is down, line protocol is down (err-disabled)
          MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
             142 input errors, 17 CRC, 0 frame, 0 overrun, 0 ignored
             Total output drops: 0
    """)
    res = parse.parse_show_interface_counters(out)
    assert res["Gi1/0/9"]["input_errors"] == 142
    assert res["Gi1/0/9"]["crc"] == 17


def test_parse_interface_counters_captures_output_side_errors(cp):
    # output errors / late collisions (duplex mismatch) / runts / giants were collected but DISCARDED by
    # the parser; they are now preserved on the per-interface record (output L1 health for the explorer).
    out = textwrap.dedent("""\
        GigabitEthernet1/0/9 is up, line protocol is up
          MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
             142 input errors, 17 CRC, 0 frame, 0 overrun, 0 ignored
             5 runts, 2 giants, 0 throttles
             8 output errors, 3 late collision, 0 deferred
    """)
    rec = parse.parse_show_interface_counters(out)["Gi1/0/9"]
    assert rec["output_errors"] == 8 and rec["late_collisions"] == 3
    assert rec["runts"] == 5 and rec["giants"] == 2


# ---- show environment: Catalyst 4948E / 4500-X PS table -------------------- #
def test_parse_show_environment_catalyst_ps_table(cp):
    # 4948E layout: PS health + fan-sensor live here (NOT in 'show environment power',
    # which returns '% Invalid input' on this platform). Recover ps_status / fan / num_ps.
    out = textwrap.dedent("""\
        no temperature alarms

        Module Sensor                     Temperature          Status
        ------+--------------------------+--------------------+------------
        1      air inlet                  26C (49C,64C,67C)              ok
        1      air outlet                 43C (69C,85C,88C)              ok

        Power                                             Fan      Inline
        Supply  Model No          Type       Status       Sensor   Status
        ------  ----------------  ---------  -----------  -------  -------
        PS1     PWR-C49E-300AC-R  AC 300W    good         good     n.a.
        PS2     PWR-C49E-300AC-R  AC 300W    good         good     n.a.

        Power supplies needed by system    : 1
        Power supplies currently available : 2

        Fantray : Good
    """)
    res = parse.parse_show_environment(out)
    assert res["ps_status"] == "OK"          # both PSUs good -> distinct -> "OK"
    assert res["num_ps"] == "2"
    assert res["fan_status"] == "OK"         # PS fan-sensor column + Fantray line
    assert res["temperature_status"] == "OK"


def test_parse_show_environment_flags_failed_ps(cp):
    out = textwrap.dedent("""\
        Power                                             Fan      Inline
        Supply  Model No          Type       Status       Sensor   Status
        ------  ----------------  ---------  -----------  -------  -------
        PS1     PWR-C49E-300AC-R  AC 300W    good         good     n.a.
        PS2     PWR-C49E-300AC-R  AC 300W    faulty       good     n.a.
    """)
    res = parse.parse_show_environment(out)
    assert res["ps_status"] == "OK / FAIL"   # one healthy, one failed -> both shown
    assert res["num_ps"] == "2"


def test_parse_show_environment_iosxe_show_environment_all(cp):
    # IOS-XE 9300/3850 'show environment all' (the form those platforms accept - bare
    # 'show environment' returns '% Incomplete command'). Format per Cisco docs; recover
    # fan + temperature here (ps still comes from the dedicated 'show environment power').
    out = textwrap.dedent("""\
        Switch   FAN     Speed   State   Airflow direction
        ------   ----    -----   -----   -----------------
        1        1       8160    OK      front to back
        1        2       8160    OK      front to back
        1        3       8160    OK      front to back
        FAN PS-1 is OK
        FAN PS-2 is NOT PRESENT

        Temperature State: GREEN
        Temperature Value: 28 Degree Celsius
        Yellow Threshold : 66 Degree Celsius
        Red Threshold    : 76 Degree Celsius
    """)
    res = parse.parse_show_environment(out)
    assert res["fan_status"] == "OK"
    assert res["temperature_status"] == "OK"


def test_parse_show_environment_iosxe_flags_red_temp(cp):
    out = textwrap.dedent("""\
        1        1       8160    OK      front to back
        Temperature State: RED
    """)
    res = parse.parse_show_environment(out)
    assert res["temperature_status"] == "Critical/Failed"   # RED -> Critical
    assert res["fan_status"] == "OK"


# ---- tolerance: empty / garbage input never raises ------------------------- #
def test_parsers_tolerate_empty_and_garbage(cp):
    for fn in (parse.parse_show_interface_status, parse.parse_show_interface_switchport,
               parse.parse_show_interface_trunk_table, parse.parse_vlan_brief,
               parse.parse_hsrp_summary, parse.parse_ospf_neighbors, parse.parse_bgp_summary,
               parse.parse_neighbors_cdp, parse.parse_ip_routes,
               parse.parse_show_interface_counters):
        assert fn("") in ({}, [])
        # random non-matching text must not raise and must yield nothing useful
        assert fn("garbage line\n%% nonsense ????\n") in ({}, [])


def test_parse_poe_inline_budget_sums_modules_and_skips_na(cp):
    """DET-poe-001: the 'show power inline' Module rows carry the PoE budget the per-port parse skips.
    Sum across stack modules; an n/a-only switch stays UNBUDGETED (no false 0/0 -> poe_util blank)."""
    two_mod = (
        "Module   Available     Used     Remaining\n"
        "          (Watts)     (Watts)    (Watts)\n"
        "------   ---------   --------   ---------\n"
        "1          1120.0      156.4       963.6\n"
        "2          1120.0      171.8       948.2\n")
    assert parse._parse_poe_inline_budget(two_mod) == {"available": 2240.0, "used": 328.2}
    na = ("Module   Available     Used     Remaining\n"
          "1             n/a        n/a         n/a\n")
    assert parse._parse_poe_inline_budget(na) == {}
    assert parse._parse_poe_inline_budget("") == {}


def test_parse_hsrp_detail_captures_priority_preempt_track(cp):
    """Universality (FHRP gap): the brief parser keeps only state+VIP, silently dropping priority,
    preemption and tracking. parse_hsrp_detail reads the FULL 'show standby [all]' so a senior FHRP
    audit (election, preempt, untracked-active) becomes possible. AJ has zero FHRP -> this is the first
    capability proven on a NON-AJ environment."""
    out = (
        "GigabitEthernet0/1 - Group 10\n"
        "  State is Active\n"
        "  Virtual IP address is 10.1.1.1\n"
        "  Active virtual MAC address is 0000.0c07.ac0a\n"
        "  Hello time 3 sec, hold time 10 sec\n"
        "  Preemption enabled, delay min 30 secs\n"
        "  Active router is local\n"
        "  Standby router is 10.1.1.3, priority 90 (expires in 8.000 sec)\n"
        "  Priority 110 (configured 110)\n"
        "    Track object 1 state Up decrement 20\n"
        "GigabitEthernet0/2 - Group 20\n"
        "  State is Active\n"
        "  Virtual IP address is 10.1.2.1\n"
        "  Active virtual MAC address is 0000.0c07.ac14\n"
        "  Preemption disabled\n"
        "  Priority 100 (configured 100)\n")
    r = parse.parse_hsrp_detail(out)
    by_grp = {k[1]: v for k, v in r.items()}
    g10 = by_grp["10"]
    assert g10["state"] == "Active" and g10["priority"] == 110 and g10["preempt"] is True
    assert g10["vip"] == "10.1.1.1" and g10["standby_ip"] == "10.1.1.3"
    assert g10["track"] == [{"obj": "1", "decrement": 20}] and g10["preempt_delay"] == 30
    g20 = by_grp["20"]
    # the senior red flags AJ could never surface: an Active group with NO preemption and NO tracking
    assert g20["preempt"] is False and g20["track"] == [] and g20["priority"] == 100
    assert parse.parse_hsrp_detail("") == {}


def test_parse_nve_peers_states(cp):
    """Universality (NX-OS VXLAN-EVPN): the engine was blind to its OWN target fabric. parse_nve_peers reads
    'show nve peers' so a DOWN VTEP peer (overlay partition) is detectable."""
    out = (
        "Interface Peer-IP          State LearnType Uptime   Router-Mac\n"
        "--------- ---------------  ----- --------- -------- -----------------\n"
        "nve1      10.0.0.1         Up    CP        00:10:00 n/a\n"
        "nve1      10.0.0.2         Down  CP        00:00:00 n/a\n")
    r = parse.parse_nve_peers(out)
    assert len(r) == 2
    assert r[0] == {"interface": "nve1", "peer_ip": "10.0.0.1", "state": "Up", "learn_type": "CP"}
    assert r[1]["state"] == "Down" and r[1]["peer_ip"] == "10.0.0.2"
    assert parse.parse_nve_peers("") == []


def test_parse_evpn_summary_states(cp):
    """Universality (VXLAN-EVPN control plane): parse_evpn_summary reads 'show bgp l2vpn evpn summary' so a
    non-Established RR session (overlay MAC/IP route exchange broken) is detectable."""
    out = (
        "BGP router identifier 10.0.0.7, local AS number 65001\n"
        "Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "10.0.0.254      4 65001    5000    5000      120    0    0 1d05h    240\n"
        "10.0.0.253      4 65001       0       0        0    0    0 00:00:00 Idle\n")
    r = parse.parse_evpn_summary(out)
    assert len(r) == 2
    assert r[0] == {"neighbor": "10.0.0.254", "as": "65001", "state": "Established", "prefixes": 240}
    assert r[1]["state"] == "Idle" and r[1]["prefixes"] == 0
    assert parse.parse_evpn_summary("") == []


def test_parse_nve_vni_states(cp):
    """Universality (VXLAN VNI): parse_nve_vni reads 'show nve vni' so a VNI not Up (stranded VLAN/VRF) is detectable."""
    out = (
        "Interface VNI      Multicast-group   State Mode Type [BD/VRF]\n"
        "nve1      10010    225.1.1.10        Up    CP   L2 [10]\n"
        "nve1      50000    n/a               Down  CP   L3 [vrf-prod]\n")
    r = parse.parse_nve_vni(out)
    assert len(r) == 2
    assert r[0] == {"vni": "10010", "mcast_group": "225.1.1.10", "state": "Up", "mode": "CP", "type": "L2"}
    assert r[1]["vni"] == "50000" and r[1]["state"] == "Down" and r[1]["mcast_group"] == ""
    assert parse.parse_nve_vni("") == []
