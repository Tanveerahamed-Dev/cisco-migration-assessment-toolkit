from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from portable import release_contract
from pytest_invocation_reader import default_testpaths, pytest_invocations
from test_release_supply_chain import _RunnerWorkflowLoader


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-release.yml"


def _assert_pip_owner_reconciliation(
    *,
    contract: dict,
    release_contract_version: str,
    pyproject_text: str,
    lock_text: str,
    workflow_text: str,
) -> None:
    expected = contract["pip"]
    assert expected == release_contract_version == "26.2.1"

    project = tomllib.loads(pyproject_text)
    dependency_groups = [
        ("project", project["project"].get("dependencies", [])),
        *project["project"]["optional-dependencies"].items(),
    ]
    pip_project_rows = []
    for group, rows in dependency_groups:
        try:
            requirements = [Requirement(row) for row in rows]
        except InvalidRequirement as error:
            raise AssertionError("project contains an invalid requirement") from error
        pip_project_rows.extend(
            (group, requirement)
            for requirement in requirements
            if canonicalize_name(requirement.name) == "pip"
        )
    assert len(pip_project_rows) == 1
    pip_group, pip_build = pip_project_rows[0]
    assert pip_group == "build"
    assert str(pip_build.specifier) == f"=={expected}"
    assert not pip_build.extras and pip_build.marker is None and pip_build.url is None

    locked_pip_versions = [
        version
        for name, version in re.findall(
            r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock_text, re.MULTILINE
        )
        if release_contract._distribution_name(name) == "pip"
    ]
    assert locked_pip_versions == [expected]

    workflow_pip_installs = []
    for raw_line in workflow_text.splitlines():
        if not re.search(r"\b(?:python\s+-m\s+)?pip\s+install\b", raw_line, re.IGNORECASE):
            continue
        try:
            tokens = shlex.split(raw_line.strip())
        except ValueError as error:
            raise AssertionError("workflow contains malformed shell syntax") from error
        lowered = [token.lower() for token in tokens]
        arguments = None
        for index in range(len(tokens)):
            if lowered[index : index + 4] == ["python", "-m", "pip", "install"]:
                arguments = tokens[index + 4 :]
                break
            if lowered[index : index + 2] == ["pip", "install"]:
                arguments = tokens[index + 2 :]
                break
        if arguments is None:
            continue
        for token in arguments:
            try:
                requirement = Requirement(token)
            except InvalidRequirement:
                continue
            if canonicalize_name(requirement.name) == "pip":
                workflow_pip_installs.append((raw_line.strip(), requirement))
    # Every install of pip itself is the one pinned upgrade, and there is exactly one per job that
    # runs pytest (the full gate's shards and its full collection each install their own), placed
    # before that job's first pytest. Derived from the parsed jobs, never a hand-kept count.
    pinned_line = f"python -m pip install --upgrade 'pip=={expected}'"
    assert workflow_pip_installs, "the workflow no longer pins the pip it tests with"
    for workflow_line, workflow_pip in workflow_pip_installs:
        assert workflow_line == pinned_line, workflow_line
        assert str(workflow_pip.specifier) == f"=={expected}"
        assert not workflow_pip.extras and workflow_pip.marker is None and workflow_pip.url is None
    jobs = yaml.load(workflow_text, Loader=_RunnerWorkflowLoader)["jobs"]
    pytest_jobs = {job_id: [str(step.get("run") or "") for step in job.get("steps") or []]
                   for job_id, job in jobs.items()
                   if any(pytest_invocations(str(step.get("run") or "")) for step in job.get("steps") or [])}
    assert pytest_jobs, "no portable-release job runs pytest"
    for job_id, runs in pytest_jobs.items():
        script = "\n".join(runs)
        assert script.count(pinned_line) == 1, f"{job_id} must upgrade to the pinned pip exactly once"
        first_pytest = re.search(r"-m\s+pytest\b", script)
        assert first_pytest and script.index(pinned_line) < first_pytest.start(), (
            f"{job_id} runs pytest before its pinned pip upgrade")
    assert len(workflow_pip_installs) == len(pytest_jobs), sorted(pytest_jobs)


def test_hash_lock_and_toolchain_contract_reconcile() -> None:
    contract = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
    lock = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(encoding="utf-8")
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert contract == {
        "schema": "atlas.portable-toolchain-contract/1",
        "platform": "windows-x64",
        "python": "3.12.10",
        "pip": "26.2.1",
        "pyinstaller": "6.22.2",
        "node": "v24.19.0",
        "npm": "11.16.0",
        "npm_tarball": {
            "url": "https://registry.npmjs.org/npm/-/npm-11.16.0.tgz",
            "sha512_base64": "A74XL8OxmcegZDMWPkWb5bEQppg8HdYwW3rBD2sPoS4UQHVajfaxBkqyzLeJ3wR0kZ+5xoTjItxXaF7eIXUsyw==",
            "sha512_hex": "03be172fc3b199c7a06433163e459be5b110a6983c1dd6305b7ac10f6b0fa12e1440755a8df6b1064ab2ccb789df0474919fb9c684e322dc57685ede21752ccb",
        },
        "dependency_install": "python -m pip install --require-hashes --only-binary=:all: -r portable/windows-x64-requirements.lock",
        "frontend_install": "npm ci --ignore-scripts",
        "authority": "version and hash pins constrain the build; they do not establish publisher identity or field qualification",
    }
    assert {
        "python": release_contract.PYTHON_VERSION,
        "pip": release_contract.PIP_VERSION,
        "pyinstaller": release_contract.PYINSTALLER_VERSION,
        "node": release_contract.NODE_VERSION,
        "npm": release_contract.NPM_VERSION,
    } == {key: contract[key] for key in ("python", "pip", "pyinstaller", "node", "npm")}
    assert contract["npm_tarball"]["sha512_hex"] == release_contract.NPM_TARBALL_SHA512_HEX
    assert contract["npm_tarball"]["sha512_base64"] == release_contract.NPM_TARBALL_SHA512_BASE64
    _assert_pip_owner_reconciliation(
        contract=contract,
        release_contract_version=release_contract.PIP_VERSION,
        pyproject_text=pyproject_text,
        lock_text=lock,
        workflow_text=workflow_text,
    )
    assert "pip" not in release_contract.EXPECTED_BUNDLED_PYTHON
    locked_versions = {
        release_contract._distribution_name(match.group(1)): match.group(2)
        for match in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock, re.MULTILINE)
    }
    assert {
        name: locked_versions[name] for name in release_contract.EXPECTED_BUNDLED_PYTHON
    } == release_contract.EXPECTED_BUNDLED_PYTHON
    frontend = release_contract._bundled_frontend_packages(ROOT)
    assert len(frontend) == release_contract.EXPECTED_BUNDLED_FRONTEND_COUNT
    assert release_contract.digest_object(frontend) == release_contract.EXPECTED_BUNDLED_FRONTEND_DIGEST
    scope = release_contract._bundled_scope_frontend_packages(ROOT)
    assert len(scope) == release_contract.EXPECTED_BUNDLED_SCOPE_FRONTEND_COUNT
    assert release_contract.digest_object(scope) == (
        release_contract.EXPECTED_BUNDLED_SCOPE_FRONTEND_DIGEST)
    assert f"pyinstaller=={contract['pyinstaller']} " in lock
    assert "setuptools==84.0.0 " in lock
    assert "cyclonedx-python-lib==11.12.0 " in lock
    assert "jsonschema==4.26.0 " in lock
    assert "jsonschema-rs==0.58.6 " in lock
    assert "referencing==0.37.0 " in lock
    native_block = re.search(r"(?m)^jsonschema-rs==0\.58\.6 \\\n((?:[ \t].*\n)+)", lock)
    assert native_block is not None
    assert re.findall(r"--hash=sha256:([a-f0-9]{64})", native_block.group()) == [
        "b4319d634748d57a21017753838a663e08f58b69227170b994ac2da07677c519"
    ]
    assert "jsonschema-specifications==2025.9.1 " in lock
    assert "--hash=sha256:" in lock
    assert "\r" not in lock


def _npm_resolve(packages: dict, dependent: str, name: str) -> str | None:
    """Node's resolution over a v3 lock: the nearest ``node_modules/<name>`` walking up from the
    dependent's install path."""
    base = dependent
    while True:
        candidate = f"{base}/node_modules/{name}" if base else f"node_modules/{name}"
        if candidate in packages:
            return candidate
        if not base:
            return None
        head, sep, _tail = base.rpartition("/node_modules/")
        base = head if sep else ""


def test_scope_inventory_covers_the_real_production_closure_of_the_atlas_scope_lock() -> None:
    """Requirement R-PB 3, against the real lock and an INDEPENDENT oracle: walk atlas-scope's
    runtime dependency graph from its root `dependencies` (dependencies, optional dependencies and
    required peers, resolved the way Node resolves them) and require every package reached to be in
    the release inventory. Every inventoried package the walk does not reach must be one the lock
    itself flags devOptional (disclosed over-inclusion of the same lock-derived rule the AssessHub
    SPA uses), never an unexplained extra."""
    lock = json.loads((ROOT / "atlas-scope" / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    root_dependencies = packages[""].get("dependencies", {})
    assert {"three", "postprocessing", "react", "react-dom", "zustand"} <= set(root_dependencies)
    reached: set[str] = set()
    pending = [("", name) for name in root_dependencies]
    while pending:
        dependent, name = pending.pop()
        resolved = _npm_resolve(packages, dependent, name)
        assert resolved is not None, (dependent, name)
        if resolved in reached:
            continue
        reached.add(resolved)
        package = packages[resolved]
        optional_peers = {peer for peer, meta in (package.get("peerDependenciesMeta") or {}).items()
                          if meta.get("optional")}
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            for child in package.get(field) or {}:
                if field == "peerDependencies" and child in optional_peers:
                    continue
                if field == "optionalDependencies" and _npm_resolve(packages, resolved, child) is None:
                    continue
                pending.append((resolved, child))
    inventory = {row["install_path"]: row for row in release_contract._bundled_scope_frontend_packages(ROOT)}
    assert reached <= set(inventory), sorted(reached - set(inventory))
    for install_path in set(inventory) - reached:
        assert packages[install_path].get("devOptional") is True, install_path
    for install_path in reached:
        assert inventory[install_path]["version"] == packages[install_path]["version"]


@pytest.mark.parametrize(
    "mutated_owner",
    [
        "toolchain",
        "release_contract",
        "pyproject",
        "pyproject_alias",
        "pyproject_dev_alias",
        "lock",
        "workflow",
        "workflow_unpinned",
        "workflow_first_job_without_pip",
        "workflow_last_job_without_pip",
    ],
)
def test_each_portable_pip_owner_is_required_for_reconciliation(mutated_owner: str) -> None:
    contract = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
    release_contract_version = release_contract.PIP_VERSION
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock_text = (ROOT / "portable" / "windows-x64-requirements.lock").read_text(
        encoding="utf-8"
    )
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    original = (
        json.dumps(contract, sort_keys=True),
        release_contract_version,
        pyproject_text,
        lock_text,
        workflow_text,
    )

    if mutated_owner == "toolchain":
        contract["pip"] = "26.2.0"
    elif mutated_owner == "release_contract":
        release_contract_version = "26.2.0"
    elif mutated_owner == "pyproject":
        pyproject_text = pyproject_text.replace("pip==26.2.1", "pip==26.2.0")
    elif mutated_owner == "pyproject_alias":
        pyproject_text = pyproject_text.replace(
            'build = ["pip==26.2.1",',
            'build = ["pip==26.2.1", "Pip>=99",',
        )
    elif mutated_owner == "pyproject_dev_alias":
        pyproject_text = pyproject_text.replace(
            "dev = [\n",
            'dev = [\n    "Pip>=99",\n',
            1,
        )
    elif mutated_owner == "lock":
        lock_text = lock_text.replace("pip==26.2.1", "pip==26.2.0")
    elif mutated_owner == "workflow":
        workflow_text = workflow_text.replace("pip==26.2.1", "pip==26.2.0")
    elif mutated_owner in ("workflow_first_job_without_pip", "workflow_last_job_without_pip"):
        # One pytest job loses its pinned upgrade while every other job keeps its own.
        lines = workflow_text.splitlines(keepends=True)
        pinned = [index for index, line in enumerate(lines)
                  if line.strip() == "python -m pip install --upgrade 'pip==26.2.1'"]
        assert len(pinned) >= 2, pinned
        del lines[pinned[0 if mutated_owner == "workflow_first_job_without_pip" else -1]]
        workflow_text = "".join(lines)
    else:
        workflow_text = workflow_text.replace(
            "python -m pip install --upgrade 'pip==26.2.1'",
            "python -m pip install --upgrade 'pip==26.2.1'\n"
            "          python -m pip install --upgrade pip",
        )

    assert (
        json.dumps(contract, sort_keys=True),
        release_contract_version,
        pyproject_text,
        lock_text,
        workflow_text,
    ) != original

    with pytest.raises(AssertionError):
        _assert_pip_owner_reconciliation(
            contract=contract,
            release_contract_version=release_contract_version,
            pyproject_text=pyproject_text,
            lock_text=lock_text,
            workflow_text=workflow_text,
        )


#: The normalization a testing or building job runs on its checkout: each command, in this order, each
#: followed by its exit check, then a refusal of any dirty tree.
_NORMALIZE_COMMANDS = (
    "git config core.autocrlf false",
    "git config core.eol lf",
    "git rm --cached -r --quiet .",
    "git reset --hard --quiet",
)
_EXIT_CHECK = "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
_DIRTY_TREE_REFUSAL = re.compile(r"if \(git status --porcelain\) \{ throw '[^']+' \}")


def _is_checkout_normalization(step: dict) -> bool:
    lines = [line.strip() for line in str(step.get("run") or "").splitlines() if line.strip()]
    expected = [line for command in _NORMALIZE_COMMANDS for line in (command, _EXIT_CHECK)]
    return (step.get("shell") == "pwsh" and "uses" not in step and lines[:-1] == expected
            and len(lines) == len(expected) + 1 and _DIRTY_TREE_REFUSAL.fullmatch(lines[-1]) is not None)


def _tests_or_builds(step: dict) -> bool:
    run = str(step.get("run") or "")
    return bool(pytest_invocations(run)) or "portable.build_release" in run


def _checkout_normalization_problems(document: dict) -> tuple[list[str], list[str]]:
    """``(jobs that test or build, problems)``. The class is derived, never listed: every job with a step
    that runs pytest (any spelling the shared reader knows) or portable.build_release must normalize
    its workspace-root checkout to committed bytes after its LAST such checkout and before its first
    testing/building step, so no test reads, and no build packages, checkout-translated bytes."""
    matched: list[str] = []
    problems: list[str] = []
    for job_id, job in document["jobs"].items():
        steps = job.get("steps") or []
        first = next((index for index, step in enumerate(steps) if _tests_or_builds(step)), None)
        if first is None:
            continue
        matched.append(job_id)
        checkouts = [index for index, step in enumerate(steps[:first])
                     if str(step.get("uses") or "").startswith("actions/checkout@")
                     and not (step.get("with") or {}).get("path")]
        if not checkouts:
            problems.append(f"{job_id}: no workspace-root checkout before its first test/build step")
        elif not any(_is_checkout_normalization(step) for step in steps[checkouts[-1] + 1:first]):
            problems.append(f"{job_id}: its checkout is not normalized to committed bytes before step {first}")
    return matched, problems


def _portable_document() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)


@pytest.mark.parametrize("mutation", [
    "dropped_shard_normalization", "late_gate_normalization", "unchecked_portable_command",
    "no_dirty_tree_refusal", "checkout_after_normalization", "bash_normalization",
])
def test_checkout_normalization_contract_rejects_each_weakening(mutation: str) -> None:
    document = _portable_document()
    jobs = document["jobs"]
    assert not _checkout_normalization_problems(document)[1]  # the real workflow passes first
    shard_steps, gate_steps = jobs["gate_shard"]["steps"], jobs["gate"]["steps"]
    shard_normalize = next(step for step in shard_steps if _is_checkout_normalization(step))
    if mutation == "dropped_shard_normalization":
        shard_steps.remove(shard_normalize)
    elif mutation == "late_gate_normalization":
        normalize = next(step for step in gate_steps if _is_checkout_normalization(step))
        gate_steps.remove(normalize)
        gate_steps.insert(next(i for i, step in enumerate(gate_steps) if _tests_or_builds(step)) + 1, normalize)
    elif mutation == "unchecked_portable_command":
        step = next(step for step in jobs["portable"]["steps"] if _is_checkout_normalization(step))
        step["run"] = step["run"].replace(_EXIT_CHECK + "\n", "", 1)
    elif mutation == "no_dirty_tree_refusal":
        shard_normalize["run"] = "\n".join(shard_normalize["run"].splitlines()[:-1]) + "\n"
    elif mutation == "checkout_after_normalization":
        checkout = next(step for step in shard_steps if str(step.get("uses") or "").startswith("actions/checkout@"))
        shard_steps.insert(shard_steps.index(shard_normalize) + 1, dict(checkout))
    else:
        shard_normalize["shell"] = "bash"
    assert _checkout_normalization_problems(document)[1]


def test_portable_workflow_separates_untrusted_build_from_draft_write_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text and "workflow_dispatch:" in text
    portable = text.split("  portable:", 1)[1].split("  draft:", 1)[0]
    draft = text.split("  draft:", 1)[1]
    assert "contents: read" in portable
    assert "contents: write" not in portable
    assert "id-token: write" not in portable
    assert "contents: write" in draft and "attestations: write" in draft
    assert "github.event_name == 'workflow_dispatch'" in draft
    assert "portable.build_release" in portable
    assert "--require-hashes --only-binary=:all:" in portable
    assert "npm install --global" not in portable
    assert "npm tarball SHA-512 mismatch" in portable
    # Every job that tests or builds from the checkout normalizes it to committed bytes first: a
    # structural reading of the parsed jobs, not a count of jobs that happened to exist.
    document = yaml.load(text, Loader=_RunnerWorkflowLoader)
    normalized, problems = _checkout_normalization_problems(document)
    assert not problems, problems
    assert {"gate_shard", "gate", "portable"} <= set(normalized), sorted(normalized)
    assert "python -m pytest -q -p no:cacheprovider" in text
    gate = text.split("  gate:", 1)[1].split("  portable:", 1)[0]
    assert "contents: write" not in gate and "id-token: write" not in gate
    # The shards precede `gate`, so the slice above does not hold them: read their permissions whole.
    for job_id in ("gate_shard", "gate"):
        assert document["jobs"][job_id]["permissions"] == {"contents": "read"}, job_id
    assert "--release-dir" in portable
    assert "atlas-portable-release\\portable-controller.json" not in portable
    assert "--draft --prerelease" in draft
    assert "never overwrites release assets" in draft
    assert 'gh release view "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert 'gh release create "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert 'gh release upload "$DRAFT_TAG" --repo "$GITHUB_REPOSITORY"' in draft
    assert "gh attestation verify" in draft
    assert "--signer-workflow" in draft and "--source-digest" in draft
    assert "--predicate-type 'https://cyclonedx.org/bom'" in draft
    assert "id: candidate" in draft
    assert "candidate ZIP denominator is not exactly one" in draft
    assert "candidate SBOM denominator is not exactly one" in draft
    assert "subject-path: ${{ steps.candidate.outputs.zip }}" in draft
    assert "sbom-path: ${{ steps.candidate.outputs.sbom }}" in draft
    assert not re.search(r"(?m)^\s*sbom-path:.*\*", draft)
    assert "actions/attest-sbom@" not in draft
    assert "--stdlib-only" in text
    assert "pip install" not in draft
    assert "protected-main checks not successful" in text
    assert "new draft release metadata differs from the exact source" in draft
    assert "uploaded draft release metadata differs from the exact source" in draft
    assert "targetCommitish" in draft and "publishedAt" in draft
    assert "tag_target=" not in draft
    assert 'releases/tags/${DRAFT_TAG}' not in draft
    assert "draft release asset readback differs" in draft
    verify_candidate = text.split("  verify_candidate:", 1)[1].split("  draft:", 1)[0]
    assert "ref: ${{ github.sha }}" in verify_candidate
    assert "ref: ${{ needs.portable.outputs.source_commit }}" not in verify_candidate
    assert "${{ inputs.draft_tag }}'" not in draft
    for match in re.finditer(r"uses:\s+[^\s]+@([^\s#]+)", text):
        assert re.fullmatch(r"[0-9a-f]{40}", match.group(1)), match.group(0)


_PORTABLE_CONCURRENCY = {
    "group": "atlas-portable-${{ github.event.pull_request.number || inputs.source_commit || github.sha }}",
    "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
}


def _assert_portable_concurrency(document: dict) -> None:
    assert set(document["on"]) == {"pull_request", "workflow_dispatch"}
    assert document["concurrency"] == _PORTABLE_CONCURRENCY
    for job_id, job in document["jobs"].items():
        assert "concurrency" not in job, f"{job_id} overrides the workflow concurrency"


def test_portable_workflow_cancels_only_superseded_pull_request_runs() -> None:
    """A newer push to a pull request cancels that pull request's in-flight run, so required checks never queue
    behind a stale head; a dispatched candidate build, which may be attesting or attaching draft assets, is never
    cancelled by a later trigger. The two triggers never share a group (pull request number vs exact commit)."""
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)
    _assert_portable_concurrency(document)


@pytest.mark.parametrize("mutation", [
    "never_cancel", "always_cancel", "cancel_dispatch", "shared_group", "job_override", "push_trigger",
])
def test_portable_concurrency_contract_rejects_drift(mutation: str) -> None:
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)
    if mutation == "never_cancel":
        document["concurrency"]["cancel-in-progress"] = False
    elif mutation == "always_cancel":
        document["concurrency"]["cancel-in-progress"] = True
    elif mutation == "cancel_dispatch":
        document["concurrency"]["cancel-in-progress"] = "${{ github.event_name == 'workflow_dispatch' }}"
    elif mutation == "shared_group":
        document["concurrency"]["group"] = "atlas-portable"
    elif mutation == "job_override":
        document["jobs"]["draft"]["concurrency"] = {"group": "draft", "cancel-in-progress": True}
    else:
        document["on"]["push"] = {"branches": ["main"]}
    with pytest.raises(AssertionError):
        _assert_portable_concurrency(document)


# -- the sharded full gate -------------------------------------------------------------------------
# `gate_shard` runs the complete Python suite as parallel jobs partitioned by test file (the root
# conftest.py --atlas-shard option, tests/atlas_shard_partition.py); the required `gate` context
# aggregates them. GitHub counts a SKIPPED required job as passing, a plain `needs` skips the
# dependent job when a dependency fails, and `!cancelled()` skips it when the run is cancelled, so the
# contract below is what keeps a failed, cancelled, skipped or dropped shard from ever turning the
# required check green.
#
# The shards' evidence (.github/scripts/verify_shard_union.py) proves only what the pinned steps
# ran. One-line edits would otherwise keep every guard green while no test runs or a failure is
# swallowed: PYTEST_ADDOPTS=--collect-only in a shard's env, a workflow-wide PYTEST_ADDOPTS that drops
# the same files from the shards and the full collection alike, an exit check replaced by `exit 0`, a
# shell that discards the script's status, an extra step writing $GITHUB_ENV. So both jobs are pinned
# exactly: no workflow-level env or defaults, no job-level defaults, exact job env, every step by
# identity, order and key set, the shard run, the full collection and the shard-result check by name,
# shell, env and every script line, and no PYTEST*/PYTHON* control anywhere in their environment
# (_interpreter_controls).
_SHARD_SPEC = re.compile(r"\$\{\{ matrix\.shard \}\}/([1-9][0-9]*)")
#: The aggregate's first step, exactly: its message is an expandable string, so a pattern admitting
#: any message would admit a `$(...)` subexpression -- `$(exit 0)` ends the step green.
_SHARD_RESULT_CHECK = ("if ($env:SHARD_RESULT -cne 'success') { throw \"gate_shard concluded '$env:SHARD_RESULT'; "
                       "this required check passes only when every shard succeeded\" }")
#: How every job that runs pytest installs, line for line (each native command followed by the exit
#: check): the pinned pip, then requirements-dev.txt. Each job resolves those ranges itself when it
#: starts, as ci.yml's legs do, so the jobs' versions can skew: an accepted residual
#: (.github/scripts/verify_shard_union.py), not something the evidence claims to exclude.
_DEV_INSTALL = "python -m pip install -r requirements-dev.txt"
_UNION_VERIFIER = ".github/scripts/verify_shard_union.py"
_SHARD_OPTION = re.compile(r"--atlas-shard(?=[\s=]|$)")


def _load_union_verifier():
    """The verifier owns the evidence layout (its file names); the workflow is held to it."""
    spec = importlib.util.spec_from_file_location("_portable_gate_union_verifier", ROOT / _UNION_VERIFIER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_UNION = _load_union_verifier()
_TOOLCHAIN = json.loads((ROOT / "portable" / "toolchain.json").read_text(encoding="utf-8"))
_JOB_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
_CHECKOUT_WITH = {"ref": "${{ github.event_name == 'workflow_dispatch' && inputs.source_commit || github.sha }}",
                  "fetch-depth": 0}
_SHARD_EVIDENCE = "${{ runner.temp }}/atlas-gate-shard-${{ matrix.shard }}"
_EVIDENCE_ARTIFACT = "atlas-gate-shard-evidence-"
_EVIDENCE_ROOT = "${{ runner.temp }}/atlas-gate-shard-evidence"
_RUN_STEP = "Run this shard of the complete Python suite without artifact authority"
_COLLECT_STEP = "Collect the complete suite once and prove the shards ran exactly it without failure"
_NORMALIZE_STEP = "Normalize the test checkout to committed bytes"
_FRONTEND_STEP = "Run the frontend tests and prove the tracked build reproduces"
#: Each job's exact steps, in order: (action or None, name or None, exact key set). An action step is
#: identified by its action, a run step by its name.
_SHARD_STEPS = (
    ("actions/checkout", None, {"uses", "with"}),
    (None, _NORMALIZE_STEP, {"name", "shell", "run"}),
    ("actions/setup-python", None, {"uses", "with"}),
    ("actions/setup-node", None, {"uses", "with"}),
    (None, _RUN_STEP, {"name", "shell", "env", "run"}),
    ("actions/upload-artifact", "Upload what this shard selected and executed", {"name", "uses", "with"}),
)
_GATE_STEPS = (
    (None, "Require every Python shard to have succeeded", {"name", "shell", "env", "run"}),
    ("actions/checkout", None, {"uses", "with"}),
    (None, _NORMALIZE_STEP, {"name", "shell", "run"}),
    ("actions/setup-python", None, {"uses", "with"}),
    ("actions/setup-node", None, {"uses", "with"}),
    ("actions/download-artifact", "Download every shard's evidence", {"name", "uses", "with"}),
    (None, _COLLECT_STEP, {"name", "shell", "env", "run"}),
    (None, _FRONTEND_STEP, {"name", "shell", "run"}),
)
_SHARD_JOB_KEYS = {"name", "runs-on", "timeout-minutes", "strategy", "permissions", "env", "steps"}
_GATE_JOB_KEYS = {"name", "needs", "if", "runs-on", "timeout-minutes", "permissions", "env", "steps"}
#: Interpreter and pytest controls that reach every pytest run through the environment
#: (PYTEST_ADDOPTS, PYTEST_PLUGINS, PYTHONPATH, PYTHONWARNINGS, ...): a class, matched by prefix and
#: case-insensitively, as Windows reads environment names.
_INTERPRETER_CONTROL_PREFIXES = ("PYTEST", "PYTHON")


def _uses(step: dict, action: str) -> bool:
    return str(step.get("uses") or "").startswith(action + "@")


def _one(indices: list[int], what: str) -> int:
    assert len(indices) == 1, f"expected exactly one {what}, found {len(indices)}"
    return indices[0]


def _script_lines(step: dict) -> list[str]:
    return [line.strip() for line in str(step.get("run") or "").splitlines() if line.strip()]


def _script(*lines: str) -> str:
    """A `run: |` block's exact text."""
    return "".join(line + "\n" for line in lines)


def _step_identity(step: dict) -> tuple:
    action = str(step["uses"]).split("@", 1)[0] if "uses" in step else None
    return action, step.get("name"), set(step)


def _interpreter_controls(document: dict, job_ids: tuple[str, ...] = ("gate_shard", "gate")) -> list[str]:
    """Every PYTEST*/PYTHON* environment variable the workflow, one of these jobs or one of their steps
    sets -- except the pinned job-level PYTHONDONTWRITEBYTECODE -- and every env that is not a mapping."""
    scopes = [("workflow", document.get("env"), frozenset())]
    for job_id in job_ids:
        job = document["jobs"][job_id]
        scopes.append((job_id, job.get("env"), frozenset({"PYTHONDONTWRITEBYTECODE"})))
        scopes.extend((f"{job_id} step {index}", step.get("env"), frozenset())
                      for index, step in enumerate(job.get("steps") or []))
    found = []
    for where, env, allowed in scopes:
        if env is None:
            continue
        if not isinstance(env, dict):
            found.append(f"{where}: env is not a mapping: {env!r}")
            continue
        found.extend(f"{where}: {key}" for key in env
                     if str(key).upper().startswith(_INTERPRETER_CONTROL_PREFIXES) and key not in allowed)
    return found


def _assert_gate_shard_contract(document: dict) -> None:
    jobs = document["jobs"]
    shard, gate = jobs["gate_shard"], jobs["gate"]
    shard_steps, gate_steps = shard["steps"], gate["steps"]

    # Nothing outside the two jobs reaches into them: no workflow-level env or defaults (a
    # PYTEST_ADDOPTS there would drop the same files from every shard AND the full collection, so the
    # union would still match), and neither job carries defaults or any key beyond the pinned ones
    # (a container, a deployment environment), and both carry exactly the pinned job env.
    assert not {"env", "defaults"} & set(document), sorted({"env", "defaults"} & set(document))
    assert set(shard) == _SHARD_JOB_KEYS and set(gate) == _GATE_JOB_KEYS, (sorted(shard), sorted(gate))
    for job_id, job in (("gate_shard", shard), ("gate", gate)):
        assert "defaults" not in job and job.get("env") == _JOB_ENV, (job_id, job.get("env"))
    # No interpreter or pytest control anywhere in either job's environment, matched as a class.
    assert _interpreter_controls(document) == []

    # Neither job can swallow a failure or skip one of its steps: no continue-on-error on the job or
    # any step, and no step condition at all, so every step runs in order and any failure is final.
    for job_id, job in (("gate_shard", shard), ("gate", gate)):
        assert "continue-on-error" not in job, job_id
        for step in job["steps"]:
            assert "continue-on-error" not in step and "if" not in step, (
                job_id, step.get("name") or step.get("uses"))
    # Every step, by identity and order, with its exact key set (so no step gains an env, a
    # working-directory, a timeout or a condition), and every run step's shell is exactly pwsh, whose
    # script GitHub fails on a terminating error: no shell that discards the script's status.
    assert [_step_identity(step) for step in shard_steps] == list(_SHARD_STEPS)
    assert [_step_identity(step) for step in gate_steps] == list(_GATE_STEPS)
    for job_id, steps in (("gate_shard", shard_steps), ("gate", gate_steps)):
        for step in steps:
            assert "run" not in step or step.get("shell") == "pwsh", (job_id, step.get("name"), step.get("shell"))
    pinned_pip = f"python -m pip install --upgrade 'pip=={_TOOLCHAIN['pip']}'"
    install = (pinned_pip, _EXIT_CHECK, _DEV_INSTALL, _EXIT_CHECK)

    # The shard count is ONE value: derived from the spec and held by the matrix, the job name and
    # the verifier's --expected-shards, so the four cannot drift apart.
    run_index = _one([i for i, step in enumerate(shard_steps) if pytest_invocations(str(step.get("run") or ""))],
                     "pytest step in a shard")
    run_step = shard_steps[run_index]
    run_env = run_step.get("env") or {}
    spec = _SHARD_SPEC.fullmatch(str(run_env.get("ATLAS_SHARD_SPEC")))
    assert spec is not None, run_env
    total = int(spec.group(1))
    assert total >= 2, total
    assert shard.get("strategy") == {"fail-fast": False, "matrix": {"shard": list(range(total))}}
    assert shard.get("name") == (
        f"Full source gate Python shard ${{{{ matrix.shard }}}} of {total} (unprivileged runner)")
    # Every shard always runs (no condition, no prerequisite) on the full history.
    assert "if" not in shard and "needs" not in shard
    checkouts = [step for step in shard_steps if _uses(step, "actions/checkout")]
    assert len(checkouts) == 1 and str(checkouts[0]["with"].get("fetch-depth")) == "0"
    # The run step, completely: each evidence path is ONE whitespace-free token inside one directory
    # under RUNNER_TEMP, named as the verifier names them; the directory exists before pytest; the
    # single gate's exact flags plus the three shard options; and every exit check, so the shared
    # reader sees a full default-suite run and every leg guard holds each shard to account.
    assert run_step["name"] == _RUN_STEP and run_step["shell"] == "pwsh"
    assert run_env == {
        "ATLAS_SHARD_SPEC": f"${{{{ matrix.shard }}}}/{total}",
        "ATLAS_SHARD_EVIDENCE": _SHARD_EVIDENCE,
        "ATLAS_SHARD_SELECTED": f"{_SHARD_EVIDENCE}/{_UNION.SELECTED}",
        "ATLAS_SHARD_EXECUTED": f"{_SHARD_EVIDENCE}/{_UNION.EXECUTED}",
    }, run_env
    assert run_step["run"] == _script(
        *install,
        "New-Item -ItemType Directory -Path $env:ATLAS_SHARD_EVIDENCE | Out-Null",
        "python -m pytest -q -p no:cacheprovider --durations=40 --atlas-shard $env:ATLAS_SHARD_SPEC "
        "--atlas-shard-manifest $env:ATLAS_SHARD_SELECTED --atlas-shard-executed $env:ATLAS_SHARD_EXECUTED",
        _EXIT_CHECK,
    ), run_step["run"]
    assert pytest_invocations(run_step["run"]) == [default_testpaths()]
    evidence = str(run_env.get("ATLAS_SHARD_EVIDENCE"))
    assert evidence.startswith("${{ runner.temp }}/") and "${{ matrix.shard }}" in evidence, evidence
    upload_index = _one([i for i, step in enumerate(shard_steps) if _uses(step, "actions/upload-artifact")],
                        "evidence upload")
    assert upload_index > run_index
    upload = shard_steps[upload_index].get("with") or {}
    # The whole evidence directory, as one artifact per shard; a missing directory fails the upload.
    assert upload == {"name": f"{_EVIDENCE_ARTIFACT}${{{{ matrix.shard }}}}", "path": evidence,
                      "if-no-files-found": "error", "overwrite": True, "retention-days": 30}, upload

    # The aggregate keeps the exact required context, waits for the whole matrix, and is never skipped:
    # exactly `always()`, because the default success() skips it when a shard fails and `!cancelled()`
    # (alone or behind `always() &&`) skips it when the run is cancelled before it starts, and a
    # skipped required job passes. It refuses anything but a successful matrix before anything else.
    assert gate.get("name") == "Full source and frontend gate (unprivileged runner)"
    assert gate.get("needs") == ["gate_shard"]
    assert gate.get("if") == "${{ always() }}"
    assert "strategy" not in gate
    first = gate_steps[0]
    assert "uses" not in first and first.get("shell") == "pwsh", first
    assert first.get("env") == {"SHARD_RESULT": "${{ needs.gate_shard.result }}"}
    assert first.get("run") == _script(_SHARD_RESULT_CHECK), first

    # Its full collection runs on the shards' checkout, interpreter and node, and installs with the
    # shards' exact install lines (pinned in both scripts below).
    for key in ("runs-on", "timeout-minutes", "permissions", "env"):
        assert gate.get(key) == shard.get(key), key
    for action in ("actions/checkout", "actions/setup-python", "actions/setup-node"):
        assert [step["uses"] for step in gate_steps if _uses(step, action)] == [
            step["uses"] for step in shard_steps if _uses(step, action)], action
    for steps in (shard_steps, gate_steps):
        assert [step.get("with") for step in steps if _uses(step, "actions/checkout")] == [_CHECKOUT_WITH]
        assert [step.get("with") for step in steps if _uses(step, "actions/setup-python")] == [
            {"python-version": _TOOLCHAIN["python"]}]
    shard_node = [i for i, step in enumerate(shard_steps) if _uses(step, "actions/setup-node")]
    gate_node = [i for i, step in enumerate(gate_steps) if _uses(step, "actions/setup-node")]
    assert len(shard_node) == len(gate_node) == 1 and shard_node[0] < run_index
    # A shard runs no npm, so it restores no npm cache; the aggregate's frontend gate keeps its own.
    node = _TOOLCHAIN["node"].removeprefix("v")
    assert shard_steps[shard_node[0]].get("with") == {"node-version": node}
    assert gate_steps[gate_node[0]].get("with") == {
        "node-version": node, "cache": "npm", "cache-dependency-path": "webapp/frontend/package-lock.json"}
    pip = [[line for step in steps for line in _script_lines(step) if "pip install" in line]
           for steps in (shard_steps, gate_steps)]
    assert pip[0] and pip[0] == pip[1], pip

    # Download every shard's evidence -- without merge-multiple, so each artifact keeps its own
    # directory -- collect the whole suite ONCE (never itself a shard), prove the selection cover and
    # each shard's execution, and only then run the unchanged frontend gate.
    download_index = _one([i for i, step in enumerate(gate_steps) if _uses(step, "actions/download-artifact")],
                          "evidence download")
    download = gate_steps[download_index].get("with") or {}
    assert download == {"pattern": f"{_EVIDENCE_ARTIFACT}*", "path": _EVIDENCE_ROOT}, download
    assert download.get("pattern") == str(upload.get("name")).replace("${{ matrix.shard }}", "*"), download
    collect_index = _one([i for i, step in enumerate(gate_steps) if pytest_invocations(str(step.get("run") or ""))],
                         "full collection step")
    assert gate_node[0] < collect_index and download_index < collect_index
    collect = gate_steps[collect_index]
    collect_env = collect.get("env") or {}
    assert collect["name"] == _COLLECT_STEP and collect["shell"] == "pwsh"
    assert collect_env == {
        "ATLAS_FULL_SELECTED": "${{ runner.temp }}/atlas-gate-full-selected.txt",
        "ATLAS_SHARD_EVIDENCE_ROOT": _EVIDENCE_ROOT,
    }, collect_env
    assert collect["run"] == _script(
        *install,
        "python -m pytest -q -p no:cacheprovider --collect-only -q --atlas-shard-manifest $env:ATLAS_FULL_SELECTED",
        _EXIT_CHECK,
        f"python {_UNION_VERIFIER} --expected-shards {total} --full $env:ATLAS_FULL_SELECTED "
        "--shard-dir $env:ATLAS_SHARD_EVIDENCE_ROOT",
        _EXIT_CHECK,
    ), collect["run"]
    assert pytest_invocations(collect["run"]) == [default_testpaths()]
    assert _SHARD_OPTION.search(collect["run"]) is None, "the full collection must not itself be a shard"
    assert collect_env.get("ATLAS_SHARD_EVIDENCE_ROOT") == download.get("path"), (collect_env, download)
    full = collect_env["ATLAS_FULL_SELECTED"]
    assert full.startswith("${{ runner.temp }}/"), full
    assert not full.startswith(str(download.get("path")) + "/"), "the full collection's evidence is no shard's"
    assert (ROOT / _UNION_VERIFIER).is_file()
    frontend_index = _one([i for i, step in enumerate(gate_steps)
                           if "npm ci --ignore-scripts" in str(step.get("run") or "")], "frontend step")
    assert collect_index < frontend_index
    assert _script_lines(gate_steps[frontend_index]) == [
        "npm install --global npm@11.16.0", _EXIT_CHECK,
        "Set-Location webapp/frontend",
        "npm ci --ignore-scripts", _EXIT_CHECK,
        "npm test", _EXIT_CHECK,
        "npm run build", _EXIT_CHECK,
        "Set-Location ../..",
        "git diff --exit-code -- webapp/frontend/dist", _EXIT_CHECK,
    ]

    # Release authority still waits on the aggregate (and so, through it, on every shard).
    assert jobs["verify_candidate"].get("needs") == ["gate", "portable"]


def test_full_gate_is_sharded_behind_one_required_aggregate() -> None:
    _assert_gate_shard_contract(_portable_document())


def _swap(steps: list, first: int, second: int) -> None:
    steps[first], steps[second] = steps[second], steps[first]


#: A shell that runs the script and then discards its status: every failure in it would pass.
_SWALLOWING_SHELL = "pwsh -command \". '{0}'; exit 0\""
#: A step that steers every later step's pytest through the runner's environment file.
_GITHUB_ENV_STEP = {"name": "Prepare the suite", "shell": "pwsh",
                    "run": "\"PYTEST_ADDOPTS=--collect-only\" >> $env:GITHUB_ENV\n"}


@pytest.mark.parametrize("mutation", [
    "matrix_short", "spec_three", "name_three", "verifier_three", "spec_as_split_tokens", "shard_conditional",
    "shallow_shard", "upload_elsewhere", "manifest_in_workspace", "different_python", "shard_npm_cache",
    "no_result_check", "result_check_after_checkout", "lenient_result_check", "not_cancelled",
    "always_unless_cancelled", "success_if", "default_if",
    "needs_nothing", "sharded_collection", "no_verifier", "no_frontend", "collect_before_download",
    "frontend_before_collect", "shard_continues_on_error", "shard_test_step_continues_on_error",
    "gate_continues_on_error", "collect_continues_on_error", "collect_conditional", "frontend_conditional",
    "verify_candidate_skips_gate",
    # P2: what would keep the evidence green while no test runs or a failure is swallowed
    "shard_step_pytest_addopts", "shard_step_lowercase_pytest_addopts", "collect_step_pytest_addopts",
    "shard_job_pytest_addopts", "gate_job_pytest_addopts", "workflow_pytest_addopts", "workflow_defaults",
    "shard_job_defaults", "gate_job_defaults", "swallowed_shard_exit", "swallowed_collect_exit",
    "shard_shell_swallows", "collect_shell_swallows", "frontend_shell_swallows", "shard_extra_step",
    "gate_extra_step", "no_executed_option", "extra_collect_line", "extra_shard_line", "merge_multiple_download",
    "pythonpath_step_env", "pythonpath_run_env", "no_evidence_directory", "upload_one_file",
    "download_one_artifact", "run_step_working_directory", "gate_job_container",
    # the shard-result check runs no code of its own
    "result_check_message_runs_code",
])
def test_full_gate_shard_contract_rejects_each_weakening(mutation: str) -> None:
    document = _portable_document()
    _assert_gate_shard_contract(document)  # the real workflow passes first
    jobs = document["jobs"]
    shard, gate = jobs["gate_shard"], jobs["gate"]
    run_step = next(step for step in shard["steps"] if pytest_invocations(str(step.get("run") or "")))
    collect_index = next(i for i, step in enumerate(gate["steps"]) if pytest_invocations(str(step.get("run") or "")))
    collect = gate["steps"][collect_index]
    upload = next(step for step in shard["steps"] if _uses(step, "actions/upload-artifact"))
    download = next(step for step in gate["steps"] if _uses(step, "actions/download-artifact"))
    frontend = next(step for step in gate["steps"] if step.get("name") == _FRONTEND_STEP)
    if mutation == "matrix_short":
        shard["strategy"]["matrix"]["shard"] = [0]
    elif mutation == "spec_three":
        run_step["env"]["ATLAS_SHARD_SPEC"] = "${{ matrix.shard }}/3"
    elif mutation == "name_three":
        shard["name"] = shard["name"].replace(" of 2 ", " of 3 ")
    elif mutation == "verifier_three":
        collect["run"] = collect["run"].replace("--expected-shards 2", "--expected-shards 3")
    elif mutation == "spec_as_split_tokens":
        run_step["run"] = run_step["run"].replace("$env:ATLAS_SHARD_SPEC", "${{ matrix.shard }}/2")
    elif mutation == "shard_conditional":
        shard["if"] = "${{ false }}"
    elif mutation == "shallow_shard":
        next(step for step in shard["steps"] if _uses(step, "actions/checkout"))["with"]["fetch-depth"] = 1
    elif mutation == "upload_elsewhere":
        next(step for step in shard["steps"] if _uses(step, "actions/upload-artifact"))["with"]["path"] = "x.txt"
    elif mutation == "manifest_in_workspace":
        run_step["env"]["ATLAS_SHARD_SELECTED"] = "atlas-gate-shard-${{ matrix.shard }}/selected.txt"
    elif mutation == "different_python":
        next(step for step in shard["steps"] if _uses(step, "actions/setup-python"))["with"]["python-version"] = "3.12.9"
    elif mutation == "shard_npm_cache":
        next(step for step in shard["steps"] if _uses(step, "actions/setup-node"))["with"]["cache"] = "npm"
    elif mutation == "no_result_check":
        del gate["steps"][0]
    elif mutation == "result_check_after_checkout":
        _swap(gate["steps"], 0, 1)
    elif mutation == "lenient_result_check":
        gate["steps"][0]["run"] = gate["steps"][0]["run"].replace("-cne 'success'", "-eq 'failure'")
    elif mutation == "not_cancelled":
        gate["if"] = "${{ !cancelled() }}"
    elif mutation == "always_unless_cancelled":
        gate["if"] = "${{ always() && !cancelled() }}"
    elif mutation == "success_if":
        gate["if"] = "${{ success() }}"
    elif mutation == "default_if":
        del gate["if"]
    elif mutation == "needs_nothing":
        gate["needs"] = []
    elif mutation == "sharded_collection":
        collect["run"] = collect["run"].replace("--collect-only -q", "--collect-only -q --atlas-shard 0/2")
    elif mutation == "no_verifier":
        collect["run"] = "\n".join(line for line in collect["run"].splitlines() if _UNION_VERIFIER not in line)
    elif mutation == "no_frontend":
        gate["steps"] = [step for step in gate["steps"] if "npm ci --ignore-scripts" not in str(step.get("run") or "")]
    elif mutation == "collect_before_download":
        _swap(gate["steps"], collect_index, next(
            i for i, step in enumerate(gate["steps"]) if _uses(step, "actions/download-artifact")))
    elif mutation == "frontend_before_collect":
        _swap(gate["steps"], collect_index, next(
            i for i, step in enumerate(gate["steps"]) if "npm ci --ignore-scripts" in str(step.get("run") or "")))
    elif mutation == "shard_continues_on_error":
        shard["continue-on-error"] = True
    elif mutation == "shard_test_step_continues_on_error":
        run_step["continue-on-error"] = True
    elif mutation == "gate_continues_on_error":
        gate["continue-on-error"] = True
    elif mutation == "collect_continues_on_error":
        collect["continue-on-error"] = True
    elif mutation == "collect_conditional":
        collect["if"] = "${{ false }}"
    elif mutation == "frontend_conditional":
        next(step for step in gate["steps"] if "npm ci --ignore-scripts" in str(step.get("run") or ""))["if"] = (
            "${{ false }}")
    elif mutation == "verify_candidate_skips_gate":
        jobs["verify_candidate"]["needs"] = ["portable"]
    elif mutation == "shard_step_pytest_addopts":
        run_step["env"]["PYTEST_ADDOPTS"] = "--collect-only"
    elif mutation == "shard_step_lowercase_pytest_addopts":
        run_step["env"]["pytest_addopts"] = "--setup-plan"  # Windows reads environment names caselessly
    elif mutation == "collect_step_pytest_addopts":
        collect["env"]["PYTEST_ADDOPTS"] = "--ignore=webapp/tests"
    elif mutation == "shard_job_pytest_addopts":
        shard["env"]["PYTEST_ADDOPTS"] = "--collect-only"
    elif mutation == "gate_job_pytest_addopts":
        gate["env"]["PYTEST_ADDOPTS"] = "--ignore=webapp/tests"
    elif mutation == "workflow_pytest_addopts":
        document["env"] = {"PYTEST_ADDOPTS": "--ignore=webapp/tests"}
    elif mutation == "workflow_defaults":
        document["defaults"] = {"run": {"shell": _SWALLOWING_SHELL}}
    elif mutation == "shard_job_defaults":
        shard["defaults"] = {"run": {"shell": _SWALLOWING_SHELL}}
    elif mutation == "gate_job_defaults":
        gate["defaults"] = {"run": {"working-directory": "webapp"}}
    elif mutation == "swallowed_shard_exit":
        lines = run_step["run"].splitlines()
        assert lines[-1] == _EXIT_CHECK and "-m pytest" in lines[-2]
        run_step["run"] = _script(*lines[:-1], "exit 0")
    elif mutation == "swallowed_collect_exit":
        lines = collect["run"].splitlines()
        after = next(index for index, line in enumerate(lines) if "-m pytest" in line) + 1
        assert lines[after] == _EXIT_CHECK
        lines[after] = "$global:LASTEXITCODE = 0"
        collect["run"] = _script(*lines)
    elif mutation == "shard_shell_swallows":
        run_step["shell"] = _SWALLOWING_SHELL
    elif mutation == "collect_shell_swallows":
        collect["shell"] = _SWALLOWING_SHELL
    elif mutation == "frontend_shell_swallows":
        frontend["shell"] = _SWALLOWING_SHELL
    elif mutation == "shard_extra_step":
        shard["steps"].insert(shard["steps"].index(run_step), dict(_GITHUB_ENV_STEP))
    elif mutation == "gate_extra_step":
        gate["steps"].insert(collect_index, dict(_GITHUB_ENV_STEP))
    elif mutation == "no_executed_option":
        run_step["run"] = run_step["run"].replace(" --atlas-shard-executed $env:ATLAS_SHARD_EXECUTED", "")
    elif mutation == "extra_collect_line":
        collect["run"] = "$env:PYTEST_ADDOPTS = '--ignore=webapp/tests'\n" + collect["run"]
    elif mutation == "extra_shard_line":
        run_step["run"] = "$env:PYTEST_ADDOPTS = '--collect-only'\n" + run_step["run"]
    elif mutation == "merge_multiple_download":
        download["with"]["merge-multiple"] = True
    elif mutation == "pythonpath_step_env":
        next(step for step in shard["steps"] if step.get("name") == _NORMALIZE_STEP)["env"] = {"PYTHONPATH": "shim"}
    elif mutation == "pythonpath_run_env":
        run_step["env"]["PYTHONPATH"] = "shim"
    elif mutation == "no_evidence_directory":
        run_step["run"] = _script(*(line for line in run_step["run"].splitlines() if not line.startswith("New-Item")))
    elif mutation == "upload_one_file":
        upload["with"]["path"] = run_step["env"]["ATLAS_SHARD_SELECTED"]
    elif mutation == "download_one_artifact":
        download["with"] = {"name": f"{_EVIDENCE_ARTIFACT}0", "path": _EVIDENCE_ROOT}
    elif mutation == "run_step_working_directory":
        run_step["working-directory"] = "webapp"
    elif mutation == "gate_job_container":
        gate["container"] = "mcr.microsoft.com/windows/servercore:ltsc2025"
    elif mutation == "result_check_message_runs_code":
        gate["steps"][0]["run"] = gate["steps"][0]["run"].replace("succeeded\"", "succeeded$(exit 0)\"")
        assert "$(exit 0)" in gate["steps"][0]["run"]
    else:
        raise AssertionError(f"unknown mutation {mutation!r}")  # outside pytest.raises: a typo fails loudly
    with pytest.raises(AssertionError):
        _assert_gate_shard_contract(document)


@pytest.mark.parametrize("mutation", [
    "workflow_env", "job_env_pythonpath", "lowercase_step_env", "frontend_pythonwarnings",
    "step_pythondontwritebytecode", "expression_env", "pytest_plugins_in_gate_step",
])
def test_no_interpreter_or_pytest_control_reaches_either_job_through_its_environment(mutation: str) -> None:
    """The class, not a list: any PYTEST*/PYTHON* variable at workflow, job or step level (matched
    caselessly) is found, except the pinned job-level PYTHONDONTWRITEBYTECODE."""
    document = _portable_document()
    assert _interpreter_controls(document) == []  # the real workflow sets none
    shard, gate = document["jobs"]["gate_shard"], document["jobs"]["gate"]
    if mutation == "workflow_env":
        document["env"] = {"PYTEST_ADDOPTS": "--ignore=webapp/tests"}
    elif mutation == "job_env_pythonpath":
        shard["env"]["PYTHONPATH"] = "shim"
    elif mutation == "lowercase_step_env":
        gate["steps"][0]["env"]["pytest_addopts"] = "--collect-only"
    elif mutation == "frontend_pythonwarnings":
        next(step for step in gate["steps"] if step.get("name") == _FRONTEND_STEP)["env"] = {"PYTHONWARNINGS": "ignore"}
    elif mutation == "step_pythondontwritebytecode":
        next(step for step in shard["steps"] if step.get("name") == _RUN_STEP)["env"]["PYTHONDONTWRITEBYTECODE"] = "0"
    elif mutation == "expression_env":
        gate["env"] = "${{ fromJSON(needs.gate_shard.outputs.env) }}"
    else:
        next(step for step in gate["steps"] if step.get("name") == _COLLECT_STEP)["env"]["PYTEST_PLUGINS"] = "shim"
    found = _interpreter_controls(document)
    assert len(found) == 1, found
    with pytest.raises(AssertionError):
        _assert_gate_shard_contract(document)


def test_archive_release_workflows_create_drafts_only() -> None:
    for name in ("release.yml", "release-selfhosted.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        command = text.split("gh release create", 1)[1]
        assert "--draft" in command
    hosted = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "!contains(github.ref_name, '-rc.')" in hosted


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 syntax gate")
@pytest.mark.parametrize("name", ["make_stick.ps1", "sign_release.ps1", "verify_signatures.ps1"])
def test_portable_powershell_scripts_parse_on_windows_powershell(name: str) -> None:
    path = ROOT / "portable" / name
    command = f"$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath '{path}'))"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_signing_machinery_requires_explicit_identity_sha256_and_rfc3161() -> None:
    sign = (ROOT / "portable" / "sign_release.ps1").read_text(encoding="ascii")
    verify = (ROOT / "portable" / "verify_signatures.ps1").read_text(encoding="ascii")
    for token in ("Thumbprint", "/fd SHA256", "/tr $TimestampUrl", "/td SHA256", "/pa /all /tw"):
        assert token in sign
    assert "TEST_SIGNATURE_NOT_TRUSTED" in sign
    assert "SignedBundle" in sign and "fresh path disjoint" in sign
    assert "pre-sign manifest" in sign
    assert "Get-AuthenticodeSignature" in sign and "Get-AuthenticodeSignature" in verify
    assert "Cert:\\CurrentUser\\My" in sign
    assert "Cert:\\LocalMachine\\My" not in sign
    assert "$VerifyOs = '2:10.0.0'" in sign and "$VerifyOs = '2:10.0.0'" in verify
    assert "/o $VerifyOs" in sign and "/o $VerifyOs" in verify
    assert "promotion_eligible = $false" in sign
    for token in (
        "portable-member-manifest.json",
        "manifest_sha256",
        "member_set_digest",
        "executable_member_count",
        "signtool_policy_valid",
        "publisher_subject",
        "publisher_thumbprint",
        "timestamp_verified",
        "signing_lane_certificate_store = 'CurrentUser\\My'",
        "promotion_effect = 'NONE'",
    ):
        assert token in verify
    assert "BEGIN PRIVATE KEY" not in sign + verify


def _project_output(field: str) -> tuple[str, str]:
    from portable import atlas_bundle

    project = release_contract._NPM_INVENTORIES[field][0]
    outputs = [output for output in atlas_bundle.BUILD_OUTPUTS
               if output.rsplit("/", 1)[0] == project]
    assert len(outputs) == 1, outputs
    return project, outputs[0]


def test_shared_protocol_autocrlf_checkout_preserves_committed_byte_custody(tmp_path: Path) -> None:
    """The actual shared source must survive Windows checkout without relaxing its byte guard."""
    relative = "webapp/frontend/src/projectionEmbed.ts"
    committed = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{relative}"],
        cwd=ROOT, capture_output=True, check=True, timeout=30,
    ).stdout
    assert b"\n" in committed and b"\r" not in committed
    repository = tmp_path / "checkout"
    source = repository / relative
    source.parent.mkdir(parents=True)
    source.write_bytes(committed)
    (repository / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())

    def git(*arguments: str) -> bytes:
        return subprocess.run(
            ["git", *arguments], cwd=repository, capture_output=True, check=True, timeout=30,
        ).stdout

    git("init", "--quiet")
    git("config", "core.autocrlf", "true")
    git("config", "core.eol", "crlf")
    git("add", "--", ".gitattributes", relative)
    git("-c", "user.name=Byte custody test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Shared protocol checkout")
    assert git("cat-file", "blob", f"HEAD:{relative}") == committed
    source.unlink()
    git("checkout", "--", relative)
    assert source.read_bytes() == committed
    assert release_contract._shared_npm_source_receipts(repository, "atlas-scope/dist-hub") == {
        relative: {"bytes": len(committed), "sha256": hashlib.sha256(committed).hexdigest()},
    }

    # A checkout fix must not admit changed bytes, even if Git's index hides the edit.
    git("update-index", "--assume-unchanged", "--", relative)
    source.write_bytes(committed + b"// intentional custody mutation\n")
    assert git("diff", "--name-only", "HEAD", "--", relative) == b""
    with pytest.raises(release_contract.PortableReleaseError,
                       match="shared npm source bytes differ from committed blob"):
        release_contract._shared_npm_source_receipts(repository, "atlas-scope/dist-hub")


@pytest.mark.parametrize("field", sorted(release_contract._NPM_INVENTORIES))
def test_the_real_built_output_carries_bundler_runtime_packages_and_they_are_inventoried(
        field: str, tmp_path: Path) -> None:
    """W5-X5 against the REAL frontends: build each shipped output the way its npm script does
    (into a scratch tree that mirrors the repository layout), then derive the shipped-package set
    from a module-recording rebuild bound byte-for-byte to it. Vite's preload helper and Rolldown's
    runtime are in BOTH real builds although both packages are dev-only; the derived set beyond the
    production graph must be exactly the reviewed one (a new bundler-injected package must be
    reviewed before a release, as a production lock change already is)."""
    import shutil

    project, output = _project_output(field)
    project_root = ROOT.joinpath(*project.split("/"))
    vite = project_root / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if node is None or not vite.is_file():
        pytest.skip(f"{project}: node or its installed toolchain is absent (run npm ci there); the "
                    "built-output proof needs the real bundler, and nothing else can stand in for it")
    mirror = tmp_path / "mirror"
    shipped = mirror.joinpath(*output.split("/"))
    arguments = release_contract._vite_build_arguments(ROOT, output)
    built = subprocess.run(
        [node, str(vite), "build", *arguments, "--outDir", str(shipped), "--emptyOutDir",
         "--logLevel", "error"],
        cwd=project_root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    assert built.returncode == 0, built.stderr[-4000:]
    attribution = release_contract._npm_build_attribution(
        ROOT, field, build_root=mirror, required=True)
    assert attribution["status"] == "built_module_graph_bound"
    assert attribution["output"] == output
    # every shipped file is accounted for by the graph: chunks by their modules, emitted assets
    # (the HTML shell, stylesheets) by the files they were made from; none is attributed by default
    assert attribution["files_without_modules"] == [], attribution["files_without_modules"]
    names = {row["name"] for row in attribution["additional_rows"]}
    assert {"vite", "rolldown"} <= names, attribution["additional_rows"]
    virtual = {
        module for package in attribution["packages"] for module in package["virtual_modules"]}
    assert {"vite/preload-helper.js", "rolldown/runtime.js"} <= virtual, virtual
    assert tuple(
        f"{row['install_path']}@{row['version']}" for row in attribution["additional_rows"]
    ) == release_contract.EXPECTED_BUILD_ONLY_NPM_PACKAGES[field]
    # every production package whose modules ship is in the production graph already
    production = {row["install_path"] for row in release_contract._npm_production_packages(ROOT, project)}
    attributed = {package["install_path"] for package in attribution["packages"]}
    assert attributed - production == {row["install_path"] for row in attribution["additional_rows"]}
    # the derivation never records a path outside the project (no home directory in a receipt)
    assert str(ROOT).replace("\\", "/").casefold() not in json.dumps(attribution).casefold()
