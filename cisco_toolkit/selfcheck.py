"""Agent-system self-check (Phase 4) — the immune system that verifies the guards are NON-VACUOUS.

Phase 4 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` runs this in the nightly clock and leads
the morning briefing with any failure. The whole autonomy story rests on guards (evals, the scorecard
appender, the protected-constraint tier, the learnings discipline, the SSOT reconcilers). A guard that has
been **deleted or gutted** silently stops protecting — a *skipped* test is **red**, not green. This module
re-derives, from the repo, whether each guard is present and actually asserting, plus whether the feedback
substrate is being written, the graph is fresh, and the REAL protected-memory artifact is still pinned
(P0-1 / DEC-005 — the memory_guard mechanism's only live wiring).

Every check returns **GREEN** (verified healthy), **RED** (verified broken — leads the briefing), or
**UNKNOWN** (could not be evaluated — coverage-honest: absence of a signal is *never* rendered GREEN). Pure
filesystem + a couple of real guard invocations (the learnings lint); ``root`` and ``now`` are injectable so
it is deterministic and unit-testable. Total — a check that raises is caught and reported UNKNOWN, never
crashes the nightly run.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

GREEN, RED, UNKNOWN = "GREEN", "RED", "UNKNOWN"

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
]

# The D12 protected-tier artifact constants (store path, env override, artifact name) are OWNED by
# cisco_toolkit.memory_guard (one source of truth) and imported lazily inside the check, so a deleted
# guard module reads RED there instead of breaking this module's import.


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


def check_guards_nonvacuous(root: str) -> Dict[str, str]:
    """Each guard file must exist AND contain an assertion (a deleted/gutted guard is RED, not silently gone)."""
    missing, vacuous = [], []
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
        if "assert" not in txt and "pytest.fail" not in txt:
            vacuous.append(rel)
    if missing or vacuous:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if vacuous:
            parts.append(f"no assertions: {', '.join(vacuous)}")
        return _check("guards_nonvacuous", RED, "; ".join(parts))
    return _check("guards_nonvacuous", GREEN, f"all {len(GUARD_FILES)} guard suites present and asserting")


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
                  f"canonical anchors pinned + doctrine-reconciled, MEMORY.md indexes it")


def check_graph_fresh(root: str, *, now: float, stale_days: int = 7) -> Dict[str, str]:
    """graph.json lives in the MAIN checkout (untracked) — absent in a worktree -> UNKNOWN, never RED/GREEN."""
    p = os.path.join(root, "graphify-out", "graph.json")
    if not os.path.exists(p):
        return _check("graph_fresh", UNKNOWN, "graphify-out/graph.json not found here (lives in the main checkout; a worktree won't have it)")
    try:
        age_days = (now - os.path.getmtime(p)) / 86400.0
    except OSError as e:
        return _check("graph_fresh", UNKNOWN, f"could not stat graph.json: {e!r}")
    if age_days > stale_days:
        return _check("graph_fresh", RED, f"stale: {age_days:.0f}d old (> {stale_days}d) — run: python -m graphify update .")
    return _check("graph_fresh", GREEN, f"fresh ({age_days:.0f}d old)")


def run_selfcheck(root: Optional[str] = None, *, now: Optional[float] = None,
                  graph_stale_days: int = 7, memory_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run every check and summarize. ``now`` defaults to wall-clock and ``memory_dir`` to the real
    agent-memory store (both injected in tests — pytest must never touch the per-machine store). RED
    checks lead the briefing; the overall verdict is RED if any check is RED, else GREEN if none are
    UNKNOWN, else 'GREEN-with-gaps' (coverage-honest: unknowns are disclosed, not hidden)."""
    root = _repo_root(root)
    now = now if now is not None else time.time()
    checks = [
        check_scorecard_substrate(root),
        check_pir_substrate(root),
        check_nightly_ledger(root),
        check_learnings_discipline(root),
        check_guards_nonvacuous(root),
        check_protected_artifact(root, memory_dir=memory_dir),
        check_graph_fresh(root, now=now, stale_days=graph_stale_days),
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
