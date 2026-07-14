"""Gate-board domain logic: the per-wave T-minus sign-off record for a campaign.

The cadence (which gates exist, in what order) is the engine's `GATE_SEQUENCE` — one source of
truth with the Engagement Workflow & Plan of Record deliverable, so a decision recorded here lands
back in that document's §4.3 "Gate record (as signed)" under exactly the same gate names. Waves are
the campaign's latest-snapshot migration-readiness groups ("Group N"), the same labels the cutover
plan and the war-room execution console use, so the whole loop joins on one key.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def _is_go(cell: Any) -> bool:
    """A gate cell counts as GO only on an explicit 'go' decision (absent/None/other = not GO)."""
    return isinstance(cell, dict) and cell.get("decision") == "go"


def upstream_gap(rows_by_gate: Dict[str, Any], gate: str) -> Optional[str]:
    """The PPDIOO ordering rule for ONE wave, in one place (the whole subsystem defers to it).

    When `gate` is signed 'go', return the FIRST earlier gate in GATE_KEYS that is absent or not
    itself 'go' — the upstream a downstream GO would contradict ("never advance a gate without its
    upstream artifact"). Returns None when `gate` is not a 'go', is not a known gate, or every
    earlier gate is 'go' (i.e. the sign-off is in order). `rows_by_gate` maps a gate key to its
    stored cell/row — any dict carrying a 'decision' (both the flat board row and the §4.3 cell)."""
    if gate not in GATE_KEYS or not _is_go(rows_by_gate.get(gate)):
        return None
    for prior in GATE_KEYS[:GATE_KEYS.index(gate)]:
        if not _is_go(rows_by_gate.get(prior)):
            return prior
    return None


def annotate_out_of_order(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The gate board's rows (a shallow copy of each), tagged with the ordering annotation the §4.3
    plan-of-record trail also carries. Every row gets `out_of_order` (bool); an out-of-order row
    additionally gets `out_of_order_upstream` naming the offending gate key. Coverage-honesty
    (surface, don't hide): the board DISCLOSES a 'go' recorded atop an absent/NO-GO upstream instead
    of blocking it — real engagements do record conditional/provisional sign-offs; the defect was
    publishing them as if clean. Derived per read, never stored, so signing the missing upstream
    later clears the flag on its own."""
    by_wave: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        by_wave.setdefault(str(r.get("wave")), {})[str(r.get("gate"))] = r
    annotated: List[Dict[str, Any]] = []
    for r in rows:
        gap = upstream_gap(by_wave.get(str(r.get("wave")), {}), str(r.get("gate")))
        row = dict(r)
        row["out_of_order"] = gap is not None
        if gap is not None:
            row["out_of_order_upstream"] = gap
        annotated.append(row)
    return annotated


def gate_record(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Shape stored gate rows into the writer's contract:
    {wave: {gate_key: {decision, signed_by, note, decided_at[, out_of_order, out_of_order_upstream]}}}.
    An out-of-order 'go' (recorded before an upstream gate was itself 'go') carries the two extra
    keys so §4.3 can DISCLOSE the contradiction rather than render it as a clean sign-off — same
    coverage-honesty as the live board (see annotate_out_of_order). Computed here, not stored, so it
    always reflects the wave's current full record."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["wave"]), {})[str(r["gate"])] = {
            "decision": r.get("decision"), "signed_by": r.get("signed_by"),
            "note": r.get("note"), "decided_at": r.get("decided_at"),
        }
    for by_gate in out.values():
        for gate, cell in by_gate.items():
            gap = upstream_gap(by_gate, gate)
            if gap is not None:
                cell["out_of_order"] = True
                cell["out_of_order_upstream"] = gap
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
