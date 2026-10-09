"""Device-level failure impact and structural links (contract gaps G10/G11): selections, never re-simulation.

A device page selects the stored ``failure_impact`` row and the stored ``link_centrality`` rows that name the device
by exact host, and builds each with the fleet topology's own row builder, so a device row IS the fleet row. The page
never re-simulates, and an empty selection is never a clean result:

* ``analyze.compute_failure_impact`` writes one row per host of its network model (every scanned host), so a device
  with no row was not simulated -- that is a blind spot, never "no impact";
* ``analyze.compute_link_centrality`` keeps only CDP/LLDP links whose two ends were both scanned, so a device absent
  from it may face an unscanned peer or lack CDP/LLDP evidence -- never proof that it has no inter-switch link.

Both producers compute over every scanned device's evidence, so a blind spot ANYWHERE in the fleet qualifies their
rows, on the fleet topology and on the device page alike. A row the producer says it could not simulate (its
INDETERMINATE detail) withholds its severity and counts rather than show Info and zero as measurements. So does a
row older than the producer's off_scan_gw_vlans marker, and the row of a device whose scoped interface running-config
(the only source of its gateway SVIs) was not captured -- held by the one shared row builder, so both surfaces agree.
A held row's detail is held with it, unless it is the producer's own INDETERMINATE disclosure. A row that simulated
only part of its VLANs, or whose switch the stored cable map cables to a peer the collection never reached (anything
but positively identified edge gear), never shows a band below High, a zero, or a clean-bill detail as a measurement.

Every value is checked against an INDEPENDENT lookup in the snapshot, never the module's own join.
"""
from __future__ import annotations

import ast
import copy
import json
import pathlib
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze
from cisco_toolkit import ui_projection as ui
from cisco_toolkit.model import InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
SECTIONS = ("failure_impact", "structural_links")
ENDS = ("a_host", "b_host")
#: The failure-impact cells that measure a simulated blast radius (host, off_scan_gw_vlans and detail do not).
MEASURES = ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp")
#: The device document's limitations, in document order, written out by hand rather than taken from the module's
#: own formula: its four own limitations, then each payload limitation a device page cites, in payload order.
DEVICE_DOC_LIMITATION_IDS = (
    "deduction_refs_are_subsequence", "routes_in_scope_only", "interface_default_not_observed",
    "routing_neighbors_empty_is_ambiguous", "one_hop_failure_attribution", "coverage_matrix_shown_as_published",
    "projection_owned_verdicts", "device_physical_defaults_not_observed", "health_scored_without_security",
    "health_scored_over_partial_collection", "dossier_band_over_unassessed_axes", "engine_list_capped",
    "move_group_label_absent", "row_selection_by_exact_key", "fleet_lists_exclude_blind_devices",
    "device_findings_scope", "topology_scanned_model", "impact_scanned_scope",
)
#: Two blind spots, neither of them core1 or dist2: one device never reached, one reached in part.
BLIND = [{"host": "ghost1", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]},
         {"host": "access2", "status": "partial", "data_quality": 75, "missing": ["interface status"]}]


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema():
    return ui.ui_projection_schema()


@pytest.fixture(scope="module")
def doc_validator(schema):
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/DeviceDocument"})


@pytest.fixture(scope="module")
def topology_validator(schema):
    return Draft202012Validator({"$ref": "#/$defs/Topology", "$defs": schema["$defs"]})


def _page(snap, host, validator):
    """One device document, schema-validated and JSON-native, returning its page."""
    doc = ui.project_device(snap, host)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    assert not errors, (host, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]])
    json.dumps(doc, allow_nan=False)
    return doc["device"]


def _topology(snap, validator):
    topology = ui.project_topology(snap)
    errors = sorted(validator.iter_errors(topology), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    json.dumps(topology, allow_nan=False)
    return topology


def _naming(rows, host, fields):
    """Independent selection: the indices of the stored rows that name `host` exactly in any of `fields`."""
    return [i for i, r in enumerate(rows) if isinstance(r, dict) and any(r.get(f) == host for f in fields)]


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


_MISSING = object()


def _resolve(doc, pointer):
    """An independent RFC 6901 resolver (``""`` is the whole document): ``_MISSING`` when it does not resolve."""
    if pointer == "":
        return doc
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return _MISSING
    return cur


def _facts(obj, where=""):
    """``(document pointer, fact-or-factlist)`` for every envelope under `obj`."""
    if isinstance(obj, dict):
        if {"state", "subject", "refs", "basis"} <= set(obj):
            yield where, obj
        for key, val in obj.items():
            yield from _facts(val, f"{where}/{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _facts(val, f"{where}/{i}")


def _no_interface_parse(snap, host):
    """Independent: the snapshot carries no non-empty interface parse for `host`."""
    row = snap.get("interfaces", {}).get(host)
    return not (isinstance(row, dict) and row)


def _run_config_observed(snap, host):
    """Independent: some interface of `host` carries ``run_config_observed: true`` -- build.py's mark for the scoped
    interface running-config capture, the only source of a device's gateway SVI addresses (svi_ip)."""
    ports = snap.get("interfaces", {}).get(host)
    return isinstance(ports, dict) and any(isinstance(rec, dict) and rec.get("run_config_observed") is True
                                           for rec in ports.values())


#: analyze.compute_cable_map's kinds for POSITIVELY identified edge gear (its _node_kind ranks switch, router and
#: firewall first across every observer), written out here rather than taken from the module.
EDGE_KINDS = ("ap", "phone", "endpoint")


def _uncollected_peer_cables(snap, host):
    """Independent: the stored cable rows naming `host` as one end whose far end is not ONE cable-map node shown as
    collected, or as an uncollected edge-gear node -- the neighbours a scanned-only simulation cannot see behind."""
    nodes = snap["cable_map"]["nodes"]
    out = []
    for j, cable in enumerate(snap["cable_map"]["cables"]):
        if host not in (cable["a"], cable["b"]):
            continue
        far = cable["b"] if cable["a"] == host else cable["a"]
        same = [node for node in nodes if node.get("host") == far]
        if len(same) == 1 and (same[0].get("collected") is True or (
                same[0].get("collected") is False and same[0].get("kind") in EDGE_KINDS)):
            continue
        out.append(j)
    return out


def _understatable(src, field):
    """Independent: a value an uncollected neighbour may understate -- a band below High, a zero count, or a detail
    that names no simulated VLAN (the producer's clean bill)."""
    if field == "severity":
        return src[field] != "High"
    if field == "detail":
        return src["vlans_impacted"] == 0 and not src[field].startswith(ui.IMPACT_INDETERMINATE_PREFIX)
    return field in MEASURES and src[field] == 0


# --------------------------------------------------------------------------------------------------
# the closed schema and the module tables carry both selections
# --------------------------------------------------------------------------------------------------
def test_device_page_schema_and_tables_carry_both_selections(sample):
    d = ui.ui_projection_schema()["$defs"]
    page = d["DevicePage"]
    assert page["additionalProperties"] is False
    assert page["properties"]["failure_impact"] == {"$ref": "#/$defs/TopologyImpactRowList"}
    assert page["properties"]["structural_links"] == {"$ref": "#/$defs/TopologyStructuralLinkRowList"}
    assert set(SECTIONS) <= set(page["required"])
    assert set(page["required"]) == set(page["properties"])
    # needs: what the producers read among the essential captures collection_completeness can name as missing
    assert set(ui.SELECTION_NEEDS["failure_impact"]) == {"switchport", "CDP/LLDP neighbors"}
    assert tuple(ui.SELECTION_NEEDS["structural_links"]) == ("CDP/LLDP neighbors",)
    cited = ui.DEVICE_CITED_LIMITATIONS
    for section in SECTIONS:
        for lid in ("one_hop_failure_attribution", "row_selection_by_exact_key", "topology_scanned_model",
                    "projection_owned_verdicts", "fleet_lists_exclude_blind_devices"):
            assert "/device/" + section in cited[lid], (lid, section)
    assert tuple(cited["impact_scanned_scope"]) == ("/device/failure_impact",)
    # the count and order come from the hand-written list above, never from the module's own formula
    lims = page["properties"]["limitations"]
    assert lims["minItems"] == lims["maxItems"] == len(DEVICE_DOC_LIMITATION_IDS)
    doc = ui.project_device(sample, "core1")["device"]["limitations"]
    assert [lim["id"] for lim in doc] == list(DEVICE_DOC_LIMITATION_IDS)
    payload = {lim["id"]: lim for lim in ui.LIMITATIONS}
    for path in ("/topology/failure_impact", "/topology/structural_links"):
        assert path in payload["fleet_lists_exclude_blind_devices"]["applies_to"], path


# --------------------------------------------------------------------------------------------------
# (a) a simulated device selects exactly its fleet row; (d) structural rows from either end, nothing else
# --------------------------------------------------------------------------------------------------
def test_a_simulated_device_selects_exactly_its_fleet_rows(sample, doc_validator):
    topology = ui.project(sample)["topology"]
    impact, structural = topology["failure_impact"]["items"], topology["structural_links"]["items"]
    assert [it["index"] for it in impact] == list(range(len(sample["failure_impact"])))
    assert [it["index"] for it in structural] == list(range(len(sample["link_centrality"])))
    lacking, bounded = [], []
    for host in sorted(sample["devices"]):
        page = _page(sample, host, doc_validator)
        rows = _naming(sample["failure_impact"], host, ("host",))
        assert len(rows) == 1, host                                 # the producer writes one row per scanned host
        sel = page["failure_impact"]
        assert sel["subject"] == "/failure_impact"
        assert sel["items"] == [impact[rows[0]]], host               # the fleet row itself, same pointer and values
        # every sample device carries its scoped interface running-config, the simulation's gateway input
        assert _run_config_observed(sample, host), host
        assert sel["state"] == PUB, (host, sel.get("reason"))
        if host not in sample["security"]:
            # no full running-config (no security row): that capture is not the simulation's input, so it holds
            # nothing -- the device's gateway SVIs came from the scoped interface capture it does carry
            lacking.append(host)
        row = sel["items"][0]
        assert row["pointer"] == f"/failure_impact/{rows[0]}"
        assert row["host"]["value"] == host
        src = sample["failure_impact"][rows[0]]
        # a switch cabled to a peer the collection never reached cannot vouch for a value that peer may understate
        peers = _uncollected_peer_cables(sample, host)
        witness = {(f"/cable_map/cables/{j}", "witness") for j in peers}
        if peers:
            bounded.append(host)
        for field in ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp", "off_scan_gw_vlans", "detail"):
            assert row[field]["subject"] == f"/failure_impact/{rows[0]}/{field}"
            if peers and _understatable(src, field):
                assert row[field]["state"] == NC and row[field]["value"] is None, (host, field, row[field])
                assert f"cannot account for endpoints behind {len(peers)} uncollected neighbour(s)" in (
                    row[field]["reason"]), (host, field, row[field]["reason"])
                assert witness <= _refs(row[field]), (host, field)
                continue
            assert row[field]["state"] == PUB, (host, field, row[field].get("reason"))
            assert row[field]["value"] == src[field], (host, field)
            if field in MEASURES:                                       # a published lower bound cites each cable
                assert witness <= _refs(row[field]), (host, field)
        assert "row_selection_by_exact_key" in sel["caveats"]
        want = _naming(sample["link_centrality"], host, ENDS)
        links = page["structural_links"]
        assert want and links["state"] == PUB, (host, links.get("reason"))
        assert links["subject"] == "/link_centrality"
        assert links["items"] == [structural[i] for i in want], host
    assert lacking and lacking == sorted(set(sample["devices"]) - set(sample["security"]))
    # The sample's uncollected peers: one AP behind every access switch and another, plus a WAN router, on core2.
    # The APs are edge gear and bound nothing; the router bounds core2's row. core2 is High, so only its zero
    # counts are withheld: its band, positive counts and per-VLAN detail stay published as lower bounds.
    kinds = {n["host"]: n["kind"] for n in sample["cable_map"]["nodes"] if n["collected"] is False}
    assert sorted(kinds.values()) == ["ap", "ap", "router"], kinds
    assert bounded == ["core2"], bounded
    core2 = sample["failure_impact"][_naming(sample["failure_impact"], "core2", ("host",))[0]]
    assert core2["severity"] == "High" and core2["backup"] == core2["fhrp"] == 0 and core2["vlans_impacted"] > 0
    assert [kinds[sample["cable_map"]["cables"][j]["b"]] for j in _uncollected_peer_cables(sample, "core2")] == [
        "router"]


def test_d_structural_links_name_the_device_from_either_end_and_nothing_else(sample, doc_validator):
    ends = [it["ends"]["value"] for it in _page(sample, "core1", doc_validator)["structural_links"]["items"]]
    assert ends and all("core1" in (e["a_host"], e["b_host"]) for e in ends)
    assert any(e["a_host"] == "core1" for e in ends) and any(e["b_host"] == "core1" for e in ends)
    assert len(ends) == sum(1 for r in sample["link_centrality"] if "core1" in (r["a_host"], r["b_host"]))
    for host in ("access16", "dist2", "podacc1"):
        sel = _page(sample, host, doc_validator)["structural_links"]
        assert [it["index"] for it in sel["items"]] == _naming(sample["link_centrality"], host, ENDS), host
        for item in sel["items"]:
            assert host in (item["ends"]["value"]["a_host"], item["ends"]["value"]["b_host"])
            assert item["is_bridge"]["value"] == sample["link_centrality"][item["index"]]["is_bridge"]
            assert item["pairs_cut"]["value"] == sample["link_centrality"][item["index"]]["pairs_cut"]
    # a scanned, fully collected device that no stored link names: honest absence, never "no link"
    snap = copy.deepcopy(sample)
    snap["link_centrality"] = [r for r in snap["link_centrality"] if "podacc1" not in (r["a_host"], r["b_host"])]
    assert snap["link_centrality"]
    sel = _page(snap, "podacc1", doc_validator)["structural_links"]
    assert sel["state"] == NC and sel["items"] == []
    assert "not proof that the device has no inter-switch link" in sel["reason"]
    other = _page(snap, "core1", doc_validator)["structural_links"]
    assert other["state"] == PUB and other["items"]


def test_two_rows_naming_one_device_are_unverified_never_picked_between(sample, doc_validator):
    snap = copy.deepcopy(sample)
    first = _naming(snap["failure_impact"], "core1", ("host",))[0]
    snap["failure_impact"].append(copy.deepcopy(snap["failure_impact"][first]))
    dup = len(snap["failure_impact"]) - 1
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "2 rows" in sel["reason"], sel
    assert {(f"/failure_impact/{first}", "witness"), (f"/failure_impact/{dup}", "witness")} <= _refs(sel)
    assert [it["index"] for it in sel["items"]] == [first, dup]
    assert "collection gap" not in sel["reason"]
    assert _page(snap, "dist1", doc_validator)["failure_impact"]["state"] == PUB
    # the duplicate keeps the device's own collection gap, and its witness, beside the ambiguity: both negative
    # observations, each with its witnesses, and both stored rows
    snap["collection_completeness"]["devices"] = [
        {"host": "core1", "status": "partial", "data_quality": 75, "missing": ["switchport"]}]
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "2 rows" in sel["reason"], sel
    assert "collection gap" in sel["reason"] and "switchport" in sel["reason"], sel["reason"]
    assert {(f"/failure_impact/{first}", "witness"), (f"/failure_impact/{dup}", "witness"),
            ("/collection_completeness/devices/0/missing", "witness")} <= _refs(sel)
    assert [it["index"] for it in sel["items"]] == [first, dup]


@pytest.mark.parametrize("bad", ["not a row", None, {"severity": "High"}, {"host": 7}, {"host": ["core1"]}])
def test_an_unreadable_impact_row_makes_every_selection_unverified(sample, doc_validator, topology_validator, bad):
    """The join cannot read the row, so it could be the device's own: never 'not simulated', never picked past."""
    snap = copy.deepcopy(sample)
    snap["failure_impact"] = [r for r in snap["failure_impact"] if r["host"] != "core1"] + [bad]
    k = len(snap["failure_impact"]) - 1
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "could name this device" in sel["reason"], sel
    assert "an absent row is not 'no impact'" not in sel["reason"]
    assert (f"/failure_impact/{k}", "witness") in _refs(sel)
    assert sel["items"] == []
    kept = _page(snap, "dist1", doc_validator)["failure_impact"]          # a device that still has its row
    assert kept["state"] == UV and (f"/failure_impact/{k}", "witness") in _refs(kept)
    assert [it["index"] for it in kept["items"]] == _naming(snap["failure_impact"], "dist1", ("host",))
    fleet = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert fleet["host"]["state"] != PUB                                 # the fleet shows the same row withheld


def test_an_unreadable_structural_row_makes_every_selection_unverified(sample, doc_validator):
    snap = copy.deepcopy(sample)
    snap["link_centrality"].append({"a_host": None, "b_host": "core1", "betweenness": 1.0, "is_bridge": False,
                                    "pairs_cut": 0, "rank": 99})
    k = len(snap["link_centrality"]) - 1
    for host in ("core1", "podacc1"):
        sel = _page(snap, host, doc_validator)["structural_links"]
        assert sel["state"] == UV and "could name this device" in sel["reason"], (host, sel)
        assert (f"/link_centrality/{k}", "witness") in _refs(sel)
        assert [it["index"] for it in sel["items"]] == _naming(snap["link_centrality"], host, ENDS), host


def test_a_valid_row_beside_an_unreadable_tail_is_kept_and_the_tail_witnessed(sample, doc_validator,
                                                                            topology_validator):
    """The refuter's counterexample: core1's valid row plus a copy of it whose host is null. The valid stored row is
    kept (the fleet row itself), the selection is unverified for membership with a witness to the tail, and a capture
    gap is carried beside that doubt with its own witness."""
    snap = copy.deepcopy(sample)
    first = _naming(snap["failure_impact"], "core1", ("host",))[0]
    tail = copy.deepcopy(snap["failure_impact"][first])
    tail["host"] = None
    snap["failure_impact"].append(tail)
    k = len(snap["failure_impact"]) - 1
    topology = _topology(snap, topology_validator)
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "1 row(s) in failure_impact cannot be joined" in sel["reason"], sel
    assert "2 rows" not in sel["reason"]                   # a membership doubt, not a duplicate the join can see
    assert (f"/failure_impact/{k}", "witness") in _refs(sel)
    assert sel["items"] == [topology["failure_impact"]["items"][first]]
    assert all(sel["items"][0][field]["state"] == PUB for field in ("host",) + MEASURES)
    assert topology["failure_impact"]["items"][k]["host"]["state"] == UV       # the fleet withholds the tail's key
    # the same device's structural selection reads another list: untouched by this tail
    assert _page(snap, "core1", doc_validator)["structural_links"]["state"] == PUB
    # a capture gap is carried beside the membership doubt, each with its witness
    snap["collection_completeness"]["devices"] = [
        {"host": "core1", "status": "partial", "data_quality": 75, "missing": ["switchport"]}]
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "cannot be joined" in sel["reason"] and "switchport" in sel["reason"], sel
    assert {(f"/failure_impact/{k}", "witness"), ("/collection_completeness/devices/0/missing", "witness")} <= (
        _refs(sel))
    assert [it["index"] for it in sel["items"]] == [first]
    # the control: without the tail, the same device publishes its one row, unqualified
    clean = _page(sample, "core1", doc_validator)["failure_impact"]
    assert clean["state"] == PUB and clean["items"] == [topology["failure_impact"]["items"][first]]


@pytest.mark.parametrize("source, key, rows, deep_empty", [
    ("failure_impact", "failure_impact", [None, {"host": None}], True),
    ("failure_impact", "failure_impact", [{"host": 7, "severity": "High"}], False),
    ("link_centrality", "structural_links", [None, {"a_host": None, "b_host": None}], True),
    ("link_centrality", "structural_links", [{"a_host": 7, "b_host": ["core1"], "is_bridge": True}], False),
])
def test_a_list_of_only_unreadable_members_is_unverified_with_a_witness_to_each(sample, doc_validator,
                                                                              topology_validator, source, key, rows,
                                                                              deep_empty):
    """Malformed-only input: never 'not simulated' or 'no link' (an absent row), and never a clean absence. Every
    member is witnessed on each device page and kept, withheld, on the fleet list. The other list is unaffected.
    A list of deep-empty rows is one the abstention core calls empty: it stays unverified for that reason too."""
    snap = copy.deepcopy(sample)
    snap[source] = copy.deepcopy(rows)
    members = {(f"/{source}/{j}", "witness") for j in range(len(rows))}
    other = next(s for s in SECTIONS if s != key)
    for host in ("core1", "podacc1"):
        page = _page(snap, host, doc_validator)
        sel = page[key]
        assert sel["state"] == UV and "cannot be joined" in sel["reason"], (host, sel)
        assert ("the abstention core calls this list empty" in sel["reason"]) == deep_empty, sel["reason"]
        assert "an absent row is not 'no impact'" not in sel["reason"], host
        assert "not proof that the device has no inter-switch link" not in sel["reason"], host
        assert members <= _refs(sel), (host, sel["refs"])
        assert sel["items"] == [], host
        assert page[other]["state"] == PUB and not members & _refs(page[other]), (host, other)   # the control
    fleet = _topology(snap, topology_validator)[key]
    assert fleet["state"] == (UV if deep_empty else PUB), fleet.get("reason")
    assert [it["index"] for it in fleet["items"]] == list(range(len(rows)))
    for item in fleet["items"]:
        field = "host" if key == "failure_impact" else "ends"
        assert item[field]["state"] == UV and item[field]["value"] is None, item[field]


# --------------------------------------------------------------------------------------------------
# (b) no simulation row is never "no impact"; no selection is ever a clean absence
# --------------------------------------------------------------------------------------------------
def test_b_a_device_with_no_simulation_row_is_not_collected_never_no_impact(sample, doc_validator):
    snap = copy.deepcopy(sample)
    snap["failure_impact"] = [r for r in snap["failure_impact"] if r["host"] != "core1"]
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == NC and sel["items"] == []
    assert sel["state"] not in (PUB, CBE)
    assert "an absent row is not 'no impact'" in sel["reason"]
    assert sel["subject"] == "/failure_impact"
    other = _page(snap, "dist1", doc_validator)["failure_impact"]
    assert other["state"] == PUB and [it["host"]["value"] for it in other["items"]] == ["dist1"]
    snap["failure_impact"] = []                                  # an empty simulation, no failure recorded
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == NC and "an absent row is not 'no impact'" in sel["reason"]


def test_b_no_device_selection_is_ever_a_clean_absence(sample, monkeypatch):
    """Every host's empty selection is not_collected for the concrete reason that applies to it -- and the check
    is shown able to fail: an absence rule mutated into a plain 'nothing found' turns those selections CBE."""
    hosts = sorted(set(sample["devices"]) | {n["host"] for n in sample["cable_map"]["nodes"]})
    snap = copy.deepcopy(sample)
    snap["failure_impact"], snap["link_centrality"] = [], []         # read, present, and naming nobody

    def pages():
        return {(host, section): ui.project_device(snap, host)["device"][section]
                for host in hosts for section in SECTIONS}

    expected = {"failure_impact": "an absent row is not 'no impact'",
                "structural_links": "not proof that the device has no inter-switch link"}
    for (host, section), sel in pages().items():
        assert sel["state"] == NC and sel["items"] == [], (host, section, sel)
        assert "not a blind spot" not in sel["reason"], (host, section)
        # the full running-config (the security row) is not a simulation input, so it never gates a selection;
        # a device's own gateway evidence is held inside its row, never as a second selection state
        assert "security carries no row" not in sel["reason"], (host, section, sel["reason"])
        if _no_interface_parse(snap, host):
            assert "no interface parse result" in sel["reason"], (host, section, sel["reason"])
        else:
            assert expected[section] in sel["reason"], (host, section, sel["reason"])
    monkeypatch.setattr(ui, "_ABSENT_IMPACT", "no simulation row names this device")
    monkeypatch.setattr(ui, "_ABSENT_STRUCTURAL", "no structural link names this device")
    mutated = pages()
    assert {section for (_h, section), sel in mutated.items() if sel["state"] == CBE} == set(SECTIONS)
    # and on the sample itself, every selection is published or a reasoned not_collected
    for host in hosts:
        page = ui.project_device(sample, host)["device"]
        for section in SECTIONS:
            sel = page[section]
            assert sel["state"] in (PUB, NC), (host, section, sel.get("reason"))
            if sel["state"] != PUB:
                assert "not a blind spot" not in sel["reason"], (host, section)


# --------------------------------------------------------------------------------------------------
# (c) a device the collection did not fully reach is not_collected, with the witness that says so
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("missing, impact_gap, structural_gap", [
    ("CDP/LLDP neighbors", True, True),
    ("switchport", True, False),
    ("interface status", False, False),          # read by neither producer
    ("version/inventory", False, False),
])
def test_c_a_missing_needed_capture_makes_the_selection_incomplete(sample, doc_validator, missing, impact_gap,
                                                                   structural_gap):
    host = "core1"
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [
        {"host": host, "status": "partial", "data_quality": 75, "missing": [missing]}]
    page = _page(snap, host, doc_validator)
    witness = ("/collection_completeness/devices/0/missing", "witness")
    for section, gap, rows in (
            ("failure_impact", impact_gap, _naming(snap["failure_impact"], host, ("host",))),
            ("structural_links", structural_gap, _naming(snap["link_centrality"], host, ENDS))):
        sel = page[section]
        assert rows and [it["index"] for it in sel["items"]] == rows, section     # shown, then qualified
        if gap:
            assert sel["state"] == NC, (section, sel)
            assert missing in sel["reason"], (section, sel["reason"])
            if section == "failure_impact":
                # one row per device: the row's own values are in doubt, not the list's completeness
                assert "values may be unreliable" in sel["reason"], sel["reason"]
                assert "the rows shown are the ones other evidence names" not in sel["reason"]
            else:
                assert "may be incomplete" in sel["reason"], sel["reason"]
            assert witness in _refs(sel), section
        else:
            # the device's own partial row is a fleet blind spot: published, and qualified by it
            assert sel["state"] == PUB, (section, sel.get("reason"))
            assert witness not in _refs(sel), section
            assert "fleet_lists_exclude_blind_devices" in sel["caveats"], section
            assert ("/collection_completeness/devices/0", "witness") in _refs(sel), section


def test_c_a_device_the_collection_never_reached_is_not_collected(sample, doc_validator):
    host = "access16"
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [
        {"host": host, "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]}]
    page = _page(snap, host, doc_validator)
    for section in SECTIONS:
        sel = page[section]
        assert sel["state"] == NC, (section, sel)
        assert ("/collection_completeness/devices/0", "witness") in _refs(sel), section


def test_c_an_uncollected_cable_map_peer_has_no_clean_absence(sample, doc_validator):
    peers = [n["host"] for n in sample["cable_map"]["nodes"] if n.get("collected") is False]
    assert peers
    for host in peers:
        assert host not in sample["devices"] and host not in sample["interfaces"]
        page = _page(sample, host, doc_validator)
        for section in SECTIONS:
            sel = page[section]
            assert sel["state"] == NC and "no interface parse result" in sel["reason"], (host, section, sel)
            assert sel["items"] == []


@pytest.mark.parametrize("host, want", [("no-such-host", NC), (7, UV), (None, UV)])
def test_an_unknown_or_non_text_host_claims_nothing(sample, doc_validator, host, want):
    page = _page(sample, host, doc_validator)
    for section in SECTIONS:
        sel = page[section]
        assert sel["state"] == want and sel["items"] == [] and sel["refs"] == [], (section, sel)


# --------------------------------------------------------------------------------------------------
# (g) a blind spot elsewhere qualifies both producers' rows, on the fleet topology and on the device page
# --------------------------------------------------------------------------------------------------
def test_g_blind_spots_elsewhere_qualify_impact_and_structural_rows_on_both_surfaces(sample, doc_validator,
                                                                                     topology_validator):
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = copy.deepcopy(BLIND)
    witness = {("/collection_completeness/devices/0", "witness"), ("/collection_completeness/devices/1", "witness")}
    topology = _topology(snap, topology_validator)
    for key in SECTIONS:
        fleet = topology[key]
        assert fleet["state"] == PUB and "fleet_lists_exclude_blind_devices" in fleet["caveats"], key
        assert witness <= _refs(fleet), key
    for key in ("nodes", "cables"):                  # discovery observations: their uncollected peers stay as rows
        assert "fleet_lists_exclude_blind_devices" not in topology[key].get("caveats", ()), key
    clean = _topology(sample, topology_validator)    # the control: no blind spot, no qualifier
    for key in SECTIONS:
        assert "fleet_lists_exclude_blind_devices" not in clean[key].get("caveats", ()), key
        assert not witness & _refs(clean[key]), key
    for host in ("core1", "dist2"):                  # neither is a blind spot; their rows are computed over them
        doc = ui.project_device(snap, host)
        assert not list(doc_validator.iter_errors(doc))
        lims = {lim["id"]: lim["applies_to"] for lim in doc["device"]["limitations"]}
        for key, source, fields in (("failure_impact", "failure_impact", ("host",)),
                                    ("structural_links", "link_centrality", ENDS)):
            sel = doc["device"][key]
            assert sel["state"] == PUB and "fleet_lists_exclude_blind_devices" in sel["caveats"], (host, key)
            assert witness <= _refs(sel), (host, key)
            assert "/device/" + key in lims["fleet_lists_exclude_blind_devices"], key
            # the rows are untouched: still exactly the fleet rows naming the device
            assert sel["items"] == [topology[key]["items"][i] for i in _naming(snap[source], host, fields)]
        assert not witness & _refs(ui.project_device(sample, host)["device"]["failure_impact"])
    # an empty list under blind spots is never 'nothing found'; without them it is collected_but_empty
    for base, blind in ((snap, True), (sample, False)):
        empty = copy.deepcopy(base)
        empty["failure_impact"], empty["link_centrality"] = [], []
        topology = _topology(empty, topology_validator)
        for key in SECTIONS:
            if blind:
                assert topology[key]["state"] == NC, (key, topology[key])
                assert "collection_completeness lists 2 device(s)" in topology[key]["reason"], key
            else:
                assert topology[key]["state"] == CBE, (key, topology[key])


# --------------------------------------------------------------------------------------------------
# (h) a switch the REAL producer could not simulate never shows Info and zero as measurements
# --------------------------------------------------------------------------------------------------
# Every interface below carries run_config_observed, as build.py marks each interface its scoped interface
# running-config capture parsed: the only source of an SVI's gateway address (svi_ip), which the producer reads.
def _trunk(port, peer, peer_port, vlans="", blocked=""):
    """A CDP-seen inter-switch trunk allowing `vlans`; STP forwards them here unless `blocked` names them."""
    return InterfaceData(port=port, status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                         neighbor_port=peer_port, endpoint_type="Switch", trunk_allowed_vlans=vlans,
                         stp_fwd_vlans="" if blocked else vlans, stp_blk_vlans=blocked, run_config_observed=True)


def _access(port, vid, mac):
    return InterfaceData(port=port, status="connected", switchport_mode="Access", vlan=str(vid), end_host_mac=mac,
                         run_config_observed=True)


def _svi(vid, address, fhrp=""):
    return InterfaceData(port=f"Vlan{vid}", svi_ip=address, hsrp_behavior=fhrp, run_config_observed=True)


def _unsimulatable_fleet():
    """Captures the real producer reads, built so that it cannot simulate every switch: `acc` carries VLAN 20,
    whose gateway was never scanned, and nothing it can simulate; `gw` gateways VLAN 10 for `acc` (a measured hard
    partition) and also carries VLAN 20; `x1` and `x2` share a trunk with no VLAN-carriage evidence on either end."""
    return {"gw": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10,20"), "Vlan10": _svi(10, "10.10.0.1/24")},
            "acc": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10,20"), "Gi10": _access("Gi10", 10, "0000.0000.000a"),
                    "Gi20": _access("Gi20", 20, "0000.0000.0014")},
            "x1": {"Gi1": _trunk("Gi1", "x2", "Gi1")}, "x2": {"Gi1": _trunk("Gi1", "x1", "Gi1")}}


def _impact_snapshot(interfaces, impact):
    return {"schema": "collect_parse_snapshot/1", "devices": {host: {"hostname": host} for host in interfaces},
            "interfaces": {host: {port: asdict(row) for port, row in ports.items()}
                           for host, ports in interfaces.items()},
            "failure_impact": impact, "cable_map": analyze.compute_cable_map(interfaces), "routes": {}}


def test_h_an_unsimulated_switch_withholds_its_severity_and_counts(doc_validator, topology_validator):
    interfaces = _unsimulatable_fleet()
    impact = analyze.compute_failure_impact(interfaces)               # the REAL producer, never a hand-written row
    by_host = {row["host"]: row for row in impact}
    assert set(by_host) == set(interfaces)
    # the producer's own disclosure, pinned: both INDETERMINATE branches open with the projection's marker
    for host, off_scan in (("acc", 1), ("x1", 0), ("x2", 0)):
        row = by_host[host]
        assert row["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), (host, row["detail"])
        assert ("off-scan gateway" in row["detail"]) == bool(off_scan), (host, row["detail"])
        assert row["severity"] == "Info" and row["off_scan_gw_vlans"] == off_scan, row
        assert all(row[f] == 0 for f in MEASURES[1:]), row                # zeros that look like measurements
    gw = by_host["gw"]
    assert not gw["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX)
    assert gw["severity"] == "High" and gw["hard"] == gw["vlans_impacted"] == 1 and gw["off_scan_gw_vlans"] == 1
    assert gw["backup"] == gw["fhrp"] == 0                                # zeros the partial simulation cannot vouch for
    snap = _impact_snapshot(interfaces, impact)
    topology = _topology(snap, topology_validator)
    rows = {row["host"]["value"]: row for row in topology["failure_impact"]["items"]}
    for host in ("acc", "x1", "x2"):
        row = rows[host]
        for field in MEASURES:
            fact = row[field]
            assert fact["state"] == NC and fact["value"] is None, (host, field, fact)
            assert "could not simulate" in fact["reason"], (host, field, fact["reason"])
            assert (row["pointer"] + "/detail", "witness") in _refs(fact), (host, field)
        for field in ("host", "off_scan_gw_vlans", "detail"):
            assert row[field]["state"] == PUB and row[field]["value"] == by_host[host][field], (host, field)
        assert row["style"]["value"]["token"] == "not_observed", (host, row["style"])
    # simulated in part, at the worst band: High and each positive count are kept as lower bounds; a zero is withheld.
    # Every measure cites the off-scan count.
    row = rows["gw"]
    for field in MEASURES:
        fact = row[field]
        assert (row["pointer"] + "/off_scan_gw_vlans", "witness") in _refs(fact), field
        if field == "severity" or gw[field]:
            assert fact["state"] == PUB and fact["value"] == gw[field], (field, fact)
        else:
            assert fact["state"] == NC and "only a lower bound" in fact["reason"], (field, fact)
    assert row["style"]["value"]["token"] == "impact_high"
    # the device page shows the same rows: a published selection whose row withholds what was not simulated
    for host in ("acc", "gw", "x1"):
        sel = _page(snap, host, doc_validator)["failure_impact"]
        assert sel["state"] == PUB and sel["items"] == [rows[host]], (host, sel.get("reason"))


def test_h_the_off_scan_count_alone_withholds_and_a_bad_count_is_unverified(topology_validator):
    interfaces = _unsimulatable_fleet()
    snap = _impact_snapshot(interfaces, analyze.compute_failure_impact(interfaces))
    k = next(i for i, row in enumerate(snap["failure_impact"]) if row["host"] == "acc")
    pointer = f"/failure_impact/{k}"
    # the same producer row without its prose marker: the count still says nothing was simulated
    snap["failure_impact"][k]["detail"] = "No reachability impact from removing this switch (within the scan)."
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in MEASURES:
        assert row[field]["state"] == NC and "simulated none" in row[field]["reason"], (field, row[field])
        assert (pointer + "/off_scan_gw_vlans", "witness") in _refs(row[field]), field
    # the clean-bill prose is not the producer's INDETERMINATE disclosure: it is held with the measures it contradicts
    detail = row["detail"]
    assert detail["state"] == NC and detail["value"] is None, detail
    assert detail["reason"] == row["severity"]["reason"]
    assert (pointer + "/off_scan_gw_vlans", "witness") in _refs(detail)
    assert row["style"]["value"]["token"] == "not_observed"
    snap["failure_impact"][k]["off_scan_gw_vlans"] = "1"
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert row["off_scan_gw_vlans"]["state"] == UV
    for field in MEASURES + ("detail",):
        assert row[field]["state"] == UV and "off_scan_gw_vlans is not a count" in row[field]["reason"], field
    assert row["style"]["value"]["token"] == "unverified"
    # the control: a clean bill the producer could fully simulate stays a published Info row, its detail included
    snap["failure_impact"][k]["off_scan_gw_vlans"] = 0
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(row[field]["state"] == PUB for field in MEASURES + ("detail",))
    assert row["severity"]["value"] == "Info" and row["style"]["value"]["token"] == "impact_info"


# --------------------------------------------------------------------------------------------------
# (i) a row the REAL producer simulated only in part never reads as a clean or low verdict
# --------------------------------------------------------------------------------------------------
def _fhrp_fleet():
    """`g1` and `g2` are FHRP peers gatewaying VLAN 10 for `acc`, so removing either one is FHRP-covered (Low).
    Both also carry VLAN 20 to `acc`, whose gateway was never scanned."""
    return {"g1": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10,20"), "Vlan10": _svi(10, "10.10.0.2/24", "Active")},
            "g2": {"Gi1": _trunk("Gi1", "acc", "Gi2", "10,20"), "Vlan10": _svi(10, "10.10.0.3/24", "Standby")},
            "acc": {"Gi1": _trunk("Gi1", "g1", "Gi1", "10,20"), "Gi2": _trunk("Gi2", "g2", "Gi1", "10,20"),
                    "Gi10": _access("Gi10", 10, "0000.0000.000a"), "Gi20": _access("Gi20", 20, "0000.0000.0014")}}


def _backup_fleet():
    """`gw` gateways VLAN 10 for `acc` through the transit `mid`; the direct gw-acc trunk is STP-blocked for VLAN 10,
    so removing `mid` is backup-covered (Medium) and removing `gw` is a hard partition (High). `gw` and `mid` also
    carry VLAN 20 to `acc`, whose gateway was never scanned."""
    return {"gw": {"Gi1": _trunk("Gi1", "mid", "Gi1", "10,20"), "Gi2": _trunk("Gi2", "acc", "Gi2", "10"),
                   "Vlan10": _svi(10, "10.10.0.1/24")},
            "mid": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10,20"), "Gi2": _trunk("Gi2", "acc", "Gi1", "10,20")},
            "acc": {"Gi1": _trunk("Gi1", "mid", "Gi2", "10,20"), "Gi2": _trunk("Gi2", "gw", "Gi2", "10", blocked="10"),
                    "Gi10": _access("Gi10", 10, "0000.0000.000a"), "Gi20": _access("Gi20", 20, "0000.0000.0014")}}


def _partial_row(fleet, host):
    """The REAL producer's rows over `fleet`, its snapshot, and the index of `host`'s row."""
    interfaces = fleet()
    impact = analyze.compute_failure_impact(interfaces)
    k = next(i for i, row in enumerate(impact) if row["host"] == host)
    return impact[k], _impact_snapshot(interfaces, impact), k


@pytest.mark.parametrize("fleet, host, band, status", [
    (_fhrp_fleet, "g1", "Low", "fhrp"),
    (_backup_fleet, "mid", "Medium", "backup"),
])
def test_i_a_partly_simulated_row_below_high_withholds_its_band_and_its_zeros(doc_validator, topology_validator,
                                                                              fleet, host, band, status):
    src, snap, k = _partial_row(fleet, host)
    # the producer simulated one VLAN and counted one it could not assess: no INDETERMINATE marker, a low band
    assert not src["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), src
    assert src["severity"] == band and src["off_scan_gw_vlans"] == 1, src
    assert src["vlans_impacted"] == src[status] == 1, src
    zeros = sorted(set(MEASURES[1:]) - {"vlans_impacted", status})
    assert all(src[field] == 0 for field in zeros), src                # stranded, hard and the other status count
    topology = _topology(snap, topology_validator)
    row = topology["failure_impact"]["items"][k]
    off_scan = (row["pointer"] + "/off_scan_gw_vlans", "witness")
    severity = row["severity"]
    assert severity["state"] == NC and severity["value"] is None, severity
    assert "may understate" in severity["reason"] and "1 VLAN(s)" in severity["reason"], severity["reason"]
    assert off_scan in _refs(severity)
    assert row["style"]["value"]["token"] == "not_observed", row["style"]   # never the neutral impact_low/medium
    for field in zeros:
        fact = row[field]
        assert fact["state"] == NC and fact["value"] is None, (field, fact)
        assert "only a lower bound" in fact["reason"] and "1 VLAN(s)" in fact["reason"], (field, fact["reason"])
        assert off_scan in _refs(fact), field
    for field in ("vlans_impacted", status):                              # a positive lower bound stays published
        fact = row[field]
        assert fact["state"] == PUB and fact["value"] == 1, (field, fact)
        assert off_scan in _refs(fact) and "impact_scanned_scope" in fact["caveats"], field
    for field in ("host", "off_scan_gw_vlans", "detail"):
        assert row[field]["state"] == PUB and row[field]["value"] == src[field], field
    sel = _page(snap, host, doc_validator)["failure_impact"]            # the device page shows the same row
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")
    # the control: the same row with nothing off-scan publishes its band and its zeros as measurements
    snap["failure_impact"][k]["off_scan_gw_vlans"] = 0
    clean = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(clean[field]["state"] == PUB and clean[field]["value"] == src[field] for field in MEASURES)
    assert clean["style"]["value"]["token"] == "impact_" + band.lower()


def test_i_a_partly_simulated_high_row_keeps_its_band(doc_validator, topology_validator):
    """High cannot be understated: it stays published beside the off-scan count, with the positive counts as lower
    bounds; the zeros are still withheld."""
    src, snap, k = _partial_row(_backup_fleet, "gw")
    assert not src["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), src
    assert src["severity"] == "High" and src["off_scan_gw_vlans"] == 1, src
    assert src["vlans_impacted"] == src["hard"] == 1 and src["stranded"] > 0 and src["backup"] == src["fhrp"] == 0
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    off_scan = (row["pointer"] + "/off_scan_gw_vlans", "witness")
    for field in ("severity", "vlans_impacted", "stranded", "hard"):
        fact = row[field]
        assert fact["state"] == PUB and fact["value"] == src[field], (field, fact)
        assert off_scan in _refs(fact), field
    for field in ("backup", "fhrp"):
        fact = row[field]
        assert fact["state"] == NC and "only a lower bound" in fact["reason"], (field, fact)
        assert off_scan in _refs(fact), field
    assert row["style"]["value"]["token"] == "impact_high"
    sel = _page(snap, "gw", doc_validator)["failure_impact"]
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")


# --------------------------------------------------------------------------------------------------
# (j) a device whose gateway evidence was not captured holds its row on both surfaces alike
# --------------------------------------------------------------------------------------------------
def test_j_a_device_without_its_scoped_running_config_holds_its_row_on_both_surfaces(sample, doc_validator,
                                                                                      topology_validator):
    host = "core1"
    snap = copy.deepcopy(sample)
    k = _naming(snap["failure_impact"], host, ("host",))[0]
    assert snap["failure_impact"][k]["severity"] == "High" and snap["failure_impact"][k]["off_scan_gw_vlans"] == 0
    assert host in snap["security"]                    # its full running-config is present: that is not the input
    for port in snap["interfaces"][host].values():
        port.pop("run_config_observed", None)          # what html.sparsify_interfaces writes for false
    assert not _run_config_observed(snap, host)
    topology = _topology(snap, topology_validator)
    row = topology["failure_impact"]["items"][k]
    # the detail too: its per-VLAN results state what the held measures could not (only the producer's own
    # INDETERMINATE disclosure stays published beside a hold)
    assert not snap["failure_impact"][k]["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX)
    for field in MEASURES + ("detail",):
        fact = row[field]
        assert fact["state"] == NC and fact["value"] is None, (field, fact)
        assert "run_config_observed" in fact["reason"] and "svi_ip" in fact["reason"], fact["reason"]
        assert (f"/interfaces/{host}", "witness") in _refs(fact), field
    assert row["detail"]["reason"] == row["severity"]["reason"]
    for field in ("host", "off_scan_gw_vlans"):
        assert row[field]["state"] == PUB and row[field]["value"] == snap["failure_impact"][k][field], field
    assert row["style"]["value"]["token"] == "not_observed"
    # one state on both surfaces: the device page shows the held fleet row, never a second selection gap
    sel = _page(snap, host, doc_validator)["failure_impact"]
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")
    for other in ("dist1", "access1"):                 # every other device keeps its measured row
        i = _naming(snap["failure_impact"], other, ("host",))[0]
        assert all(topology["failure_impact"]["items"][i][field]["state"] == PUB for field in MEASURES), other
    # a marker that is present but not true reads the same; one observed interface lifts the hold
    name = next(iter(snap["interfaces"][host]))
    snap["interfaces"][host][name]["run_config_observed"] = "true"
    assert _topology(snap, topology_validator)["failure_impact"]["items"][k]["severity"]["state"] == NC
    snap["interfaces"][host][name]["run_config_observed"] = True
    lifted = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(lifted[field]["state"] == PUB for field in MEASURES + ("detail",))
    assert lifted["style"]["value"]["token"] == "impact_high"
    # no interface record at all: held, with the interfaces map as the witness
    del snap["interfaces"][host]
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(row[field]["state"] == NC for field in MEASURES + ("detail",))
    assert ("/interfaces", "witness") in _refs(row["severity"])
    assert ("/interfaces", "witness") in _refs(row["detail"])
    # the control the earlier rule got wrong: no security row (no full running-config) holds nothing
    snap = copy.deepcopy(sample)
    del snap["security"][host]
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(row[field]["state"] == PUB for field in MEASURES)
    sel = _page(snap, host, doc_validator)["failure_impact"]
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")


# --------------------------------------------------------------------------------------------------
# (k) a row older than the producer's assessability marker is never a measurement
# --------------------------------------------------------------------------------------------------
def test_k_a_row_without_the_off_scan_marker_withholds_its_severity_and_counts(sample, doc_validator,
                                                                               topology_validator):
    """Engines before analyze.compute_failure_impact wrote off_scan_gw_vlans (and before they flagged blind trunks
    INDETERMINATE) wrote 'No reachability impact' with Info and zeros for a switch they could not simulate."""
    snap = copy.deepcopy(sample)
    legacy = {"podacc1": "Info", "core1": "High"}        # a stored clean bill, and a stored High
    for host, band in legacy.items():
        k = _naming(snap["failure_impact"], host, ("host",))[0]
        assert snap["failure_impact"][k]["severity"] == band
        del snap["failure_impact"][k]["off_scan_gw_vlans"]
    topology = _topology(snap, topology_validator)
    for host in legacy:
        k = _naming(snap["failure_impact"], host, ("host",))[0]
        row = topology["failure_impact"]["items"][k]
        # the detail is held with the measures: the stored clean bill ("No reachability impact") and the stored
        # per-VLAN results are what an engine that old wrote without being able to assess them
        assert not snap["failure_impact"][k]["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), host
        for field in MEASURES + ("detail",):
            fact = row[field]
            assert fact["state"] == NC and fact["value"] is None, (host, field, fact)
            assert "predates the producer's assessability marker" in fact["reason"], (host, field, fact["reason"])
            assert (row["pointer"], "witness") in _refs(fact), (host, field)
        assert row["off_scan_gw_vlans"]["state"] == NC
        assert row["host"]["state"] == PUB
        assert row["style"]["value"]["token"] == "not_observed", (host, row["style"])
        sel = _page(snap, host, doc_validator)["failure_impact"]
        assert sel["state"] == PUB and sel["items"] == [row], (host, sel.get("reason"))
    # the control: a row that carries the marker keeps its measures and its detail
    i = _naming(snap["failure_impact"], "dist1", ("host",))[0]
    assert all(topology["failure_impact"]["items"][i][field]["state"] == PUB for field in MEASURES + ("detail",))
    # a legacy row whose detail is the producer's INDETERMINATE disclosure keeps that disclosure published
    k = _naming(snap["failure_impact"], "podacc1", ("host",))[0]
    snap["failure_impact"][k]["detail"] = ui.IMPACT_INDETERMINATE_PREFIX + " - a disclosure, not a clean bill."
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert row["detail"]["state"] == PUB and row["detail"]["value"] == snap["failure_impact"][k]["detail"]
    assert all(row[field]["state"] == NC for field in MEASURES)


# --------------------------------------------------------------------------------------------------
# (l) a switch cabled to a peer the collection never reached cannot vouch for a clean or low verdict
# --------------------------------------------------------------------------------------------------
def _edge(port, peer, endpoint_type, platform=""):
    """A CDP-seen trunk to a peer the collection never reached; how the peer advertised itself (its endpoint type
    and platform) is what analyze.compute_cable_map classifies its node kind from."""
    return InterfaceData(port=port, status="connected", switchport_mode="Trunk", cdp_neighbor=peer,
                         neighbor_port="Gi0/1", endpoint_type=endpoint_type, neighbor_platform=platform,
                         trunk_allowed_vlans="10", stp_fwd_vlans="10", run_config_observed=True)


def _downstream_fleet(peer="dsw", endpoint_type="Switch", platform=""):
    """`gw` gateways VLAN 10 for `acc`, so removing `gw` is a measured hard partition (High). `acc` also trunks down
    to `peer` and `gw` up to the router `wan`; the collection reached neither. Removing `acc` strands nothing the
    scan can see, so the producer writes its clean bill for it, whatever hangs behind `peer`."""
    return {"gw": {"Gi1": _trunk("Gi1", "acc", "Gi1", "10"), "Gi47": _edge("Gi47", "wan", "Router", "cisco ISR4331/K9"),
                   "Vlan10": _svi(10, "10.10.0.1/24")},
            "acc": {"Gi1": _trunk("Gi1", "gw", "Gi1", "10"), "Gi10": _access("Gi10", 10, "0000.0000.000a"),
                    "Gi48": _edge("Gi48", peer, endpoint_type, platform)}}


def _downstream(fleet_args=(), host="acc"):
    """The REAL producers' rows over :func:`_downstream_fleet`, its snapshot, and `host`'s row index and source row."""
    interfaces = _downstream_fleet(*fleet_args)
    impact = analyze.compute_failure_impact(interfaces)
    snap = _impact_snapshot(interfaces, impact)
    k = next(i for i, row in enumerate(impact) if row["host"] == host)
    return snap, k, impact[k]


def _node(snap, host):
    same = [n for n in snap["cable_map"]["nodes"] if n["host"] == host]
    assert len(same) == 1, (host, same)
    return same[0]


def _assert_clean_bill(src):
    """The producer's clean bill: Info, every count zero, nothing off-scan, no INDETERMINATE disclosure."""
    assert src["severity"] == "Info" and src["off_scan_gw_vlans"] == 0, src
    assert all(src[field] == 0 for field in MEASURES[1:]), src
    assert not src["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), src


def test_l_a_switch_facing_an_uncollected_downstream_switch_withholds_its_clean_bill(doc_validator,
                                                                                    topology_validator):
    snap, k, src = _downstream()
    _assert_clean_bill(src)
    node = _node(snap, "dsw")
    assert node["collected"] is False and node["kind"] == "switch", node        # the REAL cable-map producer's node
    cables = _uncollected_peer_cables(snap, "acc")
    assert len(cables) == 1
    witness = (f"/cable_map/cables/{cables[0]}", "witness")
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in MEASURES + ("detail",):
        fact = row[field]
        assert fact["state"] == NC and fact["value"] is None, (field, fact)
        assert "cannot account for endpoints behind 1 uncollected neighbour(s)" in fact["reason"], (field, fact)
        assert witness in _refs(fact), field
    assert "may understate" in row["severity"]["reason"]
    assert all("only a lower bound" in row[field]["reason"] for field in MEASURES[1:])
    assert "not a clean bill" in row["detail"]["reason"]
    for field in ("host", "off_scan_gw_vlans"):                         # not measures of the blast radius
        assert row[field]["state"] == PUB and row[field]["value"] == src[field], field
    assert row["style"]["value"]["token"] == "not_observed", row["style"]
    sel = _page(snap, "acc", doc_validator)["failure_impact"]            # one builder, one state on both surfaces
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")
    # the control: the same stored row once the cable map shows that peer collected is a published clean bill
    node["collected"] = True
    clean = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(clean[field]["state"] == PUB and clean[field]["value"] == src[field] for field in MEASURES + ("detail",))
    assert clean["style"]["value"]["token"] == "impact_info"
    assert not any(witness in _refs(clean[field]) for field in MEASURES)


@pytest.mark.parametrize("peer, platform, kind", [
    ("ap1", "cisco AIR-AP2802I-E-K9", "ap"),
    ("sep1", "Cisco IP Phone 8865", "phone"),
])
def test_l_an_uncollected_edge_gear_peer_bounds_nothing_but_any_other_kind_does(topology_validator, peer,
                                                                                platform, kind):
    """analyze.compute_cable_map marks an AP or a phone POSITIVELY as edge gear (platform evidence, ranked below every
    infrastructure kind across observers): what hangs off it depends on the removed switch's own port, which the
    producer already excludes from 'stranded'. So it bounds nothing. Every other kind -- or none -- does."""
    snap, k, src = _downstream((peer, "Switch", platform))
    _assert_clean_bill(src)
    node = _node(snap, peer)
    assert node["collected"] is False and node["kind"] == kind, node           # the REAL producer's classification
    assert _uncollected_peer_cables(snap, "acc") == []
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    assert all(row[field]["state"] == PUB and row[field]["value"] == src[field] for field in MEASURES + ("detail",))
    assert row["style"]["value"]["token"] == "impact_info"
    cable = next(j for j, c in enumerate(snap["cable_map"]["cables"]) if peer in (c["a"], c["b"]))
    witness = (f"/cable_map/cables/{cable}", "witness")
    assert not any(witness in _refs(row[field]) for field in MEASURES)
    # the rule follows the stored kind, never the name: an unknown, missing, unrecognised or collected-device kind
    # on an uncollected node, or a node that does not say it was collected, bounds the row
    for mutate in (lambda n: n.update(kind="unknown"), lambda n: n.pop("kind"), lambda n: n.update(kind="AP"),
                   lambda n: n.update(kind="device"), lambda n: n.pop("collected"),
                   lambda n: n.update(collected="false")):
        held = copy.deepcopy(snap)
        mutate(_node(held, peer))
        row = _topology(held, topology_validator)["failure_impact"]["items"][k]
        for field in MEASURES + ("detail",):
            assert row[field]["state"] == NC, (_node(held, peer), field, row[field])
            assert "cannot account for endpoints behind 1 uncollected neighbour(s)" in row[field]["reason"], field
            assert witness in _refs(row[field]), field


def test_l_a_high_row_facing_an_uncollected_neighbour_keeps_its_lower_bounds(doc_validator, topology_validator):
    """High cannot be understated and a positive count is a lower bound, so both stay published, citing the cable;
    only the zero counts are withheld. The per-VLAN detail lists what was simulated and stays published."""
    snap, k, src = _downstream(host="gw")
    assert src["severity"] == "High" and src["hard"] == src["vlans_impacted"] == 1 and src["stranded"] == 1, src
    assert src["backup"] == src["fhrp"] == 0 and src["off_scan_gw_vlans"] == 0, src
    node = _node(snap, "wan")
    assert node["collected"] is False and node["kind"] == "router", node
    cables = _uncollected_peer_cables(snap, "gw")
    assert len(cables) == 1
    witness = (f"/cable_map/cables/{cables[0]}", "witness")
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in ("severity", "vlans_impacted", "stranded", "hard"):
        fact = row[field]
        assert fact["state"] == PUB and fact["value"] == src[field], (field, fact)
        assert witness in _refs(fact) and "impact_scanned_scope" in fact["caveats"], field
    for field in ("backup", "fhrp"):
        fact = row[field]
        assert fact["state"] == NC and "only a lower bound" in fact["reason"], (field, fact)
        assert "cannot account for endpoints behind 1 uncollected neighbour(s)" in fact["reason"], field
        assert witness in _refs(fact), field
    assert row["detail"]["state"] == PUB and row["detail"]["value"] == src["detail"]
    assert row["style"]["value"]["token"] == "impact_high"
    sel = _page(snap, "gw", doc_validator)["failure_impact"]
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")


@pytest.mark.parametrize("mode, want", [
    ("duplicate_node", NC), ("missing_node", NC), ("unreadable_cable", NC), ("malformed_cables", UV),
    ("absent_cables", NC), ("absent_cable_map", NC), ("null_cable_map", NC), ("failed_cable_map", AU),
])
def test_l_a_neighbour_the_join_cannot_resolve_fails_closed(topology_validator, mode, want):
    """Starting from a row the AP rule leaves published, a far end that joins no single node, a cable row the join
    cannot read (it could name this switch), and a cable list that cannot be read are never assumed collected. A
    cable list that is absent is witnessed by the record it is missing from: the cable map, or the snapshot root
    when there is no cable map at all (a pointer to nothing would be dropped, and the bound with it)."""
    snap, k, src = _downstream(("ap1", "Switch", "cisco AIR-AP2802I-E-K9"))
    _assert_clean_bill(src)
    nodes, cables = snap["cable_map"]["nodes"], snap["cable_map"]["cables"]
    j = next(i for i, c in enumerate(cables) if "ap1" in (c["a"], c["b"]))
    witness = (f"/cable_map/cables/{j}", "witness")
    if mode == "duplicate_node":
        nodes.append(copy.deepcopy(_node(snap, "ap1")))
    elif mode == "missing_node":
        nodes.remove(_node(snap, "ap1"))
    elif mode == "unreadable_cable":
        cables.append(None)
        witness = (f"/cable_map/cables/{len(cables) - 1}", "witness")
    elif mode == "malformed_cables":
        snap["cable_map"]["cables"] = 7
        witness = ("/cable_map/cables", "witness")
    elif mode == "absent_cables":
        del snap["cable_map"]["cables"]
        witness = ("/cable_map", "witness")
    elif mode == "absent_cable_map":
        del snap["cable_map"]
        witness = ("", "witness")
    elif mode == "null_cable_map":
        snap["cable_map"] = None
        witness = ("/cable_map", "witness")
    else:
        snap["assessment_integrity"] = {"cable_map": "failed"}
        witness = ("/cable_map/cables", "witness")
    assert _resolve(snap, witness[0]) is not _MISSING, witness
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in MEASURES + ("detail",):
        fact = row[field]
        assert fact["state"] == want and fact["value"] is None, (field, fact)
        assert witness in _refs(fact), (field, fact["refs"])
        if mode in ("duplicate_node", "missing_node", "unreadable_cable"):
            assert "cannot account for endpoints behind 1 uncollected neighbour(s)" in fact["reason"], fact
            assert "1 of them fail closed" in fact["reason"], fact["reason"]
        else:
            assert "cannot be checked" in fact["reason"], fact["reason"]
    if mode == "failed_cable_map":
        assert ("/assessment_integrity/cable_map", "failure_record") in _refs(row["severity"])
    for field in ("host", "off_scan_gw_vlans"):
        assert row[field]["state"] == PUB and row[field]["value"] == src[field], field


@pytest.mark.parametrize("mode, pointer", [
    ("absent_cable_map", ""), ("null_cable_map", "/cable_map"), ("cable_map_without_cables", "/cable_map"),
])
def test_l_a_high_row_without_a_readable_cable_list_still_marks_its_lower_bounds(doc_validator, topology_validator,
                                                                                mode, pointer):
    """F7: High and a positive count on a row the projection cannot check against the stored cable map are only
    lower bounds, and the witness their cells cite is the one machine-readable mark of that. With no cable map at all
    the cable list has no address of its own, so the record it is missing from (the snapshot root) is cited instead,
    never a pointer that resolves to nothing: that one would be dropped, and the lower bounds would read as exact."""
    snap, k, src = _downstream(host="gw")                        # the REAL producers' rows
    assert src["severity"] == "High" and src["hard"] == src["vlans_impacted"] == 1 and src["stranded"] == 1, src
    assert src["backup"] == src["fhrp"] == 0 and src["off_scan_gw_vlans"] == 0, src
    cables = _uncollected_peer_cables(snap, "gw")
    assert len(cables) == 1
    # the control: with the stored cable map readable, the same row cites the uncollected router's cable, unchanged
    control = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in MEASURES:
        refs = _refs(control[field])
        assert (f"/cable_map/cables/{cables[0]}", "witness") in refs, (field, refs)
        assert not {("", "witness"), ("/cable_map", "witness")} & refs, (field, refs)
    if mode == "absent_cable_map":
        del snap["cable_map"]
    elif mode == "null_cable_map":
        snap["cable_map"] = None
    else:
        del snap["cable_map"]["cables"]
    witness = (pointer, "witness")
    assert _resolve(snap, pointer) is not _MISSING, pointer         # independently: the cited record exists
    row = _topology(snap, topology_validator)["failure_impact"]["items"][k]
    for field in ("severity", "vlans_impacted", "stranded", "hard"):
        fact = row[field]
        assert fact["state"] == PUB and fact["value"] == src[field], (field, fact)
        assert witness in _refs(fact) and "impact_scanned_scope" in fact["caveats"], (field, fact["refs"])
    for field in ("backup", "fhrp"):
        fact = row[field]
        assert fact["state"] == NC and fact["value"] is None, (field, fact)
        assert "only a lower bound" in fact["reason"] and "cannot be checked" in fact["reason"], fact["reason"]
        assert witness in _refs(fact), (field, fact["refs"])
    assert row["detail"]["state"] == PUB and row["detail"]["value"] == src["detail"]   # it lists what was simulated
    for where, fact in _facts(row):
        for ref in fact["refs"]:
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (where, ref)
    sel = _page(snap, "gw", doc_validator)["failure_impact"]          # one builder, one state on both surfaces
    assert sel["state"] == PUB and sel["items"] == [row], sel.get("reason")


@pytest.mark.parametrize("mode", ["present", "absent_cable_map", "cable_map_without_cables"])
def test_l_a_measure_cites_a_witness_exactly_when_a_bound_applies(sample, topology_validator, mode):
    """F7 over every row of the real sample: a failure-impact measure cites a witness exactly when the row is bounded
    (an off-scan count, a cable to an uncollected neighbour, or a cable list that cannot be read), and each one
    resolves. A published measure with no witness is an exact measurement; one that cites a witness is a lower bound.
    The bound is derived here independently of the module."""
    snap = copy.deepcopy(sample)
    unread = None
    if mode == "absent_cable_map":
        del snap["cable_map"]
        unread = ""
    elif mode == "cable_map_without_cables":
        del snap["cable_map"]["cables"]
        unread = "/cable_map"
    items = _topology(snap, topology_validator)["failure_impact"]["items"]
    assert len(items) == len(snap["failure_impact"]) > 0
    bounded = exact = lower = 0
    for k, src in enumerate(snap["failure_impact"]):
        row = items[k]
        assert row["pointer"] == f"/failure_impact/{k}"
        assert _run_config_observed(snap, src["host"]) and "off_scan_gw_vlans" in src, src   # no row hold applies
        assert not src["detail"].startswith(ui.IMPACT_INDETERMINATE_PREFIX), src
        peers = ({unread} if unread is not None
                 else {f"/cable_map/cables/{j}" for j in _uncollected_peer_cables(snap, src["host"])})
        wits = peers | ({f"/failure_impact/{k}/off_scan_gw_vlans"} if src["off_scan_gw_vlans"] else set())
        bounded += bool(wits)
        for field in MEASURES + ("detail",):
            fact = row[field]
            for ref in fact["refs"]:
                assert _resolve(snap, ref["pointer"]) is not _MISSING, (src["host"], field, ref)
            cited = {p for p, role in _refs(fact) if role == "witness"}
            # the detail is never a measure: it cites a bound only where it is withheld as the producer's clean bill
            reach = wits if field in MEASURES else peers
            held = bool(reach) and _understatable(src, field)
            assert fact["state"] == (NC if held else PUB), (src["host"], field, fact)
            assert cited == (reach if (field in MEASURES or held) else set()), (src["host"], field, cited, reach)
            if field in MEASURES and not held:
                assert fact["value"] == src[field], (src["host"], field, fact)
                if cited:
                    lower += 1
                else:
                    exact += 1
    if unread is None:
        # the sample's cable map bounds only core2 (it faces the uncollected router); every other row is exact
        assert bounded == 1 and exact > 0 and lower > 0, (bounded, exact, lower)
    else:
        # no row can be checked against a cable list that cannot be read: no measure is published as exact
        assert bounded == len(items) and exact == 0 and lower > 0, (bounded, exact, lower)


# --------------------------------------------------------------------------------------------------
# (m) two rows naming one unordered host pair: the producer writes one record per pair, so neither is chosen
# --------------------------------------------------------------------------------------------------
STRUCTURAL_CELLS = ("ends", "betweenness", "is_bridge", "pairs_cut", "rank")
STRUCTURAL_JOINS = ("a_nodes", "b_nodes", "host_pair_cable_refs")


def _pair_row(rows, a, b):
    """Independent: the index of the one stored link_centrality row naming the unordered pair {a, b}."""
    hits = [i for i, r in enumerate(rows) if {r["a_host"], r["b_host"]} == {a, b}]
    assert len(hits) == 1, (a, b, hits)
    return hits[0]


def test_m_the_real_producer_writes_one_record_per_unordered_host_pair():
    """The invariant the projection relies on, pinned to analyze.compute_link_centrality: CDP seen from both ends of
    one link, and a second parallel link between the same two switches, still make ONE record for the pair."""
    interfaces = {"s1": {"Gi1": _trunk("Gi1", "s2", "Gi1", "10"), "Gi2": _trunk("Gi2", "s2", "Gi2", "10"),
                         "Gi3": _trunk("Gi3", "s3", "Gi1", "10")},
                  "s2": {"Gi1": _trunk("Gi1", "s1", "Gi1", "10"), "Gi2": _trunk("Gi2", "s1", "Gi2", "10")},
                  "s3": {"Gi1": _trunk("Gi1", "s1", "Gi3", "10")}}
    recs = analyze.compute_link_centrality(interfaces)
    pairs = [frozenset((r["a_host"], r["b_host"])) for r in recs]
    assert sorted(sorted(p) for p in pairs) == [["s1", "s2"], ["s1", "s3"]], recs
    assert len(set(pairs)) == len(pairs)


@pytest.mark.parametrize("mode", ["exact", "reversed", "contradictory"])
def test_m_two_rows_naming_one_host_pair_are_unverified_on_both_surfaces(sample, doc_validator,
                                                                         topology_validator, mode):
    snap = copy.deepcopy(sample)
    rows = snap["link_centrality"]
    first = _pair_row(rows, "core1", "access1")
    src = rows[first]
    assert src["is_bridge"] is True and src["pairs_cut"] > 0, src
    extra = copy.deepcopy(src)
    if mode == "reversed":
        extra.update(a_host=src["b_host"], a_port=src["b_port"], b_host=src["a_host"], b_port=src["a_port"])
    elif mode == "contradictory":
        extra["is_bridge"] = not src["is_bridge"]
    rows.append(extra)
    dup = len(rows) - 1
    pair = {(f"/link_centrality/{first}", "witness"), (f"/link_centrality/{dup}", "witness")}
    topology = _topology(snap, topology_validator)
    fleet = topology["structural_links"]
    assert fleet["state"] == PUB, fleet.get("reason")         # one doubted pair never withholds the other pairs
    assert [it["index"] for it in fleet["items"]] == list(range(len(rows)))
    for j in (first, dup):
        row = fleet["items"][j]
        assert row["pointer"] == f"/link_centrality/{j}"     # each row is kept, at its own index
        for field in STRUCTURAL_CELLS:
            fact = row[field]
            assert fact["state"] == UV and fact["value"] is None, (mode, j, field, fact)
            assert "2 rows in link_centrality name this unordered host pair" in fact["reason"], fact["reason"]
            assert pair <= _refs(fact), (mode, j, field)
        for field in STRUCTURAL_JOINS:                       # nothing is joined for withheld ends
            join = row[field]
            assert join["state"] == UV and join["items"] == [], (mode, j, field, join)
            assert join["reason"] == row["ends"]["reason"], (mode, j, field)
            assert pair <= _refs(join), (mode, j, field)
        assert row["style"]["value"]["token"] == "unverified", row["style"]
    # neither contradicting claim is published
    assert {fleet["items"][j]["is_bridge"]["value"] for j in (first, dup)} == {None}
    for j, row in enumerate(fleet["items"]):                 # every other pair stays the producer's one record
        if j in (first, dup):
            continue
        assert all(row[field]["state"] == PUB for field in STRUCTURAL_CELLS), (j, row["ends"])
        assert not pair & _refs(row["ends"]), j
    # fleet and device agree: both ends' pages hold the same rows, in a published selection
    for host in ("core1", "access1"):
        sel = _page(snap, host, doc_validator)["structural_links"]
        want = _naming(snap["link_centrality"], host, ENDS)
        assert first in want and dup in want, (host, want)
        assert sel["state"] == PUB, (host, sel.get("reason"))
        assert sel["items"] == [fleet["items"][i] for i in want], host
    # the control: the stored single record for that pair is published, its bridge claim included
    clean = _topology(sample, topology_validator)["structural_links"]["items"][first]
    assert all(clean[field]["state"] == PUB for field in STRUCTURAL_CELLS)
    assert clean["is_bridge"]["value"] is True and clean["style"]["value"]["token"] == "structural_bridge"


def test_m_a_device_with_several_distinct_neighbours_stays_published(sample, doc_validator, topology_validator):
    """Per-device uniqueness would be wrong: a device has one record per neighbour, each a distinct pair."""
    want = _naming(sample["link_centrality"], "core1", ENDS)
    pairs = [frozenset((sample["link_centrality"][i]["a_host"], sample["link_centrality"][i]["b_host"]))
             for i in want]
    assert len(want) > 2 and len(set(pairs)) == len(pairs), want
    snap = copy.deepcopy(sample)
    # one more neighbour: a new pair that shares core1 with every existing one
    other = next(h for h in sorted(sample["devices"]) if h != "core1" and frozenset(("core1", h)) not in pairs)
    extra = copy.deepcopy(sample["link_centrality"][want[0]])
    extra.update(a_host="core1", b_host=other)
    snap["link_centrality"].append(extra)
    fleet = _topology(snap, topology_validator)["structural_links"]["items"]
    for base in (sample, snap):
        rows = _naming(base["link_centrality"], "core1", ENDS)
        sel = _page(base, "core1", doc_validator)["structural_links"]
        assert sel["state"] == PUB and [it["index"] for it in sel["items"]] == rows, sel.get("reason")
        for item in sel["items"]:
            assert all(item[field]["state"] == PUB for field in STRUCTURAL_CELLS), item["pointer"]
            assert not any("unordered host pair" in item[field].get("reason", "") for field in STRUCTURAL_CELLS)
    assert _page(snap, "core1", doc_validator)["structural_links"]["items"] == [
        fleet[i] for i in _naming(snap["link_centrality"], "core1", ENDS)]


# --------------------------------------------------------------------------------------------------
# (n) two rows naming one host: the producer writes one row per host, so neither is chosen, on either surface
# --------------------------------------------------------------------------------------------------
IMPACT_CELLS = ("host",) + MEASURES + ("off_scan_gw_vlans", "detail")
IMPACT_DUP = "unverified: 2 rows in failure_impact name this exact host"


@pytest.mark.parametrize("mode", ["exact", "contradictory", "held_copy"])
def test_n_two_rows_naming_one_host_are_unverified_and_agree_on_both_surfaces(sample, doc_validator,
                                                                              topology_validator, mode):
    snap = copy.deepcopy(sample)
    rows = snap["failure_impact"]
    first = _naming(rows, "core1", ("host",))[0]
    src = rows[first]
    assert src["severity"] == "High" and src["off_scan_gw_vlans"] == 0 and src["hard"] > 0, src
    extra = copy.deepcopy(src)
    if mode == "contradictory":                     # the same host, a clean bill instead of a hard partition
        extra.update(severity="Info", vlans_impacted=0, stranded=0, hard=0, backup=0, fhrp=0,
                     detail="No reachability impact from removing this switch (within the scan).")
    elif mode == "held_copy":                       # a copy older than the off-scan marker: its own hold applies too
        del extra["off_scan_gw_vlans"]
    rows.append(extra)
    dup = len(rows) - 1
    pair = {(f"/failure_impact/{first}", "witness"), (f"/failure_impact/{dup}", "witness")}
    fleet = _topology(snap, topology_validator)["failure_impact"]
    assert fleet["state"] == PUB, fleet.get("reason")              # one doubted host never withholds the others
    assert [it["index"] for it in fleet["items"]] == list(range(len(rows)))
    for j in (first, dup):
        row = fleet["items"][j]
        assert row["pointer"] == f"/failure_impact/{j}"            # each row is kept, at its own index
        for field in IMPACT_CELLS:
            fact = row[field]
            if mode == "held_copy" and j == dup and field == "off_scan_gw_vlans":
                assert fact["state"] == NC, fact                     # a missing field carries no value to doubt
                continue
            assert fact["state"] == UV and fact["value"] is None, (mode, j, field, fact)
            assert fact["reason"].startswith(IMPACT_DUP), (mode, j, field, fact["reason"])
            assert pair <= _refs(fact), (mode, j, field)
        join = row["node_refs"]                                      # nothing is joined for a withheld host
        assert join["state"] == UV and join["items"] == [] and join["reason"] == row["host"]["reason"], join
        assert pair <= _refs(join)
        assert row["style"]["value"]["token"] == "unverified", row["style"]
    assert {fleet["items"][j]["severity"]["value"] for j in (first, dup)} == {None}    # neither claim is published
    # unverified wins over a not_collected hold (module precedence); the hold is carried beside, with its witness
    for field in MEASURES + ("detail",):
        copy_reason = fleet["items"][dup][field]["reason"]
        assert ("predates the producer's assessability marker" in copy_reason) == (mode == "held_copy"), copy_reason
        assert "predates" not in fleet["items"][first][field]["reason"], field
    # every other host's row is exactly the sample's
    clean = _topology(sample, topology_validator)["failure_impact"]["items"]
    for j, row in enumerate(fleet["items"][:len(clean)]):
        if j != first:
            assert row == clean[j], j
    # the device page holds the same two rows, cell for cell, in an unverified selection
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == UV and "2 rows" in sel["reason"], sel
    assert sel["items"] == [fleet["items"][first], fleet["items"][dup]]
    # a failed section is analysis_unavailable before any duplicate doubt
    snap["assessment_integrity"] = {"failure_impact": "failed"}
    failed = _topology(snap, topology_validator)["failure_impact"]["items"]
    for j in (first, dup):
        assert all(failed[j][field]["state"] == AU for field in IMPACT_CELLS), j


def test_n_distinct_hosts_stay_published_and_the_key_is_exact_text(sample, doc_validator, topology_validator):
    """The control: one row per host is the producer's shape, so no sample row is doubted and each device row is its
    fleet row. The key is the exact host text the device selection joins by, so a case variant is another host."""
    hosts = [row["host"] for row in sample["failure_impact"]]
    assert len(set(hosts)) == len(hosts)
    fleet = _topology(sample, topology_validator)["failure_impact"]["items"]
    for j, row in enumerate(fleet):
        assert row["host"]["state"] == PUB, j
        assert not any("name this exact host" in row[field].get("reason", "") for field in IMPACT_CELLS), j
    for host in ("core1", "dist1"):
        sel = _page(sample, host, doc_validator)["failure_impact"]
        assert sel["state"] == PUB and sel["items"] == [fleet[_naming(sample["failure_impact"], host, ("host",))[0]]]
    snap = copy.deepcopy(sample)
    first = _naming(snap["failure_impact"], "core1", ("host",))[0]
    variant = copy.deepcopy(snap["failure_impact"][first])
    variant["host"] = "CORE1"
    snap["failure_impact"].append(variant)
    items = _topology(snap, topology_validator)["failure_impact"]["items"]
    assert items[first] == fleet[first]                                  # core1's own row is untouched
    assert items[-1]["host"]["state"] == PUB and items[-1]["host"]["value"] == "CORE1"
    assert not any("name this exact host" in items[-1][field].get("reason", "") for field in IMPACT_CELLS)
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == PUB and sel["items"] == [items[first]], sel.get("reason")


# --------------------------------------------------------------------------------------------------
# (e) a failed or malformed source is withheld as such, never an empty page
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("section, key, mode, want", [
    ("failure_impact", "failure_impact", "phase_failed", AU),
    ("failure_impact", "failure_impact", "phase_failed_fallback", AU),
    ("failure_impact", "failure_impact", "integrity_failed", AU),
    ("failure_impact", "failure_impact", "malformed", UV),
    ("failure_impact", "failure_impact", "absent", NC),
    ("link_centrality", "structural_links", "integrity_failed", AU),
    ("link_centrality", "structural_links", "unavailable", AU),
    ("link_centrality", "structural_links", "malformed", UV),
    ("link_centrality", "structural_links", "absent", NC),
])
def test_e_a_failed_or_malformed_source_is_never_an_empty_page(sample, doc_validator, section, key, mode, want):
    snap = copy.deepcopy(sample)
    if mode == "phase_failed":
        snap["assessment_integrity"] = {"failed_phases": ["Failure Impact"]}
    elif mode == "phase_failed_fallback":
        snap["failure_impact"] = []                              # the _run_phase fallback of 'Failure Impact'
        snap["assessment_integrity"] = {"failed_phases": ["Failure Impact"]}
    elif mode == "integrity_failed":
        snap["assessment_integrity"] = {section: "failed"}
    elif mode == "unavailable":
        snap[section] = {"_unavailable": True}
    elif mode == "malformed":
        snap[section] = 7
    else:
        del snap[section]
    for host in ("core1", "podacc1"):
        sel = _page(snap, host, doc_validator)[key]
        assert sel["state"] == want, (mode, host, sel)
        assert sel["state"] not in (PUB, CBE)
        if want == AU:
            assert any(r["role"] == "failure_record" for r in sel["refs"]), (mode, host, sel["refs"])
            # rows a failed phase left behind are shown, but none of their own cells is a measurement
            fields = ("host", "severity", "stranded", "detail") if key == "failure_impact" else (
                "ends", "is_bridge", "pairs_cut", "rank")
            for item in sel["items"]:
                assert all(item[f]["state"] == AU for f in fields), (mode, host, item["pointer"])


# --------------------------------------------------------------------------------------------------
# a selection is never a re-simulation: the projection names no topology producer or model helper
# --------------------------------------------------------------------------------------------------
#: The producers whose stored rows the topology and device pages select, and the model helpers they compute over.
SIMULATION_NAMES = frozenset({
    "compute_failure_impact", "compute_link_centrality", "build_network_model", "_topology_adjacency",
    "compute_topology_links", "compute_cable_map", "compute_causality_chains", "_vlan_components", "_link_carries",
    "_carry", "_link_has_vlan_evidence"})
_DYNAMIC_LOOKUPS = ("getattr", "hasattr", "__import__", "import_module", "vars", "globals", "eval", "exec")


def _reachable_names(node):
    """Every identifier code under `node` can reach a callable by: names, attributes, imported names and aliases,
    and the string arguments of a dynamic lookup."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.alias):
            out.update(n for n in (sub.name.rsplit(".", 1)[-1], sub.asname) if n)
        if isinstance(sub, ast.Call) and getattr(sub.func, "id", getattr(sub.func, "attr", "")) in _DYNAMIC_LOOKUPS:
            out.update(a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
    return out


def test_the_projection_source_never_names_a_topology_producer():
    source = pathlib.Path(ui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not _reachable_names(tree) & SIMULATION_NAMES
    # no module object through which a producer could be reached under another spelling
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("cisco_toolkit.analyze") for a in node.names), ast.unparse(node)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module == "cisco_toolkit" and any(a.name == "analyze" for a in node.names)), (
                ast.unparse(node))
    assert not {"getattr", "__import__", "import_module", "eval", "exec"} & _reachable_names(tree)
    # one level down: the analyze functions the projection does import name no producer either
    imported = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                and node.module == "cisco_toolkit.analyze" for a in node.names}
    owner = ast.parse(pathlib.Path(analyze.__file__).read_text(encoding="utf-8"))
    functions = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
    checked = [name for name in sorted(imported) if name in functions]
    assert checked, imported
    for name in checked:
        assert not _reachable_names(functions[name]) & SIMULATION_NAMES, name
    # the scan is able to fail: a direct call, an aliased import and a dynamic lookup are each caught
    for mutant in ("\n_x = compute_failure_impact\n",
                   "\nfrom cisco_toolkit.analyze import build_network_model as _bnm\n",
                   "\nimport cisco_toolkit.analyze as _a\n_y = _a.compute_link_centrality\n",
                   "\n_z = getattr(_a, '_vlan_components')\n"):
        assert _reachable_names(ast.parse(source + mutant)) & SIMULATION_NAMES, mutant


# --------------------------------------------------------------------------------------------------
# (f) the document defines every caveat its new sections carry, where they carry it
# --------------------------------------------------------------------------------------------------
def test_new_sections_cite_only_limitations_their_document_defines(sample, doc_validator):
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}   # any failure adds the one-hop caveat
    snap["collection_completeness"]["devices"] = copy.deepcopy(BLIND)     # blind spots add the fleet qualifier
    doc = ui.project_device(snap, "core1")
    assert not list(doc_validator.iter_errors(doc))
    lims = {lim["id"]: lim["applies_to"] for lim in doc["device"]["limitations"]}
    seen = set()
    for section in SECTIONS:
        assert doc["device"][section]["state"] == PUB, section
        for where, fact in _facts(doc["device"][section], "/device/" + section):
            for cav in fact.get("caveats", ()):
                seen.add(cav)
                assert cav in lims, (where, cav)
                assert any(where == p or where.startswith(p + "/") for p in lims[cav]), (where, cav)
    assert {"row_selection_by_exact_key", "topology_scanned_model", "impact_scanned_scope",
            "one_hop_failure_attribution", "fleet_lists_exclude_blind_devices"} <= seen
