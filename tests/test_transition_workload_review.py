from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_workload_review as wr


_COMMIT = "a" * 40
_TREE = "b" * 40
_PRODUCER = "workload-producer.fixture.001"
_REVIEWER_KEY_ID = "workload-reviewer-key.fixture.001"
_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _ROOT / "cisco_toolkit/schemas/atlas-r2-transition-workload-review-v1.schema.json"


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def _evidence(
        *,
        state: str = wr.WORKLOAD_EVIDENCE_READY,
        producer_id: str = _PRODUCER) -> dict[str, Any]:
    artifacts = [] if state == wr.WORKLOAD_EVIDENCE_ABSENT else [
        {
            "artifact_id": "workload-corpus.fixture.001",
            "role": "EXTERNAL_WORKLOAD_CORPUS_MANIFEST",
            "digest": _digest("workload corpus"),
            "raw_bytes": 1234,
        },
        {
            "artifact_id": "workload-receipts.fixture.001",
            "role": "EXTERNAL_WORKLOAD_EXECUTION_RECEIPTS",
            "digest": _digest("workload receipts"),
            "raw_bytes": 5678,
        },
    ]
    return {
        "schema": wr.TRANSITION_WORKLOAD_EVIDENCE_SCHEMA,
        "evidence_id": "transition-workload-evidence.fixture.001",
        "purpose": wr.WORKLOAD_REVIEW_PURPOSE,
        "state": state,
        "producer_id": producer_id,
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        **{field: _digest(field) for field in wr.WORKLOAD_BINDING_DIGEST_FIELDS},
        "artifacts": artifacts,
        "known_gaps": (
            ["REPRESENTATIVE_WORKLOAD_EVIDENCE_NOT_SUPPLIED"]
            if state == wr.WORKLOAD_EVIDENCE_ABSENT
            else ["FIELD_SELECTION_REMAINS_EXTERNAL_REVIEW_JUDGMENT"]
        ),
        "claim_boundary": wr.WORKLOAD_EVIDENCE_CLAIM_BOUNDARY,
        "authority": {
            "authoritative": False,
            "adequacy_decision": None,
            "approved_budget": None,
            "qualification_effect": "NONE",
            "promotion_eligible": False,
            "release3_included": False,
        },
    }


def _public_key_raw(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _bindings(evidence: wr.BoundTransitionWorkloadEvidence) -> dict[str, Any]:
    return {
        "schema": wr.WORKLOAD_REVIEW_BINDINGS_SCHEMA,
        "selected_commit": evidence["selected_commit"],
        "selected_tree": evidence["selected_tree"],
        **{field: evidence[field] for field in wr.WORKLOAD_BINDING_DIGEST_FIELDS},
        "workload_evidence_digest": evidence.digest,
        "workload_evidence_state": evidence["state"],
    }


def _receipt(
        evidence: wr.BoundTransitionWorkloadEvidence,
        *,
        decision: str = wr.WORKLOAD_REVIEW_ADEQUATE) -> dict[str, Any]:
    bindings = _bindings(evidence)
    return {
        "schema": wr.WORKLOAD_REVIEW_RECEIPT_SCHEMA,
        "receipt_id": "transition-workload-review.fixture.001",
        "purpose": wr.WORKLOAD_REVIEW_PURPOSE,
        **{key: value for key, value in bindings.items() if key != "schema"},
        "decision": decision,
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "reviewer_key_id": _REVIEWER_KEY_ID,
    }


def _policy(
        evidence: wr.BoundTransitionWorkloadEvidence,
        receipt: dict[str, Any],
        public_key_raw: bytes) -> dict[str, Any]:
    return {
        "schema": wr.WORKLOAD_REVIEW_TRUST_POLICY_SCHEMA,
        "policy_kind": wr.WORKLOAD_REVIEW_POLICY_KIND,
        "policy_id": "transition-workload-review-policy.fixture",
        "policy_version": "1.0.0",
        "purpose": wr.WORKLOAD_REVIEW_PURPOSE,
        "evaluated_at": "2026-08-23T00:00:00.000000Z",
        "trusted_keys": [{
            "schema": wr.WORKLOAD_REVIEW_TRUSTED_KEY_SCHEMA,
            "key_id": receipt["reviewer_key_id"],
            "public_key_digest": tc.bytes_digest(public_key_raw),
            "reviewer_kind": wr.WORKLOAD_REVIEW_REVIEWER_KIND,
            "independent_from_workload_producer": True,
            "independent_from_measurement_producer": True,
            "independent_from_budget_proposer": True,
            "independent_from_release_builder": True,
            "authorizations": [{
                "schema": wr.WORKLOAD_REVIEW_AUTHORIZATION_SCHEMA,
                "purpose": wr.WORKLOAD_REVIEW_PURPOSE,
                "target_schema_version": wr.WORKLOAD_REVIEW_RECEIPT_SCHEMA,
                "reviewer_role": wr.WORKLOAD_REVIEW_REVIEWER_ROLE,
                "substrate": wr.WORKLOAD_REVIEW_SUBSTRATE,
            }],
            "allowed_subjects": [{
                "selected_commit": evidence["selected_commit"],
                "selected_tree": evidence["selected_tree"],
                "workload_evidence_digest": evidence.digest,
            }],
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2027-01-01T00:00:00.000000Z",
        }],
        "revoked_receipt_digests": [],
    }


def _material(
        *,
        state: str = wr.WORKLOAD_EVIDENCE_READY,
        decision: str = wr.WORKLOAD_REVIEW_ADEQUATE,
        producer_id: str = _PRODUCER) -> dict[str, Any]:
    evidence_value = _evidence(state=state, producer_id=producer_id)
    evidence_raw = tc.canonical_json_bytes(evidence_value)
    evidence = wr.bind_transition_workload_evidence_bytes(evidence_raw)
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_raw(private_key)
    receipt = _receipt(evidence, decision=decision)
    policy = _policy(evidence, receipt, public_key_raw)
    receipt_raw = tc.canonical_json_bytes(receipt)
    policy_raw = tc.canonical_json_bytes(policy)
    signature = {
        "schema": wr.WORKLOAD_REVIEW_SIGNATURE_SCHEMA,
        "purpose": wr.WORKLOAD_REVIEW_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "signer_key_id": receipt["reviewer_key_id"],
        "algorithm": wr.WORKLOAD_REVIEW_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(
            private_key.sign(wr.workload_review_signing_material(receipt_raw, policy_raw))
        ).decode("ascii"),
    }
    return {
        "evidence": evidence,
        "evidence_raw": evidence_raw,
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "receipt": receipt,
        "receipt_raw": receipt_raw,
        "policy": policy,
        "policy_raw": policy_raw,
        "signature": signature,
        "signature_raw": tc.canonical_json_bytes(signature),
        "bindings": _bindings(evidence),
    }


def _verify(material: dict[str, Any]) -> wr.VerifiedTransitionWorkloadReview:
    return wr.verify_transition_workload_review(
        material["evidence"],
        material["receipt_raw"],
        material["signature_raw"],
        wr.bind_external_workload_review_trust_policy_bytes(material["policy_raw"]),
        material["public_key_raw"],
        material["bindings"],
        tc.bytes_digest(material["policy_raw"]),
    )


def _require_current(
        material: dict[str, Any],
        verified: wr.VerifiedTransitionWorkloadReview,
        ) -> wr.VerifiedTransitionWorkloadReview:
    policy = wr.bind_external_workload_review_trust_policy_bytes(
        material["policy_raw"]
    )
    return wr.require_verified_transition_workload_review(
        verified,
        policy,
        tc.bytes_digest(material["policy_raw"]),
    )


def _refuses(call, code: str) -> None:
    with pytest.raises(wr.WorkloadReviewError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == code


def _schema_validator(definition: str) -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator({
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    })


def test_evidence_envelope_is_canonical_but_never_self_adequate() -> None:
    for state in (wr.WORKLOAD_EVIDENCE_ABSENT, wr.WORKLOAD_EVIDENCE_READY):
        raw = tc.canonical_json_bytes(_evidence(state=state))
        bound = wr.bind_transition_workload_evidence_bytes(raw)
        assert bound.digest == tc.bytes_digest(raw)
        assert bound["authority"]["adequacy_decision"] is None
        assert bound["authority"]["qualification_effect"] == "NONE"
        assert bound["authority"]["promotion_eligible"] is False
        assert bound["authority"]["release3_included"] is False
        assert wr.require_bound_transition_workload_evidence(bound) is bound

    hostile = _evidence()
    hostile["authority"]["adequacy_decision"] = "ADEQUATE"
    _refuses(
        lambda: wr.bind_transition_workload_evidence_bytes(tc.canonical_json_bytes(hostile)),
        "transition_workload_evidence_malformed",
    )

    for field in ("authoritative", "promotion_eligible", "release3_included"):
        hostile = _evidence()
        hostile["authority"][field] = 0
        _refuses(
            lambda hostile=hostile: wr.bind_transition_workload_evidence_bytes(
                tc.canonical_json_bytes(hostile)
            ),
            "transition_workload_evidence_malformed",
        )


def test_ready_evidence_can_receive_separate_signed_adequacy_decision() -> None:
    material = _material()
    verified = _verify(material)
    assert verified.adequate is True
    assert verified.evidence_state == wr.WORKLOAD_EVIDENCE_READY
    assert verified.evidence_digest == material["evidence"].digest
    assert verified.bindings_digest == tc.canonical_digest(material["bindings"])
    assert verified.selected_commit == _COMMIT
    current = _require_current(material, verified)
    assert current is not verified
    assert current.adequate is True
    assert current.policy_digest == tc.bytes_digest(material["policy_raw"])
    assert current.bindings_digest == verified.bindings_digest
    with pytest.raises(AttributeError):
        verified.decision = wr.WORKLOAD_REVIEW_INADEQUATE


def test_adequate_decision_over_absent_evidence_is_refused() -> None:
    material = _material(state=wr.WORKLOAD_EVIDENCE_ABSENT)
    _refuses(
        lambda: _verify(material),
        "workload_review_adequate_requires_ready_evidence",
    )


def test_inadequate_decision_can_bind_absent_evidence_without_authority_laundering() -> None:
    material = _material(
        state=wr.WORKLOAD_EVIDENCE_ABSENT,
        decision=wr.WORKLOAD_REVIEW_INADEQUATE,
    )
    verified = _verify(material)
    assert verified.adequate is False
    assert verified.decision == wr.WORKLOAD_REVIEW_INADEQUATE


def test_candidate_binding_and_detached_signature_mutations_are_refused() -> None:
    material = _material()
    hostile_bindings = deepcopy(material["bindings"])
    hostile_bindings["selected_tree"] = "c" * 40
    _refuses(
        lambda: wr.verify_transition_workload_review(
            material["evidence"],
            material["receipt_raw"],
            material["signature_raw"],
            wr.bind_external_workload_review_trust_policy_bytes(material["policy_raw"]),
            material["public_key_raw"],
            hostile_bindings,
            tc.bytes_digest(material["policy_raw"]),
        ),
        "workload_review_candidate_binding_mismatch",
    )

    hostile_signature = deepcopy(material["signature"])
    hostile_signature["signature_base64"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    material["signature_raw"] = tc.canonical_json_bytes(hostile_signature)
    _refuses(lambda: _verify(material), "workload_review_signature_invalid")


def test_policy_requires_all_independence_assertions_and_exact_subject() -> None:
    material = _material()
    policy = deepcopy(material["policy"])
    policy["trusted_keys"][0]["independent_from_workload_producer"] = False
    _refuses(
        lambda: wr.bind_external_workload_review_trust_policy_bytes(
            tc.canonical_json_bytes(policy)
        ),
        "workload_review_trust_policy_malformed",
    )

    policy = deepcopy(material["policy"])
    policy["trusted_keys"][0]["allowed_subjects"][0]["selected_tree"] = "c" * 40
    material["policy_raw"] = tc.canonical_json_bytes(policy)
    _refuses(lambda: _verify(material), "workload_review_subject_not_authorized")


def test_revocation_and_producer_reviewer_identity_are_refused() -> None:
    material = _material()
    policy = deepcopy(material["policy"])
    policy["revoked_receipt_digests"] = [tc.bytes_digest(material["receipt_raw"])]
    material["policy_raw"] = tc.canonical_json_bytes(policy)
    _refuses(lambda: _verify(material), "workload_review_receipt_revoked")

    material = _material(producer_id=_REVIEWER_KEY_ID)
    _refuses(lambda: _verify(material), "workload_reviewer_producer_identity_conflict")


def test_external_policy_digest_pin_is_required_and_exact() -> None:
    material = _material()
    policy = wr.bind_external_workload_review_trust_policy_bytes(material["policy_raw"])

    _refuses(
        lambda: wr.verify_transition_workload_review(
            material["evidence"],
            material["receipt_raw"],
            material["signature_raw"],
            policy,
            material["public_key_raw"],
            material["bindings"],
            "sha256:" + "0" * 64,
        ),
        "workload_review_policy_pin_mismatch",
    )
    _refuses(
        lambda: wr.verify_transition_workload_review(
            material["evidence"],
            material["receipt_raw"],
            material["signature_raw"],
            policy,
            material["public_key_raw"],
            material["bindings"],
            "not-a-digest",
        ),
        "workload_review_policy_pin_malformed",
    )


def test_signature_covers_receipt_while_current_policy_remains_live_authority() -> None:
    material = _material()
    original_signing_material = wr.workload_review_signing_material(
        material["receipt_raw"], material["policy_raw"]
    )
    original_signature = material["signature"]["signature_base64"]
    verified = _verify(material)

    successor = deepcopy(material["policy"])
    successor["policy_version"] = "1.0.1"
    successor["evaluated_at"] = "2026-08-24T00:00:00.000000Z"
    successor_raw = tc.canonical_json_bytes(successor)
    assert wr.workload_review_signing_material(
        material["receipt_raw"], successor_raw
    ) == original_signing_material
    assert base64.b64encode(
        material["private_key"].sign(original_signing_material)
    ).decode("ascii") == original_signature

    fresh = wr.require_verified_transition_workload_review(
        verified,
        wr.bind_external_workload_review_trust_policy_bytes(successor_raw),
        tc.bytes_digest(successor_raw),
    )
    assert fresh.signature_digest == verified.signature_digest
    assert fresh.policy_digest == tc.bytes_digest(successor_raw)
    assert fresh.evaluated_at == successor["evaluated_at"]

    revoked = deepcopy(successor)
    revoked["revoked_receipt_digests"] = [tc.bytes_digest(material["receipt_raw"])]
    revoked_raw = tc.canonical_json_bytes(revoked)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            fresh,
            wr.bind_external_workload_review_trust_policy_bytes(revoked_raw),
            tc.bytes_digest(revoked_raw),
        ),
        "workload_review_receipt_revoked",
    )


def test_every_use_rechecks_current_policy_and_rejects_rollback() -> None:
    material = _material()
    verified = _verify(material)

    successor = deepcopy(material["policy"])
    successor["policy_version"] = "1.0.1"
    successor["evaluated_at"] = "2026-08-24T00:00:00.000000Z"
    successor_raw = tc.canonical_json_bytes(successor)
    fresh = wr.require_verified_transition_workload_review(
        verified,
        wr.bind_external_workload_review_trust_policy_bytes(successor_raw),
        tc.bytes_digest(successor_raw),
    )
    assert fresh is not verified
    assert fresh.adequate is True
    assert fresh.policy_digest == tc.bytes_digest(successor_raw)

    revoked = deepcopy(successor)
    revoked["revoked_receipt_digests"] = [tc.bytes_digest(material["receipt_raw"])]
    revoked_raw = tc.canonical_json_bytes(revoked)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(revoked_raw),
            tc.bytes_digest(revoked_raw),
        ),
        "workload_review_receipt_revoked",
    )

    deny_all = deepcopy(successor)
    deny_all["policy_version"] = "1.0.2"
    deny_all["trusted_keys"] = []
    deny_all_raw = tc.canonical_json_bytes(deny_all)
    assert wr.validate_workload_review_trust_policy(deny_all) == deny_all
    _schema_validator("trustPolicy").validate(deny_all)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(deny_all_raw),
            tc.bytes_digest(deny_all_raw),
        ),
        "workload_review_key_not_trusted",
    )

    rollback = deepcopy(material["policy"])
    rollback["policy_version"] = "0.9.0"
    rollback["evaluated_at"] = "2026-08-22T12:00:00.000000Z"
    rollback_raw = tc.canonical_json_bytes(rollback)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            fresh,
            wr.bind_external_workload_review_trust_policy_bytes(rollback_raw),
            tc.bytes_digest(rollback_raw),
        ),
        "workload_review_policy_rollback",
    )

    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(successor_raw),
            tc.bytes_digest(material["policy_raw"]),
        ),
        "workload_review_policy_pin_mismatch",
    )

    subject_removed = deepcopy(successor)
    subject_removed["trusted_keys"][0]["allowed_subjects"][0]["selected_tree"] = (
        "c" * 40
    )
    subject_removed_raw = tc.canonical_json_bytes(subject_removed)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(subject_removed_raw),
            tc.bytes_digest(subject_removed_raw),
        ),
        "workload_review_subject_not_authorized",
    )

    key_changed = deepcopy(successor)
    key_changed["trusted_keys"][0]["public_key_digest"] = "sha256:" + "0" * 64
    key_changed_raw = tc.canonical_json_bytes(key_changed)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(key_changed_raw),
            tc.bytes_digest(key_changed_raw),
        ),
        "workload_review_key_not_trusted",
    )

    expired = deepcopy(successor)
    expired["policy_version"] = "1.0.3"
    expired["evaluated_at"] = "2026-10-01T00:00:00.000000Z"
    expired_raw = tc.canonical_json_bytes(expired)
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            verified,
            wr.bind_external_workload_review_trust_policy_bytes(expired_raw),
            tc.bytes_digest(expired_raw),
        ),
        "workload_review_receipt_not_current",
    )


def test_verified_review_subject_and_policy_bindings_cannot_be_mutated() -> None:
    material = _material()
    verified = _verify(material)
    object.__setattr__(verified, "bindings_digest", "sha256:" + "0" * 64)
    _refuses(
        lambda: _require_current(material, verified),
        "verified_transition_workload_review_mutated",
    )

    verified = _verify(material)
    hostile_historical_policy = deepcopy(material["policy"])
    hostile_historical_policy["policy_version"] = "1.0.1"
    object.__setattr__(
        verified,
        "_trust_policy_raw",
        tc.canonical_json_bytes(hostile_historical_policy),
    )
    _refuses(
        lambda: _require_current(material, verified),
        "verified_transition_workload_review_mutated",
    )

    verified = _verify(material)
    hostile_bindings = deepcopy(material["bindings"])
    hostile_bindings["selected_tree"] = "c" * 40
    object.__setattr__(
        verified,
        "_expected_bindings_raw",
        tc.canonical_json_bytes(hostile_bindings),
    )
    _refuses(
        lambda: _require_current(material, verified),
        "verified_transition_workload_review_mutated",
    )

    verified = _verify(material)
    object.__setattr__(
        verified,
        "externally_selected_trust_policy_digest",
        "sha256:" + "0" * 64,
    )
    _refuses(
        lambda: _require_current(material, verified),
        "verified_transition_workload_review_mutated",
    )


def test_verified_review_cannot_be_forged_by_constructor_or_plain_mapping() -> None:
    material = _material()
    policy = wr.bind_external_workload_review_trust_policy_bytes(material["policy_raw"])
    _refuses(
        lambda: wr.require_verified_transition_workload_review(
            {"decision": "ADEQUATE"},
            policy,
            tc.bytes_digest(material["policy_raw"]),
        ),
        "detached_or_unverified_transition_workload_review",
    )
    with pytest.raises(TypeError):
        wr.VerifiedTransitionWorkloadReview(
            evidence=object(),
            receipt={},
            receipt_raw=b"{}",
            signature_raw=b"{}",
            policy=object(),
            public_key_raw=b"\x00" * 32,
            expected_bindings={},
            externally_selected_trust_policy_digest="sha256:" + "0" * 64,
            _authority=object(),
        )


def test_json_schema_matches_all_public_structures_and_rejects_authority_laundering() -> None:
    material = _material()
    values = {
        "workloadEvidence": tc.parse_canonical_json_bytes(material["evidence_raw"]),
        "reviewBindings": material["bindings"],
        "reviewReceipt": material["receipt"],
        "reviewSignature": material["signature"],
        "trustedKey": material["policy"]["trusted_keys"][0],
        "trustPolicy": material["policy"],
    }
    for definition, value in values.items():
        _schema_validator(definition).validate(value)

    hostile = deepcopy(values["workloadEvidence"])
    hostile["authority"]["qualification_effect"] = "QUALIFIED"
    with pytest.raises(ValidationError):
        _schema_validator("workloadEvidence").validate(hostile)
