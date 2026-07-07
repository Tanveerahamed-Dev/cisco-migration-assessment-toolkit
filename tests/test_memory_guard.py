"""Tests for the protected-constraint memory tier (cisco_toolkit.memory_guard) — D12.

The load-bearing guarantee: a pinned safety constraint SURVIVES a memory-consolidation ("compression")
pass, even a maximally aggressive one — that is the Phase-0 acceptance criterion ("a pinned constraint
survives a simulated compression pass"). The mutants prove the guard is non-vacuous (an ordinary entry
IS dropped by the same pass; a dropped constraint IS flagged), and a reconcile keeps the pinned set
grounded in the doctrine owner (CLAUDE.md) so it cannot silently drift.
"""
import os

from cisco_toolkit import memory_guard as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSTRAINT_FM = {"metadata": {"type": "constraint", "protected": "true"}}
PROJECT_FM = {"metadata": {"type": "project"}}


def _store():
    """A store like the real one: one protected safety entry (its body pins every canonical anchor)
    plus ordinary project entries — one of them a stale duplicate a compaction would drop."""
    pinned_body = "\n".join(anchor for _, anchor in M.CANONICAL_SAFETY_CONSTRAINTS)
    return [
        M.MemoryEntry("protected-constraints", pinned_body, dict(CONSTRAINT_FM)),
        M.MemoryEntry("autonomy-brain-plan-v3", "the plan", dict(PROJECT_FM)),
        M.MemoryEntry("stale-dup", "a superseded fact", dict(PROJECT_FM)),
    ]


def test_pinned_constraint_survives_a_simulated_compression_pass():
    """THE acceptance: run a maximally aggressive pass (drop every ordinary entry) — the protected
    tier is retained verbatim."""
    store = _store()
    after = M.compact_preserving_protected(store, keep=lambda e: False)  # worst case: prune everything
    assert M.missing_protected(store, after) == []          # no protected entry lost
    survivors = {e.name for e in after}
    assert "protected-constraints" in survivors             # the safety tier survived...
    assert "stale-dup" not in survivors                     # ...and the pass really did compress


def test_compaction_is_non_vacuous_ordinary_entries_are_dropped():
    """If the pass kept everything, the survival test would be meaningless. Prove ordinary entries
    are subject to the policy while protected ones are exempt."""
    store = _store()
    # a realistic policy: drop the stale duplicate only
    after = M.compact_preserving_protected(store, keep=lambda e: e.name != "stale-dup")
    names = {e.name for e in after}
    assert names == {"protected-constraints", "autonomy-brain-plan-v3"}


def test_guard_flags_a_dropped_constraint():
    """missing_protected must NAME a safety constraint that a (buggy/greedy) pass removed — a RED
    signal, never a silent loss."""
    store = _store()
    bad_pass = [e for e in store if e.name != "protected-constraints"]   # constraint wrongly dropped
    assert M.missing_protected(store, bad_pass) == ["protected-constraints"]


def test_canonical_constraints_reconcile_against_the_doctrine_owner():
    """Every pinned constraint's anchor must be a verbatim substring of CLAUDE.md (the guardrails
    owner), so the protected set cannot drift from the doctrine it mirrors."""
    claude = open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8").read()
    assert M.reconcile_constraints(claude) == []


def test_unpinned_constraints_is_coverage_honest():
    """A store WITH the protected entry pins everything (empty); a store WITHOUT it reports the full
    set as unpinned — absence reported as absence, never a green ok."""
    store = _store()
    assert M.unpinned_constraints(store) == []
    assert len(M.unpinned_constraints(store[1:])) == len(M.CANONICAL_SAFETY_CONSTRAINTS)


def test_frontmatter_parse_and_protection_marker():
    text = ("---\n"
            "name: protected-constraints\n"
            "description: pinned safety tier\n"
            "metadata:\n"
            "  type: constraint\n"
            "  protected: true\n"
            "---\n"
            "body line one\n")
    meta = M.parse_frontmatter(text)
    assert meta["name"] == "protected-constraints"
    assert meta["metadata"]["type"] == "constraint"
    assert M.is_protected(meta) is True
    assert M.is_protected({"metadata": {"type": "project"}}) is False
    # top-level protected: true also counts; a bare project entry does not
    assert M.is_protected({"protected": "true"}) is True


def test_load_store_is_total_on_missing_dir(tmp_path):
    assert M.load_store(str(tmp_path / "nope")) == []
    # a real file round-trips into an entry with the right protection
    p = tmp_path / "c.md"
    p.write_text("---\nname: c\nmetadata:\n  protected: true\n---\nx\n", encoding="utf-8")
    entries = M.load_store(str(tmp_path))
    assert len(entries) == 1 and entries[0].protected is True
