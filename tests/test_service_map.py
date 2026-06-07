"""NEW-V3.23.101: the L4 service map -- ACL port references + multicast activity resolved to named
services via the offline port registry. ACL refs are design intent (Inferred), not active traffic."""
from cisco_toolkit.analyze import compute_service_map
from cisco_toolkit.model import InterfaceData


def _acl(action="permit", proto="udp", dport=None, sport=None, src=None, dst=None):
    return {"action": action, "proto": proto, "sport": sport, "dport": dport,
            "src": src or {"ip": "0.0.0.0", "wild": "255.255.255.255"},
            "dst": dst or {"ip": "0.0.0.0", "wild": "255.255.255.255"}, "raw": ""}


def test_service_map_resolves_acl_ports():
    acls = {
        "sw1": {"RELAY": [_acl(dport={"op": "eq", "val": 67}),
                          _acl(dport={"op": "eq", "val": 68})]},
        "sw2": {"BFD": [_acl(dport={"op": "eq", "val": 3784})],
                "MGMT": [_acl(proto="ip")]},          # ip rule, no L4 port -> ignored
    }
    sm = compute_service_map(acls, {})
    by = {(s["port"], s["proto"]): s for s in sm["services"]}
    assert by[(67, "udp")]["service"] == "DHCP-server" and by[(67, "udp")]["category"] == "Infra"
    assert by[(3784, "udp")]["service"] == "BFD-control" and by[(3784, "udp")]["host_count"] == 1
    assert "Inferred" in by[(67, "udp")]["evidence_class"]
    assert sm["acl_rule_count"] == 4
    # categories aggregate refs
    cats = {c["category"]: c["refs"] for c in sm["categories"]}
    assert cats["Infra"] == 2 and cats["Routing"] == 1


def test_service_map_multicast_activity_and_classification():
    # PIM/mroute presence on interfaces = Confirmed multicast forwarding
    ai = {
        "sw1": {"Vlan10": InterfaceData(port="Vlan10", multicast_info="PIM Sparse / Mroute OIL"),
                "Gi1/0/1": InterfaceData(port="Gi1/0/1")},
        "sw2": {"Vlan20": InterfaceData(port="Vlan20", multicast_info="PIM enabled")},
    }
    # a multicast group referenced in an ACL gets classified
    acls = {"sw1": {"MC": [_acl(dst={"ip": "224.0.1.129", "wild": "0.0.0.0"})]}}
    sm = compute_service_map(acls, ai)
    mc = sm["multicast"]
    assert mc["active_interfaces"] == 2 and mc["active_switch_count"] == 2
    assert mc["group_level_collected"] is False          # richer collection not present
    groups = {g["group"]: g for g in mc["classified_groups"]}
    assert groups["224.0.1.129"]["name"] == "PTP-primary" and groups["224.0.1.129"]["broadcast"] is True


def test_service_map_empty_inputs():
    sm = compute_service_map({}, {})
    assert sm["services"] == [] and sm["acl_rule_count"] == 0
    assert sm["multicast"]["active_interfaces"] == 0


def test_service_map_tolerates_malformed_rules():
    # a stray non-dict rule entry must be skipped, not crash (defensive, V3.23.105)
    acls = {"sw1": {"A": ["junk", {"proto": "udp", "sport": None, "dport": {"op": "eq", "val": 67},
                                   "src": None, "dst": None}]}}
    sm = compute_service_map(acls, {})
    assert {(s["port"], s["service"]) for s in sm["services"]} == {(67, "DHCP-server")}
    assert sm["acl_rule_count"] == 1   # only the well-formed rule counted
