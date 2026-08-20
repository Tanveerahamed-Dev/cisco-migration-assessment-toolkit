"""Subtype- and state-truthful FHRP cases in the executable NRFU pack."""
from copy import deepcopy

from cisco_toolkit.nrfu_export import NRFU_BANNER, compute_nrfu_commands


def _snapshot(platform="ios"):
    return {
        "devices": {"dist1": {"platform": platform}},
        "interfaces": {
            "dist1": {
                "Vlan10": {"status": "up", "hsrp_behavior":
                           "HSRP grp 10 Active VIP 10.0.10.1"},
                "Vlan20": {"status": "up", "hsrp_behavior":
                           "VRRP grp 20 Backup VIP 10.0.20.1"},
                "Vlan30": {"status": "up", "hsrp_behavior":
                           "GLBP grp 30 Standby VIP 10.0.30.1"},
                "Vlan40": {"status": "up", "hsrp_behavior":
                           "HSRP grp 40 Init VIP 10.0.40.1"},
                "Vlan50": {"status": "up", "hsrp_behavior":
                           "VRRP grp 50 Init VIP 10.0.50.1"},
                "Vlan60": {"status": "up", "hsrp_behavior":
                           "GLBP grp 60 Disabled VIP 10.0.60.1"},
                # Detail-only HSRP remains an observed baseline instead of disappearing when the
                # compatibility summary projection is absent.
                "Vlan70": {"status": "up"},
            },
        },
        "fhrp_detail": {
            "dist1": [
                {"ifname": "Vlan70", "group": "70", "state": "Learn",
                 "vip": "10.0.70.1"},
                {"ifname": "Vlan40", "group": "40", "state": "Init",
                 "vip": "10.0.40.1"},
                {"ifname": "Vlan10", "group": "10", "state": "Active",
                 "vip": "10.0.10.1"},
            ],
        },
    }


def _fhrp_cases(snapshot):
    out = compute_nrfu_commands(snapshot)
    return [
        case
        for wave in out["waves"]
        for device in wave["devices"] if device["host"] == "dist1"
        for case in device["cases"]
        if case["command"] in {
            "show standby brief", "show hsrp brief", "show vrrp brief", "show glbp brief",
        }
    ]


def test_fhrp_nrfu_uses_observed_subtype_commands_and_roles():
    cases = _fhrp_cases(_snapshot())

    assert [case["command"] for case in cases] == [
        "show standby brief", "show vrrp brief", "show glbp brief",
    ]
    by_command = {case["command"]: case for case in cases}

    hsrp = by_command["show standby brief"]
    assert hsrp["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "HSRP Vlan10 grp 10 observed state Active" in hsrp["expected"]
    assert "HSRP Vlan40 grp 40 observed state Init" in hsrp["expected"]
    assert "HSRP Vlan70 grp 70 observed state Learn" in hsrp["expected"]
    assert hsrp["source_key"].startswith("fhrp_detail.dist1")

    vrrp = by_command["show vrrp brief"]
    assert vrrp["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "VRRP Vlan20 grp 20 observed state Backup" in vrrp["expected"]
    assert "VRRP Vlan50 grp 50 observed state Init" in vrrp["expected"]
    assert "Standby" not in vrrp["expected"] and "Active" not in vrrp["expected"]

    glbp = by_command["show glbp brief"]
    assert glbp["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "GLBP Vlan30 grp 30 observed state Standby" in glbp["expected"]
    assert "GLBP Vlan60 grp 60 observed state Disabled" in glbp["expected"]
    assert "Master" not in glbp["expected"] and "Backup" not in glbp["expected"]


def test_fhrp_nrfu_preserves_degraded_baseline_without_inventing_a_pair():
    cases = _fhrp_cases(_snapshot())
    rendered = "\n".join(case["expected"] for case in cases)

    assert "state Init" in rendered
    assert "state Learn" in rendered
    assert "state Disabled" in rendered
    assert "Active + Standby" not in rendered
    assert "Master + Backup" not in rendered
    assert "all groups healthy" not in rendered.lower()
    assert "neighbor(s)" not in rendered.lower()
    assert "matching this degraded state after cutover is NOT ACCEPTANCE" in rendered
    assert "reproducing a degraded state is not acceptance" in NRFU_BANNER
    assert "PRE-CUTOVER REVIEW" in NRFU_BANNER


def test_fhrp_nrfu_mixed_vlan_output_is_deterministic():
    original = _snapshot()
    reordered = deepcopy(original)
    reordered["interfaces"]["dist1"] = dict(
        reversed(list(reordered["interfaces"]["dist1"].items()))
    )
    reordered["fhrp_detail"]["dist1"].reverse()

    assert _fhrp_cases(original) == _fhrp_cases(reordered)


def test_fhrp_nrfu_does_not_infer_a_case_without_observed_group_state():
    snapshot = {
        "devices": {"dist1": {"platform": "ios"}},
        "interfaces": {"dist1": {"Vlan10": {"status": "up", "hsrp_behavior": ""}}},
    }

    assert _fhrp_cases(snapshot) == []


def test_fhrp_nrfu_healthy_hsrp_detail_remains_a_compatible_acceptance_baseline():
    snapshot = {
        "devices": {"dist1": {"platform": "ios"}},
        "interfaces": {"dist1": {"Vlan10": {
            "hsrp_behavior": "HSRP grp 10 Active VIP 10.0.10.1",
        }}},
        "fhrp_detail": {"dist1": [{
            "ifname": "Vlan10", "group": "10", "state": "Active", "vip": "10.0.10.1",
        }]},
    }

    cases = _fhrp_cases(snapshot)
    assert len(cases) == 1
    assert cases[0]["command"] == "show standby brief"
    assert "Vlan10" in cases[0]["expected"] and "Active" in cases[0]["expected"]
    assert "10.0.10.1" in cases[0]["expected"]
    assert "PRE-CUTOVER DEGRADED" not in cases[0]["expected"]
    assert cases[0]["source_key"] == "fhrp_detail.dist1"


def test_fhrp_nrfu_hsrp_command_remains_platform_aware():
    snapshot = _snapshot(platform="nxos")
    commands = [case["command"] for case in _fhrp_cases(snapshot)]

    assert commands == ["show hsrp brief", "show vrrp brief", "show glbp brief"]
    assert "show standby brief" not in commands


def test_fhrp_nrfu_does_not_call_a_single_backup_only_local_view_degraded():
    snapshot = {
        "devices": {"dist1": {"platform": "ios"}},
        "interfaces": {"dist1": {"Vlan20": {
            "hsrp_behavior": "VRRP grp 20 Backup VIP 10.0.20.1",
        }}},
    }

    cases = _fhrp_cases(snapshot)
    assert len(cases) == 1 and cases[0]["command"] == "show vrrp brief"
    assert "Backup" in cases[0]["expected"]
    assert "PRE-CUTOVER DEGRADED" not in cases[0]["expected"]


def test_fhrp_nrfu_marks_a_multi_member_election_without_a_leader_as_a_blocker():
    snapshot = {
        "devices": {
            "dist1": {"platform": "ios"},
            "dist2": {"platform": "ios"},
        },
        "interfaces": {
            "dist1": {"Vlan20": {
                "hsrp_behavior": "VRRP grp 20 Backup VIP 10.0.20.1",
            }},
            "dist2": {"Vlan20": {
                "hsrp_behavior": "VRRP grp 20 Backup VIP 10.0.20.1",
            }},
        },
    }

    cases = _fhrp_cases(snapshot)
    assert len(cases) == 1
    assert cases[0]["expected"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "VRRP group 20 VIP 10.0.20.1 has no observed Master role" in cases[0]["expected"]
    assert "Verify intended members simultaneously before acceptance" in cases[0]["expected"]
    assert cases[0]["source_key"] == "interfaces.*.*.hsrp_behavior"


def test_fhrp_nrfu_accepts_an_observed_healthy_active_standby_election():
    snapshot = {
        "devices": {
            "dist1": {"platform": "ios"},
            "dist2": {"platform": "ios"},
        },
        "interfaces": {
            "dist1": {"Vlan10": {
                "hsrp_behavior": "HSRP grp 10 Active VIP 10.0.10.1",
            }},
            "dist2": {"Vlan10": {
                "hsrp_behavior": "HSRP grp 10 Standby VIP 10.0.10.1",
            }},
        },
    }

    cases = _fhrp_cases(snapshot)
    assert len(cases) == 1
    assert "Active" in cases[0]["expected"]
    assert "PRE-CUTOVER DEGRADED" not in cases[0]["expected"]


def test_fhrp_nrfu_scopes_local_degradation_without_contaminating_other_protocol():
    snapshot = {
        "devices": {
            "hsrp-a": {"platform": "ios"},
            "vrrp-a": {"platform": "ios"},
        },
        "interfaces": {
            "hsrp-a": {"Vlan10": {
                "svi_ip": "10.0.10.1/24",
                "hsrp_behavior": "HSRP grp 10 Init VIP 10.0.10.253",
            }},
            "vrrp-a": {"Vlan10": {
                "svi_ip": "10.0.10.2/24",
                "hsrp_behavior": "VRRP grp 20 Master VIP 10.0.10.254",
            }},
        },
    }

    out = compute_nrfu_commands(snapshot)
    by_host = {
        device["host"]: next(case for case in device["cases"]
                             if case["command"] in {"show standby brief", "show vrrp brief"})
        for wave in out["waves"] for device in wave["devices"]
    }

    assert by_host["hsrp-a"]["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert by_host["vrrp-a"]["expected"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert "observed degraded role Init" not in by_host["vrrp-a"]["expected"]
