"""Temporal red-team tests using real public qualification verification paths."""

from __future__ import annotations

import base64
from copy import deepcopy
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_tcb_review as tr
from cisco_toolkit import transition_verifier as tv
from tests.transition_fixtures import minimal_transition_case


_SIGNATURE_DOMAIN = b"ATLAS-TRANSITION-QUALIFICATION\x00v1\x00"
_PACK_ID = "PACK-FIXTURE"
_PACK_VERSION = "1.0.0"
_KEY_ID = "qualification-key.temporal"
_POLICY_ID = "qualification-policy.temporal"


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _trust_policy(
        public_key_raw: bytes,
        subject_ids: list[str],
        *,
        evaluated_at: str = "2026-08-23T00:00:00.000000Z") -> dict[str, Any]:
    return {
        "schema": tp.TRUST_POLICY_SCHEMA,
        "policy_id": _POLICY_ID,
        "policy_version": "1.0.0",
        "purpose": tp.QUALIFICATION_PURPOSE,
        "evaluated_at": evaluated_at,
        "trusted_keys": [
            {
                "schema": tp.TRUSTED_KEY_SCHEMA,
                "key_id": _KEY_ID,
                "public_key_digest": tc.bytes_digest(public_key_raw),
                "allowed_subject_kinds": sorted(
                    item.value for item in tp.QualificationSubjectKind
                ),
                "allowed_subject_ids": sorted(subject_ids),
                "valid_from": "2026-01-01T00:00:00.000000Z",
                "valid_until": "2027-01-01T00:00:00.000000Z",
            }
        ],
        "revoked_receipt_digests": [],
    }


def _verified_qualification(
        *,
        private_key: Ed25519PrivateKey,
        public_key_raw: bytes,
        policy: tp.BoundTrustPolicy,
        receipt_id: str,
        subject_kind: str,
        subject_id: str,
        subject_version: str,
        subject_digest: str,
        denominator_digest: str | None = None,
) -> tuple[tp.VerifiedQualification, bytes, bytes]:
    receipt = {
        "schema": tp.QUALIFICATION_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "purpose": tp.QUALIFICATION_PURPOSE,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "subject_version": subject_version,
        "subject_digest": subject_digest,
        "qualification_state": tc.QualificationState.QUALIFIED.value,
        "denominator_digest": denominator_digest or _digest(f"denominator {receipt_id}"),
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "issuer_key_id": _KEY_ID,
    }
    receipt_raw = tc.canonical_json_bytes(receipt)
    signature = {
        "schema": tp.QUALIFICATION_SIGNATURE_SCHEMA,
        "purpose": tp.QUALIFICATION_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "signer_key_id": _KEY_ID,
        "algorithm": tp.QUALIFICATION_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(
            private_key.sign(_SIGNATURE_DOMAIN + receipt_raw)
        ).decode("ascii"),
    }
    signature_raw = tc.canonical_json_bytes(signature)
    verified = tp.verify_qualification_evidence(
        receipt_raw,
        signature_raw,
        policy,
        public_key_raw,
    )
    return verified, receipt_raw, signature_raw


def _qualified_pack_manifest(case: dict[str, Any]) -> dict[str, Any]:
    pack_denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == tp.QualificationSubjectKind.BEHAVIOR_PACK.value
    )
    return {
        "schema": tp.PACK_MANIFEST_SCHEMA,
        "pack_id": _PACK_ID,
        "pack_version": _PACK_VERSION,
        "abi_version": tc.PACK_ABI_VERSION,
        "behavior_kind": "BEHAVIOR_PACK",
        "qualification_state": tc.QualificationState.QUALIFIED.value,
        "qualification_receipt_digest": None,
        "execution_state": tp.PackExecutionState.ACTIVATABLE.value,
        "substrate": tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        "semantic_bundle_digest": case["pack_binding"]["semantic_bundle_digest"],
        "declarative_rules_digest": case["pack_binding"]["semantic_bundle_digest"],
        "declarative_operators": list(tp.DECLARATIVE_DSL_OPERATORS),
        "supported_denominator_digest": tc.canonical_digest(pack_denominator),
        "applicability_profile_ids": [case["applicability"]["profile_id"]],
        "functions": list(tp.PACK_ABI_FUNCTIONS),
        "wasm_modules": [],
        "tcb_manifest_digest": _digest("qualified tcb manifest"),
        "claim_boundary": "Qualified fixture pack; machine eligibility is not human approval.",
    }


def _frozen_tcb_manifest(
        *,
        denominator_digest: str,
        program_digest: str,
        qualification_receipt_digest: str | None = None) -> dict[str, Any]:
    interpreter_digest = _digest("temporal fixture DSL interpreter")
    return {
        "schema": tp.TCB_MANIFEST_SCHEMA,
        "manifest_id": "tcb.temporal.fixture.001",
        "substrate": tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        "core_sources": [
            {
                "artifact_id": "atlas.temporal-interpreter",
                "artifact_version": "1.0.0",
                "path": "cisco_toolkit/transition_dsl.py",
                "role": "DSL_INTERPRETER",
                "bytes": 100,
                "digest": interpreter_digest,
            },
        ],
        "pack_sources": [
            {
                "artifact_id": "atlas.temporal-denominator",
                "artifact_version": "1.0.0",
                "path": "tests/fixtures/temporal-denominator.json",
                "role": tp.SUPPORTED_DENOMINATOR_SOURCE_ROLE,
                "bytes": 100,
                "digest": denominator_digest,
            },
            {
                "artifact_id": "atlas.temporal-pack",
                "artifact_version": "1.0.0",
                "path": "tests/fixtures/temporal-pack.json",
                "role": tp.DECLARATIVE_PROGRAM_SOURCE_ROLE,
                "bytes": 100,
                "digest": program_digest,
            },
        ],
        "transitive_dependencies": [
            {
                "component_id": "runtime-dependency.temporal",
                "component_version": "1.0.0",
                "content_digest": _digest("temporal runtime dependency"),
            },
        ],
        "runtime_inventory_state": (
            tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
        ),
        "core_census_method": tp.TCB_CORE_CENSUS_METHOD,
        "pack_census_method": tp.TCB_PACK_CENSUS_METHOD,
        "core_executable_lines": 100,
        "pack_executable_lines": 20,
        "dsl_interpreter": {
            "component_id": "atlas.temporal-interpreter",
            "component_version": "1.0.0",
            "content_digest": interpreter_digest,
        },
        "wasm_runtime": None,
        "toolchains": [
            {
                "component_id": "CPython",
                "component_version": "3.12.10",
                "content_digest": _digest("temporal fixture toolchain"),
            },
        ],
        "abi_version": tc.PACK_ABI_VERSION,
        "qualification_receipt_digest": qualification_receipt_digest,
        "supported_denominator_digest": denominator_digest,
        "budget_review_receipt_digest": None,
        "budget_state": tp.TCBBudgetState.FROZEN.value,
        "core_sloc_budget": 120,
        "pack_sloc_budget": 30,
        "resource_ceilings": {
            "dsl": {
                "max_program_bytes": 65_536,
                "max_input_bytes": 131_072,
                "max_output_bytes": 65_536,
                "max_rules": 128,
                "max_expression_depth": 16,
                "max_expression_nodes": 2_048,
                "max_operator_operands": 64,
                "max_path_segments": 16,
                "max_string_bytes": 8_192,
                "max_set_items": 256,
                "max_input_nodes": 8_192,
                "max_instruction_fuel": 32_768,
            },
            "wasm": None,
        },
    }


def _verified_budget_review(tcb: dict[str, Any]) -> tr.VerifiedTCBBudgetReview:
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_bytes(private_key)
    subject_digest = tr.tcb_budget_review_subject_digest(tcb)
    profile = {
        "schema": tr.DSL_RESOURCE_PROFILE_SCHEMA,
        "substrate": tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        **tcb["resource_ceilings"]["dsl"],
    }
    receipt = {
        "schema": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
        "receipt_id": "tcb-budget-review.temporal.001",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "selected_commit": "a" * 40,
        "selected_tree": "b" * 40,
        "structural_census_digest": _digest("temporal structural census"),
        "prototype_measurement_digest": _digest("temporal prototype measurements"),
        "runtime_inventory_digest": _digest("temporal runtime inventory"),
        "approved_runtime_inventory_state": (
            tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
        ),
        "budget_proposal_digest": _digest("temporal budget proposal"),
        "prototype_pack_manifest_digest": _digest("temporal prototype pack manifest"),
        "dsl_interpreter_digest": tcb["dsl_interpreter"]["content_digest"],
        "prototype_program_digest": _digest("temporal prototype program"),
        "tcb_budget_subject_digest": subject_digest,
        "approved_core_sloc_budget": tcb["core_sloc_budget"],
        "approved_pack_sloc_budget": tcb["pack_sloc_budget"],
        "approved_dsl_resource_profile": profile,
        "approved_receipt_container_ceiling": dsl.dsl_receipt_container_ceiling(profile),
        "wasm_review_state": "UNREVIEWED",
        "measurement_denominator_digest": _digest("temporal measurement denominator"),
        "decision": tr.TCBBudgetReviewDecision.APPROVED.value,
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "reviewer_key_id": "tcb-reviewer.temporal",
    }
    policy = {
        "schema": tr.TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA,
        "policy_kind": tr.TCB_BUDGET_REVIEW_POLICY_KIND,
        "policy_id": "tcb-budget-review-policy.temporal",
        "policy_version": "1.0.0",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "evaluated_at": "2026-08-23T00:00:00.000000Z",
        "trusted_keys": [
            {
                "schema": tr.TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA,
                "key_id": receipt["reviewer_key_id"],
                "public_key_digest": tc.bytes_digest(public_key_raw),
                "reviewer_kind": tr.TCB_BUDGET_REVIEWER_KIND,
                "independent_from_budget_proposer": True,
                "independent_from_prototype_and_measurement_producer": True,
                "independent_from_release_builder": True,
                "authorizations": [{
                    "schema": tr.TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA,
                    "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
                    "target_schema_version": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
                    "reviewer_role": tr.TCB_BUDGET_REVIEWER_ROLE,
                    "substrate": tr.TCB_BUDGET_REVIEW_SUBSTRATE,
                }],
                "allowed_source_revisions": [{
                    "selected_commit": receipt["selected_commit"],
                    "selected_tree": receipt["selected_tree"],
                    "tcb_budget_subject_digest": subject_digest,
                }],
                "valid_from": "2026-01-01T00:00:00.000000Z",
                "valid_until": "2027-01-01T00:00:00.000000Z",
            },
        ],
        "revoked_receipt_digests": [],
    }
    receipt_raw = tc.canonical_json_bytes(receipt)
    policy_raw = tc.canonical_json_bytes(policy)
    signature = {
        "schema": tr.TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA,
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "signer_key_id": receipt["reviewer_key_id"],
        "algorithm": tr.TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(
            private_key.sign(tr.tcb_budget_review_signing_material(receipt_raw, policy_raw))
        ).decode("ascii"),
    }
    bindings = {
        "schema": tr.TCB_BUDGET_REVIEW_BINDINGS_SCHEMA,
        **{
            key: receipt[key]
            for key in (
                "selected_commit",
                "selected_tree",
                "structural_census_digest",
                "prototype_measurement_digest",
                "runtime_inventory_digest",
                "approved_runtime_inventory_state",
                "budget_proposal_digest",
                "prototype_pack_manifest_digest",
                "dsl_interpreter_digest",
                "prototype_program_digest",
                "tcb_budget_subject_digest",
                "measurement_denominator_digest",
            )
        },
    }
    return tr.verify_tcb_budget_review_evidence(
        receipt_raw,
        tc.canonical_json_bytes(signature),
        tr.bind_external_tcb_budget_review_trust_policy_bytes(policy_raw),
        public_key_raw,
        bindings,
    )


def _content_binding(role: str, digest: str) -> dict[str, Any]:
    return {
        "schema": tc.OBJECT_BINDING_SCHEMA,
        "role": role,
        "digest": digest,
        "location": "EMBEDDED",
        "resolver_id": None,
        "required": True,
    }


def _qualified_fixture(
    case: dict[str, Any] | None = None,
    *,
    policy_evaluated_at: str = "2026-08-23T00:00:00.000000Z",
) -> tuple[
        tc.BoundTransitionCase,
        tp.BoundPackManifest,
        tp.BoundTCBManifest,
        tp.BoundTrustPolicy,
        tv.BoundContentSet,
        tp.VerifiedQualification,
        tp.VerifiedQualification,
        dict[str, tp.VerifiedQualification],
        tr.VerifiedTCBBudgetReview,
]:
    value = deepcopy(case or minimal_transition_case())
    profile = value["observation_profiles"][0]
    pack_denominator = next(
        item for item in value["qualification_denominators"]
        if item["subject_kind"] == tp.QualificationSubjectKind.BEHAVIOR_PACK.value
    )
    previous_denominator_id = pack_denominator["denominator_id"]
    pack_denominator.update({
        "denominator_id": "denominator.PACK-FIXTURE.pack",
        "subject_id": _PACK_ID,
        "subject_version": _PACK_VERSION,
    })
    value["qualification_denominators"].sort(key=lambda item: item["denominator_id"])
    pack_denominator_digest = tc.canonical_digest(pack_denominator)
    for dependency in value["version_contract"]["dependency_digests"]:
        if (
                dependency["kind"] == "QUALIFICATION_DENOMINATOR"
                and dependency["identifier"] == previous_denominator_id
        ):
            dependency.update({
                "identifier": pack_denominator["denominator_id"],
                "digest": pack_denominator_digest,
            })
    value["version_contract"]["dependency_digests"].sort(
        key=lambda item: (item["kind"], item["identifier"])
    )
    manifest = _qualified_pack_manifest(value)
    tcb = _frozen_tcb_manifest(
        denominator_digest=manifest["supported_denominator_digest"],
        program_digest=manifest["declarative_rules_digest"],
    )
    budget_review = _verified_budget_review(tcb)
    tcb["budget_review_receipt_digest"] = budget_review.review_digest
    manifest["tcb_manifest_digest"] = tc.canonical_digest(tcb)
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_bytes(private_key)
    subject_ids = [
        value["applicability"]["profile_id"],
        profile["profile_id"],
        manifest["pack_id"],
    ]
    policy = _trust_policy(
        public_key_raw,
        subject_ids,
        evaluated_at=policy_evaluated_at,
    )
    policy_raw = tc.canonical_json_bytes(policy)
    bound_policy = tp.bind_external_trust_policy_bytes(policy_raw)

    (
        applicability_qualification,
        applicability_receipt_raw,
        applicability_signature_raw,
    ) = _verified_qualification(
        private_key=private_key,
        public_key_raw=public_key_raw,
        policy=bound_policy,
        receipt_id="qualification.applicability.temporal",
        subject_kind=tp.QualificationSubjectKind.APPLICABILITY_PROFILE.value,
        subject_id=value["applicability"]["profile_id"],
        subject_version="1",
        subject_digest=value["applicability"]["profile_digest"],
        denominator_digest=value["applicability"]["supported_denominator_digest"],
    )
    profile_qualification, profile_receipt_raw, profile_signature_raw = _verified_qualification(
        private_key=private_key,
        public_key_raw=public_key_raw,
        policy=bound_policy,
        receipt_id="qualification.observation.temporal",
        subject_kind=tp.QualificationSubjectKind.OBSERVATION_PROFILE.value,
        subject_id=profile["profile_id"],
        subject_version="1",
        subject_digest=tp.qualification_subject_digest(
            tp.QualificationSubjectKind.OBSERVATION_PROFILE.value,
            profile,
        ),
        denominator_digest=profile["qualification_denominator_digest"],
    )
    pack_qualification, pack_receipt_raw, pack_signature_raw = _verified_qualification(
        private_key=private_key,
        public_key_raw=public_key_raw,
        policy=bound_policy,
        receipt_id="qualification.pack.temporal",
        subject_kind=tp.QualificationSubjectKind.BEHAVIOR_PACK.value,
        subject_id=manifest["pack_id"],
        subject_version=manifest["pack_version"],
        subject_digest=tp.pack_qualification_subject_digest(
            manifest,
            tcb,
        ),
        denominator_digest=manifest["supported_denominator_digest"],
    )

    value["applicability"]["qualification_receipt_digest"] = (
        applicability_qualification.receipt_digest
    )
    profile["qualification_receipt_digest"] = profile_qualification.receipt_digest
    profile_digest = tc.canonical_digest(profile)
    value["evolution_ir"]["obligations"][0]["observation_profile_digest"] = profile_digest
    value["evolution_ir"]["covered_frame_domain"]["observation_profile_digests"] = [
        profile_digest
    ]
    value["evolution_ir"]["covered_frame_domain"][
        "qualification_denominator_digests"
    ] = [profile["qualification_denominator_digest"]]
    value["evidence_atoms"][0]["observation_profile_digest"] = profile_digest

    tcb["qualification_receipt_digest"] = pack_qualification.receipt_digest
    tcb_raw = tc.canonical_json_bytes(tcb)
    bound_tcb = tp.bind_tcb_manifest_bytes(tcb_raw)
    manifest["qualification_receipt_digest"] = pack_qualification.receipt_digest
    manifest["tcb_manifest_digest"] = bound_tcb.digest
    pack_raw = tc.canonical_json_bytes(manifest)
    bound_pack = tp.bind_pack_manifest_bytes(pack_raw)
    tp.validate_pack_tcb_pair(
        bound_pack,
        bound_tcb,
        budget_review=budget_review,
    )
    value["pack_binding"].update({
        "pack_id": bound_pack["pack_id"],
        "pack_version": bound_pack["pack_version"],
        "pack_manifest_digest": bound_pack.digest,
        "tcb_manifest_digest": bound_tcb.digest,
        "semantic_bundle_digest": bound_pack["semantic_bundle_digest"],
        "pack_qualification_receipt_digest": pack_qualification.receipt_digest,
    })
    value["replay_contract"]["trust_policy_digest"] = tc.bytes_digest(policy_raw)
    value["qualification_evidence_bindings"] = sorted(
        [
            {
                "schema": tc.QUALIFICATION_EVIDENCE_BINDING_SCHEMA,
                "receipt_digest": qualification.receipt_digest,
                "signature_digest": qualification.signature_digest,
                "public_key_digest": qualification.public_key_digest,
            }
            for qualification in (
                applicability_qualification,
                profile_qualification,
                pack_qualification,
            )
        ],
        key=lambda item: item["receipt_digest"],
    )

    retained_bindings = [
        binding
        for binding in value["replay_contract"]["object_bindings"]
        if binding["role"] not in {
            "PACK_MANIFEST",
            "TCB_MANIFEST",
            "QUALIFICATION_RECEIPT",
            "QUALIFICATION_SIGNATURE",
            "QUALIFICATION_PUBLIC_KEY",
        }
    ]
    retained_bindings.extend([
        _content_binding("PACK_MANIFEST", bound_pack.digest),
        _content_binding("TCB_MANIFEST", bound_tcb.digest),
        _content_binding("QUALIFICATION_RECEIPT", applicability_qualification.receipt_digest),
        _content_binding("QUALIFICATION_RECEIPT", pack_qualification.receipt_digest),
        _content_binding("QUALIFICATION_RECEIPT", profile_qualification.receipt_digest),
        _content_binding("QUALIFICATION_SIGNATURE", applicability_qualification.signature_digest),
        _content_binding("QUALIFICATION_SIGNATURE", pack_qualification.signature_digest),
        _content_binding("QUALIFICATION_SIGNATURE", profile_qualification.signature_digest),
        _content_binding("QUALIFICATION_PUBLIC_KEY", tc.bytes_digest(public_key_raw)),
    ])
    value["replay_contract"]["object_bindings"] = sorted(
        retained_bindings,
        key=lambda item: (item["role"], item["digest"]),
    )

    dependencies = value["version_contract"]["dependency_digests"]
    for dependency in dependencies:
        if dependency["kind"] == "PACK":
            dependency.update({"identifier": _PACK_ID, "digest": bound_pack.digest})
        elif dependency["kind"] == "TCB":
            dependency.update({"identifier": _PACK_ID, "digest": bound_tcb.digest})
        elif dependency["kind"] == "SEMANTIC_PROFILE":
            dependency["identifier"] = _PACK_ID
    dependencies.extend([
        {
            "kind": "OBSERVATION_PROFILE",
            "identifier": profile["profile_id"],
            "digest": profile_digest,
        },
        {
            "kind": "QUALIFICATION",
            "identifier": "qualification.applicability.temporal",
            "digest": applicability_qualification.receipt_digest,
        },
        {
            "kind": "QUALIFICATION",
            "identifier": "qualification.observation.temporal",
            "digest": profile_qualification.receipt_digest,
        },
        {
            "kind": "QUALIFICATION",
            "identifier": "qualification.pack.temporal",
            "digest": pack_qualification.receipt_digest,
        },
        {
            "kind": "TRUST_POLICY",
            "identifier": _POLICY_ID,
            "digest": tc.bytes_digest(policy_raw),
        },
    ])
    dependencies.sort(key=lambda item: (item["kind"], item["identifier"]))
    value["security_contract"]["evidence_protection"] = "PLAINTEXT_POLICY_APPROVED"

    bound_case = tc.bind_transition_case_bytes(tc.canonical_json_bytes(value))
    content = tv.bind_content_objects([
        tc.canonical_json_bytes({"fixture": "sampled-observation-bytes"}),
        tc.canonical_json_bytes({"fixture": "before-snapshot"}),
        tc.canonical_json_bytes({"fixture": "after-snapshot"}),
        tc.canonical_json_bytes({"fixture": "fhrp-single-owner-evidence-recipe"}),
        tc.canonical_json_bytes({"fixture": "gateway-handoff-compensation-plan"}),
        tc.canonical_json_bytes({"fixture": "decision-time-trust-policy-snapshot"}),
        tc.canonical_json_bytes({"fixture": "independently-obtained-verifier-bootstrap"}),
        tc.canonical_json_bytes({"fixture": "qcp-001-experimental-replay-recipe"}),
        tc.canonical_json_bytes({"fixture": "qcp-001-experimental-applicability-profile"}),
        tc.canonical_json_bytes({"fixture": "fixture-retention-policy"}),
        pack_raw,
        tcb_raw,
        tc.canonical_json_bytes({"fixture": "qcp-001-experimental-semantic-bundle"}),
        applicability_receipt_raw,
        applicability_signature_raw,
        pack_receipt_raw,
        pack_signature_raw,
        profile_receipt_raw,
        profile_signature_raw,
        public_key_raw,
        policy_raw,
    ])
    return (
        bound_case,
        bound_pack,
        bound_tcb,
        bound_policy,
        content,
        applicability_qualification,
        pack_qualification,
        {profile_digest: profile_qualification},
        budget_review,
    )


def _verify_qualified_fixture(case: dict[str, Any] | None = None) -> dict[str, Any]:
    (
        bound_case,
        pack,
        tcb,
        policy,
        content,
        applicability,
        pack_qualification,
        profiles,
        budget_review,
    ) = _qualified_fixture(case)
    return tv.verify_transition_case(
        bound_case,
        pack,
        content=content,
        tcb_manifest=tcb,
        tcb_budget_review=budget_review,
        trust_policy=policy,
        applicability_qualification=applicability,
        pack_qualification=pack_qualification,
        observation_profile_qualifications=profiles,
        verifier_bootstrap_raw=tc.canonical_json_bytes({
            "fixture": "independently-obtained-verifier-bootstrap"
        }),
    )


def _temporal_mode_case(mode: str, operator: str) -> dict[str, Any]:
    value = minimal_transition_case()
    profile = value["observation_profiles"][0]
    denominator = next(
        item for item in value["qualification_denominators"]
        if item["subject_kind"] == tp.QualificationSubjectKind.OBSERVATION_PROFILE.value
    )
    profile["coverage_mode"] = mode
    obligation = value["evolution_ir"]["obligations"][0]
    obligation.update({
        "temporal_operator": operator,
        "trigger_id": None,
        "minimum_delay_ms": None,
        "maximum_delay_ms": None,
        "stable_duration_ms": None,
        "commit_event_id": None,
        "rollback_condition_id": None,
    })
    if operator in (
            tc.TemporalOperator.EVENTUALLY_WITHIN.value,
            tc.TemporalOperator.ON_REQUIRE_WITHIN.value,
    ):
        obligation.update({
            "trigger_id": "trigger.gateway-handoff",
            "minimum_delay_ms": 0,
            "maximum_delay_ms": 30_000,
        })
    elif operator == tc.TemporalOperator.HOLD.value:
        obligation["stable_duration_ms"] = 30_000
    elif operator == tc.TemporalOperator.UNTIL.value:
        obligation.update({
            "commit_event_id": "trigger.gateway-handoff",
            "rollback_condition_id": "condition.legacy-interconnect-retired",
        })
    value["derivations"][0]["temporal_outcome"] = tc.TemporalOutcome.INCONCLUSIVE.value
    value["derivations"][0]["effect"] = tc.EvidenceEffect.NO_EFFECT.value
    if mode == tc.ObservationMode.SAMPLED.value:
        denominator.update({
            "denominator_kind": "EXACT_SUBJECTS",
            "event_inventory_digest": None,
            "model_bound_digest": None,
            "assumption_set_digest": None,
        })
        value["evidence_atoms"][0]["coverage_scope"].update({
            "denominator_kind": "EXACT_SUBJECTS",
            "complete": False,
        })
    elif mode == tc.ObservationMode.EVENT_COMPLETE.value:
        profile.update({
            "planned_cadence_ms": None,
            "observed_maximum_gap_ms": None,
            "collection_completeness": "COMPLETE",
            "detection_latency_bound_ms": 500,
            "start_end_coverage": "BOTH",
        })
        denominator.update({
            "denominator_kind": "EXACT_EVENTS",
            "event_inventory_digest": _digest("qualified exact event inventory"),
            "model_bound_digest": None,
            "assumption_set_digest": None,
        })
        value["replay_contract"]["object_bindings"].append(
            _content_binding("EVENT_INVENTORY", denominator["event_inventory_digest"])
        )
        value["evidence_atoms"][0]["coverage_scope"].update({
            "denominator_kind": "EXACT_EVENTS",
            "complete": True,
        })
    else:
        profile.update({
            "planned_cadence_ms": None,
            "observed_maximum_gap_ms": None,
            "collection_completeness": "COMPLETE",
            "detection_latency_bound_ms": None,
            "start_end_coverage": "BOTH",
        })
        denominator.update({
            "denominator_kind": "EXACT_MODEL_BOUND",
            "event_inventory_digest": None,
            "model_bound_digest": _digest("qualified bounded model"),
            "assumption_set_digest": _digest("qualified bounded assumptions"),
        })
        value["replay_contract"]["object_bindings"].extend([
            _content_binding("MODEL_BOUND", denominator["model_bound_digest"]),
            _content_binding("ASSUMPTION_SET", denominator["assumption_set_digest"]),
        ])
        value["evidence_atoms"][0]["coverage_scope"].update({
            "denominator_kind": "EXACT_MODEL_BOUND",
            "complete": True,
        })
    denominator_digest = tc.canonical_digest(denominator)
    profile["qualification_denominator_digest"] = denominator_digest
    for dependency in value["version_contract"]["dependency_digests"]:
        if (
                dependency["kind"] == "QUALIFICATION_DENOMINATOR"
                and dependency["identifier"] == denominator["denominator_id"]
        ):
            dependency["digest"] = denominator_digest
    profile_digest = tc.canonical_digest(profile)
    value["evolution_ir"]["obligations"][0]["observation_profile_digest"] = profile_digest
    value["evolution_ir"]["covered_frame_domain"]["observation_profile_digests"] = [
        profile_digest
    ]
    value["evolution_ir"]["covered_frame_domain"][
        "qualification_denominator_digests"
    ] = [denominator_digest]
    value["evidence_atoms"][0]["observation_profile_digest"] = profile_digest
    value["replay_contract"]["object_bindings"].sort(
        key=lambda item: (item["role"], item["digest"])
    )
    return value


@pytest.mark.parametrize(
    ("mode", "roles", "code"),
    [
        (
            tc.ObservationMode.EVENT_COMPLETE.value,
            ("EVENT_INVENTORY",),
            "EVENT_INVENTORY_CONTENT_BINDING_MISSING",
        ),
        (
            tc.ObservationMode.BOUNDED_MODEL.value,
            ("MODEL_BOUND",),
            "MODEL_BOUND_CONTENT_BINDING_MISSING",
        ),
        (
            tc.ObservationMode.BOUNDED_MODEL.value,
            ("ASSUMPTION_SET",),
            "ASSUMPTION_SET_CONTENT_BINDING_MISSING",
        ),
    ],
)
def test_complete_temporal_denominator_preimages_require_exact_content(
    mode: str,
    roles: tuple[str, ...],
    code: str,
) -> None:
    case = _temporal_mode_case(mode, tc.TemporalOperator.AT_SAMPLE.value)
    bound, *_rest = _qualified_fixture(case)
    hostile = deepcopy(dict(bound))
    hostile["replay_contract"]["object_bindings"] = [
        item for item in hostile["replay_contract"]["object_bindings"]
        if item["role"] not in roles
    ]
    with pytest.raises(tc.TransitionContractError, match=code):
        tc.bind_transition_case_bytes(tc.canonical_json_bytes(hostile))


@pytest.mark.parametrize(
    ("digest_field", "role", "code"),
    [
        (
            "signature_digest",
            "QUALIFICATION_SIGNATURE",
            "QUALIFICATION_SIGNATURE_DIGEST_MISMATCH",
        ),
        (
            "public_key_digest",
            "QUALIFICATION_PUBLIC_KEY",
            "QUALIFICATION_PUBLIC_KEY_DIGEST_MISMATCH",
        ),
    ],
)
def test_verified_qualification_must_match_case_signature_and_public_key_custody(
    digest_field: str,
    role: str,
    code: str,
) -> None:
    (
        bound_case,
        pack,
        tcb,
        policy,
        content,
        applicability,
        pack_qualification,
        profiles,
        budget_review,
    ) = _qualified_fixture()
    hostile = deepcopy(dict(bound_case))
    evidence_binding = next(
        item for item in hostile["qualification_evidence_bindings"]
        if item["receipt_digest"] == applicability.receipt_digest
    )
    old_digest = evidence_binding[digest_field]
    new_digest = _digest(f"detached qualification {digest_field}")
    evidence_binding[digest_field] = new_digest
    replay_binding = next(
        item for item in hostile["replay_contract"]["object_bindings"]
        if item["role"] == role and item["digest"] == old_digest
    )
    replay_binding["digest"] = new_digest
    if digest_field == "public_key_digest":
        hostile["replay_contract"]["object_bindings"].append(
            _content_binding(role, old_digest)
        )
    hostile["replay_contract"]["object_bindings"].sort(
        key=lambda item: (item["role"], item["digest"])
    )
    rebound = tc.bind_transition_case_bytes(tc.canonical_json_bytes(hostile))

    receipt = tv.verify_transition_case(
        rebound,
        pack,
        content=content,
        tcb_manifest=tcb,
        tcb_budget_review=budget_review,
        trust_policy=policy,
        applicability_qualification=applicability,
        pack_qualification=pack_qualification,
        observation_profile_qualifications=profiles,
        verifier_bootstrap_raw=tc.canonical_json_bytes({
            "fixture": "independently-obtained-verifier-bootstrap"
        }),
    )
    assert code in receipt["reason_codes"]


@pytest.mark.parametrize(
    ("mode", "operator"),
    tuple(
        (mode.value, operator.value)
        for mode in tc.ObservationMode
        for operator in tc.TemporalOperator
    ),
)
def test_r2_0_temporal_monitor_is_uniformly_inconclusive_until_r2_2_activation(
        mode: str,
        operator: str) -> None:
    case = _temporal_mode_case(mode, operator)
    bound, _pack, _tcb, policy, content, _app, _pack_qualification, profiles, _review = (
        _qualified_fixture(case)
    )
    obligation = bound["evolution_ir"]["obligations"][0]
    profile_digest = obligation["observation_profile_digest"]

    result = tv.monitor_temporal_obligation(
        bound,
        obligation["obligation_id"],
        profiles[profile_digest],
        trust_policy=policy,
        content=content,
    )

    assert result["coverage_mode"] == mode
    assert result["temporal_operator"] == operator
    assert result["temporal_outcome"] == tc.TemporalOutcome.INCONCLUSIVE.value
    assert result["authoritative"] is False
    assert result["supplies_obligation_support"] is False
    assert "TEMPORAL_MONITOR_NOT_ACTIVATED_R2_0" in result["reason_codes"]
    assert "TEMPORAL_MONITOR_NONAUTHORITATIVE_R2_0" in result["reason_codes"]


def test_temporal_monitor_discloses_missing_exact_evidence_bytes_without_promotion() -> None:
    bound, _pack, _tcb, policy, _content, _app, _pack_qualification, profiles, _review = (
        _qualified_fixture()
    )
    obligation = bound["evolution_ir"]["obligations"][0]
    profile_digest = obligation["observation_profile_digest"]

    result = tv.monitor_temporal_obligation(
        bound,
        obligation["obligation_id"],
        profiles[profile_digest],
        trust_policy=policy,
        content=tv.bind_content_objects([]),
    )

    assert result["temporal_outcome"] == tc.TemporalOutcome.INCONCLUSIVE.value
    assert "EVIDENCE_BYTES_UNAVAILABLE" in result["reason_codes"]
    assert result["supplies_obligation_support"] is False


@pytest.mark.parametrize(
    "mode",
    (tc.ObservationMode.EVENT_COMPLETE.value, tc.ObservationMode.BOUNDED_MODEL.value),
)
@pytest.mark.parametrize("mutation", ("remove", "optional"))
def test_qualified_observation_receipt_is_mandatory_replay_content(
        mode: str,
        mutation: str) -> None:
    value = _temporal_mode_case(mode, tc.TemporalOperator.AT_SAMPLE.value)
    bound, *_rest = _qualified_fixture(value)
    hostile = deepcopy(dict(bound))
    receipt_digest = hostile["observation_profiles"][0]["qualification_receipt_digest"]
    binding = next(
        item for item in hostile["replay_contract"]["object_bindings"]
        if item["role"] == "QUALIFICATION_RECEIPT" and item["digest"] == receipt_digest
    )
    if mutation == "remove":
        hostile["replay_contract"]["object_bindings"].remove(binding)
    else:
        binding["required"] = False

    with pytest.raises(tc.TransitionContractError) as error:
        tc.validate_transition_case(hostile)
    assert error.value.code == "OBSERVATION_QUALIFICATION_CONTENT_BINDING_MISSING"


def test_signed_but_unapproved_qualification_policy_cannot_reach_positive_state() -> None:
    receipt = _verify_qualified_fixture()

    assert receipt["applicability_qualification_state"] is None
    assert receipt["pack_qualification_state"] == tc.QualificationState.EXPERIMENTAL.value
    assert "QUALIFICATION_POLICY_NOT_APPROVED_R2_0" in receipt["reason_codes"]
    assert "DIRECT_TCB_BUDGET_REVIEW_CANNOT_ACTIVATE" in receipt["reason_codes"]
    assert "PACK_TCB_FREEZE_REQUIRED" in receipt["reason_codes"]
    assert receipt["tcb_pair_verified"] is False
    assert receipt["obligations"][0]["evidence_status"] == tc.EvidenceStatus.UNKNOWN.value
    assert receipt["obligations"][0]["valid_support_derivation_ids"] == []
    assert "PACK_DERIVATION_NOT_RECOMPUTED_R2_0" in (
        receipt["obligations"][0]["temporal_outcomes_and_reasons"]
    )
    assert receipt["replay_status"] == (
        tv.ReplayStatus.SEALED_BYTES_PRESENT_INDEPENDENT_REPLAY_NOT_ESTABLISHED.value
    )
    assert receipt["security_status"] == tv.SecurityStatus.SECURITY_EVIDENCE_NOT_VERIFIED.value
    assert receipt["authoritative_gate"] == tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    assert receipt["autonomous_go"] is False


def test_signed_wrong_denominator_is_reported_even_when_registry_is_unapproved() -> None:
    (
        bound,
        pack,
        tcb,
        policy,
        content,
        _applicability,
        pack_qualification,
        profiles,
        budget_review,
    ) = _qualified_fixture()
    wrong_qualification = next(iter(profiles.values()))

    receipt = tv.verify_transition_case(
        bound,
        pack,
        content=content,
        tcb_manifest=tcb,
        tcb_budget_review=budget_review,
        trust_policy=policy,
        applicability_qualification=wrong_qualification,
        pack_qualification=pack_qualification,
        observation_profile_qualifications=profiles,
    )

    assert "QUALIFICATION_DENOMINATOR_MISMATCH" in receipt["reason_codes"]
    assert "QUALIFICATION_SUBJECT_KIND_MISMATCH" in receipt["reason_codes"]
    assert "QUALIFICATION_POLICY_NOT_APPROVED_R2_0" in receipt["reason_codes"]
    assert receipt["applicability_qualification_state"] is None


def test_expired_signed_qualification_diagnostic_is_not_masked_by_unapproved_registry() -> None:
    (
        bound,
        pack,
        tcb,
        policy,
        content,
        applicability,
        pack_qualification,
        profiles,
        budget_review,
    ) = _qualified_fixture(policy_evaluated_at="2026-10-01T00:00:00.000000Z")
    receipt = tv.verify_transition_case(
        bound,
        pack,
        content=content,
        tcb_manifest=tcb,
        tcb_budget_review=budget_review,
        trust_policy=policy,
        applicability_qualification=applicability,
        pack_qualification=pack_qualification,
        observation_profile_qualifications=profiles,
    )

    assert "QUALIFICATION_RECEIPT_EXPIRED" in receipt["reason_codes"]
    assert "QUALIFICATION_POLICY_NOT_APPROVED_R2_0" in receipt["reason_codes"]
    assert receipt["applicability_qualification_state"] is None


@pytest.mark.parametrize(
    "operator",
        (
            tc.TemporalOperator.ALWAYS_DURING.value,
            tc.TemporalOperator.NEVER_DURING.value,
            tc.TemporalOperator.EVENTUALLY_WITHIN.value,
            tc.TemporalOperator.ON_REQUIRE_WITHIN.value,
            tc.TemporalOperator.HOLD.value,
            tc.TemporalOperator.UNTIL.value,
        ),
    )
def test_sampled_no_violation_for_continuous_claim_maps_to_incomplete(operator: str) -> None:
    case = _temporal_mode_case(tc.ObservationMode.SAMPLED.value, operator)
    case["derivations"][0]["temporal_outcome"] = (
        tc.TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value
    )
    case["derivations"][0]["effect"] = tc.EvidenceEffect.SUPPORT.value
    receipt = _verify_qualified_fixture(case)
    obligation = receipt["obligations"][0]

    assert obligation["evidence_status"] == tc.EvidenceStatus.UNKNOWN.value
    assert obligation["valid_support_derivation_ids"] == []
    expected_reason = (
        "SAMPLED_EVENTUAL_INTERVAL_RECEIPT_REQUIRED"
        if operator in (
            tc.TemporalOperator.EVENTUALLY_WITHIN.value,
            tc.TemporalOperator.ON_REQUIRE_WITHIN.value,
        )
        else "SAMPLED_EVIDENCE_OFFERED_FOR_CONTINUOUS_CLAIM"
    )
    assert expected_reason in (
        obligation["temporal_outcomes_and_reasons"]
    )
    assert receipt["authoritative_gate"] == tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    assert receipt["autonomous_go"] is False


def test_uncertified_positive_search_cannot_promote() -> None:
    case = minimal_transition_case()
    case["derivations"][0]["evaluator_kind"] = tc.EvaluatorKind.UNCERTIFIED_SEARCH_EXHAUSTED.value
    receipt = _verify_qualified_fixture(case)
    obligation = receipt["obligations"][0]

    assert obligation["evidence_status"] == tc.EvidenceStatus.UNKNOWN.value
    assert obligation["valid_support_derivation_ids"] == []
    assert "UNCERTIFIED_POSITIVE_SEARCH_CANNOT_PROMOTE" in (
        obligation["temporal_outcomes_and_reasons"]
    )
    assert receipt["authoritative_gate"] == tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    assert receipt["autonomous_go"] is False
