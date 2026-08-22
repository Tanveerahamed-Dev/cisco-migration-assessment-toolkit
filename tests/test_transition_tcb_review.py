from __future__ import annotations

import base64
from copy import deepcopy
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_tcb_review as tr


_COMMIT = "a" * 40
_TREE = "b" * 40


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def _resource_profile() -> dict[str, Any]:
    return {
        "schema": tr.DSL_RESOURCE_PROFILE_SCHEMA,
        "substrate": "DECLARATIVE_DSL_ONLY",
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
    }


def _authorization() -> dict[str, Any]:
    return {
        "schema": tr.TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA,
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "target_schema_version": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
        "reviewer_role": tr.TCB_BUDGET_REVIEWER_ROLE,
        "substrate": tr.TCB_BUDGET_REVIEW_SUBSTRATE,
    }


def _receipt(*, decision: str = "APPROVED") -> dict[str, Any]:
    return {
        "schema": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
        "receipt_id": "tcb-budget-review.fixture.001",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "structural_census_digest": _digest("structural census"),
        "prototype_measurement_digest": _digest("prototype measurements"),
        "dsl_interpreter_digest": _digest("DSL interpreter"),
        "prototype_program_digest": _digest("prototype program"),
        "prototype_pack_manifest_digest": _digest("prototype pack manifest"),
        "tcb_budget_subject_digest": _digest("TCB budget subject"),
        "approved_core_sloc_budget": 2_500,
        "approved_pack_sloc_budget": 500,
        "approved_dsl_resource_profile": _resource_profile(),
        "wasm_review_state": "UNREVIEWED",
        "measurement_denominator_digest": _digest("measurement denominator"),
        "decision": decision,
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "reviewer_key_id": "tcb-reviewer-key.fixture.001",
    }


def _bindings(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": tr.TCB_BUDGET_REVIEW_BINDINGS_SCHEMA,
        "selected_commit": receipt["selected_commit"],
        "selected_tree": receipt["selected_tree"],
        "structural_census_digest": receipt["structural_census_digest"],
        "prototype_measurement_digest": receipt["prototype_measurement_digest"],
        "dsl_interpreter_digest": receipt["dsl_interpreter_digest"],
        "prototype_program_digest": receipt["prototype_program_digest"],
        "prototype_pack_manifest_digest": receipt["prototype_pack_manifest_digest"],
        "tcb_budget_subject_digest": receipt["tcb_budget_subject_digest"],
        "measurement_denominator_digest": receipt["measurement_denominator_digest"],
    }


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _policy(
        public_key_raw: bytes,
        receipt: dict[str, Any],
        *,
        evaluated_at: str = "2026-08-23T00:00:00.000000Z",
        revoked: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema": tr.TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA,
        "policy_kind": tr.TCB_BUDGET_REVIEW_POLICY_KIND,
        "policy_id": "tcb-budget-review-policy.fixture",
        "policy_version": "1.0.0",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "evaluated_at": evaluated_at,
        "trusted_keys": [
            {
                "schema": tr.TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA,
                "key_id": receipt["reviewer_key_id"],
                "public_key_digest": tc.bytes_digest(public_key_raw),
                "reviewer_kind": tr.TCB_BUDGET_REVIEWER_KIND,
                "independent_from_budget_proposer": True,
                "independent_from_prototype_and_measurement_producer": True,
                "independent_from_release_builder": True,
                "authorizations": [_authorization()],
                "allowed_selected_commits": [receipt["selected_commit"]],
                "allowed_selected_trees": [receipt["selected_tree"]],
                "allowed_tcb_subject_digests": [receipt["tcb_budget_subject_digest"]],
                "valid_from": "2026-01-01T00:00:00.000000Z",
                "valid_until": "2027-01-01T00:00:00.000000Z",
            }
        ],
        "revoked_receipt_digests": sorted(revoked or []),
    }


def _signature(
        receipt_raw: bytes,
        policy_raw: bytes,
        private_key: Ed25519PrivateKey,
        *,
        signer_key_id: str = "tcb-reviewer-key.fixture.001",
        signing_material: bytes | None = None) -> dict[str, Any]:
    material = signing_material or tr.tcb_budget_review_signing_material(receipt_raw, policy_raw)
    signature = private_key.sign(material)
    return {
        "schema": tr.TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA,
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "trust_policy_digest": tc.bytes_digest(policy_raw),
        "signer_key_id": signer_key_id,
        "algorithm": tr.TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def _material(*, decision: str = "APPROVED") -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_bytes(private_key)
    receipt = _receipt(decision=decision)
    policy = _policy(public_key_raw, receipt)
    receipt_raw = tc.canonical_json_bytes(receipt)
    policy_raw = tc.canonical_json_bytes(policy)
    signature = _signature(receipt_raw, policy_raw, private_key)
    return {
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "receipt": receipt,
        "policy": policy,
        "signature": signature,
        "bindings": _bindings(receipt),
    }


def _resign(material: dict[str, Any], *, signing_material: bytes | None = None) -> None:
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    policy_raw = tc.canonical_json_bytes(material["policy"])
    material["signature"] = _signature(
        receipt_raw,
        policy_raw,
        material["private_key"],
        signing_material=signing_material,
    )


def _verify(material: dict[str, Any]) -> tr.VerifiedTCBBudgetReview:
    policy = tr.bind_external_tcb_budget_review_trust_policy_bytes(
        tc.canonical_json_bytes(material["policy"])
    )
    return tr.verify_tcb_budget_review_evidence(
        tc.canonical_json_bytes(material["receipt"]),
        tc.canonical_json_bytes(material["signature"]),
        policy,
        material["public_key_raw"],
        material["bindings"],
    )


def _assert_refusal(call: Any, code: str) -> tr.TCBBudgetReviewError:
    with pytest.raises(tr.TCBBudgetReviewError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == code
    return caught.value


def test_signed_approved_review_binds_candidate_budgets_profile_and_exact_bytes() -> None:
    material = _material()
    verified = _verify(material)
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    signature_raw = tc.canonical_json_bytes(material["signature"])
    policy_raw = tc.canonical_json_bytes(material["policy"])

    assert verified.approved is True
    assert verified.decision == "APPROVED"
    assert verified.review_digest == tc.bytes_digest(receipt_raw)
    assert verified.signature_digest == tc.bytes_digest(signature_raw)
    assert verified.policy_digest == tc.bytes_digest(policy_raw)
    assert verified.selected_commit == _COMMIT
    assert verified.selected_tree == _TREE
    assert (
        verified.prototype_pack_manifest_digest
        == material["receipt"]["prototype_pack_manifest_digest"]
    )
    assert verified.tcb_subject_digest == material["receipt"]["tcb_budget_subject_digest"]
    assert verified.core_sloc_budget == 2_500
    assert verified.pack_sloc_budget == 500
    assert verified.dsl_resource_profile == _resource_profile()
    assert verified.wasm_review_state == "UNREVIEWED"
    assert tr.require_verified_tcb_budget_review(verified) is verified

    detached_profile = verified.dsl_resource_profile
    detached_profile["max_rules"] = 1
    assert verified.dsl_resource_profile["max_rules"] == 128


def test_signed_rejected_review_is_verified_but_never_approved() -> None:
    verified = _verify(_material(decision="REJECTED"))

    assert verified.decision == "REJECTED"
    assert verified.approved is False
    assert tr.require_verified_tcb_budget_review(verified) is verified


def test_review_object_is_sealed_and_detached_values_never_acquire_authority() -> None:
    verified = _verify(_material())

    with pytest.raises(AttributeError, match="immutable"):
        verified.approved = False
    _assert_refusal(
        lambda: tr.require_verified_tcb_budget_review({}),
        "detached_or_unverified_tcb_budget_review",
    )

    object.__setattr__(verified, "core_sloc_budget", 1)
    _assert_refusal(
        lambda: tr.require_verified_tcb_budget_review(verified),
        "verified_tcb_budget_review_mutated",
    )


def test_policy_requires_the_separate_exact_byte_channel_and_detects_mutation() -> None:
    material = _material()
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    signature_raw = tc.canonical_json_bytes(material["signature"])

    _assert_refusal(
        lambda: tr.verify_tcb_budget_review_evidence(
            receipt_raw,
            signature_raw,
            material["policy"],  # type: ignore[arg-type]
            material["public_key_raw"],
            material["bindings"],
        ),
        "external_tcb_budget_review_trust_policy_required",
    )

    bound = tr.bind_external_tcb_budget_review_trust_policy_bytes(
        tc.canonical_json_bytes(material["policy"])
    )
    bound["trusted_keys"][0]["allowed_selected_commits"] = ["c" * 40]
    _assert_refusal(
        lambda: tr.require_bound_tcb_budget_review_trust_policy(bound),
        "bound_tcb_budget_review_trust_policy_mutated",
    )


@pytest.mark.parametrize("target", ("receipt", "signature", "policy"))
def test_review_purpose_is_closed_across_every_external_object(target: str) -> None:
    material = _material()
    material[target]["purpose"] = "ATLAS_OTHER_PURPOSE"

    expected = (
        "tcb_budget_review_trust_policy_malformed"
        if target == "policy"
        else "tcb_budget_review_evidence_malformed"
        if target == "receipt"
        else "tcb_budget_review_signature_malformed"
    )
    _assert_refusal(lambda: _verify(material), expected)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("reviewer_kind", "PROTOTYPE_PRODUCER"),
        ("independent_from_budget_proposer", False),
        ("independent_from_prototype_and_measurement_producer", False),
        ("independent_from_release_builder", False),
        ("authorizations", []),
    ),
)
def test_external_policy_cannot_authorize_a_non_independent_reviewer(
        field: str, value: Any) -> None:
    material = _material()
    material["policy"]["trusted_keys"][0][field] = value

    _assert_refusal(
        lambda: _verify(material),
        "tcb_budget_review_trust_policy_malformed",
    )


def test_external_policy_authorization_tuple_is_closed_to_dsl_budget_review() -> None:
    for field, value in (
            ("purpose", "ATLAS_OTHER_PURPOSE"),
            ("target_schema_version", "atlas.tcb-budget-review-receipt/2"),
            ("reviewer_role", "RELEASE_BUILDER"),
            ("substrate", "DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI")):
        material = _material()
        material["policy"]["trusted_keys"][0]["authorizations"][0][field] = value
        _assert_refusal(
            lambda material=material: _verify(material),
            "tcb_budget_review_trust_policy_malformed",
        )


def test_decision_is_exactly_approved_or_rejected_with_no_fifth_state() -> None:
    material = _material()
    material["receipt"]["decision"] = "CONDITIONALLY_APPROVED"

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_evidence_malformed")


@pytest.mark.parametrize(
    "binding",
    (
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_budget_subject_digest",
        "measurement_denominator_digest",
    ),
)
def test_review_must_rejoin_every_current_candidate_binding(binding: str) -> None:
    material = _material()
    material["bindings"][binding] = "c" * 40 if binding.startswith("selected_") else _digest("wrong")

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_candidate_binding_mismatch")


@pytest.mark.parametrize(
    "constraint",
    ("allowed_selected_commits", "allowed_selected_trees", "allowed_tcb_subject_digests"),
)
def test_trust_key_subject_constraints_are_closed(constraint: str) -> None:
    material = _material()
    material["policy"]["trusted_keys"][0][constraint] = [
        "c" * 40 if constraint != "allowed_tcb_subject_digests" else _digest("other subject")
    ]
    _resign(material)

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_subject_not_authorized")


def test_public_key_policy_and_key_id_substitution_fail_closed() -> None:
    substitute = _material()
    substitute["public_key_raw"] = _public_key_bytes(Ed25519PrivateKey.generate())
    _assert_refusal(lambda: _verify(substitute), "tcb_budget_review_key_not_trusted")

    policy_swap = _material()
    policy_swap["policy"]["policy_id"] = "different-policy.fixture"
    _assert_refusal(lambda: _verify(policy_swap), "tcb_budget_review_signature_binding_mismatch")

    key_id = _material()
    key_id["signature"]["signer_key_id"] = "tcb-reviewer-key.other"
    _assert_refusal(lambda: _verify(key_id), "tcb_budget_review_signature_binding_mismatch")


def test_key_time_receipt_time_and_revocation_are_evaluated_from_external_policy() -> None:
    key_expired = _material()
    key_expired["policy"]["evaluated_at"] = "2027-01-01T00:00:00.000001Z"
    _resign(key_expired)
    _assert_refusal(
        lambda: _verify(key_expired),
        "tcb_budget_review_key_not_valid_at_policy_time",
    )

    key_not_yet_valid_when_issued = _material()
    key_not_yet_valid_when_issued["policy"]["trusted_keys"][0]["valid_from"] = (
        "2026-08-22T00:00:00.000001Z"
    )
    _resign(key_not_yet_valid_when_issued)
    _assert_refusal(
        lambda: _verify(key_not_yet_valid_when_issued),
        "tcb_budget_review_key_not_valid_at_receipt_time",
    )

    receipt_expired = _material()
    receipt_expired["policy"]["evaluated_at"] = "2026-10-01T00:00:00.000000Z"
    _resign(receipt_expired)
    _assert_refusal(lambda: _verify(receipt_expired), "tcb_budget_review_receipt_not_current")

    revoked = _material()
    receipt_digest = tc.canonical_digest(revoked["receipt"])
    revoked["policy"]["revoked_receipt_digests"] = [receipt_digest]
    _resign(revoked)
    _assert_refusal(lambda: _verify(revoked), "tcb_budget_review_receipt_revoked")


def test_receipt_issue_and_validity_interval_is_structurally_closed() -> None:
    material = _material()
    material["receipt"]["issued_at"] = "2026-08-22T00:00:00.000001Z"

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_evidence_malformed")


@pytest.mark.parametrize(
    "attack",
    ("bit_flip", "wrong_domain", "wrong_payload", "wrong_policy", "wrong_algorithm", "bad_base64"),
)
def test_detached_signature_attacks_never_mint_a_verified_review(attack: str) -> None:
    material = _material()
    if attack == "bit_flip":
        raw_signature = bytearray(base64.b64decode(material["signature"]["signature_base64"]))
        raw_signature[0] ^= 1
        material["signature"]["signature_base64"] = base64.b64encode(raw_signature).decode("ascii")
        expected = "tcb_budget_review_signature_invalid"
    elif attack == "wrong_domain":
        receipt_raw = tc.canonical_json_bytes(material["receipt"])
        policy_raw = tc.canonical_json_bytes(material["policy"])
        _resign(material, signing_material=b"WRONG-DOMAIN\x00" + receipt_raw + policy_raw)
        expected = "tcb_budget_review_signature_invalid"
    elif attack == "wrong_payload":
        material["signature"]["payload_digest"] = _digest("wrong receipt")
        expected = "tcb_budget_review_signature_binding_mismatch"
    elif attack == "wrong_policy":
        material["signature"]["trust_policy_digest"] = _digest("wrong policy")
        expected = "tcb_budget_review_signature_binding_mismatch"
    elif attack == "wrong_algorithm":
        material["signature"]["algorithm"] = "Ed448"
        expected = "tcb_budget_review_signature_malformed"
    else:
        material["signature"]["signature_base64"] = "C:/hostile/secret/not-base64!"
        expected = "tcb_budget_review_signature_malformed"

    refusal = _assert_refusal(lambda: _verify(material), expected)
    assert "hostile" not in str(refusal)


@pytest.mark.parametrize(
    ("target", "replacement"),
    (
        ("approved_core_sloc_budget", 2_501),
        ("approved_pack_sloc_budget", 501),
        ("approved_dsl_resource_profile", {**_resource_profile(), "max_rules": 129}),
    ),
)
def test_budget_and_resource_profile_are_covered_by_the_exact_receipt_signature(
        target: str, replacement: Any) -> None:
    material = _material()
    material["receipt"][target] = replacement

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_signature_binding_mismatch")

    material["signature"]["payload_digest"] = tc.canonical_digest(material["receipt"])
    _assert_refusal(lambda: _verify(material), "tcb_budget_review_signature_invalid")


def test_noncanonical_duplicate_and_hostile_values_are_remapped_without_echo() -> None:
    material = _material()
    policy = tr.bind_external_tcb_budget_review_trust_policy_bytes(
        tc.canonical_json_bytes(material["policy"])
    )
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    duplicate = receipt_raw[:-1] + b',"receipt_id":"C:/hostile/private/path"}'

    refusal = _assert_refusal(
        lambda: tr.verify_tcb_budget_review_evidence(
            duplicate,
            tc.canonical_json_bytes(material["signature"]),
            policy,
            material["public_key_raw"],
            material["bindings"],
        ),
        "tcb_budget_review_evidence_malformed",
    )
    assert "hostile" not in str(refusal)

    hostile = _material()
    hostile["receipt"]["selected_commit"] = "C:/hostile/private/path"
    refusal = _assert_refusal(lambda: _verify(hostile), "tcb_budget_review_evidence_malformed")
    assert "hostile" not in str(refusal)


def test_tcb_subject_digest_normalizes_both_detached_receipt_slots_only() -> None:
    tcb = {
        "schema": "atlas.tcb-manifest/2",
        "manifest_id": "tcb.fixture",
        "budget_review_receipt_digest": _digest("budget review receipt"),
        "qualification_receipt_digest": _digest("qualification receipt"),
        "core_sloc_budget": 2_500,
        "resource_ceilings": _resource_profile(),
    }
    first = tr.tcb_budget_review_subject_digest(tcb)

    changed_receipts = deepcopy(tcb)
    changed_receipts["budget_review_receipt_digest"] = _digest("other budget receipt")
    changed_receipts["qualification_receipt_digest"] = None
    assert tr.tcb_budget_review_subject_digest(changed_receipts) == first

    changed_budget = deepcopy(tcb)
    changed_budget["core_sloc_budget"] += 1
    assert tr.tcb_budget_review_subject_digest(changed_budget) != first

    for invalid in (
            {**tcb, "schema": "atlas.tcb-manifest/1"},
            {key: value for key, value in tcb.items() if key != "budget_review_receipt_digest"},
            {**tcb, "qualification_receipt_digest": "not-a-digest"}):
        _assert_refusal(
            lambda invalid=invalid: tr.tcb_budget_review_subject_digest(invalid),
            "tcb_budget_review_subject_invalid",
        )


def test_review_schema_and_verified_result_have_no_qualification_or_promotion_surface() -> None:
    receipt = _receipt()
    verified = _verify(_material())

    prohibited = (
        "qualification_state",
        "qualification_receipt_digest",
        "pack_qualification",
        "promotion_eligible",
        "authoritative_gate",
    )
    for field in prohibited:
        assert field not in receipt
        assert not hasattr(verified, field)


def test_wasm_review_cannot_be_laundered_through_the_dsl_only_profile() -> None:
    wasm = _material()
    wasm["receipt"]["wasm_review_state"] = "APPROVED"
    _assert_refusal(lambda: _verify(wasm), "tcb_budget_review_evidence_malformed")

    substrate = _material()
    substrate["receipt"]["approved_dsl_resource_profile"]["substrate"] = (
        "DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI"
    )
    _assert_refusal(lambda: _verify(substrate), "tcb_budget_review_evidence_malformed")
