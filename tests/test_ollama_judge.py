"""Tests for the cross-family Ollama judge runner (ollama_judge) — HERMETIC: the Ollama call is injected,
so these never require a running model. Properties:

- the verdict parser is conservative (only a CLEAR reject counts; a reject localizes only on a KNOWN class);
- the prompt is refute-first and embeds the deliverable text + the class vocabulary;
- run_baseline wires the judge over the panel and scores TNR — an AGREEABLE judge scores 0 (the failure
  mode we hunt), a correct rejection localizes to 1.0, a wrong-reason reject is unlocalized;
- Ollama-down degrades to {ok: False}, never raises.
"""
import email.message
import http.client
import io

import pytest

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


def test_build_prompt_walks_all_eleven_text_visible_conditions():
    """The 18-panel growth (2026-07-18): every text-visible class has its own NUMBERED condition in the
    walk — a panel defect without a prompt condition would be scored against a judge never told to look
    for it (the rung-5 lesson: the check must live INSIDE a numbered condition, not the preamble)."""
    prompt = J.build_prompt("x")
    for cls in J._text_visible_classes():
        assert f"{cls}:" in prompt, f"class {cls} lacks a numbered condition in the prompt walk"
    assert "11." in prompt                            # the walk is numbered through the grown panel


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


def test_run_baseline_refuses_to_measure_a_judge_that_never_answered():
    """A judge that RAISED is signal_absent, not an APPROVE (2026-07-28, finding #77).

    The prior contract here was "a judge error just counts as not-caught": the exception became the
    string ``"(judge error: …)"``, which :func:`parse_verdict` reads as ordinary free text and defaults
    to APPROVE. With the model not pulled, ``_listening`` still returns True and every /api/chat 404s —
    so ``approves_clean`` (the specificity control that unlocks a numeric ``judge_tnr``) was satisfied
    with ZERO successful calls and a 0.0 TNR was recorded over a panel nobody judged. The run must
    degrade the same way Ollama-down degrades, and it must never raise.
    """
    def boom(prompt):
        raise RuntimeError("model 'qwen3:4b' not found, try pulling it first")
    res = J.run_baseline(ids=["D-11"], listening=lambda h: True, chat=boom)
    assert res["ok"] is False
    assert "clean control" in res["reason"] and "not found" in res["reason"]
    assert "localized_tnr" not in res and "approves_clean" not in res   # nothing is measured


def test_run_baseline_refuses_when_a_panel_call_fails_midway():
    """The clean control answering does not license scoring a PARTIAL panel: one unjudged defect and
    the TNR denominator is a fiction, so the whole run is signal_absent."""
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "VERDICT: APPROVE\nDEFECT_CLASS: NONE"        # clean control answers
        raise TimeoutError("read timed out")                     # then the model dies
    res = J.run_baseline(ids=["D-03", "D-11"], listening=lambda h: True, chat=flaky)
    assert res["ok"] is False and "D-03" in res["reason"] and "incomplete" in res["reason"]


def test_append_baseline_cli_records_nothing_when_the_judge_errors(tmp_path, monkeypatch):
    """End-to-end of the same defect through the recording path: a listening-but-not-answering Ollama
    (model never pulled) must append NO scorecard row — the docstring's signal_absent promise."""
    from cisco_toolkit import scorecard as S
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    monkeypatch.setattr(J, "_listening", lambda *a, **kw: True)   # socket accepts...
    monkeypatch.setattr(J, "_chat", lambda *a, **kw: (_ for _ in ()).throw(
        OSError("HTTP Error 404: Not Found")))                    # ...but every call 404s
    assert J.main(["qwen3:4b", "--append-baseline"]) == 0
    assert S.read_rows(sc) == []


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


# ── the loopback pin: no redirect may take an Ollama call off-host ──────────────────────────────
# cisco_toolkit.attestation.loopback_only validates the FIRST hop only. urlopen follows a 301/302/303
# through the default HTTPRedirectHandler, so anything answering on 127.0.0.1:11434 that is not
# Ollama (a local AI-gateway / LiteLLM shim on the standard port) could reply
# `Location: http://ollama.corp.example/...` and urllib would open THAT host and hand its body back
# as the model's answer — egress, and an off-host party dictating a scorecard measurement. Driven
# through a faked transport: no socket is ever created, and the assertion is on the hosts urllib
# WOULD have opened. Reverting the _no_redirect_opener() call sites fails this with
# `2 hop(s) opened: ['127.0.0.1', 'ollama.corp.example']`.
_REAL_CONN = http.client.HTTPConnection


class _FakeResp(io.BytesIO):
    def __init__(self, status, headers, body=b""):
        super().__init__(body)
        self.status = self.code = status
        self.reason, self.url, self.will_close = "fake", "", False
        self.headers = self.msg = email.message.Message()
        for k, v in headers.items():
            self.headers[k] = v

    def info(self):
        return self.headers

    def geturl(self):
        return self.url


def _redirecting_transport(opened, target):
    """An HTTPConnection whose first response is a 302 to `target` — connect() is a no-op, so no
    socket is opened and nothing here can touch a real network."""

    class _Conn(_REAL_CONN):
        def connect(self):
            pass

        def request(self, method, url, body=None, headers=None, **kw):
            opened.append(self.host)
            self._n = len(opened)

        def getresponse(self):
            if self._n == 1:
                return _FakeResp(302, {"Location": target, "Content-Length": "0"})
            return _FakeResp(200, {"Content-Type": "application/json"},
                             b'{"message": {"content": "{}"}, "embedding": [1.0]}')

        def close(self):
            pass

    return _Conn


@pytest.mark.parametrize("module_name, call", [
    ("ollama_judge", lambda m: m._chat("qwen3:4b", "prompt", timeout=1)),
    ("ollama_recall", lambda m: m._embed("prompt", timeout=1)),
    ("ollama_retrieval_judge", lambda m: m._chat("qwen3:4b", "prompt", timeout=1)),
])
def test_ollama_helpers_refuse_a_redirect_off_loopback(module_name, call, monkeypatch):
    mod = __import__(module_name)
    assert mod.OLLAMA_HOST.startswith(("127.", "localhost", "[::1]"))   # first hop is pinned
    opened = []
    monkeypatch.setattr(http.client, "HTTPConnection",
                        _redirecting_transport(opened, "http://ollama.corp.example:11434/api/chat"))
    with pytest.raises(Exception) as ex:
        call(mod)
    assert "redirect" in str(ex.value).lower(), f"{module_name} did not name the refusal: {ex.value}"
    assert opened == ["127.0.0.1"], f"{len(opened)} hop(s) opened: {opened}"
