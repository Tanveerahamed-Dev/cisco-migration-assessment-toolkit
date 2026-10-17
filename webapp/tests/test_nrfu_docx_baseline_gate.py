"""NRFU must retain typed validation authority and refuse blocker-as-acceptance wording."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("docx", reason="python-docx not installed on this runner")


def _review_snapshot() -> dict:
    row = {
        "device": "gw2",
        "platform": "ios",
        "wave": "Gateway wave",
        "category": "Routing",
        "severity": "High",
        "check": "Verify source-bound review evidence",
        "command": "show ip ospf neighbor",
        "expect": (
            "PRE-CUTOVER REVIEW — BLOCKER: the source-bound observation requires simultaneous "
            "verification or explicit disposition."
        ),
        "why": "The evidence does not establish an acceptable current state.",
        "evidence_state": "review",
        "projection_custody": "source_bound_current_run",
        "source_key": "routing_baseline_receipt/subjects/gw2/OSPF",
    }
    return {
        "devices": {"gw2": {"platform": "ios"}},
        "validation_plan": {
            "items": [row],
            "by_wave": {"Gateway wave": [dict(row)]},
            "summary": {
                "n_items": 1,
                "n_waves": 1,
                "by_category": {"Routing": 1},
                "n_high": 1,
            },
        },
    }


def test_nrfu_renders_typed_authority_and_indeterminate_blocker_banner(tmp_path):
    from docx import Document

    from backend.nrfu_docx import write_nrfu_docx

    out = tmp_path / "typed-baseline-nrfu.docx"
    write_nrfu_docx(str(out), _review_snapshot(), "Typed baseline")

    doc = Document(out)
    paragraphs = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    cells = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]

    assert "CURRENT BASELINE INDETERMINATE" in paragraphs
    assert "Matching a blocker observation is not acceptance" in paragraphs
    assert "Evidence state" in cells
    assert "Custody / source" in cells
    assert "review" in cells
    assert any(
        "source_bound_current_run" in cell
        and "routing_baseline_receipt/subjects/" in cell
        for cell in cells
    )
    assert any("simultaneous verification or explicit disposition" in cell for cell in cells)


@pytest.mark.parametrize("missing", ["description", "setup", "pass_criteria", "devices"])
def test_nrfu_incomplete_persisted_acceptance_never_claims_tested(tmp_path, missing):
    from docx import Document

    from backend.nrfu_docx import write_nrfu_docx

    complete = {
        "decision_id": "EXAMPLE-complete", "title": "EXAMPLE acceptance", "phase": "pre-cutover",
        "description": "EXAMPLE verify recorded adjacency", "setup": "EXAMPLE collect both peers first",
        "pass_criteria": "EXAMPLE adjacency matches the source-bound expectation", "devices": ["EXAMPLE-SW"],
    }
    incomplete = {**complete, "decision_id": "EXAMPLE-incomplete"}
    incomplete.pop(missing)
    snap = {
        "devices": {},
        "design_blueprint": {"decisions": [
            {"id": "EXAMPLE-complete", "title": "Complete decision", "status": "recommended"},
            {"id": "EXAMPLE-incomplete", "title": "Incomplete decision", "status": "recommended"},
        ]},
        "design_nrfu": {"items": [complete, incomplete]},
    }
    out = tmp_path / "acceptance.docx"
    write_nrfu_docx(str(out), snap, "EXAMPLE persisted acceptance")
    doc = Document(out)
    rows = [[cell.text for cell in row.cells] for table in doc.tables for row in table.rows]
    assert next(row for row in rows if row[0] == "Complete decision")[2] == "Tested — pre-cutover"
    uncovered = next(row for row in rows if row[0] == "Incomplete decision")[2]
    assert "NOT COVERED" in uncovered and "Tested" not in uncovered
    body = next(row for row in rows if row[0] == "EXAMPLE-complete")
    assert body[3:7] == [complete["description"], complete["setup"], complete["pass_criteria"], "EXAMPLE-SW"]
    assert next(row for row in rows if row[0] == "EXAMPLE-incomplete")[-1] == ""
    assert "Not supplied in persisted acceptance content" in "\n".join("\n".join(row) for row in rows)


def test_nrfu_summaries_count_the_exact_rendered_rows_with_distinct_service_ports(tmp_path):
    from docx import Document

    from backend.nrfu_docx import write_nrfu_docx

    snap = {
        "devices": {},
        "lifecycle_risk": {"per_device": [{"host": "EXAMPLE-SW"}]},
        "validation_plan": {"items": [
            {"category": "Routing", "check": "EXAMPLE check 1"},
            {"category": "Routing", "check": "EXAMPLE check 2"},
            {"category": "Link", "check": "EXAMPLE check 3"},
        ]},
        "service_map": {"services": [
            {"service": "ssh", "category": "management", "port": 22, "proto": "tcp"},
            {"service": "ssh", "category": "management", "port": 2222, "proto": "tcp"},
            {"service": "ssh", "category": "management", "port": 22, "proto": "tcp"},
        ]},
        "application_intelligence": {"domains": [{"domain": "EXAMPLE app", "switches": []}]},
        "multicast_intelligence": {"pim": True},
        "design_nrfu": {
            "items": [{"decision_id": "EXAMPLE-design", "description": "EXAMPLE design instruction",
                       "setup": "EXAMPLE design setup", "pass_criteria": "EXAMPLE design pass",
                       "devices": ["EXAMPLE-SW"]}],
            "evpn_acceptance": [{"decision_id": "EXAMPLE-evpn", "description": "EXAMPLE EVPN instruction",
                                 "pass_criteria": "EXAMPLE EVPN pass"}],
            "n_items": 999,
        },
    }
    out = tmp_path / "counts.docx"
    write_nrfu_docx(str(out), snap, "EXAMPLE exact rendered counts")
    doc = Document(out)
    tables = [[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables]
    summary = next(table for table in tables if table[0] == ["Phase", "Coverage", "Tests"])
    results = next(table for table in tables if table[0] == ["Phase", "Total", "Pass", "Fail", "Deviations / notes"])
    rows = [row for table in tables for row in table[1:]]
    phase1 = [row for row in rows if row[0].startswith("NRFU-I-")]
    phase2 = [row for row in rows if row[0].startswith("NRFU-II-")]
    phase3 = [row for row in rows if row[0].startswith("NRFU-III-")]
    design = [row for row in rows if row[0] == "EXAMPLE-design"]
    evpn = [row for row in rows if row[0] == "EXAMPLE-evpn"]
    assert [len(phase1), len(phase2), len(phase3), len(design), len(evpn)] == [1, 3, 4, 1, 1]
    assert any("tcp/22" == row[2].split()[-1] for row in phase3)
    assert any("tcp/2222" == row[2].split()[-1] for row in phase3)
    expected = [len(phase1), len(phase2), len(phase3), len(design), len(evpn)]
    assert [int(row[2]) for row in summary[1:-1]] == expected
    assert [int(row[1]) for row in results[1:-1]] == expected
    assert int(summary[-1][2]) == int(results[-1][1]) == sum(expected) == 10
    categories = next(p.text for p in doc.paragraphs if p.text.startswith("Phase II tests by category:"))
    assert categories == "Phase II tests by category: Routing 2 · Link 1"
    assert evpn[0][3] == "EXAMPLE EVPN instruction" and evpn[0][5] == "EXAMPLE EVPN pass"
    assert evpn[0][-1] == ""



def test_nrfu_keeps_all_persisted_acceptance_rows_without_recomputation(tmp_path, monkeypatch):
    import copy

    from docx import Document

    from backend.nrfu_docx import write_nrfu_docx
    from cisco_toolkit import design_advisor

    def forbidden(*_args, **_kwargs):
        raise AssertionError("rendering must not derive acceptance from the current blueprint")

    monkeypatch.setattr(design_advisor, "compute_design_nrfu", forbidden)
    items = [{
        "decision_id": f"EXAMPLE-{index}", "title": f"EXAMPLE retained title {index}",
        "priority": "High", "phase": "EXAMPLE retained phase",
        "description": f"EXAMPLE persisted description {index}",
        "setup": f"EXAMPLE persisted setup {index}",
        "pass_criteria": f"EXAMPLE persisted pass criterion {index}",
        "devices": [f"EXAMPLE-device-{index}"], "principle_citation": f"EXAMPLE source {index}",
    } for index in range(45)]
    snap = {
        "devices": {},
        "design_blueprint": {"decisions": [{"id": item["decision_id"], "status": "recommended",
                                              "title": "EXAMPLE different blueprint title"} for item in items]},
        "design_nrfu": {"items": items, "evpn_acceptance": [
            {**items[0], "decision_id": "EXAMPLE-EVPN", "description": "EXAMPLE persisted EVPN description"},
        ]},
    }
    original = copy.deepcopy(snap)
    out = tmp_path / "all-acceptance.docx"
    write_nrfu_docx(str(out), snap, "EXAMPLE retained source")
    doc = Document(out)
    rows = [[cell.text for cell in row.cells] for table in doc.tables for row in table.rows]
    text = "\n".join("\n".join(row) for row in rows)
    for item in items:
        row = next(row for row in rows if row[0] == item["decision_id"])
        for field in ("title", "priority", "phase", "description", "setup", "pass_criteria", "principle_citation"):
            assert item[field] in "\n".join(row)
        assert row[6] == item["devices"][0] and row[-1] == ""
    assert "EXAMPLE persisted EVPN description" in text
    assert "5 more decision(s)" in "\n".join(p.text for p in doc.paragraphs)
    assert next(row for row in rows if row[0] == "Total")[2] == "46"
    assert next(row for row in rows if row[0] == "Overall")[1] == "46"
    assert snap == original



def test_nrfu_category_summary_preserves_multiline_and_falsey_category_identity(tmp_path):
    from docx import Document

    from backend.nrfu_docx import write_nrfu_docx

    snap = {"devices": {}, "validation_plan": {"items": [
        {"category": "Routing\nA"}, {"category": "Routing\nB"},
        {"category": 0}, {"category": False},
    ]}}
    out = tmp_path / "category-identity.docx"
    write_nrfu_docx(str(out), snap, "EXAMPLE category identity")
    doc = Document(out)
    summary = next(p.text for p in doc.paragraphs if p.text.startswith("Phase II tests by category:"))
    assert summary == "Phase II tests by category: — 2 · Routing\nA 1 · Routing\nB 1"
    rows = [[cell.text for cell in row.cells] for table in doc.tables for row in table.rows]
    assert len([row for row in rows if row[0].startswith("NRFU-II-")]) == 4
