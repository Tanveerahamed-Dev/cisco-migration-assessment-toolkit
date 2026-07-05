"""Feature J2 — attribute-level provenance for the canonical headline facts (Infrahub-style).

`ssot.compute_fact_lineage(snap)` makes the SSOT contract QUERYABLE: for every CANONICAL_FACTS
entry it names WHERE the headline number comes from — its dotted canonical path, the authoritative
published value (read canonical-first via `ssot.canonical_facts`), the coverage-honest 3-state of
that path, and the one-line basis/derivation already recorded in CANONICAL_FACTS. It REUSES the
SSOT contract rather than inventing a parallel provenance store.

Coverage-honesty (Law 3): a fact whose canonical block is NOT published reads `not_collected` (a
blind spot) with `value=None` — never a silent 0, never "ok"/"healthy". (source_command depth —
mapping each fact to the exact show-command — is DEFERRED; the basis string is the v1 provenance.)
"""
import json
import os

import pytest

from cisco_toolkit import ssot


# A synthetic snapshot that PUBLISHES the canonical blocks, so we can exercise the published /
# collected_but_empty states. Values are internally consistent but arbitrary — the lineage test
# cares about provenance shape + state, not reconciliation (that is ssot.reconcile's job).
PUBLISHED = {
    "executive_brief": {
        "scale": {
            "n_devices": 12,
            "n_collected": 10,
            "n_endpoints": 44,
            "n_vlans": 7,
            "n_domains": 3,
        },
        "posture": {
            "avg_health": 68,
            "n_critical": 2,
            "n_poor": 3,
            "worst_band": "Critical",
        },
    },
    "lifecycle_risk": {
        "summary": {
            "n_past_ldos": 5,
            "n_past_eos": 0,           # published but zero -> collected_but_empty (NOT a blind spot)
            "n_near": 4,
            "n_active": 3,
        },
    },
    "design_blueprint": {
        "summary": {"n_decisions": 9},
    },
}


def _lineage(snap):
    return ssot.compute_fact_lineage(snap)


def _fact(lineage, name):
    return next((f for f in lineage["facts"] if f["name"] == name), None)


def test_schema_and_one_row_per_canonical_fact():
    lin = _lineage(PUBLISHED)
    assert lin["schema"] == "fact_lineage/1"
    names_out = [f["name"] for f in lin["facts"]]
    # exactly the CANONICAL_FACTS keys, once each, in registry order (deterministic)
    assert names_out == list(ssot.CANONICAL_FACTS.keys())
    assert len(names_out) == len(set(names_out)), "a canonical fact is duplicated in the lineage"


def test_each_fact_carries_value_path_state_basis():
    lin = _lineage(PUBLISHED)
    for f in lin["facts"]:
        assert set(f) == {"name", "value", "path", "state", "basis"}, f["name"]
        name = f["name"]
        path, concept = ssot.CANONICAL_FACTS[name]
        # path is the dotted canonical path from the contract (never re-invented)
        assert f["path"] == path
        # basis is the one-line concept/derivation from the contract (the "== len(...)" hints)
        assert f["basis"] == concept
        # state is the SAME token abstention_reason returns for that path (one source of truth)
        assert f["state"] == ssot.abstention_reason(PUBLISHED, path)
        # state is always one of the three honest tokens — never "ok"/"healthy"
        assert f["state"] in {"published", "collected_but_empty", "not_collected"}


def test_value_matches_canonical_facts_accessor():
    """value must be the authoritative value from ssot.canonical_facts (read canonical-first),
    not a re-derivation — so lineage can never disagree with the accessor every surface uses."""
    lin = _lineage(PUBLISHED)
    values = ssot.canonical_facts(PUBLISHED)
    for f in lin["facts"]:
        assert f["value"] == values[f["name"]], f["name"]
    # spot-check the headline numbers came through
    assert _fact(lin, "n_devices")["value"] == 12
    assert _fact(lin, "n_past_ldos")["value"] == 5
    assert _fact(lin, "worst_band")["value"] == "Critical"   # worst_band stays a string, not coerced


def test_published_block_reads_published():
    lin = _lineage(PUBLISHED)
    f = _fact(lin, "n_devices")
    assert f["state"] == "published"
    assert f["value"] == 12


def test_present_but_zero_reads_collected_but_empty_not_blind_spot():
    """The load-bearing coverage-honesty distinction: a canonical value published as 0 was
    COLLECTED (genuinely nothing of this kind) — it must read collected_but_empty, never a blind
    spot, and the value must be a real 0, never None."""
    lin = _lineage(PUBLISHED)
    f = _fact(lin, "n_past_eos")           # published as 0 in PUBLISHED
    assert f["state"] == "collected_but_empty"
    assert f["value"] == 0                 # a real collected zero, not a fabricated/absent value


def test_unpublished_block_reads_not_collected():
    """An un-published canonical block is a BLIND SPOT (not_collected) with value None — never a
    silent 0. This is the whole point: absence of evidence is never health (Law 3)."""
    # strip the executive_brief block entirely -> all scale/posture facts become blind spots
    snap = {k: v for k, v in PUBLISHED.items() if k != "executive_brief"}
    lin = _lineage(snap)
    for name in ("n_devices", "n_collected", "n_endpoints", "n_vlans", "n_domains",
                 "avg_health", "n_critical", "n_poor", "worst_band"):
        f = _fact(lin, name)
        assert f["state"] == "not_collected", name
        assert f["value"] is None, name
    # the lifecycle facts, still published, are unaffected — provenance is per-fact
    assert _fact(lin, "n_past_ldos")["state"] == "published"
    assert _fact(lin, "n_past_ldos")["value"] == 5


def test_empty_snapshot_every_fact_is_a_blind_spot():
    lin = _lineage({})
    assert all(f["state"] == "not_collected" and f["value"] is None for f in lin["facts"])
    # basis + path are still populated from the contract even with zero evidence (the map is stable)
    for f in lin["facts"]:
        assert f["path"] and f["basis"]


@pytest.mark.parametrize("bad", [None, [], "garbage", 42, {"executive_brief": "not-a-dict"}])
def test_total_on_bad_input(bad):
    """Deterministic + total: any non-dict (or degenerate) snapshot yields a well-formed lineage
    with every canonical fact as a blind spot, never an exception."""
    lin = ssot.compute_fact_lineage(bad)
    assert lin["schema"] == "fact_lineage/1"
    assert len(lin["facts"]) == len(ssot.CANONICAL_FACTS)
    for f in lin["facts"]:
        assert f["state"] == "not_collected"
        assert f["value"] is None
        assert f["path"] and f["basis"]


def test_lineage_is_deterministic():
    """Same snapshot -> byte-identical lineage (no dates, no model)."""
    a = json.dumps(_lineage(PUBLISHED), sort_keys=True)
    b = json.dumps(_lineage(dict(PUBLISHED)), sort_keys=True)
    assert a == b


# --- the golden fixture, where present --------------------------------------------------------
_GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "snapshot.json")


@pytest.mark.skipif(not os.path.isfile(_GOLDEN), reason="golden snapshot not present in worktree")
def test_lineage_over_golden_fixture_is_coverage_honest():
    """The golden fixture is a slim synthetic snapshot without the canonical blocks, so every
    headline fact is honestly a blind spot — a real coverage-honest reading, not a fabricated
    number. Whatever the fixture publishes, every state is one of the three honest tokens and each
    fact's state agrees with abstention_reason on its path."""
    with open(_GOLDEN, encoding="utf-8") as f:
        snap = json.load(f)
    lin = ssot.compute_fact_lineage(snap)
    assert len(lin["facts"]) == len(ssot.CANONICAL_FACTS)
    for fact in lin["facts"]:
        assert fact["state"] in {"published", "collected_but_empty", "not_collected"}
        assert fact["state"] == ssot.abstention_reason(snap, fact["path"])
        # a not_collected fact must never carry a fabricated value
        if fact["state"] == "not_collected":
            assert fact["value"] is None, fact["name"]
