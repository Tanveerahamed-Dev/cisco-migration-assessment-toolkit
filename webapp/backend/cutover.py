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

Methodology (grounded in standard network-migration / cutover practice, PPDIOO Implement + Operate):
  * **make-before-break** (dual-homed) is a *soft* cutover — the target path is established before the
    legacy one is removed, so it is zero-downtime; **hard cutover** (single-homed) is *break-before-make*
    — the path is broken first, a partition during the cut, so it needs a maintenance window.
  * Each hard-cutover wave should be **rehearsed end-to-end (dry run)** before the live window — a
    rehearsal validates the window and rollback and surfaces hidden dependencies that planning misses.
  * Capture **config + live-state backups** (running-config, routing/MAC/ARP tables) immediately before
    each cut for rollback, in addition to the validation 'expect' baselines.
  * Window figures are **first-order anchors** — there is no universal per-device standard; calibrate
    them against the dry-run's measured timings before committing to a change window.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from . import summary

# Single source of truth for the severity vocabulary — reuse summary's rather than redeclaring it, so a
# new/renamed band can't be ranked here (unknown -> 99 = sorted last) while the cockpit ranks it right.
_SEV_RANK = {s: i for i, s in enumerate(summary.SEVERITY_ORDER)}


def _int(v: Any, default: int = 0) -> int:
    """Best-effort int from a snapshot value — robust to None/str/garbage in an uploaded snapshot, incl. the
    bare JSON Infinity/NaN json.loads accepts (int(inf) raises OverflowError, which the plain guard missed)."""
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def _int_or_none(v: Any) -> Optional[int]:
    """``_int`` that preserves ABSENT / unparseable as ``None`` instead of collapsing it onto 0.

    Needed wherever a genuine 0 is a real published count and a fallback must fire ONLY when the field
    is missing: ``_int(x) or fallback`` silently replaces a reported 0 with the fallback (this project's
    ``or``-masks-zero class — ``storage.add_snapshot`` documents the same guard as ``is not None`` for the
    canonical n_devices)."""
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_dict(v: Any) -> Dict[str, Any]:
    """Coerce a snapshot section/sub-section to a dict. A truthy NON-dict (an int/str/list in a malformed or
    hostile upload) would otherwise survive `... or {}` and 500 the very next `.get`/`.items()` -- a stored
    DoS on /cutover, which reads these straight from the snapshot. Returning {} degrades gracefully."""
    return v if isinstance(v, dict) else {}


def _hkey(v: Any) -> Any:
    """A HASHABLE form of a snapshot LEAF used as a dict-lookup key (see summary._hkey, the twin).

    _as_dict guards a section's SHAPE; this guards the leaf inside a row. `_SEV_RANK.get(severity)`
    hashes its argument, so a dict/list `severity` raises `TypeError: unhashable type` -- an unhandled
    500. Hashable values pass through UNCHANGED (real labels keep their exact rank and sort order);
    only the unhashable poison is stringified, which matches no rank and degrades to 99 (unknown)."""
    try:
        hash(v)
        return v
    except TypeError:
        return str(v)


def _as_hosts(v: Any) -> Set[str]:
    """Coerce a snapshot 'hosts'/'switches' field to a set of host strings.

    Robust to a bare string (treated as a single host, NOT its characters — ``set('sw1')`` would
    otherwise become ``{'s','w','1'}`` and silently drop the match, e.g. dropping a Critical
    cross-layer hit so the wave is no longer gated NO-GO) and to non-iterables in a malformed snapshot.
    """
    if isinstance(v, str):
        return {v} if v else set()
    if isinstance(v, (list, tuple, set)):
        return {str(x) for x in v if x}
    return set()

# Gate vocabulary, worst -> best. The fleet verdict is the worst wave gate.
GATE_GO = "GO"
GATE_COND = "CONDITIONAL GO"
GATE_NOGO = "NO-GO"
_GATE_RANK = {GATE_GO: 0, GATE_COND: 1, GATE_NOGO: 2}

#: FLEET-level only, never a wave gate (so it is deliberately absent from _GATE_RANK, which ranks
#: waves): there were no waves to gate, so no posture was measured. Coverage honesty — "not observed"
#: must not read as "healthy" (CLAUDE.md guardrail 3), the same distinction archreview draws with
#: `not-assessable` and device_dossiers with the `Unassessed` band. Consumers that colour a gate token
#: degrade to NEUTRAL on an unknown one by construction (`cutover_docx._GATE_INK.get(v, _NAVY)`, and
#: the SPA's `gateColor` -> `var(--gate-NOTASSESSED, var(--text-faint))`), which is the right rendering.
GATE_NOT_ASSESSED = "NOT ASSESSED"


def _rows(snap: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    # summary._as_list, not `or []`: a section that is a truthy non-list (an int in a malformed upload)
    # survives `or []` and 500s `for r in ...` -> stored DoS on /cutover.
    return [r for r in summary._as_list(snap.get(key)) if isinstance(r, dict)]


def _by_group(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # str(...) the group: an UNHASHABLE group value (a list/dict in a malformed upload) is truthy, so it
    # passes the filter and then 500s as a dict key -> stored DoS. Coercing keeps well-formed keys identical.
    return {str(r["group"]): r for r in rows if r.get("group")}


def _wave_switches(seq: Dict[str, Any], readiness: Optional[Dict[str, Any]]) -> List[str]:
    """All switches in a wave — union of the sequencing buckets, backfilled from readiness."""
    sw = _as_hosts(seq.get("make_before_break")) | _as_hosts(seq.get("hard_cutover"))
    if not sw and readiness:
        sw = _as_hosts(readiness.get("switches"))
    return sorted(sw)


def _match_move_group(switches: Set[str], move_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``move_groups`` rows carry no name — match the one whose switch-set overlaps this wave most."""
    best: Dict[str, Any] = {}
    best_overlap = 0
    for mg in move_groups:
        overlap = len(switches & _as_hosts(mg.get("switches")))
        if overlap > best_overlap:
            best, best_overlap = mg, overlap
    return best


def _keystone_hosts(snap: Dict[str, Any], top: int = 8) -> Set[str]:
    """The few hosts the fleet most depends on — reuse summary's keystone heuristic (don't re-derive),
    so the cockpit's keystone list and the plan's per-wave keystones can't drift apart."""
    out: Set[str] = set()
    for k in summary._keystones(snap, top):
        host = k.get("host") if isinstance(k, dict) else None
        if host:
            out.add(str(host))   # str(): an unhashable host (a list in a malformed upload) must not 500 set.add
    return out


def _worst_blast_radius(switches: Set[str], failure_impact: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The single worst failure-impact row among this wave's switches (severity, then stranded)."""
    # str(host): switches are stringified (via _as_hosts); an unhashable host (a list) would else 500 the
    # `in`-a-set membership test -> stored DoS. Coercing keeps well-formed string hosts matching as before.
    cands = [r for r in failure_impact if str(r.get("host")) in switches]
    if not cands:
        return None
    worst = min(cands, key=lambda r: (_SEV_RANK.get(r.get("severity", ""), 99), -_int(r.get("stranded"))))
    return {
        "host": worst.get("host", ""),
        "severity": worst.get("severity", ""),
        "stranded": _int(worst.get("stranded")),
        "vlans_impacted": _int(worst.get("vlans_impacted")),
        "detail": worst.get("detail", ""),
    }


def _critical_crosslayer(switches: Set[str], cross_layer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Critical cross-layer correlations whose blast touches this wave — these gate a wave to NO-GO."""
    out = []
    for cl in cross_layer:
        if cl.get("severity") != "Critical":
            continue
        if switches & _as_hosts(cl.get("hosts")):
            out.append({
                "id": cl.get("id", ""),
                "title": cl.get("title", ""),
                "layers": cl.get("layers", ""),
                "recommendation": cl.get("recommendation", ""),
            })
    return out


def _window_minutes(n_hard_switches: int, hard_endpoints: int) -> int:
    """First-order maintenance-window estimate for the single-homed (hard-cutover) switches.

    Make-before-break switches are zero-outage and excluded. There is no universal per-device standard
    (cutover duration depends heavily on platform, scale, and method) — so this is a transparent,
    additive planning anchor to *calibrate against a dry run*, not a commitment. The model times each
    block that a windowed cut actually contains: mobilisation/pre-checks + per-switch cut & verify +
    per-endpoint re-home/settle + a post-cut validation & rollback-decision buffer.
    """
    if n_hard_switches <= 0:
        return 0
    mobilisation = 15
    per_switch_cut_verify = 10 * n_hard_switches
    per_endpoint_settle = hard_endpoints              # ~1 min to re-home/verify each stranded endpoint
    validation_rollback_buffer = 20
    return mobilisation + per_switch_cut_verify + per_endpoint_settle + validation_rollback_buffer


def _gate(n_fail: int, n_warn: int, n_crit_cl: int, n_high_remediation: int, n_blind: int = 0) -> str:
    if n_fail > 0 or n_crit_cl > 0:
        return GATE_NOGO
    # audit-5 #15: a device the collection never reached (band 'Insufficient Data') cannot be certified ready, so
    # a wave containing one is never a confident GO -- it is CONDITIONAL pending collection (coverage-honest).
    if n_warn > 0 or n_high_remediation > 0 or n_blind > 0:
        return GATE_COND
    return GATE_GO


def _blind_hosts(snap: Dict[str, Any]) -> set:
    """Hosts the collection never reached -- health band 'Insufficient Data' / data_quality 0. A cutover wave
    cannot be confidently gated for a device that was never assessed; the plan surfaces them rather than folding
    them in as fully-plannable hard-cutover waves with the same verdict as an assessed wave (audit-5 #15)."""
    out: set = set()
    for r in _rows(snap, "health_scores"):
        band = str(r.get("band", "")).strip().lower()
        dq = r.get("data_quality")
        if band.startswith("insufficient") or (isinstance(dq, (int, float)) and not isinstance(dq, bool) and dq <= 0):
            h = r.get("switch") or r.get("host")
            if h:
                out.add(str(h))   # str(): an unhashable host (a list in a malformed upload) must not 500 set.add
    return out


def _blockers(readiness: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The readiness checks that are not passing — fails first, then warns — with their PPDIOO phase."""
    if not readiness:
        return []
    # summary._as_list, not `or []`: a truthy non-list `checks` (an int in a malformed upload) 500s `for c in ...`.
    checks = [c for c in summary._as_list(readiness.get("checks")) if isinstance(c, dict)]
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
    # isinstance-dict guard: `rem_by_device` (remediation_plan.by_device) that is a truthy non-dict in a
    # malformed upload would 500 `.items()` here -> stored DoS. build_plan already coerces, this is defence in depth.
    if not isinstance(rem_by_device, dict):
        return out
    for dev, items in rem_by_device.items():
        if dev not in switches:
            continue
        # isinstance-guard, not `or []`: a per-device value that is a TRUTHY non-list (an int/str in a
        # malformed upload) survives `or []` and 500s this iteration -> stored DoS on /cutover.
        for it in summary._as_list(items):
            if isinstance(it, dict):
                out.append({
                    "device": dev,
                    "title": it.get("title", ""),
                    "category": it.get("category", ""),
                    "severity": it.get("severity", ""),
                    "why": it.get("why", ""),
                })
    # _hkey: an unhashable dict/list `severity` leaf makes _SEV_RANK.get() raise
    # `TypeError: unhashable type` -- an unhandled 500 on /cutover and /executions, and the
    # snapshot is STORED so it re-crashes on every later read (same class as summary._keystones).
    out.sort(key=lambda r: _SEV_RANK.get(_hkey(r.get("severity", "")), 99))
    return out


def _wave_validation(group: str, val_by_wave: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post-cutover validation checks for this wave (engine's validation_plan.by_wave)."""
    out = []
    # isinstance-dict guard: `val_by_wave` (validation_plan.by_wave) that is a truthy non-dict in a malformed
    # upload would 500 `.get()` here -> stored DoS. build_plan already coerces, this is defence in depth.
    if not isinstance(val_by_wave, dict):
        return out
    # isinstance-guard, not `or []`: a per-wave value that is a TRUTHY non-list survives `or []` and 500s
    # this iteration -> stored DoS on /cutover.
    for it in summary._as_list(val_by_wave.get(group)):
        if isinstance(it, dict):
            out.append({
                "category": it.get("category", ""),
                "severity": it.get("severity", ""),
                "check": it.get("check", ""),
                "command": it.get("command", ""),
                "expect": it.get("expect", ""),
            })
    # _hkey: an unhashable dict/list `severity` leaf makes _SEV_RANK.get() raise
    # `TypeError: unhashable type` -- an unhandled 500 on /cutover and /executions, and the
    # snapshot is STORED so it re-crashes on every later read (same class as summary._keystones).
    out.sort(key=lambda r: _SEV_RANK.get(_hkey(r.get("severity", "")), 99))
    return out


def _run_of_show(*, mbb: List[str], hard: List[str], hard_ep: int, window: int,
                 n_val: int, n_rem: int, blockers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A PPDIOO-phased sequence of steps for this wave — the operational run-of-show."""
    n_baseline_gates = sum(1 for b in blockers if b.get("status") == "fail")
    steps: List[Dict[str, Any]] = [{
        "phase": "Baseline capture",
        "action": f"Back up config + live state (running-config, routing/MAC/ARP tables) for all "
                  f"{len(mbb) + len(hard)} switch(es) for rollback, and record the known-good output for "
                  f"the {n_val} validation check(s) as the post-cut 'expect' baseline.",
    }]
    if n_rem or n_baseline_gates:
        steps.append({
            "phase": "Remediation (gate)",
            "action": (f"Clear the {n_baseline_gates} failing readiness check(s) and apply "
                       f"{n_rem} pre-cutover fix(es) — redundant uplinks, FHRP, and config hygiene — "
                       "BEFORE scheduling the window. This wave does not pass the gate until they are resolved."),
        })
    if hard:
        steps.append({
            "phase": "Rehearsal (dry run)",
            "action": (f"Rehearse the cut of the {len(hard)} single-homed switch(es) and the rollback "
                       "end-to-end in a lab or staging — time every block to calibrate the window, and "
                       "surface hidden dependencies before the live change."),
        })
    if mbb:
        steps.append({
            "phase": "Cutover · make-before-break",
            "action": (f"Stage the parallel target path and migrate the {len(mbb)} dual-homed switch(es) "
                       f"({', '.join(mbb[:6])}{'…' if len(mbb) > 6 else ''}) with no outage window."),
            # AS convention: the impact rides the step that causes it (additive; writers/UI may render)
            "impact": "No outage — the legacy leg stays live until the new path is proven.",
        })
    if hard:
        steps.append({
            "phase": "Cutover · hard cutover",
            "action": (f"In the maintenance window (~{_fmt_minutes(window)}), cut the {len(hard)} single-homed "
                       f"switch(es) affecting {hard_ep} endpoint(s). Single-homed = a hard partition during the cut."),
            "impact": (f"OUTAGE — {hard_ep} endpoint(s) on {len(hard)} switch(es) are hard-down from "
                       f"the cable pull until validation passes (window ~{_fmt_minutes(window)})."),
        })
    steps.append({
        "phase": "Validation",
        "action": (f"Run the {n_val} post-cutover check(s) and compare each result to the captured "
                   "'expect' baseline. Any deviation is a regression to investigate before sign-off."),
    })
    steps.append({
        "phase": "Rollback gate",
        "action": ("If a High-severity check regresses or endpoints fail to re-home within the window, "
                   "execute the back-out: for a hardware swap re-cable to the legacy device; for a config "
                   "change restore the captured running-config. Re-baseline before re-attempting."),
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
    # _as_dict at every level, not `... or {}`: a truthy non-dict remediation_plan/validation_plan (or a
    # non-dict by_device/by_wave) survives `or {}` and 500s the next `.get`/`.items()` -> stored DoS.
    rem_by_device = _as_dict(_as_dict(snap.get("remediation_plan")).get("by_device"))
    val_by_wave = _as_dict(_as_dict(snap.get("validation_plan")).get("by_wave"))
    keystones = _keystone_hosts(snap)
    blind_hosts = _blind_hosts(snap)

    waves: List[Dict[str, Any]] = []
    for seq in seq_rows:
        # str(...) the group: an unhashable group (a list in a malformed upload) would 500 the readiness /
        # validation dict lookups keyed on it. sorted(_as_hosts(...)) the buckets, not list(...): a
        # non-iterable 500s list(), and a list of ints 500s the run-of-show ', '.join -- _as_hosts str-coerces.
        group = str(seq.get("group") or "")
        readiness = readiness_by_group.get(group)
        mbb = sorted(_as_hosts(seq.get("make_before_break")))
        hard = sorted(_as_hosts(seq.get("hard_cutover")))
        switches = set(_wave_switches(seq, readiness))
        wblind = sorted(switches & blind_hosts)
        mg = _match_move_group(switches, move_groups)

        hard_ep = _int(seq.get("hard_cutover_endpoints"))
        # PRESENCE, not truthiness: a move group that genuinely reports 0 endpoints is a real count, and
        # `_int(...) or hard_ep` silently adopted the hard-cutover figure instead. This value is an SSOT
        # headline (it feeds fleet_summary['n_endpoints']) AND the final tie-break of the pilot-first wave
        # ordering below, so a masked 0 both overstates the fleet and mis-ranks the run-of-show.
        mg_endpoints = _int_or_none(mg.get("endpoints"))
        endpoints = mg_endpoints if mg_endpoints is not None else hard_ep
        n_fail = _int((readiness or {}).get("n_fail"))
        n_warn = _int((readiness or {}).get("n_warn"))

        blockers = _blockers(readiness)
        crit_cl = _critical_crosslayer(switches, cross_layer)
        remediation = _wave_remediation(switches, rem_by_device)
        n_high_rem = sum(1 for r in remediation if r.get("severity") in ("Critical", "High"))
        validation = _wave_validation(group, val_by_wave)
        window = _window_minutes(len(hard), hard_ep)
        gate = _gate(n_fail, n_warn, len(crit_cl), n_high_rem, len(wblind))
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
            # summary._as_list, not list(...): a non-iterable gateways/spanning_vlans (an int in a malformed
            # move_group) 500s list(). _as_list preserves ints (VLAN ids are ints), unlike _as_hosts.
            "gateways": summary._as_list(mg.get("gateways")),
            "spanning_vlans": summary._as_list(mg.get("spanning_vlans")),
            "blast_radius": _worst_blast_radius(switches, failure_impact),
            "keystones": sorted(switches & keystones),
            "n_fail": n_fail,
            "n_warn": n_warn,
            "n_blind": len(wblind),
            "blind_switches": wblind,
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

    # Fleet roll-up = the worst wave gate. VACUOUS-TRUTH GUARD (the exact twin of
    # execution._derive_outcome's `not decisions` branch): over an EMPTY wave list the loop below
    # never executes, so the GATE_GO seed survived untouched and the plan published
    # `"verdict": "GO"` for a snapshot from which NOTHING was derived — cutover_docx then printed
    # "Cutover posture: GO" in green (_GATE_INK) on the title page, directly above its own body line
    # "No migration waves were derived from this snapshot", and the SPA drew the same GO badge. Every
    # other branch here requires positive evidence (a wave that was actually gated); this one
    # required none. Reproduced end to end through GET /api/snapshots/{id}/cutover on an uploaded
    # {"devices": {}}. The seed is now the honest token when there is nothing to roll up; with waves
    # present it is GATE_GO exactly as before, so no assessed fleet's verdict moves.
    fleet_gate = GATE_GO if waves else GATE_NOT_ASSESSED
    for w in waves:
        if _GATE_RANK[w["gate"]] > _GATE_RANK[fleet_gate]:
            fleet_gate = w["gate"]

    total_hard_ep = sum(w["hard_cutover_endpoints"] for w in waves)
    total_window = sum(w["est_window_minutes"] for w in waves)
    n_mbb = sum(len(w["make_before_break"]) for w in waves)
    n_hard = sum(len(w["hard_cutover"]) for w in waves)
    n_not_assessed = sum(_int(w.get("n_blind")) for w in waves)

    # NB: named fleet_summary, not `summary` -- a local named `summary` would shadow the module-level
    # `summary` import for the WHOLE function body, turning the `summary._as_list(...)` guards above into an
    # UnboundLocalError. (The output KEY stays "summary"; only the local binding is renamed.)
    fleet_summary = {
        "verdict": fleet_gate,
        "n_waves": len(waves),
        "n_devices": n_mbb + n_hard,
        "n_endpoints": sum(w["endpoints"] for w in waves),
        "n_make_before_break": n_mbb,
        "n_hard_cutover": n_hard,
        "n_not_assessed": n_not_assessed,
        "hard_cutover_endpoints": total_hard_ep,
        "est_window_minutes": total_window,
        "est_window_label": _fmt_minutes(total_window),
        "gates": {g: sum(1 for w in waves if w["gate"] == g) for g in (GATE_GO, GATE_COND, GATE_NOGO)},
        "statement": _fleet_statement(fleet_gate, waves, n_mbb, n_hard, total_window),
        "methodology": _METHODOLOGY,
    }
    return {"summary": fleet_summary, "waves": waves}


# Grounded in standard network-migration / cutover practice (PPDIOO Implement + Operate). Surfaced in the
# UI and the downloadable plan so the synthesis is defensible, not a black box.
_METHODOLOGY: List[str] = [
    "Make-before-break (dual-homed) is a soft, zero-downtime cutover; hard-cutover (single-homed) is "
    "break-before-make — a partition during the cut, so it needs a maintenance window.",
    "Each hard-cutover wave should be rehearsed end-to-end (dry run) before the live window — a rehearsal "
    "validates the window and rollback and surfaces hidden dependencies that planning misses.",
    "Capture config + live-state backups (running-config, routing/MAC/ARP) immediately before each cut "
    "for rollback, in addition to the validation 'expect' baselines.",
    "Window figures are first-order anchors — there is no universal per-device standard; calibrate them "
    "against the dry-run's measured timings before committing to a change window.",
]


def _fleet_statement(verdict: str, waves: List[Dict[str, Any]], n_mbb: int, n_hard: int,
                     total_window: int) -> str:
    n_nogo = sum(1 for w in waves if w["gate"] == GATE_NOGO)
    n_blind = sum(_int(w.get("n_blind")) for w in waves)
    parts = [f"Cutover posture: {verdict}."]
    if not waves:
        # Lead with the posture here too. The old wording named only the cause ("no waves"), so a
        # reader who saw the green GO headline above it read this line as a footnote to a passing
        # plan rather than as the reason the plan has no verdict at all.
        return (f"Cutover posture: {verdict} — no migration waves were derived from this snapshot, "
                f"so no cutover posture was assessed. This is an ABSENCE of assessment, not a "
                f"clean bill of health.")
    if n_blind:
        parts.append(f"{n_blind} device(s) were NOT assessed (collection incomplete) -- they cannot be certified "
                     f"ready, so their wave(s) are gated CONDITIONAL pending collection and this posture is a LOWER "
                     f"BOUND, not a clean bill of health.")
    if n_nogo:
        parts.append(f"{n_nogo} of {len(waves)} wave(s) are NO-GO until their gating checks are cleared.")
    parts.append(f"{n_mbb} switch(es) migrate make-before-break (zero outage); "
                 f"{n_hard} need a maintenance window (~{_fmt_minutes(total_window)} total).")
    parts.append("Waves are ordered pilot-first: the safest zero-outage wave proves the method before "
                 "the higher-risk hard-cutover waves run.")
    return " ".join(parts)
