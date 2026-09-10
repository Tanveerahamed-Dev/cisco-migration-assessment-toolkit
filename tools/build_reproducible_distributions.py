#!/usr/bin/env python3
"""Build one wheel and one sdist twice with a commit-bound deterministic timestamp.

The first build supplies the artifacts retained in the requested output directory. The second
build is temporary. Success requires identical archive names and bytes across both builds. The
timestamp is never caller-selected: it is the exact Git commit time of the separately supplied
and verified source commit, exposed to PEP 517 backends through SOURCE_DATE_EPOCH.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from typing import BinaryIO, Iterator
import uuid


ROOT = Path(__file__).resolve().parents[1]
_FULL_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_ZIP_MINIMUM_EPOCH = 315_532_800
_GZIP_MAXIMUM_EPOCH = 4_294_967_295
_MAX_SDIST_MEMBERS = 10_000
_MAX_SDIST_BYTES = 268_435_456
_MAX_ARCHIVE_BYTES = 536_870_912
_ALLOWED_PAX_KEYS = frozenset({"mtime", "path"})
_REGULAR_TAR_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE})
_WINDOWS_RESERVED_PARTS = frozenset(
    {"aux", "con", "nul", "prn"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_GIT_CANDIDATE = shutil.which("git")
_GIT_EXECUTABLE = (
    str(Path(_GIT_CANDIDATE).resolve(strict=True))
    if _GIT_CANDIDATE is not None
    else ""
)


class ReproducibleBuildError(RuntimeError):
    """The selected source or one of the two archive builds failed the closed contract."""


def _trusted_git_executable() -> str:
    if not _GIT_EXECUTABLE:
        raise ReproducibleBuildError("GIT_EXECUTABLE_UNAVAILABLE")
    try:
        value = os.lstat(_GIT_EXECUTABLE)
    except OSError:
        raise ReproducibleBuildError("GIT_EXECUTABLE_UNAVAILABLE") from None
    reparse = int(getattr(value, "st_file_attributes", 0)) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or reparse
        or value.st_size < 1
        or value.st_size > _MAX_ARCHIVE_BYTES
    ):
        raise ReproducibleBuildError("GIT_EXECUTABLE_INVALID")
    return _GIT_EXECUTABLE


def _bind_trusted_git(environment: dict[str, str]) -> dict[str, str]:
    bound = dict(environment)
    git_directory = str(Path(_trusted_git_executable()).parent)
    existing = bound.get("PATH", "")
    bound["PATH"] = git_directory + (os.pathsep + existing if existing else "")
    return bound


def _clean_environment(*, epoch: int | None = None) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if epoch is not None:
        environment["SOURCE_DATE_EPOCH"] = str(epoch)
    return environment


def _build_environment(epoch: int, lane_root: Path) -> dict[str, str]:
    if lane_root.exists():
        raise ReproducibleBuildError("BUILD_ENVIRONMENT_EXISTS")
    lane_root.mkdir()
    directories = {
        name: lane_root / name
        for name in ("appdata", "cache", "home", "localappdata", "pip-cache", "pycache", "temp")
    }
    for directory in directories.values():
        directory.mkdir()
    environment = _clean_environment(epoch=epoch)
    environment.update(
        {
            "APPDATA": str(directories["appdata"]),
            "HOME": str(directories["home"]),
            "LOCALAPPDATA": str(directories["localappdata"]),
            "PIP_CACHE_DIR": str(directories["pip-cache"]),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",
            "PYTHONPYCACHEPREFIX": str(directories["pycache"]),
            "TEMP": str(directories["temp"]),
            "TMP": str(directories["temp"]),
            "TMPDIR": str(directories["temp"]),
            "TZ": "UTC",
            "USERPROFILE": str(directories["home"]),
            "UV_CACHE_DIR": str(directories["cache"] / "uv"),
            "XDG_CACHE_HOME": str(directories["cache"]),
        }
    )
    return environment


def _git_text(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            [_trusted_git_executable(), "--no-replace-objects", *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            env=_bind_trusted_git(_clean_environment()),
            text=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ReproducibleBuildError("SOURCE_GIT_QUERY_FAILED") from None
    if completed.returncode != 0 or len(completed.stdout) > 256:
        raise ReproducibleBuildError("SOURCE_GIT_QUERY_FAILED")
    try:
        value = completed.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError:
        raise ReproducibleBuildError("SOURCE_GIT_OUTPUT_INVALID") from None
    if not value or "\n" in value or "\r" in value:
        raise ReproducibleBuildError("SOURCE_GIT_OUTPUT_INVALID")
    return value


def source_date_epoch(
    repository: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> int:
    if not _FULL_SHA1.fullmatch(expected_commit) or not _FULL_SHA1.fullmatch(expected_tree):
        raise ReproducibleBuildError("SOURCE_IDENTITY_INVALID")
    observed_commit = _git_text(repository, "rev-parse", "--verify", "HEAD^{commit}")
    observed_tree = _git_text(
        repository,
        "rev-parse",
        "--verify",
        f"{observed_commit}^{{tree}}",
    )
    if observed_commit != expected_commit or observed_tree != expected_tree:
        raise ReproducibleBuildError("SOURCE_IDENTITY_MISMATCH")
    epoch_text = _git_text(
        repository,
        "show",
        "-s",
        "--no-show-signature",
        "--format=%ct",
        expected_commit,
    )
    if not epoch_text.isascii() or not epoch_text.isdigit() or len(epoch_text) > 10:
        raise ReproducibleBuildError("SOURCE_TIMESTAMP_INVALID")
    epoch = int(epoch_text)
    if epoch < _ZIP_MINIMUM_EPOCH or epoch > _GZIP_MAXIMUM_EPOCH:
        raise ReproducibleBuildError("SOURCE_DATE_EPOCH_OUT_OF_RANGE")
    return epoch


def _is_reparse_point(value: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(int(getattr(value, "st_file_attributes", 0)) & attribute)


def _handle_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _path_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


@contextmanager
def _stable_reader(
    path: Path,
    *,
    maximum_bytes: int = _MAX_ARCHIVE_BYTES,
) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or _is_reparse_point(before)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > maximum_bytes
        ):
            raise ReproducibleBuildError("ARCHIVE_FILE_INVALID")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        handle = os.fdopen(descriptor, "rb")
    except ReproducibleBuildError:
        raise
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_FILE_INVALID") from None

    try:
        opened = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse_point(opened)
            or _path_identity(opened) != _path_identity(before)
        ):
            raise ReproducibleBuildError("ARCHIVE_FILE_INVALID")
        yield handle, opened
        after_handle = os.fstat(handle.fileno())
    finally:
        handle.close()

    try:
        after_path = path.lstat()
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_FILE_CHANGED_DURING_READ") from None
    if (
        _handle_identity(after_handle) != _handle_identity(opened)
        or _path_identity(after_path) != _path_identity(opened)
        or not stat.S_ISREG(after_path.st_mode)
        or stat.S_ISLNK(after_path.st_mode)
        or _is_reparse_point(after_path)
    ):
        raise ReproducibleBuildError("ARCHIVE_FILE_CHANGED_DURING_READ")


def _stream_payload(
    source: BinaryIO,
    expected_size: int,
    *,
    destination: BinaryIO | None = None,
) -> str:
    digest = hashlib.sha256()
    remaining = expected_size
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ReproducibleBuildError("SDIST_MEMBER_SIZE_MISMATCH")
        remaining -= len(chunk)
        digest.update(chunk)
        if destination is not None:
            destination.write(chunk)
    if source.read(1):
        raise ReproducibleBuildError("SDIST_MEMBER_SIZE_MISMATCH")
    return digest.hexdigest()


@contextmanager
def _stable_sdist(path: Path) -> Iterator[tarfile.TarFile]:
    with _stable_reader(path) as (source, _identity):
        with tarfile.open(fileobj=source, mode="r|gz", errorlevel=2) as archive:
            yield archive


def _archive_set_observation(
    directory: Path,
) -> tuple[
    dict[str, Path],
    tuple[
        tuple[int, int, int, int, int, int],
        tuple[tuple[str, tuple[int, int, int, int, int, int]], ...],
    ],
]:
    try:
        directory_before = directory.lstat()
        if (
            not stat.S_ISDIR(directory_before.st_mode)
            or stat.S_ISLNK(directory_before.st_mode)
            or _is_reparse_point(directory_before)
        ):
            raise ReproducibleBuildError("ARCHIVE_SET_INVALID")
        entries = sorted(directory.iterdir())
    except ReproducibleBuildError:
        raise
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID") from None
    if len(entries) != 2:
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID")
    member_identities = []
    for path in entries:
        try:
            value = path.lstat()
        except OSError:
            raise ReproducibleBuildError("ARCHIVE_SET_INVALID") from None
        if (
            not stat.S_ISREG(value.st_mode)
            or stat.S_ISLNK(value.st_mode)
            or _is_reparse_point(value)
            or value.st_nlink != 1
            or value.st_size < 0
            or value.st_size > _MAX_ARCHIVE_BYTES
        ):
            raise ReproducibleBuildError("ARCHIVE_SET_INVALID")
        member_identities.append((path.name, _handle_identity(value)))
    wheel = [path for path in entries if path.name.endswith(".whl")]
    sdist = [path for path in entries if path.name.endswith(".tar.gz")]
    if len(wheel) != 1 or len(sdist) != 1:
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID")
    try:
        directory_after = directory.lstat()
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID") from None
    if (
        not stat.S_ISDIR(directory_after.st_mode)
        or stat.S_ISLNK(directory_after.st_mode)
        or _is_reparse_point(directory_after)
        or _directory_identity(directory_before) != _directory_identity(directory_after)
    ):
        raise ReproducibleBuildError("ARCHIVE_SET_CHANGED_DURING_OBSERVATION")
    archives = {path.name: path for path in entries}
    observation = (_directory_identity(directory_after), tuple(member_identities))
    return archives, observation


def _archives(directory: Path) -> dict[str, Path]:
    archives, _observation = _archive_set_observation(directory)
    return archives


def _single_archive(directory: Path, suffix: str) -> Path:
    try:
        entries = list(directory.iterdir())
        value = entries[0].lstat() if len(entries) == 1 else None
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID") from None
    if len(entries) != 1 or value is None or (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or _is_reparse_point(value)
        or value.st_nlink != 1
        or not entries[0].name.endswith(suffix)
        or value.st_size < 0
        or value.st_size > _MAX_ARCHIVE_BYTES
    ):
        raise ReproducibleBuildError("ARCHIVE_SET_INVALID")
    return entries[0]


def _safe_sdist_member(member: tarfile.TarInfo, seen: set[str]) -> None:
    name = member.name
    parts = name.split("/")
    portable_key = "/".join(unicodedata.normalize("NFC", part).casefold() for part in parts)
    invalid_part = any(
        part != part.rstrip(" .")
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_PARTS
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in part)
        for part in parts
    )
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(":" in part for part in parts)
        or any(part in ("", ".", "..") for part in parts)
        or invalid_part
        or portable_key in seen
        or member.type not in _REGULAR_TAR_TYPES | {tarfile.DIRTYPE}
        or set(member.pax_headers) - _ALLOWED_PAX_KEYS
        or member.size < 0
    ):
        raise ReproducibleBuildError("SDIST_MEMBER_INVALID")
    seen.add(portable_key)


def _sdist_payload_manifest(path: Path) -> tuple[tuple[str, str, int, str], ...]:
    manifest = []
    seen: set[str] = set()
    total = 0
    try:
        with _stable_sdist(path) as archive:
            if archive.pax_headers:
                raise ReproducibleBuildError("SDIST_MEMBER_INVALID")
            count = 0
            for count, member in enumerate(archive, 1):
                if count > _MAX_SDIST_MEMBERS:
                    raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")
                _safe_sdist_member(member, seen)
                total += member.size
                if total > _MAX_SDIST_BYTES:
                    raise ReproducibleBuildError("SDIST_CONTENT_LIMIT_EXCEEDED")
                if member.isdir():
                    manifest.append((member.name, "directory", 0, ""))
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ReproducibleBuildError("SDIST_MEMBER_UNREADABLE")
                with extracted:
                    digest = _stream_payload(extracted, member.size)
                manifest.append((member.name, "file", member.size, digest))
            if count == 0:
                raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")
    except ReproducibleBuildError:
        raise
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise ReproducibleBuildError("SDIST_CANONICALIZATION_FAILED") from None
    return tuple(manifest)


def _canonicalize_sdist(path: Path, epoch: int) -> None:
    """Normalize the backend sdist container without changing member names or payload bytes."""
    temporary_path: Path | None = None
    tar_bytes = None
    try:
        with _stable_sdist(path) as source:
            if source.pax_headers:
                raise ReproducibleBuildError("SDIST_MEMBER_INVALID")
            seen: set[str] = set()
            total = 0
            expected_manifest = []
            tar_bytes = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode="w+b")
            with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as target:
                count = 0
                for count, original in enumerate(source, 1):
                    if count > _MAX_SDIST_MEMBERS:
                        raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")
                    _safe_sdist_member(original, seen)
                    total += original.size
                    if total > _MAX_SDIST_BYTES:
                        raise ReproducibleBuildError("SDIST_CONTENT_LIMIT_EXCEEDED")
                    normalized = copy(original)
                    normalized.uid = 0
                    normalized.gid = 0
                    normalized.uname = ""
                    normalized.gname = ""
                    normalized.mtime = epoch
                    normalized.mode = (
                        0o755
                        if original.isdir() or original.mode & 0o111
                        else 0o644
                    )
                    normalized.pax_headers = {}
                    if original.isdir():
                        normalized.size = 0
                        target.addfile(normalized)
                        expected_manifest.append((original.name, "directory", 0, ""))
                        continue
                    extracted = source.extractfile(original)
                    if extracted is None:
                        raise ReproducibleBuildError("SDIST_MEMBER_UNREADABLE")
                    with extracted, tempfile.SpooledTemporaryFile(
                        max_size=8 * 1024 * 1024,
                        mode="w+b",
                    ) as payload:
                        digest = _stream_payload(
                            extracted,
                            original.size,
                            destination=payload,
                        )
                        payload.seek(0)
                        target.addfile(normalized, payload)
                    expected_manifest.append(
                        (original.name, "file", original.size, digest)
                    )

            if count == 0:
                raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")

        tar_bytes.seek(0)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".canonical",
            dir=path.parent,
            delete=False,
        ) as raw:
            temporary_path = Path(raw.name)
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=epoch,
            ) as compressed:
                shutil.copyfileobj(tar_bytes, compressed, length=1024 * 1024)
        if _sdist_payload_manifest(temporary_path) != tuple(expected_manifest):
            raise ReproducibleBuildError("SDIST_PAYLOAD_CHANGED")
        os.replace(temporary_path, path)
        temporary_path = None
    except ReproducibleBuildError:
        raise
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise ReproducibleBuildError("SDIST_CANONICALIZATION_FAILED") from None
    finally:
        if tar_bytes is not None:
            tar_bytes.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _run_build(
    repository: Path,
    output: Path,
    epoch: int,
    *,
    kind: str,
    lane_root: Path,
) -> None:
    if kind not in {"sdist", "wheel"}:
        raise ReproducibleBuildError("ARCHIVE_KIND_INVALID")
    environment = _bind_trusted_git(_build_environment(epoch, lane_root))
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                f"--{kind}",
                "--outdir",
                str(output),
            ],
            cwd=repository,
            env=environment,
            check=False,
        )
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_BUILD_FAILED") from None
    if completed.returncode != 0:
        raise ReproducibleBuildError("ARCHIVE_BUILD_FAILED")


def _verify_source(
    repository: Path,
    *,
    expected_commit: str,
    expected_tree: str,
    allow_build_outputs: bool = False,
    allow_node_modules: bool = False,
    staged_output: Path | None = None,
) -> None:
    verifier = repository / ".github" / "scripts" / "verify_checkout_immutable.py"
    command = [
        sys.executable,
        "-I",
        "-B",
        str(verifier),
        "--root",
        str(repository),
        "--expected-commit",
        expected_commit,
        "--expected-tree",
        expected_tree,
    ]
    if allow_node_modules:
        command.extend(
            ["--allow-untracked-prefix", "webapp/frontend/node_modules"]
        )
    if allow_build_outputs:
        command.extend(
            [
                "--allow-untracked-prefix",
                "build",
                "--allow-untracked-prefix",
                "cisco_migration_assessment_toolkit.egg-info",
            ]
        )
    if staged_output is not None:
        try:
            staged_relative = staged_output.resolve(strict=True).relative_to(
                repository.resolve(strict=True)
            )
        except ValueError:
            staged_relative = None
        if staged_relative is not None:
            command.extend(
                ["--allow-untracked-prefix", staged_relative.as_posix()]
            )
    try:
        completed = subprocess.run(
            command,
            cwd=repository,
            check=False,
            env=_bind_trusted_git(_clean_environment()),
        )
    except OSError:
        raise ReproducibleBuildError("SOURCE_WORKTREE_MISMATCH") from None
    if completed.returncode != 0:
        raise ReproducibleBuildError("SOURCE_WORKTREE_MISMATCH")


def _run_git(cwd: Path, *arguments: str) -> None:
    try:
        completed = subprocess.run(
            [_trusted_git_executable(), "--no-replace-objects", *arguments],
            cwd=cwd,
            check=False,
            capture_output=True,
            env=_bind_trusted_git(_clean_environment()),
            text=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ReproducibleBuildError("SOURCE_MATERIALIZATION_FAILED") from None
    if completed.returncode != 0:
        raise ReproducibleBuildError("SOURCE_MATERIALIZATION_FAILED")


def _materialize_source(
    repository: Path,
    destination: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> None:
    _run_git(
        destination.parent,
        "clone",
        "--no-local",
        "--no-checkout",
        "--quiet",
        str(repository),
        str(destination),
    )
    for key, value in (
        ("core.autocrlf", "false"),
        ("core.eol", "lf"),
        ("core.safecrlf", "true"),
    ):
        _run_git(destination, "config", key, value)
    _run_git(destination, "checkout", "--detach", "--quiet", expected_commit)
    if (
        _git_text(destination, "rev-parse", "--verify", "HEAD^{commit}") != expected_commit
        or _git_text(
            destination,
            "rev-parse",
            "--verify",
            f"{expected_commit}^{{tree}}",
        )
        != expected_tree
    ):
        raise ReproducibleBuildError("SOURCE_MATERIALIZATION_IDENTITY_MISMATCH")
    _verify_source(
        destination,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
    )


def _compare_file_bytes(primary: Path, replay: Path) -> tuple[int, str]:
    primary_hash = hashlib.sha256()
    replay_hash = hashlib.sha256()
    equal = True
    try:
        with primary.open("rb") as primary_file, replay.open("rb") as replay_file:
            primary_before = os.fstat(primary_file.fileno())
            replay_before = os.fstat(replay_file.fileno())
            for value in (primary_before, replay_before):
                if (
                    not stat.S_ISREG(value.st_mode)
                    or value.st_nlink != 1
                    or value.st_size < 0
                    or value.st_size > _MAX_ARCHIVE_BYTES
                ):
                    raise ReproducibleBuildError("ARCHIVE_FILE_INVALID")
            if primary_before.st_size != replay_before.st_size:
                equal = False
            while True:
                primary_chunk = primary_file.read(1024 * 1024)
                replay_chunk = replay_file.read(1024 * 1024)
                if not primary_chunk and not replay_chunk:
                    break
                primary_hash.update(primary_chunk)
                replay_hash.update(replay_chunk)
                if primary_chunk != replay_chunk:
                    equal = False
            primary_after = os.fstat(primary_file.fileno())
            replay_after = os.fstat(replay_file.fileno())
        primary_path = os.stat(primary, follow_symlinks=False)
        replay_path = os.stat(replay, follow_symlinks=False)
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_FILE_INVALID") from None
    if (
        _handle_identity(primary_after) != _handle_identity(primary_before)
        or _handle_identity(replay_after) != _handle_identity(replay_before)
        or _path_identity(primary_path) != _path_identity(primary_before)
        or _path_identity(replay_path) != _path_identity(replay_before)
        or not stat.S_ISREG(primary_path.st_mode)
        or not stat.S_ISREG(replay_path.st_mode)
    ):
        raise ReproducibleBuildError("ARCHIVE_FILE_CHANGED_DURING_COMPARISON")
    primary_digest = primary_hash.hexdigest()
    replay_digest = replay_hash.hexdigest()
    if not equal or primary_digest != replay_digest:
        raise ReproducibleBuildError(
            f"ARCHIVE_BYTES_MISMATCH:{primary.name}:{primary_digest}:{replay_digest}"
        )
    return primary_before.st_size, primary_digest


def _compare_archives(
    primary: dict[str, Path],
    replay: dict[str, Path],
) -> list[dict[str, object]]:
    if primary.keys() != replay.keys():
        raise ReproducibleBuildError("ARCHIVE_NAME_SET_MISMATCH")
    result = []
    for name in sorted(primary):
        size, digest = _compare_file_bytes(primary[name], replay[name])
        result.append({"bytes": size, "name": name, "sha256": digest})
    return result


def _measure_archives(archives: dict[str, Path]) -> list[dict[str, object]]:
    result = []
    for name in sorted(archives):
        digest = hashlib.sha256()
        with _stable_reader(archives[name]) as (source, identity):
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        result.append(
            {
                "bytes": identity.st_size,
                "name": name,
                "sha256": digest.hexdigest(),
            }
        )
    return result


def _measure_archive_directory(directory: Path) -> list[dict[str, object]]:
    archives, before = _archive_set_observation(directory)
    result = _measure_archives(archives)
    _archives_after, after = _archive_set_observation(directory)
    if before != after:
        raise ReproducibleBuildError("ARCHIVE_SET_CHANGED_DURING_MEASUREMENT")
    return result


def _extract_sdist(path: Path, destination: Path) -> Path:
    if destination.exists():
        raise ReproducibleBuildError("SDIST_EXTRACTION_TARGET_EXISTS")
    destination.mkdir()
    seen: set[str] = set()
    root_name = ""
    total = 0
    try:
        with _stable_sdist(path) as archive:
            if archive.pax_headers:
                raise ReproducibleBuildError("SDIST_MEMBER_INVALID")
            count = 0
            for count, member in enumerate(archive, 1):
                if count > _MAX_SDIST_MEMBERS:
                    raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")
                _safe_sdist_member(member, seen)
                total += member.size
                if total > _MAX_SDIST_BYTES:
                    raise ReproducibleBuildError("SDIST_CONTENT_LIMIT_EXCEEDED")
                parts = member.name.split("/")
                if not root_name:
                    root_name = parts[0]
                if parts[0] != root_name:
                    raise ReproducibleBuildError("SDIST_ROOT_INVALID")
                target = destination.joinpath(*parts)
                if member.isdir():
                    if target.exists() and not target.is_dir():
                        raise ReproducibleBuildError("SDIST_PATH_COLLISION")
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ReproducibleBuildError("SDIST_PATH_COLLISION")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ReproducibleBuildError("SDIST_MEMBER_UNREADABLE")
                with extracted, target.open("xb") as output:
                    _stream_payload(extracted, member.size, destination=output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            if count == 0 or not root_name:
                raise ReproducibleBuildError("SDIST_MEMBER_COUNT_INVALID")
    except ReproducibleBuildError:
        raise
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise ReproducibleBuildError("SDIST_EXTRACTION_FAILED") from None
    root = destination / root_name
    if not (root / "pyproject.toml").is_file() or not (root / "PKG-INFO").is_file():
        raise ReproducibleBuildError("SDIST_BUILD_ROOT_INVALID")
    return root


def _build_candidate(
    source: Path,
    workspace: Path,
    *,
    epoch: int,
    expected_commit: str,
    expected_tree: str,
) -> dict[str, Path]:
    workspace.mkdir()
    raw_sdist = workspace / "raw-sdist"
    _run_build(
        source,
        raw_sdist,
        epoch,
        kind="sdist",
        lane_root=workspace / "environment-sdist",
    )
    sdist = _single_archive(raw_sdist, ".tar.gz")
    _canonicalize_sdist(sdist, epoch)
    extracted_root = _extract_sdist(sdist, workspace / "extracted")
    raw_wheel = workspace / "raw-wheel"
    _run_build(
        extracted_root,
        raw_wheel,
        epoch,
        kind="wheel",
        lane_root=workspace / "environment-wheel",
    )
    wheel = _single_archive(raw_wheel, ".whl")

    final = workspace / "final"
    final.mkdir()
    shutil.copyfile(sdist, final / sdist.name)
    shutil.copyfile(wheel, final / wheel.name)
    _verify_source(
        source,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        allow_build_outputs=True,
    )
    return _archives(final)


def _stage_archives(primary: dict[str, Path], output: Path) -> Path:
    if output.exists():
        raise ReproducibleBuildError("OUTPUT_DIRECTORY_EXISTS")
    output.parent.resolve(strict=True)
    staged = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.publishing-", dir=output.parent)
    )
    try:
        for name, source in primary.items():
            shutil.copyfile(source, staged / name)
        copied = _archives(staged)
        _compare_archives(primary, copied)
        if output.exists():
            raise ReproducibleBuildError("OUTPUT_DIRECTORY_EXISTS")
        return staged
    except ReproducibleBuildError:
        raise
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_PUBLISH_FAILED") from None
    finally:
        if sys.exc_info()[0] is not None:
            shutil.rmtree(staged, ignore_errors=True)


def _quarantine_published_output(output: Path) -> None:
    quarantine = output.parent / f".{output.name}.rejected-{uuid.uuid4().hex}"
    try:
        os.rename(output, quarantine)
    except OSError:
        raise ReproducibleBuildError("PUBLISHED_ARCHIVE_QUARANTINE_FAILED") from None


def _publish_staged_archives(
    staged: Path,
    output: Path,
    expected: list[dict[str, object]],
) -> None:
    if output.exists() or output.is_symlink():
        raise ReproducibleBuildError("OUTPUT_DIRECTORY_EXISTS")
    try:
        os.rename(staged, output)
    except OSError:
        raise ReproducibleBuildError("ARCHIVE_PUBLISH_FAILED") from None
    try:
        observed = _measure_archive_directory(output)
    except ReproducibleBuildError:
        _quarantine_published_output(output)
        raise
    if observed != expected:
        _quarantine_published_output(output)
        raise ReproducibleBuildError("PUBLISHED_ARCHIVE_BYTES_MISMATCH")


def build_reproducible_distributions(
    repository: Path,
    output: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> dict[str, object]:
    repository = repository.resolve(strict=True)
    output = output if output.is_absolute() else repository / output
    output = output.resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise ReproducibleBuildError("OUTPUT_DIRECTORY_EXISTS")
    output.parent.resolve(strict=True)

    epoch = source_date_epoch(
        repository,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
    )
    _verify_source(
        repository,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        allow_node_modules=True,
    )
    staged_output: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-dist-repro-") as temporary:
            temporary_root = Path(temporary)
            primary_source = temporary_root / "source-primary"
            replay_source = temporary_root / "source-replay"
            _materialize_source(
                repository,
                primary_source,
                expected_commit=expected_commit,
                expected_tree=expected_tree,
            )
            _materialize_source(
                repository,
                replay_source,
                expected_commit=expected_commit,
                expected_tree=expected_tree,
            )
            primary = _build_candidate(
                primary_source,
                temporary_root / "candidate-primary",
                epoch=epoch,
                expected_commit=expected_commit,
                expected_tree=expected_tree,
            )
            replay = _build_candidate(
                replay_source,
                temporary_root / "candidate-replay",
                epoch=epoch,
                expected_commit=expected_commit,
                expected_tree=expected_tree,
            )
            artifacts = _compare_archives(primary, replay)
            staged_output = _stage_archives(primary, output)
        if source_date_epoch(
            repository,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
        ) != epoch:
            raise ReproducibleBuildError("SOURCE_DATE_EPOCH_DRIFT")
        _verify_source(
            repository,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
            allow_node_modules=True,
            staged_output=staged_output,
        )
        if _measure_archive_directory(staged_output) != artifacts:
            raise ReproducibleBuildError("STAGED_ARCHIVE_BYTES_MISMATCH")
        _publish_staged_archives(staged_output, output, artifacts)
        staged_output = None
    finally:
        if staged_output is not None:
            shutil.rmtree(staged_output, ignore_errors=True)
    return {
        "artifacts": artifacts,
        "reproducible": True,
        "source_commit": expected_commit,
        "source_date_epoch": epoch,
        "source_tree": expected_tree,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_reproducible_distributions(
            args.root,
            args.outdir,
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
        )
    except ReproducibleBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
