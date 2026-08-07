"""Deterministic primitives for the read-only continuity interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


class ContinuityInputError(ValueError):
    """An input was ambiguous, unsafe, stale, or structurally invalid."""


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def digest_object(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative(value: object, *, allow_directory_prefix: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ContinuityInputError(f"unsafe relative path: {value!r}")
    directory = value.endswith("/")
    material = value[:-1] if directory else value
    path = PurePosixPath(material)
    if (
        not material
        or path.is_absolute()
        or path.as_posix() != material
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContinuityInputError(f"unsafe relative path: {value!r}")
    if directory and not allow_directory_prefix:
        raise ContinuityInputError(f"directory prefix not allowed here: {value!r}")
    return value


def read_json_object(path: Path) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContinuityInputError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        raw = path.resolve(strict=True).read_bytes()
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ContinuityInputError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuityInputError(f"invalid JSON input: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityInputError(f"JSON input must be an object: {path}")
    return value
