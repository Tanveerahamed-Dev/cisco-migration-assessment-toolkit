"""Invariant guard for the graphify knowledge graph (``graphify-out/graph.json``).

Dimension-A gap (docs/architect-understanding-2026-07-10.md): the live graph - the tool CLAUDE.md
says to consult FIRST for codebase questions - had NO test validating its schema, its size, or the
central **AST-only / no-LLM-derived-nodes doctrine** (CLAUDE.md graphify section). ``test_doctrine_graph``
guards a *different* graph (the in-code doctrine/design_advisor projection), not this one. This closes
that gap: it makes the doctrine a RED test on the machine where the graph lives.

Coverage-honest by construction (the graph is gitignored / owner-machine-only - CLAUDE.md):
* graph unreachable (clean clone / CI) -> SKIP, never a fabricated pass;
* a degenerate/partial graph (the worktree trap - a linked worktree's own ``graphify update`` can
  leave a ~100-node stub) -> SKIP with the count stated, never a false FAIL;
* a SUBSTANTIAL graph (the real owner-machine build) -> the invariants are asserted.

The locator is reused from :func:`cisco_toolkit.d10_eval_set.find_graph_json` (one owner, DRY) - it is
already worktree-aware (resolves the main checkout via ``git rev-parse --git-common-dir``).
"""
from __future__ import annotations

import os
import re

import pytest

from cisco_toolkit.d10_eval_set import find_graph_json, load_graph_settled

# A real graph is ~7.5k nodes; the degenerate worktree partials observed were ~76-122. This floor
# cleanly separates "the full owner-machine graph" (assert) from "a worktree stub" (skip) - it is a
# SKIP threshold, not an assertion, so the worktree trap can never turn into a red build.
_SUBSTANTIAL_FLOOR = 1000

# The AST-only doctrine, encoded as an ALLOWLIST (fail-closed): every node originates from the offline
# AST extractor (``ast``) or is an un-tagged structural node (``None`` - e.g. YAML-workflow / release
# nodes). Any OTHER ``_origin`` marker (an LLM/label/semantic origin) is a doctrine violation and must
# trip review. If a new *non-LLM* extractor is ever added, widen this set deliberately - never loosen
# it to silence a surprise. Owner of the doctrine: CLAUDE.md graphify section.
_ALLOWED_ORIGINS = {"ast", None}

# The closed node-type enum and the edge-relation vocabulary the extractor emits (read from the live
# graph 2026-07-11). A test failure here means the schema grew - reconcile deliberately, don't paper over.
_KNOWN_FILE_TYPES = {"code", "rationale", "document", "concept"}
_KNOWN_RELATIONS = {
    "calls", "contains", "defines", "imports", "imports_from", "indirect_call",
    "inherits", "method", "rationale_for", "re_exports", "references", "uses",
}
_REQUIRED_NODE_KEYS = {"id", "label", "file_type", "community", "source_file", "norm_label"}


def _load_graph():
    """The real graph as a dict, or a pytest SKIP - the coverage-honest gate every test shares."""
    path = find_graph_json()
    if not path:
        pytest.skip("graph.json not reachable (clean clone / CI) - the graph is gitignored and "
                    "owner-machine-only; invariants are checked where the graph lives")
    graph, unsettled = load_graph_settled(path)
    if unsettled:
        # background git-hook rebuilds rewrite this file non-atomically under us; a torn read is a
        # spurious ERROR, not an invariant violation
        pytest.skip(f"graph.json could not be read as a settled whole: {unsettled}")
    n = len(graph.get("nodes", []))
    if n < _SUBSTANTIAL_FLOOR:
        pytest.skip(f"degenerate/partial graph ({n} nodes < {_SUBSTANTIAL_FLOOR}) - the worktree stub, "
                    "not the full owner-machine graph; the real build is asserted on the main checkout")
    return graph, path


def test_graph_schema_has_toplevel_keys():
    graph, _ = _load_graph()
    for key in ("nodes", "links", "built_at_commit", "directed", "multigraph"):
        assert key in graph, f"graph.json missing top-level key {key!r} - schema changed or file corrupt"


def test_built_at_commit_present():
    """The provenance stamp exists (freshness is *derivable*). Not asserted == HEAD: the Stop-hook
    refresh and a manual edit legitimately diverge; presence is the invariant, currency is advisory."""
    graph, _ = _load_graph()
    commit = graph.get("built_at_commit")
    assert isinstance(commit, str) and commit.strip(), "built_at_commit absent/empty - graph has no provenance stamp"


def test_every_node_has_required_keys():
    graph, _ = _load_graph()
    for node in graph["nodes"]:
        missing = _REQUIRED_NODE_KEYS - set(node)
        assert not missing, f"node {node.get('id','?')!r} missing keys {missing} - node schema drift"


def test_no_llm_derived_nodes():
    """THE doctrine (CLAUDE.md): the graph is AST-only and contains NO LLM-derived nodes. A stray
    ``graphify label`` (or any LLM extractor) would plant nodes carrying a non-AST ``_origin`` - this
    is the guard that turns that from a silent provenance breach into a red build."""
    graph, _ = _load_graph()
    offenders = sorted({
        node.get("_origin") for node in graph["nodes"] if node.get("_origin") not in _ALLOWED_ORIGINS
    })
    assert not offenders, (
        f"non-AST node origin(s) {offenders} present - the AST-only / no-LLM-derived-nodes doctrine is "
        "violated (CLAUDE.md). If this is a NEW non-LLM extractor, widen _ALLOWED_ORIGINS deliberately; "
        "if it is an LLM origin, a forbidden `graphify label`-class node was planted.")


def test_file_types_within_known_enum():
    graph, _ = _load_graph()
    seen = {node.get("file_type") for node in graph["nodes"]}
    unknown = seen - _KNOWN_FILE_TYPES
    assert not unknown, f"unknown node file_type(s) {unknown} - the node-type enum grew; reconcile intentionally"


def test_relation_kinds_within_known_vocabulary():
    graph, _ = _load_graph()
    seen = {edge.get("relation") for edge in graph["links"]}
    unknown = seen - _KNOWN_RELATIONS
    assert not unknown, f"unknown edge relation(s) {unknown} - the edge vocabulary grew; reconcile intentionally"


def test_node_count_reconciles_with_graph_report():
    """Loose SSOT reconcile: CLAUDE.md names ``GRAPH_REPORT.md``'s header the AUTHORITATIVE node count.
    graph.json (Stop-hook-refreshed) and the report (regenerated less often) legitimately differ, so the
    bar is gross divergence, not equality - this is the assertion that would have caught the 76-node
    worktree trap had the report sat beside it."""
    graph, path = _load_graph()
    report = os.path.join(os.path.dirname(path), "GRAPH_REPORT.md")
    if not os.path.exists(report):
        pytest.skip("GRAPH_REPORT.md not beside graph.json - nothing to reconcile against")
    with open(report, encoding="utf-8") as f:
        head = f.read(2000)
    m = re.search(r"([\d,]+)\s+nodes", head)
    if not m:
        pytest.skip("could not parse a node count from GRAPH_REPORT.md header")
    reported = int(m.group(1).replace(",", ""))
    actual = len(graph["nodes"])
    assert 0.5 * reported <= actual <= 1.5 * reported, (
        f"graph.json has {actual} nodes vs GRAPH_REPORT.md's authoritative {reported} - "
        "gross divergence (stale/partial graph or corrupt report)")
