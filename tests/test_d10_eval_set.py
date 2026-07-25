"""Contract guard for the P2-1 D10 eval-set fixtures (docs/quality/d10-eval-set.jsonl + the
anchor pair).

The Phase-2 falsification run (master plan §5 Phase 2; owner doc
docs/d10-retrieval-eval-design-2026-07-08.md §2–§4) consumes a FROZEN 60-query set with graded
0–3 qrels plus a 15-anchor judge-screening set whose expected grades are SEALED from the judge.
This suite pins that contract:

* strata counts reconcile to the P2-0d pre-registration (``d10-eval-thresholds.json :: query_set``
  — the count owner; ``tests/test_d10_thresholds.py`` pins the owner's values, so the chain is
  exact end-to-end without a second hardcoding here);
* every non-identifier query carries a grounding citation; semantic queries are synonym-stripped
  (owner doc §2); multi-hop rows declare ≥ 2 named graph edges (verified against the live graph
  where one is reachable — the graph is owner-machine-only, so elsewhere that check SKIPS loudly);
* the anchor answer key is sealed by SEPARATION (judge-visible file carries ONLY aid/query/doc —
  the defect_panel sealed-key pattern) and by TAMPER-EVIDENCE: exact SHA-256 pins below, the
  d10-thresholds pin idiom — any edit must move fixture and pin together in a reviewed diff.

The validators live in ``cisco_toolkit/d10_eval_set.py`` (one implementation; this suite calls it
rather than re-deriving the rules — Law 1 applied to the contract itself).
"""
import json
import os
import pathlib

import pytest

from cisco_toolkit.d10_eval_set import (
    ANCHOR_BANDS, ANCHOR_CLASSES, ANCHOR_FIELDS, REFERENCE_RELATIONS,
    extract_identifier_queries, find_graph_json, load_anchor_key, load_anchors, load_eval_set,
    load_graph_settled, load_thresholds, sha256_normalized, validate_all, verify_multi_hop_edges)

ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- the tamper-evidence pins (normalized line endings, so LF/CRLF checkouts hash alike) -----------
# These fixtures are FROZEN at registration (owner doc §7: commit before running, never adjust
# after). P2-2 pool judging appends to a SEPARATE pooled-qrels file. Editing any of the three files
# must update its pin here in the same reviewed diff — that visibility IS the seal's second half.
EVAL_SET_SHA256 = "2477125eb6d282437ba4fe96ff6b5bff49de16465fd65616f4c12dd234cf51f1"
ANCHORS_SHA256 = "72e81d6310ce7d748331ee5854935d3599073d860eae29651448d7a4823dfb9e"
ANCHOR_KEY_SHA256 = "10b6851be7f16112d0d592b956417d266a127dedf144d3c10875c51a40657359"


def test_fixture_contract_clean_via_module():
    """The single-source validator finds zero contract violations in the committed fixtures."""
    problems = validate_all(str(ROOT))
    assert problems == [], "P2-1 fixture contract violated:\n" + "\n".join(problems)


def test_strata_counts_pinned_exactly():
    """20/20/10/10 (+15 anchors), reconciled to the P2-0d pre-registration — the count owner."""
    want = load_thresholds(str(ROOT))["query_set"]
    _, rows = load_eval_set(str(ROOT))
    got = {}
    for r in rows:
        got[r["stratum"]] = got.get(r["stratum"], 0) + 1
    assert got == {"identifier": want["identifier"], "semantic": want["semantic"],
                   "multi_hop": want["multi_hop"], "negative": want["negative"]}
    _, anchors = load_anchors(str(ROOT))
    assert len(anchors) == want["anchors_separate"]


def test_identifier_rows_quote_symbol_and_ground_in_graph():
    _, rows = load_eval_set(str(ROOT))
    for r in rows:
        if r["stratum"] != "identifier":
            continue
        assert f"`{r['symbol']}`" in r["query"], f"{r['qid']}: query must quote the exact symbol"
        assert r.get("node_id") and r.get("in_degree", 0) >= 1, f"{r['qid']}: graph provenance missing"
        assert any(q["grade"] == 3 for q in r["qrels"]), f"{r['qid']}: no grade-3 qrel"
        assert "graph.json" in r.get("grounding", ""), f"{r['qid']}: grounding must cite the graph"


def test_every_non_identifier_row_cites_grounding():
    """The task contract: authored queries are sanctioned, but each must cite what grounds it."""
    _, rows = load_eval_set(str(ROOT))
    for r in rows:
        if r["stratum"] == "identifier":
            continue
        grounding = str(r.get("grounding", ""))
        assert grounding.strip(), f"{r['qid']}: no grounding citation"
        # the citation must name at least one on-disk repo path (digest-lane rows also name their
        # repo-side statement, so this holds for them too)
        cited = [tok.rstrip(";,.)") for tok in grounding.replace("(", " ").split()
                 if ("/" in tok or ".md" in tok or ".py" in tok)]
        on_disk = [c for c in cited if (ROOT / c).exists()]
        assert on_disk, f"{r['qid']}: grounding cites no existing repo file: {grounding!r}"


def test_semantic_rows_are_synonym_stripped_and_digest_rows_honest():
    """Owner doc §2: a semantic query may not reuse its target's name tokens (else it degenerates
    into an identifier query). Digest-lane rows must say the digest is gitignored (DEC-006 A2)."""
    _, rows = load_eval_set(str(ROOT))
    from cisco_toolkit.d10_eval_set import _name_tokens, _query_tokens
    digest_rows = 0
    for r in rows:
        if r["stratum"] != "semantic":
            continue
        qtoks = _query_tokens(r["query"])
        for q in r["qrels"]:
            if q["grade"] == 3:
                overlap = qtoks & _name_tokens(q["doc"])
                assert not overlap, f"{r['qid']}: reuses target name token(s) {sorted(overlap)}"
        if r.get("requires_digest"):
            digest_rows += 1
            assert "gitignor" in r["grounding"], f"{r['qid']}: digest grounding must say gitignored"
            assert any(q["doc"].startswith("digest:") for q in r["qrels"])
    assert digest_rows >= 1, "DEC-006 A5: the set must contain digest-relevant queries"


def test_multi_hop_rows_declare_at_least_two_reference_edges():
    _, rows = load_eval_set(str(ROOT))
    for r in rows:
        if r["stratum"] != "multi_hop":
            continue
        edges = r.get("edges", [])
        assert len(edges) >= 2, f"{r['qid']}: fewer than 2 declared edges"
        for e in edges:
            assert e["relation"] in REFERENCE_RELATIONS, f"{r['qid']}: non-reference relation"
            for k in ("source", "source_file", "target", "target_file"):
                assert str(e.get(k, "")).strip(), f"{r['qid']}: edge missing {k}"


def test_multi_hop_edges_exist_in_live_graph():
    """Graph-dependent half: every declared edge must exist verbatim. The graph is gitignored and
    owner-machine-only (the graphify-out worktree trap), so absence is a SKIP with the reason
    stated — never a silent pass, never a fabricated one.

    KNOWN RESIDUAL, deliberately not masked: this still false-reds when the live graph is an
    edge-truncated INCREMENTAL rebuild (full node count, but a re-extracted file's cross-file edges
    evicted — the .git/hooks/post-commit `changed_paths` path). That is a producer bug, not fixture
    rot; the mitigation is `python -m graphify update .` (a full rebuild heals it) before running
    this. A consumer-side "vouch against a same-commit backup" guard was tried and reverted — three
    refuters showed it masks genuine deletions (`built_at_commit` is HEAD, blind to the tree). So the
    honest state is: torn reads skip (below), truncated rebuilds fail loudly and are pinned by
    :func:`test_verify_multi_hop_edges_reports_on_an_edge_truncated_graph`."""
    gp = find_graph_json(str(ROOT))
    if not gp:
        pytest.skip("graph.json not reachable (clean clone / CI / bare worktree) — "
                    "edge existence is verified on the owner machine and at build time")
    graph, unsettled = load_graph_settled(gp)
    if unsettled:
        pytest.skip(f"graph.json could not be read as a settled whole: {unsettled}. A file caught "
                    f"mid-rewrite by a background rebuild is not evidence about the declared edges")
    meta, rows = load_eval_set(str(ROOT))
    recorded = int(meta.get("graph_provenance", {}).get("nodes", 0))
    live = len(graph.get("nodes", []))
    if recorded and live < recorded // 2:
        pytest.skip(f"reachable graph.json is a partial/stub rebuild ({live} nodes vs "
                    f"{recorded} recorded in the fixture _meta — the worktree-hook rebuild "
                    f"case): verifying edges against it would be meaningless; the full check "
                    f"runs on the owner machine's main-checkout graph")
    problems = verify_multi_hop_edges(rows, graph)
    assert problems == [], "\n".join(problems)


def test_verify_multi_hop_edges_reports_on_an_edge_truncated_graph():
    """The non-weakening pin for the SURVIVING code: a graph with a full node set but a declared
    edge missing (the edge-truncated incremental-rebuild shape) must still be REPORTED, not masked.
    This is the case the reverted corroboration guard wrongly skipped; it now fails loudly."""
    row = {"qid": "M-99", "stratum": "multi_hop", "edges": [
        {"source": "main()", "source_file": "app.py", "relation": "calls",
         "target": "helper()", "target_file": "lib.py"}]}
    # both endpoint nodes present (full node count) but the linking edge evicted → truncated, not stub
    truncated = {"built_at_commit": "abc",
                 "nodes": [{"id": "m", "label": "main()", "source_file": "app.py"},
                           {"id": "h", "label": "helper()", "source_file": "lib.py"}],
                 "links": []}
    problems = verify_multi_hop_edges([row], truncated)
    assert len(problems) == 1 and "M-99" in problems[0] and "helper()" in problems[0]


# --- the settled-read guard: graph.json is rewritten under readers by background rebuilds --------

def _mini_graph():
    return {"built_at_commit": "abc", "nodes": [{"id": "m", "label": "main()"}], "links": []}


def test_settled_loader_reports_a_torn_read_instead_of_raising(tmp_path):
    """The non-atomic-write window: `graphify update` truncates graph.json then streams ~8 MB into
    it, so a concurrent reader sees half a file. That must degrade to a stated reason, never a
    JSONDecodeError escaping into the suite as a red."""
    torn = tmp_path / "graph.json"
    torn.write_text('{"nodes": [{"id": "a"}, {"id"', encoding="utf-8")
    graph, reason = load_graph_settled(str(torn), attempts=2, settle=0.01)
    assert graph is None and "never settled" in reason and "JSONDecodeError" in reason


def test_settled_loader_does_not_blame_a_rebuild_for_an_absent_file(tmp_path):
    """Coverage-honesty: a missing/unreadable file is a state of the FILE. Reporting it as "a
    rebuild is in flight" would assert a cause we never observed."""
    graph, reason = load_graph_settled(str(tmp_path / "nope.json"), attempts=3, settle=0.01)
    assert graph is None
    assert "could not be opened" in reason and "FileNotFoundError" in reason
    assert "never settled" not in reason and "being rewritten" not in reason


def test_settled_loader_rejects_a_graph_rewritten_under_the_read(tmp_path, monkeypatch):
    """A file that parsed cleanly but changed identity across the read was mid-rebuild: the bytes we
    parsed are not the bytes on disk, so the parse is not evidence."""
    import cisco_toolkit.d10_eval_set as mod
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(_mini_graph()), encoding="utf-8")
    real_stat, calls = os.stat, []

    def shifting_stat(p, *a, **kw):
        st = real_stat(p, *a, **kw)
        calls.append(p)
        if len(calls) % 2 == 0:          # the post-read stat never matches the pre-read one
            class _S:
                st_size, st_mtime_ns = st.st_size + 1, st.st_mtime_ns + 1
            return _S()
        return st

    monkeypatch.setattr(mod.os, "stat", shifting_stat)
    graph, reason = load_graph_settled(str(path), attempts=2, settle=0.01)
    assert graph is None and "rewritten while it was being read" in reason


def test_settled_loader_rejects_a_non_object_graph(tmp_path):
    """`json.load` of `null`/a list parses fine but is not a graph; returning it would hand callers
    an AttributeError on .get() one line later."""
    path = tmp_path / "graph.json"
    path.write_text("null", encoding="utf-8")
    graph, reason = load_graph_settled(str(path), attempts=1)
    assert graph is None and "not a JSON object" in reason


def test_settled_loader_reads_a_quiet_graph_cleanly(tmp_path):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(_mini_graph()), encoding="utf-8")
    graph, reason = load_graph_settled(str(path), attempts=1)
    assert reason is None and graph["built_at_commit"] == "abc"


def test_negative_rows_are_unanswerable_by_construction():
    _, rows = load_eval_set(str(ROOT))
    negatives = [r for r in rows if r["stratum"] == "negative"]
    for r in negatives:
        assert r["qrels"] == [], f"{r['qid']}: negative row must have empty qrels"
        assert "unanswerable" in r["grounding"], f"{r['qid']}: grounding must state unanswerability"


def test_anchor_fixture_is_sealed_no_answer_leakage():
    """The judge-visible anchor half carries ONLY aid/query/doc — class or expected grades in this
    file would hand the judge its own answer key (the defect_panel separation, mechanically)."""
    _, anchors = load_anchors(str(ROOT))
    for row in anchors:
        assert set(row) == ANCHOR_FIELDS, (
            f"{row.get('aid')}: judge-visible fields {sorted(row)} != {sorted(ANCHOR_FIELDS)}")
        assert (ROOT / row["doc"]).exists(), f"{row.get('aid')}: anchor doc missing on disk"


def test_anchor_key_split_and_preregistered_bands():
    """5 clear-relevant / 5 clear-irrelevant / 5 borderline, each keyed inside its frozen band."""
    _, key = load_anchor_key(str(ROOT))
    _, anchors = load_anchors(str(ROOT))
    assert {k["aid"] for k in key} == {a["aid"] for a in anchors}
    by_class = {}
    for k in key:
        by_class[k["class"]] = by_class.get(k["class"], 0) + 1
        assert set(k["expected_grades"]) <= ANCHOR_BANDS[k["class"]] and k["expected_grades"]
        assert str(k["rationale"]).strip() and str(k["grounding"]).strip()
    assert by_class == {c: len(anchors) // 3 for c in ANCHOR_CLASSES}


def test_seal_sha_pins_exact():
    """Tamper-evidence: the frozen fixtures hash exactly to their registered pins. A legitimate
    revision (it should be rare — the set is frozen) must change file AND pin in one reviewed
    diff; anything else is the drift/tamper this seal exists to catch."""
    assert sha256_normalized(str(ROOT / "docs/quality/d10-eval-set.jsonl")) == EVAL_SET_SHA256
    assert sha256_normalized(str(ROOT / "docs/quality/d10-anchors.jsonl")) == ANCHORS_SHA256
    assert sha256_normalized(str(ROOT / "docs/quality/d10-anchor-key.jsonl")) == ANCHOR_KEY_SHA256


def test_extractor_is_deterministic_and_rule_faithful_on_synthetic_graph():
    """The identifier extractor's declared rules, proven on a fixed mini-graph (the live graph
    mutates with every commit, so rule-faithfulness is pinned here, not against it): label
    uniqueness (ambiguous labels excluded), CROSS-FILE-only in-degree (intra-file fan-in ignored),
    structural relations ignored, deterministic label tie-break, and purity (same dict in → same
    rows out, twice)."""
    def node(nid, label, src, ftype="code"):
        return {"id": nid, "label": label, "source_file": src, "file_type": ftype}

    graph = {
        "built_at_commit": "cafebabe",
        "nodes": [
            node("a", "alpha()", "pkg/a.py"), node("b", "beta()", "pkg/b.py"),
            node("g", "gamma()", "pkg/e.py"),
            node("d1", "dup()", "pkg/c.py"), node("d2", "dup()", "pkg/d.py"),
            node("x", "x_caller()", "pkg/x.py"), node("y", "y_caller()", "pkg/y.py"),
            node("z", "z_caller()", "pkg/z.py"), node("s", "self_caller()", "pkg/a.py"),
            node("fa", "a.py", "pkg/a.py"),
        ],
        "links": [
            {"source": "x", "target": "a", "relation": "calls"},
            {"source": "y", "target": "a", "relation": "calls"},
            {"source": "z", "target": "a", "relation": "imports"},
            {"source": "s", "target": "a", "relation": "calls"},      # intra-file: must NOT count
            {"source": "fa", "target": "a", "relation": "contains"},  # structural: must NOT count
            {"source": "y", "target": "g", "relation": "calls"},      # gamma: 1
            {"source": "x", "target": "b", "relation": "calls"},      # beta: 1 (tie with gamma)
            {"source": "z", "target": "d1", "relation": "calls"},     # ambiguous label: excluded
            {"source": "x", "target": "d2", "relation": "calls"},
        ],
    }
    rows1, prov = extract_identifier_queries(graph, n=3)
    rows2, _ = extract_identifier_queries(graph, n=3)
    assert rows1 == rows2, "extractor is not pure/deterministic"
    assert prov == {"built_at_commit": "cafebabe", "nodes": 10, "links": 9}
    assert [r["symbol"] for r in rows1] == ["alpha()", "beta()", "gamma()"]  # rank, then label tie
    assert [r["in_degree"] for r in rows1] == [3, 1, 1]
    alpha = rows1[0]
    assert alpha["query"] == "what does `alpha()` do?"
    assert alpha["qrels"][0] == {"doc": "pkg/a.py", "grade": 3,
                                 "why": "defining file of `alpha()` (graph node a)"}
    assert [q["doc"] for q in alpha["qrels"][1:]] == ["pkg/x.py", "pkg/y.py", "pkg/z.py"]
    assert all(q["grade"] == 1 for q in alpha["qrels"][1:])
    assert not any(r["symbol"] == "dup()" for r in rows1), "ambiguous label must be excluded"


def test_registry_and_readme_cite_the_fixtures():
    """Law-1 wiring: the SSOT registry row and the quality README must keep naming these fixtures
    and this guard, so a rename/removal is loud (the test_registry_freshness self-citation idiom)."""
    registry = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    readme = (ROOT / "docs" / "quality" / "README.md").read_text(encoding="utf-8")
    for token in ("d10-eval-set.jsonl", "d10-anchor-key.jsonl", pathlib.Path(__file__).name):
        assert token in registry, f"docs/ssot.md no longer cites {token}"
    for token in ("d10-eval-set.jsonl", "d10-anchors.jsonl", "d10-anchor-key.jsonl"):
        assert token in readme, f"docs/quality/README.md no longer documents {token}"
