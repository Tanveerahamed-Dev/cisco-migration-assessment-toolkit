"""Configured FHRP group truth reaches readiness, validation, and NRFU losslessly."""

from __future__ import annotations

from copy import deepcopy

from cisco_toolkit.analyze import (
    compute_current_baseline_gate,
    compute_migration_readiness,
    compute_validation_plan,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.fhrp_intent import (
    compute_fhrp_configured_group_baseline,
    embedded_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.nrfu_export import compute_nrfu_commands


def _current_baseline(tmp_path, *, config: str, runtime: str):
    config_path = tmp_path / "show_running-config.txt"
    runtime_path = tmp_path / "show_standby_brief.txt"
    config_path.write_text(config, encoding="utf-8")
    runtime_path.write_text(runtime, encoding="utf-8")
    paths = {"r1": {
        "show running-config": str(config_path),
        "show standby brief": str(runtime_path),
    }}
    baseline = compute_fhrp_configured_group_baseline(
        paths,
        compute_capture_integrity_from_paths(paths),
        devices={"r1": {"platform": "ios"}},
    )
    assert validate_fhrp_configured_group_baseline(
        baseline, require_current_run=True)["valid"] is True
    return baseline


def _two_configured_one_runtime(tmp_path):
    return _current_baseline(
        tmp_path,
        config=(
            "hostname r1\n"
            "interface Vlan10\n"
            " ip address 10.0.10.2 255.255.255.0\n"
            " standby 10 ip 10.0.10.1\n"
            " standby 20 ip 10.0.10.254\n"
            "end\n"
        ),
        runtime=(
            "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
            "Vl10        10   110 P Active   local           10.0.10.3      10.0.10.1\n"
        ),
    )


def _interfaces():
    return {"r1": {"Vlan10": InterfaceData(
        port="Vlan10",
        svi_ip="10.0.10.2 255.255.255.0",
        hsrp_behavior="HSRP grp 10 Active VIP 10.0.10.1",
    )}}


def _dep_map():
    return {
        "single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
        "orphan": set(), "access_by_vlan": {}, "model": {"hosts": ["r1"]},
    }


def _readiness(baseline):
    return compute_migration_readiness(
        _interfaces(), [{"switches": ["r1"], "endpoints": 0}],
        [{"switch": "r1", "band": "Good"}], [{"switch": "r1"}], [], [],
        [{"switch": "r1", "protocol": "FHRP", "severity": "Info"}],
        _dep_map(), fhrp_configured_group_baseline=baseline,
    )[0]


def _plan(baseline):
    return compute_validation_plan(
        _interfaces(), move_groups=[{"switches": ["r1"]}],
        devices={"r1": {"platform": "ios"}},
        fhrp_configured_group_baseline=baseline,
    )


def _nrfu(baseline):
    output = compute_nrfu_commands({
        "devices": {"r1": {"platform": "ios"}},
        "interfaces": _interfaces(),
        "move_groups": [{"switches": ["r1"]}],
        "fhrp_configured_group_baseline": baseline,
    })
    cases = [
        case
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "FHRP"
    ]
    return output, cases


def test_same_interface_multi_group_denominator_blocks_every_decision_surface(tmp_path):
    baseline = _two_configured_one_runtime(tmp_path)
    assert baseline["verdict"] == "BLOCKED"
    assert [(row["group"], row["status"]) for row in baseline["rows"]] == [
        ("10", "assessed"),
        ("20", "degraded"),
    ]

    readiness = _readiness(baseline)
    gateway = next(check for check in readiness["checks"]
                   if check["check"] == "Gateway redundancy")
    assert readiness["readiness"] == "NOT READY"
    assert gateway["status"] == "fail"
    assert "group 20" in gateway["note"]

    plan = _plan(baseline)
    rows = [row for row in plan["items"] if row["category"] == "FHRP"]
    assert [(row["interface"], row["group"]) for row in rows] == [
        ("Vlan10", "10"), ("Vlan10", "20"),
    ]
    assert len({row["group_key"] for row in rows}) == 2
    missing = next(row for row in rows if row["group"] == "20")
    assert missing["evidence_state"] == "degraded"
    assert missing["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert missing["configured_vip"] == "10.0.10.254"
    assert missing["runtime_observed"] is False
    assert compute_current_baseline_gate(plan)["verdict"] == "BLOCKED"

    output, cases = _nrfu(baseline)
    assert [(case["interface"], case["group"]) for case in cases] == [
        ("Vlan10", "10"), ("Vlan10", "20"),
    ]
    assert len({case["group_key"] for case in cases}) == 2
    assert output["summary"]["n_fhrp_cases"] == 2
    assert output["summary"]["n_fhrp_blockers"] == 1
    for row, case in zip(rows, cases):
        core = next(item for item in baseline["rows"] if item["group"] == row["group"])
        assert row["expect"] == case["expected"] == core["acceptance"]
        assert row["command"] == case["command"] == core["command"]
        assert row["source_key"] == case["source_key"] == core["source_key"]
        assert row["projection_custody"] == case["projection_custody"] == (
            "current_run_source_bound"
        )


def test_embedded_phase_failed_or_tampered_baseline_cannot_authorize_fhrp(tmp_path):
    current = _two_configured_one_runtime(tmp_path)
    embedded = embedded_fhrp_configured_group_baseline(current)
    assert validate_fhrp_configured_group_baseline(embedded)["valid"] is True
    rejected = validate_fhrp_configured_group_baseline(embedded, require_current_run=True)
    assert rejected["valid"] is False
    assert rejected["reason"] == "baseline_not_current_run_source_bound"

    tampered = deepcopy(embedded)
    tampered["rows"][0]["acceptance"] = "forged healthy target"
    assert validate_fhrp_configured_group_baseline(tampered)["valid"] is False

    readiness = _readiness(embedded)
    gateway = next(check for check in readiness["checks"]
                   if check["check"] == "Gateway redundancy")
    assert readiness["readiness"] == "CAUTION"
    assert gateway["status"] == "warn"

    for invalid in (embedded, {}, tampered):
        plan = _plan(invalid)
        rows = [row for row in plan["items"] if row["category"] == "FHRP"]
        assert len(rows) == 1
        assert rows[0]["group"] == ""
        assert rows[0]["evidence_state"] == "not_verified"
        assert rows[0]["expect"].startswith(
            "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:")
        assert compute_current_baseline_gate(plan)["verdict"] != "CLEAR"

        output, cases = _nrfu(invalid)
        assert len(cases) == 1
        assert cases[0]["group"] == ""
        assert cases[0]["evidence_state"] == "not_verified"
        assert cases[0]["expected"].startswith(
            "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:")
        assert output["summary"]["n_fhrp_blockers"] == 1


def test_vrrp_and_glbp_keep_subtype_commands_and_local_state_semantics(tmp_path):
    config_path = tmp_path / "show_running-config.txt"
    vrrp_path = tmp_path / "show_vrrp_brief.txt"
    glbp_path = tmp_path / "show_glbp_brief.txt"
    config_path.write_text(
        "hostname r1\n"
        "interface Vlan30\n"
        " vrrp 30 ip 10.0.30.1\n"
        "interface Vlan40\n"
        " glbp 40 ip 10.0.40.1\n"
        "end\n",
        encoding="utf-8",
    )
    vrrp_path.write_text(
        "Interface          Grp Pri Time  Own Pre State   Master addr     Group addr\n"
        "Vl30               30  110 3570      Y  Master  10.0.30.2      10.0.30.1\n",
        encoding="utf-8",
    )
    glbp_path.write_text(
        "Interface Grp Fwd Pri State  Address       Active router Standby router\n"
        "Vl40      40  -   110 Active 10.0.40.1    local         10.0.40.3\n",
        encoding="utf-8",
    )
    paths = {"r1": {
        "show running-config": str(config_path),
        "show vrrp brief": str(vrrp_path),
        "show glbp brief": str(glbp_path),
    }}
    baseline = compute_fhrp_configured_group_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"r1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "CLEAR"
    assert [(row["protocol"], row["runtime_state"], row["command"], row["status"])
            for row in baseline["rows"]] == [
        ("VRRP", "MASTER", "show vrrp brief", "assessed"),
        ("GLBP", "ACTIVE", "show glbp brief", "assessed"),
    ]

    plan_rows = [row for row in _plan(baseline)["items"] if row["category"] == "FHRP"]
    output, cases = _nrfu(baseline)
    assert [(row["protocol"], row["command"]) for row in plan_rows] == [
        ("GLBP", "show glbp brief"), ("VRRP", "show vrrp brief"),
    ]
    assert {(case["protocol"], case["command"]) for case in cases} == {
        ("VRRP", "show vrrp brief"), ("GLBP", "show glbp brief"),
    }
    assert output["summary"]["n_fhrp_cases"] == 2
    assert output["summary"]["n_fhrp_blockers"] == 0


def test_coverage_only_indeterminate_fails_closed_without_inventing_a_subject():
    paths = {"r1": {}}
    baseline = compute_fhrp_configured_group_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"r1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["rows"] == []
    assert [(cell["protocol"], cell["subject"], cell["status"])
            for cell in baseline["coverage"]] == [
        ("HSRP", False, "not_verified"),
        ("VRRP", False, "not_verified"),
        ("GLBP", False, "not_verified"),
    ]

    readiness = _readiness(baseline)
    gateway = next(check for check in readiness["checks"]
                   if check["check"] == "Gateway redundancy")
    assert readiness["readiness"] == "CAUTION"
    assert gateway["status"] == "warn"
    assert "INDETERMINATE" in gateway["note"]

    plan = _plan(baseline)
    rows = [row for row in plan["items"] if row["category"] == "FHRP"]
    assert {(row["protocol"], row["group"], row["evidence_state"]) for row in rows} == {
        ("HSRP", "", "not_verified"),
        ("VRRP", "", "not_verified"),
        ("GLBP", "", "not_verified"),
    }
    assert all(row["expect"].startswith(
        "FHRP CONFIGURED GROUP NOT VERIFIED — BLOCKER:") for row in rows)
    gate = compute_current_baseline_gate(plan)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["summary"]["by_state"]["not_verified"] == 3

    output, cases = _nrfu(baseline)
    assert {(case["protocol"], case["group"], case["evidence_state"])
            for case in cases} == {
        ("HSRP", "", "not_verified"),
        ("VRRP", "", "not_verified"),
        ("GLBP", "", "not_verified"),
    }
    assert output["summary"]["n_fhrp_cases"] == 3
    assert output["summary"]["n_fhrp_blockers"] == 3


def test_not_applicable_is_neutral_only_inside_current_run_boundary(tmp_path):
    baseline = _current_baseline(
        tmp_path,
        config="hostname r1\ninterface Loopback0\n description no-fhrp\nend\n",
        runtime=(
            "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
        ),
    )
    assert baseline["verdict"] == "NOT_APPLICABLE"
    readiness = _readiness(baseline)
    gateway = next(check for check in readiness["checks"]
                   if check["check"] == "Gateway redundancy")
    assert gateway["status"] == "info"
    assert "not FHRP health" in gateway["note"]
    assert [row for row in _plan(baseline)["items"] if row["category"] == "FHRP"] == []
    output, cases = _nrfu(baseline)
    assert cases == []
    assert output["summary"]["n_fhrp_blockers"] == 0

    # Serialization deliberately erases source-bound custody; it cannot re-authorize absence.
    output, cases = _nrfu(embedded_fhrp_configured_group_baseline(baseline))
    assert cases and all(case["evidence_state"] == "not_verified" for case in cases)
    assert output["summary"]["n_fhrp_blockers"] == len(cases)
