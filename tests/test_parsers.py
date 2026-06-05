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
