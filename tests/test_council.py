"""Tests for the grounded /council mechanism (cisco_toolkit.council) — Phase 3, D8.

Load-bearing properties:

- lenses are the coverage-selected domain packs, findings-carrying first; with a general N-sample fallback
  when no domain applies (a council is always a real panel);
- each lens prompt is refute-first and independent (no cross-critique);
- aggregation is refute-first MAJORITY: SUPPORT only on a strict majority of ALL lenses, else REFUTE — and
  it is non-vacuous (a clear support-majority really does return SUPPORT). A zero-lens council fails safe.
"""
from cisco_toolkit import council as C

S, R, U = C.SUPPORT, C.REFUTE, C.UNCERTAIN


def _cov(observed):
    return {"classes": [{"key": k, "observed": True, "status": s} for k, s in observed.items()]}


# --- lens selection ----------------------------------------------------------------------------

def test_plan_council_selects_domain_lenses():
    plan = C.plan_council("The DC fabric is ready to cut over", _cov({"aci": "clean", "ise": "clean"}))
    ids = {le["lens"] for le in plan["lenses"]}
    assert "dc" in ids and "sec" in ids and plan["n"] == 2


def test_plan_council_findings_lenses_come_first():
    plan = C.plan_council("claim", _cov({"aci": "clean", "ise": "finding"}))   # sec has a finding
    assert plan["lenses"][0]["lens"] == "sec" and plan["lenses"][0]["priority"] is True


def test_plan_council_falls_back_to_general_samples():
    plan = C.plan_council("A non-domain claim", {"classes": []})
    assert plan["n"] == 3 and all(le["lens"].startswith("general#") for le in plan["lenses"])


def test_lens_prompt_is_refute_first_and_independent():
    p = C._lens_prompt("DC / ACI", "docs/packs/dc.md", "fabric is healthy")
    assert "REFUTE" in p and "INDEPENDENTLY" in p and "cannot see" in p
    assert "fabric is healthy" in p and "cite the field/line" in p


# --- verdict normalization ---------------------------------------------------------------------

def test_normalize_verdict_aliases():
    assert C.normalize_verdict("VERDICT=BLOCK") == R
    assert C.normalize_verdict("i would APPROVE this") == S
    assert C.normalize_verdict("tried to DISPROVE — succeeded") == R
    assert C.normalize_verdict("hmm, not sure") == U          # refute-first on ambiguity -> UNCERTAIN


# --- aggregation (refute-first majority) -------------------------------------------------------

def test_aggregate_support_needs_strict_majority():
    assert C.aggregate([S, S, S, R])["verdict"] == S          # 3/4 support -> SUPPORT


def test_aggregate_tie_blocks():
    a = C.aggregate([S, S, R, R])
    assert a["verdict"] == R and "no support-majority" in a["rationale"]


def test_aggregate_uncertain_plurality_blocks():
    assert C.aggregate([S, U, U])["verdict"] == R             # 1/3 support -> refute-first blocks


def test_aggregate_unanimous_support_is_non_vacuous():
    assert C.aggregate([S, S, S])["verdict"] == S             # the SAME fn returns SUPPORT when earned


def test_aggregate_zero_lenses_fails_safe():
    a = C.aggregate([])
    assert a["verdict"] == R and a["n"] == 0                  # cannot certify with no lens


def test_aggregate_non_refute_first_is_plurality():
    assert C.aggregate([S, S, R], refute_first=False)["verdict"] == S
    assert C.aggregate([S, R, R], refute_first=False)["verdict"] == R
