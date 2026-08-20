"""Authoritative FHRP domain rows remain lossless across decision consumers."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from cisco_toolkit.analyze import (
    compute_current_baseline_gate,
    compute_migration_punchlist,
    compute_migration_readiness,
    compute_remediation_plan,
    compute_validation_plan,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.excel import compute_fhrp_consistency
from cisco_toolkit.fhrp_intent import compute_fhrp_configured_group_baseline
from cisco_toolkit.fhrp_redundancy import (
    compute_fhrp_redundancy_domain_baseline,
    embedded_fhrp_redundancy_domain_baseline,
)
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.nrfu_export import compute_nrfu_commands


_HSRP_HEADER = "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"


def _runtime(role: str) -> str:
    active = "local" if role == "Active" else "10.0.10.2"
    standby = "local" if role == "Standby" else "10.0.10.3"
    return _HSRP_HEADER + (
        f"Vl10        10   110 P {role:<8} {active:<15} {standby:<15} 10.0.10.1\n"
    )


def _owner(tmp_path: Path, *, second_role: str = "") -> tuple[dict, dict, dict]:
    specs = {
        "edge-a": {"ip": "10.0.10.2", "role": "Active", "group": True},
        "edge-b": {"ip": "10.0.10.3", "role": second_role, "group": bool(second_role)},
    }
    paths = {}
    for host, spec in specs.items():
        stanza = " standby 10 ip 10.0.10.1\n" if spec["group"] else ""
        captures = {
            "show running-config": (
                f"hostname {host}\ninterface Vlan10\n"
                f" ip address {spec['ip']} 255.255.255.0\n{stanza}end\n"
            ),
            "show standby brief": (
                _runtime(spec["role"]) if spec["group"]
                else "No standby groups configured\n"
            ),
            "show vrrp brief": "No VRRP groups configured\n",
            "show glbp brief": "No GLBP groups configured\n",
        }
        mapping = {}
        for index, (command, body) in enumerate(captures.items(), 1):
            capture = tmp_path / f"{host}-{index}.txt"
            capture.write_text(body, encoding="utf-8")
            mapping[command] = str(capture)
        paths[host] = mapping

    devices = {host: {"platform": "ios"} for host in specs}
    configured = compute_fhrp_configured_group_baseline(
        paths, compute_capture_integrity_from_paths(paths), devices,
    )
    interfaces = {
        host: {"Vlan10": InterfaceData(
            port="Vlan10",
            svi_ip=f"{spec['ip']}/24",
            hsrp_behavior=(
                f"HSRP grp 10 {spec['role']} VIP 10.0.10.1" if spec["group"] else ""
            ),
        )}
        for host, spec in specs.items()
    }
    return configured, interfaces, devices


def _dep_map():
    return {
        "single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
        "orphan": set(), "access_by_vlan": {},
        "model": {"hosts": ["edge-a", "edge-b"]},
    }


def _surfaces(configured, domain, interfaces, devices):
    readiness = compute_migration_readiness(
        interfaces,
        [{"switches": ["edge-a", "edge-b"], "endpoints": 0}],
        [{"switch": host, "band": "Good"} for host in devices],
        [{"switch": host} for host in devices],
        [], [],
        [{"switch": "edge-a", "protocol": "FHRP", "severity": "Info"}],
        _dep_map(),
        fhrp_configured_group_baseline=configured,
        fhrp_redundancy_domain_baseline=domain,
    )[0]
    plan = compute_validation_plan(
        interfaces,
        move_groups=[{"switches": ["edge-a", "edge-b"]}],
        devices=devices,
        fhrp_configured_group_baseline=configured,
        fhrp_redundancy_domain_baseline=domain,
    )
    nrfu = compute_nrfu_commands({
        "devices": devices,
        "interfaces": interfaces,
        "move_groups": [{"switches": ["edge-a", "edge-b"]}],
        "fhrp_configured_group_baseline": configured,
        "fhrp_redundancy_domain_baseline": domain,
    })
    domain_validation = [
        row for row in plan["items"] if row.get("domain_key")
    ]
    domain_cases = [
        case
        for wave in nrfu["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "FHRP Domain"
    ]
    return readiness, plan, domain_validation, nrfu, domain_cases


def _identity(row):
    return row["switch"], row["interface"], row["domain_key"], row["candidate_key"]


def test_one_positive_and_one_complete_zero_is_review_everywhere(tmp_path: Path):
    configured, interfaces, devices = _owner(tmp_path)
    domain = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    assert domain["verdict"] == "INDETERMINATE"
    assert len(domain["rows"]) == 2
    assert {row["status"] for row in domain["rows"]} == {"review"}

    readiness, plan, validation, nrfu, cases = _surfaces(
        configured, domain, interfaces, devices)
    assert readiness["readiness"] == "CAUTION"
    gateway = next(row for row in readiness["checks"] if row["check"] == "Gateway redundancy")
    assert gateway["status"] == "warn"
    assert len(validation) == 2
    assert {row["category"] for row in validation} == {"FHRP"}
    assert {row["evidence_state"] for row in validation} == {"review"}
    gate = compute_current_baseline_gate(plan)
    assert gate["verdict"] == "INDETERMINATE"
    assert gate["summary"]["by_state"]["review"] == 2
    assert len(cases) == 2
    assert nrfu["summary"]["n_fhrp_domain_cases"] == 2
    assert nrfu["summary"]["n_fhrp_domain_blockers"] == 2
    assert nrfu["summary"]["fhrp_domain_by_evidence_state"] == {"review": 2}


def test_active_standby_is_clear_ready_and_exactly_projected(tmp_path: Path):
    configured, interfaces, devices = _owner(tmp_path, second_role="Standby")
    domain = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    assert domain["verdict"] == "CLEAR"

    readiness, plan, validation, nrfu, cases = _surfaces(
        configured, domain, interfaces, devices)
    assert readiness["readiness"] == "READY"
    assert compute_current_baseline_gate(plan)["verdict"] == "CLEAR"
    assert nrfu["summary"]["n_fhrp_domain_blockers"] == 0
    assert nrfu["summary"]["fhrp_domain_by_projection_custody"] == {
        "current_run_projection_bound": 2,
    }

    owner = {_identity(row): row for row in domain["rows"]}
    by_validation = {_identity(row): row for row in validation}
    by_case = {_identity(row): row for row in cases}
    assert set(owner) == set(by_validation) == set(by_case)
    for key, owner_row in owner.items():
        validation_row = by_validation[key]
        case = by_case[key]
        for field, value in owner_row.items():
            assert validation_row[field] == value
            assert case[field] == value
        assert validation_row["expect"] == case["expected"] == owner_row["acceptance"]
        assert validation_row["evidence_state"] == case["evidence_state"] == "assessed"

    # The local configured-group family remains additive rather than being replaced by domain rows.
    assert any(row.get("group_key") for row in plan["items"] if row["category"] == "FHRP")
    assert any(
        case.get("evidence_family") == "FHRP"
        for wave in nrfu["waves"] for device in wave["devices"] for case in device["cases"]
    )


def test_embedded_phase_failed_and_tampered_receipts_emit_only_static_rows(tmp_path: Path):
    configured, interfaces, devices = _owner(tmp_path, second_role="Standby")
    current = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    embedded = embedded_fhrp_redundancy_domain_baseline(current)
    tampered = deepcopy(embedded)
    tampered["rows"][0]["acceptance"] = "REJECTED DOMAIN LEAF"

    for rejected in (embedded, {}, tampered):
        readiness, plan, validation, nrfu, cases = _surfaces(
            configured, rejected, interfaces, devices)
        assert readiness["readiness"] == "CAUTION"
        assert len(validation) == len(cases) == 2
        assert {row["evidence_state"] for row in validation} == {"not_verified"}
        assert {case["evidence_state"] for case in cases} == {"not_verified"}
        assert all(row["expect"].startswith(
            "FHRP REDUNDANCY DOMAIN NOT VERIFIED — BLOCKER:") for row in validation)
        assert all(case["expected"].startswith(
            "FHRP REDUNDANCY DOMAIN NOT VERIFIED — BLOCKER:") for case in cases)
        assert all(row["candidate_key"] == "" for row in validation)
        assert all(case["candidate_key"] == "" for case in cases)
        assert "REJECTED DOMAIN LEAF" not in json.dumps(plan)
        assert "REJECTED DOMAIN LEAF" not in json.dumps(nrfu)
        assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
        assert nrfu["summary"]["n_fhrp_domain_blockers"] == 2


def test_domain_review_is_qualified_and_never_generates_config(tmp_path: Path):
    configured, interfaces, _devices = _owner(tmp_path)
    domain = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    compatibility = compute_fhrp_consistency(interfaces, domain)
    assert compatibility and compatibility[0]["status"] == "review"

    punchlist = compute_migration_punchlist(
        [], {}, {}, [], [], [], {}, [], [], l2={"fhrp": compatibility},
    )
    review = next(row for row in punchlist if row["category"] == "FHRP")
    assert review["severity"] == "Medium"
    assert review["title"].startswith("FHRP domain composition review")
    assert "Intended FHRP membership is unresolved" in review["detail"]

    remediation = compute_remediation_plan(l2={"fhrp": compatibility})
    assert [row for row in remediation["items"] if row["category"] == "FHRP"] == []

    # Domain-wide worst-state propagation cannot identify which local member owns a definite fault.
    # Even an authoritative degraded domain therefore remains validation truth, not configuration authority.
    authoritative_degraded = deepcopy(compatibility)
    for row in authoritative_degraded:
        row["status"] = "degraded"
        row["authoritative"] = True
    remediation = compute_remediation_plan(l2={"fhrp": authoritative_degraded})
    assert [row for row in remediation["items"] if row["category"] == "FHRP"] == []
