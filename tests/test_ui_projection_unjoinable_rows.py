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
  row they cannot read, with a witness, rather than passing over it;
* the blind-spot list itself is held to it: carried as something other than a list (or its section as something
  other than an object), its owner reads it as listing no blind spot, so every device value is ``unverified`` and
  every fleet list qualified, with a witness to that value; so it is (W51) when its phase failed (citing the failure
  record) or its summary counts a blind spot the list does not carry. A list the snapshot does not carry stays the
  abstention core's ``not_collected`` on the device's own record, but is never read as "no blind spot": every fleet
  list is qualified by it (the record's one coverage verdict, ``_Ctx.cc_coverage``);
* a forced device-page state (an unknown host) has a varying arity, so no reader unpacks it (W51);
* the topology joins are the same kind of join: the exact-hostname join over ``cable_map.nodes`` (a cable's ends, a
  failure-impact row, an address observation, a path hop), the host-pair join over ``cable_map.cables`` and the
  failure-impact neighbour bound's far-end join.

The class is read from the projection's own source, not from a list of call shapes: every exact-key join the module
makes through its one cached join index (``_Ctx.index`` / ``_Ctx.pairs``) must read the rows that join cannot read
(``_Ctx.unjoinable``, the only caller of ``_unjoinable_rows``) over the same list and key, or be a reviewed exemption
with its reason, and every function holding such a join names the behavioural test below that exercises it. A join
added later fails here until it is held to the rule and tested. Every value is checked against the real stored
sample (and the golden snapshot), and every withheld value is compared with the same page over the unedited sample,
which publishes it.
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


@pytest.fixture(scope="module")
def path_validator(schema):
    return Draft202012Validator({"$ref": "#/$defs/PathDocument", "$defs": schema["$defs"]})


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


def _resolves(snap, pointer):
    """Independent RFC 6901 resolution of `pointer` in `snap`."""
    cur = snap
    for raw in pointer.split("/")[1:]:
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return False
    return True


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


def _literal(node):
    """A literal argument, or the module constant a bare name argument refers to (e.g. ``_CC_ROWS``)."""
    if isinstance(node, ast.Name):
        return getattr(ui, node.id)
    return ast.literal_eval(node)


def _key_field_joins():
    """Every ``_resolve(..., key_field=...)`` join in the projection, read from its source: ``{name in _joins:
    (list path, key field, norm)}``, and how many such joins the whole module makes. A _joins member that delegates to
    a module helper (W51 round 4: the collection join's doubt-aware door, ``_collection_join``) is that helper's one
    key_field join, so the parametrized join tests below still reach it."""
    tree = _source_tree()
    every = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_resolve"
                and any(k.arg == "key_field" for k in n.keywords))
    (ret,) = [n for n in ast.walk(_function(tree, "_joins")) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    joins = {}
    for key, call in zip(ret.value.keys, ret.value.values):
        if not (isinstance(key, ast.Constant) and isinstance(call, ast.Call)):
            continue
        callee = getattr(call.func, "id", None)
        if callee != "_resolve":
            inner = [c for c in ast.walk(_function(tree, callee)) if isinstance(c, ast.Call)
                     and getattr(c.func, "id", None) == "_resolve" and any(k.arg == "key_field" for k in c.keywords)]
            assert len(inner) == 1, (key.value, callee, len(inner))     # a helper holds exactly one such join
            call = inner[0]
        kw = {k.arg: k.value for k in call.keywords}
        if "key_field" in kw:
            joins[key.value] = (_literal(call.args[1]), _literal(kw["key_field"]),
                                bool(_literal(kw["norm"])) if "norm" in kw else False)
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
#: W51: the key_field joins made outside _joins, each through _resolve (which holds the one rule itself) over the same
#: list and key as a _joins member, so the parametrized join test below exercises that very join: function -> (list
#: path, key field). G24's cross-layer deduction joins each named host to its health_scores row by "switch".
OTHER_KEY_FIELD_JOINS = {"_xl_deduction": (("health_scores",), "switch")}
SELECTIONS, N_SELECTIONS = _selection_calls()


def _calls_in_functions(tree):
    """``(innermost enclosing function name, call)`` for every call in the module (a lambda keeps its function)."""
    out = []

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                out.append((fn, child))
            visit(child, fn)

    visit(tree, "<module>")
    return out


def _callee(call):
    return getattr(call.func, "attr", None) or getattr(call.func, "id", None)


def _exact_key_joins():
    """Every exact-key join through the module's one cached join index (``_Ctx.index`` / ``_Ctx.pairs``), read from its
    source, as ``{(function, list path source, key fields source)}``, and the unjoinable-row reads
    (``_Ctx.unjoinable``) in the same form."""
    joins, reads = set(), set()
    for fn, call in _calls_in_functions(_source_tree()):
        if len(call.args) < 2 or not isinstance(call.func, ast.Attribute):
            continue
        key = (fn, ast.unparse(call.args[0]), ast.unparse(call.args[1]))
        if call.func.attr in ("index", "pairs"):
            joins.add(key)
        elif call.func.attr == "unjoinable":
            reads.add(key)
    return joins, reads


#: The exact-key joins that join no row to one device, endpoint or host pair, each with why the one rule does not
#: apply. A new join is not added here to quiet the census: it is held to the rule (read its unjoinable rows) unless
#: it is one of these kinds.
EXEMPT_JOINS = {
    ("cc_row", "('collection_completeness', 'devices')", "('host',)"):
        "the owner's own first-match row (ssot._device_not_collected), reproduced on purpose; it is read only through "
        "partial_row (behind scope_doubt), cc_witness (for a device the owner calls not collected) and the roster "
        "join (which reads the list's unjoinable rows itself)",
    ("_endpoint_rows", "stoks", "('ip',)"):
        "an endpoint's shared-IP selection, keyed by IP, not by device: a bare pointer list with no fact envelope "
        "that could carry a doubt (the VLAN-keyed selections' recorded residual)",
    ("_endpoint_rows", "dtoks", "('mac',)"):
        "an endpoint's dual-homed selection, keyed by MAC, not by device: a bare pointer list with no fact envelope "
        "that could carry a doubt (the VLAN-keyed selections' recorded residual)",
    ("_structural_dup", "('link_centrality',)", "_STRUCTURAL_HOSTS"):
        "a uniqueness check inside a fleet list that shows every row: a row it cannot read stays in that list, "
        "withheld by its own cells, and the device page's selection of the list follows the rule",
    ("impact", "('failure_impact',)", "('host',)"):
        "W33's failure-impact owner (impact_assessability.ImpactSnapshot) reads this index for its duplicate-host "
        "doubt, the uniqueness check inside a fleet list that shows every row: a row with no readable host stays in "
        "that list, withheld by the owner's own hold (impact_assessability.R_NO_HOST), and the device page's "
        "selection follows the rule (W51: this replaces the pre-W33 _impact_dup exemption)",
    ("_gateway_coverage", "ntoks", "('host',)"):
        "G16's fleet-wide gateway coverage census, which joins no row to one device: it asks whether each cable end "
        "names exactly one node. A node row the host join cannot read is itself counted as a coverage gap in the "
        "same function (an uncollected neighbour, with a witness), which withholds every sole-gateway risk and every "
        "empty gateway list it qualifies (tests/test_ui_projection_gateways.py, unreadable_node)",
}
#: Every function holding an exact-key join the rule governs -> the behavioural test in this module that exercises it.
JOIN_TESTS = {
    "_resolve": "test_a_row_the_key_join_cannot_read_makes_the_join_unverified",
    "_selection_rows": "test_a_row_a_selection_cannot_read_never_vanishes_and_never_passes_silently",
    "scope_doubt": "test_an_unjoinable_blind_spot_row_leaves_no_device_value_published_or_clean",
    "_cc_universe": "test_the_inventory_discloses_a_blind_spot_row_it_cannot_join",
    "_roster_join": "test_an_unknown_host_beside_an_unreadable_roster_row_is_unverified_not_absent",
    "_nrfu_block": "test_an_nrfu_device_entry_the_host_join_cannot_read_is_witnessed",
    "_topology_join": "test_a_cable_map_node_the_hostname_join_cannot_read_never_leaves_a_node_join_clean",
    "_topology_structural": "test_path_hop_nodes_and_host_pair_cables_follow_the_one_rule",
    "_impact_cable_source": "test_a_node_row_the_host_join_cannot_read_makes_every_neighbour_fail_closed",
    "_trust_inputs": "test_a_risk_register_row_the_trust_input_join_cannot_read_is_witnessed",
}


def test_the_class_is_read_from_the_source_and_covers_every_member():
    """Every key_field join lives in _joins, and every selection is a device-page entry, so the parametrized tests
    below reach each one. A join or selection added elsewhere fails here until it is held to the rule too."""
    assert KEY_FIELD_JOINS and len(KEY_FIELD_JOINS) + len(OTHER_KEY_FIELD_JOINS) == N_KEY_FIELD_JOINS, (
        KEY_FIELD_JOINS, OTHER_KEY_FIELD_JOINS, N_KEY_FIELD_JOINS)
    joined = {(toks, field) for toks, field, _norm in KEY_FIELD_JOINS.values()}
    for fn, (toks, field) in OTHER_KEY_FIELD_JOINS.items():
        made = [call for call in ast.walk(_function(_source_tree(), fn)) if isinstance(call, ast.Call)
                and getattr(call.func, "id", None) == "_resolve" and any(k.arg == "key_field" for k in call.keywords)]
        assert [(ast.literal_eval(c.args[1]), ast.literal_eval(next(k.value for k in c.keywords
                                                                   if k.arg == "key_field"))) for c in made] == [
            (toks, field)], (fn, made)
        assert (toks, field) in joined, (fn, toks, field)
    assert SELECTIONS and len(SELECTIONS) == N_SELECTIONS, (sorted(SELECTIONS), N_SELECTIONS)
    # the enumeration is able to see what the page actually joins (a sanity floor, not the class itself)
    assert {"health", "lifecycle", "dossier", "collection"} <= set(KEY_FIELD_JOINS)
    assert {"links", "endpoints", "findings", "native_vlan_mismatches", "failure_impact",
            "structural_links"} <= set(SELECTIONS)
    # no selection can opt out of the rule: there is no parameter that would switch it off
    assert "strict" not in inspect.signature(ui._selection_rows).parameters


def test_every_exact_key_join_reads_the_rows_it_cannot_join():
    """The class itself, not a list of call shapes: every exact-key join the module makes through its join index
    reads the rows that join cannot read, over the same list and key, in the same function -- or is a reviewed
    exemption -- and every function holding one names the behavioural test that exercises it here."""
    joins, reads = _exact_key_joins()
    unpaired = joins - reads
    assert unpaired == set(EXEMPT_JOINS), ("unpaired", sorted(unpaired - set(EXEMPT_JOINS)),
                                           "stale exemption", sorted(set(EXEMPT_JOINS) - unpaired))
    held = {fn for fn, _toks, _fields in joins - set(EXEMPT_JOINS)}
    assert held == set(JOIN_TESTS), ("untested", sorted(held - set(JOIN_TESTS)),
                                     "stale", sorted(set(JOIN_TESTS) - held))
    for fn, name in JOIN_TESTS.items():
        assert callable(globals().get(name)), (fn, name)
    # one predicate decides what a join cannot read: the cached _Ctx.unjoinable is its only caller
    callers = {fn for fn, call in _calls_in_functions(_source_tree()) if _callee(call) == "_unjoinable_rows"}
    assert callers == {"unjoinable"}, callers
    # the census sees the joins it is meant to see (a sanity floor, not the class itself)
    assert {"_resolve", "_selection_rows", "_topology_join", "_topology_structural", "_impact_cable_source",
            "_roster_join", "scope_doubt"} <= held


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
    """A host no readable roster names is the clean "no roster names this device" only while every roster can be read
    in full. Beside a roster row the join cannot read, or a roster carried as the wrong type, every fact on the page is
    unverified, with a witness to each such row or roster: the page names what leaves its absence open."""
    host = "no-such-host"
    n_nodes = len(sample["cable_map"]["nodes"])

    def check(snap, want, text, witness):
        page = _page(snap, host, doc_validator)
        facts = list(_top_facts(page))
        assert len(facts) > 30
        for where, fact in facts:
            if where.endswith(HOST_INDEPENDENT):
                assert fact["state"] == NC and fact["refs"] == []
                continue
            assert fact["state"] == want, (where, fact)
            assert text in fact["reason"], (where, fact["reason"])
            if witness:
                assert witness <= _refs(fact), (where, fact["refs"])
                for pointer, _role in _refs(fact):                    # every ref resolves in the snapshot
                    assert _resolves(snap, pointer), (where, pointer)
            else:
                assert fact["refs"] == [], (where, fact)

    check(sample, NC, "no roster in this snapshot names this device", set())        # the control: nothing to cite
    cases = (
        (lambda s: s["collection_completeness"]["devices"].append(copy.deepcopy(UNJOINABLE_CC)),
         "1 roster row(s) cannot be joined by host", "/collection_completeness/devices/0"),
        (lambda s: s["cable_map"]["nodes"].append({"host": None, "collected": False}),
         "1 roster row(s) cannot be joined by host", f"/cable_map/nodes/{n_nodes}"),
        (lambda s: s["collection_completeness"].__setitem__("devices", {host: {"status": "not collected"}}),
         "collection_completeness.devices is present but is not a list", "/collection_completeness/devices"),
        (lambda s: s.__setitem__("devices", sorted(s["devices"])),
         "devices is present but is not an object", "/devices"),
        (lambda s: s["cable_map"].__setitem__("nodes", "nodes"),
         "cable_map.nodes is present but is not a list", "/cable_map/nodes"),
    )
    for edit, text, pointer in cases:
        snap = copy.deepcopy(sample)
        edit(snap)
        check(snap, UV, text, {(pointer, "witness")})


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


def test_a_risk_register_row_the_trust_input_join_cannot_read_is_witnessed(sample):
    """W51 (F6 x G08): the analysis-input gap summary joins each inventory device to its one risk-register row by
    exact host. A register row that join cannot read could be any device's, so under every input the device list and
    its count are unverified and cite that row, never a published count or zero
    (tests/test_ui_projection_trust_inputs.py pins the full behaviour)."""
    snap = copy.deepcopy(sample)
    per_device = snap["device_dossiers"]["per_device"]
    per_device.append({k: v for k, v in copy.deepcopy(per_device[0]).items() if k != "host"})
    witness = (_ptr("device_dossiers", "per_device", len(per_device) - 1), "witness")
    rows = ui.project_trust(snap)["inputs"]
    assert rows
    for row in rows:
        assert row["hosts"]["state"] == UV and row["n"]["state"] == UV, (row["input"], row["hosts"]["state"])
        assert witness in _refs(row["hosts"]) and witness in _refs(row["n"]), row["input"]


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
    assert ctx.cc_unreadable() is None
    assert ctx.unjoinable(("cable_map", "nodes"), ("host",)) == []
    assert ctx.unjoinable(("cable_map", "cables"), ("a", "b")) == []
    for host in hosts:
        assert ctx.scope_doubt(host) is None, host
        page = _page(snap, host, doc_validator)
        for where, fact in _top_facts(page):
            reason = fact.get("reason") or ""
            for phrase in ("cannot be joined by exact key", "cannot be joined by host",
                           "cannot be joined by exact host", "whether collection_completeness lists this device",
                           "is present but is not"):
                assert phrase not in reason, (host, where, reason)


def test_the_real_producers_distinct_hosts_raise_no_scope_doubt(sample, doc_validator, tmp_path):
    """The stored shape the device scope reads, built by the REAL producer rather than left empty: one row per partial
    or uncollected inventory host, no two naming one device. No devices-map host is doubted, a partial device keeps
    its published score qualified by its own missing list, and a complete one is read as collected. (Both stored
    snapshots carry no blind spot at all, so the test above cannot fail by over-withholding.)"""
    essentials = [variants[0] for variants in analyze._ESSENTIAL_CMD_VARIANTS]
    captured = {host: list(essentials) for host in sorted(sample["devices"])}
    captured[HOST] = [c for c in essentials if c != "show version"]                # partial
    captured["access2"] = [c for c in essentials if c != "show interface status"]  # partial
    captured["Ghost-Edge"] = []                                                    # never reached
    cc = _real_blind_spots(tmp_path, captured)
    assert sorted((d["host"], d["status"]) for d in cc["devices"]) == [
        ("Ghost-Edge", "not collected"), ("access2", "partial"), (HOST, "partial")]
    snap = copy.deepcopy(sample)
    snap["collection_completeness"] = cc
    ctx = ui._Ctx(snap)
    for host in sorted(snap["devices"]):
        assert ctx.scope_doubt(host) is None, host
    own = next(i for i, d in enumerate(cc["devices"]) if d["host"] == HOST)
    score = _page(snap, HOST, doc_validator)["health"]["score"]
    assert score["state"] == PUB and "health_scored_over_partial_collection" in score["caveats"], score
    assert (_ptr("collection_completeness", "devices", own, "missing"), "witness") in _refs(score)
    complete =_page(snap, "access1", doc_validator)["health"]["score"]
    assert complete["state"] == PUB and "health_scored_over_partial_collection" not in complete.get("caveats", ())
    ghost = _page(snap, "Ghost-Edge", doc_validator)["health"]["score"]
    assert ghost["state"] == NC, ghost                         # the owner calls it not collected: a blind spot


def _cc_list_reads():
    """``{function}`` reading the blind-spot list itself: a join, an unjoinable-row read, a raw ``_get``, the
    unreadable-container check or a ``_resolve`` whose arguments name ``collection_completeness.devices``."""
    def names_list(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "_CC_ROWS":
                return True
            if (isinstance(sub, ast.Tuple) and len(sub.elts) >= 2
                    and all(isinstance(e, ast.Constant) for e in sub.elts[:2])
                    and [e.value for e in sub.elts[:2]] == ["collection_completeness", "devices"]):
                return True
        return False

    readers = ("index", "unjoinable", "pairs", "_get", "_unreadable_container", "_resolve", "_unjoinable_rows")
    return {fn for fn, call in _calls_in_functions(_source_tree()) if _callee(call) in readers
            and any(names_list(arg) for arg in list(call.args) + [k.value for k in call.keywords])}


#: Every function that reads the blind-spot list itself, with why it may: the device scope's own readers, and the
#: universes that disclose what they cannot read. Any other reader goes through device_scope (or blind_rows).
CC_LIST_READERS = {
    "scope_doubt": "the device scope's doubt: every row the owner's first-match key join passes over",
    "cc_unreadable": "whether the list can be read at all (the doubt's, the qualifier's and the inventory's witness)",
    "cc_row": "the owner's own first-match row, read only through partial_row, cc_witness and the roster join",
    "blind_rows": "the fleet qualifier's readable blind spots (fleet_blind_spot_rows)",
    "unread_blind_rows": "the fleet qualifier's rows it cannot read as a blind spot",
    "_cc_universe": "the inventory universe's one read of the list, which discloses the rows and lists it cannot "
                    "read (the inventory rows, their count, the trust inputs' denominator and the device facet)",
    "_roster_join": "the unknown-host roster check, which discloses the rows and lists it cannot read",
    "_collection_join": "the device's own blind-spot record (a _joins member since W51 round 4): a key_field join "
                        "held to the one rule inside _resolve, whose 'not a blind spot' absence is further held to the "
                        "device scope's own doubt (scope_doubt)",
}


def test_the_device_scope_is_read_only_through_its_doubt_aware_door():
    """Every reader of the owner's device scope takes it from _Ctx.device_scope, which carries the doubt; the raw
    blind-spot answer, the owner's device-scoped call and the first-match row are read nowhere else, and the list
    itself is read only by the reviewed readers above."""
    calls = _calls_in_functions(_source_tree())
    callers = {}
    for fn, call in calls:
        if isinstance(call.func, ast.Attribute):
            callers.setdefault(call.func.attr, set()).add(fn)
    assert callers.get("device_blind") == {"device_scope"}, callers.get("device_blind")
    assert callers.get("abst_dev") == {"device_blind"}, callers.get("abst_dev")
    assert callers.get("cc_row") == {"partial_row", "cc_witness", "_roster_join"}, callers.get("cc_row")
    assert "device_scope" in callers and len(callers["device_scope"]) >= 5, callers.get("device_scope")
    # the owner is asked a device-scoped question in exactly one place, whatever the call's spelling
    scoped = {fn for fn, call in calls if _callee(call) == "abstention_reason"
              and (len(call.args) > 2 or any(k.arg in ("device", None) for k in call.keywords))}
    assert scoped == {"abst_dev"}, scoped
    readers = _cc_list_reads()
    assert readers == set(CC_LIST_READERS), ("unreviewed", sorted(readers - set(CC_LIST_READERS)),
                                             "stale", sorted(set(CC_LIST_READERS) - readers))


# --------------------------------------------------------------------------------------------------
# (f) the topology joins: a node or cable row the join cannot read never leaves a join published or absent
# --------------------------------------------------------------------------------------------------
#: A cable-map node row the exact-hostname join cannot read; no producer writes one.
BAD_NODE = {"host": None, "kind": "switch", "collected": True}


def _node_joins(page, topology, host):
    """``{where: join}`` for every exact-hostname node join that names `host` on its device page and the fleet
    topology: a failure-impact row's nodes, a cable's or a structural link's end nodes, an address observation's
    nodes. Found from the projected rows' own published host values, never from the module's join."""
    out = {}
    for k, item in enumerate(page["failure_impact"]["items"]):
        out[f"/device/failure_impact/{k}/node_refs"] = item["node_refs"]
    for scope, rows in (("/device/structural_links", page["structural_links"]["items"]),
                        ("/topology/structural_links", topology["structural_links"]["items"]),
                        ("/topology/cables", topology["cables"]["items"])):
        for k, item in enumerate(rows):
            ends = item["ends"]["value"] or {}
            for side in ("a", "b"):
                if ends.get(side) == host or ends.get(side + "_host") == host:
                    out[f"{scope}/{k}/{side}_nodes"] = item[f"{side}_nodes"]
    for scope in ("failure_impact", "source_addresses"):
        for k, item in enumerate(topology[scope]["items"]):
            if item["host"]["state"] == PUB and item["host"]["value"] == host:
                out[f"/topology/{scope}/{k}/node_refs"] = item["node_refs"]
    return out


def _host_joins(snap, host, doc_validator, topology_validator):
    return _node_joins(_page(snap, host, doc_validator), _topology(snap, topology_validator), host)


def test_a_cable_map_node_the_hostname_join_cannot_read_never_leaves_a_node_join_clean(sample, doc_validator,
                                                                                      topology_validator):
    nodes = sample["cable_map"]["nodes"]
    (own,) = _naming(nodes, HOST, "host")
    own_witness = (_ptr("cable_map", "nodes", own), "witness")
    clean = _host_joins(sample, HOST, doc_validator, topology_validator)
    # the real sample joins core1's single node on every surface (published, never doubted)
    surfaces = {where.rsplit("/", 2)[0] for where in clean}
    assert {"/device/failure_impact", "/device/structural_links", "/topology/cables",
            "/topology/failure_impact", "/topology/source_addresses"} <= surfaces, sorted(surfaces)
    for where, join in clean.items():
        assert join["state"] == PUB and [it["index"] for it in join["items"]] == [own], (where, join)

    # 1. a node row the join cannot read beside core1's own: never a single node picked
    snap = copy.deepcopy(sample)
    snap["cable_map"]["nodes"].append(copy.deepcopy(BAD_NODE))
    bad = (_ptr("cable_map", "nodes", len(nodes)), "witness")
    edited = _host_joins(snap, HOST, doc_validator, topology_validator)
    assert set(edited) == set(clean)
    for where, join in edited.items():
        assert join["state"] == UV and "cannot be joined" in join["reason"], (where, join)
        assert {bad, own_witness} <= _refs(join), (where, join["refs"])
        assert join["items"] == clean[where]["items"], where          # the node that does carry the name stays

    # 2. core1's own node is gone: the clean absence, the control
    gone = copy.deepcopy(sample)
    del gone["cable_map"]["nodes"][own]
    absent = _host_joins(gone, HOST, doc_validator, topology_validator)
    assert set(absent) == set(clean)
    for where, join in absent.items():
        assert join["state"] == NC and "no cable-map node has this exact hostname" in join["reason"], (where, join)
        assert join["items"] == []

    # 3. core1's own node row with an unreadable host: it could be core1's, so the absence is not established
    unread = copy.deepcopy(sample)
    unread["cable_map"]["nodes"][own]["host"] = None
    for where, join in _host_joins(unread, HOST, doc_validator, topology_validator).items():
        assert join["state"] == UV and "cannot be joined" in join["reason"], (where, join)
        assert own_witness in _refs(join) and join["items"] == [], (where, join)


def _mini():
    """A two-node topology every projection surface reads: one switch (edge1, an SVI from its scoped running-config)
    cabled to an uncollected AP, its structural link and its failure-impact row (Info and zeros: an AP neighbour is
    edge gear, so it bounds nothing). The path 10.0.0.2 -> 192.0.2.1 is computed through edge1."""
    return {
        "schema": "collect_parse_snapshot/1",
        "devices": {"edge1": {}, "peer": {}},
        "interfaces": {"edge1": {"Vlan1": {"svi_ip": "10.0.0.1/24", "ip_mtu": 1500, "run_config_observed": True}},
                       "peer": {"Gi1": {}}},
        "routes": {"edge1": [
            {"prefix": "10.0.0.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan1"},
            {"prefix": "192.0.2.0/24", "source": "connected", "next_hop": "", "out_intf": "Vlan1"},
            {"prefix": "10.0.0.1/32", "source": "local", "next_hop": "", "out_intf": "Vlan1"}], "peer": []},
        "cable_map": {
            "nodes": [{"host": "edge1", "kind": "device", "role": "Core", "collected": True, "op_status": "up"},
                      {"host": "offscan", "kind": "ap", "role": "", "collected": False, "op_status": "unknown"}],
            "cables": [{"a": "edge1", "a_port": "Gi1", "b": "offscan", "b_port": "Gi0", "is_pc": False,
                        "members": [{"a_port": "Gi1", "b_port": "Gi0"}], "speed": "1000",
                        "confirmation": "One end (edge1)", "op_status": "up"}],
            "summary": {"n_nodes": 2, "n_cables": 1}},
        "link_centrality": [{"a_host": "edge1", "a_port": "Gi1", "b_host": "offscan", "b_port": "Gi0",
                             "betweenness": 321.5, "is_bridge": True, "pairs_cut": 3, "rank": 1}],
        "failure_impact": [{"host": "edge1", "severity": "Info", "vlans_impacted": 0, "stranded": 0,
                            "hard": 0, "backup": 0, "fhrp": 0, "off_scan_gw_vlans": 0, "blind_links": 0,
                            "detail": "No reachability impact from removing this switch (within the scan)."}],
    }


def _hop_nodes(snap, path_validator):
    doc = ui.project_path(snap, "10.0.0.2", "192.0.2.1")
    errors = sorted(path_validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    hops = doc["path"]["hop_evidence"]["items"]
    assert hops and hops[0]["hop_index"] == 0, doc["path"]["result"]
    return hops[0]["node_rows"]


def _pair_cables(snap, topology_validator):
    return _topology(snap, topology_validator)["structural_links"]["items"][0]["host_pair_cable_refs"]


def test_path_hop_nodes_and_host_pair_cables_follow_the_one_rule(path_validator, topology_validator):
    # the controls: one node carries the hop's host, one cable carries the link's host pair
    hop = _hop_nodes(_mini(), path_validator)
    assert hop["state"] == PUB and [it["index"] for it in hop["items"]] == [0], hop
    pair = _pair_cables(_mini(), topology_validator)
    assert pair["state"] == PUB and [it["index"] for it in pair["items"]] == [0], pair

    # a path hop's node join beside a node row it cannot read
    snap = _mini()
    snap["cable_map"]["nodes"].append(copy.deepcopy(BAD_NODE))
    hop = _hop_nodes(snap, path_validator)
    assert hop["state"] == UV and "cannot be joined" in hop["reason"], hop
    assert {("/cable_map/nodes/2", "witness"), ("/cable_map/nodes/0", "witness")} <= _refs(hop)
    assert [it["index"] for it in hop["items"]] == [0]

    # the host-pair join beside a cable row it cannot read
    for bad in (None, {"a": None, "b": "offscan"}, {"a": "edge1"}):
        snap = _mini()
        snap["cable_map"]["cables"].append(copy.deepcopy(bad))
        pair = _pair_cables(snap, topology_validator)
        assert pair["state"] == UV and "cannot be joined by exact host pair" in pair["reason"], (bad, pair)
        assert {("/cable_map/cables/1", "witness"), ("/cable_map/cables/0", "witness")} <= _refs(pair), bad
        assert [it["index"] for it in pair["items"]] == [0], bad

    # no cable carries the pair: the clean absence only while every cable row can be read
    snap = _mini()
    snap["cable_map"]["cables"][0]["b"] = "elsewhere"
    pair = _pair_cables(snap, topology_validator)
    assert pair["state"] == CBE and pair["items"] == [], pair
    snap["cable_map"]["cables"].append(None)
    pair = _pair_cables(snap, topology_validator)
    assert pair["state"] == UV and ("/cable_map/cables/1", "witness") in _refs(pair) and pair["items"] == [], pair


def test_a_node_row_the_host_join_cannot_read_makes_every_neighbour_fail_closed(topology_validator):
    """analyze.compute_failure_impact counts only endpoints on scanned switches, so a neighbour is passed over only
    when its far end joins exactly ONE node the cable map shows as collected or as edge gear. A node row the host join
    cannot read could be a second node for that far end, so beside one no neighbour is assumed collected: the row's
    Info, zeros and clean bill are withheld, citing the cable and the unreadable node row."""
    row = _topology(_mini(), topology_validator)["failure_impact"]["items"][0]
    for field in ("severity", "stranded", "detail"):
        assert row[field]["state"] == PUB, (field, row[field])          # the AP neighbour bounds nothing
    assert row["severity"]["value"] == "Info"
    snap = _mini()
    snap["cable_map"]["nodes"].append({"host": None, "kind": "switch", "collected": False})
    row = _topology(snap, topology_validator)["failure_impact"]["items"][0]
    for field in ("severity", "stranded", "detail"):
        fact = row[field]
        assert fact["state"] == NC and fact["value"] is None, (field, fact)
        assert "1 of them fail closed" in fact["reason"], (field, fact["reason"])
        assert {("/cable_map/cables/0", "witness"), ("/cable_map/nodes/2", "witness")} <= _refs(fact), field


# --------------------------------------------------------------------------------------------------
# (g) a blind-spot list that cannot be read at all: every device doubted, every fleet list qualified
# --------------------------------------------------------------------------------------------------
def _set_devices(value):
    return lambda s: s["collection_completeness"].__setitem__("devices", value)


def _set_section(value):
    return lambda s: s.__setitem__("collection_completeness", value)


_DEVICES_TEXT = "collection_completeness.devices is present but is not a list"
_SECTION_TEXT = "collection_completeness is present but is not an object"
#: A blind-spot list (or its section) carried as the wrong type, which ssot._as_list reads as listing no blind spot.
UNREADABLE_CC = {
    "devices_object": (_set_devices({HOST: {"status": "not collected"}}), "/collection_completeness/devices",
                       _DEVICES_TEXT),
    "devices_text": (_set_devices("not collected"), "/collection_completeness/devices", _DEVICES_TEXT),
    "devices_number": (_set_devices(7), "/collection_completeness/devices", _DEVICES_TEXT),
    "devices_false": (_set_devices(False), "/collection_completeness/devices", _DEVICES_TEXT),
    "section_list": (_set_section([{"host": HOST, "status": "not collected"}]), "/collection_completeness",
                     _SECTION_TEXT),
    "section_text": (_set_section("partial"), "/collection_completeness", _SECTION_TEXT),
}


@pytest.mark.parametrize("case", sorted(UNREADABLE_CC))
def test_a_blind_spot_list_that_cannot_be_read_doubts_every_device_and_qualifies_every_fleet_list(
        sample, doc_validator, payload_validator, topology_validator, case):
    edit, pointer, text = UNREADABLE_CC[case]
    witness = (pointer, "witness")
    read = _read_facts(_page(sample, HOST, doc_validator))
    clean_row = {w for w, f in _top_facts(_inventory_row(sample, HOST)) if f["state"] in (PUB, CBE)}
    assert len(read) > 20 and clean_row
    snap = copy.deepcopy(sample)
    edit(snap)
    # the owner reads the value as listing no blind spot, so its device scope calls core1 collected
    assert ssot.abstention_reason(snap, "devices", device=HOST) == PUB
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    for where in sorted(read):
        fact = facts[where]
        if where.startswith("/collection/"):                 # the device's own record cannot be read either
            assert fact["state"] not in (PUB, CBE), (where, fact)
            continue
        assert fact["state"] == UV, (where, fact)
        assert witness in _refs(fact) and text in fact["reason"], (where, fact)
    row = dict(_top_facts(_inventory_row(snap, HOST)))
    for where in sorted(clean_row):
        if where.startswith("/collection_status"):
            assert row[where]["state"] not in (PUB, CBE), (where, row[where])
            continue
        assert row[where]["state"] == UV and witness in _refs(row[where]), (where, row[where])
    # the inventory universe cannot list the blind spots it holds
    inv = ui.project_inventory(snap)["devices"]
    assert sorted(r["host"] for r in inv["rows"]["items"]) == sorted(sample["devices"])
    assert inv["rows"]["state"] == UV and witness in _refs(inv["rows"]) and text in inv["rows"]["reason"]
    assert inv["total"]["state"] != PUB, inv["total"]
    if case.startswith("devices_"):                          # the owner's count is readable: it cannot be reconciled
        assert inv["total"]["state"] == UV and witness in _refs(inv["total"]), inv["total"]
    # every fleet list is qualified, and an empty one is not_collected, never "nothing found"
    payload = _payload(snap, payload_validator)
    for a, b in (("findings", "rows"), ("findings", "total"), ("topology", "failure_impact"),
                 ("topology", "structural_links")):
        fact = payload[a][b]
        assert fact["state"] == PUB, (a, b, fact.get("reason"))
        assert "fleet_lists_exclude_blind_devices" in fact["caveats"] and witness in _refs(fact), (a, b)
    snap["failure_impact"], snap["link_centrality"] = [], []
    topology = _topology(snap, topology_validator)
    for key in ("failure_impact", "structural_links"):
        assert topology[key]["state"] == NC and text in topology[key]["reason"], (key, topology[key])
        assert witness in _refs(topology[key]), key


@pytest.mark.parametrize("case", ["section_missing", "section_null", "devices_missing", "devices_null"])
def test_a_blind_spot_list_the_snapshot_does_not_carry_is_never_read_as_no_blind_spot(
        sample, doc_validator, payload_validator, topology_validator, case):
    """W51 (F6 P2): a list (or section) the snapshot does not carry is the abstention core's not_collected on the
    device's own record, and no single device is doubted for it (each page's facts are its own evidence) -- but it is
    never read as "no blind spot" (ssot._as_list -> []): the blind-spot record's coverage verdict calls it absent, so
    every fleet list is qualified and an empty one is not_collected, never "nothing found". Before W51 the fleet lists
    published as if every inventory device had been collected."""
    snap = copy.deepcopy(sample)
    if case == "section_missing":
        del snap["collection_completeness"]
    elif case == "section_null":
        snap["collection_completeness"] = None
    elif case == "devices_missing":
        del snap["collection_completeness"]["devices"]
    else:
        snap["collection_completeness"]["devices"] = None
    ctx = ui._Ctx(snap)
    assert ctx.cc_unreadable() is None
    assert [gap.kind for gap in ctx.cc_coverage().gaps] == ["absent"]
    assert ctx.cc_coverage().state == NC
    for host in sorted(snap["devices"]):
        assert ctx.scope_doubt(host) is None, host
    page = _page(snap, HOST, doc_validator)
    assert page["collection"]["status"]["state"] == NC, page["collection"]["status"]
    assert page["health"]["score"]["state"] == PUB, page["health"]["score"]
    payload = _payload(snap, payload_validator)
    for a, b in (("findings", "rows"), ("findings", "total"), ("topology", "failure_impact"),
                 ("topology", "structural_links")):
        fact = payload[a][b]
        assert fact["state"] == PUB and "fleet_lists_exclude_blind_devices" in fact["caveats"], (case, a, b)
    snap["failure_impact"], snap["link_centrality"] = [], []
    topology = _topology(snap, topology_validator)
    for key in ("failure_impact", "structural_links"):
        assert topology[key]["state"] == NC, (case, key, topology[key])
        assert "collection_completeness cannot be read" in topology[key]["reason"], topology[key]["reason"]
        assert "not a clean result" in topology[key]["reason"], topology[key]["reason"]
    # the control: the stored, readable record lists no blind spot, so the same empty list is a measurement
    clean = copy.deepcopy(sample)
    clean["failure_impact"] = []
    assert _topology(clean, topology_validator)["failure_impact"]["state"] == CBE


def test_a_failed_blind_spot_record_doubts_every_device_and_always_cites_its_failure_record(
        sample, doc_validator, payload_validator):
    """W51 (F6 P2): a failed phase leaves the record's fallback (here the real _run_phase default, {}), which the
    owner's device scope reads as listing no blind spot (ssot._as_list -> []). Its coverage verdict is
    analysis_unavailable, so every device value the scope governs is unverified, and every one cites the failure
    record; every fleet list is qualified the same way. Before W51 every device read as collected."""
    read = _read_facts(_page(sample, HOST, doc_validator))
    snap = copy.deepcopy(sample)
    snap["collection_completeness"] = {}
    snap["assessment_integrity"] = {"failed_phases": ["Collection completeness"]}
    assert ssot.abstention_reason(snap, "devices", device=HOST) == PUB        # the owner reads it as collected
    ctx = ui._Ctx(snap)
    assert ctx.cc_coverage().state == AU and [gap.kind for gap in ctx.cc_coverage().gaps] == ["failed"]
    record = ("/assessment_integrity/failed_phases/0", "failure_record")
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    for where in sorted(read):
        fact = facts[where]
        if where.startswith("/collection/"):
            assert fact["state"] == AU, (where, fact)                          # the record's own cells
            continue
        assert fact["state"] == UV, (where, fact)
        assert "collection_completeness cannot be read (analysis unavailable" in fact["reason"], (where, fact)
        assert record in _refs(fact), (where, fact["refs"])
    payload = _payload(snap, payload_validator)
    fleet = payload["topology"]["failure_impact"]
    assert fleet["state"] == PUB and "fleet_lists_exclude_blind_devices" in fleet["caveats"]
    assert record in _refs(fleet)


def test_a_summary_that_counts_an_unlisted_blind_spot_doubts_every_device(sample, doc_validator):
    """W51 (F6 P2): the producer writes one devices row per partial or not-collected device and counts it in its
    summary, so a summary counting more than the list carries says a blind spot is missing from it, and it could be
    any device. Every device value the scope governs is unverified, citing the summary. A list carrying more rows
    than its summary counts over-reports and hides nothing (the control)."""
    read = _read_facts(_page(sample, HOST, doc_validator))
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["summary"]["not_collected"] = 2
    facts = dict(_top_facts(_page(snap, HOST, doc_validator)))
    witness = ("/collection_completeness/summary", "witness")
    for where in sorted(read):
        if where.startswith("/collection/"):
            continue
        assert facts[where]["state"] == UV, (where, facts[where])
        assert "summary counts 2 partial or not-collected device(s)" in facts[where]["reason"], where
        assert witness in _refs(facts[where]), where
    over = copy.deepcopy(sample)
    over["collection_completeness"]["devices"] = [
        {"host": "access2", "status": "partial", "data_quality": 75, "missing": ["switchport"]}]
    assert ui._Ctx(over).scope_doubt(HOST) is None
    assert _page(over, HOST, doc_validator)["health"]["score"]["state"] == PUB


def test_an_unknown_host_beside_an_unjoinable_blind_spot_row_renders_its_finding_rollup(sample, doc_validator):
    """W51 (F6 P1): a host no readable roster names, beside a roster row the host join cannot read, is forced to a
    three-element state (state, reason, witnesses). Every reader takes forced[0] and forced[1]; the finding rollup
    unpacked two and raised ValueError on every such page before W51."""
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"].append(copy.deepcopy(UNJOINABLE_CC))
    rosters, forced = ui._roster_join(ui._Ctx(snap), "no-such-host")
    assert not any(rosters.values()) and len(forced) == 3
    page = _page(snap, "no-such-host", doc_validator)
    witness = (_ptr("collection_completeness", "devices", len(snap["collection_completeness"]["devices"]) - 1),
               "witness")
    for key in ("worst", "by_severity"):
        fact = page["findings_rollup"][key]
        assert fact["state"] == UV and fact["value"] is None, (key, fact)
        assert witness in _refs(fact), (key, fact["refs"])


def _unpacked_names(node):
    """The names a ``Name`` target or a tuple/list unpacking binds."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [n for elt in node.elts for n in _unpacked_names(elt)]
    return []


def test_no_reader_unpacks_a_forced_state_or_the_roster_join():
    """W51 (F6 P1): the class, read from the source, not the one crashing line. A forced device-page state has a
    varying arity (two elements, or three beside a roster it cannot read), so no function may unpack a name `forced`
    into a tuple target (only forced[0], forced[1] and _forced_wit read it), and every call of _roster_join is
    unpacked into exactly its two results (rosters, forced)."""
    tree = _source_tree()
    unpacks, roster_calls = [], []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, (ast.Tuple, ast.List)) and isinstance(node.value, ast.Name)
                            and node.value.id == "forced"):
                        unpacks.append((fn.name, node.lineno))
                    if isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "_roster_join":
                        roster_calls.append((fn.name, len(_unpacked_names(target)) if isinstance(
                            target, (ast.Tuple, ast.List)) else 1))
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == "forced":
                unpacks.append((fn.name, node.lineno))
    assert unpacks == [], unpacks
    assert roster_calls and all(n == 2 for _fn, n in roster_calls), roster_calls
    # every function taking a forced state reads it only by index or through _forced_wit / a callee
    takers = [fn for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
              and any(a.arg == "forced" for a in fn.args.args + fn.args.kwonlyargs)]
    assert len(takers) >= 13, [fn.name for fn in takers]
