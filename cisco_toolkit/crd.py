"""Customer Requirements Document (CRD) — the Plan-phase requirements-capture instrument (.docx).

NEW-V3.23.156: the missing first link of the AS document chain (CRD → HLD → LLD → MOP → NRFU → PIR).
A CRD captures the customer's business / technical / operational requirements as testable, owned,
traceable statements (REQ-IDs), gathered through a requirements workshop, key-personnel interviews
and a questionnaire — and it is a LIVING document, revisited when the detailed design surfaces new
requirements.

Evidence discipline is the whole point of this generator: requirements are the CUSTOMER'S statements,
so the toolkit cannot invent them. What it CAN do is prime the instrument with the assessment's
evidence — the current-environment summary is real, the technical-requirement sections are gated by
what was actually observed (no wireless section for a fleet with no wireless evidence), and each
seeded technical requirement is a PROPOSAL derived from observed state ("preserve the N production
VLANs") that the customer must confirm, amend, or strike. Unconfirmed requirements are UNKNOWN, not
assumed — no confidence theater.

python-docx is OPTIONAL: imported inside the function so the package imports without it; a missing
library is a warning + skip, never a crash. Every snapshot read is defensive. Deterministic; no network.
"""
import logging
from datetime import datetime

from cisco_toolkit.analyze import vlan_inventory
from cisco_toolkit.docmeta import SEV_RANK as _SEV_RANK
from cisco_toolkit.docmeta import add_acceptance, add_document_control, add_excellence_front, add_glossary, add_inputs_required, add_table, add_toc
from cisco_toolkit.docmeta import as_dict as _as_dict, as_list as _as_list   # coerce truthy non-dict/list sections
from cisco_toolkit.textutils import xml_safe, xml_safe_deep   # entry deep-sanitize of device text (audit-5)

logger = logging.getLogger(__name__)


def _evidence_facts(snap: dict) -> dict:
    """Pull the evidence the CRD primes its sections with — all defensive reads of known shapes."""
    devices = _as_dict(snap.get("devices"))
    ifaces = _as_dict(snap.get("interfaces"))
    endpoints = 0
    vrfs, n_acl_svis = set(), 0
    for host, ports in ifaces.items():
        for p, d in _as_dict(ports).items():
            d = d or {}
            if (d.get("switchport_mode") or "").lower() == "access" and (d.get("end_host_mac") or "").strip():
                endpoints += 1
            vrf = (d.get("vrf") or "").strip()
            if vrf and vrf.lower() not in ("default", "global"):
                vrfs.add(vrf)
            if (d.get("svi_ip") or "") and ((d.get("acl_in") or "").strip() or (d.get("acl_out") or "").strip()):
                n_acl_svis += 1
    # Dual-homed endpoints: the CANONICAL redundancy-bearing count is the engine's
    # endpoint_dependencies.dual_homed (host MAC observed on two switches) — the SAME source the
    # design blueprint's preserve-dual-homed-endpoints decision reads — so the CRD and the HLD agree
    # on one number instead of the CRD reporting a looser per-port dual_connection tally (A1 SSOT fix).
    dual = len(_as_list(_as_dict(snap.get("endpoint_dependencies")).get("dual_homed")))
    rn = _as_dict(snap.get("routing_neighbors"))
    protos = sorted({p.upper() for host in rn for p, nbrs in _as_dict(rn.get(host)).items() if nbrs})
    l3f = _as_list(snap.get("l3_forwarding"))
    # Real FHRP only. The parser writes the literal string "none" when no HSRP/VRRP/GLBP is present,
    # and "none".strip() is truthy — so a bare truthiness test mislabels EVERY gateway VLAN as
    # FHRP-protected (a false-redundancy claim). Mirror the engine's canonical gate
    # `(fhrp or "none") != "none"` (analyze.py) so the CRD agrees with the FHRP Consistency sheet.
    fhrp_vlans = sorted({str(r.get("vlan")) for r in l3f
                         if isinstance(r, dict) and (r.get("fhrp", "none") or "none") != "none"})
    svc = _as_dict(snap.get("service_map"))
    services = [s for s in _as_list(svc.get("services")) if isinstance(s, dict)]
    mc = _as_dict(svc.get("multicast"))
    mcast_active = any((
        int(mc.get("active_interfaces") or 0), int(mc.get("active_switch_count") or 0),
        len(mc.get("classified_groups") or []), len(mc.get("igmp_queriers") or []),
        any((v or {}).get("operational") for v in (mc.get("ptp") or {}).values()),
    ))
    lc = _as_dict(_as_dict(snap.get("lifecycle_risk")).get("summary"))
    coll = _as_dict(_as_dict(snap.get("collection_completeness")).get("summary"))
    punch = sorted([i for i in _as_list(snap.get("punchlist")) if isinstance(i, dict)],
                   key=lambda i: _SEV_RANK.get(i.get("severity"), 5))
    # isinstance-guard the canonical scale once: a TRUTHY non-dict executive_brief (malformed/slimmed snapshot)
    # slips through `or {}` and crashes .get('scale') -> the whole CRD silently aborts (audit L4).
    _eb = snap.get("executive_brief"); _eb_scale = _eb.get("scale") if isinstance(_eb, dict) else None
    _eb_scale = _eb_scale if isinstance(_eb_scale, dict) else {}
    return {
        # canonical-first (SSOT) like the n_vlans / n_endpoints reads below -- not a raw len(devices) recount,
        # which is the device-count drift seam ssot.py was created to eliminate (design.py/engagement.py do this)
        "devices": devices,
        "n_devices": _eb_scale.get("n_devices") or len(devices),
        # SSOT: the published canonical VLAN count first (the one source design/explorer/webapp/workbook
        # reconcile to), with the local vlan_inventory recount only as the pre-brief fallback (mirrors
        # n_endpoints below + design.py's A5 canonical-first read — closes the recompute drift seam).
        "n_vlans": _eb_scale.get("n_vlans") or len(vlan_inventory(snap)),
        "endpoints": endpoints, "dual": dual, "protos": protos, "fhrp_vlans": fhrp_vlans,
        "vrfs": sorted(vrfs), "n_acl_svis": n_acl_svis, "services": services,
        "mcast": mc, "mcast_active": mcast_active, "lifecycle": lc, "coll": coll, "punch": punch,
        "n_l3": len(l3f),
        # canonical endpoint scale (the published single source) with the access-port tally as fallback
        "n_endpoints": _eb_scale.get("n_endpoints") or endpoints,
    }


def write_crd_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the Customer Requirements Document (.docx) to `output_path`. Fail-soft: a missing
    python-docx is a warning + skip; any unexpected render error is logged, never raised."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        logger.warning("  CRD (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the requirements-capture deliverable).")
        return

    snap = xml_safe_deep(snap_dict if isinstance(snap_dict, dict) else {})   # one bad device byte (noncharacter/surrogate) must not abort the docx
    label = xml_safe(label) if isinstance(label, str) else (str(label) if label is not None else "")
    NAVY = RGBColor(0x1F, 0x38, 0x64)
    GREY = RGBColor(0x59, 0x59, 0x59)
    RED = RGBColor(0xB0, 0x2A, 0x1E)
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    def _label_run(p, label_text, value, color=NAVY):
        r = p.add_run(label_text); r.bold = True; r.font.color.rgb = color
        p.add_run(" " + (str(value) if value not in (None, "") else "—"))

    def table(headers, rows, widths=None):
        # Delegates to the family's single table builder (docmeta.add_table).
        return add_table(doc, headers, rows, widths, fixed=False)

    ev = _evidence_facts(snap)
    _bp = snap.get("design_blueprint")        # isinstance-guard, not `or {}`: a truthy non-dict crashes .get below
    bp = _bp if isinstance(_bp, dict) else {}   # (audit-2 L5 -- design.py guarded this; crd.py was the gap)
    req_ids: list = []   # (req_id, origin) — feeds the traceability skeleton

    def _verify_method(rid):
        # how the requirement is PROVEN — Source is implicit in the REQ-ID class (B/T/O/D), so the
        # higher-value column to add is the verification method, kept consistent with §7 (N5).
        rid = str(rid)
        if rid.startswith("REQ-D"):
            return "Design-driven NRFU (§8 + HLD §4)"
        if rid.startswith("REQ-T"):
            return "NRFU technical acceptance test"
        if rid.startswith("REQ-B"):
            return "Sponsor acceptance / sign-off"
        if rid.startswith("REQ-O"):
            return "Operational acceptance (Day-2 handover)"
        return "<NRFU test — detail in HLD/NRFU>"

    def req_table(rows):
        """A requirement-capture table; registers every REQ-ID for traceability, has each requirement
        DECLARE how it is proven (Verification), and classifies its strength with a BCP 14 / RFC 2119
        normative keyword (Class) rather than an ad-hoc H/M/L."""
        out = []
        for r in rows:
            req_ids.append(r[0])
            cls = "<MUST/SHOULD/MAY>" if str(r[3]).strip() in ("<H/M/L>", "") else r[3]
            out.append((r[0], r[1], r[2], cls, _verify_method(r[0]), r[4]))
        table(["REQ-ID", "Requirement (testable statement)", "Owner", "Class (RFC 2119)", "Verification",
               "Confirmed?"], out, widths=[0.85, 2.6, 0.75, 0.95, 1.4, 0.65])

    # ---- title page ----
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Customer Requirements Document (CRD)"); tr.bold = True
    tr.font.size = Pt(26); tr.font.color.rgb = NAVY
    sub2 = doc.add_paragraph(); sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s2 = sub2.add_run("Plan-phase requirements capture — workshop / interview / questionnaire instrument")
    s2.font.size = Pt(14); s2.font.color.rgb = GREY
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(label); sr.font.size = Pt(13); sr.font.color.rgb = GREY
    meta = doc.add_paragraph(); meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{ev['coll'].get('complete', ev['n_devices'])} of {ev['n_devices']} devices collected  ·  script {snap.get('script_version', '')}"
                 ).font.color.rgb = GREY
    status = doc.add_paragraph(); status.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st = status.add_run("DRAFT TEMPLATE — requirements are the customer's statements; confirm, amend or "
                        "strike every seeded row in the workshop.")
    st.italic = True; st.font.color.rgb = RED
    doc.add_paragraph()
    note = doc.add_paragraph()
    _label_run(note, "How to use this CRD:",
               "Run one requirements workshop, interview the key personnel, and leave the questionnaire "
               "columns with the customer. Every requirement needs a REQ-ID, an owner, and a TESTABLE "
               "statement ('the network should be fast' is not a requirement; 'voice VLANs tolerate at "
               "most one 30-minute outage window' is). Seeded technical rows are PROPOSALS derived from "
               "the observed network — they are not requirements until the customer confirms them. This "
               "is a living document: revisit it when the detailed design surfaces new requirements.", GREY)
    doc.add_page_break()

    # ---- document control (AS-style front matter) ----
    add_document_control(
        doc, document="Customer Requirements Document (CRD)", label=label,
        engine_version=str(snap.get("script_version", "")), generated_at=snap.get("generated_at"),
        collected_at=snap.get("collected_at"),
        audience="The customer's project sponsor, network owner and operations lead (requirement "
                 "owners), and the delivery engineer facilitating the requirements workshop.",
        exclude=("crd",),
        extra_assumptions=(
            "Requirements are the customer's statements. The evidence-primed rows below are proposals "
            "derived from observed state and must be confirmed or corrected by the customer; an "
            "unconfirmed requirement is recorded as UNKNOWN, never assumed.",))
    doc.add_page_break()

    # ---- table of contents (shared field-code helper, V3.23.171) ----
    add_toc(doc)


    # Deliverable Excellence (DE-01): answer-first at-a-glance register + single-source-of-truth signal.
    add_excellence_front(doc, snap_dict)
    # Deliverable Excellence (DE-01): consolidated Inputs-Required register (Law 9).
    add_inputs_required(doc, snap_dict)
    # ===== 1. Engagement context =====
    doc.add_heading("1. Engagement Context", level=1)
    doc.add_paragraph(
        "Drivers, scope and decision owners — completed with the customer in the workshop. The "
        "evidence scope below is what the assessment actually observed; the engagement scope may be "
        "wider (name the gap explicitly if so).")
    table(["Field", "Value"], [
        ("Business drivers for the change", "<why now — e.g. EoL exposure, capacity, site move>"),
        ("Engagement scope (sites / domains)", "<sites and network domains in scope>"),
        ("Evidence scope (this assessment)", f"{ev['coll'].get('complete', ev['n_devices'])} of "
                                             f"{ev['n_devices']} devices collected, {ev['n_vlans']} VLANs, "
                                             f"{ev['n_endpoints']} evidenced endpoints"),
        ("Project sponsor", "<name, role>"),
        ("Network owner (requirement owner)", "<name, role>"),
        ("Operations lead", "<name, role>"),
        ("Decision process", "<who approves the design, the windows, and the acceptance>"),
    ], widths=[2.4, 4.3])

    # ===== 2. Current environment summary (evidence) =====
    doc.add_heading("2. Current Environment Summary (evidence)", level=1)
    doc.add_paragraph(
        "What the assessment observed — the factual baseline the requirements are written against. "
        "Full evidence is in the assessment workbook; every number here reconciles to it.")
    lc, coll = ev["lifecycle"], ev["coll"]
    table(["Fact", "Observed"], [
        ("Devices", ev["n_devices"]),
        ("VLANs in use", ev["n_vlans"]),
        ("Evidenced endpoints (access ports with a host MAC)", ev["endpoints"]),
        ("Dual-homed endpoints (host MAC on two switches)", ev["dual"]),
        ("Routing protocols observed", ", ".join(ev["protos"]) or "none (pure L2 fleet)"),
        ("Gateway SVIs / FHRP-protected VLANs", f"{ev['n_l3']} / {len(ev['fhrp_vlans'])}"),
        ("Non-default VRFs", ", ".join(ev["vrfs"]) or "none"),
        ("Hardware past last-day-of-support (LDoS)", lc.get("n_past_ldos", "—")),
        ("Collection completeness", f"{coll.get('complete', '—')} complete / "
                                    f"{coll.get('partial', '—')} partial / "
                                    f"{coll.get('not_collected', '—')} not collected"),
    ], widths=[3.4, 3.3])
    if ev["punch"]:
        doc.add_paragraph("Known issues the requirements must take a position on (top of the "
                          "assessment punch-list):")
        table(["Severity", "Category", "Issue"],
              [(i.get("severity"), i.get("category") or "—", i.get("title") or "—")
               for i in ev["punch"][:8]], widths=[0.9, 1.4, 4.3])

    # requirements-classification legend (BCP 14 / RFC 2119 + RFC 8174) — establishes the normative-keyword
    # convention before the first requirement table (N1/N8)
    doc.add_paragraph(
        "Requirements classification (BCP 14). Each requirement's strength is stated with an RFC 2119 / "
        "RFC 8174 normative keyword in the Class column — MUST / MUST NOT (an absolute requirement), "
        "SHOULD / SHOULD NOT (recommended; deviate only with a documented reason), MAY / OPTIONAL (truly "
        "discretionary) — and the keyword carries this meaning only when written in all capitals (RFC 8174). "
        "Confirm the class of each row in the workshop.")

    # ===== 3. Business requirements =====
    doc.add_heading("3. Business Requirements", level=1)
    doc.add_paragraph(
        "Success criteria and constraints, as testable statements with owners. These are pure "
        "customer inputs — the rows are prompts, not proposals.")
    req_table([
        ("REQ-B-001", "Outage tolerance per service class: <e.g. voice VLANs tolerate at most one "
                      "30-minute window; CCTV tolerates none>", "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-B-002", "Timeline and window constraints: <deadline, change-freeze periods, allowed "
                      "maintenance windows>", "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-B-003", "Compliance / policy constraints: <regulatory, security policy, vendor-support "
                      "requirements>", "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-B-004", "Definition of success: <the measurable end-state the sponsor will accept>",
         "<owner>", "<H/M/L>", "<YES/AMEND>"),
    ])

    # ===== 4. Technical requirements (per observed discipline) =====
    doc.add_heading("4. Technical Requirements", level=1)
    doc.add_paragraph(
        "One subsection per discipline the evidence shows in use — a discipline with no observed "
        "footprint gets no section (add one in the workshop if the TARGET state introduces it). "
        "Seeded rows are evidence-derived proposals.")

    doc.add_heading("4.1 Campus LAN / Layer 2", level=2)
    req_table([
        ("REQ-T-LAN-001", f"Preserve the {ev['n_vlans']} production VLAN IDs and names through the "
                          "migration (observed as-built).", "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-T-LAN-002", f"Maintain dual-homing for the {ev['dual']} dual-homed endpoint(s) (host "
                          "MAC present on two switches); no dual-homed endpoint may lose both legs "
                          "together.", "<owner>", "<H/M/L>", "<YES/AMEND>"),
    ])

    if ev["protos"] or ev["n_l3"]:
        doc.add_heading("4.2 Layer 3 & routing", level=2)
        req_table([
            ("REQ-T-L3-001",
             (f"Preserve gateway redundancy on the {len(ev['fhrp_vlans'])} FHRP-protected VLAN(s); "
              "single-gateway VLANs are remediated, not carried forward." if ev["fhrp_vlans"]
              else f"No first-hop redundancy (HSRP/VRRP/GLBP) was observed on any of the {ev['n_l3']} "
                   "gateway SVI instance(s) — every gateway is single-homed; evaluate introducing FHRP "
                   "so VLANs are not carried forward without gateway redundancy."),
             "<owner>", "<H/M/L>", "<YES/AMEND>"),
            ("REQ-T-L3-002", "Maintain the observed routing adjacencies ("
                             + (", ".join(ev["protos"]) or "static/connected only")
                             + ") and their policy through the migration.",
             "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ])

    if ev["mcast_active"]:
        doc.add_heading("4.3 Multicast & timing", level=2)
        groups = ev["mcast"].get("classified_groups") or []
        gname = (groups[0].get("name") or groups[0].get("group")) if groups else "the observed groups"
        req_table([
            ("REQ-T-MC-001", f"Preserve multicast delivery for the {len(groups)} classified group(s) "
                             f"(e.g. {gname}) including snooping/querier behaviour per VLAN.",
             "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ])

    if ev["vrfs"] or ev["n_acl_svis"]:
        doc.add_heading("4.4 Segmentation & security", level=2)
        req_table([
            ("REQ-T-SEC-001", "Preserve the observed segmentation: VRF(s) "
                              + (", ".join(ev["vrfs"]) or "—")
                              + f"; {ev['n_acl_svis']} gateway SVI(s) carry ACLs that must be "
                              "carried forward or consciously redesigned.",
             "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ])

    if ev["services"]:
        doc.add_heading("4.5 Services & applications", level=2)
        cats = sorted({(s.get("category") or "").strip() for s in ev["services"] if s.get("category")})
        req_table([
            ("REQ-T-SVC-001", "End-to-end continuity for the detected service categories ("
                              + (", ".join(cats[:6]) or "see service map")
                              + ") — each gets an NRFU end-to-end test.",
             "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ])

    # ===== 5. Operational requirements =====
    doc.add_heading("5. Operational Requirements", level=1)
    req_table([
        ("REQ-O-001", "Management & monitoring continuity: <SNMP/syslog/flow reach the same "
                      "collectors throughout; no monitoring blackout longer than X>",
         "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-O-002", "Change windows & freeze calendar: <when work may happen>",
         "<owner>", "<H/M/L>", "<YES/AMEND>"),
        ("REQ-O-003", "Support model & knowledge transfer: <who operates the target network; what "
                      "handover/training is required before acceptance>",
         "<owner>", "<H/M/L>", "<YES/AMEND>"),
    ])

    # ===== 6. Future plans & growth =====
    doc.add_heading("6. Future Plans & Growth", level=1)
    # evidence-anchored scale baseline — growth targets are measured against observed reality (N3)
    table(["Scale dimension", "Today (observed)", "Target horizon", "Headroom / note"], [
        ("Switches in scope", ev["n_devices"], "<confirm>",
         "replacement / refresh tracked in the lifecycle plan"),
        ("Production VLANs", ev["n_vlans"], "<confirm>", "new segments add to the L2/L3 + addressing plan"),
        ("Evidenced endpoints", ev["n_endpoints"], "<confirm>",
         "PoE / port / multicast capacity must absorb the growth"),
    ], widths=[1.7, 1.3, 1.2, 2.5])
    doc.add_paragraph(
        "Planned initiatives the design must not block — capacity horizon, new sites or services, "
        "technology directions. Captured in the workshop; each becomes a requirement row or an "
        "explicit exclusion.")
    table(["Horizon", "Plan", "Design implication"],
          [("<12 months>", "<e.g. new building / IP camera expansion>", "<ports, PoE, multicast>"),
           ("<36 months>", "<e.g. platform refresh, segmentation program>", "<to be assessed>")],
          widths=[1.1, 3.0, 2.6])

    # Design-driven requirements (REQ-D) are derived from the canonical blueprint; register their IDs in
    # the traceability set BEFORE §7 renders so they are NOT orphaned from the matrix (a requirement that
    # traces to nothing is the exact review defect §7 forbids). Their detail table is §8.
    bp_decisions = [d for d in (bp.get("decisions") or []) if isinstance(d, dict)]
    rec = [d for d in bp_decisions if d.get("status") == "recommended"]
    req_d = [(f"REQ-D-{i:03d}", d) for i, d in enumerate(rec, 1)]
    req_ids.extend(rid for rid, _ in req_d)

    # ===== 7. Requirement traceability =====
    doc.add_heading("7. Requirement Traceability", level=1)
    doc.add_paragraph(
        "Every requirement lands in design content and an acceptance test — an orphan requirement "
        "(traced to nothing) or an orphan design choice (tracing to no requirement) is a review "
        "defect. Complete as the HLD/LLD/NRFU are produced.")

    def _trace_row(rid):
        # REQ-D requirements trace to the HLD §4 design blueprint (known) + the design-driven NRFU; the
        # rest stay placeholders to complete as the HLD/LLD/NRFU are produced.
        if rid.startswith("REQ-D"):
            return (rid, "HLD §4 (design blueprint)", "<LLD §>", "design-driven NRFU")
        return (rid, "<HLD §>", "<LLD §>", "<NRFU-…>")
    table(["REQ-ID", "HLD section", "LLD section", "NRFU test ID"],
          [_trace_row(rid) for rid in req_ids], widths=[1.1, 1.8, 1.8, 1.8])

    # ===== 8. Design-driven requirements (target-state blueprint) — evidence-gated =====
    if bp_decisions:
        doc.add_heading("8. Design-Driven Requirements (Target-State Blueprint)", level=1)
        doc.add_paragraph(
            "Requirements the assessment itself derives: the CCDE-grounded target-state design blueprint "
            "(the SAME design_blueprint behind the HLD/LLD §4 and the explorer Design mode), read as "
            "requirement candidates. Each is gated on observed evidence and cites a network-design "
            "principle — confirm, amend or strike it like any workshop requirement; each traces forward to "
            "an HLD §4 design decision (and appears in the §7 traceability matrix).")
        if rec:
            table(["REQ-D", "Design requirement (recommended target pattern)", "Driver / evidence",
                   "CCDE basis", "Confirmed?"],
                  [(rid,
                    f"{d.get('title')}: {d.get('recommended_action') or ''}".strip().rstrip(":"),
                    (d.get("evidence") or {}).get("summary") or d.get("driver") or "—",
                    (d.get("principle") or {}).get("citation") or "—", "<YES/AMEND>")
                   for rid, d in req_d],
                  widths=[0.8, 2.7, 2.0, 1.4, 0.8])
        needs = [d for d in bp_decisions if d.get("status") == "needs-requirement"]
        if needs:
            doc.add_paragraph(
                "Open design questions — these decisions depend on requirements the assessment cannot "
                "observe; answer them in the workshop and the target design right-sizes (the engine never "
                "assumes an answer):")
            for d in needs:
                _label_run(doc.add_paragraph(), f"{d.get('title')} —",
                           ", ".join(d.get("requirements_needed") or []) or "requirement to confirm", GREY)
        cov = bp.get("coverage") or {}
        if cov.get("caveat"):
            _label_run(doc.add_paragraph(), "Coverage:", cov.get("caveat"), GREY)

    # ---- closing acceptance gate ----
    # Deliverable Excellence (DE-01): shared glossary before the sign-off gate.
    add_glossary(doc)

    add_acceptance(
        doc, scope_note="Acceptance of this CRD baselines the requirements for the high-level design; "
                        "changes after acceptance go through change control as requirement amendments.")

    n_req = len(req_ids)
    doc.save(output_path)
    logger.info(f"[Phase 35] CRD (DOCX) written: {output_path} ({n_req} requirement rows seeded)")
