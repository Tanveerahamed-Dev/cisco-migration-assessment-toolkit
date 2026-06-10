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
    ("deck", "Executive Presentation Deck (.pptx)",
     "Stakeholder summary of posture, risk and the migration plan"),
)

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
        c.text = str(hd)
        for para in c.paragraphs:
            for run in para.runs:
                run.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = "" if v is None else str(v)
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
    r = p.add_run(label)
    r.bold = True
    r.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
    p.add_run(" " + (str(value) if value not in (None, "") else "—"))
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
                         audience="", exclude=(), extra_assumptions=()):
    """Render the Document Control front matter (control table, revision history, intended audience,
    related documents, assumptions & caveats). Call it between the cover page and the table of
    contents; the heading is deliberately unnumbered so the writers' numbered sections are untouched."""
    doc.add_heading("Document Control", level=1)
    add_table(doc, ["Field", "Value"], [
        ("Document", document),
        ("Subject", label or "—"),
        ("Snapshot captured", generated_at or "—"),
        ("Generated by", ("cisco-migration-assessment-toolkit " + str(engine_version)).strip()),
        ("Status", "DRAFT — generated; not yet reviewed"),
    ], widths=[1.8, 4.9])

    doc.add_heading("Revision history", level=2)
    add_table(doc, ["Version", "Date", "Author", "Notes"], [
        ("0.1", datetime.now().strftime("%Y-%m-%d"), "Generated draft",
         "Initial draft generated from the assessment snapshot"),
        ("", "", "", ""),
    ], widths=[0.8, 1.1, 1.9, 2.9])

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
