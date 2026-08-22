"""Check or rebuild the machine-generated Atlas R2 structural TCB census.

This census measures the implemented structural prototype. It deliberately does not fabricate the
pack SLOC budget or DSL/Wasm resource ceilings that require a real executable pack prototype and
independent review under the governing Release 2 strategy.  The default check is portable: it
reuses the committed reference environment's statement counts and dependency/toolchain observations
while recomputing every source byte count and digest. ``--reference-check`` recomputes the complete
measurement and is expected to pass only in the exact recorded reference environment.
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


SCHEMA = "atlas.structural-tcb-census/1"
RESOURCE = "atlas-r2-structural-tcb-census.v1.json"
SOURCE_BASIS_PARENT_SHA = "935213e8babc6fde555627eaa434749397a1617d"
CORE_SOURCES = (
    ("cisco_toolkit/transition_contract.py", "STRUCTURAL_CONTRACT_AND_CANONICAL_CODEC"),
    ("cisco_toolkit/transition_pack.py", "PACK_ABI_TCB_AND_QUALIFICATION_BOUNDARY"),
    ("cisco_toolkit/transition_verifier.py", "STRUCTURAL_VERIFIER_AND_GATE_MAPPING"),
)
LEGACY_SOURCE = ("cisco_toolkit/transition_legacy.py", "CONDITIONAL_RELEASE1_REPLAY_ADAPTER")
REFERENCE_DISTRIBUTIONS = ("coverage", "cryptography", "cffi", "pycparser")


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
    return _canonical({
        "budget_gate": {
            "budget_state": "PENDING_EXECUTABLE_PACK_PROTOTYPE_AND_INDEPENDENT_REVIEW",
            "core_sloc_budget": None,
            "pack_resource_ceilings": None,
            "pack_sloc_budget": None,
            "promotion_effect": "BLOCKS_R2_0_COMPLETION",
            "reason": (
                "QCP-001 is CONTRACT_ONLY and no executable DSL/Wasm prototype exists; numeric "
                "pack budgets or enforcement ceilings would be invented rather than measured."
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
                "EXECUTABLE_DSL_OR_WASM_PROTOTYPE",
                "MEASURED_N_MINUS_1_N_N_PLUS_1_RESOURCE_LIMIT_TESTS",
                "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
                "SIGNED_REVIEW_RECEIPT_BOUND_TO_THIS_CENSUS_DIGEST",
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
