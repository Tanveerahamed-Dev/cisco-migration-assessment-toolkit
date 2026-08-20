"""Read-only, content-bound Git state observation for continuity receipts."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .model import ContinuityInputError, digest_object, safe_relative, sha256_bytes


_RESTRICTED_PARTS = frozenset(
    {
        ".obsidian",
        "captures",
        "client-data",
        "client_data",
        "credentials",
        "private-inputs",
        "raw-captures",
        "secrets",
        "vault",
    }
)


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
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContinuityInputError(f"git command could not run: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
        raise ContinuityInputError(
            f"git {' '.join(arguments)} failed ({process.returncode}): {' '.join(detail.split())[:500]}"
        )
    return process.stdout


def _decode_paths(value: bytes) -> list[str]:
    result: list[str] = []
    for item in value.split(b"\0"):
        if not item:
            continue
        try:
            path = item.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ContinuityInputError("Git returned a non-UTF-8 path") from exc
        result.append(safe_relative(PurePosixPath(path).as_posix()))
    return result


def _tree(root: Path, revision: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for item in _git(root, "ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not item:
            continue
        try:
            metadata, raw_path = item.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            path = safe_relative(PurePosixPath(raw_path.decode("utf-8", errors="strict")).as_posix())
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContinuityInputError("could not parse git ls-tree output") from exc
        rows[path] = {"mode": mode, "kind": kind, "object_id": object_id}
    return rows


def _is_restricted(path: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    name = parts[-1] if parts else ""
    return (
        any(part in _RESTRICTED_PARTS for part in parts)
        or name == ".env"
        or name.startswith(".env.")
        or "credential" in name
        or "private-key" in name
        or "private_key" in name
        or "secret" in name
    )


def _material(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"kind": "deleted", "sha256": None, "bytes": 0, "restricted": False}
    if _is_restricted(relative):
        return {"kind": "restricted", "sha256": None, "bytes": metadata.st_size, "restricted": True}
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path).encode("utf-8", errors="strict")
        return {"kind": "symlink", "sha256": sha256_bytes(target), "bytes": len(target), "restricted": False}
    if not stat.S_ISREG(metadata.st_mode):
        return {"kind": "unsupported", "sha256": None, "bytes": metadata.st_size, "restricted": False}
    before = path.stat(follow_symlinks=False)
    value = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or len(value) != after.st_size:
        raise ContinuityInputError(f"file changed while continuity state was read: {relative}")
    return {
        "kind": "regular",
        "sha256": sha256_bytes(value),
        "bytes": len(value),
        "restricted": False,
    }


def observe_git_state(repository_root: Path, baseline_commit: str) -> dict[str, Any]:
    root = repository_root.resolve(strict=True)
    if not root.is_dir():
        raise ContinuityInputError("repository root is not a directory")
    top = Path(_git(root, "rev-parse", "--show-toplevel").decode("utf-8", errors="strict").strip()).resolve()
    if top != root:
        raise ContinuityInputError("repository root must be the exact Git worktree root")
    baseline = _git(root, "rev-parse", f"{baseline_commit}^{{commit}}").decode("ascii").strip()
    if baseline != baseline_commit:
        raise ContinuityInputError("baseline commit is not an exact canonical commit id")
    baseline_tree_id = _git(root, "rev-parse", f"{baseline}^{{tree}}").decode("ascii").strip()
    head_commit = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    head_tree_id = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    tracked_status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    changed = set(_decode_paths(_git(root, "diff", "--name-only", "-z", baseline, "--")))
    changed.update(_decode_paths(_git(root, "diff", "--name-only", "--diff-filter=D", "-z", baseline, "--")))
    baseline_tree = _tree(root, baseline)
    head_tree = _tree(root, "HEAD")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if tracked_status:
        errors.append("tracked_status_not_clean")
    for path in sorted(changed):
        material = _material(root, path)
        if material["restricted"]:
            errors.append(f"restricted_path_in_diff:{path}")
        if material["kind"] == "unsupported":
            errors.append(f"unsupported_path_kind:{path}")
        rows.append(
            {
                "path": path,
                "baseline": baseline_tree.get(path),
                "head": head_tree.get(path),
                "worktree": material,
            }
        )
    return {
        "baseline_commit": baseline,
        "baseline_tree": baseline_tree_id,
        "head_commit": head_commit,
        "head_tree": head_tree_id,
        "changed_paths": sorted(changed),
        "diff_digest": digest_object(rows),
        "tracked_status_digest": sha256_bytes(tracked_status),
        "tracked_status_clean": not tracked_status,
        "material_rows": rows,
        "errors": sorted(set(errors)),
    }
