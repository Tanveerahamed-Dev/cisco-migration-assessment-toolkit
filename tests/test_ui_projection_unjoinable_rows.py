"""F6 (W43): a row a key join cannot read never silently attaches to, or vanishes from, a device page.

A device page joins rows to one device by key: a health, lifecycle, dossier or blind-spot row by ``_resolve``'s list
join (``key_field``), the rows a selection keeps by ``_selection_rows``, and the owner's device scope
(``ssot._device_not_collected``) by the first ``collection_completeness.devices`` row naming the device. Each is the
same kind of join, held to one rule:

* a row the join cannot read (not an object, or a key that is missing or not text) could name any device, so while
  a list holds one, every join or selection from that list is ``unverified``, with a witness to each such row and to
  each row that does name the device: never a silent pick, and never the clean absence "no row for this device";
* the device scope reads only the first row naming a device and passes over every row it cannot read, so while
  ``collection_completeness.devices`` holds a row it cannot join, a second row naming the device, or a row whose
  status the owner's vocabulary does not name, every value about a device the scope does not call not collected is
  ``unverified`` with a witness to each such row; a device the owner does call not collected stays ``not_collected``;
* the inventory universe (devices map + blind spots) and the fleet lists' blind-spot qualifier disclose a blind-spot
  row they cannot read, with a witness, rather than passing over it.

The class members are found by reading the projection's own source (every ``key_field`` join and every
``_selection_rows`` call), so a join added later is held to the rule here without editing this file. Every value is
checked against the real stored sample (and the golden snapshot), and every withheld value is compared with the same
page over the unedited sample, which publishes it.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from cisco_toolkit import analyze, ssot
from cisco_toolkit import ui_projection as ui

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
HOST = "core1"
CC = ("collection_completeness", "devices")
ALL_ESSENTIAL = ["interface status", "switchport", "version/inventory", "CDP/LLDP neighbors"]
#: A blind-spot row the owner's device scope passes over: its status is readable, its host is not.
UNJOINABLE_CC = {"host": None, "status": "not collected", "data_quality": 0, "missing": list(ALL_ESSENTIAL)}
#: The one top-level device-page fact read from a fleet-level record rather than joined by device: the remediation
#: plan's banner (``_remediation_block`` resolves ``remediation_plan`` itself, with no host). Its pointer names no
#: device, so no device scope or device key join governs it; every test below asserts it stays as the sample has it.
FLEET_LEVEL = frozenset({"/remediation/banner"})
#: Host-independent totals no owner publishes: not_collected on every page, whatever the host.
HOST_INDEPENDENT = ("/deductions_cap/total", "/deduction_refs_cap/total")
SHAPES = ("none", "text", "int", "empty", "key_null", "key_int", "key_list")


# --------------------------------------------------------------------------------------------------
# fixtures and independent helpers (never the module's own join)
# --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema():
    return ui.ui_projection_schema()


@pytest.fixture(scope="module")
def doc_validator(schema):
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/DeviceDocument"})


@pytest.fixture(scope="module")
def payload_validator(schema):
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def topology_validator(schema):
    return Draft202012Validator({"$ref": "#/$defs/Topology", "$defs": schema["$defs"]})


def _page(snap, host, validator):
    doc = ui.project_device(snap, host)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    assert not errors, (host, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]])
    json.dumps(doc, allow_nan=False)
    return doc["device"]


def _payload(snap, validator):
    payload = ui.project(snap)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    json.dumps(payload, allow_nan=False)
    return payload


def _topology(snap, validator):
    topology = ui.project_topology(snap)
    errors = sorted(validator.iter_errors(topology), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    return topology


def _ptr(*tokens):
    return "".join("/" + str(t).replace("~", "~0").replace("/", "~1") for t in tokens)


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


def _top_facts(obj, where=""):
    """``(pointer, envelope)`` for every fact or fact list under `obj`, not descending into a list fact's items: the
    rows a selection keeps are fleet rows with their own states, and stay as they are."""
    if isinstance(obj, dict):
        if {"state", "subject", "refs", "basis"} <= set(obj):
            yield where, obj
            return
        for key, val in obj.items():
            yield from _top_facts(val, f"{where}/{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from _top_facts(val, f"{where}/{i}")


def _at(snap, toks):
    cur = snap
    for tok in toks:
        cur = cur[tok]
    return cur


def _naming(rows, host, field, norm=False):
    """Independent: the indices of the rows whose `field` names `host` (with `norm`, without case or surrounding
    space, the owner's device-scope rule)."""
    want = host.strip().lower() if norm else host
    out = []
    for i, row in enumerate(rows):
        val = row.get(field) if isinstance(row, dict) else None
        if isinstance(val, str) and (val.strip().lower() if norm else val) == want:
            out.append(i)
    return out


def _bad_row(shape, field):
    """A row an exact-key join over `field` cannot read; no producer writes one."""
    return {"none": None, "text": "not a row", "int": 7, "empty": {}, "key_null": {field: None},
            "key_int": {field: 7}, "key_list": {field: [HOST]}}[shape]


def _inventory_row(snap, host):
    hits = [r for r in ui.project_inventory(snap)["devices"]["rows"]["items"] if r["host"] == host]
    assert len(hits) == 1, (host, len(hits))
    return hits[0]


def _source_tree():
    return ast.parse(pathlib.Path(ui.__file__).read_text(encoding="utf-8"))


def _function(tree, name):
    hits = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(hits) == 1, name
    return hits[0]


def _returned_calls(fn, callee):
    """``{dict key: call}`` for each entry of `fn`'s returned dict literal whose value calls `callee`."""
    (ret,) = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    return {k.value: v for k, v in zip(ret.value.keys, ret.value.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Call) and getattr(v.func, "id", None) == callee}


def _key_field_joins():
    """Every ``_resolve(..., key_field=...)`` join in the projection, read from its source: ``{name in _joins:
    (list path, key field, norm)}``, and how many such joins the whole module makes."""
    tree = _source_tree()
    every = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_resolve"
                and any(k.arg == "key_field" for k in n.keywords))
    joins = {}
    for name, call in _returned_calls(_function(tree, "_joins"), "_resolve").items():
        kw = {k.arg: k.value for k in call.keywords}
        if "key_field" in kw:
            joins[name] = (ast.literal_eval(call.args[1]), ast.literal_eval(kw["key_field"]),
                           bool(ast.literal_eval(kw["norm"])) if "norm" in kw else False)
    return joins, every


def _selection_calls():
    """Every ``_selection_rows`` call on the device page, read from its source: ``{page key: (block, list path, key
    fields, multi)}``, and how many such calls the whole module makes."""
    tree = _source_tree()
    every = sum(1 for n in ast.walk(tree)
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_selection_rows")
    out = {}
    for key, call in _returned_calls(_function(tree, "_device_page"), "_selection_rows").items():
        kw = {k.arg: k.value for k in call.keywords}
        out[key] = (ast.literal_eval(call.args[3]), ast.literal_eval(call.args[4]), ast.literal_eval(call.args[5]),
                    bool(ast.literal_eval(kw["multi"])) if "multi" in kw else False)
    return out, every


KEY_FIELD_JOINS, N_KEY_FIELD_JOINS = _key_field_joins()
SELECTIONS, N_SELECTIONS = _selection_calls()


def test_the_class_is_read_from_the_source_and_covers_every_member():
    """Every key_field join lives in _joins, and every selection is a device-page entry, so the parametrized tests
    below reach each one. A join or selection added elsewhere fails here until it is held to the rule too."""
    assert KEY_FIELD_JOINS and len(KEY_FIELD_JOINS) == N_KEY_FIELD_JOINS, (KEY_FIELD_JOINS, N_KEY_FIELD_JOINS)
    assert SELECTIONS and len(SELECTIONS) == N_SELECTIONS, (sorted(SELECTIONS), N_SELECTIONS)
    # the enumeration is able to see what the page actually joins (a sanity floor, not the class itself)
    assert {"health", "lifecycle", "dossier", "collection"} <= set(KEY_FIELD_JOINS)
    assert {"links", "endpoints", "findings", "native_vlan_mismatches", "failure_impact",
            "structural_links"} <= set(SELECTIONS)
    # no selection can opt out of the rule: there is no parameter that would switch it off
    assert "strict" not in inspect.signature(ui._selection_rows).parameters


# --------------------------------------------------------------------------------------------------
# (a) every key_field join: a row it cannot read makes the join unverified, never a pick or an absence
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("name", sorted(KEY_FIELD_JOINS))
def test_a_row_the_key_join_cannot_read_makes_the_join_unverified(sample, doc_validator, name, shape):
    path, field, norm = KEY_FIELD_JOINS[name]
    clean = dict(_top_facts(_page(sample, HOST, doc_validator)[name], "/" + name))
    read = {w for w, f in clean.items() if f["state"] in (PUB, CBE)}
    assert read, (name, {w: f["state"] for w, f in clean.items()})          # the sample reads this join
    snap = copy.deepcopy(sample)
    rows = _at(snap, path)
    own = _naming(rows, HOST, field, norm)
    rows.append(_bad_row(shape, field))
    witness = (_ptr(*path, len(rows) - 1), "witness")
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)[name], "/" + name))
    for where in sorted(read):
        fact = facts[where]
        assert fact["state"] == UV, (name, shape, where, fact)
        assert "cannot be joined" in fact["reason"], (where, fact["reason"])
        assert witness in _refs(fact), (where, fact["refs"])
        assert {(_ptr(*path, i), "witness") for i in own} <= _refs(fact), where     # the row that does name it
        assert fact.get("value") is None, where
    # the inventory row withdraws its pointer to the joined row: never a pick
    row = _inventory_row(snap, HOST)
    assert row["rows"][name] is None
    if own:
        assert _inventory_row(sample, HOST)["rows"][name] == _ptr(*path, own[0])   # the control pointed at it


@pytest.mark.parametrize("name", sorted(KEY_FIELD_JOINS))
def test_a_device_whose_row_is_gone_is_unverified_not_absent_while_an_unreadable_row_remains(sample, doc_validator,
                                                                                             name):
    """Without the device's own row the join reads 'no row for this device' (an absence); beside a row it cannot
    read, that absence is not established, so the same facts are unverified, with a witness to that row."""
    path, field, norm = KEY_FIELD_JOINS[name]
    gone = copy.deepcopy(sample)
    rows = _at(gone, path)
    own = set(_naming(rows, HOST, field, norm))
    rows[:] = [r for i, r in enumerate(rows) if i not in own]
    absent = dict(_top_facts(_page(gone, HOST, doc_validator)[name], "/" + name))
    withheld = {w for w, f in absent.items() if f["state"] in (NC, CBE) and not w.endswith(HOST_INDEPENDENT)}
    assert withheld, name                                                      # the absence is read as such
    rows.append({field: None})
    facts = dict(_top_facts(_page(gone, HOST, doc_validator)[name], "/" + name))
    for where in sorted(withheld):
        assert facts[where]["state"] == UV, (name, where, facts[where])
        assert facts[where]["reason"] != absent[where]["reason"], where
        assert (_ptr(*path, len(rows) - 1), "witness") in _refs(facts[where]), where


def test_a_duplicate_beside_an_unreadable_row_names_both_doubts_and_every_candidate(sample, doc_validator):
    snap = copy.deepcopy(sample)
    rows = snap["health_scores"]
    (own,) = _naming(rows, HOST, "switch")
    rows.append(copy.deepcopy(rows[own]))
    rows.append({"switch": None, "band": "Excellent", "score": 100})
    dup, bad = len(rows) - 2, len(rows) - 1
    for fact in (_page(snap, HOST, doc_validator)["health"]["score"], _inventory_row(snap, HOST)["health_score"]):
        assert fact["state"] == UV and fact["value"] is None, fact
        assert "2 rows in health_scores name this key" in fact["reason"], fact["reason"]
        assert "1 row(s) in health_scores cannot be joined" in fact["reason"], fact["reason"]
        assert {(_ptr("health_scores", i), "witness") for i in (own, dup, bad)} <= _refs(fact)
    # the control: the duplicate alone keeps its own reason, with no unreadable-row doubt
    snap["health_scores"].pop()
    alone = _page(snap, HOST, doc_validator)["health"]["score"]
    assert alone["state"] == UV and "cannot be joined" not in alone["reason"]


# --------------------------------------------------------------------------------------------------
# (b) the device scope: an unreadable blind-spot row leaves no device value published or clean
# --------------------------------------------------------------------------------------------------
def _read_facts(page):
    return {w: f for w, f in _top_facts(page) if f["state"] in (PUB, CBE) and w not in FLEET_LEVEL}


def test_an_unjoinable_blind_spot_row_leaves_no_device_value_published_or_clean(sample, doc_validator):
    clean_page = _page(sample, HOST, doc_validator)
    read = _read_facts(clean_page)
    assert len(read) > 20 and any(f["state"] == CBE for f in read.values())   # published values and clean absences
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [copy.deepcopy(UNJOINABLE_CC)]
    # the owner passes over the row: its device scope does not call the device a blind spot
    assert ssot.abstention_reason(snap, "devices", device=HOST) == PUB
    page = _page(snap, HOST, doc_validator)
    facts = dict(_top_facts(page))
    witness = ("/collection_completeness/devices/0", "witness")
    for where in sorted(read):
        assert facts[where]["state"] == UV, (where, facts[where])
        assert witness in _refs(facts[where]), (where, facts[where]["refs"])
    assert not [w for w, f in facts.items() if f["state"] in (PUB, CBE) and w not in FLEET_LEVEL]
    for where in FLEET_LEVEL:
        assert facts[where] == dict(_top_facts(clean_page))[where]
    # the same device's inventory row
    clean_row = {w: f for w, f in _top_facts(_inventory_row(sample, HOST)) if f["state"] in (PUB, CBE)}
    assert clean_row
    row = dict(_top_facts(_inventory_row(snap, HOST)))
    for where in sorted(clean_row):
        assert row[where]["state"] == UV and witness in _refs(row[where]), (where, row[where])


def test_a_device_the_owner_calls_not_collected_stays_not_collected_beside_an_unreadable_row(sample, doc_validator):
    """The doubt qualifies only the owner's 'not a blind spot' answer: a device its scope calls not collected keeps
    that state on every value the scope governs. Its blind-spot record itself is a key join over a list holding a
    row it cannot read, so that record is unverified, with a witness to both rows."""
    read = _read_facts(_page(sample, HOST, doc_validator))
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [
        {"host": HOST, "status": "not collected", "data_quality": 0, "missing": list(ALL_ESSENTIAL)},
        copy.deepcopy(UNJOINABLE_CC)]
    assert ssot.abstention_reason(snap, "devices", device=HOST) == NC
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    for where in sorted(read):
        fact = facts[where]
        if where.startswith("/collection/"):
            assert fact["state"] == UV, (where, fact)
            assert {("/collection_completeness/devices/0", "witness"),
                    ("/collection_completeness/devices/1", "witness")} <= _refs(fact), where
        else:
            assert fact["state"] == NC, (where, fact)
            assert ("/collection_completeness/devices/0", "witness") in _refs(fact), where


def _real_blind_spots(tmp_path, captured):
    """``analyze.compute_collection_completeness`` over real capture files: `captured` maps each inventory host to
    the essential commands it returned."""
    acf = {}
    for n, (host, commands) in enumerate(captured.items()):
        folder = tmp_path / f"capture-{n}"
        folder.mkdir()
        acf[host] = {}
        for command in commands:
            path = folder / (command.replace(" ", "_") + ".txt")
            path.write_text("data\n", encoding="utf-8")
            acf[host][command] = str(path)
    return analyze.compute_collection_completeness(list(captured), acf)


def test_two_rows_the_owner_joins_to_one_device_never_attach_the_first_silently(sample, doc_validator, tmp_path):
    """The REAL producer writes one row per exact inventory host, so 'Core1' and 'core1' get a row each; the owner's
    device scope joins both to core1 (no case) and reads only the first, which is Core1's. core1's page must not
    take Core1's partial row as its own: every value it governs is unverified, with a witness to both rows."""
    cc = _real_blind_spots(tmp_path, {"Core1": ["show version"], "core1": ["show interface status"]})
    assert [(d["host"], d["status"]) for d in cc["devices"]] == [("Core1", "partial"), ("core1", "partial")]
    assert cc["devices"][0]["missing"] != cc["devices"][1]["missing"]          # two devices, two different gaps
    snap = copy.deepcopy(sample)
    snap["collection_completeness"] = cc
    assert ssot.abstention_reason(snap, "devices", device=HOST) == PUB        # the owner reads Core1's row
    read = _read_facts(_page(sample, HOST, doc_validator))
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    both = {("/collection_completeness/devices/0", "witness"), ("/collection_completeness/devices/1", "witness")}
    for where in sorted(read):
        assert facts[where]["state"] == UV, (where, facts[where])
        assert both <= _refs(facts[where]), (where, facts[where]["refs"])
    assert "2 collection_completeness rows name this device" in facts["/health/score"]["reason"]
    # no value reads Core1's missing captures as core1's own (the partial row is never picked)
    assert not [w for w, f in facts.items()
                if ("/collection_completeness/devices/0/missing", "witness") in _refs(f)]


@pytest.mark.parametrize("status", ["collected", 7, None, "MISSING"])
def test_a_blind_spot_row_whose_status_the_owner_cannot_read_is_never_read_as_collected(sample, doc_validator,
                                                                                        status):
    row = {"host": HOST, "data_quality": 50, "missing": ["switchport"]}
    if status != "MISSING":
        row["status"] = status
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [row]
    assert ssot.abstention_reason(snap, "devices", device=HOST) == PUB        # the owner reads it as collected
    read = _read_facts(_page(sample, HOST, doc_validator))
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    witness = ("/collection_completeness/devices/0" + ("" if status == "MISSING" else "/status"), "witness")
    for where in sorted(read):
        if where.startswith("/collection/"):
            continue                                       # the device's own blind-spot record: its cells say it
        assert facts[where]["state"] == UV, (where, facts[where])
        assert witness in _refs(facts[where]), (where, facts[where]["refs"])
    assert facts["/collection/status"]["state"] not in (PUB, CBE)       # its own status cell is no clean value either
    # the control: a readable partial row is read, and qualifies the published score with its missing list
    snap["collection_completeness"]["devices"] = [dict(row, status="partial")]
    score = _page(snap, HOST, doc_validator)["health"]["score"]
    assert score["state"] == PUB and "health_scored_over_partial_collection" in score["caveats"]
    assert ("/collection_completeness/devices/0/missing", "witness") in _refs(score)


def test_address_observations_of_a_doubted_host_are_unverified(sample, topology_validator):
    clean = _topology(sample, topology_validator)["source_addresses"]["items"]
    mine = [i for i, r in enumerate(clean) if r["host"]["state"] == PUB and r["host"]["value"] == HOST]
    assert mine and all(clean[i]["address"]["state"] == PUB for i in mine)
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [copy.deepcopy(UNJOINABLE_CC)]
    items = _topology(snap, topology_validator)["source_addresses"]["items"]
    assert [r["pointer"] for r in items] == [r["pointer"] for r in clean]      # every observation stays a row
    for i in mine:
        for field in ("host", "address", "interface"):
            fact = items[i][field]
            assert fact["state"] == UV, (i, field, fact)
            assert ("/collection_completeness/devices/0", "witness") in _refs(fact)


# --------------------------------------------------------------------------------------------------
# (c) the inventory universe and the fleet qualifier disclose a blind-spot row they cannot read
# --------------------------------------------------------------------------------------------------
def test_the_inventory_discloses_a_blind_spot_row_it_cannot_join(sample):
    witness = ("/collection_completeness/devices/0", "witness")
    control = copy.deepcopy(sample)
    control["collection_completeness"]["devices"] = [dict(UNJOINABLE_CC, host="ghost1")]
    control["collection_completeness"]["summary"]["inventory"] += 1
    inv = ui.project_inventory(control)["devices"]
    assert inv["rows"]["state"] == PUB and "ghost1" in [r["host"] for r in inv["rows"]["items"]]
    assert inv["total"]["state"] == PUB and inv["total"]["value"] == len(sample["devices"]) + 1
    snap = copy.deepcopy(control)
    snap["collection_completeness"]["devices"][0]["host"] = None              # the same blind spot, host unreadable
    inv = ui.project_inventory(snap)["devices"]
    assert sorted(r["host"] for r in inv["rows"]["items"]) == sorted(sample["devices"])   # rows still shown
    for fact in (inv["rows"], inv["total"]):
        assert fact["state"] == UV, fact
        assert witness in _refs(fact), fact["refs"]
    assert "cannot be joined by host" in inv["rows"]["reason"]


@pytest.mark.parametrize("bad", [None, "not a row", {"host": "x", "status": 7}, {"host": "x"}])
def test_a_blind_spot_row_that_cannot_be_read_qualifies_every_fleet_list(sample, payload_validator,
                                                                         topology_validator, bad):
    lists = (("findings", "rows"), ("findings", "total"), ("topology", "failure_impact"),
             ("topology", "structural_links"))
    clean = _payload(sample, payload_validator)
    for a, b in lists:
        assert "fleet_lists_exclude_blind_devices" not in clean[a][b].get("caveats", ()), (a, b)
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [copy.deepcopy(bad)]
    assert ui._Ctx(snap).blind_rows() == []                  # not a readable partial or not-collected row
    payload = _payload(snap, payload_validator)
    witness = ("/collection_completeness/devices/0", "witness")
    for a, b in lists:
        fact = payload[a][b]
        assert fact["state"] == PUB, (a, b, fact.get("reason"))
        assert "fleet_lists_exclude_blind_devices" in fact["caveats"] and witness in _refs(fact), (a, b)
    snap["failure_impact"], snap["link_centrality"] = [], []
    topology = _topology(snap, topology_validator)
    for key in ("failure_impact", "structural_links"):
        assert topology[key]["state"] == NC, (key, topology[key])
        assert "cannot be read as a partial or not-collected device" in topology[key]["reason"], key
        assert witness in _refs(topology[key]), key


def test_an_unknown_host_beside_an_unreadable_roster_row_is_unverified_not_absent(sample, doc_validator):
    host = "no-such-host"

    def check(snap, want, text):
        page = _page(snap, host, doc_validator)
        facts = list(_top_facts(page))
        assert len(facts) > 30
        for where, fact in facts:
            if where.endswith(HOST_INDEPENDENT):
                assert fact["state"] == NC and fact["refs"] == []
                continue
            assert fact["state"] == want and fact["refs"] == [], (where, fact)
            assert text in fact["reason"], (where, fact["reason"])

    check(sample, NC, "no roster in this snapshot names this device")        # the control
    for edit in (lambda s: s["collection_completeness"]["devices"].append(copy.deepcopy(UNJOINABLE_CC)),
                 lambda s: s["cable_map"]["nodes"].append({"host": None, "collected": False})):
        snap = copy.deepcopy(sample)
        edit(snap)
        check(snap, UV, "1 roster row(s) cannot be joined by host")


# --------------------------------------------------------------------------------------------------
# (d) every selection: a row its join cannot read keeps the device's rows and makes the selection unverified
# --------------------------------------------------------------------------------------------------
def _selection_bad_rows(fields, multi):
    """Rows the selection's join cannot read and which do not name HOST in any readable key, so the device's own rows
    are exactly the sample's."""
    rows = [None, {f: None for f in fields}]
    if multi:
        rows.append({f: ["not-this-device", 7] for f in fields})        # a key list holding anything but text
    return rows


@pytest.mark.parametrize("key", sorted(SELECTIONS))
def test_a_row_a_selection_cannot_read_never_vanishes_and_never_passes_silently(sample, doc_validator, key):
    _block, toks, fields, multi = SELECTIONS[key]
    clean = _page(sample, HOST, doc_validator)[key]
    assert clean["state"] == PUB and clean["items"], (key, clean.get("reason"))
    kept = [item["index"] if "index" in item else item for item in clean["items"]]
    for bad in _selection_bad_rows(fields, multi):
        snap = copy.deepcopy(sample)
        rows = _at(snap, toks)
        rows.append(copy.deepcopy(bad))
        sel = _page(snap, HOST, doc_validator)[key]
        assert sel["state"] == UV, (key, bad, sel)
        assert "cannot be joined" in sel["reason"], sel["reason"]
        assert (_ptr(*toks, len(rows) - 1), "witness") in _refs(sel), (key, bad)
        assert [item["index"] if "index" in item else item for item in sel["items"]] == kept, (key, bad)


def test_a_fleet_level_finding_naming_no_device_is_a_readable_row(sample, doc_validator):
    """A punch-list row whose devices list is empty names no device: it is read, not doubted."""
    assert any(isinstance(r, dict) and r.get("devices") == [] for r in sample["punchlist"])
    assert _page(sample, HOST, doc_validator)["findings"]["state"] == PUB


def test_an_nrfu_device_entry_the_host_join_cannot_read_is_witnessed(sample, doc_validator):
    clean = _page(sample, HOST, doc_validator)["nrfu_cases"]
    assert clean["state"] == PUB and clean["items"]
    for bad in (None, {"host": None, "cases": []}, {"cases": []}):
        snap = copy.deepcopy(sample)
        devices = snap["nrfu_commands"]["waves"][0]["devices"]
        devices.append(copy.deepcopy(bad))
        sel = _page(snap, HOST, doc_validator)["nrfu_cases"]
        assert sel["state"] == UV and "cannot be joined" in sel["reason"], (bad, sel)
        assert (_ptr("nrfu_commands", "waves", 0, "devices", len(devices) - 1), "witness") in _refs(sel)
        assert [it["pointer"] for it in sel["items"]] == [it["pointer"] for it in clean["items"]]


# --------------------------------------------------------------------------------------------------
# (e) the real stored data reads clean, and the scope is read through one door
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("source", [SAMPLE, GOLDEN], ids=["sample", "golden"])
def test_the_stored_snapshots_raise_no_doubt(source, doc_validator):
    """Both stored snapshots come from the real producers: no row of theirs is unreadable, so no device page doubts
    a join or its scope, and no value says it is unverified for that reason."""
    snap = json.loads(source.read_text(encoding="utf-8"))
    ctx = ui._Ctx(snap)
    hosts = sorted(snap["devices"])
    assert hosts
    for host in hosts:
        assert ctx.scope_doubt(host) is None, host
        page = _page(snap, host, doc_validator)
        for where, fact in _top_facts(page):
            reason = fact.get("reason") or ""
            for phrase in ("cannot be joined by exact key", "cannot be joined by host",
                           "whether collection_completeness lists this device"):
                assert phrase not in reason, (host, where, reason)


def test_the_device_scope_is_read_only_through_its_doubt_aware_door():
    """Every reader of the owner's device scope takes it from _Ctx.device_scope, which carries the doubt; the raw
    blind-spot answer and the first-match row are read nowhere else."""
    tree = _source_tree()
    callers = {}
    for scope in ast.walk(tree):
        if not isinstance(scope, ast.FunctionDef):
            continue
        for node in ast.walk(scope):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                callers.setdefault(node.func.attr, set()).add(scope.name)
    assert callers.get("device_blind") == {"device_scope"}, callers.get("device_blind")
    assert callers.get("cc_row") == {"partial_row", "cc_witness", "_device_page"}, callers.get("cc_row")
    assert "device_scope" in callers and len(callers["device_scope"]) >= 5, callers.get("device_scope")
