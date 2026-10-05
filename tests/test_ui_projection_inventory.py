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

from cisco_toolkit import analyze, coverage_matrix, nrfu_export, ssot, stp_topology
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


def _device_doc_limitation_ids():
    """What a standalone device document must define: its own limitations, then every payload limitation a device
    page can cite (in payload order)."""
    return ([lim["id"] for lim in uip.DEVICE_LIMITATIONS]
            + [lim["id"] for lim in uip.LIMITATIONS if lim["id"] in uip.DEVICE_CITED_LIMITATIONS])


def _covered(where, pointers):
    return any(where == p or where.startswith(p + "/") for p in pointers)


def _cc_row(snap, host):
    """The blind-spot row of `host` by the owner's rule (ssot._device_not_collected: case/space-insensitive, first
    match wins), read independently."""
    for i, r in enumerate(snap["collection_completeness"]["devices"]):
        if isinstance(r, dict) and isinstance(r.get("host"), str) and r["host"].strip().lower() == host.strip().lower():
            return i, r
    return None, None


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
        g["group"] = analyze.move_group_label(i)
    # A labelled control must carry the same derived joins as the real current producers. The legacy
    # sample can have empty waves; merely adding labels would now create contradictory source records.
    host_groups, ordinal = analyze.move_group_host_index(snap["move_groups"])
    for finding in snap["punchlist"]:
        labels = analyze._ordered_group_labels(
            (host_groups.get(h, analyze.MOVE_GROUP_UNSCHEDULED) for h in finding["devices"]), ordinal)
        finding["wave"] = ", ".join(labels)
    for host, rows in snap["remediation_plan"]["by_device"].items():
        for row in rows:
            row["wave"] = host_groups.get(host, analyze.MOVE_GROUP_UNSCHEDULED)
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
CORE = ("a", "b", "c", "hf", "pf", "ef", "fi", "real", "real2", "bl", "bl_nc", "mg", "dup", "odd")
ALL_CASES = CORE + tuple(GARBAGE)
REAL_FAILED = ("Health Scores", "Migration Punch-List", "Endpoint identity")
#: The second real run: one inventory host the collection never reached, and one host whose CDP capture is gone.
GHOST = {"hostname": "ghost-sw", "ip": "10.0.99.200", "username": "svc-audit", "password": "x", "platform": "ios"}
PARTIAL = ("access1", "show cdp neighbors detail")


def _failure_impact_failed(sample):
    """'Failure Impact' failed: its fallback feeds the dossiers, which ssot does NOT mark (the one-hop gap).
    The dossiers and the brief are recomputed with the REAL producers over the fallback."""
    snap = copy.deepcopy(sample)
    snap["failure_impact"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Failure Impact"]}
    params = inspect.signature(analyze.compute_device_dossiers).parameters
    snap["device_dossiers"] = analyze.compute_device_dossiers(**{p: snap.get(p) for p in params})
    return _rebrief(snap, sample)


def _run_real_engine(tmp_path, mp, *, fail=True, extra_devices=(), drop=()):
    """The real pipeline (pattern of tests/test_ssot_failed_phase_abstention.py::_run_engine, copied rather than
    imported): with `fail`, three phases are forced to fail; `extra_devices` join devices.json with no capture
    directory; each ``(host, command)`` in `drop` has its capture removed."""
    mp.syspath_prepend(str(ROOT / "tests"))
    mp.syspath_prepend(str(ROOT))
    mp.chdir(tmp_path)                       # before the engine import, so no log lands in the work tree
    import synthetic_fixtures as fx
    from openpyxl import Workbook
    import COLLECT_PARSE_V3_23_0 as cp
    collection = fx.write_collection(str(tmp_path / "collection"))
    for host, command in drop:
        os.remove(os.path.join(collection, host, fx.cmd_filename(command)))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(list(fx.DEVICES) + list(extra_devices)), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(str(template))
    out = tmp_path / "out.xlsx"
    mp.setattr(sys, "argv", ["cisco-assess", "--no-collect", "--collection-dir", collection,
                             "--devices-file", str(devices), "--template", str(template),
                             "--output", str(out), "--workers", "1", "--no-html", "--no-docx",
                             "--no-pptx", "--no-design", "--no-mop", "--no-crd", "--no-engagement",
                             "--no-opshandbook", "--no-archreview"])

    def _boom(*_a, **_kw):
        raise RuntimeError("synthetic phase failure")

    if fail:
        mp.setattr(cp, "compute_health_scores", _boom)
        mp.setattr(cp, "_punchlist", _boom)
        mp.setattr(cp, "compute_endpoint_identity", _boom)
    cp.main()
    return json.loads(pathlib.Path(str(out)[:-len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snaps(tmp_path_factory):
    sample = _sample()
    out = {"a": sample, "b": _minimal(), "c": _all_insufficient(sample), "hf": _health_failed(sample),
           "pf": _punch_failed(sample), "ef": _endpoints_failed(sample), "fi": _failure_impact_failed(sample),
           "bl": _blind_spots(sample), "bl_nc": _blind_existing(sample), "mg": _labelled_groups(sample),
           "dup": _duplicate_health(sample), "odd": _odd_hosts(sample)}
    with pytest.MonkeyPatch.context() as mp:
        out["real"] = _run_real_engine(tmp_path_factory.mktemp("uip_inventory_real_engine"), mp)
    with pytest.MonkeyPatch.context() as mp:
        out["real2"] = _run_real_engine(tmp_path_factory.mktemp("uip_inventory_real_blind"), mp, fail=False,
                                        extra_devices=(GHOST,), drop=(PARTIAL,))
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
    assert schema["required"] == ["schema", "engine", "overview", "trust", "inventory", "findings", "topology"]
    assert schema["properties"]["inventory"] == {"$ref": "#/$defs/Inventory"}
    assert schema["properties"]["findings"] == {"$ref": "#/$defs/Findings"}
    enums = {"LifecycleBandFact": uip.LIFECYCLE_BAND_ORDER, "RiskBandFact": uip.DOSSIER_BANDS,
             "SeverityFact": uip.SEVERITIES, "ReadinessFact": uip.VLAN_READINESS,
             "EndpointConfidenceFact": uip.ENDPOINT_CONFIDENCES, "CollectionStatusFact": uip.CC_STATUSES,
             "OpStatusFact": uip.OP_STATUSES, "CoverageStateFact": uip.COVERAGE_STATE_ORDER,
             "CoverageDimensionFact": uip.COVERAGE_DIMENSIONS,
             "CoverageVerdictSourceFact": uip.COVERAGE_VERDICT_SOURCES}
    for name, vocab in enums.items():
        assert _value_schema(d, name) == {"type": "string", "enum": list(vocab)}, name
    assert _value_schema(d, "TextListFact") == {"type": "array", "items": {"type": "string"}}
    assert d["ExposureValue"]["properties"]["state"]["enum"] == list(uip.EXPOSURE_STATES)
    assert d["CompoundValue"]["properties"]["severity"]["enum"] == list(uip.SEVERITIES)
    assert d["SecurityCheckValue"]["properties"]["severity"]["enum"] == list(uip.SEC_SEVERITIES)
    assert d["SecurityCheckValue"]["properties"]["status"]["enum"] == list(uip.SEC_STATUSES)
    assert d["SecuritySummaryValue"]["properties"]["grade"]["enum"] == list(uip.SEC_GRADES)
    assert d["CoverageCellValue"]["properties"]["state"]["enum"] == list(uip.COVERAGE_STATES)
    assert d["CoverageItem"]["required"] == ["axis", "pointer", "fact", "dimension", "verdict_source", "is_abstention"]
    assert d["CoverageItem"]["properties"] == {
        "axis": {"type": "string"}, "pointer": {"$ref": "#/$defs/Pointer"},
        "fact": {"$ref": "#/$defs/CoverageCellFact"},
        "dimension": {"$ref": "#/$defs/CoverageDimensionFact"},
        "verdict_source": {"$ref": "#/$defs/CoverageVerdictSourceFact"},
        "is_abstention": {"$ref": "#/$defs/FlagFact"},
    }
    assert d["DeviceCoverageRollup"]["required"] == ["worst", "n_abstained"]
    assert d["DeviceCoverageRollup"]["properties"] == {
        "worst": {"$ref": "#/$defs/CoverageStateFact"}, "n_abstained": {"$ref": "#/$defs/CountFact"},
    }
    assert d["DeviceRow"]["properties"]["coverage"] == {"$ref": "#/$defs/DeviceCoverageRollup"}
    assert d["DevicePage"]["properties"]["coverage_rollup"] == {"$ref": "#/$defs/DeviceCoverageRollup"}
    assert list(d["InterfaceCells"]["properties"]) == list(uip.IF_COLUMNS)
    assert d["InterfaceCells"]["required"] == list(uip.IF_COLUMNS)
    ids = [lim["id"] for lim in uip.LIMITATIONS] + [lim["id"] for lim in uip.DEVICE_LIMITATIONS]
    assert d["LimitationId"]["enum"] == ids and len(set(ids)) == len(ids)
    dev_lims = d["DevicePage"]["properties"]["limitations"]
    assert dev_lims["minItems"] == dev_lims["maxItems"] == len(_device_doc_limitation_ids())
    assert set(uip.DEVICE_CITED_LIMITATIONS) <= {lim["id"] for lim in uip.LIMITATIONS}
    assert d["DeviceDocument"]["required"] == ["schema", "engine", "device"]
    assert "$anchor" not in d["DeviceDocument"]          # Ajv 2020 strict rejects it: address #/$defs/DeviceDocument
    assert d["Cap"]["properties"]["total"] == {"$ref": "#/$defs/WithheldFact"}
    assert d["Cap"]["properties"]["reached"] == {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
    assert d["DeviceDocument"]["properties"]["schema"]["const"] == uip.SCHEMA
    for name in ("Inventory", "Findings", "DevicePage", "DeviceRow", "VlanRow", "EndpointRow", "FindingRow",
                 "DualHomedRow", "InterfaceRow", "CableRow", "RouteRow", "NeighborRow", "RemediationRow",
                 "NrfuCaseRow", "Cap", "RowRef", "FhrpValue", "FhrpMember", "CoverageItem", "DeviceCoverageRollup"):
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


def test_i0_schema_rejects_a_forged_device_document(docs, doc_validator):
    doc = _doc(docs, "a", "core1")
    assert doc_validator.is_valid(doc)
    forgeries = {
        "published_cap_total": lambda d: d["device"]["health"]["deductions_cap"].update(
            total={"state": PUB, "value": 9, "subject": None, "refs": [], "basis": "x"}),
        "short_limitations": lambda d: d["device"]["limitations"].pop(),
        "unknown_key": lambda d: d["device"].update(extra=1),
    }
    for name, forge in forgeries.items():
        forged = copy.deepcopy(doc)
        forge(forged)
        assert not doc_validator.is_valid(forged), name


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
    for host, doc in docs[name]:
        doc_ids = {lim["id"] for lim in doc["device"]["limitations"]}
        _check_facts(doc["device"], "/device", doc_ids, snap)            # self-contained: its OWN limitations
        for where, ptr in _walk_pointers(doc["device"]):
            if where.startswith("/limitations"):
                continue
            assert _resolve(snap, ptr) is not _MISSING, (host, where, ptr)
        assert [lim["id"] for lim in doc["device"]["limitations"]] == _device_doc_limitation_ids()
        for lim in doc["device"]["limitations"]:
            for pointer in lim["applies_to"]:
                assert pointer.startswith("/device/"), (lim["id"], pointer)
                assert _resolve(doc, pointer) is not _MISSING, (lim["id"], pointer)
    if name == "a":
        rows = p["inventory"]["devices"]["rows"]["items"]
        assert all(_resolve(snap, r["pointer"]) is not _MISSING for r in rows)
        roles = {r["role"] for _w, f in _walk_facts(p["inventory"]) for r in f["refs"]}
        assert {"subject", "witness"} <= roles


@pytest.mark.parametrize("name", ALL_CASES)
def test_i2_every_caveat_is_defined_where_it_is_used(name, payloads, docs):
    """A caveat names a limitation the SAME document defines, and one of that limitation's applies_to pointers
    prefixes the caveat's location (the whole payload, slice 1 included, and every standalone device document)."""
    p = payloads[name]
    lims = {lim["id"]: lim["applies_to"] for lim in p["trust"]["limitations"]}
    n = 0
    for where, fact in _walk_facts(p):
        for cav in fact.get("caveats", ()):
            n += 1
            assert cav in lims and _covered(where, lims[cav]), (where, cav)
    for host, doc in docs[name]:
        dl = {lim["id"]: lim["applies_to"] for lim in doc["device"]["limitations"]}
        for where, fact in _walk_facts(doc["device"], "/device"):
            for cav in fact.get("caveats", ()):
                n += 1
                assert cav in dl and _covered(where, dl[cav]), (host, where, cav)
    if name in ("a", "real2", "fi"):
        assert n > 50


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
        for item in page["coverage"]["items"]:
            source_rows = [row for row in snap["coverage_matrix"]["rows"]
                           if isinstance(row, dict) and row.get("device") == host and row.get("axis") == item["axis"]]
            assert len(source_rows) == 1, (host, item["axis"], source_rows)
            source = source_rows[0]
            assert _sv(item["fact"]) == (PUB, {"axis": item["axis"], "state": cm[item["axis"]]})
            for field in ("dimension", "verdict_source", "is_abstention"):
                assert _sv(item[field]) == (PUB, source[field]), (host, item["axis"], field)
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
        state = raw[vid].get("stp_root_state")
        if state is None or state == "not_observed":
            assert _sv(row["stp_root"]) == (NC, None)
            assert _sv(row["stp_root_default_election"]) == (NC, None)
        elif state == "ambiguous":
            assert _sv(row["stp_root"]) == _sv(row["stp_root_default_election"]) == (UV, None)
        else:
            assert state == "published"
            assert _sv(row["stp_root"]) == (PUB, raw[vid]["stp_root"])
            default = raw[vid]["stp_root_default_election"]
            assert _sv(row["stp_root_default_election"]) == ((PUB, default) if default is not None else (NC, None))
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
        assert page["deductions"]["state"] in (PUB, CBE)
        assert page["deductions_cap"]["reached"] is (n >= cap)
        assert page["deductions_cap"]["total"]["state"] == NC and page["deductions_cap"]["total"]["value"] is None
        assert ("engine_list_capped" in page["deductions"].get("caveats", ())) is (n >= cap), host
        reached += n >= cap
        short += n < cap
        assert [it["fact"]["value"] for it in page["deductions"]["items"]] == health[host]["deductions"]
    assert reached and short
    for row in p["inventory"]["endpoints"]["dual_homed"]["items"]:
        raw = _resolve(snap, row["pointer"])
        assert row["ports_cap"]["limit"] == uip.ENGINE_LIST_CAPS["endpoint_dependencies.dual_homed[].ports"]
        assert row["ports_cap"]["reached"] is (len(raw["ports"]) >= row["ports_cap"]["limit"])
        assert row["ports_cap"]["total"]["state"] == NC
    for host, doc in docs["c"]:                                  # an unreadable list reaches no cap
        if doc["device"]["health"]["deductions"]["state"] not in (PUB, CBE):
            assert doc["device"]["health"]["deductions_cap"]["reached"] is None, host
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
    legacy = copy.deepcopy(snaps["a"])
    for group in legacy["move_groups"]:
        group.pop("group", None)
    p = uip.project(legacy)
    assert not any(isinstance(g, dict) and g.get("group") for g in legacy["move_groups"])
    for row in p["findings"]["rows"]["items"]:
        assert _sv(row["wave"]) == (NC, None) and "no 'group' label" in row["wave"]["reason"]
    for row in p["inventory"]["endpoints"]["dual_homed"]["items"]:
        for f in ("move_groups", "split_across_groups"):
            assert _sv(row[f]) == (NC, None) and "no 'group' label" in row[f]["reason"], f
    items = uip.project_device(legacy, "core1")["device"]["remediation"]["items"]["items"]
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
            if where.endswith(("/deductions_cap/total", "/deduction_refs_cap/total")):
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
    want = ([list(lim["applies_to"]) for lim in uip.DEVICE_LIMITATIONS]
            + [list(uip.DEVICE_CITED_LIMITATIONS[lim["id"]]) for lim in uip.LIMITATIONS
               if lim["id"] in uip.DEVICE_CITED_LIMITATIONS])
    assert [lim["applies_to"] for lim in again] == want
    batch = uip.project_devices(snap, ["core1", "access1", "core1"])
    _mutate_everything(batch[0])
    assert batch[2] == uip.project_device(before, "core1")                # no container shared between documents


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
    assert uip.ESSENTIAL_LABELS == analyze._ESSENTIAL_LABELS
    assert uip.COVERAGE_STATE_ORDER == coverage_matrix.COVERAGE_STATE_ORDER == (
        "not_collected", "unverified", "unparsed", "partial", "not_observed", "covered")
    assert set(uip.COVERAGE_STATE_ORDER) == set(uip.COVERAGE_STATES)
    assert uip.COVERAGE_DIMENSIONS == coverage_matrix.COVERAGE_DIMENSIONS
    assert uip.COVERAGE_VERDICT_SOURCES == coverage_matrix.COVERAGE_VERDICT_SOURCES
    assert len(uip.COVERAGE_DIMENSIONS) == len(set(uip.COVERAGE_DIMENSIONS)) == 4
    assert len(uip.COVERAGE_VERDICT_SOURCES) == len(set(uip.COVERAGE_VERDICT_SOURCES)) == 4
    for block, needs in uip.SELECTION_NEEDS.items():
        assert set(needs) <= set(uip.ESSENTIAL_LABELS), block
    assert set(uip.ANALYSIS_SECTIONS) == {s for secs in ssot.PHASE_SECTIONS.values() for s in secs}
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
    dimensions, sources, non_literal_coverage = set(), set(), []
    for node in ast.walk(_function_ast(coverage_matrix.compute_coverage_matrix)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_row":
            for index, found in ((2, dimensions), (4, sources)):
                arg = node.args[index] if len(node.args) > index else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
                else:
                    non_literal_coverage.append(ast.dump(node)[:120])
    assert not non_literal_coverage, non_literal_coverage
    assert dimensions == set(uip.COVERAGE_DIMENSIONS)
    assert sources == set(uip.COVERAGE_VERDICT_SOURCES)
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


#: Every prefix slice ``x[:n]`` reachable from a producer this projection names, reviewed: the ENGINE_LIST_CAPS key
#: it is, or why it is no cap of a projected value. Keyed by (function, the slice's source text).
CAP_SITES = {
    ("analyze.compute_health_scores", "reasons[:8]"): "health_scores[].deductions",
    ("analyze.compute_health_scores", "reason_refs[:8]"): "health_scores[].deduction_refs",
    ("analyze._normalize_evidence_refs", "ordered[:cap]"):
        "exempt: evidence_refs uses the source-owned cap and publishes evidence_refs_total when truncated",
    ("analyze._evidence_ref", "text[:_EVIDENCE_CITE_MAX]"):
        "exempt: the bounded citation is preserved verbatim inside the typed reference",
    ("analyze.compute_endpoint_dependencies", "sorted(m['ports'])[:8]"): "endpoint_dependencies.dual_homed[].ports",
    ("analyze.compute_remediation_plan", "(why or '')[:300]"): "remediation_plan[].why",
    ("analyze.compute_vlan_cutover_matrix", "doms[:3]"): "vlan_cutover[].app_domain",
    ("analyze.compute_migration_punchlist", "s[:n]"): "punchlist[].detail",           # _clip(..., n=400)
    ("analyze.compute_executive_brief", "flags[:4]"):
        "exempt: the posture statement says in-band how many flags it holds back",
    ("analyze.compute_migration_readiness", "subjects[:8]"):
        "exempt: the IPv6 check note discloses exact '+N' omitted subjects and their full Cutover Validation/NRFU sinks",
    ("analyze.compute_failure_impact", "pv[:8]"):
        "exempt: detail prose says '+N more' in-band; full model counts remain separate and the projection discloses the 8-example cap",
    ("analyze._fmt_endpoint_mix", "items[:limit]"): "exempt: endpoint_mix says '+N more' in-band",
    ("analyze._classify_endpoint", "desc.strip()[:32]"):
        "exempt: a quoted fragment inside the evidence prose; the full description is on the interface record",
    ("analyze._classify_endpoint", "plat.strip()[:24]"): "exempt: a quoted fragment inside the evidence prose",
    ("analyze._static_vtp_safety_rows", "_strict_protocol_text(reason)[:180]"):
        "exempt: a bounded validator reason quoted inside punch-list prose, which the detail cap covers",
    ("analyze._static_vtp_safety_rows",
     "('vtp_safety_subject_scope.valid/attempted/reason + vtp_safety_baseline' if scope_abstention else "
     "f'vtp_safety_subject_scope[{host}] + protocol_assessability.rows[{host},VTP] + protocol_health[{host},VTP] + "
     "vtp_safety_baseline')[:300]"):
        "exempt: a length bound on a VTP row's source-key text, which is not projected",
    ("nrfu_export.compute_nrfu_commands", "up[:12]"): "exempt: the NRFU expected text says '+N more' in-band",
    ("nrfu_export._port_key", "p[:2]"): "exempt: a port-name sort key, not a value",
    ("excel._parse_track", "line.strip()[:40]"): "exempt: l3_forwarding values are not projected (only row indices)",
    ("excel._track_summary", "tr['objects'][:6]"): "exempt: l3_forwarding values are not projected (only row indices)",
    ("excel._xls_cell_value", "v[:_XLSX_MAX_CELL - len(note)]"): "exempt: the workbook cell writer, not the snapshot",
    ("analyze.compute_lifecycle_risk", "str(x or '')[:10]"): "exempt: the ISO date part of a timestamp",
    ("analyze.compute_lifecycle_risk", "str(s)[:10]"): "exempt: the ISO date part of a timestamp",
    ("analyze.compute_lifecycle_risk", "_retrieved_at[:10]"):
        "exempt: the retained registry retrieval date used to judge lifecycle freshness, not a projected list",
    ("parse.parse_security", "raw[:1]"): "exempt: a first-character test, not a value",
    ("analyze.compute_cable_map", "badges[:3]"): "exempt: badges are not projected",
    ("analyze.compute_device_dossiers",
     "[d['host'] for d in per_device if d['risk_band'] in ('Severe', 'Elevated')][:3]"):
        "exempt: the dossier summary headline is not projected",
    ("analyze.compute_device_dossiers", "[e['label'] for e in exposures if e['state'] == 'risk'][:3]"):
        "exempt: the dossier verdict prose is not projected",
    ("analyze.compute_device_dossiers", "[e['label'] for e in exposures if e['state'] == 'watch'][:3]"):
        "exempt: the dossier verdict prose is not projected",
    ("analyze.compute_device_dossiers", "watch_labels[:max(0, 3 - len(red_labels))]"):
        "exempt: the dossier verdict prose is not projected",
}
def _producer_roots():
    """Every ``<module>.<function>`` this projection names as an owner (its basis strings and limitation owners)."""
    import importlib
    import re
    names = set(re.findall(r"\b(analyze|build|parse|coverage_matrix|html|nrfu_export|excel|fib)\.([A-Za-z_]\w*)",
                           inspect.getsource(uip)))
    out = set()
    for mod, fn in names:
        module = importlib.import_module(f"cisco_toolkit.{mod}")
        if inspect.isfunction(getattr(module, fn, None)):
            out.add((module, fn))
    return out


def _prefix_slices():
    """``{(qualified function, slice source)}`` over every function reachable from the named producers by a direct
    call to a function of the same module (transitive), plus the producers themselves."""
    seen, queue, hits = set(), list(_producer_roots()), set()
    while queue:
        module, fn = queue.pop()
        if (module.__name__, fn) in seen:
            continue
        seen.add((module.__name__, fn))
        tree = _function_ast(getattr(module, fn))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                target = getattr(module, node.func.id, None)
                if inspect.isfunction(target) and target.__module__ == module.__name__:
                    queue.append((module, node.func.id))
            if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and node.slice.lower is None
                    and node.slice.upper is not None):
                hits.add((f"{module.__name__.rsplit('.', 1)[-1]}.{fn}", ast.unparse(node)))
    return hits, seen


def test_i12_every_engine_cap_is_registered_or_reviewed():
    """Structural, not a hand-kept list: every prefix slice reachable from a producer this projection names is either
    an ENGINE_LIST_CAPS entry (with the producer's own constant) or a reviewed exemption."""
    hits, seen = _prefix_slices()
    assert len(seen) > 20 and ("cisco_toolkit.analyze", "_classify_endpoint") in seen    # the walk is transitive
    assert ("cisco_toolkit.fib", "trace_fib_path") in seen  # the new path owner participates in the same guard
    assert hits - set(CAP_SITES) == set(), "unreviewed prefix slice(s): register a cap or an exemption"
    assert set(CAP_SITES) - hits == set(), "a reviewed slice no longer exists: drop it"
    registered = {v for v in CAP_SITES.values() if not v.startswith("exempt:")}
    assert registered == set(uip.ENGINE_LIST_CAPS)
    for (fn, text), key in CAP_SITES.items():
        if key in uip.ENGINE_LIST_CAPS and fn != "analyze.compute_migration_punchlist":
            assert f"[:{uip.ENGINE_LIST_CAPS[key]}]" in text, (fn, text, key)
    # the punch-list detail is cut by the producer's nested _clip(s, n=400): its default bound is the cap
    clip = next(n for n in ast.walk(_function_ast(analyze.compute_migration_punchlist))
                if isinstance(n, ast.FunctionDef) and n.name == "_clip")
    names = [a.arg for a in clip.args.args]
    default = clip.args.defaults[names.index("n") - (len(names) - len(clip.args.defaults))]
    assert ast.literal_eval(default) == uip.ENGINE_LIST_CAPS["punchlist[].detail"]
    assert uip.PUNCH_DETAIL_CLIP_MARKER in _str_constants(clip)


def test_i12_readiness_ipv6_subject_preview_keeps_its_exact_omission_and_source_disclosure():
    """Execute the actual producer's pure nested helpers, without hand-restating their clipping rule.

    The owner integration suite additionally proves full Validation/NRFU blocker retention in
    test_ipv6_routing_engine.test_readiness_note_is_bounded_but_validation_and_nrfu_keep_every_blocker.
    This proof targets the one new preview exemption and the projection's source disclosure.
    """
    tree = _function_ast(analyze.compute_migration_readiness)
    helpers = [copy.deepcopy(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name in {"ipv6_subject", "ipv6_subject_summary"}]
    assert {node.name for node in helpers} == {"ipv6_subject", "ipv6_subject_summary"}
    namespace = {"_strict_protocol_text": analyze._strict_protocol_text, "List": list}
    module = ast.fix_missing_locations(ast.Module(body=helpers, type_ignores=[]))
    exec(compile(module, "<readiness-owner-subject-summary>", "exec"), namespace)
    rows = [{"protocol": "OSPFv3", "peer": f"2001:db8::{i:04x}", "state_raw": "DOWN"} for i in range(12)]
    before = copy.deepcopy(rows)
    rendered = namespace["ipv6_subject_summary"](rows)
    assert all(row["peer"] in rendered for row in rows[:8])
    assert all(row["peer"] not in rendered for row in rows[8:])
    assert "+4 additional blocker row(s) retained in Cutover Validation and NRFU" in rendered
    assert rows == before and len(rows) == 12
    scope = next(lim for lim in uip.LIMITATIONS if lim["id"] == "migration_readiness_check_scope")
    assert "eight blocker subjects" in scope["text"] and "exact omitted count" in scope["text"]
    assert "Cutover Validation/NRFU" in scope["text"]
    assert "/overview/readiness/groups" in scope["applies_to"]


def test_i12_caps_and_move_group_label_are_held_against_the_producer_source():
    for fn in (analyze.compute_migration_punchlist, analyze.compute_remediation_plan,
               analyze.compute_device_dossiers, analyze.compute_endpoint_dependencies):
        reads = [node for node in ast.walk(_function_ast(fn))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "move_group_host_index"]
        assert reads, fn.__name__
    keys = set()
    for node in ast.walk(_function_ast(analyze.compute_move_groups)):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys if isinstance(k, ast.Constant)}
    assert "switches" in keys and uip.MOVE_GROUP_LABEL in keys
    groups = analyze.compute_move_groups({"a": {}, "b": {}})
    assert [g[uip.MOVE_GROUP_LABEL] for g in groups] == ["Group 1", "Group 2"]


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
def _independent_coverage_abstention_count(snap, host):
    """Reconcile only the new device fold's count directly with original matrix row flags.

    This never calls the index, matcher, projection, or engine fold under test. Duplicate, missing,
    orphan, malformed or contradictory rows cannot supply a positive count witness.
    """
    assert isinstance(host, str)
    matrix = snap["coverage_matrix"]
    cells = matrix["by_device"][host]
    rows = matrix["rows"]
    assert isinstance(cells, dict) and cells and isinstance(rows, list)
    assert {"collection", "capture", "parse"} <= set(cells)
    assert host != coverage_matrix._FLEET
    for row in rows:
        assert isinstance(row, dict)
        for identity in ("device", "axis"):
            assert isinstance(row.get(identity), str) and row[identity].strip()
            row[identity].encode("utf-8")
    source_rows = [row for row in rows if isinstance(row, dict) and row.get("device") == host]
    assert len(source_rows) == len(cells), (host, source_rows, cells)
    flags = []
    for axis, state in cells.items():
        assert isinstance(axis, str) and axis and state in coverage_matrix.COVERAGE_STATE_ORDER
        matches = [row for row in source_rows if row.get("axis") == axis]
        assert len(matches) == 1, (host, axis, matches)
        row = matches[0]
        assert row["state"] == state
        assert row["dimension"] in coverage_matrix.COVERAGE_DIMENSIONS
        assert row["verdict_source"] in coverage_matrix.COVERAGE_VERDICT_SOURCES
        assert type(row["is_abstention"]) is bool and row["is_abstention"] == (state != "covered")
        if axis in {"collection", "capture", "parse"}:
            assert row["dimension"] == axis
        else:
            assert row["dimension"] == "architecture"
        if row["verdict_source"] == "collection_completeness":
            assert state in ({"covered", "partial", "not_collected"} if axis == "collection"
                             else {"not_collected"})
            assert row["dimension"] in {"collection", "capture", "parse"}
        else:
            source, states = {
                "capture": ("capture_integrity", {"covered", "unverified"}),
                "parse": ("parse_yield", {"covered", "unparsed"}),
                "architecture": ("architecture_coverage", {"covered"}),
            }[row["dimension"]]
            assert row["verdict_source"] == source and state in states
        flags.append(row["is_abstention"])
    count = sum(flags)
    assert count > 0, "zero abstentions cannot prove a fully covered device through silence"
    return count


@pytest.mark.parametrize("name", ("a", "bl", "mg", "real", "g_phys_bad", "g_poison_str"))
def test_i13_every_published_number_is_the_owners(name, snaps, payloads, docs):
    snap = snaps[name] if isinstance(snaps[name], dict) else {}
    inventory = payloads[name]["inventory"]
    coverage_counts = {f"/devices/rows/items/{index}/coverage/n_abstained": row["host"]
                       for index, row in enumerate(inventory["devices"]["rows"]["items"])}
    roots = [(inventory, coverage_counts), (payloads[name]["findings"], {})] + [
        (doc["device"], {"/coverage_rollup/n_abstained": doc["device"]["host"]}) for _host, doc in docs[name]]
    n = 0
    for root, folded_coverage_paths in roots:
        for where, fact in _walk_facts(root):
            value = fact.get("value")
            if fact["state"] != PUB or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            n += 1
            if where in folded_coverage_paths:
                assert fact["subject"] is None
                assert fact["basis"] == "coverage_matrix.compute_device_coverage:stored matrix rows by exact device.n_abstained"
                assert type(value) is int
                host = folded_coverage_paths[where]
                assert value == _independent_coverage_abstention_count(snap, host), (where, host, value)
                witnesses = [ref["pointer"] for ref in fact["refs"] if ref["role"] == "witness"]
                assert _ptr("coverage_matrix", "by_device", host) in witnesses
                expected_rows = [index for index, row in enumerate(snap["coverage_matrix"]["rows"])
                                 if isinstance(row, dict) and row.get("device") == host]
                assert {_ptr("coverage_matrix", "rows", index) for index in expected_rows} <= set(witnesses)
            elif fact["subject"] is not None:
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
    def readable(path):                      # the owner's own answer: a selection reads only what it can read
        return ssot.abstention_reason(snap, path) in (PUB, CBE)

    srcs = p["inventory"]["vlans"]["selection_sources"]
    for key, path in (("endpoints", "endpoint_identity"), ("gateways", "l3_forwarding"), ("stp_roots", "stp_roots")):
        assert (srcs[key]["state"] in (PUB, CBE)) is readable(path), key
    for row in p["inventory"]["vlans"]["rows"]["items"]:
        vid = row["vlan"]["value"]
        sel = row["selections"]
        assert sel["endpoints"] == ([i for i, r in enumerate(eps) if _digit(r.get("vlan")) == vid]
                                    if readable("endpoint_identity") else None)
        assert sel["gateways"] == ([i for i, r in enumerate(l3) if _digit(r.get("vlan")) == vid]
                                   if readable("l3_forwarding") else None)
        want = sorted(_ptr("stp_roots", h, k) for h in roots for k, rec in roots[h].items()
                      if stp_topology._election_priority(k) == vid
                      and not (isinstance(rec, dict) and rec.get("is_mst")))
        assert sel["stp_roots"] == (want if readable("stp_roots") else None)
    deps = snap.get("endpoint_dependencies") or {}
    shared = deps.get("shared_ip") or []
    dual = deps.get("dual_homed") or []
    vrows = snap.get("vlan_cutover") or []
    for item, raw in zip(p["inventory"]["endpoints"]["rows"]["items"], eps):
        sel = item["selections"]
        ip = raw["ip"].strip()
        assert sel["shared_ip"] == ([k for k, r in enumerate(shared) if ip and r["ip"] == ip]
                                    if readable("endpoint_dependencies.shared_ip") else None)
        assert sel["dual_homed"] == ([k for k, r in enumerate(dual) if r["mac"] == raw["mac"].lower()]
                                     if readable("endpoint_dependencies.dual_homed") else None)
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
    start = time.perf_counter()
    every = uip.project_devices(big, hosts)                  # one shared context for all 300 pages
    took = time.perf_counter() - start
    assert took <= 60.0, took
    assert [d["device"]["host"] for d in every] == hosts
    assert every[150] == uip.project_device(big, hosts[150])


# --------------------------------------------------------------------------------------------------
# I16 -- a device the collection never reached, or reached only partly, is never a clean result
# --------------------------------------------------------------------------------------------------
_SELECTIONS = ("links", "native_vlan_mismatches", "findings", "endpoints")


def test_i16_an_uncollected_device_page_claims_no_clean_absence(snaps, docs, payloads):
    """The REAL engine writes an unreached inventory host as all defaults with an empty interface parse and a
    'not collected' blind-spot row. Nothing on its page may read 'collected but empty (not a blind spot)'."""
    snap, host = snaps["real2"], GHOST["hostname"]
    i, cc = _cc_row(snap, host)
    assert cc["status"] == "not collected"                                   # the engine's own verdict
    assert snap["devices"][host]["model"] == "" and snap["interfaces"][host] == {}
    page = _doc(docs, "real2", host)["device"]
    n = 0
    for where, fact in _walk_facts(page):
        n += 1
        assert fact["state"] != CBE, (where, fact.get("reason"))
    assert n > 40
    witness = {"pointer": _ptr("collection_completeness", "devices", i), "role": "witness"}
    for block in _SELECTIONS:
        assert page[block]["state"] == NC, block
        assert witness in page[block]["refs"], block
    assert page["health"]["role"]["state"] != PUB         # 'access' is the engine's default over no interfaces
    assert page["health"]["deductions_cap"]["reached"] is None
    assert _row_for(payloads["real2"], host)["role"]["state"] != PUB


def test_i16_an_empty_interface_parse_is_no_clean_absence(snaps):
    """A device whose captures parsed to no interface (the engine writes ``{}``; the scorer bands it Insufficient
    Data) need not be listed as not collected, yet nothing derived from its interfaces reads as a clean absence,
    and its 'access' role is the engine's default, not an observation."""
    snap = copy.deepcopy(snaps["a"])
    snap["interfaces"]["access1"] = {}
    assert _cc_row(snap, "access1") == (None, None)                       # no blind-spot row names it
    page = uip.project_device(snap, "access1")["device"]
    for block in _SELECTIONS:
        fact = page[block]
        assert fact["state"] == NC and "no interface parse result" in fact["reason"], block
    assert page["links"]["items"]                                        # neighbours still name it: shown, qualified
    assert page["health"]["role"]["state"] == NC and "default" in page["health"]["role"]["reason"]
    assert page["interfaces"]["rows"]["state"] == NC
    assert _row_for({"inventory": uip.project_inventory(snap)}, "access1")["role"]["state"] == NC


def test_i16_a_partial_device_says_which_capture_its_lists_miss(snaps, docs, payloads):
    snap, (host, _cmd) = snaps["real2"], PARTIAL
    i, cc = _cc_row(snap, host)
    assert cc["status"] == "partial" and cc["missing"] == ["CDP/LLDP neighbors"]     # the real engine's record
    page = _doc(docs, "real2", host)["device"]
    missing = {"pointer": _ptr("collection_completeness", "devices", i, "missing"), "role": "witness"}
    for block in ("links", "native_vlan_mismatches", "findings"):
        fact = page[block]
        assert fact["state"] == NC and "CDP/LLDP neighbors" in fact["reason"], block
        assert missing in fact["refs"], block
    assert page["endpoints"]["state"] in (PUB, CBE)       # its interface status and switchport were collected
    hs = next(r for r in snap["health_scores"] if r["switch"] == host)
    assert hs["band"] != "Insufficient Data"              # 3 of 4 essentials: the scorer keeps the band
    row = _row_for(payloads["real2"], host)
    for fact in (page["health"]["score"], page["health"]["band"], row["health_score"], row["health_band"]):
        assert fact["state"] == PUB
        assert "health_scored_over_partial_collection" in fact["caveats"]
        assert missing in fact["refs"]
    other = next(h for h in snap["devices"] if h not in (host, GHOST["hostname"]))
    assert "health_scored_over_partial_collection" not in _row_for(payloads["real2"], other)["health_band"].get(
        "caveats", ())
    fnd = payloads["real2"]["findings"]
    blind = sorted(_ptr("collection_completeness", "devices", k) for k, _r in
                   enumerate(snap["collection_completeness"]["devices"]))
    for fact in (fnd["rows"], fnd["total"]):
        assert fact["state"] == PUB and "fleet_lists_exclude_blind_devices" in fact["caveats"]
        assert sorted(r["pointer"] for r in fact["refs"] if r["pointer"] in blind) == blind


def test_i16_device_findings_without_running_config_are_incomplete(snaps, docs):
    snap = snaps["a"]
    expected_lacking = sorted(set(snap["devices"]) - set(snap["security"]))
    assert expected_lacking                         # this fixture must exercise missing running-config
    lacking = []
    for host in sorted(snap["devices"]):
        page = _doc(docs, "a", host)["device"]
        sel = [i for i, r in enumerate(snap["punchlist"]) if host in r["devices"]]
        assert [it["index"] for it in page["findings"]["items"]] == sel
        rem = page["remediation"]["items"]
        if host in snap["security"]:
            assert page["findings"]["state"] == (PUB if sel else CBE), host
            assert rem["state"] in (PUB, CBE), host
        else:
            lacking.append(host)
            for fact in (page["findings"], rem):
                assert fact["state"] == NC and "security carries no row" in fact["reason"], host
    assert lacking == expected_lacking
    edit = copy.deepcopy(snap)
    edit["punchlist"] = [r for r in edit["punchlist"] if "podacc1" not in r["devices"]]
    fact = uip.project_device(edit, "podacc1")["device"]["findings"]
    assert fact["state"] == NC and fact["items"] == []                       # never 'no row names it'


def test_i16_fleet_lists_over_blind_devices(snaps, payloads):
    snap, p = snaps["a"], payloads["a"]
    lacking = sorted(h for h in snap["devices"] if h not in snap["security"])
    for fact in (p["findings"]["rows"], p["findings"]["total"]):
        assert "findings_without_running_config" in fact["caveats"]
        assert sorted(r["pointer"] for r in fact["refs"] if r["pointer"].startswith("/devices/")) == \
            [_ptr("devices", h) for h in lacking]
        assert "fleet_lists_exclude_blind_devices" not in fact["caveats"]           # the sample has no blind spot
    full = copy.deepcopy(snap)
    for h in lacking:
        full["security"][h] = copy.deepcopy(snap["security"]["core1"])
    assert "findings_without_running_config" not in uip.project_findings(full)["rows"].get("caveats", ())
    bl = payloads["bl"]
    witness = [{"pointer": _ptr("collection_completeness", "devices", k), "role": "witness"} for k in range(2)]
    for fact in (bl["findings"]["rows"], bl["inventory"]["vlans"]["rows"], bl["inventory"]["vlans"]["total"],
                 bl["inventory"]["endpoints"]["rows"], bl["inventory"]["endpoints"]["total"],
                 bl["inventory"]["endpoints"]["dual_homed"]):
        assert "fleet_lists_exclude_blind_devices" in fact["caveats"]
        assert all(w in fact["refs"] for w in witness)
    empty = copy.deepcopy(snaps["bl"])
    empty["punchlist"] = []
    fact = uip.project_findings(empty)["rows"]
    assert fact["state"] == NC and "collection_completeness" in fact["reason"]      # never 'nothing found'


# --------------------------------------------------------------------------------------------------
# I17 -- the one-hop gap and a band over unassessed axes are stated on the value
# --------------------------------------------------------------------------------------------------
def test_i17_one_hop_failure_caveat_reaches_the_dossier(snaps, payloads, docs):
    snap, p = snaps["fi"], payloads["fi"]
    assert "device_dossiers" not in ssot.failed_sections(snap)[0]           # the owner does not mark it
    rows = p["inventory"]["devices"]["rows"]["items"]
    assert rows
    for row in rows:
        assert row["risk_band"]["state"] == PUB
        assert "one_hop_failure_attribution" in row["risk_band"]["caveats"], row["host"]
    page = _doc(docs, "fi", "core1")["device"]["dossier"]
    assert "one_hop_failure_attribution" in page["risk_band"]["caveats"]
    for where, fact in _walk_facts({"inventory": payloads["a"]["inventory"], "findings": payloads["a"]["findings"]}):
        assert "one_hop_failure_attribution" not in fact.get("caveats", ()), where      # no failure, no caveat


def test_i17_a_band_below_severe_over_unassessed_axes_is_caveated(snaps, payloads, docs):
    snap, p = snaps["a"], payloads["a"]
    per = snap["device_dossiers"]["per_device"]
    kinds = set()
    for row in p["inventory"]["devices"]["rows"]["items"]:
        k = next(k for k, r in enumerate(per) if r["host"] == row["host"])
        want = per[k]["n_na"] > 0 and per[k]["risk_band"] in ("Elevated", "Guarded", "Low")
        for fact in (row["risk_band"], _doc(docs, "a", row["host"])["device"]["dossier"]["risk_band"]):
            assert ("dossier_band_over_unassessed_axes" in fact.get("caveats", ())) is want, row["host"]
            if want:
                assert {"pointer": _ptr("device_dossiers", "per_device", k, "n_na"), "role": "witness"} in fact["refs"]
        kinds.add((per[k]["risk_band"], want))
    assert ("Low", True) in kinds and ("Severe", False) in kinds and ("Elevated", True) in kinds


# --------------------------------------------------------------------------------------------------
# I18 -- VLAN rows: a flag or an empty list over evidence nobody read is withheld
# --------------------------------------------------------------------------------------------------
def _vlan_item(inv, vid):
    return next(it for it in inv["vlans"]["rows"]["items"] if it["vlan"]["value"] == vid)


def test_i18_default_election_over_an_unparsed_root_priority_is_withheld(snaps, payloads):
    roots = {"a": {"10": {"is_root": True, "root_address": "aaaa.0000.0001", "root_priority": 32778}}}
    snap = {"stp_roots": roots, "vlan_cutover": analyze.compute_vlan_cutover_matrix({}, roots)}
    assert _sv(_vlan_item(uip.project_inventory(snap), 10)["stp_root_default_election"]) == (PUB, True)
    roots["a"]["10"]["root_priority"] = None
    snap["vlan_cutover"] = analyze.compute_vlan_cutover_matrix({}, roots)
    projected = _vlan_item(uip.project_inventory(snap), 10)
    fact = projected["stp_root_default_election"]
    assert _sv(fact) == (NC, None) and "priority" in fact["reason"]
    assert _sv(projected["stp_root"]) == (PUB, "a")
    assert projected["stp_root_identities"]["value"][0]["root_priority"] is None
    assert fact["subject"] == "/vlan_cutover/0/stp_root_default_election"


def test_i18_empty_dependencies_need_every_gateway_config(snaps, payloads):
    for item, raw in zip(payloads["a"]["inventory"]["vlans"]["rows"]["items"], snaps["a"]["vlan_cutover"]):
        want = (PUB, raw["dependencies"]) if raw["dependencies"] else (CBE, None)      # every gateway SVI observed
        assert _sv(item["dependencies"]) == want, raw["vlan"]
    snap = copy.deepcopy(snaps["a"])
    snap["interfaces"]["core2"]["Vlan20"].pop("run_config_observed")
    row30 = next(r for r in snap["vlan_cutover"] if r["vlan"] == 30)
    row30.update(gateway_svi_hosts=[], fhrp=uip.NOT_OBSERVED_SENTINEL)              # what it writes with no gateway
    inv = uip.project_inventory(snap)
    fact = _vlan_item(inv, 20)["dependencies"]
    assert fact["state"] == NC and "DHCP relay" in fact["reason"]
    assert {"pointer": _ptr("interfaces", "core2", "Vlan20"), "role": "witness"} in fact["refs"]
    fact = _vlan_item(inv, 30)["dependencies"]
    assert fact["state"] == NC and "no gateway SVI" in fact["reason"]
    assert _vlan_item(inv, 40)["dependencies"]["state"] == CBE


def test_i18_scenario_reason_names_the_right_gap(snaps):
    snap = copy.deepcopy(snaps["a"])
    snap["vlan_cutover"][0]["scenario"] = ""
    snap["vlan_cutover"][1].update(wave="", scenario="")
    items = uip.project_inventory(snap)["vlans"]["rows"]["items"]
    with_wave, no_wave = items[0]["scenario"], items[1]["scenario"]
    assert with_wave["state"] == no_wave["state"] == NC
    assert "sequenced move group" not in with_wave["reason"] and "wave sequencing" in with_wave["reason"]
    assert "sequenced move group" in no_wave["reason"]


def test_i18_fhrp_blank_fields_are_null(snaps, payloads):
    blanks = 0
    for item, raw in zip(payloads["a"]["inventory"]["vlans"]["rows"]["items"], snaps["a"]["vlan_cutover"]):
        if not isinstance(raw["fhrp"], dict):
            continue
        val = item["fhrp"]["value"]
        for k in ("proto", "group", "vip"):
            assert val[k] == (raw["fhrp"][k] or None), k
        for got, rm in zip(val["members"], raw["fhrp"]["members"]):
            for k in ("host", "proto", "group", "vip", "role", "vmac"):
                assert got[k] == (rm[k] or None), k
                blanks += rm[k] == ""
    assert blanks


def test_i18_text_caps_say_so(snaps):
    snap = copy.deepcopy(snaps["a"])
    snap["vlan_cutover"][0]["app_domain"] = "A + B + C"
    snap["vlan_cutover"][1]["app_domain"] = "A + B"
    snap["punchlist"][0]["detail"] = ("word " * 90).strip() + uip.PUNCH_DETAIL_CLIP_MARKER
    vl = uip.project_inventory(snap)["vlans"]["rows"]["items"]
    assert "engine_list_capped" in vl[0]["app_domain"]["caveats"]
    assert "engine_list_capped" not in vl[1]["app_domain"].get("caveats", ())
    rows = uip.project_findings(snap)["rows"]["items"]
    assert "engine_list_capped" in rows[0]["detail"]["caveats"]
    assert all("engine_list_capped" not in r["detail"].get("caveats", ())
               for r, raw in zip(rows[1:], snap["punchlist"][1:]) if uip.PUNCH_DETAIL_CLIP_MARKER not in raw["detail"])


def test_i18_dual_homed_ports_cap_caveat_is_exact(snaps):
    snap = copy.deepcopy(snaps["a"])
    rows = snap["endpoint_dependencies"]["dual_homed"]
    assert all(len(r["ports"]) == 8 for r in rows)
    rows[1]["ports"] = rows[1]["ports"][:7]
    dual = uip.project_inventory(snap)["endpoints"]["dual_homed"]["items"]
    for item, raw in zip(dual, rows):
        at_cap = len(raw["ports"]) >= 8
        assert ("engine_list_capped" in item["ports"].get("caveats", ())) is at_cap
        assert item["ports_cap"]["reached"] is at_cap


def test_i18_severity_basis_marker_from_the_real_producer(snaps):
    """The punch-list producer's own fold of two media risks: one publishing its basis, one falling back to the
    engine's not-published marker."""
    rows = analyze.compute_migration_punchlist(
        cross_layer=[], security={}, config_hygiene={}, physical_health=[], l3_forwarding=[], protocol_health=[],
        stp_findings={}, health_scores=[], move_groups=[],
        media_risks=[{"severity": "High", "devices": ["access1"], "title": "MAC alias", "detail": "d1",
                      "remediation": "r1", "severity_basis": "curated on-air classification",
                      "evidence_confidence": "registry hint"},
                     {"severity": "Medium", "devices": ["access2"], "title": "IGMP querier gap", "detail": "d2"}])
    snap = copy.deepcopy(snaps["a"])
    snap["punchlist"] = rows
    items = uip.project_findings(snap)["rows"]["items"]
    by_title = {it["title"]["value"]: it for it in items}
    alias, gap = by_title["MAC alias"], by_title["IGMP querier gap"]
    assert _sv(alias["severity_basis"]) == (PUB, "curated on-air classification")
    assert _sv(alias["evidence_confidence"]) == (PUB, "registry hint")
    for f in ("severity_basis", "evidence_confidence"):
        assert gap[f]["state"] == NC and "marker" in gap[f]["reason"], f
    assert rows[[r["title"] for r in rows].index("IGMP querier gap")]["severity_basis"] == uip.PUNCH_BASIS_UNPUBLISHED


# --------------------------------------------------------------------------------------------------
# I19 -- joins follow the owner's key rule; two rows are never picked between
# --------------------------------------------------------------------------------------------------
_ALL_ESSENTIAL = ["interface status", "switchport", "version/inventory", "CDP/LLDP neighbors"]


@pytest.mark.parametrize("variant", ("CORE1", " core1 ", "Core1"))
def test_i19_blind_spot_join_follows_the_owners_key_rule(snaps, variant):
    snap = copy.deepcopy(snaps["a"])
    snap["collection_completeness"]["devices"] = [
        {"host": variant, "status": "not collected", "data_quality": 0, "missing": list(_ALL_ESSENTIAL)}]
    assert ssot.abstention_reason(snap, "devices", device="core1") == NC          # the owner matches it
    inv = uip.project_inventory(snap)["devices"]
    rows = [r for r in inv["rows"]["items"] if r["host"].strip().lower() == "core1"]
    assert [r["host"] for r in rows] == ["core1"]                                  # no phantom row
    row = rows[0]
    assert row["rosters"] == {"devices": True, "collection_completeness": True}
    assert _sv(row["collection_status"]) == (PUB, "not collected")
    assert row["rows"]["collection"] == "/collection_completeness/devices/0"
    assert row["model"]["state"] == NC
    assert _sv(inv["total"]) == (PUB, 23)
    page = uip.project_device(snap, "core1")["device"]
    assert page["rosters"]["collection_completeness"] is True
    assert _sv(page["collection"]["status"]) == (PUB, "not collected")


def test_i19_two_blind_spot_rows_for_one_device_are_unverified(snaps):
    snap = copy.deepcopy(snaps["a"])
    snap["collection_completeness"]["devices"] = [
        {"host": "CORE1", "status": "partial", "data_quality": 75, "missing": ["CDP/LLDP neighbors"]},
        {"host": "core1", "status": "partial", "data_quality": 50, "missing": ["switchport", "CDP/LLDP neighbors"]},
        {"host": "GHOST9", "status": "not collected", "data_quality": 0, "missing": list(_ALL_ESSENTIAL)},
        {"host": "ghost9", "status": "not collected", "data_quality": 0, "missing": list(_ALL_ESSENTIAL)}]
    snap["collection_completeness"]["summary"]["inventory"] = 24
    inv = uip.project_inventory(snap)["devices"]
    core = _row_for({"inventory": {"devices": inv}}, "core1")
    assert core["collection_status"]["state"] == UV and core["rows"]["collection"] is None
    ghosts = [r for r in inv["rows"]["items"] if r["host"].lower() == "ghost9"]
    assert len(ghosts) == 1 and ghosts[0]["pointer"] is None                      # never picked between
    assert ghosts[0]["collection_status"]["state"] == UV
    assert _sv(inv["total"]) == (PUB, 24)


def test_i19_ambiguous_headline_and_unreadable_peer_flags(snaps, payloads):
    snap = copy.deepcopy(snaps["a"])
    axes = snap["executive_brief"]["axes"]
    axes.append(copy.deepcopy(axes[payloads["a"]["findings"]["headline_axis_index"]]))
    assert uip.project_findings(snap)["headline_axis_index"] is None
    snap = copy.deepcopy(snaps["a"])
    snap["cable_map"]["nodes"][1]["collected"] = None
    peers = uip.project_inventory(snap)["uncollected_peers"]
    assert peers["state"] == UV and NOT_A_BLIND_SPOT not in peers["reason"]


# --------------------------------------------------------------------------------------------------
# I20 -- a selection says whether its source could be read
# --------------------------------------------------------------------------------------------------
def test_i20_selections_carry_their_source_state(snaps, payloads):
    p = payloads["a"]["inventory"]
    assert {k: v["state"] for k, v in p["vlans"]["selection_sources"].items()} == \
        {"stp_roots": PUB, "gateways": PUB, "endpoints": PUB}
    assert {k: v["state"] for k, v in p["endpoints"]["selection_sources"].items()} == \
        {"interfaces": PUB, "vlan_rows": PUB, "shared_ip": PUB, "dual_homed": PUB}
    snap = copy.deepcopy(snaps["a"])
    del snap["stp_roots"], snap["l3_forwarding"]
    vl = uip.project_inventory(snap)["vlans"]
    assert vl["selection_sources"]["stp_roots"]["state"] == NC
    assert vl["selection_sources"]["gateways"]["state"] == NC
    assert vl["rows"]["items"]
    for row in vl["rows"]["items"]:
        assert row["selections"]["stp_roots"] is None and row["selections"]["gateways"] is None
        assert isinstance(row["selections"]["endpoints"], list)
    failed = copy.deepcopy(snaps["a"])
    failed["endpoint_dependencies"] = {}
    failed["assessment_integrity"] = {"failed_phases": ["Endpoint dependencies"]}
    ep = uip.project_inventory(failed)["endpoints"]
    assert ep["selection_sources"]["shared_ip"]["state"] == AU
    assert ep["rows"]["items"]
    for row in ep["rows"]["items"]:
        assert row["selections"]["shared_ip"] is None and row["selections"]["dual_homed"] is None


# --------------------------------------------------------------------------------------------------
# I21 -- a lone surrogate never reaches the output (a UTF-8 encoder would raise on it)
# --------------------------------------------------------------------------------------------------
_SUR = "\udc80"


def _poison_text(obj):
    if isinstance(obj, str):
        return obj + _SUR
    if isinstance(obj, dict):
        return {k: _poison_text(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_poison_text(v) for v in obj]
    return obj


def _rename_host(obj, old, new):
    if isinstance(obj, str):
        return new if obj == old else obj
    if isinstance(obj, dict):
        return {(new if k == old else k): _rename_host(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename_host(v, old, new) for v in obj]
    return obj


def test_i21_lone_surrogates_are_withheld(snaps, validator, doc_validator):
    values = _poison_text(copy.deepcopy(snaps["a"]))
    keys = _rename_host(copy.deepcopy(snaps["a"]), "access1", "access1" + _SUR)
    keys["executive_brief"]["axes"][0]["axis"] += _SUR
    keys["assessment_integrity"] = {"failed_phases": ["Health Scores" + _SUR]}
    for snap in (values, keys):
        payload = uip.project(snap)
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        assert validator.is_valid(payload)
        for host in _roster_hosts(snap)[:4] + ["access1" + _SUR]:
            doc = uip.project_device(snap, host)
            json.dumps(doc, ensure_ascii=False, allow_nan=False).encode("utf-8")
            assert doc_validator.is_valid(doc)
    model = uip.project_device(values, "core1")["device"]["identity"]["model"]
    assert model["state"] == UV
    page = uip.project_device(keys, "access1" + _SUR)["device"]
    assert page["host"] is None and page["identity"]["model"]["state"] == UV


# --------------------------------------------------------------------------------------------------
# I22 -- device pages share one context; owners a page does not read are never called
# --------------------------------------------------------------------------------------------------
def test_i22_project_devices_equals_one_page_at_a_time(snaps, monkeypatch):
    snap = snaps["a"]
    hosts = _roster_hosts(snap) + ["no-such", 7]
    want = [uip.project_device(snap, h) for h in hosts]
    assert uip.project_devices(snap, hosts) == want
    assert uip.project_devices(snap, tuple(hosts[:2])) == want[:2]
    assert uip.project_devices(snap, None) == [] and uip.project_devices(snap, 5) == []

    def _boom(*_a, **_kw):
        raise AssertionError("a device page does not read this owner")

    monkeypatch.setattr(ssot, "summary", _boom)
    monkeypatch.setattr(ssot, "canonical_facts", _boom)
    assert uip.project_device(snap, "core1") == want[hosts.index("core1")]
    assert uip.project_inventory(snap) == uip.project_inventory(copy.deepcopy(snap))


# --------------------------------------------------------------------------------------------------
# I23 -- every engine-published evidence field survives the typed projection
# --------------------------------------------------------------------------------------------------
_EVIDENCE_KEYS = ("evidence_refs", "evidence_refs_total", "evidence_basis", "deduction_refs")


def test_i23_engine_row_evidence_is_projected_without_loss():
    """The former deliberate-absence tripwire now requires parity for every source-owned evidence field.
    Adversarial, capped, legacy and real-producer subsequence cases live in test_ui_projection_evidence.py.
    """
    consts = _str_constants(ast.parse(inspect.getsource(analyze)))
    assert set(_EVIDENCE_KEYS) <= consts
    sample = _sample()
    findings = uip.project_findings(sample)
    assert "punch_rows_carry_no_evidence_pointers" not in findings["rows"].get("caveats", ())
    assert sample["punchlist"] and sample["health_scores"]
    for raw, row in zip(sample["punchlist"], findings["rows"]["items"]):
        assert _sv(row["evidence_basis"]) == (PUB, raw["evidence_basis"])
        refs = [item["fact"]["value"] for item in row["evidence_refs"]["items"]]
        assert refs == raw["evidence_refs"]
        assert all(_resolve(sample, ref["ref"]) is not _MISSING for ref in refs)
        assert _sv(row["evidence_refs_total"]) == (
            (PUB, raw["evidence_refs_total"]) if "evidence_refs_total" in raw else (NC, None))
    for raw in sample["health_scores"]:
        health = uip.project_device(sample, raw["switch"])["device"]["health"]
        assert [item["fact"]["value"] for item in health["deduction_refs"]["items"]] == raw["deduction_refs"]
