"""Engine-owned topology and route-model presentation: independent source/ref and FIB parity checks."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import fib, ui_projection as ui


@pytest.fixture
def snap():
    return {
        "schema": "collect_parse_snapshot/1",
        "devices": {"a/b~c.d": {}, "peer": {}},
        # an svi_ip comes only from the scoped interface running-config capture, which build.py marks
        # run_config_observed; without the mark the failure-impact row's measures are withheld
        "interfaces": {"a/b~c.d": {"Vlan1": {"svi_ip": "10.0.0.1/24", "ip_mtu": 1500, "run_config_observed": True}},
                       "peer": {"Gi1": {}}},
        "routes": {"a/b~c.d": [
            {"prefix": "10.0.0.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan1"},
            {"prefix": "192.0.2.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan1"},
            {"prefix": "10.0.0.1/32", "source": "local", "next_hop": "", "out_intf": "Vlan1"}], "peer": []},
        "cable_map": {
            "nodes": [{"host": "a/b~c.d", "kind": "device", "role": "Core", "collected": True, "op_status": "up"},
                      {"host": "offscan", "kind": "ap", "role": "", "collected": False, "op_status": "unknown"}],
            "cables": [{"a": "a/b~c.d", "a_port": "Gi1", "b": "offscan", "b_port": "Gi0", "is_pc": False,
                        "members": [{"a_port": "Gi1", "b_port": "Gi0"}], "speed": "1000",
                        "confirmation": "One end (a/b~c.d)", "op_status": "up"}],
            "summary": {"n_nodes": 2, "n_cables": 1}},
        "link_centrality": [{"a_host": "a/b~c.d", "a_port": "Gi1", "b_host": "offscan", "b_port": "Gi0",
                             "betweenness": 321.5, "is_bridge": True, "pairs_cut": 3, "rank": 1}],
        "failure_impact": [{"host": "a/b~c.d", "severity": "Info", "vlans_impacted": 0, "stranded": 0,
                            "hard": 0, "backup": 0, "fhrp": 0, "off_scan_gw_vlans": 0,
                            "detail": "No reachability impact from removing this switch (within the scan)."}],
    }


@pytest.fixture(scope="module")
def schema():
    value = ui.ui_projection_schema()
    Draft202012Validator.check_schema(value)
    return value


def validate(value, definition, schema):
    Draft202012Validator({"$ref": "#/$defs/" + definition, "$defs": schema["$defs"]}).validate(value)


def resolve(snap, pointer):
    current = snap
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def refs_resolve(snap, value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "pointer":
                resolve(snap, child)
            refs_resolve(snap, child)
    elif isinstance(value, list):
        for child in value:
            refs_resolve(snap, child)


def test_topology_preserves_source_semantics_and_refs(snap, schema):
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    refs_resolve(snap, value)
    assert value["summary"]["nodes"]["value"] == 2
    nodes = value["nodes"]["items"]
    assert nodes[1]["style"]["value"]["token"] == "uncollected"
    assert nodes[1]["style"]["value"]["glyph"] == "ap"
    assert nodes[1]["role"]["state"] == "not_collected"
    assert "op_status" not in nodes[0]
    cable = value["cables"]["items"][0]
    assert cable["ends"]["value"] == {k: snap["cable_map"]["cables"][0][k] for k in ("a", "a_port", "b", "b_port", "is_pc")}
    assert cable["a_nodes"]["items"] == [{"index": 0, "pointer": "/cable_map/nodes/0"}]
    assert cable["b_nodes"]["items"] == [{"index": 1, "pointer": "/cable_map/nodes/1"}]
    structural = value["structural_links"]["items"][0]
    assert structural["betweenness"]["value"] == 321.5  # deliberately not a percentage/ScoreFact
    assert structural["host_pair_cable_refs"]["items"] == [{"index": 0, "pointer": "/cable_map/cables/0"}]
    impact = value["failure_impact"]["items"][0]
    assert impact["stranded"]["value"] == 0
    assert impact["detail"]["value"] == snap["failure_impact"][0]["detail"]
    assert impact["style"]["value"]["token"] == "impact_info"


@pytest.mark.parametrize("section", ["cable_map", "link_centrality", "failure_impact"])
@pytest.mark.parametrize("mode", ["absent", "null", "malformed", "failed"])
def test_absence_and_failed_stored_sections_never_recompute(snap, schema, section, mode, monkeypatch):
    from cisco_toolkit import analyze
    def forbidden(*args, **kwargs):
        raise AssertionError("stored projection must not recompute analysis")
    monkeypatch.setattr(analyze, "compute_cable_map", forbidden)
    if mode == "absent":
        del snap[section]
    elif mode == "null":
        snap[section] = None
    elif mode == "malformed":
        snap[section] = 7
    else:
        snap["assessment_integrity"] = {section: "failed"}
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    key = {"cable_map": "nodes", "link_centrality": "structural_links", "failure_impact": "failure_impact"}[section]
    expected = "analysis_unavailable" if mode == "failed" else "unverified" if mode == "malformed" else "not_collected"
    assert value[key]["state"] == expected
    refs_resolve(snap, value)


def test_ambiguity_exact_hosts_and_contradictory_census(snap, schema):
    snap["cable_map"]["nodes"].extend([copy.deepcopy(snap["cable_map"]["nodes"][0]),
                                        {"host": "A/B~C.D", "collected": True, "kind": "device", "role": "Core"}])
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    joined = value["cables"]["items"][0]["a_nodes"]
    assert joined["state"] == "unverified"
    assert [r["index"] for r in joined["items"]] == [0, 2]
    assert value["summary"]["nodes"]["state"] == "unverified"
    assert value["cables"]["items"][0]["style"]["value"]["token"] == "unverified"
    snap["cable_map"]["cables"][0]["a"] = " a/b~c.d "
    assert ui.project_topology(snap)["cables"]["items"][0]["a_nodes"]["state"] == "not_collected"


@pytest.mark.parametrize("field", ["nodes", "cables"])
@pytest.mark.parametrize("kind", ["missing", "null", "malformed"])
def test_summary_distinguishes_missing_from_malformed_source_list(snap, schema, field, kind):
    snap["cable_map"]["summary"]["n_" + field] = 0
    if kind == "missing":
        del snap["cable_map"][field]
    else:
        snap["cable_map"][field] = None if kind == "null" else 7
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    fact = value["summary"][field]
    assert fact["state"] == ("unverified" if kind == "malformed" else "not_collected")
    assert fact["value"] is None
    if kind != "missing":
        assert {"pointer": "/cable_map/" + field, "role": "witness"} in fact["refs"]
    refs_resolve(snap, value)


@pytest.mark.parametrize("source", [[], 123, True, {}, None, "", "\x00", "\ud800"])
def test_unusable_route_source_cannot_publish_empty_address_observations(schema, source):
    snap = {"interfaces": {}, "routes": {"r": [{"source": source, "prefix": "192.0.2.1/32"}]}}
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    addresses = value["source_addresses"]
    assert addresses["state"] == "unverified"
    assert addresses["items"] == []
    assert {"pointer": "/routes/r/0/source", "role": "witness"} in addresses["refs"]
    refs_resolve(snap, value)


def test_absent_route_source_is_disclosed_but_valid_nonconnected_source_is_excluded(schema):
    snap = {"interfaces": {}, "routes": {"r": [{"prefix": "192.0.2.1/32"}]}}
    missing = ui.project_topology(snap)["source_addresses"]
    assert missing["state"] == "unverified"
    assert {"pointer": "/routes/r/0", "role": "witness"} in missing["refs"]
    snap["routes"]["r"][0]["source"] = "static"
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    assert value["source_addresses"]["state"] == "collected_but_empty"
    assert value["source_addresses"]["items"] == []


def test_address_observations_are_positive_and_distinct(snap, schema):
    iface = snap["interfaces"]["a/b~c.d"]["Vlan1"]
    iface["svi_ips"] = "10.0.0.1/24;2001:db8::1/64"
    snap["routes"]["a/b~c.d"] += [
        {"prefix": "10.0.0.254/32", "source": "hsrp", "next_hop": "10.0.0.254", "out_intf": "Vlan1"},
        {"prefix": "10.0.0.253/32", "source": "hsrp", "next_hop": "10.0.0.252", "out_intf": "Vlan1"}]
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    rows = value["source_addresses"]["items"]
    assert len(rows) == 5  # distinct same-address observations retain separate provenance
    assert {r["address"]["value"] for r in rows} == {"10.0.0.1", "10.0.0.254", "2001:db8::1"}
    assert [r["index"] for r in rows] == list(range(5))
    assert any(r["family"]["value"] == 6 for r in rows)
    refs_resolve(snap, value)
    assert all(r["address"]["subject"] is None for r in rows)


@pytest.mark.parametrize("failed", [False, True])
def test_address_blind_spot_cites_the_actual_collection_record(snap, schema, failed):
    snap["collection_completeness"] = {"devices": [{"host": "A/B~C.D", "status": "not collected"}]}
    if failed:
        snap["assessment_integrity"] = {"interfaces": "failed", "routes": "failed"}
    topology = ui.project_topology(snap)
    validate(topology, "Topology", schema)
    if failed:
        assert topology["source_addresses"]["state"] == "analysis_unavailable"
    observations = topology["source_addresses"]["items"]
    assert observations
    for row in observations:
        assert row["address"]["state"] == "not_collected"
        assert {"pointer": "/collection_completeness/devices/0", "role": "witness"} in row["address"]["refs"]
    refs_resolve(snap, topology)


@pytest.mark.parametrize("src,dst,status", [
    ("10.0.0.2", "192.0.2.1", "computed:reached"),
    ("bad", "192.0.2.1", "lower_bound:bad_address"),
    ("10.0.0.2", "2001:db8::1", "lower_bound:cross_family"),
    ("198.51.100.1", "192.0.2.1", "lower_bound:src_host_not_found"),
])
def test_path_exact_owner_result_and_query(snap, schema, src, dst, status):
    value = ui.project_path(snap, src, dst)
    validate(value, "PathDocument", schema)
    path = value["path"]
    expected = fib.trace_fib_path(snap, src, dst, max_hops=32, required_mtu=None, disclose=True)
    assert path["result"]["state"] == "published"
    assert path["result"]["value"] == expected
    assert len(expected) == 14
    assert expected["status"] == status
    assert path["query"] == {"src_ip": src, "dst_ip": dst, "max_hops": 32, "required_mtu": None, "disclose": True}
    refs_resolve(snap, value)
    if expected["hops"]:
        evidence = path["hop_evidence"]["items"][0]
        assert evidence["route_rows"]["state"] == "published"
        assert evidence["route_rows"]["items"] == [{"index": 1, "pointer": "/routes/a~1b~0c.d/1"}]
        assert evidence["interfaces"]["items"] == [{"pointer": "/interfaces/a~1b~0c.d/Vlan1", "role": "witness"}]


@pytest.mark.parametrize("case", ["discard", "absence", "ecmp", "malformed", "ambiguous"])
def test_path_disclosures_remain_distinct(snap, schema, case):
    routes = snap["routes"]["a/b~c.d"]
    if case in ("discard", "absence"):
        routes[1].update(source="static", out_intf="Null0")
        if case == "absence":
            routes[1]["prefix"] = "198.51.100.0/24"
    elif case == "ecmp":
        routes.append({"prefix": "192.0.2.0/24", "source": "static", "admin_distance": 0,
                       "next_hop": "", "out_intf": "Null0"})
    elif case == "malformed":
        routes[1]["next_hop"] = {"hostile": True}
    else:
        snap["routes"]["peer"] = copy.deepcopy(routes)
    path = ui.project_path(snap, "10.0.0.2", "192.0.2.5")["path"]
    validate(path, "Path", schema)
    assert path["result"]["value"] == fib.trace_fib_path(snap, "10.0.0.2", "192.0.2.5", disclose=True)
    result = path["result"]["value"]
    if case in ("discard", "absence"):
        assert result["drop_evidence"] == ("observed_discard" if case == "discard" else "no_route_observed")
        assert path["style"]["value"]["token"] == "path_" + result["drop_evidence"]
    elif case == "ecmp":
        assert result["reached"] and result["ecmp_dropping_legs"]
        assert path["style"]["value"]["token"] == "path_partial_drop"
    elif case == "malformed":
        assert result["hops"][0]["invalid_route_fields"] == ["next_hop"]
        assert path["hop_evidence"]["items"][0]["route_rows"]["state"] == "unverified"
    else:
        assert result["ambiguous_candidate_sets"]


def test_duplicate_routes_are_unverified_evidence_not_arbitrary_pick(snap, schema):
    snap["routes"]["a/b~c.d"].append(copy.deepcopy(snap["routes"]["a/b~c.d"][1]))
    path = ui.project_path(snap, "10.0.0.2", "192.0.2.1")["path"]
    validate(path, "Path", schema)
    evidence = path["hop_evidence"]["items"][0]["route_rows"]
    assert evidence["state"] == "unverified"
    assert [r["index"] for r in evidence["items"]] == [1, 3]


@pytest.mark.parametrize("mode,state", [("missing", "not_collected"), ("empty", "collected_but_empty"),
                                        ("bad", "unverified"), ("failed", "analysis_unavailable")])
def test_path_refuses_before_owner_when_basis_unavailable(snap, schema, mode, state, monkeypatch):
    if mode == "missing":
        del snap["routes"]
    elif mode == "empty":
        snap["routes"] = {}
    elif mode == "bad":
        snap["routes"] = []
    else:
        snap["assessment_integrity"] = {"routes": "failed"}
    def forbidden(*args, **kwargs):
        raise AssertionError("must refuse before FIB")
    monkeypatch.setattr(fib, "trace_fib_path", forbidden)
    value = ui.project_path(snap, "10.0.0.2", "192.0.2.5")
    validate(value, "PathDocument", schema)
    assert value["path"]["result"]["state"] == state
    refs_resolve(snap, value)


def test_owner_fault_malformed_output_and_mutable_aliases(snap, schema, monkeypatch):
    before = copy.deepcopy(snap)
    topology = ui.project_topology(snap)
    topology["cables"]["items"][0]["ends"]["value"]["a"] = "tampered"
    assert snap == before
    owner = fib.trace_fib_path(snap, "10.0.0.2", "192.0.2.1", disclose=True)
    monkeypatch.setattr(fib, "trace_fib_path", lambda *a, **k: owner)
    result = ui.project_path(snap, "10.0.0.2", "192.0.2.1")
    result["path"]["result"]["value"]["hops"][0]["host"] = "tampered"
    assert owner["hops"][0]["host"] == "a/b~c.d"
    owner["unexpected"] = True
    assert ui.project_path(snap, "a", "b")["path"]["result"]["state"] == "unverified"
    def fault(*args, **kwargs):
        raise ValueError("owner fault")
    monkeypatch.setattr(fib, "trace_fib_path", fault)
    value = ui.project_path(snap, "a", "b")
    validate(value, "PathDocument", schema)
    assert value["path"]["result"]["state"] == "unverified"


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), float("inf"), {}, "1", 2 ** 60])
def test_topology_numeric_slots_refuse_bad_values(snap, schema, bad):
    snap["link_centrality"][0]["betweenness"] = bad
    snap["link_centrality"][0]["rank"] = bad
    snap["failure_impact"][0]["stranded"] = bad
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    assert value["structural_links"]["items"][0]["betweenness"]["state"] == "unverified"
    assert value["structural_links"]["items"][0]["rank"]["state"] == "unverified"
    assert value["failure_impact"]["items"][0]["stranded"]["state"] == "unverified"
    json.dumps(value, allow_nan=False)


def test_malformed_rows_retained_and_address_partiality_disclosed(snap, schema):
    snap["cable_map"]["nodes"].append("bad row")
    snap["cable_map"]["cables"].append(None)
    snap["link_centrality"].append([])
    snap["interfaces"]["a/b~c.d"]["Vlan1"]["svi_ips"] = ["bad address", "2001:db8::1/64"]
    value = ui.project_topology(snap)
    validate(value, "Topology", schema)
    assert value["nodes"]["items"][-1]["index"] == 2
    assert value["nodes"]["items"][-1]["host"]["state"] == "unverified"
    assert value["cables"]["items"][-1]["ends"]["state"] == "unverified"
    assert value["structural_links"]["items"][-1]["ends"]["state"] == "unverified"
    assert value["source_addresses"]["state"] == "unverified"
    assert any(r["address"]["value"] == "2001:db8::1" for r in value["source_addresses"]["items"])
    refs_resolve(snap, value)


def test_path_ipv6_and_missing_mtu_preserve_owner(snap, schema):
    snap["routes"]["a/b~c.d"] = [
        {"prefix": "2001:db8:1::/64", "source": "connected", "next_hop": "", "out_intf": "Vlan1"},
        {"prefix": "2001:db8:2::/64", "source": "connected", "next_hop": "", "out_intf": "missing"}]
    value = ui.project_path(snap, "2001:db8:1::2", "2001:db8:2::2")
    validate(value, "PathDocument", schema)
    result = value["path"]["result"]["value"]
    assert result == fib.trace_fib_path(snap, "2001:db8:1::2", "2001:db8:2::2", disclose=True)
    assert result["reached"] and result["mtu_min"] is None
    assert result["mtu_unobserved_hops"]
    assert value["path"]["hop_evidence"]["items"][0]["interfaces"]["state"] == "not_collected"
    assert "path_route_model_only" in value["path"]["result"]["caveats"]


def test_new_projections_are_offline_and_schema_outputs_detached(snap, schema, monkeypatch):
    import builtins
    import socket
    import subprocess
    expected = ui.project_path(snap, "10.0.0.2", "192.0.2.1")
    def no_io(*a, **kw):
        raise AssertionError("projection attempted I/O")
    with monkeypatch.context() as m:
        for owner, attr in ((builtins, "open"), (socket, "socket"), (socket, "create_connection"), (subprocess, "Popen")):
            m.setattr(owner, attr, no_io)
        assert ui.project_path(snap, "10.0.0.2", "192.0.2.1") == expected
        ui.project_topology(snap)
    fresh = ui.ui_projection_schema()
    fresh["$defs"]["Path"]["required"].append("hostile")
    assert "hostile" not in ui.ui_projection_schema()["$defs"]["Path"]["required"]
    validate(expected, "PathDocument", schema)


def test_unavailable_style_follows_the_ssot_owner_at_module_binding(monkeypatch):
    import runpy
    from cisco_toolkit import ssot

    # A fresh module binding follows the owner, rather than retaining a copied receipt-like literal.
    sentinel = "synthetic_owner_unavailable"
    with monkeypatch.context() as changed:
        changed.setattr(ssot, "ANALYSIS_UNAVAILABLE", sentinel)
        rebound = runpy.run_path(ui.__file__)
        assert sentinel in rebound["TOPOLOGY_STYLE_TOKENS"]
        assert "analysis_unavailable" not in rebound["TOPOLOGY_STYLE_TOKENS"]
        entry = next(row for row in rebound["_topology_legend"]()["entries"] if row["token"] == sentinel)
        assert (entry["tone"], entry["stroke"]) == ("warning", "dashed")
        style = rebound["_topology_style"]([{"state": sentinel, "refs": []}], "observed")
        assert style["value"]["token"] == sentinel


def test_failure_impact_preserves_full_counts_and_disclosed_eight_example_detail(schema):
    from dataclasses import asdict
    import re
    from cisco_toolkit import analyze
    from cisco_toolkit.model import InterfaceData

    def trunk(peer):
        return InterfaceData(port="Gi1", status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                             neighbor_port="Gi1", endpoint_type="Switch", trunk_allowed_vlans="10-19",
                             stp_fwd_vlans="10-19")
    interfaces = {"gateway": {"Gi1": trunk("access")}, "access": {"Gi1": trunk("gateway")}}
    for vid in range(10, 20):
        # the scoped interface running-config capture is the only source of svi_ip, and build.py marks what it parsed
        interfaces["gateway"][f"Vlan{vid}"] = InterfaceData(port=f"Vlan{vid}", svi_ip=f"10.{vid}.0.1/24",
                                                             run_config_observed=True)
        interfaces["access"][f"Gi{vid}"] = InterfaceData(port=f"Gi{vid}", status="connected",
            switchport_mode="Access", vlan=str(vid), end_host_mac=f"0000.0000.{vid:04x}")
    impact = analyze.compute_failure_impact(interfaces)
    source = next(row for row in impact if row["host"] == "gateway")
    assert source["vlans_impacted"] == source["stranded"] == source["hard"] == 10
    assert len(re.findall(r"\bVLAN \d+:", source["detail"])) == 8
    assert source["detail"].endswith("... +2 more")
    snapshot = {"failure_impact": impact, "cable_map": analyze.compute_cable_map(interfaces), "routes": {},
                "interfaces": {host: {port: asdict(row) for port, row in ports.items()}
                               for host, ports in interfaces.items()}}
    topology = ui.project_topology(snapshot)
    validate(topology, "Topology", schema)
    projected = next(row for row in topology["failure_impact"]["items"] if row["host"]["value"] == "gateway")
    for field in ("vlans_impacted", "stranded", "hard", "detail"):
        assert projected[field]["state"] == "published"
        assert projected[field]["value"] == source[field]
    assert "impact_scanned_scope" in projected["detail"]["caveats"]
    limitation = next(row for row in ui.LIMITATIONS if row["id"] == "impact_scanned_scope")
    assert "8 per-VLAN examples" in limitation["text"] and "+N more" in limitation["text"]
    refs_resolve(snapshot, topology)


def test_sample_whole_document_schema_and_new_source_parity(schema):
    sample = json.loads((Path(__file__).resolve().parents[1] / "webapp/sample_data/sample_fleet.snapshot.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(sample)
    document = ui.project(sample)
    Draft202012Validator(schema).validate(document)
    assert sample == before
    topology = document["topology"]
    for key, source in (("nodes", sample["cable_map"]["nodes"]), ("cables", sample["cable_map"]["cables"]),
                        ("structural_links", sample["link_centrality"]), ("failure_impact", sample["failure_impact"])):
        assert len(topology[key]["items"]) == len(source)
        for i, row in enumerate(topology[key]["items"]):
            assert resolve(sample, row["pointer"]) == source[i]
    refs_resolve(sample, topology)
    assert ui.project_topology(sample) == topology
    json.dumps(document, allow_nan=False)
