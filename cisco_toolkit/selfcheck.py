"""Agent-system self-check (Phase 4) — the immune system that verifies the guards are NON-VACUOUS.

Phase 4 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` runs this in the nightly clock and leads
the morning briefing with any failure. The whole autonomy story rests on guards (evals, the scorecard
appender, the protected-constraint tier, the learnings discipline, the SSOT reconcilers). A guard that has
been **deleted or gutted** silently stops protecting — a *skipped* test is **red**, not green. This module
re-derives, from the repo, whether each guard is present and actually asserting, plus whether the feedback
substrate is being written, guarded-refresh bookkeeping is current, and the REAL protected-memory artifact is still pinned
(P0-1 / DEC-005 — the memory_guard mechanism's only live wiring).

Every check returns **GREEN** (verified healthy), **RED** (verified broken — leads the briefing), or
**UNKNOWN** (could not be evaluated — coverage-honest: absence of a signal is *never* rendered GREEN). Pure
filesystem + a couple of real guard invocations (the learnings lint); ``root`` and ``now`` are injectable so
it is deterministic and unit-testable. Total — a check that raises is caught and reported UNKNOWN, never
crashes the nightly run.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

GREEN, RED, UNKNOWN = "GREEN", "RED", "UNKNOWN"
GRAPHIFY_REFRESH_COMMAND = "py -3.12 -I -B tools/graphify_guarded.py update ."
GRAPHIFY_REFRESH_RECEIPT_CONTRACT = "atlas-graphify-refresh/1"
GRAPHIFY_GUARD_IDENTITY = {
    "aliases": 5,
    "ast_cache": "bypass-json-casefold",
    "bytecode_writes": "disabled",
    "contract": "graphify-json-extends-overlay/1",
    "environment": "graphify-git-path-sanitized",
    "extractor": "graphify/extractors/json_config.py",
    "isolated": True,
    "max_workers": 1,
    "patched_sha256": "cb6b660bd2dee3f58e9007d0eac27883cd3bb3fe5d8136c13e8d83b92b90e011",
    "source_sha256": "d15ea6d9b48cc71e73615c44c72808562ad4a1dbc82d5a340e3ad0c2fb4fc945",
    "status": "pass",
    "version": "0.9.47",
}

# The non-vacuity guards: each must exist AND actually assert something. A guard deleted or emptied is RED.
GUARD_FILES = [
    "tests/test_memory_guard.py", "tests/test_learnings.py", "tests/test_scorecard.py",
    "tests/test_calibration.py", "tests/test_clock.py", "tests/test_domain_packs.py",
    "tests/test_council.py", "tests/test_eval_harness.py", "tests/test_ssot_registry.py",
    "tests/test_pipeline_golden.py",
    # the judge-trust + calibration-corpus instruments — the "measure the judge, don't assume it" nerve.
    # Gutting the TNR floor or the fault-corpus discrimination would let an unmeasured judge read GREEN.
    "tests/test_defect_panel.py", "tests/test_fault_corpus.py", "tests/test_ollama_judge.py",
    # registry-freshness guard (P0-5): four docs/ssot.md rows + ADR 0001 cite it as their enforcement;
    # deleting it must go RED here, not leave the registry advertising a guard that no longer exists.
    "tests/test_registry_freshness.py",
    # the schema-version value pin (P0-6 / G-006): test_version.py is what makes the REAL
    # cisco_toolkit.__version__ value a guarded fact (the docs/ssot.md "currently 3.23.0" cache);
    # test_registry_freshness guards the registry CELL, this guards the VALUE — gut either, read RED.
    "tests/test_version.py",
]

# This roster's exact membership is itself pinned by tests/test_selfcheck.py::test_guard_files_exact_pin
# (P0-6): without that pin, dropping an entry here AND deleting its file leaves every check green —
# the roster is the one place where a guard can silently stop being watched.

# The D12 protected-tier artifact constants (store path, env override, artifact name) are OWNED by
# cisco_toolkit.memory_guard (one source of truth) and imported lazily inside the check, so a deleted
# guard module reads RED there instead of breaking this module's import.

# --- the D12 verbatim floor (see check_protected_artifact / protected_body_integrity) -------------
# D12 says the protected tier survives a consolidation pass VERBATIM. Existence + the frontmatter
# marker + "each of the 8 short anchors appears somewhere" is satisfied by a BULLET LIST of the
# anchors — i.e. by exactly the compression D12 forbids (measured: an artifact reduced to the 8
# anchor strings read GREEN, "all 8 canonical anchors pinned"). The byte-exact mechanism
# (memory_guard.verify_snapshot's sha256) needs a pre-pass baseline and is reachable only from the
# manual CLI wrapper, and a standing check cannot use bytes anyway: a legitimate human edit is not a
# D12 violation. These two floors reject the compressed SHAPE instead, and both are reported with
# their measured values so the verdict is never a bare assertion.
#: body characters required per character of canonical anchor text (real artifact measures 14.1x).
PROTECTED_MIN_BODY_RATIO = 5
#: characters of surrounding doctrine required on an anchor's own line (real artifact's min is 44) —
#: a bullet holding nothing but the anchor is a keyword, not the constraint.
PROTECTED_MIN_ANCHOR_CONTEXT = 24


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _repo_root(root: Optional[str]) -> str:
    if root:
        return root
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def _count_rows(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return -1


def _count_real_pir(path: str) -> int:
    """Count only REAL-provenance PIR rows — the sole class that counts toward the D11 tuning floor
    (surrogate rows like ``fault-injected`` validate the scorer but must NEVER unlock a tuning move).
    Delegates provenance classification to ``calibration._norm_source`` so this readout can never DRIFT
    from the gate it reports on (one source of truth). Fail-safe: an unparseable/unclassed row is non-REAL."""
    import json
    from cisco_toolkit.calibration import _norm_source
    real = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    if _norm_source(json.loads(line).get("source_class")) == "REAL":
                        real += 1
                except Exception:
                    pass
    except OSError:
        return 0
    return real


def check_scorecard_substrate(root: str) -> Dict[str, str]:
    p = os.path.join(root, "docs", "quality", "scorecard.jsonl")
    n = _count_rows(p)
    if n < 0:
        return _check("scorecard_substrate", RED, "docs/quality/scorecard.jsonl missing — the feedback nerve cannot record")
    tail = " (0 entries — no /qa verdict yet; honest, not unhealthy)" if n == 0 else f" ({n} verdict row(s))"
    return _check("scorecard_substrate", GREEN, "present" + tail)


def check_pir_substrate(root: str) -> Dict[str, str]:
    p = os.path.join(root, "docs", "quality", "pir_outcomes.jsonl")
    n = _count_rows(p)
    if n < 0:
        return _check("pir_outcomes_substrate", RED, "docs/quality/pir_outcomes.jsonl missing — calibration cannot record")
    real = _count_real_pir(p)      # only REAL rows count toward D11; surrogate rows populate the descriptive gap only
    return _check("pir_outcomes_substrate", GREEN,
                  f"present ({n} labeled outcome(s), {real} REAL — {real}/5 toward the D11 tuning floor)")


def check_nightly_ledger(root: str) -> Dict[str, str]:
    p = os.path.join(root, "docs", "quality", "nightly_runs.jsonl")
    n = _count_rows(p)
    if n < 0:
        return _check("nightly_ledger", RED, "docs/quality/nightly_runs.jsonl missing — the clock has no audit trail")
    return _check("nightly_ledger", GREEN, f"present ({n} run(s) recorded)")


def check_learnings_discipline(root: str) -> Dict[str, str]:
    p = os.path.join(root, "docs", "quality", "learnings.md")
    if not os.path.exists(p):
        return _check("learnings_discipline", RED, "docs/quality/learnings.md missing")
    try:
        from cisco_toolkit.learnings import lint_file
        violations = lint_file(p)
    except Exception as e:
        return _check("learnings_discipline", UNKNOWN, f"could not lint: {e!r}")
    if violations:
        return _check("learnings_discipline", RED, f"{len(violations)} discipline violation(s): {violations[0]}")
    return _check("learnings_discipline", GREEN, "within discipline (<100 lines, every entry cited, no self-assessment)")


def _module_level_skip(tree: "ast.Module") -> bool:
    """True if the module disables its own collection wholesale — `pytestmark = pytest.mark.skip(...)`
    (or a list containing one), or a bare `pytest.skip(..., allow_module_level=True)` call."""
    def _is_skip(node: Any) -> bool:
        f = node.func if isinstance(node, ast.Call) else node
        name = ""
        while isinstance(f, ast.Attribute):
            name = f.attr if not name else f"{f.attr}.{name}"
            f = f.value
        return name.split(".")[-1] in ("skip", "skipif") if name else False

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            vals = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
            if any(_is_skip(v) for v in vals):
                return True
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _is_skip(node.value):
            return True
    return False


def _live_assertion_count(tree: "ast.Module") -> int:
    """Assertions that would actually RUN: `assert` statements and `pytest.fail(...)` calls inside a
    test function that is not itself skip-decorated. Text matching cannot answer this — a comment, a
    docstring, or a string literal all contain the word `assert` while asserting nothing."""
    live = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        if any("skip" in ast.dump(d) for d in node.decorator_list):
            continue                                  # decorated off -> not a live assertion
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                live += 1
            elif (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "fail"):
                live += 1
    return live


def check_guards_nonvacuous(root: str) -> Dict[str, str]:
    """Each guard file must exist AND carry an assertion that would actually RUN — a deleted, gutted,
    or SKIPPED guard is RED, not silently gone.

    Parsed, never grepped. The substring test this replaced ("assert" in the file's text) could not
    see the three ways a guard stops guarding while still reading green: a module-level
    `pytest.mark.skip`, an assertion commented out or left in a docstring, and an assertion inside a
    test that is decorated off. Measured on the old check: all 15 GUARD_FILES rewritten as
    `pytestmark = pytest.mark.skip("disabled")` + `def test_x(): assert False` returned GREEN "all 15
    guard suites present and asserting", and a file containing only `# TODO: assert something here
    one day` did too — i.e. the entire roster (memory_guard, ssot_registry, scorecard, defect_panel,
    the version pin) could be disabled wholesale and the nightly self-check would still lead the
    morning briefing all-green. This module's own docstring already said a skipped test is RED."""
    missing, vacuous, skipped = [], [], []
    for rel in GUARD_FILES:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            missing.append(rel)
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            missing.append(rel)
            continue
        try:
            tree = ast.parse(txt)
        except SyntaxError as e:
            vacuous.append(f"{rel} (does not parse: {e.msg})")
            continue
        if _module_level_skip(tree):
            skipped.append(rel)
        elif not _live_assertion_count(tree):
            vacuous.append(rel)
    if missing or vacuous or skipped:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if skipped:
            parts.append(f"skipped at module level (collected but never run): {', '.join(skipped)}")
        if vacuous:
            parts.append(f"no live assertions: {', '.join(vacuous)}")
        return _check("guards_nonvacuous", RED, "; ".join(parts))
    return _check("guards_nonvacuous", GREEN,
                  f"all {len(GUARD_FILES)} guard suites present, collected and asserting")


def check_judge_trust(root: str) -> Dict[str, str]:
    """PROVISIONAL-verdict enforcement (P0-6 / DEC-004; gap G-006) — the consumer that treats an
    unquantified APPROVE as NON-GATING. A QA APPROVE is an LLM judge's output; it gates nothing
    unless the judge's measured TNR clears ``scorecard.JUDGE_TNR_FLOOR`` (below it the instrument is
    broken — LLM judges default to TNR < 25%, Jain et al. 2510.11822). RED on the one forbidden
    state: a persisted row contradicting the predicate in the TRUSTING direction (``provisional``
    stored false while judge_tnr is null / below the floor — fabricated confidence). Advisory-only
    approvals under an honestly-demoted weak judge are GREEN *with the demotion disclosed* — a
    measured-weak instrument correctly marked is health, not failure. No scorecard → UNKNOWN
    (signal_absent; the substrate check owns the missing-file RED)."""
    p = os.path.join(root, "docs", "quality", "scorecard.jsonl")
    if not os.path.exists(p):
        return _check("judge_trust", UNKNOWN,
                      "signal_absent: docs/quality/scorecard.jsonl not found — no verdicts to enforce on")
    try:
        from cisco_toolkit import scorecard as SCD
        rows = SCD.read_rows(p)
        fabricated = [f"row {i + 1} ({r.get('date')} {r.get('deliverable')})"
                      for i, r in enumerate(rows)
                      if SCD.is_provisional(r) and r.get("provisional") is False]
        if fabricated:
            return _check("judge_trust", RED,
                          f"fabricated confidence: {len(fabricated)} APPROVE row(s) persisted "
                          f"provisional=false with judge_tnr null/< {SCD.JUDGE_TNR_FLOOR} "
                          f"(first: {fabricated[0]}) — a below-floor judge's APPROVE must stay advisory")
        approvals = [r for r in rows
                     if str(r.get("verdict") or "").strip().upper().startswith("APPROVE")]
        # A scored row is exempt from the floor as "deterministic harness output" — a claim NOTHING
        # in the schema authenticates. Rows that also carry judge provenance are judged rows again
        # (scorecard.is_provisional narrows the exemption); the rest keep it, so COUNT and DISCLOSE
        # them instead of letting the exemption absorb rows out of the denominator silently.
        judged, score_exempt = [], []
        for r in approvals:
            (score_exempt if (SCD._num(r.get("score")) is not None
                              and not SCD.judge_provenance(r)) else judged).append(r)
        advisory = sum(1 for r in judged if SCD.is_provisional(r))
        base = SCD.latest_judge_baseline(rows)
        if base is None:
            tail = (f"no judge-baseline row yet — every judge APPROVE stays advisory until a "
                    f"baseline clears TNR >= {SCD.JUDGE_TNR_FLOOR}")
        else:
            tnr = SCD._num(base.get("judge_tnr"))
            if tnr is None:
                # a REAL measurement that concluded null trust (e.g. the specificity fail-safe) —
                # the demoting baseline of P1-3/DEC-004, not an absence
                state = "NULL trust (e.g. specificity failure) — judge APPROVEs stay advisory"
            elif tnr < SCD.JUDGE_TNR_FLOOR:
                state = "BELOW the floor — judge APPROVEs stay advisory until a re-baseline clears it"
            else:
                state = "clears the floor — freshly-stamped APPROVEs are gating"
            tail = f"latest judge-baseline TNR={tnr} ({base.get('date')}), floor {SCD.JUDGE_TNR_FLOOR}: {state}"
        if score_exempt:
            tail += (f"; {len(score_exempt)} scored APPROVE row(s) exempt from the floor as "
                     "deterministic harness output — that producer is DECLARED, not authenticated "
                     "(no producer identity in the row schema), so the exemption is disclosed here "
                     "rather than counted as verified trust")
        return _check("judge_trust", GREEN,
                      f"{advisory}/{len(judged)} judge-APPROVE row(s) advisory (non-gating); {tail}")
    except Exception as e:
        return _check("judge_trust", UNKNOWN, f"could not evaluate: {e!r}")


def protected_body_integrity(body: str, constraints: List[Tuple[str, str]]) -> List[str]:
    """Problems showing the protected entry was COMPRESSED rather than retained verbatim (D12).

    Pure over the artifact's body text, so it is exhaustively unit-testable. Two floors, each
    reported with the value it measured:

    * **volume** — the body must be at least :data:`PROTECTED_MIN_BODY_RATIO`x the total length of
      the canonical anchors. A keyword list of the anchors measures ~1.2x; the real artifact 14.1x.
    * **anchor context** — an anchor that appears ONLY on lines holding little else
      (< :data:`PROTECTED_MIN_ANCHOR_CONTEXT` characters beyond the anchor) has been reduced to a
      keyword: the constraint is the sentence, not the phrase. An anchor absent altogether is NOT
      reported here — ``memory_guard.unpinned_constraints`` owns that loss class.

    Deliberately a SHAPE test, not a byte pin: bytes cannot distinguish a compression pass from a
    legitimate human edit, and the byte-exact mechanism (``memory_guard snapshot|verify``) brackets a
    consolidation run rather than standing watch. Empty == the entry still reads as doctrine prose."""
    text = body or ""
    problems: List[str] = []
    total = sum(len(a) for _, a in constraints)
    n_body = len(text.strip())
    if total and n_body < PROTECTED_MIN_BODY_RATIO * total:
        problems.append(
            f"body COMPRESSED toward a keyword list: {n_body} chars for {total} chars of canonical "
            f"anchors ({n_body / total:.1f}x, floor {PROTECTED_MIN_BODY_RATIO}x) — D12 requires the "
            "protected tier verbatim, not a summary of it")
    bare = []
    for cid, anchor in constraints:
        margins = [len(ln.strip()) - len(anchor) for ln in text.splitlines() if anchor in ln]
        if margins and max(margins) < PROTECTED_MIN_ANCHOR_CONTEXT:
            bare.append(f"{cid} (max {max(margins)} chars of context, floor "
                        f"{PROTECTED_MIN_ANCHOR_CONTEXT})")
    if bare:
        problems.append(f"{len(bare)}/{len(constraints)} canonical constraint(s) survive only as a "
                        f"bare keyword, not as the doctrine sentence: {', '.join(bare)}")
    return problems


def check_protected_artifact(root: str, memory_dir: Optional[str] = None) -> Dict[str, str]:
    """Pin the REAL protected-memory artifact (P0-1 / DEC-005; gap G-001). ``memory_guard`` is a
    mechanism exercised only by synthetic-store tests — without this check, deleting or unprotecting
    the real ``protected-constraints.md`` trips nothing (BLK-1). Store resolution: explicit arg >
    ``$AGENT_MEMORY_DIR`` > the known per-machine location. RED when the guard's own reconcilers
    report loss or drift: artifact dropped (``missing_protected``), frontmatter no longer marked
    protected, a canonical anchor unpinned (``unpinned_constraints``) or drifted out of the doctrine
    owner (``reconcile_constraints``), or MEMORY.md no longer indexes the artifact (an index prune
    orphans it from session-start re-surfacing). A machine without the store is explicit
    ``signal_absent`` (UNKNOWN) — portable pytest never references the real store; THIS runtime
    check is the pin. Never green on absence."""
    try:
        from cisco_toolkit import memory_guard as MG
    except Exception as e:                      # the guard mechanism itself deleted/broken -> RED, not a crash
        return _check("protected_artifact", RED, f"cisco_toolkit.memory_guard unavailable ({e!r}) — the D12 guard mechanism is gone")
    problems: List[str] = []
    # Doctrine side (repo-portable): every pinned anchor must still ground verbatim in the owner.
    try:
        doctrine = open(os.path.join(root, "CLAUDE.md"), encoding="utf-8", errors="replace").read()
    except OSError:
        doctrine = ""
    drifted = MG.reconcile_constraints(doctrine)
    if drifted:
        problems.append(f"doctrine drift: {len(drifted)}/{len(MG.CANONICAL_SAFETY_CONSTRAINTS)} canonical anchor(s) "
                        f"not verbatim in CLAUDE.md (first: {drifted[0]})")
    # Store side (per-machine): a missing store is a missing SIGNAL, not health.
    mdir = MG.resolve_store_dir(memory_dir)
    if not os.path.isdir(mdir):
        if problems:                            # doctrine drift is verified regardless of the store
            return _check("protected_artifact", RED, "; ".join(problems) + f" (store itself absent at {mdir})")
        return _check("protected_artifact", UNKNOWN,
                      f"signal_absent: agent-memory store not found at {mdir} "
                      f"(set {MG.AGENT_MEMORY_DIR_ENV} to point at it) — absence is never green")
    store = MG.load_store(mdir)
    # The pinned expectation, reconciled via the guard's own loss detector: an entry named after the
    # artifact must survive in the live store (deletion OR a name-pin rewrite reads as dropped).
    expected = [MG.MemoryEntry(name=os.path.splitext(MG.PROTECTED_ARTIFACT)[0], body="", meta={"protected": "true"})]
    body_measure = ""
    if MG.missing_protected(expected, store) or not os.path.exists(os.path.join(mdir, MG.PROTECTED_ARTIFACT)):
        problems.append(f"{MG.PROTECTED_ARTIFACT} dropped from the store ({mdir}) — the D12 never-delete tier is gone")
    else:
        entry = MG.load_entry(os.path.join(mdir, MG.PROTECTED_ARTIFACT))
        if not entry.protected:                 # the frontmatter flip: protected: true -> false
            problems.append("frontmatter no longer marks the artifact protected "
                            "(protected/type-constraint marker off) — consolidation may now compress it")
        unpinned = MG.unpinned_constraints(store)
        if unpinned:
            problems.append(f"{len(unpinned)}/{len(MG.CANONICAL_SAFETY_CONSTRAINTS)} canonical constraint(s) "
                            f"unpinned by any protected entry (first: {unpinned[0]})")
        # D12 is a VERBATIM requirement: the checks above are all satisfied by an artifact compressed
        # to a list of the anchor phrases, which is the compression they exist to catch.
        problems += protected_body_integrity(entry.body, MG.CANONICAL_SAFETY_CONSTRAINTS)
        body_measure = (f", body {len(entry.body.strip())} chars = "
                        f"{len(entry.body.strip()) / max(1, sum(len(a) for _, a in MG.CANONICAL_SAFETY_CONSTRAINTS)):.1f}x "
                        "the anchor text (not compressed to a keyword list)")
    # Index coverage: MEMORY.md is what re-surfaces the fact at session start (BLK-1 route d).
    try:
        index_text = open(os.path.join(mdir, "MEMORY.md"), encoding="utf-8", errors="replace").read()
    except OSError:
        index_text = None
    if index_text is None:
        problems.append("MEMORY.md index absent from the store — the artifact cannot re-surface at session start")
    elif MG.PROTECTED_ARTIFACT not in index_text:
        problems.append(f"MEMORY.md no longer indexes {MG.PROTECTED_ARTIFACT} — an index prune orphaned the protected tier")
    if problems:
        return _check("protected_artifact", RED, "; ".join(problems))
    return _check("protected_artifact", GREEN,
                  f"{MG.PROTECTED_ARTIFACT} pinned: protected marker intact, all {len(MG.CANONICAL_SAFETY_CONSTRAINTS)} "
                  f"canonical anchors pinned + doctrine-reconciled, MEMORY.md indexes it"
                  f"{body_measure}. Structural pin — the BYTE-exact D12 check is "
                  "`python -m cisco_toolkit.memory_guard snapshot|verify` around a consolidation pass")


def _stable_graph_identity(path: str) -> Dict[str, Any]:
    """Hash one regular graph file and reject a replacement during the read."""
    if os.path.islink(path):
        raise ValueError("graph.json is a symlink")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("graph.json is not a regular file")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    def identity(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    if identity(before) != identity(after):
        raise ValueError("graph.json changed while hashing")
    return {"sha256": digest.hexdigest(), "size": after.st_size}


def _strict_json_equal(left: Any, right: Any) -> bool:
    """JSON comparison that keeps booleans distinct from integers."""
    try:
        return json.dumps(left, allow_nan=False, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return False


def _guarded_refresh_time(root: str) -> Tuple[Optional[float], Optional[str]]:
    """Validate clean-HEAD endpoint evidence and the still-identical graph bytes.

    This local hook receipt is not a signed source-to-output attestation and cannot
    exclude a source writer that changes and restores a file during extraction.
    """
    path = os.path.join(root, "graphify-out", ".guarded_refresh.json")
    if not os.path.exists(path):
        return None, None
    try:
        if os.path.islink(path) or os.path.getsize(path) > 16_384:
            raise ValueError("receipt is not a bounded regular file")
        with open(path, encoding="utf-8") as handle:
            receipt = json.load(handle)
        updated = datetime.fromisoformat(receipt["updated_at"])
        guard = receipt["guard"]
        python_version = guard.get("python") if isinstance(guard, dict) else None
        if not isinstance(python_version, str):
            raise ValueError("guard Python identity absent")
        try:
            python_parts = tuple(int(part) for part in python_version.split("."))
        except ValueError as exc:
            raise ValueError("guard Python identity invalid") from exc
        expected_guard = {**GRAPHIFY_GUARD_IDENTITY, "python": python_version}
        graph_path = os.path.join(root, "graphify-out", "graph.json")
        graph_identity = _stable_graph_identity(graph_path)
        head_proc = _run_git(root, "rev-parse", "--verify", "HEAD")
        status_proc = _run_git(root, "status", "--porcelain")
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"contract", "graph", "guard", "head", "phase", "root", "state", "updated_at"}
            or receipt.get("contract") != GRAPHIFY_REFRESH_RECEIPT_CONTRACT
            or receipt.get("phase") != "complete"
            or receipt.get("state") != "clean"
            or os.path.realpath(receipt.get("root", "")) != os.path.realpath(root)
            or python_parts < (3, 12)
            or not _strict_json_equal(guard, expected_guard)
            or not _strict_json_equal(receipt.get("graph"), graph_identity)
            or head_proc is None
            or head_proc.returncode != 0
            or receipt.get("head") != head_proc.stdout.strip()
            or status_proc is None
            or status_proc.returncode != 0
            or bool(status_proc.stdout.strip())
            or updated.tzinfo is None
        ):
            raise ValueError("receipt identity/state mismatch")
        return updated.timestamp(), None
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return None, f"guarded refresh receipt invalid: {exc}"


def check_graph_fresh(root: str, *, now: float, stale_days: int = 7) -> Dict[str, str]:
    """Verify bounded refresh bookkeeping; mtime is context, never refresh evidence."""
    del stale_days  # identity, not elapsed wall time, determines currency
    p = os.path.join(root, "graphify-out", "graph.json")
    if not os.path.exists(p):
        return _check("graph_refresh_receipt", UNKNOWN, "graphify-out/graph.json not found here (lives in the main checkout; a worktree won't have it)")
    refreshed_at, receipt_error = _guarded_refresh_time(root)
    try:
        topology_age = (now - os.path.getmtime(p)) / 86400.0
    except OSError as e:
        return _check("graph_refresh_receipt", UNKNOWN, f"could not stat graph.json: {e!r}")
    if receipt_error:
        return _check("graph_refresh_receipt", UNKNOWN, receipt_error)
    if refreshed_at is None:
        return _check(
            "graph_refresh_receipt",
            UNKNOWN,
            f"topology write is {topology_age:.0f}d old, but no current guarded refresh receipt exists; "
            "topology-neutral scans do not update graph.json mtime",
        )
    age_days = (now - refreshed_at) / 86400.0
    return _check(
        "graph_refresh_receipt",
        GREEN,
        f"guarded refresh completed at this clean HEAD; graph bytes still match "
        f"(recorded {age_days:.0f}d ago; concurrent source writes are not excluded)",
    )


def _graph_commit_verdict(built: str, head: str, is_ancestor: Optional[bool],
                          n_changed: Optional[int]) -> Tuple[str, str]:
    """The PURE decision for graph topology-stamp currency. ``built``/``head``
    are non-empty commit strings; ``is_ancestor`` is whether ``built`` is an ancestor of ``head`` (None =
    undeterminable); ``n_changed`` is the count of tracked paths changed between them (only meaningful when
    ``is_ancestor``). Coverage-honest: what cannot be evaluated is UNKNOWN, never a fabricated GREEN.

    Graphify intentionally leaves ``built_at_commit`` unchanged after a successful refresh whose graph topology
    is byte-equivalent. Any path drift is therefore a disclosed risk/UNKNOWN, not proof that the hook failed."""
    if head.startswith(built) or built.startswith(head):
        return GREEN, f"current (built at HEAD {head[:10]})"
    if is_ancestor is None:
        return UNKNOWN, f"built at {built[:10]}; ancestry vs HEAD {head[:10]} undeterminable"
    if not is_ancestor:
        return UNKNOWN, (
            f"built at {built[:10]} — not in current history (rebased/rewritten); "
            f"from the main checkout root, run: {GRAPHIFY_REFRESH_COMMAND}"
        )
    if n_changed is None:
        return UNKNOWN, (
            f"built at {built[:10]}; changed-path denominator vs HEAD {head[:10]} unavailable"
        )
    if n_changed <= 0:
        return GREEN, f"built at {built[:10]}; behind HEAD but no tracked path changed"
    return UNKNOWN, (
        f"built at topology write {built[:10]}; {n_changed} tracked path(s) changed since. "
        "The stamp does not distinguish a missed refresh from a successful topology-neutral scan; "
        f"from the main checkout root, run: {GRAPHIFY_REFRESH_COMMAND}"
    )


def _run_git(root: str, *args: str) -> Optional[subprocess.CompletedProcess]:
    """Run git in ``root``; None on any failure (the caller degrades to UNKNOWN — never crashes a run)."""
    try:
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        return subprocess.run(
            ["git", *args],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return None


def check_graph_commit_current(root: str) -> Dict[str, str]:
    """Disclose ``built_at_commit`` vs HEAD without overstating the stamp.

    The stamp records the last topology write, not the last successful full scan: Markdown body-only,
    unsupported, and other topology-neutral changes can be scanned successfully without advancing it.
    Any tracked-path drift is therefore UNKNOWN. Absent graph / non-git / unreadable is also UNKNOWN."""
    p = os.path.join(root, "graphify-out", "graph.json")
    if not os.path.exists(p):
        return _check("graph_commit", UNKNOWN, "graphify-out/graph.json not found here (lives in the main checkout)")
    try:
        with open(p, encoding="utf-8") as f:
            built = json.load(f).get("built_at_commit")
    except (OSError, ValueError) as e:
        return _check("graph_commit", UNKNOWN, f"could not read built_at_commit: {e!r}")
    if not built or not isinstance(built, str):
        return _check("graph_commit", UNKNOWN, "graph.json has no built_at_commit stamp")
    head_proc = _run_git(root, "rev-parse", "HEAD")
    if head_proc is None or head_proc.returncode != 0 or not head_proc.stdout.strip():
        return _check("graph_commit", UNKNOWN, "not a git checkout / HEAD unavailable")
    head = head_proc.stdout.strip()
    is_ancestor: Optional[bool] = None
    n_changed: Optional[int] = None
    if not (head.startswith(built) or built.startswith(head)):
        anc = _run_git(root, "merge-base", "--is-ancestor", built, head)
        if anc is not None and anc.returncode in (0, 1):
            is_ancestor = anc.returncode == 0
            if is_ancestor:
                diff = _run_git(root, "diff", "--name-only", built, head)
                if diff is not None and diff.returncode == 0:
                    n_changed = sum(1 for line in diff.stdout.splitlines() if line.strip())
    status, detail = _graph_commit_verdict(
        built,
        head,
        is_ancestor,
        n_changed,
    )
    return _check("graph_commit", status, detail)


def _guarded(name: str, fn, *args, **kwargs) -> Dict[str, str]:
    """Run one check; ANY exception becomes an UNKNOWN row NAMING the failure.

    This is what makes the module docstring's "a check that raises is caught and reported UNKNOWN,
    never crashes the nightly run" true. It was not: nothing wrapped the checks and the per-check
    guards caught only ``OSError``, so a single non-UTF-8 byte in ``scorecard.jsonl`` /
    ``pir_outcomes.jsonl`` / ``nightly_runs.jsonl`` / ``learnings.md`` raised ``UnicodeDecodeError``
    (a ``ValueError``) straight out of :func:`run_selfcheck` — the immune system went dark instead of
    reporting that it had gone dark, which is the one failure mode this module exists to prevent.
    UNKNOWN (not RED): the check was not evaluated, and an unevaluated check is never a verdict —
    it still forces 'GREEN-with-gaps', so it can never read as plain green."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:                       # noqa: BLE001 — a dark check must still report
        return _check(name, UNKNOWN,
                      f"check RAISED {type(e).__name__}: {e} — it could not be evaluated at all "
                      "(reported as a gap; absence of a signal is never GREEN)")


def run_selfcheck(root: Optional[str] = None, *, now: Optional[float] = None,
                  graph_stale_days: int = 7, memory_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run every check and summarize. ``now`` defaults to wall-clock and ``memory_dir`` to the real
    agent-memory store (both injected in tests — pytest must never touch the per-machine store). RED
    checks lead the briefing; the overall verdict is RED if any check is RED, else GREEN if none are
    UNKNOWN, else 'GREEN-with-gaps' (coverage-honest: unknowns are disclosed, not hidden).

    Every check runs through :func:`_guarded`, so one that raises is reported UNKNOWN under its own
    name and the remaining checks still run — a broken check can never take the whole nightly run
    (and with it every other signal) down with it."""
    root = _repo_root(root)
    now = now if now is not None else time.time()
    checks = [
        _guarded("scorecard_substrate", check_scorecard_substrate, root),
        _guarded("pir_outcomes_substrate", check_pir_substrate, root),
        _guarded("nightly_ledger", check_nightly_ledger, root),
        _guarded("learnings_discipline", check_learnings_discipline, root),
        _guarded("guards_nonvacuous", check_guards_nonvacuous, root),
        _guarded("judge_trust", check_judge_trust, root),
        _guarded("protected_artifact", check_protected_artifact, root, memory_dir=memory_dir),
        _guarded("graph_refresh_receipt", check_graph_fresh, root, now=now, stale_days=graph_stale_days),
        _guarded("graph_commit", check_graph_commit_current, root),
    ]
    n_red = sum(1 for c in checks if c["status"] == RED)
    n_unknown = sum(1 for c in checks if c["status"] == UNKNOWN)
    n_green = sum(1 for c in checks if c["status"] == GREEN)
    verdict = RED if n_red else ("GREEN" if not n_unknown else "GREEN-with-gaps")
    leads = [c for c in checks if c["status"] == RED]
    return {"verdict": verdict, "checks": checks, "leads": leads,
            "summary": {"green": n_green, "red": n_red, "unknown": n_unknown, "n": len(checks)}}


def render(report: Dict[str, Any]) -> str:
    sym = {GREEN: "[OK ]", RED: "[RED]", UNKNOWN: "[ ? ]"}
    s = report["summary"]
    L = [f"Agent-system self-check — {report['verdict']}  "
         f"({s['green']} green / {s['red']} red / {s['unknown']} unknown)"]
    for c in report["leads"]:                      # failures first (they lead the briefing)
        L.append(f"  {sym[RED]} {c['name']}: {c['detail']}")
    for c in report["checks"]:
        if c["status"] != RED:
            L.append(f"  {sym[c['status']]} {c['name']}: {c['detail']}")
    return "\n".join(L)


def main(argv: List[str] = None) -> int:
    """CLI: print the self-check. Exit 0 if not RED, 4 if any check is RED (a wrapper/briefing can flag it)."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    report = run_selfcheck()
    print(render(report))
    return 4 if report["verdict"] == RED else 0


if __name__ == "__main__":
    raise SystemExit(main())
