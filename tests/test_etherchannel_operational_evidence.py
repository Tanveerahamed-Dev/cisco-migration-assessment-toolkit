from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cisco_toolkit import input_custody, protocol_assurance
from cisco_toolkit.analyze import (
    compute_etherchannel_projection,
    summarize_etherchannel_baseline,
)
from cisco_toolkit.capture_integrity import compute_capture_integrity_from_paths
from cisco_toolkit.etherchannel import (
    compute_etherchannel_operational_evidence,
    embedded_etherchannel_operational_evidence,
    validate_etherchannel_operational_evidence,
)
from cisco_toolkit.protocol_assurance import (
    bind_snapshot_json_bytes,
    bound_snapshot_source,
)
from cisco_toolkit.protocol_deltas import compute_etherchannel_delta
from cisco_toolkit.l2_rehearsal import compute_l2_failure_rehearsal
from cisco_toolkit.html import compute_cutover_gate
from tests.test_etherchannel_cutover_truth import _receipt as protocol_receipt


FIXTURES = Path(__file__).parent / "fixtures" / "etherchannel"


COMMAND_FILES = {
    "ios": {
        "show etherchannel summary": "show_etherchannel_summary.txt",
        "show running-config": "show_running_config.txt",
        "show running-config | section ^interface": "show_running_config_scoped.txt",
        "show lacp neighbor": "show_lacp_neighbor.txt",
        "show interface status": "show_interface_status.txt",
        "show interfaces": "show_interfaces.txt",
    },
    "nxos": {
        "show port-channel summary": "show_port_channel_summary.txt",
        "show running-config": "show_running_config.txt",
        "show running-config interface": "show_running_config_interface.txt",
        "show lacp neighbor": "show_lacp_neighbor.txt",
        "show interface status": "show_interface_status.txt",
        "show interface": "show_interface.txt",
    },
}


def _paths(platform: str, host: str) -> dict[str, dict[str, str]]:
    base = FIXTURES / platform
    return {host: {
        command: str(base / filename)
        for command, filename in COMMAND_FILES[platform].items()
    }}


def _bind(paths: dict[str, dict[str, str]]) -> None:
    bindings = []
    for mapping in paths.values():
        for command, raw_path in mapping.items():
            payload = Path(raw_path).read_bytes()
            bindings.append({
                "path": raw_path,
                "name": command,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
    input_custody.reset()
    input_custody.bind_files(bindings)


def _produce(
        platform: str, host: str = "sw1", *, declared_platform: str | None = None) -> dict:
    paths = _paths(platform, host)
    _bind(paths)
    projection = compute_etherchannel_projection({host: {}}, paths)
    integrity = compute_capture_integrity_from_paths(paths)
    result = compute_etherchannel_operational_evidence(
        paths, integrity, projection,
        devices={host: {"platform": declared_platform or platform}},
    )
    assert validate_etherchannel_operational_evidence(
        result, require_current_run=True,
    )["valid"] is True
    return result


def _snapshot_from_paths(paths: dict[str, dict[str, str]], platform: str, host: str) -> dict:
    _bind(paths)
    projection = compute_etherchannel_projection({host: {}}, paths)
    disposition = "assessed" if projection["rows"][0]["groups"] else "captured_no_record"
    receipt = protocol_receipt({host: {"EtherChannel": disposition}})
    devices = {host: {"platform": platform}}
    legacy = summarize_etherchannel_baseline(
        projection, receipt, devices=devices)
    typed = compute_etherchannel_operational_evidence(
        paths, compute_capture_integrity_from_paths(paths), projection,
        devices=devices,
    )
    return {
        "schema": "collect_parse_snapshot/1",
        "script_version": "V3.23.0",
        "devices": devices,
        "interfaces": {host: {}},
        "protocol_assessability": receipt,
        "etherchannel_projection": projection,
        "etherchannel_baseline": legacy,
        "etherchannel_operational_evidence":
            embedded_etherchannel_operational_evidence(typed),
    }


def _bound_delta(before: dict, after: dict) -> dict:
    def bind(value: dict) -> tuple[dict, dict]:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        bound = bind_snapshot_json_bytes(raw)
        return bound, {"sha256": bound_snapshot_source(bound)["sha256"], "bytes": len(raw)}

    bound_before, before_binding = bind(before)
    bound_after, after_binding = bind(after)
    return compute_etherchannel_delta(
        bound_before, bound_after,
        comparison_source_binding={"before": before_binding, "after": after_binding},
    )


def _sha(value) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _reseal(value: dict) -> None:
    for cell in value["coverage"]:
        host_rows = [
            row for row in value["rows"] if row["switch"] == cell["switch"]
        ]
        cell["source_sha256"] = _sha(cell["source_receipts"])
        cell["projection_sha256"] = _sha(host_rows)
    unsigned = copy.deepcopy(value)
    unsigned["summary"].pop("evidence_sha256")
    value["summary"]["evidence_sha256"] = _sha(unsigned)


def _copy_paths(
        tmp_path: Path, platform: str, host: str,
        replacements: dict[str, tuple[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, str] = {}
    for command, filename in COMMAND_FILES[platform].items():
        text = (FIXTURES / platform / filename).read_text(encoding="utf-8")
        for old, new in [replacements[command]] if command in replacements else []:
            text = text.replace(old, new)
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        result[command] = str(path)
    return {host: result}


@pytest.mark.parametrize(
    ("platform", "group", "modes", "hash_algorithm", "speed"),
    [
        ("ios", "Po10", ["active", "passive"], "src-dst-ip", 1000),
        ("nxos", "Po20", ["active", "passive"], "src-dst ip-l4port", 10000),
    ],
)
def test_real_ios_nxos_sources_produce_strict_decision_depth(
        platform: str, group: str, modes: list[str], hash_algorithm: str,
        speed: int) -> None:
    evidence = _produce(platform)
    row = evidence["rows"][0]

    assert evidence["schema"] == "etherchannel_operational_evidence/1"
    assert evidence["verdict"] == "CLEAR"
    assert row["group"] == group
    assert row["protocol"] == "lacp"
    assert [item["mode"] for item in row["configured_members"]] == modes
    assert row["partner"] == {
        "status": "assessed",
        "system_id": "0011.2233.4455",
        "aggregation_id": "2" if platform == "ios" else "42",
        "member_count": 2,
    }
    assert row["min_links"] == {"status": "assessed", "configured": True, "value": 1}
    assert row["capacity"]["configured_member_count"] == 2
    assert row["capacity"]["forwarding_member_count"] == 2
    assert row["capacity"]["forwarding_bandwidth_mbps"] == speed * 2
    assert row["hashing"] == {"status": "assessed", "algorithm": hash_algorithm}
    assert row["counter_evidence"]["fault_total"] == 0
    assert row["member_failure_rehearsal"]["status"] == "pass"
    assert row["member_failure_rehearsal"]["after_worst_case_bandwidth_mbps"] == speed
    assert row["member_failure_rehearsal"]["service_path_survival"] == "not_verified"


def test_real_ios_shaped_source_is_the_declared_ios_xe_variant() -> None:
    evidence = _produce("ios", declared_platform="ios-xe")

    assert evidence["verdict"] == "CLEAR"
    assert evidence["rows"][0]["platform"] == "ios"
    assert evidence["rows"][0]["configured_members"] == [
        {"interface": "Gi1/0/1", "mode": "active"},
        {"interface": "Gi1/0/2", "mode": "passive"},
    ]


def test_serialized_projection_is_audit_evidence_not_current_run_authority() -> None:
    receipt = embedded_etherchannel_operational_evidence(_produce("ios"))

    assert validate_etherchannel_operational_evidence(receipt)["valid"] is True
    assert validate_etherchannel_operational_evidence(
        receipt, require_current_run=True,
    )["valid"] is False


@pytest.mark.parametrize("platform", ["ios-xr", "iosxr", "bios", "notnxos"])
def test_platform_support_uses_closed_aliases_and_never_substring_matches(
        platform: str) -> None:
    paths = _paths("ios", "sw1")
    _bind(paths)
    projection = compute_etherchannel_projection({"sw1": {}}, paths)
    evidence = compute_etherchannel_operational_evidence(
        paths, compute_capture_integrity_from_paths(paths), projection,
        devices={"sw1": {"platform": platform}},
    )

    assert evidence["verdict"] == "INDETERMINATE"
    assert evidence["rows"][0]["platform"] == "unsupported"
    assert evidence["rows"][0]["status"] == "not_verified"
    assert evidence["rows"][0]["findings"] == [{
        "kind": "not_verified",
        "code": "platform_unsupported",
        "issue": (
            "This positive EtherChannel subject is outside the declared "
            "IOS/NX-OS source variants."
        ),
    }]


@pytest.mark.parametrize(
    ("protocol_token", "first_mode", "second_mode", "expected_protocol"),
    [
        ("PAgP", "desirable", "auto", "pagp"),
        ("NONE", "on", "on", "static"),
    ],
)
def test_ios_pagp_and_static_modes_remain_exact_without_lacp_partner_inference(
        tmp_path: Path, protocol_token: str, first_mode: str, second_mode: str,
        expected_protocol: str) -> None:
    paths = _copy_paths(
        tmp_path, "ios", "sw1",
        {
            "show etherchannel summary": ("LACP", protocol_token),
            "show running-config": (
                "mode active", f"mode {first_mode}"),
            "show running-config | section ^interface": (
                "mode active", f"mode {first_mode}"),
        },
    )
    for command in ("show running-config", "show running-config | section ^interface"):
        path = Path(paths["sw1"][command])
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "mode passive", f"mode {second_mode}"),
            encoding="utf-8",
        )
    _bind(paths)
    projection = compute_etherchannel_projection({"sw1": {}}, paths)
    evidence = compute_etherchannel_operational_evidence(
        paths, compute_capture_integrity_from_paths(paths), projection,
        devices={"sw1": {"platform": "ios"}},
    )
    row = evidence["rows"][0]

    assert row["protocol"] == expected_protocol
    assert [item["mode"] for item in row["configured_members"]] == [
        first_mode, second_mode,
    ]
    assert row["partner"] == {
        "status": "not_applicable", "system_id": "",
        "aggregation_id": "", "member_count": 0,
    }
    assert row["status"] == "assessed"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("coverage"),
        lambda value: value["rows"][0].pop("min_links"),
        lambda value: value["rows"][0]["partner"].update({"aggregation_id": ""}),
        lambda value: value["rows"][0]["capacity"].update(
            {"forwarding_bandwidth_mbps": 1}),
        lambda value: value["rows"][0]["counter_evidence"].update({"fault_total": "0"}),
        lambda value: value["rows"][0]["member_failure_rehearsal"].update(
            {"service_path_survival": "pass"}),
        lambda value: value["rows"][0].update({"typo": True}),
    ],
)
def test_missing_malformed_renamed_and_claim_expanding_leaves_fail_closed(mutation) -> None:
    receipt = copy.deepcopy(embedded_etherchannel_operational_evidence(_produce("ios")))
    mutation(receipt)

    assert validate_etherchannel_operational_evidence(receipt)["valid"] is False


def test_resealed_renamed_source_command_is_semantically_rejected() -> None:
    receipt = copy.deepcopy(embedded_etherchannel_operational_evidence(_produce("ios")))
    partner = next(
        row for row in receipt["coverage"][0]["source_receipts"]
        if row["role"] == "partner"
    )
    partner["command"] = "show lacp neighbours"
    _reseal(receipt)

    view = validate_etherchannel_operational_evidence(receipt)
    assert view["valid"] is False
    assert view["reason"] == "evidence_source_receipt_invalid"


def test_resealed_failure_rehearsal_cannot_be_relabelled_as_assessed_pass() -> None:
    receipt = copy.deepcopy(embedded_etherchannel_operational_evidence(_produce("ios")))
    row = receipt["rows"][0]
    row["min_links"] = {"status": "assessed", "configured": True, "value": 2}
    row["member_failure_rehearsal"].update({
        "status": "fail", "min_links": 2, "count_survives": False,
    })
    receipt["summary"].update({
        "n_member_failure_pass": 0,
        "n_member_failure_fail": 1,
    })
    _reseal(receipt)

    view = validate_etherchannel_operational_evidence(receipt)
    assert view["valid"] is False
    assert view["reason"] == "evidence_assessed_semantics_invalid"


def test_missing_required_partner_capture_is_not_verified_and_cannot_be_clear() -> None:
    paths = _paths("ios", "sw1")
    paths["sw1"].pop("show lacp neighbor")
    _bind(paths)
    projection = compute_etherchannel_projection({"sw1": {}}, paths)
    evidence = compute_etherchannel_operational_evidence(
        paths, compute_capture_integrity_from_paths(paths), projection,
        devices={"sw1": {"platform": "ios"}},
    )

    row = evidence["rows"][0]
    assert row["partner"]["status"] == "not_verified"
    assert row["status"] == "not_verified"
    assert evidence["verdict"] == "INDETERMINATE"
    assert validate_etherchannel_operational_evidence(
        evidence, require_current_run=True,
    )["valid"] is True


@pytest.mark.parametrize(
    ("mutation", "finding_code"),
    [
        ("renamed_partner_command", "lacp_partner_not_verified"),
        ("truncated_full_config", "full_config_capture_incomplete"),
        ("malformed_utf8", "full_config_capture_unreadable"),
    ],
)
def test_renamed_truncated_or_malformed_required_source_cannot_clear(
        tmp_path: Path, mutation: str, finding_code: str) -> None:
    paths = _copy_paths(tmp_path, "ios", "sw1", {})
    if mutation == "renamed_partner_command":
        paths["sw1"]["show lacp neighbours"] = paths["sw1"].pop(
            "show lacp neighbor")
    elif mutation == "truncated_full_config":
        path = Path(paths["sw1"]["show running-config"])
        path.write_text(
            path.read_text(encoding="utf-8").removesuffix("end\n"),
            encoding="utf-8",
        )
    else:
        path = Path(paths["sw1"]["show running-config"])
        path.write_bytes(path.read_bytes() + b"\xff")

    _bind(paths)
    projection = compute_etherchannel_projection({"sw1": {}}, paths)
    evidence = compute_etherchannel_operational_evidence(
        paths, compute_capture_integrity_from_paths(paths), projection,
        devices={"sw1": {"platform": "ios"}},
    )

    assert evidence["verdict"] == "INDETERMINATE"
    assert evidence["rows"][0]["status"] == "not_verified"
    assert finding_code in {
        finding["code"] for finding in evidence["rows"][0]["findings"]
    }


def test_typed_delta_preserves_exact_depth_and_blocks_min_links_unsafe_rehearsal(
        tmp_path: Path) -> None:
    before_paths = _copy_paths(tmp_path / "before", "ios", "sw1", {})
    after_paths = _copy_paths(
        tmp_path / "after", "ios", "sw1",
        {
            "show running-config": ("port-channel min-links 1", "port-channel min-links 2"),
            "show running-config | section ^interface": (
                "port-channel min-links 1", "port-channel min-links 2"),
        },
    )
    result = _bound_delta(
        _snapshot_from_paths(before_paths, "ios", "sw1"),
        _snapshot_from_paths(after_paths, "ios", "sw1"),
    )

    row = result["changes"][0]
    assert result["assurance_level"] == "intent_reconciled_survival"
    assert row["transition"] == "regressed"
    assert row["decision_effect"] == "block"
    assert row["after_state"]["min_links"]["value"] == 2
    assert row["after_state"]["member_failure_rehearsal"]["status"] == "fail"
    assert row["after_state"]["member_failure_rehearsal"][
        "service_path_survival"] == "not_verified"


def test_safe_mode_and_hash_movement_is_review_until_exact_intent_reconciles(
        tmp_path: Path) -> None:
    before_paths = _copy_paths(tmp_path / "before", "ios", "sw1", {})
    after_paths = _copy_paths(
        tmp_path / "after", "ios", "sw1",
        {
            "show running-config": ("mode passive", "mode active"),
            "show running-config | section ^interface": (
                "mode passive", "mode active"),
        },
    )
    full_config = Path(after_paths["sw1"]["show running-config"])
    full_config.write_text(
        full_config.read_text(encoding="utf-8").replace(
            "src-dst-ip", "dst-ip"),
        encoding="utf-8",
    )
    result = _bound_delta(
        _snapshot_from_paths(before_paths, "ios", "sw1"),
        _snapshot_from_paths(after_paths, "ios", "sw1"),
    )

    row = result["changes"][0]
    assert row["transition"] == "intent_changed"
    assert row["decision_effect"] == "review"
    assert [item["mode"] for item in row["after_state"]["configured_members"]] == [
        "active", "active",
    ]
    assert row["after_state"]["hashing"]["algorithm"] == "dst-ip"
    family_changes = protocol_assurance.protocol_family_change_set(
        {
            "schema": "protocol_adjacency_delta/1",
            "summary": {"n_preserved": 1},
            "changes": [],
            "coverage_gaps": [],
        },
        {"expected_changes": [{
            "family": "etherchannel",
            "transitions": ["intent_changed"],
            "subjects": [row["subject"]],
        }]},
        native_deltas=[result],
    )
    composed = next(
        change
        for family in family_changes["families"]
        if family["family"] == "etherchannel"
        for change in family["changes"]
    )
    assert composed["expected"] is True
    assert composed["decision_effect"] == "none"


def test_bounded_current_counter_fault_remains_block_on_clean_self_delta(
        tmp_path: Path) -> None:
    paths = _copy_paths(
        tmp_path, "ios", "sw1",
        {"show interfaces": ("0 input errors", "5 input errors")},
    )
    snapshot = _snapshot_from_paths(paths, "ios", "sw1")
    result = _bound_delta(snapshot, copy.deepcopy(snapshot))

    row = result["changes"][0]
    assert row["transition"] == "unchanged_degraded"
    assert row["decision_effect"] == "block"
    assert row["after_state"]["counter_evidence"]["fault_total"] == 10


def test_newly_appeared_degraded_group_is_producer_block_not_expected_review(
        tmp_path: Path) -> None:
    before_paths = _copy_paths(
        tmp_path / "before", "ios", "sw1",
        {
            "show etherchannel summary": (
                "10     Po10(SU)        LACP       Gi1/0/1(P) Gi1/0/2(P)\n", ""),
            "show running-config": (
                "interface GigabitEthernet1/0/1\n description first uplink member\n"
                " channel-group 10 mode active\n!\ninterface GigabitEthernet1/0/2\n"
                " description second uplink member\n channel-group 10 mode passive\n!\n"
                "interface Port-channel10\n description upstream bundle\n"
                " port-channel min-links 1\n!\n", ""),
            "show running-config | section ^interface": (
                "interface GigabitEthernet1/0/1\n description first uplink member\n"
                " channel-group 10 mode active\n!\ninterface GigabitEthernet1/0/2\n"
                " description second uplink member\n channel-group 10 mode passive\n!\n"
                "interface Port-channel10\n description upstream bundle\n"
                " port-channel min-links 1\n!\n", ""),
        },
    )
    after_paths = _copy_paths(
        tmp_path / "after", "ios", "sw1",
        {
            "show running-config": ("port-channel min-links 1", "port-channel min-links 2"),
            "show running-config | section ^interface": (
                "port-channel min-links 1", "port-channel min-links 2"),
        },
    )
    result = _bound_delta(
        _snapshot_from_paths(before_paths, "ios", "sw1"),
        _snapshot_from_paths(after_paths, "ios", "sw1"),
    )

    assert result["changes"][0]["transition"] == "appeared"
    assert result["changes"][0]["decision_effect"] == "block"
    assert "expected intent cannot clear" in result["changes"][0]["note"]

    family_changes = protocol_assurance.protocol_family_change_set(
        {
            "schema": "protocol_adjacency_delta/1",
            "summary": {"n_preserved": 1},
            "changes": [],
            "coverage_gaps": [],
        },
        {"expected_changes": [{
            "family": "etherchannel",
            "transitions": ["appeared"],
            "subjects": [result["changes"][0]["subject"]],
        }]},
        native_deltas=[result],
    )
    gate = compute_cutover_gate(
        {
            "verdict": "CLEAN",
            "verdict_display": "NO DELTA REGRESSION OBSERVED",
            "verdict_note": "legacy delta is clean",
            "protocol_adjacencies": {
                "gate": "PASS",
                "summary": {
                    "n_state_regressed": 0,
                    "n_coverage_gaps": 0,
                    "n_baseline_peers": 1,
                },
            },
        },
        {"verdict": "PASS", "verdict_note": "certificate clean"},
        protocol_family_changes=family_changes,
    )
    assert gate["verdict"] == "REGRESSED"
    assert gate["protocol_family_blocking"] == 1


def test_l2_rehearsal_consumes_typed_local_min_links_and_never_claims_service(
        tmp_path: Path) -> None:
    paths = _copy_paths(tmp_path, "ios", "sw1", {})
    snapshot = _snapshot_from_paths(paths, "ios", "sw1")
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    rehearsal = compute_l2_failure_rehearsal(bind_snapshot_json_bytes(raw))
    row = next(
        item for item in rehearsal["scenarios"] if item["family"] == "etherchannel"
    )

    assert row["disposition"] == "simulation_only"
    assert row["evidence"]["configured_min_links"] == 1
    assert row["evidence"]["observed_forwarding_member_count"] == 2
    assert row["evidence"]["remaining_forwarding_members_after_loss"] == 1
    assert row["evidence"]["remaining_worst_case_bandwidth_mbps"] == 1000
    assert row["evidence"]["service_path_survival"] == "not_verified"
