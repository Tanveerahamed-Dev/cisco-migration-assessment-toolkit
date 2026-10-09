"""Cross-layer correlations on the Findings screen (contract gap G24): stored rows, honest host joins, no recompute.

``findings.cross_layer`` is the engine's own ``cross_layer`` list (``analyze.compute_cross_layer_correlations``), in
its order, each row's id, severity, layers, title, detail and recommendation selected from the stored row. Each host
the row names is kept at its index and joined, by exact name, to:

* ``device`` -- the devices-map record of that name (its pointer). A blind spot is not collected; a name no record
  carries is unverified, never dropped;
* ``deduction_ref`` -- the one reference the device's ``health_scores`` row publishes to this cross-layer row
  (``analyze.compute_health_scores`` writes it beside the line item, inside the same eight-deduction prefix);
* ``deduction`` -- that line item, selected by the row's own ``<id> <severity>`` label, never paired by position.

A reference the scorer may have cut (its device's deductions reached eight) is not collected, never "no deduction".
A missing reference below the cut, a repeated or foreign reference, a missing line item, a repeated or blank host
are unverified with witnesses. The fleet's blind spots qualify the list, and a failed phase is analysis_unavailable.

Every expected value is read INDEPENDENTLY from the snapshot (or from the real scorer), never from the module's join.
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

from cisco_toolkit import analyze
from cisco_toolkit import ui_projection as ui
from cisco_toolkit.model import InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
PUB, CBE, NC, AU, UV, NA = ("published", "collected_but_empty", "not_collected", "analysis_unavailable",
                            "unverified", "not_assessed")
TEXT_FIELDS = ("id", "layers", "title", "detail", "recommendation")
JOINS = ("device", "deduction_ref", "deduction")


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator():
    schema = ui.ui_projection_schema()
    return Draft202012Validator({"$ref": "#/$defs/Findings", "$defs": schema["$defs"]})


def _cross_layer(snap, validator):
    """The Findings block, schema-validated and JSON-native, returning its cross-layer list."""
    findings = ui.project_findings(snap)
    errors = sorted(validator.iter_errors(findings), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    json.dumps(findings, allow_nan=False)
    return findings["cross_layer"]


def _ptr(*tokens):
    return "".join("/" + str(t).replace("~", "~0").replace("/", "~1") for t in tokens)


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


def _health_rows(snap, host):
    """Independent: the health_scores indices whose switch is exactly `host`."""
    return [i for i, r in enumerate(snap["health_scores"]) if isinstance(r, dict) and r.get("switch") == host]


def _label_lines(deductions, rule_id, severity):
    """Independent: the deductions written as '<id> <severity> (-<digits>)' for this rule and severity."""
    head = f"{rule_id} {severity} (-"
    return [n for n, text in enumerate(deductions)
            if text.startswith(head) and text.endswith(")") and text[len(head):-1].isascii()
            and text[len(head):-1].isdigit()]


def _host_item(xl, k, host):
    hits = [h for h in xl["items"][k]["hosts"]["items"] if h["host"]["value"] == host]
    assert len(hits) == 1, (k, host, len(hits))
    return hits[0]


def _row_naming(snap, host, rule_id=None):
    """Independent: the one stored cross-layer row naming `host` (and, if given, of that rule)."""
    rows = [k for k, r in enumerate(snap["cross_layer"])
            if host in r["hosts"] and (rule_id is None or r["id"] == rule_id)]
    assert len(rows) == 1, (host, rule_id, rows)
    return rows[0]


# --------------------------------------------------------------------------------------------------
# the closed schema, and the tables held against the producers
# --------------------------------------------------------------------------------------------------
def test_findings_schema_carries_the_cross_layer_rows():
    d = ui.ui_projection_schema()["$defs"]
    findings = d["Findings"]
    assert findings["additionalProperties"] is False
    # W51: the combined schema carries G21's facets and G24's cross_layer, in merge order
    assert findings["required"] == ["total", "headline_axis_index", "rows", "facets", "cross_layer"]
    assert findings["properties"]["cross_layer"] == {"$ref": "#/$defs/CrossLayerRowList"}
    row = d["CrossLayerRow"]
    assert row["additionalProperties"] is False and set(row["required"]) == set(row["properties"])
    assert {k: v for k, v in row["properties"].items() if k != "index"} == {
        "pointer": {"$ref": "#/$defs/Pointer"}, "id": {"$ref": "#/$defs/TextFact"},
        "severity": {"$ref": "#/$defs/SeverityFact"}, "layers": {"$ref": "#/$defs/TextFact"},
        "title": {"$ref": "#/$defs/TextFact"}, "detail": {"$ref": "#/$defs/TextFact"},
        "recommendation": {"$ref": "#/$defs/TextFact"}, "hosts": {"$ref": "#/$defs/CrossLayerHostRowList"}}
    host = d["CrossLayerHostRow"]
    assert host["additionalProperties"] is False and set(host["required"]) == set(host["properties"])
    assert {k: v for k, v in host["properties"].items() if k != "index"} == {
        "pointer": {"$ref": "#/$defs/Pointer"}, "host": {"$ref": "#/$defs/TextFact"},
        "device": {"$ref": "#/$defs/PointerFact"}, "deduction_ref": {"$ref": "#/$defs/EvidenceRefFact"},
        "deduction": {"$ref": "#/$defs/TextFact"}}
    published, withheld = d["PointerFact"]["oneOf"]
    assert published["properties"]["value"] == {"$ref": "#/$defs/Pointer"}
    assert withheld["properties"]["value"] == {"type": "null"}
    for name in ("CrossLayerRowList", "CrossLayerHostRowList"):
        pub, _wh = d[name]["oneOf"]
        assert pub["properties"]["items"]["minItems"] == 1, name           # a published list is never empty
    # no new closed vocabulary: severity reuses the punch-list severities (ranked by the G43 block)
    assert d["SeverityFact"]["oneOf"][0]["properties"]["value"]["enum"] == list(ui.SEVERITIES)
    payload = {lim["id"]: lim["applies_to"] for lim in ui.LIMITATIONS}
    for lid in ("one_hop_failure_attribution", "fleet_lists_exclude_blind_devices", "row_selection_by_exact_key",
                "engine_list_capped", "projection_owned_verdicts"):
        assert "/findings/cross_layer" in payload[lid], lid


def test_inputs_vocabulary_and_row_shape_are_the_producers():
    params = ["interfaces" if p == "all_interfaces" else p
              for p in inspect.signature(analyze.build_dependency_map).parameters]
    assert tuple(params) == ui.CROSS_LAYER_INPUTS
    assert list(inspect.signature(analyze.compute_cross_layer_correlations).parameters) == ["dep"]
    assert set(analyze._CL_RANK) == set(ui.SEVERITIES)
    tree = ast.parse(textwrap.dedent(inspect.getsource(analyze.compute_cross_layer_correlations)))
    adds = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "add"]
    assert len(adds) == 1
    stored = [n for n in ast.walk(adds[0]) if isinstance(n, ast.Dict)]
    keys = {k.value for d in stored for k in d.keys if isinstance(k, ast.Constant)}
    assert set(TEXT_FIELDS) | {"severity", "hosts"} <= keys
    hosts = [v for d in stored for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and k.value == "hosts"]
    assert [ast.unparse(v) for v in hosts] == ["sorted(set(hosts or []))"]      # each host once: a repeat is a doubt
    def arms(node):
        """The string values a severity expression can take: a literal, or each arm of a conditional."""
        if isinstance(node, ast.IfExp):
            return arms(node.body) | arms(node.orelse)
        assert isinstance(node, ast.Constant) and isinstance(node.value, str), ast.dump(node)
        return {node.value}

    severities, by_name = set(), False
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "add":
            arg = call.args[1]
            if isinstance(arg, ast.Name):
                assert arg.id == "sev", ast.dump(arg)
                by_name = True
            else:
                severities |= arms(arg)
    if by_name:
        bound = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "sev" for t in node.targets)]
        assert bound
        for value in bound:
            severities |= arms(value)
    assert {"Critical", "High", "Medium"} <= severities <= set(ui.SEVERITIES), severities


# --------------------------------------------------------------------------------------------------
# the real stored sample and golden: every row, every host, every join published from the stored values
# --------------------------------------------------------------------------------------------------
def test_sample_rows_are_the_stored_rows_in_producer_order(sample, validator):
    xl = _cross_layer(sample, validator)
    stored = sample["cross_layer"]
    assert stored and xl["state"] == PUB and xl["subject"] == "/cross_layer"
    assert xl["basis"] == "analyze.compute_cross_layer_correlations:cross_layer"
    assert "fleet_lists_exclude_blind_devices" not in xl.get("caveats", ())     # the sample has no blind spot
    assert [it["index"] for it in xl["items"]] == list(range(len(stored)))
    for k, (item, src) in enumerate(zip(xl["items"], stored)):
        assert item["pointer"] == f"/cross_layer/{k}"
        for field in TEXT_FIELDS + ("severity",):
            fact = item[field]
            assert fact["state"] == PUB and fact["value"] == src[field], (k, field, fact)
            assert fact["subject"] == f"/cross_layer/{k}/{field}"
        hosts = item["hosts"]
        assert hosts["state"] == PUB and hosts["subject"] == f"/cross_layer/{k}/hosts"
        assert "row_selection_by_exact_key" in hosts["caveats"]
        assert [h["index"] for h in hosts["items"]] == list(range(len(src["hosts"])))
        assert [h["pointer"] for h in hosts["items"]] == [f"/cross_layer/{k}/hosts/{j}" for j in range(len(src["hosts"]))]
        assert [h["host"]["value"] for h in hosts["items"]] == src["hosts"]


def _assert_every_join_published(snap, xl):
    """Independent lookups for every (row, host): the devices record, the one reference, the one line item."""
    weights = analyze.ScoringConfig().xl_weights
    n = 0
    for k, item in enumerate(xl["items"]):
        src = snap["cross_layer"][k]
        for j, h in enumerate(item["hosts"]["items"]):
            host = src["hosts"][j]
            assert host in snap["devices"], host
            assert h["device"]["state"] == PUB and h["device"]["value"] == _ptr("devices", host), (k, host)
            assert {(_ptr("devices", host), "witness"), (f"/cross_layer/{k}/hosts/{j}", "witness")} <= _refs(h["device"])
            rows = _health_rows(snap, host)
            assert len(rows) == 1, host
            hr = snap["health_scores"][rows[0]]
            refs = [m for m, r in enumerate(hr["deduction_refs"]) if r["ref"] == f"/cross_layer/{k}"]
            assert len(refs) == 1, (k, host)
            ref = h["deduction_ref"]
            assert ref["state"] == PUB, (k, host, ref.get("reason"))
            assert ref["subject"] == f"/health_scores/{rows[0]}/deduction_refs/{refs[0]}"
            assert ref["value"] == hr["deduction_refs"][refs[0]]
            assert ref["value"]["host"] == host and ref["value"]["kind"] == "analysis_row"
            lines = _label_lines(hr["deductions"], src["id"], src["severity"])
            assert len(lines) == 1, (k, host, hr["deductions"])
            line = h["deduction"]
            assert line["state"] == PUB, (k, host, line.get("reason"))
            assert line["subject"] == f"/health_scores/{rows[0]}/deductions/{lines[0]}"
            # the line item is the scorer's own cross-layer weight for this severity, as it published it
            assert line["value"] == hr["deductions"][lines[0]] == (
                f"{src['id']} {src['severity']} (-{weights[src['severity']]})")
            assert "row_selection_by_exact_key" in line["caveats"]
            assert (ref["subject"], "witness") in _refs(line)
            n += 1
    return n


def test_sample_hosts_join_their_device_and_the_deduction_each_row_drives(sample, validator):
    xl = _cross_layer(sample, validator)
    n = _assert_every_join_published(sample, xl)
    assert n == sum(len(r["hosts"]) for r in sample["cross_layer"]) and n > 40
    # both sides of the cut are exercised: hosts whose eight deductions reached the cut, and hosts below it
    lens = {len(sample["health_scores"][_health_rows(sample, h)[0]]["deductions"])
            for r in sample["cross_layer"] for h in r["hosts"]}
    assert 8 in lens and min(lens) < 8, lens


def test_the_device_page_reaches_each_row_by_its_exact_pointer(sample, validator):
    """The device page's health references to cross-layer rows are the Findings rows' own pointers (a key join)."""
    xl = _cross_layer(sample, validator)
    by_pointer = {it["pointer"]: it for it in xl["items"]}
    seen = 0
    for host in ("core1", "access13", "dist1"):
        page = ui.project_device(sample, host)["device"]
        for ref in page["health"]["deduction_refs"]["items"]:
            target = ref["fact"]["value"]["ref"]
            if target.startswith("/cross_layer/"):
                row = by_pointer[target]
                assert host in [h["host"]["value"] for h in row["hosts"]["items"]], (host, target)
                assert _host_item(xl, row["index"], host)["deduction_ref"]["value"] == ref["fact"]["value"]
                seen += 1
    assert seen >= 5


def test_golden_rows_publish_every_join(validator):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    xl = _cross_layer(golden, validator)
    assert xl["state"] == PUB and len(xl["items"]) == len(golden["cross_layer"]) > 0
    assert _assert_every_join_published(golden, xl) == sum(len(r["hosts"]) for r in golden["cross_layer"])


# --------------------------------------------------------------------------------------------------
# the real scorer: the line item's label, two rows of one rule, and the eight-deduction cut
# --------------------------------------------------------------------------------------------------
def _cl_row(rule_id, severity, hosts, note=""):
    """A row in the producer's stored shape (analyze.compute_cross_layer_correlations' add())."""
    return {"id": rule_id, "severity": severity, "layers": "L2+L3", "title": f"{rule_id} synthetic {note}".strip(),
            "detail": f"synthetic detail {note}".strip(), "recommendation": "synthetic recommendation",
            "hosts": sorted(set(hosts)), "evidence_refs": []}


def _scored(cross_layer, host="sw1", data_quality=None):
    """The REAL scorer over one switch the rows name, and the stored snapshot around it."""
    ifaces = {host: {"Gi1/0/1": InterfaceData(port="Gi1/0/1", status="connected", switchport_mode="Access",
                                              vlan="10")}}
    health = analyze.compute_health_scores(ifaces, [], [], cross_layer, [], data_quality=data_quality)
    return {"schema": "collect_parse_snapshot/1", "devices": {host: {"hostname": host}},
            "interfaces": {host: {"Gi1/0/1": {"port": "Gi1/0/1", "status": "connected"}}},
            "physical_health": [], "l3_forwarding": [], "health_scores": health,
            "cross_layer": copy.deepcopy(cross_layer)}


def test_the_line_item_label_is_the_real_scorers(validator):
    rows = [_cl_row("CL-01", "Critical", ["sw1"]), _cl_row("CL-03", "High", ["sw1"]), _cl_row("CL-10", "Medium", ["sw1"])]
    snap = _scored(rows)
    hr = snap["health_scores"][0]
    weights = analyze.ScoringConfig().xl_weights
    assert sorted(hr["deductions"]) == sorted(f"{r['id']} {r['severity']} (-{weights[r['severity']]})" for r in rows)
    assert hr["band"] != ui.HEALTH_BAND_NOT_SCORED
    xl = _cross_layer(snap, validator)
    assert xl["state"] == PUB and len(xl["items"]) == 3
    assert _assert_every_join_published(snap, xl) == 3


def test_two_rows_of_one_rule_on_one_device_share_one_line_item_and_keep_their_own_references(validator):
    rows = [_cl_row("CL-03", "High", ["sw1"], "VLAN 10"), _cl_row("CL-03", "High", ["sw1"], "VLAN 30")]
    snap = _scored(rows)
    hr = snap["health_scores"][0]
    assert hr["deductions"] == ["CL-03 High (-10)", "CL-03 High (-10)"]          # the scorer's own line items
    xl = _cross_layer(snap, validator)
    subjects = set()
    for k in (0, 1):
        h = _host_item(xl, k, "sw1")
        ref, line = h["deduction_ref"], h["deduction"]
        assert ref["state"] == PUB and ref["value"]["ref"] == f"/cross_layer/{k}"
        subjects.add(ref["subject"])
        # the value is determined; which position is this row's is not published, so no subject is claimed
        assert line["state"] == PUB and line["value"] == "CL-03 High (-10)" and line["subject"] is None
        assert {("/health_scores/0/deductions/0", "witness"), ("/health_scores/0/deductions/1", "witness"),
                (ref["subject"], "witness")} <= _refs(line)
    assert len(subjects) == 2                                                      # never picked between


def test_a_row_the_scorer_cut_is_not_collected_never_no_deduction(validator):
    rows = [_cl_row(f"CL-{n:02d}", "High", ["sw1"]) for n in range(1, 10)]      # nine rows, one device
    snap = _scored(rows)
    hr = snap["health_scores"][0]
    assert len(hr["deductions"]) == len(hr["deduction_refs"]) == 8              # the scorer's own [:8]
    cut = [k for k in range(len(rows)) if all(r["ref"] != f"/cross_layer/{k}" for r in hr["deduction_refs"])]
    assert len(cut) == 1
    xl = _cross_layer(snap, validator)
    for k in range(len(rows)):
        h = _host_item(xl, k, "sw1")
        assert h["device"]["state"] == PUB
        for name in ("deduction_ref", "deduction"):
            fact = h[name]
            if k in cut:
                assert fact["state"] == NC and fact["value"] is None, (k, name, fact)
                assert "after 8" in fact["reason"] and "beyond the cut" in fact["reason"]
                assert "engine_list_capped" in fact["caveats"]
                assert ("/health_scores/0/deductions", "witness") in _refs(fact)
            else:
                assert fact["state"] == PUB, (k, name, fact.get("reason"))


def test_an_unscored_device_withholds_its_deduction_as_not_assessed(validator):
    rows = [_cl_row("CL-03", "High", ["sw1"])]
    snap = _scored(rows, data_quality={})                    # never measured: the scorer bands it Insufficient Data
    assert snap["health_scores"][0]["band"] == ui.HEALTH_BAND_NOT_SCORED
    h = _host_item(_cross_layer(snap, validator), 0, "sw1")
    assert h["device"]["state"] == PUB
    for name in ("deduction_ref", "deduction"):
        assert h[name]["state"] == NA and "Insufficient Data" in h[name]["reason"], h[name]


# --------------------------------------------------------------------------------------------------
# contradictions with the producers are unverified, with witnesses; nothing is dropped or picked
# --------------------------------------------------------------------------------------------------
def test_a_missing_reference_is_not_collected_at_the_cut_and_unverified_below_it(sample, validator):
    snap = copy.deepcopy(sample)
    k = _row_naming(snap, "core1", "CL-01")
    i = _health_rows(snap, "core1")[0]
    assert len(snap["health_scores"][i]["deductions"]) == 8                        # at the scorer's cut
    snap["health_scores"][i]["deduction_refs"] = [r for r in snap["health_scores"][i]["deduction_refs"]
                                                  if r["ref"] != f"/cross_layer/{k}"]
    low = next(h for h in ("dist1", "dist2", "core2", "podacc1", "podacc2")
               if len(snap["health_scores"][_health_rows(snap, h)[0]]["deductions"]) < 8)
    k2 = _row_naming(snap, low)
    i2 = _health_rows(snap, low)[0]
    snap["health_scores"][i2]["deduction_refs"] = [r for r in snap["health_scores"][i2]["deduction_refs"]
                                                   if r["ref"] != f"/cross_layer/{k2}"]
    xl = _cross_layer(snap, validator)
    at_cut = _host_item(xl, k, "core1")
    below = _host_item(xl, k2, low)
    for name in ("deduction_ref", "deduction"):
        assert at_cut[name]["state"] == NC and "beyond the cut" in at_cut[name]["reason"], at_cut[name]
        assert "engine_list_capped" in at_cut[name]["caveats"]
        assert below[name]["state"] == UV and "stop short of the scorer's cut of 8" in below[name]["reason"]
        assert (f"/health_scores/{i2}/deduction_refs", "witness") in _refs(below[name])
        assert (f"/cross_layer/{k2}/hosts/0", "witness") in _refs(below[name])
    assert at_cut["device"]["state"] == below["device"]["state"] == PUB
    # every other host of the core1 row keeps its published deduction
    others = [h for h in xl["items"][k]["hosts"]["items"] if h["host"]["value"] != "core1"]
    assert others and all(h["deduction_ref"]["state"] == PUB for h in others)


def test_a_repeated_or_foreign_reference_is_unverified(sample, validator):
    k = _row_naming(sample, "core1", "CL-01")
    i = _health_rows(sample, "core1")[0]
    refs = sample["health_scores"][i]["deduction_refs"]
    m = next(n for n, r in enumerate(refs) if r["ref"] == f"/cross_layer/{k}")
    other = next(n for n, r in enumerate(refs) if not r["ref"].startswith("/cross_layer/"))
    repeated = copy.deepcopy(sample)
    repeated["health_scores"][i]["deduction_refs"][other] = copy.deepcopy(refs[m])
    h = _host_item(_cross_layer(repeated, validator), k, "core1")
    for name in ("deduction_ref", "deduction"):
        assert h[name]["state"] == UV and "2 deduction references" in h[name]["reason"], h[name]
        assert {(f"/health_scores/{i}/deduction_refs/{m}", "witness"),
                (f"/health_scores/{i}/deduction_refs/{other}", "witness")} <= _refs(h[name])
    for change in ({"kind": "device_fact"}, {"role": "subject"}, {"host": None}):
        foreign = copy.deepcopy(sample)
        foreign["health_scores"][i]["deduction_refs"][m].update(change)
        h = _host_item(_cross_layer(foreign, validator), k, "core1")
        for name in ("deduction_ref", "deduction"):
            assert h[name]["state"] == UV and "not the scorer's analysis-row reference" in h[name]["reason"], change
            assert (f"/health_scores/{i}/deduction_refs/{m}", "witness") in _refs(h[name])


def test_a_missing_or_conflicting_line_item_is_unverified_and_identical_ones_publish_once(sample, validator):
    k = _row_naming(sample, "core1", "CL-01")
    i = _health_rows(sample, "core1")[0]
    deductions = sample["health_scores"][i]["deductions"]
    mine = _label_lines(deductions, "CL-01", "Critical")
    assert len(mine) == 1
    other = next(n for n, text in enumerate(deductions) if not text.startswith("CL-01 Critical"))
    gone = copy.deepcopy(sample)
    gone["health_scores"][i]["deductions"][mine[0]] += " "                  # no longer the scorer's line item
    h = _host_item(_cross_layer(gone, validator), k, "core1")
    assert h["deduction_ref"]["state"] == PUB                               # the reference itself still stands
    assert h["deduction"]["state"] == UV and "no published deduction carries" in h["deduction"]["reason"]
    assert (f"/health_scores/{i}/deductions", "witness") in _refs(h["deduction"])
    conflict = copy.deepcopy(sample)
    conflict["health_scores"][i]["deductions"][other] = "CL-01 Critical (-17)"
    h = _host_item(_cross_layer(conflict, validator), k, "core1")
    assert h["deduction"]["state"] == UV and "different points" in h["deduction"]["reason"]
    assert {(f"/health_scores/{i}/deductions/{mine[0]}", "witness"),
            (f"/health_scores/{i}/deductions/{other}", "witness")} <= _refs(h["deduction"])
    same = copy.deepcopy(sample)
    same["health_scores"][i]["deductions"][other] = deductions[mine[0]]
    h = _host_item(_cross_layer(same, validator), k, "core1")
    assert h["deduction"]["state"] == PUB and h["deduction"]["value"] == deductions[mine[0]]
    assert h["deduction"]["subject"] is None
    assert {(f"/health_scores/{i}/deductions/{mine[0]}", "witness"),
            (f"/health_scores/{i}/deductions/{other}", "witness")} <= _refs(h["deduction"])


@pytest.mark.parametrize("bad, why", [("ghost-x", "joins no collected device"), ("", "blank"), (7, "type check")])
def test_an_unjoinable_host_is_unverified_and_kept(sample, validator, bad, why):
    snap = copy.deepcopy(sample)
    k = _row_naming(snap, "core1", "CL-01")
    snap["cross_layer"][k]["hosts"].append(bad)
    j = len(snap["cross_layer"][k]["hosts"]) - 1
    xl = _cross_layer(snap, validator)
    hosts = xl["items"][k]["hosts"]
    assert hosts["state"] == PUB and len(hosts["items"]) == j + 1                # kept at its index, never dropped
    item = hosts["items"][j]
    assert item["pointer"] == f"/cross_layer/{k}/hosts/{j}"
    if bad == "ghost-x":
        assert item["host"]["state"] == PUB and item["host"]["value"] == bad
        assert item["device"]["state"] == UV and why in item["device"]["reason"]
        assert (f"/cross_layer/{k}/hosts/{j}", "witness") in _refs(item["device"])
        for name in ("deduction_ref", "deduction"):
            assert item[name]["state"] == UV and "health_scores has no row" in item[name]["reason"]
    else:
        assert item["host"]["state"] == UV and why in item["host"]["reason"]
        for name in JOINS:
            assert item[name]["state"] == UV and item[name]["reason"] == item["host"]["reason"]
            assert item[name]["refs"] == item["host"]["refs"]
    for h in hosts["items"][:j]:                                               # the stored hosts keep their joins
        assert all(h[name]["state"] == PUB for name in JOINS)


def test_a_repeated_host_is_unverified_with_a_witness_to_each_entry(sample, validator):
    snap = copy.deepcopy(sample)
    k = _row_naming(snap, "core1", "CL-01")
    j = snap["cross_layer"][k]["hosts"].index("core1")
    snap["cross_layer"][k]["hosts"].append("core1")
    last = len(snap["cross_layer"][k]["hosts"]) - 1
    items = _cross_layer(snap, validator)["items"][k]["hosts"]["items"]
    for n in (j, last):
        host = items[n]["host"]
        assert host["state"] == UV and "names this host 2 times" in host["reason"], host
        assert {(f"/cross_layer/{k}/hosts/{j}", "witness"), (f"/cross_layer/{k}/hosts/{last}", "witness")} <= _refs(host)
        assert all(items[n][name]["state"] == UV for name in JOINS)
    assert all(h["host"]["state"] == PUB for n, h in enumerate(items) if n not in (j, last))


# --------------------------------------------------------------------------------------------------
# blind spots, failed phases and absence: never a clean "no correlation"
# --------------------------------------------------------------------------------------------------
def test_blind_spots_qualify_the_list_and_a_blind_host_is_not_collected(sample, validator):
    snap = copy.deepcopy(sample)
    snap["collection_completeness"]["devices"] = [
        {"host": "core1", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]}]
    xl = _cross_layer(snap, validator)
    assert xl["state"] == PUB and "fleet_lists_exclude_blind_devices" in xl["caveats"]
    assert ("/collection_completeness/devices/0", "witness") in _refs(xl)
    h = _host_item(xl, _row_naming(snap, "core1", "CL-01"), "core1")
    for name in JOINS:
        assert h[name]["state"] == NC and "not collected" in h[name]["reason"], (name, h[name])
        assert ("/collection_completeness/devices/0", "witness") in _refs(h[name])
    empty = copy.deepcopy(snap)
    empty["cross_layer"] = []
    xl = _cross_layer(empty, validator)
    assert xl["state"] == NC and xl["items"] == [] and "not a clean result" in xl["reason"], xl
    assert ("/collection_completeness/devices/0", "witness") in _refs(xl)
    clean = copy.deepcopy(sample)                              # control: no blind spot, an empty list is a measurement
    clean["cross_layer"] = []
    xl = _cross_layer(clean, validator)
    assert xl["state"] == CBE and "not a blind spot" in xl["reason"], xl


def test_failed_phases_and_an_absent_section_are_never_a_clean_result(sample, validator):
    failed = copy.deepcopy(sample)
    failed["cross_layer"] = []                                 # the _run_phase fallback
    failed["assessment_integrity"] = {"failed_phases": ["Cross-Layer correlations"]}
    xl = _cross_layer(failed, validator)
    assert xl["state"] == AU and xl["items"] == []
    assert ("/assessment_integrity/failed_phases/0", "failure_record") in _refs(xl)
    upstream = copy.deepcopy(sample)
    upstream["assessment_integrity"] = {"failed_phases": ["Physical Health"]}
    xl = _cross_layer(upstream, validator)
    assert xl["state"] == AU and "physical_health" in xl["reason"] and "may be incomplete" in xl["reason"]
    assert len(xl["items"]) == len(sample["cross_layer"])                   # what it has stays visible
    assert "one_hop_failure_attribution" in xl["items"][0]["id"]["caveats"]
    health = copy.deepcopy(sample)
    health["health_scores"] = []
    health["assessment_integrity"] = {"failed_phases": ["Health Scores"]}
    xl = _cross_layer(health, validator)
    h = xl["items"][0]["hosts"]["items"][0]
    assert h["device"]["state"] == PUB
    assert h["deduction_ref"]["state"] == h["deduction"]["state"] == AU
    absent = copy.deepcopy(sample)
    del absent["cross_layer"]
    xl = _cross_layer(absent, validator)
    assert xl["state"] == NC and xl["items"] == [] and "blind spot" in xl["reason"]


@pytest.mark.parametrize("snap", [None, [], {}, {"cross_layer": "x"}, {"cross_layer": [None, 5, {"hosts": "core1"}]}])
def test_garbage_is_total_and_schema_valid(snap, validator):
    xl = _cross_layer(snap, validator)
    if isinstance(snap, dict) and isinstance(snap.get("cross_layer"), list):
        assert [it["index"] for it in xl["items"]] == [0, 1, 2]
        assert all(it["hosts"]["state"] == UV for it in xl["items"])            # no row can name a host here
    else:
        assert xl["items"] == [] and xl["state"] != PUB
