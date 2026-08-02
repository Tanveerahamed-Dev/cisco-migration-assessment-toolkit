"""The PPDIOO gate verdict must survive the run — in the engine log AND, authoritatively, in the seal.

`cisco_toolkit.gate_state` logs its verdicts on the `cisco_toolkit.gate_state` logger, but
`COLLECT_PARSE_V3_23_0.setup_logging` used to configure only `CiscoMigrationAutofillV3_14_6`. With no
root handler either, gate records fell through to `logging.lastResort`: WARNING+ hit bare stderr and
INFO was discarded. Two defects followed, both pinned here:

1. **A refusal left no durable trace.** Grepping `cisco_migration_autofill_*.log` for `GATE REFUSED`
   after a refused run returned nothing. An OVERRIDE always persisted (it appends an audit line to the
   store); the refused and brownfield-ungated cases did not — the exact asymmetry that matters for a
   control whose overrides DEC-003 says are reviewed weekly.
2. **It was fragile.** Any `logging.basicConfig()` in the import graph, or a root handler that is not
   stderr, silently changed or swallowed those records.

The fix has two halves and this file pins both: `_attach_package_logging` puts the `cisco_toolkit.*`
tree on the engine's handlers with `propagate = False`, and `enforce()` records every verdict
structurally so `build_run_manifest` can seal it into the manifest's hash chain. The two are
COMPLEMENTARY, not ranked: the sealed row is tamper-evident but is written only in the last stage,
while the log line is editable plain text but is written at the instant of the verdict and so is what
survives a crash in between. Tests below therefore assert BOTH that the verdict reaches the log and
that the seal BREAKS when a verdict is edited out — a record that can be quietly deleted is not an
audit trail.
"""
import ast
import inspect
import json
import logging
import os
import sys
import textwrap
import types

import pytest
from openpyxl import Workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import COLLECT_PARSE_V3_23_0 as cp   # noqa: E402  (the entry module owning setup_logging + the manifest)
from cisco_toolkit import gate_state, manifest as M   # noqa: E402

_TRACKED = ("CiscoMigrationAutofillV3_14_6", "cisco_toolkit", "")


@pytest.fixture(autouse=True)
def _clean_ledger():
    """The verdict ledger is process-global; never let one test's verdicts leak into another's seal."""
    gate_state.reset_verdicts()
    yield
    gate_state.reset_verdicts()


@pytest.fixture
def engine_log(tmp_path, monkeypatch):
    """Run `setup_logging()` with cwd inside tmp_path (LOG_FILE is a bare relative name) and yield the
    log path. Restores every logger it touched and CLOSES the handlers it opened — on Windows a live
    FileHandler keeps tmp_path undeletable."""
    monkeypatch.chdir(tmp_path)
    loggers = [logging.getLogger(n) for n in _TRACKED]
    saved = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in loggers]
    before = {id(h) for lg in loggers for h in lg.handlers}
    cp.setup_logging()
    try:
        yield tmp_path / cp.LOG_FILE
    finally:
        # Recompute at TEARDOWN, not before the yield: a test may itself call setup_logging() (the
        # re-entry cases below do), and a handler opened during the test would otherwise never be
        # closed -- which on Windows keeps tmp_path undeletable, the very thing this guards.
        opened = [h for lg in loggers for h in lg.handlers if id(h) not in before]
        for h in dict.fromkeys(opened):
            h.close()
        for lg, handlers, level, propagate in saved:
            lg.handlers[:] = handlers
            lg.level, lg.propagate = level, propagate


def _write_store(root, **decisions):
    """Create a gate-state store under `root` with the given gate -> decision markers."""
    docs = os.path.join(str(root), "docs")
    os.makedirs(docs, exist_ok=True)
    store = {"schema": 1, "gates": {g: {"decision": d} for g, d in decisions.items()}, "audit": []}
    with open(os.path.join(docs, "engagement-state.json"), "w", encoding="utf-8") as f:
        json.dump(store, f)


def _manifest_for(tmp_path):
    """Build the run manifest the engine writes, for a workbook in `tmp_path`."""
    xlsx = os.path.join(str(tmp_path), "wb.xlsx")
    if not os.path.exists(xlsx):
        Workbook().save(xlsx)
    return cp.build_run_manifest(xlsx, {})


def _gate_step(man):
    steps = [s for s in man["chain"] if s.get("stage") == "gate"]
    assert len(steps) == 1, f"expected exactly one sealed gate step, got {len(steps)}"
    return steps[0]


# --------------------------------------------------------------- defect 1: the log had no refusal

def test_gate_refusal_reaches_the_engine_log_file(engine_log, tmp_path):
    """THE regression: a refused run must be greppable in the log an engineer actually consults."""
    _write_store(tmp_path)                                   # store exists, nothing approved
    assert gate_state.enforce("design", root=str(tmp_path)).proceed is False
    text = engine_log.read_text(encoding="utf-8")
    assert "[GATE REFUSED]" in text, "a gate refusal still does not reach the engine log"
    assert "assessment_approved" in text, "the log names the verdict but not the missing approval"


def test_brownfield_ungated_warning_reaches_the_engine_log_file(engine_log, tmp_path):
    """The other half of the reported gap: 'no gate-state store at ...' was equally invisible.
    Proceeding UNGATED is a disclosure, and a disclosure nobody can find later is not one."""
    assert gate_state.enforce("design", root=str(tmp_path)).proceed is True
    assert "UNGATED" in engine_log.read_text(encoding="utf-8")


def test_reconfiguring_logging_mid_run_does_not_truncate_the_log(engine_log):
    """`cisco_toolkit/attestation.py` re-imports the engine by name; under `python
    COLLECT_PARSE_V3_23_0.py` the module is __main__, so that re-executes the body and calls
    setup_logging() a SECOND time near the end of the run. A fresh mode="w" FileHandler there threw
    away everything already written -- which silently gutted the very log this change makes the gate
    verdict land in. The second call must reuse the open handler, not reopen the file."""
    logging.getLogger("cisco_toolkit.excel").info("[OK] 'Inventory' sheet: 253 device(s)")
    cp.setup_logging()                                   # what the re-import does
    logging.getLogger("cisco_toolkit.gate_state").error("[GATE REFUSED] design: late verdict")
    text = engine_log.read_text(encoding="utf-8")
    assert "'Inventory' sheet: 253 device(s)" in text, "reconfiguring logging truncated the log"
    assert "late verdict" in text, "records after the second setup_logging() were lost"


def test_package_info_records_are_no_longer_discarded(engine_log):
    """`lastResort` is WARNING-level, so every `cisco_toolkit` INFO was dropped — including the
    per-sheet `[OK] '<Sheet>': N row(s)` chain-of-custody lines that 8aa9a4e moved out of the engine.
    Attaching the package tree restores them; pin that INFO now survives."""
    logging.getLogger("cisco_toolkit.excel").info("[OK] 'Inventory' sheet: 253 device(s)")
    assert "'Inventory' sheet: 253 device(s)" in engine_log.read_text(encoding="utf-8")


# ------------------------------------------------------------------- defect 2: it was fragile

def test_root_handlers_cannot_swallow_or_duplicate_gate_records(engine_log, tmp_path):
    """`propagate = False` is the fragility fix. A root handler installed later must neither steal
    these records nor double them in the log.

    Installing the handler directly IS the general case: `logging.basicConfig()`'s entire effect is to
    add one to root. Calling `basicConfig()` here would prove nothing — it no-ops whenever root
    already has a handler, which it does under pytest — and `force=True` would close pytest's own
    capture handlers for the rest of the session."""
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    root = logging.getLogger()
    root.addHandler(_Capture())
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))

    text = engine_log.read_text(encoding="utf-8")
    assert text.count("[GATE REFUSED]") == 1, "record duplicated once root gained a handler"
    assert not [m for m in captured if "GATE REFUSED" in m], \
        "gate records escaped to root -- a non-stderr root handler could swallow or reformat them"


# ------------------------------------------------------- the structural record: every outcome

def test_every_enforce_outcome_records_a_verdict(tmp_path):
    """Coverage-honest: each of the six documented outcomes must leave a row. A path that returns
    without recording is one whose verdict silently vanishes from the manifest."""
    seen, rows_by_scenario = {}, {}

    def _run(name, setup, **kw):
        root = tmp_path / name
        root.mkdir()
        setup(root)
        gate_state.reset_verdicts()
        proceeded = gate_state.enforce("design", root=str(root), **kw)
        rows = gate_state.verdicts()
        assert len(rows) == 1, f"{name}: expected exactly one verdict row, got {rows}"
        seen[name] = bool(proceeded)
        rows_by_scenario[name] = rows[0]

    def _unreadable(root):
        os.makedirs(root / "docs")
        (root / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")

    _run("ungated", lambda r: None)
    _run("approved", lambda r: _write_store(r, assessment_approved="approved"))
    _run("refused", _write_store)
    _run("refused_no_reason", _write_store, override_reason="   ")
    _run("overridden", _write_store, override_reason="CAB waiver 42")
    _run("refused_unreadable", _unreadable)

    # Since #439 the vocabulary is STATUSES, and it is NOT 1:1 with the old flat verdict names:
    # a refusal, a rejected empty-reason override and an accepted override are all `pending`,
    # separated by `proceed` and by the presence of the sealed `reason`. Assert the mapping per
    # SCENARIO rather than as a set, so a collision can never silently satisfy the check.
    assert {k: (r["verdict"], r["proceed"], "reason" in r) for k, r in rows_by_scenario.items()} == {
        "ungated":            ("ungated",    True,  False),
        "approved":           ("clear",      True,  False),
        "refused":            ("pending",    False, False),
        "refused_no_reason":  ("pending",    False, False),
        "overridden":         ("pending",    True,  True),
        "refused_unreadable": ("unreadable", False, False),
    }
    # every status emitted must live in the ONE published vocabulary
    assert {r["verdict"] for r in rows_by_scenario.values()} <= set(gate_state.STATUSES)
    # and the ledger must agree with the return value it was recorded beside
    assert [k for k, proceeded in seen.items() if proceeded] == ["ungated", "approved", "overridden"]
    assert all(not proceeded for v, proceeded in seen.items() if v.startswith("refused"))

    # "never evaluated" must not render as "evaluated, nothing missing" -- the not-observed-is-not-
    # healthy rule. No store and an unreadable store never got to compare anything: those are None.
    assert rows_by_scenario["ungated"]["missing"] is None
    assert rows_by_scenario["refused_unreadable"]["missing"] is None
    assert rows_by_scenario["approved"]["missing"] == []


def test_ownership_refusals_seal_missing_as_never_evaluated(tmp_path):
    """REGRESSION PIN (independent-refuter finding, 25-Jul-2026). `missing` is nullable on purpose:
    None = the approvals were NEVER EVALUATED, [] = evaluated and nothing was missing. #439 added
    `ownership_mismatch` and `ownership_unbound`, and NOTHING pinned them to the None side -- with
    them dropped from `UNEVALUATED` the entire gate suite still passed while a run refused because
    the ledger belongs to ANOTHER CLIENT sealed as evaluated-with-nothing-missing. That is the exact
    "never-checked run scores as a clean zero" harm the nullable exists to prevent.

    `bad_root` is pinned in tests/test_gate_state.py; `ungated`/`unreadable` in
    test_every_enforce_outcome_records_a_verdict. These two were the gap."""
    root = tmp_path / "eng"
    root.mkdir()
    _write_store(root)
    gate_state.bind_engagement("ACME-2026", root=str(root))

    for engagement, expected in (("GLOBEX-2026", "ownership_mismatch"),):
        gate_state.reset_verdicts()
        v = gate_state.enforce("design", root=str(root), engagement=engagement)
        row, = gate_state.verdicts()
        assert row["verdict"] == expected, row
        assert v.proceed is False and row["proceed"] is False, row
        assert row["missing"] is None, (
            f"{expected} sealed missing={row['missing']!r} -- it must be null (NEVER EVALUATED), "
            f"never [] (evaluated, nothing missing): no approval was ever checked")

    # and the unbound case: a run that declares an engagement against a ledger that names none
    plain = tmp_path / "plain"
    plain.mkdir()
    _write_store(plain)
    gate_state.reset_verdicts()
    v = gate_state.enforce("design", root=str(plain), engagement="ACME-2026")
    row, = gate_state.verdicts()
    assert row["verdict"] == "ownership_unbound", row
    assert row["missing"] is None, row
    assert v.proceed is False

    # the property this all rests on: every UNEVALUATED status seals null
    assert set(gate_state.UNEVALUATED) >= {"ownership_mismatch", "ownership_unbound"}, \
        "UNEVALUATED lost an ownership status -- see this test's docstring"


def test_verdicts_returns_a_deep_copy(tmp_path):
    """`verdicts()` is the only read path to the audit source, so a caller that sorts or normalises
    a row in place must not be able to rewrite the record that gets sealed."""
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))
    handed_out = gate_state.verdicts()
    handed_out[0]["missing"].append("INJECTED")
    handed_out[0]["verdict"] = "approved"
    assert gate_state.verdicts() == [
        {"generator": "design", "verdict": "pending", "missing": ["assessment_approved"],
         "proceed": False, "recorded": True, "engagement": None}]


def test_refusal_reason_is_recorded_not_just_logged(tmp_path):
    """The refusal row carries WHICH approvals were missing, so the manifest explains itself without
    the reader having to reconstruct it from log prose."""
    _write_store(tmp_path, lld_approved="approved")          # baseline_captured still missing
    gate_state.enforce("mop", root=str(tmp_path))
    row, = gate_state.verdicts()
    assert row == {"generator": "mop", "verdict": "pending",
                   "missing": ["baseline_captured"], "proceed": False,
                   "recorded": True, "engagement": None}


# ------------------------------------------------------------- the seal: the auditable record

def test_refusal_is_sealed_into_the_run_manifest(tmp_path, monkeypatch):
    """The verdict lands in `.run_manifest.json` as data, inside the hash chain, and the manifest
    still verifies."""
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))
    man = _manifest_for(tmp_path)
    assert _gate_step(man)["verdicts"] == [
        {"generator": "design", "verdict": "pending", "missing": ["assessment_approved"],
         "proceed": False, "recorded": True, "engagement": None}]
    ok, broken = M.verify_manifest(man)
    assert ok, f"manifest chain broken at rows {broken}"


def test_no_gate_decision_seals_an_empty_list_not_silence(tmp_path, monkeypatch):
    """`--no-design --no-mop` runs no gate. The step must still be present and empty: 'no decision'
    is a distinct, readable state, never absence that a reader could take for 'gates passed'."""
    monkeypatch.chdir(tmp_path)
    assert _gate_step(_manifest_for(tmp_path))["verdicts"] == []


def test_editing_a_verdict_out_of_the_manifest_breaks_the_seal(tmp_path, monkeypatch):
    """The property that makes this an audit record rather than a note: laundering a refusal into an
    approval, or deleting it, must be detectable by `verify_manifest`."""
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))
    man = _manifest_for(tmp_path)
    assert M.verify_manifest(man)[0]

    laundered = json.loads(json.dumps(man))                  # deep copy
    _gate_step(laundered)["verdicts"][0]["verdict"] = "approved"
    ok, broken = M.verify_manifest(laundered)
    assert not ok and broken, "a rewritten gate verdict passed verification"

    deleted = json.loads(json.dumps(man))
    deleted["chain"] = [s for s in deleted["chain"] if s.get("stage") != "gate"]
    assert not M.verify_manifest(deleted)[0], "deleting the gate step passed verification"


def test_sealed_gate_step_is_deterministic(tmp_path, monkeypatch):
    """`manifest.py`'s contract is 'same inputs -> same chain'. A timestamp or username in the sealed
    row would break it for every consumer, so pin both the stable root and the exact key set."""
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path), override_reason="CAB waiver 42")
    first = _manifest_for(tmp_path)
    second = _manifest_for(tmp_path)
    assert first["chain_root"] == second["chain_root"]
    row, = _gate_step(first)["verdicts"]
    assert set(row) == {"generator", "verdict", "missing", "proceed", "reason",
                        "recorded", "engagement"}, \
        ("unexpected key in a SEALED verdict row -- who/when/store belong to the store's audit line, "
         "never the seal: they are environment-derived and would make chain_root vary run-to-run. "
         "`recorded` and `engagement` ARE sealed on purpose -- a bool and an opaque human-minted "
         "identifier, both deterministic. Without them the seal cannot say whether its own durable "
         "trail exists, nor which engagement it belongs to.")


def test_seal_distinguishes_a_refusal_whose_durable_write_FAILED(tmp_path, monkeypatch):
    """The seal must be able to say that its own durable trail is MISSING.

    Before ``recorded`` was sealed, a refusal whose ledger write failed produced a row -- and a
    ``chain_root`` -- byte-identical to one that succeeded. The tamper-evident record could not
    express "this refusal was withheld but NOTHING was persisted", which is the same class of defect
    the gate exists to prevent, one layer up: an audit record asserting a governance trail that is
    not there.

    ``os.replace`` raising PermissionError is not a contrived fault: it is the routine Windows case
    when any process holds the ledger -- an engineer with docs/engagement-state.json open in an
    editor while a scheduled assessment runs.
    """
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)

    gate_state.enforce("design", root=str(tmp_path))
    healthy_row, = _gate_step(_manifest_for(tmp_path))["verdicts"]
    healthy_root = _manifest_for(tmp_path)["chain_root"]

    gate_state.reset_verdicts()
    import unittest.mock as _mock
    with _mock.patch.object(os, "replace", side_effect=PermissionError(5, "Access is denied")):
        v = gate_state.enforce("design", root=str(tmp_path))
    assert v.refused and v.recorded is False, "precondition: the durable write must have failed"
    failed_row, = _gate_step(_manifest_for(tmp_path))["verdicts"]

    assert healthy_row != failed_row, \
        ("the seal cannot distinguish a durably-recorded refusal from one whose ledger write FAILED "
         "-- it asserts an audit trail that does not exist")
    assert healthy_row["recorded"] is True and failed_row["recorded"] is False
    # Same decision, different durability => different chain: the difference is TAMPER-EVIDENT, not
    # merely present in a field a reader might ignore.
    assert _manifest_for(tmp_path)["chain_root"] != healthy_root


def test_sealed_row_cites_its_owning_engagement(tmp_path, monkeypatch):
    """Law 1: this per-run row is a COPY of the ledger's audit array, so it must name its owner.
    Sealing the opaque identifier (never the absolute store path) is what lets a reader join the
    manifest copy back to the ledger that owns it -- without it, two records can disagree about
    which engagement a decision concerned with no way to reconcile them."""
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)
    gate_state.bind_engagement("ACME-2026", root=str(tmp_path), by="lead")

    gate_state.reset_verdicts()
    gate_state.enforce("design", root=str(tmp_path), engagement="ACME-2026")
    row, = _gate_step(_manifest_for(tmp_path))["verdicts"]
    assert row["engagement"] == "ACME-2026", "the sealed copy names no owner (Law 1)"
    assert "store" not in row, \
        "the ABSOLUTE store path must never be sealed -- it would make chain_root machine-specific"

    # An UNBOUND ledger seals None rather than omitting the key: "this ledger declares no owner" is
    # itself a fact a reconciler needs, and is distinct from "the key was never recorded".
    other = tmp_path / "unbound"
    other.mkdir()
    _write_store(other)
    gate_state.reset_verdicts()
    gate_state.enforce("design", root=str(other))
    unbound_row, = gate_state.verdicts()
    assert unbound_row["engagement"] is None and "engagement" in unbound_row


def test_reset_verdicts_prevents_cross_run_bleed(tmp_path):
    """`main()` resets the ledger, so a second in-process run cannot seal the previous run's verdicts
    -- a false audit record being worse than the missing one this fixes. The hosts that actually call
    main() twice per process are tests/test_pipeline_inprocess.py and tests/test_pipeline_failopen.py;
    the webapp uses a subprocess and serve.py's --run-engine sentinel dispatches exactly once."""
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))
    assert len(gate_state.verdicts()) == 1
    gate_state.reset_verdicts()
    assert gate_state.verdicts() == []


def test_every_return_path_in_enforce_records_a_verdict():
    """STRUCTURAL guard, not an enumeration: every `return` in `enforce()` must be preceded by a
    `_record(...)` in its own block.

    `test_every_enforce_outcome_records_a_verdict` only covers the outcomes that exist TODAY. Gate
    work is in flight (PR #439 adds TWO new `return False` arms — a mis-set `--gate-root` and a ledger
    ownership refusal), and a new refusal that forgets to record is invisible in exactly the way this
    whole change exists to fix — it would refuse a deliverable and seal nothing. This fails the moment
    such a path is added.

    Bounds, so nobody over-trusts it: it matches `_record(...)` only as a bare statement, so
    `row = _record(...)` or `gate_state._record(...)` would fail LOUDLY (safe), while a call hidden
    behind a helper would be missed. It proves a verdict is recorded, never that it is the RIGHT one —
    `test_every_enforce_outcome_records_a_verdict` covers that."""
    fn = ast.parse(textwrap.dedent(inspect.getsource(gate_state.enforce))).body[0]
    unrecorded = []

    def _walk(stmts, recorded):
        seen = recorded
        for st in stmts:
            if (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
                    and getattr(st.value.func, "id", "") == "_record"):
                seen = True
            # since #439 every exit is `return _emit(GateVerdict(...))`, and _emit is the single
            # site that calls _record -- a return THROUGH it is recorded by construction
            if (isinstance(st, ast.Return) and isinstance(st.value, ast.Call)
                    and getattr(st.value.func, "id", "") == "_emit"):
                seen = True
            for block in ("body", "orelse", "finalbody"):
                if isinstance(getattr(st, block, None), list):
                    _walk(getattr(st, block), seen)
            for handler in getattr(st, "handlers", []) or []:
                _walk(handler.body, seen)
            if isinstance(st, ast.Return) and not seen:
                unrecorded.append(st.lineno)

    _walk(fn.body, False)
    assert not unrecorded, (
        f"enforce() returns without recording a verdict at body line(s) {unrecorded} -- that "
        f"outcome would be refused/allowed with no durable trace. Add a _record(...) call.")


def test_STATUSES_covers_every_verdict_enforce_can_seal(tmp_path):
    """`STATUSES` is the ONE published vocabulary (Law 1) — #445's separate flat `VERDICTS` tuple was
    retired when #439 landed, because a second enum for the same situations is a copy that drifts.

    The old guard scanned the source for `_record(g, "<literal>")` calls. That cannot work now: every
    verdict is sealed at ONE chokepoint (`_emit`) which passes `v.status`, a VARIABLE. The guarantee
    did not disappear, it moved — and this is the stronger form, because it drives the real code
    instead of pattern-matching it: whatever `enforce` actually emits must be a published status."""
    emitted = set()
    for name, setup, kw in (
            ("ungated",    lambda r: None,                                          {}),
            ("approved",   lambda r: _write_store(r, assessment_approved="approved"), {}),
            ("refused",    _write_store,                                             {}),
            ("overridden", _write_store,           {"override_reason": "CAB waiver 42"}),
    ):
        root = tmp_path / name
        root.mkdir()
        setup(root)
        gate_state.reset_verdicts()
        gate_state.enforce("design", root=str(root), **kw)
        emitted |= {r["verdict"] for r in gate_state.verdicts()}

    assert emitted, "no verdict was sealed at all -- the chokepoint is not recording"
    assert emitted <= set(gate_state.STATUSES), (
        f"enforce() sealed a verdict outside the published vocabulary: "
        f"{sorted(emitted - set(gate_state.STATUSES))}")
    assert not hasattr(gate_state, "VERDICTS"), (
        "VERDICTS is back: a second enum beside STATUSES is the copy-that-drifts this retired")


def test_withheld_deliverables_are_restated_at_the_end_of_the_run(engine_log, tmp_path,
                                                                 monkeypatch):
    """Every finalize phase signs off with `[OK] ...`, so a run that produced neither the design nor
    the MOP used to END on a success line, thousands of lines after the refusal. The closing summary
    must name what was withheld -- and must stay silent when nothing was."""
    monkeypatch.chdir(tmp_path)
    _write_store(tmp_path)
    gate_state.enforce("design", root=str(tmp_path))
    ctx = types.SimpleNamespace(
        out_xlsx=str(tmp_path / "wb.xlsx"), snap_dict={}, root_dir=str(tmp_path),
        args=types.SimpleNamespace(redact_collection=False), all_devices_meta=[], workers=1)
    (tmp_path / "wb.xlsx").write_text("workbook", encoding="utf-8")
    cp._stage_finalize(ctx)
    tail = engine_log.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "WITHHELD" in tail and "design" in tail, f"run ended on a non-gate line: {tail!r}"

    gate_state.reset_verdicts()                       # nothing refused -> no summary
    cp._stage_finalize(ctx)
    assert "WITHHELD" not in engine_log.read_text(encoding="utf-8").strip().splitlines()[-1]


def test_a_closed_log_handler_is_never_reused(engine_log, tmp_path):
    """The re-entry guard reuses an open FileHandler. It must NOT reuse a CLOSED one: `close()` sets
    stream=None, and a closed mode="w" handler refuses to reopen on emit, so every later record would
    be silently dropped -- the same silent-loss class the guard was added to remove."""
    eng = logging.getLogger("CiscoMigrationAutofillV3_14_6")
    for h in [h for h in eng.handlers if isinstance(h, logging.FileHandler)]:
        h.close()
    cp.setup_logging()
    logging.getLogger("cisco_toolkit.gate_state").error("[GATE REFUSED] design: after a close()")
    assert "after a close()" in engine_log.read_text(encoding="utf-8")


def test_main_resets_the_ledger_before_it_gates(tmp_path):
    """Source guard (the repo's established pattern): the reset must stay wired into `main()`, and
    the manifest builder must keep reading the ledger. Both are easy to drop in a refactor."""
    src = open(os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py"), encoding="utf-8").read()
    assert "gate_reset_verdicts()" in src, "main() no longer resets the per-run gate ledger"
    assert '{"stage": "gate", "verdicts": _gate_state.verdicts()}' in src, \
        "build_run_manifest no longer seals the gate verdicts"
