"""NEW-V3.23.102: tolerant parsers + builders for the new multicast / PTP / ACL-hit collection.
They are inert (return []/{}) until the new commands are collected, then light up the broadcast-fabric
intelligence (multicast group census, PTP grandmaster lock, active-traffic evidence)."""
from cisco_toolkit import build
from cisco_toolkit.parse import (
    parse_acl_hitcounts,
    parse_igmp_groups,
    parse_igmp_snooping_querier,
    parse_ptp_clock,
)


def test_parse_igmp_groups():
    out = """IGMP Connected Group Membership
Group Address    Interface   Uptime    Expires   Last Reporter
239.255.255.250  Vlan10      1d00h     00:02:30  10.0.10.5
224.0.1.129      Vlan20      2w1d      00:02:45  10.0.20.3
239.1.2.3        Vlan20      00:10:00  00:02:10  10.0.20.9
"""
    g = parse_igmp_groups(out)
    assert g == ["224.0.1.129", "239.1.2.3", "239.255.255.250"]   # sorted, unicast reporters excluded
    assert parse_igmp_groups("") == []
    assert parse_igmp_groups("no multicast groups") == []


def test_parse_igmp_snooping_querier_table_and_detail():
    table = """Vlan      IP Address     IGMP Version   Port
10        10.0.10.1      v2             Switch
20        10.0.20.1      v3             Gi1/0/1
"""
    q = parse_igmp_snooping_querier(table)
    assert {"vlan": "10", "querier": "10.0.10.1"} in q and len(q) == 2
    detail = """Vlan 30:  IGMP snooping querier status
  Admin state         : Enabled
  IP address          : 10.0.30.1
"""
    assert parse_igmp_snooping_querier(detail) == [{"vlan": "30", "querier": "10.0.30.1"}]
    assert parse_igmp_snooping_querier("") == []


def test_parse_ptp_clock_operational_boundary_clock():
    out = """PTP CLOCK INFO
PTP Device Type: Boundary clock
PTP Device Profile: Default Profile
Clock Identity: 0x00A0B1.FFFE.000001
Clock Domain: 0
Number of PTP ports: 4
Grandmaster Clock Identity: 0x00A0B1.FFFE.123456
Offset From Master(ns): 42
Mean Path Delay(ns): 310
"""
    p = parse_ptp_clock(out)
    assert p["device_type"] == "Boundary clock" and p["domain"] == "0" and p["num_ports"] == 4
    assert p["clock_identity"].endswith("000001") and p["grandmaster"].endswith("123456")
    assert p["offset_ns"] == 42 and p["mean_path_delay_ns"] == 310
    assert p["locked"] is True and p["operational"] is True
    # a large offset => not locked
    assert parse_ptp_clock("PTP Device Type: Boundary clock\nNumber of PTP ports: 2\n"
                           "Offset From Master(ns): 50000")["locked"] is False


def test_parse_ptp_clock_dormant_real_format():
    # the real AJ-fleet output: PTP available but NOT an active boundary clock (Unknown / 0 ports / no parent)
    out = """ PTP CLOCK INFO
  PTP Device Type: Unknown
  PTP Device Profile: Default Profile
  Clock Identity: 0x5C:E1:76:FF:FE:79:1B:80
  Clock Domain: 0
  Network Transport Protocol: 802.3
  Number of PTP ports: 0
 The clock has no parent clock information."""
    p = parse_ptp_clock(out)
    assert p["device_type"] == "Unknown" and p["num_ports"] == 0
    assert p["clock_identity"].endswith("1B:80") and p["grandmaster"] == ""
    assert p["operational"] is False                 # the key finding: configured but dormant
    assert parse_ptp_clock("") == {} and parse_ptp_clock("nothing here") == {}


def test_parse_ptp_clock_operational_robust_to_missing_port_count():
    # V3.23.111: a known boundary clock whose output omits 'Number of PTP ports' must NOT be
    # false-flagged dormant (num_ports unparsed = unknown, not zero).
    p = parse_ptp_clock("PTP CLOCK INFO\nPTP Device Type: Boundary clock\nClock Domain: 0")
    assert p["num_ports"] is None and p["operational"] is True
    # sync evidence alone (a measured offset) also counts as operational even if device type is blank
    p2 = parse_ptp_clock("PTP info\nOffset From Master(ns): 12")
    assert p2["operational"] is True
    # an explicit 0-port known clock is still dormant
    p3 = parse_ptp_clock("PTP Device Type: Boundary clock\nNumber of PTP ports: 0")
    assert p3["operational"] is False


def test_parse_acl_hitcounts():
    out = """Extended IP access list RELAY
    10 permit udp any any eq 67 (1234 matches)
    20 permit udp any any eq 68
Standard IP access list 99
    10 permit 10.0.0.0 0.0.0.255 (10 matches)
"""
    aces = parse_acl_hitcounts(out)
    relay = [a for a in aces if a["acl"] == "RELAY"][0]
    assert relay["proto"] == "udp" and relay["port"] == 67 and relay["matches"] == 1234
    assert all(a["matches"] for a in aces)           # only ACEs with hit counts captured
    assert parse_acl_hitcounts("") == []


def test_builders_inert_when_uncollected():
    # no files -> every new builder fail-soft to empty
    assert build.build_igmp_groups({}) == []
    assert build.build_igmp_queriers({}) == []
    assert build.build_ptp({}) == {}
    assert build.build_acl_hits({}) == {}


def test_build_acl_hits_aggregates_by_port(tmp_path):
    f = tmp_path / "acl.txt"
    f.write_text("Extended IP access list A\n  10 permit udp any any eq 67 (5 matches)\n"
                 "Extended IP access list B\n  10 permit udp any any eq 67 (3 matches)\n", encoding="utf-8")
    hits = build.build_acl_hits({"show ip access-lists": str(f)})
    assert hits == {"67:udp": 8}
