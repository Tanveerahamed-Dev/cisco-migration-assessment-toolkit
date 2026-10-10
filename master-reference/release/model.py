"""Canonical serialization, hashing, path, and archive primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0.0"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ReleaseInputError(RuntimeError):
    """An input or path failed a release integrity rule."""


def canonical_json(value: Any) -> bytes:
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
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"urn:atlas:{kind}:{hashlib.sha256(payload).hexdigest()[:24]}"


def safe_relative(value: str) -> str:
    """Return one canonical POSIX relative path or fail closed."""

    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ReleaseInputError(f"unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseInputError(f"unsafe relative path: {value!r}")
    return value


def safe_input(root: Path, relative: str) -> Path:
    """Resolve an allowlisted input without following any symlink component."""

    relative = safe_relative(relative)
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ReleaseInputError(f"missing required input {relative}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ReleaseInputError(f"symlink input refused: {relative}")
    if not current.is_file():
        raise ReleaseInputError(f"required input is not a regular file: {relative}")
    return current


def read_bytes(root: Path, relative: str) -> bytes:
    path = safe_input(root, relative)
    before = path.stat(follow_symlinks=False)
    value = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or len(value) != after.st_size:
        raise ReleaseInputError(f"input changed while read: {relative}")
    return value


def read_json(root: Path, relative: str) -> Any:
    try:
        return json.loads(read_bytes(root, relative).decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError(f"invalid UTF-8 JSON input: {relative}: {exc}") from exc


def receipt(value: bytes) -> dict[str, Any]:
    return {"sha256": sha256_bytes(value), "bytes": len(value)}


def write_bytes(root: Path, relative: str, value: bytes) -> dict[str, Any]:
    relative = safe_relative(relative)
    target = root.joinpath(*PurePosixPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ReleaseInputError(f"release output already exists: {relative}")
    target.write_bytes(value)
    return {"path": relative, **receipt(value)}


@dataclass
class StagedOutput:
    """Sibling staging directory that can be atomically published once."""

    target: Path
    staging: Path
    target_was_empty: bool
    published: bool = False

    def publish(self) -> Path:
        if self.published:
            raise ReleaseInputError("release staging directory was already published")
        if not self.staging.is_dir() or self.staging.is_symlink():
            raise ReleaseInputError("release staging directory is unavailable")
        removed_empty_target = False
        if self.target_was_empty:
            if self.target.is_symlink() or not self.target.is_dir() or any(self.target.iterdir()):
                raise ReleaseInputError("pre-existing empty release target changed before publication")
            self.target.rmdir()
            removed_empty_target = True
        elif self.target.exists() or self.target.is_symlink():
            raise ReleaseInputError("release target appeared before atomic publication")
        try:
            os.rename(self.staging, self.target)
        except OSError:
            if removed_empty_target and not self.target.exists():
                self.target.mkdir(parents=False, exist_ok=False)
            raise
        self.published = True
        return self.target

    def cleanup(self) -> None:
        if self.published or not self.staging.exists():
            return
        if self.staging.is_symlink() or self.staging.parent != self.target.parent:
            raise ReleaseInputError("refusing to clean an unexpected staging path")
        shutil.rmtree(self.staging)


def prepare_output(path: Path) -> StagedOutput:
    """Reserve a sibling staging directory without exposing partial artifacts."""

    raw = Path(os.path.abspath(path))
    raw.parent.mkdir(parents=True, exist_ok=True)
    parent = raw.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ReleaseInputError(f"output parent is not a directory: {parent}")
    absolute = parent / raw.name
    target_was_empty = False
    if absolute.exists() or absolute.is_symlink():
        if absolute.is_symlink() or not absolute.is_dir():
            raise ReleaseInputError(f"output is not a safe directory: {absolute}")
        if any(absolute.iterdir()):
            raise ReleaseInputError(f"output directory must be empty: {absolute}")
        target_was_empty = True
    staging = Path(tempfile.mkdtemp(prefix=f".{absolute.name}.building-", dir=parent))
    return StagedOutput(absolute, staging, target_was_empty)


@dataclass(frozen=True)
class VerifiedFile:
    """An archive entry held as a receipt, not as bytes.

    The file was read and hash-checked once before it became an entry.  Every
    ``read`` re-reads it through ``read_bytes`` (canonical path, no symlink
    component, stable size and mtime) and re-checks its byte count and SHA-256
    against that receipt, so an entry can never carry bytes other than the
    ones verified.  An archive therefore holds one entry's bytes at a time.
    """

    root: Path
    relative: str
    sha256: str
    byte_count: int
    changed_message: str
    unreadable_message: str | None = None

    def read(self) -> bytes:
        try:
            value = read_bytes(self.root, self.relative)
        except (OSError, ReleaseInputError):
            if self.unreadable_message is None:
                raise
            raise ReleaseInputError(self.unreadable_message) from None
        if len(value) != self.byte_count or sha256_bytes(value) != self.sha256:
            raise ReleaseInputError(self.changed_message)
        return value


ArchiveEntry = bytes | VerifiedFile


def entry_receipt(value: ArchiveEntry) -> dict[str, Any]:
    """The bundle-receipt row of one archive entry, identical for both kinds."""

    if isinstance(value, VerifiedFile):
        return {"sha256": value.sha256, "bytes": value.byte_count}
    return receipt(value)


def _entry_bytes(value: ArchiveEntry) -> bytes:
    return value.read() if isinstance(value, VerifiedFile) else value


def _write_deterministic_zip(stream: Any, entries: Mapping[str, ArchiveEntry]) -> None:
    """The one ZIP writer behind both ``deterministic_zip`` and the streamed form.

    Entry order, timestamps, permissions, flags, compression and the
    ``writestr`` call are unchanged from the original in-memory builder, so the
    archive bytes depend only on the entry names and bytes, never on whether
    the destination is memory or a file.  A ``VerifiedFile`` entry is read,
    re-verified and released inside its own ``writestr`` call.
    """

    with zipfile.ZipFile(
        stream,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(entries):
            safe_relative(name)
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800
            archive.writestr(info, _entry_bytes(entries[name]), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def deterministic_zip(entries: Mapping[str, ArchiveEntry]) -> bytes:
    """Build a byte-stable ZIP with fixed timestamps, ordering, and permissions."""

    import io

    buffer = io.BytesIO()
    _write_deterministic_zip(buffer, entries)
    return buffer.getvalue()


def write_deterministic_zip(root: Path, relative: str, entries: Mapping[str, ArchiveEntry]) -> dict[str, Any]:
    """Write ``deterministic_zip(entries)`` to ``root/relative`` entry by entry.

    The archive is never held in memory: it is written straight to a new file
    (refused, like ``write_bytes``, if the path already exists), and its
    receipt is then computed from the bytes on disk.
    """

    relative = safe_relative(relative)
    target = root.joinpath(*PurePosixPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ReleaseInputError(f"release output already exists: {relative}")
    with target.open("xb") as stream:
        _write_deterministic_zip(stream, entries)
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {"path": relative, "sha256": digest.hexdigest(), "bytes": size}


def collect_output_bytes(root: Path, receipts: Iterable[Mapping[str, Any]]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for item in receipts:
        relative = safe_relative(str(item["path"]))
        value = read_bytes(root, relative)
        if sha256_bytes(value) != item.get("sha256") or len(value) != item.get("bytes"):
            raise ReleaseInputError(f"generated artifact changed before packaging: {relative}")
        result[relative] = value
    return result


def verified_output_entries(root: Path, receipts: Iterable[Mapping[str, Any]]) -> dict[str, VerifiedFile]:
    """``collect_output_bytes`` without keeping the bytes.

    Each generated artifact is read and checked against its receipt now, as
    before, and becomes a ``VerifiedFile`` that is re-checked when packaged.
    """

    result: dict[str, VerifiedFile] = {}
    for item in receipts:
        relative = safe_relative(str(item["path"]))
        value = read_bytes(root, relative)
        if sha256_bytes(value) != item.get("sha256") or len(value) != item.get("bytes"):
            raise ReleaseInputError(f"generated artifact changed before packaging: {relative}")
        result[relative] = VerifiedFile(
            root,
            relative,
            sha256_bytes(value),
            len(value),
            changed_message=f"generated artifact changed before packaging: {relative}",
        )
        del value
    return result
