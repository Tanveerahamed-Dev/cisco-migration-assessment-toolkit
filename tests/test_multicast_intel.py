"""NEW-V3.23.115: media-fabric / multicast intelligence — MAC-address aliasing (RFC 4541), IGMP querier
coverage, and the PTP timing tree over service_map.multicast. Pure read; these tests pin the L2-MAC math,
the 32:1 aliasing detection, the querier-gap detection, the PTP tree, and empty tolerance."""
from cisco_toolkit.analyze import compute_multicast_intelligence, _mcast_mac
from cisco_toolkit.model import InterfaceData


def test_mcast_mac_low23_bits_and_aliasing():
    assert _mcast_mac("224.1.1.1") == "01:00:5e:01:01:01"
    # 32:1 aliasing: groups differing only ABOVE the low 23 bits share one MAC
    assert _mcast_mac("239.1.1.1") == _mcast_mac("225.1.1.1") == "01:00:5e:01:01:01"
    # the top bit of octet-2 is masked (23-bit boundary): 224.129.1.1 aliases 224.1.1.1
    assert _mcast_mac("224.129.1.1") == "01:00:5e:01:01:01"
    # non-multicast / junk -> ""
    assert _mcast_mac("10.0.0.1") == "" and _mcast_mac("") == "" and _mcast_mac("nope") == ""


def _sm(groups=None, queriers=None, ptp=None):
    return {"multicast": {"classified_groups": groups or [], "igmp_queriers": queriers or [],
                          "ptp": ptp or {}, "active_switch_count": 0, "active_interfaces": 0}}


def test_groups_enriched_with_mac_and_on_air():
    groups = [{"group": "239.10.10.1", "name": "AV-cam1", "category": "Broadcast-AV", "broadcast": True,
               "source": "IGMP/mroute"},
              {"group": "224.0.1.1", "name": "NTP", "category": "Management", "broadcast": False,
               "source": "IGMP/mroute"}]
    out = compute_multicast_intelligence(_sm(groups), {})
    g = {x["group"]: x for x in out["groups"]}
    assert g["239.10.10.1"]["mac"] == "01:00:5e:0a:0a:01" and g["239.10.10.1"]["on_air"] is True
    assert g["224.0.1.1"]["on_air"] is False
    assert out["summary"]["n_groups"] == 2 and out["summary"]["n_av_groups"] == 1


def test_mac_alias_clash_detected_and_high_when_av():
    groups = [{"group": "224.1.1.1", "name": "g1", "category": "Broadcast-AV", "broadcast": True},
              {"group": "239.1.1.1", "name": "g2", "category": "Multicast", "broadcast": False}]
    out = compute_multicast_intelligence(_sm(groups), {})
    assert len(out["mac_aliases"]) == 1
    a = out["mac_aliases"][0]
    assert a["mac"] == "01:00:5e:01:01:01" and a["groups"] == ["224.1.1.1", "239.1.1.1"] and a["has_av"] is True
    r = next(r for r in out["risks"] if r["kind"] == "mac-alias")
    assert r["severity"] == "High" and "RFC 4541" in r["standard"]


def test_no_alias_when_groups_have_distinct_macs():
    out = compute_multicast_intelligence(_sm([{"group": "239.1.1.1"}, {"group": "239.1.1.2"}]), {})
    assert out["mac_aliases"] == [] and not any(r["kind"] == "mac-alias" for r in out["risks"])


def test_querier_gap_detection():
    # SVI Vlan20 carries multicast but only Vlan10 has a querier -> Vlan20 is a coverage gap
    ai = {"sw1": {"Vlan10": InterfaceData(port="Vlan10", multicast_info="PIM"),
                  "Vlan20": InterfaceData(port="Vlan20", multicast_info="PIM Sparse")}}
    out = compute_multicast_intelligence(_sm(queriers=[{"switch": "sw1", "vlan": "10", "querier": "10.0.10.1"}]), ai)
    assert out["querier"]["gap_vlans"] == ["20"]
    r = next(r for r in out["risks"] if r["kind"] == "querier-gap")
    assert r["severity"] == "High" and "20" in r["detail"]


def test_ptp_tree_and_dormant_risk():
    out = compute_multicast_intelligence(_sm(ptp={"sw1": {"operational": False}, "sw2": {"operational": False}}), {})
    assert out["ptp"]["n_clocks"] == 2 and out["ptp"]["n_dormant"] == 2 and out["ptp"]["n_operational"] == 0
    assert any(r["kind"] == "ptp-dormant" for r in out["risks"])
    out2 = compute_multicast_intelligence(_sm(ptp={"sw1": {"operational": True}}), {})
    assert not any(r["kind"] == "ptp-dormant" for r in out2["risks"])


def test_empty_inputs_are_well_formed():
    out = compute_multicast_intelligence(None, None)
    assert out["groups"] == [] and out["mac_aliases"] == [] and out["risks"] == []
    assert out["summary"]["n_groups"] == 0
    assert compute_multicast_intelligence({}, {})["querier"]["gap_vlans"] == []
