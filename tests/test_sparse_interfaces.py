"""Plan-A #14 Phase-2: sparse-encode the on-disk snapshot's `interfaces` subtree.

Every InterfaceData field defaults to '', so dropping '' values on write is lossless as long as
InterfaceData.from_sparse restores them on read. These pin that round-trip (dense -> sparse ->
dense is the identity on asdict), that the encoder is confined to `interfaces` (devices untouched),
and that it does not mutate the in-memory snapshot (shallow-copy for disk only)."""
import dataclasses

from cisco_toolkit.html import sparsify_interfaces
from cisco_toolkit.model import InterfaceData


def test_sparsify_drops_only_empty_fields_and_leaves_devices_alone():
    dense = dataclasses.asdict(InterfaceData(
        port="Gi1/0/1", status="connected", switchport_mode="Access",
        vlan="10", end_host_mac="aa:bb:cc:dd:ee:ff"))
    snap = {"interfaces": {"sw1": {"Gi1/0/1": dense}},
            "devices": {"sw1": {"hostname": "sw1", "active_ports": 0}}}
    out = sparsify_interfaces(snap)
    sp = out["interfaces"]["sw1"]["Gi1/0/1"]
    assert set(sp) == {"port", "status", "switchport_mode", "vlan", "end_host_mac"}   # only non-empties kept
    assert "poe_status" not in sp and "acl_in" not in sp                              # '' fields dropped
    assert out["devices"] == snap["devices"]                                          # devices subtree untouched
    assert snap["interfaces"]["sw1"]["Gi1/0/1"] == dense                              # original snap NOT mutated


def test_from_sparse_restores_the_dense_record():
    for x in (InterfaceData(port="Te1/1/1", speed="10G", trunk_allowed_vlans="1-100"),
              InterfaceData(),                                                          # all-default record
              InterfaceData(port="Gi0/0", description="uplink", acl_in="MGMT", mtu="9000"),
              InterfaceData(port="Vl10", svi_ip="10.0.10.1", dhcp_helpers="10.0.0.5,10.0.0.6")):
        dense = dataclasses.asdict(x)
        sparse = sparsify_interfaces({"interfaces": {"h": {"p": dense}}})["interfaces"]["h"]["p"]
        assert dataclasses.asdict(InterfaceData.from_sparse(sparse)) == dense          # round-trip identity


def test_from_sparse_drops_unknown_keys_and_tolerates_none():
    # a legacy/foreign key must not crash the dataclass constructor
    obj = InterfaceData.from_sparse({"port": "Gi1/0/1", "vlan": "10", "legacy_removed_field": "x"})
    assert obj.port == "Gi1/0/1" and obj.vlan == "10"
    assert InterfaceData.from_sparse(None) == InterfaceData()                          # None -> all-default


def test_sparsify_no_op_when_interfaces_absent_or_malformed():
    assert sparsify_interfaces({"devices": {}}) == {"devices": {}}                     # no interfaces key
    assert sparsify_interfaces({"interfaces": "oops"}) == {"interfaces": "oops"}       # non-dict -> passthrough
