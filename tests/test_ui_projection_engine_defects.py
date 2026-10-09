"""W2b: project G13/G15/G49 facts from their producers without rebuilding their conclusions."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot, stp_topology
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.model import InterfaceData

PUB, NC, UV, AU, CBE = "published", "not_collected", "unverified", "analysis_unavailable", "collected_but_empty"
STP_FIELDS = ("stp_root_state", "stp_root_reason", "stp_root_claimants", "stp_root_identities")


def _root(priority=32778, address="aaaa.0000.0001", claim=True, **kwargs):
    return {"root_priority": priority, "root_address": address, "is_root": claim, **kwargs}


def _vlan_snapshot(roots):
    return {"stp_roots": roots, "vlan_cutover": analyze.compute_vlan_cutover_matrix({}, roots)}


def _vlan(snap, vlan=10):
    return next(row for row in uip.project_inventory(snap)["vlans"]["rows"]["items"]
                if row["vlan"]["value"] == vlan)


def _validate(snap, host=None):
    schema = uip.ui_projection_schema()
    document = uip.project(snap)
    if host is not None:
        schema = {"$ref": "#/$defs/DeviceDocument", "$defs": schema["$defs"]}
        document = uip.project_device(snap, host)
    errors = list(Draft202012Validator(schema).iter_errors(document))
    assert not errors, [(list(e.path), e.message) for e in errors]


def test_g13_real_groups_have_source_bound_device_identity_and_preserve_reordered_labels():
    interfaces = {h: {"Gi1/0/1": InterfaceData(port="Gi1/0/1", vlan=str(i), switchport_mode="Access")}
                  for i, h in enumerate(("a", "b", "c"), 10)}
    groups = analyze.compute_move_groups(interfaces)
    assert [g["group"] for g in groups] == ["Group 1", "Group 2", "Group 3"]
    snap = {"devices": {h: {} for h in interfaces}, "move_groups": list(reversed(groups))}
    before = copy.deepcopy(snap)
    for row in uip.project_inventory(snap)["devices"]["rows"]["items"]:
        index = next(i for i, g in enumerate(snap["move_groups"]) if row["host"] in g["switches"])
        fact = row["move_group"]
        assert (fact["state"], fact["value"]) == (PUB, snap["move_groups"][index]["group"])
        assert fact["subject"] == f"/move_groups/{index}/group"
        assert uip.project_device(snap, row["host"])["device"]["move_group"] == fact
    _validate(snap)
    _validate(snap, "a")
    assert snap == before


@pytest.mark.parametrize("groups,state", [([{"switches": ["a"]}], NC),
    ([{"group": "G", "switches": ["a"]}, {"switches": ["b"]}], UV),
    ([{"group": "G", "switches": ["a"]}, {"group": "G", "switches": ["b"]}], UV),
    ([{"group": "G", "switches": ["a"]}, {"group": "H", "switches": ["a"]}], UV),
    ([{"group": "G", "switches": "a"}], UV), ([{"group": [], "switches": ["a"]}], UV)])
def test_g13_legacy_and_malformed_groups_do_not_invent_identity(groups, state):
    snap = {"devices": {"a": {}}, "move_groups": groups}
    fact = uip.project_device(snap, "a")["device"]["move_group"]
    assert fact["state"] == state and fact["value"] is None
    _validate(snap, "a")


def test_g13_failed_groups_withhold_identity_and_absent_member_is_explicit():
    snap = {"devices": {"a": {}}, "move_groups": [{"group": "G", "switches": ["b"]}]}
    assert uip.project_device(snap, "a")["device"]["move_group"]["state"] == CBE
    snap["assessment_integrity"] = {"failed_phases": ["move groups"]}
    fact = uip.project_device(snap, "a")["device"]["move_group"]
    assert fact["state"] == AU and fact["value"] is None


def test_g13_actual_producer_wave_is_published_and_legacy_caveat_is_scoped():
    groups = analyze.compute_move_groups({"a": {}, "b": {}})
    punch = analyze.compute_migration_punchlist(
        [], {}, {}, [{"switch": "b", "port": "Gi1/0/1", "risk": "err-disabled", "severity": "High"}],
        [], [], {}, [], groups)
    assert punch and punch[0]["wave"] == "Group 2"
    snap = {"move_groups": groups, "punchlist": punch}
    findings = uip.project_findings(snap)
    assert findings["rows"]["items"][0]["wave"]["value"] == "Group 2"
    assert "move_group_label_absent" not in findings["rows"].get("caveats", [])


def test_g13_forged_derived_groups_and_split_flags_are_withheld():
    groups = analyze.compute_move_groups({"a": {}, "b": {}})
    punch = analyze.compute_migration_punchlist(
        [], {}, {}, [{"switch": "b", "port": "Gi1/0/1", "risk": "err-disabled", "severity": "High"}],
        [], [], {}, [], groups)
    snap = {"move_groups": groups, "punchlist": punch}
    punch[0]["wave"] = "Group 99"
    assert uip.project_findings(snap)["rows"]["items"][0]["wave"]["state"] == UV
    endpoints = [{"host": host, "port": "Gi1/0/1", "mac": "aabb.ccdd.eeff", "endpoint_class": "Server"}
                 for host in ("a", "b")]
    snap["endpoint_dependencies"] = analyze.compute_endpoint_dependencies(endpoints, groups)
    raw = snap["endpoint_dependencies"]["dual_homed"][0]
    assert raw["move_groups"] == ["Group 1", "Group 2"] and raw["split_across_groups"] is True
    raw.update(move_groups=["Group 99"], split_across_groups=False)
    row = uip.project_inventory(snap)["endpoints"]["dual_homed"]["items"][0]
    assert row["move_groups"]["state"] == row["split_across_groups"]["state"] == UV


def test_g13_custom_labels_follow_owner_order_and_wrong_device_label_is_rejected():
    groups = [{"group": "Cutover Z", "switches": ["b"]}, {"group": "Cutover A", "switches": ["a"]}]
    punch = analyze.compute_migration_punchlist([], {}, {}, [], [], [], {}, [], groups,
        l2={"addressing": {"dup_ip": [{"ip": "192.0.2.1", "where": [("a", "Vlan10", 10),
                                                                      ("b", "Vlan20", 20)]}], "dup_subnet": []}})
    assert punch and punch[0]["wave"] == "Cutover Z, Cutover A"
    snap = {"move_groups": groups, "punchlist": punch}
    assert uip.project_findings(snap)["rows"]["items"][0]["wave"]["value"] == punch[0]["wave"]
    punch[0].update(devices=["a"], wave="Cutover Z")
    assert uip.project_findings(snap)["rows"]["items"][0]["wave"]["state"] == UV
    groups[0].pop("group")
    findings = uip.project_findings(snap)
    assert findings["rows"]["items"][0]["wave"]["state"] == UV
    assert "move_group_label_absent" not in findings["rows"].get("caveats", [])


def test_g15_real_parser_duplicate_claimants_are_preserved_and_never_named_root():
    import synthetic_fixtures as fx
    from cisco_toolkit.parse import parse_spanning_tree_root
    roots = {"access1": parse_spanning_tree_root(fx._ACCESS1["show spanning-tree"]),
             "access2": parse_spanning_tree_root(fx._ACCESS1["show spanning-tree"]),
             "core1": parse_spanning_tree_root(fx._CORE1["show spanning-tree"])}
    snap = _vlan_snapshot(roots)
    before = copy.deepcopy(snap)
    for raw in snap["vlan_cutover"]:
        row = _vlan(snap, raw["vlan"])
        for field in STP_FIELDS:
            assert row[field]["state"] == (PUB if raw[field] else CBE)
            assert row[field]["value"] == (raw[field] or None)
    ambiguous = _vlan(snap, 30)
    assert ambiguous["stp_root_state"]["value"] == "ambiguous"
    assert ambiguous["stp_root_reason"]["value"] == "duplicate_bridge_identity"
    assert ambiguous["stp_root"]["state"] == ambiguous["stp_root_default_election"]["state"] == UV
    assert _vlan(snap)["stp_root"]["value"] == "core1"
    _validate(snap)
    assert snap == before


@pytest.mark.parametrize("roots,root_state,reason,flag", [
    ({"a": {"10": _root()}}, "published", "single_claimant", True),
    ({"a": {"10": _root(-7)}}, "published", "single_claimant", False),
    ({"a": {"10": _root(None)}}, "published", "single_claimant", None),
    ({"a": {"10": _root()}, "b": {"10": _root(24586, claim=False)}}, "published", "single_claimant", None),
    ({"a": {"10": _root(claim=False)}}, "not_observed", "root_not_collected", None),
    ({"a": {"10": _root(address="", claim=False)}}, "not_observed", "no_root_evidence", None),
    ({"a": {"10": None}}, "ambiguous", "malformed_root_rows", None),
    ({"a": {"10": _root()}, "b": {"10": _root(address="bbbb.0000.0002")}},
     "ambiguous", "multiple_root_identities", None)])
def test_g15_projects_each_owner_verdict_and_signed_priorities(roots, root_state, reason, flag):
    snap = _vlan_snapshot(roots)
    row, raw = _vlan(snap), snap["vlan_cutover"][0]
    assert row["stp_root_state"]["value"] == root_state
    assert row["stp_root_reason"]["value"] == reason
    assert row["stp_root_identities"]["value"] == (raw["stp_root_identities"] or None)
    assert row["stp_root"]["state"] == (PUB if root_state == PUB else UV if root_state == "ambiguous" else NC)
    assert row["stp_root_default_election"]["value"] is flag
    assert row["stp_root_default_election"]["state"] == (PUB if flag is not None else UV if root_state == "ambiguous" else NC)
    _validate(snap)


def test_g15_legacy_root_does_not_prove_uniqueness_and_projection_never_reelects():
    snap = _vlan_snapshot({"a": {"10": _root()}})
    # A changed raw claim cannot cause the projection to rerun the election or choose its own root.
    snap["stp_roots"]["a"]["10"]["root_priority"] = None
    assert _vlan(snap)["stp_root_default_election"]["value"] is True
    for field in STP_FIELDS:
        del snap["vlan_cutover"][0][field]
    row = _vlan(snap)
    assert all(row[f]["state"] == NC for f in STP_FIELDS + ("stp_root", "stp_root_default_election"))


@pytest.mark.parametrize("field,bad", [("stp_root_state", []), ("stp_root_reason", "future"),
    ("stp_root_claimants", ["a", "b"]), ("stp_root_identities", [{}]), ("stp_root", "other"),
    ("stp_root_default_election", "false")])
def test_g15_malformed_published_verdict_cannot_publish_root(field, bad):
    snap = _vlan_snapshot({"a": {"10": _root()}})
    snap["vlan_cutover"][0][field] = bad
    row = _vlan(snap)
    assert row["stp_root"]["state"] == row["stp_root_default_election"]["state"] == UV
    _validate(snap)


def test_g15_published_default_flag_must_match_owned_priority_rule():
    snap = _vlan_snapshot({"a": {"10": _root()}})
    snap["vlan_cutover"][0]["stp_root_default_election"] = False
    assert _vlan(snap)["stp_root"]["state"] == UV
    assert _vlan(snap)["stp_root_default_election"]["state"] == UV


def test_g15_identity_metadata_cannot_contradict_root_state_or_claimants():
    snap = _vlan_snapshot({"a": {"10": _root(claim=False)},
                           "b": {"10": _root(address="bbbb.0000.0002", claim=False)}})
    snap["vlan_cutover"][0].update(stp_root_state="not_observed", stp_root_reason="root_not_collected",
                                  stp_root=uip.NOT_OBSERVED_SENTINEL)
    assert _vlan(snap)["stp_root_state"]["state"] == UV
    snap = _vlan_snapshot({"a": {"10": _root()}, "b": {"10": _root()}})
    snap["vlan_cutover"][0]["stp_root_identities"][0]["claimants"] = ["a"]
    assert _vlan(snap)["stp_root_claimants"]["state"] == UV


def test_g15_empty_metadata_under_malformed_election_does_not_claim_coverage():
    snap = _vlan_snapshot({"a": {"10": None}})
    row = _vlan(snap)
    assert row["stp_root_state"]["value"] == "ambiguous"
    assert row["stp_root_reason"]["value"] == "malformed_root_rows"
    for field in ("stp_root_claimants", "stp_root_identities"):
        assert row[field]["state"] == CBE
        assert "published STP" in row[field]["reason"]
        assert "contains no parsed entries" in row[field]["reason"]
        assert "election state/reason" in row[field]["reason"]
        assert "not a blind spot" not in row[field]["reason"]
        assert "no root" not in row[field]["reason"]


@pytest.mark.parametrize("duplicate_key", [10, 10.0])
def test_g15_duplicate_owner_vlan_keys_cannot_publish_two_roots(duplicate_key):
    first = _vlan_snapshot({"a": {"10": _root()}})
    second = _vlan_snapshot({"b": {"10": _root(address="bbbb.0000.0002")}})
    second["vlan_cutover"][0]["vlan"] = duplicate_key
    first["stp_roots"].update(second["stp_roots"])
    first["vlan_cutover"].extend(second["vlan_cutover"])
    rows = uip.project_inventory(first)["vlans"]["rows"]["items"]
    assert len(rows) == 2 and [r["pointer"] for r in rows] == ["/vlan_cutover/0", "/vlan_cutover/1"]
    for row in rows:
        for field in STP_FIELDS + ("stp_root", "stp_root_default_election"):
            assert row[field]["state"] == UV and row[field]["value"] is None
        assert [r["pointer"] for r in row["selections"]["stp_roots"]["items"]] == [
            "/stp_roots/a/10", "/stp_roots/b/10"]


def _ready_vlan_snapshot(roots, verdict="READY"):
    groups = analyze.compute_move_groups({host: {} for host in roots})
    readiness = [{"group": group["group"], "readiness": verdict} for group in groups]
    return {"stp_roots": roots, "move_groups": groups, "migration_readiness": readiness,
            "vlan_cutover": analyze.compute_vlan_cutover_matrix({}, roots, move_groups=groups,
                                                               migration_readiness=readiness)}


@pytest.mark.parametrize("invalid", ["contradiction", "duplicate"])
def test_g15_invalid_stp_metadata_cannot_publish_ready(invalid):
    snap = _ready_vlan_snapshot({"a": {"10": _root()}})
    assert _vlan(snap)["readiness"]["value"] == "READY"
    if invalid == "contradiction":
        snap["vlan_cutover"][0]["stp_root_default_election"] = False
    else:
        snap["vlan_cutover"].append(copy.deepcopy(snap["vlan_cutover"][0]))
    for row in uip.project_inventory(snap)["vlans"]["rows"]["items"]:
        assert row["readiness"]["state"] == UV and row["readiness"]["value"] is None


@pytest.mark.parametrize("roots,legacy", [({"a": {"10": _root()}, "b": {"10": _root()}}, False),
    ({"a": {"10": _root(claim=False)}}, False), ({"a": {"10": _root()}}, True)])
def test_g15_valid_ready_verdict_is_preserved_with_stp_scope_qualification(roots, legacy):
    snap = _ready_vlan_snapshot(roots)
    if legacy:
        for field in STP_FIELDS:
            del snap["vlan_cutover"][0][field]
    fact = _vlan(snap)["readiness"]
    assert fact["state"] == PUB and fact["value"] == "READY"
    assert "vlan_readiness_scope" in fact["caveats"]
    _validate(snap)


@pytest.mark.parametrize("verdict", ["READY", "CAUTION", "NOT READY"])
def test_g15_all_published_readiness_values_disclose_the_owner_scope(verdict):
    snap = _ready_vlan_snapshot({"a": {"10": _root()}}, verdict)
    fact = _vlan(snap)["readiness"]
    assert fact["state"] == PUB and fact["value"] == verdict
    assert "vlan_readiness_scope" in fact["caveats"]


def test_g15_selection_uses_bounded_ascii_owner_keys_preserves_spelling_and_malformed_rows():
    roots = {"a": {" 00010 ": _root(), "10": None, "١٠": _root(), "0" * 17 + "10": _root(),
                    "9" * 5000: _root(), "-10": _root()}, "mst": {"10": _root(is_mst=True)}}
    snap = _vlan_snapshot(roots)
    row = _vlan(snap)
    assert row["stp_root_state"]["value"] == "ambiguous"
    assert [r["pointer"] for r in row["selections"]["stp_roots"]["items"]] == [
        "/stp_roots/a/ 00010 ", "/stp_roots/a/10"]
    assert row["selections"]["stp_roots"]["state"] == UV


def test_g15_failure_overrides_stale_owner_verdict():
    snap = _vlan_snapshot({"a": {"10": _root()}})
    snap["assessment_integrity"] = {"failed_phases": ["VLAN cutover matrix"]}
    row = uip.project_inventory(snap)["vlans"]["rows"]["items"][0]
    for field in STP_FIELDS + ("stp_root", "stp_root_default_election"):
        assert row[field]["state"] == AU


def test_g49_real_dossier_preserves_input_states_and_only_owner_screened_empty_is_clean():
    health = [{"switch": "a", "band": "Excellent", "score": 95}]
    dossiers = analyze.compute_device_dossiers(health_scores=health, physical_health=[])
    snap = {"devices": {"a": {}}, "health_scores": health, "device_dossiers": dossiers}
    raw = dossiers["per_device"][0]["exposures"]
    projected = uip.project_device(snap, "a")["device"]["dossier"]["exposures"]["items"]
    assert [item["fact"]["value"] for item in projected] == raw
    assert {e["input_state"] for e in raw} >= {PUB, CBE, NC, AU}
    assert next(e for e in raw if e["axis"] == "Physical")["state"] == "ok"
    _validate(snap, "a")


@pytest.mark.parametrize("change", [{"input_state": "future"}, {"input_state": None},
    {"input_state": NC, "state": "ok"}, {"input_state": CBE, "state": "ok", "axis": "Protocol"},
    {"legacy": True}])
def test_g49_missing_or_malformed_input_state_withholds_exposure(change):
    dossiers = analyze.compute_device_dossiers(health_scores=[{"switch": "a", "band": "Excellent", "score": 95}])
    raw = dossiers["per_device"][0]["exposures"][0]
    if "legacy" in change:
        del raw["input_state"]
    else:
        raw.update(change)
    snap = {"devices": {"a": {}}, "device_dossiers": dossiers}
    fact = uip.project_device(snap, "a")["device"]["dossier"]["exposures"]["items"][0]["fact"]
    assert fact["state"] == UV and fact["value"] is None
    _validate(snap, "a")


def test_w2b_schema_and_vocabulary_are_closed_and_source_pinned():
    assert uip.STP_ROOT_ELECTION_STATES == stp_topology.STP_ROOT_ELECTION_STATES
    assert uip.STP_ROOT_ELECTION_REASONS == stp_topology.STP_ROOT_ELECTION_REASONS
    assert uip.DOSSIER_INPUT_STATES == ssot.ABSTENTION_STATES
    assert uip.DOSSIER_EMPTY_IS_CLEAN == analyze.DOSSIER_EMPTY_IS_CLEAN
    assert uip.DOSSIER_AXES == tuple(analyze.DOSSIER_AXIS_INPUTS)
    assert uip.AMBIGUOUS_STP_SENTINEL == analyze.VLAN_CUTOVER_AMBIGUOUS
    assert uip.MOVE_GROUP_UNSCHEDULED == analyze.MOVE_GROUP_UNSCHEDULED
    assert uip.STP_DEFAULT_BRIDGE_PRIORITY == stp_topology._DEFAULT_BRIDGE_PRIORITY
    defs = uip.ui_projection_schema()["$defs"]
    assert set(defs["StpRootIdentity"]["required"]) == {
        "root_address", "root_priority", "root_priorities", "claimants", "observers"}
    assert defs["StpRootIdentity"]["additionalProperties"] is False
    assert "input_state" in defs["ExposureValue"]["required"]
    assert set(STP_FIELDS) <= set(defs["VlanRow"]["required"])


def test_g15_schema_and_runtime_reject_poisoned_identity_priorities():
    for bad in (True, 1.0, "32778", 2 ** 53, -(2 ** 53), float("nan")):
        snap = _vlan_snapshot({"a": {"10": _root()}})
        identity = snap["vlan_cutover"][0]["stp_root_identities"][0]
        identity.update(root_priority=bad, root_priorities=[bad])
        assert _vlan(snap)["stp_root_identities"]["state"] == UV
        _validate(snap)
    doc = uip.project(_vlan_snapshot({"a": {"10": _root()}}))
    identity = doc["inventory"]["vlans"]["rows"]["items"][0]["stp_root_identities"]["value"][0]
    identity["extra"] = "not part of owner contract"
    assert list(Draft202012Validator(uip.ui_projection_schema()).iter_errors(doc))


@pytest.mark.parametrize("key", ["10", " 0010 ", "0", 10, -10, True, None, 1.0, [], {}, "-10", "١٠",
                                  "0" * 17, "9" * 50, 2 ** 53 - 1, 2 ** 53, -(2 ** 53)])
def test_g15_selection_key_eligibility_matches_actual_owner(key):
    owner = stp_topology._election_priority(key)
    assert uip._stp_vlan_key(key) == (owner if owner is not None and owner >= 0 else None)


def test_g15_serialized_map_key_collisions_withhold_selections():
    snap = _vlan_snapshot({"a": {10: _root(), "10": _root(claim=False)}})
    inventory = uip.project_inventory(snap)
    assert inventory["vlans"]["selection_sources"]["stp_roots"]["state"] == UV
    selected = inventory["vlans"]["rows"]["items"][0]["selections"]["stp_roots"]
    assert selected["state"] == UV and selected["items"] == []
    assert "collide" in selected["reason"]


@pytest.mark.parametrize("record", [_root(), None])
def test_g15_unique_integer_keys_and_negative_rows_preserve_serialized_pointer_identity(record):
    snap = _vlan_snapshot({"a": {10: record}})
    before = uip.project_inventory(snap)["vlans"]
    after = uip.project_inventory(json.loads(json.dumps(snap)))["vlans"]
    assert before == after
    assert before["selection_sources"]["stp_roots"]["state"] in (PUB, CBE)
    selected = before["rows"]["items"][0]["selections"]["stp_roots"]
    assert [r["pointer"] for r in selected["items"]] == ["/stp_roots/a/10"]
    assert selected["state"] == (PUB if isinstance(record, dict) else UV)
