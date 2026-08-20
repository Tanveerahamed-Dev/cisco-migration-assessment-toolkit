"""Current-run VTP safety truth reaches every cutover decision consumer."""

from __future__ import annotations

import json
from copy import deepcopy

from cisco_toolkit.analyze import (
    compute_current_baseline_gate,
    compute_migration_punchlist,
    compute_migration_readiness,
    compute_protocol_assessability,
    compute_protocol_health,
    compute_validation_plan,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.nrfu_export import compute_nrfu_commands
from cisco_toolkit.vtp_safety import (
    compute_vtp_safety_baseline,
    compute_vtp_safety_subject_scope,
    embedded_vtp_safety_baseline,
    scope_vtp_safety_subjects,
    validate_vtp_safety_baseline,
)


def _owner(tmp_path, *, mode: str = "Server", domain: str = "CAMPUS",
           revision: int = 150):
    capture = tmp_path / "show_vtp_status.txt"
    capture.write_text(
        "VTP Version capable             : 1 to 3\n"
        "VTP version running             : 2\n"
        f"VTP Domain Name                 : {domain}\n"
        f"VTP Operating Mode              : {mode}\n"
        f"Configuration Revision          : {revision}\n",
        encoding="utf-8",
    )
    paths = {"sw1": {"show vtp status": str(capture)}}
    integrity = compute_capture_integrity_from_paths(paths)
    baseline = compute_vtp_safety_baseline(
        paths, integrity, devices={"sw1": {"platform": "ios"}})
    health = compute_protocol_health({"sw1": {}}, paths)
    receipt = compute_protocol_assessability(
        ["sw1"], {"sw1": {}}, paths, health)
    assert validate_vtp_safety_baseline(
        baseline, require_current_run=True)["valid"] is True
    return baseline, health, receipt


def _dep_map():
    return {
        "single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
        "orphan": set(), "access_by_vlan": {}, "model": {"hosts": ["sw1"]},
    }


def _surfaces(baseline, health, receipt, *, subject_scope=None):
    interfaces = {"sw1": {}}
    groups = [{"switches": ["sw1"], "endpoints": 0}]
    devices = {"sw1": {"platform": "ios"}}
    readiness = compute_migration_readiness(
        interfaces, groups, [{"switch": "sw1", "band": "Good"}],
        [{"switch": "sw1"}], [], [], health, _dep_map(),
        protocol_assessability=receipt, vtp_safety_baseline=baseline,
        vtp_safety_subject_scope=subject_scope,
    )[0]
    plan = compute_validation_plan(
        interfaces, move_groups=groups, devices=devices,
        protocol_health=health, protocol_assessability=receipt,
        vtp_safety_baseline=baseline,
        vtp_safety_subject_scope=subject_scope,
    )
    nrfu = compute_nrfu_commands({
        "devices": devices,
        "interfaces": interfaces,
        "move_groups": groups,
        "protocol_health": health,
        "protocol_assessability": receipt,
        "vtp_safety_baseline": baseline,
        "vtp_safety_subject_scope": subject_scope,
    })
    cases = [
        case
        for wave in nrfu["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "VTP"
    ]
    punchlist = compute_migration_punchlist(
        [], {}, {}, [], [], health, {}, [], groups,
        protocol_assessability=receipt, vtp_safety_baseline=baseline,
        vtp_safety_subject_scope=subject_scope,
    )
    return readiness, plan, nrfu, cases, punchlist


def test_high_revision_server_withholds_ready_and_clear_everywhere(tmp_path):
    baseline, health, receipt = _owner(tmp_path, revision=150)
    assert baseline["verdict"] == "INDETERMINATE"
    assert len(baseline["rows"]) == 1
    owner = baseline["rows"][0]
    assert owner["status"] == "review"
    assert owner["revision"] == 150
    assert owner["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")

    readiness, plan, nrfu, cases, punchlist = _surfaces(
        baseline, health, receipt)
    vtp_check = next(row for row in readiness["checks"]
                     if row["check"] == "VTP cutover safety")
    assert readiness["readiness"] == "CAUTION"
    assert vtp_check["status"] == "warn"
    assert "revision 150" in vtp_check["note"]

    validation = [row for row in plan["items"] if row["category"] == "VTP"]
    assert len(validation) == len(cases) == 1
    row = validation[0]
    case = cases[0]
    assert row["evidence_state"] == case["evidence_state"] == "review"
    assert row["expect"] == case["expected"] == owner["acceptance"]
    assert row["command"] == case["command"] == owner["command"]
    assert row["source_key"] == case["source_key"] == owner["source_key"]
    assert row["projection_custody"] == case["projection_custody"] == owner[
        "projection_custody"]
    assert case["vtp_revision"] == 150
    assert case["vtp_revision_present"] is True
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert nrfu["summary"]["n_vtp_safety_cases"] == 1
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "VTP"]) == 1


def test_low_revision_observation_is_bounded_clear_not_a_propagation_claim(tmp_path):
    baseline, health, receipt = _owner(tmp_path, revision=99)
    assert baseline["verdict"] == "CLEAR"
    assert baseline["rows"][0]["status"] == "assessed"

    readiness, plan, nrfu, cases, punchlist = _surfaces(
        baseline, health, receipt)
    check = next(row for row in readiness["checks"]
                 if row["check"] == "VTP cutover safety")
    assert readiness["readiness"] == "READY"
    assert check["status"] == "pass"
    assert "does not prove database authority" in check["note"]
    assert compute_current_baseline_gate(plan)["verdict"] == "CLEAR"
    assert len(cases) == 1 and cases[0]["evidence_state"] == "assessed"
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 0
    assert [row for row in punchlist if row["category"] == "VTP"] == []


def test_embedded_phase_failed_and_tampered_receipts_fail_closed_without_echo(tmp_path):
    current, health, receipt = _owner(tmp_path, revision=150)
    embedded = embedded_vtp_safety_baseline(current)
    tampered = deepcopy(embedded)
    tampered["rows"][0]["acceptance"] = "HOSTILE HEALTHY VTP TARGET"

    for rejected in (embedded, {}, tampered):
        readiness, plan, nrfu, cases, punchlist = _surfaces(
            rejected, health, receipt)
        validation = [row for row in plan["items"] if row["category"] == "VTP"]
        assert readiness["readiness"] == "CAUTION"
        assert len(validation) == len(cases) == 1
        assert validation[0]["evidence_state"] == cases[0]["evidence_state"] == "not_verified"
        assert validation[0]["expect"].startswith(
            "VTP SAFETY BASELINE NOT VERIFIED — BLOCKER:")
        assert cases[0]["expected"].startswith(
            "VTP SAFETY BASELINE NOT VERIFIED — BLOCKER:")
        assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
        assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
        assert len([row for row in punchlist if row["category"] == "VTP"]) == 1
        assert "HOSTILE HEALTHY VTP TARGET" not in json.dumps(plan)
        assert "HOSTILE HEALTHY VTP TARGET" not in json.dumps(nrfu)


def test_no_positive_vtp_subject_remains_neutral():
    baseline = compute_vtp_safety_baseline(
        {}, compute_capture_integrity_from_paths({}),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "NOT_APPLICABLE"
    receipt = compute_protocol_assessability(
        ["sw1"], {"sw1": {}}, {}, [])
    readiness, plan, nrfu, cases, punchlist = _surfaces(
        baseline, [], receipt)
    assert readiness["readiness"] == "READY"
    assert not any(row["check"] == "VTP cutover safety" for row in readiness["checks"])
    assert [row for row in plan["items"] if row["category"] == "VTP"] == []
    assert cases == []
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 0
    assert [row for row in punchlist if row["category"] == "VTP"] == []


def test_phase_failure_keeps_an_attempted_empty_status_capture_in_scope(tmp_path):
    capture = tmp_path / "empty-vtp-status.txt"
    capture.write_text("", encoding="utf-8")
    paths = {"sw1": {"show vtp status": str(capture)}}
    receipt = compute_protocol_assessability(
        ["sw1"], {"sw1": {}}, paths, [])
    vtp_cell = next(row for row in receipt["rows"] if row["protocol"] == "VTP")
    assert vtp_cell["input_states"]["status"] == "empty"

    readiness, plan, nrfu, cases, punchlist = _surfaces({}, [], receipt)
    assert readiness["readiness"] == "CAUTION"
    assert len([row for row in plan["items"] if row["category"] == "VTP"]) == 1
    assert len(cases) == 1 and cases[0]["evidence_state"] == "not_verified"
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "VTP"]) == 1


def test_unreadable_attempted_status_capture_uses_path_free_scope_and_fails_closed(tmp_path):
    missing = tmp_path / "missing-vtp-status.txt"
    paths = {"sw1": {"show vtp status": str(missing)}}
    devices = {"sw1": {"platform": "ios"}}
    scope = scope_vtp_safety_subjects(paths, devices=devices)
    assert scope == {
        "schema": "vtp_safety_subject_scope/1", "valid": True,
        "attempted": True, "reason": "ok", "rows": [{
            "switch": "sw1", "platform": "ios", "command": "show vtp status",
        }],
    }
    receipt = compute_protocol_assessability(
        ["sw1"], {"sw1": {}}, paths, [])
    vtp_cell = next(row for row in receipt["rows"] if row["protocol"] == "VTP")
    assert vtp_cell["input_states"]["status"] == "missing"

    readiness, plan, nrfu, cases, punchlist = _surfaces(
        {}, [], receipt, subject_scope=scope)
    validation = [row for row in plan["items"] if row["category"] == "VTP"]
    assert readiness["readiness"] == "CAUTION"
    assert len(validation) == len(cases) == 1
    assert validation[0]["evidence_state"] == cases[0]["evidence_state"] == "not_verified"
    assert "vtp_safety_subject_scope[sw1]" in validation[0]["source_key"]
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "VTP"]) == 1


def test_non_high_revision_review_uses_generic_operator_wording(tmp_path):
    baseline, health, receipt = _owner(
        tmp_path, mode="Client", domain="", revision=4)
    assert baseline["rows"][0]["status"] == "review"
    assert {finding["code"] for finding in baseline["rows"][0]["findings"]} == {
        "active_mode_domain_empty",
    }

    readiness, plan, _, _, punchlist = _surfaces(baseline, health, receipt)
    row = next(item for item in plan["items"] if item["category"] == "VTP")
    punch = next(item for item in punchlist if item["category"] == "VTP")
    assert row["check"] == "VTP cutover safety review"
    assert punch["title"] == "VTP cutover safety review"
    rendered = json.dumps([readiness, row, punch])
    assert "high-revision cutover exposure" not in rendered
    assert "resolve or explicitly disposition the local VTP safety finding" in rendered


def test_rejected_ambiguous_attempt_scope_yields_unattributed_blocker(tmp_path):
    missing = tmp_path / "missing.txt"
    paths = {
        "sw1": {"show vtp status": str(missing)},
        "SW1": {"show vtp status": str(missing)},
    }
    scope = compute_vtp_safety_subject_scope(paths)
    assert scope["valid"] is False
    assert scope["attempted"] is True
    assert scope["rows"] == []
    receipt = compute_protocol_assessability(
        ["sw1", "SW1"], {"sw1": {}, "SW1": {}}, paths, [])

    readiness, plan, nrfu, cases, punchlist = _surfaces(
        {}, [], receipt, subject_scope=scope)
    validation = [row for row in plan["items"] if row["category"] == "VTP"]
    assert readiness["readiness"] == "CAUTION"
    assert len(validation) == len(cases) == 1
    assert validation[0]["device"] == "(VTP subject scope not verified)"
    assert validation[0]["evidence_state"] == cases[0]["evidence_state"] == "not_verified"
    assert validation[0]["source_key"] == (
        "vtp_safety_subject_scope.valid/attempted/reason + vtp_safety_baseline")
    assert "scope_identity_collision" in validation[0]["why"]
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "VTP"]) == 1


def test_malformed_scope_receipt_cannot_authorize_neutral_omission():
    malformed_scopes = [
        [],
        {"schema": "vtp_safety_subject_scope/1", "valid": True,
         "attempted": True, "reason": "ok", "rows": []},
        {"schema": "vtp_safety_subject_scope/1", "valid": True,
         "attempted": False, "reason": "ok", "rows": [], "extra": "HOSTILE"},
    ]
    receipt = compute_protocol_assessability(
        ["sw1"], {"sw1": {}}, {}, [])
    for scope in malformed_scopes:
        readiness, plan, nrfu, cases, _ = _surfaces(
            {}, [], receipt, subject_scope=scope)
        validation = [row for row in plan["items"] if row["category"] == "VTP"]
        assert readiness["readiness"] == "CAUTION"
        assert len(validation) == len(cases) == 1
        assert validation[0]["device"] == "(VTP subject scope not verified)"
        assert validation[0]["source_key"] == (
            "vtp_safety_subject_scope.valid/attempted/reason + vtp_safety_baseline")
        assert "scope_contract_invalid" in validation[0]["why"]
        assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
        assert nrfu["summary"]["n_vtp_safety_blockers"] == 1
        assert "HOSTILE" not in json.dumps([validation, nrfu])
