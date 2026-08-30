"""Release-workflow and immutable supply-chain contracts."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
_FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _release_module():
    path = ROOT / ".github" / "scripts" / "verify_release.py"
    spec = importlib.util.spec_from_file_location("_verify_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checkout_module():
    path = ROOT / ".github" / "scripts" / "verify_checkout_immutable.py"
    spec = importlib.util.spec_from_file_location("_verify_checkout_immutable", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _clean_repository(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_bytes(b"ignored/\n")
    (root / "tracked.txt").write_bytes(b"frozen\n")
    _git(root, "add", ".gitignore", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Distribution Test",
        "-c",
        "user.email=distribution-test@example.invalid",
        "commit",
        "-m",
        "frozen source",
    )
    return (
        root,
        _git(root, "rev-parse", "HEAD^{commit}"),
        _git(root, "rev-parse", "HEAD^{tree}"),
    )


def test_every_action_is_pinned_to_an_immutable_commit():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("- uses:"):
                continue
            target = stripped.split("#", 1)[0].split("uses:", 1)[1].strip()
            if target.startswith("./"):
                continue
            revision = target.rsplit("@", 1)[-1] if "@" in target else ""
            if not _FULL_SHA.fullmatch(revision):
                offenders.append(f"{path.name}:{number}: {target}")
    assert not offenders, "mutable or unversioned Actions dependencies: " + "; ".join(offenders)


def test_pull_request_workflows_cannot_select_self_hosted_runners():
    for name in ("ci.yml", "webapp-ci.yml"):
        body = "\n".join(
            line for line in _workflow(name).splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "self-hosted" not in body
        assert "CI_RUNNER" not in body
        runs_on = [
            line.split("runs-on:", 1)[1].strip()
            for line in body.splitlines()
            if line.strip().startswith("runs-on:")
        ]
        assert runs_on
        assert all(
            value in {"ubuntu-latest", "windows-2025", "${{ matrix.os }}"}
            for value in runs_on
        )


def test_no_workflow_that_handles_pull_requests_can_select_self_hosted_runners():
    """The STRUCTURAL form of the guard above, which is scoped to two workflows by NAME.

    The invariant (ci.yml header) is about the event, not about those two files: code arriving
    via a pull request must only ever execute on GitHub-hosted, ephemeral runners — never on a
    persistent local machine holding credentials or private state. A future workflow file with a
    `pull_request` trigger would evade a named list, so this sweeps EVERY workflow: any file
    whose non-comment body engages with pull_request events at all must not select self-hosted
    runners. Push-to-main workflows may use the fleet after review and merge; any manual-dispatch
    trust boundary needs a separate workflow-specific guard."""
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        body = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        if "pull_request" in body and "self-hosted" in body:
            offenders.append(path.name)
    assert not offenders, (
        "workflows that handle pull_request events must never run on self-hosted runners: "
        + ", ".join(offenders)
    )
    # NON-VACUITY, both directions: the sweep saw a pull_request workflow and a self-hosted one.
    bodies = {p.name: p.read_text(encoding="utf-8") for p in WORKFLOWS.glob("*.yml")}
    assert any("pull_request" in b for b in bodies.values())
    assert any("self-hosted" in "\n".join(
        line for line in b.splitlines() if not line.lstrip().startswith("#")
    ) for b in bodies.values()), "no self-hosted workflow found — the sweep proves nothing"


def test_main_selfhosted_runs_only_after_main_integration_with_bounded_job_timeouts():
    body = _workflow("main-selfhosted.yml")
    uncommented = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )
    events = re.search(r"(?ms)^on:\n.*?(?=^permissions:)", uncommented)
    permissions = re.search(r"(?ms)^permissions:\n.*?(?=^concurrency:)", uncommented)
    concurrency = re.search(r"(?ms)^concurrency:\n.*?(?=^jobs:)", uncommented)
    assert events and events.group(0).strip() == "on:\n  push:\n    branches: [main]"
    assert permissions and permissions.group(0).strip() == "permissions:\n  contents: read"
    assert concurrency and concurrency.group(0).strip() == (
        "concurrency:\n  group: mainsh-${{ github.ref }}\n  cancel-in-progress: true"
    )
    assert len(re.findall(r"(?m)^on:$", uncommented)) == 1
    assert len(re.findall(r"(?m)^permissions:$", uncommented)) == 1
    assert len(re.findall(r"(?m)^concurrency:$", uncommented)) == 1
    assert "continue-on-error:" not in uncommented
    assert "|| true" not in uncommented

    suite, frontend = uncommented.split("  frontend:", 1)
    assert suite.count("runs-on: [self-hosted, Windows, X64]") == 1
    assert suite.count("timeout-minutes: 120") == 1
    assert "timeout-minutes: 45" not in suite
    runner_python = '& "$env:RUNNER_TEMP\\ci-venv\\Scripts\\python.exe"'
    expected_runs = [
        'run: py -3.12 -m venv "$env:RUNNER_TEMP\\ci-venv"',
        f"run: '{runner_python} -m pip install --upgrade pip'",
        f"""run: '{runner_python} -m pip install -e ".[dev]"'""",
        f"run: '{runner_python} -m ruff check .'",
        f"run: '{runner_python} .github/scripts/verify_repository_privacy.py'",
        f"run: '{runner_python} -m pytest'",
    ]
    actual_runs = [
        line.strip() for line in suite.splitlines() if line.strip().startswith("run:")
    ]
    assert actual_runs == expected_runs

    assert frontend.count("runs-on: [self-hosted, Windows, X64]") == 1
    assert frontend.count("timeout-minutes: 45") == 1
    assert "timeout-minutes: 120" not in frontend
    expected_frontend_runs = [
        "run: npm --prefix webapp/frontend run verify:node",
        "run: npm --prefix webapp/frontend ci",
        "run: npm --prefix webapp/frontend test -- --maxWorkers=4",
        "run: npm --prefix webapp/frontend run build",
        "run: Set-Location webapp/frontend; npx playwright install chromium",
        "run: Set-Location webapp/frontend; npm run test:e2e",
    ]
    actual_frontend_runs = [
        line.strip() for line in frontend.splitlines() if line.strip().startswith("run:")
    ]
    assert actual_frontend_runs == expected_frontend_runs
    frontend_manifest = json.loads(
        (ROOT / "webapp" / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert frontend_manifest["scripts"]["test"] == "vitest run"
    expected_unit_test_step = (
        "      - name: Frontend unit tests\n"
        "        env:\n"
        '          VITEST_MAX_WORKERS: "4"\n'
        "        run: npm --prefix webapp/frontend test -- --maxWorkers=4"
    )
    assert frontend.count(expected_unit_test_step) == 1
    assert frontend.count("env:") == 2
    assert frontend.count('VITEST_MAX_WORKERS: "4"') == 1
    assert 'E2E_PORT: "42973"' in frontend
    assert "VITEST_" not in frontend.replace('VITEST_MAX_WORKERS: "4"', "")
    for forbidden in (
        "--retry",
        "--pool",
        "--testNamePattern",
        "--passWithNoTests",
    ):
        assert forbidden not in frontend
    vitest_config = (ROOT / "webapp" / "frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )
    assert sorted(path.name for path in (ROOT / "webapp" / "frontend").glob("vite.config.*")) == [
        "vite.config.ts"
    ]
    assert not list((ROOT / "webapp" / "frontend").glob("vitest.config.*"))
    assert not list((ROOT / "webapp" / "frontend").glob("vitest.workspace.*"))
    expected_vitest_test_config = """  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "text"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },"""
    assert vitest_config.count(expected_vitest_test_config) == 1
    assert len(re.findall(r"(?m)^\s*test\s*:", vitest_config)) == 1
    assert vitest_config.count("export default defineConfig({") == 1
    assert vitest_config.rstrip().endswith("});")
    assert "..." not in vitest_config
    assert re.search(r"(?:^|[,{]\s*)\[[^\]\r\n]+\]\s*:", vitest_config) is None
    for forbidden_field in (
        "bail",
        "dangerouslyIgnoreUnhandledErrors",
        "fileParallelism",
        "hookTimeout",
        "isolate",
        "maxWorkers",
        "minWorkers",
        "passWithNoTests",
        "pool",
        "poolOptions",
        "retry",
        "testNamePattern",
        "testTimeout",
    ):
        assert re.search(rf"\b{re.escape(forbidden_field)}\s*:", vitest_config) is None


def test_publish_promotes_release_assets_without_rebuilding():
    body = _workflow("publish.yml")
    assert "workflow_dispatch:" in body
    assert "release:" not in body
    assert "gh release download" in body
    assert "python -m build" not in body
    assert "dist/*.whl" in body and "dist/*.tar.gz" in body
    assert "id-token: write" in body
    assert "attestations: true" in body
    assert (
        '--expected-json "${RUNNER_TEMP}/release-proof/dist-verification.json"'
        in body
    )
    assert "verify_repository_privacy.py" in body
    assert '"twine==6.2.0"' in body
    assert "twine>=" not in body
    assert "verify_checkout_immutable.py" in body
    assert "HEAD^{commit}" in body and "HEAD^{tree}" in body
    assert "--source-commit" in body and "--source-tree" in body
    assert '--pattern "dist-verification.json"' in body
    assert "packages-dir: dist/" in body
    assert "Reverify the exact archive bytes immediately before publication" in body
    assert '--tag "${{ inputs.tag }}"' not in body
    assert 'download "${{ inputs.tag }}"' not in body


def test_release_builds_once_and_reuses_assets_on_rerun():
    body = _workflow("release.yml")
    assert "gh release view" in body
    assert "gh release download" in body
    assert "steps.existing.outputs.exists == 'false'" in body
    assert "cisco_toolkit.distribution_verify" in body
    assert ".github/scripts/verify_release.py" in body
    assert "--expected-json dist/dist-verification.json" in body
    assert "verify_repository_privacy.py" in body
    assert '"build==1.5.0"' in body
    assert '"twine==6.2.0"' in body
    assert "build>=" not in body and "twine>=" not in body
    assert "dist/dist-verification.json" in body
    assert body.count("verify_checkout_immutable.py") >= 8
    assert "HEAD^{commit}" in body and "HEAD^{tree}" in body
    assert body.count("--source-commit") == 3
    assert body.count("--source-tree") == 3
    assert '"dist/${wheel}"' in body and '"dist/${sdist}"' in body
    assert "dist/*.whl dist/*.tar.gz dist/dist-verification.json" not in body


def test_ci_distribution_job_pins_tools_and_rechecks_immutable_source():
    body = _workflow("ci.yml")
    assert '"build==1.5.0"' in body
    assert '"twine==6.2.0"' in body
    assert "build>=" not in body and "twine>=" not in body
    assert "--json-out dist/dist-verification.json" in body
    assert body.count("verify_checkout_immutable.py") >= 7
    assert "HEAD^{commit}" in body and "HEAD^{tree}" in body
    assert body.count("--source-commit") == 2
    assert body.count("--source-tree") == 2
    assert "Reverify the exact archive bytes immediately before preservation" in body


@pytest.mark.parametrize(
    ("workflow", "install_command", "selftest_line"),
    (
        (
            "ci.yml",
            "pip install --force-reinstall dist/*.whl",
            "          assesshub --selftest\n",
        ),
        (
            "release.yml",
            "pip install --force-reinstall dist/*.whl",
            "          assesshub --selftest\n",
        ),
        (
            "release-selfhosted.yml",
            "pip install --quiet $wheel",
            '          & "$env:RUNNER_TEMP\\smoke-venv\\Scripts\\assesshub.exe" --selftest\n',
        ),
    ),
)
def test_installed_wheel_selftest_gates_every_release_path(
    workflow, install_command, selftest_line
):
    """The EoL authority check is meaningful only if every built-wheel path executes it."""
    body = _workflow(workflow)
    install_at = body.index(install_command)
    selftest_at = body.index(selftest_line)

    assert install_at < selftest_at
    assert "('eol', eoldb.registry_health())" in body[selftest_at:]
    assert "registry_integrity as R" in body[selftest_at:]


def test_immutable_checkout_helper_accepts_only_a_stable_clean_tree(tmp_path):
    root, commit, tree = _clean_repository(tmp_path)
    helper = _checkout_module()

    assert helper.verify_checkout(root, commit, tree) == {
        "commit": commit,
        "tree": tree,
        "tracked_files_verified": 2,
        "untracked_entries": 0,
    }

    (root / "ignored").mkdir()
    (root / "ignored" / "tool-output.txt").write_bytes(b"ignored\n")
    with pytest.raises(ValueError, match="including ignored files"):
        helper.verify_checkout(root, commit, tree)
    assert helper.verify_checkout(
        root,
        commit,
        tree,
        allowed_untracked_prefixes=("ignored",),
    )["untracked_entries"] == 1


def test_immutable_checkout_helper_rejects_tracked_and_untracked_mutations(tmp_path):
    root, commit, tree = _clean_repository(tmp_path)
    helper = _checkout_module()

    (root / "tracked.txt").write_bytes(b"mutated\n")
    with pytest.raises(ValueError, match="tracked checkout bytes"):
        helper.verify_checkout(root, commit, tree)

    (root / "tracked.txt").write_bytes(b"frozen\n")
    (root / "unexpected.txt").write_bytes(b"unexpected\n")
    with pytest.raises(ValueError, match="unapproved untracked"):
        helper.verify_checkout(root, commit, tree)


def test_immutable_checkout_helper_rejects_hidden_index_mutations(tmp_path):
    root, commit, tree = _clean_repository(tmp_path)
    helper = _checkout_module()

    _git(root, "update-index", "--assume-unchanged", "tracked.txt")
    (root / "tracked.txt").write_bytes(b"hidden mutation\n")
    with pytest.raises(ValueError, match="assume-unchanged"):
        helper.verify_checkout(root, commit, tree)


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v3.31.0", "3.31.0"),
        ("v1.0.0rc1", "1.0.0rc1"),
    ],
)
def test_release_tag_validator_accepts_only_the_exact_project_version(tag, version):
    _release_module().validate_tag(tag, version)


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("3.31.0", "3.31.0"),
        ("v3.31", "3.31.0"),
        ("v3.31.1", "3.31.0"),
        ("v3.31.0/extra", "3.31.0"),
        ("v3.31.0", "3.31.0rc1"),
    ],
)
def test_release_tag_validator_rejects_malformed_or_mismatched_refs(tag, version):
    with pytest.raises(ValueError):
        _release_module().validate_tag(tag, version)
