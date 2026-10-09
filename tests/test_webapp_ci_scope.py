"""Executable contracts for the required-check-safe webapp CI path classifier."""

from __future__ import annotations

import importlib.util
import base64
from itertools import combinations
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
        # AssessHub serves the Atlas Scope hub build at /scope, and webapp-ci's backend leg builds
        # it and runs the /scope pins against it: an atlas-scope change engages webapp CI too.
        "atlas-scope/src/main.tsx",
        "atlas-scope/index.html",
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
        "tests/pytest_invocation_reader.py",
        "webapp/backend/export_ui_projection_openapi.py",
        ".github/workflows/webapp-ci.yml",
        ".github/scripts/classify_webapp_ci_scope.py",
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
        "webapp/backend/observe_ui_projection_contract.py",
        "tests/test_ui_projection_contract_observation.py",
        "master-reference/release/pipeline.py",
        "portable/release_contract.py",
        "portable/atlas_bundle.py",
        "portable/windows-x64-requirements.lock",
        "portable/third-party-license-fallbacks.json",
        "portable/third-party-licenses/jsonschema-rs-LICENSE",
        "tests/test_webapp_ci_scope.py",
        "tests/test_frontend_artifact_workflow_contract.py",
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
        "atlas-scope-neighbour/file.ts",
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


def test_frontend_gate_checks_generated_types_against_the_actual_backend():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    frontend = workflow.split("\n  frontend:", 1)[1].split("\n  e2e:", 1)[0]
    export = "python -m webapp.backend.export_ui_projection_openapi --output webapp/frontend/.generated/openapi.json"
    assert "actions/setup-python@" in frontend
    assert 'python -m pip install -e ".[dev]"' in frontend
    assert frontend.index(export) < frontend.index("npm run api:check")
    assert frontend.index("npm ci") < frontend.index("npm run api:check")
    assert frontend.index("npm run api:check") < frontend.index("npm run build")
    # Run from the checkout root so export imports this app and never a user store.
    export_step = frontend.split("      - name: Export the live backend contract offline", 1)[1]
    export_step = export_step.split("      - ", 1)[0]
    assert "working-directory: ." in export_step
    assert export in export_step
    assert "continue-on-error" not in frontend


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


def test_every_tests_helper_a_webapp_test_imports_engages_webapp_ci():
    """W5b: webapp/tests import helper modules from tests/ by bare name (root conftest.py puts tests/ on
    sys.path) -- tests/synthetic_fixtures.py, tests/pytest_invocation_reader.py. A change to one changes
    what webapp CI's suite does, so it must engage webapp CI. Derived from the webapp test modules' own
    imports, not from a list of known helpers."""
    import ast

    helpers = set()
    for module in sorted((ROOT / "webapp" / "tests").rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                     else [])
            for name in names:
                candidate = ROOT / "tests" / (name.split(".", 1)[0] + ".py")
                if candidate.is_file():
                    helpers.add(candidate.relative_to(ROOT).as_posix())
    assert "tests/pytest_invocation_reader.py" in helpers, sorted(helpers)  # the scan is live
    assert sorted(path for path in helpers if not SCOPE.path_is_relevant(path)) == []


MANUAL_FLAGS = ("prepare_frontend_dependencies", "receive_frontend_artifact", "observe_vite_distribution", "refresh_visual_baselines", "observe_jsonschema_rs")
CANONICAL_TEST_SRI = "sha512-" + base64.b64encode(bytes(64)).decode()


def _manual_values(operation=None):
    values = {name: "false" for name in MANUAL_FLAGS}
    values.update(frontend_artifact_selection="", vite_distribution_integrity="", jsonschema_rs_source_commit="")
    if operation:
        values[operation] = "true"
    if operation == "receive_frontend_artifact":
        # Preflight checks the bounded envelope; the receiver owns the full exact-source schema.
        values["frontend_artifact_selection"] = '{"schema":"frontend-artifact-selection/1","profile":"dependency-candidate"}'
    if operation == "observe_vite_distribution":
        values["vite_distribution_integrity"] = CANONICAL_TEST_SRI
    if operation == "observe_jsonschema_rs":
        values["jsonschema_rs_source_commit"] = "a" * 40
    return values


@pytest.mark.parametrize("operation", [None, *MANUAL_FLAGS])
def test_manual_preflight_admits_only_one_explicit_operation_or_normal_ci(operation):
    assert SCOPE.MANUAL_FLAGS == MANUAL_FLAGS
    assert SCOPE.validate_manual_operations("workflow_dispatch", _manual_values(operation)) == (operation or "none")


@pytest.mark.parametrize("first,second", list(combinations(MANUAL_FLAGS, 2)))
def test_manual_preflight_refuses_every_pair_of_operations(first, second):
    values = _manual_values(first)
    values[second] = "true"
    with pytest.raises(ValueError, match="mutually exclusive"):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


@pytest.mark.parametrize("value", ["", "True", "TRUE", "0", " false", False])
@pytest.mark.parametrize("flag", MANUAL_FLAGS)
def test_manual_flags_are_typed_environment_booleans(value, flag):
    values = _manual_values()
    values[flag] = value
    with pytest.raises(ValueError):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


@pytest.mark.parametrize("field", ["frontend_artifact_selection", "vite_distribution_integrity", "jsonschema_rs_source_commit"])
def test_disabled_manual_operation_refuses_even_whitespace_extra_data(field):
    values = _manual_values()
    values[field] = " "
    with pytest.raises(ValueError, match="supplied without"):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


@pytest.mark.parametrize("selection", ["", " ", "{}", "[]", "not-json", '{"a":1,"a":2}', '{"a":1,"\\u0061":2}',
                                       '{"a":NaN}', '{"a":1e999}', '{"a":"' + "x" * 4096 + '"}'])
def test_receive_preflight_requires_bounded_nonempty_json_without_duplicate_or_nonfinite_data(selection):
    values = _manual_values("receive_frontend_artifact")
    values["frontend_artifact_selection"] = selection
    with pytest.raises(ValueError):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


@pytest.mark.parametrize("integrity", ["", "sha256-abc", CANONICAL_TEST_SRI + "\n", "sha512-" + "A" * 85 + "B=="])
def test_observer_preflight_requires_canonical_exact_sha512(integrity):
    values = _manual_values("observe_vite_distribution")
    values["vite_distribution_integrity"] = integrity
    with pytest.raises(ValueError):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


@pytest.mark.parametrize("commit", ["", " ", "a" * 39, "a" * 64, "A" * 40, "g" * 40, "a" * 40 + "\n", False])
def test_native_observer_preflight_requires_exact_source_commit(commit):
    values = _manual_values("observe_jsonschema_rs")
    values["jsonschema_rs_source_commit"] = commit
    with pytest.raises(ValueError):
        SCOPE.validate_manual_operations("workflow_dispatch", values)


def test_manual_preflight_refuses_cross_operation_payloads_and_wrong_event():
    receive = _manual_values("receive_frontend_artifact")
    receive["vite_distribution_integrity"] = CANONICAL_TEST_SRI
    observe = _manual_values("observe_vite_distribution")
    observe["frontend_artifact_selection"] = '{"unexpected":"payload"}'
    native = _manual_values("observe_jsonschema_rs")
    native["vite_distribution_integrity"] = CANONICAL_TEST_SRI
    other_with_native_source = _manual_values("observe_vite_distribution")
    other_with_native_source["jsonschema_rs_source_commit"] = "a" * 40
    for values in (receive, observe, native, other_with_native_source):
        with pytest.raises(ValueError):
            SCOPE.validate_manual_operations("workflow_dispatch", values)
    with pytest.raises(ValueError, match="workflow_dispatch"):
        SCOPE.validate_manual_operations("pull_request", _manual_values())


def test_manual_input_census_is_closed():
    for mode in ("missing", "extra"):
        values = _manual_values()
        if mode == "missing":
            del values["refresh_visual_baselines"]
        else:
            values["arbitrary_command"] = "not accepted"
        with pytest.raises(ValueError, match="census"):
            SCOPE.validate_manual_operations("workflow_dispatch", values)


def test_manual_cli_only_validates_env_data_and_does_not_classify_or_write_output(monkeypatch, tmp_path):
    values = _manual_values("receive_frontend_artifact")
    values["frontend_artifact_selection"] = '{"quoted":"$(this remains inert data)"}'
    for name, value in values.items():
        monkeypatch.setenv("WEBAPP_MANUAL_" + name.upper(), value)
    output = tmp_path / "classification-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    def forbidden(*args, **kwargs):
        pytest.fail("manual preflight must not classify Git or execute a subprocess")
    monkeypatch.setattr(SCOPE, "classify", forbidden)
    monkeypatch.setattr(SCOPE.subprocess, "run", forbidden)
    assert SCOPE.main(["--event-name", "workflow_dispatch", "--validate-manual-operations"]) == 0
    assert not output.exists()
