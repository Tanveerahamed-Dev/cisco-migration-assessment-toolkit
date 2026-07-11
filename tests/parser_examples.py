"""[K2] PARSER_EXAMPLES -- the real-output example registry for cisco_toolkit.parse.

The #1 recurring bug class in this toolkit: an unseen platform variant (NX-OS vs IOS vs
IOS-XE formatting) parses to []/{} and silently reads as feature-absent. This registry
pins one-or-more VERBATIM real-output blocks per parser (anonymized to the
tests/test_audit5_parse_fidelity.py precedent: hostnames -> CS01/NBR-A.example.tv style,
secrets/communities scrubbed, structure untouched) and replays them forever via
tests/test_parser_examples.py.

Registry shape:
    PARSER_EXAMPLES: dict[parser_name -> list[example]]
    example = {
        "input":               verbatim real block fed to the parser (str),
        "expect_min_entities": minimum len(result) the parser must yield (int),
        "spot_facts":          [(path, value), ...] -- path is a tuple of dict-keys /
                               list-indices resolved into the result; the leaf must
                               equal value exactly,
        # optional:
        "prefix_args":         positional args passed BEFORE input (multi-arg parsers),
        "note":                provenance / platform-variant note,
    }

v1 note: the seed examples below are lifted from tests/test_audit5_parse_fidelity.py
(left untouched on purpose -- duplication between the two files is accepted for v1 so a
refactor there can never silently weaken this registry).
"""

# Real CS01 'show spanning-tree' slice (NX-OS RSTP, vPC peer-link rows) -- shared by the
# root-bridge and port-state parsers below.
_STP_REAL_BLOCK = (
    "\n"
    "VLAN0001\n"
    "  Spanning tree enabled protocol rstp\n"
    "  Root ID    Priority    32769\n"
    "             Address     0023.04ee.be13\n"
    "             This bridge is the root\n"
    "             Hello Time  2  sec  Max Age 20 sec  Forward Delay 15 sec\n"
    "\n"
    "  Bridge ID  Priority    32769  (priority 32768 sys-id-ext 1)\n"
    "             Address     0023.04ee.be13\n"
    "             Hello Time  2  sec  Max Age 20 sec  Forward Delay 15 sec\n"
    "\n"
    "Interface        Role Sts Cost      Prio.Nbr Type\n"
    "---------------- ---- --- --------- -------- --------------------------------\n"
    "Po1              Root FWD 250       128.4096 (vPC peer-link) Network P2p \n"
    "Po15             Desg FWD 200       128.4110 (vPC) P2p \n"
    "Po16             Desg FWD 200       128.4111 (vPC) P2p \n"
    "\n"
    "\n"
    "VLAN0012\n"
    "  Spanning tree enabled protocol rstp\n"
    "  Root ID    Priority    12\n"
    "             Address     0023.04ee.be13\n"
    "             This bridge is the root\n"
    "             Hello Time  2  sec  Max Age 20 sec  Forward Delay 15 sec\n"
    "\n"
    "  Bridge ID  Priority    12     (priority 0 sys-id-ext 12)\n"
    "             Address     0023.04ee.be13\n"
    "             Hello Time  2  sec  Max Age 20 sec  Forward Delay 15 sec\n"
    "\n"
    "Interface        Role Sts Cost      Prio.Nbr Type\n"
    "---------------- ---- --- --------- -------- --------------------------------\n"
    "Po1              Desg FWD 250       128.4096 (vPC peer-link) Network P2p \n"
    "Po15             Desg FWD 200       128.4110 (vPC) P2p \n"
    "Po31             Desg FWD 200       128.4126 (vPC) P2p \n"
)

PARSER_EXAMPLES = {
    # ------------------------------------------------------------------ multicast / PIM
    "parse_multicast_info": [
        {
            "note": "NX-OS verbose 'show ip pim interface' stanza (real CS01 shape); "
                    "signature is (mroute_out, pim_out) so the pim block rides behind "
                    "an empty mroute arg.",
            "prefix_args": ("",),
            "input": (
                'PIM Interface Status for VRF "default"\n'
                'Vlan64, Interface status: protocol-up/link-up/admin-up\n'
                '  IP address: 10.203.64.2, IP subnet: 10.203.64.0/24\n'
                "  PIM DR: 10.203.64.3, DR's priority: 1\n"
                '  PIM neighbor count: 1\n'
                'Vlan28, Interface status: protocol-up/link-up/admin-up\n'
                '  IP address: 10.203.28.2, IP subnet: 10.203.28.0/24\n'
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                (("Vlan64",), "PIM enabled"),
                (("Vlan28",), "PIM enabled"),
            ],
        },
    ],
    # ------------------------------------------------------------------ security posture
    "parse_security": [
        {
            "note": "NX-OS Type-5 users (STRONG, must not flag) + no "
                    "'service password-encryption' (IOS-only cmd -> N/A). Real CS01 "
                    "shapes; hashes are fabricated fixture values.",
            "input": (
                "feature ospf\n"
                "feature interface-vlan\n"
                "username admin password 5 $1$REDACTED$0000000000000000000000  role network-admin\n"
                "username swadmin password 5 $1$SCRUBBED$1111111111111111111111  role vdc-operator\n"
            ),
            "expect_min_entities": 1,
            # findings order is deterministic (registry order inside parse_security)
            "spot_facts": [
                (("findings", 0, "id"), "password-encryption"),
                (("findings", 0, "status"), "na"),   # IOS-only cmd: N/A, not a false FAIL
                (("findings", 6, "id"), "weak-user-pw"),
                (("findings", 6, "status"), "pass"),  # Type-5 users are strong
            ],
        },
    ],
    # ------------------------------------------------------------------ neighbors
    "parse_neighbors_cdp": [
        {
            "note": "NX-OS 'show cdp neighbors detail' uses 'IPv4 Address:' not IOS "
                    "'IP address:'. Real CS01 shape, anonymized neighbor names.",
            "input": (
                "----------------------------------------\n"
                "Device ID:NBR-A.example.tv\n"
                "Interface: Ethernet1/1,  Port ID (outgoing port): Ethernet1/2\n"
                "    IPv4 Address: 10.200.200.222\n"
                "----------------------------------------\n"
                "Device ID:NBR-B.example.tv\n"
                "Interface: Ethernet1/3,  Port ID (outgoing port): Ethernet1/4\n"
                "    IPv4 Address: 10.200.200.223\n"
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                (("Eth1/1", "device_id"), "NBR-A.example.tv"),
                (("Eth1/1", "mgmt_ip"), "10.200.200.222"),
                (("Eth1/3", "mgmt_ip"), "10.200.200.223"),
            ],
        },
        {
            "note": "FULL real NX-OS 'show cdp neighbors detail' blocks (VTP domain, "
                    "Version stanza, Platform+Capabilities, Mgmt address). Device IDs / "
                    "VTP domain anonymized, structure verbatim from CS01.",
            "input": (
                "----------------------------------------\n"
                "Device ID:AS-NBR-A.example.tv\n"
                "VTP Management Domain Name: EXAMPLE-DOM\n"
                "\n"
                "Interface address(es):\n"
                "    IPv4 Address: 10.200.200.222\n"
                "Platform: C9300-48T, Capabilities: Switch IGMP Filtering \n"
                "Interface: Ethernet1/15, Port ID (outgoing port): TenGigabitEthernet1/1/1\n"
                "Holdtime: 132 sec\n"
                "\n"
                "Version:\n"
                "Cisco IOS Software [Everest], Catalyst L3 Switch Software (CAT9K_IOSXE), "
                "Version 16.6.7, RELEASE SOFTWARE (fc2)\n"
                "\n"
                "Advertisement Version: 2\n"
                "\n"
                "Native VLAN: 1\n"
                "Duplex: full\n"
                "Mgmt address(es):\n"
                "    IPv4 Address: 10.200.200.222\n"
                "----------------------------------------\n"
                "Device ID:AS-NBR-B.example.tv\n"
                "VTP Management Domain Name: EXAMPLE-DOM\n"
                "\n"
                "Interface address(es):\n"
                "    IPv4 Address: 10.200.200.223\n"
                "Platform: WS-C3850-48T, Capabilities: Router Switch IGMP Filtering \n"
                "Interface: Ethernet1/16, Port ID (outgoing port): TenGigabitEthernet1/1/3\n"
                "Holdtime: 169 sec\n"
                "\n"
                "Native VLAN: 1\n"
                "Duplex: full\n"
                "Mgmt address(es):\n"
                "    IPv4 Address: 10.200.200.223\n"
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                (("Eth1/15", "device_id"), "AS-NBR-A.example.tv"),
                (("Eth1/15", "platform"), "C9300-48T"),  # Capabilities tail stripped
                (("Eth1/15", "remote_port"), "Te1/1/1"),
                (("Eth1/16", "platform"), "WS-C3850-48T"),
                (("Eth1/16", "mgmt_ip"), "10.200.200.223"),
            ],
        },
    ],
    "parse_neighbors_lldp": [
        {
            "note": "NX-OS LLDP 'System Name: not advertised' sentinel must not become "
                    "a neighbor name. Real CS01 shape.",
            "input": (
                "Chassis id: AAAA\n"
                "Port id: 11aa.22bb.33cc\n"
                "Local Port id: Eth1/1\n"
                "System Name: not advertised\n"
                "Chassis id: BBBB\n"
                "Port id: Eth2/2\n"
                "Local Port id: Eth1/2\n"
                "System Name: RealNeighbor\n"
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                (("Eth1/2", "device_id"), "RealNeighbor"),
                (("Eth1/1", "device_id"), ""),  # 'not advertised' -> empty, no phantom hub
                (("Eth1/2", "remote_port"), "Eth2/2"),
            ],
        },
    ],
    # ------------------------------------------------------------------ routing / redistribution
    "parse_redistribution": [
        {
            "note": "NX-OS 'redistribute direct' + named OSPF/EIGRP process tags "
                    "(IOS-only regex missed both). NX-OS CLI shapes.",
            "input": (
                "router ospf UNDERLAY\n"
                "  redistribute direct route-map RM-CONN\n"
                "  redistribute bgp 65001 route-map RM-BGP\n"
                "router eigrp CORE\n"
                "  redistribute static route-map RM-STAT\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                ((0, "from_proto"), "connected"),  # NX-OS 'direct' normalized
                ((0, "into_id"), "UNDERLAY"),      # named process tag kept
                ((0, "route_map"), "RM-CONN"),
                ((1, "from_id"), "65001"),
                ((2, "into_id"), "CORE"),
                ((2, "route_map"), "RM-STAT"),
            ],
        },
    ],
    # ------------------------------------------------------------------ environment
    "parse_show_environment_power": [
        {
            "note": "NX-OS space-aligned power budget (no colon). Real CS01 shape.",
            "input": (
                "PS  Model                Input Power       Current   Status\n"
                "1   N55-PAC-1100W-B      AC    1050.00     87.50     ok\n"
                "2   N55-PAC-1100W-B      AC    1050.00     87.50     ok\n"
                "\n"
                "Total Power Capacity                             2100.00 W\n"
                "Total Power Available                            1099.92 W\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [
                (("total_capacity_w",), "2100.00"),
                (("total_remaining_w",), "1099.92"),
                (("total_drawn_w",), "1000.08"),  # capacity - available
                (("num_ps",), 2),
            ],
        },
    ],
    "parse_show_environment": [
        {
            "note": "NX-OS 'show environment' fan table rows (Chassis-N / PS-N). "
                    "Real CS01 shape.",
            "input": (
                "Fan:\n"
                "Fan             Model                Hw         Status\n"
                "Chassis-1       N6K-C6001-FAN-B      --         ok\n"
                "Chassis-2       N6K-C6001-FAN-B      --         ok\n"
                "PS-1            N55-PAC-1100W-B      --         ok\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [(("fan_status",), "OK")],
        },
    ],
    # ------------------------------------------------------------------ L2 tables
    "parse_show_mac_address_table": [
        {
            "note": "NX-OS mac table: '+' vPC peer-link rows ('vPC Peer-Link', two "
                    "tokens) must be skipped, not become a phantom interface.",
            "input": (
                "VLAN     MAC Address      Type      age     Secure NTFY Ports\n"
                "*   64     0000.0c07.ac40   dynamic   0         F      F    Po1\n"
                "*   64     0050.56aa.bb01   dynamic   0         F      F    Eth1/9\n"
                "+   64     001b.54c2.3a40   dynamic   0         F      F    vPC Peer-Link\n"
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                (("Po1", 0), "0000.0c07.ac40"),
                (("Eth1/9", 0), "0050.56aa.bb01"),
            ],
        },
    ],
    # ------------------------------------------------------------------ config hygiene
    "parse_config_hygiene": [
        {
            "note": "NX-OS SNMPv3 group 'access <ACL>' reference form -- the ACL is "
                    "USED, not unused. Real CS01/AAS shapes (group/OID anonymized).",
            "input": (
                "ip access-list SNMPv3_Allowed_Managers\n"
                "  10 permit ip 10.0.0.0/8 any\n"
                "snmp-server group SNMPv3-Group v3 auth access SNMPv3_Allowed_Managers\n"
                "snmp-server group SNMPv3-Group v3 priv notify *tv.FFFF access SNMPv3_Allowed_Managers\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [
                (("summary", "unused"), 0),      # the ACL is referenced, not unused
                (("summary", "structures"), 1),
            ],
        },
    ],
    # ------------------------------------------------------------------ routing table
    "parse_ip_routes": [
        {
            "note": "NX-OS 'show ip route' ubest/mbest blocks with ECMP '*via' lines; the "
                    "source ('ospf-<tag>') is followed by a route-type qualifier ('inter') "
                    "that must NOT be read as the source. Real CS01 shape (process tag "
                    "anonymized).",
            "input": (
                'IP Route Table for VRF "default"\n'
                "'*' denotes best ucast next-hop\n"
                "'**' denotes best mcast next-hop\n"
                "'[x/y]' denotes [preference/metric]\n"
                "'%<string>' in via output denotes VRF <string>\n"
                "\n"
                "0.0.0.0/0, ubest/mbest: 2/0\n"
                "    *via 10.203.254.5, Po11, [110/2], 34w1d, ospf-CORE, inter\n"
                "    *via 10.203.254.9, Po12, [110/2], 34w1d, ospf-CORE, inter\n"
                "10.0.0.60/32, ubest/mbest: 2/0\n"
                "    *via 10.203.254.5, Po11, [110/5], 34w1d, ospf-CORE, inter\n"
                "    *via 10.203.254.9, Po12, [110/5], 34w1d, ospf-CORE, inter\n"
                "10.6.4.0/24, ubest/mbest: 2/0\n"
                "    *via 10.203.254.5, Po11, [110/42], 34w1d, ospf-CORE, inter\n"
                "    *via 10.203.254.9, Po12, [110/42], 34w1d, ospf-CORE, inter\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                (("0.0.0.0/0", "entries", 0, "source"), "ospf"),  # not the 'inter' qualifier
                (("0.0.0.0/0", "entries", 0, "next_hop"), "10.203.254.5"),
                (("0.0.0.0/0", "entries", 1, "out_intf"), "Po12"),  # ECMP sibling kept
                (("10.6.4.0/24", "entries", 0, "out_intf"), "Po11"),
            ],
        },
    ],
    # ------------------------------------------------------------------ routing adjacency
    "parse_bgp_summary": [
        {
            "note": "IOS/NX-OS 'show ip bgp summary' -- the last column is PfxRcd (Established -> a "
                    "number) OR the BGP state word (Idle/Active/...). A down (Idle) peer must NOT read "
                    "as a healthy prefix count, and an IPv6 peer row must survive. Anonymized "
                    "addresses/ASNs.",
            "input": (
                "BGP router identifier 10.0.0.1, local AS number 65001\n"
                "Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
                "10.0.0.2        4 65002    1000    1001       50    0    0 10w2d          120\n"
                "10.0.0.3        4 65003    2000    2002       50    0    0 00:00:15       Idle\n"
                "2001:db8::1     4 65004     500     501       50    0    0 01:02:03         45\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                ((0, "neighbor"), "10.0.0.2"),
                ((0, "as"), "65002"),
                ((0, "state"), "120"),              # Established -> the PfxRcd count
                ((1, "state"), "Idle"),             # down peer NOT silently read as Established
                ((2, "neighbor"), "2001:db8::1"),   # IPv6 peer row kept, not dropped
            ],
        },
    ],
    "parse_ospf_neighbors": [
        {
            "note": "'show ip ospf neighbor' -- on a point-to-point/unnumbered interface the State's "
                    "role is a whitespace-separated dash ('FULL/  -'); the row (incl. a stuck EXSTART) "
                    "must survive and collapse to 'FULL/-', else it reads like a device with no OSPF. "
                    "Anonymized.",
            "input": (
                "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
                "10.0.0.2          1   FULL/DR         00:00:38    10.1.1.2        Vlan10\n"
                "10.0.0.3          0   FULL/  -        00:00:35    10.1.2.3        GigabitEthernet0/1\n"
                "10.0.0.4          1   EXSTART/  -     00:00:31    10.1.3.4        GigabitEthernet0/2\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                ((0, "state"), "FULL/DR"),
                ((1, "state"), "FULL/-"),          # p2p '/  -' role collapsed, row not dropped
                ((1, "interface"), "Gi0/1"),       # normalized ifname
                ((2, "state"), "EXSTART/-"),        # stuck adjacency preserved, not read as absent
            ],
        },
    ],
    "parse_eigrp_neighbors": [
        {
            "note": "'show ip eigrp neighbors' -- H/Address/Interface/Hold/Uptime grid; the token after "
                    "Hold (the Uptime) becomes the 'up <uptime>' state, and the ifname normalizes "
                    "(Vl20 -> Vlan20). Anonymized.",
            "input": (
                "EIGRP-IPv4 Neighbors for AS(100)\n"
                "H   Address                 Interface       Hold Uptime   SRTT   RTO  Q  Seq\n"
                "0   10.1.1.2                Gi0/1             12 01:22:33   10   200  0  5\n"
                "1   10.1.2.3                Vl20              10 1d02h      15   300  0  8\n"
            ),
            "expect_min_entities": 2,
            "spot_facts": [
                ((0, "neighbor"), "10.1.1.2"),
                ((0, "interface"), "Gi0/1"),
                ((0, "state"), "up 01:22:33"),
                ((1, "interface"), "Vlan20"),       # Vl20 -> Vlan20 normalized
            ],
        },
    ],
    # ------------------------------------------------------------------ trunking
    "parse_show_interface_trunk_table": [
        {
            "note": "NX-OS 'show interface trunk' TWO-line header ('Port Native Status "
                    "Port' / 'Vlan ... Channel') -- the channel column marker lives on "
                    "line 2. Real CS01 slice.",
            "input": (
                "\n"
                "--------------------------------------------------------------------------------\n"
                "Port          Native  Status        Port\n"
                "              Vlan                  Channel\n"
                "--------------------------------------------------------------------------------\n"
                "Eth1/12       1       trunking      --\n"
                "Eth1/15       1       trnk-bndl     Po15\n"
                "Eth2/3        1       trnk-bndl     Po1\n"
                "Po1           1       trunking      --\n"
                "Po15          1       trunking      --\n"
            ),
            "expect_min_entities": 5,
            "spot_facts": [
                (("Eth1/12", "native_vlan"), "1"),
                (("Eth1/12", "status"), "trunking"),
                (("Eth1/15", "status"), "trnk-bndl"),
                (("Eth1/15", "port_channel"), "Po15"),
                (("Eth2/3", "port_channel"), "Po1"),
            ],
        },
    ],
    # ------------------------------------------------------------------ FHRP
    "parse_vrrp_summary": [
        {
            "note": "IOS 'show vrrp brief' -- Vl<N> short names, Grp/Pri/Own/Pre columns, "
                    "Group addr is the LAST IP. Real ACS shape (this estate runs VRRP, "
                    "not HSRP: every show hsrp/standby brief capture is header-only).",
            "input": (
                "Interface          Grp Pri Time  Own Pre State   Master addr     Group addr\n"
                "Vl3                3   110 3570       Y  Master  10.202.0.2      10.202.0.1     \n"
                "Vl4                4   90  3648       Y  Backup  10.202.4.3      10.202.4.1     \n"
                "Vl10               10  110 3570       Y  Master  10.202.10.2     10.202.10.1    \n"
                "Vl250              200 90  3648       Y  Backup  10.202.250.3    10.202.250.1   \n"
            ),
            "expect_min_entities": 4,
            "spot_facts": [
                (("Vlan3",), "VRRP grp 3 Master VIP 10.202.0.1"),
                (("Vlan4",), "VRRP grp 4 Backup VIP 10.202.4.1"),
                (("Vlan250",), "VRRP grp 200 Backup VIP 10.202.250.1"),  # ifname != grp
            ],
        },
    ],
    "parse_hsrp_summary": [
        {
            "note": "'show standby brief' tabular HSRP -- 'Vl<N> Grp Pri P State ... Virtual-IP' with "
                    "the VIP as the LAST IP on the row. Feeds the FHRP behavior string that _parse_fhrp "
                    "later re-parses (an Init/down group must survive, not drop to 'no FHRP'). The "
                    "sample-fleet estate runs VRRP, so this pins the HSRP device-output format itself. "
                    "Anonymized addresses.",
            "input": (
                "Interface   Grp  Pri P State   Active          Standby         Virtual IP\n"
                "Vl10        10   110 P Active  local           10.1.10.3       10.1.10.1\n"
                "Vl20        20   90  P Standby 10.1.20.2       local           10.1.20.1\n"
                "Vl30        30   90  P Init    unknown         unknown         10.1.30.1\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                (("Vlan10",), "HSRP grp 10 Active VIP 10.1.10.1"),
                (("Vlan20",), "HSRP grp 20 Standby VIP 10.1.20.1"),
                (("Vlan30",), "HSRP grp 30 Init VIP 10.1.30.1"),  # Init (down) group kept, not dropped
            ],
        },
    ],
    # ------------------------------------------------------------------ vPC
    "parse_vpc": [
        {
            "note": "NX-OS 'show vpc': colon key/value block + peer-link table + vPC "
                    "status table with down*/wrapped-vlan rows. Real CS01 slice.",
            "input": (
                "Legend:\n"
                "                (*) - local vPC is down, forwarding via vPC peer-link\n"
                "\n"
                "vPC domain id                     : 19  \n"
                "Peer status                       : peer adjacency formed ok      \n"
                "vPC keep-alive status             : peer is alive                 \n"
                "Configuration consistency status  : success \n"
                "Per-vlan consistency status       : success                       \n"
                "Type-2 consistency status         : success \n"
                "vPC role                          : primary, operational secondary\n"
                "Number of vPCs configured         : 27  \n"
                "Peer Gateway                      : Enabled\n"
                "Auto-recovery status              : Enabled (timeout = 240 seconds)\n"
                "\n"
                "vPC Peer-link status\n"
                "---------------------------------------------------------------------\n"
                "id   Port   Status Active vlans    \n"
                "--   ----   ------ --------------------------------------------------\n"
                "1    Po1    up     1,12-18,24-28,30-33,64                                    \n"
                "\n"
                "vPC status\n"
                "----------------------------------------------------------------------------\n"
                "id     Port        Status Consistency Reason                     Active vlans\n"
                "------ ----------- ------ ----------- -------------------------- -----------\n"
                "15     Po15        up     success     success                    1,12-18,24- \n"
                "                                                                 28,30-33,64 \n"
                "22     Po22        down*  success     success                    -           \n"
                "31     Po31        up     success     success                    12-14,16-18 \n"
            ),
            "expect_min_entities": 5,
            "spot_facts": [
                (("domain_id",), 19),
                (("peer_status",), "peer adjacency formed ok"),
                (("num_vpcs",), 27),
                (("peer_link", "port"), "Po1"),
                (("vpcs", 1, "port"), "Po22"),
                (("vpcs", 1, "status"), "down*"),
            ],
        },
    ],
    # ------------------------------------------------------------------ port-channels
    "parse_portchannel_protocol_from_summary": [
        {
            "note": "NX-OS 'show port-channel summary' 2-line header; LACP -> Active, "
                    "NONE -> On. Real CS01 slice.",
            "input": (
                "Flags:  D - Down        P - Up in port-channel (members)\n"
                "        I - Individual  H - Hot-standby (LACP only)\n"
                "        s - Suspended   r - Module-removed\n"
                "        S - Switched    R - Routed\n"
                "        U - Up (port-channel)\n"
                "        M - Not in use. Min-links not met\n"
                "--------------------------------------------------------------------------------\n"
                "Group Port-       Type     Protocol  Member Ports\n"
                "      Channel\n"
                "--------------------------------------------------------------------------------\n"
                "1     Po1(SU)     Eth      LACP      Eth2/3(P)    Eth2/4(P)    \n"
                "2     Po2(RU)     Eth      LACP      Eth1/48(P)   \n"
                "39    Po39(SD)    Eth      LACP      Eth1/41(D)   \n"
                "47    Po47(SD)    Eth      NONE      --\n"
            ),
            "expect_min_entities": 4,
            "spot_facts": [
                (("Po1",), "Active"),
                (("Po47",), "On"),  # protocol NONE = static/mode-on bundle
            ],
        },
    ],
    "parse_etherchannel_summary_members": [
        {
            "note": "Same real NX-OS 'show port-channel summary' slice: member -> Po map "
                    "(down members still belong to their bundle).",
            "input": (
                "Flags:  D - Down        P - Up in port-channel (members)\n"
                "        U - Up (port-channel)\n"
                "--------------------------------------------------------------------------------\n"
                "Group Port-       Type     Protocol  Member Ports\n"
                "      Channel\n"
                "--------------------------------------------------------------------------------\n"
                "1     Po1(SU)     Eth      LACP      Eth2/3(P)    Eth2/4(P)    \n"
                "2     Po2(RU)     Eth      LACP      Eth1/48(P)   \n"
                "39    Po39(SD)    Eth      LACP      Eth1/41(D)   \n"
            ),
            "expect_min_entities": 4,
            "spot_facts": [
                (("Eth2/3",), "Po1"),
                (("Eth2/4",), "Po1"),
                (("Eth1/41",), "Po39"),  # down member still mapped
            ],
        },
    ],
    # ------------------------------------------------------------------ control-plane health
    "parse_cpu_utilization": [
        {
            "note": "IOS-XE multicore 'show processes cpu' ('Core 0: CPU utilization "
                    "for five seconds: ...', no /interrupt part). Real ACS shape.",
            "input": (
                "Core 0: CPU utilization for five seconds: 21%; one minute: 19%; five minutes: 18%\n"
                "Core 1: CPU utilization for five seconds: 6%; one minute: 5%; five minutes: 4%\n"
                "PID     Runtime(ms) Invoked   uSecs  5Sec 1Min 5Min TTY   Process\n"
                "1       904         768       1177   0.00 0.00 0.00 0     init               \n"
            ),
            "expect_min_entities": 4,
            "spot_facts": [
                (("five_sec",), 21),
                (("one_min",), 19),
                (("five_min",), 18),
                (("interrupt",), 0),  # no /interrupt part on this platform
            ],
        },
    ],
    "parse_system_resources": [
        {
            "note": "NX-OS 'show system resources' (the NX-OS CPU/memory source of "
                    "truth -- N6K 'show processes cpu' has no utilization header). "
                    "Real CS01 output.",
            "input": (
                "Load average:   1 minute: 0.44   5 minutes: 0.25   15 minutes: 0.19\n"
                "Processes   :   429 total, 2 running\n"
                "CPU states  :   0.6% user,   0.0% kernel,   99.4% idle\n"
                "Memory usage:   8238112K total,   2851208K used,   5386904K free\n"
            ),
            "expect_min_entities": 5,
            "spot_facts": [
                (("cpu_idle",), 99.4),
                (("mem_total_kb",), 8238112),
                (("mem_free_kb",), 5386904),
                (("load_1m",), 0.44),
            ],
        },
    ],
    # ------------------------------------------------------------------ spanning tree
    "parse_spanning_tree_root": [
        {
            "note": "NX-OS RSTP per-VLAN blocks ('This bridge is the root', vPC "
                    "peer-link rows). Real CS01 slice.",
            "input": _STP_REAL_BLOCK,
            "expect_min_entities": 2,
            "spot_facts": [
                (("1", "root_priority"), 32769),
                (("1", "is_root"), True),
                (("12", "bridge_priority"), 12),
                (("12", "root_address"), "0023.04ee.be13"),
            ],
        },
    ],
    "parse_spanning_tree_states": [
        {
            "note": "Same real 'show spanning-tree' slice: interface Role/Sts rows "
                    "with '(vPC peer-link) Network P2p' type suffixes.",
            "input": _STP_REAL_BLOCK,
            "expect_min_entities": 4,
            "spot_facts": [
                (("Po1",), "Forwarding"),
                (("Po31",), "Forwarding"),
            ],
        },
    ],
    # ------------------------------------------------------------------ platform / version
    "parse_show_version": [
        {
            "note": "Real NX-OS N6K 'show version' (serial + device name anonymized): "
                    "chassis PID normalization, kickstart/system version, 'Kernel "
                    "uptime' must not be read as hostname 'Kernel' -- the hostname is "
                    "on 'Device name:'.",
            "input": (
                "Cisco Nexus Operating System (NX-OS) Software\n"
                "TAC support: http://www.cisco.com/tac\n"
                "Copyright (c) 2002-2016, Cisco Systems, Inc. All rights reserved.\n"
                "\n"
                "Software\n"
                "  BIOS:      version 2.2.0\n"
                "  loader:    version N/A\n"
                "  kickstart: version 7.0(8)N1(1)\n"
                "  system:    version 7.0(8)N1(1)\n"
                "  BIOS compile time:       12/05/2015\n"
                "  kickstart image file is: bootflash:///n6000-uk9-kickstart.7.0.8.N1.1.bin\n"
                "  system image file is:    bootflash:///n6000-uk9.7.0.8.N1.1.bin\n"
                "\n"
                "\n"
                "Hardware\n"
                '  cisco Nexus 6001 Chassis ("Nexus 64 Supervisor")\n'
                "  Intel(R) Xeon(R) CPU  @ 2.00 with 8238112 kB of memory.\n"
                "  Processor Board ID FOC12345ABC\n"
                "\n"
                "  Device name: CS01\n"
                "  bootflash:    7827456 kB\n"
                "\n"
                "Kernel uptime is 3552 day(s), 14 hour(s), 45 minute(s), 27 second(s)\n"
                "\n"
                "Last reset at 931349 usecs after  Thu Jun  7 17:31:05 2012\n"
                "\n"
                "  Reason: Reset Requested by CLI command reload\n"
                "  System version: 7.0(8)N1(1)\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [
                (("model",), "N6K-C6001"),  # normalized PID, matches eoldb
                (("sw_version",), "7.0(8)N1(1)"),
                (("serial_number",), "FOC12345ABC"),
                (("uptime",), "3552 day(s), 14 hour(s), 45 minute(s), 27 second(s)"),
                (("hostname_reported",), "CS01"),  # from 'Device name:', never 'Kernel'
            ],
        },
    ],
    # ------------------------------------------------------------------ interface physical
    "parse_interface_phy": [
        {
            "note": "NX-OS 'show interface' -- speed capture must not bleed across "
                    "newlines into the Beacon/flow-control lines. Real CS01 shape.",
            "input": (
                "Ethernet1/9 is up\n"
                "  full-duplex, 10 Gb/s, media type is 10G\n"
                "  Beacon is turned off\n"
                "  Input flow-control is off\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [
                (("Eth1/9", "speed"), "10 Gb/s"),  # no multi-line bleed
                (("Eth1/9", "duplex"), "Full"),
            ],
        },
    ],
    # ------------------------------------------------------------------ operational logs
    "parse_syslog_events": [
        {
            "note": "'show logging' -- IOS ('000123: *Jun ... %LINK-3-UPDOWN: ...') and NX-OS "
                    "('2026 Jun ... host %ETHPORT-5-...: ...') event shapes both parse; the non-event "
                    "header lines ('Syslog logging: enabled ...') are skipped, never errored. "
                    "Anonymized host.",
            "input": (
                "Syslog logging: enabled (0 messages dropped, 0 flushes, 0 overruns)\n"
                "    Console logging: level debugging, 100 messages logged\n"
                "Log Buffer (200000 bytes):\n"
                "000123: *Jun  9 12:00:01.123: %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down\n"
                "000124: *Jun  9 12:00:02.456: %LINEPROTO-5-UPDOWN: Line protocol on Interface Gi0/1, changed state to down\n"
                "2026 Jun  9 12:00:03 CS01 %ETHPORT-5-IF_DOWN_LINK_FAILURE: Interface Ethernet1/1 is down\n"
            ),
            "expect_min_entities": 3,
            "spot_facts": [
                ((0, "facility"), "LINK"),
                ((0, "severity"), 3),         # numeric syslog level, not the mnemonic
                ((0, "mnemonic"), "UPDOWN"),
                ((2, "facility"), "ETHPORT"),  # NX-OS line shape parsed too
                ((2, "severity"), 5),
            ],
        },
    ],
    # ------------------------------------------------------------------ QoS posture
    "parse_qos_config": [
        {
            "note": "QoS slice of a running-config: global 'mls qos', an MQC class-map/policy-map, and "
                    "a per-interface trust + voice-vlan + input service-policy. The per-interface "
                    "attribute keys (trust / voice_vlan / policy_in) are exactly what compute_qos_audit "
                    "counts into n_trust_if / n_voice_if -- renaming one of these output keys is the "
                    "parser<->detector drift this pin catches. Fixed 6-key shape, so the spot_facts (not "
                    "the entity count) carry the guard. Anonymized.",
            "input": (
                "mls qos\n"
                "class-map match-any VOICE\n"
                " match ip dscp ef\n"
                "policy-map MARK\n"
                " class VOICE\n"
                "  set dscp ef\n"
                "interface GigabitEthernet0/1\n"
                " switchport voice vlan 100\n"
                " mls qos trust dscp\n"
                " service-policy input MARK\n"
            ),
            "expect_min_entities": 1,
            "spot_facts": [
                (("mls_qos",), True),
                (("class_maps", 0), "VOICE"),
                (("policy_maps", 0), "MARK"),
                (("interfaces", "Gi0/1", "trust"), "dscp"),       # the acceptance field
                (("interfaces", "Gi0/1", "voice_vlan"), "100"),
                (("interfaces", "Gi0/1", "policy_in"), "MARK"),
            ],
        },
    ],
}
