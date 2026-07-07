"""Tests for the PIR-outcome calibration nerve (cisco_toolkit.calibration).

The load-bearing properties, straight off the Phase-1 acceptance in
``docs/autonomous-brain-plan-v4-final-2026-07-06.md``:

- the calibration gap is DERIVED from labeled outcomes (false-confidence / false-alarm), and the
  *direction* flips with the data (lenient vs strict) — non-vacuous;
- **below the N-floor, a proposal is REFUSED and the reason says so** (the D11 gate);
- at/above the floor a proposal is small, reversible, direction-matched, and **never applied**;
- absence is absence (no outcomes -> "cannot run", not a fabricated calibration);
- the proposer never mutates the engine's live ScoringConfig.
"""
import os

from cisco_toolkit import calibration as C


def _oc(predicted, actual, **kw):
    return {"predicted": predicted, "actual": actual, **kw}


# --- the gap (descriptive) ---------------------------------------------------------------------

def test_gap_false_confidence_rate_and_too_lenient():
    # 3 of 5 READY units hit an incident -> false-confidence 0.6; no NOT_READY -> too lenient.
    ocs = [_oc("READY", "incident")] * 3 + [_oc("READY", "clean")] * 2
    g = C.calibration_gap(ocs)
    assert g["n"] == 5
    assert g["false_confidence_rate"] == 0.6
    assert g["false_alarm_rate"] is None
    assert g["direction"] == "too_lenient"


def test_gap_false_alarm_rate_and_too_strict():
    # 4 of 5 NOT_READY units were actually clean -> false-alarm 0.8 -> too strict.
    ocs = [_oc("NOT_READY", "clean")] * 4 + [_oc("NOT_READY", "incident")] * 1
    g = C.calibration_gap(ocs)
    assert g["false_alarm_rate"] == 0.8
    assert g["false_confidence_rate"] is None
    assert g["direction"] == "too_strict"


def test_gap_balanced_when_predictions_hold():
    ocs = [_oc("READY", "clean")] * 3 + [_oc("NOT_READY", "incident")] * 3
    g = C.calibration_gap(ocs)
    assert g["false_confidence_rate"] == 0.0 and g["false_alarm_rate"] == 0.0
    assert g["direction"] == "balanced" and g["accuracy"] == 1.0


def test_caution_excluded_from_confident_accuracy():
    # CAUTION is neither a go nor a stop -> excluded from the accuracy denominator.
    ocs = [_oc("READY", "clean"), _oc("NOT_READY", "incident"), _oc("CAUTION", "incident")]
    g = C.calibration_gap(ocs)
    assert g["by_predicted"]["CAUTION"]["n"] == 1
    assert g["accuracy"] == 1.0        # 2/2 confident predictions correct; CAUTION not counted


# --- the D11 gate ------------------------------------------------------------------------------

def test_gated_below_floor_refuses_and_says_so():
    """The Phase-1 acceptance: below N=5, no parameter moves and the reason says exactly why."""
    res = C.propose_adjustment([_oc("READY", "incident")] * 4)     # N=4 < 5
    assert res["gated"] is True
    assert res["proposal"] is None
    assert res["applied"] is False
    assert res["n"] == 4 and res["n_floor"] == 5
    assert "descriptive-only" in res["reason"] and ">= 5" in res["reason"]


def test_n_floor_is_the_knob():
    ocs = [_oc("READY", "incident")] * 3
    assert C.propose_adjustment(ocs, n_floor=5)["gated"] is True
    assert C.propose_adjustment(ocs, n_floor=3)["gated"] is False   # explicit lower floor ungates


# --- the proposal (at/above the floor; propose-only) -------------------------------------------

def test_proposal_at_floor_stricter_when_lenient():
    ocs = [_oc("READY", "incident")] * 4 + [_oc("READY", "clean")] * 1   # N=5, fc=0.8 -> lenient
    res = C.propose_adjustment(ocs)
    assert res["gated"] is False and res["applied"] is False
    p = res["proposal"]
    assert p is not None
    assert p["delta"] > 0 and p["direction"] == "stricter" and p["reversible"] is True
    assert p["proposed"] == p["current"] + p["delta"]
    assert abs(p["delta"]) <= p["current"] * 0.10 + 1                    # small (<= ~10%)


def test_proposal_at_floor_looser_when_strict():
    """Non-vacuity vs. the lenient case: an over-strict scorer proposes the OPPOSITE sign."""
    ocs = [_oc("NOT_READY", "clean")] * 4 + [_oc("NOT_READY", "incident")] * 1   # N=5, fa=0.8 -> strict
    res = C.propose_adjustment(ocs)
    p = res["proposal"]
    assert p is not None and p["delta"] < 0 and p["direction"] == "looser"


def test_balanced_at_floor_proposes_no_change():
    ocs = [_oc("READY", "clean")] * 3 + [_oc("NOT_READY", "incident")] * 2   # N=5, well-calibrated
    res = C.propose_adjustment(ocs)
    assert res["gated"] is False and res["proposal"] is None
    assert "well-calibrated" in res["reason"]


def test_propose_never_mutates_scoring():
    from cisco_toolkit.analyze import SCORING
    before = SCORING.caps["XL"]
    res = C.propose_adjustment([_oc("READY", "incident")] * 5)
    assert res["applied"] is False
    assert SCORING.caps["XL"] == before                # proposed, never applied
    assert res["proposal"]["current"] == before        # and it read the live default


# --- robustness + coverage-honesty -------------------------------------------------------------

def test_empty_is_descriptive_absence():
    res = C.propose_adjustment([])
    assert res["gated"] is True and res["proposal"] is None
    assert res["gap"]["n"] == 0 and "cannot run" in res["gap"]["note"]


def test_malformed_rows_skipped_not_fatal():
    ocs = [_oc("READY", "clean"), {"predicted": "???", "actual": "clean"},
           {"predicted": "READY"}, "not a dict", {"actual": "incident"}, None]
    assert C.calibration_gap(ocs)["n"] == 1             # only the one usable row is counted


def test_normalize_outcome_aliases():
    assert C.normalize_outcome({"predicted": "go", "actual": "success"})["predicted"] == "READY"
    assert C.normalize_outcome({"predicted": "no-go", "actual": "rollback"}) == {
        "predicted": "NOT_READY", "actual": "incident"}
    assert C.normalize_outcome({"predicted": "warn", "actual": "clean"})["predicted"] == "CAUTION"
    assert C.normalize_outcome({"predicted": "ready", "actual": "???"}) is None


def test_read_outcomes_missing_file_is_empty():
    assert C.read_outcomes(os.path.join("no", "such", "file.jsonl")) == []


def test_render_report_gated_and_proposal():
    gated = C.render_report([_oc("READY", "incident")] * 3)
    assert "GATED" in gated and "descriptive-only" in gated
    proposed = C.render_report([_oc("READY", "incident")] * 5)
    assert "PROPOSAL" in proposed and "reversible" in proposed and "PROPOSE-ONLY" in proposed
