"""Hermetic guard for the P2-2 retrieval-eval harness (:mod:`cisco_toolkit.retrieval_eval`).

Everything here runs WITHOUT Ollama and without the live graph: the judge is an injected callable
(the harness's own ``judge_invoke`` seam), the graph lane is an injected ranker, and the
end-to-end test builds a synthetic mini-fixture root (its own thresholds + eval set + anchors +
sealed key, counts reconciled the same way the real fixtures reconcile to P2-0d). ``[eval]``-extra
tests (`rank_bm25` / `pytrec_eval` / `scipy`) ``importorskip`` cleanly, the ``test_eval_deps``
idiom, so the base suite never requires them.

What must hold (the §6/§7 mechanics, pinned):

* the graph-token → doc-id mapping never fabricates a hit (bare symbols dropped, ambiguous
  suffixes dropped);
* the dual-prompt combination is take-the-MIN and the sealed key stays scorer-only (the gate
  payload carries no expected grades);
* Cohen's κ and the screening gate floors behave per the pre-registered validity gate — including
  the signal_absent path (Ollama down ⇒ PARTIAL run, identifier still scored, verdict UNDECIDED,
  grades never fabricated);
* metrics binarize at grade ≥ 2 exactly as the fixture ``_meta`` froze; negatives stay out of the
  rank aggregates; Hole@10 counts only unjudged docs;
* the decision statistics and the BM25 verdict read every bar from the thresholds file (both
  branches exercised);
* ``run_eval`` REFUSES on a missing/invalid P2-1 fixture — the harness never builds its own set.
"""
import json
import pathlib
import subprocess

import pytest

from cisco_toolkit.retrieval_eval import (
    CONFIG_A, CONFIG_B, CONFIGS, Bm25Lane, append_pooled_qrels, authored_qrels, binarize,
    bm25_verdict, cohens_kappa, combine_dual, dense_column_status, excerpt_for_judge, hole_at_k,
    judge_prompts, judge_schema, load_pooled_qrels, map_graph_tokens_to_docs, merge_qrels,
    negative_diagnostic, paired_stats, pool_unjudged, render_markdown, run_eval, screen_judge)

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- pure lane / mapping mechanics ------------------------------------------------------------------

def test_graph_token_mapping_is_strict_and_deterministic():
    ids = ["cisco_toolkit/recall.py", "docs/quality/README.md", "webapp/backend/app.py",
           "tests/app.py"]
    tokens = ["cisco_toolkit\\recall.py:123",      # backslashes + :line -> normalized exact hit
              "docs/quality/README.md",             # exact hit
              "rrf_fuse()",                         # bare symbol: no doc identity -> dropped
              "app.py",                             # suffix AMBIGUOUS (2 candidates) -> dropped
              "backend/app.py",                     # suffix unique -> mapped
              "cisco_toolkit/recall.py"]            # duplicate -> deduped
    assert map_graph_tokens_to_docs(tokens, ids) == [
        "cisco_toolkit/recall.py", "docs/quality/README.md", "webapp/backend/app.py"]


def test_dual_prompt_combination_is_take_the_min():
    assert combine_dual(3, 1) == 1
    assert combine_dual(0, 2) == 0
    assert combine_dual(2, 2) == 2


def test_excerpt_picks_the_query_relevant_window_deterministically():
    # windows=1 is instrument v1 exactly: the earliest max-hit window, nothing else
    text = ("padding " * 400) + "the circuit breaker cooldown lives here" + (" trailer" * 400)
    ex = excerpt_for_judge("circuit breaker cooldown", text, size=200, windows=1)
    assert "circuit breaker cooldown" in ex
    assert len(ex) <= 200
    small = "tiny doc"
    assert excerpt_for_judge("anything", small) == small


def test_excerpt_v2_multi_window_carries_head_and_hit_regions():
    """Instrument v2 (pre-registered 2026-07-11): head window (doc identity) + top-hit windows,
    document order, overlap-suppressed, budget-bounded, deterministic."""
    head = "MODULE DOCSTRING: this file owns the breaker discipline. "
    text = head + ("padding " * 400) + "the circuit breaker cooldown lives here" + (" trailer" * 400)
    ex = excerpt_for_judge("circuit breaker cooldown", text, size=200, windows=3)
    assert ex.startswith("MODULE DOCSTRING")           # the head window is always included
    assert "circuit breaker cooldown" in ex            # ...and so is the best-hit region
    assert "[...]" in ex                               # non-contiguous regions are marked, not spliced
    assert len(ex) <= 3 * 200 + 2 * len("\n[...]\n")   # the budget bounds the excerpt
    assert ex == excerpt_for_judge("circuit breaker cooldown", text, size=200, windows=3)
    # whole doc when it fits the TOTAL budget (size*windows), not just one window
    mid = "x" * 500
    assert excerpt_for_judge("anything", mid, size=200, windows=3) == mid
    # production default is the v2 shape (three windows of 1800)
    big = "HEAD " + ("filler " * 2000) + " breaker cooldown target " + ("tail " * 2000)
    prod = excerpt_for_judge("breaker cooldown", big)
    assert prod.startswith("HEAD ") and "breaker cooldown target" in prod


def test_judge_prompts_carry_rubric_and_no_expected_grades():
    rubric = {"0": "not relevant", "1": "marginal", "2": "substantive", "3": "defining"}
    p = judge_prompts("what verifies feeds?", "cisco_toolkit/intel_feed.py", "excerpt", rubric)
    assert set(p) == {"neutral", "adversarial"}
    for text in p.values():
        assert "defining" in text and "excerpt" in text
        assert "expected" not in text.lower()       # the sealed key never enters a prompt
    assert "NOT answer" in p["adversarial"]
    schema = judge_schema()
    assert schema["properties"]["grade"]["enum"] == [0, 1, 2, 3]
    assert list(schema["properties"]) == ["reasoning", "grade"]   # reasoning FIRST
    # grammar-enforced reasoning bound: forces string closure so the grade is always reached
    # (unbounded deliberation produced unterminated JSON on real content — measured, not theory)
    assert schema["properties"]["reasoning"]["maxLength"] == 400


# --- κ + screening gate ------------------------------------------------------------------------------

def test_cohens_kappa_known_values():
    assert cohens_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
    # hand-computed: po=0.5, pe=0.5 -> kappa = 0 (agreement no better than chance)
    assert cohens_kappa([0, 0, 1, 1], [0, 1, 0, 1], labels=(0, 1)) == pytest.approx(0.0)
    # hand-computed: po=0.75, pe=(3/4)(1/2)+(1/4)(1/2)=0.5 -> kappa = 0.5
    assert cohens_kappa([0, 0, 0, 1], [0, 0, 1, 1], labels=(0, 1)) == pytest.approx(0.5)
    assert cohens_kappa([2, 2, 2], [2, 2, 2]) == 1.0             # constant agreement
    assert cohens_kappa([0, 0, 0], [1, 1, 1]) == 0.0             # constant disagreement guard
    with pytest.raises(ValueError):
        cohens_kappa([1], [1, 2])


def _key_rows():
    return [{"aid": "A-1", "class": "clear_relevant", "expected_grades": [2, 3]},
            {"aid": "A-2", "class": "clear_irrelevant", "expected_grades": [0]},
            {"aid": "A-3", "class": "borderline", "expected_grades": [1, 2]}]


def _gate_thresholds():
    return {"validity_gate": {"judge_kappa_min": 0.7, "anchor_accuracy_min": 0.8,
                              "hole_at_10_max": 0.15}}


def test_screen_judge_passes_on_consistent_in_band_grades():
    p1 = {"A-1": 3, "A-2": 0, "A-3": 1}
    gate = screen_judge(p1, dict(p1), _key_rows(), _gate_thresholds())
    assert gate["status"] == "passed" and gate["kappa"] == 1.0 and gate["accuracy"] == 1.0


def test_screen_judge_fails_on_agreeable_out_of_band_grades():
    # consistent (kappa perfect) but grades the clearly-irrelevant doc as relevant -> accuracy 2/3
    p1 = {"A-1": 3, "A-2": 2, "A-3": 1}
    gate = screen_judge(p1, dict(p1), _key_rows(), _gate_thresholds())
    assert gate["status"] == "failed" and gate["accuracy"] < 0.8


def test_screen_judge_fails_loudly_on_missing_anchors():
    gate = screen_judge({"A-1": 3}, {"A-1": 3}, _key_rows(), _gate_thresholds())
    assert gate["status"] == "failed" and "ungraded" in gate["reason"]


# --- qrels / metrics conventions ---------------------------------------------------------------------

def test_binarize_floor_and_merge_precedence():
    authored = {"q1": {"a.py": 3, "b.py": 1}}
    pooled = {"q1": {"a.py": 0, "c.py": 2}}          # pooled disagrees on a.py -> authored wins
    merged = merge_qrels(authored, pooled)
    assert merged == {"q1": {"a.py": 3, "b.py": 1, "c.py": 2}}
    assert binarize(merged) == {"q1": {"a.py": 1, "b.py": 0, "c.py": 1}}


def test_hole_at_10_counts_only_unjudged_docs():
    run = {"q1": ["a.py", "b.py", "x.py", "y.py"], "q2": []}
    judged = {"q1": {"a.py": 3, "b.py": 0}}          # grade 0 is still an ANNOTATION, not a hole
    assert hole_at_k(run, judged, ["q1", "q2"], k=10) == pytest.approx(0.25)  # (2/4 + 0)/2


def test_negative_diagnostic_lower_is_better_shape():
    run = {"n1": ["a.py", "b.py"], "n2": []}
    d = negative_diagnostic(run, ["n1", "n2"])
    assert d == {"mean_returned@5": 1.0, "any_returned_rate": 0.5}


def test_paired_stats_zero_variance_is_degenerate_not_significant():
    a = {f"q{i}": {"mrr@5": 0.5} for i in range(4)}
    b = {f"q{i}": {"mrr@5": 0.5} for i in range(4)}
    st = paired_stats(a, b, sorted(a))
    assert st["p_value"] is None and st["cohens_dz"] == 0.0 and "degenerate" in st["note"]


def test_paired_stats_detects_a_consistent_lift():
    pytest.importorskip("scipy", reason="[eval] extra not installed")
    lifts = [0.3, 0.5, 0.4, 0.35, 0.45, 0.4]
    base = [0.2, 0.25, 0.3, 0.2, 0.25, 0.3]
    a = {f"q{i}": {"mrr@5": v} for i, v in enumerate(base)}
    b = {f"q{i}": {"mrr@5": v + lifts[i]} for i, v in enumerate(base)}
    st = paired_stats(a, b, sorted(a))
    assert st["delta"] == pytest.approx(sum(lifts) / len(lifts))
    assert st["p_value"] is not None and st["p_value"] < 0.05
    assert st["cohens_dz"] > 0.4


def test_bm25_verdict_reads_the_preregistered_bars_both_branches():
    thresholds = json.loads((ROOT / "docs/quality/d10-eval-thresholds.json").read_text("utf-8"))
    earned = bm25_verdict({"mean_a": 0.5, "mean_b": 0.6, "delta": 0.1,
                           "p_value": 0.01, "cohens_dz": 0.9}, thresholds)
    assert earned["verdict"] == "EARNED"
    # clears the margin but not significance -> the pre-registered on_fail verdict
    falsified = bm25_verdict({"mean_a": 0.5, "mean_b": 0.6, "delta": 0.1,
                              "p_value": 0.2, "cohens_dz": 0.9}, thresholds)
    assert falsified["verdict"] == thresholds["criteria"]["bm25_earns_place"]["on_fail"]


def test_dense_column_defers_below_the_row_floor(tmp_path):
    thresholds = {"dense_precondition": {"n_real_queries": 30, "semantic_share_min": 0.3}}
    dc = dense_column_status(str(tmp_path), thresholds)
    assert dc["status"] == "DEFERRED" and dc["real_queries_logged"] == 0 and dc["required"] == 30
    log = tmp_path / "docs" / "quality" / "query_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("\n".join('{"date":"d","query":"q","surface":"s"}' for _ in range(31)),
                   encoding="utf-8")
    assert dense_column_status(str(tmp_path), thresholds)["status"].startswith("PRECONDITION MET")


# --- pooling ----------------------------------------------------------------------------------------

def test_pool_unjudged_targets_only_judged_strata_and_unjudged_docs(tmp_path):
    rows = [{"qid": "I-01", "stratum": "identifier"}, {"qid": "S-01", "stratum": "semantic"},
            {"qid": "M-01", "stratum": "multi_hop"}, {"qid": "N-01", "stratum": "negative"}]
    runs = {"cfg": {"I-01": ["a.py"], "S-01": ["a.py", "b.py"], "M-01": ["c.py"],
                    "N-01": ["d.py"]}}
    judged = {"S-01": {"a.py": 3}}
    assert pool_unjudged(runs, judged, rows) == [("M-01", "c.py"), ("S-01", "b.py")]
    n = append_pooled_qrels({("S-01", "b.py"): 2}, root=str(tmp_path), model="m", date="2026-07-11")
    assert n == 1
    again = append_pooled_qrels({("S-01", "b.py"): 2}, root=str(tmp_path), model="m",
                                date="2026-07-11")
    assert again == 0                                # idempotent: an existing judgment is kept
    pooled = load_pooled_qrels(str(tmp_path / "docs" / "quality" / "d10-pooled-qrels.jsonl"))
    assert pooled == {"S-01": {"b.py": 2}}


# --- BM25 lane + reference scoring (the [eval] extra) ------------------------------------------------

def test_bm25_lane_ranks_the_rare_term_doc_first():
    pytest.importorskip("rank_bm25", reason="[eval] extra not installed")
    corpus = {"a.py": "circuit breaker cooldown ceiling", "b.py": "scorecard trend rows",
              "c.md": "unrelated prose entirely"}
    lane = Bm25Lane(corpus, k1=0.9, b=0.4)
    ranked = lane.rank("circuit breaker")
    assert ranked and ranked[0] == "a.py"
    assert "c.md" not in ranked                      # zero-overlap docs never fabricated in


def test_score_config_hand_computed_mrr_and_p1():
    pytest.importorskip("pytrec_eval", reason="[eval] extra not installed")
    from cisco_toolkit.retrieval_eval import score_config
    graded = {"q1": {"gold.py": 3, "near.py": 1},    # near.py grade 1 -> NOT relevant at floor 2
              "q2": {"gold.py": 2}}
    run = {"q1": ["near.py", "gold.py"],             # relevant at rank 2 -> MRR@5 0.5, P@1 0
           "q2": ["gold.py"]}                        # rank 1 -> MRR@5 1.0, P@1 1
    per_q = score_config(run, graded, ["q1", "q2"])
    assert per_q["q1"]["mrr@5"] == pytest.approx(0.5)
    assert per_q["q1"]["p@1"] == pytest.approx(0.0)
    assert per_q["q2"]["mrr@5"] == pytest.approx(1.0)
    assert per_q["q2"]["p@1"] == pytest.approx(1.0)
    assert per_q["q1"]["recall@10"] == pytest.approx(1.0)


# --- the run-refusal precondition + hermetic end-to-end ----------------------------------------------

def test_run_eval_refuses_without_the_p2_1_fixtures(tmp_path):
    with pytest.raises(RuntimeError, match="P2-1"):
        run_eval(str(tmp_path))


def _write_jsonl(path, meta, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"_meta": meta})] + [json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mini_fixture_root(tmp_path):
    """A fully synthetic P2-1-shaped root: tiny counts, its own thresholds, git-tracked corpus."""
    root = tmp_path
    (root / "pkg").mkdir()
    (root / "pkg" / "gold.py").write_text("def target_fn():\n    'circuit breaker cooldown'\n",
                                          encoding="utf-8")
    (root / "pkg" / "near.py").write_text("from pkg.gold import target_fn\n", encoding="utf-8")
    (root / "notes.md").write_text("prose about breaker cooldown discipline\n", encoding="utf-8")
    thresholds = {
        "significance": {"test": "paired-t", "p_max": 0.05, "cohens_d_min": 0.4,
                         "rule": "BOTH must clear"},
        "criteria": {"bm25_earns_place": {"metric": "MRR@5", "comparison": "graph+BM25 > graph",
                                          "margin": 0.05, "on_fail": "FALSIFIED"}},
        "validity_gate": {"judge_kappa_min": 0.7, "anchor_accuracy_min": 0.8,
                          "hole_at_10_max": 0.15,
                          "on_fail": "eval INVALID - re-pool"},
        "dense_precondition": {"semantic_share_min": 0.3, "n_real_queries": 30},
        "query_set": {"identifier": 1, "semantic": 1, "multi_hop": 1, "negative": 1,
                      "anchors_separate": 3},
        "tuning_frozen": {"rrf_k": 60, "bm25_k1": 0.9, "bm25_b": 0.4},
    }
    q = root / "docs" / "quality"
    q.mkdir(parents=True)
    (q / "d10-eval-thresholds.json").write_text(json.dumps(thresholds), encoding="utf-8")
    rubric = {"0": "not relevant", "1": "marginal", "2": "substantive", "3": "defining"}
    rows = [
        {"qid": "I-01", "stratum": "identifier", "query": "what does `target_fn()` do?",
         "symbol": "target_fn()", "node_id": "pkg_gold_target_fn", "in_degree": 1,
         "qrels": [{"doc": "pkg/gold.py", "grade": 3, "why": "defining file"},
                   {"doc": "pkg/near.py", "grade": 1, "why": "neighbour"}],
         "grounding": "graph.json :: node pkg_gold_target_fn"},
        {"qid": "S-01", "stratum": "semantic",
         "query": "which module implements the pause discipline?",
         "qrels": [{"doc": "notes.md", "grade": 3, "why": "the prose owner"}],
         "grounding": "notes.md"},
        {"qid": "M-01", "stratum": "multi_hop", "query": "who calls the defining function?",
         "qrels": [{"doc": "pkg/near.py", "grade": 3, "why": "the caller"}],
         "grounding": "pkg/near.py imports pkg/gold.py",
         "edges": [{"source": "near", "source_file": "pkg/near.py", "relation": "imports",
                    "target": "target_fn()", "target_file": "pkg/gold.py"},
                   {"source": "near", "source_file": "pkg/near.py", "relation": "calls",
                    "target": "target_fn()", "target_file": "pkg/gold.py"}]},
        {"qid": "N-01", "stratum": "negative", "query": "how is kerberos configured?",
         "qrels": [], "grounding": "unanswerable: verified absent"},
    ]
    _write_jsonl(q / "d10-eval-set.jsonl",
                 {"artifact": "mini", "grading_rubric": rubric}, rows)
    anchors = [{"aid": "A-1", "query": "is the breaker documented?", "doc": "notes.md"},
               {"aid": "A-2", "query": "who owns billing?", "doc": "pkg/gold.py"},
               {"aid": "A-3", "query": "is near a caller?", "doc": "pkg/near.py"}]
    _write_jsonl(q / "d10-anchors.jsonl", {"artifact": "mini-anchors"}, anchors)
    key = [{"aid": "A-1", "class": "clear_relevant", "expected_grades": [2, 3],
            "rationale": "r", "grounding": "notes.md"},
           {"aid": "A-2", "class": "clear_irrelevant", "expected_grades": [0],
            "rationale": "r", "grounding": "pkg/gold.py"},
           {"aid": "A-3", "class": "borderline", "expected_grades": [1, 2],
            "rationale": "r", "grounding": "pkg/near.py"}]
    _write_jsonl(q / "d10-anchor-key.jsonl", {"artifact": "mini-key"}, key)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _fake_graph_ranker(query):
    if "target_fn" in query or "calls" in query:
        return ["pkg/gold.py", "pkg/near.py"]
    return []


def _fake_judge(gate_grades):
    """An injected judge: anchors (pids A-*) get ``gate_grades``; pooled pairs all grade 2."""
    def invoke(pairs, *, root, passes=1, **_kw):
        grades = []
        for p in pairs:
            pid = str(p["pid"])
            g = gate_grades.get(pid, 2)
            grades.append({"pid": pid, "final_by_pass": [g] * passes,
                           "detail": []})
        return {"ok": True, "model": "fake:judge", "passes": passes, "grades": grades}
    return invoke


def test_run_eval_end_to_end_complete_and_partial(tmp_path):
    pytest.importorskip("rank_bm25", reason="[eval] extra not installed")
    pytest.importorskip("pytrec_eval", reason="[eval] extra not installed")
    pytest.importorskip("scipy", reason="[eval] extra not installed")
    root = _mini_fixture_root(tmp_path)
    out = root / "out"
    judge = _fake_judge({"A-1": 3, "A-2": 0, "A-3": 1})
    results = run_eval(str(root), out_dir=str(out), graph_ranker=_fake_graph_ranker,
                       judge_invoke=judge, today="2026-07-11")
    assert results["judge_gate"]["status"] == "passed"
    assert results["run_status"] in ("COMPLETE", "INVALID")   # INVALID only if holes stay open
    assert results["hole@10"]["valid"] is True                # pool judging closed every hole
    assert results["run_status"] == "COMPLETE"
    ident = results["strata"]["identifier"]
    assert ident["n"] == 1 and ident[CONFIG_A]["mrr@5"] == pytest.approx(1.0)
    assert set(results["strata"]) == {"identifier", "semantic", "multi_hop", "negative"}
    assert results["verdicts"]["bm25_earns_place"]["verdict"] in ("EARNED", "FALSIFIED")
    assert results["verdicts"]["dense_column"]["status"] == "DEFERRED"
    md = render_markdown(results)
    assert "Judge screening gate" in md and "Pre-registered verdicts" in md
    assert (out / "d10-eval-results-2026-07-11.md").exists()
    assert (out / "d10-eval-results-2026-07-11.json").exists()

    # PARTIAL path: judge unreachable -> judged strata INVALID, identifier still scored, honest.
    def down(pairs, *, root, passes=1, **_kw):
        return {"ok": False, "reason": "Ollama not listening (test)"}
    partial = run_eval(str(root), graph_ranker=_fake_graph_ranker, judge_invoke=down,
                       today="2026-07-11")
    assert partial["run_status"] == "PARTIAL"
    assert partial["judge_gate"]["status"] == "signal_absent"
    assert "INVALID" in partial["strata"]["semantic"]["status"]
    assert partial["strata"]["identifier"][CONFIG_A]["mrr@5"] == pytest.approx(1.0)
    assert partial["overall"] is None
    assert partial["verdicts"]["bm25_earns_place"]["verdict"] == "UNDECIDED"
    assert "PARTIAL" in render_markdown(partial)


def test_authored_qrels_and_configs_shape():
    rows = [{"qid": "I-01", "stratum": "identifier", "query": "q",
             "qrels": [{"doc": "a.py", "grade": 3}]}]
    assert authored_qrels(rows) == {"I-01": {"a.py": 3}}
    assert CONFIGS == (CONFIG_A, CONFIG_B) == ("graph", "graph+bm25")


def test_main_usage_returns_2(capsys):
    from cisco_toolkit import retrieval_eval as RE
    assert RE.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_invoke_judge_helper_missing_is_signal_absent(tmp_path):
    """No fabricated grade when the judge helper is absent — signal_absent honesty (retrieval_eval.py:515)."""
    from cisco_toolkit import retrieval_eval as RE
    res = RE.invoke_judge_helper([{"pid": "1", "query": "q"}], root=str(tmp_path))
    assert res["ok"] is False and "judge helper missing" in res["reason"]


def test_tracked_files_raises_on_git_failure(monkeypatch, tmp_path):
    import pytest
    from cisco_toolkit import retrieval_eval as RE

    class _Bad:
        returncode = 128
        stderr = "not a git repository"
        stdout = ""

    monkeypatch.setattr(RE.subprocess, "run", lambda *a, **k: _Bad())
    with pytest.raises(RuntimeError):
        RE.tracked_files(str(tmp_path))
