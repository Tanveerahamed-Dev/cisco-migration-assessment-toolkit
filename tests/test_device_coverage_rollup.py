"""The ephemeral coverage index owns exact joins and a conservative stored-state fold."""
from copy import deepcopy

import pytest

from cisco_toolkit.coverage_matrix import (
    COVERAGE_DIMENSIONS,
    COVERAGE_STATE_ORDER,
    COVERAGE_VERDICT_SOURCES,
    compute_coverage_matrix,
    compute_device_coverage,
    index_coverage_rows,
    match_coverage_cell,
)


def _cell(host, axis, state="covered", *, dimension=None, source=None):
    return {
        "device": host, "axis": axis, "dimension": dimension or axis,
        "state": state,
        "verdict_source": source or {
            "collection": "collection_completeness", "capture": "capture_integrity", "parse": "parse_yield",
        }[axis],
        "is_abstention": state != "covered", "evidence": "",
    }


def _core(host="edgeA"):
    return [_cell(host, "collection"), _cell(host, "capture"), _cell(host, "parse")]


def _by(rows):
    return {host: {row["axis"]: row["state"] for row in rows if row["device"] == host}
            for host in {row["device"] for row in rows}}


def test_public_vocabularies_have_the_agreed_evidence_limit_precedence():
    assert COVERAGE_STATE_ORDER == (
        "not_collected", "unverified", "unparsed", "partial", "not_observed", "covered",
    )
    assert COVERAGE_DIMENSIONS == ("collection", "capture", "parse", "architecture")
    assert COVERAGE_VERDICT_SOURCES == (
        "collection_completeness", "capture_integrity", "parse_yield", "architecture_coverage",
    )
    assert len(set(COVERAGE_STATE_ORDER)) == len(COVERAGE_STATE_ORDER)


def test_real_producer_rollups_keep_the_known_device_verdicts_and_fleet_boundary():
    snap = {
        "devices": {"edgeA": {}, "half": {}, "blind": {}},
        "collection_completeness": {"devices": [
            {"host": "blind", "status": "not collected", "missing": ["all"]},
            {"host": "half", "status": "partial", "missing": ["version/inventory"]},
        ]},
        "capture_integrity": {"findings": [
            {"host": "edgeA", "status": "error", "command": "show version", "reason": "capture failed"},
        ]},
        "parse_yield": {"events": [
            {"device": "edgeA", "parser": "parse_ip_routes", "error": True, "cmd": "show ip route"},
        ]},
        "architecture_coverage": {"classes": [
            {"key": "fhrp_detail", "observed": True, "status": "clean", "hosts": ["edgeA"]},
            {"key": "lisp", "observed": False, "label": "LISP", "hosts": []},
        ]},
    }
    matrix = compute_coverage_matrix(snap)
    frozen = deepcopy((snap, matrix))
    index = index_coverage_rows(matrix["rows"])
    assert index.problem is None
    a = compute_device_coverage(matrix["by_device"], index, "edgeA")
    assert a is not None and a["worst"] == "unverified" and a["n_abstained"] == 2
    assert compute_device_coverage(matrix["by_device"], index, "half")["worst"] == "partial"
    assert compute_device_coverage(matrix["by_device"], index, "half")["n_abstained"] == 1
    blind = compute_device_coverage(matrix["by_device"], index, "blind")
    assert blind is not None and blind["worst"] == "not_collected" and blind["n_abstained"] == 3
    assert compute_device_coverage(matrix["by_device"], index, "(fleet)") is None
    assert matrix["by_device"]["edgeA"]["fhrp_detail"] == "covered"
    architecture = match_coverage_cell(index, "edgeA", "fhrp_detail", "covered")
    assert architecture is not None and architecture[1]["verdict_source"] == "architecture_coverage"
    assert [row["device"] for row in matrix["rows"] if row["state"] == "not_observed"] == ["(fleet)"]
    assert (snap, matrix) == frozen


def test_nominal_all_covered_is_a_mathematical_fold_not_a_projection_assurance():
    rows = _core()
    result = compute_device_coverage(_by(rows), index_coverage_rows(rows), "edgeA")
    # The projection must withhold/qualify zero and covered under its existing source-silence caveat.
    assert result == {"worst": "covered", "n_abstained": 0, "row_indices": [0, 1, 2]}


def test_core_and_architecture_cells_count_once_in_original_source_order():
    rows = [
        _cell("outside", "collection"),
        _cell("edgeA", "parse", "unparsed"),
        _cell("edgeA", "collection", "partial"),
        _cell("edgeA", "arch.a/b~x", dimension="architecture", source="architecture_coverage"),
        _cell("edgeA", "capture", "unverified"),
    ]
    result = compute_device_coverage(_by(rows), index_coverage_rows(rows), "edgeA")
    assert result == {"worst": "unverified", "n_abstained": 3, "row_indices": [1, 2, 3, 4]}


def test_exact_case_punctuation_and_whitespace_never_share_an_identity():
    rows = _core("leaf/1~a.b:2") + _core("Leaf/1~a.b:2") + _core(" leaf/1~a.b:2 ")
    index = index_coverage_rows(rows)
    assert index.problem is None
    assert match_coverage_cell(index, "leaf/1~a.b:2", "capture", "covered")[0] == 1
    assert match_coverage_cell(index, "Leaf/1~a.b:2", "capture", "covered")[0] == 4
    assert match_coverage_cell(index, " leaf/1~a.b:2 ", "capture", "covered")[0] == 7
    assert match_coverage_cell(index, "leaf/1~a.b:2", "Capture", "covered") is None
    assert compute_device_coverage(_by(rows), index, "leaf/1~a.b:2")["row_indices"] == [0, 1, 2]


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_exact_rows_are_ambiguous_even_when_identical(conflict):
    rows = _core()
    duplicate = deepcopy(rows[0])
    if conflict:
        duplicate.update(state="partial", is_abstention=True)
    rows.append(duplicate)
    index = index_coverage_rows(rows)
    assert index.problem is None
    assert [position for position, _record in index.by_key[("edgeA", "collection")]] == [0, 3]
    assert match_coverage_cell(index, "edgeA", "collection", "covered") is None
    assert compute_device_coverage(_by(rows[:3]), index, "edgeA") is None


@pytest.mark.parametrize("raw", [None, {}, (), "rows"])
def test_missing_or_wrong_row_container_has_no_usable_index(raw):
    index = index_coverage_rows(raw)
    assert index.problem
    assert match_coverage_cell(index, "edgeA", "collection", "covered") is None
    assert compute_device_coverage({"edgeA": {"collection": "covered"}}, index, "edgeA") is None


@pytest.mark.parametrize("bad", [None, [], 1, {}, {"device": "edgeA"}, {"axis": "collection"},
                               {"device": [], "axis": "collection"},
                               {"device": "edgeA", "axis": {}},
                               {"device": "", "axis": "collection"},
                               {"device": "edgeA", "axis": " "},
                               {"device": "\ud800", "axis": "collection"}])
def test_unreadable_subject_row_might_be_any_device_so_it_withholds_every_match(bad):
    rows = _core() + [bad]
    index = index_coverage_rows(rows)
    assert index.problem
    assert index.unreadable_indices == (3,)
    assert [position for position, _record in index.by_key[("edgeA", "collection")]] == [0]
    assert match_coverage_cell(index, "edgeA", "collection", "covered") is None
    assert compute_device_coverage(_by(rows[:3]), index, "edgeA") is None


@pytest.mark.parametrize("edit", [
    lambda row: row.update(state="unknown"), lambda row: row.update(state=None),
    lambda row: row.update(state=1), lambda row: row.update(dimension="other"),
    lambda row: row.update(dimension="parse"), lambda row: row.update(dimension=[]),
    lambda row: row.update(verdict_source="other"), lambda row: row.update(verdict_source=[]),
    lambda row: row.update(verdict_source="capture_integrity "),
    lambda row: row.update(is_abstention=1), lambda row: row.update(is_abstention=0),
    lambda row: row.update(is_abstention=False), lambda row: row.pop("is_abstention"),
    lambda row: row.pop("dimension"), lambda row: row.pop("verdict_source"),
    lambda row: row.update(verdict_source="collection_completeness"),
    lambda row: row.update(state="partial", is_abstention=True),
])
def test_wrong_metadata_or_type_aliases_cannot_authorize_an_exact_cell(edit):
    rows = _core()
    rows[1].update(state="unverified", is_abstention=True)
    expected = _by(rows)
    edit(rows[1])
    index = index_coverage_rows(rows)
    assert index.problem is None  # identity is readable; payload failure is scoped
    assert match_coverage_cell(index, "edgeA", "capture", "unverified") is None
    assert compute_device_coverage(expected, index, "edgeA") is None


@pytest.mark.parametrize("axis", ["capture", "parse"])
def test_collection_source_is_allowed_only_for_an_explicit_not_collected_cell(axis):
    rows = _core()
    position = {"capture": 1, "parse": 2}[axis]
    rows[position].update(state="not_collected", verdict_source="collection_completeness", is_abstention=True)
    index = index_coverage_rows(rows)
    assert match_coverage_cell(index, "edgeA", axis, "not_collected")[0] == position
    result = compute_device_coverage(_by(rows), index, "edgeA")
    assert result is not None and result["worst"] == "not_collected" and result["n_abstained"] == 1
    rows[position].update(state="covered", is_abstention=False)
    assert match_coverage_cell(index_coverage_rows(rows), "edgeA", axis, "covered") is None


def test_architecture_source_and_core_dimension_cannot_be_interchanged():
    rows = _core() + [_cell("edgeA", "fhrp_detail", dimension="architecture", source="architecture_coverage")]
    assert compute_device_coverage(_by(rows), index_coverage_rows(rows), "edgeA") is not None
    rows[-1]["verdict_source"] = "parse_yield"
    assert compute_device_coverage(_by(rows), index_coverage_rows(rows), "edgeA") is None
    rows[-1].update(axis="collection", verdict_source="architecture_coverage")
    assert match_coverage_cell(index_coverage_rows(rows), "edgeA", "collection", "covered") is None


def test_not_observed_architecture_is_fleet_only_and_cannot_be_promoted_to_a_device_axis():
    rows = _core() + [_cell("edgeA", "lisp", "not_observed", dimension="architecture", source="architecture_coverage")]
    index = index_coverage_rows(rows)
    assert index.problem is None
    assert match_coverage_cell(index, "edgeA", "lisp", "not_observed") is None
    assert compute_device_coverage(_by(rows), index, "edgeA") is None
    rows[-1]["device"] = "(fleet)"
    assert compute_device_coverage(_by(rows), index_coverage_rows(rows), "edgeA") == {
        "worst": "covered", "n_abstained": 0, "row_indices": [0, 1, 2],
    }


def test_owner_index_failure_fallback_never_authorizes_a_cell_or_rollup():
    assert match_coverage_cell(None, "edgeA", "collection", "covered") is None
    assert compute_device_coverage(_by(_core()), None, "edgeA") is None


def test_a_stored_cell_that_disagrees_with_its_single_row_is_withheld():
    rows = _core()
    by_device = _by(rows)
    by_device["edgeA"]["capture"] = "unverified"
    assert match_coverage_cell(index_coverage_rows(rows), "edgeA", "capture", "unverified") is None
    assert compute_device_coverage(by_device, index_coverage_rows(rows), "edgeA") is None


@pytest.mark.parametrize("by_device", [None, [], {}, {"edgeA": None}, {"edgeA": []}, {"edgeA": {}},
                                     {"edgeA": {"collection": "covered"}},
                                     {"edgeA": {"collection": "covered", "capture": "covered", "parse": True}}])
def test_missing_empty_or_unreadable_device_mapping_is_not_zero(by_device):
    assert compute_device_coverage(by_device, index_coverage_rows(_core()), "edgeA") is None


def test_device_axis_universe_must_match_the_entire_stored_source_for_that_device():
    rows = _core() + [_cell("edgeA", "aci", dimension="architecture", source="architecture_coverage")]
    assert compute_device_coverage(_by(rows[:3]), index_coverage_rows(rows), "edgeA") is None
    by_device = _by(rows[:3])
    by_device["edgeA"]["missing-row"] = "covered"
    assert compute_device_coverage(by_device, index_coverage_rows(rows[:3]), "edgeA") is None


def test_known_other_subject_bad_payload_does_not_poison_the_selected_device():
    rows = _core() + _core("outside")
    rows[-1]["state"] = "future_unknown_state"
    index = index_coverage_rows(rows)
    assert index.problem is None
    assert compute_device_coverage(_by(rows), index, "edgeA") == {
        "worst": "covered", "n_abstained": 0, "row_indices": [0, 1, 2],
    }
    assert compute_device_coverage(_by(rows), index, "outside") is None


def test_source_index_match_and_rollup_outputs_do_not_mutate_or_alias_each_other():
    rows = _core()
    rows[0]["unrelated"] = {"nested": [1, 2]}
    by_device = _by(rows)
    frozen = deepcopy((rows, by_device))
    index = index_coverage_rows(rows)
    match = match_coverage_cell(index, "edgeA", "collection", "covered")
    assert match is not None
    assert set(match[1]) == {"device", "axis", "state", "dimension", "verdict_source", "is_abstention"}
    match[1]["state"] = "partial"
    assert index.by_key[("edgeA", "collection")][0][1]["state"] == "covered"
    assert index.by_key[("edgeA", "collection")][0][1]["unrelated"] == {"nested": [1, 2]}
    result = compute_device_coverage(by_device, index, "edgeA")
    assert result is not None
    result["row_indices"].append(99)
    assert compute_device_coverage(by_device, index, "edgeA")["row_indices"] == [0, 1, 2]
    # The index owns its row dictionary; unrelated subtrees remain read-only source views.
    index.by_key[("edgeA", "collection")][0][1]["state"] = "partial"
    assert (rows, by_device) == frozen


def test_unrelated_nested_payload_is_not_copied_or_exposed_by_a_match():
    class MustNotCopy:
        def __deepcopy__(self, memo):
            raise AssertionError("unvalidated extra payload must not be copied")

    rows = _core()
    rows[0]["unrelated"] = MustNotCopy()
    index = index_coverage_rows(rows)
    match = match_coverage_cell(index, "edgeA", "collection", "covered")
    assert match is not None and "unrelated" not in match[1]
    assert compute_device_coverage(_by(rows), index, "edgeA") == {
        "worst": "covered", "n_abstained": 0, "row_indices": [0, 1, 2],
    }


def test_failed_phase_state_copies_are_not_a_coverage_verdict_or_zero():
    rows = _core()
    by_device = _by(rows)
    rows[1].update(state="analysis_unavailable", is_abstention=True)
    by_device["edgeA"]["capture"] = "analysis_unavailable"
    assert compute_device_coverage(by_device, index_coverage_rows(rows), "edgeA") is None
    # Attribution to a real failed phase is a separate projection gate; the pure index cannot invent it.
    assert compute_device_coverage({"edgeA": {}}, index_coverage_rows([]), "edgeA") is None


@pytest.mark.parametrize("host,axis,state", [(None, "collection", "covered"), ([], "collection", "covered"),
                                          ("edgeA", [], "covered"), ("edgeA", "collection", []),
                                          ("edgeA", "collection", True), ("missing", "collection", "covered")])
def test_unreadable_unknown_selection_or_state_is_never_normalized_into_a_match(host, axis, state):
    assert match_coverage_cell(index_coverage_rows(_core()), host, axis, state) is None
