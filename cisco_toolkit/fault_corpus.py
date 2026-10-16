"""Fault-injected calibration corpus — labeled readiness rows with ground truth by construction (Move 2).

The calibration nerve (:mod:`cisco_toolkit.calibration`) needs rows joining a PREDICTED pre-cutover
readiness ({READY/CAUTION/NOT_READY}) to an ACTUAL outcome ({clean/incident}). At N≈0 real cutovers the
strongest *honest* source is **fault injection**: start from a clean, all-pass scenario, inject ONE known
network fault, and the ground-truth outcome is known by construction (a clean scenario should come up
clean; a scenario with a real fault — a single-homed uplink, a sole gateway, a Critical-health switch — is
an incident-risk). We then ask the engine's own :func:`cisco_toolkit.analyze.compute_migration_readiness`
what it PREDICTS, and record the pair. This MEASURES whether the readiness scorer actually discriminates
good network states from bad ones — the deterministic strength — without waiting for real engagements and
without fabricating any outcome.

Every row is tagged ``source_class = "fault-injected"``: a surrogate. Per the D11 real-only gate
(:func:`cisco_toolkit.calibration.propose_adjustment`, `docs/quality/README.md`) these rows appear in the
DESCRIPTIVE calibration gap (so you can see the separation) but can NEVER unlock a ScoringConfig tuning
move — only genuine post-cutover outcomes may tune the engine.

Pure, offline, no egress. ``compute_migration_readiness`` reads only ``dep_map`` / ``health_scores`` /
``cross_layer`` / ``protocol_health`` (its ``all_interfaces`` / ``l3_forwarding`` params are unused), so a
minimal in-memory scenario is a faithful, controlled exercise of the real verdict logic.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List


def clean_scenario() -> Dict[str, Any]:
    """A minimal, internally-consistent, all-pass scenario for one switch — the engine scores it READY."""
    return {
        "all_interfaces": {},                                   # unused by readiness; present for signature
        "l3_forwarding": [],                                    # unused by readiness
        "move_groups": [{"switches": ["sw1"], "endpoints": 10}],
        "health_scores": [{"switch": "sw1", "band": "Good"}],
        "physical_health": [{"switch": "sw1"}],                 # baseline captured -> audit check passes
        "cross_layer": [],
        "protocol_health": [],
        "dep_map": {"single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
                    "orphan": [], "access_by_vlan": {}, "model": {"hosts": ["sw1"]}},
    }


def _set_band(s: Dict[str, Any], host: str, band: str) -> None:
    for r in s["health_scores"]:
        if r["switch"] == host:
            r["band"] = band


# Each fault is a real, named network problem an assessment must NOT wave through. The mutation triggers
# exactly one readiness check; the ground-truth outcome of shipping it is an incident.
FAULTS: Dict[str, Callable[[Dict[str, Any]], None]] = {
    "sole-gateway (SPOF)":        lambda s: s["dep_map"].__setitem__("sole_gw", {"vlan10": "sw1"}),
    "single-homed uplink":        lambda s: s["dep_map"].__setitem__("single_fiber", [("sw1", "Gi1/0/1")]),
    "critical device health":     lambda s: _set_band(s, "sw1", "Critical"),
    "cross-layer Critical":       lambda s: s.__setitem__("cross_layer",
                                                          [{"severity": "Critical", "hosts": ["sw1"]}]),
    "err-disabled port":          lambda s: s["dep_map"].__setitem__("errdis", [("sw1", "Gi1/0/2")]),
    "half-duplex uplink":         lambda s: s["dep_map"].__setitem__("halfdup_up", [("sw1", "Gi1/0/3")]),
}

_ORDER = {"NOT READY": 2, "CAUTION": 1, "READY": 0}


def readiness_of(scenario: Dict[str, Any]) -> str:
    """The engine's predicted readiness for a scenario — the WORST move-group verdict (NOT READY >
    CAUTION > READY). Calls the real :func:`compute_migration_readiness` (imported lazily so the module
    is importable without the engine for schema-only uses)."""
    from cisco_toolkit.analyze import compute_migration_readiness
    groups = compute_migration_readiness(
        scenario["all_interfaces"], scenario["move_groups"], scenario["health_scores"],
        scenario["physical_health"], scenario["l3_forwarding"], scenario["cross_layer"],
        scenario["protocol_health"], scenario["dep_map"])
    if not groups:
        return "READY"
    return max((g["readiness"] for g in groups), key=lambda r: _ORDER.get(r, 0))


def corpus_rows(commit: str = "") -> List[Dict[str, Any]]:
    """The labeled fault-injected calibration corpus: one clean row (ground truth clean) + one per fault
    (ground truth incident). ``predicted`` is what the engine says; ``actual`` is the constructed truth;
    every row is tagged ``source_class='fault-injected'`` (surrogate — never tunes the scorer)."""
    rows: List[Dict[str, Any]] = [{
        "predicted": readiness_of(clean_scenario()), "actual": "clean",
        "source_class": "fault-injected", "engagement": "synthetic", "unit": "clean-baseline",
        "commit": commit, "notes": "no fault injected — should be READY"}]
    for name, mutate in FAULTS.items():
        s = clean_scenario()
        mutate(s)
        rows.append({
            "predicted": readiness_of(s), "actual": "incident",
            "source_class": "fault-injected", "engagement": "synthetic", "unit": f"fault:{name}",
            "commit": commit, "notes": f"injected {name} — engine must not rate this READY"})
    return rows


def main(argv: Any = None) -> int:
    """CLI. ``--report`` prints the corpus + the engine's discrimination (does it rate every fault
    non-READY and the clean baseline READY?). ``--emit`` prints the rows as JSONL for appending to the
    calibration store (they are tagged fault-injected, so the D11 gate keeps them out of tuning)."""
    import json
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rows = corpus_rows()
    if "--emit" in argv:
        for r in rows:
            print(json.dumps({k: r[k] for k in ("predicted", "actual", "source_class",
                                                "engagement", "unit", "commit", "notes")},
                             ensure_ascii=True))
        return 0
    clean = rows[0]
    faults = rows[1:]
    flagged = sum(1 for r in faults if r["predicted"] != "READY")
    print(f"fault-injected calibration corpus — {len(rows)} rows (all source_class=fault-injected)")
    print(f"  clean baseline -> predicted {clean['predicted']}  (want READY)")
    for r in faults:
        mark = "flagged" if r["predicted"] != "READY" else "MISSED (rated READY!)"
        print(f"  {r['unit']:<28} -> {r['predicted']:<10} [{mark}]")
    print(f"  engine flagged {flagged}/{len(faults)} injected faults as non-READY; "
          f"clean baseline is {'READY' if clean['predicted'] == 'READY' else 'NOT READY'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
