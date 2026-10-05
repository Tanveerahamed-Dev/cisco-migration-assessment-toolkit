"""Bound a hosted SPA output to unchanged source inputs; never a release receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from verify_repository_privacy import _is_reparse_point, _read_bounded


# Bounded, review-only text transfer. These are not release packaging limits.
MAX_FILES = 64
MAX_ENTRIES = 128
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
PROCESSING_INPUTS = (
    ".github/scripts/frontend_build_handoff.py",
    ".github/scripts/verify_repository_privacy.py",
    ".github/scripts/classify_webapp_ci_scope.py",
    ".github/workflows/webapp-ci.yml",
    "cisco_toolkit/distribution_verify.py",
)
# These are existing generated/install directories, never source inputs. An
# ignored root file (including .env.local) remains an untracked build input.
GENERATED_DIRECTORIES = {"dist", "node_modules", ".generated"}


def _ordinary_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        raise ValueError("Generated SPA directory is indirect or nonregular")


def _inventory(dist: Path) -> list[Path]:
    _ordinary_directory(dist)
    files = []
    entries = 0
    pending = [dist]
    while pending:
        directory = pending.pop()
        _ordinary_directory(directory)
        for path in directory.iterdir():
            entries += 1
            if entries > MAX_ENTRIES:
                raise ValueError("Generated SPA inventory is oversized")
            info = path.lstat()
            if _is_reparse_point(info):
                raise ValueError("Generated SPA member is indirect or nonregular")
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                if path.suffix not in {".html", ".js", ".css", ".svg", ".json", ".txt"}:
                    raise ValueError("Generated handoff admits reviewed text formats only")
                files.append(path)
                if len(files) > MAX_FILES:
                    raise ValueError("Generated SPA inventory is oversized")
            else:
                raise ValueError("Generated SPA member is indirect or nonregular")
    if not files or dist / "index.html" not in files:
        raise ValueError("Generated SPA inventory is incomplete")
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError("Handoff must be outside the checkout")

    def git(*tokens: str) -> str:
        return subprocess.check_output(["git", *tokens], cwd=root).decode().strip()

    def source_inputs() -> dict[str, object]:
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD", "--",
             "webapp/frontend", *PROCESSING_INPUTS], cwd=root,
        ).decode().split("\0")
        if not set(PROCESSING_INPUTS).issubset(paths):
            raise ValueError("Handoff processing inputs are not committed")
        indexed = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "webapp/frontend", *PROCESSING_INPUTS], cwd=root,
        ).decode().split("\0")
        source_paths = sorted(path for path in paths if path and not path.startswith("webapp/frontend/dist/"))
        index_paths = sorted(path for path in indexed if path and not path.startswith("webapp/frontend/dist/"))
        if source_paths != index_paths:
            raise ValueError("Frontend input index differs from the committed tree")
        inputs = {}
        for path in source_paths:
            for directory in (root / path).parents:
                _ordinary_directory(directory)
                if directory == root:
                    break
            data = _read_bounded(root / path, MAX_INPUT_BYTES)
            size = int(subprocess.check_output(
                ["git", "cat-file", "-s", "HEAD:" + path], cwd=root,
            ))
            if size > MAX_INPUT_BYTES:
                raise ValueError("Committed frontend input exceeds bounded read")
            committed = subprocess.check_output(["git", "cat-file", "blob", "HEAD:" + path], cwd=root)
            if data != committed:
                raise ValueError("Frontend input differs from its committed source")
            inputs[path] = hashlib.sha256(data).hexdigest()
        for ignored in (False, True):
            flags = ["--others", "--exclude-standard"] + (["--ignored"] if ignored else [])
            extra = subprocess.check_output(
                ["git", "ls-files", "-z", *flags, "--", "webapp/frontend"], cwd=root,
            ).decode().split("\0")
            for path in extra:
                if path and Path(path).relative_to("webapp/frontend").parts[0] not in GENERATED_DIRECTORIES:
                    raise ValueError("Untracked frontend build input")
        return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"), "inputs": inputs}

    source = source_inputs()
    if source["commit"] != os.environ["GITHUB_SHA"]:
        raise ValueError("Selected checkout differs from the hosted context")
    before = output / "source-before.json"
    if args.phase == "before":
        output.mkdir(parents=True, exist_ok=False)
        before.write_text(json.dumps(source, sort_keys=True) + "\n", encoding="utf-8")
        return
    _ordinary_directory(output)
    if set(output.iterdir()) != {before}:
        raise ValueError("Handoff output is not the fresh before-phase directory")
    if json.loads(_read_bounded(before, MAX_INPUT_BYTES)) != source:
        raise ValueError("Frontend source inputs changed during the build")
    dist = root / "webapp/frontend/dist"
    files = _inventory(dist)
    sys.path.insert(0, str(root))
    from cisco_toolkit.distribution_verify import _marker_patterns_for
    members = {}
    remaining = MAX_TOTAL_BYTES
    for path in files:
        name = path.relative_to(dist).as_posix()
        data = _read_bounded(path, remaining)
        remaining -= len(data)
        patterns = _marker_patterns_for("webapp/frontend/dist/" + name)
        if any(pattern.search(data.decode("utf-8")) for pattern in patterns):
            raise ValueError("Generated bytes fail the canonical marker scan")
        target = output / "dist" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        members[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if hashlib.sha256(_read_bounded(target, len(data))).hexdigest() != members[name]["sha256"]:
            raise ValueError("Captured member changed")
    if _inventory(dist) != files:
        raise ValueError("Generated member inventory changed during capture")
    for path in files:
        data = _read_bounded(path, members[path.relative_to(dist).as_posix()]["bytes"])
        if hashlib.sha256(data).hexdigest() != members[path.relative_to(dist).as_posix()]["sha256"]:
            raise ValueError("Generated member changed during capture")
    if json.loads(_read_bounded(before, MAX_INPUT_BYTES)) != source_inputs():
        raise ValueError("Frontend source changed during handoff capture")
    captured = _inventory(output / "dist")
    if [path.relative_to(output / "dist").as_posix() for path in captured] != list(members):
        raise ValueError("Captured handoff member inventory changed")
    for path in captured:
        member = members[path.relative_to(output / "dist").as_posix()]
        data = _read_bounded(path, member["bytes"])
        if hashlib.sha256(data).hexdigest() != member["sha256"]:
            raise ValueError("Captured handoff member changed")
    record = {"schema": "frontend_build_handoff/1", "source": source, "members": members,
              "github_head": os.environ.get("PR_HEAD_SHA") or source["commit"],
              "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "node": subprocess.check_output(["node", "--version"]).decode().strip(),
              "npm": subprocess.check_output(["npm", "--version"]).decode().strip(),
              "status": "GENERATED_INPUT_FOR_REVIEW_ONLY", "release_authority": False,
              "final_source_rebuild_required": True}
    (output / "handoff.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
