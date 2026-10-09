"""Hosted-only controls for the new stored carriage owner.

Fixtures use the actual cable and namespace-aware STP producers. Deliberate mutations of
stored inputs are labelled; no local test run or regenerated golden is implied by this file.
"""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from cisco_toolkit.analyze import _link_carries, compute_cable_map
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.stp_topology import produce_stp_topology_observation
from cisco_toolkit.vlan_carriage import (
    _Inputs, carriage_observation_admission, compute_vlan_carriage,
    validate_vlan_carriage, vlan_row_identity,
)

A, B = "switch-a", "switch-b"
PORT = "Gi1/0/1"


def _fleet(a_allowed="10", b_allowed="10", *, channels=("", "")):
    return {
        A: {PORT: InterfaceData(port=PORT, status="connected", switchport_mode="Trunk",
                               cdp_neighbor=B, neighbor_port=PORT, endpoint_type="Switch",
                               trunk_allowed_vlans=a_allowed, port_channel=channels[0])},
        B: {PORT: InterfaceData(port=PORT, status="connected", switchport_mode="Trunk",
                               cdp_neighbor=A, neighbor_port=PORT, endpoint_type="Switch",
                               trunk_allowed_vlans=b_allowed, port_channel=channels[1])},
    }


def _observation(state="FWD", *, port=PORT, namespace="VLAN", vid=10):
    role = "Altn" if state == "BLK" else "Desg"
    body = f"""{namespace}{vid:04d}
  Root ID Priority 32778
          Address aaaa.0001.0001
          This bridge is the root
  Bridge ID Priority 32778
          Address aaaa.0001.0001
Interface Role Sts Cost Prio.Nbr Type
{port} {role} {state} 4 128.1 P2p
"""
    detail = f"{namespace}{vid:04d}\n  Number of topology changes 0 last change occurred 00:00:00 ago\n"
    return produce_stp_topology_observation(body, detail, state_capture_state="usable", detail_capture_state="usable")


def _compute(interfaces=None, *, observation=None, vlans=None, cables=None, failed=()):
    interfaces = _fleet() if interfaces is None else interfaces
    return compute_vlan_carriage(compute_cable_map(interfaces) if cables is None else cables,
                                 interfaces, observation, [{"vlan": 10}] if vlans is None else vlans,
                                 failed_sources=failed)


def _row(document):
    assert validate_vlan_carriage(document) == (True, "ok")
    assert len(document["rows"]) == 1
    assert document["coverage"]["capture_completeness_claim"] is False
    return document["rows"][0]


def test_typed_pvst_forwarding_retains_original_cable_and_role_pointers():
    interfaces = _fleet("", "")
    # Legacy ranges must not substitute for or override the typed PVST observation.
    interfaces[A][PORT].stp_blk_vlans = "10"
    result = _compute(interfaces, observation={A: _observation(), B: _observation()})
    row = _row(result)
    assert (row["state"], row["relation"], row["basis"]) == ("published", "forwarding", "typed_pvst")
    assert row["vlan_index"] == row["cable_index"] == 0 and row["vlan"] == 10
    assert row["vlan_pointer"] == "/vlan_cutover/0" and row["cable_pointer"] == "/cable_map/cables/0"
    member = row["members"][0]
    assert member["pointer"] == "/cable_map/cables/0/members/0"
    for side, host in (("a", A), ("b", B)):
        end = member[side]
        assert (end["host"], end["port"], end["signal"]) == (host, PORT, "forwarding")
        assert end["interface_pointer"] == f"/interfaces/{host}/Gi1~10~11"
        assert f"/stp_topology_observations/{host}/roles/0" in end["refs"]


def test_blocking_requires_both_ends_evidence_not_just_the_legacy_block_token():
    interfaces = _fleet("", "")
    interfaces[A][PORT].stp_blk_vlans = "10"
    # The old simulation predicate is unchanged and still says blk. New display evidence is stricter.
    assert _link_carries({"da": interfaces[A][PORT], "db": interfaces[B][PORT]}, 10) == "blk"
    one = _row(_compute(interfaces, observation={A: _observation("BLK")}))
    assert (one["state"], one["relation"], one["evidence_shape"]) == ("not_collected", None, "one_end_only")
    assert one["members"][0]["a"]["signal"] == "blocked"
    complete = _row(_compute(interfaces, observation={A: _observation("BLK"), B: _observation()}))
    assert (complete["state"], complete["relation"]) == ("published", "stp_blocked")


def test_missing_interface_does_not_become_blocked_even_with_an_observation_for_that_host():
    interfaces = _fleet("", "")
    cables = compute_cable_map(interfaces)
    del interfaces[B][PORT]  # Explicit stored-input damage after the cable was recorded.
    row = _row(_compute(interfaces, cables=cables, observation={A: _observation("BLK"), B: _observation()}))
    assert (row["state"], row["relation"]) == ("not_collected", None)
    assert row["members"][0]["b"]["interface_pointer"] is None


def test_blank_or_legacy_only_evidence_is_not_carried_neither_forwarding_nor_negative():
    interfaces = _fleet("", "")
    for recs in interfaces.values():
        recs[PORT].stp_fwd_vlans = "10"
    row = _row(_compute(interfaces))
    assert (row["state"], row["relation"], row["evidence_shape"]) == ("not_collected", None, "no_evidence")


@pytest.mark.parametrize("allowed, relation", [("all", "forwarding"), ("1-4094", "forwarding"),
                                                ("10,20-23", "forwarding"), ("none", "not_carried"),
                                                ("20-23", "not_carried")])
def test_mutual_explicit_trunk_allowance_has_only_the_configured_model_basis(allowed, relation):
    doc = _compute(_fleet(allowed, allowed))
    row = _row(doc)
    assert (row["state"], row["relation"], row["basis"]) == ("published", relation, "stored_trunk_allowance")
    assert "not observed STP forwarding or traffic" in " ".join(doc["limitations"])
    assert any(ref.endswith("/trunk_allowed_vlans") for ref in row["members"][0]["a"]["refs"])


def test_native_vlan_is_positive_membership_but_a_different_native_is_not_an_exclusion():
    interfaces = _fleet("", "")
    for records in interfaces.values():
        records[PORT].trunk_native_vlan = "10"
    assert _row(_compute(interfaces))["relation"] == "forwarding"
    assert _row(_compute(interfaces, vlans=[{"vlan": 20}]))["state"] == "not_collected"


@pytest.mark.parametrize("mode, state", [("", "not_collected"), ("Routed", "unverified"), ("Access", "unverified")])
def test_allowance_does_not_imply_an_unobserved_or_contradictory_trunk_mode(mode, state):
    interfaces = _fleet()
    interfaces[A][PORT].switchport_mode = mode
    row = _row(_compute(interfaces))
    assert row["state"] == state and row["relation"] is None


@pytest.mark.parametrize("value", [True, None, 10, [10], "10,broken", "10-foo", "40-10", "4095", "0",
                                   "10,,20", "10," + "9" * 5000])
def test_malformed_mixed_ranges_and_wrong_types_never_become_a_false_exclusion(value):
    row = _row(_compute(_fleet(value, "10")))
    assert row["state"] == "unverified" and row["relation"] is None


def test_explicit_trunk_exclusion_conflicting_with_pvst_forwarding_is_held():
    row = _row(_compute(_fleet("20", "10"), observation={A: _observation(), B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert "disagree" in row["reason"]


def test_two_different_positive_bases_do_not_silently_make_a_shared_forwarding_claim():
    row = _row(_compute(_fleet("", "10"), observation={A: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert row["members"][0]["a"]["signal"] == "forwarding"
    assert row["members"][0]["b"]["signal"] == "allowed"


def test_mst_instance_ten_is_not_vlan_ten_even_when_legacy_ranges_and_config_are_positive():
    interfaces = _fleet()
    interfaces[A][PORT].stp_fwd_vlans = "10"
    doc = _compute(interfaces, observation={A: _observation(namespace="MST"), B: _observation()})
    row = _row(doc)
    assert row["state"] == "unverified" and row["relation"] is None
    assert "MST" in row["members"][0]["a"]["reason"]
    assert doc["issues"] and doc["coverage"]["input_census_complete"] is False


def test_normalized_duplicate_pvst_port_rows_are_ambiguous_not_first_row_wins():
    observation = _observation()
    extra = {**observation["roles"][0], "interface": "GigabitEthernet1/0/1"}
    observation["roles"].append(extra)
    observation["role_candidate_count"] = observation["role_parsed_count"] = 2
    row = _row(_compute(_fleet("", ""), observation={A: observation, B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None
    assert "one normalized" in row["members"][0]["a"]["reason"]


def test_transitional_pvst_state_is_not_forwarding_from_trunk_fallback():
    row = _row(_compute(observation={A: _observation("LRN"), B: _observation()}))
    assert row["state"] == "unverified" and row["relation"] is None


def test_stp_capture_failure_and_an_unreferenced_malformed_observation_stay_visible():
    failed = produce_stp_topology_observation("", "", state_capture_state="error", detail_capture_state="missing")
    doc = _compute(observation={A: failed})
    assert _row(doc)["state"] == "analysis_unavailable"
    orphan = _compute(observation={"synthetic-orphan": {}})
    assert orphan["state"] == "unverified"
    assert orphan["issues"][0]["pointer"] == "/stp_topology_observations/synthetic-orphan"
    assert orphan["coverage"]["input_census_complete"] is False


@pytest.mark.parametrize(("case", "state", "reason", "retained"), [
    ("pvst", "published", None, True),
    ("no_roles", "published", None, True),
    ("empty", "not_collected", None, True),
    ("missing", "not_collected", None, True),
    ("error", "analysis_unavailable", "stp_failed", True),
    ("mst", "unverified", "mst_unmapped", True),
    ("role_census", "unverified", "stp_unreadable", True),
    ("duplicate_finding", "unverified", "stp_unreadable", True),
    ("blank_dict", "unverified", "stp_unreadable", False),
    ("null", "unverified", "stp_unreadable", False),
    ("malformed_capture", "unverified", "stp_unreadable", False),
])
def test_shared_stp_admission_preserves_exact_existing_record_and_producer_end_semantics(
        case, state, reason, retained):
    if case in {"empty", "missing", "error"}:
        observation = produce_stp_topology_observation(
            "", "", state_capture_state=case, detail_capture_state="missing")
    elif case == "blank_dict":
        observation = {}
    elif case == "null":
        observation = None
    else:
        observation = _observation(namespace="MST" if case == "mst" else "VLAN")
        # These are explicit stored-record perturbations, not asserted parser outputs.
        if case == "no_roles":
            observation["roles"] = []
            observation["role_candidate_count"] = observation["role_parsed_count"] = 0
        elif case == "role_census":
            observation["role_candidate_count"] += 1
            observation["finding_codes"] = sorted(set(observation["finding_codes"]) | {"role_row_malformed"})
        elif case == "duplicate_finding":
            observation["finding_codes"] = sorted(set(observation["finding_codes"]) | {"state_instance_duplicate"})
        elif case == "malformed_capture":
            observation["state_capture_state"] = []
    before = deepcopy(observation)
    direct = carriage_observation_admission(observation)
    through_owner = _Inputs(_fleet(), {A: observation}, set()).observation(A)
    assert direct[:2] == through_owner[:2] == (state, reason)
    assert direct[2] is (observation if retained else None)
    assert through_owner[2] is direct[2]
    end = _row(_compute(observation={A: observation}))["members"][0]["a"]
    if state in {"unverified", "analysis_unavailable"}:
        assert end["state"] == state and end["signal"] is None
    else:
        # An absent PVST role/capture can still use the explicitly disclosed
        # configured-trunk model; the extraction must not change that old boundary.
        assert end["state"] == "published"
        assert end["basis"] == ("typed_pvst" if case == "pvst" else "stored_trunk_allowance")
    assert observation == before


def test_shared_stp_admission_does_not_replace_environment_absence_or_failed_source_precedence():
    assert _Inputs(_fleet(), None, set()).observation(A) == ("not_collected", None, None)
    assert _Inputs(_fleet(), {}, set()).observation(A) == ("not_collected", None, None)
    assert _Inputs(_fleet(), {A: None}, set()).observation(A) == ("unverified", "stp_unreadable", None)
    assert _Inputs(_fleet(), {A: _observation()}, {"stp_topology_observations"}).observation(A) == (
        "analysis_unavailable", "failed_source", None)


def test_a_valid_unjoined_interface_record_does_not_invent_an_extra_cable():
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    interfaces["orphan"] = {PORT: InterfaceData(port=PORT)}
    doc = _compute(interfaces, cables=cables)
    assert _row(doc)["relation"] == "forwarding"
    assert doc["state"] == "published" and doc["issues"] == []
    assert doc["coverage"]["input_census_complete"] is True
    assert doc["coverage"]["cable_rows"] == doc["coverage"]["emitted_pairs"] == 1


def test_an_unjoined_malformed_range_is_a_source_issue_without_a_fabricated_vlan_query():
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    interfaces["orphan"] = {PORT: InterfaceData(port=PORT, trunk_allowed_vlans="10 \t 20")}
    doc = _compute(interfaces, cables=cables)
    assert _row(doc)["relation"] == "forwarding"
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert any(issue["pointer"] == "/interfaces/orphan/Gi1~10~11/trunk_allowed_vlans" for issue in doc["issues"])


@pytest.mark.parametrize("bad", [None, [], "unreadable", {"trunk_allowed_vlans": False},
                                 {"neighbor_port": []}, {"port_channel": None}, {"port": "Gi1/0/99"}])
@pytest.mark.parametrize("joined", [False, True])
def test_malformed_interface_values_are_censused_whether_or_not_a_cable_joins_them(bad, joined):
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    host = A if joined else "orphan"
    interfaces[host] = {PORT: deepcopy(bad)}  # Explicit stored damage after real cable construction.
    doc = _compute(interfaces, cables=cables)
    row = _row(doc)
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert any(issue["pointer"] == f"/interfaces/{host}/Gi1~10~11" for issue in doc["issues"])
    assert doc["coverage"]["emitted_pairs"] == 1
    if joined:
        assert row["state"] == "unverified" and row["relation"] is None
    else:
        assert row["state"] == "published" and row["relation"] == "forwarding"
        assert all(end["state"] == "published" for end in (row["members"][0]["a"], row["members"][0]["b"]))


def test_aliases_resolve_exactly_and_keep_original_interface_pointer():
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    rec = interfaces[A].pop(PORT)
    interfaces[A]["GigabitEthernet1/0/1"] = rec  # Explicit equivalent stored spelling.
    row = _row(_compute(interfaces, cables=cables))
    assert row["relation"] == "forwarding"
    assert row["members"][0]["a"]["interface_pointer"] == f"/interfaces/{A}/GigabitEthernet1~10~11"
    interfaces[A][PORT] = deepcopy(rec)
    duplicate = _compute(interfaces, cables=cables)
    assert _row(duplicate)["state"] == "unverified" and duplicate["coverage"]["input_census_complete"] is False


def test_host_canonical_collision_is_refused_without_selecting_a_sibling():
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    interfaces[A + ".example"] = deepcopy(interfaces[A])
    doc = _compute(interfaces, cables=cables)
    assert _row(doc)["state"] == "unverified"
    assert doc["coverage"]["input_census_complete"] is False
    assert any(issue["pointer"] == f"/interfaces/{A}.example" for issue in doc["issues"])


def _parallel(*, channels=("", ""), second_allowed="20"):
    interfaces = _fleet(channels=channels)
    for host, peer in ((A, B), (B, A)):
        interfaces[host]["Gi1/0/2"] = InterfaceData(port="Gi1/0/2", status="connected", switchport_mode="Trunk",
            cdp_neighbor=peer, neighbor_port="Gi1/0/2", endpoint_type="Switch",
            trunk_allowed_vlans=second_allowed, port_channel=channels[0 if host == A else 1])
    return interfaces


def test_parallel_cables_keep_distinct_port_identities_and_the_supplied_vlan_row_order():
    doc = _compute(_parallel(), vlans=[{"vlan": 20}, {"vlan": "0010"}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert [(r["vlan_index"], r["vlan"], r["cable_index"], r["relation"]) for r in doc["rows"]] == [
        (0, 20, 0, "not_carried"), (0, 20, 1, "forwarding"),
        (1, 10, 0, "forwarding"), (1, 10, 1, "not_carried")]
    assert doc["coverage"]["requested_pairs"] == doc["coverage"]["emitted_pairs"] == 4


def test_reversed_cable_orientation_preserves_member_ends_and_does_not_change_relation():
    interfaces = _fleet()
    remote = interfaces[B].pop(PORT)
    remote.port = "Gi1/0/24"
    interfaces[B][remote.port] = remote
    interfaces[A][PORT].neighbor_port = remote.port
    cables = compute_cable_map(interfaces)
    row = cables["cables"][0]
    row["a"], row["b"] = row["b"], row["a"]
    row["a_port"], row["b_port"] = row["b_port"], row["a_port"]
    for member in row["members"]:
        member["a_port"], member["b_port"] = member["b_port"], member["a_port"]
    result = _row(_compute(interfaces, cables=cables))
    assert result["relation"] == "forwarding"
    assert result["members"][0]["a"]["host"] == B and result["members"][0]["b"]["host"] == A
    assert result["members"][0]["a"]["interface_pointer"] == f"/interfaces/{B}/Gi1~10~124"
    assert result["members"][0]["b"]["interface_pointer"] == f"/interfaces/{A}/Gi1~10~11"


def test_host_and_interface_witnesses_use_original_rfc6901_tokens():
    interfaces = _fleet()
    escaped = "switch/a~b"
    interfaces[escaped] = interfaces.pop(A)
    interfaces[B][PORT].cdp_neighbor = escaped
    row = _row(_compute(interfaces))
    end = next(e for e in (row["members"][0]["a"], row["members"][0]["b"]) if e["host"] == escaped)
    assert end["interface_pointer"] == "/interfaces/switch~1a~0b/Gi1~10~11"
    assert row["relation"] == "forwarding"


def test_bundle_requires_every_member_agreement_and_consistent_local_port_channels():
    interfaces = _parallel(channels=("Po1", "Po20"), second_allowed="10")
    doc = _compute(interfaces)
    row = _row(doc)
    assert row["relation"] == "forwarding" and row["basis"] == "member_consensus" and len(row["members"]) == 2
    interfaces[A]["Gi1/0/2"].trunk_allowed_vlans = "20"
    mixed = _row(_compute(interfaces))
    assert mixed["state"] == "unverified" and mixed["relation"] is None
    assert [m["relation"] for m in mixed["members"]] == ["forwarding", "not_carried"]
    interfaces[A]["Gi1/0/2"].trunk_allowed_vlans = "10"
    interfaces[A]["Gi1/0/2"].port_channel = "Po2"
    ambiguous = _row(_compute(interfaces))
    assert ambiguous["state"] == "unverified" and "consistent local bundle" in ambiguous["reason"]


def test_real_bundle_accepts_port_channel_spelling_and_different_local_numbers():
    interfaces = _parallel(channels=("Port-channel001", "Po020"), second_allowed="10")
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["is_pc"] is True
    row = _row(_compute(interfaces, cables=cables))
    assert len(row["members"]) == 2
    assert (row["state"], row["relation"], row["basis"]) == ("published", "forwarding", "member_consensus")


@pytest.mark.parametrize("bad", ["Gi1/0/8", "Vlan10", "Loopback1", "Po1.10", "Po0", "", None, 7])
def test_real_cable_builder_does_not_make_a_non_channel_member_identity_admissible(bad):
    interfaces = _parallel(channels=("Po1", "Po20"), second_allowed="10")
    for record in interfaces[A].values():
        record.port_channel = bad
    # The other end still names a channel, so the real legacy builder groups both links.
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["is_pc"] is True
    row = _row(_compute(interfaces, cables=cables))
    assert len(row["members"]) == 2 and row["state"] == "unverified" and row["relation"] is None


def test_physical_port_tokens_on_both_sides_cannot_certify_a_bundle():
    interfaces = _parallel(channels=("Gi1/0/8", "Gi1/0/9"), second_allowed="10")
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and len(cables["cables"][0]["members"]) == 2
    row = _row(_compute(interfaces, cables=cables))
    assert row["relation"] is None and row["state"] == "unverified"


def test_duplicate_cables_and_malformed_tail_are_retained_in_the_pair_denominator():
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    cables["cables"].append(deepcopy(cables["cables"][0]))
    cables["cables"].append(None)  # Unreadable stored row, not an absent cable.
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert len(doc["rows"]) == doc["coverage"]["cable_rows"] == doc["coverage"]["requested_pairs"] == 3
    assert all(row["state"] == "unverified" and row["relation"] is None for row in doc["rows"])
    assert doc["rows"][2]["cable_pointer"] == "/cable_map/cables/2" and doc["issues"]


@pytest.mark.parametrize("damage", ["outer_port", "extra_member_key"])
@pytest.mark.parametrize("vlans", [[{"vlan": 10}], [{"vlan": 10}, {"vlan": 20}]])
def test_readable_duplicate_inside_a_refused_tail_withholds_both_and_the_result_validates(damage, vlans):
    interfaces = _fleet()
    cables = compute_cable_map(interfaces)
    cables["cables"].append(deepcopy(cables["cables"][0]))
    if damage == "outer_port":
        cables["cables"][1]["a_port"] = "Gi1/0/2"
    else:
        cables["cables"][1]["members"][0]["extra"] = "malformed stored member"
    before = deepcopy(cables)
    doc = _compute(interfaces, cables=cables, vlans=vlans)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert cables == before
    assert doc["state"] == "unverified" and doc["coverage"]["input_census_complete"] is False
    assert doc["coverage"]["cable_rows"] == 2 and len(doc["rows"]) == 2 * len(vlans)
    assert all(row["state"] == "unverified" and row["relation"] is None for row in doc["rows"])
    assert all(member["state"] == "unverified" for row in doc["rows"] for member in row["members"])
    assert {row["members"][0]["pointer"] for row in doc["rows"]} == {
        "/cable_map/cables/0/members/0", "/cable_map/cables/1/members/0"}
    assert any(issue["pointer"].startswith("/cable_map/cables/1") for issue in doc["issues"])


@pytest.mark.parametrize("damage", ["outer_port", "extra_member_key"])
def test_a_non_overlapping_refused_tail_keeps_the_unrelated_positive_and_validates(damage):
    interfaces = _parallel(second_allowed="10")
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 2
    if damage == "outer_port":
        cables["cables"][1]["a_port"] = "Gi1/0/99"
    else:
        cables["cables"][1]["members"][0]["extra"] = True
    doc = _compute(interfaces, cables=cables)
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert len(doc["rows"]) == 2 and doc["state"] == "unverified"
    assert (doc["rows"][0]["state"], doc["rows"][0]["relation"]) == ("published", "forwarding")
    assert doc["rows"][1]["state"] == "unverified" and doc["rows"][1]["relation"] is None


def _reverse_observed_bundle_with_decoys():
    def port(name, allowed, channel, peer="", peer_port=""):
        return InterfaceData(port=name, status="connected", switchport_mode="Trunk", endpoint_type="Switch",
                             cdp_neighbor=peer, neighbor_port=peer_port, trunk_allowed_vlans=allowed,
                             port_channel=channel)
    # Source order makes the first physical link A:1 -> B:11, while only B reports
    # the second as B:22 -> A:2. The legacy builder folds by unordered host pair.
    return {
        A: {"Gi1/0/1": port("Gi1/0/1", "10", "Po1", B, "Gi1/0/11"),
            "Gi1/0/2": port("Gi1/0/2", "20", "Po1"),
            "Gi1/0/22": port("Gi1/0/22", "10", "Po1")},
        B: {"Gi1/0/11": port("Gi1/0/11", "10", "Po20"),
            "Gi1/0/22": port("Gi1/0/22", "20", "Po20", A, "Gi1/0/2"),
            "Gi1/0/2": port("Gi1/0/2", "10", "Po20")},
    }


def test_real_reverse_observed_lag_member_cannot_use_decoy_interface_allowances():
    interfaces = _reverse_observed_bundle_with_decoys()
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1
    cable = cables["cables"][0]
    assert (cable["a"], cable["b"]) == (A, B)
    assert cable["members"] == [{"a_port": "Gi1/0/1", "b_port": "Gi1/0/11"},
                                {"a_port": "Gi1/0/22", "b_port": "Gi1/0/2"}]
    assert interfaces[A]["Gi1/0/2"].trunk_allowed_vlans == interfaces[B]["Gi1/0/22"].trunk_allowed_vlans == "20"
    before = deepcopy(cables)
    row = _row(_compute(interfaces, cables=cables))
    assert cables == before  # No hidden orientation repair of the cable owner.
    assert row["state"] == "unverified" and row["relation"] is None
    assert row["members"][0]["relation"] == "forwarding"
    refused = row["members"][1]
    assert refused["state"] == "unverified" and refused["relation"] is None
    assert (refused["a"]["port"], refused["b"]["port"]) == ("Gi1/0/22", "Gi1/0/2")
    for end in (refused["a"], refused["b"]):
        assert end["state"] == "unverified" and end["signal"] is None
        assert "no stored neighbor observation" in end["reason"]
        assert "/cable_map/cables/0/members/1" in end["refs"]


def test_correctly_oriented_one_direction_bundle_keeps_its_positive_without_inventing_reciprocity():
    interfaces = _parallel(channels=("Po1", "Po20"), second_allowed="10")
    for record in interfaces[B].values():
        record.cdp_neighbor = record.neighbor_port = ""
    cables = compute_cable_map(interfaces)
    assert len(cables["cables"]) == 1 and cables["cables"][0]["confirmation"] == f"One end ({A})"
    row = _row(_compute(interfaces, cables=cables))
    assert row["relation"] == "forwarding" and row["basis"] == "member_consensus"
    for member in row["members"]:
        assert member["a"]["interface_pointer"] + "/cdp_neighbor" in member["a"]["refs"]
        assert member["a"]["interface_pointer"] + "/neighbor_port" in member["a"]["refs"]
        assert not any(ref.endswith("/cdp_neighbor") or ref.endswith("/neighbor_port") for ref in member["b"]["refs"])


def test_one_direction_nonbundled_physical_observation_remains_admissible():
    interfaces = _fleet()
    interfaces[B][PORT].cdp_neighbor = interfaces[B][PORT].neighbor_port = ""
    cables = compute_cable_map(interfaces)
    assert cables["cables"][0]["is_pc"] is False and cables["cables"][0]["confirmation"] == f"One end ({A})"
    assert _row(_compute(interfaces, cables=cables))["relation"] == "forwarding"


def test_published_bundle_record_requires_its_stored_orientation_witnesses():
    doc = _compute(_parallel(channels=("Po1", "Po20"), second_allowed="10"))
    assert validate_vlan_carriage(doc) == (True, "ok")
    for end in (doc["rows"][0]["members"][0]["a"], doc["rows"][0]["members"][0]["b"]):
        end["refs"] = [ref for ref in end["refs"] if not ref.endswith(("/cdp_neighbor", "/neighbor_port"))]
    assert validate_vlan_carriage(doc)[0] is False


@pytest.mark.parametrize("bad", [None, [], {"a_port": PORT}, {"a_port": PORT, "b_port": PORT, "extra": True}])
def test_malformed_bundle_member_is_not_dropped_or_executed_as_another_shape(bad):
    interfaces = _parallel(channels=("Po1", "Po1"), second_allowed="10")
    cables = compute_cable_map(interfaces)
    cables["cables"][0]["members"][1] = bad
    row = _row(_compute(interfaces, cables=cables))
    assert len(row["members"]) == 2 and row["members"][1]["state"] == "unverified"
    assert row["state"] == "unverified" and row["relation"] is None


@pytest.mark.parametrize("bad", [True, 0, 4095, "10x", None])
def test_invalid_vlan_never_borrows_vlan_one_evidence(bad):
    row = _row(_compute(vlans=[{"vlan": bad}]))
    assert row["vlan"] is None and row["state"] == "unverified" and row["relation"] is None
    assert all(end["state"] == "unverified" and end["signal"] is None and end["refs"] == []
               for end in (row["members"][0]["a"], row["members"][0]["b"]))


def test_vlan_alias_collision_keeps_both_rows_and_refuses_a_definite_relation():
    doc = _compute(vlans=[{"vlan": 10}, {"vlan": "0010"}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert len(doc["rows"]) == 2 and all(r["state"] == "unverified" for r in doc["rows"])
    assert {issue["pointer"] for issue in doc["issues"]} == {"/vlan_cutover/0/vlan", "/vlan_cutover/1/vlan"}


@pytest.mark.parametrize(("selector", "expected"), [
    (1, 1), (10, 10), (4094, 4094), ("0010", 10), ("0000000000000010", 10),
    (True, None), (False, None), (10.0, None), (0, None), (4095, None),
    ("10.0", None), (" 10", None), ("+10", None), ("00000000000000010", None),
    (None, None), ([], None), ({}, None),
])
def test_public_vlan_row_selector_and_producer_share_exact_admission(selector, expected):
    source = {"vlan": selector}
    before = deepcopy(source)
    assert vlan_row_identity(source) == expected
    row = _row(_compute(vlans=[source]))
    assert row["vlan"] == expected and source == before
    if expected is None:
        assert row["state"] == "unverified" and row["relation"] is None


@pytest.mark.parametrize("row", [None, [], "10", 10, {}, {"other": 10}])
def test_public_vlan_row_selector_does_not_invent_a_missing_row_identity(row):
    assert vlan_row_identity(row) is None


@pytest.mark.parametrize("source", ["cable_map", "interfaces", "stp_topology_observations", "vlan_cutover"])
def test_failed_input_is_not_an_empty_or_successful_carriage_section(source):
    doc = _compute(failed=(source,))
    assert validate_vlan_carriage(doc) == (True, "ok")
    assert doc["state"] == "analysis_unavailable" and doc["rows"][0]["relation"] is None
    assert any(issue["pointer"] == "/" + source for issue in doc["issues"])


def test_missing_empty_and_malformed_sources_remain_distinct():
    interfaces = _fleet()
    missing = compute_vlan_carriage(None, interfaces, None, [{"vlan": 10}])
    empty = compute_vlan_carriage(compute_cable_map({}), {}, {}, [{"vlan": 10}])
    malformed = compute_vlan_carriage({"cables": "unreadable"}, interfaces, {}, [{"vlan": 10}])
    for doc in (missing, empty, malformed):
        assert validate_vlan_carriage(doc) == (True, "ok")
        assert doc["coverage"]["capture_completeness_claim"] is False
    assert missing["state"] == "not_collected" and missing["coverage"]["cable_rows"] is None
    assert empty["state"] == "collected_but_empty" and empty["coverage"]["requested_pairs"] == 0
    assert malformed["state"] == "unverified"
    assert _compute(vlans=[])["state"] == "collected_but_empty"


def test_json_roundtrip_sparse_records_and_input_purity_preserve_identical_output():
    interfaces = _fleet("", "")
    observations = {A: _observation(), B: _observation()}
    cables, vlans = compute_cable_map(interfaces), [{"vlan": "0010"}]
    before = deepcopy((interfaces, observations, cables, vlans))
    doc = compute_vlan_carriage(cables, interfaces, observations, vlans)
    stored_interfaces = {h: {p: asdict(record) for p, record in ports.items()} for h, ports in interfaces.items()}
    round_trip = json.loads(json.dumps([cables, stored_interfaces, observations, vlans]))
    assert compute_vlan_carriage(round_trip[0], round_trip[1], round_trip[2], round_trip[3]) == doc
    assert (interfaces, observations, cables, vlans) == before
    assert validate_vlan_carriage(json.loads(json.dumps(doc))) == (True, "ok")
    doc["rows"][0]["ends"]["a"] = "changed-output"
    assert (interfaces, observations, cables, vlans) == before


@pytest.mark.parametrize("value", ["10 \t 20", "10 \n 20", "10, \t ,20"])
def test_internal_mixed_whitespace_tokens_are_refused_with_the_actual_field_witness(value):
    row = _row(_compute(_fleet(value, "10")))
    assert row["state"] == "unverified" and row["relation"] is None
    assert f"/interfaces/{A}/Gi1~10~11/trunk_allowed_vlans" in row["members"][0]["a"]["refs"]
    assert "expression is malformed" in row["members"][0]["a"]["reason"]


@pytest.mark.parametrize("value", ["10 20", "10 , 20-23", "10,20 30"])
def test_the_same_range_separator_grammar_keeps_valid_space_and_comma_lists(value):
    row = _row(_compute(_fleet(value, value)))
    assert row["state"] == "published" and row["relation"] == "forwarding"


@pytest.mark.parametrize("mutation", ["outer_port", "member_and_outer_port", "pointer_port", "pointer_host"])
def test_one_vlan_closed_record_cannot_contradict_its_member_interface_identity(mutation):
    doc = _compute()
    assert validate_vlan_carriage(doc) == (True, "ok")
    row, end = doc["rows"][0], doc["rows"][0]["members"][0]["a"]
    if mutation == "outer_port":
        row["ends"]["a_port"] = "Gi1/0/2"
    elif mutation == "member_and_outer_port":
        row["ends"]["a_port"] = end["port"] = "Gi1/0/2"
    else:
        old = end["interface_pointer"]
        new = f"/interfaces/{A}/Gi1~10~12" if mutation == "pointer_port" else "/interfaces/unrelated/Gi1~10~11"
        end["interface_pointer"] = new
        end["refs"] = [new if ref == old else ref for ref in end["refs"]]
    assert validate_vlan_carriage(doc)[0] is False, mutation


def test_duplicate_stored_vlan_identity_cannot_keep_two_published_relations():
    doc = _compute(vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    doc["rows"][1]["vlan"] = 10
    assert validate_vlan_carriage(doc)[0] is False
    # Actual duplicate selectors are retained with explicit UV rows/members and witnesses.
    genuine = _compute(vlans=[{"vlan": 10}, {"vlan": "0010"}])
    assert validate_vlan_carriage(genuine) == (True, "ok")
    assert all(row["state"] == "unverified" and row["relation"] is None for row in genuine["rows"])


@pytest.mark.parametrize("mutation", ["extra", "schema", "null_relation", "false_census", "capture_promotion",
                                      "invalid_basis", "signal_basis", "held_member", "aggregate_relation",
                                      "row_identity", "missing_limitation", "cross_vlan_identity"])
def test_closed_stored_contract_refuses_inconsistent_or_promoting_mutations(mutation):
    doc = _compute(vlans=[{"vlan": 10}, {"vlan": 20}])
    assert validate_vlan_carriage(doc) == (True, "ok")
    row = doc["rows"][0]
    if mutation == "extra":
        row["healthy"] = True
    elif mutation == "schema":
        doc["schema"] = "vlan_carriage/future"
    elif mutation == "null_relation":
        row["relation"] = None
    elif mutation == "false_census":
        doc["coverage"]["by_state"]["published"] = True
    elif mutation == "capture_promotion":
        doc["coverage"]["capture_completeness_claim"] = True
    elif mutation == "invalid_basis":
        row["basis"] = "none"
    elif mutation == "signal_basis":
        row["members"][0]["a"]["basis"] = "typed_pvst"
    elif mutation == "held_member":
        held = _row(_compute(_fleet("", "")))["members"][0]
        row["members"][0] = held  # Structurally valid held member cannot support published aggregate.
    elif mutation == "aggregate_relation":
        row["relation"] = "stp_blocked"
    elif mutation == "row_identity":
        row["cable_pointer"] = "/cable_map/cables/1"
    elif mutation == "missing_limitation":
        doc["limitations"].pop(2)
    else:
        doc["rows"][1]["ends"]["a_port"] = "Gi1/0/2"
    assert validate_vlan_carriage(doc)[0] is False, mutation
