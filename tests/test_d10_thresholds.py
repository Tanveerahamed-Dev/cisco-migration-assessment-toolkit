"""Exact-value pin for the D10 Phase-2 eval pre-registration (P2-0d).

The eval design (docs/d10-retrieval-eval-design-2026-07-08.md §7) commits: "Write these thresholds
to a file first; do not adjust after seeing results." docs/quality/d10-eval-thresholds.json is that
file; this pin is the mechanical half of the commitment (the test_version.py value-pin pattern): every
load-bearing number is asserted EXACTLY, so a post-hoc adjustment cannot be quiet — it must change the
file AND this pin together in a reviewed diff, which is precisely the visibility the pre-registration
protocol demands. A light prose-reconcile also anchors the JSON to the owner doc's §7 wording, so the
two cannot drift apart silently (Law 1: the JSON is machine-readable, the doc is the registration of
record). DEC-006 (2026-07-10) widened the eval CORPUS; it changed no value here — the bar is intact.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREREG = ROOT / "docs" / "quality" / "d10-eval-thresholds.json"


def _load() -> dict:
    assert PREREG.exists(), "d10-eval-thresholds.json missing — the P2-0d pre-registration is broken"
    return json.loads(PREREG.read_text(encoding="utf-8"))


def test_significance_bar_pinned_exactly():
    sig = _load()["significance"]
    assert sig["test"] == "paired-t"
    assert sig["p_max"] == 0.05
    assert sig["cohens_d_min"] == 0.4


def test_decision_criteria_pinned_exactly():
    c = _load()["criteria"]
    assert c["bm25_earns_place"]["metric"] == "MRR@5"
    assert c["bm25_earns_place"]["margin"] == 0.05
    assert c["bm25_earns_place"]["on_fail"] == "FALSIFIED"
    assert c["dense_earns_dependency"]["metric"] == "MRR@5"
    assert c["dense_earns_dependency"]["stratum"] == "semantic"
    assert c["dense_earns_dependency"]["margin"] == 0.05
    assert c["dense_anti_pattern_auto_reject"]["stratum"] == "identifier"
    assert c["dense_anti_pattern_auto_reject"]["condition"] == "+dense < BM25"


def test_validity_gate_pinned_exactly():
    v = _load()["validity_gate"]
    assert v["judge_kappa_min"] == 0.7
    assert v["anchor_accuracy_min"] == 0.8
    assert v["hole_at_10_max"] == 0.15


def test_dense_precondition_query_set_and_frozen_tuning_pinned():
    t = _load()
    assert t["dense_precondition"]["semantic_share_min"] == 0.3
    assert t["dense_precondition"]["n_real_queries"] == 30
    assert t["query_set"] == {"identifier": 20, "semantic": 20, "multi_hop": 10,
                              "negative": 10, "anchors_separate": 15}
    assert t["tuning_frozen"]["rrf_k"] == 60
    assert t["tuning_frozen"]["bm25_k1"] == 0.9
    assert t["tuning_frozen"]["bm25_b"] == 0.4


def test_prereg_cross_links_to_owner_doc_and_prose_agrees():
    """The JSON must point at the owner doc, the owner doc must exist, and §7's prose must still
    state the same load-bearing values (frozen pre-registration: rewording §7 SHOULD be loud)."""
    meta = _load()["_meta"]
    owner = ROOT / meta["owner_doc"]
    assert meta["owner_doc"] == "docs/d10-retrieval-eval-design-2026-07-08.md"
    assert owner.exists(), "pre-registration points at an owner doc that does not exist"
    txt = owner.read_text(encoding="utf-8")
    for token in ("p < 0.05", "d > 0.4", "κ≥0.70", "acc≥0.80", "Hole@10 ≤ 0.15", "+ 0.05",
                  "RRF k=60", "k1=0.9, b=0.4"):
        assert token in txt, f"owner doc no longer states {token!r} — prereg and doc have drifted"
