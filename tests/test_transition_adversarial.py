"""Adversarial R2.0 tests for the canonical TransitionCase boundary.

These tests intentionally build a complete case locally.  That keeps the hostile-byte and
cross-binding tests useful even when shared fixture helpers are unavailable, and ensures every
mutation reaches the real whole-case validator rather than a mocked sub-validator.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from cisco_toolkit import transition_contract as tc


def _digest(label: str) -> str:
    return tc.bytes_digest(label.encode("utf-8"))


def _interval(
    start: str = "2026-08-22T00:00:00.000000Z",
    end: str = "2026-08-22T00:01:00.000000Z",
) -> dict[str, str]:
    return {"start_inclusive": start, "end_inclusive": end}


def _content_binding(
    role: str,
    digest: str,
    mode: str,
    index: int,
) -> dict[str, Any]:
    if mode == tc.CaseMode.SEALED_PORTABLE.value:
        location, resolver = "EMBEDDED", None
    elif mode == tc.CaseMode.REFERENCED.value:
        location, resolver = "EXTERNAL", f"resolver.{index}"
    else:
        location, resolver = "PROJECTION", None
    return {
        "schema": tc.OBJECT_BINDING_SCHEMA,
        "role": role,
        "digest": digest,
        "location": location,
        "resolver_id": resolver,
        "required": True,
    }


def _case(mode: str = tc.CaseMode.REFERENCED.value) -> dict[str, Any]:
    identity = {
        "schema": tc.TRANSITION_IDENTITY_SCHEMA,
        "engagement_id": "engagement.1",
        "campaign_id": "campaign.1",
        "pair_id": "pair.1",
        "before_snapshot_digest": _digest("before snapshot"),
        "after_snapshot_digest": _digest("after snapshot"),
        "protocol_id": "fhrp.hsrp",
        "direction": "forward",
        "scenario_id": "gateway.handoff",
        "wave_id": "wave.1",
        "transition_id": "transition.1",
        "trial_attempt_id": "attempt.1",
    }
    window = _interval()
    semantic_digest = _digest("experimental semantic bundle")
    qualification_denominators = [
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.qcp-001.applicability",
            "subject_kind": "APPLICABILITY_PROFILE",
            "subject_id": "qcp-001",
            "subject_version": "1",
            "denominator_kind": "APPLICABILITY_SCOPE",
            "subject_ids": ["vlan.10"],
            "predicate_ids": [],
            "window": deepcopy(window),
            "platform_release_ids": ["fixture.platform-release"],
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        },
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.qcp-001.observation",
            "subject_kind": "OBSERVATION_PROFILE",
            "subject_id": "sampled.profile.1",
            "subject_version": "1",
            "denominator_kind": "EXACT_SUBJECTS",
            "subject_ids": ["vlan.10"],
            "predicate_ids": ["gateway.owner"],
            "window": deepcopy(window),
            "platform_release_ids": [],
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        },
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.qcp-001.pack",
            "subject_kind": "BEHAVIOR_PACK",
            "subject_id": "qcp-001",
            "subject_version": "0.1.0-experimental",
            "denominator_kind": "PACK_SUPPORTED_SCOPE",
            "subject_ids": ["vlan.10"],
            "predicate_ids": ["gateway.owner"],
            "window": deepcopy(window),
            "platform_release_ids": ["fixture.platform-release"],
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        },
    ]
    denominator_digests = {
        item["subject_kind"]: tc.canonical_digest(item)
        for item in qualification_denominators
    }
    observation_profile = {
        "schema": tc.OBSERVATION_PROFILE_SCHEMA,
        "profile_id": "sampled.profile.1",
        "source_kind": "atlas.snapshot",
        "coverage_mode": tc.ObservationMode.SAMPLED.value,
        "predicate_ids": ["gateway.owner"],
        "window": deepcopy(window),
        "planned_cadence_ms": 1_000,
        "observed_maximum_gap_ms": 1_200,
        "clock_error_bound_ms": 100,
        "collection_completeness": "INCOMPLETE",
        "detection_latency_bound_ms": None,
        "cross_device_overlap_rule": "NOT_APPLICABLE",
        "start_end_coverage": "BOTH",
        "missing_sample_policy": "INCONCLUSIVE",
        "qualification_denominator_digest": denominator_digests["OBSERVATION_PROFILE"],
        "qualification_receipt_digest": None,
    }
    observation_profile_digest = tc.canonical_digest(observation_profile)
    obligation = {
        "schema": tc.OBLIGATION_SCHEMA,
        "obligation_id": "obligation.1",
        "requirement_id": "requirement.1",
        "predicate_id": "gateway.owner",
        "subject_ids": ["vlan.10"],
        "state_ids": ["state.target"],
        "temporal_operator": tc.TemporalOperator.SAMPLED_NO_VIOLATION_DURING.value,
        "mandatory": True,
        "window": deepcopy(window),
        "observation_profile_digest": observation_profile_digest,
        "semantic_profile_digest": semantic_digest,
        "accepted_evidence_classes": [tc.EvidenceClass.OBSERVED.value],
        "rollback_dimension": None,
    }
    evidence_digest = _digest("observed evidence")
    evidence = {
        "schema": tc.EVIDENCE_ATOM_SCHEMA,
        "evidence_id": "evidence.1",
        "artifact_digest": evidence_digest,
        "transition_identity": deepcopy(identity),
        "subject_id": "vlan.10",
        "state_id": "state.target",
        "predicate_id": "gateway.owner",
        "value": {"owner": "gateway.target"},
        "observed_time_interval": _interval(
            "2026-08-22T00:00:01.000000Z",
            "2026-08-22T00:00:02.000000Z",
        ),
        "collected_at": "2026-08-22T00:00:03.000000Z",
        "received_at": "2026-08-22T00:00:04.000000Z",
        "sealed_at": "2026-08-22T00:00:05.000000Z",
        "evidence_class": tc.EvidenceClass.OBSERVED.value,
        "acquisition_method": "offline.capture",
        "observation_profile_digest": observation_profile_digest,
        "semantic_profile_digest": semantic_digest,
        "coverage_scope": {
            "schema": tc.COVERAGE_SCOPE_SCHEMA,
            "denominator_kind": "EXACT_SUBJECTS",
            "subject_ids": ["vlan.10"],
            "predicate_ids": ["gateway.owner"],
            "window": deepcopy(window),
            "complete": False,
        },
        "transform_chain": [],
    }
    applicability_receipt = _digest("qcp-001 experimental qualification receipt")
    pack_manifest = _digest("experimental pack manifest")
    tcb_manifest = _digest("experimental tcb manifest")
    verifier_bootstrap = _digest("independent verifier bootstrap")
    trust_policy = _digest("external trust policy")
    replay_recipe = _digest("replay recipe")
    binding_specs = sorted(
        [
            ("EVIDENCE", evidence_digest),
            ("PACK_MANIFEST", pack_manifest),
            ("QUALIFICATION_RECEIPT", applicability_receipt),
            ("REPLAY_RECIPE", replay_recipe),
            ("SEMANTIC_BUNDLE", semantic_digest),
            ("STATE_SNAPSHOT", identity["after_snapshot_digest"]),
            ("STATE_SNAPSHOT", identity["before_snapshot_digest"]),
            ("TCB_MANIFEST", tcb_manifest),
            ("TRUST_SNAPSHOT", trust_policy),
            ("VERIFIER_BOOTSTRAP", verifier_bootstrap),
        ]
    )
    bindings = [
        _content_binding(role, digest, mode, index)
        for index, (role, digest) in enumerate(binding_specs)
    ]
    return {
        "schema": tc.TRANSITION_CASE_SCHEMA,
        "case_id": "case.1",
        "case_mode": mode,
        "created_at": "2026-08-22T00:00:06.000000Z",
        "transition_identity": identity,
        "evolution_ir": {
            "schema": tc.EVOLUTION_IR_SCHEMA,
            "ir_version": tc.EVOLUTION_IR_VERSION,
            "transition_identity": deepcopy(identity),
            "from_state_id": "state.current",
            "to_state_id": "state.target",
            "intermediate_state_ids": [],
            "subject_ids": ["vlan.10"],
            "trigger_ids": ["change.1"],
            "obligations": [obligation],
            "rollback_dimensions": list(tc.ROLLBACK_DIMENSIONS),
        },
        "observation_profiles": [observation_profile],
        "qualification_denominators": qualification_denominators,
        "evidence_atoms": [evidence],
        "applicability": {
            "schema": tc.APPLICABILITY_SCHEMA,
            "kind": tc.ApplicabilityKind.APPLICABLE.value,
            "reason_codes": [],
            "profile_id": "qcp-001",
            "profile_digest": _digest("qcp-001 experimental profile"),
            "supported_denominator_digest": denominator_digests["APPLICABILITY_PROFILE"],
            "qualification_receipt_digest": applicability_receipt,
        },
        "pack_binding": {
            "schema": tc.PACK_BINDING_SCHEMA,
            "pack_id": "qcp-001",
            "pack_version": "0.1.0-experimental",
            "pack_manifest_digest": pack_manifest,
            "tcb_manifest_digest": tcb_manifest,
            "semantic_bundle_digest": semantic_digest,
            "pack_qualification_receipt_digest": None,
            "abi_version": tc.PACK_ABI_VERSION,
        },
        "derivations": [
            {
                "schema": tc.DERIVATION_SCHEMA,
                "derivation_id": "derivation.1",
                "obligation_id": "obligation.1",
                "evidence_ids": ["evidence.1"],
                "effect": tc.EvidenceEffect.SUPPORT.value,
                "temporal_outcome": tc.TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value,
                "evaluator_kind": tc.EvaluatorKind.STRUCTURAL_DECLARATIVE.value,
                "evaluator_digest": semantic_digest,
                "certificate_digest": None,
                "reason_codes": ["sampled.trace.only"],
            }
        ],
        "replay_contract": {
            "schema": tc.REPLAY_CONTRACT_SCHEMA,
            "mode": mode,
            "object_bindings": bindings,
            "verifier_bootstrap_digest": verifier_bootstrap,
            "trust_policy_digest": trust_policy,
            "replay_recipe_digest": replay_recipe,
        },
        "security_contract": {
            "schema": tc.SECURITY_CONTRACT_SCHEMA,
            "classification": "INTERNAL",
            "evidence_protection": "CONTRACT_ONLY",
            "recipient_policy_digest": None,
            "encryption_profile_digest": None,
            "redaction_profile_digest": None,
            "key_policy_digest": None,
            "retention_policy_digest": _digest("retention policy"),
        },
        "version_contract": {
            "schema": tc.VERSION_CONTRACT_SCHEMA,
            "contract_version": tc.CONTRACT_VERSION,
            "canonical_encoding": tc.CANONICAL_ENCODING,
            "semantic_version": tc.TRANSITION_SEMANTICS_VERSION,
            "pack_abi_version": tc.PACK_ABI_VERSION,
            "wording_policy_version": tc.WORDING_POLICY_VERSION,
            "migration_policy": "REFERENCE_NOT_REWRITE",
            "invalidation_policy": "DIGEST_CHANGE_INVALIDATES_DEPENDENTS",
            "replay_policy": "PINNED_SEMANTICS_EXACT_BYTES",
            "qualification_policy": "EXTERNAL_TRUST_POLICY_AT_EVALUATION_TIME",
            "legacy_semantics_digest": None,
            "dependency_digests": [
                {
                    "kind": "PACK",
                    "identifier": "qcp-001",
                    "digest": pack_manifest,
                },
                {
                    "kind": "QUALIFICATION_DENOMINATOR",
                    "identifier": "denominator.qcp-001.applicability",
                    "digest": denominator_digests["APPLICABILITY_PROFILE"],
                },
                {
                    "kind": "QUALIFICATION_DENOMINATOR",
                    "identifier": "denominator.qcp-001.observation",
                    "digest": denominator_digests["OBSERVATION_PROFILE"],
                },
                {
                    "kind": "QUALIFICATION_DENOMINATOR",
                    "identifier": "denominator.qcp-001.pack",
                    "digest": denominator_digests["BEHAVIOR_PACK"],
                },
                {
                    "kind": "SEMANTIC_PROFILE",
                    "identifier": "qcp-001",
                    "digest": semantic_digest,
                },
                {
                    "kind": "TCB",
                    "identifier": "qcp-001",
                    "digest": tcb_manifest,
                },
                {
                    "kind": "WORDING_POLICY",
                    "identifier": tc.WORDING_POLICY_VERSION,
                    "digest": tc.wording_policy_digest(),
                },
            ],
        },
    }


def _assign(root: Any, path: tuple[str | int, ...], value: Any) -> None:
    cursor = root
    for component in path[:-1]:
        cursor = cursor[component]
    cursor[path[-1]] = value


def _rebind_observation_profile(case: dict[str, Any]) -> None:
    profile_digest = tc.canonical_digest(case["observation_profiles"][0])
    case["evolution_ir"]["obligations"][0]["observation_profile_digest"] = profile_digest
    case["evidence_atoms"][0]["observation_profile_digest"] = profile_digest


def _rebind_observation_denominator(case: dict[str, Any]) -> None:
    denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator_digest = tc.canonical_digest(denominator)
    case["observation_profiles"][0]["qualification_denominator_digest"] = denominator_digest
    for dependency in case["version_contract"]["dependency_digests"]:
        if (
                dependency["kind"] == "QUALIFICATION_DENOMINATOR"
                and dependency["identifier"] == denominator["denominator_id"]
        ):
            dependency["digest"] = denominator_digest
    _rebind_observation_profile(case)


def _assert_error(error: pytest.ExceptionInfo[tc.TransitionContractError], code: str) -> None:
    assert error.value.code == code
    assert str(error.value) == f"{error.value.code} at {error.value.path}"


def test_complete_reference_case_is_canonical_and_exact_byte_bound() -> None:
    case = _case()
    assert tc.validate_transition_case(case) == case

    raw = tc.canonical_json_bytes(case)
    bound = tc.bind_transition_case_bytes(raw)

    assert bound.source_bytes == len(raw)
    assert bound.source_digest == tc.bytes_digest(raw) == bound.payload_digest
    assert tc.require_bound_transition_case(bound) is bound


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"a":1,"a":2}', "CANONICAL_DUPLICATE_KEY"),
        (b'{"nested":{"a":1,"a":2}}', "CANONICAL_DUPLICATE_KEY"),
        (b"1.0", "CANONICAL_FLOAT_FORBIDDEN"),
        (b"1e0", "CANONICAL_FLOAT_FORBIDDEN"),
        (b"NaN", "CANONICAL_NONFINITE_FORBIDDEN"),
        (b"Infinity", "CANONICAL_NONFINITE_FORBIDDEN"),
        (b"-Infinity", "CANONICAL_NONFINITE_FORBIDDEN"),
        (b"\xef\xbb\xbf{}", "CANONICAL_BOM_FORBIDDEN"),
        (b'"\xff"', "CANONICAL_INVALID_UTF8"),
        (b'"\\ud800"', "CANONICAL_INVALID_UNICODE"),
    ],
)
def test_hostile_json_bytes_are_rejected_with_fixed_non_echoing_codes(raw: bytes, code: str) -> None:
    with pytest.raises(tc.TransitionContractError) as error:
        tc.parse_canonical_json_bytes(raw)
    _assert_error(error, code)
    assert repr(raw) not in str(error.value)


@pytest.mark.parametrize("value", [0.0, -0.0, 1.5, float("inf"), float("nan")])
def test_in_memory_floats_and_nonfinite_values_are_never_coerced(value: float) -> None:
    with pytest.raises(tc.TransitionContractError) as error:
        tc.canonical_json_bytes({"value": value})
    _assert_error(error, "CANONICAL_UNSUPPORTED_TYPE")


def test_canonical_unicode_requires_valid_utf8_nfc_and_one_exact_spelling() -> None:
    composed = "\N{LATIN SMALL LETTER E WITH ACUTE}"
    decomposed = "e\N{COMBINING ACUTE ACCENT}"

    assert tc.canonical_json_bytes({"text": composed}) == b'{"text":"\\u00e9"}'
    with pytest.raises(tc.TransitionContractError) as value_error:
        tc.canonical_json_bytes({"text": decomposed})
    _assert_error(value_error, "CANONICAL_NON_NFC_STRING")
    with pytest.raises(tc.TransitionContractError) as key_error:
        tc.canonical_json_bytes({decomposed: "value"})
    _assert_error(key_error, "CANONICAL_NON_NFC_STRING")

    # Literal UTF-8 is semantically valid NFC but is not the one canonical byte spelling.
    with pytest.raises(tc.TransitionContractError) as spelling_error:
        tc.parse_canonical_json_bytes(b'{"text":"\xc3\xa9"}')
    _assert_error(spelling_error, "CANONICAL_BYTES_REQUIRED")


def test_portable_integer_boundary_is_closed_and_booleans_do_not_alias_integers() -> None:
    limit = tc.PORTABLE_INTEGER_LIMIT
    assert tc.parse_canonical_json_bytes(str(limit).encode("ascii")) == limit
    assert tc.parse_canonical_json_bytes(str(-limit).encode("ascii")) == -limit

    for hostile in (limit + 1, -limit - 1):
        with pytest.raises(tc.TransitionContractError) as encode_error:
            tc.canonical_json_bytes(hostile)
        _assert_error(encode_error, "CANONICAL_NON_PORTABLE_INTEGER")
        with pytest.raises(tc.TransitionContractError) as parse_error:
            tc.parse_canonical_json_bytes(str(hostile).encode("ascii"))
        _assert_error(parse_error, "CANONICAL_NON_PORTABLE_INTEGER")

    case = _case()
    case["observation_profiles"][0]["planned_cadence_ms"] = True
    with pytest.raises(tc.TransitionContractError) as bool_error:
        tc.validate_transition_case(case)
    _assert_error(bool_error, "EXPECTED_PORTABLE_INTEGER")


def test_authoritative_enum_denominators_have_no_fifth_status() -> None:
    assert {item.value for item in tc.AuthoritativeGate} == {
        "OBSERVED_BREACH",
        "CONFLICT_REQUIRES_RESOLUTION",
        "EVIDENCE_INCOMPLETE",
        "ELIGIBLE_FOR_HUMAN_DECISION",
    }
    assert {item.value for item in tc.TemporalOutcome} == {
        "SATISFIED_WITHIN_DECLARED_MODEL",
        "NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE",
        "VIOLATED",
        "INCONCLUSIVE",
    }
    assert {item.value for item in tc.EvidenceStatus} == {
        "SUPPORTED",
        "REFUTED",
        "CONFLICTING",
        "UNKNOWN",
    }
    for enum_type, hostile in (
        (tc.AuthoritativeGate, "GO"),
        (tc.TemporalOutcome, "PROVEN"),
        (tc.EvidenceStatus, "PARTIAL"),
    ):
        with pytest.raises(ValueError):
            enum_type(hostile)


@pytest.mark.parametrize(
    ("path", "hostile"),
    [
        (("case_mode",), "PORTABLE_ENOUGH"),
        (("observation_profiles", 0, "coverage_mode"), "CONTINUOUS"),
        (("evidence_atoms", 0, "evidence_class"), "certified"),
        (("derivations", 0, "temporal_outcome"), "PROVEN"),
        (("derivations", 0, "effect"), "PARTIAL_SUPPORT"),
    ],
)
def test_unknown_structural_enums_fail_closed(path: tuple[str | int, ...], hostile: str) -> None:
    case = _case()
    _assign(case, path, hostile)
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "UNKNOWN_ENUM_VALUE")


def test_sampled_profile_represents_continuous_obligation_only_as_inconclusive() -> None:
    case = _case()
    case["observation_profiles"][0]["collection_completeness"] = "COMPLETE"
    _rebind_observation_profile(case)
    case["evolution_ir"]["obligations"][0]["temporal_operator"] = (
        tc.TemporalOperator.ALWAYS_DURING.value
    )
    case["derivations"][0]["temporal_outcome"] = tc.TemporalOutcome.INCONCLUSIVE.value
    case["derivations"][0]["reason_codes"] = ["sampled.continuous.inconclusive"]

    checked = tc.validate_transition_case(case)
    assert checked["derivations"][0]["temporal_outcome"] == "INCONCLUSIVE"


def test_sampled_profile_cannot_claim_satisfied_within_declared_model() -> None:
    case = _case()
    case["observation_profiles"][0]["collection_completeness"] = "COMPLETE"
    _rebind_observation_profile(case)
    case["derivations"][0]["temporal_outcome"] = (
        tc.TemporalOutcome.SATISFIED_WITHIN_DECLARED_MODEL.value
    )

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "SAMPLED_PROFILE_CANNOT_SATISFY_DECLARED_MODEL")


def test_transform_chain_accepts_an_honest_remint() -> None:
    case = _case()
    atom = case["evidence_atoms"][0]
    atom["transform_chain"] = [
        {
            "schema": tc.TRANSFORM_STEP_SCHEMA,
            "input_digest": _digest("private evidence before redaction"),
            "output_digest": atom["artifact_digest"],
            "transform_profile_digest": _digest("redaction profile"),
            "transform_receipt_digest": _digest("redaction receipt"),
            "coverage_effect": "NARROWED",
            "removed_predicate_ids": ["private.detail"],
        }
    ]

    assert tc.validate_transition_case(case) == case


def test_transform_cannot_reuse_input_bytes_as_a_redacted_derivative() -> None:
    case = _case()
    atom = case["evidence_atoms"][0]
    atom["transform_chain"] = [
        {
            "schema": tc.TRANSFORM_STEP_SCHEMA,
            "input_digest": atom["artifact_digest"],
            "output_digest": atom["artifact_digest"],
            "transform_profile_digest": _digest("redaction profile"),
            "transform_receipt_digest": _digest("redaction receipt"),
            "coverage_effect": "UNCHANGED",
            "removed_predicate_ids": [],
        }
    ]

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "TRANSFORM_MUST_REMINT_BYTES")


@pytest.mark.parametrize(
    ("coverage_effect", "removed", "code"),
    [
        ("NARROWED", [], "NARROWED_COVERAGE_MUST_NAME_REMOVALS"),
        ("UNCHANGED", ["private.detail"], "UNCHANGED_COVERAGE_CANNOT_REMOVE_PREDICATES"),
    ],
)
def test_transform_coverage_claim_must_match_named_removals(
    coverage_effect: str,
    removed: list[str],
    code: str,
) -> None:
    case = _case()
    atom = case["evidence_atoms"][0]
    atom["transform_chain"] = [
        {
            "schema": tc.TRANSFORM_STEP_SCHEMA,
            "input_digest": _digest("private input"),
            "output_digest": atom["artifact_digest"],
            "transform_profile_digest": _digest("redaction profile"),
            "transform_receipt_digest": _digest("redaction receipt"),
            "coverage_effect": coverage_effect,
            "removed_predicate_ids": removed,
        }
    ]

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, code)


def test_transform_chain_must_be_connected_and_end_at_the_bound_artifact() -> None:
    case = _case()
    atom = case["evidence_atoms"][0]
    middle = _digest("middle")
    atom["transform_chain"] = [
        {
            "schema": tc.TRANSFORM_STEP_SCHEMA,
            "input_digest": _digest("raw"),
            "output_digest": middle,
            "transform_profile_digest": _digest("profile one"),
            "transform_receipt_digest": _digest("receipt one"),
            "coverage_effect": "UNCHANGED",
            "removed_predicate_ids": [],
        },
        {
            "schema": tc.TRANSFORM_STEP_SCHEMA,
            "input_digest": _digest("not middle"),
            "output_digest": atom["artifact_digest"],
            "transform_profile_digest": _digest("profile two"),
            "transform_receipt_digest": _digest("receipt two"),
            "coverage_effect": "UNCHANGED",
            "removed_predicate_ids": [],
        },
    ]
    with pytest.raises(tc.TransitionContractError) as disconnected:
        tc.validate_transition_case(case)
    _assert_error(disconnected, "TRANSFORM_CHAIN_DISCONNECTED")

    atom["transform_chain"] = [deepcopy(atom["transform_chain"][0])]
    with pytest.raises(tc.TransitionContractError) as terminal:
        tc.validate_transition_case(case)
    _assert_error(terminal, "TRANSFORM_OUTPUT_ARTIFACT_MISMATCH")


@pytest.mark.parametrize("mode", [item.value for item in tc.CaseMode])
def test_each_replay_mode_accepts_only_its_own_content_location(mode: str) -> None:
    assert tc.validate_transition_case(_case(mode))["case_mode"] == mode


def test_case_and_replay_mode_cannot_disagree() -> None:
    case = _case(tc.CaseMode.SEALED_PORTABLE.value)
    case["replay_contract"]["mode"] = tc.CaseMode.REFERENCED.value
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "CASE_MODE_MISMATCH")


def test_sealed_mode_refuses_external_required_content() -> None:
    case = _case(tc.CaseMode.SEALED_PORTABLE.value)
    binding = case["replay_contract"]["object_bindings"][0]
    binding["location"] = "EXTERNAL"
    binding["resolver_id"] = "resolver.hostile"
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "SEALED_REQUIRED_CONTENT_NOT_EMBEDDED")


def test_projection_mode_refuses_embedded_or_external_authority() -> None:
    case = _case(tc.CaseMode.PROJECTION_ONLY.value)
    binding = case["replay_contract"]["object_bindings"][0]
    binding["location"] = "EMBEDDED"
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "PROJECTION_CONTENT_LOCATION_REQUIRED")


def test_detached_or_mutated_case_cannot_acquire_replay_authority() -> None:
    case = _case()
    with pytest.raises(tc.TransitionContractError) as detached:
        tc.require_bound_transition_case(case)
    _assert_error(detached, "DETACHED_TRANSITION_CASE")

    bound = tc.bind_transition_case_bytes(tc.canonical_json_bytes(case))
    bound["case_id"] = "case.mutated"
    with pytest.raises(tc.TransitionContractError) as mutated:
        tc.require_bound_transition_case(bound)
    _assert_error(mutated, "BOUND_TRANSITION_CASE_MUTATED")


@pytest.mark.parametrize(
    ("identity_field", "replacement"),
    [
        ("engagement_id", "engagement.other"),
        ("campaign_id", "campaign.other"),
        ("pair_id", "pair.other"),
        ("before_snapshot_digest", _digest("other before")),
        ("after_snapshot_digest", _digest("other after")),
        ("protocol_id", "fhrp.vrrp"),
        ("direction", "reverse"),
        ("scenario_id", "gateway.other"),
        ("wave_id", "wave.other"),
        ("transition_id", "transition.other"),
        ("trial_attempt_id", "attempt.other"),
    ],
)
def test_evidence_cannot_teleport_across_transition_identity(
    identity_field: str,
    replacement: str,
) -> None:
    case = _case()
    case["evidence_atoms"][0]["transition_identity"][identity_field] = replacement
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "EVIDENCE_TELEPORTATION")


@pytest.mark.parametrize(
    ("path", "replacement", "code"),
    [
        (("evidence_atoms", 0, "subject_id"), "vlan.999", "EVIDENCE_SCOPE_MISMATCH"),
        (("evidence_atoms", 0, "state_id"), "state.other", "EVIDENCE_SCOPE_MISMATCH"),
        (
            ("evidence_atoms", 0, "observation_profile_digest"),
            _digest("unknown profile"),
            "UNKNOWN_OBSERVATION_PROFILE_DIGEST",
        ),
        (
            ("evidence_atoms", 0, "coverage_scope", "subject_ids"),
            ["vlan.999"],
            "EVIDENCE_COVERAGE_SCOPE_MISMATCH",
        ),
        (
            ("evidence_atoms", 0, "semantic_profile_digest"),
            _digest("wrong semantic profile"),
            "DERIVATION_SEMANTIC_PROFILE_MISMATCH",
        ),
    ],
)
def test_evidence_scope_and_semantic_cross_bindings_fail_closed(
    path: tuple[str | int, ...],
    replacement: Any,
    code: str,
) -> None:
    case = _case()
    _assign(case, path, replacement)
    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, code)


def test_derivation_cannot_use_same_predicate_evidence_from_another_obligation_subject() -> None:
    case = _case()
    case["evolution_ir"]["subject_ids"] = ["vlan.10", "vlan.20"]
    atom = case["evidence_atoms"][0]
    atom["subject_id"] = "vlan.20"
    atom["coverage_scope"]["subject_ids"] = ["vlan.20"]
    denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator["subject_ids"] = ["vlan.20"]
    _rebind_observation_denominator(case)

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "OBLIGATION_QUALIFICATION_DENOMINATOR_SCOPE_MISMATCH")


def test_derivation_cannot_use_same_predicate_evidence_from_another_obligation_state() -> None:
    case = _case()
    case["evidence_atoms"][0]["state_id"] = "state.current"

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "DERIVATION_EVIDENCE_STATE_MISMATCH")


def test_observation_mode_is_bound_to_exact_denominator_kind() -> None:
    case = _case()
    denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator["denominator_kind"] = "EXACT_EVENTS"
    denominator["event_inventory_digest"] = _digest("qualified event inventory")
    case["evidence_atoms"][0]["coverage_scope"]["denominator_kind"] = "EXACT_EVENTS"
    _rebind_observation_denominator(case)

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH")


@pytest.mark.parametrize(
    ("field", "replacement", "code"),
    (
        ("subject_id", "sampled.profile.other", "OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH"),
        ("subject_version", "2", "OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH"),
        ("predicate_ids", ["gateway.other"], "OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH"),
        (
            "window",
            _interval("2026-08-22T00:00:00.000000Z", "2026-08-22T00:00:59.000000Z"),
            "OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH",
        ),
        (
            "subject_ids",
            ["vlan.20"],
            "OBLIGATION_QUALIFICATION_DENOMINATOR_SCOPE_MISMATCH",
        ),
    ),
)
def test_observation_denominator_field_mutation_breaks_exact_cross_join(
        field: str,
        replacement: Any,
        code: str) -> None:
    case = _case()
    denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == "OBSERVATION_PROFILE"
    )
    denominator[field] = replacement
    _rebind_observation_denominator(case)

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, code)


def test_evidence_scope_kind_cannot_claim_a_different_qualified_denominator() -> None:
    case = _case()
    case["evidence_atoms"][0]["coverage_scope"]["denominator_kind"] = "EXACT_EVENTS"

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "EVIDENCE_QUALIFICATION_DENOMINATOR_MISMATCH")


def test_pack_and_applicability_platform_release_denominators_must_be_identical() -> None:
    case = _case()
    denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == "BEHAVIOR_PACK"
    )
    denominator["platform_release_ids"] = ["fixture.other-release"]
    denominator_digest = tc.canonical_digest(denominator)
    dependency = next(
        item for item in case["version_contract"]["dependency_digests"]
        if item["kind"] == "QUALIFICATION_DENOMINATOR"
        and item["identifier"] == denominator["denominator_id"]
    )
    dependency["digest"] = denominator_digest

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "PACK_APPLICABILITY_PLATFORM_DENOMINATOR_MISMATCH")


def test_semantic_profile_cannot_teleport_as_a_paired_atom_and_obligation_mutation() -> None:
    case = _case()
    hostile_digest = _digest("hostile substitute semantic profile")
    case["evolution_ir"]["obligations"][0]["semantic_profile_digest"] = hostile_digest
    case["evidence_atoms"][0]["semantic_profile_digest"] = hostile_digest

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, "OBLIGATION_SEMANTIC_PROFILE_PACK_MISMATCH")


@pytest.mark.parametrize(
    ("role", "code"),
    (
        ("EVIDENCE", "EVIDENCE_CONTENT_BINDING_MISSING"),
        ("PACK_MANIFEST", "AUTHORITY_CONTENT_BINDING_MISSING"),
        ("TCB_MANIFEST", "AUTHORITY_CONTENT_BINDING_MISSING"),
        ("SEMANTIC_BUNDLE", "AUTHORITY_CONTENT_BINDING_MISSING"),
        ("QUALIFICATION_RECEIPT", "AUTHORITY_CONTENT_BINDING_MISSING"),
        ("STATE_SNAPSHOT", "STATE_SNAPSHOT_CONTENT_BINDING_MISSING"),
        ("VERIFIER_BOOTSTRAP", "VERIFIER_BOOTSTRAP_CONTENT_BINDING_MISSING"),
        ("TRUST_SNAPSHOT", "TRUST_POLICY_CONTENT_BINDING_MISSING"),
        ("REPLAY_RECIPE", "REPLAY_RECIPE_CONTENT_BINDING_MISSING"),
    ),
)
def test_semantic_mandatory_content_binding_cannot_be_downgraded_to_optional_external(
        role: str,
        code: str) -> None:
    case = _case(tc.CaseMode.SEALED_PORTABLE.value)
    binding = next(
        item for item in case["replay_contract"]["object_bindings"]
        if item["role"] == role
    )
    binding["required"] = False
    binding["location"] = "EXTERNAL"
    binding["resolver_id"] = "resolver.hostile"

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(case)
    _assert_error(error, code)
