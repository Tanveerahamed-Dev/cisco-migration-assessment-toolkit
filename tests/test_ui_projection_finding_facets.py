"""G21 -- punch-list facet totals: row counts by severity, category and inventory device.

``findings.facets`` publishes, for each key of the owner's closed vocabulary and in its order, the number of stored
punch-list rows with that severity or category (``analyze.compute_punchlist_facets``), and, for each inventory
device, the per-device rollup (G09, ``analyze.compute_device_findings``) summed. Coverage honesty:

* a missing punch list is not_collected, an empty one collected_but_empty, a failed one analysis_unavailable;
* the owner's buckets are published only as an exact partition of the stored rows (every row once, in the bucket
  its own field names, as many rows as the row list and its total), else the facet is unverified;
* while a fleet qualification applies (blind devices, devices without a captured running-config), a positive count
  is a lower bound carrying that caveat and its witnesses, and a zero is not_collected, never a clean result;
* a device bucket is the device's own rollup: same state, reason, refs and caveats as its inventory row.

Every expected number is recounted here from the snapshot, never taken from the module's own fold. The stored
engine-built sample fleet and the committed golden snapshot are read as they are; neither is regenerated.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as uip
from test_ui_projection_decision_rollups import HOSTS, _snapshot

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORED = {"sample_fleet": ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json",
          "golden": ROOT / "tests" / "golden" / "snapshot.json"}
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
BASIS_REF = {"pointer": "/punchlist", "role": "basis"}
OWNER_FACETS = (("severity", analyze.PUNCH_SEVERITIES), ("category", analyze.PUNCH_CATEGORIES))


def _rows():
    return [
        {"severity": "High", "category": "Security", "devices": ["edgeA", "edgeA", "edgeB"]},
        {"severity": "Critical", "category": "L3", "devices": ["edgeA"]},
        {"severity": "Info", "category": "Coverage", "devices": ["edgeB"]},
        {"severity": "High", "category": "Security", "devices": ["edgeA"]},
        {"severity": "Low", "category": "STP", "devices": []},
    ]


def _facets(snap):
    return uip.project_findings(snap)["facets"]


def _by_key(buckets):
    keys = [bucket["k"] for bucket in buckets]
    assert len(set(keys)) == len(keys), keys
    return {bucket["k"]: bucket["n"] for bucket in buckets}


def _recount(rows, facet):
    return Counter(row[facet] for row in rows)


def _stored(name):
    return json.loads(STORED[name].read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------------
# F0 -- vocabularies, schema and registration
# --------------------------------------------------------------------------------------------------
def test_f0_facet_keys_are_the_owner_vocabularies_and_the_schema_closes_them():
    assert uip.FINDING_CATEGORIES == analyze.PUNCH_CATEGORIES == tuple(analyze._PUNCH_EVIDENCE_POLICY)
    assert uip.SEVERITIES == analyze.PUNCH_SEVERITIES
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
    assert facets["properties"]["device"] == {"type": "array", "items": {"$ref": "#/$defs/DeviceFacetRow"}}
    assert d["DeviceFacetRow"]["properties"] == {"k": {"type": "string"}, "n": {"$ref": "#/$defs/CountFact"}}
    vocab = uip.project({})["vocab"]
    assert vocab["unranked"]["punch_category"]["tokens"] == list(uip.FINDING_CATEGORIES)
    lims = {lim["id"]: lim["applies_to"] for lim in uip.LIMITATIONS}
    for cid in ("one_hop_failure_attribution", "fleet_lists_exclude_blind_devices",
                "findings_without_running_config", "projection_owned_verdicts"):
        assert "/findings/facets" in lims[cid], cid
    assert "/findings/facets/device" in lims["device_findings_scope"]


# --------------------------------------------------------------------------------------------------
# F1 -- the stored engine data: owner order, independent recounts, reconciliation, qualification
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", tuple(STORED))
def test_f1_stored_engine_snapshots_publish_recounted_facets_that_reconcile_with_the_rows(name):
    snap = _stored(name)
    rows = snap["punchlist"]
    assert len(rows) > 20                                           # the real stored producer output
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
                assert "findings_without_running_config" in n["caveats"]
                published += n["value"]
            else:                                                   # a zero over a qualified list is no clean result
                assert (n["state"], n["value"]) == (NC, None), (facet, bucket["k"])
                assert "not a clean result" in n["reason"] and "security row" in n["reason"]
        assert published == len(rows) == findings["total"]["value"]      # the facet reconciles with the row count
    # the device facet is the inventory roster's own rollup, summed
    device = _by_key(findings["facets"]["device"])
    inventory = {row["host"]: row["findings"]["by_severity"] for row in payload["inventory"]["devices"]["rows"]["items"]}
    assert list(device) == sorted(inventory) == sorted(snap["devices"])
    for host, n in device.items():
        rollup = inventory[host]
        assert n["state"] == rollup["state"] and n["refs"] == rollup["refs"], host
        if host in lacking:
            assert n["state"] == NC, host
        if n["state"] == PUB:
            assert n["value"] == sum(rollup["value"].values()) == sum(1 for row in rows if host in row["devices"])
            assert n.get("caveats") == rollup.get("caveats") and "device_findings_scope" in n["caveats"]
        else:
            assert n["value"] is None and n["reason"] == rollup["reason"]
    assert any(n["state"] == PUB and n["value"] > 0 for n in device.values())     # non-vacuous
    schema = uip.ui_projection_schema()
    Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                          "$ref": "#/$defs/Findings"}).validate(findings)


def test_f1_with_every_running_config_captured_zeros_publish_and_nothing_is_qualified():
    snap = _stored("sample_fleet")
    for host in [host for host in snap["devices"] if host not in snap["security"]]:
        snap["security"][host] = deepcopy(snap["security"]["core1"])
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
    assert all(n["state"] == PUB for n in category.values())
    device = _by_key(facets["device"])
    assert list(device) == sorted(HOSTS)
    assert {k: (n["state"], n["value"]) for k, n in device.items()} == {
        "edgeA": (PUB, 3), "edgeB": (PUB, 2), "empty": (PUB, 0)}
    witnesses = {ref["pointer"] for ref in device["edgeA"]["refs"] if ref["pointer"].startswith("/punchlist/")}
    assert witnesses == {"/punchlist/0", "/punchlist/1", "/punchlist/3"}
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
    assert {k: (n["state"], n["value"]) for k, n in _by_key(facets["device"]).items()} == {
        host: (PUB, 0) for host in HOSTS}


def test_f2_a_missing_punch_list_is_not_collected_everywhere():
    snap = _snapshot(_rows())
    del snap["punchlist"]
    facets = _facets(snap)
    for facet in uip.FINDING_FACETS:
        for bucket in facets[facet]:
            n = bucket["n"]
            assert (n["state"], n["value"]) == (NC, None), (facet, bucket["k"])
            assert n["reason"].startswith("not collected")
            assert BASIS_REF not in n["refs"]                     # the absent section is never cited as a basis
    assert [bucket["k"] for bucket in facets["device"]] == sorted(HOSTS)


@pytest.mark.parametrize("retained", [False, True])
def test_f2_a_failed_punch_list_phase_is_unavailable_with_its_failure_record(retained):
    snap = _snapshot(_rows() if retained else [])
    snap["assessment_integrity"] = {"failed_phases": ["Migration Punch-List"]}
    assert ssot.abstention_reason(snap, "punchlist") == AU
    facets = _facets(snap)
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    for facet in uip.FINDING_FACETS:
        for bucket in facets[facet]:
            assert (bucket["n"]["state"], bucket["n"]["value"]) == (AU, None), (facet, bucket["k"])
            assert record in bucket["n"]["refs"], (facet, bucket["k"])


def test_f2_a_failed_punch_list_input_is_unavailable_even_with_stored_rows():
    snap = _snapshot(_rows())
    snap["health_scores"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    facets = _facets(snap)
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    for facet in uip.FINDING_FACETS:
        for bucket in facets[facet]:
            assert bucket["n"]["state"] == AU and record in bucket["n"]["refs"], (facet, bucket["k"])


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
    device = _by_key(facets["device"])
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
    device = _by_key(facets["device"])
    assert list(device) == sorted(HOSTS + ("ghost",))
    assert device["ghost"]["state"] == NC and witness in device["ghost"]["refs"]


# --------------------------------------------------------------------------------------------------
# F4 -- the owner's partition is admitted only when it is exact
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
    assert {bucket["n"]["state"] for bucket in facets["device"]} == {UV}          # the G09 fold refuses it too
    snap = _snapshot(_rows() + [None])
    facets = _facets(snap)
    for facet in uip.FINDING_FACETS:
        assert {bucket["n"]["state"] for bucket in facets[facet]} == {UV}, facet


def test_f4_an_owner_fault_is_unverified_and_names_the_owner(monkeypatch):
    def broken(_rows):
        raise ValueError("synthetic owner failure")

    monkeypatch.setattr(uip, "compute_punchlist_facets", broken)
    facets = _facets(_snapshot(_rows()))
    for facet, _keys in OWNER_FACETS:
        for bucket in facets[facet]:
            assert bucket["n"]["state"] == UV and "analyze.compute_punchlist_facets" in bucket["n"]["reason"]
    assert {bucket["n"]["state"] for bucket in facets["device"]} == {PUB}


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
    assert {bucket["n"]["state"] for bucket in facets["device"]} == {PUB}


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
    lambda f: f["device"][0].update(k=7),
    lambda f: f["device"][0].update(extra=True),
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
