"""ui_projection/1 -- slice 1 (Overview + Trust) of the one typed engine->UI projection (D9).

"Facts in Python, geometry in the browser": every verdict, count, rollup, denominator, severity band
and evidence state a screen shows comes from an engine owner through ONE schema-tagged payload. These
tests hold the projection to that contract:

* the populated fixtures come from the engine's own code: the shipped sample fleet, the brief
  recomputed by ``analyze.compute_executive_brief`` for the unscored / failed-phase / not-collected
  variants, and one real ``COLLECT_PARSE_V3_23_0.main()`` run with four phases forced to fail. The
  minimal snapshot, the GARBAGE cases and a few single-field edits of the sample are hand-shaped on
  purpose: they probe one rule each, and every expectation on them is still read from an owner;
* expectations are read from the owners (``ssot.canonical_facts`` / ``abstention_reason`` /
  ``fleet_avg_health`` / ``failed_sections`` / ``compute_schema_census`` / ``summary`` / ``reconcile``),
  never from cached sample-fleet literals, so a regenerated sample cannot silently break them;
* the vocabularies the projection copies are held equal to their owners by source/AST checks, so a
  producer change fails here instead of drifting silently.

Coverage honesty is the point: absence never renders as 0 / healthy, a MEASURED zero is published as 0
only when nothing says its input was incomplete, a failed phase's fallback is ``analysis_unavailable``,
a value the engine's own reconcile rejects is ``unverified``, and malformed values are ``unverified``
rather than coerced.
"""
from __future__ import annotations

import ast
import builtins
import copy
import inspect
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import textwrap
import types

import pytest
from jsonschema import Draft202012Validator

import cisco_toolkit
from cisco_toolkit import analyze, ssot, unknown_evidence
from cisco_toolkit import ui_projection as uip
from cisco_toolkit.html import snapshot_state

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
MODULE_SRC = ROOT / "cisco_toolkit" / "ui_projection.py"
AU = "analysis_unavailable"
NC = "not_collected"
CBE = "collected_but_empty"
PUB = "published"
NA = "not_assessed"
UV = "unverified"
POSTURE_NAMES = ("avg_health", "n_critical", "n_poor", "worst_band")
NOT_A_BLIND_SPOT = "not a blind spot"
HUGE = "1" + "0" * 400

_MISSING = object()


# --------------------------------------------------------------------------------------------------
# independent helpers (deliberately NOT the module's own)
# --------------------------------------------------------------------------------------------------
def _resolve(doc, pointer):
    """An independent RFC 6901 resolver: ``_MISSING`` when the pointer does not resolve."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
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


def _is_fact(obj):
    return isinstance(obj, dict) and {"state", "subject", "refs", "basis"} <= set(obj)


def _walk_facts(obj, where=""):
    """Yield ``(payload pointer, fact-or-factlist)`` for every Fact / FactList in a payload."""
    if isinstance(obj, dict):
        if _is_fact(obj):
            yield where, obj
        for key, val in obj.items():
            yield from _walk_facts(val, f"{where}/{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _walk_facts(val, f"{where}/{i}")


def _as_dict(snap):
    return snap if isinstance(snap, dict) else {}


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


def _axis_item(payload, label):
    hits = [it for it in payload["overview"]["axes"]["items"] if it["axis"] == label]
    assert len(hits) == 1, (label, [it["axis"] for it in payload["overview"]["axes"]["items"]])
    return hits[0]


def _limitation_ids(payload):
    return {lim["id"] for lim in payload["trust"]["limitations"]}


def _fact(payload, name):
    return payload["overview"]["facts"][name]["fact"]


def _sv(fact):
    return fact["state"], fact.get("value")


def _deep(n, open_="[", close="]"):
    return open_ * n + close * n


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


def _legacy(all_insufficient):
    snap = copy.deepcopy(all_insufficient)
    snap["executive_brief"]["posture"] = {"avg_health": 0, "n_critical": 0, "n_poor": 0, "worst_band": ""}
    return snap


def _no_avg_key(all_insufficient):
    """All rows unscored and a posture that publishes zero band counts but no avg_health key at all:
    ``ssot.fleet_avg_health`` says ``unpublished`` while its ``n_scored`` is 0."""
    snap = copy.deepcopy(all_insufficient)
    snap["executive_brief"]["posture"] = {"n_critical": 0, "n_poor": 0, "worst_band": ""}
    return snap


def _failed_phases(sample):
    snap = copy.deepcopy(sample)
    snap["failure_impact"] = []          # the _run_phase fallbacks (main(): failure_impact / punchlist)
    snap["punchlist"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Failure Impact", "Migration Punch-List"]}
    return _rebrief(snap, sample)


def _failure_record_only(sample):
    """A failure record for two phases while their sections still hold content: the projection must
    follow the RECORD (propagation rules), whatever the section holds."""
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores", "Segmentation audit"]}
    return snap


def _failed_health_and_segmentation(sample):
    snap = copy.deepcopy(sample)
    snap["health_scores"] = []           # _run_phase fallbacks of 'Health Scores' / 'Segmentation audit'
    snap["segmentation"] = {}
    snap["assessment_integrity"] = {"failed_phases": ["Health Scores", "Segmentation audit"]}
    return _rebrief(snap, sample)


def _inputs_not_collected(sample):
    """The brief recomputed with 11 of its 13 inputs absent (a snapshot predating those sections)."""
    snap = copy.deepcopy(sample)
    for key in uip.BRIEF_INPUTS:
        if key not in ("health_scores", "punchlist"):
            snap.pop(key, None)
    return _rebrief(snap, sample)


GARBAGE = {
    "g_none": lambda s: None,
    "g_list": lambda s: [],
    "g_str": lambda s: "",
    "g_zero": lambda s: 0,
    "g_empty": lambda s: {},
    "g_eb_int": lambda s: {"executive_brief": 5},
    "g_nan_posture": lambda s: {"executive_brief": {"posture": {"avg_health": float("nan")}},
                                "health_scores": [{"band": "Good", "score": float("inf")}]},
    "g_lc_inf": lambda s: {"lifecycle_risk": {"summary": {"n_near": float("inf"), "n_unknown": "abc"}}},
    "g_huge": lambda s: json.loads('{"lifecycle_risk":{"summary":{"n_near":' + HUGE
                                   + ',"n_unknown":9007199254740993,"n_devices":2.5}},'
                                   + '"coverage_matrix":{"summary":{"n_rows":' + HUGE + '}}}'),
    "g_eb_badtypes": lambda s: {"executive_brief": {"scale": {"n_devices": -5}, "axes": "x",
                                                    "top_gating": [1, None], "posture_statement": 7}},
    "g_eb_unavailable": lambda s: {"executive_brief": {"_unavailable": True}},
    "g_fp_str": lambda s: {"assessment_integrity": {"failed_phases": "boom"}},
    "g_fp_mixed": lambda s: {"assessment_integrity": {"failed_phases": [None, {"a": 1}, "Totally new phase"]}},
    "g_cm_nan": lambda s: {"coverage_matrix": {"summary": {"n_rows": float("nan"), "by_state": {"weird": 1}}}},
    "g_ue_bad": lambda s: {"unknown_evidence": {"summary": {"state": "made_up"}, "sources": [5]}},
    "g_band_unhashable": lambda s: _set_band(s, []),
    "g_deep_axes": lambda s: json.loads('{"executive_brief":{"axes":' + _deep(600) + '}}'),
    "g_deep_section": lambda s: json.loads('{"schema":"collect_parse_snapshot/1","punchlist":' + _deep(900) + '}'),
    "g_deep_label": lambda s: json.loads('{"assessment_integrity":{"failed_phases":[' + _deep(900) + ']}}'),
    "g_poison_nan": lambda s: _poison_with(float("nan"))(s),
    "g_poison_inf": lambda s: _poison_with(float("inf"))(s),
    "g_poison_huge": lambda s: _poison_with(10 ** 400)(s),
    "g_poison_str": lambda s: _poison_with("12")(s),
    "g_poison_dict": lambda s: _poison_with({"n": 1})(s),
}


def _set_band(sample, band):
    snap = copy.deepcopy(sample)
    snap["health_scores"][0]["band"] = band
    return snap


CORE = ("a", "b", "c", "c_legacy", "c_noavg", "d", "d_real", "e", "e_fallback", "f_nc")
ALL_CASES = CORE + tuple(GARBAGE)
REAL_FAILED = ("Failure Impact", "Migration Punch-List", "Health Scores", "Segmentation audit")


def _run_real_engine(tmp_path, mp):
    """The real pipeline with four phases forced to fail (pattern of
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

    mp.setattr(analyze, "compute_failure_impact", _boom)   # main() imports it at call time
    mp.setattr(cp, "_punchlist", _boom)
    mp.setattr(cp, "compute_health_scores", _boom)          # module-level imports of COLLECT_PARSE_V3_23_0
    mp.setattr(cp, "compute_segmentation", _boom)
    cp.main()
    return json.loads(pathlib.Path(str(out)[:-len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snaps(tmp_path_factory):
    sample = _sample()
    c = _all_insufficient(sample)
    out = {"a": sample, "b": _minimal(), "c": c, "c_legacy": _legacy(c), "c_noavg": _no_avg_key(c),
           "d": _failed_phases(sample), "e": _failure_record_only(sample),
           "e_fallback": _failed_health_and_segmentation(sample), "f_nc": _inputs_not_collected(sample)}
    with pytest.MonkeyPatch.context() as mp:
        out["d_real"] = _run_real_engine(tmp_path_factory.mktemp("uip_real_engine"), mp)
    for name, build in GARBAGE.items():
        out[name] = build(sample)
    return out


@pytest.fixture(scope="module")
def payloads(snaps):
    return {name: uip.project(snap) for name, snap in snaps.items()}


@pytest.fixture(scope="module")
def validator():
    return Draft202012Validator(uip.ui_projection_schema())


# --------------------------------------------------------------------------------------------------
# T0 -- the schema is sound, codegen/Ajv-strict friendly, and its enums ARE the module's vocabularies
# --------------------------------------------------------------------------------------------------
def _branches(defn):
    assert set(defn) == {"title", "oneOf"}, sorted(defn)
    pub, wh = defn["oneOf"]
    assert pub["properties"]["state"] == {"const": PUB}
    assert wh["properties"]["state"] == {"$ref": "#/$defs/WithheldState"}
    assert "reason" not in pub["properties"] and "reason" in wh["required"]
    return pub, wh


def test_t0_schema_is_sound_and_enums_are_the_module_vocabularies():
    schema = uip.ui_projection_schema()
    Draft202012Validator.check_schema(schema)
    d = schema["$defs"]
    assert schema["properties"]["schema"]["const"] == uip.SCHEMA == "ui_projection/1"
    assert schema["title"] == uip.SCHEMA
    assert schema["$id"] == "urn:atlas:schema:ui-projection:1"
    assert d["State"]["enum"] == list(uip.STATES)
    assert uip.STATES[:4] == ssot.ABSTENTION_STATES
    assert set(uip.STATES[4:]) == set(uip.DOMAIN_STATE_OWNERS)
    assert d["WithheldState"]["enum"] == list(uip.WITHHELD_STATES) == [s for s in uip.STATES if s != PUB]
    assert d["EngineState"]["enum"] == list(uip.ENGINE_STATES)
    assert set(uip.ENGINE_STATES) == set(uip.STATES) | set(uip.FLEET_HEALTH_STATES)
    assert d["EngineStateOwner"]["enum"] == list(uip.ENGINE_STATE_OWNERS)
    assert d["Ref"]["properties"]["role"]["enum"] == list(uip.REF_ROLES)
    assert d["LimitationId"]["enum"] == [lim["id"] for lim in uip.LIMITATIONS + uip.DEVICE_LIMITATIONS]
    typed = {"CountFact": {"type": "integer", "minimum": 0, "maximum": uip.JS_MAX_SAFE_INT},
             "ScoreFact": {"type": "number", "minimum": 0, "maximum": 100},
             "TextFact": {"type": "string"}, "FlagFact": {"type": "boolean"},
             "BandFact": {"type": "string", "enum": list(uip.HEALTH_BANDS)},
             "UnknownEvidenceStateFact": {"type": "string", "enum": list(uip.UNKNOWN_EVIDENCE_STATES)}}
    for name, value in typed.items():
        pub, wh = _branches(d[name])
        assert pub["properties"]["value"] == value, name
        assert wh["properties"]["value"] == {"type": "null"}, name
    for name, value_def in (("AxisFact", "AxisValue"), ("ByStateFact", "ByStateValue"),
                            ("StampFact", "StampValue"), ("SourceFact", "SourceValue")):
        pub, _wh = _branches(d[name])
        assert pub["properties"]["value"] == {"$ref": f"#/$defs/{value_def}"}, name
    assert d["AxisValue"]["properties"]["severity"]["enum"] == list(uip.SEVERITIES)
    assert list(d["ByStateValue"]["properties"]) == list(uip.COVERAGE_STATES)
    assert d["SourceValue"]["properties"]["state"]["enum"] == list(uip.UE_SOURCE_STATES)
    ov = d["Overview"]["properties"]
    assert d["OverviewFacts"]["required"] == list(ssot.CANONICAL_FACTS)
    assert set(d["OverviewFacts"]["properties"]) == set(ssot.CANONICAL_FACTS)
    assert ov["facts"] == {"$ref": "#/$defs/OverviewFacts"}
    fh_pub, fh_wh = _branches(d["FleetHealth"])
    assert fh_pub["properties"]["engine_state"]["enum"] == list(uip.FLEET_HEALTH_STATES)
    assert fh_pub["properties"]["not_assessed_reason"] == {"type": "null"}
    assert fh_wh["properties"]["not_assessed_reason"]["anyOf"][0]["enum"] == list(uip.NOT_ASSESSED_REASONS)
    bands = d["Lifecycle"]["properties"]["bands"]
    assert bands["minItems"] == bands["maxItems"] == len(uip.LIFECYCLE_BAND_ORDER) == 5
    band_row = d["LifecycleBand"]["properties"]
    assert band_row["band"]["enum"] == list(uip.LIFECYCLE_BAND_ORDER)
    assert band_row["fact_name"]["enum"] == [uip.LIFECYCLE_BAND_FACTS_BY_BAND[b] for b in uip.LIFECYCLE_BAND_ORDER]
    assert d["FailureRecordItem"]["properties"]["classification"]["enum"] == list(uip.PHASE_CLASSIFICATIONS)
    assert d["CensusRow"]["properties"]["kind"]["enum"] == list(uip.CENSUS_KINDS)
    lims = d["Trust"]["properties"]["limitations"]
    assert lims["minItems"] == lims["maxItems"] == len(uip.LIMITATIONS)
    ids = [lim["id"] for lim in uip.LIMITATIONS]
    assert len(set(ids)) == len(ids)


_OBJECT_KWS = {"properties", "required", "additionalProperties", "minProperties", "maxProperties",
               "dependentRequired", "propertyNames"}
_ARRAY_KWS = {"items", "prefixItems", "minItems", "maxItems", "uniqueItems", "contains"}
_STRING_KWS = {"minLength", "maxLength", "pattern", "format"}
_NUMBER_KWS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}


def _subschemas(node):
    for key in ("properties", "$defs"):
        for sub in (node.get(key) or {}).values():
            yield sub
    for key in ("items", "additionalProperties", "propertyNames", "contains"):
        if isinstance(node.get(key), dict):
            yield node[key]
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        yield from node.get(key) or ()


def _strict_lint(node, where, problems):
    """Ajv ``strict`` / ``strictTypes`` / ``strictRequired`` plus what TS code generators need."""
    if not isinstance(node, dict):
        return
    kws = set(node)
    typ = node.get("type")
    if isinstance(typ, list):
        problems.append((where, "union type list (use anyOf with a null branch)"))
    for group, want in ((_OBJECT_KWS, {"object"}), (_ARRAY_KWS, {"array"}), (_STRING_KWS, {"string"}),
                        (_NUMBER_KWS, {"integer", "number"})):
        if kws & group and typ not in want:
            problems.append((where, f"{sorted(kws & group)} without type {sorted(want)}"))
    for bad in ("if", "then", "else", "not"):
        if bad in kws:
            problems.append((where, f"'{bad}' is invisible to TS generators"))
    for name in node.get("required") or ():
        if name not in (node.get("properties") or {}):
            problems.append((where, f"required '{name}' is not a declared property"))
    if typ == "object" and node.get("additionalProperties") is not False and "properties" in node:
        problems.append((where, "open object with declared properties"))
    for i, sub in enumerate(_subschemas(node)):
        _strict_lint(sub, f"{where}/{i}", problems)


def test_t0_schema_is_strict_and_codegen_friendly():
    schema = uip.ui_projection_schema()
    problems = []
    _strict_lint(schema, "#", problems)
    assert not problems, problems[:10]
    for name, defn in schema["$defs"].items():
        assert defn.get("title"), name
        for i, branch in enumerate(defn.get("oneOf") or ()):
            if "$ref" not in branch:
                assert branch.get("title"), (name, i)
    for name in ("AxisItem", "AbsentAxis", "TopGatingItem", "CensusRow", "FailureRecordItem", "DirectSection",
                 "Limitation", "LifecycleBand", "SourceItem"):
        assert schema["$defs"][name]["type"] == "object", name


def test_t0_schema_rejects_envelope_violations(payloads, validator):
    """The closed published/withheld branches enforce the envelope invariant, not just describe it."""
    forgeries = {
        "published_without_value": lambda f: f.update(value=None),
        "published_with_reason": lambda f: f.update(reason="x"),
        "withheld_with_value": lambda f: f.update(state=NC, reason="x"),
        "withheld_without_reason": lambda f: f.update(state=NC, value=None),
        "unknown_key": lambda f: f.update(valeu=1),
        "unsafe_integer": lambda f: f.update(value=2 ** 53),
        "unknown_caveat": lambda f: f.update(caveats=["made-up"]),
        "engine_state_without_owner": lambda f: f.update(engine_state=CBE),
    }
    for name, forge in forgeries.items():
        payload = copy.deepcopy(payloads["a"])
        forge(payload["overview"]["facts"]["n_devices"]["fact"])
        assert not validator.is_valid(payload), name
    payload = copy.deepcopy(payloads["a"])
    payload["overview"]["axes"]["items"] = []                       # a published list is never empty
    assert not validator.is_valid(payload)


def test_t0_schema_accessor_returns_a_fresh_unaliased_copy():
    first = uip.ui_projection_schema()
    seen = {}

    def walk(node, where):
        if isinstance(node, (dict, list)):
            assert id(node) not in seen, (where, seen.get(id(node)))
            seen[id(node)] = where
            for key, val in (node.items() if isinstance(node, dict) else enumerate(node)):
                walk(val, f"{where}/{key}")

    walk(first, "#")
    _mutate_everything(first)
    again = uip.ui_projection_schema()
    Draft202012Validator.check_schema(again)
    assert again["$defs"]["State"]["enum"] == list(uip.STATES)


def test_t0_exported_tables_are_read_only():
    for table in (uip.AXIS_BASIS, uip.LIFECYCLE_BAND_FACTS, uip.LIFECYCLE_BAND_FACTS_BY_BAND,
                  uip.DOMAIN_STATE_OWNERS):
        assert isinstance(table, types.MappingProxyType)
        with pytest.raises(TypeError):
            table["x"] = "y"
    assert isinstance(uip.LIMITATIONS, tuple)
    for lim in uip.LIMITATIONS:
        assert isinstance(lim, types.MappingProxyType) and isinstance(lim["applies_to"], tuple)


def test_json_pointer_is_rfc6901():
    assert uip.json_pointer() == ""
    assert uip.json_pointer("a/b", "c~d", 0, "~/") == "/a~1b/c~0d/0/~0~1"
    doc = {"a/b": {"c~d": [{"~/": 7}]}}
    assert _resolve(doc, uip.json_pointer("a/b", "c~d", 0, "~/")) == 7


# --------------------------------------------------------------------------------------------------
# T1 / T2 -- schema-valid everywhere; the envelope invariants hold; every ref / pointer resolves
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALL_CASES)
def test_t1_projection_is_schema_valid_and_sections_compose(name, snaps, payloads, validator):
    snap, payload = snaps[name], payloads[name]
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:10]]
    assert payload["schema"] == uip.SCHEMA
    assert payload["engine"] == uip.project_engine(snap)
    assert payload["overview"] == uip.project_overview(snap)
    assert payload["trust"] == uip.project_trust(snap)
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("name", ALL_CASES)
def test_t1_envelope_invariants(name, payloads):
    payload = payloads[name]
    lim_ids = _limitation_ids(payload)
    n = 0
    for where, fact in _walk_facts(payload):
        n += 1
        state = fact["state"]
        assert state in uip.STATES, where
        assert ("reason" in fact) is (state != PUB), (where, fact)
        if "value" in fact:
            assert (fact["value"] is None) is (state != PUB), (where, fact)
        if "items" in fact and state == PUB:
            assert fact["items"], where
        if "engine_state" in fact:
            assert fact["engine_state"] != state, where
            assert fact["engine_state_owner"] in uip.ENGINE_STATE_OWNERS, where
        else:
            assert "engine_state_owner" not in fact, where
        assert set(fact.get("caveats", ())) <= lim_ids, where
        if state != PUB:
            assert NOT_A_BLIND_SPOT not in fact["reason"] or state == CBE, (where, fact["reason"])
    assert n > 30
    fh = payload["overview"]["fleet_health"]
    avg = _fact(payload, "avg_health")
    assert fh["state"] == avg["state"]
    assert (fh["not_assessed_reason"] is not None) <= (fh["state"] == NA)
    axes = payload["overview"]["axes"]["items"]
    for item in payload["overview"]["top_gating"]["items"]:
        if item["fact"]["state"] == PUB:
            target = axes[item["axis_index"]]["fact"]
            assert target["state"] == PUB and target["value"]["headline"] == item["fact"]["value"]
            assert target["value"]["severity"] in ("Critical", "High")
    for row in payload["trust"]["census"]["rows"]["items"]:
        assert row["pointer"] == uip.json_pointer(row["key"])


@pytest.mark.parametrize("name", ALL_CASES)
def test_t2_every_ref_and_pointer_resolves(name, snaps, payloads):
    snap, payload = snaps[name], payloads[name]
    n_refs = 0
    for where, fact in _walk_facts(payload):
        for ref in fact["refs"]:
            n_refs += 1
            assert ref["role"] in uip.REF_ROLES
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (where, ref)
        if fact["state"] == PUB and fact["subject"] is not None:
            assert _resolve(snap, fact["subject"]) is not _MISSING, (where, fact["subject"])
        for item in fact.get("items", ()):
            if isinstance(item, dict) and "pointer" in item:
                assert _resolve(snap, item["pointer"]) is not _MISSING, (where, item)
    for row in payload["trust"]["failures"]["direct_sections"]:
        for ref in row["refs"]:
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (row, ref)
    for lim in payload["trust"]["limitations"]:
        assert lim["applies_to"], lim["id"]
        for pointer in lim["applies_to"]:
            assert _resolve(payload, pointer) is not _MISSING, (lim["id"], pointer)
    if name == "a":
        assert n_refs > 50           # non-vacuous on the populated fixture
        roles = {r["role"] for _w, f in _walk_facts(payload) for r in f["refs"]}
        assert {"subject", "basis", "witness", "denominator"} <= roles


# --------------------------------------------------------------------------------------------------
# T3 / T4 -- values come from the owner; the owner's abstention and reconcile verdict always win
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "b", "c", "d", "e"))
def test_t3_canonical_values_come_from_the_owner(name, snaps, payloads):
    snap, facts = snaps[name], payloads[name]["overview"]["facts"]
    canon = ssot.canonical_facts(snap)
    fh = ssot.fleet_avg_health(snap)
    assert list(facts) == list(ssot.CANONICAL_FACTS)
    for fname, (path, concept) in ssot.CANONICAL_FACTS.items():
        entry = facts[fname]
        assert (entry["path"], entry["concept"]) == (path, concept)
        fact = entry["fact"]
        if fact["state"] == PUB:
            assert fact["value"] == (fh["value"] if fname == "avg_health" else canon[fname]), fname
        if canon[fname] is None:
            assert fact["state"] != PUB, fname
    if fh["state"] == "measured" and facts["avg_health"]["fact"]["state"] == PUB:
        assert facts["avg_health"]["fact"]["engine_state"] == "measured"
        assert facts["avg_health"]["fact"]["engine_state_owner"] == "ssot.fleet_avg_health"


@pytest.mark.parametrize("name", ALL_CASES)
def test_t4a_owner_abstention_wins(name, snaps, payloads):
    snap, payload = _as_dict(snaps[name]), payloads[name]
    facts = payload["overview"]["facts"]
    for fname, (path, _concept) in ssot.CANONICAL_FACTS.items():
        try:
            owner = ssot.abstention_reason(snap, path)
        except RecursionError:
            continue
        if owner == AU:
            assert facts[fname]["fact"]["state"] == AU, fname
    if ssot.fleet_avg_health(snap)["state"] != "measured":
        assert facts["avg_health"]["fact"]["state"] != PUB
    direct = ssot.failed_sections(snap)[0]
    failed_pointers = {uip.json_pointer(sec) for sec in direct}
    checked = 0
    for where, fact in _walk_facts(payload):
        if any(r["role"] == "basis" and r["pointer"] in failed_pointers for r in fact["refs"]):
            checked += 1
            assert fact["state"] == AU, (where, fact["state"], fact["refs"])
    if name in ("d", "d_real", "e", "e_fallback"):
        assert checked >= 3          # a failed axis + both brief rollup lists


def test_t4b_a_value_reconcile_rejects_is_unverified(snaps):
    sample = snaps["a"]
    snap = copy.deepcopy(sample)
    truth = ssot.canonical_facts(sample)
    snap["executive_brief"]["posture"]["n_critical"] = 0
    snap["lifecycle_risk"]["summary"]["n_unknown"] = 0
    violations = ssot.reconcile(snap)
    assert any(v.startswith("executive_brief.posture.n_critical=") for v in violations)
    p = uip.project(snap)
    for name in ("n_critical", "n_unknown"):
        fact = _fact(p, name)
        assert _sv(fact) == (UV, None), (name, fact)
        assert "ssot.reconcile" in fact["reason"]
        if truth[name]:
            assert str(truth[name]) in fact["reason"]
    # the engine's own audit() stamp: the stored violation becomes a witness
    stamped = copy.deepcopy(snap)
    stamped["assessment_integrity"] = ssot.audit(stamped)
    fact = _fact(uip.project(stamped), "n_critical")
    stored = stamped["assessment_integrity"]["violations"]
    idx = next(i for i, v in enumerate(stored) if v.startswith("executive_brief.posture.n_critical="))
    assert {"pointer": f"/assessment_integrity/violations/{idx}", "role": "witness"} in fact["refs"]
    assert fact["state"] == UV
    # the legacy shape: `n_devices: 0` over an empty health list beside a collected inventory
    legacy = copy.deepcopy(sample)
    legacy["health_scores"] = []
    legacy["executive_brief"]["scale"]["n_devices"] = 0
    if any(v.startswith("executive_brief.scale.n_devices=") for v in ssot.reconcile(legacy)):
        assert _fact(uip.project(legacy), "n_devices")["state"] == UV


def test_t4b_every_reconcile_check_maps_to_a_projected_path(snaps):
    ran = []
    ssot.reconcile(snaps["a"], _ran=ran)
    assert len(ran) >= 10
    projected = set(uip.RECONCILED_PATHS)
    for name in ran:
        assert name in projected or name.startswith("lifecycle_risk.summary.by_band["), name
    assert {path for path, _c in ssot.CANONICAL_FACTS.values()} <= projected
    assert "lifecycle_risk.summary.n_devices" in projected


@pytest.mark.parametrize("name", ("c", "c_legacy", "c_noavg"))
def test_t4c_an_unscored_fleet_makes_no_health_claim(name, snaps, payloads):
    snap, payload = snaps[name], payloads[name]
    ov = payload["overview"]
    owner = ssot.fleet_avg_health(snap)
    assert owner["n_scored"] == 0
    for fname in POSTURE_NAMES:
        fact = ov["facts"][fname]["fact"]
        assert fact["state"] == NA, (fname, fact)       # c_noavg: the owner says 'unpublished', n_scored 0
        assert fact["value"] is None
        assert "no device was health-scored" in fact["reason"]
    fh = ov["fleet_health"]
    assert fh["engine_state"] == owner["state"]
    if name == "c":
        assert fh["state"] == NA and fh["not_assessed_reason"] == "all_insufficient_data"
    assert _sv(fh["n_scored"]) == (PUB, 0)                                   # a MEASURED zero
    assert _sv(fh["n_rows"]) == (PUB, len(snap["health_scores"]))
    axis = _axis_item(payload, "Fleet health")["fact"]
    assert axis["state"] == PUB
    assert axis["value"]["severity"] == "Info"
    assert axis["value"]["headline"].startswith("NOT ASSESSED")


@pytest.mark.parametrize("name", ("d", "d_real"))
def test_t4d_failed_phases_are_unavailable_never_clean(name, snaps, payloads):
    snap, payload = snaps[name], payloads[name]
    ov, tr = payload["overview"], payload["trust"]
    labels = snap["assessment_integrity"]["failed_phases"]
    punch_idx = labels.index("Migration Punch-List")
    punch = _axis_item(payload, "Migration punch-list")
    assert punch["fact"]["state"] == AU and punch["fact"]["value"] is None
    assert {"pointer": "/punchlist", "role": "basis"} in punch["fact"]["refs"]
    assert {"pointer": f"/assessment_integrity/failed_phases/{punch_idx}", "role": "failure_record"} \
        in punch["fact"]["refs"]
    assert ov["axes"]["state"] == AU
    assert ov["top_gating"]["state"] == AU
    direct, unattributed = ssot.failed_sections(snap)
    assert [row["section"] for row in tr["failures"]["direct_sections"]] == sorted(direct)
    assert {"failure_impact", "punchlist"} <= set(direct)
    assert tr["failures"]["unattributed"] is unattributed
    census = {row["key"]: row["state"] for row in tr["census"]["rows"]["items"]}
    assert census["failure_impact"] == census["punchlist"] == AU
    live = ssot.compute_schema_census(snap)["summary"]
    assert tr["census"]["summary"]["n_analysis_unavailable"]["value"] == live.get("n_analysis_unavailable", 0) >= 2
    assert "one_hop_failure_attribution" in _limitation_ids(payload)
    owner = ssot.abstention_reason(snap, "device_dossiers")
    expected = owner if owner in (AU, NC) else PUB
    if any(it["axis"] == "Asset risk register" for it in ov["axes"]["items"]):
        asset = _axis_item(payload, "Asset risk register")["fact"]
        assert asset["state"] == expected
        if expected == PUB:
            assert "one_hop_failure_attribution" in asset.get("caveats", ())   # the gap is visible per fact
    else:
        absent = {row["axis"]: row["fact"] for row in ov["absent_axes"]}
        assert absent["Asset risk register"]["state"] != PUB
    if name == "d":
        assert ov["posture_statement"]["state"] == PUB
        assert "one_hop_failure_attribution" in ov["posture_statement"]["caveats"]
        tg = ov["top_gating"]["items"]
        assert len(tg) == len(snap["executive_brief"]["top_gating"]) > 0
        assert all(item["fact"]["state"] == PUB for item in tg)
        assert [row["section"] for row in tr["failures"]["direct_sections"]] == sorted(direct)
        assert unattributed is False
        rec = [(it["label"], it["classification"], it["sections"]) for it in tr["failures"]["record"]["items"]]
        assert rec == [(lab, "sections", list(ssot.PHASE_SECTIONS[lab])) for lab in labels]
        states_a = {k: v["fact"]["state"] for k, v in payloads["a"]["overview"]["facts"].items()}
        assert {k: v["fact"]["state"] for k, v in ov["facts"].items()} == states_a
        assert tr["census"]["embedded"]["matches_live"] is False      # the stamped census predates the failure
    else:
        assert set(REAL_FAILED) <= set(labels)
        seg_idx = labels.index("Segmentation audit")
        ps = ov["posture_statement"]
        assert _sv(ps) == (AU, None)
        assert {"pointer": f"/assessment_integrity/failed_phases/{seg_idx}", "role": "failure_record"} in ps["refs"]
        fh = ov["fleet_health"]
        assert fh["state"] == AU and fh["not_assessed_reason"] is None
        assert fh["n_scored"]["state"] == fh["n_rows"]["state"] == AU
        for fname in POSTURE_NAMES:
            assert _fact(payload, fname)["state"] == AU, fname


def test_t4e_a_failure_record_propagates_to_every_dependent_fact(snaps, payloads):
    snap, p = snaps["e"], payloads["e"]
    ov = p["overview"]
    labels = snap["assessment_integrity"]["failed_phases"]
    fh = ov["fleet_health"]
    assert fh["state"] == AU and fh["not_assessed_reason"] is None
    assert fh["n_scored"]["state"] == fh["n_rows"]["state"] == AU
    for fname in POSTURE_NAMES + ("n_devices",):
        assert _fact(p, fname)["state"] == AU, fname
    ps = ov["posture_statement"]
    assert ps["state"] == AU
    assert {"pointer": f"/assessment_integrity/failed_phases/{labels.index('Segmentation audit')}",
            "role": "failure_record"} in ps["refs"]
    fleet = _axis_item(p, "Fleet health")
    assert fleet["fact"]["state"] == AU
    if any(it["axis"] == "Segmentation" for it in ov["axes"]["items"]):
        assert _axis_item(p, "Segmentation")["fact"]["state"] == AU
    gating = [it for it in ov["top_gating"]["items"] if it["axis_index"] == fleet["index"]]
    assert len(gating) == 1 and gating[0]["fact"]["state"] == AU
    assert {"pointer": f"/executive_brief/axes/{fleet['index']}", "role": "witness"} in gating[0]["fact"]["refs"]
    # the realistic shape: the failed phases' fallbacks, and the brief recomputed over them
    q = payloads["e_fallback"]["overview"]["fleet_health"]
    assert q["state"] == AU and q["not_assessed_reason"] is None and q["engine_state"] == NA


def test_t4f_not_collected_inputs_never_roll_up_clean(snaps, payloads):
    snap, p = snaps["f_nc"], payloads["f_nc"]
    ov = p["overview"]
    absent_inputs = sorted(k for k in uip.BRIEF_INPUTS if ssot.abstention_reason(snap, k) == NC)
    assert len(absent_inputs) == 11
    for key in ("axes", "top_gating"):
        lst = ov[key]
        assert lst["state"] == NC, (key, lst["state"])
        assert "may be incomplete" in lst["reason"] and NOT_A_BLIND_SPOT not in lst["reason"]
        assert all(sec in lst["reason"] for sec in absent_inputs), key
    ps = ov["posture_statement"]
    assert ps["state"] == NC and ps["value"] is None
    present = {it["axis"] for it in ov["axes"]["items"]}
    absent = {row["axis"]: row for row in ov["absent_axes"]}
    assert set(absent) == set(uip.AXIS_BASIS) - present
    for label, row in absent.items():
        assert row["basis_sections"] == list(uip.AXIS_BASIS[label])
        assert row["fact"]["state"] == NC, (label, row["fact"])


def test_t4f_absent_axes_on_the_sample_are_explained(snaps, payloads):
    snap, p = snaps["a"], payloads["a"]
    present = {row["axis"] for row in snap["executive_brief"]["axes"]}
    absent = {row["axis"]: row["fact"] for row in p["overview"]["absent_axes"]}
    assert set(absent) == set(uip.AXIS_BASIS) - present
    for label, fact in absent.items():
        basis = [ssot.abstention_reason(snap, s) for s in uip.AXIS_BASIS[label]]
        want = AU if AU in basis else NC if NC in basis else CBE
        assert fact["state"] == want and fact["value"] is None, (label, fact)
    broken = copy.deepcopy(snap)
    broken["executive_brief"]["axes"] = [r for r in broken["executive_brief"]["axes"] if r["axis"] != "Fleet health"]
    q = uip.project(broken)["overview"]
    assert {r["axis"]: r["fact"]["state"] for r in q["absent_axes"]}["Fleet health"] == UV
    assert q["axes"]["state"] == UV


def test_t4g_a_zero_over_an_uncollected_basis_is_not_a_measurement(snaps):
    snap = copy.deepcopy(snaps["a"])
    for key in ("endpoint_identity", "l3_forwarding", "service_map", "application_intelligence",
                "collection_completeness"):
        snap.pop(key, None)
    snap["executive_brief"]["scale"].update(n_endpoints=0, n_vlans=0, n_domains=0, n_collected=0)
    p = uip.project(snap)
    violations = ssot.reconcile(snap)
    for name in ("n_endpoints", "n_vlans", "n_domains", "n_collected"):
        fact = _fact(p, name)
        path = ssot.CANONICAL_FACTS[name][0]
        if any(v.startswith(path + "=") for v in violations):
            assert _sv(fact) == (UV, None), (name, fact)          # positive evidence the zero is wrong
        else:
            assert _sv(fact) == (NC, None), (name, fact)
            assert "not a measurement" in fact["reason"]
    assert sum(_fact(p, n)["state"] == NC for n in ("n_endpoints", "n_vlans", "n_domains", "n_collected")) >= 2
    legacy = copy.deepcopy(snaps["a"])
    legacy.pop("health_scores")
    legacy["executive_brief"]["posture"] = {"avg_health": 0, "n_critical": 0, "n_poor": 0, "worst_band": ""}
    # the owner itself now withholds a number with no scored-row basis (it read `measured` when this
    # projection first guarded the gap), and its abstention core calls the siblings a blind spot
    fh = ssot.fleet_avg_health(legacy)
    assert (fh["state"], fh["reason"]) == (UV, "no_scored_basis")
    projected = uip.project(legacy)
    assert _sv(_fact(projected, "avg_health")) == (UV, None)
    for name in POSTURE_NAMES:
        if name != "avg_health":
            assert ssot.abstention_reason(legacy, ssot.CANONICAL_FACTS[name][0]) == NC, name
            assert _fact(projected, name)["state"] == NC, name


def test_t4h_top_gating_must_equal_the_producers_rule(snaps):
    sample = snaps["a"]
    gating = [r["headline"] for r in sample["executive_brief"]["axes"] if r["severity"] in ("Critical", "High")]
    assert gating == sample["executive_brief"]["top_gating"] and len(gating) >= 2
    for bad in ([], gating[1:], list(reversed(gating)), gating + ["invented headline"]):
        snap = copy.deepcopy(sample)
        snap["executive_brief"]["top_gating"] = bad
        lst = uip.project(snap)["overview"]["top_gating"]
        assert lst["state"] == UV, bad
        assert "producer's rule" in lst["reason"]


def test_t4i_owner_domain_state_gates_its_zeros(snaps):
    sample = snaps["a"]
    snap = copy.deepcopy(sample)
    snap.pop("parse_yield", None)
    snap["unknown_evidence"] = unknown_evidence.compute_unknown_evidence(snap)
    state = snap["unknown_evidence"]["summary"]["state"]
    assert state.startswith("incomplete")
    ue = uip.project(snap)["trust"]["unknown_evidence"]
    for key in ("n_events", "n_unresolved"):
        if snap["unknown_evidence"]["summary"][key] == 0:
            assert ue[key]["state"] == NC, (key, ue[key])
            assert {"pointer": "/unknown_evidence/summary/state", "role": "witness"} in ue[key]["refs"]
    snap = copy.deepcopy(sample)
    snap["unknown_evidence"] = unknown_evidence.unavailable_unknown_evidence()
    ue = uip.project(snap)["trust"]["unknown_evidence"]
    assert _sv(ue["state"]) == (PUB, "unavailable")
    for key in ("n_events", "n_unresolved"):
        assert ue[key]["state"] == AU, (key, ue[key])
    snap = copy.deepcopy(sample)
    snap["coverage_matrix"]["summary"]["n_abstained"] = 0
    cm = uip.project(snap)["trust"]["coverage_matrix"]
    assert _sv(cm["n_abstained"]) == (UV, None)
    assert "coverage_matrix_shown_as_published" in cm["n_covered"].get("caveats", ())


def test_t4j_one_hop_caveat_only_when_a_failure_is_recorded(payloads):
    for where, fact in _walk_facts(payloads["a"]):
        assert "one_hop_failure_attribution" not in fact.get("caveats", ()), where
    ov = payloads["d"]["overview"]
    assert "one_hop_failure_attribution" in ov["posture_statement"]["caveats"]
    published = [it["fact"] for it in ov["axes"]["items"] if it["fact"]["state"] == PUB]
    assert published and all("one_hop_failure_attribution" in f["caveats"] for f in published)


# --------------------------------------------------------------------------------------------------
# T5 -- a measured zero is published as 0 (and only then)
# --------------------------------------------------------------------------------------------------
def test_t5_measured_zeros_publish(snaps, payloads):
    a, pa = snaps["a"], payloads["a"]
    zeros = [name for name, (path, _c) in ssot.CANONICAL_FACTS.items()
             if ssot.abstention_reason(a, path) == CBE and ssot.canonical_facts(a)[name] == 0]
    assert zeros, "the sample fleet should carry at least one measured-zero canonical fact"
    for name in zeros:
        fact = _fact(pa, name)
        assert (fact["state"], fact["value"], fact.get("engine_state")) == (PUB, 0, CBE), name
        assert "measured_zero_mapping" in fact["caveats"]
    ue_owner = a["unknown_evidence"]["summary"]
    ue = pa["trust"]["unknown_evidence"]
    for key in ("n_events", "n_unresolved"):
        if ue_owner["state"] in uip.UE_COMPLETE_STATES:
            assert _sv(ue[key]) == (PUB, ue_owner[key]), key
    live = ssot.compute_schema_census(a)["summary"]
    summ = pa["trust"]["census"]["summary"]
    assert _sv(summ["n_analysis_unavailable"]) == (PUB, live.get("n_analysis_unavailable", 0))
    assert _sv(summ["n_sections"]) == (PUB, live["n_sections"])
    if live["n_not_collected"] == 0:
        assert summ["n_not_collected"]["state"] == NC            # a zero lower bound is no evidence
    else:
        assert _sv(summ["n_not_collected"]) == (PUB, live["n_not_collected"])
    n_scored = payloads["c"]["overview"]["fleet_health"]["n_scored"]
    assert _sv(n_scored) == (PUB, 0)


def test_t5_synthetic_zero_unknown_is_proof_of_coverage():
    snap = {"lifecycle_risk": {"summary": {"n_devices": 2, "n_past_ldos": 0, "n_near": 0, "n_past_eos": 0,
                                           "n_active": 2, "n_unknown": 0}}}
    facts = uip.project_overview(snap)["facts"]
    for name in ("n_past_ldos", "n_near", "n_past_eos", "n_unknown"):
        fact = facts[name]["fact"]
        assert (fact["state"], fact["value"]) == (PUB, 0), name
        assert {"pointer": "/lifecycle_risk/summary/n_devices", "role": "denominator"} in fact["refs"]
    assert (facts["n_active"]["fact"]["state"], facts["n_active"]["fact"]["value"]) == (PUB, 2)
    assert "engine_state" not in facts["n_active"]["fact"]


def test_t5_all_zero_engine_stamp_publishes():
    stamp = {"verified": False, "n_facts": 0, "n_checked": 0, "n_violations": 0}
    fact = uip.project_trust({"executive_brief": {"ssot": stamp}})["ssot"]["engine_stamp"]
    assert _sv(fact) == (PUB, stamp)
    assert fact["engine_state"] == CBE


# --------------------------------------------------------------------------------------------------
# T6 / T7 -- the sample fleet and the minimal snapshot
# --------------------------------------------------------------------------------------------------
def test_t6_sample_shape_matches_the_owners(snaps, payloads):
    a, p = snaps["a"], payloads["a"]
    ov, tr, eng = p["overview"], p["trust"], p["engine"]
    canon = ssot.canonical_facts(a)
    assert ssot.reconcile(a) == []
    for name, entry in ov["facts"].items():
        assert entry["fact"]["state"] == PUB, (name, entry["fact"])
        assert entry["fact"]["value"] == canon[name]
    eb = a["executive_brief"]
    assert ov["axes"]["state"] == PUB
    items = ov["axes"]["items"]
    assert [it["index"] for it in items] == list(range(len(eb["axes"])))
    for it, row in zip(items, eb["axes"]):
        assert it["axis"] == row["axis"]
        assert it["fact"]["state"] == PUB, it
        assert it["fact"]["value"] == {k: row[k] for k in ("severity", "headline", "detail")}
        assert it["basis_sections"] == list(uip.AXIS_BASIS[row["axis"]])
        assert "engine_state" not in it["fact"]
    tg = ov["top_gating"]["items"]
    assert len(tg) == len(eb["top_gating"]) > 0
    for it, text in zip(tg, eb["top_gating"]):
        assert it["fact"]["state"] == PUB and it["fact"]["value"] == text
    assert ov["posture_statement"]["state"] == PUB
    assert ov["posture_statement"]["value"] == eb["posture_statement"]
    fh = ssot.fleet_avg_health(a)
    assert ov["fleet_health"]["engine_state"] == fh["state"] == "measured"
    assert ov["fleet_health"]["state"] == PUB and "reason" not in ov["fleet_health"]
    assert ov["fleet_health"]["n_scored"]["value"] == fh["n_scored"]
    assert ov["fleet_health"]["n_rows"]["value"] == fh["n_rows"]
    assert ov["fleet_health"]["not_assessed_reason"] is None
    lc = a["lifecycle_risk"]["summary"]
    rank = analyze._LIFECYCLE_BAND_RANK
    assert [(b["band"], b["rank"]) for b in ov["lifecycle"]["bands"]] == \
        sorted(rank.items(), key=lambda kv: kv[1])
    for b in ov["lifecycle"]["bands"]:
        assert ssot._LIFECYCLE_BANDS[b["fact_name"]] == b["band"]
    assert ov["lifecycle"]["of"]["value"] == lc["n_devices"]
    assert ov["lifecycle"]["asof"]["value"] == lc["asof"]
    assert tr["census"]["embedded"] == {"state": PUB, "matches_live": True}
    live = ssot.compute_schema_census(a)
    assert [r["key"] for r in tr["census"]["rows"]["items"]] == sorted(r["key"] for r in live["sections"])
    cm = a["coverage_matrix"]["summary"]
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"):
        fact = tr["coverage_matrix"][key]
        if key != "note" and fact["state"] == PUB:
            assert "coverage_matrix_shown_as_published" in fact["caveats"], key
        if isinstance(cm[key], int) and cm[key] == 0:
            assert fact["state"] == UV, key
        else:
            assert _sv(fact) == (PUB, cm[key]), key
    ue = tr["unknown_evidence"]
    assert ue["state"]["value"] == a["unknown_evidence"]["summary"]["state"]
    assert ue["state"]["value"] in uip.UNKNOWN_EVIDENCE_STATES
    assert [it["fact"]["value"]["section"] for it in ue["sources"]["items"]] == \
        [row["section"] for row in a["unknown_evidence"]["sources"]]
    rec = tr["failures"]["record"]
    assert rec["state"] == NC and rec["items"] == []
    assert "only when" in rec["reason"]
    s, live_s = tr["ssot"], ssot.summary(a)
    for key in ("verified", "n_facts", "n_checked", "n_violations"):
        if key == "n_violations" and live_s["n_checked"] and live_s[key] == 0:
            assert _sv(s[key]) == (PUB, 0)
        else:
            assert _sv(s[key]) == (PUB, live_s[key]), key
    assert s["violations"]["state"] == CBE and s["violations"]["items"] == []
    assert s["stamp_matches_live"] is True
    assert s["engine_stamp"]["value"] == eb["ssot"]
    assert eng["snapshot_schema"]["value"] == a["schema"] and eng["snapshot_schema_supported"] is True
    assert eng["code_schema_version"] == cisco_toolkit.__version__
    for key in ("script_version", "generated_at", "collected_at"):
        assert eng[key]["state"] == PUB and eng[key]["value"] == a[key]


def test_t6_negative_paths(snaps):
    sample = snaps["a"]

    def edit(fn):
        snap = copy.deepcopy(sample)
        fn(snap)
        return uip.project(snap)

    p = edit(lambda s: s["executive_brief"]["ssot"].update(n_checked=s["executive_brief"]["ssot"]["n_checked"] + 1))
    assert p["trust"]["ssot"]["stamp_matches_live"] is False
    p = edit(lambda s: s.update(schema="collect_parse_snapshot/2"))
    assert p["engine"]["snapshot_schema_supported"] is False
    p = edit(lambda s: s["lifecycle_risk"]["summary"].update(n_unknown=2.5))
    assert _sv(_fact(p, "n_unknown")) == (UV, None)
    p = edit(lambda s: s["executive_brief"]["posture"].update(avg_health=150))
    assert _fact(p, "avg_health")["state"] == UV
    # a finite, fractional average over scored rows is a measurement its owner accepts (a legacy / foreign
    # producer): 72.5 reconciles to round(mean(72, 73))
    frac = copy.deepcopy(sample)
    frac["health_scores"] = [{"switch": "a", "band": "Fair", "score": 72}, {"switch": "b", "band": "Fair", "score": 73}]
    frac["executive_brief"]["posture"]["avg_health"] = 72.5
    assert ssot.fleet_avg_health(frac)["state"] == "measured"
    assert not any(v.startswith("executive_brief.posture.avg_health=") for v in ssot.reconcile(frac))
    assert _sv(_fact(uip.project(frac), "avg_health")) == (PUB, 72.5)
    # over rows that reconcile, the score slot itself must still bound the average
    over = copy.deepcopy(frac)
    over["health_scores"] = [{"switch": "a", "band": "Excellent", "score": 150}]
    over["executive_brief"]["posture"]["avg_health"] = 150
    assert ssot.fleet_avg_health(over)["state"] == "measured"
    assert not any(v.startswith("executive_brief.posture.avg_health=") for v in ssot.reconcile(over))
    assert _sv(_fact(uip.project(over), "avg_health")) == (UV, None)
    # with no health list at all the owner withholds the number itself (no scored-row basis)
    bare = copy.deepcopy(frac)
    bare.pop("health_scores")
    assert (ssot.fleet_avg_health(bare)["state"], ssot.fleet_avg_health(bare)["reason"]) == (UV, "no_scored_basis")
    assert _sv(_fact(uip.project(bare), "avg_health")) == (UV, None)
    # the not-assessed reason says which case it is; a positive posture n_scored is no scored-row basis
    withheld = copy.deepcopy(bare)
    withheld["executive_brief"]["posture"].update(avg_health=None, n_scored=5)
    assert ssot.fleet_avg_health(withheld)["n_scored"] is None
    fact = _fact(uip.project(withheld), "avg_health")
    assert fact["state"] == NA and "no scored health rows can be counted" in fact["reason"]
    withheld["executive_brief"]["posture"]["n_scored"] = 0          # the producer's abstention record
    fact = _fact(uip.project(withheld), "avg_health")
    assert fact["state"] == NA and "no device was health-scored" in fact["reason"]
    # rows that carry no recognised band could be any band: the owner no longer certifies "none observed"
    # over them, so the empty band is withheld with reconcile's reason rather than published as empty
    odd = copy.deepcopy(sample)
    for row in odd["health_scores"]:
        row["band"] = "Unrecognised"
    odd["executive_brief"]["posture"]["worst_band"] = ""
    worst = [v for v in ssot.reconcile(odd) if v.startswith("executive_brief.posture.worst_band=")]
    assert len(worst) == 1 and "cannot be determined" in worst[0], worst
    fact = _fact(uip.project(odd), "worst_band")
    assert fact["state"] == UV and "cannot be determined" in fact["reason"], fact
    # failure refs: the `_unavailable` sentinel and an integrity failure token
    p = edit(lambda s: s.update(punchlist={"_unavailable": True}))
    punch = _axis_item(p, "Migration punch-list")["fact"]
    assert punch["state"] == AU and {"pointer": "/punchlist/_unavailable", "role": "failure_record"} in punch["refs"]
    p = edit(lambda s: s.update(assessment_integrity={"lifecycle_risk": "compute_failed"}))
    fact = _fact(p, "n_unknown")
    assert fact["state"] == AU
    assert {"pointer": "/assessment_integrity/lifecycle_risk", "role": "failure_record"} in fact["refs"]
    # a malformed health list is unverified, not a blind spot
    p = edit(lambda s: s.update(health_scores={"x": 1}))
    fh = p["overview"]["fleet_health"]
    assert fh["n_rows"]["state"] == fh["n_scored"]["state"] == UV
    # reasons say what happened: an engine null is not a collection blind spot
    p = edit(lambda s: s["executive_brief"]["scale"].update(n_devices=None))
    fact = _fact(p, "n_devices")
    assert fact["state"] == NC and "null" in fact["reason"] and "blind spot" not in fact["reason"]
    # labels that are not text are published as null, never as a Python repr
    items = uip.project_trust({"assessment_integrity": {"failed_phases": [None, {"a": 1}, 3.5, "x"]}})
    labels = [(it["label"], it["classification"]) for it in items["failures"]["record"]["items"]]
    assert labels == [(None, "unknown"), (None, "unknown"), (None, "unknown"), ("x", "unknown")]
    # a present null section is counted (the census's lower bound), with its limitation attached
    summ = uip.project_trust({"schema": "s", "nulled": None, "health_scores": None})["census"]["summary"]
    assert _sv(summ["n_not_collected"]) == (PUB, 2)
    assert "census_present_keys_only" in summ["n_not_collected"]["caveats"]


def test_t6b_the_withheld_average_says_which_owner_reason_withheld_it(snaps):
    """``ssot.fleet_avg_health`` withholds a published average for one of two reasons
    (``ssot.FLEET_AVG_UNVERIFIED_REASONS``). The projection said "not a finite number" for both, which is false
    for a finite number that merely has no scored health rows behind it."""
    bare = copy.deepcopy(snaps["a"])
    bare.pop("health_scores")                                   # a finite average, no rows to back it
    text = copy.deepcopy(snaps["a"])
    text["executive_brief"]["posture"]["avg_health"] = "abc"    # scored rows, a published value that is no number
    cases = {"no_scored_basis": bare, "not_a_number": text}
    assert set(cases) == set(ssot.FLEET_AVG_UNVERIFIED_REASONS)  # every owner reason is exercised
    for why, snap in cases.items():
        fh = ssot.fleet_avg_health(snap)
        assert (fh["state"], fh["reason"]) == (UV, why)
        p = uip.project(snap)
        fact = _fact(p, "avg_health")
        assert fact["state"] == UV and why in fact["reason"], (why, fact["reason"])
        assert p["overview"]["fleet_health"]["reason"] == fact["reason"]
        if why == "no_scored_basis":
            assert "not a finite number" not in fact["reason"], fact["reason"]
            assert "no scored health rows" in fact["reason"] and "health_scores" in fact["reason"], fact["reason"]
        else:
            assert "not a finite number" in fact["reason"], fact["reason"]
    assert "no scored-row basis" in uip.DOMAIN_STATE_OWNERS[UV]


def test_t7_minimal_snapshot_is_blind_spots_not_health(snaps, payloads):
    p = payloads["b"]
    ov, tr = p["overview"], p["trust"]
    for name, entry in ov["facts"].items():
        assert entry["fact"]["state"] == NC and entry["fact"]["refs"] == [], name
    for key in ("axes", "top_gating", "posture_statement"):
        assert ov[key]["state"] == NC, key
    assert {row["axis"] for row in ov["absent_axes"]} == set(uip.AXIS_BASIS)
    assert {row["fact"]["state"] for row in ov["absent_axes"]} == {NC}
    assert [(r["key"], r["state"]) for r in tr["census"]["rows"]["items"]] == [("devices", PUB), ("schema", PUB)]
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"):
        assert tr["coverage_matrix"][key]["state"] == NC, key
    for key in ("state", "n_events", "n_unresolved", "source_coverage_complete", "claim_scope", "note",
                "sources"):
        assert tr["unknown_evidence"][key]["state"] == NC, key
    s = tr["ssot"]
    assert _sv(s["verified"]) == (PUB, False) and _sv(s["n_checked"]) == (PUB, 0)
    assert s["n_violations"]["state"] == NC and s["violations"]["state"] == NC
    assert s["engine_stamp"]["state"] == NC and s["stamp_matches_live"] is None
    assert tr["census"]["embedded"] == {"state": NC, "matches_live": None}
    assert tr["census"]["summary"]["n_not_collected"]["state"] == NC
    assert "census_present_keys_only" in _limitation_ids(p)
    assert p["engine"]["snapshot_schema"]["state"] == PUB and p["engine"]["snapshot_schema_supported"] is True
    assert p["engine"]["script_version"]["state"] == NC


# --------------------------------------------------------------------------------------------------
# T8 - T11 -- deterministic, no mutation / aliasing, total on garbage, pure
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "b", "d", "e"))
def test_t8_deterministic_and_key_order_independent(name, snaps, payloads):
    snap = snaps[name]
    once = json.dumps(uip.project(snap), sort_keys=True, allow_nan=False)
    twice = json.dumps(uip.project(snap), sort_keys=True, allow_nan=False)
    assert once == twice
    assert once == json.dumps(payloads[name], sort_keys=True, allow_nan=False)
    reordered = json.loads(json.dumps(snap, sort_keys=True))
    assert uip.project(reordered) == payloads[name]


@pytest.mark.parametrize("name", ("a", "d"))
def test_t9_never_mutates_and_never_aliases(name, snaps):
    snap = copy.deepcopy(snaps[name])
    before = copy.deepcopy(snap)
    payload = uip.project(snap)
    assert snap == before
    _mutate_everything(payload)
    assert snap == before
    assert uip.project(snap) == uip.project(before)
    again = uip.project(snap)
    for lim, orig in zip(again["trust"]["limitations"], uip.LIMITATIONS):
        assert lim["applies_to"] == list(orig["applies_to"])


_ALL_NC = ("g_none", "g_list", "g_str", "g_zero", "g_empty", "g_eb_int")
_LIVE_PUBLISHED = {"/trust/ssot/verified", "/trust/ssot/n_facts", "/trust/ssot/n_checked"}


@pytest.mark.parametrize("name", tuple(GARBAGE))
def test_t10_total_on_garbage(name, snaps, payloads, validator):
    snap, p = snaps[name], payloads[name]
    validator.validate(p)
    json.dumps(p, allow_nan=False)
    facts = list(_walk_facts(p))
    assert facts
    ov, tr = p["overview"], p["trust"]
    for where, fact in facts:
        if fact["state"] == PUB and isinstance(fact.get("value"), int):
            assert 0 <= fact["value"] <= uip.JS_MAX_SAFE_INT or fact["value"] is False or fact["value"] is True
    if name in _ALL_NC:
        census_live = name == "g_eb_int"
        for where, fact in facts:
            if where in _LIVE_PUBLISHED or (census_live and where.startswith("/trust/census")):
                continue
            assert fact["state"] == NC, (where, fact)
        s = tr["ssot"]
        assert (s["verified"]["value"], s["n_facts"]["value"], s["n_checked"]["value"]) == (False, 0, 0)
    if name == "g_eb_int":
        owner = {r["key"]: r["state"] for r in ssot.compute_schema_census(snap)["sections"]}
        assert {r["key"]: r["state"] for r in tr["census"]["rows"]["items"]} == owner
        assert owner["executive_brief"] == PUB
    if name == "g_nan_posture":
        assert _fact(p, "avg_health")["state"] == NA
    if name == "g_lc_inf":
        assert _fact(p, "n_near")["state"] == UV
        assert _fact(p, "n_unknown")["state"] == UV
    if name == "g_huge":
        assert _fact(p, "n_near")["state"] == UV
        assert _fact(p, "n_unknown")["state"] == UV                     # 2**53 + 1: not exact in a browser
        assert ov["lifecycle"]["of"]["state"] == UV
        assert tr["coverage_matrix"]["n_rows"]["state"] == UV
        assert "2^53" in _fact(p, "n_unknown")["reason"]
    if name == "g_eb_badtypes":
        assert _fact(p, "n_devices")["state"] == UV
        assert ov["axes"]["state"] == UV and ov["axes"]["items"] == []
        assert [it["fact"]["state"] for it in ov["top_gating"]["items"]] == [UV, UV]
        assert ov["posture_statement"]["state"] == UV
    if name == "g_eb_unavailable":
        under = [(w, f) for w, f in facts if (f["subject"] or "").startswith("/executive_brief")]
        assert len(under) >= 12
        for where, fact in under:
            assert fact["state"] == AU, (where, fact)
    if name == "g_fp_str":
        assert tr["failures"]["record"]["state"] == UV
        assert tr["failures"]["unattributed"] is True
    if name == "g_fp_mixed":
        assert [it["classification"] for it in tr["failures"]["record"]["items"]] == ["unknown"] * 3
        assert [it["label"] for it in tr["failures"]["record"]["items"]] == [None, None, "Totally new phase"]
        assert tr["failures"]["unattributed"] is True
    if name == "g_cm_nan":
        assert tr["coverage_matrix"]["n_rows"]["state"] == UV
        assert tr["coverage_matrix"]["by_state"]["state"] == UV
    if name == "g_ue_bad":
        assert tr["unknown_evidence"]["state"]["state"] == UV
        assert [it["fact"]["state"] for it in tr["unknown_evidence"]["sources"]["items"]] == [UV]
    if name == "g_band_unhashable":
        # the owner no longer raises on an unhashable band: it reports the band facts that row could change
        # as unverifiable, so the live self-verification is published -- and says NOT verified
        s = tr["ssot"]
        assert _sv(s["verified"]) == (PUB, False), s["verified"]
        assert s["n_violations"]["state"] == PUB and s["n_violations"]["value"] >= 1
        assert any("carry no recognised band" in v for v in s["violations"]["items"]), s["violations"]
        assert s["stamp_matches_live"] is False                         # the engine's stamp said verified
        assert _fact(p, "n_devices")["state"] == PUB                    # the rest is unaffected
    if name == "g_deep_axes":
        # the owners are total at this depth: the brief is withheld for what it lacks, not for an owner fault
        assert ov["axes"]["state"] == UV and "raised" not in ov["axes"]["reason"], ov["axes"]["reason"]
    if name == "g_deep_section":
        assert {r["key"]: r["state"] for r in tr["census"]["rows"]["items"]} == {"schema": PUB, "punchlist": CBE}
        punch = [row for row in ov["absent_axes"] if row["axis"] == "Migration punch-list"]
        assert punch and punch[0]["fact"]["state"] in (UV, NC)
    if name == "g_deep_label":
        assert tr["failures"]["record"]["items"][0]["label"] is None
        assert tr["failures"]["unattributed"] is True
    if name.startswith("g_poison"):
        assert "NaN" not in json.dumps(p, allow_nan=False)
        assert "Infinity" not in json.dumps(p, allow_nan=False)
        for fname in ("n_devices", "n_unknown", "n_design_decisions"):
            assert _fact(p, fname)["state"] in (UV, NA, NC, AU), fname


def test_t11_pure_no_file_socket_or_process_io(snaps, payloads, monkeypatch):
    def _no_io(*_a, **_kw):
        raise AssertionError("ui_projection performed I/O")

    for target, attr in ((builtins, "open"), (io, "open"), (os, "open"), (socket, "socket"),
                         (socket, "create_connection"), (subprocess, "Popen")):
        monkeypatch.setattr(target, attr, _no_io)
    assert uip.project(snaps["a"]) == payloads["a"]
    assert uip.project(snaps["d_real"]) == payloads["d_real"]


def test_module_imports_only_stdlib_and_the_explicit_projection_owners():
    tree = ast.parse(MODULE_SRC.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            imported.update(f"{base}:{alias.name}" for alias in node.names)
    # Topology/path projection delegates to the existing offline FIB owner, including its exact address
    # observation rules; ipaddress canonicalizes those evidence joins. Decision rollups admit only the
    # existing public vocabulary, stored-row folds, capture-flag precedence and VLAN membership owners.
    # Coverage joins/folds are admitted by their exact public names; neither a module-wide analyze or
    # coverage_matrix import nor private/other owner imports are admitted.
    # Stored carriage adds only its public vocabulary, selectors, validators and identity joins.
    # Its compute function and whole module remain outside this exact read-only import boundary.
    allowed = {"math", "re", "ipaddress", "__future__:annotations", "types:MappingProxyType", "cisco_toolkit:ssot",
               "cisco_toolkit:__version__", "cisco_toolkit:fib", "cisco_toolkit.analyze:PUNCH_SEVERITIES",
               "cisco_toolkit.analyze:compute_device_findings", "cisco_toolkit.analyze:device_config_capture",
               "cisco_toolkit.analyze:vlan_cutover_host_index", "cisco_toolkit.coverage_matrix:CoverageRowIndex",
               "cisco_toolkit.coverage_matrix:index_coverage_rows", "cisco_toolkit.coverage_matrix:match_coverage_cell",
               "cisco_toolkit.coverage_matrix:compute_device_coverage", "cisco_toolkit.coverage_matrix:COVERAGE_STATE_ORDER",
               "cisco_toolkit.coverage_matrix:COVERAGE_DIMENSIONS", "cisco_toolkit.coverage_matrix:COVERAGE_VERDICT_SOURCES",
               "cisco_toolkit.vlan_carriage:RELATIONS", "cisco_toolkit.vlan_carriage:END_SIGNALS",
               "cisco_toolkit.vlan_carriage:BASES", "cisco_toolkit.vlan_carriage:EVIDENCE_SHAPES",
               "cisco_toolkit.vlan_carriage:validate_vlan_carriage", "cisco_toolkit.vlan_carriage:vlan_row_identity",
               "cisco_toolkit.vlan_carriage:carriage_observation_admission",
               "cisco_toolkit.vlan_carriage:carriage_host_identity", "cisco_toolkit.vlan_carriage:carriage_port_identity"}
    extra = {name for name in imported if name not in allowed and not name.startswith("typing:")}
    assert not extra, extra
    private = sorted({node.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                      and node.value.id == "ssot" and node.attr.startswith("_")})
    assert not private, private                     # production code reads no private owner name


# --------------------------------------------------------------------------------------------------
# T12 -- the copied vocabularies and the axis-basis table are held against the engine source
# --------------------------------------------------------------------------------------------------
def _function_ast(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def test_t12_axis_basis_is_held_against_the_producer_source():
    labels, non_literal = set(), []
    for node in ast.walk(_function_ast(analyze.compute_executive_brief)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ax":
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                labels.add(first.value)
            else:
                non_literal.append(ast.dump(node)[:120])
    assert not non_literal, non_literal
    assert len(labels) >= 12
    assert set(uip.AXIS_BASIS) == labels
    params = set(_brief_params())
    phase_sections = set().union(*ssot.PHASE_SECTIONS.values())
    for label, basis in uip.AXIS_BASIS.items():
        assert basis and len(set(basis)) == len(basis), label
        assert set(basis) <= params, (label, set(basis) - params)
        assert set(basis) <= phase_sections, (label, set(basis) - phase_sections)
    assert set(uip.POSTURE_STATEMENT_BASIS) <= params & phase_sections
    assert uip.BRIEF_INPUTS == tuple(sorted(set().union(*uip.AXIS_BASIS.values(), uip.POSTURE_STATEMENT_BASIS)))
    # the axes the producer emits with NO input at all are the ones it always emits
    assert {row["axis"] for row in analyze.compute_executive_brief()["axes"]} == set(uip.ALWAYS_EMITTED_AXES)


def test_t12_unregistered_axis_label_fails_closed_to_every_brief_input():
    snap = {"executive_brief": {"axes": [{"axis": "Brand-new axis", "severity": "Low", "headline": "h",
                                          "detail": "d"}]}}
    item = uip.project_overview(snap)["axes"]["items"][0]
    assert item["basis_sections"] == list(uip.BRIEF_INPUTS)
    assert item["fact"]["state"] == NC            # its (fail-closed) basis is not collected here


def test_t12_vocabularies_equal_their_owners():
    assert uip.SEVERITIES == tuple(analyze._APP_SEV_RANK)
    assert uip.HEALTH_BANDS == ssot._HEALTH_BAND_ORDER
    assert set(uip.COVERAGE_STATES) == set(unknown_evidence._COVERAGE_STATES)
    assert len(uip.COVERAGE_STATES) == len(set(uip.COVERAGE_STATES))
    assert set(uip.UE_SOURCE_STATES) == set(unknown_evidence._SOURCE_STATES)
    assert uip.SNAPSHOT_SCHEMA == snapshot_state({}, [])["schema"]
    assert dict(uip.LIFECYCLE_BAND_FACTS) == ssot._LIFECYCLE_BANDS
    assert dict(uip.LIFECYCLE_BAND_FACTS_BY_BAND) == {b: n for n, b in ssot._LIFECYCLE_BANDS.items()}
    rank = analyze._LIFECYCLE_BAND_RANK
    assert uip.LIFECYCLE_BAND_ORDER == tuple(sorted(rank, key=rank.get))
    assert set(uip.LIFECYCLE_BAND_FACTS) <= set(ssot.CANONICAL_FACTS)
    assert uip.JS_MAX_SAFE_INT == 2 ** 53 - 1
    # the unknown-evidence summary states: every literal assigned to `state` by the two assemblers
    found = set()
    for fn in (unknown_evidence._assemble, unknown_evidence.unavailable_unknown_evidence):
        for node in ast.walk(_function_ast(fn)):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                is_state = (isinstance(target, ast.Name) and target.id == "state") or (
                    isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "state")
                if is_state:
                    found.update(c.value for c in ast.walk(node.value)
                                 if isinstance(c, ast.Constant) and isinstance(c.value, str))
    assert found == set(uip.UNKNOWN_EVIDENCE_STATES)
    # only the states _assemble reaches with every source observed completely vouch for a zero:
    # the true branch of each `... if source_complete else ...` expression
    complete = {node.body.value for node in ast.walk(_function_ast(unknown_evidence._assemble))
                if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Name)
                and node.test.id == "source_complete" and isinstance(node.body, ast.Constant)}
    assert complete == set(uip.UE_COMPLETE_STATES)


def test_t12_domain_tokens_are_really_emitted_by_their_owners(snaps):
    fah = ssot.fleet_avg_health
    emitted = {
        fah(snaps["a"])["state"],
        fah({"health_scores": [], "executive_brief": {"posture": {"avg_health": None}}})["state"],
        fah({"health_scores": [{"band": "Good", "score": 80}],
             "executive_brief": {"posture": {"avg_health": "abc"}}})["state"],
        fah({})["state"],
    }
    assert emitted == set(uip.FLEET_HEALTH_STATES)
    assert set(uip.DOMAIN_STATE_OWNERS) == {NA, UV}
    for token, owner in uip.DOMAIN_STATE_OWNERS.items():
        assert "ssot.fleet_avg_health" in owner, token
    assert "cisco_toolkit.ui_projection" in uip.DOMAIN_STATE_OWNERS[UV]
    assert set(uip.DOMAIN_STATE_OWNERS) <= set(uip.FLEET_HEALTH_STATES)
    reasons = {
        analyze.compute_executive_brief(health_scores=[])["posture"].get("not_assessed"),
        analyze.compute_executive_brief(
            health_scores=[{"band": "Insufficient Data", "score": 90}])["posture"].get("not_assessed"),
        analyze.compute_executive_brief(
            health_scores=[{"band": "Good", "score": None}])["posture"].get("not_assessed"),
    }
    assert reasons == set(uip.NOT_ASSESSED_REASONS)
    classes = {ssot.phase_classification(lab) for lab in
               ("Failure Impact", "Flow paths", "HTML Explorer", "Totally new phase")}
    assert classes == set(uip.PHASE_CLASSIFICATIONS)
    kinds = {ssot._census_kind(v) for v in (None, [], {}, 1)}
    assert kinds == set(uip.CENSUS_KINDS)


# --------------------------------------------------------------------------------------------------
# T13 -- the real engine
# --------------------------------------------------------------------------------------------------
def test_t13_real_engine_failed_phases(snaps, payloads, validator):
    snap, p = snaps["d_real"], payloads["d_real"]
    validator.validate(p)
    labels = snap["assessment_integrity"]["failed_phases"]
    assert set(REAL_FAILED) <= set(labels)
    assert not snap["executive_brief"].get("_unavailable")
    assert _axis_item(p, "Migration punch-list")["fact"]["state"] == AU
    assert _axis_item(p, "Fleet health")["fact"]["state"] == AU
    record = [it["label"] for it in p["trust"]["failures"]["record"]["items"]]
    assert record == [lab if isinstance(lab, str) else None for lab in labels]
    for where, fact in _walk_facts(p):
        assert "raised" not in fact.get("reason", ""), (where, fact["reason"])   # no owner fault on real output


# --------------------------------------------------------------------------------------------------
# W12-A -- decision rollups are typed, coverage-honest, unpersisted views of their existing owners
# --------------------------------------------------------------------------------------------------
def _decision_snapshot():
    groups = [{"group": "Move Group 8", "switches": ["sw.b", "sw/a"], "endpoints": 2},
              {"group": "Move Group 2", "switches": ["edge"], "endpoints": 0}]
    rows = []
    for group, statuses in zip(groups, (("pass", "warn", "info"), ("fail", "info"))):
        rows.append({**copy.deepcopy(group), "readiness": "NOT READY" if "fail" in statuses else "CAUTION",
                     "n_fail": statuses.count("fail"), "n_warn": statuses.count("warn"),
                     "checks": [{"check": f"Check {i}", "status": status, "note": "owner evidence",
                                 "phase": "Inventory"} for i, status in enumerate(statuses)]})
    return {"move_groups": groups, "migration_readiness": rows,
            "interfaces": {host: {"Gi1/0/1": {"status": "up"}} for g in groups for host in g["switches"]},
            "health_scores": [{"switch": "sw.b", "band": "Critical", "score": 20},
                              {"switch": "sw/a", "band": "Poor", "score": 40},
                              {"switch": "edge", "band": "Insufficient Data", "score": None}],
            "executive_brief": {"posture": {"avg_health": 30, "n_critical": 1, "n_poor": 1,
                                             "worst_band": "Critical"}}}


def _assert_overview_schema(overview):
    schema = uip.ui_projection_schema()
    Draft202012Validator({"$ref": "#/$defs/Overview", "$defs": schema["$defs"]}).validate(overview)


def test_w12a_readiness_preserves_written_identity_and_check_evidence():
    snap = _decision_snapshot()
    before = copy.deepcopy(snap)
    ov = uip.project_overview(snap)
    _assert_overview_schema(ov)
    groups = ov["readiness"]["groups"]
    assert groups["state"] == PUB
    assert [r["group"]["value"] for r in groups["items"]] == [g["group"] for g in snap["move_groups"]]
    for i, row in enumerate(groups["items"]):
        owner = snap["migration_readiness"][i]
        for key in ("group", "readiness", "switches", "endpoints", "n_fail", "n_warn"):
            assert _sv(row[key]) == (PUB, owner[key]), key
        assert row["checks"]["state"] == PUB
        assert "move_group_endpoints_not_distinct" in row["endpoints"]["caveats"]
        assert {"pointer": f"/move_groups/{i}/endpoints", "role": "witness"} in row["endpoints"]["refs"]
        for j, check in enumerate(row["checks"]["items"]):
            for key in ("check", "status", "note", "phase"):
                assert _sv(check[key]) == (PUB, owner["checks"][j][key])
    for _where, fact in _walk_facts(ov):
        for ref in fact["refs"]:
            assert _resolve(snap, ref["pointer"]) is not _MISSING, ref
    assert snap == before
    _mutate_everything(ov)
    assert snap == before


def test_w12a_reversed_readiness_and_move_groups_keep_their_labels():
    snap = _decision_snapshot()
    snap["move_groups"].reverse()
    result = uip.project_overview(snap)["readiness"]["groups"]
    assert result["state"] == PUB
    assert [r["group"]["value"] for r in result["items"]] == ["Move Group 8", "Move Group 2"]
    snap["migration_readiness"].reverse()
    result = uip.project_overview(snap)["readiness"]["groups"]
    assert result["state"] == PUB
    assert [r["group"]["value"] for r in result["items"]] == ["Move Group 2", "Move Group 8"]


@pytest.mark.parametrize("edit", [
    lambda s: s["migration_readiness"][0].update(readiness="READY"),
    lambda s: s["migration_readiness"][0].update(n_fail=1),
    lambda s: s["migration_readiness"][0].update(n_warn=True),
    lambda s: s["migration_readiness"][0].update(endpoints=0),
    lambda s: s["migration_readiness"][0].update(switches=["edge"]),
    lambda s: s["migration_readiness"].append(copy.deepcopy(s["migration_readiness"][0])),
    lambda s: s["migration_readiness"].pop(),
    lambda s: s["migration_readiness"][0]["checks"][0].update(status="healthy"),
    lambda s: s["migration_readiness"][0].update(checks=[]),
    lambda s: s["move_groups"][1].update(group=s["move_groups"][0]["group"]),
    lambda s: s["move_groups"][1].update(switches=["sw.b"]),
    lambda s: s["move_groups"][0].update(group=""),
    lambda s: s["move_groups"][0].update(endpoints="2"),
])
def test_w12a_malformed_or_contradictory_readiness_never_publishes_a_verdict(edit):
    snap = _decision_snapshot()
    edit(snap)
    ov = uip.project_overview(snap)
    _assert_overview_schema(ov)
    groups = ov["readiness"]["groups"]
    assert groups["state"] == UV
    assert all(_sv(r["readiness"]) == (UV, None) for r in groups["items"])


@pytest.mark.parametrize("edit", [
    lambda s: s.pop("migration_readiness"),
    lambda s: s.pop("move_groups"),
    lambda s: [g.pop("group") for g in s["move_groups"]],
    lambda s: s["migration_readiness"][0].pop("readiness"),
    lambda s: s["move_groups"][0].pop("endpoints"),
    lambda s: s.pop("interfaces"),
    lambda s: s.pop("health_scores"),
    lambda s: s.update(health_scores=[]),
])
def test_w12a_missing_readiness_evidence_is_not_collected(edit):
    snap = _decision_snapshot()
    edit(snap)
    ov = uip.project_overview(snap)
    _assert_overview_schema(ov)
    groups = ov["readiness"]["groups"]
    assert groups["state"] == NC
    assert all(_sv(r["readiness"]) == (NC, None) for r in groups["items"])


@pytest.mark.parametrize("integrity, pointer", [
    ({"failed_phases": ["Migration Readiness"]}, "/assessment_integrity/failed_phases/0"),
    ({"move_groups": "failed"}, "/assessment_integrity/move_groups"),
    ({"failed_phases": ["Health Scores"]}, "/assessment_integrity/failed_phases/0"),
    ({"failed_phases": ["Protocol Health"]}, "/assessment_integrity/failed_phases/0"),
    ({"failed_phases": ["FHRP configured-group baseline"]}, "/assessment_integrity/failed_phases/0"),
])
def test_w12a_failed_readiness_or_move_group_section_withholds_the_stored_rows(integrity, pointer):
    snap = _decision_snapshot()
    snap["assessment_integrity"] = integrity
    groups = uip.project_overview(snap)["readiness"]["groups"]
    assert groups["state"] == AU
    assert groups["items"] and all(_sv(r["readiness"]) == (AU, None) for r in groups["items"])
    assert {"pointer": pointer, "role": "failure_record"} in groups["refs"]


def test_w12a_readiness_input_vocabulary_is_complete_against_the_producer_signature():
    params = set(inspect.signature(analyze.compute_migration_readiness).parameters)
    transient = {"config", "dep_map", "vtp_safety_subject_scope", "ipv6_routing_subject_scope"}
    sections = {"interfaces" if p == "all_interfaces" else p for p in params - transient}
    assert set(uip.READINESS_INPUTS) == sections
    assert set(uip.READINESS_CHECK_STATUSES) == {"pass", "warn", "fail", "info"}
    schema = uip.ui_projection_schema()["$defs"]
    assert _branches(schema["CheckStatusFact"])[0]["properties"]["value"]["enum"] == list(uip.READINESS_CHECK_STATUSES)


def test_w12a_real_move_group_and_readiness_producers_supply_the_published_values():
    from cisco_toolkit.model import InterfaceData

    ifaces = {host: {"Gi1/0/1": InterfaceData(port="Gi1/0/1", switchport_mode="Access", vlan="20",
                                             end_host_mac="0011.2233.4455")} for host in ("a", "b")}
    groups = analyze.compute_move_groups(ifaces)
    assert len(groups) == 1 and groups[0]["endpoints"] == 2  # the same MAC is observed on both switches
    dep = {"single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {}, "orphan": [],
           "access_by_vlan": {}, "model": {"hosts": ["a", "b"]}}
    health = [{"switch": host, "band": "Good", "score": 90} for host in ifaces]
    readiness = analyze.compute_migration_readiness(ifaces, groups, health, [], [], [], [], dep)
    snap = {"move_groups": groups, "migration_readiness": readiness, "health_scores": health,
            "interfaces": {host: {port: vars(value) for port, value in ports.items()} for host, ports in ifaces.items()}}
    projected = uip.project_overview(snap)["readiness"]["groups"]
    assert projected["state"] == PUB
    assert projected["items"][0]["readiness"]["value"] == readiness[0]["readiness"]
    assert projected["items"][0]["endpoints"]["value"] == 2
    assert "move_group_endpoints_not_distinct" in projected["items"][0]["endpoints"]["caveats"]
    assert {c["status"]["value"] for c in projected["items"][0]["checks"]["items"]} <= set(uip.READINESS_CHECK_STATUSES)


def test_w12a_health_partition_order_counts_and_members_are_owned_by_ssot():
    snap = _decision_snapshot()
    before = copy.deepcopy(snap)
    ov = uip.project_overview(snap)
    _assert_overview_schema(ov)
    bands = ov["fleet_health"]["bands"]
    assert [r["band"] for r in bands] == list(ssot._HEALTH_BAND_ORDER) + [ssot._HEALTH_BAND_NOT_SCORED]
    expected = ssot.health_band_partition(snap)["bands"]
    assert [(r["band"], r["n"]["value"], r["hosts"]["value"]) for r in bands] == [
        (r["band"], r["n"], r["hosts"] or None) for r in expected]
    assert all(r["hosts"]["state"] == (PUB if source["hosts"] else CBE) for r, source in zip(bands, expected))
    assert bands[0]["n"]["value"] == ssot.canonical_facts(snap)["n_critical"]
    assert bands[1]["n"]["value"] == ssot.canonical_facts(snap)["n_poor"]
    assert snap == before
    bands[0]["hosts"]["value"].append("mutated")
    assert snap == before


@pytest.mark.parametrize("edit", [
    lambda s: s["health_scores"].append(copy.deepcopy(s["health_scores"][0])),
    lambda s: s["health_scores"][0].update(band="Healthy"),
    lambda s: s["health_scores"][0].update(switch=""),
    lambda s: s["health_scores"].append(42),
    lambda s: s.update(health_scores={}),
    lambda s: s["executive_brief"]["posture"].update(n_critical=0),
    lambda s: s["executive_brief"]["posture"].update(n_poor=True),
])
def test_w12a_health_partition_withholds_counts_and_hosts_on_malformed_or_canonical_drift(edit):
    snap = _decision_snapshot()
    edit(snap)
    ov = uip.project_overview(snap)
    _assert_overview_schema(ov)
    assert all(_sv(r[key]) == (UV, None) for r in ov["fleet_health"]["bands"] for key in ("n", "hosts"))


def test_w12a_missing_health_and_failed_health_never_publish_zero_or_host_lists():
    absent = _decision_snapshot()
    absent.pop("health_scores")
    assert all(_sv(r[key]) == (NC, None) for r in uip.project_overview(absent)["fleet_health"]["bands"]
               for key in ("n", "hosts"))
    failed = _decision_snapshot()
    failed["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    assert all(_sv(r[key]) == (AU, None) for r in uip.project_overview(failed)["fleet_health"]["bands"]
               for key in ("n", "hosts"))


def test_w12a_unscored_band_membership_survives_average_abstention_and_overlap_absence_stays_withheld():
    snap = _decision_snapshot()
    for row in snap["health_scores"]:
        row.update(band="Insufficient Data", score=None)
    snap["executive_brief"]["posture"].update(avg_health=None, n_critical=0, n_poor=0, worst_band="")
    ov = uip.project_overview(snap)
    assert ov["fleet_health"]["state"] == NA
    bands = ov["fleet_health"]["bands"]
    assert all(_sv(r["n"]) == (NA, None) for r in bands[:-1])
    assert _sv(bands[-1]["n"]) == (PUB, 3)
    assert _sv(bands[-1]["hosts"]) == (PUB, [r["switch"] for r in snap["health_scores"]])
    snap = _decision_snapshot()
    snap["executive_brief"]["posture"].pop("n_critical")
    bands = uip.project_overview(snap)["fleet_health"]["bands"]
    assert _sv(bands[0]["n"]) == (NC, None)
    assert _sv(bands[0]["hosts"]) == (NC, None)
    assert _sv(bands[1]["n"]) == (PUB, 1)
