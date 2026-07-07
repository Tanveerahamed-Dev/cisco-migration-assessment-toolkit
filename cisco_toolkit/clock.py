"""The clock's safety rails — the 3-fail circuit breaker + the daily-spend gate (Phase 2 prerequisites).

Phase 2 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md`` wires a nightly, propose-only headless
``claude -p`` run. That run spends **real metered money** (D13) and can misfire, so it must never fire
without two rails checked FIRST:

1. **Circuit breaker (D5)** — three consecutive failed runs trips it; it then stays **open** for a
   30-minute cooldown, after which a single **half-open** probe is allowed (a fresh failure re-opens it,
   a success closes it). Prevents a broken nightly from hammering a failing system run after run.
2. **Daily-spend gate (D13)** — headless runs bill outside the interactive subscription, so spend is
   metered against a **daily ceiling**; once today's spend reaches it, no further run.

Plus the **weekly spend-vs-action report** (D13 / the metrics section): if a week's runs cost money but led
to **zero** actions, that is surfaced as a *kill-the-briefing* signal — value has to be falsifiable too.

**This module is the rails only — it starts nothing and spends nothing.** It does not register a scheduler
task and does not invoke ``claude -p``; those are the human-gated steps (like wiring ``/briefing`` into
SessionStart, they are deferred to explicit approval — a system-config + real-spend change). Here we build
the *decision* (``preflight`` -> go/no-go) and the *ledger* (``docs/quality/nightly_runs.jsonl``) a wrapper
would consult and append to.

Pure-stdlib; the decision core takes the clock (``now``) and rows as explicit arguments, so it is fully
deterministic and unit-testable without a real scheduler or a real clock (mirrors the injected date/commit
in :mod:`cisco_toolkit.scorecard`). Coverage-honest & **fail-safe** where safety is at stake: a tripped
breaker with no readable timestamp stays *open* (better to skip a nightly than to hammer a failing system);
absence is absence (an empty ledger is "no runs", never "healthy").
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# The append-only nightly-run ledger (one JSON object per line). Trackable — it is the audit trail the
# weekly spend-vs-action report reads.
NIGHTLY_RUNS_PATH = os.path.join("docs", "quality", "nightly_runs.jsonl")

# D5 breaker defaults; D13 spend default (conservative — a wrapper/env can raise it deliberately).
DEFAULT_FAIL_THRESHOLD = 3
DEFAULT_COOLDOWN_MIN = 30
DEFAULT_DAILY_CEILING_USD = 2.0

# One ledger row (emitted in this order). ``outcome`` in {ok, fail, blocked, skipped}: only ok/fail
# actually ran (and may have cost); blocked = a rail refused it; skipped = nothing to do.
SCHEMA_KEYS = ("date", "ts", "outcome", "cost_usd", "turns", "actions", "commit", "notes")
_COST_OUTCOMES = ("ok", "fail")   # the outcomes that can carry spend / count toward the breaker


# --- parsing helpers ---------------------------------------------------------------------------

def _parse_ts(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None


def _parse_date(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _outcome(r: Dict[str, Any]) -> str:
    return str(r.get("outcome", "")).lower()


# --- the circuit breaker (D5) ------------------------------------------------------------------

def consecutive_failures(rows: List[Dict[str, Any]]) -> int:
    """Trailing 'fail' outcomes since the last 'ok'. 'skipped'/'blocked'/unknown are transparent — a
    run a rail *blocked* is not a task failure, so it neither counts nor resets the breaker."""
    c = 0
    for r in reversed(rows or []):
        o = _outcome(r)
        if o == "fail":
            c += 1
        elif o == "ok":
            break
        # else: skipped/blocked/unknown -> ignore, keep walking back
    return c


def breaker_state(rows: List[Dict[str, Any]], *, now: datetime,
                  threshold: int = DEFAULT_FAIL_THRESHOLD,
                  cooldown_min: int = DEFAULT_COOLDOWN_MIN) -> Dict[str, Any]:
    """The breaker decision: closed / open / half_open, with the reason. Pure; ``now`` is injected."""
    cf = consecutive_failures(rows)
    if cf < threshold:
        return {"state": "closed", "allowed": True, "consecutive_failures": cf,
                "cooldown_remaining_min": None,
                "reason": f"breaker closed ({cf}/{threshold} consecutive failures)"}
    # Tripped — age the cooldown from the most recent failure's timestamp.
    last_fail_ts = None
    for r in reversed(rows or []):
        if _outcome(r) == "fail":
            last_fail_ts = _parse_ts(r.get("ts"))
            break
    if last_fail_ts is None:
        return {"state": "open", "allowed": False, "consecutive_failures": cf,
                "cooldown_remaining_min": None,
                "reason": (f"breaker OPEN ({cf} consecutive failures); no readable timestamp to age the "
                           f"{cooldown_min}m cooldown — staying open (fail-safe)")}
    remaining = cooldown_min - (now - last_fail_ts).total_seconds() / 60.0
    if remaining > 0:
        return {"state": "open", "allowed": False, "consecutive_failures": cf,
                "cooldown_remaining_min": round(remaining, 1),
                "reason": f"breaker OPEN ({cf} consecutive failures); {round(remaining, 1)}m cooldown remaining"}
    return {"state": "half_open", "allowed": True, "consecutive_failures": cf,
            "cooldown_remaining_min": None,
            "reason": (f"breaker HALF-OPEN — {cooldown_min}m cooldown elapsed; one probe run permitted "
                       f"(a fresh failure re-opens it)")}


# --- the daily-spend gate (D13) ----------------------------------------------------------------

def spent_today(rows: List[Dict[str, Any]], *, today: str) -> float:
    """Total USD spent by runs that actually ran today (ok/fail). blocked/skipped never cost."""
    tot = 0.0
    for r in rows or []:
        if str(r.get("date")) == today and _outcome(r) in _COST_OUTCOMES:
            v = r.get("cost_usd")
            if isinstance(v, (int, float)):
                tot += float(v)
    return round(tot, 4)


def budget_gate(rows: List[Dict[str, Any]], *, today: str,
                daily_ceiling_usd: float = DEFAULT_DAILY_CEILING_USD) -> Dict[str, Any]:
    spent = spent_today(rows, today=today)
    allowed = spent < daily_ceiling_usd
    return {"allowed": allowed, "spent_usd": spent, "ceiling_usd": daily_ceiling_usd,
            "remaining_usd": round(max(0.0, daily_ceiling_usd - spent), 4),
            "reason": (f"within daily ceiling (${spent:.2f} of ${daily_ceiling_usd:.2f})" if allowed
                       else f"daily ceiling reached (${spent:.2f} >= ${daily_ceiling_usd:.2f}) — no run")}


# --- combined go/no-go + reporting -------------------------------------------------------------

def preflight(rows: List[Dict[str, Any]], *, now: datetime,
              daily_ceiling_usd: float = DEFAULT_DAILY_CEILING_USD,
              threshold: int = DEFAULT_FAIL_THRESHOLD,
              cooldown_min: int = DEFAULT_COOLDOWN_MIN) -> Dict[str, Any]:
    """The nightly go/no-go a scheduler wrapper checks BEFORE it would ever call ``claude -p``. Both
    rails must pass. Never runs anything itself."""
    today = now.date().isoformat()
    b = breaker_state(rows, now=now, threshold=threshold, cooldown_min=cooldown_min)
    g = budget_gate(rows, today=today, daily_ceiling_usd=daily_ceiling_usd)
    allowed = bool(b["allowed"] and g["allowed"])
    blockers = [x["reason"] for x in (b, g) if not x["allowed"]]
    reason = "; ".join(blockers) if blockers else f'GO — {b["reason"]}; {g["reason"]}'
    return {"allowed": allowed, "reason": reason, "breaker": b, "budget": g, "today": today}


def weekly_report(rows: List[Dict[str, Any]], *, now: datetime, days: int = 7) -> Dict[str, Any]:
    """Spend-vs-action over the trailing ``days`` (D13). Flags a *zero-value week* — cost but no action —
    as the kill-the-briefing signal (value must be falsifiable, not assumed)."""
    today = now.date()
    start = today - timedelta(days=days - 1)
    window = [r for r in (rows or []) if (_parse_date(r.get("date")) or date.min) >= start
              and (_parse_date(r.get("date")) or date.max) <= today]
    cost = round(sum(float(r["cost_usd"]) for r in window if isinstance(r.get("cost_usd"), (int, float))), 4)
    actions = sum(int(r["actions"]) for r in window if isinstance(r.get("actions"), int))
    outcomes: Dict[str, int] = {}
    for r in window:
        o = _outcome(r) or "?"
        outcomes[o] = outcomes.get(o, 0) + 1
    zero_value = cost > 0 and actions == 0
    note = ("zero-value week — spend without action; per D13 reconsider the nightly briefing"
            if zero_value else f"{len(window)} run(s), ${cost:.2f}, {actions} action(s) over {days}d")
    return {"window_days": days, "from": start.isoformat(), "to": today.isoformat(),
            "runs": len(window), "cost_usd": cost, "outcomes": outcomes, "actions": actions,
            "cost_per_action": round(cost / actions, 4) if actions else None,
            "zero_value_week": zero_value, "note": note}


# --- persistence -------------------------------------------------------------------------------

def read_runs(path: str = NIGHTLY_RUNS_PATH) -> List[Dict[str, Any]]:
    """Every well-formed row, in file order. Missing/empty -> [] (absence is absence). Mirrors
    :func:`cisco_toolkit.scorecard.read_rows`."""
    try:
        with open(path, encoding="utf-8") as f:
            out: List[Dict[str, Any]] = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            return out
    except OSError:
        return []


def make_run_row(*, outcome: str, now: datetime, cost_usd: float = 0.0, turns: int = 0,
                 actions: int = 0, commit: str = "", notes: str = "") -> Dict[str, Any]:
    """Build a schema-exact ledger row, stamping date+ts from the injected clock."""
    return {"date": now.date().isoformat(), "ts": now.isoformat(timespec="seconds"),
            "outcome": str(outcome).lower(), "cost_usd": round(float(cost_usd), 4),
            "turns": int(turns), "actions": int(actions), "commit": commit, "notes": notes}


def append_run(row: Dict[str, Any], path: str = NIGHTLY_RUNS_PATH) -> bool:
    """Append one ledger row (JSON, one line, schema order). Creates the file/dir if absent."""
    if not isinstance(row, dict):
        return False
    ordered = {k: row.get(k) for k in SCHEMA_KEYS}
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=True) + "\n")
    return True


# --- CLI ---------------------------------------------------------------------------------------

def render_preflight(res: Dict[str, Any]) -> str:
    tag = "GO" if res["allowed"] else "NO-GO"
    return (f"nightly preflight [{tag}] — {res['reason']}\n"
            f"  breaker: {res['breaker']['state']} ({res['breaker']['consecutive_failures']} consec. fail)\n"
            f"  budget:  ${res['budget']['spent_usd']:.2f} of ${res['budget']['ceiling_usd']:.2f} "
            f"(${res['budget']['remaining_usd']:.2f} left today)")


def render_report(rep: Dict[str, Any]) -> str:
    L = [f"nightly spend-vs-action — {rep['from']} → {rep['to']} ({rep['window_days']}d)",
         f"  runs {rep['runs']}  outcomes {rep['outcomes']}  spend ${rep['cost_usd']:.2f}  "
         f"actions {rep['actions']}"
         + (f"  (${rep['cost_per_action']:.2f}/action)" if rep["cost_per_action"] is not None else ""),
         f"  {rep['note']}"]
    if rep["zero_value_week"]:
        L.append("  [!] zero-value week")
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. ``--preflight`` prints the go/no-go and exits 0 (go) or 3 (no-go) so a wrapper can bail;
    ``--report`` prints the weekly spend-vs-action; ``--show`` tails the ledger; ``--record`` appends a
    ledger row read as JSON on stdin. Reads/derives only — never starts a run, never spends."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    path = os.environ.get("NIGHTLY_RUNS_FILE") or NIGHTLY_RUNS_PATH
    ceiling = float(os.environ.get("ASNE_NIGHTLY_CEILING_USD") or DEFAULT_DAILY_CEILING_USD)
    rows = read_runs(path)
    if "--report" in argv:
        print(render_report(weekly_report(rows, now=datetime.now())))
        return 0
    if "--show" in argv:
        if not rows:
            print("nightly_runs: no entries yet")
        else:
            for r in rows[-10:]:
                print(json.dumps(r, ensure_ascii=True))
        return 0
    if "--record" in argv:
        try:
            row = json.loads(sys.stdin.read() or "{}")
            if "date" not in row or "ts" not in row:
                row = make_run_row(now=datetime.now(), **{k: row[k] for k in
                                   ("outcome", "cost_usd", "turns", "actions", "commit", "notes") if k in row})
            print("recorded" if append_run(row, path) else "not recorded")
        except Exception as e:
            print(f"record failed: {e!r}")
        return 0
    # default: preflight
    res = preflight(rows, now=datetime.now(), daily_ceiling_usd=ceiling)
    print(render_preflight(res))
    return 0 if res["allowed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
