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
import base64
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


RELEVANT_PATH_FILTERS = (
    "webapp/**",
    "atlas-scope/**",
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
    "tests/pytest_invocation_reader.py",
    ".github/workflows/webapp-ci.yml",
    ".github/scripts/classify_webapp_ci_scope.py",
    ".github/scripts/frontend_build_handoff.py",
    ".github/frontend-dependency-plan.json",
    ".github/scripts/frontend_dependency_prepare.mjs",
    ".github/scripts/frontend_dependency_prepare.test.mjs",
    ".github/scripts/frontend_artifact_receive.py",
    ".github/scripts/frontend_candidate_admit.mjs",
    ".github/scripts/test_frontend_artifact_receive.py",
    ".github/scripts/observe_vite_distribution.py",
    ".github/scripts/test_observe_vite_distribution.py",
    ".github/scripts/frontend_candidate_materials.py",
    ".github/scripts/test_frontend_candidate_materials.py",
    ".github/scripts/observe_jsonschema_rs_wheel.py",
    "tests/test_jsonschema_rs_observation.py",
    "master-reference/release/pipeline.py",
    "portable/release_contract.py",
    "portable/atlas_bundle.py",
    "portable/windows-x64-requirements.lock",
    "portable/third-party-license-fallbacks.json",
    "portable/third-party-licenses/jsonschema-rs-LICENSE",
    "tests/test_webapp_ci_scope.py",
    "tests/test_frontend_artifact_workflow_contract.py",
    ".github/scripts/verify_repository_privacy.py",
)

_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.IGNORECASE)
MANUAL_FLAGS = (
    "prepare_frontend_dependencies", "receive_frontend_artifact",
    "observe_vite_distribution", "refresh_visual_baselines", "observe_jsonschema_rs",
)
MANUAL_INPUTS = (*MANUAL_FLAGS, "frontend_artifact_selection", "vite_distribution_integrity", "jsonschema_rs_source_commit")


def validate_manual_operations(event_name: str, values: dict[str, str]) -> str:
    """Pure dispatch-input admission; full artifact selectors stay receiver-owned."""
    if event_name != "workflow_dispatch":
        raise ValueError("manual preflight requires workflow_dispatch")
    if type(values) is not dict or set(values) != set(MANUAL_INPUTS):
        raise ValueError("manual input census differs")
    if not all(type(value) is str for value in values.values()):
        raise ValueError("manual inputs must be environment strings")
    if any(values[name] not in ("true", "false") for name in MANUAL_FLAGS):
        raise ValueError("manual operation flags must be exactly true or false")
    selected = [name for name in MANUAL_FLAGS if values[name] == "true"]
    if len(selected) > 1:
        raise ValueError("manual preparation, receipt, observation and refresh are mutually exclusive")
    operation = selected[0] if selected else "none"
    selection = values["frontend_artifact_selection"]
    integrity = values["vite_distribution_integrity"]
    native_source = values["jsonschema_rs_source_commit"]
    if operation == "receive_frontend_artifact":
        if not selection or len(selection.encode("utf-8")) > 4096:
            raise ValueError("receipt requires a bounded nonempty selection")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate selection JSON key")
                result[key] = value
            return result
        def constant(_):
            raise ValueError("nonfinite selection JSON")
        def finite_float(raw):
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("nonfinite selection JSON")
            return value
        try:
            parsed = json.loads(selection, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValueError("selection must be bounded JSON data") from error
        if type(parsed) is not dict or not parsed:
            raise ValueError("selection must be a nonempty JSON object")
    elif selection:
        raise ValueError("selection supplied without receipt operation")
    if operation == "observe_vite_distribution":
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", integrity):
            raise ValueError("observation requires canonical SHA-512 integrity")
        raw = base64.b64decode(integrity[7:], validate=True)
        if len(raw) != 64 or base64.b64encode(raw).decode() != integrity[7:]:
            raise ValueError("noncanonical SHA-512 integrity")
    elif integrity:
        raise ValueError("integrity supplied without observation operation")
    if operation == "observe_jsonschema_rs":
        if not re.fullmatch(r"[0-9a-f]{40}", native_source):
            raise ValueError("native observation requires an exact lowercase source commit")
    elif native_source:
        raise ValueError("native source supplied without native observation operation")
    return operation


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
    parser.add_argument("--validate-manual-operations", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.validate_manual_operations:
            values = {name: os.environ.get("WEBAPP_MANUAL_" + name.upper(), "") for name in MANUAL_INPUTS}
            validate_manual_operations(args.event_name, values)
            return 0
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
