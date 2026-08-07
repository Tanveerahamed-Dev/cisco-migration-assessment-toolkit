"""Exact Git/tree and clean-worktree binding for Atlas release builds.

The compiler is the source-accounting authority, but a release may be built
later.  This module proves that the repository still is the compiler's exact
clean source state. Full-exposure bytes come from raw selected-commit Git blobs,
so checkout filters cannot alter custody. Restricted/metadata-only paths are
compared through Git metadata and are deliberately never opened.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .compiler_bundle import CompilerBundle
from .model import ReleaseInputError, digest_object, sha256_bytes


@dataclass(frozen=True)
class GitEntry:
    mode: str
    blob_oid: str
    stage: int
    path: str


@dataclass(frozen=True)
class SourceValidation:
    source_commit: str
    head_tree_oid: str
    index_digest: str
    source_tree_digest: str
    tracked_path_count: int
    full_exposure_file_count: int
    metadata_only_file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_commit": self.source_commit,
            "head_tree_oid": self.head_tree_oid,
            "index_digest": self.index_digest,
            "source_tree_digest": self.source_tree_digest,
            "repository_input_basis": "raw_selected_commit_git_blobs",
            "tracked_path_count": self.tracked_path_count,
            "full_exposure_file_count": self.full_exposure_file_count,
            "metadata_only_file_count": self.metadata_only_file_count,
            "tracked_worktree_dirty": False,
            "metadata_only_content_read": False,
        }


def _git(root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        process = subprocess.run(
            ["git", "-c", "core.quotepath=false", *arguments],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseInputError(f"could not execute Git {' '.join(arguments)}: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip().replace("\r", " ").replace("\n", " ")
        raise ReleaseInputError(
            f"git {' '.join(arguments)} failed ({process.returncode}): {detail[:500]}"
        )
    return process.stdout


def _decode_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReleaseInputError(f"Git path is not UTF-8: {exc}") from exc
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or parsed.as_posix() != path or ".." in parsed.parts:
        raise ReleaseInputError(f"unsafe or non-canonical Git path: {path!r}")
    return path


def _census(root: Path) -> list[GitEntry]:
    cached = [_decode_path(row) for row in _git(root, "ls-files", "--cached", "-z").split(b"\0") if row]
    stage_rows = [row for row in _git(root, "ls-files", "--stage", "-z").split(b"\0") if row]
    entries: list[GitEntry] = []
    for row in stage_rows:
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, blob_oid, stage_text = metadata.decode("ascii", errors="strict").split(" ")
            entries.append(GitEntry(mode, blob_oid, int(stage_text), _decode_path(raw_path)))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseInputError("could not parse git ls-files --stage record") from exc
    if cached != [entry.path for entry in entries]:
        raise ReleaseInputError("Git cached and staged censuses differ")
    if len(cached) != len(set(cached)):
        raise ReleaseInputError("duplicate paths in Git tracked-file census")
    if any(entry.stage != 0 for entry in entries):
        raise ReleaseInputError("Git index contains an unmerged stage")
    folded: dict[str, str] = {}
    for path in cached:
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise ReleaseInputError(f"case-fold path collision: {folded[key]} and {path}")
        folded[key] = path
    return entries


def _tree_census(root: Path, source_commit: str) -> list[GitEntry]:
    """Enumerate the selected commit tree independently of the Git index."""

    rows = [
        row
        for row in _git(root, "ls-tree", "-r", "--full-tree", "-z", source_commit).split(b"\0")
        if row
    ]
    entries: list[GitEntry] = []
    folded: dict[str, str] = {}
    for row in rows:
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, object_type, blob_oid = metadata.decode("ascii", errors="strict").split(" ")
            path = _decode_path(raw_path)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseInputError("could not parse git ls-tree record") from exc
        expected_type = "commit" if mode == "160000" else "blob"
        if object_type != expected_type:
            raise ReleaseInputError(
                f"selected commit tree has unexpected {object_type} object for mode {mode}: {path}"
            )
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise ReleaseInputError(f"case-fold path collision: {folded[key]} and {path}")
        folded[key] = path
        entries.append(GitEntry(mode, blob_oid, 0, path))
    paths = [entry.path for entry in entries]
    if len(paths) != len(set(paths)):
        raise ReleaseInputError("duplicate paths in selected commit tree census")
    return entries


def _nonstandard_index_flags(root: Path) -> dict[str, str]:
    """Return flags that allow a tracked worktree change to evade status."""

    result: dict[str, str] = {}
    for row in (item for item in _git(root, "ls-files", "-v", "-z").split(b"\0") if item):
        if len(row) < 3 or row[1:2] != b" ":
            raise ReleaseInputError("could not parse git ls-files -v record")
        try:
            tag = row[:1].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReleaseInputError("Git index flag is not ASCII") from exc
        path = _decode_path(row[2:])
        if tag != "H":
            result[path] = tag
    return result


def _read_git_blobs(root: Path, entries: list[GitEntry]) -> dict[str, bytes]:
    if not entries:
        return {}
    if any(entry.mode == "160000" for entry in entries):
        raise ReleaseInputError("Git links cannot be read as full-exposure blobs")
    request = b"".join(entry.blob_oid.encode("ascii") + b"\n" for entry in entries)
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        process = subprocess.run(
            ["git", "-c", "core.quotepath=false", "cat-file", "--batch"],
            cwd=root,
            env=environment,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseInputError(f"could not execute Git blob batch: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip().replace("\r", " ").replace("\n", " ")
        raise ReleaseInputError(f"Git blob batch failed ({process.returncode}): {detail[:500]}")

    output = process.stdout
    cursor = 0
    result: dict[str, bytes] = {}
    for entry in entries:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise ReleaseInputError(f"Git blob batch response is truncated: {entry.path}")
        try:
            actual_oid, object_type, size_text = output[cursor:header_end].decode("ascii").split(" ")
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseInputError(f"Git blob batch header is invalid: {entry.path}") from exc
        start = header_end + 1
        end = start + size
        if (
            actual_oid != entry.blob_oid
            or object_type != "blob"
            or size < 0
            or end >= len(output)
            or output[end : end + 1] != b"\n"
        ):
            raise ReleaseInputError(f"Git blob batch identity, type, or size mismatch: {entry.path}")
        raw = output[start:end]
        header = f"blob {len(raw)}\0".encode("ascii")
        algorithm = hashlib.sha1 if len(entry.blob_oid) == 40 else hashlib.sha256
        if algorithm(header + raw).hexdigest() != entry.blob_oid:
            raise ReleaseInputError(f"Git blob object identity mismatch: {entry.path}")
        result[entry.path] = raw
        cursor = end + 1
    if cursor != len(output):
        raise ReleaseInputError("Git blob batch returned unexpected trailing output")
    return result


def read_bound_source_blob(repo_root: Path, bundle: CompilerBundle, relative: str) -> bytes:
    """Read one compiler-approved full-exposure path from its selected Git blob."""

    records = bundle.records.get("files")
    if not isinstance(records, list):
        raise ReleaseInputError("compiler bundle retained no file census")
    matches = [item for item in records if item.get("path") == relative]
    if len(matches) != 1:
        raise ReleaseInputError(f"release input is absent or duplicated in compiler census: {relative}")
    record = matches[0]
    if record.get("privacy_exposure") != "full":
        raise ReleaseInputError(f"release input is not approved for full exposure: {relative}")
    if record.get("content_source") != "selected_commit_git_blob":
        raise ReleaseInputError(f"release input does not declare selected-commit blob custody: {relative}")
    entry = GitEntry(
        mode=str(record.get("git_mode") or ""),
        blob_oid=str(record.get("git_blob_oid") or ""),
        stage=int(record.get("git_stage") or 0),
        path=relative,
    )
    raw = _read_git_blobs(repo_root.resolve(strict=True), [entry])[relative]
    if len(raw) != record.get("size_bytes") or sha256_bytes(raw) != record.get("content_digest"):
        raise ReleaseInputError(f"selected-commit Git blob differs from compiler source: {relative}")
    return raw


def validate_exact_source(repo_root: Path, bundle: CompilerBundle) -> SourceValidation:
    """Revalidate one clean repository snapshot against a compiler bundle.

    All full-exposure tracked files are read from raw Git blobs and
    hash-compared. Metadata-only paths are never opened: their identity is
    restricted to the Git path/mode/blob/stage tuple already captured by the
    compiler. The tracked worktree and index are checked before and after.
    """

    root = repo_root.resolve(strict=True)
    commit = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    head_tree = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if status:
        raise ReleaseInputError("release repository has tracked worktree changes")
    nonstandard_index_flags = _nonstandard_index_flags(root)
    if nonstandard_index_flags:
        path, tag = sorted(nonstandard_index_flags.items())[0]
        raise ReleaseInputError(
            "full-exposure file differs from compiler source or cannot be proven because "
            f"Git index flag {tag!r} hides worktree state: {path}"
        )
    entries = _census(root)
    commit_entries = _tree_census(root, commit)
    index_rows = [
        {"mode": row.mode, "blob_oid": row.blob_oid, "stage": row.stage, "path": row.path}
        for row in entries
    ]
    index_digest = digest_object(index_rows)

    if commit != bundle.source_commit:
        raise ReleaseInputError("repository HEAD differs from compiler source_commit")
    if head_tree != bundle.manifest.get("head_tree_oid"):
        raise ReleaseInputError("repository HEAD tree differs from compiler head_tree_oid")
    if index_digest != bundle.manifest.get("index_digest"):
        raise ReleaseInputError("repository Git index census differs from compiler index_digest")
    if entries != commit_entries:
        raise ReleaseInputError("clean Git index census differs from selected commit tree census")

    file_records = bundle.records.get("files")
    if not isinstance(file_records, list):
        raise ReleaseInputError("compiler bundle retained no file census")
    by_path: dict[str, dict[str, Any]] = {}
    for record in file_records:
        path = record.get("path")
        if not isinstance(path, str) or not path or path in by_path:
            raise ReleaseInputError("compiler file census contains an invalid or duplicate path")
        by_path[path] = record
    entry_by_path = {entry.path: entry for entry in commit_entries}
    if set(by_path) != set(entry_by_path):
        missing = sorted(set(entry_by_path) - set(by_path))
        extra = sorted(set(by_path) - set(entry_by_path))
        raise ReleaseInputError(
            f"compiler/Git tracked path census differs (missing={missing[:5]}, extra={extra[:5]})"
        )

    full_entries = [
        entry_by_path[path]
        for path, record in sorted(by_path.items())
        if record.get("privacy_exposure") == "full"
    ]
    full_blobs = _read_git_blobs(root, full_entries)
    tree_rows: list[dict[str, str]] = []
    full_count = 0
    metadata_count = 0
    for path, record in sorted(by_path.items()):
        entry = entry_by_path[path]
        if (
            record.get("git_mode") != entry.mode
            or record.get("git_blob_oid") != entry.blob_oid
            or record.get("git_stage") != entry.stage
        ):
            raise ReleaseInputError(f"compiler/Git index metadata differs: {path}")
        exposure = record.get("privacy_exposure")
        if exposure == "full":
            if record.get("classification_errors"):
                raise ReleaseInputError(f"full-exposure compiler file has classification errors: {path}")
            if record.get("content_source") != "selected_commit_git_blob":
                raise ReleaseInputError(f"full-exposure file lacks selected-commit blob custody: {path}")
            raw = full_blobs[path]
            digest = sha256_bytes(raw)
            if digest != record.get("content_digest") or len(raw) != record.get("size_bytes"):
                raise ReleaseInputError(f"full-exposure Git blob differs from compiler source: {path}")
            tree_rows.append({"path": path, "git_mode": entry.mode, "digest": digest})
            full_count += 1
        elif exposure == "metadata_only":
            if record.get("content_source") != "metadata_only_git_object":
                raise ReleaseInputError(f"metadata-only file has an invalid content source: {path}")
            tree_rows.append(
                {"path": path, "git_mode": entry.mode, "digest": f"git-object:{entry.blob_oid}"}
            )
            metadata_count += 1
        else:
            raise ReleaseInputError(f"compiler file has unsupported privacy exposure: {path}")
    tree_digest = digest_object(tree_rows)
    if tree_digest != bundle.source_tree_digest:
        raise ReleaseInputError("current source-tree digest differs from compiler source_tree_digest")

    status_after = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    commit_after = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    head_tree_after = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
    entries_after = _census(root)
    commit_entries_after = _tree_census(root, commit_after)
    index_digest_after = digest_object(
        [
            {"mode": row.mode, "blob_oid": row.blob_oid, "stage": row.stage, "path": row.path}
            for row in entries_after
        ]
    )
    if (
        status_after != status
        or commit_after != commit
        or head_tree_after != head_tree
        or index_digest_after != index_digest
        or commit_entries_after != commit_entries
    ):
        raise ReleaseInputError("repository source state changed during exact-source validation")

    return SourceValidation(
        source_commit=commit,
        head_tree_oid=head_tree,
        index_digest=index_digest,
        source_tree_digest=tree_digest,
        tracked_path_count=len(entries),
        full_exposure_file_count=full_count,
        metadata_only_file_count=metadata_count,
    )
