"""Hosted engine-output regeneration handoff: review input only, never release authority.

Under the GitHub-only rule no engine run happens on a workstation, yet any change to a stored
snapshot section moves the tracked engine outputs in OUTPUT_PATHS. This one file owns their closed
set and both ends of the handoff:

* ``before`` / ``after`` run inside the manual GitHub-hosted workflow WORKFLOW, around the
  repository's own regeneration commands (GOLDEN_COMMAND, SAMPLE_COMMAND). They bind the exact
  dispatched source commit, refuse any produced set other than OUTPUT_PATHS, and write
  ``manifest.json`` plus ``files/<path>`` for exactly one uploaded artifact.
* ``receive`` runs in a clean local checkout. It selects that run, job and artifact through
  ``gh api``; checks their identities, the archive digest, a closed ZIP member set, the manifest's
  source binding and every member hash; and only then writes OUTPUT_PATHS into the working tree
  for review and commit.

Imported bytes are review input. The committed result must still pass the golden, sample and
Atlas Scope gates on fresh hosted CI; nothing here approves, merges or releases. See
docs/engine-output-handoff.md.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import stat
import subprocess
import sys
import zipfile

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
# Every named step of the workflow job, in order. The receiver requires each to have succeeded;
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

MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_API_BYTES = 8 * 1024 * 1024
MAX_GIT_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 32
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


class HandoffRefusal(ValueError):
    """A fail-closed refusal: nothing is captured, uploaded or written past this point."""


def need(condition: object, message: str) -> None:
    if not condition:
        raise HandoffRefusal(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    need(not text.startswith("\ufeff"), f"{label}: carries a byte-order mark")
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


def read_regular(path: Path, maximum: int) -> bytes:
    """One stable, ordinary, singly linked file, read without following links."""
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise HandoffRefusal(f"{path}: missing") from error
    need(stat.S_ISREG(before.st_mode) and not _indirect(before), f"{path}: not an ordinary file")
    need(before.st_nlink == 1, f"{path}: hard-linked file refused")
    need(before.st_size <= maximum, f"{path}: exceeds the bounded size")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
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
    descriptor = os.open(path, flags, 0o644)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            need(written > 0, f"{path}: write stalled")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_file(target: Path, data: bytes) -> None:
    """Write a sibling temporary file exclusively, then replace the target in one rename."""
    temporary = target.parent / f".{target.name}.{secrets.token_hex(8)}.engine-handoff.tmp"
    try:
        write_new(temporary, data)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _outside(path: Path, root: Path) -> bool:
    resolved, base = path.resolve(), root.resolve()
    return not (resolved == base or resolved.is_relative_to(base) or base.is_relative_to(resolved))


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


def _nul_paths(raw: bytes) -> list[str]:
    if not raw:
        return []
    need(raw.endswith(b"\0"), "git path list is not NUL terminated")
    return [item.decode("utf-8") for item in raw[:-1].split(b"\0")]


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


def committed_output(root: Path, commit: str, path: str) -> bytes:
    entry = git(root, "ls-tree", "-z", commit, "--", path)
    need(entry.endswith(b"\0") and entry.count(b"\0") == 1, f"{path} is not one committed entry at {commit}")
    header, name = entry[:-1].split(b"\t", 1)
    mode, kind, _blob = header.decode("ascii").split(" ")
    need(name.decode("utf-8") == path and mode == "100644" and kind == "blob",
         f"{path} is not an ordinary committed file at {commit}")
    size = int(git(root, "cat-file", "-s", f"{commit}:{path}").decode().strip())
    need(size <= MAX_MEMBER_BYTES, f"{path} exceeds the bounded size at {commit}")
    data = git(root, "cat-file", "blob", f"{commit}:{path}")
    need(len(data) == size, f"{path}: committed blob size mismatch")
    return data


def untracked_census(root: Path) -> list[str]:
    """Every untracked file, ignored ones included (no standard excludes)."""
    return sorted(_nul_paths(git(root, "ls-files", "-z", "--others")))


# --------------------------------------------------------------------------- content policy


def marker_patterns_for(root: Path):
    """The canonical client-marker policy from THIS checkout, never from an installed copy."""
    saved = sys.path[:]
    try:
        sys.path.insert(0, str(root))
        module = importlib.import_module("cisco_toolkit.distribution_verify")
    finally:
        # Restore in place: spawned children inherit sys.path and must not see the checkout.
        sys.path[:] = saved
    loaded = Path(getattr(module, "__file__", "") or "").resolve()
    need(loaded == (root / "cisco_toolkit" / "distribution_verify.py").resolve(),
         "the marker policy did not load from this checkout")
    policy = getattr(module, "_marker_patterns_for", None)
    need(callable(policy), "the canonical marker policy is missing")
    return policy


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
    need(not state.exists(), "the state directory must be fresh")
    record = {"schema": SOURCE_SCHEMA, **bind_source(root, env["expected"]), "untracked": untracked_census(root)}
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
    need(not output.exists(), "the handoff output directory must be fresh")

    changed = _closed_effect(root, before)
    policy = marker_patterns_for(root) if patterns_for is None else patterns_for
    produced = {}
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


# --------------------------------------------------------------------------- receiver (local)


def safe_member_name(name: object) -> str:
    need(isinstance(name, str) and 0 < len(name) <= 240 and name.isascii(), f"unsafe member name {name!r}")
    need(not name.startswith("/") and "\\" not in name and ":" not in name and "\x00" not in name,
         f"absolute or ambiguous member name {name!r}")
    parts = name.split("/")
    need(all(_SEGMENT.fullmatch(part) for part in parts), f"unsafe member path segment in {name!r}")
    need(all(not part.endswith((".", " ")) and part.split(".")[0].lower() not in _WINDOWS_DEVICES
             for part in parts), f"Windows alias in member name {name!r}")
    return name


def zip_members(data: bytes) -> dict[str, bytes]:
    """Every regular member of a bounded, unencrypted ZIP; links, aliases and specials refused."""
    need(22 <= len(data) <= MAX_ARCHIVE_BYTES, "the artifact archive size is out of bounds")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise HandoffRefusal("the artifact is not a ZIP archive") from error
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    with archive:
        entries = archive.infolist()
        need(0 < len(entries) <= MAX_ZIP_ENTRIES, "the artifact member census is out of bounds")
        for entry in entries:
            raw = entry.filename
            directory = raw.endswith("/")
            name = safe_member_name(raw[:-1] if directory else raw)
            need(name.casefold() not in seen, f"duplicate or case-aliased member {name!r}")
            seen.add(name.casefold())
            kind = stat.S_IFMT(entry.external_attr >> 16)
            need(entry.flag_bits & 0x1 == 0, f"encrypted member {name!r}")
            if directory:
                need(kind in (0, stat.S_IFDIR) and entry.file_size == 0, f"directory member {name!r} carries data")
                need(name in ALLOWED_DIRECTORIES, f"unexpected directory member {name!r}")
                continue
            need(kind in (0, stat.S_IFREG), f"member {name!r} is a link or special file")
            need(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                 f"member {name!r} uses an unsupported compression")
            need(0 <= entry.file_size <= MAX_MEMBER_BYTES and total + entry.file_size <= MAX_TOTAL_BYTES,
                 f"member {name!r} exceeds the expanded-size bound")
            try:
                with archive.open(entry) as stream:
                    content = stream.read(entry.file_size + 1)
            except (zipfile.BadZipFile, OSError, EOFError, ValueError) as error:
                raise HandoffRefusal(f"member {name!r} is unreadable or fails its CRC") from error
            need(len(content) == entry.file_size, f"member {name!r} expands past its declared size")
            total += len(content)
            files[name] = content
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
         "and pass --allow-golden-shrink to accept it explicitly")
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


def resolve_source(root: Path, head: str, requested: str | None) -> tuple[str, list[str]]:
    """HEAD by default; an explicitly named ancestor only when the commits after it touch docs/*.md alone."""
    if requested is None:
        return head, []
    need(isinstance(requested, str) and HEX40.fullmatch(requested), "--source-commit must be a full 40-character commit")
    if requested == head:
        return head, []
    need(commit_of(root, requested) == requested, "--source-commit is not a commit in this checkout")
    # merge-base --is-ancestor answers 0 (ancestor) or 1 (not); anything else is a git failure.
    is_ancestor = git(root, "merge-base", "--is-ancestor", requested, head, ok=(0, 1), want_code=True)
    need(is_ancestor == 0, "--source-commit is not an ancestor of HEAD")
    between = _nul_paths(git(root, "diff", "--no-renames", "--name-only", "-z", requested, head, "--"))
    outside = sorted(path for path in between if not DOCUMENTATION_ONLY.fullmatch(path))
    need(not outside, "commits after the source change more than top-level docs/*.md: " + ", ".join(outside[:12]))
    return requested, sorted(between)


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


def write_outputs(root: Path, admitted: dict[str, bytes]) -> None:
    targets = {}
    for path in OUTPUT_PATHS:
        target = _ordinary_parents(root, path)
        try:
            info = target.lstat()
        except FileNotFoundError as error:
            raise HandoffRefusal(f"{path}: the local target is missing") from error
        need(stat.S_ISREG(info.st_mode) and not _indirect(info) and info.st_nlink == 1,
             f"{path}: the local target is not an ordinary singly linked file")
        targets[path] = target
    for path, target in targets.items():
        replace_file(target, admitted[path])
    for path, target in targets.items():
        need(read_regular(target, MAX_MEMBER_BYTES) == admitted[path], f"{path}: written bytes differ")


def receive(root: Path, run_id: int, *, source_commit: str | None = None, allow_golden_shrink: bool = False,
            dry_run: bool = False, api=None, patterns_for=None, out=print) -> dict:
    need(type(run_id) is int and 0 < run_id < 2**53, "--run-id must be a positive run number")
    checkout_root(root)
    head = commit_of(root, "HEAD")
    require_clean_tracked_tree(root)
    source, between = resolve_source(root, head, source_commit)
    tree = tree_of(root, source)
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
                          allow_golden_shrink=allow_golden_shrink)
    admitted = admit_outputs(files, rows, marker_patterns_for(root) if patterns_for is None else patterns_for)
    from_source = sorted(path for path in OUTPUT_PATHS if committed_output(root, source, path) != admitted[path])
    need(from_source == manifest["changed_from_source"],
         "the manifest's changed_from_source disagrees with this checkout's source commit")

    report = []
    for path in OUTPUT_PATHS:
        old = committed_output(root, head, path)
        row = {"path": path, "bytes": len(admitted[path]), "sha256": digest(admitted[path]),
               "identical_to_head": old == admitted[path]}
        if not row["identical_to_head"]:
            row["changed_top_level_keys"] = _top_level_drift(old, admitted[path], path)
        report.append(row)
    result = {"run_id": run_id, "run_attempt": attempt, "artifact": artifact["name"], "source_commit": source,
              "head": head, "commits_after_source_touch": between, "allow_golden_shrink": manifest["allow_golden_shrink"],
              "outputs": report, "written": False}

    out(f"ADMITTED {artifact['name']} (archive sha256 {artifact['sha256']})")
    out(f"source {source} tree {tree}" + ("" if source == head else
                                          f"; HEAD {head} differs only in: {', '.join(between) or 'no paths'}"))
    if manifest["allow_golden_shrink"]:
        out("WARNING: produced under ALLOW_GOLDEN_SHRINK=1; the golden contract may have lost surface")
    for row in report:
        state = "identical to HEAD" if row["identical_to_head"] else (
            "changed; top-level keys: " + (", ".join(row["changed_top_level_keys"])
                                           if row["changed_top_level_keys"] is not None else "unparseable at HEAD"))
        out(f"  {row['path']}: {row['bytes']} bytes, {state}")
    if dry_run:
        out("dry run: nothing written")
        return result

    need(commit_of(root, "HEAD") == head, "HEAD moved during the receipt")
    require_clean_tracked_tree(root)
    write_outputs(root, admitted)
    result["written"] = True
    out("wrote the closed output set into the working tree. Review `git diff`, then commit; the hosted "
        "golden, sample and Atlas Scope gates on that commit decide. Nothing here approves, merges or releases.")
    return result


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hosted engine-output regeneration handoff (review input only).")
    commands = parser.add_subparsers(dest="command", required=True)
    before = commands.add_parser("before", help="hosted: bind the exact source before regeneration")
    before.add_argument("--state", type=Path, required=True)
    after = commands.add_parser("after", help="hosted: capture the closed output set after regeneration")
    after.add_argument("--state", type=Path, required=True)
    after.add_argument("--output", type=Path, required=True)
    take = commands.add_parser("receive", help="local: verify one hosted artifact and write the outputs")
    take.add_argument("--run-id", type=int, required=True)
    take.add_argument("--source-commit", default=None,
                      help="the artifact's source when it is an ancestor of HEAD (later commits may touch docs/*.md only)")
    take.add_argument("--allow-golden-shrink", action="store_true",
                      help="accept a handoff produced under the explicit ALLOW_GOLDEN_SHRINK dispatch input")
    take.add_argument("--dry-run", action="store_true", help="verify and report without writing")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2] if root is None else root
    try:
        if args.command == "before":
            phase_before(checkout_root(root), args.state)
        elif args.command == "after":
            phase_after(checkout_root(root), args.state, args.output)
        else:
            receive(root, args.run_id, source_commit=args.source_commit,
                    allow_golden_shrink=args.allow_golden_shrink, dry_run=args.dry_run)
    except HandoffRefusal as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
