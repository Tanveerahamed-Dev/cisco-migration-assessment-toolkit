#!/usr/bin/env python3
"""Read-only R2.0 smoke test intended to run from an installed wheel.

Run this script from a directory outside the source checkout with the target
virtual environment's interpreter.  It refuses source-tree imports, executes
the exact packaged non-authoritative DSL prototype, validates the packaged
QCP/census/measurement resources, and replays the pinned Release 1 conformance
vector twice under the exact reference runtime profile.  It also binds the
installed R2.0 `/5` schemas and public fail-closed validator entry points.
"""

from __future__ import annotations

from importlib import metadata, resources
import json
from pathlib import Path
import site

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_legacy as legacy
from cisco_toolkit import transition_pack as pack
from cisco_toolkit import transition_runtime_discovery as runtime_discovery
from cisco_toolkit import transition_runtime_inventory as runtime_inventory
from cisco_toolkit import transition_verifier as verifier


_DISTRIBUTION = "cisco-migration-assessment-toolkit"
_QCP_RESOURCE = "qcp-001.experimental.json"
_MEASUREMENT_RESOURCE = "atlas-r2-dsl-prototype-measurements.v1.json"
_V5_RUNTIME_SCHEMA_RESOURCE = "atlas-r2-windows-debug-runtime-discovery-v5.schema.json"
_V5_ENVIRONMENT_SCHEMA_RESOURCE = (
    "atlas-r2-windows-execution-environment-manifest-v5.schema.json"
)
_QCP_DIGEST = "sha256:5c820c7128b50abf40d3f23dbb01251795a977d22b3c05e327b5c4eef432f8ac"
_R1_REPLAY_DIGEST = "sha256:e92dbe997b92b3c6d1e3017408ac1a32e7364e14f61edd9202a67d9710a87c70"
_V5_RUNTIME_SCHEMA_DIGEST = (
    "sha256:bcb5ccc2b06d892978a70d2b984c7d104b6a7e2252114af5281c4002b9ba428f"
)
_V5_ENVIRONMENT_SCHEMA_DIGEST = (
    "sha256:047478aed5fa8f83467a57afece872b59a831873670d1305390d071ea3c0ec5a"
)


def _installed_module_path() -> Path:
    module_path = Path(legacy.__file__).resolve()
    site_roots = [Path(item).resolve() for item in site.getsitepackages()]
    if not any(module_path.is_relative_to(root) for root in site_roots):
        raise RuntimeError(f"transition runtime was not imported from site-packages: {module_path}")
    return module_path


def _package_bytes(package_root, relative: str) -> bytes:
    return package_root.joinpath(*relative.removeprefix("cisco_toolkit/").split("/")).read_bytes()


def _parsed(raw: bytes) -> dict:
    value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
    if type(value) is not dict:
        raise RuntimeError("installed transition evidence is not an object")
    return value


def _schema(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("installed transition schema is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise RuntimeError("installed transition schema is not an object")
    return value


def main() -> int:
    module_path = _installed_module_path()
    package_root = resources.files("cisco_toolkit")
    v5_runtime_schema_raw = package_root.joinpath(
        "schemas", _V5_RUNTIME_SCHEMA_RESOURCE
    ).read_bytes()
    v5_environment_schema_raw = package_root.joinpath(
        "schemas", _V5_ENVIRONMENT_SCHEMA_RESOURCE
    ).read_bytes()
    v5_runtime_schema = _schema(v5_runtime_schema_raw)
    v5_environment_schema = _schema(v5_environment_schema_raw)
    expected_v5_exports = {
        "capture_windows_debug_runtime_closure_v5_incomplete",
        "validate_windows_debug_execution_environment_v5_manifest",
        "validate_windows_debug_runtime_discovery_v5_trace",
    }
    if (
        contract.bytes_digest(v5_runtime_schema_raw) != _V5_RUNTIME_SCHEMA_DIGEST
        or contract.bytes_digest(v5_environment_schema_raw)
        != _V5_ENVIRONMENT_SCHEMA_DIGEST
        or v5_runtime_schema.get("$id")
        != "urn:atlas:schema:r2-windows-debug-runtime-discovery:5"
        or v5_runtime_schema.get("$defs", {}).get("claimBoundary", {}).get("const")
        != runtime_discovery.WINDOWS_DEBUG_MAPPED_IMAGE_CLAIM_BOUNDARY
        or "memory_region_passes"
        not in v5_runtime_schema.get("$defs", {}).get("fileIdentityRow", {}).get(
            "required", []
        )
        or "memory_regions"
        in v5_runtime_schema.get("$defs", {}).get("fileIdentityRow", {}).get(
            "required", []
        )
        or v5_environment_schema.get("$id")
        != "urn:atlas:schema:r2-windows-execution-environment-manifest:5"
        or v5_environment_schema.get("$defs", {}).get("captureProtocol", {}).get(
            "const"
        )
        != runtime_discovery.WINDOWS_DEBUG_MAPPED_IMAGE_CAPTURE_PROTOCOL
        or not expected_v5_exports.issubset(set(runtime_discovery.__all__))
    ):
        raise RuntimeError("installed `/5` schemas or public API drifted")
    invalid_v5_calls = (
        (
            runtime_discovery.validate_windows_debug_runtime_discovery_v5_trace,
            "WINDOWS_DEBUG_V5_RUNTIME_TRACE_COMMON_INVALID",
        ),
        (
            runtime_discovery.validate_windows_debug_execution_environment_v5_manifest,
            "WINDOWS_DEBUG_V5_EXECUTION_ENVIRONMENT_MANIFEST_INVALID",
        ),
    )
    for validator, expected_code in invalid_v5_calls:
        try:
            validator({})
        except runtime_discovery.RuntimeDiscoveryError as exc:
            if exc.code != expected_code:
                raise RuntimeError("installed `/5` validator reason drifted") from exc
        else:
            raise RuntimeError("installed `/5` validator accepted an empty artifact")
    qcp_raw = package_root.joinpath("data", _QCP_RESOURCE).read_bytes()
    qcp = pack.bind_pack_manifest_bytes(qcp_raw)
    if qcp.digest != _QCP_DIGEST:
        raise RuntimeError("installed QCP-001 digest mismatch")
    pack.qcp_001_must_remain_experimental(qcp)
    if (
        qcp["pack_id"] != "QCP-001"
        or qcp["pack_version"] != "0.1.0-experimental"
        or qcp["qualification_state"] != "EXPERIMENTAL"
        or qcp["execution_state"] != "CONTRACT_ONLY"
        or qcp["declarative_rules_digest"] is not None
        or qcp["tcb_manifest_digest"] is not None
        or qcp["qualification_receipt_digest"] is not None
    ):
        raise RuntimeError("installed QCP-001 crossed its contract-only boundary")

    prototype_pack_raw = _package_bytes(package_root, dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH)
    prototype_tcb_raw = _package_bytes(package_root, dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH)
    prototype_program_raw = _package_bytes(package_root, dsl.DSL_PROTOTYPE_PROGRAM_PATH)
    prototype_input_raw = _package_bytes(package_root, dsl.DSL_PROTOTYPE_INPUT_PATH)
    prototype_denominator_raw = _package_bytes(
        package_root,
        dsl.DSL_PROTOTYPE_DENOMINATOR_PATH,
    )
    prototype_tcb = _parsed(prototype_tcb_raw)
    prototype_source_raw = {
        item["path"]: _package_bytes(package_root, item["path"])
        for item in [*prototype_tcb["core_sources"], *prototype_tcb["pack_sources"]]
    }
    prototype = dsl.bind_packaged_dsl_prototype_bytes(
        prototype_pack_raw,
        prototype_tcb_raw,
        prototype_program_raw,
        prototype_denominator_raw,
        prototype_source_raw,
    )

    evaluated_raw = [
        dsl.run_bound_pack_abi(prototype, "evaluate", prototype_input_raw)
        for _index in range(2)
    ]
    replay_raw = [
        dsl.run_bound_pack_abi(prototype, "replay_witness", prototype_input_raw)
        for _index in range(2)
    ]
    if len(set(evaluated_raw)) != 1 or len(set(replay_raw)) != 1:
        raise RuntimeError("installed DSL prototype receipts are not deterministic")
    evaluated = _parsed(evaluated_raw[0])
    replay = _parsed(replay_raw[0])
    nonauthority = {
        "authoritative": False,
        "supplies_obligation_support": False,
        "qualification_effect": "NONE",
        "authoritative_gate": None,
        "promotion_eligible": False,
    }
    if any(evaluated[key] != value for key, value in nonauthority.items()):
        raise RuntimeError("installed DSL prototype crossed its non-authority boundary")
    temporal = next(
        (
            item
            for item in evaluated["inner_receipt"]["result"]["entries"]
            if item["rule_id"] == "prototype.evaluate-temporal"
        ),
        None,
    )
    if temporal is None or temporal["truth"] != "INCONCLUSIVE" or temporal["value"] is not None:
        raise RuntimeError("installed DSL prototype promoted incomplete temporal observation")
    replay_inner = replay["inner_receipt"]
    if (
        any(replay[key] != value for key, value in nonauthority.items())
        or replay_inner["outcome"] != "REFUSED_NONAUTHORITATIVE"
        or replay_inner["error"] != {"code": "REPLAY_WITNESS_UNSUPPORTED_R2_0"}
        or replay_inner["result"] is not None
        or replay_inner["authoritative_gate"] is not None
        or replay_inner["promotion_eligible"] is not False
    ):
        raise RuntimeError("installed DSL prototype replay did not fail closed")

    measurements = _parsed(package_root.joinpath("data", _MEASUREMENT_RESOURCE).read_bytes())
    if (
        measurements["authoritative"] is not False
        or measurements["approved_budget"] is not None
        or measurements["review_evidence"] is not None
        or measurements["qualification_effect"] != "NONE"
        or measurements["promotion_eligible"] is not False
        or measurements["wasm_execution_state"] != "UNIMPLEMENTED_UNREVIEWED"
        or measurements["release3_included"] is not False
        or measurements["review_state"]["resource_ceiling_effect"] != "NONE"
        or measurements["review_state"]["qualification_effect"] != "NONE"
        or measurements["review_state"]["promotion_effect"] != "NONE"
        or measurements["review_state"]["blockers"]
        != [
            "APPROVED_BUDGET_ABSENT",
            "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
            "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
            "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT",
        ]
    ):
        raise RuntimeError("installed prototype measurements invented authority")
    if prototype_tcb["runtime_inventory_state"] != "PARTIAL_NONPORTABLE_PROTOTYPE":
        raise RuntimeError("installed prototype invented a complete runtime closure")
    measurement_bindings = measurements["bindings"]
    packaged_measurement_subjects = {
        "pack_manifest": (dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH, prototype_pack_raw),
        "tcb_manifest": (dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH, prototype_tcb_raw),
        "prototype_program": (dsl.DSL_PROTOTYPE_PROGRAM_PATH, prototype_program_raw),
        "prototype_input": (dsl.DSL_PROTOTYPE_INPUT_PATH, prototype_input_raw),
        "supported_denominator": (
            dsl.DSL_PROTOTYPE_DENOMINATOR_PATH,
            prototype_denominator_raw,
        ),
        "interpreter_source": (
            dsl.DSL_INTERPRETER_SOURCE_PATH,
            prototype_source_raw[dsl.DSL_INTERPRETER_SOURCE_PATH],
        ),
    }
    for key, (path, raw) in packaged_measurement_subjects.items():
        if measurement_bindings[key] != {
            "path": path,
            "raw_bytes": len(raw),
            "digest": contract.bytes_digest(raw),
        }:
            raise RuntimeError("installed prototype measurement binding drifted")

    runtime_raw = _package_bytes(
        package_root,
        runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH,
    )
    runtime_value = _parsed(runtime_raw)
    runtime_inventory.validate_runtime_inventory(runtime_value)
    runtime_profile = runtime_value["profile"]["prototype"]
    if (
        runtime_profile["program_digest"] != contract.bytes_digest(prototype_program_raw)
        or runtime_profile["input_digest"] != contract.bytes_digest(prototype_input_raw)
        or runtime_value["closure"]["state"] != "PARTIAL_NONPORTABLE_PROTOTYPE"
        or runtime_value["closure"]["complete_exact_runtime_closure"] is not False
    ):
        raise RuntimeError("installed runtime inventory crossed its partial evidence boundary")
    try:
        runtime_inventory.require_complete_runtime_closure(runtime_value)
    except runtime_inventory.RuntimeInventoryError as exc:
        if exc.code != "COMPLETE_EXACT_RUNTIME_CLOSURE_NOT_ESTABLISHED":
            raise RuntimeError("installed runtime closure failed with an unstable reason") from exc
    else:
        raise RuntimeError("installed partial inventory claimed complete runtime closure")

    census = pack.r2_structural_tcb_census()
    if census["budget_gate"]["promotion_effect"] != "BLOCKS_R2_0_COMPLETION":
        raise RuntimeError("installed structural TCB census lost its completion blocker")
    if census["budget_gate"]["budget_state"] != (
        "PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
    ):
        raise RuntimeError("installed structural TCB census misstated its blocker state")
    if census["independent_review"]["required_next_evidence"][0] != (
        "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY"
    ):
        raise RuntimeError("installed structural TCB census lost its runtime-closure blocker")
    if census["independent_review"]["review_evidence"] is not None:
        raise RuntimeError("installed structural TCB census invented bound review evidence")
    if census["release3_included"] is not False:
        raise RuntimeError("installed structural TCB census includes Release 3")
    if (
        census["budget_gate"]["core_sloc_budget"] is not None
        or census["budget_gate"]["pack_sloc_budget"] is not None
        or census["budget_gate"]["pack_resource_ceilings"] is not None
        or census["repository_basis"]["selected_commit"] is not None
    ):
        raise RuntimeError("installed structural TCB census invented approval evidence")

    bundle = legacy.verify_release1_semantic_bundle()
    if not bundle.runtime_matches_reference:
        raise RuntimeError("installed replay runtime does not match the pinned reference profile")
    before, after, comparison = legacy.legacy_retrospective_vector_bytes()
    replay_arguments = {
        "change_intent": None,
        "path_intents": None,
        "l2_failure_trial": None,
    }
    first = legacy.replay_release1_comparison_bytes(
        comparison,
        before,
        after,
        bundle,
        **replay_arguments,
    )
    second = legacy.replay_release1_comparison_bytes(
        comparison,
        before,
        after,
        bundle,
        **replay_arguments,
    )
    if first != second or first["replayed_payload_digest"] != _R1_REPLAY_DIGEST:
        raise RuntimeError("installed Release 1 replay is not deterministic")
    if (
        first["replay_state"] != "CANONICAL_SEMANTIC_PAYLOAD_IDENTICAL"
        or first["migration_policy"] != "REFERENCE_NOT_REWRITE"
        or first["r2_authoritative_gate"] is not None
        or first["r2_promotion_eligible"] is not False
    ):
        raise RuntimeError("installed Release 1 replay crossed its audit-only boundary")

    gate_disposition, gate = verifier.map_authoritative_gate(
        applicability_kind=contract.ApplicabilityKind.APPLICABLE.value,
        qualification_state=contract.QualificationState.EXPERIMENTAL.value,
        mandatory_evidence_statuses=[contract.EvidenceStatus.SUPPORTED.value],
        evaluator_complete=True,
        certificates_complete=True,
    )
    if (
        gate_disposition != verifier.GateDisposition.AUTHORITATIVE_GATE.value
        or gate != contract.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    ):
        raise RuntimeError("unqualified installed gate mapping did not fail closed")

    print(json.dumps({
        "before_digest": contract.bytes_digest(before),
        "distribution_version": metadata.version(_DISTRIBUTION),
        "executable_bundle_digest": bundle.executable_bundle_digest,
        "historical_source_roster_verified": bundle.historical_source_roster_verified,
        "module_path": str(module_path),
        "dsl_prototype_evaluate_digest": contract.bytes_digest(evaluated_raw[0]),
        "dsl_prototype_replay_digest": contract.bytes_digest(replay_raw[0]),
        "dsl_prototype_source_binding_state": evaluated["source_binding_state"],
        "dsl_temporal_truth": temporal["truth"],
        "measurement_digest": contract.bytes_digest(
            package_root.joinpath("data", _MEASUREMENT_RESOURCE).read_bytes()
        ),
        "qcp_digest": qcp.digest,
        "r2_authoritative_gate": first["r2_authoritative_gate"],
        "r2_promotion_eligible": first["r2_promotion_eligible"],
        "replay_state": first["replay_state"],
        "replayed_payload_digest": first["replayed_payload_digest"],
        "runtime_inventory_digest": contract.bytes_digest(runtime_raw),
        "runtime_inventory_file_count": runtime_value["coverage"]["runtime_file_count"],
        "runtime_matches_reference": bundle.runtime_matches_reference,
        "runtime_profile_digest": bundle.runtime_profile_digest,
        "semantic_bundle_digest": bundle.digest,
        "structural_tcb_budget_state": census["budget_gate"]["budget_state"],
        "v5_environment_schema_digest": contract.bytes_digest(
            v5_environment_schema_raw
        ),
        "v5_runtime_schema_digest": contract.bytes_digest(v5_runtime_schema_raw),
        "v5_validator_empty_artifacts_refused": True,
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
