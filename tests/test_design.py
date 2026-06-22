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


def test_design_scale_reads_canonical_executive_brief(tmp_path):
    """A5 (SSOT): the HLD scale figures (devices / VLANs in scope) must read the canonical
    executive_brief.scale — the published single source the explorer/deck/webapp read — not a local
    recount. Discriminating fixture: scale says 999 devices / 777 VLANs while the raw arrays hold a
    handful each, so a recompute regression would render the small count, not the canonical 999/777."""
    snap = _snap()
    snap["executive_brief"]["scale"] = {"n_devices": 999, "n_vlans": 777, "n_endpoints": 5000}
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "999" in text       # "Devices in scope" reads canonical scale
    assert "777" in text       # "VLANs in use" reads canonical scale


def test_design_fhrp_candidates_not_mislabeled_as_configured_groups(tmp_path):
    """FHRP false-redundancy class: snap['fhrp'] is the set of MULTI-GATEWAY VLANs (FHRP candidates),
    most/all WITHOUT a configured first-hop-redundancy protocol (every member fhrp=False — the AJ shape).
    The §2.4 resilience table must NOT label them 'FHRP gateway groups' (which reads as 'N FHRP groups
    protect the gateways'); it labels them candidates and surfaces the honest count actually running
    FHRP (0 here), so the design doc can never imply redundancy that is not configured."""
    snap = _snap()
    snap["fhrp"] = [
        {"vid": 3, "issues": ["3 gateways but no FHRP — no first-hop redundancy"],
         "members": [{"host": "a", "fhrp": False}, {"host": "b", "fhrp": False}, {"host": "c", "fhrp": False}]},
        {"vid": 4, "issues": ["2 gateways but no FHRP — no first-hop redundancy"],
         "members": [{"host": "a", "fhrp": False}, {"host": "b", "fhrp": False}]},
    ]
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "FHRP gateway groups" not in text, "must not imply configured FHRP groups exist (false redundancy)"
    assert "Multi-gateway VLANs (FHRP candidates)" in text
    assert "first-hop redundancy (FHRP) configured" in text


def test_design_interoperability_footprint_section(tmp_path):
    """N14: the HLD must surface what the target design has to keep INTEROPERATING with — the
    observed NOS-family spread and the multi-vendor endpoint estate (OUI-derived) — grounded in
    devices[].platform + endpoint_identity, framed honestly as per-MAC observations (NOT a
    service-dependency / HA-cluster claim)."""
    snap = _snap()
    hosts = list(snap["devices"])
    for i, h in enumerate(hosts):
        snap["devices"][h]["platform"] = "nxos" if i == 0 else "ios"   # two NOS families
    snap["endpoint_identity"] = (
        [{"vendor": "Hewlett Packard", "endpoint_class": "Server", "mac": f"aaaa.0000.{i:04x}"} for i in range(5)]
        + [{"vendor": "APC by Schneider Electric", "endpoint_class": "UPS/PDU", "mac": "bbbb.0000.0001"}])
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert any("Interoperability" in t for t in h1), h1
    text = _all_text(d)
    assert "IOS" in text and "NXOS" in text                          # both NOS families surfaced
    assert "Hewlett Packard" in text and "APC by Schneider Electric" in text   # vendor mix
    assert "Server" in text and "UPS/PDU" in text                    # class mix
    assert "not a service-dependency" in text.lower() or "not a service-dependency graph" in text  # honest framing


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


def test_design_renders_canonical_blueprint_section(tmp_path):
    """When the snapshot carries the canonical design_blueprint, §4 renders the CCDE-grounded decisions,
    the trade-off scorecard and the open requirement questions (not the punch-list fallback) — proving the
    design DOCX reads the single source of truth rather than re-deriving design intent."""
    snap = _snap()
    snap["design_blueprint"] = {
        "summary": {"headline": "1 critical target-state design decision(s); leading: introduce FHRP.",
                    "n_decisions": 2, "n_recommended": 1, "n_needs_requirement": 1, "n_critical": 1,
                    "by_domain": {}, "requirements_provided": False},
        "tradeoff_scorecard": [{"axis": "availability", "label": "High availability & resiliency",
                                "score": 0, "posture": "Weak", "evidence": "no FHRP; SPOFs present"}],
        "decisions": [
            {"id": "fhrp-first-hop-gateway-redundancy", "title": "Introduce first-hop redundancy",
             "domain": "methodology", "priority": "Critical", "status": "recommended",
             "confidence": "Observed", "driver": "Gateway resilience",
             "evidence": {"summary": "52 VLAN(s) without FHRP", "count": 52, "devices": []},
             "principle": {"id": "fhrp-first-hop-gateway-redundancy", "title": "First-hop redundancy",
                           "citation": "CCDE In Depth — High Availability"},
             "recommended_action": "Deploy HSRP/VRRP across dual gateways", "alternatives": "GLBP; anycast gateway",
             "tradeoffs": "HA vs simplicity", "axes": ["availability", "convergence"], "requirements_needed": []},
            {"id": "availability-right-sized-per-tier", "title": "Right-size availability per tier",
             "domain": "methodology", "priority": "High", "status": "needs-requirement",
             "confidence": "Requirement-needed", "driver": "WHY-first",
             "evidence": {"summary": "redundancy posture varies by tier", "count": 0, "devices": []},
             "principle": {"id": "availability-right-sized-per-tier", "title": "Right-size availability",
                           "citation": "CCDE In Depth — Fundamentals"},
             "recommended_action": "Assign an availability target per class", "alternatives": "uniform SLA fleet-wide",
             "tradeoffs": "HA vs cost", "axes": ["availability", "cost"], "requirements_needed": ["availability_tier"]},
        ],
        "requirements_model": {"fields": [], "open_questions": [], "provided": False, "note": ""},
        "coverage": {"inventory": 3, "collected": 3, "not_collected": 0,
                     "caveat": "grounded only in collected evidence"},
        "methodology": "WHY-first.", "axes": [],
    }
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    for token in ("4.1 Design trade-off scorecard", "4.2 Recommended target-state design decisions",
                  "4.3 Open design questions (requirements to confirm)"):
        assert token in h2, f"missing §4 subsection: {token}; have {h2}"
    text = _all_text(d)
    assert "Introduce first-hop redundancy" in text                 # the recommended decision
    assert "CCDE In Depth — High Availability" in text              # traced to its CCDE basis
    assert "Right-size availability per tier" in text               # the open requirement question
    assert "availability_tier" in text
    text = _all_text(d)
    assert "Revision history" in text and "Assumptions & caveats" in text
    assert "Customer network owner" in text                      # acceptance signature roles
    assert "Per-Wave Method of Procedure (.docx)" in text        # related-documents cross-reference


def test_design_renders_full_doctrine_catalogue(tmp_path):
    """§4.4 surfaces the FULL CCDE doctrine reference (incl. non-actionable domains the L1-L4 assessment
    cannot trigger, e.g. firewall), so the HLD reasons with the whole knowledge base, not only the
    auto-emitted decisions -- proving the 51 'dark' principles reach the page."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["design_blueprint"] = compute_design_blueprint(snap)        # real blueprint -> carries the doctrine catalogue
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    assert "4.4 Design doctrine applied (CCDE-grounded reference)" in h2, f"missing §4.4; have {h2}"
    text = _all_text(d)
    assert ("screened-subnet" in text) or ("DMZ" in text), "firewall doctrine must surface in the HLD §4.4"


def test_design_renders_target_state_architecture(tmp_path):
    """C: §5 renders the generated CANDIDATE target-state architecture (tier model, L2/L3 boundary,
    resilience, lifecycle disposition, migration), each row current->target with its rationale."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["design_blueprint"] = compute_design_blueprint(snap)
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert any("proposed target-state architecture" in t.lower() for t in h1), f"missing §5; have {h1}"
    text = _all_text(d)
    assert "Topology / tier model" in text                       # a target-state dimension
    assert "candidate" in text.lower()                            # honest framing


def test_design_renders_replacement_bom(tmp_path):
    """C next-layer: §5 surfaces the target-state replacement BoM (EoL gear to procure), grounded in
    lifecycle evidence — the target-procurement detail the as-built §3.4 BoM does not give."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["lifecycle_risk"] = {"per_device": [
        {"host": "a", "band": "Past-LDoS", "model": "WS-C4948E"},
        {"host": "b", "band": "Past-LDoS", "model": "WS-C4948E"}]}
    snap["design_blueprint"] = compute_design_blueprint(snap)
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Replacement" in text and "WS-C4948E" in text         # target procurement surfaced in §5


def test_design_renders_addressing_plan_when_supernet_supplied(tmp_path):
    """F1: with an address_space requirement, §5.3 renders a candidate per-VLAN IP allocation from it."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["design_blueprint"] = compute_design_blueprint(snap, {"address_space": "10.50.0.0/16"})
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Net-new IP addressing plan" in text and "10.50." in text


def test_design_addressing_plan_needs_requirement_discloses_census(tmp_path):
    """SSOT + coverage-honesty: with NO address_space, HLD §5.3 still discloses the VLAN census
    context (total / sizeable-observed / querier-only un-sizable) the snapshot carries — not just
    'requirement needed'. Mirrors the explorer's addressing-plan block so the deliverable matches the
    canonical addressing_plan instead of silently dropping the census the engine computed."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    # a querier-only VLAN (live per IGMP, no access port / SVI) -> census(3) > sizeable(2), 1 un-sizable
    snap["service_map"]["multicast"]["igmp_queriers"].append(
        {"switch": "core1", "vlan": "777", "querier": "10.0.77.1"})
    bp = compute_design_blueprint(snap)  # no address_space -> needs-requirement path
    snap["design_blueprint"] = bp
    ap = bp["target_state"]["addressing_plan"]
    assert ap["status"] == "needs-requirement"
    assert (ap["n_census_vlans"], ap["observed_vlans"], ap["n_unsizable"]) == (3, 2, 1)
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    paras = [p.text for p in Document(out).paragraphs]
    assert any("Net-new IP addressing plan" in p for p in paras)
    census_line = next((p for p in paras if "census" in p.lower()), None)
    assert census_line is not None, "§5.3 must disclose the VLAN census on the needs-requirement path"
    # the disclosed sentence carries all three canonical counts
    assert "3" in census_line and "2" in census_line and "1" in census_line, census_line


def test_design_renders_wave_plan(tmp_path):
    """F2: §5.4 renders the candidate migration wave plan derived from move-groups."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["move_groups"] = [{"switches": [f"SW{i:03d}" for i in range(95)], "spanning_vlans": [[124, "X", 95]]}]
    snap["design_blueprint"] = compute_design_blueprint(snap)
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Candidate migration wave plan" in text and "coupled-subwave" in text


def test_design_renders_zone_aware_ip_plan(tmp_path):
    """AUDIT: §5.3 renders the per-zone summary table when the IP plan is zone-aware (vlan_zones supplied)."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["l3_forwarding"] = [{"switch": "d", "vlan": "10", "svi_ip": "10.0.10.1"},
                             {"switch": "d", "vlan": "20", "svi_ip": "10.0.20.1"}]
    snap["design_blueprint"] = compute_design_blueprint(
        snap, {"address_space": "10.20.0.0/16", "vlan_zones": {10: "PCI", 20: "corp"}})
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Per-zone summarization" in text and "PCI" in text
    """V3.23.153: LLD §3.5 — version sprawl per model is flagged with the most widely deployed
    image as the standardization candidate, and past-EoS hardware gets a replace-not-upgrade rec."""
    snap = _snap()
    # second + third 2960X: two devices on 15.2(7)E, the original acc1 on 15.2 → MIXED, candidate 15.2(7)E
    for n in ("acc2", "acc3"):
        snap["devices"][n] = {"hostname": n, "model": "WS-C2960X-48FPD-L", "serial_number": f"S{n}",
                              "sw_version": "15.2(7)E", "platform": "ios"}
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h2 = [p.text for p in d.paragraphs if p.style.name == "Heading 2"]
    assert any(t == "3.5 Software plan & recommendations" for t in h2), h2
    text = _all_text(d)
    assert "MIXED — standardize on 15.2(7)E" in text          # majority image is the candidate
    assert "validate it against Cisco's published recommended release" in text
    assert "replacement, not an image upgrade" in text and "WS-C2960X-48FPD-L" in text


def test_design_software_plan_consistent_fleet_message(tmp_path):
    """A fleet with one image per model and no past-EoS hardware gets the carry-forward message."""
    snap = _snap()
    snap["lifecycle_risk"]["per_device"][2]["band"] = "Active"   # acc1 no longer Past-EoS
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "carry the current images forward as the minimum-version baseline" in text
    assert "MIXED" not in text


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


def test_design_vlan_inventory_is_canonical_single_source():
    """Single source of truth: the design doc's VLAN inventory must BE analyze.vlan_inventory — the
    same derivation the CRD reads — so 'VLANs in use' agrees across deliverables, and an L3-only VLAN
    (a gateway SVI with no access port) is counted, not silently dropped by an access-port-only tally."""
    from cisco_toolkit.analyze import vlan_inventory
    from cisco_toolkit.design import _vlan_inventory
    snap = {
        "interfaces": {
            "acc1": {"Gi1/0/1": {"switchport_mode": "Access", "vlan": "10",
                                 "end_host_mac": "aaaa.0000.0001"}},
        },
        # VLAN 40 has an L3 gateway but sits on NO access port -> only the canonical inventory sees it
        "l3_forwarding": [{"switch": "core1", "vlan": "40", "svi_ip": "10.0.40.1"}],
    }
    canonical = vlan_inventory(snap)
    assert {v for v, _ in canonical} == {10, 40}        # access 10 + L3-only 40
    assert _vlan_inventory(snap) == canonical           # design delegates to the ONE derivation (no drift)


def test_design_bom_labels_past_eos_as_refresh_not_replace(tmp_path):
    """REVIEW #3: a still-supported Past-EoS device must appear under REFRESH (label names past-EoS), never
    in a 'Replace (past-LDoS)' row -- the §5.1 BoM must not call supported gear past-LDoS/replace-now."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()                                       # acc1 is Past-EoS WS-C2960X-48FPD-L; no Past-LDoS
    snap["design_blueprint"] = compute_design_blueprint(snap)   # §5.1 reads the canonical blueprint
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Refresh (near-LDoS / past-EoS)" in text     # refresh label now names past-EoS
    assert "Replace (past-LDoS)" not in text            # no replace row (the fleet has 0 Past-LDoS)


def test_design_53_renders_when_candidate_but_no_subnets(tmp_path):
    """REVIEW #9: a candidate addressing plan that allocated NO subnets (supernet too small / overflow) must
    still render §5.3 with its 'enlarge the address_space' note, not be silently dropped."""
    from cisco_toolkit.design_advisor import compute_design_blueprint
    snap = _snap()
    snap["design_blueprint"] = compute_design_blueprint(snap, {"address_space": "10.0.0.0/30"})
    ap = snap["design_blueprint"]["target_state"]["addressing_plan"]
    assert ap["status"] == "candidate" and not ap.get("subnets") and not ap.get("requirement_needed")
    out = str(tmp_path / "d.docx")
    write_design_doc_docx(out, snap, "Unit Test Fleet")
    paras = [p.text for p in Document(out).paragraphs]
    assert any("Net-new IP addressing plan" in p for p in paras)
    assert any("smaller than a /24" in p or "enlarge" in p.lower() for p in paras)
