from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MASTER_REFERENCE))

from continuity.git_state import observe_git_state  # noqa: E402
from continuity.model import digest_object  # noqa: E402
from continuity.query import query_by_id, query_by_path, query_impact  # noqa: E402
from continuity.validation import validate_completion_receipt, validate_task_envelope  # noqa: E402


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeBundle:
    source_commit: str
    source_tree_digest: str
    manifest: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]


def _bundle(commit: str = "a" * 40, tree: str = "b" * 40) -> FakeBundle:
    file_id = "urn:atlas:file:one"
    symbol_id = "urn:atlas:symbol:one"
    call_id = "urn:atlas:call:one"
    return FakeBundle(
        source_commit=commit,
        source_tree_digest="c" * 64,
        manifest={"release_class": "exact_commit", "head_tree_oid": tree},
        records={
            "files": [{"id": file_id, "path": "src/app.py", "privacy_exposure": "full"}],
            "lines": [
                {
                    "id": "urn:atlas:line:one",
                    "path": "src/app.py",
                    "line_number": 1,
                    "semantic_entity": symbol_id,
                    "owner": file_id,
                }
            ],
            "source_text": [
                {
                    "id": "urn:atlas:source-text:one",
                    "path": "src/app.py",
                    "lines": [{"number": 1, "text": "def app():", "terminator": "\n"}],
                }
            ],
            "symbols": [
                {
                    "id": symbol_id,
                    "path": "src/app.py",
                    "name": "app",
                    "qualified_name": "app",
                    "callees": [call_id],
                    "known_impact_if_changed": [call_id],
                }
            ],
            "calls": [
                {
                    "id": call_id,
                    "path": "src/app.py",
                    "callee": "app",
                    "semantic_entity": symbol_id,
                }
            ],
        },
    )


def _git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Continuity Test",
            "GIT_AUTHOR_EMAIL": "continuity@example.invalid",
            "GIT_COMMITTER_NAME": "Continuity Test",
            "GIT_COMMITTER_EMAIL": "continuity@example.invalid",
            "GIT_AUTHOR_DATE": "2026-08-07T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-08-07T00:00:00Z",
        }
    )
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def _write(root: Path, relative: str, value: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    _git(root, "init", "-q")
    architecture = {
        "components": [
            {"id": "master_reference", "paths": ["master-reference/"]},
            {"id": "engine", "paths": ["src/"]},
        ],
        "exclusions": [{"id": "verification_source", "paths": ["tests/"]}],
    }
    _write(root, "master-reference/governance/architecture.json", json.dumps(architecture))
    _write(root, "master-reference/continuity/item.py", "VALUE = 1\n")
    _write(root, "src/app.py", "def app():\n    return 1\n")
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "baseline")
    commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return commit, tree


def _envelope(commit: str, tree: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "task-continuity",
        "baseline_commit": commit,
        "baseline_tree": tree,
        "objective": "Change the bounded continuity module.",
        "allowed_owners": ["master_reference"],
        "allowed_paths": ["master-reference/continuity/"],
        "allowed_actions": ["read-repository", "edit-repository", "run-tests", "commit-git"],
        "prohibited_actions": [
            "device-write",
            "vault-write",
            "client-data-ingest",
            "public-publish",
        ],
        "required_tests": [{"id": "continuity", "command": "python -m pytest tests/continuity -q"}],
        "authority": {
            "actor_id": "agent-continuity",
            "grant_id": "grant-owner-1",
            "granted_by": "owner-1",
        },
        "expires_at": "2026-08-08T00:00:00Z",
    }


def test_query_by_id_path_line_and_impact_are_source_bound() -> None:
    bundle = _bundle()
    code, by_id = query_by_id(bundle, "urn:atlas:symbol:one")
    assert code == 0
    assert by_id["record"]["qualified_name"] == "app"
    assert by_id["source_commit"] == "a" * 40

    code, by_line = query_by_path(bundle, "src/app.py", 1)
    assert code == 0
    assert by_line["source_lines"][0]["text"] == "def app():"
    assert by_line["line_records"][0]["semantic_entity"] == "urn:atlas:symbol:one"

    code, impact = query_impact(bundle, "urn:atlas:symbol:one")
    assert code == 0
    assert [row["id"] for row in impact["outgoing_references"]] == [
        "urn:atlas:call:one",
    ]
    assert impact["incoming_references"][0]["id"] == "urn:atlas:call:one"
    assert "not runtime" in impact["limits"][0].lower()


def test_missing_queries_abstain_instead_of_inventing() -> None:
    bundle = _bundle()
    code, result = query_by_id(bundle, "urn:atlas:symbol:missing")
    assert code == 3
    assert result["status"] == "abstained"
    assert result["reason"] == "stable_id_not_found_in_exact_bundle"

    code, result = query_by_path(bundle, "src/app.py", 2)
    assert code == 3
    assert result["reason"] == "line_not_present_or_blank_in_exact_bundle"


def test_task_envelope_binds_exact_baseline_authority_scope_and_constraints(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    commit, tree = _repository(repo)
    envelope = _envelope(commit, tree)
    result = validate_task_envelope(envelope, repo, _bundle(commit, tree), now=NOW)
    assert result["status"] == "valid"
    assert result["observed_git"]["changed_paths"] == []
    assert result["protected_actions"] == [
        "client-data-ingest",
        "device-write",
        "public-publish",
        "vault-write",
    ]

    illegal = copy.deepcopy(envelope)
    illegal["allowed_actions"].append("device-write")
    illegal["prohibited_actions"].remove("device-write")
    result = validate_task_envelope(illegal, repo, _bundle(commit, tree), now=NOW)
    assert result["status"] == "invalid"
    assert "protected_action_unwaivable:device-write" in result["errors"]
    assert "protected_action_not_explicitly_prohibited:device-write" in result["errors"]

    _write(repo, "outside.py", "UNAUTHORIZED = True\n")
    _git(repo, "add", "outside.py")
    result = validate_task_envelope(envelope, repo, _bundle(commit, tree), now=NOW)
    assert "changed_path_outside_scope:outside.py" in result["errors"]


def test_expired_or_unknown_owner_envelope_is_invalid(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    commit, tree = _repository(repo)
    envelope = _envelope(commit, tree)
    envelope["expires_at"] = "2026-08-07T11:59:59Z"
    envelope["allowed_owners"] = ["invented_owner"]
    result = validate_task_envelope(envelope, repo, _bundle(commit, tree), now=NOW)
    assert result["status"] == "invalid"
    assert "authority:expired" in result["errors"]
    assert "allowed_owner_unknown:invented_owner" in result["errors"]


def test_completion_receipt_reconciles_exact_commit_tree_diff_owners_and_tests(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline_commit, baseline_tree = _repository(repo)
    envelope = _envelope(baseline_commit, baseline_tree)
    _write(repo, "master-reference/continuity/item.py", "VALUE = 2\n")
    _git(repo, "add", "master-reference/continuity/item.py")
    _git(repo, "commit", "-qm", "completion")
    completion_commit = _git(repo, "rev-parse", "HEAD")
    completion_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    observed = observe_git_state(repo, baseline_commit)
    receipt = {
        "schema_version": "1.0.0",
        "id": "completion-continuity",
        "envelope_digest": digest_object(envelope),
        "baseline_commit": baseline_commit,
        "baseline_tree": baseline_tree,
        "completion_commit": completion_commit,
        "completion_tree": completion_tree,
        "diff_digest": observed["diff_digest"],
        "changed_paths": ["master-reference/continuity/item.py"],
        "changed_owners": ["master_reference"],
        "actions_performed": ["edit-repository", "run-tests", "commit-git"],
        "tests": [
            {
                "id": "continuity",
                "command": "python -m pytest tests/continuity -q",
                "exit_code": 0,
            }
        ],
        "artifacts": [],
        "conflicts": [],
        "exceptions": [],
        "external_actions": [],
        "actor_id": "agent-continuity",
    }
    result = validate_completion_receipt(
        receipt,
        envelope,
        repo,
        _bundle(completion_commit, completion_tree),
        now=NOW,
    )
    assert result["status"] == "valid"
    assert result["observed_git"]["diff_digest"] == receipt["diff_digest"]

    forged = copy.deepcopy(receipt)
    forged["diff_digest"] = "0" * 64
    forged["actions_performed"].append("public-publish")
    result = validate_completion_receipt(
        forged,
        envelope,
        repo,
        _bundle(completion_commit, completion_tree),
        now=NOW,
    )
    assert result["status"] == "invalid"
    assert "receipt:diff_digest_mismatch" in result["errors"]
    assert "protected_action_unwaivable:public-publish" in result["errors"]


def test_completion_requires_clean_exact_compiler_bound_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline_commit, baseline_tree = _repository(repo)
    envelope = _envelope(baseline_commit, baseline_tree)
    observed = observe_git_state(repo, baseline_commit)
    receipt = {
        "schema_version": "1.0.0",
        "id": "completion-no-change",
        "envelope_digest": digest_object(envelope),
        "baseline_commit": baseline_commit,
        "baseline_tree": baseline_tree,
        "completion_commit": baseline_commit,
        "completion_tree": baseline_tree,
        "diff_digest": observed["diff_digest"],
        "changed_paths": [],
        "changed_owners": [],
        "actions_performed": ["run-tests"],
        "tests": [
            {
                "id": "continuity",
                "command": "python -m pytest tests/continuity -q",
                "exit_code": 0,
            }
        ],
        "artifacts": [],
        "conflicts": [],
        "exceptions": [],
        "external_actions": [],
        "actor_id": "agent-continuity",
    }
    _write(repo, "master-reference/continuity/item.py", "VALUE = 99\n")
    result = validate_completion_receipt(
        receipt,
        envelope,
        repo,
        _bundle(baseline_commit, baseline_tree),
        now=NOW,
    )
    assert result["status"] == "invalid"
    assert "completion_worktree:not_clean" in result["errors"]
    assert "receipt:changed_paths_mismatch" in result["errors"]
