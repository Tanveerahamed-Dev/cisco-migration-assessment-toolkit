"""Tests for the seeded-defect TNR harness (cisco_toolkit.defect_panel).

Load-bearing properties:
- the registry is the 12-defect, doctrine-mapped panel; every defect names a law;
- the known-good deliverable is clean (no false positives from the deterministic arm);
- each injector creates EXACTLY its own defect (non-vacuous, no cross-tripping) — the oracle is sound;
- the text rendering strips the oracle flags but keeps the judge-visible claims;
- the scorer's true-negative math is non-vacuous: a perfect judge -> 1.0, an all-APPROVE (agreeableness)
  judge -> 0.0, a reject-everything-for-the-wrong-reason judge -> unlocalized, not localized.
"""
from cisco_toolkit import defect_panel as P


def test_registry_is_eighteen_doctrine_mapped_defects():
    # 12 founding defects + the 2026-07-18 growth (D-13..D-18) to the registered 18-defect target.
    assert len(P.DEFECTS) == 18
    for did, meta in P.DEFECTS.items():
        assert meta["class"] and meta["law"] and meta["desc"]
        assert meta["detect"] in ("deterministic", "both")


def test_growth_defects_cite_their_independent_source():
    """The registered growth path is INDEPENDENT sources only — each D-13..D-18 entry must cite the
    real QA-scorecard row or audit PR it was harvested from (never authored to fit the judge)."""
    for did in ("D-13", "D-14", "D-15", "D-16", "D-17", "D-18"):
        desc = P.DEFECTS[did]["desc"]
        assert ("QA row" in desc) or ("PR #" in desc), f"{did} lacks an independent-source citation"


def test_good_deliverable_is_clean():
    assert P.deterministic_findings(P.good_deliverable()) == set()      # no false positives


def test_each_injector_creates_exactly_its_own_defect():
    for did in P.DEFECT_IDS:
        corrupted, key = P.inject(did)
        assert key["defect_id"] == did
        assert key["defect_class"] == P.DEFECTS[did]["class"]
        found = P.deterministic_findings(corrupted)
        assert found == {did}, f"{did} injection produced findings {found}, expected exactly {{{did}}}"


def test_injection_is_non_vacuous():
    assert P.inject("D-01")[0] != P.good_deliverable()


def test_unknown_defect_id_raises():
    import pytest
    with pytest.raises(KeyError):
        P.inject("D-99")


def test_render_text_strips_oracle_flags_but_keeps_claims():
    corrupted, _ = P.inject("D-03")
    text = P.render_text(corrupted)
    for flag in ("in_corpus", "required_direction", "twin_result", "peers_in_evidence",
                 "in_switchport_evidence"):
        assert flag not in text
    assert "core9" in text and "healthy" in text            # the claim + the manifest are both visible


def test_text_visible_ids_are_the_fair_llm_panel():
    ids = P.text_visible_ids()
    assert 4 <= len(ids) <= 18 and set(ids) <= set(P.DEFECT_IDS)
    for did in ids:
        assert P.DEFECTS[did]["detect"] == "both"
    # the six growth defects are all text-visible by design (they grow the LLM-judge fair panel 5 -> 11)
    assert {"D-13", "D-14", "D-15", "D-16", "D-17", "D-18"} <= set(ids)


def _keys():
    return {did: P.inject(did)[1] for did in P.DEFECT_IDS}


def test_scorer_perfect_judge_scores_tnr_one():
    keys = _keys()
    verdicts = [{"defect_id": d, "verdict": "REJECT", "defect_class": k["defect_class"]}
                for d, k in keys.items()]
    r = P.score_verdicts(verdicts, keys)
    assert r["localized_tnr"] == 1.0 and r["unlocalized_rejection_rate"] == 0.0


def test_scorer_agreeable_judge_scores_tnr_zero():
    # the exact failure mode we are hunting: an all-APPROVE judge is exposed as TNR 0, not trusted.
    keys = _keys()
    verdicts = [{"defect_id": d, "verdict": "APPROVE"} for d in keys]
    r = P.score_verdicts(verdicts, keys)
    assert r["localized_tnr"] == 0.0 and r["rejection_rate"] == 0.0


def test_scorer_wrong_reason_is_unlocalized_not_localized():
    keys = _keys()
    verdicts = [{"defect_id": d, "verdict": "REJECT", "defect_class": "some-other-class"} for d in keys]
    r = P.score_verdicts(verdicts, keys)
    assert r["localized_tnr"] == 0.0 and r["unlocalized_rejection_rate"] == 1.0


def test_deterministic_arm_is_the_full_panel_floor():
    # the bias-free oracle catches (and localizes) every seeded defect: TNR 1.0 by construction.
    base = P.deterministic_baseline()
    assert base["n"] == 18 and base["localized_tnr"] == 1.0


def test_build_panel_shape():
    panel = P.build_panel(["D-01", "D-11"])
    assert [e["defect_id"] for e in panel] == ["D-01", "D-11"]
    for e in panel:
        assert set(e) == {"defect_id", "structured", "text", "key"}
        assert isinstance(e["text"], str) and e["text"]
