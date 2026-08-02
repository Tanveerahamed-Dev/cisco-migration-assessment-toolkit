"""Prove that a workflow checkout still equals its captured commit and tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_TREE_MODES = {"100644", "100755"}


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        capture_output=True,
    )


def _object_id(root: Path, expression: str) -> str:
    return (
        _git(root, "rev-parse", expression)
        .stdout.decode("ascii", errors="strict")
        .strip()
        .casefold()
    )


def _normalise_allowed_prefixes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalised: list[str] = []
    for value in values:
        raw = value.strip().rstrip("/")
        path = Path(raw)
        posix = raw.replace("\\", "/")
        if (
            not raw
            or path.is_absolute()
            or "\\" in raw
            or any(part in {"", ".", ".."} for part in posix.split("/"))
            or posix == ".git"
            or posix.startswith(".git/")
        ):
            raise ValueError(f"unsafe allowed-untracked prefix: {value!r}")
        normalised.append(posix + "/")
    return tuple(sorted(set(normalised)))


def _decode_repository_path(raw: bytes) -> str:
    path = raw.decode(
        "utf-8",
        errors="surrogateescape",
    )
    pure = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or pure.is_absolute()
        or pure.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure.parts)
        or path == ".git"
        or path.startswith(".git/")
    ):
        raise ValueError(f"Git contains an unsafe repository path: {path!r}")
    return path


def _tree_entries(root: Path) -> dict[str, tuple[str, str]]:
    raw = _git(
        root,
        "ls-tree",
        "-rz",
        "--full-tree",
        "HEAD",
    ).stdout
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = header.decode("ascii", errors="strict").split()
            path = _decode_repository_path(raw_path)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Git tree contains an unreadable entry") from exc
        if (
            kind != "blob"
            or mode not in _TREE_MODES
            or path in entries
            or not _OBJECT_ID.fullmatch(object_id)
        ):
            raise ValueError(f"unsupported or duplicate Git tree entry: {path!r}")
        entries[path] = (mode, object_id)
    if not entries:
        raise ValueError("Git tree has no ordinary files")
    return entries


def _index_entries(root: Path) -> dict[str, tuple[str, str]]:
    raw = _git(root, "ls-files", "-s", "-z").stdout
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, object_id, stage = header.decode(
                "ascii",
                errors="strict",
            ).split()
            path = _decode_repository_path(raw_path)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Git index contains an unreadable entry") from exc
        if (
            stage != "0"
            or path in entries
            or not _OBJECT_ID.fullmatch(object_id)
        ):
            raise ValueError(f"unmerged or duplicate Git index entry: {path!r}")
        entries[path] = (mode, object_id)

    flags_raw = _git(root, "ls-files", "-v", "-z").stdout
    flagged: list[str] = []
    flag_paths: set[str] = set()
    for record in flags_raw.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise ValueError("Git index flags are unreadable")
        path = _decode_repository_path(record[2:])
        flag_paths.add(path)
        if record[:1] != b"H":
            flagged.append(f"{record[:1].decode('ascii', errors='replace')} {path}")
    if flag_paths != set(entries):
        raise ValueError("Git index flag inventory differs from stage-zero inventory")
    if flagged:
        raise ValueError(
            "Git index contains assume-unchanged, skip-worktree, or "
            f"non-cached entries: {sorted(flagged)}"
        )
    return entries


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _is_reparse_point(info: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(int(getattr(info, "st_file_attributes", 0)) & attribute)


def _worktree_blob_id(
    path: Path,
    *,
    algorithm: str,
    expected_mode: str,
) -> str:
    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ValueError(f"tracked path is not an ordinary non-link file: {path}")
    if os.name != "nt":
        executable = bool(before.st_mode & 0o111)
        if executable != (expected_mode == "100755"):
            raise ValueError(f"tracked executable mode differs from Git: {path}")

    digest = hashlib.new(algorithm)
    digest.update(f"blob {before.st_size}\0".encode("ascii"))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_identity(opened) != _file_identity(before)
        ):
            raise ValueError(f"tracked file identity changed before read: {path}")
        for block in iter(lambda: os.read(descriptor, 1024 * 1024), b""):
            digest.update(block)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = path.lstat()
    identities = {
        _file_identity(before),
        _file_identity(opened),
        _file_identity(after_open),
        _file_identity(after_path),
    }
    if (
        len(identities) != 1
        or stat.S_ISLNK(after_path.st_mode)
        or _is_reparse_point(after_path)
        or not stat.S_ISREG(after_path.st_mode)
    ):
        raise ValueError(f"tracked file identity changed during read: {path}")
    return digest.hexdigest()


def _verify_tracked_bytes(
    root: Path,
    tree_entries: dict[str, tuple[str, str]],
) -> None:
    algorithm = (
        _git(root, "rev-parse", "--show-object-format")
        .stdout.decode("ascii", errors="strict")
        .strip()
    )
    if algorithm not in {"sha1", "sha256"}:
        raise ValueError(f"unsupported Git object format: {algorithm!r}")
    mismatches: list[str] = []
    for name, (mode, expected_object_id) in sorted(tree_entries.items()):
        path = root.joinpath(*name.split("/"))
        try:
            actual_object_id = _worktree_blob_id(
                path,
                algorithm=algorithm,
                expected_mode=mode,
            )
        except (OSError, ValueError) as exc:
            mismatches.append(f"{name}: {exc}")
            continue
        if actual_object_id != expected_object_id:
            mismatches.append(name)
    if mismatches:
        raise ValueError(
            "tracked checkout bytes differ from immutable HEAD: "
            f"{mismatches[:20]}"
        )


def _untracked_paths(root: Path) -> tuple[str, ...]:
    raw = _git(
        root,
        "ls-files",
        "-z",
        "--others",
        "--directory",
        "--no-empty-directory",
    ).stdout
    paths: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        directory = item.endswith(b"/")
        path = _decode_repository_path(item[:-1] if directory else item)
        paths.append(path + "/" if directory else path)
    return tuple(sorted(paths))


def _checkout_observation(
    root: Path,
    expected_commit: str,
    expected_tree: str,
    allowed_untracked_prefixes: tuple[str, ...],
) -> tuple[str, str, int, tuple[str, ...]]:
    actual_commit = _object_id(root, "HEAD^{commit}")
    actual_tree = _object_id(root, "HEAD^{tree}")
    if actual_commit != expected_commit.casefold():
        raise ValueError(
            f"checkout commit changed: {actual_commit} != {expected_commit}"
        )
    if actual_tree != expected_tree.casefold():
        raise ValueError(
            f"checkout tree changed: {actual_tree} != {expected_tree}"
        )
    tree_entries = _tree_entries(root)
    index_entries = _index_entries(root)
    if tree_entries != index_entries:
        raise ValueError("Git index differs from the immutable HEAD tree")
    _verify_tracked_bytes(root, tree_entries)
    paths = _untracked_paths(root)
    unexpected_paths = tuple(
        name
        for name in paths
        if not any(
            name.startswith(prefix)
            for prefix in allowed_untracked_prefixes
        )
    )
    if unexpected_paths:
        raise ValueError(
            "checkout has unapproved untracked files, including ignored files: "
            f"{list(unexpected_paths[:20])}"
        )
    return actual_commit, actual_tree, len(tree_entries), paths


def verify_checkout(
    root: Path,
    expected_commit: str,
    expected_tree: str,
    *,
    allowed_untracked_prefixes: tuple[str, ...] = (),
) -> dict:
    for label, value in (
        ("expected commit", expected_commit),
        ("expected tree", expected_tree),
    ):
        if not _OBJECT_ID.fullmatch(value):
            raise ValueError(f"{label} is not a full Git object ID")

    allowed_prefixes = _normalise_allowed_prefixes(allowed_untracked_prefixes)
    first = _checkout_observation(
        root,
        expected_commit,
        expected_tree,
        allowed_prefixes,
    )
    second = _checkout_observation(
        root,
        expected_commit,
        expected_tree,
        allowed_prefixes,
    )
    if first != second:
        raise ValueError("checkout identity changed while it was being verified")
    actual_commit, actual_tree, tracked_files, paths = second
    return {
        "commit": actual_commit,
        "tree": actual_tree,
        "tracked_files_verified": tracked_files,
        "untracked_entries": len(paths),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument(
        "--allow-untracked-prefix",
        action="append",
        default=[],
        help="allow generated files only below this repository-relative directory",
    )
    arguments = parser.parse_args(argv)
    try:
        result = verify_checkout(
            arguments.root.resolve(),
            arguments.expected_commit,
            arguments.expected_tree,
            allowed_untracked_prefixes=tuple(arguments.allow_untracked_prefix),
        )
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"immutable checkout verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
