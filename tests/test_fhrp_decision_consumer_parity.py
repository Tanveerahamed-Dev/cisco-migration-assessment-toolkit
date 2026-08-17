"""Configured and observed FHRP election blockers remain lossless and additive."""

from __future__ import annotations

import pytest

from cisco_toolkit.analyze import (
    compute_current_baseline_gate,
    compute_migration_readiness,
    compute_validation_plan,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.fhrp_intent import (
    compute_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.nrfu_export import compute_nrfu_commands


def _election(tmp_path, *, second_state="Active", second_group="10",
              second_vip="10.0.10.1"):
    specifications = {
        "r1": {"state": "Active", "group": "10", "vip": "10.0.10.1"},
        "r2": {
            "state": second_state,
            "group": second_group,
            "vip": second_vip,
        },
    }
    paths = {}
    interfaces = {}
    devices = {host: {"platform": "ios"} for host in specifications}
    for address, (host, spec) in enumerate(specifications.items(), 2):
        config_path = tmp_path / f"{host}-show-running-config.txt"
        runtime_path = tmp_path / f"{host}-show-standby-brief.txt"
        config_path.write_text(
            f"hostname {host}\n"
            "interface Vlan10\n"
            f" ip address 10.0.10.{address} 255.255.255.0\n"
            f" standby {spec['group']} ip {spec['vip']}\n"
            "end\n",
            encoding="utf-8",
        )
        active = "local" if spec["state"] == "Active" else "10.0.10.2"
        standby = "10.0.10.3" if spec["state"] == "Active" else "local"
        runtime_path.write_text(
            "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
            f"Vl10        {spec['group']:<4} 110 P {spec['state']:<8} "
            f"{active:<15} {standby:<15} {spec['vip']}\n",
            encoding="utf-8",
        )
        paths[host] = {
            "show running-config": str(config_path),
            "show standby brief": str(runtime_path),
        }
        interfaces[host] = {
            "Vlan10": InterfaceData(
                port="Vlan10",
                svi_ip=f"10.0.10.{address} 255.255.255.0",
                hsrp_behavior=(
                    f"HSRP grp {spec['group']} {spec['state']} VIP {spec['vip']}"
                ),
            )
        }

    baseline = compute_fhrp_configured_group_baseline(
        paths,
        compute_capture_integrity_from_paths(paths),
        devices=devices,
    )
    assert validate_fhrp_configured_group_baseline(
        baseline, require_current_run=True
    )["valid"] is True
    return baseline, interfaces, devices


def _plan(baseline, interfaces, devices):
    return compute_validation_plan(
        interfaces,
        move_groups=[{"switches": ["r1", "r2"]}],
        devices=devices,
        fhrp_configured_group_baseline=baseline,
    )


def _nrfu(baseline, interfaces, devices):
    output = compute_nrfu_commands({
        "devices": devices,
        "interfaces": interfaces,
        "move_groups": [{"switches": ["r1", "r2"]}],
        "fhrp_configured_group_baseline": baseline,
    })
    cases = [
        (device["host"], case)
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "FHRP"
    ]
    return output, cases


def _readiness(baseline, interfaces):
    result = compute_migration_readiness(
        interfaces,
        [{"switches": ["r1", "r2"], "endpoints": 0}],
        [{"switch": host, "band": "Good"} for host in ("r1", "r2")],
        [{"switch": host} for host in ("r1", "r2")],
        [],
        [],
        [{"switch": host, "protocol": "FHRP", "severity": "Info"}
         for host in ("r1", "r2")],
        {
            "single_fiber": [],
            "errdis": [],
            "halfdup_up": [],
            "sole_gw": {},
            "orphan": set(),
            "access_by_vlan": {},
            "model": {"hosts": ["r1", "r2"]},
        },
        fhrp_configured_group_baseline=baseline,
    )[0]
    gateway = next(
        check for check in result["checks"] if check["check"] == "Gateway redundancy"
    )
    return result, gateway


def _assert_configured_projection_parity(baseline, plan, cases):
    core_by_host = {row["switch"]: row for row in baseline["rows"]}
    plan_by_host = {
        row["device"]: row
        for row in plan["items"]
        if row["category"] == "FHRP"
        and row.get("projection_custody") == "current_run_source_bound"
    }
    cases_by_host = {
        host: case
        for host, case in cases
        if case.get("projection_custody") == "current_run_source_bound"
    }
    assert set(core_by_host) == set(plan_by_host) == set(cases_by_host) == {"r1", "r2"}
    for host, core in core_by_host.items():
        validation = plan_by_host[host]
        nrfu = cases_by_host[host]
        assert validation["evidence_state"] == nrfu["evidence_state"] == core["status"]
        assert validation["expect"] == nrfu["expected"] == core["acceptance"]
        assert validation["source_key"] == nrfu["source_key"] == core["source_key"]
        assert validation["projection_custody"] == nrfu["projection_custody"] == (
            core["projection_custody"]
        )


def test_dual_active_review_reaches_every_decision_consumer_once(tmp_path):
    baseline, interfaces, devices = _election(tmp_path)
    assert baseline["verdict"] == "INDETERMINATE"
    assert [row["status"] for row in baseline["rows"]] == ["review", "review"]
    assert all(
        {finding["code"] for finding in row["findings"]}
        == {"election_multiple_leaders_observed"}
        for row in baseline["rows"]
    )

    plan = _plan(baseline, interfaces, devices)
    gate = compute_current_baseline_gate(plan)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["summary"]["by_state"] == {
        "degraded": 0, "review": 2, "not_verified": 0,
    }

    output, cases = _nrfu(baseline, interfaces, devices)
    assert output["summary"]["n_fhrp_cases"] == 2
    assert output["summary"]["n_fhrp_blockers"] == 2
    _assert_configured_projection_parity(baseline, plan, cases)

    readiness, gateway = _readiness(baseline, interfaces)
    assert readiness["readiness"] == "CAUTION"
    assert gateway["status"] == "warn"
    assert gateway["note"].count(
        "configured FHRP group subject is INDETERMINATE"
    ) == 1
    assert "VLAN 10 (REVIEW)" not in gateway["note"], (
        "the exact observed-election duplicate must not repeat the configured owner finding"
    )


def test_clean_active_standby_remains_clear_without_healthy_legacy_duplicates(tmp_path):
    baseline, interfaces, devices = _election(tmp_path, second_state="Standby")
    assert baseline["verdict"] == "CLEAR"
    assert [row["status"] for row in baseline["rows"]] == ["assessed", "assessed"]

    plan = _plan(baseline, interfaces, devices)
    assert compute_current_baseline_gate(plan)["verdict"] == "CLEAR"
    output, cases = _nrfu(baseline, interfaces, devices)
    assert output["summary"]["n_fhrp_cases"] == 2
    assert output["summary"]["n_fhrp_blockers"] == 0
    assert all(case["evidence_state"] == "assessed" for _host, case in cases)
    _assert_configured_projection_parity(baseline, plan, cases)

    readiness, gateway = _readiness(baseline, interfaces)
    assert readiness["readiness"] == "READY"
    assert gateway["status"] == "pass"
    assert "VLAN 10 (REVIEW)" not in gateway["note"]


@pytest.mark.parametrize(
    ("second_group", "second_vip", "expected_issue"),
    [
        ("20", "10.0.10.1", "observed groups differ"),
        ("10", "10.0.10.254", "observed VIPs differ"),
    ],
)
def test_uncovered_legacy_identity_mismatch_stays_additive_with_configured_contract(
        tmp_path, second_group, second_vip, expected_issue):
    baseline, interfaces, devices = _election(
        tmp_path,
        second_group=second_group,
        second_vip=second_vip,
    )
    assert baseline["verdict"] == "CLEAR"
    assert all(row["status"] == "assessed" for row in baseline["rows"])

    readiness, gateway = _readiness(baseline, interfaces)
    assert readiness["readiness"] == "CAUTION"
    assert gateway["status"] == "warn"
    assert expected_issue in gateway["note"]

    plan = _plan(baseline, interfaces, devices)
    fhrp_rows = [row for row in plan["items"] if row["category"] == "FHRP"]
    legacy_rows = [
        row for row in fhrp_rows
        if row.get("projection_custody") == "embedded_unverified"
    ]
    assert len(fhrp_rows) == 4
    assert len(legacy_rows) == 2
    assert all(row["evidence_state"] == "review" for row in legacy_rows)
    assert all(row["expect"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
               for row in legacy_rows)
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"

    output, cases = _nrfu(baseline, interfaces, devices)
    legacy_cases = [
        case for _host, case in cases
        if case.get("projection_custody") == "embedded_unverified"
    ]
    assert output["summary"]["n_fhrp_cases"] == 4
    assert output["summary"]["n_fhrp_blockers"] == 2
    assert len(legacy_cases) == 2
    assert all(case["evidence_state"] == "review" for case in legacy_cases)
    assert all(case["expected"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
               for case in legacy_cases)
