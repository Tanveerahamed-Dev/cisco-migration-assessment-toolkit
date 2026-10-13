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

from cisco_toolkit import analyze, stp_topology, ui_projection as uip, vlan_carriage
from cisco_toolkit.protocol_assurance import bind_snapshot_json_bytes
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


def _round2_record(port, peer="", remote="", channel=""):
    """Exact complete pure synthetic interface record in owner refutation6113983469."""
    return dict(port=port, cdp_neighbor=peer, neighbor_port=remote, switchport_mode="Trunk",
                trunk_allowed_vlans="10", trunk_native_vlan="1", trunk_allowed_none="", port_channel=channel)


def _round2_observation(port="Po10", state="FWD", vid=10):
    role = "Altn" if state == "BLK" else "Desg"
    text = (f"VLAN{vid:04d}\n  Root ID Priority 32778\n"
            "          Address aaaa.0001.0001\n"
            "          This bridge is the root\n  Bridge ID Priority 32778\n"
            "          Address aaaa.0001.0001\n"
            "Interface Role Sts Cost Prio.Nbr Type\n"
            "---------------- ---- --- --------- -------- ----------------\n"
            f"{port} {role} {state} 4 128.1 P2p\n")
    return stp_topology.produce_stp_topology_observation(
        text, f"VLAN{vid:04d}\n  Number of topology changes 0 last change occurred 00:00:00 ago\n",
        state_capture_state="usable", detail_capture_state="usable")


def _round2_bundle(observations):
    ports = ("Gi1/0/1", "Gi1/0/2")
    interfaces = {host: {port: _round2_record(port, peer, port, "Po10") for port in ports}
                  for host, peer in (("switch-a", "switch-b"), ("switch-b", "switch-a"))}
    for host in interfaces:
        interfaces[host]["Po10"] = _round2_record("Po10")
    return dict(interfaces=interfaces, stp_topology_observations=observations, vlan_cutover=[dict(vlan=10)],
                cable_map=dict(cables=[dict(a="switch-a", a_port=ports[0], b="switch-b", b_port=ports[0],
                                           is_pc=True, members=[dict(a_port=port, b_port=port) for port in ports])]))


def _round2_compute(snap):
    return vlan_carriage.compute_vlan_carriage(snap["cable_map"], snap["interfaces"],
                                               snap["stp_topology_observations"], snap["vlan_cutover"])


def _round2_assert_held_without_recomputation(snap, monkeypatch):
    original = deepcopy(snap)
    assert vlan_carriage.validate_vlan_carriage(snap["vlan_carriage"]) == (True, "ok")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Reader reconstructed a replacement carriage relation")

    with monkeypatch.context() as changed:
        changed.setattr(vlan_carriage, "compute_vlan_carriage", forbidden)
        result = uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]
        assert result["summary"]["state"] == UV
        assert result["summary"]["forwarding"]["state"] == UV
        assert result["summary"]["forwarding"]["value"] is None
        assert result["page"]["items"][0]["relation"]["state"] == UV
        assert result["page"]["items"][0]["relation"]["value"] is None
        checked(snap)
    assert snap == original


@pytest.mark.parametrize("original", ["absent", "unrelated"])
@pytest.mark.parametrize("current", ["blocked", "forwarding", "error", "malformed", "mst", "null-host",
                                    "section-malformed", "section-subclass"])
def test_round2_configured_bundle_refuses_new_current_logical_stp_even_without_a_stored_pointer(
        monkeypatch, original, current):
    observations = {} if original == "absent" else {
        host: _round2_observation(vid=20) for host in ("switch-a", "switch-b")}
    snap = _round2_bundle(observations)
    snap["vlan_carriage"] = _round2_compute(snap)
    stored = deepcopy(snap["vlan_carriage"])
    assert all(member[side]["stp_pointer"] is None for member in stored["cables"][0]["members"]
               for side in ("a", "b")) is (original == "absent")
    before = uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]
    assert before["page"]["items"][0]["relation"]["value"] == "forwarding"
    if current in ("blocked", "forwarding"):
        # EXACT absent/unrelated -> currentPo10 DesgFWD / AltnBLK owner counterexample; bothFWD also makes
        # the configured BASIS stale even where the relation would coincidentally agree.
        snap["stp_topology_observations"] = {
            "switch-a": _round2_observation(),
            "switch-b": _round2_observation(state="BLK" if current == "blocked" else "FWD")}
        fresh = _round2_compute(snap)
        assert vlan_carriage.carriage_row_cables(fresh, 0)[0][1]["relation"] == (
            "stp_blocked" if current == "blocked" else "forwarding")
    elif current == "error":
        snap["stp_topology_observations"]["switch-b"] = stp_topology.produce_stp_topology_observation(
            "", "", state_capture_state="error", detail_capture_state="absent")
    elif current == "malformed":
        snap["stp_topology_observations"]["switch-b"] = {"schema": "stp_topology_observation/1"}
    elif current == "mst":
        snap["stp_topology_observations"]["switch-b"] = _observation(namespace="MST", port="Po10")
    elif current == "null-host":
        snap["stp_topology_observations"]["switch-b"] = None  # Supplied null is not an absent host.
    elif current == "section-malformed":
        snap["stp_topology_observations"] = []
    else:
        class ForeignSection(dict):
            pass

        snap["stp_topology_observations"] = ForeignSection(
            {host: _round2_observation(vid=20) for host in ("switch-a", "switch-b")})
    _round2_assert_held_without_recomputation(snap, monkeypatch)
    assert snap["vlan_carriage"] == stored
    pointers = {ref["pointer"] for ref in source(snap)["refs"]}
    assert any(pointer.endswith("/b/stp_pointer") for pointer in pointers)
    if current in ("blocked", "forwarding", "error", "malformed", "mst", "null-host", "section-subclass"):
        assert "/stp_topology_observations/switch-b" in pointers
    else:
        assert "/stp_topology_observations" in pointers


def test_round2_configured_exclusion_cannot_remain_published_over_a_new_logical_role(monkeypatch):
    snap = _round2_bundle({})
    for records in snap["interfaces"].values():
        records["Po10"]["trunk_allowed_vlans"] = ""
        records["Po10"]["trunk_allowed_none"] = "none"
    snap["vlan_carriage"] = _round2_compute(snap)
    assert uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]["page"]["items"][0]["relation"]["value"] == "not_carried"
    snap["stp_topology_observations"] = {
        host: _round2_observation(state="BLK") for host in ("switch-a", "switch-b")}
    _round2_assert_held_without_recomputation(snap, monkeypatch)


@pytest.mark.parametrize("original", ["absent", "unrelated"])
@pytest.mark.parametrize("current", ["absent", "unrelated", "physical-only", "explicit-no-subject"])
def test_round2_complete_configured_inputs_keep_only_current_logical_absence_eligibility(original, current):
    snap = _round2_bundle({} if original == "absent" else {
        host: _round2_observation(vid=20) for host in ("switch-a", "switch-b")})
    snap["vlan_carriage"] = _round2_compute(snap)
    if current == "absent":
        snap["stp_topology_observations"] = {}
    elif current == "unrelated":
        snap["stp_topology_observations"] = {
            host: _round2_observation(vid=20) for host in ("switch-a", "switch-b")}
    elif current == "physical-only":
        # A physical member alone is not the logicalPo10 row. Preserve the OWNER's configured fallback.
        snap["stp_topology_observations"] = {
            host: _round2_observation(port="Gi1/0/1") for host in ("switch-a", "switch-b")}
    else:
        snap["stp_topology_observations"] = {
            host: stp_topology.produce_stp_topology_observation(
                "No spanning tree instance exists", "No spanning tree instance exists",
                state_capture_state="usable", detail_capture_state="usable")
            for host in ("switch-a", "switch-b")}
    result = uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]
    # A non-null STORED declaration still must resolve; removing that formerly cited source remains held.
    if original == "unrelated" and current == "absent":
        assert result["summary"]["state"] == UV and result["page"]["items"][0]["relation"]["value"] is None
    else:
        assert result["summary"]["state"] == PUB and result["summary"]["forwarding"]["value"] == 1
        assert result["page"]["items"][0]["relation"]["value"] == "forwarding"
        cable = result["page"]["items"][0]
        assert cable["basis"]["value"] == "member_consensus"
        assert len(cable["members"]["items"]) == 2
        for member in cable["members"]["items"]:
            assert member["basis"]["value"] == "stored_trunk_allowance"
            for side in ("a", "b"):
                assert member[side]["basis"]["value"] == "stored_trunk_allowance"
    checked(snap)


@pytest.mark.parametrize("port", ["Po99", " Po10 "])
def test_round2_logical_allowance_source_port_identity_gap_holds_the_stored_bundle(monkeypatch, port):
    snap = _round2_bundle({host: _round2_observation() for host in ("switch-a", "switch-b")})
    snap["vlan_carriage"] = _round2_compute(snap)
    stored = deepcopy(snap["vlan_carriage"])
    assert uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]["page"]["items"][0]["relation"]["value"] == "forwarding"
    snap["interfaces"]["switch-b"]["Po10"]["port"] = port  # EXACTPo10→Po99 source counterexample.
    _round2_assert_held_without_recomputation(snap, monkeypatch)
    assert any(ref["pointer"].endswith("/b/allowance_pointer") for ref in source(snap)["refs"])
    assert snap["vlan_carriage"] == stored


@pytest.mark.parametrize("port", ["Po10", "Port-channel10", "Po010", ""])
def test_round2_complete_logical_source_keeps_its_owned_canonical_and_sparse_identity_rules(port):
    snap = _round2_bundle({host: _round2_observation() for host in ("switch-a", "switch-b")})
    snap["vlan_carriage"] = _round2_compute(snap)
    snap["interfaces"]["switch-b"]["Po10"]["port"] = port
    result = uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]
    assert result["summary"]["state"] == PUB and result["summary"]["forwarding"]["value"] == 1
    assert result["page"]["items"][0]["relation"]["value"] == "forwarding"
    checked(snap)


@pytest.mark.parametrize("basis", ["typed", "configured"])
@pytest.mark.parametrize("host", ["switch-a", "switch-b"])
@pytest.mark.parametrize("alias", ["Po010", "Port-channel10"])
def test_round2_current_logical_alias_collision_holds_each_retained_basis_and_end(monkeypatch, basis, host, alias):
    observations = {name: _round2_observation() for name in ("switch-a", "switch-b")} if basis == "typed" else {}
    snap = _round2_bundle(observations)
    snap["vlan_carriage"] = _round2_compute(snap)
    stored = deepcopy(snap["vlan_carriage"])
    assert uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]["page"]["items"][0]["relation"]["value"] == "forwarding"
    # A distinct, complete current record with the SAME public logical-channel identity; the old cited source
    # stays readable and self-consistent, so its port/pointer checks ALONE cannot establish uniqueness.
    snap["interfaces"][host][alias] = _round2_record(alias)
    _round2_assert_held_without_recomputation(snap, monkeypatch)
    side = "a" if host == "switch-a" else "b"
    assert any(ref["pointer"].endswith(f"/{side}/allowance_pointer") for ref in source(snap)["refs"])
    assert snap["vlan_carriage"] == stored


@pytest.mark.parametrize("basis", ["typed", "configured"])
@pytest.mark.parametrize("host", ["switch-a", "switch-b"])
@pytest.mark.parametrize("alias", ["Po010", "Port-channel10"])
@pytest.mark.parametrize("port", ["canonical", "blank"])
def test_round2_one_logical_key_alias_with_its_own_valid_source_is_not_a_collision(basis, host, alias, port):
    observations = {name: _round2_observation() for name in ("switch-a", "switch-b")} if basis == "typed" else {}
    snap = _round2_bundle(observations)
    record = snap["interfaces"][host].pop("Po10")
    record["port"] = alias if port == "canonical" else ""
    snap["interfaces"][host][alias] = record
    # Produce AFTER the declared single-key alias: the stored witness names that exact current key.
    snap["vlan_carriage"] = _round2_compute(snap)
    result = uip.project_vlan_carriage(snap, 0, 0, 200)["carriage"]
    assert result["summary"]["state"] == PUB and result["summary"]["forwarding"]["value"] == 1
    assert result["page"]["items"][0]["relation"]["value"] == "forwarding"
    checked(snap)


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


def _prepared_bound(snap):
    return bind_snapshot_json_bytes(json.dumps(snap, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _prepared_materialized(bound):
    """Consume the ingest stream for these small hosted fixtures, retaining only compressed variants."""
    prepared = uip.prepare_carriage_projection(bound)
    rowsets = []
    for rowset in prepared["rows"]:
        rowsets.append({**rowset, "variants": list(rowset["variants"])})
    prepared["rows"] = rowsets
    return prepared


def _prepared_window(prepared, vi, offset, limit):
    """Independent in-memory stand-in for the storage reader's bounded materialized row selection."""
    vlan = deepcopy(prepared["vlans"][vi])
    rows = []
    member_count = 0
    if vlan["readable"]:
        for rowset in prepared["rows"][offset:offset + limit]:
            meta = {key: rowset[key] for key in ("ordinal", "index", "member_count")}
            if member_count + rowset["member_count"] > 400:
                rows.append(meta)
                break
            variant = next(row for row in rowset["variants"] if row["vlan_index"] == vi)
            rows.append({**meta, "dictionary": rowset["dictionary"],
                         "bytes": variant["bytes"], "payload": variant["payload"]})
            member_count += rowset["member_count"]
    return deepcopy(prepared["context"]), vlan, rows


@pytest.mark.parametrize("case", ["configured", "typed", "blocked", "stale-stp", "channel-identity",
                                  "logical-alias", "alias-collision", "escaped-host", "invalid-contract",
                                  "missing-section", "failed-source", "missing-end-basis"])
def test_ingest_prepared_page_keeps_original_admission_summary_and_every_member_witness(case):
    observations = ({host: _round2_observation(state="BLK" if case == "blocked" and host == "switch-b" else "FWD")
                     for host in ("switch-a", "switch-b")} if case in ("typed", "blocked") else {})
    snap = _round2_bundle(observations)
    if case == "logical-alias":
        for records in snap["interfaces"].values():
            record = records.pop("Po10")
            record["port"] = "Port-channel010"
            records["Port-channel010"] = record
    elif case == "escaped-host":
        snap["interfaces"]["switch~/a"] = snap["interfaces"].pop("switch-a")
        for record in snap["interfaces"]["switch-b"].values():
            if record["cdp_neighbor"] == "switch-a":
                record["cdp_neighbor"] = "switch~/a"
        snap["cable_map"]["cables"][0]["a"] = "switch~/a"
    snap["vlan_carriage"] = _round2_compute(snap)
    if case == "stale-stp":
        snap["stp_topology_observations"] = {"switch-a": _round2_observation(),
                                             "switch-b": _round2_observation(state="BLK")}
    elif case == "channel-identity":
        snap["interfaces"]["switch-b"]["Po10"]["port"] = "Po99"
    elif case == "alias-collision":
        snap["interfaces"]["switch-b"]["Port-channel010"] = deepcopy(snap["interfaces"]["switch-b"]["Po10"])
    elif case == "invalid-contract":
        snap["vlan_carriage"]["rows"][0]["codes"] += "~"
    elif case == "missing-section":
        del snap["vlan_carriage"]
    elif case == "failed-source":
        snap["assessment_integrity"] = {"failed_phases": ["VLAN cutover matrix"]}
    elif case == "missing-end-basis":
        del snap["interfaces"]["switch-b"]["Po10"]
    bound = _prepared_bound(snap)
    expected = uip.project_vlan_carriage(bound, 0, 0, 200)
    prepared = _prepared_materialized(bound)
    actual = uip.project_prepared_vlan_carriage(*_prepared_window(prepared, 0, 0, 200), 0, 200)
    assert actual == expected
    assert actual["carriage"]["summary"] == (
        prepared["document"]["inventory"]["vlans"]["rows"]["items"][0]["selections"]["carriage"])
    schema = uip.ui_projection_schema()
    Draft202012Validator({"$ref": "#/$defs/CarriageDocument", "$defs": schema["$defs"]}).validate(actual)
    assert prepared["schema"] == "carriage_projection_preparation/2"
    header = {key: value for key, value in prepared.items() if key != "rows"}
    assert json.loads(json.dumps(header, allow_nan=False)) == header
    assert all(type(rowset["dictionary"]) is bytes for rowset in prepared["rows"])
    assert dict(bound) == snap
    if case in ("stale-stp", "channel-identity", "alias-collision", "missing-end-basis"):
        assert actual["carriage"]["summary"]["state"] == UV
        assert actual["carriage"]["page"]["items"][0]["relation"]["value"] is None


def test_prepared_page_never_rebinds_reads_admits_or_recounts_the_raw_snapshot(tmp_path, monkeypatch):
    bound = _prepared_bound(snapshot(tmp_path, interfaces=trunks(tmp_path, 3),
                                     vlans=[{"vlan": 10}, {"vlan": 20}]))
    prepared = _prepared_materialized(bound)
    expected = uip.project_vlan_carriage(bound, 1, 1, 1)
    fragment = _prepared_window(prepared, 1, 1, 1)
    assert len(fragment[2]) == 1 and fragment[2][0]["ordinal"] == 1
    assert "codes" not in fragment[1] and "roles" not in prepared
    assert type(fragment[2][0]["payload"]) is bytes
    before = deepcopy(fragment)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("request performed snapshot admission instead of reading prepared fragments")

    for name in ("_get", "_carriage_source", "_carriage_gaps", "carriage_row_counts", "_engine",
                 "bound_snapshot_source", "carriage_observation_admission", "carriage_role_index", "carriage_role_rows",
                 "carriage_row_cables", "_carriage_page_item", "decode_carriage_end", "project"):
        monkeypatch.setattr(uip, name, forbidden)
    actual = uip.project_prepared_vlan_carriage(*fragment, 1, 1)
    assert actual == expected and fragment == before
    actual["engine"].clear()
    actual["vocab"].clear()
    actual["carriage"]["summary"].clear()
    actual["carriage"]["page"]["items"][0]["ends"]["value"].clear()
    assert fragment == before


def test_preparation_rejects_detached_or_changed_binding_and_keeps_gap_refs_bounded(tmp_path):
    bounded_refs, original_sizes = [], []
    for cable_count in (12, 24):
        snap = snapshot(tmp_path, interfaces=trunks(tmp_path, cable_count))
        for record in snap["interfaces"][A].values():
            record["trunk_allowed_vlans"] = "20"
        with pytest.raises(ValueError, match="BoundSnapshot"):
            uip.prepare_carriage_projection(snap)
        bound = _prepared_bound(snap)
        expected = uip.project(bound)
        prepared = _prepared_materialized(bound)
        old_source = expected["inventory"]["vlans"]["selection_sources"]["carriage"]
        new_source = prepared["document"]["inventory"]["vlans"]["selection_sources"]["carriage"]
        assert old_source["state"] == new_source["state"] == UV
        assert len(old_source["refs"]) > len(new_source["refs"])
        assert len(new_source["refs"]) <= 8
        assert all("/members/" not in ref["pointer"] and "/cables/" not in ref["pointer"]
                   for ref in new_source["refs"])
        assert all(_resolves(bound, ref["pointer"]) for ref in new_source["refs"])
        bounded_refs.append(deepcopy(new_source["refs"]))
        original_sizes.append(len(old_source["refs"]))
        old_source["refs"] = new_source["refs"]
        assert expected == prepared["document"]
        bound["interfaces"][A][PORT]["trunk_allowed_vlans"] = "30"
        with pytest.raises(ValueError, match="BoundSnapshot"):
            uip.prepare_carriage_projection(bound)
    assert original_sizes[1] > original_sizes[0]
    assert bounded_refs[0] == bounded_refs[1]


def test_prepared_lazy_offsets_and_transport_byte_prefix_match_the_original(tmp_path):
    bound = _prepared_bound(snapshot(tmp_path, interfaces=trunks(tmp_path, 3)))
    prepared = _prepared_materialized(bound)
    one = uip.project_vlan_carriage(bound, 0, 0, 1)
    one_bytes = len(json.dumps(one, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    overhead = uip.CARRIAGE_PAGE_BYTE_LIMIT - one_bytes - 100
    for offset, limit, transport in ((0, 200, overhead), (1, 1, 0), (2, 200, 0), (3, 200, 0)):
        original = uip.project_vlan_carriage(bound, 0, offset, limit, transport_overhead=transport)
        actual = uip.project_prepared_vlan_carriage(*_prepared_window(prepared, 0, offset, limit), offset, limit,
                                                   transport_overhead=transport)
        assert actual == original
        assert len(json.dumps(actual, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + transport <= (
            uip.CARRIAGE_PAGE_BYTE_LIMIT)
        if transport:
            assert actual["carriage"]["page"]["returned"] == 1


@pytest.mark.parametrize("member_count", [400, 401])
def test_prepared_lazy_member_boundary_is_a_whole_cable_and_never_loads_oversized_members(member_count):
    snap = _round2_bundle({})
    ports = [f"Gi1/0/{i + 1}" for i in range(member_count)]
    for host, peer in (("switch-a", "switch-b"), ("switch-b", "switch-a")):
        snap["interfaces"][host] = {port: _round2_record(port, peer, port, "Po10") for port in ports}
        snap["interfaces"][host]["Po10"] = _round2_record("Po10")
    cable = snap["cable_map"]["cables"][0]
    cable["members"] = [{"a_port": port, "b_port": port} for port in ports]
    snap["vlan_carriage"] = _round2_compute(snap)
    bound = _prepared_bound(snap)
    expected = uip.project_vlan_carriage(bound, 0, 0, 200)
    prepared = _prepared_materialized(bound)
    fragment = _prepared_window(prepared, 0, 0, 200)
    actual = uip.project_prepared_vlan_carriage(*fragment, 0, 200)
    assert actual == expected
    if member_count == 400:
        assert actual["carriage"]["page"]["returned"] == 1
        assert len(actual["carriage"]["page"]["items"][0]["members"]["items"]) == 400
    else:
        assert set(fragment[2][0]) == {"ordinal", "index", "member_count"}
        assert "codes" not in fragment[1] and "roles" not in prepared
        assert actual["carriage"]["page"]["state"] == UV
        assert actual["carriage"]["page"]["returned"] == 0
        assert actual["carriage"]["page"]["has_more"] is True


def test_materialized_rows_stream_one_cable_and_variant_at_a_time_and_refuse_late_source_mutation(monkeypatch):
    snap = _round2_bundle({})
    snap["vlan_cutover"] = [{"vlan": 10}, {"vlan": 20}, {"vlan": 30}]
    snap["vlan_carriage"] = _round2_compute(snap)
    bound = _prepared_bound(snap)
    render = uip._carriage_page_item
    rendered = []

    def observed(ctx, admission, vi, cable, *args):
        rendered.append((vi, cable["index"]))
        return render(ctx, admission, vi, cable, *args)

    monkeypatch.setattr(uip, "_carriage_page_item", observed)
    prepared = uip.prepare_carriage_projection(bound)
    assert rendered == []  # No Cartesian DTO tree accompanies the prepared document.
    rowset = next(prepared["rows"])
    assert rendered == [(0, 0)]
    assert type(rowset["dictionary"]) is bytes and len(rowset["dictionary"]) <= 32_768
    first = next(rowset["variants"])
    assert rendered == [(0, 0)]  # The dictionary's row is reused, never rendered a second time.
    assert first["vlan_index"] == 0 and type(first["payload"]) is bytes
    assert [row["vlan_index"] for row in rowset["variants"]] == [1, 2]
    assert rendered == [(0, 0), (1, 0), (2, 0)]
    bound["changed_after_materialization"] = True
    with pytest.raises(ValueError, match="changed its BoundSnapshot"):
        next(prepared["rows"])


@pytest.mark.parametrize("damage", ["truncated", "trailing", "second-stream", "wrong-dictionary", "short-count",
                                    "long-count", "no-payload", "non-object"])
def test_materialized_rows_refuse_nonexact_compressed_streams_and_expansion_counts(damage):
    import zlib
    snap = _round2_bundle({})
    snap["vlan_carriage"] = _round2_compute(snap)
    prepared = _prepared_materialized(_prepared_bound(snap))
    row = _prepared_window(prepared, 0, 0, 1)[2][0]
    original = uip._decode_materialized_carriage_row(row)
    assert original["index"] == 0
    if damage == "truncated":
        row["payload"] = row["payload"][:-1]
    elif damage == "trailing":
        row["payload"] += b"unconsumed"
    elif damage == "second-stream":
        row["payload"] += row["payload"]
    elif damage == "wrong-dictionary":
        row["dictionary"] = b"another dictionary"
    elif damage == "short-count":
        row["bytes"] -= 1
    elif damage == "long-count":
        row["bytes"] += 1
    elif damage == "no-payload":
        del row["payload"]
    else:
        row.update(payload=zlib.compress(b"[]"), dictionary=b"", bytes=2)
    with pytest.raises(ValueError, match="materialized carriage row"):
        uip._decode_materialized_carriage_row(row)


def test_materialized_decoder_refuses_buffer_objects_before_touching_their_protocol(monkeypatch):
    released = memoryview(b"released")
    released.release()
    strided = memoryview(b"noncontiguous")[::2]
    mutable = bytearray(b"mutable")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("non-bytes payload reached a binary decoder")

    monkeypatch.setattr(uip.zlib, "decompressobj", forbidden)
    for value in (released, strided, mutable, type("ForeignBytes", (bytes,), {})(b"foreign")):
        with pytest.raises(ValueError, match="invalid binary metadata"):
            uip._decode_materialized_carriage_row({"payload": value, "dictionary": b"", "bytes": 1})
        with pytest.raises(ValueError, match="invalid binary metadata"):
            uip._decode_materialized_carriage_row({"payload": b"unused", "dictionary": value, "bytes": 1})


def test_materialized_oversized_cable_has_exact_bytes_but_no_retained_payload():
    item = {"synthetic": "x" * uip.CARRIAGE_PAGE_BYTE_LIMIT}
    raw, length = uip._materialized_carriage_bytes(item)
    assert raw is None
    assert length == len(json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    assert length > uip.CARRIAGE_PAGE_BYTE_LIMIT


def test_materialized_size_is_the_original_complete_utf8_json_encoding():
    item = {"escaped": '"\\\n\u0000', "unicode": "雪\U0001f600", "values": [None, True, False, -0.0, 2**100]}
    expected = json.dumps(item, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    raw, length = uip._materialized_carriage_bytes(item)
    assert raw == expected and length == len(expected)
    with pytest.raises(ValueError):
        uip._materialized_carriage_bytes({"invalid": float("nan")})


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


def _routing_outputs(snap, *, admission=None):
    """Full public outputs from one real checked admission, including complete and sliced lazy pages."""
    admission = uip.carriage_admission(snap) if admission is None else admission
    document = uip.project(snap, carriage=admission)
    pages = [uip.project_vlan_carriage(snap, vi, offset, limit, admission=admission)
             for vi in range(len(snap["vlan_cutover"])) for offset, limit in ((0, 200), (0, 1), (1, 1))]
    return dict(admission.gaps), document, pages


@pytest.mark.parametrize("damage", ["none", "static-peer", "allowance", "late-role", "bundle-beside"])
def test_optional_routing_preserves_full_documents_pages_and_gap_order(tmp_path, monkeypatch, damage):
    if damage == "bundle-beside":
        interfaces = _bundle(tmp_path, b_groups=((1, ("Gi1/0/1", "Gi1/0/2")),), allowed=(None, None))
        observations = {host: _stp({10: [("Po1", "Desg", "FWD")], 20: [("Po1", "Altn", "BLK")]})
                        for host in (A, B)}
    else:
        interfaces = None
        observations = {host: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]})
                        for host in (A, B)}
    snap = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}], interfaces=interfaces)
    if damage == "static-peer":
        snap["interfaces"][A][PORT]["cdp_neighbor"] = "unjoined-peer"
        snap["interfaces"][A][PORT]["neighbor_port"] = "Gi1/0/99"
    elif damage == "allowance":
        snap["interfaces"][B][PORT]["trunk_allowed_none"] = "none"
        snap["interfaces"][B][PORT]["trunk_native_vlan"] = "20"
    elif damage == "late-role":
        snap["stp_topology_observations"][B] = _stp(
            {10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]})
    elif damage == "bundle-beside":
        snap["stp_topology_observations"][B] = _stp(
            {10: [("Po1", "Desg", "FWD")], 20: [("Po1", "Altn", "BLK"), ("Gi1/0/2", "Desg", "FWD")]})
    before = deepcopy(snap)
    planned = _routing_outputs(snap)
    with monkeypatch.context() as patch:
        patch.setattr(uip, "_carriage_routing_plan", lambda: None)
        original_dispatch = _routing_outputs(snap)
    assert planned == original_dispatch  # Real original dispatch and owners, not a copied routing algorithm.
    assert snap == before
    assert bool(planned[0]) is (damage != "none")


@pytest.mark.parametrize("declared", [False, True])
def test_configured_only_routing_checks_current_logical_absence_only_for_a_present_observation(
        tmp_path, monkeypatch, declared):
    observations = {A: _observation(vid=99), B: _observation(vid=99)} if declared else None
    snap = snapshot(tmp_path, observations=observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    original, calls = uip.carriage_observation_admission, []
    original_index, original_rows, queries = uip.carriage_role_index, uip.carriage_role_rows, []

    def observed(record):
        assert declared, "Absent configured-only STP gained an observation owner call"
        calls.append(record)
        return original(record)

    def index(record):
        assert declared, "Absent configured-only STP gained a role index"
        return original_index(record)

    def rows(record, interface, vid, *, index=None):
        assert declared, "Absent configured-only STP gained a role query"
        queries.append((record, interface, vid))
        return original_rows(record, interface, vid, index=index)

    monkeypatch.setattr(uip, "carriage_observation_admission", observed)
    monkeypatch.setattr(uip, "carriage_role_index", index)
    monkeypatch.setattr(uip, "carriage_role_rows", rows)
    planned = _routing_outputs(snap)
    assert bool(calls) is declared  # Declared STP still receives its ORIGINAL static admission.
    assert {(interface, vid) for _record, interface, vid in queries} == ({(PORT, 10), (PORT, 20)} if declared else set())
    assert all(record is observations[A] or record is observations[B] for record, _interface, _vid in queries)
    calls.clear()
    queries.clear()
    with monkeypatch.context() as patch:
        patch.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == planned
    assert bool(calls) is declared
    assert {(interface, vid) for _record, interface, vid in queries} == ({(PORT, 10), (PORT, 20)} if declared else set())
    assert planned[1]["inventory"]["vlans"]["rows"]["items"][0]["selections"]["carriage"]["forwarding"]["value"] == 1


@pytest.mark.parametrize("field,value", [("host", B), ("stp_interface", "Gi1/0/2"), ("port", "Gi1/0/2"),
                                         ("host-subclass", None), ("hold", "missing_interface")])
def test_a_callback_between_typed_rows_keeps_current_end_routing_and_original_flag_behavior(
        tmp_path, monkeypatch, field, value):
    observations = {
        A: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD"), ("Gi1/0/2", "Altn", "BLK")]}),
        B: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]}),
    }
    seed = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    original, results = uip.carriage_role_rows, []

    class ForeignHost(str):
        def __hash__(self):
            # Same textual value, a different owner lookup. Loose equality must not bless a plain-host plan.
            return hash(A) ^ 1

    for enabled in (False, True):
        snap, changed = deepcopy(seed), []
        end = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]

        def mutate(record, interface, vid, *, index=None):
            rows = original(record, interface, vid, index=index)
            if not changed and record is snap["stp_topology_observations"][A] and vid == 10:
                # Deliberate callback mutation after the first original logical join.
                end["host" if field == "host-subclass" else field] = ForeignHost(A) if field == "host-subclass" else value
                changed.append(True)
            return rows

        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            patch.setattr(uip, "carriage_role_rows", mutate)
            results.append(_routing_outputs(snap))
        assert changed == [True]
    assert results[0] == results[1]
    # Original static holds are not reinterpreted mid-call. Routing changes, however, must affect the later VLAN.
    assert (1 in results[1][0]) is (field != "hold")


@pytest.mark.parametrize("shape", ["foreign-index", "foreign-list", "list-pair", "copied-row", "owner-error"])
def test_optional_routing_keeps_real_owner_foreign_shapes_and_error_fallback(tmp_path, monkeypatch, shape):
    observations = {host: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]}) for host in (A, B)}
    seed = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    original_index, original_rows, results = uip.carriage_role_index, uip.carriage_role_rows, []
    failures, calls = [], []

    class ForeignIndex(dict):
        pass

    class ForeignRows(list):
        pass

    def observed_index(record):
        index = original_index(record)  # The real owner reads this current producer record BEFORE fault injection.
        calls.append(record)
        if shape == "owner-error":
            raise RuntimeError("declared real owner callback refusal")
        return ForeignIndex(index)

    def observed_rows(record, interface, vid, *, index=None):
        rows = original_rows(record, interface, vid, index=index)
        if shape == "foreign-list":
            return ForeignRows(rows)
        if shape == "list-pair":
            return [[i, row] for i, row in rows]
        return [(i, dict(row)) for i, row in rows]

    for enabled in (False, True):
        snap = deepcopy(seed)
        calls.clear()
        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            if shape in ("foreign-index", "owner-error"):
                patch.setattr(uip, "carriage_role_index", observed_index)
            else:
                patch.setattr(uip, "carriage_role_rows", observed_rows)
            if shape == "owner-error":
                # RuntimeError is deliberately OUTSIDE the unchanged _OWNER_FAULTS. Both the original
                # dispatch and optional plan must propagate it, not invent a held result or repair/retry.
                with pytest.raises(RuntimeError) as raised:
                    _routing_outputs(snap)
                failures.append((type(raised.value), raised.value.args))
                first_host = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]["host"]
                assert len(calls) == 1 and calls[0] is snap["stp_topology_observations"][first_host]
            else:
                results.append(_routing_outputs(snap))
    if shape == "owner-error":
        assert failures == [(RuntimeError, ("declared real owner callback refusal",))] * 2
    else:
        assert results[0] == results[1] and not results[1][0]


def test_declared_owner_typeerror_holds_the_whole_admission_before_separate_lazy_rendering(tmp_path, monkeypatch):
    observations = {host: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]}) for host in (A, B)}
    seed = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    original, results = uip.carriage_role_index, []
    assert TypeError in uip._OWNER_FAULTS and RuntimeError not in uip._OWNER_FAULTS
    for enabled in (False, True):
        snap, calls = deepcopy(seed), []

        def refused(record):
            original(record)  # Genuine current owner domain, not an invented index or a malformed fixture.
            calls.append(record)
            raise TypeError("declared guarded owner refusal")

        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            patch.setattr(uip, "carriage_role_index", refused)
            admission = uip.carriage_admission(snap)
            first_host = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]["host"]
            assert len(calls) == 1 and calls[0] is snap["stp_topology_observations"][first_host]
            assert admission.source["state"] == UV and list(admission.gaps) == [0, 1]
            assert dict(admission.observations) == {}  # No partial checked index/observation is retained.
        # Rendering is a SEPARATE owner call domain. Restore the real callback before lazy role witnesses;
        # no renderer catch is assumed or added, and the original admission's holds must remain in its output.
        result = _routing_outputs(snap, admission=admission)
        rows = result[1]["inventory"]["vlans"]["rows"]["items"]
        assert all(row["selections"]["carriage"]["state"] == UV for row in rows)
        assert all(row["selections"]["carriage"]["forwarding"]["value"] is None for row in rows)
        for page_result in result[2]:
            assert all(item["relation"]["value"] is None for item in page_result["carriage"]["page"]["items"])
        results.append(result)
    assert results[0] == results[1]


def _empty_query_snapshot():
    snap = _round2_bundle({host: _round2_observation(vid=99) for host in ("switch-a", "switch-b")})
    snap["vlan_cutover"] = [{"vlan": vid} for vid in (10, 20, 30)]
    snap["vlan_carriage"] = _round2_compute(snap)
    return snap


@pytest.mark.parametrize("damage", ["none", "forwarding", "blocked", "error", "logical-alias", "key-order",
                                    "physical-beside"])
def test_empty_query_reuse_preserves_real_full_outputs_and_current_counterexamples(monkeypatch, damage):
    snap = _empty_query_snapshot()
    if damage == "physical-beside":
        snap["stp_topology_observations"] = {
            host: _round2_observation() for host in ("switch-a", "switch-b")}
        snap["vlan_carriage"] = _round2_compute(snap)
        snap["stp_topology_observations"]["switch-b"] = _stp(
            {10: [("Po10", "Desg", "FWD"), ("Gi1/0/1", "Altn", "BLK")]})
    elif damage in ("forwarding", "blocked"):
        snap["stp_topology_observations"]["switch-b"] = _round2_observation(
            state="FWD" if damage == "forwarding" else "BLK")
    elif damage == "error":
        snap["stp_topology_observations"]["switch-b"] = stp_topology.produce_stp_topology_observation(
            "", "", state_capture_state="error", detail_capture_state="error")
    elif damage == "logical-alias":
        snap["interfaces"]["switch-b"]["Po010"] = _round2_record("Po010")
    elif damage == "key-order":
        snap["stp_topology_observations"]["switch-b"] = dict(reversed(tuple(
            snap["stp_topology_observations"]["switch-b"].items())))
    before = deepcopy(snap)
    planned = _routing_outputs(snap)
    with monkeypatch.context() as original:
        original.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == planned
    assert snap == before
    assert bool(planned[0]) is (damage not in ("none", "key-order"))
    checked(snap)


@pytest.mark.parametrize("cap", [0, 1, 16_384])
def test_empty_query_optional_retention_zero_and_saturation_keep_original_admission(monkeypatch, cap):
    snap = _empty_query_snapshot()
    dispatch, calls = uip._carriage_role_query, []

    def observed(record, interface, vid, *, index):
        answer = dispatch(record, interface, vid, index=index)
        assert type(answer) is list and not answer  # Real public owner supplies unrelated-VLAN absence.
        calls.append((record, interface, vid))
        return answer

    monkeypatch.setattr(uip, "_carriage_role_query", observed)
    monkeypatch.setattr(uip, "_CARRIAGE_SHARED_EMPTY_LIMIT", cap)
    planned = _routing_outputs(snap)
    planned_calls = list(calls)
    calls.clear()
    with monkeypatch.context() as original:
        original.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == planned
    assert len(calls) == 6 and {vid for _record, _interface, vid in calls} == {10, 20, 30}
    assert all(any(record is snap["stp_topology_observations"][host] for host in ("switch-a", "switch-b"))
               for record, _interface, _vid in calls)
    assert all(any(record is snap["stp_topology_observations"][host] for record, _interface, _vid in calls)
               for host in ("switch-a", "switch-b"))
    if cap in (0, 1):
        assert planned_calls == calls  # After the first seed saturates cap1, every next query is ORIGINAL.
    else:
        assert len(planned_calls) < len(calls)
    checked(snap)


@pytest.mark.parametrize("shape", ["ordinary-empty", "foreign-empty", "foreign-index", "record-copy"])
def test_empty_owner_foreign_shapes_and_wrapped_side_effects_stay_per_host(monkeypatch, shape):
    snap = _empty_query_snapshot()
    query, index_owner, admission_owner = (uip.carriage_role_rows, uip.carriage_role_index,
                                           uip.carriage_observation_admission)
    dispatch, calls = uip._carriage_role_query, []

    class ForeignRows(list):
        pass

    class ForeignIndex(dict):
        pass

    def wrapped(record, interface, vid, *, index=None):
        answer = query(record, interface, vid, index=index)
        assert not answer
        return ForeignRows(answer) if shape == "foreign-empty" else answer

    def observed(record, interface, vid, *, index):
        answer = dispatch(record, interface, vid, index=index)
        calls.append((record, interface, vid))
        return answer

    def copied_admission(record):
        state, reason, admitted = admission_owner(record)
        return state, reason, deepcopy(admitted) if admitted is not None else None

    monkeypatch.setattr(uip, "_carriage_role_query", observed)
    if shape == "foreign-index":
        monkeypatch.setattr(uip, "carriage_role_index", lambda record: ForeignIndex(index_owner(record)))
    elif shape == "record-copy":
        monkeypatch.setattr(uip, "carriage_observation_admission", copied_admission)
    else:
        monkeypatch.setattr(uip, "carriage_role_rows", wrapped)
    planned = _routing_outputs(snap)
    assert len(calls) == 6
    calls.clear()
    with monkeypatch.context() as original:
        original.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == planned
    assert len(calls) == 6 and not planned[0]


def test_empty_query_index_callback_keeps_the_current_host_and_original_record_domain(monkeypatch):
    seed, results, domains = _empty_query_snapshot(), [], []
    owner_index, dispatch = uip.carriage_role_index, uip._carriage_role_query
    for enabled in (False, True):
        snap, changed, calls = deepcopy(seed), [], []
        end = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]
        first_host, next_host = end["host"], snap["vlan_carriage"]["cables"][0]["members"][0]["b"]["host"]

        def index_callback(record):
            index = owner_index(record)
            if not changed:
                assert record is snap["stp_topology_observations"][first_host]
                end["host"] = next_host
                changed.append(True)
            return index

        def observed(record, interface, vid, *, index):
            answer = dispatch(record, interface, vid, index=index)
            calls.append(("first" if record is snap["stp_topology_observations"][first_host] else "next",
                          interface, vid))
            return answer

        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            patch.setattr(uip, "carriage_role_index", index_callback)
            patch.setattr(uip, "_carriage_role_query", observed)
            results.append(_routing_outputs(snap))
        assert changed == [True] and calls[0][0] == "first"
        domains.append(calls)
    assert results[0] == results[1] and domains[0][0] == domains[1][0]
    assert all(call in domains[0] for call in domains[1])  # Later coherent pure queries may safely reuse absence.


@pytest.mark.parametrize("switch", ["during-return", "after-seed"])
def test_current_owner_binding_is_rechecked_after_empty_return_and_before_later_hits(monkeypatch, switch):
    snap = _empty_query_snapshot()
    expected = _routing_outputs(snap)
    dispatch, public_owner = uip._carriage_role_query, uip.carriage_role_rows
    original_calls, replacement_calls, changed = [], [], []

    def replacement(record, interface, vid, *, index=None):
        answer = public_owner(record, interface, vid, index=index)
        replacement_calls.append(record)
        return answer

    def replace():
        if not changed:
            monkeypatch.setattr(uip, "carriage_role_rows", replacement)
            changed.append(True)

    def observed(record, interface, vid, *, index):
        answer = dispatch(record, interface, vid, index=index)
        original_calls.append(record)
        if switch == "during-return":
            replace()  # Before seed: the actual query returned, then its public binding changed.
        return answer

    class SwitchPlan(uip._CarriageRoutingPlan):
        def __getattribute__(self, name):
            if name == "host" and original_calls and switch == "after-seed":
                replace()  # The next position's original host read occurs AFTER the first seed.
            return super().__getattribute__(name)

    monkeypatch.setattr(uip, "_carriage_role_query", observed)
    monkeypatch.setattr(uip, "_carriage_routing_plan", SwitchPlan)
    assert _routing_outputs(snap) == expected
    assert changed == [True] and replacement_calls
    assert any(record is snap["stp_topology_observations"]["switch-b"] for record in replacement_calls)


def test_empty_query_next_admission_reads_the_new_current_role_instead_of_prior_absence(monkeypatch):
    snap = _empty_query_snapshot()
    first = _routing_outputs(snap)
    assert not first[0]
    snap["stp_topology_observations"]["switch-b"] = _round2_observation(state="FWD")
    changed = _routing_outputs(snap)
    with monkeypatch.context() as original:
        original.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == changed
    assert 0 in changed[0]
    relation = changed[2][0]["carriage"]["page"]["items"][0]["relation"]
    assert relation["state"] == UV and relation["value"] is None


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
def test_empty_query_owner_errors_keep_original_propagation_and_guard_scoped_holds(monkeypatch, error_type):
    seed, results = _empty_query_snapshot(), []
    owner = uip.carriage_role_rows
    for enabled in (False, True):
        snap, calls = deepcopy(seed), []

        def refused(record, interface, vid, *, index=None):
            assert not owner(record, interface, vid, index=index)  # Genuine public query before fault injection.
            calls.append(record)
            raise error_type("declared current empty-query refusal")

        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            patch.setattr(uip, "carriage_role_rows", refused)
            if error_type is RuntimeError:
                with pytest.raises(RuntimeError) as raised:
                    uip.carriage_admission(snap)
                results.append((type(raised.value), raised.value.args))
            else:
                admission = uip.carriage_admission(snap)
                assert admission.source["state"] == UV and list(admission.gaps) == [0, 1, 2]
                assert not admission.observations
        assert len(calls) == 1 and calls[0] is snap["stp_topology_observations"]["switch-a"]
        if error_type is TypeError:
            # Separate lazy rendering is an unguarded owner domain: restore its owner before using held admission.
            result = _routing_outputs(snap, admission=admission)
            assert all(item["relation"]["value"] is None
                       for output in result[2] for item in output["carriage"]["page"]["items"])
            results.append(result)
    assert results[0] == results[1]
    if error_type is RuntimeError:
        assert results == [(RuntimeError, ("declared current empty-query refusal",))] * 2


@pytest.mark.parametrize("owner", ["admission", "index"])
def test_routing_changed_inside_an_original_owner_callback_is_not_read_again_in_a_different_order(
        tmp_path, monkeypatch, owner):
    observations = {
        A: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]}),
        B: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]}),
    }
    seed = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    name = "carriage_observation_admission" if owner == "admission" else "carriage_role_index"
    original, results = getattr(uip, name), []
    for enabled in (False, True):
        snap, changed = deepcopy(seed), []
        end = snap["vlan_carriage"]["cables"][0]["members"][0]["a"]

        def mutate(record):
            result = original(record)
            if not changed and record is snap["stp_topology_observations"][A]:
                end["host"] = B  # Original callback point, before the caller's NEXT host read.
                changed.append(True)
            return result

        with monkeypatch.context() as patch:
            if not enabled:
                patch.setattr(uip, "_carriage_routing_plan", lambda: None)
            patch.setattr(uip, name, mutate)
            results.append(_routing_outputs(snap))
        assert changed == [True]
    assert results[0] == results[1] and 1 in results[1][0]


def test_routing_answers_do_not_survive_a_fresh_admission_after_current_source_mutation(tmp_path, monkeypatch):
    observations = {host: _stp({10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Desg", "FWD")]}) for host in (A, B)}
    snap = snapshot(tmp_path, ("", ""), observations, vlans=[{"vlan": 10}, {"vlan": 20}])
    assert _routing_outputs(snap)[0] == {}
    snap["stp_topology_observations"][B] = _stp(
        {10: [(PORT, "Desg", "FWD")], 20: [(PORT, "Altn", "BLK")]})
    planned = _routing_outputs(snap)
    assert list(planned[0]) == [1]
    with monkeypatch.context() as patch:
        patch.setattr(uip, "_carriage_routing_plan", lambda: None)
        assert _routing_outputs(snap) == planned


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
