"""The engine-output handoff workflow stays manual, read-only, source-bound, closed and nonpromoting.

It is a dispatch-only path that regenerates tracked engine outputs for review. These guards keep it
from ever running on a pull request or push, gaining a token or write permission, running anything
beyond the repository's own regeneration commands, or uploading after a failure; and they derive the
handoff's closed output set from the producers' own write targets rather than trusting a list.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
from pathlib import Path
import subprocess

import pytest
import yaml

from test_release_supply_chain import _RUNNER_JOBS, _RunnerWorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = ROOT / ".github" / "workflows" / "engine-output-handoff.yml"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
PYTHON = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def _load():
    spec = importlib.util.spec_from_file_location(
        "engine_output_handoff_contract", ROOT / ".github" / "scripts" / "engine_output_handoff.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handoff = _load()
GATE, UPGRADE, INSTALL, CONTROLS, BEFORE, GOLDEN, SAMPLE, CAPTURE, PRESERVE = handoff.REQUIRED_STEPS


def document():
    # The supply-chain contract's reader keeps GitHub's textual `on` and refuses duplicate keys.
    return yaml.load(WORKFLOW_FILE.read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)


def named(steps, name):
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def assert_wiring(doc):
    assert WORKFLOW_FILE.relative_to(ROOT).as_posix() == handoff.WORKFLOW
    assert set(doc) == {"name", "on", "permissions", "concurrency", "jobs"}
    # Dispatch only: never pull_request, pull_request_target, push, schedule or workflow_run.
    assert set(doc["on"]) == {"workflow_dispatch"}
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"expected_source_commit", "allow_golden_shrink"}
    assert set(inputs["expected_source_commit"]) == {"description", "required", "type"}
    assert inputs["expected_source_commit"]["required"] is True
    assert inputs["expected_source_commit"]["type"] == "string"
    assert inputs["allow_golden_shrink"] == {
        "description": inputs["allow_golden_shrink"]["description"],
        "required": False, "default": False, "type": "boolean",
    }
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"] == {"group": "engine-output-handoff-${{ github.ref }}", "cancel-in-progress": False}
    assert set(doc["jobs"]) == set(_RUNNER_JOBS[WORKFLOW_FILE.name]) == {"regenerate"}

    job = doc["jobs"]["regenerate"]
    assert set(job) == {"name", "runs-on", "timeout-minutes", "env", "steps"}
    assert job["name"] == handoff.JOB_NAME
    assert [job["runs-on"]] == list(handoff.RUNNER_LABELS) == ["ubuntu-24.04"]
    assert job["env"] == {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "TZ": handoff.CANONICAL_TZ}
    steps = job["steps"]
    # The receiver requires exactly these named steps to have succeeded.
    assert [step["name"] for step in steps if "name" in step] == list(handoff.REQUIRED_STEPS)
    assert {step["uses"] for step in steps if "uses" in step} == {CHECKOUT, PYTHON, UPLOAD}
    for step in steps:
        assert "if" not in step and "continue-on-error" not in step, step
        assert "working-directory" not in step and "shell" not in step or step.get("name") == GATE, step
        assert "${{" not in step.get("run", ""), "inputs reach a script only through env"
        for key in step.get("env", {}):
            assert not any(part in key.upper() for part in ("TOKEN", "SECRET", "AUTH")), key
    text = WORKFLOW_FILE.read_text(encoding="utf-8")
    for credential in ("github.token", "secrets.", "GH_TOKEN", "GITHUB_TOKEN"):
        assert credential not in text, credential

    gate = named(steps, GATE)
    assert gate["shell"] == "bash" and gate["env"] == {"EXPECTED_SOURCE_COMMIT": "${{ inputs.expected_source_commit }}"}
    assert 'set -euo pipefail' in gate["run"]
    assert '"$EXPECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$' in gate["run"]
    assert '"$EXPECTED_SOURCE_COMMIT" != "$GITHUB_SHA"' in gate["run"]
    checkout = [step for step in steps if step.get("uses") == CHECKOUT]
    assert len(checkout) == 1 and checkout[0] == {
        "uses": CHECKOUT, "with": {"ref": "${{ github.sha }}", "persist-credentials": False}}
    python = [step for step in steps if step.get("uses") == PYTHON]
    assert len(python) == 1 and python[0] == {"uses": PYTHON, "with": {"python-version": "3.12"}}
    assert named(steps, UPGRADE) == {"name": UPGRADE, "run": "python -m pip install --upgrade pip"}
    assert named(steps, INSTALL) == {"name": INSTALL, "run": "python -m pip install -r requirements-dev.txt"}
    assert handoff.CONTROL_COMMAND == (
        "python -m pytest -p no:cacheprovider tests/test_engine_output_handoff.py"
        " tests/test_engine_output_handoff_workflow_contract.py"
    )
    assert named(steps, CONTROLS) == {"name": CONTROLS, "run": handoff.CONTROL_COMMAND}
    assert named(steps, BEFORE) == {
        "name": BEFORE, "env": {"EXPECTED_SOURCE_COMMIT": "${{ inputs.expected_source_commit }}"},
        "run": 'python -I -B .github/scripts/engine_output_handoff.py before --state "$RUNNER_TEMP/engine-output-state"',
    }
    assert named(steps, GOLDEN) == {
        "name": GOLDEN,
        "env": {"UPDATE_GOLDEN": "1", "ALLOW_GOLDEN_SHRINK": "${{ inputs.allow_golden_shrink && '1' || '0' }}"},
        "run": handoff.GOLDEN_COMMAND,
    }
    assert named(steps, SAMPLE) == {"name": SAMPLE, "run": handoff.SAMPLE_COMMAND}
    assert named(steps, CAPTURE) == {
        "name": CAPTURE,
        "env": {"EXPECTED_SOURCE_COMMIT": "${{ inputs.expected_source_commit }}",
                "ALLOW_GOLDEN_SHRINK_INPUT": "${{ inputs.allow_golden_shrink }}"},
        "run": ("python -I -B .github/scripts/verify_repository_privacy.py --root .\n"
                'python -I -B .github/scripts/engine_output_handoff.py after --state "$RUNNER_TEMP/engine-output-state"'
                ' --output "$RUNNER_TEMP/engine-output-handoff"\n'),
    }
    # Success-only upload (no `if`): a failed regeneration never leaves an importable artifact.
    assert named(steps, PRESERVE) == {
        "name": PRESERVE, "uses": UPLOAD, "with": {
            "name": handoff.artifact_name("${{ github.sha }}", "${{ github.run_id }}", "${{ github.run_attempt }}"),
            "path": "${{ runner.temp }}/engine-output-handoff/",
            "if-no-files-found": "error", "retention-days": 14,
        },
    }
    order = [steps.index(step) for step in (gate, checkout[0], python[0], named(steps, UPGRADE),
                                            named(steps, INSTALL), named(steps, CONTROLS), named(steps, BEFORE), named(steps, GOLDEN),
                                            named(steps, SAMPLE), named(steps, CAPTURE), named(steps, PRESERVE))]
    assert order == list(range(len(steps)))


def test_handoff_workflow_is_manual_read_only_source_bound_and_closed():
    assert_wiring(document())


@pytest.mark.parametrize("mutation", [
    "pull-request", "push", "schedule", "workflow-run", "write-permission", "job-permission", "token-env",
    "input-in-shell", "upload-always", "upload-on-failure", "continue-on-error", "retained-credentials",
    "floating-ref", "dropped-before", "dropped-gate", "extra-step", "whole-golden-file", "no-update-golden",
    "forced-shrink", "dropped-tz", "other-python", "floating-image", "reordered", "different-sample-command",
    "input-default-shrink", "optional-source", "no-error-on-empty", "dropped-controls", "different-controls",
])
def test_wiring_guard_detects_trigger_privilege_scope_and_order_regressions(mutation):
    doc = copy.deepcopy(document())
    job = doc["jobs"]["regenerate"]
    steps = job["steps"]
    if mutation == "pull-request":
        doc["on"]["pull_request"] = None
    elif mutation == "push":
        doc["on"]["push"] = {"branches": ["main"]}
    elif mutation == "schedule":
        doc["on"]["schedule"] = [{"cron": "0 3 * * *"}]
    elif mutation == "workflow-run":
        doc["on"]["workflow_run"] = {"workflows": ["CI"]}
    elif mutation == "write-permission":
        doc["permissions"]["contents"] = "write"
    elif mutation == "job-permission":
        job["permissions"] = {"actions": "write"}
    elif mutation == "token-env":
        named(steps, CAPTURE)["env"]["GH_TOKEN"] = "${{ github.token }}"
    elif mutation == "input-in-shell":
        named(steps, BEFORE)["run"] = "python before.py --commit '${{ inputs.expected_source_commit }}'"
    elif mutation == "upload-always":
        named(steps, PRESERVE)["if"] = "${{ always() }}"
    elif mutation == "upload-on-failure":
        named(steps, PRESERVE)["if"] = "${{ failure() }}"
    elif mutation == "continue-on-error":
        named(steps, GOLDEN)["continue-on-error"] = True
    elif mutation == "retained-credentials":
        next(step for step in steps if step.get("uses") == CHECKOUT)["with"]["persist-credentials"] = True
    elif mutation == "floating-ref":
        next(step for step in steps if step.get("uses") == CHECKOUT)["with"]["ref"] = "${{ inputs.expected_source_commit }}"
    elif mutation == "dropped-before":
        steps.remove(named(steps, BEFORE))
    elif mutation == "dropped-controls":
        steps.remove(named(steps, CONTROLS))
    elif mutation == "different-controls":
        named(steps, CONTROLS)["run"] = "python -m pytest tests/test_sample_fleet.py"
    elif mutation == "dropped-gate":
        steps.remove(named(steps, GATE))
    elif mutation == "extra-step":
        steps.insert(-1, {"name": "Regenerate the frontend distribution", "run": "npm run build"})
    elif mutation == "whole-golden-file":
        named(steps, GOLDEN)["run"] = "python -m pytest tests/test_pipeline_golden.py"
    elif mutation == "no-update-golden":
        del named(steps, GOLDEN)["env"]["UPDATE_GOLDEN"]
    elif mutation == "forced-shrink":
        named(steps, GOLDEN)["env"]["ALLOW_GOLDEN_SHRINK"] = "1"
    elif mutation == "dropped-tz":
        del job["env"]["TZ"]
    elif mutation == "other-python":
        next(step for step in steps if step.get("uses") == PYTHON)["with"]["python-version"] = "3.13"
    elif mutation == "floating-image":
        job["runs-on"] = "ubuntu-latest"
    elif mutation == "reordered":
        golden, sample = named(steps, GOLDEN), named(steps, SAMPLE)
        a, b = steps.index(golden), steps.index(sample)
        steps[a], steps[b] = sample, golden
    elif mutation == "different-sample-command":
        named(steps, SAMPLE)["run"] = "python webapp/sample_data/build_sample.py --out /tmp/sample.json"
    elif mutation == "input-default-shrink":
        doc["on"]["workflow_dispatch"]["inputs"]["allow_golden_shrink"]["default"] = True
    elif mutation == "optional-source":
        doc["on"]["workflow_dispatch"]["inputs"]["expected_source_commit"]["required"] = False
    else:
        named(steps, PRESERVE)["with"]["if-no-files-found"] = "warn"
    with pytest.raises(AssertionError):
        assert_wiring(doc)


def _golden_harness_targets() -> set[str]:
    """Every golden name tests/test_pipeline_golden.py hands its one writer, `_golden`, read from its AST."""
    tree = ast.parse((ROOT / "tests" / "test_pipeline_golden.py").read_text(encoding="utf-8"))
    names = {node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_golden"
             and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    return {f"tests/golden/{name}" for name in names}


def _sample_builder_target() -> str:
    """build_sample.py's OUT, read from its AST: os.path.join(_HERE, "<name>")."""
    tree = ast.parse((ROOT / "webapp" / "sample_data" / "build_sample.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["OUT"]:
            call = node.value
            assert isinstance(call, ast.Call) and len(call.args) == 2
            assert isinstance(call.args[0], ast.Name) and call.args[0].id == "_HERE"
            assert isinstance(call.args[1], ast.Constant)
            return f"webapp/sample_data/{call.args[1].value}"
    raise AssertionError("build_sample.py no longer assigns OUT")


def _tracked(*pathspecs: str) -> set[str]:
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *pathspecs],
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return {item.decode("utf-8") for item in proc.stdout.split(b"\0") if item}


def test_closed_output_set_is_exactly_what_the_regeneration_commands_write():
    produced = _golden_harness_targets() | {_sample_builder_target()}
    assert produced == set(handoff.OUTPUT_PATHS)
    assert list(handoff.OUTPUT_PATHS) == sorted(handoff.OUTPUT_PATHS)
    # Every tracked golden and sample JSON is in the set, so a new one cannot fall outside the handoff.
    tracked = {path for path in _tracked("tests/golden", "webapp/sample_data") if path.endswith(".json")}
    assert tracked == set(handoff.OUTPUT_PATHS)


def test_golden_command_names_the_harness_writers_that_exist():
    words = handoff.GOLDEN_COMMAND.split()
    assert words[:3] == ["python", "-m", "pytest"] and "-p" in words and "no:cacheprovider" in words
    nodes = [word for word in words if "::" in word]
    assert nodes, "the golden command names no harness test"
    tree = ast.parse((ROOT / "tests" / "test_pipeline_golden.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    written = set()
    for node in nodes:
        path, name = node.split("::")
        assert path == "tests/test_pipeline_golden.py" and name in functions, node
        calls = [call for call in ast.walk(functions[name]) if isinstance(call, ast.Call)
                 and isinstance(call.func, ast.Name) and call.func.id == "_golden"]
        assert len(calls) == 1, name
        written.add(f"tests/golden/{calls[0].args[0].value}")
    # The two named tests are exactly the harness's writers: none is skipped, none is extra.
    assert written == _golden_harness_targets()


def test_sample_command_runs_the_tracked_builder_with_its_default_output():
    assert handoff.SAMPLE_COMMAND == "python webapp/sample_data/build_sample.py"
    assert "webapp/sample_data/build_sample.py" in _tracked("webapp/sample_data")


def test_final_committed_sample_has_a_non_regenerating_utc_gate():
    ci = yaml.load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)
    steps = ci["jobs"]["test"]["steps"]
    candidates = [step for step in steps if step.get("name") == "Reproduce the complete committed sample under UTC"]
    assert candidates == [{
        "name": "Reproduce the complete committed sample under UTC",
        "if": "matrix.os == 'ubuntu-24.04' && matrix.python-version == '3.12'",
        "env": {"TZ": "UTC"},
        "run": "python webapp/sample_data/build_sample.py --check",
    }]
    assert steps.index(candidates[0]) > next(i for i, step in enumerate(steps)
                                            if step.get("name") == "Run the complete default suite")


def test_repository_identity_matches_the_published_project():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f"github.com/{handoff.REPO}" in pyproject
    receiver = (ROOT / ".github" / "scripts" / "frontend_artifact_receive.py").read_text(encoding="utf-8")
    assert f'REPO = "{handoff.REPO}"' in receiver


def test_installer_profile_is_a_fixed_non_code_set_for_the_tracked_project():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "cisco-migration-assessment-toolkit"' in pyproject
    assert 'build-backend = "setuptools.build_meta"' in pyproject
    assert handoff.INSTALLER_ROOT == "cisco_migration_assessment_toolkit.egg-info/"
    assert handoff.INSTALLER_PATHS == {
        "cisco_migration_assessment_toolkit.egg-info/" + name for name in
        ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt")
    }


def test_handoff_doc_and_registry_name_the_owner():
    doc = (ROOT / "docs" / "engine-output-handoff.md").read_text(encoding="utf-8")
    for token in (handoff.WORKFLOW, ".github/scripts/engine_output_handoff.py", "receive --run-id",
                  *handoff.OUTPUT_PATHS):
        assert token in doc, token
    registry = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "docs/engine-output-handoff.md" in registry
    assert ".github/scripts/engine_output_handoff.py :: OUTPUT_PATHS" in registry
