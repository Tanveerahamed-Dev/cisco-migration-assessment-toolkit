"""Durability + auditability of the sealed run manifest (the chain-of-custody artifact).

Three properties, each of which was absent or unproven before:

1. ATOMIC WRITE. `write_json_file` used a plain `open(path, "w")`, which truncates the good file
   BEFORE the new bytes are written. A crash in that window (ADR-0004 P3: a USB unplug mid-write)
   left neither the old manifest nor a complete new one -- destroying exactly the tamper-evidence
   the `chain_root` seal exists to provide. The tests below kill the write mid-flight, with an
   `Exception` AND with a `KeyboardInterrupt` (the unplug/Ctrl-C class that `except Exception`
   does not catch), and require the previous file to survive byte-for-byte with no leaked temp.

2. GATE VERDICTS ARE SEALED. A refused deliverable is now recorded in the manifest's `gate` stage,
   so an ABSENT design/MOP is distinguishable from one that was never requested. The seal is proven
   NON-VACUOUS: editing a recorded verdict must break the hash chain.

3. THE VERDICT IS COVERAGE-HONEST. `ungated` (no gate ledger at all -> brownfield warn-and-proceed)
   must never be recorded as `approved`. That conflation is the "not observed silently becomes
   healthy" failure applied to governance.

Overwrite policy is DECIDED, not accidental, and pinned here: the manifest is a per-run seal of the
artifact set beside it, replaced by a re-run to the same --output exactly as its artifacts are.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module owning write_json_file)
from cisco_toolkit import gate_state as gs   # noqa: E402
from cisco_toolkit import manifest as m      # noqa: E402


def _tmps_in(d):
    return [f for f in os.listdir(d) if ".tmp" in f]


# ---------------------------------------------------------------- 1. atomic write

@pytest.mark.parametrize("boom", [RuntimeError("disk full"), KeyboardInterrupt()])
def test_crash_mid_write_preserves_the_previous_manifest(tmp_path, monkeypatch, boom):
    """The whole point: a torn write must not consume the file that was already there.

    KeyboardInterrupt is parametrized deliberately -- it is a BaseException, so a cleanup guarded by
    `except Exception` would leak the temp file for precisely the signal (Ctrl-C / SIGTERM on unplug)
    this protection exists for.
    """
    path = str(tmp_path / "assessment.run_manifest.json")
    cp.write_json_file(path, {"chain_root": "original", "seq": 1})
    before = open(path, encoding="utf-8").read()

    def exploding_dump(*a, **k):
        raise boom
    monkeypatch.setattr(cp.json, "dump", exploding_dump)

    with pytest.raises(type(boom)):
        cp.write_json_file(path, {"chain_root": "replacement", "seq": 2})

    assert open(path, encoding="utf-8").read() == before, "the previous sealed manifest was destroyed"
    assert json.loads(before)["chain_root"] == "original"
    assert _tmps_in(tmp_path) == [], "a temp file leaked beside the artifact"


def test_crash_before_any_manifest_exists_leaves_no_partial_file(tmp_path, monkeypatch):
    """With no prior file, a torn write must leave NOTHING -- never a truncated JSON that a reader
    would try to parse (or worse, that `verify_chain` would report on)."""
    path = str(tmp_path / "assessment.run_manifest.json")
    monkeypatch.setattr(cp.json, "dump", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        cp.write_json_file(path, {"chain_root": "x"})

    assert not os.path.exists(path)
    assert _tmps_in(tmp_path) == []


def test_successful_write_is_complete_and_leaves_no_temp(tmp_path):
    path = str(tmp_path / "nested" / "out.json")     # also pins makedirs on a fresh subdir
    cp.write_json_file(path, {"a": 1, "b": [1, 2]})
    assert json.load(open(path, encoding="utf-8")) == {"a": 1, "b": [1, 2]}
    assert _tmps_in(tmp_path / "nested") == []


# ---------------------------------------------------------------- 2. verdicts are sealed

def _manifest_with(tmp_path, verdicts):
    out_xlsx = str(tmp_path / "assessment.xlsx")
    open(out_xlsx, "w").close()                       # one artifact for the deliver stage to hash
    return cp.build_run_manifest(out_xlsx, {}, verdicts)


def _gate_step(man):
    return next(r for r in man["chain"] if r.get("stage") == "gate")


def test_gate_verdicts_are_recorded_and_sealed(tmp_path):
    verdicts = [{"gate": "design", "proceeded": False, "disposition": "refused",
                 "missing_approvals": ["assessment_approved"]}]
    man = _manifest_with(tmp_path, verdicts)

    step = _gate_step(man)
    assert step["verdicts"] == verdicts
    ok, broken = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is True and broken == []


def test_editing_a_recorded_verdict_breaks_the_seal(tmp_path):
    """Non-vacuous: if a refusal could be quietly rewritten to an approval without breaking the
    chain, sealing the verdicts would be decoration."""
    man = _manifest_with(tmp_path, [{"gate": "design", "proceeded": False,
                                     "disposition": "refused", "missing_approvals": []}])
    ok, _ = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is True                                  # clean before tampering

    _gate_step(man)["verdicts"][0]["disposition"] = "approved"
    ok, broken = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is False and broken, "a rewritten gate verdict verified clean"


def test_gate_stage_precedes_deliver(tmp_path):
    """Chronology is part of the record: the gates decide what `deliver` is allowed to contain."""
    man = _manifest_with(tmp_path, [])
    stages = [r.get("stage") for r in man["chain"]]
    assert stages.index("gate") < stages.index("deliver")


def test_manifest_without_verdicts_still_seals(tmp_path):
    """Back-compat: callers that pass nothing (and --no-design/--no-mop runs) still produce a valid
    chain, with an explicitly EMPTY verdict list rather than a missing stage."""
    man = cp.build_run_manifest(str(tmp_path / "a.xlsx"), {})
    assert _gate_step(man)["verdicts"] == []
    ok, _ = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is True


# ---------------------------------------------------------------- 3. verdicts are honest

def test_ungated_run_is_not_recorded_as_approved(tmp_path):
    """No store at all -> enforce() warn-and-proceeds (brownfield). Recording that as `approved`
    would forge a governance decision nobody made."""
    v = cp._gate_verdict("design", True, None, root=str(tmp_path))
    assert v["disposition"] == "ungated"
    assert v["proceeded"] is True


def test_approved_and_overridden_are_distinguishable(tmp_path):
    gs.record_decision("assessment_approved", "approved", root=str(tmp_path), by="tester")
    approved = cp._gate_verdict("design", True, None, root=str(tmp_path))
    assert approved["disposition"] == "approved"
    assert approved["missing_approvals"] == []

    overridden = cp._gate_verdict("design", True, "shipping anyway", root=str(tmp_path))
    assert overridden["disposition"] == "overridden"


def test_refusal_is_recorded_with_what_was_missing(tmp_path):
    """A store that exists but withholds approval: the refusal, and its cause, land in the record."""
    gs.record_decision("assessment_approved", "revoked", root=str(tmp_path), by="tester")
    v = cp._gate_verdict("design", False, None, root=str(tmp_path))
    assert v["disposition"] == "refused" and v["proceeded"] is False
    assert "assessment_approved" in v["missing_approvals"]


def test_unreadable_ledger_does_not_break_the_seal(tmp_path):
    """An unreadable store makes enforce() refuse; building the record must still succeed (the seal
    is not allowed to fail because governance state is broken) and must report the refusal."""
    store = tmp_path / "docs" / "engagement-state.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{ this is not json", encoding="utf-8")
    v = cp._gate_verdict("design", False, None, root=str(tmp_path))
    assert v["disposition"] == "refused"


# ---------------------------------------------------------------- overwrite policy (decided)

def test_rerun_replaces_the_manifest_atomically(tmp_path):
    """DECIDED policy, pinned so it cannot drift into an accident: the manifest is a PER-RUN seal of
    the artifact set beside it. A re-run to the same --output replaces it exactly as it replaces the
    artifacts it hashes -- a manifest outliving its artifacts would seal files that no longer exist.
    The durable CROSS-run record of human gate decisions is gate_state's audit array, not this file.
    """
    path = str(tmp_path / "assessment.run_manifest.json")
    cp.write_json_file(path, {"chain_root": "run-one"})
    cp.write_json_file(path, {"chain_root": "run-two"})
    assert json.load(open(path, encoding="utf-8"))["chain_root"] == "run-two"
    assert _tmps_in(tmp_path) == []


def test_gate_state_audit_is_the_cross_run_ledger(tmp_path):
    """The counterpart to the above: what the manifest deliberately does NOT keep, the gate ledger
    does -- appended across runs, so the engagement's decision history survives re-runs."""
    gs.record_decision("assessment_approved", "approved", root=str(tmp_path), by="a")
    gs.record_decision("assessment_approved", "revoked", root=str(tmp_path), by="b")
    store, _ = gs.load_store(str(tmp_path))
    events = [e.get("event") for e in store["audit"]]
    assert events == ["approve", "revoke"], "the cross-run decision history did not accumulate"
