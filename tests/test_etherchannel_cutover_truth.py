"""Receipt-gated EtherChannel projection and cutover-baseline counterexamples."""

from __future__ import annotations

import copy
import json

import pytest

from cisco_toolkit.analyze import (
    PROTOCOL_ASSESSABILITY_FAMILIES,
    PROTOCOL_ASSESSABILITY_STATES,
    _extract_protocol_states,
    compute_etherchannel_projection,
    compute_protocol_health,
    compute_validation_plan,
    summarize_etherchannel_baseline,
    summarize_routing_baseline,
    validate_etherchannel_baseline,
)
from cisco_toolkit.model import InterfaceData


FAMILIES = tuple(family["protocol"] for family in PROTOCOL_ASSESSABILITY_FAMILIES)
INPUTS = {
    family["protocol"]: tuple(item["id"] for item in family["inputs"])
    for family in PROTOCOL_ASSESSABILITY_FAMILIES
}


def _capture(tmp_path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _receipt(host_states):
    rows = []
    by_state = {state: 0 for state in PROTOCOL_ASSESSABILITY_STATES}
    for host in sorted(host_states):
        states = host_states[host]
        for protocol in FAMILIES:
            state = states.get(protocol, "not_collected")
            capture = {
                "assessed": "usable",
                "partial": "missing",
                "captured_no_record": "usable",
                "captured_empty": "empty",
                "capture_error": "error",
                "not_collected": "missing",
                "analysis_unavailable": "missing",
            }[state]
            emitted = state in ("assessed", "partial")
            rows.append({
                "switch": host,
                "protocol": protocol,
                "input_states": {name: capture for name in INPUTS[protocol]},
                "capture_state": capture,
                "health_row_emitted": emitted,
                "state": state,
                "reason": f"fixture: {state}",
            })
            by_state[state] += 1
    complete = sum(
        all(host_states[host].get(protocol, "not_collected") == "assessed"
            for protocol in FAMILIES)
        for host in host_states
    )
    return {
        "schema": "protocol_assessability/1",
        "families": [{"protocol": protocol} for protocol in FAMILIES],
        "rows": rows,
        "summary": {
            "n_devices": len(host_states),
            "n_families": len(FAMILIES),
            "n_cells": len(rows),
            "n_health_rows": sum(row["health_row_emitted"] for row in rows),
            "n_complete_devices": complete,
            "by_state": by_state,
        },
        "limitations": ["fixture receipt"],
    }


def _project(tmp_path, host: str, body: str, *, command="show etherchannel summary", ifaces=None):
    path = _capture(tmp_path, host.replace("/", "-") + ".txt", body)
    all_interfaces = {host: ifaces or {}}
    command_files = {host: {command: path}}
    return compute_etherchannel_projection(all_interfaces, command_files), all_interfaces, command_files


IOS_HEALTHY = """\
Flags: D - down P - bundled in port-channel H - hot-standby
Number of channel-groups in use: 1
Group  Port-channel  Protocol    Ports
1      Po1(SU)        LACP        Gi1/0/1(P) Gi1/0/2(H)
"""


def test_healthy_p_and_hot_standby_are_exact_assessed_states_and_json_ready(tmp_path):
    ifaces = {
        "Gi1/0/1": InterfaceData(port="Gi1/0/1", port_channel="Po01"),
        "Gi1/0/2": {"port": "Gi1/0/2", "port_channel": "Port-channel1"},
        # build_interfaces represents the logical bundle with this self-reference. It is not a
        # physical association and must not turn a healthy group into REVIEW.
        "Po1": InterfaceData(port="Po1", port_channel="Po1", port_channel_protocol="Active"),
    }
    projection, all_interfaces, command_files = _project(
        tmp_path, "dist1", IOS_HEALTHY, ifaces=ifaces
    )
    row = projection["rows"][0]
    group = row["groups"][0]

    json.dumps(projection, sort_keys=True)
    assert projection["schema"] == "etherchannel_projection/1"
    assert row["source_command"] == "show etherchannel summary"
    assert (group["group_id"], group["group"], group["group_flags"], group["protocol"]) == (
        "1", "Po1", "SU", "LACP"
    )
    assert [(item["interface"], item["flags"], item["state"], item["status"])
            for item in group["members"]] == [
        ("Gi1/0/1", "P", "forwarding_observed", "assessed"),
        ("Gi1/0/2", "H", "hot_standby", "assessed"),
    ]
    assert row["associations"] == [
        {"interface": "Gi1/0/1", "group": "Po1"},
        {"interface": "Gi1/0/2", "group": "Po1"},
    ]
    assert row["findings"] == []

    health = compute_protocol_health(
        all_interfaces, command_files, etherchannel_projection=projection
    )
    ec = next(item for item in health if item["protocol"] == "EtherChannel")
    assert ec["severity"] == "Info" and "Gi1/0/2(H)" in ec["detail"]
    assert "H" in _extract_protocol_states("EtherChannel", ec["summary"], ec["detail"])

    baseline = summarize_etherchannel_baseline(
        projection, _receipt({"dist1": {"EtherChannel": "assessed"}})
    )
    json.dumps(baseline, sort_keys=True)
    assert baseline["schema"] == "etherchannel_baseline/1"
    assert baseline["status"] == "assessed" and baseline["assessed"] is True
    result = baseline["rows"][0]
    assert result["status"] == "assessed"
    assert "Gi1/0/1(P) forwarding observed" in result["baseline"]
    assert "Gi1/0/2(H) hot standby" in result["baseline"]
    assert result["command"] == "show etherchannel summary"
    assert result["projection_custody"] == "embedded_unverified"
    assert result["source_key"] == (
        "etherchannel_projection.rows[dist1] + "
        "protocol_assessability.rows[dist1,EtherChannel]"
    )
    assert "configured-member or partner denominator was inferred" in result["acceptance"]


def test_nxos_delay_lacp_p_is_forwarding_and_whitespace_before_flags_is_accepted(tmp_path):
    body = """\
Flags: P - Up in port-channel p - Up in delay-LACP mode H - Hot-standby
Group Port-       Type     Protocol  Member Ports
      Channel
2     Po2(RU)     Eth      LACP      Eth1/1(P) Eth1/2 (p) Eth1/3(H)
"""
    projection, all_interfaces, command_files = _project(
        tmp_path, "nx1", body, command="show port-channel summary"
    )
    group = projection["rows"][0]["groups"][0]
    assert [(item["interface"], item["flags"], item["state"])
            for item in group["members"]] == [
        ("Eth1/1", "P", "forwarding_observed"),
        ("Eth1/2", "p", "delay_lacp_up"),
        ("Eth1/3", "H", "hot_standby"),
    ]
    health = next(item for item in compute_protocol_health(
        all_interfaces, command_files, projection
    ) if item["protocol"] == "EtherChannel")
    assert health["severity"] == "Info"
    assert {"H", "p"} <= set(_extract_protocol_states(
        "EtherChannel", health["summary"], health["detail"]
    ))
    result = summarize_etherchannel_baseline(
        projection, _receipt({"nx1": {"EtherChannel": "assessed"}}),
        devices={"nx1": {"platform": "nxos"}},
    )["rows"][0]
    assert result["command"] == "show port-channel summary"
    assert "Eth1/2(p) forwarding observed (delay-LACP)" in result["baseline"]


@pytest.mark.parametrize(
    ("group_flags", "member_flags"),
    [
        ("SD", None), ("SM", "P"), ("SN", "P"),
        ("SU", "D"), ("SU", "s"), ("SU", "I"), ("SU", "f"),
        ("SU", "M"), ("SU", "m"), ("SU", "u"), ("SU", "r"),
        ("SU", "RM"),
    ],
)
def test_supported_group_and_member_fault_flags_are_definite_degraded_blockers(
        tmp_path, group_flags, member_flags):
    members = "--" if member_flags is None else f"Gi1/0/1({member_flags})"
    body = f"Group Port-channel Protocol Ports\n1 Po1({group_flags}) LACP {members}\n"
    projection, all_interfaces, command_files = _project(
        tmp_path, f"sw-{group_flags}-{member_flags}", body
    )
    group = projection["rows"][0]["groups"][0]
    assert group["status"] == "degraded"
    health = next(item for item in compute_protocol_health(
        all_interfaces, command_files, projection
    ) if item["protocol"] == "EtherChannel")
    assert health["severity"] == "High"
    result = summarize_etherchannel_baseline(
        projection,
        _receipt({f"sw-{group_flags}-{member_flags}": {"EtherChannel": "assessed"}}),
    )["rows"][0]
    assert result["status"] == "degraded"
    assert result["acceptance"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "NOT ACCEPTANCE" in result["acceptance"]


@pytest.mark.parametrize("flag", ["w", "b", "d", "X"])
def test_waiting_bfd_wait_platform_delay_and_unknown_tokens_are_review_not_faults(tmp_path, flag):
    body = f"Group Port-channel Protocol Ports\n1 Po1(SU) LACP Gi1/0/1({flag})\n"
    projection, all_interfaces, command_files = _project(tmp_path, f"wait-{flag}", body)
    member = projection["rows"][0]["groups"][0]["members"][0]
    assert member["status"] == "review"
    health = next(item for item in compute_protocol_health(
        all_interfaces, command_files, projection
    ) if item["protocol"] == "EtherChannel")
    assert health["severity"] == "Medium"
    result = summarize_etherchannel_baseline(
        projection, _receipt({f"wait-{flag}": {"EtherChannel": "assessed"}})
    )["rows"][0]
    assert result["status"] == "review"
    assert result["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")
    assert not any(item["kind"] == "degraded" for item in result["findings"])


@pytest.mark.parametrize("as_dict", [False, True])
def test_config_or_trunk_only_association_is_not_verified_subject_never_operational_state(
        as_dict):
    leaf = ({"port": "Gi1/0/1", "port_channel": "Po1"} if as_dict else
            InterfaceData(port="Gi1/0/1", port_channel="Po1"))
    projection = compute_etherchannel_projection({"access1": {"Gi1/0/1": leaf}}, {"access1": {}})
    result = summarize_etherchannel_baseline(
        projection, _receipt({"access1": {"EtherChannel": "not_collected"}})
    )["rows"][0]

    assert result["status"] == "not_verified"
    assert result["group_count"] == 0 and result["member_count"] == 0
    assert result["associations"] == [{"interface": "Gi1/0/1", "group": "Po1"}]
    assert "association-only evidence" in result["baseline"]
    assert "no operational member state is asserted" in result["baseline"]
    assert result["acceptance"].startswith("ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:")


def test_clean_empty_nonassessed_cell_is_omitted_for_pure_l2_device(tmp_path):
    empty = _capture(tmp_path, "empty.txt", "\n")
    projection = compute_etherchannel_projection(
        {"access1": {"Gi1/0/1": InterfaceData(port="Gi1/0/1")}},
        {"access1": {"show etherchannel summary": empty}},
    )
    baseline = summarize_etherchannel_baseline(
        projection, _receipt({"access1": {"EtherChannel": "captured_empty"}})
    )

    assert projection["rows"][0]["capture_state"] == "empty"
    assert baseline["rows"] == []
    assert baseline["status"] == "not_verified" and baseline["assessed"] is False


def test_duplicate_aliases_count_mismatch_and_malformed_rows_fail_closed_as_review(tmp_path):
    duplicate = """\
Number of channel-groups in use: 3
Group Port-channel Protocol Ports
1 Po1(SU) LACP Gi1/0/1(P)
2 Po2(SU) LACP Gi01/00/01(P)
3 Po3 LACP Gi1/0/3(P)
"""
    projection, all_interfaces, command_files = _project(tmp_path, "dup1", duplicate)
    row = projection["rows"][0]
    codes = {item["code"] for item in row["findings"]}
    assert {"duplicate_member_identity", "group_row_malformed", "declared_group_count_mismatch"} <= codes
    assert row["rejected_line_count"] >= 2
    assert projection["summary"]["n_members"] == 1
    health = next(item for item in compute_protocol_health(
        all_interfaces, command_files, projection
    ) if item["protocol"] == "EtherChannel")
    assert health["severity"] == "Medium"
    result = summarize_etherchannel_baseline(
        projection, _receipt({"dup1": {"EtherChannel": "assessed"}})
    )["rows"][0]
    assert result["status"] == "review"
    assert result["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")


def test_stripped_duplicate_group_finding_cannot_promote_rejected_raw_row_to_assessed(tmp_path):
    duplicate = """\
Group Port-channel Protocol Ports
1 Po1(SU) LACP Gi1/0/1(P)
1 Po1(SU) LACP Gi1/0/2(P)
"""
    projection, _all_interfaces, _command_files = _project(tmp_path, "dup1", duplicate)
    receipt = _receipt({"dup1": {"EtherChannel": "assessed"}})
    row = projection["rows"][0]
    assert row["rejected_line_count"] == 1
    assert {item["code"] for item in row["findings"]} == {"duplicate_group_identity"}
    assert summarize_etherchannel_baseline(projection, receipt)["rows"][0]["status"] == "review"

    stripped = copy.deepcopy(projection)
    stripped["rows"][0]["findings"] = []
    recomputed = summarize_etherchannel_baseline(stripped, receipt)
    assert recomputed["projection"]["valid"] is False
    assert recomputed["rows"][0]["status"] == "review"
    assert recomputed["rows"][0]["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")

    healthy_projection, _ifaces, _commands = _project(
        tmp_path, "dup1", "Group Port-channel Protocol Ports\n1 Po1(SU) LACP Gi1/0/1(P)\n"
    )
    forged_assessed = summarize_etherchannel_baseline(healthy_projection, receipt)
    rejected = validate_etherchannel_baseline(
        forged_assessed, projection=stripped, protocol_assessability=receipt
    )
    assert rejected["valid"] is False and rejected["rows"] == [] and rejected["index"] == {}


def test_malformed_interface_and_command_leaves_are_visible_review_subjects():
    projection = compute_etherchannel_projection(
        {"sw1": {"Gi1/0/1": {"port_channel": ["Po1"]}}, "sw2": [],
         "sw3": {"Gi1/0/1": 7}},
        {"sw1": 7, "sw2": {}, "sw3": {}},
    )
    by_host = {row["switch"]: row for row in projection["rows"]}
    assert {item["code"] for item in by_host["sw1"]["findings"]} == {
        "association_identity_malformed", "command_projection_malformed"
    }
    assert {item["code"] for item in by_host["sw2"]["findings"]} == {
        "association_projection_malformed"
    }
    assert {item["code"] for item in by_host["sw3"]["findings"]} == {
        "association_projection_malformed"
    }
    baseline = summarize_etherchannel_baseline(
        projection,
        _receipt({"sw1": {"EtherChannel": "not_collected"},
                  "sw2": {"EtherChannel": "not_collected"},
                  "sw3": {"EtherChannel": "not_collected"}}),
    )
    assert {row["status"] for row in baseline["rows"]} == {"review"}


def test_structurally_mutated_projection_and_receipt_reconciliation_fail_closed(tmp_path):
    projection, _all_interfaces, _command_files = _project(tmp_path, "dist1", IOS_HEALTHY)
    bad_projection = copy.deepcopy(projection)
    bad_projection["rows"][0]["groups"][0]["members"] = "not-a-list"
    receipt = _receipt({"dist1": {"EtherChannel": "assessed"}})
    baseline = summarize_etherchannel_baseline(bad_projection, receipt)
    assert baseline["projection"]["valid"] is False
    assert baseline["rows"][0]["status"] == "review"
    assert "projection_invalid" in {item["code"] for item in baseline["rows"][0]["findings"]}

    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["summary"]["n_health_rows"] = 99
    baseline = summarize_etherchannel_baseline(projection, bad_receipt)
    assert baseline["receipt"]["valid"] is False
    assert baseline["rows"][0]["status"] == "review"
    # The routing consumer shares the exact validator and fails closed on the same receipt mutation.
    routing = summarize_routing_baseline(
        {"dist1": {"ospf": [{
            "neighbor": "10.0.0.2", "state": "FULL/DR", "address": "10.0.0.2", "interface": "Po1"
        }]}},
        bad_receipt,
    )
    assert routing["receipt"]["valid"] is False
    assert routing["rows"][0]["status"] == "review"


def test_stripped_classifier_findings_cannot_turn_a_down_member_into_assessed(tmp_path):
    projection, _all_interfaces, _command_files = _project(
        tmp_path, "dist1", "Group Port-channel Protocol Ports\n1 Po1(SD) LACP Gi1/0/1(D)\n"
    )
    mutated = copy.deepcopy(projection)
    group = mutated["rows"][0]["groups"][0]
    group["findings"] = []
    group["members"][0]["findings"] = []

    baseline = summarize_etherchannel_baseline(
        mutated, _receipt({"dist1": {"EtherChannel": "assessed"}})
    )
    assert baseline["projection"]["valid"] is False
    assert baseline["rows"][0]["status"] == "review"
    assert baseline["rows"][0]["acceptance"].startswith("PRE-CUTOVER REVIEW — BLOCKER:")


def test_rejected_malformed_member_identity_round_trips_as_exact_nested_review(tmp_path):
    projection, _all_interfaces, _command_files = _project(
        tmp_path, "dist1", "Group Port-channel Protocol Ports\n1 Po1(SU) LACP Vlan1/1(P)\n"
    )
    receipt = _receipt({"dist1": {"EtherChannel": "assessed"}})
    group = projection["rows"][0]["groups"][0]
    assert projection["rows"][0]["rejected_line_count"] == 1
    assert group["members"] == []
    assert {item["code"] for item in group["findings"]} == {
        "member_identity_malformed", "up_group_without_members"
    }

    baseline = summarize_etherchannel_baseline(projection, receipt)
    row = baseline["rows"][0]
    assert baseline["projection"]["valid"] is True
    assert row["status"] == "review" and row["group_count"] == 1 and row["member_count"] == 0
    assert row["rejected_line_count"] == 1
    assert "Member identity Vlan1/1 is outside the bounded physical-interface grammar." in row["issue"]
    assert validate_etherchannel_baseline(
        baseline, projection=projection, protocol_assessability=receipt
    )["valid"] is True

    stripped = copy.deepcopy(projection)
    stripped["rows"][0]["groups"][0]["findings"] = [
        item for item in group["findings"] if item["code"] != "member_identity_malformed"
    ]
    assert summarize_etherchannel_baseline(stripped, receipt)["projection"]["valid"] is False


def test_unclassified_protocol_round_trips_only_with_exact_owned_review_finding(tmp_path):
    projection, _all_interfaces, _command_files = _project(
        tmp_path, "dist1", "Group Port-channel Protocol Ports\n1 Po1(SU) STATIC Gi1/0/1(P)\n"
    )
    receipt = _receipt({"dist1": {"EtherChannel": "assessed"}})
    group = projection["rows"][0]["groups"][0]
    assert group["protocol"] == group["protocol_raw"] == ""
    assert group["members"][0]["flags"] == "P"
    assert group["findings"] == [{
        "kind": "review", "code": "protocol_unclassified",
        "issue": "No bounded aggregation protocol token was parsed for Po1.",
    }]

    baseline = summarize_etherchannel_baseline(projection, receipt)
    row = baseline["rows"][0]
    assert baseline["projection"]["valid"] is True and row["status"] == "review"
    assert "Gi1/0/1(P) forwarding observed" in row["baseline"]
    assert validate_etherchannel_baseline(
        baseline, projection=projection, protocol_assessability=receipt
    )["valid"] is True

    stripped = copy.deepcopy(projection)
    stripped["rows"][0]["groups"][0]["findings"] = []
    assert summarize_etherchannel_baseline(stripped, receipt)["projection"]["valid"] is False


def test_baseline_validator_source_reconciles_and_withholds_forged_rows(tmp_path):
    projection, _all_interfaces, _command_files = _project(tmp_path, "dist1", IOS_HEALTHY)
    receipt = _receipt({"dist1": {"EtherChannel": "assessed"}})
    baseline = summarize_etherchannel_baseline(projection, receipt)

    valid = validate_etherchannel_baseline(
        baseline, projection=projection, protocol_assessability=receipt
    )
    assert valid["valid"] is True and valid["source_bound"] is True
    assert valid["rows"] == baseline["rows"] and set(valid["index"]) == {"dist1"}

    forged = copy.deepcopy(baseline)
    forged["rows"][0]["groups"][0]["group_flags"] = "SD"
    forged["rows"][0]["groups"][0]["members"][0]["flags"] = "D"
    forged["rows"][0]["acceptance"] = "All members forwarding"
    rejected = validate_etherchannel_baseline(
        forged, projection=projection, protocol_assessability=receipt
    )
    assert rejected["valid"] is False and rejected["source_bound"] is False
    assert rejected["rows"] == [] and rejected["index"] == {}
    assert validate_etherchannel_baseline(baseline)["valid"] is False
    assert validate_etherchannel_baseline(baseline, projection=projection)["valid"] is False


def test_validation_recomputes_forged_baseline_from_supplied_down_source_without_interface_po(tmp_path):
    projection, _all_interfaces, _command_files = _project(
        tmp_path, "dist1", "Group Port-channel Protocol Ports\n1 Po1(SD) LACP Gi1/0/1(D)\n"
    )
    receipt = _receipt({"dist1": {"EtherChannel": "assessed"}})
    degraded = summarize_etherchannel_baseline(projection, receipt)
    assert degraded["rows"][0]["status"] == "degraded"
    forged = copy.deepcopy(degraded)
    forged["rows"][0]["status"] = "assessed"
    forged["rows"][0]["acceptance"] = "HOSTILE FALSE HEALTH: all members forwarding"

    plan = compute_validation_plan(
        {"dist1": {}},
        protocol_assessability=receipt,
        etherchannel_projection=projection,
        etherchannel_baseline=forged,
    )
    item = next(row for row in plan["items"] if row["category"] == "Link")
    assert item["device"] == "dist1"
    assert item["evidence_state"] == "degraded"
    assert item["check"] == "Port-channel degraded group/member baseline"
    assert item["expect"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert "Po1 group 1(SD)" in item["expect"] and "Gi1/0/1(D)" in item["expect"]
    assert "HOSTILE FALSE HEALTH" not in item["expect"]


@pytest.mark.parametrize("projection, receipt", [(None, None), (7, "bad"), ([], {}), ({}, 7)])
def test_baseline_is_total_and_json_ready_on_malformed_roots(projection, receipt):
    result = summarize_etherchannel_baseline(projection, receipt)
    assert isinstance(result, dict) and isinstance(result["rows"], list)
    json.dumps(result, sort_keys=True)


def test_precomputed_health_projection_is_reused_and_invalid_projection_falls_back(tmp_path):
    projection, all_interfaces, command_files = _project(tmp_path, "dist1", IOS_HEALTHY)
    before = copy.deepcopy(projection)
    direct = compute_protocol_health(all_interfaces, command_files)
    reused = compute_protocol_health(all_interfaces, command_files, projection)
    assert direct == reused
    assert projection == before

    invalid = copy.deepcopy(projection)
    invalid["summary"]["n_groups"] = 99
    assert compute_protocol_health(all_interfaces, command_files, invalid) == direct
