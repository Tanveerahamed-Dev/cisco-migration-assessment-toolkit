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


def test_run_hook_is_total_on_bad_input(tmp_path):
    sc = str(tmp_path / "scorecard.jsonl")
    # garbage stdin, missing transcript, non-dict payload — none may raise; all append nothing.
    assert S.run_hook("not json at all", path=sc) is None
    assert S.run_hook("", path=sc) is None
    assert S.run_hook(json.dumps({"transcript_path": str(tmp_path / "nope.jsonl")}), path=sc) is None
    assert S.read_rows(sc) == []
