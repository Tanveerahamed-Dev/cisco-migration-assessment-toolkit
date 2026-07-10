"""Tests for the protected-constraint memory tier (cisco_toolkit.memory_guard) — D12.

The load-bearing guarantee: a pinned safety constraint SURVIVES a memory-consolidation ("compression")
pass, even a maximally aggressive one — that is the Phase-0 acceptance criterion ("a pinned constraint
survives a simulated compression pass"). The mutants prove the guard is non-vacuous (an ordinary entry
IS dropped by the same pass; a dropped constraint IS flagged), and a reconcile keeps the pinned set
grounded in the doctrine owner (CLAUDE.md) so it cannot silently drift.

Plus the P0-1/DEC-005 pre/post-consolidation wrapper (snapshot_store/verify_snapshot + CLI): a LIVE
pass bracketed by a mechanical before/after reconcile. Portable per DEC-005 — every store here is
synthetic under tmp; pytest never references the per-machine real store.
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


# --- the pre/post-consolidation wrapper (P0-1 / DEC-005; BLK-1 route b) ---------------------------

def _disk_store(tmp_path, *, protected=True):
    """A synthetic ON-DISK store for the wrapper tests (never the per-machine real store — DEC-005).
    Protection rides on the `protected:` key alone so a single flip genuinely unprotects."""
    store = tmp_path / "agent-memory"
    store.mkdir(exist_ok=True)
    body = "\n".join(anchor for _, anchor in M.CANONICAL_SAFETY_CONSTRAINTS)
    (store / "protected-constraints.md").write_text(
        "---\nname: protected-constraints\nmetadata:\n  protected: " + ("true" if protected else "false")
        + "\n---\n" + body + "\n", encoding="utf-8")
    (store / "ordinary-fact.md").write_text(
        "---\nname: ordinary-fact\nmetadata:\n  type: project\n---\nan ordinary fact\n", encoding="utf-8")
    (store / "MEMORY.md").write_text(
        "# Memory Index\n\n- [Protected constraints](protected-constraints.md) - pinned (D12)\n"
        "- [Ordinary fact](ordinary-fact.md) - a fact\n", encoding="utf-8")
    return store


def test_wrapper_clean_pass_and_legitimate_compression_ok(tmp_path):
    """Non-vacuity mirror: the wrapper must NOT cry wolf — a pass that compresses an ORDINARY entry
    (the whole point of consolidation) verifies ok as long as the protected tier survived verbatim."""
    store = _disk_store(tmp_path)
    snap = M.snapshot_store(str(store))
    assert snap["store_present"] and any(e["protected"] for e in snap["entries"])
    os.remove(str(store / "ordinary-fact.md"))               # legitimate compression
    rep = M.verify_snapshot(snap, str(store))
    assert rep["ok"] and not rep["dropped"] and not rep["rewritten"] and not rep["unindexed"]


def test_wrapper_flags_dropped_protected_entry(tmp_path):
    store = _disk_store(tmp_path)
    snap = M.snapshot_store(str(store))
    os.remove(str(store / "protected-constraints.md"))       # the pass wrongly deleted the tier
    rep = M.verify_snapshot(snap, str(store))
    assert not rep["ok"] and rep["dropped"] == ["protected-constraints"]


def test_wrapper_flags_rewritten_protected_entry(tmp_path):
    """D12 says verbatim: ANY byte change to a protected file is a violation — here the frontmatter
    flip, which also un-pins every canonical anchor (both signals must fire)."""
    store = _disk_store(tmp_path)
    snap = M.snapshot_store(str(store))
    p = store / "protected-constraints.md"
    p.write_text(p.read_text(encoding="utf-8").replace("protected: true", "protected: false"),
                 encoding="utf-8")
    rep = M.verify_snapshot(snap, str(store))
    assert not rep["ok"]
    assert "protected-constraints" in rep["rewritten"]
    assert len(rep["unpinned"]) == len(M.CANONICAL_SAFETY_CONSTRAINTS)


def test_wrapper_flags_index_prune(tmp_path):
    """BLK-1 route (d): the file survives but MEMORY.md no longer references it — orphaned from
    session-start re-surfacing, flagged independently of drop/rewrite."""
    store = _disk_store(tmp_path)
    snap = M.snapshot_store(str(store))
    (store / "MEMORY.md").write_text("# Memory Index\n\n- [Ordinary fact](ordinary-fact.md) - a fact\n",
                                     encoding="utf-8")
    rep = M.verify_snapshot(snap, str(store))
    assert not rep["ok"] and rep["unindexed"] == ["protected-constraints"]
    assert not rep["dropped"] and not rep["rewritten"]       # the index loss alone gates ok


def test_wrapper_refuses_vacuous_baseline(tmp_path):
    """A baseline that pinned nothing (absent store, or no protected entries) must be REFUSED —
    absence of protection can never become a green verify."""
    absent = M.snapshot_store(str(tmp_path / "no-such-store"))
    assert absent["store_present"] is False
    rep = M.verify_snapshot(absent, str(tmp_path / "no-such-store"))
    assert rep["vacuous"] and not rep["ok"]
    store = _disk_store(tmp_path, protected=False)           # store exists but pins nothing
    rep2 = M.verify_snapshot(M.snapshot_store(str(store)), str(store))
    assert rep2["vacuous"] and not rep2["ok"]


def test_wrapper_cli_roundtrip_and_store_resolution(tmp_path, monkeypatch, capsys):
    store = _disk_store(tmp_path)
    baseline = tmp_path / "baseline.json"
    assert M.main(["snapshot", "--store", str(store), "--out", str(baseline)]) == 0
    assert M.main(["verify", str(baseline), "--store", str(store)]) == 0
    os.remove(str(store / "protected-constraints.md"))
    assert M.main(["verify", str(baseline), "--store", str(store)]) == 4      # loss -> RED exit
    assert M.main(["verify", str(tmp_path / "no-baseline.json"), "--store", str(store)]) == 4
    # resolution: explicit arg > $AGENT_MEMORY_DIR > default (pytest never resolves to the default)
    monkeypatch.setenv(M.AGENT_MEMORY_DIR_ENV, str(store))
    assert M.resolve_store_dir() == str(store)
    assert M.resolve_store_dir("explicit-wins") == "explicit-wins"
