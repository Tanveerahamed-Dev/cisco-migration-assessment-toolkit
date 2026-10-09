"""G05 (W40) -- per executive axis, how many devices it could not assess, out of how many.

``overview.axes.items[].unassessed = {n: CountFact, of: CountFact}`` is read from each axis's producer through
``cisco_toolkit.ui_projection.AXIS_UNASSESSED`` (and ``ssot.fleet_avg_health`` for Fleet health), never from the
brief's headline text. Coverage honesty is the point:

* an axis whose producer stores no such count is not_collected, never 0, and a failed input is analysis_unavailable;
* a count missing from a summary its producer wrote is not_collected, except a sparse counter's entry, which is a zero
  only when the producer's per-device rows confirm it;
* a count its own denominator or per-device rows contradict, or whose rows cannot be read, is unverified;
* a zero over a zero denominator is collected_but_empty, never a measurement;
* a count that covers one layer of an axis whose producer assesses another (``AXIS_UNASSESSED_LAYERS``) is withheld
  while that layer's OWN could-not-assess count is above zero, its value and the gap named in the reason (W51: Software
  risk's release-train layer is its train_bands Unknown count -- a release captured but never classified is not
  assessed -- never n_version_known);
* while collection_completeness lists a blind spot, no producer universe holds the unreached device: a published
  count or denominator carries ``fleet_lists_exclude_blind_devices`` with a witness to each blind-spot row, and a zero
  is not_collected; so it does (W51) while the record itself cannot show every device collected or listed (absent,
  failed with its failure record cited, or a summary that does not reconcile with its rows);
* a failed input withholds the block exactly as it withholds the row's fact.

The fixtures come from the engine's own code: the shipped engine-built sample fleet, the golden snapshot's producer
sections with the brief recomputed by the real ``analyze.compute_executive_brief``, and the real producers called on
small inputs (the patterns of tests/test_dossier_input_state.py, tests/test_device_dossiers.py,
tests/test_platform_health.py and tests/test_collection_completeness.py). Expectations are read from the snapshot and
its owners, never from cached sample literals. Single-field edits of the sample probe one rule each.
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib
import re
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
BLIND = "fleet_lists_exclude_blind_devices"
LOG = "Syslog logging: enabled\nLog Buffer (8192 bytes):\n"
CPU_OK = {"five_sec": 70, "interrupt": 0, "one_min": 65, "five_min": 59}
#: A summary key counting the devices one layer of an axis could assess (its evidence captured): the class the
#: further-layer registry must account for. A negated key ('n_not_collected', 'n_config_not_assessable') is the
#: registered count's own form, not another layer.
COVERAGE_KEY = re.compile(r"n_(?:[a-z0-9]+_)*(?:known|assessable|collected)")
#: Reviewed: the coverage key that is the registered count's own complement, per producer section. Its uncovered
#: devices all sit inside the registered count (held below on the real producers), so it is no further layer.
COMPLEMENTS = {"syslog_intelligence": "n_collected", "qos_audit": "n_assessable",
               "software_risk": "n_config_assessable", "platform_health": "n_collected"}

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


def _layer_count(snap, layer):
    """A further layer's own could-not-assess count, read independently: the stored entry, or a sparse counter's
    omitted zero confirmed by its per-device rows; ``None`` when neither can be read."""
    path, _name, rows_path, field, mark, _cover = layer
    stored = _dotted(snap, path)
    if stored is _MISSING and path.rsplit(".", 1)[0] in uip.AXIS_UNASSESSED_SPARSE:
        rows = _dotted(snap, rows_path)
        if isinstance(rows, list) and all(isinstance(r, dict) and type(r.get(field)) is type(mark) for r in rows):
            return _marked(rows, field, mark)
        return None
    return stored if type(stored) is int else None


def _layer_gaps(snap, label):
    """The further layers whose own count shows a device they could not assess, or cannot be read: ``[(pointer,
    count or None, device count)]``, read independently from the snapshot."""
    of = _dotted(snap, uip.AXIS_UNASSESSED[label][2])
    out = []
    for layer in uip.AXIS_UNASSESSED_LAYERS.get(label, ()):
        count = _layer_count(snap, layer)
        readable = count is not None and type(of) is int
        if not readable or count != 0:
            out.append((_ptr(layer[0]), count if readable else None, of))
    return out


def _producer_snapshot():
    """The six registered producers, run for real on two to three devices, each with at least one device the axis
    could not assess. Platform capacity holds a device whose capacity output was collected but not recognised, so
    its could-not-assess count (the Unknown band) exceeds its not-collected count. Software risk's release-train layer
    sees every device's version, so its configuration-layer count is the axis's."""
    health = [{"switch": "dark", "score": None, "band": "Insufficient Data", "role": "access", "criticality": 1.0,
               "deductions": []},
              {"switch": "lit", "score": 96, "band": "Excellent", "role": "access", "criticality": 1.0,
               "deductions": []}]
    return {
        "health_scores": health,
        "lifecycle_risk": analyze.compute_lifecycle_risk({"dark": {"model": "", "sw_version": ""},
                                                          "lit": {"model": "", "sw_version": ""}}),
        "syslog_intelligence": analyze.compute_syslog_intelligence({"dark": "", "lit": LOG}),
        "qos_audit": analyze.compute_qos_audit({"lit": PLAIN_CONFIG}, all_hosts=["dark", "lit"]),
        "software_risk": analyze.compute_software_risk({"lit": PLAIN_CONFIG},
                                                       {"dark": {"sw_version": "17.9.4"},
                                                        "lit": {"sw_version": "17.12.1"}},
                                                       all_hosts=["dark", "lit"]),
        "platform_health": analyze.compute_platform_health({
            "dark": {"cpu": {}, "memory": {}, "system": {}},
            "mute": {"cpu": {}, "memory": {}, "system": {"uptime": "1d"}},
            "lit": {"cpu": CPU_OK, "memory": {}, "system": {}}}),
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
    layer_parents = {layer[0].rsplit(".", 1)[0] for layers in uip.AXIS_UNASSESSED_LAYERS.values() for layer in layers}
    assert uip.AXIS_UNASSESSED_SPARSE and uip.AXIS_UNASSESSED_SPARSE <= parents | layer_parents
    for label, why in uip.AXIS_UNASSESSED_ABSENT.items():
        assert why and why == why.strip(), label
    assert isinstance(uip.AXIS_UNASSESSED_LAYERS, types.MappingProxyType)
    with pytest.raises(TypeError):
        uip.AXIS_UNASSESSED_LAYERS["x"] = ()
    assert set(uip.AXIS_UNASSESSED_LAYERS) <= set(uip.AXIS_UNASSESSED)
    for label, layers in uip.AXIS_UNASSESSED_LAYERS.items():
        assert isinstance(layers, tuple) and layers, label
        for path, layer, rows_path, field, mark, cover in layers:
            section = uip.AXIS_UNASSESSED[label][1].split(".")[0]
            assert path.split(".")[0] == rows_path.split(".")[0] == section, (label, path)
            assert path != uip.AXIS_UNASSESSED[label][1] and layer and layer == layer.strip(), (label, path)
            assert isinstance(field, str) and type(mark) in (str, bool) and cover, (label, path)


def test_every_per_layer_coverage_count_is_a_registered_layer_or_the_counts_complement():
    """The class guard for AXIS_UNASSESSED_LAYERS: every count a registered producer's REAL summary keeps of the devices
    one layer could assess is either a registered further layer's coverage key or the registered count's own
    complement. A complement leaves no device outside the registered count, and a layer's coverage key leaves none
    outside that layer's own could-not-assess count (W51: n_version_known's uncovered devices all sit in train_bands
    Unknown, which also holds the captured releases the producer could not classify)."""
    snap = _producer_snapshot()
    seen = set()
    for label, spec in uip.AXIS_UNASSESSED.items():
        _owner, n_path, of_path, _rows_path, _field, _mark = spec
        section = n_path.split(".")[0]
        summary = snap[section]["summary"]
        keys = {key for key in summary if COVERAGE_KEY.fullmatch(key) and "not_" not in key}
        layers = uip.AXIS_UNASSESSED_LAYERS.get(label, ())
        covers = {layer[5] for layer in layers}
        complement = COMPLEMENTS.get(section)
        assert keys == covers | ({complement} if complement else set()), (label, sorted(keys))
        for layer in layers:
            count = _layer_count(snap, layer)
            assert type(count) is int, (label, layer[0])                   # the real producer's count reads
            uncovered = _dotted(snap, of_path) - summary[layer[5]]
            assert 0 <= uncovered <= count, (label, layer[5], count)
        if complement:
            uncovered = _dotted(snap, of_path) - summary[complement]
            assert 0 <= uncovered <= _expected_count(snap, spec), (label, complement)
        seen |= keys
    assert "n_version_known" in seen                    # the guard reaches the one further layer that exists today


def test_each_layer_count_is_its_real_producers_own_rule():
    """The real producer writes a layer's could-not-assess count equal to its rows carrying the registered value, and
    omits the entry exactly when no row carries it (a sparse counter)."""
    rich = analyze.compute_software_risk({"a": PLAIN_CONFIG}, {"a": {"sw_version": "17.9.4"},
                                                                 "b": {"sw_version": "8.4(2)"},
                                                                 "c": {"sw_version": ""}}, all_hosts=["a", "b", "c"])
    calm = analyze.compute_software_risk({"a": PLAIN_CONFIG}, {"a": {"sw_version": "17.9.4"}}, all_hosts=["a"])
    for layer in uip.AXIS_UNASSESSED_LAYERS["Software risk"]:
        path, _name, rows_path, field, mark, _cover = layer
        rows = _dotted({"software_risk": rich}, rows_path)
        assert _dotted({"software_risk": rich}, path) == _marked(rows, field, mark) == 2   # uncaptured AND unclassified
        assert _dotted({"software_risk": calm}, path) is _MISSING                           # omitted at zero
        assert path.rsplit(".", 1)[0] in uip.AXIS_UNASSESSED_SPARSE


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
    registered axis publishes its producer's stored count and denominator, which agree with the producer's own rows,
    unless a further layer of the axis shows a gap, which withholds the count and names it; Fleet health is the
    owner's unscored rows; every other axis is not_collected, never 0. Neither snapshot lists a blind spot."""
    snap = _sample() if source == "sample" else _golden_with_brief()
    blind = _dotted(snap, "collection_completeness.devices")
    assert blind is _MISSING or blind == []
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
            assert _sv(block["of"]) == (PUB, want_of), (label, block["of"])
            gaps = _layer_gaps(snap, label)
            if gaps:                                    # one layer's count is not the axis's: withheld, named
                assert _sv(block["n"]) == (NC, None), (label, block["n"])
                assert NEVER_ZERO in block["n"]["reason"] and f"({want_n})" in block["n"]["reason"]
                for pointer, count, of in gaps:
                    if count is not None:
                        assert {"pointer": pointer, "role": "witness"} in block["n"]["refs"]
                        assert f"could not assess {count} of the {of} device(s)" in block["n"]["reason"]
                assert block["n"]["engine_state"] == (CBE if want_n == 0 else PUB)   # the owner's own token
            else:
                assert _sv(block["n"]) == (PUB, want_n), (label, block["n"])
            if _dotted(snap, n_path) is not _MISSING:
                assert _resolve(snap, block["n"]["subject"]) == want_n
                if want_n == 0 and not gaps:                              # a measured zero keeps the owner's token
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
    assert "for example" in block["n"]["reason"] and "edited" in block["n"]["reason"]   # a cause it cannot know
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
    # a further layer's count above the device count contradicts the summary as well
    block = projected(lambda sr: sr["summary"]["train_bands"].update(Unknown=summary["n_devices"] + 1))
    for key in ("n", "of"):
        assert _sv(block[key]) == (UV, None) and "further layer" in block[key]["reason"], key
        assert {"pointer": "/software_risk/summary/train_bands/Unknown", "role": "witness"} in block[key]["refs"]

    # W51: a further layer's count its own per-device rows contradict (a row the counter omits)
    def unlisted_unknown(sr):
        row = next(r for r in sr["per_device"] if r["train_band"] != "Unknown")
        row["train_band"] = "Unknown"

    block = projected(unlisted_unknown)
    for key in ("n", "of"):
        assert _sv(block[key]) == (UV, None), (key, block[key])
        assert "disagrees with its per-device rows" in block[key]["reason"], block[key]["reason"]
        assert {"pointer": "/software_risk/per_device", "role": "witness"} in block[key]["refs"]

    # no raw basis at all: the stored summary is published as it stands, with no row witness (the release-train
    # layer's own count is a stored zero here, so the configuration layer's count is the axis's)
    def no_rows(sr):
        sr.pop("per_device")
        sr["summary"]["train_bands"]["Unknown"] = 0

    block = projected(no_rows)
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


# --------------------------------------------------------------------------------------------------
# a further layer the count does not cover (Software risk's release-train layer)
# --------------------------------------------------------------------------------------------------
def _software_only(configs, versions, hosts=("acc1", "acc2")):
    """The real software-risk producer over `hosts`, with the brief recomputed by its real producer. The real
    collection-completeness producer over an empty capture set supplies a readable blind-spot record that lists none
    (W51: a record the snapshot does not carry would qualify every count instead)."""
    snap = {"software_risk": analyze.compute_software_risk(
        {h: PLAIN_CONFIG for h in configs}, {h: {"model": "", "sw_version": versions.get(h, "")} for h in hosts},
        all_hosts=list(hosts)),
        "collection_completeness": analyze.compute_collection_completeness([], {})}
    return _rebrief(snap)


UNKNOWN_TRAIN = "/software_risk/summary/train_bands/Unknown"


def test_a_count_that_covers_one_layer_is_withheld_while_another_layer_has_a_gap():
    """Every configuration captured and no software version: the producer's configuration-layer count is 0, yet its
    release-train layer assessed nothing. The axis is never 'could not assess 0'; the reason names both stored counts."""
    snap = _software_only(configs=("acc1", "acc2"), versions={})
    summary = snap["software_risk"]["summary"]
    assert summary["n_config_not_assessable"] == 0 and summary["train_bands"] == {"Unknown": 2}   # the real producer
    assert summary["n_devices"] == 2
    block = _unassessed(snap, "Software risk")
    n = block["n"]
    assert _sv(n) == (NC, None), n
    assert "this count (0) covers one layer of the axis only" in n["reason"]
    assert "release-train layer" in n["reason"] and "could not assess 2 of the 2 device(s)" in n["reason"]
    assert "software_risk.summary.train_bands.Unknown is 2" in n["reason"] and NEVER_ZERO in n["reason"]
    assert {"pointer": UNKNOWN_TRAIN, "role": "witness"} in n["refs"]
    assert n["subject"] == "/software_risk/summary/n_config_not_assessable"
    assert n["engine_state"] == CBE                                    # the owner's own stored zero
    assert _sv(block["of"]) == (PUB, 2)

    # one version captured: still a gap, of one device; a positive configuration-layer count is withheld too
    partial = _software_only(configs=("acc1",), versions={"acc1": "17.12.1"})
    n = _unassessed(partial, "Software risk")["n"]
    assert partial["software_risk"]["summary"]["n_config_not_assessable"] == 1
    assert _sv(n) == (NC, None) and "this count (1)" in n["reason"]
    assert "could not assess 1 of the 2 device(s)" in n["reason"] and n["engine_state"] == PUB

    # an unreadable layer count cannot show the layer complete
    unread = copy.deepcopy(snap)
    del unread["software_risk"]["summary"]["train_bands"]
    n = _unassessed(unread, "Software risk")["n"]
    assert _sv(n) == (NC, None) and "is not a readable count" in n["reason"] and NEVER_ZERO in n["reason"]

    # control: every version captured and classified, so the configuration layer's zero is the axis's measured zero
    # (the counter omits the empty Unknown band; the per-device rows confirm it)
    full = _software_only(configs=("acc1", "acc2"), versions={"acc1": "17.12.1", "acc2": "17.9.4"})
    assert "Unknown" not in full["software_risk"]["summary"]["train_bands"]
    n = _unassessed(full, "Software risk")["n"]
    assert _sv(n) == (PUB, 0) and "measured_zero_mapping" in n["caveats"]
    assert all(ref["pointer"] != UNKNOWN_TRAIN for ref in n["refs"])


def test_a_release_captured_but_never_classified_is_not_assessed():
    """W51 (G05 P1, the reviewer's case): every release captured (n_version_known equals n_devices) and every
    configuration captured, yet the producer classifies no release train. The release-train layer is read from its
    own could-not-assess count (train_bands Unknown), so the axis is never 'could not assess 0'. Before W51 the layer
    was read from n_version_known and the 0 was published as a measurement."""
    snap = _software_only(configs=("acc1", "acc2"), versions={"acc1": "8.4(2)", "acc2": "8.4(2)"})
    summary = snap["software_risk"]["summary"]
    assert summary["n_version_known"] == summary["n_devices"] == 2                           # every release captured
    assert summary["n_config_not_assessable"] == 0 and summary["train_bands"] == {"Unknown": 2}   # none classified
    n = _unassessed(snap, "Software risk")["n"]
    assert _sv(n) == (NC, None), n
    assert "could not assess 2 of the 2 device(s)" in n["reason"] and NEVER_ZERO in n["reason"]
    assert {"pointer": UNKNOWN_TRAIN, "role": "witness"} in n["refs"]
    assert n["engine_state"] == CBE


# --------------------------------------------------------------------------------------------------
# a collection blind spot: no producer universe holds the device the collection never reached
# --------------------------------------------------------------------------------------------------
ESSENTIAL = ("interface status", "interface switchport", "version", "cdp neighbors detail")


def _captures(root, host, names):
    """Capture files for `host`, keyed by the full show command as the real all_cmd_to_files is."""
    folder = root / host
    folder.mkdir()
    out = {}
    for name in names:
        path = folder / f"show_{name.replace(' ', '_')}.txt"
        path.write_text("data\n", encoding="utf-8")
        out[f"show {name}"] = str(path)
    return out


def _blind_fleet(root, third):
    """Three inventory devices. `third` is 'unreached' (no capture at all: the producers never see it, as when
    COLLECT_PARSE skips a device whose collection returned nothing), 'partial' (reached, its CDP/LLDP capture
    missing, so the producers do see it) or 'complete'. Every producer is the real one, and every device it sees
    is fully assessable, so each stored could-not-assess count is 0 apart from the lifecycle band (no model)."""
    acf = {h: _captures(root, h, ESSENTIAL) for h in ("acc1", "acc2")}
    seen = ["acc1", "acc2"]
    if third == "partial":
        acf["edge"] = _captures(root, "edge", ESSENTIAL[:3])
        seen.append("edge")
    elif third == "complete":
        acf["edge"] = _captures(root, "edge", ESSENTIAL)
        seen.append("edge")
    health = [{"switch": h, "score": 96, "band": "Excellent", "role": "access", "criticality": 1.0, "deductions": []}
              for h in seen]
    snap = {
        "collection_completeness": analyze.compute_collection_completeness(["acc1", "acc2", "edge"], acf),
        "health_scores": health,
        "lifecycle_risk": analyze.compute_lifecycle_risk({h: {"model": "", "sw_version": ""} for h in seen}),
        "syslog_intelligence": analyze.compute_syslog_intelligence({h: LOG for h in seen}),
        "qos_audit": analyze.compute_qos_audit({h: PLAIN_CONFIG for h in seen}),
        "software_risk": analyze.compute_software_risk({h: PLAIN_CONFIG for h in seen},
                                                       {h: {"sw_version": "17.12.1"} for h in seen}),
        "platform_health": analyze.compute_platform_health(
            {h: {"cpu": CPU_OK, "memory": {}, "system": {}} for h in seen}),
        "device_dossiers": analyze.compute_device_dossiers(health_scores=copy.deepcopy(health)),
    }
    return _rebrief(snap)


@pytest.mark.parametrize("third", ["unreached", "partial"])
def test_a_blind_spot_never_hides_behind_a_zero(tmp_path, third):
    snap = _blind_fleet(tmp_path, third)
    rows = snap["collection_completeness"]["devices"]
    want_status = "not collected" if third == "unreached" else "partial"
    assert [(r["host"], r["status"]) for r in rows] == [("edge", want_status)]          # the real producer
    witness = {"pointer": "/collection_completeness/devices/0", "role": "witness"}
    logs = snap["syslog_intelligence"]["summary"]
    assert logs["n_not_collected"] == 0 and logs["n_devices"] == (2 if third == "unreached" else 3)
    overview = uip.project_overview(snap)
    checked = set()
    for item in overview["axes"]["items"]:
        label = item["axis"]
        if label not in uip.AXIS_UNASSESSED and label not in uip.AXIS_UNASSESSED_LIVE:
            continue
        checked.add(label)
        for key in ("n", "of"):
            fact = item["unassessed"][key]
            assert _sv(fact) != (PUB, 0), (label, key, fact)
            assert witness in fact["refs"], (label, key)
            if fact["state"] == PUB:
                assert BLIND in fact["caveats"], (label, key)
            else:
                assert fact["state"] == NC and NEVER_ZERO in fact["reason"], (label, key, fact)
                assert "collection_completeness lists 1 device(s) as partial or not collected" in fact["reason"]
    assert checked == set(uip.AXIS_UNASSESSED) | set(uip.AXIS_UNASSESSED_LIVE)
    # the reviewer's case: logs from every device the producer saw, none missing, a device never reached
    logs_block = _item(overview, "Operational logs")["unassessed"]
    assert logs_block["n"]["state"] == NC and logs_block["n"]["engine_state"] == CBE   # the owner's stored zero
    assert logs_block["n"]["subject"] == "/syslog_intelligence/summary/n_not_collected"
    assert _sv(logs_block["of"]) == (PUB, logs["n_devices"])
    # a positive count stays published, as a count over the producer's own devices, with the caveat
    lifecycle = _item(overview, "Hardware lifecycle (EoL)")["unassessed"]["n"]
    assert _sv(lifecycle) == (PUB, snap["lifecycle_risk"]["summary"]["n_unknown"]) and lifecycle["value"] >= 2
    assert BLIND in lifecycle["caveats"] and "axis_basis_owned_by_projection" in lifecycle["caveats"]
    # the whole payload stays valid, and the caveat is addressed to the axes
    Draft202012Validator(uip.ui_projection_schema()).validate(uip.project(snap))
    assert "/overview/axes" in {lim["id"]: lim for lim in uip.LIMITATIONS}[BLIND]["applies_to"]


def test_with_no_blind_spot_the_same_zero_is_a_measurement(tmp_path):
    """Control for the test above: the same fleet with every inventory device collected publishes the zero."""
    snap = _blind_fleet(tmp_path, "complete")
    assert snap["collection_completeness"]["devices"] == []
    overview = uip.project_overview(snap)
    logs_block = _item(overview, "Operational logs")["unassessed"]
    assert _sv(logs_block["n"]) == (PUB, 0) and "measured_zero_mapping" in logs_block["n"]["caveats"]
    for item in overview["axes"]["items"]:
        for key in ("n", "of"):
            assert BLIND not in item["unassessed"][key].get("caveats", ()), (item["axis"], key)


def test_a_count_over_no_device_beside_a_blind_spot_is_not_a_clean_result():
    """Every inventory device unreached: the producers cover none. Their 0 of 0 is collected_but_empty only while no
    blind spot is listed; here both cells are not_collected."""
    snap = {"collection_completeness": analyze.compute_collection_completeness(["acc1", "acc2"], {}),
            "qos_audit": analyze.compute_qos_audit(),
            "executive_brief": {"axes": [{"axis": "QoS posture", "severity": "Info", "headline": "h",
                                          "detail": "d"}]}}
    block = _unassessed(snap, "QoS posture")
    for key in ("n", "of"):
        assert _sv(block[key]) == (NC, None), (key, block[key])
        assert "collection_completeness lists 2 device(s)" in block[key]["reason"]
        for i in (0, 1):
            assert {"pointer": f"/collection_completeness/devices/{i}", "role": "witness"} in block[key]["refs"]
    assert "covered no device" in block["of"]["reason"]
    # control: with no blind spot listed, the same producer output is a zero over a zero denominator
    clean = copy.deepcopy(snap)
    clean["collection_completeness"] = analyze.compute_collection_completeness([], {})
    block = _unassessed(clean, "QoS posture")
    assert _sv(block["of"]) == (PUB, 0) and _sv(block["n"]) == (CBE, None)


_ZERO_QOS = "qos_audit"


def _zero_qos(sample):
    """The stored sample with every device's QoS assessable: its could-not-assess count is a stored 0."""
    snap = copy.deepcopy(sample)
    for row in snap[_ZERO_QOS]["per_device"]:
        row["assessable"] = True
    snap[_ZERO_QOS]["summary"]["n_not_assessable"] = 0
    return snap


@pytest.mark.parametrize("case", ["section_absent", "list_absent", "phase_failed", "summary_counts_unlisted",
                                  "inventory_off_roster"])
def test_a_blind_spot_record_that_cannot_show_every_device_never_lets_a_zero_publish(case):
    """W51 (G05 P2): the qualification fires on the blind-spot record's one coverage verdict, not only on a listed row.
    A record the snapshot does not carry, a failed phase (its failure record cited), a summary counting a blind spot
    its list does not carry, or an inventory count off the roster each leaves the record unable to show every
    inventory device collected or listed, so a zero count is never shown as 0. Before W51 each published 0."""
    snap = _zero_qos(_sample())
    cc = snap["collection_completeness"]
    failure = None
    if case == "section_absent":
        del snap["collection_completeness"]
    elif case == "list_absent":
        del cc["devices"]
    elif case == "phase_failed":
        snap["collection_completeness"] = {}                        # the _run_phase fallback
        snap["assessment_integrity"] = {"failed_phases": ["Collection completeness"]}
        failure = {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"}
    elif case == "summary_counts_unlisted":
        cc["summary"]["not_collected"] = 2
    else:
        cc["summary"]["inventory"] += 1
    n = _unassessed(snap, "QoS posture")["n"]
    assert _sv(n) == (NC, None), (case, n)
    assert NEVER_ZERO in n["reason"] and "collection_completeness" in n["reason"], (case, n["reason"])
    if failure is not None:
        assert failure in n["refs"], (case, n["refs"])
    # control: the same zero over the stored, reconciled record is a measurement
    control = _unassessed(_zero_qos(_sample()), "QoS posture")["n"]
    assert _sv(control) == (PUB, 0) and BLIND not in control.get("caveats", ())


# --------------------------------------------------------------------------------------------------
# a failed input: the block and the row's fact give one verdict
# --------------------------------------------------------------------------------------------------
def test_a_failed_input_withholds_the_block_exactly_as_it_withholds_the_row():
    qos_phase = next(lab for lab, secs in ssot.PHASE_SECTIONS.items() if "qos_audit" in secs)
    snap = {"executive_brief": {"axes": [{"axis": "Brand-new axis", "severity": "Low", "headline": "h",
                                          "detail": "d"}]},
            "assessment_integrity": {"failed_phases": [qos_phase]}}
    item = uip.project_overview(snap)["axes"]["items"][0]
    assert item["fact"]["state"] == AU                       # an unregistered label fails closed to every input
    for key in ("n", "of"):
        assert _sv(item["unassessed"][key]) == (AU, None), (key, item["unassessed"][key])
        assert {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in \
            item["unassessed"][key]["refs"]
    # a failed brief: every row's fact is unavailable, and so is every count beside it, while the producer's own
    # token stays visible on a count its producer did write
    brief_phase = next(lab for lab, secs in ssot.PHASE_SECTIONS.items() if "executive_brief" in secs)
    sample = _sample()
    sample["assessment_integrity"] = {"failed_phases": [brief_phase]}
    overview = uip.project_overview(sample)
    assert overview["axes"]["items"]
    for item in overview["axes"]["items"]:
        assert item["fact"]["state"] == AU, item["axis"]
        for key in ("n", "of"):
            assert _sv(item["unassessed"][key]) == (AU, None), (item["axis"], key)
            assert {"pointer": "/assessment_integrity/failed_phases/0", "role": "failure_record"} in \
                item["unassessed"][key]["refs"], (item["axis"], key)
    lifecycle = _item(overview, "Hardware lifecycle (EoL)")["unassessed"]["n"]
    assert lifecycle["engine_state"] == PUB and lifecycle["subject"] == "/lifecycle_risk/summary/n_unknown"
