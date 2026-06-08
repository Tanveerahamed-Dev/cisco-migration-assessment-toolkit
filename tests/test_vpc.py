"""NEW-V3.23.125: parse_vpc — vPC / MLAG status from NX-OS 'show vpc'. Confirms MLAG peer pairs
(vs the topology-inferred guess) for the flow simulator. Parser is defensive / fail-soft."""
from cisco_toolkit.parse import parse_vpc

_VPC = """\
Legend:
                (*) - local vPC is down, forwarding via vPC peer-link

vPC domain id                     : 10
Peer status                       : peer adjacency formed ok
vPC keep-alive status             : peer is alive
Configuration consistency status  : success
Per-vlan consistency status       : success
Type-2 consistency status         : success
vPC role                          : primary
Number of vPCs configured         : 2
Peer Gateway                      : Disabled
Graceful Consistency Check        : Enabled

vPC Peer-link status
---------------------------------------------------------------------
id    Port   Status Active vlans
--    ----   ------ --------------------------------------------------
1     Po1    up     1,10,20,30,99

vPC status
----------------------------------------------------------------------------
id     Port        Status Consistency Reason                Active vlans
--     ----        ------ ----------- ------                ---------------
20     Po20        up     success     success               10,20
30     Po30        up     success     success               30
"""


def test_parse_vpc_fields():
    v = parse_vpc(_VPC)
    assert v["domain_id"] == 10
    assert v["role"] == "primary"
    assert v["peer_status"] == "peer adjacency formed ok"
    assert v["keepalive_status"] == "peer is alive"
    assert v["consistency"] == "success"
    assert v["num_vpcs"] == 2
    assert v["peer_link"]["port"] == "Po1" and v["peer_link"]["status"] == "up"
    assert v["peer_link"]["vlans"] == "1,10,20,30,99"


def test_parse_vpc_member_table():
    v = parse_vpc(_VPC)
    assert [x["id"] for x in v["vpcs"]] == ["20", "30"]
    assert v["vpcs"][0]["port"] == "Po20"
    assert v["vpcs"][0]["status"] == "up"
    assert v["vpcs"][0]["consistency"] == "success"
    assert v["vpcs"][0]["vlans"] == "10,20"


def test_parse_vpc_not_configured_is_empty():
    # a device that runs no vPC, an IOS box, or an errored/absent command -> {} (fail-soft)
    assert parse_vpc("vPC is not configured") == {}
    assert parse_vpc("vPC feature is not enabled") == {}
    assert parse_vpc("") == {}
    assert parse_vpc("% Invalid command at '^' marker.") == {}
