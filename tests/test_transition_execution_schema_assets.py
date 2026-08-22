"""Mechanical schema parity and hostile-field gates for R2.0 execution evidence."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import replace
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_tcb_review as tr


ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_RESOURCE = "schemas/atlas-r2-execution-evidence-v1.schema.json"


def _resource_bytes(relative: str) -> bytes:
    root = resources.files("cisco_toolkit")
    return root.joinpath(*relative.split("/")).read_bytes()


def _schema() -> dict[str, Any]:
    return json.loads(_resource_bytes(_SCHEMA_RESOURCE))


def _validator_for(definition: str) -> Draft202012Validator:
    schema = _schema()
    return Draft202012Validator({
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    })


def _parsed(raw: bytes) -> dict[str, Any]:
    value = tc.parse_canonical_json_bytes(raw, require_canonical=True)
    assert type(value) is dict
    return value


def _packaged_prototype() -> dsl.BoundPackagedDSLPrototype:
    pack_raw = _resource_bytes(dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH.removeprefix("cisco_toolkit/"))
    tcb_raw = _resource_bytes(dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH.removeprefix("cisco_toolkit/"))
    program_raw = _resource_bytes(dsl.DSL_PROTOTYPE_PROGRAM_PATH.removeprefix("cisco_toolkit/"))
    denominator_raw = _resource_bytes(
        dsl.DSL_PROTOTYPE_DENOMINATOR_PATH.removeprefix("cisco_toolkit/")
    )
    tcb = _parsed(tcb_raw)
    source_map = {
        item["path"]: (ROOT / item["path"]).read_bytes()
        for item in [*tcb["core_sources"], *tcb["pack_sources"]]
    }
    source_map[dsl.DSL_PROTOTYPE_PROGRAM_PATH] = program_raw
    return dsl.bind_packaged_dsl_prototype_bytes(
        pack_raw,
        tcb_raw,
        program_raw,
        denominator_raw,
        source_map,
    )


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def _resource_profile() -> dict[str, Any]:
    return {
        "schema": tr.DSL_RESOURCE_PROFILE_SCHEMA,
        "substrate": "DECLARATIVE_DSL_ONLY",
        **{
            field_name: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field_name)
            for field_name in tr.DSL_RESOURCE_PROFILE_FIELDS
        },
    }


def _review_material() -> dict[str, dict[str, Any]]:
    commit = "a" * 40
    tree = "b" * 40
    reviewer_key_id = "tcb-reviewer-key.schema-fixture.001"
    receipt = {
        "schema": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
        "receipt_id": "tcb-budget-review.schema-fixture.001",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "selected_commit": commit,
        "selected_tree": tree,
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
        "decision": "APPROVED",
        "issued_at": "2026-08-22T00:00:00.000000Z",
        "valid_from": "2026-08-22T00:00:00.000000Z",
        "valid_until": "2026-09-22T00:00:00.000000Z",
        "reviewer_key_id": reviewer_key_id,
    }
    trusted_key = {
        "schema": tr.TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA,
        "key_id": reviewer_key_id,
        "public_key_digest": _digest("external public key bytes"),
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
        "allowed_selected_commits": [commit],
        "allowed_selected_trees": [tree],
        "allowed_tcb_subject_digests": [receipt["tcb_budget_subject_digest"]],
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2027-01-01T00:00:00.000000Z",
    }
    policy = {
        "schema": tr.TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA,
        "policy_kind": tr.TCB_BUDGET_REVIEW_POLICY_KIND,
        "policy_id": "tcb-budget-review-policy.schema-fixture",
        "policy_version": "1.0.0",
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "evaluated_at": "2026-08-23T00:00:00.000000Z",
        "trusted_keys": [trusted_key],
        "revoked_receipt_digests": [],
    }
    signature = {
        "schema": tr.TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA,
        "purpose": tr.TCB_BUDGET_REVIEW_PURPOSE,
        "payload_digest": tc.canonical_digest(receipt),
        "trust_policy_digest": tc.canonical_digest(policy),
        "signer_key_id": reviewer_key_id,
        "algorithm": tr.TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM,
        "signature_base64": base64.b64encode(b"\x00" * 64).decode("ascii"),
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
                "dsl_interpreter_digest",
                "prototype_program_digest",
                "prototype_pack_manifest_digest",
                "tcb_budget_subject_digest",
                "measurement_denominator_digest",
            )
        },
    }
    return {
        "receipt": receipt,
        "signature": signature,
        "trusted_key": trusted_key,
        "policy": policy,
        "bindings": bindings,
    }


def test_schema_is_valid_and_closed_vocabularies_match_code_owners_exactly() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    defs = schema["$defs"]

    schema_constants = {
        "declarativeBinding": dsl.DECLARATIVE_BINDING_SCHEMA,
        "declarativeInput": dsl.DECLARATIVE_INPUT_SCHEMA,
        "declarativeProgram": dsl.DECLARATIVE_PROGRAM_SCHEMA,
        "declarativeResult": dsl.DECLARATIVE_RESULT_SCHEMA,
        "innerPrototypeReceipt": dsl.DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA,
        "boundDeclarativePrototypeReceipt": dsl.BOUND_DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA,
        "dslResourceProfile": tr.DSL_RESOURCE_PROFILE_SCHEMA,
        "tcbBudgetReviewReceipt": tr.TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
        "tcbBudgetReviewSignature": tr.TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA,
        "tcbBudgetReviewAuthorization": tr.TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA,
        "tcbBudgetReviewTrustedKey": tr.TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA,
        "tcbBudgetReviewTrustPolicy": tr.TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA,
        "tcbBudgetReviewExpectedBindings": tr.TCB_BUDGET_REVIEW_BINDINGS_SCHEMA,
    }
    for definition, expected in schema_constants.items():
        assert defs[definition]["properties"]["schema"]["const"] == expected

    expression_definitions = {
        item["$ref"].rsplit("/", maxsplit=1)[-1]
        for item in defs["declarativeExpression"]["oneOf"]
    }
    schema_operators = {
        defs[definition]["properties"]["op"]["const"]
        for definition in expression_definitions
    }
    assert tuple(dsl.DECLARATIVE_DSL_OPERATORS) == tp.DECLARATIVE_DSL_OPERATORS
    assert schema_operators == set(dsl.DECLARATIVE_DSL_OPERATORS)
    assert tuple(dsl.PACK_ABI_FUNCTIONS) == tp.PACK_ABI_FUNCTIONS
    assert defs["declarativeRule"]["properties"]["function"]["enum"] == list(
        dsl.PACK_ABI_FUNCTIONS[:-1]
    )
    assert defs["innerPrototypeReceipt"]["properties"]["function"]["oneOf"][0][
        "enum"
    ] == list(dsl.PACK_ABI_FUNCTIONS)
    assert defs["declarativeProgram"]["properties"]["abi_version"]["const"] == (
        tc.PACK_ABI_VERSION
    )

    limit_fields = set(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
    assert limit_fields == set(tr.DSL_RESOURCE_PROFILE_FIELDS)
    assert set(defs["dslLimitProfile"]["properties"]) == limit_fields
    assert set(defs["dslResourceProfile"]["properties"]) - {"schema", "substrate"} == (
        limit_fields
    )
    assert set(defs["declarativeTruth"]["enum"]) == set(dsl.TRUTH_VALUES)
    assert set(defs["declarativeTruth"]["enum"]).isdisjoint(
        item.value for item in tc.AuthoritativeGate
    )
    assert set(defs["tcbBudgetReviewDecision"]["enum"]) == {
        item.value for item in tr.TCBBudgetReviewDecision
    }
    assert defs["tcbBudgetReviewReceipt"]["properties"]["wasm_review_state"] == {
        "const": "UNREVIEWED"
    }
    trusted_key = defs["tcbBudgetReviewTrustedKey"]["properties"]
    assert trusted_key["reviewer_kind"] == {"const": tr.TCB_BUDGET_REVIEWER_KIND}
    for field in (
            "independent_from_budget_proposer",
            "independent_from_prototype_and_measurement_producer",
            "independent_from_release_builder"):
        assert trusted_key[field] == {"const": True}
    assert defs["tcbBudgetReviewTrustPolicy"]["properties"]["policy_kind"] == {
        "const": tr.TCB_BUDGET_REVIEW_POLICY_KIND
    }

    outer = defs["boundDeclarativePrototypeReceipt"]["properties"]
    assert outer["source_binding_state"]["const"] == dsl.DSL_PROTOTYPE_SOURCE_BINDING_STATE
    assert outer["pack_id"]["const"] == dsl.DSL_PROTOTYPE_PACK_ID
    assert outer["pack_version"]["const"] == dsl.DSL_PROTOTYPE_PACK_VERSION


def test_real_packaged_program_input_and_runtime_receipts_validate() -> None:
    program_raw = _resource_bytes(dsl.DSL_PROTOTYPE_PROGRAM_PATH.removeprefix("cisco_toolkit/"))
    input_raw = _resource_bytes(dsl.DSL_PROTOTYPE_INPUT_PATH.removeprefix("cisco_toolkit/"))
    program = _parsed(program_raw)
    input_value = _parsed(input_raw)

    _validator_for("declarativeProgram").validate(program)
    _validator_for("declarativeInput").validate(input_value)

    executed_raw = dsl.run_pack_abi("evaluate", program_raw, input_raw)
    executed = _parsed(executed_raw)
    _validator_for("innerPrototypeReceipt").validate(executed)
    assert executed["outcome"] == "EXECUTED_NONAUTHORITATIVE"
    assert executed["authoritative_gate"] is None
    assert executed["qualification_state"] == "EXPERIMENTAL"
    assert executed["execution_state"] == "CONTRACT_ONLY"

    refused = _parsed(dsl.run_pack_abi("replay_witness", program_raw, input_raw))
    _validator_for("innerPrototypeReceipt").validate(refused)
    assert refused["outcome"] == "REFUSED_NONAUTHORITATIVE"
    assert refused["error"] == {"code": "REPLAY_WITNESS_UNSUPPORTED_R2_0"}

    prototype = _packaged_prototype()
    bound_raw = dsl.run_bound_pack_abi(prototype, "evaluate", input_raw)
    bound = _parsed(bound_raw)
    Draft202012Validator(_schema()).validate(bound)
    assert bound["inner_receipt"] == executed
    assert bound["inner_receipt_digest"] == tc.bytes_digest(executed_raw)


def test_result_and_refusal_relationships_are_closed_and_truth_is_not_a_gate() -> None:
    program_raw = _resource_bytes(dsl.DSL_PROTOTYPE_PROGRAM_PATH.removeprefix("cisco_toolkit/"))
    input_raw = _resource_bytes(dsl.DSL_PROTOTYPE_INPUT_PATH.removeprefix("cisco_toolkit/"))
    validator = _validator_for("innerPrototypeReceipt")
    executed = _parsed(dsl.run_pack_abi("evaluate", program_raw, input_raw))
    refused = _parsed(dsl.run_pack_abi("replay_witness", program_raw, input_raw))

    hostile = deepcopy(executed)
    hostile["error"] = {"code": "LAUNDERED_SUCCESS"}
    with pytest.raises(ValidationError):
        validator.validate(hostile)

    hostile = deepcopy(refused)
    hostile["result"] = {"schema": dsl.DECLARATIVE_RESULT_SCHEMA, "entries": []}
    hostile["result_digest"] = _digest("hostile result")
    with pytest.raises(ValidationError):
        validator.validate(hostile)

    hostile = deepcopy(executed)
    inconclusive = next(
        entry for entry in hostile["result"]["entries"]
        if entry["truth"] == dsl.TRUTH_INCONCLUSIVE
    )
    inconclusive["value"] = {"gate": "ELIGIBLE_FOR_HUMAN_DECISION"}
    with pytest.raises(ValidationError):
        validator.validate(hostile)

    hostile = deepcopy(executed)
    hostile["result"]["entries"][0]["truth"] = "SUPPORTED"
    with pytest.raises(ValidationError):
        validator.validate(hostile)

    hostile = deepcopy(executed)
    hostile["result"]["entries"][0]["truth"] = "FIFTH_STATE"
    with pytest.raises(ValidationError):
        validator.validate(hostile)

    oversized = _parsed(dsl.run_pack_abi(
        "evaluate",
        program_raw + b" ",
        input_raw,
        limits=replace(
            dsl.DEFAULT_DSL_PROTOTYPE_LIMITS,
            max_program_bytes=len(program_raw),
        ),
    ))
    assert oversized["error"] == {"code": "PROGRAM_BYTE_LIMIT"}
    assert oversized["program_digest"] is None
    assert oversized["input_digest"] == tc.bytes_digest(input_raw)
    validator.validate(oversized)

    hostile = deepcopy(executed)
    hostile["program_digest"] = None
    with pytest.raises(ValidationError):
        validator.validate(hostile)


@pytest.mark.parametrize(
    ("field", "hostile_value"),
    (
        ("authoritative", True),
        ("supplies_obligation_support", True),
        ("qualification_effect", "QUALIFIES"),
        ("authoritative_gate", "ELIGIBLE_FOR_HUMAN_DECISION"),
        ("promotion_eligible", True),
        ("execution_state", "ACTIVATABLE"),
        ("qualification_state", "QUALIFIED"),
    ),
)
def test_inner_receipt_schema_rejects_every_authority_laundering_field(
        field: str, hostile_value: Any) -> None:
    program_raw = _resource_bytes(dsl.DSL_PROTOTYPE_PROGRAM_PATH.removeprefix("cisco_toolkit/"))
    input_raw = _resource_bytes(dsl.DSL_PROTOTYPE_INPUT_PATH.removeprefix("cisco_toolkit/"))
    receipt = _parsed(dsl.run_pack_abi("evaluate", program_raw, input_raw))
    receipt[field] = hostile_value

    with pytest.raises(ValidationError):
        _validator_for("innerPrototypeReceipt").validate(receipt)


def test_bound_receipt_is_closed_and_cannot_launder_prototype_authority() -> None:
    prototype = _packaged_prototype()
    input_raw = _resource_bytes(dsl.DSL_PROTOTYPE_INPUT_PATH.removeprefix("cisco_toolkit/"))
    receipt = _parsed(dsl.run_bound_pack_abi(prototype, "evaluate", input_raw))
    validator = Draft202012Validator(_schema())

    for field, value in (
        ("authoritative", True),
        ("supplies_obligation_support", True),
        ("qualification_effect", "QUALIFIES"),
        ("authoritative_gate", "ELIGIBLE_FOR_HUMAN_DECISION"),
        ("promotion_eligible", True),
    ):
        hostile = deepcopy(receipt)
        hostile[field] = value
        with pytest.raises(ValidationError):
            validator.validate(hostile)

    hostile = deepcopy(receipt)
    hostile["qualified_by"] = "self"
    with pytest.raises(ValidationError):
        validator.validate(hostile)


def test_review_structures_match_code_validators_without_bundled_authority() -> None:
    material = _review_material()
    validators = {
        "receipt": ("tcbBudgetReviewReceipt", tr.validate_tcb_budget_review_receipt),
        "signature": ("tcbBudgetReviewSignature", tr.validate_tcb_budget_review_signature),
        "policy": ("tcbBudgetReviewTrustPolicy", tr.validate_tcb_budget_review_trust_policy),
        "bindings": ("tcbBudgetReviewExpectedBindings", tr.validate_tcb_budget_review_bindings),
    }
    for name, (definition, code_validator) in validators.items():
        value = material[name]
        code_validator(value)
        _validator_for(definition).validate(value)

    tr.validate_dsl_resource_profile(material["receipt"]["approved_dsl_resource_profile"])
    _validator_for("dslResourceProfile").validate(
        material["receipt"]["approved_dsl_resource_profile"]
    )
    _validator_for("tcbBudgetReviewTrustedKey").validate(material["trusted_key"])

    rejected = deepcopy(material["receipt"])
    rejected["decision"] = "REJECTED"
    tr.validate_tcb_budget_review_receipt(rejected)
    _validator_for("tcbBudgetReviewReceipt").validate(rejected)


@pytest.mark.parametrize(
    ("name", "definition", "code_validator"),
    (
        ("receipt", "tcbBudgetReviewReceipt", tr.validate_tcb_budget_review_receipt),
        ("signature", "tcbBudgetReviewSignature", tr.validate_tcb_budget_review_signature),
        ("policy", "tcbBudgetReviewTrustPolicy", tr.validate_tcb_budget_review_trust_policy),
        ("bindings", "tcbBudgetReviewExpectedBindings", tr.validate_tcb_budget_review_bindings),
    ),
)
def test_review_schema_and_code_both_reject_open_fields(
        name: str, definition: str, code_validator: Any) -> None:
    value = deepcopy(_review_material()[name])
    value["authority"] = "SELF_ASSERTED"

    with pytest.raises(tc.TransitionContractError):
        code_validator(value)
    with pytest.raises(ValidationError):
        _validator_for(definition).validate(value)


def test_review_schema_rejects_fifth_decision_reviewed_wasm_and_open_trusted_key() -> None:
    material = _review_material()

    hostile_receipt = deepcopy(material["receipt"])
    hostile_receipt["decision"] = "PENDING"
    with pytest.raises(tc.TransitionContractError):
        tr.validate_tcb_budget_review_receipt(hostile_receipt)
    with pytest.raises(ValidationError):
        _validator_for("tcbBudgetReviewReceipt").validate(hostile_receipt)

    hostile_receipt = deepcopy(material["receipt"])
    hostile_receipt["wasm_review_state"] = "REVIEWED"
    with pytest.raises(tc.TransitionContractError):
        tr.validate_tcb_budget_review_receipt(hostile_receipt)
    with pytest.raises(ValidationError):
        _validator_for("tcbBudgetReviewReceipt").validate(hostile_receipt)

    hostile_policy = deepcopy(material["policy"])
    hostile_policy["trusted_keys"][0]["self_signed"] = True
    with pytest.raises(tc.TransitionContractError):
        tr.validate_tcb_budget_review_trust_policy(hostile_policy)
    with pytest.raises(ValidationError):
        _validator_for("tcbBudgetReviewTrustPolicy").validate(hostile_policy)
