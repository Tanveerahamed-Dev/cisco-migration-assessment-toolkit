"""Tests for the learnings discipline (cisco_toolkit.learnings).

The guard has two jobs: keep the REAL ``docs/quality/learnings.md`` disciplined (under 100 lines,
every entry cited, no self-assessment) so it stays a lean, verifiable SessionStart read; and be
non-vacuous — an uncited claim, a coasting phrase, or an over-length file must each be flagged, or the
discipline is theatre.
"""
import os

from cisco_toolkit import learnings as L

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNINGS = os.path.join(ROOT, "docs", "quality", "learnings.md")


def test_real_learnings_store_is_disciplined():
    """The committed store must pass its own discipline: exists, under 100 lines, every entry cited,
    no self-assessment language."""
    violations = L.lint_file(LEARNINGS)
    assert violations == [], "learnings.md breaks discipline:\n  - " + "\n  - ".join(violations)


def test_real_store_has_entries_and_stays_lean():
    text = open(LEARNINGS, encoding="utf-8").read()
    assert len(text.splitlines()) < 100
    assert len(L.parse_learnings(text)) >= 3          # it is a real store, not just a header


def test_linter_flags_uncited_learning():
    v = L.lint_learnings("# h\n- the parser handles every case cleanly\n")
    assert any("uncited" in x for x in v)


def test_linter_flags_self_assessment():
    v = L.lint_learnings("# h\n- great progress on the eval harness. Evidence: cisco_toolkit/eval_harness.py\n")
    assert any("coasting" in x or "self-assessment" in x for x in v)
    # even WITH a citation, the coasting phrase is a violation — a fact, not morale
    assert any("great progress" in x for x in v)


def test_linter_flags_overlength_store():
    over = "# h\n" + "\n".join(f"- fact {i}. Evidence: x.py" for i in range(120))
    assert any("too long" in x for x in L.lint_learnings(over))


def test_empty_store_is_coverage_honest_not_a_violation():
    """A store with no learnings yet is valid — absence is absence, never a fabricated defect."""
    assert L.lint_learnings("# Learnings\n\nNothing distilled yet.\n") == []


def test_entry_groups_indented_evidence_line():
    """A learning whose Evidence pointer is on an indented continuation line is ONE cited entry."""
    text = ("# h\n"
            "- reconcile is empty both when clean and when nothing is published.\n"
            "  Evidence: cisco_toolkit/eval_harness.py\n")
    entries = L.parse_learnings(text)
    assert len(entries) == 1
    assert L.lint_learnings(text) == []               # the indented citation satisfies the rule


def test_lint_file_missing_is_reported():
    v = L.lint_file(os.path.join(ROOT, "docs", "quality", "does-not-exist.md"))
    assert v and "not found" in v[0]


def test_citation_forms_accepted():
    """A file path, a commit sha, and an explicit Evidence marker all count as citations."""
    for cite in ("cisco_toolkit/ssot.py", "commit 034b416", "Evidence: the golden test", "tests/test_x.py"):
        assert L.lint_learnings(f"# h\n- a real fact ({cite})\n") == [], cite


def test_linter_flags_duplicate_learning():
    """Two entries making the same claim are an ADD where the SelfMem write-vocab (ADR-0003 §3b) says
    REPLACE/MERGE — 'replace stale, don't accumulate'. High-precision: the normalized first-line claim,
    so backtick / trailing-punctuation / case differences still count as the same claim."""
    text = ("# h\n"
            "- `foo()` returns [] on empty input. Evidence: cisco_toolkit/foo.py\n"
            "- foo() returns [] on empty input — Evidence: tests/test_foo.py\n")
    v = L.lint_learnings(text)
    assert any("duplicate" in x.lower() for x in v), v


def test_distinct_learnings_sharing_a_citation_are_not_duplicates():
    """Two genuinely different claims are NOT duplicates even when they cite the same file — the rule
    keys on the claim, not the evidence pointer (else it would punish good, well-cited learnings)."""
    text = ("# h\n"
            "- `foo()` returns [] on empty input. Evidence: cisco_toolkit/foo.py\n"
            "- `foo()` raises on a non-dict argument. Evidence: cisco_toolkit/foo.py\n")
    assert L.lint_learnings(text) == []
