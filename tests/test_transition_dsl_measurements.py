"""Machine-check the non-authoritative Atlas R2 DSL prototype measurement artifact."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from tools import measure_transition_dsl_prototype as measurement


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / measurement.RESOURCE

TOP_KEYS = {
    "schema",
    "evidence_id",
    "claim_boundary",
    "authoritative",
    "approved_budget",
    "review_evidence",
    "qualification_effect",
    "promotion_eligible",
    "wasm_execution_state",
    "bindings",
    "measurement_denominator",
    "measurement_denominator_digest",
    "design_corrections",
    "baseline_execution",
    "boundary_measurements",
    "hostile_measurements",
    "supplemental_measurements",
    "measurement_gaps",
    "reference_environment",
    "review_state",
    "release3_included",
}
BOUNDARY_ROW_KEYS = {
    "dimension",
    "shipped_default_limit",
    "reachability",
    "injected_boundary_test_owner",
    "review_blocker",
    "boundaries",
}
BOUNDARY_KEYS = {
    "label",
    "target_dimension_value",
    "raw_program_bytes",
    "program_digest",
    "raw_input_bytes",
    "input_digest",
    "raw_receipt_bytes",
    "receipt_digest",
    "repeat_receipt_digests",
    "outcome",
    "error",
    "result_digest",
    "result_is_null",
    "returned_result_bytes",
    "measured_producer_result_bytes",
    "work_units",
    "authority",
    "dominance_evidence",
    "performance_reference",
}
AUTHORITY = {
    "authoritative": False,
    "supplies_obligation_support": False,
    "qualification_effect": "NONE",
    "authoritative_gate": None,
    "promotion_eligible": False,
    "execution_state": "CONTRACT_ONLY",
    "qualification_state": "EXPERIMENTAL",
}
SUPPLEMENTAL_KEYS = {
    "case_id",
    "targets",
    "raw_program_bytes",
    "program_digest",
    "raw_input_bytes",
    "input_digest",
    "raw_receipt_bytes",
    "receipt_digest",
    "repeat_receipt_digests",
    "outcome",
    "error",
    "result_digest",
    "result_is_null",
    "work_units",
    "authority",
    "performance_reference",
}


def _artifact() -> dict[str, Any]:
    raw = ASSET.read_bytes()
    value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
    assert raw == contract.canonical_json_bytes(value)
    return value


def test_generator_default_mode_recomputes_semantics_without_drift() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / measurement.TOOL_PATH)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_update_mode_honors_an_explicit_output_target(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    generated = b'{"schema":"fixture"}'
    monkeypatch.setattr(measurement, "_build", lambda _repository: generated)
    target = tmp_path / "nested" / "measurements.json"
    assert measurement.main(["--update", "--output", str(target)]) == 0
    assert target.read_bytes() == generated


def test_artifact_schema_and_nested_records_are_closed() -> None:
    artifact = _artifact()
    assert set(artifact) == TOP_KEYS
    assert artifact["schema"] == measurement.SCHEMA
    assert set(artifact["bindings"]) == {
        "pack_manifest",
        "tcb_manifest",
        "prototype_program",
        "prototype_input",
        "supported_denominator",
        "interpreter_source",
        "default_limit_profile",
        "measurement_tool",
        "declared_toolchains",
        "pack_abi_version",
    }
    for key in (
            "pack_manifest",
            "tcb_manifest",
            "prototype_program",
            "prototype_input",
            "supported_denominator",
            "interpreter_source",
            "measurement_tool"):
        assert set(artifact["bindings"][key]) == {"path", "raw_bytes", "digest"}
    assert set(artifact["bindings"]["default_limit_profile"]) == {"value", "digest"}
    assert set(artifact["baseline_execution"]) == {
        "raw_receipt_bytes",
        "receipt_digest",
        "repeat_receipt_digests",
        "source_binding_state",
        "inner_receipt_digest",
        "inner_outcome",
        "inner_result_digest",
        "inner_work_units",
        "authority",
    }
    for row in artifact["boundary_measurements"]:
        assert set(row) == BOUNDARY_ROW_KEYS
        for boundary in row["boundaries"]:
            assert set(boundary) == BOUNDARY_KEYS
            assert set(boundary["authority"]) == set(AUTHORITY)
            assert all(
                set(observation) == {"elapsed_ns", "tracemalloc_peak_bytes"}
                for observation in boundary["performance_reference"]
            )
    for row in artifact["supplemental_measurements"]:
        assert set(row) == SUPPLEMENTAL_KEYS
        assert set(row["authority"]) == set(AUTHORITY)


def test_baseline_binds_the_exact_direct_inner_receipt() -> None:
    artifact = _artifact()
    program_raw = (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes()
    input_raw = (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes()
    direct_receipt = dsl.run_pack_abi("evaluate", program_raw, input_raw)

    assert artifact["baseline_execution"]["inner_receipt_digest"] == (
        contract.bytes_digest(direct_receipt)
    )


def test_exact_assets_interpreter_limits_tool_and_denominator_are_digest_bound() -> None:
    artifact = _artifact()
    bindings = artifact["bindings"]
    for key in (
            "pack_manifest",
            "tcb_manifest",
            "prototype_program",
            "prototype_input",
            "supported_denominator",
            "interpreter_source",
            "measurement_tool"):
        binding = bindings[key]
        raw = (ROOT / binding["path"]).read_bytes()
        assert binding["raw_bytes"] == len(raw)
        assert binding["digest"] == contract.bytes_digest(raw)
    profile = {
        field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
        for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
    }
    assert bindings["default_limit_profile"] == {
        "value": profile,
        "digest": contract.canonical_digest(profile),
    }
    assert artifact["measurement_denominator_digest"] == contract.canonical_digest(
        artifact["measurement_denominator"]
    )
    tcb = contract.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH).read_bytes(),
        require_canonical=True,
    )
    assert bindings["declared_toolchains"] == tcb["toolchains"]
    assert (
        bindings["interpreter_source"]["digest"]
        == tcb["dsl_interpreter"]["content_digest"]
    )


def test_all_twelve_default_dimensions_have_actual_n_minus_1_n_n_plus_1_evidence() -> None:
    artifact = _artifact()
    rows = artifact["boundary_measurements"]
    assert [row["dimension"] for row in rows] == list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
    assert len(rows) == 12
    for row in rows:
        dimension = row["dimension"]
        limit = getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, dimension)
        assert row["shipped_default_limit"] == limit
        assert row["injected_boundary_test_owner"] == measurement.TEST_OWNERS[dimension]
        assert [item["label"] for item in row["boundaries"]] == list(
            measurement.BOUNDARY_LABELS
        )
        assert [item["target_dimension_value"] for item in row["boundaries"]] == [
            limit - 1,
            limit,
            limit + 1,
        ]
        for boundary in row["boundaries"]:
            assert boundary["repeat_receipt_digests"] == [
                boundary["receipt_digest"],
                boundary["receipt_digest"],
            ]
            assert boundary["authority"] == AUTHORITY
            assert len(boundary["performance_reference"]) == measurement.PERFORMANCE_REPEATS
            assert all(
                observation["elapsed_ns"] > 0
                and observation["tracemalloc_peak_bytes"] >= 0
                for observation in boundary["performance_reference"]
            )


def test_all_twelve_dimensions_reach_default_boundaries_and_n_plus_1_fails_closed() -> None:
    artifact = _artifact()
    expected_errors = {
        "max_program_bytes": "PROGRAM_BYTE_LIMIT",
        "max_input_bytes": "INPUT_BYTE_LIMIT",
        "max_output_bytes": "OUTPUT_BYTE_LIMIT",
        "max_rules": "RULE_LIMIT",
        "max_expression_depth": "EXPRESSION_DEPTH_LIMIT",
        "max_expression_nodes": "EXPRESSION_NODE_LIMIT",
        "max_operator_operands": "OPERATOR_OPERAND_LIMIT",
        "max_path_segments": "PATH_SEGMENT_LIMIT",
        "max_string_bytes": "STRING_BYTE_LIMIT",
        "max_set_items": "SET_ITEM_LIMIT",
        "max_input_nodes": "INPUT_NODE_LIMIT",
        "max_instruction_fuel": "INSTRUCTION_FUEL_LIMIT",
    }
    rows = {
        row["dimension"]: row
        for row in artifact["boundary_measurements"]
    }
    assert set(rows) == set(expected_errors)
    for dimension, row in rows.items():
        assert row["reachability"] == "REACHABLE_AT_SHIPPED_DEFAULT"
        assert row["review_blocker"] is None
        n_minus_1, n, n_plus_1 = row["boundaries"]
        for success in (n_minus_1, n):
            assert success["outcome"] == "EXECUTED_NONAUTHORITATIVE"
            assert success["error"] is None
            assert success["result_is_null"] is False
            assert success["returned_result_bytes"] > 0
        assert n_plus_1["outcome"] == "REFUSED_NONAUTHORITATIVE"
        assert n_plus_1["error"] == {"code": expected_errors[dimension]}
        assert n_plus_1["result_is_null"] is True
        assert n_plus_1["result_digest"] is None
        assert n_plus_1["returned_result_bytes"] == 0
        assert n_plus_1["authority"] == AUTHORITY


def test_corrected_output_default_reaches_its_real_boundary_without_partial_result() -> None:
    artifact = _artifact()
    row = next(
        item for item in artifact["boundary_measurements"]
        if item["dimension"] == "max_output_bytes"
    )
    assert row["reachability"] == "REACHABLE_AT_SHIPPED_DEFAULT"
    assert row["review_blocker"] is None
    assert artifact["design_corrections"] == [{
        "dimension": "max_output_bytes",
        "prior_provisional_value": 262_144,
        "corrected_provisional_value": 131_072,
        "prior_n_minus_1_n_n_plus_1_output_targets": [262_143, 262_144, 262_145],
        "prior_required_program_bytes": [262_297, 262_298, 262_299],
        "dominating_guard": "max_program_bytes",
        "dominating_guard_value": 262_144,
        "correction_reason": (
            "The prior output ceiling was unreachable because its smallest boundary program "
            "exceeded max_program_bytes; the corrected provisional value restores actual "
            "shipped-profile N-1/N/N+1 execution."
        ),
        "authority_effect": "NONE_PENDING_INDEPENDENT_REVIEW",
    }]
    limit = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_output_bytes
    minus, at_limit, plus = row["boundaries"]
    for success, target in ((minus, limit - 1), (at_limit, limit)):
        assert success["raw_program_bytes"] < dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_program_bytes
        assert success["outcome"] == "EXECUTED_NONAUTHORITATIVE"
        assert success["error"] is None
        assert success["measured_producer_result_bytes"] == target
        assert success["returned_result_bytes"] == target
        assert success["dominance_evidence"] is None
    assert plus["raw_program_bytes"] < dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_program_bytes
    assert plus["outcome"] == "REFUSED_NONAUTHORITATIVE"
    assert plus["error"] == {"code": "OUTPUT_BYTE_LIMIT"}
    assert plus["measured_producer_result_bytes"] == limit + 1
    assert plus["result_is_null"] is True
    assert plus["result_digest"] is None
    assert plus["returned_result_bytes"] == 0
    assert plus["dominance_evidence"] is None


def test_hostile_canonical_cases_have_fixed_non_echoing_zero_result_refusals() -> None:
    artifact = _artifact()
    expected = {
        "DUPLICATE_KEY": "PROGRAM_CANONICAL_INVALID",
        "FLOAT_LITERAL": "PROGRAM_CANONICAL_INVALID",
        "HOSTILE_KEY_CANARY": "PROGRAM_SCHEMA_INVALID",
        "HOSTILE_PATH_CANARY": "PATH_ROOT_INVALID",
        "INVALID_UTF8_PROGRAM": "PROGRAM_CANONICAL_INVALID",
        "INVALID_UTF8_INPUT": "INPUT_CANONICAL_INVALID",
        "DUPLICATE_INPUT_KEY": "INPUT_CANONICAL_INVALID",
        "NON_NFC_INPUT_STRING": "INPUT_CANONICAL_INVALID",
    }
    assert {row["case_id"] for row in artifact["hostile_measurements"]} == set(expected)
    for row in artifact["hostile_measurements"]:
        assert row["outcome"] == "REFUSED_NONAUTHORITATIVE"
        assert row["error"] == {"code": expected[row["case_id"]]}
        assert row["result_is_null"] is True
        assert row["result_digest"] is None
        assert row["returned_result_bytes"] == 0
        assert row["canary_echoed_in_receipt"] is False
        assert row["parser_path_echoed_in_receipt"] is False
        assert row["authority"] == AUTHORITY
        assert row["repeat_receipt_digests"] == [
            row["receipt_digest"],
            row["receipt_digest"],
        ]
        assert len(row["performance_reference"]) == measurement.PERFORMANCE_REPEATS


def test_supplemental_full_path_and_combined_hostile_pressure_is_measured_honestly() -> None:
    artifact = _artifact()
    rows = {row["case_id"]: row for row in artifact["supplemental_measurements"]}
    assert set(rows) == {
        "FULL_EXISTING_PATH_N_MINUS_1",
        "FULL_EXISTING_PATH_N",
        "FULL_EXISTING_PATH_N_PLUS_1",
        "COMBINED_EXPRESSION_DEPTH_AND_NODES_AT_N",
        "COMBINED_FUEL_AND_SET_SCAN_AT_N",
    }
    for case_id in ("FULL_EXISTING_PATH_N_MINUS_1", "FULL_EXISTING_PATH_N"):
        row = rows[case_id]
        assert row["outcome"] == "EXECUTED_NONAUTHORITATIVE"
        assert row["error"] is None
        assert row["result_is_null"] is False
        assert row["authority"] == AUTHORITY
    refused = rows["FULL_EXISTING_PATH_N_PLUS_1"]
    assert refused["outcome"] == "REFUSED_NONAUTHORITATIVE"
    assert refused["error"] == {"code": "PATH_SEGMENT_LIMIT"}
    assert refused["result_is_null"] is True

    combined = rows["COMBINED_EXPRESSION_DEPTH_AND_NODES_AT_N"]
    assert combined["targets"] == {
        "expression_depth": dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_expression_depth,
        "expression_nodes": dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_expression_nodes,
    }
    assert combined["work_units"]["expression_nodes"] == (
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_expression_nodes
    )
    assert combined["outcome"] == "EXECUTED_NONAUTHORITATIVE"

    fuel = rows["COMBINED_FUEL_AND_SET_SCAN_AT_N"]
    assert fuel["work_units"]["fuel_consumed"] == (
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_instruction_fuel
    )
    assert fuel["outcome"] == "EXECUTED_NONAUTHORITATIVE"
    assert artifact["measurement_gaps"] == sorted(set(artifact["measurement_gaps"]))
    assert "MAX_RECEIPT_CONTAINER_CEILING_NOT_DEFINED" not in artifact["measurement_gaps"]
    assert (
        "UNINSTRUMENTED_DEPTH_OPERAND_PATH_STRING_AND_SET_TARGETS_ARE_"
        "SIGNED_AGGREGATE_CLAIMS_ONLY"
    ) in artifact["measurement_gaps"]
    assert "REPRESENTATIVE_FIELD_WORKLOAD_DENOMINATOR_ABSENT" in artifact[
        "measurement_gaps"
    ]


def test_measurements_cannot_approve_budgets_review_qualification_or_release3() -> None:
    artifact = _artifact()
    assert artifact["authoritative"] is False
    assert artifact["approved_budget"] is None
    assert artifact["review_evidence"] is None
    assert artifact["qualification_effect"] == "NONE"
    assert artifact["promotion_eligible"] is False
    assert artifact["wasm_execution_state"] == "UNIMPLEMENTED_UNREVIEWED"
    assert artifact["release3_included"] is False
    assert artifact["review_state"] == {
        "state": "PENDING_INDEPENDENT_NUMERIC_REVIEW_AND_SIGNED_EVIDENCE",
        "blockers": [
            "APPROVED_BUDGET_ABSENT",
            "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
            "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
            "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT",
        ],
        "resource_ceiling_effect": "NONE",
        "qualification_effect": "NONE",
        "promotion_effect": "NONE",
    }
    encoded = json.dumps(artifact, sort_keys=True)
    assert '"approved_budget": null' in encoded
    assert '"review_evidence": null' in encoded
