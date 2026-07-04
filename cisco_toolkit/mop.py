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

from cisco_toolkit.docmeta import add_acceptance, add_document_control, add_excellence_front, add_glossary, add_inputs_required, add_table, add_toc
from cisco_toolkit.docmeta import as_dict as _as_dict, as_list as _as_list
from cisco_toolkit.textutils import xml_safe, xml_safe_deep   # entry deep-sanitize of device text (audit-5)

logger = logging.getLogger(__name__)

_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _waves(snap: dict):
    """Resolve the ordered list of migration waves as (name, switches[]) pairs. Prefer the
    migration_readiness verdict rows (they carry the group name + switch set the validation plan keys
    on); fall back to synthesising 'Group N' from move_groups so the MOP still renders on an older or
    minimal snapshot."""
    mr = [_as_dict(r) for r in _as_list(snap.get("migration_readiness"))]
    if mr:
        return [(r.get("group") or f"Group {i + 1}", list(_as_list(r.get("switches"))))
                for i, r in enumerate(mr)]
    return [(f"Group {i + 1}", list(_as_list(_as_dict(g).get("switches"))))
            for i, g in enumerate(_as_list(snap.get("move_groups")))]


def _wave_sections(snap: dict):
    """Per-WAVE section descriptors keyed on the canonical design_blueprint.target_state.wave_plan (one
    MOP section per candidate wave). Each wave resolves its per-group records by SWITCH-MEMBERSHIP, never
    by index (wave_plan.source_groups is a filtered/0-based index while the readiness groups are raw/
    1-based -- joining by index would misattribute checks). Falls back to _waves() (one section per
    move-group) when wave_plan is absent, so older/minimal snapshots still render unchanged.
    Returns (name, switches, kind, group_names)."""
    wp = _as_dict(_as_dict(_as_dict(snap.get("design_blueprint")).get("target_state")).get("wave_plan"))
    waves = _as_list(wp.get("waves"))
    if not waves:
        return [(name, switches, "move-group", [name]) for name, switches in _waves(snap)]
    sw2grp = {}
    for r in _as_list(snap.get("migration_readiness")):
        r = _as_dict(r)
        g = r.get("group")
        for s in _as_list(r.get("switches")):
            sw2grp.setdefault(s, g)
    out = []
    for w in waves:
        w = _as_dict(w)
        switches = list(_as_list(w.get("switches")))
        kind = w.get("kind") or "wave"
        gnames = []
        for s in switches:
            g = sw2grp.get(s)
            if g and g not in gnames:
                gnames.append(g)
        out.append((f"Wave {w.get('wave')} ({kind})", switches, kind, gnames))
    return out


def _join_group_records(gnames, wave_switches, readiness_by_group, seq_by_group, scen_by_group, val_by_wave):
    """Union the per-group records across the groups a wave's switches belong to (a coupled-subwave maps to
    one group; an independent-batch maps to many): worst readiness verdict, fail/warn checks, first
    non-empty sequencing/scenario, deduped validation checks. Endpoints are APPORTIONED to this wave's
    switch-share of each group -- a sub-wave is a SLICE, so it must not inherit the parent group's full
    endpoint total. Single source of truth -- reads the engine's records, never recomputes them."""
    # Rank the engine's ACTUAL readiness vocabulary -- analyze.compute_migration_readiness emits exactly
    # {"NOT READY","CAUTION","READY"}. Lower = worse, so the reduce below keeps the worst verdict; an
    # unknown value defaults high (least-worst) and never masks a real NOT READY.
    rank = {"not ready": 0, "caution": 1, "ready": 2}

    def _i(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return 0

    r = {"endpoints": 0, "n_fail": 0, "n_warn": 0, "readiness": None}
    seq, scen, val_items, worst, seen = {}, {}, [], None, set()
    mbb_all, hard_all = [], []   # cutover host split UNIONED across every group in the wave (not just the first)
    wsw = set(wave_switches or [])
    for g in gnames:
        rr = readiness_by_group.get(g) or {}
        gsw = rr.get("switches") or []
        share = (len(wsw & set(gsw)) / len(gsw)) if gsw else 1.0      # a sub-wave is a SLICE -> apportion its switch-share
        r["endpoints"] += round(_i(rr.get("endpoints")) * share)   # endpoints ARE divisible -> apportion by share
        # n_fail/n_warn: ATTRIBUTE each fail/warn check to the ONE sub-wave that owns its canonical (lowest-sorted)
        # member switch, so the per-sub-wave counts SUM to the group SSOT. The old share-with-floor reprinted a
        # 'max(.,1)' on every slice, so an N-way split of a positive count summed toward N (AJ Group 1's true 3/4
        # rendered 7/7 across 7 sub-waves) -- a one-source-of-truth break vs migration_readiness (audit-2 #3).
        checks = [c for c in (rr.get("checks") or [])
                  if isinstance(c, dict) and str(c.get("status", "")).lower() in ("fail", "warn")]
        if checks:
            gsw_set = set(gsw)
            for chk in checks:
                note = str(chk.get("note", ""))
                members = sorted(s for s in gsw_set if s and s in note)   # group switches named in this check's note
                owner = members[0] if members else (sorted(gsw)[0] if gsw else None)   # canonical single owner
                if owner is not None and owner in wsw:                    # this sub-wave owns the check
                    r["n_fail" if str(chk.get("status")).lower() == "fail" else "n_warn"] += 1
        else:
            # older snapshot with no per-check attribution -> apportion by switch-share, never rounding a lone
            # blocker DOWN to 0 (that would mask a NOT-READY wave's gate). Single-slice correctness preserved.
            _ef, _ew = _i(rr.get("n_fail")) * share, _i(rr.get("n_warn")) * share
            r["n_fail"] += max(round(_ef), 1) if _ef > 0 else 0
            r["n_warn"] += max(round(_ew), 1) if _ew > 0 else 0
        rd = rr.get("readiness")
        if rd and (worst is None or rank.get(str(rd).lower(), 9) < rank.get(str(worst).lower(), 9)):
            worst = rd
        gseq = seq_by_group.get(g) or {}
        if not seq:
            seq = gseq
        for _h in (gseq.get("make_before_break") or []):
            if _h not in mbb_all:
                mbb_all.append(_h)
        for _h in (gseq.get("hard_cutover") or []):
            if _h not in hard_all:
                hard_all.append(_h)
        if not scen:
            scen = scen_by_group.get(g) or {}
        for v in (val_by_wave.get(g) or []):
            key = (v.get("device"), v.get("command")) if isinstance(v, dict) else str(v)
            if key not in seen:
                seen.add(key)
                val_items.append(v)
    r["readiness"] = worst or "—"
    # Overlay the UNIONED cutover host split so the procedure branches on the WHOLE wave, not just the
    # representative group (the free-text 'sequence' stays the representative's — descriptive only). Copy
    # so the engine's record is never mutated (this joiner reads the engine's records, never recomputes).
    if seq:
        seq = {**seq, "make_before_break": mbb_all, "hard_cutover": hard_all}
    return r, seq, scen, val_items


def write_mop_docx(output_path: str, snap_dict: dict, label: str) -> None:
    """Emit the per-wave Method of Procedure (.docx) to `output_path`. Fail-soft: a missing python-docx
    is a warning + skip; any unexpected render error is logged, never raised."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor
    except ImportError:
        logger.warning("  MOP (DOCX) skipped: python-docx not installed "
                       "(pip install python-docx to enable the Method-of-Procedure deliverable).")
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
        # Delegates to the family's single table builder (docmeta.add_table) — V3.23.152 dedup.
        return add_table(doc, headers, rows, widths, fixed=False)

    def steps(items):
        # Manual numbering rather than Word's built-in "List Number" style: that style's single shared
        # numbering definition makes numbers CONTINUE across every list block in the document, so a wave's
        # procedure and rollback (and the next wave's procedure) would not restart at 1. Explicit prefixes
        # restart per call and render identically in every viewer.
        # An item may be a plain string, or an (action, success_criterion) tuple — the MOP definition in
        # the AS migration service is steps + precautions + SUCCESS CRITERIA per step (V3.23.155).
        for i, s in enumerate(items, 1):
            if isinstance(s, tuple):
                action, success = s
                p = doc.add_paragraph(f"{i}. {action}")
                if success:
                    r = p.add_run("  Success: " + success)
                    r.bold = True
                    r.font.color.rgb = NAVY
            else:
                doc.add_paragraph(f"{i}. {s}")

    # ---- snapshot-derived facts ----
    # Shared coercers (not `or {}`/`or []`, which do NOT guard a truthy non-dict/list) so a malformed
    # uploaded snapshot -- where a section that should be a list is an object, etc. -- degrades instead of
    # char-iterating or raising AttributeError mid-render (matching engagement/ops/archreview).
    devices = _as_dict(snap.get("devices"))
    waves = _wave_sections(snap)
    readiness_by_group = {d.get("group"): d for d in (_as_dict(r) for r in _as_list(snap.get("migration_readiness")))}
    seq_by_group = {d.get("group"): d for d in (_as_dict(r) for r in _as_list(snap.get("wave_sequencing")))}
    scen_by_group = {d.get("group"): d
                     for d in (_as_dict(r) for r in _as_list(_as_dict(snap.get("migration_scenarios")).get("per_group")))}
    val_by_wave = _as_dict(_as_dict(snap.get("validation_plan")).get("by_wave"))
    fi_by_host = {d.get("host"): d for d in (_as_dict(r) for r in _as_list(snap.get("failure_impact")))}
    rem_items = [_as_dict(r) for r in _as_list(_as_dict(snap.get("remediation_plan")).get("items"))]
    punchlist = [_as_dict(r) for r in _as_list(snap.get("punchlist"))]

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
    _ninv = _as_dict(_as_dict(snap.get("executive_brief")).get("scale")).get("n_devices")   # canonical inventoried (SSOT owner); len() only pre-brief (CROSS-04)
    meta.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                 f"{len(waves)} wave(s)  ·  {_ninv if isinstance(_ninv, int) else len(devices)} devices  ·  script {snap.get('script_version', '')}"
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

    # ---- document control (AS-style front matter; unnumbered so the wave sections are untouched) ----
    add_document_control(
        doc, document="Migration Method of Procedure (MOP)", label=label,
        engine_version=str(snap.get("script_version", "")), generated_at=snap.get("generated_at"),
        collected_at=snap.get("collected_at"),
        audience="The implementing engineer(s) executing each maintenance window, the validation / "
                 "war-room lead, and the change manager approving the windows.",
        exclude=("mop",),
        extra_assumptions=(
            "“Ready for service” for a wave means the environment functions as per the "
            "post-cutover validation checks documented in that wave's section — acceptance criteria "
            "live in this MOP, not in a separate test document.",))
    doc.add_page_break()

    # ---- table of contents (shared field-code helper, V3.23.171) ----
    add_toc(doc)


    # Deliverable Excellence (DE-01): answer-first at-a-glance register + single-source-of-truth signal.
    add_excellence_front(doc, snap_dict)
    # Deliverable Excellence (DE-01): consolidated Inputs-Required register (Law 9).
    add_inputs_required(doc, snap_dict)
    # ===== 1. Change overview =====
    doc.add_heading("1. Change Overview", level=1)
    doc.add_paragraph(
        f"This migration is sequenced into {len(waves)} candidate wave(s) (right-sized from the L2-coupling "
        "move-groups), each cut over in its own maintenance window. The recommended order is: clear all "
        "blocking items first, then cut the lower-risk waves to build confidence, protecting the "
        "highest-blast-radius (keystone) devices.")
    ov_rows = []
    for name, switches, _kind, _gnames in waves:
        r, seq, _scen, _vi = _join_group_records(_gnames, switches, readiness_by_group, seq_by_group,
                                                 scen_by_group, val_by_wave)
        blast = max((int(fi_by_host.get(s, {}).get("stranded") or 0) for s in switches), default=0)
        rem, pl = _blockers_for(switches)
        ov_rows.append((name, len(switches), r.get("endpoints", "—"),
                        r.get("readiness", "—"), seq.get("sequence", "—"), blast, len(rem) + len(pl)))
    table(["Wave", "Devices", "Endpoint MACs", "Readiness", "Strategy", "Max blast", "Blockers"],
          ov_rows, widths=[1.5, 0.8, 1.0, 1.2, 1.5, 0.9, 0.9])

    fleet_rec = _as_dict(snap.get("migration_scenarios")).get("fleet_recommendation")
    if fleet_rec:
        _label_run(doc.add_paragraph(), "Fleet-level recommendation:", fleet_rec)

    # ===== 2. Global prerequisites =====
    doc.add_heading("2. Global Prerequisites (before any window)", level=1)
    doc.add_paragraph(
        "Complete these once, before the first wave. They are the fleet-wide gating items the assessment "
        "flagged; cutting over before they are resolved or risk-accepted carries the documented risk.")
    gating = _as_list(_as_dict(snap.get("executive_brief")).get("top_gating"))
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

    # 2.1 responsibilities — the AS migration-service ownership split, stated up front
    doc.add_heading("2.1 Responsibilities (RACI)", level=2)
    doc.add_paragraph(
        "Ownership follows the standard AS migration-service split: the delivery engineer prepares "
        "the MOP, mappings and pre/post checks; the customer's team executes the steps in the window "
        "and owns the key in-window decisions. Adjust names per the engagement before approval.")
    table(["Activity", "Responsible", "Notes"], [
        ("MOP preparation, port mapping & staged configuration", "Delivery engineer (author)",
         "Reviewed and approved by the customer network owner"),
        ("Pre/post check definition & baseline capture", "Delivery engineer (author)",
         "From the assessment's validation plan — one source of truth"),
        ("Change approval & window scheduling", "Customer change manager",
         "Via the customer's change-advisory process"),
        ("In-window execution of each step", "Customer operations / implementing engineer",
         "Delivery engineer advises; steps are executed exactly as written"),
        ("Go/no-go and rollback decision", "Customer network owner (change owner)",
         "At the rollback decision time stated in each wave's scope table"),
        ("Validation evidence & sign-off records", "Validation / war-room lead",
         "Archived with the post-implementation review"),
    ], widths=[2.6, 2.0, 2.2])

    # §2.2 EVPN-migration guardrails — gated, evidence-grounded brownfield->NX-OS-VXLAN-EVPN cutover doctrine.
    # Silent unless a VXLAN-EVPN fabric is the target; renders the load-bearing, primary-source migration
    # gotchas (NX-OS 10.2(3) HSRP/DAG gate, the gateway-vMAC pre-step, single-active-L2-interconnect loop
    # safety, the vPC back-to-back method, rollback triggers) grounded in the fleet's OWN observed evidence.
    evpn = _as_dict(_as_dict(snap.get("design_blueprint")).get("evpn_migration"))
    evpn_on = bool(evpn.get("applicable"))
    if evpn_on:
        doc.add_heading("2.2 EVPN-migration guardrails (brownfield → NX-OS VXLAN-EVPN)", level=2)
        doc.add_paragraph(
            f"The target fabric is NX-OS VXLAN BGP-EVPN ({evpn.get('model_basis', '')}). These migration "
            "guardrails are grounded in this fleet's own evidence and documented in primary Cisco sources; "
            "each is an easily-missed cutover failure mode that must be satisfied — or explicitly "
            "risk-accepted — before the relevant wave.")
        table(["Guardrail", "Phase", "Severity", "Basis (observed) & action — [source]"],
              [(g.get("title", ""), g.get("phase", ""), g.get("severity", ""),
                f"{g.get('basis', '')} — {g.get('detail', '')} [{g.get('source', '')}]")
               for g in _as_list(evpn.get("guardrails")) if isinstance(g, dict)],
              widths=[1.7, 0.9, 0.8, 3.4])

    # §2.3/§2.2 software / image standardization (per in-scope platform) — N24 (number follows the EVPN subsection)
    swrisk_pd = [d for d in _as_list(_as_dict(snap.get("software_risk")).get("per_device")) if isinstance(d, dict)]
    if swrisk_pd:
        doc.add_heading(f"{'2.3' if evpn_on else '2.2'} Software / image standardization", level=2)
        doc.add_paragraph(
            "Before any wave, agree the target NOS image per platform. The current software trains and their "
            "disposition (from the software-advisory screening) are below; the target image is selected at "
            "detailed design and applied + verified per wave in the staged config and post-cutover checks.")
        agg: dict = {}
        for d in swrisk_pd:
            key = (str(d.get("platform") or "—"), str(d.get("train") or "—"), str(d.get("train_band") or "—"))
            agg[key] = agg.get(key, 0) + 1
        rows = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
        table(["Platform", "Current train", "Disposition", "Devices", "Target image"],
              [(p, tr, band, n, "<confirm>") for (p, tr, band), n in rows][:30],
              widths=[1.0, 1.5, 1.6, 0.7, 1.4])

    # ===== per-wave sections =====
    for wi, (name, switches, _kind, _gnames) in enumerate(waves, start=3):
        r, seq, scen, _val_items = _join_group_records(_gnames, switches, readiness_by_group, seq_by_group,
                                                       scen_by_group, val_by_wave)
        playbook = scen.get("playbook") or {}
        rem, pl = _blockers_for(switches)
        blast = max((int(fi_by_host.get(s, {}).get("stranded") or 0) for s in switches), default=0)
        verdict = r.get("readiness", "—")

        # The constituent move-groups this wave covers (a coupled-subwave maps to ONE group; an
        # independent-batch may bundle MANY). Each keeps its own strategy/rationale/rollback -- surface
        # every one, never just the first (the joiner picks a representative seq/scen, but the document
        # must not silently drop the siblings').
        wave_groups = [(g, scen_by_group.get(g) or {}, seq_by_group.get(g) or {}) for g in _gnames]
        wave_groups = [(g, sc, sq) for g, sc, sq in wave_groups if sc or sq]
        multi = len(wave_groups) > 1
        if multi:
            strat_cell = "; ".join(dict.fromkeys(
                (sq.get("sequence") or sc.get("recommended_scenario") or "").strip()
                for _g, sc, sq in wave_groups if (sq.get("sequence") or sc.get("recommended_scenario")))) or "—"
        else:
            strat_cell = seq.get("sequence") or scen.get("recommended_scenario") or "—"

        doc.add_heading(f"{wi}. MOP — {name}", level=1)

        # 2.x.1 scope
        doc.add_heading(f"{wi}.1 Scope & risk", level=2)
        table(["Field", "Value"], [
            ("Devices in scope", ", ".join(switches) or "—"),
            ("Endpoint MACs (apportioned)", r.get("endpoints", "—")),
            ("Readiness verdict", verdict),
            ("Blocking / warning checks", f"{r.get('n_fail', 0)} / {r.get('n_warn', 0)}"),
            ("Cutover strategy", strat_cell),
            ("Max blast radius (endpoints stranded if a device is lost mid-move)", blast),
            ("Maintenance window", "<DATE> <START>–<END>  ·  owner <NAME>  ·  approver <NAME>"),
            ("Rollback decision time", "<HH:MM> — if validation has not passed by this time, roll back"),
        ], widths=[2.6, 4.2])
        if multi:
            doc.add_paragraph(
                "This wave bundles several INDEPENDENT move-groups (they share no VLANs, so they may be "
                "cut in any order within the window — but each must pass its own validation before the "
                "next). Each keeps its own strategy and rollback:")
            table(["Move-group", "Strategy", "Why"],
                  [(g, (sq.get("sequence") or sc.get("recommended_scenario") or "—"),
                    sc.get("rationale") or "—") for g, sc, sq in wave_groups], widths=[1.4, 1.8, 3.6])
        elif scen.get("rationale"):
            _label_run(doc.add_paragraph(), "Why this strategy:", scen.get("rationale"))
        if _kind == "coupled-subwave":
            _label_run(doc.add_paragraph(), "Shared-L2 coordination (coupled sub-wave):",
                       "this wave is one slice of an oversized L2-coupled move-group; the sub-waves SHARE "
                       "VLANs, so they are a SEQUENCE (order matters), not independent cutovers. Keep the "
                       "shared VLANs trunked/extended across the sibling sub-waves until the whole group "
                       "is migrated; STP root, FHRP active and trunk allowed-VLAN lists are NOT independent "
                       "of the siblings.", RED)

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
        val_items = _val_items
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

        # 2.x.4 port / interface mapping & staged configuration (AS migration-service deliverable)
        doc.add_heading(f"{wi}.4 Port / interface mapping & staged configuration", level=2)
        doc.add_paragraph(
            "The MOP carries the physical port/interface mapping and the staged (converted) "
            "configuration — the legacy side is read from the collected evidence; every <target> "
            "column must be completed by the implementing engineer before the window.")
        map_rows = []
        ifaces_all = _as_dict(snap.get("interfaces"))
        for h in switches:
            for pname, dd in sorted((ifaces_all.get(h) or {}).items()):
                dd = dd or {}
                mode = (dd.get("switchport_mode") or "").lower()
                if mode == "access" and ((dd.get("end_host_mac") or "").strip()
                                         or (dd.get("end_host_ip") or "").strip()):
                    kind = "Endpoint"
                elif mode == "trunk" and (dd.get("cdp_neighbor") or "").strip():
                    po = (dd.get("port_channel") or "").strip()
                    # surface bundle membership so redundant uplink pairs (two ports sharing a Po) are explicit
                    kind = f"Uplink → {dd.get('cdp_neighbor')}" + (f" [{po}]" if po else "")
                else:
                    continue
                map_rows.append((h, pname, kind, dd.get("vlan") or "—",
                                 (dd.get("description") or dd.get("endpoint_type") or "—"),
                                 "<target device>", "<target port>"))
        if map_rows:
            table(["Legacy device", "Port", "Role", "VLAN", "Description / endpoint",
                   "Target device", "Target port"],
                  map_rows[:30], widths=[1.0, 0.8, 1.2, 0.5, 1.4, 1.0, 0.9])
            if len(map_rows) > 30:
                doc.add_paragraph(f"… and {len(map_rows) - 30} more port(s); the full per-port "
                                  "inventory is in the workbook's interface sheets.")
            stub_by_host: dict = {}
            for h, pname, kind, v, desc, *_ in map_rows:
                if kind == "Endpoint" and v != "—":
                    stub_by_host.setdefault(h, []).append((pname, v, desc))
            if stub_by_host:
                doc.add_paragraph(
                    "Staged endpoint-port configuration, derived from the evidence (mode/VLAN/"
                    "description only — review, complete and peer-review before any use):")
                for h in sorted(stub_by_host)[:2]:
                    lines = [f"! {h} — staged endpoint-port config (evidence-derived)"]
                    for pname, v, desc in stub_by_host[h][:6]:
                        lines.append(f"interface <target port for {pname}>")
                        if desc != "—":
                            lines.append(f" description {desc}")
                        lines += [" switchport mode access", f" switchport access vlan {v}", "!"]
                    cp = doc.add_paragraph()
                    cr = cp.add_run("\n".join(lines))
                    cr.font.name = "Consolas"; cr.font.size = Pt(9)
        else:
            doc.add_paragraph("No endpoint or uplink port evidence for this wave's devices in the "
                              "snapshot — build the mapping from a fresh interface collection before "
                              "the window.")

        # 2.x.5 procedure (each step carries its success criterion — the MOP definition)
        doc.add_heading(f"{wi}.5 Cutover procedure", level=2)
        proc = [("Open the change window and announce start in the war room; confirm rollback owner "
                 "is present.",
                 "roles confirmed; the rollback decision time in §" + f"{wi}.1 is agreed.")]
        if playbook.get("pre"):
            proc.append(("Preparation: " + playbook["pre"].rstrip(". ") + ".",
                         "staging complete with no production-facing change."))
        # classify off the engine's STRUCTURED dual-homed/single-homed split, NOT the free-text 'sequence'
        # (which for a mixed wave reads "...hard cutover (single-homed) + ...make-before-break (dual-homed)" —
        # the old substring match flipped the WHOLE wave to make-before-break, applying "keep the legacy leg
        # as the live fallback" steps to single-homed switches that have NO second path). Make-before-break
        # is the procedure ONLY when every member is dual-homed; any single-homed member -> hard-cutover flow.
        mbb_hosts, hard_hosts = (seq.get("make_before_break") or []), (seq.get("hard_cutover") or [])
        if mbb_hosts and not hard_hosts:
            proc += [
                ("Build the new/target path BESIDE the existing one (do not remove the legacy path "
                 "yet): stage the target device config and bring up the new uplinks per the §"
                 f"{wi}.4 mapping.",
                 "target links up; no STP topology change on the legacy path."),
                ("Verify the new path forwards in isolation (link up, STP/trunk consistent, gateway "
                 "reachable) before moving any production load.",
                 "isolation checks pass on the target path before any endpoint moves."),
                ("Migrate endpoints leg-by-leg / VLAN-by-VLAN onto the new path, validating after "
                 "each increment; keep the legacy leg as the live fallback.",
                 "each increment re-homes and passes its checks before the next one moves."),
                ("Once all load is on the new path and validated, decommission the legacy path.",
                 "no endpoint remains on the legacy leg (MAC/ARP tables clean)."),
            ]
        else:  # any single-homed member present (mixed or pure single-homed) -> scheduled-outage flow
            if mbb_hosts and hard_hosts:   # MIXED: do the dual-homed make-before-break FIRST, then the outage
                proc.append((
                    f"Sequence within the wave: make-before-break the {len(mbb_hosts)} dual-homed switch(es) "
                    f"first (build beside, keep the legacy leg), THEN take the scheduled outage for the "
                    f"{len(hard_hosts)} single-homed switch(es) that have no second path.",
                    "dual-homed members re-homed with no outage before the single-homed window opens."))
            proc += [
                ("Announce the hard cutover; this wave has a brief outage for the moved endpoints.",
                 "stakeholders acknowledged; the outage clock is started."),
                ("Apply the staged target configuration and move the uplinks/endpoints per the §"
                 f"{wi}.4 port mapping from legacy to target.",
                 "every port in the §" + f"{wi}.4 mapping is re-terminated and up."),
                ("Bring up the target links and confirm STP converges and trunks negotiate as "
                 "expected.",
                 "STP converged; trunk allowed-VLAN checks pass; no err-disabled ports."),
            ]
        if playbook.get("validate"):
            proc.append(("In-window validation: " + playbook["validate"].rstrip(". ") + ".",
                         "in-window checks match the §" + f"{wi}.3 baseline."))
        proc.append(("Run §" + f"{wi}.6 post-cutover validation in full before declaring the wave "
                     "complete.",
                     "every check matches its captured baseline."))
        steps(proc)

        # 2.x.6 post-cutover validation (reuse the existing validation plan)
        doc.add_heading(f"{wi}.6 Post-cutover validation (go/no-go)", level=2)
        if val_items:
            doc.add_paragraph("Every check must pass. A failure that cannot be corrected in-window "
                              "triggers the rollback in §" + f"{wi}.7.")
            # surface the severity already on each validation item and order High-first, so the
            # most critical go/no-go checks survive the 40-row display cap (the rationale `why` and
            # the full set remain in the Cutover Validation workbook sheet).
            _vr = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
            vshow = sorted(val_items, key=lambda it: _vr.get(it.get("severity"), 5))[:40]
            table(["Sev", "Category", "Device", "Check", "Command", "Expected (good) result"],
                  [(it.get("severity") or "—", it.get("category"), it.get("device"), it.get("check"),
                    it.get("command"), it.get("expect")) for it in vshow],
                  widths=[0.5, 0.9, 0.9, 1.6, 1.4, 1.5])
            if len(val_items) > 40:
                doc.add_paragraph(f"… and {len(val_items) - 40} more check(s); full set in the Cutover "
                                  "Validation workbook sheet.")
        else:
            doc.add_paragraph("No machine-generated validation checks for this wave. As a minimum, verify "
                              "gateway reachability (ping the SVI/HSRP vIP), FHRP roles, routing "
                              "adjacencies, STP root, and port-channel membership are unchanged from the "
                              "§" + f"{wi}.3 baseline.")

        # 2.x.7 rollback
        doc.add_heading(f"{wi}.7 Rollback", level=2)
        rb = [("Declare rollback in the war room and record the trigger (which validation check "
               "failed).",
               "the trigger and time are recorded in the change log.")]
        if multi:
            for g, sc, _sq in wave_groups:
                rbk = (sc.get("playbook") or {}).get("rollback")
                if rbk:
                    rb.append((f"{g}: " + rbk.rstrip(". ") + ".",
                               "this group's endpoints are back on their legacy path."))
        elif playbook.get("rollback"):
            rb.append("Strategy-specific: " + playbook["rollback"].rstrip(". ") + ".")
        if _kind == "coupled-subwave":
            rb.append(("Coupled sub-wave: rolling back this sub-wave must NOT strand a sibling sub-wave's "
                       "shared VLAN — keep the shared VLANs extended on the legacy path and coordinate with "
                       "any sibling sub-waves already cut over before withdrawing anything.",
                       "no sibling sub-wave loses a shared VLAN as a result of this rollback."))
        if mbb_hosts and not hard_hosts:   # pure make-before-break: the legacy path was never torn down
            rb.append(("Move any migrated endpoints back onto the still-live legacy leg; remove the "
                       "new path. Because the legacy path was never torn down, this is non-disruptive.",
                       "all endpoints re-home onto the legacy leg with no loss."))
        else:
            if mbb_hosts and hard_hosts:   # MIXED: only the dual-homed legs roll back non-disruptively
                rb.append(("Dual-homed members roll back onto their still-live legacy leg (non-disruptive); "
                           "the single-homed members need the §" + f"{wi}.3 pre-change config re-applied (a "
                           "brief outage), since their path was torn down at cutover.",
                           "dual-homed members re-home with no loss; single-homed members restored from baseline."))
            rb.append(("Re-apply the pre-change configuration captured in §" + f"{wi}.3 to <devices>; "
                       "move uplinks/endpoints back to the legacy ports.",
                       "configuration and cabling match the §" + f"{wi}.3 captured state."))
        rb.append(("Re-run the §" + f"{wi}.6 checks against the legacy path to confirm service is "
                   "restored, then close the window as rolled-back and schedule a retro.",
                   "legacy-path checks match the §" + f"{wi}.3 baseline; window closed as rolled-back."))
        steps(rb)

        # 2.x.8 sign-off
        doc.add_heading(f"{wi}.8 Sign-off", level=2)
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
    # closing signature gate under the existing section (heading=None: no new H1)
    # Deliverable Excellence (DE-01): shared glossary before the sign-off gate.
    add_glossary(doc)

    add_acceptance(
        doc, heading=None,
        scope_note="Sign-off below closes the change as a whole; each wave's in-window sign-off is "
                   "recorded in its own section.")

    # numbered sections only — the unnumbered furniture H1s (Contents, Document Control) are not
    # content sections and inflating the figure made run logs drift across versions (review fix)
    n_sections = len([p for p in doc.paragraphs
                      if p.style.name == "Heading 1" and p.text[:1].isdigit()])
    doc.save(output_path)
    logger.info(f"[Phase 34] MOP (DOCX) written: {output_path} ({len(waves)} wave(s), {n_sections} sections)")
