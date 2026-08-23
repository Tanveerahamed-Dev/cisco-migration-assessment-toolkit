from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_runtime_closure as rc


_COMMIT = "a" * 40
_TREE = "b" * 40
_PRODUCER = "runtime-closure-producer.fixture.001"
_RUNTIME_COLLECTOR = "runtime-closure-collector.fixture.001"
_STRUCTURAL_TCB_PRODUCER = "structural-tcb-producer.fixture.001"
_PACK_PRODUCER = "transition-pack-producer.fixture.001"
_BUDGET_PROPOSER = "transition-budget-proposer.fixture.001"
_RELEASE_BUILDER = "release-builder.fixture.001"
_REVIEWER_KEY_ID = "runtime-closure-reviewer-key.fixture.001"

_IDENTITY_DEFAULTS = {
    "producer_id": _PRODUCER,
    "runtime_collector_id": _RUNTIME_COLLECTOR,
    "structural_tcb_producer_id": _STRUCTURAL_TCB_PRODUCER,
    "pack_producer_id": _PACK_PRODUCER,
    "budget_proposer_id": _BUDGET_PROPOSER,
    "release_builder_id": _RELEASE_BUILDER,
}
_INDEPENDENCE_FIELDS = (
    "independent_from_evidence_producer",
    "independent_from_runtime_collector",
    "independent_from_structural_tcb_producer",
    "independent_from_pack_producer",
    "independent_from_budget_proposer",
    "independent_from_release_builder",
)


def _artifact_binding(value: Any, field: str) -> tuple[str, str]:
    """Read the public digest-role contract without duplicating its representation."""

    if isinstance(value, str):
        return f"{field.removesuffix('_digest').replace('_', '-')}.fixture.001", value
    if isinstance(value, Mapping):
        return str(value["artifact_id"]), str(value["role"])
    artifact_id, role = value
    return str(artifact_id), str(role)


def _coverage(*, state: str) -> dict[str, Any]:
    ready = state == rc.RUNTIME_CLOSURE_EVIDENCE_READY
    absent = state == rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT
    coverage_state = {
        rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT: rc.RUNTIME_CLOSURE_COVERAGE_ABSENT,
        rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE: rc.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
        rc.RUNTIME_CLOSURE_EVIDENCE_READY: rc.RUNTIME_CLOSURE_COVERAGE_READY,
    }[state]
    value: dict[str, Any] = {"state": coverage_state}
    value.update({field: ready for field in rc.COVERAGE_BOOLEAN_FIELDS})
    value.update({
        field: (None if absent else 1)
        for field in rc.POSITIVE_COUNTER_FIELDS
    })
    value.update({
        field: (None if absent else (0 if ready else 1))
        for field in rc.ZERO_COUNTER_FIELDS
    })
    return value


def _evidence(
        *,
        state: str = rc.RUNTIME_CLOSURE_EVIDENCE_READY,
        identity_overrides: Mapping[str, str] | None = None,
        ) -> tuple[dict[str, Any], dict[str, bytes]]:
    identities = {**_IDENTITY_DEFAULTS, **(identity_overrides or {})}
    artifacts_by_role: dict[str, dict[str, Any]] = {}
    raw_by_id: dict[str, bytes] = {}
    digest_fields: dict[str, str] = {}

    if state == rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT:
        digest_fields = {
            field: None for field in rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP
        }
    else:
        for field, binding in rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP.items():
            artifact_id, role = _artifact_binding(binding, field)
            raw = tc.canonical_json_bytes({
                "artifact_id": artifact_id,
                "fixture_role": role,
            })
            artifact = {
                "artifact_id": artifact_id,
                "role": role,
                "digest": tc.bytes_digest(raw),
                "raw_bytes": len(raw),
            }
            artifacts_by_role[role] = artifact
            raw_by_id[artifact_id] = raw
            digest_fields[field] = artifact["digest"]

        for role in rc.RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES:
            if role in artifacts_by_role:
                continue
            artifact_id = f"{role.casefold().replace('_', '-')}.fixture.001"
            raw = tc.canonical_json_bytes({
                "artifact_id": artifact_id,
                "fixture_role": role,
            })
            artifacts_by_role[role] = {
                "artifact_id": artifact_id,
                "role": role,
                "digest": tc.bytes_digest(raw),
                "raw_bytes": len(raw),
            }
            raw_by_id[artifact_id] = raw

    value = {
        "schema": rc.TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
        "evidence_id": "transition-runtime-closure-evidence.fixture.001",
        "purpose": rc.RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "state": state,
        **identities,
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        **digest_fields,
        "scope": {
            "scope_kind": rc.RUNTIME_CLOSURE_SCOPE_KIND,
            "substrate": rc.RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            "universal_all_input_behavior": False,
            "portable_across_hosts": False,
            "semantic_equivalence": False,
            "continuous_capture_required": True,
            "deny_by_default_execution_required": True,
        },
        "artifacts": sorted(
            artifacts_by_role.values(),
            key=lambda row: (row["artifact_id"], row["role"], row["digest"]),
        ),
        "coverage": _coverage(state=state),
        "known_gaps": [],
        "claim_boundary": rc.RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
        "authority": {
            "authoritative": False,
            "closure_decision": None,
            "complete_exact_runtime_closure": False,
            "approved_budget": None,
            "qualification_effect": "NONE",
            "promotion_eligible": False,
            "release3_included": False,
        },
    }
    value["known_gaps"] = rc.expected_runtime_closure_gaps(value)
    return value, raw_by_id


def test_runtime_closure_claim_boundary_does_not_imply_missing_policy_artifacts() -> None:
    assert (
        "requirements for candidate closure, not facts established by this envelope"
        in rc.RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY
    )
    assert (
        "under an immutable content-addressed executable allow-set"
        not in rc.RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY
    )


def _public_key_raw(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _bindings(evidence: rc.BoundTransitionRuntimeClosureEvidence) -> dict[str, Any]:
    return {
        "schema": rc.RUNTIME_CLOSURE_REVIEW_BINDINGS_SCHEMA,
        "selected_commit": evidence["selected_commit"],
        "selected_tree": evidence["selected_tree"],
        **{
            field: evidence[field]
            for field in rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP
        },
        "runtime_closure_evidence_digest": evidence.digest,
        "runtime_closure_evidence_state": evidence["state"],
        "runtime_closure_coverage_state": evidence["coverage"]["state"],
    }


def _receipt(
        evidence: rc.BoundTransitionRuntimeClosureEvidence,
        *,
        decision: str = rc.RUNTIME_CLOSURE_REVIEW_COMPLETE,
        ) -> dict[str, Any]:
    bindings = _bindings(evidence)
    return {
        "schema": rc.RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA,
        "receipt_id": "transition-runtime-closure-review.fixture.001",
        "purpose": rc.RUNTIME_CLOSURE_REVIEW_PURPOSE,
        **{key: value for key, value in bindings.items() if key != "schema"},
        "decision": decision,
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "reviewer_key_id": _REVIEWER_KEY_ID,
    }


def _policy(
        evidence: rc.BoundTransitionRuntimeClosureEvidence,
        public_key_raw: bytes) -> dict[str, Any]:
    return {
        "schema": rc.RUNTIME_CLOSURE_REVIEW_TRUST_POLICY_SCHEMA,
        "policy_kind": rc.RUNTIME_CLOSURE_REVIEW_POLICY_KIND,
        "policy_id": "transition-runtime-closure-review-policy.fixture",
        "policy_version": "1.0.0",
        "purpose": rc.RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "evaluated_at": "2026-08-23T00:00:00.000000Z",
        "trusted_keys": [{
            "schema": rc.RUNTIME_CLOSURE_REVIEW_TRUSTED_KEY_SCHEMA,
            "key_id": _REVIEWER_KEY_ID,
            "public_key_digest": tc.bytes_digest(public_key_raw),
            "reviewer_kind": rc.RUNTIME_CLOSURE_REVIEW_REVIEWER_KIND,
            "independent_from_evidence_producer": True,
            "independent_from_runtime_collector": True,
            "independent_from_structural_tcb_producer": True,
            "independent_from_pack_producer": True,
            "independent_from_budget_proposer": True,
            "independent_from_release_builder": True,
            "authorizations": [{
                "schema": rc.RUNTIME_CLOSURE_REVIEW_AUTHORIZATION_SCHEMA,
                "purpose": rc.RUNTIME_CLOSURE_REVIEW_PURPOSE,
                "target_schema_version": rc.RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA,
                "reviewer_role": rc.RUNTIME_CLOSURE_REVIEW_REVIEWER_ROLE,
                "substrate": rc.RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            }],
            "allowed_subjects": [{
                "selected_commit": evidence["selected_commit"],
                "selected_tree": evidence["selected_tree"],
                "runtime_closure_evidence_digest": evidence.digest,
            }],
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2027-01-01T00:00:00.000000Z",
        }],
        "revoked_receipt_digests": [],
    }


def _material(
        *,
        state: str = rc.RUNTIME_CLOSURE_EVIDENCE_READY,
        decision: str = rc.RUNTIME_CLOSURE_REVIEW_COMPLETE,
        identity_overrides: Mapping[str, str] | None = None,
        ) -> dict[str, Any]:
    evidence_value, artifact_raw_by_id = _evidence(
        state=state,
        identity_overrides=identity_overrides,
    )
    evidence_raw = tc.canonical_json_bytes(evidence_value)
    evidence = rc.bind_transition_runtime_closure_evidence_bytes(
        evidence_raw,
        artifact_raw_by_id,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_raw(private_key)
    policy = _policy(evidence, public_key_raw)
    policy_raw = tc.canonical_json_bytes(policy)
    receipt = _receipt(
        evidence,
        decision=decision,
    )
    receipt_raw = tc.canonical_json_bytes(receipt)
    signature = {
        "schema": rc.RUNTIME_CLOSURE_REVIEW_SIGNATURE_SCHEMA,
        "purpose": rc.RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "signer_key_id": receipt["reviewer_key_id"],
        "algorithm": rc.RUNTIME_CLOSURE_REVIEW_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(
            private_key.sign(
                rc.runtime_closure_review_signing_material(receipt_raw, policy_raw)
            )
        ).decode("ascii"),
    }
    return {
        "artifact_raw_by_id": artifact_raw_by_id,
        "bindings": _bindings(evidence),
        "evidence": evidence,
        "evidence_raw": evidence_raw,
        "policy": policy,
        "policy_raw": policy_raw,
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "receipt": receipt,
        "receipt_raw": receipt_raw,
        "signature": signature,
        "signature_raw": tc.canonical_json_bytes(signature),
    }


def _resign(material: dict[str, Any]) -> None:
    material["policy_raw"] = tc.canonical_json_bytes(material["policy"])
    material["receipt_raw"] = tc.canonical_json_bytes(material["receipt"])
    material["signature"]["payload_digest"] = tc.bytes_digest(
        material["receipt_raw"]
    )
    material["signature"]["signature_base64"] = base64.b64encode(
        material["private_key"].sign(
            rc.runtime_closure_review_signing_material(
                material["receipt_raw"], material["policy_raw"]
            )
        )
    ).decode("ascii")
    material["signature_raw"] = tc.canonical_json_bytes(material["signature"])


def _verify(material: Mapping[str, Any]) -> rc.VerifiedTransitionRuntimeClosureReview:
    return rc.verify_transition_runtime_closure_review(
        material["evidence"],
        material["receipt_raw"],
        material["signature_raw"],
        rc.bind_external_runtime_closure_review_trust_policy_bytes(
            material["policy_raw"]
        ),
        material["public_key_raw"],
        material["bindings"],
        tc.bytes_digest(material["policy_raw"]),
    )


def _require_current(
        material: Mapping[str, Any],
        verified: rc.VerifiedTransitionRuntimeClosureReview,
        ) -> rc.VerifiedTransitionRuntimeClosureReview:
    policy = rc.bind_external_runtime_closure_review_trust_policy_bytes(
        material["policy_raw"]
    )
    return rc.require_verified_transition_runtime_closure_review(
        verified,
        policy,
        tc.bytes_digest(material["policy_raw"]),
    )


def _refuses(call) -> rc.RuntimeClosureReviewError:
    with pytest.raises(rc.RuntimeClosureReviewError) as caught:
        call()
    assert caught.value.code == str(caught.value)
    return caught.value


def test_protocol_labels_roles_and_denominators_are_exact_and_non_vacuous() -> None:
    assert (
        rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT,
        rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        rc.RUNTIME_CLOSURE_EVIDENCE_READY,
    ) == (
        "ABSENT",
        "COLLECTED_INCOMPLETE",
        "READY_FOR_EXTERNAL_REVIEW",
    )
    assert (
        rc.RUNTIME_CLOSURE_REVIEW_COMPLETE,
        rc.RUNTIME_CLOSURE_REVIEW_INCOMPLETE,
    ) == (
        "COMPLETE_EXACT_RUNTIME_CLOSURE",
        "INCOMPLETE_RUNTIME_CLOSURE",
    )
    assert rc.RUNTIME_CLOSURE_SCOPE_KIND == "EXACT_SELECTED_R2_0_RUNTIME_PROFILE"
    assert rc.RUNTIME_CLOSURE_REVIEW_SUBSTRATE == "DECLARATIVE_DSL_ONLY"
    assert (
        rc.RUNTIME_CLOSURE_COVERAGE_ABSENT,
        rc.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
        rc.RUNTIME_CLOSURE_COVERAGE_READY,
    ) == (
        "NOT_MEASURED",
        "MEASURED_INCOMPLETE",
        "MEASURED_CANDIDATE_COMPLETE",
    )

    expected_role_map = (
        ("reference_runtime_inventory_v1_digest", "REFERENCE_RUNTIME_INVENTORY_V1"),
        ("structural_census_digest", "STRUCTURAL_TCB_CENSUS"),
        ("prototype_measurement_digest", "PROTOTYPE_MEASUREMENTS"),
        ("dsl_interpreter_digest", "DSL_INTERPRETER_SOURCE"),
        ("prototype_program_digest", "PROTOTYPE_PROGRAM"),
        ("prototype_pack_manifest_digest", "PROTOTYPE_PACK_MANIFEST"),
        ("prototype_tcb_manifest_digest", "PROTOTYPE_TCB_MANIFEST"),
        ("supported_execution_denominator_digest", "SUPPORTED_EXECUTION_DENOMINATOR"),
        ("installed_distribution_digest", "INSTALLED_DISTRIBUTION"),
        ("exact_runtime_profile_digest", "EXACT_RUNTIME_PROFILE"),
        (
            "executable_allow_set_digest",
            "CONTENT_ADDRESSED_EXECUTABLE_ALLOW_SET",
        ),
        ("enforcement_policy_digest", "DENY_BY_DEFAULT_EXECUTION_POLICY"),
        ("collector_tcb_digest", "COLLECTOR_AND_VERIFIER_TCB"),
        (
            "execution_environment_manifest_digest",
            "EXECUTION_ENVIRONMENT_MANIFEST",
        ),
    )
    additional_roles = (
        "STATIC_TRANSITIVE_DEPENDENCY_CLOSURE",
        "PROCESS_TREE_LIFETIME_TRACE",
        "EXECUTABLE_MAPPING_LOAD_UNLOAD_TRACE",
        "FILE_IDENTITY_AND_HANDLE_TRACE",
        "LOADER_RESOLUTION_TRACE",
        "CRYPTO_PROVIDER_TRACE",
        "PLATFORM_BOOT_ATTESTATION",
        "COLLECTOR_LOSS_AND_RECONCILIATION",
    )
    assert tuple(rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP.items()) == expected_role_map
    assert rc.RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES == (
        *(role for _, role in expected_role_map),
        *additional_roles,
    )

    coverage_field_sets = tuple(
        set(fields)
        for fields in (
            rc.COVERAGE_BOOLEAN_FIELDS,
            rc.POSITIVE_COUNTER_FIELDS,
            rc.ZERO_COUNTER_FIELDS,
        )
    )
    assert all(coverage_field_sets)
    assert not (coverage_field_sets[0] & coverage_field_sets[1])
    assert not (coverage_field_sets[0] & coverage_field_sets[2])
    assert not (coverage_field_sets[1] & coverage_field_sets[2])


def test_schema_projects_every_protocol_document_without_minting_authority() -> None:
    schema_path = (
        Path(rc.__file__).parent
        / "schemas"
        / "atlas-r2-transition-runtime-closure-v2.schema.json"
    )
    schema = json.loads(schema_path.read_bytes())
    Draft202012Validator.check_schema(schema)
    evidence_validator = Draft202012Validator(schema)
    for state in (
            rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT,
            rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
            rc.RUNTIME_CLOSURE_EVIDENCE_READY,
    ):
        evidence_validator.validate(_evidence(state=state)[0])

    material = _material()
    documents = {
        "reviewBindings": material["bindings"],
        "reviewReceipt": material["receipt"],
        "reviewSignature": material["signature"],
        "trustPolicy": material["policy"],
    }
    for definition, value in documents.items():
        projection = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{definition}",
            "$defs": schema["$defs"],
        }
        Draft202012Validator(projection).validate(value)


def test_schema_ready_projection_rejects_incomplete_or_contradictory_closure() -> None:
    schema_path = (
        Path(rc.__file__).parent
        / "schemas"
        / "atlas-r2-transition-runtime-closure-v2.schema.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_bytes()))
    ready = _evidence(state=rc.RUNTIME_CLOSURE_EVIDENCE_READY)[0]

    missing_role = deepcopy(ready)
    missing_role["artifacts"].pop()

    duplicate_role = deepcopy(ready)
    duplicate_role["artifacts"][-1]["role"] = duplicate_role["artifacts"][0]["role"]

    false_coverage = deepcopy(ready)
    false_coverage["coverage"][rc.COVERAGE_BOOLEAN_FIELDS[0]] = False

    zero_positive_counter = deepcopy(ready)
    zero_positive_counter["coverage"][rc.POSITIVE_COUNTER_FIELDS[0]] = 0

    nonzero_failure_counter = deepcopy(ready)
    nonzero_failure_counter["coverage"][rc.ZERO_COUNTER_FIELDS[0]] = 1

    known_gap = deepcopy(ready)
    known_gap["known_gaps"] = ["UNRESOLVED_READY_GAP"]

    for contradictory in (
            missing_role,
            duplicate_role,
            false_coverage,
            zero_positive_counter,
            nonzero_failure_counter,
            known_gap,
    ):
        assert not validator.is_valid(contradictory)


@pytest.mark.parametrize(
    "state",
    (
        rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT,
        rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        rc.RUNTIME_CLOSURE_EVIDENCE_READY,
    ),
)
def test_evidence_states_are_exact_byte_bound_but_never_self_complete(
        state: str) -> None:
    value, artifact_raw_by_id = _evidence(state=state)
    raw = tc.canonical_json_bytes(value)

    assert rc.validate_transition_runtime_closure_evidence(value) == value
    bound = rc.bind_transition_runtime_closure_evidence_bytes(raw, artifact_raw_by_id)
    assert bound.digest == tc.bytes_digest(raw)
    assert bound["state"] == state
    assert bound["known_gaps"] == rc.expected_runtime_closure_gaps(bound)
    assert bound["authority"] == {
        "authoritative": False,
        "closure_decision": None,
        "complete_exact_runtime_closure": False,
        "approved_budget": None,
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "release3_included": False,
    }
    assert rc.require_bound_transition_runtime_closure_evidence(bound) is bound

    if state == rc.RUNTIME_CLOSURE_EVIDENCE_ABSENT:
        assert bound["artifacts"] == []
        assert artifact_raw_by_id == {}
        assert all(
            bound[field] is None
            for field in rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP
        )


@pytest.mark.parametrize(
    ("field", "hostile_value"),
    (
        ("authoritative", True),
        ("closure_decision", rc.RUNTIME_CLOSURE_REVIEW_COMPLETE),
        ("complete_exact_runtime_closure", True),
        ("approved_budget", {}),
        ("qualification_effect", "QUALIFIED"),
        ("promotion_eligible", True),
        ("release3_included", True),
    ),
)
def test_evidence_authority_laundering_is_refused(
        field: str, hostile_value: Any) -> None:
    value, artifact_raw_by_id = _evidence()
    value["authority"][field] = hostile_value
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(value), artifact_raw_by_id
        )
    )


def test_all_public_review_validators_accept_one_exact_material_set() -> None:
    material = _material()

    assert rc.validate_transition_runtime_closure_evidence(
        tc.parse_canonical_json_bytes(material["evidence_raw"], require_canonical=True)
    ) == dict(material["evidence"])
    assert rc.validate_runtime_closure_review_bindings(
        material["bindings"]
    ) == material["bindings"]
    assert rc.validate_runtime_closure_review_receipt(
        material["receipt"]
    ) == material["receipt"]
    assert rc.validate_runtime_closure_review_signature(
        material["signature"]
    ) == material["signature"]
    assert rc.validate_runtime_closure_review_trust_policy(
        material["policy"]
    ) == material["policy"]

    bound_policy = rc.bind_external_runtime_closure_review_trust_policy_bytes(
        material["policy_raw"]
    )
    assert bound_policy.digest == tc.bytes_digest(material["policy_raw"])


def test_evidence_rejects_missing_extra_swapped_and_rechained_artifacts() -> None:
    value, artifact_raw_by_id = _evidence()
    artifact_ids = sorted(artifact_raw_by_id)
    assert len(artifact_ids) >= 2

    missing = dict(artifact_raw_by_id)
    missing.pop(artifact_ids[0])
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(value), missing
        )
    )

    extra = dict(artifact_raw_by_id)
    extra["unexpected-artifact.fixture.001"] = b"unexpected"
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(value), extra
        )
    )

    swapped = dict(artifact_raw_by_id)
    swapped[artifact_ids[0]], swapped[artifact_ids[1]] = (
        swapped[artifact_ids[1]], swapped[artifact_ids[0]]
    )
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(value), swapped
        )
    )

    hostile = deepcopy(value)
    hostile["artifacts"][0]["raw_bytes"] += 1
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(hostile), artifact_raw_by_id
        )
    )

    hostile = deepcopy(value)
    digest_fields = list(rc.RUNTIME_CLOSURE_DIGEST_ROLE_MAP)
    hostile[digest_fields[0]], hostile[digest_fields[1]] = (
        hostile[digest_fields[1]], hostile[digest_fields[0]]
    )
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(hostile), artifact_raw_by_id
        )
    )

    hostile = deepcopy(value)
    hostile["artifacts"][1]["role"] = hostile["artifacts"][0]["role"]
    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(hostile), artifact_raw_by_id
        )
    )


@pytest.mark.parametrize(
    "attack", ("coverage_state", "boolean", "positive", "zero", "gap")
)
def test_false_ready_coverage_claims_are_refused(attack: str) -> None:
    value, artifact_raw_by_id = _evidence()
    if attack == "coverage_state":
        value["coverage"]["state"] = rc.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    elif attack == "boolean":
        value["coverage"][next(iter(rc.COVERAGE_BOOLEAN_FIELDS))] = False
    elif attack == "positive":
        value["coverage"][next(iter(rc.POSITIVE_COUNTER_FIELDS))] = 0
    elif attack == "zero":
        value["coverage"][next(iter(rc.ZERO_COUNTER_FIELDS))] = 1
    else:
        value["known_gaps"] = ["LOSSLESS_CAPTURE_NOT_ESTABLISHED"]

    _refuses(
        lambda: rc.bind_transition_runtime_closure_evidence_bytes(
            tc.canonical_json_bytes(value), artifact_raw_by_id
        )
    )


def test_ready_evidence_can_receive_a_separate_signed_complete_decision() -> None:
    material = _material()
    verified = _verify(material)

    assert verified.complete is True
    assert verified.decision == rc.RUNTIME_CLOSURE_REVIEW_COMPLETE
    assert verified.evidence_state == rc.RUNTIME_CLOSURE_EVIDENCE_READY
    assert verified.evidence_digest == material["evidence"].digest
    assert verified.bindings_digest == tc.canonical_digest(material["bindings"])
    assert verified.selected_commit == _COMMIT
    current = _require_current(material, verified)
    assert current is not verified
    assert current.complete is True
    assert current.policy_digest == tc.bytes_digest(material["policy_raw"])
    assert current.bindings_digest == verified.bindings_digest
    with pytest.raises(AttributeError):
        verified.decision = rc.RUNTIME_CLOSURE_REVIEW_INCOMPLETE


def test_complete_decision_over_incomplete_evidence_is_refused() -> None:
    material = _material(state=rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE)
    _refuses(lambda: _verify(material))

    material = _material(
        state=rc.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        decision=rc.RUNTIME_CLOSURE_REVIEW_INCOMPLETE,
    )
    verified = _verify(material)
    assert verified.complete is False
    assert verified.decision == rc.RUNTIME_CLOSURE_REVIEW_INCOMPLETE


def test_signature_key_policy_subject_and_candidate_drift_are_refused() -> None:
    material = _material()
    material["externally_selected_policy_digest"] = "sha256:" + "0" * 64
    _refuses(
        lambda: rc.verify_transition_runtime_closure_review(
            material["evidence"],
            material["receipt_raw"],
            material["signature_raw"],
            rc.bind_external_runtime_closure_review_trust_policy_bytes(
                material["policy_raw"]
            ),
            material["public_key_raw"],
            material["bindings"],
            material["externally_selected_policy_digest"],
        )
    )

    material = _material()
    hostile_signature = deepcopy(material["signature"])
    hostile_signature["signature_base64"] = base64.b64encode(b"\x00" * 64).decode(
        "ascii"
    )
    material["signature_raw"] = tc.canonical_json_bytes(hostile_signature)
    _refuses(lambda: _verify(material))

    material = _material()
    material["public_key_raw"] = _public_key_raw(Ed25519PrivateKey.generate())
    _refuses(lambda: _verify(material))

    for independence_field in _INDEPENDENCE_FIELDS:
        material = _material()
        policy = deepcopy(material["policy"])
        policy["trusted_keys"][0][independence_field] = False
        _refuses(
            lambda policy=policy: (
                rc.bind_external_runtime_closure_review_trust_policy_bytes(
                    tc.canonical_json_bytes(policy)
                )
            )
        )

    material = _material()
    material["policy"]["trusted_keys"][0]["allowed_subjects"][0][
        "selected_tree"
    ] = "c" * 40
    _resign(material)
    _refuses(lambda: _verify(material))

    material = _material()
    bindings = deepcopy(material["bindings"])
    bindings["selected_tree"] = "c" * 40
    material["bindings"] = bindings
    _refuses(lambda: _verify(material))


@pytest.mark.parametrize("identity_field", tuple(_IDENTITY_DEFAULTS))
def test_reviewer_identity_collisions_are_fail_closed(identity_field: str) -> None:
    material = _material(
        identity_overrides={identity_field: _REVIEWER_KEY_ID}
    )
    _refuses(lambda: _verify(material))


def test_review_time_and_revocation_policy_drift_are_fail_closed() -> None:
    material = _material()
    original_receipt_raw = material["receipt_raw"]
    material["policy"]["revoked_receipt_digests"] = [
        tc.bytes_digest(material["receipt_raw"])
    ]
    _resign(material)
    assert material["receipt_raw"] == original_receipt_raw
    _refuses(lambda: _verify(material))

    material = _material()
    material["receipt"]["valid_until"] = "2026-08-22T12:00:00.000000Z"
    _resign(material)
    _refuses(lambda: _verify(material))


def test_plain_or_mutated_verified_values_never_acquire_closure_authority() -> None:
    material = _material()
    current_policy = rc.bind_external_runtime_closure_review_trust_policy_bytes(
        material["policy_raw"]
    )
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            {"decision": rc.RUNTIME_CLOSURE_REVIEW_COMPLETE},
            current_policy,
            tc.bytes_digest(material["policy_raw"]),
        )
    )

    verified = _verify(material)
    object.__setattr__(verified, "decision", rc.RUNTIME_CLOSURE_REVIEW_INCOMPLETE)
    _refuses(lambda: _require_current(material, verified))


def test_retained_historical_policy_bytes_are_reverified_after_verification() -> None:
    material = _material()
    verified = _verify(material)
    policy = deepcopy(material["policy"])
    policy["policy_version"] = "1.0.1"
    object.__setattr__(verified, "_trust_policy_raw", tc.canonical_json_bytes(policy))
    _refuses(lambda: _require_current(material, verified))


def test_signature_covers_receipt_while_current_policy_remains_live_authority() -> None:
    material = _material()
    original_signing_material = rc.runtime_closure_review_signing_material(
        material["receipt_raw"], material["policy_raw"]
    )
    original_signature = material["signature"]["signature_base64"]
    verified = _verify(material)

    successor = deepcopy(material["policy"])
    successor["policy_version"] = "1.0.1"
    successor["evaluated_at"] = "2026-08-24T00:00:00.000000Z"
    successor_raw = tc.canonical_json_bytes(successor)
    assert rc.runtime_closure_review_signing_material(
        material["receipt_raw"], successor_raw
    ) == original_signing_material
    assert base64.b64encode(
        material["private_key"].sign(original_signing_material)
    ).decode("ascii") == original_signature

    fresh = rc.require_verified_transition_runtime_closure_review(
        verified,
        rc.bind_external_runtime_closure_review_trust_policy_bytes(successor_raw),
        tc.bytes_digest(successor_raw),
    )
    assert fresh.signature_digest == verified.signature_digest
    assert fresh.policy_digest == tc.bytes_digest(successor_raw)

    revoked = deepcopy(successor)
    revoked["revoked_receipt_digests"] = [tc.bytes_digest(material["receipt_raw"])]
    revoked_raw = tc.canonical_json_bytes(revoked)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            fresh,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(revoked_raw),
            tc.bytes_digest(revoked_raw),
        )
    )


def test_every_use_rechecks_external_current_policy_revocation_and_rollback() -> None:
    material = _material()
    verified = _verify(material)

    successor = deepcopy(material["policy"])
    successor["policy_version"] = "1.0.1"
    successor["evaluated_at"] = "2026-08-24T00:00:00.000000Z"
    successor_raw = tc.canonical_json_bytes(successor)
    fresh = rc.require_verified_transition_runtime_closure_review(
        verified,
        rc.bind_external_runtime_closure_review_trust_policy_bytes(successor_raw),
        tc.bytes_digest(successor_raw),
    )
    assert fresh is not verified
    assert fresh.complete is True
    assert fresh.policy_digest == tc.bytes_digest(successor_raw)
    assert fresh.evaluated_at == successor["evaluated_at"]

    revoked = deepcopy(successor)
    revoked["revoked_receipt_digests"] = [tc.bytes_digest(material["receipt_raw"])]
    revoked_raw = tc.canonical_json_bytes(revoked)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(revoked_raw),
            tc.bytes_digest(revoked_raw),
        )
    )

    deny_all = deepcopy(material["policy"])
    deny_all["policy_version"] = "1.0.2"
    deny_all["evaluated_at"] = "2026-08-24T00:00:00.000000Z"
    deny_all["trusted_keys"] = []
    deny_all_raw = tc.canonical_json_bytes(deny_all)
    assert rc.validate_runtime_closure_review_trust_policy(deny_all) == deny_all
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(deny_all_raw),
            tc.bytes_digest(deny_all_raw),
        )
    )

    rollback = deepcopy(material["policy"])
    rollback["policy_version"] = "0.9.0"
    rollback["evaluated_at"] = "2026-08-22T12:00:00.000000Z"
    rollback_raw = tc.canonical_json_bytes(rollback)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(rollback_raw),
            tc.bytes_digest(rollback_raw),
        )
    )

    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(successor_raw),
            tc.bytes_digest(material["policy_raw"]),
        )
    )

    subject_removed = deepcopy(successor)
    subject_removed["trusted_keys"][0]["allowed_subjects"][0]["selected_tree"] = (
        "c" * 40
    )
    subject_removed_raw = tc.canonical_json_bytes(subject_removed)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(
                subject_removed_raw
            ),
            tc.bytes_digest(subject_removed_raw),
        )
    )

    key_changed = deepcopy(successor)
    key_changed["trusted_keys"][0]["public_key_digest"] = "sha256:" + "0" * 64
    key_changed_raw = tc.canonical_json_bytes(key_changed)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(key_changed_raw),
            tc.bytes_digest(key_changed_raw),
        )
    )

    expired = deepcopy(successor)
    expired["policy_version"] = "1.0.3"
    expired["evaluated_at"] = "2026-10-01T00:00:00.000000Z"
    expired_raw = tc.canonical_json_bytes(expired)
    _refuses(
        lambda: rc.require_verified_transition_runtime_closure_review(
            verified,
            rc.bind_external_runtime_closure_review_trust_policy_bytes(expired_raw),
            tc.bytes_digest(expired_raw),
        )
    )


def test_bound_evidence_retains_and_rechecks_exact_artifact_bytes() -> None:
    material = _material()
    bound = material["evidence"]
    assert rc.require_bound_transition_runtime_closure_evidence(bound) is bound

    source = material["artifact_raw_by_id"]
    source_artifact_id = sorted(source)[0]
    source[source_artifact_id] = b"caller-side substitution"
    assert rc.require_bound_transition_runtime_closure_evidence(bound) is bound

    retained = dict(bound._artifact_raw_by_id)
    artifact_id = sorted(retained)[0]
    retained[artifact_id] = b"substituted"
    object.__setattr__(bound, "_artifact_raw_by_id", retained)
    _refuses(lambda: rc.require_bound_transition_runtime_closure_evidence(bound))
