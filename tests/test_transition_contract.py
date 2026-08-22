"""Structural and adversarial contract tests for Atlas Release 2 R2.0."""

from __future__ import annotations

from copy import deepcopy

import pytest

from cisco_toolkit import transition_contract as tc
from tests.transition_fixtures import (
    EXPERIMENTAL_QCP_001_QUALIFICATION,
    minimal_transition_case,
)


def _set_path(value: dict, path: tuple[str | int, ...], replacement: object) -> None:
    cursor: object = value
    for component in path[:-1]:
        cursor = cursor[component]  # type: ignore[index]
    cursor[path[-1]] = replacement  # type: ignore[index]


def _assert_refused(case: dict, code: str) -> tc.TransitionContractError:
    with pytest.raises(tc.TransitionContractError) as caught:
        tc.validate_transition_case(case)
    assert caught.value.code == code
    return caught.value


def test_minimal_experimental_qcp_001_case_validates_and_binds_exact_bytes() -> None:
    case = minimal_transition_case()
    assert tc.validate_transition_case(case) == case
    assert EXPERIMENTAL_QCP_001_QUALIFICATION["qualification_state"] == "EXPERIMENTAL"
    assert case["pack_binding"]["pack_id"] == "QCP-001"
    assert case["pack_binding"]["pack_version"].endswith("-experimental")

    raw = tc.canonical_json_bytes(case)
    bound = tc.bind_transition_case_bytes(raw)

    assert dict(bound) == case
    assert bound.source_digest == tc.bytes_digest(raw)
    assert bound.payload_digest == bound.source_digest
    assert bound.source_bytes == len(raw)
    assert tc.require_bound_transition_case(bound) is bound


def test_binding_rejects_detached_noncanonical_and_mutated_cases() -> None:
    case = minimal_transition_case()
    raw = tc.canonical_json_bytes(case)

    with pytest.raises(tc.TransitionContractError) as caught:
        tc.require_bound_transition_case(case)
    assert caught.value.code == "DETACHED_TRANSITION_CASE"

    with pytest.raises(tc.TransitionContractError) as caught:
        tc.bind_transition_case_bytes(raw + b"\n")
    assert caught.value.code == "CANONICAL_BYTES_REQUIRED"

    bound = tc.bind_transition_case_bytes(raw)
    bound["case_id"] = "case.QCP-001.EXPERIMENTAL.mutated"
    with pytest.raises(tc.TransitionContractError) as caught:
        tc.require_bound_transition_case(bound)
    assert caught.value.code == "BOUND_TRANSITION_CASE_MUTATED"


def test_canonical_encoding_is_deterministic_across_mapping_insertion_order() -> None:
    case = minimal_transition_case()
    reordered = {key: deepcopy(case[key]) for key in reversed(tuple(case))}

    first = tc.canonical_json_bytes(case)
    second = tc.canonical_json_bytes(reordered)

    assert first == second
    assert tc.canonical_digest(case) == tc.canonical_digest(reordered)
    assert tc.bind_transition_case_bytes(first).payload_digest == tc.bind_transition_case_bytes(
        second
    ).payload_digest


def test_authoritative_contract_enums_are_exact_closed_sets() -> None:
    assert {item.value for item in tc.CaseMode} == {
        "SEALED_PORTABLE", "REFERENCED", "PROJECTION_ONLY",
    }
    assert {item.value for item in tc.EvidenceClass} == {
        "observed", "declared", "derived", "simulated", "assumed", "human-accepted",
    }
    assert {item.value for item in tc.ObservationMode} == {
        "SAMPLED", "EVENT_COMPLETE", "BOUNDED_MODEL",
    }
    assert {item.value for item in tc.TemporalOutcome} == {
        "SATISFIED_WITHIN_DECLARED_MODEL",
        "NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE",
        "VIOLATED",
        "INCONCLUSIVE",
    }
    assert {item.value for item in tc.EvidenceStatus} == {
        "SUPPORTED", "REFUTED", "CONFLICTING", "UNKNOWN",
    }
    assert {item.value for item in tc.ApplicabilityKind} == {
        "NOT_APPLICABLE", "APPLICABILITY_EVIDENCE_REQUIRED", "APPLICABLE",
    }
    assert {item.value for item in tc.QualificationState} == {
        "EXPERIMENTAL", "QUALIFIED", "EXPIRED", "REVOKED",
    }
    assert {item.value for item in tc.AuthoritativeGate} == {
        "OBSERVED_BREACH",
        "CONFLICT_REQUIRES_RESOLUTION",
        "EVIDENCE_INCOMPLETE",
        "ELIGIBLE_FOR_HUMAN_DECISION",
    }
    assert tuple(item.value for item in tc.RollbackDimension) == tc.ROLLBACK_DIMENSIONS


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("case_mode",), "PORTABLE"),
        (("evolution_ir", "obligations", 0, "temporal_operator"), "EVENTUALLY"),
        (("observation_profiles", 0, "coverage_mode"), "CONTINUOUS"),
        (("evidence_atoms", 0, "evidence_class"), "inferred"),
        (("applicability", "kind"), "DRAFT"),
        (("derivations", 0, "effect"), "PASS"),
        (("derivations", 0, "temporal_outcome"), "PASS"),
        (("derivations", 0, "evaluator_kind"), "PYTHON_PLUGIN"),
    ),
)
def test_unknown_enum_values_fail_closed(
        path: tuple[str | int, ...], replacement: object) -> None:
    case = minimal_transition_case()
    _set_path(case, path, replacement)
    _assert_refused(case, "UNKNOWN_ENUM_VALUE")


@pytest.mark.parametrize(
    "path",
    (
        (),
        ("evidence_atoms", 0),
        ("version_contract",),
    ),
)
def test_unknown_fields_fail_closed(path: tuple[str | int, ...]) -> None:
    case = minimal_transition_case()
    cursor: object = case
    for component in path:
        cursor = cursor[component]  # type: ignore[index]
    cursor["future_authority"] = "ELIGIBLE"  # type: ignore[index]

    refusal = _assert_refused(case, "CLOSED_SCHEMA_KEYS")
    assert "future_authority" not in str(refusal)


def test_caller_cannot_supply_or_forge_qualification_state() -> None:
    case = minimal_transition_case()
    case["applicability"]["qualification_state"] = "QUALIFIED"

    refusal = _assert_refused(case, "CLOSED_SCHEMA_KEYS")
    assert refusal.path == "$.applicability"
    assert "QUALIFIED" not in str(refusal)


@pytest.mark.parametrize(
    ("path", "replacement", "code"),
    (
        (("created_at",), "2026-08-22T00:00:06Z", "TIMESTAMP_CANONICAL_UTC_REQUIRED"),
        (
            ("evidence_atoms", 0, "observed_time_interval", "start_inclusive"),
            "2026-08-22T00:00:02.000001Z",
            "TIME_INTERVAL_REVERSED",
        ),
        (
            ("evidence_atoms", 0, "collected_at"),
            "2026-08-22T00:00:01.500000Z",
            "EVIDENCE_TIME_ORDER_INVALID",
        ),
        (
            ("evidence_atoms", 0, "received_at"),
            "2026-08-22T00:00:02.500000Z",
            "EVIDENCE_TIME_ORDER_INVALID",
        ),
    ),
)
def test_time_contract_rejects_noncanonical_reversed_or_impossible_order(
        path: tuple[str | int, ...], replacement: str, code: str) -> None:
    case = minimal_transition_case()
    _set_path(case, path, replacement)
    _assert_refused(case, code)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("engagement_id", "engagement.alien"),
        ("campaign_id", "campaign.alien"),
        ("pair_id", "pair.alien"),
        ("before_snapshot_digest", tc.canonical_digest({"alien": "before"})),
        ("after_snapshot_digest", tc.canonical_digest({"alien": "after"})),
        ("protocol_id", "stp"),
        ("direction", "target-to-legacy"),
        ("scenario_id", "scenario.alien"),
        ("wave_id", "wave.999"),
        ("transition_id", "transition.alien"),
        ("trial_attempt_id", "attempt.alien"),
    ),
)
def test_one_field_identity_teleportation_is_rejected(field: str, replacement: str) -> None:
    case = minimal_transition_case()
    case["evidence_atoms"][0]["transition_identity"][field] = replacement

    refusal = _assert_refused(case, "EVIDENCE_TELEPORTATION")
    assert refusal.path == "$.evidence_atoms[0].transition_identity"


def test_observation_qualification_denominator_requires_a_nonempty_subject_scope() -> None:
    denominator = next(
        item for item in minimal_transition_case()["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator["subject_ids"] = []

    with pytest.raises(tc.TransitionContractError) as caught:
        tc.validate_qualification_denominator(denominator, "$")
    assert caught.value.code == "OBSERVATION_DENOMINATOR_SCOPE_REQUIRED"


@pytest.mark.parametrize(
    ("denominator_kind", "updates", "code"),
    (
        ("EXACT_EVENTS", {}, "EXACT_EVENTS_INVENTORY_REQUIRED"),
        ("EXACT_MODEL_BOUND", {}, "EXACT_MODEL_PREIMAGE_REQUIRED"),
        (
            "EXACT_SUBJECTS",
            {"event_inventory_digest": tc.canonical_digest({"events": "forbidden"})},
            "DENOMINATOR_PREIMAGE_FIELD_FORBIDDEN",
        ),
    ),
)
def test_event_and_model_denominators_require_inspectable_preimages(
        denominator_kind: str,
        updates: dict[str, object],
        code: str) -> None:
    denominator = next(
        item for item in minimal_transition_case()["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator["denominator_kind"] = denominator_kind
    denominator.update(updates)

    with pytest.raises(tc.TransitionContractError) as caught:
        tc.validate_qualification_denominator(denominator, "$")
    assert caught.value.code == code


def test_wording_policy_is_content_bound_and_contains_no_autonomous_approval() -> None:
    policy = tc.assurance_wording_policy()
    assert policy["version"] == tc.WORDING_POLICY_VERSION
    assert policy["human_decision_required"] is True
    assert policy["autonomous_go"] is False
    assert tc.wording_policy_digest() == tc.canonical_digest(policy)
    assert tc.gate_wording(
        "AUTHORITATIVE_GATE",
        tc.AuthoritativeGate.ELIGIBLE_FOR_HUMAN_DECISION.value,
    )["statement"].endswith("This is not approval or autonomous GO.")

    dependency = next(
        item for item in minimal_transition_case()["version_contract"]["dependency_digests"]
        if item["kind"] == "WORDING_POLICY"
    )
    assert dependency == {
        "kind": "WORDING_POLICY",
        "identifier": tc.WORDING_POLICY_VERSION,
        "digest": tc.wording_policy_digest(),
    }
    with pytest.raises(tc.TransitionContractError) as caught:
        tc.gate_wording("AUTHORITATIVE_GATE", "GO")
    assert caught.value.code == "WORDING_GATE_PAIR_INVALID"
