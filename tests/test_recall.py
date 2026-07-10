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


# --- the REAL-query log (P2-0a) -- hermetic: tmp paths only, never the repo's real log -----------

def test_append_query_log_appends_schema_and_respects_optout(tmp_path, monkeypatch):
    import json
    monkeypatch.delenv("CISCO_RECALL_NO_LOG", raising=False)
    p = tmp_path / "recall_queries.jsonl"
    assert R.append_query_log("  what does clock.py do  ", source="recall",
                              stores="docs+code", path=str(p)) is True
    assert R.append_query_log("second query", source="ask", path=str(p)) is True
    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2                                    # append-only, one JSON object per line
    assert rows[0]["query"] == "what does clock.py do"       # verbatim, stripped
    assert rows[0]["source"] == "recall" and rows[0]["stores"] == "docs+code"
    assert rows[1]["source"] == "ask" and rows[1]["stores"] == ""
    assert all(set(r) == {"ts", "query", "source", "stores"} for r in rows)
    monkeypatch.setenv("CISCO_RECALL_NO_LOG", "1")           # opt-out: no row, honest False
    assert R.append_query_log("third", source="recall", path=str(p)) is False
    assert len(p.read_text(encoding="utf-8").splitlines()) == 2


def test_append_query_log_never_logs_empty_and_never_raises(tmp_path):
    p = tmp_path / "q.jsonl"
    assert R.append_query_log("", source="recall", path=str(p)) is False
    assert R.append_query_log("   ", source="recall", path=str(p)) is False
    assert not p.exists()                                    # nothing fabricated for empty input
    blocked = tmp_path / "as-dir"
    blocked.mkdir()
    assert R.append_query_log("q", source="recall", path=str(blocked)) is False   # unwritable -> False


def test_main_log_only_arm_records_for_ask_without_retrieval(tmp_path, monkeypatch, capsys):
    import json
    monkeypatch.delenv("CISCO_RECALL_NO_LOG", raising=False)
    monkeypatch.chdir(tmp_path)                              # non-repo cwd -> _repo_root() falls back here
    rc = R.main(["--log-only", "--source=ask", "what breaks if the core switch fails"])
    assert rc == 0
    logf = tmp_path / "docs" / "quality" / "recall_queries.jsonl"
    assert logf.exists()
    row = json.loads(logf.read_text(encoding="utf-8").splitlines()[0])
    assert row["query"] == "what breaks if the core switch fails"
    assert row["source"] == "ask" and row["stores"] == ""
    assert "appended" in capsys.readouterr().out
    assert R.main(["--log-only"]) == 2                       # empty query: skipped, honest non-zero


def test_main_interactive_query_logs_but_eval_never_does(tmp_path, monkeypatch):
    import json
    monkeypatch.delenv("CISCO_RECALL_NO_LOG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(R, "graph_rank", lambda q, **kw: [])          # hermetic: no graphify subprocess
    monkeypatch.setattr(R, "load_vault_digest", lambda *a, **kw: {})  # hermetic: no digest, no Ollama
    logf = tmp_path / "docs" / "quality" / "recall_queries.jsonl"
    assert R.main(["--eval"]) == 0                           # synthetic eval queries: NEVER logged
    assert not logf.exists()
    assert R.main(["some real question"]) == 0               # interactive query: logged with stores
    rows = [json.loads(ln) for ln in logf.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["source"] == "recall" and rows[0]["stores"] == "docs+code"
