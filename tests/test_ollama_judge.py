"""Tests for the cross-family Ollama judge runner (ollama_judge) — HERMETIC: the Ollama call is injected,
so these never require a running model. Properties:

- the verdict parser is conservative (only a CLEAR reject counts; a reject localizes only on a KNOWN class);
- the prompt is refute-first and embeds the deliverable text + the class vocabulary;
- run_baseline wires the judge over the panel and scores TNR — an AGREEABLE judge scores 0 (the failure
  mode we hunt), a correct rejection localizes to 1.0, a wrong-reason reject is unlocalized;
- Ollama-down degrades to {ok: False}, never raises.
"""
import ollama_judge as J
from cisco_toolkit import defect_panel as P


def test_parse_reject_with_known_class_localizes():
    v = J.parse_verdict("...analysis...\nVERDICT: REJECT\nDEFECT_CLASS: phantom-health")
    assert v == {"verdict": "REJECT", "defect_class": "phantom-health"}


def test_parse_approve_is_class_none():
    v = J.parse_verdict("Everything reconciles.\nVERDICT: APPROVE\nDEFECT_CLASS: NONE")
    assert v["verdict"] == "APPROVE" and v["defect_class"] is None


def test_parse_reject_with_unknown_class_is_unlocalized():
    v = J.parse_verdict("VERDICT: REJECT\nDEFECT_CLASS: something-i-made-up")
    assert v["verdict"] == "REJECT" and v["defect_class"] is None


def test_parse_garbled_or_empty_defaults_to_approve():
    # a defect slips through a garbled/hedged answer -> APPROVE, never a fabricated reject
    assert J.parse_verdict("")["verdict"] == "APPROVE"
    assert J.parse_verdict("I think this is mostly fine, hard to say")["verdict"] == "APPROVE"


def test_build_prompt_carries_text_and_vocab_and_both_verdicts():
    text = P.build_panel(["D-03"])[0]["text"]
    prompt = J.build_prompt(text)
    assert "REJECT" in prompt.upper() and "APPROVE" in prompt.upper()   # a real judge offers both outcomes
    assert "core9" in prompt                          # the deliverable excerpt is embedded
    assert "phantom-health" in prompt                 # the defect definitions / class vocabulary are offered


def test_parse_structured_json_reject_localizes():
    v = J.parse_verdict('{"reasoning":"NRFU PASS with empty output","verdict":"REJECT","defect_class":"empty-nrfu-evidence"}')
    assert v == {"verdict": "REJECT", "defect_class": "empty-nrfu-evidence"}


def test_parse_structured_json_approve_is_class_none():
    v = J.parse_verdict('{"reasoning":"all reconciles","verdict":"APPROVE","defect_class":"NONE"}')
    assert v["verdict"] == "APPROVE" and v["defect_class"] is None


def test_parse_structured_reject_unknown_class_is_unlocalized():
    v = J.parse_verdict('{"reasoning":"x","verdict":"REJECT","defect_class":"made-up-class"}')
    assert v["verdict"] == "REJECT" and v["defect_class"] is None


def test_judge_schema_constrains_verdict_and_class():
    s = J.judge_schema()
    assert s["properties"]["verdict"]["enum"] == ["APPROVE", "REJECT"]
    enum = s["properties"]["defect_class"]["enum"]
    assert "NONE" in enum and "phantom-health" in enum


def test_run_baseline_degrades_when_ollama_down():
    res = J.run_baseline(listening=lambda h: False)
    assert res["ok"] is False and "not listening" in res["reason"]


def test_run_baseline_agreeable_judge_scores_zero():
    # the exact failure mode: an all-APPROVE cross-family judge is ALSO exposed as TNR 0, not trusted.
    res = J.run_baseline(chat=lambda prompt: "VERDICT: APPROVE\nDEFECT_CLASS: NONE",
                         listening=lambda h: True)
    assert res["ok"] is True
    assert res["localized_tnr"] == 0.0 and res["rejection_rate"] == 0.0


def test_run_baseline_correct_rejection_localizes():
    # judge one defect and answer correctly -> localized TNR 1.0 over that 1-defect panel
    res = J.run_baseline(ids=["D-03"], listening=lambda h: True,
                         chat=lambda prompt: "VERDICT: REJECT\nDEFECT_CLASS: phantom-health")
    assert res["ok"] is True and res["n"] == 1 and res["localized_tnr"] == 1.0


def test_run_baseline_wrong_reason_is_unlocalized():
    res = J.run_baseline(listening=lambda h: True,
                         chat=lambda prompt: "VERDICT: REJECT\nDEFECT_CLASS: wrong-class")
    assert res["localized_tnr"] == 0.0 and res["unlocalized_rejection_rate"] == 1.0


def test_run_baseline_is_total_on_judge_error():
    # a judge that raises must not crash the run — that defect just counts as not-caught (APPROVE)
    def boom(prompt):
        raise RuntimeError("model exploded")
    res = J.run_baseline(ids=["D-11"], listening=lambda h: True, chat=boom)
    assert res["ok"] is True and res["localized_tnr"] == 0.0


def test_run_baseline_reports_specificity_via_clean_control():
    # an all-APPROVE judge correctly APPROVES the clean control -> specificity holds
    r = J.run_baseline(chat=lambda p: '{"reasoning":"ok","verdict":"APPROVE","defect_class":"NONE"}',
                       listening=lambda h: True)
    assert r["approves_clean"] is True
    # a reject-EVERYTHING judge is exposed by the clean control (no specificity) — the trap the harness
    # must surface, so a high rejection_rate can't be mistaken for a working judge.
    r2 = J.run_baseline(chat=lambda p: '{"reasoning":"x","verdict":"REJECT","defect_class":"phantom-health"}',
                        listening=lambda h: True)
    assert r2["approves_clean"] is False


# --- the judge-baseline scorecard row (P0-6a: --append-baseline) ---------------------------------
# The measurement becomes the `judge-baseline` row that cisco_toolkit.scorecard.latest_judge_baseline
# stamps every subsequent QA verdict from. Properties: a MEASUREMENT not a verdict (verdict/score
# null); no specificity -> null trust (a reject-everything judge must never stamp APPROVEs gating);
# Ollama down -> NOTHING appended (a measurement row is never fabricated).

def test_baseline_row_is_a_measurement_not_a_verdict():
    from cisco_toolkit import scorecard as S
    # a DISCRIMINATING judge: approves the clean control (no core9 'healthy' claim in it), rejects
    # the D-03 corruption — specificity holds, so the measured TNR is trustworthy
    res = J.run_baseline(ids=["D-03"], listening=lambda h: True,
                         chat=lambda p: ("VERDICT: REJECT\nDEFECT_CLASS: phantom-health"
                                         if "Device core9 assessed" in p
                                         else "VERDICT: APPROVE\nDEFECT_CLASS: NONE"))
    assert res["approves_clean"] is True
    row = J.baseline_row(res, date="2026-07-10", commit="abc1234")
    assert row["deliverable"] == S.JUDGE_BASELINE_DELIVERABLE
    assert row["judge_tnr"] == 1.0 and row["verdict"] is None and row["score"] is None
    assert "clears" in row["notes"]                     # 1.0 >= JUDGE_TNR_FLOOR
    assert S.latest_judge_baseline([row])["judge_tnr"] == 1.0   # this row IS what stamps verdicts


def test_baseline_row_below_floor_notes_provisional():
    # the agreeable judge: approves the clean control AND every defect -> TNR 0, below the floor
    res = J.run_baseline(listening=lambda h: True,
                         chat=lambda p: "VERDICT: APPROVE\nDEFECT_CLASS: NONE")
    row = J.baseline_row(res, date="d", commit="c")
    assert row["judge_tnr"] == 0.0 and "PROVISIONAL" in row["notes"]


def test_baseline_row_no_specificity_records_null_trust():
    """A reject-everything judge can post a high localized TNR — but with approves_clean False it has
    no specificity, so the baseline records judge_tnr NULL (raw numbers kept in notes): it must never
    become the TNR that stamps later APPROVEs as gating."""
    res = J.run_baseline(listening=lambda h: True,
                         chat=lambda p: '{"reasoning":"x","verdict":"REJECT","defect_class":"phantom-health"}')
    assert res["approves_clean"] is False
    row = J.baseline_row(res, date="d", commit="c")
    assert row["judge_tnr"] is None and "NO SPECIFICITY" in row["notes"]


def test_append_baseline_cli_appends_the_row(tmp_path, monkeypatch):
    from cisco_toolkit import scorecard as S
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    canned = {"ok": True, "model": "fake", "approves_clean": True, "n": 1,
              "localized_tnr": 1.0, "rejection_rate": 1.0, "unlocalized_rejection_rate": 0.0,
              "verdicts": [{"defect_id": "D-03", "verdict": "REJECT", "defect_class": "phantom-health"}]}
    monkeypatch.setattr(J, "run_baseline", lambda model, **kw: canned)
    assert J.main(["fake", "--append-baseline"]) == 0
    rows = S.read_rows(sc)
    assert len(rows) == 1
    assert rows[0]["deliverable"] == "judge-baseline" and rows[0]["judge_tnr"] == 1.0
    # re-recording the identical measurement dedupes (append-only, no double rows)
    assert J.main(["fake", "--append-baseline"]) == 0
    assert len(S.read_rows(sc)) == 1


def test_append_baseline_cli_ollama_down_appends_nothing(tmp_path, monkeypatch):
    """signal_absent honestly: Ollama unreachable -> no row is ever fabricated (doctrine 5)."""
    from cisco_toolkit import scorecard as S
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    monkeypatch.setattr(J, "run_baseline",
                        lambda model, **kw: {"ok": False, "reason": "Ollama not listening on 127.0.0.1:11434"})
    assert J.main(["--append-baseline"]) == 0
    assert S.read_rows(sc) == []


# --- the P1-3 stability protocol (--runs / --think): rung 2's 0.4 was refuted by a same-config rerun
# (clean control rejected on run 2), so a multi-run baseline records its WORST run — a specificity
# failure outranks any TNR, then the lowest localized TNR — and the spread stays visible in notes.

def _canned(clean: bool, tnr: float, rej: float = 0.6) -> dict:
    return {"ok": True, "model": "fake", "approves_clean": clean, "n": 5,
            "localized_tnr": tnr, "rejection_rate": rej, "unlocalized_rejection_rate": round(rej - tnr, 3),
            "verdicts": [{"defect_id": "D-12", "verdict": "REJECT", "defect_class": "empty-nrfu-evidence"}]}


def test_worst_of_prefers_no_specificity_then_lowest_tnr():
    clean_high, clean_low = _canned(True, 1.0), _canned(True, 0.2)
    no_spec = _canned(False, 0.8)
    assert J.worst_of([clean_high, clean_low]) is clean_low
    assert J.worst_of([clean_low, no_spec]) is no_spec     # losing the clean control outranks any TNR
    assert J.worst_of([clean_high]) is clean_high


def test_multi_run_records_worst_run_with_spread(tmp_path, monkeypatch):
    from cisco_toolkit import scorecard as S
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    seq = iter([_canned(True, 0.4), _canned(False, 0.2)])   # the literal rung-2 A/B shape
    monkeypatch.setattr(J, "run_baseline", lambda model, **kw: next(seq))
    assert J.main(["fake", "--runs", "2", "--append-baseline"]) == 0
    rows = S.read_rows(sc)
    assert len(rows) == 1
    assert rows[0]["judge_tnr"] is None                     # worst run lost specificity -> null trust
    assert "worst run" in rows[0]["notes"] and "run1" in rows[0]["notes"] and "run2" in rows[0]["notes"]


def test_multi_run_incomplete_protocol_records_nothing(tmp_path, monkeypatch):
    from cisco_toolkit import scorecard as S
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    seq = iter([_canned(True, 1.0), {"ok": False, "reason": "Ollama died mid-protocol"}])
    monkeypatch.setattr(J, "run_baseline", lambda model, **kw: next(seq))
    assert J.main(["fake", "--runs", "2", "--append-baseline"]) == 0
    assert S.read_rows(sc) == []                            # partial k-run protocol -> signal_absent


def test_think_flag_is_plumbed_to_run_baseline(monkeypatch):
    seen = {}

    def fake_rb(model, **kw):
        seen["model"], seen["think"] = model, kw.get("think")
        return {"ok": False, "reason": "probe"}
    monkeypatch.setattr(J, "run_baseline", fake_rb)
    assert J.main(["fake", "--think"]) == 0
    assert seen == {"model": "fake", "think": True}
