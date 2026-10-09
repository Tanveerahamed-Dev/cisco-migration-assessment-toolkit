"""G08 -- ``trust.inputs``: the analysis-input gap summary.

Per analysis input, the inventory devices it could not assess, out of the inventory. The inputs are the engine's
closed per-device registry (``analyze.DOSSIER_AXIS_INPUTS``); a device's custody of each input is its risk-register
exposure. Every expectation below is folded independently from the snapshot's own sections (never through the
projection's helpers), and the real owners produce the fixtures where a producer contract is the claim.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import pathlib
import textwrap

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as uip

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
CAPTURES = ("show interface status", "show interface switchport", "show version", "show cdp neighbors detail")
INVENTORY_POINTER = "/collection_completeness/summary/inventory"


# --------------------------------------------------------------------------------------------------
# independent helpers (deliberately NOT the module's own)
# --------------------------------------------------------------------------------------------------
def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(name):
    return name.strip().lower()


def _escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def _label(section):
    """The failure label the SSOT owner attributes to `section` (looked up, never hand-written)."""
    labels = [label for label, sections in ssot.PHASE_SECTIONS.items() if section in sections]
    assert len(labels) == 1, (section, labels)
    return labels[0]


def _universe(snap):
    """The devices map plus every collection_completeness row the devices map does not name (first spelling)."""
    devices = snap.get("devices") if isinstance(snap.get("devices"), dict) else {}
    cc = snap.get("collection_completeness") if isinstance(snap.get("collection_completeness"), dict) else {}
    rows = cc.get("devices") if isinstance(cc.get("devices"), list) else []
    first = {}
    for i, row in enumerate(rows):
        if isinstance(row, dict) and isinstance(row.get("host"), str):
            first.setdefault(_norm(row["host"]), i)
    named = {_norm(host) for host in devices}
    extra = {rows[i]["host"] for key, i in first.items() if key not in named}
    return sorted(set(devices) | extra), rows, first


def _expected(snap):
    """Axis -> [(host, custody, label, pointer)]: a blind spot under every axis, else the one exposure marked 'na'."""
    universe, cc_rows, first = _universe(snap)
    dossiers = snap["device_dossiers"]["per_device"]
    out = {}
    for axis in analyze.DOSSIER_AXIS_INPUTS:
        listed = []
        for host in universe:
            i = first.get(_norm(host))
            if i is not None and str(cc_rows[i].get("status", "")).strip().lower() == "not collected":
                listed.append((host, NC, None, f"/collection_completeness/devices/{i}"))
                continue
            (k,) = [k for k, row in enumerate(dossiers) if row["host"] == host]
            (j,) = [j for j, exposure in enumerate(dossiers[k]["exposures"]) if exposure["axis"] == axis]
            exposure = dossiers[k]["exposures"][j]
            if exposure["state"] == "na":
                listed.append((host, exposure["input_state"], exposure["label"],
                               f"/device_dossiers/per_device/{k}/exposures/{j}"))
        out[axis] = listed
    return universe, out


def _items(row):
    return [(it["host"], it["custody"], it["label"], it["pointer"]) for it in row["hosts"]["items"]]


def _rows(snap):
    rows = uip.project_trust(snap)["inputs"]
    assert [row["input"] for row in rows] == list(analyze.DOSSIER_AXIS_INPUTS)
    return {row["input"]: row for row in rows}


def _real_fleet(tmp_path):
    """A small fleet through the real owners: collection completeness over captured files, lifecycle over the
    device map, and the risk register over sparse configuration inputs (a hygiene row for one device only)."""
    capture = tmp_path / "captured.txt"
    capture.write_text("synthetic captured output\n", encoding="utf-8")
    full = {cmd: str(capture) for cmd in CAPTURES}
    completeness = analyze.compute_collection_completeness(
        ["edge-a", "edge-b", "edge-c", "edge-d"],
        {"edge-a": full, "edge-b": full, "edge-c": {"show version": str(capture)}})
    hosts = ("edge-a", "edge-b", "edge-c")              # edge-d was never reached: it has no device record
    lifecycle = analyze.compute_lifecycle_risk({h: {"model": "", "sw_version": ""} for h in hosts},
                                               asof="2026-10-01")
    health = [{"switch": "edge-a", "band": "Good", "score": 90, "role": "access"},
              {"switch": "edge-b", "band": "Critical", "score": 20, "role": "access"},
              {"switch": "edge-c", "band": "Insufficient Data", "score": None, "role": "access"}]
    software = {"per_device": [
        {"host": "edge-a", "config_assessable": True, "train_band": "Current-era", "sw_version": "17.9.4"},
        {"host": "edge-b", "config_assessable": False, "train_band": "Unknown", "sw_version": "(not collected)"}]}
    security = {"edge-a": {"findings": [{"id": "S1", "status": "pass", "severity": "high"}]}}
    hygiene = {"edge-a": {"undefined": []}}             # sparse: no row for edge-b or edge-c
    dossiers = analyze.compute_device_dossiers(health_scores=health, lifecycle_risk=lifecycle,
                                               software_risk=software, security=security, config_hygiene=hygiene)
    return {"schema": "collect_parse_snapshot/1",
            "devices": {h: {"hostname": h, "model": "", "sw_version": ""} for h in hosts},
            "collection_completeness": completeness, "lifecycle_risk": lifecycle, "health_scores": health,
            "software_risk": software, "security": security, "config_hygiene": hygiene, "device_dossiers": dossiers}


def _with_blind(sample):
    """The sample with one devices-map host and one never-reached host listed as not collected."""
    snap = copy.deepcopy(sample)
    host = sorted(snap["devices"])[0]
    missing = list(uip.ESSENTIAL_LABELS)
    cc = snap["collection_completeness"]
    cc["devices"] = [{"host": f" {host.upper()} ", "status": "Not Collected", "data_quality": 0, "missing": missing},
                     {"host": "ghost-unreached", "status": "not collected", "data_quality": 0, "missing": missing}]
    cc["summary"] = {"inventory": len(snap["devices"]) + 1, "complete": len(snap["devices"]) - 1, "partial": 0,
                     "not_collected": 2}
    return snap, host


def _first_na(snap):
    for k, row in enumerate(snap["device_dossiers"]["per_device"]):
        for j, exposure in enumerate(row["exposures"]):
            if exposure["state"] == "na":
                return k, j, exposure["axis"]
    raise AssertionError("the fixture carries no unassessed axis")


@pytest.fixture(scope="module")
def sample():
    return _load(SAMPLE)


@pytest.fixture(scope="module")
def validator():
    return Draft202012Validator(uip.ui_projection_schema())


# --------------------------------------------------------------------------------------------------
# the registry is the engine owner, and the owner's producer contract holds
# --------------------------------------------------------------------------------------------------
def test_registry_is_the_engine_owner_in_its_order():
    assert dict(uip.TRUST_INPUTS) == {axis: tuple(s) for axis, s in analyze.DOSSIER_AXIS_INPUTS.items()}
    assert tuple(uip.TRUST_INPUTS) == tuple(analyze.DOSSIER_AXIS_INPUTS) == uip.DOSSIER_AXES
    assert uip.TRUST_INPUT_CUSTODY == tuple(s for s in uip.STATES if s not in (PUB, "not_assessed"))
    defs = uip.ui_projection_schema()["$defs"]
    assert defs["TrustInput"]["properties"]["input"]["enum"] == list(analyze.DOSSIER_AXIS_INPUTS)
    inputs = defs["Trust"]["properties"]["inputs"]
    assert inputs["minItems"] == inputs["maxItems"] == len(analyze.DOSSIER_AXIS_INPUTS)
    assert defs["TrustInputHost"]["properties"]["custody"]["enum"] == list(uip.TRUST_INPUT_CUSTODY)
    # The registry is read from the owner object, never restated: no axis name is a literal in its definition.
    tree = ast.parse((ROOT / "cisco_toolkit" / "ui_projection.py").read_text(encoding="utf-8"))
    (node,) = [n for n in tree.body if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "TRUST_INPUTS"]
    assert "DOSSIER_AXIS_INPUTS" in ast.unparse(node.value)
    assert not [c for c in ast.walk(node.value) if isinstance(c, ast.Constant) and c.value in analyze.DOSSIER_AXIS_INPUTS]


def test_custody_is_one_unranked_vocabulary_of_the_g43_catalogue_read_from_its_owner_tuple():
    """Every custody token names why an input did not assess a device, an absence: the catalogue names the vocabulary
    once, unranked (no class, so never 'pass'), with its tokens taken from the owner tuple, never restated."""
    vocab = uip._vocab()
    assert vocab["unranked"]["trust_input_custody"]["tokens"] == list(uip.TRUST_INPUT_CUSTODY)
    assert "trust_input_custody" not in vocab["ranked"]
    assert set(uip.TRUST_INPUT_CUSTODY) < set(uip.WITHHELD_STATES)
    tree = ast.parse((ROOT / "cisco_toolkit" / "ui_projection.py").read_text(encoding="utf-8"))
    (node,) = [n for n in tree.body
               if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "_VOCAB_UNRANKED"]
    (entry,) = [e for e in node.value.elts
                if isinstance(e, ast.Tuple) and ast.literal_eval(e.elts[0]) == "trust_input_custody"]
    assert ast.unparse(entry.elts[1]) == "TRUST_INPUT_CUSTODY"


def test_the_producer_writes_one_exposure_per_registered_axis():
    """compute_device_dossiers names every registered axis, and no other, in its ax()/config_gap() calls."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(analyze.compute_device_dossiers)))
    named = {call.args[0].value for call in ast.walk(tree)
             if isinstance(call, ast.Call) and getattr(call.func, "id", "") in ("ax", "config_gap")
             and call.args and isinstance(call.args[0], ast.Constant)}
    assert named == set(analyze.DOSSIER_AXIS_INPUTS)


def test_stored_and_fresh_registers_mark_na_exactly_off_published_custody(sample, tmp_path):
    """The fold's premise, on real producer output: one exposure per axis in owner order; 'na' whenever the input
    was not published, and never over published custody (only the empty-is-clean axes read an empty screen as ok)."""
    for snap in (sample, _load(GOLDEN), _real_fleet(tmp_path)):
        rows = snap["device_dossiers"]["per_device"]
        assert rows
        for row in rows:
            assert [e["axis"] for e in row["exposures"]] == list(analyze.DOSSIER_AXIS_INPUTS)
            for exposure in row["exposures"]:
                if exposure["input_state"] not in (PUB, CBE):
                    assert exposure["state"] == "na", exposure
                if exposure["state"] == "na":
                    assert exposure["input_state"] != PUB, exposure
                if exposure["state"] == "ok" and exposure["input_state"] == CBE:
                    assert exposure["axis"] in analyze.DOSSIER_EMPTY_IS_CLEAN, exposure


def test_the_register_writes_a_row_for_every_device_through_the_lifecycle_owner():
    """Why a missing register row is a contradiction, not a gap: the lifecycle owner writes one row per device of
    the device-physical map, and the register's host universe includes every one of them."""
    hosts = ("sw-b", "sw-a", "sw-c")
    lifecycle = analyze.compute_lifecycle_risk({h: {"model": "", "sw_version": ""} for h in hosts},
                                               asof="2026-10-01")
    assert [row["host"] for row in lifecycle["per_device"]] == sorted(hosts)
    dossiers = analyze.compute_device_dossiers(lifecycle_risk=lifecycle)
    assert sorted(row["host"] for row in dossiers["per_device"]) == sorted(hosts)     # the register ranks its rows
    for row in dossiers["per_device"]:
        assert [e["axis"] for e in row["exposures"]] == list(analyze.DOSSIER_AXIS_INPUTS)
    # The pipeline builds the devices map and the lifecycle input from the same device-physical list.
    main = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8")
    assert ('_dev_lifecycle = {dp.hostname: {"model": dp.model, "sw_version": dp.sw_version} '
            'for dp in all_device_physical}') in main
    assert 'lifecycle_risk = _run_phase("Lifecycle risk", compute_lifecycle_risk, _dev_lifecycle,' in main
    assert "lifecycle_risk=ctx.lifecycle_risk" in main
    html = (ROOT / "cisco_toolkit" / "html.py").read_text(encoding="utf-8")
    assert '"devices": {dp.hostname: dataclasses.asdict(dp) for dp in all_device_physical},' in html


# --------------------------------------------------------------------------------------------------
# n, of and hosts equal an independent fold
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("source", ["sample", "golden", "real_fleet", "blind"])
def test_counts_and_hosts_equal_an_independent_fold(source, sample, tmp_path):
    snap = {"sample": lambda: copy.deepcopy(sample), "golden": lambda: _load(GOLDEN),
            "real_fleet": lambda: _real_fleet(tmp_path), "blind": lambda: _with_blind(sample)[0]}[source]()
    universe, expected = _expected(snap)
    total = uip.project_inventory(snap)["devices"]["total"]
    assert (total["state"], total["value"]) == (PUB, len(universe))
    assert snap["collection_completeness"]["summary"]["inventory"] == len(universe)
    rows = _rows(snap)
    for axis, listed in expected.items():
        row = rows[axis]
        assert row["sections"] == list(analyze.DOSSIER_AXIS_INPUTS[axis])
        assert row["of"] == total, axis                                  # one owner for the denominator
        assert _items(row) == listed, axis
        assert row["hosts"]["state"] == (PUB if listed else CBE), axis
        assert (row["n"]["state"], row["n"]["value"]) == (PUB, len(listed)), axis
        assert row["n"]["value"] <= row["of"]["value"]
        assert "trust_inputs_scope" in row["hosts"]["caveats"] and "trust_inputs_scope" in row["n"]["caveats"]
        assert {"pointer": INVENTORY_POINTER, "role": "denominator"} in row["n"]["refs"]
        assert {"pointer": "/device_dossiers/per_device", "role": "basis"} in row["hosts"]["refs"]
    assert any(expected.values()), "a non-vacuous fixture lists at least one device"


def test_the_real_fleet_keeps_each_custody_the_engine_wrote(tmp_path):
    rows = _rows(_real_fleet(tmp_path))
    custody = {axis: {it["host"]: it["custody"] for it in row["hosts"]["items"]} for axis, row in rows.items()}
    for axis in analyze.DOSSIER_AXIS_INPUTS:
        assert custody[axis]["edge-d"] == NC, axis                     # never reached: blind under every input
    assert custody["Health"] == {"edge-c": NC, "edge-d": NC}          # Insufficient Data is not a measurement
    assert custody["Config hygiene"]["edge-b"] == NC                   # no captured running-config
    assert custody["Config hygiene"]["edge-c"] == AU                   # no capture record at all
    assert "edge-a" not in custody["Config hygiene"]                   # screened: the sparse row says clean
    assert set(custody["Hardware EoL"]) == {"edge-a", "edge-b", "edge-c", "edge-d"}
    assert {custody["Hardware EoL"][h] for h in ("edge-a", "edge-b", "edge-c")} == {CBE}   # no authoritative band


def test_blind_devices_are_listed_under_every_input_with_their_witness(sample):
    snap, host = _with_blind(sample)
    rows = _rows(snap)
    for axis, row in rows.items():
        assert (host, NC, None, "/collection_completeness/devices/0") in _items(row), axis
        assert ("ghost-unreached", NC, None, "/collection_completeness/devices/1") in _items(row), axis
        assert row["hosts"]["state"] == PUB and row["n"]["value"] == len(row["hosts"]["items"])
    # The blind host's own register row is not consulted: its published exposures do not make it assessed.
    k = next(k for k, r in enumerate(snap["device_dossiers"]["per_device"]) if r["host"] == host)
    published = [e["axis"] for e in snap["device_dossiers"]["per_device"][k]["exposures"] if e["state"] != "na"]
    assert published
    for axis in published:
        assert [it["pointer"] for it in rows[axis]["hosts"]["items"] if it["host"] == host] == [
            "/collection_completeness/devices/0"]


# --------------------------------------------------------------------------------------------------
# sparse and findings-only sections never decide a gap (or a clean result)
# --------------------------------------------------------------------------------------------------
def test_sparse_and_findings_only_sections_never_decide_a_gap(sample):
    baseline = uip.project_trust(sample)["inputs"]
    sparse = copy.deepcopy(sample)
    sparse["config_hygiene"] = {}          # rows only for devices whose hygiene screen found something
    sparse["security"] = {}                # rows only for devices with a captured running-config
    sparse["physical_health"] = []         # findings only
    sparse["protocol_health"] = []         # findings only
    sparse["cross_layer"] = []             # findings only, and no per-device input at all
    assert uip.project_trust(sparse)["inputs"] == baseline
    for sections in uip.TRUST_INPUTS.values():
        assert "cross_layer" not in sections and "l3_forwarding" not in sections


def test_a_missing_register_row_is_unverified_never_assessed(sample):
    snap = copy.deepcopy(sample)
    host = snap["device_dossiers"]["per_device"].pop(0)["host"]
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == UV and (row["n"]["state"], row["n"]["value"]) == (UV, None), axis
        assert (host, UV, None, "/devices/" + _escape(host)) in _items(row), axis
        assert "1 device(s)" in row["hosts"]["reason"] and row["n"]["reason"] == row["hosts"]["reason"]


def test_a_missing_register_row_under_a_failed_lifecycle_phase_is_unavailable(sample):
    snap = copy.deepcopy(sample)
    host = snap["device_dossiers"]["per_device"].pop(0)["host"]
    snap["assessment_integrity"] = {"failed_phases": [_label("lifecycle_risk")]}
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == AU and row["n"]["state"] == AU, axis
        assert record in row["hosts"]["refs"] and record in row["n"]["refs"], axis
        assert (host, AU, None, "/devices/" + _escape(host)) in _items(row), axis


# --------------------------------------------------------------------------------------------------
# failed and malformed inputs
# --------------------------------------------------------------------------------------------------
def test_a_failed_register_phase_withholds_every_input_with_its_failure_record(sample):
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failed_phases": [_label("device_dossiers")]}
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == AU and (row["n"]["state"], row["n"]["value"]) == (AU, None), axis
        assert record in row["hosts"]["refs"] and record in row["n"]["refs"], axis
        assert row["of"]["state"] == PUB and "one_hop_failure_attribution" in row["of"]["caveats"]


def test_a_failed_input_phase_withholds_only_its_inputs(sample):
    baseline = _rows(sample)
    snap = copy.deepcopy(sample)
    snap["assessment_integrity"] = {"failed_phases": [_label("lifecycle_risk")]}
    rows = _rows(snap)
    record = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    for axis, row in rows.items():
        if "lifecycle_risk" in analyze.DOSSIER_AXIS_INPUTS[axis]:
            assert row["hosts"]["state"] == AU and record in row["hosts"]["refs"], axis
        else:
            assert row["hosts"]["state"] == baseline[axis]["hosts"]["state"], axis
            assert _items(row) == _items(baseline[axis]), axis
            assert "one_hop_failure_attribution" in row["hosts"]["caveats"], axis


@pytest.mark.parametrize("damage", ["not_a_list", "duplicate_row", "exposures_not_list", "unreadable_axis"])
def test_an_unreadable_register_withholds_every_input(sample, damage):
    snap = copy.deepcopy(sample)
    per_device = snap["device_dossiers"]["per_device"]
    if damage == "not_a_list":
        snap["device_dossiers"]["per_device"] = {"rows": per_device}
    elif damage == "duplicate_row":
        per_device.append(copy.deepcopy(per_device[0]))
    elif damage == "exposures_not_list":
        per_device[0]["exposures"] = "unreadable"
    else:
        per_device[0]["exposures"][0]["axis"] = 7
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == UV and row["n"]["state"] == UV, (damage, axis)
        if damage != "not_a_list":
            assert per_device[0]["host"] in [it["host"] for it in row["hosts"]["items"] if it["custody"] == UV]


@pytest.mark.parametrize("damage", ["bad_custody", "na_over_published", "missing_last_axis"])
def test_one_unreadable_exposure_withholds_only_its_input(sample, damage):
    baseline = _rows(sample)
    snap = copy.deepcopy(sample)
    per_device = snap["device_dossiers"]["per_device"]
    if damage == "missing_last_axis":
        axis = per_device[0]["exposures"].pop()["axis"]
        host = per_device[0]["host"]
    else:
        k, j, axis = _first_na(snap)
        host = per_device[k]["host"]
        per_device[k]["exposures"][j]["input_state"] = "made_up" if damage == "bad_custody" else PUB
    rows = _rows(snap)
    for name, row in rows.items():
        if name == axis:
            assert row["hosts"]["state"] == UV and row["n"]["state"] == UV, damage
            assert [it["custody"] for it in row["hosts"]["items"] if it["host"] == host] == [UV]
        else:
            assert row == baseline[name], (damage, name)


# --------------------------------------------------------------------------------------------------
# a register row the host join cannot read could be any device's row: never a published count
# --------------------------------------------------------------------------------------------------
def _witness(i):
    return {"pointer": f"/device_dossiers/per_device/{i}", "role": "witness"}


def _unjoinable_tail(row, tail):
    """`row` (a deep copy of a valid register row) made unjoinable by the exact host join."""
    if tail == "host_null":
        row["host"] = None
    elif tail == "host_missing":
        del row["host"]
    elif tail == "host_not_text":
        row["host"] = [row["host"]]
    else:
        row = row["exposures"]                     # a list where a row object belongs
    return row


def test_a_clean_register_publishes_every_count_its_zeros_included(sample):
    """The control: the complete, valid register publishes every count, and at least one input's count is a
    published zero over an empty list (the case an unjoinable row must withhold). No row is witnessed."""
    rows = _rows(sample)
    for axis, row in rows.items():
        assert row["n"]["state"] == PUB and row["hosts"]["state"] in (PUB, CBE), axis
        assert row["of"]["state"] == PUB, axis
        assert not [r for r in row["hosts"]["refs"] + row["n"]["refs"] if r["role"] == "witness"], axis
    assert [axis for axis, row in rows.items() if (row["n"]["value"], row["hosts"]["state"]) == (0, CBE)]


@pytest.mark.parametrize("tail", ["host_null", "host_missing", "host_not_text", "not_a_mapping"])
def test_an_unjoinable_register_row_withholds_every_count_with_its_witness(sample, tail):
    """A complete, valid register plus one row the exact host join cannot read. Every inventory device still has one
    readable row, so the fold alone would publish its counts (a zero where no device was missed); the extra row could
    be a conflicting observation of any of them. So n and hosts are unverified under every input, never a published
    count or zero, the row is witnessed, the readable rows' devices stay listed as data, and the inventory
    denominator, which never reads the register, is unchanged."""
    baseline = _rows(sample)
    assert [axis for axis, row in baseline.items() if (row["n"]["state"], row["n"]["value"]) == (PUB, 0)]
    snap = copy.deepcopy(sample)
    per_device = snap["device_dossiers"]["per_device"]
    per_device.append(_unjoinable_tail(copy.deepcopy(per_device[0]), tail))
    witness = _witness(len(per_device) - 1)
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == UV and (row["n"]["state"], row["n"]["value"]) == (UV, None), (tail, axis)
        assert witness in row["hosts"]["refs"] and witness in row["n"]["refs"], (tail, axis)
        assert "1 row(s) in device_dossiers.per_device cannot be joined by exact key" in row["hosts"]["reason"]
        assert row["n"]["reason"] == row["hosts"]["reason"], (tail, axis)
        assert _items(row) == _items(baseline[axis]), (tail, axis)
        assert row["of"] == baseline[axis]["of"] and row["of"]["state"] == PUB, (tail, axis)


def test_a_device_row_made_unjoinable_is_both_missing_and_witnessed(sample):
    """The device's own row lost its host: the device has no readable row (unverified, as a missing row is) and the
    unjoinable row that may be it is witnessed, both reasons kept."""
    snap = copy.deepcopy(sample)
    per_device = snap["device_dossiers"]["per_device"]
    host = per_device[0]["host"]
    per_device[0]["host"] = None
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == UV and (row["n"]["state"], row["n"]["value"]) == (UV, None), axis
        assert (host, UV, None, "/devices/" + _escape(host)) in _items(row), axis
        assert "1 device(s)" in row["hosts"]["reason"] and "cannot be joined by exact key" in row["hosts"]["reason"]
        assert _witness(0) in row["hosts"]["refs"] and _witness(0) in row["n"]["refs"], axis


def test_an_unverified_register_still_witnesses_each_unjoinable_row(sample):
    """A register whose rows are all deep-empty is one the section owner calls empty, so it is unverified; its rows
    can still be read, and each one the host join cannot read is witnessed (the strict selection's rule)."""
    snap = copy.deepcopy(sample)
    snap["device_dossiers"]["per_device"] = [{"host": None, "exposures": []}, {}]
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == UV and (row["n"]["state"], row["n"]["value"]) == (UV, None), axis
        assert "2 row(s) in device_dossiers.per_device cannot be joined" in row["hosts"]["reason"], axis
        assert _witness(0) in row["hosts"]["refs"] and _witness(1) in row["hosts"]["refs"], axis
        assert row["hosts"]["items"] == [], axis


def test_an_inventory_count_that_disagrees_with_the_rows_withholds_every_count(sample):
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["summary"]["inventory"] += 1
    for axis, row in _rows(snap).items():
        assert row["of"]["state"] == UV and row["n"]["state"] == UV and row["hosts"]["state"] == UV, axis
        assert "inventory denominator is withheld" in row["hosts"]["reason"], axis


def test_without_the_blind_spot_owner_every_list_may_be_incomplete(sample):
    snap = copy.deepcopy(sample)
    del snap["collection_completeness"]
    _universe_hosts, expected = _expected(snap)
    for axis, row in _rows(snap).items():
        assert row["of"]["state"] == NC and row["n"]["state"] == NC and row["hosts"]["state"] == NC, axis
        assert _items(row) == expected[axis], axis


def test_without_the_register_only_blind_spots_are_listed(sample):
    snap, host = _with_blind(sample)
    del snap["device_dossiers"]
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == NC and row["n"]["state"] == NC, axis
        assert "device_dossiers.per_device" in row["hosts"]["reason"], axis
        assert _items(row) == [(host, NC, None, "/collection_completeness/devices/0"),
                               ("ghost-unreached", NC, None, "/collection_completeness/devices/1")], axis


def test_an_empty_inventory_claims_nothing():
    snap = {"schema": "collect_parse_snapshot/1", "devices": {}, "device_dossiers": {"per_device": []},
            "collection_completeness": {"summary": {"inventory": 0, "complete": 0, "partial": 0, "not_collected": 0},
                                        "devices": []}}
    for axis, row in _rows(snap).items():
        assert row["hosts"]["state"] == NC and row["n"]["state"] == NC and row["hosts"]["items"] == [], axis


# --------------------------------------------------------------------------------------------------
# a section dependency: receipt row states never reach the summary (SSOT section state does)
# --------------------------------------------------------------------------------------------------
def test_receipt_row_states_never_reach_the_gap_summary(sample, monkeypatch):
    receipt_key = uip.PUNCHLIST_INPUTS[-3]       # the receipt section, named only in the declared registry
    assert receipt_key == "protocol_assessability" and receipt_key in uip.TRUST_INPUTS["Protocol"]
    snap = copy.deepcopy(sample)
    baseline = uip.project_trust(snap)["inputs"]
    rows = snap[receipt_key]["rows"]
    assert rows
    for state in (*analyze.PROTOCOL_ASSESSABILITY_STATES, "future_unknown_state"):
        for row in rows:
            row["state"] = state
        assert uip.project_trust(snap)["inputs"] == baseline, state
    original = ssot.abstention_reason
    for owner_state in ssot.ABSTENTION_STATES:
        calls = []

        def section_state(value, subject, *args, **kwargs):
            if subject == receipt_key:
                calls.append(subject)
                return owner_state
            return original(value, subject, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(ssot, "abstention_reason", section_state)
            got = uip.project_trust(snap)["inputs"]
        assert calls, "the summary must consult the SSOT section owner"
        for row, base in zip(got, baseline):
            if owner_state == AU and receipt_key in row["sections"]:
                assert row["hosts"]["state"] == AU and row["n"]["state"] == AU, row["input"]
            else:
                assert row == base, (owner_state, row["input"])


# --------------------------------------------------------------------------------------------------
# closed schema, purity
# --------------------------------------------------------------------------------------------------
def test_every_case_validates_against_the_closed_schema(sample, tmp_path, validator):
    blind, _host = _with_blind(sample)
    failed = copy.deepcopy(sample)
    failed["assessment_integrity"] = {"failed_phases": [_label("device_dossiers")]}
    missing = copy.deepcopy(sample)
    missing["device_dossiers"]["per_device"].pop(0)
    malformed = copy.deepcopy(sample)
    malformed["device_dossiers"]["per_device"][0]["exposures"] = "unreadable"
    no_register = copy.deepcopy(blind)
    del no_register["device_dossiers"]
    unjoinable = copy.deepcopy(sample)
    unjoinable["device_dossiers"]["per_device"] += [{"host": None}, {"exposures": []}, "row", {"host": 7}]
    cases = [sample, _load(GOLDEN), _real_fleet(tmp_path), blind, failed, missing, malformed, no_register, unjoinable,
             None, [], {}, {"device_dossiers": 5}, {"device_dossiers": {"per_device": [None, 3, {"host": 7}]}},
             {"devices": {"x": {}}, "device_dossiers": {"per_device": [{"host": "x", "exposures": [{"axis": {}}]}]}}]
    for snap in cases:
        payload = uip.project(snap)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
        assert len(payload["trust"]["inputs"]) == len(analyze.DOSSIER_AXIS_INPUTS)
        json.dumps(payload, allow_nan=False)


def test_the_summary_is_pure_and_never_aliases_its_input(sample):
    snap = copy.deepcopy(sample)
    before = json.dumps(snap, sort_keys=True)
    first = uip.project_trust(snap)["inputs"]
    assert json.dumps(snap, sort_keys=True) == before
    again = uip.project_trust(snap)["inputs"]
    assert first == again
    for row in first:
        for item in row["hosts"]["items"]:
            item["host"] = "MUTATED"
        row["n"]["refs"].clear()
    assert uip.project_trust(snap)["inputs"] == again
    assert json.dumps(snap, sort_keys=True) == before
