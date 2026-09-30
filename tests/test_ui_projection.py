"""ui_projection/1 -- slice 1 (Overview + Trust) of the one typed engine->UI projection (D9).

"Facts in Python, geometry in the browser": every verdict, count, rollup, denominator, severity band
and evidence state a screen shows comes from an engine owner through ONE schema-tagged payload. These
tests hold the projection to that contract against the REAL producers:

* every fixture is built with the engine's own code (the shipped sample fleet; the brief recomputed by
  ``analyze.compute_executive_brief`` for the all-unscored and failed-phase variants; one real
  ``COLLECT_PARSE_V3_23_0.main()`` run with two phases forced to fail) -- never a hand-shaped stub;
* expectations are read from the owners (``ssot.canonical_facts`` / ``abstention_reason`` /
  ``fleet_avg_health`` / ``failed_sections`` / ``compute_schema_census`` / ``summary``), not cached
  literal counts;
* the vocabularies the projection copies are held equal to their owners by source/AST checks, so a
  producer change fails here instead of drifting silently.

Coverage honesty is the point: absence never renders as 0 / healthy, a MEASURED zero is published as 0,
a failed phase's fallback is ``analysis_unavailable``, and malformed values are ``unverified`` rather
than coerced.
"""
from __future__ import annotations

import ast
import builtins
import copy
import inspect
import json
import pathlib
import socket
import sys
import textwrap

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
    """Recompute the brief with the REAL producer, then re-inject what main() adds (n_vlans /
    n_collected, COLLECT_PARSE_V3_23_0.py:5269-5275) and the SSOT stamp (:5440)."""
    brief = analyze.compute_executive_brief(**{p: snap.get(p) for p in _brief_params()})
    brief["scale"]["n_vlans"] = ref["executive_brief"]["scale"]["n_vlans"]
    brief["scale"]["n_collected"] = ref["executive_brief"]["scale"]["n_collected"]
    snap["executive_brief"] = brief
    brief["ssot"] = ssot.summary(snap)
    return snap


def _poison(obj):
    """Recursively replace every numeric leaf with NaN (bools are kept: they are not numbers here)."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return float("nan")
    if isinstance(obj, dict):
        return {k: _poison(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_poison(v) for v in obj]
    return obj


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


# --------------------------------------------------------------------------------------------------
# fixtures -- built with the real producers
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


def _failed_phases(sample):
    snap = copy.deepcopy(sample)
    snap["failure_impact"] = []          # the _run_phase fallbacks (COLLECT_PARSE_V3_23_0.py:4518 / :4879)
    snap["punchlist"] = []
    snap["assessment_integrity"] = {"failed_phases": ["Failure Impact", "Migration Punch-List"]}
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
    "g_eb_badtypes": lambda s: {"executive_brief": {"scale": {"n_devices": -5}, "axes": "x",
                                                    "top_gating": [1, None], "posture_statement": 7}},
    "g_eb_unavailable": lambda s: {"executive_brief": {"_unavailable": True}},
    "g_fp_str": lambda s: {"assessment_integrity": {"failed_phases": "boom"}},
    "g_fp_mixed": lambda s: {"assessment_integrity": {"failed_phases": [None, {"a": 1}, "Totally new phase"]}},
    "g_cm_nan": lambda s: {"coverage_matrix": {"summary": {"n_rows": float("nan"), "by_state": {"weird": 1}}}},
    "g_ue_bad": lambda s: {"unknown_evidence": {"summary": {"state": "made_up"}, "sources": [5]}},
    "g_poison": lambda s: _poison(s),
}
CORE = ("a", "b", "c", "c_legacy", "d", "d_real")
ALL_CASES = CORE + tuple(GARBAGE)


def _run_real_engine(tmp_path, mp):
    """The real pipeline with two phases forced to fail (pattern of
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

    mp.setattr(analyze, "compute_failure_impact", _boom)   # main() imports it at call time (:4511)
    mp.setattr(cp, "_punchlist", _boom)
    cp.main()
    return json.loads(pathlib.Path(str(out)[:-len(".xlsx")] + ".snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snaps(tmp_path_factory):
    sample = _sample()
    c = _all_insufficient(sample)
    out = {"a": sample, "b": _minimal(), "c": c, "c_legacy": _legacy(c), "d": _failed_phases(sample)}
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
# T0 -- the schema is sound and its enums ARE the module's (and the owners') vocabularies
# --------------------------------------------------------------------------------------------------
def test_t0_schema_is_sound_and_enums_are_the_module_vocabularies():
    schema = uip.ui_projection_schema()
    Draft202012Validator.check_schema(schema)
    d = schema["$defs"]
    assert schema["properties"]["schema"]["const"] == uip.SCHEMA == "ui_projection/1"
    assert schema["title"] == uip.SCHEMA
    assert d["state"]["enum"] == list(uip.STATES)
    assert uip.STATES[:4] == ssot.ABSTENTION_STATES
    assert set(uip.STATES[4:]) == set(uip.DOMAIN_STATE_OWNERS)
    assert d["abstentionState"]["enum"] == list(ssot.ABSTENTION_STATES)
    assert d["engineState"]["enum"] == list(uip.ENGINE_STATES)
    assert set(uip.ENGINE_STATES) == set(uip.STATES) | set(uip.FLEET_HEALTH_STATES)
    assert d["ref"]["properties"]["role"]["enum"] == list(uip.REF_ROLES)
    axis_value = d["axisFact"]["allOf"][1]["properties"]["value"]["anyOf"][1]
    assert axis_value["properties"]["severity"]["enum"] == list(uip.SEVERITIES)
    assert d["bandFact"]["allOf"][1]["properties"]["value"]["enum"] == list(uip.HEALTH_BANDS) + [None]
    assert d["ueStateFact"]["allOf"][1]["properties"]["value"]["enum"] == \
        list(uip.UNKNOWN_EVIDENCE_STATES) + [None]
    by_state = d["byStateFact"]["allOf"][1]["properties"]["value"]["anyOf"][1]
    assert by_state["propertyNames"]["enum"] == list(uip.COVERAGE_STATES)
    source = d["sourceFact"]["allOf"][1]["properties"]["value"]["anyOf"][1]
    assert source["properties"]["state"]["enum"] == list(uip.UE_SOURCE_STATES)
    ov = d["overview"]["properties"]
    assert ov["facts"]["required"] == list(ssot.CANONICAL_FACTS)
    assert set(ov["facts"]["properties"]) == set(ssot.CANONICAL_FACTS)
    assert ov["fleet_health"]["properties"]["engine_state"]["enum"] == list(uip.FLEET_HEALTH_STATES)
    assert ov["fleet_health"]["properties"]["not_assessed_reason"]["enum"] == \
        list(uip.NOT_ASSESSED_REASONS) + [None]
    band_row = ov["lifecycle"]["properties"]["bands"]["items"]["properties"]
    assert band_row["band"]["enum"] == list(uip.LIFECYCLE_BAND_FACTS.values())
    assert band_row["fact_name"]["enum"] == list(uip.LIFECYCLE_BAND_FACTS)
    tr = d["trust"]["properties"]
    rec_item = tr["failures"]["properties"]["record"]["allOf"][1]["properties"]["items"]["items"]
    assert rec_item["properties"]["classification"]["enum"] == list(uip.PHASE_CLASSIFICATIONS)
    census_row = tr["census"]["properties"]["rows"]["items"]["properties"]
    assert census_row["kind"]["enum"] == list(uip.CENSUS_KINDS)
    lim_ids = tr["limitations"]["items"]["properties"]["id"]["enum"]
    assert lim_ids == [lim["id"] for lim in uip.LIMITATIONS]
    assert len(set(lim_ids)) == len(lim_ids)


def test_t0_schema_accessor_returns_a_fresh_copy():
    first = uip.ui_projection_schema()
    _mutate_everything(first)
    again = uip.ui_projection_schema()
    Draft202012Validator.check_schema(again)
    assert again["$defs"]["state"]["enum"] == list(uip.STATES)


def test_json_pointer_is_rfc6901():
    assert uip.json_pointer() == ""
    assert uip.json_pointer("a/b", "c~d", 0, "~/") == "/a~1b/c~0d/0/~0~1"
    doc = {"a/b": {"c~d": [{"~/": 7}]}}
    assert _resolve(doc, uip.json_pointer("a/b", "c~d", 0, "~/")) == 7


# --------------------------------------------------------------------------------------------------
# T1 / T2 -- schema-valid everywhere; every ref / pointer resolves
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
def test_t2_every_ref_and_pointer_resolves(name, snaps, payloads):
    snap, payload = snaps[name], payloads[name]
    n_refs = 0
    for where, fact in _walk_facts(payload):
        for ref in fact["refs"]:
            n_refs += 1
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (where, ref)
        if fact["state"] == PUB and fact["subject"] is not None:
            assert _resolve(snap, fact["subject"]) is not _MISSING, (where, fact["subject"])
        for item in fact.get("items", ()):
            if "pointer" in item:
                assert _resolve(snap, item["pointer"]) is not _MISSING, (where, item)
    for row in payload["trust"]["census"]["rows"]:
        assert _resolve(snap, row["pointer"]) is not _MISSING, row
    for row in payload["trust"]["failures"]["direct_sections"]:
        for ref in row["refs"]:
            assert _resolve(snap, ref["pointer"]) is not _MISSING, (row, ref)
    for lim in payload["trust"]["limitations"]:
        assert lim["applies_to"], lim["id"]
        for pointer in lim["applies_to"]:
            assert _resolve(payload, pointer) is not _MISSING, (lim["id"], pointer)
    if name == "a":
        assert n_refs > 50           # non-vacuous on the populated fixture


# --------------------------------------------------------------------------------------------------
# T3 / T4 -- values come from the owner; the owner's abstention always wins
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "b", "c", "d"))
def test_t3_canonical_values_come_from_the_owner(name, snaps, payloads):
    snap, facts = snaps[name], payloads[name]["overview"]["facts"]
    canon = ssot.canonical_facts(snap)
    assert list(facts) == list(ssot.CANONICAL_FACTS)
    for fname, (path, concept) in ssot.CANONICAL_FACTS.items():
        entry = facts[fname]
        assert (entry["path"], entry["concept"]) == (path, concept)
        fact = entry["fact"]
        if fact["state"] == PUB:
            assert fact["value"] == canon[fname], fname
        if canon[fname] is None:
            assert fact["state"] != PUB, fname


@pytest.mark.parametrize("name", ALL_CASES)
def test_t4a_owner_abstention_wins(name, snaps, payloads):
    snap, payload = _as_dict(snaps[name]), payloads[name]
    facts = payload["overview"]["facts"]
    for fname, (path, _concept) in ssot.CANONICAL_FACTS.items():
        if ssot.abstention_reason(snap, path) == AU:
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
    if name in ("d", "d_real"):
        assert checked >= 3          # the punch-list axis + both brief rollup lists


@pytest.mark.parametrize("name", ("c", "c_legacy"))
def test_t4c_an_unscored_fleet_makes_no_health_claim(name, snaps, payloads):
    snap, payload = snaps[name], payloads[name]
    ov = payload["overview"]
    for fname in POSTURE_NAMES:
        fact = ov["facts"][fname]["fact"]
        assert fact["state"] == NA, (fname, fact)
        assert fact["value"] is None
    fh = ov["fleet_health"]
    assert fh["engine_state"] == ssot.fleet_avg_health(snap)["state"] == NA
    if name == "c":
        assert fh["not_assessed_reason"] == "all_insufficient_data"
    assert fh["n_scored"]["state"] == PUB and fh["n_scored"]["value"] == 0      # a MEASURED zero
    assert fh["n_rows"]["state"] == PUB and fh["n_rows"]["value"] == len(snap["health_scores"])
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
    assert ov["posture_statement"]["state"] == PUB
    direct, unattributed = ssot.failed_sections(snap)
    assert [row["section"] for row in tr["failures"]["direct_sections"]] == sorted(direct)
    assert {"failure_impact", "punchlist"} <= set(direct)
    assert tr["failures"]["unattributed"] is unattributed
    census = {row["key"]: row["state"] for row in tr["census"]["rows"]}
    assert census["failure_impact"] == census["punchlist"] == AU
    live = ssot.compute_schema_census(snap)["summary"]
    assert tr["census"]["summary"]["n_analysis_unavailable"] == live.get("n_analysis_unavailable", 0) >= 2
    assert "one_hop_failure_attribution" in _limitation_ids(payload)
    owner = ssot.abstention_reason(snap, "device_dossiers")
    expected = owner if owner in (AU, NC) else PUB
    assert _axis_item(payload, "Asset risk register")["fact"]["state"] == expected
    if name == "d":
        tg = ov["top_gating"]["items"]
        assert len(tg) == len(snap["executive_brief"]["top_gating"]) > 0
        assert all(item["fact"]["state"] == PUB for item in tg)
        assert [row["section"] for row in tr["failures"]["direct_sections"]] == ["failure_impact", "punchlist"]
        assert unattributed is False
        rec = [(it["label"], it["classification"], it["sections"]) for it in tr["failures"]["record"]["items"]]
        assert rec == [("Failure Impact", "sections", ["failure_impact"]),
                       ("Migration Punch-List", "sections", ["punchlist"])]
        assert tr["census"]["summary"]["n_analysis_unavailable"] == 2
        states_a = {k: v["fact"]["state"] for k, v in payloads["a"]["overview"]["facts"].items()}
        assert {k: v["fact"]["state"] for k, v in ov["facts"].items()} == states_a


# --------------------------------------------------------------------------------------------------
# T5 -- a measured zero is published as 0
# --------------------------------------------------------------------------------------------------
def test_t5_measured_zeros_publish(snaps, payloads):
    a, pa = snaps["a"], payloads["a"]
    zeros = [name for name, (path, _c) in ssot.CANONICAL_FACTS.items()
             if ssot.abstention_reason(a, path) == CBE and ssot.canonical_facts(a)[name] == 0]
    assert zeros, "the sample fleet should carry at least one measured-zero canonical fact"
    assert {"n_near", "n_active"} <= set(zeros)
    for name in zeros:
        fact = pa["overview"]["facts"][name]["fact"]
        assert (fact["state"], fact["value"], fact.get("engine_state")) == (PUB, 0, CBE), name
    ue = pa["trust"]["unknown_evidence"]
    assert a["unknown_evidence"]["summary"]["n_events"] == 0
    assert (ue["n_events"]["state"], ue["n_events"]["value"]) == (PUB, 0)
    assert pa["trust"]["census"]["summary"]["n_not_collected"] == 0
    assert pa["trust"]["census"]["summary"]["n_analysis_unavailable"] == 0
    n_scored = payloads["c"]["overview"]["fleet_health"]["n_scored"]
    assert (n_scored["state"], n_scored["value"]) == (PUB, 0)


def test_t5_synthetic_zero_unknown_is_proof_of_coverage():
    snap = {"lifecycle_risk": {"summary": {"n_devices": 2, "n_past_ldos": 0, "n_near": 0, "n_past_eos": 0,
                                           "n_active": 2, "n_unknown": 0}}}
    facts = uip.project_overview(snap)["facts"]
    for name in ("n_past_ldos", "n_near", "n_past_eos", "n_unknown"):
        fact = facts[name]["fact"]
        assert (fact["state"], fact["value"]) == (PUB, 0), name
    assert (facts["n_active"]["fact"]["state"], facts["n_active"]["fact"]["value"]) == (PUB, 2)
    assert "engine_state" not in facts["n_active"]["fact"]


# --------------------------------------------------------------------------------------------------
# T6 / T7 -- the sample fleet and the minimal snapshot
# --------------------------------------------------------------------------------------------------
def test_t6_sample_shape_matches_the_owners(snaps, payloads):
    a, p = snaps["a"], payloads["a"]
    ov, tr, eng = p["overview"], p["trust"], p["engine"]
    canon = ssot.canonical_facts(a)
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
    tg = ov["top_gating"]["items"]
    assert len(tg) == len(eb["top_gating"]) > 0
    for it, text in zip(tg, eb["top_gating"]):
        assert it["fact"]["state"] == PUB and it["fact"]["value"] == text
        assert it["axis_index"] is not None
        assert items[it["axis_index"]]["fact"]["value"]["headline"] == text
        assert items[it["axis_index"]]["fact"]["value"]["severity"] in ("Critical", "High")
    assert ov["posture_statement"]["state"] == PUB
    assert ov["posture_statement"]["value"] == eb["posture_statement"]
    fh = ssot.fleet_avg_health(a)
    assert ov["fleet_health"]["engine_state"] == fh["state"] == "measured"
    assert ov["fleet_health"]["n_scored"]["value"] == fh["n_scored"]
    assert ov["fleet_health"]["n_rows"]["value"] == fh["n_rows"]
    assert ov["fleet_health"]["not_assessed_reason"] is None
    assert ov["facts"]["avg_health"]["fact"]["engine_state"] == "measured"
    lc = a["lifecycle_risk"]["summary"]
    assert [(b["band"], b["fact_name"]) for b in ov["lifecycle"]["bands"]] == \
        [(band, name) for name, band in ssot._LIFECYCLE_BANDS.items()]
    assert ov["lifecycle"]["of"]["value"] == lc["n_devices"]
    assert ov["lifecycle"]["asof"]["value"] == lc["asof"]
    assert tr["census"]["embedded"] == {"state": PUB, "matches_live": True}
    live = ssot.compute_schema_census(a)
    assert [r["key"] for r in tr["census"]["rows"]] == sorted(r["key"] for r in live["sections"])
    cm = a["coverage_matrix"]["summary"]
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"):
        assert tr["coverage_matrix"][key]["state"] == PUB, key
        assert tr["coverage_matrix"][key]["value"] == cm[key], key
    ue = tr["unknown_evidence"]
    assert ue["state"]["value"] == a["unknown_evidence"]["summary"]["state"] == "observed_no_unknowns"
    assert [it["fact"]["value"]["section"] for it in ue["sources"]["items"]] == \
        [row["section"] for row in a["unknown_evidence"]["sources"]]
    rec = tr["failures"]["record"]
    assert rec["state"] == NC and rec["items"] == []
    assert "only when" in rec["reason"]
    s = tr["ssot"]
    assert s["verified"] is True and s["violations"] == [] and s["stamp_matches_live"] is True
    assert s["engine_stamp"]["value"] == eb["ssot"]
    assert eng["snapshot_schema"]["value"] == a["schema"] and eng["snapshot_schema_supported"] is True
    assert eng["code_schema_version"] == cisco_toolkit.__version__
    for key in ("script_version", "generated_at", "collected_at"):
        assert eng[key]["state"] == PUB and eng[key]["value"] == a[key]


def test_t7_minimal_snapshot_is_blind_spots_not_health(snaps, payloads):
    p = payloads["b"]
    ov, tr = p["overview"], p["trust"]
    for name, entry in ov["facts"].items():
        assert entry["fact"]["state"] == NC and entry["fact"]["refs"] == [], name
    for key in ("axes", "top_gating", "posture_statement"):
        assert ov[key]["state"] == NC, key
    assert [(r["key"], r["state"]) for r in tr["census"]["rows"]] == [("devices", PUB), ("schema", PUB)]
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"):
        assert tr["coverage_matrix"][key]["state"] == NC, key
    for key in ("state", "n_events", "n_unresolved", "source_coverage_complete", "claim_scope", "note",
                "sources"):
        assert tr["unknown_evidence"][key]["state"] == NC, key
    assert tr["ssot"]["verified"] is False and tr["ssot"]["n_checked"] == 0
    assert tr["ssot"]["engine_stamp"]["state"] == NC and tr["ssot"]["stamp_matches_live"] is None
    assert tr["census"]["embedded"] == {"state": NC, "matches_live": None}
    assert "census_present_keys_only" in _limitation_ids(p)
    assert p["engine"]["snapshot_schema"]["state"] == PUB and p["engine"]["snapshot_schema_supported"] is True
    assert p["engine"]["script_version"]["state"] == NC


# --------------------------------------------------------------------------------------------------
# T8 - T11 -- deterministic, no mutation / aliasing, total on garbage, pure
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ("a", "b", "d"))
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


@pytest.mark.parametrize("name", tuple(GARBAGE))
def test_t10_total_on_garbage(name, snaps, payloads, validator):
    snap, p = snaps[name], payloads[name]
    validator.validate(p)
    json.dumps(p, allow_nan=False)
    facts = list(_walk_facts(p))
    assert facts
    ov, tr = p["overview"], p["trust"]
    if name in ("g_none", "g_list", "g_str", "g_zero", "g_empty", "g_eb_int"):
        for where, fact in facts:
            assert fact["state"] == NC, (where, fact)
    if name == "g_eb_int":
        owner = {r["key"]: r["state"] for r in ssot.compute_schema_census(snap)["sections"]}
        assert {r["key"]: r["state"] for r in tr["census"]["rows"]} == owner
        assert owner["executive_brief"] == PUB
    if name == "g_nan_posture":
        assert ov["facts"]["avg_health"]["fact"]["state"] == NA
    if name == "g_lc_inf":
        assert ov["facts"]["n_near"]["fact"]["state"] == UV
        assert ov["facts"]["n_unknown"]["fact"]["state"] == UV
    if name == "g_eb_badtypes":
        assert ov["facts"]["n_devices"]["fact"]["state"] == UV
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
        assert tr["failures"]["unattributed"] is True
    if name == "g_cm_nan":
        assert tr["coverage_matrix"]["n_rows"]["state"] == UV
        assert tr["coverage_matrix"]["by_state"]["state"] == UV
    if name == "g_ue_bad":
        assert tr["unknown_evidence"]["state"]["state"] == UV
        assert [it["fact"]["state"] for it in tr["unknown_evidence"]["sources"]["items"]] == [UV]
    if name == "g_poison":
        assert "NaN" not in json.dumps(p, allow_nan=False)


def test_t11_pure_no_file_or_socket_io(snaps, payloads, monkeypatch):
    def _no_io(*_a, **_kw):
        raise AssertionError("ui_projection performed I/O")

    monkeypatch.setattr(builtins, "open", _no_io)
    monkeypatch.setattr(socket, "socket", _no_io)
    assert uip.project(snaps["a"]) == payloads["a"]


def test_module_imports_only_stdlib_and_the_ssot_owner():
    tree = ast.parse(MODULE_SRC.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            imported.update(f"{base}:{alias.name}" for alias in node.names)
    allowed = {"copy", "math", "__future__:annotations", "cisco_toolkit:ssot", "cisco_toolkit:__version__"}
    extra = {name for name in imported if name not in allowed and not name.startswith("typing:")}
    assert not extra, extra


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
    assert uip.LIFECYCLE_BAND_FACTS == ssot._LIFECYCLE_BANDS
    assert set(uip.LIFECYCLE_BAND_FACTS.values()) <= set(analyze._LIFECYCLE_BAND_RANK)
    assert set(uip.LIFECYCLE_BAND_FACTS) <= set(ssot.CANONICAL_FACTS)
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
    assert uip.DOMAIN_STATE_OWNERS == {"not_assessed": "ssot.fleet_avg_health",
                                       "unverified": "ssot.fleet_avg_health"}
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
    assert {"Failure Impact", "Migration Punch-List"} <= set(labels)
    assert not snap["executive_brief"].get("_unavailable")
    assert _axis_item(p, "Migration punch-list")["fact"]["state"] == AU
    record = [it["label"] for it in p["trust"]["failures"]["record"]["items"]]
    assert record == [str(lab) for lab in labels]
