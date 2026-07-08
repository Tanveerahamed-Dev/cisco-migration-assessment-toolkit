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
