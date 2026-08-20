"""Fail-closed JSON Schema validation for release contracts and ledgers."""

from __future__ import annotations

import json
import re
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
    "rendered-sink-lineage-core-contract": "master-reference/schema/rendered-sink-lineage-core.schema.json",
    "artifact-inventory": "master-reference/release/schemas/artifact-inventory.schema.json",
    "preservation-coverage": "master-reference/release/schemas/preservation-coverage.schema.json",
    "family-attestation": "master-reference/release/schemas/family-attestation.schema.json",
    "release-manifest": "master-reference/release/schemas/release-manifest.schema.json",
    "authenticated-review-signature": (
        "master-reference/release/schemas/authenticated-review-signature.schema.json"
    ),
    "reviewer-key-policy": "master-reference/release/schemas/reviewer-key-policy.schema.json",
    "consequential-claim-review": (
        "master-reference/release/schemas/consequential-claim-review.schema.json"
    ),
    "authenticated-review-result": (
        "master-reference/release/schemas/authenticated-review-result.schema.json"
    ),
    "pdf-review": "master-reference/release/schemas/pdf-review.schema.json",
    "pdf-review-signature": (
        "master-reference/release/schemas/pdf-review-signature.schema.json"
    ),
    "pdf-reviewer-key-policy": (
        "master-reference/release/schemas/pdf-reviewer-key-policy.schema.json"
    ),
    "pdf-review-result": "master-reference/release/schemas/pdf-review-result.schema.json",
}

_MAX_JSON_DEPTH = 64
_MAX_JSON_VALUES = 1_000_000
_MAX_JSON_CONTAINER_ITEMS = 100_000
_MAX_JSON_STRING_LENGTH = 1_048_576
_MAX_PORTABLE_INTEGER = 9_007_199_254_740_991

_PDF_GATE_LINEAGE_SOURCE_OIDS = (
    ("rendered_sink_lineage", "ed375f35a60b7eb4cc5719223b5c349fd2bddba2", False),
    ("capability_sink_lineage", "19312d959afd79e0ae91330f6b864e0bcfba0456", False),
    ("core_sink_lineage", "27b7c166a78894d957bd3f35b5f64170dd11afb4", True),
)
_PDF_GATE_MECHANICAL_OBSERVATION_DIGESTS = (
    (
        "horizon_sink_mechanical_verification",
        "f7336194e83f235a9474fcef03248d95bff60c8dbc588cd5275e71244e3805c4",
    ),
    (
        "capability_sink_mechanical_verification",
        "afee08dec849ca72dad14a40790735337fc151dc721836ce2fc1a2a980ea5b15",
    ),
    (
        "core_sink_mechanical_verification",
        "bb4afeb3578abe796e7bbc01ecfa07272e311e68a5b1c6a77ead3c2fbbb24d47",
    ),
)
_PDF_GATE_OBSERVED_RECEIPT_DIGESTS = (
    ("rendered_sink_lineage", "7ef64012f0c22920149875e1ab0f92535bfebd118b65add09594ce6a6865cdeb"),
    ("capability_sink_lineage", "3c293e70426b4579b73530fa2944cdc856b479805579850ef3d1f9968519d931"),
    ("core_sink_lineage", "95d901997eb6aa9fd61ac768ab29fc6c3f2fb1118b4d5e1ee01286029d76f469"),
)
_GENERATED_PDF_PROVENANCE_FIELDS = (
    "sha256",
    "bytes",
    "page_count",
    "input_digest",
    "renderer",
)


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = item
    return result


def _reject_json_number(_value: str) -> None:
    raise ValueError


def _load_schema(raw: bytes, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_number,
            parse_float=_reject_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise ReleaseInputError(f"release schema is invalid UTF-8 JSON: {relative}") from None
    if type(value) is not dict:
        raise ReleaseInputError(f"release schema is invalid UTF-8 JSON: {relative}")
    _validate_plain_json_tree(value, "tracked-schema")
    return value


def _read_schema(repo_root: Path, relative: str) -> bytes:
    try:
        return read_bytes(repo_root, relative)
    except Exception:
        raise ReleaseInputError(f"release schema could not be read: {relative}") from None


def _portable_string(value: str) -> bool:
    if len(value) > _MAX_JSON_STRING_LENGTH:
        return False
    for character in value:
        point = ord(character)
        if (
            point <= 0x1F
            or 0x7F <= point <= 0x9F
            or 0xD800 <= point <= 0xDFFF
            or 0xFDD0 <= point <= 0xFDEF
            or point & 0xFFFF >= 0xFFFE
            or point == 0x061C
            or point in {0x200E, 0x200F}
            or 0x202A <= point <= 0x202E
            or 0x2066 <= point <= 0x2069
        ):
            return False
    return True


def _validate_plain_json_tree(value: Any, schema_name: str) -> None:
    """Reject hostile or non-portable values before invoking jsonschema."""

    failure = f"release object is not bounded plain JSON: {schema_name}"
    try:
        stack: list[tuple[Any, int]] = [(value, 1)]
        count = 0
        while stack:
            current, depth = stack.pop()
            count += 1
            if count > _MAX_JSON_VALUES or depth > _MAX_JSON_DEPTH:
                raise ReleaseInputError(failure)
            if type(current) is dict:
                if len(current) > _MAX_JSON_CONTAINER_ITEMS:
                    raise ReleaseInputError(failure)
                keys = tuple(current)
                if any(type(key) is not str or not _portable_string(key) for key in keys):
                    raise ReleaseInputError(failure)
                stack.extend((item, depth + 1) for item in current.values())
            elif type(current) is list:
                if len(current) > _MAX_JSON_CONTAINER_ITEMS:
                    raise ReleaseInputError(failure)
                stack.extend((item, depth + 1) for item in current)
            elif type(current) is str:
                if not _portable_string(current):
                    raise ReleaseInputError(failure)
            elif current is None or type(current) is bool:
                continue
            elif type(current) is int:
                if not -_MAX_PORTABLE_INTEGER <= current <= _MAX_PORTABLE_INTEGER:
                    raise ReleaseInputError(failure)
            else:
                raise ReleaseInputError(failure)
    except ReleaseInputError:
        raise
    except Exception:
        raise ReleaseInputError(failure) from None


def validate_release_object(
    repo_root: Path,
    schema_name: str,
    value: Any,
    *,
    pdf_provenance: Any = None,
) -> None:
    """Validate one release object; generated PDFs require caller-owned provenance."""

    if type(schema_name) is not str:
        raise ReleaseInputError("unknown release schema")
    relative = SCHEMAS.get(schema_name)
    if relative is None:
        raise ReleaseInputError("unknown release schema")
    _validate_plain_json_tree(value, schema_name)
    schema = _load_schema(_read_schema(repo_root, relative), relative)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - pinned release dependency
        raise ReleaseInputError("jsonschema is required for release contract validation") from exc
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    except Exception:
        raise ReleaseInputError(f"release schema could not be evaluated: {schema_name}") from None
    if errors:
        first = errors[0]
        keyword = first.validator if type(first.validator) is str and first.validator.isidentifier() else "constraint"
        raise ReleaseInputError(f"release object fails {schema_name} schema validation ({keyword})")
    if schema_name == "pdf-gate" and isinstance(value, dict):
        generated = value["status"] == "generated_visual_review_pending"
        for lineage_name, expected_source_oid, always_bind_source in _PDF_GATE_LINEAGE_SOURCE_OIDS:
            lineage = value[lineage_name]
            receipt_digest = lineage["sink_receipts_digest"]
            if type(receipt_digest) is not str or receipt_digest != sha256_bytes(
                canonical_json(lineage["sink_receipts"])
            ):
                raise ReleaseInputError("release object fails pdf-gate sink receipt digest binding")
            lineage_state = lineage["state"]
            source_oid = lineage["source"]["git_blob_oid"]
            exact_source_required = lineage_state == "declared_incomplete" or always_bind_source or generated
            if type(lineage_state) is not str or (
                exact_source_required
                and (type(source_oid) is not str or source_oid != expected_source_oid)
            ) or (
                not exact_source_required
                and source_oid is not None
                and (type(source_oid) is not str or source_oid != expected_source_oid)
            ):
                raise ReleaseInputError("release object fails pdf-gate declared lineage source binding")
    if schema_name == "pdf-gate" and isinstance(value, dict) and value.get("status") == "generated_visual_review_pending":
        provenance_failure = "release object has no valid independent generated PDF provenance"
        try:
            _validate_plain_json_tree(pdf_provenance, "pdf-gate-provenance")
            if type(pdf_provenance) is not dict or set(pdf_provenance) != set(
                _GENERATED_PDF_PROVENANCE_FIELDS
            ):
                raise ReleaseInputError(provenance_failure)
            if (
                type(pdf_provenance["sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", pdf_provenance["sha256"]) is None
                or type(pdf_provenance["bytes"]) is not int
                or pdf_provenance["bytes"] < 8
                or type(pdf_provenance["page_count"]) is not int
                or pdf_provenance["page_count"] < 1
                or type(pdf_provenance["input_digest"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", pdf_provenance["input_digest"]) is None
                or type(pdf_provenance["renderer"]) is not str
                or not pdf_provenance["renderer"]
                or len(pdf_provenance["renderer"]) > 2048
            ):
                raise ReleaseInputError(provenance_failure)
        except ReleaseInputError:
            raise ReleaseInputError(provenance_failure) from None
        except Exception:
            raise ReleaseInputError(provenance_failure) from None
        if any(value[field] != pdf_provenance[field] for field in _GENERATED_PDF_PROVENANCE_FIELDS):
            raise ReleaseInputError("release object fails pdf-gate generated PDF provenance binding")
        top_digest = value.get("sha256")
        horizon = value.get("horizon_sink_mechanical_verification")
        capability = value.get("capability_sink_mechanical_verification")
        core = value.get("core_sink_mechanical_verification")
        if (
            not isinstance(horizon, dict)
            or not isinstance(capability, dict)
            or not isinstance(core, dict)
            or horizon.get("pdf_sha256") != top_digest
            or capability.get("pdf_sha256") != top_digest
            or core.get("pdf_sha256") != top_digest
        ):
            raise ReleaseInputError("release object fails pdf-gate cross-field PDF digest binding")
        for verification_name, expected_observation_digest in _PDF_GATE_MECHANICAL_OBSERVATION_DIGESTS:
            if value[verification_name]["observation_digest"] != expected_observation_digest:
                raise ReleaseInputError("release object fails pdf-gate mechanical observation digest binding")
        for lineage_name, expected_receipt_digest in _PDF_GATE_OBSERVED_RECEIPT_DIGESTS:
            lineage = value[lineage_name]
            if lineage["observed_sink_count"] == 1 and sha256_bytes(
                canonical_json(lineage["sink_receipts"][0])
            ) != expected_receipt_digest:
                raise ReleaseInputError("release object fails pdf-gate observed PDF sink receipt binding")
        for verification in (horizon, capability, core):
            material = {
                "verdict": verification["verdict"],
                "pdf_sha256": verification["pdf_sha256"],
                "observation_digest": verification["observation_digest"],
                "rendered_observation_count": verification["rendered_observation_count"],
                "safety_observation_count": verification["safety_observation_count"],
            }
            if verification["verification_digest"] != sha256_bytes(canonical_json(material)):
                raise ReleaseInputError("release object fails pdf-gate mechanical verification digest binding")
