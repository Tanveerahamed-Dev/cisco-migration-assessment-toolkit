"""Fail-closed JSON Schema validation for release contracts and ledgers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import ReleaseInputError, canonical_json, read_bytes, sha256_bytes


SCHEMAS = {
    "output-contract": "master-reference/release/schemas/output-contract.schema.json",
    "pdf-gate": "master-reference/release/schemas/pdf-gate.schema.json",
    "rendered-sink-lineage-contract": "master-reference/schema/rendered-sink-lineage.schema.json",
    "rendered-sink-lineage-capability-contract": (
        "master-reference/schema/rendered-sink-lineage-capability.schema.json"
    ),
    "artifact-inventory": "master-reference/release/schemas/artifact-inventory.schema.json",
    "preservation-coverage": "master-reference/release/schemas/preservation-coverage.schema.json",
    "family-attestation": "master-reference/release/schemas/family-attestation.schema.json",
    "release-manifest": "master-reference/release/schemas/release-manifest.schema.json",
}

_PDF_GATE_DECLARED_LINEAGE_SOURCE_OIDS = (
    ("rendered_sink_lineage", "ed375f35a60b7eb4cc5719223b5c349fd2bddba2"),
    ("capability_sink_lineage", "19312d959afd79e0ae91330f6b864e0bcfba0456"),
)


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
    if schema_name == "pdf-gate" and isinstance(value, dict):
        for lineage_name, expected_source_oid in _PDF_GATE_DECLARED_LINEAGE_SOURCE_OIDS:
            lineage = value[lineage_name]
            receipt_digest = lineage["sink_receipts_digest"]
            if type(receipt_digest) is not str or receipt_digest != sha256_bytes(
                canonical_json(lineage["sink_receipts"])
            ):
                raise ReleaseInputError("release object fails pdf-gate sink receipt digest binding")
            lineage_state = lineage["state"]
            if (
                type(lineage_state) is not str
                or lineage_state == "declared_incomplete"
                and (
                    type(lineage["source"]["git_blob_oid"]) is not str
                    or lineage["source"]["git_blob_oid"] != expected_source_oid
                )
            ):
                raise ReleaseInputError("release object fails pdf-gate declared lineage source binding")
    if schema_name == "pdf-gate" and isinstance(value, dict) and value.get("status") == "generated_visual_review_pending":
        top_digest = value.get("sha256")
        horizon = value.get("horizon_sink_mechanical_verification")
        capability = value.get("capability_sink_mechanical_verification")
        if (
            not isinstance(horizon, dict)
            or not isinstance(capability, dict)
            or horizon.get("pdf_sha256") != top_digest
            or capability.get("pdf_sha256") != top_digest
        ):
            raise ReleaseInputError("release object fails pdf-gate cross-field PDF digest binding")
        for verification in (horizon, capability):
            material = {
                "verdict": verification["verdict"],
                "pdf_sha256": verification["pdf_sha256"],
                "observation_digest": verification["observation_digest"],
                "rendered_observation_count": verification["rendered_observation_count"],
                "safety_observation_count": verification["safety_observation_count"],
            }
            if verification["verification_digest"] != sha256_bytes(canonical_json(material)):
                raise ReleaseInputError("release object fails pdf-gate mechanical verification digest binding")
