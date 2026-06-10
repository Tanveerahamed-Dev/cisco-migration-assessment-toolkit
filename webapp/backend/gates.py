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


def apply_decision(store, campaign_id: int, wave: str, gate: str, decision: str,
                   signed_by: str = "", note: str = "") -> None:
    """Record one gate disposition — the domain rule lives HERE, next to its constants
    (V3.23.159): 'pending' IS the absence of a row, so clearing deletes; only decisions someone
    actually made persist (a stored 'pending' would leak into the plan of record as a signed
    disposition). Raises ValueError on an unknown gate or decision; the route maps it to a 400."""
    if gate not in GATE_KEYS:
        raise ValueError(f"Unknown gate '{gate}' (expected one of {list(GATE_KEYS)})")
    if decision == "pending":
        store.clear_gate(campaign_id, wave, gate)  # idempotent: clearing a clear cell is fine
    elif decision in DECISIONS:
        store.upsert_gate(campaign_id, wave, gate, decision, signed_by, note)
    else:
        raise ValueError(f"Unknown decision '{decision}' "
                         f"(expected one of {list(DECISIONS)} or 'pending')")
