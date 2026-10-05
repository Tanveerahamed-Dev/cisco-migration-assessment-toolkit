"""The ephemeral health partition cannot invent membership or override canonical abstentions."""
from copy import deepcopy

import pytest

from cisco_toolkit import ssot


def _fleet():
    bands = ssot._HEALTH_BAND_ORDER + (ssot._HEALTH_BAND_NOT_SCORED,)
    return {"health_scores": [{"switch": f"host-{i}", "band": band, "score": 20 + i * 15}
                              for i, band in enumerate(bands)],
            "executive_brief": {"posture": {"n_critical": 1, "n_poor": 1}}}


def test_partition_is_complete_owner_ordered_and_never_persisted():
    snap = _fleet()
    before = deepcopy(snap)
    partition = ssot.health_band_partition(snap)
    assert partition["state"] == "published"
    assert [row["band"] for row in partition["bands"]] == list(ssot._HEALTH_BAND_ORDER) + ["Insufficient Data"]
    assert [row["hosts"] for row in partition["bands"]] == [[f"host-{i}"] for i in range(6)]
    assert sum(row["n"] for row in partition["bands"]) == len(snap["health_scores"])
    assert ssot.reconcile_health_band_partition(snap, partition) == []
    assert snap == before and "health_band_partition" not in snap
    partition["bands"][0]["hosts"].append("unowned")
    assert snap == before
    assert ssot.reconcile_health_band_partition(snap, partition)


@pytest.mark.parametrize("row", [None, {}, {"switch": " ", "band": "Good"},
                                 {"switch": [], "band": "Good"}, {"switch": "x", "band": ["Critical"]},
                                 {"switch": "x", "band": "future-band"}])
def test_unreadable_subject_or_band_withholds_the_whole_partition(row):
    result = ssot.health_band_partition({"health_scores": [_fleet()["health_scores"][0], row]})
    assert result["state"] == "unverified" and result["bands"] == []


def test_duplicate_host_is_not_silently_deduplicated_across_bands():
    snap = _fleet()
    snap["health_scores"][1]["switch"] = snap["health_scores"][0]["switch"]
    result = ssot.health_band_partition(snap)
    assert result["state"] == "unverified" and result["bands"] == []


@pytest.mark.parametrize("count", [True, 1.0])
def test_guard_rejects_a_non_integer_partition_count_even_when_python_compares_it_equal(count):
    snap = _fleet()
    partition = ssot.health_band_partition(snap)
    partition["bands"][0]["n"] = count
    assert count == 1  # ordinary equality alone would incorrectly certify these mutations
    assert ssot.reconcile_health_band_partition(snap, partition)


def test_absent_malformed_and_observed_empty_are_distinct():
    assert ssot.health_band_partition({})["state"] == "not_collected"
    assert ssot.health_band_partition({"health_scores": {}})["state"] == "unverified"
    empty = ssot.health_band_partition({"health_scores": []})
    assert empty["state"] == "published"
    assert all(row["n"] == 0 and row["hosts"] == [] for row in empty["bands"])


@pytest.mark.parametrize("name", ["n_critical", "n_poor"])
@pytest.mark.parametrize("bad", [99, True, "1", 1.0, -1])
def test_overlap_guard_rejects_drift_and_coercible_non_counts(name, bad):
    snap = _fleet()
    snap["executive_brief"]["posture"][name] = bad
    violations = ssot.reconcile_health_band_partition(snap)
    assert any(message.startswith(ssot.CANONICAL_FACTS[name][0] + "=") for message in violations)


def test_canonical_abstention_is_not_changed_to_zero_by_the_fold():
    snap = {"health_scores": [{"switch": "blind-score", "band": "Insufficient Data", "score": None}],
            "executive_brief": {"posture": {"n_critical": None, "n_poor": None}}}
    before = deepcopy(snap)
    partition = ssot.health_band_partition(snap)
    assert partition["bands"][-1]["hosts"] == ["blind-score"]
    assert ssot.reconcile_health_band_partition(snap, partition) == []
    assert ssot.canonical_facts(snap)["n_critical"] is None
    assert ssot.canonical_facts(snap)["n_poor"] is None
    assert snap == before
