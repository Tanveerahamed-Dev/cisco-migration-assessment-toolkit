"""Fail-closed JSON Schema validation for release contracts and ledgers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import ReleaseInputError, read_bytes


SCHEMAS = {
    "output-contract": "output-contract.schema.json",
    "artifact-inventory": "artifact-inventory.schema.json",
    "preservation-coverage": "preservation-coverage.schema.json",
    "family-attestation": "family-attestation.schema.json",
    "release-manifest": "release-manifest.schema.json",
}


def validate_release_object(repo_root: Path, schema_name: str, value: Any) -> None:
    filename = SCHEMAS.get(schema_name)
    if filename is None:
        raise ReleaseInputError(f"unknown release schema: {schema_name}")
    relative = f"master-reference/release/schemas/{filename}"
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
