"""Strict source-bound IPv6 routing-adjacency owner contract."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle

import pytest

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
    return f"""\
IPv6 Routing Table - default - 8 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
ospf 1          {ospf}           0           96          144
bgp 65001       {bgp}           0           96          144
Total           10          0           960         1440
"""


def _ospf(*rows: tuple[str, str, str], process: str = "1") -> str:
    lines = [
        f"OSPFv3 {process} address-family ipv6 (router-id 10.0.0.4)",
        "Neighbor ID     Pri   State           Dead Time   Interface ID    Interface",
    ]
    for index, (peer, state, interface) in enumerate(rows, 16):
        lines.append(
            f"{peer:<15} 1   {state:<15} 00:00:37    {index:<15} {interface}")
    return "\n".join(lines) + "\n"


def _bgp(*rows: tuple[str, str, str]) -> str:
    lines = [
        "BGP router identifier 10.0.0.4, local AS number 65001",
        "Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd",
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
    "IPv6 Routing Table - default - 8 entries: "
    "4 connected, 4 local, 1 OSPF, 1 BGP\n",
    """\
IPv6 Routing Table - default - 8 entries
connected: 4
local: 4
ospf 1: 1
bgp 65001: 1
""",
    """\
IPv6 Routing Table - default - 8 entries
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
IPv6 Routing Table - default - 8 entries
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
    body = banner + "\n" + _bgp(("2001:db8::1", "65001", "1"))
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
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
    body = (
        "BGP summary information for VRF default, address family IPv4 Unicast\n"
        + _bgp() + _bgp_line(peer="192.0.2.1", state="7") + "\n"
    )
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=0, bgp=1),
        "show bgp ipv6 unicast summary": body,
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "bgp_ipv6_neighbors")
    assert cell["parser_status"] == "review"
    assert baseline["verdict"] == "INDETERMINATE"
    assert baseline["rows"][0]["peer_key"] == ""
    assert validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True)["valid"] is True


def test_nxos_plural_command_is_selected_before_fallback(tmp_path):
    _paths, baseline = _owner(tmp_path, {
        "show ipv6 route summary": _route(ospf=1, bgp=0),
        "show ipv6 ospfv3 neighbors": _ospf(
            ("10.0.0.1", "FULL/DR", "Ethernet1/1")),
    }, platform="nxos")
    cell = next(item for item in baseline["coverage"]
                if item["input"] == "ospfv3_neighbors")
    assert cell["selected_command"] == "show ipv6 ospfv3 neighbors"
    assert baseline["rows"][0]["command"] == "show ipv6 ospfv3 neighbors"


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
