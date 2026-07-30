#!/usr/bin/env python3
"""Fail a build when a wheel contains client evidence or unexpected repository files.

The project intentionally keeps raw network captures outside the Python package, but a packaging
configuration change can silently widen what setuptools includes.  This guard inspects the artifact
that would actually be installed or published; source-tree ignore rules alone are not sufficient.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


_REQUIRED_MEMBERS = frozenset(
    {
        "COLLECT_PARSE_V3_23_0.py",
        "cisco_toolkit/blast_radius_explorer.html",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
    }
)

# Exact path segments commonly used for raw/client material.  Keep this intentionally narrower than
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

_FORBIDDEN_BASENAMES = frozenset(
    {
        "devices.json",
        "assesshub.db",
        "engagement-state.json",
        "query_log.jsonl",
    }
)

_FORBIDDEN_FILENAME_GLOBS = (
    "show_running-config*.txt",
    "show_run*.txt",
    "show_startup-config*.txt",
    "show_configuration*.txt",
    "show_tech-support*.txt",
    "show_crypto*.txt",
    "show_snmp*.txt",
    "show_tacacs*.txt",
    "show_radius*.txt",
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


def _normalised_members(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return sorted(name.rstrip("/") for name in archive.namelist() if not name.endswith("/"))


def _is_allowed_location(parts: tuple[str, ...], dist_info_root: str | None) -> bool:
    if not parts:
        return False
    if len(parts) == 1 and parts[0] == "COLLECT_PARSE_V3_23_0.py":
        return True
    if parts[0] == "cisco_toolkit":
        return True
    if len(parts) >= 2 and parts[:2] == ("webapp", "backend"):
        return True
    return dist_info_root is not None and parts[0] == dist_info_root


def audit_wheel(wheel: Path) -> list[str]:
    """Return human-readable policy violations for one wheel (empty means the artifact is safe)."""
    errors: list[str] = []
    try:
        members = _normalised_members(wheel)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot read wheel {wheel}: {exc}"]

    member_set = set(members)
    dist_info_roots = {
        PurePosixPath(name).parts[0]
        for name in members
        if PurePosixPath(name).parts and PurePosixPath(name).parts[0].endswith(".dist-info")
    }
    if len(dist_info_roots) != 1:
        errors.append(
            f"expected exactly one .dist-info directory, found {sorted(dist_info_roots)!r}"
        )
    dist_info_root = next(iter(dist_info_roots), None)

    for name in members:
        if "\\" in name or name.startswith("/"):
            errors.append(f"unsafe member path: {name}")
            continue
        path = PurePosixPath(name)
        parts = path.parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            errors.append(f"unsafe member path: {name}")
            continue

        lowered_parts = tuple(part.lower() for part in parts)
        base = lowered_parts[-1]
        if any(
            part in _FORBIDDEN_SEGMENTS or part.startswith("migration_collection_")
            for part in lowered_parts
        ):
            errors.append(f"client-evidence directory packaged: {name}")
        if base in _FORBIDDEN_BASENAMES or any(
            fnmatch.fnmatchcase(base, pattern) for pattern in _FORBIDDEN_FILENAME_GLOBS
        ):
            errors.append(f"sensitive/generated file packaged: {name}")
        if not _is_allowed_location(parts, dist_info_root):
            errors.append(f"unexpected wheel member outside the package allowlist: {name}")

    for required in sorted(_REQUIRED_MEMBERS - member_set):
        errors.append(f"required runtime asset missing from wheel: {required}")

    return sorted(set(errors))


def audit_many(wheels: Iterable[Path]) -> int:
    failed = False
    for wheel in wheels:
        errors = audit_wheel(wheel)
        if errors:
            failed = True
            print(f"[FAIL] {wheel}", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"[OK] wheel contents audited: {wheel}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", type=Path, help="wheel file(s) to inspect")
    args = parser.parse_args(argv)
    return audit_many(args.wheels)


if __name__ == "__main__":
    raise SystemExit(main())
