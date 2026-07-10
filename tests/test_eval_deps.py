"""API-surface smoke for the ``[eval]`` extra (P2-0b, Phase-2 pre-task).

The D10 Phase-2 eval stack (rank-bm25 / pytrec-eval-terrier / scipy — see pyproject
``[project.optional-dependencies] eval`` and the d10 design §8) is OPTIONAL: the base suite and CI
never require it, so every test here ``importorskip``s cleanly when the extra is not installed.
When it IS installed (the owner machine, or a future eval-CI lane), these pin exactly the API
surface the Phase-2 harness will call — the §4 frozen BM25 priors as constructor args, the
pre-registered paired t-test, and the reference MRR implementation — so a breaking dependency
upgrade is caught at install time, not mid-eval. No egress: everything here is local compute.
"""
import pytest


def test_rank_bm25_okapi_accepts_the_frozen_priors():
    rank_bm25 = pytest.importorskip("rank_bm25", reason="[eval] extra not installed")
    # NB: query a DISCRIMINATING term (df=1 of 3). Okapi IDF for a term in every doc is negative
    # (and degenerate-zero at df=1, N=2) — correct BM25 behavior that makes an all-docs term a
    # useless probe. The Phase-2 identifier queries are rare terms by construction, so pin that.
    bm = rank_bm25.BM25Okapi([["circuit", "breaker"], ["breaker", "cooldown"],
                              ["scorecard", "trend"]], k1=0.9, b=0.4)
    scores = bm.get_scores(["circuit"])
    assert len(scores) == 3
    assert scores[0] > 0 and scores[0] == max(scores)        # the doc holding the rare term wins
    assert scores[2] == 0                                    # no-overlap doc scores exactly 0


def test_scipy_paired_t_test_surface():
    stats = pytest.importorskip("scipy.stats", reason="[eval] extra not installed")
    r = stats.ttest_rel([1.0, 0.9, 0.8, 0.7], [0.9, 0.8, 0.7, 0.6])
    assert hasattr(r, "pvalue") and 0.0 <= float(r.pvalue) <= 1.0


def test_pytrec_eval_reference_mrr_surface():
    pytrec_eval = pytest.importorskip("pytrec_eval", reason="[eval] extra not installed")
    ev = pytrec_eval.RelevanceEvaluator({"q1": {"d1": 1}}, {"recip_rank"})
    res = ev.evaluate({"q1": {"d1": 1.0, "d2": 0.5}})
    assert res["q1"]["recip_rank"] == 1.0                    # relevant doc at rank 1 -> RR 1.0
