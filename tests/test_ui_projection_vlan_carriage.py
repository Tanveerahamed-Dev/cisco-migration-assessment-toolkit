"""Stored G14 carriage facts; real producer fixtures and declared hostile mutations.

These controls are authored for hosted execution. They never replace missing stored
carriage with the legacy simulation predicate or reconstruct a VLAN universe.
"""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ui_projection as uip, vlan_carriage
from test_vlan_carriage import A, B, PORT, _fleet, _observation


def snapshot(allowed=("10", "10"), observations=None, vlans=None):
    interfaces = _fleet(*allowed)
    cables = analyze.compute_cable_map(interfaces)
    rows = [{"vlan": 10}] if vlans is None else vlans
    stored = vlan_carriage.compute_vlan_carriage(cables, interfaces, observations, rows)
    assert vlan_carriage.validate_vlan_carriage(stored) == (True, "ok")
    return {"interfaces": {h: {p: asdict(rec) for p, rec in records.items()}
                           for h, records in interfaces.items()},
            "cable_map": cables, "stp_topology_observations": observations,
            "vlan_cutover": rows, "vlan_carriage": stored}


def selection(snap, index=0):
    return uip.project_inventory(snap)["vlans"]["rows"]["items"][index]["selections"]["carriage"]


def checked(snap):
    before = deepcopy(snap)
    result = uip.project(snap)
    errors = list(Draft202012Validator(uip.ui_projection_schema()).iter_errors(result))
    assert not errors, [(list(error.path), error.message) for error in errors]
    assert snap == before
    # Strict serialization and every emitted ref must still address the input.
    json.dumps(result, allow_nan=False)
    pending = [result]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for ref in item.get("refs", []):
                assert uip._stored_pointer_tokens(uip._Ctx(snap), ref["pointer"]) is not None, ref
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return result


@pytest.mark.parametrize("allowed,observations,state,relation,shape,basis", [
    (("10", "10"), None, "published", "forwarding", "both_ends", "stored_trunk_allowance"),
    (("none", "none"), None, "published", "not_carried", "both_ends", "stored_trunk_allowance"),
    (("", ""), {A: _observation("BLK"), B: _observation()}, "published", "stp_blocked", "both_ends", "typed_pvst"),
    (("", ""), {A: _observation("BLK")}, "not_collected", None, "one_end_only", "none"),
    (("", ""), None, "not_collected", None, "no_evidence", "none"),
])
def test_actual_stored_relations_and_missing_ends_are_distinct(allowed, observations, state, relation, shape, basis):
    snap = snapshot(allowed, observations)
    result = selection(snap)
    assert result["state"] == state
    assert len(result["items"]) == 1
    row = result["items"][0]
    assert (row["relation"]["state"], row["relation"]["value"]) == (state, relation)
    assert row["evidence_shape"]["value"] == shape and row["basis"]["value"] == basis
    assert row["pointer"] == "/vlan_carriage/rows/0"
    assert row["cable_pointer"] == "/cable_map/cables/0"
    assert row["ends"]["value"]["a"] == A
    assert "stored_vlan_carriage_scope" in row["relation"]["caveats"]
    assert row["members"]["items"][0]["a"]["port"]["value"] == PORT
    if shape == "one_end_only":
        member = row["members"]["items"][0]
        assert member["a"]["signal"]["value"] == "blocked"
        assert member["b"]["signal"]["state"] == "not_collected"
        assert member["b"]["signal"]["value"] is None
    checked(snap)


def test_projection_is_stored_only_and_does_not_call_any_carriage_or_root_producer(monkeypatch):
    snap = snapshot(vlans=[{"vlan": 10}, {"vlan": 20}])
    def forbidden(*_args, **_kwargs):
        raise AssertionError("rendering must not recompute")
    monkeypatch.setattr(vlan_carriage, "compute_vlan_carriage", forbidden)
    monkeypatch.setattr(analyze, "_link_carries", forbidden)
    monkeypatch.setattr(analyze, "build_network_model", forbidden)
    monkeypatch.setattr(analyze, "compute_vlan_cutover_matrix", forbidden)
    assert selection(snap, 0)["items"][0]["relation"]["value"] == "forwarding"
    assert selection(snap, 1)["items"][0]["relation"]["value"] == "not_carried"
    del snap["vlan_carriage"]
    held = selection(snap)
    assert held["state"] == "not_collected" and held["items"] == []
    checked(snap)


@pytest.mark.parametrize("damage", ["unknown_schema", "malformed_tail", "unknown_relation", "extra_field",
                                   "withheld_relation", "boolean_census", "missing_member", "vlan_moved",
                                   "cable_moved", "member_moved"])
def test_invalid_stored_contract_or_current_identity_never_recomputes(damage):
    snap = snapshot()
    stored = snap["vlan_carriage"]
    row = stored["rows"][0]
    if damage == "unknown_schema":
        stored["schema"] = "vlan_carriage/unknown"
    elif damage == "malformed_tail":
        stored["rows"].append(None)
    elif damage == "unknown_relation":
        row["relation"] = "assumed_forwarding"
    elif damage == "extra_field":
        row["health"] = "safe"
    elif damage == "withheld_relation":
        row["state"] = "not_collected"
    elif damage == "boolean_census":
        stored["coverage"]["emitted_pairs"] = True
    elif damage == "missing_member":
        row["members"] = []
    elif damage == "vlan_moved":
        snap["vlan_cutover"][0]["vlan"] = 20
    elif damage == "cable_moved":
        snap["cable_map"]["cables"][0]["a"] = "another-host"
    else:
        snap["cable_map"]["cables"][0]["members"][0]["a_port"] = "Gi1/0/2"
    listing = selection(snap)
    assert listing["state"] == "unverified" and listing["items"] == []
    assert any(ref["pointer"] == "/vlan_carriage" for ref in listing["refs"])
    checked(snap)


def test_empty_stored_cables_and_absent_section_have_different_states():
    snap = snapshot()
    snap["cable_map"]["cables"] = []
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    assert selection(snap)["state"] == "collected_but_empty"
    assert selection(snap)["items"] == []
    checked(snap)
    del snap["vlan_carriage"]
    assert selection(snap)["state"] == "not_collected"


def test_source_uncertainty_keeps_readable_member_evidence_and_no_completeness_promotion():
    snap = snapshot()
    snap["interfaces"]["orphan"] = {"Gi1/0/2": None}
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    listing = selection(snap)
    assert listing["state"] == "unverified" and len(listing["items"]) == 1
    assert listing["items"][0]["relation"]["value"] == "forwarding"
    assert {"pointer": "/interfaces/orphan/Gi1~10~12", "role": "witness"} in listing["refs"]
    assert "input_census_complete" not in listing and "capture_completeness_claim" not in listing
    checked(snap)


def test_new_closed_enum_sets_are_owned_unranked_without_health_claims():
    vocab = uip.project({})["vocab"]
    for name, owner in (("carriage_relation", vlan_carriage.RELATIONS),
                        ("carriage_end_signal", vlan_carriage.END_SIGNALS),
                        ("carriage_basis", vlan_carriage.BASES),
                        ("carriage_evidence_shape", vlan_carriage.EVIDENCE_SHAPES)):
        assert vocab["unranked"][name]["tokens"] == list(owner)
        assert name not in vocab["ranked"]


@pytest.mark.parametrize("vid", [10, "10", "0010"])
def test_carriage_selection_uses_the_unchanged_producer_selector(vid):
    snap = snapshot(vlans=[{"vlan": vid}])
    listing = selection(snap)
    assert listing["state"] == "published" and len(listing["items"]) == 1
    assert listing["items"][0]["relation"]["value"] == "forwarding"
    assert snap["vlan_cutover"][0]["vlan"] == vid
    checked(snap)


@pytest.mark.parametrize("vid", [10.0, 0, 4095, True, "١٠", " 10 ", None])
def test_carriage_does_not_borrow_legacy_count_coercion_for_its_selector(vid):
    snap = snapshot(vlans=[{"vlan": vid}])
    assert selection(snap)["state"] == "unverified"
    assert selection(snap)["items"] == []
    checked(snap)


@pytest.mark.parametrize("damage", ["missing_interface", "malformed_interface", "missing_field", "typed_role",
                                   "typed_role_mismatch", "host_alias", "port_alias"])
def test_missing_or_ambiguous_current_basis_cannot_leave_a_published_stored_claim(damage):
    typed = damage.startswith("typed_role")
    snap = snapshot(("", "") if typed else ("10", "10"),
                    {A: _observation(), B: _observation()} if typed else None)
    stored = deepcopy(snap["vlan_carriage"])
    if damage == "missing_interface":
        del snap["interfaces"][A][PORT]
    elif damage == "malformed_interface":
        snap["interfaces"][A][PORT] = None
    elif damage == "missing_field":
        del snap["interfaces"][A][PORT]["trunk_allowed_vlans"]
    elif damage == "typed_role":
        snap["stp_topology_observations"][A]["roles"] = []
    elif damage == "typed_role_mismatch":
        # Still an ordinary supported state token, but it is not the stored end signal.
        snap["stp_topology_observations"][A]["roles"][0]["state"] = "blocked"
        snap["stp_topology_observations"][A]["roles"][0]["role"] = "alternate"
    elif damage == "host_alias":
        snap["interfaces"][A + ".example.invalid"] = deepcopy(snap["interfaces"][A])
    else:
        snap["interfaces"][A]["GigabitEthernet1/0/1"] = deepcopy(snap["interfaces"][A][PORT])
    assert snap["vlan_carriage"] == stored and vlan_carriage.validate_vlan_carriage(stored) == (True, "ok")
    listing = selection(snap)
    assert listing["state"] == "unverified" and len(listing["items"]) == 1
    row = listing["items"][0]
    assert row["relation"]["state"] == "unverified" and row["relation"]["value"] is None
    assert row["members"]["items"][0]["a"]["signal"]["value"] is None
    assert any(ref["pointer"].startswith("/vlan_carriage/rows/0/members/0/a/") for ref in listing["refs"])
    checked(snap)


def test_held_relation_still_requires_original_identity_for_its_published_end():
    snap = snapshot(("10", ""))
    assert snap["vlan_carriage"]["rows"][0]["state"] == "not_collected"
    assert snap["vlan_carriage"]["rows"][0]["members"][0]["a"]["state"] == "published"
    snap["cable_map"]["cables"][0]["members"][0]["a_port"] = "Gi1/0/2"
    listing = selection(snap)
    assert listing["state"] == "unverified" and listing["items"] == []
    checked(snap)


def test_failed_source_precedes_missing_basis_qualification_and_holds_stale_values():
    snap = snapshot()
    snap["assessment_integrity"] = {"failed_phases": ["VLAN cutover matrix"]}
    del snap["interfaces"][A][PORT]
    listing = selection(snap)
    assert listing["state"] == "analysis_unavailable" and len(listing["items"]) == 1
    assert listing["items"][0]["relation"]["state"] == "analysis_unavailable"
    assert listing["items"][0]["members"]["items"][0]["a"]["signal"]["state"] == "analysis_unavailable"
    checked(snap)


@pytest.mark.parametrize("field,value", [("port", "Gi1/0/99"), ("cdp_neighbor", "different-peer"),
                                         ("neighbor_port", "Gi1/0/99")])
def test_present_interface_record_fields_must_still_name_the_stored_end_and_peer(field, value):
    snap = snapshot()
    assert selection(snap)["items"][0]["relation"]["value"] == "forwarding"
    snap["interfaces"][A][PORT][field] = value
    listing = selection(snap)
    assert listing["state"] == "unverified" and len(listing["items"]) == 1
    assert listing["items"][0]["relation"]["value"] is None
    checked(snap)


@pytest.mark.parametrize("damage", ["malformed", "mst"])
def test_declared_stp_source_is_admitted_even_when_configured_allowance_was_selected(damage):
    snap = snapshot(observations={A: _observation(vid=20), B: _observation(vid=20)})
    assert selection(snap)["items"][0]["basis"]["value"] == "stored_trunk_allowance"
    snap["stp_topology_observations"][A] = {} if damage == "malformed" else _observation(namespace="MST", vid=20)
    listing = selection(snap)
    assert listing["state"] == "unverified" and len(listing["items"]) == 1
    assert listing["items"][0]["relation"]["value"] is None
    checked(snap)
