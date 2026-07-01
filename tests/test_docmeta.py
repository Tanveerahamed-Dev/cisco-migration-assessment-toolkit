"""NEW-V3.23.150: shared AS-style document furniture (document control + acceptance gate) for the
DOCX deliverable family. python-docx is optional, so the module is skipped when it is absent (the
helpers are only ever called by writers whose own docx import already succeeded)."""
import pytest

docx = pytest.importorskip("docx")  # skip the file if the optional dep is absent
from docx import Document  # noqa: E402

from cisco_toolkit.docmeta import (  # noqa: E402
    add_acceptance,
    add_document_control,
    add_toc,
    as_dict,
    as_list,
    related_rows,
)


def _all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_add_toc_renders_field_code_and_placeholder():
    # V3.23.171: the TOC field-code block was a verbatim copy in all 7 generators; the shared
    # helper must keep the contract every writer test relies on (the Right-click placeholder).
    doc = Document()
    add_toc(doc)
    assert any("Contents" in p.text for p in doc.paragraphs
               if p.style.name.startswith("Heading"))
    assert "Right-click → Update Field" in _all_text(doc)
    xml = doc.element.xml
    assert 'TOC \\o "1-2"' in xml and "fldChar" in xml      # the real Word field code
    deep = Document()
    add_toc(deep, depth="1-3")
    assert 'TOC \\o "1-3"' in deep.element.xml              # depth is configurable in ONE place


def test_shared_coercers_guard_truthy_non_containers():
    # the V3.23.159 review's bug class, now importable instead of copied per generator
    assert as_dict({"a": 1}) == {"a": 1}
    assert as_dict("truthy-non-dict") == {} and as_dict(None) == {} and as_dict(3) == {}
    assert as_list([1]) == [1]
    assert as_list("nope") == [] and as_list(None) == [] and as_list({"a": 1}) == []


def test_related_rows_excludes_the_document_being_written():
    rows = related_rows(exclude=("mop",))
    names = [n for n, _ in rows]
    assert not any("Method of Procedure" in n for n in names)
    assert any("Assessment workbook" in n for n in names)
    assert len(rows) == 11  # the 12-document family (incl. the ops handbook, V3.23.168) minus self
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


def test_document_control_separates_collection_from_generation():
    """Provenance (wave R2-3-01): 'Snapshot captured' is the COLLECTION instant; 'Document generated'
    is the render time. On a --no-collect re-render these differ and must NOT be conflated."""
    doc = Document()
    add_document_control(doc, document="Unit Doc", label="Fleet X", engine_version="V9",
                         generated_at="2026-06-21T06:58:07", collected_at="2026-06-13T06:32:01",
                         audience="unit testers")
    rows = {r.cells[0].text: r.cells[1].text for tbl in doc.tables for r in tbl.rows}
    assert rows.get("Snapshot captured") == "2026-06-13T06:32:01"   # collection date headlines
    assert rows.get("Document generated") == "2026-06-21T06:58:07"  # render date is distinct, not conflated


def test_document_control_collected_at_falls_back_to_generated():
    """Back-compat: a snapshot predating collected_at still shows the generation date under
    'Snapshot captured' (never blank)."""
    doc = Document()
    add_document_control(doc, document="Unit Doc", label="Fleet X", generated_at="2026-06-10 09:00")
    rows = {r.cells[0].text: r.cells[1].text for tbl in doc.tables for r in tbl.rows}
    assert rows.get("Snapshot captured") == "2026-06-10 09:00"      # fallback preserved


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
