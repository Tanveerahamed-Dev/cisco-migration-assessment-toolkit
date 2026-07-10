"""P0-2 / gap G-002 — the mechanical proposer≠verifier wedge + the read-only roster pin.

Before P0-2 the doctrine "proposer ≠ verifier" was enforced only by prompt text. Two mechanical
clauses now hold it, and this file is their proof:

1. **The scorecard wedge** (cisco_toolkit.scorecard): rows carry an optional provenance pair
   (``authored_by`` / ``reviewed_by``); the explicit record arms accept ``--authored-by`` /
   ``--reviewed-by`` and REFUSE (exit 2, reason printed, nothing appended) when the two match
   non-empty — a self-review can never mint a quality row. ``append_row`` backstops the same rule
   at the persistence layer. Absent identities stay ``null`` and pre-P0-2 rows without the keys
   stay valid (back-compat; the wedge trips only on a positive self-review signal).
2. **The roster pin**: the five read-only analyst agents' frontmatter ``tools:`` allowlists must
   never gain a write-capable tool (Edit / Write / MultiEdit / NotebookEdit) — pinning in code what
   was previously prose. A missing file or missing ``tools:`` line also fails: no allowlist means
   the agent inherits ALL tools, which is a louder version of the same regression.

Honest residual (declared, not hidden): the wedge checks *declared* identity strings — an agent
could misdeclare, and the roster pin reads the agent definition, not the running process. Both
raise the bar; the hard boundary remains the OS/permission layer (CLAUDE.md trust-boundary note).
"""
import json
import re
from pathlib import Path

import pytest

from cisco_toolkit import scorecard as S

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# The read-only analyst roster (CLAUDE.md "Specialist roster" — the agents that must never author).
READONLY_ANALYSTS = (
    "assessment-analyst",
    "config-security-auditor",
    "topology-reachability-analyst",
    "nrfu-validator",
    "deliverable-qa-reviewer",
)
# Edit/Write are the pair the plan names; MultiEdit/NotebookEdit are the same capability class.
WRITE_CAPABLE = {"edit", "write", "multiedit", "notebookedit"}

# A minimal real reviewer verdict (per-artifact signature) the record arms accept.
VERDICT = "runbook.docx — BLOCK\nFindings:\nrunbook §2 | 60 switches | snapshot = 58 | High\n"


# --- 1a. the pure wedge ---------------------------------------------------------------------------

def test_check_independence_refuses_only_a_nonempty_match():
    reason = S.check_independence("design-author", "design-author")
    assert reason is not None and "refused" in reason and "self-review" in reason
    # case- and whitespace-insensitive: a cosmetic respelling is not independence
    assert S.check_independence(" Design-Author ", "design-author") is not None
    # distinct identities pass
    assert S.check_independence("design-author", "deliverable-qa-reviewer") is None
    # absent/empty identities never refuse (optional pair — back-compat, not a metadata gate)
    assert S.check_independence(None, None) is None
    assert S.check_independence("", "") is None
    assert S.check_independence("design-author", None) is None
    assert S.check_independence(None, "deliverable-qa-reviewer") is None
    assert S.check_independence("   ", "   ") is None


# --- 1b. the --record message arm ------------------------------------------------------------------

def test_record_refuses_self_review(tmp_path, monkeypatch, capsys):
    """ACCEPTANCE (P0-2): a --record attempt with authored_by == reviewed_by is refused with a clear
    message, exits 2, and appends nothing."""
    sc = tmp_path / "sc.jsonl"
    monkeypatch.setenv("SCORECARD_FILE", str(sc))
    msg = tmp_path / "verdict.md"
    msg.write_text(VERDICT, encoding="utf-8")
    rc = S.main(["--record", str(msg),
                 "--authored-by", "design-author", "--reviewed-by", "design-author"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "refused" in out and "authored_by == reviewed_by" in out and "self-review" in out
    assert S.read_rows(str(sc)) == []              # nothing minted

def test_record_refusal_is_case_and_space_insensitive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCORECARD_FILE", str(tmp_path / "sc.jsonl"))
    msg = tmp_path / "verdict.md"
    msg.write_text(VERDICT, encoding="utf-8")
    rc = S.main(["--record", str(msg),
                 "--authored-by", " Design-Author ", "--reviewed-by", "design-author"])
    assert rc == 2 and "refused" in capsys.readouterr().out
    assert S.read_rows(str(tmp_path / "sc.jsonl")) == []

def test_record_with_distinct_identities_persists_the_pair(tmp_path, monkeypatch, capsys):
    sc = tmp_path / "sc.jsonl"
    monkeypatch.setenv("SCORECARD_FILE", str(sc))
    msg = tmp_path / "verdict.md"
    msg.write_text(VERDICT, encoding="utf-8")
    rc = S.main(["--record", str(msg),
                 "--authored-by", "design-author", "--reviewed-by", "deliverable-qa-reviewer"])
    assert rc == 0
    rows = S.read_rows(str(sc))
    assert len(rows) == 1
    assert rows[0]["authored_by"] == "design-author"
    assert rows[0]["reviewed_by"] == "deliverable-qa-reviewer"
    out = capsys.readouterr().out                   # the echo shows the wedge saw the pair
    assert "authored_by=design-author" in out and "reviewed_by=deliverable-qa-reviewer" in out

def test_record_without_identities_is_backcompat(tmp_path, monkeypatch):
    """No flags -> recorded exactly as before, pair emitted as honest null (never blocked for
    missing metadata)."""
    sc = tmp_path / "sc.jsonl"
    monkeypatch.setenv("SCORECARD_FILE", str(sc))
    msg = tmp_path / "verdict.md"
    msg.write_text(VERDICT, encoding="utf-8")
    assert S.main(["--record", str(msg)]) == 0
    rows = S.read_rows(str(sc))
    assert len(rows) == 1
    assert rows[0]["authored_by"] is None and rows[0]["reviewed_by"] is None


# --- 1c. the --record-from transcript arm ----------------------------------------------------------

def _write_transcript(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant",
                            "message": {"role": "assistant",
                                        "content": [{"type": "text", "text": text}]}}) + "\n")

def test_record_from_refuses_self_review(tmp_path, monkeypatch, capsys):
    """The wedge covers BOTH explicit record arms — no bypass via the transcript arm."""
    sc = tmp_path / "sc.jsonl"
    monkeypatch.setenv("SCORECARD_FILE", str(sc))
    tp = tmp_path / "t.jsonl"
    _write_transcript(str(tp), VERDICT)
    rc = S.main(["--record-from", str(tp),
                 "--authored-by", "nrfu-validator", "--reviewed-by", "nrfu-validator"])
    assert rc == 2 and "refused" in capsys.readouterr().out
    assert S.read_rows(str(sc)) == []

def test_record_from_with_distinct_identities_persists_the_pair(tmp_path, monkeypatch):
    sc = tmp_path / "sc.jsonl"
    monkeypatch.setenv("SCORECARD_FILE", str(sc))
    tp = tmp_path / "t.jsonl"
    _write_transcript(str(tp), VERDICT)
    assert S.main(["--record-from", str(tp),
                   "--authored-by", "main", "--reviewed-by", "deliverable-qa-reviewer"]) == 0
    rows = S.read_rows(str(sc))
    assert len(rows) == 1 and rows[0]["reviewed_by"] == "deliverable-qa-reviewer"


# --- 1d. persistence-layer backstop + schema back-compat -------------------------------------------

def test_append_row_backstop_refuses_self_review(tmp_path):
    """A programmatic caller that skips the CLI still cannot mint a self-review row."""
    path = str(tmp_path / "sc.jsonl")
    row = S.parse_qa_verdict(VERDICT, date="2026-07-10", commit="abc1234")
    row["authored_by"] = row["reviewed_by"] = "design-author"
    assert S.append_row(row, path) is False
    assert S.read_rows(path) == []

def test_schema_gains_optional_provenance_pair_and_old_rows_stay_valid(tmp_path):
    assert "authored_by" in S.SCHEMA_KEYS and "reviewed_by" in S.SCHEMA_KEYS
    path = tmp_path / "sc.jsonl"
    # a pre-P0-2 row on disk (no provenance keys) stays readable next to a new-shape row
    legacy = {"date": "2026-07-07", "deliverable": "design", "score": None, "verdict": "APPROVE",
              "judge_tnr": None, "counterexamples": 0, "laws_tripped": [], "commit": "old1234",
              "notes": "pre-P0-2 row"}
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    row = S.parse_qa_verdict(VERDICT, date="2026-07-10", commit="abc1234")
    row["authored_by"], row["reviewed_by"] = "design-author", "deliverable-qa-reviewer"
    assert S.append_row(row, str(path)) is True
    rows = S.read_rows(str(path))
    assert len(rows) == 2
    assert "authored_by" not in rows[0]            # legacy shape untouched, still valid
    assert rows[1]["authored_by"] == "design-author"
    assert list(rows[1].keys()) == list(S.SCHEMA_KEYS)
    # the trend renderer digests the mixed-shape log without complaint
    assert S.summarize_trend(rows)["n"] == 2


# --- 2. the read-only roster pin -------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"(?s)\A---\s*\n(.*?)\n---")

def _agent_tools(text):
    """The frontmatter ``tools:`` allowlist as a list of tool names, or None if the file has no
    frontmatter / no inline ``tools:`` line. Inline comma form only ("tools: Read, Grep, ...") —
    the form every agent in this repo uses; a format change fails the pin loudly, which is the
    correct failure mode for a guard (a human re-points it deliberately)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    for line in m.group(1).splitlines():
        km = re.match(r"^tools:\s*(.*)$", line)
        if km:
            return [t.strip() for t in km.group(1).split(",") if t.strip()]
    return None

@pytest.mark.parametrize("agent", READONLY_ANALYSTS)
def test_readonly_analyst_roster_is_pinned(agent):
    """The five analyst agents stay read-only: their tools: allowlist never gains a write-capable
    tool. Previously prompt-text only — this is the code pin (P0-2/G-002)."""
    p = AGENTS_DIR / f"{agent}.md"
    assert p.is_file(), (
        f"{agent}: agent file missing at {p} — the read-only roster changed; "
        f"update READONLY_ANALYSTS deliberately, don't let the pin rot")
    tools = _agent_tools(p.read_text(encoding="utf-8"))
    assert tools, (
        f"{agent}: no inline `tools:` allowlist in frontmatter — without one the agent inherits "
        f"ALL tools (incl. Edit/Write); restore the explicit read-only allowlist")
    gained = sorted(t for t in tools if t.casefold() in WRITE_CAPABLE)
    assert not gained, (
        f"{agent}: read-only analyst gained write-capable tool(s) {gained} — this breaks the "
        f"proposer != verifier roster (P0-2/G-002); authors and verifiers must stay disjoint")

def test_roster_pin_parser_is_not_vacuous():
    """The pin must be failable: the parser sees a planted Edit, and sees the real files' tools."""
    planted = "---\nname: x\ntools: Read, Edit, Bash\n---\nbody"
    assert "Edit" in _agent_tools(planted)
    assert _agent_tools("no frontmatter at all") is None
    assert _agent_tools("---\nname: x\n---\nbody") is None      # frontmatter but no tools: line
    # and at least one real analyst file parses to a non-empty allowlist (paths are right)
    real = _agent_tools((AGENTS_DIR / "deliverable-qa-reviewer.md").read_text(encoding="utf-8"))
    assert real and "Read" in real
