"""G15: select stored STP observations without re-electing or turning parser defaults into facts.

These fixtures and real parser/producer calls execute only in the hosted suite. No captured bridge address is
invented: the legacy parser drops it, so a published False is explicitly only its stored flag.
"""
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, parse, ui_projection as uip

PUB, NC, UV, AU, CBE = "published", "not_collected", "unverified", "analysis_unavailable", "collected_but_empty"
FIELDS = ("is_root", "root_address", "root_priority")


def _record(**changes):
    return {"is_root": True, "root_address": "aaaa.0000.0001", "root_priority": 32778, **changes}


def _snapshot(roots):
    # Deliberately stored minimal VLAN row: observation selection does not require or compute an election.
    return {"stp_roots": roots, "vlan_cutover": [{"vlan": 10}]}


def _selection(snap):
    return uip.project_inventory(snap)["vlans"]["rows"]["items"][0]["selections"]["stp_roots"]


def _observation(record):
    return _selection(_snapshot({"edge": {"10": record}}))["items"][0]


def _validate(snap):
    document = uip.project(snap)
    errors = list(Draft202012Validator(uip.ui_projection_schema()).iter_errors(document))
    assert not errors, [(list(error.path), error.message) for error in errors]
    return document


def test_real_parser_root_and_nonroot_keep_their_stored_fields_and_scope():
    roots = parse.parse_spanning_tree_root("""VLAN0010
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             This bridge is the root
  Bridge ID  Priority    24586
             Address     aaaa.0001.0001
VLAN0030
  Root ID    Priority    32798
             Address     cccc.0003.0003
  Bridge ID  Priority    32798
             Address     aaaa.0001.0001
""")
    assert roots["10"]["is_root"] is True and roots["30"]["is_root"] is False
    assert all("bridge_address" not in record for record in roots.values())
    snap = {"stp_roots": {"edge.lab": roots}, "vlan_cutover": [{"vlan": 10}, {"vlan": 30}]}
    before = copy.deepcopy(snap)
    rows = uip.project_inventory(snap)["vlans"]["rows"]["items"]
    for row, key in zip(rows, ("10", "30")):
        selection = row["selections"]["stp_roots"]
        assert selection["state"] == PUB and len(selection["items"]) == 1
        item = selection["items"][0]
        assert item["host"] == "edge.lab" and item["pointer"] == f"/stp_roots/edge.lab/{key}"
        for field in FIELDS:
            fact = item[field]
            assert (fact["state"], fact["value"]) == (PUB, roots[key][field])
            assert fact["subject"] == f"{item['pointer']}/{field}"
            assert {"pointer": fact["subject"], "role": "subject"} in fact["refs"]
        assert "row_selection_by_exact_key" in item["is_root"]["caveats"]
    limitation = next(item for item in uip.LIMITATIONS if item["id"] == "row_selection_by_exact_key")
    assert "does not independently prove a non-root device or complete capture" in limitation["text"]
    assert "bridge_address" in limitation["text"]
    _validate(snap)
    assert snap == before


def test_header_only_parser_default_is_not_an_observed_false_and_explicit_true_survives():
    parsed = parse.parse_spanning_tree_root("VLAN0010\n  Spanning tree enabled protocol rstp\n")
    assert parsed["10"]["is_root"] is False and parsed["10"]["root_address"] == ""
    assert parsed["10"]["root_priority"] is None
    item = _observation(parsed["10"])
    for field in FIELDS:
        assert item[field]["state"] == NC and item[field]["value"] is None
        assert "not parsed" in item[field]["reason"]
    # The positive raw marker is not lost just because the parser retained no root identity.
    positive = _observation({"is_root": True})
    assert positive["is_root"]["state"] == PUB and positive["is_root"]["value"] is True
    assert positive["root_address"]["state"] == positive["root_priority"]["state"] == NC


@pytest.mark.parametrize("bad", [None, 0, 1, "false", "true", [], {}, 0.0])
@pytest.mark.parametrize("address", ["", "aaaa.0000.0001"])
def test_malformed_boolean_is_unverified_before_any_parser_default_guard(bad, address):
    item = _observation(_record(is_root=bad, root_address=address))
    assert item["is_root"]["state"] == UV and item["is_root"]["value"] is None
    assert "not a boolean" in item["is_root"]["reason"]
    assert item["root_priority"]["state"] == PUB and item["root_priority"]["value"] == 32778


def test_missing_flag_and_independently_invalid_identity_fields_are_not_coerced():
    assert _observation({"root_address": "aaaa.0000.0001"})["is_root"]["state"] == NC
    for bad_address in (None, 1, False, [], {}):
        item = _observation(_record(is_root=False, root_address=bad_address))
        assert item["is_root"]["state"] == item["root_address"]["state"] == UV
        assert item["root_priority"]["state"] == PUB
        positive = _observation(_record(root_address=bad_address))
        assert positive["is_root"]["value"] is True and positive["root_address"]["state"] == UV
    for missing_address in ({"is_root": False}, {"is_root": False, "root_address": " \t "}):
        assert _observation(missing_address)["is_root"]["state"] == NC


@pytest.mark.parametrize("priority,want", [(0, 0), (32778, 32778), (32778.0, 32778), (2**53 - 1, 2**53 - 1)])
def test_priority_uses_the_canonical_count_admission_and_zero_is_observed(priority, want):
    fact = _observation(_record(root_priority=priority))["root_priority"]
    assert fact["state"] == PUB and fact["value"] == want and type(fact["value"]) is int


@pytest.mark.parametrize("priority", [True, False, "32778", 1.5, -1, 2**53, float("nan"), float("inf"), [], {}])
def test_invalid_priority_is_held_without_hiding_readable_flag_or_address(priority):
    item = _observation(_record(root_priority=priority))
    assert item["root_priority"]["state"] == UV and item["root_priority"]["value"] is None
    assert item["is_root"]["value"] is True and item["root_address"]["value"] == "aaaa.0000.0001"


def test_mixed_unreadable_records_and_host_maps_preserve_rows_without_complete_selection():
    snap = _snapshot({"good": {"10": _record()}, "bad-row": {"10": None}, "bad-map": []})
    selected = _selection(snap)
    assert selected["state"] == UV
    rows = {row["host"]: row for row in selected["items"]}
    assert set(rows) == {"good", "bad-row"}
    assert rows["good"]["is_root"]["value"] is True
    assert all(rows["bad-row"][field]["state"] == UV for field in FIELDS)
    assert {"pointer": "/stp_roots/bad-row/10", "role": "witness"} in selected["refs"]
    assert {"pointer": "/stp_roots/bad-map", "role": "witness"} in selected["refs"]
    _validate(snap)


def test_duplicate_true_claimants_remain_observations_beside_ambiguous_owner_election():
    roots = {"a": {"10": _record()}, "b": {"10": _record(root_address="bbbb.0000.0002")}}
    snap = {"stp_roots": roots, "vlan_cutover": analyze.compute_vlan_cutover_matrix({}, roots)}
    row = uip.project_inventory(snap)["vlans"]["rows"]["items"][0]
    assert row["stp_root_state"]["value"] == "ambiguous"
    assert row["stp_root"]["state"] == row["stp_root_default_election"]["state"] == UV
    assert [item["host"] for item in row["selections"]["stp_roots"]["items"]] == ["a", "b"]
    assert all(item["is_root"]["value"] is True for item in row["selections"]["stp_roots"]["items"])
    _validate(snap)


def test_alias_spelling_escaped_host_and_mst_exclusion_keep_original_pointer_identity():
    snap = _snapshot({"edge.lab/a~b": {" 0010 ": _record(), "10": _record(is_root=False),
                                      "11": _record(), "١٠": _record()},
                      "mst": {"10": _record(is_mst=True)}})
    selected = _selection(snap)
    assert [row["pointer"] for row in selected["items"]] == [
        "/stp_roots/edge.lab~1a~0b/ 0010 ", "/stp_roots/edge.lab~1a~0b/10"]
    assert [row["is_root"]["value"] for row in selected["items"]] == [True, False]
    assert {row["host"] for row in selected["items"]} == {"edge.lab/a~b"}
    _validate(snap)


def test_unique_integer_key_roundtrip_and_pointer_collision_refusal():
    snap = _snapshot({"edge": {10: _record()}})
    assert _selection(snap) == _selection(json.loads(json.dumps(snap)))
    snap["stp_roots"]["edge"]["10"] = _record(is_root=False)
    selected = _selection(snap)
    assert selected["state"] == UV and selected["items"] == [] and "collide" in selected["reason"]


def test_absent_empty_failed_and_invalid_selector_have_distinct_honest_states():
    snap = {"vlan_cutover": [{"vlan": 10}]}
    assert _selection(snap)["state"] == NC and _selection(snap)["items"] == []
    for roots in ({}, {"edge": {}}, {"edge": {"11": _record()}}):
        selected = _selection(_snapshot(roots))
        assert selected["state"] == CBE and selected["items"] == []
        assert "neither root absence nor complete capture" in selected["reason"]
    snap = _snapshot({"edge": {"10": _record()}})
    snap["assessment_integrity"] = {"stp_roots": "failed"}
    selected = _selection(snap)
    assert selected["state"] == AU
    assert all(fact["state"] == AU and fact["value"] is None for row in selected["items"]
               for field, fact in row.items() if field in FIELDS)
    assert {"pointer": "/assessment_integrity/stp_roots", "role": "failure_record"} in selected["refs"]
    for invalid in (None, "10", True, -1):
        snap = _snapshot({"edge": {"10": _record()}})
        snap["vlan_cutover"][0]["vlan"] = invalid
        selected = _selection(snap)
        assert selected["state"] == UV and selected["items"] == []


@pytest.mark.parametrize("roots", [None, [], "missing", 5, {"bad-map": []}, {"": {"10": _record()}}])
def test_unreadable_root_source_never_publishes_a_complete_empty_selection(roots):
    selected = _selection(_snapshot(roots))
    assert selected["state"] in (NC, UV) and selected["items"] == [] and selected["reason"]


def test_blind_host_custody_is_kept_without_dotted_path_join_or_true_leak():
    snap = _snapshot({"edge.lab": {"10": _record()}})
    snap["collection_completeness"] = {"devices": [{"host": "edge.lab", "status": "not collected"}]}
    item = _selection(snap)["items"][0]
    for field in FIELDS:
        assert item[field]["state"] == NC and item[field]["value"] is None
        assert {"pointer": "/collection_completeness/devices/0", "role": "witness"} in item[field]["refs"]


def test_closed_schema_and_no_input_or_output_aliasing():
    snap = _snapshot({"edge": {"10": _record()}})
    before = copy.deepcopy(snap)
    document = _validate(snap)
    assert snap == before
    definition = uip.ui_projection_schema()["$defs"]["StpRootObservation"]
    assert set(definition["required"]) == {"host", "pointer", *FIELDS}
    assert definition["additionalProperties"] is False
    row = document["inventory"]["vlans"]["rows"]["items"][0]["selections"]["stp_roots"]["items"][0]
    row["is_root"]["value"] = "false"
    assert list(Draft202012Validator(uip.ui_projection_schema()).iter_errors(document))
    assert snap == before and _selection(snap)["items"][0]["is_root"]["value"] is True
    document = _validate(snap)
    row = document["inventory"]["vlans"]["rows"]["items"][0]["selections"]["stp_roots"]["items"][0]
    row["bridge_address"] = "not retained by the producer"
    assert list(Draft202012Validator(uip.ui_projection_schema()).iter_errors(document))


@pytest.mark.parametrize("marker", ["false", 1, [False], {"unknown": True}, None, 0, "", [], {}])
@pytest.mark.parametrize("with_good", [False, True])
def test_unknown_namespace_withholds_completeness_without_losing_original_witness(marker, with_good):
    roots = {"suspect": {"10": _record(is_mst=marker)}}
    if with_good:
        roots["good"] = {"10": _record()}
    snap = _snapshot(roots)
    selected = _selection(snap)
    assert selected["state"] == UV and "namespace" in selected["reason"]
    for pointer in ("/stp_roots/suspect/10", "/stp_roots/suspect/10/is_mst"):
        assert {"pointer": pointer, "role": "witness"} in selected["refs"]
    observed = {row["host"]: row for row in selected["items"]}
    if with_good:
        assert observed["good"]["is_root"]["value"] is True
    if marker:
        assert "suspect" not in observed  # Unchanged owner eligibility, no definite VLAN admission.
    else:
        assert all(observed["suspect"][field]["state"] == UV and observed["suspect"][field]["value"] is None
                   for field in FIELDS)
    _validate(snap)


def test_real_namespace_markers_legacy_selection_and_other_vlans_are_unchanged():
    for raw in (_record(), _record(is_mst=False)):
        selected = _selection(_snapshot({"edge": {"10": raw}}))
        assert selected["state"] == PUB and selected["items"][0]["is_root"]["value"] is True
    assert _selection(_snapshot({"edge": {"10": _record(is_mst=True)}}))["state"] == CBE
    snap = {"stp_roots": {"suspect": {"10": _record(is_mst="false")}, "good": {"20": _record()}},
            "vlan_cutover": [{"vlan": 10}, {"vlan": 20}]}
    rows = uip.project_inventory(snap)["vlans"]["rows"]["items"]
    assert rows[0]["selections"]["stp_roots"]["state"] == UV
    assert rows[1]["selections"]["stp_roots"]["state"] == PUB


def test_namespace_integer_pointer_witness_and_failed_source_precedence():
    snap = _snapshot({"suspect": {10: _record(is_mst=0)}, "good": {"10": _record()}})
    selected = _selection(snap)
    marker = {"pointer": "/stp_roots/suspect/10/is_mst", "role": "witness"}
    assert selected["state"] == UV and marker in selected["refs"]
    suspect = next(row for row in selected["items"] if row["host"] == "suspect")
    assert all(marker in suspect[field]["refs"] and suspect[field]["state"] == UV for field in FIELDS)
    assert selected == _selection(json.loads(json.dumps(snap)))
    snap["assessment_integrity"] = {"stp_roots": "failed"}
    selected = _selection(snap)
    assert selected["state"] == AU and marker in selected["refs"]
    assert all(row[field]["state"] == AU and row[field]["value"] is None
               for row in selected["items"] for field in FIELDS)
    assert selected == _selection(json.loads(json.dumps(snap)))
