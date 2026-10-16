"""PIR-outcome calibration — the *retrospective* half of the feedback nerve (Phase 1).

Phase 1 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``. The engine emits a **prediction**
before a cutover — a per-unit readiness verdict (``READY`` / ``CAUTION`` / ``NOT_READY``, the
``compute_migration_readiness`` statuses: ``fail`` -> NOT READY, ``warn`` -> CAUTION). The **PIR**
(post-implementation review / war-room) records what actually happened — the unit came up ``clean``
or hit an ``incident`` (fault / rollback). This module joins the two into a **calibration gap**:

- **false-confidence rate** = P(incident | predicted READY) — the dangerous miss (we said go, it broke).
- **false-alarm rate**      = P(clean   | predicted NOT_READY) — the over-caution (we blocked a fine unit).

and, from the gap's *direction*, whether the scorer is **too lenient** (tighten) or **too strict** (relax).

**The D11 gate is the whole point.** Calibration is **descriptive-only until N >= 5 labeled outcomes**;
below the floor :func:`propose_adjustment` **refuses to move any** :class:`~cisco_toolkit.analyze.ScoringConfig`
**parameter and says so** — two PIRs must never re-tune the engine (overfitting on a handful of
engagements). At N >= 5 it proposes ONE *small, reversible, human-gated* delta on a single conservative
lever and **still applies nothing** (``applied`` is always ``False``): every unattended action is
propose-only. A full per-finding weight refit is out of reach from per-unit pass/fail labels — stated as
a limitation, not silently overclaimed.

**Distinct from** :func:`cisco_toolkit.analyze.compute_calibration_report`, which is a *prospective,
within-snapshot* band-discrimination diagnostic (do this fleet's health bands separate at all?). This
module is *retrospective, cross-engagement* (did the readiness verdicts match reality?). One looks at the
scores; this looks at the outcomes.

Pure-stdlib; the derivation core (:func:`calibration_gap`, :func:`propose_adjustment`) does no I/O and
does not import the engine unless a proposal needs a live default — so it is unit-testable without a
snapshot or a repo. Coverage-honest: no outcomes -> "cannot run, descriptive-only" (absence is absence),
never a fabricated calibration.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

# The labeled-outcome store (one JSON object per line, append-only). Schema in docs/quality/README.md.
PIR_OUTCOMES_PATH = os.path.join("docs", "quality", "pir_outcomes.jsonl")

# D11: descriptive-only until this many labeled PIR outcomes exist; then small, reversible, human-gated.
DEFAULT_N_FLOOR = 5

# The default conservative lever a proposal nudges: caps["XL"] — the max deduction the cross-layer
# Critical findings (the SPOFs that actually cause cutover incidents) may contribute to a health score.
# Raising it makes the scorer more conservative (fewer READY); lowering it makes it less alarmist.
DEFAULT_LEVER = "caps.XL"

_MARGIN = 0.15   # a direction only fires when the two error rates differ by more than this

# Prediction aliases -> the canonical readiness label (mirrors the engine's fail/warn/pass statuses).
_PRED_ALIASES: Dict[str, set] = {
    "READY": {"ready", "go", "green", "pass", "passed", "ok", "healthy"},
    "NOT_READY": {"not_ready", "no_go", "nogo", "blocked", "block", "red", "fail", "failed"},
    "CAUTION": {"caution", "warn", "warning", "amber", "yellow", "conditional"},
}
# Actual PIR outcome aliases -> the canonical outcome.
_ACTUAL_ALIASES: Dict[str, set] = {
    "clean": {"clean", "success", "successful", "succeeded", "pass", "passed", "ok",
              "no_incident", "noincident", "green", "healthy"},
    "incident": {"incident", "fail", "failed", "failure", "rollback", "rolled_back",
                 "rolledback", "outage", "error", "red", "broke", "broken"},
}

# Provenance of a calibration row. **Only "REAL" (a genuine post-cutover PIR / war-room outcome) counts
# toward the D11 tuning floor.** Surrogate classes (fault-injected / public / synthetic / …) VALIDATE
# detectors and inform descriptive stats, but must NEVER unlock a ScoringConfig proposal: feeding public
# or synthetic calibration data must not re-tune the scorer (the no-fabrication law, applied to the
# calibration nerve itself). This matters the moment production data from many engagements starts to
# flow — each real cutover contributes exactly one REAL row; everything else stays descriptive-only.
_SOURCE_ALIASES: Dict[str, set] = {
    "REAL": {"real", "pir", "post_cutover", "postcutover", "production", "prod", "live", "war_room"},
    "fault-injected": {"fault_injected", "faultinjected", "injected", "batfish"},
    "retro-public": {"retro_public", "retropublic", "public", "public_lab", "kathara", "retro"},
    "compare-pair": {"compare_pair", "comparepair", "before_after", "beforeafter", "diff_pair"},
    "shadow-PIR": {"shadow_pir", "shadowpir", "shadow", "postmortem", "post_mortem"},
    "synthetic": {"synthetic", "synth", "authored", "fabricated"},
}


def _norm_source(val: Any) -> Optional[str]:
    """Canonical provenance for a calibration row, or None if unspecified. An UNRECOGNIZED tag is kept
    verbatim (visible, honest) but is never equal to ``'REAL'`` — so unknown provenance can never unlock
    tuning (fail-safe; coverage-honest: unknown provenance != a real outcome)."""
    if val is None:
        return None
    key = str(val).strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    for canon, al in _SOURCE_ALIASES.items():
        normed = {a.replace(" ", "_").replace("-", "_") for a in al} | {canon.lower().replace("-", "_")}
        if key in normed:
            return canon
    return str(val).strip()


def _norm(val: Any, aliases: Dict[str, set]) -> Optional[str]:
    """Coerce a free-text label to its canonical form (space/hyphen -> underscore), or None."""
    if val is None:
        return None
    key = str(val).strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    for canon, al in aliases.items():
        normed = {a.replace(" ", "_").replace("-", "_") for a in al} | {canon.lower()}
        if key in normed:
            return canon
    return None


def normalize_outcome(row: Any) -> Optional[Dict[str, Any]]:
    """One labeled outcome -> ``{'predicted', 'actual', ...}`` with canonical labels, or ``None`` if the
    row is unusable (missing/garbled predicted or actual). A skipped row is *not counted* — coverage-honest:
    a malformed label is dropped, never coerced into a fabricated pass/fail."""
    if not isinstance(row, dict):
        return None
    pred = _norm(row.get("predicted"), _PRED_ALIASES)
    act = _norm(row.get("actual"), _ACTUAL_ALIASES)
    if pred is None or act is None:
        return None
    out: Dict[str, Any] = {"predicted": pred, "actual": act}
    sc = _norm_source(row.get("source_class"))
    if sc is not None:                                    # only carry provenance when the row states it
        out["source_class"] = sc
    for k in ("date", "engagement", "unit", "commit", "notes"):
        if row.get(k) is not None:
            out[k] = row[k]
    return out


def _direction_and_strength(fc: Optional[float], fa: Optional[float]) -> Tuple[str, float]:
    """From the two error rates -> ('too_lenient'|'too_strict'|'balanced'|'insufficient', strength).

    Too-lenient means READY units broke more than NOT_READY units held (tighten the scorer); too-strict
    is the reverse (relax it). 'insufficient' = no confident predictions at all (only CAUTION)."""
    if fc is not None and fa is not None:
        strength = abs(fc - fa)
        if fc > fa + _MARGIN:
            return "too_lenient", strength
        if fa > fc + _MARGIN:
            return "too_strict", strength
        return "balanced", strength
    if fc is not None:
        return ("too_lenient", fc) if fc > _MARGIN else ("balanced", fc)
    if fa is not None:
        return ("too_strict", fa) if fa > _MARGIN else ("balanced", fa)
    return "insufficient", 0.0


def calibration_gap(outcomes: List[Any], *, real_only: bool = False) -> Dict[str, Any]:
    """The descriptive predicted-vs-actual calibration report. Pure; no I/O, no engine import.

    Buckets the (normalized) outcomes by predicted label and reports, per bucket, the incident rate;
    then the two headline error rates (false-confidence, false-alarm), the accuracy over *confident*
    predictions (CAUTION excluded — it is neither a go nor a stop), and the calibration *direction*.
    ``n`` counts only usable rows (malformed dropped), so absence stays absence.

    ``real_n`` counts the subset whose provenance is ``REAL`` (genuine post-cutover outcomes) and
    ``by_source`` breaks the rows down by provenance — the D11 tuning floor is measured against
    ``real_n``, never the total. With ``real_only=True`` the report is computed over the REAL rows
    alone (the basis a tuning proposal must use)."""
    all_valid = [o for o in (normalize_outcome(r) for r in (outcomes or [])) if o]
    real_n = sum(1 for o in all_valid if o.get("source_class") == "REAL")
    by_source: Dict[str, int] = {}
    for o in all_valid:
        sc = o.get("source_class") or "unspecified"
        by_source[sc] = by_source.get(sc, 0) + 1
    valid = [o for o in all_valid if o.get("source_class") == "REAL"] if real_only else all_valid
    n = len(valid)
    by: Dict[str, Dict[str, Any]] = {}
    for lab in ("READY", "CAUTION", "NOT_READY"):
        grp = [o for o in valid if o["predicted"] == lab]
        inc = sum(1 for o in grp if o["actual"] == "incident")
        by[lab] = {"n": len(grp), "incident": inc, "clean": len(grp) - inc,
                   "incident_rate": round(inc / len(grp), 3) if grp else None}
    fc = by["READY"]["incident_rate"]                          # P(incident | READY)
    fa = (round(by["NOT_READY"]["clean"] / by["NOT_READY"]["n"], 3)
          if by["NOT_READY"]["n"] else None)                  # P(clean | NOT_READY)
    conf = by["READY"]["n"] + by["NOT_READY"]["n"]             # confident predictions
    correct = by["READY"]["clean"] + by["NOT_READY"]["incident"]
    accuracy = round(correct / conf, 3) if conf else None
    direction, strength = _direction_and_strength(fc, fa)
    note = _gap_note(n, fc, fa, accuracy, direction)
    return {"n": n, "real_n": real_n, "by_source": by_source,
            "by_predicted": by, "false_confidence_rate": fc, "false_alarm_rate": fa,
            "accuracy": accuracy, "direction": direction, "strength": round(strength, 3), "note": note}


def _gap_note(n: int, fc: Optional[float], fa: Optional[float],
              accuracy: Optional[float], direction: str) -> str:
    if n == 0:
        return "no labeled PIR outcomes yet — calibration is descriptive-only and cannot run."
    parts = [f"N={n}"]
    parts.append(f"false-confidence={fc}" if fc is not None else "false-confidence=n/a (no READY units)")
    parts.append(f"false-alarm={fa}" if fa is not None else "false-alarm=n/a (no NOT_READY units)")
    if accuracy is not None:
        parts.append(f"accuracy={accuracy}")
    parts.append(f"direction: {direction}")
    return "; ".join(parts) + "."


def _lever_value(config: Any, lever: str) -> Any:
    """Resolve a dotted lever ('caps.XL') to its current value on a ScoringConfig."""
    obj = config
    for part in lever.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


def propose_adjustment(outcomes: List[Any], config: Any = None, *,
                       n_floor: int = DEFAULT_N_FLOOR, lever: str = DEFAULT_LEVER) -> Dict[str, Any]:
    """The D11-gated proposal. **Descriptive-only until N >= n_floor REAL outcomes**; below the floor it
    returns ``proposal=None`` with a reason that says exactly why (the Phase-1 acceptance: "calibration
    refuses to move a parameter below the N-floor and says so"). **The floor is measured against REAL
    (post-cutover) outcomes only** — surrogate rows (fault-injected / public / synthetic) are counted in
    the descriptive ``gap`` and validate detectors, but can never unlock a tuning proposal, and the
    proposal itself is derived from the REAL outcomes alone. At/above the floor it proposes ONE small,
    reversible delta on ``lever`` in the direction the REAL gap indicates — and **applies nothing**
    (``applied`` is always False; every unattended action is propose-only).

    ``config`` defaults to the engine's module-default :data:`cisco_toolkit.analyze.SCORING` (imported
    lazily so the descriptive path needs no engine import). It is read, never mutated."""
    gap = calibration_gap(outcomes)                        # descriptive, over ALL rows (real+surrogate)
    real_gap = calibration_gap(outcomes, real_only=True)   # the tuning basis: REAL outcomes only
    real_n, total_n = real_gap["n"], gap["n"]
    if real_n < n_floor:
        surrogate = (f" (of {total_n} total — surrogate/public rows validate detectors but NEVER tune "
                     f"ScoringConfig)" if total_n > real_n else "")
        return {"gated": True, "n": total_n, "real_n": real_n, "n_floor": n_floor, "proposal": None,
                "applied": False, "gap": gap, "real_gap": real_gap,
                "reason": (f"descriptive-only until N >= {n_floor} REAL labeled PIR outcomes (D11); have "
                           f"{real_n} REAL{surrogate}. No ScoringConfig parameter will be moved — too few "
                           f"REAL outcomes to tune on without overfitting. See "
                           f"docs/autonomous-brain-plan-v4-final-2026-07-06.md D11.")}

    if config is None:
        from cisco_toolkit.analyze import SCORING as config   # lazy: only the proposing path needs it
    current = _lever_value(config, lever)
    direction, strength = real_gap["direction"], real_gap["strength"]   # tune on REAL outcomes only

    if direction in ("balanced", "insufficient"):
        reason = ("scorer is well-calibrated on these outcomes; no change proposed."
                  if direction == "balanced"
                  else "no confident predictions (all CAUTION) to calibrate against; no change proposed.")
        return {"gated": False, "n": total_n, "real_n": real_n, "n_floor": n_floor, "proposal": None,
                "applied": False, "gap": gap, "real_gap": real_gap, "reason": reason,
                "note": "PROPOSE-ONLY — nothing applied; reversible."}

    frac = 0.10 if strength >= 0.5 else 0.05                   # 5% normally; 10% only for a strong gap
    mag = max(1, round(current * frac))
    sign = +1 if direction == "too_lenient" else -1            # lenient -> stricter (raise); strict -> looser
    delta = sign * mag
    why = ("too many READY units had incidents -> tighten the scorer"
           if direction == "too_lenient"
           else "too many NOT_READY units were actually clean -> relax the scorer")
    rationale = (f"{why}. false-confidence={real_gap['false_confidence_rate']}, "
                 f"false-alarm={real_gap['false_alarm_rate']}, |gap|={strength:.2f} (over {real_n} REAL "
                 f"outcomes). Move is {round(frac * 100)}% of current and fully reversible.")
    proposal = {"param": lever, "current": current, "proposed": current + delta, "delta": delta,
                "direction": "stricter" if delta > 0 else "looser", "reversible": True,
                "rationale": rationale}
    return {"gated": False, "n": total_n, "real_n": real_n, "n_floor": n_floor, "proposal": proposal,
            "applied": False, "gap": gap, "real_gap": real_gap, "reason": rationale,
            "limitation": ("label-only outcomes calibrate DIRECTION + magnitude on one conservative "
                           "lever; a full per-finding weight refit needs per-finding labelled features, "
                           "not just per-unit pass/fail."),
            "note": "PROPOSE-ONLY — apply via a human-reviewed ScoringConfig change; reversible."}


# --- persistence + CLI -------------------------------------------------------------------------

def read_outcomes(path: str = PIR_OUTCOMES_PATH) -> List[Dict[str, Any]]:
    """Every well-formed row in file order. Missing/empty -> [] (absence is absence). Malformed JSON
    lines are skipped, not fatal (mirrors :func:`cisco_toolkit.scorecard.read_rows`)."""
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


def render_report(outcomes: List[Any], *, n_floor: int = DEFAULT_N_FLOOR) -> str:
    """A human-readable calibration report — the gap, then the (gated) proposal, both coverage-honest."""
    res = propose_adjustment(outcomes, n_floor=n_floor)
    gap = res["gap"]
    L = [f"PIR calibration — {gap['note']}"]
    if res.get("n") != res.get("real_n"):                # surrogate rows present -> disclose provenance
        L.append(f"  provenance: {res.get('real_n', 0)} REAL of {res.get('n', 0)} rows are tune-eligible "
                 f"{gap.get('by_source', {})} — only REAL outcomes can move the scorer")
    by = gap["by_predicted"]
    for lab in ("READY", "CAUTION", "NOT_READY"):
        b = by[lab]
        if b["n"]:
            L.append(f"  predicted {lab:<9} n={b['n']:<3} incident={b['incident']} clean={b['clean']}"
                     + (f"  incident-rate={b['incident_rate']}" if b["incident_rate"] is not None else ""))
    if res["gated"]:
        L.append(f"  [GATED] {res['reason']}")
    elif res["proposal"]:
        p = res["proposal"]
        L.append(f"  PROPOSAL ({p['direction']}): {p['param']} {p['current']} -> {p['proposed']} "
                 f"(delta {p['delta']:+d}, reversible)")
        L.append(f"    {p['rationale']}")
        L.append(f"  {res['note']}")
        L.append(f"  limitation: {res['limitation']}")
    else:
        L.append(f"  no change proposed — {res['reason']}")
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. ``--report`` prints the calibration gap + the D11-gated proposal; ``--show`` tails the
    labeled-outcome store. Reads only; never applies anything."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    path = os.environ.get("PIR_OUTCOMES_FILE") or PIR_OUTCOMES_PATH
    if "--show" in argv:
        rows = read_outcomes(path)
        if not rows:
            print("pir_outcomes: no entries yet")
        else:
            for r in rows[-10:]:
                print(json.dumps(r, ensure_ascii=True))
        return 0
    if "--report" in argv or not argv:
        print(render_report(read_outcomes(path)))
        return 0
    print(__doc__.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
