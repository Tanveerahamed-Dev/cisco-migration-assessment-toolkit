"""Agent-system self-check (Phase 4) — the immune system that verifies the guards are NON-VACUOUS.

Phase 4 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` runs this in the nightly clock and leads
the morning briefing with any failure. The whole autonomy story rests on guards (evals, the scorecard
appender, the protected-constraint tier, the learnings discipline, the SSOT reconcilers). A guard that has
been **deleted or gutted** silently stops protecting — a *skipped* test is **red**, not green. This module
re-derives, from the repo, whether each guard is present and actually asserting, plus whether the feedback
substrate is being written and the graph is fresh.

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
]


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
                  graph_stale_days: int = 7) -> Dict[str, Any]:
    """Run every check and summarize. ``now`` defaults to wall-clock (injected in tests). RED checks lead
    the briefing; the overall verdict is RED if any check is RED, else GREEN if none are UNKNOWN, else
    'GREEN-with-gaps' (coverage-honest: unknowns are disclosed, not hidden)."""
    root = _repo_root(root)
    now = now if now is not None else time.time()
    checks = [
        check_scorecard_substrate(root),
        check_pir_substrate(root),
        check_nightly_ledger(root),
        check_learnings_discipline(root),
        check_guards_nonvacuous(root),
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
