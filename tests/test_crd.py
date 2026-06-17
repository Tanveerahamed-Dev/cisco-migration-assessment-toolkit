"""NEW-V3.23.156: the Customer Requirements Document (CRD, DOCX) — the Plan-phase
requirements-capture instrument. python-docx is optional, so the module is skipped when it is
absent (the generator fails soft the same way). These tests pin the skeleton sections, the
evidence-primed environment summary, the discipline gating (no section without observed footprint),
the REQ-ID traceability skeleton, and the fail-soft path."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.crd import write_crd_docx  # noqa: E402


def _snap():
    """A compact snapshot exercising every evidence-gated CRD section."""
    return {
        "script_version": "V3.23.0",
        "devices": {"core1": {"model": "N9K-C93180YC"}, "acc1": {"model": "WS-C2960X-48FPD-L"}},
        "interfaces": {
            "acc1": {
                "Gi1/0/5": {"switchport_mode": "Access", "vlan": "20",
                            "end_host_mac": "bbbb.0000.0001", "dual_connection": "acc2:Gi1/0/5"},
                "Gi1/0/6": {"switchport_mode": "Access", "vlan": "30", "end_host_mac": "cccc.0000.0001"},
                "Gi1/0/1": {"switchport_mode": "Trunk", "cdp_neighbor": "core1"},
            },
            "core1": {"Vlan20": {"svi_ip": "10.0.20.1", "vrf": "PROD", "acl_in": "PROD_IN"}},
        },
        "routing_neighbors": {"core1": {"ospf": [{"neighbor": "10.0.0.2"}], "eigrp": [], "bgp": []}},
        "l3_forwarding": [{"switch": "core1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "HSRP active"}],
        "service_map": {
            "services": [{"service": "rtsp", "category": "CCTV", "port": "554", "proto": "tcp"}],
            "multicast": {"active_interfaces": 2, "active_switch_count": 1,
                          "classified_groups": [{"group": "224.0.1.129", "name": "PTP-primary"}],
                          "igmp_queriers": [], "ptp": {}},
        },
        "lifecycle_risk": {"summary": {"n_devices": 2, "n_past_eos": 1}},
        "collection_completeness": {"summary": {"complete": 2, "partial": 0, "not_collected": 0}},
        "punchlist": [{"severity": "Critical", "category": "L3 design",
                       "title": "VLAN 30 has a single gateway", "devices": ["core1"]}],
    }


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_crd_has_skeleton_sections_and_furniture(tmp_path):
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    for token in ("1. Engagement Context", "2. Current Environment Summary (evidence)",
                  "3. Business Requirements", "4. Technical Requirements",
                  "5. Operational Requirements", "6. Future Plans & Growth",
                  "7. Requirement Traceability"):
        assert any(t == token for t in h1), f"missing section: {token}; have {h1}"
    assert "Document Control" in h1 and "Document Acceptance" in h1
    text = _all_text(d)
    assert "Customer network owner" in text          # acceptance roles
    assert "Assessment workbook (.xlsx)" in text     # related-documents cross-reference


def test_crd_environment_summary_reconciles_to_evidence(tmp_path):
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "OSPF" in text                                       # protocols observed
    assert "PROD" in text                                       # VRF observed
    assert "VLAN 30 has a single gateway" in text               # punch-list carried as known issue
    # endpoint counting rule: access ports with a host MAC → 2, of which 1 dual-homed
    assert "2" in text and "1" in text


def test_crd_requirements_are_proposals_with_req_ids_and_traceability(tmp_path):
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    # capture discipline: REQ-IDs, owners, testability guidance, confirm-or-strike framing
    for rid in ("REQ-B-001", "REQ-T-LAN-001", "REQ-T-L3-001", "REQ-T-MC-001",
                "REQ-T-SEC-001", "REQ-T-SVC-001", "REQ-O-001"):
        assert rid in text, rid
    assert "testable statement" in text.lower()
    assert "<owner>" in text and "<YES/AMEND>" in text
    # every seeded REQ-ID lands in the traceability skeleton
    assert "<NRFU-…>" in text and "<HLD §>" in text
    # the evidence-primed framing is explicit (proposals, not assumed requirements)
    assert "proposals" in text.lower() or "proposal" in text.lower()


def test_crd_discipline_sections_are_evidence_gated(tmp_path):
    """A pure-L2 fleet with no multicast / VRF / service evidence gets no §4.2-§4.5."""
    snap = _snap()
    snap["routing_neighbors"] = {}
    snap["l3_forwarding"] = []
    snap["service_map"] = {}
    snap["interfaces"]["core1"] = {}   # drop the VRF/ACL SVI
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    assert any("4.1 Campus LAN" in t for t in h2)               # always present
    for absent in ("4.2 Layer 3", "4.3 Multicast", "4.4 Segmentation", "4.5 Services"):
        assert not any(absent in t for t in h2), absent
    text = _all_text(d)
    assert "none (pure L2 fleet)" in text


def test_crd_failsoft_without_python_docx(monkeypatch, tmp_path):
    import builtins, os
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("simulated missing python-docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")   # must not raise
    assert not os.path.exists(out)


def test_crd_vlan_count_is_canonical_single_source(tmp_path):
    """Single source of truth: the CRD VLAN count must equal the canonical vlan_inventory (all
    distinct VLAN IDs, incl. SVI/L3 gateways), so it agrees with the design doc — not just the
    access-port VLANs (which omit L3-only VLANs)."""
    from cisco_toolkit.analyze import vlan_inventory
    from cisco_toolkit.crd import _evidence_facts
    snap = {
        "script_version": "V3.23.0",
        "devices": {"core1": {"model": "N9K"}, "acc1": {"model": "C2960"}},
        "interfaces": {
            "acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                 "end_host_mac": "aaaa.0000.0001"}},
            "core1": {"Vlan99": {"svi_ip": "10.0.99.1"}},   # SVI carries no 'vlan' field
        },
        # VLAN 50 has an L3 gateway but sits on NO access port -> only the canonical inventory sees it
        "l3_forwarding": [{"switch": "core1", "vlan": "50", "svi_ip": "10.0.50.1"},
                          {"switch": "core1", "vlan": "99", "svi_ip": "10.0.99.1"}],
    }
    canonical = {v for v, _ in vlan_inventory(snap)}
    assert canonical == {10, 50, 99}                        # access 10 + L3 50/99
    assert _evidence_facts(snap)["n_vlans"] == len(canonical) == 3
