"""Gate-board domain logic: the per-wave T-minus sign-off record for a campaign.

The cadence (which gates exist, in what order) is the engine's `GATE_SEQUENCE` — one source of
truth with the Engagement Workflow & Plan of Record deliverable, so a decision recorded here lands
back in that document's §4.3 "Gate record (as signed)" under exactly the same gate names. Waves are
the campaign's latest-snapshot migration-readiness groups ("Group N"), the same labels the cutover
plan and the war-room execution console use, so the whole loop joins on one key.
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import engine  # noqa: F401  (import bootstraps sys.path so cisco_toolkit.* resolves)
from cisco_toolkit.engagement import GATE_SEQUENCE  # noqa: E402

GATE_KEYS = tuple(key for key, *_rest in GATE_SEQUENCE)
DECISIONS = ("go", "no-go", "slipped")  # 'pending' clears the row instead of storing a non-decision


def cadence() -> List[Dict[str, str]]:
    """The gate cadence for the UI: key + label + when (purpose/criteria live in the deliverable)."""
    return [{"key": key, "label": label, "when": when}
            for key, label, when, _purpose, _criteria in GATE_SEQUENCE]


def waves_from_snapshot(snap: dict | None) -> List[str]:
    """The wave labels a gate board offers — the snapshot's migration-readiness groups, in order."""
    rows = (snap or {}).get("migration_readiness") or []
    return [str(r.get("group")) for r in rows if isinstance(r, dict) and r.get("group")]


def gate_record(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Shape stored gate rows into the writer's contract:
    {wave: {gate_key: {decision, signed_by, note, decided_at}}}."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["wave"]), {})[str(r["gate"])] = {
            "decision": r.get("decision"), "signed_by": r.get("signed_by"),
            "note": r.get("note"), "decided_at": r.get("decided_at"),
        }
    return out
