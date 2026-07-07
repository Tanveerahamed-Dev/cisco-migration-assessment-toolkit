"""Tests for the clock's safety rails (cisco_toolkit.clock) — Phase 2 prerequisites.

The rails must be correct BEFORE any paid nightly run is ever scheduled. Load-bearing properties:

- the breaker **trips on exactly three** consecutive failures (Phase-2 acceptance), holds open through a
  30-minute cooldown, then allows a single half-open probe — and is **fail-safe** (open) when it can't age
  the cooldown;
- the daily-spend gate blocks once today's spend reaches the ceiling, counting only runs that actually ran;
- ``preflight`` is GO only when BOTH rails pass;
- the weekly report flags a **zero-value week** (cost but no action) — value has to be falsifiable too.

The decision core takes an injected ``now``, so every case is deterministic — no real clock, no scheduler.
"""
import json
import os
from datetime import datetime, timedelta

from cisco_toolkit import clock as C

NOW = datetime(2026, 7, 7, 3, 0, 0)   # a 3am nightly slot


def _run(outcome, *, ts=NOW, day=None, cost=0.0, actions=0, turns=0):
    return {"date": (day or ts.date().isoformat()), "ts": ts.isoformat(timespec="seconds"),
            "outcome": outcome, "cost_usd": cost, "turns": turns, "actions": actions,
            "commit": "c", "notes": ""}


# --- breaker -----------------------------------------------------------------------------------

def test_consecutive_failures_counts_trailing_and_resets_on_ok():
    assert C.consecutive_failures([_run("fail"), _run("ok"), _run("fail"), _run("fail")]) == 2
    assert C.consecutive_failures([_run("fail"), _run("fail"), _run("ok")]) == 0     # ok is newest
    assert C.consecutive_failures([_run("fail"), _run("blocked"), _run("fail")]) == 2  # blocked transparent


def test_breaker_closed_below_threshold():
    b = C.breaker_state([_run("fail"), _run("fail")], now=NOW)     # 2 < 3
    assert b["state"] == "closed" and b["allowed"] is True


def test_breaker_trips_on_three_failures():
    """Phase-2 acceptance: three induced failures trip the breaker (allowed=False)."""
    b = C.breaker_state([_run("fail"), _run("fail"), _run("fail")], now=NOW)   # ts=NOW -> in cooldown
    assert b["consecutive_failures"] == 3
    assert b["state"] == "open" and b["allowed"] is False


def test_breaker_open_within_cooldown_then_half_open_after():
    recent = [_run("fail", ts=NOW - timedelta(minutes=10))] * 3
    b1 = C.breaker_state(recent, now=NOW)
    assert b1["state"] == "open" and b1["allowed"] is False
    assert b1["cooldown_remaining_min"] and b1["cooldown_remaining_min"] > 0

    aged = [_run("fail", ts=NOW - timedelta(minutes=31))] * 3
    b2 = C.breaker_state(aged, now=NOW)
    assert b2["state"] == "half_open" and b2["allowed"] is True   # one probe permitted


def test_breaker_fail_safe_when_no_timestamp():
    b = C.breaker_state([{"outcome": "fail"}] * 3, now=NOW)       # tripped, no ts to age cooldown
    assert b["state"] == "open" and b["allowed"] is False         # fail-safe: stays open


# --- budget ------------------------------------------------------------------------------------

def test_budget_gate_blocks_at_ceiling():
    today = NOW.date().isoformat()
    under = [_run("ok", cost=0.8), _run("ok", cost=0.7)]          # 1.5 < 2.0
    assert C.budget_gate(under, today=today)["allowed"] is True
    over = under + [_run("ok", cost=0.6)]                         # 2.1 >= 2.0
    g = C.budget_gate(over, today=today)
    assert g["allowed"] is False and g["spent_usd"] == 2.1


def test_budget_ignores_non_running_outcomes_and_other_days():
    today = NOW.date().isoformat()
    rows = [_run("blocked", cost=5.0), _run("skipped", cost=5.0),
            _run("ok", cost=1.0, day="2026-07-01")]              # different day
    assert C.spent_today(rows, today=today) == 0.0               # nothing counts today


# --- preflight (both rails) --------------------------------------------------------------------

def test_preflight_go_when_both_pass():
    r = C.preflight([_run("ok", cost=0.2)], now=NOW)
    assert r["allowed"] is True and r["reason"].startswith("GO")


def test_preflight_nogo_when_breaker_open():
    r = C.preflight([_run("fail")] * 3, now=NOW)
    assert r["allowed"] is False and "breaker OPEN" in r["reason"]


def test_preflight_nogo_when_over_budget():
    r = C.preflight([_run("ok", cost=2.5)], now=NOW)
    assert r["allowed"] is False and "ceiling" in r["reason"]


# --- weekly spend-vs-action report -------------------------------------------------------------

def test_weekly_report_flags_zero_value_week():
    rep = C.weekly_report([_run("ok", cost=1.0, actions=0, day="2026-07-06")], now=NOW)
    assert rep["zero_value_week"] is True and rep["cost_usd"] == 1.0
    assert "zero-value" in rep["note"]


def test_weekly_report_cost_per_action_and_window():
    rows = [_run("ok", cost=1.0, actions=2, day="2026-07-06"),
            _run("ok", cost=1.0, actions=2, day="2026-06-01")]   # outside the 7-day window
    rep = C.weekly_report(rows, now=NOW)
    assert rep["runs"] == 1 and rep["cost_usd"] == 1.0 and rep["actions"] == 2
    assert rep["cost_per_action"] == 0.5 and rep["zero_value_week"] is False


# --- persistence -------------------------------------------------------------------------------

def test_read_runs_missing_file_is_empty():
    assert C.read_runs(os.path.join("no", "such", "f.jsonl")) == []


def test_make_run_row_stamps_clock_and_append_is_schema_ordered(tmp_path):
    row = C.make_run_row(outcome="OK", now=NOW, cost_usd=0.5, actions=3, notes="x")
    assert row["outcome"] == "ok" and row["date"] == "2026-07-07"
    assert row["ts"].startswith("2026-07-07T03:00:00")
    p = str(tmp_path / "n.jsonl")
    assert C.append_run(row, p) is True
    obj = json.loads(open(p, encoding="utf-8").read().splitlines()[0])
    assert list(obj.keys()) == list(C.SCHEMA_KEYS)
