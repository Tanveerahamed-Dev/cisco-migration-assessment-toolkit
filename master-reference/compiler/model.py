"""Small deterministic primitives shared by compiler adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


# Corpus contract version.  This version is shared by the compiler manifest,
# completeness ledger, and every record-chunk envelope.  It is intentionally
# independent from the release-family document schemas.
SCHEMA_VERSION = "1.1.0"
PREVIEW_LIMIT = 240


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 JSON used for IDs, digests, chunks, and receipts."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_object(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def stable_id(kind: str, *parts: object) -> str:
    identity = "\x1f".join(str(part) for part in parts)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"urn:atlas:{kind}:{suffix}"


def normalized_path(path: str | Path) -> str:
    return Path(path).as_posix()


def text_preview(value: str, limit: int = PREVIEW_LIMIT) -> str:
    clean = " ".join(value.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)] + "…"


def chunked(records: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(records), size):
        yield records[start : start + size]
