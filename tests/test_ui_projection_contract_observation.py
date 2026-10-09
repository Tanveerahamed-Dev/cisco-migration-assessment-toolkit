"""Hosted tests for review-only contract material and source-drift refusal."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("contract_observer", ROOT / "webapp/backend/observe_ui_projection_contract.py")
OBSERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVER)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Synthetic fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "core.filemode", "true")
    (root / "owner.py").write_bytes(b"VALUE = 1\n")
    (root / ".gitignore").write_bytes(b".generated/\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Synthetic committed owner")
    return root, git(root, "rev-parse", "HEAD")


def test_actual_git_materials_bind_bytes_tree_and_remain_pure(source):
    root, head = source
    before = OBSERVER.source_identity(root, head)
    assert before["commit"] == head and before["tree"] == git(root, "rev-parse", "HEAD^{tree}")
    assert before["materials"]["owner.py"]["git_blob"] == git(root, "rev-parse", "HEAD:owner.py")
    assert before["materials"]["owner.py"]["sha256"] == hashlib.sha256(b"VALUE = 1\n").hexdigest()
    assert OBSERVER.source_identity(root, head) == before
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("change", ["wrong_head", "worktree", "index", "untracked", "deleted", "assume_unchanged"])
def test_source_drift_never_becomes_review_complete(source, change):
    root, head = source
    if change == "wrong_head":
        head = "0" * 40
    elif change == "untracked":
        (root / "injected.py").write_text("unexpected", encoding="utf-8")
    elif change == "deleted":
        (root / "owner.py").unlink()
    else:
        if change == "assume_unchanged":
            git(root, "update-index", "--assume-unchanged", "owner.py")
        (root / "owner.py").write_bytes(b"VALUE = 2\n")
        if change == "index":
            git(root, "add", "owner.py")
    with pytest.raises(ValueError, match="source|clean|Physical"):
        OBSERVER.source_identity(root, head)


def test_schema_representation_preserves_owner_order_and_requires_actual_owner_hash():
    schema = {"z": "é", "a": [True, None]}
    raw = b'{"z":"\\u00e9","a":[true,null]}\n'
    observed, digest = OBSERVER.schema_bytes(schema, lambda value: hashlib.sha256(raw).hexdigest())
    assert observed == raw and digest == hashlib.sha256(raw).hexdigest()
    assert list(json.loads(observed)) == ["z", "a"]
    with pytest.raises(ValueError, match="representation"):
        OBSERVER.schema_bytes(schema, lambda value: "0" * 64)


def test_review_family_is_closed_fresh_and_bounded(tmp_path, monkeypatch):
    OBSERVER.emit(tmp_path, "openapi.ts", b"review")
    with pytest.raises(FileExistsError):
        OBSERVER.emit(tmp_path, "openapi.ts", b"replace")
    for name in ("../outside", "pins.py", "nested/openapi.ts"):
        with pytest.raises(ValueError, match="Unknown"):
            OBSERVER.emit(tmp_path, name, b"unknown")
    monkeypatch.setattr(OBSERVER, "MAX_FILE", 2)
    with pytest.raises(ValueError, match="oversized"):
        OBSERVER.emit(tmp_path, "view-schema.json", b"too large")
    assert (tmp_path / "openapi.ts").read_bytes() == b"review"


def test_observer_cannot_start_locally(monkeypatch):
    monkeypatch.setattr(OBSERVER.sys, "argv", ["observe_ui_projection_contract.py"])
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="GitHub-hosted"):
        OBSERVER.main()


def test_indirect_material_is_refused(tmp_path):
    import os
    if os.name == "nt":
        pytest.skip("Symlink refusal executes in the mandatory Linux frontend observer controls")
    actual = tmp_path / "actual"
    actual.write_bytes(b"data")
    alias = tmp_path / "alias"
    alias.symlink_to(actual)
    with pytest.raises(ValueError, match="Indirect"):
        OBSERVER.ordinary(alias)


def test_command_output_and_time_are_bounded_during_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(OBSERVER, "MAX_FILE", 1024)
    expected = b"bounded\r\n" if sys.platform == "win32" else b"bounded\n"
    assert OBSERVER.run(tmp_path, [sys.executable, "-c", "print('bounded')"]) == expected
    with pytest.raises(ValueError, match="output exceeds"):
        OBSERVER.run(tmp_path, [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"], timeout=5)
    with pytest.raises(ValueError, match="output exceeds"):
        OBSERVER.run(tmp_path, [sys.executable, "-c", "import sys; sys.stderr.write('x' * 1000000)"], timeout=5)
    with pytest.raises(ValueError, match="time bound"):
        OBSERVER.run(tmp_path, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.2)


@pytest.mark.parametrize("fault", [None, "extra_member", "oversized_member", "source_change"])
def test_main_retains_success_or_structured_failure_without_changing_pins(source, tmp_path, monkeypatch, fault):
    """A controlled owner/generator fixture tests lifecycle, not real schema/generator qualification."""
    root, _ = source
    frontend = root / "webapp/frontend"
    (frontend / ".generated").mkdir(parents=True)
    (frontend / "src/generated").mkdir(parents=True)
    (frontend / "src/generated/openapi.ts").write_bytes(b"committed old types\n")
    exported = {"openapi": "3.1.0", "paths": {}}
    (frontend / ".generated/openapi.json").write_bytes(
        (json.dumps(exported, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())
    git(root, "add", ".")
    git(root, "commit", "-qm", "Synthetic contract inputs")
    head = git(root, "rev-parse", "HEAD")
    output = tmp_path / "runner" / "ui-projection-contract"
    output.parent.mkdir()
    for key, value in {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
                       "GITHUB_JOB": "frontend", "GITHUB_SHA": head, "GITHUB_RUN_ID": "123",
                       "GITHUB_RUN_ATTEMPT": "1", "RUNNER_TEMP": str(output.parent)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(OBSERVER, "__file__", str(root / "webapp/backend/observe_ui_projection_contract.py"))
    monkeypatch.setattr(OBSERVER.sys, "argv", ["observe_ui_projection_contract.py"])
    monkeypatch.setattr(OBSERVER.sys, "path", list(sys.path))
    monkeypatch.setattr(OBSERVER, "version", lambda name: "fixture-version")
    package = types.ModuleType("webapp")
    backend = types.ModuleType("webapp.backend")
    exporter = types.ModuleType("webapp.backend.export_ui_projection_openapi")
    api = types.ModuleType("webapp.backend.ui_projection_api")
    api._VIEW_SCHEMA = {"type": "object"}
    api._LIST_SCHEMA = {"type": "array"}
    api._NATIVE_SCHEMA_HASHES = {"view": "old-view-pin", "list": "old-list-pin"}
    api._native_schema_hash = lambda schema: hashlib.sha256(
        (json.dumps(schema, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()).hexdigest()
    exporter.export_schema = lambda: exported
    backend.ui_projection_api = api
    for name, module in (("webapp", package), ("webapp.backend", backend),
                         ("webapp.backend.ui_projection_api", api),
                         ("webapp.backend.export_ui_projection_openapi", exporter)):
        monkeypatch.setitem(sys.modules, name, module)
    actual_run = OBSERVER.run

    def controlled_run(cwd, args, timeout=60):
        if args[0] == "git":
            return actual_run(cwd, args, timeout)
        if args == ["node", "webapp/frontend/scripts/generate-api-types.mjs", "--review"]:
            (output / "openapi.ts").write_bytes(b"proposed types\n")
            if fault == "extra_member":
                (output / "unexpected.txt").write_bytes(b"unexpected")
            elif fault == "oversized_member":
                (output / "openapi.ts").write_bytes(b"x" * (OBSERVER.MAX_FILE + 1))
            elif fault == "source_change":
                (root / "owner.py").write_bytes(b"changed source\n")
            return b""
        if args == ["npm", "ls", "--all", "--json"]:
            return b'{}'
        return b"fixture-version\n"

    monkeypatch.setattr(OBSERVER, "run", controlled_run)
    monkeypatch.setattr(OBSERVER, "MAX_FILE", 20000)
    result = OBSERVER.main()
    report = json.loads((output / "observation.json").read_bytes())
    assert result == (0 if fault is None else 1)
    assert report["status"] == ("OBSERVED_REVIEW_REQUIRED" if fault is None else "INCOMPLETE_OR_FAILED")
    assert bool(report["errors"]) is (fault is not None)
    assert (frontend / "src/generated/openapi.ts").read_bytes() == b"committed old types\n"
    assert api._NATIVE_SCHEMA_HASHES == {"view": "old-view-pin", "list": "old-list-pin"}
    if fault is None:
        assert report["generated_types_match_committed"] is False
        assert all(not value["matches_declared_pin"] for value in report["native_pins"].values())
        assert set(path.name for path in output.iterdir()) == OBSERVER.OUTPUT_NAMES
        assert json.loads((output / "source-before.json").read_bytes()) == json.loads((output / "source-after.json").read_bytes())
