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


def _observed_l2_receipt(*, gate_status="observed_survival") -> dict:
    def phase(snapshot_id, collected_at):
        return {
            "source": "persisted snapshots.snapshot_json blob",
            "source_id": f"snapshot:{snapshot_id}",
            "campaign_id": 7,
            "engagement_id": "ENG-L2",
            "sha256": "sha256:" + str(snapshot_id).zfill(64),
            "bytes": 4000 + snapshot_id,
            "collected_at": collected_at,
            "custody_at": collected_at,
        }

    observed = {
        "schema": "observed_l2_failure_evidence/1",
        "status": "observed_survival",
        "assurance_level": "local_safety_preservation",
        "family": "etherchannel",
        "subject": "dist1|Po10",
        "failure_scenario": "single_observed_forwarding_member_loss",
        "source_binding": {
            "pre_failure": phase(51, "2026-07-12T11:10:00+00:00"),
            "post_failure": phase(52, "2026-07-12T11:12:00+00:00"),
            "recovery": phase(53, "2026-07-12T11:14:00+00:00"),
            "failure_witness": {
                "encoding": "base64",
                "content_base64": "VEhJU19NVVNUX05PVF9CRV9JTl9USEVfUElS",
                "sha256": "sha256:" + "f" * 64,
                "bytes": 27,
                "induced_at": "2026-07-12T11:11:00+00:00",
            },
        },
        "precondition": {"status": "passed", "evidence": {}},
        "failure_witness": {"status": "witnessed", "evidence": {}},
        "post_failure": {"status": "survived", "evidence": {}},
        "recovery": {"status": "recovered", "evidence": {}},
        "claims": {
            "local_scenario": "observed_survival",
            "service_path_survival": "not_verified",
            "traffic_continuity": "not_verified",
            "convergence": "not_verified",
        },
        "failures": ["one", "two"],
        "limitations": ["Exact local scenario only."],
    }
    return {
        "id": 19,
        "created_at": "2026-07-12T11:15:00+00:00",
        "cutover_verdict": "PASS",
        "receipt_sha256": "sha256:" + "9" * 64,
        "receipt": {
            "schema": "execution_comparison_receipt/1",
            "before_snapshot_id": 41,
            "after_snapshot_id": 53,
            "receipt_sha256": "sha256:" + "9" * 64,
            "comparison": {
                "comparison_admission": {
                    "status": "admitted",
                    "source_binding": {
                        "before": {"snapshot_id": 41, "sha256": "sha256:" + "a" * 64,
                                   "bytes": 3900},
                        "after": {"snapshot_id": 53, "sha256": "sha256:" + "b" * 64,
                                  "bytes": 4053},
                    },
                },
                "cutover_gate": {
                    "schema": "cutover_gate/1",
                    "verdict": "PASS" if gate_status == "observed_survival" else "INDETERMINATE",
                    "operator_note": "Canonical context-bound local trial decision.",
                    "l2_observed_trial_status": gate_status,
                    "l2_observed_trial_assurance": (
                        "local_safety_preservation"
                        if gate_status == "observed_survival" else "not_verified"
                    ),
                    "l2_observed_trial_family": "etherchannel",
                    "l2_observed_trial_subject": "dist1|Po10",
                    "l2_observed_trial_scenario": "single_observed_forwarding_member_loss",
                    "l2_observed_trial_matched_projected_risks": 1,
                    "l2_observed_trial_note": "Exact recovery binding accepted for the local member-loss scenario.",
                },
                "operator_evidence": {
                    "rehearsal": {"observed_l2_failure_evidence": observed},
                },
                "comparison_receipt": {"payload_sha256": "sha256:" + "c" * 64},
            },
        },
    }


def test_pir_renders_context_bound_observed_local_trial_custody_and_claim_boundary(tmp_path):
    state = _minimal_state(finished=True)
    receipt = _observed_l2_receipt()
    binding = receipt["receipt"]["comparison"]["operator_evidence"]["rehearsal"][
        "observed_l2_failure_evidence"
    ]["source_binding"]
    # The displayed clock values look reversed if offsets are stripped, but represent a valid
    # source-owned order: 14:10+03 == 11:10Z, then 11:12Z, then 11:14Z.
    binding["pre_failure"]["collected_at"] = "2026-07-12T14:10:00+03:00"
    binding["pre_failure"]["custody_at"] = "2026-07-12T14:10:30+03:00"
    state["comparison_receipts"] = [receipt]
    out = str(tmp_path / "pir_observed_l2.docx")
    P.write_pir_docx(out, state, "observed")
    text = _text_of(out)

    assert "Observed local L2 failure-trial evidence" in text
    assert "OBSERVED SURVIVAL" in text
    assert "local safety preservation: VERIFIED for this exact scenario only" in text
    assert "dist1|Po10" in text
    assert "single_observed_forwarding_member_loss" in text
    assert "matched local projected risks: 1" in text
    assert "validation failures: 2" in text
    assert "snapshot:51" in text and "snapshot:52" in text and "snapshot:53" in text
    assert "ENG-L2" in text and "4053 exact bytes" in text
    assert "service-path survival: NOT VERIFIED" in text
    assert "traffic continuity: NOT VERIFIED" in text
    assert "convergence: NOT VERIFIED" in text
    assert "raw base64 intentionally omitted" in text
    assert "VEhJU19NVVNUX05PVF9CRV9JTl9USEVfUElS" not in text
    assert "2026-07-12T14:10:00+03:00" in text
    assert "2026-07-12T11:12:00+00:00" in text
    assert "Exact recovery binding accepted for the local member-loss scenario." in text
    assert "Validation failure" in text and "one" in text and "two" in text
    assert "Limitation" in text and "Exact local scenario only." in text


def test_pir_uses_context_bound_gate_status_and_discloses_unresolved_retrial(tmp_path):
    state = _minimal_state(finished=True)
    state["outcome"] = execution.OUTCOME_PARTIAL
    state["comparison_receipts"] = [_observed_l2_receipt(gate_status="not_verified")]
    state["l2_failure_trial_requirement"] = {
        "schema": "execution_l2_failure_trial_requirement/1",
        "family": "etherchannel",
        "subject": "dist1|Po10",
        "failure_scenario": "single_observed_forwarding_member_loss",
        "status": "not_verified",
        "latest_receipt_id": 19,
        "phase_sources": {
            "pre_failure": {"snapshot_id": 51, "collected_at": "2026-07-12T11:10:00+00:00",
                            "uploaded_at": "2026-07-12T11:10:30+00:00"},
            "post_failure": {"snapshot_id": 52, "collected_at": "2026-07-12T11:12:00+00:00",
                             "uploaded_at": "2026-07-12T11:12:30+00:00"},
            "recovery": {"snapshot_id": 53, "collected_at": "2026-07-12T11:14:00+00:00",
                         "uploaded_at": "2026-07-12T11:14:30+00:00"},
        },
    }
    out = str(tmp_path / "pir_observed_l2_requirement.docx")
    P.write_pir_docx(out, state, "observed")
    text = _text_of(out)

    # The detached audit receipt still says observed_survival, but the comparison gate rejected its
    # binding. The PIR must follow the gate and retain the execution ratchet.
    assert "NOT VERIFIED" in text
    assert "local safety preservation: NOT VERIFIED" in text
    assert "local safety preservation: VERIFIED" not in text
    assert "Unresolved observed local L2 re-trial requirement" in text
    assert "Only a strictly newer observed-survival trial" in text
    assert "snapshot:51" in text and "snapshot:53" in text
    assert "this execution cannot receive a SUCCESSFUL outcome" in text


def test_pir_preserves_same_second_observed_phase_microsecond_order(tmp_path):
    state = _minimal_state(finished=True)
    receipt = _observed_l2_receipt()
    observed = receipt["receipt"]["comparison"]["operator_evidence"]["rehearsal"][
        "observed_l2_failure_evidence"
    ]
    binding = observed["source_binding"]
    binding["pre_failure"]["collected_at"] = "2026-07-12T14:10:00.000001+03:00"
    binding["pre_failure"]["custody_at"] = "2026-07-12T14:10:00.000001+03:00"
    binding["failure_witness"]["induced_at"] = "2026-07-12T11:10:00.000002+00:00"
    binding["post_failure"]["collected_at"] = "2026-07-12T11:10:00.000003+00:00"
    binding["post_failure"]["custody_at"] = "2026-07-12T11:10:00.000003+00:00"
    binding["recovery"]["collected_at"] = "2026-07-12T11:10:00.000004+00:00"
    binding["recovery"]["custody_at"] = "2026-07-12T11:10:00.000004+00:00"
    state["comparison_receipts"] = [receipt]
    out = str(tmp_path / "pir_observed_l2_microseconds.docx")

    P.write_pir_docx(out, state, "observed")
    text = _text_of(out)

    assert "2026-07-12T14:10:00.000001+03:00" in text
    assert "2026-07-12T11:10:00.000002+00:00" in text
    assert "2026-07-12T11:10:00.000003+00:00" in text
    assert "2026-07-12T11:10:00.000004+00:00" in text
