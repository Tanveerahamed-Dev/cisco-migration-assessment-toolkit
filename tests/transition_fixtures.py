"""Minimal proof fixtures for the additive Atlas Release 2 transition contract.

The QCP-001 material below is deliberately EXPERIMENTAL.  Its synthetic receipt digest is useful
for exercising exact structural joins only; it is not a qualification receipt or promotion claim.
"""

from __future__ import annotations

from copy import deepcopy

from cisco_toolkit import transition_contract as tc


WINDOW = {
    "start_inclusive": "2026-08-22T00:00:00.000000Z",
    "end_inclusive": "2026-08-22T00:10:00.000000Z",
}

EXPERIMENTAL_QCP_001_QUALIFICATION = {
    "schema": "atlas.qualification-receipt/1",
    "pattern_id": "QCP-001",
    "qualification_state": tc.QualificationState.EXPERIMENTAL.value,
    "claim": "NON_PROMOTING_STRUCTURAL_FIXTURE",
}


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def minimal_transition_case() -> dict:
    """Return a fresh, fully valid canonical R2.0 TransitionCase value."""

    before_digest = _digest("before-snapshot")
    after_digest = _digest("after-snapshot")
    artifact_digest = _digest("sampled-observation-bytes")
    pack_manifest_digest = _digest("qcp-001-experimental-pack-manifest")
    tcb_manifest_digest = _digest("qcp-001-experimental-tcb-manifest")
    semantic_bundle_digest = _digest("qcp-001-experimental-semantic-bundle")
    verifier_bootstrap_digest = _digest("independently-obtained-verifier-bootstrap")
    trust_policy_digest = _digest("external-experimental-trust-policy")
    replay_recipe_digest = _digest("qcp-001-experimental-replay-recipe")
    qualification_receipt_digest = tc.canonical_digest(EXPERIMENTAL_QCP_001_QUALIFICATION)

    identity = {
        "schema": tc.TRANSITION_IDENTITY_SCHEMA,
        "engagement_id": "engagement.fixture",
        "campaign_id": "campaign.fixture",
        "pair_id": "pair.legacy-target",
        "before_snapshot_digest": before_digest,
        "after_snapshot_digest": after_digest,
        "protocol_id": "fhrp",
        "direction": "legacy-to-target",
        "scenario_id": "gateway-handoff",
        "wave_id": "wave.001",
        "transition_id": "transition.001",
        "trial_attempt_id": "attempt.001",
    }

    qualification_denominators = [
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.QCP-001.applicability",
            "subject_kind": "APPLICABILITY_PROFILE",
            "subject_id": "QCP-001.EXPERIMENTAL.applicability",
            "subject_version": "1",
            "denominator_kind": "APPLICABILITY_SCOPE",
            "subject_ids": ["subject.gateway-pair"],
            "predicate_ids": [],
            "window": deepcopy(WINDOW),
            "platform_release_ids": ["fixture.platform-release"],
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        },
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.QCP-001.observation",
            "subject_kind": "OBSERVATION_PROFILE",
            "subject_id": "QCP-001.EXPERIMENTAL.sampled-profile",
            "subject_version": "1",
            "denominator_kind": "EXACT_SUBJECTS",
            "subject_ids": ["subject.gateway-pair"],
            "predicate_ids": ["predicate.fhrp.single-owner"],
            "window": deepcopy(WINDOW),
            "platform_release_ids": [],
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        },
        {
            "schema": tc.QUALIFICATION_DENOMINATOR_SCHEMA,
            "denominator_id": "denominator.QCP-001.pack",
            "subject_kind": "BEHAVIOR_PACK",
            "subject_id": "QCP-001",
            "subject_version": "0.0.0-experimental",
            "denominator_kind": "PACK_SUPPORTED_SCOPE",
            "subject_ids": ["subject.gateway-pair"],
            "predicate_ids": ["predicate.fhrp.single-owner"],
            "window": deepcopy(WINDOW),
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
        "profile_id": "QCP-001.EXPERIMENTAL.sampled-profile",
        "source_kind": "fixture.sampled-capture",
        "coverage_mode": tc.ObservationMode.SAMPLED.value,
        "predicate_ids": ["predicate.fhrp.single-owner"],
        "window": deepcopy(WINDOW),
        "planned_cadence_ms": 1000,
        "observed_maximum_gap_ms": 1500,
        "clock_error_bound_ms": 100,
        "collection_completeness": "COMPLETE",
        "detection_latency_bound_ms": None,
        "cross_device_overlap_rule": "REQUIRE_OVERLAP_WITHIN_CLOCK_ERROR",
        "start_end_coverage": "BOTH",
        "missing_sample_policy": "INCONCLUSIVE",
        "qualification_denominator_digest": denominator_digests["OBSERVATION_PROFILE"],
        "qualification_receipt_digest": None,
    }
    observation_profile_digest = tc.canonical_digest(observation_profile)

    obligation = {
        "schema": tc.OBLIGATION_SCHEMA,
        "obligation_id": "obligation.fhrp.single-owner",
        "requirement_id": "requirement.fhrp.single-owner",
        "predicate_id": "predicate.fhrp.single-owner",
        "subject_ids": ["subject.gateway-pair"],
        "state_ids": ["state.after"],
        "temporal_operator": tc.TemporalOperator.SAMPLED_NO_VIOLATION_DURING.value,
        "mandatory": True,
        "window": deepcopy(WINDOW),
        "observation_profile_digest": observation_profile_digest,
        "semantic_profile_digest": semantic_bundle_digest,
        "accepted_evidence_classes": [tc.EvidenceClass.OBSERVED.value],
        "rollback_dimension": tc.RollbackDimension.PROTOCOL_EQUIVALENCE_OBSERVED.value,
    }

    evidence_atom = {
        "schema": tc.EVIDENCE_ATOM_SCHEMA,
        "evidence_id": "evidence.fhrp.single-owner.sample.001",
        "artifact_digest": artifact_digest,
        "transition_identity": deepcopy(identity),
        "subject_id": "subject.gateway-pair",
        "state_id": "state.after",
        "predicate_id": "predicate.fhrp.single-owner",
        "value": True,
        "observed_time_interval": {
            "start_inclusive": "2026-08-22T00:00:01.000000Z",
            "end_inclusive": "2026-08-22T00:00:02.000000Z",
        },
        "collected_at": "2026-08-22T00:00:03.000000Z",
        "received_at": "2026-08-22T00:00:04.000000Z",
        "sealed_at": "2026-08-22T00:00:05.000000Z",
        "evidence_class": tc.EvidenceClass.OBSERVED.value,
        "acquisition_method": "fixture.sampled-capture",
        "observation_profile_digest": observation_profile_digest,
        "semantic_profile_digest": semantic_bundle_digest,
        "coverage_scope": {
            "schema": tc.COVERAGE_SCOPE_SCHEMA,
            "denominator_kind": "EXACT_SUBJECTS",
            "subject_ids": ["subject.gateway-pair"],
            "predicate_ids": ["predicate.fhrp.single-owner"],
            "window": deepcopy(WINDOW),
            "complete": False,
        },
        "transform_chain": [],
    }

    derivation = {
        "schema": tc.DERIVATION_SCHEMA,
        "derivation_id": "derivation.sampled-trace.001",
        "obligation_id": "obligation.fhrp.single-owner",
        "evidence_ids": ["evidence.fhrp.single-owner.sample.001"],
        "effect": tc.EvidenceEffect.SUPPORT.value,
        "temporal_outcome": tc.TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value,
        "evaluator_kind": tc.EvaluatorKind.STRUCTURAL_DECLARATIVE.value,
        "evaluator_digest": semantic_bundle_digest,
        "certificate_digest": None,
        "reason_codes": ["sampled.trace-only"],
    }

    object_bindings = [
        {
            "schema": tc.OBJECT_BINDING_SCHEMA,
            "role": role,
            "digest": digest,
            "location": "EMBEDDED",
            "resolver_id": None,
            "required": True,
        }
        for role, digest in sorted(
            (
                ("EVIDENCE", artifact_digest),
                ("PACK_MANIFEST", pack_manifest_digest),
                ("TCB_MANIFEST", tcb_manifest_digest),
                ("QUALIFICATION_RECEIPT", qualification_receipt_digest),
                ("REPLAY_RECIPE", replay_recipe_digest),
                ("SEMANTIC_BUNDLE", semantic_bundle_digest),
                ("STATE_SNAPSHOT", after_digest),
                ("STATE_SNAPSHOT", before_digest),
                ("TRUST_SNAPSHOT", trust_policy_digest),
                ("VERIFIER_BOOTSTRAP", verifier_bootstrap_digest),
            )
        )
    ]

    dependencies = [
        {
            "kind": "PACK",
            "identifier": "QCP-001",
            "digest": pack_manifest_digest,
        },
        {
            "kind": "QUALIFICATION_DENOMINATOR",
            "identifier": "denominator.QCP-001.applicability",
            "digest": denominator_digests["APPLICABILITY_PROFILE"],
        },
        {
            "kind": "QUALIFICATION_DENOMINATOR",
            "identifier": "denominator.QCP-001.observation",
            "digest": denominator_digests["OBSERVATION_PROFILE"],
        },
        {
            "kind": "QUALIFICATION_DENOMINATOR",
            "identifier": "denominator.QCP-001.pack",
            "digest": denominator_digests["BEHAVIOR_PACK"],
        },
        {
            "kind": "SEMANTIC_PROFILE",
            "identifier": "QCP-001",
            "digest": semantic_bundle_digest,
        },
        {
            "kind": "TCB",
            "identifier": "QCP-001",
            "digest": tcb_manifest_digest,
        },
        {
            "kind": "WORDING_POLICY",
            "identifier": tc.WORDING_POLICY_VERSION,
            "digest": tc.wording_policy_digest(),
        },
    ]

    return {
        "schema": tc.TRANSITION_CASE_SCHEMA,
        "case_id": "case.QCP-001.EXPERIMENTAL.001",
        "case_mode": tc.CaseMode.SEALED_PORTABLE.value,
        "created_at": "2026-08-22T00:00:06.000000Z",
        "transition_identity": identity,
        "evolution_ir": {
            "schema": tc.EVOLUTION_IR_SCHEMA,
            "ir_version": tc.EVOLUTION_IR_VERSION,
            "transition_identity": deepcopy(identity),
            "from_state_id": "state.before",
            "to_state_id": "state.after",
            "intermediate_state_ids": [],
            "subject_ids": ["subject.gateway-pair"],
            "trigger_ids": ["trigger.gateway-handoff"],
            "obligations": [obligation],
            "rollback_dimensions": list(tc.ROLLBACK_DIMENSIONS),
        },
        "qualification_denominators": qualification_denominators,
        "observation_profiles": [observation_profile],
        "evidence_atoms": [evidence_atom],
        "applicability": {
            "schema": tc.APPLICABILITY_SCHEMA,
            "kind": tc.ApplicabilityKind.APPLICABLE.value,
            "reason_codes": [],
            "profile_id": "QCP-001.EXPERIMENTAL.applicability",
            "profile_digest": _digest("qcp-001-experimental-applicability-profile"),
            "supported_denominator_digest": denominator_digests["APPLICABILITY_PROFILE"],
            "qualification_receipt_digest": qualification_receipt_digest,
        },
        "pack_binding": {
            "schema": tc.PACK_BINDING_SCHEMA,
            "pack_id": "QCP-001",
            "pack_version": "0.0.0-experimental",
            "pack_manifest_digest": pack_manifest_digest,
            "tcb_manifest_digest": tcb_manifest_digest,
            "semantic_bundle_digest": semantic_bundle_digest,
            "pack_qualification_receipt_digest": None,
            "abi_version": tc.PACK_ABI_VERSION,
        },
        "derivations": [derivation],
        "replay_contract": {
            "schema": tc.REPLAY_CONTRACT_SCHEMA,
            "mode": tc.CaseMode.SEALED_PORTABLE.value,
            "object_bindings": object_bindings,
            "verifier_bootstrap_digest": verifier_bootstrap_digest,
            "trust_policy_digest": trust_policy_digest,
            "replay_recipe_digest": replay_recipe_digest,
        },
        "security_contract": {
            "schema": tc.SECURITY_CONTRACT_SCHEMA,
            "classification": "INTERNAL",
            "evidence_protection": "CONTRACT_ONLY",
            "recipient_policy_digest": None,
            "encryption_profile_digest": None,
            "redaction_profile_digest": None,
            "key_policy_digest": None,
            "retention_policy_digest": _digest("fixture-retention-policy"),
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
            "dependency_digests": dependencies,
        },
    }
