#!/usr/bin/env python3
"""Build or verify the non-authoritative Atlas R2 TCB budget proposal.

The proposal applies deterministic formulas to the final same-checkout census and executable
prototype measurements.  It supplies numbers for independent review; it cannot approve them,
freeze a TCB, qualify QCP-001, or include Release 3.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cisco_toolkit import transition_contract as contract  # noqa: E402
from cisco_toolkit import transition_dsl as dsl  # noqa: E402
from cisco_toolkit import transition_pack as pack  # noqa: E402
from cisco_toolkit import transition_runtime_inventory as runtime_inventory  # noqa: E402
from cisco_toolkit import transition_tcb_review as review  # noqa: E402


SCHEMA = "atlas.r2-tcb-budget-proposal/1"
RESOURCE = "cisco_toolkit/data/atlas-r2-tcb-budget-proposal.v1.json"
CENSUS_RESOURCE = "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json"
MEASUREMENT_RESOURCE = "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json"
PROPOSAL_ID = "atlas-r2-tcb-budget-proposal.001"
CORE_HEADROOM_NUMERATOR = 110
CORE_HEADROOM_DENOMINATOR = 100
CORE_BUDGET_QUANTUM = 256


def _read_canonical(repository: Path, relative: str) -> tuple[bytes, dict[str, Any]]:
    raw = (repository / relative).read_bytes()
    value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
    if type(value) is not dict:
        raise RuntimeError(f"{relative} is not a canonical object")
    return raw, value


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _core_budget(statements: int) -> int:
    minimum = _ceil_div(
        statements * CORE_HEADROOM_NUMERATOR,
        CORE_HEADROOM_DENOMINATOR,
    )
    return _ceil_div(minimum, CORE_BUDGET_QUANTUM) * CORE_BUDGET_QUANTUM


def _next_power_of_two(value: int) -> int:
    if value < 1:
        raise RuntimeError("pack statement count must be positive")
    return 1 << (value - 1).bit_length()


def _approval_blockers(runtime_closure_state: str) -> list[str]:
    blockers = [
        "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
        "EXTERNAL_INDEPENDENT_NUMERIC_APPROVAL_ABSENT",
        "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT",
        "SELECTED_SOURCE_COMMIT_AND_TREE_BINDING_ABSENT",
        "SIGNED_REVIEW_RECEIPT_AND_TRUST_POLICY_ABSENT",
    ]
    if runtime_closure_state == runtime_inventory.RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE:
        blockers.remove("COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT")
    return blockers


def _build(repository: Path) -> bytes:
    census_raw, census = _read_canonical(repository, CENSUS_RESOURCE)
    measurement_raw, measurements = _read_canonical(repository, MEASUREMENT_RESOURCE)
    runtime_raw, runtime_value = _read_canonical(
        repository,
        runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH,
    )
    program_raw, program = _read_canonical(repository, dsl.DSL_PROTOTYPE_PROGRAM_PATH)
    pack_raw, pack_manifest = _read_canonical(
        repository,
        dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH,
    )
    runtime_inventory.validate_runtime_inventory(runtime_value)
    if census.get("schema") != "atlas.structural-tcb-census/1":
        raise RuntimeError("unsupported structural census")
    if measurements.get("schema") != "atlas.dsl-prototype-measurements/1":
        raise RuntimeError("unsupported prototype measurement evidence")
    if program.get("schema") != dsl.DECLARATIVE_PROGRAM_SCHEMA:
        raise RuntimeError("unsupported prototype program")
    if pack_manifest.get("schema") != pack.PACK_MANIFEST_SCHEMA:
        raise RuntimeError("unsupported prototype pack manifest")

    core_statements = census["structural_core"]["executable_statements"]
    rules = len(program["rules"])
    pack_statements = dsl.declarative_program_semantic_statements(program)
    expression_nodes = pack_statements - rules
    if pack_statements != rules + expression_nodes:
        raise RuntimeError("semantic pack census method drifted")
    core_budget = _core_budget(core_statements)
    pack_budget = _next_power_of_two(pack_statements)

    measurement_rows = measurements.get("boundary_measurements")
    if type(measurement_rows) is not list or [
            row.get("dimension") for row in measurement_rows
    ] != list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS):
        raise RuntimeError("prototype boundary measurement set drifted")
    boundary_evidence: list[dict[str, Any]] = []
    for row in measurement_rows:
        boundaries = row.get("boundaries")
        if (
                type(boundaries) is not list
                or len(boundaries) != 3
                or [item.get("label") for item in boundaries] != [
                    "N_MINUS_1", "N", "N_PLUS_1"]
                or any(item.get("outcome") != "EXECUTED_NONAUTHORITATIVE"
                       for item in boundaries[:2])
                or boundaries[2].get("outcome") != "REFUSED_NONAUTHORITATIVE"
                or boundaries[2].get("result_is_null") is not True
                or row.get("reachability") != "REACHABLE_AT_SHIPPED_DEFAULT"
        ):
            raise RuntimeError("prototype boundary evidence is not reviewable")
        boundary_evidence.append({
            "dimension": row["dimension"],
            "proposed_ceiling": row["shipped_default_limit"],
            "derivation": (
                "RETAIN_SHIPPED_VALUE_WITH_EXECUTED_N_MINUS_1_AND_N_"
                "AND_FIXED_FAIL_CLOSED_N_PLUS_1/1"
            ),
            "measurement_row_digest": contract.canonical_digest(row),
            "n_minus_1_outcome": boundaries[0]["outcome"],
            "n_outcome": boundaries[1]["outcome"],
            "n_plus_1_outcome": boundaries[2]["outcome"],
            "n_plus_1_error": boundaries[2]["error"]["code"],
        })
    profile = {
        "schema": "atlas.dsl-only-resource-profile/1",
        "substrate": "DECLARATIVE_DSL_ONLY",
        **{
            field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
            for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
        },
    }
    closure = runtime_value["closure"]
    proposal = {
        "schema": SCHEMA,
        "proposal_id": PROPOSAL_ID,
        "source_binding_state": "SAME_CHECKOUT_SELF_CHECK_ONLY",
        "selected_source_commit": None,
        "selected_source_tree": None,
        "bindings": {
            "structural_census_digest": contract.bytes_digest(census_raw),
            "prototype_measurement_digest": contract.bytes_digest(measurement_raw),
            "runtime_inventory_digest": contract.bytes_digest(runtime_raw),
            "prototype_program_digest": contract.bytes_digest(program_raw),
            "prototype_pack_manifest_digest": contract.bytes_digest(pack_raw),
        },
        "core_budget_proposal": {
            "census_method": census["census_method"]["schema"],
            "measured_executable_statements": core_statements,
            "formula": "CEIL_TO_MULTIPLE(CEIL(MEASURED*110/100),256)/1",
            "headroom_ratio_numerator": CORE_HEADROOM_NUMERATOR,
            "headroom_ratio_denominator": CORE_HEADROOM_DENOMINATOR,
            "rounding_quantum": CORE_BUDGET_QUANTUM,
            "proposed_core_sloc_budget": core_budget,
            "headroom_statements": core_budget - core_statements,
            "headroom_basis_points": (
                (core_budget - core_statements) * 10_000 // core_statements
            ),
        },
        "pack_budget_proposal": {
            "census_method": pack.TCB_PACK_CENSUS_METHOD,
            "declarative_rule_records": rules,
            "expression_operator_nodes": expression_nodes,
            "measured_semantic_statements": pack_statements,
            "formula": "NEXT_POWER_OF_TWO(MEASURED_SEMANTIC_STATEMENTS)/1",
            "proposed_pack_sloc_budget": pack_budget,
            "headroom_semantic_statements": pack_budget - pack_statements,
            "headroom_basis_points": (
                (pack_budget - pack_statements) * 10_000 // pack_statements
            ),
        },
        "dsl_resource_profile_proposal": profile,
        "receipt_container_ceiling_proposal": dsl.dsl_receipt_container_ceiling(profile),
        "boundary_evidence": boundary_evidence,
        "measurement_gaps": measurements["measurement_gaps"],
        "runtime_closure": {
            "state": closure["state"],
            "complete_exact_runtime_closure": closure["complete_exact_runtime_closure"],
            "blind_spot_count": len(closure["blind_spots"]),
            "claim_boundary": closure["claim_boundary"],
        },
        "approval": {
            "state": "NON_AUTHORITATIVE_PROPOSAL_PENDING_EXTERNAL_DECISION",
            "approved": False,
            "review_receipt_digest": None,
            "blockers": _approval_blockers(closure["state"]),
        },
        "qcp_001": {
            "pack_id": "QCP-001",
            "pack_version": "0.1.0-experimental",
            "qualification_state": "EXPERIMENTAL",
            "execution_state": "CONTRACT_ONLY",
            "qualification_effect": "NONE",
            "promotion_eligible": False,
        },
        "freeze_overlay_schema": "atlas.r2-tcb-budget-freeze/1",
        "authoritative": False,
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "release3_included": False,
    }
    review.validate_tcb_budget_proposal(proposal)
    return contract.canonical_json_bytes(proposal)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="write the packaged proposal asset")
    parser.add_argument("--output", type=Path, help="explicit update output (requires --update)")
    args = parser.parse_args(argv)
    if args.output is not None and not args.update:
        parser.error("--output requires --update")
    target = args.output or ROOT / RESOURCE
    if not target.is_absolute():
        target = Path.cwd() / target
    generated = _build(ROOT)
    if args.update:
        target.parent.resolve(strict=True)
        target.write_bytes(generated)
        return 0
    if not target.is_file() or target.read_bytes() != generated:
        raise RuntimeError("Atlas R2 TCB budget proposal drifted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
