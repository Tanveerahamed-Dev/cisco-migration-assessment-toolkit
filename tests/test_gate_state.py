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
        assert gate_state.enforce("design", root=str(tmp_path)) is True
        assert gate_state.enforce("mop", root=str(tmp_path)) is True
    assert "UNGATED" in caplog.text and "brownfield" in caplog.text
    assert not (tmp_path / "docs" / "engagement-state.json").exists()


# ------------------------------------------------------------------------- the refusal (blocking)

def test_mop_without_approved_lld_refuses(tmp_path, caplog):
    """ACCEPTANCE: store exists, baseline captured, but no approved-LLD marker -> MOP refuses."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", root=str(tmp_path)) is False
    assert "GATE REFUSED" in caplog.text and "lld_approved" in caplog.text


def test_design_without_approved_assessment_refuses(tmp_path, caplog):
    """Design's upstream is the approved assessment (design-author charter): a store whose only
    approval is a DIFFERENT gate still refuses design generation."""
    gate_state.record_decision("lld_approved", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("design", root=str(tmp_path)) is False
    assert "assessment_approved" in caplog.text


def test_revoke_reactivates_refusal(tmp_path):
    """A revoked approval is not an approval: the gate closes again (fail closed)."""
    for g in ("lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)) is True
    gate_state.record_decision("lld_approved", "revoked", root=str(tmp_path), by="qa")
    assert gate_state.enforce("mop", root=str(tmp_path)) is False


def test_approved_upstream_proceeds_and_override_is_inert(tmp_path):
    """With every upstream approval recorded, generation proceeds — and a redundant
    --override-gate must NOT log a phantom override (nothing was overridden)."""
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="human")
    assert gate_state.enforce("design", root=str(tmp_path)) is True
    assert gate_state.enforce("mop", root=str(tmp_path),
                              override_reason="redundant flag") is True
    assert [a["event"] for a in _store(tmp_path)["audit"]] == ["approve"] * 3


# --------------------------------------------------------------- the override (audited bypass)

def test_override_proceeds_and_appends_audit_line(tmp_path, caplog):
    """ACCEPTANCE: --override-gate on a refused MOP proceeds AND the store gains a who/when/why
    audit line naming the generator and the approvals that were missing."""
    gate_state.record_decision("baseline_captured", "approved", root=str(tmp_path), by="qa")
    with caplog.at_level(logging.WARNING, logger="cisco_toolkit.gate_state"):
        ok = gate_state.enforce("mop", override_reason="lab dry-run; CAB waived by ops lead",
                                root=str(tmp_path), who="tester")
    assert ok is True
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
    assert gate_state.enforce("design", override_reason="   ", root=str(tmp_path)) is False
    assert all(a["event"] != "override" for a in _store(tmp_path)["audit"])


def test_unreadable_store_refuses_even_with_override(tmp_path, caplog):
    """A store that exists but cannot be parsed fails CLOSED — the override's audit line has
    nowhere trustworthy to land, so --override-gate cannot bypass it."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "engagement-state.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="cisco_toolkit.gate_state"):
        assert gate_state.enforce("mop", override_reason="try anyway",
                                  root=str(tmp_path)) is False
    assert "unreadable" in caplog.text


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
    """Source guard: the design/MOP blocks in main() stay gate-guarded and the flag exists.
    (The write functions themselves stay ungated on purpose — the ~60 direct-call tests and the
    webapp regeneration path are additive-compatibility surfaces; the CLI is the enforcement
    point because that is where --override-gate lives.)"""
    src = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    assert '"--override-gate"' in src, "the CLI lost the --override-gate flag"
    assert '"--gate-root"' in src, "the CLI lost the --gate-root flag (gates re-pin to cwd only)"
    assert "from cisco_toolkit.gate_state import enforce as gate_enforce" in src
    assert re.search(r'if not args\.no_design and\s+'
                     r'gate_enforce\("design", override_reason=args\.override_gate,\s*'
                     r'root=args\.gate_root\)', src), \
        "the design write block is no longer gate-guarded (or dropped root=args.gate_root)"
    assert re.search(r'if not args\.no_mop and\s+'
                     r'gate_enforce\("mop", override_reason=args\.override_gate,\s*'
                     r'root=args\.gate_root\)', src), \
        "the MOP write block is no longer gate-guarded (or dropped root=args.gate_root)"


def test_ssot_registry_cites_the_gate_state_owner():
    """Law 1: the store is a source of truth, so the registry must name it and its schema owner."""
    txt = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "engagement-state.json" in txt
    assert "gate_state.py" in txt
    assert "test_gate_state.py" in txt  # the enforcement column cites this suite


# ------------------------------------------------------- root resolution (the silent-ungate class)

#: Directories that are not production source: the repo's own tests (a synthetic cwd is CORRECT
#: there — it is the isolation), plus vendored/generated/worktree copies of the tree.
#: Kept in step with .graphifyignore's exclusions: an untracked side-engagement or scratch copy of
#: the tree would otherwise contribute a second `.../ingest.py::run_redaction_folder` under a key
#: absent from _UNGATED_BY_DECISION, turning the suite red for an environmental reason.
_NON_SOURCE_DIRS = frozenset({".claude", ".git", "tests", "graphify-out", "node_modules",
                              "dist", "build", ".venv", "venv", "_ref", "__pycache__",
                              "ds-bundle", ".ds-sync", "[HISTORY-REDACTED]_DC_Design", "figgen"})


def _flag_literals(node) -> set:
    """Flags a function really puts in an ARGV list — literals from the list/tuple that holds
    ``--collection-dir``, plus anything appended/extended/``+=``'d onto a list afterwards.

    Scoped to argv rather than the whole function body because both looser readings were shown to
    certify non-compliant callers: a source-text scan matched ``--gate-root`` in the explanatory
    COMMENTS beside compliant call sites, and a whole-function literal scan matched it in a
    defensive ``assert "--gate-root" not in cmd`` — a line this module's own comments invite
    someone to write. Comments are absent from the AST; an assertion is not."""
    import ast

    def literals(n) -> set:
        return {c.value for c in ast.walk(n)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)}

    # Pass 1: the argv list/tuple literal, and the NAME it is bound to. Mutations only count if
    # they target that name — an earlier cut harvested every `.append`/`+=` in the function, so two
    # unrelated `skipped_flags.append("--no-design")` lines certified an ungated caller as inert.
    found: set = set()
    argv_names: set = set()
    for n in ast.walk(node):
        if not isinstance(n, (ast.List, ast.Tuple)):
            continue
        lits = literals(n)
        if "--collection-dir" not in lits:
            continue
        found |= lits
        parent = getattr(n, "_gate_parent", None)
        if isinstance(parent, ast.Assign):
            argv_names |= {t.id for t in parent.targets if isinstance(t, ast.Name)}

    # Pass 2: mutations of those names only.
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("append", "extend", "insert") \
                and isinstance(n.func.value, ast.Name) and n.func.value.id in argv_names:
            found |= literals(n)
        elif isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) \
                and isinstance(n.target, ast.Name) and n.target.id in argv_names:
            found |= literals(n.value)
    return found


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
    """Which legitimate posture this caller declares, or "" for none (see ``_flag_literals``)."""
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
        # _flag_literals needs to know which Assign an argv list belongs to, and ast nodes carry no
        # parent link. Stamp one rather than re-walking per node.
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child._gate_parent = parent
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

    KNOWN COVERAGE LIMITS. State the RULE, not a list of examples — a list reads as exhaustive and
    this one never was. What is seen: string literals in the list/tuple holding ``--collection-dir``,
    plus ``append``/``extend``/``insert``/``+=`` **on the name that list is assigned to**. Every
    other way of building argv is INVISIBLE, including concatenation (``base + [...]``), star-unpack
    (``[*base, ...]``), a dict or loop that emits flags, ``list(...)``, a module-level constant, a
    helper function, f-string-composed flags, and an engine launched from module scope rather than
    a function. ``assert len(inspected) >= 3`` does not protect against those: three callers are
    found today, so an invisible fourth keeps the count satisfied.
      * A CONDITIONAL flag reads as declared (``if fast: cmd += ["--no-mop"]``), as does one added
        and then removed, and as does a flag whose VALUE is empty or nonexistent. NB the direction:
        an EMPTY ``--gate-root`` value UNGATES (``_normalize_root("")`` is ``"."`` — see
        ``test_empty_root_still_means_cwd_and_is_not_a_mis_set_root``); only a NONEXISTENT value
        refuses. So the dangerous reading here is "enforces" on a caller that silently ungates.
      * ``subprocess.Popen(cmd, …, cwd_positional)`` — cwd passed positionally is not seen.
      * It OVER-triggers too: any unrelated ``cwd=`` (a ``git`` call) or any ``f(**kwargs)`` marks a
        function as re-homing, so a legitimately-compliant future caller can be flagged, and so can
        one that builds argv by concat/star-unpack. That direction is deliberate — but the cheap
        wrong fix is to silence it with ``--no-design --no-mop``, i.e. deleting deliverables. Read
        the failure before "fixing" it.
    This is a tripwire for the shape of mistake that actually happened, not a proof."""
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


def _run_engine_for_gates(tmp_path, gate_root, cwd=None, tag=None):
    """Run the REAL engine offline over the synthetic fixture, asking for the two gated documents.
    ``gate_root`` None = omit --gate-root. ``cwd`` None = an empty scratch dir (the re-homed-child
    shape); pass a directory to model an operator running from the engagement itself.
    Returns (stdout+stderr, outdir)."""
    import subprocess
    import sys

    from openpyxl import Workbook

    import synthetic_fixtures as fx

    base = tmp_path / (tag or ("gated" if gate_root else "ungated"))
    base.mkdir(parents=True)
    collection = fx.write_collection(str(base / "collection"))
    devices = base / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = base / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    out_xlsx = base / "out.xlsx"

    if cwd is None:
        # The re-homed-child shape: an EMPTY scratch dir, exactly as run_redaction_folder does.
        # Only --gate-root can reach the ledger from here.
        cwd = tmp_path / f"scratch_{base.name}"
        cwd.mkdir()

    cmd = [sys.executable, str(ROOT / "COLLECT_PARSE_V3_23_0.py"),
           "--no-collect", "--collection-dir", collection,
           "--devices-file", str(devices), "--template", str(template),
           "--output", str(out_xlsx), "--workers", "1",
           "--no-html", "--no-pptx", "--no-crd", "--no-engagement",
           "--no-opshandbook", "--no-archreview", "--no-docx"]
    if gate_root is not None:
        cmd += ["--gate-root", str(gate_root)]
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
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
        assert gate_state.enforce("design", root=bad) is False
        assert gate_state.enforce("mop", root=bad) is False
    assert "not an existing directory" in caplog.text


def test_nonexistent_gate_root_is_not_overridable(tmp_path):
    """An override is consent to bypass a SPECIFIC gate, and with a mis-set root no gate has been
    identified — you cannot consent to bypassing an approval you never located. (Deliberately NOT
    the unreadable-store reasoning: "the audit line has nowhere to land" is false here, since
    save_store would happily makedirs the path — that is the phantom-ledger bug _require_root
    closes. See the note above _require_root in gate_state.py.)"""
    assert gate_state.enforce("mop", override_reason="ship it",
                              root=str(tmp_path / "absent")) is False


def test_an_omitted_root_still_means_cwd(tmp_path, monkeypatch):
    """The refusal above must not break the brownfield contract: OMITTING the root is not the same
    as mis-setting it, so a bare `cisco-assess` in a store-less directory still proceeds."""
    monkeypatch.chdir(tmp_path)
    assert gate_state.enforce("design") is True


def test_empty_root_still_means_cwd_and_is_not_a_mis_set_root(tmp_path, monkeypatch):
    """`""` is the argv encoding of OMITTED -- `--gate-root "$ENG_ROOT"` with the var unset, or
    `cmd += ["--gate-root", cfg.get("gate_root", "")]`. It always behaved exactly like "." because
    store_path() joins relatively, so refusing it would be a pure REGRESSION: an engagement with
    every approval recorded would suddenly lose its design and MOP. Refusing a mis-set root must
    not sweep in the one value that was never mis-set."""
    monkeypatch.chdir(tmp_path)
    for g in ("assessment_approved", "lld_approved", "baseline_captured"):
        gate_state.record_decision(g, "approved", root=str(tmp_path), by="lead")
    assert gate_state.enforce("design", root="") is True
    assert gate_state.enforce("mop", root="") is True


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


def test_the_default_gate_root_is_the_operators_cwd(tmp_path):
    """THE ARM THE FIRST VERSION OF THIS SUITE MISSED, and the one that matters most.

    `--gate-root` defaults to "." so that an ORDINARY `cisco-assess` run -- operator standing in
    the engagement, flag not passed -- keeps enforcing exactly as it did before the flag existed.
    Nothing tested that. Mutating the default to anything else (`os.path.expanduser("~")` was the
    demonstration) left the ENTIRE suite green while silently ungating every real operator run.

    It hid behind the sibling test's shape: both of its arms use an EMPTY cwd, and its control arm
    EXPECTS ungated when the flag is omitted -- which is precisely what a broken default produces.
    So the mutant satisfied the control's expectation. Only (flag omitted, cwd = engagement)
    distinguishes a correct default from a broken one."""
    engagement = tmp_path / "engagement"
    engagement.mkdir()
    gate_state.record_decision("lld_approved", "revoked", root=str(engagement), by="reviewer")

    out, base = _run_engine_for_gates(tmp_path, None, cwd=engagement, tag="default_root")

    assert "[GATE REFUSED]" in out, (
        "the engine did not consult the engagement in its own working directory -- the "
        f"--gate-root DEFAULT is broken, which ungates every ordinary CLI run:\n{out[-3000:]}")
    written = {p.name for p in base.iterdir()}
    assert not [n for n in written if n.endswith(("_design.docx", "_mop.docx"))], \
        f"a gated document was written from the operator's own engagement dir: {sorted(written)}"


def test_gate_root_default_is_pinned_in_the_parser():
    """Source guard backing the behavioural test above: the default is a one-token change with
    repo-wide blast radius, so it is asserted literally as well as exercised."""
    src = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    assert re.search(r'"--gate-root",\s*default="\."', src), (
        'the --gate-root default is no longer exactly "." -- anything else silently changes which '
        'ledger every un-flagged CLI run consults (see test_the_default_gate_root_is_the_operators_cwd)')


def test_a_root_that_exists_but_is_a_file_refuses(tmp_path):
    """`isdir`, not `exists`. Swapping them left the suite green while `--gate-root <...>/
    engagement-state.json` -- pointing AT the ledger rather than at its engagement, the likeliest
    way to get this wrong -- read as brownfield and ungated every gate."""
    gate_state.record_decision("lld_approved", "revoked", root=str(tmp_path), by="qa")
    ledger = tmp_path / "docs" / "engagement-state.json"
    assert ledger.is_file()
    assert gate_state.enforce("mop", root=str(ledger)) is False

    # And the KNOWN GAP, pinned deliberately rather than left to be rediscovered: a wrong root that
    # happens to be a real directory (here docs/, whose own docs/engagement-state.json does not
    # exist) still reads as brownfield and UNGATES. _require_root catches a path that is not a
    # directory, nothing more. Closing this needs the ledger to declare what it governs.
    assert gate_state.enforce("mop", root=str(tmp_path / "docs")) is True, \
        "documented gap changed -- update gate_state.py's 'Root resolution' note and docs/ssot.md"


def test_a_non_string_root_is_rejected_not_coerced_to_cwd(tmp_path, monkeypatch):
    """`root or "."` coerced None/0/b"" to the working directory, so record_decision(root=None)
    created a real ledger in the process cwd and returned a success receipt -- the phantom-ledger
    outcome _require_root exists to stop, reached by a bad TYPE instead of a bad path. It fired for
    real during review and wrote docs/engagement-state.json into the repo root."""
    monkeypatch.chdir(tmp_path)
    for bad in (None, 0, b""):
        with pytest.raises(TypeError):
            gate_state.record_decision("assessment_approved", "approved", root=bad)
        with pytest.raises(TypeError):
            gate_state.enforce("design", root=bad)
    assert not (tmp_path / "docs").exists(), "a bad root must never create a ledger anywhere"


def test_cli_approve_refuses_a_mis_set_root_without_a_traceback(tmp_path, capsys):
    """The write side must not answer a typo with a raw traceback while `show` answers the same
    mistake with a sentence -- and the write side is the one that used to create phantom state."""
    rc = gate_state.main(["--root", str(tmp_path / "absent"), "approve", "lld_approved"])
    out = capsys.readouterr().out
    assert rc == 1 and "REFUSING" in out
