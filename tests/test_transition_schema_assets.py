"""Mechanical parity and real-resource gates for the R2.0 structural contract."""

from __future__ import annotations

import json
from copy import deepcopy
import importlib.util
from importlib import resources
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_runtime_inventory as ri
from tests.transition_fixtures import minimal_transition_case


_SCHEMA_RESOURCE = "schemas/atlas-transition-contract-v1.schema.json"
_QCP_RESOURCE = "data/qcp-001.experimental.json"
_TCB_CENSUS_RESOURCE = "data/atlas-r2-structural-tcb-census.v1.json"
_TCB_CENSUS_SCHEMA_RESOURCE = "schemas/atlas-r2-structural-tcb-census-v1.schema.json"
_WINDOWS_RUNTIME_DISCOVERY_SCHEMA_RESOURCE = (
    "schemas/atlas-r2-windows-runtime-discovery-v1.schema.json"
)
_QCP_DIGEST = "sha256:5c820c7128b50abf40d3f23dbb01251795a977d22b3c05e327b5c4eef432f8ac"
_TCB_CENSUS_DIGEST = "sha256:f71abe7ea2d733eec30eaa7a1b4eba962a4bb4074758a1ec7335aa28c40f0d5b"


def _resource_bytes(relative: str) -> bytes:
    root = resources.files("cisco_toolkit")
    return root.joinpath(*relative.split("/")).read_bytes()


def _schema() -> dict[str, Any]:
    return json.loads(_resource_bytes(_SCHEMA_RESOURCE))


def _windows_runtime_discovery_schema() -> dict[str, Any]:
    return json.loads(_resource_bytes(_WINDOWS_RUNTIME_DISCOVERY_SCHEMA_RESOURCE))


def _windows_runtime_discovery_documents() -> list[dict[str, Any]]:
    schema = _windows_runtime_discovery_schema()
    protocol = schema["$defs"]["captureProtocol"]["const"]
    claim_boundary = schema["$defs"]["claimBoundary"]["const"]
    program_raw = _resource_bytes("data/atlas-r2-dsl-prototype-program.v1.json")
    input_raw = _resource_bytes("data/atlas-r2-dsl-prototype-input.v1.json")
    receipt = json.loads(dsl.run_pack_abi("evaluate", program_raw, input_raw))
    shim_token = "process.000000000001"
    process_token = "process.000000000002"
    mapping_token = "mapping.000000000001"
    digest = "sha256:" + "a" * 64
    authority = {
        "authoritative": False,
        "closure_decision": None,
        "complete_exact_runtime_closure": False,
        "approved_budget": None,
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "release3_included": False,
    }
    common = {
        "capture_protocol": protocol,
        "platform": {"os_name": "nt", "sys_platform": "win32"},
        "selected_commit": "1" * 40,
        "selected_tree": "2" * 40,
        "claim_boundary": claim_boundary,
        "authority": authority,
    }
    process_trace = {
        **deepcopy(common),
        "schema": "atlas.windows-job-process-trace/1",
        "limits": {
            "max_runtime_seconds": 30,
            "max_process_events": 4096,
            "max_mapping_snapshots": 256,
            "max_mappings_per_snapshot": 4096,
            "poll_interval_milliseconds": 25,
        },
        "target": {
            "program_digest": tc.bytes_digest(program_raw),
            "input_digest": tc.bytes_digest(input_raw),
            "receipt_digest": tc.canonical_digest(receipt),
            "receipt": receipt,
            "outcome": "EXECUTED_NONAUTHORITATIVE",
            "authoritative": False,
            "promotion_eligible": False,
            "crypto_provider_module": "cryptography.hazmat.bindings._rust",
            "crypto_provider_path_digest": digest,
            "crypto_vector": "RFC8032-TEST-1-EMPTY-MESSAGE",
            "crypto_verified": True,
        },
        "target_process_token": process_token,
        "job": {
            "completion_port_associated": True,
            "kill_on_job_close": True,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "assigned_process_count": 1,
            "observed_process_count": 2,
            "active_process_zero_observed": True,
            "target_exit_code": 0,
        },
        "process_event_count": 5,
        "events": [
            {
                "sequence": 0,
                "event": "NEW_PROCESS",
                "process_token": shim_token,
                "job_message_id": 6,
            },
            {
                "sequence": 1,
                "event": "NEW_PROCESS",
                "process_token": process_token,
                "job_message_id": 6,
            },
            {
                "sequence": 2,
                "event": "EXIT_PROCESS",
                "process_token": process_token,
                "job_message_id": 7,
            },
            {
                "sequence": 3,
                "event": "EXIT_PROCESS",
                "process_token": shim_token,
                "job_message_id": 7,
            },
            {
                "sequence": 4,
                "event": "ACTIVE_PROCESS_ZERO",
                "process_token": None,
                "job_message_id": 4,
            },
        ],
    }
    mapping_trace = {
        **deepcopy(common),
        "schema": "atlas.windows-k32-mapping-observation-trace/1",
        "method": "WINDOWS_K32_ENUM_PROCESS_MODULES_EX_POLLING/1",
        "semantics": "POLLING_CHECKPOINTS_NOT_LOAD_UNLOAD_HISTORY",
        "history_complete": False,
        "target_process_token": process_token,
        "snapshot_count": 1,
        "mapping_row_count": 1,
        "distinct_mapping_count": 1,
        "snapshots": [
            {
                "sequence": 0,
                "process_token": process_token,
                "status": "OBSERVED_NONEMPTY",
                "mappings": [
                    {
                        "mapping_token": mapping_token,
                        "observed_path_digest": digest,
                        "path_disclosure": "DIGEST_ONLY_NO_RAW_PATH",
                        "mapping_kind": "K32_ENUMERATED_IMAGE",
                    }
                ],
            }
        ],
    }
    loss_reconciliation = {
        **deepcopy(common),
        "schema": "atlas.windows-discovery-loss-reconciliation/1",
        "target_process_token": process_token,
        "process_event_count": 5,
        "mapping_snapshot_count": 1,
        "mapping_row_count": 1,
        "event_stream_contiguous": False,
        "start_end_snapshot_reconciled": False,
        "counters": {
            "job_messages_lost": None,
            "process_events_lost": None,
            "mapping_snapshots_lost": None,
            "mapping_load_events_lost": None,
            "mapping_unload_events_lost": None,
            "k32_enumeration_failures": 0,
        },
        "limitations": schema["$defs"]["lossReconciliation"]["properties"][
            "limitations"
        ]["const"],
    }
    return [process_trace, mapping_trace, loss_reconciliation]


def _validator_for(definition: str) -> Draft202012Validator:
    schema = _schema()
    return Draft202012Validator({
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    })


def _enum_values(enum_type: type) -> set[str]:
    return {item.value for item in enum_type}


def test_real_schema_is_valid_and_accepts_the_production_validated_case_fixture() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    case = minimal_transition_case()

    tc.validate_transition_case(case)
    Draft202012Validator(schema).validate(case)


def test_schema_closed_vocabularies_match_code_owners_exactly() -> None:
    defs = _schema()["$defs"]
    expected = {
        "caseMode": _enum_values(tc.CaseMode),
        "evidenceClass": _enum_values(tc.EvidenceClass),
        "observationMode": _enum_values(tc.ObservationMode),
        "temporalOperator": _enum_values(tc.TemporalOperator),
        "temporalOutcome": _enum_values(tc.TemporalOutcome),
        "evidenceStatus": _enum_values(tc.EvidenceStatus),
        "applicabilityKind": _enum_values(tc.ApplicabilityKind),
        "qualificationState": _enum_values(tc.QualificationState),
        "authoritativeGate": _enum_values(tc.AuthoritativeGate),
        "evidenceEffect": _enum_values(tc.EvidenceEffect),
        "evaluatorKind": _enum_values(tc.EvaluatorKind),
        "rollbackDimension": _enum_values(tc.RollbackDimension),
        "packExecutionState": _enum_values(tp.PackExecutionState),
        "packSubstrate": _enum_values(tp.PackSubstrate),
        "tcbBudgetState": _enum_values(tp.TCBBudgetState),
        "tcbRuntimeInventoryState": _enum_values(tp.TCBRuntimeInventoryState),
        "qualificationSubjectKind": _enum_values(tp.QualificationSubjectKind),
    }
    for definition, values in expected.items():
        assert set(defs[definition]["enum"]) == values

    assert set(defs["objectBinding"]["properties"]["role"]["enum"]) == (
        tc.OBJECT_BINDING_ROLES
    )

    pack = defs["packManifest"]["properties"]
    assert [item["const"] for item in pack["functions"]["prefixItems"]] == list(
        tp.PACK_ABI_FUNCTIONS
    )
    assert [item["const"] for item in pack["declarative_operators"]["prefixItems"]] == list(
        tp.DECLARATIVE_DSL_OPERATORS
    )


def test_real_qcp_asset_is_exact_canonical_experimental_and_non_resolving() -> None:
    raw = _resource_bytes(_QCP_RESOURCE)
    bound = tp.bind_pack_manifest_bytes(raw)
    _validator_for("packManifest").validate(dict(bound))

    assert bound.digest == _QCP_DIGEST
    assert bound.source_bytes == 908
    assert bound["pack_id"] == tp.QCP_001_ID
    assert bound["pack_version"] == tp.QCP_001_DRAFT_VERSION
    assert bound["qualification_state"] == tc.QualificationState.EXPERIMENTAL.value
    assert bound["execution_state"] == tp.PackExecutionState.CONTRACT_ONLY.value
    assert bound["qualification_receipt_digest"] is None
    assert {
        bound["semantic_bundle_digest"],
        bound["declarative_rules_digest"],
        bound["supported_denominator_digest"],
        bound["tcb_manifest_digest"],
    } == {None}
    tp.qcp_001_must_remain_experimental(bound)


def test_qcp_pending_references_cannot_cross_the_activation_boundary() -> None:
    qcp = json.loads(_resource_bytes(_QCP_RESOURCE))
    qcp["pack_id"] = "PACK-HOSTILE"
    qcp["pack_version"] = "1.0.0"
    qcp["qualification_state"] = tc.QualificationState.QUALIFIED.value
    qcp["qualification_receipt_digest"] = tc.canonical_digest({"fixture": "receipt"})
    qcp["execution_state"] = tp.PackExecutionState.ACTIVATABLE.value
    qcp["claim_boundary"] = "Hostile activation attempt."

    with pytest.raises(tc.TransitionContractError) as error:
        tp.validate_pack_manifest(qcp)
    assert error.value.code == "EXPECTED_TEXT"
    with pytest.raises(ValidationError):
        _validator_for("packManifest").validate(qcp)


def test_structural_tcb_census_is_exact_schema_valid_and_honestly_blocks_freeze() -> None:
    raw = _resource_bytes(_TCB_CENSUS_RESOURCE)
    value = json.loads(raw)
    schema = json.loads(_resource_bytes(_TCB_CENSUS_SCHEMA_RESOURCE))

    assert tc.bytes_digest(raw) == _TCB_CENSUS_DIGEST
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    assert tp.r2_structural_tcb_census() == value
    assert value["structural_core"]["executable_statements"] == 6335
    assert value["census_method"]["measurement_scope"] == (
        "REFERENCE_ENVIRONMENT_OBSERVATION_WITH_PORTABLE_SOURCE_DIGEST_CHECK"
    )
    assert value["conditional_legacy_replay_tcb"]["adapter_source"][
        "executable_statements"
    ] == 329
    assert value["conditional_legacy_replay_tcb"]["embedded_driver"][
        "executable_statements"
    ] == 82
    assert value["budget_gate"] == {
        "budget_state": (
            "PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
        ),
        "core_sloc_budget": None,
        "pack_resource_ceilings": None,
        "pack_sloc_budget": None,
        "promotion_effect": "BLOCKS_R2_0_COMPLETION",
        "reason": (
            "The executable DSL-only prototype has measured provisional guards, but its "
            "runtime dependency inventory remains partial and nonportable; numeric core/pack "
            "budgets and resource ceilings also lack independent approval and a signed review "
            "receipt bound to a selected commit, tree, census, and measurements."
        ),
    }
    assert value["executable_prototype"]["execution_state"] == (
        "DSL_ONLY_EXECUTABLE_NONAUTHORITATIVE"
    )
    assert value["executable_prototype"]["qcp_001_executed"] is False
    assert value["executable_prototype"]["source_binding_state"] == (
        "SAME_CHECKOUT_SELF_CHECK_ONLY"
    )
    assert value["executable_prototype"]["runtime_inventory_state"] == (
        "PARTIAL_NONPORTABLE_PROTOTYPE"
    )
    assert value["executable_prototype"]["runtime_inventory"] == {
        "asset_digest": "sha256:199742e733aaa1009ffc59f605019fc3cc0aee73cd85d444bfe70de8c8c89229",
        "blind_spot_count": 9,
        "claim_boundary": (
            "Exact-byte inventory of the observed isolated reference process and bounded "
            "static PE resolutions only; not portable closure, all-branch coverage, "
            "qualification, or promotion authority."
        ),
        "complete_exact_runtime_closure": False,
        "native_dependency_edge_count": 10062,
        "python_module_count": 148,
        "runtime_file_count": 339,
        "state": "PARTIAL_NONPORTABLE_PROTOTYPE",
        "unresolved_native_dependency_edge_count": 8194,
    }
    assert value["executable_prototype"]["runtime_inventory_tool"]["path"] == (
        "tools/build_transition_runtime_inventory.py"
    )
    assert value["executable_prototype"]["wasm_execution_state"] == (
        "UNIMPLEMENTED_UNREVIEWED"
    )
    assert value["implemented_guard_constants"]["dsl_prototype"] == {
        "max_expression_depth": 32,
        "max_expression_nodes": 4096,
        "max_input_bytes": 1048576,
        "max_input_nodes": 16384,
        "max_instruction_fuel": 32768,
        "max_operator_operands": 256,
        "max_output_bytes": 131072,
        "max_path_segments": 32,
        "max_program_bytes": 262144,
        "max_rules": 1024,
        "max_set_items": 1024,
        "max_string_bytes": 65536,
        "profile": "DEFAULT_DSL_PROTOTYPE_LIMITS",
        "state": "PROVISIONAL_MEASURED_NOT_REVIEWED_BUDGET",
    }
    assert value["release3_included"] is False
    assert value["independent_review"]["result"] == (
        "PENDING_BOUND_INDEPENDENT_REVIEW_EVIDENCE"
    )
    assert value["independent_review"]["review_evidence"] is None
    assert value["independent_review"]["required_next_evidence"] == [
        "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY",
        "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
        "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE",
        "APPROVED_REVIEW_POLICY_AND_TRUSTED_KEY_CUSTODY",
        "SIGNED_REVIEW_RECEIPT_BOUND_TO_SELECTED_COMMIT_TREE_CENSUS_AND_MEASUREMENTS",
        "SELECTED_COMMIT_BINDING",
    ]
    assert value["repository_basis"] == {
        "selected_commit": None,
        "source_basis_parent_sha": "935213e8babc6fde555627eaa434749397a1617d",
        "state": "EXACT_INPUT_DIGESTS_AWAIT_EXTERNAL_SELECTED_COMMIT_BINDING",
    }


def test_structural_tcb_census_schema_represents_only_joined_runtime_closure_states() -> None:
    value = json.loads(_resource_bytes(_TCB_CENSUS_RESOURCE))
    schema = json.loads(_resource_bytes(_TCB_CENSUS_SCHEMA_RESOURCE))
    validator = Draft202012Validator(schema)
    complete = deepcopy(value)
    complete["budget_gate"]["budget_state"] = (
        "PROTOTYPE_MEASURED_COMPLETE_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
    )
    complete["executable_prototype"]["runtime_inventory_state"] = (
        tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
    )
    complete["executable_prototype"]["runtime_inventory"].update({
        "blind_spot_count": 0,
        "claim_boundary": ri.RUNTIME_INVENTORY_COMPLETE_CLAIM_BOUNDARY,
        "complete_exact_runtime_closure": True,
        "state": ri.RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE,
        "unresolved_native_dependency_edge_count": 0,
    })
    complete["independent_review"]["required_next_evidence"] = [
        "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
        "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE",
        "APPROVED_REVIEW_POLICY_AND_TRUSTED_KEY_CUSTODY",
        "SIGNED_REVIEW_RECEIPT_BOUND_TO_SELECTED_COMMIT_TREE_CENSUS_AND_MEASUREMENTS",
        "SELECTED_COMMIT_BINDING",
    ]

    validator.validate(complete)

    mismatched = deepcopy(value)
    mismatched["executable_prototype"]["runtime_inventory_state"] = (
        tp.TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
    )
    with pytest.raises(ValidationError):
        validator.validate(mismatched)

    complete["independent_review"]["required_next_evidence"].insert(
        0, "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY"
    )
    with pytest.raises(ValidationError):
        validator.validate(complete)


def test_structural_tcb_census_default_command_is_a_portable_read_only_drift_check() -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "tools/census_transition_tcb.py"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert completed.returncode == 0, completed.stderr


def test_portable_tcb_check_reuses_only_committed_reference_observations(
        monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    script = repository / "tools/census_transition_tcb.py"
    spec = importlib.util.spec_from_file_location("_atlas_tcb_census_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def ambient_measurement_forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("portable census check consulted ambient measurement state")

    monkeypatch.setattr(module, "_statement_count", ambient_measurement_forbidden)
    monkeypatch.setattr(module, "_distribution", ambient_measurement_forbidden)
    raw = _resource_bytes(_TCB_CENSUS_RESOURCE)
    assert module._build(repository, reference=json.loads(raw)) == raw


def test_schema_and_code_both_reject_open_fields_and_caller_qualification_authority() -> None:
    case = minimal_transition_case()
    hostile = deepcopy(case)
    hostile["applicability"]["qualification_state"] = "QUALIFIED"

    with pytest.raises(tc.TransitionContractError) as code_error:
        tc.validate_transition_case(hostile)
    assert code_error.value.code == "CLOSED_SCHEMA_KEYS"
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(hostile)

    hostile = deepcopy(case)
    hostile["pack_binding"]["native_python_plugin"] = "attacker.module"
    with pytest.raises(tc.TransitionContractError) as nested_code_error:
        tc.validate_transition_case(hostile)
    assert nested_code_error.value.code == "CLOSED_SCHEMA_KEYS"
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(hostile)


def test_windows_runtime_discovery_schema_accepts_exactly_three_incomplete_artifacts() -> None:
    schema = _windows_runtime_discovery_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    documents = _windows_runtime_discovery_documents()

    assert {item["schema"] for item in documents} == {
        "atlas.windows-job-process-trace/1",
        "atlas.windows-k32-mapping-observation-trace/1",
        "atlas.windows-discovery-loss-reconciliation/1",
    }
    assert {item["$ref"] for item in schema["oneOf"]} == {
        "#/$defs/processTrace",
        "#/$defs/mappingTrace",
        "#/$defs/lossReconciliation",
    }
    for document in documents:
        validator.validate(document)
        assert document["authority"] == {
            "authoritative": False,
            "closure_decision": None,
            "complete_exact_runtime_closure": False,
            "approved_budget": None,
            "qualification_effect": "NONE",
            "promotion_eligible": False,
            "release3_included": False,
        }


def test_windows_runtime_discovery_schema_rejects_authority_raw_paths_and_history_lies() -> None:
    validator = Draft202012Validator(_windows_runtime_discovery_schema())
    process_trace, mapping_trace, loss_reconciliation = (
        _windows_runtime_discovery_documents()
    )
    hostile_documents: list[dict[str, Any]] = []

    authoritative = deepcopy(process_trace)
    authoritative["authority"]["authoritative"] = True
    hostile_documents.append(authoritative)

    complete = deepcopy(process_trace)
    complete["authority"]["complete_exact_runtime_closure"] = True
    hostile_documents.append(complete)

    qualified = deepcopy(process_trace)
    qualified["target"]["receipt"]["qualification_state"] = "QUALIFIED"
    hostile_documents.append(qualified)

    open_surface = deepcopy(process_trace)
    open_surface["ready_for_external_review"] = True
    hostile_documents.append(open_surface)

    rechained_nested_authority = deepcopy(process_trace)
    target = rechained_nested_authority["target"]
    receipt = target["receipt"]
    receipt["result"]["entries"][0]["value"] = {
        "authoritative": True,
        "qualification_effect": "COMPLETE",
    }
    receipt["result_digest"] = tc.canonical_digest(receipt["result"])
    receipt["work_units"]["result_bytes"] = len(tc.canonical_json_bytes(receipt["result"]))
    target["receipt_digest"] = tc.canonical_digest(receipt)
    hostile_documents.append(rechained_nested_authority)

    raw_path = deepcopy(mapping_trace)
    raw_path["snapshots"][0]["mappings"][0]["raw_path"] = (
        "C:/sensitive/provider.dll"
    )
    hostile_documents.append(raw_path)

    history_lie = deepcopy(mapping_trace)
    history_lie["semantics"] = "LOAD_UNLOAD_HISTORY"
    hostile_documents.append(history_lie)

    reconciled_lie = deepcopy(loss_reconciliation)
    reconciled_lie["event_stream_contiguous"] = True
    hostile_documents.append(reconciled_lie)

    missing_unknown_counter = deepcopy(loss_reconciliation)
    del missing_unknown_counter["counters"]["mapping_unload_events_lost"]
    hostile_documents.append(missing_unknown_counter)

    for hostile in hostile_documents:
        with pytest.raises(ValidationError):
            validator.validate(hostile)


def test_windows_runtime_discovery_schema_bounds_rows_and_declares_ordering_owner() -> None:
    schema = _windows_runtime_discovery_schema()
    validator = Draft202012Validator(schema)
    process_trace, mapping_trace, _ = _windows_runtime_discovery_documents()
    process_rows = schema["$defs"]["processTrace"]["properties"]["events"]
    snapshot_rows = schema["$defs"]["mappingTrace"]["properties"]["snapshots"]
    mapping_rows = schema["$defs"]["mappingSnapshot"]["properties"]["mappings"]

    assert process_rows["maxItems"] == 4096
    assert snapshot_rows["maxItems"] == 256
    assert mapping_rows["maxItems"] == 4096
    assert "sequence ordered from zero" in process_rows["$comment"]
    assert "sequence ordered from zero" in snapshot_rows["$comment"]
    assert "Python validation" in schema["$comment"]

    negative_sequence = deepcopy(process_trace)
    negative_sequence["events"][0]["sequence"] = -1
    with pytest.raises(ValidationError):
        validator.validate(negative_sequence)

    no_initial_sequence = deepcopy(process_trace)
    no_initial_sequence["events"][0]["sequence"] = 3
    with pytest.raises(ValidationError):
        validator.validate(no_initial_sequence)

    empty_dynamic_snapshot = deepcopy(mapping_trace)
    empty_dynamic_snapshot["snapshots"][0]["mappings"] = []
    with pytest.raises(ValidationError):
        validator.validate(empty_dynamic_snapshot)
