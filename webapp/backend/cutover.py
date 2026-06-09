"""Synthesize a gated **cutover plan** (run-of-show) from a raw engine snapshot.

This is a *read-only projection*, in the same spirit as ``summary.py`` and ``graph.py`` — it never
re-runs analysis and never touches ``cisco_toolkit``. The engine already computes the raw migration
model (``move_groups``, ``wave_sequencing``, ``migration_readiness`` with per-check pass/warn/fail
tagged by PPDIOO phase, ``validation_plan.by_wave``, ``remediation_plan.by_device``,
``failure_impact``, ``cross_layer``). AssessHub otherwise renders that model as flat tables; this
module adds the judgment layer a migration engineer applies by hand:

* a per-wave **Go / Conditional-Go / No-Go gate**, derived from the engine's own readiness checks plus
  any Critical cross-layer correlation touching the wave;
* **pilot-first sequencing** — the safe make-before-break waves are scheduled before the risky
  NOT-READY ones, so the cutover method is proven on a zero-outage wave first;
* a first-order **maintenance-window estimate** for the hard-cutover (single-homed) switches; and
* a PPDIOO-phased **run-of-show** per wave that wires in that wave's pre-cutover remediation and its
  post-cutover validation commands.

Everything degrades gracefully: a snapshot missing any of these sections still yields a coherent
(smaller) plan rather than an error.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

_SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"]
_SEV_RANK = {s: i for i, s in enumerate(_SEVERITY_ORDER)}

# Gate vocabulary, worst -> best. The fleet verdict is the worst wave gate.
GATE_GO = "GO"
GATE_COND = "CONDITIONAL GO"
GATE_NOGO = "NO-GO"
_GATE_RANK = {GATE_GO: 0, GATE_COND: 1, GATE_NOGO: 2}


def _rows(snap: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [r for r in (snap.get(key) or []) if isinstance(r, dict)]


def _by_group(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["group"]: r for r in rows if r.get("group")}


def _wave_switches(seq: Dict[str, Any], readiness: Optional[Dict[str, Any]]) -> List[str]:
    """All switches in a wave — union of the sequencing buckets, backfilled from readiness."""
    sw = set(seq.get("make_before_break") or []) | set(seq.get("hard_cutover") or [])
    if not sw and readiness:
        sw = set(readiness.get("switches") or [])
    return sorted(sw)


def _match_move_group(switches: Set[str], move_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``move_groups`` rows carry no name — match the one whose switch-set overlaps this wave most."""
    best: Dict[str, Any] = {}
    best_overlap = 0
    for mg in move_groups:
        overlap = len(switches & set(mg.get("switches") or []))
        if overlap > best_overlap:
            best, best_overlap = mg, overlap
    return best


def _keystone_hosts(snap: Dict[str, Any], top: int = 8) -> Set[str]:
    """The few hosts the fleet most depends on — engine keystones, else worst failure_impact."""
    eb = snap.get("executive_brief") or {}
    ks = eb.get("keystones")
    if isinstance(ks, list) and ks:
        return {k.get("host") for k in ks if isinstance(k, dict) and k.get("host")}
    fi = sorted(_rows(snap, "failure_impact"),
                key=lambda r: (_SEV_RANK.get(r.get("severity", ""), 99), -int(r.get("stranded", 0) or 0)))
    return {r.get("host") for r in fi[:top] if r.get("host")}


def _worst_blast_radius(switches: Set[str], failure_impact: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The single worst failure-impact row among this wave's switches (severity, then stranded)."""
    cands = [r for r in failure_impact if r.get("host") in switches]
    if not cands:
        return None
    worst = min(cands, key=lambda r: (_SEV_RANK.get(r.get("severity", ""), 99), -int(r.get("stranded", 0) or 0)))
    return {
        "host": worst.get("host", ""),
        "severity": worst.get("severity", ""),
        "stranded": int(worst.get("stranded", 0) or 0),
        "vlans_impacted": int(worst.get("vlans_impacted", 0) or 0),
        "detail": worst.get("detail", ""),
    }


def _critical_crosslayer(switches: Set[str], cross_layer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Critical cross-layer correlations whose blast touches this wave — these gate a wave to NO-GO."""
    out = []
    for cl in cross_layer:
        if cl.get("severity") != "Critical":
            continue
        if switches & set(cl.get("hosts") or []):
            out.append({
                "id": cl.get("id", ""),
                "title": cl.get("title", ""),
                "layers": cl.get("layers", ""),
                "recommendation": cl.get("recommendation", ""),
            })
    return out


def _window_minutes(n_hard_switches: int, hard_endpoints: int) -> int:
    """First-order maintenance-window estimate for the single-homed (hard-cutover) switches.

    Make-before-break switches are zero-outage and excluded. The model is deliberately simple and
    conservative — a planning anchor to refine, not a commitment: mobilisation + per-switch cut +
    per-endpoint re-home/settle.
    """
    if n_hard_switches <= 0:
        return 0
    return 15 + 8 * n_hard_switches + hard_endpoints


def _gate(n_fail: int, n_warn: int, n_crit_cl: int, n_high_remediation: int) -> str:
    if n_fail > 0 or n_crit_cl > 0:
        return GATE_NOGO
    if n_warn > 0 or n_high_remediation > 0:
        return GATE_COND
    return GATE_GO


def _blockers(readiness: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The readiness checks that are not passing — fails first, then warns — with their PPDIOO phase."""
    if not readiness:
        return []
    checks = [c for c in (readiness.get("checks") or []) if isinstance(c, dict)]
    flagged = [c for c in checks if c.get("status") in ("fail", "warn")]
    flagged.sort(key=lambda c: 0 if c.get("status") == "fail" else 1)
    return [{
        "check": c.get("check", ""),
        "status": c.get("status", ""),
        "note": c.get("note", ""),
        "phase": c.get("phase", ""),
    } for c in flagged]


def _wave_remediation(switches: Set[str], rem_by_device: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pre-cutover fixes for this wave's devices, worst severity first."""
    out = []
    for dev, items in rem_by_device.items():
        if dev not in switches:
            continue
        for it in (items or []):
            if isinstance(it, dict):
                out.append({
                    "device": dev,
                    "title": it.get("title", ""),
                    "category": it.get("category", ""),
                    "severity": it.get("severity", ""),
                    "why": it.get("why", ""),
                })
    out.sort(key=lambda r: _SEV_RANK.get(r.get("severity", ""), 99))
    return out


def _wave_validation(group: str, val_by_wave: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post-cutover validation checks for this wave (engine's validation_plan.by_wave)."""
    out = []
    for it in (val_by_wave.get(group) or []):
        if isinstance(it, dict):
            out.append({
                "category": it.get("category", ""),
                "severity": it.get("severity", ""),
                "check": it.get("check", ""),
                "command": it.get("command", ""),
                "expect": it.get("expect", ""),
            })
    out.sort(key=lambda r: _SEV_RANK.get(r.get("severity", ""), 99))
    return out


def _run_of_show(*, mbb: List[str], hard: List[str], hard_ep: int, window: int,
                 n_val: int, n_rem: int, blockers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A PPDIOO-phased sequence of steps for this wave — the operational run-of-show."""
    n_baseline_gates = sum(1 for b in blockers if b.get("status") == "fail")
    steps: List[Dict[str, Any]] = [{
        "phase": "Baseline capture",
        "action": f"Capture the pre-cutover state for all {len(mbb) + len(hard)} switch(es) "
                  f"and record the known-good output for the {n_val} validation check(s).",
    }]
    if n_rem or n_baseline_gates:
        steps.append({
            "phase": "Remediation (gate)",
            "action": (f"Clear the {n_baseline_gates} failing readiness check(s) and apply "
                       f"{n_rem} pre-cutover fix(es) — redundant uplinks, FHRP, and config hygiene — "
                       "BEFORE scheduling the window. This wave does not pass the gate until they are resolved."),
        })
    if mbb:
        steps.append({
            "phase": "Cutover · make-before-break",
            "action": (f"Stage the parallel target path and migrate the {len(mbb)} dual-homed switch(es) "
                       f"({', '.join(mbb[:6])}{'…' if len(mbb) > 6 else ''}) with no outage window."),
        })
    if hard:
        steps.append({
            "phase": "Cutover · hard cutover",
            "action": (f"In the maintenance window (~{_fmt_minutes(window)}), cut the {len(hard)} single-homed "
                       f"switch(es) affecting {hard_ep} endpoint(s). Single-homed = a hard partition during the cut."),
        })
    steps.append({
        "phase": "Validation",
        "action": (f"Run the {n_val} post-cutover check(s) and compare each result to the captured "
                   "'expect' baseline. Any deviation is a regression to investigate before sign-off."),
    })
    steps.append({
        "phase": "Rollback gate",
        "action": ("If a High-severity check regresses or endpoints fail to re-home, fall back to the "
                   "staged pre-cutover path and re-baseline before re-attempting."),
    })
    return steps


def _fmt_minutes(m: int) -> str:
    if m <= 0:
        return "no outage"
    if m < 60:
        return f"{m} min"
    h, mm = divmod(m, 60)
    return f"{h}h{mm:02d}m" if mm else f"{h}h"


def build_plan(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Project a gated, pilot-first cutover plan from a snapshot. Pure read-only synthesis."""
    seq_rows = _rows(snap, "wave_sequencing")
    readiness_by_group = _by_group(_rows(snap, "migration_readiness"))
    move_groups = _rows(snap, "move_groups")
    failure_impact = _rows(snap, "failure_impact")
    cross_layer = _rows(snap, "cross_layer")
    rem_by_device = (snap.get("remediation_plan") or {}).get("by_device") or {}
    val_by_wave = (snap.get("validation_plan") or {}).get("by_wave") or {}
    keystones = _keystone_hosts(snap)

    waves: List[Dict[str, Any]] = []
    for seq in seq_rows:
        group = seq.get("group", "")
        readiness = readiness_by_group.get(group)
        mbb = list(seq.get("make_before_break") or [])
        hard = list(seq.get("hard_cutover") or [])
        switches = set(_wave_switches(seq, readiness))
        mg = _match_move_group(switches, move_groups)

        hard_ep = int(seq.get("hard_cutover_endpoints", 0) or 0)
        endpoints = int(mg.get("endpoints", 0) or 0) or hard_ep
        n_fail = int((readiness or {}).get("n_fail", 0) or 0)
        n_warn = int((readiness or {}).get("n_warn", 0) or 0)

        blockers = _blockers(readiness)
        crit_cl = _critical_crosslayer(switches, cross_layer)
        remediation = _wave_remediation(switches, rem_by_device)
        n_high_rem = sum(1 for r in remediation if r.get("severity") in ("Critical", "High"))
        validation = _wave_validation(group, val_by_wave)
        window = _window_minutes(len(hard), hard_ep)
        gate = _gate(n_fail, n_warn, len(crit_cl), n_high_rem)
        strategy = "mixed" if (mbb and hard) else ("hard-cutover" if hard else "make-before-break")

        waves.append({
            "group": group,
            "readiness": (readiness or {}).get("readiness", ""),
            "gate": gate,
            "strategy": strategy,
            "n_switches": len(switches),
            "switches": sorted(switches),
            "make_before_break": sorted(mbb),
            "hard_cutover": sorted(hard),
            "endpoints": endpoints,
            "hard_cutover_endpoints": hard_ep,
            "est_window_minutes": window,
            "est_window_label": _fmt_minutes(window),
            "sequence_note": seq.get("sequence", ""),
            "gateways": list(mg.get("gateways") or []),
            "spanning_vlans": list(mg.get("spanning_vlans") or []),
            "blast_radius": _worst_blast_radius(switches, failure_impact),
            "keystones": sorted(switches & keystones),
            "n_fail": n_fail,
            "n_warn": n_warn,
            "blockers": blockers,
            "critical_crosslayer": crit_cl,
            "remediation": remediation,
            "validation": validation,
            "run_of_show": _run_of_show(mbb=sorted(mbb), hard=sorted(hard), hard_ep=hard_ep,
                                        window=window, n_val=len(validation), n_rem=len(remediation),
                                        blockers=blockers),
        })

    # Pilot-first sequencing: prove the method on the safest (GO) zero-outage waves first, leave the
    # NO-GO hard-cutover waves for last (after remediation). Tie-break on smaller blast radius first.
    waves.sort(key=lambda w: (_GATE_RANK[w["gate"]], w["hard_cutover_endpoints"], w["endpoints"]))
    for i, w in enumerate(waves, start=1):
        w["order"] = i

    # Fleet roll-up.
    fleet_gate = GATE_GO
    for w in waves:
        if _GATE_RANK[w["gate"]] > _GATE_RANK[fleet_gate]:
            fleet_gate = w["gate"]

    total_hard_ep = sum(w["hard_cutover_endpoints"] for w in waves)
    total_window = sum(w["est_window_minutes"] for w in waves)
    n_mbb = sum(len(w["make_before_break"]) for w in waves)
    n_hard = sum(len(w["hard_cutover"]) for w in waves)

    summary = {
        "verdict": fleet_gate,
        "n_waves": len(waves),
        "n_devices": n_mbb + n_hard,
        "n_endpoints": sum(w["endpoints"] for w in waves),
        "n_make_before_break": n_mbb,
        "n_hard_cutover": n_hard,
        "hard_cutover_endpoints": total_hard_ep,
        "est_window_minutes": total_window,
        "est_window_label": _fmt_minutes(total_window),
        "gates": {g: sum(1 for w in waves if w["gate"] == g) for g in (GATE_GO, GATE_COND, GATE_NOGO)},
        "statement": _fleet_statement(fleet_gate, waves, n_mbb, n_hard, total_window),
    }
    return {"summary": summary, "waves": waves}


def _fleet_statement(verdict: str, waves: List[Dict[str, Any]], n_mbb: int, n_hard: int,
                     total_window: int) -> str:
    n_nogo = sum(1 for w in waves if w["gate"] == GATE_NOGO)
    parts = [f"Cutover posture: {verdict}."]
    if not waves:
        return "No migration waves were derived from this snapshot."
    if n_nogo:
        parts.append(f"{n_nogo} of {len(waves)} wave(s) are NO-GO until their gating checks are cleared.")
    parts.append(f"{n_mbb} switch(es) migrate make-before-break (zero outage); "
                 f"{n_hard} need a maintenance window (~{_fmt_minutes(total_window)} total).")
    parts.append("Waves are ordered pilot-first: the safest zero-outage wave proves the method before "
                 "the higher-risk hard-cutover waves run.")
    return " ".join(parts)
