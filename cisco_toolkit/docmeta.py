"""Shared document-control / acceptance "furniture" for the DOCX deliverable family.

NEW-V3.23.150: a Cisco Advanced Services deliverable (HLD/LLD, MOP, NRFU/ATP, runbook) always carries
the same furniture around the technical content — a document-control block after the cover (revision
history, intended audience, related documents, assumptions & caveats) and a signature acceptance block
at the end. That review-and-approval gate is how an AS engagement actually runs: no further work until
the deliverable is accepted. The engine writers (runbook / design / MOP) and AssessHub's web-layer
writers (cutover plan; the NRFU and PIR carry their own control tables and reuse only the
related-documents list) call these helpers so the wording, structure and cross-references stay
consistent across the whole set.

python-docx is OPTIONAL repo-wide: nothing here imports it at module load; the helpers import it
inside the call, exactly like the writers themselves, and operate on an already-open Document. The
writers only call in after their own `from docx import …` has succeeded, so the fail-soft path is
unchanged.
"""
from datetime import datetime

from cisco_toolkit.textutils import xml_safe   # shared XML-illegal-char sanitizer (every cell text routes through it)

# Severity ordering shared by the writer family (V3.23.159: hoisted from per-writer copies so the
# documents sort findings identically; engagement/crd import it — older writers' private copies
# migrate as they are next touched).
SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}

# The deliverable family, keyed for self-exclusion in the Related-Documents table.
# Order is the recommended reading order of the set.
FAMILY = (
    ("engagement", "Engagement Workflow & Plan of Record (.docx)",
     "Phase-gated engagement workflow: verdict, gate calendar, RAID log and the next-action queue"),
    ("crd", "Customer Requirements Document (.docx)",
     "Plan-phase requirements capture: REQ-IDs, owners, and traceability into design and acceptance"),
    ("workbook", "Assessment workbook (.xlsx)",
     "Full per-sheet evidence; every number in the narrative documents reconciles to it"),
    ("explorer", "Blast-Radius Explorer (.html)",
     "Interactive topology, health and what-if view of the same snapshot"),
    ("runbook", "Assessment & Migration Runbook (.docx)",
     "Narrative findings, risk register and remediation detail"),
    ("design", "As-Built Network Design Document (.docx)",
     "HLD + LLD design record recovered from the fleet evidence"),
    ("archreview", "Architecture Review & Conformance Report (.docx)",
     "Leading-practice conformance scorecard, availability analysis and the design-review verdicts"),
    ("mop", "Per-Wave Method of Procedure (.docx)",
     "Maintenance-window change procedure, validation and rollback per wave"),
    ("cutover", "Cutover Plan / Run-of-Show (.docx)",
     "Pilot-first wave sequence, go/no-go gates and window estimates"),
    ("nrfu", "NRFU / Acceptance Test Plan (.docx)",
     "Production-acceptance test cases with expected baselines"),
    ("opshandbook", "Operations Handbook (.docx)",
     "Day-2 monitoring baseline, drift control, software governance and escalation readiness"),
    ("deck", "Executive Presentation Deck (.pptx)",
     "Stakeholder summary of posture, risk and the migration plan"),
)

# What a COMPLETE engine CLI run leaves on disk, keyed by FAMILY key: the filename suffix each
# writer appends to the --output stem. FAMILY says what the set IS; this says what to look for.
# It exists so a caller can diff PRODUCED-vs-EXPECTED instead of hardcoding a list that rots as
# deliverables accrete (webapp.backend.ingest.run_redaction_folder -- every engine writer is
# fail-soft, logging a warning and continuing, so a set missing two documents otherwise reports
# success). `cutover` and `nrfu` are absent BY DESIGN: AssessHub's web layer renders those two
# from a stored snapshot and the engine has no writer for them, so a CLI run is COMPLETE without
# them. tests/test_docmeta_cli_artifacts.py ratchets both halves against the engine source, so a
# renamed suffix or a newly added writer fails the suite instead of silently widening the blind
# spot. (That filename is the map's own SSOT pointer — keep it correct if the test file moves.)
CLI_ARTIFACT_SUFFIX = {
    "workbook": ".xlsx",                    # the --output path itself; the engine always writes it
    "explorer": "_explorer.html",
    "runbook": "_runbook.docx",
    "design": "_design.docx",
    "mop": "_mop.docx",
    "crd": "_crd.docx",
    "engagement": "_engagement.docx",
    "archreview": "_archreview.docx",
    "opshandbook": "_ops_handbook.docx",
    "deck": "_executive_deck.pptx",
}

#: Family kinds AssessHub renders in the web layer; no engine writer produces them.
WEB_ONLY_KINDS = frozenset({"cutover", "nrfu"})


def cli_artifacts(stem):
    """``[(key, name, filename)]`` a complete engine CLI run writes for output stem ``stem``.

    ``stem`` is the --output path without its extension (``.../Assessment_redacted``); the
    filenames returned are basenames, in FAMILY reading order."""
    base = str(stem).replace("\\", "/").rsplit("/", 1)[-1]
    return [(key, name, base + CLI_ARTIFACT_SUFFIX[key])
            for key, name, _role in FAMILY if key in CLI_ARTIFACT_SUFFIX]

# Caveats every generated deliverable shares; writers append doc-specific ones via extra_assumptions.
_ASSUMPTIONS = (
    "This document is generated from the offline assessment snapshot named on the cover; it reflects "
    "the network as collected at that time, not live state.",
    "The evidence base is read-only device command output (configuration plus CDP/LLDP neighbour "
    "data); nothing was changed on the network during collection.",
    "Every <placeholder> marker must be completed and the document peer-reviewed before it is "
    "treated as an approved record.",
    "Recommendations must be validated against the engagement's statement of work and the customer's "
    "change-control process before execution.",
)

DEFAULT_ROLES = ("Customer network owner", "Customer operations lead",
                 "Delivery engineer (author)", "Project / change manager")


def related_rows(exclude=()):
    """(name, role) rows for the Related-Documents table, excluding the document being written.
    `exclude` is a family key or an iterable of keys; a bare string is treated as one key (set("mop")
    would otherwise dissolve into letters and silently keep the document in its own related list)."""
    ex = {exclude} if isinstance(exclude, str) else set(exclude)
    return [(name, role) for key, name, role in FAMILY if key not in ex]


def add_table(doc, headers, rows, widths=None, *, fixed=True):
    """House-style banded table (bold header). Public: the engine writers (runbook/design/MOP)
    delegate their local table() closures here so the family has ONE table builder instead of
    per-writer copies (V3.23.152 review cleanup).

    `fixed=True` (the furniture tables): autofit off + widths on both column and cells so renderers
    honour them exactly — these widths were authored to fit. `fixed=False` (the writers' content
    tables): widths are hints on cells only, preserving the writers' historical auto-layout — their
    width sets predate fixed layout and can exceed the portrait text column, so forcing fixed layout
    clips the last column (caught in V3.23.152 visual QA)."""
    from docx.shared import Inches

    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = xml_safe(str(hd))            # sanitize: one XML-illegal char in any cell aborts the whole .docx
        for para in c.paragraphs:
            for run in para.runs:
                run.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = "" if v is None else xml_safe(str(v))
    if widths:
        if fixed:
            t.autofit = False
            for i, w in enumerate(widths):
                t.columns[i].width = Inches(w)
                for row in t.rows:
                    row.cells[i].width = Inches(w)
        else:
            for i, w in enumerate(widths):
                for row in t.rows:
                    row.cells[i].width = Inches(w)
    doc.add_paragraph()
    return t


def _kv(doc, label, value):
    """Bold navy lead-in + plain value, matching the writers' _label_run/kv convention."""
    from docx.shared import RGBColor

    p = doc.add_paragraph()
    r = p.add_run(xml_safe(label))
    r.bold = True
    from cisco_toolkit.brand_tokens import DOC_NAVY_RGB
    r.font.color.rgb = RGBColor(*DOC_NAVY_RGB)
    p.add_run(" " + (xml_safe(str(value)) if value not in (None, "") else "—"))
    return p


def add_related_documents(doc, *, exclude=(), audience=None, intro=False):
    """Render the family cross-reference block (level-2 heading + Related-Documents table, with an
    optional intro paragraph and an optional trailing Intended-audience line). One implementation for
    the whole set: add_document_control uses it for the engine writers' front matter, and the NRFU /
    PIR writers (which carry their own control tables) call it directly (V3.23.152 review cleanup)."""
    doc.add_heading("Related documents", level=2)
    if intro:
        doc.add_paragraph(
            "This document is one of a set generated from the same assessment snapshot — the set is "
            "internally consistent (every number reconciles) and should travel together with the "
            "engagement's statement of work and change records.")
    add_table(doc, ["Document", "Role in the set"], related_rows(exclude), widths=[2.7, 4.0])
    if audience:
        _kv(doc, "Intended audience:", audience)


def add_document_control(doc, *, document, label, engine_version="", generated_at=None,
                         collected_at=None, audience="", exclude=(), extra_assumptions=()):
    """Render the Document Control front matter (control table, revision history, intended audience,
    related documents, assumptions & caveats). Call it between the cover page and the table of
    contents; the heading is deliberately unnumbered so the writers' numbered sections are untouched.

    Provenance (wave R2-3-01): "Snapshot captured" is the COLLECTION instant (when the evidence was
    sampled), distinct from "Document generated" (when this DOCX was rendered). On a --no-collect
    re-analysis these differ; collected_at falls back to generated_at for snapshots predating the field."""
    doc.add_heading("Document Control", level=1)
    add_table(doc, ["Field", "Value"], [
        ("Document", document),
        ("Subject", label or "—"),
        ("Snapshot captured", collected_at or generated_at or "—"),
        ("Document generated", generated_at or "—"),
        ("Generated by", ("cisco-migration-assessment-toolkit " + str(engine_version)).strip()),
        ("Status", "DRAFT — generated; not yet reviewed"),
    ], widths=[1.8, 4.9])

    doc.add_heading("Revision history", level=2)
    add_table(doc, ["Version", "Date", "Author", "Notes"], [
        ("0.1", datetime.now().strftime("%Y-%m-%d"), "Generated draft",
         "Initial draft generated from the assessment snapshot"),
        ("", "", "", "<record each review/amendment here before acceptance>"),
    ], widths=[0.8, 1.1, 1.9, 2.9])

    # Distribution list (wave DE-01, Law 2 "Document Control"): a generated deliverable is a
    # controlled record — who holds a copy and in what capacity is part of the control front matter,
    # not an afterthought. Static roles (the review-and-approval chain); names/orgs are placeholders
    # the delivery lead completes before the document is issued.
    doc.add_heading("Distribution list", level=2)
    add_table(doc, ["Name", "Role", "Organisation", "Purpose"],
              [("<name>", r, "<organisation>",
                "Review & acceptance" if "author" not in r.lower() else "Author / issue")
               for r in DEFAULT_ROLES],
              widths=[1.6, 2.2, 1.7, 1.2])

    _kv(doc, "Intended audience:", audience)
    doc.add_paragraph()

    add_related_documents(doc, exclude=exclude, intro=True)

    doc.add_heading("Assumptions & caveats", level=2)
    for a in tuple(_ASSUMPTIONS) + tuple(extra_assumptions):
        doc.add_paragraph(a, style="List Bullet")


def add_acceptance(doc, *, heading="Document Acceptance", scope_note="", roles=DEFAULT_ROLES):
    """Render the closing acceptance / sign-off block: the review-and-approval gate. Pass
    heading=None to append the block under an existing section (the MOP's final acceptance)."""
    if heading:
        doc.add_heading(heading, level=1)
    doc.add_paragraph(
        "By signing below, the signatories confirm that this document has been reviewed, that review "
        "comments have been addressed, and that it is accepted as the working record for this phase "
        "of the engagement." + ((" " + scope_note) if scope_note else ""))
    add_table(doc, ["Role", "Name", "Signature", "Date"],
           [(r, "", "", "") for r in roles], widths=[2.2, 1.9, 1.6, 1.0])


def enable_update_fields(doc):
    """Mark the document so Word / LibreOffice rebuild every field (the TOC especially) on open —
    instead of shipping the client an empty placeholder they must Right-click → Update Field / F9.

    Sets ``<w:updateFields w:val="true"/>`` in word/settings.xml, idempotently (V3.23.172). Without
    it a field-code TOC renders as its placeholder text until manually refreshed, so a client who
    opens-and-prints (or a headless docx→pdf render) gets a deliverable with no table of contents.

    Placed in the schema-correct slot (``CT_Settings`` is an ordered sequence: ``updateFields`` must
    precede ``compat``/``rsids``/``mathPr``/…). Appending at the end is what Word/LibreOffice tolerate
    but a strict XSD validator rejects — insert before the first element that must follow it so the
    deliverable is schema-valid, not merely Word-openable.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    after = {qn("w:" + t) for t in (
        "compat", "docVars", "rsids", "attachedSchema", "themeFontLang", "clrSchemeMapping",
        "doNotAutoCompressPictures", "shapeDefaults", "decimalSymbol", "listSeparator",
        "hdrShapeDefaults", "footnotePr", "endnotePr")}
    after.add(qn("m:mathPr"))
    settings = doc.settings.element
    el = settings.find(qn("w:updateFields"))
    if el is None:
        el = OxmlElement("w:updateFields")
        anchor = next((c for c in settings if c.tag in after), None)
        anchor.addprevious(el) if anchor is not None else settings.append(el)
    el.set(qn("w:val"), "true")


def add_toc(doc, *, heading="Contents", depth="1-2"):
    """Render the 'Contents' heading + the Word TOC field code (V3.23.171 — was a verbatim
    copy in every generator; one home means one place to change heading depth or the
    update-field placeholder). Fields are marked to rebuild on open (``enable_update_fields``,
    V3.23.172), so the TOC populates for the client automatically — no manual F9."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc.add_heading(heading, level=1)
    p = doc.add_paragraph()
    run = p.add_run()
    fb = OxmlElement("w:fldChar"); fb.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = rf'TOC \o "{depth}" \h \z \u'
    fs = OxmlElement("w:fldChar"); fs.set(qn("w:fldCharType"), "separate")
    ft = OxmlElement("w:t"); ft.text = "This table builds automatically when the document opens (or Right-click → Update Field)."
    fe = OxmlElement("w:fldChar"); fe.set(qn("w:fldCharType"), "end")
    for el in (fb, instr, fs, ft, fe):
        run._r.append(el)
    enable_update_fields(doc)
    doc.add_page_break()


def as_dict(x) -> dict:
    """Coerce a possibly-malformed snapshot value to a dict. `snap.get(k) or {}` does NOT
    guard a truthy non-dict (the V3.23.159 review's recurring bug class) — every deliverable
    reader should use these shared coercers instead of carrying a private copy."""
    return x if isinstance(x, dict) else {}


def as_list(x) -> list:
    """Coerce a possibly-malformed snapshot value to a list (see as_dict)."""
    return x if isinstance(x, list) else []


# ---- Deliverable Excellence furniture (wave DE-01) --------------------------------------------
# The narrative documents were strong on evidence but weak on ORIENTATION: no "at a glance"
# register, no glossary, and — the recurring drift risk — they hand-recounted headline numbers
# instead of reading the single source of truth. These shared helpers close Laws 1/6/8/10 + the
# glossary for the WHOLE docx family in one place, exactly as add_document_control/add_acceptance
# already do for Law 2. Every value is read via cisco_toolkit.ssot.canonical_facts (never a recount)
# and is coverage-honest (an unpublished fact reads "[NOT OBSERVED]", never a fabricated 0).

# Curated shared glossary — terms + evidence conventions common to every deliverable. A writer
# appends doc-specific terms via extra_terms; the coverage-honesty rows are the load-bearing ones.
DEFAULT_GLOSSARY = (
    ("SVI", "Switched Virtual Interface — a VLAN's Layer-3 gateway on a switch."),
    ("FHRP", "First-Hop Redundancy Protocol (HSRP/VRRP/GLBP) — gateway redundancy across two devices."),
    ("LDoS / EoS", "Last Date of Support / End of Sale — hardware lifecycle milestones. Past-LDoS is migration-critical."),
    ("Blast radius", "The set of devices/endpoints affected if a given node or link fails."),
    ("Keystone device", "A device whose failure strands a disproportionate share of the fleet."),
    ("Move group", "A set of devices migrated together within one maintenance window."),
    ("vPC / MLAG", "Multi-chassis link aggregation — two switches presenting as one to a downstream device."),
    ("VRF", "Virtual Routing and Forwarding — an isolated routing table on a device."),
    ("Inferred-high", "Derived from CDP/LLDP or configuration rather than directly observed, but high-confidence."),
    ("[NOT OBSERVED]", "The evidence needed to judge this was NOT collected. It is NOT a healthy or passing "
                       "result — coverage-honesty: not observed never silently becomes 'fine'."),
)


def _glance_rows(snap):
    """Default 'at a glance' Q&A rows built from the canonical facts (coverage-honest). Kept private
    so a writer's extra_rows compose with a single, drift-proof headline block."""
    from cisco_toolkit import ssot   # lazy: avoids any module-load cycle (matches the docx lazy-import style)

    f = ssot.canonical_facts(snap if isinstance(snap, dict) else {})

    def v(x):
        return "[NOT OBSERVED]" if x is None else x

    nd, nc = f.get("n_devices"), f.get("n_collected")
    if nd is not None and nc is not None and nc != nd:
        scope = f"{nc} of {nd} inventoried devices collected (read-only evidence; {nd - nc} not reached)"
    elif nd is not None:
        scope = f"{nd} inventoried devices, collected read-only"
    else:
        scope = "[NOT OBSERVED]"

    rows = [
        ("What was assessed?", scope),
        ("How healthy is the fleet?",
         f"average health {v(f.get('avg_health'))}/100 — {v(f.get('n_critical'))} Critical, {v(f.get('n_poor'))} Poor"),
        ("Biggest lifecycle exposure?",
         f"{v(f.get('n_past_ldos'))} device(s) past last-date-of-support (migration-critical)"),
        ("Scale (VLANs / endpoints)?",
         f"{v(f.get('n_vlans'))} production VLANs · {v(f.get('n_endpoints'))} evidenced endpoints"),
    ]
    if f.get("n_design_decisions") is not None:
        rows.append(("Design decisions recorded?",
                     f"{f['n_design_decisions']} (each traced to a requirement or a gap)"))
    return rows


def add_excellence_front(doc, snap, *, extra_rows=(), heading="At a Glance"):
    """Answer-first 'at a glance' register + the single-source-of-truth trust signal, for EVERY
    deliverable (Laws 6/1/10). Reads headline facts via ssot.canonical_facts (never a recount),
    renders the ssot.summary self-verification line, and is coverage-honest ('[NOT OBSERVED]', not 0,
    for an unpublished fact). extra_rows lets a writer pre-answer its own doc-specific questions.
    Unnumbered heading so the writers' numbered sections are untouched. Call it right after the TOC."""
    from cisco_toolkit import ssot

    doc.add_heading(heading, level=1)
    s = ssot.summary(snap if isinstance(snap, dict) else {})
    if s.get("n_facts"):
        if s.get("verified"):
            _kv(doc, "Single source of truth:",
                f"✓ {s['n_facts']} headline figures self-verified against the raw evidence — "
                "every number in this document reconciles to one source.")
        else:
            _kv(doc, "Single source of truth:",
                f"⚠ {s['n_violations']} of {s['n_facts']} headline figures did not reconcile; "
                "treat flagged numbers with caution (see the assessment-integrity disclosure).")
    rows = list(_glance_rows(snap)) + list(extra_rows)
    add_table(doc, ["Question", "Answer"], rows, widths=[2.6, 4.1], fixed=False)


def add_glossary(doc, *, extra_terms=(), heading="Glossary & Conventions"):
    """Shared term/convention glossary for the deliverable family (Technique T2). extra_terms
    appends doc-specific terms. Unnumbered; place before the acceptance block."""
    doc.add_heading(heading, level=1)
    doc.add_paragraph(
        "Terms and evidence conventions used across the assessment deliverable set. "
        "'[NOT OBSERVED]' always means the evidence was not collected — never that the item is healthy.")
    add_table(doc, ["Term", "Meaning"], list(DEFAULT_GLOSSARY) + list(extra_terms),
              widths=[1.7, 5.0], fixed=False)


def add_inputs_required(doc, snap, *, extra_rows=(), heading="Inputs Required"):
    """Consolidated 'what the customer and delivery team must still provide or confirm' register
    (Law 9): the reader should never have to hunt scattered <placeholders> to know what is owed.
    Universal, coverage-honest base rows from the snapshot — the not-collected devices are the #1
    real gap (a blind spot, [NOT OBSERVED], never assumed healthy) — plus the standard
    placeholder/peer-review gates; extra_rows lets a writer add its own unconfirmed items.
    Unnumbered; place in the front matter so the outstanding asks are answer-first."""
    snap = snap if isinstance(snap, dict) else {}
    cc = snap.get("collection_completeness")
    cc = cc if isinstance(cc, dict) else {}
    summ = cc.get("summary")
    summ = summ if isinstance(summ, dict) else {}
    rows = []
    n_notcoll = summ.get("not_collected")
    if isinstance(n_notcoll, int) and n_notcoll > 0:
        rows.append(("Collect the not-reached devices",
                     f"{n_notcoll} inventoried device(s) were not collected — their state is a blind spot "
                     "([NOT OBSERVED]). Collect them read-only to close it before relying on this document.",
                     "Customer / delivery"))
    rows.append(("Complete every <placeholder>",
                 "Fill every <…> marker in this document before it is treated as an approved record.",
                 "Delivery engineer"))
    rows.append(("Peer review & accept",
                 "This is a generated DRAFT; it must be peer-reviewed and accepted (see Document "
                 "Acceptance) before use.", "Review owner"))
    rows = rows + list(extra_rows)
    doc.add_heading(heading, level=1)
    doc.add_paragraph(
        "What the customer and delivery team must provide or confirm to close the assessment's known "
        "gaps. Coverage-honest: a not-collected device is a blind spot, never assumed healthy.")
    add_table(doc, ["Item", "What is needed", "Owner"], rows, widths=[1.9, 3.8, 1.0], fixed=False)
