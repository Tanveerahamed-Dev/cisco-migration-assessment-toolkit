"""Mechanical and authority-boundary tests for the R2 TCB budget proposal."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_tcb_review as review
from tools import build_transition_tcb_budget_proposal as proposal


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / proposal.RESOURCE
SCHEMA = ROOT / "cisco_toolkit/schemas/atlas-r2-tcb-budget-proposal-v1.schema.json"


def _asset() -> dict:
    raw = ASSET.read_bytes()
    value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
    assert raw == contract.canonical_json_bytes(value)
    return value


def _schema() -> dict:
    return json.loads(SCHEMA.read_bytes())


def test_budget_proposal_generator_and_schema_are_drift_free() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/build_transition_tcb_budget_proposal.py")],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_asset())
    review.validate_tcb_budget_proposal(_asset())


def test_exact_budget_formulas_recompute_from_current_census_and_program() -> None:
    value = _asset()
    census = contract.parse_canonical_json_bytes(
        (ROOT / proposal.CENSUS_RESOURCE).read_bytes(),
        require_canonical=True,
    )
    program_raw = (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes()
    program = contract.parse_canonical_json_bytes(program_raw, require_canonical=True)
    core_count = census["structural_core"]["executable_statements"]
    pack_count = dsl.declarative_program_semantic_statements(program)

    core = value["core_budget_proposal"]
    assert core["measured_executable_statements"] == core_count
    assert core["proposed_core_sloc_budget"] == proposal._core_budget(core_count)
    assert core["headroom_statements"] == core["proposed_core_sloc_budget"] - core_count

    pack = value["pack_budget_proposal"]
    assert pack["measured_semantic_statements"] == pack_count == 27
    assert pack["declarative_rule_records"] == 6
    assert pack["expression_operator_nodes"] == 21
    assert pack["proposed_pack_sloc_budget"] == proposal._next_power_of_two(pack_count) == 32
    assert pack["headroom_semantic_statements"] == 5


def test_every_proposed_ceiling_is_bound_to_real_n_minus_1_n_n_plus_1_evidence() -> None:
    value = _asset()
    rows = value["boundary_evidence"]
    assert [row["dimension"] for row in rows] == list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
    profile = value["dsl_resource_profile_proposal"]
    for row in rows:
        assert row["proposed_ceiling"] == profile[row["dimension"]]
        assert row["n_minus_1_outcome"] == "EXECUTED_NONAUTHORITATIVE"
        assert row["n_outcome"] == "EXECUTED_NONAUTHORITATIVE"
        assert row["n_plus_1_outcome"] == "REFUSED_NONAUTHORITATIVE"
        assert row["n_plus_1_error"].endswith("LIMIT")


def test_receipt_container_ceiling_is_formula_derived_from_the_exact_profile() -> None:
    value = _asset()
    expected = dsl.dsl_receipt_container_ceiling(value["dsl_resource_profile_proposal"])
    assert value["receipt_container_ceiling_proposal"] == expected
    assert expected["inner_receipt_ceiling_bytes"] == (
        expected["max_output_bytes"] + expected["inner_envelope_overhead_bytes"]
    )
    assert expected["bound_receipt_ceiling_bytes"] == (
        expected["inner_receipt_ceiling_bytes"]
        + expected["bound_wrapper_overhead_bytes"]
    )
    assert expected["reviewed_receipt_ceiling_bytes"] == (
        expected["inner_receipt_ceiling_bytes"]
        + expected["reviewed_wrapper_overhead_bytes"]
    )

    hostile = deepcopy(value)
    hostile["receipt_container_ceiling_proposal"][
        "inner_envelope_overhead_bytes"
    ] += 1
    with pytest.raises(contract.TransitionContractError):
        review.validate_tcb_budget_proposal(hostile)


def test_proposal_cannot_launder_approval_qualification_or_release3() -> None:
    value = _asset()
    assert value["authoritative"] is False
    assert value["approval"]["approved"] is False
    assert value["approval"]["review_receipt_digest"] is None
    assert value["runtime_closure"]["complete_exact_runtime_closure"] is False
    assert value["qcp_001"] == {
        "pack_id": "QCP-001",
        "pack_version": "0.1.0-experimental",
        "qualification_state": "EXPERIMENTAL",
        "execution_state": "CONTRACT_ONLY",
        "qualification_effect": "NONE",
        "promotion_eligible": False,
    }
    assert value["qualification_effect"] == "NONE"
    assert value["promotion_eligible"] is False
    assert value["release3_included"] is False
    validator = Draft202012Validator(_schema())
    for path, replacement in (
        (("authoritative",), True),
        (("approval", "approved"), True),
        (("qcp_001", "qualification_state"), "QUALIFIED"),
        (("qcp_001", "execution_state"), "ACTIVATABLE"),
        (("promotion_eligible",), True),
        (("release3_included",), True),
    ):
        hostile = deepcopy(value)
        target = hostile
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        with pytest.raises(ValidationError):
            validator.validate(hostile)


def test_proposal_binds_all_current_evidence_bytes_but_not_a_selected_commit() -> None:
    value = _asset()
    expected = {
        "structural_census_digest": proposal.CENSUS_RESOURCE,
        "prototype_measurement_digest": proposal.MEASUREMENT_RESOURCE,
        "runtime_inventory_digest": (
            "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"
        ),
        "prototype_program_digest": dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        "prototype_pack_manifest_digest": dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH,
    }
    for field, relative in expected.items():
        assert value["bindings"][field] == contract.bytes_digest((ROOT / relative).read_bytes())
    assert value["source_binding_state"] == "SAME_CHECKOUT_SELF_CHECK_ONLY"
    assert value["selected_source_commit"] is None
    assert value["selected_source_tree"] is None
    assert "SELECTED_SOURCE_COMMIT_AND_TREE_BINDING_ABSENT" in value["approval"]["blockers"]


def test_complete_runtime_proposal_variant_is_structural_but_still_non_authoritative() -> None:
    value = deepcopy(_asset())
    value["runtime_closure"].update({
        "state": review.TCB_BUDGET_REVIEW_RUNTIME_STATE,
        "complete_exact_runtime_closure": True,
        "blind_spot_count": 0,
        "claim_boundary": "Externally reviewed exact runtime closure for this selected candidate.",
    })
    value["approval"]["blockers"].remove("COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT")

    assert review.validate_tcb_budget_proposal(value) == value
    Draft202012Validator(_schema()).validate(value)
    assert value["authoritative"] is False
    assert value["approval"]["approved"] is False
    assert value["qcp_001"]["qualification_state"] == "EXPERIMENTAL"
    assert value["promotion_eligible"] is False
    assert proposal._approval_blockers(review.TCB_BUDGET_REVIEW_RUNTIME_STATE) == (
        value["approval"]["blockers"]
    )

    for field, replacement in (
        ("complete_exact_runtime_closure", False),
        ("blind_spot_count", 1),
    ):
        hostile = deepcopy(value)
        hostile["runtime_closure"][field] = replacement
        with pytest.raises(contract.TransitionContractError):
            review.validate_tcb_budget_proposal(hostile)
        with pytest.raises(ValidationError):
            Draft202012Validator(_schema()).validate(hostile)


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate_dimension",
        "reordered_dimensions",
        "wrong_boundary_error",
        "ceiling_profile_mismatch",
        "core_budget_arithmetic",
        "core_headroom_arithmetic",
        "pack_count_arithmetic",
        "pack_budget_arithmetic",
        "pack_headroom_arithmetic",
    ),
)
def test_code_validator_and_schema_reject_budget_rechain_attacks(mutation: str) -> None:
    value = deepcopy(_asset())
    if mutation == "duplicate_dimension":
        value["boundary_evidence"][1]["dimension"] = value["boundary_evidence"][0]["dimension"]
    elif mutation == "reordered_dimensions":
        value["boundary_evidence"][0], value["boundary_evidence"][1] = (
            value["boundary_evidence"][1],
            value["boundary_evidence"][0],
        )
    elif mutation == "wrong_boundary_error":
        value["boundary_evidence"][0]["n_plus_1_error"] = "INPUT_BYTE_LIMIT"
    elif mutation == "ceiling_profile_mismatch":
        value["boundary_evidence"][0]["proposed_ceiling"] += 1
    elif mutation == "core_budget_arithmetic":
        value["core_budget_proposal"]["proposed_core_sloc_budget"] += 256
    elif mutation == "core_headroom_arithmetic":
        value["core_budget_proposal"]["headroom_statements"] += 1
    elif mutation == "pack_count_arithmetic":
        value["pack_budget_proposal"]["measured_semantic_statements"] += 1
    elif mutation == "pack_budget_arithmetic":
        value["pack_budget_proposal"]["proposed_pack_sloc_budget"] *= 2
    else:
        value["pack_budget_proposal"]["headroom_basis_points"] += 1

    with pytest.raises(contract.TransitionContractError):
        review.validate_tcb_budget_proposal(value)
    if mutation in {"duplicate_dimension", "reordered_dimensions", "wrong_boundary_error"}:
        with pytest.raises(ValidationError):
            Draft202012Validator(_schema()).validate(value)
