"""Capture a hosted Scope compiler family for review; never release authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

# The workflow invokes this with -I; expose the committed guard only while importing it.
_guard_import_path = sys.path[:]
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_repository_privacy import _is_reparse_point, _read_bounded
finally:
    sys.path[:] = _guard_import_path
del _guard_import_path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
PROCESSING_INPUTS = (
    ".github/scripts/scope_compile_handoff.py",
    ".github/scripts/verify_repository_privacy.py",
    ".github/workflows/atlas-scope-ci.yml",
    "cisco_toolkit/__init__.py",
    "cisco_toolkit/distribution_verify.py",
    ".gitignore",
)
# Only actual generated directories are candidates. Each allowance also needs a
# tracked root/Scope .gitignore owner; an ignored authored input still fails.
GENERATED_DIRECTORIES = (
    "node_modules", "dist", "dist-hub", ".local-data", ".vite", "coverage",
    "test-results", "review/shots", "review/blind", "review/reports",
)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        raise ValueError("Handoff directory is indirect or nonregular")


def _parents(path: Path) -> None:
    for parent in path.parents:
        _directory(parent)


def _read(path: Path, maximum: int) -> bytes:
    _parents(path)
    if path.lstat().st_nlink != 1:
        raise ValueError("Handoff file is hardlinked")
    data = _read_bounded(path, maximum)
    if path.lstat().st_nlink != 1:
        raise ValueError("Handoff file became hardlinked")
    return data


def _json(data: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("JSON has duplicate keys")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("JSON has a nonfinite number")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 256:
                raise ValueError("JSON nesting exceeds the bounded family contract")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("JSON has a nonfinite number")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Member is not strict bounded UTF-8 JSON") from exc


def _safe_relative(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Owner output path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} or ":" in part for part in path.parts):
        raise ValueError("Owner output path is unsafe")
    if path.as_posix() != value:
        raise ValueError("Owner output path is noncanonical")
    return value


def _contract(root: Path) -> dict:
    # Read exports from the same compiler the hosted step calls. Do not carry a
    # hand-maintained second list of output names or binding fields.
    code = (
        "import {OUTPUTS,BINDING_KEYS} from './atlas-scope/tools/lib/compile-model.mjs';"
        "import {SOURCE_REL,SOURCE_DIGEST_FORM} from './atlas-scope/tools/source-binding.mjs';"
        "process.stdout.write(JSON.stringify({outputs:OUTPUTS,binding_keys:BINDING_KEYS,"
        "source:SOURCE_REL,digest_form:SOURCE_DIGEST_FORM}));"
    )
    contract = _json(subprocess.check_output(["node", "--input-type=module", "-e", code], cwd=root))
    if not isinstance(contract, dict) or set(contract) != {"outputs", "binding_keys", "source", "digest_form"}:
        raise ValueError("Compiler owner exports have an unsupported shape")
    outputs, keys = contract["outputs"], contract["binding_keys"]
    if not isinstance(outputs, list) or len(outputs) != 4 or not isinstance(keys, list) or len(keys) != 7:
        raise ValueError("Compiler family/binding cardinality changed")
    files, paths, output_keys = set(), set(), set()
    for row in outputs:
        if not isinstance(row, dict) or set(row) != {"key", "file", "trackedPath"}:
            raise ValueError("Compiler output export is malformed")
        file = _safe_relative(row["file"])
        tracked = _safe_relative(row["trackedPath"])
        if "/" in file or not file.endswith(".json") or not tracked.startswith("src/"):
            raise ValueError("Compiler member must be a bare JSON name with a tracked source path")
        if not isinstance(row["key"], str) or not row["key"]:
            raise ValueError("Compiler output key is malformed")
        if file.casefold() in files or tracked.casefold() in paths or row["key"] in output_keys:
            raise ValueError("Compiler output exports are ambiguous")
        files.add(file.casefold())
        paths.add(tracked.casefold())
        output_keys.add(row["key"])
    if not all(isinstance(key, str) and key for key in keys) or len(set(keys)) != 7:
        raise ValueError("Compiler binding keys are malformed")
    _safe_relative(contract["source"])
    if contract["digest_form"] != "lf-normalised":
        raise ValueError("Hosted sample binding form changed")
    return contract


def _material_entries(root: Path, paths: tuple[str, ...]) -> dict:
    committed, indexed = {}, {}
    for is_index, data in (
        (False, _git(root, "ls-tree", "-r", "-z", "HEAD", "--", *paths)),
        (True, _git(root, "ls-files", "--stage", "-z", "--", *paths)),
    ):
        selected = indexed if is_index else committed
        for raw in filter(None, data.split(b"\0")):
            try:
                header, path = raw.split(b"\t", 1)
                fields = header.decode("ascii").split(" ")
                if len(fields) != 3:
                    raise ValueError("Git material entry has an unsupported shape")
                mode, second, third = fields
                blob, kind = (second, third) if is_index else (third, second)
                name = _safe_relative(path.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("Git material entry has an unsupported shape") from exc
            if mode not in {"100644", "100755"} or kind != ("0" if is_index else "blob"):
                raise ValueError("Git material must be an ordinary blob at index stage zero")
            if len(blob) not in {40, 64} or any(char not in "0123456789abcdef" for char in blob):
                raise ValueError("Git material has a malformed blob identity")
            if name in selected:
                raise ValueError("Git material entry is ambiguous")
            selected[name] = {"git_mode": mode, "git_blob": blob}
    if committed != indexed:
        raise ValueError("Compiler input index mode/blob differs from HEAD")
    return committed


def _source(root: Path, contract: dict | None = None) -> dict:
    source_path = contract["source"] if contract else "webapp/sample_data/sample_fleet.snapshot.json"
    committed = _material_entries(root, ("atlas-scope", source_path, *PROCESSING_INPUTS))
    if not set(PROCESSING_INPUTS).issubset(committed) or source_path not in committed:
        raise ValueError("Compiler processing/sample inputs are not committed")
    excluded = {"atlas-scope/" + row["trackedPath"] for row in contract["outputs"]} if contract else set()
    if not excluded.issubset(committed):
        raise ValueError("Owner output reference does not name a committed member")
    inputs = {}
    for name in sorted(committed):
        _safe_relative(name)
        if name.startswith("atlas-scope/dist/"):
            continue
        path = root / name
        data = _read(path, MAX_INPUT_BYTES)
        size = int(_git(root, "cat-file", "-s", "HEAD:" + name))
        if size > MAX_INPUT_BYTES:
            raise ValueError("Committed compiler input exceeds bounded read")
        blob = _git(root, "cat-file", "blob", "HEAD:" + name)
        if data != blob:
            raise ValueError("Compiler input differs from committed source")
        if name not in excluded:
            inputs[name] = {**committed[name], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    for ignored in (False, True):
        flags = ("--others", "--exclude-standard", *( ("--ignored",) if ignored else () ))
        for name in filter(None, _git(root, "ls-files", "-z", *flags, "--", "atlas-scope").decode().split("\0")):
            relative = PurePosixPath(name).relative_to("atlas-scope").as_posix()
            generated = next((prefix for prefix in GENERATED_DIRECTORIES if relative.startswith(prefix + "/")), None)
            if generated is None:
                raise ValueError("Untracked/ignored authored compiler input")
            try:
                owner = _git(root, "check-ignore", "-v", "--no-index", "atlas-scope/" + generated + "/handoff-sentinel").decode().split("\t")[0]
            except subprocess.CalledProcessError as exc:
                raise ValueError("Generated input exception has no ignore owner") from exc
            if owner.rsplit(":", 2)[0] not in {".gitignore", "atlas-scope/.gitignore"}:
                raise ValueError("Generated input exception has no tracked ignore owner")
            _directory(root / "atlas-scope" / generated)
    return {"commit": _git(root, "rev-parse", "HEAD").decode().strip(),
            "tree": _git(root, "rev-parse", "HEAD^{tree}").decode().strip(), "inputs": inputs}


def _worktree_roots(root: Path) -> list[Path]:
    raw = _git(root, "worktree", "list", "--porcelain", "-z")
    if not raw.endswith(b"\0"):
        raise ValueError("Git worktree records are not NUL terminated")
    paths = []
    for record in raw.split(b"\0"):
        if record.startswith(b"worktree "):
            path = Path(record[len(b"worktree "):].decode("utf-8", errors="strict"))
            if not path.is_absolute() or path in paths:
                raise ValueError("Git worktree path is relative or ambiguous")
            paths.append(path)
    if not paths:
        raise ValueError("Git worktree list has no managed root")
    return paths


def _boundary(root: Path, output: Path) -> None:
    if not output.is_absolute():
        raise ValueError("Handoff output must be absolute")
    _parents(output)
    if output.exists():
        _directory(output)
    forbidden = _worktree_roots(root)
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        raise ValueError("Git common directory is not absolute")
    forbidden.extend((root, common))
    if any(output.resolve().is_relative_to(path.resolve()) or path.resolve().is_relative_to(output.resolve())
           for path in forbidden):
        raise ValueError("Handoff output must be outside all worktrees and common Git metadata")


def _sample_binding(root: Path, contract: dict) -> dict:
    raw = _read(root / contract["source"], MAX_INPUT_BYTES)
    lf = raw.replace(b"\r\n", b"\n")
    blob = _git(root, "cat-file", "blob", "HEAD:" + contract["source"])
    if lf != blob:
        raise ValueError("Sample LF form differs from its committed Git blob")
    _json(raw)
    git_blob = hashlib.sha1(b"blob " + str(len(lf)).encode("ascii") + b"\0" + lf).hexdigest()
    if _git(root, "rev-parse", "HEAD:" + contract["source"]).decode().strip() != git_blob:
        raise ValueError("Sample Git blob differs from the independent LF preimage")
    binding = {"source": contract["source"], "sourceOrigin": "repository-file",
               "sourceDigestForm": contract["digest_form"], "sourceSha256": hashlib.sha256(lf).hexdigest(),
               "sourceBytes": len(lf), "sourceExactSha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
               "sourceGitBlob": git_blob}
    if set(binding) != set(contract["binding_keys"]):
        raise ValueError("Owner binding keys require a new independent verifier")
    return binding


def _members(root: Path, output: Path, contract: dict, binding: dict) -> dict:
    members_dir = output / "members"
    _directory(members_dir)
    expected = {row["file"] for row in contract["outputs"]}
    if {p.name for p in members_dir.iterdir()} != expected:
        raise ValueError("Compiled member family is not closed")
    import_path = sys.path[:]
    try:
        sys.path.insert(0, str(root))
        from cisco_toolkit.distribution_verify import _client_marker_patterns
    finally:
        # Spawned children inherit sys.path: no temporary checkout may escape this import.
        sys.path[:] = import_path

    patterns = _client_marker_patterns()
    records = {}
    remaining = MAX_TOTAL_BYTES
    for row in contract["outputs"]:
        path = members_dir / row["file"]
        raw = _read(path, min(MAX_MEMBER_BYTES, remaining))
        remaining -= len(raw)
        text = raw.decode("utf-8")
        if any(pattern.search(text) for pattern in patterns):
            raise ValueError("Compiled JSON fails the canonical marker scan")
        parsed = _json(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("meta"), dict):
            raise ValueError("Compiled member has no source metadata")
        if any(type(parsed["meta"].get(key)) is not type(value) or parsed["meta"][key] != value for key, value in binding.items()):
            raise ValueError("Compiled member binding differs from the independent sample binding")
        records[row["file"]] = {"tracked_path": "atlas-scope/" + row["trackedPath"],
                                 "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return records


def _write(path: Path, record: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    _boundary(root, args.output)
    # Refuse altered/uncontrolled inputs before importing any compiler-owner code.
    _source(root)
    contract = _contract(root)
    source = _source(root, contract)
    binding = _sample_binding(root, contract)
    context = {key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "RUNNER_OS")}
    if context["GITHUB_SHA"] != source["commit"]:
        raise ValueError("Selected checkout differs from the hosted context")
    versions = {"node": subprocess.check_output(["node", "--version"]).decode().strip(),
                "npm": subprocess.check_output(["npm", "--version"]).decode().strip(), "python": sys.version}
    tracked_outputs = {}
    tracked_paths = tuple("atlas-scope/" + row["trackedPath"] for row in contract["outputs"])
    tracked_entries = _material_entries(root, tracked_paths)
    for row in contract["outputs"]:
        path = "atlas-scope/" + row["trackedPath"]
        raw = _read(root / path, MAX_INPUT_BYTES)
        tracked_outputs[path] = {**tracked_entries[path], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    before_record = {"schema": "scope_compile_source/1", "source": source, "contract": contract,
                     "tracked_output_before": tracked_outputs,
                     "sample_binding": binding, "context": context, "tool_versions": versions}
    before_path = args.output / "source-before.json"
    if args.phase == "before":
        if _source(root, contract) != source:
            raise ValueError("Compiler source changed during before capture")
        args.output.mkdir(exist_ok=False)
        _write(before_path, before_record)
        return
    if {p.name for p in args.output.iterdir()} != {"source-before.json", "members"}:
        raise ValueError("Handoff directory is not the fresh compiled before-phase family")
    if _json(_read(before_path, MAX_INPUT_BYTES)) != before_record:
        raise ValueError("Compiler source/context/owner binding changed during compilation")
    members = _members(root, args.output, contract, binding)
    if _source(root, contract) != source or _members(root, args.output, contract, binding) != members:
        raise ValueError("Compiler source or member bytes changed during capture")
    record = {**before_record, "schema": "scope_compile_handoff/1",
              "github_head": os.environ.get("PR_HEAD_SHA") or source["commit"],
              "members": members, "status": "GENERATED_INPUT_FOR_REVIEW_ONLY", "release_authority": False,
              "final_source_rebuild_required": True}
    _write(args.output / "handoff.json", record)


if __name__ == "__main__":
    main()
