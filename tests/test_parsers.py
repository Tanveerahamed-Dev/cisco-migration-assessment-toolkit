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
        "  Priority 100 (configured 100)\n"
        "Vlan50 - Group 50 (version 2)\n"
        "  State is Standby\n"
        "  Virtual IP address is 10.1.50.1\n"
        "  Preemption enabled\n"
        "  Priority 120 (configured 120)\n")
    r = parse.parse_hsrp_detail(out)
    by_grp = {k[1]: v for k, v in r.items()}
    g10 = by_grp["10"]
    assert g10["state"] == "Active" and g10["priority"] == 110 and g10["preempt"] is True
    assert g10["vip"] == "10.1.1.1" and g10["standby_ip"] == "10.1.1.3"
    assert g10["track"] == [{"obj": "1", "decrement": 20}] and g10["preempt_delay"] == 30
    g20 = by_grp["20"]
    # the senior red flags AJ could never surface: an Active group with NO preemption and NO tracking
    assert g20["preempt"] is False and g20["track"] == [] and g20["priority"] == 100
    # HSRPv2 header carries a '(version 2)' suffix -- the group must still be captured (not dropped) + version read.
    g50 = by_grp["50"]
    assert g50["state"] == "Standby" and g50["priority"] == 120 and g50["version"] == 2 and g50["preempt"] is True
    assert parse.parse_hsrp_detail("") == {}


def test_parse_ipv6_route_summary_number_first(cp):
    """parse_ipv6_route_summary must read the real IOS/IOS-XE number-first comma list ('37 local, 35 connected,
    ...') which sits on its OWN line (not after an inline colon). Previously by_source came back EMPTY so the
    per-source breakdown was invisible even though the routing table was 'present'."""
    out = (
        "IPv6 Routing Table Summary - 257 entries\n"
        "  37 local, 35 connected, 25 static, 0 RIP, 160 BGP\n"
        "  Number of prefixes:\n"
        "    /16: 1, /64: 200, /128: 56\n")
    r = parse.parse_ipv6_route_summary(out)
    assert r["present"] is True and r["total"] == 257
    assert r["by_source"]["local"] == 37 and r["by_source"]["connected"] == 35
    assert r["by_source"]["static"] == 25 and r["by_source"]["bgp"] == 160 and r["by_source"]["rip"] == 0
    assert parse.parse_ipv6_route_summary("") == {}


def test_parse_pim_rp_mapping_nxos_group_ranges_ssm_only(cp):
    """NX-OS prints 'Group ranges:' (not IOS 'Group(s)'). The old regex missed it -> groups=[] -> the SSM-only
    safety valve was dead -> a healthy SSM-only Nexus (0 ASM RP; SSM needs none) FALSE-POSITIVE fired 'PIM up,
    no RP'. The NX-OS wording must populate groups so ssm_only is recognised and the cry-wolf is suppressed."""
    nxos_ssm = (
        "PIM Group-to-RP Mappings and Expiry Times\n"
        "Group ranges: 232.0.0.0/8\n"
        "  (SSM)\n")
    r = parse.parse_pim_rp_mapping(nxos_ssm)
    assert r["present"] is True and r["rp_count"] == 0
    assert r["groups"] == ["232.0.0.0/8"] and r["ssm_only"] is True


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
    # IOS-XE Catalyst 9000 layout: 'Interface VNI Type Peer-IP RMAC/Num_RTs eVNI state flags uptime' -- the IP is
    # column 4 (column 2 is the VNI), so the NX-OS regex returned [] for the entire IOS-XE VXLAN-EVPN fleet.
    iosxe = (
        "Interface VNI       Type Peer-IP        RMAC/Num_RTs   eVNI    state flags UP time\n"
        "nve1      50001     L2CP 10.1.1.1       a0b1.c2d3.e4f5 50001   UP    A/M/4 1d05h\n"
        "nve1      50002     L3CP 10.1.1.2       a0b1.c2d3.e4f6 50002   DOWN  A/-/4 00:00:10\n")
    byi = {x["peer_ip"]: x for x in parse.parse_nve_peers(iosxe)}
    assert set(byi) == {"10.1.1.1", "10.1.1.2"}
    assert byi["10.1.1.1"]["state"] == "Up" and byi["10.1.1.1"]["learn_type"] == "CP"
    assert byi["10.1.1.2"]["state"] == "Down"
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


def test_parse_bgp_vpnv4_summary_states(cp):
    """Universality (MPLS L3VPN): parse_bgp_vpnv4_summary reads 'show bgp vpnv4 unicast summary' (same grid as
    the EVPN/IPv4 summaries) so a non-Established VPNv4 PE peer -- no customer VRF routes exchanged -- is
    detectable. The 'BGP router identifier' and header rows never become phantom neighbors."""
    out = (
        "BGP router identifier 10.0.255.1, local AS number 65000\n"
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "10.0.255.2      4        65000     842     839       14    0    0 4d05h           6\n"
        "10.0.255.9      4        65000       0       0        1    0    0 never    Idle\n")
    r = parse.parse_bgp_vpnv4_summary(out)
    assert len(r) == 2
    assert r[0] == {"neighbor": "10.0.255.2", "as": "65000", "state": "Established", "prefixes": 6}
    assert r[1]["neighbor"] == "10.0.255.9" and r[1]["state"] == "Idle" and r[1]["prefixes"] == 0
    assert parse.parse_bgp_vpnv4_summary("") == []


def test_parse_bgp_summary_wrapped_ipv6_and_asdot(cp):
    """Refutes the wrapped-row FALSE-HEALTH bug. When the Neighbor/AS columns are wide (a 15-char IPv4, any
    IPv6 peer, or a 4-byte asdot AS), real 'show bgp ... summary' wraps the State/PfxRcd onto a continuation
    line. The old parser read the last token of line 1 (an AS number) as the state and fabricated
    'Established' for a genuinely DOWN peer -- and dropped IPv6 peers entirely (IPv4-only anchor). The down
    peers must surface as Idle, IPv6/asdot peers must not vanish, and the asdot AS must be captured whole."""
    out = (
        "BGP router identifier 10.0.0.7, local AS number 65001\n"
        "Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        # long 15-char IPv4: Neighbor/V/AS on line 1, stats+State wrap to line 2 (Idle == DOWN)
        "192.168.250.254 4 65001\n"
        "                         984    1086       11    0    0 16:16:33 Idle\n"
        # IPv6 peer: address alone on line 1, the whole grid wraps to line 2 (Idle == DOWN)
        "FEC0:C0FF:EE00::11:2\n"
        "                4 65100     984    1086       11    0    0 16:16:33 Idle\n"
        # asdot 4-byte AS, single line, Established -> AS captured whole ('1.2'), not truncated to '1'
        "10.0.0.9        4  1.2     5000    5000      120    0    0 1d05h        240\n")
    r = parse._parse_bgp_summary_rows(out)
    by = {x["neighbor"]: x for x in r}
    assert set(by) == {"192.168.250.254", "FEC0:C0FF:EE00::11:2", "10.0.0.9"}, by
    assert by["192.168.250.254"]["state"] == "Idle" and by["192.168.250.254"]["prefixes"] == 0
    assert by["FEC0:C0FF:EE00::11:2"]["state"] == "Idle"
    assert by["10.0.0.9"]["state"] == "Established" and by["10.0.0.9"]["prefixes"] == 240
    assert by["10.0.0.9"]["as"] == "1.2"


def test_parse_bgp_ipv6_summary_wrapped(cp):
    """parse_bgp_ipv6_summary must not drop a wrapped long-IPv6 peer: real 'show bgp ipv6 unicast summary' prints
    a long neighbor on its own line with the V/AS/.../State grid wrapped to the next line; a down (Idle) peer in
    that form previously VANISHED (read as 'no IPv6 BGP'). It must surface as Idle."""
    out = (
        "BGP router identifier 10.0.0.7, local AS number 65001\n"
        "Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "2001:DB8::1     4 65001    5000    5000      120    0    0 1d05h        240\n"
        "FEC0:C0FF:EE00::11:2\n"
        "                4 65100     984    1086       11    0    0 16:16:33 Idle\n")
    by = {x["neighbor"]: x for x in parse.parse_bgp_ipv6_summary(out)}
    assert by["2001:DB8::1"]["state"] == "Established" and by["2001:DB8::1"]["prefixes"] == 240
    assert by["FEC0:C0FF:EE00::11:2"]["state"] == "Idle"
    assert parse.parse_bgp_ipv6_summary("") == []


def test_parse_mpls_ldp_neighbors_states(cp):
    """Universality (MPLS LDP underlay): parse_mpls_ldp_neighbors reads 'show mpls ldp neighbor' so a session
    not in 'Oper' (no transport label bindings exchanged -> LSPs blackhole) is detectable. The indented TCP /
    discovery lines and the 'Addresses bound to peer LDP Ident' line never create phantom neighbors."""
    out = (
        "Peer LDP Ident: 10.0.255.2:0; Local LDP Ident 10.0.255.1:0\n"
        "\tTCP connection: 10.0.255.2.646 - 10.0.255.1.11008\n"
        "\tState: Oper; Msgs sent/rcvd: 842/839; Downstream\n"
        "\tUp time: 4d05h\n"
        "\tAddresses bound to peer LDP Ident:\n"
        "\t  10.0.255.2\n"
        "Peer LDP Ident: 10.0.255.9:0; Local LDP Ident 10.0.255.1:0\n"
        "\tState: Nonexistent; Msgs sent/rcvd: 0/0; Downstream\n")
    r = parse.parse_mpls_ldp_neighbors(out)
    assert len(r) == 2
    assert r[0] == {"peer": "10.0.255.2", "label_space": "0", "state": "Oper"}
    assert r[1]["peer"] == "10.0.255.9" and r[1]["state"] == "Nonexistent"
    assert parse.parse_mpls_ldp_neighbors("") == []


def test_parse_mpls_l2vpn_vc_status(cp):
    """Universality (MPLS L2VPN/pseudowire): parse_mpls_l2vpn_vc reads 'show mpls l2transport vc' and parses
    each row from the RIGHT, so a 'Local circuit' value containing spaces still yields the correct VC ID /
    dest / status, and a DOWN pseudowire (broken customer L2 circuit) is detectable. The header and the dashed
    separator are skipped (their dest column is not an IPv4 address)."""
    out = (
        "Local intf     Local circuit              Dest address    VC ID    Status\n"
        "-------------  -------------------------  --------------  -------  ----------\n"
        "Gi1/0/2        Ethernet                   10.0.255.2      200      UP\n"
        "Gi1/0/3        Ethernet VLAN 300          10.0.255.9      300      DOWN\n"
        "Gi1/0/4        Ethernet                   10.0.255.10     400      ADMIN DOWN\n")
    r = parse.parse_mpls_l2vpn_vc(out)
    assert len(r) == 3
    assert r[0] == {"local_intf": "Gi1/0/2", "dest": "10.0.255.2", "vc_id": "200", "status": "UP"}
    assert r[1]["vc_id"] == "300" and r[1]["status"] == "DOWN" and r[1]["dest"] == "10.0.255.9"
    # the two-word 'ADMIN DOWN' state must be captured WHOLE (the row was previously dropped entirely)
    assert r[2]["vc_id"] == "400" and r[2]["status"] == "ADMIN DOWN" and r[2]["dest"] == "10.0.255.10"
    assert parse.parse_mpls_l2vpn_vc("") == []


def test_parse_lisp_sessions_states(cp):
    """Universality (SD-Access LISP fabric): parse_lisp_sessions reads 'show lisp session', keying each
    'Sessions for VRF <name>, total: N, established: M' block and its 'IP:port State ...' peer rows. The Down
    VRF (established 0) is distinguishable from the Up VRF by the summary counts, so the all-sessions-down
    fabric partition is detectable while the indented column header never creates a phantom peer."""
    out = (
        "Sessions for VRF default, total: 2, established: 2\n"
        "Peer                           State      Up/Down        In/Out    Users\n"
        "10.0.255.2:4342                Up         1d04h          27/9      14\n"
        "10.0.255.3:4342                Up         1d03h          19/9      14\n"
        "Sessions for VRF red, total: 2, established: 0\n"
        "Peer                           State      Up/Down        In/Out    Users\n"
        "10.0.255.2:4342                Down       never          0/0       0\n"
        "10.0.255.3:4342                Down       never          0/0       0\n")
    r = parse.parse_lisp_sessions(out)
    assert len(r) == 2
    assert r[0]["vrf"] == "default" and r[0]["total"] == 2 and r[0]["established"] == 2
    assert len(r[0]["peers"]) == 2
    assert r[0]["peers"][0] == {"peer": "10.0.255.2", "port": "4342", "state": "Up"}
    assert r[1]["vrf"] == "red" and r[1]["total"] == 2 and r[1]["established"] == 0
    assert all(p["state"] == "Down" for p in r[1]["peers"])
    assert parse.parse_lisp_sessions("") == []


def test_parse_cts_environment_data_states(cp):
    """Universality (Cisco TrustSec / CTS segmentation): parse_cts_environment_data reads the env-data
    'Current state' so a download that is not COMPLETE (no SGT->policy map -> segmentation blind) is
    detectable, while a COMPLETE set is recognized as healthy. Critically, a COMPLETE state with DEAD
    RADIUS servers stays COMPLETE (server status is NOT read), and absent / non-CTS output yields {}."""
    complete = (
        "CTS Environment Data\n"
        "====================\n"
        "Current state = COMPLETE\n"
        "Last status = Successful\n"
        "Local Device SGT:\n"
        "  SGT tag = 216-22:TrustSec_Devices\n"
        "Server List Info:\n"
        "Installed list: CTSServerList1-000B, 2 server(s):\n"
        " *Server: 10.0.0.10, port 1812, A-ID 3X0P672A296F212FUEC21S27E4A2579N\n"
        "          Status = DEAD\n"
        " *Server: 10.0.0.11, port 1812, A-ID 3X08674A806S217FUEC21C24E4A3549N\n"
        "          Status = DEAD\n"
        "Security Group Name Table:\n"
        "    0-07:Unknown    3-00:Network_Services    4-04:Employees    5-00:Contractors\n"
        "Environment Data Lifetime = 86400 secs\n"
        "State Machine is running\n")
    r = parse.parse_cts_environment_data(complete)
    assert r["state"] == "COMPLETE" and r["last_status"] == "Successful"
    assert r["sgt_count"] == 4 and r["server_count"] == 2 and r["lifetime"] == 86400
    broken = (
        "CTS Environment Data\n"
        "====================\n"
        "Current state = WAITING_RESPONSE\n"
        "Last status = Failed\n"
        "Environment Data is empty\n"
        "State Machine is running\n"
        "Retry_timer (60 secs) is running\n")
    b = parse.parse_cts_environment_data(broken)
    assert b["state"] == "WAITING_RESPONSE" and b["last_status"] == "Failed" and b["sgt_count"] == 0
    # Absent / non-CTS -> {} (coverage-honest: nothing to assess).
    assert parse.parse_cts_environment_data("") == {}
    assert parse.parse_cts_environment_data("% Invalid input detected at '^' marker.") == {}


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
        "     1 37.37.37.3             10.0.1.3  NHRP 00:00:04     D\n"
        "     1 47.47.47.4             10.0.1.4  NHRP 48w0d        D\n"
        "     1 57.57.57.5             10.0.1.5  NHRP never        D\n")
    r = parse.parse_dmvpn_peers(out)
    assert len(r) == 5
    assert r[0] == {"interface": "Tunnel1", "nbma": "17.17.17.1", "tunnel_ip": "10.0.1.1", "state": "UP", "attrb": "S"}
    assert r[1]["tunnel_ip"] == "10.0.1.2" and r[1]["state"] == "IKE"
    assert r[2]["tunnel_ip"] == "10.0.1.3" and r[2]["state"] == "NHRP"
    # Aged (>=24h -> '48w0d', no HH:MM:SS) and 'never' UpDn times must NOT drop a broken peer (most common real case).
    assert r[3]["tunnel_ip"] == "10.0.1.4" and r[3]["state"] == "NHRP"
    assert r[4]["tunnel_ip"] == "10.0.1.5" and r[4]["state"] == "NHRP"
    # Legend / header / dashed-separator lines must NOT become peers (only the 5 real rows).
    assert [p["state"] for p in r] == ["UP", "IKE", "NHRP", "NHRP", "NHRP"]
    assert parse.parse_dmvpn_peers("") == []
    assert parse.parse_dmvpn_peers("% Incomplete command.") == []


def test_parse_crypto_sessions_states(cp):
    """Universality (IPsec encrypted WAN): parse_crypto_sessions reads 'show crypto session' so a session
    whose 'Session status' begins with DOWN (no established IKE/IPsec SA -> tunnel down) is detectable. Each
    'Interface:' opens a new record; the indented IKE SA / IPSEC FLOW / Active SAs lines never create phantom
    sessions, and the peer is captured without the trailing 'port 500'."""
    out = (
        "Crypto session current status\n"
        "\n"
        "Interface: Tunnel0\n"
        "Session status: UP-ACTIVE\n"
        "Peer: 10.0.255.2 port 500\n"
        "  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.2/500 Active\n"
        "  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.20.0/255.255.255.0\n"
        "        Active SAs: 2, origin: crypto map\n"
        "Interface: Tunnel1\n"
        "Session status: DOWN-NEGOTIATING\n"
        "Peer: 10.0.255.9 port 500\n"
        "  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.9/500 Inactive\n"
        "        Active SAs: 0, origin: crypto map\n")
    r = parse.parse_crypto_sessions(out)
    assert len(r) == 2
    assert r[0] == {"interface": "Tunnel0", "peer": "10.0.255.2", "status": "UP-ACTIVE"}
    assert r[1]["interface"] == "Tunnel1" and r[1]["peer"] == "10.0.255.9" and r[1]["status"] == "DOWN-NEGOTIATING"
    assert parse.parse_crypto_sessions("") == []


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
    # Real-world COLUMN DRIFT: a wide 32-bit discriminator overflows the LD/RD column, shifting every right-hand
    # column past its header position, so reading State by header CHAR-POSITION misreads it (lands on Holdown/Int).
    # Reading State by TOKEN (the column right after the Holdown paren token) stays correct under any drift.
    drift = (
        "OurAddr      NeighAddr    LD/RD       RH/RS   Holdown(mult)   State    Int       Vrf   Type\n"
        "2.16.2.1     2.16.2.2     1090519042/1090519042   Up    9193(5)    Up     Eth1/1    default  SH\n"
        "2.16.2.1     2.16.2.3     1090519044/1090519043   Up    8800(5)    Down   Eth2/1    default  SH\n")
    byd = {x["neighbor"]: x for x in parse.parse_bfd_neighbors(drift)}
    assert byd["2.16.2.2"]["state"] == "Up" and byd["2.16.2.2"]["interface"] == "Eth1/1"
    assert byd["2.16.2.3"]["state"] == "Down"   # the genuinely broken session must NOT be misread or lost
    assert parse.parse_bfd_neighbors("") == []
    assert parse.parse_bfd_neighbors("% BFD is not enabled\n") == []


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
    assert set(by) >= {"Vlan10", "Vlan30", "Gi0/2"}
    # Vlan10: one clean global + one TENTATIVE continuation address; NEITHER is a duplicate
    v10 = by["Vlan10"]
    assert v10["link_local_dup"] is False and v10["ipv6_enabled"] is True
    states10 = {g["addr"]: g["dad_state"] for g in v10["global"]}
    assert states10 == {"2001:DB8:10::1": "ok", "2001:DB8:10::2": "tentative"}
    # Vlan30: the global address AND the link-local are DUPLICATE
    v30 = by["Vlan30"]
    assert v30["link_local_dup"] is True
    assert v30["global"] == [{"addr": "1:4::1", "subnet": "1:4::/64", "dad_state": "duplicate"}]
    # admin-down IPv6-disabled interface: enabled False, no addresses, no false duplicate
    assert by["Gi0/2"]["ipv6_enabled"] is False and by["Gi0/2"]["global"] == []
    assert parse.parse_ipv6_interface_addrs("") == []


def test_parse_ipv6_interface_addrs_nxos_dad(cp):
    """parse_ipv6_interface_addrs must read the NX-OS 'show ipv6 interface' format (its '<intf>, Interface
    status: protocol-.../admin-...' header, the bare 'IPv6 address:' block, and 'IPv6 link-local address:'
    line all differ from IOS). Previously it returned [] for EVERY Nexus device -> a [DUPLICATE] DAD failure on
    the Nexus core (AJ's DS/CS tier is Nexus) was silently reported as clean."""
    out = (
        "Ethernet2/1, Interface status: protocol-up/link-up/admin-up, iod: 36\n"
        "  IPv6 address:\n"
        "    2001:db8:1::1/64 [VALID]\n"
        "    2001:db8:1::99/64 [DUPLICATE]\n"
        "  IPv6 link-local address: fe80::1 (default) [VALID]\n"
        "  IPv6 multicast routing is disabled\n"
        "Vlan20, Interface status: protocol-up/link-up/admin-up, iod: 40\n"
        "  IPv6 address:\n"
        "    2001:db8:20::1/64 [VALID]\n"
        "  IPv6 link-local address: fe80::20 [DUPLICATE]\n")
    r = parse.parse_ipv6_interface_addrs(out)
    by = {x["interface"]: x for x in r}
    assert set(by) >= {"Eth2/1", "Vlan20"}
    e = by["Eth2/1"]
    assert e["ipv6_enabled"] is True
    states = {g["addr"]: g["dad_state"] for g in e["global"]}
    assert states == {"2001:db8:1::1": "ok", "2001:db8:1::99": "duplicate"}
    assert e["link_local_dup"] is False
    # a DUPLICATE link-local (disables IPv6 packet processing on the whole interface) must be flagged
    assert by["Vlan20"]["link_local_dup"] is True


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


def test_parse_aci_faults_filters_and_normalizes(cp):
    """Universality (Cisco ACI / JSON-ingestion): parse_aci_faults json-loads an APIC 'moquery -c faultInst'
    export (imdata[].faultInst.attributes). severity/lc/ack are lower-cased for the detector's filter; a
    non-JSON or imdata-less payload yields [] (so a non-ACI fleet never cries wolf)."""
    out = (
        '{"totalCount": "2", "imdata": ['
        '{"faultInst": {"attributes": {"code": "F1394", "severity": "critical", "lc": "raised", "ack": "no", "dn": "topology/pod-1/node-101/fault-F1394", "descr": "Port is down"}}},'
        '{"faultInst": {"attributes": {"code": "F1234", "severity": "Minor", "lc": "raised", "ack": "no", "dn": "x", "descr": "minor"}}}'
        ']}')
    r = parse.parse_aci_faults(out)
    assert len(r) == 2
    assert r[0]["code"] == "F1394" and r[0]["severity"] == "critical" and r[0]["lc"] == "raised" and r[0]["ack"] == "no"
    assert r[1]["severity"] == "minor"          # normalized to lower-case
    assert parse.parse_aci_faults("") == []
    assert parse.parse_aci_faults("not json at all") == []
    assert parse.parse_aci_faults("{}") == []


def test_parse_aci_fabric_nodes_state(cp):
    """Universality (Cisco ACI): parse_aci_fabric_nodes reads 'moquery -c fabricNode' so a node whose
    fabricSt is not active (decommissioned/inactive) is detectable; fabricSt/adSt are lower-cased."""
    out = (
        '{"imdata": ['
        '{"fabricNode": {"attributes": {"id": "101", "name": "leaf-101", "role": "leaf", "fabricSt": "active", "adSt": "on", "dn": "topology/pod-1/node-101"}}},'
        '{"fabricNode": {"attributes": {"id": "102", "name": "leaf-102-OLD", "role": "leaf", "fabricSt": "Decommissioned", "adSt": "off", "dn": "topology/pod-1/node-102"}}}'
        ']}')
    r = parse.parse_aci_fabric_nodes(out)
    assert len(r) == 2
    assert r[0]["id"] == "101" and r[0]["fabric_st"] == "active"
    assert r[1]["name"] == "leaf-102-OLD" and r[1]["fabric_st"] == "decommissioned"
    assert parse.parse_aci_fabric_nodes("") == []


def test_parse_aci_health_score(cp):
    """Universality (Cisco ACI): parse_aci_health reads 'moquery -c fabricHealthTotal' -> {cur:int, max_sev}.
    A non-numeric / empty / imdata-less payload yields {} (never a false 'degraded')."""
    out = '{"imdata": [{"fabricHealthTotal": {"attributes": {"cur": "82", "maxSev": "critical"}}}]}'
    assert parse.parse_aci_health(out) == {"cur": 82, "max_sev": "critical"}
    assert parse.parse_aci_health("") == {}
    assert parse.parse_aci_health('{"imdata": []}') == {}


def test_parse_sdwan_control_connections_state(cp):
    """Universality (Cisco Catalyst SD-WAN / vManage JSON channel): parse_sdwan_control_connections reads the
    {"data":[...]} envelope so a control connection that is down (or actual < expected) is detectable; state
    is lower-cased and expected/actual are ints. Non-JSON / empty / data-less -> []."""
    out = (
        '{"data": ['
        '{"system-ip": "10.10.1.13", "host-name": "BR13-cedge", "peer-type": "vsmart", "state": "Down", "local-color": "mpls", "expected-connections": 2, "actual-connections": 0},'
        '{"system-ip": "10.10.1.13", "host-name": "BR13-cedge", "peer-type": "vbond", "state": "up", "expected-connections": 1, "actual-connections": 1}'
        ']}')
    r = parse.parse_sdwan_control_connections(out)
    assert len(r) == 2
    assert r[0]["peer_type"] == "vsmart" and r[0]["state"] == "down" and r[0]["expected"] == 2 and r[0]["actual"] == 0
    assert r[1]["state"] == "up"
    assert parse.parse_sdwan_control_connections("") == []
    assert parse.parse_sdwan_control_connections("not json") == []


def test_parse_sdwan_devices_reachability(cp):
    """Universality (Cisco Catalyst SD-WAN): parse_sdwan_devices reads vManage /dataservice/device so a device
    the Manager reports unreachable is detectable; reachability is lower-cased. Empty -> []."""
    out = (
        '{"data": ['
        '{"system-ip": "10.10.1.1", "host-name": "DC1-cedge", "reachability": "reachable", "device-model": "vedge-C8000V"},'
        '{"system-ip": "10.10.1.99", "host-name": "BR99-cedge", "reachability": "Unreachable", "device-model": "vedge-C8000V"}'
        ']}')
    r = parse.parse_sdwan_devices(out)
    assert len(r) == 2
    assert r[0]["host_name"] == "DC1-cedge" and r[0]["reachability"] == "reachable"
    assert r[1]["reachability"] == "unreachable"
    assert parse.parse_sdwan_devices("") == []


def test_parse_sdwan_omp_counters(cp):
    """Universality (Cisco Catalyst SD-WAN OMP): parse_sdwan_omp_counters reads vManage
    /dataservice/device/counters so an edge with ompPeersDown > 0 (overlay routing degraded) is detectable;
    omp_up/omp_down are coerced to ints. Empty / non-JSON -> []."""
    out = (
        '{"data": ['
        '{"system-ip": "10.10.1.13", "host-name": "BR13", "ompPeersUp": 1, "ompPeersDown": 1},'
        '{"system-ip": "10.10.1.1", "host-name": "DC1", "ompPeersUp": 2, "ompPeersDown": 0}'
        ']}')
    r = parse.parse_sdwan_omp_counters(out)
    assert len(r) == 2
    assert r[0]["host_name"] == "BR13" and r[0]["omp_up"] == 1 and r[0]["omp_down"] == 1
    assert r[1]["omp_down"] == 0
    assert parse.parse_sdwan_omp_counters("") == []


def test_parse_aci_vrfs_enforcement(cp):
    """Universality (Cisco ACI logical inventory): parse_aci_vrfs reads 'moquery -c fvCtx' so a VRF with
    contract enforcement UNENFORCED (default-permit between EPGs) is detectable; the tenant is parsed from the
    dn (uni/tn-<tenant>/ctx-<name>); pcEnfPref is lower-cased."""
    out = (
        '{"imdata": ['
        '{"fvCtx": {"attributes": {"name": "prod-vrf", "dn": "uni/tn-PROD/ctx-prod-vrf", "pcEnfPref": "enforced"}}},'
        '{"fvCtx": {"attributes": {"name": "legacy-vrf", "dn": "uni/tn-LEGACY/ctx-legacy-vrf", "pcEnfPref": "Unenforced"}}}'
        ']}')
    r = parse.parse_aci_vrfs(out)
    assert len(r) == 2
    assert r[0] == {"name": "prod-vrf", "tenant": "PROD", "dn": "uni/tn-PROD/ctx-prod-vrf", "pc_enf_pref": "enforced", "pc_enf_dir": ""}
    assert r[1]["tenant"] == "LEGACY" and r[1]["pc_enf_pref"] == "unenforced"
    assert parse.parse_aci_vrfs("") == []


def test_parse_aci_logical_census(cp):
    """Universality (Cisco ACI logical census / move-group scoping): the tenant/BD/EPG inventory parsers read
    'moquery -c fvTenant/fvBD/fvAEPg'. Pure inventory (the migration move-group units); tenant is parsed from
    the dn. Empty -> []."""
    assert parse.parse_aci_tenants('{"imdata":[{"fvTenant":{"attributes":{"name":"PROD","dn":"uni/tn-PROD"}}}]}') == [{"name": "PROD", "dn": "uni/tn-PROD"}]
    bds = parse.parse_aci_bds('{"imdata":[{"fvBD":{"attributes":{"name":"prod-bd","dn":"uni/tn-PROD/BD-prod-bd","unicastRoute":"yes","arpFlood":"no"}}}]}')
    assert bds[0]["name"] == "prod-bd" and bds[0]["tenant"] == "PROD" and bds[0]["unicast_route"] == "yes"
    epgs = parse.parse_aci_epgs('{"imdata":[{"fvAEPg":{"attributes":{"name":"web-epg","dn":"uni/tn-PROD/ap-app/epg-web-epg"}}}]}')
    assert epgs[0]["name"] == "web-epg" and epgs[0]["tenant"] == "PROD"
    assert parse.parse_aci_tenants("") == [] and parse.parse_aci_bds("") == [] and parse.parse_aci_epgs("") == []


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
    # IOS-XE Catalyst 9000: Type is fused into the Mode (L2CP/L3CP) and the next column is the VLAN/BD number,
    # so the NX-OS regex (which needs a bare L2/L3 token there) returned [] for every IOS-XE VTEP.
    iosxe = (
        "Interface VNI       Multicast-group   VNI state Mode VLAN cfg vrf\n"
        "nve1      10306     N/A               Up        L3CP 306      CLI\n"
        "nve1      20100     239.1.1.1         Down      L2CP 100      -\n")
    byv = {x["vni"]: x for x in parse.parse_nve_vni(iosxe)}
    assert byv["10306"]["state"] == "Up" and byv["10306"]["type"] == "L3" and byv["10306"]["mode"] == "CP"
    assert byv["20100"]["state"] == "Down" and byv["20100"]["type"] == "L2" and byv["20100"]["mcast_group"] == "239.1.1.1"
    assert parse.parse_nve_vni("") == []


def test_parse_copp_drops_nxos_and_iosxe(cp):
    """Universality (control-plane policing): the engine had no CoPP visibility. parse_copp_drops reads
    'show policy-map [interface] control-plane' on BOTH NX-OS (bytes, module blocks) and IOS/IOS-XE (packets,
    actions: drop) so a CoPP class actively DROPPING punted traffic (drops > 0) becomes detectable; rate lines
    and the policer cir/bc config line are never miscounted."""
    nxos = (
        "    class-map copp-system-p-class-critical (match-any)\n"
        "      police cir 36000 kbps bc 250 ms\n"
        "      module 1:\n"
        "        conformed 177446058 bytes,\n"
        "          5-min offered rate 3 bytes/sec\n"
        "        violated 4521 bytes,\n"
        "          5-min violate rate 12 bytes/sec\n"
        "    class-map copp-system-p-class-normal (match-any)\n"
        "      module 1:\n"
        "        conformed 88231005 bytes,\n"
        "        violated 0 bytes,\n")
    by = {c["class"]: c for c in parse.parse_copp_drops(nxos)}
    assert by["copp-system-p-class-critical"]["violated"] == 4521
    assert by["copp-system-p-class-critical"]["drops"] == 4521
    assert by["copp-system-p-class-normal"]["drops"] == 0
    assert by["copp-system-p-class-critical"]["conformed"] == 177446058
    iosxe = (
        "    Class-map: copp-class-bgp (match-any)\n"
        "      120 packets, 7680 bytes\n"
        "      police:\n"
        "          cir 8000 bps, bc 1500 bytes\n"
        "        conformed 15 packets, 6210 bytes; actions: transmit\n"
        "        exceeded 5 packets, 5070 bytes; actions: drop\n"
        "        violated 2 packets, 140 bytes; actions: drop\n"
        "    Class-map: class-default (match-any)\n"
        "        conformed 0 packets, 0 bytes; actions: transmit\n"
        "        exceeded 0 packets, 0 bytes; actions: drop\n")
    byx = {c["class"]: c for c in parse.parse_copp_drops(iosxe)}
    assert byx["copp-class-bgp"]["exceeded"] == 5 and byx["copp-class-bgp"]["violated"] == 2
    assert byx["copp-class-bgp"]["drops"] == 7 and byx["class-default"]["drops"] == 0
    # NX-OS one-line module form: 'module N : transmitted X bytes; dropped Y bytes;' -- the drop counter is NOT
    # at line start, so the old ^-anchored match silently missed it (CoPP-drop blindness on Nexus, CoPP default).
    nx_oneline = (
        "    class-map copp-system-p-class-important (match-any)\n"
        "      police cir 2500 kbps bc 1000 ms\n"
        "      module 1 : transmitted 13818516 bytes; dropped 84348 bytes;\n"
        "      module 2 : transmitted 0 bytes; dropped 0 bytes;\n")
    byo = {c["class"]: c for c in parse.parse_copp_drops(nx_oneline)}
    assert byo["copp-system-p-class-important"]["dropped"] == 84348
    assert byo["copp-system-p-class-important"]["drops"] == 84348
    assert parse.parse_copp_drops("") == [] and parse.parse_copp_drops("% policy-map not configured\n") == []


# ============================ architecture-coverage slices (build wave) =========================== #
def test_parse_pim_rp_mapping_learned_static_ssm_and_broken(cp):
    """PIM-SM RP learning: parse_pim_rp_mapping reads 'show ip pim rp mapping' across IOS Auto-RP (multi-line),
    IOS static (single-line), NX-OS multi-RP, header-only (running but 0 RP -> the broken state), and SSM-only
    (0 RP but HEALTHY). 'present' distinguishes 'collected, no RP' from 'not collected' ({})."""
    autorp = textwrap.dedent("""\
        PIM Group-to-RP Mappings
        Group(s) 224.0.0.0/4
          RP 10.10.205.20 (?), v2v1
            Info source: 10.10.105.20 (?), elected via Auto-RP
                 Uptime: 00:12:02, expires: 00:00:53
    """)
    r = parse.parse_pim_rp_mapping(autorp)
    assert r["present"] is True and r["rp_count"] == 1 and r["rps"][0]["rp"] == "10.10.205.20"
    assert r["rps"][0]["group"] == "224.0.0.0/4" and r["rps"][0]["source"] == "10.10.105.20" and r["ssm_only"] is False
    static = "PIM Group-to-RP Mappings\nGroup(s): 224.0.0.0/4, Static RP: 192.168.7.2 (?)\n"
    rs = parse.parse_pim_rp_mapping(static)
    assert rs["rp_count"] == 1 and rs["rps"][0]["rp"] == "192.168.7.2" and rs["rps"][0]["group"] == "224.0.0.0/4"
    nxos = textwrap.dedent("""\
        PIM Group-to-RP Mappings
        Group(s) 239.1.0.0/16, uptime: 1d02h, expires: never,
          RP: 10.0.0.1, (local), via static
        Group(s) 239.2.0.0/16, uptime: 1d02h, expires: never,
          RP: 10.0.0.2, via bsr
    """)
    rn = parse.parse_pim_rp_mapping(nxos)
    assert rn["rp_count"] == 2 and {x["rp"] for x in rn["rps"]} == {"10.0.0.1", "10.0.0.2"}
    broken = parse.parse_pim_rp_mapping("PIM Group-to-RP Mappings\n\n")
    assert broken["present"] is True and broken["rp_count"] == 0 and broken["ssm_only"] is False
    ssm = parse.parse_pim_rp_mapping("PIM Group-to-RP Mappings\nGroup(s) 232.0.0.0/8\n  (SSM, no RP required)\n")
    assert ssm["present"] is True and ssm["rp_count"] == 0 and ssm["ssm_only"] is True
    assert parse.parse_pim_rp_mapping("") == {} and parse.parse_pim_rp_mapping("% Invalid input detected") == {}


def test_parse_pim_neighbors_ios_and_nxos(cp):
    """parse_pim_neighbors reads 'show ip pim neighbor' on IOS (combined Uptime/Expires) and NX-OS (separate
    columns), skipping the legend/header, and normalises interfaces to the short canonical form. [] on empty."""
    ios = textwrap.dedent("""\
        PIM Neighbor Table
        Mode: B - Bidir Capable, DR - Designated Router, N - Default DR Priority
        Neighbor          Interface                Uptime/Expires    Ver   DR
        Address                                                            Prio/Mode
        192.168.12.2      GigabitEthernet0/1       00:00:17/00:01:27 v2    1 / DR S P G
        192.168.14.4      GigabitEthernet0/2       00:00:15/00:01:29 v2    1 / DR S P G
        3.3.3.3           Tunnel0                  00:16:40/00:01:20 v2    1 / DR S P G
    """)
    rows = parse.parse_pim_neighbors(ios)
    assert len(rows) == 3 and rows[0]["neighbor"] == "192.168.12.2" and rows[0]["interface"] == "Gi0/1"
    assert rows[0]["uptime"] == "00:00:17"
    # PIM over a Tunnel (DMVPN/mGRE multicast WAN) must NOT be dropped by the interface-validity gate
    assert rows[2]["interface"] == "Tu0" and rows[2]["neighbor"] == "3.3.3.3"
    nxos = textwrap.dedent("""\
        PIM Neighbor Status for VRF "default"
        Neighbor       Interface            Uptime    Expires   DR    Bidir-  BFD
                                                                Priority Capable State
        192.0.2.2      port-channel2000     03:43:40  00:01:21  1     no      n/a
        192.0.2.1      Ethernet1/26         03:43:44  00:01:33  1     no      n/a
    """)
    rn = parse.parse_pim_neighbors(nxos)
    assert len(rn) == 2 and rn[0]["interface"] == "Po2000" and rn[1]["interface"] == "Eth1/26"
    assert parse.parse_pim_neighbors("") == []
    assert parse.parse_pim_neighbors("PIM Neighbor Table\nNeighbor Interface Uptime\n") == []


def test_parse_ipv6_raguard_and_dhcp_guard_policy(cp):
    """IPv6 first-hop security: 'show ipv6 nd raguard policy' -> policy/device-role/trusted/PORT-VLAN targets;
    'show ipv6 dhcp guard policy' -> policy/device-role/targets (interface tokens or 'vlan N' list). [] on empty."""
    ra = textwrap.dedent("""\
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
    r = parse.parse_ipv6_raguard_policy(ra)
    by = {p["policy"]: p for p in r}
    assert by["HOSTS"]["device_role"] == "host" and by["HOSTS"]["trusted"] is False
    assert by["HOSTS"]["targets"] == [{"name": "Gi0/2", "type": "PORT"}]
    assert by["UPLINK"]["device_role"] == "router" and by["UPLINK"]["trusted"] is True
    assert parse.parse_ipv6_raguard_policy("") == []
    assert parse.parse_ipv6_raguard_policy("% Invalid input detected at '^' marker.") == []
    dh = textwrap.dedent("""\
        Dhcp guard policy: default
          Device Role: dhcp client
          Target: Et0/3
        Dhcp guard policy: test1
          Device Role: dhcp server
          Target: vlan 0 vlan 1 vlan 2
        Dhcp guard policy: test2
          Device Role: dhcp relay
          Target: Et0/0 Et0/1
    """)
    rd = parse.parse_ipv6_dhcp_guard_policy(dh)
    byd = {p["policy"]: p for p in rd}
    assert byd["default"]["device_role"] == "client" and byd["default"]["targets"] == [{"name": "Et0/3", "type": "PORT"}]
    assert byd["test1"]["device_role"] == "server"
    assert byd["test1"]["targets"] == [{"name": "0", "type": "VLAN"}, {"name": "1", "type": "VLAN"}, {"name": "2", "type": "VLAN"}]
    assert byd["test2"]["device_role"] == "relay" and len(byd["test2"]["targets"]) == 2
    assert parse.parse_ipv6_dhcp_guard_policy("") == []


def test_parse_ntp_status_ios_and_nxos(cp):
    """Clock-sync STATE: IOS 'show ntp status' first line is authoritative (synchronized + stratum + reference;
    British spelling tolerated); NX-OS 'show ntp peer-status' uses a '*'-selected peer (its 'st' = stratum), and
    a populated table with NO '*' means unsynchronized (stratum 16). {} on absence (never inferred unsynced)."""
    bad = ("Clock is unsynchronized, stratum 16, no reference clock\n"
           "nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18\n")
    r = parse.parse_ntp_status(bad)
    assert r["synchronized"] is False and r["stratum"] == 16 and r["source"] == "ios-status"
    good = "Clock is synchronized, stratum 3, reference is 10.0.10.2\n"
    g = parse.parse_ntp_status(good)
    assert g["synchronized"] is True and g["stratum"] == 3 and g["reference"] == "10.0.10.2"
    assert parse.parse_ntp_status("Clock is synchronised, stratum 2, reference is 1.2.3.4")["synchronized"] is True
    assert parse.parse_ntp_status("") == {} and parse.parse_ntp_status("% NTP is not enabled.") == {}
    synced = ("Total peers : 2\n"
              "* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client mode\n"
              "remote               local                st  poll reach delay   vrf\n"
              "-------------------------------------------------------------------------------\n"
              "*10.255.0.254        10.255.0.7           2   16   377   0.00107 default\n"
              "=127.127.1.0         10.255.0.7           8   16   377   0.00000 default\n")
    rs = parse.parse_ntp_status(synced)
    assert rs["synchronized"] is True and rs["stratum"] == 2 and rs["reference"] == "10.255.0.254"
    assert rs["source"] == "nxos-peer-status"
    nosync = ("Total peers : 1\n"
              "* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client mode\n"
              "remote               local                st  poll reach delay   vrf\n"
              "-------------------------------------------------------------------------------\n"
              "=10.255.0.254        10.255.0.7           16  64   0     0.00000 default\n")
    n = parse.parse_ntp_status(nosync)
    assert n["synchronized"] is False and n["stratum"] == 16


def test_parse_port_security_detail_secure_shutdown_vs_restrict(cp):
    """Access-edge port-security DETAIL: parse_port_security_detail reads 'show port-security interface' so a
    shutdown-mode violation -> Port Status 'secure-shutdown' (a live outage with an offending MAC) is captured,
    distinct from a restrict-mode port that stays 'secure-up' while counting. Interface name precedes each block."""
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
    assert g3["enabled"] is True and g3["port_status"] == "secure-shutdown"
    assert g3["violation_mode"] == "Shutdown" and g3["violation_count"] == 3
    assert g3["last_src"] == "0011.22aa.0099" and g3["last_vlan"] == "10"
    g10 = r["Gi0/10"]
    assert g10["port_status"] == "secure-up" and g10["violation_mode"] == "Restrict" and g10["violation_count"] == 17
    assert parse.parse_port_security_detail("") == {}
    assert parse.parse_port_security_detail("random noise\nnot a detail block") == {}


def test_parse_storm_control_actions_and_legacy_form(cp):
    """Storm-control: the modern 'Action + Type(B/M/U)' form yields the per-traffic action ('None' = the toothless
    gap, Trap/Shutdown actioned), and the older leading-Type form (no Action column) yields action '' (so the
    detector, firing only on action 'None', correctly stays silent on that form). configured=True iff Upper present."""
    out = (
        "Key: U - Unicast, B - Broadcast, M - Multicast\n"
        "Interface Filter State   Upper       Lower       Current    Action    Type\n"
        "--------- ------------- ----------- ----------- ---------- --------- ----\n"
        "Gi0/2     Forwarding    5.00%       5.00%       0.12%      None      B\n"
        "Gi0/3     Forwarding    2.00%       2.00%       0.05%      Shutdown  B\n"
        "Gi0/4     Link Down     50k bps     40k bps     0 bps      Trap      M\n")
    r = parse.parse_storm_control(out)
    assert len(r) == 3
    assert r[0] == {"interface": "Gi0/2", "traffic": "broadcast", "filter_state": "Forwarding",
                    "upper": "5.00%", "lower": "5.00%", "current": "0.12%", "action": "None", "configured": True}
    assert r[1]["action"] == "Shutdown" and r[1]["traffic"] == "broadcast"
    assert r[2]["filter_state"] == "Link Down" and r[2]["action"] == "Trap" and r[2]["upper"] == "50k"
    assert parse.parse_storm_control("") == []
    legacy = (
        "Interface Type    Filter State    Upper       Lower       Current\n"
        "--------- ------  -------------   ----------- ----------- ----------\n"
        "Gi0/0/1   Bcast   Blocking        50k bps     40k bps     362.25k bps\n"
        "Gi0/0/1   Ucast   Forwarding      1.00%       0.50%       1.28%\n")
    rl = parse.parse_storm_control(legacy)
    assert len(rl) == 2
    assert rl[0]["traffic"] == "broadcast" and rl[0]["filter_state"] == "Blocking"
    assert rl[0]["upper"] == "50k" and rl[0]["action"] == "" and rl[0]["configured"] is True
    assert rl[1]["traffic"] == "unicast" and rl[1]["action"] == ""


def test_parse_policymap_drops_iosxe_and_nxos(cp):
    """QoS RUNTIME: parse_policymap_drops reads 'show policy-map interface' EGRESS-only across the IOS-XE dialect
    (priority/LLQ queue drops, bandwidth class, policer 'exceeded' block, clean class) and the NX-OS queuing form
    ('Class-map (queuing):', 'queue dropped/transmit pkts'). The input direction is ignored."""
    iosxe = textwrap.dedent("""\
        GigabitEthernet0/0/0

          Service-policy input: MARK-IN

            Class-map: SCAVENGER-IN (match-any)
              Queueing
              (queue depth/total drops/no-buffer drops) 0/999999/0
              (pkts output/bytes output) 1/1

          Service-policy output: WAN-EDGE-OUT

            Class-map: VOICE (match-any)
              2348138 packets, 1202246656 bytes
              Match: dscp ef (46)
              Queueing
              priority level 1
              queue limit 512 packets
              (queue depth/total drops/no-buffer drops) 49476/44577300/0
              (pkts output/bytes output) 2348138/1202246656

            Class-map: BULK (match-any)
              3000453 packets, 262033259 bytes
              Match: dscp af11 (10)
              Queueing
              queue limit 525000 bytes
              (queue depth/total drops/no-buffer drops) 0/250/0
              (pkts output/bytes output) 3000454/262033337
              bandwidth remaining 30%

            Class-map: SCAVENGER (match-any)
              9000 packets, 8000 bytes
              police: cir 1000000 bps, bc 31250 bytes
                conformed 5000 packets, 4000 bytes; action: transmit
                exceeded 4000 packets, 3500 bytes; action: drop
                violated 0 packets, 0 bytes; action: drop

            Class-map: class-default (match-any)
              100 packets, 9000 bytes
              Queueing
              queue limit 416 packets
              (queue depth/total drops/no-buffer drops) 0/0/0
              (pkts output/bytes output) 100/9000
    """)
    r = parse.parse_policymap_drops(iosxe)
    assert [c["class"] for c in r] == ["VOICE", "BULK", "SCAVENGER", "class-default"]
    assert all(c["interface"] == "Gi0/0/0" and c["policy"] == "WAN-EDGE-OUT" for c in r)
    assert r[0]["priority"] is True and r[0]["drop_pkts"] == 44577300 and r[0]["output_pkts"] == 2348138
    assert r[1]["priority"] is False and r[1]["drop_pkts"] == 250 and r[1]["output_pkts"] == 3000454
    assert r[2]["police_drop_pkts"] == 4000 and r[2]["police_drop_bytes"] == 3500 and r[2]["drop_pkts"] == 0
    assert r[3]["drop_pkts"] == 0 and r[3]["output_pkts"] == 100
    assert parse.parse_policymap_drops("") == [] and parse.parse_policymap_drops("% Incomplete command") == []
    nxos = textwrap.dedent("""\
        port-channel6
        Service-policy (queuing) output: out-q-policy

        Class-map (queuing): q1 (match-any)
        priority level 1
        queue dropped pkts: 12345
        queue dropped bytes: 678900
        queue transmit pkts: 2175032764
        queue transmit bytes: 1051188564890

        Class-map (queuing): q-default (match-any)
        bandwidth percent 49
        queue dropped pkts: 0
        queue dropped bytes: 0
        queue transmit pkts: 518903560636
    """)
    rn = parse.parse_policymap_drops(nxos)
    assert [c["class"] for c in rn] == ["q1", "q-default"]
    assert all(c["interface"] == "Po6" for c in rn)
    assert rn[0]["priority"] is True and rn[0]["drop_pkts"] == 12345 and rn[0]["output_pkts"] == 2175032764
    assert rn[1]["drop_pkts"] == 0 and rn[1]["priority"] is False


def test_parse_neighbors_detail_cdp_and_lldp_keep_capabilities(cp):
    """Shadow-infra discovery: parse_neighbors_detail KEEPS the capability codes the topology-link parsers drop
    (CDP 'Router Switch' words; LLDP 'B,R' letters) so an undocumented switch/router is distinguishable from a
    CDP/LLDP-speaking phone or AP. [] on empty."""
    cdp = (
        "-------------------------\n"
        "Device ID: dist-core-7.lab\n"
        "  IP address: 10.0.0.7\n"
        "Platform: cisco N9K-C93180YC-EX,  Capabilities: Router Switch\n"
        "Interface: Ethernet1/47,  Port ID (outgoing port): Ethernet1/1\n"
        "-------------------------\n"
        "Device ID: SEP00112233AABB\n"
        "  IP address: 10.0.40.20\n"
        "Platform: Cisco IP Phone 8845,  Capabilities: Host Phone\n"
        "Interface: GigabitEthernet1/0/20,  Port ID (outgoing port): Port 1\n")
    rc = parse.parse_neighbors_detail(cdp, "cdp")
    assert len(rc) == 2
    assert rc[0]["device_id"] == "dist-core-7.lab" and rc[0]["capabilities"] == "Router Switch"
    assert rc[0]["platform"] == "cisco N9K-C93180YC-EX" and rc[0]["local_intf"] == "Eth1/47"
    assert rc[0]["remote_port"] == "Eth1/1" and rc[0]["mgmt_ip"] == "10.0.0.7" and rc[0]["proto"] == "cdp"
    assert rc[1]["device_id"] == "SEP00112233AABB" and rc[1]["capabilities"] == "Host Phone"
    assert parse.parse_neighbors_detail("", "cdp") == []
    lldp = (
        "Local Intf: Gi1/0/47\n"
        "Chassis id: 00aa.bbcc.ddee\n"
        "Port id: Gi1/0/1\n"
        "System Name: agg-sw-2\n"
        "System Description: Cisco IOS Software, C9300\n"
        "System Capabilities: B,R\n"
        "Enabled Capabilities: B,R\n"
        "Management Addresses:\n"
        "  IP: 10.0.0.8\n"
        "\n"
        "Local Intf: Gi1/0/20\n"
        "Port id: 1\n"
        "System Name: phone-2\n"
        "System Capabilities: T\n"
        "Enabled Capabilities: T\n")
    rl = parse.parse_neighbors_detail(lldp, "lldp")
    assert len(rl) == 2
    assert rl[0]["device_id"] == "agg-sw-2" and rl[0]["capabilities"] == "B,R"
    assert rl[0]["local_intf"] == "Gi1/0/47" and rl[0]["remote_port"] == "Gi1/0/1" and rl[0]["proto"] == "lldp"
    assert rl[1]["device_id"] == "phone-2" and rl[1]["capabilities"] == "T"
    assert parse.parse_neighbors_detail("", "lldp") == []


def test_parse_neighbors_detail_nxos(cp):
    """NX-OS LLDP detail has NO 'Local Intf:' (the local interface is on a 'Local Port id:' line and each block
    begins with 'Chassis id:'). The old split-on-'Local Intf:' returned ONE Frankenstein record for N neighbours,
    feeding the shadow-infra detector garbage on every Nexus switch (AJ's core is Nexus). NX-OS CDP also reports
    'IPv4 Address:' (not IOS 'IP address:'). Both must parse one correct record per neighbour."""
    lldp = (
        "Chassis id: 547f.eeab.0001\n"
        "Port id: Ethernet1/1\n"
        "Local Port id: Eth1/2\n"
        "System Name: spine-1\n"
        "System Description: Cisco Nexus Operating System (NX-OS) Software\n"
        "Enabled Capabilities: B, R\n"
        "Management Address: 10.0.0.1\n"
        "\n"
        "Chassis id: 547f.eeab.0002\n"
        "Port id: Ethernet2/2\n"
        "Local Port id: Eth2/2\n"
        "System Name: leaf-9\n"
        "System Description: Cisco Nexus 9000\n"
        "Enabled Capabilities: B, R\n"
        "Management Address: 10.0.0.9\n")
    rl = parse.parse_neighbors_detail(lldp, "lldp")
    assert len(rl) == 2
    by = {x["local_intf"]: x for x in rl}
    assert set(by) == {"Eth1/2", "Eth2/2"}
    assert by["Eth1/2"]["device_id"] == "spine-1" and by["Eth1/2"]["remote_port"] == "Eth1/1"
    assert by["Eth1/2"]["capabilities"] == "B, R" and by["Eth1/2"]["mgmt_ip"] == "10.0.0.1"
    assert by["Eth2/2"]["device_id"] == "leaf-9"
    nxcdp = (
        "----------------------------------------\n"
        "Device ID: core-nexus.lab(FOX1234)\n"
        "  IPv4 Address: 10.0.0.2\n"
        "Platform: N9K-C9504,  Capabilities: Router Switch\n"
        "Interface: Ethernet1/1,  Port ID (outgoing port): Ethernet1/2\n")
    rc = parse.parse_neighbors_detail(nxcdp, "cdp")
    assert len(rc) == 1 and rc[0]["mgmt_ip"] == "10.0.0.2" and rc[0]["local_intf"] == "Eth1/1"
