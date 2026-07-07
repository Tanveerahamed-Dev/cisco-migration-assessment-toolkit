"""Tests for domain pack-selection (cisco_toolkit.domain_packs) — Phase 3, D6.

Load-bearing properties:

- selection is COVERAGE-HONEST: a pack loads iff one of its architecture classes was OBSERVED; a
  not-observed class never loads a pack, and empty coverage loads nothing (and says so);
- the Phase-3 acceptance: an ACI+ISE snapshot auto-loads the DC and Security packs **and nothing else**;
- the pack→class map is pinned to the authoritative _ARCH_COVERAGE_REGISTRY — every mapped class exists in
  the registry (no rot), and every registry class has a pack (no architecture without a domain lens).
"""
from cisco_toolkit import domain_packs as D


def _cov(observed):
    """observed: dict class-key -> status ('clean' | 'finding'). Builds an architecture_coverage dict
    of OBSERVED classes, plus one not-observed class to prove it never triggers."""
    classes = [{"key": k, "observed": True, "status": s} for k, s in observed.items()]
    classes.append({"key": "aci", "observed": False, "status": "not-observed"}
                   if "aci" not in observed else
                   {"key": "mpls", "observed": False, "status": "not-observed"})
    return {"classes": classes}


def test_aci_and_ise_load_dc_and_security_only():
    """Phase-3 acceptance: ACI + ISE -> {dc, sec} and nothing else."""
    sel = D.select_packs({"classes": [
        {"key": "aci", "observed": True, "status": "clean"},
        {"key": "ise", "observed": True, "status": "finding"},
    ]})
    assert sel["loaded"] == ["dc", "sec"]
    sec = next(s for s in sel["selected"] if s["pack"] == "sec")
    assert sec["with_findings"] == ["ise"]          # the ISE finding is surfaced for the review


def test_not_observed_class_never_loads_a_pack():
    sel = D.select_packs({"classes": [{"key": "aci", "observed": False, "status": "not-observed"}]})
    assert sel["loaded"] == []                       # ACI in the registry but not in the evidence


def test_empty_coverage_loads_nothing_and_says_so():
    for empty in ({}, {"classes": []}, None, {"classes": "corrupt"}):
        sel = D.select_packs(empty)
        assert sel["loaded"] == []
    assert "absence is absence" in D.select_packs({})["note"]


def test_findings_are_prioritized():
    sel = D.select_packs(_cov({"aci": "finding"}))
    dc = next(s for s in sel["selected"] if s["pack"] == "dc")
    assert dc["with_findings"] == ["aci"] and dc["triggered_by"] == ["aci"]


def test_cross_listed_class_loads_both_packs():
    """access-edge port-security is campus AND security -> loads ent and sec."""
    loaded = D.select_packs(_cov({"port_security": "clean"}))["loaded"]
    assert "ent" in loaded and "sec" in loaded


def test_sp_pack_loads_on_mpls():
    assert "sp" in D.select_packs(_cov({"mpls": "clean"}))["loaded"]


def test_selection_order_is_stable():
    sel = D.select_packs(_cov({"ise": "clean", "aci": "clean", "mpls": "clean", "lisp": "clean"}))
    assert sel["loaded"] == ["dc", "ent", "sp", "sec"]     # PACKS declaration order


# --- the registry cross-checks (SSOT discipline) -----------------------------------------------

def test_every_mapped_class_exists_in_registry():
    """No pack may reference a class the engine doesn't assess (guards against a rename/removal)."""
    orphans = D.mapped_class_keys() - D.registry_class_keys()
    assert not orphans, f"pack classes not in _ARCH_COVERAGE_REGISTRY: {sorted(orphans)}"


def test_every_registry_class_has_a_pack():
    """No assessed architecture may lack a domain lens (a new detector must be assigned to a pack)."""
    uncovered = D.registry_class_keys() - D.mapped_class_keys()
    assert not uncovered, f"registry classes with no domain pack: {sorted(uncovered)}"


def test_every_pack_doc_exists():
    """Each pack points at a real knowledge/checklist doc (the mapping can't reference a missing file)."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for pid, spec in D.PACKS.items():
        assert os.path.exists(os.path.join(root, spec["doc"])), f"{pid}: missing {spec['doc']}"
