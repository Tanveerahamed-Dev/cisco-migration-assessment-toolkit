"""NEW-V3.23.97: subnet & routing reachability intelligence + the BGP-RIB parser."""
from cisco_toolkit.parse import parse_bgp_table
from cisco_toolkit.analyze import compute_subnet_intelligence, _svi_network
from cisco_toolkit.model import InterfaceData


def test_parse_bgp_table():
    out = """
BGP table version is 5, local router ID is 10.0.0.1
Status codes: s suppressed, d damped, h history, * valid, > best, i - internal
   Network          Next Hop            Metric LocPrf Weight Path
*> 10.10.0.0/24     10.1.1.1                 0             0 65001 i
*  10.10.1.0/24     10.1.1.2                               0 65001 ?
*> 192.168.5.0/24   0.0.0.0                  0         32768 i
"""
    assert set(parse_bgp_table(out)) == {"10.10.0.0/24", "10.10.1.0/24", "192.168.5.0/24"}
    assert parse_bgp_table("") == [] and parse_bgp_table("no bgp configured") == []


def test_svi_network_handles_cidr_and_mask():
    assert _svi_network("10.0.10.1/24") == "10.0.10.0/24"
    assert _svi_network("10.0.10.1 255.255.255.0") == "10.0.10.0/24"
    assert _svi_network("") == "" and _svi_network("garbage") == ""


def test_compute_subnet_intelligence():
    def svi(p, ip):
        d = InterfaceData(port=p); d.svi_ip = ip; return d
    def acc(p, vlan):
        return InterfaceData(port=p, switchport_mode="Access", vlan=vlan)
    ai = {
        "core": {"Vlan10": svi("Vlan10", "10.0.10.1/24"), "Vlan20": svi("Vlan20", "10.0.20.1/24")},
        "acc1": {"Gi1/0/1": acc("Gi1/0/1", "10")},   # L2 access switch; endpoints live in VLAN 10
    }
    routes_full = {"core": {
        "10.0.10.0/24": {"entries": [{"source": "connected", "next_hop": ""}]},
        "10.0.99.0/24": {"entries": [{"source": "ospf", "next_hop": "10.0.0.2"}]},
        "0.0.0.0/0": {"entries": [{"source": "static", "next_hop": "10.0.0.1"}]},
    }}
    mg = [{"group": "G1", "switches": ["core", "acc1"]}]
    si = compute_subnet_intelligence(ai, routes_full, mg, {"core": ["172.16.0.0/16"]})
    pd = {r["host"]: r for r in si["per_device"]}
    # core: terminates both SVI subnets; reaches the ospf prefix; default next-hop; one BGP prefix
    assert {"10.0.10.0/24", "10.0.20.0/24"} <= set(pd["core"]["destination_subnets"])
    assert pd["core"]["is_l3"] and pd["core"]["reachable_count"] == 1
    assert pd["core"]["default_next_hop"] == "10.0.0.1" and pd["core"]["bgp_received_count"] == 1
    # acc1: L2 — its VLAN-10 endpoints reach 10.0.10.0/24 transitively via gateway 'core'
    assert pd["acc1"]["is_l3"] is False
    assert any(s["subnet"] == "10.0.10.0/24" and s["gateway"] == "core"
               for s in pd["acc1"]["served_subnets"])
    # move-group source<->destination: local = terminated+served; remote = reachable-not-local
    g = si["move_groups"][0]
    assert "10.0.10.0/24" in g["local_subnets"] and g["remote_count"] >= 1
    assert si["bgp_received_collected"] is True
