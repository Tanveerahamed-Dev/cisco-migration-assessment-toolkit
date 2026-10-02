"""Adversarial G15 consumers: raw compatibility mirrors must not outrank owner verdicts."""
import json
import shutil
import subprocess
from pathlib import Path

import openpyxl
import pytest

from cisco_toolkit import design_advisor, nrfu_export
from cisco_toolkit.excel import write_vlan_cutover_sheet
from cisco_toolkit.stp_topology import classify_stp_root_election


def _row(**over):
    return {"is_root": True, "root_address": "aaaa.0000.0001", "root_priority": 32798, **over}


def _explorer(tmp_path, expression, snapshot=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = (Path(nrfu_export.__file__).parent / "blast_radius_explorer.html").read_text(encoding="utf-8")
    start = html.index("function stpElectionPriority(")
    election = html[start:html.index("function epIdentity(", start)]
    start = html.index("function stpRootCard(")
    card = html[start:html.index("/* review r10", start)]
    start = html.index("function abH_stp(")
    assistant = html[start:html.index("function abH_fhrpgaps(", start)]
    start = html.index("const ABQ_AUTO=[")
    auto = html[start:html.index(" [/fhrp|", start)] + "];\n"
    driver = tmp_path / "g15-surfaces.js"
    driver.write_text(
        "const SNAP=JSON.parse(" + json.dumps(json.dumps(snapshot or {})) + ");\n"
        + "const esc=String, shortName=String, abHostLink=String, abAskAct=()=>()=>{};\n"
        + "const abKv=(k,v)=>k+': '+v;\n" + election + card + assistant + auto
        + "\nprocess.stdout.write(JSON.stringify(" + expression + "));\n", encoding="utf-8")
    result = subprocess.run([node, str(driver)], capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("address", ["__proto__", "constructor", "toString", None])
def test_explorer_identity_dictionary_and_null_address_match_owner(tmp_path, address):
    raw = {"a": {"30": _row(root_address=address)}}
    got = _explorer(tmp_path, "stpRootElection(" + json.dumps(raw) + ")")
    want = classify_stp_root_election(raw)["pvst_vlan"]["30"]
    assert got["30"] == {key: want[key] or "" if key == "root" else want[key]
                         for key in ("state", "reason", "root", "claimants", "root_priority", "default_election")}


@pytest.mark.parametrize("bad", [None, [], 7, "claimed"])
def test_explorer_nonmapping_row_prevents_positive_root(tmp_path, bad):
    raw = {"a": {"30": _row()}, "b": {"30": bad}}
    got = _explorer(tmp_path, "stpRootElection(" + json.dumps(raw) + ")")
    assert got["30"]["state"] == "ambiguous"
    assert got["30"]["reason"] == "malformed_root_rows"
    assert got["30"]["root"] == ""


@pytest.mark.parametrize("number", ["9007199254740992", 9007199254740992, "00000000000000030", "٣٠", True])
def test_explorer_numeric_parity_rejects_unusable_priority_and_vlan(tmp_path, number):
    raw = {"a": {"30": _row(root_priority=number), str(number): _row()}}
    got = _explorer(tmp_path, "stpRootElection(" + json.dumps(raw) + ")")
    want = classify_stp_root_election(raw)["pvst_vlan"]
    assert set(got) == set(want)
    assert got["30"]["root_priority"] == want["30"]["root_priority"]
    assert got["30"]["default_election"] == want["30"]["default_election"]
    assert got["30"]["state"] == want["30"]["state"]
    assert got["30"]["claimants"] == want["30"]["claimants"]


def test_explorer_prefers_present_engine_election_over_raw_compatibility_mirror(tmp_path):
    snap = {"stp_roots": {"wrong": {"30": _row()}}, "vlan_cutover": [
        {"vlan": 30, "stp_root_state": "ambiguous", "stp_root_reason": "duplicate_bridge_identity",
         "stp_root": "[AMBIGUOUS]", "stp_root_claimants": ["a", "b"],
         "stp_root_default_election": None},
        {"vlan": 10, "stp_root_state": "published", "stp_root_reason": "single_claimant",
         "stp_root": "right", "stp_root_claimants": ["right"], "stp_root_default_election": False},
    ]}
    got = _explorer(tmp_path, "({owner:stpRootElection(),root:stpRootFor(30),"
                    "raw:stpRootElection(SNAP.stp_roots),card:stpRootCard(),assistant:abH_stp().html,auto:ABQ_AUTO[0][1]()})", snap)
    assert got["root"] == ""
    assert got["owner"]["30"]["claimants"] == ["a", "b"]
    assert got["owner"]["10"]["root"] == "right"
    assert got["raw"]["30"]["root"] == "wrong"
    assert "root ambiguous" in got["card"]
    assert "wrong" not in got["card"]
    assert "Ambiguous roots" in got["assistant"]
    assert "wrong" not in got["assistant"]
    assert "AMBIGUOUS" in got["auto"]


def test_explorer_engine_election_renders_without_legacy_root_section(tmp_path):
    snap = {"vlan_cutover": [{"vlan": 30, "stp_root_state": "ambiguous",
                             "stp_root_reason": "duplicate_bridge_identity",
                             "stp_root_claimants": ["a", "b"], "stp_root_default_election": None}]}
    got = _explorer(tmp_path, "({card:stpRootCard(),assistant:abH_stp().html,auto:ABQ_AUTO[0][1]()})", snap)
    assert "root ambiguous" in got["card"]
    assert "Ambiguous roots" in got["assistant"]
    assert got["auto"] and "AMBIGUOUS" in got["auto"]


def test_explorer_engine_unknown_state_never_falls_back_to_raw_root(tmp_path):
    snap = {"stp_roots": {"wrong": {"30": _row()}}, "vlan_cutover": [
        {"vlan": 30, "stp_root_state": "invalid", "stp_root": "wrong"}]}
    assert _explorer(tmp_path, "stpRootFor(30)", snap) == ""


@pytest.mark.parametrize("host", ["__proto__", "constructor"])
def test_explorer_root_host_name_cannot_collide_with_assistant_dictionary(tmp_path, host):
    snap = {"stp_roots": {host: {"30": _row()}}}
    got = _explorer(tmp_path, "({root:stpRootFor(30),assistant:abH_stp().html})", snap)
    assert got["root"] == host
    assert host in got["assistant"]


def test_explorer_malformed_engine_claimant_list_never_authorizes_root(tmp_path):
    snap = {"vlan_cutover": [{"vlan": 30, "stp_root_state": "published", "stp_root": "a",
                             "stp_root_claimants": ["a", None], "stp_root_default_election": False}]}
    assert _explorer(tmp_path, "stpRootFor(30)", snap) == ""


def test_explorer_legacy_cutover_row_without_state_uses_raw_mirror(tmp_path):
    snap = {"stp_roots": {"a": {"30": _row()}}, "vlan_cutover": [{"vlan": 30, "stp_root": "old"}]}
    assert _explorer(tmp_path, "stpRootFor(30)", snap) == "a"


@pytest.mark.parametrize("snap", [
    {"stp_roots": {"a": {"30": _row(root_priority="invalid")}}},
    {"vlan_cutover": [{"vlan": 30, "stp_root_state": "published", "stp_root": "a",
                       "stp_root_claimants": ["a"], "stp_root_default_election": None}]},
])
def test_explorer_undetermined_default_election_cannot_read_as_engineered(tmp_path, snap):
    got = _explorer(tmp_path, "({card:stpRootCard(),assistant:abH_stp().html,auto:ABQ_AUTO[0][1]()})", snap)
    assert "undetermined" in got["card"].lower()
    assert "deliberate (non-default) priority" not in got["card"]
    assert "undetermined" in got["assistant"].lower()
    assert "priorities look engineered" not in got["assistant"]
    assert "undetermined" in got["auto"].lower()


def test_design_advisor_keeps_full_claimant_cardinality_before_display_cap():
    raw = {f"a{i:02}": {"30": _row()} for i in range(17)}
    sig = design_advisor._signals({"stp_roots": raw})
    decision = design_advisor._d_stp_root_determinism({}, sig)
    assert len(sig["stp_ambiguous_root_claimants"]) == 17
    assert "17 collected bridge(s)" in decision["evidence"]["summary"]
    assert len(decision["evidence"]["devices"]) == 12


def test_excel_not_observed_state_overrides_supplied_default_false():
    wb = openpyxl.Workbook()
    write_vlan_cutover_sheet(wb, [{"vlan": 30, "stp_root": "stale",
                                  "stp_root_state": "not_observed", "stp_root_default_election": False}])
    assert wb.worksheets[-1].cell(2, 4).value == ""


def _root_cases(raw):
    result = nrfu_export.compute_nrfu_commands({"stp_roots": raw, "devices": {h: {} for h in raw}})
    return [case for wave in result["waves"] for device in wave["devices"] for case in device["cases"]
            if case["command"].startswith("show spanning-tree vlan ")]


@pytest.mark.parametrize("token", ["broken", "٣٠", "9007199254740992", "00000000000000030"])
def test_nrfu_does_not_invent_commands_from_invalid_owner_vlan_tokens(token):
    assert _root_cases({"a": {token: _row()}}) == []


@pytest.mark.parametrize("over", [{"root_address": None}, {"is_root": "true"}, {"is_root": 0},
                                {"is_root": False, "root_address": {"bad": "address"}}])
def test_nrfu_requires_owner_publication_before_positive_root_acceptance(over):
    cases = _root_cases({"a": {"30": _row(**over)}})
    assert cases
    assert all("This bridge is the root" not in case["expected"] for case in cases)
    assert all(case.get("evidence_state") == "review" for case in cases)
