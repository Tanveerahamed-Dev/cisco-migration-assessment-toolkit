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

from cisco_toolkit.docmeta import add_acceptance, add_document_control

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


def write_runbook_docx(output_path: str, snap_dict: dict, label: str, flow_paths: dict = None) -> None:
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

    # ---- document control (AS-style front matter; unnumbered so §1–§13 are untouched) ----
    add_document_control(
        doc, document="Network Assessment & Migration Runbook", label=label,
        engine_version=str(snap_dict.get("script_version", "")),
        generated_at=snap_dict.get("generated_at"),
        audience="The customer's network engineering and operations teams and the migration war "
                 "room; review owner: the customer's network architecture owner.",
        exclude=("runbook",))
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

    # cross-axis migration brief (NEW-V3.23.120)
    eb = snap_dict.get("executive_brief") or {}
    if eb.get("axes"):
        _label_run(doc.add_paragraph(), "Migration brief:", eb.get("posture_statement", ""))
        tg = eb.get("top_gating") or []
        if tg:
            _label_run(doc.add_paragraph(), "Address first:", "; ".join(tg[:6]))
        table(["Axis", "Severity", "Headline"],
              [[a.get("axis"), a.get("severity"), a.get("headline")] for a in eb["axes"]],
              widths=[1.8, 0.9, 4.0])

    # ===== 2. Scope & Data Completeness =====
    doc.add_heading("2. Scope & Data Completeness", level=1)
    doc.add_paragraph(
        f"In scope: the {n_dev} Cisco switches present in the collected dataset and their "
        "configuration, interface, CDP/LLDP, STP, FHRP/SVI, and routing-adjacency state.")
    doc.add_paragraph("Dataset limits (these bound every claim below):", style="List Bullet")
    _mc_collected = ((snap_dict.get("service_map") or {}).get("multicast") or {}).get("group_level_collected")
    _mc_limit = ("Multicast / PTP group membership IS collected; QoS baselines are not — and PTP lock state "
                 "is read from `show ptp clock`, not observed over time."
                 if _mc_collected else
                 "Multicast / PTP / QoS baselines are not collected — broadcast-media timing health is Unknown.")
    for t in (
        "No live forwarding/ARP-aging telemetry — endpoint presence is a snapshot, not a census over time.",
        "Topology is CDP/LLDP-derived: links to off-scan or non-advertising devices are Unknown.",
        _mc_limit,
        "Active FHRP ownership and failover behaviour are inferred from config, not observed over a failover.",
    ):
        doc.add_paragraph(t, style="List Bullet 2")

    # Collection completeness / blind spots (NEW-V3.23.109): make the un-/partially-collected inventory
    # devices explicit -- every finding is only as trustworthy as the data behind it.
    cc = snap_dict.get("collection_completeness") or {}
    cs = cc.get("summary") or {}
    blind = cc.get("devices") or []
    if cs.get("inventory"):
        doc.add_heading("2.1 Collection completeness (assessment blind spots)", level=2)
        doc.add_paragraph(
            f"Of {cs.get('inventory', 0)} inventory device(s): {cs.get('complete', 0)} fully collected, "
            f"{cs.get('partial', 0)} partial, {cs.get('not_collected', 0)} NOT collected. The not-/partially-"
            f"collected devices below are assessment blind spots ({_CONF_UNKNOWN} state) — re-collect them "
            "before relying on the findings for those devices; a missing device is not a healthy device.")
        if blind:
            table(["Status", "Device", "Data quality", "Missing essential commands"],
                  [[d.get("status", ""), d.get("host", ""), f"{d.get('data_quality', 0)}%",
                    ", ".join(d.get("missing", []))] for d in blind[:40]],
                  widths=[1.3, 2.8, 1.0, 3.3])
            if len(blind) > 40:
                doc.add_paragraph(f"…and {len(blind) - 40} more — see the 'Collection Completeness' sheet.")

    # ===== 3. Scenario Classification =====
    doc.add_heading("3. Scenario Classification", level=1)
    doc.add_paragraph(
        "Primary mode: Migration planning (brownfield). Secondary: steady-state health assessment. "
        "The plan rests on an endpoint-move architecture: access-layer switches and their endpoints "
        "move in dependency-scoped groups while L3 gateways remain on the legacy core. That premise is "
        "validated per VLAN in §6; VLANs whose gateway cannot be evidenced are gated, not assumed.")
    scen = snap_dict.get("migration_scenarios") or {}
    if scen.get("fleet_recommendation"):
        p = doc.add_paragraph()
        _label_run(p, "Fleet recommendation:", scen["fleet_recommendation"])
    pg = scen.get("per_group") or []
    if pg:
        doc.add_paragraph("Recommended cutover scenario per move-group (the group's shape decides; the "
                          "war-room confirms). Playbooks per scenario are in §11:")
        table(["Move group", "Switches", "Dual-homed %", "Hard cutovers", "Scenario", "Why"],
              [[g.get("group") or "(group)", g.get("switches"), g.get("dual_homed_pct"),
                g.get("hard_cutover"), g.get("recommended_scenario"), g.get("rationale")]
               for g in pg[:12]], widths=[1.6, 0.9, 1.1, 1.1, 1.4, 3.4])

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

    # 4.1 Hardware lifecycle (EoL / End-of-Support) — NEW-V3.23.117
    lr = snap_dict.get("lifecycle_risk") or {}
    ls = lr.get("summary") or {}
    if ls.get("n_devices"):
        doc.add_heading("4.1 Hardware lifecycle (EoL / End-of-Support)", level=2)
        doc.add_paragraph(
            f"As of {lr.get('asof', '')}, of {ls.get('n_devices', 0)} device(s): "
            f"{ls.get('n_past_ldos', 0)} are PAST Cisco's last day of support (no software fixes / no TAC), "
            f"{ls.get('n_near', 0)} reach end-of-support within a year, {ls.get('n_active', 0)} are active, "
            f"{ls.get('n_unknown', 0)} unknown. End-of-support hardware is a hard migration driver.")
        _label_run(doc.add_paragraph(), "Reference note:", lr.get("note", ""), GREY)
        rows = [[p.get("platform"), p.get("count"), p.get("band"), p.get("ldos") or "—"]
                for p in (ls.get("by_platform") or [])]
        if rows:
            table(["Platform", "Devices", "Lifecycle band", "LDoS"], rows, widths=[2.6, 1.0, 1.7, 1.4])

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

    si = snap_dict.get("subnet_intelligence") or {}
    pdv = si.get("per_device") or []
    if pdv:
        doc.add_heading("6.4 Subnet & routing reachability", level=2)
        n_l3 = sum(1 for r in pdv if r.get("is_l3"))
        bgp_note = ("BGP received-prefixes were collected." if si.get("bgp_received_collected")
                    else f"BGP received-prefixes were NOT collected ({_CONF_UNKNOWN}); re-run with the "
                         "new 'show ip bgp' command to populate them.")
        doc.add_paragraph(
            f"{n_l3} L3 device(s) terminate/route subnets; {len(pdv) - n_l3} L2 access switch(es) reach "
            "their subnets transitively via a gateway SVI. Destination = subnets a device terminates "
            f"({_CONF_CONFIRMED} from connected routes/SVIs); reachable = its route table "
            f"({_CONF_CONFIRMED}-at-snapshot from 'show ip route'). {bgp_note}")
        top = sorted([r for r in pdv if r.get("is_l3")],
                     key=lambda r: -(r.get("destination_count", 0) + r.get("reachable_count", 0)))[:12]
        doc.add_paragraph("L3 devices — subnets terminated vs reachable:")
        table(["Switch", "Dest subnets", "Reachable", "Sources", "Default next-hop"],
              [[r.get("host"), r.get("destination_count"), r.get("reachable_count"),
                ", ".join(f"{k}:{v}" for k, v in (r.get("reachable_sources") or {}).items()),
                r.get("default_next_hop", "")] for r in top], widths=[3.0, 1.1, 1.1, 2.4, 1.4])
        mg = si.get("move_groups") or []
        if mg:
            doc.add_paragraph("Per move-group source↔destination (local subnets move with the group; "
                              "remote subnets must stay reachable across the cutover):")
            table(["Move group", "Switches", "Local subnets", "Remote subnets to preserve"],
                  [[m.get("group") or "(group)", m.get("switches"), m.get("local_count"),
                    m.get("remote_count")] for m in mg[:12]], widths=[2.0, 1.0, 1.4, 2.2])

    fpaths = (flow_paths or {}).get("flows") or []
    if fpaths:
        fsum = (flow_paths or {}).get("summary") or {}
        doc.add_heading("6.4.1 Representative end-to-end flow paths", level=3)
        doc.add_paragraph(
            f"{fsum.get('n_flows', 0)} representative flow(s) — the lowest-IP endpoint per VLAN, traced "
            "L1–L3 (the static twin of the explorer's interactive Flow Simulator): "
            f"{fsum.get('n_at_risk', 0)} at HIGH/CRITICAL risk, {fsum.get('n_partitioned', 0)} partitioned. "
            "Each path is a lower bound (scan-bound topology); the explorer walks any chosen pair, all OSI "
            "layers, with the backup path. See the workbook 'Flow Paths' sheet for the full hop list.")
        table(["Flow (VLAN → VLAN)", "Type", "Risk", "SPOFs on path"],
              [[f.get("label", ""), (f.get("summary") or {}).get("flow_type", ""),
                (f.get("summary") or {}).get("risk", ""),
                "; ".join((f.get("summary") or {}).get("spofs") or []) or "none"]
               for f in fpaths], widths=[2.8, 1.4, 0.9, 2.4])

    pintel = snap_dict.get("protocol_intelligence") or []
    if pintel:
        doc.add_heading("6.5 Protocol behaviour & remediation", level=2)
        n_high = sum(1 for r in pintel if r.get("severity") == "High")
        by_proto = sorted({r.get("protocol", "") for r in pintel})
        doc.add_paragraph(
            f"{len(pintel)} abnormal control-plane state(s) across {len(by_proto)} protocol(s) "
            f"[{', '.join(by_proto)}], {n_high} High. Each observed state is a fact (read from the "
            f"device); the likely cause is Inferred per Cisco doctrine ({_CONF_UNKNOWN} until validated "
            "live). Fix these before the affected switches are cut over.")
        table(["Severity", "Switch", "Protocol", "State", "Likely cause (Inferred) → Remediation"],
              [[r.get("severity", ""), r.get("switch", ""), r.get("protocol", ""), r.get("state", ""),
                (r.get("likely_cause", "") + "  →  " + r.get("remediation", "")).strip()[:200]]
               for r in sorted(pintel, key=lambda r: _SEV_ORDER.get(r.get("severity"), 9))[:18]],
              widths=[0.9, 2.0, 1.1, 0.7, 4.3])

    sm = snap_dict.get("service_map") or {}
    svcs = sm.get("services") or []
    mc = sm.get("multicast") or {}
    if svcs or mc.get("active_interfaces"):
        doc.add_heading("6.6 Services & multicast (observed vs intent)", level=2)
        doc.add_paragraph(
            f"L4 services referenced in ACLs are migration *design intent* ({_CONF_UNKNOWN} as live "
            "traffic — there is no flow telemetry); preserve these reachabilities across the cutover. "
            f"Multicast forwarding presence (PIM/mroute on an interface) is {_CONF_CONFIRMED}; when the "
            "IGMP/mroute group collection is present the broadcast/PTP groups are classified below.")
        if svcs:
            table(["Port", "Proto", "Service", "Category", "ACL refs", "Switches"],
                  [[s.get("port"), s.get("proto"), s.get("service"), s.get("category"),
                    s.get("refs"), s.get("host_count")] for s in svcs[:15]],
                  widths=[0.8, 0.8, 1.7, 1.4, 1.0, 1.0])
        groups = mc.get("classified_groups") or []
        bcast = [g for g in groups if g.get("broadcast")]
        gnote = (f" {len(groups)} multicast group(s) classified ({len(bcast)} broadcast/AV)." if groups
                 else f" Per-group (S,G)/IGMP classification {_CONF_UNKNOWN} until re-collection.")
        doc.add_paragraph(
            f"Multicast: {mc.get('active_interfaces', 0)} interface(s) across "
            f"{mc.get('active_switch_count', 0)} switch(es) run PIM/mroute ({_CONF_CONFIRMED} "
            f"forwarding presence).{gnote}")
        # PTP is a per-switch map {host: clock-summary}; report operational boundary clocks vs dormant.
        ptp = mc.get("ptp") or {}
        if ptp:
            oper = [h for h, v in ptp.items() if (v or {}).get("operational")]
            gms = sorted({(v or {}).get("grandmaster") for v in ptp.values() if (v or {}).get("grandmaster")})
            if oper:
                doc.add_paragraph(
                    f"PTP (IEEE 1588): {len(oper)} of {len(ptp)} switch(es) act as boundary/transparent "
                    f"clocks" + (f" (grandmaster(s) {', '.join(gms)})" if gms else "") +
                    f"; the rest have PTP present but dormant ({_CONF_CONFIRMED}). PTP lock gates any "
                    "ST 2110 / AES67 / Dante move-group cutover.")
            else:
                doc.add_paragraph(
                    f"PTP (IEEE 1588): present on {len(ptp)} switch(es) but NONE are active boundary/"
                    "transparent clocks (Device Type Unknown / 0 ports / no parent) — PTP is flowing as "
                    f"plain multicast, not boundary-clocked ({_CONF_CONFIRMED}). For ST 2110/AES67/Dante "
                    "timing accuracy, confirm whether boundary-clock mode is required on the media-path "
                    "switches before the cutover.")
        queriers = mc.get("igmp_queriers") or []
        if queriers:
            doc.add_paragraph(f"IGMP snooping querier present on {len(queriers)} VLAN(s) "
                              f"({_CONF_CONFIRMED}); VLANs without a querier risk multicast flooding/pruning.")
        # media-fabric intelligence (NEW-V3.23.115): MAC-aliasing / querier coverage / PTP tree
        mi = snap_dict.get("multicast_intelligence") or {}
        aliases = mi.get("mac_aliases") or []
        if aliases:
            doc.add_paragraph(
                f"Multicast MAC-address aliasing ({_CONF_CONFIRMED}, RFC 4541): {len(aliases)} case(s) where "
                "groups collapse to one L2 MAC (IPv4 multicast is 32:1 into Ethernet MACs) so a MAC-level switch "
                "forwards them together — " + "; ".join(f"{a.get('mac')} ← {', '.join(a.get('groups') or [])}"
                                                        for a in aliases[:4])
                + ". Re-address one of each overlapping pair (or use IGMPv3 SSM end-to-end) before the cutover.")
        gaps = (mi.get("querier") or {}).get("gap_vlans") or []
        if gaps:
            doc.add_paragraph(
                f"Multicast VLANs without an IGMP querier ({_CONF_CONFIRMED}, RFC 4541): VLAN(s) "
                f"{', '.join(gaps[:20])} carry multicast but have no querier — flooding/blackhole risk; "
                "configure exactly one querier per multicast VLAN.")
        ptp_tree = mi.get("ptp") or {}
        if ptp_tree.get("n_clocks"):
            doc.add_paragraph(
                f"PTP timing tree (ST 2059): {ptp_tree.get('n_operational', 0)} of {ptp_tree.get('n_clocks', 0)} "
                f"clock(s) are active boundary clocks, {ptp_tree.get('n_dormant', 0)} dormant"
                + (f"; grandmaster(s) {', '.join(ptp_tree.get('grandmasters') or [])}."
                   if ptp_tree.get("grandmasters") else "; no grandmaster observed."))

    # ===== 6.7 Application domains (workload synthesis & migration playbook) — NEW-V3.23.112 =====
    appi = snap_dict.get("application_intelligence") or {}
    appd = appi.get("domains") or []
    if appd:
        doc.add_heading("6.7 Application domains & migration playbook", level=2)
        asum = appi.get("summary") or {}
        doc.add_paragraph(
            f"The fleet resolves into {asum.get('n_domains', len(appd))} application domain(s) "
            f"({asum.get('n_on_air_critical', 0)} on-air-critical, {asum.get('n_high_risk', 0)} carrying a "
            "High/Critical migration risk). Each switch is attributed by a deliberate hostname role token, by "
            f"observed PTP/multicast ({_CONF_CONFIRMED}), or by its dominant endpoint class ({_CONF_MED}); "
            "switches with no application signal fall to a General bucket rather than being over-claimed as a "
            "media fabric. Per-domain migration risk is grounded in broadcast-over-IP practice (SMPTE ST 2059 "
            "boundary clocks, RFC 4541 IGMP-querier continuity, ST 2022-7 dual-path, Avid NEXIS dual-leg).")
        table(["Domain", "Tier", "Switches", "Endpoints", "PTP", "Top migration risk"],
              [[d.get("domain"), d.get("tier"), d.get("switch_count"), d.get("endpoint_count"),
                ("boundary-clocked" if d.get("ptp_boundary_clocked")
                 else "present, NOT BC" if d.get("ptp_present") else "—"),
                ((d.get("risks") or [{}])[0].get("title", "—") if d.get("risks") else "—")]
               for d in appd],
              widths=[2.2, 1.2, 0.8, 0.9, 1.1, 2.3])
        # the on-air-critical domain risks as evidence-disciplined findings (false-health doctrine)
        for d in appd:
            if d.get("tier") != "On-air critical":
                continue
            for r in (d.get("risks") or []):
                if r.get("severity") not in ("Critical", "High"):
                    continue
                finding_block(
                    f"{d.get('domain')} — {r.get('title')}",
                    severity=r.get("severity"),
                    scope=f"{d.get('switch_count')} switch(es); tier {d.get('tier')}",
                    observed=d.get("evidence", ""),
                    interpretation=r.get("detail", ""),
                    impact="On-air media path — a timing or multicast break at cutover is audience-visible.",
                    confidence=f"{_CONF_CONFIRMED} (switch state) / {_CONF_MED} (media dependency)",
                    unknowns="Whether this domain's live traffic actually traverses the flagged switches at "
                             "cutover time (no flow telemetry).",
                    next_validation="; ".join(d.get("validation") or []),
                    remediation=r.get("remediation", ""))
        cross = appi.get("cross_domain_risks") or []
        if cross:
            doc.add_paragraph(
                f"Cross-domain risks (IGMP querier continuity / RFC 4541 + dependency coupling): "
                f"{len(cross)} finding(s) — " + "; ".join(c.get("title", "") for c in cross[:6]) + ".")
        # 6.7.1 inter-domain dependency graph (NEW-V3.23.113)
        edges = appi.get("edges") or []
        keystones = appi.get("keystones") or []
        if edges:
            doc.add_heading("6.7.1 Inter-domain dependencies (what couples to what)", level=3)
            kline = ""
            if keystones:
                k = keystones[0]
                kline = (f" The keystone domain is {k.get('domain')} (weighted coupling degree "
                         f"{k.get('degree')}, {len(k.get('neighbors') or [])} neighbour domains) — the widest "
                         "cross-domain blast radius; sequence it deliberately, not as an early pilot.")
            doc.add_paragraph(
                f"The domains are coupled by {len(edges)} dependency edge(s): physical inter-switch links "
                f"({_CONF_CONFIRMED}), shared subnets ({_CONF_HIGH}), and dual-homed endpoints that span domains "
                f"({_CONF_CONFIRMED}). A coupling means two domains cannot be cut over in isolation without "
                f"coordination.{kline}")
            table(["Domain A", "Domain B", "Weight", "Coupling", "Migration note"],
                  [[e.get("source"), e.get("target"), e.get("weight"), ", ".join(e.get("kinds") or []),
                    e.get("migration_note") or ("media-adjacent" if e.get("media") else "")]
                   for e in edges[:15]],
                  widths=[1.9, 1.9, 0.7, 1.4, 2.6])
        # 6.7.2 recommended cutover order (NEW-V3.23.114)
        cutover = appi.get("cutover_order") or []
        if cutover:
            doc.add_heading("6.7.2 Recommended cutover order", level=3)
            doc.add_paragraph(
                "A migration-criticality score (tier + health + open risk + dependency coupling + timing/wave "
                f"flags) orders the domains lowest-risk first. Start with the {asum.get('pilot_domain', '')} "
                f"pilot to fail-fast and learn; migrate {asum.get('last_domain', '')} last with make-before-break "
                "and full validation. A recommendation — the war-room sets the final schedule.")
            table(["#", "Band", "Domain", "Tier", "Score", "Rationale"],
                  [[c.get("order"), c.get("band"), c.get("domain"), c.get("tier"), c.get("score"),
                    c.get("rationale")] for c in cutover],
                  widths=[0.4, 0.8, 2.0, 1.2, 0.6, 3.0])

    # 6.8 Segmentation & isolation (NEW-V3.23.118)
    seg = snap_dict.get("segmentation") or {}
    ss = seg.get("summary") or {}
    if ss.get("n_gateways"):
        doc.add_heading("6.8 Segmentation & isolation", level=2)
        ga = seg.get("gateway_acl") or {}
        doc.add_paragraph(
            ("The L3 fabric is FLAT: " if ss.get("flat") else "")
            + f"{ss.get('n_vrfs', 0)} VRF(s) across {ss.get('n_gateways', 0)} gateway SVI(s); only "
            f"{ga.get('n_with_acl', 0)} ({ga.get('coverage_pct', 0)}%) apply an ACL. "
            f"{ss.get('n_oncrit_exposed', 0)} on-air-critical domain(s) are not isolated — they share the global "
            "routing table with back-office and management and have no gateway ACL. Segmentation for the media "
            "fabric must be designed into the target.")
        rows = [[d.get("domain"), d.get("tier"), d.get("gateways"),
                 "yes" if d.get("isolated") else "NO", d.get("exposure")]
                for d in (seg.get("domains") or [])]
        if rows:
            table(["Domain", "Tier", "Gateways", "Isolated", "Exposure"], rows, widths=[2.2, 1.2, 0.8, 0.8, 3.0])

    # 6.9 golden-config drift (NEW-V3.23.146): per-device running-config compliance vs the baseline.
    gd = snap_dict.get("golden_drift") or {}
    gsum = gd.get("summary") or {}
    if gsum.get("n_baseline"):
        doc.add_heading("6.9 Configuration-standard drift", level=2)
        gmode = gsum.get("mode") or gd.get("mode") or "majority"
        gsrc = ("a supplied golden-config baseline" if gmode == "golden-file"
                else "the fleet's de-facto majority baseline (auto-derived)")
        doc.add_paragraph(
            f"Each device's running-config measured against {gsrc} of {gsum.get('n_baseline', 0)} required "
            f"directive(s): {gsum.get('n_drifting', 0)} of {gsum.get('n_devices', 0)} device(s) drift "
            f"(avg compliance {gsum.get('avg_compliance_pct', 0)}%). Bring the drifting devices up to the "
            "standard before — or as part of — their cutover wave.")
        drows = [[d.get("host"), f"{d.get('compliance_pct', 0)}%", d.get("n_missing", 0),
                  "; ".join((d.get("missing") or [])[:6])]
                 for d in (gd.get("per_device") or []) if d.get("n_missing")]
        if drows:
            table(["Device", "Compliance", "Missing", "Missing required directives"],
                  drows, widths=[1.6, 1.0, 0.8, 4.6])
        else:
            doc.add_paragraph("All devices match the baseline — no configuration drift.")

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

    # scenario playbooks for the recommended scenarios (NEW-V3.23.98).
    pg2 = (snap_dict.get("migration_scenarios") or {}).get("per_group") or []
    if pg2:
        seen_sc = {}
        for g in pg2:
            sc = g.get("recommended_scenario")
            if sc and sc not in seen_sc and g.get("playbook"):
                seen_sc[sc] = g["playbook"]
        if seen_sc:
            doc.add_heading("11.2 Cutover playbook by scenario", level=2)
            table(["Scenario", "Pre-check", "Validate", "Rollback"],
                  [[sc, pb.get("pre", ""), pb.get("validate", ""), pb.get("rollback", "")]
                   for sc, pb in sorted(seen_sc.items())], widths=[1.3, 2.7, 2.7, 2.7])

    # 11.3 generated per-wave post-cutover verification plan (NEW-V3.23.143): the concrete checks +
    # commands + expected good result (captured from the pre-cutover state) to run after each wave.
    vp = snap_dict.get("validation_plan") or {}
    vp_by_wave = vp.get("by_wave") or {}
    if vp_by_wave:
        vs = vp.get("summary") or {}
        doc.add_heading("11.3 Post-cutover verification plan (per wave)", level=2)
        doc.add_paragraph(
            f"{vs.get('n_items', 0)} check(s) across {vs.get('n_waves', 0)} wave(s) "
            f"({vs.get('n_high', 0)} High/Critical). After each wave's cutover run these and confirm the "
            "result matches the 'Expect' column — it is the known-good output captured from the "
            "pre-cutover state, so a deviation is a regression. Full detail is in the 'Cutover "
            "Validation' workbook sheet.")
        for wave, vits in vp_by_wave.items():
            doc.add_heading(f"Wave: {wave}", level=3)
            table(["Device", "Category", "Check", "Command", "Expect (good result)"],
                  [[it.get("device"), it.get("category"), it.get("check"), it.get("command"), it.get("expect")]
                   for it in vits[:14]], widths=[1.6, 1.1, 2.6, 2.2, 2.5])
            if len(vits) > 14:
                doc.add_paragraph(f"…and {len(vits) - 14} more check(s) for {wave} — see the 'Cutover "
                                  "Validation' workbook sheet.")

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

    # ===== 13. Remediation Appendix (generated config, review-only) — NEW-V3.23.116 =====
    rp = snap_dict.get("remediation_plan") or {}
    rem_items = rp.get("items") or []
    if rem_items:
        doc.add_heading("13. Remediation Appendix — generated config (review only)", level=1)
        bp = doc.add_paragraph()
        _label_run(bp, "⚠ Review banner:", rp.get("banner") or
                   "Generated for review — validate against the running-config and change-control before applying.",
                   GREY)
        rs = rp.get("summary") or {}
        doc.add_paragraph(
            f"{rs.get('n_items', 0)} generated fix snippet(s) across {rs.get('n_devices', 0)} device(s) "
            f"({rs.get('n_high', 0)} High/Critical), per device in severity order. Placeholders (<...>) mark "
            "values that require local intent — do not paste them literally.")
        by_dev = rp.get("by_device") or {}
        ranked = sorted(by_dev.items(),
                        key=lambda kv: (-sum(1 for it in kv[1] if it.get("severity") in ("Critical", "High")),
                                        str(kv[0])))
        for host, its in ranked[:40]:
            doc.add_heading(str(host), level=2)
            for it in its[:8]:
                hp = doc.add_paragraph()
                hr = hp.add_run(f"[{it.get('severity')}] {it.get('category')} — {it.get('title')}"); hr.bold = True
                cp = doc.add_paragraph(); cp.paragraph_format.left_indent = Inches(0.3)
                cr = cp.add_run("\n".join(it.get("commands") or []))
                cr.font.name = "Consolas"; cr.font.size = Pt(9)
                _label_run(doc.add_paragraph(style="List Bullet 2"), "Verify:", it.get("verify", ""))
                _label_run(doc.add_paragraph(style="List Bullet 2"), "Caution:", it.get("caution", ""))
            if len(its) > 8:
                doc.add_paragraph(f"…and {len(its) - 8} more item(s) for {host} — see the Remediation Plan sheet.")
        if len(ranked) > 40:
            doc.add_paragraph(f"…and {len(ranked) - 40} more device(s) — see the Remediation Plan workbook sheet.")

    # ---- closing acceptance gate (AS-style back matter) ----
    add_acceptance(
        doc, scope_note="Acceptance of this runbook confirms its findings and migration approach as "
                        "the agreed basis for the MOP and cutover planning that follow.")

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
