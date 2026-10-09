"""Hostile artifacts, runs and checkouts cannot promote an engine-output regeneration handoff.

The receiver (`engine_output_handoff.py receive`) is driven against real temporary Git checkouts and
in-memory ZIP archives through a fake read-only GitHub API; the hosted producer phases run against
the same checkouts with an explicit hosted environment. One round trip proves the two halves agree.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import py_compile
import stat
import subprocess
import sys
from types import SimpleNamespace
import warnings
import zipfile

import pytest

from cisco_toolkit.distribution_verify import _marker_patterns_for as POLICY

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "engine_output_handoff.py"


def _load():
    # Loaded by location: sys.path is never extended for the script's directory.
    spec = importlib.util.spec_from_file_location("engine_output_handoff_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handoff = _load()
RUN_ID = 41
ARTIFACT_ID = 9001


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
        "source_inputs": {
            path: {"mode": _git(root, "ls-tree", source, "--", path).split()[0],
                   "blob": _git(root, "rev-parse", source + ":" + path),
                   "bytes": len(_blob(root, source, path)), "sha256": _sha(_blob(root, source, path))}
            for path in _git(root, "ls-tree", "-r", "--name-only", source).splitlines()
            if path not in handoff.OUTPUT_PATHS
        },
        "installer_inputs": {},
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


def _receive(root: Path, api, **options):
    lines = []
    result = handoff.receive(root, RUN_ID, api=api, patterns_for=POLICY, out=lines.append, **options)
    return result, lines


def _on_disk(root: Path) -> dict:
    return {path: (root / path).read_bytes() for path in handoff.OUTPUT_PATHS}


# --------------------------------------------------------------------------- positive controls


def test_admitted_artifact_writes_exactly_the_closed_output_set(repo):
    outputs = _regenerated()
    result, lines = _receive(repo, _api(repo, outputs=outputs))
    assert result["written"] is True and _on_disk(repo) == outputs
    assert [row["path"] for row in result["outputs"]] == list(handoff.OUTPUT_PATHS)
    assert all(row["identical_to_head"] is False and row["changed_top_level_keys"] == ["version"]
               for row in result["outputs"])
    assert sorted(_git(repo, "diff", "--name-only").splitlines()) == sorted(handoff.OUTPUT_PATHS)
    assert _git(repo, "ls-files", "--others") == ""
    assert lines[0].startswith("ADMITTED " + handoff.ARTIFACT_PREFIX)


def test_byte_identical_regeneration_is_reported_as_identity(repo):
    committed = _on_disk(repo)
    result, _lines = _receive(repo, _api(repo, outputs=dict(committed)))
    assert all(row["identical_to_head"] for row in result["outputs"])
    assert _git(repo, "status", "--porcelain=v1") == ""


def test_dry_run_verifies_without_writing(repo):
    before = _on_disk(repo)
    result, lines = _receive(repo, _api(repo), dry_run=True)
    assert result["written"] is False and _on_disk(repo) == before
    assert lines[-1] == "dry run: nothing written"


def test_explicit_ancestor_source_is_admitted_when_only_top_level_docs_follow(repo):
    source = _git(repo, "rev-parse", "HEAD")
    api = _api(repo, source=source)
    (repo / "docs" / "NOW.md").write_bytes(b"# board\n\nW31 row\n")
    _commit(repo, "board")
    result, _lines = _receive(repo, api, source_commit=source)
    assert result["source_commit"] == source and result["commits_after_source_touch"] == ["docs/NOW.md"]
    assert result["written"] is True


def test_explicit_golden_shrink_is_admitted_only_with_acknowledgement(repo):
    def shrink(manifest):
        manifest["allow_golden_shrink"] = True
    with pytest.raises(handoff.HandoffRefusal, match="allow-golden-shrink"):
        _receive(repo, _api(repo, edit_manifest=shrink))
    result, lines = _receive(repo, _api(repo, edit_manifest=shrink), allow_golden_shrink=True)
    assert result["allow_golden_shrink"] is True and any(line.startswith("WARNING") for line in lines)


def test_admitted_explicit_parent_directory_entries_are_tolerated(repo):
    def directories(entries):
        return {"files/": b"", "files/tests/": b"", **entries}
    result, _lines = _receive(repo, _api(repo, edit_entries=directories))
    assert result["written"] is True


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
        handoff.receive(repo / "docs", RUN_ID, api=api, patterns_for=POLICY, out=lambda _line: None)
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
    assert _on_disk(repo) == {path: _doc(path, "committed") for path in handoff.OUTPUT_PATHS}


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
    assert _on_disk(repo)[target] == _doc(target, "committed")


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(extra=True),
    lambda m: m.pop("status"),
    lambda m: m.update(schema="engine_output_handoff/1"),
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
    lambda m: m["source_inputs"].pop("engine.py"),
    lambda m: m["source_inputs"]["engine.py"].update(bytes=True),
    lambda m: m["source_inputs"]["engine.py"].update(sha256="0" * 64),
    lambda m: m["source_inputs"]["engine.py"].update(extra=True),
    lambda m: m["installer_inputs"].update({"untracked.py": {"mode": 420, "bytes": 1, "sha256": "0" * 64}}),
    lambda m: m["installer_inputs"].update({handoff.INSTALLER_ROOT + "PKG-INFO":
                                         {"mode": 493, "bytes": 1, "sha256": "0" * 64}}),
    lambda m: m["installer_inputs"].update({handoff.INSTALLER_ROOT + "PKG-INFO":
                                         {"mode": 420, "bytes": True, "sha256": "0" * 64}}),
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
        # Built from fragments so this source never carries the marker it proves is refused.
        data = json.dumps({"site": "al" + "jazeera" + " campus"}).encode("utf-8")
    outputs = {**_regenerated(), target: data}
    with pytest.raises(handoff.HandoffRefusal):
        _receive(repo, _api(repo, outputs=outputs))
    assert _on_disk(repo)[target] == _doc(target, "committed")


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
    assert _on_disk(repo) == {path: _doc(path, "committed") for path in handoff.OUTPUT_PATHS}


def test_artifact_name_is_bound_to_source_run_and_attempt():
    assert handoff.artifact_name("a" * 40, 5, 2) == f"{handoff.ARTIFACT_PREFIX}-{'a' * 40}-5-2"


# --------------------------------------------------------------------------- local writes


def _symlink_or_skip(link: Path, target: Path, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symbolic links are unavailable here: {error}")


def test_write_refuses_a_linked_target(repo, tmp_path):
    target = repo / handoff.OUTPUT_PATHS[0]
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    target.unlink()
    _symlink_or_skip(target, outside)
    with pytest.raises(handoff.HandoffRefusal, match="ordinary"):
        handoff.write_outputs(repo, _regenerated())
    assert outside.read_bytes() == b"{}"


def test_write_refuses_a_linked_parent_directory(repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "golden").mkdir(parents=True)
    for name in ("sheet_schema.json", "snapshot.json"):
        (elsewhere / "golden" / name).write_bytes(b"{}")
    real = repo / "tests" / "golden"
    for child in real.iterdir():
        child.unlink()
    real.rmdir()
    _symlink_or_skip(real, elsewhere / "golden", directory=True)
    with pytest.raises(handoff.HandoffRefusal, match="ordinary directory"):
        handoff.write_outputs(repo, _regenerated())
    assert (elsewhere / "golden" / "snapshot.json").read_bytes() == b"{}"


def test_write_refuses_a_hard_linked_target(repo, tmp_path):
    target = repo / handoff.OUTPUT_PATHS[2]
    try:
        os.link(target, tmp_path / "alias.json")
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"hard links are unavailable here: {error}")
    with pytest.raises(handoff.HandoffRefusal, match="singly linked"):
        handoff.write_outputs(repo, _regenerated())


# --------------------------------------------------------------------------- canonical marker policy


def test_marker_policy_loads_from_this_checkout_and_restores_sys_path():
    identity, contents = sys.path, list(sys.path)
    policy = handoff.marker_patterns_for(ROOT)
    assert sys.path is identity and sys.path == contents
    assert policy.__name__ == POLICY.__name__ == "_marker_patterns_for"
    assert (Path(policy.__code__.co_filename).resolve()
            == (ROOT / "cisco_toolkit" / "distribution_verify.py").resolve())
    assert policy("tests/golden/snapshot.json")


def test_marker_policy_refuses_another_checkouts_owner(tmp_path):
    # The canonical owner is already imported from this repository, so a foreign root cannot supply it.
    identity, contents = sys.path, list(sys.path)
    with pytest.raises(handoff.HandoffRefusal, match="git rev-parse failed"):
        handoff.marker_patterns_for(tmp_path)
    assert sys.path is identity and sys.path == contents


def test_marker_policy_ignores_a_cached_same_path_impostor(monkeypatch):
    name = "cisco_toolkit.distribution_verify"
    fake = SimpleNamespace(__file__=str(ROOT / "cisco_toolkit" / "distribution_verify.py"),
                           _marker_patterns_for=lambda _path: ())
    monkeypatch.setitem(sys.modules, name, fake)
    before = {key for key in sys.modules if key.startswith("_atlas_engine_marker_")}
    path_identity, path_contents = sys.path, list(sys.path)
    policy = handoff.marker_patterns_for(ROOT)
    assert len(policy(handoff.OUTPUT_PATHS[0])) == 12
    assert any(pattern.search("al" + "jazeera") for pattern in policy(handoff.OUTPUT_PATHS[0]))
    assert sys.modules[name] is fake
    assert sys.path is path_identity and sys.path == path_contents
    assert {key for key in sys.modules if key.startswith("_atlas_engine_marker_")} == before


def _policy_checkout(repo):
    for _suffix, path in handoff.MARKER_CLOSURE:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    _commit(repo, "admitted marker sources")


def test_marker_policy_uses_admitted_bytes_instead_of_bytecode(repo, tmp_path):
    _policy_checkout(repo)
    real = repo / "cisco_toolkit" / "distribution_verify.py"
    poison = tmp_path / "poison.py"
    poison.write_text("def _marker_patterns_for(name): return ()\n", encoding="utf-8")
    cache = Path(importlib.util.cache_from_source(str(real)))
    cache.parent.mkdir()
    py_compile.compile(str(poison), cfile=str(cache), dfile=str(real), doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    # The hostile cache is usable by the ordinary loader; merely creating an
    # irrelevant filename would not establish this negative control.
    spec = importlib.util.spec_from_file_location("marker_cache_positive_control", real)
    assert spec and spec.loader
    ordinary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ordinary)
    assert ordinary._marker_patterns_for(handoff.OUTPUT_PATHS[0]) == ()
    policy = handoff.marker_patterns_for(repo)
    assert any(pattern.search("al" + "jazeera") for pattern in policy(handoff.OUTPUT_PATHS[0]))
    assert Path(policy.__code__.co_filename) == repo / "cisco_toolkit" / "distribution_verify.py"


def test_marker_policy_refuses_physical_code_drift(repo):
    _policy_checkout(repo)
    (repo / "cisco_toolkit" / "distribution_verify.py").write_bytes(
        b"def _marker_patterns_for(name): return ()\n"
    )
    with pytest.raises(handoff.HandoffRefusal, match="closure bytes differ"):
        handoff.marker_patterns_for(repo)


def test_marker_policy_cannot_import_an_unadmitted_project_sibling(repo):
    _policy_checkout(repo)
    target = repo / "cisco_toolkit" / "distribution_verify.py"
    target.write_bytes(target.read_bytes() + b"\nfrom .surprise import marker_override\n")
    (repo / "cisco_toolkit" / "surprise.py").write_bytes(b"marker_override = ()\n")
    _commit(repo, "unadmitted policy import")
    with pytest.raises(handoff.HandoffRefusal, match="relative import escaped"):
        handoff.marker_patterns_for(repo)


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
    # The receiver requires the reviewed Python 3.12 profile; this suite runs on every supported version.
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
    assert result["written"] is True and _on_disk(repo) == outputs


def test_producer_reports_byte_identical_regeneration(repo, produced):
    manifest = produced.after()
    assert manifest["changed_from_source"] == []
    assert [row["sha256"] for row in manifest["files"]] == [_sha(_blob(repo, "HEAD", p)) for p in handoff.OUTPUT_PATHS]


@pytest.mark.parametrize("changed", [{"GITHUB_RUN_ID": "42"}, {"GITHUB_RUN_ATTEMPT": "2"}])
def test_producer_cannot_relabel_another_same_source_run_or_attempt(repo, produced, changed):
    produced.regenerate(_regenerated())
    with pytest.raises(handoff.HandoffRefusal, match="run, attempt or interpreter changed"):
        handoff.phase_after(repo, produced.state, produced.output, environ=_hosted(repo, **changed), patterns_for=POLICY)
    assert not produced.output.exists()


def test_producer_cannot_hide_an_output_mode_change_beside_expected_byte_changes(repo, produced):
    if os.name == "nt":
        pytest.skip("executable mode is a hosted Linux producer property")
    produced.regenerate(_regenerated())
    target = repo / handoff.OUTPUT_PATHS[0]
    target.chmod(0o755)
    assert target.read_bytes() != _blob(repo, "HEAD", handoff.OUTPUT_PATHS[0])
    with pytest.raises(handoff.HandoffRefusal, match="output executable mode"):
        produced.after()
    assert not produced.output.exists()


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
    metadata = repo / handoff.INSTALLER_ROOT / "PKG-INFO"
    metadata.parent.mkdir()
    metadata.write_bytes(b"Metadata-Version: 2.4\nName: cisco-migration-assessment-toolkit\n")
    env, state = _hosted(repo), tmp_path / "state"
    handoff.phase_before(repo, state, environ=env)
    metadata.unlink()
    with pytest.raises(handoff.HandoffRefusal, match="untracked file set"):
        handoff.phase_after(repo, state, tmp_path / "handoff", environ=env, patterns_for=POLICY)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_producer_refuses_hidden_index_flags_before_generation(repo, tmp_path, monkeypatch, flag):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    _git(repo, "update-index", flag, "engine.py")
    (repo / "engine.py").write_bytes(b"VALUE = 2\n")
    assert _git(repo, "diff", "--name-only", "HEAD") == ""
    with pytest.raises(handoff.HandoffRefusal, match="hidden or non-cached flags"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_producer_refuses_hidden_source_after_generation(repo, produced, flag):
    produced.regenerate(_regenerated())
    _git(repo, "update-index", flag, "engine.py")
    (repo / "engine.py").write_bytes(b"VALUE = 2\n")
    assert "engine.py" not in _git(repo, "diff", "--name-only", "HEAD").splitlines()
    with pytest.raises(handoff.HandoffRefusal, match="hidden or non-cached flags"):
        produced.after()
    assert not produced.output.exists()


def test_physical_source_ledger_refuses_same_size_same_mtime_drift(repo, produced):
    produced.regenerate(_regenerated())
    source = repo / "engine.py"
    before = source.stat()
    source.write_bytes(b"VALUE = 2\n")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.read_bytes() != _blob(repo, "HEAD", "engine.py")
    with pytest.raises(handoff.HandoffRefusal, match="physical source bytes"):
        handoff.source_inputs(repo, _git(repo, "rev-parse", "HEAD"))


def test_source_ledger_has_every_non_output_file(repo, produced):
    before = json.loads((produced.state / "source-before.json").read_bytes())
    assert set(before["inputs"]) == {"engine.py", "docs/NOW.md"}
    for path in before["inputs"]:
        raw = _blob(repo, "HEAD", path)
        assert before["inputs"][path] == {
            "mode": "100644", "blob": _git(repo, "rev-parse", "HEAD:" + path),
            "bytes": len(raw), "sha256": _sha(raw),
        }
    produced.regenerate(_regenerated())
    manifest = produced.after()
    assert manifest["source_inputs"] == before["inputs"]
    assert manifest["installer_inputs"] == {}


@pytest.mark.parametrize("path", ["build.log", "shadow.py", "cisco_toolkit/__pycache__/shadow.pyc",
                                  "shadow.pth", "shadow.pyd", "shadow.dll",
                                  handoff.INSTALLER_ROOT + "unexpected.txt",
                                  handoff.INSTALLER_ROOT + "nested/PKG-INFO"])
def test_producer_refuses_unadmitted_preexisting_inputs(repo, tmp_path, monkeypatch, path):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"unadmitted")
    with pytest.raises(handoff.HandoffRefusal, match="unadmitted untracked"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))
    assert not (tmp_path / "state").exists()


def test_installer_metadata_is_bound_as_data_not_git_source(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    path = handoff.INSTALLER_ROOT + "PKG-INFO"
    target = repo / path
    target.parent.mkdir()
    raw = b"Metadata-Version: 2.4\nName: cisco-migration-assessment-toolkit\n"
    target.write_bytes(raw)
    state = tmp_path / "state"
    record = handoff.phase_before(repo, state, environ=_hosted(repo))
    assert path not in record["inputs"] and record["untracked"] == [path]
    assert record["installer_inputs"][path]["bytes"] == len(raw)
    assert record["installer_inputs"][path]["sha256"] == _sha(raw)
    target.write_bytes(raw + b"changed")
    with pytest.raises(handoff.HandoffRefusal, match="installer metadata bytes"):
        handoff.phase_after(repo, state, tmp_path / "handoff", environ=_hosted(repo), patterns_for=POLICY)


def test_source_filters_are_refused_before_content_conversion(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    (repo / ".gitattributes").write_bytes(b"engine.py filter=unadmitted\n")
    _commit(repo, "filter attribute")
    with pytest.raises(handoff.HandoffRefusal, match="unsupported filter"):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "executable"])
def test_installer_metadata_cannot_supply_linked_or_executable_inputs(repo, tmp_path, monkeypatch, kind):
    monkeypatch.setattr(handoff, "platform", SimpleNamespace(python_version=lambda: "3.12.11"))
    target = repo / handoff.INSTALLER_ROOT / "PKG-INFO"
    target.parent.mkdir()
    outside = tmp_path / "installer-source"
    outside.write_bytes(b"Metadata-Version: 2.4\n")
    if kind == "symlink":
        _symlink_or_skip(target, outside)
    elif kind == "hardlink":
        try:
            os.link(outside, target)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"hard links unavailable: {error}")
    else:
        if os.name == "nt":
            pytest.skip("executable mode is a hosted Linux producer property")
        target.write_bytes(outside.read_bytes())
        target.chmod(0o755)
    with pytest.raises(handoff.HandoffRefusal):
        handoff.phase_before(repo, tmp_path / "state", environ=_hosted(repo))
    assert not (tmp_path / "state").exists()


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
