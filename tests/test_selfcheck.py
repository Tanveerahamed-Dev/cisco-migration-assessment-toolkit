"""Tests for the agent-system self-check (cisco_toolkit.selfcheck) — Phase 4.

The self-check is itself a guard, so it must be NON-VACUOUS: a deleted or gutted guard reads RED (not
silently gone), a missing substrate reads RED, an un-evaluable check reads UNKNOWN (never GREEN), and a
healthy repo reads GREEN. Root, now AND memory_dir are injected so every case is deterministic —
per DEC-005, portable pytest must NEVER reference the per-machine real agent-memory store (the
runtime default path is the pin; here every store is synthetic, under tmp or via $AGENT_MEMORY_DIR).
"""
import os

from cisco_toolkit import memory_guard as MG
from cisco_toolkit import selfcheck as SC

_REAL_LEARNINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "docs", "quality", "learnings.md")


def _quality_dir(root):
    q = os.path.join(root, "docs", "quality")
    os.makedirs(q, exist_ok=True)
    return q


def _doctrine_root(tmp_path):
    """A portable stand-in for the repo root: CLAUDE.md carries every canonical anchor verbatim, so
    the protected-artifact reconcile never reads the real repo's doctrine from a unit test."""
    root = str(tmp_path)
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS))
    return root


def _protected_store(tmp_path, *, protected=True, anchors=True, indexed=True):
    """A synthetic agent-memory store shaped like the real one. The artifact marks protection via the
    `protected:` frontmatter key ONLY (no `type: constraint`), so flipping that single key genuinely
    unprotects it — the real artifact carries both markers, which only makes it harder to unprotect."""
    store = tmp_path / "agent-memory"
    store.mkdir(exist_ok=True)
    body = ("\n".join(anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS)
            if anchors else "anchors edited out\n")
    (store / "protected-constraints.md").write_text(
        "---\nname: protected-constraints\ndescription: pinned safety tier\n"
        "metadata:\n  node_type: memory\n  protected: " + ("true" if protected else "false")
        + "\n---\n" + body + "\n", encoding="utf-8")
    line = ("- [Protected constraints](protected-constraints.md) - pinned safety tier (D12)\n"
            if indexed else "- [Other fact](other-fact.md) - something else\n")
    (store / "MEMORY.md").write_text("# Memory Index\n\n" + line, encoding="utf-8")
    return str(store)


def _write_guards(root, *, gut=None, drop=None):
    """Create every guard file with a real assertion, optionally gutting/dropping one (for RED cases)."""
    gut, drop = gut or set(), drop or set()
    for rel in SC.GUARD_FILES:
        p = os.path.join(root, rel)
        if rel in drop:
            if os.path.exists(p):
                os.remove(p)                     # ensure absent (a prior call may have created it)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        body = "def test_x():\n    pass\n" if rel in gut else "def test_x():\n    assert True\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)


# --- individual checks -------------------------------------------------------------------------

def test_scorecard_substrate_states(tmp_path):
    root = str(tmp_path)
    q = _quality_dir(root)
    # missing -> RED
    assert SC.check_scorecard_substrate(root)["status"] == SC.RED
    # present + empty -> GREEN, honest about 0 entries
    open(os.path.join(q, "scorecard.jsonl"), "w").close()
    c = SC.check_scorecard_substrate(root)
    assert c["status"] == SC.GREEN and "0 entries" in c["detail"]
    # present + rows -> GREEN with count
    with open(os.path.join(q, "scorecard.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"a":1}\n{"a":2}\n')
    assert "2 verdict row" in SC.check_scorecard_substrate(root)["detail"]


def test_pir_substrate_counts_only_real_toward_floor(tmp_path):
    """The D11 floor is REAL-only: a surrogate (fault-injected) row populates the descriptive gap but must
    NOT read as tune-eligible, while a REAL alias (`pir`) does — and the readout normalizes via the same
    `_norm_source` the gate uses, so the health line can never drift from the gate it reports on."""
    root = str(tmp_path)
    q = _quality_dir(root)
    with open(os.path.join(q, "pir_outcomes.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"source_class":"fault-injected","predicted":"READY","actual":"clean"}\n')
        f.write('{"source_class":"pir","predicted":"READY","actual":"incident"}\n')      # alias -> REAL
    c = SC.check_pir_substrate(root)
    assert c["status"] == SC.GREEN
    assert "2 labeled outcome(s), 1 REAL" in c["detail"]      # surrogate excluded; alias normalized to REAL


def test_guards_nonvacuous_detects_missing_and_gutted(tmp_path):
    root = str(tmp_path)
    _write_guards(root)
    assert SC.check_guards_nonvacuous(root)["status"] == SC.GREEN
    # a guard with no assertion -> RED (non-vacuity: a skipped/gutted test is red)
    _write_guards(root, gut={"tests/test_scorecard.py"})
    c = SC.check_guards_nonvacuous(root)
    assert c["status"] == SC.RED and "no assertions" in c["detail"]
    # a deleted guard -> RED
    _write_guards(root, drop={"tests/test_council.py"})
    c2 = SC.check_guards_nonvacuous(root)
    assert c2["status"] == SC.RED and "missing" in c2["detail"]


def test_graph_fresh_stale_absent(tmp_path):
    root = str(tmp_path)
    gdir = os.path.join(root, "graphify-out")
    os.makedirs(gdir)
    gpath = os.path.join(gdir, "graph.json")
    open(gpath, "w").close()
    mtime = os.path.getmtime(gpath)
    assert SC.check_graph_fresh(root, now=mtime + 3600)["status"] == SC.GREEN          # 1h old
    assert SC.check_graph_fresh(root, now=mtime + 100 * 86400)["status"] == SC.RED     # 100d old
    os.remove(gpath)
    assert SC.check_graph_fresh(root, now=mtime)["status"] == SC.UNKNOWN               # absent -> UNKNOWN, not GREEN


def test_learnings_discipline(tmp_path):
    root = str(tmp_path)
    q = _quality_dir(root)
    # missing -> RED
    assert SC.check_learnings_discipline(root)["status"] == SC.RED
    # the real file -> GREEN (test_learnings.py keeps it disciplined)
    import shutil
    shutil.copyfile(_REAL_LEARNINGS, os.path.join(q, "learnings.md"))
    assert SC.check_learnings_discipline(root)["status"] == SC.GREEN
    # a clearly-violating file (over-length + uncited + coasting) -> RED
    with open(os.path.join(q, "learnings.md"), "w", encoding="utf-8") as f:
        f.write("\n".join("- unverified claim of great progress" for _ in range(150)))
    assert SC.check_learnings_discipline(root)["status"] == SC.RED


# --- the protected-tier artifact pin (P0-1 / DEC-005; gap G-001, evidence BLK-1) -----------------

def test_protected_artifact_green_when_pinned(tmp_path):
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path))
    assert c["status"] == SC.GREEN and "pinned" in c["detail"]


def test_protected_artifact_frontmatter_flip_goes_red(tmp_path):
    """THE P0-1 acceptance: flipping `protected: true -> false` in the store makes the check RED."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path, protected=False))
    assert c["status"] == SC.RED
    assert "no longer marks the artifact protected" in c["detail"]


def test_protected_artifact_store_absent_is_signal_absent_never_green(tmp_path):
    """THE second P0-1 acceptance: a machine without the store reads explicit signal_absent
    (UNKNOWN) — coverage-honesty forbids rendering an unobserved store as healthy."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=str(tmp_path / "no-such-store"))
    assert c["status"] == SC.UNKNOWN
    assert "signal_absent" in c["detail"]
    assert c["status"] != SC.GREEN


def test_protected_artifact_dropped_artifact_goes_red(tmp_path):
    """Deleting protected-constraints.md from a live store is the exact loss class memory_guard
    names (missing_protected) — RED, never a silent gap."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path)
    os.remove(os.path.join(store, "protected-constraints.md"))
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "dropped" in c["detail"]


def test_protected_artifact_gutted_body_goes_red(tmp_path):
    """Frontmatter intact but the canonical anchors edited out of the body — drift, not deletion —
    must still be RED (unpinned_constraints is the detector)."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path, anchors=False))
    assert c["status"] == SC.RED and "unpinned" in c["detail"]


def test_protected_artifact_index_prune_goes_red(tmp_path):
    """BLK-1 route (d): a MEMORY.md prune that drops the index line orphans the fact from
    session-start re-surfacing — RED; a missing index entirely is the same loss class."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path, indexed=False)
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "no longer indexes" in c["detail"]
    os.remove(os.path.join(store, "MEMORY.md"))
    c2 = SC.check_protected_artifact(root, memory_dir=store)
    assert c2["status"] == SC.RED and "index absent" in c2["detail"]


def test_protected_artifact_doctrine_drift_goes_red(tmp_path):
    """An anchor no longer verbatim in CLAUDE.md (the doctrine owner) is drift (reconcile_constraints)
    — RED even with an intact store; and verified drift outranks an absent store's UNKNOWN."""
    root = str(tmp_path)
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS[1:]))  # 1st anchor gone
    store = _protected_store(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "doctrine drift" in c["detail"]
    c2 = SC.check_protected_artifact(root, memory_dir=str(tmp_path / "no-such-store"))
    assert c2["status"] == SC.RED and "absent" in c2["detail"]


def test_protected_artifact_env_var_points_the_store(tmp_path, monkeypatch):
    """The DEC-005 portability contract: $AGENT_MEMORY_DIR relocates the store; an explicit argument
    beats the env; without either, THIS test never resolves to the per-machine default."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path)
    monkeypatch.setenv(SC.AGENT_MEMORY_DIR_ENV, store)
    assert SC.check_protected_artifact(root)["status"] == SC.GREEN
    monkeypatch.setenv(SC.AGENT_MEMORY_DIR_ENV, str(tmp_path / "relocated-away"))
    assert SC.check_protected_artifact(root, memory_dir=store)["status"] == SC.GREEN   # arg > env
    assert SC.check_protected_artifact(root)["status"] == SC.UNKNOWN                   # env honored


# --- the aggregate ------------------------------------------------------------------------------

def _healthy_root(tmp_path, now_ref):
    root = _doctrine_root(tmp_path)                 # CLAUDE.md doctrine for the protected reconcile
    q = _quality_dir(root)
    for name in ("scorecard.jsonl", "pir_outcomes.jsonl", "nightly_runs.jsonl"):
        open(os.path.join(q, name), "w").close()
    import shutil
    shutil.copyfile(_REAL_LEARNINGS, os.path.join(q, "learnings.md"))
    _write_guards(root)
    gdir = os.path.join(root, "graphify-out")
    os.makedirs(gdir)
    open(os.path.join(gdir, "graph.json"), "w").close()
    return root


def test_run_selfcheck_all_green(tmp_path):
    root = _healthy_root(tmp_path, None)
    gpath = os.path.join(root, "graphify-out", "graph.json")
    rep = SC.run_selfcheck(root, now=os.path.getmtime(gpath) + 3600,
                           memory_dir=_protected_store(tmp_path))
    assert rep["verdict"] == "GREEN" and rep["summary"]["red"] == 0 and rep["summary"]["unknown"] == 0


def test_run_selfcheck_absent_graph_is_green_with_gaps(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "graphify-out", "graph.json"))     # worktree: no graph
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    assert rep["verdict"] == "GREEN-with-gaps" and rep["summary"]["unknown"] == 1
    assert rep["summary"]["red"] == 0                                # unknown is disclosed, not counted red


def test_run_selfcheck_absent_store_is_green_with_gaps_not_green(tmp_path):
    """The P0-1 aggregate acceptance: an otherwise-healthy system with no reachable agent-memory
    store must disclose the gap (signal_absent -> GREEN-with-gaps), never render plain GREEN."""
    root = _healthy_root(tmp_path, None)
    gpath = os.path.join(root, "graphify-out", "graph.json")
    rep = SC.run_selfcheck(root, now=os.path.getmtime(gpath) + 3600,
                           memory_dir=str(tmp_path / "no-such-store"))
    assert rep["verdict"] == "GREEN-with-gaps" and rep["summary"]["red"] == 0
    byname = {c["name"]: c for c in rep["checks"]}
    assert byname["protected_artifact"]["status"] == SC.UNKNOWN
    assert "signal_absent" in byname["protected_artifact"]["detail"]


def test_run_selfcheck_red_leads(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "docs", "quality", "scorecard.jsonl"))   # break one guard
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    assert rep["verdict"] == "RED"
    assert rep["leads"] and rep["leads"][0]["name"] == "scorecard_substrate"
    assert "scorecard_substrate" in SC.render(rep)
