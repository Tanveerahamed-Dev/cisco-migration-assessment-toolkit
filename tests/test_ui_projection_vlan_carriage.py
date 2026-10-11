"""Stored G14 carriage facts (``vlan_carriage/2``): a per-VLAN summary in the inventory and a lazy page.

Fixtures come from the real producers (capture text read back by build_interfaces, compute_cable_map, the typed STP
producer and compute_vlan_carriage); hostile mutations of the stored snapshot are declared. These controls are
authored for hosted execution. They never replace missing stored carriage with the legacy simulation predicate or
reconstruct a VLAN universe.
"""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ui_projection as uip, vlan_carriage
from test_vlan_carriage import A, B, LONG, PORT, _built, _bundle, _cdp, _ios_trunk, _link, _observation, _stored, _stp

PUB, NC, UV, AU, CBE = "published", "not_collected", "unverified", "analysis_unavailable", "collected_but_empty"


def snapshot(tmp_path, allowed=("10", "10"), observations=None, vlans=None, interfaces=None):
    if interfaces is None:
        interfaces = _link(tmp_path, (allowed[0] or None, True), (allowed[1] or None, True))
    cables = analyze.compute_cable_map(interfaces)
    rows = [{"vlan": 10}] if vlans is None else vlans
    stored = vlan_carriage.compute_vlan_carriage(cables, _stored(interfaces), observations, rows)
    assert vlan_carriage.validate_vlan_carriage(stored) == (True, "ok")
    return {"interfaces": _stored(interfaces), "cable_map": cables, "stp_topology_observations": observations,
            "vlan_cutover": rows, "vlan_carriage": stored}


def trunks(tmp_path, n):
    """n parallel unbundled trunks Gi1/0/1..n, each allowing VLAN 10, built from capture text."""
    ports = [f"Gi1/0/{i + 1}" for i in range(n)]
    return {host: _built(tmp_path, host, {"show interfaces trunk": _ios_trunk([(p, "10", "1", True) for p in ports]),
                                          "show cdp neighbors detail": _cdp([(p, peer, p) for p in ports])})
            for host, peer in ((A, B), (B, A))}


def summary(snap, index=0):
    return uip.project_inventory(snap)["vlans"]["rows"]["items"][index]["selections"]["carriage"]


def source(snap):
    return uip.project_inventory(snap)["vlans"]["selection_sources"]["carriage"]


def page(snap, index=0, offset=0, limit=200):
    return uip.project_vlan_carriage(snap, index, offset, limit)["carriage"]


def counts(fact):
    return {name: (fact[name]["state"], fact[name]["value"]) for name in uip.CARRIAGE_SUMMARY_COUNTS}


def _resolves(snap, pointer):
    return uip._stored_pointer_tokens(uip._Ctx(snap), pointer) is not None


def checked(snap):
    before = deepcopy(snap)
    schema = uip.ui_projection_schema()
    result = uip.project(snap)
    errors = list(Draft202012Validator(schema).iter_errors(result))
    assert not errors, [(list(error.path), error.message) for error in errors]
    document = Draft202012Validator({"$ref": "#/$defs/CarriageDocument", "$defs": schema["$defs"]})
    rows = result["inventory"]["vlans"]["rows"]["items"]
    pages = []
    for row in rows:
        carriage = uip.project_vlan_carriage(snap, row["index"], 0, 200)
        errors = list(document.iter_errors(carriage))
        assert not errors, [(list(error.path), error.message) for error in errors]
        assert carriage["carriage"]["summary"] == row["selections"]["carriage"]
        assert carriage["engine"] == result["engine"]
        pages.append(carriage)
    assert snap == before
    # Strict serialization, and every emitted ref and published subject must still address the input.
    json.dumps([result, pages], allow_nan=False)
    pending = [result, pages]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for ref in item.get("refs", []):
                assert _resolves(snap, ref["pointer"]), ref
            if item.get("state") == PUB and isinstance(item.get("subject"), str) and "basis" in item:
                assert _resolves(snap, item["subject"]), item["subject"]
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return result


@pytest.mark.parametrize("allowed,observations,state,relation,shape,basis", [
    (("10", "10"), None, PUB, "forwarding", "both_ends", "stored_trunk_allowance"),
    (("none", "none"), None, PUB, "not_carried", "both_ends", "stored_trunk_allowance"),
    (("", ""), "blk", PUB, "stp_blocked", "both_ends", "typed_pvst"),
    (("", ""), "one", NC, None, "one_end_only", "none"),
    (("", ""), None, NC, None, "no_evidence", "none"),
])
def test_actual_stored_relations_and_missing_ends_are_distinct(tmp_path, allowed, observations, state, relation, shape,
                                                               basis):
    observed = {"blk": {A: _observation("BLK"), B: _observation()}, "one": {A: _observation("BLK")}}.get(observations)
    snap = snapshot(tmp_path, allowed, observed)
    result = summary(snap)
    assert result["state"] == state and result["vlan_index"] == 0
    assert {ref["pointer"] for ref in result["refs"]} == {"/vlan_carriage/rows/0", "/vlan_carriage/coverage"}
    expected = {"assessed": 1, "edge_not_collected": 0, "forwarding": int(relation == "forwarding"),
                "stp_blocked": int(relation == "stp_blocked"), "not_carried": int(relation == "not_carried"),
                "held": int(relation is None)}
    assert counts(result) == {name: (PUB, value) for name, value in expected.items()}
    carriage = page(snap)
    assert (carriage["page"]["total"], carriage["page"]["returned"], carriage["page"]["has_more"]) == (1, 1, False)
    row = carriage["page"]["items"][0]
    assert (row["relation"]["state"], row["relation"]["value"]) == (state, relation)
    assert row["evidence_shape"]["value"] == shape and row["basis"]["value"] == basis
    assert row["pointer"] == "/vlan_carriage/cables/0" and row["cable_pointer"] == "/cable_map/cables/0"
    assert row["relation"]["subject"] == "/vlan_carriage/rows/0/codes"
    assert row["ends"]["value"]["a"] == A
    assert "stored_vlan_carriage_scope" in row["relation"]["caveats"]
    assert row["members"]["items"][0]["a"]["port"]["value"] == PORT
    if shape == "one_end_only":
        member = row["members"]["items"][0]
        assert member["a"]["signal"]["value"] == "blocked"
        assert member["b"]["signal"]["state"] == NC and member["b"]["signal"]["value"] is None
    checked(snap)


def test_projection_is_stored_only_and_does_not_call_any_carriage_or_root_producer(tmp_path, monkeypatch):
    snap = snapshot(tmp_path, vlans=[{"vlan": 10}, {"vlan": 20}])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("rendering must not recompute")

    monkeypatch.setattr(vlan_carriage, "compute_vlan_carriage", forbidden)
    monkeypatch.setattr(analyze, "_link_carries", forbidden)
    monkeypatch.setattr(analyze, "build_network_model", forbidden)
    monkeypatch.setattr(analyze, "compute_vlan_cutover_matrix", forbidden)
    assert page(snap, 0)["page"]["items"][0]["relation"]["value"] == "forwarding"
    assert page(snap, 1)["page"]["items"][0]["relation"]["value"] == "not_carried"
    assert counts(summary(snap, 1))["not_carried"] == (PUB, 1)
    del snap["vlan_carriage"]
    held = summary(snap)
    assert held["state"] == NC and all(state == NC and value is None for state, value in counts(held).values())
    assert page(snap)["page"]["total"] == 0
    checked(snap)


@pytest.mark.parametrize("damage", ["unknown_schema", "malformed_tail", "unknown_code", "extra_field",
                                   "withheld_relation", "boolean_census", "missing_member", "vlan_moved",
                                   "cable_moved", "member_moved"])
def test_invalid_stored_contract_or_current_identity_never_recomputes(tmp_path, damage):
    snap = snapshot(tmp_path)
    stored = snap["vlan_carriage"]
    row = stored["rows"][0]
    if damage == "unknown_schema":
        stored["schema"] = "vlan_carriage/unknown"
    elif damage == "malformed_tail":
        stored["rows"].append(None)
    elif damage == "unknown_code":
        row["codes"] = "~" + row["codes"][1:]
    elif damage == "extra_field":
        row["health"] = "safe"
    elif damage == "withheld_relation":
        row["state"] = NC
    elif damage == "boolean_census":
        stored["coverage"]["emitted_pairs"] = True
    elif damage == "missing_member":
        stored["cables"][0]["members"] = []
    elif damage == "vlan_moved":
        snap["vlan_cutover"][0]["vlan"] = 20
    elif damage == "cable_moved":
        snap["cable_map"]["cables"][0]["a"] = "another-host"
    else:
        snap["cable_map"]["cables"][0]["members"][0]["a_port"] = "Gi1/0/2"
    result = summary(snap)
    assert result["state"] == UV
    # A refused section never reads as zero: every count carries the refusal.
    assert all(state == UV and value is None for state, value in counts(result).values())
    assert source(snap)["state"] == UV
    assert any(ref["pointer"] == "/vlan_carriage" for ref in source(snap)["refs"])
    assert page(snap)["page"]["total"] == 0 and page(snap)["page"]["items"] == []
    checked(snap)


def test_empty_stored_cables_and_absent_section_have_different_states(tmp_path):
    snap = snapshot(tmp_path)
    snap["devices"] = {host: {"hostname": host} for host in (A, B)}
    snap["collection_completeness"] = {
        "devices": [], "summary": {"inventory": 2, "partial": 0, "not_collected": 0},
    }
    snap["cable_map"]["cables"] = []
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    result = summary(snap)
    assert result["state"] == CBE and counts(result)["assessed"] == (PUB, 0)
    assert page(snap)["page"]["total"] == 0
    checked(snap)
    del snap["vlan_carriage"]
    assert summary(snap)["state"] == NC


@pytest.mark.parametrize("gap", ["blind_device", "absent_record", "unreadable_rows", "summary_gap"])
def test_empty_carriage_is_not_clean_absence_under_fleet_coverage_gap(tmp_path, gap):
    snap = snapshot(tmp_path)
    snap["devices"] = {host: {"hostname": host} for host in (A, B)}
    snap["cable_map"]["cables"] = []
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    snap["collection_completeness"] = {
        "devices": [], "summary": {"inventory": 2, "partial": 0, "not_collected": 0},
    }
    if gap == "blind_device":
        snap["collection_completeness"]["devices"] = [{"host": B, "status": "partial"}]
        snap["collection_completeness"]["summary"]["partial"] = 1
    elif gap == "absent_record":
        del snap["collection_completeness"]
    elif gap == "unreadable_rows":
        snap["collection_completeness"]["devices"] = [None]
    else:
        snap["collection_completeness"]["summary"]["partial"] = 1
    result = summary(snap)
    assert result["state"] == NC
    assert "empty list" in result["reason"]
    if gap == "blind_device":
        assert {"pointer": "/collection_completeness/devices/0", "role": "witness"} in result["refs"]
    checked(snap)


def test_nonempty_carriage_keeps_local_facts_and_fleet_blind_spot_qualification(tmp_path):
    snap = snapshot(tmp_path)
    snap["devices"] = {host: {"hostname": host} for host in (A, B)}
    snap["collection_completeness"] = {
        "devices": [{"host": B, "status": "partial"}],
        "summary": {"inventory": 2, "partial": 1, "not_collected": 0},
    }
    result = summary(snap)
    assert result["state"] == PUB
    assert "fleet_lists_exclude_blind_devices" in result["caveats"]
    assert {"pointer": "/collection_completeness/devices/0", "role": "witness"} in result["refs"]
    assert counts(result)["forwarding"] == (PUB, 1)
    assert "fleet_lists_exclude_blind_devices" in result["forwarding"]["caveats"]
    assert page(snap)["page"]["items"][0]["relation"]["value"] == "forwarding"
    checked(snap)


def test_source_uncertainty_keeps_readable_cable_evidence_and_no_completeness_promotion(tmp_path):
    snap = snapshot(tmp_path)
    snap["interfaces"]["orphan"] = {"Gi1/0/2": None}  # Declared hostile stored record outside every cable.
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    result = summary(snap)
    assert result["state"] == UV and counts(result)["forwarding"] == (PUB, 1)
    assert {"pointer": "/interfaces/orphan/Gi1~10~12", "role": "witness"} in source(snap)["refs"]
    assert "input_census_complete" not in result and "capture_completeness_claim" not in result
    assert page(snap)["page"]["items"][0]["relation"]["value"] == "forwarding"
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
def test_carriage_selection_uses_the_unchanged_producer_selector(tmp_path, vid):
    snap = snapshot(tmp_path, vlans=[{"vlan": vid}])
    assert summary(snap)["state"] == PUB
    assert page(snap)["page"]["items"][0]["relation"]["value"] == "forwarding"
    assert snap["vlan_cutover"][0]["vlan"] == vid
    checked(snap)


@pytest.mark.parametrize("vid", [10.0, 0, 4095, True, "١٠", " 10 ", None])
def test_carriage_does_not_borrow_legacy_count_coercion_for_its_selector(tmp_path, vid):
    snap = snapshot(tmp_path, vlans=[{"vlan": vid}])
    result = summary(snap)
    assert result["state"] == UV
    assert all(value is None for _state, value in counts(result).values() if _state != PUB)
    assert counts(result)["forwarding"] == (UV, None)
    assert page(snap)["page"]["items"] == []
    checked(snap)


@pytest.mark.parametrize("damage", ["missing_interface", "malformed_interface", "missing_field", "typed_role",
                                   "typed_role_mismatch", "typed_role_incompatible", "host_alias", "port_alias"])
def test_missing_or_ambiguous_current_basis_cannot_leave_a_published_stored_claim(tmp_path, damage):
    typed = damage.startswith("typed_role")
    snap = snapshot(tmp_path, ("", "") if typed else ("10", "10"),
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
    elif damage == "typed_role_incompatible":
        # The state still matches the stored signal; its role cannot certify that state.
        snap["stp_topology_observations"][A]["roles"][0]["role"] = "alternate"
    elif damage == "host_alias":
        snap["interfaces"][A + ".example.invalid"] = deepcopy(snap["interfaces"][A])
    else:
        snap["interfaces"][A][LONG] = deepcopy(snap["interfaces"][A][PORT])
    assert snap["vlan_carriage"] == stored and vlan_carriage.validate_vlan_carriage(stored) == (True, "ok")
    result = summary(snap)
    assert result["state"] == UV and "no longer resolve" in result["reason"]
    assert counts(result)["forwarding"] == (UV, None)
    item = page(snap)["page"]["items"][0]
    assert item["relation"]["state"] == UV and item["relation"]["value"] is None
    assert item["members"]["items"][0]["a"]["signal"]["value"] is None
    assert any(ref["pointer"].startswith("/vlan_carriage/cables/0/members/0/a/") for ref in source(snap)["refs"])
    checked(snap)


def test_held_relation_still_requires_original_identity_for_its_published_end(tmp_path):
    snap = snapshot(tmp_path, ("10", ""))
    assert summary(snap)["state"] == NC
    snap["cable_map"]["cables"][0]["members"][0]["a_port"] = "Gi1/0/2"  # Declared hostile mutation.
    result = summary(snap)
    assert result["state"] == UV and page(snap)["page"]["items"] == []
    checked(snap)


@pytest.mark.parametrize("damage", ["exclude_vlan", "literal_none", "access_mode", "bad_range", "two_allowances"])
def test_current_allowance_cannot_be_cited_beside_a_contradictory_stored_positive(tmp_path, damage):
    snap = snapshot(tmp_path)
    assert summary(snap)["forwarding"]["value"] == 1
    stored = deepcopy(snap["vlan_carriage"])
    record = snap["interfaces"][A][PORT]
    if damage == "exclude_vlan":
        record["trunk_allowed_vlans"] = "20"
    elif damage == "literal_none":
        record["trunk_allowed_vlans"], record["trunk_allowed_none"] = "", "none"
    elif damage == "access_mode":
        record["switchport_mode"] = "Access"
    elif damage == "bad_range":
        record["trunk_allowed_vlans"] = "10,broken"
    else:
        record["trunk_allowed_none"] = "none"
    assert snap["vlan_carriage"] == stored  # Deliberate source drift; the reader may only hold the old claim.
    result = summary(snap)
    assert result["state"] == UV and result["forwarding"]["value"] is None
    item = page(snap)["page"]["items"][0]
    assert item["relation"]["state"] == UV and item["relation"]["value"] is None
    assert item["members"]["items"][0]["a"]["signal"]["value"] is None
    checked(snap)


def test_current_allowance_cannot_turn_a_stored_exclusion_into_a_live_allowance_claim(tmp_path):
    snap = snapshot(tmp_path, ("none", "none"))
    assert summary(snap)["not_carried"]["value"] == 1
    record = snap["interfaces"][A][PORT]
    record["trunk_allowed_vlans"], record["trunk_allowed_none"] = "10", ""
    result = summary(snap)
    assert result["state"] == UV and result["not_carried"]["value"] is None
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    checked(snap)


@pytest.mark.parametrize("damage", ["exclude_forwarding", "native_exclusion", "malformed_range"])
def test_current_allowance_conflict_cannot_leave_a_typed_signal_published(tmp_path, damage):
    snap = snapshot(tmp_path, ("", ""), {A: _observation(), B: _observation()})
    record = snap["interfaces"][A][PORT]
    record["trunk_allowed_vlans"] = "20" if damage != "malformed_range" else "broken"
    if damage == "native_exclusion":
        record["trunk_native_vlan"] = "10"
    result = summary(snap)
    assert result["state"] == UV and result["forwarding"]["value"] is None
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    checked(snap)


@pytest.mark.parametrize("mode", ["Trunk", "dynamic trunk", "trunk (802.1q)"])
def test_admissible_configured_basis_spelling_preserves_the_stored_claim(tmp_path, mode):
    snap = snapshot(tmp_path)
    for host in (A, B):
        snap["interfaces"][host][PORT]["switchport_mode"] = mode
    assert summary(snap)["state"] == PUB and summary(snap)["forwarding"]["value"] == 1
    assert page(snap)["page"]["items"][0]["relation"]["value"] == "forwarding"
    checked(snap)


@pytest.mark.parametrize("damage", ["edge_scope", "edge_port", "edge_host", "unreadable_scope"])
def test_every_stored_cable_scope_and_known_identity_must_join_current_sources(tmp_path, damage):
    snap = snapshot(tmp_path)
    peer = deepcopy(snap["interfaces"][B])
    if damage == "unreadable_scope":
        snap["cable_map"]["cables"][0]["is_pc"] = "invalid"  # Declared unreadable source.
    else:
        del snap["interfaces"][B]  # Declared off-scan peer in an otherwise real producer cable.
    snap["vlan_carriage"] = vlan_carriage.compute_vlan_carriage(
        snap["cable_map"], snap["interfaces"], None, snap["vlan_cutover"])
    assert vlan_carriage.validate_vlan_carriage(snap["vlan_carriage"]) == (True, "ok")
    stored = deepcopy(snap["vlan_carriage"])
    if damage == "edge_scope":
        snap["interfaces"][B] = peer
    elif damage == "edge_port":
        cable = snap["cable_map"]["cables"][0]
        cable["b_port"] = cable["members"][0]["b_port"] = "Gi0"
    elif damage == "edge_host":
        snap["cable_map"]["cables"][0]["b"] = "another-off-scan-peer"
    else:
        snap["cable_map"]["cables"][0]["is_pc"] = False
    assert snap["vlan_carriage"] == stored
    result = summary(snap)
    assert result["state"] == UV and "does not join" in result["reason"]
    assert all(state == UV and value is None for state, value in counts(result).values())
    assert page(snap)["page"]["items"] == []
    checked(snap)


def test_failed_source_precedes_missing_basis_qualification_and_holds_stale_values(tmp_path):
    snap = snapshot(tmp_path)
    snap["assessment_integrity"] = {"failed_phases": ["VLAN cutover matrix"]}
    del snap["interfaces"][A][PORT]
    result = summary(snap)
    assert result["state"] == AU and all(state == AU for state, _value in counts(result).values())
    item = page(snap)["page"]["items"][0]
    assert item["relation"]["state"] == AU
    assert item["members"]["items"][0]["a"]["signal"]["state"] == AU
    checked(snap)


@pytest.mark.parametrize("field,value", [("port", "Gi1/0/99"), ("cdp_neighbor", "different-peer"),
                                         ("neighbor_port", "Gi1/0/99")])
def test_present_interface_record_fields_must_still_name_the_stored_end_and_peer(tmp_path, field, value):
    snap = snapshot(tmp_path)
    assert page(snap)["page"]["items"][0]["relation"]["value"] == "forwarding"
    snap["interfaces"][A][PORT][field] = value  # Declared hostile mutation.
    assert summary(snap)["state"] == UV
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    checked(snap)


@pytest.mark.parametrize("damage", ["malformed", "mst"])
def test_declared_stp_source_is_admitted_even_when_configured_allowance_was_selected(tmp_path, damage):
    snap = snapshot(tmp_path, observations={A: _observation(vid=20), B: _observation(vid=20)})
    assert page(snap)["page"]["items"][0]["basis"]["value"] == "stored_trunk_allowance"
    snap["stp_topology_observations"][A] = {} if damage == "malformed" else _observation(namespace="MST", vid=20)
    assert summary(snap)["state"] == UV
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    checked(snap)


def test_a_vlan_summary_reads_its_own_row_never_another_vlans_hold(tmp_path):
    observations = {A: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "LRN")]}),
                    B: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]})}
    snap = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert [summary(snap, i)["state"] for i in (0, 1)] == [PUB, UV]
    assert counts(summary(snap, 0))["forwarding"] == (PUB, 1) and counts(summary(snap, 1))["held"] == (PUB, 1)
    assert source(snap)["state"] == UV
    checked(snap)


def test_a_summary_keeps_o1_refs_and_its_size_whatever_the_cable_count(tmp_path):
    small, large = snapshot(tmp_path, interfaces=trunks(tmp_path, 1)), snapshot(tmp_path, interfaces=trunks(tmp_path, 3))
    one, three = summary(small), summary(large)
    assert counts(three)["assessed"] == (PUB, 3) and counts(three)["forwarding"] == (PUB, 3)
    assert [ref["pointer"] for ref in one["refs"]] == [ref["pointer"] for ref in three["refs"]]
    assert len(json.dumps(one, separators=(",", ":"))) == len(json.dumps(three, separators=(",", ":")))
    assert len(json.dumps(three, separators=(",", ":"))) <= 4096


def test_the_lazy_page_windows_the_assessed_cables_and_reads_the_snapshot_read_only(tmp_path):
    snap = snapshot(tmp_path, interfaces=trunks(tmp_path, 3))
    before = deepcopy(snap)
    first, last, beyond = page(snap, 0, 0, 2), page(snap, 0, 2, 2), page(snap, 0, 3, 2)
    assert [(p["page"]["returned"], p["page"]["total"], p["page"]["has_more"]) for p in (first, last, beyond)] == [
        (2, 3, True), (1, 3, False), (0, 3, False)]
    assert [item["index"] for item in first["page"]["items"] + last["page"]["items"]] == [0, 1, 2]
    assert first["summary"] == last["summary"] == summary(snap)
    admission = uip.carriage_admission(snap)
    assert uip.project_vlan_carriage(snap, 0, 0, 2, admission=admission)["carriage"] == first
    assert snap == before
    checked(snap)


@pytest.mark.parametrize("field,value,states", [
    ("trunk_allowed_vlans", "20", (UV, UV)),
    ("switchport_mode", "access", (UV, UV)),
    ("trunk_allowed_none", "none", (UV, UV)),
    ("trunk_native_vlan", "20", (PUB, UV)),
])
def test_shared_allowance_bases_keep_each_end_and_vlan_native_or_mode_conflict(tmp_path, field, value, states):
    # Real producer rows share their original allowance. A later, different end's current basis must never
    # inherit an earlier end's answer, even when all other fields and the stored code characters still agree.
    snap = snapshot(tmp_path, interfaces=trunks(tmp_path, 3), vlans=[{"vlan": 10}, {"vlan": 20}])
    assert counts(summary(snap, 0))["forwarding"] == (PUB, 3)
    assert counts(summary(snap, 1))["not_carried"] == (PUB, 3)
    snap["interfaces"][A]["Gi1/0/3"][field] = value  # Declared hostile current-basis mutation.
    assert tuple(summary(snap, vi)["state"] for vi in (0, 1)) == states
    for vi, state in enumerate(states):
        relation = page(snap, vi)["page"]["items"][0]["relation"]
        assert (relation["value"] is None) == (state == UV)
    checked(snap)


def test_a_bundled_end_must_still_join_the_channel_its_record_cites(tmp_path):
    snap = snapshot(tmp_path, interfaces=_bundle(tmp_path))
    assert summary(snap)["state"] == PUB
    snap["interfaces"][A][PORT]["port_channel"] = "Po2"  # Declared hostile mutation: the member moved channel.
    assert summary(snap)["state"] == UV
    assert any(ref["pointer"] == "/vlan_carriage/cables/0/members/0/a/stp_interface" for ref in source(snap)["refs"])
    checked(snap)


def test_a_typed_end_signal_cites_the_role_row_the_owner_join_names(tmp_path):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    signal = page(snap)["page"]["items"][0]["members"]["items"][0]["a"]["signal"]
    assert (signal["state"], signal["value"]) == (PUB, "forwarding")
    pointers = {ref["pointer"] for ref in signal["refs"]}
    assert {f"/stp_topology_observations/{A}", f"/stp_topology_observations/{A}/roles/0"} <= pointers
    checked(snap)


def test_value_identical_observations_keep_each_current_host_object_and_scope_the_answer_cache(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    assert observations[A] == observations[B] and observations[A] is not observations[B]
    original, calls = uip.carriage_observation_admission, []

    def observed(record):
        calls.append(record)
        return original(record)

    monkeypatch.setattr(uip, "carriage_observation_admission", observed)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 1
    assert admission.observations[A][0] is observations[A]
    assert admission.observations[B][0] is observations[B]
    result = uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission)
    assert result["carriage"]["summary"]["forwarding"]["value"] == 1
    for side, host in (("a", A), ("b", B)):
        refs = result["carriage"]["page"]["items"][0]["members"]["items"][0][side]["signal"]["refs"]
        assert any(ref["pointer"] == f"/stp_topology_observations/{host}/roles/0" for ref in refs)
    calls.clear()
    uip.carriage_admission(snap)
    assert len(calls) == 1  # Fresh admission calls the owner again; nothing survives the read-only call.


@pytest.mark.parametrize("damage", [
    "float-count", "bool-counter", "bool-root", "float-priority", "array-order", "integrity-finding", "new-field",
])
def test_observation_answer_reuse_cannot_hide_a_later_hosts_type_order_or_integrity_gap(tmp_path, damage):
    observations = {host: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]})
                    for host in (A, B)}
    snap = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert observations[A] == observations[B] and summary(snap)["state"] == PUB
    record = observations[B]
    if damage == "float-count":
        record["counter_parsed_count"] = float(record["counter_parsed_count"])
    elif damage == "bool-counter":
        assert record["topology_changes"][0]["count"] == 0
        record["topology_changes"][0]["count"] = False
    elif damage == "bool-root":
        assert record["roots"][0]["is_root"] is True
        record["roots"][0]["is_root"] = 1
    elif damage == "float-priority":
        record["roots"][0]["bridge_priority"] = float(record["roots"][0]["bridge_priority"])
    elif damage == "array-order":
        record["roles"].reverse()
    elif damage == "integrity-finding":
        record["finding_codes"] = sorted(set(record["finding_codes"]) | {"role_evidence_missing"})
    else:
        record["new_field"] = "unadmitted"
    assert summary(snap)["state"] == UV
    assert page(snap)["page"]["items"][0]["members"]["items"][0]["b"]["signal"]["value"] is None
    checked(snap)


def test_noneligible_observation_key_uses_the_owner_without_changing_its_admission_policy(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    # A string subclass is outside the optional exact-builtins memo, but the STP owner admits it by its own rules.
    observations[B]["roles"][0]["instance"] = type("ForeignInstance", (str,), {})("10")
    original, calls = uip.carriage_observation_admission, []

    def observed(record):
        calls.append(record)
        return original(record)

    monkeypatch.setattr(uip, "carriage_observation_admission", observed)
    assert uip.carriage_admission(snap).source["state"] == PUB
    assert len(calls) == 2
    assert summary(snap)["state"] == PUB
    checked(snap)


def test_equal_observations_share_immutable_positions_but_keep_each_current_host_role(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    before = deepcopy(snap)
    original, indexed = uip.carriage_role_index, []

    def observed(record):
        indexed.append(record)
        return original(record)

    monkeypatch.setattr(uip, "carriage_role_index", observed)
    admission = uip.carriage_admission(snap)
    assert len(indexed) == 1
    indexes = [admission.observations[host][1] for host in (A, B)]
    assert indexes[0] is indexes[1]
    with pytest.raises(TypeError):
        indexes[0][("pvst_vlan", 10, PORT)] = (999,)
    for host in (A, B):
        record, index = admission.observations[host]
        assert record is observations[host]
        rows = vlan_carriage.carriage_role_rows(record, PORT, 10, index=index)
        assert rows[0][1] is observations[host]["roles"][0]
    produced = uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission)["carriage"]
    assert produced["summary"]["forwarding"]["value"] == 1
    for side, host in (("a", A), ("b", B)):
        signal = produced["page"]["items"][0]["members"]["items"][0][side]["signal"]
        assert signal["value"] == "forwarding"
        assert any(ref["pointer"] == f"/stp_topology_observations/{host}/roles/0" for ref in signal["refs"])
    indexed.clear()
    uip.carriage_admission(snap)
    assert len(indexed) == 1
    assert snap == before


@pytest.mark.parametrize("damage", ["incompatible", "unpublished", "namespace", "missing-role"])
def test_shared_role_positions_are_read_again_for_a_changed_later_host(tmp_path, damage):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    assert summary(snap)["state"] == PUB
    if damage == "incompatible":
        observations[B]["roles"][0]["role"] = "alternate"  # Forwarding beside alternate is not compatible.
    elif damage == "unpublished":
        observations[B]["roles"][0]["state"] = "learning"
    elif damage == "namespace":
        observations[B]["roles"][0]["namespace"] = "mst_instance"
    else:
        observations[B]["roles"] = []
        observations[B]["role_parsed_count"] = 0
    result = summary(snap)
    assert result["state"] == UV and result["forwarding"]["value"] is None
    assert page(snap)["page"]["items"][0]["members"]["items"][0]["b"]["signal"]["value"] is None
    checked(snap)


def test_equal_current_role_records_keep_a_shared_false_compatibility_answer_false(tmp_path):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    assert summary(snap)["state"] == PUB
    for record in observations.values():
        record["roles"][0]["role"] = "alternate"  # Both current role rows are now incompatible with FWD.
    assert observations[A] == observations[B]
    assert summary(snap)["state"] == UV
    members = page(snap)["page"]["items"][0]["members"]["items"]
    assert members[0]["a"]["signal"]["value"] is None and members[0]["b"]["signal"]["value"] is None
    checked(snap)


@pytest.mark.parametrize("damage", ["range", "literal_none", "blocked_native_conflict"])
def test_shared_role_compatibility_never_shares_a_final_end_allowance_decision(tmp_path, damage):
    blocked = damage == "blocked_native_conflict"
    observations = {host: _observation("BLK" if blocked else "FWD") for host in (A, B)}
    snap = snapshot(tmp_path, ("20", "20") if blocked else ("10", "10"), observations)
    assert observations[A] == observations[B]
    assert page(snap)["page"]["items"][0]["relation"]["value"] == ("stp_blocked" if blocked else "forwarding")
    record = snap["interfaces"][B][PORT]
    if damage == "range":
        record["trunk_allowed_vlans"] = "20"
    elif damage == "literal_none":
        record["trunk_allowed_vlans"], record["trunk_allowed_none"] = "", "none"
    else:
        record["trunk_native_vlan"] = "10"
    assert summary(snap)["state"] == UV
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    checked(snap)


def test_shared_logical_channel_positions_do_not_erase_a_physical_member_beside_role(tmp_path):
    interfaces = _bundle(tmp_path, b_groups=((1, ("Gi1/0/1", "Gi1/0/2")),), allowed=(None, None))
    observations = {host: _stp({10: [("Po1", "Desg", "FWD")]}) for host in (A, B)}
    snap = snapshot(tmp_path, observations=observations, interfaces=interfaces)
    assert observations[A] == observations[B] and summary(snap)["state"] == PUB
    # Rebuild through the typed producer, on both value-identical host records: one physical member now also has
    # a role beside the logical channel. The stored old positive must be held; no first-member fallback.
    snap["stp_topology_observations"] = {
        host: _stp({10: [("Po1", "Desg", "FWD"), ("Gi1/0/2", "Altn", "BLK")]}) for host in (A, B)}
    assert summary(snap)["state"] == UV
    assert page(snap)["page"]["items"][0]["relation"]["value"] is None
    assert any("stp_pointer" in ref["pointer"] for ref in source(snap)["refs"])
    checked(snap)


def test_nonstandard_real_owner_index_shape_keeps_per_host_fallback_and_complete_output(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    expected, expected_page = checked(snap), uip.project_vlan_carriage(snap, 0, 0, 200)
    original, calls = uip.carriage_role_index, []

    class ForeignIndex(dict):
        pass

    def observed(record):
        calls.append(record)
        return ForeignIndex(original(record))  # Same real owner positions; optional ordinary-index reuse is ineligible.

    monkeypatch.setattr(uip, "carriage_role_index", observed)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 2 and calls[0] is observations[A] and calls[1] is observations[B]
    first, second = admission.observations[A][1], admission.observations[B][1]
    assert type(first) is type(second) is ForeignIndex and first is not second
    assert uip.project(snap, carriage=admission) == expected
    assert uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission) == expected_page
    checked(snap)


@pytest.mark.parametrize("shape", ["foreign-list", "list-pair", "copied-row"])
def test_nonstandard_real_owner_queries_never_retain_shared_positions_or_foreign_rows(tmp_path, monkeypatch, shape):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    expected, expected_page = checked(snap), uip.project_vlan_carriage(snap, 0, 0, 200)
    original, calls, replies = uip.carriage_role_rows, [], []
    compatible, seen_rows = uip.carriage_role_compatible, []

    class ForeignRows(list):
        pass

    def observed(record, interface, vid, *, index=None):
        rows = original(record, interface, vid, index=index)
        assert rows and rows[0][1] is record["roles"][rows[0][0]]
        if shape == "foreign-list":
            result = ForeignRows(rows)
        elif shape == "list-pair":
            result = [[i, row] for i, row in rows]
        else:
            result = [(i, dict(row)) for i, row in rows]
        calls.append(record)
        replies.append(result)
        return result

    def observed_compatible(row):
        seen_rows.append(row)
        return compatible(row)

    monkeypatch.setattr(uip, "carriage_role_rows", observed)
    monkeypatch.setattr(uip, "carriage_role_compatible", observed_compatible)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 2 and calls[0] is observations[A] and calls[1] is observations[B]
    # Both host queries were executed: the second was not replaced by a shared position hit.
    if shape == "copied-row":
        assert len(seen_rows) == 2
        assert seen_rows[0] is replies[0][0][1] and seen_rows[1] is replies[1][0][1]
        assert seen_rows[0] is not observations[A]["roles"][0]
        assert seen_rows[1] is not observations[B]["roles"][0]
    assert uip.project(snap, carriage=admission) == expected
    assert uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission) == expected_page
    checked(snap)


def _old_observation_key_eligible(record):
    """Frozen pre-bytes key domain/count oracle; dict keys contribute characters but never extra nodes."""
    if type(record) is not dict:
        return False
    nodes, characters = 0, 0

    def typed(node, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes > 65_536 or depth > 32:
            raise ValueError("old optional count/depth limit")
        kind = type(node)
        if kind is dict:
            if not all(type(key) is str for key in node):
                raise TypeError("old exact key types")
            characters += sum(len(key) for key in node)
            if characters > 1_000_000:
                raise ValueError("old character limit")
            return (dict, tuple((key, typed(node[key], depth + 1)) for key in sorted(node)))
        if kind is list:
            return (list, tuple(typed(child, depth + 1) for child in node))
        if kind is str:
            characters += len(node)
            if characters > 1_000_000:
                raise ValueError("old character limit")
            return (str, node)
        if node is None or kind in (bool, int):
            return (kind, node)
        if kind is float and uip.math.isfinite(node):
            return (float, node.hex())
        raise TypeError("old exact finite JSON types")

    try:
        typed(record, 0)
    except (TypeError, ValueError, RecursionError, OverflowError, MemoryError):
        return False
    return True


def test_complete_observation_bytes_distinguish_types_values_sign_and_extra_fields():
    base = {"value": 0, "extra": [True, None, "text"]}
    cases = [base, {**base, "value": False}, {**base, "value": 0.0}, {**base, "value": -0.0},
             {**base, "value": 1}, {**base, "new": "unadmitted"}, {**base, "extra": [None, True, "text"]}]
    keys = []
    for record in cases:
        assert _old_observation_key_eligible(record)
        key = uip._carriage_observation_key(record)
        assert type(key) is bytes
        keys.append(key)
    assert len(set(keys)) == len(cases)


def test_complete_observation_encoding_reads_the_entire_current_record_on_every_host(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    original, calls = uip.marshal.dumps, []

    def observed(record, version):
        assert version == 2 and any(record is current for current in observations.values())
        calls.append(record)
        return original(record, version)

    monkeypatch.setattr(uip.marshal, "dumps", observed)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 2 and calls[0] is observations[A] and calls[1] is observations[B]
    assert admission.observations[A][0] is observations[A] and admission.observations[B][0] is observations[B]
    calls.clear()
    uip.carriage_admission(snap)
    assert len(calls) == 2  # Fresh full encodings; never a previous request/result or metadata-only key.


def test_observation_dictionary_reordering_is_only_a_conservative_owner_cache_miss(tmp_path, monkeypatch):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    expected, expected_page = checked(snap), uip.project_vlan_carriage(snap, 0, 0, 200)
    record = observations[B]
    key = next(iter(record))
    record[key] = record.pop(key)
    assert observations[A] == observations[B]
    assert uip._carriage_observation_key(observations[A]) != uip._carriage_observation_key(observations[B])
    original, calls = uip.carriage_observation_admission, []

    def observed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(uip, "carriage_observation_admission", observed)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 2
    assert uip.project(snap, carriage=admission) == expected
    assert uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission) == expected_page


@pytest.mark.parametrize("value", [b"bytes", bytearray(b"bytes"), memoryview(b"bytes"), float("inf"),
                                  float("nan"), type("ForeignString", (str,), {})("text")])
def test_observation_bytes_key_keeps_the_old_noneligible_value_domain(value):
    record = {"value": value}
    assert not _old_observation_key_eligible(record)
    assert uip._carriage_observation_key(record) is None


def test_nonplain_buffer_value_is_rejected_before_encoder_or_buffer_protocol_hooks(monkeypatch):
    hooks, encodings = [], []

    class ForeignBuffer:
        def __buffer__(self, _flags):
            hooks.append(True)
            raise AssertionError("Optional key eligibility invoked a nonplain buffer capability")

    def forbidden(*_args):
        encodings.append(True)
        pytest.fail("Nonplain observation value reached the full marshal encoder")

    record = {"value": ForeignBuffer()}
    assert not _old_observation_key_eligible(record)
    monkeypatch.setattr(uip.marshal, "dumps", forbidden)
    assert uip._carriage_observation_key(record) is None
    assert hooks == [] and encodings == []


def test_observation_key_node_and_dictionary_key_count_boundaries_match_the_old_domain():
    # root + list + 65,534 values is exactly65,536; dict keys do not contribute extra counted nodes.
    for record in ({"value": [None] * 65_534}, {str(i): None for i in range(65_535)}):
        assert _old_observation_key_eligible(record)
        assert type(uip._carriage_observation_key(record)) is bytes
    record = {"value": [None] * 65_535}
    assert not _old_observation_key_eligible(record) and uip._carriage_observation_key(record) is None


def test_repeated_aliases_are_counted_per_occurrence_and_cycles_keep_owner_fallback():
    shared = [None] * 32_766
    record = {"first": shared, "second": shared}
    assert _old_observation_key_eligible(record) and type(uip._carriage_observation_key(record)) is bytes
    shared.append(None)
    assert not _old_observation_key_eligible(record) and uip._carriage_observation_key(record) is None
    cycle = []
    cycle.append(cycle)
    record = {"value": cycle}
    assert not _old_observation_key_eligible(record) and uip._carriage_observation_key(record) is None


def test_observation_depth_and_codepoint_boundaries_are_unchanged():
    at_depth = 0
    for _ in range(31):
        at_depth = [at_depth]
    record = {"value": at_depth}  # root0, scalar32
    assert _old_observation_key_eligible(record) and type(uip._carriage_observation_key(record)) is bytes
    record = {"value": [at_depth]}
    assert not _old_observation_key_eligible(record) and uip._carriage_observation_key(record) is None
    for suffix, eligible in (("", True), ("x", False)):
        record = {"k": "a" * 999_999 + suffix}
        assert _old_observation_key_eligible(record) is eligible
        assert (uip._carriage_observation_key(record) is not None) is eligible


def test_a_large_container_stops_at_old_node_eligibility_before_full_encoding(monkeypatch):
    record = {"value": [None] * 1_000_000}
    assert not _old_observation_key_eligible(record)

    def forbidden(*_args):
        pytest.fail("Node-ineligible large container reached the full encoder")

    monkeypatch.setattr(uip.marshal, "dumps", forbidden)
    assert uip._carriage_observation_key(record) is None


@pytest.mark.parametrize("failure", ["type", "resource", "audit-oserror", "bytearray", "byte-subclass", "retained-bytes"])
def test_observation_encoder_errors_and_optional_byte_limit_preserve_full_owner_policy(tmp_path, monkeypatch, failure):
    observations = {A: _observation(), B: _observation()}
    snap = snapshot(tmp_path, ("", ""), observations)
    expected, expected_page = checked(snap), uip.project_vlan_carriage(snap, 0, 0, 200)
    original, calls = uip.carriage_observation_admission, []

    def observed(record):
        calls.append(record)
        return original(record)

    def unadmitted(_record, version):
        assert version == 2
        if failure == "type":
            raise TypeError("deliberate optional encoding refusal")
        if failure == "resource":
            raise MemoryError("deliberate optional resource refusal")
        if failure == "audit-oserror":
            raise OSError("deliberate marshal audit-hook refusal")
        if failure == "bytearray":
            return bytearray(b"unadmitted")
        if failure == "byte-subclass":
            return type("ForeignBytes", (bytes,), {})(b"unadmitted")
        return b"x" * (8 * 1024 * 1024 + 1)

    monkeypatch.setattr(uip.marshal, "dumps", unadmitted)
    monkeypatch.setattr(uip, "carriage_observation_admission", observed)
    admission = uip.carriage_admission(snap)
    assert len(calls) == 2
    assert admission.observations[A][0] is observations[A] and admission.observations[B][0] is observations[B]
    assert uip.project(snap, carriage=admission) == expected
    assert uip.project_vlan_carriage(snap, 0, 0, 200, admission=admission) == expected_page
