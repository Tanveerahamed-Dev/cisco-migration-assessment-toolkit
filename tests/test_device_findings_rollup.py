"""The unpersisted device fold admits every membership before exposing counts."""
from copy import deepcopy

import pytest

from cisco_toolkit.analyze import (
    PUNCH_SEVERITIES,
    _APP_SEV_RANK,
    compute_device_findings,
    compute_migration_punchlist,
    device_config_capture,
)


def test_findings_vocabulary_follows_the_existing_severity_owner():
    assert PUNCH_SEVERITIES == tuple(sorted(_APP_SEV_RANK, key=_APP_SEV_RANK.get))


@pytest.mark.parametrize("severity", PUNCH_SEVERITIES)
def test_each_supported_severity_has_one_closed_bucket_and_the_same_worst(severity):
    result = compute_device_findings([{"severity": severity, "devices": ["A"]}], ["A"])
    assert result["problem"] is None
    device = result["per_device"]["A"]
    assert device["worst"] == severity
    assert list(device["by_severity"]) == list(PUNCH_SEVERITIES)
    assert device["by_severity"][severity] == 1
    assert sum(device["by_severity"].values()) == 1
    assert device["indices"] == [0]


def test_distinct_rows_and_duplicate_memberships_have_different_count_semantics():
    rows = [
        {"severity": "High", "devices": ["A", "A", "B"], "foreign": {"preserve": [1]}},
        {"severity": "Critical", "devices": ["A"]},
        {"severity": "High", "devices": ["A"]},
        {"severity": "Info", "devices": ["B"]},
        {"severity": "Low", "devices": []},
    ]
    result = compute_device_findings(rows, ["A", "B", "C"])
    assert result["problem"] is None
    assert result["per_device"]["A"] == {
        "worst": "Critical", "by_severity": {"Critical": 1, "High": 2, "Medium": 0, "Low": 0, "Info": 0},
        "indices": [0, 1, 2],
    }
    assert result["per_device"]["B"] == {
        "worst": "High", "by_severity": {"Critical": 0, "High": 1, "Medium": 0, "Low": 0, "Info": 1},
        "indices": [0, 3],
    }
    assert result["per_device"]["C"]["worst"] is None
    assert result["per_device"]["C"]["indices"] == []
    assert list(result["per_device"]) == ["A", "B", "C"]


def test_exact_identity_is_not_case_or_whitespace_normalized():
    rows = [{"severity": "Medium", "devices": ["a", " A", "A "]}]
    result = compute_device_findings(rows, ["A", "a", " A", "A "])
    assert result["problem"] is None
    assert result["per_device"]["A"]["worst"] is None
    assert result["per_device"]["a"]["indices"] == [0]
    assert result["per_device"][" A"]["indices"] == [0]
    assert result["per_device"]["A "]["indices"] == [0]


def test_empty_partition_does_not_invent_a_clean_severity_and_is_fresh():
    first = compute_device_findings([], ["A"])
    assert first == {"problem": None, "per_device": {
        "A": {"worst": None, "by_severity": dict.fromkeys(PUNCH_SEVERITIES, 0), "indices": []},
    }}
    first["per_device"]["A"]["indices"].append(12)
    first["per_device"]["A"]["by_severity"]["High"] = 2
    second = compute_device_findings([], ["A"])
    assert second["per_device"]["A"]["indices"] == []
    assert second["per_device"]["A"]["by_severity"]["High"] == 0


@pytest.mark.parametrize("rows", [
    None, {}, (), "", [None], [[]], [1],
    [{}], [{"severity": "High"}], [{"devices": ["A"]}],
    [{"severity": "unknown", "devices": ["A"]}],
    [{"severity": "high", "devices": ["A"]}],
    [{"severity": [], "devices": ["A"]}],
    [{"severity": None, "devices": ["A"]}],
    [{"severity": "High", "devices": "A"}],
    [{"severity": "High", "devices": {"A": True}}],
    [{"severity": "High", "devices": ("A",)}],
    [{"severity": "High", "devices": [""]}],
    [{"severity": "High", "devices": ["  "]}],
    [{"severity": "High", "devices": ["A", None]}],
    [{"severity": "High", "devices": ["A", {}]}],
    [{"severity": "High", "devices": ["A", 2]}],
])
def test_any_unreadable_source_has_no_usable_partition(rows):
    result = compute_device_findings(rows, ["A"])
    assert isinstance(result["problem"], str) and result["problem"]
    assert result["per_device"] == {}


@pytest.mark.parametrize("hosts", [None, {}, {"A"}, "A", [""], [" "], [None], [1], [True],
                                    ["A", "A"], ["A", []]])
def test_unreadable_or_duplicate_host_selection_has_no_usable_partition(hosts):
    result = compute_device_findings([], hosts)
    assert result["problem"]
    assert result["per_device"] == {}


def test_invalid_tail_outside_requested_membership_still_invalidates_the_partition():
    rows = [{"severity": "High", "devices": ["A"]}, {"severity": "Unknown", "devices": ["outside"]}]
    for hosts in (["A"], []):
        result = compute_device_findings(rows, hosts)
        assert result["problem"]
        assert result["per_device"] == {}


def test_source_and_unrelated_fields_are_not_mutated():
    rows = [{"severity": "Info", "devices": ["A", "A"], "extra": {"nested": [1, 2]}}]
    hosts = ["A", "B"]
    frozen = deepcopy((rows, hosts))
    result = compute_device_findings(rows, hosts)
    result["per_device"]["A"]["indices"].append(77)
    result["per_device"]["A"]["by_severity"]["Info"] = 88
    assert (rows, hosts) == frozen
    assert result["per_device"]["B"]["by_severity"]["Info"] == 0
    assert compute_device_findings(rows, hosts)["per_device"]["A"]["indices"] == [0]


def test_real_punchlist_output_folds_the_published_rows_without_a_new_engine_section():
    rows = compute_migration_punchlist(
        cross_layer=[
            {"severity": "Critical", "hosts": ["A", "A", "B"], "title": "critical dependency", "detail": "fact"},
            {"severity": "High", "hosts": ["A"], "title": "separate high", "detail": "fact"},
            {"severity": "Info", "hosts": ["B"], "title": "observed context", "detail": "fact"},
        ],
        security={}, config_hygiene={}, physical_health=[], l3_forwarding=[],
        protocol_health=[], stp_findings={}, health_scores=[], move_groups=[],
    )
    before = deepcopy(rows)
    result = compute_device_findings(rows, ("A", "B"))
    assert result["problem"] is None
    assert result["per_device"]["A"]["by_severity"] == {
        "Critical": 1, "High": 1, "Medium": 0, "Low": 0, "Info": 0,
    }
    assert result["per_device"]["B"]["by_severity"]["Critical"] == 1
    assert result["per_device"]["B"]["by_severity"]["Info"] == 1
    assert result["per_device"]["A"]["indices"] == [0, 1]
    assert result["per_device"]["B"]["indices"] == [0, 2]
    assert rows == before


@pytest.mark.parametrize("canonical,fallback,expected", [
    ({"config_assessable": True}, {"assessable": False}, True),
    ({"config_assessable": False}, {"assessable": True}, False),
    ({}, {"assessable": True}, None),
    ({"config_assessable": None}, {"assessable": True}, None),
    ({"config_assessable": 1}, {"assessable": True}, None),
    ({"config_assessable": "true"}, {"assessable": True}, None),
    ([], {"assessable": True}, None),
    (False, {"assessable": True}, None),
    (None, {"assessable": True}, True),
    (None, {"assessable": False}, False),
    (None, {"assessable": 1}, None),
    (None, {"assessable": "false"}, None),
    (None, {}, None), (None, None, None), (None, [], None),
])
def test_config_capture_is_exact_and_present_canonical_records_dominate(canonical, fallback, expected):
    frozen = deepcopy((canonical, fallback))
    assert device_config_capture(canonical, fallback) is expected
    assert (canonical, fallback) == frozen
