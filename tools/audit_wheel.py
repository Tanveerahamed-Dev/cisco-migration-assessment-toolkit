#!/usr/bin/env python3
"""Fail a build when a distribution contains client evidence or unexpected wheel files.

The project intentionally keeps raw network captures outside the Python package, but a packaging
configuration change can silently widen what setuptools includes. This guard inspects the artifacts
that would actually be installed or published; source-tree ignore rules alone are not sufficient.

Despite the historical filename, the command audits both wheels and ``.tar.gz`` source distributions.
A directory argument is expanded in Python rather than by the calling shell, so the same command works
under PowerShell and POSIX shells. A directory must contain exactly one wheel and one source archive.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


_REQUIRED_RUNTIME_MEMBERS = frozenset(
    {
        "COLLECT_PARSE_V3_23_0.py",
        "cisco_toolkit/blast_radius_explorer.html",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
    }
)
_REQUIRED_SDIST_MEMBERS = _REQUIRED_RUNTIME_MEMBERS | {"pyproject.toml"}

# Exact path segments commonly used for raw/client material. Keep this intentionally narrower than
# words that can legitimately occur in source module names (for example capture_integrity.py).
_FORBIDDEN_SEGMENTS = frozenset(
    {
        "collection",
        "collections",
        "client_data",
        "client-data",
        "client_evidence",
        "client-evidence",
        "evidence",
        "captures",
        "raw_collection",
        "raw-collection",
        "raw_evidence",
        "raw-evidence",
    }
)

_COLLECTION_SIDECAR_BASENAMES = frozenset(
    {
        "device_info.json",
        "command_index.json",
        "_capture_meta.json",
    }
)

_FORBIDDEN_BASENAMES = frozenset(
    {
        "devices.json",
        "assesshub.db",
        "engagement-state.json",
        "query_log.jsonl",
    }
) | _COLLECTION_SIDECAR_BASENAMES

# Every current command registry family, not only running-config and credential-bearing captures.
# Inventory, ARP, MAC, neighbor, platform, and log output are client evidence as well. The ignore
# regression statically enumerates the command lists, so a future prefix requires an intentional
# update here and in .gitignore rather than silently passing through.
_CAPTURE_FILENAME_GLOBS = (
    "show_*.txt",
    "moquery_-c_*.txt",
    "api_v1_*.txt",
    "api_fmc_*.txt",
    "ers_config_*.txt",
    "dataservice_*.txt",
    "aws_ec2_describe-security-groups.txt",
    "get_system_ha_status.txt",
)

_FORBIDDEN_FILENAME_GLOBS = _CAPTURE_FILENAME_GLOBS + (
    "*.snapshot.json",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.xlsx",
    "*.docx",
    "*.pptx",
    "*.log",
)


def _safe_parts(name: str) -> tuple[str, ...] | None:
    if "\\" in name or name.startswith("/"):
        return None
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def _member_policy_errors(name: str, *, synthetic_tests_allowed: bool = False) -> list[str]:
    parts = _safe_parts(name)
    if parts is None:
        return [f"unsafe member path: {name}"]

    lowered_parts = tuple(part.lower() for part in parts)
    base = lowered_parts[-1]
    errors: list[str] = []
    if any(
        part in _FORBIDDEN_SEGMENTS or part.startswith("migration_collection_")
        for part in lowered_parts
    ):
        errors.append(f"client-evidence directory packaged: {name}")

    matches_capture = any(fnmatch.fnmatchcase(base, pattern) for pattern in _CAPTURE_FILENAME_GLOBS)
    is_reviewable_test_artifact = (
        synthetic_tests_allowed
        and lowered_parts[0] == "tests"
        and (matches_capture or base in _COLLECTION_SIDECAR_BASENAMES)
    )
    matches_forbidden = base in _FORBIDDEN_BASENAMES or any(
        fnmatch.fnmatchcase(base, pattern) for pattern in _FORBIDDEN_FILENAME_GLOBS
    )
    if matches_forbidden and not is_reviewable_test_artifact:
        errors.append(f"sensitive/generated file packaged: {name}")
    return errors


def _wheel_members(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return sorted(name.rstrip("/") for name in archive.namelist() if not name.endswith("/"))


def _is_allowed_wheel_location(parts: tuple[str, ...], dist_info_root: str | None) -> bool:
    if len(parts) == 1 and parts[0] == "COLLECT_PARSE_V3_23_0.py":
        return True
    if parts[0] == "cisco_toolkit":
        return True
    if len(parts) >= 2 and parts[:2] == ("webapp", "backend"):
        return True
    return dist_info_root is not None and parts[0] == dist_info_root


def audit_wheel(wheel: Path) -> list[str]:
    """Return policy violations for one wheel (empty means the artifact is safe)."""
    errors: list[str] = []
    try:
        members = _wheel_members(wheel)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot read wheel {wheel}: {exc}"]

    member_set = set(members)
    dist_info_roots = {
        PurePosixPath(name).parts[0]
        for name in members
        if _safe_parts(name) and PurePosixPath(name).parts[0].endswith(".dist-info")
    }
    if len(dist_info_roots) != 1:
        errors.append(
            f"expected exactly one .dist-info directory, found {sorted(dist_info_roots)!r}"
        )
    dist_info_root = next(iter(dist_info_roots), None)

    for name in members:
        errors.extend(_member_policy_errors(name))
        parts = _safe_parts(name)
        if parts is not None and not _is_allowed_wheel_location(parts, dist_info_root):
            errors.append(f"unexpected wheel member outside the package allowlist: {name}")

    for required in sorted(_REQUIRED_RUNTIME_MEMBERS - member_set):
        errors.append(f"required runtime asset missing from wheel: {required}")
    return sorted(set(errors))


def _sdist_files(sdist: Path) -> tuple[list[str], list[str]]:
    """Return (files relative to the single archive root, structural errors)."""
    structural_errors: list[str] = []
    raw_files: list[str] = []
    roots: set[str] = set()
    with tarfile.open(sdist, "r:*") as archive:
        for member in archive.getmembers():
            parts = _safe_parts(member.name.rstrip("/"))
            if parts is None:
                structural_errors.append(f"unsafe member path: {member.name}")
                continue
            roots.add(parts[0])
            if member.isdir():
                continue
            if not member.isfile():
                structural_errors.append(
                    f"source distribution contains a link or special member: {member.name}"
                )
                continue
            raw_files.append(member.name)

    if len(roots) != 1:
        structural_errors.append(f"expected one source-distribution root, found {sorted(roots)!r}")
        return [], structural_errors

    root = next(iter(roots))
    relative: list[str] = []
    for name in raw_files:
        parts = _safe_parts(name)
        if parts is None or parts[0] != root or len(parts) < 2:
            structural_errors.append(f"source-distribution member is outside its root: {name}")
            continue
        relative.append(PurePosixPath(*parts[1:]).as_posix())
    return sorted(relative), structural_errors


def audit_sdist(sdist: Path) -> list[str]:
    """Return policy violations for one ``.tar.gz`` source distribution."""
    try:
        members, errors = _sdist_files(sdist)
    except (OSError, tarfile.TarError) as exc:
        return [f"cannot read source distribution {sdist}: {exc}"]

    for name in members:
        errors.extend(_member_policy_errors(name, synthetic_tests_allowed=True))
    for required in sorted(_REQUIRED_SDIST_MEMBERS - set(members)):
        errors.append(f"required source member missing from sdist: {required}")
    return sorted(set(errors))


def audit_artifact(artifact: Path) -> list[str]:
    if artifact.suffix == ".whl":
        return audit_wheel(artifact)
    if artifact.name.endswith(".tar.gz"):
        return audit_sdist(artifact)
    return [f"unsupported distribution artifact: {artifact}"]


def discover_artifacts(inputs: Iterable[Path]) -> tuple[list[Path], list[str]]:
    """Expand artifact files/directories without relying on shell wildcard expansion.

    A directory is treated as a clean build output and must contain exactly one wheel and one source
    archive. This rejects stale multi-version or unexpected output rather than auditing a subset and
    publishing every file in the directory.
    """
    artifacts: list[Path] = []
    errors: list[str] = []
    for item in inputs:
        if not item.is_dir():
            artifacts.append(item)
            continue

        wheels = sorted(item.glob("*.whl"))
        sdists = sorted(item.glob("*.tar.gz"))
        expected = set(wheels + sdists)
        unexpected = sorted(path.name for path in item.iterdir() if path not in expected)
        if len(wheels) != 1:
            errors.append(
                f"expected exactly one wheel in directory {item}, found {[p.name for p in wheels]!r}"
            )
        if len(sdists) != 1:
            errors.append(
                f"expected exactly one source distribution in directory {item}, "
                f"found {[p.name for p in sdists]!r}"
            )
        if unexpected:
            errors.append(f"unexpected entries in distribution directory {item}: {unexpected!r}")
        artifacts.extend(wheels)
        artifacts.extend(sdists)
    return artifacts, errors


def audit_many(inputs: Iterable[Path]) -> int:
    artifacts, discovery_errors = discover_artifacts(inputs)
    failed = bool(discovery_errors)
    for error in discovery_errors:
        print(f"[FAIL] {error}", file=sys.stderr)
    for artifact in artifacts:
        errors = audit_artifact(artifact)
        if errors:
            failed = True
            print(f"[FAIL] {artifact}", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"[OK] distribution contents audited: {artifact}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifacts",
        nargs="+",
        type=Path,
        help="wheel/sdist file(s), or a directory containing exactly one of each",
    )
    args = parser.parse_args(argv)
    return audit_many(args.artifacts)


if __name__ == "__main__":
    raise SystemExit(main())
