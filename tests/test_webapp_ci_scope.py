"""Executable contracts for the required-check-safe webapp CI path classifier."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_PATH = ROOT / ".github" / "scripts" / "classify_webapp_ci_scope.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "webapp-ci.yml"


def _classifier_module():
    spec = importlib.util.spec_from_file_location("_classify_webapp_ci_scope", CLASSIFIER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCOPE = _classifier_module()


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "--all")
    _git(
        root,
        "-c",
        "user.name=Webapp Scope Test",
        "-c",
        "user.email=webapp-scope@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "core.autocrlf", "false")
    return root


def test_push_filter_and_classifier_share_the_exact_path_policy():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger_block = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    filters = [
        line.split("paths:", 1)[1].strip()
        for line in trigger_block.splitlines()
        if line.strip().startswith("paths:")
    ]
    assert len(filters) == 1, "pull_request must be unconditional; only push may be filtered"
    assert tuple(json.loads(filters[0])) == SCOPE.RELEVANT_PATH_FILTERS


@pytest.mark.parametrize(
    "path",
    [
        "webapp/frontend/src/App.tsx",
        ".design-sync/config.json",
        "cisco_toolkit/model.py",
        "reference-data/official-sources/registry.json",
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
        "tests/golden/snapshot.json",
        "tests/synthetic_fixtures.py",
        ".github/workflows/webapp-ci.yml",
        ".github/scripts/classify_webapp_ci_scope.py",
    ],
)
def test_every_policy_arm_has_a_relevant_witness(path: str):
    assert SCOPE.path_is_relevant(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/design.md",
        ".github/workflows/ci.yml",
        "webapp-neighbour/file.ts",
        "design-sync/config.json",
        "webapp\\frontend\\src\\App.tsx",
    ],
)
def test_irrelevant_paths_do_not_consume_the_expensive_jobs(path: str):
    assert not SCOPE.path_is_relevant(path)


def test_real_three_dot_diff_distinguishes_irrelevant_and_relevant_changes(tmp_path: Path):
    root = _repository(tmp_path)
    (root / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(root, "base")

    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("docs only\n", encoding="utf-8")
    docs_head = _commit(root, "docs")
    assert not SCOPE.classify(
        "pull_request",
        root=root,
        base_sha=base,
        head_sha=docs_head,
    )

    (root / "webapp" / "frontend").mkdir(parents=True)
    (root / "webapp" / "frontend" / "app.ts").write_text("export {};\n", encoding="utf-8")
    webapp_head = _commit(root, "webapp")
    assert SCOPE.classify(
        "pull_request",
        root=root,
        base_sha=docs_head,
        head_sha=webapp_head,
    )


def test_three_dot_diff_ignores_relevant_changes_unique_to_the_base_branch(tmp_path: Path):
    root = _repository(tmp_path)
    (root / "README.md").write_text("shared base\n", encoding="utf-8")
    common = _commit(root, "common base")

    _git(root, "checkout", "--quiet", "-b", "target")
    target_file = root / "webapp" / "frontend" / "base-only.ts"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("export {};\n", encoding="utf-8")
    base_sha = _commit(root, "base branch moves")

    _git(root, "checkout", "--quiet", "-b", "feature", common)
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("feature docs\n", encoding="utf-8")
    head_sha = _commit(root, "feature docs")

    assert SCOPE.changed_paths(root, base_sha, head_sha) == ("docs/note.md",)
    assert not SCOPE.classify(
        "pull_request", root=root, base_sha=base_sha, head_sha=head_sha
    )
    two_dot_paths = _git(
        root,
        "diff",
        "--name-only",
        "--no-renames",
        f"{base_sha}..{head_sha}",
    ).splitlines()
    assert "webapp/frontend/base-only.ts" in two_dot_paths


def test_moving_a_relevant_file_out_of_scope_still_runs_the_gate(tmp_path: Path):
    root = _repository(tmp_path)
    source = root / "webapp" / "frontend" / "legacy.ts"
    source.parent.mkdir(parents=True)
    source.write_text("export {};\n", encoding="utf-8")
    base = _commit(root, "base")

    (root / "docs").mkdir()
    _git(root, "mv", "webapp/frontend/legacy.ts", "docs/legacy.ts")
    head = _commit(root, "move out of scope")

    paths = set(SCOPE.changed_paths(root, base, head))
    assert {"webapp/frontend/legacy.ts", "docs/legacy.ts"} <= paths
    assert SCOPE.classify("pull_request", root=root, base_sha=base, head_sha=head)


def test_dispatch_and_unknown_added_events_conservatively_run_without_a_diff(tmp_path: Path):
    assert SCOPE.classify("workflow_dispatch", root=tmp_path)
    assert SCOPE.classify("future_event", root=tmp_path)


def test_missing_pr_identity_fails_without_writing_a_false_result(tmp_path: Path, capsys):
    output = tmp_path / "github-output.txt"
    result = SCOPE.main(
        [
            "--event-name",
            "pull_request",
            "--github-output",
            str(output),
            "--root",
            str(tmp_path),
        ]
    )
    assert result == 2
    assert not output.exists()
    assert "base SHA is missing or malformed" in capsys.readouterr().err


@pytest.mark.parametrize("unknown_sha", ["0" * 40, "a" * 40])
def test_unresolvable_pr_identity_fails_without_writing_a_result(
    unknown_sha: str, tmp_path: Path, capsys
):
    root = _repository(tmp_path)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    known_sha = _commit(root, "seed")
    output = tmp_path / "github-output.txt"

    assert SCOPE.main(
        [
            "--event-name",
            "pull_request",
            "--base-sha",
            unknown_sha,
            "--head-sha",
            known_sha,
            "--github-output",
            str(output),
            "--root",
            str(root),
        ]
    ) == 2
    assert not output.exists()
    assert "scope classification failed" in capsys.readouterr().err


def test_cli_writes_only_the_valid_boolean_contract(tmp_path: Path):
    output = tmp_path / "github-output.txt"
    assert SCOPE.main(
        [
            "--event-name",
            "workflow_dispatch",
            "--github-output",
            str(output),
            "--root",
            str(tmp_path),
        ]
    ) == 0
    assert output.read_text(encoding="utf-8") == "relevant=true\n"


def test_prs_execute_only_the_base_classifier_with_a_run_all_bootstrap():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    scope_job = workflow.split("\n  scope:", 1)[1].split("\n  backend:", 1)[0]

    trusted_object = (
        '"${WEBAPP_CI_BASE_SHA}:.github/scripts/classify_webapp_ci_scope.py"'
    )
    assert f"git cat-file -e {trusted_object}" in scope_job
    assert f"git show {trusted_object}" in scope_job
    assert 'python "$classifier"' in scope_job
    assert 'echo "relevant=true" >> "$GITHUB_OUTPUT"' in scope_job
    assert "git cat-file -e \"${WEBAPP_CI_BASE_SHA}^{commit}\"" in scope_job
    assert "git cat-file -e \"${WEBAPP_CI_HEAD_SHA}^{commit}\"" in scope_job
    assert scope_job.count("python .github/scripts/classify_webapp_ci_scope.py") == 1
    assert "persist-credentials: false" in scope_job


def test_pr_retargeting_is_an_explicit_scope_trigger():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger_block = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    assert "types: [opened, synchronize, reopened, edited]" in trigger_block


def test_one_stable_aggregate_gate_requires_exact_classified_results():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    gate = workflow.split("\n  gate:", 1)[1]

    assert "name: Webapp CI gate" in gate
    assert "needs: [scope, backend, frontend, e2e, visual]" in gate
    assert "if: ${{ always() }}" in gate
    assert "SCOPE_RESULT: ${{ needs.scope.result }}" in gate
    assert "RELEVANT: ${{ needs.scope.outputs.relevant }}" in gate
    for job in ("backend", "frontend", "e2e", "visual"):
        assert f"${{{{ needs.{job}.result }}}}" in gate
    assert 'true) expected="success"' in gate
    assert 'false) expected="skipped"' in gate
    assert 'if [[ "$result" != "$expected" ]]' in gate
