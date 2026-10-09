"""G21 -- punch-list facet totals: row counts by severity, category and inventory device.

``findings.facets`` publishes, for each key of the owner's closed vocabulary and in its order, the number of stored
punch-list rows with that severity or category (``analyze.compute_punchlist_facets``), and, as a roster list with
its own state, for each inventory device, the per-device rollup (G09, ``analyze.compute_device_findings``) summed.
Coverage honesty:

* a missing punch list is not_collected, an empty one collected_but_empty, a failed one analysis_unavailable;
* the owner's buckets are published only as an exact partition of the stored rows (every row once, in the bucket
  its own field names, as many rows as the row list and its published total), else the facet is unverified, and a
  row total that is not published leaves nothing to reconcile with, so the facet is unverified too;
* a category is folded from one engine section (``analyze.PUNCH_CATEGORY_SECTION``, often not a punch-list input):
  while that section failed, could not be read or was not collected, the category's zero takes its state and a
  positive count is a lower bound carrying ``finding_facet_source_incomplete``; a row of any category can carry any
  severity, so every severity bucket follows the same rule while any category source is incomplete;
* while a fleet qualification applies (blind devices, devices without a captured running-config), a positive count
  is a lower bound carrying that caveat and its witnesses, and a zero is not_collected, never a clean result;
* a device bucket is the device's own rollup (same state, reason and caveats as its inventory row), and the device
  list takes the roster's own state: an absent or unreadable devices map is withheld, never an empty roster.

Every expected number is recounted here from the snapshot, never taken from the module's own fold. The stored
engine-built sample fleet and the committed golden snapshot are read as they are; neither is regenerated.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import pathlib
from types import MappingProxyType

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as uip
from test_ui_projection_decision_rollups import HOSTS, _snapshot as _rollup_snapshot

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORED = {"sample_fleet": ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json",
          "golden": ROOT / "tests" / "golden" / "snapshot.json"}
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
BASIS_REF = {"pointer": "/punchlist", "role": "basis"}
OWNER_FACETS = (("severity", analyze.PUNCH_SEVERITIES), ("category", analyze.PUNCH_CATEGORIES))
SOURCE_CAVEAT = "finding_facet_source_incomplete"
#: Every distinct category source section, read from the owner map (never a hand list).
SOURCES = tuple(sorted(set(analyze.PUNCH_CATEGORY_SECTION.values())))


def _stored(name):
    return json.loads(STORED[name].read_text(encoding="utf-8"))


_GOLDEN = _stored("golden")


def _snapshot(rows=None):
    """The decision-rollup synthetic snapshot plus every category source section it does not carry, each present and
    empty in the shape the committed golden publishes it, so no category is held for a missing source."""
    snap = _rollup_snapshot(rows)
    for section in SOURCES:
        snap.setdefault(section, type(_GOLDEN[section])())
    return snap


def _rows():
    return [
        {"severity": "High", "category": "Security", "devices": ["edgeA", "edgeA", "edgeB"]},
        {"severity": "Critical", "category": "L3", "devices": ["edgeA"]},
        {"severity": "Info", "category": "Coverage", "devices": ["edgeB"]},
        {"severity": "High", "category": "Security", "devices": ["edgeA"]},
        {"severity": "Low", "category": "STP", "devices": []},
    ]


def _captured_sample():
    """The stored sample fleet with every device's running-config captured: a security row and positive capture
    custody (software_risk config_assessable) for each configless device, so no fleet qualification applies and
    the device facet can publish those devices too. Returns the snapshot and the patched hosts."""
    snap = _stored("sample_fleet")
    lacking = sorted(host for host in snap["devices"] if host not in snap["security"])
    assert lacking
    for host in lacking:
        snap["security"][host] = deepcopy(snap["security"]["core1"])
    patched = 0
    for row in snap["software_risk"]["per_device"]:
        if row["host"] in lacking:
            row["config_assessable"] = True
            patched += 1
    assert patched == len(lacking)
    return snap, lacking


def _facets(snap):
    return uip.project_findings(snap)["facets"]


def _by_key(buckets):
    keys = [bucket["k"] for bucket in buckets]
    assert len(set(keys)) == len(keys), keys
    return {bucket["k"]: bucket["n"] for bucket in buckets}


def _devices(facets):
    """The device facet's buckets, by device (the list's own state is checked where it matters)."""
    return _by_key(facets["device"]["items"])


def _recount(rows, facet):
    return Counter(row[facet] for row in rows)


def _without_row_witnesses(refs):
    return [ref for ref in refs if not (ref["role"] == "witness" and ref["pointer"].startswith("/punchlist/"))]


# --------------------------------------------------------------------------------------------------
# F0 -- vocabularies, schema and registration
# --------------------------------------------------------------------------------------------------
def test_f0_facet_keys_are_the_owner_vocabularies_and_the_schema_closes_them():
    assert uip.FINDING_CATEGORIES == analyze.PUNCH_CATEGORIES == tuple(analyze._PUNCH_EVIDENCE_POLICY)
    assert uip.SEVERITIES == analyze.PUNCH_SEVERITIES
    assert uip.PUNCH_CATEGORY_SECTION is analyze.PUNCH_CATEGORY_SECTION        # the owner's map, never a copy
    assert set(uip.PUNCH_CATEGORY_SECTION) == set(uip.FINDING_CATEGORIES)
    assert uip.FINDING_FACETS == ("severity", "category", "device")
    assert tuple(name for name, _keys in uip._OWNER_FACETS) + ("device",) == uip.FINDING_FACETS
    assert [(name, tuple(keys)) for name, keys in uip._OWNER_FACETS] == list(OWNER_FACETS)
    schema = uip.ui_projection_schema()
    Draft202012Validator.check_schema(schema)
    d = schema["$defs"]
    assert d["Findings"]["required"] == ["total", "headline_axis_index", "rows", "facets"]
    assert d["Findings"]["properties"]["facets"] == {"$ref": "#/$defs/FindingFacets"}
    facets = d["FindingFacets"]
    assert facets["additionalProperties"] is False and facets["required"] == list(uip.FINDING_FACETS)
    for facet, row, keys in (("severity", "SeverityFacetRow", uip.SEVERITIES),
                             ("category", "CategoryFacetRow", uip.FINDING_CATEGORIES)):
        prop = facets["properties"][facet]
        assert prop == {"type": "array", "minItems": len(keys), "maxItems": len(keys), "items": {"$ref": f"#/$defs/{row}"}}
        assert d[row]["properties"]["k"] == {"type": "string", "enum": list(keys)}
        assert d[row]["properties"]["n"] == {"$ref": "#/$defs/CountFact"}
        assert d[row]["required"] == ["k", "n"] and d[row]["additionalProperties"] is False
    # the device facet is a list with its own state, of the same shape as every other primary list
    assert facets["properties"]["device"] == {"$ref": "#/$defs/DeviceFacetList"}
    assert d["DeviceFacetList"] == uip._list_def("DeviceFacetList", {"$ref": "#/$defs/DeviceFacetRow"})
    assert d["DeviceFacetRow"]["properties"] == {"k": {"type": "string"}, "n": {"$ref": "#/$defs/CountFact"}}
    vocab = uip.project({})["vocab"]
    assert vocab["unranked"]["punch_category"]["tokens"] == list(uip.FINDING_CATEGORIES)
    assert SOURCE_CAVEAT in vocab["unranked"]["limitation_id"]["tokens"]
    lims = {lim["id"]: lim for lim in uip.LIMITATIONS}
    for cid in ("one_hop_failure_attribution", "fleet_lists_exclude_blind_devices",
                "findings_without_running_config", "projection_owned_verdicts"):
        assert "/findings/facets" in lims[cid]["applies_to"], cid
    assert "/findings/facets/device" in lims["device_findings_scope"]["applies_to"]
    assert "need not sum" in lims["device_findings_scope"]["text"]
    assert lims[SOURCE_CAVEAT]["owner"] == "analyze.PUNCH_CATEGORY_SECTION"
    assert lims[SOURCE_CAVEAT]["applies_to"] == ("/findings/facets/severity", "/findings/facets/category")
    assert SOURCE_CAVEAT not in uip.DEVICE_CITED_LIMITATIONS


# --------------------------------------------------------------------------------------------------
# F1 -- the stored engine data: owner order, independent recounts, reconciliation, qualification
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", tuple(STORED))
def test_f1_stored_engine_snapshots_publish_recounted_facets_that_reconcile_with_the_rows(name):
    snap = _stored(name)
    rows = snap["punchlist"]
    assert len(rows) > 20                                           # the real stored producer output
    # every category source is present in the real stored output, so no category is held for its source
    assert all(ssot.abstention_reason(snap, section) not in (NC, AU) for section in SOURCES)
    payload = uip.project(snap)
    findings = payload["findings"]
    assert findings["rows"]["state"] == PUB and findings["total"]["state"] == PUB
    assert findings["total"]["value"] == len(rows) == len(findings["rows"]["items"])
    lacking = sorted(host for host in snap["devices"] if host not in snap["security"])
    assert lacking, "both stored snapshots carry configless devices: the qualification path is exercised"
    for facet, keys in OWNER_FACETS:
        buckets = findings["facets"][facet]
        assert [bucket["k"] for bucket in buckets] == list(keys)
        expected = _recount(rows, facet)
        published = 0
        for bucket in buckets:
            n = bucket["n"]
            assert n["subject"] is None and n["basis"] == f"analyze.compute_punchlist_facets:stored punch-list rows by {facet}"
            assert n["refs"][0] == BASIS_REF
            witnesses = sorted(ref["pointer"] for ref in n["refs"] if ref["role"] == "witness")
            assert witnesses == sorted(f"/devices/{host}" for host in lacking), (facet, bucket["k"])
            if expected[bucket["k"]]:
                assert (n["state"], n["value"]) == (PUB, expected[bucket["k"]]), (facet, bucket["k"])
                assert "findings_without_running_config" in n["caveats"] and SOURCE_CAVEAT not in n["caveats"]
                published += n["value"]
            else:                                                   # a zero over a qualified list is no clean result
                assert (n["state"], n["value"]) == (NC, None), (facet, bucket["k"])
                assert "not a clean result" in n["reason"] and "security row" in n["reason"]
        assert published == len(rows) == findings["total"]["value"]      # the facet reconciles with the row count
    # the device facet is the inventory roster's own rollup, summed, in the roster's own list state
    device_list, roster = findings["facets"]["device"], payload["inventory"]["devices"]["rows"]
    assert (device_list["state"], device_list["subject"], device_list["refs"]) == (
        roster["state"], roster["subject"], roster["refs"])
    assert device_list["state"] == PUB and device_list["subject"] == "/devices"
    assert "device_findings_scope" in device_list["caveats"]
    device = _devices(findings["facets"])
    inventory = {row["host"]: row["findings"]["by_severity"] for row in roster["items"]}
    assert list(device) == sorted(inventory) == sorted(snap["devices"])
    carried_row_witnesses = False
    for host, n in device.items():
        rollup = inventory[host]
        assert n["state"] == rollup["state"], host
        # the rollup's basis, custody and qualification refs, without one witness per stored row naming the device
        assert n["refs"] == _without_row_witnesses(rollup["refs"]) and BASIS_REF in n["refs"], host
        carried_row_witnesses |= len(rollup["refs"]) > len(n["refs"])
        if host in lacking:
            assert n["state"] == NC, host
        if n["state"] == PUB:
            assert n["value"] == sum(rollup["value"].values()) == sum(1 for row in rows if host in row["devices"])
            assert n.get("caveats") == rollup.get("caveats") and "device_findings_scope" in n["caveats"]
        else:
            assert n["value"] is None and n["reason"] == rollup["reason"]
    assert carried_row_witnesses                                    # non-vacuous: the trim removed real witnesses
    assert any(n["state"] == PUB and n["value"] > 0 for n in device.values())     # non-vacuous
    schema = uip.ui_projection_schema()
    Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                          "$ref": "#/$defs/Findings"}).validate(findings)


def test_f1_with_every_running_config_captured_zeros_publish_and_nothing_is_qualified():
    snap, patched = _captured_sample()
    findings = uip.project_findings(snap)
    assert "caveats" not in findings["rows"] or not {"findings_without_running_config",
                                                    "fleet_lists_exclude_blind_devices"} & set(findings["rows"]["caveats"])
    rows = snap["punchlist"]
    for facet, keys in OWNER_FACETS:
        expected = _recount(rows, facet)
        values = [(bucket["k"], bucket["n"]["state"], bucket["n"]["value"]) for bucket in findings["facets"][facet]]
        assert values == [(key, PUB, expected[key]) for key in keys], facet
        assert sum(value for _k, _s, value in values) == len(rows)
        assert any(value == 0 for _k, _s, value in values)        # a measured zero over a complete list is published
        for bucket in findings["facets"][facet]:
            assert bucket["n"]["refs"] == [BASIS_REF] and "caveats" not in bucket["n"]
    # the same control is consistent across facets: the devices given a running-config publish their own counts
    device = _devices(findings["facets"])
    for host in patched:
        assert (device[host]["state"], device[host]["value"]) == (
            PUB, sum(1 for row in rows if host in row["devices"])), host


# --------------------------------------------------------------------------------------------------
# F2 -- absence, emptiness and failure are never a count
# --------------------------------------------------------------------------------------------------
def test_f2_synthetic_partition_publishes_every_key_and_the_device_rollup():
    snap = _snapshot(_rows())
    payload = uip.project(snap)
    facets = payload["findings"]["facets"]
    assert list(facets) == list(uip.FINDING_FACETS)
    severity = {k: (n["state"], n["value"]) for k, n in _by_key(facets["severity"]).items()}
    assert severity == {"Critical": (PUB, 1), "High": (PUB, 2), "Medium": (PUB, 0), "Low": (PUB, 1), "Info": (PUB, 1)}
    category = _by_key(facets["category"])
    assert list(category) == list(analyze.PUNCH_CATEGORIES)
    assert {k: n["value"] for k, n in category.items() if n["value"]} == {"Security": 2, "L3": 1, "Coverage": 1,
                                                                          "STP": 1}
    assert all(n["state"] == PUB and "caveats" not in n for n in category.values())
    assert facets["device"]["state"] == PUB
    device = _devices(facets)
    assert list(device) == sorted(HOSTS)
    assert {k: (n["state"], n["value"]) for k, n in device.items()} == {
        "edgeA": (PUB, 3), "edgeB": (PUB, 2), "empty": (PUB, 0)}
    assert not [ref for n in device.values() for ref in n["refs"] if ref["pointer"].startswith("/punchlist/")]
    assert all(BASIS_REF in n["refs"] for n in device.values())
    assert "device_findings_scope" in device["empty"]["caveats"]
    assert payload["findings"]["total"]["value"] == 5
    Draft202012Validator(uip.ui_projection_schema()).validate(payload)


def test_f2_an_empty_punch_list_is_collected_but_empty_never_a_zero_count():
    facets = _facets(_snapshot([]))
    for facet, keys in OWNER_FACETS:
        buckets = facets[facet]
        assert [bucket["k"] for bucket in buckets] == list(keys)
        for bucket in buckets:
            n = bucket["n"]
            assert (n["state"], n["value"]) == (CBE, None)
            assert "carries no row" in n["reason"] and "not a blind spot" in n["reason"]
            assert n["refs"] == [BASIS_REF]
    # the captured devices keep their own measured rollup: zero rows name them
    assert {k: (n["state"], n["value"]) for k, n in _devices(facets).items()} == {host: (PUB, 0) for host in HOSTS}


def test_f2_a_missing_punch_list_is_not_collected_everywhere():
    snap = _snapshot(_rows())
    del snap["punchlist"]
    facets = _facets(snap)
    buckets = [(facet, bucket) for facet, _keys in OWNER_FACETS for bucket in facets[facet]]
    buckets += [("device", bucket) for bucket in facets["device"]["items"]]
    for facet, bucket in buckets:
        n = bucket["n"]
        assert (n["state"], n["value"]) == (NC, None), (facet, bucket["k"])
        assert n["reason"].startswith("not collected")
        assert BASIS_REF not in n["refs"]                         # the absent section is never cited as a basis
    assert [bucket["k"] for bucket in facets["device"]["items"]] == sorted(HOSTS)


@pytest.mark.parametrize("retained", [False, True])
def test_f2_a_failed_punch_list_phase_is_unavailable_with_its_failure_record(retained):
    snap = _snapshot(_rows() if retained else [])
    snap["assessment_integrity"] = {"failed_phases": ["Migration Punch-List"]}
    assert ssot.abstention_reason(snap, "punchlist") == AU
    facets = _facets(snap)
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    buckets = [(facet, bucket) for facet, _keys in OWNER_FACETS for bucket in facets[facet]]
    buckets += [("device", bucket) for bucket in facets["device"]["items"]]
    for facet, bucket in buckets:
        assert (bucket["n"]["state"], bucket["n"]["value"]) == (AU, None), (facet, bucket["k"])
        assert record in bucket["n"]["refs"], (facet, bucket["k"])


def test_f2_a_failed_punch_list_input_is_unavailable_even_with_stored_rows():
    snap = _snapshot(_rows())
    snap["health_scores"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    facets = _facets(snap)
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    buckets = [bucket for facet, _keys in OWNER_FACETS for bucket in facets[facet]] + facets["device"]["items"]
    for bucket in buckets:
        assert bucket["n"]["state"] == AU and record in bucket["n"]["refs"], bucket["k"]


# --------------------------------------------------------------------------------------------------
# F3 -- a fleet qualification makes a positive count a lower bound and a zero no clean result
# --------------------------------------------------------------------------------------------------
def test_f3_a_device_without_running_config_qualifies_every_owner_bucket():
    snap = _snapshot(_rows())
    del snap["security"]["edgeB"]
    facets = _facets(snap)
    witness = {"pointer": "/devices/edgeB", "role": "witness"}
    for facet, _keys in OWNER_FACETS:
        for bucket in facets[facet]:
            n = bucket["n"]
            assert witness in n["refs"], (facet, bucket["k"])
            if n["state"] == PUB:
                assert n["value"] > 0 and n["caveats"] == ["findings_without_running_config"]
            else:
                assert (n["state"], n["value"]) == (NC, None), (facet, bucket["k"])
                assert "not a clean result" in n["reason"] and "no security row" in n["reason"]
    assert _by_key(facets["severity"])["Medium"]["state"] == NC
    assert _by_key(facets["severity"])["High"]["value"] == 2
    device = _devices(facets)
    assert device["edgeB"]["state"] == NC and device["edgeA"]["state"] == PUB


def test_f3_a_blind_device_qualifies_the_buckets_and_joins_the_device_facet_as_a_blind_spot():
    snap = _snapshot(_rows())
    snap["collection_completeness"]["devices"] = [
        {"host": "ghost", "status": "not collected", "missing": ["interface status"], "data_quality": 0}]
    snap["collection_completeness"]["summary"]["inventory"] += 1
    facets = _facets(snap)
    witness = {"pointer": "/collection_completeness/devices/0", "role": "witness"}
    for facet, _keys in OWNER_FACETS:
        for bucket in facets[facet]:
            n = bucket["n"]
            assert witness in n["refs"]
            if n["state"] == PUB:
                assert "fleet_lists_exclude_blind_devices" in n["caveats"]
            else:
                assert n["state"] == NC and "collection_completeness lists 1 device" in n["reason"]
    device = _devices(facets)
    assert list(device) == sorted(HOSTS + ("ghost",))
    assert device["ghost"]["state"] == NC and witness in device["ghost"]["refs"]


# --------------------------------------------------------------------------------------------------
# F4 -- the owner's partition is admitted only when it is exact and has a published total to agree with
# --------------------------------------------------------------------------------------------------
def test_f4_a_legacy_category_withholds_only_the_category_facet():
    rows = _rows()
    rows[2]["category"] = "Legacy name"
    facets = _facets(_snapshot(rows))
    for bucket in facets["category"]:
        assert bucket["n"]["state"] == UV and "outside the owner's closed vocabulary" in bucket["n"]["reason"]
    assert [bucket["n"]["state"] for bucket in facets["severity"]] == [PUB] * len(uip.SEVERITIES)
    legacy = [{k: v for k, v in row.items() if k != "category"} for row in _rows()]
    facets = _facets(_snapshot(legacy))                        # rows written before categories existed
    assert {bucket["n"]["state"] for bucket in facets["category"]} == {UV}
    assert sum(bucket["n"]["value"] for bucket in facets["severity"]) == len(legacy)


def test_f4_an_unreadable_row_or_severity_publishes_no_partial_counts():
    rows = _rows()
    rows[1]["severity"] = "critical"
    facets = _facets(_snapshot(rows))
    assert {bucket["n"]["state"] for bucket in facets["severity"]} == {UV}
    assert {bucket["n"]["state"] for bucket in facets["category"]} == {PUB}
    assert {bucket["n"]["state"] for bucket in facets["device"]["items"]} == {UV}   # the G09 fold refuses it too
    facets = _facets(_snapshot(_rows() + [None]))
    for facet, _keys in OWNER_FACETS:
        assert {bucket["n"]["state"] for bucket in facets[facet]} == {UV}, facet
    assert {bucket["n"]["state"] for bucket in facets["device"]["items"]} == {UV}


def test_f4_an_owner_fault_is_unverified_and_names_the_owner(monkeypatch):
    def broken(_rows):
        raise ValueError("synthetic owner failure")

    monkeypatch.setattr(uip, "compute_punchlist_facets", broken)
    facets = _facets(_snapshot(_rows()))
    for facet, _keys in OWNER_FACETS:
        for bucket in facets[facet]:
            assert bucket["n"]["state"] == UV and "analyze.compute_punchlist_facets" in bucket["n"]["reason"]
    assert {bucket["n"]["state"] for bucket in facets["device"]["items"]} == {PUB}


def _mutated_owner(monkeypatch, edit):
    owner = analyze.compute_punchlist_facets

    def mutated(rows):
        folded = owner(rows)
        edit(folded)
        return folded

    monkeypatch.setattr(uip, "compute_punchlist_facets", mutated)


@pytest.mark.parametrize("edit", [
    lambda f: f["severity"]["indices"]["High"].pop(),                              # a row dropped
    lambda f: f["severity"]["indices"]["Medium"].append(0),                        # a row counted twice
    lambda f: f["severity"]["indices"].update(High=[0], Medium=[3]),               # a row in the wrong bucket
    lambda f: f["severity"]["indices"].update(High=[0, True]),                     # a non-integer index
    lambda f: f["severity"]["indices"].update(High=[0, 3, 99]),                    # an index outside the list
    lambda f: f["severity"].update(indices=dict(reversed(list(f["severity"]["indices"].items())))),   # key order
    lambda f: f["severity"]["indices"].pop("Info"),                                # a key missing
    lambda f: f["severity"]["indices"].update(Severe=[]),                          # a key invented
    lambda f: f["severity"]["indices"].update(High=(0, 3)),                        # not a list
    lambda f: f["severity"].update(problem="synthetic refusal"),
    lambda f: f.update(severity=None),
])
def test_f4_an_owner_partition_that_does_not_reconcile_is_unverified(monkeypatch, edit):
    _mutated_owner(monkeypatch, edit)
    facets = _facets(_snapshot(_rows()))
    for bucket in facets["severity"]:
        n = bucket["n"]
        assert (n["state"], n["value"]) == (UV, None), bucket["k"]
        assert n["reason"].startswith("unverified: the engine's severity")
    assert {bucket["n"]["state"] for bucket in facets["category"]} == {PUB}       # the other facet keeps its verdict


def test_f4_an_owner_row_count_that_disagrees_with_the_list_withholds_both_owner_facets(monkeypatch):
    _mutated_owner(monkeypatch, lambda f: f.update(n_rows=4))
    facets = _facets(_snapshot(_rows()))
    for facet, _keys in OWNER_FACETS:
        for bucket in facets[facet]:
            assert bucket["n"]["state"] == UV and "5 stored punch-list rows" in bucket["n"]["reason"], facet
    assert {bucket["n"]["state"] for bucket in facets["device"]["items"]} == {PUB}


def test_f4_a_published_total_that_disagrees_with_the_rows_withholds_both_owner_facets(monkeypatch):
    owner = ssot.compute_schema_census

    def inflated(snap):
        census = owner(snap)
        for row in census["sections"]:
            if row["key"] == "punchlist":
                row["count"] += 1
        return census

    monkeypatch.setattr(ssot, "compute_schema_census", inflated)
    findings = uip.project_findings(_snapshot(_rows()))
    assert (findings["total"]["state"], findings["total"]["value"]) == (PUB, 6)
    for facet, _keys in OWNER_FACETS:
        for bucket in findings["facets"][facet]:
            assert bucket["n"]["state"] == UV and "published row total is 6" in bucket["n"]["reason"]


@pytest.mark.parametrize("break_census", [
    lambda owner: (lambda snap: (_ for _ in ()).throw(ValueError("synthetic census failure"))),   # a census fault
    lambda owner: (lambda snap: {**owner(snap), "sections": [
        {**row, "count": "5"} if row.get("key") == "punchlist" else row for row in owner(snap)["sections"]]}),
])
def test_f4_a_total_that_is_not_published_leaves_nothing_to_reconcile_with(monkeypatch, break_census):
    """The row list stays published, but its total is withheld (a census fault, or a count that is not a count):
    the facets are never checked against the rows alone and published beside an unverified total."""
    monkeypatch.setattr(ssot, "compute_schema_census", break_census(ssot.compute_schema_census))
    findings = uip.project_findings(_snapshot(_rows()))
    assert findings["rows"]["state"] == PUB and findings["total"]["state"] == UV
    for facet, _keys in OWNER_FACETS:
        for bucket in findings["facets"][facet]:
            n = bucket["n"]
            assert (n["state"], n["value"]) == (UV, None), (facet, bucket["k"])
            assert "row total is unverified" in n["reason"] and "cannot be reconciled" in n["reason"]
    assert {bucket["n"]["state"] for bucket in findings["facets"]["device"]["items"]} == {PUB}   # its own owner


# --------------------------------------------------------------------------------------------------
# F5 -- closed schema, purity and no shared containers
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("forge", [
    lambda f: f.pop("device"),
    lambda f: f.update(extra=[]),
    lambda f: f["severity"].pop(),
    lambda f: f["severity"].append(deepcopy(f["severity"][0])),
    lambda f: f["category"][0].update(k="Legacy name"),
    lambda f: f["severity"][0].update(k="critical"),
    lambda f: f["device"]["items"][0].update(k=7),
    lambda f: f["device"]["items"][0].update(extra=True),
    lambda f: f.update(device=f["device"]["items"]),                               # a bare array has no state
    lambda f: f["device"].update(items=[]),                                        # a published list is never empty
    lambda f: f["device"].pop("state"),
    lambda f: f["severity"][0]["n"].update(value=True),
    lambda f: f["severity"][0]["n"].update(value=-1),
    lambda f: f["severity"][0]["n"].update(state=NC),
    lambda f: f["category"][0]["n"].update(state=PUB, value=None),
])
def test_f5_the_closed_schema_rejects_forged_facets(forge):
    payload = uip.project(_snapshot(_rows()))
    validator = Draft202012Validator(uip.ui_projection_schema())
    validator.validate(payload)
    forged = deepcopy(payload)
    forge(forged["findings"]["facets"])
    assert not validator.is_valid(forged)


def test_f5_projection_is_pure_and_buckets_share_no_container():
    snap = _snapshot(_rows())
    frozen = deepcopy(snap)
    first = uip.project_findings(snap)
    assert snap == frozen
    severity = first["facets"]["severity"]
    severity[0]["n"]["refs"].append({"pointer": "/injected", "role": "witness"})
    assert all({"pointer": "/injected", "role": "witness"} not in bucket["n"]["refs"] for bucket in severity[1:])
    assert all({"pointer": "/injected", "role": "witness"} not in bucket["n"]["refs"]
               for bucket in first["facets"]["category"])
    second = uip.project_findings(snap)
    assert second["facets"]["severity"][0]["n"]["refs"] == [BASIS_REF]
    reordered = json.loads(json.dumps(snap, sort_keys=True))
    assert uip.project_findings(reordered)["facets"] == second["facets"]


# --------------------------------------------------------------------------------------------------
# F6 -- a category whose source section is incomplete is never a clean zero, nor its severities
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("section", SOURCES)
def test_f6_every_uncollected_category_source_withholds_its_zero_and_bounds_its_count(section):
    """For EVERY source section the owner names (the whole class, read from analyze.PUNCH_CATEGORY_SECTION): delete it
    from the fully captured stored sample. No held category and no severity is then a published zero, and any
    published count of them is a lower bound carrying the source caveat."""
    snap, _patched = _captured_sample()
    del snap[section]
    assert ssot.abstention_reason(snap, section) == NC
    findings = uip.project_findings(snap)
    rows = snap["punchlist"]
    held = [category for category, source in analyze.PUNCH_CATEGORY_SECTION.items() if source == section]
    assert held
    facets = {facet: _by_key(findings["facets"][facet]) for facet, _keys in OWNER_FACETS}
    for facet, key in [("category", category) for category in held] + [("severity", s) for s in uip.SEVERITIES]:
        n = facets[facet][key]
        assert not (n["state"] == PUB and n["value"] == 0), (section, facet, key)
        if n["state"] == PUB:
            assert n["value"] > 0 and SOURCE_CAVEAT in n["caveats"], (section, facet, key)
        else:
            assert n["reason"].startswith("not collected") and "not a clean result" in n["reason"], (section, key)
    if section in uip.PUNCHLIST_INPUTS:                    # the row list itself is then incomplete and withheld
        assert findings["rows"]["state"] == NC
        return
    # a section outside the punch-list inputs: the rows stay published and only the held buckets change
    assert findings["rows"]["state"] == PUB and findings["total"]["state"] == PUB
    for facet, keys in OWNER_FACETS:
        expected = _recount(rows, facet)
        for key in keys:
            n = facets[facet][key]
            if facet == "severity" or key in held:
                if expected[key]:
                    assert (n["state"], n["value"]) == (PUB, expected[key]) and SOURCE_CAVEAT in n["caveats"], key
                else:
                    assert (n["state"], n["value"]) == (NC, None), key
                    assert section in n["reason"], (key, n["reason"])
                    if facet == "category":
                        assert n["reason"].startswith(f"not collected: {section}, the section the engine folds the "
                                                      f"{key} findings from, was not collected")
                    else:
                        assert all(f"{category} ({section} not collected)" in n["reason"] for category in held)
            else:                                          # an unheld category keeps its measured value
                assert (n["state"], n["value"]) == (PUB, expected[key]), key
                assert SOURCE_CAVEAT not in n.get("caveats", ()), key
            assert n["refs"][0] == BASIS_REF, key


def test_f6_the_reviewed_multicast_case_and_a_positive_count_over_a_missing_source():
    """The reviewed counterexample: with every running-config captured, a missing multicast_intelligence made
    'Multicast/Media: 0' and 'Info: 0' clean published zeros. And a stored row of a category whose own source is
    missing is a lower bound, never an exact count."""
    snap, _patched = _captured_sample()
    del snap["multicast_intelligence"]
    findings = uip.project_findings(snap)
    category = _by_key(findings["facets"]["category"])
    severity = _by_key(findings["facets"]["severity"])
    assert sum(1 for row in snap["punchlist"] if row["category"] == "Multicast/Media") == 0
    assert (category["Multicast/Media"]["state"], category["Multicast/Media"]["value"]) == (NC, None)
    assert sum(1 for row in snap["punchlist"] if row["severity"] == "Info") == 0
    assert (severity["Info"]["state"], severity["Info"]["value"]) == (NC, None)
    assert severity["High"]["state"] == PUB and SOURCE_CAVEAT in severity["High"]["caveats"]
    # a positive count of a category whose own source section is gone
    snap = _snapshot(_rows() + [{"severity": "Medium", "category": "FHRP", "devices": ["edgeA"]}])
    del snap["fhrp"]
    facets = _facets(snap)
    fhrp = _by_key(facets["category"])["FHRP"]
    assert (fhrp["state"], fhrp["value"]) == (PUB, 1) and fhrp["caveats"] == [SOURCE_CAVEAT]
    assert not [ref for ref in fhrp["refs"] if ref["pointer"] == "/fhrp"]             # an absent section is not cited
    medium = _by_key(facets["severity"])["Medium"]
    assert (medium["state"], medium["value"]) == (PUB, 1) and medium["caveats"] == [SOURCE_CAVEAT]
    assert _by_key(facets["category"])["Security"].get("caveats") is None           # its own source is complete


def test_f6_a_failed_category_source_phase_is_unavailable_with_its_failure_record():
    snap, _patched = _captured_sample()
    snap["multicast_intelligence"] = {}                                            # the failed phase's fallback
    snap["assessment_integrity"] = {"failed_phases": ["Multicast intelligence"]}
    assert ssot.abstention_reason(snap, "multicast_intelligence") == AU
    findings = uip.project_findings(snap)
    assert findings["rows"]["state"] == PUB                                         # not a punch-list input
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    multicast = _by_key(findings["facets"]["category"])["Multicast/Media"]
    assert (multicast["state"], multicast["value"]) == (AU, None)
    held_section = {"pointer": "/multicast_intelligence", "role": "witness"}
    assert record in multicast["refs"] and held_section in multicast["refs"]
    assert "failed sections: multicast_intelligence" in multicast["reason"]
    info = _by_key(findings["facets"]["severity"])["Info"]
    assert (info["state"], info["value"]) == (AU, None) and record in info["refs"] and held_section in info["refs"]
    assert info["reason"].startswith("analysis unavailable") and "Multicast/Media (multicast_intelligence" in info["reason"]
    high = _by_key(findings["facets"]["severity"])["High"]
    assert high["state"] == PUB and {SOURCE_CAVEAT, "one_hop_failure_attribution"} <= set(high["caveats"])
    # a published lower bound cites the failed section as a witness, never as a basis (a basis ref to a failed
    # section belongs only to a value that is itself unavailable)
    assert held_section in high["refs"]
    assert not [ref for ref in high["refs"] if ref["role"] == "basis" and ref["pointer"] == "/multicast_intelligence"]
    link = _by_key(findings["facets"]["category"])["Link L1"]                       # its own source is complete
    assert (link["state"], link["value"]) == (PUB, 0) and SOURCE_CAVEAT not in link.get("caveats", ())


def test_f6_a_category_the_owner_maps_to_no_section_is_unverified_never_complete(monkeypatch):
    """The fail-closed path for a category the map does not name (the map is total today; this proves the guard)."""
    unmapped = ("STP", "QoS")
    monkeypatch.setattr(uip, "PUNCH_CATEGORY_SECTION", MappingProxyType(
        {k: v for k, v in analyze.PUNCH_CATEGORY_SECTION.items() if k not in unmapped}))
    facets = _facets(_snapshot(_rows()))
    category, severity = _by_key(facets["category"]), _by_key(facets["severity"])
    assert (category["STP"]["state"], category["STP"]["value"]) == (PUB, 1)
    assert category["STP"]["caveats"] == [SOURCE_CAVEAT]
    assert (category["QoS"]["state"], category["QoS"]["value"]) == (UV, None)
    assert "names no source section for the QoS findings" in category["QoS"]["reason"]
    assert (severity["Medium"]["state"], severity["Medium"]["value"]) == (UV, None)
    assert "STP (no source section)" in severity["Medium"]["reason"]
    assert category["Security"]["state"] == PUB and "caveats" not in category["Security"]


# --------------------------------------------------------------------------------------------------
# F7 -- the device facet takes the roster's own state: absence is never an empty roster
# --------------------------------------------------------------------------------------------------
def _findings_validator():
    schema = uip.ui_projection_schema()
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/Findings"})


def test_f7_a_missing_devices_map_withholds_the_device_facet_and_every_held_count():
    snap = _snapshot(_rows())
    del snap["devices"]
    assert ssot.abstention_reason(snap, "devices") == NC
    findings = uip.project_findings(snap)
    facets = findings["facets"]
    device_list = facets["device"]
    assert device_list["state"] == NC and device_list["items"] == []                 # withheld, not an empty roster
    assert device_list["reason"].startswith("not collected")
    roster = uip.project_inventory(snap)["devices"]["rows"]
    assert (device_list["state"], device_list["reason"]) == (roster["state"], roster["reason"])
    # 'devices' is the Inventory category's own source: its zero and every severity zero are withheld too
    inventory = _by_key(facets["category"])["Inventory"]
    assert (inventory["state"], inventory["value"]) == (NC, None)
    medium = _by_key(facets["severity"])["Medium"]
    assert (medium["state"], medium["value"]) == (NC, None) and "Inventory (devices not collected)" in medium["reason"]
    high = _by_key(facets["severity"])["High"]
    assert (high["state"], high["value"]) == (PUB, 2) and SOURCE_CAVEAT in high["caveats"]
    _findings_validator().validate(findings)


def test_f7_an_unreadable_devices_map_is_unverified_and_blind_spots_stay_listed():
    snap = _snapshot(_rows())
    snap["devices"] = sorted(HOSTS)                                                  # a list, not the map
    snap["collection_completeness"]["devices"] = [
        {"host": "ghost", "status": "not collected", "missing": ["interface status"], "data_quality": 0}]
    findings = uip.project_findings(snap)
    device_list = findings["facets"]["device"]
    assert device_list["state"] == UV and "devices is not an object" in device_list["reason"]
    assert [bucket["k"] for bucket in device_list["items"]] == ["ghost"]            # the roster it can read
    assert device_list["items"][0]["n"]["state"] == NC
    _findings_validator().validate(findings)
