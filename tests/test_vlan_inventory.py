"""SSOT completeness for the canonical VLAN inventory.

`vlan_inventory` is the single source of truth for every "VLANs in use" count (design doc, CRD,
executive_brief.scale.n_vlans -> explorer + webapp). It must count every VLAN evidenced as IN USE,
including VLANs evidenced only by an active IGMP querier.

Grounding (Cisco / industry, researched 2026-06-18): exactly one IGMP querier exists per active
VLAN / L2 segment, normally the L3 default gateway itself — so a querier observed FIRST-HAND by a
collected switch is direct evidence the VLAN is live and trunk-carried, even when that VLAN's SVI /
gateway sits on a device that was not collected. A VLAN is "in use" when an access OR trunk port
utilises it; omitting querier-only VLANs undercounts migration scope and risks stranded multicast at
cutover. Sources: Cisco IGMP config guide; Cisco IP-multicast troubleshooting; VLAN active-vs-allowed
trunk assessment.
"""
from cisco_toolkit.analyze import vlan_inventory


def test_vlan_inventory_counts_access_svi_and_querier_evidenced_vlans():
    """VLAN 50 has no access port and no collected SVI — only an IGMP querier seen by a collected
    switch proves it is active (its gateway is on an uncollected device). It must be counted."""
    snap = {
        "interfaces": {
            "acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                 "vlan_name": "USERS", "end_host_mac": "aaaa.0000.0001"}},
        },
        "l3_forwarding": [{"switch": "core1", "vlan": "20", "svi_ip": "10.0.20.1"}],
        "service_map": {"multicast": {"igmp_queriers": [
            {"switch": "acc1", "vlan": "50", "querier": "10.0.50.1"},   # querier-only -> must count
            {"switch": "acc1", "vlan": "10", "querier": "10.0.10.1"},   # already an access VLAN -> no double
        ]}},
    }
    vids = {v for v, _ in vlan_inventory(snap)}
    assert vids == {10, 20, 50}, f"querier-only VLAN 50 must be counted; got {sorted(vids)}"
    # names still resolve from the access port where one exists; querier-only VLANs carry no name
    names = dict(vlan_inventory(snap))
    assert names[10] == "USERS" and names[50] == ""


def test_vlan_inventory_back_compatible_without_multicast():
    """No service_map / multicast / querier evidence -> behaves exactly as before (access + L3)."""
    snap = {"interfaces": {"a": {"Gi1": {"vlan": "10"}}},
            "l3_forwarding": [{"vlan": "20"}]}
    assert {v for v, _ in vlan_inventory(snap)} == {10, 20}


def test_vlan_inventory_tolerates_malformed_querier_records():
    """Defensive: missing/blank/non-digit querier VLAN ids are skipped, not crashed on."""
    snap = {"service_map": {"multicast": {"igmp_queriers": [
        {"switch": "a"}, {"vlan": ""}, {"vlan": "n/a"}, {"vlan": "99"}, None]}}}
    assert {v for v, _ in vlan_inventory(snap)} == {99}
