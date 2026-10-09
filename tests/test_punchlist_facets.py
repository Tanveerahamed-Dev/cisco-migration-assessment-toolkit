"""G21: the unpersisted punch-list facet fold partitions every stored row or publishes nothing.

Expectations are recounted independently here (collections.Counter over the stored rows), never taken from the
fold itself. The stored engine-built sample fleet and the committed golden snapshot are read, not regenerated.
"""
from collections import Counter
from copy import deepcopy
import json
import os

import pytest

from cisco_toolkit import analyze
from cisco_toolkit.analyze import (
    PUNCH_CATEGORIES,
    PUNCH_SEVERITIES,
    compute_device_findings,
    compute_migration_punchlist,
    compute_punchlist_facets,
)
from test_punchlist_evidence_refs import emittable_categories

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORED = (os.path.join(ROOT, "webapp", "sample_data", "sample_fleet.snapshot.json"),
          os.path.join(ROOT, "tests", "golden", "snapshot.json"))
FACETS = (("severity", PUNCH_SEVERITIES), ("category", PUNCH_CATEGORIES))


def _stored(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _assert_exact_partition(rows, folded):
    """Every key in owner order, every row exactly once, in the bucket its own field names."""
    assert folded["n_rows"] == len(rows)
    for facet, keys in FACETS:
        entry = folded[facet]
        assert entry["problem"] is None, (facet, entry["problem"])
        assert list(entry["indices"]) == list(keys)
        placed = [index for key in keys for index in entry["indices"][key]]
        assert sorted(placed) == list(range(len(rows))), facet
        for key, members in entry["indices"].items():
            assert members == sorted(members), (facet, key)
            assert all(rows[index][facet] == key for index in members), (facet, key)
        expected = Counter(row[facet] for row in rows)
        assert {key: len(members) for key, members in entry["indices"].items() if members} == dict(expected)


def test_category_vocabulary_is_the_evidence_policy_and_the_producer_emittable_set():
    assert PUNCH_CATEGORIES == tuple(analyze._PUNCH_EVIDENCE_POLICY)
    assert len(set(PUNCH_CATEGORIES)) == len(PUNCH_CATEGORIES)
    assert set(PUNCH_CATEGORIES) == emittable_categories()   # derived from the producer's AST, not a hand list
    assert set(analyze._PUNCH_CATEGORY_SECTION) <= set(PUNCH_CATEGORIES)


@pytest.mark.parametrize("path", STORED, ids=("sample_fleet", "golden"))
def test_the_stored_engine_punch_lists_partition_exactly(path):
    snap = _stored(path)
    rows = snap["punchlist"]
    assert len(rows) > 20                                      # non-vacuous: the real stored producer output
    before = deepcopy(rows)
    folded = compute_punchlist_facets(rows)
    _assert_exact_partition(rows, folded)
    assert rows == before
    # every stored category is a category the owner vocabulary names (no legacy spelling in the stored data)
    assert {row["category"] for row in rows} <= set(PUNCH_CATEGORIES)
    # device membership stays the G09 fold: the facet fold does not restate it
    assert "device" not in folded and "per_device" not in folded
    hosts = sorted(snap["devices"])
    per_device = compute_device_findings(rows, hosts)["per_device"]
    for host in hosts:
        assert len(per_device[host]["indices"]) == sum(1 for row in rows if host in row["devices"])


def test_real_producer_rows_partition_with_their_owner_keys():
    rows = compute_migration_punchlist(
        cross_layer=[
            {"severity": "Critical", "hosts": ["A", "B"], "title": "shared dependency", "detail": "observed"},
            {"severity": "High", "hosts": ["A"], "title": "separate finding", "detail": "observed"},
            {"severity": "Info", "hosts": ["B"], "title": "context", "detail": "observed"},
        ],
        security={}, config_hygiene={}, physical_health=[], l3_forwarding=[], protocol_health=[],
        stp_findings={}, health_scores=[], move_groups=[],
    )
    folded = compute_punchlist_facets(rows)
    _assert_exact_partition(rows, folded)
    cross = folded["category"]["indices"]["Cross-layer"]
    assert len(cross) == 3
    assert sorted(rows[index]["severity"] for index in cross) == ["Critical", "High", "Info"]
    for index in cross:
        assert index in folded["severity"]["indices"][rows[index]["severity"]]


def test_distinct_rows_are_counted_once_each_and_zero_buckets_stay_listed():
    rows = [
        {"severity": "High", "category": "Security", "devices": ["A", "A", "B"]},
        {"severity": "High", "category": "Security", "devices": []},
        {"severity": "Low", "category": "STP", "devices": ["A"]},
    ]
    folded = compute_punchlist_facets(rows)
    _assert_exact_partition(rows, folded)
    assert folded["severity"]["indices"]["High"] == [0, 1]
    assert folded["severity"]["indices"]["Critical"] == []
    assert folded["category"]["indices"]["Security"] == [0, 1]
    assert folded["category"]["indices"]["Compound risk"] == []


def test_an_empty_punch_list_is_a_complete_partition_of_nothing():
    folded = compute_punchlist_facets([])
    assert folded["n_rows"] == 0
    for facet, keys in FACETS:
        assert folded[facet] == {"problem": None, "indices": {key: [] for key in keys}}


@pytest.mark.parametrize("rows", [None, {}, (), "", 5, [None], [[]], [1], ["row"]])
def test_an_unreadable_list_or_row_refuses_both_facets(rows):
    folded = compute_punchlist_facets(rows)
    assert folded["n_rows"] is None
    for facet, _keys in FACETS:
        assert isinstance(folded[facet]["problem"], str) and folded[facet]["problem"]
        assert folded[facet]["indices"] == {}


@pytest.mark.parametrize("bad", [None, "", "high", "HIGH", "Severe", 3, [], {}, ["High"]])
def test_a_severity_outside_the_owner_vocabulary_refuses_only_the_severity_facet(bad):
    rows = [{"severity": "High", "category": "L3"}, {"severity": bad, "category": "L1"}]
    folded = compute_punchlist_facets(rows)
    assert "row 1" in folded["severity"]["problem"] and folded["severity"]["indices"] == {}
    assert folded["category"]["problem"] is None
    assert folded["category"]["indices"]["L3"] == [0] and folded["category"]["indices"]["L1"] == [1]


@pytest.mark.parametrize("bad", [None, "", "security", "Legacy category", 7, [], {"Security": 1}])
def test_a_category_outside_the_owner_vocabulary_refuses_only_the_category_facet(bad):
    rows = [{"severity": "High", "category": "Security"}, {"severity": "Low", "category": bad}]
    folded = compute_punchlist_facets(rows)
    assert "row 1" in folded["category"]["problem"] and folded["category"]["indices"] == {}
    assert folded["severity"]["problem"] is None
    assert folded["severity"]["indices"]["High"] == [0] and folded["severity"]["indices"]["Low"] == [1]


def test_a_missing_field_refuses_its_facet_and_never_drops_the_row():
    folded = compute_punchlist_facets([{"severity": "Medium", "category": "QoS"}, {"severity": "Medium"}])
    assert folded["category"]["problem"] and folded["category"]["indices"] == {}
    assert [len(folded["severity"]["indices"][key]) for key in PUNCH_SEVERITIES] == [0, 0, 2, 0, 0]


def test_the_fold_is_pure_and_returns_fresh_containers():
    rows = [{"severity": "Info", "category": "Coverage", "extra": {"nested": [1, 2]}}]
    frozen = deepcopy(rows)
    first = compute_punchlist_facets(rows)
    first["severity"]["indices"]["Info"].append(99)
    first["category"]["indices"].clear()
    assert rows == frozen
    second = compute_punchlist_facets(rows)
    assert second["severity"]["indices"]["Info"] == [0]
    assert second["category"]["indices"]["Coverage"] == [0]
