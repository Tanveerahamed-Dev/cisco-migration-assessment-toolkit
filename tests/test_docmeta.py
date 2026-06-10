"""NEW-V3.23.150: shared AS-style document furniture (document control + acceptance gate) for the
DOCX deliverable family. python-docx is optional, so the module is skipped when it is absent (the
helpers are only ever called by writers whose own docx import already succeeded)."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.docmeta import add_acceptance, add_document_control, related_rows  # noqa: E402


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_related_rows_excludes_the_document_being_written():
    rows = related_rows(exclude=("mop",))
    names = [n for n, _ in rows]
    assert not any("Method of Procedure" in n for n in names)
    assert any("Assessment workbook" in n for n in names)
    assert len(rows) == 10  # the 11-document family (incl. the architecture review, V3.23.160) minus self
    # a bare-string exclude is one key, not an iterable of letters (set("mop") footgun)
    assert related_rows(exclude="mop") == rows


def test_document_control_renders_all_furniture():
    doc = Document()
    add_document_control(doc, document="Unit Doc", label="Fleet X", engine_version="V9",
                         generated_at="2026-06-10 09:00", audience="unit testers",
                         exclude=("design",), extra_assumptions=("extra unit caveat",))
    text = _all_text(doc)
    assert "Document Control" in text and "Revision history" in text
    assert "Fleet X" in text and "2026-06-10 09:00" in text
    assert "DRAFT — generated; not yet reviewed" in text
    assert "Related documents" in text and "Assessment workbook (.xlsx)" in text
    assert "As-Built Network Design Document (.docx)" not in text   # self excluded from the set
    assert "Assumptions & caveats" in text and "extra unit caveat" in text
    assert "unit testers" in text


def test_related_documents_block_renders_table_and_audience():
    """V3.23.152: the shared family cross-reference block (used by NRFU/PIR directly and by
    add_document_control with intro=True)."""
    from cisco_toolkit.docmeta import add_related_documents

    doc = Document()
    add_related_documents(doc, exclude=("nrfu",), audience="unit audience")
    text = _all_text(doc)
    assert "Related documents" in text
    assert "NRFU / Acceptance Test Plan (.docx)" not in text   # self excluded
    assert "Assessment workbook (.xlsx)" in text
    assert "Intended audience:" in text and "unit audience" in text
    assert "one of a set" not in text                          # intro only when intro=True


def test_acceptance_renders_roles_and_optional_heading():
    doc = Document()
    add_acceptance(doc, scope_note="unit scope note")
    text = _all_text(doc)
    assert "Document Acceptance" in text and "unit scope note" in text
    for role in ("Customer network owner", "Customer operations lead",
                 "Delivery engineer (author)", "Project / change manager"):
        assert role in text
    # heading=None appends the gate under an existing section without a new H1 (the MOP's use)
    doc2 = Document()
    add_acceptance(doc2, heading=None)
    h1 = [p.text for p in doc2.paragraphs if p.style.name == "Heading 1"]
    assert h1 == []
    assert "Customer network owner" in _all_text(doc2)
