"""Operations Handbook — the PPDIOO Operate-phase deliverable (.docx).

NEW-V3.23.168: the document family covered Prepare→Plan→Design→Implement (CRD, design,
MOP, cutover, NRFU) and the close-out (PIR), but nothing for the OPERATE phase — the
handbook the customer's NOC actually runs the network with after the migration. This
generator turns the assessment's own evidence into that handbook: the monitoring
baseline comes from what the syslog axis actually saw fire, the capacity baseline from
the platform-health sample, the drift-control standard from the golden-config baseline,
and the patch-governance section from the software-risk screening.

Evidence discipline: every axis-backed section is GATED on its snapshot key — an older
snapshot (or a collection without that evidence) gets an honest one-line declaration and
a re-collection prompt, never an invented baseline. Placeholders mark everything only the
customer can decide (contacts, escalation tiers, maintenance windows).

python-docx is OPTIONAL: imported inside the function so the package imports without it;
a missing library is a warning + skip, never a crash. Deterministic; no network.
"""
import logging
from datetime import datetime

from cisco_toolkit.docmeta import add_acceptance, add_document_control, add_excellence_front, add_glossary, add_inputs_required, add_table, add_toc
from cisco_toolkit.docmeta import as_dict as _as_dict
from cisco_toolkit.docmeta import as_list as _as_list
from cisco_toolkit.textutils import xml_safe, xml_safe_deep   # entry deep-sanitize of device text (audit-5)

logger = logging.getLogger(__name__)


def _facts(snap: dict) -> dict:
    """Defensive reads of the snapshot sections the handbook is grounded in."""
    devices = _as_dict(snap.get("devices"))
    fi = _as_list(snap.get("failure_impact"))
    keystones = [r for r in fi if isinstance(r, dict)]

    def _stranded(r):
        try:
            return int(r.get("stranded") or 0)
        except (TypeError, ValueError):
            return 0
    keystones.sort(key=lambda r: (-_stranded(r), str(r.get("host") or "")))
    keystones = [k for k in keystones if _stranded(k) > 0]
    si = _as_dict(snap.get("syslog_intelligence"))
    ph = _as_dict(snap.get("platform_health"))
    gd = _as_dict(snap.get("golden_drift"))
    qa = _as_dict(snap.get("qos_audit"))
    sr = _as_dict(snap.get("software_risk"))
    lc = _as_dict(snap.get("lifecycle_risk"))
    sec = _as_dict(snap.get("security"))
    sec_fail = 0
    for host, blk in sec.items():
        s = _as_dict(_as_dict(blk).get("summary"))
        try:
            sec_fail += int(s.get("fail") or 0)
        except (TypeError, ValueError):
            continue
    # routing-adjacency + first-hop-redundancy Day-2 health (N36)
    ph2 = _as_list(snap.get("protocol_health"))
    routing_protos = sorted({str(r.get("protocol", "")).upper() for r in ph2 if isinstance(r, dict)
                             and str(r.get("protocol", "")).upper() in ("OSPF", "BGP", "EIGRP", "ISIS", "IS-IS")})
    n_proto_high = sum(1 for r in ph2 if isinstance(r, dict) and r.get("severity") in ("High", "Critical"))
    l3f = _as_list(snap.get("l3_forwarding"))
    n_gw = len(l3f)
    n_fhrp = sum(1 for r in l3f if isinstance(r, dict) and (str(r.get("fhrp", "none")) or "none") != "none")
    return {"devices": devices, "keystones": keystones[:5], "si": si, "ph": ph,
            "gd": gd, "qa": qa, "sr": sr, "lc": lc, "n_sec_fail": sec_fail,
            "routing_protos": routing_protos, "n_proto_high": n_proto_high, "n_gw": n_gw, "n_fhrp": n_fhrp}


def write_ops_handbook_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the Operations Handbook (.docx) to `output_path`. Fail-soft: a missing
    python-docx is a warning + skip; any unexpected render error is logged, never raised."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        logger.warning("  Operations handbook (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the Operate-phase deliverable).")
        return

    snap = xml_safe_deep(snap_dict if isinstance(snap_dict, dict) else {})   # one bad device byte (noncharacter/surrogate) must not abort the docx
    label = xml_safe(label) if isinstance(label, str) else (str(label) if label is not None else "")
    NAVY = RGBColor(0x1F, 0x38, 0x64)
    GREY = RGBColor(0x59, 0x59, 0x59)
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    def _label_run(p, label_text, value, color=NAVY):
        r = p.add_run(label_text); r.bold = True; r.font.color.rgb = color
        p.add_run(" " + (str(value) if value not in (None, "") else "—"))

    def table(headers, rows, widths=None):
        return add_table(doc, headers, rows, widths, fixed=False)

    def absent(what, how):
        p = doc.add_paragraph()
        _label_run(p, "Not in this snapshot:", f"{what} — {how}", GREY)

    ev = _facts(snap)
    devices = ev["devices"]

    # ---- title page ----
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Operations Handbook"); tr.bold = True
    tr.font.size = Pt(26); tr.font.color.rgb = NAVY
    sub2 = doc.add_paragraph(); sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s2 = sub2.add_run("Operate-phase handbook — monitoring baseline, drift control, "
                      "software governance and escalation readiness")
    s2.font.size = Pt(14); s2.font.color.rgb = GREY
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr2 = sub.add_run(label); sr2.font.size = Pt(13); sr2.font.color.rgb = GREY
    meta = doc.add_paragraph(); meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _scale = _as_dict(_as_dict(snap.get("executive_brief")).get("scale"))   # coerce: a truthy non-dict eb/scale must not crash (audit-4 #10)
    _ncoll = _scale.get("n_collected")
    _ninv = _scale.get("n_devices")                                         # canonical inventoried (SSOT owner: executive_brief.scale.n_devices); len() only pre-brief (CROSS-03)
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{_ncoll if isinstance(_ncoll, int) else len(devices)} collected of "
                 f"{_ninv if isinstance(_ninv, int) else len(devices)} inventoried  ·  script {snap.get('script_version', '')}"
                 ).font.color.rgb = GREY
    doc.add_paragraph()
    note = doc.add_paragraph()
    _label_run(note, "How to use this handbook:",
               "This is the Day-2 companion to the migration documents: the monitoring thresholds, "
               "baselines and cadences below are derived from this fleet's own assessed evidence, "
               "not generic defaults. Adopt it as the NOC's working document — complete the "
               "<placeholder> contact and window fields, then re-generate from a fresh assessment "
               "whenever the network changes materially (the baselines move with the evidence).", GREY)
    doc.add_page_break()

    # ---- document control ----
    add_document_control(
        doc, document="Operations Handbook", label=label,
        engine_version=str(snap.get("script_version", "")), generated_at=snap.get("generated_at"),
        collected_at=snap.get("collected_at"),
        audience="The customer's NOC / operations team (primary users), the network owner "
                 "(standards and escalation authority) and the delivery engineer handing over.",
        exclude=("opshandbook",),
        extra_assumptions=(
            "Baselines in this handbook are derived from the named assessment snapshot; they are "
            "the network AS ASSESSED, and drift with every change. Re-generate after material "
            "changes rather than hand-editing the numbers.",))
    doc.add_page_break()

    # ---- table of contents (shared field-code helper, V3.23.171) ----
    add_toc(doc)


    # Deliverable Excellence (DE-01): answer-first at-a-glance register + single-source-of-truth signal.
    add_excellence_front(doc, snap_dict)
    # Deliverable Excellence (DE-01): consolidated Inputs-Required register (Law 9).
    add_inputs_required(doc, snap_dict)
    # ===== 1. Purpose & audience =====
    doc.add_heading("1. Purpose & Audience", level=1)
    doc.add_paragraph(
        "The document family covers planning (CRD), design (HLD/LLD), execution (MOP, cutover, "
        "NRFU) and close-out (PIR); this handbook covers what comes after — running the network. "
        "It gives the operations team four things grounded in this fleet's own evidence: a "
        "monitoring baseline (what this network's logs and control planes actually look like), a "
        "drift-control standard, a software-governance cadence, and an escalation pack. It is a "
        "living document owned by operations after handover.")

    # ===== 2. Network quick reference =====
    doc.add_heading("2. Network Quick Reference", level=1)
    if devices:
        rows = [[h, _as_dict(devices[h]).get("model") or "—",
                 _as_dict(devices[h]).get("platform") or "—",
                 _as_dict(devices[h]).get("sw_version") or "—",
                 _as_dict(devices[h]).get("serial_number") or "—"]
                for h in sorted(devices)]
        table(["Device", "Model", "Platform", "Software", "Serial"],
              rows[:60], widths=[1.6, 1.7, 0.8, 1.4, 1.5])
        if len(rows) > 60:
            doc.add_paragraph(f"… and {len(rows) - 60} more — full inventory in the workbook.")
    else:
        absent("device inventory", "re-run the collection to populate the quick reference.")
    if ev["keystones"]:
        doc.add_heading("2.1 Keystone devices (handle with care)", level=2)
        doc.add_paragraph(
            "Failure-impact analysis ranks these as the fleet's keystones — the devices whose loss "
            "strands the most endpoints. Treat any work on them as high-risk change control.")
        table(["Device", "Severity", "Endpoints stranded if it fails", "VLANs impacted"],
              [[k.get("host"), k.get("severity", "—"), k.get("stranded", 0),
                k.get("vlans_impacted", 0)]
               for k in ev["keystones"]], widths=[2.0, 1.2, 2.0, 1.6])

    # ===== 3. Monitoring & alerting baseline =====
    doc.add_heading("3. Monitoring & Alerting Baseline", level=1)
    doc.add_heading("3.1 Log signatures to alert on (from this fleet's own logs)", level=2)
    si_sum = _as_dict(ev["si"].get("summary"))
    if si_sum.get("n_devices"):
        if si_sum.get("n_collected"):
            doc.add_paragraph(
                f"The assessment parsed {si_sum.get('total_events', 0)} buffered log event(s) on "
                f"{si_sum.get('n_collected', 0)} device(s) and raised "
                f"{si_sum.get('n_detections', 0)} detection(s). Alert on these signature classes "
                "FIRST — they have already occurred on this network:")
            det_rows = [[d.get("host"), d.get("label"), d.get("severity"), d.get("count", 0)]
                        for d in _as_list(ev["si"].get("detections"))[:12]
                        if isinstance(d, dict)]
            if det_rows:
                table(["Device", "Signature (already seen here)", "Severity", "Count"],
                      det_rows, widths=[1.5, 3.0, 0.9, 0.7])
            else:
                doc.add_paragraph("No detections in the assessed window — start from the standard "
                                  "set: MAC flaps, err-disable, link flaps, environmental alarms, "
                                  "duplex mismatches, login failures.")
            doc.add_paragraph(
                "Forward syslog to a central collector (the CIS check in the workbook flags devices "
                "without 'logging host') and page on severities 0–2; review severity 3 daily.")
        else:
            absent("log evidence ('show logging')",
                   "re-run the collection (the command is in the standard set) to derive the alert "
                   "baseline from this fleet's own history.")
    else:
        absent("the syslog-intelligence axis", "re-run the assessment with a current engine.")

    doc.add_heading("3.2 Control-plane capacity baseline", level=2)
    ph_sum = _as_dict(ev["ph"].get("summary"))
    if ph_sum.get("n_collected"):
        pb = ph_sum.get("bands") or {}
        btxt = ", ".join(f"{v}× {k}" for k, v in pb.items())
        doc.add_paragraph(
            f"Capacity sample at collection time ({btxt}). These figures are the NORMAL for this "
            "fleet — alert when a device departs its own baseline, not just on absolute thresholds. "
            "The sample is a single point in time: re-sample on the §6 cadence.")
        prow = [[d.get("host"), d.get("cpu_5min") if d.get("cpu_5min") is not None else "—",
                 d.get("mem_free_pct") if d.get("mem_free_pct") is not None else "—",
                 d.get("band")]
                for d in _as_list(ev["ph"].get("per_device"))
                if isinstance(d, dict) and d.get("collected")][:30]
        if prow:
            table(["Device", "CPU 5-min % (baseline)", "Memory free % (baseline)", "Band"],
                  prow, widths=[1.9, 1.7, 1.7, 1.2])
    else:
        absent("CPU/memory capacity output",
               "re-run the collection to capture the control-plane baseline.")

    # ---- 3.3 routing-adjacency & first-hop-redundancy health (Day-2 monitored items, N36) ----
    doc.add_heading("3.3 Routing-adjacency & first-hop-redundancy health", level=2)
    doc.add_paragraph(
        "Beyond CIS / syslog / capacity, the operate phase continuously watches the control plane's "
        "routing adjacencies and gateway redundancy — a silent adjacency drop or a lost FHRP peer is an "
        "outage waiting for the next failure.")
    r36 = []
    if ev["routing_protos"]:
        r36.append(("Routing adjacencies", ", ".join(ev["routing_protos"]),
                    "Baseline the neighbour list per device; alert on any adjacency leaving Full/Up and on "
                    "flap counts."))
    else:
        r36.append(("Routing adjacencies", "none observed (L2-forwarded fleet)",
                    "If routing is introduced in the target design, add adjacency-state + flap monitoring."))
    if ev["n_gw"]:
        if ev["n_fhrp"]:
            r36.append(("First-hop redundancy", f"{ev['n_fhrp']} of {ev['n_gw']} gateway SVI(s) FHRP-protected",
                        "Alert on HSRP/VRRP/GLBP active↔standby transitions and track-decrement events."))
        else:
            r36.append(("First-hop redundancy", f"0 of {ev['n_gw']} gateway SVI(s) — none observed",
                        "No FHRP state to monitor today; introducing gateway redundancy is a design "
                        "recommendation — then alarm on active/standby transitions."))
    if ev["n_proto_high"]:
        r36.append(("Protocol-health findings", f"{ev['n_proto_high']} flagged High at assessment",
                    "Re-verify post-cutover and monitor for recurrence (see the punch-list)."))
    table(["Monitored item", "Observed", "Day-2 alerting"], r36, widths=[1.5, 2.2, 2.8])

    # ===== 4. Operational standards & drift control =====
    doc.add_heading("4. Operational Standards & Drift Control", level=1)
    gd_sum = _as_dict(ev["gd"].get("summary"))
    if gd_sum.get("n_baseline"):
        gmode = gd_sum.get("mode") or "majority"
        gsrc = ("the supplied golden-config standard" if gmode == "golden-file"
                else "the fleet's de-facto majority baseline (auto-derived)")
        doc.add_paragraph(
            f"Configuration standard: {gsrc}, {gd_sum.get('n_baseline', 0)} required directive(s). "
            f"At assessment time {gd_sum.get('n_drifting', 0)} of {gd_sum.get('n_devices', 0)} "
            f"device(s) drifted (average compliance {gd_sum.get('avg_compliance_pct', 0)}%). "
            "Operations owns keeping this at zero: re-run the drift check on the §6 cadence and "
            "treat every new MISSING directive as an unauthorized change until explained.")
    else:
        absent("a configuration baseline",
               "supply --golden-config (or collect ≥3 full running-configs for the majority "
               "baseline) and re-run.")
    qa_sum = _as_dict(ev["qa"].get("summary"))
    if qa_sum.get("n_assessable"):
        qmodes = _as_dict(qa_sum.get("modes"))
        doc.add_paragraph(
            f"QoS posture to hold: {', '.join(f'{v}× {k}' for k, v in qmodes.items())} "
            f"({qa_sum.get('n_findings', 0)} finding(s) open in the QoS Audit sheet). Any new "
            "switch joining the fleet must match its role's trust + queuing template before "
            "carrying traffic.")
    if ev["n_sec_fail"]:
        doc.add_paragraph(
            f"Security hardening: {ev['n_sec_fail']} CIS check failure(s) were open at assessment "
            "time (Security Posture sheet). Each is an operations-owned remediation with a named "
            "owner and date — track them to zero.")

    # ===== 5. Software & lifecycle governance =====
    doc.add_heading("5. Software & Lifecycle Governance", level=1)
    sr_sum = _as_dict(ev["sr"].get("summary"))
    if sr_sum.get("n_devices"):
        tb = _as_dict(sr_sum.get("train_bands"))
        doc.add_paragraph(
            f"Software trains at assessment: {', '.join(f'{v}× {k}' for k, v in tb.items())}. "
            f"{sr_sum.get('n_findings', 0)} exposed advisory surface(s) were open (Software Risk "
            "sheet). Governance: validate every running release with the Cisco PSIRT Software "
            "Checker on the §6 cadence, close the exposed surfaces, and plan upgrades for every "
            "Replace/Upgrade and Verify-EoL train against Cisco's published notices.")
        worst = [d for d in _as_list(ev["sr"].get("per_device"))
                 if isinstance(d, dict)
                 and d.get("train_band") in ("Replace/Upgrade", "Verify EoL")][:12]
        if worst:
            table(["Device", "Version", "Train", "Band"],
                  [[d.get("host"), d.get("sw_version"), d.get("train"), d.get("train_band")]
                   for d in worst], widths=[1.7, 1.5, 1.8, 1.6])
    else:
        absent("the software-risk screening", "re-run the assessment with a current engine.")
    lc_sum = _as_dict(ev["lc"].get("summary"))
    if lc_sum:
        doc.add_paragraph(
            "Hardware lifecycle: the Lifecycle Risk sheet carries the per-device EoX bands — "
            "review quarterly and feed Past-EoS / Near-LDoS devices into budget planning.")

    # ===== 6. Routine operations calendar =====
    doc.add_heading("6. Routine Operations Calendar", level=1)
    doc.add_paragraph(
        "The cadence that keeps the baselines above honest. Each row names its evidence source so "
        "the activity stays mechanical, not aspirational.")
    table(["Cadence", "Activity", "Evidence / tool"], [
        ("Daily", "Review severity 0–3 syslog events against the §3.1 alert list; clear or ticket "
                  "every new detection-class event.", "Central syslog / §3.1"),
        ("Weekly", "Sample control-plane CPU/memory and compare to the §3.2 baseline; investigate "
                   "any device that departed its own normal.", "show processes cpu / §3.2"),
        ("Monthly", "Re-run the configuration drift check; every new missing directive is an "
                    "unauthorized change until explained.", "Toolkit --no-collect re-run / §4"),
        ("Monthly", "Validate running releases against new advisories.",
         "Cisco PSIRT Software Checker / §5"),
        ("Quarterly", "Review hardware EoX bands and software-train lifecycle; feed into budget "
                      "and upgrade planning.", "Lifecycle Risk + Software Risk sheets"),
        ("Quarterly", "Re-run the full assessment and trend it against prior snapshots; the "
                      "baselines in this handbook move with the evidence.",
         "Toolkit (--trend OLD NEW)"),
        ("Per change", "MOP with per-step success criteria + post-change validation; update the "
                       "drift baseline when the standard itself changes.", "MOP / NRFU documents"),
    ], widths=[1.0, 4.0, 1.9])

    # ===== 7. Escalation & TAC readiness =====
    doc.add_heading("7. Escalation & TAC Readiness", level=1)
    doc.add_paragraph(
        "Before any vendor case: capture the evidence pack below — it answers the first round of "
        "TAC questions in one attachment and anchors the case to facts.")
    table(["Item", "Where it comes from"], [
        ("Device model, serial and running release", "§2 quick reference (verify against the device)"),
        ("The failing device's full command capture", "Re-run the toolkit collection for that device "
                                                      "(read-only show commands)"),
        ("'show tech-support' from the affected device", "Collected at incident time (large; collect "
                                                         "to file)"),
        ("Recent log excerpt around the event", "Central syslog / 'show logging'"),
        ("Relevant advisory IDs already screened", "Software Risk sheet (§5)"),
        ("The assessment workbook + this handbook", "Engagement deliverables"),
    ], widths=[3.0, 3.9])
    doc.add_paragraph(
        "Escalation tiers, contacts and response targets are the customer's to define:")
    table(["Tier", "Condition", "Contact", "Response target"], [
        ("P1", "<service-down condition>", "<name / desk>", "<minutes>"),
        ("P2", "<degraded / redundancy-lost condition>", "<name / desk>", "<hours>"),
        ("P3", "<single-user / non-urgent condition>", "<queue>", "<business days>"),
    ], widths=[0.6, 2.7, 1.9, 1.7])

    # ---- acceptance ----
    # Deliverable Excellence (DE-01): shared glossary before the sign-off gate.
    add_glossary(doc)

    add_acceptance(
        doc, scope_note="Acceptance of this handbook transfers Day-2 operational ownership to the "
                        "customer's operations team; the baselines inside it are superseded by each "
                        "newer accepted re-generation.")

    doc.save(output_path)
    logger.info(f"[Phase 38] Operations handbook (DOCX) written: {output_path} "
                f"({_ninv if isinstance(_ninv, int) else len(devices)} devices in scope)")   # canonical n_devices (reuse title's read); len() only pre-brief (CROSS-03)
