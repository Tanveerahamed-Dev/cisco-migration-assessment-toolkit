#!/usr/bin/env python3
"""Fail-closed owner for the installed transition-runtime smoke.

The workflow provisions the pinned environment and copies the smoke outside the
checkout.  This owner executes that copy with the pinned interpreter, propagates
its failure, and refuses a vacuous zero exit that lacks the smoke's receipt.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


_FAILURE_EXIT = 2
_SMOKE_TIMEOUT_SECONDS = 600
_REQUIRED_RECEIPT_VALUES = {
    "dsl_prototype_source_binding_state": "SAME_CHECKOUT_SELF_CHECK_ONLY",
    "dsl_temporal_truth": "INCONCLUSIVE",
    "historical_source_roster_verified": False,
    "r2_authoritative_gate": None,
    "r2_promotion_eligible": False,
    "replay_state": "CANONICAL_SEMANTIC_PAYLOAD_IDENTICAL",
    "runtime_matches_reference": True,
    "structural_tcb_budget_state": (
        "PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
    ),
}
_REQUIRED_DIGEST_FIELDS = (
    "before_digest",
    "dsl_prototype_evaluate_digest",
    "dsl_prototype_replay_digest",
    "executable_bundle_digest",
    "measurement_digest",
    "qcp_digest",
    "replayed_payload_digest",
    "runtime_inventory_digest",
    "runtime_profile_digest",
    "semantic_bundle_digest",
    "v5_environment_schema_digest",
    "v5_runtime_schema_digest",
)
_REQUIRED_RECEIPT_FIELDS = frozenset(
    {
        *_REQUIRED_RECEIPT_VALUES,
        *_REQUIRED_DIGEST_FIELDS,
        "distribution_version",
        "module_path",
        "runtime_inventory_file_count",
        "v5_validator_empty_artifacts_refused",
    }
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_SMOKE_RELATIVE = Path("tools", "smoke_installed_transition_runtime.py")


class SmokeOwnershipError(RuntimeError):
    """The installed-runtime execution contract was not established."""


def _existing_path(value: str | os.PathLike[str], *, label: str, kind: str) -> Path:
    try:
        resolved = Path(value).resolve(strict=True)
    except OSError as exc:
        raise SmokeOwnershipError(f"{label} does not exist: {value}") from exc
    if kind == "file" and not resolved.is_file():
        raise SmokeOwnershipError(f"{label} is not a file: {resolved}")
    if kind == "directory" and not resolved.is_dir():
        raise SmokeOwnershipError(f"{label} is not a directory: {resolved}")
    return resolved


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise SmokeOwnershipError(
                f"installed-runtime smoke receipt repeats JSON key: {key}"
            )
        value[key] = item
    return value


def _receipt(stdout: str, *, workspace: Path) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise SmokeOwnershipError("installed-runtime smoke returned zero without a receipt")
    try:
        value = json.loads(lines[-1], object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise SmokeOwnershipError(
            "installed-runtime smoke did not end with a JSON receipt"
        ) from exc
    if type(value) is not dict:
        raise SmokeOwnershipError("installed-runtime smoke receipt is not an object")

    fields = set(value)
    if fields != _REQUIRED_RECEIPT_FIELDS:
        raise SmokeOwnershipError(
            "installed-runtime smoke receipt fields drifted: "
            f"missing={sorted(_REQUIRED_RECEIPT_FIELDS - fields)}, "
            f"unexpected={sorted(fields - _REQUIRED_RECEIPT_FIELDS)}"
        )

    drifted = {
        field: value.get(field)
        for field, expected in _REQUIRED_RECEIPT_VALUES.items()
        if type(value.get(field)) is not type(expected) or value.get(field) != expected
    }
    if drifted:
        raise SmokeOwnershipError(
            f"installed-runtime smoke receipt lost required invariants: {drifted}"
        )

    malformed_digests = [
        field
        for field in _REQUIRED_DIGEST_FIELDS
        if not isinstance(value.get(field), str) or not _SHA256.fullmatch(value[field])
    ]
    if malformed_digests:
        raise SmokeOwnershipError(
            "installed-runtime smoke receipt lost digest bindings: "
            f"{malformed_digests}"
        )

    if not isinstance(value.get("distribution_version"), str) or not value[
        "distribution_version"
    ]:
        raise SmokeOwnershipError(
            "installed-runtime smoke receipt lacks the distribution version"
        )
    if type(value.get("runtime_inventory_file_count")) is not int or value[
        "runtime_inventory_file_count"
    ] <= 0:
        raise SmokeOwnershipError(
            "installed-runtime smoke receipt lacks a positive runtime inventory count"
        )
    if value.get("v5_validator_empty_artifacts_refused") is not True:
        raise SmokeOwnershipError(
            "installed-runtime smoke receipt lacks the fail-closed validator witness"
        )

    module_path = value.get("module_path")
    if not isinstance(module_path, str) or not module_path:
        raise SmokeOwnershipError("installed-runtime smoke receipt lacks its module origin")
    module = _existing_path(module_path, label="receipt module origin", kind="file")
    if _inside(module, workspace):
        raise SmokeOwnershipError(
            f"installed-runtime smoke receipt names a checkout module: {module}"
        )
    return value


def run_smoke(
    python: str | os.PathLike[str],
    smoke: str | os.PathLike[str],
    source_smoke: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout_seconds: int = _SMOKE_TIMEOUT_SECONDS,
) -> int:
    """Execute the installed smoke and validate its fail-closed receipt contract."""

    workspace_path = _existing_path(workspace, label="workspace", kind="directory")
    python_path = _existing_path(python, label="pinned interpreter", kind="file")
    smoke_path = _existing_path(smoke, label="installed-runtime smoke", kind="file")
    source_smoke_path = _existing_path(
        source_smoke,
        label="reviewed installed-runtime smoke source",
        kind="file",
    )
    cwd_path = _existing_path(cwd or Path.cwd(), label="smoke cwd", kind="directory")

    expected_source_smoke = (workspace_path / _SOURCE_SMOKE_RELATIVE).resolve(strict=True)
    if (
        source_smoke_path != expected_source_smoke
        or not _inside(source_smoke_path, workspace_path)
    ):
        raise SmokeOwnershipError(
            "reviewed installed-runtime smoke source is not the owned checkout path: "
            f"{source_smoke_path}"
        )
    try:
        source_bytes = source_smoke_path.read_bytes()
        copied_bytes = smoke_path.read_bytes()
    except OSError as exc:
        raise SmokeOwnershipError(
            f"installed-runtime smoke bytes could not be read: {exc}"
        ) from exc
    if copied_bytes != source_bytes:
        raise SmokeOwnershipError(
            "outside-checkout smoke bytes differ from the reviewed checkout source"
        )

    for label, path in (
        ("pinned interpreter", python_path),
        ("installed-runtime smoke", smoke_path),
        ("smoke cwd", cwd_path),
    ):
        if _inside(path, workspace_path):
            raise SmokeOwnershipError(f"{label} must remain outside the checkout: {path}")
    if type(timeout_seconds) is not int or timeout_seconds <= 0:
        raise SmokeOwnershipError("installed-runtime smoke timeout must be a positive integer")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(workspace_path)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [str(python_path), "-I", "-B", str(smoke_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            sys.stdout.write(
                exc.stdout.decode(errors="replace")
                if isinstance(exc.stdout, bytes)
                else exc.stdout
            )
        if exc.stderr:
            sys.stderr.write(
                exc.stderr.decode(errors="replace")
                if isinstance(exc.stderr, bytes)
                else exc.stderr
            )
        raise SmokeOwnershipError(
            f"installed-runtime smoke exceeded {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise SmokeOwnershipError(f"installed-runtime smoke could not start: {exc}") from exc

    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        return completed.returncode if completed.returncode > 0 else _FAILURE_EXIT
    _receipt(completed.stdout, workspace=workspace_path)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--smoke", required=True)
    parser.add_argument("--source-smoke", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_smoke(args.python, args.smoke, args.source_smoke, args.workspace)
    except SmokeOwnershipError as exc:
        print(f"installed-runtime smoke ownership failed: {exc}", file=sys.stderr)
        return _FAILURE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
