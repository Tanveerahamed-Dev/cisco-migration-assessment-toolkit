"""VLAN gateway rows (contract gap G16): the stored l3_forwarding rows of a VLAN, selected, never recomputed.

A VLAN row's ``selections.gateways`` is a fact list of the ``excel.write_l3_forwarding_sheet`` rows that name its VLAN
id: per gateway, the switch, SVI address, FHRP role, object tracking and the sole-gateway risk. The page never reads an
absence as health:

* the producer's ``[NOT OBSERVED]`` tracking marker is not collected, never "no tracking"; an empty tracking text is
  "captured, no tracked object" only where the snapshot proves its producer separates the two (before 2026-07-28 it
  wrote '' for both); a text that disagrees with the row's own tracked-object-down flag is unverified;
* ``risk`` is the producer's single-gateway flag alone, a boolean. The producer counts gateways by VLAN id, so its
  absence is published as false only where another switch's row provably shares the segment (subnet and VRF, and --
  W51 -- positive layer-2 evidence between the two switches: a trunk path carrying the VLAN, or one spanning-tree root
  bridge for it), and then whatever the coverage (an unscanned device can only add gateways). The flag is a published
  risk only when the scan covers every gateway the producer's VlanN rule could count and nothing stored contradicts
  it: no collection blind spot nor any gap of the blind-spot record's own coverage verdict, no cable-map neighbour the collection never reached that could route, every collected device's interface
  running-config captured, no other collected interface holding an address in the gateway's subnet, and no stored FHRP
  evidence of another router in its group. A flag the stored rows contradict is unverified;
* an empty gateway list is a clean "no gateway in the scan" only under that same coverage, and a row the VLAN join
  cannot read makes every gateway list unverified;
* the VLAN row's "sole gateway on X (no FHRP)" fhrp text is published only where X's own sole-gateway risk is.

Every value is checked against an INDEPENDENT lookup in the snapshot, never the module's own join. The stored sample and
golden snapshots carry a real coverage gap (an uncollected WAN router), and the producer's own markers and flags are
pinned by driving ``excel.write_l3_forwarding_sheet`` (and the HSRP detail builder) itself.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import json
import pathlib
import textwrap

import pytest
from jsonschema import Draft202012Validator
from openpyxl import Workbook

from cisco_toolkit import analyze, build, excel
from cisco_toolkit import ui_projection as ui
from cisco_toolkit.model import InterfaceData

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json"
GOLDEN = ROOT / "tests" / "golden" / "snapshot.json"
PUB, CBE, NC, AU, UV = "published", "collected_but_empty", "not_collected", "analysis_unavailable", "unverified"
NOT_A_BLIND_SPOT = "not a blind spot"
CAVEAT = "vlan_gateway_rows"
#: Written out here rather than taken from the module: the producer's tokens and markers.
SOLE = "single-gateway"
MARKER = "[NOT OBSERVED]"
TRACK_NOT_ASSESSED = "[NOT OBSERVED] - no 'show track' evidence; object tracking NOT assessed"
DOWN_SOLE = "tracked-object-down; single-gateway"
#: The most witnesses one coverage gap cites (its reason then says "(8 of N cited)").
CAP = 8
#: analyze.compute_cable_map's kinds for POSITIVELY identified edge gear, which cannot be a VLAN's gateway.
EDGE_KINDS = ("ap", "phone", "endpoint")
BLIND = {"host": "access2", "status": "partial", "data_quality": 75, "missing": ["interface status"]}


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def inv_validator():
    schema = ui.ui_projection_schema()
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"],
                                 "$ref": "#/$defs/Inventory"})


# --------------------------------------------------------------------------------------------------
# independent helpers (deliberately NOT the module's own)
# --------------------------------------------------------------------------------------------------
def _ptr(*tokens):
    return "".join("/" + str(t).replace("~", "~0").replace("/", "~1") for t in tokens)


def _refs(fact):
    return {(r["pointer"], r["role"]) for r in fact["refs"]}


def _inventory(snap, validator):
    """The inventory section, schema-validated and JSON-native; the projection never mutates its input."""
    before = copy.deepcopy(snap)
    inv = ui.project_inventory(snap)
    assert snap == before
    errors = sorted(validator.iter_errors(inv), key=lambda e: list(e.absolute_path))
    assert not errors, [(list(e.absolute_path), e.message[:200]) for e in errors[:5]]
    json.dumps(inv, allow_nan=False)
    return inv


def _vlan_row(inv, vid):
    rows = [r for r in inv["vlans"]["rows"]["items"] if r["vlan"]["state"] == PUB and r["vlan"]["value"] == vid]
    assert len(rows) == 1, vid
    return rows[0]


def _gateways(inv, vid):
    return _vlan_row(inv, vid)["selections"]["gateways"]


def _gw(inv, vid, j):
    hits = [it for it in _gateways(inv, vid)["items"] if it["index"] == j]
    assert len(hits) == 1, (vid, j)
    return hits[0]


def _naming(snap, vid):
    """Independent selection: the stored l3_forwarding rows whose integer VLAN is `vid`."""
    return [j for j, r in enumerate(snap["l3_forwarding"])
            if isinstance(r, dict) and type(r.get("vlan")) is int and r["vlan"] == vid]


def _sole_rows(snap):
    """``(row index, vlan)`` of every stored row the producer flags single-gateway."""
    return [(j, r["vlan"]) for j, r in enumerate(snap["l3_forwarding"]) if SOLE in r["risk"].split("; ")]


def _pair_vlan(snap):
    """A VLAN two distinct scanned devices gateway, with its two row indices."""
    l3 = snap["l3_forwarding"]
    for vid in sorted({r["vlan"] for r in l3}):
        rows = _naming(snap, vid)
        if len({l3[j]["switch"] for j in rows}) == 2 and len(rows) == 2:
            return vid, rows[0], rows[1]
    raise AssertionError("the fixture has no VLAN with two gateways")


def _gap_witnesses(snap):
    """Independent: every stored record that says the scan may not cover a VLAN's possible gateways -- a blind spot,
    a cable-map neighbour the collection never reached that is not positively edge gear, a cable end that joins no
    single node, and a collected device none of whose interfaces carries run_config_observed: true."""
    out = []
    for i, r in enumerate(snap["collection_completeness"]["devices"]):
        if r["status"].strip().lower() in ("partial", "not collected"):
            out.append(_ptr("collection_completeness", "devices", i))
    nodes = snap["cable_map"]["nodes"]
    for i, n in enumerate(nodes):
        if not (n.get("collected") is True or (n.get("collected") is False and n.get("kind") in EDGE_KINDS)):
            out.append(_ptr("cable_map", "nodes", i))
    hosts = [n.get("host") for n in nodes]
    for j, c in enumerate(snap["cable_map"]["cables"]):
        if hosts.count(c.get("a")) != 1 or hosts.count(c.get("b")) != 1:
            out.append(_ptr("cable_map", "cables", j))
    for h in sorted(set(snap["devices"]) | set(snap["interfaces"])):
        ports = snap["interfaces"].get(h)
        if not (isinstance(ports, dict) and any(isinstance(p, dict) and p.get("run_config_observed") is True
                                                for p in ports.values())):
            out.append(_ptr("interfaces", h) if h in snap["interfaces"] else _ptr("devices", h))
    return out


def _covered(sample):
    """The sample with its one uncollected neighbour that could route removed (its node and every cable naming it):
    the scan then covers every device the collection discovered."""
    snap = copy.deepcopy(sample)
    nodes = snap["cable_map"]["nodes"]
    gone = {n["host"] for n in nodes
            if not (n.get("collected") is True or (n.get("collected") is False and n.get("kind") in EDGE_KINDS))}
    assert gone == {"wan-edge-rtr1.lab"}                      # the stored shape this control relies on
    snap["cable_map"]["nodes"] = [n for n in nodes if n["host"] not in gone]
    snap["cable_map"]["cables"] = [c for c in snap["cable_map"]["cables"] if c["a"] not in gone and c["b"] not in gone]
    assert not _gap_witnesses(snap)
    return snap


# --------------------------------------------------------------------------------------------------
# (a) the stored sample and golden: the owner's rows, the tracking marker withheld, the sole flag held by a real gap
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", (SAMPLE, GOLDEN), ids=("sample", "golden"))
def test_stored_gateway_rows_are_the_owner_rows_with_a_coverage_honest_risk(path, inv_validator):
    snap = json.loads(path.read_text(encoding="utf-8"))
    inv = _inventory(snap, inv_validator)
    l3 = snap["l3_forwarding"]
    gaps = _gap_witnesses(snap)
    assert gaps, "the stored fixture carries an uncollected WAN router; without a gap this test would not bite"
    sole_seen = plain_seen = 0
    for row in inv["vlans"]["rows"]["items"]:
        vid = row["vlan"]["value"]
        gw = row["selections"]["gateways"]
        want = _naming(snap, vid)
        assert want, vid                                      # every stored VLAN row has a gateway row here
        assert [it["index"] for it in gw["items"]] == want
        assert gw["state"] == PUB and gw["subject"] == "/l3_forwarding"
        assert CAVEAT in gw["caveats"] and "row_selection_by_exact_key" in gw["caveats"]
        assert {(p, "witness") for p in gaps} <= _refs(gw)   # a list that may be incomplete cites why
        for it in gw["items"]:
            j = it["index"]
            src = l3[j]
            assert it["pointer"] == _ptr("l3_forwarding", j)
            assert (it["host"]["state"], it["host"]["value"]) == (PUB, src["switch"])
            assert it["host"]["subject"] == _ptr("l3_forwarding", j, "switch")
            assert (it["svi_ip"]["state"], it["svi_ip"]["value"]) == (
                (PUB, src["svi_ip"]) if src["svi_ip"] else (NC, None))
            if src["role"]:
                assert (it["role"]["state"], it["role"]["value"]) == (PUB, src["role"])
                assert CAVEAT in it["role"]["caveats"]
            else:
                assert it["role"]["state"] == NC and "not 'no FHRP'" in it["role"]["reason"]
            # the producer's own not-observed marker: never "no tracking"
            assert src["tracking"] == MARKER
            assert (it["tracking"]["state"], it["tracking"]["value"]) == (NC, None)
            assert "never 'no tracking'" in it["tracking"]["reason"]
            risk = it["risk"]
            assert risk["subject"] == _ptr("l3_forwarding", j, "risk")
            if SOLE in src["risk"].split("; "):
                sole_seen += 1
                assert (risk["state"], risk["value"]) == (NC, None), risk
                assert risk["reason"].startswith("not collected: the producer flags this gateway single-gateway")
                assert "not proven to be the VLAN's only gateway" in risk["reason"]
                assert {(p, "witness") for p in gaps} <= _refs(risk)
            else:
                plain_seen += 1
                assert (risk["state"], risk["value"]) == (PUB, False), risk
                assert CAVEAT in risk["caveats"]
    assert sole_seen == 1 and plain_seen >= 4
    # the same VLAN row's fhrp text names that sole gateway: one row never states it in one cell and withholds it in
    # another, while every other fhrp value (an FHRP record) stays published
    (j, vid), = _sole_rows(snap)
    raw = {r["vlan"]: r for r in snap["vlan_cutover"]}
    assert raw[vid]["fhrp"] == f"sole gateway on {l3[j]['switch']} (no FHRP)"
    fhrp = _vlan_row(inv, vid)["fhrp"]
    assert (fhrp["state"], fhrp["value"]) == (NC, None), fhrp
    assert fhrp["reason"].startswith("not collected: the engine names a sole gateway for this VLAN")
    assert {(p, "witness") for p in gaps} <= _refs(fhrp)
    for other, rec in raw.items():
        if other != vid:
            assert isinstance(rec["fhrp"], dict) and _vlan_row(inv, other)["fhrp"]["state"] == PUB, other


def test_a_sole_gateway_is_a_risk_once_the_scan_covers_every_possible_gateway(sample, inv_validator):
    snap = _covered(sample)
    inv = _inventory(snap, inv_validator)
    (j, vid), = _sole_rows(snap)
    risk = _gw(inv, vid, j)["risk"]
    assert (risk["state"], risk["value"]) == (PUB, True), risk
    assert CAVEAT in risk["caveats"]
    fhrp = _vlan_row(inv, vid)["fhrp"]
    raw = next(r["fhrp"] for r in snap["vlan_cutover"] if r["vlan"] == vid)
    assert (fhrp["state"], fhrp["value"]) == (PUB, raw)
    for row in inv["vlans"]["rows"]["items"]:
        gw = row["selections"]["gateways"]
        assert gw["state"] == PUB and CAVEAT not in gw.get("caveats", ())     # no coverage gap left to cite
        assert not any(p.startswith("/cable_map/") for p, _role in _refs(gw))
        for it in gw["items"]:
            if it["index"] != j:
                assert (it["risk"]["state"], it["risk"]["value"]) == (PUB, False), it["risk"]


# --------------------------------------------------------------------------------------------------
# (b) every coverage gap withholds the sole flag, and only the sole flag
# --------------------------------------------------------------------------------------------------
def _add_node(snap, **fields):
    node = {"host": "ghost-sw", "kind": "switch", "collected": False, "role": "", "tier": 0, "order": 99,
            "ports": [], "badges": [], "op_status": "unknown"}
    node.update(fields)
    for key in [k for k, v in fields.items() if v is _DROP]:
        node.pop(key)
    snap["cable_map"]["nodes"].append(node)
    return _ptr("cable_map", "nodes", len(snap["cable_map"]["nodes"]) - 1)


_DROP = object()


def _gap_partial(snap):
    snap["collection_completeness"]["devices"].append(copy.deepcopy(BLIND))
    return NC, _ptr("collection_completeness", "devices", 0), "partial or not collected"


def _gap_not_collected(snap):
    snap["collection_completeness"]["devices"].append(
        {"host": "ghost1", "status": "not collected", "data_quality": 0, "missing": ["version/inventory"]})
    summary = snap["collection_completeness"]["summary"]       # the producer counts the device it lists (W51)
    summary["inventory"] += 1
    summary["not_collected"] += 1
    return NC, _ptr("collection_completeness", "devices", 0), "partial or not collected"


def _gap_completeness_list_absent(snap):
    del snap["collection_completeness"]["devices"]
    return NC, _ptr("collection_completeness"), "collection_completeness cannot be read"


def _gap_inventory_off_the_roster(snap):
    # W51 (the shared coverage verdict): an inventory count the devices map and the listed blind spots do not reach
    snap["collection_completeness"]["summary"]["inventory"] += 1
    return UV, _ptr("collection_completeness", "summary", "inventory"), "does not reconcile with the roster"


def _gap_no_record(snap):
    del snap["collection_completeness"]
    return NC, None, "collection_completeness cannot be read"


def _gap_unreadable_status(snap):
    snap["collection_completeness"]["devices"].append({"host": "ghost1", "status": None})
    return UV, _ptr("collection_completeness", "devices", 0), "no readable status"


def _gap_node(**fields):
    def build(snap):
        return NC, _add_node(snap, **fields), "neighbour(s) the collection never reached"
    return build


def _gap_unreadable_node(snap):
    snap["cable_map"]["nodes"].append(None)
    return NC, _ptr("cable_map", "nodes", len(snap["cable_map"]["nodes"]) - 1), "never reached"


def _gap_loose_cable(snap):
    snap["cable_map"]["cables"].append({"a": "core1", "a_port": "Gi1/0/48", "b": "nowhere-sw", "b_port": "Gi1/0/1",
                                        "is_pc": False})
    return NC, _ptr("cable_map", "cables", len(snap["cable_map"]["cables"]) - 1), "fail closed"


def _gap_unreadable_cable(snap):
    snap["cable_map"]["cables"].append(5)
    return NC, _ptr("cable_map", "cables", len(snap["cable_map"]["cables"]) - 1), "fail closed"


def _gap_no_run_config(snap):
    for port in snap["interfaces"]["access3"].values():
        port.pop("run_config_observed", None)
    return NC, _ptr("interfaces", "access3"), "run_config_observed: true"


def _gap_run_config_text(snap):
    for port in snap["interfaces"]["access3"].values():
        port["run_config_observed"] = "true"                 # a string is not the producer's marker
    return NC, _ptr("interfaces", "access3"), "run_config_observed: true"


def _gap_devices_not_a_map(snap):
    snap["devices"] = sorted(snap["devices"])
    return UV, _ptr("devices"), "devices map cannot be read"


def _gap_cable_map_failed(snap):
    snap["assessment_integrity"] = {"failed_phases": ["Cable map"]}
    return AU, None, "cable map's nodes cannot be read"


def _gap_completeness_failed(snap):
    snap["assessment_integrity"] = {"failed_phases": ["Collection completeness"]}
    return AU, None, "collection_completeness cannot be read"


def _gap_summary_counts_unlisted(snap):
    # the producer counts each blind spot in its summary AND lists it; a count the list does not carry is a blind spot
    # the list may be missing, never "no blind spot"
    assert snap["collection_completeness"]["devices"] == []
    snap["collection_completeness"]["summary"]["not_collected"] = 3
    return UV, _ptr("collection_completeness", "summary"), "summary counts 3 partial or not-collected device(s)"


def _gap_summary_unreadable(snap):
    snap["collection_completeness"]["summary"]["partial"] = "two"
    return UV, _ptr("collection_completeness", "summary"), "partial or not_collected count cannot be read"


GAPS = {
    "partial_device": _gap_partial,
    "not_collected_device": _gap_not_collected,
    "no_completeness_record": _gap_no_record,
    "unreadable_completeness_row": _gap_unreadable_status,
    "uncollected_switch": _gap_node(),
    "uncollected_unknown": _gap_node(kind="unknown"),
    "uncollected_no_kind": _gap_node(kind=_DROP),
    "uncollected_case_variant_ap": _gap_node(kind="AP"),
    "uncollected_device_kind": _gap_node(kind="device"),
    "collected_as_text": _gap_node(kind="ap", collected="false"),
    "collected_missing": _gap_node(kind="ap", collected=_DROP),
    "unreadable_node": _gap_unreadable_node,
    "loose_cable_end": _gap_loose_cable,
    "unreadable_cable": _gap_unreadable_cable,
    "device_without_interface_running_config": _gap_no_run_config,
    "run_config_marker_as_text": _gap_run_config_text,
    "devices_not_a_map": _gap_devices_not_a_map,
    "cable_map_phase_failed": _gap_cable_map_failed,
    "completeness_phase_failed": _gap_completeness_failed,
    "summary_counts_an_unlisted_blind_spot": _gap_summary_counts_unlisted,
    "summary_count_unreadable": _gap_summary_unreadable,
    "completeness_list_absent": _gap_completeness_list_absent,
    "inventory_off_the_roster": _gap_inventory_off_the_roster,
}
WORD = {NC: "not collected", UV: "unverified", AU: "analysis unavailable"}


@pytest.mark.parametrize("name", sorted(GAPS))
def test_every_coverage_gap_withholds_the_sole_flag_but_never_a_no_flag(name, sample, inv_validator):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    pair, a, b = _pair_vlan(snap)
    want, witness, fragment = GAPS[name](snap)
    inv = _inventory(snap, inv_validator)
    risk = _gw(inv, vid, j)["risk"]
    assert (risk["state"], risk["value"]) == (want, None), (name, risk)
    assert risk["reason"].startswith(f"{WORD[want]}: the producer flags this gateway single-gateway"), risk["reason"]
    assert fragment in risk["reason"], (name, risk["reason"])
    if witness is not None:
        assert (witness, "witness") in _refs(risk), (name, risk["refs"])
    if want == AU:
        assert ("/assessment_integrity/failed_phases/0", "failure_record") in _refs(risk)
    for k in (a, b):                                          # another gateway only grows with coverage
        other = _gw(inv, pair, k)["risk"]
        assert (other["state"], other["value"]) == (PUB, False), (name, other)
    listing = _gateways(inv, pair)
    assert listing["state"] == PUB and CAVEAT in listing["caveats"]
    if witness is not None:
        assert (witness, "witness") in _refs(listing)


def test_a_blind_spot_qualifies_every_published_gateway_list(sample, inv_validator):
    snap = _covered(sample)
    snap["collection_completeness"]["devices"] = [copy.deepcopy(BLIND)]
    inv = _inventory(snap, inv_validator)
    for row in inv["vlans"]["rows"]["items"]:
        gw = row["selections"]["gateways"]
        assert gw["state"] == PUB
        assert {"fleet_lists_exclude_blind_devices", CAVEAT} <= set(gw["caveats"])
        assert ("/collection_completeness/devices/0", "witness") in _refs(gw)


# --------------------------------------------------------------------------------------------------
# (c) the producer's flags: decoded exactly, and checked against the stored rows
# --------------------------------------------------------------------------------------------------
def test_a_flag_the_stored_rows_contradict_is_unverified(sample, inv_validator):
    snap = _covered(sample)
    l3 = snap["l3_forwarding"]
    (j, vid), = _sole_rows(snap)
    pair, a, b = _pair_vlan(snap)
    l3[a]["risk"] = SOLE              # claims its VLAN's only gateway while another device carries a gateway row
    l3[j]["risk"] = "ok"              # claims another gateway while it is its VLAN's only gateway row
    inv = _inventory(snap, inv_validator)
    ra = _gw(inv, pair, a)["risk"]
    assert (ra["state"], ra["value"]) == (UV, None) and "contradicts the stored rows" in ra["reason"]
    assert {(_ptr("l3_forwarding", a), "witness"), (_ptr("l3_forwarding", b), "witness")} <= _refs(ra)
    rb = _gw(inv, pair, b)["risk"]
    assert (rb["state"], rb["value"]) == (PUB, False)
    rj = _gw(inv, vid, j)["risk"]
    assert (rj["state"], rj["value"]) == (UV, None) and "contradict the stored rows" in rj["reason"]
    assert (_ptr("l3_forwarding", j), "witness") in _refs(rj)
    # the VLAN row's "sole gateway on X" text follows X's own risk, whatever withheld it
    fhrp = _vlan_row(inv, vid)["fhrp"]
    assert (fhrp["state"], fhrp["value"]) == (UV, None), fhrp
    assert fhrp["reason"].startswith("unverified: the engine names a sole gateway for this VLAN, but that gateway row's")
    assert {(_ptr("l3_forwarding", j, "risk"), "witness"), (_ptr("l3_forwarding", j), "witness")} <= _refs(fhrp)


@pytest.mark.parametrize("text", ("single gateway", "", "Single-Gateway", "single-gateway; no-FHRP",
                                  "single-gateway; single-gateway", "ok; single-gateway", "single-gateway;",
                                  "single-gateway; tracked-object-down", "no-FHRP; tracked-object-down",
                                  7, None, ["single-gateway"]))
def test_a_risk_text_that_is_not_the_producers_flag_list_is_unverified(sample, inv_validator, text):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    snap["l3_forwarding"][j]["risk"] = text
    risk = _gw(_inventory(snap, inv_validator), vid, j)["risk"]
    assert (risk["state"], risk["value"]) == (UV, None), (text, risk)
    assert risk["reason"].startswith("unverified: the stored risk text is not the producer's flag list"), risk


@pytest.mark.parametrize("text, sole", (("tracked-object-down; single-gateway", True), (SOLE, True),
                                        ("tracked-object-down", False), ("no-FHRP", False), ("ok", False),
                                        (TRACK_NOT_ASSESSED, False),
                                        ("tracked-object-down; no-FHRP", False)))
def test_the_sole_gateway_risk_reads_only_the_single_gateway_flag(sample, inv_validator, text, sole):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    pair, a, _b = _pair_vlan(snap)
    target_vid, target = (vid, j) if sole else (pair, a)
    snap["l3_forwarding"][target]["risk"] = text
    risk = _gw(_inventory(snap, inv_validator), target_vid, target)["risk"]
    assert (risk["state"], risk["value"]) == (PUB, sole), (text, risk)


@pytest.mark.parametrize("value", ("", None, 7))
def test_a_gateway_row_naming_no_switch_makes_its_vlans_gateway_count_unreadable(sample, inv_validator, value):
    snap = _covered(sample)
    pair, a, b = _pair_vlan(snap)
    snap["l3_forwarding"][b]["switch"] = value
    inv = _inventory(snap, inv_validator)
    for k in (a, b):
        risk = _gw(inv, pair, k)["risk"]
        assert (risk["state"], risk["value"]) == (UV, None), risk
        assert "name no readable switch" in risk["reason"]
        assert (_ptr("l3_forwarding", b), "witness") in _refs(risk)
    host = _gw(inv, pair, b)["host"]
    assert host["state"] == (NC if value == "" else UV) and host["value"] is None


@pytest.mark.parametrize("bad", ({"switch": "core9", "vlan": "ten", "risk": SOLE}, None, 5,
                                 {"switch": "core9", "vlan": -1, "risk": SOLE}, {"switch": "core9", "risk": SOLE}))
def test_a_row_the_vlan_join_cannot_read_makes_every_gateway_list_unverified(sample, inv_validator, bad):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    pair, a, _b = _pair_vlan(snap)
    snap["l3_forwarding"].append(copy.deepcopy(bad))
    k = len(snap["l3_forwarding"]) - 1
    inv = _inventory(snap, inv_validator)
    for row in inv["vlans"]["rows"]["items"]:
        gw = row["selections"]["gateways"]
        assert gw["state"] == UV and "cannot be joined by VLAN" in gw["reason"], gw
        assert (_ptr("l3_forwarding", k), "witness") in _refs(gw)
        assert [it["index"] for it in gw["items"]] == _naming(snap, row["vlan"]["value"])     # rows are kept
    sole = _gw(inv, vid, j)["risk"]                           # the unreadable row could be its other gateway
    assert (sole["state"], sole["value"]) == (UV, None) and (_ptr("l3_forwarding", k), "witness") in _refs(sole)
    other = _gw(inv, pair, a)["risk"]                         # two readable gateways stay two
    assert (other["state"], other["value"]) == (PUB, False)
    fhrp = _vlan_row(inv, vid)["fhrp"]                        # and the row's sole-gateway text is withheld with it
    assert (fhrp["state"], fhrp["value"]) == (UV, None), fhrp
    assert fhrp["reason"].startswith("unverified: the engine names a sole gateway for this VLAN")
    assert (_ptr("l3_forwarding", k), "witness") in _refs(fhrp)


# --------------------------------------------------------------------------------------------------
# (d) object tracking: observed, not observed, and the pre-split ambiguity
# --------------------------------------------------------------------------------------------------
def test_tracking_cells_never_read_an_absence_as_no_tracking(sample, inv_validator):
    snap = _covered(sample)
    l3 = snap["l3_forwarding"]
    (j, vid), = _sole_rows(snap)
    pair, a, b = _pair_vlan(snap)
    assert l3[a]["risk"] == TRACK_NOT_ASSESSED and l3[b]["risk"] == TRACK_NOT_ASSESSED
    l3[j]["tracking"] = ""                                    # a captured 'show track' with no tracked object
    l3[a]["tracking"] = ""                                    # ... beside its own 'tracking NOT assessed' marker
    l3[b]["tracking"] = "1 obj - T1:Up"                       # objects beside that marker
    inv = _inventory(snap, inv_validator)
    none = _gw(inv, vid, j)["tracking"]
    assert (none["state"], none["value"]) == (CBE, None) and NOT_A_BLIND_SPOT in none["reason"]
    for k in (a, b):
        cell = _gw(inv, pair, k)["tracking"]
        assert (cell["state"], cell["value"]) == (UV, None) and "contradicts" in cell["reason"], cell
        assert (_ptr("l3_forwarding", k, "risk"), "witness") in _refs(cell)
    # a Down object, beside the tracked-object-down flag the producer always raises with it
    l3[j].update(tracking="2 obj (1 DOWN) - T1:Up; T2:Down", risk=DOWN_SOLE)
    seen = _gw(_inventory(snap, inv_validator), vid, j)["tracking"]
    assert (seen["state"], seen["value"]) == (PUB, "2 obj (1 DOWN) - T1:Up; T2:Down")
    assert CAVEAT in seen["caveats"]


@pytest.mark.parametrize("tracking, risk, agree", (
    ("", DOWN_SOLE, False),                                   # 'captured, none' beside a Down flag
    (MARKER, DOWN_SOLE, False),                               # 'never captured' beside a Down flag
    ("1 obj - T1:Up", DOWN_SOLE, False),                      # no Down object beside a Down flag
    ("2 obj (1 DOWN) - T1:Up; T2:Down", SOLE, False),         # a Down object with no Down flag
    ("2 obj (1 DOWN) - T1:Up; T2:Down", DOWN_SOLE, True),
    ("1 obj - T1:Up", SOLE, True),
))
def test_a_tracking_text_the_rows_own_down_flag_contradicts_is_unverified(sample, inv_validator, tracking, risk,
                                                                          agree):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    snap["l3_forwarding"][j].update(tracking=tracking, risk=risk)
    cell = _gw(_inventory(snap, inv_validator), vid, j)["tracking"]
    if agree:
        assert (cell["state"], cell["value"]) == (PUB, tracking), cell
    else:
        assert (cell["state"], cell["value"]) == (UV, None), cell
        assert cell["reason"].startswith("unverified: this tracking text and the row's tracked-object-down flag")
        assert (_ptr("l3_forwarding", j, "risk"), "witness") in _refs(cell)


def _pre_split(sample):
    """The sample as the producer wrote it before 2026-07-28: '' for every tracking text, 'ok' where no flag fired,
    and no run_config_observed marker anywhere."""
    snap = copy.deepcopy(sample)
    for row in snap["l3_forwarding"]:
        row["tracking"] = ""
        if row["risk"] == TRACK_NOT_ASSESSED:
            row["risk"] = "ok"
    for ports in snap["interfaces"].values():
        for port in ports.values():
            port.pop("run_config_observed", None)
    return snap


def test_an_empty_tracking_text_is_withheld_where_the_snapshot_cannot_prove_the_split(sample, inv_validator):
    snap = _pre_split(sample)
    inv = _inventory(snap, inv_validator)
    cells = [it["tracking"] for r in inv["vlans"]["rows"]["items"] for it in r["selections"]["gateways"]["items"]]
    assert len(cells) == len(snap["l3_forwarding"])
    for cell in cells:
        assert (cell["state"], cell["value"]) == (NC, None), cell
        assert "ambiguous" in cell["reason"] and "not 'no tracking'" in cell["reason"]
    # one interface marked run_config_observed proves the later producer: '' is then 'captured, none'
    proven = copy.deepcopy(snap)
    host = sorted(proven["interfaces"])[0]
    proven["interfaces"][host][sorted(proven["interfaces"][host])[0]]["run_config_observed"] = True
    inv = _inventory(proven, inv_validator)
    for r in inv["vlans"]["rows"]["items"]:
        for it in r["selections"]["gateways"]["items"]:
            assert (it["tracking"]["state"], it["tracking"]["value"]) == (CBE, None), it["tracking"]
    # so does the producer's own not-observed tracking text on any row
    marked = copy.deepcopy(snap)
    marked["l3_forwarding"][0]["tracking"] = MARKER
    inv = _inventory(marked, inv_validator)
    for r in inv["vlans"]["rows"]["items"]:
        for it in r["selections"]["gateways"]["items"]:
            want = NC if it["index"] == 0 else CBE
            assert it["tracking"]["state"] == want, (it["index"], it["tracking"])


# --------------------------------------------------------------------------------------------------
# (e) the list: an unreadable source selects nothing, and an empty selection is clean only under coverage
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode, want", (("absent", NC), ("null", NC), ("malformed", UV), ("failed", AU),
                                        ("failed_fallback", AU)))
def test_an_unreadable_gateway_source_selects_nothing_and_says_why(sample, inv_validator, mode, want):
    snap = _covered(sample)
    if mode == "absent":
        del snap["l3_forwarding"]
    elif mode == "null":
        snap["l3_forwarding"] = None
    elif mode == "malformed":
        snap["l3_forwarding"] = 7
    else:
        if mode == "failed_fallback":
            snap["l3_forwarding"] = []
        snap["assessment_integrity"] = {"failed_phases": ["L3 Forwarding Map"]}
    inv = _inventory(snap, inv_validator)
    rows = inv["vlans"]["rows"]["items"]
    assert rows
    for row in rows:
        gw = row["selections"]["gateways"]
        assert gw["state"] == want and gw["items"] == [] and gw["reason"], (mode, gw)
        if want == AU:
            assert ("/assessment_integrity/failed_phases/0", "failure_record") in _refs(gw)
    assert inv["vlans"]["selection_sources"]["gateways"]["state"] == want


def _drop_gateway(snap):
    """VLAN 30 as the producer would write it with no gateway: its only gateway row names a VLAN with no row, and its
    SVI holds no address (an addressed SVI with no gateway row would contradict the empty list)."""
    (j, vid), = _sole_rows(snap)
    snap["l3_forwarding"][j]["vlan"] = 4094
    svi = snap["interfaces"][snap["l3_forwarding"][j]["switch"]][f"Vlan{vid}"]
    svi.update(svi_ip="", svi_ips="")
    assert not _naming(snap, vid)
    return vid


def test_a_vlan_with_no_gateway_row_is_a_clean_absence_only_under_coverage(sample, inv_validator):
    for make, want in ((copy.deepcopy, NC), (_covered, CBE)):
        snap = make(sample)
        vid = _drop_gateway(snap)
        gw = _gateways(_inventory(snap, inv_validator), vid)
        assert (gw["state"], gw["items"]) == (want, []), gw
        if want == CBE:
            assert NOT_A_BLIND_SPOT in gw["reason"]
        else:
            assert gw["reason"].startswith("not collected: no scanned device records a gateway for this VLAN")
            assert {(p, "witness") for p in _gap_witnesses(snap)} <= _refs(gw)
            assert NOT_A_BLIND_SPOT not in gw["reason"]


def test_a_vlan_row_with_no_readable_vlan_joins_no_gateway(sample, inv_validator):
    snap = _covered(sample)
    snap["vlan_cutover"][0]["vlan"] = "ten"
    inv = _inventory(snap, inv_validator)
    gw = inv["vlans"]["rows"]["items"][0]["selections"]["gateways"]
    assert (gw["state"], gw["items"]) == (UV, []) and "no readable VLAN id" in gw["reason"]


def test_an_addressed_svi_with_no_gateway_row_contradicts_an_empty_list(sample, inv_validator):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    host = snap["l3_forwarding"][j]["switch"]
    snap["l3_forwarding"][j]["vlan"] = 4094                   # the row is gone, but the SVI keeps its address
    assert snap["interfaces"][host][f"Vlan{vid}"]["svi_ip"]
    gw = _gateways(_inventory(snap, inv_validator), vid)
    assert (gw["state"], gw["items"]) == (UV, []), gw
    assert "carry no gateway row" in gw["reason"] and NOT_A_BLIND_SPOT not in gw["reason"]
    assert (_ptr("interfaces", host, f"Vlan{vid}"), "witness") in _refs(gw)


#: Interfaces excel.write_l3_forwarding_sheet never counts as a VLAN's gateway (it counts only SVIs named VlanN): a
#: routed /30 whose far end is no collected address, a dot1Q subinterface, a bridge-domain interface and an irb unit.
_UNCOUNTED = {
    "routed_port_with_a_free_host": ("dist1", "Gi1/0/3", "10.0.141.2 255.255.255.252"),
    "subinterface": ("core2", "Gi0/0.30", "10.0.31.254 255.255.255.0"),
    "bridge_domain_interface": ("core2", "BDI30", "10.0.31.254 255.255.255.0"),
    "irb_unit": ("core2", "irb.30", "10.0.31.254/24"),
}


@pytest.mark.parametrize("name", sorted(_UNCOUNTED))
def test_an_interface_the_vlann_rule_never_counts_withholds_an_empty_list(sample, inv_validator, name):
    snap = _covered(sample)
    vid = _drop_gateway(snap)
    host, port, address = _UNCOUNTED[name]
    rec = snap["interfaces"][host].setdefault(port, {"port": port, "run_config_observed": True})
    rec.update(svi_ip=address, svi_ips=address)
    gw = _gateways(_inventory(snap, inv_validator), vid)
    assert (gw["state"], gw["items"]) == (NC, []), (name, gw)
    assert "not named VlanN" in gw["reason"] and NOT_A_BLIND_SPOT not in gw["reason"], gw["reason"]
    assert (_ptr("interfaces", host, port), "witness") in _refs(gw), gw["refs"]


def _routed(snap, port="Gi1/0/48", address="10.0.30.254 255.255.255.0", vrf="TENANT_RED", host="core2", **extra):
    """A collected interface not named VlanN holding `address` (core1's Vlan30 sits in TENANT_RED)."""
    rec = {"port": port, "svi_ip": address, "svi_ips": address, "vrf": vrf, "run_config_observed": True}
    rec.update(extra)
    snap["interfaces"][host][port] = rec
    return _ptr("interfaces", host, port)


def _hsrp(snap, **fields):
    """Append one HSRP detail record for core1's Vlan30 (parse.parse_hsrp_detail's shape)."""
    rec = {"ifname": "Vlan30", "group": "30", "state": "Active", "priority": 110, "cfg_priority": 110, "preempt": True,
           "preempt_delay": None, "vip": "10.0.30.254", "vmac": "0000.0c07.ac1e", "hello": 3, "hold": 10,
           "standby_ip": "", "track": [], "version": 1}
    rec.update(fields)
    snap["fhrp_detail"]["core1"].append(rec)
    return _ptr("fhrp_detail", "core1", len(snap["fhrp_detail"]["core1"]) - 1)


def _sole_row(snap):
    (j, _vid), = _sole_rows(snap)
    return snap["l3_forwarding"][j]


def _scoped_role(role):
    def build_(snap):
        row = _sole_row(snap)
        row["role"] = role
        return UV, _ptr("l3_forwarding", snap["l3_forwarding"].index(row), "role"), "neither Active nor Master"
    return build_


def _scoped_standby(snap):
    _sole_row(snap)["role"] = "Active"
    return UV, _hsrp(snap, standby_ip="10.0.30.3") + "/standby_ip", "names a standby router"


def _scoped_listen(snap):
    return UV, _hsrp(snap, state="Listen") + "/state", "records a state other than Active or Master"


def _scoped_active_no_record(snap):
    _sole_row(snap)["role"] = "Active"
    return NC, _ptr("fhrp_detail", "core1"), "no stored HSRP detail record of this device names its SVI"


def _scoped_active_no_device(snap):
    _sole_row(snap)["role"] = "Active"
    del snap["fhrp_detail"]["core1"]
    return NC, _ptr("fhrp_detail"), "no HSRP detail is stored for this device"


def _scoped_detail_record_unreadable(snap):
    snap["fhrp_detail"]["core1"].append(5)
    return UV, _ptr("fhrp_detail", "core1", len(snap["fhrp_detail"]["core1"]) - 1), "detail record(s) of this device"


def _scoped_detail_unreadable(snap):
    snap["fhrp_detail"] = [5]
    return UV, _ptr("fhrp_detail"), "HSRP detail (fhrp_detail) cannot be read"


def _scoped_routed(**fields):
    def build_(snap):
        return UV, _routed(snap, **fields), "hold an address in this VLAN's gateway subnet"
    return build_


def _scoped_secondary(snap):
    # another VLAN's SVI holds a secondary address in VLAN 30's subnet; its VRF was never read (no running-config
    # capture of it), so no VRF tells the two apart
    svi = snap["interfaces"]["core2"]["Vlan20"]
    assert svi["vrf"] is None
    svi.update(svi_ips=svi["svi_ip"] + ";10.0.30.5 255.255.255.0", run_config_observed=False)
    return UV, _ptr("interfaces", "core2", "Vlan20"), "hold an address in this VLAN's gateway subnet"


def _scoped_uncounted_svi(snap):
    snap["interfaces"]["core2"]["Vlan30"] = {"port": "Vlan30", "svi_ip": "", "svi_ips": "10.0.30.2 255.255.255.0",
                                             "vrf": "TENANT_RED", "run_config_observed": True}
    return UV, _ptr("interfaces", "core2", "Vlan30"), "carry no gateway row"


def _scoped_no_segment(snap):
    row = _sole_row(snap)
    row.update(svi_ip="", primary_subnet="")                  # the row names no segment to scope the check by
    rec = snap["interfaces"]["dist1"]["Gi1/0/3"]
    rec.update(svi_ip="10.0.141.2 255.255.255.252", svi_ips="10.0.141.2 255.255.255.252")
    return NC, _ptr("interfaces", "dist1", "Gi1/0/3"), "not named VlanN"


def _scoped_address_unreadable(snap):
    return UV, _routed(snap, address="10.0.30.999 255.255.255.0") + "/svi_ip", "cannot be read"


def _scoped_record_unreadable(snap):
    snap["interfaces"]["core2"]["Gi9/9"] = 5
    return UV, _ptr("interfaces", "core2", "Gi9/9"), "cannot be read"


#: name -> (build, whether the gap reaches VLAN 30's gateway list, whether it reaches every VLAN's list). FHRP evidence
#: bears on one gateway's risk; an address in a VLAN's subnet on that VLAN; an unreadable address on every VLAN.
SCOPED = {
    "own_role_standby": (_scoped_role("Standby"), False, False),
    "own_role_init": (_scoped_role("Init"), False, False),
    "hsrp_detail_names_a_standby_router": (_scoped_standby, False, False),
    "hsrp_detail_state_listen": (_scoped_listen, False, False),
    "active_with_no_detail_record_for_the_svi": (_scoped_active_no_record, False, False),
    "active_with_no_detail_for_the_device": (_scoped_active_no_device, False, False),
    "unreadable_detail_record": (_scoped_detail_record_unreadable, False, False),
    "unreadable_detail_section": (_scoped_detail_unreadable, False, False),
    "routed_port_in_the_subnet": (_scoped_routed(), True, False),
    "subinterface_in_the_subnet": (_scoped_routed(port="Gi0/0.30"), True, False),
    "routed_port_vrf_unreadable": (_scoped_routed(vrf=None, run_config_observed=False), True, False),
    "secondary_address_on_another_vlans_svi": (_scoped_secondary, True, False),
    "addressed_svi_without_a_gateway_row": (_scoped_uncounted_svi, True, False),
    "row_without_a_segment_and_a_free_routed_port": (_scoped_no_segment, True, False),
    "unreadable_interface_address": (_scoped_address_unreadable, True, True),
    "unreadable_interface_record": (_scoped_record_unreadable, True, True),
}


@pytest.mark.parametrize("name", sorted(SCOPED))
def test_stored_evidence_of_another_gateway_withholds_the_sole_flag(name, sample, inv_validator):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    pair, a, b = _pair_vlan(snap)
    build_, listed, fleet = SCOPED[name]
    want, witness, fragment = build_(snap)
    inv = _inventory(snap, inv_validator)
    risk = _gw(inv, vid, j)["risk"]
    assert (risk["state"], risk["value"]) == (want, None), (name, risk)
    assert risk["reason"].startswith(f"{WORD[want]}: the producer flags this gateway single-gateway"), risk["reason"]
    assert fragment in risk["reason"], (name, risk["reason"])
    assert (witness, "witness") in _refs(risk), (name, risk["refs"])
    fhrp = _vlan_row(inv, vid)["fhrp"]                        # the row's sole-gateway text is withheld with it
    assert (fhrp["state"], fhrp["value"]) == (want, None), (name, fhrp)
    assert (witness, "witness") in _refs(fhrp), (name, fhrp["refs"])
    own = _gateways(inv, vid)
    assert own["state"] == PUB and (CAVEAT in own.get("caveats", ())) is listed, (name, own)
    assert ((witness, "witness") in _refs(own)) is listed, (name, own["refs"])
    for k in (a, b):                                          # another VLAN's gateways are untouched
        other = _gw(inv, pair, k)["risk"]
        assert (other["state"], other["value"]) == (PUB, False), (name, other)
    assert (CAVEAT in _gateways(inv, pair).get("caveats", ())) is fleet, name


#: The same records where they cannot be another gateway of the sole gateway's segment: the rule is scoped, not a
#: blanket withhold.
UNRELATED = {
    "routed_port_in_another_vrf": lambda snap: _routed(snap, vrf=None),
    "routed_port_outside_the_subnet": lambda snap: _routed(snap, address="10.0.31.254 255.255.255.0"),
    "active_with_no_standby_router": lambda snap: (_sole_row(snap).update(role="Active"), _hsrp(snap)),
    "no_role_and_no_hsrp_detail_at_all": lambda snap: snap.pop("fhrp_detail"),
    "hsrp_detail_for_another_svi": lambda snap: _hsrp(snap, ifname="Vlan31", standby_ip="10.0.31.3"),
}


@pytest.mark.parametrize("name", sorted(UNRELATED))
def test_records_that_cannot_be_another_gateway_of_the_segment_keep_the_sole_flag(name, sample, inv_validator):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    UNRELATED[name](snap)
    inv = _inventory(snap, inv_validator)
    risk = _gw(inv, vid, j)["risk"]
    assert (risk["state"], risk["value"]) == (PUB, True), (name, risk)
    assert _vlan_row(inv, vid)["fhrp"]["state"] == PUB, name


_STANDBY = """Vlan30 - Group 30
  State is Active
    2 state changes, last state change 00:10:00
  Virtual IP address is 10.0.30.254
  Active virtual MAC address is 0000.0c07.ac1e
  Hello time 3 sec, hold time 10 sec
  Preemption enabled
  Active router is local
  Standby router is {standby}
  Priority 110 (configured 110)
"""


def test_the_producers_hsrp_detail_decides_whether_an_active_sole_gateway_is_alone(sample, inv_validator, tmp_path):
    base = _covered(sample)
    ifaces = {}
    for host, ports in base["interfaces"].items():
        ifaces[host] = {}
        for port, rec in ports.items():
            d = InterfaceData(**{k: v for k, v in rec.items() if k in _IF_FIELDS})
            d.port = port
            ifaces[host][port] = d
    ifaces["core1"]["Vlan30"].hsrp_behavior = "HSRP grp 30 Active VIP 10.0.30.254"   # HSRP, no peer discovered
    rows = json.loads(json.dumps(_l3(ifaces)))
    (j, vid), = [(k, r["vlan"]) for k, r in enumerate(rows) if SOLE in r["risk"].split("; ")]
    assert (rows[j]["switch"], rows[j]["role"]) == ("core1", "Active")
    for standby, sole in (("10.0.30.3, priority 100 (expires in 9.0 sec)", False), ("unknown", True)):
        snap = copy.deepcopy(base)
        snap["l3_forwarding"] = rows
        capture = _capture(tmp_path, f"standby-{sole}.txt", _STANDBY.format(standby=standby))
        snap["fhrp_detail"]["core1"] = json.loads(json.dumps(build.build_fhrp_detail({"show standby": capture})))
        (i, rec), = [(i, r) for i, r in enumerate(snap["fhrp_detail"]["core1"]) if r["ifname"] == "Vlan30"]
        risk = _gw(_inventory(snap, inv_validator), vid, j)["risk"]
        if sole:
            assert rec["standby_ip"] == "" and (risk["state"], risk["value"]) == (PUB, True), risk
        else:
            assert rec["standby_ip"] == "10.0.30.3"
            assert (risk["state"], risk["value"]) == (UV, None), risk
            assert (_ptr("fhrp_detail", "core1", i, "standby_ip"), "witness") in _refs(risk)


# --------------------------------------------------------------------------------------------------
# (e3) VLAN-id reuse: a second row with the same VLAN id is a second gateway only on the same segment
# --------------------------------------------------------------------------------------------------
def _other_site(snap, row, vrf=None):
    """Move `row` to another segment: its own subnet and SVI address (and, with `vrf`, its SVI's VRF)."""
    row.update(svi_ip=row["svi_ip"].replace("10.0.", "10.1.", 1), primary_subnet=row["primary_subnet"].replace(
        "10.0.", "10.1.", 1))
    svi = snap["interfaces"][row["switch"]][f"Vlan{row['vlan']}"]
    svi.update(svi_ip=row["svi_ip"], svi_ips=row["svi_ip"], subnet_primary_route=row["primary_subnet"])


REUSE = {
    "different_subnet": lambda snap, rb: _other_site(snap, rb),
    "same_subnet_different_vrf": lambda snap, rb: snap["interfaces"][rb["switch"]][f"Vlan{rb['vlan']}"].update(
        vrf="TENANT_BLUE"),
    "no_segment_recorded": lambda snap, rb: rb.update(svi_ip="", primary_subnet=""),
    "mask_mismatch": lambda snap, rb: rb.update(svi_ip=rb["svi_ip"].split()[0].split("/")[0] + "/25"),
}


@pytest.mark.parametrize("name", sorted(REUSE))
def test_a_vlan_id_seen_on_two_switches_is_a_second_gateway_only_on_one_segment(name, sample, inv_validator):
    snap = _covered(sample)
    pair, a, b = _pair_vlan(snap)
    l3 = snap["l3_forwarding"]
    REUSE[name](snap, l3[b])
    inv = _inventory(snap, inv_validator)
    for k in (a, b):
        risk = _gw(inv, pair, k)["risk"]
        assert (risk["state"], risk["value"]) == (UV, None), (name, k, risk)
        assert risk["reason"].startswith("unverified: the producer raises no single-gateway flag here because it "
                                         "counts a VLAN's gateways by VLAN id"), risk["reason"]
        assert "VLAN-id reuse" in risk["reason"]
        assert {(_ptr("l3_forwarding", a), "witness"), (_ptr("l3_forwarding", b), "witness")} <= _refs(risk)


def _trunk_hosts(snap, vid):
    """Independent: host -> the hosts one stored cable joins it to over two ports both trunking `vid` (status
    'trunking', the VLAN in the allowed list, read here with plain comma/range parsing)."""
    def carries(rec):
        if not isinstance(rec, dict) or str(rec.get("trunk_status", "")).strip().lower() != "trunking":
            return False
        for part in str(rec.get("trunk_allowed_vlans", "")).split(","):
            lo, _sep, hi = part.strip().partition("-")
            if lo.isdigit() and int(lo) <= vid <= int(hi if hi.isdigit() else lo):
                return True
        return False

    out = {}
    for cable in snap["cable_map"]["cables"]:
        a, b = cable["a"], cable["b"]
        if carries(snap["interfaces"].get(a, {}).get(cable["a_port"])) and carries(
                snap["interfaces"].get(b, {}).get(cable["b_port"])):
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)
    return out


def _joined(graph, a, b):
    seen, todo = {a}, [a]
    while todo:
        for nxt in graph.get(todo.pop(), ()):
            if nxt == b:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def test_one_subnet_in_one_table_without_layer_2_evidence_is_vlan_id_reuse(sample, inv_validator):
    """W51 (G16 P2, the reviewer's case): two sites reuse a VLAN id AND its subnet in the global table. Matching
    networks and VRFs are then no proof of one segment; only positive layer-2 evidence between the two switches is (a
    stored cable path every hop of which joins two ports trunking the VLAN, or the same spanning-tree root bridge for
    the VLAN). Without it both rows' false is withheld; before W51 it was published."""
    snap = _covered(sample)
    pair, a, b = _pair_vlan(snap)
    l3 = snap["l3_forwarding"]
    ha, hb = l3[a]["switch"], l3[b]["switch"]
    assert _joined(_trunk_hosts(snap, pair), ha, hb)                     # the stored pair is one trunked segment
    # sever every trunk path for the VLAN: no port that trunks it to a neighbour carries it any more
    for host, ports in snap["interfaces"].items():
        for rec in ports.values():
            if isinstance(rec, dict) and rec.get("trunk_allowed_vlans"):
                vids = [v for v in rec["trunk_allowed_vlans"].split(",") if v.strip() != str(pair)]
                rec["trunk_allowed_vlans"] = ",".join(vids) or "none"
    assert not _joined(_trunk_hosts(snap, pair), ha, hb)
    roots = snap.get("stp_roots", {})
    shared = {(roots.get(h) or {}).get(str(pair), {}).get("root_address") for h in (ha, hb)}
    assert not (len(shared) == 1 and shared != {""} and None not in shared)  # and no shared root bridge
    assert l3[a]["primary_subnet"] == l3[b]["primary_subnet"]             # one subnet, one table: the trap
    inv = _inventory(snap, inv_validator)
    for k in (a, b):
        risk = _gw(inv, pair, k)["risk"]
        assert (risk["state"], risk["value"]) == (UV, None), (k, risk)
        assert "VLAN-id reuse" in risk["reason"] and "layer-2 domain" in risk["reason"], risk["reason"]
        assert {(_ptr("l3_forwarding", a), "witness"), (_ptr("l3_forwarding", b), "witness")} <= _refs(risk)
    # the same switches reporting one spanning-tree root bridge for the VLAN share its layer-2 domain
    for h in (ha, hb):
        snap.setdefault("stp_roots", {}).setdefault(h, {})[str(pair)] = {
            "root_priority": 24586, "root_address": "aaaa.0001.0001", "is_root": h == ha, "is_mst": False,
            "bridge_priority": 24586}
    inv = _inventory(snap, inv_validator)
    for k in (a, b):
        risk = _gw(inv, pair, k)["risk"]
        assert (risk["state"], risk["value"]) == (PUB, False), (k, risk)
    # an MST instance key is not a VLAN: the same root then proves nothing
    snap["stp_roots"][hb][str(pair)]["is_mst"] = True
    inv = _inventory(snap, inv_validator)
    assert _gw(inv, pair, a)["risk"]["state"] == UV


def test_a_trunk_that_is_not_trunking_carries_no_layer_2_proof(sample, inv_validator):
    """A port whose trunk status is not 'trunking' (or whose allowed list cannot be read) carries no VLAN, whatever its
    configured allowed list says."""
    snap = _covered(sample)
    pair, a, b = _pair_vlan(snap)
    l3 = snap["l3_forwarding"]
    ha, hb = l3[a]["switch"], l3[b]["switch"]
    for host, ports in snap["interfaces"].items():
        for rec in ports.values():
            if isinstance(rec, dict) and rec.get("trunk_status"):
                rec["trunk_status"] = "not-trunking"
    assert not _joined(_trunk_hosts(snap, pair), ha, hb)
    inv = _inventory(snap, inv_validator)
    assert _gw(inv, pair, a)["risk"]["state"] == UV


def test_a_vrf_that_cannot_be_read_does_not_split_one_segment(sample, inv_validator):
    snap = _covered(sample)
    pair, a, b = _pair_vlan(snap)
    svi = snap["interfaces"][snap["l3_forwarding"][b]["switch"]][f"Vlan{pair}"]
    svi.pop("vrf", None)
    svi["run_config_observed"] = False                        # its VRF was never read: compared only where both are
    inv = _inventory(snap, inv_validator)
    for k in (a, b):
        risk = _gw(inv, pair, k)["risk"]
        assert (risk["state"], risk["value"]) == (PUB, False), risk


def test_two_sites_reusing_a_vlan_id_each_keep_an_unproven_sole_gateway(sample, inv_validator):
    """The reviewer's two-site fleet: siteA's core1 and siteB's core2 both carry Vlan30 without FHRP, in different
    subnets. The producer counts two gateways for VLAN 30 and flags both no-FHRP; neither is published as having a
    second gateway."""
    snap = _covered(sample)
    l3 = snap["l3_forwarding"]
    (j, vid), = _sole_rows(snap)
    l3[j]["risk"] = "no-FHRP"
    l3.append(dict(l3[j], switch="core2", svi_ip="10.1.30.1 255.255.255.0", primary_subnet="10.1.30.0/24"))
    snap["interfaces"]["core2"][f"Vlan{vid}"] = {"port": f"Vlan{vid}", "svi_ip": "10.1.30.1 255.255.255.0",
                                                 "svi_ips": "10.1.30.1 255.255.255.0",
                                                 "subnet_primary_route": "10.1.30.0/24", "vrf": "TENANT_RED",
                                                 "run_config_observed": True}
    row = next(r for r in snap["vlan_cutover"] if r["vlan"] == vid)
    row["fhrp"] = "2 gateways but no FHRP — no first-hop redundancy"   # what the producer writes for two gateways
    inv = _inventory(snap, inv_validator)
    k = len(l3) - 1
    for idx in (j, k):
        risk = _gw(inv, vid, idx)["risk"]
        assert (risk["state"], risk["value"]) == (UV, None), (idx, risk)
        assert "VLAN-id reuse" in risk["reason"]
    fhrp = _vlan_row(inv, vid)["fhrp"]                        # a risk statement, never a sole-gateway claim
    assert (fhrp["state"], fhrp["value"]) == (PUB, row["fhrp"])


def test_every_gap_cites_a_bounded_witness_list_with_its_full_count(sample, inv_validator):
    snap = _covered(sample)
    (j, vid), = _sole_rows(snap)
    n = 3 * CAP + 6
    for i in range(n):
        _add_node(snap, host=f"ghost-{i:02d}")
    assert ui._GW_GAP_WITNESS_CAP == CAP
    inv = _inventory(snap, inv_validator)
    risk = _gw(inv, vid, j)["risk"]
    nodes = [p for p, role in _refs(risk) if p.startswith("/cable_map/nodes/") and role == "witness"]
    assert risk["state"] == NC and len(nodes) == CAP, (len(nodes), risk["reason"])
    assert f"shows {n} neighbour(s)" in risk["reason"] and f"({CAP} of {n} cited)" in risk["reason"]
    for row in inv["vlans"]["rows"]["items"]:
        gw = row["selections"]["gateways"]
        cited = [p for p, _role in _refs(gw) if p.startswith("/cable_map/nodes/")]
        assert gw["state"] == PUB and len(cited) == CAP, (row["vlan"], len(cited))


# --------------------------------------------------------------------------------------------------
# (f) the producer: its markers, flags and joiner are the module's copies, and its own rows project
# --------------------------------------------------------------------------------------------------
def _svi(port, **fields):
    d = InterfaceData()
    d.port = port
    for key, value in fields.items():
        setattr(d, key, value)
    return d


def _l3(ifaces, captures=None):
    return excel.write_l3_forwarding_sheet(excel.harden_workbook(Workbook()), ifaces, captures or {})


def _hsrp_pair(vid=10):
    net, port = f"10.0.{vid}", f"Vlan{vid}"
    return {"CORE1": {port: _svi(port, svi_ip=f"{net}.2 255.255.255.0", subnet_primary_route=f"{net}.0/24",
                                 hsrp_behavior=f"HSRP grp {vid} Active VIP {net}.1")},
            "CORE2": {port: _svi(port, svi_ip=f"{net}.3 255.255.255.0", subnet_primary_route=f"{net}.0/24",
                                 hsrp_behavior=f"HSRP grp {vid} Standby VIP {net}.1")}}


def _capture(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


UP = "Track 1\n  IP SLA 1 reachability\n  Reachability is Up\n"
DOWN = "Track 2\n  Interface GigabitEthernet1/0/1 line-protocol\n  Line protocol is Down\n"


def test_the_copied_flags_and_markers_are_the_producers(tmp_path):
    assert ui.NOT_OBSERVED_SENTINEL == excel.HEALTH_NOT_OBSERVED == MARKER
    assert ui.L3_RISK_TRACKING_NOT_ASSESSED == TRACK_NOT_ASSESSED
    assert set(ui.L3_RISK_FLAGS) == set(analyze.ScoringConfig().l3_weights)
    tree = ast.parse(textwrap.dedent(inspect.getsource(excel.write_l3_forwarding_sheet)))
    calls = sorted((n.lineno, n.col_offset, n.args[0].value) for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
                   and isinstance(n.func.value, ast.Name) and n.func.value.id == "flags"
                   and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str))
    # the flags in the order the producer appends them, which the decoder holds every stored risk text to
    assert tuple(flag for _line, _col, flag in calls) == ui.L3_RISK_FLAGS
    assert ui.L3_TRACKED_DOWN_FLAG == ui.L3_RISK_FLAGS[0] == "tracked-object-down"
    assert ui.L3_SOLE_GATEWAY_FLAG in ui.L3_RISK_FLAGS and ui.L3_NO_FHRP_FLAG in ui.L3_RISK_FLAGS
    # excel._track_summary's text: its Down head is what the tracked-object-down flag is held against
    objects = [{"id": str(i), "desc": "", "state": "Down" if i in (2, 7) else "Up"} for i in range(1, 9)]
    many = excel._track_summary({"objects": objects, "up": 6, "down": 2, "observed": True})
    up_only = excel._track_summary({"objects": objects[:1], "up": 1, "down": 0, "observed": True})
    assert many.startswith("8 obj (2 DOWN) - ") and up_only == "1 obj - T1:Up"
    assert ui._TRACK_SUMMARY.fullmatch(many).group(2) == "2"
    assert ui._TRACK_SUMMARY.fullmatch(up_only).group(2) is None
    assert excel._track_summary({"objects": [], "up": 0, "down": 0, "observed": True}) == ""
    assert excel._track_summary({"objects": [], "up": 0, "down": 0, "observed": False}) == ui.NOT_OBSERVED_SENTINEL
    # no 'show track': no flag fires on a redundant FHRP pair, so the risk is the whole-text marker
    blind = _l3(_hsrp_pair())
    assert [r["risk"] for r in blind] == [ui.L3_RISK_TRACKING_NOT_ASSESSED] * 2
    assert [r["tracking"] for r in blind] == [ui.NOT_OBSERVED_SENTINEL] * 2
    assert [r["role"] for r in blind] == ["Active", "Standby"]
    assert ui._l3_risk_flags(blind[0]["risk"]) == ()
    # one gateway with no FHRP: the sole flag, and no role
    one = _l3({"CORE1": {"Vlan30": _svi("Vlan30", svi_ip="10.0.30.1 255.255.255.0")}})
    assert (one[0]["risk"], one[0]["role"]) == (ui.L3_SOLE_GATEWAY_FLAG, "")
    # 'show track' captured with an Up object on a redundant pair: the clean word
    up = _capture(tmp_path, "up.txt", UP)
    clean = _l3(_hsrp_pair(), {"CORE1": {"show track": up}, "CORE2": {"show track": up}})
    assert [r["risk"] for r in clean] == [ui.L3_RISK_CLEAR] * 2
    assert clean[0]["tracking"] == "1 obj - T1:Up"
    # a Down object on a sole gateway: two flags, in the producer's order, with its joiner
    down = _capture(tmp_path, "down.txt", DOWN)
    both = _l3({"CORE1": {"Vlan30": _svi("Vlan30", svi_ip="10.0.30.1 255.255.255.0")}},
               {"CORE1": {"show track": down}})
    assert both[0]["risk"] == ui.L3_RISK_JOINER.join(("tracked-object-down", ui.L3_SOLE_GATEWAY_FLAG))
    assert ui._l3_risk_flags(both[0]["risk"]) == ("tracked-object-down", ui.L3_SOLE_GATEWAY_FLAG)
    # two gateways without FHRP on a subnet with free host addresses
    pair = _l3({"CORE1": {"Vlan12": _svi("Vlan12", svi_ip="10.0.12.2 255.255.255.0")},
                "CORE2": {"Vlan12": _svi("Vlan12", svi_ip="10.0.12.3 255.255.255.0")}})
    assert [r["risk"] for r in pair] == [ui.L3_NO_FHRP_FLAG] * 2
    # 'show track' captured with no tracked object: the producer's '' (collected, none)
    none = _capture(tmp_path, "none.txt", "No tracked objects are configured\n")
    empty = _l3(_hsrp_pair(), {"CORE1": {"show track": none}, "CORE2": {"show track": none}})
    assert [(r["tracking"], r["risk"]) for r in empty] == [("", ui.L3_RISK_CLEAR)] * 2
    # the VLAN cutover matrix's sole-gateway fhrp text, whose opening and closing the projection matches
    opening, closing = ui.VLAN_SOLE_GATEWAY_FHRP
    rows = analyze.compute_vlan_cutover_matrix({"CORE1": {"Vlan30": _svi("Vlan30", svi_ip="10.0.30.1 255.255.255.0")}})
    assert [(r["vlan"], r["fhrp"]) for r in rows] == [(30, f"{opening}CORE1{closing}")]
    paired = analyze.compute_vlan_cutover_matrix(_hsrp_pair())
    assert [r["vlan"] for r in paired] == [10] and isinstance(paired[0]["fhrp"], dict)


_IF_FIELDS = frozenset(f.name for f in dataclasses.fields(InterfaceData))


def test_the_producers_own_rows_project_as_gateway_rows(sample, inv_validator, tmp_path):
    snap = _covered(sample)
    ifaces = {}
    for host, ports in snap["interfaces"].items():
        ifaces[host] = {}
        for port, rec in ports.items():
            d = InterfaceData(**{k: v for k, v in rec.items() if k in _IF_FIELDS})
            d.port = port
            ifaces[host][port] = d
    rows = json.loads(json.dumps(_l3(ifaces, {"core1": {"show track": _capture(tmp_path, "core1.txt", UP)}})))
    assert any(r["switch"] == "core1" for r in rows)
    snap["l3_forwarding"] = rows
    inv = _inventory(snap, inv_validator)
    sole_seen = 0
    for row in inv["vlans"]["rows"]["items"]:
        gw = row["selections"]["gateways"]
        assert [it["index"] for it in gw["items"]] == _naming(snap, row["vlan"]["value"])
        for it in gw["items"]:
            src = rows[it["index"]]
            if src["switch"] == "core1":
                assert (it["tracking"]["state"], it["tracking"]["value"]) == (PUB, "1 obj - T1:Up"), it["tracking"]
            else:
                assert it["tracking"]["state"] == NC and "never 'no tracking'" in it["tracking"]["reason"]
            sole = SOLE in src["risk"].split("; ")
            sole_seen += sole
            assert (it["risk"]["state"], it["risk"]["value"]) == (PUB, sole), (src, it["risk"])
    assert sole_seen >= 1


# --------------------------------------------------------------------------------------------------
# (g) the closed schema and the registered limitation
# --------------------------------------------------------------------------------------------------
def test_the_closed_schema_carries_the_gateway_fact_list(sample):
    d = ui.ui_projection_schema()["$defs"]
    assert d["VlanSelections"]["properties"]["gateways"] == {"$ref": "#/$defs/VlanGatewayRowList"}
    assert "gateways" in d["VlanSelections"]["required"]
    row = d["VlanGatewayRow"]
    assert row["additionalProperties"] is False
    assert row["required"] == ["index", "pointer", "host", "svi_ip", "role", "tracking", "risk"]
    assert row["properties"]["risk"] == {"$ref": "#/$defs/FlagFact"}
    for name in ("host", "svi_ip", "role", "tracking"):
        assert row["properties"][name] == {"$ref": "#/$defs/TextFact"}, name
    pub, _withheld = d["VlanGatewayRowList"]["oneOf"]
    assert pub["properties"]["items"] == {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/VlanGatewayRow"}}
    assert CAVEAT in d["LimitationId"]["enum"]
    lim = next(lim for lim in ui.LIMITATIONS if lim["id"] == CAVEAT)
    assert lim["applies_to"] == ("/inventory/vlans/rows",)
    for phrase in ("single-gateway flag", "never 'no tracking'", "not that the gateway is healthy",
                   "at most 6 objects", "VLAN carriage per cable is not stored", "SVI named VlanN",
                   "counts gateways by VLAN id", "fhrp_detail[].track", "HSRP detail's standby router",
                   f"at most {CAP} witnesses per gap"):
        assert phrase in lim["text"], phrase
    assert ui._GW_GAP_WITNESS_CAP == CAP
    trust = ui.project_trust(sample)
    assert [x["applies_to"] for x in trust["limitations"] if x["id"] == CAVEAT] == [["/inventory/vlans/rows"]]
