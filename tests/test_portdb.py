"""NEW-V3.23.99: the offline port / protocol / multicast knowledge base (twin of the OUI registry).
Port<->service resolution and IPv4 multicast-group classification are facts; lookups are fully offline."""
from cisco_toolkit import portdb


def test_service_for_port_curated_overlay():
    # IANA owns the assignment; the repository overlay is separately labelled.
    bgp = portdb.service_for_port(179, "tcp")
    assert bgp["service"] == "bgp"
    assert bgp["overlay_service"] == "BGP"
    assert bgp["category"] == "Routing"
    assert bgp["assignment_authoritative"] is True
    assert bgp["semantics_authoritative"] is False
    assert portdb.service_for_port(3784, "udp")["service"] == "bfd-control"
    # Curated broadcast / pro-AV semantics remain useful but non-authoritative.
    ptp = portdb.service_for_port(319, "udp")
    assert ptp["category"] == "Broadcast-AV" and ptp["broadcast"] is True
    dante = portdb.service_for_port(4440, "udp")
    assert dante["service"] == "Dante-audio"
    assert dante["assignment_authoritative"] is False
    assert portdb.is_broadcast_av_port(5004, "udp") is True
    # storage / OT
    assert portdb.service_for_port(3260, "tcp")["category"] == "Storage"
    assert portdb.service_for_port(502, "tcp")["category"] == "OT-ICS"
    # Friendly overlay labels do not replace official BOOTP assignments.
    assert portdb.service_for_port(67, "udp")["service"] == "bootps"
    assert portdb.service_for_port(67, "udp")["overlay_service"] == "DHCP-server"
    assert portdb.service_for_port(68, "udp")["service"] == "bootpc"
    assert portdb.service_for_port(68, "udp")["overlay_service"] == "DHCP-client"


def test_iana_aliases_and_overlay_collisions_are_preserved_without_overwrite():
    http = portdb.service_for_port(80, "tcp")
    assert http["service"] == "http"
    assert http["aliases"] == ["www", "www-http"]
    assert http["alias_records"] == [
        {"service": "www", "description": "World Wide Web HTTP"},
        {"service": "www-http", "description": "World Wide Web HTTP"},
    ]

    collision = portdb.service_for_port(4444, "udp")
    assert collision["service"] == "krb524"
    assert collision["aliases"] == ["nv-video"]
    assert collision["overlay_service"] == "Dante-audio"
    assert collision["overlay_status"] == "conflict-suppressed"
    assert collision["category"] == ""
    assert collision["broadcast"] is False
    assert collision["source_authoritative"] is True
    assert portdb.service_for_port(4455, "udp")["service"] == "prchat-user"
    assert portdb.service_for_port(8800, "udp")["service"] == "sunwebadmin"


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
    assert portdb.classify_multicast("224.0.1.129")[
        "source_authoritative"
    ] is False
    # No generic SSM, admin-scoped, or undocumented Dante claim is retained.
    assert portdb.classify_multicast("232.1.2.3") is None
    assert portdb.classify_multicast("239.254.1.2") is None
    assert portdb.classify_multicast("239.10.20.30") is None
    # not multicast / junk
    assert portdb.classify_multicast("10.0.0.1") is None
    assert portdb.classify_multicast("garbage") is None


def test_lookups_tolerate_non_string_args():
    # the KB is a reusable utility -- a non-string proto / group must degrade gracefully, never crash
    assert portdb.service_for_port(443, 123) is not None        # odd proto coerced -> tcp/udp probe finds HTTPS
    assert portdb.service_for_port(65000, 123) is None
    assert portdb.classify_multicast(123) is None
    assert portdb.classify_multicast(1.5) is None
    assert portdb.classify_multicast(("a",)) is None
    assert portdb.is_broadcast_av_port(319, "udp") is True      # correct proto -> PTP/AV resolves
    assert isinstance(portdb.is_broadcast_av_port(319, 123), bool)   # odd proto tolerated, never raises


def test_registry_resilient_to_missing_file(monkeypatch):
    monkeypatch.setattr(portdb, "_DATA", "/nonexistent/port_registry.tsv.gz")
    portdb._registry.cache_clear()
    try:
        assert portdb.service_for_port(179, "tcp") is None
        assert portdb.classify_multicast("224.0.0.5") is None
    finally:
        portdb._registry.cache_clear()   # restore for other tests
