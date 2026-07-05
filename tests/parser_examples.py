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
                "username admin password 5 $1$/xzLOXP8$cb6hjzRZiOUAmAkP91S930  role network-admin\n"
                "username swadmin password 5 $1$.2qNwXmh$KYWx8jlR.OCGELDIxtNLi0  role vdc-operator\n"
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
}
