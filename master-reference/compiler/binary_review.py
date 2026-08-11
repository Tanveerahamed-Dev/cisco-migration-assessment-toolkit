"""Fail-closed validation for the tracked repository-binary review receipt.

The compiler's public binary records remain metadata-only.  This module is the
small, bounded exception that reads selected-commit Git blobs solely to
recompute format and privacy evidence joined to an independently authored,
tracked receipt.  Every diagnostic is categorical: untrusted paths, metadata,
and decoded content are never copied into exceptions or compiler ledgers.
"""

from __future__ import annotations

import binascii
import hashlib
import ipaddress
import json
import re
import struct
import zlib
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable, Mapping

from atlas_privacy import forbidden_content_findings, generic_local_identity_rule

from .model import canonical_json, sha256_bytes


RECEIPT_PATH = "master-reference/governance/tracked-binary-review.json"
RECEIPT_SCHEMA_VERSION = "tracked-binary-review/1"
RECEIPT_KIND = "tracked_repository_binary_privacy_review"
PNG_VALIDATOR = "atlas_png_strict/1"
GZIP_TSV_VALIDATOR = "atlas_gzip_tsv_strict/1"

MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_BINARY_BYTES = 512 * 1024 * 1024
MAX_PNG_CHUNK_BYTES = 64 * 1024 * 1024
MAX_PNG_DECODED_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_GZIP_DECOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_TSV_ROWS = 1_000_000
MAX_TSV_FIELD_CHARS = 65_535
MAX_REVIEW_RECORDS = 10_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_GIT_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_DECODED_RGBA_REFERENCE_RE = re.compile(r"decoded-rgba-sha256:[0-9a-f]{64}")
_DECODED_TSV_REFERENCE_RE = re.compile(r"decoded-tsv-sha256:[0-9a-f]{64}")
_PRIVACY_SCAN_REFERENCE = "privacy-scan:forbidden-local-generic-identities"
_VISUAL_REVIEW_REFERENCE = "visual-review:exact-rendered-pixels"
_REGISTRY_VALIDATION_REFERENCE = "registry-validation:retained-source-and-runtime-loader"
_PNG_TYPE_RE = re.compile(rb"[A-Za-z]{4}")
_RISKY_PNG_CHUNKS = ("eXIf", "iCCP", "iTXt", "tEXt", "zTXt")
_ACCEPTED_PNG_ANCILLARY_CHUNKS = frozenset(
    {"bKGD", "cHRM", "gAMA", "hIST", "pHYs", "sBIT", "sPLT", "sRGB", "tIME", "tRNS"}
)
_PNG_EVIDENCE_KEYS = frozenset(
    {
        "kind",
        "validator",
        "format_valid",
        "crc_valid",
        "chunk_order_valid",
        "idat_framing_valid",
        "trailing_bytes",
        "width",
        "height",
        "bit_depth",
        "color_type",
        "interlace_method",
        "chunk_count",
        "idat_chunk_count",
        "idat_compressed_bytes",
        "decoded_scanline_bytes",
        "decoded_scanline_sha256",
        "risky_metadata_chunk_counts",
        "forbidden_content_findings",
    }
)
_GZIP_EVIDENCE_KEYS = frozenset(
    {
        "kind",
        "validator",
        "format_valid",
        "member_count",
        "header_flags",
        "header_mtime",
        "header_xfl",
        "header_os",
        "trailer_crc32",
        "trailer_isize",
        "uncompressed_bytes",
        "uncompressed_sha256",
        "tsv_header_mode",
        "tsv_header",
        "column_count",
        "row_count",
        "forbidden_content_findings",
    }
)
_INDEPENDENT_REVIEW_KEYS = frozenset(
    {
        "reviewer_kind",
        "reviewer_role",
        "independent_from_proposer",
        "review_scope",
        "evidence_references",
        "verdict",
    }
)
_RECORD_KEYS = frozenset(
    {
        "path",
        "git_blob_oid",
        "raw_sha256",
        "raw_bytes",
        "media_type",
        "format",
        "automated_format_evidence",
        "independent_review",
    }
)
_TOP_LEVEL_KEYS = frozenset({"schema_version", "receipt_kind", "review_basis_commit", "binary_set_digest", "records"})
_SUMMARY_ERROR_CODES = frozenset(
    {
        "binary_denominator_contains_unsupported_format",
        "binary_format_invalid",
        "binary_review_automated_format_pending_unsupported_png_ancillary",
        "binary_review_denominator_empty",
        "binary_review_dirty_preview_not_eligible",
        "binary_review_receipt_absent",
        "binary_review_receipt_binary_set_digest_mismatch",
        "binary_review_receipt_format_evidence_mismatch",
        "binary_review_receipt_identity_mismatch",
        "binary_review_receipt_independent_verdict_not_passed",
        "binary_review_receipt_malformed",
        "binary_review_receipt_membership_mismatch",
        "binary_review_receipt_review_basis_not_ancestor",
        "binary_review_reviewer_authentication_pending",
    }
)

_INCOMPLETE_ERROR_CODES = frozenset(
    {
        "binary_review_automated_format_pending_unsupported_png_ancillary",
        "binary_review_receipt_independent_verdict_not_passed",
        "binary_review_reviewer_authentication_pending",
    }
)

OUI_TSV_HEADER = ("prefix_hex", "prefix_bits", "vendor")
PORT_TSV_HEADER = (
    "key",
    "protocol",
    "service",
    "alias_records_json",
    "category",
    "broadcast",
    "note",
    "assignment_source",
    "semantics_source",
    "overlay_service",
    "overlay_note",
    "overlay_status",
)


class BinaryReviewFailure(RuntimeError):
    """A fixed, non-echoing binary-review failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fixed_failure(code: str = "binary_review_receipt_malformed") -> BinaryReviewFailure:
    return BinaryReviewFailure(code)


def _pending_reviewer_custody() -> dict[str, Any]:
    """Return compiler-owned custody state; receipt strings cannot promote it."""

    return {
        "status": "pending_trusted_external_attestation",
        "required_mechanism": "detached_signature_with_trusted_public_key",
        "trusted_public_key_configured": False,
        "detached_signature_present": False,
        "detached_signature_verified": False,
        "authenticated_reviewer_kind": None,
        "authenticated_files": 0,
        "receipt_claims_trusted": False,
    }


def _privacy_channel_is_unsafe(label: str, value: str | bytes) -> bool:
    if isinstance(value, bytes):
        if len(value) > MAX_METADATA_BYTES:
            return True
        texts = (value.decode("utf-8", errors="ignore"), value.decode("latin-1", errors="strict"))
    else:
        texts = (value,)
    return any(forbidden_content_findings(label, text) or generic_local_identity_rule(text) for text in texts)


def _is_int(value: object, *, minimum: int = 0, maximum: int = MAX_SAFE_INTEGER) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST_RE.fullmatch(value) is not None


def _is_git_oid(value: object) -> bool:
    return isinstance(value, str) and _GIT_OID_RE.fullmatch(value) is not None


def _is_safe_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return bool(
        not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == value
        and all(part not in {"", "."} for part in path.parts)
    )


def _format_for_path(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith(".png"):
        return "png"
    if lower.endswith(".tsv.gz"):
        return "gzip_tsv"
    return None


def _identity_row(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": record["path"],
        "git_blob_oid": record["git_blob_oid"],
        "raw_sha256": record["raw_sha256"],
        "raw_bytes": record["raw_bytes"],
        "media_type": record["media_type"],
        "format": record["format"],
    }


def binary_set_digest(records: Iterable[Mapping[str, Any]]) -> str:
    identities = [_identity_row(record) for record in sorted(records, key=lambda item: str(item["path"]))]
    return sha256_bytes(canonical_json(identities))


def receipt_set_digest(records: Iterable[Mapping[str, Any]]) -> str:
    ordered = [dict(record) for record in sorted(records, key=lambda item: str(item["path"]))]
    return sha256_bytes(canonical_json(ordered))


def _strict_json(raw: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _fixed_failure()
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(_fixed_failure()),
        )
    except BinaryReviewFailure:
        raise
    except (RecursionError, UnicodeError, ValueError):
        raise _fixed_failure() from None


def _valid_risky_counts(value: object) -> bool:
    return bool(
        isinstance(value, dict)
        and set(value) == set(_RISKY_PNG_CHUNKS)
        and all(_is_int(count) for count in value.values())
    )


def _valid_png_evidence(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _PNG_EVIDENCE_KEYS:
        return False
    return bool(
        value.get("kind") == "png"
        and value.get("validator") == PNG_VALIDATOR
        and value.get("format_valid") is True
        and value.get("crc_valid") is True
        and value.get("chunk_order_valid") is True
        and value.get("idat_framing_valid") is True
        and value.get("trailing_bytes") == 0
        and _is_int(value.get("width"), minimum=1, maximum=2_147_483_647)
        and _is_int(value.get("height"), minimum=1, maximum=2_147_483_647)
        and value.get("bit_depth") in {1, 2, 4, 8, 16}
        and value.get("color_type") in {0, 2, 3, 4, 6}
        and value.get("interlace_method") in {0, 1}
        and _is_int(value.get("chunk_count"), minimum=3)
        and _is_int(value.get("idat_chunk_count"), minimum=1)
        and _is_int(value.get("idat_compressed_bytes"), maximum=MAX_BINARY_BYTES)
        and _is_int(value.get("decoded_scanline_bytes"), maximum=MAX_PNG_DECODED_BYTES)
        and _is_digest(value.get("decoded_scanline_sha256"))
        and _valid_risky_counts(value.get("risky_metadata_chunk_counts"))
        and value.get("forbidden_content_findings") == 0
    )


def _valid_gzip_evidence(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _GZIP_EVIDENCE_KEYS:
        return False
    header = value.get("tsv_header")
    return bool(
        value.get("kind") == "gzip_tsv"
        and value.get("validator") == GZIP_TSV_VALIDATOR
        and value.get("format_valid") is True
        and value.get("member_count") == 1
        and _is_int(value.get("header_flags"), maximum=31)
        and _is_int(value.get("header_mtime"), maximum=0xFFFFFFFF)
        and _is_int(value.get("header_xfl"), maximum=255)
        and _is_int(value.get("header_os"), maximum=255)
        and isinstance(value.get("trailer_crc32"), str)
        and re.fullmatch(r"[0-9a-f]{8}", value["trailer_crc32"]) is not None
        and _is_int(value.get("trailer_isize"), maximum=0xFFFFFFFF)
        and _is_int(value.get("uncompressed_bytes"), maximum=MAX_GZIP_DECOMPRESSED_BYTES)
        and _is_digest(value.get("uncompressed_sha256"))
        and value.get("tsv_header_mode") == "declared_schema_no_physical_header"
        and isinstance(header, list)
        and bool(header)
        and all(isinstance(item, str) and 1 <= len(item) <= 64 for item in header)
        and len(header) == len(set(header))
        and value.get("column_count") == len(header)
        and _is_int(value.get("row_count"), minimum=1, maximum=MAX_TSV_ROWS)
        and value.get("forbidden_content_findings") == 0
    )


def _valid_independent_review(value: object, binary_format: str, automated_evidence: object) -> bool:
    if not isinstance(value, dict) or set(value) != _INDEPENDENT_REVIEW_KEYS:
        return False
    references = value.get("evidence_references")
    expected_scope = "rendered_pixels_and_context" if binary_format == "png" else "decoded_tsv_rows_and_context"
    if not isinstance(references, list) or references != sorted(set(references)):
        return False
    if any(not isinstance(reference, str) or generic_local_identity_rule(reference) for reference in references):
        return False
    if binary_format == "png":
        digest_references = [
            reference for reference in references if _DECODED_RGBA_REFERENCE_RE.fullmatch(reference) is not None
        ]
        references_valid = bool(
            len(references) == 3
            and len(digest_references) == 1
            and set(references) == {digest_references[0], _PRIVACY_SCAN_REFERENCE, _VISUAL_REVIEW_REFERENCE}
        )
    else:
        evidence = automated_evidence if isinstance(automated_evidence, dict) else {}
        decoded_digest = evidence.get("uncompressed_sha256")
        expected_digest_reference = f"decoded-tsv-sha256:{decoded_digest}"
        references_valid = bool(
            isinstance(decoded_digest, str)
            and _DECODED_TSV_REFERENCE_RE.fullmatch(expected_digest_reference) is not None
            and references
            == sorted([expected_digest_reference, _PRIVACY_SCAN_REFERENCE, _REGISTRY_VALIDATION_REFERENCE])
        )
    return bool(
        value.get("reviewer_kind") == "independent_agent"
        and value.get("reviewer_role") == "binary_privacy_verifier"
        and value.get("independent_from_proposer") is True
        and value.get("review_scope") == expected_scope
        and references_valid
        and value.get("verdict") in {"pass", "block", "abstain"}
    )


def parse_tracked_binary_review(raw: bytes) -> dict[str, Any]:
    """Parse the canonical tracked receipt without echoing malformed values."""

    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RECEIPT_BYTES:
        raise _fixed_failure()
    value = _strict_json(raw)
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise _fixed_failure()
    if (
        value.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or value.get("receipt_kind") != RECEIPT_KIND
        or not _is_git_oid(value.get("review_basis_commit"))
        or not _is_digest(value.get("binary_set_digest"))
        or not isinstance(value.get("records"), list)
        or not 1 <= len(value["records"]) <= MAX_REVIEW_RECORDS
    ):
        raise _fixed_failure()
    records = value["records"]
    paths: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
            raise _fixed_failure()
        path = record.get("path")
        binary_format = record.get("format")
        if (
            not _is_safe_path(path)
            or binary_format not in {"png", "gzip_tsv"}
            or _format_for_path(path) != binary_format
            or not _is_git_oid(record.get("git_blob_oid"))
            or not _is_digest(record.get("raw_sha256"))
            or not _is_int(record.get("raw_bytes"), maximum=MAX_BINARY_BYTES)
            or record.get("media_type") not in {"image/png", "text/tab-separated-values"}
            or (binary_format == "png" and record.get("media_type") != "image/png")
            or (binary_format == "gzip_tsv" and record.get("media_type") != "text/tab-separated-values")
            or (binary_format == "png" and not _valid_png_evidence(record.get("automated_format_evidence")))
            or (binary_format == "gzip_tsv" and not _valid_gzip_evidence(record.get("automated_format_evidence")))
            or not _valid_independent_review(
                record.get("independent_review"), binary_format, record.get("automated_format_evidence")
            )
        ):
            raise _fixed_failure()
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise _fixed_failure()
    if value["binary_set_digest"] != binary_set_digest(records):
        raise BinaryReviewFailure("binary_review_receipt_binary_set_digest_mismatch")
    return value


def _bounded_zlib(value: bytes, maximum: int) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(value, maximum + 1)
        if len(decoded) > maximum or decompressor.unconsumed_tail:
            raise _fixed_failure("binary_format_invalid")
        remaining = maximum + 1 - len(decoded)
        if remaining > 0:
            decoded += decompressor.flush(remaining)
        if len(decoded) > maximum or not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
            raise _fixed_failure("binary_format_invalid")
        return decoded
    except BinaryReviewFailure:
        raise
    except (MemoryError, OverflowError, ValueError, zlib.error):
        raise _fixed_failure("binary_format_invalid") from None


def _adam7_passes(width: int, height: int) -> list[tuple[int, int]]:
    starts = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
    passes: list[tuple[int, int]] = []
    for start_x, start_y, step_x, step_y in starts:
        pass_width = 0 if width <= start_x else (width - start_x + step_x - 1) // step_x
        pass_height = 0 if height <= start_y else (height - start_y + step_y - 1) // step_y
        if pass_width and pass_height:
            passes.append((pass_width, pass_height))
    return passes


def _scanline_layout(width: int, height: int, bits_per_pixel: int, interlace: int) -> list[tuple[int, int]]:
    dimensions = [(width, height)] if interlace == 0 else _adam7_passes(width, height)
    layout: list[tuple[int, int]] = []
    total = 0
    for pass_width, pass_height in dimensions:
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        total += pass_height * (row_bytes + 1)
        if total > MAX_PNG_DECODED_BYTES:
            raise _fixed_failure("binary_format_invalid")
        layout.append((row_bytes, pass_height))
    return layout


def _inspect_png(value: bytes) -> dict[str, Any]:
    if len(value) < 8 or value[:8] != b"\x89PNG\r\n\x1a\n":
        raise _fixed_failure("binary_format_invalid")
    cursor = 8
    chunk_count = 0
    seen: Counter[str] = Counter()
    risky: Counter[str] = Counter()
    idat_parts: list[bytes] = []
    ihdr: tuple[int, int, int, int, int] | None = None
    palette_entries: int | None = None
    idat_closed = False
    singleton = {
        "IHDR",
        "PLTE",
        "IEND",
        "cHRM",
        "gAMA",
        "iCCP",
        "sBIT",
        "sRGB",
        "bKGD",
        "hIST",
        "tRNS",
        "pHYs",
        "tIME",
        "eXIf",
    }
    before_plte_and_idat = {"cHRM", "gAMA", "iCCP", "sBIT", "sRGB"}
    before_idat = {"PLTE", "bKGD", "hIST", "tRNS", "pHYs", "sPLT", "eXIf"}
    known_critical = {"IHDR", "PLTE", "IDAT", "IEND"}

    while cursor < len(value):
        if len(value) - cursor < 12:
            raise _fixed_failure("binary_format_invalid")
        length = struct.unpack(">I", value[cursor : cursor + 4])[0]
        chunk_type_raw = value[cursor + 4 : cursor + 8]
        if length > MAX_PNG_CHUNK_BYTES or _PNG_TYPE_RE.fullmatch(chunk_type_raw) is None:
            raise _fixed_failure("binary_format_invalid")
        if chunk_type_raw[2] & 0x20:
            raise _fixed_failure("binary_format_invalid")
        data_start = cursor + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(value):
            raise _fixed_failure("binary_format_invalid")
        data = value[data_start:data_end]
        expected_crc = struct.unpack(">I", value[data_end:crc_end])[0]
        if (binascii.crc32(chunk_type_raw + data) & 0xFFFFFFFF) != expected_crc:
            raise _fixed_failure("binary_format_invalid")
        chunk_type = chunk_type_raw.decode("ascii", errors="strict")
        chunk_count += 1
        seen[chunk_type] += 1
        if chunk_count == 1 and chunk_type != "IHDR":
            raise _fixed_failure("binary_format_invalid")
        if chunk_type in singleton and seen[chunk_type] != 1:
            raise _fixed_failure("binary_format_invalid")
        ancillary = bool(chunk_type_raw[0] & 0x20)
        if chunk_type not in known_critical and not ancillary:
            raise _fixed_failure("binary_format_invalid")
        if ancillary:
            if chunk_type in _RISKY_PNG_CHUNKS or chunk_type not in _ACCEPTED_PNG_ANCILLARY_CHUNKS:
                raise _fixed_failure("binary_review_automated_format_pending_unsupported_png_ancillary")
            if _privacy_channel_is_unsafe("binary-review-png-ancillary", data):
                raise _fixed_failure("binary_format_invalid")
        if chunk_type in before_plte_and_idat and (seen["PLTE"] or seen["IDAT"]):
            raise _fixed_failure("binary_format_invalid")
        if chunk_type in before_idat and seen["IDAT"]:
            raise _fixed_failure("binary_format_invalid")

        if chunk_type == "IHDR":
            if length != 13:
                raise _fixed_failure("binary_format_invalid")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if (
                not 1 <= width <= 2_147_483_647
                or not 1 <= height <= 2_147_483_647
                or bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
                or interlace not in {0, 1}
            ):
                raise _fixed_failure("binary_format_invalid")
            ihdr = (width, height, bit_depth, color_type, interlace)
        elif chunk_type == "PLTE":
            if ihdr is None or not 1 <= length <= 768 or length % 3:
                raise _fixed_failure("binary_format_invalid")
            palette_entries = length // 3
            if ihdr[3] in {0, 4} or (ihdr[3] == 3 and palette_entries > (1 << ihdr[2])):
                raise _fixed_failure("binary_format_invalid")
        elif chunk_type == "IDAT":
            if ihdr is None or idat_closed:
                raise _fixed_failure("binary_format_invalid")
            idat_parts.append(data)
        elif chunk_type == "IEND":
            if length != 0 or not idat_parts or crc_end != len(value):
                raise _fixed_failure("binary_format_invalid")
        elif idat_parts:
            idat_closed = True

        cursor = crc_end
        if chunk_type == "IEND":
            break

    if cursor != len(value) or ihdr is None or seen["IHDR"] != 1 or seen["IEND"] != 1 or not idat_parts:
        raise _fixed_failure("binary_format_invalid")
    width, height, bit_depth, color_type, interlace = ihdr
    if color_type == 3 and palette_entries is None:
        raise _fixed_failure("binary_format_invalid")
    if seen["hIST"] and palette_entries is None:
        raise _fixed_failure("binary_format_invalid")
    if seen["tRNS"] and color_type in {4, 6}:
        raise _fixed_failure("binary_format_invalid")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    layout = _scanline_layout(width, height, channels * bit_depth, interlace)
    expected_decoded = sum((row_bytes + 1) * rows for row_bytes, rows in layout)
    decoded = _bounded_zlib(b"".join(idat_parts), expected_decoded)
    if len(decoded) != expected_decoded:
        raise _fixed_failure("binary_format_invalid")
    offset = 0
    for row_bytes, rows in layout:
        for _row in range(rows):
            if decoded[offset] > 4:
                raise _fixed_failure("binary_format_invalid")
            offset += row_bytes + 1
    if offset != len(decoded):
        raise _fixed_failure("binary_format_invalid")
    return {
        "kind": "png",
        "validator": PNG_VALIDATOR,
        "format_valid": True,
        "crc_valid": True,
        "chunk_order_valid": True,
        "idat_framing_valid": True,
        "trailing_bytes": 0,
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "interlace_method": interlace,
        "chunk_count": chunk_count,
        "idat_chunk_count": len(idat_parts),
        "idat_compressed_bytes": sum(len(part) for part in idat_parts),
        "decoded_scanline_bytes": len(decoded),
        "decoded_scanline_sha256": hashlib.sha256(decoded).hexdigest(),
        "risky_metadata_chunk_counts": {name: risky[name] for name in _RISKY_PNG_CHUNKS},
        "forbidden_content_findings": 0,
    }


def inspect_png(value: bytes) -> dict[str, Any]:
    """Return deterministic structural PNG evidence or one fixed failure."""

    try:
        if not isinstance(value, bytes) or len(value) > MAX_BINARY_BYTES:
            raise _fixed_failure("binary_format_invalid")
        return _inspect_png(value)
    except BinaryReviewFailure:
        raise
    except (IndexError, MemoryError, OverflowError, TypeError, UnicodeError, ValueError, zlib.error):
        raise _fixed_failure("binary_format_invalid") from None


def _gzip_header(value: bytes) -> tuple[int, int, int, int, int]:
    if len(value) < 18 or value[:3] != b"\x1f\x8b\x08":
        raise _fixed_failure("binary_format_invalid")
    flags = value[3]
    if flags != 0:
        raise _fixed_failure("binary_format_invalid")
    mtime = struct.unpack("<I", value[4:8])[0]
    xfl = value[8]
    operating_system = value[9]
    cursor = 10
    if cursor >= len(value) - 8:
        raise _fixed_failure("binary_format_invalid")
    return cursor, flags, mtime, xfl, operating_system


def _strict_alias_json(value: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise _fixed_failure("binary_format_invalid")
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            object_pairs_hook=object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(_fixed_failure("binary_format_invalid")),
        )
    except BinaryReviewFailure:
        raise
    except (RecursionError, ValueError):
        raise _fixed_failure("binary_format_invalid") from None


def _validate_oui_rows(rows: list[str]) -> tuple[tuple[str, ...], int]:
    prefixes: set[tuple[int, str]] = set()
    for row in rows:
        parts = row.split("\t")
        if len(parts) != len(OUI_TSV_HEADER):
            raise _fixed_failure("binary_format_invalid")
        prefix, bits_text, vendor = parts
        try:
            bits = int(bits_text)
        except ValueError:
            raise _fixed_failure("binary_format_invalid") from None
        identity = (bits, prefix)
        if (
            bits not in {24, 28, 36}
            or bits_text != str(bits)
            or len(prefix) != bits // 4
            or re.fullmatch(r"[0-9A-F]+", prefix) is None
            or not vendor.strip()
            or vendor != vendor.strip()
            or identity in prefixes
        ):
            raise _fixed_failure("binary_format_invalid")
        prefixes.add(identity)
    return OUI_TSV_HEADER, len(rows)


def _validate_port_rows(rows: list[str]) -> tuple[tuple[str, ...], int]:
    ports: set[tuple[int, str]] = set()
    multicast: set[str] = set()
    for row in rows:
        parts = row.split("\t")
        if len(parts) != len(PORT_TSV_HEADER):
            raise _fixed_failure("binary_format_invalid")
        (
            key,
            protocol,
            service,
            aliases_json,
            category,
            broadcast,
            _note,
            assignment_source,
            semantics_source,
            overlay_service,
            _overlay_note,
            overlay_status,
        ) = parts
        aliases = _strict_alias_json(aliases_json)
        if (
            not service.strip()
            or service != service.strip()
            or broadcast not in {"0", "1"}
            or not isinstance(aliases, list)
            or any(
                not isinstance(alias, list)
                or len(alias) != 2
                or any(not isinstance(item, str) for item in alias)
                or not alias[0]
                for alias in aliases
            )
        ):
            raise _fixed_failure("binary_format_invalid")
        if protocol == "mcast":
            try:
                network = ipaddress.ip_network(key, strict=True)
            except ValueError:
                raise _fixed_failure("binary_format_invalid") from None
            canonical = str(network)
            if (
                aliases
                or not isinstance(network, ipaddress.IPv4Network)
                or not network.network_address.is_multicast
                or canonical != key
                or canonical in multicast
                or assignment_source != "curated-multicast"
                or semantics_source != "curated-multicast"
                or overlay_status != "curated-only"
            ):
                raise _fixed_failure("binary_format_invalid")
            multicast.add(canonical)
            continue
        if protocol not in {"tcp", "udp", "sctp", "dccp"}:
            raise _fixed_failure("binary_format_invalid")
        try:
            port = int(key)
        except ValueError:
            raise _fixed_failure("binary_format_invalid") from None
        identity = (port, protocol)
        if (
            not 0 <= port <= 65_535
            or key != str(port)
            or identity in ports
            or assignment_source not in {"iana", "curated-overlay"}
            or semantics_source not in {"iana", "curated-overlay"}
            or overlay_status not in {"none", "supplemental", "overlay-only", "conflict-suppressed"}
        ):
            raise _fixed_failure("binary_format_invalid")
        if assignment_source == "curated-overlay" and (
            aliases or semantics_source != "curated-overlay" or overlay_status != "overlay-only"
        ):
            raise _fixed_failure("binary_format_invalid")
        if overlay_status == "conflict-suppressed" and (
            category or broadcast != "0" or semantics_source != "iana" or not overlay_service
        ):
            raise _fixed_failure("binary_format_invalid")
        if overlay_status == "none" and (overlay_service or _overlay_note or semantics_source != "iana"):
            raise _fixed_failure("binary_format_invalid")
        ports.add(identity)
    return PORT_TSV_HEADER, len(rows)


def _inspect_gzip_tsv(path: str, value: bytes) -> dict[str, Any]:
    deflate_offset, flags, mtime, xfl, operating_system = _gzip_header(value)
    try:
        decompressor = zlib.decompressobj(wbits=-zlib.MAX_WBITS)
        decoded = decompressor.decompress(value[deflate_offset:], MAX_GZIP_DECOMPRESSED_BYTES + 1)
        if len(decoded) > MAX_GZIP_DECOMPRESSED_BYTES or decompressor.unconsumed_tail or not decompressor.eof:
            raise _fixed_failure("binary_format_invalid")
        trailer = decompressor.unused_data
        if len(trailer) != 8:
            raise _fixed_failure("binary_format_invalid")
        expected_crc, expected_size = struct.unpack("<II", trailer)
        if (binascii.crc32(decoded) & 0xFFFFFFFF) != expected_crc or len(decoded) != expected_size:
            raise _fixed_failure("binary_format_invalid")
        text = decoded.decode("utf-8", errors="strict")
    except BinaryReviewFailure:
        raise
    except (MemoryError, OverflowError, UnicodeError, ValueError, zlib.error):
        raise _fixed_failure("binary_format_invalid") from None
    if (
        not text
        or text.startswith("\ufeff")
        or not text.endswith("\n")
        or "\r" in text
        or "\x00" in text
        or _privacy_channel_is_unsafe("binary-review-gzip-tsv", text)
    ):
        raise _fixed_failure("binary_format_invalid")
    rows = text[:-1].split("\n")
    if not rows or len(rows) > MAX_TSV_ROWS or any(not row for row in rows):
        raise _fixed_failure("binary_format_invalid")
    if any(any(ord(char) < 32 and char != "\t" for char in row) for row in rows):
        raise _fixed_failure("binary_format_invalid")
    if any(any(len(field) > MAX_TSV_FIELD_CHARS for field in row.split("\t")) for row in rows):
        raise _fixed_failure("binary_format_invalid")
    if path.endswith("/oui_registry.tsv.gz"):
        header, row_count = _validate_oui_rows(rows)
    elif path.endswith("/port_registry.tsv.gz"):
        header, row_count = _validate_port_rows(rows)
    else:
        raise _fixed_failure("binary_format_invalid")
    return {
        "kind": "gzip_tsv",
        "validator": GZIP_TSV_VALIDATOR,
        "format_valid": True,
        "member_count": 1,
        "header_flags": flags,
        "header_mtime": mtime,
        "header_xfl": xfl,
        "header_os": operating_system,
        "trailer_crc32": f"{expected_crc:08x}",
        "trailer_isize": expected_size,
        "uncompressed_bytes": len(decoded),
        "uncompressed_sha256": hashlib.sha256(decoded).hexdigest(),
        "tsv_header_mode": "declared_schema_no_physical_header",
        "tsv_header": list(header),
        "column_count": len(header),
        "row_count": row_count,
        "forbidden_content_findings": 0,
    }


def inspect_gzip_tsv(path: str, value: bytes) -> dict[str, Any]:
    """Return strict single-member gzip/TSV evidence or one fixed failure."""

    try:
        if not _is_safe_path(path) or not isinstance(value, bytes) or len(value) > MAX_BINARY_BYTES:
            raise _fixed_failure("binary_format_invalid")
        return _inspect_gzip_tsv(path, value)
    except BinaryReviewFailure:
        raise
    except (IndexError, MemoryError, OverflowError, TypeError, UnicodeError, ValueError, zlib.error):
        raise _fixed_failure("binary_format_invalid") from None


def inspect_binary(path: str, value: bytes) -> dict[str, Any]:
    binary_format = _format_for_path(path)
    if binary_format == "png":
        return inspect_png(value)
    if binary_format == "gzip_tsv":
        return inspect_gzip_tsv(path, value)
    raise _fixed_failure("binary_format_invalid")


def _format_counts(descriptors: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(_format_for_path(str(item.get("path") or "")) or "unsupported" for item in descriptors)
    return {"png": counts["png"], "gzip_tsv": counts["gzip_tsv"], "unsupported": counts["unsupported"]}


def unavailable_summary(
    descriptors: Iterable[Mapping[str, Any]],
    *,
    status: str,
    receipt_git_blob_oid: str | None = None,
    receipt_raw: bytes | None = None,
) -> dict[str, Any]:
    items = list(descriptors)
    if status not in {"absent", "dirty_preview_not_eligible", "invalid"}:
        raise ValueError("binary review unavailable status is invalid")
    code = {
        "absent": "binary_review_receipt_absent",
        "dirty_preview_not_eligible": "binary_review_dirty_preview_not_eligible",
        "invalid": "binary_review_receipt_malformed",
    }[status]
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_path": RECEIPT_PATH,
        "status": status,
        "expected_files": len(items),
        "receipt_records": 0,
        "identity_matched_files": 0,
        "automated_format_passed_files": 0,
        "automated_format_pending_files": 0,
        "claimed_independent_contextual_passed_files": 0,
        "independent_contextual_passed_files": 0,
        "accepted_files": 0,
        "format_counts": _format_counts(items),
        "receipt_git_blob_oid": receipt_git_blob_oid,
        "receipt_content_digest": sha256_bytes(receipt_raw) if receipt_raw is not None else None,
        "receipt_set_digest": None,
        "binary_set_digest": None,
        "review_basis_commit": None,
        "review_basis_is_ancestor": None,
        "reviewer_custody": _pending_reviewer_custody(),
        "payload_bytes_embedded_in_projection": False,
        "error_codes": [code],
    }


def evaluate_tracked_binary_review(
    receipt_raw: bytes,
    descriptors: Iterable[Mapping[str, Any]],
    *,
    receipt_git_blob_oid: str,
    review_basis_is_ancestor: Callable[[str], bool],
) -> dict[str, Any]:
    """Recompute exact binary identities/evidence and join the tracked receipt."""

    items = sorted((dict(item) for item in descriptors), key=lambda item: str(item.get("path") or ""))
    try:
        receipt = parse_tracked_binary_review(receipt_raw)
    except BinaryReviewFailure as exc:
        summary = unavailable_summary(
            items,
            status="invalid",
            receipt_git_blob_oid=receipt_git_blob_oid,
            receipt_raw=receipt_raw,
        )
        code = exc.code if exc.code in _SUMMARY_ERROR_CODES else "binary_review_receipt_malformed"
        summary["error_codes"] = [code]
        return summary

    records = receipt["records"]
    receipt_by_path = {str(record["path"]): record for record in records}
    item_paths = [str(item.get("path") or "") for item in items]
    errors: set[str] = set()
    if not items:
        errors.add("binary_review_denominator_empty")
    format_counts = _format_counts(items)
    if format_counts["unsupported"]:
        errors.add("binary_denominator_contains_unsupported_format")
    if item_paths != list(receipt_by_path):
        errors.add("binary_review_receipt_membership_mismatch")
    try:
        basis_is_ancestor = bool(review_basis_is_ancestor(str(receipt["review_basis_commit"])))
    except (OSError, RuntimeError, ValueError):
        basis_is_ancestor = False
    if not basis_is_ancestor:
        errors.add("binary_review_receipt_review_basis_not_ancestor")
    claimed_contextual_passed = sum(
        1
        for record in records
        if _valid_independent_review(
            record.get("independent_review"),
            str(record.get("format") or ""),
            record.get("automated_format_evidence"),
        )
        and record["independent_review"].get("verdict") == "pass"
    )
    if claimed_contextual_passed != len(records):
        errors.add("binary_review_receipt_independent_verdict_not_passed")
    errors.add("binary_review_reviewer_authentication_pending")

    actual_identities: list[dict[str, Any]] = []
    identity_matched = 0
    automated_passed = 0
    automated_pending = 0
    for item in items:
        path = item.get("path")
        blob_oid = item.get("git_blob_oid")
        media_type = item.get("media_type")
        raw = item.get("raw")
        binary_format = _format_for_path(str(path or ""))
        if (
            not _is_safe_path(path)
            or not _is_git_oid(blob_oid)
            or not isinstance(media_type, str)
            or not isinstance(raw, bytes)
            or len(raw) > MAX_BINARY_BYTES
            or binary_format is None
        ):
            errors.add("binary_review_receipt_identity_mismatch")
            continue
        identity = {
            "path": path,
            "git_blob_oid": blob_oid,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes": len(raw),
            "media_type": media_type,
            "format": binary_format,
        }
        actual_identities.append(identity)
        receipt_record = receipt_by_path.get(path)
        identity_ok = receipt_record is not None and _identity_row(receipt_record) == identity
        if identity_ok:
            identity_matched += 1
        else:
            errors.add("binary_review_receipt_identity_mismatch")
        try:
            evidence = inspect_binary(path, raw)
            format_ok = receipt_record is not None and receipt_record.get("automated_format_evidence") == evidence
        except BinaryReviewFailure as exc:
            if exc.code == "binary_review_automated_format_pending_unsupported_png_ancillary":
                errors.add(exc.code)
                automated_pending += 1
                format_ok = None
            else:
                errors.add("binary_format_invalid")
                format_ok = False
        if format_ok is True:
            automated_passed += 1
        elif format_ok is False:
            errors.add("binary_review_receipt_format_evidence_mismatch")

    actual_binary_set_digest = binary_set_digest(actual_identities) if len(actual_identities) == len(items) else None
    if actual_binary_set_digest != receipt.get("binary_set_digest"):
        errors.add("binary_review_receipt_binary_set_digest_mismatch")
    status = "incomplete" if errors and errors <= _INCOMPLETE_ERROR_CODES else "invalid"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_path": RECEIPT_PATH,
        "status": status,
        "expected_files": len(items),
        "receipt_records": len(records),
        "identity_matched_files": identity_matched,
        "automated_format_passed_files": automated_passed,
        "automated_format_pending_files": automated_pending,
        "claimed_independent_contextual_passed_files": claimed_contextual_passed,
        "independent_contextual_passed_files": 0,
        "accepted_files": 0,
        "format_counts": format_counts,
        "receipt_git_blob_oid": receipt_git_blob_oid,
        "receipt_content_digest": sha256_bytes(receipt_raw),
        "receipt_set_digest": receipt_set_digest(records),
        "binary_set_digest": actual_binary_set_digest,
        "review_basis_commit": receipt["review_basis_commit"],
        "review_basis_is_ancestor": basis_is_ancestor,
        "reviewer_custody": _pending_reviewer_custody(),
        "payload_bytes_embedded_in_projection": False,
        "error_codes": sorted(errors),
    }
