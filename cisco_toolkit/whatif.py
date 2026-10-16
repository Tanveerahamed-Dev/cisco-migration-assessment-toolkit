"""Single-snapshot failure-injection what-if (roadmap G4) — offline, read-only, coverage-honest.

Selector's flagship is a compound "what if a router AND a circuit AND a region fail?" — recast here with
zero device contact and no second collection: deep-mutate ONE snapshot in memory (remove a node / a whole
site from `snap['routes']`, so its owned next-hops vanish), then re-run the EXISTING `fib.reachability_diff`
against the original. We already own the FIB engine; this just feeds it a synthetic post-failure snapshot.

COVERAGE-HONEST by construction (it inherits `fib`'s honesty): removing a transit node makes the flows that
forwarded through it resolve to `lower_bound:next_hop_not_collected` -> `inconclusive`. We surface those as
PATH LOST (a flow that WAS computed-reached and is now unprovable), never as a fabricated `newly_blocked`.
A flow is only reported `blocked` when `fib` returns the definitive `newly_blocked` verdict on its own.
The input snapshot is never modified (a shallow copy with a filtered `routes` dict).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import fib


def _match_failures(hosts: List[str], failures: List[dict]) -> set:
    """Resolve a scenario's failures to the concrete set of hosts to remove. type 'node' = exact host
    (case-insensitive); type 'site' = case-insensitive substring of the hostname (a campus/site code)."""
    removed: set = set()
    for f in failures or []:
        if not isinstance(f, dict):              # a malformed catalog entry is skipped, never aborts the batch
            continue
        ftype = str(f.get("type") or "node").lower()
        fid = str(f.get("id") or "").strip().lower()
        if not fid:
            continue
        for h in hosts:
            hl = str(h).strip().lower()
            if ftype == "site":
                if fid in hl:
                    removed.add(h)
            elif hl == fid:
                removed.add(h)
    return removed


def apply_scenario(snap: Dict[str, Any], scenario: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Return (mutated_snapshot, sorted removed_hosts). The mutation is a shallow copy whose `routes` dict
    excludes the failed hosts — the original snapshot is left untouched (read-only)."""
    routes = (snap or {}).get("routes")
    routes = routes if isinstance(routes, dict) else {}
    removed = _match_failures(list(routes.keys()), (scenario or {}).get("failures") or [])
    mutated = dict(snap or {})
    mutated["routes"] = {h: r for h, r in routes.items() if h not in removed}
    return mutated, sorted(removed)


def run_scenario(snap: Dict[str, Any], scenario: Dict[str, Any], pairs: Optional[list] = None,
                 limit: int = 24, max_pairs: int = 400) -> Dict[str, Any]:
    """Inject one failure scenario and classify how reachability changed across the tested flows.

    Returns {scenario, removed_hosts, blocked_flows, lost_flows, summary, note}. `blocked_flows` are the
    DEFINITIVE regressions (fib `newly_blocked`); `lost_flows` were computed-reached and are now
    inconclusive because their path went through the removed device (coverage-honest: path lost, not a
    claimed drop)."""
    mutated, removed = apply_scenario(snap, scenario)
    if pairs is None:
        pairs = fib.default_pairs(snap, limit, max_pairs)
    diff = fib.reachability_diff(snap, mutated, pairs)

    blocked: List[dict] = []
    lost: List[dict] = []
    preserved = 0
    inconclusive_other = 0
    other = 0                                    # both_unreachable / newly_reachable -> surfaced, never silently dropped
    for p in diff["pairs"]:
        v = p.get("verdict")
        if v == "newly_blocked":
            blocked.append(p)
        elif v == "inconclusive" and str(p.get("old_status", "")).startswith("computed:reached"):
            lost.append(p)
        elif v == "preserved":
            preserved += 1
        elif v == "inconclusive":
            inconclusive_other += 1
        else:
            other += 1

    summary = {
        "removed": len(removed),
        "pairs_tested": len(diff["pairs"]),
        "blocked": len(blocked),
        "lost_path": len(lost),
        "preserved": preserved,
        "inconclusive_other": inconclusive_other,
        "other": other,                          # exhaustive: the buckets now reconcile with pairs_tested
    }
    note = "No device matched the scenario — nothing was removed." if not removed else ""
    return {"scenario": scenario, "removed_hosts": removed, "blocked_flows": blocked,
            "lost_flows": lost, "summary": summary, "note": note}


def run_scenarios(snap: Dict[str, Any], scenarios: List[dict], limit: int = 24, max_pairs: int = 400) -> List[dict]:
    """Run a catalog of failure scenarios (each {name?, failures:[…]}) over one snapshot."""
    out = []
    for sc in scenarios or []:
        res = run_scenario(snap, sc, pairs=None, limit=limit, max_pairs=max_pairs)
        res["name"] = (sc or {}).get("name", "")
        out.append(res)
    return out
