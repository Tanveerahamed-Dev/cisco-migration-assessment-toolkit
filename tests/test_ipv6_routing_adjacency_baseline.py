"""Strict source-bound IPv6 routing-adjacency owner contract."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle

import pytest

import cisco_toolkit.ipv6_routing as ipv6_routing_module
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.ipv6_routing import (
    IPV6_ROUTING_ADJACENCY_SCHEMA,
    IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
    compute_ipv6_routing_adjacency_baseline,
    compute_ipv6_routing_subject_scope,
    embedded_ipv6_routing_adjacency_baseline,
    validate_ipv6_routing_adjacency_baseline,
)


ROOT_KEYS = {
    "schema", "scope", "verdict", "assessed", "projection_custody",
    "rows", "coverage", "findings", "summary", "limitations",
}
ROW_KEYS = {
    "switch", "platform", "protocol", "routing_instance", "process",
    "peer", "peer_key", "interface", "remote_as", "role", "state_raw",
    "state", "prefix_count", "prefix_count_present", "status", "command",
    "acceptance", "source_key", "projection_custody", "findings",
}
COVERAGE_KEYS = {
    "switch", "platform", "input", "protocol", "subject", "status",
    "selected_command", "capture_status", "parser_status",
    "candidate_count", "parsed_count", "rejected_count",
    "active_route_count", "source_sha256", "projection_sha256",
    "finding_codes",
}


def _route(*, ospf: int = 1, bgp: int = 1) -> str:
    entries = 8 + ospf + bgp
    return f"""\
IPv6 Routing Table - default - {entries} entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
ospf 1          {ospf}           0           96          144
bgp 65001       {bgp}           0           96          144
Total           {entries}          0           960         1440
"""


def _nx_route(*, vrf: str = "default", ospf: int = 2, bgp: int = 2) -> str:
    return f'''\
IPv6 Routing Table for VRF "{vrf}"
Total number of routes: 10
Total number of paths:  {10 + ospf + bgp}

Best paths per protocol:      Backup paths per protocol:
  local          : 5            None
  direct         : 5
  ospfv3-p1      : {ospf}
  bgp-65001      : {bgp}
Number of routes per mask-length:
  /64: 6       /128: 4
'''


def _ospf(*rows: tuple[str, str, str], process: str = "1") -> str:
    lines = [
        f"OSPFv3 {process} address-family ipv6 (router-id 10.0.0.4)",
        "Neighbor ID     Pri   State           Dead Time   Interface ID    Interface",
    ]
    for index, (peer, state, interface) in enumerate(rows, 16):
        lines.append(
            f"{peer:<15} 1   {state:<15} 00:00:37    {index:<15} {interface}")
    return "\n".join(lines) + "\n"


def _nx_ospf(*, vrf: str = "default", up_time: str = "2d03h") -> str:
    # Verbatim public NX-OS sample values from Cisco's command reference:
    # https://www.cisco.com/en/US/docs/switches/datacenter/sw/4_2/nx-os/unicast/command/reference/l3_cmds_show.html
    return f"""\
OSPFv3 Process ID p1 vrf {vrf}
Total number of neighbors: 2
Neighbor ID     Pri State      Up Time  Interface ID Interface
60.60.60.60       1 FULL/DR    {up_time}    5            GigE2/0/5
  Neighbor address fe80::0206:d6ff:fec8:a41c
60.60.60.60       1 FULL/DR    {up_time}    4            GigE2/0/6
  Neighbor address fe80::0206:d6ff:fec8:a408
"""


def _bgp(*rows: tuple[str, str, str]) -> str:
    lines = [
        "BGP router identifier 10.0.0.4, local AS number 65001",
        "Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd",
    ]
    for peer, remote_as, state in rows:
        lines.append(
            f"{peer:<25} 4      {remote_as:<5} 10 11 15 0 0 1d02h {state}")
    return "\n".join(lines) + "\n"


def _nx_bgp(
        *rows: tuple[str, str, str],
        banner: str = (
            "BGP summary information for VRF default, address family "
            "IPv6 Unicast"
        ),
        configured: int | None = None,
        capable: int | None = None,
) -> str:
    configured = len(rows) if configured is None else configured
    capable = len(rows) if capable is None else capable
    lines = [
        banner,
        "BGP router identifier 10.0.0.4, local AS number 65001",
        (
            "BGP table version is 15, IPv6 Unicast config peers "
            f"{configured}, capable peers {capable}"
        ),
        (
            "Neighbor                  V         AS  MsgRcvd  MsgSent  "
            "TblVer  InQ OutQ Up/Down  State/PfxRcd"
        ),
    ]
    for peer, remote_as, state in rows:
        lines.append(
            f"{peer:<25} 4      {remote_as:<5} 10 11 15 0 0 1d02h {state}")
    return "\n".join(lines) + "\n"


def _bgp_line(peer: str = "2001:db8::1", *, version: str = "4",
              remote_as: str = "65001", counters: tuple[str, ...] = (
                  "10", "11", "15", "0", "0"),
              up_down: str = "1d02h", state: str = "0") -> str:
    return " ".join((peer, version, remote_as, *counters, up_down, state))


def _write_captures(tmp_path, commands: dict[str, str], *, host: str = "sw1"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {host: {}}
    for index, (command, body) in enumerate(commands.items()):
        path = tmp_path / f"capture-{index}.txt"
        path.write_text(body, encoding="utf-8")
        paths[host][command] = str(path)
    return paths


def _owner(tmp_path, commands: dict[str, str], *, platform: str = "ios"):
    paths = _write_captures(tmp_path, commands)
    value = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": platform}},
    )
    return paths, value


def _rehash(value: dict) -> None:
    payload = copy.deepcopy(value)
    payload["summary"].pop("baseline_sha256", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    value["summary"]["baseline_sha256"] = hashlib.sha256(encoded).hexdigest()


def _rehash_coverage_source(cell: dict) -> None:
    payload = {
        key: cell[key] for key in COVERAGE_KEYS
        if key not in {"source_sha256", "projection_sha256"}
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    cell["source_sha256"] = hashlib.sha256(encoded).hexdigest()


def _rehash_coverage_projection(value: dict, cell: dict) -> None:
    rows_by_family: dict[tuple[str, str], list[dict]] = {}
    for row in value["rows"]:
        rows_by_family.setdefault(
            (row["switch"], row["protocol"]), []).append(row)
    payload = ipv6_routing_module._coverage_projection_payload(
        cell, rows_by_family)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    cell["projection_sha256"] = hashlib.sha256(encoded).hexdigest()


def test_exstart_and_active_are_source_bound_blockers_with_exact_denominators(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.9", "EXSTART/-", "GigabitEthernet0/1")),
        "show bgp ipv6 unicast summary": _bgp(
            ("2001:DB8:0:9::9", "65009", "Active")),
    })
    assert set(baseline) == ROOT_KEYS
    assert baseline["schema"] == IPV6_ROUTING_ADJACENCY_SCHEMA
    assert baseline["verdict"] == "BLOCKED"
    assert baseline["assessed"] is True
    assert len(baseline["coverage"]) == 3
    assert all(set(row) == ROW_KEYS for row in baseline["rows"])
    assert all(set(cell) == COVERAGE_KEYS for cell in baseline["coverage"])
    assert all(
        cell["candidate_count"] == cell["parsed_count"] + cell["rejected_count"]
        for cell in baseline["coverage"])
    assert [(row["protocol"], row["state"], row["status"])
            for row in baseline["rows"]] == [
        ("OSPFv3", "EXSTART", "degraded"),
        ("BGPv6", "ACTIVE", "degraded"),
    ]
    assert all(row["acceptance"].startswith(
        "PRE-CUTOVER DEGRADED — BLOCKER:") for row in baseline["rows"])
    view = validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)
    assert view["valid"] is True and view["source_bound"] is True


def test_full_2way_and_numeric_pfxrcd_are_clear_but_not_expected_peer_claims(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10"),
            ("10.0.0.7", "2WAY/DROTHER", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(
            ("2001:DB8::1", "65001", "0")),
    })
    assert baseline["verdict"] == "CLEAR" and baseline["assessed"] is True
    assert {row["status"] for row in baseline["rows"]} == {"assessed"}
    bgp = next(row for row in baseline["rows"] if row["protocol"] == "BGPv6")
    assert bgp["state"] == "ESTABLISHED"
    assert bgp["prefix_count_present"] is True and bgp["prefix_count"] == 0
    assert "observed runtime adjacencies" in bgp["acceptance"]
    assert "informational and are not pinned targets" in bgp["acceptance"]


def test_healthy_row_needs_route_census_but_definite_degraded_still_wins(tmp_path):
    _paths, healthy = _owner(tmp_path / "healthy", {
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    assert healthy["verdict"] == "INDETERMINATE"
    assert healthy["rows"][0]["status"] == "not_verified"
    assert "route_census_not_verified" in {
        item["code"] for item in healthy["rows"][0]["findings"]}

    _paths, degraded = _owner(tmp_path / "degraded", {
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.9", "EXSTART/-", "Vlan10")),
    })
    assert degraded["verdict"] == "BLOCKED"
    assert degraded["assessed"] is False
    assert degraded["rows"][0]["status"] == "degraded"
    assert {item["kind"] for item in degraded["rows"][0]["findings"]} == {
        "degraded", "not_verified"}


def test_positive_route_source_without_family_capture_scopes_static_gap_row(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=3, bgp=0),
    })
    assert baseline["verdict"] == "INDETERMINATE"
    assert len(baseline["rows"]) == 1
    row = baseline["rows"][0]
    assert row["protocol"] == "OSPFv3" and row["peer"] == row["peer_key"] == ""
    assert row["state"] == "NOT_VERIFIED" and row["status"] == "not_verified"
    ospf = next(cell for cell in baseline["coverage"]
                if cell["input"] == "ospfv3_neighbors")
    assert ospf["subject"] is True and ospf["active_route_count"] == 3


def test_no_positive_subject_is_not_applicable_not_proof_of_absence(tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=0),
    })
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    scope = compute_ipv6_routing_subject_scope(
        paths, devices={"sw1": {"platform": "ios"}})
    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert baseline["rows"] == []
    assert len(baseline["coverage"]) == 3
    assert {cell["status"] for cell in baseline["coverage"]} == {
        "not_applicable"}
    assert scope == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True, "attempted": True, "reason": "ok", "rows": [],
    }
    assert "not proof" in baseline["limitations"][1]


@pytest.mark.parametrize("route_body", [
    _route(),
    "IPv6 Routing Table - default - 10 entries: "
    "4 connected, 4 local, 1 OSPF, 1 BGP\n",
    """\
IPv6 Routing Table - default - 10 entries
connected: 4
local: 4
ospf 1: 1
bgp 65001: 1
""",
    """\
IPv6 Routing Table - default - 10 entries
4 connected, 4 local, 1 OSPF, 1 BGP
""",
])
def test_bounded_route_census_forms_remain_source_bound(route_body, tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route_body,
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "1")),
    })
    assert baseline["verdict"] == "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_official_ios_route_summary_source_and_prefix_totals_close(tmp_path):
    route = """\
IPv6 Routing Table Summary - 257 entries
  37 local, 35 connected, 25 static, 0 RIP, 160 BGP
  Number of prefixes:
    /16: 1, /24: 46, /28: 10, /32: 5, /35: 25, /40: 1, /48: 63, /64: 19
    /96: 15, /112: 1, /126: 31, /127: 4, /128: 36
"""
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route,
        "show bgp ipv6 unicast summary": _bgp(
            ("2001:db8::1", "65001", "160")),
    })
    route_cell = baseline["coverage"][0]
    assert route_cell["parser_status"] == "complete"
    assert route_cell["active_route_count"] == 160
    assert baseline["verdict"] == "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("route", [
    """\
IPv6 Routing Table Summary - 257 entries
  37 local, 35 connected, 25 static, 0 RIP, 1 OSPF
  Number of prefixes:
    /128: 257
""",
    """\
IPv6 Routing Table Summary - 10 entries
  4 local, 4 connected, 1 OSPF, 1 BGP
  Number of prefixes:
    /64: 6, /128: 3
""",
    """\
IPv6 Routing Table Summary - 10 entries
  4 local, 4 connected, 1 OSPF, 1 BGP
  Number of prefixes
    /64: 6, /128: 4
""",
    """\
IPv6 Routing Table Summary - 10 entries
  4 local, 4 connected, 1 OSPF, 1 BGP
  Number of prefixes:
  Number of prefixes:
    /64: 6, /128: 4
""",
    _route().replace("Total           10", "Total           9"),
    _route() + "Total           10          0           960         1440\n",
])
def test_ios_route_source_total_prefix_or_explicit_total_mismatch_rejects(
        route, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] != "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


@pytest.mark.parametrize("residue", [
    "?spf 1: 9",
    "?spf 1          9           0           96          144",
    "?spf 1          banana      0           96          144",
])
def test_ios_route_census_rejects_malformed_source_shaped_residue(
        residue, tmp_path):
    route = f"""\
IPv6 Routing Table - default - 8 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
{residue}
Total           8           0           768         1152
"""
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")


def test_nxos_route_summary_and_backup_columns_are_bounded_source_census(
        tmp_path):
    route = _nx_route(ospf=2, bgp=1).replace(
        "Total number of paths:  13",
        "Total number of paths:  14",
    ).replace(
        "local          : 5            None",
        "local          : 5            ospfv3-p1      : 1",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route,
        "show ipv6 ospfv3 neighbors": _nx_ospf(),
        "show bgp ipv6 unicast summary": _nx_bgp(
            ("2001:db8::1", "65001", "1")),
    }, platform="nxos")
    route_cell = baseline["coverage"][0]
    assert route_cell["parser_status"] == "complete"
    assert route_cell["active_route_count"] == 4
    assert (route_cell["candidate_count"], route_cell["parsed_count"],
            route_cell["rejected_count"]) == (1, 1, 0)
    assert baseline["verdict"] == "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize(("backup_source", "protocol", "input_name"), [
    ("ospfv3-p1", "OSPFv3", "ospfv3_neighbors"),
    ("bgp-65001", "BGPv6", "bgp_ipv6_neighbors"),
])
def test_nxos_backup_only_protocol_path_establishes_subject_scope(
        backup_source, protocol, input_name, tmp_path):
    route = _nx_route(ospf=0, bgp=0).replace(
        "Total number of paths:  10",
        "Total number of paths:  11",
    ).replace(
        "local          : 5            None",
        f"local          : 5            {backup_source} : 1",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route,
    }, platform="nxos")
    route_cell = next(item for item in baseline["coverage"]
                      if item["input"] == "route_summary")
    family_cell = next(item for item in baseline["coverage"]
                       if item["input"] == input_name)
    assert route_cell["parser_status"] == "complete"
    assert route_cell["subject"] is True
    assert route_cell["active_route_count"] == 1
    assert family_cell["protocol"] == protocol
    assert family_cell["subject"] is True
    assert family_cell["active_route_count"] == 1
    assert family_cell["status"] == "not_verified"
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nxos_route_named_context_or_impossible_path_total_cannot_clear(tmp_path):
    for index, route in enumerate((
        _nx_route(vrf="Red", ospf=2, bgp=0),
        _nx_route(ospf=2, bgp=0).replace(
            "Total number of paths:  12", "Total number of paths:  9"),
    )):
        paths = _write_captures(tmp_path / str(index), {
            "show ipv6 route summary": route,
            "show ipv6 ospfv3 neighbors": _nx_ospf(),
        })
        baseline = compute_ipv6_routing_adjacency_baseline(
            paths, compute_capture_integrity_from_paths(paths),
            devices={"sw1": {"platform": "nxos"}},
        )
        assert baseline["verdict"] != "CLEAR"
        if index == 0:
            assert baseline["coverage"][0]["parser_status"] == "review"
            assert validate_ipv6_routing_adjacency_baseline(
                baseline, require_current_run=True)["valid"] is True
        else:
            assert compute_ipv6_routing_subject_scope(
                paths, {"sw1": {"platform": "nxos"}},
            )["reason"] == "scope_evidence_rejected"


def test_nxos_route_list_under_table_banner_is_not_summary_census(tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": '''\
IPv6 Routing Table for VRF "default"
2001:db8:10::/64, ubest/mbest: 1/0
  *via fe80::1, Eth1/1, [110/20], 2d03h, ospfv3-p1, intra
''',
    })
    assert compute_ipv6_routing_subject_scope(
        paths, {"sw1": {"platform": "nxos"}},
    )["reason"] == "scope_evidence_rejected"
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "nxos"}},
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_connected_local_only_census_is_valid_not_applicable(tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": """\
IPv6 Routing Table - default - 8 entries
connected: 4
local: 4
""",
    })
    scope = compute_ipv6_routing_subject_scope(paths)
    assert scope["valid"] is True and scope["rows"] == []
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths))
    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("route_body", [
    """\
IPv6 Routing Table - default - 8 entries
Codes: C - connected, L - local, O - OSPF intra
C 2001:db8:10::/64 [0/0]
 via Vlan10, directly connected
O 2001:db8:20::/64 [110/20]
 via fe80::1, Vlan10
""",
    """\
IPv6 Routing Table - default - 8 entries
connected: 4
banana: 1
""",
])
def test_generic_route_list_or_arbitrary_source_is_not_a_summary_census(
        route_body, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route_body,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths))
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_duplicate_same_value_route_sources_are_review_not_clear(tmp_path):
    route = """\
IPv6 Routing Table - default - 12 entries
connected: 4
local: 4
ospf 1: 1
ospf 2: 1
bgp 65001: 1
bgp 65002: 1
"""
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route,
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "1")),
    })
    route_cell = next(cell for cell in baseline["coverage"]
                      if cell["input"] == "route_summary")
    assert route_cell["parser_status"] == "review"
    assert "route_census_conflict" in route_cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("route_body", [
    """\
IPv6 Routing Table - default - 1 entries
connected: 4294967295
local: 1
""",
    """\
IPv6 Routing Table - default - 4294967296 entries
connected: 1
""",
])
def test_route_census_aggregate_and_header_counts_share_the_bounded_cap(
        route_body, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route_body,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths))
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


@pytest.mark.parametrize("family_body", [
    _ospf(("999.999.999.999", "FULL/DR", "Vlan10")),
    _bgp(("192.0.2.1", "65001", "12")),
    _bgp(("2001:db8::1", "banana", "12")),
])
def test_invalid_peer_or_as_candidate_rejects_scope_and_never_authorizes_clear(
        tmp_path, family_body):
    command = "show ospfv3 neighbor" if "OSPFv3" in family_body \
        else "show bgp ipv6 unicast summary"
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(), command: family_body,
    })
    scope = compute_ipv6_routing_subject_scope(paths, {"sw1": {"platform": "ios"}})
    assert scope == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": False, "attempted": True,
        "reason": "scope_evidence_rejected", "rows": [],
    }
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_duplicate_identity_and_conflicting_integrity_ok_variants_prevent_clear(tmp_path):
    duplicate = _ospf(
        ("10.0.0.1", "FULL/DR", "Vlan10"),
        ("10.0.0.1", "EXSTART/-", "Vlan10"),
    )
    _paths, baseline = _owner(tmp_path / "duplicate", {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": duplicate,
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "4")),
    })
    ospf = next(row for row in baseline["rows"] if row["protocol"] == "OSPFv3")
    assert ospf["status"] == "degraded"
    assert "ospfv3_duplicate_identity" in {
        item["code"] for item in ospf["findings"]}
    assert baseline["assessed"] is False

    _paths, conflict = _owner(tmp_path / "variants", {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
        "show ospfv3 neighbors": _ospf(("10.0.0.2", "FULL/DR", "Vlan10")),
    })
    assert conflict["verdict"] == "INDETERMINATE"
    cell = next(item for item in conflict["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert "command_variant_conflict" in cell["finding_codes"]


def test_same_valued_ospf_and_bgp_duplicate_rows_are_review(tmp_path):
    ospf_row = ("10.0.0.1", "FULL/DR", "Vlan10")
    bgp_row = ("2001:db8::1", "65001", "4")
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(ospf_row, ospf_row),
        "show bgp ipv6 unicast summary": _bgp(bgp_row, bgp_row),
    })
    assert baseline["verdict"] == "INDETERMINATE"
    assert {row["status"] for row in baseline["rows"]} == {"review"}
    cells = {cell["protocol"]: cell for cell in baseline["coverage"]}
    assert "ospfv3_duplicate_identity" in cells["OSPFv3"]["finding_codes"]
    assert "bgpv6_duplicate_identity" in cells["BGPv6"]["finding_codes"]
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("mutation", [
    lambda body: body.replace("00:00:37", "forever"),
    lambda body: body.replace("00:00:37", "2d03h"),
    lambda body: body.replace("16             ", "not-a-number   "),
    lambda body: body.replace("00:00:37    16", "00:00:37 GARBAGE 16"),
])
def test_ospf_requires_dead_time_interface_id_and_no_garbage_middle_columns(
        mutation, tmp_path):
    malformed = mutation(_ospf(("10.0.0.1", "FULL/DR", "Vlan10")))
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": malformed,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_ospf_rows_without_the_exact_header_cannot_clear(tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")).replace(
        "Neighbor ID     Pri   State           Dead Time   Interface ID    Interface",
        "Neighbor ID Pri State Dead Interface",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("bad_row", [
    "BROKEN-NEIGHBOR 1 EXSTART/- 00:00:37 2 Vlan20",
    "BROKEN-NEIGHBOR x EXSTART/- 00:00:37 2 Vlan20",
])
def test_ospf_table_shaped_invalid_neighbor_enters_candidate_denominator(
        bad_row, tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")) + bad_row + "\n"
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (2, 1, 1)
    assert cell["parser_status"] == "review"
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_ospf_rows_without_a_process_context_are_review_only(tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")).replace(
        "OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)\n", "",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert "ospfv3_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_canonical_ospfv3_router_banner_uses_process_id_not_router_word(tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")).replace(
        "OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)",
        "OSPFv3 Router with ID (42.1.1.1) (Process ID 42)",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    row = baseline["rows"][0]
    assert row["process"] == "42"
    assert row["peer_key"] == "ospfv3|default|42|10.0.0.1|vlan10"
    assert baseline["verdict"] == "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_multiple_canonical_ospfv3_process_banners_are_review(tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")).replace(
        "OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)",
        "OSPFv3 Router with ID (42.1.1.1) (Process ID 42)\n"
        "OSPFv3 Router with ID (43.1.1.1) (Process ID 43)",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert "ospfv3_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("malformed_banner", [
    "OSPFv3 ??? address-family ipv6 (router-id 43.1.1.1)",
    "OSPFv3 Router with ID (43.1.1.1) (Process ID ???)",
    'Routing Process "ospfv3 ???"',
])
def test_malformed_additional_ospfv3_process_banner_is_review_only(
        malformed_banner, tmp_path):
    body = _ospf(("10.0.0.1", "FULL/DR", "Vlan10")).replace(
        "OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)",
        "OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)\n"
        + malformed_banner,
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert "ospfv3_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("bad_row", [
    "2001:db8::1 4 65001 0",
    _bgp_line(version="999"),
    _bgp_line(counters=("garbage",) * 5),
    _bgp_line(up_down="tomorrow"),
    _bgp_line(up_down="1d99h"),
    _bgp_line(up_down="1h99m"),
    _bgp_line(up_down="1m99s"),
    _bgp_line(up_down="999y99w"),
    _bgp_line(state="Banana"),
    _bgp_line(counters=("18446744073709551616", "11", "15", "0", "0")),
    _bgp_line(state="4294967296"),
])
def test_bgp_rejects_truncated_wrong_version_garbage_or_unbounded_full_rows(
        bad_row, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": _bgp() + bad_row + "\n",
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_bgp_rows_without_the_exact_ten_column_header_cannot_clear(tmp_path):
    body = _bgp(("2001:db8::1", "65001", "1")).replace(
        "State/PfxRcd", "State",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "review"
    assert "bgpv6_candidate_rejected" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("bad_row", [
    "BROKEN-NEIGHBOR 4 65003 10 11 12 0 0 1d02h Active",
    "BROKEN-NEIGHBOR x 65003 10 11 12 0 0 1d02h Active",
])
def test_bgp_table_shaped_invalid_neighbor_enters_candidate_denominator(
        bad_row, tmp_path):
    body = _bgp(("2001:db8::1", "65001", "1")) + bad_row + "\n"
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (2, 1, 1)
    assert cell["parser_status"] == "review"
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_bgp_rows_without_a_local_as_process_banner_are_review_only(tmp_path):
    body = _bgp(("2001:db8::1", "65001", "1")).replace(
        "BGP router identifier 10.0.0.4, local AS number 65001\n", "",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "review"
    assert "bgpv6_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_malformed_additional_bgp_process_banner_is_review_only(tmp_path):
    body = _bgp(("2001:db8::1", "65001", "1")).replace(
        "BGP router identifier 10.0.0.4, local AS number 65001",
        "BGP router identifier 10.0.0.4, local AS number 65001\n"
        "BGP router identifier 10.0.0.5, local AS banana 65002",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "review"
    assert "bgpv6_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize(("up_down", "state_raw", "state", "verdict"), [
    ("00:00:37", "0", "ESTABLISHED", "CLEAR"),
    ("1w2d", "Active", "ACTIVE", "BLOCKED"),
    ("2d03h", "7", "ESTABLISHED", "CLEAR"),
    ("never", "Active", "ACTIVE", "BLOCKED"),
    ("never", "Idle (Admin)", "IDLE(ADMIN)", "BLOCKED"),
])
def test_bgp_accepts_only_supported_up_down_and_exact_state_tokens(
        up_down, state_raw, state, verdict, tmp_path):
    body = _bgp() + _bgp_line(up_down=up_down, state=state_raw) + "\n"
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    row = baseline["rows"][0]
    assert row["state"] == state and baseline["verdict"] == verdict
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "complete"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_bgp_wrapped_ipv6_neighbor_address_keeps_full_row_grammar(tmp_path):
    body = _bgp() + "2001:DB8:0:1::1\n" + (
        "4 65001 10 11 15 0 0 1d02h 7\n")
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    assert baseline["verdict"] == "CLEAR"
    assert baseline["rows"][0]["peer"] == "2001:db8:0:1::1"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_bgp_adjacent_star_marker_retains_ipv6_identity_and_state(tmp_path):
    body = _bgp() + _bgp_line(
        peer="*2001:DB8:0:1::1", remote_as="65009", state="Active",
    ) + "\n"
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    row = baseline["rows"][0]
    assert (row["peer"], row["peer_key"], row["remote_as"], row["state"]) == (
        "2001:db8:0:1::1", "bgpv6|default|2001:db8:0:1::1", "65009",
        "ACTIVE",
    )
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (1, 1, 0)
    assert baseline["verdict"] == "BLOCKED"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("marker", [">", "!", "+", "**"])
def test_bgp_rejects_unsupported_leading_neighbor_markers(marker, tmp_path):
    body = _bgp() + _bgp_line(peer=f"{marker}2001:db8::1") + "\n"
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] != "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


@pytest.mark.parametrize(("banner", "expected_status"), [
    ("BGP summary information for VRF default, address family IPv6 Unicast",
     "complete"),
    ("BGP summary information for VRF BLUE, address family IPv6 Unicast",
     "review"),
    ("BGP summary information for VRF default, address family IPv4 Unicast",
     "review"),
    ("BGP summary information for VRF default, address family IPv6 Unicast\n"
     "BGP summary information for VRF default, address family IPv6 Unicast",
     "review"),
])
def test_nxos_bgp_summary_context_is_explicitly_scoped(
        banner, expected_status, tmp_path):
    body = _nx_bgp(("2001:db8::1", "65001", "1"), banner=banner)
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == expected_status
    assert baseline["verdict"] == (
        "CLEAR" if expected_status == "complete" else "INDETERMINATE")
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nxos_wrong_address_family_is_review_even_without_ipv6_rows(tmp_path):
    body = _nx_bgp(
        ("192.0.2.1", "65001", "7"),
        banner=(
            "BGP summary information for VRF default, address family "
            "IPv4 Unicast"
        ),
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "review"
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["rows"][0]["peer_key"] == ""
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nxos_bgp_configured_peer_denominator_closes_exact_two_rows(tmp_path):
    body = _nx_bgp(
        ("2001:db8::1", "65001", "1"),
        ("2001:db8::2", "65002", "2"),
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=0, bgp=2),
        "show bgp ipv6 unicast summary": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "complete"
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (2, 2, 0)
    assert baseline["verdict"] == "CLEAR"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize(("mutation", "expected_status"), [
    (lambda body: "\n".join(
        line for line in body.splitlines()
        if not line.startswith("BGP table version is")
    ) + "\n", "review"),
    (lambda body: body.replace("config peers 2", "config peers banana"),
     "review"),
    (lambda body: body.replace(
        "BGP table version is 15, IPv6 Unicast config peers 2, capable peers 2",
        "BGP table version is 15, IPv6 Unicast config peers 2, capable peers 2\n"
        "BGP table version is 15, IPv6 Unicast config peers 2, capable peers 2",
    ), "review"),
    (lambda body: body.replace("config peers 2", "config peers 3"), "review"),
    (lambda body: body.replace("capable peers 2", "capable peers 3"), "review"),
    (lambda body: body.replace("config peers 2", "config peers 8193"),
     "rejected"),
])
def test_nxos_bgp_peer_denominator_missing_malformed_repeated_mismatch_or_cap(
        mutation, expected_status, tmp_path):
    body = mutation(_nx_bgp(
        ("2001:db8::1", "65001", "1"),
        ("2001:db8::2", "65002", "2"),
    ))
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=0, bgp=2),
        "show bgp ipv6 unicast summary": body,
    })
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "nxos"}},
    )
    assert baseline["verdict"] != "CLEAR"
    if expected_status == "review":
        cell = next(item for item in baseline["coverage"]
                    if item["input"] == "bgp_ipv6_neighbors")
        assert cell["parser_status"] == "review"
        assert "bgpv6_context_review" in cell["finding_codes"]
        assert validate_ipv6_routing_adjacency_baseline(
            baseline, require_current_run=True)["valid"] is True
    else:
        assert compute_ipv6_routing_subject_scope(
            paths, {"sw1": {"platform": "nxos"}},
        )["reason"] == "scope_evidence_rejected"


def test_nxos_plural_command_is_selected_before_fallback(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": _nx_ospf(),
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["selected_command"] == "show ipv6 ospfv3 neighbors"
    assert baseline["rows"][0]["command"] == "show ipv6 ospfv3 neighbors"


def test_nxos_ospfv3_up_time_rows_and_declared_denominator_parse_exactly(
        tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": _nx_ospf(),
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "complete"
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (2, 2, 0)
    assert baseline["verdict"] == "CLEAR"
    assert [(row["process"], row["peer"], row["interface"], row["state"])
            for row in baseline["rows"]] == [
        ("p1", "60.60.60.60", "GigE2/0/5", "FULL"),
        ("p1", "60.60.60.60", "GigE2/0/6", "FULL"),
    ]
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nxos_ospfv3_named_vrf_is_parsed_but_review_only(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": _nx_ospf(vrf="Red"),
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parsed_count"] == 2 and cell["parser_status"] == "review"
    assert "ospfv3_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


@pytest.mark.parametrize("body", [
    _nx_ospf().replace("OSPFv3 Process ID p1 vrf default\n", ""),
    _nx_ospf().replace(
        "OSPFv3 Process ID p1 vrf default",
        "OSPFv3 Process ID p1",
    ),
    _nx_ospf().replace(
        "OSPFv3 Process ID p1 vrf default",
        "OSPFv3 Process ID p1 vrf default\n"
        "OSPFv3 Process ID p1 vrf default",
    ),
])
def test_nxos_ospfv3_context_missing_malformed_or_repeated_is_review_only(
        body, tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["parser_status"] == "review"
    assert "ospfv3_context_review" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"


@pytest.mark.parametrize(("body", "expected_status"), [
    (_nx_ospf().replace("Total number of neighbors: 2\n", ""), "review"),
    (_nx_ospf().replace("neighbors: 2", "neighbors: 3"), "review"),
    (_nx_ospf().replace("neighbors: 2", "neighbors: banana"), "review"),
    (_nx_ospf().replace(
        "Total number of neighbors: 2",
        "Total number of neighbors: 2\nTotal number of neighbors: 2",
    ), "review"),
    (_nx_ospf().replace("neighbors: 2", "neighbors: 8193"), "rejected"),
])
def test_nxos_ospfv3_total_missing_malformed_repeated_mismatch_or_cap_never_clears(
        body, expected_status, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": body,
    })
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "nxos"}},
    )
    assert baseline["verdict"] != "CLEAR"
    if expected_status == "review":
        cell = next(item for item in baseline["coverage"]
                    if item["input"] == "ospfv3_neighbors")
        assert cell["parser_status"] == expected_status
        assert validate_ipv6_routing_adjacency_baseline(
            baseline, require_current_run=True)["valid"] is True
    else:
        assert compute_ipv6_routing_subject_scope(
            paths, {"sw1": {"platform": "nxos"}},
        )["reason"] == "scope_evidence_rejected"


def test_nxos_ospfv3_duplicate_candidates_reconcile_total_then_review(tmp_path):
    body = _nx_ospf().replace(
        "60.60.60.60       1 FULL/DR    2d03h    4            GigE2/0/6",
        "60.60.60.60       1 FULL/DR    2d03h    5            GigE2/0/5",
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert (cell["candidate_count"], cell["parsed_count"],
            cell["rejected_count"]) == (2, 1, 1)
    assert cell["parser_status"] == "review"
    assert "ospfv3_duplicate_identity" in cell["finding_codes"]
    assert baseline["verdict"] == "INDETERMINATE"


@pytest.mark.parametrize("up_time", ["forever", "1d99h", "24:00:00"])
def test_nxos_ospfv3_rejects_unbounded_or_invalid_up_time(up_time, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _nx_route(ospf=2, bgp=0),
        "show ipv6 ospfv3 neighbors": _nx_ospf(up_time=up_time),
    })
    assert compute_ipv6_routing_subject_scope(
        paths, {"sw1": {"platform": "nxos"}},
    )["reason"] == "scope_evidence_rejected"


def test_current_marker_deepcopy_json_embedding_tamper_and_reseal_boundaries(tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "7")),
    })
    assert validate_ipv6_routing_adjacency_baseline(
        current, require_current_run=True)["valid"] is True

    deep = copy.deepcopy(current)
    assert deep["projection_custody"] == "embedded_unverified"
    assert validate_ipv6_routing_adjacency_baseline(deep)["valid"] is True
    assert validate_ipv6_routing_adjacency_baseline(
        deep, require_current_run=True)["reason"] == (
            "baseline_not_current_run_source_bound")

    ordinary = json.loads(json.dumps(current))
    ordinary_view = validate_ipv6_routing_adjacency_baseline(ordinary)
    assert ordinary_view["valid"] is True and ordinary_view["source_bound"] is False
    assert validate_ipv6_routing_adjacency_baseline(
        ordinary, require_current_run=True)["valid"] is False

    embedded = embedded_ipv6_routing_adjacency_baseline(current)
    assert embedded["projection_custody"] == "embedded_unverified"
    assert validate_ipv6_routing_adjacency_baseline(embedded)["valid"] is True

    restored = pickle.loads(pickle.dumps(current))
    assert type(restored) is dict
    assert restored["projection_custody"] == "embedded_unverified"
    assert validate_ipv6_routing_adjacency_baseline(restored)["valid"] is True
    assert validate_ipv6_routing_adjacency_baseline(
        restored, require_current_run=True)["valid"] is False

    semantic = copy.deepcopy(embedded)
    semantic["rows"][0]["acceptance"] = "HOSTILE HEALTHY ACCEPTANCE"
    _rehash(semantic)
    rejected = validate_ipv6_routing_adjacency_baseline(semantic)
    assert rejected["valid"] is False and rejected["rows"] == []
    assert "HOSTILE" not in json.dumps(rejected)

    current["summary"]["n_rows"] += 1
    _rehash(current)
    assert validate_ipv6_routing_adjacency_baseline(
        current, require_current_run=True)["source_bound"] is False


@pytest.mark.parametrize(("parser_status", "counts", "finding_codes"), [
    ("complete", (0, 0, 0), []),
    ("review", (1, 0, 1), ["route_context_review"]),
    ("rejected", (2, 1, 1), ["route_census_rejected"]),
    ("not_verified", (0, 0, 0), []),
    ("explicit_no_subject", (0, 0, 0), []),
])
def test_validator_rejects_rehashed_impossible_route_census_count_tuple(
        parser_status, counts, finding_codes, tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    hostile = embedded_ipv6_routing_adjacency_baseline(current)
    route_cell = next(cell for cell in hostile["coverage"]
                      if cell["input"] == "route_summary")
    route_cell["parser_status"] = parser_status
    (route_cell["candidate_count"], route_cell["parsed_count"],
     route_cell["rejected_count"]) = counts
    route_cell["finding_codes"] = finding_codes
    _rehash_coverage_source(route_cell)
    _rehash(hostile)
    rejected = validate_ipv6_routing_adjacency_baseline(hostile)
    assert rejected["valid"] is False
    assert rejected["reason"] == (
        "baseline_coverage_source_parser_invalid"
        if parser_status == "rejected"
        else "baseline_coverage_parser_count_invalid"
    )


def test_validator_rejects_rehashed_successful_rejected_route_census(tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=0),
    })
    hostile = embedded_ipv6_routing_adjacency_baseline(current)
    route_cell = next(cell for cell in hostile["coverage"]
                      if cell["input"] == "route_summary")
    assert route_cell["subject"] is False
    route_cell["parser_status"] = "rejected"
    (route_cell["candidate_count"], route_cell["parsed_count"],
     route_cell["rejected_count"]) = (1, 0, 1)
    route_cell["finding_codes"] = ["route_census_rejected"]
    _rehash_coverage_source(route_cell)
    _rehash(hostile)
    rejected = validate_ipv6_routing_adjacency_baseline(hostile)
    assert rejected["valid"] is False
    assert rejected["reason"] == "baseline_coverage_source_parser_invalid"


@pytest.mark.parametrize("input_name", [
    "ospfv3_neighbors", "bgp_ipv6_neighbors",
])
@pytest.mark.parametrize(("parser_status", "counts", "finding_codes"), [
    ("complete", (0, 0, 0), []),
    ("rejected", (1, 0, 1), ["ospfv3_candidate_rejected"]),
    ("not_verified", (0, 0, 0), []),
    ("explicit_no_subject", (0, 0, 0), []),
])
def test_validator_rejects_rehashed_successful_no_subject_family_capture(
        input_name, parser_status, counts, finding_codes, tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=0),
    })
    hostile = embedded_ipv6_routing_adjacency_baseline(current)
    cell = next(item for item in hostile["coverage"]
                if item["input"] == input_name)
    assert cell["subject"] is False
    cell["capture_status"] = "ok"
    cell["parser_status"] = parser_status
    (cell["candidate_count"], cell["parsed_count"],
     cell["rejected_count"]) = counts
    cell["finding_codes"] = finding_codes
    _rehash_coverage_source(cell)
    _rehash(hostile)
    rejected = validate_ipv6_routing_adjacency_baseline(hostile)
    assert rejected["valid"] is False
    assert rejected["reason"] == "baseline_coverage_source_parser_invalid"


@pytest.mark.parametrize(("protocol", "mutation"), [
    ("OSPFv3", "remove"),
    ("BGPv6", "remove"),
    ("OSPFv3", "split"),
    ("BGPv6", "split"),
])
def test_validator_rejects_rehashed_missing_or_split_family_process_identity(
        protocol, mutation, tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=2, bgp=2),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10"),
            ("10.0.0.2", "FULL/DR", "Vlan20"),
        ),
        "show bgp ipv6 unicast summary": _bgp(
            ("2001:db8::1", "65001", "1"),
            ("2001:db8::2", "65002", "2"),
        ),
    })
    hostile = embedded_ipv6_routing_adjacency_baseline(current)
    family_rows = [
        row for row in hostile["rows"] if row["protocol"] == protocol
    ]
    target = family_rows[0 if mutation == "remove" else 1]
    if mutation == "remove":
        target["process"] = ""
        if protocol == "OSPFv3":
            parts = target["peer_key"].split("|")
            parts[2] = "-"
            target["peer_key"] = "|".join(parts)
    else:
        target["process"] = "2" if protocol == "OSPFv3" else "65009"
        if protocol == "OSPFv3":
            parts = target["peer_key"].split("|")
            parts[2] = "2"
            target["peer_key"] = "|".join(parts)
    target["acceptance"] = ipv6_routing_module._acceptance(target)
    input_name = (
        "ospfv3_neighbors" if protocol == "OSPFv3"
        else "bgp_ipv6_neighbors"
    )
    cell = next(item for item in hostile["coverage"]
                if item["input"] == input_name)
    _rehash_coverage_projection(hostile, cell)
    _rehash(hostile)
    assert validate_ipv6_routing_adjacency_baseline(hostile)["valid"] is False


def test_projection_hashing_uses_one_family_index_without_full_row_rescans(
        tmp_path, monkeypatch):
    original = ipv6_routing_module._coverage_projection_payload
    observed_indexes: list[dict] = []

    def guarded(cell, rows_by_family):
        assert isinstance(rows_by_family, dict)
        assert all(
            isinstance(key, tuple) and len(key) == 2
            for key in rows_by_family
        )
        # Retain the mappings themselves so allocator id reuse cannot make the
        # one-index-per-pass assertion flaky.
        observed_indexes.append(rows_by_family)
        return original(cell, rows_by_family)

    monkeypatch.setattr(
        ipv6_routing_module, "_coverage_projection_payload", guarded)
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(
            ("2001:db8::1", "65001", "1")),
    })
    # Producer hashing and its mandatory self-validation each build one
    # family index, then reuse it for every coverage cell.
    assert len(observed_indexes) == 2 * len(baseline["coverage"])
    identities = {id(index) for index in observed_indexes}
    assert len(identities) == 2
    assert all(
        sum(index is candidate for index in observed_indexes)
        == len(baseline["coverage"])
        for candidate in {id(index): index for index in observed_indexes}.values()
    )

    observed_indexes.clear()
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True
    assert len(observed_indexes) == len(baseline["coverage"])
    assert len({id(index) for index in observed_indexes}) == 1


def test_scope_receipt_positive_attempted_empty_rejected_collision_and_cap(tmp_path):
    paths = _write_captures(tmp_path / "positive", {
        "show ipv6 route summary": _route(ospf=2, bgp=3),
    })
    assert compute_ipv6_routing_subject_scope(paths, {"sw1": {"platform": "ios"}}) == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True, "attempted": True, "reason": "ok",
        "rows": [{
            "switch": "sw1", "platform": "ios",
            "protocols": ["OSPFv3", "BGPv6"],
        }],
    }

    empty_paths = _write_captures(tmp_path / "empty", {
        "show ospfv3 neighbor": "% Invalid input detected at '^' marker.\n",
    })
    assert compute_ipv6_routing_subject_scope(empty_paths)["rows"] == []
    assert compute_ipv6_routing_subject_scope(empty_paths)["attempted"] is True

    assert compute_ipv6_routing_subject_scope(
        {"sw1": {"show ospfv3 neighbor": object()}}) == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": False, "attempted": True,
        "reason": "scope_evidence_rejected", "rows": [],
    }
    collision = {
        "SW1": {}, "sw1": {"show ospfv3 neighbor": empty_paths["sw1"][
            "show ospfv3 neighbor"]},
    }
    assert compute_ipv6_routing_subject_scope(collision)["reason"] == (
        "scope_identity_collision")
    over_cap = {f"host-{index}": {} for index in range(4097)}
    assert compute_ipv6_routing_subject_scope(over_cap)["reason"] == (
        "scope_host_cap_exceeded")


@pytest.mark.parametrize(("artifact", "expected_status"), [
    ("--More--", "incomplete"),
    ("% Invalid input detected at '^' marker.", "error"),
])
def test_exact_body_reinspection_overrides_stale_integrity_ok_receipt(
        artifact, expected_status, tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    stale_integrity = compute_capture_integrity_from_paths(paths)
    family_path = paths["sw1"]["show ospfv3 neighbor"]
    with open(family_path, "a", encoding="utf-8") as handle:
        handle.write(artifact + "\n")

    scope = compute_ipv6_routing_subject_scope(
        paths, {"sw1": {"platform": "ios"}})
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, stale_integrity, devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] != "CLEAR"
    if expected_status == "incomplete":
        assert scope["reason"] == "scope_evidence_rejected"
        assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False
    else:
        assert scope["valid"] is True
        cell = next(item for item in baseline["coverage"]
                    if item["input"] == "ospfv3_neighbors")
        assert cell["capture_status"] == expected_status
        assert cell["status"] == "not_verified"
        assert validate_ipv6_routing_adjacency_baseline(
            baseline, require_current_run=True)["valid"] is True


def test_strict_utf8_rejects_bytes_capture_integrity_would_ignore(tmp_path):
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    family_path = paths["sw1"]["show ospfv3 neighbor"]
    raw = open(family_path, "rb").read().replace(b"FULL", b"FU\xffLL")
    with open(family_path, "wb") as handle:
        handle.write(raw)
    integrity = compute_capture_integrity_from_paths(paths)
    assert next(item for item in integrity["inspections"]
                if item["command"] == "show ospfv3 neighbor")["status"] == "ok"
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, integrity, devices={"sw1": {"platform": "ios"}},
    )
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_ascii_identity_contract_matches_producer_scoper_and_validator(tmp_path):
    unicode_paths = _write_captures(tmp_path / "host", {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
    }, host="swé")
    assert compute_ipv6_routing_subject_scope(unicode_paths)["reason"] == (
        "scope_identity_invalid")
    unicode_baseline = compute_ipv6_routing_adjacency_baseline(
        unicode_paths, compute_capture_integrity_from_paths(unicode_paths))
    assert validate_ipv6_routing_adjacency_baseline(unicode_baseline)["valid"] is False

    paths, current = _owner(tmp_path / "validator", {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    assert paths
    embedded = embedded_ipv6_routing_adjacency_baseline(current)
    embedded["rows"][0]["switch"] = "swé"
    _rehash(embedded)
    rejected = validate_ipv6_routing_adjacency_baseline(embedded)
    assert rejected["valid"] is False
    assert rejected["reason"] == "baseline_row_text_invalid"

    platform = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "iös"}},
    )
    assert validate_ipv6_routing_adjacency_baseline(platform)["valid"] is False


def test_bgp_candidate_denominator_overflow_never_emits_invalid_private_marker(
        tmp_path):
    rows = "\n".join(
        _bgp_line(peer=f"2001:db8::{index:x}")
        for index in range(1, 8194)
    )
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": _bgp() + rows + "\n",
    })
    assert compute_ipv6_routing_subject_scope(paths)["reason"] == (
        "scope_evidence_rejected")
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["projection_custody"] == "embedded_unverified"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_multiple_route_context_never_authorizes_healthy_clear(tmp_path):
    route = _route() + _route(ospf=9, bgp=9).replace("default", "BLUE", 1)
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": route,
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "1")),
    })
    assert baseline["verdict"] == "INDETERMINATE"
    assert {row["status"] for row in baseline["rows"]} == {"not_verified"}
    route_cell = baseline["coverage"][0]
    assert route_cell["parser_status"] == "review"
    assert "route_context_review" in route_cell["finding_codes"]


def test_named_route_table_before_default_preserves_default_subjects(tmp_path):
    route = _route(ospf=0, bgp=0).replace("default", "BLUE", 1) + _route()
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route,
    })
    assert compute_ipv6_routing_subject_scope(
        paths, devices={"sw1": {"platform": "ios"}},
    ) == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True, "attempted": True, "reason": "ok",
        "rows": [{
            "switch": "sw1", "platform": "ios",
            "protocols": ["OSPFv3", "BGPv6"],
        }],
    }
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    route_cell = baseline["coverage"][0]
    assert route_cell["parser_status"] == "review"
    assert route_cell["active_route_count"] == 2
    assert "route_context_review" in route_cell["finding_codes"]
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True,
    )["valid"] is True


def test_second_default_route_table_cannot_hide_protocol_subjects(tmp_path):
    route = """\
IPv6 Routing Table - default - 8 entries
connected: 4
local: 4
""" + _route()
    paths = _write_captures(tmp_path, {
        "show ipv6 route summary": route,
    })
    assert compute_ipv6_routing_subject_scope(paths) == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": False, "attempted": True,
        "reason": "scope_evidence_rejected", "rows": [],
    }
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "INDETERMINATE"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False


def test_validator_is_total_bounded_and_never_echoes_hostile_leaves(tmp_path):
    _paths, current = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ospfv3 neighbor": _ospf(("10.0.0.1", "FULL/DR", "Vlan10")),
    })
    embedded = embedded_ipv6_routing_adjacency_baseline(current)

    deep = copy.deepcopy(embedded)
    nested: object = "HOSTILE-DEEP-LEAF"
    for _index in range(20):
        nested = [nested]
    deep["findings"] = nested
    over_rows = copy.deepcopy(embedded)
    over_rows["rows"] = [{}] * 20_001
    over_coverage = copy.deepcopy(embedded)
    over_coverage["coverage"] = [{}] * 12_289
    malformed = {"schema": IPV6_ROUTING_ADJACENCY_SCHEMA,
                 "rows": [{"acceptance": "HOSTILE-ECHO"}]}
    for candidate in (None, [], deep, over_rows, over_coverage, malformed):
        result = validate_ipv6_routing_adjacency_baseline(candidate)
        assert result["valid"] is False
        assert result["rows"] == [] and result["index"] == {} \
            and result["baseline"] == {}
        rendered = json.dumps(result)
        assert "HOSTILE" not in rendered


def test_receipt_never_publishes_capture_paths_raw_text_or_secret_lines(tmp_path):
    secret = "password SUPER-SECRET-PARSER-INPUT"
    paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(),
        "show ospfv3 neighbor": _ospf(
            ("10.0.0.1", "FULL/DR", "Vlan10")) + secret + "\n",
        "show bgp ipv6 unicast summary": _bgp(("2001:db8::1", "65001", "1")),
    })
    rendered = json.dumps(baseline)
    assert str(tmp_path) not in rendered
    assert secret not in rendered
    assert all(path not in rendered for path in paths["sw1"].values())
