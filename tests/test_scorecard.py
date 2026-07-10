"""Tests for the scorecard verdict parser + appender (cisco_toolkit.scorecard).

The appender turns an INDEPENDENT QA verdict into one append-only row. The load-bearing properties:
a real verdict parses to the documented schema; a non-QA subagent message parses to *nothing*
(no fabricated rows); the file is append-only with a dedupe guard; and the whole path is total
(never raises) so the fail-open hook can lean on it.
"""
import json
import os

from cisco_toolkit import scorecard as S

# A realistic deliverable-qa-reviewer verdict: two blocking findings (pipe-delimited), an approving
# sibling, and a Law reference — the shape docs .claude/agents/deliverable-qa-reviewer.md documents.
QA_BLOCK = """Per-artifact QA verdict (I tried to DISPROVE each artifact):

design.docx — BLOCK
Findings (location | claimed | source-of-truth | severity):
LLD §3 topology | 60 access switches | snapshot health_scores = 58 | High
ops Security axis | rendered 'complete' | not-assessable branch missing (Law 3) | High

mop.docx — APPROVE
Rationale: reconciles to the design baseline; no counterexamples found.
"""

QA_APPROVE = """QA verdict: reviewed the runbook for gate-readiness and single-source-of-truth.
runbook.docx — APPROVE. Every headline figure reconciles to the snapshot; no findings.
"""

# A non-QA subagent (design-author) final message — has no verdict/QA markers -> must NOT append.
NON_QA = """I have authored the HLD and LLD. The design collapses the core into a vPC pair and adds
FHRP on every SVI. Artifacts written to deliverables/. Let me know if you'd like changes.
"""

# Regression: the MAIN AGENT's own summary that DESCRIBES a QA verdict — it mentions "verdict",
# "BLOCK", "counterexamples", "reconcile", renders a markdown table, even shows a sample row — but has
# no per-artifact verdict LINE. It must NOT be recorded (this exact prose once fabricated a row).
SUMMARY_PROSE = """Done — the scorecard appender is wired. It parses the **independent** /qa verdict
(proposer != verifier — a verifiable fact, not a self-assessment) into one schema-exact row.

| Item | What it gives you |
|---|---|
| Golden-snapshot eval harness | Deliverable quality is now a falsifiable number |
| Scorecard appender | Each verdict persists a row; e.g. verdict BLOCK, counterexamples 2, laws L3 |

It reconciles to one source of truth; the row is `{"verdict":"BLOCK","counterexamples":2}`.
"""


def test_parse_block_verdict_with_findings():
    row = S.parse_qa_verdict(QA_BLOCK, date="2026-07-06", commit="abc1234")
    assert row is not None
    assert row["verdict"] == "BLOCK"
    assert row["counterexamples"] == 2           # two pipe-delimited findings
    assert row["laws_tripped"] == ["L3"]
    assert row["score"] is None                  # numeric score is the golden harness's job
    assert row["commit"] == "abc1234" and row["date"] == "2026-07-06"
    assert row["deliverable"] == "set"           # spans design + mop
    assert "58" in row["notes"] or "switches" in row["notes"]   # factual: the first finding


def test_parse_approve_verdict_no_findings():
    row = S.parse_qa_verdict(QA_APPROVE, date="2026-07-06", commit="abc1234")
    assert row is not None
    assert row["verdict"] == "APPROVE"
    assert row["counterexamples"] == 0
    assert row["laws_tripped"] == []
    assert row["deliverable"] == "runbook"


def test_non_qa_message_appends_nothing():
    assert S.parse_qa_verdict(NON_QA, date="2026-07-06", commit="abc1234") is None


def test_main_agent_summary_prose_is_not_a_verdict():
    """The load-bearing regression: prose that DESCRIBES a QA verdict (keywords + tables, but no
    per-artifact verdict line) must never be recorded as one."""
    assert S.parse_qa_verdict(SUMMARY_PROSE, date="2026-07-06", commit="abc1234") is None


def test_empty_or_blank_text_is_none():
    assert S.parse_qa_verdict("", date="d", commit="c") is None
    assert S.parse_qa_verdict("   \n  ", date="d", commit="c") is None


def test_verdict_word_without_qa_marker_is_none():
    """A stray 'approve' in prose (no QA marker) must not be mistaken for a QA verdict."""
    assert S.parse_qa_verdict("I approve of this migration plan wholeheartedly.",
                              date="d", commit="c") is None


def test_laws_tripped_filters_stray_tokens():
    txt = "design.docx — BLOCK\nfinding: trips Law 3 and L10 but an ID like L47 is not a Law."
    row = S.parse_qa_verdict(txt, date="d", commit="c")
    assert row["laws_tripped"] == ["L3", "L10"]   # sorted by number; L47 dropped


def test_deliverable_inference_single_vs_set():
    single = S.parse_qa_verdict("mop.docx — APPROVE. reconciles; no findings.", date="d", commit="c")
    assert single["deliverable"] == "mop"


def test_append_row_writes_schema_order_and_dedupes(tmp_path):
    path = str(tmp_path / "scorecard.jsonl")
    row = S.parse_qa_verdict(QA_BLOCK, date="2026-07-06", commit="abc1234")
    assert S.append_row(row, path) is True
    # exact schema keys, in order
    lines = open(path, encoding="utf-8").read().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert list(obj.keys()) == list(S.SCHEMA_KEYS)
    # identical verdict for the same commit -> dedupe no-op (double-fired hook can't double-write)
    assert S.append_row(row, path) is False
    assert len(open(path, encoding="utf-8").read().splitlines()) == 1
    # a different verdict DOES append
    other = S.parse_qa_verdict(QA_APPROVE, date="2026-07-06", commit="abc1234")
    assert S.append_row(other, path) is True
    assert len(open(path, encoding="utf-8").read().splitlines()) == 2


def test_read_rows_missing_file_is_empty_not_error():
    assert S.read_rows(os.path.join("does", "not", "exist.jsonl")) == []


def test_judge_tnr_is_a_schema_field_and_persists(tmp_path):
    """A QA verdict is a Claude judge on Claude's work; its trustworthiness is unknown until the judge's
    true-negative rate is MEASURED (cisco_toolkit.defect_panel). `judge_tnr` records that measurement per
    row: a measured value persists; absent -> honest null (trust unquantified), never a fabricated score."""
    assert "judge_tnr" in S.SCHEMA_KEYS
    path = str(tmp_path / "sc.jsonl")
    row = S.parse_qa_verdict("runbook.docx — APPROVE. reconciles; no findings.", date="d", commit="c")
    row["judge_tnr"] = 0.6                                 # the Move-1 baseline annotates the verdict
    assert S.append_row(row, path) is True
    assert S.read_rows(path)[0]["judge_tnr"] == 0.6
    row2 = S.parse_qa_verdict("mop.docx — APPROVE. reconciles.", date="d", commit="c2")
    assert S.append_row(row2, path) is True
    assert S.read_rows(path)[1]["judge_tnr"] is None       # unmeasured -> null, not a guess


# --- judge trust: PROVISIONAL vs quantified verdicts (P0-6 / DEC-004; gap G-006) -----------------
# Before P0-6, `judge_tnr` was a passive schema field no writer emitted and PROVISIONAL lived only in
# README prose. Properties under test: the latest judge-baseline row stamps every subsequent QA
# verdict (EMIT); an APPROVE whose judge_tnr is null / below JUDGE_TNR_FLOOR persists provisional:true
# and cannot be written trusting (ENFORCE); BLOCKs and deterministic scored rows are never provisional.

BASELINE_ROW = {"date": "2026-07-08", "deliverable": "judge-baseline", "score": None, "verdict": None,
                "judge_tnr": 0.2, "provisional": None, "counterexamples": None, "laws_tripped": [],
                "commit": "b2b2951", "notes": "cross-family LLM judge qwen3:4b: localized TNR=0.2"}


def test_latest_judge_baseline_picks_last_measured():
    rows = [BASELINE_ROW,
            {"deliverable": "judge-baseline", "judge_tnr": None},        # unmeasured -> skipped
            {"deliverable": "design", "judge_tnr": 0.9},                 # not a baseline row
            dict(BASELINE_ROW, date="2026-07-10", judge_tnr=0.4)]
    assert S.latest_judge_baseline(rows)["judge_tnr"] == 0.4             # the LATEST measured one
    assert S.latest_judge_baseline([]) is None
    assert S.latest_judge_baseline(None) is None
    # a bool is not a measurement (True is an int in Python — must not read as TNR 1.0)
    assert S.latest_judge_baseline([{"deliverable": "judge-baseline", "judge_tnr": True}]) is None


def test_is_provisional_predicate():
    # a judge APPROVE with no measured TNR quantifies nothing -> provisional (advisory)
    assert S.is_provisional({"verdict": "APPROVE", "score": None, "judge_tnr": None}) is True
    # measured below the floor -> still provisional (the qwen3:4b 0.2 baseline demotes, not promotes)
    assert S.is_provisional({"verdict": "APPROVE", "score": None, "judge_tnr": 0.2}) is True
    # at/above the floor -> quantified trust, gating
    assert S.is_provisional({"verdict": "APPROVE", "score": None, "judge_tnr": S.JUDGE_TNR_FLOOR}) is False
    # a BLOCK is a grounded counterexample regardless of judge trust (weak judges OVER-approve)
    assert S.is_provisional({"verdict": "BLOCK", "score": None, "judge_tnr": None}) is False
    # a deterministic scored row (golden harness) involves no judge -> never provisional
    assert S.is_provisional({"verdict": "APPROVE", "score": 100, "judge_tnr": None}) is False
    # a judge-baseline / malformed row is not a verdict at all
    assert S.is_provisional({"verdict": None, "score": None}) is False
    assert S.is_provisional("not a dict") is False


def test_run_hook_stamps_judge_tnr_from_latest_baseline(tmp_path):
    """(a) EMIT: with a judge-baseline row on the scorecard, the QA-verdict writer stamps the new
    row's judge_tnr from it — PROVISIONAL vs quantified is machine-readable off the row, not prose."""
    sc = str(tmp_path / "sc.jsonl")
    assert S.append_row(BASELINE_ROW, sc) is True
    tp = str(tmp_path / "t.jsonl")
    _write_transcript_rows(tp, QA_APPROVE)
    row = S.run_hook(json.dumps({"transcript_path": tp}), path=sc, date="2026-07-10", commit="c")
    assert row["judge_tnr"] == 0.2                       # stamped from the baseline, not null
    persisted = S.read_rows(sc)[-1]
    assert persisted["judge_tnr"] == 0.2
    assert persisted["provisional"] is True              # 0.2 < JUDGE_TNR_FLOOR -> advisory, non-gating


def test_run_hook_without_baseline_stamps_null_and_provisional(tmp_path):
    """No baseline ever measured -> judge_tnr stays an honest null and the APPROVE is provisional."""
    sc = str(tmp_path / "sc.jsonl")
    tp = str(tmp_path / "t.jsonl")
    _write_transcript_rows(tp, QA_APPROVE)
    S.run_hook(json.dumps({"transcript_path": tp}), path=sc, date="d", commit="c")
    persisted = S.read_rows(sc)[-1]
    assert persisted["judge_tnr"] is None and persisted["provisional"] is True


def test_record_arm_stamps_from_floor_clearing_baseline(tmp_path, monkeypatch):
    """The --record (message) arm stamps too; a baseline AT/above the floor makes the APPROVE gating."""
    sc = str(tmp_path / "sc.jsonl")
    S.append_row(dict(BASELINE_ROW, judge_tnr=0.5), sc)  # a (hypothetical) floor-clearing baseline
    monkeypatch.setenv("SCORECARD_FILE", sc)
    msg = tmp_path / "qa.md"
    msg.write_text(QA_APPROVE, encoding="utf-8")
    assert S.main(["--record", str(msg)]) == 0
    persisted = S.read_rows(sc)[-1]
    assert persisted["judge_tnr"] == 0.5 and persisted["provisional"] is False


def test_append_row_enforces_provisional_cannot_be_false(tmp_path):
    """(b) ENFORCE at the choke point: a caller stamping provisional=False on a below-floor APPROVE
    is overruled — fabricated confidence cannot be persisted. The conservative direction (forcing
    True on a trustworthy row) is deliberately left alone; BLOCK rows pass through unforced."""
    sc = str(tmp_path / "sc.jsonl")
    row = S.parse_qa_verdict(QA_APPROVE, date="d", commit="c")
    row["provisional"] = False                            # a lying writer
    assert S.append_row(row, sc) is True
    assert S.read_rows(sc)[0]["provisional"] is True      # enforced: judge_tnr null -> advisory
    b = S.parse_qa_verdict(QA_BLOCK, date="d", commit="c")
    assert S.append_row(b, sc) is True
    assert S.read_rows(sc)[-1]["provisional"] is None     # a BLOCK is never marked, never forced


def _write_transcript_rows(path, text):
    _write_transcript(path, [("user", "run /qa"), ("assistant", [{"type": "text", "text": text}])])


def _write_transcript(path, messages):
    """messages: list of (role, content) where content is a str or list of text-block dicts."""
    with open(path, "w", encoding="utf-8") as f:
        for role, content in messages:
            f.write(json.dumps({"type": role, "message": {"role": role, "content": content}}) + "\n")


def test_extract_last_assistant_text_across_shapes(tmp_path):
    p = str(tmp_path / "t.jsonl")
    _write_transcript(p, [
        ("user", "please QA the deliverables"),
        ("assistant", [{"type": "text", "text": "working on it"}]),
        ("assistant", "runbook.docx — APPROVE. reconciles; no findings."),   # string content shape
    ])
    assert "APPROVE" in S.extract_last_assistant_text(p)


def test_run_hook_appends_qa_verdict_from_transcript(tmp_path):
    tp = str(tmp_path / "transcript.jsonl")
    _write_transcript(tp, [
        ("user", "run /qa"),
        ("assistant", [{"type": "text", "text": QA_BLOCK}]),
    ])
    sc = str(tmp_path / "scorecard.jsonl")
    payload = json.dumps({"hook_event_name": "SubagentStop", "transcript_path": tp})
    row = S.run_hook(payload, path=sc, date="2026-07-06", commit="abc1234")
    assert row is not None and row["verdict"] == "BLOCK"
    rows = S.read_rows(sc)
    assert len(rows) == 1 and rows[0]["counterexamples"] == 2


def test_run_hook_non_qa_transcript_appends_nothing(tmp_path):
    tp = str(tmp_path / "transcript.jsonl")
    _write_transcript(tp, [("assistant", [{"type": "text", "text": NON_QA}])])
    sc = str(tmp_path / "scorecard.jsonl")
    assert S.run_hook(json.dumps({"transcript_path": tp}), path=sc, date="d", commit="c") is None
    assert S.read_rows(sc) == []                  # coverage-honest: nothing recorded, file untouched


def test_record_from_transcript_cli(tmp_path, monkeypatch):
    """`--record-from <transcript>` records the INDEPENDENT subagent verdict from its transcript (the
    manual path for envs where SubagentStop fires but the hook wasn't triggered). Same parser/invariant:
    a transcript of main-agent prose (no verdict signature) records nothing."""
    tp = str(tmp_path / "t.jsonl")
    _write_transcript(tp, [("user", "run /qa"), ("assistant", [{"type": "text", "text": QA_BLOCK}])])
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    assert S.main(["--record-from", tp]) == 0
    rows = S.read_rows(sc)
    assert len(rows) == 1 and rows[0]["verdict"] == "BLOCK" and rows[0]["counterexamples"] == 2
    # a transcript with only non-verdict prose records nothing (invariant preserved)
    tp2 = str(tmp_path / "t2.jsonl")
    _write_transcript(tp2, [("assistant", [{"type": "text", "text": SUMMARY_PROSE}])])
    assert S.main(["--record-from", tp2]) == 0
    assert len(S.read_rows(sc)) == 1               # unchanged — prose is not a verdict


def test_record_from_missing_transcript_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("SCORECARD_FILE", str(tmp_path / "sc.jsonl"))
    assert S.main(["--record-from", str(tmp_path / "nope.jsonl")]) == 0   # total; records nothing


def test_run_hook_is_total_on_bad_input(tmp_path):
    sc = str(tmp_path / "scorecard.jsonl")
    # garbage stdin, missing transcript, non-dict payload — none may raise; all append nothing.
    assert S.run_hook("not json at all", path=sc) is None
    assert S.run_hook("", path=sc) is None
    assert S.run_hook(json.dumps({"transcript_path": str(tmp_path / "nope.jsonl")}), path=sc) is None
    assert S.read_rows(sc) == []


# --- trend renderer (Phase 1) ------------------------------------------------------------------
# The trend turns the append-only log into the two watch-lines: counterexamples/cycle DOWN, eval
# score UP. Properties under test: buckets by ISO week; the direction is DERIVED (improving vs
# regressing flips with the data — non-vacuous); empty + short-span + no-scored-rows are all
# reported honestly (absence is absence), and >= 2 weeks of rows render a trend (Phase-1 acceptance).

def _row(date, *, deliverable="design", score=None, verdict="APPROVE", cx=0, laws=None, commit="c"):
    return {"date": date, "deliverable": deliverable, "score": score, "verdict": verdict,
            "counterexamples": cx, "laws_tripped": laws or [], "commit": commit, "notes": ""}


def test_render_trend_empty_is_honest():
    out = S.render_trend([])
    assert "no entries yet" in out
    assert "Absence is absence" in out          # never a fabricated healthy line
    assert S.summarize_trend([])["n"] == 0


def test_summarize_trend_buckets_by_iso_week():
    rows = [_row("2026-06-22", cx=2, verdict="BLOCK"),    # Mon — week A
            _row("2026-06-24", cx=1, verdict="APPROVE"),  # Wed — week A (same ISO week)
            _row("2026-07-01", cx=0, verdict="APPROVE")]  # Wed — week B
    s = S.summarize_trend(rows)
    assert s["n"] == 3 and s["weeks"] == 2
    wks = [b["bucket"] for b in s["buckets"]]
    assert wks == sorted(wks)                              # chronological
    week_a = next(b for b in s["buckets"] if b["cycles"] == 2)
    assert week_a["blocks"] == 1 and week_a["mean_cx"] == 1.5
    assert week_a["block_rate"] == 0.5                     # 1 BLOCK of 2 decided


def test_trend_two_week_bar_met_and_counterexamples_improving():
    # Phase-1 acceptance: >= 2 weeks of rows render a trend; counterexamples fall 3 -> 1 -> 0.
    rows = [_row("2026-06-22", cx=3, verdict="BLOCK"),
            _row("2026-06-29", cx=1, verdict="APPROVE"),
            _row("2026-07-06", cx=0, verdict="APPROVE")]
    s = S.summarize_trend(rows)
    assert s["span_days"] == 14 and s["two_week_bar"] is True and s["weeks"] == 3
    assert s["counterexamples"]["direction"] == "improving"
    out = S.render_trend(rows)
    assert "trend is meaningful" in out                    # the >= 2-week label (ASCII-safe assert)


def test_trend_counterexamples_regressing_when_rising():
    """Non-vacuity: the SAME renderer calls a rising counterexample series 'regressing'."""
    rows = [_row("2026-06-22", cx=0), _row("2026-06-29", cx=2), _row("2026-07-06", cx=5)]
    assert S.summarize_trend(rows)["counterexamples"]["direction"] == "regressing"


def test_trend_score_absence_is_honest():
    rows = [_row("2026-06-22", cx=1), _row("2026-06-29", cx=0)]   # all /qa rows -> score None
    s = S.summarize_trend(rows)
    assert s["scored_rows"] == 0
    assert "no scored rows yet" in S.render_trend(rows)           # absence, not score=0


def test_trend_scored_rows_render_and_direction_up():
    rows = [_row("2026-06-22", score=80, verdict="APPROVE"),
            _row("2026-07-06", score=92, verdict="APPROVE")]
    s = S.summarize_trend(rows)
    assert s["scored_rows"] == 2 and s["score"]["direction"] == "improving"   # 80 -> 92, up is good
    out = S.render_trend(rows)
    assert "eval score" in out and "scored row" in out


def test_trend_short_span_is_labeled_not_yet_meaningful():
    rows = [_row("2026-07-06", cx=1), _row("2026-07-07", cx=0)]
    s = S.summarize_trend(rows)
    assert s["two_week_bar"] is False
    assert "< 2 weeks" in S.render_trend(rows)


def test_trend_laws_frequency_counted():
    rows = [_row("2026-06-22", verdict="BLOCK", laws=["L3"]),
            _row("2026-06-29", verdict="BLOCK", laws=["L3", "L10"])]
    assert S.summarize_trend(rows)["laws"] == {"L3": 2, "L10": 1}   # sorted by frequency desc


def test_trend_malformed_date_bucketed_out_but_counted():
    rows = [_row("2026-06-22", cx=1), _row("not-a-date", cx=9)]
    s = S.summarize_trend(rows)
    assert s["n"] == 2 and s["weeks"] == 1     # total counts both; only the parseable date buckets


def test_trend_single_bucket_direction_is_na():
    """One week of data has no direction yet — reported as such, not a fake trend."""
    rows = [_row("2026-07-06", cx=1), _row("2026-07-07", cx=2)]   # same ISO week
    s = S.summarize_trend(rows)
    assert s["weeks"] == 1 and s["counterexamples"]["direction"] == "n/a"


def test_record_message_file_cli(tmp_path, monkeypatch):
    """`--record <file>` — the MESSAGE arm — records the reviewer's verdict from a saved verbatim copy
    of its final message: the arm for harnesses where SubagentStop never fires and the Agent-tool
    subagent transcript is empty (the Claude Agent SDK). Same conservative parser as the hook: prose
    without the per-artifact signature records nothing, and re-recording the same verdict dedupes."""
    sc = str(tmp_path / "sc.jsonl")
    monkeypatch.setenv("SCORECARD_FILE", sc)
    msg = tmp_path / "qa-verdict.md"
    msg.write_text(QA_BLOCK, encoding="utf-8")
    assert S.main(["--record", str(msg)]) == 0
    rows = S.read_rows(sc)
    assert len(rows) == 1 and rows[0]["verdict"] == "BLOCK" and rows[0]["counterexamples"] == 2
    # main-agent summary prose (no per-artifact verdict line) must record nothing
    prose = tmp_path / "prose.md"
    prose.write_text(SUMMARY_PROSE, encoding="utf-8")
    assert S.main(["--record", str(prose)]) == 0
    assert len(S.read_rows(sc)) == 1
    # dedupe: recording the same verdict file twice appends once
    assert S.main(["--record", str(msg)]) == 0
    assert len(S.read_rows(sc)) == 1


def test_record_missing_message_file_is_safe(tmp_path, monkeypatch):
    """Fail-open: a missing/unreadable message file records nothing and never raises (exit 0)."""
    monkeypatch.setenv("SCORECARD_FILE", str(tmp_path / "sc.jsonl"))
    assert S.main(["--record", str(tmp_path / "nope.md")]) == 0
    assert S.read_rows(str(tmp_path / "sc.jsonl")) == []
    assert S.main(["--record"]) == 0               # no path argument at all — still total
