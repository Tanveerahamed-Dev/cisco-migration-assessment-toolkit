"""Tests for RRF hybrid recall (cisco_toolkit.recall) — Phase 5, D10 experiment.

Pins the dependency-free core: RRF rewards multi-signal agreement; the lexical signal only returns real
overlaps (never a fabricated hit); the hybrid surfaces a code-store-only hit; and the eval computes MRR and
reports lift honestly. All pure — no repo, no egress.
"""
from cisco_toolkit import recall as R


def test_tokenize():
    assert R.tokenize("Circuit-Breaker cooldown_30!") == ["circuit", "breaker", "cooldown_30"]


def test_rrf_fuse_rewards_multi_list_agreement():
    fused = R.rrf_fuse([["a", "b"], ["b", "c"]])
    order = [x for x, _ in fused]
    assert order[0] == "b"                      # in BOTH lists -> highest fused score
    assert set(order) == {"a", "b", "c"}


def test_rrf_fuse_empty():
    assert R.rrf_fuse([]) == [] and R.rrf_fuse([[], []]) == []


def test_lexical_rank_returns_overlap_only_ranked_by_tf():
    corpus = {"d1": "circuit breaker cooldown", "d2": "scorecard trend renderer",
              "d3": "circuit circuit breaker"}
    r = R.lexical_rank("circuit breaker", corpus)
    assert "d3" in r and "d1" in r and "d2" not in r     # d2 has no overlap -> excluded
    assert r[0] == "d3"                                  # higher term frequency ranks first


def test_lexical_rank_empty_query_is_empty():
    assert R.lexical_rank("", {"d": "x"}) == []


def test_hybrid_surfaces_a_code_only_hit():
    docs = {"doc.md": "nothing relevant here"}
    code = {"clock.py": "circuit breaker cooldown", "other.py": "unrelated content"}
    ids = [x for x, _ in R.hybrid_recall("circuit breaker", docs_corpus=docs, code_corpus=code)]
    assert "clock.py" in ids                             # surfaced from the code store despite empty docs hit


def test_evaluate_reports_mrr_vs_best_single_honestly():
    docs = {"clock.md": "circuit breaker cooldown nightly"}
    code = {"clock.py": "circuit breaker cooldown nightly spend"}
    rep = R.evaluate([("circuit breaker cooldown", "clock")], docs_corpus=docs, code_corpus=code)
    assert rep["n"] == 1 and rep["mrr_hybrid"] == 1.0        # 'clock' is the top hit
    assert set(rep) >= {"mrr_docs", "mrr_code", "mrr_hybrid", "best_single", "delta"}
    assert rep["delta"] == round(rep["mrr_hybrid"] - rep["best_single"], 3)   # honest baseline
    # non-vacuity: fusion is compared against the BEST single signal, so it cannot look better than it is
    assert rep["best_single"] == max(rep["mrr_docs"], rep["mrr_code"])


def test_graph_rank_parses_identifiers_dedups_and_caps(monkeypatch):
    import subprocess

    class _Out:
        returncode = 0
        stdout = "NODE cisco_toolkit/recall.py:104\nrrf_fuse()\ndocs/ssot.md\nrrf_fuse()\ncisco_toolkit/parse.py"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    toks = R.graph_rank("anything")
    assert "cisco_toolkit/recall.py:104" in toks and "rrf_fuse()" in toks and "docs/ssot.md" in toks
    assert toks.count("rrf_fuse()") == 1                      # first-seen, deduped


def test_graph_rank_degrades_to_empty_when_graphify_unavailable(monkeypatch):
    import subprocess

    class _Bad:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Bad())
    assert R.graph_rank("q") == []                            # offline-graphify degrades, never fabricates


def test_main_usage_returns_2(capsys):
    assert R.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()
