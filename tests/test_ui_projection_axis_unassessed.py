"""G05 (W40) -- per executive axis, how many devices it could not assess, out of how many.

``overview.axes.items[].unassessed = {n: CountFact, of: CountFact}`` is read from each axis's producer through
``cisco_toolkit.ui_projection.AXIS_UNASSESSED`` (and ``ssot.fleet_avg_health`` for Fleet health), never from the
brief's headline text. Coverage honesty is the point:

* an axis whose producer stores no such count is not_collected, never 0, and a failed input is analysis_unavailable;
* a count missing from a summary its producer wrote is not_collected, except a sparse counter's entry, which is a zero
  only when the producer's per-device rows confirm it;
* a count its own denominator or per-device rows contradict, or whose rows cannot be read, is unverified;
* a zero over a zero denominator is collected_but_empty, never a measurement.

The fixtures come from the engine's own code: the shipped engine-built sample fleet, the golden snapshot's producer
sections with the brief recomputed by the real ``analyze.compute_executive_brief``, and the real producers called on
small inputs (the patterns of tests/test_dossier_input_state.py, tests/test_device_dossiers.py and
tests/test_platform_health.py). Expectations are read from the snapshot and its owners, never from cached sample
literals. Single-field edits of the sample probe one rule each.
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib
import types

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as uip

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
NEVER_ZERO = "never shown as 0"
PLAIN_CONFIG = "\n".join([
    "hostname acc", "version 17.12", "service timestamps debug datetime msec",
    "service timestamps log datetime msec", "no ip http server", "no ip http secure-server",
    "ip ssh version 2", "no service pad", "service password-encryption", "logging buffered 8192",
    "interface GigabitEthernet1/0/1", " switchport mode access", " switchport access vlan 10",
    " spanning-tree portfast", "end", "",
])
#: The producer each registered section comes from (the fixture below calls exactly these).
PRODUCERS = {"lifecycle_risk": "compute_lifecycle_risk", "syslog_intelligence": "compute_syslog_intelligence",
             "qos_audit": "compute_qos_audit", "software_risk": "compute_software_risk",
             "platform_health": "compute_platform_health", "device_dossiers": "compute_device_dossiers"}

_MISSING = object()


# --------------------------------------------------------------------------------------------------
# independent helpers (deliberately not the module's own)
# --------------------------------------------------------------------------------------------------
def _resolve(doc, pointer):
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


def _dotted(doc, path):
    cur = doc
    for tok in path.split("."):
        if not isinstance(cur, dict) or tok not in cur:
            return _MISSING
        cur = cur[tok]
    return cur


def _ptr(path):
    return "/" + path.replace(".", "/")


def _sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _rebrief(snap):
    """The brief recomputed by the REAL producer over the snapshot's own sections."""
    params = inspect.signature(analyze.compute_executive_brief).parameters
    snap["executive_brief"] = analyze.compute_executive_brief(**{p: snap.get(p) for p in params})
    return snap


def _item(overview, label):
    hits = [it for it in overview["axes"]["items"] if it["axis"] == label]
    assert len(hits) == 1, (label, [it["axis"] for it in overview["axes"]["items"]])
    return hits[0]


def _unassessed(snap, label):
    return _item(uip.project_overview(snap), label)["unassessed"]


def _sv(fact):
    return fact["state"], fact["value"]


def _expected_count(snap, spec):
    """The producer's count, read independently: the stored entry, or a sparse counter's omitted zero."""
    _owner, n_path, _of_path, _rows_path, _field, _mark = spec
    stored = _dotted(snap, n_path)
    if stored is _MISSING and n_path.rsplit(".", 1)[0] in uip.AXIS_UNASSESSED_SPARSE:
        return 0
    return stored


def _marked(rows, field, mark):
    return sum(1 for row in rows if type(row[field]) is type(mark) and row[field] == mark)


def _producer_snapshot():
    """The six registered producers, run for real on two to three devices, each with at least one device the axis
    could not assess. Platform capacity holds a device whose capacity output was collected but not recognised, so
    its could-not-assess count (the Unknown band) exceeds its not-collected count."""
    log = "Syslog logging: enabled\nLog Buffer (8192 bytes):\n"
    cpu_ok = {"five_sec": 70, "interrupt": 0, "one_min": 65, "five_min": 59}
    health = [{"switch": "dark", "score": None, "band": "Insufficient Data", "role": "access", "criticality": 1.0,
               "deductions": []},
              {"switch": "lit", "score": 96, "band": "Excellent", "role": "access", "criticality": 1.0,
               "deductions": []}]
    return {
        "health_scores": health,
        "lifecycle_risk": analyze.compute_lifecycle_risk({"dark": {"model": "", "sw_version": ""},
                                                          "lit": {"model": "", "sw_version": ""}}),
        "syslog_intelligence": analyze.compute_syslog_intelligence({"dark": "", "lit": log}),
        "qos_audit": analyze.compute_qos_audit({"lit": PLAIN_CONFIG}, all_hosts=["dark", "lit"]),
        "software_risk": analyze.compute_software_risk({"lit": PLAIN_CONFIG}, all_hosts=["dark", "lit"]),
        "platform_health": analyze.compute_platform_health({
            "dark": {"cpu": {}, "memory": {}, "system": {}},
            "mute": {"cpu": {}, "memory": {}, "system": {"uptime": "1d"}},
            "lit": {"cpu": cpu_ok, "memory": {}, "system": {}}}),
        "device_dossiers": analyze.compute_device_dossiers(health_scores=copy.deepcopy(health)),
    }


# --------------------------------------------------------------------------------------------------
# the registry is closed, read-only and held against the real producers
# --------------------------------------------------------------------------------------------------
def test_registry_partitions_every_brief_axis_exactly_once():
    stored, live, absent = set(uip.AXIS_UNASSESSED), set(uip.AXIS_UNASSESSED_LIVE), set(uip.AXIS_UNASSESSED_ABSENT)
    assert not stored & live and not stored & absent and not live & absent
    assert stored | live | absent == set(uip.AXIS_BASIS)
    assert isinstance(uip.AXIS_UNASSESSED, types.MappingProxyType)
    assert isinstance(uip.AXIS_UNASSESSED_ABSENT, types.MappingProxyType)
    assert isinstance(uip.AXIS_UNASSESSED_LIVE, tuple) and isinstance(uip.AXIS_UNASSESSED_SPARSE, frozenset)
    for table in (uip.AXIS_UNASSESSED, uip.AXIS_UNASSESSED_ABSENT):
        with pytest.raises(TypeError):
            table["x"] = "y"
    assert uip.AXIS_UNASSESSED_LIVE == ("Fleet health",) and uip.AXIS_BASIS["Fleet health"] == ("health_scores",)
    for label, (owner, n_path, of_path, rows_path, field, mark) in uip.AXIS_UNASSESSED.items():
        section = n_path.split(".")[0]
        assert section in uip.AXIS_BASIS[label], label
        assert of_path.split(".")[0] == rows_path.split(".")[0] == section, label
        assert owner == "analyze." + PRODUCERS[section], label
        assert callable(getattr(analyze, PRODUCERS[section])), label
        assert isinstance(field, str) and type(mark) in (str, bool), label
    parents = {spec[1].rsplit(".", 1)[0] for spec in uip.AXIS_UNASSESSED.values()}
    assert uip.AXIS_UNASSESSED_SPARSE and uip.AXIS_UNASSESSED_SPARSE <= parents
    for label, why in uip.AXIS_UNASSESSED_ABSENT.items():
        assert why and why == why.strip(), label


@pytest.mark.parametrize("label", sorted(uip.AXIS_UNASSESSED))
def test_each_entry_is_its_real_producers_own_rule(label):
    """The real producer writes the registered count equal to its rows carrying the registered value, and the
    registered denominator equal to its row count, on input where at least one device could not be assessed."""
    _owner, n_path, of_path, rows_path, field, mark = uip.AXIS_UNASSESSED[label]
    snap = _producer_snapshot()
    rows = _dotted(snap, rows_path)
    assert isinstance(rows, list) and rows, label
    marked = _marked(rows, field, mark)
    assert marked >= 1, label                                  # the fixture really holds an unassessed device
    assert _expected_count(snap, uip.AXIS_UNASSESSED[label]) == marked, label
    assert _dotted(snap, of_path) == len(rows), label


def test_sparse_counters_are_exactly_the_producers_that_omit_a_zero_entry():
    """A missing entry may read as zero only where the producer omits zero entries; every other registered count is a
    key its producer writes even at zero, so its absence is a count the snapshot does not store."""
    empty = {"lifecycle_risk": analyze.compute_lifecycle_risk({}),
             "syslog_intelligence": analyze.compute_syslog_intelligence(),
             "qos_audit": analyze.compute_qos_audit(),
             "software_risk": analyze.compute_software_risk(),
             "platform_health": analyze.compute_platform_health(),
             "device_dossiers": analyze.compute_device_dossiers()}
    for label, (_owner, n_path, _of, _rows, _field, _mark) in uip.AXIS_UNASSESSED.items():
        written = _dotted(empty, n_path)
        sparse = n_path.rsplit(".", 1)[0] in uip.AXIS_UNASSESSED_SPARSE
        assert (written is _MISSING) is sparse, (label, written)
        if not sparse:
            assert written == 0, label
    healthy = analyze.compute_platform_health({"lit": {"cpu": {"five_sec": 70, "interrupt": 0, "one_min": 65,
                                                               "five_min": 59}, "memory": {}, "system": {}}})
    assert "Unknown" not in healthy["summary"]["bands"]                     # its counter omits an empty band


# --------------------------------------------------------------------------------------------------
# projection over real producer output, the shipped sample and the golden sections
# --------------------------------------------------------------------------------------------------
def test_projection_publishes_each_real_producers_count_and_denominator():
    snap = _rebrief(_producer_snapshot())
    overview = uip.project_overview(snap)
    for label, spec in uip.AXIS_UNASSESSED.items():
        owner, n_path, of_path, _rows_path, _field, _mark = spec
        block = _item(overview, label)["unassessed"]
        assert set(block) == {"n", "of"}
        assert _sv(block["n"]) == (PUB, _dotted(snap, n_path)), (label, block["n"])
        assert _sv(block["of"]) == (PUB, _dotted(snap, of_path)), (label, block["of"])
        assert block["n"]["subject"] == _ptr(n_path) and block["of"]["subject"] == _ptr(of_path)
        assert block["n"]["basis"] == f"{owner}:{n_path}"
        assert {"pointer": _ptr(of_path), "role": "denominator"} in block["n"]["refs"]
        assert "axis_basis_owned_by_projection" in block["n"]["caveats"]
        assert "axis_basis_owned_by_projection" in block["of"]["caveats"]
    # Platform capacity counts its Unknown band, which includes a collected device whose output was not
    # recognised: more than the devices whose capacity output was not collected at all.
    platform = _item(overview, "Platform capacity")["unassessed"]["n"]
    summary = snap["platform_health"]["summary"]
    assert platform["value"] == summary["bands"]["Unknown"] > summary["n_not_collected"]
    # Fleet health: the owner's unscored rows, out of its health rows.
    fh = ssot.fleet_avg_health(snap)
    fleet = _item(overview, "Fleet health")["unassessed"]
    assert _sv(fleet["n"]) == (PUB, fh["n_rows"] - fh["n_scored"]) and fleet["n"]["value"] >= 1
    assert _sv(fleet["of"]) == (PUB, fh["n_rows"]) == (PUB, len(snap["health_scores"]))
    assert fleet["n"]["subject"] is None and {"pointer": "/health_scores", "role": "basis"} in fleet["n"]["refs"]


def _golden_with_brief():
    """The golden snapshot stores the producer sections but no brief: recompute it with the real producer."""
    return _rebrief(json.loads(GOLDEN.read_text(encoding="utf-8")))


@pytest.mark.parametrize("source", ["sample", "golden"])
def test_engine_built_snapshots_publish_the_stored_counts(source):
    """The shipped engine-built sample (its stored brief) and the golden producer sections (brief recomputed): every
    registered axis publishes its producer's stored count and denominator, which agree with the producer's own rows;
    Fleet health is the owner's unscored rows; every other axis is not_collected, never 0."""
    snap = _sample() if source == "sample" else _golden_with_brief()
    overview = uip.project_overview(snap)
    seen = 0
    for item in overview["axes"]["items"]:
        label, block = item["axis"], item["unassessed"]
        assert set(block) == {"n", "of"}, label
        if label in uip.AXIS_UNASSESSED:
            spec = uip.AXIS_UNASSESSED[label]
            _owner, n_path, of_path, rows_path, field, mark = spec
            rows = _dotted(snap, rows_path)
            want_n, want_of = _expected_count(snap, spec), _dotted(snap, of_path)
            assert want_n == _marked(rows, field, mark) and want_of == len(rows), label   # the raw basis agrees
            assert _sv(block["n"]) == (PUB, want_n), (label, block["n"])
            assert _sv(block["of"]) == (PUB, want_of), (label, block["of"])
            if _dotted(snap, n_path) is not _MISSING:
                assert _resolve(snap, block["n"]["subject"]) == want_n
                if want_n == 0:                                           # a measured zero keeps the owner's token
                    assert block["n"]["engine_state"] == CBE
                    assert "measured_zero_mapping" in block["n"]["caveats"]
            seen += 1
        elif label in uip.AXIS_UNASSESSED_LIVE:
            fh = ssot.fleet_avg_health(snap)
            assert _sv(block["n"]) == (PUB, fh["n_rows"] - fh["n_scored"])
            assert _sv(block["of"]) == (PUB, len(snap["health_scores"]))
            assert block["of"]["value"] == overview["fleet_health"]["n_rows"]["value"]
        else:
            assert label in uip.AXIS_UNASSESSED_ABSENT, label
            for key in ("n", "of"):
                assert _sv(block[key]) == (NC, None), (label, key, block[key])
                assert NEVER_ZERO in block[key]["reason"]
                assert block[key]["basis"] == "cisco_toolkit.ui_projection.AXIS_UNASSESSED_ABSENT"
    assert seen == sum(1 for it in overview["axes"]["items"] if it["axis"] in uip.AXIS_UNASSESSED) >= 4
    published = [it["unassessed"]["n"]["value"] for it in overview["axes"]["items"]
                 if it["unassessed"]["n"]["state"] == PUB]
    assert any(published), "the fixture should carry at least one axis that could not assess a device"
    if source == "sample":
        lifecycle = _item(overview, "Hardware lifecycle (EoL)")["unassessed"]
        assert _sv(lifecycle["n"]) == _sv(overview["facts"]["n_unknown"]["fact"])      # one stored owner
        assert _sv(lifecycle["of"]) == _sv(overview["lifecycle"]["of"])


def test_payload_validates_and_the_block_is_closed():
    schema = uip.ui_projection_schema()
    defs = schema["$defs"]
    assert "unassessed" in defs["AxisItem"]["required"]
    assert defs["AxisItem"]["properties"]["unassessed"] == {"$ref": "#/$defs/AxisUnassessed"}
    block = defs["AxisUnassessed"]
    assert block["additionalProperties"] is False and block["required"] == ["n", "of"]
    assert block["properties"] == {"n": {"$ref": "#/$defs/CountFact"}, "of": {"$ref": "#/$defs/CountFact"}}
    validator = Draft202012Validator(schema)
    payload = uip.project(_sample())
    validator.validate(payload)

    def forged(edit):
        bad = copy.deepcopy(payload)
        edit(bad["overview"]["axes"]["items"][0])
        return bad

    assert not validator.is_valid(forged(lambda it: it.pop("unassessed")))
    assert not validator.is_valid(forged(lambda it: it["unassessed"].pop("of")))
    assert not validator.is_valid(forged(lambda it: it["unassessed"].update(total=it["unassessed"]["of"])))
    assert not validator.is_valid(forged(lambda it: it["unassessed"]["n"].update(state=PUB, value=-1)))
    assert not validator.is_valid(forged(lambda it: it["unassessed"]["n"].update(state=PUB, value=None)))
    assert not validator.is_valid(forged(lambda it: it["unassessed"]["n"].update(state=NC, value=0, reason="x")))


def test_the_count_never_comes_from_the_headline():
    snap = _sample()
    before = [it["unassessed"] for it in uip.project_overview(snap)["axes"]["items"]]
    for row in snap["executive_brief"]["axes"]:
        row["headline"] = "0 of 0 NOT ASSESSED"
        row["detail"] = ""
    after = [it["unassessed"] for it in uip.project_overview(snap)["axes"]["items"]]
    assert after == before


# --------------------------------------------------------------------------------------------------
# absence, failure and contradiction never render as a measurement
# --------------------------------------------------------------------------------------------------
def test_a_failed_input_is_unavailable_with_its_failure_record():
    sample = _sample()
    for section, label in (("software_risk", "Software risk"), ("punchlist", "Migration punch-list"),
                           ("health_scores", "Fleet health")):
        phase = next(lab for lab, secs in ssot.PHASE_SECTIONS.items() if section in secs)
        snap = copy.deepcopy(sample)
        snap["assessment_integrity"] = {"failed_phases": [phase]}
        overview = uip.project_overview(snap)
        block = _item(overview, label)["unassessed"]
        for key in ("n", "of"):
            assert _sv(block[key]) == (AU, None), (label, key, block[key])
            assert {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in block[key]["refs"]
        other = _item(overview, "QoS posture")["unassessed"]["n"]          # an unfailed input stays published
        assert other["state"] == PUB and "one_hop_failure_attribution" in other["caveats"]


def test_a_missing_count_or_section_is_not_collected_never_zero():
    sample = _sample()
    snap = copy.deepcopy(sample)
    del snap["software_risk"]["summary"]["n_config_not_assessable"]
    block = _unassessed(snap, "Software risk")
    assert _sv(block["n"]) == (NC, None)
    assert "predates" in block["n"]["reason"] and NEVER_ZERO in block["n"]["reason"]
    assert block["n"]["subject"] == "/software_risk/summary/n_config_not_assessable"
    assert _sv(block["of"]) == (PUB, sample["software_risk"]["summary"]["n_devices"])
    snap = copy.deepcopy(sample)
    del snap["device_dossiers"]["summary"]["bands"]["Unassessed"]             # a counter that is never sparse
    assert _sv(_unassessed(snap, "Asset risk register")["n"]) == (NC, None)
    snap = copy.deepcopy(sample)
    snap.pop("qos_audit")
    block = _unassessed(snap, "QoS posture")
    assert _sv(block["n"]) == (NC, None) and _sv(block["of"]) == (NC, None)
    snap = copy.deepcopy(sample)
    snap.pop("health_scores")
    block = _unassessed(snap, "Fleet health")
    assert _sv(block["n"]) == (NC, None) and _sv(block["of"]) == (NC, None)


def test_a_sparse_counters_zero_needs_its_rows_to_confirm_it():
    sample = _sample()
    calm = copy.deepcopy(sample)
    for row in calm["platform_health"]["per_device"]:
        row["band"] = "OK"
    calm["platform_health"]["summary"]["bands"] = {"OK": len(calm["platform_health"]["per_device"])}
    n = _unassessed(calm, "Platform capacity")["n"]
    assert _sv(n) == (PUB, 0) and n["subject"] is None
    for ref in ({"pointer": "/platform_health/summary/bands", "role": "witness"},
                {"pointer": "/platform_health/per_device", "role": "witness"},
                {"pointer": "/platform_health/summary/n_devices", "role": "denominator"}):
        assert ref in n["refs"], ref
    assert "axis_basis_owned_by_projection" in n["caveats"]
    unconfirmed = copy.deepcopy(calm)
    del unconfirmed["platform_health"]["per_device"]
    n = _unassessed(unconfirmed, "Platform capacity")["n"]
    assert _sv(n) == (NC, None) and "cannot confirm" in n["reason"] and NEVER_ZERO in n["reason"]
    hidden = copy.deepcopy(calm)
    hidden["platform_health"]["per_device"][0]["band"] = "Unknown"
    n = _unassessed(hidden, "Platform capacity")["n"]
    assert _sv(n) == (UV, None) and "yet 1 of the rows" in n["reason"]
    unreadable = copy.deepcopy(calm)
    unreadable["platform_health"]["per_device"][0]["band"] = None
    assert _sv(_unassessed(unreadable, "Platform capacity")["n"]) == (UV, None)


def test_a_contradicted_count_is_unverified_never_published():
    sample = _sample()
    summary = sample["software_risk"]["summary"]
    n_ptr, of_ptr = "/software_risk/summary/n_config_not_assessable", "/software_risk/summary/n_devices"

    def projected(edit):
        snap = copy.deepcopy(sample)
        edit(snap["software_risk"])
        return _unassessed(snap, "Software risk")

    block = projected(lambda sr: sr["summary"].update(n_config_not_assessable=summary["n_devices"] + 1))
    for key in ("n", "of"):
        assert _sv(block[key]) == (UV, None) and "exceeds" in block[key]["reason"], key
        assert {"pointer": n_ptr, "role": "witness"} in block[key]["refs"]
        assert {"pointer": of_ptr, "role": "witness"} in block[key]["refs"]
    assert block["n"]["engine_state"] == PUB                                    # the owner's token is kept

    def flip(sr):
        row = next(r for r in sr["per_device"] if r["config_assessable"] is True)
        row["config_assessable"] = False

    for edit, words in ((flip, "software_risk.per_device holds"),
                        (lambda sr: sr["per_device"][0].update(config_assessable="False"), "cannot be read"),
                        (lambda sr: sr["per_device"].pop(), "software_risk.per_device holds")):
        block = projected(edit)
        for key in ("n", "of"):
            assert _sv(block[key]) == (UV, None), (words, key, block[key])
            assert words in block[key]["reason"]
            assert {"pointer": "/software_risk/per_device", "role": "witness"} in block[key]["refs"]
    # no raw basis at all: the stored summary is published as it stands, with no row witness
    block = projected(lambda sr: sr.pop("per_device"))
    assert _sv(block["n"]) == (PUB, summary["n_config_not_assessable"])
    assert _sv(block["of"]) == (PUB, summary["n_devices"])
    assert all(ref["pointer"] != "/software_risk/per_device" for ref in block["n"]["refs"])


def test_a_zero_over_a_zero_denominator_is_not_a_measurement():
    snap = _sample()
    snap["qos_audit"] = analyze.compute_qos_audit()                           # the real producer over no device
    block = _unassessed(snap, "QoS posture")
    assert _sv(block["of"]) == (PUB, 0) and "measured_zero_mapping" in block["of"]["caveats"]
    assert _sv(block["n"]) == (CBE, None) and "covered no device" in block["n"]["reason"]
    empty = _sample()
    empty["health_scores"] = []
    block = _unassessed(_rebrief(empty), "Fleet health")
    assert _sv(block["of"]) == (PUB, 0)
    assert _sv(block["n"]) == (CBE, None) and "no health row" in block["n"]["reason"]


def test_an_unscored_fleet_counts_every_row_as_unassessed():
    snap = _sample()
    for row in snap["health_scores"]:
        row["band"] = "Insufficient Data"
    block = _unassessed(_rebrief(snap), "Fleet health")
    assert ssot.fleet_avg_health(snap)["n_scored"] == 0
    assert _sv(block["n"]) == _sv(block["of"]) == (PUB, len(snap["health_scores"]))


def test_an_unreadable_or_unregistered_axis_label_claims_nothing():
    snap = {"executive_brief": {"axes": [{"axis": "Brand-new axis", "severity": "Low", "headline": "h",
                                          "detail": "d"}, 7]}}
    items = uip.project_overview(snap)["axes"]["items"]
    new, broken = items[0]["unassessed"], items[1]["unassessed"]
    for key in ("n", "of"):
        assert _sv(new[key]) == (NC, None) and NEVER_ZERO in new[key]["reason"]
        assert _sv(broken[key]) == (UV, None) and "no readable label" in broken[key]["reason"]
        assert {"pointer": "/executive_brief/axes/1", "role": "witness"} in broken[key]["refs"]
