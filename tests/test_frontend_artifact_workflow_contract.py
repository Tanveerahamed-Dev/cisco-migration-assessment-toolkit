"""Structural guards for optional, nonpromoting hosted frontend data operations."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from test_release_supply_chain import _RUNNER_JOBS, _RunnerWorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/webapp-ci.yml"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
PYTHON = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
PREFLIGHT = "Validate exclusive manual operations and bound data inputs"
RECEIVE = "Receive finite reviewed frontend edit data"
OBSERVE = "Observe the independently selected Vite distribution bytes"
RECEIVE_TEST = "Test finite frontend artifact receipt refusals"
OBSERVE_TEST = "Test fixed Vite distribution observation refusals"
MATERIAL_TEST = "Test candidate material observation contracts"
MATERIAL_CHECK = "Check installed Vite bytes and observe the canonical frontend inventory"
MATERIAL_UPLOAD = "Preserve candidate material observations and failures"
NATIVE_TEST = "Test selected native wheel observation refusals"
NATIVE_OBSERVE = "Observe the selected native Windows wheel as data"
NATIVE_UPLOAD = "Preserve native wheel observations and failures"
FLAGS = ("prepare_frontend_dependencies", "receive_frontend_artifact", "observe_vite_distribution", "refresh_visual_baselines", "observe_jsonschema_rs")
DATA = ("frontend_artifact_selection", "vite_distribution_integrity", "jsonschema_rs_source_commit")
REVIEW_PATHS = (
    ".github/scripts/frontend_artifact_receive.py", ".github/scripts/frontend_candidate_admit.mjs",
    ".github/scripts/test_frontend_artifact_receive.py", ".github/scripts/observe_vite_distribution.py",
    ".github/scripts/test_observe_vite_distribution.py", "tests/test_webapp_ci_scope.py",
    "tests/test_frontend_artifact_workflow_contract.py",
    ".github/scripts/frontend_candidate_materials.py", ".github/scripts/test_frontend_candidate_materials.py",
    ".github/scripts/observe_jsonschema_rs_wheel.py", "tests/test_jsonschema_rs_observation.py",
    "master-reference/release/pipeline.py", "portable/release_contract.py",
    "portable/atlas_bundle.py", "portable/windows-x64-requirements.lock",
    "portable/third-party-license-fallbacks.json", "portable/third-party-licenses/jsonschema-rs-LICENSE",
)


def document():
    # Reuse the existing supply-chain contract's duplicate-key-refusing YAML reader,
    # which retains GitHub's textual `on` and real true/false scalars.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=_RunnerWorkflowLoader)


def named(steps, name):
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def assert_wiring(doc):
    assert set(doc["jobs"]) == set(_RUNNER_JOBS["webapp-ci.yml"])
    assert doc["permissions"] == {"contents": "read"}
    assert not doc.get("env")
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == set(FLAGS + DATA)
    for name in FLAGS + DATA:
        spec = inputs[name]
        assert set(spec) == {"description", "required", "default", "type"}
        assert spec["required"] is False
        if name in FLAGS:
            assert spec["type"] == "boolean" and spec["default"] is False
        else:
            assert spec["type"] == "string" and spec["default"] == ""
    assert doc["on"]["pull_request"] == {"types": ["opened", "synchronize", "reopened", "edited"]}
    assert doc["on"]["push"]["branches"] == ["main"]
    assert set(REVIEW_PATHS) <= set(doc["on"]["push"]["paths"])

    scope = doc["jobs"]["scope"]
    steps = scope["steps"]
    preflight = named(steps, PREFLIGHT)
    assert preflight == {
        "name": PREFLIGHT, "if": "${{ github.event_name == 'workflow_dispatch' }}",
        "env": {"WEBAPP_MANUAL_" + name.upper(): "${{ inputs." + name + " }}" for name in FLAGS + DATA},
        "run": "python -I -B .github/scripts/classify_webapp_ci_scope.py --validate-manual-operations",
    }
    setup = next(step for step in steps if step.get("uses") == PYTHON)
    classifier = next(step for step in steps if step.get("id") == "classify")
    assert steps.index(setup) < steps.index(preflight) < steps.index(classifier)
    # The manual-only preflight must never become a PR-head relevance policy.
    assert 'git show "${WEBAPP_CI_BASE_SHA}:.github/scripts/classify_webapp_ci_scope.py"' in classifier["run"]
    assert 'python "$classifier"' in classifier["run"]

    frontend = doc["jobs"]["frontend"]
    assert frontend["permissions"] == {"contents": "read", "actions": "read"}
    assert frontend["needs"] == "scope"
    assert frontend["if"] == "${{ always() && (needs.scope.result != 'success' || needs.scope.outputs.relevant == 'true') }}"
    for name, job in doc["jobs"].items():
        assert not job.get("env")
        if name != "frontend":
            assert "permissions" not in job
    front_steps = frontend["steps"]
    checkout = [step for step in front_steps if step.get("uses") == CHECKOUT]
    assert len(checkout) == 1 and checkout[0]["with"] == {"fetch-depth": 0, "persist-credentials": False}
    guard = next(step for step in front_steps if step.get("run") == "npm run verify:node")
    install = next(step for step in front_steps if step.get("run") == "npm ci")
    ordinary_order = []
    for command in ("npm ci", "npm run api:check", "npm test", "npm run build"):
        matches = [step for step in front_steps if step.get("run") == command]
        assert len(matches) == 1 and set(matches[0]) == {"run"}
        ordinary_order.append(front_steps.index(matches[0]))
    assert ordinary_order == sorted(ordinary_order)
    material_test = named(front_steps, MATERIAL_TEST)
    material_check = named(front_steps, MATERIAL_CHECK)
    material_upload = named(front_steps, MATERIAL_UPLOAD)
    assert material_test == {
        "name": MATERIAL_TEST, "working-directory": ".",
        "run": "python -I -B -m unittest discover -s .github/scripts -p test_frontend_candidate_materials.py",
    }
    assert material_check == {
        "name": MATERIAL_CHECK, "working-directory": ".",
        "run": "python -I -B .github/scripts/frontend_candidate_materials.py",
    }
    assert material_upload == {
        "name": MATERIAL_UPLOAD, "if": "${{ always() }}", "uses": UPLOAD,
        "with": {
            "name": "frontend-candidate-materials-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
            "path": "${{ runner.temp }}/frontend-candidate-materials/",
            "if-no-files-found": "error", "retention-days": 14,
        },
    }
    assert (ordinary_order[0] < front_steps.index(material_test) < front_steps.index(material_check)
            < front_steps.index(material_upload) < ordinary_order[1])
    before = named(front_steps, "Bind immutable frontend inputs before the SPA build")
    after = named(front_steps, "Verify privacy and capture the generated SPA for review")
    assert front_steps.index(before) < ordinary_order[-1] < front_steps.index(after)
    for name, filename in ((RECEIVE_TEST, "test_frontend_artifact_receive.py"), (OBSERVE_TEST, "test_observe_vite_distribution.py")):
        step = named(front_steps, name)
        assert step == {"name": name, "working-directory": ".",
                        "run": "python -I -B -m unittest discover -s .github/scripts -p " + filename}
        assert front_steps.index(guard) < front_steps.index(step) < front_steps.index(install)
    receiver = named(front_steps, RECEIVE)
    observer = named(front_steps, OBSERVE)
    assert receiver == {
        "name": RECEIVE, "if": "${{ github.event_name == 'workflow_dispatch' && inputs.receive_frontend_artifact }}",
        "working-directory": ".", "env": {"GH_TOKEN": "${{ github.token }}", "FRONTEND_ARTIFACT_SELECTION": "${{ inputs.frontend_artifact_selection }}"},
        "run": "python -I -B .github/scripts/frontend_artifact_receive.py",
    }
    assert observer == {
        "name": OBSERVE, "if": "${{ github.event_name == 'workflow_dispatch' && inputs.observe_vite_distribution }}",
        "working-directory": ".", "env": {"VITE_SELECTED_INTEGRITY": "${{ inputs.vite_distribution_integrity }}"},
        "run": 'python -I -B .github/scripts/observe_vite_distribution.py --integrity "$VITE_SELECTED_INTEGRITY"',
    }
    assert front_steps.index(named(front_steps, RECEIVE_TEST)) < front_steps.index(receiver) < front_steps.index(install)
    assert front_steps.index(named(front_steps, OBSERVE_TEST)) < front_steps.index(observer) < front_steps.index(install)
    native_test = named(front_steps, NATIVE_TEST)
    assert native_test == {
        "name": NATIVE_TEST, "working-directory": ".",
        "run": "python -I -B -m unittest discover -s tests -p test_jsonschema_rs_observation.py",
    }
    native = named(front_steps, NATIVE_OBSERVE)
    assert native == {
        "name": NATIVE_OBSERVE,
        "if": "${{ github.event_name == 'workflow_dispatch' && inputs.observe_jsonschema_rs }}",
        "working-directory": ".", "env": {"EXPECTED_SOURCE_COMMIT": "${{ inputs.jsonschema_rs_source_commit }}"},
        "run": "python -I -B .github/scripts/observe_jsonschema_rs_wheel.py",
    }
    assert front_steps.index(guard) < front_steps.index(native_test) < front_steps.index(native) < front_steps.index(install)
    for name, flag, prefix, command in (
        ("Preserve frontend receiver results and failures", "receive_frontend_artifact", "frontend-artifact-receive", receiver),
        ("Preserve Vite distribution observation and failures", "observe_vite_distribution", "vite-distribution-observation", observer),
        (NATIVE_UPLOAD, "observe_jsonschema_rs", "jsonschema-rs-observation", native),
    ):
        upload = named(front_steps, name)
        assert upload == {
            "name": name, "if": "${{ always() && github.event_name == 'workflow_dispatch' && inputs." + flag + " }}",
            "uses": UPLOAD, "with": {
                "name": prefix + "-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
                "path": "${{ runner.temp }}/" + prefix + "/", "if-no-files-found": "error", "retention-days": 14,
            },
        }
        assert front_steps.index(command) < front_steps.index(upload) < front_steps.index(install)
    for job_name, job in doc["jobs"].items():
        for step in job["steps"]:
            for key, value in step.get("env", {}).items():
                if any(part in key.upper() for part in ("TOKEN", "SECRET", "AUTH")):
                    assert job_name == "frontend" and step is receiver and key == "GH_TOKEN" and value == "${{ github.token }}"
            if step is not receiver:
                assert "${{ github.token }}" not in step.get("run", "")
    for step in (preflight, receiver, observer, native):
        assert "${{" not in step["run"], "untrusted input must be passed through env, never inserted into shell source"
    assert all("continue-on-error" not in step for step in front_steps)
    assert_e2e_evidence_wiring(doc)


def test_optional_hosted_data_wiring_keeps_read_only_finite_operations_and_existing_gates():
    assert_wiring(document())


@pytest.mark.parametrize("mutation", ["global-token", "observer-token", "write-permission", "missing-preflight", "preflight-on-pr",
                                     "input-in-shell", "missing-path", "changed-default", "pure-tests-optional", "lost-failure-upload",
                                     "retained-credentials", "dropped-unit-tests", "dropped-job"])
def test_wiring_guard_detects_real_privilege_input_scope_and_gate_regressions(mutation):
    doc = copy.deepcopy(document())
    steps = doc["jobs"]["frontend"]["steps"]
    if mutation == "global-token":
        doc["env"] = {"GH_TOKEN": "${{ github.token }}"}
    elif mutation == "observer-token":
        named(steps, OBSERVE)["env"]["GH_TOKEN"] = "${{ github.token }}"
    elif mutation == "write-permission":
        doc["jobs"]["frontend"]["permissions"]["actions"] = "write"
    elif mutation == "missing-preflight":
        scope_steps = doc["jobs"]["scope"]["steps"]
        scope_steps.remove(named(scope_steps, PREFLIGHT))
    elif mutation == "preflight-on-pr":
        named(doc["jobs"]["scope"]["steps"], PREFLIGHT).pop("if")
    elif mutation == "input-in-shell":
        named(steps, OBSERVE)["run"] = "python observer.py --integrity '${{ inputs.vite_distribution_integrity }}'"
    elif mutation == "missing-path":
        doc["on"]["push"]["paths"].remove(REVIEW_PATHS[0])
    elif mutation == "changed-default":
        doc["on"]["workflow_dispatch"]["inputs"]["receive_frontend_artifact"]["default"] = True
    elif mutation == "pure-tests-optional":
        named(steps, RECEIVE_TEST)["if"] = "${{ inputs.receive_frontend_artifact }}"
    elif mutation == "lost-failure-upload":
        named(steps, "Preserve frontend receiver results and failures")["if"] = "${{ success() }}"
    elif mutation == "retained-credentials":
        next(step for step in steps if step.get("uses") == CHECKOUT)["with"]["persist-credentials"] = True
    elif mutation == "dropped-unit-tests":
        steps.remove(next(step for step in steps if step.get("run") == "npm test"))
    else:
        del doc["jobs"]["e2e"]
    with pytest.raises(AssertionError):
        assert_wiring(doc)


@pytest.mark.parametrize("mutation", ["missing-check", "optional-controls", "token", "unbound-source", "success-only-evidence", "missing-path"])
def test_native_observer_wiring_preserves_controls_source_and_failure_evidence(mutation):
    doc = copy.deepcopy(document())
    steps = doc["jobs"]["frontend"]["steps"]
    if mutation == "missing-check":
        steps.remove(named(steps, NATIVE_OBSERVE))
    elif mutation == "optional-controls":
        named(steps, NATIVE_TEST)["if"] = "${{ inputs.observe_jsonschema_rs }}"
    elif mutation == "token":
        named(steps, NATIVE_OBSERVE)["env"]["GH_TOKEN"] = "${{ github.token }}"
    elif mutation == "unbound-source":
        named(steps, NATIVE_OBSERVE)["env"]["EXPECTED_SOURCE_COMMIT"] = ""
    elif mutation == "success-only-evidence":
        named(steps, NATIVE_UPLOAD)["if"] = "${{ success() }}"
    else:
        doc["on"]["push"]["paths"].remove(".github/scripts/observe_jsonschema_rs_wheel.py")
    with pytest.raises(AssertionError):
        assert_wiring(doc)


@pytest.mark.parametrize("mutation", ["missing-check", "optional-control", "success-only-evidence", "before-install"])
def test_candidate_material_wiring_refuses_missing_optional_or_misordered_evidence(mutation):
    doc = copy.deepcopy(document())
    steps = doc["jobs"]["frontend"]["steps"]
    if mutation == "missing-check":
        steps.remove(named(steps, MATERIAL_CHECK))
    elif mutation == "optional-control":
        named(steps, MATERIAL_TEST)["if"] = "${{ inputs.receive_frontend_artifact }}"
    elif mutation == "success-only-evidence":
        named(steps, MATERIAL_UPLOAD)["if"] = "${{ success() }}"
    else:
        check = named(steps, MATERIAL_CHECK)
        steps.remove(check)
        install = next(step for step in steps if step.get("run") == "npm ci")
        steps.insert(steps.index(install), check)
    with pytest.raises(AssertionError):
        assert_wiring(doc)


@pytest.mark.parametrize("owner_path", ["master-reference/release/pipeline.py", "portable/release_contract.py"])
def test_candidate_material_direct_owner_paths_cannot_fall_out_of_hosted_coverage(owner_path):
    doc = copy.deepcopy(document())
    doc["on"]["push"]["paths"].remove(owner_path)
    with pytest.raises(AssertionError):
        assert_wiring(doc)


@pytest.mark.parametrize("owner_path", ["portable/atlas_bundle.py", "portable/windows-x64-requirements.lock",
                                        "portable/third-party-license-fallbacks.json", "portable/third-party-licenses/jsonschema-rs-LICENSE"])
def test_native_observer_direct_owner_paths_cannot_fall_out_of_hosted_coverage(owner_path):
    doc = copy.deepcopy(document())
    doc["on"]["push"]["paths"].remove(owner_path)
    with pytest.raises(AssertionError):
        assert_wiring(doc)


def assert_e2e_evidence_wiring(doc):
    steps = doc["jobs"]["e2e"]["steps"]
    test_steps = [step for step in steps if step.get("run") == "npm run test:e2e"]
    assert len(test_steps) == 1 and test_steps[0] == {"run": "npm run test:e2e"}
    upload = named(steps, "Preserve frontend E2E results and partial evidence")
    assert upload == {
        "name": "Preserve frontend E2E results and partial evidence",
        "if": "${{ always() }}", "uses": UPLOAD,
        "with": {
            "name": "frontend-e2e-results-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
            "path": "webapp/frontend/test-results",
            "if-no-files-found": "error", "retention-days": 14,
        },
    }
    assert steps.index(upload) == steps.index(test_steps[0]) + 1


@pytest.mark.parametrize("mutation", ["missing", "success-only", "before-test", "wrong-root"])
def test_e2e_evidence_retention_guard_rejects_lost_or_misdirected_failure_evidence(mutation):
    doc = copy.deepcopy(document())
    steps = doc["jobs"]["e2e"]["steps"]
    upload = named(steps, "Preserve frontend E2E results and partial evidence")
    if mutation == "missing":
        steps.remove(upload)
    elif mutation == "success-only":
        upload["if"] = "${{ success() }}"
    elif mutation == "before-test":
        steps.remove(upload)
        command = next(step for step in steps if step.get("run") == "npm run test:e2e")
        steps.insert(steps.index(command), upload)
    else:
        upload["with"]["path"] = "webapp/frontend/dist"
    with pytest.raises(AssertionError):
        assert_wiring(doc)
