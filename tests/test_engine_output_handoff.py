"""Hostile artifacts, runs, checkouts and environments cannot promote an engine-output regeneration handoff.

The hosted receiver (`engine_output_handoff.py receive`) is driven against real temporary Git
checkouts and in-memory ZIP archives through a fake read-only GitHub API and an explicit hosted
receipt-workflow environment; it writes review data outside the checkout and never the checkout.
The hosted producer phases run against the same checkouts with an explicit hosted environment. One
round trip proves the two halves agree.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import warnings
import zipfile
import zlib

import pytest

from cisco_toolkit.distribution_verify import _marker_patterns_for as POLICY

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "engine_output_handoff.py"


def _load(path: Path = SCRIPT, name: str = "engine_output_handoff_under_test"):
    # Loaded by location: sys.path is never extended for the script's directory.
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handoff = _load()
RUN_ID = 41
ARTIFACT_ID = 9001
# Built from fragments so this source never carries the marker it proves is refused.
MARKER_TEXT = "al" + "jazeera" + " campus"
# The policy closure imports tomllib, standard library from 3.11; the hosted ends run 3.12 only.
BOUND_POLICY = pytest.mark.skipif(sys.version_info < (3, 11),
                                  reason="the marker-policy closure imports tomllib (standard library from 3.11)")


@pytest.fixture(autouse=True)
def reviewed_python(monkeypatch):
    # Both hosted ends require the reviewed Python 3.12 profile; this suite runs on every supported version.
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=Handoff Test", "-c", "user.email=handoff-test@example.invalid",
         "-c", "commit.gpgsign=false", "-C", str(root), *args],
        capture_output=True, timeout=120,
    )
    assert proc.returncode == 0, (args, proc.stderr.decode("utf-8", "replace"))
    return proc.stdout.decode("utf-8").strip()


def _blob(root: Path, commit: str, path: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(root), "cat-file", "blob", f"{commit}:{path}"],
                          capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _doc(path: str, version: str) -> bytes:
    return json.dumps({"path": path, "version": version, "rows": [1, 2.5, None]}, indent=1).encode("utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    for path in handoff.OUTPUT_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_doc(path, "committed"))
    (root / "docs").mkdir()
    (root / "docs" / "NOW.md").write_bytes(b"# board\n")
    (root / "engine.py").write_bytes(b"VALUE = 1\n")
    _commit(root, "source")
    return root


@pytest.fixture
def closure_repo(repo):
    """`repo` plus the canonical marker-policy closure, committed from this repository's own Git bytes."""
    for _suffix, path in handoff.MARKER_CLOSURE:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_blob(ROOT, "HEAD", path))
    _commit(repo, "marker policy closure")
    return repo


def _zip(entries: dict, modes: dict | None = None, compression=zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names are written deliberately by some cases
        with zipfile.ZipFile(output, "w", compression=compression) as archive:
            for name, data in (entries.items() if isinstance(entries, dict) else entries):
                info = zipfile.ZipInfo(name)
                info.compress_type = compression
                default = stat.S_IFDIR | 0o755 if name.endswith("/") else stat.S_IFREG | 0o644
                info.external_attr = (modes or {}).get(name, default) << 16
                archive.writestr(info, data)
    return output.getvalue()


def _manifest(root: Path, outputs: dict, source: str, run_id: int = RUN_ID, attempt: int = 1) -> dict:
    return {
        "schema": handoff.MANIFEST_SCHEMA, "source_commit": source,
        "tree": _git(root, "rev-parse", source + "^{tree}"),
        "files": [{"path": p, "sha256": _sha(outputs[p]), "bytes": len(outputs[p])} for p in handoff.OUTPUT_PATHS],
        "changed_from_source": sorted(p for p in handoff.OUTPUT_PATHS if outputs[p] != _blob(root, source, p)),
        "producer": {"workflow": handoff.WORKFLOW, "run_id": str(run_id), "run_attempt": str(attempt),
                     "runner_os": "Linux", "python": "3.12.11", "tz": "UTC"},
        "allow_golden_shrink": False, "status": handoff.STATUS, "release_authority": False,
    }


def _entries(manifest: dict, outputs: dict) -> dict:
    entries = {handoff.MANIFEST_NAME: json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"}
    entries.update({handoff.FILES_PREFIX + path: data for path, data in outputs.items()})
    return entries


def _regenerated() -> dict:
    return {path: _doc(path, "regenerated") for path in handoff.OUTPUT_PATHS}


class FakeAPI:
    """The three read-only REST records and the archive bytes `receive` asks GitHub for."""

    def __init__(self, archive: bytes, source: str, run_id: int = RUN_ID, attempt: int = 1):
        self.calls = []
        self.archive = archive
        self.run = {"id": run_id, "path": handoff.WORKFLOW, "event": "workflow_dispatch", "status": "completed",
                    "conclusion": "success", "head_sha": source, "run_attempt": attempt,
                    "repository": {"full_name": handoff.REPO}, "head_repository": {"full_name": handoff.REPO}}
        steps = ["Set up job", *handoff.REQUIRED_STEPS, "Complete job"]
        self.jobs = {"total_count": 1, "jobs": [{
            "name": handoff.JOB_NAME, "run_id": run_id, "run_attempt": attempt, "head_sha": source,
            "status": "completed", "conclusion": "success", "labels": list(handoff.RUNNER_LABELS),
            "runner_group_name": "GitHub Actions",
            "steps": [{"name": name, "status": "completed", "conclusion": "success"} for name in steps]}]}
        self.artifacts = {"total_count": 1, "artifacts": [{
            "id": ARTIFACT_ID, "name": handoff.artifact_name(source, run_id, attempt), "expired": False,
            "size_in_bytes": len(archive), "digest": "sha256:" + _sha(archive),
            "workflow_run": {"id": run_id, "head_sha": source}}]}

    def json(self, endpoint):
        self.calls.append(endpoint)
        assert endpoint.startswith(f"repos/{handoff.REPO}/actions/runs/")
        if endpoint.endswith("/jobs?per_page=100"):
            return copy.deepcopy(self.jobs)
        if endpoint.endswith("/artifacts?per_page=100"):
            return copy.deepcopy(self.artifacts)
        return copy.deepcopy(self.run)

    def bytes(self, endpoint, maximum):
        self.calls.append(endpoint)
        assert endpoint == f"repos/{handoff.REPO}/actions/artifacts/{ARTIFACT_ID}/zip"
        return self.archive


def _api(root: Path, *, outputs=None, edit_manifest=None, edit_entries=None, source=None, modes=None):
    source = source or _git(root, "rev-parse", "HEAD")
    outputs = _regenerated() if outputs is None else outputs
    manifest = _manifest(root, outputs, source)
    if edit_manifest:
        edit_manifest(manifest)
    entries = _entries(manifest, outputs)
    if edit_entries:
        entries = edit_entries(entries) or entries
    return FakeAPI(_zip(entries, modes), source)


def _runner_temp(root: Path) -> Path:
    temp = root.parent / "runner-temp"
    temp.mkdir(exist_ok=True)
    return temp


def _review_dir(root: Path) -> Path:
    return root.parent / "runner-temp" / handoff.RECEIPT_DIRECTORY


def _review_files(root: Path) -> dict:
    return {path: (_review_dir(root) / "files" / path).read_bytes() for path in handoff.OUTPUT_PATHS}


def _receiver_env(root: Path, **changes) -> dict:
    """The receipt workflow's hosted environment, dispatched at the checkout's HEAD."""
    head = _git(root, "rev-parse", "HEAD")
    env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
           "GITHUB_REPOSITORY": handoff.REPO, "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_WORKFLOW_REF": f"{handoff.REPO}/{handoff.RECEIPT_WORKFLOW}@refs/heads/claude/example",
           "GITHUB_SHA": head, "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1",
           "HANDOFF_RUN_ID": str(RUN_ID), "HANDOFF_SOURCE_COMMIT": head,
           "ALLOW_GOLDEN_SHRINK_INPUT": "false", "VERIFY_IMPORT_INPUT": "false",
           "RUNNER_TEMP": str(_runner_temp(root))}
    env.update(changes)
    return env


def _receive(root: Path, api, *, source_commit=None, allow_golden_shrink=False, verify_import=False,
             policy=POLICY):
    changes = {"ALLOW_GOLDEN_SHRINK_INPUT": "true" if allow_golden_shrink else "false",
               "VERIFY_IMPORT_INPUT": "true" if verify_import else "false"}
    if source_commit is not None:
        changes["HANDOFF_SOURCE_COMMIT"] = source_commit
    lines = []
    result = handoff.receive(root, environ=_receiver_env(root, **changes), api=api, patterns_for=policy,
                             out=lines.append)
    return result, lines


def _on_disk(root: Path) -> dict:
    return {path: (root / path).read_bytes() for path in handoff.OUTPUT_PATHS}


def _committed_docs() -> dict:
    return {path: _doc(path, "committed") for path in handoff.OUTPUT_PATHS}


# --------------------------------------------------------------------------- positive controls


def test_admitted_artifact_is_review_data_and_the_checkout_is_untouched(repo):
    outputs = _regenerated()
    result, lines = _receive(repo, _api(repo, outputs=outputs))
    assert result["status"] == handoff.RECEIPT_STATUS and result["mode"] == "receipt"
    assert result["release_authority"] is False and result["acceptance"] is False
    # Review data only: the closed output set beside the receipt, outside the checkout.
    review = _review_dir(repo)
    assert sorted(p.relative_to(review).as_posix() for p in review.rglob("*") if p.is_file()) == sorted(
        [handoff.RECEIPT_NAME, *(handoff.FILES_PREFIX + path for path in handoff.OUTPUT_PATHS)])
    assert _review_files(repo) == outputs
    assert json.loads((review / handoff.RECEIPT_NAME).read_bytes()) == result
    assert [row["path"] for row in result["outputs"]] == list(handoff.OUTPUT_PATHS)
    assert all(row["identical_to_source"] is False and row["changed_top_level_keys"] == ["version"]
               for row in result["outputs"])
    # The recorded blob names are what `git hash-object` prints for the review copies.
    for row in result["outputs"]:
        copy_path = review / "files" / row["path"]
        assert row["git_blob"] == _git(repo, "hash-object", "--no-filters", "--", str(copy_path))
    assert _on_disk(repo) == _committed_docs()
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert lines[0].startswith("ADMITTED " + handoff.ARTIFACT_PREFIX)


def test_byte_identical_regeneration_is_reported_as_identity(repo):
    committed = _on_disk(repo)
    result, _lines = _receive(repo, _api(repo, outputs=dict(committed)))
    assert all(row["identical_to_source"] for row in result["outputs"])
    assert _git(repo, "status", "--porcelain=v1") == ""


def test_explicit_ancestor_source_is_admitted_when_only_top_level_docs_follow(repo):
    source = _git(repo, "rev-parse", "HEAD")
    api = _api(repo, source=source)
    (repo / "docs" / "NOW.md").write_bytes(b"# board\n\nW31 row\n")
    _commit(repo, "board")
    result, _lines = _receive(repo, api, source_commit=source)
    assert result["source_commit"] == source and result["commits_after_source_touch"] == ["docs/NOW.md"]
    assert result["status"] == handoff.RECEIPT_STATUS and _review_files(repo) == _regenerated()


def test_explicit_golden_shrink_is_admitted_only_with_acknowledgement(repo):
    def shrink(manifest):
        manifest["allow_golden_shrink"] = True
    with pytest.raises(handoff.HandoffRefusal, match="allow_golden_shrink to accept"):
        _receive(repo, _api(repo, edit_manifest=shrink))
    assert not _review_dir(repo).exists()
    result, lines = _receive(repo, _api(repo, edit_manifest=shrink), allow_golden_shrink=True)
    assert result["allow_golden_shrink"] is True and any(line.startswith("WARNING") for line in lines)


def test_admitted_explicit_parent_directory_entries_are_tolerated(repo):
    def directories(entries):
        return {"files/": b"", "files/tests/": b"", **entries}
    result, _lines = _receive(repo, _api(repo, edit_entries=directories))
    assert result["status"] == handoff.RECEIPT_STATUS


# --------------------------------------------------------------------------- hosted-only receipt (concern 1)


@pytest.mark.parametrize("changes", [
    {"GITHUB_ACTIONS": ""}, {"RUNNER_ENVIRONMENT": "self-hosted"}, {"RUNNER_OS": "Windows"},
    {"GITHUB_REPOSITORY": "someone/fork"}, {"GITHUB_EVENT_NAME": "push"}, {"GITHUB_EVENT_NAME": "pull_request"},
    {"GITHUB_WORKFLOW_REF": handoff.REPO + "/.github/workflows/ci.yml@refs/heads/main"},
    {"GITHUB_WORKFLOW_REF": "someone/fork/" + handoff.RECEIPT_WORKFLOW + "@refs/heads/main"},
    {"GITHUB_SHA": "0" * 40}, {"GITHUB_SHA": ""}, {"GITHUB_RUN_ID": ""}, {"GITHUB_RUN_ATTEMPT": "0"},
    {"HANDOFF_RUN_ID": ""}, {"HANDOFF_RUN_ID": "0"}, {"HANDOFF_RUN_ID": "41 --dry-run"},
    {"HANDOFF_RUN_ID": str(2**53)}, {"HANDOFF_SOURCE_COMMIT": "HEAD"}, {"HANDOFF_SOURCE_COMMIT": "A" * 40},
    {"ALLOW_GOLDEN_SHRINK_INPUT": "1"}, {"VERIFY_IMPORT_INPUT": ""}, {"RUNNER_TEMP": ""},
    {"RUNNER_TEMP": "relative/runner-temp"},
])
def test_receiver_refuses_every_environment_but_the_hosted_receipt_workflow(repo, changes):
    api = _api(repo)
    with pytest.raises(handoff.HandoffRefusal):
        handoff.receive(repo, environ=_receiver_env(repo, **changes), api=api, patterns_for=POLICY,
                        out=lambda _line: None)
    assert api.calls == [] and _on_disk(repo) == _committed_docs() and not _review_dir(repo).exists()


def test_receiver_refuses_another_python(repo, monkeypatch):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.13.1"))
    api = _api(repo)
    with pytest.raises(handoff.HandoffRefusal, match="Python 3.12"):
        _receive(repo, api)
    assert api.calls == []


def test_the_command_line_receive_takes_no_inputs_and_refuses_a_workstation(repo, monkeypatch, capsys):
    # No path, run, source or dry-run option exists: inputs arrive only through the workflow environment.
    for key in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS", "GITHUB_REPOSITORY", "GITHUB_EVENT_NAME",
                "GITHUB_WORKFLOW_REF", "HANDOFF_RUN_ID", "HANDOFF_SOURCE_COMMIT"):
        monkeypatch.delenv(key, raising=False)
    assert handoff.main(["receive"], root=repo) == 1
    assert "local execution" in capsys.readouterr().err
    for option in (["--run-id", str(RUN_ID)], ["--dry-run"], ["--source-commit", "0" * 40]):
        with pytest.raises(SystemExit):
            handoff.main(["receive", *option], root=repo)
    assert _on_disk(repo) == _committed_docs()
    assert not hasattr(handoff, "write_outputs") and not hasattr(handoff, "replace_file")


@pytest.mark.parametrize("kind", ["exists", "inside-checkout", "missing-parent"])
def test_receipt_output_is_a_fresh_directory_outside_the_checkout(repo, kind):
    api = _api(repo)
    changes = {}
    if kind == "exists":
        _review_dir(repo).parent.mkdir(exist_ok=True)
        _review_dir(repo).mkdir()
    elif kind == "inside-checkout":
        (repo / "runner-temp").mkdir()
        changes["RUNNER_TEMP"] = str(repo / "runner-temp")
    else:
        changes["RUNNER_TEMP"] = str(repo.parent / "absent-runner-temp")
    with pytest.raises(handoff.HandoffRefusal):
        handoff.receive(repo, environ=_receiver_env(repo, **changes), api=api, patterns_for=POLICY,
                        out=lambda _line: None)
    assert api.calls == []


def _symlink_or_skip(link: Path, target: Path, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symbolic links are unavailable here: {error}")


@pytest.mark.parametrize("kind", ["dangling-output-link", "linked-runner-temp"])
def test_receipt_output_refuses_links(repo, tmp_path, kind):
    api = _api(repo)
    changes = {}
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if kind == "dangling-output-link":
        _runner_temp(repo)
        _symlink_or_skip(_review_dir(repo), elsewhere / "absent", directory=True)
    else:
        linked = tmp_path / "linked-runner-temp"
        _symlink_or_skip(linked, elsewhere, directory=True)
        changes["RUNNER_TEMP"] = str(linked)
    with pytest.raises(handoff.HandoffRefusal):
        handoff.receive(repo, environ=_receiver_env(repo, **changes), api=api, patterns_for=POLICY,
                        out=lambda _line: None)
    assert api.calls == [] and list(elsewhere.iterdir()) == []


def _import(repo: Path, outputs: dict, message: str = "import the admitted outputs") -> str:
    for path, data in outputs.items():
        (repo / path).write_bytes(data)
    return _commit(repo, message)


def test_verify_import_binds_the_import_commit_to_the_admitted_bytes(repo):
    source = _git(repo, "rev-parse", "HEAD")
    outputs = _regenerated()
    api = _api(repo, outputs=outputs, source=source)
    _import(repo, outputs)
    (repo / "docs" / "NOW.md").write_bytes(b"# board\n\nimported\n")
    _commit(repo, "board")
    result, lines = _receive(repo, api, source_commit=source, verify_import=True)
    assert result["status"] == handoff.IMPORT_STATUS and result["mode"] == "verify-import"
    assert [row["at_import"] for row in result["outputs"]] == ["admitted"] * len(handoff.OUTPUT_PATHS)
    assert "import: every output carries the admitted bytes" in lines
    assert result["commits_after_source_touch"] == sorted(["docs/NOW.md", *handoff.OUTPUT_PATHS])
    # Verification emits the receipt only: the bytes are already in the commit it verified.
    assert [p.name for p in _review_dir(repo).iterdir()] == [handoff.RECEIPT_NAME]


def test_verify_import_reports_an_output_held_at_the_source(repo):
    source = _git(repo, "rev-parse", "HEAD")
    outputs = _regenerated()
    api = _api(repo, outputs=outputs, source=source)
    held = handoff.OUTPUT_PATHS[2]
    _import(repo, {path: data for path, data in outputs.items() if path != held})
    result, lines = _receive(repo, api, source_commit=source, verify_import=True)
    assert {row["path"]: row["at_import"] for row in result["outputs"]} == {
        **{path: "admitted" for path in handoff.OUTPUT_PATHS}, held: "source"}
    # A partial import is allowed and is named as partial, never presented as a complete import.
    assert result["status"] == handoff.IMPORT_STATUS
    assert f"import: partial; held at the source: {held}" in lines


@pytest.mark.parametrize("kind", ["foreign-bytes", "engine-change", "source-is-head", "receipt-of-an-import"])
def test_verify_import_refuses_anything_but_admitted_or_source_bytes(repo, kind):
    source = _git(repo, "rev-parse", "HEAD")
    outputs = _regenerated()
    api = _api(repo, outputs=outputs, source=source)
    verify = True
    if kind == "foreign-bytes":
        _import(repo, {**outputs, handoff.OUTPUT_PATHS[1]: _doc(handoff.OUTPUT_PATHS[1], "hand-edited")})
    elif kind == "engine-change":
        (repo / "engine.py").write_bytes(b"VALUE = 8\n")
        _import(repo, outputs)
    elif kind == "receipt-of-an-import":
        _import(repo, outputs)
        verify = False  # an import commit changes outputs, so a plain receipt there is refused
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, api, source_commit=source, verify_import=verify)
    assert not _review_dir(repo).exists()


# --------------------------------------------------------------------------- source binding


def test_dirty_checkout_is_refused_before_any_network_call(repo):
    api = _api(repo)
    (repo / "engine.py").write_bytes(b"VALUE = 2\n")
    with pytest.raises(handoff.HandoffRefusal, match="not clean"):
        _receive(repo, api)
    assert api.calls == []


def test_receiver_must_run_at_the_checkout_root(repo):
    api = _api(repo)
    with pytest.raises(handoff.HandoffRefusal, match="checkout root"):
        handoff.receive(repo / "docs", environ=_receiver_env(repo), api=api, patterns_for=POLICY,
                        out=lambda _line: None)
    assert api.calls == []


@pytest.mark.parametrize("kind", ["manifest-commit", "manifest-tree", "run-commit", "artifact-commit",
                                  "head-advanced", "engine-after-explicit-source", "not-ancestor",
                                  "short-source"])
def test_wrong_source_commit_is_refused(repo, kind):
    source = _git(repo, "rev-parse", "HEAD")
    options = {}
    if kind == "manifest-commit":
        api = _api(repo, edit_manifest=lambda m: m.update(source_commit="0" * 40))
    elif kind == "manifest-tree":
        api = _api(repo, edit_manifest=lambda m: m.update(tree="1" * 40))
    elif kind == "run-commit":
        api = _api(repo)
        api.run["head_sha"] = "2" * 40
    elif kind == "artifact-commit":
        api = _api(repo)
        api.artifacts["artifacts"][0]["workflow_run"]["head_sha"] = "3" * 40
    elif kind == "head-advanced":
        api = _api(repo, source=source)
        (repo / "engine.py").write_bytes(b"VALUE = 3\n")
        _commit(repo, "engine change after the dispatch")
    elif kind == "engine-after-explicit-source":
        api = _api(repo, source=source)
        (repo / "engine.py").write_bytes(b"VALUE = 4\n")
        (repo / "docs" / "NOW.md").write_bytes(b"# board\nnew\n")
        _commit(repo, "engine and board")
        options["source_commit"] = source
    elif kind == "not-ancestor":
        _git(repo, "checkout", "-q", "-b", "side")
        (repo / "docs" / "side.md").write_bytes(b"side\n")
        side = _commit(repo, "side")
        _git(repo, "checkout", "-q", "-")
        api = _api(repo, source=side)
        options["source_commit"] = side
    else:
        api = _api(repo)
        options["source_commit"] = source[:12]
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, api, **options)
    assert _on_disk(repo) == _committed_docs() and not _review_dir(repo).exists()


# --------------------------------------------------------------------------- hidden index state (concern 2)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_producer_refuses_a_hidden_index_edit_before_regeneration(repo, tmp_path, flag):
    _git(repo, "update-index", flag, "engine.py")
    (repo / "engine.py").write_bytes(b"VALUE = 666\n")
    # The precondition that makes this a counterexample: git status cannot see the edit.
    assert _git(repo, "status", "--porcelain=v1") == ""
    with pytest.raises(handoff.HandoffRefusal, match="hides working-tree state"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_producer_refuses_a_hidden_flag_even_over_unchanged_bytes(repo, tmp_path, flag):
    _git(repo, "update-index", flag, "engine.py")
    with pytest.raises(handoff.HandoffRefusal, match="hides working-tree state"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_producer_refuses_a_hidden_index_edit_during_regeneration(repo, produced, flag):
    produced.regenerate(_regenerated())
    _git(repo, "update-index", flag, "engine.py")
    (repo / "engine.py").write_bytes(b"VALUE = 666\n")
    assert sorted(_git(repo, "diff", "--name-only").splitlines()) == sorted(handoff.OUTPUT_PATHS)
    with pytest.raises(handoff.HandoffRefusal, match="hides working-tree state"):
        produced.after()
    assert not (produced.output / handoff.MANIFEST_NAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows checkouts carry no executable bit to compare")
def test_producer_refuses_an_executable_bit_that_git_is_configured_to_ignore(repo, tmp_path):
    _git(repo, "config", "core.fileMode", "false")
    os.chmod(repo / "engine.py", 0o755)
    assert _git(repo, "status", "--porcelain=v1") == ""
    with pytest.raises(handoff.HandoffRefusal, match="executable mode"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))


def test_producer_refuses_untracked_compiled_python_that_could_shadow_the_source(repo, tmp_path):
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "engine.cpython-312.pyc").write_bytes(b"\0" * 16)
    with pytest.raises(handoff.HandoffRefusal, match="compiled Python"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_receiver_refuses_a_hidden_index_edit_before_any_network_call(repo, flag):
    api = _api(repo)
    _git(repo, "update-index", flag, "engine.py")
    (repo / "engine.py").write_bytes(b"VALUE = 666\n")
    assert _git(repo, "status", "--porcelain=v1") == ""
    with pytest.raises(handoff.HandoffRefusal, match="hides working-tree state"):
        _receive(repo, api)
    assert api.calls == []


def test_checkout_binding_reads_every_tracked_byte(repo):
    assert handoff.bind_checkout(repo, _git(repo, "rev-parse", "HEAD")) == len(
        _git(repo, "ls-files").splitlines())
    (repo / handoff.OUTPUT_PATHS[0]).write_bytes(_doc(handoff.OUTPUT_PATHS[0], "regenerated"))
    with pytest.raises(handoff.HandoffRefusal, match="bytes differ"):
        handoff.bind_checkout(repo, _git(repo, "rev-parse", "HEAD"))
    # Only an explicitly regenerated path may differ in bytes.
    handoff.bind_checkout(repo, _git(repo, "rev-parse", "HEAD"), regenerated=handoff.OUTPUT_PATHS)
    (repo / handoff.OUTPUT_PATHS[1]).unlink()
    with pytest.raises(handoff.HandoffRefusal, match="missing"):
        handoff.bind_checkout(repo, _git(repo, "rev-parse", "HEAD"), regenerated=handoff.OUTPUT_PATHS)


# --------------------------------------------------------------------------- archive and member closure


def test_missing_manifest_is_refused(repo):
    def drop(entries):
        del entries[handoff.MANIFEST_NAME]
    with pytest.raises(handoff.HandoffRefusal, match="missing manifest.json"):
        _receive(repo, _api(repo, edit_entries=drop))


def test_missing_output_member_is_refused(repo):
    def drop(entries):
        del entries[handoff.FILES_PREFIX + handoff.OUTPUT_PATHS[0]]
    with pytest.raises(handoff.HandoffRefusal, match="missing " + handoff.FILES_PREFIX):
        _receive(repo, _api(repo, edit_entries=drop))


@pytest.mark.parametrize("extra", ["files/tests/golden/extra.json", "notes.txt", "files/engine.py"])
def test_extra_member_is_refused(repo, extra):
    def add(entries):
        entries[extra] = b"{}"
    with pytest.raises(handoff.HandoffRefusal, match="unexpected " + extra):
        _receive(repo, _api(repo, edit_entries=add))


@pytest.mark.parametrize("name", ["files/../../evil.json", "/etc/evil.json", "files/./x.json", "..",
                                  "files//x.json", "C:/evil.json", "files/CON.json", "files/x.json.",
                                  "files/.hidden.json", "files/\u00e9.json"])
def test_traversal_and_alias_member_names_are_refused(repo, name):
    def add(entries):
        entries[name] = b"{}"
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, _api(repo, edit_entries=add))


def test_backslash_member_names_are_refused():
    # zipfile normalises the platform separator when it READS, so the name rule is pinned directly.
    with pytest.raises(handoff.HandoffRefusal, match="ambiguous"):
        handoff.safe_member_name("files\\tests\\golden\\snapshot.json")


@pytest.mark.parametrize("mode", [stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o644, stat.S_IFCHR | 0o644])
def test_link_and_special_members_are_refused(repo, mode):
    member = handoff.FILES_PREFIX + handoff.OUTPUT_PATHS[1]
    with pytest.raises(handoff.HandoffRefusal, match="link or special"):
        _receive(repo, _api(repo, modes={member: mode}))


@pytest.mark.parametrize("entries", [
    [("files/other/", b"")],
    [("files/", b"payload")],
])
def test_unexpected_or_loaded_directory_members_are_refused(repo, entries):
    def add(existing):
        return dict(entries + list(existing.items()))
    with pytest.raises(handoff.HandoffRefusal, match="directory member"):
        _receive(repo, _api(repo, edit_entries=add))


@pytest.mark.parametrize("alias", ["manifest.json", "Manifest.json", "MANIFEST.JSON"])
def test_duplicate_and_case_aliased_members_are_refused(repo, alias):
    def add(entries):
        return list(entries.items()) + [(alias, entries[handoff.MANIFEST_NAME])]
    with pytest.raises(handoff.HandoffRefusal, match="duplicate or case-aliased"):
        _receive(repo, _api(repo, edit_entries=add))


def test_non_zip_and_truncated_archives_are_refused():
    with pytest.raises(handoff.HandoffRefusal, match="not a ZIP"):
        handoff.zip_members(b"PK" + b"\0" * 64)
    with pytest.raises(handoff.HandoffRefusal, match="size is out of bounds"):
        handoff.zip_members(b"")


def test_crc_mismatch_is_refused():
    archive = bytearray(_zip({"manifest.json": b'{"a": 1}'}, compression=zipfile.ZIP_STORED))
    payload = archive.index(b'{"a": 1}')
    archive[payload + 6] ^= 0x01
    with pytest.raises(handoff.HandoffRefusal, match="CRC"):
        handoff.zip_members(bytes(archive))


# --------------------------------------------------------------------------- raw ZIP stream closure (concern 3)


def _deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def _member(span: bytes, contents: bytes, *, name: str = "manifest.json", method: int = zipfile.ZIP_DEFLATED,
            size: int | None = None, **extra) -> dict:
    return {"name": name, "method": method, "span": span, "crc": zlib.crc32(contents),
            "size": len(contents) if size is None else size, **extra}


def _raw_zip(members: list[dict], *, prefix: bytes = b"", gap: bytes = b"", comment: bytes = b"",
             suffix: bytes = b"") -> bytes:
    """Hand-built archive bytes, so each header field and raw span is exactly what a case states.

    A member is a dict of name, method, span (the raw compressed bytes), crc and size (the declared
    expanded size), optionally flags, local_flags, local_name, local_sizes, extra (central), comment
    (central file comment), disk (central disk number), offset (central header offset) and descriptor.
    """
    body = bytearray(prefix)
    central = bytearray()
    for index, member in enumerate(members):
        flags = member.get("flags", 0)
        crc, size, span = member["crc"], member["size"], member["span"]
        local_name = member.get("local_name", member["name"]).encode("ascii")
        offset = len(body)
        sizes = member.get("local_sizes", (0, 0, 0) if flags & 0x8 else (crc, len(span), size))
        body += struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, member.get("local_flags", flags), member["method"],
                            0, 0x21, *sizes, len(local_name), 0)
        body += local_name + span
        if flags & 0x8:
            body += b"PK\x07\x08" + struct.pack("<3L", *member.get("descriptor", (crc, len(span), size)))
        if index == 0:
            body += gap
        name = member["name"].encode("ascii")
        extra, file_comment = member.get("extra", b""), member.get("comment", b"")
        central += struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 0x031E, 20, flags, member["method"], 0, 0x21,
                               crc, len(span), size, len(name), len(extra), len(file_comment),
                               member.get("disk", 0), 0, 0o100644 << 16, member.get("offset", offset))
        central += name + extra + file_comment
    start = len(body)
    body += central
    body += struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, len(members), len(members), len(central), start,
                        len(comment)) + comment
    return bytes(body) + suffix


BODY = b'{"a": 1}'


def test_raw_span_controls_admit_plain_and_descriptor_members():
    # Positive controls for the hand-built shape, including the data-descriptor layout upload-artifact writes.
    for member in (_member(_deflate(BODY), BODY), _member(_deflate(BODY), BODY, flags=0x8),
                   _member(BODY, BODY, method=zipfile.ZIP_STORED), _member(BODY, BODY, method=zipfile.ZIP_STORED,
                                                                           flags=0x8)):
        assert handoff.zip_members(_raw_zip([member])) == {"manifest.json": BODY}
    pair = [_member(_deflate(BODY), BODY), _member(_deflate(b"{}"), b"{}", name="files/x.json", flags=0x8)]
    assert handoff.zip_members(_raw_zip(pair)) == {"manifest.json": BODY, "files/x.json": b"{}"}


@pytest.mark.parametrize("kind,match", [
    # The reviewed counterexample: a STORED body `ab` declared as one byte with the CRC of `a`.
    ("stored-prefix", "STORED compressed and expanded sizes differ"),
    ("deflate-overexpansion", "actual expansion differs"),
    ("deflate-trailing-bytes", "truncated, trailing or holds another stream"),
    ("deflate-second-stream", "truncated, trailing or holds another stream"),
    ("deflate-unfinished", "truncated, trailing or holds another stream"),
    ("deflate-corrupt", "not one valid raw DEFLATE stream"),
])
def test_member_stream_must_close_exactly_at_its_declared_size(kind, match):
    if kind == "stored-prefix":
        member = {"name": "manifest.json", "method": zipfile.ZIP_STORED, "span": b"ab", "crc": zlib.crc32(b"a"),
                  "size": 1}
    elif kind == "deflate-overexpansion":
        member = _member(_deflate(BODY + b"concealed tail"), BODY)
    elif kind == "deflate-trailing-bytes":
        member = _member(_deflate(BODY) + b"JUNK", BODY)
    elif kind == "deflate-second-stream":
        member = _member(_deflate(BODY) + _deflate(b"more"), BODY)
    elif kind == "deflate-unfinished":
        # One non-final stored DEFLATE block: the right bytes, but the stream never reaches its end.
        member = _member(b"\x00" + struct.pack("<HH", len(BODY), len(BODY) ^ 0xFFFF) + BODY, BODY)
    else:
        member = _member(b"\xff" * 12, BODY)
    with pytest.raises(handoff.HandoffRefusal, match=match):
        handoff.zip_members(_raw_zip([member]))


@pytest.mark.parametrize("kind", ["prefix", "gap", "comment", "suffix", "unsupported-flag", "local-flags",
                                  "descriptor-mismatch", "local-name", "zip64-extra", "malformed-extra"])
def test_archive_layout_must_tile_exactly_with_agreeing_headers(kind):
    first, second = _member(_deflate(BODY), BODY), _member(_deflate(b"{}"), b"{}", name="files/x.json")
    options = {}
    if kind in ("prefix", "gap", "comment", "suffix"):
        options[kind] = b"unexplained bytes"
    elif kind == "unsupported-flag":
        first["flags"] = 0x2
    elif kind == "local-flags":
        first["flags"], first["local_flags"] = 0x800, 0
    elif kind == "descriptor-mismatch":
        first["flags"], first["descriptor"] = 0x8, (zlib.crc32(b"other"), len(first["span"]), len(BODY))
    elif kind == "local-name":
        first["local_name"] = "manifest.jsoN"
    elif kind == "zip64-extra":
        first["extra"] = struct.pack("<2H", 0x0001, 0)
    else:
        first["extra"] = b"\x0a\x00\x10"
    with pytest.raises(handoff.HandoffRefusal):
        handoff.zip_members(_raw_zip([first, second], **options))


# --------------------------------------------------------------------------- ZIP64 end structures (W54 review)


def _end_fields(archive: bytes) -> tuple[int, int, int]:
    """The entry count, central-directory size and central-directory offset of a classic end record."""
    _signature, _disk, _start, _here, count, size, offset, _comment = struct.unpack("<4s4H2LH", archive[-22:])
    return count, size, offset


def _classic_end(count: int, size: int, offset: int) -> bytes:
    return struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, count, count, size, offset, 0)


def _zip64_end(count: int, size: int, offset: int, record_at: int) -> bytes:
    """A 56-byte ZIP64 end-of-central-directory record followed by the 20-byte locator naming it."""
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    return record + struct.pack("<4sLQL", b"PK\x06\x07", 0, record_at, 1)


def _zip64_case(kind: str) -> bytes:
    member = _member(_deflate(BODY), BODY)
    base = _raw_zip([member])
    count, size, offset = _end_fields(base)
    body = base[:-22]
    if kind == "hidden-payload":
        # The reviewed counterexample: the ZIP64 record names a central directory placed after 1000
        # unexplained bytes, while the classic record's arithmetic still covers them.
        hidden = b"ARBITRARY HIDDEN PAYLOAD " * 40
        body = base[:offset] + hidden + base[offset:offset + size]
        tail = _zip64_end(count, size, offset + len(hidden), len(body))
        return body + tail + _classic_end(count, len(body) + len(tail) - offset, offset)
    if kind == "record-without-locator":
        record = _zip64_end(count, size, offset, len(body))[:56]
        return body + record + _classic_end(count, size + len(record), offset)
    if kind == "locator-in-last-extra":
        # A well-formed private extra field whose payload ends in a ZIP64 record and its locator, so
        # both sit exactly where a reader looks: immediately before the classic end record.
        payload = b"\x00" * 8 + _zip64_end(count, size, offset, 0)
        member["extra"] = struct.pack("<2H", 0x9999, len(payload)) + payload
        return _raw_zip([member])
    tail = _zip64_end(count, size, offset, len(body))
    end = {"spliced": (count, size + len(tail), offset),
           "count-sentinel": (0xFFFF, size + len(tail), offset),
           "size-sentinel": (count, 0xFFFFFFFF, offset),
           "offset-sentinel": (count, size + len(tail), 0xFFFFFFFF)}[kind]
    return body + tail + _classic_end(*end)


@pytest.mark.parametrize("kind", ["spliced", "hidden-payload", "count-sentinel", "size-sentinel",
                                  "offset-sentinel", "record-without-locator", "locator-in-last-extra"])
def test_zip64_end_structures_and_sentinels_are_refused(kind):
    # `spliced` and `hidden-payload` were admitted by the reader that checked only the classic
    # end-record arithmetic and the ZIP64 extra field; the others were refused only incidentally.
    with pytest.raises(handoff.HandoffRefusal, match="ZIP64 end"):
        handoff.zip_members(_zip64_case(kind))


@pytest.mark.parametrize("kind,match", [
    ("file-comment", "carries a file comment"),
    ("multi-disk", "ZIP64 sentinel or a multi-disk number"),
    ("sentinel-offset", "ZIP64 sentinel or a multi-disk number"),
    ("trailing-bytes", "unexplained bytes after its records"),
    ("descriptor-local-sentinel", "neither zero nor the central directory's"),
])
def test_central_directory_is_exactly_its_records(kind, match):
    member = _member(_deflate(BODY), BODY)
    if kind == "file-comment":
        member["comment"] = b"concealed"
    elif kind == "multi-disk":
        member["disk"] = 0xFFFF
    elif kind == "sentinel-offset":
        member["offset"] = 0xFFFFFFFF
    elif kind == "descriptor-local-sentinel":
        member["flags"], member["local_sizes"] = 0x8, (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    archive = _raw_zip([member])
    if kind == "trailing-bytes":
        count, size, offset = _end_fields(archive)
        archive = archive[:-22] + b"concealed" + _classic_end(count, size + len(b"concealed"), offset)
    with pytest.raises(handoff.HandoffRefusal, match=match):
        handoff.zip_members(archive)


# --------------------------------------------------------------------------- hashes and manifest


@pytest.mark.parametrize("kind", ["member-bytes", "manifest-size", "manifest-sha"])
def test_hash_and_size_mismatches_are_refused(repo, kind):
    target = handoff.OUTPUT_PATHS[2]

    def edit_manifest(manifest):
        row = next(row for row in manifest["files"] if row["path"] == target)
        if kind == "manifest-size":
            row["bytes"] += 1
        elif kind == "manifest-sha":
            row["sha256"] = "f" * 64

    def edit_entries(entries):
        if kind == "member-bytes":
            entries[handoff.FILES_PREFIX + target] = _doc(target, "tampered")
    with pytest.raises(handoff.HandoffRefusal, match="size or SHA-256"):
        _receive(repo, _api(repo, edit_manifest=edit_manifest, edit_entries=edit_entries))
    assert _on_disk(repo)[target] == _doc(target, "committed") and not _review_dir(repo).exists()


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(extra=True),
    lambda m: m.pop("status"),
    lambda m: m.update(schema="engine_output_handoff/2"),
    lambda m: m.update(status="APPROVED"),
    lambda m: m.update(release_authority=True),
    lambda m: m["files"].reverse(),
    lambda m: m["files"].pop(),
    lambda m: m["files"][0].update(mode="100755"),
    lambda m: m["files"][0].update(sha256="A" * 64),
    lambda m: m["files"][0].update(bytes=True),
    lambda m: m.update(changed_from_source=[]),
    lambda m: m.update(changed_from_source=["tests/golden/other.json"]),
    lambda m: m.update(changed_from_source=[1, "tests/golden/snapshot.json"]),
    lambda m: m.update(changed_from_source=list(reversed(m["changed_from_source"]))),
    lambda m: m.update(allow_golden_shrink="false"),
    lambda m: m["producer"].update(run_id="42"),
    lambda m: m["producer"].update(run_attempt="2"),
    lambda m: m["producer"].update(workflow=".github/workflows/ci.yml"),
    lambda m: m["producer"].update(tz="Europe/Berlin"),
    lambda m: m["producer"].update(python="3.11.9"),
    lambda m: m["producer"].update(runner_os="Windows"),
    lambda m: m["producer"].update(extra=1),
])
def test_malformed_or_promoting_manifest_is_refused(repo, mutation):
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, _api(repo, edit_manifest=mutation))


@pytest.mark.parametrize("raw", [b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": 1e999}', b"\xef\xbb\xbf{}",
                                 b"{} trailing", b"\xff"])
def test_unreadable_manifest_json_is_refused(repo, raw):
    def replace(entries):
        entries[handoff.MANIFEST_NAME] = raw
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, _api(repo, edit_entries=replace))


@pytest.mark.parametrize("kind", ["crlf", "not-json", "array", "empty-object", "bom", "marker"])
def test_output_content_policy_is_enforced(repo, kind):
    target = handoff.OUTPUT_PATHS[1]
    if kind == "crlf":
        data = _doc(target, "regenerated").replace(b"\n", b"\r\n")
    elif kind == "not-json":
        data = b"{not json"
    elif kind == "array":
        data = b"[1, 2]"
    elif kind == "empty-object":
        data = b"{}"
    elif kind == "bom":
        data = b"\xef\xbb\xbf" + _doc(target, "regenerated")
    else:
        data = json.dumps({"site": MARKER_TEXT}).encode("utf-8")
    outputs = {**_regenerated(), target: data}
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, _api(repo, outputs=outputs))
    assert _on_disk(repo)[target] == _doc(target, "committed") and not _review_dir(repo).exists()


# --------------------------------------------------------------------------- run, job and artifact identity


@pytest.mark.parametrize("field,value", [
    ("conclusion", "failure"), ("status", "in_progress"), ("event", "push"), ("event", "pull_request"),
    ("path", ".github/workflows/ci.yml"), ("repository", {"full_name": "someone/fork"}),
    ("head_repository", {"full_name": "someone/fork"}), ("run_attempt", 0), ("id", RUN_ID + 1),
])
def test_run_identity_refusals(repo, field, value):
    api = _api(repo)
    api.run[field] = value
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, api)


@pytest.mark.parametrize("kind", ["two-jobs", "failed-job", "floating-image", "other-runner-group",
                                  "missing-step", "skipped-step", "census", "other-name"])
def test_job_identity_refusals(repo, kind):
    api = _api(repo)
    job = api.jobs["jobs"][0]
    if kind == "two-jobs":
        api.jobs["jobs"].append(copy.deepcopy(job))
        api.jobs["total_count"] = 2
    elif kind == "failed-job":
        job["conclusion"] = "failure"
    elif kind == "floating-image":
        job["labels"] = ["ubuntu-latest"]
    elif kind == "other-runner-group":
        job["runner_group_name"] = "Default"
    elif kind == "missing-step":
        job["steps"] = [step for step in job["steps"] if step["name"] != handoff.REQUIRED_STEPS[4]]
    elif kind == "skipped-step":
        next(step for step in job["steps"] if step["name"] == handoff.REQUIRED_STEPS[5])["conclusion"] = "skipped"
    elif kind == "census":
        api.jobs["total_count"] = 3
    else:
        job["name"] = "Ruff lint"
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, api)


@pytest.mark.parametrize("kind", ["absent", "ambiguous", "expired", "no-digest", "digest-mismatch",
                                  "size-mismatch", "other-run", "oversized", "census"])
def test_artifact_selection_and_download_refusals(repo, kind):
    api = _api(repo)
    item = api.artifacts["artifacts"][0]
    if kind == "absent":
        item["name"] = "frontend-dist-handoff"
    elif kind == "ambiguous":
        api.artifacts["artifacts"].append(dict(item, id=ARTIFACT_ID + 1))
        api.artifacts["total_count"] = 2
    elif kind == "expired":
        item["expired"] = True
    elif kind == "no-digest":
        item["digest"] = None
    elif kind == "digest-mismatch":
        api.archive = api.archive[:-1] + bytes([api.archive[-1] ^ 0x01])
    elif kind == "size-mismatch":
        api.archive = api.archive + b"\0"
    elif kind == "other-run":
        item["workflow_run"]["id"] = RUN_ID + 7
    elif kind == "oversized":
        item["size_in_bytes"] = handoff.MAX_ARCHIVE_BYTES + 1
    else:
        api.artifacts["total_count"] = 101
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, api)
    assert _on_disk(repo) == _committed_docs() and not _review_dir(repo).exists()


def test_artifact_name_is_bound_to_source_run_and_attempt():
    assert handoff.artifact_name("a" * 40, 5, 2) == f"{handoff.ARTIFACT_PREFIX}-{'a' * 40}-5-2"


# --------------------------------------------------------------------------- canonical marker policy (concern 4)


def _foreign_policy_module(path: Path) -> ModuleType:
    """A permissive module claiming the canonical name and the checkout's own policy path."""
    module = ModuleType("cisco_toolkit.distribution_verify")
    module.__file__ = str(path)
    module._marker_patterns_for = lambda name: ()
    module._client_marker_patterns = lambda: ()
    return module


def _plant_cached_code(source: Path) -> Path:
    """Timestamp bytecode beside `source`, stamped with its size and mtime, that returns no patterns."""
    code = compile("def _marker_patterns_for(name):\n    return ()\n", str(source), "exec")
    info = source.stat()
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little")
                      + (int(info.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                      + (info.st_size & 0xFFFFFFFF).to_bytes(4, "little") + marshal.dumps(code))
    return cache


def _flags_marker(policy) -> bool:
    return any(pattern.search(MARKER_TEXT) for pattern in policy("tests/golden/snapshot.json"))


@BOUND_POLICY
def test_bound_policy_executes_admitted_git_bytes_not_a_same_path_or_cached_module(closure_repo, monkeypatch):
    source = closure_repo / "cisco_toolkit" / "distribution_verify.py"
    foreign = _foreign_policy_module(source)
    monkeypatch.setitem(sys.modules, "cisco_toolkit.distribution_verify", foreign)
    _plant_cached_code(source)
    path_identity, path_contents = sys.path, list(sys.path)
    with handoff.bound_marker_policy(closure_repo, _git(closure_repo, "rev-parse", "HEAD")) as policy:
        assert _flags_marker(policy)
        assert Path(policy.__code__.co_filename) == source
        assert policy.__module__.startswith("_engine_handoff_marker_")
    assert sys.modules["cisco_toolkit.distribution_verify"] is foreign
    assert not [name for name in sys.modules if name.startswith("_engine_handoff_marker_")]
    assert sys.path is path_identity and sys.path == path_contents


@BOUND_POLICY
def test_bound_policy_ignores_a_permissive_working_tree_edit(closure_repo):
    (closure_repo / "cisco_toolkit" / "distribution_verify.py").write_text(
        "def _marker_patterns_for(name):\n    return ()\n", encoding="utf-8")
    with handoff.bound_marker_policy(closure_repo, _git(closure_repo, "rev-parse", "HEAD")) as policy:
        assert _flags_marker(policy)


@BOUND_POLICY
@pytest.mark.parametrize("kind,match", [
    ("relative-escape", "escaped the admitted closure"),
    ("absolute-project", "not standard library"),
    ("missing-member", "not one committed entry"),
])
def test_bound_policy_refuses_an_import_outside_its_admitted_closure(closure_repo, kind, match):
    eoldb = closure_repo / "cisco_toolkit" / "eoldb.py"
    if kind == "relative-escape":
        eoldb.write_bytes(eoldb.read_bytes() + b"\nfrom .ssot import reconcile\n")
    elif kind == "absolute-project":
        eoldb.write_bytes(eoldb.read_bytes() + b"\nimport cisco_toolkit.ssot\n")
    else:
        eoldb.unlink()
    commit = _commit(closure_repo, kind)
    with pytest.raises(handoff.HandoffRefusal, match=match):
        with handoff.bound_marker_policy(closure_repo, commit):
            pass
    assert not [name for name in sys.modules if name.startswith("_engine_handoff_marker_")]


@BOUND_POLICY
def test_bound_policy_loads_this_repository_closure_from_git():
    with handoff.bound_marker_policy(ROOT, _git(ROOT, "rev-parse", "HEAD")) as policy:
        assert _flags_marker(policy)
        assert policy("tests/golden/snapshot.json")


@BOUND_POLICY
def test_producer_marker_scan_cannot_be_disarmed_by_a_preloaded_policy(closure_repo, tmp_path, monkeypatch):
    source = closure_repo / "cisco_toolkit" / "distribution_verify.py"
    monkeypatch.setitem(sys.modules, "cisco_toolkit.distribution_verify", _foreign_policy_module(source))
    env, state, output = _hosted(closure_repo), tmp_path / "state", tmp_path / "handoff"
    handoff.phase_before(closure_repo, state, environ=env)
    (closure_repo / handoff.OUTPUT_PATHS[2]).write_bytes(json.dumps({"site": MARKER_TEXT}).encode("utf-8"))
    with pytest.raises(handoff.HandoffRefusal, match="client-marker"):
        handoff.phase_after(closure_repo, state, output, environ=env)
    assert not (output / handoff.MANIFEST_NAME).exists()


@BOUND_POLICY
def test_receiver_marker_scan_cannot_be_disarmed_by_a_preloaded_policy(closure_repo, monkeypatch):
    source = closure_repo / "cisco_toolkit" / "distribution_verify.py"
    monkeypatch.setitem(sys.modules, "cisco_toolkit.distribution_verify", _foreign_policy_module(source))
    outputs = {**_regenerated(), handoff.OUTPUT_PATHS[2]: json.dumps({"site": MARKER_TEXT}).encode("utf-8")}
    with pytest.raises(handoff.HandoffRefusal, match="client-marker"):
        _receive(closure_repo, _api(closure_repo, outputs=outputs), policy=None)
    assert not _review_dir(closure_repo).exists()


@BOUND_POLICY
def test_receiver_admits_through_the_bound_policy(closure_repo):
    result, _lines = _receive(closure_repo, _api(closure_repo), policy=None)
    assert result["status"] == handoff.RECEIPT_STATUS and _review_files(closure_repo) == _regenerated()


def test_marker_closure_matches_the_reviewed_frontend_receiver():
    frontend = _load(ROOT / ".github" / "scripts" / "frontend_artifact_receive.py", "frontend_receiver_closure")
    assert handoff.MARKER_CLOSURE == frontend.MARKER_CLOSURE
    assert handoff.MARKER_IMPORTS == frontend.MARKER_IMPORTS


def test_marker_closure_tables_are_exactly_the_closure_sources_imports():
    members = {path: suffix for suffix, path in handoff.MARKER_CLOSURE}
    for path, suffix in members.items():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        relative: dict[str, frozenset] = {}
        absolute = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.level == 1 and node.module, (path, ast.dump(node))
                relative[node.module] = frozenset(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                absolute.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                absolute.update(alias.name.split(".")[0] for alias in node.names)
        assert relative == handoff.MARKER_IMPORTS[suffix], path
        assert set(relative) <= {other for other in members.values() if other}, path
        # Only the guarded tomllib/tomli pair can fall outside this interpreter's standard library
        # (tomllib joined it in 3.11; tomli is the 3.10 fallback the bound loader refuses).
        outside = absolute - set(sys.stdlib_module_names)
        assert outside <= {"tomllib", "tomli"}, (path, outside)


# --------------------------------------------------------------------------- hosted producer phases


def _hosted(root: Path, **changes) -> dict:
    head = _git(root, "rev-parse", "HEAD")
    env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux", "TZ": "UTC",
           "EXPECTED_SOURCE_COMMIT": head, "GITHUB_SHA": head, "GITHUB_RUN_ID": str(RUN_ID),
           "GITHUB_RUN_ATTEMPT": "1", "ALLOW_GOLDEN_SHRINK_INPUT": "false"}
    env.update(changes)
    return env


@pytest.fixture
def produced(repo, tmp_path, monkeypatch):
    # The producer requires the reviewed Python 3.12 profile; this suite runs on every supported version.
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    env = _hosted(repo)
    state, output = tmp_path / "state", tmp_path / "handoff"

    def regenerate(outputs):
        for path, data in outputs.items():
            (repo / path).write_bytes(data)

    def after(**changes):
        return handoff.phase_after(repo, state, output, environ={**env, **changes}, patterns_for=POLICY)

    handoff.phase_before(repo, state, environ=env)
    return SimpleNamespace(env=env, state=state, output=output, regenerate=regenerate, after=after)


def _archive_directory(directory: Path) -> bytes:
    entries = {path.relative_to(directory).as_posix(): path.read_bytes()
               for path in sorted(directory.rglob("*")) if path.is_file()}
    return _zip(entries)


def test_producer_round_trip_is_admitted_by_the_receiver(repo, produced):
    outputs = {**_regenerated(), handoff.OUTPUT_PATHS[0]: _doc(handoff.OUTPUT_PATHS[0], "committed")}
    produced.regenerate(outputs)
    manifest = produced.after()
    assert manifest["changed_from_source"] == list(handoff.OUTPUT_PATHS[1:])
    assert manifest["status"] == handoff.STATUS and manifest["release_authority"] is False
    archive = _archive_directory(produced.output)
    assert set(handoff.zip_members(archive)) == handoff.EXPECTED_MEMBERS
    for path in handoff.OUTPUT_PATHS:  # the receiver needs the clean source checkout back
        (repo / path).write_bytes(_blob(repo, "HEAD", path))
    result, _lines = _receive(repo, FakeAPI(archive, manifest["source_commit"]))
    assert result["status"] == handoff.RECEIPT_STATUS and _review_files(repo) == outputs
    assert [row["identical_to_source"] for row in result["outputs"]] == [True, False, False]


def test_producer_reports_byte_identical_regeneration(repo, produced):
    manifest = produced.after()
    assert manifest["changed_from_source"] == []
    assert [row["sha256"] for row in manifest["files"]] == [_sha(_blob(repo, "HEAD", p)) for p in handoff.OUTPUT_PATHS]


@pytest.mark.parametrize("kind", ["tracked-outside-set", "new-untracked", "staged", "output-deleted",
                                  "output-crlf", "head-moved", "marker"])
def test_producer_refuses_effects_outside_the_closed_set(repo, produced, kind):
    produced.regenerate(_regenerated())
    if kind == "tracked-outside-set":
        (repo / "engine.py").write_bytes(b"VALUE = 9\n")
    elif kind == "new-untracked":
        (repo / "tests" / "golden" / "extra.json").write_bytes(b"{}")
    elif kind == "staged":
        _git(repo, "add", handoff.OUTPUT_PATHS[0])
    elif kind == "output-deleted":
        (repo / handoff.OUTPUT_PATHS[1]).unlink()
    elif kind == "output-crlf":
        (repo / handoff.OUTPUT_PATHS[1]).write_bytes(_doc(handoff.OUTPUT_PATHS[1], "x").replace(b"\n", b"\r\n"))
    elif kind == "head-moved":
        _commit(repo, "moved during regeneration")
    else:
        (repo / handoff.OUTPUT_PATHS[2]).write_bytes(json.dumps({"site": "al" + "jazeera"}).encode("utf-8"))
    with pytest.raises(handoff.HandoffRefusal):
        produced.after()
    assert not (produced.output / handoff.MANIFEST_NAME).exists()


def test_producer_refuses_a_removed_untracked_file(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    (repo / "build.log").write_bytes(b"installer residue\n")
    env, state = _hosted(repo), tmp_path / "state"
    handoff.phase_before(repo, state, environ=env)
    (repo / "build.log").unlink()
    with pytest.raises(handoff.HandoffRefusal, match="untracked file set"):
        handoff.phase_after(repo, state, tmp_path / "handoff", environ=env, patterns_for=POLICY)


@pytest.mark.parametrize("changes", [
    {"GITHUB_ACTIONS": ""}, {"RUNNER_ENVIRONMENT": "self-managed"}, {"RUNNER_OS": "Windows"}, {"TZ": "Europe/Berlin"},
    {"TZ": ""}, {"EXPECTED_SOURCE_COMMIT": "HEAD"}, {"GITHUB_SHA": "0" * 40}, {"GITHUB_RUN_ID": ""},
    {"GITHUB_RUN_ATTEMPT": "0"},
])
def test_producer_environment_refusals(repo, tmp_path, monkeypatch, changes):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    with pytest.raises(handoff.HandoffRefusal):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo, **changes))
    assert not (tmp_path / "state").exists()


def test_producer_refuses_another_python(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.13.1"))
    with pytest.raises(handoff.HandoffRefusal, match="Python 3.12"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))


@pytest.mark.parametrize("kind", ["dirty", "inside-checkout", "reused-state", "head-not-expected"])
def test_producer_before_refuses_an_unbound_source(repo, tmp_path, monkeypatch, kind):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    env, state = _hosted(repo), tmp_path / "state"
    if kind == "dirty":
        (repo / handoff.OUTPUT_PATHS[0]).write_bytes(b'{"edited": true}')
    elif kind == "inside-checkout":
        state = repo / "state"
    elif kind == "reused-state":
        state.mkdir()
    else:
        (repo / "engine.py").write_bytes(b"VALUE = 5\n")
        _commit(repo, "not the dispatched commit")
    with pytest.raises(handoff.HandoffRefusal):
        handoff.phase_before(repo, state, environ=env)


@pytest.mark.parametrize("kind", ["reused-output", "output-in-checkout", "extra-state-file", "shrink-text"])
def test_producer_after_refuses_misplaced_or_reused_directories(repo, produced, kind):
    changes = {}
    if kind == "reused-output":
        produced.output.mkdir()
    elif kind == "output-in-checkout":
        produced.output = repo / "handoff"
    elif kind == "extra-state-file":
        (produced.state / "notes.json").write_bytes(b"{}")
    else:
        changes["ALLOW_GOLDEN_SHRINK_INPUT"] = "1"
    with pytest.raises(handoff.HandoffRefusal):
        handoff.phase_after(repo, produced.state, produced.output, environ={**produced.env, **changes},
                            patterns_for=POLICY)


def test_producer_records_the_explicit_shrink_input(repo, produced):
    manifest = produced.after(ALLOW_GOLDEN_SHRINK_INPUT="true")
    assert manifest["allow_golden_shrink"] is True
