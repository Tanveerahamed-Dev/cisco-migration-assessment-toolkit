"""NEW-V3.23.95: endpoint identity & vendor intelligence -- the offline OUI lookup and the
evidence-disciplined classifier (vendor is a fact; class is Inferred with a confidence label)."""
from cisco_toolkit import ouidb
from cisco_toolkit.analyze import _classify_endpoint, compute_endpoint_identity
from cisco_toolkit.model import InterfaceData


def test_ouidb_resolves_known_ouis_offline():
    # well-known, stable IEEE allocations present in the shipped registry
    assert "cisco" in ouidb.vendor_for_mac("00:00:0c:11:22:33").lower()
    assert "vmware" in ouidb.vendor_for_mac("00:50:56:aa:bb:cc").lower()
    # locally-administered (bit 0x02) -> no registered vendor
    assert ouidb.vendor_for_mac("02:00:00:00:00:01") == ""
    assert ouidb.is_locally_administered("52:54:00:12:34:56") is True   # QEMU/KVM
    assert ouidb.is_locally_administered("00:50:56:aa:bb:cc") is False
    # junk / too short
    assert ouidb.vendor_for_mac("") == "" and ouidb.vendor_for_mac("zz") == ""


def test_classifier_picks_highest_confidence_signal():
    # description (rank 2) beats an ambiguous vendor (rank 1)
    cls, conf, ev = _classify_endpoint("Dell Inc.", "**STD3 Camera PTZ**", "", "", False)
    assert cls == "Camera" and conf == "Inferred-high" and "description" in ev
    # CDP platform VMware -> VM/Hypervisor
    cls, conf, ev = _classify_endpoint("Intel Corporate", "", "VMware ESX", "", False)
    assert cls == "VM / Hypervisor" and conf == "Inferred-high"
    # unambiguous vendor only (UPS)
    cls, conf, ev = _classify_endpoint("APC by Schneider Electric", "", "", "", False)
    assert cls == "UPS/PDU" and conf == "Inferred-high" and "vendor" in ev
    # device-reported endpoint_type
    cls, conf, ev = _classify_endpoint("", "", "", "Storage", False)
    assert cls == "Storage" and conf == "Inferred-high"
    # nothing but a locally-administered MAC -> weak virtual signal
    cls, conf, ev = _classify_endpoint("", "", "", "", True)
    assert cls == "VM / Hypervisor" and conf == "Inferred-medium"
    # truly nothing -> honest Unknown (no confidence theater)
    cls, conf, ev = _classify_endpoint("", "", "", "", False)
    assert cls == "Unknown" and conf == "Unknown"


def test_compute_endpoint_identity_smoke():
    def ep(port, vlan, mac, **kw):
        d = InterfaceData(port=port, switchport_mode="Access", vlan=vlan, end_host_mac=mac)
        for k, v in kw.items():
            setattr(d, k, v)
        return d
    ai = {
        "sw1": {
            "Gi1/0/1": ep("Gi1/0/1", "10", "00:50:56:aa:00:01"),                       # VMware -> VM
            "Gi1/0/2": ep("Gi1/0/2", "20", "aa:bb:cc:dd:ee:01", description="ISILON storage"),  # desc -> Storage
            "Te1/1": InterfaceData(port="Te1/1", switchport_mode="Trunk", end_host_mac="00:00:0c:00:00:01"),  # trunk excluded
        },
    }
    recs = compute_endpoint_identity(ai)
    assert len(recs) == 2                                    # the trunk port is not an endpoint
    by_port = {r["port"]: r for r in recs}
    assert by_port["Gi1/0/1"]["endpoint_class"] == "VM / Hypervisor"
    assert "vmware" in by_port["Gi1/0/1"]["vendor"].lower()
    assert by_port["Gi1/0/2"]["endpoint_class"] == "Storage"
    # every record carries vendor (fact) + class + confidence + evidence
    assert all({"vendor", "endpoint_class", "confidence", "evidence"} <= set(r) for r in recs)


def test_endpoint_dependencies_clusters_dualhomed_validation():
    """NEW-V3.23.96: clusters (cohesive units), dual-homed detection, and the per-switch service
    checklist — over the identity model, honouring move-group context."""
    from cisco_toolkit.analyze import compute_endpoint_dependencies
    ident = [
        {"host": "sw1", "port": "Gi1/0/1", "vlan": "10", "ip": "", "mac": "aa:00:00:00:00:01",
         "vendor": "Dell Inc.", "endpoint_class": "Server"},
        {"host": "sw2", "port": "Gi1/0/1", "vlan": "10", "ip": "", "mac": "aa:00:00:00:00:02",
         "vendor": "Dell Inc.", "endpoint_class": "Server"},
        {"host": "sw3", "port": "Gi1/0/1", "vlan": "10", "ip": "", "mac": "aa:00:00:00:00:03",
         "vendor": "Dell Inc.", "endpoint_class": "Server"},
        # a dual-homed storage endpoint: SAME MAC on sw1 + sw2 (both in group G1)
        {"host": "sw1", "port": "Te1/1", "vlan": "20", "ip": "10.0.0.5", "mac": "bb:00:00:00:00:01",
         "vendor": "NetApp", "endpoint_class": "Storage"},
        {"host": "sw2", "port": "Te1/1", "vlan": "20", "ip": "10.0.0.5", "mac": "bb:00:00:00:00:01",
         "vendor": "NetApp", "endpoint_class": "Storage"},
    ]
    mg = [{"group": "G1", "switches": ["sw1", "sw2"]}, {"group": "G2", "switches": ["sw3"]}]
    dep = compute_endpoint_dependencies(ident, mg)
    # cluster: Dell Server, 3 endpoints across 3 switches, spanning both move-groups
    clu = next(c for c in dep["clusters"] if c["endpoint_class"] == "Server" and "Dell" in c["vendor"])
    assert clu["count"] == 3 and clu["switches"] == 3 and clu["spans_groups"] is True
    # dual-homed: NetApp storage MAC on sw1+sw2 (same group -> not split)
    dh = next(d for d in dep["dual_homed"] if d["endpoint_class"] == "Storage")
    assert sorted(dh["switches"]) == ["sw1", "sw2"] and dh["split_across_groups"] is False
    # per-switch validation: sw1 hosts Server + Storage -> checklist lines + a dual-homed note
    v = dep["per_switch_validation"]["sw1"]
    assert any("Storage" in line for line in v) and any("Dual-homed" in line for line in v)


def test_classify_apc_real_registry_name_chained():
    """[audit-4 #13] CHAIN the real OUI output (not a marketing string): block 00C0B7's genuine IEEE/Wireshark
    registry name is 'American Power Conversion Corp', which contains NONE of the UPS rule substrings -- so real
    APC UPS endpoints fell through unclassified (342 rows / 311 Unknown on the [HISTORY-REDACTED] snapshot). The existing fixture
    feeds 'APC by Schneider Electric', which always matched -- the self-authored fixture that hid the miss."""
    from cisco_toolkit import ouidb
    from cisco_toolkit.analyze import _classify_endpoint
    v = ouidb.vendor_for_mac("00:c0:b7:12:34:56")
    assert "american power conversion" in v.lower()                       # the REAL registry name, not marketing
    cls, _conf, ev = _classify_endpoint(v, "", "", "", False)
    assert cls == "UPS/PDU" and "vendor" in ev and "no vendor" not in ev.lower()   # classifies + truthful evidence


def test_classify_resolved_vendor_evidence_never_says_no_vendor():
    """[audit-4 #13 moat] when a vendor WAS resolved but matched no class rule, the evidence must not claim 'no
    vendor signal' (the row's own vendor column is populated). 'no vendor/...' is only truthful when vendor is
    genuinely empty. (On the [HISTORY-REDACTED] snapshot the false string hit 1770/5127 rows, true in 0.)"""
    from cisco_toolkit.analyze import _classify_endpoint
    for v in ("American Power Conversion Corp", "Cisco Systems", "DigiBoard", "Myricom", "Mellanox",
              "Brocade", "Data Direct Networks", "Some Unlisted Maker Inc"):
        _cls, _conf, ev = _classify_endpoint(v, "", "", "", False)
        assert "no vendor" not in ev.lower(), f"false 'no vendor' evidence for resolved vendor {v!r}: {ev!r}"
    _cls, _conf, ev = _classify_endpoint("", "", "", "", False)           # genuinely no vendor -> honest 'no vendor'
    assert "no vendor" in ev.lower()
