#!/usr/bin/env python3
"""Build or verify the exact non-authoritative Atlas R2 DSL prototype assets.

The default mode is read-only and fails on any byte drift. ``--update`` is the explicit generation
mode used after reviewing interpreter/source changes. The resulting TCB remains pending independent
review: this tool measures source/rule counts and exact bytes but never selects budgets, signs review
evidence, qualifies a pack, or changes QCP-001.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coverage.parser import PythonParser  # noqa: E402

from cisco_toolkit import transition_contract as contract  # noqa: E402
from cisco_toolkit import transition_dsl as dsl  # noqa: E402
from cisco_toolkit import transition_pack as pack  # noqa: E402


ASSET_PATHS = (
    dsl.DSL_PROTOTYPE_DENOMINATOR_PATH,
    dsl.DSL_PROTOTYPE_INPUT_PATH,
    dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH,
    dsl.DSL_PROTOTYPE_PROGRAM_PATH,
    dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH,
)
CORE_SOURCE_ROSTER = (
    ("atlas.transition-contract", "STRUCTURAL_CONTRACT_AND_CANONICAL_CODEC",
     "cisco_toolkit/transition_contract.py"),
    ("atlas.transition-dsl", "DECLARATIVE_DSL_INTERPRETER",
     "cisco_toolkit/transition_dsl.py"),
    ("atlas.transition-pack", "PACK_ABI_AND_TCB_BOUNDARY",
     "cisco_toolkit/transition_pack.py"),
)


def _digest(label: str) -> str:
    return contract.bytes_digest(label.encode("ascii"))


def _binding(kind: str, value: Any) -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_BINDING_SCHEMA,
        "kind": kind,
        "digest": contract.canonical_digest(value),
        "value": value,
    }


def _expression_program() -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_PROGRAM_SCHEMA,
        "program_id": "atlas-r2-dsl-conformance",
        "program_version": dsl.DSL_PROTOTYPE_PACK_VERSION,
        "abi_version": contract.PACK_ABI_VERSION,
        "pack_id": dsl.DSL_PROTOTYPE_PACK_ID,
        "pack_version": dsl.DSL_PROTOTYPE_PACK_VERSION,
        "rules": [
            {
                "function": "manifest",
                "rule_id": "prototype.manifest",
                "when": {"op": "EXISTS", "path": ["identity", "transition_id"]},
                "emit": {"kind": "PROTOTYPE_MANIFEST", "value": "synthetic-only"},
            },
            {
                "function": "resolve_applicability",
                "rule_id": "prototype.resolve-applicability",
                "when": {
                    "op": "ALL_OF",
                    "args": [
                        {"op": "EQUALS", "path": ["facts", "typed"], "value": True},
                        {
                            "op": "MATCH_SCOPE",
                            "fact_path": ["facts", "site_id"],
                            "scope_path": ["scope", "site_id"],
                        },
                    ],
                },
                "emit": {"kind": "APPLICABILITY_SIGNAL", "value": "synthetic-match"},
            },
            {
                "function": "extract_atoms",
                "rule_id": "prototype.extract-atoms",
                "when": {"op": "EXISTS", "path": ["facts", "atom"]},
                "emit": {"kind": "TYPED_ATOM_SIGNAL", "value": "present"},
            },
            {
                "function": "compile_obligations",
                "rule_id": "prototype.compile-obligations",
                "when": {
                    "op": "ANY_OF",
                    "args": [
                        {"op": "EXISTS", "path": ["facts", "obligation"]},
                        {
                            "op": "NOT",
                            "arg": {"op": "EXISTS", "path": ["facts", "disabled"]},
                        },
                    ],
                },
                "emit": {"kind": "PROTOTYPE_OBLIGATION", "value": "compiled"},
            },
            {
                "function": "evaluate",
                "rule_id": "prototype.evaluate-functional",
                "when": {
                    "op": "ALL_OF",
                    "args": [
                        {"op": "EQUALS", "path": ["facts", "enabled"], "value": True},
                        {"op": "EXISTS", "path": ["facts", "atom"]},
                        {
                            "op": "IN_SET",
                            "path": ["facts", "role"],
                            "values": ["gateway", "router"],
                        },
                        {
                            "op": "MATCH_SCOPE",
                            "fact_path": ["facts", "site_id"],
                            "scope_path": ["scope", "site_id"],
                        },
                        {
                            "op": "NOT",
                            "arg": {"op": "EXISTS", "path": ["facts", "forbidden"]},
                        },
                        {
                            "op": "NOT_EQUALS",
                            "path": ["facts", "role"],
                            "value": "core",
                        },
                        {
                            "op": "ANY_OF",
                            "args": [
                                {
                                    "op": "EQUALS",
                                    "path": ["facts", "typed"],
                                    "value": True,
                                },
                                {"op": "EXISTS", "path": ["facts", "fallback"]},
                            ],
                        },
                    ],
                },
                "emit": {"kind": "PROTOTYPE_EVALUATION", "value": "matched"},
            },
            {
                "function": "evaluate",
                "rule_id": "prototype.evaluate-temporal",
                "when": {
                    "op": "TEMPORAL_MONITOR",
                    "profile_path": ["time", "observation_profile_digest"],
                },
                "emit": {"kind": "PROTOTYPE_TEMPORAL", "value": "not-activated"},
            },
        ],
    }


def _prototype_input() -> dict[str, Any]:
    identity = {
        "campaign_id": "synthetic-campaign",
        "transition_id": "synthetic-transition",
        "trial_attempt_id": "synthetic-trial",
    }
    scope = {"site_id": "synthetic-site", "subject_id": "synthetic-gateway"}
    time_value = {
        "observation_profile_digest": _digest("prototype-observation-profile"),
        "observed_at": "2026-08-22T00:00:00.000000Z",
        "semantic_profile_digest": _digest("prototype-semantic-profile"),
        "state_id": "synthetic-state",
    }
    return {
        "schema": dsl.DECLARATIVE_INPUT_SCHEMA,
        "request_id": "prototype-request-001",
        "identity": _binding("IDENTITY", identity),
        "scope": _binding("SCOPE", scope),
        "time": _binding("TIME", time_value),
        "facts": {
            "atom": {"kind": "typed", "value": True},
            "enabled": True,
            "obligation": True,
            "role": "gateway",
            "site_id": "synthetic-site",
            "typed": True,
        },
    }


def _denominator() -> dict[str, Any]:
    return {
        "schema": contract.QUALIFICATION_DENOMINATOR_SCHEMA,
        "denominator_id": "denominator.ATLAS-R2-DSL-CONFORMANCE.synthetic-only",
        "subject_kind": "BEHAVIOR_PACK",
        "subject_id": dsl.DSL_PROTOTYPE_PACK_ID,
        "subject_version": dsl.DSL_PROTOTYPE_PACK_VERSION,
        "denominator_kind": "PACK_SUPPORTED_SCOPE",
        "subject_ids": ["synthetic-gateway"],
        "predicate_ids": [
            "prototype.evaluate-functional",
            "prototype.evaluate-temporal",
        ],
        "window": None,
        "platform_release_ids": ["ATLAS-R2-DSL-PROTOTYPE.synthetic-only"],
        "event_inventory_digest": None,
        "model_bound_digest": None,
        "assumption_set_digest": None,
    }


def _statement_count(path: Path) -> int:
    parser = PythonParser(filename=str(path))
    parser.parse_source()
    return len(parser.statements)


def _artifact(
        artifact_id: str,
        role: str,
        relative: str,
        raw: bytes) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_version": "1.0.0",
        "path": relative,
        "role": role,
        "bytes": len(raw),
        "digest": contract.bytes_digest(raw),
    }


def _build() -> dict[str, bytes]:
    program = _expression_program()
    denominator = _denominator()
    input_value = _prototype_input()
    contract.validate_qualification_denominator(denominator, "$")
    program_raw = contract.canonical_json_bytes(program)
    denominator_raw = contract.canonical_json_bytes(denominator)
    input_raw = contract.canonical_json_bytes(input_value)

    probe = contract.parse_canonical_json_bytes(
        dsl.run_pack_abi("evaluate", program_raw, input_raw),
        require_canonical=True,
    )
    if (
            probe["outcome"] != "EXECUTED_NONAUTHORITATIVE"
            or probe["authoritative"] is not False
            or probe["promotion_eligible"] is not False
    ):
        raise RuntimeError("prototype program did not execute inside its non-authority boundary")

    source_raw: dict[str, bytes] = {
        relative: (ROOT / relative).read_bytes()
        for _, _, relative in CORE_SOURCE_ROSTER
    }
    core_sources = [
        _artifact(artifact_id, role, relative, source_raw[relative])
        for artifact_id, role, relative in CORE_SOURCE_ROSTER
    ]
    core_sources.sort(key=lambda item: (item["artifact_id"], item["path"]))
    pack_raw_by_path = {
        dsl.DSL_PROTOTYPE_DENOMINATOR_PATH: denominator_raw,
        dsl.DSL_PROTOTYPE_INPUT_PATH: input_raw,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH: program_raw,
    }
    pack_sources = [
        _artifact("atlas.prototype-denominator", "PROTOTYPE_DENOMINATOR",
                  dsl.DSL_PROTOTYPE_DENOMINATOR_PATH, denominator_raw),
        _artifact("atlas.prototype-input", "PROTOTYPE_TYPED_INPUT",
                  dsl.DSL_PROTOTYPE_INPUT_PATH, input_raw),
        _artifact("atlas.prototype-program", "DECLARATIVE_RULE_PROGRAM",
                  dsl.DSL_PROTOTYPE_PROGRAM_PATH, program_raw),
    ]
    executable = Path(sys.executable).resolve().read_bytes()
    tcb = {
        "schema": pack.TCB_MANIFEST_SCHEMA,
        "manifest_id": "atlas-r2-dsl-prototype-tcb.001",
        "substrate": pack.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        "core_sources": core_sources,
        "pack_sources": pack_sources,
        "transitive_dependencies": [],
        "runtime_inventory_state": (
            pack.TCBRuntimeInventoryState.PARTIAL_NONPORTABLE_PROTOTYPE.value
        ),
        "core_census_method": pack.TCB_CORE_CENSUS_METHOD,
        "pack_census_method": pack.TCB_PACK_CENSUS_METHOD,
        "core_executable_lines": sum(
            _statement_count(ROOT / relative)
            for _, _, relative in CORE_SOURCE_ROSTER
        ),
        "pack_executable_lines": len(program["rules"]),
        "dsl_interpreter": {
            "component_id": "atlas.transition-dsl",
            "component_version": dsl.DECLARATIVE_INTERPRETER_SEMANTICS_VERSION,
            "content_digest": contract.bytes_digest(source_raw[dsl.DSL_INTERPRETER_SOURCE_PATH]),
        },
        "wasm_runtime": None,
        "toolchains": [
            {
                "component_id": "CPython",
                "component_version": (
                    f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                ),
                "content_digest": contract.bytes_digest(executable),
            }
        ],
        "abi_version": contract.PACK_ABI_VERSION,
        "qualification_receipt_digest": None,
        "supported_denominator_digest": contract.bytes_digest(denominator_raw),
        "budget_review_receipt_digest": None,
        "budget_state": pack.TCBBudgetState.PENDING_INDEPENDENT_REVIEW.value,
        "core_sloc_budget": None,
        "pack_sloc_budget": None,
        "resource_ceilings": None,
    }
    pack.validate_tcb_manifest(tcb)
    tcb_raw = contract.canonical_json_bytes(tcb)
    manifest = {
        "schema": pack.PACK_MANIFEST_SCHEMA,
        "pack_id": dsl.DSL_PROTOTYPE_PACK_ID,
        "pack_version": dsl.DSL_PROTOTYPE_PACK_VERSION,
        "abi_version": contract.PACK_ABI_VERSION,
        "behavior_kind": "BEHAVIOR_PACK",
        "qualification_state": contract.QualificationState.EXPERIMENTAL.value,
        "qualification_receipt_digest": None,
        "execution_state": pack.PackExecutionState.CONTRACT_ONLY.value,
        "substrate": pack.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        "semantic_bundle_digest": contract.bytes_digest(program_raw),
        "declarative_rules_digest": contract.bytes_digest(program_raw),
        "declarative_operators": list(pack.DECLARATIVE_DSL_OPERATORS),
        "supported_denominator_digest": contract.bytes_digest(denominator_raw),
        "applicability_profile_ids": [
            "ATLAS-R2-DSL-CONFORMANCE.synthetic-only",
        ],
        "functions": list(pack.PACK_ABI_FUNCTIONS),
        "wasm_modules": [],
        "tcb_manifest_digest": contract.bytes_digest(tcb_raw),
        "claim_boundary": dsl.DSL_PROTOTYPE_CLAIM_BOUNDARY,
    }
    pack.validate_pack_manifest(manifest)
    manifest_raw = contract.canonical_json_bytes(manifest)
    pack.validate_pack_tcb_pair(manifest, tcb)
    all_source_raw: Mapping[str, bytes] = {**source_raw, **pack_raw_by_path}
    dsl.bind_packaged_dsl_prototype_bytes(
        manifest_raw,
        tcb_raw,
        program_raw,
        denominator_raw,
        dict(all_source_raw),
    )
    return {
        dsl.DSL_PROTOTYPE_DENOMINATOR_PATH: denominator_raw,
        dsl.DSL_PROTOTYPE_INPUT_PATH: input_raw,
        dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH: manifest_raw,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH: program_raw,
        dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH: tcb_raw,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="write reviewed generated bytes instead of performing the default read-only check",
    )
    args = parser.parse_args(argv)
    expected = _build()
    drift: list[str] = []
    for relative in ASSET_PATHS:
        path = ROOT / relative
        raw = expected[relative]
        if args.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        elif not path.is_file() or path.read_bytes() != raw:
            drift.append(relative)
    if drift:
        raise RuntimeError("Atlas R2 DSL prototype assets drifted: " + ", ".join(drift))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
