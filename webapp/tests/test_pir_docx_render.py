"""Renderer smoke tests for webapp.backend.pir_docx.write_pir_docx (P3-W2, part 2).

Complements test_pir_docx.py (the pure formatters) by exercising the FULL 221-line renderer end to
end: does it turn a run state into a valid .docx across the finished and in-flight paths without
crashing? The state here is a minimal-but-VALID execution state built to the documented contract
(execution.progress + write_pir_docx reads) — a legitimate test structure, NOT a guessed device
fixture. Empty waves keep the per-wave shape out of scope while still driving the title page, document
control, all five section headers, the summary roll-up, the related-documents cross-reference, and the
sign-off table. Skips cleanly when python-docx is not installed (the docx extra is optional).
"""
import pytest

from webapp.backend import execution
from webapp.backend import pir_docx as P

docx = pytest.importorskip("docx")   # optional [docx] extra -> skip, never a false fail


def _minimal_state(*, finished: bool) -> dict:
    """A valid run state with no waves/events. tz-AWARE timestamps: progress() falls back to
    datetime.now(utc) for an open run, so a naive started_at would raise on the subtraction — the
    real _now() is tz-aware, and this mirrors it."""
    return {
        "label": "Test cutover run",
        "operator": "test-lead",
        "status": "completed" if finished else "in_progress",
        "outcome": execution.OUTCOME_SUCCESS if finished else None,
        "started_at": "2026-07-12T10:00:00+00:00",
        "ended_at": "2026-07-12T11:30:00+00:00" if finished else None,
        "plan_summary": {"est_window_minutes": 90},
        "waves": [],
        "events": [],
    }


def _text_of(path: str) -> str:
    document = docx.Document(path)
    paragraphs = [p.text for p in document.paragraphs]
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def test_write_pir_docx_finished_run(tmp_path):
    out = str(tmp_path / "pir.docx")
    P.write_pir_docx(out, _minimal_state(finished=True), "Assessment_2026-06-13")
    text = _text_of(out)
    assert "Post-Implementation Review" in text          # title rendered
    assert "As-Executed Cutover Record" in text
    assert execution.OUTCOME_SUCCESS in text             # the derived outcome is surfaced
    assert "INTERIM" not in text                         # a finished run is NOT flagged interim


def test_write_pir_docx_in_progress_flags_interim(tmp_path):
    out = str(tmp_path / "pir_interim.docx")
    P.write_pir_docx(out, _minimal_state(finished=False), "Assessment_2026-06-13")
    text = _text_of(out)
    assert "Post-Implementation Review" in text
    assert "INTERIM" in text                             # an open run carries the point-in-time caveat


def test_write_pir_docx_is_a_valid_openable_docx(tmp_path):
    """The output must be a real, openable .docx with the five review sections — not a truncated or
    corrupt file (the failure mode that text-extraction QA is blind to)."""
    out = str(tmp_path / "pir_valid.docx")
    P.write_pir_docx(out, _minimal_state(finished=True), "SnapshotLabel")
    text = _text_of(out)
    for heading in ("Document control", "1. Execution summary", "2. Planned vs actual",
                    "3. Per-wave as-executed log", "4. Timeline", "5. Review & sign-off"):
        assert heading in text, f"missing section heading: {heading!r}"


def test_pir_renders_bound_before_after_receipt_and_latest_canonical_gate(tmp_path):
    state = _minimal_state(finished=True)
    state["comparison_policy"] = {
        "schema": "execution_comparison_policy/1",
        "canonical_gate_required": True,
    }
    state["comparison_receipts"] = [{
        "id": 9,
        "created_at": "2026-07-12T11:20:00+00:00",
        "cutover_verdict": "PASS",
        "receipt_sha256": "sha256:" + "9" * 64,
        "receipt": {
            "schema": "execution_comparison_receipt/1",
            "before_snapshot_id": 41,
            "after_snapshot_id": 42,
            "receipt_sha256": "sha256:" + "9" * 64,
            "comparison": {
                "comparison_admission": {
                    "status": "admitted",
                    "source_binding": {
                        "before": {"snapshot_id": 41, "sha256": "sha256:" + "a" * 64,
                                   "bytes": 1234},
                        "after": {"snapshot_id": 42, "sha256": "sha256:" + "b" * 64,
                                  "bytes": 1250},
                    },
                },
                "cutover_gate": {
                    "schema": "cutover_gate/1",
                    "verdict": "PASS",
                    "operator_note": "Canonical PASS from the stored before/after evidence.",
                },
                "comparison_receipt": {"payload_sha256": "sha256:" + "c" * 64},
            },
        },
    }]
    out = str(tmp_path / "pir_receipt.docx")
    P.write_pir_docx(out, state, "Assessment_2026-06-13")
    text = _text_of(out)
    assert "Canonical post-change comparison receipts" in text
    assert "LATEST" in text and "41" in text and "42" in text
    assert "sha256:" + "a" * 64 in text
    assert "sha256:" + "b" * 64 in text
    assert "Canonical PASS from the stored before/after evidence." in text


def test_pir_discloses_legacy_execution_has_no_backfilled_receipt(tmp_path):
    out = str(tmp_path / "pir_legacy_receipt.docx")
    P.write_pir_docx(out, _minimal_state(finished=True), "legacy")
    assert "legacy execution is not reinterpreted or backfilled" in _text_of(out)
