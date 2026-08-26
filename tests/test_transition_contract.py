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
    assert {item.value for item in tc.TransitionKind} == {
        "FORWARD", "ROLLBACK", "RETRY", "SUPERSESSION", "COMPENSATION",
    }
    assert {item.value for item in tc.ObligationKind} == {
        "PRECONDITION", "REQUIRED_CHANGE", "PERMITTED_CHANGE", "FRAME_CONDITION",
        "INVARIANT", "POSTCONDITION", "TEMPORAL_OBLIGATION", "ROLLBACK_OBLIGATION",
    }
    assert {item.value for item in tc.TemporalOperator} == {
        "AT_SAMPLE", "ALWAYS_DURING", "NEVER_DURING", "EVENTUALLY_WITHIN",
        "ON_REQUIRE_WITHIN", "HOLD", "UNTIL", "SAMPLED_NO_VIOLATION_DURING",
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
        (("evolution_ir", "obligations", 0, "obligation_kind"), "OPTIONAL_HINT"),
        (("evolution_ir", "transition_kind"), "REORDERED_UPLOAD"),
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


@pytest.mark.parametrize(
    "field",
    (
        "predecessor_edges",
        "transition_kind",
        "precondition_obligation_ids",
        "required_change_obligation_ids",
        "permitted_change_obligation_ids",
        "invariant_obligation_ids",
        "postcondition_obligation_ids",
        "temporal_obligation_ids",
        "covered_frame_domain",
        "compensation_plan",
        "rollback_horizon",
        "irreversibility_conditions",
        "exceptions",
        "decision_receipts",
    ),
)
def test_canonical_transition_tuple_fields_cannot_be_omitted(field: str) -> None:
    case = minimal_transition_case()
    case["evolution_ir"].pop(field)
    _assert_refused(case, "CLOSED_SCHEMA_KEYS")


def test_frame_claim_cannot_expand_to_nothing_else_changed() -> None:
    case = minimal_transition_case()
    case["evolution_ir"]["covered_frame_domain"]["claim"] = "NOTHING_ELSE_CHANGED"
    _assert_refused(case, "FRAME_CLAIM_WORDING_REQUIRED")


def test_contract_index_must_exactly_partition_typed_obligations() -> None:
    case = minimal_transition_case()
    case["evolution_ir"]["temporal_obligation_ids"] = []
    _assert_refused(case, "CONTRACT_INDEX_MUST_PARTITION_OBLIGATIONS")


def test_nonforward_transition_requires_the_matching_predecessor_relation() -> None:
    case = minimal_transition_case()
    case["evolution_ir"]["transition_kind"] = tc.TransitionKind.RETRY.value
    _assert_refused(case, "TRANSITION_KIND_PREDECESSOR_RELATION_REQUIRED")


@pytest.mark.parametrize(
    ("operator", "updates", "code"),
    (
        (tc.TemporalOperator.ON_REQUIRE_WITHIN.value, {}, "TRIGGERED_WITHIN_BOUNDS_REQUIRED"),
        (tc.TemporalOperator.HOLD.value, {}, "HOLD_STABLE_DURATION_REQUIRED"),
        (tc.TemporalOperator.UNTIL.value, {}, "UNTIL_EVENT_AND_ROLLBACK_CONDITION_REQUIRED"),
        (
            tc.TemporalOperator.AT_SAMPLE.value,
            {"stable_duration_ms": 1},
            "TEMPORAL_OPERATOR_PARAMETERS_FORBIDDEN",
        ),
    ),
)
def test_temporal_operator_parameters_fail_closed(
        operator: str, updates: dict[str, object], code: str) -> None:
    case = minimal_transition_case()
    obligation = case["evolution_ir"]["obligations"][0]
    obligation["temporal_operator"] = operator
    obligation.update(updates)
    _assert_refused(case, code)


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
