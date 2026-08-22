"""Adversarial R2.0 tests for the closed Pack ABI and qualification boundary."""

from __future__ import annotations

import base64
from copy import deepcopy
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_pack as tp


_SIGNATURE_DOMAIN = b"ATLAS-TRANSITION-QUALIFICATION\x00v1\x00"


def _digest(label: str) -> str:
    return tc.bytes_digest(label.encode("utf-8"))


def _wasm_module() -> dict[str, Any]:
    return {
        "schema": tp.PACK_WASM_MODULE_SCHEMA,
        "module_id": "module.parser.001",
        "role": "PARSER",
        "digest": _digest("parser wasm"),
        "signature_digest": _digest("parser wasm signature"),
        "imports": list(tp.PACK_HOST_IMPORTS),
        "wasi_imports": [],
        "native_fallback": False,
        "metering_profile_digest": _digest("parser metering profile"),
    }


def _resource_ceilings() -> dict[str, int]:
    return {
        "max_input_bytes": 1_000_000,
        "max_output_bytes": 1_000_000,
        "max_memory_pages": 64,
        "max_call_depth": 32,
        "max_instruction_fuel": 10_000_000,
        "max_host_deadline_ms": 5_000,
    }


def _tcb_manifest(
        *,
        frozen: bool = False,
        qualification_receipt_digest: str | None = None,
        denominator_digest: str | None = None,
        wasm_runtime_digest: str | None = None) -> dict[str, Any]:
    return {
        "schema": tp.TCB_MANIFEST_SCHEMA,
        "manifest_id": "tcb.fixture.001",
        "core_source_digests": [_digest("structural core source")],
        "pack_source_digests": [_digest("pack source")],
        "transitive_dependency_digests": [],
        "core_executable_lines": 100,
        "pack_executable_lines": 20,
        "dsl_interpreter_digest": _digest("dsl interpreter"),
        "wasm_runtime_digest": wasm_runtime_digest,
        "toolchain_digests": [_digest("python toolchain")],
        "abi_version": tc.PACK_ABI_VERSION,
        "qualification_receipt_digest": qualification_receipt_digest,
        "supported_denominator_digest": denominator_digest or _digest("supported denominator"),
        "budget_state": (
            tp.TCBBudgetState.FROZEN.value
            if frozen
            else tp.TCBBudgetState.PENDING_PROTOTYPE_CENSUS_AND_INDEPENDENT_REVIEW.value
        ),
        "core_sloc_budget": 120 if frozen else None,
        "pack_sloc_budget": 30 if frozen else None,
        "resource_ceilings": _resource_ceilings() if frozen else None,
    }


def _pack_manifest(
        *,
        tcb: dict[str, Any] | None = None,
        pack_id: str = tp.QCP_001_ID,
        pack_version: str | None = None,
        qualification_state: str = tc.QualificationState.EXPERIMENTAL.value,
        qualification_receipt_digest: str | None = None,
        execution_state: str = tp.PackExecutionState.CONTRACT_ONLY.value,
        substrate: str = tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        wasm_modules: list[dict[str, Any]] | None = None,
        denominator_digest: str | None = None) -> dict[str, Any]:
    checked_tcb = tcb or _tcb_manifest()
    denominator = denominator_digest or checked_tcb["supported_denominator_digest"]
    is_qcp_001 = pack_id == tp.QCP_001_ID
    return {
        "schema": tp.PACK_MANIFEST_SCHEMA,
        "pack_id": pack_id,
        "pack_version": pack_version or (tp.QCP_001_DRAFT_VERSION if is_qcp_001 else "1.0.0"),
        "abi_version": tc.PACK_ABI_VERSION,
        "behavior_kind": "BEHAVIOR_PACK",
        "qualification_state": qualification_state,
        "qualification_receipt_digest": qualification_receipt_digest,
        "execution_state": execution_state,
        "substrate": substrate,
        "semantic_bundle_digest": _digest(f"{pack_id} semantic bundle"),
        "declarative_rules_digest": _digest(f"{pack_id} declarative rules"),
        "declarative_operators": list(tp.DECLARATIVE_DSL_OPERATORS),
        "supported_denominator_digest": denominator,
        "applicability_profile_ids": [f"{pack_id}.profile.001"],
        "functions": list(tp.PACK_ABI_FUNCTIONS),
        "wasm_modules": deepcopy(wasm_modules or []),
        "tcb_manifest_digest": tc.canonical_digest(checked_tcb),
        "claim_boundary": (
            tp.QCP_001_CLAIM_BOUNDARY
            if is_qcp_001
            else "Bounded qualified fixture pack; no autonomous decision authority."
        ),
    }


def _assert_transition_refusal(callable_value: Any, code: str) -> tc.TransitionContractError:
    with pytest.raises(tc.TransitionContractError) as caught:
        callable_value()
    assert caught.value.code == code
    return caught.value


def _assert_pack_refusal(callable_value: Any, code: str) -> tp.PackContractError:
    with pytest.raises(tp.PackContractError) as caught:
        callable_value()
    assert caught.value.code == code
    return caught.value


def test_pack_manifest_abi_and_substrate_vocabularies_are_closed() -> None:
    assert tp.PACK_ABI_FUNCTIONS == (
        "manifest",
        "resolve_applicability",
        "extract_atoms",
        "compile_obligations",
        "evaluate",
        "replay_witness",
    )
    assert tp.DECLARATIVE_DSL_OPERATORS == (
        "ALL_OF",
        "ANY_OF",
        "EQUALS",
        "EXISTS",
        "IN_SET",
        "MATCH_SCOPE",
        "NOT",
        "NOT_EQUALS",
        "TEMPORAL_MONITOR",
    )
    assert tp.PACK_HOST_IMPORTS == (
        "atlas.host.emit_canonical_json",
        "atlas.host.read_content_bytes",
        "atlas.host.sha256",
    )
    assert {item.value for item in tp.PackSubstrate} == {
        "DECLARATIVE_DSL_ONLY",
        "DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI",
    }
    assert {item.value for item in tp.PackExecutionState} == {"CONTRACT_ONLY", "ACTIVATABLE"}
    assert tp.validate_pack_manifest(_pack_manifest())["pack_id"] == tp.QCP_001_ID


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("extra_field", "CLOSED_SCHEMA_KEYS"),
        ("missing_function", "PACK_ABI_FUNCTIONS_CLOSED_SET_REQUIRED"),
        ("extra_function", "PACK_ABI_FUNCTIONS_CLOSED_SET_REQUIRED"),
        ("extra_operator", "DECLARATIVE_DSL_CLOSED_SET_REQUIRED"),
        ("unknown_substrate", "UNKNOWN_ENUM_VALUE"),
    ),
)
def test_manifest_rejects_open_ended_abi_or_schema_mutations(mutation: str, code: str) -> None:
    manifest = _pack_manifest()
    if mutation == "extra_field":
        manifest["native_plugin"] = "python"
    elif mutation == "missing_function":
        manifest["functions"].pop()
    elif mutation == "extra_function":
        manifest["functions"].append("open_socket")
    elif mutation == "extra_operator":
        manifest["declarative_operators"].append("EVAL_PYTHON")
    else:
        manifest["substrate"] = "NATIVE_PYTHON_PLUGIN"

    _assert_transition_refusal(lambda: tp.validate_pack_manifest(manifest), code)


def test_substrate_requires_exactly_the_declared_executable_shape() -> None:
    declarative_with_wasm = _pack_manifest(wasm_modules=[_wasm_module()])
    _assert_transition_refusal(
        lambda: tp.validate_pack_manifest(declarative_with_wasm),
        "DECLARATIVE_ONLY_PACK_CANNOT_DECLARE_WASM",
    )

    wasm_without_module = _pack_manifest(
        substrate=tp.PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value,
    )
    _assert_transition_refusal(
        lambda: tp.validate_pack_manifest(wasm_without_module),
        "WASM_SUBSTRATE_REQUIRES_MODULE",
    )

    valid_wasm = _pack_manifest(
        substrate=tp.PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value,
        wasm_modules=[_wasm_module()],
    )
    assert tp.validate_pack_manifest(valid_wasm) == valid_wasm


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("imports", ["atlas.host.getenv"], "PACK_WASM_IMPORT_FORBIDDEN"),
        ("imports", ["wasi_snapshot_preview1.fd_read"], "PACK_WASM_IMPORT_FORBIDDEN"),
        ("wasi_imports", ["wasi_snapshot_preview1.fd_read"], "PACK_WASI_IMPORT_FORBIDDEN"),
        ("native_fallback", True, "PACK_NATIVE_FALLBACK_FORBIDDEN"),
    ),
)
def test_wasm_modules_reject_unknown_wasi_and_native_import_paths(
        field: str, value: object, code: str) -> None:
    module = _wasm_module()
    module[field] = value
    manifest = _pack_manifest(
        substrate=tp.PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value,
        wasm_modules=[module],
    )

    _assert_transition_refusal(lambda: tp.validate_pack_manifest(manifest), code)


def test_qcp_001_is_a_nonpromoting_experimental_contract_only_draft() -> None:
    manifest = _pack_manifest()
    assert tp.validate_pack_manifest(manifest) == manifest
    assert manifest["qualification_state"] == "EXPERIMENTAL"
    assert manifest["qualification_receipt_digest"] is None
    assert manifest["execution_state"] == "CONTRACT_ONLY"
    tp.qcp_001_must_remain_experimental(manifest)

    promoted = deepcopy(manifest)
    promoted["qualification_state"] = "QUALIFIED"
    promoted["qualification_receipt_digest"] = _digest("forged qcp-001 qualification")
    promoted["execution_state"] = "ACTIVATABLE"
    _assert_transition_refusal(
        lambda: tp.validate_pack_manifest(promoted),
        "QCP_001_R2_0_MUST_REMAIN_EXPERIMENTAL",
    )

    version_promoted = deepcopy(manifest)
    version_promoted["pack_version"] = "1.0.0"
    _assert_transition_refusal(
        lambda: tp.validate_pack_manifest(version_promoted),
        "QCP_001_R2_0_MUST_REMAIN_EXPERIMENTAL",
    )

    claim_promoted = deepcopy(manifest)
    claim_promoted["claim_boundary"] = "Qualified and promotion eligible."
    _assert_transition_refusal(
        lambda: tp.validate_pack_manifest(claim_promoted),
        "QCP_001_R2_0_MUST_REMAIN_EXPERIMENTAL",
    )


def test_pending_tcb_budgets_remain_null_until_prototype_review() -> None:
    pending = _tcb_manifest()
    assert tp.validate_tcb_manifest(pending) == pending

    for field, value in (
        ("core_sloc_budget", 120),
        ("pack_sloc_budget", 30),
        ("resource_ceilings", _resource_ceilings()),
    ):
        candidate = deepcopy(pending)
        candidate[field] = value
        _assert_transition_refusal(
            lambda candidate=candidate: tp.validate_tcb_manifest(candidate),
            "PENDING_TCB_BUDGETS_MUST_BE_NULL",
        )


def test_frozen_tcb_requires_complete_ceilings_and_enforces_sloc_budgets() -> None:
    frozen = _tcb_manifest(frozen=True)
    assert tp.validate_tcb_manifest(frozen) == frozen

    missing_ceiling = deepcopy(frozen)
    missing_ceiling["resource_ceilings"].pop("max_instruction_fuel")
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(missing_ceiling),
        "CLOSED_SCHEMA_KEYS",
    )

    core_exceeded = deepcopy(frozen)
    core_exceeded["core_executable_lines"] = core_exceeded["core_sloc_budget"] + 1
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(core_exceeded),
        "CORE_SLOC_BUDGET_EXCEEDED",
    )

    pack_exceeded = deepcopy(frozen)
    pack_exceeded["pack_executable_lines"] = pack_exceeded["pack_sloc_budget"] + 1
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(pack_exceeded),
        "PACK_SLOC_BUDGET_EXCEEDED",
    )


def test_activatable_pack_requires_frozen_tcb_and_matching_qualification() -> None:
    receipt_digest = _digest("qualified generic pack receipt")
    pending = _tcb_manifest(qualification_receipt_digest=receipt_digest)
    pending_pack = _pack_manifest(
        tcb=pending,
        pack_id="pack.fixture",
        qualification_state="QUALIFIED",
        qualification_receipt_digest=receipt_digest,
        execution_state="ACTIVATABLE",
    )
    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(pending_pack, pending),
        "ACTIVATABLE_PACK_REQUIRES_FROZEN_TCB_BUDGET",
    )

    frozen = _tcb_manifest(frozen=True, qualification_receipt_digest=receipt_digest)
    frozen_pack = _pack_manifest(
        tcb=frozen,
        pack_id="pack.fixture",
        qualification_state="QUALIFIED",
        qualification_receipt_digest=receipt_digest,
        execution_state="ACTIVATABLE",
    )
    tp.validate_pack_tcb_pair(frozen_pack, frozen)

    wrong_receipt_tcb = deepcopy(frozen)
    wrong_receipt_tcb["qualification_receipt_digest"] = _digest("different receipt")
    wrong_receipt_pack = _pack_manifest(
        tcb=wrong_receipt_tcb,
        pack_id="pack.fixture",
        qualification_state="QUALIFIED",
        qualification_receipt_digest=receipt_digest,
        execution_state="ACTIVATABLE",
    )
    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(wrong_receipt_pack, wrong_receipt_tcb),
        "PACK_TCB_QUALIFICATION_MISMATCH",
    )


def test_pack_manifest_binding_requires_exact_canonical_unchanged_bytes() -> None:
    manifest = _pack_manifest()
    raw = tc.canonical_json_bytes(manifest)
    bound = tp.bind_pack_manifest_bytes(raw)

    assert dict(bound) == manifest
    assert bound.digest == tc.bytes_digest(raw)
    assert bound.source_bytes == len(raw)
    assert tp.require_bound_pack_manifest(bound) is bound

    _assert_pack_refusal(lambda: tp.require_bound_pack_manifest(manifest), "detached_pack_manifest")
    with pytest.raises(tc.TransitionContractError) as caught:
        tp.bind_pack_manifest_bytes(raw + b"\n")
    assert caught.value.code == "CANONICAL_BYTES_REQUIRED"

    bound["semantic_bundle_digest"] = _digest("mutated semantic bundle")
    _assert_pack_refusal(lambda: tp.require_bound_pack_manifest(bound), "bound_pack_manifest_mutated")


def test_pack_to_tcb_binding_rejects_digest_and_denominator_substitution() -> None:
    tcb = _tcb_manifest()
    pack = _pack_manifest(tcb=tcb)
    tp.validate_pack_tcb_pair(pack, tcb)

    mutated_tcb = deepcopy(tcb)
    mutated_tcb["core_executable_lines"] += 1
    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(pack, mutated_tcb),
        "PACK_TCB_DIGEST_MISMATCH",
    )

    mismatched_pack = _pack_manifest(
        tcb=tcb,
        denominator_digest=_digest("substituted denominator"),
    )
    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(mismatched_pack, tcb),
        "PACK_TCB_DENOMINATOR_MISMATCH",
    )


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _qualification_receipt() -> dict[str, Any]:
    return {
        "schema": tp.QUALIFICATION_RECEIPT_SCHEMA,
        "receipt_id": "qualification.fixture.001",
        "purpose": tp.QUALIFICATION_PURPOSE,
        "subject_kind": tp.QualificationSubjectKind.BEHAVIOR_PACK.value,
        "subject_id": "pack.fixture",
        "subject_version": "1.0.0",
        "subject_digest": _digest("qualified pack exact bytes"),
        "qualification_state": tc.QualificationState.QUALIFIED.value,
        "denominator_digest": _digest("qualified denominator"),
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "issuer_key_id": "qualification-key.001",
    }


def _qualification_signature(
        receipt_raw: bytes,
        private_key: Ed25519PrivateKey,
        *,
        signer_key_id: str = "qualification-key.001",
        domain: bytes = _SIGNATURE_DOMAIN) -> dict[str, Any]:
    signature = private_key.sign(domain + receipt_raw)
    return {
        "schema": tp.QUALIFICATION_SIGNATURE_SCHEMA,
        "purpose": tp.QUALIFICATION_PURPOSE,
        "payload_digest": tc.bytes_digest(receipt_raw),
        "signer_key_id": signer_key_id,
        "algorithm": tp.QUALIFICATION_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def _trust_policy(
        public_key_raw: bytes,
        *,
        evaluated_at: str = "2026-08-23T00:00:00.000000Z",
        allowed_subject_kinds: list[str] | None = None,
        allowed_subject_ids: list[str] | None = None,
        revoked_receipt_digests: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema": tp.TRUST_POLICY_SCHEMA,
        "policy_id": "qualification-policy.fixture",
        "policy_version": "1.0.0",
        "purpose": tp.QUALIFICATION_PURPOSE,
        "evaluated_at": evaluated_at,
        "trusted_keys": [
            {
                "schema": tp.TRUSTED_KEY_SCHEMA,
                "key_id": "qualification-key.001",
                "public_key_digest": tc.bytes_digest(public_key_raw),
                "allowed_subject_kinds": allowed_subject_kinds or [
                    tp.QualificationSubjectKind.BEHAVIOR_PACK.value
                ],
                "allowed_subject_ids": allowed_subject_ids or ["pack.fixture"],
                "valid_from": "2026-01-01T00:00:00.000000Z",
                "valid_until": "2027-01-01T00:00:00.000000Z",
            }
        ],
        "revoked_receipt_digests": sorted(revoked_receipt_digests or []),
    }


def _qualification_material() -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key_raw = _public_key_bytes(private_key)
    receipt = _qualification_receipt()
    receipt_raw = tc.canonical_json_bytes(receipt)
    signature = _qualification_signature(receipt_raw, private_key)
    policy = _trust_policy(public_key_raw)
    return {
        "private_key": private_key,
        "public_key_raw": public_key_raw,
        "receipt": receipt,
        "signature": signature,
        "policy": policy,
    }


def _verify(material: dict[str, Any]) -> tp.VerifiedQualification:
    bound_policy = tp.bind_external_trust_policy_bytes(
        tc.canonical_json_bytes(material["policy"])
    )
    return tp.verify_qualification_evidence(
        tc.canonical_json_bytes(material["receipt"]),
        tc.canonical_json_bytes(material["signature"]),
        bound_policy,
        material["public_key_raw"],
    )


def _resign(material: dict[str, Any], *, domain: bytes = _SIGNATURE_DOMAIN) -> None:
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    material["signature"] = _qualification_signature(
        receipt_raw,
        material["private_key"],
        domain=domain,
    )


def test_ed25519_qualification_binds_exact_receipt_policy_key_and_subject() -> None:
    material = _qualification_material()
    verified = _verify(material)
    receipt_raw = tc.canonical_json_bytes(material["receipt"])
    policy_raw = tc.canonical_json_bytes(material["policy"])

    assert verified.receipt_digest == tc.bytes_digest(receipt_raw)
    assert verified.policy_digest == tc.bytes_digest(policy_raw)
    assert verified.subject_kind == "BEHAVIOR_PACK"
    assert verified.subject_id == "pack.fixture"
    assert verified.subject_version == "1.0.0"
    assert verified.subject_digest == material["receipt"]["subject_digest"]
    assert verified.denominator_digest == material["receipt"]["denominator_digest"]
    assert verified.receipt_claimed_state == "QUALIFIED"
    assert verified.policy_evaluated_state == "QUALIFIED"
    assert verified.state is None
    assert verified.policy_approved is False
    assert verified.registry_state == tp.QUALIFICATION_REGISTRY_STATE
    assert verified.evaluated_at == material["policy"]["evaluated_at"]
    assert tp.require_verified_qualification(verified) is verified
    _assert_pack_refusal(
        lambda: tp.require_verified_qualification({}),
        "detached_or_unverified_qualification",
    )


def test_qualification_requires_policy_from_the_external_exact_byte_channel() -> None:
    material = _qualification_material()

    _assert_pack_refusal(
        lambda: tp.verify_qualification_evidence(
            tc.canonical_json_bytes(material["receipt"]),
            tc.canonical_json_bytes(material["signature"]),
            tc.canonical_json_bytes(material["policy"]),  # type: ignore[arg-type]
            material["public_key_raw"],
        ),
        "external_trust_policy_required",
    )


def test_checked_qualification_is_immutable_and_integrity_guarded() -> None:
    verified = _verify(_qualification_material())

    with pytest.raises(AttributeError, match="immutable"):
        verified.state = "QUALIFIED"

    object.__setattr__(verified, "state", "QUALIFIED")
    _assert_pack_refusal(
        lambda: tp.require_verified_qualification(verified),
        "verified_qualification_mutated",
    )


@pytest.mark.parametrize("target", ("receipt", "signature", "policy"))
def test_qualification_purpose_is_closed_across_all_signed_inputs(target: str) -> None:
    material = _qualification_material()
    material[target]["purpose"] = "ATLAS_OTHER_PURPOSE"
    if target == "receipt":
        _resign(material)

    expected = (
        "external_trust_policy_malformed"
        if target == "policy"
        else "qualification_evidence_malformed"
    )
    _assert_pack_refusal(lambda: _verify(material), expected)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("subject_kind", "OBSERVATION_PROFILE"),
        ("subject_id", "pack.unauthorized"),
    ),
)
def test_signed_but_policy_unauthorized_subject_is_rejected(field: str, value: str) -> None:
    material = _qualification_material()
    material["receipt"][field] = value
    _resign(material)

    _assert_pack_refusal(lambda: _verify(material), "qualification_subject_not_authorized")


def test_receipt_subject_digest_mutation_breaks_exact_payload_binding() -> None:
    material = _qualification_material()
    material["receipt"]["subject_digest"] = _digest("substituted subject bytes")

    _assert_pack_refusal(lambda: _verify(material), "qualification_signature_binding_mismatch")

    material["signature"]["payload_digest"] = tc.canonical_digest(material["receipt"])
    _assert_pack_refusal(lambda: _verify(material), "qualification_signature_invalid")


def test_policy_public_key_digest_prevents_key_substitution() -> None:
    material = _qualification_material()
    substitute_private = Ed25519PrivateKey.generate()
    material["public_key_raw"] = _public_key_bytes(substitute_private)

    _assert_pack_refusal(lambda: _verify(material), "qualification_key_not_trusted")


def test_qualification_time_range_and_key_time_fail_closed() -> None:
    malformed_receipt = _qualification_material()
    malformed_receipt["receipt"]["issued_at"] = "2026-08-22T00:00:00.000001Z"
    _resign(malformed_receipt)
    _assert_pack_refusal(lambda: _verify(malformed_receipt), "qualification_evidence_malformed")

    invalid_key_time = _qualification_material()
    invalid_key_time["policy"]["evaluated_at"] = "2027-01-01T00:00:00.000001Z"
    _assert_pack_refusal(
        lambda: _verify(invalid_key_time),
        "qualification_key_not_valid_at_policy_time",
    )


def test_expiry_is_derived_from_independent_policy_time() -> None:
    material = _qualification_material()
    material["policy"]["evaluated_at"] = "2026-10-01T00:00:00.000000Z"

    verified = _verify(material)
    assert material["receipt"]["qualification_state"] == "QUALIFIED"
    assert verified.receipt_claimed_state == "QUALIFIED"
    assert verified.policy_evaluated_state == "EXPIRED"
    assert verified.state is None


def test_revocation_is_derived_from_exact_receipt_digest_and_dominates_expiry() -> None:
    material = _qualification_material()
    receipt_digest = tc.canonical_digest(material["receipt"])
    material["policy"]["evaluated_at"] = "2026-10-01T00:00:00.000000Z"
    material["policy"]["revoked_receipt_digests"] = [receipt_digest]

    verified = _verify(material)
    assert verified.receipt_digest == receipt_digest
    assert verified.receipt_claimed_state == "QUALIFIED"
    assert verified.policy_evaluated_state == "REVOKED"
    assert verified.state is None


@pytest.mark.parametrize(
    "attack",
    ("bit_flip", "wrong_domain", "wrong_signer", "wrong_payload_digest", "wrong_algorithm"),
)
def test_signature_attacks_never_mint_verified_qualification(attack: str) -> None:
    material = _qualification_material()
    if attack == "bit_flip":
        raw_signature = bytearray(base64.b64decode(material["signature"]["signature_base64"]))
        raw_signature[0] ^= 0x01
        material["signature"]["signature_base64"] = base64.b64encode(raw_signature).decode("ascii")
        expected = "qualification_signature_invalid"
    elif attack == "wrong_domain":
        _resign(material, domain=b"")
        expected = "qualification_signature_invalid"
    elif attack == "wrong_signer":
        material["signature"]["signer_key_id"] = "qualification-key.other"
        expected = "qualification_signature_binding_mismatch"
    elif attack == "wrong_payload_digest":
        material["signature"]["payload_digest"] = _digest("unrelated receipt")
        expected = "qualification_signature_binding_mismatch"
    else:
        material["signature"]["algorithm"] = "Ed448"
        expected = "qualification_evidence_malformed"

    _assert_pack_refusal(lambda: _verify(material), expected)


def test_malformed_signature_encoding_is_rejected_without_value_echo() -> None:
    material = _qualification_material()
    material["signature"]["signature_base64"] = "not-base64!"

    refusal = _assert_pack_refusal(lambda: _verify(material), "qualification_signature_malformed")
    assert "not-base64" not in str(refusal)
