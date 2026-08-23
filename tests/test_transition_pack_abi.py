"""Adversarial R2.0 tests for the closed Pack ABI and qualification boundary."""

from __future__ import annotations

import base64
from copy import deepcopy
import json
from importlib import resources
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_runtime_inventory as runtime_inventory
from cisco_toolkit import transition_tcb_review as tcb_review
from tools import build_transition_dsl_prototype_assets as prototype_assets
from tools import census_transition_tcb as tcb_census


_SIGNATURE_DOMAIN = b"ATLAS-TRANSITION-QUALIFICATION\x00v1\x00"


def test_workload_review_is_structural_tcb_authority_not_runtime_inventory_v1() -> None:
    relative = "cisco_toolkit/transition_workload_review.py"
    role = "REPRESENTATIVE_WORKLOAD_REVIEW_AUTHORITY_BOUNDARY"

    assert dict(tcb_census.CORE_SOURCES)[relative] == role
    assert {
        path: source_role
        for _artifact_id, source_role, path in prototype_assets.CORE_SOURCE_ROSTER
    }[relative] == role
    assert dict(tp._STRUCTURAL_TCB_CORE_SOURCE_ROLES)[relative] == role

    module_name = "cisco_toolkit.transition_workload_review"
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS
    assert module_name not in runtime_inventory._STRUCTURAL_CORE_VALIDATOR_MODULES


def test_runtime_closure_is_structural_tcb_authority_not_runtime_inventory_v1() -> None:
    relative = "cisco_toolkit/transition_runtime_closure.py"
    role = "RUNTIME_CLOSURE_REVIEW_AUTHORITY_BOUNDARY"

    assert dict(tcb_census.CORE_SOURCES)[relative] == role
    assert {
        path: source_role
        for _artifact_id, source_role, path in prototype_assets.CORE_SOURCE_ROSTER
    }[relative] == role
    assert dict(tp._STRUCTURAL_TCB_CORE_SOURCE_ROLES)[relative] == role
    assert relative in tcb_review._STRUCTURAL_CORE_SOURCE_PATH_ROSTER
    assert tcb_review._STRUCTURAL_CORE_SOURCE_PATH_ROSTER == tuple(
        sorted(tcb_review._STRUCTURAL_CORE_SOURCE_PATH_ROSTER)
    )

    module_name = "cisco_toolkit.transition_runtime_closure"
    assert module_name not in {
        module for module, _path in tcb_review._STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER
    }
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS
    assert module_name not in runtime_inventory._STRUCTURAL_CORE_VALIDATOR_MODULES


def test_runtime_discovery_is_not_structural_or_dsl_tcb_authority() -> None:
    relative = "cisco_toolkit/transition_runtime_discovery.py"
    module_name = "cisco_toolkit.transition_runtime_discovery"

    assert relative not in dict(tcb_census.CORE_SOURCES)
    assert relative not in {
        path for _artifact_id, _source_role, path in prototype_assets.CORE_SOURCE_ROSTER
    }
    assert relative not in dict(tp._STRUCTURAL_TCB_CORE_SOURCE_ROLES)
    assert relative not in tcb_review._STRUCTURAL_CORE_SOURCE_PATH_ROSTER
    assert module_name not in {
        module for module, _path in tcb_review._STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER
    }
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES
    assert module_name not in runtime_inventory._REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS
    assert module_name not in runtime_inventory._STRUCTURAL_CORE_VALIDATOR_MODULES


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


def _dsl_resource_profile() -> dict[str, int]:
    return {
        "max_program_bytes": 65_536,
        "max_input_bytes": 65_536,
        "max_output_bytes": 65_536,
        "max_rules": 32,
        "max_expression_depth": 16,
        "max_expression_nodes": 256,
        "max_operator_operands": 32,
        "max_path_segments": 16,
        "max_string_bytes": 4_096,
        "max_set_items": 64,
        "max_input_nodes": 512,
        "max_instruction_fuel": 4_096,
    }


def _resource_ceilings(*, wasm: bool = False) -> dict[str, Any]:
    wasm_profile = None
    if wasm:
        wasm_profile = {
            "max_module_bytes": 1_000_000,
            "max_input_bytes": 1_000_000,
            "max_output_bytes": 1_000_000,
            "max_memory_pages": 64,
            "max_table_elements": 128,
            "max_call_depth": 32,
            "max_instruction_fuel": 10_000_000,
            "max_host_deadline_ms": 5_000,
        }
    return {"dsl": _dsl_resource_profile(), "wasm": wasm_profile}


def _component(label: str) -> dict[str, str]:
    return {
        "component_id": f"component.{label}",
        "component_version": "1.0.0",
        "content_digest": _digest(label),
    }


def _artifact(
        label: str,
        path: str,
        role: str,
        *,
        digest: str | None = None,
        artifact_id: str | None = None) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id or f"artifact.{label}",
        "artifact_version": "1.0.0",
        "path": path,
        "role": role,
        "bytes": 100,
        "digest": digest or _digest(label),
    }


def _tcb_manifest(
        *,
        frozen: bool = False,
        qualification_receipt_digest: str | None = None,
        denominator_digest: str | None = None,
        wasm_runtime_digest: str | None = None,
        wasm_modules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    interpreter = _component("dsl-interpreter")
    wasm = wasm_runtime_digest is not None
    denominator = denominator_digest or _digest("supported denominator")
    program_digest = _digest("fixture declarative program")
    if wasm:
        wasm_runtime = {
            "component_id": "component.wasm-runtime",
            "component_version": "1.0.0",
            "content_digest": wasm_runtime_digest,
        }
    else:
        wasm_runtime = None
    module_source_roles = {
        "PARSER": tp.WASM_PARSER_MODULE_SOURCE_ROLE,
        "NORMALIZER": tp.WASM_NORMALIZER_MODULE_SOURCE_ROLE,
    }
    pack_sources = [
        _artifact(
            "declarative-program",
            "cisco_toolkit/data/fixture-program.json",
            tp.DECLARATIVE_PROGRAM_SOURCE_ROLE,
            digest=program_digest,
        ),
        _artifact(
            "supported-denominator",
            "cisco_toolkit/data/fixture-denominator.json",
            tp.SUPPORTED_DENOMINATOR_SOURCE_ROLE,
            digest=denominator,
        ),
    ]
    for module in wasm_modules or []:
        pack_sources.append(_artifact(
            module["module_id"],
            f"cisco_toolkit/data/{module['module_id']}.wasm",
            module_source_roles[module["role"]],
            digest=module["digest"],
            artifact_id=module["module_id"],
        ))
    pack_sources.sort(key=lambda item: (item["artifact_id"], item["path"]))
    return {
        "schema": tp.TCB_MANIFEST_SCHEMA,
        "manifest_id": "tcb.fixture.001",
        "substrate": (
            tp.PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value
            if wasm
            else tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value
        ),
        "core_sources": [
            _artifact(
                "dsl-interpreter",
                "cisco_toolkit/transition_dsl.py",
                "DSL_INTERPRETER",
                digest=interpreter["content_digest"],
            ),
        ],
        "pack_sources": pack_sources,
        "transitive_dependencies": [_component("runtime-dependency")] if frozen else [],
        "runtime_inventory_state": (
            tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
        ),
        "core_census_method": tp.TCB_CORE_CENSUS_METHOD,
        "pack_census_method": tp.TCB_PACK_CENSUS_METHOD,
        "core_executable_lines": 100,
        "pack_executable_lines": 20,
        "dsl_interpreter": interpreter,
        "wasm_runtime": wasm_runtime,
        "toolchains": [_component("python-toolchain")],
        "abi_version": tc.PACK_ABI_VERSION,
        "qualification_receipt_digest": qualification_receipt_digest,
        "supported_denominator_digest": denominator,
        "budget_review_receipt_digest": _digest("budget review") if frozen else None,
        "budget_state": (
            tp.TCBBudgetState.FROZEN.value
            if frozen
            else tp.TCBBudgetState.PENDING_INDEPENDENT_REVIEW.value
        ),
        "core_sloc_budget": 120 if frozen else None,
        "pack_sloc_budget": 30 if frozen else None,
        "resource_ceilings": _resource_ceilings(wasm=wasm) if frozen else None,
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
    program_sources = [
        source
        for source in checked_tcb.get("pack_sources", [])
        if source.get("role") == tp.DECLARATIVE_PROGRAM_SOURCE_ROLE
    ]
    program_digest = (
        program_sources[0]["digest"]
        if len(program_sources) == 1
        else _digest(f"{pack_id} semantic bundle")
    )
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
        "semantic_bundle_digest": program_digest,
        "declarative_rules_digest": program_digest,
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


@pytest.mark.parametrize(
    ("alias", "expected"),
    (
        ("pack_artifact_id", "DUPLICATE_TCB_ARTIFACT_ID"),
        ("pack_path", "DUPLICATE_TCB_ARTIFACT_PATH"),
        ("pack_path_case_alias", "DUPLICATE_TCB_ARTIFACT_PATH"),
        ("core_pack_artifact_id", "DUPLICATE_TCB_ARTIFACT_ID"),
        ("core_pack_path", "DUPLICATE_TCB_ARTIFACT_PATH"),
    ),
)
def test_tcb_source_roster_rejects_individually_aliased_ids_and_paths(
        alias: str,
        expected: str) -> None:
    tcb = _tcb_manifest()
    program, denominator = tcb["pack_sources"]
    if alias == "pack_artifact_id":
        denominator["artifact_id"] = program["artifact_id"]
    elif alias == "pack_path":
        denominator["path"] = program["path"]
    elif alias == "pack_path_case_alias":
        denominator["path"] = program["path"].upper()
    elif alias == "core_pack_artifact_id":
        denominator["artifact_id"] = tcb["core_sources"][0]["artifact_id"]
    else:
        denominator["path"] = tcb["core_sources"][0]["path"]
    tcb["pack_sources"].sort(key=lambda item: (item["artifact_id"], item["path"]))

    _assert_transition_refusal(lambda: tp.validate_tcb_manifest(tcb), expected)


@pytest.mark.parametrize(
    "path",
    (
        "cisco_toolkit/data/trailing-dot./fixture.json",
        "cisco_toolkit/data/trailing-space /fixture.json",
        "cisco_toolkit/data/NUL.json",
        "cisco_toolkit/data/control-\u0001.json",
        "cisco_toolkit/data/wildcard*.json",
    ),
)
def test_tcb_source_paths_are_portable_across_supported_filesystems(path: str) -> None:
    tcb = _tcb_manifest()
    tcb["pack_sources"][0]["path"] = path
    tcb["pack_sources"].sort(key=lambda item: (item["artifact_id"], item["path"]))

    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(tcb),
        "TCB_ARTIFACT_PATH_NOT_PORTABLE",
    )


def test_tcb_component_identity_cannot_alias_multiple_digests() -> None:
    tcb = _tcb_manifest()
    first = _component("runtime-dependency")
    second = deepcopy(first)
    second["content_digest"] = _digest("substituted runtime dependency")
    tcb["transitive_dependencies"] = sorted(
        [first, second],
        key=lambda item: (
            item["component_id"], item["component_version"], item["content_digest"]
        ),
    )

    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(tcb),
        "DUPLICATE_TCB_COMPONENT_ID_VERSION",
    )


def test_frozen_tcb_requires_complete_ceilings_and_enforces_sloc_budgets() -> None:
    frozen = _tcb_manifest(frozen=True)
    assert tp.validate_tcb_manifest(frozen) == frozen

    missing_ceiling = deepcopy(frozen)
    missing_ceiling["resource_ceilings"]["dsl"].pop("max_instruction_fuel")
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

    partial_runtime = deepcopy(frozen)
    partial_runtime["runtime_inventory_state"] = (
        tp.TCBRuntimeInventoryState.PARTIAL_NONPORTABLE_PROTOTYPE.value
    )
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(partial_runtime),
        "FROZEN_TCB_REQUIRES_COMPLETE_RUNTIME_INVENTORY",
    )

    legacy_count = deepcopy(frozen)
    legacy_count["pack_census_method"] = tp.LEGACY_TCB_PACK_CENSUS_METHOD
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(legacy_count),
        "FROZEN_TCB_REQUIRES_CURRENT_PACK_CENSUS_METHOD",
    )
    schema = json.loads(
        resources.files("cisco_toolkit").joinpath(
            "schemas",
            "atlas-transition-contract-v1.schema.json",
        ).read_bytes()
    )
    validator = Draft202012Validator({
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/tcbManifestV2",
    })
    with pytest.raises(ValidationError):
        validator.validate(legacy_count)


def test_frozen_complete_runtime_closure_requires_nonempty_dependency_roster() -> None:
    frozen = _tcb_manifest(frozen=True)
    frozen["transitive_dependencies"] = []

    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(frozen),
        "FROZEN_TCB_REQUIRES_RUNTIME_DEPENDENCIES",
    )


def test_legacy_rule_count_census_is_pending_read_compatible_only() -> None:
    pending = _tcb_manifest()
    pending["pack_census_method"] = tp.LEGACY_TCB_PACK_CENSUS_METHOD
    assert tp.validate_tcb_manifest(pending) == pending


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
    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(frozen_pack, frozen),
        "ACTIVATABLE_PACK_REQUIRES_VERIFIED_TCB_BUDGET_REVIEW",
    )

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


def test_tcb_v1_is_readable_pending_only_and_never_activatable() -> None:
    legacy = {
        "schema": tp.LEGACY_TCB_MANIFEST_SCHEMA,
        "manifest_id": "tcb.legacy.fixture.001",
        "core_source_digests": [_digest("legacy structural core")],
        "pack_source_digests": [_digest("legacy pack source")],
        "transitive_dependency_digests": [],
        "core_executable_lines": 100,
        "pack_executable_lines": 20,
        "dsl_interpreter_digest": _digest("legacy interpreter"),
        "wasm_runtime_digest": None,
        "toolchain_digests": [_digest("legacy toolchain")],
        "abi_version": tc.PACK_ABI_VERSION,
        "qualification_receipt_digest": None,
        "supported_denominator_digest": _digest("legacy denominator"),
        "budget_state": (
            tp.TCBBudgetState.PENDING_PROTOTYPE_CENSUS_AND_INDEPENDENT_REVIEW.value
        ),
        "core_sloc_budget": None,
        "pack_sloc_budget": None,
        "resource_ceilings": None,
    }
    assert tp.validate_tcb_manifest(legacy) == legacy

    frozen = deepcopy(legacy)
    frozen["budget_state"] = tp.TCBBudgetState.FROZEN.value
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(frozen),
        "LEGACY_TCB_MANIFEST_CANNOT_FREEZE",
    )


def test_tcb_v2_requires_named_versioned_sources_and_substrate_specific_limits() -> None:
    pending = _tcb_manifest()
    anonymous = deepcopy(pending)
    anonymous["core_sources"][0].pop("artifact_version")
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(anonymous),
        "CLOSED_SCHEMA_KEYS",
    )

    wrong_interpreter = deepcopy(pending)
    wrong_interpreter["dsl_interpreter"]["content_digest"] = _digest("substituted")
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(wrong_interpreter),
        "DSL_INTERPRETER_SOURCE_NOT_IN_TCB_CORE",
    )

    frozen = _tcb_manifest(frozen=True)
    frozen["resource_ceilings"]["wasm"] = {
        "max_module_bytes": 1,
        "max_input_bytes": 1,
        "max_output_bytes": 1,
        "max_memory_pages": 1,
        "max_table_elements": 1,
        "max_call_depth": 1,
        "max_instruction_fuel": 1,
        "max_host_deadline_ms": 1,
    }
    _assert_transition_refusal(
        lambda: tp.validate_tcb_manifest(frozen),
        "DSL_ONLY_TCB_FORBIDS_WASM_CEILINGS",
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
    assert pack["qualification_receipt_digest"] is None
    assert tcb["qualification_receipt_digest"] is None
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


def test_pack_tcb_receipts_must_match_for_qualified_contract_only_pair() -> None:
    tcb_receipt = _digest("qualified TCB receipt")
    pack_receipt = _digest("different qualified pack receipt")
    tcb = _tcb_manifest(qualification_receipt_digest=tcb_receipt)
    pack = _pack_manifest(
        tcb=tcb,
        pack_id="pack.fixture",
        qualification_state=tc.QualificationState.QUALIFIED.value,
        qualification_receipt_digest=pack_receipt,
        execution_state=tp.PackExecutionState.CONTRACT_ONLY.value,
    )

    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(pack, tcb),
        "PACK_TCB_QUALIFICATION_MISMATCH",
    )


@pytest.mark.parametrize(
    ("attack", "expected"),
    (
        ("unrelated_source", "PACK_TCB_SOURCE_ROLE_UNSUPPORTED"),
        ("unrelated_allowed_role", "PACK_TCB_SOURCE_SET_MISMATCH"),
        ("missing_program", "PACK_TCB_DECLARATIVE_PROGRAM_SOURCE_MISMATCH"),
        ("duplicate_program", "PACK_TCB_DECLARATIVE_PROGRAM_SOURCE_MISMATCH"),
        ("program_digest_substitution", "PACK_TCB_DECLARATIVE_PROGRAM_DIGEST_MISMATCH"),
        ("denominator_digest_substitution", "PACK_TCB_DENOMINATOR_SOURCE_MISMATCH"),
        ("legacy_rule_census", "PACK_TCB_SEMANTIC_CENSUS_MISMATCH"),
        ("zero_semantic_census", "PACK_TCB_SEMANTIC_CENSUS_MISMATCH"),
    ),
)
def test_pack_tcb_pair_rejects_unjoined_or_substituted_pack_sources(
        attack: str,
        expected: str) -> None:
    tcb = _tcb_manifest()
    pack = _pack_manifest(tcb=tcb)
    candidate = deepcopy(tcb)

    program_index = next(
        index
        for index, source in enumerate(candidate["pack_sources"])
        if source["role"] == tp.DECLARATIVE_PROGRAM_SOURCE_ROLE
    )
    denominator_index = next(
        index
        for index, source in enumerate(candidate["pack_sources"])
        if source["role"] == tp.SUPPORTED_DENOMINATOR_SOURCE_ROLE
    )
    if attack == "unrelated_source":
        candidate["pack_sources"].append(_artifact(
            "unrelated",
            "cisco_toolkit/data/unrelated-workload.json",
            "PROTOTYPE_TYPED_INPUT",
        ))
    elif attack == "unrelated_allowed_role":
        candidate["pack_sources"].append(_artifact(
            "unrelated-module",
            "cisco_toolkit/data/unrelated-module.wasm",
            tp.WASM_PARSER_MODULE_SOURCE_ROLE,
        ))
    elif attack == "missing_program":
        candidate["pack_sources"].pop(program_index)
    elif attack == "duplicate_program":
        candidate["pack_sources"].append(_artifact(
            "duplicate-program",
            "cisco_toolkit/data/duplicate-program.json",
            tp.DECLARATIVE_PROGRAM_SOURCE_ROLE,
            digest=pack["declarative_rules_digest"],
        ))
    elif attack == "program_digest_substitution":
        candidate["pack_sources"][program_index]["digest"] = _digest(
            "unrelated declarative program"
        )
    elif attack == "denominator_digest_substitution":
        candidate["pack_sources"][denominator_index]["digest"] = _digest(
            "unrelated denominator"
        )
    elif attack == "legacy_rule_census":
        candidate["pack_census_method"] = tp.LEGACY_TCB_PACK_CENSUS_METHOD
    else:
        candidate["pack_executable_lines"] = 0
    candidate["pack_sources"].sort(
        key=lambda item: (item["artifact_id"], item["path"])
    )
    pack["tcb_manifest_digest"] = tc.canonical_digest(candidate)

    _assert_transition_refusal(
        lambda: tp.validate_pack_tcb_pair(pack, candidate),
        expected,
    )


def test_wasm_capable_pair_requires_exact_module_role_and_digest_join() -> None:
    module = _wasm_module()
    tcb = _tcb_manifest(
        wasm_runtime_digest=_digest("metered Wasm runtime"),
        wasm_modules=[module],
    )
    pack = _pack_manifest(
        tcb=tcb,
        pack_id="pack.fixture",
        substrate=tp.PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value,
        wasm_modules=[module],
    )
    tp.validate_pack_tcb_pair(pack, tcb)

    for attack in ("digest", "role", "artifact_id", "missing"):
        candidate = deepcopy(tcb)
        module_index = next(
            index
            for index, source in enumerate(candidate["pack_sources"])
            if source["role"] == tp.WASM_PARSER_MODULE_SOURCE_ROLE
        )
        if attack == "digest":
            candidate["pack_sources"][module_index]["digest"] = _digest(
                "substituted Wasm module"
            )
        elif attack == "role":
            candidate["pack_sources"][module_index]["role"] = (
                tp.WASM_NORMALIZER_MODULE_SOURCE_ROLE
            )
        elif attack == "artifact_id":
            candidate["pack_sources"][module_index]["artifact_id"] = "module.parser.other"
        else:
            candidate["pack_sources"].pop(module_index)
        candidate["pack_sources"].sort(
            key=lambda item: (item["artifact_id"], item["path"])
        )
        hostile_pack = deepcopy(pack)
        hostile_pack["tcb_manifest_digest"] = tc.canonical_digest(candidate)

        _assert_transition_refusal(
            lambda hostile_pack=hostile_pack, candidate=candidate: (
                tp.validate_pack_tcb_pair(hostile_pack, candidate)
            ),
            "PACK_TCB_WASM_MODULE_SOURCE_MISMATCH",
        )


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
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
    assert verified.signature_digest == tc.bytes_digest(
        tc.canonical_json_bytes(material["signature"])
    )
    assert verified.public_key_digest == tc.bytes_digest(material["public_key_raw"])
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

    invalid_issuance_time = _qualification_material()
    invalid_issuance_time["receipt"]["issued_at"] = "2025-12-31T23:59:59.999999Z"
    _resign(invalid_issuance_time)
    _assert_pack_refusal(
        lambda: _verify(invalid_issuance_time),
        "qualification_key_not_valid_at_receipt_issuance",
    )

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
