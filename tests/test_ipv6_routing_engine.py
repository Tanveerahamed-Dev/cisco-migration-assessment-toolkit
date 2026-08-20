"""Current-run IPv6 routing adjacency truth reaches every cutover consumer."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from cisco_toolkit.analyze import (
    compute_current_baseline_gate,
    compute_migration_punchlist,
    compute_migration_readiness,
    compute_validation_plan,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.ipv6_routing import (
    IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
    compute_ipv6_routing_adjacency_baseline,
    compute_ipv6_routing_subject_scope,
    embedded_ipv6_routing_adjacency_baseline,
    validate_ipv6_routing_adjacency_baseline,
)
from cisco_toolkit.nrfu_export import compute_nrfu_commands


ROUTE_SUMMARY = """\
IPv6 Routing Table - default - 10 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
ospf 1          1           0           96          144
bgp 65001       1           0           96          144
Total           10          0           960         1440
"""


def _ospfv3(*rows: tuple[str, str, str]) -> str:
    body = [
        "            OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)",
        "",
        "Neighbor ID     Pri   State           Dead Time   Interface ID    Interface",
    ]
    for index, (peer, state, interface) in enumerate(rows, 16):
        body.append(
            f"{peer:<15}    1   {state:<15} 00:00:37    {index:<15} {interface}"
        )
    return "\n".join(body) + "\n"


def _bgpv6(*rows: tuple[str, str, str]) -> str:
    body = [
        "BGP router identifier 10.0.0.4, local AS number 65001",
        "BGP table version is 15, main routing table version 15",
        "Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd",
    ]
    for peer, remote_as, state in rows:
        body.append(
            f"{peer:<25} 4      {remote_as:<5}      10       11      15    0    0 1d02h          {state}"
        )
    return "\n".join(body) + "\n"


def _owner(
        tmp_path, *, ospf_rows: tuple[tuple[str, str, str], ...],
        bgp_rows: tuple[tuple[str, str, str], ...], include_ospf: bool = True,
        include_bgp: bool = True):
    paths = {"sw1": {}}
    bodies = {"show ipv6 route summary": ROUTE_SUMMARY}
    if include_ospf:
        bodies["show ospfv3 neighbor"] = _ospfv3(*ospf_rows)
    if include_bgp:
        bodies["show bgp ipv6 unicast summary"] = _bgpv6(*bgp_rows)
    for command, body in bodies.items():
        capture = tmp_path / (command.replace(" ", "_") + ".txt")
        capture.write_text(body, encoding="utf-8")
        paths["sw1"][command] = str(capture)
    devices = {"sw1": {"platform": "ios"}}
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths), devices=devices,
    )
    scope = compute_ipv6_routing_subject_scope(paths, devices=devices)
    validated = validate_ipv6_routing_adjacency_baseline(
        baseline, require_current_run=True,
    )
    assert validated["valid"] is True
    assert validated["source_bound"] is True
    return baseline, scope


def _owner_from_bodies(tmp_path, bodies: dict[str, str]):
    paths = {"sw1": {}}
    for command, body in bodies.items():
        capture = tmp_path / (command.replace(" ", "_") + ".txt")
        capture.write_text(body, encoding="utf-8")
        paths["sw1"][command] = str(capture)
    devices = {"sw1": {"platform": "ios"}}
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths), devices=devices,
    )
    scope = compute_ipv6_routing_subject_scope(paths, devices=devices)
    return baseline, scope


def _dep_map():
    return {
        "single_fiber": [], "errdis": [], "halfdup_up": [], "sole_gw": {},
        "orphan": set(), "access_by_vlan": {}, "model": {"hosts": ["sw1"]},
    }


def _surfaces(baseline, *, scope=None):
    interfaces = {"sw1": {}}
    groups = [{"switches": ["sw1"], "endpoints": 0}]
    devices = {"sw1": {"platform": "ios"}}
    readiness = compute_migration_readiness(
        interfaces, groups, [{"switch": "sw1", "band": "Good"}],
        [{"switch": "sw1"}], [], [], [], _dep_map(),
        ipv6_routing_adjacency_baseline=baseline,
        ipv6_routing_subject_scope=scope,
    )[0]
    plan = compute_validation_plan(
        interfaces, move_groups=groups, devices=devices,
        ipv6_routing_adjacency_baseline=baseline,
        ipv6_routing_subject_scope=scope,
    )
    nrfu = compute_nrfu_commands({
        "devices": devices,
        "interfaces": interfaces,
        "move_groups": groups,
        "ipv6_routing_adjacency_baseline": baseline,
        "ipv6_routing_subject_scope": scope,
    })
    cases = [
        case
        for wave in nrfu["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "IPv6 Routing"
    ]
    punchlist = compute_migration_punchlist(
        [], {}, {}, [], [], [], {}, [], groups,
        ipv6_routing_adjacency_baseline=baseline,
        ipv6_routing_subject_scope=scope,
    )
    return readiness, plan, nrfu, cases, punchlist


def _ipv6_items(plan: dict) -> list[dict]:
    return [row for row in plan["items"] if row["category"] == "IPv6 Routing"]


def _ipv6_check(readiness: dict) -> dict | None:
    return next(
        (row for row in readiness["checks"]
         if row["check"] == "IPv6 routing adjacencies"),
        None,
    )


def test_exstart_and_active_close_ready_clear_and_zero_nrfu_false_clear(tmp_path):
    baseline, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.9", "EXSTART/-", "GigabitEthernet0/1"),),
        bgp_rows=(("2001:DB8:0:9::9", "65009", "Active"),),
    )
    assert baseline["verdict"] == "BLOCKED"
    assert [(row["protocol"], row["status"]) for row in baseline["rows"]] == [
        ("OSPFv3", "degraded"), ("BGPv6", "degraded"),
    ]
    assert all(row["acceptance"].startswith(
        "PRE-CUTOVER DEGRADED — BLOCKER:") for row in baseline["rows"])

    readiness, plan, nrfu, cases, punchlist = _surfaces(baseline, scope=scope)
    assert readiness["readiness"] == "NOT READY"
    assert _ipv6_check(readiness)["status"] == "fail"
    assert compute_current_baseline_gate(plan)["verdict"] == "BLOCKED"
    assert len(_ipv6_items(plan)) == len(cases) == 2
    assert {case["evidence_state"] for case in cases} == {"degraded"}
    assert nrfu["summary"]["n_ipv6_routing_cases"] == 2
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 2
    ipv6_punch = [row for row in punchlist if row["category"] == "IPv6 Routing"]
    assert len(ipv6_punch) == 2
    assert {row["severity"] for row in ipv6_punch} == {"High"}
    assert all(row["remediation"] == "" for row in ipv6_punch)


@pytest.mark.parametrize("bodies", [
    {
        "show ipv6 route summary": """\
IPv6 Routing Table - default - 8 entries
Codes: C - connected, L - local, O - OSPF intra
C 2001:db8:10::/64 [0/0]
 via Vlan10, directly connected
O 2001:db8:20::/64 [110/20]
 via fe80::1, Vlan10
""",
        "show ospfv3 neighbor": _ospfv3(
            ("10.0.0.1", "FULL/DR", "Vlan10")),
    },
    {
        "show ipv6 route summary": ROUTE_SUMMARY,
        "show bgp ipv6 unicast summary": (
            _bgpv6() + "2001:db8::1 4 65001 0\n"),
    },
    {
        "show ipv6 route summary": ROUTE_SUMMARY,
        "show ospfv3 neighbor": _ospfv3(
            ("10.0.0.1", "FULL/DR", "Vlan10")
        ).replace("00:00:37    16", "garbage garbage"),
    },
])
def test_rejected_parser_denominator_never_reaches_ready_clear_or_zero_blockers(
        bodies, tmp_path):
    baseline, scope = _owner_from_bodies(tmp_path, bodies)
    assert scope["valid"] is False
    assert scope["attempted"] is True
    assert scope["reason"] == "scope_evidence_rejected"
    assert validate_ipv6_routing_adjacency_baseline(baseline)["valid"] is False

    readiness, plan, nrfu, cases, punchlist = _surfaces(
        baseline, scope=scope)
    assert readiness["readiness"] == "CAUTION"
    assert _ipv6_check(readiness)["status"] == "warn"
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert len(_ipv6_items(plan)) == len(cases) == 1
    assert cases[0]["evidence_state"] == "not_verified"
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 1
    assert len([
        row for row in punchlist if row["category"] == "IPv6 Routing"
    ]) == 1


def test_full_2way_and_established_are_bounded_clear(tmp_path):
    baseline, scope = _owner(
        tmp_path,
        ospf_rows=(
            ("10.0.0.1", "FULL/DR", "Vlan10"),
            ("10.0.0.7", "2WAY/DROTHER", "Vlan10"),
        ),
        bgp_rows=(("2001:DB8:0:1::1", "65001", "12"),),
    )
    assert baseline["verdict"] == "CLEAR"
    assert all(row["status"] == "assessed" for row in baseline["rows"])

    readiness, plan, nrfu, cases, punchlist = _surfaces(baseline, scope=scope)
    assert readiness["readiness"] == "READY"
    assert _ipv6_check(readiness)["status"] == "pass"
    assert compute_current_baseline_gate(plan)["verdict"] == "CLEAR"
    assert len(cases) == 3
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 0
    assert [row for row in punchlist if row["category"] == "IPv6 Routing"] == []


def test_unknown_adjacency_state_requires_review_everywhere(tmp_path):
    baseline, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.5", "MYSTERY/DR", "Vlan20"),),
        bgp_rows=(("2001:DB8:0:5::5", "65005", "12"),),
    )
    review = next(row for row in baseline["rows"] if row["protocol"] == "OSPFv3")
    assert review["status"] == "review"
    assert review["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")

    readiness, plan, nrfu, cases, punchlist = _surfaces(baseline, scope=scope)
    assert readiness["readiness"] == "CAUTION"
    assert _ipv6_check(readiness)["status"] == "warn"
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert nrfu["summary"]["ipv6_routing_by_evidence_state"]["review"] == 1
    reviews = [row for row in punchlist if row["category"] == "IPv6 Routing"]
    assert len(reviews) == 1 and reviews[0]["severity"] == "Medium"
    assert next(case for case in cases if case["evidence_state"] == "review")


def test_positive_route_subject_with_missing_runtime_capture_is_not_verified(tmp_path):
    baseline, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.1", "FULL/DR", "Vlan10"),),
        bgp_rows=(),
        include_bgp=False,
    )
    assert scope["valid"] is True
    assert scope["rows"] == [{
        "switch": "sw1", "platform": "ios", "protocols": ["OSPFv3", "BGPv6"],
    }]
    assert any(
        row["protocol"] == "BGPv6" and row["status"] == "not_verified"
        for row in baseline["rows"]
    )

    readiness, plan, nrfu, cases, punchlist = _surfaces(baseline, scope=scope)
    assert readiness["readiness"] == "CAUTION"
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    missing = next(case for case in cases if case["evidence_state"] == "not_verified")
    assert missing["expected"].startswith(
        "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER:")
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "IPv6 Routing"]) == 1


def test_phase_failure_uses_only_exact_valid_subject_scope(tmp_path):
    current, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.1", "FULL/DR", "Vlan10"),),
        bgp_rows=(("2001:DB8:0:1::1", "65001", "12"),),
    )
    assert scope["valid"] is True and scope["attempted"] is True

    for rejected in ({}, embedded_ipv6_routing_adjacency_baseline(current)):
        readiness, plan, nrfu, cases, punchlist = _surfaces(rejected, scope=scope)
        assert readiness["readiness"] == "CAUTION"
        assert _ipv6_check(readiness)["status"] == "warn"
        assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
        assert len(_ipv6_items(plan)) == len(cases) == 2
        assert {case["evidence_state"] for case in cases} == {"not_verified"}
        assert all(case["expected"].startswith(
            "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER:") for case in cases)
        assert nrfu["summary"]["n_ipv6_routing_blockers"] == 2
        assert len([row for row in punchlist if row["category"] == "IPv6 Routing"]) == 2


def test_valid_no_subject_is_neutral_on_every_surface():
    paths = {}
    baseline = compute_ipv6_routing_adjacency_baseline(
        paths, compute_capture_integrity_from_paths(paths),
        devices={"sw1": {"platform": "ios"}},
    )
    scope = compute_ipv6_routing_subject_scope(
        paths, devices={"sw1": {"platform": "ios"}},
    )
    assert baseline["verdict"] == "NOT_APPLICABLE"
    assert scope == {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True, "attempted": False, "reason": "ok", "rows": [],
    }

    readiness, plan, nrfu, cases, punchlist = _surfaces(baseline, scope=scope)
    assert readiness["readiness"] == "READY"
    assert _ipv6_check(readiness) is None
    assert _ipv6_items(plan) == []
    # With no validation subjects of any category, the shared gate correctly
    # abstains; IPv6 contributes no blocker and never manufactures an all-clear.
    assert compute_current_baseline_gate(plan)["verdict"] == "NOT_ASSESSED"
    assert cases == []
    assert nrfu["summary"]["n_ipv6_routing_cases"] == 0
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 0
    assert [row for row in punchlist if row["category"] == "IPv6 Routing"] == []


def test_valid_attempted_but_no_positive_subject_is_also_neutral():
    scope = {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True,
        "attempted": True,
        "reason": "ok",
        "rows": [],
    }
    readiness, plan, nrfu, cases, punchlist = _surfaces({}, scope=scope)
    assert readiness["readiness"] == "READY"
    assert _ipv6_check(readiness) is None
    assert _ipv6_items(plan) == []
    assert cases == []
    assert nrfu["summary"]["n_ipv6_routing_cases"] == 0
    assert [row for row in punchlist if row["category"] == "IPv6 Routing"] == []


def test_validation_nrfu_and_owner_share_common_fields_and_custody(tmp_path):
    baseline, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.1", "FULL/DR", "Vlan10"),),
        bgp_rows=(("2001:DB8:0:1::1", "65001", "12"),),
    )
    _, plan, nrfu, cases, _ = _surfaces(baseline, scope=scope)
    validation = _ipv6_items(plan)
    assert len(validation) == len(cases) == len(baseline["rows"])
    common_validation_keys = {
        "device", "platform", "wave", "category", "severity", "check",
        "command", "expect", "why", "evidence_state", "projection_custody",
        "source_key",
    }
    assert all(set(row) == common_validation_keys for row in validation)

    for owner in baseline["rows"]:
        row = next(item for item in validation if item["expect"] == owner["acceptance"])
        case = next(item for item in cases if item["expected"] == owner["acceptance"])
        assert row["command"] == case["command"] == owner["command"]
        assert row["source_key"] == case["source_key"] == owner["source_key"]
        assert row["evidence_state"] == case["evidence_state"] == owner["status"]
        assert row["projection_custody"] == case["projection_custody"] == (
            owner["projection_custody"]
        )
        assert owner["peer"] in row["check"]
        assert owner["state_raw"] in row["check"]
        assert owner["peer"] in row["expect"]
        assert owner["state_raw"] in row["expect"]

    assert nrfu["summary"]["ipv6_routing_by_projection_custody"] == {
        "current_run_source_bound": len(cases),
    }
    projected = json.dumps([validation, cases])
    assert str(tmp_path) not in projected
    assert "source_sha256" not in projected
    assert "projection_sha256" not in projected


@pytest.mark.parametrize("scope", [
    None,
    [],
    {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True,
        "attempted": False,
        "reason": "ok",
        "rows": [],
        "extra": "HOSTILE-SCOPE-LEAF",
    },
    {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": False,
        "attempted": True,
        "reason": "scope_identity_collision",
        "rows": [],
    },
    {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": False,
        "attempted": False,
        "reason": "scope_evidence_rejected",
        "rows": [],
    },
    {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True,
        "attempted": True,
        "reason": "ok",
        "rows": [{
            "switch": "safe\u202eexe", "platform": "ios",
            "protocols": ["OSPFv3"],
        }],
    },
    {
        "schema": IPV6_ROUTING_SUBJECT_SCOPE_SCHEMA,
        "valid": True,
        "attempted": True,
        "reason": "ok",
        "rows": [
            {"switch": f"host-{index}", "platform": "ios", "protocols": ["OSPFv3"]}
            for index in range(4097)
        ],
    },
])
def test_rejected_or_hostile_scope_yields_one_static_global_blocker_without_echo(scope):
    hostile = {
        "schema": "ipv6_routing_adjacency_baseline/1",
        "rows": [{
            "switch": "HOSTILE-DEVICE", "peer": "HOSTILE-PEER",
            "state_raw": "FULL", "acceptance": "HOSTILE-HEALTHY-TARGET",
        }],
    }
    readiness, plan, nrfu, cases, punchlist = _surfaces(hostile, scope=scope)
    validation = _ipv6_items(plan)
    assert readiness["readiness"] == "CAUTION"
    assert len(validation) == len(cases) == 1
    assert validation[0]["device"] == "(IPv6 routing subject scope not verified)"
    assert validation[0]["evidence_state"] == cases[0]["evidence_state"] == "not_verified"
    assert validation[0]["expect"].startswith(
        "IPV6 ROUTING BASELINE NOT VERIFIED — BLOCKER:")
    assert compute_current_baseline_gate(plan)["verdict"] == "INDETERMINATE"
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 1
    assert len([row for row in punchlist if row["category"] == "IPv6 Routing"]) == 1
    rendered = json.dumps([readiness, plan, nrfu, punchlist])
    for hostile_leaf in (
            "HOSTILE-DEVICE", "HOSTILE-PEER", "HOSTILE-HEALTHY-TARGET",
            "HOSTILE-SCOPE-LEAF", "host-4096", "safe\u202eexe"):
        assert hostile_leaf not in rendered


def test_readiness_note_is_bounded_but_validation_and_nrfu_keep_every_blocker(tmp_path):
    ospf_rows = tuple(
        (f"10.0.0.{index}", "EXSTART/-", f"Vlan{index}")
        for index in range(1, 13)
    )
    baseline, scope = _owner(tmp_path, ospf_rows=ospf_rows, bgp_rows=())

    readiness, plan, nrfu, cases, _punchlist = _surfaces(baseline, scope=scope)
    note = _ipv6_check(readiness)["note"]
    assert readiness["readiness"] == "NOT READY"
    assert "+4 additional blocker row(s) retained in Cutover Validation and NRFU" in note
    assert "additionally, 1 REVIEW/NOT VERIFIED blocker row(s)" in note
    assert len(note) < 1_000
    # The route census also declares BGPv6, so its absent runtime row remains a
    # thirteenth NOT VERIFIED blocker even though the readiness headline leads
    # with the twelve definite OSPFv3 faults.
    assert len(_ipv6_items(plan)) == len(cases) == 13
    assert nrfu["summary"]["n_ipv6_routing_blockers"] == 13


def test_tampered_embedded_receipt_cannot_echo_owner_leaves(tmp_path):
    current, scope = _owner(
        tmp_path,
        ospf_rows=(("10.0.0.1", "FULL/DR", "Vlan10"),),
        bgp_rows=(("2001:DB8:0:1::1", "65001", "12"),),
    )
    tampered = deepcopy(embedded_ipv6_routing_adjacency_baseline(current))
    tampered["rows"][0]["acceptance"] = "HOSTILE-HEALTHY-TARGET"
    assert validate_ipv6_routing_adjacency_baseline(tampered)["valid"] is False

    surfaces = _surfaces(tampered, scope=scope)
    rendered = json.dumps(surfaces, default=str)
    assert "HOSTILE-HEALTHY-TARGET" not in rendered
    assert "show_ospfv3_neighbor.txt" not in rendered
    assert all(case["evidence_state"] == "not_verified" for case in surfaces[3])
