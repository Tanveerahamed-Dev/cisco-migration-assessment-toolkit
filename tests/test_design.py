"""NEW-V3.23.148: the As-Built Network Design Document (HLD + LLD, DOCX) deliverable. python-docx is
optional, so the whole module is skipped when it is absent (the generator itself fails soft the same
way). These tests pin the HLD/LLD section structure, the reconciliation of the as-built facts to the
snapshot, the BoM aggregation, and the fail-soft path."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.design import write_design_doc_docx  # noqa: E402


def _snap():
    """A representative snapshot exercising every section the design generator builds."""
    return {
        "script_version": "V3.23.0",
        "devices": {
            "core1": {"hostname": "core1", "model": "N9K-C93180YC", "serial_number": "SAL001",
                      "sw_version": "10.2", "platform": "nxos", "total_ports": 48, "active_ports": 30},
            "dist1": {"hostname": "dist1", "model": "C9300-48T", "serial_number": "SAL002",
                      "sw_version": "17.9", "platform": "ios", "total_ports": 48, "active_ports": 20},
            "acc1": {"hostname": "acc1", "model": "WS-C2960X-48FPD-L", "serial_number": "SAL003",
                     "sw_version": "15.2", "platform": "ios", "total_ports": 48, "active_ports": 12},
        },
        "interfaces": {
            "core1": {"Vlan10": {"svi_ip": "10.0.10.1", "hsrp_behavior": "HSRP grp10 active", "vrf": "PROD",
                                 "acl_in": "PROD_IN"},
                      "Vlan20": {"svi_ip": "10.0.20.1"},
                      "Po1": {"switchport_mode": "Trunk", "cdp_neighbor": "dist1"},
                      "Te1/1": {"switchport_mode": "Trunk", "cdp_neighbor": "dist1"}},
            "dist1": {"Vlan10": {"svi_ip": "10.0.10.2", "hsrp_behavior": "HSRP grp10 standby"},
                      "Gi1/0/1": {"switchport_mode": "Trunk", "cdp_neighbor": "core1"},
                      "Gi1/0/24": {"switchport_mode": "Access", "vlan": "10", "vlan_name": "PROD",
                                   "end_host_mac": "aaaa.0000.0001"}},
            "acc1": {"Gi1/0/1": {"switchport_mode": "Trunk", "cdp_neighbor": "dist1"},
                     "Gi1/0/5": {"switchport_mode": "Access", "vlan": "20", "vlan_name": "VOICE",
                                 "end_host_mac": "bbbb.0000.0001"}},
        },
        "l3_forwarding": [
            {"switch": "core1", "vlan": "10", "svi_ip": "10.0.10.1", "fhrp": "HSRP active",
             "role": "primary", "risk": ""},
            {"switch": "dist1", "vlan": "10", "svi_ip": "10.0.10.2", "fhrp": "HSRP standby",
             "role": "secondary", "risk": ""},
            {"switch": "core1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "",
             "role": "", "risk": "single-gateway"},
        ],
        "routing_neighbors": {"core1": {"ospf": [{"neighbor": "10.0.0.2", "state": "FULL"}],
                                        "eigrp": [], "bgp": [{"neighbor": "10.0.0.3", "as": "65001",
                                                              "state": "Established"}]}},
        "redistribution": {"core1": [{"into_proto": "bgp", "from_proto": "ospf", "route_map": "OSPF_TO_BGP"}]},
        "stp_roots": {"core1": {"10": {"is_root": True, "root_priority": "24576"},
                                "20": {"is_root": True, "root_priority": "24576"}}},
        "fhrp": [{"vid": "10", "members": [{"host": "core1"}, {"host": "dist1"}], "issues": []},
                 {"vid": "20", "members": [{"host": "core1"}], "issues": ["no FHRP peer"]}],
        "vpc": {"core1": {"domain_id": "1", "role": "primary", "peer_status": "peer-ok", "vpcs": []}},
        "lifecycle_risk": {
            "per_device": [
                {"host": "core1", "model": "N9K-C93180YC", "band": "Active", "eos": "", "ldos": ""},
                {"host": "dist1", "model": "C9300-48T", "band": "Active", "eos": "", "ldos": ""},
                {"host": "acc1", "model": "WS-C2960X-48FPD-L", "band": "Past-EoS",
                 "eos": "2025-04-30", "ldos": "2030-04-30"},
            ],
            "summary": {"n_devices": 3, "by_band": {"Active": 2, "Past-EoS": 1}, "n_past_eos": 1,
                        "n_past_ldos": 0, "n_near": 0},
        },
        "capacity": [{"hostname": "core1", "model": "N9K-C93180YC", "total_ports": 48,
                      "active_ports": 30, "free_ports": 18, "port_util": 62.5}],
        "failure_impact": [{"host": "core1", "severity": "High", "vlans_impacted": 2, "stranded": 12,
                            "hard": 4, "detail": "core1 fronts both gateways"}],
        "punchlist": [{"severity": "Critical", "category": "L3 design", "devices": ["core1"],
                       "title": "VLAN 20 has a single gateway (no FHRP)", "detail": "x"},
                      {"severity": "High", "category": "Lifecycle", "devices": ["acc1"],
                       "title": "acc1 is past end-of-sale", "detail": "y"}],
        "subnet_intelligence": {
            "per_device": [
                {"host": "dist1", "is_l3": False, "served_subnets": [
                    {"subnet": "10.0.10.0/24", "gateway": "core1", "vlan": "10"}]},
                {"host": "acc1", "is_l3": False, "served_subnets": [
                    {"subnet": "10.0.20.0/24", "gateway": "core1", "vlan": "20"}]},
            ],
            "move_groups": [],
        },
        "service_map": {
            "multicast": {"active_interfaces": 4, "active_switch_count": 2,
                          "classified_groups": [{"group": "224.0.1.129", "name": "PTP-primary",
                                                 "category": "Broadcast-AV", "broadcast": True}],
                          "igmp_queriers": [{"switch": "core1", "vlan": "10", "querier": "10.0.10.1"}],
                          "ptp": {"core1": {"operational": True}, "dist1": {"operational": False}}},
        },
        "executive_brief": {"posture_statement": "A two-tier campus with a single-gateway exposure on VLAN 20.",
                            "axes": [], "top_gating": []},
    }


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_design_has_hld_and_lld_sections(tmp_path):
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    for token in ("1. Executive Design Summary", "2. High-Level Design (HLD)",
                  "3. Low-Level Design (LLD)", "4. Target-State Design Recommendations"):
        assert any(t == token for t in h1), f"missing section: {token}; have {h1}"
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    for token in ("2.3 Layer-3 design", "2.5 Multicast & timing design",
                  "3.1 Device inventory & roles", "3.4 Equipment list (Bill of Materials)"):
        assert any(t == token for t in h2), f"missing subsection: {token}"


def test_design_reconciles_to_snapshot(tmp_path):
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # device inventory carries every device + model + lifecycle band
    for token in ("core1", "dist1", "acc1", "N9K-C93180YC", "C9300-48T", "WS-C2960X-48FPD-L", "Past-EoS"):
        assert token in text, token
    # HLD L3: routing protocols recovered from neighbours
    assert "OSPF" in text and "BGP" in text
    # addressing plan joins the served subnet to the VLAN/gateway
    assert "10.0.10.0/24" in text and "10.0.10.1" in text
    # multicast/timing design surfaces the classified group + PTP
    assert "PTP-primary" in text or "224.0.1.129" in text
    # target-state recommendations are the punch-list read as design intent
    assert "single gateway" in text.lower()


def test_design_bom_aggregates_by_model(tmp_path):
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    # the BoM table has one row per distinct model (3 here) + header
    bom = None
    for t in d.tables:
        if t.rows[0].cells[0].text == "Model":
            bom = t
            break
    assert bom is not None, "BoM table not found"
    models = {r.cells[0].text for r in bom.rows[1:]}
    assert models == {"N9K-C93180YC", "C9300-48T", "WS-C2960X-48FPD-L"}


def test_design_multicast_section_suppressed_when_no_activity(tmp_path):
    """A multicast dict that exists but carries all-zero counts (non-media fabric, or the commands were
    not collected) gets the fallback message — not an all-zeros 'PTP: 0 of 0' filler paragraph."""
    snap = _snap()
    snap["service_map"] = {"multicast": {"active_interfaces": 0, "active_switch_count": 0,
                                         "classified_groups": [], "igmp_queriers": [], "ptp": {}}}
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "No multicast/PTP activity was classified" in text
    assert "0 of 0 device(s)" not in text


def test_design_tolerates_malformed_stp_roots(tmp_path):
    """A stp_roots VLAN value that is not a dict (malformed snapshot) must not abort the design doc."""
    snap = _snap()
    snap["stp_roots"] = {"core1": {"10": None, "20": "garbage", "30": {"is_root": True}}}
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")   # must not raise
    import os
    assert os.path.exists(out)


def test_design_carries_document_furniture(tmp_path):
    """V3.23.150: AS-style front/back matter — Document Control between cover and TOC, and the
    closing acceptance signature gate."""
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert "Document Control" in h1 and "Document Acceptance" in h1
    text = _all_text(d)
    assert "Revision history" in text and "Assumptions & caveats" in text
    assert "Customer network owner" in text                      # acceptance signature roles
    assert "Per-Wave Method of Procedure (.docx)" in text        # related-documents cross-reference


def test_design_failsoft_without_python_docx(monkeypatch, tmp_path):
    import builtins, os
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    assert not os.path.exists(out)
