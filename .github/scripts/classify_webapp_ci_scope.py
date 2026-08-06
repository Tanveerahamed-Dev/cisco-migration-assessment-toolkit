"""Fail-closed path classifier for the always-reported webapp CI jobs.

GitHub leaves required checks pending when an entire workflow is skipped by a
``pull_request.paths`` filter.  ``webapp-ci.yml`` therefore starts for every pull
request and uses this script to decide whether its expensive jobs should run or
report a successful ``skipped`` conclusion.

The pull-request comparison deliberately mirrors GitHub's three-dot path-filter
semantics.  Rename detection is disabled so moving a relevant file out of scope
still exposes the deleted source path and keeps the gate engaged.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


RELEVANT_PATH_FILTERS = (
    "webapp/**",
    ".design-sync/**",
    "cisco_toolkit/**",
    "reference-data/official-sources/**",
    "COLLECT_PARSE_V3_23_0.py",
    "conftest.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "MANIFEST.in",
    "README.md",
    "LICENSE",
    ".gitattributes",
    "pytest.ini",
    "tests/golden/**",
    "tests/synthetic_fixtures.py",
    ".github/workflows/webapp-ci.yml",
    ".github/scripts/classify_webapp_ci_scope.py",
)

_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.IGNORECASE)


def path_is_relevant(path: str) -> bool:
    """Return whether one repository-relative Git path engages webapp CI."""

    for pattern in RELEVANT_PATH_FILTERS:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif path == pattern:
            return True
    return False


def changed_paths(root: Path, base_sha: str, head_sha: str) -> tuple[str, ...]:
    """Return the three-dot PR diff as unambiguous, repository-relative paths."""

    if not _OBJECT_ID.fullmatch(base_sha or ""):
        raise ValueError("pull-request base SHA is missing or malformed")
    if not _OBJECT_ID.fullmatch(head_sha or ""):
        raise ValueError("pull-request head SHA is missing or malformed")

    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            "--diff-filter=ACDMRTUXB",
            f"{base_sha}...{head_sha}",
            "--",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(
        raw.decode("utf-8", errors="surrogateescape")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def classify(
    event_name: str,
    *,
    root: Path,
    base_sha: str = "",
    head_sha: str = "",
) -> bool:
    """Classify a workflow event conservatively.

    Native push filtering already limits push runs, while manual dispatch must
    always run the visual capture path.  Unknown non-empty events also run: an
    added trigger must never silently become an opt-out.
    """

    if not event_name:
        raise ValueError("GITHUB_EVENT_NAME is missing")
    if event_name != "pull_request":
        return True
    return any(path_is_relevant(path) for path in changed_paths(root, base_sha, head_sha))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-name",
        default=os.environ.get("GITHUB_EVENT_NAME", ""),
    )
    parser.add_argument(
        "--base-sha",
        default=os.environ.get("WEBAPP_CI_BASE_SHA", ""),
    )
    parser.add_argument(
        "--head-sha",
        default=os.environ.get("WEBAPP_CI_HEAD_SHA", ""),
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.github_output:
            raise ValueError("GITHUB_OUTPUT is missing")
        relevant = classify(
            args.event_name,
            root=args.root,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
        with Path(args.github_output).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"relevant={'true' if relevant else 'false'}\n")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"webapp-ci scope classification failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
