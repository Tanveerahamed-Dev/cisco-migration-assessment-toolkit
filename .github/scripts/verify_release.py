"""Fail-closed release-ref validation used by release and PyPI workflows."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:                       # Python 3.10: tomllib is stdlib only since 3.11.
    import tomli as tomllib  # type: ignore[no-redef]  # tomli ships in [dev]; first 3.10 CI leg
    #                          ever to run this script found the bare import (the old fleet was
    #                          Windows py3.12 only, so requires-python ">=3.10" was never exercised)
from pathlib import Path

_TAG_RE = re.compile(r"v(?P<version>[0-9]+(?:\.[0-9]+){2}(?:[A-Za-z0-9.+-]*)?)\Z")


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        value = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("pyproject.toml has no non-empty project.version")
    return value.strip()


def validate_tag(tag: str, version: str) -> None:
    match = _TAG_RE.fullmatch(tag)
    if not match:
        raise ValueError(f"release tag must have the form vX.Y.Z, got {tag!r}")
    if match.group("version") != version:
        raise ValueError(
            f"release tag {tag!r} does not match pyproject.toml version {version!r}"
        )


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def validate_git(root: Path, tag: str, commit: str, base: str) -> str:
    tag_ref = f"refs/tags/{tag}"
    object_type = _git(root, "cat-file", "-t", tag_ref).stdout.strip()
    if object_type != "tag":
        raise ValueError(f"{tag_ref} is {object_type!r}, not an annotated tag")

    tagged_commit = _git(root, "rev-parse", f"{tag_ref}^{{commit}}").stdout.strip().lower()
    expected_commit = _git(root, "rev-parse", f"{commit}^{{commit}}").stdout.strip().lower()
    if tagged_commit != expected_commit:
        raise ValueError(
            f"{tag_ref} resolves to {tagged_commit}, not workflow commit {expected_commit}"
        )

    ancestry = _git(
        root,
        "merge-base",
        "--is-ancestor",
        tagged_commit,
        base,
        check=False,
    )
    if ancestry.returncode == 1:
        raise ValueError(f"tagged commit {tagged_commit} is not an ancestor of {base}")
    if ancestry.returncode != 0:
        detail = ancestry.stderr.strip() or ancestry.stdout.strip() or "git failed"
        raise ValueError(f"could not validate ancestry against {base}: {detail}")
    return tagged_commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        version = project_version(root)
        validate_tag(args.tag, version)
        commit = validate_git(root, args.tag, args.commit, args.base)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"tag": args.tag, "version": version, "commit": commit, "base": args.base},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
