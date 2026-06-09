"""Method of Procedure (MOP) — per-wave migration cutover runbook (.docx).

NEW-V3.23.149: the Implement-phase deliverable. A Cisco Advanced Services migration ends each wave in
a maintenance window driven by a MOP: scope, pre-cutover baseline capture, the ordered procedure,
post-cutover validation, and rollback. This module emits one MOP document with a section per migration
wave (move group), assembled from the SAME snapshot the other deliverables read so it stays consistent
with the workbook / explorer / runbook / design doc.

It is a TEMPLATE primed with the assessment's evidence — never an auto-executed change. The procedure
steps carry <placeholder> markers for window-specific facts (date, owner, approver), and the cutover
strategy (make-before-break vs hard cutover) and the rollback come from the per-group migration
scenario the engine already recommended. The post-cutover checks are the EXISTING validation plan
(one source of truth: the same per-wave checks the workbook's Cutover Validation sheet carries).

python-docx is OPTIONAL: imported inside the function so the package imports without it; a missing
library is a warning + skip, never a crash. Every snapshot read is defensive. Deterministic; no network.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _waves(snap: dict):
    """Resolve the ordered list of migration waves as (name, switches[]) pairs. Prefer the
    migration_readiness verdict rows (they carry the group name + switch set the validation plan keys
    on); fall back to synthesising 'Group N' from move_groups so the MOP still renders on an older or
    minimal snapshot."""
    mr = snap.get("migration_readiness") or []
    if mr:
        return [(r.get("group") or f"Group {i + 1}", list(r.get("switches") or []))
                for i, r in enumerate(mr)]
    return [(f"Group {i + 1}", list(g.get("switches") or []))
            for i, g in enumerate(snap.get("move_groups") or [])]


def write_mop_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the per-wave Method of Procedure (.docx) to `output_path`. Fail-soft: a missing python-docx
    is a warning + skip; any unexpected render error is logged, never raised."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.shared import Pt, RGBColor, Inches
    except ImportError:
        logger.warning("  MOP (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the Method-of-Procedure deliverable).")
        return

    snap = snap_dict or {}
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

    def steps(items):
        for s in items:
            doc.add_paragraph(s, style="List Number")

    # ---- snapshot-derived facts ----
    devices = snap.get("devices") or {}
    waves = _waves(snap)
    readiness_by_group = {r.get("group"): r for r in (snap.get("migration_readiness") or [])}
    seq_by_group = {r.get("group"): r for r in (snap.get("wave_sequencing") or [])}
    scen_by_group = {r.get("group"): r
                     for r in ((snap.get("migration_scenarios") or {}).get("per_group") or [])}
    val_by_wave = (snap.get("validation_plan") or {}).get("by_wave") or {}
    fi_by_host = {r.get("host"): r for r in (snap.get("failure_impact") or [])}
    rem_items = (snap.get("remediation_plan") or {}).get("items") or []
    punchlist = snap.get("punchlist") or []

    def _blockers_for(switches):
        sw = set(switches)
        # high-severity remediation snippets that touch this wave's devices
        rem = [it for it in rem_items if it.get("device") in sw
               and _SEV_RANK.get(it.get("severity"), 4) <= 1]
        # critical/high punch-list items that touch this wave's devices
        pl = [i for i in punchlist if _SEV_RANK.get(i.get("severity"), 4) <= 1
              and (set(i.get("devices") or []) & sw)]
        return rem, pl

    # ---- title page ----
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Migration Method of Procedure (MOP)"); tr.bold = True
    tr.font.size = Pt(26); tr.font.color.rgb = NAVY
    sub2 = doc.add_paragraph(); sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s2 = sub2.add_run("Per-wave maintenance-window cutover procedure")
    s2.font.size = Pt(14); s2.font.color.rgb = GREY
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(label); sr.font.size = Pt(13); sr.font.color.rgb = GREY
    meta = doc.add_paragraph(); meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{len(waves)} wave(s)  ·  {len(devices)} devices  ·  script {snap.get('script_version', '')}"
                 ).font.color.rgb = GREY
    status = doc.add_paragraph(); status.alignment = WD_ALIGN_PARAGRAPH.CENTER
    st = status.add_run("DRAFT TEMPLATE — fill every <placeholder>, peer-review, and dry-run before any window.")
    st.italic = True; st.font.color.rgb = RED
    doc.add_paragraph()
    note = doc.add_paragraph()
    _label_run(note, "How to use this MOP:",
               "This is a change template primed with the assessment evidence, NOT an auto-executed "
               "change. Each wave below is one maintenance window. Work top to bottom: clear the wave's "
               "blockers, capture the pre-cutover baseline, run the procedure, then PROVE the wave with "
               "the post-cutover validation checks — and only proceed to the next wave once they pass. "
               "If any validation check fails and cannot be corrected within the window, execute the "
               "rollback. Every <placeholder> (date, owner, approver, exact uplinks) must be completed "
               "by the implementing engineer.", GREY)
    doc.add_page_break()

    # ---- table of contents ----
    doc.add_heading("Contents", level=1)
    toc_p = doc.add_paragraph(); run = toc_p.add_run()
    fb = OxmlElement("w:fldChar"); fb.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = r'TOC \o "1-2" \h \z \u'
    fs = OxmlElement("w:fldChar"); fs.set(qn("w:fldCharType"), "separate")
    ft = OxmlElement("w:t"); ft.text = "Right-click → Update Field to build the table of contents."
    fe = OxmlElement("w:fldChar"); fe.set(qn("w:fldCharType"), "end")
    for el in (fb, instr, fs, ft, fe):
        run._r.append(el)
    doc.add_page_break()

    # ===== 1. Change overview =====
    doc.add_heading("1. Change Overview", level=1)
    doc.add_paragraph(
        f"This migration is sequenced into {len(waves)} wave(s) (move groups), each cut over in its own "
        "maintenance window. The recommended order is: clear all blocking items first, then cut the "
        "lower-risk waves to build confidence, protecting the highest-blast-radius (keystone) devices.")
    ov_rows = []
    for name, switches in waves:
        r = readiness_by_group.get(name, {})
        seq = seq_by_group.get(name, {})
        blast = max((int(fi_by_host.get(s, {}).get("stranded") or 0) for s in switches), default=0)
        rem, pl = _blockers_for(switches)
        ov_rows.append((name, len(switches), r.get("endpoints", "—"),
                        r.get("readiness", "—"), seq.get("sequence", "—"), blast, len(rem) + len(pl)))
    table(["Wave", "Devices", "Endpoints", "Readiness", "Strategy", "Max blast", "Blockers"],
          ov_rows, widths=[1.5, 0.8, 1.0, 1.2, 1.5, 0.9, 0.9])

    fleet_rec = (snap.get("migration_scenarios") or {}).get("fleet_recommendation")
    if fleet_rec:
        _label_run(doc.add_paragraph(), "Fleet-level recommendation:", fleet_rec)

    # ===== 2. Global prerequisites =====
    doc.add_heading("2. Global Prerequisites (before any window)", level=1)
    doc.add_paragraph(
        "Complete these once, before the first wave. They are the fleet-wide gating items the assessment "
        "flagged; cutting over before they are resolved or risk-accepted carries the documented risk.")
    gating = (snap.get("executive_brief") or {}).get("top_gating") or []
    if gating:
        for g in gating[:6]:
            doc.add_paragraph(g, style="List Bullet")
    steps([
        "Confirm the assessment workbook, runbook and this MOP are the agreed change record, and that "
        "the change ticket <CHG-NUMBER> references them.",
        "Obtain change-advisory-board approval and a signed maintenance window per wave "
        "(<DATE/TIME>, owner <NAME>, approver <NAME>).",
        "Verify out-of-band/console access to every device in scope, and that current configurations "
        "are backed up off-box (golden snapshot).",
        "Stage and peer-review the remediation/config snippets from the Remediation Plan for each wave's "
        "blockers (review-only — do not paste un-reviewed).",
        "Brief the war room: roles, the rollback decision-maker, and the go/no-go criteria (the "
        "post-cutover validation must pass).",
    ])

    # ===== per-wave sections =====
    for wi, (name, switches) in enumerate(waves, start=3):
        r = readiness_by_group.get(name, {})
        seq = seq_by_group.get(name, {})
        scen = scen_by_group.get(name, {})
        playbook = scen.get("playbook") or {}
        rem, pl = _blockers_for(switches)
        blast = max((int(fi_by_host.get(s, {}).get("stranded") or 0) for s in switches), default=0)
        verdict = r.get("readiness", "—")

        doc.add_heading(f"{wi}. MOP — {name}", level=1)

        # 2.x.1 scope
        doc.add_heading(f"{wi}.1 Scope & risk", level=2)
        table(["Field", "Value"], [
            ("Devices in scope", ", ".join(switches) or "—"),
            ("Endpoints affected", r.get("endpoints", "—")),
            ("Readiness verdict", verdict),
            ("Blocking / warning checks", f"{r.get('n_fail', 0)} / {r.get('n_warn', 0)}"),
            ("Cutover strategy", seq.get("sequence", scen.get("recommended_scenario", "—"))),
            ("Max blast radius (endpoints stranded if a device is lost mid-move)", blast),
            ("Maintenance window", "<DATE> <START>–<END>  ·  owner <NAME>  ·  approver <NAME>"),
            ("Rollback decision time", "<HH:MM> — if validation has not passed by this time, roll back"),
        ], widths=[2.6, 4.2])
        if scen.get("rationale"):
            _label_run(doc.add_paragraph(), "Why this strategy:", scen.get("rationale"))

        # 2.x.2 blockers to clear first
        doc.add_heading(f"{wi}.2 Blockers to clear before this window", level=2)
        if not rem and not pl:
            doc.add_paragraph("No Critical/High blockers attributed to this wave's devices. Proceed once "
                              "the global prerequisites are met.")
        else:
            if pl:
                table(["Severity", "Category", "Item", "Devices"],
                      [(i.get("severity"), i.get("category") or "—", i.get("title") or "—",
                        ", ".join(str(x) for x in (i.get("devices") or []) if x in set(switches)))
                       for i in pl[:10]], widths=[0.9, 1.3, 3.0, 1.6])
            for it in rem[:8]:
                p = doc.add_paragraph()
                _label_run(p, f"{it.get('device')} — {it.get('title') or it.get('source') or 'fix'}"
                              f" ({it.get('severity', '—')}):",
                           it.get("why") or "review-only config change; see the Remediation Plan sheet.")
                for c in (it.get("commands") or [])[:8]:
                    doc.add_paragraph(c, style="List Bullet")

        # 2.x.3 pre-cutover baseline capture
        doc.add_heading(f"{wi}.3 Pre-cutover baseline capture", level=2)
        doc.add_paragraph(
            "Capture and SAVE the output of these commands before any change, so 'good' is defined by "
            "the pre-change state and the post-cutover checks have a baseline to compare against.")
        val_items = val_by_wave.get(name) or []
        cap_cmds = []
        seen_cap = set()
        for it in val_items:
            dev, cmd = it.get("device"), it.get("command")
            if cmd and (dev, cmd) not in seen_cap:
                seen_cap.add((dev, cmd))
                cap_cmds.append((dev, cmd))
        if cap_cmds:
            table(["Device", "Command to capture"], cap_cmds[:20], widths=[1.8, 4.6])
        else:
            steps([f"On each of {', '.join(switches) or 'the wave devices'}: capture "
                   "'show running-config', 'show ip interface brief', 'show cdp neighbors', "
                   "'show spanning-tree summary', and (if L3) 'show ip route' / 'show standby brief'."])

        # 2.x.4 procedure
        doc.add_heading(f"{wi}.4 Cutover procedure", level=2)
        strategy = (seq.get("sequence") or scen.get("recommended_scenario") or "").lower()
        proc = ["Open the change window and announce start in the war room; confirm rollback owner is present."]
        if playbook.get("pre"):
            proc.append("Preparation: " + playbook["pre"].rstrip(". ") + ".")
        if "make-before-break" in strategy or "parallel" in strategy:
            proc += [
                "Build the new/target path BESIDE the existing one (do not remove the legacy path yet): "
                "stage the target device config and bring up the new uplinks <list exact interfaces>.",
                "Verify the new path forwards in isolation (link up, STP/trunk consistent, gateway "
                "reachable) before moving any production load.",
                "Migrate endpoints leg-by-leg / VLAN-by-VLAN onto the new path, validating after each "
                "increment; keep the legacy leg as the live fallback.",
                "Once all load is on the new path and validated, decommission the legacy path.",
            ]
        else:  # hard cutover
            proc += [
                "Announce the hard cutover; this wave has a brief outage for the moved endpoints.",
                "Apply the staged target configuration to <devices>; move the uplinks/endpoints "
                "<list exact interfaces> from legacy to target.",
                "Bring up the target links and confirm STP converges and trunks negotiate as expected.",
            ]
        if playbook.get("validate"):
            proc.append("In-window validation: " + playbook["validate"].rstrip(". ") + ".")
        proc.append("Run §" + f"{wi}.5 post-cutover validation in full before declaring the wave complete.")
        steps(proc)

        # 2.x.5 post-cutover validation (reuse the existing validation plan)
        doc.add_heading(f"{wi}.5 Post-cutover validation (go/no-go)", level=2)
        if val_items:
            doc.add_paragraph("Every check must pass. A failure that cannot be corrected in-window "
                              "triggers the rollback in §" + f"{wi}.6.")
            table(["Category", "Device", "Check", "Command", "Expected (good) result"],
                  [(it.get("category"), it.get("device"), it.get("check"),
                    it.get("command"), it.get("expect")) for it in val_items[:40]],
                  widths=[1.0, 1.0, 1.7, 1.5, 1.6])
            if len(val_items) > 40:
                doc.add_paragraph(f"… and {len(val_items) - 40} more check(s); full set in the Cutover "
                                  "Validation workbook sheet.")
        else:
            doc.add_paragraph("No machine-generated validation checks for this wave. As a minimum, verify "
                              "gateway reachability (ping the SVI/HSRP vIP), FHRP roles, routing "
                              "adjacencies, STP root, and port-channel membership are unchanged from the "
                              "§" + f"{wi}.3 baseline.")

        # 2.x.6 rollback
        doc.add_heading(f"{wi}.6 Rollback", level=2)
        rb = ["Declare rollback in the war room and record the trigger (which validation check failed)."]
        if playbook.get("rollback"):
            rb.append("Strategy-specific: " + playbook["rollback"].rstrip(". ") + ".")
        if "make-before-break" in strategy or "parallel" in strategy:
            rb.append("Move any migrated endpoints back onto the still-live legacy leg; remove the "
                      "new path. Because the legacy path was never torn down, this is non-disruptive.")
        else:
            rb.append("Re-apply the pre-change configuration captured in §" + f"{wi}.3 to <devices>; "
                      "move uplinks/endpoints back to the legacy ports.")
        rb.append("Re-run the §" + f"{wi}.5 checks against the legacy path to confirm service is restored, "
                  "then close the window as rolled-back and schedule a retro.")
        steps(rb)

        # 2.x.7 sign-off
        doc.add_heading(f"{wi}.7 Sign-off", level=2)
        table(["Role", "Name", "Time", "Result (proceed / rolled-back)"],
              [("Implementing engineer", "", "", ""),
               ("Validation / war-room lead", "", "", ""),
               ("Change owner", "", "", "")], widths=[2.2, 1.8, 1.2, 1.6])

    # ===== final acceptance =====
    doc.add_heading(f"{len(waves) + 3}. Post-Migration Acceptance", level=1)
    doc.add_paragraph(
        "The migration is complete when every wave above has been cut over and its validation passed, "
        "the consolidated punch-list has no open Critical/High item, and a final fleet re-assessment "
        "(re-run this toolkit and compare via the campaign-trend report) confirms the target-state "
        "health bands. Record the final sign-off and archive the per-wave evidence.")

    n_sections = len([p for p in doc.paragraphs if p.style.name == "Heading 1"])
    doc.save(output_path)
    logger.info(f"[Phase 34] MOP (DOCX) written: {output_path} ({len(waves)} wave(s), {n_sections} sections)")
