"""NEW-V3.23.99: the offline port / protocol / multicast knowledge base (twin of the OUI registry).
Port<->service resolution and IPv4 multicast-group classification are facts; lookups are fully offline."""
from cisco_toolkit import portdb


def test_service_for_port_curated_overlay():
    # routing / control-plane
    assert portdb.service_for_port(179, "tcp")["service"] == "BGP"
    assert portdb.service_for_port(179, "tcp")["category"] == "Routing"
    assert portdb.service_for_port(3784, "udp")["service"] == "BFD-control"
    # broadcast / pro-AV are flagged
    ptp = portdb.service_for_port(319, "udp")
    assert ptp["category"] == "Broadcast-AV" and ptp["broadcast"] is True
    assert portdb.service_for_port(4440, "udp")["service"] == "Dante-audio"
    assert portdb.is_broadcast_av_port(5004, "udp") is True
    # storage / OT
    assert portdb.service_for_port(3260, "tcp")["category"] == "Storage"
    assert portdb.service_for_port(502, "tcp")["category"] == "OT-ICS"
    # the only L4 ports this fleet's ACLs reference resolve to friendly names
    assert portdb.service_for_port(67, "udp")["service"] == "DHCP-server"
    assert portdb.service_for_port(68, "udp")["service"] == "DHCP-client"


def test_service_for_port_iana_long_tail_and_unknown():
    # an IANA-only well-known port (not in the curated overlay) still resolves
    assert portdb.service_for_port(25, "tcp") is not None     # smtp
    # unknown / junk -> None
    assert portdb.service_for_port(65000, "tcp") is None
    assert portdb.service_for_port("not-a-port", "tcp") is None
    assert portdb.service_for_port(None) is None


def test_classify_multicast_longest_prefix():
    # specific reserved address wins over its enclosing block
    assert portdb.classify_multicast("224.0.0.5")["group"] == "OSPF-AllSPF"
    assert portdb.classify_multicast("224.0.1.129")["group"] == "PTP-primary"
    assert portdb.classify_multicast("224.0.1.129")["broadcast"] is True
    # Dante / admin-scoped ranges
    assert portdb.classify_multicast("239.254.1.2")["group"] == "Dante"
    assert portdb.classify_multicast("239.10.20.30")["group"] == "admin-scoped"
    # not multicast / junk
    assert portdb.classify_multicast("10.0.0.1") is None
    assert portdb.classify_multicast("garbage") is None


def test_registry_resilient_to_missing_file(monkeypatch):
    monkeypatch.setattr(portdb, "_DATA", "/nonexistent/port_registry.tsv.gz")
    portdb._registry.cache_clear()
    try:
        assert portdb.service_for_port(179, "tcp") is None
        assert portdb.classify_multicast("224.0.0.5") is None
    finally:
        portdb._registry.cache_clear()   # restore for other tests
