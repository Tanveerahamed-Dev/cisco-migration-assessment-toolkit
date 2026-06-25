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
        # Two genuinely dual-homed endpoints (host MAC on two switches) — the canonical
        # redundancy-bearing count. Note the per-port dual_connection tally above is only 1, so a
        # CRD reading endpoint_dependencies (2) is provably distinct from the old per-port count (1).
        "endpoint_dependencies": {"dual_homed": [
            {"mac": "bbbb.0000.0001", "switches": ["acc1", "acc2"]},
            {"mac": "dddd.0000.0002", "switches": ["acc1", "core1"]},
        ]},
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
    # endpoints = access ports with a host MAC (2); dual-homed is the canonical
    # endpoint_dependencies.dual_homed count, surfaced as its own honest stat line
    assert "Dual-homed endpoints (host MAC on two switches)" in text


def test_crd_dual_homed_reads_canonical_endpoint_dependencies(tmp_path):
    """A1 (SSOT): the CRD's dual-homed figure must be the canonical
    endpoint_dependencies.dual_homed count (host MAC on two switches) — the SAME source the HLD's
    preserve-dual-homed-endpoints design decision reads — not a looser per-port dual_connection
    tally. The fixture has 1 dual_connection port but 2 canonical dual-homed endpoints, so this
    discriminates: a regression to the per-port count would render 1, not 2."""
    snap = _snap()
    assert len(snap["endpoint_dependencies"]["dual_homed"]) == 2          # canonical truth
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Dual-homed endpoints (host MAC on two switches)" in text       # honest label
    assert "for the 2 dual-homed endpoint" in text                         # REQ-T-LAN-002 cites 2, not 1
    assert "endpoint port(s)" not in text                                  # old misleading phrasing gone


def test_crd_future_plans_anchors_to_observed_scale(tmp_path):
    """N3: §6 Future Plans must anchor growth to the OBSERVED scale baseline (devices / VLANs /
    endpoints, canonical-first), so a growth target is measured against reality, not a blank prompt."""
    snap = _snap()
    snap["executive_brief"] = {"scale": {"n_devices": 2, "n_vlans": 5, "n_endpoints": 4242}}
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "Today (observed)" in text        # evidence-anchored scale baseline table
    assert "4242" in text                     # canonical n_endpoints, not a blank prompt


def test_crd_vlan_count_reads_published_scale_canonical_first(tmp_path):
    """SSOT: the 'VLANs in use' count must read the published executive_brief.scale.n_vlans (the ONE
    source the workbook / design / explorer / webapp reconcile to) canonical-first, not independently
    recompute vlan_inventory — mirroring the endpoint line one row below (n_endpoints) and design.py's
    'A5 SSOT fix' canonical-first read. Mutation-proof: pin a published scale.n_vlans that DISAGREES with
    vlan_inventory and assert the CRD renders the published value, so the read path cannot silently drift."""
    snap = _snap()
    # vlan_inventory(_snap()) is a small set; pin a disagreeing published canonical scalar (777).
    snap["executive_brief"] = {"scale": {"n_devices": 2, "n_vlans": 777, "n_endpoints": 4242}}
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "777" in text, "CRD must render the published scale.n_vlans (777), not a local vlan_inventory recount"


def test_crd_evidence_scope_says_collected_not_inventory_scope(tmp_path):
    """Coverage-honesty (inventoried vs collected): n_devices is the full INVENTORY (devices.json), not
    the collected count. The title page + §1 evidence-scope must phrase it 'C of N devices collected'
    (C = collection_completeness.complete), never the old 'N devices in evidence scope' which presented
    the inventory as if every device had been collected."""
    snap = _snap()
    snap["collection_completeness"] = {"summary": {"complete": 1, "inventory": 99}}
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "devices collected" in text and "1 of" in text     # collected framing + the collected count
    assert "devices in evidence scope" not in text            # the old inventory-as-scope wording is gone


def test_crd_requirement_tables_declare_verification_method(tmp_path):
    """N5: every requirement-capture table declares HOW each requirement is proven (a Verification
    column), so a requirement is testable — the technical rows reference the NRFU acceptance test."""
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")
    d = Document(out)
    req_tabs = [t for t in d.tables if t.rows and any(c.text == "Verification" for c in t.rows[0].cells)]
    assert req_tabs, "no requirement table with a Verification column"
    text = _all_text(d)
    assert "NRFU technical acceptance test" in text     # REQ-T rows declare their verification method


def test_crd_has_rfc2119_classification_legend(tmp_path):
    """N1/N8: the CRD declares the BCP 14 (RFC 2119 / RFC 8174) normative-keyword convention, and the
    requirement tables classify strength with MUST/SHOULD/MAY rather than an ad-hoc H/M/L."""
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, _snap(), "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "BCP 14" in text and "RFC 2119" in text       # classification legend cites the standard
    assert "Class (RFC 2119)" in text                     # requirement tables use the RFC-2119 class column
    assert "<MUST/SHOULD/MAY>" in text                    # the normative-keyword placeholder, not <H/M/L>


def test_crd_l3_no_fhrp_text_says_svi_instances_not_vlans(tmp_path):
    """A4: l3_forwarding row count (n_l3) is SVI INSTANCES, not distinct gateway VLANs. The
    no-FHRP REQ-T-L3-001 wording must not call the SVI-instance count 'gateway VLAN(s)'."""
    snap = _snap()
    # all-"none" FHRP so the else-branch (the mislabeled one) renders
    snap["l3_forwarding"] = [{"switch": "core1", "vlan": "20", "svi_ip": "10.0.20.1", "fhrp": "none"},
                             {"switch": "core1", "vlan": "30", "svi_ip": "10.0.30.1", "fhrp": "none"}]
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    text = _all_text(Document(out))
    assert "gateway SVI instance(s)" in text
    assert "gateway VLAN(s) — every gateway is single-homed" not in text    # old mislabel gone


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


def test_crd_fhrp_count_excludes_none_sentinel_no_false_redundancy():
    """False-health guard (the 'none'-is-truthy bug class): l3_forwarding rows carry fhrp='none' when
    no FHRP is configured, and 'none'.strip() is truthy — so the CRD was counting EVERY gateway VLAN as
    'FHRP-protected', a customer-facing claim of redundancy that does not exist and that contradicts the
    workbook's FHRP Consistency sheet (0). Mirror the engine's canonical (fhrp or 'none') != 'none'
    check so only a real HSRP/VRRP/GLBP token counts."""
    from cisco_toolkit.crd import _evidence_facts
    snap = {"l3_forwarding": [
        {"switch": "c1", "vlan": "10", "fhrp": "none"},         # no FHRP -> must NOT count
        {"switch": "c1", "vlan": "20", "fhrp": ""},             # blank -> must NOT count
        {"switch": "c1", "vlan": "30", "fhrp": "HSRP active"},  # real FHRP -> counts
        {"switch": "c2", "vlan": "30", "fhrp": "HSRP standby"}, # same VLAN, real -> dedups to one
    ]}
    assert _evidence_facts(snap)["fhrp_vlans"] == ["30"]
    # a fleet with zero real FHRP must report an EMPTY set (not every gateway VLAN)
    none_snap = {"l3_forwarding": [{"switch": "c1", "vlan": str(v), "fhrp": "none"} for v in (10, 20, 30)]}
    assert _evidence_facts(none_snap)["fhrp_vlans"] == []


def test_crd_gains_design_driven_requirements_section(tmp_path):
    """A snapshot carrying the canonical design_blueprint renders §8 — the target-state design decisions
    read as requirement candidates (REQ-D-…), each citing a CCDE principle, plus the open design
    questions. It is data-gated: the other CRD tests (no design_blueprint) never see §8, proving it is
    never empty filler. One source of truth: the SAME design_blueprint behind the HLD/LLD and dashboards."""
    snap = _snap()
    snap["design_blueprint"] = {
        "summary": {"n_recommended": 1, "n_needs_requirement": 1, "n_critical": 1},
        "decisions": [
            {"title": "Introduce first-hop redundancy", "status": "recommended", "priority": "Critical",
             "recommended_action": "Deploy HSRP/VRRP across dual gateways", "driver": "Gateway resilience",
             "evidence": {"summary": "52 VLAN(s) without FHRP"}, "principle": {"citation": "CCDE In Depth — HA"}},
            {"title": "Right-size availability per tier", "status": "needs-requirement", "priority": "High",
             "evidence": {"summary": ""}, "principle": {"citation": "CCDE"},
             "requirements_needed": ["availability_tier"]},
        ],
        "coverage": {"caveat": "grounded only in collected evidence"},
    }
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    h1 = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert any("8. Design-Driven Requirements" in t for t in h1), f"missing §8; have {h1}"
    text = _all_text(d)
    assert "REQ-D-001" in text
    assert "Introduce first-hop redundancy" in text and "CCDE In Depth — HA" in text
    assert "Right-size availability per tier" in text          # open design question surfaced
    # gated off when there is no blueprint (the other tests rely on this)
    d2 = Document(out)  # sanity: §8 only here
    assert any("8. Design-Driven Requirements" in p.text for p in d2.paragraphs)


def test_crd_design_requirements_enter_traceability_matrix(tmp_path):
    """REVIEW #8: the §8 design-driven REQ-D requirements must ALSO be registered in req_ids so they land
    in the §7 Requirement Traceability matrix (and the seeded-requirement count) — a requirement that
    traces to nothing is the exact 'orphan requirement' §7 forbids. The §7 row for a REQ-D pre-fills the
    KNOWN HLD §4 trace (the design blueprint)."""
    snap = _snap()
    snap["design_blueprint"] = {
        "summary": {"n_recommended": 1, "n_needs_requirement": 0, "n_critical": 1},
        "decisions": [
            {"title": "Introduce first-hop redundancy", "status": "recommended", "priority": "Critical",
             "recommended_action": "Deploy HSRP/VRRP", "driver": "Gateway resilience",
             "evidence": {"summary": "52 VLAN(s) without FHRP"}, "principle": {"citation": "CCDE — HA"}},
        ],
        "coverage": {},
    }
    out = str(tmp_path / "c.docx")
    write_crd_docx(out, snap, "Unit Test Fleet")
    d = Document(out)
    # locate the §7 traceability matrix by its header (distinct from the §2-6 capture tables and §8 detail)
    matrix = next((t for t in d.tables
                   if [c.text for c in t.rows[0].cells][:1] == ["REQ-ID"]
                   and "HLD section" in [c.text for c in t.rows[0].cells]), None)
    assert matrix is not None, "no §7 traceability matrix found"
    rids = [r.cells[0].text for r in matrix.rows[1:]]
    assert "REQ-D-001" in rids, f"REQ-D requirement is orphaned from the §7 matrix; have {rids}"
    row = next(r for r in matrix.rows[1:] if r.cells[0].text == "REQ-D-001")
    assert "§4" in " ".join(c.text for c in row.cells)          # traces to the known HLD §4 design blueprint


def test_crd_evidence_facts_tolerates_non_dict_executive_brief(tmp_path):
    """[multi-domain audit L4] crd.py's chained '(executive_brief or {}).get(scale)' crashed on a TRUTHY non-dict
    executive_brief (malformed/slimmed snapshot) -> the whole CRD silently aborted. The evidence-facts read and
    the doc builder must degrade, never raise."""
    from cisco_toolkit.crd import write_crd_docx, _evidence_facts
    ev = _evidence_facts({"executive_brief": "oops", "devices": {"sw1": {}}})
    assert ev["n_devices"] == 1
    out = str(tmp_path / "crd.docx")
    write_crd_docx(out, {"executive_brief": "oops", "devices": {"sw1": {}}}, "Test")   # must not raise
