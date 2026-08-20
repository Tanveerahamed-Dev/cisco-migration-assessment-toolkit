"""FHRP readiness and validation preserve observed election truth."""
from copy import deepcopy
import json

import pytest

from cisco_toolkit.analyze import (compute_migration_readiness,
                                   compute_validation_plan,
                                   summarize_fhrp_elections)
from cisco_toolkit.model import InterfaceData


def _svi(port, behavior, ip=""):
    return InterfaceData(port=port, hsrp_behavior=behavior, svi_ip=ip)


def _dep(*hosts):
    return {
        "single_fiber": set(),
        "errdis": set(),
        "halfdup_up": set(),
        "sole_gw": {},
        "orphan": set(),
        "access_by_vlan": {},
        "model": {"hosts": set(hosts)},
    }


def _gateway_readiness(ifaces, protocol_health):
    hosts = sorted(ifaces)
    result = compute_migration_readiness(
        ifaces,
        [{"switches": hosts, "endpoints": 0}],
        [{"switch": host, "band": "Good"} for host in hosts],
        [], [], [], protocol_health, _dep(*hosts),
    )[0]
    gateway = next(check for check in result["checks"]
                   if check["check"] == "Gateway redundancy")
    return result, gateway


def test_election_summary_is_subtype_aware_json_ready_and_backup_honest():
    interfaces = {
        "r2": {
            # Snapshot dictionaries and abbreviated interface names are accepted.
            "Vl10": {"hsrp_behavior": "HSRP grp 10 Standby VIP 10.0.10.254"},
        },
        "r1": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Active VIP 10.0.10.254"),
            "Vlan20": _svi("Vlan20", "VRRP grp 20 Backup VIP 10.0.20.254"),
            "Vlan30": _svi("Vlan30", "GLBP grp 30 Active VIP 10.0.30.254"),
        },
    }

    rows = summarize_fhrp_elections(interfaces)

    json.dumps(rows, sort_keys=True)
    assert [row["vlan"] for row in rows] == [10, 20, 30]
    assert all(row["status"] == "healthy" and row["issues"] == [] for row in rows)
    assert all(row["vrf"] == "" and row["subnet"] == "(subnet-unobserved)" for row in rows)
    assert [member["host"] for member in rows[0]["members"]] == ["r1", "r2"]
    # A single observed backup is a bounded local fact, not proof that a leader is absent.
    assert rows[1]["members"][0]["role"] == "Backup"
    assert rows[1]["status"] == "healthy"
    metadata = {item["protocol"]: item for row in rows for item in row["validation"]}
    assert metadata["HSRP"] == {
        "protocol": "HSRP", "command": "show standby brief",
        "leader_roles": ["Active"], "backup_roles": ["Standby", "Listen", "Speak"],
        "degraded_roles": ["Init", "Learn"],
    }
    assert metadata["VRRP"]["command"] == "show vrrp brief"
    assert metadata["VRRP"]["leader_roles"] == ["Master"]
    assert metadata["VRRP"]["backup_roles"] == ["Backup"]
    assert metadata["GLBP"]["command"] == "show glbp brief"
    assert metadata["GLBP"]["leader_roles"] == ["Active"]


@pytest.mark.parametrize(
    "interfaces",
    [
        None,
        7,
        ["not", "a", "mapping"],
        {"r1": 7},
        {"": {"Vlan10": {"hsrp_behavior": "HSRP grp10 Active VIP 10.0.10.1"}}},
        {"r1": {
            "Vlan10": 7,
            "Vlan20": {"hsrp_behavior": {"not": "text"}},
            "Vlan30": {
                "hsrp_behavior": "VRRP grp30 Backup VIP 10.0.30.1",
                "svi_ip": {"not": "an address"},
                "vrf": ["not", "a", "vrf"],
            },
        }},
    ],
)
def test_election_summary_is_total_and_json_ready_on_malformed_leaves(interfaces):
    rows = summarize_fhrp_elections(interfaces)

    assert isinstance(rows, list)
    json.dumps(rows, sort_keys=True)


def test_election_summary_separates_local_degradation_from_cross_member_review():
    interfaces = {
        "r1": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254"),
            "Vlan20": _svi("Vlan20", "HSRP grp 20 Active VIP 10.0.20.254"),
            "Vlan30": _svi("Vlan30", "GLBP grp 30 Init VIP 10.0.30.254"),
            "Vlan40": _svi("Vlan40", "HSRP grp 40 Active VIP 10.0.40.254"),
        },
        "r2": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254"),
            "Vlan20": _svi("Vlan20", "VRRP grp 20 Master VIP 10.0.20.254"),
            "Vlan40": _svi("Vlan40", "HSRP grp 40 Active VIP 10.0.40.254"),
        },
    }

    by_vlan = {row["vlan"]: row for row in summarize_fhrp_elections(interfaces)}

    assert by_vlan[10]["status"] == "review"
    assert any("HSRP group 10" in issue and "no observed Active" in issue
               for issue in by_vlan[10]["issues"])
    assert by_vlan[20]["status"] == "review"
    assert any("mixed FHRP protocols" in issue and "HSRP, VRRP" in issue
               for issue in by_vlan[20]["issues"])
    assert by_vlan[30]["status"] == "degraded"
    assert any("GLBP group 30" in issue and "degraded role Init" in issue
               for issue in by_vlan[30]["issues"])
    assert by_vlan[40]["status"] == "review"
    assert any("HSRP group 40" in issue and "2 observed Active roles" in issue
               for issue in by_vlan[40]["issues"])
    assert all("live simultaneous verification required" in issue
               for issue in by_vlan[40]["issues"])


def test_election_summary_does_not_false_join_reused_vlan_across_l3_domains():
    interfaces = {
        "blue-a": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Active VIP 10.0.10.254", "10.0.10.1/24"),
        },
        "blue-b": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254", "10.0.10.2/24"),
        },
        "red-a": {
            "Vlan10": {
                "hsrp_behavior": "VRRP grp 20 Master VIP 10.20.10.254",
                "svi_ip": "10.20.10.1/24",
                "vrf": "RED",
            },
        },
        "red-b": {
            "Vlan10": {
                "hsrp_behavior": "VRRP grp 20 Backup VIP 10.20.10.254",
                "svi_ip": "10.20.10.2/24",
                "vrf": "red",
            },
        },
    }

    rows = summarize_fhrp_elections(interfaces)

    assert [(row["vlan"], row["vrf"], row["subnet"], row["status"]) for row in rows] == [
        (10, "", "10.0.10.0/24", "healthy"),
        (10, "red", "10.20.10.0/24", "healthy"),
    ]


def test_independent_election_identities_in_one_domain_are_review_not_asserted_degraded():
    interfaces = {
        "a": {"Vlan10": _svi("Vlan10", "HSRP grp 10 Active VIP 10.0.10.253", "10.0.10.1/24")},
        "b": {"Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.253", "10.0.10.2/24")},
        "c": {"Vlan10": _svi("Vlan10", "HSRP grp 20 Active VIP 10.0.10.254", "10.0.10.3/24")},
        "d": {"Vlan10": _svi("Vlan10", "HSRP grp 20 Standby VIP 10.0.10.254", "10.0.10.4/24")},
    }

    row = summarize_fhrp_elections(interfaces)[0]

    assert row["status"] == "review"
    assert all(finding["kind"] == "review" for finding in row["findings"])
    assert "cannot distinguish independent elections from a mismatched pair" in " ".join(row["issues"])
    assert all(member["status"] == "review" for member in row["members"])


@pytest.mark.parametrize(
    ("severity", "expected_status", "expected_readiness"),
    [("Medium", "warn", "CAUTION"), ("High", "fail", "NOT READY")],
)
def test_readiness_gateway_check_consumes_observed_degraded_fhrp_health(
        severity, expected_status, expected_readiness):
    ifaces = {
        "r1": {"Vlan10": _svi("Vlan10", "HSRP grp 10 Init VIP 10.0.10.254")},
    }
    health = [{
        "switch": "r1", "protocol": "FHRP", "severity": severity,
        "summary": "1 group; 1 stuck (Init/Learn)",
        "detail": "Vlan10 HSRP Init",
    }]

    result, gateway = _gateway_readiness(ifaces, health)

    assert gateway["status"] == expected_status
    assert "r1" in gateway["note"] and "Init" in gateway["note"]
    assert result["readiness"] == expected_readiness


def test_readiness_allows_single_observed_backup_but_warns_on_multi_member_no_leader():
    backup_only = {
        "r1": {"Vlan10": _svi("Vlan10", "VRRP grp 10 Backup VIP 10.0.10.254")},
    }
    healthy, healthy_gateway = _gateway_readiness(
        backup_only,
        [{"switch": "r1", "protocol": "FHRP", "severity": "Info",
          "summary": "1 group; 0 active/master", "detail": ""}],
    )
    assert healthy_gateway["status"] == "pass"
    assert healthy["readiness"] == "READY"

    no_leader = {
        "r1": {"Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254")},
        "r2": {"Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254")},
    }
    caution, caution_gateway = _gateway_readiness(no_leader, [])
    assert caution_gateway["status"] == "warn"
    assert "no observed Active" in caution_gateway["note"]
    assert caution["readiness"] == "CAUTION"


def _validation_fabric():
    return {
        "r1": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Init VIP 10.0.10.254", "10.0.10.1"),
            "Vlan20": _svi("Vlan20", "VRRP grp 20 Master VIP 10.0.20.254", "10.0.20.1"),
            "Vlan30": _svi("Vlan30", "GLBP grp 30 Active VIP 10.0.30.254", "10.0.30.1"),
            "Vlan40": _svi("Vlan40", "HSRP grp 40 Active VIP 10.0.40.254", "10.0.40.1"),
            "Vlan50": _svi("Vlan50", "VRRP grp 50 Backup VIP 10.0.50.254", "10.0.50.1"),
        },
        "r2": {
            "Vlan10": _svi("Vlan10", "HSRP grp 10 Standby VIP 10.0.10.254", "10.0.10.2"),
            "Vlan20": _svi("Vlan20", "VRRP grp 20 Backup VIP 10.0.20.254", "10.0.20.2"),
            "Vlan30": _svi("Vlan30", "GLBP grp 30 Standby VIP 10.0.30.254", "10.0.30.2"),
            "Vlan40": _svi("Vlan40", "VRRP grp 40 Master VIP 10.0.40.254", "10.0.40.2"),
        },
    }


def _fhrp_plan_projection(ifaces):
    hosts = sorted(ifaces)
    plan = compute_validation_plan(
        ifaces,
        move_groups=[{"switches": hosts}],
        devices={host: {"platform": "ios"} for host in hosts},
        protocol_health=[],
    )
    return plan, [
        (item["device"], item["check"], item["command"], item["expect"])
        for item in plan["items"] if item["category"] == "FHRP"
    ]


def test_validation_plan_preserves_subtype_roles_degradation_and_deterministic_mixed_scope():
    fabric = _validation_fabric()
    plan, projection = _fhrp_plan_projection(fabric)
    fhrp = [item for item in plan["items"] if item["category"] == "FHRP"]

    assert len(fhrp) == 9, "one validation row per observed local member; no expected peer was invented"
    init = next(item for item in fhrp if item["device"] == "r1" and "VLAN 10" in item["check"])
    assert init["command"] == "show standby brief"
    assert init["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "Init" in init["expect"] and "NOT ACCEPTANCE" in init["expect"]
    assert "exactly one Active + one Standby" not in init["expect"]
    assert "Do NOT substitute an ideal healthy role/count" in init["expect"]

    vrrp = next(item for item in fhrp if item["device"] == "r1" and "VLAN 20" in item["check"])
    assert vrrp["command"] == "show vrrp brief"
    assert "Master" in vrrp["expect"] and "Backup" in vrrp["expect"]
    glbp = next(item for item in fhrp if item["device"] == "r1" and "VLAN 30" in item["check"])
    assert glbp["command"] == "show glbp brief"
    assert "Active" in glbp["expect"] and "Standby" in glbp["expect"]

    single_backup = next(item for item in fhrp if item["device"] == "r1" and "VLAN 50" in item["check"])
    assert "degraded" not in single_backup["check"].lower()
    assert "is Backup" in single_backup["expect"]
    assert "no expected peer count was inferred" in single_backup["expect"]

    mixed = [item for item in fhrp if "VLAN 40" in item["check"]]
    assert {item["command"] for item in mixed} == {"show standby brief", "show vrrp brief"}
    assert all("mixed FHRP protocols" in item["expect"] for item in mixed)

    # Insertion order from a JSON producer cannot change the emitted validation sequence or copy.
    reversed_fabric = {
        host: dict(reversed(list(interfaces.items())))
        for host, interfaces in reversed(list(deepcopy(fabric).items()))
    }
    _reversed_plan, reversed_projection = _fhrp_plan_projection(reversed_fabric)
    assert reversed_projection == projection
    assert "'Observed baseline / acceptance'" in plan["banner"]
    assert "PRE-CUTOVER DEGRADED — BLOCKER:" in plan["banner"]
    assert "NOT ACCEPTANCE" in plan["banner"]


@pytest.mark.parametrize("platform", ["nxos", "NX-OS", "Nexus 9300"])
def test_validation_hsrp_command_uses_canonical_nxos_platform_detection(platform):
    interfaces = {
        "n9k": {
            "Vlan10": _svi(
                "Vlan10", "HSRP grp 10 Active VIP 10.0.10.254", "10.0.10.1"
            ),
        },
    }

    plan = compute_validation_plan(
        interfaces,
        move_groups=[{"switches": ["n9k"]}],
        devices={"n9k": {"platform": platform}},
    )
    row = next(item for item in plan["items"] if item["category"] == "FHRP")

    assert row["command"] == "show hsrp brief"


def test_validation_scopes_local_degradation_without_contaminating_other_protocol():
    interfaces = {
        "hsrp-a": {
            "Vlan10": _svi(
                "Vlan10", "HSRP grp 10 Init VIP 10.0.10.253", "10.0.10.1/24"
            ),
        },
        "vrrp-a": {
            "Vlan10": _svi(
                "Vlan10", "VRRP grp 20 Master VIP 10.0.10.254", "10.0.10.2/24"
            ),
        },
    }

    election = summarize_fhrp_elections(interfaces)[0]
    by_protocol = {member["protocol"]: member for member in election["members"]}
    assert election["status"] == "degraded"
    assert by_protocol["HSRP"]["status"] == "degraded"
    assert by_protocol["VRRP"]["status"] == "review"

    plan = compute_validation_plan(
        interfaces,
        move_groups=[{"switches": sorted(interfaces)}],
        devices={host: {"platform": "ios"} for host in interfaces},
    )
    rows = {item["device"]: item for item in plan["items"] if item["category"] == "FHRP"}
    assert rows["hsrp-a"]["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert rows["vrrp-a"]["expect"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "PRE-CUTOVER DEGRADED" not in rows["vrrp-a"]["expect"]
