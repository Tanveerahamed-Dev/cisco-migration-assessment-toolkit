"""Stored-DoS guard: a malformed snapshot value must not 500 GET /api/snapshots/{id}/cutover.

The read route synthesizes the cutover plan straight from the stored snapshot (``cutover.build_plan``),
so ANY value in a cutover-consumed section that a hand-crafted / hostile ``--no-collect`` upload can carry
must degrade gracefully rather than raise. The POST is accepted (201) and the snapshot is stored first, so
a value that raises inside ``build_plan`` is a STORED availability DoS: every later GET /cutover 500s.

This file guards the WHOLE cutover class, not just two helpers:
  * ``_rows`` -- a section that is a truthy non-list (``5`` -> ``for r in 5``);
  * ``_by_group`` / the wave ``group`` -- an UNHASHABLE group value (``["a","b"]`` used as a dict key /
    ``dict.get`` key);
  * ``build_plan`` section reads -- ``remediation_plan`` / ``validation_plan`` (or their ``by_device`` /
    ``by_wave``) a truthy non-dict (``.get`` on an int);
  * ``build_plan`` ``list(...)`` coercions -- ``make_before_break`` / ``hard_cutover`` / ``gateways`` /
    ``spanning_vlans`` a non-iterable (``list(5)``), or a list of ints that then hits ``', '.join`` in the
    run-of-show;
  * ``_wave_remediation`` / ``_wave_validation`` -- a per-item value that is a truthy non-list, AND their
    whole ``by_device`` / ``by_wave`` container being a non-dict;
  * the sibling set-key helpers ``_keystone_hosts`` / ``_blind_hosts`` / ``_worst_blast_radius`` /
    ``_blockers`` -- an unhashable host added to / tested against a set, or a non-iterable ``checks``.

The fix coerces via ``summary._as_list`` / a local ``_as_dict`` / ``_as_hosts`` / ``str(...)`` -- the
module's own degrade-gracefully discipline. Non-vacuity: every ``*_int`` / ``*_unhashable`` case here 500s
against the pre-guard code (proven by running this file before the cutover.py guards are applied).
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

from backend.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    # base_url=localhost so the default Host passes the no-token guard, matching the emulated loopback dev
    # server; raise_server_exceptions=False so a stored-DoS surfaces as a 500 RESPONSE we can assert on
    # (not a raised exception), matching how a real client experiences it.
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        yield c


def _upload(client, snap):
    cid = client.post("/api/campaigns", json={"name": "c"}).json()["id"]
    r = client.post(
        f"/api/campaigns/{cid}/snapshots",
        files={"file": ("s.json", json.dumps(snap).encode(), "application/json")},
        data={"label": "s"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _get_cutover(client, snap):
    """POST the poison (accepted 201 -> stored), then GET the cutover plan for it."""
    sid = _upload(client, snap)
    return client.get(f"/api/snapshots/{sid}/cutover")


def _base():
    """A minimal well-formed snapshot with ONE wave, so build_plan actually runs its helpers."""
    return {
        "devices": {"sw1": {}},
        "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"], "make_before_break": ["sw2"]}],
    }


def _wave(**over):
    w = {"group": "W1", "hard_cutover": ["sw1"], "make_before_break": ["sw2"]}
    w.update(over)
    return w


# ---- original targeted cases: inner per-item value a truthy non-list (guarded by summary._as_list) -----
_POISON_REMEDIATION = {
    "devices": {"sw1": {}},
    "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
    "remediation_plan": {"by_device": {"sw1": 5}},   # inner per-device value a truthy non-list
}
_POISON_VALIDATION = {
    "devices": {"sw1": {}},
    "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"]}],
    "validation_plan": {"by_wave": {"W1": 5}},        # inner per-wave value a truthy non-list
}


@pytest.mark.parametrize(
    "snap",
    [_POISON_REMEDIATION, _POISON_VALIDATION],
    ids=["remediation_by_device_scalar", "validation_by_wave_scalar"],
)
def test_cutover_read_route_survives_truthy_nonlist_wave_helper_value(client, snap):
    """POST the poison (201), then GET the cutover plan: it must render (200), never 500."""
    r = _get_cutover(client, snap)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"


# ---- WHOLE-class sweep 1: every cutover-consumed TOP-LEVEL section x {int, str, list} ------------------
_SECTIONS = [
    "wave_sequencing", "migration_readiness", "move_groups", "failure_impact",
    "cross_layer", "health_scores", "remediation_plan", "validation_plan", "executive_brief",
]


@pytest.mark.parametrize("section", _SECTIONS)
@pytest.mark.parametrize("value", [5, "x", [1, 2]], ids=["int", "str", "list"])
def test_cutover_survives_toplevel_section_poison(client, section, value):
    snap = _base()
    snap[section] = value
    r = _get_cutover(client, snap)
    assert r.status_code == 200, f"section={section} value={value!r} -> {r.status_code}: {r.text[:200]}"


# ---- WHOLE-class sweep 2: deeper per-field poison inside otherwise well-formed sections ---------------
_DEEP_CASES = {
    # remediation_plan / its by_device a non-dict -> build_plan:309 .get on non-dict / _wave_remediation.items()
    "rem_plan_int": {**_base(), "remediation_plan": 5},
    "rem_by_device_int": {**_base(), "remediation_plan": {"by_device": 5}},
    "rem_by_device_str": {**_base(), "remediation_plan": {"by_device": "x"}},
    "rem_by_device_list": {**_base(), "remediation_plan": {"by_device": [1, 2]}},
    "rem_inner_str": {**_base(), "remediation_plan": {"by_device": {"sw1": "x"}}},
    # validation_plan / its by_wave a non-dict -> build_plan:310 .get on non-dict / _wave_validation.get
    "val_plan_int": {**_base(), "validation_plan": 5},
    "val_by_wave_int": {**_base(), "validation_plan": {"by_wave": 5}},
    "val_by_wave_str": {**_base(), "validation_plan": {"by_wave": "x"}},
    "val_by_wave_list": {**_base(), "validation_plan": {"by_wave": [1, 2]}},
    "val_inner_str": {**_base(), "validation_plan": {"by_wave": {"W1": "x"}}},
    # wave bucket fields non-iterable / list-of-ints -> build_plan:318/319 list(); _run_of_show ', '.join
    "mbb_int": {**_base(), "wave_sequencing": [_wave(make_before_break=5)]},
    "mbb_str": {**_base(), "wave_sequencing": [_wave(make_before_break="x")]},
    "mbb_list_ints": {**_base(), "wave_sequencing": [_wave(make_before_break=[1, 2])]},
    "hard_int": {**_base(), "wave_sequencing": [_wave(hard_cutover=5)]},
    "hard_list_ints": {**_base(), "wave_sequencing": [_wave(hard_cutover=[1, 2])]},
    # move_group sub-fields non-iterable -> build_plan:352/353 list(); the mg must overlap the wave to be picked
    "mg_gateways_int": {**_base(), "move_groups": [{"switches": ["sw1"], "gateways": 5}]},
    "mg_gateways_list_ints": {**_base(), "move_groups": [{"switches": ["sw1"], "gateways": [1, 2]}]},
    "mg_spanning_vlans_int": {**_base(), "move_groups": [{"switches": ["sw1"], "spanning_vlans": 5}]},
    # UNHASHABLE group key -> _by_group dict key / build_plan readiness+validation lookups
    "readiness_group_unhashable": {**_base(), "migration_readiness": [{"group": ["a", "b"], "readiness": "READY"}]},
    "wave_group_unhashable": {**_base(), "wave_sequencing": [_wave(group=["a", "b"])]},
    # readiness.checks non-iterable -> _blockers
    "readiness_checks_int": {**_base(), "migration_readiness": [{"group": "W1", "checks": 5}]},
    # UNHASHABLE host added to / tested against a set (sibling helpers, same class)
    "failure_impact_host_unhashable": {
        **_base(), "failure_impact": [{"host": ["a", "b"], "severity": "Critical", "stranded": 3}]},
    "health_scores_switch_unhashable": {
        **_base(), "health_scores": [{"switch": ["a", "b"], "band": "Insufficient Data"}]},
    "exec_brief_keystone_host_unhashable": {
        **_base(), "executive_brief": {"keystones": [{"host": ["a", "b"]}]}},
    # cross_layer hosts non-iterable (already robust via _as_hosts; kept as a regression guard)
    "crosslayer_hosts_int": {**_base(), "cross_layer": [{"severity": "Critical", "hosts": 5}]},
}


@pytest.mark.parametrize("snap", list(_DEEP_CASES.values()), ids=list(_DEEP_CASES.keys()))
def test_cutover_survives_deep_field_poison(client, snap):
    r = _get_cutover(client, snap)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"


def test_cutover_wellformed_still_produces_coherent_plan(client):
    """Non-vacuity anchor: a well-formed snapshot yields 200 with a coherent, POPULATED plan -- proving the
    guards degrade only garbage, and the wave helpers still run on good input."""
    validation = {"device": "sw1", "platform": "ios", "wave": "W1", "category": "Reachability",
                  "severity": "High", "check": "reachability", "command": "ping",
                  "expect": "Success rate is 100 percent", "why": "Proves post-cut reachability",
                  "evidence_state": "assessed", "projection_custody": "embedded_unverified",
                  "source_key": "validation.sw1"}
    snap = {
        "devices": {"sw1": {}, "sw2": {}},
        "wave_sequencing": [{"group": "W1", "hard_cutover": ["sw1"], "make_before_break": ["sw2"],
                             "hard_cutover_endpoints": 4}],
        "migration_readiness": [{"group": "W1", "readiness": "READY", "n_fail": 0, "n_warn": 0}],
        "remediation_plan": {"by_device": {"sw1": [{"title": "Add redundant uplink", "severity": "High"}]}},
        "validation_plan": {
            "items": [validation], "by_wave": {"W1": [validation]},
            "summary": {"n_items": 1, "n_waves": 1,
                        "by_category": {"Reachability": 1}, "n_high": 1},
        },
    }
    r = _get_cutover(client, snap)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["n_waves"] == 1
    assert len(body["waves"]) == 1
    w = body["waves"][0]
    assert w["group"] == "W1"
    assert w["hard_cutover"] == ["sw1"]
    assert w["make_before_break"] == ["sw2"]
    assert any(row["title"] == "Add redundant uplink" for row in w["remediation"])
    assert any(row["check"] == "reachability" for row in w["validation"])
