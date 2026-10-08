"""Device-level failure impact and structural links (contract gaps G10/G11): selections, never re-simulation.

A device page selects the stored ``failure_impact`` row and the stored ``link_centrality`` rows that name the device
by exact host, and builds each with the fleet topology's own row builder, so a device row IS the fleet row. The page
never re-simulates, and an empty selection is never a clean result:

* ``analyze.compute_failure_impact`` writes one row per host of its network model (every scanned host), so a device
  with no row was not simulated -- that is a blind spot, never "no impact";
* ``analyze.compute_link_centrality`` keeps only CDP/LLDP links whose two ends were both scanned, so a device absent
  from it may face an unscanned peer or lack CDP/LLDP evidence -- never proof that it has no inter-switch link.

Every value is checked against an INDEPENDENT lookup in the snapshot, never the module's own join.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze
from cisco_toolkit import ui_projection as ui

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
SECTIONS = ("failure_impact", "structural_links")
ENDS = ("a_host", "b_host")


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


def _naming(rows, host, fields):
    """Independent selection: the indices of the stored rows that name `host` exactly in any of `fields`."""
    return [i for i, r in enumerate(rows) if isinstance(r, dict) and any(r.get(f) == host for f in fields)]


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


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


# --------------------------------------------------------------------------------------------------
# the closed schema and the module tables carry both selections
# --------------------------------------------------------------------------------------------------
def test_device_page_schema_and_tables_carry_both_selections():
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
                    "projection_owned_verdicts"):
            assert "/device/" + section in cited[lid], (lid, section)
    assert tuple(cited["impact_scanned_scope"]) == ("/device/failure_impact",)
    n = len(ui.DEVICE_LIMITATIONS) + sum(1 for lim in ui.LIMITATIONS if lim["id"] in cited)
    lims = page["properties"]["limitations"]
    assert lims["minItems"] == lims["maxItems"] == n


# --------------------------------------------------------------------------------------------------
# (a) a simulated device selects exactly its fleet row; (d) structural rows from either end, nothing else
# --------------------------------------------------------------------------------------------------
def test_a_simulated_device_selects_exactly_its_fleet_rows(sample, doc_validator):
    topology = ui.project(sample)["topology"]
    impact, structural = topology["failure_impact"]["items"], topology["structural_links"]["items"]
    assert [it["index"] for it in impact] == list(range(len(sample["failure_impact"])))
    assert [it["index"] for it in structural] == list(range(len(sample["link_centrality"])))
    for host in sorted(sample["devices"]):
        page = _page(sample, host, doc_validator)
        rows = _naming(sample["failure_impact"], host, ("host",))
        assert len(rows) == 1, host                                 # the producer writes one row per scanned host
        sel = page["failure_impact"]
        assert sel["state"] == PUB, (host, sel.get("reason"))
        assert sel["subject"] == "/failure_impact"
        assert sel["items"] == [impact[rows[0]]], host               # the fleet row itself, same pointer and values
        row = sel["items"][0]
        assert row["pointer"] == f"/failure_impact/{rows[0]}"
        assert row["host"]["value"] == host
        for field in ("severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp", "off_scan_gw_vlans", "detail"):
            assert row[field]["value"] == sample["failure_impact"][rows[0]][field], (host, field)
            assert row[field]["subject"] == f"/failure_impact/{rows[0]}/{field}"
        assert "row_selection_by_exact_key" in sel["caveats"]
        want = _naming(sample["link_centrality"], host, ENDS)
        links = page["structural_links"]
        assert want and links["state"] == PUB, (host, links.get("reason"))
        assert links["subject"] == "/link_centrality"
        assert links["items"] == [structural[i] for i in want], host


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
    assert _page(snap, "core2", doc_validator)["failure_impact"]["state"] == PUB


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
    other = _page(snap, "core2", doc_validator)["failure_impact"]
    assert other["state"] == PUB and [it["host"]["value"] for it in other["items"]] == ["core2"]
    snap["failure_impact"] = []                                  # an empty simulation, no failure recorded
    sel = _page(snap, "core1", doc_validator)["failure_impact"]
    assert sel["state"] == NC and "an absent row is not 'no impact'" in sel["reason"]


def test_b_no_device_selection_is_ever_a_clean_absence(sample, doc_validator):
    hosts = set(sample["devices"]) | {n["host"] for n in sample["cable_map"]["nodes"]}
    for host in sorted(hosts):
        page = _page(sample, host, doc_validator)
        for section in SECTIONS:
            sel = page[section]
            assert sel["state"] != CBE, (host, section, sel.get("reason"))
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
            assert missing in sel["reason"] and "may be incomplete" in sel["reason"], (section, sel["reason"])
            assert witness in _refs(sel), section
        else:
            assert sel["state"] == PUB, (section, sel.get("reason"))
            assert witness not in _refs(sel), section


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


def test_the_device_page_never_recomputes_the_simulation(sample, monkeypatch):
    expected = ui.project_device(sample, "core1")

    def forbidden(*_a, **_kw):
        raise AssertionError("a device page selects stored rows; it never re-simulates")

    for name in ("compute_failure_impact", "build_network_model", "compute_link_centrality",
                 "compute_topology_links", "_topology_adjacency", "compute_cable_map"):
        monkeypatch.setattr(analyze, name, forbidden)
    assert ui.project_device(sample, "core1") == expected


# --------------------------------------------------------------------------------------------------
# (f) the document defines every caveat its new sections carry, where they carry it
# --------------------------------------------------------------------------------------------------
def test_new_sections_cite_only_limitations_their_document_defines(sample, doc_validator):
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}   # any failure adds the one-hop caveat
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
            "one_hop_failure_attribution"} <= seen
