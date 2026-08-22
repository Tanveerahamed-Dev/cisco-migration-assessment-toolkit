"""Check or rebuild the machine-generated Atlas R2 structural TCB census.

This census measures the implemented structural prototype and exact executable DSL evidence.  The
measured guard values remain provisional observations: it deliberately does not convert them into
approved core/pack budgets or resource ceilings without independent signed review.  The default
check is portable: it reuses the committed reference environment's statement counts and
dependency/toolchain observations while recomputing every source and evidence byte count and
digest. ``--reference-check`` recomputes the complete measurement and is expected to pass only in
the exact recorded reference environment.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys
import tempfile
from typing import Any

import coverage


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cisco_toolkit import transition_dsl as dsl  # noqa: E402
from cisco_toolkit import transition_runtime_inventory as runtime_inventory  # noqa: E402


SCHEMA = "atlas.structural-tcb-census/1"
RESOURCE = "atlas-r2-structural-tcb-census.v1.json"
SOURCE_BASIS_PARENT_SHA = "935213e8babc6fde555627eaa434749397a1617d"
CORE_SOURCES = (
    ("cisco_toolkit/transition_contract.py", "STRUCTURAL_CONTRACT_AND_CANONICAL_CODEC"),
    ("cisco_toolkit/transition_dsl.py", "DECLARATIVE_DSL_INTERPRETER"),
    ("cisco_toolkit/transition_pack.py", "PACK_ABI_TCB_AND_QUALIFICATION_BOUNDARY"),
    ("cisco_toolkit/transition_runtime_inventory.py", "RUNTIME_DEPENDENCY_INVENTORY_VALIDATOR"),
    ("cisco_toolkit/transition_tcb_review.py", "EXTERNAL_SIGNED_TCB_BUDGET_REVIEW_BOUNDARY"),
    ("cisco_toolkit/transition_verifier.py", "STRUCTURAL_VERIFIER_AND_GATE_MAPPING"),
    (
        "cisco_toolkit/transition_workload_review.py",
        "REPRESENTATIVE_WORKLOAD_REVIEW_AUTHORITY_BOUNDARY",
    ),
)
LEGACY_SOURCE = ("cisco_toolkit/transition_legacy.py", "CONDITIONAL_RELEASE1_REPLAY_ADAPTER")
REFERENCE_DISTRIBUTIONS = ("coverage", "cryptography", "cffi", "pycparser")
MEASUREMENT_RESOURCE = "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json"
MEASUREMENT_TOOL = "tools/measure_transition_dsl_prototype.py"
RUNTIME_INVENTORY_TOOL = "tools/build_transition_runtime_inventory.py"
PROTOTYPE_ASSETS = (
    (dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH, "EXPERIMENTAL_PACK_MANIFEST"),
    (dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH, "RECEIPT_SPECIFIC_TCB_MANIFEST"),
    (dsl.DSL_PROTOTYPE_PROGRAM_PATH, "DECLARATIVE_PROGRAM"),
    (dsl.DSL_PROTOTYPE_INPUT_PATH, "TYPED_SYNTHETIC_INPUT"),
    (dsl.DSL_PROTOTYPE_DENOMINATOR_PATH, "SYNTHETIC_SUPPORTED_DENOMINATOR"),
    (MEASUREMENT_RESOURCE, "REFERENCE_BOUNDARY_MEASUREMENTS"),
    (runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH, "REFERENCE_RUNTIME_INVENTORY"),
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _distribution(name: str) -> dict[str, Any]:
    distribution = metadata.distribution(name)
    record = next(
        (item for item in distribution.files or () if str(item).endswith(".dist-info/RECORD")),
        None,
    )
    if record is None:
        raise RuntimeError(f"{name} has no installed RECORD")
    raw = Path(distribution.locate_file(record)).read_bytes()
    return {
        "metadata_record_bytes": len(raw),
        "metadata_record_sha256": _digest(raw),
        "name": distribution.metadata["Name"].lower(),
        "version": distribution.version,
    }


def _statement_count(path: Path) -> int:
    census = coverage.Coverage(config_file=False, data_file=None)
    return len(census.analysis2(str(path))[1])


def _source_entry(
        repository: Path,
        relative: str,
        role: str,
        *,
        reference_statement_count: int | None = None) -> dict[str, Any]:
    raw = (repository / relative).read_bytes()
    return {
        "bytes": len(raw),
        "executable_statements": (
            _statement_count(repository / relative)
            if reference_statement_count is None
            else reference_statement_count
        ),
        "path": relative,
        "role": role,
        "sha256": _digest(raw),
    }


def _file_binding(repository: Path, relative: str, role: str) -> dict[str, Any]:
    raw = (repository / relative).read_bytes()
    return {
        "bytes": len(raw),
        "path": relative,
        "role": role,
        "sha256": _digest(raw),
    }


def _prototype_evidence(repository: Path) -> dict[str, Any]:
    raw_by_path = {
        path: (repository / path).read_bytes()
        for path, _role in PROTOTYPE_ASSETS
    }
    pack_raw = raw_by_path[dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH]
    tcb_raw = raw_by_path[dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH]
    program_raw = raw_by_path[dsl.DSL_PROTOTYPE_PROGRAM_PATH]
    input_raw = raw_by_path[dsl.DSL_PROTOTYPE_INPUT_PATH]
    denominator_raw = raw_by_path[dsl.DSL_PROTOTYPE_DENOMINATOR_PATH]
    try:
        tcb = json.loads(tcb_raw)
        source_rows = [*tcb["core_sources"], *tcb["pack_sources"]]
        source_bytes = {
            row["path"]: (repository / row["path"]).read_bytes()
            for row in source_rows
        }
        bound = dsl.bind_packaged_dsl_prototype_bytes(
            pack_raw,
            tcb_raw,
            program_raw,
            denominator_raw,
            source_bytes,
        )
        receipt_raw = dsl.run_bound_pack_abi(bound, "evaluate", input_raw)
        repeat_raw = dsl.run_bound_pack_abi(bound, "evaluate", input_raw)
        receipt = json.loads(receipt_raw)
        measurement_raw = raw_by_path[MEASUREMENT_RESOURCE]
        measurement = json.loads(measurement_raw)
        runtime_inventory_raw = raw_by_path[runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH]
        runtime_inventory_value = json.loads(runtime_inventory_raw)
        runtime_inventory.validate_runtime_inventory(runtime_inventory_value)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        raise RuntimeError("executable DSL prototype evidence is invalid") from None
    if receipt_raw != repeat_raw or _canonical(receipt) != receipt_raw:
        raise RuntimeError("executable DSL prototype replay is not deterministic")
    if (
            tcb.get("runtime_inventory_state")
            != "PARTIAL_NONPORTABLE_PROTOTYPE"
    ):
        raise RuntimeError("prototype TCB did not disclose its partial runtime inventory")
    inner = receipt.get("inner_receipt")
    if (
            type(inner) is not dict
            or receipt.get("source_binding_state") != dsl.DSL_PROTOTYPE_SOURCE_BINDING_STATE
            or inner.get("outcome") != "EXECUTED_NONAUTHORITATIVE"
            or inner.get("authoritative") is not False
            or inner.get("authoritative_gate") is not None
            or inner.get("promotion_eligible") is not False
            or inner.get("qualification_effect") != "NONE"
            or inner.get("supplies_obligation_support") is not False
    ):
        raise RuntimeError("executable DSL prototype crossed its non-authority boundary")

    limits = {
        field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
        for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
    }
    bindings = measurement.get("bindings")
    boundary_rows = measurement.get("boundary_measurements")
    baseline = measurement.get("baseline_execution")
    if (
            _canonical(measurement) != measurement_raw
            or measurement.get("schema") != "atlas.dsl-prototype-measurements/1"
            or measurement.get("authoritative") is not False
            or measurement.get("approved_budget") is not None
            or measurement.get("review_evidence") is not None
            or measurement.get("qualification_effect") != "NONE"
            or measurement.get("promotion_eligible") is not False
            or measurement.get("release3_included") is not False
            or measurement.get("wasm_execution_state") != "UNIMPLEMENTED_UNREVIEWED"
            or type(bindings) is not dict
            or type(baseline) is not dict
            or baseline.get("inner_receipt_digest") != _digest(_canonical(inner))
            or bindings.get("default_limit_profile", {}).get("value") != limits
            or type(boundary_rows) is not list
            or [row.get("dimension") for row in boundary_rows]
            != list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
            or any(
                row.get("shipped_default_limit") != limits[row.get("dimension")]
                or row.get("reachability") != "REACHABLE_AT_SHIPPED_DEFAULT"
                or row.get("review_blocker") is not None
                for row in boundary_rows
            )
            or measurement.get("review_state") != {
                "blockers": [
                    "APPROVED_BUDGET_ABSENT",
                    "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
                    "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
                    "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT",
                ],
                "promotion_effect": "NONE",
                "qualification_effect": "NONE",
                "resource_ceiling_effect": "NONE",
                "state": "PENDING_INDEPENDENT_NUMERIC_REVIEW_AND_SIGNED_EVIDENCE",
            }
    ):
        raise RuntimeError("DSL prototype measurements are not honest pending-review evidence")
    corrections = measurement.get("design_corrections")
    if (
            type(corrections) is not list
            or len(corrections) != 1
            or corrections[0].get("dimension") != "max_output_bytes"
            or corrections[0].get("prior_provisional_value") != 262_144
            or corrections[0].get("corrected_provisional_value") != 131_072
            or corrections[0].get("authority_effect")
            != "NONE_PENDING_INDEPENDENT_REVIEW"
    ):
        raise RuntimeError("DSL prototype limit correction evidence is missing")
    runtime_profile = runtime_inventory_value["profile"]["prototype"]
    runtime_coverage = runtime_inventory_value["coverage"]
    runtime_closure = runtime_inventory_value["closure"]
    if (
            _canonical(runtime_inventory_value) != runtime_inventory_raw
            or runtime_profile["program_digest"] != _digest(program_raw)
            or runtime_profile["input_digest"] != _digest(input_raw)
            or runtime_profile["receipt_digest"]
            != baseline.get("inner_receipt_digest")
            or runtime_profile["authoritative"] is not False
            or runtime_profile["promotion_eligible"] is not False
            or runtime_closure["state"]
            != runtime_inventory.RUNTIME_INVENTORY_CLOSURE_STATE
            or runtime_closure["complete_exact_runtime_closure"] is not False
    ):
        raise RuntimeError("reference runtime inventory crossed its claim boundary")

    return {
        "asset_bindings": [
            _file_binding(repository, path, role)
            for path, role in PROTOTYPE_ASSETS
        ],
        "baseline_receipt_digest": _digest(receipt_raw),
        "claim_boundary": dsl.DSL_PROTOTYPE_CLAIM_BOUNDARY,
        "execution_state": "DSL_ONLY_EXECUTABLE_NONAUTHORITATIVE",
        "interpreter_source": _file_binding(
            repository,
            dsl.DSL_INTERPRETER_SOURCE_PATH,
            "DECLARATIVE_DSL_INTERPRETER",
        ),
        "measurement_tool": _file_binding(
            repository,
            MEASUREMENT_TOOL,
            "REFERENCE_MEASUREMENT_PRODUCER",
        ),
        "runtime_inventory": {
            "asset_digest": _digest(runtime_inventory_raw),
            "blind_spot_count": len(runtime_closure["blind_spots"]),
            "claim_boundary": runtime_closure["claim_boundary"],
            "complete_exact_runtime_closure": False,
            "native_dependency_edge_count": runtime_coverage[
                "native_dependency_edge_count"
            ],
            "python_module_count": runtime_coverage["python_module_count"],
            "runtime_file_count": runtime_coverage["runtime_file_count"],
            "state": runtime_closure["state"],
            "unresolved_native_dependency_edge_count": runtime_coverage[
                "unresolved_native_dependency_edge_count"
            ],
        },
        "runtime_inventory_tool": _file_binding(
            repository,
            RUNTIME_INVENTORY_TOOL,
            "REFERENCE_RUNTIME_INVENTORY_PRODUCER",
        ),
        "pack_id": dsl.DSL_PROTOTYPE_PACK_ID,
        "pack_version": dsl.DSL_PROTOTYPE_PACK_VERSION,
        "promotion_eligible": False,
        "qcp_001_executed": False,
        "qualification_effect": "NONE",
        "runtime_inventory_state": "PARTIAL_NONPORTABLE_PROTOTYPE",
        "source_binding_state": dsl.DSL_PROTOTYPE_SOURCE_BINDING_STATE,
        "substrate": "DECLARATIVE_DSL_ONLY",
        "wasm_execution_state": "UNIMPLEMENTED_UNREVIEWED",
    }


def _embedded_driver(
        repository: Path,
        *,
        reference_statement_count: int | None = None) -> dict[str, Any]:
    source_path = repository / LEGACY_SOURCE[0]
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=LEGACY_SOURCE[0])
    driver: str | None = None
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "_PINNED_RELEASE1_DRIVER"
                   for target in targets):
                value = ast.literal_eval(node.value)
                if type(value) is str:
                    driver = value
                break
    if driver is None:
        raise RuntimeError("pinned Release 1 driver source was not found")
    raw = driver.encode("utf-8")
    if reference_statement_count is None:
        with tempfile.TemporaryDirectory(prefix="atlas-tcb-driver-") as temporary:
            path = Path(temporary) / "pinned_release1_driver.py"
            path.write_bytes(raw)
            statements = _statement_count(path)
    else:
        statements = reference_statement_count
    return {
        "bytes": len(raw),
        "executable_statements": statements,
        "identifier": "transition_legacy._PINNED_RELEASE1_DRIVER",
        "role": "CONDITIONAL_RELEASE1_ISOLATED_DRIVER",
        "sha256": _digest(raw),
    }


def _reference_statement_counts(reference: dict[str, Any]) -> tuple[dict[str, int], int, int]:
    try:
        core = {
            item["path"]: item["executable_statements"]
            for item in reference["structural_core"]["sources"]
        }
        legacy = reference["conditional_legacy_replay_tcb"]["adapter_source"][
            "executable_statements"
        ]
        driver = reference["conditional_legacy_replay_tcb"]["embedded_driver"][
            "executable_statements"
        ]
    except (KeyError, TypeError):
        raise RuntimeError("committed reference census has invalid statement measurements") from None
    expected = {path for path, _role in CORE_SOURCES}
    if (
            set(core) != expected
            or any(type(value) is not int or value < 1 for value in core.values())
            or type(legacy) is not int
            or legacy < 1
            or type(driver) is not int
            or driver < 1
    ):
        raise RuntimeError("committed reference census has invalid statement measurements")
    return core, legacy, driver


def _build(repository: Path, *, reference: dict[str, Any] | None = None) -> bytes:
    if reference is None:
        core_counts: dict[str, int | None] = {
            path: None for path, _role in CORE_SOURCES
        }
        legacy_count = None
        driver_count = None
        statement_parser = f"coverage.py/{coverage.__version__}"
        runtime_dependencies = [
            _distribution(name) for name in REFERENCE_DISTRIBUTIONS
        ]
        executable_raw = Path(sys.executable).read_bytes()
        reference_toolchain = {
            "cache_tag": sys.implementation.cache_tag,
            "executable_bytes": len(executable_raw),
            "executable_sha256": _digest(executable_raw),
            "implementation": platform.python_implementation(),
            "platform_machine": platform.machine(),
            "platform_system": platform.system(),
            "python_version": platform.python_version(),
        }
    else:
        measured_core, legacy_count, driver_count = _reference_statement_counts(reference)
        core_counts = dict(measured_core)
        try:
            statement_parser = reference["census_method"]["executable_statement_parser"]
            runtime_dependencies = reference["reference_runtime_dependencies"]
            reference_toolchain = reference["reference_toolchain"]
        except (KeyError, TypeError):
            raise RuntimeError("committed reference census has invalid environment evidence") from None
        if (
                type(statement_parser) is not str
                or type(runtime_dependencies) is not list
                or type(reference_toolchain) is not dict
        ):
            raise RuntimeError("committed reference census has invalid environment evidence")

    core = [
        _source_entry(
            repository,
            path,
            role,
            reference_statement_count=core_counts[path],
        )
        for path, role in CORE_SOURCES
    ]
    legacy = _source_entry(
        repository,
        *LEGACY_SOURCE,
        reference_statement_count=legacy_count,
    )
    embedded_driver = _embedded_driver(
        repository,
        reference_statement_count=driver_count,
    )
    tool_raw = Path(__file__).read_bytes()
    r1_bundle = repository / "cisco_toolkit/data/atlas-r1-source-bundle.json"
    r1_manifest = json.loads(
        (repository / "cisco_toolkit/data/atlas-r1-executable-bundle.json").read_bytes()
    )
    prototype = _prototype_evidence(repository)
    return _canonical({
        "budget_gate": {
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
        },
        "census_method": {
            "executable_statement_parser": statement_parser,
            "generator_bytes": len(tool_raw),
            "generator_path": "tools/census_transition_tcb.py",
            "generator_sha256": _digest(tool_raw),
            "measurement_scope": (
                "REFERENCE_ENVIRONMENT_OBSERVATION_WITH_PORTABLE_SOURCE_DIGEST_CHECK"
            ),
            "schema": "atlas.python-executable-statement-census/1",
        },
        "conditional_legacy_replay_tcb": {
            "adapter_source": legacy,
            "embedded_driver": embedded_driver,
            "source_bundle_bytes": r1_bundle.stat().st_size,
            "source_bundle_file_count": r1_manifest["source_bundle_file_count"],
            "source_bundle_path": "cisco_toolkit/data/atlas-r1-source-bundle.json",
            "source_bundle_sha256": _digest(r1_bundle.read_bytes()),
        },
        "executable_prototype": prototype,
        "implemented_guard_constants": {
            "canonical_json": {
                "max_bytes": 8 * 1024 * 1024,
                "max_depth": 64,
                "max_nodes": 100_000,
                "max_string_bytes": 1 * 1024 * 1024,
                "state": "PROVISIONAL_NOT_PACK_QUALIFICATION_BUDGET",
            },
            "content_set": {
                "max_objects": 10_000,
                "max_single_object_bytes": 64 * 1024 * 1024,
                "max_total_bytes": 256 * 1024 * 1024,
                "state": "PROVISIONAL_NOT_PACK_QUALIFICATION_BUDGET",
            },
            "dsl_prototype": {
                **{
                    field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
                    for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
                },
                "profile": "DEFAULT_DSL_PROTOTYPE_LIMITS",
                "state": "PROVISIONAL_MEASURED_NOT_REVIEWED_BUDGET",
            },
            "legacy_replay": {
                "max_json_bytes": 64 * 1024 * 1024,
                "max_request_bytes": 192 * 1024 * 1024,
                "max_stdout_bytes": 4 * 1024 * 1024,
                "timeout_seconds": 60,
                "state": "CONDITIONAL_AUDIT_ONLY_RUNTIME_GUARDS",
            },
        },
        "independent_review": {
            "result": "PENDING_BOUND_INDEPENDENT_REVIEW_EVIDENCE",
            "review_evidence": None,
            "required_next_evidence": [
                "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY",
                "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
                "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE",
                "APPROVED_REVIEW_POLICY_AND_TRUSTED_KEY_CUSTODY",
                "SIGNED_REVIEW_RECEIPT_BOUND_TO_SELECTED_COMMIT_TREE_CENSUS_AND_MEASUREMENTS",
                "SELECTED_COMMIT_BINDING",
            ],
        },
        "reference_runtime_dependencies": runtime_dependencies,
        "reference_toolchain": reference_toolchain,
        "release3_included": False,
        "repository_basis": {
            "selected_commit": None,
            "source_basis_parent_sha": SOURCE_BASIS_PARENT_SHA,
            "state": "EXACT_INPUT_DIGESTS_AWAIT_EXTERNAL_SELECTED_COMMIT_BINDING",
        },
        "schema": SCHEMA,
        "structural_core": {
            "executable_statements": sum(item["executable_statements"] for item in core),
            "sources": core,
        },
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true")
    mode.add_argument("--reference-check", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    target = repository / "cisco_toolkit/data" / RESOURCE
    if args.update or args.reference_check:
        generated = _build(repository)
    else:
        if not target.is_file():
            raise RuntimeError("Atlas R2 structural TCB census is missing")
        try:
            reference = json.loads(target.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError, MemoryError):
            raise RuntimeError("Atlas R2 structural TCB census is unreadable") from None
        if type(reference) is not dict:
            raise RuntimeError("Atlas R2 structural TCB census is not an object")
        generated = _build(repository, reference=reference)
    if args.update:
        target.write_bytes(generated)
        return 0
    if not target.is_file() or target.read_bytes() != generated:
        raise RuntimeError("Atlas R2 structural TCB census drifted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
