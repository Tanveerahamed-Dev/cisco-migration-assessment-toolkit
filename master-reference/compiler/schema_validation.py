"""Validate emitted Atlas compiler artifacts against tracked JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from .graphify import GraphifyFailure, validate_graphify_metadata


class SchemaValidationError(RuntimeError):
    """An emitted compiler artifact differs from its tracked schema."""


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise SchemaValidationError(f"expected JSON object: {path.name}")
    return value


def _validate_schema(
    validator: Draft202012Validator,
    value: dict[str, Any],
    label: str,
) -> None:
    try:
        validator.validate(value)
    except ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise SchemaValidationError(
            f"{label} differs from its tracked schema at {location}: {exc.message}"
        ) from exc


def validate_compiler_output(output: Path, schema_root: Path | None = None) -> dict[str, int]:
    output = output.resolve(strict=True)
    schema_root = (schema_root or Path(__file__).resolve().parent.parent / "schema").resolve(strict=True)
    schemas = {
        path.name: _read_object(path)
        for path in sorted(schema_root.glob("*.schema.json"))
    }
    required = {
        "manifest.schema.json",
        "completeness-ledger.schema.json",
        "atlas-records.schema.json",
        "graphify-metadata.schema.json",
    }
    if not required.issubset(schemas):
        raise SchemaValidationError(f"missing tracked schemas: {sorted(required - set(schemas))}")
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    completeness = _read_object(output / "completeness.json")
    _validate_schema(
        Draft202012Validator(schemas["completeness-ledger.schema.json"], registry=registry),
        completeness,
        "completeness.json",
    )
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise SchemaValidationError(
            "compiler output has no manifest.json; a failure ledger is not a publishable schema-validated corpus"
        )
    manifest = _read_object(manifest_path)
    _validate_schema(
        Draft202012Validator(schemas["manifest.schema.json"], registry=registry),
        manifest,
        "manifest.json",
    )
    graphify = _read_object(output / "graphify-metadata.json")
    _validate_schema(
        Draft202012Validator(schemas["graphify-metadata.schema.json"], registry=registry),
        graphify,
        "graphify-metadata.json",
    )
    try:
        validate_graphify_metadata(graphify)
    except GraphifyFailure as exc:
        raise SchemaValidationError(
            f"graphify-metadata.json fails disposition reconciliation: {exc}"
        ) from exc
    record_validator = Draft202012Validator(schemas["atlas-records.schema.json"], registry=registry)
    chunks = 0
    for chunk in sorted((output / "chunks").rglob("*.json")):
        _validate_schema(record_validator, _read_object(chunk), chunk.relative_to(output).as_posix())
        chunks += 1
    expected_chunks = sum(int(group.get("chunk_count", 0)) for group in manifest["groups"].values())
    if chunks != expected_chunks:
        raise SchemaValidationError(f"schema-validation chunk census mismatch: expected {expected_chunks}, found {chunks}")
    return {"manifest": 1, "completeness": 1, "graphify_metadata": 1, "chunks": chunks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Atlas compiler output against tracked schemas")
    parser.add_argument("--input", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = validate_compiler_output(arguments.input)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
