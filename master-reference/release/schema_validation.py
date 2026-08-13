"""Fail-closed JSON Schema validation for release contracts and ledgers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import ReleaseInputError, read_bytes


SCHEMAS = {
    "output-contract": "master-reference/release/schemas/output-contract.schema.json",
    "pdf-gate": "master-reference/release/schemas/pdf-gate.schema.json",
    "rendered-sink-lineage-contract": "master-reference/schema/rendered-sink-lineage.schema.json",
    "artifact-inventory": "master-reference/release/schemas/artifact-inventory.schema.json",
    "preservation-coverage": "master-reference/release/schemas/preservation-coverage.schema.json",
    "family-attestation": "master-reference/release/schemas/family-attestation.schema.json",
    "release-manifest": "master-reference/release/schemas/release-manifest.schema.json",
}


def validate_release_object(repo_root: Path, schema_name: str, value: Any) -> None:
    relative = SCHEMAS.get(schema_name)
    if relative is None:
        raise ReleaseInputError(f"unknown release schema: {schema_name}")
    try:
        schema = json.loads(read_bytes(repo_root, relative).decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError(f"release schema is invalid UTF-8 JSON: {relative}") from exc
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - pinned release dependency
        raise ReleaseInputError("jsonschema is required for release contract validation") from exc
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    except Exception as exc:
        raise ReleaseInputError(f"release schema could not be evaluated: {schema_name}: {exc}") from exc
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise ReleaseInputError(f"release object fails {schema_name} schema at {location}: {first.message}")
