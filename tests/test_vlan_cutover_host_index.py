"""Shared VLAN membership keeps the cutover producer's existing output and wave semantics."""
from copy import deepcopy
from dataclasses import asdict
import re

import pytest

from cisco_toolkit import analyze
from cisco_toolkit.model import InterfaceData
from cisco_toolkit.stp_topology import _election_priority


def _fabric():
    return {
        "access": {
            "Gi1/0/1": InterfaceData(switchport_mode="Access", vlan="010", vlan_name="USERS"),
            "Gi1/0/2": InterfaceData(switchport_mode="Trunk", vlan="99"),
            "Gi1/0/3": InterfaceData(switchport_mode="access", vlan="98"),
        },
        "gateway": {
            "Vlan0010": InterfaceData(vlan_name="USERS", svi_ip="192.0.2.1/24"),
            "vLaN00020": InterfaceData(),
            "Vlan30.5": InterfaceData(),
        },
        "outside": {"Gi1/0/4": InterfaceData(switchport_mode="Access", vlan="10")},
    }


def _roots():
    return {
        "root": {
            " 30 ": {"is_mst": False, "is_root": True, "root_priority": 32798,
                      "root_address": "aaaa.0001.0001"},
            "40": {"is_mst": False, "is_root": False},
            "0": {"is_mst": False},
            "77": {"is_mst": True},
            "MST1": {"is_mst": True},
            "-1": {"is_mst": False},
            "bad": {},
            True: {},
        },
    }


def _legacy_host_index(all_interfaces, stp_roots=None):
    """Independent transcription of the removed producer membership lines, not the new helper."""
    result = {}
    for host in sorted(all_interfaces or {}):
        for port, record in (all_interfaces[host] or {}).items():
            value = (getattr(record, "vlan", "") or "").strip()
            if (getattr(record, "switchport_mode", "") or "") == "Access" and value.isdigit():
                result.setdefault(int(value), set()).add(host)
            match = re.match(r"^Vlan0*(\d+)$", str(port), re.IGNORECASE)
            if match:
                result.setdefault(int(match.group(1)), set()).add(host)
    for host in sorted(stp_roots or {}):
        per_host = stp_roots[host]
        for vlan, record in (per_host.items() if isinstance(per_host, dict) else []):
            number = _election_priority(vlan)
            if number is None or number < 0 or (isinstance(record, dict) and record.get("is_mst")):
                continue
            result.setdefault(number, set()).add(host)
    return result


def test_interface_and_serialized_membership_are_the_same_exact_capture():
    fabric, roots = _fabric(), _roots()
    serialized = {host: {port: asdict(record) for port, record in ports.items()}
                  for host, ports in fabric.items()}
    expected = {0: {"root"}, 10: {"access", "gateway", "outside"},
                20: {"gateway"}, 30: {"root"}, 40: {"root"}}
    assert analyze.vlan_cutover_host_index(fabric, roots) == expected
    assert analyze.vlan_cutover_host_index(serialized, roots) == expected
    assert _legacy_host_index(fabric, roots) == expected


@pytest.mark.parametrize("all_interfaces,roots,expected", [
    (None, None, {}), ({}, {}, {}),
    ({"host": {}}, None, {}),
    ({}, {"host": {"7": None}}, {7: {"host"}}),
    ({}, {"host": {7: {"is_mst": False}}}, {7: {"host"}}),
    ({}, {"host": {"7": {"is_mst": True}}}, {}),
    ({}, {"host": {"7.0": {}}}, {}),
    ({}, {"host": {"7": {}, "007": {}}}, {7: {"host"}}),
])
def test_host_universe_retains_current_root_priority_admission(all_interfaces, roots, expected):
    assert analyze.vlan_cutover_host_index(all_interfaces, roots) == expected
    assert _legacy_host_index(all_interfaces, roots) == expected


def test_membership_source_and_result_are_not_mutated_or_shared():
    fabric, roots = _fabric(), _roots()
    frozen = deepcopy((fabric, roots))
    result = analyze.vlan_cutover_host_index(fabric, roots)
    result[10].add("injected")
    result[1] = {"extra"}
    assert (fabric, roots) == frozen
    fresh = analyze.vlan_cutover_host_index(fabric, roots)
    assert "injected" not in fresh[10]
    assert 1 not in fresh


@pytest.mark.parametrize("groups", [
    [{"group": "Later, measured", "switches": ["gateway"]},
     {"group": "Pilot", "switches": ["access"]},
     {"group": "Root", "switches": ["root"]}],
    [{"group": "Pilot", "switches": ["access"]},
     {"group": "Later, measured", "switches": ["gateway"]},
     {"group": "Root", "switches": ["root"]}],
    [{"switches": ["gateway"]}, {"switches": ["access"]}, {"switches": ["root"]}],
    [],
])
def test_actual_producer_all_fields_match_the_legacy_membership_index(monkeypatch, groups):
    fabric, roots = _fabric(), _roots()
    labels = analyze.move_group_labels(groups)
    sequencing = [{"group": label, "make_before_break": list(group["switches"]),
                   "hard_cutover": [], "homing_unknown": []}
                  for label, group in zip(labels, groups)]
    readiness = [{"group": label, "readiness": "CAUTION"} for label in labels]
    endpoints = [{"host": "access", "port": "Gi1/0/1", "vlan": "10", "mac_count": 2,
                  "endpoint_class": "Server"}]
    apps = {"domains": [{"domain": "Infrastructure", "tier": "Support", "vlans": ["10"]}]}
    multicast = {"querier": {"multicast_vlans": ["10"], "gap_vlans": ["10"]}}
    args = (fabric, roots, None, endpoints, apps, groups, sequencing, readiness, multicast)
    frozen = deepcopy(args)
    actual = analyze.compute_vlan_cutover_matrix(*args)
    monkeypatch.setattr(analyze, "vlan_cutover_host_index", _legacy_host_index)
    legacy = analyze.compute_vlan_cutover_matrix(*args)
    assert actual == legacy
    assert args == frozen
    assert {row["vlan"] for row in actual} == {0, 10, 20, 30, 40}
    assert all("(unscheduled)" not in row["wave"] for row in actual)


def test_wave_order_uses_whole_labels_and_excludes_unmatched_hosts():
    groups = [{"group": "Later, measured", "switches": ["gateway"]},
              {"group": "Pilot", "switches": ["access"]}]
    rows = {row["vlan"]: row for row in analyze.compute_vlan_cutover_matrix(_fabric(), move_groups=groups)}
    assert rows[10]["wave"] == "Later, measured, Pilot"
    assert rows[20]["wave"] == "Later, measured"
    reverse = list(reversed(groups))
    reversed_rows = {row["vlan"]: row
                     for row in analyze.compute_vlan_cutover_matrix(_fabric(), move_groups=reverse)}
    assert reversed_rows[10]["wave"] == "Pilot, Later, measured"
    # A VLAN on an observed but unmatched switch has no published group label to inherit.
    only_outside = {"outside": {"Gi1/0/4": InterfaceData(switchport_mode="Access", vlan="10")}}
    assert analyze.compute_vlan_cutover_matrix(only_outside, move_groups=groups)[0]["wave"] == ""
