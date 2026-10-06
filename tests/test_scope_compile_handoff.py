"""Hostile source/member mutations cannot promote a Scope review handoff."""
from __future__ import annotations

import builtins
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github/scripts"


def _load_handoff():
    spec = importlib.util.spec_from_file_location("scope_compile_handoff", SCRIPTS / "scope_compile_handoff.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _restore_sys_path(original, contents):
    original[:] = contents
    sys.path = original


def _load_handoff_for_collection():
    # Collection must not contaminate unrelated tests while the regression is red.
    original, contents = sys.path, list(sys.path)
    try:
        return _load_handoff()
    finally:
        _restore_sys_path(original, contents)


handoff = _load_handoff_for_collection()


@pytest.fixture(autouse=True)
def isolate_sys_path():
    original, contents = sys.path, list(sys.path)
    try:
        yield
    finally:
        # Restore only after assertions; within-test path leaks remain observable.
        _restore_sys_path(original, contents)


@pytest.fixture
def family(tmp_path, monkeypatch):
    # These synthetic cisco_toolkit files remain deliberately invalid witness
    # bytes. Bind the real scanner before a synthetic root can enter sys.path.
    importlib.import_module("cisco_toolkit.distribution_verify")
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".git").mkdir()
    contract = {
        "outputs": [{"key": f"part{i}", "file": f"part{i}.json", "trackedPath": f"src/data/part{i}.json"}
                    for i in range(4)],
        "binding_keys": ["source", "sourceOrigin", "sourceDigestForm", "sourceSha256", "sourceBytes",
                         "sourceExactSha256", "sourceGitBlob"],
        "source": "webapp/sample_data/sample_fleet.snapshot.json", "digest_form": "lf-normalised",
    }
    committed = {}

    def commit(name, raw):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        committed[name] = raw

    for path in handoff.PROCESSING_INPUTS:
        commit(path, b"synthetic processing source\n")
    commit("atlas-scope/.gitignore", b"node_modules/\ndist/\n.local-data/\n")
    commit("atlas-scope/src/model.ts", b"export const synthetic = 1;\n")
    owner = "atlas-scope/tools/lib/compile-model.mjs"
    commit(owner, ("export const OUTPUTS = " + json.dumps(contract["outputs"]) + ";\n"
                   "export const BINDING_KEYS = " + json.dumps(contract["binding_keys"]) + ";\n").encode())
    commit("atlas-scope/tools/source-binding.mjs", b"export const syntheticSourceOwner = true;\n")
    commit(contract["source"], b'{"schema":"synthetic/1","devices":{"edge":{}}}\n')
    for row in contract["outputs"]:
        commit("atlas-scope/" + row["trackedPath"], b'{"old":"tracked output retained"}\n')
    indexed = list(committed)
    modes, staged_modes, staged_blobs, staged_stages = {}, {}, {}, {}
    node_exports_calls = []
    ignored = set()
    worktrees = [root]

    def command(argv, **_kwargs):
        if argv[0] == "node":
            if "-e" not in argv:
                return b"v24.19.0\n"
            node_exports_calls.append(argv)
            text = (root / owner).read_text()
            result = dict(contract)
            for field, export in (("outputs", "OUTPUTS"), ("binding_keys", "BINDING_KEYS")):
                result[field] = json.loads(re.search(r"export const " + export + r" = (.+);", text)[1])
            assert "compileAll(" not in argv[-1]
            return json.dumps(result).encode()
        if argv[0] == "npm":
            return b"11.17.0\n"
        assert argv[0] == "git"
        if argv[1:3] == ["worktree", "list"]:
            assert argv[3:] == ["--porcelain", "-z"]
            return b"".join(("worktree " + str(path)).encode("utf-8") + b"\0\0" for path in worktrees)
        if argv[1] == "check-ignore":
            if "/node_modules/" in argv[-1] or "/.local-data/" in argv[-1]:
                return b"atlas-scope/.gitignore:1:node_modules/\tsentinel\n"
            raise subprocess.CalledProcessError(1, argv)
        if argv[1] == "rev-parse":
            if "--git-common-dir" in argv:
                return str(root / ".git").encode()
            if argv[2].startswith("HEAD:"):
                raw = committed[argv[2][5:]].replace(b"\r\n", b"\n")
                return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest().encode()
            return ("a" * 40 if argv[2] == "HEAD" else "b" * 40).encode()
        if argv[1] == "cat-file":
            raw = committed[argv[3][5:]]
            return str(len(raw)).encode() if argv[2] == "-s" else raw
        if "--others" in argv:
            extras = [p.relative_to(root).as_posix() for p in (root / "atlas-scope").rglob("*")
                      if p.is_file() and p.relative_to(root).as_posix() not in indexed]
            return "\0".join(p for p in extras if (p in ignored) == ("--ignored" in argv)).encode()
        assert argv[1] in {"ls-tree", "ls-files"}
        records = []
        for name in committed if argv[1] == "ls-tree" else indexed:
            raw = committed.get(name, b"new index-only material")
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            mode = modes.get(name, "100644")
            if argv[1] == "ls-tree":
                kind = "commit" if mode == "160000" else "blob"
                records.append(f"{mode} {kind} {blob}\t{name}")
            else:
                records.append(f"{staged_modes.get(name, mode)} {staged_blobs.get(name, blob)} {staged_stages.get(name, '0')}\t{name}")
        return ("\0".join(records) + "\0").encode()

    monkeypatch.setattr(handoff, "__file__", str(root / ".github/scripts/scope_compile_handoff.py"))
    monkeypatch.setattr(handoff.subprocess, "check_output", command)
    for key, value in {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                       "RUNNER_OS": "Linux"}.items():
        monkeypatch.setenv(key, value)
    target = tmp_path / "handoff"

    def run(phase, output=None):
        monkeypatch.setattr(sys, "argv", ["helper", phase, "--output", str(output or target)])
        handoff.main()

    def compile_members():
        raw = committed[contract["source"]]
        binding = {"source": contract["source"], "sourceOrigin": "repository-file",
                   "sourceDigestForm": "lf-normalised", "sourceSha256": hashlib.sha256(raw).hexdigest(),
                   "sourceBytes": len(raw), "sourceExactSha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                   "sourceGitBlob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
        (target / "members").mkdir()
        for row in contract["outputs"]:
            (target / "members" / row["file"]).write_text(json.dumps({"meta": binding, "synthetic": []}), encoding="utf-8")

    return SimpleNamespace(root=root, target=target, contract=contract, committed=committed, indexed=indexed,
                           ignored=ignored, worktrees=worktrees, run=run, compile=compile_members,
                           owner=owner, monkeypatch=monkeypatch, modes=modes, staged_modes=staged_modes,
                           staged_blobs=staged_blobs, staged_stages=staged_stages, node_exports_calls=node_exports_calls)


def test_loading_handoff_preserves_sys_path_identity_and_contents():
    original, contents = sys.path, list(sys.path)
    loaded = _load_handoff()
    assert callable(loaded.main)
    assert sys.path is original
    assert sys.path == contents


@pytest.mark.parametrize("phase", ["before", "after"])
def test_successful_handoff_preserves_sys_path_identity_and_contents(family, phase):
    if phase == "after":
        family.run("before")
        family.compile()
    original, contents = sys.path, list(sys.path)
    family.run(phase)
    assert (family.target / ("source-before.json" if phase == "before" else "handoff.json")).is_file()
    assert sys.path is original
    assert sys.path == contents


def test_member_refusal_after_scanner_import_preserves_sys_path(family, monkeypatch):
    family.run("before")
    family.compile()
    member_path = family.target / "members/part0.json"
    member = json.loads(member_path.read_bytes())
    member["meta"]["sourceSha256"] = "wrong-source"
    member_path.write_text(json.dumps(member), encoding="utf-8")
    imported = []
    real_import = builtins.__import__

    def observe_import(name, *args, **kwargs):
        if name == "cisco_toolkit.distribution_verify":
            imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", observe_import)
    original, contents = sys.path, list(sys.path)
    with pytest.raises(ValueError, match="binding"):
        family.run("after")
    assert imported, "the member refusal must follow the canonical scanner import"
    assert not (family.target / "handoff.json").exists()
    assert sys.path is original
    assert sys.path == contents


def test_loading_handoff_import_failure_preserves_sys_path(monkeypatch):
    attempted = []
    real_import = builtins.__import__

    def refuse_import(name, *args, **kwargs):
        if name == "verify_repository_privacy":
            attempted.append(name)
            raise ImportError("synthetic guard import refusal")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_import)
    original, contents = sys.path, list(sys.path)
    with pytest.raises(ImportError, match="synthetic guard import refusal"):
        _load_handoff()
    assert attempted == ["verify_repository_privacy"]
    assert sys.path is original
    assert sys.path == contents


def test_scanner_import_failure_preserves_sys_path(family, monkeypatch):
    family.run("before")
    family.compile()
    attempted = []
    real_import = builtins.__import__

    def refuse_import(name, *args, **kwargs):
        if name == "cisco_toolkit.distribution_verify":
            attempted.append(name)
            raise ImportError("synthetic scanner import refusal")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_import)
    original, contents = sys.path, list(sys.path)
    with pytest.raises(ImportError, match="synthetic scanner import refusal"):
        family.run("after")
    assert attempted == ["cisco_toolkit.distribution_verify"]
    assert not (family.target / "handoff.json").exists()
    assert sys.path is original
    assert sys.path == contents


def test_complete_family_is_source_bound_closed_and_nonpromoting(family):
    old = {r["trackedPath"]: (family.root / "atlas-scope" / r["trackedPath"]).read_bytes()
           for r in family.contract["outputs"]}
    family.run("before")
    family.compile()
    family.run("after")
    receipt = json.loads((family.target / "handoff.json").read_bytes())
    assert receipt["status"] == "GENERATED_INPUT_FOR_REVIEW_ONLY"
    assert receipt["release_authority"] is False and receipt["final_source_rebuild_required"] is True
    assert len(receipt["members"]) == 4 and set(receipt["tracked_output_before"]) == {"atlas-scope/" + p for p in old}
    assert all((family.root / "atlas-scope" / p).read_bytes() == raw for p, raw in old.items())
    assert set(receipt["source"]["inputs"]).isdisjoint(receipt["tracked_output_before"])
    assert set(p.name for p in family.target.iterdir()) == {"source-before.json", "members", "handoff.json"}


@pytest.mark.parametrize("mode", ["120000", "160000"])
@pytest.mark.parametrize("name", ["atlas-scope/src/model.ts", "atlas-scope/src/data/part0.json"])
def test_wrong_git_mode_is_refused_before_owner_import_even_with_regular_disk_file(family, mode, name):
    family.modes[name] = mode
    assert (family.root / name).is_file() and not (family.root / name).is_symlink()
    with pytest.raises(ValueError, match="ordinary blob"):
        family.run("before")
    assert family.node_exports_calls == []
    assert not family.target.exists()


@pytest.mark.parametrize("kind", ["mode", "blob", "stage"])
def test_index_requires_exact_head_mode_blob_and_stage_zero(family, kind):
    name = "atlas-scope/src/model.ts"
    if kind == "mode":
        family.staged_modes[name] = "100755"
    elif kind == "blob":
        family.staged_blobs[name] = "f" * 40
    else:
        family.staged_stages[name] = "2"
    with pytest.raises(ValueError, match="index"):
        family.run("before")
    assert family.node_exports_calls == []


def test_correct_executable_git_blob_is_preserved_in_material_record(family):
    family.modes[family.owner] = "100755"
    family.run("before")
    family.compile()
    family.run("after")
    receipt = json.loads((family.target / "handoff.json").read_bytes())
    material = receipt["source"]["inputs"][family.owner]
    assert material["git_mode"] == "100755"
    raw = family.committed[family.owner]
    assert material["git_blob"] == hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert all(value["git_mode"] == "100644" for value in receipt["tracked_output_before"].values())


@pytest.mark.parametrize("kind", ["physical", "index", "ignored", "unignored", "tracked_output"])
def test_changed_or_uncontrolled_source_fails_closed(family, kind):
    family.run("before")
    family.compile()
    if kind in {"physical", "tracked_output"}:
        name = "atlas-scope/src/model.ts" if kind == "physical" else "atlas-scope/src/data/part0.json"
        (family.root / name).write_bytes(b"changed source")
    elif kind == "index":
        family.indexed.append("atlas-scope/src/new.ts")
    else:
        name = "atlas-scope/.env.local"
        (family.root / name).write_bytes(b"uncontrolled input")
        if kind == "ignored":
            family.ignored.add(name)
    with pytest.raises(ValueError):
        family.run("after")
    assert not (family.target / "handoff.json").exists()


@pytest.mark.parametrize("key", ["source", "sourceOrigin", "sourceDigestForm", "sourceSha256", "sourceBytes",
                                 "sourceExactSha256", "sourceGitBlob"])
def test_every_binding_field_rejects_a_mixed_source_member(family, key):
    family.run("before")
    family.compile()
    path = family.target / "members/part2.json"
    member = json.loads(path.read_bytes())
    member["meta"][key] = True if key == "sourceBytes" else "different-source"
    path.write_text(json.dumps(member), encoding="utf-8")
    with pytest.raises(ValueError, match="binding"):
        family.run("after")


@pytest.mark.parametrize("raw", [b'{"meta":{},"meta":{}}', b'{"meta":{},"v":NaN}',
                                 b'{"meta":{},"v":1e9999}', b'\xff', b'{"meta":{}'])
def test_unreadable_or_nonfinite_or_duplicate_json_is_refused(family, raw):
    family.run("before")
    family.compile()
    (family.target / "members/part0.json").write_bytes(raw)
    with pytest.raises(ValueError):
        family.run("after")


@pytest.mark.parametrize("kind", ["extra", "missing", "directory", "hardlink", "oversized"])
def test_family_inventory_and_members_are_closed(family, kind):
    family.run("before")
    family.compile()
    path = family.target / "members/part0.json"
    if kind == "extra":
        (family.target / "members/extra.json").write_bytes(b"{}")
    elif kind == "missing":
        path.unlink()
    elif kind == "directory":
        path.unlink()
        path.mkdir()
    elif kind == "hardlink":
        os.link(path, family.target.parent / "outside-alias.json")
    else:
        family.monkeypatch.setattr(handoff, "MAX_MEMBER_BYTES", 1)
    with pytest.raises(ValueError):
        family.run("after")


def test_reparse_directory_is_refused(family):
    family.run("before")
    family.compile()
    real = handoff._is_reparse_point
    family.monkeypatch.setattr(handoff, "_is_reparse_point", lambda info: real(info) or info.st_ino == (family.target / "members").stat().st_ino)
    with pytest.raises(ValueError, match="directory"):
        family.run("after")


def test_reparse_file_is_refused_by_the_canonical_reader(family):
    family.run("before")
    family.compile()
    guard = sys.modules[handoff._read_bounded.__module__]
    real = guard._is_reparse_point
    inode = (family.target / "members/part0.json").stat().st_ino
    family.monkeypatch.setattr(guard, "_is_reparse_point", lambda info: real(info) or info.st_ino == inode)
    with pytest.raises(ValueError, match="regular"):
        family.run("after")


def test_total_family_bound_is_checked_across_members(family):
    family.run("before")
    family.compile()
    first = family.target / "members/part0.json"
    family.monkeypatch.setattr(handoff, "MAX_TOTAL_BYTES", first.stat().st_size + 1)
    with pytest.raises(ValueError, match="limit"):
        family.run("after")


def test_changed_hosted_context_cannot_reuse_the_before_receipt(family):
    family.run("before")
    family.compile()
    family.monkeypatch.setenv("GITHUB_RUN_ID", "different-run")
    with pytest.raises(ValueError, match="context"):
        family.run("after")


def test_missing_tracked_member_reference_is_refused(family):
    outputs = family.contract["outputs"]
    outputs[0]["trackedPath"] = "src/data/untracked.json"
    raw = ("export const OUTPUTS = " + json.dumps(outputs) + ";\n"
           "export const BINDING_KEYS = " + json.dumps(family.contract["binding_keys"]) + ";\n").encode()
    (family.root / family.owner).write_bytes(raw)
    family.committed[family.owner] = raw
    with pytest.raises(ValueError, match="committed member"):
        family.run("before")


def test_before_record_cannot_be_replaced_by_an_alias(family):
    family.run("before")
    family.compile()
    os.link(family.target / "source-before.json", family.target.parent / "source-alias.json")
    with pytest.raises(ValueError, match="hardlinked"):
        family.run("after")


def test_marker_scan_is_the_canonical_unexempted_json_scan(family):
    family.run("before")
    family.compile()
    path = family.target / "members/part0.json"
    member = json.loads(path.read_bytes())
    member["unsafe"] = "ja" + "jch"
    path.write_text(json.dumps(member), encoding="utf-8")
    with pytest.raises(ValueError, match="marker"):
        family.run("after")


def test_output_cannot_enter_another_worktree_or_common_git(family):
    other = family.target.parent / "other-worktree-\u03b1"
    other.mkdir()
    family.worktrees.append(other)
    for target in (other / "handoff", family.root / ".git/output", family.root.parent, Path("relative-output")):
        with pytest.raises(ValueError, match="outside|absolute"):
            family.run("before", target)


def test_nul_worktree_records_preserve_embedded_newline_and_non_ascii(family):
    other = family.target.parent / "other-worktree\n\u03b1"
    family.worktrees.append(other)
    assert handoff._worktree_roots(family.root) == [family.root, other]


@pytest.mark.parametrize("raw", [b"worktree relative\0\0", b"worktree /truncated", b"HEAD abc\0\0"])
def test_malformed_worktree_inventory_cannot_authorize_output(family, raw):
    original = handoff._git
    family.monkeypatch.setattr(handoff, "_git", lambda root, *args: raw if args[0] == "worktree" else original(root, *args))
    with pytest.raises(ValueError, match="worktree"):
        family.run("before")


@pytest.mark.parametrize("path", ["../outside.json", "src/../outside.json", "/absolute.json", "src/data//part0.json"])
def test_owner_member_reference_must_close_to_a_safe_committed_path(family, path):
    outputs = family.contract["outputs"]
    outputs[0]["trackedPath"] = path
    raw = ("export const OUTPUTS = " + json.dumps(outputs) + ";\n"
           "export const BINDING_KEYS = " + json.dumps(family.contract["binding_keys"]) + ";\n").encode()
    (family.root / family.owner).write_bytes(raw)
    family.committed[family.owner] = raw
    with pytest.raises(ValueError, match="path"):
        family.run("before")


def test_generated_install_directory_requires_its_tracked_ignore_owner(family):
    path = family.root / "atlas-scope/node_modules/pkg/index.js"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"installed dependency")
    family.ignored.add(path.relative_to(family.root).as_posix())
    family.run("before")
    assert (family.target / "source-before.json").is_file()
