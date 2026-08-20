from __future__ import annotations

import copy
import hashlib

import pytest

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.html import compute_cutover_gate
from cisco_toolkit.multichassis_lag import (
    MULTICHASSIS_LAG_DELTA_SCHEMA,
    MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA,
    MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA,
    compute_multichassis_lag_delta,
    compute_multichassis_lag_domain_baseline,
    compute_multichassis_lag_subject_scope,
    multichassis_lag_support_profile,
    produce_multichassis_lag_typed_observation,
    validate_multichassis_lag_domain_baseline,
    validate_multichassis_lag_snapshot_evidence,
)
from cisco_toolkit.protocol_assurance import ASSURANCE_LEVELS, CHANGE_VOCABULARY


def _identity(name: str) -> str:
    compact = hashlib.sha256(name.casefold().encode()).hexdigest()[:12]
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _nxos_observation(
    switch: str,
    peer: str,
    *,
    source_digit: str,
    domain_id: str = "10",
    attachment_id: str | None = "20",
    port_channel: str = "Po20",
    partner_system: str | None = "0011.2233.4455",
    partner_aggregation: str | None = "42",
    status: str = "up",
    consistency: str = "success",
    collection_mode: str = "live",
    extra_legs: list[dict] | None = None,
    domain_state_overrides: dict[str, str] | None = None,
    dual_active_status: str = "0",
    orphan_output: str = "VLAN           Orphan Ports\n-------        -------------------------\n",
    orphan_suspend_ports: tuple[str, ...] = (),
    running_config_output: str | None = None,
    declared_leg_count: int | None = None,
) -> dict:
    legs = []
    if attachment_id is not None:
        legs.append(
            {
                "attachment_id": attachment_id,
                "local_port_channel": port_channel,
                "status": status,
                "consistency": consistency,
                "lacp_partner_system_id": partner_system,
                "lacp_partner_aggregation_id": partner_aggregation,
            }
        )
    legs.extend(extra_legs or [])
    vpc_rows = "".join(
        f"{leg['attachment_id']} {leg['local_port_channel']} {leg['status']} "
        f"{leg['consistency']} success 10-20\n"
        for leg in legs
    )
    domain_state = {
        "peer_status": "peer adjacency formed ok",
        "keepalive_status": "peer is alive",
        "consistency": "success",
        "peer_link_status": "up",
    }
    domain_state.update(domain_state_overrides or {})
    vpc = f"""vPC domain id                     : {domain_id}
Peer status                       : {domain_state['peer_status']}
vPC keep-alive status             : {domain_state['keepalive_status']}
Configuration consistency status : {domain_state['consistency']}
Number of vPCs configured         : {len(legs) if declared_leg_count is None else declared_leg_count}

vPC Peer-link status
id Port Status Active vlans
1 Po100 {domain_state['peer_link_status']} 1-4094

vPC status
id Port Status Consistency Reason Active vlans
{vpc_rows}""".encode()
    role = f"""vPC Role status
vPC role                        : primary
Dual Active Detection Status    : {dual_active_status}
vPC system-mac                  : 00:00:5e:00:01:01
vPC local system-mac            : {_identity(switch)}
vPC peer system-mac             : {_identity(peer)}
""".encode()
    lacp_sections = []
    for leg in legs:
        partner_system_value = leg.get("lacp_partner_system_id")
        partner_key_value = leg.get("lacp_partner_aggregation_id")
        if not partner_system_value or not partner_key_value:
            continue
        port_number = int("".join(ch for ch in leg["local_port_channel"] if ch.isdigit()))
        partner_mac = str(partner_system_value).replace(".", "").replace(":", "").replace("-", "")
        partner_mac = "-".join(partner_mac[index:index + 2] for index in range(0, 12, 2))
        key = int(str(partner_key_value), 0) if str(partner_key_value).startswith("0x") else int(partner_key_value)
        lacp_sections.append(f"""port-channel{port_number} neighbors
Partner's information
Port System ID Port Number Age Flags
Eth1/{port_number} 32768,{partner_mac}0x11f 20 SA
LACP Partner Partner Partner
Port Priority Oper Key Port State
32768 0x{key:x} 0x3d
""")
    commands = {
        "show vpc": vpc,
        "show vpc role": role,
        "show lacp neighbor": ("\n".join(lacp_sections) or "No LACP neighbors\n").encode(),
        "show vpc orphan-ports": orphan_output.encode(),
        "show running-config": (
            running_config_output
            if running_config_output is not None else
            "hostname " + switch + "\n" + "\n".join(
                f"interface {interface}\n"
                + (" vpc orphan-port suspend\n" if interface in orphan_suspend_ports else "")
                for interface in sorted({"Eth1/1", *orphan_suspend_ports})
            ) + "\nend\n"
        ).encode(),
    }
    observation = produce_multichassis_lag_typed_observation(
        switch, vendor="cisco", platform="nxos", collection_mode=collection_mode,
        command_bytes=commands,
    )
    assert observation is not None
    return observation


def _eos_observation(
    switch: str,
    peer: str,
    *,
    source_digit: str,
    domain_id: str = "blue",
    attachment_id: str | None = "20",
    partner_system: str | None = "00:11:22:33:44:55",
    partner_aggregation: str | None = "42",
    collection_mode: str = "offline",
    domain_state_overrides: dict[str, str] | None = None,
) -> dict:
    interfaces = ""
    lacp = "No LACP peers\n"
    if attachment_id is not None:
        interfaces = (
            "mlag state local remote oper config last change changes\n"
            f"{attachment_id} active-full Po20 Po20 up/up ena/ena 1 day ago 1\n"
        )
        if partner_system and partner_aggregation:
            lacp = f"""Port Channel Port-Channel20*:
Et20 Bundled | 8000,{str(partner_system).replace(':', '-')} 20 ALGs+CD 0x{int(partner_aggregation):04x} 32768
"""
    domain_state = {
        "state": "active",
        "neg_status": "connected",
        "config_sanity": "consistent",
        "peer_link_status": "up",
        "local_intf_status": "up",
    }
    domain_state.update(domain_state_overrides or {})
    observation = produce_multichassis_lag_typed_observation(
        switch, vendor="arista", platform="eos", collection_mode=collection_mode,
        command_bytes={
            "show mlag": (
                '{"domainId":"' + domain_id + '","peerAddress":"192.0.2.1",'
                f'"peerLink":"Port-Channel1000","state":"{domain_state["state"]}",'
                f'"negStatus":"{domain_state["neg_status"]}",'
                f'"configSanity":"{domain_state["config_sanity"]}",'
                f'"peerLinkStatus":"{domain_state["peer_link_status"]}",'
                f'"localIntfStatus":"{domain_state["local_intf_status"]}",'
                '"systemId":"02:1c:73:00:13:19","mlagPorts":{"Active-full":1}}'
            ).encode(),
            "show mlag interfaces detail": interfaces.encode(),
            "show lacp peer": lacp.encode(),
        },
    )
    assert observation is not None
    return observation


def _nxos_pair(*, domain_id: str = "10", second_status: str = "up",
               partner_system: str = "0011.2233.4455",
               partner_aggregation: str = "42",
               second_partner_system: str | None = None,
               second_partner_aggregation: str | None = None,
               extra_legs: list[dict] | None = None,
               dual_active_status: str = "0",
               second_dual_active_status: str | None = None) -> dict:
    return {
        "observations": [
            _nxos_observation(
                "leaf-a", "leaf-b", source_digit="a", domain_id=domain_id,
                partner_system=partner_system, partner_aggregation=partner_aggregation,
                extra_legs=extra_legs, dual_active_status=dual_active_status),
            _nxos_observation(
                "leaf-b", "leaf-a", source_digit="b", domain_id=domain_id,
                status=second_status,
                partner_system=(second_partner_system or partner_system),
                partner_aggregation=(second_partner_aggregation or partner_aggregation),
                extra_legs=extra_legs,
                dual_active_status=(second_dual_active_status or dual_active_status)),
        ]
    }


def _eos_pair() -> dict:
    return {
        "observations": [
            _eos_observation("eos-a", "eos-b", source_digit="c"),
            _eos_observation("eos-b", "eos-a", source_digit="d"),
        ]
    }


def _binding(before: dict, after: dict) -> dict:
    return {
        "custody": "persisted_snapshot_bytes_bound",
        "before_snapshot_sha256": f"sha256:{'1' * 64}",
        "after_snapshot_sha256": f"sha256:{'2' * 64}",
        "before_baseline_sha256": before["summary"]["baseline_sha256"],
        "after_baseline_sha256": after["summary"]["baseline_sha256"],
    }


def _assert_no_overall_decision(value: dict) -> None:
    assert value["owns_score"] is False
    assert value["owns_verdict"] is False
    assert "score" not in value
    assert "verdict" not in value


def _canonical_gate_for(native_delta: dict, expected_changes: list[dict]) -> tuple[dict, dict]:
    ipv4 = {
        "schema": "protocol_adjacency_delta/1",
        "summary": {"n_preserved": 1},
        "changes": [],
        "coverage_gaps": [],
    }
    families = pa.protocol_family_change_set(
        ipv4,
        {"expected_changes": expected_changes},
        native_deltas=[native_delta],
    )
    clean_delta = {
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
    }
    gate = compute_cutover_gate(
        clean_delta,
        {"verdict": "PASS", "verdict_note": "certificate clean"},
        protocol_family_changes=families,
    )
    return families, gate


def test_support_profile_and_subject_scope_are_closed_and_total() -> None:
    profile = multichassis_lag_support_profile()
    assert profile["owner_schema"] == MULTICHASSIS_LAG_DELTA_SCHEMA
    assert profile["assurance_level"] == "intent_reconciled_survival"
    assert profile["variants"][0]["collection_modes"] == ["live", "offline"]
    assert profile["variants"][0]["raw_commands"] == [
        "show vpc", "show vpc role", "show lacp neighbor",
        "show vpc orphan-ports", "show running-config",
    ]
    assert profile["variants"][0]["maximum_assurance"] == "intent_reconciled_survival"
    assert profile["variants"][1]["collection_modes"] == ["offline"]
    assert profile["variants"][1]["raw_commands"] == [
        "show mlag", "show mlag interfaces detail", "show lacp peer",
    ]
    assert profile["variants"][1]["maximum_assurance"] == "local_safety_preservation"
    assert any("No IOS" in limitation for limitation in profile["limitations"])

    scope = compute_multichassis_lag_subject_scope(_nxos_pair())
    assert scope["schema"] == MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA
    _assert_no_overall_decision(scope)
    assert scope["summary"]["n_in_scope"] == 2
    assert {row["source_custody"] for row in scope["rows"]} == {"current_run_source_bound"}

    unsupported = _eos_pair()
    unsupported["observations"][0]["collection_mode"] = "live"
    unsupported_scope = compute_multichassis_lag_subject_scope(unsupported)
    assert unsupported_scope["summary"]["n_not_verified"] == 2
    assert unsupported_scope["rows"][0]["status"] == "not_verified"

    for malformed in (None, [], "typed", {"observations": [None]}):
        candidate_scope = compute_multichassis_lag_subject_scope(malformed)
        baseline = compute_multichassis_lag_domain_baseline(malformed)
        assert candidate_scope["schema"] == MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA
        assert baseline["schema"] == MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA
        assert baseline["summary"]["by_health_state"]["healthy"] == 0
        assert validate_multichassis_lag_domain_baseline(baseline)["valid"] is True


def test_reciprocal_pair_and_attachment_require_complete_typed_evidence() -> None:
    baseline = compute_multichassis_lag_domain_baseline(_nxos_pair())
    validation = validate_multichassis_lag_domain_baseline(baseline, require_current_run=True)

    assert validation["valid"] is True
    assert validation["source_bound"] is True
    _assert_no_overall_decision(baseline)
    assert [row["record_type"] for row in baseline["local_observations"]] == [
        "local_observation",
        "local_observation",
    ]
    assert [row["record_type"] for row in baseline["reciprocal_peer_pairs"]] == [
        "reciprocal_peer_pair"
    ]
    assert [row["record_type"] for row in baseline["local_legs"]] == ["local_leg", "local_leg"]
    assert [row["record_type"] for row in baseline["reconciled_attachments"]] == [
        "reconciled_attachment"
    ]
    assert baseline["summary"]["by_health_state"]["not_verified"] == 0
    assert baseline["summary"]["by_health_state"]["degraded"] == 0
    attachment = baseline["reconciled_attachments"][0]
    assert attachment["lacp_partner_system_id"] == "00:11:22:33:44:55"
    assert attachment["lacp_partner_aggregation_id"] == "42"
    assert attachment["assurance_level"] == "intent_reconciled_survival"


def test_domain_id_is_an_attribute_and_never_pair_identity() -> None:
    baseline = compute_multichassis_lag_domain_baseline(_nxos_pair())
    renumbered = compute_multichassis_lag_domain_baseline(_nxos_pair(domain_id="901"))
    assert baseline["reciprocal_peer_pairs"][0]["subject_id"] == (
        renumbered["reciprocal_peer_pairs"][0]["subject_id"]
    )

    one_sided = _nxos_pair()
    one_sided["observations"][1]["peer_identity"] = "leaf-c"
    inferred = compute_multichassis_lag_domain_baseline(one_sided)
    assert inferred["reciprocal_peer_pairs"] == []
    assert inferred["reconciled_attachments"] == []
    assert {row["health_state"] for row in inferred["local_observations"]} == {"not_verified"}
    assert {row["health_state"] for row in inferred["local_legs"]} == {"not_verified"}


def test_reused_domain_ids_keep_reciprocal_pairs_distinct_but_not_verified() -> None:
    value = {
        "observations": [
            _nxos_observation("site1-a", "site1-b", source_digit="a", domain_id="10"),
            _nxos_observation("site1-b", "site1-a", source_digit="b", domain_id="10"),
            _nxos_observation("site2-a", "site2-b", source_digit="c", domain_id="10"),
            _nxos_observation("site2-b", "site2-a", source_digit="d", domain_id="10"),
        ]
    }
    baseline = compute_multichassis_lag_domain_baseline(value)

    assert len(baseline["reciprocal_peer_pairs"]) == 2
    assert len({row["subject_id"] for row in baseline["reciprocal_peer_pairs"]}) == 2
    assert {row["health_state"] for row in baseline["reciprocal_peer_pairs"]} == {"not_verified"}
    assert len(baseline["reconciled_attachments"]) == 2
    assert {row["health_state"] for row in baseline["reconciled_attachments"]} == {"not_verified"}
    assert all(
        any(finding["code"] == "domain_id_reused" for finding in row["findings"])
        for row in baseline["reciprocal_peer_pairs"]
    )


@pytest.mark.parametrize(
    ("mutator", "expected_state"),
    [
        (lambda value: value["observations"][1]["legs"][0].pop("lacp_partner_system_id"), "not_verified"),
        (
            lambda value: value["observations"][1]["legs"][0].__setitem__(
                "lacp_partner_system_id", "00aa.bbcc.ddee"
            ),
            "degraded",
        ),
        (lambda value: value["observations"][1].__setitem__("legs", []), "not_verified"),
    ],
)
def test_matching_attachment_id_without_both_matching_lacp_legs_never_reconciles(
    mutator, expected_state: str
) -> None:
    value = _nxos_pair()
    mutator(value)
    baseline = compute_multichassis_lag_domain_baseline(value)

    assert baseline["reconciled_attachments"] == []
    assert expected_state in {row["health_state"] for row in baseline["local_legs"]}
    assert "healthy" not in {
        row["health_state"]
        for row in baseline["local_legs"]
        if row["attachment_subject_id"]
    }


@pytest.mark.parametrize(
    ("platform", "field", "value", "expected_state"),
    [
        ("nxos", "peer_status", "peer adjacency not formed", "degraded"),
        ("nxos", "peer_status", "peer adjacency pending", "not_verified"),
        ("nxos", "keepalive_status", "", "not_verified"),
        ("eos", "state", "connecting", "not_verified"),
        ("eos", "neg_status", "disconnected", "degraded"),
        ("eos", "peer_link_status", "down", "degraded"),
    ],
)
def test_unknown_missing_and_known_bad_domain_states_fail_closed(
    platform: str, field: str, value: str, expected_state: str
) -> None:
    fixture = _nxos_pair() if platform == "nxos" else _eos_pair()
    fixture["observations"][0]["domain_state"][field] = value
    baseline = compute_multichassis_lag_domain_baseline(fixture)

    local = next(row for row in baseline["local_observations"] if row["switch"].endswith("-a"))
    assert local["health_state"] == expected_state
    if platform == "nxos":
        assert baseline["reciprocal_peer_pairs"][0]["health_state"] == expected_state
        assert baseline["reconciled_attachments"][0]["health_state"] == expected_state
    else:
        assert baseline["reciprocal_peer_pairs"] == []
        assert baseline["reconciled_attachments"] == []


@pytest.mark.parametrize(
    "mutator",
    [
        lambda source: source.pop("source_sha256"),
        lambda source: source.__setitem__("source_sha256", "sha256:truncated"),
        lambda source: source.__setitem__("commands", "show vpc"),
        lambda source: source.__setitem__("capture_status", "renamed-ok"),
        lambda source: source.__setitem__("projection_custody", "trusted"),
    ],
)
def test_source_receipt_missing_renamed_truncated_or_malformed_leaves_fail_closed(mutator) -> None:
    value = _nxos_pair()
    mutator(value["observations"][0]["source"])
    baseline = compute_multichassis_lag_domain_baseline(value)

    local = next(row for row in baseline["local_observations"] if row["switch"] == "leaf-a")
    assert local["health_state"] == "not_verified"
    assert local["source_custody"] == "embedded_unverified"
    assert baseline["reciprocal_peer_pairs"][0]["health_state"] == "not_verified"
    assert baseline["reconciled_attachments"][0]["health_state"] == "not_verified"


def test_validator_rejects_tamper_and_plain_rehydration_cannot_claim_current_run() -> None:
    baseline = compute_multichassis_lag_domain_baseline(_nxos_pair())
    tampered = copy.deepcopy(dict(baseline))
    tampered["reconciled_attachments"][0]["lacp_partner_system_id"] = "aa:bb:cc:dd:ee:ff"
    assert validate_multichassis_lag_domain_baseline(tampered)["valid"] is False

    rehydrated = copy.deepcopy(dict(baseline))
    validation = validate_multichassis_lag_domain_baseline(rehydrated)
    assert validation["valid"] is True
    assert validation["source_bound"] is False
    current_run = validate_multichassis_lag_domain_baseline(rehydrated, require_current_run=True)
    assert current_run == {
        "present": True,
        "valid": False,
        "source_bound": False,
        "reason": "baseline_not_current_run_source_bound",
        "baseline": {},
    }


def test_delta_uses_shared_vocabulary_and_tracks_health_and_intent_transitions() -> None:
    healthy = compute_multichassis_lag_domain_baseline(_nxos_pair())
    unchanged = compute_multichassis_lag_delta(healthy, healthy, source_binding=_binding(healthy, healthy))
    _assert_no_overall_decision(unchanged)
    assert set(unchanged["summary"]["by_transition"]) == set(CHANGE_VOCABULARY)
    assert unchanged["summary"]["by_transition"]["unchanged_healthy"] == 6
    assert {row["assurance_level"] for row in unchanged["changes"]} <= set(ASSURANCE_LEVELS)
    assert all(row["subject"] == row["subject_id"] for row in unchanged["changes"])
    assert {row["decision_effect"] for row in unchanged["changes"]} == {"none"}
    assert all(row["note"] for row in unchanged["changes"])

    # Two independently stored snapshots can have identical content bytes.  Distinct comparison
    # identity is enforced by admission, so equal content hashes do not make typed evidence invalid.
    equal_content_binding = _binding(healthy, healthy)
    equal_content_binding["after_snapshot_sha256"] = equal_content_binding[
        "before_snapshot_sha256"
    ]
    equal_content = compute_multichassis_lag_delta(
        healthy, healthy, source_binding=equal_content_binding)
    assert equal_content["comparison_failures"] == []
    assert equal_content["summary"]["by_transition"]["unchanged_healthy"] == 6

    degraded = compute_multichassis_lag_domain_baseline(
        _nxos_pair(second_status="down"))
    regression = compute_multichassis_lag_delta(
        healthy,
        degraded,
        source_binding=_binding(healthy, degraded),
    )
    assert regression["summary"]["by_transition"]["regressed"] == 2
    assert {
        row["decision_effect"]
        for row in regression["changes"]
        if row["transition"] == "regressed"
    } == {"block"}
    reverse = compute_multichassis_lag_delta(
        degraded,
        healthy,
        source_binding=_binding(degraded, healthy),
    )
    assert reverse["summary"]["by_transition"]["recovered"] == 2
    current_fault = compute_multichassis_lag_delta(
        degraded,
        degraded,
        source_binding=_binding(degraded, degraded),
    )
    assert current_fault["summary"]["by_transition"]["unchanged_degraded"] == 2
    assert {
        row["decision_effect"]
        for row in current_fault["changes"]
        if row["transition"] == "unchanged_degraded"
    } == {"block"}

    changed = compute_multichassis_lag_domain_baseline(_nxos_pair(
        partner_system="00aa.bbcc.ddee", partner_aggregation="84"))
    intent = compute_multichassis_lag_delta(
        healthy,
        changed,
        source_binding=_binding(healthy, changed),
    )
    assert intent["summary"]["by_transition"]["intent_changed"] == 3
    assert {
        row["decision_effect"]
        for row in intent["changes"]
        if row["transition"] == "intent_changed"
    } == {"review"}
    assert any(
        row["record_type"] == "reconciled_attachment"
        and row["transition"] == "intent_changed"
        and row["changed_fields"] == [
            "lacp_partner_aggregation_id",
            "lacp_partner_system_id",
        ]
        for row in intent["changes"]
    )


def test_changed_current_degradation_stays_blocking_through_expected_intent_and_gate() -> None:
    before = compute_multichassis_lag_domain_baseline(
        _nxos_pair(second_status="down"))
    after = compute_multichassis_lag_domain_baseline(_nxos_pair(
        second_status="down",
        partner_system="00aa.bbcc.ddee",
        partner_aggregation="84",
    ))
    native = compute_multichassis_lag_delta(
        before, after, source_binding=_binding(before, after))

    degraded = [row for row in native["changes"] if row["after_state"] == "degraded"]
    assert len(degraded) == 2
    assert all(row["changed_fields"] for row in degraded)
    assert {row["transition"] for row in degraded} == {"unchanged_degraded"}
    assert {row["decision_effect"] for row in degraded} == {"block"}

    expected = [{
        "family": "multichassis_lag",
        "transitions": ["intent_changed", "unchanged_degraded"],
        "subjects": [],
        "reason": "planned attachment identity update",
    }]
    families, gate = _canonical_gate_for(native, expected)
    family = next(
        row for row in families["families"] if row["family"] == "multichassis_lag")
    current_faults = [
        row for row in family["changes"] if row["after_state"] == "degraded"
    ]
    assert current_faults and all(row["expected"] is True for row in current_faults)
    assert {row["decision_effect"] for row in current_faults} == {"block"}
    assert family["summary"]["n_blocking"] == len(current_faults)
    assert gate["verdict"] == "REGRESSED"
    assert gate["protocol_family_blocking"] == len(current_faults)


def test_appeared_degraded_subjects_stay_blocking_through_expected_intent_and_gate() -> None:
    before = compute_multichassis_lag_domain_baseline(_nxos_pair())
    after = compute_multichassis_lag_domain_baseline(_nxos_pair(extra_legs=[{
        "attachment_id": "30",
        "local_port_channel": "Po30",
        "status": "down",
        "consistency": "success",
        "lacp_partner_system_id": "00ff.eedd.ccbb",
        "lacp_partner_aggregation_id": "60",
    }]))
    native = compute_multichassis_lag_delta(
        before, after, source_binding=_binding(before, after))

    appeared_faults = [
        row for row in native["changes"]
        if row["transition"] == "appeared" and row["after_state"] == "degraded"
    ]
    assert len(appeared_faults) == 3
    assert {row["record_type"] for row in appeared_faults} == {
        "local_leg", "reconciled_attachment",
    }
    assert {row["decision_effect"] for row in appeared_faults} == {"block"}

    expected = [{
        "family": "multichassis_lag",
        "transitions": ["appeared"],
        "subjects": [row["subject"] for row in appeared_faults],
        "reason": "planned new dual-homed attachment",
    }]
    families, gate = _canonical_gate_for(native, expected)
    family = next(
        row for row in families["families"] if row["family"] == "multichassis_lag")
    current_faults = [
        row for row in family["changes"] if row["after_state"] == "degraded"
    ]
    assert current_faults and all(row["expected"] is True for row in current_faults)
    assert {row["decision_effect"] for row in current_faults} == {"block"}
    assert gate["verdict"] == "REGRESSED"
    assert gate["protocol_family_blocking"] == len(current_faults)


def test_source_bound_nxos_dual_active_status_is_preserved_and_compared() -> None:
    before = compute_multichassis_lag_domain_baseline(
        _nxos_pair(dual_active_status="0"))
    after = compute_multichassis_lag_domain_baseline(
        _nxos_pair(dual_active_status="1"))

    assert {row["dual_active_status"] for row in before["local_observations"]} == {
        "0"
    }
    assert {row["dual_active_status"] for row in after["local_observations"]} == {
        "1"
    }
    native = compute_multichassis_lag_delta(
        before, after, source_binding=_binding(before, after))
    changed = [
        row for row in native["changes"]
        if row["record_type"] == "local_observation"
        and "dual_active_status" in row["changed_fields"]
    ]
    assert len(changed) == 2
    assert {row["transition"] for row in changed} == {"regressed"}
    assert {row["decision_effect"] for row in changed} == {"block"}

    expected = [{
        "family": "multichassis_lag",
        "transitions": ["regressed"],
        "subjects": [row["subject"] for row in changed],
        "reason": "planned vPC role work",
    }]
    families, gate = _canonical_gate_for(native, expected)
    family = next(
        row for row in families["families"] if row["family"] == "multichassis_lag")
    regressed = [
        row for row in family["changes"]
        if row["subject"] in {item["subject"] for item in changed}
    ]
    assert regressed and all(row["expected"] is True for row in regressed)
    assert {row["decision_effect"] for row in regressed} == {"block"}
    assert gate["verdict"] == "REGRESSED"

    unknown = compute_multichassis_lag_domain_baseline(
        _nxos_pair(dual_active_status="Disabled"))
    assert {row["health_state"] for row in unknown["local_observations"]} == {
        "not_verified"
    }


def test_source_bound_nxos_orphan_ports_preserve_vlan_and_suspend_evidence() -> None:
    orphan_output = """Switch# show vpc orphan-ports
Note:
--------::Going through port database. Please be patient.::--------

VLAN           Orphan Ports
-------        -------------------------
10             Po21, Eth1/45
20             Po21
"""
    baseline = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation(
            "leaf-a", "leaf-b", source_digit="a",
            orphan_output=orphan_output,
            orphan_suspend_ports=("Eth1/45",),
        ),
        _nxos_observation(
            "leaf-b", "leaf-a", source_digit="b",
            orphan_output="VLAN           Orphan Ports\n"
                          "-------        -------------------------\n",
        ),
    ]})

    leaf_a = next(
        row for row in baseline["local_observations"] if row["switch"] == "leaf-a"
    )
    assert leaf_a["orphan_evidence"] == {
        "status": "assessed",
        "ports": [
            {
                "interface": "Eth1/45",
                "vlans": [10],
                "suspend_on_peer_link_loss": True,
            },
            {
                "interface": "Po21",
                "vlans": [10, 20],
                "suspend_on_peer_link_loss": False,
            },
        ],
        "orphan_table_observed": True,
        "suspend_config_observed": True,
    }
    assert leaf_a["health_state"] == "healthy"
    assert validate_multichassis_lag_domain_baseline(baseline)["valid"] is True

    missing = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation("leaf-a", "leaf-b", source_digit="a"),
        _nxos_observation("leaf-b", "leaf-a", source_digit="b"),
    ]})
    changed = compute_multichassis_lag_delta(
        missing, baseline, source_binding=_binding(missing, baseline))
    rows = [
        row for row in changed["changes"]
        if row["record_type"] == "local_observation"
        and "orphan_evidence" in row["changed_fields"]
    ]
    assert len(rows) == 1
    assert rows[0]["transition"] == "intent_changed"
    assert rows[0]["decision_effect"] == "review"


@pytest.mark.parametrize(
    ("orphan_output", "running_config_output"),
    (
        ("VLAN Orphan Ports\n", "interface Eth1/1\nend\n"),
        ('{"TABLE_orphan_ports":{}}', "interface Eth1/1\nend\n"),
        (
            '{"TABLE_orphan_ports":{"ROW_orphan_ports":'
            '{"vpc-vlan":"10"}}}',
            "interface Eth1/1\nend\n",
        ),
        (
            "VLAN           Orphan Ports\n-------        -------------------------\n",
            "interface Eth1/1\n",
        ),
        (
            "VLAN           Orphan Ports\n-------        -------------------------\n10\n",
            "interface Eth1/1\nend\n",
        ),
        (
            "VLAN           Orphan Ports\n-------        -------------------------\nBADVLAN Eth1/7\n",
            "interface Eth1/1\nend\n",
        ),
        (
            "VLAN           Orphan Ports\n-------        -------------------------\n10 BADPORT\n",
            "interface Eth1/1\nend\n",
        ),
        (
            "ERROR: no vPC orphan ports because authorization failed\n",
            "interface Eth1/1\nend\n",
        ),
        (
            "No orphan ports information available due timeout\n",
            "interface Eth1/1\nend\n",
        ),
        (
            "garbage no orphan port response truncated\n",
            "interface Eth1/1\nend\n",
        ),
    ),
    ids=(
        "header-only", "json-table-only", "json-row-leaf-missing", "config-truncated",
        "text-row-truncated", "text-vlan-malformed", "text-port-malformed",
        "explicit-empty-error-prefix", "explicit-empty-error-suffix",
        "explicit-empty-garbage-wrapper",
    ),
)
def test_truncated_or_malformed_orphan_sources_cannot_authorize_health(
        orphan_output: str, running_config_output: str) -> None:
    baseline = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation(
            "leaf-a", "leaf-b", source_digit="a",
            orphan_output=orphan_output,
            running_config_output=running_config_output,
        ),
        _nxos_observation(
            "leaf-b", "leaf-a", source_digit="b",
            orphan_output=orphan_output,
            running_config_output=running_config_output,
        ),
    ]})

    assert {row["health_state"] for row in baseline["local_observations"]} == {
        "not_verified"
    }
    delta = compute_multichassis_lag_delta(
        baseline, baseline, source_binding=_binding(baseline, baseline))
    _families, gate = _canonical_gate_for(delta, [])
    assert gate["verdict"] == "INDETERMINATE"


def test_closed_explicit_empty_orphan_response_remains_assessed() -> None:
    baseline = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation(
            "leaf-a", "leaf-b", source_digit="a",
            orphan_output="No vPC orphan ports\n",
        ),
        _nxos_observation(
            "leaf-b", "leaf-a", source_digit="b",
            orphan_output="No vPC orphan ports\n",
        ),
    ]})

    assert {row["health_state"] for row in baseline["local_observations"]} == {"healthy"}
    assert all(
        row["orphan_evidence"] == {
            "status": "assessed",
            "ports": [],
            "orphan_table_observed": True,
            "suspend_config_observed": True,
        }
        for row in baseline["local_observations"]
    )
    delta = compute_multichassis_lag_delta(
        baseline, baseline, source_binding=_binding(baseline, baseline))
    _families, gate = _canonical_gate_for(delta, [])
    assert gate["verdict"] == "PASS"


def test_declared_vpc_count_without_member_rows_cannot_authorize_clean_gate() -> None:
    baseline = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation(
            "leaf-a", "leaf-b", source_digit="a", attachment_id=None,
            declared_leg_count=1,
        ),
        _nxos_observation(
            "leaf-b", "leaf-a", source_digit="b", attachment_id=None,
            declared_leg_count=1,
        ),
    ]})

    assert {row["health_state"] for row in baseline["local_observations"]} == {
        "not_verified"
    }
    assert baseline["reconciled_attachments"] == []
    delta = compute_multichassis_lag_delta(
        baseline, baseline, source_binding=_binding(baseline, baseline))
    _families, gate = _canonical_gate_for(delta, [])
    assert gate["verdict"] == "INDETERMINATE"


def test_persisted_healthy_receipt_and_subject_scope_must_reconcile_exactly() -> None:
    observations = _nxos_pair()
    baseline = compute_multichassis_lag_domain_baseline(observations)
    tampered = copy.deepcopy(dict(baseline))
    for row in tampered["local_observations"]:
        row["source_receipt"]["capture_status"] = "incomplete"
        row["source_receipt"]["commands"].remove("show lacp neighbor")
    tampered["summary"]["baseline_sha256"] = ""
    tampered["summary"]["baseline_sha256"] = pa.canonical_sha256(tampered)

    validation = validate_multichassis_lag_domain_baseline(tampered)
    assert validation["valid"] is False
    assert validation["reason"] == "baseline_local_false_health"

    scope_tamper = copy.deepcopy(dict(baseline))
    scope_tamper["subject_scope"]["rows"] = []
    scope_tamper["subject_scope"]["summary"]["n_local_subjects"] = 0
    scope_tamper["subject_scope"]["summary"]["n_in_scope"] = 0
    scope_tamper["subject_scope"]["summary"]["scope_sha256"] = ""
    scope_tamper["subject_scope"]["summary"]["scope_sha256"] = pa.canonical_sha256(
        scope_tamper["subject_scope"]
    )
    scope_tamper["summary"]["baseline_sha256"] = ""
    scope_tamper["summary"]["baseline_sha256"] = pa.canonical_sha256(scope_tamper)
    reconciled = validate_multichassis_lag_snapshot_evidence(
        scope_tamper, observations, {"leaf-a": {}, "leaf-b": {}}
    )
    assert reconciled["valid"] is False
    assert reconciled["reason"] == (
        "stored_baseline_invalid:baseline_subject_scope_invalid"
    )


def test_delta_distinguishes_coverage_loss_appearance_disappearance_and_bad_binding() -> None:
    healthy = compute_multichassis_lag_domain_baseline(_nxos_pair())
    incomplete = compute_multichassis_lag_domain_baseline({"observations": [
        _nxos_observation("leaf-a", "leaf-b", source_digit="a"),
        _nxos_observation(
            "leaf-b", "leaf-a", source_digit="b", partner_system=None),
    ]})
    lost = compute_multichassis_lag_delta(
        healthy,
        incomplete,
        source_binding=_binding(healthy, incomplete),
    )
    attachment_change = next(
        row for row in lost["changes"] if row["record_type"] == "reconciled_attachment"
    )
    assert attachment_change["transition"] == "coverage_lost"
    assert attachment_change["assurance_level"] == "not_verified"
    assert attachment_change["decision_effect"] == "not_verified"

    expanded = compute_multichassis_lag_domain_baseline(_nxos_pair(extra_legs=[{
        "attachment_id": "30",
        "local_port_channel": "Po30",
        "status": "up",
        "consistency": "success",
        "lacp_partner_system_id": "00ff.eedd.ccbb",
        "lacp_partner_aggregation_id": "60",
    }]))
    appeared = compute_multichassis_lag_delta(
        healthy,
        expanded,
        source_binding=_binding(healthy, expanded),
    )
    disappeared = compute_multichassis_lag_delta(
        expanded,
        healthy,
        source_binding=_binding(expanded, healthy),
    )
    assert appeared["summary"]["by_transition"]["appeared"] == 3
    assert disappeared["summary"]["by_transition"]["disappeared"] == 3

    bad_binding = _binding(healthy, expanded)
    bad_binding["after_baseline_sha256"] = f"sha256:{'f' * 64}"
    not_comparable = compute_multichassis_lag_delta(
        healthy,
        expanded,
        source_binding=bad_binding,
    )
    assert not_comparable["changes"] == []
    assert not_comparable["assurance_level"] == "not_verified"
    assert not_comparable["summary"]["by_transition"]["not_comparable"] == 1
    assert any("after baseline digest" in failure for failure in not_comparable["comparison_failures"])


def test_empty_typed_baselines_abstain_instead_of_vacuously_clearing() -> None:
    empty = compute_multichassis_lag_domain_baseline({"observations": []})

    result = compute_multichassis_lag_delta(
        empty, empty, source_binding=_binding(empty, empty))

    assert result["changes"] == []
    assert result["assurance_level"] == "not_verified"
    assert result["summary"]["by_transition"]["not_comparable"] == 1
    assert any("no typed local" in item for item in result["comparison_failures"])
