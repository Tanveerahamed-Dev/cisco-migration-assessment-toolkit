"""Exact Git/worktree binding for deterministic Atlas release builds.

The compiler is the source-accounting authority, but a release may be built
later.  This module proves that the repository still is the compiler's exact
clean source state.  Restricted/metadata-only paths are compared through Git
index metadata and are deliberately never opened.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .compiler_bundle import CompilerBundle
from .model import ReleaseInputError, digest_object, read_bytes, sha256_bytes


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


def validate_exact_source(repo_root: Path, bundle: CompilerBundle) -> SourceValidation:
    """Revalidate one clean repository snapshot against a compiler bundle.

    All full-exposure tracked files are read atomically and hash-compared.
    Metadata-only paths are never opened: their identity is restricted to the
    Git path/mode/blob/stage tuple already captured by the compiler.
    """

    root = repo_root.resolve(strict=True)
    commit = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
    head_tree = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if status:
        raise ReleaseInputError("release repository has tracked worktree changes")
    entries = _census(root)
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

    file_records = bundle.records.get("files")
    if not isinstance(file_records, list):
        raise ReleaseInputError("compiler bundle retained no file census")
    by_path: dict[str, dict[str, Any]] = {}
    for record in file_records:
        path = record.get("path")
        if not isinstance(path, str) or not path or path in by_path:
            raise ReleaseInputError("compiler file census contains an invalid or duplicate path")
        by_path[path] = record
    entry_by_path = {entry.path: entry for entry in entries}
    if set(by_path) != set(entry_by_path):
        missing = sorted(set(entry_by_path) - set(by_path))
        extra = sorted(set(by_path) - set(entry_by_path))
        raise ReleaseInputError(
            f"compiler/Git tracked path census differs (missing={missing[:5]}, extra={extra[:5]})"
        )

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
            raw = read_bytes(root, path)
            digest = sha256_bytes(raw)
            if digest != record.get("content_digest"):
                raise ReleaseInputError(f"full-exposure file differs from compiler source: {path}")
            tree_rows.append({"path": path, "git_mode": entry.mode, "digest": digest})
            full_count += 1
        elif exposure == "metadata_only":
            tree_rows.append(
                {"path": path, "git_mode": entry.mode, "digest": f"git-object:{entry.blob_oid}"}
            )
            metadata_count += 1
        else:
            raise ReleaseInputError(f"compiler file has unsupported privacy exposure: {path}")
    tree_digest = digest_object(tree_rows)
    if tree_digest != bundle.source_tree_digest:
        raise ReleaseInputError("current source-tree digest differs from compiler source_tree_digest")

    return SourceValidation(
        source_commit=commit,
        head_tree_oid=head_tree,
        index_digest=index_digest,
        source_tree_digest=tree_digest,
        tracked_path_count=len(entries),
        full_exposure_file_count=full_count,
        metadata_only_file_count=metadata_count,
    )
