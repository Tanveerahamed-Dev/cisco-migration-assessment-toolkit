"""Routing-neighbour peer resolution (contract gap G17): the collected device a neighbour's address belongs to.

Each routing-neighbour row on a device page carries ``peer_host``, a TextFact read from the ONE address index the
fleet topology publishes as ``topology.source_addresses`` (``fib._connected_index``'s exact owners: configured
interface addresses and local/FHRP host routes, never a connected subnet). The projection builds no second index and
never guesses from a subnet:

* exactly one collected device carries the address -> published, citing every observation of it, and every collected
  device whose interface addresses were never captured (it could be a second owner);
* two or more devices, or only this device itself -> unverified, every observation a witness;
* no collected device carries it -> ``collected_but_empty`` ("not resolved") ONLY over a readable, complete IPv4 index:
  every input collected and every collected device's interface addresses captured. Otherwise the absence is
  ``not_collected``, never "not resolved"; an IPv6 address is always ``not_collected`` (the index holds IPv4
  interface addresses only).

Every value is checked against an INDEPENDENT lookup in the snapshot or the engine's own exact-owner function, never
the module's own join. No test here is run locally: the hosted gates run them.
"""
from __future__ import annotations

import ast
import copy
import inspect
import ipaddress
import json
import pathlib
import textwrap
import types

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import build, fib, parse
from cisco_toolkit import ui_projection as ui

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
CAVEAT = "routing_peer_resolution_scope"
#: The neighbour row's cells, in the producer's field order (``build.build_routing_neighbors`` rows).
ROW_CELLS = ("neighbor", "state", "address", "interface", "as")
#: The stored sample's routing neighbours, resolved by hand from its interfaces and local routes: the collected
#: device each neighbour's ADDRESS is configured on, or None where no collected device carries it.
SAMPLE_PEERS = {
    ("core1", "ospf"): ["core2", None, "dist1"],      # 10.0.10.3, 10.0.40.9, 10.0.140.2 (never the router IDs)
    ("core1", "bgp"): [None],                         # 10.0.10.254: the uncollected upstream next hop
    ("dist1", "ospf"): ["core1", "dist2"],            # 10.0.140.1, 10.0.40.3
    ("dist2", "ospf"): ["dist1"],                     # 10.0.40.2
}


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def doc_validator():
    schema = ui.ui_projection_schema()
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/DeviceDocument"})


def _page(snap, host, validator):
    """One device document, schema-validated and JSON-native, returning its page."""
    doc = ui.project_device(snap, host)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    assert not errors, (host, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]])
    json.dumps(doc, allow_nan=False)
    return doc["device"]


def _rows(page, proto):
    groups = [g for g in page["routing_neighbors"]["items"] if g["protocol"] == proto]
    assert len(groups) == 1, (proto, [g["protocol"] for g in page["routing_neighbors"]["items"]])
    return groups[0]["neighbors"]["items"]


def _refs(fact, role=None):
    return {r["pointer"] for r in fact["refs"] if role is None or r["role"] == role}


def _resolve(doc, pointer):
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        cur = cur[int(tok)] if isinstance(cur, list) else cur[tok]
    return cur


def _observation_pointers(snap, address):
    """Independent: every stored record that positively places `address` on a device -- an interface's svi_ip /
    svi_ips text (an address with a dotted mask or a prefix length), a local host route, or an FHRP host route that
    names itself as next hop. A connected subnet that merely CONTAINS the address is not one."""
    want = ipaddress.ip_address(address)
    out = set()
    for host, ports in (snap.get("interfaces") or {}).items():
        for port, rec in ports.items():
            for key in ("svi_ip", "svi_ips"):
                raw = rec.get(key) if isinstance(rec, dict) else None
                values = list(enumerate(raw)) if isinstance(raw, list) else (
                    [(None, v) for v in raw.split(";")] if isinstance(raw, str) else [])
                for j, value in values:
                    text = value.strip() if isinstance(value, str) else ""
                    if text and ipaddress.ip_address(text.split()[0].split("/")[0]) == want:
                        toks = ("interfaces", host, port, key) + (() if j is None else (j,))
                        out.add(ui.json_pointer(*toks))
    for host, rows in (snap.get("routes") or {}).items():
        for j, row in enumerate(rows):
            net = ipaddress.ip_network(row["prefix"], strict=False)
            source = str(row.get("source", "")).lower()
            fhrp = any(k in source for k in ("hsrp", "vrrp", "glbp")) and row.get("next_hop") == address
            if net.prefixlen == net.max_prefixlen and net.network_address == want and (
                    source.startswith("local") or fhrp):
                out.add(ui.json_pointer("routes", host, j, "prefix"))
    return out


def _owners(pointers):
    """The devices those records belong to (the host token of each pointer)."""
    return {pointer.split("/")[2].replace("~1", "/").replace("~0", "~") for pointer in pointers}


def _engine_owners(snap, address):
    """The engine's own answer: fib._hosts_owning_ip over fib._connected_index, exact owners only."""
    index = fib._connected_index(snap.get("routes") or {}, snap.get("interfaces") or {})
    return fib._hosts_owning_ip(index, address, exact=True)


def _base():
    """Two collected routers on a /30, both with their scoped interface running-config captured; r1 sees r2 over
    OSPF and BGP, and an OSPF neighbour at an address no collected device carries."""
    return {
        "schema": "collect_parse_snapshot/1",
        "devices": {"r1": {"hostname": "r1"}, "r2": {"hostname": "r2"}},
        "interfaces": {
            "r1": {"Gi1": {"svi_ip": "192.0.2.1 255.255.255.252", "run_config_observed": True}},
            "r2": {"Gi1": {"svi_ip": "192.0.2.2/30", "run_config_observed": True}},
        },
        "routes": {"r1": [], "r2": []},
        "routing_neighbors": {"r1": {
            "ospf": [{"neighbor": "10.255.0.2", "state": "FULL/-", "address": "192.0.2.2", "interface": "Gi1"},
                     {"neighbor": "10.255.0.9", "state": "FULL/-", "address": "198.51.100.9", "interface": "Gi1"}],
            "eigrp": [],
            "bgp": [{"neighbor": "192.0.2.2", "as": "65001", "state": "12"}],
        }},
    }


def _peers(snap, validator, host="r1"):
    """``{protocol: [peer_host fact, ...]}`` of one device page."""
    page = _page(snap, host, validator)
    return {g["protocol"]: [row["peer_host"] for row in g["neighbors"]["items"]]
            for g in page["routing_neighbors"]["items"]}


# --------------------------------------------------------------------------------------------------
# the closed schema and the owner tables
# --------------------------------------------------------------------------------------------------
def test_schema_adds_peer_host_as_a_text_fact_and_the_scope_limitation():
    d = ui.ui_projection_schema()["$defs"]
    row = d["NeighborRow"]
    assert row["additionalProperties"] is False
    assert list(row["properties"]) == ["index", "pointer", *ROW_CELLS, "peer_host"]
    assert row["required"] == list(row["properties"])
    assert row["properties"]["peer_host"] == {"$ref": "#/$defs/TextFact"}
    lims = {lim["id"]: lim for lim in ui.DEVICE_LIMITATIONS}
    assert tuple(lims[CAVEAT]["applies_to"]) == ("/device/routing_neighbors",)
    assert CAVEAT in d["LimitationId"]["enum"]
    # a device-document limitation only: the fleet payload's own registry (and its transport copies) is unchanged
    assert CAVEAT not in {lim["id"] for lim in ui.LIMITATIONS}
    pages = d["DevicePage"]["properties"]["limitations"]
    assert pages["minItems"] == pages["maxItems"] == len(ui.DEVICE_LIMITATIONS) + len(ui.DEVICE_CITED_LIMITATIONS)


def test_address_fields_are_the_producers_protocol_keys_and_the_parsers_address_columns():
    assert isinstance(ui.NEIGHBOR_ADDRESS_FIELDS, types.MappingProxyType)
    assert set(ui.NEIGHBOR_ADDRESS_FIELDS.values()) <= set(ROW_CELLS)
    # the producer's own protocol keys, read from its source: one returned literal mapping
    tree = ast.parse(textwrap.dedent(inspect.getsource(build.build_routing_neighbors)))
    returned = [node.value for node in ast.walk(tree) if isinstance(node, ast.Return)]
    assert len(returned) == 1 and isinstance(returned[0], ast.Dict)
    assert {key.value for key in returned[0].keys} == set(ui.NEIGHBOR_ADDRESS_FIELDS)
    # OSPF: the Address column, never the Neighbor ID (a router ID that is no interface address)
    ospf = parse.parse_ospf_neighbors(
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        "10.0.99.2         1   FULL/DR         00:00:33    10.0.10.3       Vlan10\n")
    assert len(ospf) == 1 and ospf[0]["neighbor"] == "10.0.99.2"
    assert ospf[0][ui.NEIGHBOR_ADDRESS_FIELDS["ospf"]] == "10.0.10.3"
    # EIGRP: the peer is named by its address; the parser emits no separate address field
    eigrp = parse.parse_eigrp_neighbors(
        "EIGRP-IPv4 Neighbors for AS(100)\n"
        "H   Address                 Interface              Hold Uptime   SRTT   RTO  Q  Seq\n"
        "0   10.1.1.2                Gi0/1                    13 00:10:02    1   100  0  5\n")
    assert len(eigrp) == 1 and "address" not in eigrp[0]
    assert eigrp[0][ui.NEIGHBOR_ADDRESS_FIELDS["eigrp"]] == "10.1.1.2"
    # BGP: the Neighbor column is the peer address
    bgp = parse.parse_bgp_summary(
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "10.0.10.254     4        64500       0       0        1    0    0 never    Idle\n")
    assert len(bgp) == 1 and "address" not in bgp[0]
    assert bgp[0][ui.NEIGHBOR_ADDRESS_FIELDS["bgp"]] == "10.0.10.254"


# --------------------------------------------------------------------------------------------------
# the real stored sample: every neighbour resolved, against hand-resolved anchors and the engine's exact owners
# --------------------------------------------------------------------------------------------------
def test_sample_peer_hosts_are_the_engines_exact_owners(sample, doc_validator):
    assert set(sample["routing_neighbors"]) == {host for host, _proto in SAMPLE_PEERS}
    seen = 0
    for (host, proto), expected in SAMPLE_PEERS.items():
        page = _page(sample, host, doc_validator)
        rows = _rows(page, proto)
        stored = sample["routing_neighbors"][host][proto]
        assert len(rows) == len(stored) == len(expected), (host, proto)
        field = ui.NEIGHBOR_ADDRESS_FIELDS[proto]
        for i, (row, want) in enumerate(zip(rows, expected)):
            peer = row["peer_host"]
            address = stored[i][field]
            pointers = _observation_pointers(sample, address)
            # three independent answers agree: the hand-resolved anchor, this lookup and the engine's exact owner
            assert sorted(_owners(pointers)) == ([want] if want else []), (host, proto, i)
            assert _engine_owners(sample, address) == ([want] if want else []), (host, proto, i)
            subject = ui.json_pointer("routing_neighbors", host, proto, i, field)
            assert ("subject", subject) in {(r["role"], r["pointer"]) for r in peer["refs"]}
            assert {"/interfaces", "/routes"} <= _refs(peer, "basis")
            assert peer["basis"].endswith("routing_neighbors{}{}[]." + field)
            assert peer["caveats"] == [CAVEAT]
            if want is None:
                assert (peer["state"], peer["value"]) == (CBE, None), (host, proto, i, peer)
                assert peer["reason"].startswith("collected but empty: not resolved")
                assert _refs(peer, "witness") == set()
            else:
                assert (peer["state"], peer["value"]) == (PUB, want), (host, proto, i, peer)
                assert "reason" not in peer
                # every observation of the address is cited; the sample captured every device, so nothing else is
                assert _refs(peer, "witness") == pointers and pointers
            seen += 1
    assert seen == 7
    # the OSPF router ID is never what is resolved: core1's first neighbour ID is carried by no device at all
    assert _observation_pointers(sample, sample["routing_neighbors"]["core1"]["ospf"][0]["neighbor"]) == set()


def test_peer_host_agrees_with_the_published_topology_index(sample, doc_validator):
    """The one index: every published peer is the single owner topology.source_addresses lists for the address, and
    every 'not resolved' address appears nowhere in it."""
    index = ui.project_topology(sample)["source_addresses"]
    assert index["state"] == PUB
    listed = {}
    for item in index["items"]:
        assert item["address"]["state"] == PUB
        listed.setdefault(item["address"]["value"], set()).add(item["host"]["value"])
    checked = 0
    for host in sorted(sample["routing_neighbors"]):
        page = _page(sample, host, doc_validator)
        for group in page["routing_neighbors"]["items"]:
            field = ui.NEIGHBOR_ADDRESS_FIELDS[group["protocol"]]
            for row in group["neighbors"]["items"]:
                peer, address = row["peer_host"], row[field]["value"]
                if peer["state"] == PUB:
                    assert listed.get(address) == {peer["value"]}, (host, address)
                else:
                    assert peer["state"] == CBE and address not in listed, (host, address, peer)
                checked += 1
    assert checked == 7


def test_the_one_index_is_built_once_per_context_and_shared(sample, monkeypatch):
    calls = []
    real = ui._address_sources

    def counted(ctx):
        calls.append(ctx)
        return real(ctx)

    monkeypatch.setattr(ui, "_address_sources", counted)
    docs = ui.project_devices(sample, ["core1", "dist1", "dist2", "access1"])
    assert len(calls) == 1
    assert [_rows(doc["device"], "ospf")[0]["peer_host"]["value"] for doc in docs[:3]] == ["core2", "core1", "dist1"]
    calls.clear()
    ui.project_topology(sample)
    assert len(calls) == 1


# --------------------------------------------------------------------------------------------------
# synthetic, fully controlled: published, not resolved, and never a subnet guess
# --------------------------------------------------------------------------------------------------
def test_one_exact_owner_is_published_and_an_absent_address_is_not_resolved(doc_validator):
    snap = _base()
    peers = _peers(snap, doc_validator)
    assert sorted(peers) == ["bgp", "eigrp", "ospf"] and peers["eigrp"] == []
    owner, absent = peers["ospf"]
    assert (owner["state"], owner["value"], owner["subject"]) == (PUB, "r2", None)
    assert owner["refs"] == [
        {"pointer": "/routing_neighbors/r1/ospf/0/address", "role": "subject"},
        {"pointer": "/interfaces", "role": "basis"},
        {"pointer": "/routes", "role": "basis"},
        {"pointer": "/interfaces/r2/Gi1/svi_ip", "role": "witness"},
    ]
    assert owner["caveats"] == [CAVEAT]
    assert (absent["state"], absent["value"]) == (CBE, None)
    assert absent["reason"].startswith("collected but empty: not resolved")
    assert _refs(absent) == {"/routing_neighbors/r1/ospf/1/address", "/interfaces", "/routes"}
    assert absent["caveats"] == [CAVEAT]
    bgp = peers["bgp"][0]
    assert (bgp["state"], bgp["value"]) == (PUB, "r2")
    assert "/routing_neighbors/r1/bgp/0/neighbor" in _refs(bgp, "subject")
    assert _engine_owners(snap, "192.0.2.2") == ["r2"] and _engine_owners(snap, "198.51.100.9") == []


def test_a_connected_subnet_never_names_an_owner_but_local_and_fhrp_host_routes_do(doc_validator):
    snap = _base()
    snap["routing_neighbors"]["r1"]["ospf"][1]["address"] = "203.0.113.7"
    snap["routes"]["r2"] = [{"prefix": "203.0.113.0/24", "source": "connected", "next_hop": "", "out_intf": "Gi3"}]
    # the engine's subnet rule WOULD place the address behind r2; the exact-owner rule (the index's) does not
    index = fib._connected_index(snap["routes"], snap["interfaces"])
    assert fib._hosts_owning_ip(index, "203.0.113.7") == ["r2"]
    assert _engine_owners(snap, "203.0.113.7") == []
    absent = _peers(snap, doc_validator)["ospf"][1]
    assert (absent["state"], absent["value"]) == (CBE, None)
    snap["routes"]["r2"].append({"prefix": "203.0.113.7/32", "source": "local", "next_hop": "", "out_intf": "Gi3"})
    local = _peers(snap, doc_validator)["ospf"][1]
    assert (local["state"], local["value"]) == (PUB, "r2")
    assert _refs(local, "witness") == {"/routes/r2/1/prefix"}
    snap["routes"]["r2"] = [{"prefix": "203.0.113.7/32", "source": "hsrp", "next_hop": "203.0.113.7",
                             "out_intf": "Gi3"}]
    fhrp = _peers(snap, doc_validator)["ospf"][1]
    assert (fhrp["state"], fhrp["value"]) == (PUB, "r2")
    assert _refs(fhrp, "witness") == {"/routes/r2/0/prefix"}


# --------------------------------------------------------------------------------------------------
# ambiguity: two owners, or this device itself
# --------------------------------------------------------------------------------------------------
def test_two_owning_devices_are_unverified_with_every_observation_a_witness(doc_validator):
    snap = _base()
    snap["devices"]["r3"] = {"hostname": "r3"}
    snap["interfaces"]["r3"] = {"Gi2": {"svi_ip": "192.0.2.2 255.255.255.252", "run_config_observed": True}}
    assert _engine_owners(snap, "192.0.2.2") == ["r2", "r3"]
    peers = _peers(snap, doc_validator)
    for fact in (peers["ospf"][0], peers["bgp"][0]):
        assert (fact["state"], fact["value"]) == (UV, None)
        assert "2 collected devices" in fact["reason"] and "this device among them" not in fact["reason"]
        assert _refs(fact, "witness") == {"/interfaces/r2/Gi1/svi_ip", "/interfaces/r3/Gi2/svi_ip"}
        assert "caveats" not in fact
    # the other neighbour is untouched by the duplicate
    assert peers["ospf"][1]["state"] == CBE


def test_an_address_on_this_device_is_unverified_alone_or_with_another_owner(doc_validator):
    snap = _base()
    snap["routing_neighbors"]["r1"]["ospf"][0]["address"] = "192.0.2.1"        # r1's own address
    alone = _peers(snap, doc_validator)["ospf"][0]
    assert (alone["state"], alone["value"]) == (UV, None)
    assert "only on this device itself" in alone["reason"]
    assert _refs(alone, "witness") == {"/interfaces/r1/Gi1/svi_ip"}
    snap["interfaces"]["r2"]["Gi1"]["svi_ips"] = "192.0.2.2/30;192.0.2.1/30"
    shared = _peers(snap, doc_validator)["ospf"][0]
    assert (shared["state"], shared["value"]) == (UV, None)
    assert "2 collected devices (this device among them)" in shared["reason"]
    assert _refs(shared, "witness") == {"/interfaces/r1/Gi1/svi_ip", "/interfaces/r2/Gi1/svi_ips"}


# --------------------------------------------------------------------------------------------------
# coverage honesty: an absence over an incomplete index is never "not resolved"
# --------------------------------------------------------------------------------------------------
def test_a_device_whose_addresses_were_never_captured_makes_absence_not_collected(doc_validator):
    snap = _base()
    snap["interfaces"]["r2"] = {}                     # r2 was reached, but its interface running-config was not parsed
    peers = _peers(snap, doc_validator)
    for fact in (peers["ospf"][0], peers["ospf"][1], peers["bgp"][0]):
        assert (fact["state"], fact["value"]) == (NC, None), fact
        assert fact["reason"].startswith("not collected: 1 collected device record(s) have no interface addresses")
        assert "/interfaces/r2" in _refs(fact, "witness")
        assert "caveats" not in fact


def test_a_published_owner_cites_every_device_it_cannot_rule_out(doc_validator):
    for mutate, witness in (
            # r2's address survives but no interface of it carries the capture marker
            (lambda s: s["interfaces"]["r2"]["Gi1"].pop("run_config_observed"), "/interfaces/r2"),
            # an inventory device with no interface record at all
            (lambda s: s["devices"].update(r3={"hostname": "r3"}), "/devices/r3"),
            # an inventory device the collection never reached (a blind-spot row naming no collected device)
            (lambda s: s.update(collection_completeness={"devices": [
                {"host": "r9", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]}]}),
             "/collection_completeness/devices/0")):
        snap = _base()
        mutate(snap)
        peers = _peers(snap, doc_validator)
        owner, absent = peers["ospf"]
        assert (owner["state"], owner["value"]) == (PUB, "r2"), witness
        assert witness in _refs(owner, "witness") and "/interfaces/r2/Gi1/svi_ip" in _refs(owner, "witness")
        assert owner["caveats"] == [CAVEAT]
        assert (absent["state"], absent["value"]) == (NC, None), witness
        assert absent["reason"].startswith("not collected: 1 collected device record(s)"), absent["reason"]
        assert witness in _refs(absent, "witness")


def test_ipv6_is_never_resolved_and_never_cleared(doc_validator):
    snap = _base()
    snap["routing_neighbors"]["r1"]["bgp"][0]["neighbor"] = "2001:db8::2"
    absent = _peers(snap, doc_validator)["bgp"][0]
    assert (absent["state"], absent["value"]) == (NC, None)
    assert "IPv6" in absent["reason"] and "never observed" in absent["reason"]
    snap["interfaces"]["r2"]["Gi1"]["svi_ips"] = ["2001:db8::2/64"]
    assert _engine_owners(snap, "2001:db8::2") == ["r2"]
    owned = _peers(snap, doc_validator)["bgp"][0]
    assert (owned["state"], owned["value"]) == (NC, None)
    assert _refs(owned, "witness") == {"/interfaces/r2/Gi1/svi_ips/0"}
    snap["routing_neighbors"]["r1"]["bgp"][0]["neighbor"] = "2001:db8::2%Gi1"       # a zone id is the same address
    zoned = _peers(snap, doc_validator)["bgp"][0]
    assert (zoned["state"], _refs(zoned, "witness")) == (NC, {"/interfaces/r2/Gi1/svi_ips/0"})


def test_an_unreadable_source_record_withholds_what_it_could_change(doc_validator):
    # on another device: it could carry either address, so neither the owner nor the absence can be claimed
    snap = _base()
    snap["devices"]["r3"] = {"hostname": "r3"}
    snap["interfaces"]["r3"] = {"Gi9": {"svi_ip": "bogus", "run_config_observed": True}}
    assert ui.project_topology(snap)["source_addresses"]["state"] == UV
    owner, absent = _peers(snap, doc_validator)["ospf"]
    for fact in (owner, absent):
        assert (fact["state"], fact["value"]) == (UV, None)
        assert fact["reason"].startswith("unverified: 1 address source record(s) cannot be read")
        assert "/interfaces/r3/Gi9/svi_ip" in _refs(fact, "witness")
    assert "/interfaces/r2/Gi1/svi_ip" in _refs(owner, "witness")
    # on the owner itself: the owner stands, the absence still cannot be claimed
    snap = _base()
    snap["interfaces"]["r2"]["Gi9"] = {"svi_ip": "bogus", "run_config_observed": True}
    owner, absent = _peers(snap, doc_validator)["ospf"]
    assert (owner["state"], owner["value"]) == (PUB, "r2")
    assert "/interfaces/r2/Gi9/svi_ip" not in _refs(owner)
    assert (absent["state"], "/interfaces/r2/Gi9/svi_ip" in _refs(absent, "witness")) == (UV, True)


def test_an_owner_the_index_withholds_is_withheld_with_its_collection_record(doc_validator):
    snap = _base()
    # the owner's own device-scope rule: the name without case or surrounding space
    snap["collection_completeness"] = {"devices": [
        {"host": " R2 ", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]}]}
    index = ui.project_topology(snap)["source_addresses"]["items"]
    assert [item["host"]["state"] for item in index if item["pointer"].startswith("/interfaces/r2/")] == [NC]
    owner, absent = _peers(snap, doc_validator)["ospf"]
    assert (owner["state"], owner["value"]) == (NC, None)
    assert owner["reason"].startswith("not collected: this host is a recorded collection blind spot (the one device")
    assert {"/collection_completeness/devices/0", "/interfaces/r2/Gi1/svi_ip"} <= _refs(owner, "witness")
    assert (absent["state"], "/collection_completeness/devices/0" in _refs(absent, "witness")) == (NC, True)


def test_a_failed_or_uncollected_index_input(doc_validator):
    snap = _base()
    snap["assessment_integrity"] = {"interfaces": "failed"}
    page = _page(snap, "r1", doc_validator)
    for group in page["routing_neighbors"]["items"]:
        for row in group["neighbors"]["items"]:
            assert row[ui.NEIGHBOR_ADDRESS_FIELDS[group["protocol"]]]["state"] == PUB   # the address itself is read
            fact = row["peer_host"]
            assert (fact["state"], fact["value"]) == (AU, None)
            assert fact["reason"].startswith("analysis unavailable")
            assert "/assessment_integrity/interfaces" in _refs(fact, "failure_record")
    snap = _base()
    del snap["routes"]
    owner, absent = _peers(snap, doc_validator)["ospf"]
    assert (owner["state"], owner["value"]) == (PUB, "r2")              # an observed owner stands
    assert (absent["state"], absent["value"]) == (NC, None)             # but its absence is no clean result
    assert absent["reason"].startswith("not collected: the address index (topology.source_addresses) may be "
                                       "incomplete") and "(routes)" in absent["reason"]


def test_an_unusable_address_cell_withholds_the_peer_with_its_own_state(doc_validator):
    snap = _base()
    ospf = snap["routing_neighbors"]["r1"]["ospf"]
    ospf[0]["address"] = ""                                             # the producer's empty text
    del ospf[1]["address"]                                              # a parser that emits no address
    ospf.append("junk")                                                 # a row that is not an object
    snap["routing_neighbors"]["r1"]["bgp"][0]["neighbor"] = "peer-group-x"
    snap["routing_neighbors"]["r1"]["isis"] = [{"neighbor": "192.0.2.2", "state": "UP"}]
    page = _page(snap, "r1", doc_validator)
    empty, missing, junk = (row["peer_host"] for row in _rows(page, "ospf"))
    assert (empty["state"], empty["reason"]) == (
        NC, "not collected: the neighbour row's address is empty, so there is no address to resolve")
    assert _refs(empty) == {"/routing_neighbors/r1/ospf/0/address"}
    assert missing["state"] == NC and missing["reason"] == _rows(page, "ospf")[1]["address"]["reason"]
    assert junk["state"] == UV and junk["reason"] == _rows(page, "ospf")[2]["address"]["reason"]
    bgp = _rows(page, "bgp")[0]["peer_host"]
    assert (bgp["state"], bgp["reason"]) == (
        UV, "unverified: the neighbour row's neighbor is not an IP address, so it names no owner")
    isis = _rows(page, "isis")[0]["peer_host"]
    assert isis["state"] == NC and "routing protocol 'isis'" in isis["reason"]
    assert _refs(isis) == {"/routing_neighbors/r1/isis/0"}
    for fact in (empty, missing, junk, bgp, isis):
        assert fact["value"] is None and "caveats" not in fact
        for pointer in _refs(fact):
            _resolve(snap, pointer)


# --------------------------------------------------------------------------------------------------
# purity: no input mutation, and no container shared between documents
# --------------------------------------------------------------------------------------------------
def test_resolution_is_pure_and_owns_its_containers(sample):
    snap = copy.deepcopy(sample)
    before = copy.deepcopy(snap)
    first, again = ui.project_devices(snap, ["core1", "core1"])
    assert snap == before and first == again == ui.project_device(snap, "core1")
    peer = _rows(first["device"], "ospf")[0]["peer_host"]
    peer["refs"].clear()
    peer["refs"].append({"pointer": "/x", "role": "witness"})
    assert _rows(again["device"], "ospf")[0]["peer_host"] == _rows(
        ui.project_device(before, "core1")["device"], "ospf")[0]["peer_host"]
