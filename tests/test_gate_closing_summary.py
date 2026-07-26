"""The closing gate summary is the LAST thing the operator sees — it must not lie about the record.

Phase 42 of ``COLLECT_PARSE_V3_23_0._stage_finalize`` restates withheld deliverables at ERROR, after
thousands of ``[OK]`` lines, precisely so "not observed" cannot read as healthy on the final line. That
makes every claim IN it load-bearing, and three were wrong:

1. **"Sealed in the run manifest's 'gate' step" was derived from the manifest FILE EXISTING.**
   ``write_json_file`` leaves the previous manifest intact when it fails, so a re-run to the same
   ``--output`` whose seal failed left an EARLIER run's manifest on disk and satisfied the existence
   check. Reproduced end-to-end: an approved run, then a revoked run whose manifest write failed,
   ended on "Sealed in the run manifest's 'gate' step" three lines below "manifest write FAILED" —
   with ``proceed=true`` still on disk for both deliverables that run had just withheld. This repo's
   "existence != delivery" class (a name check certifying content it never read).
2. **"the only durable record of them is now lost"** was true only while a refusal wrote nothing to
   the ledger. It now appends a durable ``refuse`` row, so the sentence sent an auditor hunting for
   evidence sitting exactly where it belongs.
3. **Remediation collapsed to one status.** A run can withhold the design over a missing approval
   (fixable by ``approve``) and the MOP over an unreadable ledger (fixable only by repairing the
   file); naming one left the other unactionable.

These tests drive ``_stage_finalize`` directly rather than a full ``main()``: the seal outcome is
threaded inside that one function, and a full run costs ~17s per invocation with nothing else to say.
"""
import json
import logging
import os
import sys
import types
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402
from cisco_toolkit import gate_state   # noqa: E402

MANIFEST_SUFFIX = ".run_manifest.json"


@pytest.fixture(autouse=True)
def _clean_ledger():
    """The verdict ledger is process-global; one test's verdicts must never reach another's summary."""
    gate_state.reset_verdicts()
    yield
    gate_state.reset_verdicts()


def _ctx(tmp_path):
    """The six fields `_stage_finalize` reads. A real workbook file must exist for the manifest to
    hash; its CONTENT is irrelevant to the gate summary."""
    xlsx = tmp_path / "wb.xlsx"
    xlsx.write_text("workbook", encoding="utf-8")
    args = types.SimpleNamespace(redact_collection=False, no_perf=True)
    return types.SimpleNamespace(out_xlsx=str(xlsx), snap_dict={}, root_dir=str(tmp_path),
                                 args=args, all_devices_meta=[], workers=1)


def _finalize(tmp_path, caplog, fail_manifest=False):
    """Run phase 39-42 and return the captured ERROR/WARNING text."""
    ctx = _ctx(tmp_path)
    real = cp.write_json_file

    def _boom(path, obj, **kw):
        if str(path).endswith(MANIFEST_SUFFIX):
            raise OSError(13, "Permission denied")
        return real(path, obj, **kw)

    with caplog.at_level(logging.WARNING, logger="CiscoMigrationAutofillV3_14_6"):
        if fail_manifest:
            with mock.patch.object(cp, "write_json_file", _boom):
                cp._stage_finalize(ctx)
        else:
            cp._stage_finalize(ctx)
    return caplog.text


def _refuse(tmp_path, generator="design", **gates):
    """Record a real refusal by driving enforce() against a ledger, so the verdict rows under test
    come from the PRODUCER, never hand-built to the shape the summary expects."""
    docs = tmp_path / "eng" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "gates": {g: {"decision": d} for g, d in gates.items()},
                    "audit": []}), encoding="utf-8")
    return gate_state.enforce(generator, root=str(tmp_path / "eng"))


# ------------------------------------------------------------------ 1. the stale-manifest false claim

def test_summary_does_not_claim_sealed_when_this_runs_write_failed(tmp_path, caplog):
    """THE CRITICAL ONE. A manifest from an earlier run to the same --output is still on disk, so an
    existence check says "sealed" — while this run sealed nothing."""
    # A previous, successful run leaves its manifest at the path this run will use.
    _refuse(tmp_path, "design", lld_approved="approved")
    _finalize(tmp_path, caplog)
    manifest = os.path.join(str(tmp_path), "wb" + MANIFEST_SUFFIX)
    assert os.path.isfile(manifest), "precondition: an earlier manifest must exist on disk"
    caplog.clear()

    # This run refuses and its manifest write FAILS.
    gate_state.reset_verdicts()
    _refuse(tmp_path, "design", lld_approved="approved")
    text = _finalize(tmp_path, caplog, fail_manifest=True)

    assert "[GATE]" in text, "the closing gate summary did not run"
    assert "NOT SEALED" in text, \
        ("the summary claimed the verdict was sealed while THIS run's manifest write failed -- "
         "derived from the file existing, not from the write succeeding")
    assert "Sealed in the run manifest's 'gate' step." not in text
    # The dangerous part is that a file IS there: the operator must be told not to read it.
    assert "EARLIER run" in text and "does NOT describe this run" in text, \
        "the operator was not warned that the manifest on disk belongs to a different run"


def test_summary_says_plainly_not_sealed_when_no_manifest_exists_at_all(tmp_path, caplog):
    """The other arm: nothing on disk to mistake for this run's record, so no stale-file warning —
    but still never 'sealed'."""
    _refuse(tmp_path, "design", lld_approved="approved")
    text = _finalize(tmp_path, caplog, fail_manifest=True)
    assert "NOT SEALED" in text
    assert "EARLIER run" not in text, "warned about a stale manifest that does not exist"


def test_summary_claims_the_seal_only_when_the_write_really_succeeded(tmp_path, caplog):
    """Non-vacuity guard for the two above: on a healthy run the claim must still be made, or the
    tests above would pass against code that simply never says 'sealed'."""
    _refuse(tmp_path, "design", lld_approved="approved")
    text = _finalize(tmp_path, caplog)
    assert "Sealed in the run manifest's 'gate' step." in text
    assert "NOT SEALED" not in text


# --------------------------------------------------- 2. "the only durable record" is no longer true

def test_manifest_failure_names_the_ledger_as_the_durable_record(tmp_path, caplog):
    """A refusal over missing approvals writes a durable `refuse` row. Telling the operator the only
    record is lost, while that row sits in the ledger this same run wrote, is a false alarm."""
    v = _refuse(tmp_path, "design", lld_approved="approved")
    assert v.recorded is True, "precondition: the durable ledger row must have been written"
    text = _finalize(tmp_path, caplog, fail_manifest=True)

    assert "the only durable record of them is now lost" not in text, \
        "the run declared the record lost while the gate ledger holds it"
    assert "gate ledger still holds the durable row" in text
    assert "Durable ledger row(s) written for design" in text


def test_summary_reports_a_refusal_that_reached_NO_durable_record(tmp_path, caplog):
    """The opposite direction, and the reason this is read from `recorded` rather than assumed: a
    refusal whose ledger write failed must NOT be reported as durably recorded."""
    docs = tmp_path / "eng" / "docs"
    docs.mkdir(parents=True)
    (docs / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "gates": {"lld_approved": {"decision": "approved"}}, "audit": []}),
        encoding="utf-8")
    with mock.patch.object(os, "replace", side_effect=PermissionError(5, "Access is denied")):
        v = gate_state.enforce("design", root=str(tmp_path / "eng"))
    assert v.refused and v.recorded is False, "precondition: the ledger write must have failed"

    text = _finalize(tmp_path, caplog)
    assert "NO durable ledger row for design" in text
    assert "Durable ledger row(s) written for design" not in text


# ------------------------------------------------------------------ 3. per-status remediation advice

def test_remediation_for_an_unreadable_ledger_is_actionable_for_THAT_status(tmp_path, caplog):
    """An unreadable ledger cannot be fixed by `approve`, by an override, or by changing the gate
    root — the file must be repaired or removed. Advice naming anything else is unactionable on the
    last line the operator reads."""
    docs = tmp_path / "eng" / "docs"
    docs.mkdir(parents=True)
    (docs / "engagement-state.json").write_text("{not json", encoding="utf-8")
    v = gate_state.enforce("design", root=str(tmp_path / "eng"))
    assert v.status == "unreadable", "precondition"

    text = _finalize(tmp_path, caplog)
    assert "[unreadable]" in text, "the summary did not name the status it is advising on"
    assert "repair or remove" in text
    assert "NOT overridable" in text


def test_remediation_covers_EVERY_refused_status_not_just_the_worst(tmp_path, caplog):
    """A mixed run is the case a collapsed message gets wrong: one deliverable fixable by recording
    an approval, another needing the ledger repaired. Both must be told how."""
    eng_ok = tmp_path / "ok"
    (eng_ok / "docs").mkdir(parents=True)
    (eng_ok / "docs" / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "gates": {"lld_approved": {"decision": "approved"}}, "audit": []}),
        encoding="utf-8")
    bad = tmp_path / "bad"
    (bad / "docs").mkdir(parents=True)
    (bad / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")

    a = gate_state.enforce("design", root=str(eng_ok))       # pending
    b = gate_state.enforce("mop", root=str(bad))             # unreadable
    assert {a.status, b.status} == {"pending", "unreadable"}, "precondition: two distinct statuses"

    text = _finalize(tmp_path, caplog)
    assert "[pending]" in text and "[unreadable]" in text, \
        "remediation collapsed to one status, leaving the other deliverable unactionable"
    assert "record the approval" in text and "repair or remove" in text


def test_summary_is_silent_when_nothing_was_refused(tmp_path, caplog):
    """A summary that always prints is one nobody reads — and a spurious [GATE] line on a clean run
    would train operators to ignore the real ones."""
    gate_state.enforce("design", root=str(tmp_path))         # no ledger -> ungated, proceeds
    text = _finalize(tmp_path, caplog)
    assert "WITHHELD" not in text
