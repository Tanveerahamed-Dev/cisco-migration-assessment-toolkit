"""Hosted engine-output regeneration handoff: review input only, never release authority.

Under the GitHub-only rule no engine run happens on a workstation, yet any change to a stored
snapshot section moves the tracked engine outputs in OUTPUT_PATHS. This one file owns their closed
set and both ends of the handoff, and every end runs only on a GitHub-hosted runner:

* ``before`` / ``after`` run inside the manual producer workflow WORKFLOW, around the repository's
  own regeneration commands (GOLDEN_COMMAND, SAMPLE_COMMAND). They bind the exact dispatched source
  commit (its every tracked byte and mode, with no hidden index state), refuse any produced set
  other than OUTPUT_PATHS, and write ``manifest.json`` plus ``files/<path>`` for exactly one
  uploaded artifact.
* ``receive`` runs inside the manual receipt workflow RECEIPT_WORKFLOW and refuses to run anywhere
  else. It selects that producer run, job and artifact through the read-only Actions API; checks
  their identities, the archive digest, every raw ZIP member span, a closed member set, the
  manifest's source binding and every member hash; executes the canonical marker policy only from
  admitted Git bytes; and writes ``receipt.json`` plus ``files/<path>`` as review data outside the
  checkout. It never writes to the repository. With ``verify_import`` it instead proves that the
  dispatched commit carries exactly the admitted bytes.

Imported bytes are review input. The committed result must still pass the golden, sample and
Atlas Scope gates on fresh hosted CI; nothing here approves, merges or releases. See
docs/engine-output-handoff.md.
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import hashlib
from importlib.machinery import ModuleSpec
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import stat
import struct
import subprocess
import sys
import types
import zipfile
import zlib

REPO = "Tanveerahamed-Dev/cisco-migration-assessment-toolkit"
WORKFLOW = ".github/workflows/engine-output-handoff.yml"
JOB_NAME = "Regenerate engine outputs for review (manual)"
RUNNER_LABELS = ("ubuntu-24.04",)
ARTIFACT_PREFIX = "engine-output-handoff"
MANIFEST_SCHEMA = "engine_output_handoff/1"
SOURCE_SCHEMA = "engine_output_source/1"
STATUS = "GENERATED_INPUT_FOR_REVIEW_ONLY"
# The engine stamps local time into some outputs (the sample's collected_at offset); the producer
# runs under one canonical zone so that stamp is a property of the handoff, not of a runner image.
CANONICAL_TZ = "UTC"

# The closed output set: every tracked file the two regeneration commands below write. The
# workflow contract test derives the same set from the producers' own write targets and from
# the tracked tests/golden directory, so a new golden or sample file cannot fall outside it.
OUTPUT_PATHS = (
    "tests/golden/sheet_schema.json",
    "tests/golden/snapshot.json",
    "webapp/sample_data/sample_fleet.snapshot.json",
)
# The repository's own regeneration commands, run unchanged by WORKFLOW (UPDATE_GOLDEN=1 for the
# first; ALLOW_GOLDEN_SHRINK only through the explicit dispatch input). The shrink guard in
# tests/test_pipeline_golden.py still applies inside the hosted run.
GOLDEN_COMMAND = (
    "python -m pytest -p no:cacheprovider"
    " tests/test_pipeline_golden.py::test_snapshot_matches_golden"
    " tests/test_pipeline_golden.py::test_excel_sheet_schema_matches_golden"
)
SAMPLE_COMMAND = "python webapp/sample_data/build_sample.py"
# Every named step of the producer job, in order. The receiver requires each to have succeeded;
# the workflow contract test requires this tuple to equal the workflow's named steps.
REQUIRED_STEPS = (
    "Require the dispatched commit to be the expected source",
    "Upgrade the installer",
    "Install complete runtime and test dependencies",
    "Bind the exact source before regeneration",
    "Regenerate the golden snapshot and workbook sheet schema",
    "Regenerate the engine-built sample fleet",
    "Verify privacy and capture the closed output set for review",
    "Preserve the source-bound engine output handoff",
)

# The hosted receipt: the only place `receive` runs. Its named steps are pinned by the workflow
# contract test; its upload is review data, never a write to the repository.
RECEIPT_WORKFLOW = ".github/workflows/engine-output-receipt.yml"
RECEIPT_JOB_NAME = "Receive engine outputs as review data (manual)"
RECEIPT_STEPS = (
    "Receive the selected handoff as review data",
    "Preserve the receipt review data",
)
RECEIPT_PREFIX = "engine-output-receipt"
RECEIPT_DIRECTORY = "engine-output-receipt"
RECEIPT_NAME = "receipt.json"
RECEIPT_SCHEMA = "engine_output_receipt/1"
RECEIPT_STATUS = "ADMITTED_REVIEW_DATA_ONLY"
IMPORT_STATUS = "IMPORT_MATCHES_ADMITTED_BYTES_REVIEW_ONLY"

MANIFEST_NAME = "manifest.json"
FILES_PREFIX = "files/"
EXPECTED_MEMBERS = frozenset({MANIFEST_NAME, *(FILES_PREFIX + path for path in OUTPUT_PATHS)})
# Explicit ZIP directory entries are admitted only when they are parents of an expected member.
ALLOWED_DIRECTORIES = frozenset(
    parent.as_posix()
    for member in EXPECTED_MEMBERS
    for parent in PurePosixPath(member).parents
    if parent.as_posix() != "."
)
MANIFEST_KEYS = frozenset({"schema", "source_commit", "tree", "files", "changed_from_source",
                           "producer", "allow_golden_shrink", "status", "release_authority"})
PRODUCER_KEYS = frozenset({"workflow", "run_id", "run_attempt", "runner_os", "python", "tz"})
FILE_KEYS = frozenset({"path", "sha256", "bytes"})

# The canonical client-marker policy and its exact import closure, executed only from admitted Git
# bytes (bound_marker_policy). These tables equal the reviewed frontend receiver's
# (.github/scripts/frontend_artifact_receive.py), which the contract tests check; a change to the
# closure's imports fails closed until both are reviewed.
MARKER_CLOSURE = (
    ("", "cisco_toolkit/__init__.py"),
    ("registry_integrity", "cisco_toolkit/registry_integrity.py"),
    ("eoldb", "cisco_toolkit/eoldb.py"),
    ("distribution_verify", "cisco_toolkit/distribution_verify.py"),
)
MARKER_IMPORTS = {
    "": {}, "registry_integrity": {},
    "eoldb": {"registry_integrity": frozenset(("MAX_MANIFEST_BYTES", "PackIntegrityError", "SOURCE_INVENTORY_RELATIVE_PATH", "source_freshness"))},
    "distribution_verify": {"registry_integrity": frozenset(("PackIntegrityError", "verify_retained_source_chain")),
                            "eoldb": frozenset(("verify_retained_eol_source_chain",))},
}

MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_API_BYTES = 8 * 1024 * 1024
MAX_GIT_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 32
# The reviewed frontend receiver's expansion bound: generous for JSON, fatal to a ZIP bomb.
MAX_EXPANSION_RATIO = 200
ZIP_ALLOWED_FLAGS = 0x0008 | 0x0800  # data descriptor, UTF-8 member names
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
DIGITS = re.compile(r"[1-9][0-9]{0,15}\Z")
# Between an explicitly named source commit and HEAD only top-level docs/*.md may change: the board
# and dated records. No engine, test or sample code reads them, so they cannot move an output.
DOCUMENTATION_ONLY = re.compile(r"docs/[^/]+\.md\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_DEVICES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                              *(f"lpt{i}" for i in range(1, 10))})
_ZIP_END = struct.Struct("<4s4H2LH")
_ZIP_LOCAL = struct.Struct("<4s5H3L2H")
_ZIP_DESCRIPTOR = struct.Struct("<3L")


class HandoffRefusal(ValueError):
    """A fail-closed refusal: nothing is captured, uploaded or written past this point."""


def need(condition: object, message: str) -> None:
    if not condition:
        raise HandoffRefusal(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_id(data: bytes) -> str:
    """The SHA-1 Git object name of `data` as a blob (what `git hash-object` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def artifact_name(source_commit: str, run_id: object, run_attempt: object) -> str:
    """The one artifact name; the workflow's upload step renders the same pattern."""
    return f"{ARTIFACT_PREFIX}-{source_commit}-{run_id}-{run_attempt}"


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def strict_json(data: bytes, label: str) -> object:
    """UTF-8 JSON without a BOM, duplicate keys or non-finite numbers."""
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(token):
        raise HandoffRefusal(f"{label}: non-finite JSON number {token}")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HandoffRefusal(f"{label}: not UTF-8") from error
    need(not text.startswith("﻿"), f"{label}: carries a byte-order mark")
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise HandoffRefusal(f"{label}: not strict JSON ({error})") from error
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float):
            need(math.isfinite(item), f"{label}: non-finite JSON number")
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


# --------------------------------------------------------------------------- filesystem


def _indirect(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (int(info.st_dev), int(info.st_ino), int(info.st_mode), int(info.st_size), int(info.st_mtime_ns))


def _ordinary_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise HandoffRefusal(f"{path}: missing directory") from error
    need(stat.S_ISDIR(info.st_mode) and not _indirect(info), f"{path}: not an ordinary directory")


def _ordinary_parents(root: Path, relative: str) -> Path:
    """Every directory from root down to the file's parent is ordinary (no link or junction)."""
    target = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        _ordinary_directory(current)
    return target


_READ_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def read_regular(path: Path, maximum: int) -> bytes:
    """One stable, ordinary, singly linked file, read without following links."""
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise HandoffRefusal(f"{path}: missing") from error
    need(stat.S_ISREG(before.st_mode) and not _indirect(before), f"{path}: not an ordinary file")
    need(before.st_nlink == 1, f"{path}: hard-linked file refused")
    need(before.st_size <= maximum, f"{path}: exceeds the bounded size")
    descriptor = os.open(path, _READ_FLAGS)
    try:
        opened = os.fstat(descriptor)
        chunks, total = [], 0
        while total <= maximum:
            block = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        finished = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    data = b"".join(chunks)
    need(len({_identity(before), _identity(opened), _identity(finished), _identity(after)}) == 1
         and len(data) == before.st_size, f"{path}: changed during the bounded read")
    return data


def write_new(path: Path, data: bytes) -> None:
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    descriptor = os.open(path, flags, 0o600)  # owner-only; Git tracks only the executable bit
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            need(written > 0, f"{path}: write stalled")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _outside(path: Path, root: Path) -> bool:
    resolved, base = path.resolve(), root.resolve()
    return not (resolved == base or resolved.is_relative_to(base) or base.is_relative_to(resolved))


def _fresh_external_directory(path: Path, *inside: Path) -> None:
    """An absolute, not yet existing directory whose parent is ordinary and which lies outside `inside`."""
    need(path.is_absolute() and all(_outside(path, other) for other in inside),
         f"{path}: must be absolute and outside the checkout")
    _ordinary_directory(path.parent)
    need(not os.path.lexists(path), f"{path}: must be fresh (it, or a link in its place, already exists)")


# --------------------------------------------------------------------------- git


def git(root: Path, *args: str, ok: tuple[int, ...] = (0,), maximum: int = MAX_GIT_BYTES,
        want_code: bool = False):
    """Run git against `root` only; any exit outside `ok` is a refusal. Returns stdout, or the exit code."""
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off",
         "-C", str(root), *args],
        capture_output=True, timeout=600, check=False,
    )
    need(result.returncode in ok,
         f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()[:400]}")
    need(len(result.stdout) <= maximum, f"git {args[0]} output exceeds its bound")
    return result.returncode if want_code else result.stdout


def _nul_records(raw: bytes, label: str) -> list[bytes]:
    if not raw:
        return []
    need(raw.endswith(b"\0"), f"{label} is not NUL terminated")
    return raw[:-1].split(b"\0")


def _nul_paths(raw: bytes) -> list[str]:
    return [item.decode("utf-8") for item in _nul_records(raw, "git path list")]


def _repository_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HandoffRefusal("Git names a path that is not UTF-8") from error
    parts = path.split("/")
    need(path and "\\" not in path and not path.startswith("/") and "\0" not in path
         and all(part not in ("", ".", "..") for part in parts) and parts[0] != ".git",
         f"Git names an unsafe repository path {path!r}")
    return path


def _ascii_fields(header: bytes, count: int, label: str) -> list[str]:
    try:
        fields = header.decode("ascii").split(" ")
    except UnicodeDecodeError as error:
        raise HandoffRefusal(f"{label} is unreadable") from error
    need(len(fields) == count, f"{label} is unreadable")
    return fields


def checkout_root(root: Path) -> Path:
    need(git(root, "rev-parse", "--show-prefix").strip() == b"", "the handoff must run at the checkout root")
    return root


def commit_of(root: Path, revision: str) -> str:
    # Callers pass only "HEAD" or an already validated 40-character hexadecimal name.
    need(revision == "HEAD" or HEX40.fullmatch(revision), f"unsupported revision {revision!r}")
    value = git(root, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    need(HEX40.fullmatch(value), f"{revision} does not name a full SHA-1 commit")
    return value


def tree_of(root: Path, commit: str) -> str:
    need(HEX40.fullmatch(commit), f"unsupported commit {commit!r}")
    value = git(root, "rev-parse", "--verify", commit + "^{tree}").decode().strip()
    need(HEX40.fullmatch(value), f"{commit} has no readable tree")
    return value


def require_clean_tracked_tree(root: Path) -> None:
    status = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no", "--ignore-submodules=none")
    need(status == b"", "the tracked working tree or index is not clean; commit or restore it first: "
         + ", ".join(entry[3:] for entry in _nul_paths(status)[:12]))


def committed_output(root: Path, commit: str, path: str, maximum: int = MAX_MEMBER_BYTES) -> bytes:
    """One ordinary committed file's bytes, bound to the blob name its tree records."""
    need(HEX40.fullmatch(commit), f"unsupported commit {commit!r}")
    entry = git(root, "ls-tree", "-z", commit, "--", path)
    need(entry.endswith(b"\0") and entry.count(b"\0") == 1, f"{path} is not one committed entry at {commit}")
    header, name = entry[:-1].split(b"\t", 1)
    mode, kind, blob = _ascii_fields(header, 3, f"{path}'s tree entry")
    need(name.decode("utf-8", "replace") == path and mode == "100644" and kind == "blob" and HEX40.fullmatch(blob),
         f"{path} is not an ordinary committed file at {commit}")
    size = int(git(root, "cat-file", "-s", blob).decode().strip())
    need(size <= maximum, f"{path} exceeds the bounded size at {commit}")
    data = git(root, "cat-file", "blob", blob, maximum=maximum)
    need(len(data) == size and git_blob_id(data) == blob, f"{path}: committed blob bytes do not match their name")
    return data


def untracked_census(root: Path) -> list[str]:
    """Every untracked file, ignored ones included (no standard excludes)."""
    return sorted(_nul_paths(git(root, "ls-files", "-z", "--others")))


def _compiled_python(paths: list[str]) -> list[str]:
    """Untracked bytecode can shadow tracked source when the regeneration imports it."""
    return [path for path in paths if path.endswith((".pyc", ".pyo")) or "__pycache__" in path.split("/")]


def _tree_entries(root: Path, commit: str) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in _nul_records(git(root, "ls-tree", "-r", "-z", "--full-tree", commit), "git ls-tree"):
        header, _tab, raw = record.partition(b"\t")
        mode, kind, blob = _ascii_fields(header, 3, "a source tree entry")
        path = _repository_path(raw)
        need(kind == "blob" and mode in ("100644", "100755") and HEX40.fullmatch(blob) and path not in entries,
             f"{path}: not an ordinary committed file (links, submodules and duplicates are refused)")
        entries[path] = (mode, blob)
    need(entries, "the source tree has no files")
    return entries


def _index_entries(root: Path) -> dict[str, tuple[str, str]]:
    """Stage-zero index entries; any assume-unchanged, skip-worktree or other non-cached flag is refused."""
    entries: dict[str, tuple[str, str]] = {}
    for record in _nul_records(git(root, "ls-files", "-s", "-z"), "git ls-files -s"):
        header, _tab, raw = record.partition(b"\t")
        mode, blob, stage = _ascii_fields(header, 3, "an index entry")
        path = _repository_path(raw)
        need(stage == "0" and HEX40.fullmatch(blob) and path not in entries,
             f"{path}: unmerged or duplicate index entry")
        entries[path] = (mode, blob)
    tags: dict[str, bytes] = {}
    for record in _nul_records(git(root, "ls-files", "-v", "-z"), "git ls-files -v"):
        need(len(record) > 2 and record[1:2] == b" ", "the index flags are unreadable")
        tags[_repository_path(record[2:])] = record[:1]
    need(set(tags) == set(entries), "the index flag inventory differs from its stage-zero inventory")
    hidden = sorted(f"{tag.decode('ascii', 'replace')} {path}" for path, tag in tags.items() if tag != b"H")
    need(not hidden, "the Git index hides working-tree state (assume-unchanged, skip-worktree or another "
         "non-cached flag): " + ", ".join(hidden[:12]))
    return entries


def _worktree_blob(root: Path, path: str, mode: str) -> str:
    """The Git blob name of one tracked working-tree file, read without following links."""
    target = _ordinary_parents(root, path)
    try:
        before = target.lstat()
    except FileNotFoundError as error:
        raise HandoffRefusal(f"{path}: missing from the checkout") from error
    need(stat.S_ISREG(before.st_mode) and not _indirect(before), f"{path}: not an ordinary file")
    if os.name != "nt":  # Windows checkouts carry no executable bit to compare.
        need(bool(before.st_mode & 0o111) == (mode == "100755"), f"{path}: executable mode differs from the source")
    hasher = hashlib.sha1(b"blob %d\0" % before.st_size, usedforsecurity=False)
    descriptor = os.open(target, _READ_FLAGS)
    total = 0
    try:
        opened = os.fstat(descriptor)
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            hasher.update(block)
            total += len(block)
        finished = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = target.lstat()
    need(len({_identity(before), _identity(opened), _identity(finished), _identity(after)}) == 1
         and total == before.st_size, f"{path}: changed while it was read")
    return hasher.hexdigest()


def bind_checkout(root: Path, commit: str, *, regenerated: tuple[str, ...] = ()) -> int:
    """HEAD is `commit`, the index is its tree with no hidden flag, and every tracked file's bytes and
    mode equal that tree. Only the bytes of `regenerated` may differ (their kind and mode may not).

    `git status` trusts the index's flags and stat cache; this reads every tracked byte instead.
    """
    need(git(root, "rev-parse", "--show-object-format").strip() == b"sha1",
         "only SHA-1 Git object names are supported")
    need(commit_of(root, "HEAD") == commit, "HEAD is not the bound commit")
    tree = _tree_entries(root, commit)
    need(_index_entries(root) == tree, "the Git index differs from the bound commit's tree")
    mismatched = []
    for path, (mode, blob) in sorted(tree.items()):
        try:
            actual = _worktree_blob(root, path, mode)
        except (HandoffRefusal, OSError) as error:
            mismatched.append(str(error) if isinstance(error, HandoffRefusal) else f"{path}: unreadable ({error.strerror})")
            continue
        if path not in regenerated and actual != blob:
            mismatched.append(f"{path}: bytes differ from the bound commit")
    need(not mismatched, "the checkout's tracked bytes or modes differ from the bound commit: "
         + "; ".join(mismatched[:12]))
    return len(tree)


# --------------------------------------------------------------------------- content policy


@contextlib.contextmanager
def bound_marker_policy(root: Path, commit: str):
    """The canonical marker policy, executed from the admitted Git bytes of its closure at `commit`.

    The import system never supplies it: no sys.path entry, existing canonical module, working-tree
    file or bytecode cache is consulted. Standard-library imports behave normally; the four project
    modules see only each other through their reviewed relative imports. This binds the policy's
    source; it is not a Python sandbox. Yields `_marker_patterns_for`.
    """
    admitted = {path: committed_output(root, commit, path) for _suffix, path in MARKER_CLOSURE}
    prefix = "_engine_handoff_marker_" + secrets.token_hex(16)
    need(not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules),
         "the private marker-policy namespace is not fresh")
    modules: dict[str, types.ModuleType] = {}
    loaded: set[str] = set()
    owned: list[str] = []
    original_import = builtins.__import__

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            caller_name = globals.get("__name__") if type(globals) is dict else None
            caller = next((key for key, module in modules.items()
                           if module.__name__ == caller_name and module.__dict__ is globals), None)
            need(level == 1 and caller in MARKER_IMPORTS and name in MARKER_IMPORTS[caller]
                 and name in loaded and type(fromlist) in (tuple, list) and bool(fromlist)
                 and frozenset(fromlist) == MARKER_IMPORTS[caller][name],
                 "a marker-policy relative import escaped the admitted closure")
            module = modules[name]
            need(all(item in module.__dict__ for item in fromlist), "a bound marker-policy export is missing")
            return module
        need(type(name) is str and name.split(".", 1)[0] in sys.stdlib_module_names,
             f"marker-policy import {name!r} is not standard library; no project or installed fallback")
        return original_import(name, globals, locals, fromlist, 0)

    try:
        for suffix, path in MARKER_CLOSURE:
            name = prefix + ("." + suffix if suffix else "")
            module = types.ModuleType(name)
            module.__file__ = str(root / path)
            module.__package__ = prefix
            module.__spec__ = ModuleSpec(name, loader=None, is_package=not suffix)
            if not suffix:
                module.__path__ = []  # no directory to search for another project module
            module.__builtins__ = {**vars(builtins), "__import__": controlled_import}
            modules[suffix] = module
            sys.modules[name] = module
            owned.append(name)
            try:
                exec(compile(admitted[path], str(root / path), "exec", dont_inherit=True), module.__dict__)
            except HandoffRefusal:
                raise
            except Exception as error:
                raise HandoffRefusal(f"the bound marker policy did not load ({path}: {type(error).__name__})") from error
            loaded.add(suffix)
            if suffix:
                setattr(modules[""], suffix, module)
        policy = modules["distribution_verify"].__dict__.get("_marker_patterns_for")
        need(callable(policy), "the canonical marker policy is missing")
        yield policy
    finally:
        # Only this invocation's private names are removed; canonical cisco_toolkit modules, sys.path
        # and unrelated modules are never touched.
        for name in reversed(owned):
            sys.modules.pop(name, None)


@contextlib.contextmanager
def _marker_policy(root: Path, commit: str, injected):
    if injected is not None:
        yield injected
    else:
        with bound_marker_policy(root, commit) as policy:
            yield policy


def check_output_bytes(path: str, data: bytes, patterns_for) -> None:
    """Bounded, LF-only, strict-JSON object text that passes the canonical marker scan."""
    need(path in OUTPUT_PATHS, f"{path} is not a handoff output")
    need(0 < len(data) <= MAX_MEMBER_BYTES, f"{path}: empty or oversized")
    need(b"\r" not in data, f"{path}: carries CR bytes; the tracked outputs are LF-only")
    value = strict_json(data, path)
    need(isinstance(value, dict) and value, f"{path}: not a non-empty JSON object")
    text = data.decode("utf-8")
    need(not any(pattern.search(text) for pattern in patterns_for(path)),
         f"{path}: fails the canonical client-marker scan")


# --------------------------------------------------------------------------- producer (hosted)


def producer_environment(environ=None) -> dict:
    env = os.environ if environ is None else environ
    need(env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_ENVIRONMENT") == "github-hosted",
         "the producer phases run only on a GitHub-hosted runner")
    need(env.get("RUNNER_OS") == "Linux", "the producer phases run only on the Linux image")
    need(env.get("TZ") == CANONICAL_TZ, f"the producer requires TZ={CANONICAL_TZ}")
    python = platform.python_version()
    need(python.startswith("3.12."), "the producer runs only on the reviewed Python 3.12 profile")
    expected = env.get("EXPECTED_SOURCE_COMMIT", "")
    need(HEX40.fullmatch(expected), "EXPECTED_SOURCE_COMMIT must be a full lowercase 40-character commit")
    need(env.get("GITHUB_SHA") == expected, "the dispatched commit is not the expected source commit")
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    need(DIGITS.fullmatch(run_id) and DIGITS.fullmatch(attempt), "the hosted run identity is incomplete")
    return {"expected": expected, "run_id": run_id, "run_attempt": attempt, "python": python}


def bind_source(root: Path, expected: str) -> dict:
    head = commit_of(root, "HEAD")
    need(head == expected, "the checkout is not the expected source commit")
    require_clean_tracked_tree(root)
    bind_checkout(root, head)
    outputs = {}
    for path in OUTPUT_PATHS:
        committed = committed_output(root, head, path)
        on_disk = read_regular(_ordinary_parents(root, path), MAX_MEMBER_BYTES)
        need(on_disk == committed, f"{path}: checkout bytes differ from the committed source")
        outputs[path] = {"sha256": digest(committed), "bytes": len(committed)}
    return {"source_commit": head, "tree": tree_of(root, head), "outputs": outputs}


def phase_before(root: Path, state: Path, environ=None) -> dict:
    env = producer_environment(environ)
    need(state.is_absolute() and _outside(state, root), "the state directory must be absolute and outside the checkout")
    need(not os.path.lexists(state), "the state directory must be fresh")
    bound = bind_source(root, env["expected"])
    census = untracked_census(root)
    shadowing = _compiled_python(census)
    need(not shadowing, "untracked compiled Python in the checkout could shadow the bound source: "
         + ", ".join(shadowing[:12]))
    record = {"schema": SOURCE_SCHEMA, **bound, "untracked": census}
    state.mkdir()
    write_new(state / "source-before.json", canonical_json(record))
    return record


def _tracked_changes(root: Path) -> tuple[list[str], list[str]]:
    staged = _nul_paths(git(root, "diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"))
    worktree = _nul_paths(git(root, "diff", "--no-renames", "--name-only", "-z", "HEAD", "--"))
    return sorted(staged), sorted(worktree)


def _closed_effect(root: Path, before: dict) -> list[str]:
    """The regeneration's whole effect on the checkout is a change to OUTPUT_PATHS, nothing else."""
    need(commit_of(root, "HEAD") == before["source_commit"], "HEAD moved during regeneration")
    need(tree_of(root, before["source_commit"]) == before["tree"], "the source tree changed during regeneration")
    staged, changed = _tracked_changes(root)
    need(not staged, "regeneration staged changes: " + ", ".join(staged[:12]))
    extra = sorted(set(changed) - set(OUTPUT_PATHS))
    need(not extra, "regeneration changed tracked files outside the closed output set: " + ", ".join(extra[:12]))
    # git diff trusts the index; every other tracked input's bytes and mode are re-read here.
    bind_checkout(root, before["source_commit"], regenerated=OUTPUT_PATHS)
    census = untracked_census(root)
    appeared = sorted(set(census) - set(before["untracked"]))
    vanished = sorted(set(before["untracked"]) - set(census))
    need(not appeared and not vanished, "regeneration changed the untracked file set: appeared "
         + ", ".join(appeared[:12]) + "; vanished " + ", ".join(vanished[:12]))
    return changed


def phase_after(root: Path, state: Path, output: Path, environ=None, patterns_for=None) -> dict:
    env = os.environ if environ is None else environ
    context = producer_environment(env)
    shrink_text = env.get("ALLOW_GOLDEN_SHRINK_INPUT", "")
    need(shrink_text in ("true", "false"), "ALLOW_GOLDEN_SHRINK_INPUT must be the dispatch input's true or false")
    need(state.is_absolute() and _outside(state, root), "the state directory must be absolute and outside the checkout")
    _ordinary_directory(state)
    need(sorted(entry.name for entry in state.iterdir()) == ["source-before.json"],
         "the state directory is not the fresh before-phase record")
    before = strict_json(read_regular(state / "source-before.json", MAX_API_BYTES), "source-before.json")
    need(isinstance(before, dict) and before.get("schema") == SOURCE_SCHEMA
         and set(before) == {"schema", "source_commit", "tree", "outputs", "untracked"},
         "the before-phase record has an unsupported shape")
    need(before["source_commit"] == context["expected"], "the before-phase record names another source")
    need(output.is_absolute() and _outside(output, root) and _outside(output, state),
         "the handoff output must be absolute and outside the checkout and state")
    need(not os.path.lexists(output), "the handoff output directory must be fresh")

    changed = _closed_effect(root, before)
    produced = {}
    with _marker_policy(root, before["source_commit"], patterns_for) as policy:
        for path in OUTPUT_PATHS:
            data = read_regular(_ordinary_parents(root, path), MAX_MEMBER_BYTES)
            check_output_bytes(path, data, policy)
            produced[path] = data
    need(sum(len(data) for data in produced.values()) <= MAX_TOTAL_BYTES, "the output set exceeds its bound")
    differs = sorted(path for path in OUTPUT_PATHS if digest(produced[path]) != before["outputs"][path]["sha256"])
    need(differs == changed, "git's changed-file census disagrees with the produced bytes")

    output.mkdir()
    for path, data in produced.items():
        target = output.joinpath(*PurePosixPath(FILES_PREFIX + path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new(target, data)
        need(read_regular(target, MAX_MEMBER_BYTES) == data, f"{path}: captured copy differs")
    # The source and every produced file are still exactly what was captured.
    need(_closed_effect(root, before) == changed, "the checkout changed during capture")
    for path in OUTPUT_PATHS:
        need(read_regular(_ordinary_parents(root, path), MAX_MEMBER_BYTES) == produced[path],
             f"{path} changed during capture")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source_commit": before["source_commit"],
        "tree": before["tree"],
        "files": [{"path": path, "sha256": digest(produced[path]), "bytes": len(produced[path])}
                  for path in OUTPUT_PATHS],
        "changed_from_source": differs,
        "producer": {"workflow": WORKFLOW, "run_id": context["run_id"], "run_attempt": context["run_attempt"],
                     "runner_os": "Linux", "python": context["python"], "tz": CANONICAL_TZ},
        "allow_golden_shrink": shrink_text == "true",
        "status": STATUS,
        "release_authority": False,
    }
    write_new(output / MANIFEST_NAME, canonical_json(manifest))
    return manifest


# --------------------------------------------------------------------------- archive admission


def safe_member_name(name: object) -> str:
    need(isinstance(name, str) and 0 < len(name) <= 240 and name.isascii(), f"unsafe member name {name!r}")
    need(not name.startswith("/") and "\\" not in name and ":" not in name and "\x00" not in name,
         f"absolute or ambiguous member name {name!r}")
    parts = name.split("/")
    need(all(_SEGMENT.fullmatch(part) for part in parts), f"unsafe member path segment in {name!r}")
    need(all(not part.endswith((".", " ")) and part.split(".")[0].lower() not in _WINDOWS_DEVICES
             for part in parts), f"Windows alias in member name {name!r}")
    return name


def member_bytes(span: bytes, method: int, declared_size: int, declared_crc: int, name: str) -> bytes:
    """Decode one member's exact raw compressed span to its actual bytes.

    zipfile's reader stops at the DECLARED expanded size, which is not codec end-of-stream: a longer
    STORED body, a DEFLATE stream that expands further, trailing bytes or a second stream would
    hide behind a CRC computed over the accepted prefix. The span must expand to exactly the
    declared size, reach end-of-stream, consume every compressed byte, and match the CRC.
    """
    if method == zipfile.ZIP_STORED:
        need(len(span) == declared_size, f"member {name!r}: STORED compressed and expanded sizes differ")
        contents = span
    else:
        need(method == zipfile.ZIP_DEFLATED, f"member {name!r} uses an unsupported compression")
        decoder = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            # One byte beyond the declaration detects concealed expansion and bounds the allocation.
            contents = decoder.decompress(span, declared_size + 1)
        except zlib.error as error:
            raise HandoffRefusal(f"member {name!r} is not one valid raw DEFLATE stream") from error
        need(len(contents) == declared_size, f"member {name!r}: actual expansion differs from its declared size")
        need(decoder.eof and decoder.unused_data == b"" and decoder.unconsumed_tail == b"",
             f"member {name!r}: the compressed span is truncated, trailing or holds another stream")
    need(zlib.crc32(contents) & 0xFFFFFFFF == declared_crc, f"member {name!r} fails its CRC")
    return contents


def _plain_extra(extra: bytes, name: str) -> None:
    offset = 0
    while offset < len(extra):
        need(offset + 4 <= len(extra), f"member {name!r}: malformed ZIP extra field")
        tag, length = struct.unpack_from("<2H", extra, offset)
        need(tag != 0x0001 and offset + 4 + length <= len(extra), f"member {name!r}: ZIP64 or malformed extra field")
        offset += 4 + length


def zip_members(data: bytes) -> dict[str, bytes]:
    """Every regular member of a bounded, unencrypted ZIP, decoded from its exact raw span.

    The end record must be the archive's last 22 bytes (no comment, suffix or multi-disk), the
    central directory must abut it, and the member records must tile everything before it with no
    prefix, gap or overlap. Local and central headers must agree; ZIP64, encryption, unsupported
    flags or compression, links, aliases and special files are refused.
    """
    need(22 <= len(data) <= MAX_ARCHIVE_BYTES, "the artifact archive size is out of bounds")
    end = _ZIP_END.unpack_from(data, len(data) - 22)
    member_area = end[6]
    need(end[0] == b"PK\x05\x06" and end[1:3] == (0, 0) and end[3] == end[4] and end[7] == 0
         and end[5] + end[6] == len(data) - 22,
         "the artifact is not a ZIP archive with one exact end record (no comment, prefix, suffix or multi-disk)")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError, OSError, struct.error, UnicodeDecodeError) as error:
        raise HandoffRefusal("the artifact is not a ZIP archive") from error
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    spans: list[tuple[int, int]] = []
    total = 0
    with archive:
        entries = archive.infolist()
        need(0 < len(entries) <= MAX_ZIP_ENTRIES and len(entries) == end[4],
             "the artifact member census is out of bounds")
        for entry in entries:
            raw = entry.filename
            need(entry.orig_filename == raw, f"member name {entry.orig_filename!r} was rewritten by the reader")
            directory = raw.endswith("/")
            name = safe_member_name(raw[:-1] if directory else raw)
            need(name.casefold() not in seen, f"duplicate or case-aliased member {name!r}")
            seen.add(name.casefold())
            kind = stat.S_IFMT(entry.external_attr >> 16)
            need(entry.flag_bits & 0x1 == 0, f"encrypted member {name!r}")
            need(entry.flag_bits & ~ZIP_ALLOWED_FLAGS == 0, f"member {name!r} uses unsupported ZIP flags")
            if directory:
                need(kind in (0, stat.S_IFDIR) and entry.file_size == 0, f"directory member {name!r} carries data")
                need(name in ALLOWED_DIRECTORIES, f"unexpected directory member {name!r}")
            else:
                need(kind in (0, stat.S_IFREG), f"member {name!r} is a link or special file")
            need(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                 f"member {name!r} uses an unsupported compression")
            need(0 <= entry.file_size <= MAX_MEMBER_BYTES and total + entry.file_size <= MAX_TOTAL_BYTES,
                 f"member {name!r} exceeds the expanded-size bound")
            need(0 <= entry.compress_size <= MAX_ARCHIVE_BYTES
                 and entry.file_size <= max(1024 * 1024, entry.compress_size * MAX_EXPANSION_RATIO),
                 f"member {name!r} exceeds the expansion-ratio bound")
            start = entry.header_offset
            need(0 <= start <= member_area - _ZIP_LOCAL.size, f"member {name!r}: local header outside the member area")
            local = _ZIP_LOCAL.unpack_from(data, start)
            need(local[0] == b"PK\x03\x04" and local[2] == entry.flag_bits and local[3] == entry.compress_type,
                 f"member {name!r}: local and central headers disagree")
            name_end = start + _ZIP_LOCAL.size + local[9]
            body = name_end + local[10]
            need(body <= member_area, f"member {name!r}: local header overruns the member area")
            try:
                local_name = data[start + _ZIP_LOCAL.size:name_end].decode(
                    "utf-8" if entry.flag_bits & 0x800 else "cp437")
            except UnicodeDecodeError as error:
                raise HandoffRefusal(f"member {name!r}: unreadable local name") from error
            need(local_name == raw, f"member {name!r}: local and central names disagree")
            _plain_extra(entry.extra, name)
            _plain_extra(data[name_end:body], name)
            finish = body + entry.compress_size
            need(finish <= member_area, f"member {name!r}: data overlaps the central directory")
            if entry.flag_bits & 0x8:
                if data[finish:finish + 4] == b"PK\x07\x08":
                    finish += 4
                need(finish + _ZIP_DESCRIPTOR.size <= member_area
                     and _ZIP_DESCRIPTOR.unpack_from(data, finish) == (entry.CRC, entry.compress_size, entry.file_size),
                     f"member {name!r}: data descriptor missing or disagrees with the central directory")
                finish += _ZIP_DESCRIPTOR.size
            else:
                need(local[6:9] == (entry.CRC, entry.compress_size, entry.file_size),
                     f"member {name!r}: local sizes or CRC disagree with the central directory")
            spans.append((start, finish))
            contents = member_bytes(data[body:body + entry.compress_size], entry.compress_type,
                                    entry.file_size, entry.CRC, name)
            if directory:
                continue
            total += len(contents)
            files[name] = contents
    at = 0
    for start, finish in sorted(spans):
        need(start == at, "the archive's member records overlap, leave a gap or follow a prefix")
        at = finish
    need(at == member_area, "the archive carries unexplained bytes before its central directory")
    return files


def require_closed_members(files: dict[str, bytes]) -> None:
    missing = sorted(EXPECTED_MEMBERS - set(files))
    unexpected = sorted(set(files) - EXPECTED_MEMBERS)
    need(not missing and not unexpected, "the artifact is not the closed handoff member set: missing "
         + (", ".join(missing) or "none") + "; unexpected " + (", ".join(unexpected) or "none"))


def admit_manifest(manifest: object, *, source_commit: str, tree: str, run_id: int, run_attempt: int,
                   allow_golden_shrink: bool) -> dict:
    need(isinstance(manifest, dict) and set(manifest) == MANIFEST_KEYS, "the manifest keys are not the closed set")
    need(manifest["schema"] == MANIFEST_SCHEMA, "unknown manifest schema")
    need(manifest["status"] == STATUS and manifest["release_authority"] is False, "the manifest claims promotion")
    need(manifest["source_commit"] == source_commit, "the manifest's source commit is not the expected source commit")
    need(manifest["tree"] == tree, "the manifest's tree is not the source commit's tree")
    producer = manifest["producer"]
    need(isinstance(producer, dict) and set(producer) == PRODUCER_KEYS, "the producer record keys are not closed")
    need(producer["workflow"] == WORKFLOW and producer["run_id"] == str(run_id)
         and producer["run_attempt"] == str(run_attempt), "the producer record names another run")
    need(producer["runner_os"] == "Linux" and producer["tz"] == CANONICAL_TZ
         and isinstance(producer["python"], str) and producer["python"].startswith("3.12."),
         "the producer ran outside the reviewed Linux/UTC/Python 3.12 profile")
    need(type(manifest["allow_golden_shrink"]) is bool, "allow_golden_shrink must be a boolean")
    need(not manifest["allow_golden_shrink"] or allow_golden_shrink,
         "this handoff removed golden contract surface under ALLOW_GOLDEN_SHRINK; review the removal "
         "and dispatch the receipt with allow_golden_shrink to accept it explicitly")
    rows = manifest["files"]
    need(isinstance(rows, list) and all(isinstance(row, dict) and set(row) == FILE_KEYS for row in rows),
         "the manifest file records are not closed")
    need([row["path"] for row in rows] == list(OUTPUT_PATHS), "the manifest file list is not the closed output set")
    for row in rows:
        need(isinstance(row["sha256"], str) and HEX64.fullmatch(row["sha256"])
             and type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_MEMBER_BYTES,
             f"{row['path']}: malformed manifest digest or size")
    changed = manifest["changed_from_source"]
    need(isinstance(changed, list) and all(isinstance(path, str) for path in changed)
         and changed == sorted(set(changed)) and set(changed) <= set(OUTPUT_PATHS),
         "changed_from_source is not a sorted subset of the output set")
    return {row["path"]: row for row in rows}


def admit_outputs(files: dict[str, bytes], rows: dict, patterns_for) -> dict[str, bytes]:
    admitted = {}
    for path in OUTPUT_PATHS:
        data = files[FILES_PREFIX + path]
        need(len(data) == rows[path]["bytes"] and digest(data) == rows[path]["sha256"],
             f"{path}: bytes differ from the manifest's size or SHA-256")
        check_output_bytes(path, data, patterns_for)
        admitted[path] = data
    return admitted


def _descendant_drift(root: Path, source: str, head: str, label: str) -> list[str]:
    need(commit_of(root, source) == source, f"{label} is not a commit in this checkout")
    # merge-base --is-ancestor answers 0 (ancestor) or 1 (not); anything else is a git failure.
    is_ancestor = git(root, "merge-base", "--is-ancestor", source, head, ok=(0, 1), want_code=True)
    need(is_ancestor == 0, f"{label} is not an ancestor of the dispatched commit")
    return sorted(_nul_paths(git(root, "diff", "--no-renames", "--name-only", "-z", source, head, "--")))


def resolve_source(root: Path, head: str, requested: str | None) -> tuple[str, list[str]]:
    """HEAD by default; a named ancestor only when the commits after it touch top-level docs/*.md alone."""
    if requested is None:
        return head, []
    need(isinstance(requested, str) and HEX40.fullmatch(requested), "the source commit must be a full 40-character commit")
    if requested == head:
        return head, []
    between = _descendant_drift(root, requested, head, "the source commit")
    outside = sorted(path for path in between if not DOCUMENTATION_ONLY.fullmatch(path))
    need(not outside, "commits after the source change more than top-level docs/*.md: " + ", ".join(outside[:12]))
    return requested, between


def resolve_import(root: Path, head: str, requested: str) -> tuple[str, list[str]]:
    """An import commit descends from the source and changes only OUTPUT_PATHS and top-level docs/*.md."""
    need(isinstance(requested, str) and HEX40.fullmatch(requested), "the source commit must be a full 40-character commit")
    need(requested != head, "verify_import needs the import commit, a descendant of the source commit")
    between = _descendant_drift(root, requested, head, "the source commit")
    outside = sorted(path for path in between if path not in OUTPUT_PATHS and not DOCUMENTATION_ONLY.fullmatch(path))
    need(not outside, "the import changes more than the closed output set and top-level docs/*.md: "
         + ", ".join(outside[:12]))
    return requested, between


class GitHubCLI:
    """Read-only GitHub REST calls through the authenticated `gh` CLI."""

    def __init__(self, executable: str = "gh"):
        self.executable = executable

    def _run(self, arguments: list[str], maximum: int) -> bytes:
        result = subprocess.run([self.executable, "api", *arguments], capture_output=True, timeout=900, check=False)
        need(result.returncode == 0,
             f"gh api {arguments[-1]} failed: {result.stderr.decode('utf-8', 'replace').strip()[:400]}")
        need(len(result.stdout) <= maximum, f"gh api {arguments[-1]} exceeded its bound")
        return result.stdout

    def json(self, endpoint: str) -> object:
        raw = self._run(["-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28",
                         endpoint], MAX_API_BYTES)
        return strict_json(raw, f"GitHub API {endpoint}")

    def bytes(self, endpoint: str, maximum: int) -> bytes:
        return self._run([endpoint], maximum)


def check_run(run: object, run_id: int, source_commit: str) -> int:
    need(isinstance(run, dict) and run.get("id") == run_id, "the run record is not the requested run")
    need(run.get("path") == WORKFLOW, "the run is not the engine-output handoff workflow")
    need(run.get("event") == "workflow_dispatch", "the run was not a manual dispatch")
    need(run.get("status") == "completed" and run.get("conclusion") == "success", "the run did not complete successfully")
    need(run.get("head_sha") == source_commit, "the run's commit is not the expected source commit")
    for key in ("repository", "head_repository"):
        need(isinstance(run.get(key), dict) and run[key].get("full_name") == REPO, "the run belongs to another repository")
    attempt = run.get("run_attempt")
    need(type(attempt) is int and 0 < attempt < 2**31, "the run attempt is malformed")
    return attempt


def check_job(listing: object, run_id: int, run_attempt: int, source_commit: str) -> None:
    need(isinstance(listing, dict) and isinstance(listing.get("jobs"), list)
         and listing.get("total_count") == len(listing["jobs"]), "the job listing is incomplete")
    jobs = listing["jobs"]
    need(len(jobs) == 1 and isinstance(jobs[0], dict), "the run does not have exactly one job")
    job = jobs[0]
    need(job.get("name") == JOB_NAME and job.get("run_id") == run_id and job.get("run_attempt") == run_attempt
         and job.get("head_sha") == source_commit, "the job is not this run's regeneration job")
    need(job.get("status") == "completed" and job.get("conclusion") == "success", "the regeneration job did not succeed")
    need(job.get("labels") == list(RUNNER_LABELS) and job.get("runner_group_name") == "GitHub Actions",
         "the job did not run on the GitHub-hosted ubuntu-24.04 image")
    steps = job.get("steps")
    need(isinstance(steps, list) and all(isinstance(step, dict) for step in steps), "the job's steps are unreadable")
    for name in REQUIRED_STEPS:
        rows = [step for step in steps if step.get("name") == name]
        need(len(rows) == 1 and rows[0].get("status") == "completed" and rows[0].get("conclusion") == "success",
             f"required step did not succeed: {name}")


def select_artifact(listing: object, run_id: int, run_attempt: int, source_commit: str) -> dict:
    need(isinstance(listing, dict) and isinstance(listing.get("artifacts"), list)
         and listing.get("total_count") == len(listing["artifacts"]), "the artifact listing is incomplete")
    name = artifact_name(source_commit, run_id, run_attempt)
    matches = [item for item in listing["artifacts"] if isinstance(item, dict) and item.get("name") == name]
    need(len(matches) == 1, f"expected exactly one artifact named {name}")
    item = matches[0]
    need(type(item.get("id")) is int and item["id"] > 0, "the artifact id is malformed")
    need(item.get("expired") is False, "the artifact has expired; dispatch the workflow again")
    size = item.get("size_in_bytes")
    need(type(size) is int and 0 < size <= MAX_ARCHIVE_BYTES, "the artifact size is out of bounds")
    declared = item.get("digest")
    need(isinstance(declared, str) and declared.startswith("sha256:") and HEX64.fullmatch(declared[7:]),
         "the artifact has no SHA-256 digest")
    origin = item.get("workflow_run")
    need(isinstance(origin, dict) and origin.get("id") == run_id and origin.get("head_sha") == source_commit,
         "the artifact was not produced by this run at the expected source commit")
    return {"id": item["id"], "name": name, "size": size, "sha256": declared[7:]}


def _top_level_drift(old: bytes, new: bytes, label: str) -> list[str] | None:
    try:
        before, after = strict_json(old, label), strict_json(new, label)
    except HandoffRefusal:
        return None
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    missing = object()
    return sorted(key for key in set(before) | set(after) if before.get(key, missing) != after.get(key, missing))


# --------------------------------------------------------------------------- receiver (hosted)


def receiver_environment(environ=None) -> dict:
    """The receipt runs only as the dispatched receipt workflow on a GitHub-hosted Linux runner.

    Local execution, a dry run included, is refused before any Git, API or archive operation. Every
    input arrives through the workflow's environment; the command line takes no path, URL or option.
    """
    env = os.environ if environ is None else environ
    need(env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_ENVIRONMENT") == "github-hosted",
         "the receiver runs only on a GitHub-hosted runner; local execution (a dry run included) is refused")
    need(env.get("RUNNER_OS") == "Linux", "the receiver runs only on the Linux image")
    need(platform.python_version().startswith("3.12."), "the receiver runs only on the reviewed Python 3.12 profile")
    need(env.get("GITHUB_REPOSITORY") == REPO, "the receiver runs only in the project repository")
    need(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "the receiver runs only as a manual dispatch")
    need(env.get("GITHUB_WORKFLOW_REF", "").startswith(f"{REPO}/{RECEIPT_WORKFLOW}@"),
         "the receiver runs only from the receipt workflow")
    github_sha = env.get("GITHUB_SHA", "")
    need(HEX40.fullmatch(github_sha), "the dispatched receiver commit is incomplete")
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    need(DIGITS.fullmatch(run_id) and DIGITS.fullmatch(attempt), "the hosted run identity is incomplete")
    producer = env.get("HANDOFF_RUN_ID", "")
    need(DIGITS.fullmatch(producer) and int(producer) < 2**53, "producer_run_id must be a positive run number")
    source = env.get("HANDOFF_SOURCE_COMMIT", "")
    need(HEX40.fullmatch(source), "source_commit must be a full lowercase 40-character commit")
    shrink, verify = env.get("ALLOW_GOLDEN_SHRINK_INPUT", ""), env.get("VERIFY_IMPORT_INPUT", "")
    need(shrink in ("true", "false") and verify in ("true", "false"),
         "allow_golden_shrink and verify_import must be the dispatch inputs' true or false")
    temp = env.get("RUNNER_TEMP", "")
    need(temp and Path(temp).is_absolute(), "RUNNER_TEMP must be an absolute runner directory")
    return {"github_sha": github_sha, "run_id": run_id, "run_attempt": attempt, "producer_run_id": int(producer),
            "source": source, "allow_golden_shrink": shrink == "true", "verify_import": verify == "true",
            "output": Path(temp) / RECEIPT_DIRECTORY}


def _write_review_data(output: Path, receipt: dict, admitted: dict[str, bytes] | None) -> None:
    output.mkdir(mode=0o700)
    for path, data in (admitted or {}).items():
        target = output.joinpath(*PurePosixPath(FILES_PREFIX + path).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_new(target, data)
        need(read_regular(target, MAX_MEMBER_BYTES) == data, f"{path}: the review copy differs")
    write_new(output / RECEIPT_NAME, canonical_json(receipt))


def receive(root: Path, *, environ=None, api=None, patterns_for=None, out=print) -> dict:
    """Admit one producer artifact as review data, or verify an import of it; never write the checkout."""
    context = receiver_environment(environ)
    checkout_root(root)
    head = commit_of(root, "HEAD")
    need(head == context["github_sha"], "the checkout is not the dispatched receiver commit")
    output = context["output"]
    _fresh_external_directory(output, root)
    require_clean_tracked_tree(root)
    bind_checkout(root, head)
    verify_import = context["verify_import"]
    if verify_import:
        source, between = resolve_import(root, head, context["source"])
    else:
        source, between = resolve_source(root, head, context["source"])
    tree = tree_of(root, source)
    run_id = context["producer_run_id"]
    api = GitHubCLI() if api is None else api

    run = api.json(f"repos/{REPO}/actions/runs/{run_id}")
    attempt = check_run(run, run_id, source)
    check_job(api.json(f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"),
              run_id, attempt, source)
    artifact = select_artifact(api.json(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100"),
                               run_id, attempt, source)
    archive = api.bytes(f"repos/{REPO}/actions/artifacts/{artifact['id']}/zip", artifact["size"])
    need(len(archive) == artifact["size"] and digest(archive) == artifact["sha256"],
         "the downloaded archive differs from the artifact's recorded size or SHA-256")

    files = zip_members(archive)
    require_closed_members(files)
    manifest = strict_json(files[MANIFEST_NAME], MANIFEST_NAME)
    rows = admit_manifest(manifest, source_commit=source, tree=tree, run_id=run_id, run_attempt=attempt,
                          allow_golden_shrink=context["allow_golden_shrink"])
    with _marker_policy(root, head, patterns_for) as policy:
        admitted = admit_outputs(files, rows, policy)
    at_source = {path: committed_output(root, source, path) for path in OUTPUT_PATHS}
    from_source = sorted(path for path in OUTPUT_PATHS if at_source[path] != admitted[path])
    need(from_source == manifest["changed_from_source"],
         "the manifest's changed_from_source disagrees with this checkout's source commit")

    report = []
    for path in OUTPUT_PATHS:
        row = {"path": path, "bytes": len(admitted[path]), "sha256": digest(admitted[path]),
               "git_blob": git_blob_id(admitted[path]), "identical_to_source": at_source[path] == admitted[path]}
        if not row["identical_to_source"]:
            row["changed_top_level_keys"] = _top_level_drift(at_source[path], admitted[path], path)
        if verify_import:
            imported = committed_output(root, head, path)
            need(imported == admitted[path] or imported == at_source[path],
                 f"{path}: the import commit carries bytes that are neither the admitted output nor the source's")
            row["at_import"] = "admitted" if imported == admitted[path] else "source"
        report.append(row)

    # The checkout is still exactly the dispatched commit before anything is recorded.
    need(commit_of(root, "HEAD") == head, "HEAD moved during the receipt")
    require_clean_tracked_tree(root)
    bind_checkout(root, head)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": IMPORT_STATUS if verify_import else RECEIPT_STATUS,
        "mode": "verify-import" if verify_import else "receipt",
        "producer": {"workflow": WORKFLOW, "run_id": run_id, "run_attempt": attempt, "artifact_id": artifact["id"],
                     "artifact": artifact["name"], "archive_sha256": artifact["sha256"], "archive_bytes": artifact["size"]},
        "source_commit": source,
        "tree": tree,
        "receiver": {"workflow": RECEIPT_WORKFLOW, "commit": head, "run_id": context["run_id"],
                     "run_attempt": context["run_attempt"]},
        "commits_after_source_touch": between,
        "allow_golden_shrink": manifest["allow_golden_shrink"],
        "outputs": report,
        "acceptance": False,
        "release_authority": False,
    }
    _write_review_data(output, receipt, None if verify_import else admitted)

    out(f"ADMITTED {artifact['name']} (archive sha256 {artifact['sha256']})")
    out(f"source {source} tree {tree}" + ("" if source == head else
                                          f"; {head} differs only in: {', '.join(between) or 'no paths'}"))
    if manifest["allow_golden_shrink"]:
        out("WARNING: produced under ALLOW_GOLDEN_SHRINK=1; the golden contract may have lost surface")
    for row in report:
        state = "identical to the source" if row["identical_to_source"] else (
            "changed; top-level keys: " + (", ".join(row["changed_top_level_keys"])
                                           if row["changed_top_level_keys"] is not None else "unparseable at the source"))
        if verify_import:
            state += f"; the import commit carries the {row['at_import']} bytes"
        out(f"  {row['path']}: {row['bytes']} bytes, git blob {row['git_blob']}, {state}")
    out(f"{receipt['status']}: review data only. Nothing here approves, merges or releases; the hosted golden, "
        "sample and Atlas Scope gates on the committed result decide.")
    return receipt


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hosted engine-output regeneration handoff (review input only).")
    commands = parser.add_subparsers(dest="command", required=True)
    before = commands.add_parser("before", help="hosted producer: bind the exact source before regeneration")
    before.add_argument("--state", type=Path, required=True)
    after = commands.add_parser("after", help="hosted producer: capture the closed output set after regeneration")
    after.add_argument("--state", type=Path, required=True)
    after.add_argument("--output", type=Path, required=True)
    commands.add_parser("receive", help="hosted receipt workflow only: admit one producer artifact as review "
                                        "data (inputs come from the workflow environment)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2] if root is None else root
    try:
        if args.command == "before":
            phase_before(checkout_root(root), args.state)
        elif args.command == "after":
            phase_after(checkout_root(root), args.state, args.output)
        else:
            receive(root)
    except HandoffRefusal as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
