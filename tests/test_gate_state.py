"""P0-3 / DEC-003 (gap G-003): the PPDIOO human gates are mechanized, not prose-only.

Acceptance criteria from the architect master plan (2026-07-10):
- generating a MOP without an approved-LLD marker REFUSES (``test_mop_without_approved_lld_refuses``);
- ``--override-gate`` proceeds AND leaves a who/when/why audit line
  (``test_override_proceeds_and_appends_audit_line``);
plus the fail-safe brownfield contract (no store at all = warn-and-proceed, never hard-fail) and
the fail-closed contracts (revoked marker re-refuses; an unreadable store is NOT overridable).

The engine wiring is pinned by source guard (the repo's established pattern — see
``test_registry_cited_snapshot_keys_are_published_by_the_engine``): the design/MOP write blocks in
``COLLECT_PARSE_V3_23_0.main()`` must stay guarded by ``gate_state.enforce`` and the parser must
keep the ``--override-gate`` flag.
"""
import json
import logging
import re
from pathlib import Path

import pytest

from cisco_toolkit import gate_state

ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "docs" / "engagement-state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- brownfield fail-safe (no store)

def test_no_store_warns_and_proceeds(tmp_path, caplog):
    """ABSENT store = ungated brownfield: both generators proceed, loudly, and the warn path must
    never itself create a store (activation is an explicit human `approve`, not a side effect)."""
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(tmp_path)).proceed is True
        assert gate_state.enforce("mop", root=str(tmp_path)).proceed is True
    assert "UNGATED" in caplog.text and "brownfield" in caplog.text
    assert not (tmp_path / "docs" / "engagement-state.json").exists()


# ------------------------------------------------------------------------- the refusal (blocking)

def test_mop_without_approved_lld_refuses(tmp_path, caplog):
    """ACCEPTANCE: store exists, baseline captured, but no approved-LLD marker -> MOP refuses."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", root=str(tmp_path)).proceed is False
    assert "GATE REFUSED" in caplog.text and "lld_approved" in caplog.text


def test_design_without_approved_assessment_refuses(tmp_path, caplog):
    """Design's upstream is the approved assessment (design-author charter): a store whose only
    approval is a DIFFERENT gate still refuses design generation."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(tmp_path)).proceed is False
    assert "assessment_approved" in caplog.text


def test_revoke_reactivates_refusal(tmp_path):
    """A revoked approval is not an approval: the gate closes again (fail closed)."""
    for g in ("lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)).proceed is True
    gate_state.record_decision("lld_approved", "revoked", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)).proceed is False


def test_approved_upstream_proceeds_and_override_is_inert(tmp_path):
    """With every upstream approval recorded, generation proceeds — and a redundant
    --override-gate must NOT log a phantom override (nothing was overridden)."""
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="human")
    assert gate_state.enforce("design", root=str(tmp_path)).proceed is True
    assert gate_state.enforce("mop", root=str(tmp_path),
                              override_reason="redundant flag").proceed is True
    assert [a["event"] for a in _store(tmp_path)["audit"]] == ["approve"] * 3


# --------------------------------------------------------------- the override (audited bypass)

def test_override_proceeds_and_appends_audit_line(tmp_path, caplog):
    """ACCEPTANCE: --override-gate on a refused MOP proceeds AND the store gains a who/when/why
    audit line naming the generator and the approvals that were missing."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        ok = gate_state.enforce("mop", override_reason="lab dry-run; CAB waived by ops lead",
                                root=str(tmp_path), who="tester")
    assert ok.proceed is True
    line = _store(tmp_path)["audit"][-1]
    assert line["event"] == "override"
    assert line["generator"] == "mop"
    assert line["missing"] == ["lld_approved"]
    assert line["who"] == "tester"
    assert line["reason"] == "lab dry-run; CAB waived by ops lead"
    assert line["at"]  # the WHEN
    assert "GATE OVERRIDDEN" in caplog.text


def test_blank_override_reason_still_refuses(tmp_path):
    """The audit line is the point of the override: a whitespace-only reason refuses and no
    override line is written."""
    gate_state.record_decision("assessment_approved", "revoked", root=str(tmp_path), by="qa")
    assert gate_state.enforce("design", override_reason="   ", root=str(tmp_path)).proceed is False
    assert all(a["event"] != "override" for a in _store(tmp_path)["audit"])


def test_unreadable_store_refuses_even_with_override(tmp_path, caplog):
    """A store that exists but cannot be parsed fails CLOSED — the override's audit line has
    nowhere trustworthy to land, so --override-gate cannot bypass it."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", override_reason="try anyway",
                                  root=str(tmp_path)).proceed is False
    assert "unreadable" in caplog.text


# ------------------------------------------------- the refusal is durable too (the audit symmetry)

def test_refusal_appends_a_durable_audit_line(tmp_path):
    """THE GAP: proceeding despite a missing approval always left a who/when/why line, while
    REFUSING left nothing anywhere — so an absent design.docx was indistinguishable from a
    --no-design run. The refusal now writes the same shape of row the override does."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    v = gate_state.enforce("design", root=str(tmp_path), who="tester")
    assert v.proceed is False and v.recorded is True

    line = _store(tmp_path)["audit"][-1]
    assert line["event"] == "refuse"
    assert line["generator"] == "design"
    assert line["status"] == "pending"
    assert line["missing"] == ["assessment_approved"]
    assert line["who"] == "tester"                       # the WHO
    assert line["at"]                                    # the WHEN
    assert "assessment_approved" in line["reason"]       # the WHY


def test_refusal_record_survives_the_rerun_it_provokes(tmp_path):
    """Why the ledger's audit array is the home and a per-run manifest is not: the natural response
    to a refusal is to re-run, and a per-run seal is overwritten by exactly that. Three refused runs
    leave three rows, oldest still intact."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    for _ in range(3):
        assert gate_state.enforce("design", root=str(tmp_path)).recorded is True
    refusals = [a for a in _store(tmp_path)["audit"] if a["event"] == "refuse"]
    assert len(refusals) == 3, "a re-run overwrote the earlier refusals instead of appending"


def test_override_on_an_approved_ledger_records_no_breach(tmp_path):
    """The exact case that sank the previous attempt: it inferred "overridden" from the presence of
    the flag, but enforce() returns at its approvals-present branch BEFORE reaching the override
    branch, appending nothing. A verdict claiming a breach with no matching ledger line is a
    tamper-evident record of something that never happened."""
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="human")
    v = gate_state.enforce("design", root=str(tmp_path), override_reason="ship it anyway")
    assert v.proceed is True
    assert v.status == "clear"
    assert v.overridden is False, "a redundant --override-gate manufactured a phantom override"
    assert [a["event"] for a in _store(tmp_path)["audit"]] == ["approve"] * 3


def test_overridden_is_true_only_where_the_line_was_written(tmp_path):
    """The other half of the same invariant: a REAL override sets it, and the ledger has the row."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    v = gate_state.enforce("mop", override_reason="CAB waived", root=str(tmp_path), who="lead")
    assert v.proceed is True and v.overridden is True and v.recorded is True
    assert _store(tmp_path)["audit"][-1]["event"] == "override"


def test_unreadable_ledger_is_not_rewritten_by_the_refusal(tmp_path):
    """A corrupt ledger is EVIDENCE. Recording into it would serialise the parsed dict we never
    got and destroy the bytes that show the corruption, so this refusal stays unrecorded — and
    says so, rather than leaving the caller to assume it was written."""
    (tmp_path / "docs").mkdir()
    ledger = tmp_path / "docs" / "engagement-state.json"
    ledger.write_text("{not json", encoding="utf-8")
    v = gate_state.enforce("design", root=str(tmp_path))
    assert v.proceed is False and v.status == "unreadable"
    assert v.recorded is False, "the refusal claimed a durable record it could not have written"
    assert ledger.read_text(encoding="utf-8") == "{not json", "the corrupt ledger was overwritten"


def test_bad_root_refusal_creates_no_ledger(tmp_path):
    """A mis-set root must not be answered by MAKING the directory tree it names — that is the
    phantom-ledger bug _require_root exists to close, arriving through the audit path instead."""
    bad = str(tmp_path / "nope" / "not here")
    v = gate_state.enforce("design", root=bad)
    assert v.proceed is False and v.status == "bad_root" and v.recorded is False
    assert not (tmp_path / "nope").exists()


def test_ungated_run_never_creates_a_ledger(tmp_path):
    """Brownfield proceeds, and must stay brownfield: the first write to a ledger is the human
    opt-in that ACTIVATES enforcement, so a run must never enrol an engagement as a side effect."""
    v = gate_state.enforce("design", root=str(tmp_path))
    assert v.proceed is True and v.status == "ungated" and v.recorded is False
    assert not (tmp_path / "docs").exists()


def test_unrecordable_refusal_is_reported_not_crashed(tmp_path, monkeypatch, caplog):
    """A locked or read-only ledger (os.replace raises on Windows while any process holds the file)
    must not turn a working refusal into a crash — the deliverable is already withheld, which is the
    safe outcome. It degrades to recorded=False, loudly."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")

    def _boom(path, store):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(gate_state, "save_store", _boom)
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        v = gate_state.enforce("design", root=str(tmp_path))
    assert v.proceed is False, "a bookkeeping failure changed the gate decision"
    assert v.recorded is False
    assert "could NOT be recorded" in caplog.text


def test_ownership_refusal_stays_unrecorded_and_says_so(tmp_path):
    """The one refusal with a readable ledger in reach that still must not write to it: it governs
    another engagement. Pairs with test_ownership_refusals_are_not_overridable_and_write_nothing —
    that one pins the bytes, this one pins that the verdict does not CLAIM a record."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    v = gate_state.enforce("design", root=str(root), engagement="GLOBEX-2026")
    assert v.proceed is False and v.status == "ownership_mismatch" and v.recorded is False


# -------------------------------------------------------------- the verdict object's own contracts

def test_enforce_and_pending_approvals_share_one_status_vocabulary(tmp_path):
    """Law 1 applied to a taxonomy: the deciding path and the disclosing path report the SAME seven
    statuses, so they can never disagree about one ledger. A parallel enum for "the same situations,
    as seen by the enforcer" is a copy that drifts — and inventing one was called out explicitly."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    seen = set()
    for root, eng in ((str(tmp_path / "gone"), None), (str(tmp_path), None),
                      (str(tmp_path), "ACME-2026")):
        seen.add(gate_state.enforce("design", root=root, engagement=eng).status)
        seen.add(gate_state.pending_approvals("design", root=root, engagement=eng)["status"])
    assert seen <= set(gate_state.STATUSES), f"a status escaped the shared vocabulary: {seen}"
    assert {"bad_root", "pending", "ownership_unbound"} <= seen, "the sweep stopped exercising them"


def test_verdict_is_truthy_exactly_when_it_proceeds(tmp_path):
    """`if gate_enforce(...)` is the historical call shape at both engine sites, so truthiness must
    track the decision and nothing else — a dataclass is truthy by default, which would have made
    every refusal generate its deliverable."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    refused = gate_state.enforce("design", root=str(tmp_path))
    assert bool(refused) is False and refused.refused is True
    gate_state.record_decision("assessment_approved", "approved", root=str(tmp_path), by="qa")
    allowed = gate_state.enforce("design", root=str(tmp_path))
    assert bool(allowed) is True and allowed.refused is False


def test_empty_missing_never_reads_as_nothing_missing_when_unevaluated(tmp_path):
    """Coverage honesty (D3) on the governance axis: `missing == ()` after a run that never located
    a ledger means UNKNOWN, not "nothing outstanding". `status`/`evaluated` carry that, which is why
    `missing` does not need to be nullable."""
    unknown = gate_state.enforce("design", root=str(tmp_path / "gone"))
    assert unknown.missing == () and unknown.evaluated is False
    gate_state.record_decision("assessment_approved", "approved", root=str(tmp_path), by="qa")
    known = gate_state.enforce("design", root=str(tmp_path))
    assert known.missing == () and known.evaluated is True


def test_show_counts_refusals_beside_overrides(tmp_path, capsys):
    """The operator's one diagnostic tool stayed mute about every run the gates actually stopped."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    gate_state.enforce("design", root=str(tmp_path))
    assert gate_state.main(["--root", str(tmp_path), "show"]) == 0
    out = capsys.readouterr().out
    assert "1 refusal(s)" in out
    assert "**REFUSED**" in out and "design" in out


# ------------------------------------------------------------------------------ schema contracts

def test_unknown_generator_gate_and_decision_raise(tmp_path):
    with pytest.raises(ValueError):
        gate_state.enforce("runbook", root=str(tmp_path))  # not a gated generator
    with pytest.raises(ValueError):
        gate_state.record_decision("not_a_gate", "approved", root=str(tmp_path))
    with pytest.raises(ValueError):
        gate_state.record_decision("lld_approved", "maybe", root=str(tmp_path))


def test_gate_keys_are_append_only_storage_schema():
    """The keys are persisted into per-engagement stores — a rename orphans recorded sign-offs
    (same contract as engagement.GATE_SEQUENCE). Renaming/removing one must fail here first."""
    assert {"assessment_approved", "lld_approved", "baseline_captured",
            "cab_approved", "nrfu_signed"} <= set(gate_state.GATE_KEYS)
    assert gate_state.GENERATOR_REQUIRES["design"] == ("assessment_approved",)
    assert gate_state.GENERATOR_REQUIRES["mop"] == ("lld_approved", "baseline_captured")


# ------------------------------------------------------------------------------------ CLI arms

def test_cli_approve_show_roundtrip(tmp_path, capsys):
    rc = gate_state.main(["--root", str(tmp_path), "approve", "lld_approved",
                          "--by", "reviewer", "--note", "LLD v2 signed"])
    assert rc == 0
    rc = gate_state.main(["--root", str(tmp_path), "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lld_approved" in out and "approved" in out and "reviewer" in out
    assert "override(s)" in out  # the weekly-review counter (DEC-003)


def test_cli_show_absent_store_is_honest(tmp_path, capsys):
    assert gate_state.main(["--root", str(tmp_path), "show"]) == 0
    assert "UNGATED" in capsys.readouterr().out


# ------------------------------------------------------------------- engine wiring + Law 1 pins

def test_engine_wires_the_gates_and_the_override_flag():
    """Source guard: the design/MOP blocks in main() stay gate-guarded and the flags exist.
    (The write functions themselves stay ungated on purpose — the ~60 direct-call tests and the
    webapp regeneration path are additive-compatibility surfaces; the CLI is the enforcement
    point because that is where --override-gate lives.)

    ONE guard covering every property of the call site, deliberately: this pinned the ``root=`` /
    ``engagement=`` threading and the verdict collection as two separate regexes for a while, and
    because both matched overlapping text, a change satisfying either one alone read as compliant.
    A single pattern per generator cannot be half-satisfied.
    """
    src = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    assert '"--override-gate"' in src, "the CLI lost the --override-gate flag"
    assert '"--gate-root"' in src, "the CLI lost the --gate-root flag (gates re-pin to cwd only)"
    assert '"--engagement"' in src, \
        "the CLI lost --engagement (ADR-0006: ownership becomes un-verifiable again)"
    assert '"--fail-on-gate-refusal"' in src, \
        "the CLI lost --fail-on-gate-refusal (a pipeline can no longer stop on a withheld document)"
    assert "from cisco_toolkit.gate_state import enforce as gate_enforce" in src
    for gen, flag in (("design", "no_design"), ("mop", "no_mop")):
        # Four properties in one pattern, in order:
        #  1. `if not args.no_X:` comes FIRST, so a suppressed deliverable never consults the ledger
        #     and never writes a refusal row about a document nobody asked for;
        #  2. root= AND engagement= are threaded — a run that declares who it is, on a path that
        #     forgets to pass the declaration on, silently reverts to proximity (the ADR-0006 defect);
        #  3. the verdict is COLLECTED, so the exit disposition reads what happened rather than
        #     re-deriving it from the flags (the defect that sank the previous attempt);
        #  4. the write is gated on that same collected verdict, not on a second call.
        assert re.search(rf'if not args\.{flag}:\s+'
                         rf'{gen}_gate = gate_enforce\("{gen}", '
                         rf'override_reason=args\.override_gate,\s*'
                         rf'root=args\.gate_root, engagement=args\.engagement\)\s+'
                         rf'gate_verdicts\.append\({gen}_gate\)\s+'
                         rf'if {gen}_gate:', src), \
            (f"the {gen} block no longer matches the required gate shape: evaluate only when "
             f"requested, thread root=/engagement=, collect the verdict, gate the write on it")
    assert re.search(r'if __name__ == "__main__":.*?\n\s*sys\.exit\(main\(\)\)', src, re.S), \
        ("the bare-script door stopped propagating main()'s exit code -- `python "
         "COLLECT_PARSE_V3_23_0.py` would silently exit 0 on a refusal again, and "
         "tests/test_pipeline_golden.py runs through THIS door")


def test_ssot_registry_cites_the_gate_state_owner():
    """Law 1: the store is a source of truth, so the registry must name it and its schema owner."""
    txt = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "engagement-state.json" in txt
    assert "gate_state.py" in txt
    assert "test_gate_state.py" in txt  # the enforcement column cites this suite


# ------------------------------------------------------- root resolution (the silent-ungate class)

#: Directories that are not production source: the repo's own tests (a synthetic cwd is CORRECT
#: there — it is the isolation), plus vendored/generated/worktree copies of the tree.
_NON_SOURCE_DIRS = frozenset({".claude", ".git", "tests", "graphify-out", "node_modules",
                              "dist", "build", ".venv", "venv", "_ref", "__pycache__"})


def _flag_literals(node) -> set:
    """The exact string literals a function passes — the flags it REALLY sends.

    Deliberately not a substring scan of the source text: the first cut of this guard matched
    ``--gate-root`` inside the explanatory comments that were added next to the compliant call
    sites, so two callers that never pass the flag reported as compliant. Prose cannot satisfy an
    exact-equality test against ``"--gate-root"``, and comments are absent from the AST entirely."""
    import ast

    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _rehomes_the_child(node) -> bool:
    """True if the function moves the engine off the operator's cwd — ``subprocess(..., cwd=…)``
    for a child, ``os.chdir()`` for an in-process ``main()``. AST, so a comment cannot trip it.

    Errs toward TRUE (a `**kwargs` splat could hide a cwd), because a false positive only demands
    that the caller declare a posture, while a false negative is the silent ungating itself."""
    import ast

    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        # os.chdir(...) AND a bare chdir(...) from `from os import chdir`.
        if isinstance(n.func, ast.Attribute) and n.func.attr == "chdir":
            return True
        if isinstance(n.func, ast.Name) and n.func.id == "chdir":
            return True
        for kw in n.keywords:
            if kw.arg is None:      # **kwargs splat — contents unknowable, assume the worst
                return True
            if kw.arg == "cwd" and not (isinstance(kw.value, ast.Constant)
                                        and kw.value.value is None):
                return True
    return False


#: Synthetic-cwd engine callers that are UNGATED BY DECISION, mapped to a phrase their docstring
#: must still contain. An exemption with a reason attached is honest; a silent one is the bug this
#: guard exists for. If someone deletes the reasoning, this fails and they have to re-make the call.
_UNGATED_BY_DECISION = {
    "webapp/backend/ingest.py::run_redaction_folder": "deliberately do NOT apply",
}


def _declares_a_posture(node) -> str:
    """Which legitimate posture this caller declares, or "" for none.

    Exact AST matching, never substring: the first version of this guard scanned source text and
    was satisfied by the explanatory COMMENTS beside the compliant call sites, certifying two
    callers that pass nothing."""
    flags = _flag_literals(node)
    if "--gate-root" in flags:
        return "enforces (--gate-root)"
    if {"--no-design", "--no-mop"} <= flags:
        return "inert (--no-design/--no-mop)"
    return ""


def _engine_launching_functions():
    """Every production function that builds an engine invocation, as (label, ast node).

    ``--collection-dir`` is the discriminator: it is on every offline engine launch in the repo
    (subprocess or in-process ``main()``) and appears nowhere else."""
    import ast

    for path in sorted(ROOT.glob("**/*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if _NON_SOURCE_DIRS & set(rel.split("/")[:-1]):
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        if "--collection-dir" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover - a broken source file is another test's problem
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "--collection-dir" in _flag_literals(node):
                yield f"{rel}::{node.name}", node


def test_no_engine_caller_declares_a_gate_posture():
    """THE REGRESSION GUARD for this whole class (see gate_state.py 'Root resolution').

    ``enforce()`` resolves ``docs/engagement-state.json`` from the process working directory, so a
    caller that re-homes the engine child to a scratch dir finds no store, takes the brownfield
    branch and turns EVERY document gate into an unconditional True — no error, no failure-shaped
    warning, just two documents quietly missing. Note the asymmetry that hides it: an unreadable
    store fails closed, an unreachable one fails open.

    Such a caller must therefore DECLARE a posture:
      (a) enforce — point the gates at the real engagement with ``--gate-root``;
      (b) inert — generate no gated deliverable at all (``--no-design`` AND ``--no-mop``);
      (c) ungated by an explicit, documented decision — listed in ``_UNGATED_BY_DECISION`` with
          the reasoning that justifies it, which this test re-checks is still present.

    ``--redact-folder`` originally declared none and rendered both gated documents for any
    engagement. The check is per FUNCTION, not per file, because webapp/backend/ingest.py holds
    call sites of two different postures — file granularity would let one vouch for the other.

    KNOWN COVERAGE LIMITS (stated rather than overclaimed — an honest partial guard beats a
    confident one). It only sees argv literals inside the function body, so it would miss a caller
    that builds argv in a module-level constant or a helper, composes flags with f-strings, or
    launches the engine from module scope rather than a function. It also cannot tell a
    CONDITIONAL flag from an unconditional one: ``if x: cmd += ["--no-mop"]`` reads as declared.
    It is a tripwire for the shape of mistake that actually happened, not a proof."""
    import ast

    offenders, undocumented, inspected = [], [], {}
    for where, node in _engine_launching_functions():
        if not _rehomes_the_child(node):
            continue
        posture = _declares_a_posture(node)
        if not posture and where in _UNGATED_BY_DECISION:
            posture = "ungated by decision"
            if _UNGATED_BY_DECISION[where] not in (ast.get_docstring(node) or ""):
                undocumented.append(where)
        inspected[where] = posture
        if not posture:
            offenders.append(where)

    assert not undocumented, (
        "these callers are exempted from the gates by decision, but the reasoning that justifies "
        "the exemption is gone from their docstring: " + ", ".join(undocumented) +
        "\nAn exemption without a reason is indistinguishable from the oversight this guards.")

    assert not offenders, (
        "engine launched with a synthetic cwd and NO declared gate posture, which silently "
        "disables the PPDIOO document gates: " + ", ".join(offenders) +
        "\nPass --gate-root <engagement root>, or suppress the gated deliverables with "
        "--no-design --no-mop, or add it to _UNGATED_BY_DECISION with the reasoning written "
        "into its docstring.")
    # A guard that inspects nothing passes trivially. The three known synthetic-cwd callers are
    # run_redaction_folder (ungated by decision), _assess_tree and build_sample.main (both inert) —
    # if a rename drops them off the inventory the guard has stopped guarding, which is the failure.
    assert len(inspected) >= 3, (
        f"expected >=3 synthetic-cwd engine callers, found {len(inspected)}: {inspected}. "
        "The inventory stopped matching real call sites — fix the discriminator, do not relax it.")
    assert "webapp/backend/ingest.py::run_redaction_folder" in inspected, \
        "the caller this guard exists for dropped off the inventory"


def _run_engine_for_gates(tmp_path, gate_root):
    """Run the REAL engine offline over the synthetic fixture, asking for the two gated documents.
    ``gate_root`` None = omit --gate-root (the pre-fix invocation). Returns (stdout+stderr, outdir)."""
    import subprocess
    import sys

    from openpyxl import Workbook

    import synthetic_fixtures as fx

    base = tmp_path / ("gated" if gate_root else "ungated")
    base.mkdir(parents=True)
    collection = fx.write_collection(str(base / "collection"))
    devices = base / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = base / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    out_xlsx = base / "out.xlsx"

    # The point of the test: the child's cwd is an EMPTY scratch dir, exactly as
    # run_redaction_folder re-homes it. Only --gate-root can reach the ledger from here.
    scratch = tmp_path / f"scratch_{base.name}"
    scratch.mkdir()

    cmd = [sys.executable, str(ROOT / "COLLECT_PARSE_V3_23_0.py"),
           "--no-collect", "--collection-dir", collection,
           "--devices-file", str(devices), "--template", str(template),
           "--output", str(out_xlsx), "--workers", "1",
           "--no-html", "--no-pptx", "--no-crd", "--no-engagement",
           "--no-opshandbook", "--no-archreview", "--no-docx"]
    if gate_root is not None:
        cmd += ["--gate-root", str(gate_root)]
    proc = subprocess.run(cmd, cwd=str(scratch), capture_output=True,
                          encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, f"engine failed:\n{proc.stdout}\n{proc.stderr}"
    return (proc.stdout or "") + (proc.stderr or ""), base


def test_gate_root_enforces_gates_the_synthetic_cwd_would_have_disabled(tmp_path):
    """END-TO-END, through the real CLI: an engagement whose gates are recorded-but-unapproved
    must NOT get a design or a MOP, even though the engine child runs in an empty scratch dir.

    The second run is the non-vacuity control AND the characterization of the original defect:
    identical inputs, identical unapproved ledger, only --gate-root omitted -> both documents are
    written. That is the pre-fix `--redact-folder` behaviour, and it proves the refusal above comes
    from the flag rather than from a missing renderer or an empty fixture."""
    engagement = tmp_path / "engagement"
    engagement.mkdir()   # the root must pre-exist; only docs/ is created by the first decision
    # Records the store (activating enforcement) with design's and the MOP's upstreams UNAPPROVED:
    # a revoked LLD is the sharpest case — a peer review that actively said no.
    gate_state.record_decision("lld_approved", "revoked", root=str(engagement), by="reviewer")
    assert (engagement / "docs" / "engagement-state.json").is_file()

    out, base = _run_engine_for_gates(tmp_path, engagement)
    # Bracketed exactly as gate_state emits it. An unbracketed assertion passed while any consumer
    # matching the real marker (`[GATE REFUSED]`) would have broken on a formatting change.
    assert "[GATE REFUSED]" in out, f"gates did not fire with --gate-root:\n{out[-3000:]}"
    written = {p.name for p in base.iterdir()}
    assert not [n for n in written if n.endswith(("_design.docx", "_mop.docx"))], \
        f"a gated document was written despite an unapproved ledger: {sorted(written)}"

    out2, base2 = _run_engine_for_gates(tmp_path, None)
    assert "[GATE REFUSED]" not in out2, \
        "control run should be ungated (that is the defect it models)"
    written2 = {p.name for p in base2.iterdir()}
    assert [n for n in written2 if n.endswith("_design.docx")], \
        f"control produced no design doc, so the refusal above proves nothing: {sorted(written2)}"
    assert [n for n in written2 if n.endswith("_mop.docx")], \
        f"control produced no MOP, so the refusal above proves nothing: {sorted(written2)}"


# --------------------------------------------------- a MIS-SET root is an error, not "no gates"

@pytest.mark.parametrize("bad", ["C:/nope/does/not/exist", "definitely/not/here"])
def test_nonexistent_gate_root_refuses_instead_of_going_brownfield(bad, tmp_path, caplog):
    r"""The flag whose whole purpose is 'never silently downgrade a gate' must not silently
    downgrade every gate when mis-set. `--gate-root D:\Engagments\ACME` (typo) or a Windows-quoted
    `--gate-root "C:\eng\"` (argparse receives a trailing quote) used to hit the absent-store
    branch and return True — one typo, every gate off, exit 0, no signal."""
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=bad).proceed is False
        assert gate_state.enforce("mop", root=bad).proceed is False
    assert "not an existing directory" in caplog.text


def test_nonexistent_gate_root_is_not_overridable(tmp_path):
    """Same reasoning as an unreadable store: the override's audit line has nowhere to land, so
    --override-gate must not talk its way past a root that does not exist."""
    assert gate_state.enforce("mop", override_reason="ship it",
                              root=str(tmp_path / "absent")).proceed is False


def test_an_omitted_root_still_means_cwd(tmp_path, monkeypatch):
    """The refusal above must not break the brownfield contract: OMITTING the root is not the same
    as mis-setting it, so a bare `cisco-assess` in a store-less directory still proceeds."""
    monkeypatch.chdir(tmp_path)
    assert gate_state.enforce("design").proceed is True


def test_empty_root_still_means_cwd_and_is_not_a_mis_set_root(tmp_path, monkeypatch):
    """`""` is the argv encoding of OMITTED -- `--gate-root "$ENG_ROOT"` with the var unset, or
    `cmd += ["--gate-root", cfg.get("gate_root", "")]`. It always behaved exactly like "." because
    store_path() joins relatively, so refusing it would be a pure REGRESSION: an engagement with
    every approval recorded would suddenly lose its design and MOP. Refusing a mis-set root must
    not sweep in the one value that was never mis-set."""
    monkeypatch.chdir(tmp_path)
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="lead")
    assert gate_state.enforce("design", root="").proceed is True
    assert gate_state.enforce("mop", root="").proceed is True


def test_recording_into_a_nonexistent_root_refuses_instead_of_creating_a_phantom_ledger(tmp_path):
    r"""The WRITE side needs this more than the read side. save_store() calls os.makedirs, so
    `gate_state --root D:\Engagments\ACME approve assessment_approved` (typo) used to succeed and
    print a receipt -- durable state at a path nobody will look at again, while the real
    engagement stayed unapproved. Worse than the read-side bug, because it is silent AND sticky."""
    absent = tmp_path / "Engagments" / "ACME"
    with pytest.raises(gate_state.GateStateError, match="not an existing directory"):
        gate_state.record_decision("assessment_approved", "approved", root=str(absent), by="lead")
    assert not absent.exists(), "a mis-set root must not leave a phantom ledger behind"

    # The legitimate case still works: the engagement dir exists, docs/ is created on first approve.
    real = tmp_path / "acme"
    real.mkdir()
    gate_state.record_decision("assessment_approved", "approved", root=str(real), by="lead")
    assert (real / "docs" / "engagement-state.json").is_file()


def test_cli_show_refuses_a_mis_set_root_instead_of_reporting_brownfield(tmp_path, capsys):
    """`show` is the operator's one diagnostic tool. Answering a typo with "UNGATED (brownfield)"
    is the exact sentence this module exists to stop anything from saying wrongly."""
    rc = gate_state.main(["--root", str(tmp_path / "absent"), "show"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSING" in out and "UNGATED" not in out


# ------------------------------------------------ ADR-0006: ledger ownership, declared not inferred

def _store_at(root: Path) -> dict:
    return json.loads((root / "docs" / "engagement-state.json").read_text(encoding="utf-8"))


def _approved_ledger(tmp_path: Path, engagement=None, gates=("assessment_approved",)) -> Path:
    """An engagement root whose `gates` are approved, optionally bound to `engagement`."""
    root = tmp_path / (engagement or "unbound")
    root.mkdir(parents=True, exist_ok=True)
    for i, gate in enumerate(gates):
        gate_state.record_decision(gate, "approved", root=str(root), by="lead",
                                   engagement=engagement if i == 0 else None)
    return root


def test_unbound_ledger_and_undeclared_run_behave_exactly_as_before(tmp_path):
    """Row 1 of the ownership table — the backward-compatibility contract.

    Every ledger that exists today is unbound. If adding the field changed their behaviour at all,
    shipping it would be a silent migration of live engagements, so this pins that it does not:
    approvals still decide, and nothing starts demanding an identifier."""
    root = _approved_ledger(tmp_path)
    assert gate_state.enforce("design", root=str(root)).proceed is True
    assert gate_state.enforce("mop", root=str(root)).proceed is False       # lld/baseline still unsigned
    assert gate_state.engagement_of(_store_at(root)) is None
    assert "engagement" not in _store_at(root), \
        "an unbound ledger acquired an engagement key just by being read"


def test_bound_ledger_with_no_declaration_applies_gates_but_calls_them_unverified(tmp_path, caplog):
    """Row 2. The operator standing in the engagement root is the historical, legitimate case and
    must keep working — but the log must not let "it passed" read as "ownership was checked"."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(root)).proceed is True
    assert "PROXIMITY" in caplog.text and "unverified" in caplog.text
    assert "ACME-2026" in caplog.text


def test_matching_declaration_verifies_ownership(tmp_path, caplog):
    """Row 3 — the point of the mechanism: the answer is now known to be about this client."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    with caplog.at_level(logging.INFO, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(root), engagement="ACME-2026").proceed is True
    assert "VERIFIED" in caplog.text


def test_declaring_a_different_engagement_refuses_even_with_every_approval_present(tmp_path,
                                                                                   caplog):
    """Row 4, and THE regression this whole change exists for, end to end.

    The refuted walk-up heuristic printed "all recorded approvals present" for a run of GLOBEX out
    of engagement ACME's ledger. Here ACME's ledger is fully approved and GLOBEX asks: the answer
    must be a refusal naming both engagements, and must never contain the approval sentence."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    with caplog.at_level(logging.INFO, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(root), engagement="GLOBEX-2026").proceed is False
    assert "REFUSED" in caplog.text
    assert "ACME-2026" in caplog.text and "GLOBEX-2026" in caplog.text
    assert "approvals present" not in caplog.text, \
        "a cross-engagement run was told another client's approvals were present"


def test_declaring_an_engagement_against_an_unbound_ledger_refuses(tmp_path):
    """Row 5. Adopting an unbound ledger because it happens to be here is exactly the proximity
    inference this replaced — asking for verification and getting a guess is the worst outcome."""
    root = _approved_ledger(tmp_path)
    assert gate_state.enforce("design", root=str(root), engagement="ACME-2026").proceed is False


def test_ownership_refusals_are_not_overridable_and_write_nothing(tmp_path):
    """--override-gate is consent to skip a KNOWN gate; when ownership does not check out, no gate
    for this engagement has been located, so there is nothing to consent to. Equally important, the
    refusal must not append its audit line into the other engagement's ledger."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    ledger = root / "docs" / "engagement-state.json"
    before = ledger.read_text(encoding="utf-8")
    assert gate_state.enforce("design", override_reason="CAB said so", root=str(root),
                              engagement="GLOBEX-2026").proceed is False
    assert ledger.read_text(encoding="utf-8") == before, \
        "a refused cross-engagement run mutated the ledger it was refused access to"


def test_engagement_match_ignores_case_and_surrounding_whitespace(tmp_path):
    """A refusal over `acme-2026` vs `ACME-2026` would teach operators to stop passing
    --engagement, losing the control entirely. Stored verbatim; only the comparison normalizes."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    assert gate_state.enforce("design", root=str(root), engagement="  acme-2026 ").proceed is True
    assert _store_at(root)["engagement"] == "ACME-2026", "the stored identifier was rewritten"


def test_signing_into_another_engagements_ledger_is_refused(tmp_path):
    """The write side matters more than the read side: an approval landing in the wrong ledger both
    fails to gate the engagement the lead meant AND silently unblocks a different one."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    with pytest.raises(gate_state.GateStateError, match="GLOBEX-2026"):
        gate_state.record_decision("lld_approved", "approved", root=str(root), by="lead",
                                   engagement="GLOBEX-2026")
    assert "lld_approved" not in _store_at(root)["gates"]


def test_bind_creates_is_idempotent_and_refuses_a_rebind(tmp_path):
    """Binding is the one-time act that makes ownership verifiable. Re-binding to a different id
    would retroactively re-attribute every approval already signed in the ledger — the exact
    mis-attribution the mechanism exists to prevent — so it is refused, not warned about."""
    root = tmp_path / "eng"
    root.mkdir()
    assert gate_state.bind_engagement("ACME-2026", root=str(root)) == "ACME-2026"
    assert _store_at(root)["engagement"] == "ACME-2026"
    assert gate_state.bind_engagement("acme-2026", root=str(root)) == "acme-2026"   # idempotent
    with pytest.raises(gate_state.GateStateError, match="already bound"):
        gate_state.bind_engagement("GLOBEX-2026", root=str(root))
    assert _store_at(root)["engagement"] == "acme-2026", "a refused re-bind still moved the label"


def test_is_revoked_distinguishes_withdrawal_from_silence(tmp_path):
    """The MOP posture in ADR-0006 turns entirely on this distinction: a gate nobody ever signed is
    unapproved by SILENCE (perhaps an engagement that never opted in), while a revoked gate is a
    human's positive withdrawal of approval. Only the second justifies withholding a deliverable."""
    root = tmp_path / "eng"
    root.mkdir()
    gate_state.record_decision("lld_approved", "approved", root=str(root), by="lead")
    gate_state.record_decision("lld_approved", "revoked", root=str(root), by="lead")
    store = _store_at(root)
    assert gate_state.is_revoked(store, "lld_approved") is True
    assert gate_state.is_approved(store, "lld_approved") is False
    # baseline_captured was never signed at all: missing, but NOT revoked.
    assert gate_state.is_revoked(store, "baseline_captured") is False
    assert gate_state.missing_approvals(store, "mop") == ["lld_approved", "baseline_captured"]
    assert gate_state.revoked_requirements(store, "mop") == ["lld_approved"]


def test_pending_approvals_reads_without_deciding_or_writing(tmp_path):
    """The disclosure primitive's contract, which is what makes it safe on a field path: it never
    writes (a disclosure that mutates the ledger it reports on is not a disclosure) and it never
    raises (its callers are paths where an exception aborts a deliverable someone is waiting on)."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    ledger = root / "docs" / "engagement-state.json"
    before = ledger.read_text(encoding="utf-8")

    clear = gate_state.pending_approvals("design", root=str(root), engagement="ACME-2026")
    assert clear["status"] == "clear" and clear["verified"] is True and clear["missing"] == []

    pending = gate_state.pending_approvals("mop", root=str(root), engagement="ACME-2026")
    assert pending["status"] == "pending" and "lld_approved" in pending["missing"]

    assert ledger.read_text(encoding="utf-8") == before, "disclosure wrote to the ledger"

    # Every failure mode is a STATUS, never an exception — including ones enforce() refuses on.
    empty = tmp_path / "empty"
    empty.mkdir()
    broken = tmp_path / "broken"
    (broken / "docs").mkdir(parents=True)
    (broken / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")
    assert gate_state.pending_approvals("design", root=str(tmp_path / "gone"))["status"] \
        == "bad_root"
    assert gate_state.pending_approvals("design", root=str(empty))["status"] == "ungated"
    assert gate_state.pending_approvals("design", root=str(broken))["status"] == "unreadable"


def test_pending_approvals_never_reports_another_engagements_approvals(tmp_path):
    """The disclosure path must fail the same way enforcement does — it is the one destined for the
    field tool, where a wrong "approved" is read by someone standing at a client site."""
    root = _approved_ledger(tmp_path, engagement="ACME-2026")
    verdict = gate_state.pending_approvals("design", root=str(root), engagement="GLOBEX-2026")
    assert verdict["status"] == "ownership_mismatch"
    assert verdict["verified"] is False and verdict["missing"] == []
    assert "ACME-2026" in verdict["summary"] and "GLOBEX-2026" in verdict["summary"]
    assert "all upstream approvals" not in verdict["summary"], \
        "a cross-engagement disclosure claimed approvals it never verified"

    unbound = _approved_ledger(tmp_path)
    assert gate_state.pending_approvals("design", root=str(unbound),
                                        engagement="ACME-2026")["status"] == "ownership_unbound"


def test_cli_bind_and_show_disclose_ownership(tmp_path, capsys):
    """`show` is the operator's diagnostic tool, so it must say whose board it is printing — and
    say plainly when the honest answer is "attributed by directory alone"."""
    root = tmp_path / "eng"
    root.mkdir()
    gate_state.record_decision("assessment_approved", "approved", root=str(root), by="lead")
    assert gate_state.main(["--root", str(root), "show"]) == 0
    assert "UNBOUND" in capsys.readouterr().out

    assert gate_state.main(["--root", str(root), "bind", "ACME-2026"]) == 0
    assert "ACME-2026" in capsys.readouterr().out
    assert gate_state.main(["--root", str(root), "show"]) == 0
    out = capsys.readouterr().out
    assert "governs engagement: ACME-2026" in out and "UNBOUND" not in out

    # A cross-engagement approval attempt is refused at the CLI with a non-zero exit, not a receipt.
    assert gate_state.main(["--root", str(root), "approve", "lld_approved",
                            "--engagement", "GLOBEX-2026"]) == 1
    assert "REFUSING" in capsys.readouterr().out
