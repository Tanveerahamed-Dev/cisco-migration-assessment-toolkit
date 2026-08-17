"""Live **cutover-execution runs** — the war-room layer over the cutover plan.

``cutover.build_plan`` synthesizes the *plan* (gated waves, run-of-show, validation checks); a
deliverable freezes it on paper. What actually happens on the night of the change is a different
artifact: steps get checked off with timestamps, validation checks pass or fail against their
captured 'expect' baselines, waves are closed out (completed / rolled back / deferred), and every
note or deviation is scribed to a timeline. Standard change-management practice (ITIL change
enablement, Cisco AS cutover bridges) keeps exactly that record, because the post-implementation
review is written from it.

This module materializes a plan into a *frozen* execution state (so later re-uploads can't mutate a
run in flight), applies the war-room mutations, and derives live progress. It is webapp-only state —
the engine and its snapshot contract are untouched.

Outcome vocabulary follows the ITIL PIR outcomes: a change either met its objectives, met them with
deviations, was partially implemented, or was backed out.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import cutover

# One mutation at a time — uvicorn serves sync endpoints from a threadpool, so two concurrent
# check-offs on the same run would otherwise race the read-modify-write cycle.
MUTATION_LOCK = threading.Lock()


class RunClosedError(ValueError):
    """The run is finished — mutations are a conflict (409), not a bad request."""


class WaveClosedError(ValueError):
    """The wave is closed out — its steps/checks are part of the signed record (409)."""

STEP_STATUSES = ("pending", "done", "skipped")
CHECK_RESULTS = ("pending", "pass", "fail", "na")
CLOSEOUT_DECISIONS = ("COMPLETE", "ROLLED BACK", "DEFERRED")
EVENT_KINDS = ("note", "deviation")
RUN_STATUSES = ("in_progress", "completed", "aborted")

OUTCOME_SUCCESS = "SUCCESSFUL"
OUTCOME_DEVIATIONS = "SUCCESSFUL WITH DEVIATIONS"
OUTCOME_PARTIAL = "PARTIALLY IMPLEMENTED"
OUTCOME_ROLLED_BACK = "ROLLED BACK"
OUTCOME_ABORTED = "ABORTED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _unique_groups(plan_waves: List[Dict[str, Any]]) -> List[str]:
    """Wave identity keys. Group names come from the snapshot and can be missing or duplicated
    (e.g. uploaded wave_sequencing rows without 'group' all default to "") — every mutation is
    addressed by group, so a collision would silently route the second wave's actions to the first."""
    names: List[str] = []
    seen: set = set()
    for w in plan_waves:
        name = w["group"] or f"Wave {w['order']}"
        if name in seen:
            base, n = name, 2
            while f"{base} ({n})" in seen:
                n += 1
            name = f"{base} ({n})"
        seen.add(name)
        names.append(name)
    return names


def start_run(snap: Dict[str, Any], label: str, operator: str) -> Dict[str, Any]:
    """Materialize the snapshot's cutover plan into a frozen, executable run state."""
    plan = cutover.build_plan(snap)
    raw_plan_blockers = [
        row for row in plan.get("baseline_blockers", []) if isinstance(row, dict)
    ]
    # The plan deliberately shares each bound row object between the fleet list and its wave view.
    # Resolve that occurrence binding before the JSON-backed execution state copies the rows (where
    # object identity is lost). A blocker omitted from every scheduled wave remains a fleet-level
    # acceptance blocker and must survive the execution/PIR chain in full, outside diagnostic caps.
    bound_blocker_ids = {
        id(row)
        for wave in plan.get("waves", [])
        if isinstance(wave, dict)
        for row in wave.get("baseline_blockers", [])
        if isinstance(row, dict)
    }
    frozen_plan_blockers = [dict(row) for row in raw_plan_blockers]
    frozen_unbound_blockers = [
        dict(row) for row in raw_plan_blockers if id(row) not in bound_blocker_ids
    ]
    group_names = _unique_groups(plan["waves"])
    waves: List[Dict[str, Any]] = []
    for w, group_name in zip(plan["waves"], group_names):
        waves.append({
            "group": group_name,
            "order": w["order"],
            "gate": w["gate"],
            "strategy": w["strategy"],
            "n_switches": w["n_switches"],
            "switches": w["switches"],
            "endpoints": w["endpoints"],
            "hard_cutover_endpoints": w["hard_cutover_endpoints"],
            "est_window_minutes": w["est_window_minutes"],
            "est_window_label": w["est_window_label"],
            "blockers": w["blockers"],
            "current_baseline": w.get("current_baseline", {}),
            "baseline_blockers": w.get("baseline_blockers", []),
            "steps": [{
                "phase": s["phase"], "action": s["action"],
                "status": "pending", "at": None, "by": "", "note": "",
            } for s in w["run_of_show"]],
            "checks": [{
                "device": c.get("device", ""), "wave": c.get("wave", group_name),
                "category": c["category"], "severity": c["severity"], "check": c["check"],
                "command": c["command"], "expect": c["expect"],
                # Freeze the start-snapshot authority alongside the observed check. A later
                # upload/recollection must start a new run; it cannot silently rewrite this record.
                "evidence_state": c.get("evidence_state", ""),
                "projection_custody": c.get("projection_custody", ""),
                "source_key": c.get("source_key", ""),
                "why": c.get("why", ""),
                "baseline_state": c.get("baseline_state", ""),
                "baseline_blocker": bool(c.get("baseline_blocker")),
                "result": "pending", "observed": "", "at": None, "by": "",
            } for c in w["validation"]],
            "closeout": {"decision": None, "at": None, "by": "", "note": ""},
        })
    state = {
        "label": label.strip() or "Cutover run",
        "operator": operator.strip(),
        "status": "in_progress",
        "outcome": None,
        "started_at": _now(),
        "ended_at": None,
        "plan_summary": plan["summary"],
        "baseline_blockers": frozen_plan_blockers,
        "unbound_baseline_blockers": frozen_unbound_blockers,
        "waves": waves,
        "events": [],
    }
    _log(state, "run", f"Execution run started from the cutover plan (posture at start: "
                       f"{plan['summary'].get('verdict', '—')}).", "", operator)
    return state


def _log(state: Dict[str, Any], kind: str, text: str, wave: str, by: str) -> None:
    state["events"].append({"at": _now(), "kind": kind, "wave": wave, "text": text, "by": by.strip()})


def _wave(state: Dict[str, Any], group: str) -> Dict[str, Any]:
    for w in state["waves"]:
        if w["group"] == group:
            return w
    raise KeyError(group)


def _require_live(state: Dict[str, Any]) -> None:
    if state["status"] != "in_progress":
        raise RunClosedError(f"Run is already {state['status']} — it can no longer be modified.")


def _live_wave(state: Dict[str, Any], group: str) -> Dict[str, Any]:
    """The wave, only while it is still open — a closed-out wave is part of the signed record,
    so a late check-off (stale tab, scripted call) must not rewrite its timestamps."""
    w = _wave(state, group)
    decision = w["closeout"]["decision"]
    if decision:
        raise WaveClosedError(f"Wave '{group}' is already closed out ({decision}) — "
                              "its record can no longer be modified.")
    return w


def _item(items: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
    """Bounds-checked item lookup — a bare list index would let a negative index silently
    address from the end and corrupt the wrong step's record."""
    if not 0 <= index < len(items):
        raise IndexError(index)
    return items[index]


def apply_step(state: Dict[str, Any], group: str, index: int, status: str,
               note: str, by: str) -> None:
    _require_live(state)
    if status not in STEP_STATUSES:
        raise ValueError(f"status must be one of {STEP_STATUSES}")
    step = _item(_live_wave(state, group)["steps"], index)
    step["status"] = status
    step["at"] = _now() if status != "pending" else None
    step["by"] = by.strip() if status != "pending" else ""
    step["note"] = note.strip()
    verb = {"done": "completed", "skipped": "SKIPPED", "pending": "reset to pending"}[status]
    _log(state, "step", f"[{step['phase']}] {verb}" + (f" — {note.strip()}" if note.strip() else ""),
         group, by)


def apply_check(state: Dict[str, Any], group: str, index: int, result: str,
                observed: str, by: str) -> None:
    _require_live(state)
    if result not in CHECK_RESULTS:
        raise ValueError(f"result must be one of {CHECK_RESULTS}")
    check = _item(_live_wave(state, group)["checks"], index)
    if result == "pass" and check.get("baseline_blocker"):
        raise ValueError(
            "This check was a current-baseline blocker when the run started and cannot be recorded "
            "as a plain PASS. Re-collect a clear snapshot and start a new execution run."
        )
    check["result"] = result
    check["observed"] = observed.strip()
    check["at"] = _now() if result != "pending" else None
    check["by"] = by.strip() if result != "pending" else ""
    if result == "fail":
        _log(state, "deviation", f"Validation FAILED: {check['check']}"
             + (f" — observed: {observed.strip()}" if observed.strip() else ""), group, by)
    elif result != "pending":
        _log(state, "check", f"Validation {result.upper()}: {check['check']}", group, by)


def apply_closeout(state: Dict[str, Any], group: str, decision: str, note: str, by: str) -> None:
    _require_live(state)
    if decision not in CLOSEOUT_DECISIONS:
        raise ValueError(f"decision must be one of {CLOSEOUT_DECISIONS}")
    w = _live_wave(state, group)
    w["closeout"] = {"decision": decision, "at": _now(), "by": by.strip(), "note": note.strip()}
    kind = "deviation" if decision == "ROLLED BACK" else "gate"
    _log(state, kind, f"Wave closed out: {decision}"
         + (f" — {note.strip()}" if note.strip() else ""), group, by)


def add_event(state: Dict[str, Any], kind: str, text: str, wave: str, by: str) -> None:
    _require_live(state)
    if kind not in EVENT_KINDS:
        raise ValueError(f"kind must be one of {EVENT_KINDS}")
    if not text.strip():
        raise ValueError("event text must not be empty")
    _log(state, kind, text.strip(), wave.strip(), by)


def _derive_outcome(state: Dict[str, Any], status: str) -> str:
    if status == "aborted":
        return OUTCOME_ABORTED
    decisions = [w["closeout"]["decision"] for w in state["waves"]]
    if any(d == "ROLLED BACK" for d in decisions):
        return OUTCOME_ROLLED_BACK
    # `not decisions` first: over an EMPTY wave list both `any()` guards are vacuously False, so a run
    # with zero waves fell through to SUCCESSFUL and the PIR printed "Outcome: SUCCESSFUL" in green as its
    # title-page verdict over its own "0 of 0 wave(s) completed" body (pir_docx). Every other branch here
    # requires positive evidence; this one required none. Nothing was implemented, so the honest outcome
    # is PARTIALLY IMPLEMENTED — the same verdict as a run whose waves did not all close COMPLETE.
    if not decisions or any(d != "COMPLETE" for d in decisions):
        return OUTCOME_PARTIAL
    # New execution records freeze the shared current-baseline verdict in plan_summary. CLEAR is the
    # only state that can authorize a clean-success outcome; BLOCKED, INDETERMINATE, and NOT_ASSESSED
    # all require a fresh/recollected snapshot and a new run. Legacy records have no such field and
    # retain their historical outcome rules for backward compatibility.
    current_baseline = state.get("plan_summary", {}).get("current_baseline") \
        if isinstance(state.get("plan_summary"), dict) else None
    if isinstance(current_baseline, dict) and current_baseline.get("verdict") != "CLEAR":
        return OUTCOME_PARTIAL
    # A signed closeout is not evidence that the frozen run-of-show and validations actually
    # happened. Every wave needs positive required work, and every item must be actioned, before
    # either the execution response or its PIR may call the run successful.
    if any(not w.get("steps") or not w.get("checks") for w in state["waves"]):
        return OUTCOME_PARTIAL
    if any(s.get("status") == "pending" for w in state["waves"] for s in w["steps"]):
        return OUTCOME_PARTIAL
    if any(c.get("result") == "pending" for w in state["waves"] for c in w["checks"]):
        return OUTCOME_PARTIAL
    failed = any(c.get("result") != "pass" for w in state["waves"] for c in w["checks"])
    skipped = any(s.get("status") != "done" for w in state["waves"] for s in w["steps"])
    deviations = any(e["kind"] == "deviation" for e in state["events"])
    if failed or skipped or deviations:
        return OUTCOME_DEVIATIONS
    return OUTCOME_SUCCESS


def finish(state: Dict[str, Any], status: str, note: str, by: str) -> None:
    _require_live(state)
    if status not in ("completed", "aborted"):
        raise ValueError("status must be 'completed' or 'aborted'")
    state["status"] = status
    state["ended_at"] = _now()
    state["outcome"] = _derive_outcome(state, status)
    _log(state, "finish", f"Run {status} — outcome: {state['outcome']}"
         + (f" — {note.strip()}" if note.strip() else ""), "", by)


def with_current_outcome(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return a read view whose finished outcome uses the current evidence rules.

    Older rows may have persisted ``SUCCESSFUL`` under the former closeout-only rule. Reads and
    PIR exports must not keep publishing that stale verdict after the authority rule is fixed.
    """
    status = state.get("status")
    if status not in ("completed", "aborted"):
        return state
    current = _derive_outcome(state, status)
    if state.get("outcome") == current:
        return state
    return {**state, "outcome": current}


def _wave_state(w: Dict[str, Any]) -> str:
    decision = w["closeout"]["decision"]
    if decision == "COMPLETE":
        return "complete"
    if decision == "ROLLED BACK":
        return "rolled_back"
    if decision == "DEFERRED":
        return "deferred"
    touched = any(s["status"] != "pending" for s in w["steps"]) or \
        any(c["result"] != "pending" for c in w["checks"])
    return "active" if touched else "pending"


def wave_elapsed_minutes(w: Dict[str, Any]) -> Optional[int]:
    """Actual wave duration: first recorded action -> closeout (best effort, None until both exist)."""
    stamps = [t for t in
              ([s.get("at") for s in w["steps"]] + [c.get("at") for c in w["checks"]]) if t]
    start = min((d for d in map(_parse_ts, stamps) if d), default=None)
    end = _parse_ts(w["closeout"].get("at"))
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds() // 60))


def progress(state: Dict[str, Any]) -> Dict[str, Any]:
    """Derived live roll-up — recomputed on every read, never stored."""
    steps = [s for w in state["waves"] for s in w["steps"]]
    checks = [c for w in state["waves"] for c in w["checks"]]
    n_actioned = sum(1 for s in steps if s["status"] != "pending")
    started = _parse_ts(state["started_at"])
    ended = _parse_ts(state["ended_at"]) or datetime.now(timezone.utc)
    elapsed = int((ended - started).total_seconds()) if started else 0
    return {
        "n_steps": len(steps),
        "n_steps_done": sum(1 for s in steps if s["status"] == "done"),
        "n_steps_skipped": sum(1 for s in steps if s["status"] == "skipped"),
        "pct": int(round(100 * n_actioned / len(steps))) if steps else 0,
        "checks": {r: sum(1 for c in checks if c["result"] == r) for r in CHECK_RESULTS},
        "n_deviations": sum(1 for e in state["events"] if e["kind"] == "deviation"),
        "elapsed_seconds": max(0, elapsed),
        "planned_window_minutes": _planned_window(state),
        "waves": [{"group": w["group"], "state": _wave_state(w),
                   "n_steps": len(w["steps"]),
                   "n_actioned": sum(1 for s in w["steps"] if s["status"] != "pending")}
                  for w in state["waves"]],
    }


def _planned_window(state: Dict[str, Any]) -> int:
    try:
        return int((state.get("plan_summary") or {}).get("est_window_minutes") or 0)
    except (TypeError, ValueError, OverflowError):   # OverflowError: a JSON Infinity est_window_minutes
        return 0


def with_progress(execution_id: int, snapshot_id: int, state: Dict[str, Any]) -> Dict[str, Any]:
    """The API shape: the state plus its identifiers and the derived progress block."""
    state = with_current_outcome(state)
    return {"id": execution_id, "snapshot_id": snapshot_id, **state, "progress": progress(state)}
