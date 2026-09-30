"""ui_projection/1 -- slice 2 (Inventory, device page, Findings) of the one typed engine->UI projection (D9).

The projection may select, type-check, order and point. It must not invent a verdict, rollup, band or count the
engine does not publish. These tests hold slice 2 to that contract:

* every row value is compared with an INDEPENDENT lookup in the snapshot (never the module's own join);
* engine defaults that mean "not observed" (DevicePhysical '' and 0, the '[NOT OBSERVED]' markers, sparse
  interface fields, empty routing-neighbour lists) are withheld, never published as measurements;
* failed phases make the facts built on them ``analysis_unavailable`` (fixtures recomputed with the real
  producers, plus one real ``COLLECT_PARSE_V3_23_0.main()`` run with three phases forced to fail);
* lists the engine caps say so, and no total is computed for them;
* the copied vocabularies and tables are held equal to their owners by source/AST checks;
* a synthetic 300-device / 20k-interface fleet stays fast.

Helpers are copied, not imported, from tests/test_ui_projection.py (a sibling-module import would take this
file down with it if a name there moved).
"""
from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import inspect
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import textwrap
import time

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, nrfu_export, ssot
from cisco_toolkit import parse as parse_mod
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.model import DevicePhysical, InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
AU = "analysis_unavailable"
NC = "not_collected"
CBE = "collected_but_empty"
PUB = "published"
NA = "not_assessed"
UV = "unverified"
NOT_A_BLIND_SPOT = "not a blind spot"
HUGE = "1" + "0" * 400
EXTRA_HOSTS = ("", "no-such", "a/b~c.d", 7, None)

_MISSING = object()


# --------------------------------------------------------------------------------------------------
# independent helpers (deliberately NOT the module's own)
# --------------------------------------------------------------------------------------------------
def _resolve(doc, pointer):
    """An independent RFC 6901 resolver: ``_MISSING`` when the pointer does not resolve."""
    if pointer == "":
        return doc
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            if tok not in cur:
                return _MISSING
            cur = cur[tok]
        elif isinstance(cur, list):
            if not tok.isdigit() or (len(tok) > 1 and tok.startswith("0")):
                return _MISSING
            idx = int(tok)
            if idx >= len(cur):
                return _MISSING
            cur = cur[idx]
        else:
            return _MISSING
    return cur


def _ptr(*tokens):
    return "".join("/" + str(t).replace("~", "~0").replace("/", "~1") for t in tokens)


def _is_fact(obj):
    return isinstance(obj, dict) and {"state", "subject", "refs", "basis"} <= set(obj)


def _walk_facts(obj, where=""):
    """Yield ``(payload pointer, fact-or-factlist)`` for every Fact / FactList under `obj`."""
    if isinstance(obj, dict):
        if _is_fact(obj):
            yield where, obj
        for key, val in obj.items():
            yield from _walk_facts(val, f"{where}/{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _walk_facts(val, f"{where}/{i}")


def _walk_pointers(obj, where=""):
    """Every snapshot pointer a row or selection carries (``pointer`` keys, row refs, selections)."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "pointer" and isinstance(val, str):
                yield f"{where}/{key}", val
            elif key in ("rows", "selections") and isinstance(val, dict) and not _is_fact(val):
                for sub, ptr in val.items():
                    if isinstance(ptr, str):
                        yield f"{where}/{key}/{sub}", ptr
                    elif sub in ("stp_roots",) and isinstance(ptr, list):
                        for j, p in enumerate(ptr):
                            yield f"{where}/{key}/{sub}/{j}", p
            if not (_is_fact(obj) and key in ("refs",)):
                yield from _walk_pointers(val, f"{where}/{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _walk_pointers(val, f"{where}/{i}")


def _sv(fact):
    return fact["state"], fact.get("value")


def _deep(n, open_="[", close="]"):
    return open_ * n + close * n


def _poison_with(bad):
    def _poison(obj):
        """Recursively replace every numeric leaf (bools kept) with `bad` -- the repo's fuzz rule."""
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            return copy.deepcopy(bad)
        if isinstance(obj, dict):
            return {k: _poison(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_poison(v) for v in obj]
        return obj
    return _poison


def _mutate_everything(obj):
    if isinstance(obj, dict):
        for key in list(obj):
            _mutate_everything(obj[key])
            obj[key] = "MUTATED"
        obj["__mutated__"] = True
    elif isinstance(obj, list):
        for i in range(len(obj)):
            _mutate_everything(obj[i])
            obj[i] = "MUTATED"
        obj.append("MUTATED")


def _brief_params():
    return list(inspect.signature(analyze.compute_executive_brief).parameters)


def _rebrief(snap, ref):
    """Recompute the brief with the REAL producer, then re-inject what ``COLLECT_PARSE_V3_23_0.main``
    adds after it (``scale.n_vlans`` / ``scale.n_collected``) and the SSOT stamp."""
    brief = analyze.compute_executive_brief(**{p: snap.get(p) for p in _brief_params()})
    brief["scale"]["n_vlans"] = ref["executive_brief"]["scale"]["n_vlans"]
    brief["scale"]["n_collected"] = ref["executive_brief"]["scale"]["n_collected"]
    snap["executive_brief"] = brief
    brief["ssot"] = ssot.summary(snap)
    return snap


def _roster_hosts(snap):
    """The device-page roster, read independently: devices keys, blind spots, cable-map nodes."""
    s = snap if isinstance(snap, dict) else {}
    hosts = set()
    if isinstance(s.get("devices"), dict):
        hosts.update(k for k in s["devices"] if isinstance(k, str))
    cc = s.get("collection_completeness")
    rows = cc.get("devices") if isinstance(cc, dict) else None
    for r in rows if isinstance(rows, list) else ():
        if isinstance(r, dict) and isinstance(r.get("host"), str):
            hosts.add(r["host"])
    cm = s.get("cable_map")
    nodes = cm.get("nodes") if isinstance(cm, dict) else None
    for n in nodes if isinstance(nodes, list) else ():
        if isinstance(n, dict) and isinstance(n.get("host"), str):
            hosts.add(n["host"])
    return sorted(hosts)


def _inventory_hosts(snap):
    s = snap if isinstance(snap, dict) else {}
    hosts = set()
    if isinstance(s.get("devices"), dict):
        hosts.update(k for k in s["devices"] if isinstance(k, str))
    cc = s.get("collection_completeness")
    rows = cc.get("devices") if isinstance(cc, dict) else None
    for r in rows if isinstance(rows, list) else ():
        if isinstance(r, dict) and isinstance(r.get("host"), str):
            hosts.add(r["host"])
    return sorted(hosts)


def _row_for(p, host):
    hits = [r for r in p["inventory"]["devices"]["rows"]["items"] if r["host"] == host]
    assert len(hits) == 1, (host, len(hits))
    return hits[0]


def _all_limitation_ids():
    return {lim["id"] for lim in uip.LIMITATIONS} | {lim["id"] for lim in uip.DEVICE_LIMITATIONS}


# --------------------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------------------
def _sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _minimal():
    return {"schema": "collect_parse_snapshot/1", "devices": {"sw1": {"hostname": "sw1"}}}


def _all_insufficient(sample):
    snap = copy.deepcopy(sample)
    for row in snap["health_scores"]:
        row["band"] = "Insufficient Data"
    return _rebrief(snap, sample)


def _health_failed(sample):
    snap = copy.deepcopy(sample)
    snap["health_scores"] = []                   # the _run_phase fallback of 'Health Scores'
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    return _rebrief(snap, sample)


def _punch_failed(sample):
    snap = copy.deepcopy(sample)
    snap["punchlist"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Migration Punch-List"]}
    return _rebrief(snap, sample)


def _endpoints_failed(sample):
    snap = copy.deepcopy(sample)
    snap["endpoint_identity"] = []
    snap["endpoint_dependencies"] = analyze.compute_endpoint_dependencies([], snap["move_groups"])
    snap["assessment_integrity"] = {"failed_phases": ["Endpoint identity"]}
    return _rebrief(snap, sample)


def _blind_spots(sample):
    snap = copy.deepcopy(sample)
    cc = snap["collection_completeness"]
    cc["devices"] = [{"host": "ghost1", "status": "not collected", "data_quality": 0, "missing": ["show version"]},
                     {"host": "access2", "status": "partial", "data_quality": 75, "missing": ["show cdp neighbors"]}]
    cc["summary"]["inventory"] += 1
    return snap


def _blind_existing(sample):
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [
        {"host": "access1", "status": "not collected", "data_quality": 0, "missing": ["show version"]}]
    return snap


def _labelled_groups(sample):
    snap = copy.deepcopy(sample)
    for i, g in enumerate(snap["move_groups"], 1):
        g["group"] = f"Group {i}"
    snap["endpoint_dependencies"] = analyze.compute_endpoint_dependencies(snap["endpoint_identity"],
                                                                           snap["move_groups"])
    return snap


def _duplicate_health(sample):
    snap = copy.deepcopy(sample)
    snap["health_scores"].append(copy.deepcopy(snap["health_scores"][0]))
    return snap


ODD = {"access1": "a/b", "access2": "x~y", "access3": "r1.lab"}


def _odd_hosts(sample):
    snap = copy.deepcopy(sample)
    for old, new in ODD.items():
        for section in ("devices", "interfaces", "security", "coverage_matrix"):
            block = snap[section] if section != "coverage_matrix" else snap["coverage_matrix"]["by_device"]
            if old in block:
                block[new] = block.pop(old)
        for row in snap["health_scores"]:
            if row["switch"] == old:
                row["switch"] = new
        for row in snap["endpoint_identity"]:
            if row["host"] == old:
                row["host"] = new
    return snap


def _set(sample, fn):
    snap = copy.deepcopy(sample)
    fn(snap)
    return snap


def _bad_physical(s):
    hosts = sorted(s["devices"])
    s["devices"][hosts[0]]["num_modules"] = float("nan")
    s["devices"][hosts[1]]["total_ports"] = 10 ** 400
    s["devices"][hosts[2]]["num_power_supplies"] = True
    s["devices"][hosts[3]]["active_ports"] = -1


def _bad_punch(s):
    s["punchlist"][0]["severity"] = "medium"
    s["punchlist"][1]["rank"] = 99
    s["punchlist"][2]["priority"] = 999


GARBAGE = {
    "g_none": lambda s: None,
    "g_list": lambda s: [],
    "g_str": lambda s: "",
    "g_zero": lambda s: 0,
    "g_empty": lambda s: {},
    "g_eb_int": lambda s: {"executive_brief": 5},
    "g_nan_posture": lambda s: {"executive_brief": {"posture": {"avg_health": float("nan")}},
                                "health_scores": [{"band": "Good", "score": float("inf")}]},
    "g_huge": lambda s: json.loads('{"collection_completeness":{"summary":{"inventory":' + HUGE + '}}}'),
    "g_eb_unavailable": lambda s: {"executive_brief": {"_unavailable": True}},
    "g_fp_str": lambda s: {"assessment_integrity": {"failed_phases": "boom"}},
    "g_deep_section": lambda s: json.loads('{"schema":"collect_parse_snapshot/1","punchlist":' + _deep(900) + '}'),
    "g_poison_nan": lambda s: _poison_with(float("nan"))(s),
    "g_poison_huge": lambda s: _poison_with(10 ** 400)(s),
    "g_poison_str": lambda s: _poison_with("12")(s),
    "g_poison_dict": lambda s: _poison_with({"n": 1})(s),
    "g_devices_int": lambda s: {"devices": 5},
    "g_devices_rowint": lambda s: {"devices": {"x": 5}},
    "g_if_deep": lambda s: json.loads('{"devices":{"sw1":{}},"interfaces":' + _deep(900) + '}'),
    "g_if_host_deep": lambda s: json.loads('{"devices":{"sw1":{}},"interfaces":{"sw1":' + _deep(900) + '}}'),
    "g_ep_bad": lambda s: _set(s, lambda x: x.update(endpoint_identity=[None, 5, {"host": []}])),
    "g_punch_bad": lambda s: _set(s, _bad_punch),
    "g_phys_bad": lambda s: _set(s, _bad_physical),
    "g_fhrp_bad": lambda s: _set(s, lambda x: x["vlan_cutover"][0].update(
        fhrp={"proto": "HSRP", "group": "10", "vip": "v", "members": [{"host": 5}]})),
}
_ALL_NC = ("g_none", "g_list", "g_str", "g_zero", "g_empty", "g_eb_int")
CORE = ("a", "b", "c", "hf", "pf", "ef", "real", "bl", "bl_nc", "mg", "dup", "odd")
ALL_CASES = CORE + tuple(GARBAGE)
REAL_FAILED = ("Health Scores", "Migration Punch-List", "Endpoint identity")


def _run_real_engine(tmp_path, mp):
    """The real pipeline with three phases forced to fail (pattern of
    tests/test_ssot_failed_phase_abstention.py::_run_engine, copied rather than imported)."""
    mp.syspath_prepend(str(ROOT / "tests"))
    mp.syspath_prepend(str(ROOT))
    import synthetic_fixtures as fx
    from openpyxl import Workbook
    import COLLECT_PARSE_V3_23_0 as cp
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(template))
    out = tmp_path / "out.xlsx"
    mp.chdir(tmp_path)
    mp.setattr(sys, "argv", ["cisco-assess", "--no-collect", "--collection-dir", collection,
                             "--devices-file", str(devices), "--template", str(template),
                             "--output", str(out), "--workers", "1", "--no-html", "--no-docx",
                             "--no-pptx", "--no-design", "--no-mop", "--no-crd", "--no-engagement",
                             "--no-opshandbook", "--no-archreview"])

    def _boom(*_a, **_kw):
        raise RuntimeError("synthetic phase failure")

    mp.setattr(cp, "compute_health_scores", _boom)
    mp.setattr(cp, "_punchlist", _boom)
    mp.setattr(cp, "compute_endpoint_identity", _boom)
    cp.main()
    return json.loads(pathlib.Path(str(out)[:-len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snaps(tmp_path_factory):
    sample = _sample()
    out = {"a": sample, "b": _minimal(), "c": _all_insufficient(sample), "hf": _health_failed(sample),
           "pf": _punch_failed(sample), "ef": _endpoints_failed(sample), "bl": _blind_spots(sample),
           "bl_nc": _blind_existing(sample), "mg": _labelled_groups(sample), "dup": _duplicate_health(sample),
           "odd": _odd_hosts(sample)}
    with pytest.MonkeyPatch.context() as mp:
        out["real"] = _run_real_engine(tmp_path_factory.mktemp("uip_inventory_real_engine"), mp)
    for name, build in GARBAGE.items():
        out[name] = build(sample)
    return out


@pytest.fixture(scope="module")
def payloads(snaps):
    return {name: uip.project(snap) for name, snap in snaps.items()}


def _doc_hosts(name, snap):
    hosts = _roster_hosts(snap)
    if name not in CORE:
        hosts = hosts[:3]
    return list(hosts) + list(EXTRA_HOSTS)


@pytest.fixture(scope="module")
def docs(snaps):
    return {name: [(host, uip.project_device(snap, host)) for host in _doc_hosts(name, snap)]
            for name, snap in snaps.items()}


@pytest.fixture(scope="module")
def validator():
    return Draft202012Validator(uip.ui_projection_schema())


@pytest.fixture(scope="module")
def doc_validator():
    schema = uip.ui_projection_schema()
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/DeviceDocument"})


def _doc(docs, name, host):
    hits = [d for h, d in docs[name] if h == host]
    assert len(hits) == 1, (name, host)
    return hits[0]


# --------------------------------------------------------------------------------------------------
# I0 -- the schema carries the new sections, and its enums ARE the module's vocabularies
# --------------------------------------------------------------------------------------------------
def _value_schema(defs, name):
    pub, wh = defs[name]["oneOf"]
    assert pub["properties"]["state"] == {"const": PUB}, name
    assert wh["properties"]["value"] == {"type": "null"}, name
    return pub["properties"]["value"]


def test_i0_schema_sections_and_vocabularies():
    schema = uip.ui_projection_schema()
    Draft202012Validator.check_schema(schema)
    d = schema["$defs"]
    assert schema["$id"] == uip.SCHEMA_ID and schema["title"] == uip.SCHEMA
    assert schema["required"] == ["schema", "engine", "overview", "trust", "inventory", "findings"]
    assert schema["properties"]["inventory"] == {"$ref": "#/$defs/Inventory"}
    assert schema["properties"]["findings"] == {"$ref": "#/$defs/Findings"}
    enums = {"LifecycleBandFact": uip.LIFECYCLE_BAND_ORDER, "RiskBandFact": uip.DOSSIER_BANDS,
             "SeverityFact": uip.SEVERITIES, "ReadinessFact": uip.VLAN_READINESS,
             "EndpointConfidenceFact": uip.ENDPOINT_CONFIDENCES, "CollectionStatusFact": uip.CC_STATUSES,
             "OpStatusFact": uip.OP_STATUSES}
    for name, vocab in enums.items():
        assert _value_schema(d, name) == {"type": "string", "enum": list(vocab)}, name
    assert _value_schema(d, "TextListFact") == {"type": "array", "items": {"type": "string"}}
    assert d["ExposureValue"]["properties"]["state"]["enum"] == list(uip.EXPOSURE_STATES)
    assert d["CompoundValue"]["properties"]["severity"]["enum"] == list(uip.SEVERITIES)
    assert d["SecurityCheckValue"]["properties"]["severity"]["enum"] == list(uip.SEC_SEVERITIES)
    assert d["SecurityCheckValue"]["properties"]["status"]["enum"] == list(uip.SEC_STATUSES)
    assert d["SecuritySummaryValue"]["properties"]["grade"]["enum"] == list(uip.SEC_GRADES)
    assert d["CoverageCellValue"]["properties"]["state"]["enum"] == list(uip.COVERAGE_STATES)
    assert list(d["InterfaceCells"]["properties"]) == list(uip.IF_COLUMNS)
    assert d["InterfaceCells"]["required"] == list(uip.IF_COLUMNS)
    ids = [lim["id"] for lim in uip.LIMITATIONS] + [lim["id"] for lim in uip.DEVICE_LIMITATIONS]
    assert d["LimitationId"]["enum"] == ids and len(set(ids)) == len(ids)
    dev_lims = d["DevicePage"]["properties"]["limitations"]
    assert dev_lims["minItems"] == dev_lims["maxItems"] == len(uip.DEVICE_LIMITATIONS)
    assert d["DeviceDocument"]["required"] == ["schema", "engine", "device"]
    assert d["DeviceDocument"]["properties"]["schema"]["const"] == uip.SCHEMA
    for name in ("Inventory", "Findings", "DevicePage", "DeviceRow", "VlanRow", "EndpointRow", "FindingRow",
                 "DualHomedRow", "InterfaceRow", "CableRow", "RouteRow", "NeighborRow", "RemediationRow",
                 "NrfuCaseRow", "Cap", "RowRef", "FhrpValue", "FhrpMember"):
        assert d[name]["type"] == "object" and d[name]["additionalProperties"] is False, name
    for name in ("DeviceRowList", "VlanRowList", "EndpointRowList", "FindingRowList", "SharedIpList",
                 "DualHomedList", "PeerList", "InterfaceRowList", "CableRowList", "RouteRowList",
                 "NeighborGroupList", "NeighborRowList", "SecurityCheckList", "TrunkNativeList",
                 "RemediationRowList", "NrfuCaseList", "RowRefList", "TextItemList", "ExposureList",
                 "CompoundList", "CoverageList"):
        pub, _wh = d[name]["oneOf"]
        assert pub["properties"]["items"]["minItems"] == 1, name          # a published list is never empty


def test_i0_schema_rejects_a_forged_device_row(payloads, validator):
    forgeries = {
        "unknown_key": lambda r: r.update(extra=1),
        "published_default": lambda r: r["model"].update(state=PUB, value=None),
        "bad_band": lambda r: r["risk_band"].update(state=PUB, value="Catastrophic"),
        "missing_rosters": lambda r: r.pop("rosters"),
    }
    for name, forge in forgeries.items():
        payload = copy.deepcopy(payloads["a"])
        forge(payload["inventory"]["devices"]["rows"]["items"][0])
        assert not validator.is_valid(payload), name


# --------------------------------------------------------------------------------------------------
# I1 / I2 -- schema-valid everywhere; composes; the envelope invariants hold; every pointer resolves
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALL_CASES)
def test_i1_projection_is_schema_valid_and_composes(name, snaps, payloads, validator, docs, doc_validator):
    snap, payload = snaps[name], payloads[name]
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:10]]
    assert payload["inventory"] == uip.project_inventory(snap)
    assert payload["findings"] == uip.project_findings(snap)
    json.dumps(payload, allow_nan=False)
    assert docs[name], name
    for host, doc in docs[name]:
        errors = sorted(doc_validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
        assert not errors, (host, [(list(e.absolute_path), e.message[:200]) for e in errors[:10]])
        assert doc["schema"] == uip.SCHEMA and doc["engine"] == payload["engine"]
        assert doc["device"]["host"] == (host if isinstance(host, str) else None)
        json.dumps(doc, allow_nan=False)


def _check_facts(root, where_prefix, lim_ids, snap):
    n = 0
    for where, fact in _walk_facts(root, where_prefix):
        n += 1
        state = fact["state"]
        assert state in uip.STATES, where
        assert ("reason" in fact) is (state != PUB), (where, fact)
        if "value" in fact:
            assert (fact["value"] is None) is (state != PUB), (where, fact)
        if "items" in fact and state == PUB:
            assert fact["items"], where
        if not where.endswith("/devices/total"):     # the one fact with a fixed dotted path the core addresses
            assert "engine_state" not in fact and "engine_state_owner" not in fact, where   # cells carry none
        assert set(fact.get("caveats", ())) <= lim_ids, (where, fact.get("caveats"))
        if state != PUB:
            assert NOT_A_BLIND_SPOT not in fact["reason"] or state == CBE, (where, fact["reason"])
        for ref in fact["refs"]:
            assert ref["role"] in uip.REF_ROLES
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (where, ref)
        if state == PUB and fact["subject"] is not None:
            assert _resolve(snap, fact["subject"]) is not _MISSING, (where, fact["subject"])
    return n


@pytest.mark.parametrize("name", ALL_CASES)
def test_i2_envelope_invariants_and_pointers(name, snaps, payloads, docs):
    snap, p = snaps[name], payloads[name]
    lim_ids = {lim["id"] for lim in p["trust"]["limitations"]}
    n = _check_facts({"inventory": p["inventory"], "findings": p["findings"]}, "", lim_ids, snap)
    assert n >= 8
    for where, ptr in _walk_pointers({"inventory": p["inventory"], "findings": p["findings"]}):
        assert _resolve(snap, ptr) is not _MISSING, (where, ptr)
    for lim in p["trust"]["limitations"]:
        for pointer in lim["applies_to"]:
            assert _resolve(p, pointer) is not _MISSING, (lim["id"], pointer)
    all_ids = _all_limitation_ids()
    for host, doc in docs[name]:
        _check_facts(doc["device"], "/device", all_ids, snap)
        for where, ptr in _walk_pointers(doc["device"]):
            if where.startswith("/limitations"):
                continue
            assert _resolve(snap, ptr) is not _MISSING, (host, where, ptr)
        assert [lim["id"] for lim in doc["device"]["limitations"]] == [lim["id"] for lim in uip.DEVICE_LIMITATIONS]
        for lim in doc["device"]["limitations"]:
            for pointer in lim["applies_to"]:
                assert _resolve(doc, pointer) is not _MISSING, (lim["id"], pointer)
    if name == "a":
        rows = p["inventory"]["devices"]["rows"]["items"]
        assert all(_resolve(snap, r["pointer"]) is not _MISSING for r in rows)
        roles = {r["role"] for _w, f in _walk_facts(p["inventory"]) for r in f["refs"]}
        assert {"subject", "witness"} <= roles


def test_i2_odd_hostnames_escape_and_resolve(snaps, payloads, docs):
    snap, p = snaps["odd"], payloads["odd"]
    for new in ODD.values():
        row = _row_for(p, new)
        assert row["pointer"] == _ptr("devices", new)
        assert _resolve(snap, row["pointer"]) == snap["devices"][new]
        assert row["health_score"]["state"] == PUB
        assert row["health_score"]["subject"] == _ptr("health_scores", row["rows"]["health"].rsplit("/", 1)[-1],
                                                      "score")
        doc = _doc(docs, "odd", new)
        assert doc["device"]["identity"]["model"]["subject"] == _ptr("devices", new, "model")
        ifs = doc["device"]["interfaces"]["rows"]
        assert ifs["state"] == PUB and all(r["pointer"].startswith(_ptr("interfaces", new) + "/") for r in ifs["items"])


# --------------------------------------------------------------------------------------------------
# I3 -- values and totals come from the owners (independent lookups)
# --------------------------------------------------------------------------------------------------
def test_i3_device_rows_are_the_owners_values(snaps, payloads):
    snap, p = snaps["a"], payloads["a"]
    inv = p["inventory"]["devices"]
    assert [r["host"] for r in inv["rows"]["items"]] == _inventory_hosts(snap)
    assert inv["rows"]["state"] == PUB
    assert _sv(inv["total"]) == (PUB, snap["collection_completeness"]["summary"]["inventory"])
    assert inv["total"]["subject"] == "/collection_completeness/summary/inventory"
    health = {r["switch"]: r for r in snap["health_scores"]}
    lc = {r["host"]: r for r in snap["lifecycle_risk"]["per_device"]}
    dd = {r["host"]: r for r in snap["device_dossiers"]["per_device"]}
    n_pub = 0
    for row in inv["rows"]["items"]:
        h = row["host"]
        dev = snap["devices"][h]
        assert row["rosters"] == {"devices": True, "collection_completeness": False}
        for f in ("model", "platform", "sw_version", "serial_number"):
            if dev[f]:
                assert _sv(row[f]) == (PUB, dev[f]), (h, f)
                n_pub += 1
            else:
                assert _sv(row[f]) == (NC, None), (h, f)
        hr = health[h]
        assert row["rows"]["health"] == _ptr("health_scores", snap["health_scores"].index(hr))
        assert _sv(row["role"]) == (PUB, hr["role"])
        if hr["band"] != "Insufficient Data":
            assert _sv(row["health_score"]) == (PUB, hr["score"])
            assert _sv(row["health_band"]) == (PUB, hr["band"])
        assert _sv(row["lifecycle_band"]) == (PUB, lc[h]["band"])
        assert _sv(row["risk_band"]) == (PUB, dd[h]["risk_band"])
        assert row["collection_status"]["state"] == CBE           # not a blind spot
        assert row["rows"]["collection"] is None
    assert n_pub > 40


def test_i3_totals_and_row_counts_equal_the_owners(snaps, payloads):
    snap, p = snaps["a"], payloads["a"]
    inv, fnd = p["inventory"], p["findings"]
    canon = ssot.canonical_facts(snap)
    assert _sv(inv["endpoints"]["total"]) == (PUB, len(snap["endpoint_identity"])) == (PUB, canon["n_endpoints"])
    assert {"pointer": "/executive_brief/scale/n_endpoints", "role": "witness"} in inv["endpoints"]["total"]["refs"]
    assert len(inv["endpoints"]["rows"]["items"]) == len(snap["endpoint_identity"])
    assert _sv(inv["vlans"]["total"]) == (PUB, len(snap["vlan_cutover"]))
    assert len(inv["vlans"]["rows"]["items"]) == len(snap["vlan_cutover"])
    assert _sv(fnd["total"]) == (PUB, len(snap["punchlist"]))
    assert len(fnd["rows"]["items"]) == len(snap["punchlist"])
    axes = snap["executive_brief"]["axes"]
    assert axes[fnd["headline_axis_index"]]["axis"] == "Migration punch-list"
    for item, raw in zip(fnd["rows"]["items"], snap["punchlist"]):
        for f in ("category", "title", "detail"):
            assert _sv(item[f]) == (PUB, raw[f]), f
        assert _sv(item["severity"]) == (PUB, raw["severity"])
        assert _sv(item["priority"]) == (PUB, raw["priority"])
        assert _sv(item["rank"]) == (PUB, raw["rank"])
        if raw["devices"]:
            assert _sv(item["devices"]) == (PUB, raw["devices"])
        if raw.get("source_command"):
            assert _sv(item["source_command"]) == (PUB, raw["source_command"])
        else:
            assert item["source_command"]["state"] == NC and "composite" in item["source_command"]["reason"]
        if raw["remediation"]:
            assert _sv(item["remediation"]) == (PUB, raw["remediation"])
        else:
            assert item["remediation"]["state"] == CBE
    for item, raw in zip(inv["vlans"]["rows"]["items"], snap["vlan_cutover"]):
        assert _sv(item["vlan"]) == (PUB, raw["vlan"])
    peers = [n["host"] for n in snap["cable_map"]["nodes"] if n["collected"] is False]
    assert [it["host"]["value"] for it in inv["uncollected_peers"]["items"]] == peers


def test_i3_device_page_values_come_from_the_owners(snaps, docs):
    snap = snaps["a"]
    for host in ("core1", "access1", "dist1"):
        page = _doc(docs, "a", host)["device"]
        dev = snap["devices"][host]
        for f in uip.DEVICE_PHYSICAL_TEXT:
            block = "identity" if f in page["identity"] else "physical"
            fact = page[block][f]
            assert _sv(fact) == ((PUB, dev[f]) if dev[f] else (NC, None)), (host, f)
        sec = snap["security"].get(host)
        if sec:
            assert _sv(page["security"]["summary"]) == (PUB, sec["summary"])
            assert [it["fact"]["value"] for it in page["security"]["checks"]["items"]] == sec["findings"]
        else:
            assert page["security"]["checks"]["state"] == NC
        cm = snap["coverage_matrix"]["by_device"][host]
        assert [it["axis"] for it in page["coverage"]["items"]] == sorted(cm)
        assert all(it["fact"]["value"] == {"axis": it["axis"], "state": cm[it["axis"]]} for it in page["coverage"]["items"])
        ifs = snap["interfaces"][host]
        assert [r["port"] for r in page["interfaces"]["rows"]["items"]] == sorted(ifs)
        assert page["interfaces"]["columns"] == list(uip.IF_COLUMNS)
        cables = [i for i, c in enumerate(snap["cable_map"]["cables"]) if host in (c["a"], c["b"])]
        assert [it["index"] for it in page["links"]["items"]] == cables
    routes = _doc(docs, "a", "core1")["device"]["routes"]
    assert routes["state"] == PUB and "routes_in_scope_only" in routes["caveats"]
    assert [it["prefix"]["value"] for it in routes["items"]] == [r["prefix"] for r in snap["routes"]["core1"]]
    groups = _doc(docs, "a", "core1")["device"]["routing_neighbors"]["items"]
    assert [g["protocol"] for g in groups] == sorted(snap["routing_neighbors"]["core1"])
    ospf = next(g for g in groups if g["protocol"] == "ospf")["neighbors"]
    assert ospf["state"] == PUB
    assert [it["neighbor"]["value"] for it in ospf["items"]] == \
        [r["neighbor"] for r in snap["routing_neighbors"]["core1"]["ospf"]]


# --------------------------------------------------------------------------------------------------
# I4 -- engine defaults that mean "not observed" are withheld, never published as measurements
# --------------------------------------------------------------------------------------------------
def test_i4_device_physical_defaults_are_withheld(snaps, docs):
    snap = snaps["a"]
    n_default = 0
    for host in sorted(snap["devices"]):
        page = _doc(docs, "a", host)["device"]
        dev = snap["devices"][host]
        for f in uip.DEVICE_PHYSICAL_ZERO_DEFAULTS:
            fact = page["physical"][f]
            if dev[f] == 0:
                n_default += 1
                assert _sv(fact) == (NC, None), (host, f)
                assert "default 0" in fact["reason"]
            else:
                assert _sv(fact) == (PUB, dev[f]), (host, f)
                assert "device_physical_defaults_not_observed" in fact["caveats"]
        for f in uip.DEVICE_PHYSICAL_TEXT:
            block = "identity" if f in uip.IDENTITY_FIELDS else "physical"
            if dev[f] == "":
                n_default += 1
                assert _sv(page[block][f]) == (NC, None), (host, f)
    assert n_default > 200
    edit = copy.deepcopy(snap)
    edit["devices"]["access1"]["active_ports"] = 0
    edit["devices"]["access2"]["active_ports"] = None
    assert _sv(uip.project_device(edit, "access1")["device"]["physical"]["active_ports"]) == (PUB, 0)
    fact = uip.project_device(edit, "access2")["device"]["physical"]["active_ports"]
    assert _sv(fact) == (NC, None) and "null" in fact["reason"]


def test_i4_sparse_interfaces_markers_and_human_fields(snaps, payloads, docs):
    snap, p = snaps["a"], payloads["a"]
    page = _doc(docs, "a", "core1")["device"]
    seen_sparse = 0
    for item in page["interfaces"]["rows"]["items"]:
        rec = snap["interfaces"]["core1"][item["port"]]
        for col in uip.IF_COLUMNS:
            fact = item["cells"][col]
            if rec.get(col, "") == "":
                seen_sparse += 1
                assert _sv(fact) == (NC, None), (item["port"], col)
                assert "interface record carries no value" in fact["reason"]
            else:
                assert _sv(fact) == (PUB, rec[col])
        roc = item["run_config_observed"]
        assert roc["state"] == (PUB if rec.get("run_config_observed") is True else NC)
    assert seen_sparse > 10
    vlans = {r["vlan"]["value"]: r for r in p["inventory"]["vlans"]["rows"]["items"]}
    raw = {r["vlan"]: r for r in snap["vlan_cutover"]}
    for vid, row in vlans.items():
        if raw[vid]["stp_root"] == uip.NOT_OBSERVED_SENTINEL:
            assert _sv(row["stp_root"]) == (NC, None)
            assert _sv(row["stp_root_default_election"]) == (NC, None)       # a False over no root
        else:
            assert _sv(row["stp_root"]) == (PUB, raw[vid]["stp_root"])
            assert _sv(row["stp_root_default_election"]) == (PUB, raw[vid]["stp_root_default_election"])
        if raw[vid]["endpoint_mix"] == uip.NOT_OBSERVED_SENTINEL:
            assert _sv(row["endpoint_mix"]) == (NC, None)
            if raw[vid]["endpoint_count"] == 0:
                assert _sv(row["endpoint_count"]) == (NC, None)
        else:
            assert _sv(row["endpoint_count"]) == (PUB, raw[vid]["endpoint_count"])
            assert "vlan_cutover_universe" in row["endpoint_count"]["caveats"]
        for f in ("cutover_window", "rollback_owner"):
            assert row[f]["state"] == NC and "human owns" in row[f]["reason"], f
        if isinstance(raw[vid]["fhrp"], dict):
            assert row["fhrp"]["state"] == PUB and row["fhrp"]["value"]["members"]
    assert vlans[20]["stp_root"]["state"] == NC and vlans[20]["endpoint_count"]["state"] == NC
    nrfu_seen = 0
    for host in ("access1", "core1"):
        for case in _doc(docs, "a", host)["device"]["nrfu_cases"]["items"]:
            rc = _resolve(snap, case["pointer"])
            if rc["expected"] == uip.NRFU_NOT_OBSERVED:
                nrfu_seen += 1
                assert _sv(case["expected"]) == (NC, None)
            else:
                assert _sv(case["expected"]) == (PUB, rc["expected"])
            assert case["evidence_state"]["state"] == (PUB if "evidence_state" in rc else NC)
    assert nrfu_seen >= 1
    for item, raw_ep in zip(p["inventory"]["endpoints"]["rows"]["items"], snap["endpoint_identity"]):
        for f in ("ip", "vendor"):
            assert _sv(item[f]) == ((NC, None) if raw_ep[f] == "" else (PUB, raw_ep[f])), f
    empty_neighbors = [g for g in _doc(docs, "a", "core1")["device"]["routing_neighbors"]["items"]
                       if snap["routing_neighbors"]["core1"][g["protocol"]] == []]
    assert empty_neighbors and all(g["neighbors"]["state"] == NC for g in empty_neighbors)
    routes = _doc(docs, "a", "access1")["device"]["routes"]
    assert routes["state"] == NC and "in-scope" in routes["reason"]


# --------------------------------------------------------------------------------------------------
# I5 -- capped lists say so; no total is ever computed for them
# --------------------------------------------------------------------------------------------------
def test_i5_capped_lists_say_at_least_and_publish_no_total(snaps, payloads, docs):
    snap, p = snaps["a"], payloads["a"]
    health = {r["switch"]: r for r in snap["health_scores"]}
    cap = uip.ENGINE_LIST_CAPS["health_scores[].deductions"]
    reached = short = 0
    for host in sorted(health):
        page = _doc(docs, "a", host)["device"]["health"]
        n = len(health[host]["deductions"])
        assert page["deductions_cap"]["limit"] == cap
        assert page["deductions_cap"]["reached"] is (n >= cap)
        assert page["deductions_cap"]["total"]["state"] == NC and page["deductions_cap"]["total"]["value"] is None
        reached += n >= cap
        short += n < cap
        assert [it["fact"]["value"] for it in page["deductions"]["items"]] == health[host]["deductions"]
    assert reached and short
    for row in p["inventory"]["endpoints"]["dual_homed"]["items"]:
        raw = _resolve(snap, row["pointer"])
        assert row["ports_cap"]["limit"] == uip.ENGINE_LIST_CAPS["endpoint_dependencies.dual_homed[].ports"]
        assert row["ports_cap"]["reached"] is (len(raw["ports"]) >= row["ports_cap"]["limit"])
        assert row["ports_cap"]["total"]["state"] == NC
    edit = copy.deepcopy(snap)
    edit["remediation_plan"]["by_device"]["core1"][0]["why"] = "x" * 300
    item = uip.project_device(edit, "core1")["device"]["remediation"]["items"]["items"][0]
    assert "engine_list_capped" in item["why"]["caveats"]
    for _w, fact in _walk_facts(_doc(docs, "a", "core1")["device"]):
        if fact["state"] == PUB and fact["subject"] and "/deductions/" in fact["subject"] and "items" not in fact:
            assert isinstance(fact["value"], str)                             # never a computed count


# --------------------------------------------------------------------------------------------------
# I6 -- a health score computed without the security input says so
# --------------------------------------------------------------------------------------------------
def test_i6_health_without_security_is_caveated(snaps, payloads):
    snap, p = snaps["a"], payloads["a"]
    security = snap["security"]
    good_without = 0
    for row in p["inventory"]["devices"]["rows"]["items"]:
        h = row["host"]
        for f in ("health_score", "health_band"):
            fact = row[f]
            if fact["state"] != PUB:
                continue
            has = "health_scored_without_security" in fact.get("caveats", ())
            assert has is (h not in security), (h, f)
        if row["health_band"]["value"] in ("Good", "Excellent") and h not in security:
            good_without += 1
            dossier = _resolve(snap, row["rows"]["dossier"])
            j = next(j for j, e in enumerate(dossier["exposures"]) if e["axis"] == "Security posture")
            assert {"pointer": row["rows"]["dossier"] + f"/exposures/{j}", "role": "witness"} in \
                row["health_band"]["refs"]
    assert good_without == sum(1 for r in snap["health_scores"]
                               if r["band"] in ("Good", "Excellent") and r["switch"] not in security) > 0


def test_i6_unscored_devices_are_not_assessed(snaps, payloads, docs):
    p = payloads["c"]
    for row in p["inventory"]["devices"]["rows"]["items"]:
        for f in ("health_score", "health_band"):
            assert _sv(row[f]) == (NA, None), (row["host"], f)
            assert "Insufficient Data" in row[f]["reason"]
        assert row["role"]["state"] == PUB
    page = _doc(docs, "c", "core1")["device"]["health"]
    assert page["score"]["state"] == page["band"]["state"] == page["deductions"]["state"] == NA
    assert all(it["fact"]["state"] == NA for it in page["deductions"]["items"])
    assert "compute_health_scores" in uip.DOMAIN_STATE_OWNERS[NA]


# --------------------------------------------------------------------------------------------------
# I7 -- failed phases: analysis_unavailable, never a clean value
# --------------------------------------------------------------------------------------------------
def _failed_idx(snap, label):
    return snap["assessment_integrity"]["failed_phases"].index(label)


@pytest.mark.parametrize("name", ("hf", "real"))
def test_i7_failed_health_phase(name, snaps, payloads):
    snap, p = snaps[name], payloads[name]
    idx = _failed_idx(snap, "Health Scores")
    rows = p["inventory"]["devices"]["rows"]
    assert rows["state"] == PUB and rows["items"]
    n_model = 0
    for row in rows["items"]:
        for f in ("health_score", "health_band", "role"):
            if row[f]["reason"].startswith("not collected: collection_completeness lists"):
                continue                                                         # a blind device, owner order
            assert _sv(row[f]) == (AU, None), (row["host"], f)
            assert {"pointer": f"/assessment_integrity/failed_phases/{idx}", "role": "failure_record"} \
                in row[f]["refs"], (row["host"], f)
        n_model += row["model"]["state"] == PUB
    assert n_model


@pytest.mark.parametrize("name", ("pf", "real"))
def test_i7_failed_punchlist_phase(name, snaps, payloads, docs):
    snap, p = snaps[name], payloads[name]
    idx = _failed_idx(snap, "Migration Punch-List")
    fnd = p["findings"]
    assert fnd["rows"]["state"] == AU and fnd["total"]["state"] == AU
    assert {"pointer": f"/assessment_integrity/failed_phases/{idx}", "role": "failure_record"} in fnd["rows"]["refs"]
    for host, doc in docs[name]:
        if isinstance(host, str) and host in _roster_hosts(snap):
            assert doc["device"]["findings"]["state"] == AU, host


@pytest.mark.parametrize("name", ("ef", "real"))
def test_i7_failed_endpoint_phase(name, payloads):
    p = payloads[name]
    ep = p["inventory"]["endpoints"]
    assert ep["rows"]["state"] == AU and ep["total"]["state"] == AU
    assert ep["shared_ip"]["state"] == AU and ep["dual_homed"]["state"] == AU
    vlans = p["inventory"]["vlans"]["rows"]["items"]
    if name == "ef":
        assert vlans
    for row in vlans:
        assert row["endpoint_count"]["state"] == AU and row["endpoint_mix"]["state"] == AU


@pytest.mark.parametrize("name", ALL_CASES)
def test_i7_a_basis_ref_to_a_failed_section_is_unavailable(name, snaps, payloads, docs):
    snap = snaps[name] if isinstance(snaps[name], dict) else {}
    direct = ssot.failed_sections(snap)[0]
    failed = {_ptr(sec) for sec in direct}
    checked = 0
    roots = [payloads[name]["inventory"], payloads[name]["findings"]] + [d["device"] for _h, d in docs[name]]
    for root in roots:
        for where, fact in _walk_facts(root):
            if (any(r["role"] == "basis" and r["pointer"] in failed for r in fact["refs"])
                    or fact["subject"] in failed):
                checked += 1
                assert fact["state"] == AU, (where, fact["state"], fact["refs"])
    if name in ("hf", "pf", "ef", "real"):
        assert checked >= 1


# --------------------------------------------------------------------------------------------------
# I8 -- the move-group label gate
# --------------------------------------------------------------------------------------------------
def test_i8_move_group_values_over_no_labels_are_withheld(snaps, payloads, docs):
    p = payloads["a"]
    assert not any(isinstance(g, dict) and g.get("group") for g in snaps["a"]["move_groups"])
    for row in p["findings"]["rows"]["items"]:
        assert _sv(row["wave"]) == (NC, None) and "no 'group' label" in row["wave"]["reason"]
    for row in p["inventory"]["endpoints"]["dual_homed"]["items"]:
        for f in ("move_groups", "split_across_groups"):
            assert _sv(row[f]) == (NC, None) and "no 'group' label" in row[f]["reason"], f
    items = _doc(docs, "a", "core1")["device"]["remediation"]["items"]["items"]
    assert items and all(it["wave"]["state"] == NC for it in items)
    q = payloads["mg"]
    split = [row for row in q["inventory"]["endpoints"]["dual_homed"]["items"]]
    assert split and all(row["split_across_groups"]["state"] == PUB for row in split)
    raw = snaps["mg"]["endpoint_dependencies"]["dual_homed"]
    assert [row["move_groups"]["value"] for row in split] == [r["move_groups"] for r in raw]
    assert all(row["wave"]["state"] in (PUB, CBE) for row in q["findings"]["rows"]["items"])
    items = _doc(docs, "mg", "core1")["device"]["remediation"]["items"]["items"]
    assert items and all(it["wave"]["state"] in (PUB, CBE) for it in items)


# --------------------------------------------------------------------------------------------------
# I9 -- contradictions with the producer's rule are unverified
# --------------------------------------------------------------------------------------------------
def test_i9_contradictions_are_unverified(snaps, payloads):
    rows = payloads["g_punch_bad"]["findings"]["rows"]["items"]
    assert rows[0]["severity"]["state"] == UV and rows[0]["rank"]["state"] == UV      # 'medium' is no severity
    assert rows[1]["rank"]["state"] == UV and rows[1]["severity"]["state"] == PUB
    assert rows[2]["priority"]["state"] == UV
    assert rows[3]["priority"]["state"] == rows[3]["rank"]["state"] == PUB
    dup = payloads["dup"]
    host = snaps["dup"]["health_scores"][0]["switch"]
    row = _row_for(dup, host)
    for f in ("health_score", "health_band", "role"):
        assert row[f]["state"] == UV, f
        assert sum(r["role"] == "witness" and r["pointer"].startswith("/health_scores/") for r in row[f]["refs"]) == 2
    assert row["rows"]["health"] is None
    bumped = copy.deepcopy(snaps["a"])
    bumped["collection_completeness"]["summary"]["inventory"] += 1
    total = uip.project_inventory(bumped)["devices"]["total"]
    assert total["state"] == UV and "number" in total["reason"]
    deep = payloads["g_deep_section"]["findings"]
    assert deep["rows"]["state"] == UV and deep["total"]["state"] == UV
    for row in deep["rows"]["items"]:
        assert row["title"]["state"] == UV


def test_i9_blind_spots_join_the_inventory(snaps, payloads, docs):
    snap, p = snaps["bl"], payloads["bl"]
    ghost = _row_for(p, "ghost1")
    assert ghost["rosters"] == {"devices": False, "collection_completeness": True}
    assert ghost["pointer"] == "/collection_completeness/devices/0"
    assert _sv(ghost["collection_status"]) == (PUB, "not collected")
    for f in ("model", "health_score", "lifecycle_band", "risk_band"):
        assert ghost[f]["state"] == NC and "lists this device as not collected" in ghost[f]["reason"], f
        assert {"pointer": "/collection_completeness/devices/0", "role": "witness"} in ghost[f]["refs"]
    assert _sv(_row_for(p, "access2")["collection_status"]) == (PUB, "partial")
    assert _row_for(p, "access2")["model"]["state"] == PUB
    assert _sv(p["inventory"]["devices"]["total"]) == (PUB, len(_inventory_hosts(snap)))
    page = _doc(docs, "bl", "ghost1")["device"]
    assert page["rosters"] == {"devices": False, "collection_completeness": True, "cable_map": False}
    assert _sv(page["collection"]["status"]) == (PUB, "not collected")
    assert page["identity"]["model"]["state"] == NC and page["interfaces"]["rows"]["state"] == NC
    q = payloads["bl_nc"]
    row = _row_for(q, "access1")
    assert _sv(row["collection_status"]) == (PUB, "not collected")
    assert row["model"]["state"] == row["health_score"]["state"] == NC
    assert _row_for(q, "access2")["model"]["state"] == PUB
    page = _doc(docs, "bl_nc", "access1")["device"]
    assert page["identity"]["model"]["state"] == NC and page["security"]["checks"]["state"] == NC
    assert page["interfaces"]["rows"]["state"] == NC


def test_i9_a_cable_map_peer_is_never_a_clean_collection(snaps, docs):
    snap = snaps["a"]
    peers = [n["host"] for n in snap["cable_map"]["nodes"] if n["collected"] is False]
    assert peers
    for host in peers:
        page = _doc(docs, "a", host)["device"]
        assert page["rosters"] == {"devices": False, "collection_completeness": False, "cable_map": True}
        for f in ("status", "data_quality", "missing"):
            fact = page["collection"][f]
            assert fact["state"] == NC and "only its neighbours reported it" in fact["reason"], (host, f)
        assert page["identity"]["model"]["state"] == NC
        cables = [i for i, c in enumerate(snap["cable_map"]["cables"]) if host in (c["a"], c["b"])]
        assert [it["index"] for it in page["links"]["items"]] == cables and cables
        assert page["endpoints"]["state"] == NC                     # no interface parse: absence is no clean result
    # a device in the devices map that collection_completeness does not list IS covered: collected but empty
    assert _doc(docs, "a", "core1")["device"]["collection"]["status"]["state"] == CBE


def test_i9_unknown_and_non_text_hosts_claim_nothing(docs):
    for host in ("", "no-such", "a/b~c.d", 7, None):
        page = _doc(docs, "a", host)["device"]
        want = NC if isinstance(host, str) else UV
        assert page["rosters"] == {"devices": False, "collection_completeness": False, "cable_map": False}
        facts = list(_walk_facts(page))
        assert len(facts) > 40
        for where, fact in facts:
            if where.endswith("/deductions_cap/total"):
                assert fact["state"] == NC and fact["refs"] == []    # host-independent: no owner publishes it
                continue
            assert fact["state"] == want and fact["refs"] == [], (host, where, fact)
            if "items" in fact:
                assert fact["items"] == [], (host, where)


# --------------------------------------------------------------------------------------------------
# I10 -- total on garbage
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", tuple(GARBAGE))
def test_i10_total_on_garbage(name, snaps, payloads, docs):
    p = payloads[name]
    inv, fnd = p["inventory"], p["findings"]
    for where, fact in _walk_facts({"inventory": inv, "findings": fnd}):
        if fact["state"] == PUB and isinstance(fact.get("value"), int) and not isinstance(fact["value"], bool):
            assert 0 <= fact["value"] <= uip.JS_MAX_SAFE_INT, where
    if name in _ALL_NC:
        for where, fact in _walk_facts({"inventory": inv, "findings": fnd}):
            assert fact["state"] == NC, (where, fact)
    if name == "g_huge":
        assert inv["devices"]["total"]["state"] == UV
    if name == "g_devices_int":
        assert inv["devices"]["rows"]["state"] == UV and inv["devices"]["rows"]["items"] == []
    if name == "g_devices_rowint":
        row = _row_for(p, "x")
        assert row["model"]["state"] == UV and "not an object" in row["model"]["reason"]
    if name in ("g_if_deep", "g_if_host_deep"):
        page = _doc(docs, name, "sw1")["device"]
        assert page["interfaces"]["rows"]["state"] == UV
    if name == "g_ep_bad":
        rows = inv["endpoints"]["rows"]["items"]
        assert [r["host"]["state"] for r in rows] == [UV, UV, UV]
        assert rows[2]["port"]["state"] == NC
    if name == "g_phys_bad":
        hosts = sorted(snaps[name]["devices"])
        for host, f in ((hosts[0], "num_modules"), (hosts[1], "total_ports"), (hosts[2], "num_power_supplies"),
                        (hosts[3], "active_ports")):
            assert uip.project_device(snaps[name], host)["device"]["physical"][f]["state"] == UV, (host, f)
    if name == "g_fhrp_bad":
        assert inv["vlans"]["rows"]["items"][0]["fhrp"]["state"] == UV
    if name.startswith("g_poison"):
        dumped = json.dumps(p, allow_nan=False)
        assert "NaN" not in dumped and "Infinity" not in dumped


# --------------------------------------------------------------------------------------------------
# I11 -- deterministic, key-order independent, never mutates or aliases, pure
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "bl", "real", "odd"))
def test_i11_deterministic_and_key_order_independent(name, snaps, payloads):
    snap = snaps[name]
    reordered = json.loads(json.dumps(snap, sort_keys=True))
    assert uip.project_inventory(reordered) == payloads[name]["inventory"]
    assert uip.project_findings(reordered) == payloads[name]["findings"]
    for host in _roster_hosts(snap)[:6]:
        assert uip.project_device(reordered, host) == uip.project_device(snap, host)
        first = json.dumps(uip.project_device(snap, host), sort_keys=True, allow_nan=False)
        assert first == json.dumps(uip.project_device(snap, host), sort_keys=True, allow_nan=False)


def test_i11_never_mutates_and_never_aliases(snaps):
    snap = copy.deepcopy(snaps["a"])
    before = copy.deepcopy(snap)
    inv, fnd, doc = uip.project_inventory(snap), uip.project_findings(snap), uip.project_device(snap, "core1")
    assert snap == before
    for out in (inv, fnd, doc):
        _mutate_everything(out)
    assert snap == before
    assert uip.project_device(snap, "core1") == uip.project_device(before, "core1")
    again = uip.project_device(snap, "core1")["device"]["limitations"]
    assert [lim["applies_to"] for lim in again] == [list(lim["applies_to"]) for lim in uip.DEVICE_LIMITATIONS]


def test_i11_pure_no_file_socket_or_process_io(snaps, payloads, monkeypatch):
    expected_doc = uip.project_device(snaps["a"], "core1")

    def _no_io(*_a, **_kw):
        raise AssertionError("ui_projection performed I/O")

    for target, attr in ((builtins, "open"), (io, "open"), (os, "open"), (socket, "socket"),
                         (socket, "create_connection"), (subprocess, "Popen")):
        monkeypatch.setattr(target, attr, _no_io)
    assert uip.project_inventory(snaps["a"]) == payloads["a"]["inventory"]
    assert uip.project_findings(snaps["real"]) == payloads["real"]["findings"]
    assert uip.project_device(snaps["a"], "core1") == expected_doc


# --------------------------------------------------------------------------------------------------
# I12 -- every copied vocabulary and table is held against its owner
# --------------------------------------------------------------------------------------------------
def _function_ast(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _str_constants(node):
    return {c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)}


def test_i12_vocabularies_equal_their_owners():
    assert dict(uip.PUNCH_RANK) == analyze._PUNCH_RANK
    assert set(analyze._PUNCH_RANK) <= set(uip.SEVERITIES)
    assert tuple(analyze._REMEDIATION_RANK) == uip.SEVERITIES
    assert uip.DOSSIER_BANDS == analyze._DOSSIER_BANDS
    assert uip.VLAN_READINESS == tuple(analyze._VLAN_CUTOVER_READY_RANK)
    assert uip.ENDPOINT_CONFIDENCES == tuple(analyze._EP_CONF.values())
    assert uip.NOT_OBSERVED_SENTINEL == analyze.VLAN_CUTOVER_NOT_OBSERVED
    assert uip.NRFU_NOT_OBSERVED == nrfu_export.NOT_OBSERVED
    assert uip.PUNCH_BASIS_UNPUBLISHED == analyze.PUNCH_BASIS_UNPUBLISHED
    assert uip.PUNCH_CONFIDENCE_UNPUBLISHED == analyze.PUNCH_CONFIDENCE_UNPUBLISHED
    assert uip.HEALTH_BAND_NOT_SCORED == ssot._HEALTH_BAND_NOT_SCORED
    fields = dataclasses.fields(DevicePhysical)
    ints = tuple(f.name for f in fields if f.type in (int, "int") and f.default == 0)
    strs = tuple(f.name for f in fields if f.type in (str, "str") and f.name != "hostname")
    assert uip.DEVICE_PHYSICAL_ZERO_DEFAULTS == ints
    assert uip.DEVICE_PHYSICAL_TEXT == strs
    assert set(uip.IDENTITY_FIELDS) | set(uip.PHYSICAL_TEXT_FIELDS) == set(strs)
    assert not set(uip.IDENTITY_FIELDS) & set(uip.PHYSICAL_TEXT_FIELDS)
    assert "active_ports" in {f.name for f in fields} and DevicePhysical().active_ports is None
    if_fields = {f.name for f in dataclasses.fields(InterfaceData)}
    assert set(uip.IF_COLUMNS) <= if_fields and len(set(uip.IF_COLUMNS)) == len(uip.IF_COLUMNS)


def test_i12_literal_vocabularies_are_held_against_the_producer_source():
    exposure, non_literal = set(), []
    for node in ast.walk(_function_ast(analyze.compute_device_dossiers)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ax":
            arg = node.args[1] if len(node.args) > 1 else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                exposure.add(arg.value)
            else:
                non_literal.append(ast.dump(node)[:120])
    assert not non_literal and exposure == set(uip.EXPOSURE_STATES)
    statuses = set()
    for node in ast.walk(_function_ast(analyze.compute_collection_completeness)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "status" for t in node.targets):
            statuses |= _str_constants(node.value)
    assert statuses - {"complete"} == set(uip.CC_STATUSES) and "complete" in statuses
    sec_status, sec_sev, grade = set(), {v[1] for v in parse_mod._SEC_CHECKS.values()} | {"info"}, set()
    for node in ast.walk(_function_ast(parse_mod.parse_security)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "add":
            sec_status |= _str_constants(node.args[1])
            for kw in node.keywords:
                if kw.arg == "severity":
                    sec_sev |= _str_constants(kw.value)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "grade" for t in node.targets):
            grade |= _str_constants(node.value)
    assert sec_status == set(uip.SEC_STATUSES)
    assert sec_sev == set(uip.SEC_SEVERITIES)
    assert grade == set(uip.SEC_GRADES)
    op = set()
    for node in ast.walk(_function_ast(analyze.compute_cable_map)):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == "op_status":
                    op |= _str_constants(node.value)
    assert op == set(uip.OP_STATUSES)


def test_i12_caps_and_move_group_label_are_held_against_the_producer_source():
    for key, fn in (("health_scores[].deductions", analyze.compute_health_scores),
                    ("endpoint_dependencies.dual_homed[].ports", analyze.compute_endpoint_dependencies),
                    ("remediation_plan[].why", analyze.compute_remediation_plan)):
        uppers = {node.slice.upper.value for node in ast.walk(_function_ast(fn))
                  if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)
                  and node.slice.lower is None and isinstance(node.slice.upper, ast.Constant)}
        assert uip.ENGINE_LIST_CAPS[key] in uppers, (key, uppers)
    assert len(uip.ENGINE_LIST_CAPS) == 3
    for fn in (analyze.compute_migration_punchlist, analyze.compute_remediation_plan,
               analyze.compute_device_dossiers, analyze.compute_endpoint_dependencies):
        reads = [node for node in ast.walk(_function_ast(fn))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                 and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == uip.MOVE_GROUP_LABEL]
        assert reads, fn.__name__
    keys = set()
    for node in ast.walk(_function_ast(analyze.compute_move_groups)):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys if isinstance(k, ast.Constant)}
    # the engine gap this projection gates on: when compute_move_groups writes a label, remove the gate
    assert "switches" in keys and uip.MOVE_GROUP_LABEL not in keys


def test_i12_tables_are_held_against_the_producer_signatures():
    sample = _sample()
    vparams = {"interfaces" if p == "all_interfaces" else p
               for p in inspect.signature(analyze.compute_vlan_cutover_matrix).parameters}
    row_keys = set()
    for node in ast.walk(_function_ast(analyze.compute_vlan_cutover_matrix)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "rows"
                and node.args and isinstance(node.args[0], ast.Dict)):
            row_keys |= {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
    assert set(uip.VLAN_FIELD_BASIS) == row_keys == set(sample["vlan_cutover"][0])
    for field, basis in uip.VLAN_FIELD_BASIS.items():
        assert set(basis) <= vparams and set(basis) <= set(sample), (field, basis)
        assert len(set(basis)) == len(basis), field
    pparams = set(inspect.signature(analyze.compute_migration_punchlist).parameters)
    assert set(uip.PUNCHLIST_INPUTS) == {p for p in pparams if p in sample}
    assert isinstance(uip.VLAN_FIELD_BASIS, type(uip.AXIS_BASIS))
    assert isinstance(uip.ENGINE_LIST_CAPS, type(uip.AXIS_BASIS)) and isinstance(uip.PUNCH_RANK, type(uip.AXIS_BASIS))


# --------------------------------------------------------------------------------------------------
# I13 -- no invented numbers
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "bl", "mg", "real", "g_phys_bad", "g_poison_str"))
def test_i13_every_published_number_is_the_owners(name, snaps, payloads, docs):
    snap = snaps[name] if isinstance(snaps[name], dict) else {}
    roots = [payloads[name]["inventory"], payloads[name]["findings"]] + [d["device"] for _h, d in docs[name]]
    n = 0
    for root in roots:
        for where, fact in _walk_facts(root):
            value = fact.get("value")
            if fact["state"] != PUB or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            n += 1
            if fact["subject"] is not None:
                assert _resolve(snap, fact["subject"]) == value, (where, fact["subject"], value)
            else:
                witness = [r["pointer"] for r in fact["refs"] if r["role"] == "witness"]
                assert witness, where
                assert value == len(_resolve(snap, witness[0])), (where, witness[0])
    if name in ("a", "real"):
        assert n > 20


# --------------------------------------------------------------------------------------------------
# I14 -- selections are the owner's key rules, nothing more
# --------------------------------------------------------------------------------------------------
def _digit(value):
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    return int(text) if text.isdigit() else None


@pytest.mark.parametrize("name", ("a", "real", "mg"))
def test_i14_selections_follow_the_owners_key_rules(name, snaps, payloads, docs):
    snap, p = snaps[name], payloads[name]
    punch = snap.get("punchlist") or []
    eps = snap.get("endpoint_identity") or []
    for host, doc in docs[name]:
        if not isinstance(host, str) or host not in _roster_hosts(snap):
            continue
        page = doc["device"]
        if page["findings"]["state"] == PUB:
            assert [it["index"] for it in page["findings"]["items"]] == \
                [i for i, r in enumerate(punch) if host in r["devices"]]
        if page["endpoints"]["state"] == PUB:
            assert [it["index"] for it in page["endpoints"]["items"]] == \
                [i for i, r in enumerate(eps) if r["host"] == host]
        tn = [i for i, r in enumerate(snap.get("trunk_native") or []) if host in (r["a_host"], r["b_host"])]
        assert [it["index"] for it in page["native_vlan_mismatches"]["items"]] == tn
    l3 = snap.get("l3_forwarding") or []
    roots = snap.get("stp_roots") or {}
    for row in p["inventory"]["vlans"]["rows"]["items"]:
        vid = row["vlan"]["value"]
        sel = row["selections"]
        assert sel["endpoints"] == [i for i, r in enumerate(eps) if _digit(r.get("vlan")) == vid]
        assert sel["gateways"] == [i for i, r in enumerate(l3) if _digit(r.get("vlan")) == vid]
        want = sorted(_ptr("stp_roots", h, k) for h in roots for k, rec in roots[h].items()
                      if k.isdigit() and int(k) == vid and isinstance(rec, dict) and not rec.get("is_mst"))
        assert sel["stp_roots"] == want
    deps = snap.get("endpoint_dependencies") or {}
    shared = deps.get("shared_ip") or []
    dual = deps.get("dual_homed") or []
    vrows = snap.get("vlan_cutover") or []
    for item, raw in zip(p["inventory"]["endpoints"]["rows"]["items"], eps):
        sel = item["selections"]
        ip = raw["ip"].strip()
        assert sel["shared_ip"] == [k for k, r in enumerate(shared) if ip and r["ip"] == ip]
        assert sel["dual_homed"] == [k for k, r in enumerate(dual) if r["mac"] == raw["mac"].lower()]
        matches = [k for k, r in enumerate(vrows) if r["vlan"] == _digit(raw["vlan"])]
        assert sel["vlan_row"] == (matches[0] if len(matches) == 1 else None)
        iface = (snap.get("interfaces") or {}).get(raw["host"], {}).get(raw["port"])
        assert sel["interface"] == (_ptr("interfaces", raw["host"], raw["port"]) if iface is not None else None)


# --------------------------------------------------------------------------------------------------
# I15 -- scale: a 300-device / 20k-interface fleet
# --------------------------------------------------------------------------------------------------
def _big(sample, n_hosts=300, ports=67, eps_per_host=30, punch_copies=14, n_blind=20):
    s = copy.deepcopy(sample)
    templates = sorted(sample["devices"])
    hosts = [f"sw{i:03d}" for i in range(n_hosts)]
    src = {h: templates[i % len(templates)] for i, h in enumerate(hosts)}
    s["devices"] = {h: dict(sample["devices"][src[h]], hostname=h) for h in hosts}
    ifs = {}
    for h in hosts:
        tpl = list(sample["interfaces"][src[h]].values())
        ifs[h] = {f"Gi1/0/{k + 1}": dict(tpl[k % len(tpl)], port=f"Gi1/0/{k + 1}") for k in range(ports)}
    s["interfaces"] = ifs

    def by(rows, key):
        return {r[key]: r for r in rows}

    hs = by(sample["health_scores"], "switch")
    s["health_scores"] = [dict(hs[src[h]], switch=h) for h in hosts if src[h] in hs]
    lc = by(sample["lifecycle_risk"]["per_device"], "host")
    s["lifecycle_risk"]["per_device"] = [dict(lc[src[h]], host=h) for h in hosts if src[h] in lc]
    dd = by(sample["device_dossiers"]["per_device"], "host")
    s["device_dossiers"]["per_device"] = [dict(dd[src[h]], host=h) for h in hosts if src[h] in dd]
    s["security"] = {h: sample["security"][src[h]] for h in hosts if src[h] in sample["security"]}
    rp = sample["remediation_plan"]["by_device"]
    s["remediation_plan"]["by_device"] = {h: [dict(it, device=h) for it in rp[src[h]]] for h in hosts if src[h] in rp}
    cm = sample["coverage_matrix"]["by_device"]
    s["coverage_matrix"]["by_device"] = {h: dict(cm[src[h]]) for h in hosts if src[h] in cm}
    s["cable_map"]["cables"] = [dict(c, a=h) for h in hosts for c in sample["cable_map"]["cables"] if c["a"] == src[h]]
    s["routes"] = {h: sample["routes"][src[h]] for h in hosts if src[h] in sample["routes"]}
    s["routing_neighbors"] = {h: sample["routing_neighbors"][src[h]] for h in hosts
                              if src[h] in sample["routing_neighbors"]}
    waves = []
    for w in sample["nrfu_commands"]["waves"]:
        tpl_dev = by(w["devices"], "host")
        waves.append(dict(w, devices=[dict(tpl_dev[src[h]], host=h) for h in hosts if src[h] in tpl_dev]))
    s["nrfu_commands"]["waves"] = waves
    ep_tpl = sample["endpoint_identity"]
    s["endpoint_identity"] = [dict(ep_tpl[(i * eps_per_host + k) % len(ep_tpl)], host=h, port=f"Gi1/0/{k + 1}")
                              for i, h in enumerate(hosts) for k in range(eps_per_host)]
    punch = [dict(r) for _c in range(punch_copies) for r in sample["punchlist"]]
    punch.sort(key=lambda x: (-x["rank"], x["category"], x["title"]))
    for i, r in enumerate(punch, 1):
        r["priority"] = i
    s["punchlist"] = punch
    s["collection_completeness"] = {
        "summary": {"inventory": n_hosts, "complete": n_hosts - n_blind, "partial": 0, "not_collected": n_blind},
        "devices": [{"host": hosts[i], "status": "not collected", "data_quality": 0, "missing": ["show version"]}
                    for i in range(n_blind)]}
    return s, hosts


def _truncate(obj, keep=25):
    if isinstance(obj, dict):
        out = {k: _truncate(v, keep) for k, v in obj.items()}
        if _is_fact(out) and isinstance(out.get("items"), list):
            out["items"] = out["items"][:keep]
        return out
    if isinstance(obj, list):
        return [_truncate(v, keep) for v in obj]
    return obj


def test_i15_scale_300_devices_20k_interfaces(snaps, validator, doc_validator):
    big, hosts = _big(snaps["a"])
    assert sum(len(v) for v in big["interfaces"].values()) >= 20000
    assert len(big["endpoint_identity"]) >= 9000
    uip.project(snaps["a"])                                    # warm-up: the one-time lazy imports
    start = time.perf_counter()
    payload = uip.project(big)
    elapsed = time.perf_counter() - start
    assert elapsed <= 30.0, elapsed
    inv = payload["inventory"]
    assert _sv(inv["devices"]["total"]) == (PUB, 300)
    assert [r["host"] for r in inv["devices"]["rows"]["items"]] == hosts
    assert _sv(inv["endpoints"]["total"]) == (PUB, len(big["endpoint_identity"]))
    assert _sv(payload["findings"]["total"]) == (PUB, len(big["punchlist"]))
    blind = [r for r in inv["devices"]["rows"]["items"] if r["collection_status"]["state"] == PUB]
    assert len(blind) == 20 and all(r["model"]["state"] == NC for r in blind)
    json.dumps(payload, allow_nan=False)
    small = _truncate(payload)
    errors = sorted(validator.iter_errors(small), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    for host in (hosts[0], hosts[150], hosts[299]):
        start = time.perf_counter()
        doc = uip.project_device(big, host)
        took = time.perf_counter() - start
        assert took <= 5.0, (host, took)
        assert not list(doc_validator.iter_errors(_truncate(doc)))
        json.dumps(doc, allow_nan=False)
    assert uip.project_device(big, hosts[150])["device"]["interfaces"]["rows"]["state"] == PUB
    assert len(uip.project_device(big, hosts[150])["device"]["interfaces"]["rows"]["items"]) == 67
