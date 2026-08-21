"""Source-bound FHRP redundancy-domain composition counterexamples."""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

from cisco_toolkit import fhrp_redundancy as redundancy
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.fhrp_intent import (
    compute_fhrp_configured_group_baseline,
    embedded_fhrp_configured_group_baseline,
    validate_fhrp_configured_group_baseline,
)
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    bound_snapshot_source,
)
from cisco_toolkit.protocol_deltas import compute_fhrp_redundancy_domain_delta
from cisco_toolkit.fhrp_redundancy import (
    FHRP_REDUNDANCY_DOMAIN_SCHEMA,
    _baseline_digest,
    compute_fhrp_redundancy_domain_baseline,
    embedded_fhrp_redundancy_domain_baseline,
    scope_fhrp_redundancy_domains,
    validate_fhrp_redundancy_domain_baseline,
)
from cisco_toolkit.model import InterfaceData


_HSRP_HEADER = "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
_NO_VRRP = "No VRRP groups configured\n"
_NO_GLBP = "No GLBP groups configured\n"


def _config(ip: str, *, group: bool = True) -> str:
    stanza = (
        " standby 10 ip 10.0.10.1\n standby 10 priority 110\n standby 10 preempt\n"
        if group else ""
    )
    return f"hostname edge\ninterface Vlan10\n ip address {ip} 255.255.255.0\n{stanza}end\n"


def _runtime(role: str) -> str:
    active = "local" if role == "Active" else "10.0.10.2"
    standby = "local" if role == "Standby" else "10.0.10.3"
    return _HSRP_HEADER + (
        f"Vl10        10   110 P {role:<8} {active:<15} {standby:<15} 10.0.10.1\n"
    )


def _owner(tmp_path: Path, hosts: dict[str, dict]) -> tuple[dict, dict]:
    paths: dict[str, dict[str, str]] = {}
    for host, spec in hosts.items():
        mapping: dict[str, str] = {}
        captures = {
            "show running-config": _config(spec["ip"], group=spec.get("group", True)),
            "show standby brief": (
                _runtime(spec["role"]) if spec.get("group", True)
                else "No standby groups configured\n"
            ),
        }
        if not spec.get("omit_vrrp"):
            captures["show vrrp brief"] = _NO_VRRP
        if not spec.get("omit_glbp"):
            captures["show glbp brief"] = _NO_GLBP
        for index, (command, body) in enumerate(captures.items(), 1):
            path = tmp_path / f"{host}-{index}.txt"
            path.write_text(body, encoding="utf-8")
            mapping[command] = str(path)
        paths[host] = mapping
    integrity = compute_capture_integrity_from_paths(paths)
    configured = compute_fhrp_configured_group_baseline(
        paths, integrity, {host: {"platform": "ios"} for host in hosts},
    )
    interfaces = {
        host: {
            "Vlan10": InterfaceData(
                port="Vlan10", svi_ip=f"{spec['ip']}/24",
                hsrp_behavior=(
                    f"HSRP grp 10 {spec['role']} VIP 10.0.10.1"
                    if spec.get("group", True) else ""
                ),
            )
        }
        for host, spec in hosts.items()
    }
    return configured, interfaces


def _captured_owner(tmp_path: Path, captures: dict[str, dict[str, str]]) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths: dict[str, dict[str, str]] = {}
    for host, command_bodies in captures.items():
        paths[host] = {}
        for index, (command, body) in enumerate(command_bodies.items(), 1):
            path = tmp_path / f"{host}-custom-{index}.txt"
            path.write_text(body, encoding="utf-8")
            paths[host][command] = str(path)
    integrity = compute_capture_integrity_from_paths(paths)
    return compute_fhrp_configured_group_baseline(
        paths, integrity, {host: {"platform": "ios"} for host in paths},
    )


def test_matching_active_standby_domain_is_bounded_clear(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["schema"] == FHRP_REDUNDANCY_DOMAIN_SCHEMA
    assert baseline["verdict"] == "CLEAR"
    assert baseline["assessed"] is True
    assert baseline["summary"]["by_status"] == {
        "degraded": 0, "review": 0, "not_verified": 0, "assessed": 1,
    }
    assert {row["status"] for row in baseline["rows"]} == {"assessed"}
    assert {row["role"] for row in baseline["rows"]} == {"ACTIVE", "STANDBY"}
    view = validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)
    assert view["valid"] is True and len(view["domains"]) == 1


def test_hsrp_listen_and_speak_are_not_accepted_backup_roles(tmp_path: Path):
    for role in ("Listen", "Speak"):
        configured, interfaces = _owner(tmp_path, {
            "edge-a": {"ip": "10.0.10.2", "role": "Active"},
            "edge-b": {"ip": "10.0.10.3", "role": role},
        })

        baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

        assert baseline["verdict"] == "INDETERMINATE"
        assert baseline["domains"][0]["status"] == "review"
        assert "no_backup_observed" in {
            finding["code"] for finding in baseline["domains"][0]["findings"]
        }
        assert {row["status"] for row in baseline["rows"]} == {"review"}


def test_complete_same_domain_nonparticipant_is_review_not_failure(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-independent": {"ip": "10.0.10.3", "role": "", "group": False},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["summary"]["n_review"] == 1
    assert len(baseline["rows"]) == 2
    assert {row["status"] for row in baseline["rows"]} == {"review"}
    zero = next(row for row in baseline["rows"] if row["participation"] == "nonparticipant")
    assert "intended redundancy membership is not established" in zero["why"]
    assert "PRE-CUTOVER REVIEW — BLOCKER:" in zero["acceptance"]
    assert "unprotected" not in json.dumps(baseline).lower()
    assert "not proof that the svi is misconfigured" in json.dumps(baseline).lower()


def test_missing_subtype_receipt_makes_nonparticipant_not_verified(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {
            "ip": "10.0.10.3", "role": "", "group": False, "omit_glbp": True,
        },
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["summary"]["n_not_verified"] == 1
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    assert all("FHRP REDUNDANCY DOMAIN NOT VERIFIED" in row["acceptance"]
               for row in baseline["rows"])


def test_missing_subtype_receipt_on_positive_members_withholds_assessment(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {
            "ip": "10.0.10.2", "role": "Active",
            "omit_vrrp": True, "omit_glbp": True,
        },
        "edge-b": {
            "ip": "10.0.10.3", "role": "Standby",
            "omit_vrrp": True, "omit_glbp": True,
        },
    })

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["domains"][0]["status"] == "not_verified"
    assert {member["local_status"] for member in baseline["domains"][0]["members"]} == {
        "not_verified"
    }
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    assert validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_dual_active_is_review_and_matching_it_is_not_acceptance(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Active"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "INDETERMINATE"
    assert {row["status"] for row in baseline["rows"]} == {"review"}
    assert any(finding["code"] == "multiple_leaders_observed"
               for finding in baseline["domains"][0]["findings"])
    assert all("NOT ACCEPTANCE" in row["acceptance"] for row in baseline["rows"])


def test_resealed_assessed_role_forgery_is_rejected_semantically(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    forged = copy.deepcopy(baseline)
    forged["rows"][0]["role"] = "DOWN"
    forged["domains"][0]["members"][0]["role"] = "DOWN"
    forged["domains"][0]["leader_count"] = 0
    forged["summary"]["baseline_sha256"] = ""
    forged["summary"]["baseline_sha256"] = _baseline_digest(forged)

    view = validate_fhrp_redundancy_domain_baseline(forged)

    assert view["valid"] is False
    assert view["reason"] == "baseline_domain_semantics_mismatch"


def test_different_observed_subnets_do_not_cross_join(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    interfaces["edge-b"]["Vlan10"].svi_ip = "10.0.20.3/24"
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["domains"] == [] and baseline["rows"] == []


def test_same_vlan_different_normalized_vrfs_do_not_cross_join(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    interfaces["edge-b"]["Vlan10"].vrf = "TENANT-RED"

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["domains"] == [] and baseline["rows"] == []


def test_casefold_host_alias_collision_withholds_but_stays_self_valid(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    interfaces["EDGE-A"] = copy.deepcopy(interfaces["edge-a"])

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    view = validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)

    assert baseline["verdict"] == "INDETERMINATE"
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    assert len({row["switch"].casefold() for row in baseline["rows"]}) == 2
    assert view["valid"] is True


def test_ios_dotted_mask_and_nxos_cidr_share_one_canonical_domain(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-ios": {"ip": "10.0.10.2", "role": "Active"},
        "edge-nx": {"ip": "10.0.10.3", "role": "Standby"},
    })
    interfaces["edge-ios"]["Vlan10"].svi_ip = "10.0.10.2 255.255.255.0"
    interfaces["edge-nx"]["Vlan10"].svi_ip = "10.0.10.3/24"

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "CLEAR"
    assert {row["subnet"] for row in baseline["rows"]} == {"10.0.10.0/24"}


def test_two_group_load_sharing_is_assessed_per_exact_candidate(tmp_path: Path):
    captures = {}
    interfaces = {}
    for host, address, states in (
        ("edge-a", "10.0.10.2", ("Active", "Standby")),
        ("edge-b", "10.0.10.3", ("Standby", "Active")),
    ):
        captures[host] = {
            "show running-config": (
                f"interface Vlan10\n ip address {address} 255.255.255.0\n"
                " standby 10 ip 10.0.10.1\n"
                " standby 20 ip 10.0.10.254\nend\n"
            ),
            "show standby brief": _HSRP_HEADER + (
                f"Vl10 10 110 P {states[0]} local 10.0.10.3 10.0.10.1\n"
                f"Vl10 20 110 P {states[1]} 10.0.10.2 local 10.0.10.254\n"
            ),
            "show vrrp brief": _NO_VRRP,
            "show glbp brief": _NO_GLBP,
        }
        interfaces[host] = {
            "Vlan10": InterfaceData(
                port="Vlan10", svi_ip=f"{address}/24", hsrp_behavior="HSRP",
            )
        }
    configured = _captured_owner(tmp_path, captures)

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "CLEAR"
    assert len(baseline["rows"]) == 4
    assert baseline["domains"][0]["leader_count"] == 2
    assert baseline["domains"][0]["backup_count"] == 2
    assert {row["candidate_key"] for row in baseline["rows"]} == {
        "HSRP:10:10.0.10.1", "HSRP:20:10.0.10.254",
    }


def test_disjoint_and_subset_nonempty_candidate_sets_require_review(tmp_path: Path):
    cases = {
        "subset": ({10, 20}, {10}),
        "disjoint": ({10}, {20}),
    }
    for label, (a_groups, b_groups) in cases.items():
        captures = {}
        interfaces = {}
        for host, address, groups in (
            ("edge-a", "10.0.10.2", a_groups),
            ("edge-b", "10.0.10.3", b_groups),
        ):
            config_groups = "".join(
                f" standby {group} ip "
                f"{'10.0.10.1' if group == 10 else '10.0.10.254'}\n"
                for group in sorted(groups)
            )
            runtime_groups = "".join(
                f"Vl10 {group} 110 P "
                f"{'Active' if host == 'edge-a' else 'Standby'} "
                f"local 10.0.10.3 "
                f"{'10.0.10.1' if group == 10 else '10.0.10.254'}\n"
                for group in sorted(groups)
            )
            captures[host] = {
                "show running-config": (
                    f"interface Vlan10\n ip address {address} 255.255.255.0\n"
                    f"{config_groups}end\n"
                ),
                "show standby brief": _HSRP_HEADER + runtime_groups,
                "show vrrp brief": _NO_VRRP,
                "show glbp brief": _NO_GLBP,
            }
            interfaces[host] = {"Vlan10": InterfaceData(
                port="Vlan10", svi_ip=f"{address}/24", hsrp_behavior="HSRP")}
        configured = _captured_owner(tmp_path / label, captures)

        baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

        assert baseline["verdict"] == "INDETERMINATE"
        assert baseline["domains"][0]["status"] == "review"
        assert "candidate_set_mismatch" in {
            finding["code"] for finding in baseline["domains"][0]["findings"]
        }


def test_nonparticipant_requires_exact_zero_subtype_counts(tmp_path: Path):
    captures = {
        "edge-a": {
            "show running-config": (
                "interface Vlan10\n ip address 10.0.10.2 255.255.255.0\n"
                " standby 10 ip 10.0.10.1\nend\n"
            ),
            "show standby brief": _runtime("Active"),
            "show vrrp brief": _NO_VRRP,
            "show glbp brief": _NO_GLBP,
        },
        "edge-b": {
            "show running-config": (
                "interface Vlan10\n ip address 10.0.10.3 255.255.255.0\n"
                "interface Vlan20\n ip address 10.0.20.2 255.255.255.0\n"
                " standby 20 ip 10.0.20.1\nend\n"
            ),
            "show standby brief": _HSRP_HEADER + (
                "Vl20 20 110 P Active local 10.0.20.3 10.0.20.1\n"
            ),
            "show vrrp brief": _NO_VRRP,
            "show glbp brief": _NO_GLBP,
        },
    }
    configured = _captured_owner(tmp_path, captures)
    interfaces = {
        "edge-a": {"Vlan10": InterfaceData(
            port="Vlan10", svi_ip="10.0.10.2/24", hsrp_behavior="HSRP")},
        "edge-b": {
            "Vlan10": InterfaceData(port="Vlan10", svi_ip="10.0.10.3/24"),
            "Vlan20": InterfaceData(
                port="Vlan20", svi_ip="10.0.20.2/24", hsrp_behavior="HSRP"),
        },
    }

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    zero = next(row for row in baseline["rows"] if row["switch"] == "edge-b")

    assert zero["participation"] == "not_verified"
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    assert validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_definite_local_degraded_state_gates_every_domain_member(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Init"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })

    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    assert baseline["verdict"] == "BLOCKED"
    assert baseline["domains"][0]["status"] == "degraded"
    assert {row["status"] for row in baseline["rows"]} == {"degraded"}
    assert validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)["valid"] is True
    assert validate_fhrp_redundancy_domain_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_invalid_source_echoes_no_hostile_leaves_but_scoper_keeps_safe_svis():
    interfaces = {
        "edge-a": {"Vlan10": InterfaceData(
            port="Vlan10", svi_ip="10.0.10.2/24", hsrp_behavior="HSRP Active")},
        "edge-b": {"Vlan10": InterfaceData(
            port="Vlan10", svi_ip="10.0.10.3/24")},
    }
    hostile = {"rows": [{"switch": "HOSTILE", "acceptance": "HOSTILE PASS"}]}
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, hostile)

    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["rows"] == [] and baseline["domains"] == []
    assert "HOSTILE" not in json.dumps(baseline)
    assert {row["switch"] for row in scope_fhrp_redundancy_domains(
        interfaces, hostile)} == {"edge-a", "edge-b"}


def test_json_and_embedded_receipts_cannot_self_authorize(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    serialized = json.loads(json.dumps(baseline))
    embedded = embedded_fhrp_redundancy_domain_baseline(baseline)

    assert validate_fhrp_redundancy_domain_baseline(serialized)["valid"] is True
    assert validate_fhrp_redundancy_domain_baseline(
        serialized, require_current_run=True)["reason"] == (
            "baseline_not_current_run_source_bound"
        )
    assert embedded["projection_custody"] == "embedded_unverified"
    assert embedded["source_receipt"]["source_bound"] is False
    assert validate_fhrp_redundancy_domain_baseline(embedded)["valid"] is True


def test_embedded_domain_rebinds_only_to_its_exact_current_configured_owner(
        tmp_path: Path):
    (tmp_path / "matching").mkdir()
    configured, interfaces = _owner(tmp_path / "matching", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    domain = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    embedded_configured = embedded_fhrp_configured_group_baseline(configured)
    embedded_domain = embedded_fhrp_redundancy_domain_baseline(
        domain, configured_group_baseline=configured)

    assert validate_fhrp_configured_group_baseline(
        embedded_configured)["valid"] is True
    assert validate_fhrp_redundancy_domain_baseline(
        embedded_domain)["valid"] is True
    assert embedded_domain["source_receipt"]["configured_baseline_sha256"] == (
        embedded_configured["summary"]["baseline_sha256"]
    )

    snapshot = {
        "script_version": "fhrp-persisted-reconciliation-test/1",
        "devices": {"edge-a": {"platform": "ios"}, "edge-b": {"platform": "ios"}},
        "interfaces": interfaces,
        "fhrp_configured_group_baseline": embedded_configured,
        "fhrp_redundancy_domain_baseline": embedded_domain,
    }
    raw = json.dumps(
        snapshot,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")
    bound = bind_snapshot_json_bytes(raw)
    binding = bound_snapshot_source(bound)
    delta = compute_fhrp_redundancy_domain_delta(
        bound,
        bound,
        comparison_source_binding={"before": binding, "after": binding},
    )
    assert delta["summary"]["by_transition"]["unchanged_healthy"] == 1
    assert delta["summary"]["by_transition"]["not_comparable"] == 0

    (tmp_path / "mismatched").mkdir()
    mismatched, _other_interfaces = _owner(tmp_path / "mismatched", {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Active"},
    })
    rejected = embedded_fhrp_redundancy_domain_baseline(
        domain, configured_group_baseline=mismatched)
    rejected_view = validate_fhrp_redundancy_domain_baseline(rejected)
    assert rejected_view["valid"] is True
    assert rejected["source_receipt"]["valid"] is False
    assert rejected["verdict"] == "INDETERMINATE"


def test_domain_receipt_from_different_svi_projection_fails_closed(
        tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "", "group": False},
    })
    actual = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    assert actual["domains"][0]["status"] == "review"

    # This receipt is structurally valid and consumes the exact same configured
    # owner, but its SVI source was empty.  It must not erase the review domain
    # when grafted beside the real, co-published interface projection.
    grafted = compute_fhrp_redundancy_domain_baseline({}, configured)
    snapshot = {
        "script_version": "fhrp-svi-graft-test/1",
        "devices": {"edge-a": {"platform": "ios"}, "edge-b": {"platform": "ios"}},
        "interfaces": interfaces,
        "fhrp_configured_group_baseline": embedded_fhrp_configured_group_baseline(
            configured),
        "fhrp_redundancy_domain_baseline": embedded_fhrp_redundancy_domain_baseline(
            grafted, configured_group_baseline=configured),
    }
    raw = json.dumps(
        snapshot,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: dataclasses.asdict(item)
        if dataclasses.is_dataclass(item) else str(item),
    ).encode("utf-8")
    bound = bind_snapshot_json_bytes(raw)
    binding = bound_snapshot_source(bound)

    delta = compute_fhrp_redundancy_domain_delta(
        bound,
        bound,
        comparison_source_binding={"before": binding, "after": binding},
    )

    assert delta["applicability"] == "applicable"
    assert delta["comparable"] is False
    assert delta["summary"]["by_transition"]["not_comparable"] == 1
    assert delta["summary"]["by_decision_effect"]["not_verified"] == 1
    assert delta["changes"][0]["transition"] == "not_comparable"


def test_consistently_resealed_nested_local_status_loses_current_authority(
        tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
    forged = copy.deepcopy(baseline)
    domain = forged["domains"][0]
    domain["members"][0]["local_status"] = "review"
    semantics = redundancy._domain_semantics(domain["members"], domain["subnet"])
    for field in (
            "status", "member_count", "participant_count", "leader_count",
            "backup_count", "protocol", "group", "virtual_ip"):
        domain[field] = semantics[field]
    domain["assessed"] = False
    domain["findings"] = copy.deepcopy(semantics["findings"])
    acceptance = redundancy._acceptance(
        semantics["status"], vlan=domain["vlan"], vrf=domain["vrf"],
        subnet=domain["subnet"], member_count=semantics["member_count"],
        candidate_count=semantics["candidate_count"],
    )
    domain["acceptance"] = acceptance
    for member in domain["members"]:
        member["findings"] = copy.deepcopy(semantics["findings"])
    for row in forged["rows"]:
        row["status"] = semantics["status"]
        row["findings"] = copy.deepcopy(semantics["findings"])
        row["why"] = redundancy._why(semantics["findings"])
        row["acceptance"] = acceptance
    forged["findings"] = [
        {**finding, "domain_key": domain["domain_key"]}
        for finding in semantics["findings"]
    ]
    forged["summary"] = redundancy._summary(forged["domains"], forged["rows"])
    forged["verdict"], forged["assessed"] = redundancy._verdict(
        forged["domains"], True)
    forged["summary"]["baseline_sha256"] = _baseline_digest(forged)

    audit_view = validate_fhrp_redundancy_domain_baseline(forged)
    current_view = validate_fhrp_redundancy_domain_baseline(
        forged, require_current_run=True)

    assert audit_view["valid"] is True and audit_view["source_bound"] is False
    assert current_view["valid"] is False
    assert current_view["reason"] == "baseline_not_current_run_source_bound"


def test_duplicate_tamper_and_deep_hostile_values_fail_closed(tmp_path: Path):
    configured, interfaces = _owner(tmp_path, {
        "edge-a": {"ip": "10.0.10.2", "role": "Active"},
        "edge-b": {"ip": "10.0.10.3", "role": "Standby"},
    })
    baseline = compute_fhrp_redundancy_domain_baseline(interfaces, configured)

    duplicate = copy.deepcopy(baseline)
    duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
    duplicate["domains"][0]["members"].append(
        copy.deepcopy(duplicate["domains"][0]["members"][0]))
    duplicate["summary"]["baseline_sha256"] = ""
    duplicate["summary"]["baseline_sha256"] = _baseline_digest(duplicate)
    assert validate_fhrp_redundancy_domain_baseline(duplicate)["valid"] is False

    receipt_tamper = copy.deepcopy(baseline)
    receipt_tamper["source_receipt"]["svi_projection_sha256"] = "0" * 64
    assert validate_fhrp_redundancy_domain_baseline(receipt_tamper)["reason"] == (
        "baseline_digest_mismatch"
    )

    deep: dict = {}
    cursor = deep
    for _ in range(5000):
        child: dict = {}
        cursor["nested"] = child
        cursor = child
    assert validate_fhrp_redundancy_domain_baseline(deep)["valid"] is False

    oversized = copy.deepcopy(embedded_fhrp_redundancy_domain_baseline(None))
    oversized["rows"] = [{}] * 20_001
    assert validate_fhrp_redundancy_domain_baseline(oversized)["valid"] is False
