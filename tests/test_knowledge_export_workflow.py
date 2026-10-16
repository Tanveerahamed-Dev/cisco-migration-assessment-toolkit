"""The hosted knowledge export stays manual, read-only, source-pinned and fail-closed."""
from pathlib import Path
import re

import yaml

from test_release_supply_chain import _RUNNER_JOBS, _RunnerWorkflowLoader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "3401627f6fd69bb838a2c921d7f95c77b2373623"


def document():
    return yaml.load((ROOT / ".github/workflows/knowledge-export.yml").read_text(encoding="utf-8"),
                     Loader=_RunnerWorkflowLoader)


def test_manual_read_only_pinned_hosted_workflow():
    doc = document()
    assert set(doc["on"]) == {"workflow_dispatch"}
    inputs = doc["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"source_commit"}
    assert inputs["source_commit"]["default"] == SOURCE
    assert inputs["source_commit"]["required"] is True
    assert doc["permissions"] == {"contents": "read"}
    assert set(doc["jobs"]) == {"export"} == set(_RUNNER_JOBS["knowledge-export.yml"])
    job = doc["jobs"]["export"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["name"] == _RUNNER_JOBS["knowledge-export.yml"]["export"][0]
    assert not doc["concurrency"]["cancel-in-progress"]
    steps = job["steps"]
    actions = [s["uses"] for s in steps if "uses" in s]
    assert all(re.fullmatch(r"actions/(checkout|setup-python|upload-artifact)@[0-9a-f]{40}", a) for a in actions)
    checkouts = [s["with"] for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert checkouts == [
        {"ref": "${{ github.sha }}", "path": "controller", "persist-credentials": False},
        {"ref": SOURCE, "path": "source", "fetch-depth": 0, "persist-credentials": False},
    ]
    assert "secrets." not in str(doc)
    assert "workflow_dispatch" not in str(job)  # No nested/release dispatch.
    assert steps[0]["env"]["SOURCE_COMMIT"] == "${{ inputs.source_commit }}"
    assert SOURCE in steps[0]["run"]


def test_only_success_publishes_a_downloadable_vault():
    steps = document()["jobs"]["export"]["steps"]
    uploads = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 2
    success, failure = uploads
    assert "if" not in success  # GitHub's default success() gates the importable artifact.
    assert success["with"]["path"] == "${{ runner.temp }}/knowledge-output/"
    assert success["with"]["include-hidden-files"] is True
    assert success["with"]["if-no-files-found"] == "error"
    assert failure["if"] == "failure()"
    assert failure["with"]["path"] == "${{ runner.temp }}/knowledge-diagnostics/"
    assert "BLOCKED" in failure["with"]["name"]
    generation = next(s for s in steps if s.get("name") == "Generate and verify the source-bound knowledge handoff")
    assert "controller/.github/scripts/knowledge_export.py" in generation["run"]
    assert '--source-root "$GITHUB_WORKSPACE/source"' in generation["run"]
    assert "${{ inputs." not in generation["run"]  # Values enter through environment, never shell source.
    controls = next(s for s in steps if s.get("name") == "Refute export admission and workflow boundary defects")
    assert controls["working-directory"] == "controller"
    assert "tests/test_knowledge_export.py tests/test_knowledge_export_workflow.py" in controls["run"]
