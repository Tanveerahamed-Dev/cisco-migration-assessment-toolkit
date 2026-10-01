"""Validate emitted Atlas compiler artifacts against tracked JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from atlas_privacy import FORBIDDEN_CONTENT_RULES
from .graphify import GraphifyFailure, validate_graphify_metadata
from .policy import (
    CENSUS_DEPTH_FULL,
    CENSUS_DEPTH_IDENTITY,
    CENSUS_DEPTH_POLICY_OWNER,
    IDENTITY_DEPTH_DEFERRED_GROUPS,
    IDENTITY_DEPTH_RETAINED_GROUPS,
    census_depth_decision,
    census_depth_declaration_receipts,
    validate_census_depth_declarations,
)


class SchemaValidationError(RuntimeError):
    """An emitted compiler artifact differs from its tracked schema."""


class ForbiddenContentScanValidationError(RuntimeError):
    """The compiler privacy scan cannot support a downstream pass claim."""


class CensusDepthValidationError(RuntimeError):
    """A file's census depth differs from the single tracked policy owner."""


_CENSUS_DEPTH_STATIC_KEYS = ("prefix", "census_depth", "reason", "block_category", "follow_up_owner")


def validate_census_depth_receipt(
    completeness: dict[str, Any],
    file_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rejoin every file's census depth and the ledger receipt to the policy owner.

    The policy (``compiler.policy.CENSUS_DEPTH_DECLARATIONS``) is the only
    place a prefix can be censused below full depth.  A file whose recorded
    depth or reason differs from it, a receipt whose declarations differ from
    it, or counts that do not reconcile, is refused -- a downstream consumer
    can therefore never present an identity-depth file as line-covered nor a
    full-depth file as deferred.
    """

    message = "compiler census-depth receipt differs from the tracked policy owner"
    if validate_census_depth_declarations():
        raise CensusDepthValidationError(message)
    receipt = completeness.get("census_depth")
    if type(receipt) is not dict or type(file_records) is not list:
        raise CensusDepthValidationError(message)
    identity: list[dict[str, Any]] = []
    full = 0
    for record in file_records:
        if type(record) is not dict or type(record.get("path")) is not str:
            raise CensusDepthValidationError(message)
        depth, reason = census_depth_decision(record["path"])
        if record.get("census_depth") != depth or record.get("census_depth_reason") != reason:
            raise CensusDepthValidationError(message)
        if depth == CENSUS_DEPTH_IDENTITY:
            identity.append(record)
            if record.get("parse_status") == "parsed":
                raise CensusDepthValidationError(message)
        elif depth == CENSUS_DEPTH_FULL:
            full += 1
            if record.get("parse_status") == "identity_census":
                raise CensusDepthValidationError(message)
    declarations = receipt.get("declarations")
    policy_rows = census_depth_declaration_receipts()
    if (
        receipt.get("policy_owner") != CENSUS_DEPTH_POLICY_OWNER
        or type(declarations) is not list
        or len(declarations) != len(policy_rows)
        or any(
            type(row) is not dict or {key: row.get(key) for key in _CENSUS_DEPTH_STATIC_KEYS} != policy
            for row, policy in zip(declarations, policy_rows)
        )
        or receipt.get("identity_depth_files") != len(identity)
        or receipt.get("full_depth_files") != full
        or receipt.get("retained_record_groups") != list(IDENTITY_DEPTH_RETAINED_GROUPS)
        or receipt.get("deferred_record_groups") != list(IDENTITY_DEPTH_DEFERRED_GROUPS)
        or receipt.get("status") != ("identity_depth_deferred" if identity else "full_depth")
    ):
        raise CensusDepthValidationError(message)
    active: set[str] = set()
    for row in declarations:
        members = [record for record in identity if str(record["path"]).startswith(str(row["prefix"]))]
        if row.get("tracked_files") != len(members):
            raise CensusDepthValidationError(message)
        text_members = [
            record
            for record in members
            if record.get("privacy_exposure") == "full"
            and record.get("language") != "binary"
            and type(record.get("content_digest")) is str
        ]
        if (
            row.get("text_files") != len(text_members)
            or row.get("privacy_scanned_text_files") != len(text_members)
            or row.get("deferred_nonblank_lines")
            != sum(int(record.get("nonblank_line_count") or 0) for record in text_members)
        ):
            raise CensusDepthValidationError(message)
        if members:
            active.add(str(row["block_category"]))
    if receipt.get("block_categories") != sorted(active):
        raise CensusDepthValidationError(message)
    return receipt


FORBIDDEN_CONTENT_SCAN_SCOPE = "allowlisted_utf8_text_payloads_only"
FORBIDDEN_CONTENT_SCAN_RULES = tuple(name for name, _pattern in FORBIDDEN_CONTENT_RULES)
_FORBIDDEN_CONTENT_SCAN_KEYS = frozenset(
    {
        "status",
        "scope",
        "eligible_text_files",
        "scanned_text_files",
        "rules",
        "findings_count",
        "findings",
        "matched_values_retained",
        "unresolved_reasons",
    }
)


def validate_passed_forbidden_content_scan(
    completeness: dict[str, Any],
    file_records: list[dict[str, Any]],
) -> int:
    """Reconcile a PASS claim against the independently loaded file denominator."""

    privacy = completeness.get("privacy")
    scan = privacy.get("forbidden_content_scan") if type(privacy) is dict else None
    if type(scan) is not dict or set(scan) != _FORBIDDEN_CONTENT_SCAN_KEYS:
        raise ForbiddenContentScanValidationError(
            "compiler forbidden-content scan is absent, malformed, incomplete, or failed"
        )
    eligible = 0
    if type(file_records) is not list:
        raise ForbiddenContentScanValidationError(
            "compiler forbidden-content scan is absent, malformed, incomplete, or failed"
        )
    for record in file_records:
        if type(record) is not dict or type(record.get("classification_errors")) is not list:
            raise ForbiddenContentScanValidationError(
                "compiler forbidden-content scan is absent, malformed, incomplete, or failed"
            )
        if (
            record.get("privacy_exposure") == "full"
            and record.get("language") != "binary"
            and type(record.get("content_digest")) is str
        ):
            eligible += 1
    if (
        scan.get("status") != "passed"
        or scan.get("scope") != FORBIDDEN_CONTENT_SCAN_SCOPE
        or type(scan.get("eligible_text_files")) is not int
        or scan["eligible_text_files"] != eligible
        or type(scan.get("scanned_text_files")) is not int
        or scan["scanned_text_files"] != eligible
        or type(scan.get("rules")) is not list
        or tuple(scan["rules"]) != FORBIDDEN_CONTENT_SCAN_RULES
        or type(scan.get("findings_count")) is not int
        or scan["findings_count"] != 0
        or type(scan.get("findings")) is not list
        or scan["findings"]
        or scan.get("matched_values_retained") is not False
        or type(scan.get("unresolved_reasons")) is not list
        or scan["unresolved_reasons"]
    ):
        raise ForbiddenContentScanValidationError(
            "compiler forbidden-content scan is absent, malformed, incomplete, or failed"
        )
    return eligible


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
    file_records: list[dict[str, Any]] = []
    for chunk in sorted((output / "chunks").rglob("*.json")):
        envelope = _read_object(chunk)
        _validate_schema(record_validator, envelope, chunk.relative_to(output).as_posix())
        if envelope.get("record_type") == "files" and type(envelope.get("records")) is list:
            file_records.extend(envelope["records"])
        chunks += 1
    expected_chunks = sum(int(group.get("chunk_count", 0)) for group in manifest["groups"].values())
    if chunks != expected_chunks:
        raise SchemaValidationError(f"schema-validation chunk census mismatch: expected {expected_chunks}, found {chunks}")
    try:
        validate_passed_forbidden_content_scan(completeness, file_records)
    except ForbiddenContentScanValidationError as exc:
        raise SchemaValidationError(str(exc)) from None
    try:
        validate_census_depth_receipt(completeness, file_records)
    except CensusDepthValidationError as exc:
        raise SchemaValidationError(str(exc)) from None
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
