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
