"""NRFU consumes the receipt-gated EtherChannel baseline without inventing ``(P)`` state."""

from __future__ import annotations

import copy
import os

from cisco_toolkit.analyze import (
    compute_etherchannel_projection,
    compute_protocol_assessability,
    compute_protocol_health,
    summarize_etherchannel_baseline,
)
from cisco_toolkit.nrfu_export import compute_nrfu_commands, write_nrfu_pack


def _row(host: str, *, status: str = "assessed", command: str = "show etherchannel summary",
         acceptance: str | None = None) -> dict:
    if acceptance is None:
        acceptance = (
            f"Observed EtherChannel baseline on {host}: Po1 members Gi1/0/1(P), Gi1/0/2(H). "
            "Preserve or explain every observed member identity/state change; H is hot-standby and "
            "must not be rewritten as (P)."
        )
    return {
        "switch": host,
        "status": status,
        "receipt_state": "assessed",
        "capture_state": "usable",
        "health_row_emitted": True,
        "group_count": 1,
        "member_count": 2,
        "groups": [{
            "group_id": "1", "group": "Po1", "group_flags": "SU", "protocol": "LACP",
            "status": status,
            "members": [
                {"interface": "Gi1/0/1", "flags": "P", "status": "assessed", "state": "bundled"},
                {"interface": "Gi1/0/2", "flags": "H", "status": "assessed", "state": "hot_standby"},
            ],
            "findings": [],
        }],
        "associations": [
            {"interface": "Gi1/0/1", "group": "Po1"},
            {"interface": "Gi1/0/2", "group": "Po1"},
        ],
        "findings": [],
        "command": command,
        "baseline": f"Observed EtherChannel baseline on {host}",
        "acceptance": acceptance,
        "issue": "",
        "note": "Bounded observed member-state baseline.",
        "source_key": (
            f"etherchannel_projection.rows[{host}] + "
            f"protocol_assessability.rows[{host},EtherChannel]"
        ),
        "projection_custody": "embedded_unverified",
    }


def _baseline(*rows: dict) -> dict:
    by_status = {
        state: sum(row["status"] == state for row in rows)
        for state in ("assessed", "degraded", "review", "not_verified")
    }
    overall = next(
        (state for state in ("degraded", "review", "not_verified") if by_status[state]),
        "assessed",
    )
    return {
        "schema": "etherchannel_baseline/1",
        "scope": "baseline_observed",
        "status": overall,
        "assessed": all(row["status"] in ("assessed", "degraded") for row in rows),
        "projection_custody": "embedded_unverified",
        "rows": list(rows),
        "summary": {"n_subject_cells": len(rows), "by_status": by_status},
        "limitations": ["fixture"],
    }


def _etherchannel_cases(output: dict) -> dict[str, dict]:
    return {
        device["host"]: case
        for wave in output["waves"]
        for device in wave["devices"]
        for case in device["cases"]
        if case.get("evidence_family") == "EtherChannel"
    }


def _owner_evidence(tmp_path, specs: dict[str, tuple[str, str, str]]) -> dict:
    devices = {host: {"platform": platform}
               for host, (platform, _command, _body) in specs.items()}
    interfaces = {host: {} for host in specs}
    command_files = {}
    for host, (_platform, command, body) in specs.items():
        capture = tmp_path / f"{host}_etherchannel.txt"
        capture.write_text(body, encoding="utf-8")
        command_files[host] = {command: str(capture)}
    health = compute_protocol_health(interfaces, command_files)
    receipt = compute_protocol_assessability(
        list(specs), interfaces, command_files, health,
    )
    projection = compute_etherchannel_projection(interfaces, command_files)
    baseline = summarize_etherchannel_baseline(projection, receipt, devices)
    return {
        "devices": devices,
        "interfaces": interfaces,
        "protocol_assessability": receipt,
        "etherchannel_projection": projection,
        "etherchannel_baseline": baseline,
    }


def test_prepublished_baseline_is_projected_verbatim_with_blocker_and_custody(tmp_path) -> None:
    snap = _owner_evidence(tmp_path, {
        "ios1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SU)       LACP        Gi1/0/1(P) Gi1/0/2(H)\n",
        ),
        "nx1": (
            "nxos", "show port-channel summary",
            "Group Port-Channel Type Protocol Member Ports\n"
            "9     Po9(SD)     Eth  LACP     Eth1/9(D)\n",
        ),
    })
    snap["move_groups"] = [{"switches": ["ios1", "nx1"]}]
    owner_rows = {row["switch"]: row for row in snap["etherchannel_baseline"]["rows"]}

    output = compute_nrfu_commands(snap)
    cases = _etherchannel_cases(output)

    assert cases["ios1"]["expected"] == owner_rows["ios1"]["acceptance"]
    assert "Gi1/0/2(H)" in cases["ios1"]["expected"]
    assert "all members" not in cases["ios1"]["expected"].lower()
    assert cases["nx1"]["expected"] == owner_rows["nx1"]["acceptance"]
    assert cases["nx1"]["expected"].startswith("PRE-CUTOVER DEGRADED — BLOCKER:")
    assert cases["nx1"]["command"] == "show port-channel summary"
    assert cases["nx1"]["evidence_state"] == "degraded"
    assert all(case["evidence_family"] == "EtherChannel" for case in cases.values())
    assert all(case["projection_custody"] == "embedded_unverified" for case in cases.values())
    assert cases["ios1"]["source_key"] == owner_rows["ios1"]["source_key"]

    summary = output["summary"]
    assert summary["n_etherchannel_cases"] == 2
    assert summary["n_etherchannel_blockers"] == 1
    assert summary["etherchannel_by_evidence_state"] == {"assessed": 1, "degraded": 1}
    assert summary["etherchannel_by_projection_custody"] == {"embedded_unverified": 2}
    assert summary["n_routing_cases"] == 0


def test_real_owner_baseline_flows_through_nrfu_without_member_reclassification(tmp_path) -> None:
    capture = tmp_path / "show_etherchannel_summary.txt"
    capture.write_text(
        "Group  Port-channel  Protocol    Ports\n"
        "------+-------------+-----------+-----------------------------------------------\n"
        "1      Po1(SU)       LACP        Gi1/0/1(P)    Gi1/0/2(H)\n",
        encoding="utf-8",
    )
    interfaces = {"sw1": {}}
    command_files = {"sw1": {"show etherchannel summary": str(capture)}}
    health = compute_protocol_health(interfaces, command_files)
    receipt = compute_protocol_assessability(
        ["sw1"], interfaces, command_files, health,
    )
    projection = compute_etherchannel_projection(interfaces, command_files)
    baseline = summarize_etherchannel_baseline(
        projection, receipt, {"sw1": {"platform": "ios"}},
    )

    assert baseline["status"] == "assessed"
    assert len(baseline["rows"]) == 1
    owner_row = baseline["rows"][0]
    assert "Gi1/0/1(P) forwarding observed" in owner_row["acceptance"]
    assert "Gi1/0/2(H) hot standby" in owner_row["acceptance"]

    cases = _etherchannel_cases(compute_nrfu_commands({
        "devices": {"sw1": {"platform": "ios"}},
        "interfaces": interfaces,
        "protocol_assessability": receipt,
        "etherchannel_projection": projection,
        "etherchannel_baseline": baseline,
    }))

    assert cases["sw1"]["expected"] == owner_row["acceptance"]
    assert cases["sw1"]["evidence_state"] == owner_row["status"]
    assert cases["sw1"]["source_key"] == owner_row["source_key"]
    assert cases["sw1"]["projection_custody"] == owner_row["projection_custody"]


def test_legacy_interface_membership_fails_closed_and_never_becomes_bundled_p() -> None:
    snap = {
        "devices": {"ios1": {"platform": "ios"}, "nx1": {"platform": "nxos"},
                    "access1": {"platform": "ios"}},
        "interfaces": {
            "ios1": {
                "Gi1/0/1": {"port_channel": "Po1"},
                "Gi1/0/2": {"port_channel": "Po1"},
                "Po1": {"port_channel": "Po1"},
            },
            "nx1": {
                "Eth1/1": {"port_channel": "Po7"},
                "Po7": {"port_channel": "Po7"},
            },
            "access1": {"Gi0/1": {"status": "connected"}},
        },
    }

    output = compute_nrfu_commands(snap)
    cases = _etherchannel_cases(output)

    assert set(cases) == {"ios1", "nx1"}
    assert cases["ios1"]["command"] == "show etherchannel summary"
    assert "Po1: 2 associated physical member(s)" in cases["ios1"]["expected"]
    assert cases["nx1"]["command"] == "show port-channel summary"
    assert "Po7: 1 associated physical member(s)" in cases["nx1"]["expected"]
    for case in cases.values():
        assert case["expected"].startswith("ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:")
        assert "member(s) bundled (P)" not in case["expected"]
        assert "association is not proof of (p)/bundled state" in case["expected"].lower()
        assert case["evidence_family"] == "EtherChannel"
        assert case["evidence_state"] == "not_verified"
        assert case["projection_custody"] == "embedded_unverified"
        assert "etherchannel_baseline" in case["source_key"]
        assert "etherchannel_projection" in case["source_key"]
        assert "protocol_assessability" in case["source_key"]

    assert output["summary"]["n_etherchannel_cases"] == 2
    assert output["summary"]["n_etherchannel_blockers"] == 2
    assert output["summary"]["etherchannel_by_evidence_state"] == {"not_verified": 2}


def test_malformed_or_duplicate_prepublished_rows_fail_closed() -> None:
    unsafe = _row("sw1")
    unsafe["command"] = "show version"
    duplicate_a = _row("sw2")
    duplicate_b = _row("sw2")
    snap = {
        "devices": {"sw1": {"platform": "ios"}, "sw2": {"platform": "ios"}},
        "interfaces": {
            "sw1": {"Gi1/0/1": {"port_channel": "Po1"}},
            "sw2": {"Gi1/0/2": {"port_channel": "Po2"}},
        },
        "etherchannel_baseline": _baseline(unsafe, duplicate_a, duplicate_b),
    }

    cases = _etherchannel_cases(compute_nrfu_commands(snap))

    assert set(cases) == {"sw1", "sw2"}
    assert all(case["evidence_state"] == "not_verified" for case in cases.values())
    assert all(case["command"] == "show etherchannel summary" for case in cases.values())
    assert "apparent interface association: Po2" in cases["sw2"]["expected"]


def test_forged_assessed_baseline_cannot_override_degraded_group_and_member_evidence(tmp_path) -> None:
    snap = _owner_evidence(tmp_path, {
        "sw1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SD)       LACP        Gi1/0/1(D)\n",
        ),
    })
    forged = copy.deepcopy(snap["etherchannel_baseline"])
    forged["status"] = "assessed"
    forged["assessed"] = True
    forged["rows"][0]["status"] = "assessed"
    forged["rows"][0]["acceptance"] = (
        "All EtherChannel members are healthy and this baseline is accepted."
    )
    forged["summary"]["by_status"] = {
        "assessed": 1, "degraded": 0, "review": 0, "not_verified": 0,
    }
    snap["etherchannel_baseline"] = forged

    output = compute_nrfu_commands(snap)
    case = _etherchannel_cases(output)["sw1"]

    assert case["evidence_state"] == "not_verified"
    assert case["expected"].startswith("ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:")
    assert "All EtherChannel members are healthy" not in case["expected"]
    assert "projection/receipt-owned EtherChannel subject" in case["expected"]
    assert output["summary"]["n_etherchannel_cases"] == 1
    assert output["summary"]["n_etherchannel_blockers"] == 1


def test_forged_acceptance_and_source_only_cannot_erase_source_owned_degraded_subject(tmp_path) -> None:
    snap = _owner_evidence(tmp_path, {
        "sw1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SD)       LACP        Gi1/0/1(D)\n",
        ),
    })
    forged = copy.deepcopy(snap["etherchannel_baseline"])
    forged["rows"][0]["acceptance"] = "FORGED HEALTHY ACCEPTANCE"
    forged["rows"][0]["source_key"] = "hostile.acceptance.source"
    snap["etherchannel_baseline"] = forged

    output = compute_nrfu_commands(snap)
    case = _etherchannel_cases(output)["sw1"]

    assert case["evidence_state"] == "not_verified"
    assert case["expected"].startswith("ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:")
    assert "FORGED HEALTHY ACCEPTANCE" not in case["expected"]
    assert case["source_key"] != "hostile.acceptance.source"
    assert "etherchannel_projection" in case["source_key"]
    assert "protocol_assessability" in case["source_key"]
    assert output["summary"]["n_etherchannel_cases"] == 1
    assert output["summary"]["n_etherchannel_blockers"] == 1


def test_structurally_valid_but_source_divergent_baseline_fails_closed(tmp_path) -> None:
    source = _owner_evidence(tmp_path, {
        "sw1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SU)       LACP        Gi1/0/1(P)\n",
        ),
    })
    divergent = _owner_evidence(tmp_path, {
        "sw1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SU)       LACP        Gi1/0/1(H)\n",
        ),
    })
    source["etherchannel_baseline"] = divergent["etherchannel_baseline"]

    output = compute_nrfu_commands(source)
    case = _etherchannel_cases(output)["sw1"]

    assert case["evidence_state"] == "not_verified"
    assert case["expected"].startswith("ETHERCHANNEL BASELINE NOT VERIFIED — BLOCKER:")
    assert "hot standby" not in case["expected"]
    assert output["summary"]["n_etherchannel_cases"] == 1
    assert output["summary"]["n_etherchannel_blockers"] == 1


def test_text_pack_carries_etherchannel_family_state_custody_source_and_banner(tmp_path) -> None:
    snap = _owner_evidence(tmp_path, {
        "sw1": (
            "ios", "show etherchannel summary",
            "Group  Port-channel  Protocol    Ports\n"
            "1      Po1(SU)       LACP        Gi1/0/1(w)\n",
        ),
    })
    row = snap["etherchannel_baseline"]["rows"][0]
    acceptance = row["acceptance"]
    assert row["status"] == "review"

    written = write_nrfu_pack(snap, str(tmp_path))
    assert len(written) == 1
    body = open(written[0], encoding="utf-8").read()

    assert "ETHERCHANNEL BASELINE NOT VERIFIED" in body
    assert f"expect: {acceptance}" in body
    assert "evidence_family: EtherChannel" in body
    assert "evidence_state: review" in body
    assert "projection_custody: embedded_unverified" in body
    assert f"source: {row['source_key']}" in body
    assert os.path.basename(written[0]) == "sw1.txt"
