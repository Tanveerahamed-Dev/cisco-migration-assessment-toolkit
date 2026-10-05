"""W13 source-admission controls; execution belongs to hosted CI, not field qualification."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cisco_toolkit import coverage_matrix as cm
from cisco_toolkit import ui_projection as uip

HOST = "edge/a~b"


def snapshot():
    snap = {
        "schema": "collect_parse_snapshot/1",
        "devices": {HOST: {"hostname": HOST}},
        "collection_completeness": {"devices": [], "summary": {"inventory": 1, "collected": 1}},
        "capture_integrity": {"findings": [{"host": HOST, "command": "show version",
                                            "status": "empty", "reason": "synthetic empty capture"}]},
        "parse_yield": {"events": []}, "architecture_coverage": {"classes": []},
    }
    snap["coverage_matrix"] = cm.compute_coverage_matrix(snap)
    return snap


def page(snap, host=HOST):
    return uip.project_device(snap, host)["device"]


def cells(snap):
    return {item["axis"]: item for item in page(snap)["coverage"]["items"]}


def held(rollup, state):
    for fact in rollup.values():
        assert fact["state"] == state
        assert fact["value"] is None
        assert fact["reason"]


def test_real_producer_metadata_and_rollup_agree_without_mutating_source():
    snap = snapshot()
    before = deepcopy(snap)
    output = page(snap)
    rows = snap["coverage_matrix"]["rows"]
    for item in output["coverage"]["items"]:
        matches = [(i, row) for i, row in enumerate(rows) if row["device"] == HOST and row["axis"] == item["axis"]]
        assert len(matches) == 1
        index, raw = matches[0]
        assert item["fact"]["value"] == {"axis": raw["axis"], "state": raw["state"]}
        for field in ("dimension", "verdict_source", "is_abstention"):
            assert item[field]["state"] == "published"
            assert type(item[field]["value"]) is type(raw[field])
            assert item[field]["value"] == raw[field]
            assert item[field]["subject"] == f"/coverage_matrix/rows/{index}/{field}"
            assert {"role": "witness", "pointer": "/coverage_matrix/by_device/edge~1a~0b/" + item["axis"]} in item[field]["refs"]
    assert output["coverage_rollup"]["worst"]["value"] == "unverified"
    assert output["coverage_rollup"]["n_abstained"]["value"] == 1
    inventory = uip.project(snap)["inventory"]["devices"]["rows"]["items"]
    assert inventory[0]["coverage"] == output["coverage_rollup"]
    assert snap == before


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong_case", "wrong_axis", "contradict_state",
                                     "wrong_dimension", "wrong_source", "integer_flag", "wrong_flag", "unreadable"])
def test_ambiguous_or_contradictory_join_withholds_cell_and_all_metadata(mutation):
    snap = snapshot()
    rows = snap["coverage_matrix"]["rows"]
    index = next(i for i, row in enumerate(rows) if row["axis"] == "capture")
    raw = rows[index]
    if mutation == "duplicate":
        rows.append(deepcopy(raw))
    elif mutation == "missing":
        rows.pop(index)
    elif mutation == "wrong_case":
        raw["device"] = HOST.upper()
    elif mutation == "wrong_axis":
        raw["axis"] = "Capture"
    elif mutation == "contradict_state":
        raw["state"] = "covered"
        raw["is_abstention"] = False
    elif mutation == "wrong_dimension":
        raw["dimension"] = "parse"
    elif mutation == "wrong_source":
        raw["verdict_source"] = "parse_yield"
    elif mutation == "integer_flag":
        raw["is_abstention"] = 1
    elif mutation == "wrong_flag":
        raw["is_abstention"] = False
    else:
        rows.append({"device": None, "axis": "capture"})
    capture = cells(snap)["capture"]
    for field in ("fact", "dimension", "verdict_source", "is_abstention"):
        held({field: capture[field]}, "unverified")
    held(page(snap)["coverage_rollup"], "unverified")
    if mutation == "duplicate":
        references = capture["dimension"]["refs"]
        assert {"role": "witness", "pointer": f"/coverage_matrix/rows/{index}"} in references
        assert {"role": "witness", "pointer": f"/coverage_matrix/rows/{len(rows) - 1}"} in references


def test_zero_and_all_covered_remain_unverified_even_with_explicit_stored_rows():
    snap = snapshot()
    snap["capture_integrity"]["findings"] = []
    snap["coverage_matrix"] = cm.compute_coverage_matrix(snap)
    output = page(snap)
    assert all(item["fact"]["value"]["state"] == "covered" for item in output["coverage"]["items"])
    held(output["coverage_rollup"], "unverified")
    assert all("coverage_matrix_shown_as_published" in fact["caveats"] for fact in output["coverage_rollup"].values())


def test_empty_missing_and_blind_axes_never_become_zero():
    snap = snapshot()
    snap.pop("coverage_matrix")
    held(page(snap)["coverage_rollup"], "not_collected")
    snap = snapshot()
    snap["coverage_matrix"]["by_device"][HOST] = {}
    held(page(snap)["coverage_rollup"], "not_collected")
    snap = snapshot()
    snap["collection_completeness"]["devices"] = [{"host": HOST, "status": "Not collected", "missing": []}]
    held(page(snap)["coverage_rollup"], "not_collected")


@pytest.mark.parametrize("host", ["absent", None, 3, {}, []])
def test_forced_unknown_host_keeps_new_rollup_facts_bare(host):
    output = page(snapshot(), host)
    for fact in output["coverage_rollup"].values():
        assert fact["value"] is None and fact["refs"] == []
        assert fact["state"] == ("not_collected" if isinstance(host, str) else "unverified")


def test_failed_matrix_producer_outranks_present_consistent_coverage():
    snap = snapshot()
    snap["assessment_integrity"] = {"failed_phases": ["Design blueprint"]}
    held(page(snap)["coverage_rollup"], "analysis_unavailable")
    assert page(snap)["coverage"]["state"] == "analysis_unavailable"


def test_one_projection_builds_one_index_and_one_rollup_per_exact_device(monkeypatch):
    snap = snapshot()
    observed = {"index": 0, "fold": 0}
    original_index, original_fold = uip.index_coverage_rows, uip.compute_device_coverage

    def index(raw):
        observed["index"] += 1
        return original_index(raw)

    def fold(raw, indexed, host):
        observed["fold"] += 1
        return original_fold(raw, indexed, host)

    monkeypatch.setattr(uip, "index_coverage_rows", index)
    monkeypatch.setattr(uip, "compute_device_coverage", fold)
    ctx = uip._Ctx(snap)
    first = uip._device_coverage_rollup(ctx, HOST)
    second = uip._device_coverage_rollup(ctx, HOST)
    assert first == second and observed == {"index": 1, "fold": 1}


@pytest.mark.parametrize("mutation", ["missing_rollup", "extra_rollup", "bad_worst", "bool_count", "negative_count",
                                     "unsafe_count", "missing_dimension", "extra_metadata", "bad_dimension",
                                     "bad_source", "integer_flag", "withheld_value"])
def test_new_device_schema_is_closed_and_rejects_hostile_shapes(mutation):
    document = uip.project_device(snapshot(), HOST)
    schema = uip.ui_projection_schema()
    validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                      "$ref": "#/$defs/DeviceDocument"})
    validator.validate(document)
    output = document["device"]
    rollup = output["coverage_rollup"]
    item = output["coverage"]["items"][0]
    if mutation == "missing_rollup":
        del output["coverage_rollup"]
    elif mutation == "extra_rollup":
        rollup["assurance"] = True
    elif mutation == "bad_worst":
        rollup["worst"]["value"] = "healthy"
    elif mutation == "bool_count":
        rollup["n_abstained"]["value"] = True
    elif mutation == "negative_count":
        rollup["n_abstained"]["value"] = -1
    elif mutation == "unsafe_count":
        rollup["n_abstained"]["value"] = 2**53
    elif mutation == "missing_dimension":
        del item["dimension"]
    elif mutation == "extra_metadata":
        item["all_covered"] = True
    elif mutation == "bad_dimension":
        item["dimension"]["value"] = "risk"
    elif mutation == "bad_source":
        item["verdict_source"]["value"] = "foreign"
    elif mutation == "integer_flag":
        item["is_abstention"]["value"] = 0
    else:
        item["dimension"].update(state="unverified", reason="synthetic withheld", value="collection")
    with pytest.raises(ValidationError):
        validator.validate(document)
