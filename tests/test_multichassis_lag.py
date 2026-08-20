from __future__ import annotations

import copy

import pytest

from cisco_toolkit.multichassis_lag import (
    MULTICHASSIS_LAG_DELTA_SCHEMA,
    MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA,
    MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA,
    MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA,
    compute_multichassis_lag_delta,
    compute_multichassis_lag_domain_baseline,
    compute_multichassis_lag_subject_scope,
    multichassis_lag_support_profile,
    validate_multichassis_lag_domain_baseline,
)
from cisco_toolkit.protocol_assurance import ASSURANCE_LEVELS, CHANGE_VOCABULARY


def _source(hex_digit: str, *, capture: str = "ok", custody: str = "current_run_source_bound") -> dict:
    return {
        "schema": MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA,
        "capture_status": capture,
        "projection_custody": custody,
        "source_sha256": f"sha256:{hex_digit * 64}",
        "owner_version": "typed-fixture-v1",
        "commands": ["show vpc", "show lacp neighbor"],
    }


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
    return {
        "switch": switch,
        "vendor": "cisco",
        "platform": "nxos",
        "collection_mode": collection_mode,
        "peer_identity": peer,
        "domain_id": domain_id,
        "domain_state": {
            "peer_status": "peer adjacency formed ok",
            "keepalive_status": "peer is alive",
            "consistency": "success",
            "peer_link_status": "up",
        },
        "source": _source(source_digit),
        "legs": legs,
    }


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
) -> dict:
    legs = []
    if attachment_id is not None:
        legs.append(
            {
                "attachment_id": attachment_id,
                "local_port_channel": "Port-Channel20",
                "status": "up",
                "consistency": "success",
                "lacp_partner_system_id": partner_system,
                "lacp_partner_aggregation_id": partner_aggregation,
            }
        )
    return {
        "switch": switch,
        "vendor": "arista",
        "platform": "eos",
        "collection_mode": collection_mode,
        "peer_identity": peer,
        "domain_id": domain_id,
        "domain_state": {
            "state": "active",
            "neg_status": "connected",
            "config_sanity": "consistent",
            "peer_link_status": "up",
            "local_intf_status": "up",
        },
        "source": _source(source_digit),
        "legs": legs,
    }


def _nxos_pair(*, domain_id: str = "10") -> dict:
    return {
        "observations": [
            _nxos_observation("leaf-a", "leaf-b", source_digit="a", domain_id=domain_id),
            _nxos_observation("leaf-b", "leaf-a", source_digit="b", domain_id=domain_id),
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


def test_support_profile_and_subject_scope_are_closed_and_total() -> None:
    profile = multichassis_lag_support_profile()
    assert profile["owner_schema"] == MULTICHASSIS_LAG_DELTA_SCHEMA
    assert profile["assurance_level"] == "intent_reconciled_survival"
    assert profile["variants"] == [
        {
            "vendor": "cisco",
            "platform": "nxos",
            "collection_modes": ["live", "offline"],
            "required_typed_evidence": [
                "vpc_domain_state",
                "explicit_peer_identity",
                "lacp_partner_identity",
            ],
        },
        {
            "vendor": "arista",
            "platform": "eos",
            "collection_modes": ["offline"],
            "required_typed_evidence": [
                "mlag_domain_state",
                "explicit_peer_identity",
                "lacp_partner_identity",
            ],
        },
    ]
    assert any("No IOS" in limitation for limitation in profile["limitations"])

    scope = compute_multichassis_lag_subject_scope(_nxos_pair())
    assert scope["schema"] == MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA
    _assert_no_overall_decision(scope)
    assert scope["summary"]["n_in_scope"] == 2
    assert {row["source_custody"] for row in scope["rows"]} == {"current_run_source_bound"}

    unsupported = _eos_pair()
    unsupported["observations"][0]["collection_mode"] = "live"
    unsupported_scope = compute_multichassis_lag_subject_scope(unsupported)
    assert unsupported_scope["summary"]["n_not_verified"] == 1
    assert unsupported_scope["rows"][0]["status"] == "not_verified"

    for malformed in (None, [], "typed", {"observations": [None]}):
        candidate_scope = compute_multichassis_lag_subject_scope(malformed)
        baseline = compute_multichassis_lag_domain_baseline(malformed)
        assert candidate_scope["schema"] == MULTICHASSIS_LAG_SUBJECT_SCOPE_SCHEMA
        assert baseline["schema"] == MULTICHASSIS_LAG_DOMAIN_BASELINE_SCHEMA
        assert baseline["summary"]["by_health_state"]["healthy"] == 0
        assert validate_multichassis_lag_domain_baseline(baseline)["valid"] is True


@pytest.mark.parametrize("fixture", [_nxos_pair, _eos_pair])
def test_reciprocal_pair_and_attachment_require_complete_typed_evidence(fixture) -> None:
    baseline = compute_multichassis_lag_domain_baseline(fixture())
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
    assert baseline["reciprocal_peer_pairs"][0]["health_state"] == expected_state
    assert baseline["reconciled_attachments"][0]["health_state"] == expected_state


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

    degraded_input = _nxos_pair()
    degraded_input["observations"][1]["legs"][0]["status"] = "down"
    degraded = compute_multichassis_lag_domain_baseline(degraded_input)
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

    changed_input = _nxos_pair()
    for observation in changed_input["observations"]:
        observation["legs"][0]["lacp_partner_system_id"] = "00aa.bbcc.ddee"
        observation["legs"][0]["lacp_partner_aggregation_id"] = "84"
    changed = compute_multichassis_lag_domain_baseline(changed_input)
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


def test_delta_distinguishes_coverage_loss_appearance_disappearance_and_bad_binding() -> None:
    healthy = compute_multichassis_lag_domain_baseline(_nxos_pair())
    incomplete_input = _nxos_pair()
    incomplete_input["observations"][1]["legs"][0].pop("lacp_partner_system_id")
    incomplete = compute_multichassis_lag_domain_baseline(incomplete_input)
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

    expanded_input = _nxos_pair()
    for index, observation in enumerate(expanded_input["observations"]):
        observation["legs"].append(
            {
                "attachment_id": "30",
                "local_port_channel": "Po30",
                "status": "up",
                "consistency": "success",
                "lacp_partner_system_id": "00ff.eedd.ccbb",
                "lacp_partner_aggregation_id": "60",
            }
        )
        observation["source"] = _source("c" if index == 0 else "d")
    expanded = compute_multichassis_lag_domain_baseline(expanded_input)
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
