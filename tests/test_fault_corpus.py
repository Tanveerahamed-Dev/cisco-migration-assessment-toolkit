"""Tests for the fault-injected calibration corpus (cisco_toolkit.fault_corpus).

Properties:
- the clean scenario scores READY; injecting any single real fault flips it to non-READY (the engine's
  readiness scorer discriminates good network states from bad — the deterministic strength, verified);
- the corpus rows are labeled by construction (clean->clean, fault->incident) and tagged fault-injected;
- fed to the calibration nerve the rows show OUTCOME SEPARATION (READY->clean, NOT_READY->incident) — the
  Gate-B signal — yet, being surrogate, they NEVER unlock a tuning proposal (Correction 1, end-to-end).
"""
import json

from cisco_toolkit import fault_corpus as F
from cisco_toolkit import calibration as C


def test_clean_scenario_scores_ready():
    assert F.readiness_of(F.clean_scenario()) == "READY"


def test_every_injected_fault_is_flagged_non_ready():
    for name, mutate in F.FAULTS.items():
        s = F.clean_scenario()
        mutate(s)
        assert F.readiness_of(s) != "READY", f"{name} was not flagged (engine rated it READY)"


def test_injection_is_non_vacuous():
    s = F.clean_scenario()
    assert F.readiness_of(s) == "READY"
    list(F.FAULTS.values())[0](s)                              # inject the first fault
    assert F.readiness_of(s) != "READY"                        # the verdict genuinely flips


def test_corpus_rows_are_labeled_and_surrogate_tagged():
    rows = F.corpus_rows()
    assert len(rows) == 1 + len(F.FAULTS)
    assert all(r["source_class"] == "fault-injected" for r in rows)
    clean = [r for r in rows if r["actual"] == "clean"]
    faults = [r for r in rows if r["actual"] == "incident"]
    assert len(clean) == 1 and clean[0]["predicted"] == "READY"
    assert len(faults) == len(F.FAULTS) and all(r["predicted"] != "READY" for r in faults)


def test_corpus_shows_calibration_separation():
    gap = C.calibration_gap(F.corpus_rows())
    assert gap["false_confidence_rate"] == 0.0                 # no predicted-READY unit had an incident
    assert gap["by_predicted"]["NOT_READY"]["incident"] >= 1   # NOT_READY -> incident cell populated (Gate B)


def test_surrogate_corpus_never_unlocks_tuning():
    # the whole point of Correction 1: a full fault-injected corpus stays descriptive-only.
    res = C.propose_adjustment(F.corpus_rows())
    assert res["gated"] is True and res["real_n"] == 0 and res["n"] == 1 + len(F.FAULTS)


def test_readiness_of_empty_move_groups_is_ready():
    """No move-groups → nothing to gate → READY (the short-circuit at fault_corpus.py:73)."""
    s = F.clean_scenario()
    s["move_groups"] = []
    assert F.readiness_of(s) == "READY"


def test_main_emit_prints_one_jsonl_row_per_corpus_entry(capsys):
    rc = F.main(["--emit"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1 + len(F.FAULTS)           # clean baseline + one row per fault
    for ln in lines:
        row = json.loads(ln)
        assert {"predicted", "actual", "source_class"} <= set(row)
        assert row["source_class"] == "fault-injected"


def test_main_report_shows_full_discrimination(capsys):
    rc = F.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fault-injected calibration corpus" in out
    assert "clean baseline" in out
    # every injected fault is flagged non-READY (the module's whole reason to exist)
    assert f"engine flagged {len(F.FAULTS)}/{len(F.FAULTS)}" in out
