from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_runtime_inventory as runtime_inventory
from cisco_toolkit import transition_tcb_review as tr


_COMMIT = "a" * 40
_TREE = "b" * 40
ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_CORE_MUTATION_PATHS = {
    "runtime_core_transition_contract": (
        "cisco_toolkit.transition_contract",
        "$PROJECT_ROOT/cisco_toolkit/transition_contract.py",
    ),
    "runtime_core_transition_dsl": (
        "cisco_toolkit.transition_dsl",
        "$PROJECT_ROOT/cisco_toolkit/transition_dsl.py",
    ),
    "runtime_core_transition_pack": (
        "cisco_toolkit.transition_pack",
        "$PROJECT_ROOT/cisco_toolkit/transition_pack.py",
    ),
    "runtime_core_transition_runtime_inventory": (
        "cisco_toolkit.transition_runtime_inventory",
        "$PROJECT_ROOT/cisco_toolkit/transition_runtime_inventory.py"
    ),
    "runtime_core_transition_tcb_review": (
        "cisco_toolkit.transition_tcb_review",
        "$PROJECT_ROOT/cisco_toolkit/transition_tcb_review.py"
    ),
    "runtime_core_transition_verifier": (
        "cisco_toolkit.transition_verifier",
        "$PROJECT_ROOT/cisco_toolkit/transition_verifier.py"
    ),
}


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
        "runtime_inventory_digest": _digest("runtime inventory"),
        "approved_runtime_inventory_state": tr.TCB_BUDGET_REVIEW_RUNTIME_STATE,
        "budget_proposal_digest": _digest("budget proposal"),
        "dsl_interpreter_digest": _digest("DSL interpreter"),
        "prototype_program_digest": _digest("prototype program"),
        "prototype_pack_manifest_digest": _digest("prototype pack manifest"),
        "tcb_budget_subject_digest": _digest("TCB budget subject"),
        "approved_core_sloc_budget": 2_500,
        "approved_pack_sloc_budget": 500,
        "approved_dsl_resource_profile": _resource_profile(),
        "approved_receipt_container_ceiling": dsl.dsl_receipt_container_ceiling(
            _resource_profile()
        ),
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
        "runtime_inventory_digest": receipt["runtime_inventory_digest"],
        "approved_runtime_inventory_state": receipt["approved_runtime_inventory_state"],
        "budget_proposal_digest": receipt["budget_proposal_digest"],
        "dsl_interpreter_digest": receipt["dsl_interpreter_digest"],
        "prototype_program_digest": receipt["prototype_program_digest"],
        "prototype_pack_manifest_digest": receipt["prototype_pack_manifest_digest"],
        "tcb_budget_subject_digest": receipt["tcb_budget_subject_digest"],
        "measurement_denominator_digest": receipt["measurement_denominator_digest"],
    }


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
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
                "allowed_source_revisions": [{
                    "selected_commit": receipt["selected_commit"],
                    "selected_tree": receipt["selected_tree"],
                    "tcb_budget_subject_digest": receipt["tcb_budget_subject_digest"],
                }],
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


def _current_freeze_candidate(
        *,
        mutation: str | None = None) -> tuple[
        dict[str, Any],
        tp.BoundPackManifest,
        tp.BoundTCBManifest,
        tr.VerifiedTCBBudgetReview,
        dict[str, bytes],
        bytes]:
    """Build a test-only signed request over the real canonical R2.0 evidence.

    The generated key exercises cryptographic joins only.  It is not packaged, trusted outside
    this process, or represented as independent authority, and the real partial runtime evidence
    must still prevent the freeze from binding.
    """

    paths = {
        "structural_census_digest": "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
        "prototype_measurement_digest": "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
        "runtime_inventory_digest": "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json",
        "budget_proposal_digest": "cisco_toolkit/data/atlas-r2-tcb-budget-proposal.v1.json",
        "dsl_interpreter_digest": "cisco_toolkit/transition_dsl.py",
        "prototype_program_digest": dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        "prototype_pack_manifest_digest": dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH,
    }
    evidence = {field: (ROOT / path).read_bytes() for field, path in paths.items()}
    runtime_value = tc.parse_canonical_json_bytes(
        evidence["runtime_inventory_digest"],
        require_canonical=True,
    )
    if mutation in {
            "runtime_cryptography_version_teleport",
            "runtime_program_digest_teleport",
            "runtime_input_digest_teleport",
            "runtime_receipt_digest_teleport",
            "runtime_core_module_file_teleport",
            *_RUNTIME_CORE_MUTATION_PATHS,
    }:
        if mutation == "runtime_cryptography_version_teleport":
            runtime_value["profile"]["crypto_probe"]["cryptography_version"] = "999.0.0"
        elif mutation in {
                "runtime_program_digest_teleport",
                "runtime_input_digest_teleport",
        }:
            role, digest_field = (
                (
                    "PROTOTYPE_DECLARATIVE_PROGRAM",
                    "program_digest",
                )
                if mutation == "runtime_program_digest_teleport"
                else ("PROTOTYPE_TYPED_INPUT", "input_digest")
            )
            runtime_row = next(
                row for row in runtime_value["runtime_files"]
                if role in row["roles"]
            )
            teleported_digest = _digest(f"teleported runtime {digest_field}")
            runtime_row["digest"] = teleported_digest
            runtime_row["file_id"] = runtime_inventory._runtime_file_id(
                runtime_row["path_token"],
                teleported_digest,
            )
            runtime_value["profile"]["prototype"][digest_field] = teleported_digest
            runtime_value["runtime_files"].sort(
                key=lambda item: (item["path_token"], item["digest"])
            )
        elif mutation == "runtime_receipt_digest_teleport":
            runtime_value["profile"]["prototype"]["receipt_digest"] = _digest(
                "teleported runtime inner receipt"
            )
        elif mutation == "runtime_core_module_file_teleport":
            module_row = next(
                row for row in runtime_value["python_modules"]
                if row["module_name"] == "cisco_toolkit.transition_contract"
            )
            alternate_file = next(
                row for row in runtime_value["runtime_files"]
                if row["path_token"] == "$PROJECT_ROOT/cisco_toolkit/__init__.py"
            )
            module_row["file_id"] = alternate_file["file_id"]
        else:
            module_name, path_token = _RUNTIME_CORE_MUTATION_PATHS[mutation]
            runtime_row = next(
                row for row in runtime_value["runtime_files"]
                if row["path_token"] == path_token
            )
            teleported_digest = _digest(f"teleported {mutation}")
            runtime_row["digest"] = teleported_digest
            runtime_row["file_id"] = runtime_inventory._runtime_file_id(
                runtime_row["path_token"],
                teleported_digest,
            )
            module_row = next(
                row for row in runtime_value["python_modules"]
                if row["module_name"] == module_name
            )
            module_row["file_id"] = runtime_row["file_id"]
            runtime_value["runtime_files"].sort(
                key=lambda item: (item["path_token"], item["digest"])
            )
        if mutation != "runtime_core_module_file_teleport":
            runtime_inventory.validate_runtime_inventory(runtime_value)
        evidence["runtime_inventory_digest"] = tc.canonical_json_bytes(runtime_value)
        census = tc.parse_canonical_json_bytes(
            evidence["structural_census_digest"],
            require_canonical=True,
        )
        census_prototype = census["executable_prototype"]
        census_prototype["runtime_inventory"]["asset_digest"] = tc.bytes_digest(
            evidence["runtime_inventory_digest"]
        )
        runtime_binding = next(
            row for row in census_prototype["asset_bindings"]
            if row["path"] == runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH
        )
        runtime_binding["bytes"] = len(evidence["runtime_inventory_digest"])
        runtime_binding["sha256"] = tc.bytes_digest(evidence["runtime_inventory_digest"])
        evidence["structural_census_digest"] = tc.canonical_json_bytes(census)
    measurements = tc.parse_canonical_json_bytes(
        evidence["prototype_measurement_digest"], require_canonical=True
    )
    if "MAX_RECEIPT_CONTAINER_CEILING_NOT_DEFINED" in measurements["measurement_gaps"]:
        measurements["measurement_gaps"].remove(
            "MAX_RECEIPT_CONTAINER_CEILING_NOT_DEFINED"
        )
    aggregate_gap = (
        "UNINSTRUMENTED_DEPTH_OPERAND_PATH_STRING_AND_SET_TARGETS_ARE_"
        "SIGNED_AGGREGATE_CLAIMS_ONLY"
    )
    if aggregate_gap not in measurements["measurement_gaps"]:
        partial_gap = "RUNTIME_CLOSURE_REMAINS_PARTIAL_NONPORTABLE_PROTOTYPE"
        insertion_index = (
            measurements["measurement_gaps"].index(partial_gap)
            if partial_gap in measurements["measurement_gaps"]
            else len(measurements["measurement_gaps"])
        )
        measurements["measurement_gaps"].insert(insertion_index, aggregate_gap)
    measurements["measurement_gaps"].sort()
    if mutation == "measurement_boundary":
        measurements["boundary_measurements"][0]["boundaries"][0][
            "target_dimension_value"
        ] += 1
    elif mutation == "measurement_digest_shape":
        measurements["boundary_measurements"][0]["boundaries"][0][
            "program_digest"
        ] = "fiction"
    elif mutation == "measurement_work_size":
        measurements["boundary_measurements"][0]["boundaries"][0]["work_units"][
            "program_bytes"
        ] += 1
    elif mutation == "measurement_target_work":
        measurements["boundary_measurements"][3]["boundaries"][1]["work_units"][
            "rules"
        ] += 1
    elif mutation == "measurement_supplemental_work":
        measurements["supplemental_measurements"][3]["work_units"][
            "expression_nodes"
        ] += 1
    elif mutation == "measurement_claim_boundary":
        measurements["claim_boundary"] = "Fictional locally replayed measurement authority."
    elif mutation == "measurement_design_correction":
        measurements["design_corrections"][0]["corrected_provisional_value"] += 1
    elif mutation == "measurement_performance":
        measurements["boundary_measurements"][0]["boundaries"][0][
            "performance_reference"
        ] = [{"elapsed_ns": -1, "tracemalloc_peak_bytes": 0}]
    elif mutation == "measurement_receipt_size":
        measurements["boundary_measurements"][0]["boundaries"][0][
            "raw_receipt_bytes"
        ] = 1
    elif mutation == "measurement_hostile_empty":
        measurements["hostile_measurements"] = []
    elif mutation == "measurement_supplemental_empty":
        measurements["supplemental_measurements"] = []
    elif mutation == "measurement_baseline_empty":
        measurements["baseline_execution"] = {}
    elif mutation == "measurement_tool_empty":
        measurements["bindings"]["measurement_tool"] = {}
    elif mutation == "measurement_input_empty":
        measurements["bindings"]["prototype_input"] = {}
    elif mutation == "measurement_tcb_empty":
        measurements["bindings"]["tcb_manifest"] = {}
    elif mutation == "measurement_toolchains_empty":
        measurements["bindings"]["declared_toolchains"] = []
    elif mutation == "measurement_abi_fiction":
        measurements["bindings"]["pack_abi_version"] = "FICTION/1"
    evidence["prototype_measurement_digest"] = tc.canonical_json_bytes(measurements)
    evidence["measurement_denominator_digest"] = tc.canonical_json_bytes(
        measurements["measurement_denominator"]
    )
    census = tc.parse_canonical_json_bytes(
        evidence["structural_census_digest"],
        require_canonical=True,
    )
    measurement_binding = next(
        row for row in census["executable_prototype"]["asset_bindings"]
        if row["path"] == paths["prototype_measurement_digest"]
    )
    measurement_binding["bytes"] = len(evidence["prototype_measurement_digest"])
    measurement_binding["sha256"] = tc.bytes_digest(
        evidence["prototype_measurement_digest"]
    )
    evidence["structural_census_digest"] = tc.canonical_json_bytes(census)
    if mutation is not None and mutation.startswith("census_"):
        census = tc.parse_canonical_json_bytes(
            evidence["structural_census_digest"],
            require_canonical=True,
        )
        prototype = census["executable_prototype"]
        if mutation == "census_interpreter":
            prototype["interpreter_source"]["sha256"] = _digest(
                "fictional interpreter"
            )
        elif mutation == "census_prototype_extra":
            prototype["fictional_authority"] = False
        elif mutation == "census_interpreter_extra":
            prototype["interpreter_source"]["fictional_attestation"] = False
        elif mutation == "census_asset_extra":
            prototype["asset_bindings"].append(deepcopy(prototype["asset_bindings"][0]))
        elif mutation == "census_asset_field_extra":
            prototype["asset_bindings"][0]["fictional_attestation"] = False
        elif mutation == "census_asset_role":
            prototype["asset_bindings"][0]["role"] = "FICTIONAL_PACK_ROLE"
        elif mutation == "census_asset_order":
            prototype["asset_bindings"][0], prototype["asset_bindings"][1] = (
                prototype["asset_bindings"][1],
                prototype["asset_bindings"][0],
            )
        evidence["structural_census_digest"] = tc.canonical_json_bytes(census)
    proposal = tc.parse_canonical_json_bytes(
        evidence["budget_proposal_digest"], require_canonical=True
    )
    proposal["measurement_gaps"] = measurements["measurement_gaps"]
    proposal["receipt_container_ceiling_proposal"] = dsl.dsl_receipt_container_ceiling(
        proposal["dsl_resource_profile_proposal"]
    )
    for field in (
            "structural_census_digest",
            "prototype_measurement_digest",
            "runtime_inventory_digest",
            "prototype_program_digest",
            "prototype_pack_manifest_digest"):
        proposal["bindings"][field] = tc.bytes_digest(evidence[field])
    for index, measurement_row in enumerate(measurements["boundary_measurements"]):
        proposal["boundary_evidence"][index]["measurement_row_digest"] = (
            tc.canonical_digest(measurement_row)
        )
    evidence["budget_proposal_digest"] = tc.canonical_json_bytes(proposal)

    material = _material()
    for field, raw in evidence.items():
        material["receipt"][field] = tc.bytes_digest(raw)
    material["receipt"]["approved_core_sloc_budget"] = proposal[
        "core_budget_proposal"
    ]["proposed_core_sloc_budget"]
    material["receipt"]["approved_pack_sloc_budget"] = proposal[
        "pack_budget_proposal"
    ]["proposed_pack_sloc_budget"]
    material["receipt"]["approved_dsl_resource_profile"] = proposal[
        "dsl_resource_profile_proposal"
    ]
    material["receipt"]["approved_receipt_container_ceiling"] = proposal[
        "receipt_container_ceiling_proposal"
    ]

    tcb = tc.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH).read_bytes(),
        require_canonical=True,
    )
    supported = measurements["bindings"]["supported_denominator"]
    program_raw = evidence["prototype_program_digest"]
    tcb["pack_sources"] = [
        {
            "artifact_id": "atlas.r2-dsl-prototype-program",
            "artifact_version": "1.0.0",
            "bytes": len(program_raw),
            "digest": tc.bytes_digest(program_raw),
            "path": dsl.DSL_PROTOTYPE_PROGRAM_PATH,
            "role": tp.DECLARATIVE_PROGRAM_SOURCE_ROLE,
        },
        {
            "artifact_id": "atlas.r2-dsl-supported-denominator",
            "artifact_version": "1.0.0",
            "bytes": supported["raw_bytes"],
            "digest": supported["digest"],
            "path": supported["path"],
            "role": tp.SUPPORTED_DENOMINATOR_SOURCE_ROLE,
        },
    ]
    tcb["runtime_inventory_state"] = (
        tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
    )
    tcb["transitive_dependencies"] = sorted(
        (
            {
                "component_id": row["file_id"],
                "component_version": "REFERENCE_FILE/1",
                "content_digest": row["digest"],
            }
            for row in runtime_value["runtime_files"]
        ),
        key=lambda row: row["component_id"],
    )
    tcb["budget_state"] = tp.TCBBudgetState.FROZEN.value
    tcb["core_sloc_budget"] = material["receipt"]["approved_core_sloc_budget"]
    tcb["pack_sloc_budget"] = material["receipt"]["approved_pack_sloc_budget"]
    tcb["resource_ceilings"] = {
        "dsl": {
            field: material["receipt"]["approved_dsl_resource_profile"][field]
            for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
        },
        "wasm": None,
    }
    if mutation == "runtime_tcb_roster":
        tcb["transitive_dependencies"][0]["content_digest"] = _digest(
            "fictional runtime dependency"
        )
    elif mutation == "tcb_interpreter_identity":
        tcb["dsl_interpreter"]["component_id"] = "atlas.fictional-interpreter"
    elif mutation == "tcb_pack_count":
        tcb["pack_executable_lines"] = 1
    subject_digest = tr.tcb_budget_review_subject_digest(tcb)
    material["receipt"]["tcb_budget_subject_digest"] = subject_digest
    material["bindings"] = _bindings(material["receipt"])
    material["policy"]["trusted_keys"][0]["allowed_source_revisions"][0][
        "tcb_budget_subject_digest"
    ] = subject_digest
    _resign(material)
    verified = _verify(material)
    tcb["budget_review_receipt_digest"] = verified.review_digest
    bound_tcb = tp.bind_tcb_manifest_bytes(tc.canonical_json_bytes(tcb))
    final_pack = tc.parse_canonical_json_bytes(
        evidence["prototype_pack_manifest_digest"],
        require_canonical=True,
    )
    final_pack["tcb_manifest_digest"] = bound_tcb.digest
    bound_pack = tp.bind_pack_manifest_bytes(tc.canonical_json_bytes(final_pack))
    freeze = {
        "schema": tr.R2_TCB_BUDGET_FREEZE_SCHEMA,
        "purpose": tr.R2_TCB_BUDGET_FREEZE_PURPOSE,
        "source_freeze_state": tr.R2_TCB_BUDGET_FREEZE_SOURCE_STATE,
        "selected_source_commit": verified.selected_commit,
        "selected_source_tree": verified.selected_tree,
        **{
            field: getattr(verified, field)
            for field in tr.R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS
        },
        "approved_runtime_inventory_state": verified.approved_runtime_inventory_state,
        "tcb_budget_subject_digest": verified.tcb_subject_digest,
        "final_pack_manifest_digest": bound_pack.digest,
        "final_tcb_manifest_digest": bound_tcb.digest,
        "review_receipt_digest": verified.review_digest,
        "review_signature_digest": verified.signature_digest,
        "review_trust_policy_digest": verified.policy_digest,
        "review_public_key_digest": verified.trusted_public_key_digest,
        "core_sloc_budget": verified.core_sloc_budget,
        "pack_sloc_budget": verified.pack_sloc_budget,
        "dsl_resource_profile": verified.dsl_resource_profile,
        "receipt_container_ceiling": verified.receipt_container_ceiling,
        "wasm_review_state": "UNREVIEWED",
        "qcp_001": {
            "schema": tr.R2_TCB_BUDGET_FREEZE_QCP_SCHEMA,
            "pack_id": "QCP-001",
            "pack_version": "0.1.0-experimental",
            "qualification_state": "EXPERIMENTAL",
            "execution_state": "CONTRACT_ONLY",
            "qualification_effect": "NONE",
            "promotion_eligible": False,
        },
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "release3_included": False,
    }
    supported_denominator_raw = (ROOT / dsl.DSL_PROTOTYPE_DENOMINATOR_PATH).read_bytes()
    return freeze, bound_pack, bound_tcb, verified, evidence, supported_denominator_raw


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
    assert verified.approved_runtime_inventory_state == tr.TCB_BUDGET_REVIEW_RUNTIME_STATE
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


def test_detached_freeze_joins_exact_evidence_source_commit_review_and_frozen_tcb() -> None:
    (
        freeze,
        bound_pack,
        bound_tcb,
        verified,
        evidence_raw,
        supported_denominator_raw,
    ) = _current_freeze_candidate()
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(freeze),
            bound_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_representative_workload_adequacy_evidence_absent",
    )

    detached_source = deepcopy(freeze)
    detached_source["selected_source_commit"] = "c" * 40
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(detached_source),
            bound_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_review_binding_mismatch",
    )

    prototype_pack = tp.bind_pack_manifest_bytes(
        evidence_raw["prototype_pack_manifest_digest"]
    )
    detached_pack = deepcopy(freeze)
    detached_pack["final_pack_manifest_digest"] = prototype_pack.digest
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(detached_pack),
            prototype_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_pack_binding_mismatch",
    )

    hostile_evidence = dict(evidence_raw)
    hostile_evidence["runtime_inventory_digest"] = b"substituted runtime"
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(freeze),
            bound_pack,
            bound_tcb,
            verified,
            hostile_evidence,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_evidence_binding_mismatch",
    )

    hostile_denominator = tc.parse_canonical_json_bytes(
        supported_denominator_raw,
        require_canonical=True,
    )
    hostile_denominator["denominator_id"] = "denominator.fictional"
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(freeze),
            bound_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=tc.canonical_json_bytes(hostile_denominator),
        ),
        "r2_tcb_budget_freeze_malformed",
    )

    opaque_evidence = {
        field: f"opaque {field}".encode("ascii")
        for field in tr.R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS
    }
    opaque_material = _material()
    for field, raw in opaque_evidence.items():
        opaque_material["receipt"][field] = tc.bytes_digest(raw)
    opaque_material["receipt"]["tcb_budget_subject_digest"] = verified.tcb_subject_digest
    opaque_material["bindings"] = _bindings(opaque_material["receipt"])
    opaque_material["policy"]["trusted_keys"][0]["allowed_source_revisions"][0][
        "tcb_budget_subject_digest"
    ] = verified.tcb_subject_digest
    _resign(opaque_material)
    opaque_review = _verify(opaque_material)
    opaque_freeze = deepcopy(freeze)
    for field in tr.R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS:
        opaque_freeze[field] = getattr(opaque_review, field)
    opaque_freeze.update({
        "review_receipt_digest": opaque_review.review_digest,
        "review_signature_digest": opaque_review.signature_digest,
        "review_trust_policy_digest": opaque_review.policy_digest,
        "review_public_key_digest": opaque_review.trusted_public_key_digest,
    })
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(opaque_freeze),
            bound_pack,
            bound_tcb,
            opaque_review,
            opaque_evidence,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_malformed",
    )


def test_reviewed_execution_rejects_a_direct_review_without_final_freeze() -> None:
    verified = _verify(_material())
    with pytest.raises(dsl.DSLPrototypeError) as caught:
        dsl.run_reviewed_dsl_pack_abi(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            verified,
            "evaluate",
            tc.canonical_json_bytes({}),
            tc.canonical_json_bytes({}),
        )
    assert caught.value.code == "REVIEWED_DSL_CUSTODY_INVALID"


def test_representative_workload_absence_interlock_precedes_runtime_freeze() -> None:
    (
        freeze,
        bound_pack,
        bound_tcb,
        verified,
        evidence_raw,
        supported_denominator_raw,
    ) = _current_freeze_candidate()
    measurements = tc.parse_canonical_json_bytes(
        evidence_raw["prototype_measurement_digest"],
        require_canonical=True,
    )
    proposal = tc.parse_canonical_json_bytes(
        evidence_raw["budget_proposal_digest"],
        require_canonical=True,
    )
    assert (
        "REPRESENTATIVE_FIELD_WORKLOAD_DENOMINATOR_ABSENT"
        in measurements["measurement_gaps"]
    )
    assert (
        "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT"
        in measurements["review_state"]["blockers"]
    )
    assert (
        "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT"
        in proposal["approval"]["blockers"]
    )
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(freeze),
            bound_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_representative_workload_adequacy_evidence_absent",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "census_interpreter",
        "census_prototype_extra",
        "census_interpreter_extra",
        "census_asset_extra",
        "census_asset_field_extra",
        "census_asset_role",
        "census_asset_order",
        "measurement_boundary",
        "measurement_digest_shape",
        "measurement_work_size",
        "measurement_target_work",
        "measurement_supplemental_work",
        "measurement_claim_boundary",
        "measurement_design_correction",
        "measurement_performance",
        "measurement_receipt_size",
        "measurement_hostile_empty",
        "measurement_supplemental_empty",
        "measurement_baseline_empty",
        "measurement_tool_empty",
        "measurement_input_empty",
        "measurement_tcb_empty",
        "measurement_toolchains_empty",
        "measurement_abi_fiction",
        "runtime_tcb_roster",
        "runtime_cryptography_version_teleport",
        "runtime_program_digest_teleport",
        "runtime_input_digest_teleport",
        "runtime_receipt_digest_teleport",
        "runtime_core_module_file_teleport",
        *_RUNTIME_CORE_MUTATION_PATHS,
        "tcb_interpreter_identity",
        "tcb_pack_count",
    ),
)
def test_rechained_review_still_rejects_fictional_or_incoherent_evidence(
        mutation: str) -> None:
    (
        freeze,
        bound_pack,
        bound_tcb,
        verified,
        evidence_raw,
        supported_denominator_raw,
    ) = _current_freeze_candidate(mutation=mutation)
    _assert_refusal(
        lambda: tr.bind_r2_tcb_budget_freeze_bytes(
            tc.canonical_json_bytes(freeze),
            bound_pack,
            bound_tcb,
            verified,
            evidence_raw,
            supported_denominator_raw=supported_denominator_raw,
        ),
        "r2_tcb_budget_freeze_malformed",
    )


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

    rejected = _verify(_material(decision="REJECTED"))
    object.__setattr__(rejected, "decision", "APPROVED")
    object.__setattr__(rejected, "approved", True)
    object.__setattr__(rejected, "core_sloc_budget", 1)
    object.__setattr__(rejected, "_integrity_digest", rejected._compute_integrity_digest())
    _assert_refusal(
        lambda: tr.require_verified_tcb_budget_review(rejected),
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
    detached = bound["trusted_keys"]
    detached[0]["allowed_source_revisions"] = [{
        "selected_commit": "c" * 40,
        "selected_tree": "d" * 40,
        "tcb_budget_subject_digest": _digest("detached subject"),
    }]
    assert bound["trusted_keys"] != detached
    assert tr.require_bound_tcb_budget_review_trust_policy(bound) is bound
    with pytest.raises(AttributeError, match="immutable"):
        bound._bound_digest = _digest("rechained policy")  # type: ignore[misc]

    hostile = tc.parse_canonical_json_bytes(bound._bound_raw, require_canonical=True)
    hostile["trusted_keys"][0]["allowed_source_revisions"] = [{
        "selected_commit": "c" * 40,
        "selected_tree": "d" * 40,
        "tcb_budget_subject_digest": _digest("hostile subject"),
    }]
    object.__setattr__(bound, "_bound_raw", tc.canonical_json_bytes(hostile))
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
            ("target_schema_version", "atlas.tcb-budget-review-receipt/1"),
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
        "runtime_inventory_digest",
        "budget_proposal_digest",
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


def test_trust_key_subject_constraints_are_closed() -> None:
    material = _material()
    material["policy"]["trusted_keys"][0]["allowed_source_revisions"] = [{
        "selected_commit": "c" * 40,
        "selected_tree": "d" * 40,
        "tcb_budget_subject_digest": _digest("other subject"),
    }]
    _resign(material)

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_subject_not_authorized")


def test_trust_policy_authorizes_an_exact_commit_tree_pair_not_a_cross_product() -> None:
    material = _material()
    material["policy"]["trusted_keys"][0]["allowed_source_revisions"] = [
        {
            "selected_commit": _COMMIT,
            "selected_tree": "c" * 40,
            "tcb_budget_subject_digest": material["receipt"]["tcb_budget_subject_digest"],
        },
        {
            "selected_commit": "c" * 40,
            "selected_tree": _TREE,
            "tcb_budget_subject_digest": material["receipt"]["tcb_budget_subject_digest"],
        },
    ]
    _assert_refusal(lambda: _verify(material), "tcb_budget_review_subject_not_authorized")


def test_public_key_policy_and_key_id_substitution_fail_closed() -> None:
    substitute = _material()
    substitute["public_key_raw"] = _public_key_bytes(Ed25519PrivateKey.generate())
    _assert_refusal(lambda: _verify(substitute), "tcb_budget_review_key_not_trusted")

    policy_swap = _material()
    policy_swap["policy"]["policy_id"] = "different-policy.fixture"
    original_signature = deepcopy(policy_swap["signature"])
    verified = _verify(policy_swap)
    assert verified.policy_digest == tc.canonical_digest(policy_swap["policy"])
    assert policy_swap["signature"] == original_signature

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
    _assert_refusal(lambda: _verify(revoked), "tcb_budget_review_receipt_revoked")


def test_receipt_issue_and_validity_interval_is_structurally_closed() -> None:
    material = _material()
    material["receipt"]["issued_at"] = "2026-08-22T00:00:00.000001Z"

    _assert_refusal(lambda: _verify(material), "tcb_budget_review_evidence_malformed")


@pytest.mark.parametrize(
    "attack",
    ("bit_flip", "wrong_domain", "wrong_payload", "wrong_algorithm", "bad_base64"),
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


def test_receipt_container_contract_is_formula_validated_and_signature_covered() -> None:
    malformed = _material()
    malformed["receipt"]["approved_receipt_container_ceiling"][
        "inner_receipt_ceiling_bytes"
    ] += 1
    _assert_refusal(
        lambda: _verify(malformed),
        "tcb_budget_review_evidence_malformed",
    )

    valid_alternative = _material()
    valid_alternative["receipt"]["approved_dsl_resource_profile"][
        "max_output_bytes"
    ] -= 1
    valid_alternative["receipt"]["approved_receipt_container_ceiling"] = (
        dsl.dsl_receipt_container_ceiling(
            valid_alternative["receipt"]["approved_dsl_resource_profile"]
        )
    )
    _assert_refusal(
        lambda: _verify(valid_alternative),
        "tcb_budget_review_signature_binding_mismatch",
    )
    valid_alternative["signature"]["payload_digest"] = tc.canonical_digest(
        valid_alternative["receipt"]
    )
    _assert_refusal(
        lambda: _verify(valid_alternative),
        "tcb_budget_review_signature_invalid",
    )


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
