"""Tests for the agent-system self-check (cisco_toolkit.selfcheck) — Phase 4.

The self-check is itself a guard, so it must be NON-VACUOUS: a deleted or gutted guard reads RED (not
silently gone), a missing substrate reads RED, an un-evaluable check reads UNKNOWN (never GREEN), and a
healthy repo reads GREEN. Root + now are injected so every case is deterministic.
"""
import os

from cisco_toolkit import selfcheck as SC

_REAL_LEARNINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "docs", "quality", "learnings.md")


def _quality_dir(root):
    q = os.path.join(root, "docs", "quality")
    os.makedirs(q, exist_ok=True)
    return q


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


# --- the aggregate ------------------------------------------------------------------------------

def _healthy_root(tmp_path, now_ref):
    root = str(tmp_path)
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
    rep = SC.run_selfcheck(root, now=os.path.getmtime(gpath) + 3600)
    assert rep["verdict"] == "GREEN" and rep["summary"]["red"] == 0 and rep["summary"]["unknown"] == 0


def test_run_selfcheck_absent_graph_is_green_with_gaps(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "graphify-out", "graph.json"))     # worktree: no graph
    rep = SC.run_selfcheck(root, now=1.0)
    assert rep["verdict"] == "GREEN-with-gaps" and rep["summary"]["unknown"] == 1
    assert rep["summary"]["red"] == 0                                # unknown is disclosed, not counted red


def test_run_selfcheck_red_leads(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "docs", "quality", "scorecard.jsonl"))   # break one guard
    rep = SC.run_selfcheck(root, now=1.0)
    assert rep["verdict"] == "RED"
    assert rep["leads"] and rep["leads"][0]["name"] == "scorecard_substrate"
    assert "scorecard_substrate" in SC.render(rep)
