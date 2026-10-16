"""Hostile input/output mutations cannot promote a review-only SPA handoff."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))


def _module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handoff = _module("frontend_build_handoff")


@pytest.fixture
def build(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    frontend = root / "webapp/frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "dist/assets").mkdir(parents=True)
    (frontend / "src/main.ts").write_text("export const source = 1;", encoding="utf-8")
    (frontend / "dist/index.html").write_text("<script src='assets/app.js'></script>", encoding="utf-8")
    (frontend / "dist/assets/app.js").write_text("console.log('synthetic source');", encoding="utf-8")
    paths = ["webapp/frontend/src/main.ts", "webapp/frontend/dist/index.html"]
    for path in handoff.PROCESSING_INPUTS:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("synthetic processing input\n", encoding="utf-8")
        paths.append(path)
    committed = {path: (root / path).read_bytes() for path in paths}
    indexed = paths.copy()
    ignored = set()

    def output(command, **_kwargs):
        if command[0] == "node":
            return b"v24.19.0\n"
        if command[0] == "npm":
            return b"11.16.0\n"
        assert command[0] == "git"
        if command[1] == "rev-parse":
            return ("a" * 40 if command[2] == "HEAD" else "b" * 40).encode()
        if command[1] == "cat-file":
            data = committed[command[3].removeprefix("HEAD:")]
            return str(len(data)).encode() if command[2] == "-s" else data
        if "--others" in command:
            extra = [path.relative_to(root).as_posix() for path in frontend.rglob("*")
                     if path.is_file() and path.relative_to(root).as_posix() not in indexed]
            selected = [path for path in extra if (path in ignored) == ("--ignored" in command)]
            return "\0".join(selected).encode()
        assert command[1] in {"ls-files", "ls-tree"}
        return ("\0".join(paths if command[1] == "ls-tree" else indexed) + "\0").encode()

    monkeypatch.setattr(handoff, "__file__", str(root / ".github/scripts/frontend_build_handoff.py"))
    monkeypatch.setattr(handoff.subprocess, "check_output", output)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    target = tmp_path / "handoff"

    def run(phase):
        monkeypatch.setattr(sys, "argv", ["helper", phase, "--output", str(target)])
        handoff.main()

    return SimpleNamespace(root=root, frontend=frontend, target=target, paths=paths,
                           indexed=indexed, committed=committed, ignored=ignored, run=run)


def test_generated_output_is_closed_to_committed_inputs_and_nonpromoting(build):
    build.run("before")
    build.run("after")
    receipt = json.loads((build.target / "handoff.json").read_text())
    assert set(receipt["members"]) == {"index.html", "assets/app.js"}
    assert receipt["status"] == "GENERATED_INPUT_FOR_REVIEW_ONLY"
    assert receipt["release_authority"] is False
    assert receipt["final_source_rebuild_required"] is True
    assert receipt["source"]["commit"] == "a" * 40
    assert set(handoff.PROCESSING_INPUTS) <= set(receipt["source"]["inputs"])
    assert "webapp/frontend/dist/index.html" not in receipt["source"]["inputs"]
    assert handoff.MAX_FILES == 64 and handoff.MAX_TOTAL_BYTES == 64 * 1024 * 1024


def test_changed_or_newly_tracked_frontend_inputs_are_refused(build):
    build.run("before")
    source = build.frontend / "src/main.ts"
    source.write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="committed"):
        build.run("after")
    source.write_bytes(build.committed[build.paths[0]])
    added = "webapp/frontend/src/extra.ts"
    (build.root / added).write_text("extra", encoding="utf-8")
    build.indexed.append(added)
    with pytest.raises(ValueError, match="index differs"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("remove_disk", [False, True])
def test_committed_input_cannot_disappear_from_the_index_census(build, remove_disk):
    build.indexed.remove("webapp/frontend/src/main.ts")
    if remove_disk:
        (build.frontend / "src/main.ts").unlink()
    with pytest.raises(ValueError, match="index differs"):
        build.run("before")
    assert not build.target.exists()


def test_committed_input_must_exist_even_if_the_index_is_unchanged(build):
    (build.frontend / "src/main.ts").unlink()
    with pytest.raises(FileNotFoundError):
        build.run("before")
    assert not build.target.exists()


@pytest.mark.parametrize("ignored", [False, True])
@pytest.mark.parametrize("path", ["src/extra.ts", "scripts/extra.mjs", "public/extra.js", ".env.local"])
def test_new_build_inputs_are_refused_even_when_ignored(build, ignored, path):
    build.run("before")
    extra = build.frontend / path
    extra.parent.mkdir(exist_ok=True)
    extra.write_text("uncommitted input", encoding="utf-8")
    if ignored:
        build.ignored.add(extra.relative_to(build.root).as_posix())
    with pytest.raises(ValueError, match="Untracked"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


def test_only_known_install_and_generated_directories_are_excluded(build):
    for directory in handoff.GENERATED_DIRECTORIES:
        path = build.frontend / directory / "synthetic.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        build.ignored.add(path.relative_to(build.root).as_posix())
    build.run("before")
    build.run("after")
    assert (build.target / "handoff.json").exists()


def test_growing_member_is_bounded_by_the_actual_reader(build, monkeypatch):
    build.run("before")
    index_size = (build.frontend / "dist/index.html").stat().st_size
    monkeypatch.setattr(handoff, "MAX_TOTAL_BYTES", index_size + 48)
    real = handoff._read_bounded
    seen_limits = []

    def grew(path, limit):
        if path == build.frontend / "dist/assets/app.js":
            seen_limits.append(limit)
            with path.open("ab") as stream:
                stream.write(b"x" * 65)
        return real(path, limit)

    monkeypatch.setattr(handoff, "_read_bounded", grew)
    with pytest.raises(ValueError, match="exceeds.*privacy-scan limit"):
        build.run("after")
    assert seen_limits and seen_limits[0] <= index_size + 48
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("mutation", ["new_member", "changed_member", "changed_input", "captured_member"])
def test_capture_refuses_mutation_during_the_actual_read(build, monkeypatch, mutation):
    build.run("before")
    real = handoff._read_bounded
    changed = False

    def mutate(path, limit):
        nonlocal changed
        data = real(path, limit)
        if not changed and path == build.frontend / "dist/assets/app.js":
            changed = True
            if mutation == "new_member":
                (path.parent / "unexpected.js").write_text("new", encoding="utf-8")
            elif mutation == "changed_member":
                path.write_text("changed", encoding="utf-8")
            elif mutation == "changed_input":
                (build.frontend / "src/main.ts").write_text("changed", encoding="utf-8")
        elif mutation == "captured_member" and path == build.frontend / "dist/assets/app.js":
            (build.target / "dist/assets/app.js").write_text("changed", encoding="utf-8")
        return data

    monkeypatch.setattr(handoff, "_read_bounded", mutate)
    with pytest.raises(ValueError, match="changed|committed"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("location", ["dist", "dist/assets", "src"])
def test_directory_reparse_points_are_refused(build, monkeypatch, location):
    build.run("before")
    indirect = (build.frontend / location).lstat()
    real = handoff._is_reparse_point
    monkeypatch.setattr(handoff, "_is_reparse_point", lambda info: info.st_ino == indirect.st_ino or real(info))
    with pytest.raises(ValueError, match="indirect"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("root_link", [False, True])
def test_root_or_member_symlinks_are_refused(build, root_link):
    build.run("before")
    dist = build.frontend / "dist"
    link = dist if root_link else dist / "assets/indirect.js"
    if root_link:
        dist.rename(build.root / "saved-dist")
    try:
        link.symlink_to(build.root / "saved-dist" if root_link else dist / "assets/app.js",
                        target_is_directory=root_link)
    except OSError as exc:
        pytest.skip(f"host cannot create test symlink: {exc}")
    with pytest.raises(ValueError, match="indirect|nonregular"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


def test_nonregular_member_is_refused(build):
    if not hasattr(os, "mkfifo"):
        pytest.skip("host cannot create test FIFO")
    build.run("before")
    os.mkfifo(build.frontend / "dist/assets/nonregular.js")
    with pytest.raises(ValueError, match="nonregular"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("failure", ["count", "entries", "text", "privacy", "output"])
def test_closed_capture_refusals(build, monkeypatch, failure):
    build.run("before")
    if failure == "count":
        monkeypatch.setattr(handoff, "MAX_FILES", 1)
    elif failure == "entries":
        monkeypatch.setattr(handoff, "MAX_ENTRIES", 1)
    elif failure == "text":
        (build.frontend / "dist/assets/binary.bin").write_bytes(b"\x00")
    elif failure == "privacy":
        (build.frontend / "dist/assets/app.js").write_text("al" + "jazeera", encoding="utf-8")
    else:
        (build.target / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="oversized|text formats|canonical marker|fresh before"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


def test_wrong_hosted_source_or_uncommitted_processor_is_refused(build, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    with pytest.raises(ValueError, match="hosted context"):
        build.run("before")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    build.paths.remove(handoff.PROCESSING_INPUTS[0])
    with pytest.raises(ValueError, match="processing inputs"):
        build.run("before")
    assert not build.target.exists()


def test_canonical_generated_alias_policy_applies_only_to_top_level_js_bundle(build):
    alias = "export {value as " + "a" + "j" + "};"
    (build.frontend / "dist/assets/app.js").write_text(alias, encoding="utf-8")
    build.run("before")
    build.run("after")
    assert (build.target / "dist/assets/app.js").read_text() == alias


@pytest.mark.parametrize("path", ["index.html", "assets/nested/app.js"])
def test_generated_alias_is_refused_outside_the_canonical_bundle_path(build, path):
    member = build.frontend / "dist" / path
    member.parent.mkdir(exist_ok=True)
    member.write_text("export {value as " + "a" + "j" + "};", encoding="utf-8")
    build.run("before")
    with pytest.raises(ValueError, match="canonical marker"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


@pytest.mark.parametrize("marker", ["al" + "jazeera", "a" + "j" + "-fleet", "jaj" + "ch"])
def test_brand_compound_and_user_markers_remain_refused_inside_bundle(build, marker):
    (build.frontend / "dist/assets/app.js").write_text(marker, encoding="utf-8")
    build.run("before")
    with pytest.raises(ValueError, match="canonical marker"):
        build.run("after")
    assert not (build.target / "handoff.json").exists()


def test_helper_and_privacy_guard_changes_engage_the_existing_hosted_job():
    classifier = _module("classify_webapp_ci_scope")
    for path in handoff.PROCESSING_INPUTS:
        assert classifier.path_is_relevant(path)
    workflow = (ROOT / ".github/workflows/webapp-ci.yml").read_text(encoding="utf-8")
    before = workflow.index("frontend_build_handoff.py before")
    build = workflow.index("- run: npm run build", before)
    after = workflow.index("frontend_build_handoff.py after", build)
    upload = workflow.index("name: Preserve the source-bound SPA build handoff", after)
    assert before < build < after < upload
    assert "permissions:\n  contents: read" in workflow
