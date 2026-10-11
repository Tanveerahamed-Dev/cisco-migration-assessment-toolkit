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
from typing import Any, Iterable, Iterator, Mapping


SCHEMA_VERSION = "1.0.0"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ReleaseInputError(RuntimeError):
    """An input or path failed a release integrity rule."""


def _canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json(value: Any) -> bytes:
    # Encoding before appending the newline gives the same bytes as encoding
    # ``text + "\n"``, but never holds a second full copy of the text, which
    # is four bytes per character as soon as one astral character appears.
    return _canonical_text(value).encode("utf-8") + b"\n"


def canonical_json_text_pieces(value: Any) -> Iterator[str]:
    """``canonical_json(value)`` as text pieces, never as one string.

    ``"".join(pieces).encode("utf-8") == canonical_json(value)``.  Only a
    top-level object whose keys are all strings is split: each member's key,
    and each element of a member whose value is exactly a ``list``, becomes its
    own piece, serialized by the same canonical encoder; anything else is one
    piece.  JSON's object and array grammar makes the joined pieces the same
    text the one-shot encoder produces (keys in sorted order, ``,`` and ``:``
    separators, no whitespace).
    """

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        yield _canonical_text(value) + "\n"
        return
    yield "{"
    for member, key in enumerate(sorted(value)):
        item = value[key]
        prefix = ("," if member else "") + _canonical_text(key) + ":"
        if type(item) is list:
            yield prefix + "["
            for position, element in enumerate(item):
                yield ("," if position else "") + _canonical_text(element)
            yield "]"
        else:
            yield prefix + _canonical_text(item)
    yield "}\n"


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
    ``read`` re-reads it from its canonical path (no symlink component) with
    a read bounded by the receipt: a size that differs from the receipt is
    refused before any byte is read, at most ``byte_count + 1`` bytes are read,
    size and mtime must be stable across the read, and the SHA-256 must match.
    An entry can never carry bytes other than the ones verified, and an
    archive holds one entry's bytes at a time.
    """

    root: Path
    relative: str
    sha256: str
    byte_count: int
    changed_message: str
    unreadable_message: str | None = None

    def _bounded_read(self) -> bytes | None:
        path = safe_input(self.root, self.relative)
        before = path.stat(follow_symlinks=False)
        if before.st_size != self.byte_count:
            return None
        with path.open("rb") as stream:
            value = stream.read(self.byte_count + 1)
        after = path.stat(follow_symlinks=False)
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or len(value) != after.st_size:
            raise ReleaseInputError(f"input changed while read: {self.relative}")
        return value

    def read(self) -> bytes:
        try:
            value = self._bounded_read()
        except (OSError, ReleaseInputError):
            if self.unreadable_message is None:
                raise
            raise ReleaseInputError(self.unreadable_message) from None
        if value is None or len(value) != self.byte_count or sha256_bytes(value) != self.sha256:
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


def _verify_written_archive(stream: Any, entries: Mapping[str, ArchiveEntry], relative: str) -> None:
    """Re-read the archive just written and require exactly its entries.

    The member names must be the sorted entry names, and every member must
    decompress (CRC-checked by ``zipfile``) to the byte count and SHA-256 of
    its entry's receipt.  Members are read in bounded blocks.
    """

    refusal = f"streamed archive differs from its entries: {relative}"
    expected = {name: entry_receipt(value) for name, value in entries.items()}
    try:
        with zipfile.ZipFile(stream) as archive:
            if archive.namelist() != sorted(entries):
                raise ReleaseInputError(refusal)
            for name in archive.namelist():
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as member:
                    while block := member.read(1024 * 1024):
                        digest.update(block)
                        size += len(block)
                if {"sha256": digest.hexdigest(), "bytes": size} != expected[name]:
                    raise ReleaseInputError(refusal)
    except ReleaseInputError:
        raise
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, KeyError):
        raise ReleaseInputError(refusal) from None


def write_deterministic_zip(root: Path, relative: str, entries: Mapping[str, ArchiveEntry]) -> dict[str, Any]:
    """Write ``deterministic_zip(entries)`` to ``root/relative`` entry by entry.

    The archive is never held in memory.  It is written straight to a new file
    (refused, like ``write_bytes``, if the path already exists) through one
    handle, and that same handle then computes the receipt from the bytes on
    disk and re-reads every member against its entry's receipt, so no other
    file can be substituted between writing and hashing.  On any failure the
    partial file this call created is removed and the original error raised.
    """

    relative = safe_relative(relative)
    target = root.joinpath(*PurePosixPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise ReleaseInputError(f"release output already exists: {relative}")
    with target.open("xb+") as stream:
        try:
            _write_deterministic_zip(stream, entries)
            stream.flush()
            stream.seek(0)
            digest = hashlib.sha256()
            size = 0
            while block := stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
            stream.seek(0)
            _verify_written_archive(stream, entries, relative)
        except BaseException:
            # Only the file this call created is removed, and a failure while
            # cleaning up never masks the original refusal.
            try:
                stream.close()
            except BaseException:
                pass
            try:
                target.unlink(missing_ok=True)
            except BaseException:
                pass
            raise
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
