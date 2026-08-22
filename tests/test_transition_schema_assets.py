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
from cisco_toolkit import transition_pack as tp
from tests.transition_fixtures import minimal_transition_case


_SCHEMA_RESOURCE = "schemas/atlas-transition-contract-v1.schema.json"
_QCP_RESOURCE = "data/qcp-001.experimental.json"
_TCB_CENSUS_RESOURCE = "data/atlas-r2-structural-tcb-census.v1.json"
_TCB_CENSUS_SCHEMA_RESOURCE = "schemas/atlas-r2-structural-tcb-census-v1.schema.json"
_QCP_DIGEST = "sha256:5c820c7128b50abf40d3f23dbb01251795a977d22b3c05e327b5c4eef432f8ac"
_TCB_CENSUS_DIGEST = "sha256:6c7f1795152d3bdc2a5583d8976523ec03d5a20ec6a40b589c4951bb709eccf9"


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
        "qualificationSubjectKind": _enum_values(tp.QualificationSubjectKind),
    }
    for definition, values in expected.items():
        assert set(defs[definition]["enum"]) == values

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
    assert value["structural_core"]["executable_statements"] == 1753
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
        "budget_state": "PENDING_EXECUTABLE_PACK_PROTOTYPE_AND_INDEPENDENT_REVIEW",
        "core_sloc_budget": None,
        "pack_resource_ceilings": None,
        "pack_sloc_budget": None,
        "promotion_effect": "BLOCKS_R2_0_COMPLETION",
        "reason": (
            "QCP-001 is CONTRACT_ONLY and no executable DSL/Wasm prototype exists; numeric pack "
            "budgets or enforcement ceilings would be invented rather than measured."
        ),
    }
    assert value["release3_included"] is False
    assert value["independent_review"]["result"] == (
        "PENDING_BOUND_INDEPENDENT_REVIEW_EVIDENCE"
    )
    assert value["independent_review"]["review_evidence"] is None
    assert value["repository_basis"] == {
        "selected_commit": None,
        "source_basis_parent_sha": "935213e8babc6fde555627eaa434749397a1617d",
        "state": "EXACT_INPUT_DIGESTS_AWAIT_EXTERNAL_SELECTED_COMMIT_BINDING",
    }


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
