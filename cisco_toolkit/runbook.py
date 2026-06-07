"""Assessment & migration RUNBOOK (DOCX) — the narrative sign-off twin of the workbook.

NEW-V3.23.93: the cisco-network-assessment doctrine mandates TWO complementary deliverables for
an engagement — an operational workbook (XLSX, which this toolkit already emits) AND a formal
assessment & migration runbook (DOCX). This module adds the second. It is PURE PRESENTATION of the
already-computed snapshot (one source of truth: it reads the same snap_dict the workbook + explorer
consume, so every number agrees) and follows the skill's report-standards 12-section structure with
evidence-disciplined finding blocks (Observed / Interpretation / Impact / Confidence / Unknowns /
Next validation).

Evidence discipline (false-health doctrine) is baked in, because this dataset is config- and
CDP/LLDP-derived, NOT live forwarding telemetry:
  * gateway PLACEMENT (an SVI is configured) is Confirmed; the active forwarding owner over time is
    Unknown -- "gateway active is not service proof".
  * inter-switch links are Inferred-high (a neighbour was advertised), never Confirmed; off-scan
    links are Unknown -- "no inferred link is presented as confirmed".
  * endpoint presence is Confirmed at snapshot time only; MAC aging means absence is Unknown.

python-docx is an OPTIONAL dependency: imported inside the function so the package imports fine
without it, and a missing library is a warning + skip (the run's workbook/explorer/JSON already
saved), exactly like the HTML explorer's template-missing path.
"""
import logging
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

# Confidence vocabulary (governance/terminology-and-confidence-glossary.md).
_CONF_CONFIRMED = "Confirmed"
_CONF_HIGH = "Inferred-high"
_CONF_MED = "Inferred-medium"
_CONF_UNKNOWN = "Unknown"

_SEV_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _endpoint_census(snap: dict):
    """Derive endpoint counts the SAME way the workbook does (access ports carrying a host MAC) so the
    runbook reconciles to it. Returns (total, per_vlan Counter, per_switch Counter). Trunk MAC-table
    entries are excluded by construction (only access ports are counted). Pure read of the snapshot."""
    import re
    per_vlan: Counter = Counter()
    per_switch: Counter = Counter()
    total = 0
    for host, ports in (snap.get("interfaces") or {}).items():
        for d in (ports or {}).values():
            if (d.get("switchport_mode") or "") != "Access":
                continue
            macs = [m for m in re.split(r"[,\s]+", d.get("end_host_mac") or "") if m]
            if not macs:
                continue
            n = len(macs)
            total += n
            per_switch[host] += n
            vlan = d.get("vlan") or ""
            if vlan.isdigit():
                per_vlan[int(vlan)] += n
    return total, per_vlan, per_switch


def _gateways(snap: dict):
    """Per-VLAN gateway register from l3_forwarding (SVIs). Returns list of dicts with the
    false-health separation the doctrine requires: placement (Confirmed) vs active-owner /
    forwarding (Unknown). FHRP role from config is Inferred-high."""
    rows = []
    for r in (snap.get("l3_forwarding") or []):
        rows.append({
            "vlan": r.get("vlan", ""), "svi_ip": r.get("svi_ip", ""), "owner": r.get("switch", ""),
            "fhrp": r.get("fhrp", ""), "role": r.get("role", ""), "risk": r.get("risk", ""),
        })
    return rows


def write_runbook_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the assessment & migration runbook (.docx) from the live snapshot. Safe/fail-soft:
    a missing python-docx is a warning + skip; never crashes a run whose other outputs are saved."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.section import WD_ORIENT
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.shared import Pt, RGBColor, Inches
    except ImportError:
        logger.warning("  Runbook (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the narrative runbook deliverable).")
        return

    NAVY = RGBColor(0x1F, 0x38, 0x64)
    GREY = RGBColor(0x59, 0x59, 0x59)
    doc = Document()

    # base style
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    def _label_run(p, label_text, value, color=NAVY):
        r = p.add_run(label_text)
        r.bold = True
        r.font.color.rgb = color
        p.add_run(" " + (value if value else "—"))

    def finding_block(title, *, severity, scope, observed, interpretation, impact,
                      confidence, unknowns, next_validation, remediation=""):
        """One evidence-disciplined finding (report-standards.md finding format). Each line is
        explicitly typed (Observed / Interpretation / Impact / Confidence / Unknowns / Next), and
        Remediation is omitted when not evidence-justified."""
        doc.add_heading(title, level=3)
        meta = doc.add_paragraph()
        _label_run(meta, "Severity:", severity); meta.add_run("    ")
        _label_run(meta, "Scope:", scope)
        for lbl, val in (("Observed Evidence:", observed), ("Interpretation:", interpretation),
                         ("Impact / Blast Radius:", impact), ("Confidence:", confidence),
                         ("Unknowns:", unknowns), ("Next Validation:", next_validation)):
            p = doc.add_paragraph(); _label_run(p, lbl, val)
        if remediation:
            p = doc.add_paragraph(); _label_run(p, "Remediation:", remediation)

    def table(headers, rows, widths=None):
        t = doc.add_table(rows=1, cols=len(headers)); t.style = "Light Grid Accent 1"
        for i, hd in enumerate(headers):
            c = t.rows[0].cells[i]; c.text = str(hd)
            for para in c.paragraphs:
                for run in para.runs:
                    run.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = "" if v is None else str(v)
        if widths:
            for i, w in enumerate(widths):
                for row in t.rows:
                    row.cells[i].width = Inches(w)
        doc.add_paragraph()
        return t

    # ---- snapshot-derived headline numbers (reconciled; all sections cite these) ----
    devices = snap_dict.get("devices") or {}
    hs = snap_dict.get("health_scores") or []
    bands = Counter(r.get("band", "") for r in hs)
    move_groups = snap_dict.get("move_groups") or []
    mr = snap_dict.get("migration_readiness") or []
    ws = snap_dict.get("wave_sequencing") or []
    cross_layer = snap_dict.get("cross_layer") or []
    punchlist = snap_dict.get("punchlist") or []
    failure_impact = snap_dict.get("failure_impact") or []
    link_centrality = snap_dict.get("link_centrality") or []
    gw = _gateways(snap_dict)
    ep_total, ep_per_vlan, ep_per_switch = _endpoint_census(snap_dict)
    n_dev = len(devices)
    n_links = len([r for r in link_centrality])  # link records == inter-switch links
    bridges = [r for r in link_centrality if r.get("is_bridge")]
    crit_cl = [f for f in cross_layer if f.get("severity") == "Critical"]
    high_cl = [f for f in cross_layer if f.get("severity") == "High"]

    # ---- title page ----
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Network Assessment & Migration Runbook"); tr.bold = True
    tr.font.size = Pt(26); tr.font.color.rgb = NAVY
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(label); sr.font.size = Pt(13); sr.font.color.rgb = GREY
    meta = doc.add_paragraph(); meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{n_dev} devices in scope  ·  script {snap_dict.get('script_version', '')}").font.color.rgb = GREY
    status = doc.add_paragraph(); status.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st = status.add_run("DRAFT for war-room review — evidence-led; numbers reconcile to the workbook.")
    st.italic = True; st.font.color.rgb = GREY
    doc.add_paragraph()
    note = doc.add_paragraph()
    _label_run(note, "Evidence posture:",
               "This runbook is derived from collected configuration and CDP/LLDP neighbour data, not "
               "from live forwarding telemetry. Gateway PLACEMENT is Confirmed where an SVI is "
               "configured; the active forwarding owner over time is Unknown. Inter-switch links are "
               "Inferred-high (a neighbour was advertised), never Confirmed; off-scan links are Unknown. "
               "Endpoint presence is Confirmed at snapshot time only. Configured is not healthy; up is "
               "not healthy; gateway-active is not service proof.", GREY)
    doc.add_page_break()

    # ---- table of contents (auto-updates in Word) ----
    doc.add_heading("Contents", level=1)
    toc_p = doc.add_paragraph()
    run = toc_p.add_run()
    fld_begin = OxmlElement("w:fldChar"); fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = r'TOC \o "1-2" \h \z \u'
    fld_sep = OxmlElement("w:fldChar"); fld_sep.set(qn("w:fldCharType"), "separate")
    fld_txt = OxmlElement("w:t"); fld_txt.text = "Right-click → Update Field to build the table of contents."
    fld_end = OxmlElement("w:fldChar"); fld_end.set(qn("w:fldCharType"), "end")
    for el in (fld_begin, instr, fld_sep, fld_txt, fld_end):
        run._r.append(el)
    doc.add_page_break()

    # ===== 1. Assessment Header & Executive Summary =====
    doc.add_heading("1. Assessment Header & Executive Summary", level=1)
    table(["Metric", "Value"], [
        ("Devices in scope", n_dev),
        ("Inter-switch links (CDP/LLDP-derived; Inferred-high)", n_links),
        ("Bridge links (single points of fabric partition)", len(bridges)),
        ("Endpoints (access-port host MACs at snapshot)", ep_total),
        ("VLANs with endpoints", len(ep_per_vlan)),
        ("Gateways (SVIs) observed", len(gw)),
        ("Migration move groups", len(move_groups)),
        ("Health bands (Critical/Poor/Fair/Good/Excellent)",
         f"{bands.get('Critical',0)} / {bands.get('Poor',0)} / {bands.get('Fair',0)} / "
         f"{bands.get('Good',0)} / {bands.get('Excellent',0)}"),
        ("Cross-layer findings (Critical / High)", f"{len(crit_cl)} / {len(high_cl)}"),
        ("Punch-list items", len(punchlist)),
    ], widths=[4.8, 2.0])
    p = doc.add_paragraph()
    _label_run(p, "Top gating decisions:",
               f"{len(crit_cl)} Critical cross-layer single-point(s) of failure and {len(bridges)} "
               f"bridge link(s) must be resolved or risk-accepted before cutover. "
               f"{sum(1 for r in mr if r.get('readiness') == 'NOT READY')} of {len(mr)} move group(s) "
               f"are NOT READY on the pre-migration checklist.")

    # ===== 2. Scope & Data Completeness =====
    doc.add_heading("2. Scope & Data Completeness", level=1)
    doc.add_paragraph(
        f"In scope: the {n_dev} Cisco switches present in the collected dataset and their "
        "configuration, interface, CDP/LLDP, STP, FHRP/SVI, and routing-adjacency state.")
    doc.add_paragraph("Dataset limits (these bound every claim below):", style="List Bullet")
    for t in (
        "No live forwarding/ARP-aging telemetry — endpoint presence is a snapshot, not a census over time.",
        "Topology is CDP/LLDP-derived: links to off-scan or non-advertising devices are Unknown.",
        "Multicast / PTP / QoS baselines are not collected — broadcast-media timing health is Unknown.",
        "Active FHRP ownership and failover behaviour are inferred from config, not observed over a failover.",
    ):
        doc.add_paragraph(t, style="List Bullet 2")

    # ===== 3. Scenario Classification =====
    doc.add_heading("3. Scenario Classification", level=1)
    doc.add_paragraph(
        "Primary mode: Migration planning (brownfield). Secondary: steady-state health assessment. "
        "The plan rests on an endpoint-move architecture: access-layer switches and their endpoints "
        "move in dependency-scoped groups while L3 gateways remain on the legacy core. That premise is "
        "validated per VLAN in §6; VLANs whose gateway cannot be evidenced are gated, not assumed.")

    # ===== 4. Platform Intelligence =====
    doc.add_heading("4. Platform Intelligence", level=1)
    model_mix = Counter(d.get("model", "") or "unknown" for d in devices.values())
    doc.add_paragraph("Hardware/software mix (device-reported; cross-check labels against behaviour "
                      "before relying on them):")
    table(["Model / PID", "Count"],
          sorted(([m or "unknown", c] for m, c in model_mix.items()), key=lambda r: -r[1])[:15],
          widths=[4.5, 1.5])
    # EoL / environmental flags surfaced from capacity + device fields
    env_flags = [(d.get("hostname", h), d.get("ps_status", ""), d.get("fan_status", ""),
                  d.get("temperature_status", ""))
                 for h, d in devices.items()
                 if any((d.get(k) or "").lower() not in ("", "ok", "normal", "good")
                        for k in ("ps_status", "fan_status", "temperature_status"))]
    if env_flags:
        doc.add_paragraph("Environmental exceptions (PSU/fan/temperature not nominal):")
        table(["Device", "PSU", "Fan", "Temp"], env_flags[:20], widths=[3.5, 1.3, 1.3, 1.3])

    # ===== 5. Topology & Current State =====
    doc.add_heading("5. Topology & Current State", level=1)
    p = doc.add_paragraph()
    _label_run(p, "Confidence:",
               f"{_CONF_HIGH}. {n_links} inter-switch links reconstructed from CDP/LLDP. "
               f"{len(bridges)} are bridges (their loss partitions the fabric). Off-scan links are "
               f"{_CONF_UNKNOWN}.")
    if bridges:
        doc.add_paragraph("Chokepoint links (ranked by structural blast radius; live fault state is "
                          "Unknown until validated):")
        table(["Rank", "Link", "Betweenness", "Switch-pairs cut if it fails"],
              [[b.get("rank"), f"{b.get('a_host')} {b.get('a_port')} ↔ {b.get('b_host')} {b.get('b_port')}",
                b.get("betweenness"), b.get("pairs_cut")] for b in
               sorted(bridges, key=lambda r: -(r.get("pairs_cut") or 0))[:12]],
              widths=[0.6, 4.4, 1.2, 1.6])

    # ===== 6. L1-L4 Findings (the gateway premise + evidence finding blocks) =====
    doc.add_heading("6. L1–L4 Findings", level=1)
    doc.add_heading("6.1 Gateway placement (the migration premise)", level=2)
    doc.add_paragraph(
        "Per-VLAN gateway register. Placement (an SVI is configured on the named switch) is "
        f"{_CONF_CONFIRMED}; the active forwarding owner and failover behaviour are {_CONF_UNKNOWN} "
        "without a live ARP/HSRP-state capture. VLANs flagged below carry an L3 risk.")
    gw_rows = [[g["vlan"], g["svi_ip"] or "—", g["owner"], g["fhrp"] or "none",
                (g["risk"] or "ok")] for g in
               sorted(gw, key=lambda g: (0 if g["risk"] and g["risk"] != "ok" else 1, str(g["vlan"])))[:25]]
    if gw_rows:
        table(["VLAN", "SVI IP (Confirmed)", "Owner (Confirmed)", "FHRP (Inferred-high)", "L3 risk"],
              gw_rows, widths=[0.8, 1.8, 2.6, 1.5, 1.5])
    n_no_fhrp = sum(1 for g in gw if not (g["fhrp"] or "").strip())
    doc.add_paragraph(
        f"{n_no_fhrp} of {len(gw)} gateways have no FHRP peer in scope — single-gateway exposure. "
        "Any VLAN whose gateway is off-scan is gated as Unknown in §12.")

    doc.add_heading("6.2 Material cross-layer findings", level=2)
    for f in sorted(cross_layer, key=lambda f: _SEV_ORDER.get(f.get("severity"), 9))[:8]:
        hosts = ", ".join(f.get("hosts") or []) or "—"
        finding_block(
            f.get("title", f.get("id", "Cross-layer finding")),
            severity=f.get("severity", "Medium"),
            scope=f"{hosts}  (layers {f.get('layers', '?')})",
            observed=f.get("detail", "—"),
            interpretation=f"A single condition is implicated across {f.get('layers', 'multiple')} — "
                           "structural exposure, independent of whether a fault is active now.",
            impact="Loss of the named element removes the only path/gateway for the dependent "
                   "population (see Risk Register §10 for the scoped count).",
            confidence=f"{_CONF_HIGH} for the structural exposure (config + topology agree); "
                       f"{_CONF_UNKNOWN} for live fault state.",
            unknowns="Whether redundancy exists off-scan; whether the fault is active at cutover time.",
            next_validation="Confirm the second path/gateway on the live devices before the wave that "
                            "moves this element.",
            remediation=f.get("recommendation", ""))

    drift = snap_dict.get("operational_drift") or []
    if drift:
        doc.add_heading("6.3 False-health / operational drift", level=2)
        doc.add_paragraph(
            "Conditions a green control plane hides — surfaced because configured/up is not healthy. "
            "Each is a snapshot-evidenced exposure; whether it is biting right now is Unknown until "
            "validated live.")
        table(["Severity", "Finding", "Devices", "Why it matters / next step"],
              [[d.get("severity", ""), d.get("title", ""),
                str(len(d.get("devices") or [])),
                (d.get("detail", "") + " " + (d.get("remediation", "") or "")).strip()[:160]]
               for d in sorted(drift, key=lambda d: _SEV_ORDER.get(d.get("severity"), 9))],
              widths=[0.9, 2.8, 0.9, 4.0])

    # ===== 7. Endpoint & VLAN Census =====
    doc.add_heading("7. Endpoint & VLAN Census", level=1)
    p = doc.add_paragraph()
    _label_run(p, "Counting rule:",
               "endpoints = access ports carrying at least one learned host MAC. Trunk/uplink MAC-table "
               f"entries are excluded. Presence is {_CONF_CONFIRMED} at snapshot time; absence is "
               f"{_CONF_UNKNOWN} (MAC aging).")
    doc.add_paragraph(f"Total endpoints: {ep_total} across {len(ep_per_vlan)} VLAN(s) and "
                      f"{len(ep_per_switch)} switch(es).")
    doc.add_paragraph("Top VLANs by endpoint count:")
    table(["VLAN", "Endpoints"], [[v, c] for v, c in ep_per_vlan.most_common(12)], widths=[1.5, 1.5])
    doc.add_paragraph("Top switches by endpoint count:")
    table(["Switch", "Endpoints"], [[s, c] for s, c in ep_per_switch.most_common(12)], widths=[4.5, 1.5])

    # vendor + endpoint-type grouping with confidence (a skill first-class output). NEW-V3.23.95.
    ident = snap_dict.get("endpoint_identity") or []
    if ident:
        doc.add_heading("7.1 Endpoint identity (vendor & type)", level=2)
        p = doc.add_paragraph()
        _label_run(p, "Method:",
                   "vendor is the MAC-OUI registered owner (a fact); the class is inferred from vendor + "
                   f"description + CDP platform and is labelled {_CONF_HIGH}/{_CONF_MED}/{_CONF_UNKNOWN} "
                   "per endpoint (no role is claimed as proven from passive data).")
        cls_c = Counter(r.get("endpoint_class", "Unknown") for r in ident)
        ven_c = Counter(r.get("vendor") for r in ident if r.get("vendor"))
        resolved = sum(1 for r in ident if r.get("vendor"))
        doc.add_paragraph(f"{len(ident)} endpoints; vendor resolved for {resolved} "
                          f"({round(100 * resolved / max(len(ident), 1))}%).")
        doc.add_paragraph("By inferred class:")
        table(["Class", "Endpoints"], [[k, v] for k, v in cls_c.most_common()], widths=[3.0, 1.5])
        doc.add_paragraph("Top vendors:")
        table(["Vendor", "Endpoints"], [[k, v] for k, v in ven_c.most_common(12)], widths=[4.5, 1.5])

    # ===== 8. Shared Infrastructure & Consolidation =====
    doc.add_heading("8. Shared Infrastructure & Consolidation", level=1)
    cap = snap_dict.get("capacity") or []
    low_util = sorted([c for c in cap if isinstance(c.get("port_util"), (int, float))],
                      key=lambda c: c.get("port_util") or 0)[:10]
    doc.add_paragraph("Spare port capacity (consolidation candidates — lowest port utilisation):")
    table(["Switch", "Model", "Active/Total", "Port util %"],
          [[c.get("hostname"), c.get("model"), f"{c.get('active_ports')}/{c.get('total_ports')}",
            c.get("port_util")] for c in low_util], widths=[3.2, 2.2, 1.2, 1.2])
    dep = snap_dict.get("endpoint_dependencies") or {}
    clusters = dep.get("clusters") or []
    dual = dep.get("dual_homed") or []
    affinity = dep.get("affinity") or []
    if clusters or dual or affinity:
        doc.add_heading("8.1 Endpoint clusters & dependencies", level=2)
        doc.add_paragraph(
            "Cohesive units inferred from the endpoint identity model — a distributed system is a "
            f"(vendor, class) seen across many switches. Confidence travels with the identities "
            f"({_CONF_HIGH}/{_CONF_MED}); live cluster role (active/standby) stays {_CONF_UNKNOWN} "
            "until validated.")
        if clusters:
            doc.add_paragraph("Largest cohesive units (clusters):")
            table(["Class", "Vendor", "Endpoints", "Switches", "VLANs", "Spans move-groups?"],
                  [[c.get("endpoint_class"), c.get("vendor"), c.get("count"), c.get("switches"),
                    c.get("vlans"), "YES" if c.get("spans_groups") else "no"] for c in clusters[:12]],
                  widths=[1.7, 2.4, 1.0, 0.9, 0.8, 1.4])
        if dual:
            split = sum(1 for d in dual if d.get("split_across_groups"))
            doc.add_paragraph(
                f"Dual-homed / NIC-team endpoints: {len(dual)} (same MAC on >=2 switches) — sequence each "
                f"make-before-break so the peer leg stays up. {split} are split across move-groups "
                "(coordinate those waves explicitly).")
        if affinity:
            doc.add_paragraph("Per-VLAN application tiers (dominant endpoint class in each VLAN):")
            table(["VLAN", "Dominant class", "Endpoints", "Class mix"],
                  [[a.get("vlan"), a.get("dominant"), a.get("total"),
                    ", ".join(f"{k} ({v})" for k, v in (a.get("classes") or {}).items())]
                   for a in affinity[:12]], widths=[0.9, 2.0, 1.0, 3.5])

    # ===== 9. Migration Dependency & Move Groups =====
    doc.add_heading("9. Migration Dependency & Move Groups", level=1)
    doc.add_paragraph(
        "Unit of movement: a shared-VLAN dependency group (switches coupled by a common access VLAN). "
        "Dual-homed switches migrate make-before-break; single-homed switches are hard cutovers "
        "(maintenance window; their endpoints take an outage). Numbers reconcile to the workbook's "
        "Move Groups and Migration Readiness sheets.")
    ws_by_group = {w.get("group"): w for w in ws}
    mg_rows = []
    for r in mr:
        g = r.get("group", "")
        w = ws_by_group.get(g, {})
        mg_rows.append([g, len(r.get("switches") or []), r.get("endpoints", 0),
                        r.get("readiness", ""), len(w.get("make_before_break") or []),
                        len(w.get("hard_cutover") or []), w.get("hard_cutover_endpoints", 0)])
    if mg_rows:
        table(["Group", "Switches", "Endpoints", "Readiness", "Make-before-break",
               "Hard cutover", "At-risk endpoints"], mg_rows, widths=[1.4, 1.0, 1.0, 1.3, 1.4, 1.1, 1.2])

    # ===== 10. Risk Register (behaviour-based blast radius) =====
    doc.add_heading("10. Risk Register", level=1)
    doc.add_paragraph(
        "Per-switch migration blast radius from the removal simulation, ranked by stranded endpoints. "
        "Structural exposure (who depends on the element) is separated from live fault state, which "
        f"is {_CONF_UNKNOWN} until validated.")
    fi_rows = [[r.get("host"), r.get("severity"), r.get("vlans_impacted"), r.get("stranded"),
                r.get("hard"), r.get("backup"), r.get("fhrp")]
               for r in sorted(failure_impact,
                               key=lambda r: (_SEV_ORDER.get(r.get("severity"), 9),
                                              -(r.get("stranded") or 0)))[:15]]
    if fi_rows:
        table(["Switch (remove/migrate)", "Severity", "VLANs", "Stranded eps", "Hard",
               "Backup-covered", "FHRP-covered"], fi_rows, widths=[3.0, 1.0, 0.8, 1.1, 0.8, 1.2, 1.2])

    # ===== 11. Validation & Rollback Logic =====
    doc.add_heading("11. Validation & Rollback Logic", level=1)
    doc.add_paragraph("Per-phase, governed by the false-health rule (a green control plane is not "
                      "service proof — validate forwarding for a real endpoint).")
    table(["Stage", "Pre-check", "Validation (forwarding-proof)", "Rollback trigger", "Rollback action"],
          [["Per group, before move",
            "Confirm second uplink/path live; confirm gateway reachable from a test endpoint",
            "Ping/trace from a moved endpoint to its gateway AND to one cross-VLAN service",
            "Any moved endpoint loses gateway reachability, or a bridge link drops",
            "Re-home the group's uplinks to the legacy path; re-validate"]],
          widths=[1.6, 2.4, 2.4, 2.0, 2.0])

    # per-class service-validation derived from the endpoint classes actually present (NEW-V3.23.96).
    psv = (snap_dict.get("endpoint_dependencies") or {}).get("per_switch_validation") or {}
    if psv:
        present = sorted({line for lines in psv.values() for line in lines})
        doc.add_heading("11.1 Service validation by endpoint class (what to prove per switch)", level=2)
        doc.add_paragraph(
            f"The workbook / snapshot carry a per-switch checklist ({len(psv)} switches). The distinct "
            "service-validation items across the fleet — attach the ones matching a switch's hosted "
            "classes to its move:")
        for line in present:
            doc.add_paragraph(line, style="List Bullet")

    # ===== 12. War-Room Decision Logic & Open Unknowns =====
    doc.add_heading("12. War-Room Decision Logic & Open Unknowns", level=1)
    doc.add_paragraph("GO / HOLD / ROLLBACK matrix:")
    table(["State after a move", "Decision"],
          [["Endpoint forwarding to gateway + cross-VLAN service proven", "GO (proceed to next group)"],
           ["Control plane up but forwarding not yet proven", "HOLD (validate before proceeding)"],
           ["Moved endpoint stranded, or a bridge link / sole gateway dropped", "ROLLBACK"]],
          widths=[5.0, 2.0])
    doc.add_heading("Open unknowns (these gate the phases above — no confidence theater)", level=2)
    unknowns = [
        ("Active forwarding owner per FHRP VLAN", _CONF_UNKNOWN,
         "Gates any VLAN relying on a specific gateway staying active during cutover.",
         "Capture 'show standby brief' / ARP for the gateway VIP at cutover time."),
        ("Off-scan links and gateways", _CONF_UNKNOWN,
         "A VLAN gatewayed off-scan looks orphaned here; a redundant path off-scan looks like a bridge.",
         "Extend collection to the legacy core / any non-responding device."),
        ("Live cluster role (active/standby) & application dependencies", _CONF_MED,
         "Endpoint vendor/class and cohesive units are now inferred (see §7.1/§8.1), but which node is "
         "active vs standby, and which app depends on which, is not provable from passive data.",
         "Confirm cluster roles + app dependencies with the application owners using the §8.1 clusters "
         "and the per-switch service checklist (§11.1) as the starting map."),
    ]
    for name, conf, gates, nextstep in unknowns:
        p = doc.add_paragraph(style="List Bullet")
        _label_run(p, name + ":", f"[{conf}] {gates}")
        sp = doc.add_paragraph(style="List Bullet 2"); _label_run(sp, "Next validation:", nextstep)

    # landscape for the wide tables; US Letter
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Inches(11), Inches(8.5)
    # running footer
    footer = sec.footer.paragraphs[0]
    footer.text = f"{label} — Assessment & Migration Runbook (DRAFT, evidence-led)"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in footer.runs:
        run.font.size = Pt(8); run.font.color.rgb = GREY

    doc.save(output_path)
    logger.info(f"[Phase 31] Runbook (DOCX) written: {output_path}")
