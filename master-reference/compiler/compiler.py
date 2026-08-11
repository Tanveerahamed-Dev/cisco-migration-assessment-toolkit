"""Deterministic whole-repository intelligence compiler.

The selected commit's Git tree is the primary corpus. Exact-clean builds parse
raw Git-blob bytes so checkout filters such as ``core.autocrlf`` cannot change
source or line digests. The tracked index, worktree status, and a separate
full-exposure worktree snapshot still prove that local changes were neither
silently ignored nor introduced while compilation was running. Optional
Graphify data is a secondary, privacy-filtered projection and is never used to
fill gaps in the primary census.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from atlas_privacy import FORBIDDEN_CONTENT_RULES, forbidden_content_findings
from governance.architecture import build_architecture_conformance, load_contract
from governance.policy import validate_claims

from .graphify import (
    GRAPHIFY_DIRTY_PREVIEW_REASON,
    GraphifyFailure,
    project_graphify,
    validate_graphify_metadata,
    verify_graphify_snapshot,
)
from .model import SCHEMA_VERSION, canonical_json, chunked, digest_object, sha256_bytes, stable_id
from .parsers import ParseFailure, ParseResult, nonblank_line_records, parse_by_language, safe_decode_text
from .policy import classify_file, documentation_status


MAX_BINARY_BYTES = 512 * 1024 * 1024
TYPESCRIPT_LANGUAGES = frozenset({"javascript", "jsx", "typescript", "tsx"})
RECORD_GROUPS = (
    "files",
    "lines",
    "source_text",
    "symbols",
    "structural_entities",
    "imports",
    "calls",
    "markdown",
    "structured",
    "documents",
    "routes",
    "components",
    "tests",
    "workflows",
    "datasets",
    "binaries",
    "manifests",
    "configs",
    "dependencies",
    "graph_nodes",
    "graph_edges",
    "claims",
)
FALLBACK_ENTITY_TYPE_BY_GROUP = {
    "files": "file",
    "lines": "line",
    "source_text": "source_text",
    "symbols": "symbol",
    "structural_entities": "structural_entity",
    "imports": "import",
    "calls": "call",
    "markdown": "markdown",
    "structured": "structured_record",
    "documents": "document",
    "routes": "route",
    "components": "component",
    "tests": "test",
    "workflows": "workflow",
    "datasets": "dataset",
    "binaries": "binary",
    "manifests": "manifest",
    "configs": "config",
    "dependencies": "dependency",
    "graph_nodes": "graph_node",
    "graph_edges": "graph_edge",
    "claims": "claim",
}

GUI_DOSSIER_FIELDS = (
    "persona_journey",
    "data_snapshot_sources",
    "props_contract",
    "state_model",
    "loading_empty_error_unknown_stale_states",
    "user_actions",
    "accessibility",
    "responsive_behavior",
    "design_tokens",
    "white_label_inputs",
    "design_sync_receipt",
    "visual_baseline",
    "tests",
    "downstream_consumers",
    "known_gaps",
)
GUI_EVIDENCE_STATES = frozenset({"explicitly_linked", "structural_only", "not_evidenced"})
GUI_FIELD_GAPS = {
    "persona_journey": ("gap.product-adoption",),
    "data_snapshot_sources": ("gap.artifact-channel-parity",),
    "props_contract": ("gap.accessibility-performance",),
    "state_model": ("gap.accessibility-performance",),
    "loading_empty_error_unknown_stale_states": ("gap.accessibility-performance",),
    "user_actions": ("gap.accessibility-performance",),
    "accessibility": ("gap.accessibility-performance",),
    "responsive_behavior": ("gap.accessibility-performance",),
    "design_tokens": ("gap.white-label",),
    "white_label_inputs": ("gap.white-label",),
    "design_sync_receipt": ("gap.white-label",),
    "visual_baseline": ("gap.accessibility-performance",),
    "tests": ("gap.accessibility-performance",),
    "downstream_consumers": ("gap.artifact-channel-parity",),
    "known_gaps": ("gap.accessibility-performance", "gap.white-label"),
}


class CompilationError(RuntimeError):
    """The compiler refused to publish an incomplete or unsafe projection."""

    def __init__(self, errors: Iterable[str], output_directory: Path | None = None):
        self.errors = tuple(sorted(set(str(error) for error in errors)))
        self.output_directory = output_directory
        detail = "; ".join(self.errors[:8])
        if len(self.errors) > 8:
            detail += f"; … {len(self.errors) - 8} more"
        super().__init__(detail or "repository compilation failed")


@dataclass(frozen=True)
class GitEntry:
    mode: str
    blob_oid: str
    stage: int
    path: str


def _git(root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    process = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip().replace("\r", " ").replace("\n", " ")
        raise CompilationError([f"git {' '.join(arguments)} failed ({process.returncode}): {message[:500]}"])
    return process.stdout


def _decode_git_path(value: bytes) -> str:
    try:
        path = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CompilationError([f"Git path is not UTF-8: {exc}"]) from exc
    normalized = PurePosixPath(path).as_posix()
    if normalized != path or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise CompilationError([f"unsafe or non-canonical Git path: {path!r}"])
    return path


def _git_census(root: Path) -> list[GitEntry]:
    cached = [_decode_git_path(item) for item in _git(root, "ls-files", "--cached", "-z").split(b"\0") if item]
    stage_rows = [item for item in _git(root, "ls-files", "--stage", "-z").split(b"\0") if item]
    entries: list[GitEntry] = []
    for row in stage_rows:
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, oid, stage_text = metadata.decode("ascii").split(" ")
            entry = GitEntry(mode=mode, blob_oid=oid, stage=int(stage_text), path=_decode_git_path(raw_path))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CompilationError(["could not parse git ls-files --stage record"]) from exc
        entries.append(entry)
    stage_paths = [entry.path for entry in entries]
    errors: list[str] = []
    if cached != stage_paths:
        errors.append("git cached census and stage census differ")
    if len(cached) != len(set(cached)):
        errors.append("duplicate paths in Git tracked-file census")
    folded: dict[str, str] = {}
    for path in cached:
        key = path.casefold()
        if key in folded and folded[key] != path:
            errors.append(f"case-fold path collision: {folded[key]} and {path}")
        folded[key] = path
    for entry in entries:
        if entry.stage != 0:
            errors.append(f"unmerged Git index stage {entry.stage}: {entry.path}")
    if errors:
        raise CompilationError(errors)
    return entries


def _git_tree_census(root: Path, source_commit: str) -> list[GitEntry]:
    """Enumerate the selected commit tree independently of the worktree index."""

    rows = [item for item in _git(root, "ls-tree", "-r", "--full-tree", "-z", source_commit).split(b"\0") if item]
    entries: list[GitEntry] = []
    errors: list[str] = []
    folded: dict[str, str] = {}
    for row in rows:
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, object_type, oid = metadata.decode("ascii", errors="strict").split(" ")
            path = _decode_git_path(raw_path)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CompilationError(["could not parse git ls-tree record"]) from exc
        expected_type = "commit" if mode == "160000" else "blob"
        if object_type != expected_type:
            errors.append(f"selected commit tree has unexpected {object_type} object for mode {mode}: {path}")
        key = path.casefold()
        if key in folded and folded[key] != path:
            errors.append(f"case-fold path collision: {folded[key]} and {path}")
        folded[key] = path
        entries.append(GitEntry(mode=mode, blob_oid=oid, stage=0, path=path))
    paths = [entry.path for entry in entries]
    if len(paths) != len(set(paths)):
        errors.append("duplicate paths in selected commit tree census")
    if errors:
        raise CompilationError(errors)
    return entries


def _nonstandard_index_flags(root: Path) -> dict[str, str]:
    """Return index flags that can make ordinary status checks omit a path."""

    result: dict[str, str] = {}
    for row in (item for item in _git(root, "ls-files", "-v", "-z").split(b"\0") if item):
        if len(row) < 3 or row[1:2] != b" ":
            raise CompilationError(["could not parse git ls-files -v record"])
        try:
            tag = row[:1].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise CompilationError(["Git index flag is not ASCII"]) from exc
        path = _decode_git_path(row[2:])
        if tag != "H":
            result[path] = tag
    return result


def _tracked_path(root: Path, path: str, *, allow_final_symlink: bool) -> Path:
    current = root
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CompilationError([f"{path}: tracked path is unavailable: {exc.strerror or exc}"]) from exc
        is_final = index == len(parts) - 1
        if stat.S_ISLNK(metadata.st_mode) and not (is_final and allow_final_symlink):
            raise CompilationError([f"{path}: symlink traversal refused"])
        if not is_final and not stat.S_ISDIR(metadata.st_mode):
            raise CompilationError([f"{path}: parent component is not a directory"])
    return current


def _read_regular(root: Path, entry: GitEntry) -> tuple[bytes, int]:
    path = _tracked_path(root, entry.path, allow_final_symlink=False)
    metadata_before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata_before.st_mode):
        raise CompilationError([f"{entry.path}: full-exposure tracked path is not a regular file"])
    if metadata_before.st_size > MAX_BINARY_BYTES:
        raise CompilationError([f"{entry.path}: file exceeds {MAX_BINARY_BYTES} bytes"])
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CompilationError([f"{entry.path}: read failed: {exc.strerror or exc}"]) from exc
    metadata_after = path.stat(follow_symlinks=False)
    if (
        metadata_before.st_size != metadata_after.st_size
        or metadata_before.st_mtime_ns != metadata_after.st_mtime_ns
        or len(data) != metadata_after.st_size
    ):
        raise CompilationError([f"{entry.path}: file changed while it was being read"])
    return data, metadata_after.st_size


def _git_object_size(root: Path, entry: GitEntry) -> int:
    """Return object payload size without reading a restricted payload."""

    try:
        value = _git(root, "cat-file", "-s", entry.blob_oid).decode("ascii", errors="strict").strip()
        size = int(value)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CompilationError([f"{entry.path}: Git object size is invalid"]) from exc
    if size < 0:
        raise CompilationError([f"{entry.path}: Git object size is negative"])
    return size


def _read_git_blobs(root: Path, entries: list[GitEntry]) -> dict[str, tuple[bytes, int]]:
    """Read approved full-exposure blobs through one fail-closed Git batch."""

    if not entries:
        return {}
    if any(entry.mode == "160000" for entry in entries):
        raise CompilationError(["Git links cannot be read as full-exposure blobs"])
    request = b"".join(entry.blob_oid.encode("ascii") + b"\n" for entry in entries)
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        process = subprocess.run(
            ["git", "-c", "core.quotepath=false", "cat-file", "--batch"],
            cwd=root,
            env=environment,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompilationError([f"Git blob batch could not run: {exc}"]) from exc
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip().replace("\r", " ").replace("\n", " ")
        raise CompilationError([f"Git blob batch failed ({process.returncode}): {detail[:500]}"])

    output = process.stdout
    cursor = 0
    result: dict[str, tuple[bytes, int]] = {}
    for entry in entries:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise CompilationError([f"{entry.path}: Git blob batch response is truncated"])
        try:
            actual_oid, object_type, size_text = output[cursor:header_end].decode("ascii").split(" ")
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise CompilationError([f"{entry.path}: Git blob batch header is invalid"]) from exc
        if actual_oid != entry.blob_oid or object_type != "blob" or size < 0:
            raise CompilationError([f"{entry.path}: Git blob batch identity or type mismatch"])
        if size > MAX_BINARY_BYTES:
            raise CompilationError([f"{entry.path}: Git blob exceeds {MAX_BINARY_BYTES} bytes"])
        start = header_end + 1
        end = start + size
        if end >= len(output) or output[end : end + 1] != b"\n":
            raise CompilationError([f"{entry.path}: Git blob batch payload is truncated"])
        data = output[start:end]
        header = f"blob {len(data)}\0".encode("ascii")
        algorithm = hashlib.sha1 if len(entry.blob_oid) == 40 else hashlib.sha256
        if algorithm(header + data).hexdigest() != entry.blob_oid:
            raise CompilationError([f"{entry.path}: Git blob object identity mismatch"])
        result[entry.path] = (data, size)
        cursor = end + 1
    if cursor != len(output):
        raise CompilationError(["Git blob batch returned unexpected trailing output"])
    return result


def _metadata_size(root: Path, entry: GitEntry) -> int | None:
    if entry.mode == "160000":
        return None
    return _git_object_size(root, entry)


def _typescript_results(files: list[dict[str, str]]) -> tuple[str, dict[str, ParseResult]]:
    if not files:
        return "not_used", {}
    adapter = Path(__file__).with_name("ts_adapter.mjs")
    request = canonical_json({"files": sorted(files, key=lambda row: row["path"])})
    try:
        process = subprocess.run(
            ["node", str(adapter)],
            cwd=adapter.parent.parent,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ParseFailure(f"TypeScript adapter could not run: {exc}") from exc
    try:
        response = json.loads(process.stdout.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ParseFailure(f"TypeScript adapter returned invalid JSON (exit {process.returncode})") from exc
    if process.returncode != 0 or not isinstance(response, dict) or response.get("ok") is not True:
        errors = response.get("errors") if isinstance(response, dict) else None
        detail = " | ".join(str(item) for item in errors) if isinstance(errors, list) else "unknown adapter error"
        raise ParseFailure(f"TypeScript adapter failed: {detail[:4000]}")
    raw_results = response.get("results")
    expected = {row["path"] for row in files}
    if not isinstance(raw_results, dict) or set(raw_results) != expected:
        raise ParseFailure("TypeScript adapter result paths do not exactly match its input paths")
    results: dict[str, ParseResult] = {}
    list_fields = (
        "symbols",
        "imports",
        "calls",
        "markdown",
        "structured",
        "routes",
        "components",
        "tests",
        "workflows",
        "dependencies",
        "unresolved_reasons",
    )
    for path in sorted(expected):
        raw = raw_results[path]
        if not isinstance(raw, dict) or not isinstance(raw.get("line_context"), dict):
            raise ParseFailure(f"{path}: malformed TypeScript adapter result")
        result = ParseResult(
            parser=str(raw.get("parser") or "typescript_compiler_api"),
            parser_mode=str(raw.get("parser_mode") or "syntax_ast"),
        )
        try:
            result.line_context = {int(number): value for number, value in raw["line_context"].items()}
        except (TypeError, ValueError) as exc:
            raise ParseFailure(f"{path}: malformed TypeScript line context") from exc
        for field_name in list_fields:
            value = raw.get(field_name, [])
            if not isinstance(value, list):
                raise ParseFailure(f"{path}: TypeScript adapter field {field_name} is not a list")
            setattr(result, field_name, value)
        results[path] = result
    return str(response.get("compiler_version") or "undisclosed"), results


def _new_records() -> dict[str, list[dict[str, Any]]]:
    return {group: [] for group in RECORD_GROUPS}


def _exact_source_lines(value: str) -> list[dict[str, Any]]:
    """Split only CRLF/LF/CR while retaining every source character."""

    result: list[dict[str, Any]] = []
    start = 0
    number = 1
    while start < len(value):
        cr = value.find("\r", start)
        lf = value.find("\n", start)
        positions = [position for position in (cr, lf) if position >= 0]
        if not positions:
            text = value[start:]
            terminator = ""
            next_start = len(value)
        else:
            end = min(positions)
            text = value[start:end]
            if value.startswith("\r\n", end):
                terminator = "\r\n"
            else:
                terminator = value[end]
            next_start = end + len(terminator)
        encoded_text = text.encode("utf-8")
        encoded_line = (text + terminator).encode("utf-8")
        result.append(
            {
                "number": number,
                "text": text,
                "terminator": terminator,
                "text_digest": sha256_bytes(encoded_text),
                "line_digest": sha256_bytes(encoded_line),
            }
        )
        number += 1
        start = next_start
    return result


def _merge_parse_result(records: dict[str, list[dict[str, Any]]], result: ParseResult) -> None:
    for group in (
        "symbols",
        "imports",
        "calls",
        "markdown",
        "structured",
        "routes",
        "components",
        "tests",
        "workflows",
        "dependencies",
    ):
        records[group].extend(getattr(result, group))


def _is_config(file_record: dict[str, Any]) -> bool:
    path = str(file_record["path"]).lower()
    language = file_record["language"]
    roles = set(file_record["roles"])
    name = PurePosixPath(path).name
    return (
        "config" in roles
        or "workflow" in roles
        or language in {"config", "ini", "jsonc", "toml", "yaml"}
        or "config" in name
        or name in {".mcp.json", "package.json", "pyproject.toml", "pytest.ini", "ruff.toml"}
    )


def _structural_root_kind(file_record: dict[str, Any]) -> str:
    """Return the parser-owned document/module root kind for one safe source."""

    language = str(file_record["language"])
    roles = {str(role) for role in file_record.get("roles") or []}
    if "workflow" in roles:
        return "workflow_document"
    if language == "python":
        return "python_module"
    if language in TYPESCRIPT_LANGUAGES:
        # The TypeScript compiler API represents JavaScript and TypeScript
        # inputs with the same SourceFile root; language remains explicit.
        return "typescript_source_file"
    if language == "css":
        return "stylesheet_document"
    if language in {"html", "svg"}:
        return "template_document"
    if language == "markdown":
        return "documentation_document"
    if _is_config(file_record):
        return "configuration_document"
    if "structured_data" in roles:
        return "structured_document"
    if language == "text":
        return "plain_text_document"
    return "source_document"


def _structural_root_record(
    file_record: dict[str, Any],
    result: ParseResult,
    text: str,
) -> dict[str, Any]:
    """Build the single typed parser root that owns non-symbol source lines.

    This entity is a semantic denominator, not a behavioral claim.  Its range
    is derived from the exact decoded source accepted by the owning parser;
    empty sources retain an explicit empty-range state instead of inventing a
    line.  Generation provenance remains unknown unless a future classifier
    provides an explicit generated role and generator relationship.
    """

    source_lines = text.splitlines()
    has_lines = bool(source_lines)
    location: dict[str, int | None] = {
        "start_line": 1 if has_lines else None,
        "start_column": 0 if has_lines else None,
        "end_line": len(source_lines) if has_lines else None,
        "end_column": len(source_lines[-1]) if has_lines else None,
    }
    roles = sorted({str(role) for role in file_record.get("roles") or []})
    generated_declared = "generated" in roles
    unresolved = {str(reason) for reason in result.unresolved_reasons if str(reason)}
    unresolved.add("structural_root_does_not_establish_behavior_or_execution")
    if generated_declared:
        unresolved.add("declared_generated_source_has_no_joined_generator_record")
    else:
        unresolved.add("generated_provenance_not_declared")
    kind = _structural_root_kind(file_record)
    return {
        "id": stable_id("structural-entity", file_record["path"], "parsed-source-root"),
        "file_id": file_record["id"],
        "path": file_record["path"],
        "name": file_record["path"],
        "kind": kind,
        "entity_type": f"structural_root_{kind}",
        "root_scope": "parsed_source",
        "range": location,
        "range_state": "exact_source_lines" if has_lines else "empty_source",
        "line_count": len(source_lines),
        "nonblank_line_count": int(file_record.get("nonblank_line_count") or 0),
        "parser": result.parser,
        "parser_mode": result.parser_mode,
        "parser_version": file_record.get("parser_version"),
        "parser_owned": True,
        "language": file_record["language"],
        "roles": roles,
        "source_basis": file_record["content_source"],
        "git_blob_oid": file_record["git_blob_oid"],
        "content_digest": file_record["content_digest"],
        "generation_provenance": {
            "state": "declared_generated" if generated_declared else "not_declared",
            "basis": "explicit_generated_role" if generated_declared else "no_generated_role_or_generator_declaration",
            "generator_record_ids": [],
        },
        "extraction_disposition": "parser_structural_root",
        "explanation_depth": 1,
        "uncertainty": sorted(unresolved),
        "unresolved_reasons": sorted(unresolved),
    }


def _sort_and_validate(records: dict[str, list[dict[str, Any]]]) -> list[str]:
    errors: list[str] = []
    global_ids: dict[str, str] = {}
    for group in RECORD_GROUPS:
        for record in records[group]:
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier:
                errors.append(f"{group}: record without stable id")
                continue
            if identifier in global_ids:
                errors.append(f"duplicate record id {identifier} in {global_ids[identifier]} and {group}")
            global_ids[identifier] = group
        records[group].sort(key=lambda row: str(row.get("id", "")))
    return errors


def _assign_entity_types(records: dict[str, list[dict[str, Any]]]) -> None:
    """Give every published record an explicit denominator category.

    Parser adapters may provide a more precise category.  The fallback is a
    structural group/kind label only; it never raises explanation depth or
    claims behavioral understanding.
    """

    if set(FALLBACK_ENTITY_TYPE_BY_GROUP) != set(RECORD_GROUPS):
        missing = sorted(set(RECORD_GROUPS) - set(FALLBACK_ENTITY_TYPE_BY_GROUP))
        extra = sorted(set(FALLBACK_ENTITY_TYPE_BY_GROUP) - set(RECORD_GROUPS))
        raise CompilationError([f"fallback entity-type registry mismatch: missing={missing}, extra={extra}"])
    for group in RECORD_GROUPS:
        singular = FALLBACK_ENTITY_TYPE_BY_GROUP[group]
        for record in records[group]:
            if record.get("entity_type"):
                continue
            subtype = record.get("kind") or record.get("value_type") or record.get("record_type")
            raw = f"{singular}_{subtype}" if subtype else singular
            normalized = "_".join(part for part in re.split(r"[^a-z0-9]+", str(raw).lower()) if part)
            record["entity_type"] = normalized or singular


def _sanitize_error(error: object, root: Path, output: Path) -> str:
    value = str(error).replace(str(root), "<repo>").replace(str(output), "<output>")
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:4000]


def _source_state_id(source_commit: str, source_tree_digest: str) -> str:
    return stable_id("source-state", source_commit, source_tree_digest)


def _commit_time(root: Path, source_commit: str) -> str:
    """Return the commit's recorded time without introducing wall-clock state."""

    value = _git(root, "show", "-s", "--format=%cI", source_commit).decode("ascii", errors="strict").strip()
    if not value or "T" not in value or not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:]):
        raise CompilationError([f"Git commit {source_commit} has no parseable committer timestamp"])
    return value


def _claims(
    source_commit: str,
    source_commit_time: str,
    source_tree_digest: str,
    files: list[dict[str, Any]],
    line_count: int,
    graphify: dict[str, Any],
    completeness_id: str,
    dirty: bool,
) -> list[dict[str, Any]]:
    source_id = _source_state_id(source_commit, source_tree_digest)
    owner_id = stable_id("owner", "atlas_repository_compiler")
    preview_reason = ["dirty_worktree_not_exact_commit_bound"] if dirty else []
    basis = (
        "deterministic_structural_derivation_from_dirty_tracked_worktree_preview"
        if dirty
        else "deterministic_structural_derivation_from_exact_git_tree"
    )

    def denominator(value: int | float | None, unit: str, denominator_basis: str) -> dict[str, Any]:
        return {
            "value": value,
            "unit": unit,
            "basis": denominator_basis,
            "status": "known" if value is not None else "unknown",
        }

    def claim(
        predicate: str,
        value: Any,
        unit: str | None,
        evidence: list[str],
        claim_denominator: dict[str, Any],
        unresolved: list[str] | None = None,
        *,
        freshness: str | None = None,
    ) -> dict[str, Any]:
        reasons = sorted(set((unresolved or []) + preview_reason))
        effective_freshness = freshness or ("unknown" if dirty else "current")
        verdict = "indeterminate" if dirty else "proven"
        return {
            "id": stable_id("claim", source_id, predicate),
            "subject": source_id,
            "predicate": predicate,
            "value": value,
            "unit": unit,
            "basis": basis,
            "scope": {
                "source_commit": source_commit,
                "source_tree_digest": source_tree_digest,
                "universe": "git_tracked_tree",
                "privacy_projection": "tracked_safe_content_with_metadata_only_restricted_paths",
                "exact_commit_bound": not dirty,
            },
            "effective_time": source_commit_time,
            "recorded_time": source_commit_time,
            "temporal_basis": "git_commit_committer_time",
            "owner": owner_id,
            "evidence_ids": sorted(set(evidence)),
            "evidence_class": "derived",
            "transformation": {
                "id": stable_id("transformation", "atlas_repository_compiler", predicate),
                "version": SCHEMA_VERSION,
            },
            "denominator": claim_denominator,
            "verdict": verdict,
            "freshness": effective_freshness,
            "lineage": sorted(set(evidence)),
            "derived_from": [],
            "origin": "atlas_repository_compiler",
            "extraction_mode": "structural",
            "confidence": 0.0 if dirty else 1.0,
            "status": "candidate" if dirty else "current",
            "revoked_by": None,
            "revocation_reason": None,
            "conflicts_with": [],
            "current_view": not dirty,
            "satisfies_evidence_requirement": not dirty and effective_freshness == "current",
            "source_commit": source_commit,
            "unresolved_reasons": reasons,
        }

    full_files = [row for row in files if row["privacy_exposure"] == "full"]
    graph_freshness = (
        "unknown"
        if dirty or graphify.get("stale") is None
        else ("stale" if graphify.get("stale") is True else "current")
    )
    return sorted(
        [
            claim(
                "repository.source_commit",
                source_commit,
                None,
                [completeness_id],
                denominator(1, "git_tracked_tree", "compiler_source_snapshot"),
            ),
            claim(
                "repository.source_tree_digest",
                source_tree_digest,
                "sha256",
                [completeness_id],
                denominator(1, "git_tracked_tree", "compiler_source_snapshot"),
            ),
            claim(
                "repository.tracked_file_count",
                len(files),
                "tracked_paths",
                [completeness_id, *[row["id"] for row in files]],
                denominator(len(files), "git_tracked_paths", "git_index_census"),
            ),
            claim(
                "repository.full_exposure_file_count",
                len(full_files),
                "safe_tracked_paths",
                [completeness_id, *[row["id"] for row in full_files]],
                denominator(len(files), "git_tracked_paths", "privacy_classified_git_index_census"),
            ),
            claim(
                "repository.nonblank_line_record_count",
                line_count,
                "nonblank_safe_text_lines",
                [completeness_id],
                denominator(len(files), "git_tracked_paths", "safe_text_line_mapping_over_tracked_tree"),
            ),
            claim(
                "repository.graphify_status",
                {
                    "available": graphify.get("available"),
                    "stale": graphify.get("stale"),
                    "projected_nodes": graphify.get("projected_nodes", 0),
                    "projected_edges": graphify.get("projected_edges", 0),
                    "edge_modes": graphify.get("projected_edge_modes", {}),
                },
                "graph_projection_status",
                [completeness_id],
                denominator(
                    int(graphify.get("projected_nodes", 0)) + int(graphify.get("projected_edges", 0)),
                    "projected_graph_records",
                    "privacy_filtered_graphify_projection",
                )
                if int(graphify.get("projected_nodes", 0)) + int(graphify.get("projected_edges", 0)) > 0
                else denominator(1, "graphify_availability_observation", "compiler_graphify_adapter"),
                list(graphify.get("unresolved_reasons") or []),
                freshness=graph_freshness,
            ),
        ],
        key=lambda row: row["id"],
    )


def _gui_citation(
    record: dict[str, Any],
    evidence_role: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    line_state: str | None = None,
) -> dict[str, Any]:
    location = record.get("range") if isinstance(record.get("range"), dict) else {}
    start = start_line if start_line is not None else location.get("start_line")
    end = end_line if end_line is not None else location.get("end_line")
    has_lines = isinstance(start, int) and isinstance(end, int)
    return {
        "record_id": str(record["id"]),
        "path": str(record["path"]),
        "start_line": start if has_lines else None,
        "end_line": end if has_lines else None,
        "line_state": line_state or ("source_range" if has_lines else "not_applicable_binary"),
        "evidence_role": evidence_role,
    }


def _gui_field(
    state: str,
    value: Any,
    *,
    citations: Iterable[dict[str, Any]] = (),
    unresolved_reasons: Iterable[str] = (),
    gap_ids: Iterable[str],
) -> dict[str, Any]:
    if state not in GUI_EVIDENCE_STATES:
        raise ValueError(f"unsupported GUI evidence state: {state}")
    unique_citations: dict[str, dict[str, Any]] = {}
    for citation in citations:
        key = json.dumps(citation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique_citations[key] = citation
    ordered_citations = [unique_citations[key] for key in sorted(unique_citations)]
    reasons = {str(reason) for reason in unresolved_reasons if str(reason)}
    if len(ordered_citations) > 24:
        ordered_citations = ordered_citations[:24]
        reasons.add("gui_field_citations_bounded_to_24_records")
    return {
        "state": state,
        "value": value,
        "citations": ordered_citations,
        "unresolved_reasons": sorted(reasons),
        "gap_ids": sorted({str(gap_id) for gap_id in gap_ids if str(gap_id)}),
    }


def _json_pointer_parts(pointer: str) -> list[str]:
    if pointer == "/":
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.lstrip("/").split("/")]


def _structured_source_line(
    record: dict[str, Any],
    source_lines_by_path: dict[str, list[dict[str, Any]]],
) -> int | None:
    parts = _json_pointer_parts(str(record.get("pointer") or "/"))
    if not parts:
        return None
    lines = source_lines_by_path.get(str(record["path"]), [])
    section_start = 0
    if len(parts) > 1:
        section_token = json.dumps(parts[0], ensure_ascii=False)
        for index, line in enumerate(lines):
            if section_token in str(line.get("text") or ""):
                section_start = index
                break
    leaf_token = json.dumps(parts[-1], ensure_ascii=False)
    preview = record.get("value_preview")
    preview_token = json.dumps(preview, ensure_ascii=False) if isinstance(preview, str) else None
    fallback: int | None = None
    for line in lines[section_start:]:
        text = str(line.get("text") or "")
        if leaf_token not in text:
            continue
        number = int(line["number"])
        if fallback is None:
            fallback = number
        if preview_token is None or preview_token in text:
            return number
    return fallback


def _safe_repo_relative(base_directory: str, value: str) -> str | None:
    candidate = value.replace("\\", "/").strip()
    if not candidate or candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        return None
    normalized = posixpath.normpath(posixpath.join(base_directory, candidate))
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return PurePosixPath(normalized).as_posix()


def _enrich_gui_dossiers(
    records: dict[str, list[dict[str, Any]]],
    file_records: list[dict[str, Any]],
    source_commit: str,
) -> None:
    """Attach bounded GUI dossiers without promoting static shape to behavior.

    The only joins are exact source ranges, same-path compiler records, explicit
    DesignSync configuration mappings, and the tracked visual-contract manifest.
    Names without one of those structural joins never establish behavior.
    """

    files_by_path = {str(row["path"]): row for row in file_records}
    source_lines_by_path = {str(source["path"]): list(source.get("lines") or []) for source in records["source_text"]}
    line_ids = {(str(line["path"]), int(line["line"])): str(line["id"]) for line in records["lines"]}
    symbols_by_path: dict[str, list[dict[str, Any]]] = {}
    imports_by_path: dict[str, list[dict[str, Any]]] = {}
    calls_by_path: dict[str, list[dict[str, Any]]] = {}
    tests_by_path: dict[str, list[dict[str, Any]]] = {}
    components_by_path: dict[str, list[dict[str, Any]]] = {}
    for group, destination in (
        ("symbols", symbols_by_path),
        ("imports", imports_by_path),
        ("calls", calls_by_path),
        ("tests", tests_by_path),
        ("components", components_by_path),
    ):
        for record in records[group]:
            destination.setdefault(str(record["path"]), []).append(record)

    config_path = ".design-sync/config.json"
    config_records = {
        str(record.get("pointer")): record for record in records["structured"] if record.get("path") == config_path
    }
    entry_record = config_records.get("/entry")
    entry_value = str(entry_record.get("value_preview") or "") if entry_record else ""
    entry_path = _safe_repo_relative("", entry_value)
    entry_directory = posixpath.dirname(entry_path) if entry_path else ""
    project_record = config_records.get("/projectId")
    css_record = config_records.get("/cssEntry")
    css_path = (
        _safe_repo_relative(entry_directory, str(css_record.get("value_preview") or ""))
        if css_record and entry_directory
        else None
    )

    design_sync_components: dict[str, dict[str, Any]] = {}
    design_sync_props: dict[str, dict[str, Any]] = {}
    for pointer, record in config_records.items():
        parts = _json_pointer_parts(pointer)
        if len(parts) != 2:
            continue
        if parts[0] == "componentSrcMap" and entry_directory:
            mapped_path = _safe_repo_relative(entry_directory, str(record.get("value_preview") or ""))
            if mapped_path:
                design_sync_components[parts[1]] = {"record": record, "path": mapped_path}
        elif parts[0] == "dtsPropsFor":
            design_sync_props[parts[1]] = record

    visual_contract_path = "webapp/frontend/visual-e2e/design-cards.visual.spec.ts"
    visual_contract_lines: dict[str, int] = {}
    in_visual_manifest = False
    for line in source_lines_by_path.get(visual_contract_path, []):
        text = str(line.get("text") or "")
        if "const EXPECTED_VARIANTS" in text:
            in_visual_manifest = True
            continue
        if in_visual_manifest and text.strip() == "};":
            break
        if not in_visual_manifest:
            continue
        match = re.match(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*):\s*\[", text)
        if match:
            visual_contract_lines.setdefault(match.group(1), int(line["number"]))

    def structured_citation(record: dict[str, Any], role: str) -> dict[str, Any]:
        number = _structured_source_line(record, source_lines_by_path)
        return _gui_citation(
            record,
            role,
            start_line=number,
            end_line=number,
            line_state="source_range" if number is not None else "source_line_not_resolved",
        )

    def range_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
        outer_range = outer.get("range") or {}
        inner_range = inner.get("range") or {}
        values = (
            outer_range.get("start_line"),
            outer_range.get("end_line"),
            inner_range.get("start_line"),
            inner_range.get("end_line"),
        )
        if not all(isinstance(value, int) for value in values):
            return False
        outer_start, outer_end, inner_start, inner_end = values
        return outer_start <= inner_start <= inner_end <= outer_end

    for surface_kind, surfaces in (("route", records["routes"]), ("component", records["components"])):
        for surface in surfaces:
            path = str(surface["path"])
            source_citation = _gui_citation(surface, "gui_surface_declaration")
            surface_range = surface.get("range") or {}
            start_line = surface_range.get("start_line")
            end_line = surface_range.get("end_line")
            relevant_symbols = []
            for symbol in symbols_by_path.get(path, []):
                exact_identity = str(symbol.get("qualified_name") or symbol.get("name") or "") in {
                    str(surface.get("handler") or ""),
                    str(surface.get("name") or ""),
                }
                same_range = symbol.get("range") == surface.get("range")
                if same_range or (exact_identity and range_contains(symbol, surface)):
                    relevant_symbols.append(symbol)
            relevant_symbols.sort(key=lambda row: str(row["id"]))
            relevant_calls = [
                call
                for call in calls_by_path.get(path, [])
                if isinstance(start_line, int)
                and isinstance(end_line, int)
                and isinstance((call.get("range") or {}).get("start_line"), int)
                and start_line <= int(call["range"]["start_line"]) <= end_line
            ]
            relevant_calls.sort(key=lambda row: str(row["id"]))
            same_path_imports = sorted(imports_by_path.get(path, []), key=lambda row: str(row["id"]))
            same_path_tests = sorted(tests_by_path.get(path, []), key=lambda row: str(row["id"]))

            attribute_names = {str(name) for name in surface.get("attribute_names") or [] if str(name)}
            if surface_kind == "component" and surface.get("entity_type") == "jsx_component_symbol":
                for child in components_by_path.get(path, []):
                    if child is not surface and range_contains(surface, child):
                        attribute_names.update(str(name) for name in child.get("attribute_names") or [] if str(name))
            ordered_attributes = sorted(attribute_names)
            action_attributes = sorted(name for name in ordered_attributes if re.match(r"^on[A-Z]|^on[a-z]", name))
            accessibility_attributes = sorted(
                name
                for name in ordered_attributes
                if name.lower() in {"alt", "role", "tabindex", "htmlfor", "label", "title"}
                or name.lower().startswith("aria-")
            )

            surface_name = str(surface.get("name") or "")
            design_link = (
                design_sync_components.get(surface_name)
                if surface_kind == "component" and surface.get("entity_type") == "jsx_component_symbol"
                else None
            )
            if design_link and design_link["path"] != path:
                design_link = None
            props_link = design_sync_props.get(surface_name) if design_link else None
            visual_line = visual_contract_lines.get(surface_name) if design_link else None
            visual_citations: list[dict[str, Any]] = []
            visual_paths: list[str] = []
            if visual_line is not None:
                line_id = line_ids.get((visual_contract_path, visual_line))
                if line_id:
                    visual_citations.append(
                        {
                            "record_id": line_id,
                            "path": visual_contract_path,
                            "start_line": visual_line,
                            "end_line": visual_line,
                            "line_state": "source_range",
                            "evidence_role": "explicit_visual_variant_manifest_entry",
                        }
                    )
                for suffix in (".png", "-728.png"):
                    baseline_path = (
                        f"webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/{surface_name}{suffix}"
                    )
                    baseline_file = files_by_path.get(baseline_path)
                    if baseline_file:
                        visual_paths.append(baseline_path)
                        visual_citations.append(_gui_citation(baseline_file, "tracked_visual_baseline_binary"))

            symbol_parameters = [
                parameter for symbol in relevant_symbols for parameter in list(symbol.get("parameters") or [])
            ]
            dependency_citations = [
                _gui_citation(record, "same_path_static_dependency_candidate")
                for record in [*same_path_imports[:16], *relevant_calls[:16]]
            ]
            fields: dict[str, dict[str, Any]] = {}
            fields["persona_journey"] = _gui_field(
                "not_evidenced",
                None,
                unresolved_reasons=("persona_and_end_to_end_journey_not_declared_in_surface_structure",),
                gap_ids=GUI_FIELD_GAPS["persona_journey"],
            )
            if same_path_imports or relevant_calls:
                fields["data_snapshot_sources"] = _gui_field(
                    "structural_only",
                    {
                        "same_path_import_ids": [str(row["id"]) for row in same_path_imports[:16]],
                        "in_range_call_ids": [str(row["id"]) for row in relevant_calls[:16]],
                    },
                    citations=dependency_citations,
                    unresolved_reasons=(
                        "static_dependencies_are_candidates_not_proven_runtime_snapshot_sources",
                        "dependency_lists_are_bounded_to_16_records_per_kind",
                    ),
                    gap_ids=GUI_FIELD_GAPS["data_snapshot_sources"],
                )
            else:
                fields["data_snapshot_sources"] = _gui_field(
                    "not_evidenced",
                    None,
                    unresolved_reasons=("no_same_path_import_or_in_range_call_evidence",),
                    gap_ids=GUI_FIELD_GAPS["data_snapshot_sources"],
                )
            props_value = {
                "parser_attribute_names": ordered_attributes,
                "symbol_parameters": symbol_parameters,
            }
            props_citations = [source_citation] + [
                _gui_citation(symbol, "same_path_surface_symbol") for symbol in relevant_symbols[:8]
            ]
            if props_link:
                props_value["design_sync_contract_preview"] = props_link.get("value_preview")
                fields["props_contract"] = _gui_field(
                    "explicitly_linked",
                    props_value,
                    citations=[*props_citations, structured_citation(props_link, "design_sync_props_contract")],
                    unresolved_reasons=(
                        "design_sync_props_declaration_is_not_runtime_prop_validation",
                        "design_sync_props_preview_may_be_truncated",
                    ),
                    gap_ids=GUI_FIELD_GAPS["props_contract"],
                )
            elif ordered_attributes or symbol_parameters:
                fields["props_contract"] = _gui_field(
                    "structural_only",
                    props_value,
                    citations=props_citations,
                    unresolved_reasons=("parser_attributes_and_parameters_do_not_establish_runtime_prop_behavior",),
                    gap_ids=GUI_FIELD_GAPS["props_contract"],
                )
            else:
                fields["props_contract"] = _gui_field(
                    "not_evidenced",
                    None,
                    unresolved_reasons=("no_parser_attribute_parameter_or_explicit_props_contract",),
                    gap_ids=GUI_FIELD_GAPS["props_contract"],
                )
            fields["state_model"] = _gui_field(
                "not_evidenced",
                None,
                unresolved_reasons=("state_reads_writes_and_transitions_not_semantically_resolved",),
                gap_ids=GUI_FIELD_GAPS["state_model"],
            )
            fields["loading_empty_error_unknown_stale_states"] = _gui_field(
                "not_evidenced",
                None,
                unresolved_reasons=("rendered_state_matrix_not_structurally_proven",),
                gap_ids=GUI_FIELD_GAPS["loading_empty_error_unknown_stale_states"],
            )
            fields["user_actions"] = _gui_field(
                "structural_only" if action_attributes else "not_evidenced",
                {"event_attribute_names": action_attributes} if action_attributes else None,
                citations=(source_citation,) if action_attributes else (),
                unresolved_reasons=(
                    "event_attributes_do_not_prove_handler_binding_or_outcome"
                    if action_attributes
                    else "no_parser_event_attribute_evidence",
                ),
                gap_ids=GUI_FIELD_GAPS["user_actions"],
            )
            fields["accessibility"] = _gui_field(
                "structural_only" if accessibility_attributes else "not_evidenced",
                {"accessibility_attribute_names": accessibility_attributes} if accessibility_attributes else None,
                citations=(source_citation,) if accessibility_attributes else (),
                unresolved_reasons=(
                    "attributes_do_not_establish_wcag_or_assistive_technology_conformance"
                    if accessibility_attributes
                    else "no_parser_accessibility_attribute_evidence",
                ),
                gap_ids=GUI_FIELD_GAPS["accessibility"],
            )
            fields["responsive_behavior"] = _gui_field(
                "structural_only" if len(visual_paths) == 2 else "not_evidenced",
                {"tracked_visual_baseline_paths": visual_paths, "narrow_width_label": 728} if visual_paths else None,
                citations=visual_citations,
                unresolved_reasons=(
                    "tracked_pixels_and_manifest_are_not_a_joined_execution_or_manual_review_receipt"
                    if visual_paths
                    else "no_explicit_responsive_baseline_link",
                ),
                gap_ids=GUI_FIELD_GAPS["responsive_behavior"],
            )
            css_imports = [row for row in same_path_imports if str(row.get("module") or "").lower().endswith(".css")]
            token_citations = [_gui_citation(row, "same_path_stylesheet_import") for row in css_imports[:16]]
            token_value: dict[str, Any] = {
                "same_path_stylesheet_import_ids": [str(row["id"]) for row in css_imports[:16]]
            }
            if design_link and css_record and css_path:
                token_value["design_sync_css_entry"] = css_path
                token_citations.append(structured_citation(css_record, "design_sync_global_css_entry"))
            fields["design_tokens"] = _gui_field(
                "structural_only" if token_citations else "not_evidenced",
                token_value if token_citations else None,
                citations=token_citations,
                unresolved_reasons=(
                    "stylesheet_presence_does_not_resolve_selector_token_or_component_consumption"
                    if token_citations
                    else "no_same_path_stylesheet_or_explicit_design_sync_css_entry",
                ),
                gap_ids=GUI_FIELD_GAPS["design_tokens"],
            )
            fields["white_label_inputs"] = _gui_field(
                "not_evidenced",
                None,
                unresolved_reasons=(
                    "no_surface_specific_white_label_input_contract",
                    "customer_specific_profiles_and_client_data_not_ingested",
                ),
                gap_ids=GUI_FIELD_GAPS["white_label_inputs"],
            )
            design_citations = []
            design_value = None
            if design_link:
                design_citations.append(
                    structured_citation(design_link["record"], "explicit_design_sync_component_source_mapping")
                )
                if project_record:
                    design_citations.append(structured_citation(project_record, "design_sync_project_configuration"))
                design_value = {
                    "component_name": surface_name,
                    "mapped_source_path": design_link["path"],
                    "project_id": project_record.get("value_preview") if project_record else None,
                }
            fields["design_sync_receipt"] = _gui_field(
                "structural_only" if design_citations else "not_evidenced",
                design_value,
                citations=design_citations,
                unresolved_reasons=(
                    "design_sync_configuration_is_not_a_sync_or_served_hash_receipt"
                    if design_citations
                    else "no_explicit_design_sync_component_mapping",
                ),
                gap_ids=GUI_FIELD_GAPS["design_sync_receipt"],
            )
            fields["visual_baseline"] = _gui_field(
                "structural_only" if visual_paths else "not_evidenced",
                {"tracked_paths": visual_paths, "baseline_set": "windows-2025-x64"} if visual_paths else None,
                citations=visual_citations,
                unresolved_reasons=(
                    "visual_files_are_inventory_evidence_not_current_test_execution_or_manual_review"
                    if visual_paths
                    else "no_explicit_visual_manifest_and_binary_baseline_join",
                ),
                gap_ids=GUI_FIELD_GAPS["visual_baseline"],
            )
            fields["tests"] = _gui_field(
                "structural_only" if same_path_tests else "not_evidenced",
                {"same_path_test_ids": [str(row["id"]) for row in same_path_tests[:24]]} if same_path_tests else None,
                citations=[_gui_citation(row, "same_path_test_declaration") for row in same_path_tests[:24]],
                unresolved_reasons=(
                    "same_path_test_declarations_are_not_execution_or_surface_coverage_receipts"
                    if same_path_tests
                    else "no_same_path_test_declaration",
                    "same_path_test_list_is_bounded_to_24_records" if len(same_path_tests) > 24 else "",
                ),
                gap_ids=GUI_FIELD_GAPS["tests"],
            )
            fields["downstream_consumers"] = _gui_field(
                "not_evidenced",
                None,
                unresolved_reasons=("static_binding_does_not_resolve_complete_downstream_gui_or_artifact_consumers",),
                gap_ids=GUI_FIELD_GAPS["downstream_consumers"],
            )
            known_gap_ids = sorted({gap_id for field in fields.values() for gap_id in field["gap_ids"]})
            fields["known_gaps"] = _gui_field(
                "structural_only",
                known_gap_ids,
                citations=(source_citation,),
                unresolved_reasons=("gap_ids_are_dispositions_not_behavioral_evidence",),
                gap_ids=known_gap_ids or GUI_FIELD_GAPS["known_gaps"],
            )
            dossier_reasons = sorted(
                {str(reason) for field in fields.values() for reason in field["unresolved_reasons"] if str(reason)}
            )
            dossier_gap_ids = sorted({str(gap_id) for field in fields.values() for gap_id in field["gap_ids"]})
            dossier_state = (
                "explicitly_linked"
                if any(field["state"] == "explicitly_linked" for field in fields.values())
                else "structural_only"
            )
            surface["gui_dossier"] = {
                "id": stable_id("gui-dossier", surface["id"]),
                "surface_id": str(surface["id"]),
                "surface_kind": surface_kind,
                "source_commit": source_commit,
                "source_citation": source_citation,
                "evidence_state": dossier_state,
                "derivation": "compiler_structural_evidence_only",
                "field_count": len(GUI_DOSSIER_FIELDS),
                **fields,
                "unresolved_reasons": dossier_reasons,
                "gap_ids": dossier_gap_ids,
            }
            surface["unresolved_reasons"] = sorted(
                set(str(reason) for reason in surface.get("unresolved_reasons") or [])
                | {"gui_dossier_behavior_and_runtime_not_verified"}
            )


def _enrich_semantic_records(
    records: dict[str, list[dict[str, Any]]],
    file_records: list[dict[str, Any]],
    source_commit: str,
) -> None:
    """Attach explicit, coverage-honest line and symbol dossier fields.

    Static structure can establish ownership and possible relationships, but it
    cannot establish runtime behavior, test execution, security impact, or a
    human review. Those fields are therefore present with an explicit unknown
    state instead of being omitted or inferred as healthy.
    """

    files_by_path = {str(row["path"]): row for row in file_records}
    source_line_digests: dict[tuple[str, int], str] = {}
    for source in records["source_text"]:
        for source_line in source.get("lines") or []:
            source_line_digests[(str(source["path"]), int(source_line["number"]))] = str(source_line["line_digest"])
    tests_by_path: dict[str, list[dict[str, Any]]] = {}
    for test in records["tests"]:
        tests_by_path.setdefault(str(test["path"]), []).append(test)

    symbols_by_id = {str(row["id"]): row for row in records["symbols"]}
    structural_roots_by_path: dict[str, list[dict[str, Any]]] = {}
    for structural_entity in records["structural_entities"]:
        if structural_entity.get("root_scope") == "parsed_source":
            structural_roots_by_path.setdefault(str(structural_entity["path"]), []).append(structural_entity)
    symbol_by_position: dict[tuple[str, int], str] = {}
    # Larger spans are written first and smaller/deeper spans overwrite them.
    ranged_symbols = sorted(
        records["symbols"],
        key=lambda row: (
            str(row["path"]),
            -(
                int((row.get("range") or {}).get("end_line") or 0)
                - int((row.get("range") or {}).get("start_line") or 0)
            ),
            str(row["id"]),
        ),
    )
    for symbol in ranged_symbols:
        location = symbol.get("range") or {}
        start = location.get("start_line")
        end = location.get("end_line")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        for line_number in range(start, end + 1):
            symbol_by_position[(str(symbol["path"]), line_number)] = str(symbol["id"])

    calls_by_symbol: dict[tuple[str, str], list[str]] = {}
    calls_by_line: dict[tuple[str, int], list[str]] = {}
    calls_by_leaf: dict[str, list[dict[str, Any]]] = {}
    for call in records["calls"]:
        path = str(call["path"])
        containing = str(call.get("containing_symbol") or "")
        calls_by_symbol.setdefault((path, containing), []).append(str(call["id"]))
        start_line = (call.get("range") or {}).get("start_line")
        if isinstance(start_line, int):
            calls_by_line.setdefault((path, start_line), []).append(str(call["id"]))
        leaf = str(call.get("callee") or "").rsplit(".", 1)[-1]
        if leaf:
            calls_by_leaf.setdefault(leaf, []).append(call)

    imports_by_line: dict[tuple[str, int], list[str]] = {}
    imports_by_path: dict[str, list[str]] = {}
    for imported in records["imports"]:
        path = str(imported["path"])
        imports_by_path.setdefault(path, []).append(str(imported["id"]))
        start_line = (imported.get("range") or {}).get("start_line")
        if isinstance(start_line, int):
            imports_by_line.setdefault((path, start_line), []).append(str(imported["id"]))

    surfaces_by_symbol: dict[tuple[str, str], list[str]] = {}
    for group in ("routes", "components"):
        for surface in records[group]:
            path = str(surface["path"])
            handler = str(surface.get("handler") or surface.get("name") or "")
            surfaces_by_symbol.setdefault((path, handler), []).append(str(surface["id"]))

    test_paths = set(tests_by_path)
    for symbol in records["symbols"]:
        path = str(symbol["path"])
        qualified = str(symbol["qualified_name"])
        name = str(symbol["name"])
        documentation = str(symbol.get("documentation") or "").strip()
        purpose = documentation.split("\n\n", 1)[0].replace("\n", " ").strip()
        if not purpose:
            purpose = f"Compiler-identified {symbol['kind']} named {qualified}."
        callees = sorted(set(calls_by_symbol.get((path, qualified), [])))
        possible_callers = sorted(
            {
                str(call["id"])
                for call in calls_by_leaf.get(name, [])
                if str(call["path"]) != path or str(call.get("containing_symbol") or "") != qualified
            }
        )
        test_refs: set[str] = set()
        if path in test_paths:
            for test in tests_by_path[path]:
                location = test.get("range") or {}
                symbol_range = symbol.get("range") or {}
                if (
                    isinstance(location.get("start_line"), int)
                    and isinstance(symbol_range.get("start_line"), int)
                    and location["start_line"] <= symbol_range["start_line"] <= (location.get("end_line") or 0)
                ):
                    test_refs.add(str(test["id"]))
        for call in calls_by_leaf.get(name, []):
            call_path = str(call["path"])
            if call_path in test_paths:
                test_refs.update(str(test["id"]) for test in tests_by_path[call_path])
        surfaces = sorted(set(surfaces_by_symbol.get((path, qualified), [])))
        sensitive = any(
            token in path.lower()
            for token in ("security", "privacy", "redact", "credential", "secret", "auth", "custody")
        )
        criticality = "review_required" if bool(symbol.get("exported")) or surfaces or sensitive else "internal"
        unresolved = set(str(item) for item in symbol.get("unresolved_reasons") or [])
        unresolved.update(
            {
                "runtime_trace_not_collected",
                "state_effects_not_semantically_resolved",
                "failure_and_abstention_behavior_not_reviewed",
            }
        )
        if criticality == "review_required":
            unresolved.add("critical_or_public_symbol_requires_independent_human_review")
        symbol.update(
            {
                "stable_urn": symbol["id"],
                "path_and_range": {"path": path, "range": symbol.get("range")},
                "purpose": purpose[:4_000],
                "purpose_basis": "owned_docstring" if documentation else "compiler_structure",
                "responsibility": (
                    purpose[:4_000]
                    if documentation
                    else "Structural responsibility only; behavioral responsibility has not been independently reviewed."
                ),
                "parameters_and_types": list(symbol.get("parameters") or []),
                "return_or_output": symbol.get("return_annotation"),
                "state_read": [],
                "state_written": [],
                "external_effects": [],
                "failure_and_exception_behavior": "not_reviewed",
                "abstention_behavior": "not_reviewed",
                "callers": possible_callers,
                "caller_resolution": "static_name_inference",
                "callees": callees,
                "data_dependencies": sorted(set(imports_by_path.get(path, []))),
                "claims_produced_or_consumed": [],
                "tests": sorted(test_refs),
                "test_linkage": "same-file-or-static-name-inference" if test_refs else "not_linked",
                "runtime_trace_evidence": [],
                "runtime_trace_state": "not_collected",
                "performance_characteristics": "not_measured",
                "security_boundary": "security_sensitive_path_candidate" if sensitive else "not_classified",
                "downstream_surfaces": surfaces,
                "limitations": sorted(unresolved),
                "known_impact_if_changed": sorted(set(possible_callers + surfaces + callees)),
                "history": [{"source_commit": source_commit, "event": "structurally_mapped"}],
                "criticality": criticality,
                "explanation_depth": 1,
                "review_state": "not_human_reviewed",
                "unresolved_reasons": sorted(unresolved),
            }
        )

    _enrich_gui_dossiers(records, file_records, source_commit)

    for line in records["lines"]:
        path = str(line["path"])
        line_number = int(line["line"])
        file_record = files_by_path[path]
        symbol_id = symbol_by_position.get((path, line_number))
        symbol = symbols_by_id.get(symbol_id or "")
        path_roots = structural_roots_by_path.get(path, [])
        structural_root = path_roots[0] if len(path_roots) == 1 else None
        direct_tests: list[str] = []
        for test in tests_by_path.get(path, []):
            location = test.get("range") or {}
            if (
                isinstance(location.get("start_line"), int)
                and isinstance(location.get("end_line"), int)
                and location["start_line"] <= line_number <= location["end_line"]
            ):
                direct_tests.append(str(test["id"]))
        surface_refs = [] if symbol is None else list(symbol.get("downstream_surfaces") or [])
        unresolved = set(str(item) for item in line.get("unresolved_reasons") or [])
        unresolved.add("runtime_trace_not_collected")
        if symbol is not None:
            structural_mapping_basis = "symbol_range"
            semantic_entity = symbol_id
        elif structural_root is None:
            structural_mapping_basis = "structural_root_missing"
            semantic_entity = None
            unresolved.add("parser_owned_structural_root_missing_or_duplicated")
        elif line.get("syntax_kind") != "unresolved_text" or line.get("containing_symbol"):
            structural_mapping_basis = "parser_context"
            semantic_entity = str(structural_root["id"])
        else:
            structural_mapping_basis = "parser_structural_root"
            semantic_entity = str(structural_root["id"])
            unresolved.add("parser_specific_child_entity_not_available")
            unresolved.add("line_mapped_to_parser_owned_structural_root")
        # A symbol or typed parser-owned structural entity establishes Level 1.
        # File census records never satisfy this semantic denominator, and no
        # structural mapping establishes behavior, execution, correctness, or review.
        explanation_depth = 1 if semantic_entity is not None else 0
        unresolved.add("behavioral_semantics_not_verified")
        line.update(
            {
                "source_commit": source_commit,
                "line_number": line_number,
                "line_digest": source_line_digests[(path, line_number)],
                "syntax_depth": int(line.get("depth") or 0),
                "semantic_entity": semantic_entity,
                "owner": str(file_record["id"]),
                "structural_mapping_basis": structural_mapping_basis,
                "behavior_group": list(file_record.get("roles") or []),
                "inputs_and_outputs": {
                    "parameters": [] if symbol is None else list(symbol.get("parameters_and_types") or []),
                    "return_or_output": None if symbol is None else symbol.get("return_or_output"),
                    "derivation": structural_mapping_basis,
                },
                "claims_influenced": [],
                "callers_and_dependencies": sorted(
                    set(calls_by_line.get((path, line_number), []) + imports_by_line.get((path, line_number), []))
                ),
                "tests_covering_it": sorted(set(direct_tests)),
                "test_coverage_state": "structural_test_membership" if direct_tests else "not_executed_or_linked",
                "runtime_trace_state": "not_collected",
                "GUI_or_artifact_consumers": surface_refs,
                "security_and_privacy_effect": {
                    "source_exposure": file_record["privacy_exposure"],
                    "semantic_effect": "not_classified",
                },
                "current_or_historical": file_record.get("documentation_status") or "current_source",
                "explanation_depth": explanation_depth,
                "unresolved_reasons": sorted(unresolved),
            }
        )


def _ledger(
    *,
    source_commit: str | None,
    head_tree_oid: str | None,
    index_digest: str | None,
    source_tree_digest: str | None,
    status_digest: str | None,
    dirty: bool | None,
    file_records: list[dict[str, Any]],
    records: dict[str, list[dict[str, Any]]],
    parser_counts: Counter[str],
    fatal_errors: list[str],
    graphify: dict[str, Any],
    architecture_conformance: dict[str, Any],
    forbidden_content_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_status = Counter(str(row.get("parse_status")) for row in file_records)
    expected_lines = sum(int(row.get("nonblank_line_count") or 0) for row in file_records)
    actual_lines = len(records["lines"])
    unresolved_lines = sum(1 for row in records["lines"] if row.get("unresolved_reasons"))
    expected_source_text = sum(
        1
        for row in file_records
        if row.get("privacy_exposure") == "full"
        and row.get("language") != "binary"
        and row.get("content_digest") is not None
        and not row.get("classification_errors")
    )
    classified = sum(1 for row in file_records if not row.get("classification_errors"))
    full = sum(1 for row in file_records if row.get("privacy_exposure") == "full")
    metadata_only = len(file_records) - full
    binary_inventory_only = sum(1 for row in file_records if row.get("language") == "binary")
    safe_text_scan_eligible = sum(
        1
        for row in file_records
        if row.get("privacy_exposure") == "full"
        and row.get("language") != "binary"
        and row.get("content_digest") is not None
    )
    hard_failure = bool(fatal_errors)
    line_depths = Counter(int(row.get("explanation_depth") or 0) for row in records["lines"])
    symbol_depths = Counter(int(row.get("explanation_depth") or 0) for row in records["symbols"])
    expected_line_coordinates: set[tuple[str, int]] = set()
    source_line_counts: dict[str, int] = {}
    source_end_columns: dict[str, int | None] = {}
    for source in records["source_text"]:
        path = str(source.get("path") or "")
        raw = "".join(
            str(line.get("text") or "") + str(line.get("terminator") or "") for line in source.get("lines") or []
        ).encode("utf-8")
        try:
            decoded_lines = raw.decode("utf-8-sig", errors="strict").splitlines()
        except UnicodeDecodeError:
            decoded_lines = []
        source_line_counts[path] = len(decoded_lines)
        source_end_columns[path] = len(decoded_lines[-1]) if decoded_lines else None
        expected_line_coordinates.update(
            (path, number) for number, value in enumerate(decoded_lines, start=1) if value.strip()
        )

    line_rows_by_coordinate: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in records["lines"]:
        path = row.get("path")
        number = row.get("line")
        if isinstance(path, str) and isinstance(number, int):
            line_rows_by_coordinate.setdefault((path, number), []).append(row)
    exactly_accounted_lines = sum(
        1 for coordinate in expected_line_coordinates if len(line_rows_by_coordinate.get(coordinate, [])) == 1
    )

    safe_parsed_files = {
        str(row["id"]): row
        for row in file_records
        if row.get("privacy_exposure") == "full"
        and row.get("language") != "binary"
        and row.get("parse_status") == "parsed"
    }
    roots_by_file: dict[str, list[dict[str, Any]]] = {}
    for root in records["structural_entities"]:
        roots_by_file.setdefault(str(root.get("file_id") or ""), []).append(root)

    def valid_structural_root(root: dict[str, Any], file_record: dict[str, Any]) -> bool:
        path = str(file_record["path"])
        location = root.get("range")
        line_count = source_line_counts.get(path)
        if not isinstance(location, dict) or line_count is None:
            return False
        if line_count == 0:
            exact_range = root.get("range_state") == "empty_source" and all(
                location.get(field) is None for field in ("start_line", "start_column", "end_line", "end_column")
            )
        else:
            exact_range = (
                root.get("range_state") == "exact_source_lines"
                and location.get("start_line") == 1
                and location.get("start_column") == 0
                and location.get("end_line") == line_count
                and location.get("end_column") == source_end_columns.get(path)
            )
        return bool(
            exact_range
            and root.get("root_scope") == "parsed_source"
            and root.get("file_id") == file_record.get("id")
            and root.get("path") == path
            and root.get("parser") == file_record.get("parser")
            and root.get("parser_mode") == file_record.get("parser_mode")
            and root.get("parser_version") == file_record.get("parser_version")
            and root.get("language") == file_record.get("language")
            and root.get("roles") == file_record.get("roles")
            and root.get("source_basis") == file_record.get("content_source")
            and root.get("git_blob_oid") == file_record.get("git_blob_oid")
            and root.get("content_digest") == file_record.get("content_digest")
            and root.get("line_count") == line_count
            and root.get("nonblank_line_count") == file_record.get("nonblank_line_count")
            and root.get("parser_owned") is True
            and int(root.get("explanation_depth") or 0) >= 1
        )

    valid_root_by_file: dict[str, dict[str, Any]] = {}
    for file_id, file_record in safe_parsed_files.items():
        candidates = roots_by_file.get(file_id, [])
        if len(candidates) == 1 and valid_structural_root(candidates[0], file_record):
            valid_root_by_file[file_id] = candidates[0]
    structurally_rooted_sources = len(valid_root_by_file)
    valid_structural_roots = {str(root["id"]): root for root in valid_root_by_file.values()}
    symbols_by_id = {str(row["id"]): row for row in records["symbols"]}

    def valid_line_mapping(row: dict[str, Any]) -> bool:
        semantic_id = row.get("semantic_entity")
        path = row.get("path")
        number = row.get("line")
        if (
            not isinstance(semantic_id, str)
            or not semantic_id
            or not isinstance(path, str)
            or not isinstance(number, int)
            or int(row.get("explanation_depth") or 0) < 1
        ):
            return False
        symbol = symbols_by_id.get(semantic_id)
        if symbol is not None:
            location = symbol.get("range") or {}
            return bool(
                row.get("structural_mapping_basis") == "symbol_range"
                and symbol.get("file_id") == row.get("file_id")
                and symbol.get("path") == path
                and isinstance(location.get("start_line"), int)
                and isinstance(location.get("end_line"), int)
                and location["start_line"] <= number <= location["end_line"]
            )
        root = valid_structural_roots.get(semantic_id)
        return bool(
            root is not None
            and row.get("structural_mapping_basis") in {"parser_context", "parser_structural_root"}
            and root.get("file_id") == row.get("file_id")
            and root.get("path") == path
            and 1 <= number <= int(root.get("line_count") or 0)
        )

    structurally_mapped_lines = sum(
        1
        for coordinate in expected_line_coordinates
        if len(line_rows_by_coordinate.get(coordinate, [])) == 1
        and valid_line_mapping(line_rows_by_coordinate[coordinate][0])
    )
    critical_symbols = [row for row in records["symbols"] if row.get("criticality") == "review_required"]
    level_four_symbols = [
        row
        for row in critical_symbols
        if int(row.get("explanation_depth") or 0) >= 4 and row.get("review_state") == "independently_reviewed"
    ]
    dossier_fields = {
        "purpose",
        "responsibility",
        "parameters_and_types",
        "return_or_output",
        "callers",
        "callees",
        "tests",
        "runtime_trace_state",
        "downstream_surfaces",
        "limitations",
        "known_impact_if_changed",
        "explanation_depth",
        "review_state",
    }
    dossier_count = sum(1 for row in records["symbols"] if dossier_fields.issubset(row))
    gui_surfaces = [*records["routes"], *records["components"]]

    def valid_gui_dossier(surface: dict[str, Any]) -> bool:
        dossier = surface.get("gui_dossier")
        if not isinstance(dossier, dict):
            return False
        citation = dossier.get("source_citation")
        if (
            dossier.get("surface_id") != surface.get("id")
            or dossier.get("surface_kind") not in {"route", "component"}
            or dossier.get("source_commit") != source_commit
            or dossier.get("evidence_state") not in GUI_EVIDENCE_STATES
            or dossier.get("field_count") != len(GUI_DOSSIER_FIELDS)
            or not isinstance(citation, dict)
            or citation.get("record_id") != surface.get("id")
            or citation.get("path") != surface.get("path")
            or not isinstance(citation.get("start_line"), int)
            or not isinstance(citation.get("end_line"), int)
        ):
            return False
        for field_name in GUI_DOSSIER_FIELDS:
            field = dossier.get(field_name)
            if (
                not isinstance(field, dict)
                or field.get("state") not in GUI_EVIDENCE_STATES
                or not isinstance(field.get("citations"), list)
                or not isinstance(field.get("unresolved_reasons"), list)
                or not isinstance(field.get("gap_ids"), list)
                or not field.get("gap_ids")
            ):
                return False
        return True

    gui_dossier_count = sum(1 for row in gui_surfaces if valid_gui_dossier(row))
    gui_dossier_states = Counter(
        str((row.get("gui_dossier") or {}).get("evidence_state") or "missing") for row in gui_surfaces
    )
    gui_field_states = Counter(
        str(field.get("state") or "missing")
        for row in gui_surfaces
        for field_name in GUI_DOSSIER_FIELDS
        for field in [((row.get("gui_dossier") or {}).get(field_name) or {})]
    )
    total_records = sum(len(records[group]) for group in RECORD_GROUPS)
    typed_records = sum(
        1
        for group in RECORD_GROUPS
        for row in records[group]
        if isinstance(row.get("entity_type"), str) and bool(str(row["entity_type"]).strip())
    )
    entity_type_counts = Counter(
        str(row["entity_type"])
        for group in RECORD_GROUPS
        for row in records[group]
        if isinstance(row.get("entity_type"), str) and bool(str(row["entity_type"]).strip())
    )
    entity_disposition_counts = Counter(
        str(row["extraction_disposition"])
        for group in RECORD_GROUPS
        for row in records[group]
        if isinstance(row.get("extraction_disposition"), str) and bool(str(row["extraction_disposition"]).strip())
    )
    documentation_records_classified = sum(
        1
        for row in records["markdown"]
        if row.get("authority_classification")
        in {
            "current_authority",
            "current_explanatory",
            "accepted_decision",
            "historical_evidence",
            "superseded",
            "archived",
            "unresolved",
        }
    )
    exact_line_denominator = bool(
        len(expected_line_coordinates) == expected_lines
        and exactly_accounted_lines == expected_lines
        and actual_lines == expected_lines
        and set(line_rows_by_coordinate) == expected_line_coordinates
    )
    exact_structural_root_denominator = bool(
        structurally_rooted_sources == len(safe_parsed_files)
        and len(records["structural_entities"]) == len(safe_parsed_files)
        and set(roots_by_file) == set(safe_parsed_files)
    )
    graphify_source_bound = bool(
        isinstance(source_commit, str)
        and isinstance(source_tree_digest, str)
        and graphify.get("schema_version") == SCHEMA_VERSION
        and graphify.get("source_commit") == source_commit
        and graphify.get("source_tree_digest") == source_tree_digest
    )
    invariants = [
        {
            "name": "every_tracked_file_classified",
            "passed": classified == len(file_records),
            "expected": len(file_records),
            "actual": classified,
        },
        {
            "name": "every_nonblank_text_line_has_one_record",
            "passed": exact_line_denominator,
            "expected": expected_lines,
            "actual": exactly_accounted_lines,
        },
        {
            "name": "every_safe_parsed_source_has_one_structural_root",
            "passed": exact_structural_root_denominator,
            "expected": len(safe_parsed_files),
            "actual": structurally_rooted_sources,
        },
        {
            "name": "every_safe_line_structurally_mapped",
            "passed": exact_line_denominator and structurally_mapped_lines == expected_lines,
            "expected": expected_lines,
            "actual": structurally_mapped_lines,
        },
        {
            "name": "no_silent_parser_failure",
            "passed": parse_status.get("parser_error", 0) == 0,
            "expected": 0,
            "actual": parse_status.get("parser_error", 0),
        },
        {
            "name": "graphify_receipt_exact_source_bound",
            "passed": graphify_source_bound,
            "expected": 1,
            "actual": int(graphify_source_bound),
        },
        {
            "name": "every_safe_text_file_has_exact_source_record",
            "passed": expected_source_text == len(records["source_text"]),
            "expected": expected_source_text,
            "actual": len(records["source_text"]),
        },
        {
            "name": "publication_has_no_fatal_error",
            "passed": not hard_failure,
            "expected": 0,
            "actual": len(fatal_errors),
        },
        {
            "name": "every_published_record_has_entity_type",
            "passed": typed_records == total_records,
            "expected": total_records,
            "actual": typed_records,
        },
        {
            "name": "every_documentation_record_has_authority_classification",
            "passed": documentation_records_classified == len(records["markdown"]),
            "expected": len(records["markdown"]),
            "actual": documentation_records_classified,
        },
        {
            "name": "every_gui_surface_has_standardized_evidence_honest_dossier",
            "passed": gui_dossier_count == len(gui_surfaces),
            "expected": len(gui_surfaces),
            "actual": gui_dossier_count,
        },
    ]
    completeness_id = stable_id("completeness", source_commit or "unknown", source_tree_digest or "unknown")
    return {
        "id": completeness_id,
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
        "head_tree_oid": head_tree_oid,
        "index_digest": index_digest,
        "source_tree_digest": source_tree_digest,
        "tracked_status_digest": status_digest,
        "tracked_worktree_dirty": dirty,
        "hard_failure": hard_failure,
        "fatal_errors": sorted(set(fatal_errors)),
        "census": {
            "tracked_files": len(file_records),
            "classified_files": classified,
            "full_exposure_files": full,
            "metadata_only_files": metadata_only,
        },
        "parsing": {
            "status_counts": dict(sorted(parse_status.items())),
            "parser_counts": dict(sorted(parser_counts.items())),
            "expected_nonblank_lines": expected_lines,
            "line_records": actual_lines,
            "lines_with_explicit_unresolved_reasons": unresolved_lines,
        },
        "semantic_accounting": {
            "symbol_records": len(records["symbols"]),
            "symbol_dossiers": dossier_count,
            "safe_parsed_sources": len(safe_parsed_files),
            "structural_root_entities": structurally_rooted_sources,
            "structural_root_kind_counts": dict(
                sorted(Counter(str(row.get("kind") or "missing") for row in records["structural_entities"]).items())
            ),
            "structurally_mapped_lines": structurally_mapped_lines,
            "line_explanation_depth_counts": {str(key): value for key, value in sorted(line_depths.items())},
            "symbol_explanation_depth_counts": {str(key): value for key, value in sorted(symbol_depths.items())},
            "critical_or_public_symbols": len(critical_symbols),
            "critical_level_four_reviews": len(level_four_symbols),
            "gui_surface_records": len(gui_surfaces),
            "gui_dossiers": gui_dossier_count,
            "gui_dossier_evidence_state_counts": {str(key): value for key, value in sorted(gui_dossier_states.items())},
            "gui_dossier_field_state_counts": {str(key): value for key, value in sorted(gui_field_states.items())},
            "runtime_trace_state": "not_collected",
            "coverage_evidence_state": "structural_links_only",
            "consequential_claim_denominator_state": "not_declared",
            "typed_claim_records": len(records["claims"]),
            "bitemporal_event_ledger_state": "not_populated",
            "bitemporal_event_records": 0,
            "release_lifecycle_transition_receipt_state": "not_integrated",
        },
        "record_counts": {
            **{group: len(records[group]) for group in RECORD_GROUPS},
            **{f"entity_type::{key}": value for key, value in sorted(entity_type_counts.items())},
            **{f"entity_disposition::{key}": value for key, value in sorted(entity_disposition_counts.items())},
            **{f"gui_dossier_state::{key}": value for key, value in sorted(gui_dossier_states.items())},
            **{f"gui_dossier_field_state::{key}": value for key, value in sorted(gui_field_states.items())},
        },
        "graphify": graphify,
        "architecture_conformance": architecture_conformance,
        "privacy": {
            "primary_corpus": "selected_commit_git_tree_raw_blobs",
            "worktree_role": "separate_cleanliness_and_changed_during_read_check_only",
            "tracked_claude_agent_memory": "parsed_as_repository_history_cache",
            "machine_local_claude_memory": "outside_repository_not_read",
            "obsidian_vault": "outside_repository_not_read",
            "client_state": "not_read",
            "network": "not_used",
            "symlinks": "not_followed",
            "forbidden_content_scan": {
                "status": "passed" if not forbidden_content_findings else "failed",
                "scope": "allowlisted_utf8_text_payloads_only",
                "eligible_text_files": safe_text_scan_eligible,
                "rules": [name for name, _pattern in FORBIDDEN_CONTENT_RULES],
                "findings_count": len(forbidden_content_findings),
                "findings": sorted(
                    forbidden_content_findings,
                    key=lambda item: (str(item["path"]), int(item["line"]), str(item["rule"])),
                ),
                "matched_values_retained": False,
            },
            "binary_payload_scan": {
                "status": "not_performed_inventory_and_digest_only",
                "inventory_only_files": binary_inventory_only,
                "payload_bytes_embedded_in_projection": False,
                "format_aware_or_manual_review_receipt": "absent",
                "claim": "Binary artifacts are inventoried by type, size, and digest; this compiler does not claim decoded-content privacy review.",
            },
        },
        "invariants": invariants,
        "acceptance_gates": [
            {
                "name": "architecture_contract_declared_and_conformant",
                "passed": architecture_conformance.get("status") == "passed",
                "expected": True,
                "actual": architecture_conformance.get("status") == "passed",
            },
            {
                "name": "runtime_architecture_edges_observed_and_reconciled",
                "passed": architecture_conformance.get("runtime_observed") is True,
                "expected": True,
                "actual": architecture_conformance.get("runtime_observed") is True,
            },
            {
                "name": "every_symbol_has_dossier_fields",
                "passed": dossier_count == len(records["symbols"]),
                "expected": len(records["symbols"]),
                "actual": dossier_count,
            },
            {
                "name": "every_gui_surface_has_standardized_evidence_honest_dossier",
                "passed": gui_dossier_count == len(gui_surfaces),
                "expected": len(gui_surfaces),
                "actual": gui_dossier_count,
            },
            {
                "name": "every_safe_line_behaviorally_explained",
                "passed": len(records["lines"]) > 0
                and all(int(row.get("explanation_depth") or 0) >= 2 for row in records["lines"]),
                "expected": len(records["lines"]),
                "actual": sum(1 for row in records["lines"] if int(row.get("explanation_depth") or 0) >= 2),
            },
            {
                "name": "every_critical_or_public_symbol_level_four_reviewed",
                "passed": len(level_four_symbols) == len(critical_symbols),
                "expected": len(critical_symbols),
                "actual": len(level_four_symbols),
            },
            {
                "name": "exact_clean_commit_binding",
                "passed": dirty is False,
                "expected": False,
                "actual": dirty,
            },
            {
                "name": "every_binary_has_format_aware_privacy_review",
                "passed": binary_inventory_only == 0,
                "expected": binary_inventory_only,
                "actual": 0,
            },
            {
                "name": "runtime_trace_evidence_joined_to_source_records",
                "passed": bool(records["lines"])
                and all(row.get("runtime_trace_state") == "runtime_observed" for row in records["lines"]),
                "expected": len(records["lines"]),
                "actual": sum(1 for row in records["lines"] if row.get("runtime_trace_state") == "runtime_observed"),
            },
            {
                "name": "consequential_claim_denominator_closed",
                "passed": False,
                "expected": True,
                "actual": False,
            },
            {
                "name": "bitemporal_event_ledger_populated_and_replayable",
                "passed": False,
                "expected": True,
                "actual": False,
            },
            {
                "name": "release_lifecycle_transitions_integrated_and_receipted",
                "passed": False,
                "expected": True,
                "actual": False,
            },
        ],
    }


def _write_bytes(path: Path, value: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"sha256": sha256_bytes(value), "bytes": len(value)}


def _write_failure(output: Path, ledger: dict[str, Any]) -> None:
    _write_bytes(
        output / "architecture-conformance.json",
        canonical_json(ledger["architecture_conformance"]),
    )
    _write_bytes(output / "completeness.json", canonical_json(ledger))
    failure = {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "source_commit": ledger.get("source_commit"),
        "source_tree_digest": ledger.get("source_tree_digest"),
        "errors": ledger.get("fatal_errors", []),
        "completeness_id": ledger.get("id"),
    }
    _write_bytes(output / "failure.json", canonical_json(failure))


def _write_success(
    output: Path,
    records: dict[str, list[dict[str, Any]]],
    ledger: dict[str, Any],
    chunk_size: int,
) -> dict[str, Any]:
    manifest_groups: dict[str, Any] = {}
    for group in RECORD_GROUPS:
        group_records = records[group]
        effective_chunk_size = 1 if group == "source_text" else chunk_size
        pieces = list(chunked(group_records, effective_chunk_size))
        chunk_receipts: list[dict[str, Any]] = []
        for index, piece in enumerate(pieces):
            record_ids = [str(item["id"]) for item in piece]
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "record_type": group,
                "source_commit": ledger["source_commit"],
                "source_tree_digest": ledger["source_tree_digest"],
                "chunk_index": index,
                "chunk_count": len(pieces),
                "record_count": len(piece),
                "records_digest": digest_object(record_ids),
                "records": piece,
            }
            relative = f"chunks/{group}/{index:05d}.json"
            receipt = _write_bytes(output / relative, canonical_json(envelope))
            chunk_receipts.append({"path": relative, "record_count": len(piece), **receipt})
        manifest_groups[group] = {
            "record_count": len(group_records),
            "chunk_count": len(pieces),
            "records_digest": digest_object([str(item["id"]) for item in group_records]),
            "chunks": chunk_receipts,
        }
    completeness_receipt = _write_bytes(output / "completeness.json", canonical_json(ledger))
    graphify_receipt = _write_bytes(output / "graphify-metadata.json", canonical_json(ledger["graphify"]))
    architecture_receipt = _write_bytes(
        output / "architecture-conformance.json",
        canonical_json(ledger["architecture_conformance"]),
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "release_class": "dirty_preview" if ledger["tracked_worktree_dirty"] else "exact_commit",
        "source_commit": ledger["source_commit"],
        "head_tree_oid": ledger["head_tree_oid"],
        "index_digest": ledger["index_digest"],
        "source_tree_digest": ledger["source_tree_digest"],
        "tracked_worktree_dirty": ledger["tracked_worktree_dirty"],
        "chunk_size": chunk_size,
        "groups": manifest_groups,
        "completeness": {"path": "completeness.json", **completeness_receipt},
        "graphify_metadata": {"path": "graphify-metadata.json", **graphify_receipt},
        "architecture_conformance": {
            "path": "architecture-conformance.json",
            **architecture_receipt,
        },
    }
    manifest_receipt = _write_bytes(output / "manifest.json", canonical_json(manifest))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "manifest": {"path": "manifest.json", **manifest_receipt},
        "source_commit": ledger["source_commit"],
        "source_tree_digest": ledger["source_tree_digest"],
    }
    _write_bytes(output / "receipt.json", canonical_json(receipt))
    return manifest


def compile_repository(
    repository_root: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
    *,
    chunk_size: int = 2_000,
    allow_dirty_preview: bool = False,
) -> dict[str, Any]:
    """Compile a caller-selected Git worktree into a new output directory.

    The default is release-safe and refuses tracked changes. A caller may
    explicitly request a dirty preview; its manifest and claims remain marked
    as non-releaseable and the exact-source acceptance gate remains failed.
    """

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir() or not (root / ".git").exists():
        raise CompilationError(["repository_root must be a Git worktree directory"])
    if chunk_size <= 0 or chunk_size > 100_000:
        raise CompilationError(["chunk_size must be between 1 and 100000"])
    output = Path(output_directory).resolve(strict=False)
    if output.exists():
        raise CompilationError(["output_directory must not already exist"], output)
    if output == root or output == root / ".git":
        raise CompilationError(["output_directory cannot be the repository or Git directory"], output)
    output.mkdir(parents=True, exist_ok=False)

    records = _new_records()
    file_records: list[dict[str, Any]] = []
    parser_counts: Counter[str] = Counter()
    fatal_errors: list[str] = []
    source_commit: str | None = None
    source_commit_time: str | None = None
    head_tree_oid: str | None = None
    index_digest: str | None = None
    source_tree_digest: str | None = None
    status_digest: str | None = None
    dirty: bool | None = None
    graphify_metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": None,
        "source_tree_digest": None,
        "available": False,
        "status": "not_attempted",
        "stale": None,
        "unresolved_reasons": ["compilation_did_not_reach_graphify_projection"],
    }
    architecture_conformance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": None,
        "source_tree_digest": None,
        "status": "not_declared",
        "evidence_class": "architecture_contract_not_present_in_tracked_tree",
        "runtime_observed": False,
        "errors": ["tracked_architecture_contract_missing"],
        "limitations": ["No tracked architecture contract was available for this repository."],
        "receipt_digest": digest_object({"status": "not_declared"}),
    }
    snapshot_digests: dict[str, str] = {}
    ts_inputs: list[dict[str, str]] = []
    privacy_findings: list[dict[str, Any]] = []

    try:
        source_commit = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
        source_commit_time = _commit_time(root, source_commit)
        head_tree_oid = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
        index_entries = _git_census(root)
        commit_entries = _git_tree_census(root, source_commit)
        status_before = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
        status_digest = sha256_bytes(status_before)
        dirty = bool(status_before)
        nonstandard_index_flags = _nonstandard_index_flags(root)
        if dirty and not allow_dirty_preview:
            fatal_errors.append("tracked worktree is dirty; exact-commit compilation requires a clean tracked tree")
        if not dirty and nonstandard_index_flags:
            fatal_errors.extend(
                f"{path}: Git index flag {tag!r} prevents an exact-clean worktree proof"
                for path, tag in sorted(nonstandard_index_flags.items())
            )
        index_digest = digest_object(
            [
                {"mode": row.mode, "blob_oid": row.blob_oid, "stage": row.stage, "path": row.path}
                for row in index_entries
            ]
        )
        if index_entries != commit_entries and not dirty:
            fatal_errors.append("clean Git index census differs from selected commit tree census")
        entries = index_entries if dirty else commit_entries

        classifications: dict[str, dict[str, Any]] = {}
        for entry in entries:
            classification = classify_file(entry.path, entry.mode)
            classifications[entry.path] = classification
            for error in classification["classification_errors"]:
                fatal_errors.append(f"{entry.path}: classification: {error}")

        canonical_blobs = (
            {}
            if dirty
            else _read_git_blobs(
                root,
                [
                    entry
                    for entry in entries
                    if classifications[entry.path]["privacy_exposure"] == "full"
                    and not classifications[entry.path]["classification_errors"]
                ],
            )
        )

        for entry in entries:
            classification = classifications[entry.path]
            file_id = stable_id("file", entry.path)
            file_record: dict[str, Any] = {
                "id": file_id,
                "path": entry.path,
                "git_mode": entry.mode,
                "git_blob_oid": entry.blob_oid,
                "git_stage": entry.stage,
                "content_source": (
                    "metadata_only_git_object"
                    if classification["privacy_exposure"] == "metadata_only"
                    else "dirty_preview_worktree"
                    if dirty
                    else "selected_commit_git_blob"
                ),
                "language": classification["language"],
                "roles": classification["roles"],
                "media_type": classification["media_type"],
                "privacy_exposure": classification["privacy_exposure"],
                "privacy_reasons": classification["privacy_reasons"],
                "classification_errors": classification["classification_errors"],
                "size_bytes": None,
                "content_digest": None,
                "parse_status": "pending",
                "parser": None,
                "parser_mode": None,
                "parser_version": None,
                "line_count": None,
                "nonblank_line_count": 0,
                "documentation_status": None,
                "documentation_status_reasons": [],
                "unresolved_reasons": [],
            }
            file_records.append(file_record)
            if classification["classification_errors"]:
                file_record["parse_status"] = "classification_error"
                continue
            if classification["privacy_exposure"] == "metadata_only":
                file_record["size_bytes"] = _metadata_size(root, entry)
                file_record["parse_status"] = "metadata_only"
                file_record["unresolved_reasons"] = ["privacy_policy_prevents_content_read"]
                parser_counts["metadata_only"] += 1
                if classification["language"] == "binary":
                    file_record["parser"] = "binary_metadata"
                    file_record["unresolved_reasons"] = ["binary_payload_requires_format_aware_privacy_review"]
                    records["binaries"].append(
                        {
                            "id": stable_id("binary", entry.path),
                            "file_id": file_id,
                            "path": entry.path,
                            "media_type": classification["media_type"],
                            "size_bytes": file_record["size_bytes"],
                            "content_digest": None,
                            "git_blob_oid": entry.blob_oid,
                            "inspection_mode": "git_object_digest_and_metadata_only",
                            "privacy_exposure": "metadata_only",
                            "unresolved_reasons": ["decoded_binary_content_privacy_review_not_performed"],
                        }
                    )
                continue
            try:
                worktree_data, worktree_size = _read_regular(root, entry)
                snapshot_digests[entry.path] = sha256_bytes(worktree_data)
                if dirty:
                    data, size = worktree_data, worktree_size
                else:
                    data, size = canonical_blobs[entry.path]
            except CompilationError as exc:
                file_record["parse_status"] = "parser_error"
                fatal_errors.extend(exc.errors)
                continue
            digest = sha256_bytes(data)
            file_record["size_bytes"] = size
            file_record["content_digest"] = digest
            if classification["language"] == "binary":
                file_record["parse_status"] = "binary_inventory"
                file_record["parser"] = "binary_metadata"
                parser_counts["binary_metadata"] += 1
                records["binaries"].append(
                    {
                        "id": stable_id("binary", entry.path),
                        "file_id": file_id,
                        "path": entry.path,
                        "media_type": classification["media_type"],
                        "size_bytes": size,
                        "content_digest": digest,
                        "inspection_mode": "metadata_and_digest_only",
                    }
                )
                continue
            try:
                text = safe_decode_text(data, entry.path)
            except ParseFailure as exc:
                file_record["parse_status"] = "parser_error"
                file_record["unresolved_reasons"] = ["safe_text_detection_failed"]
                fatal_errors.append(str(exc))
                continue
            exact_text = data.decode("utf-8", errors="strict")
            findings = forbidden_content_findings(entry.path, exact_text)
            if findings:
                privacy_findings.extend(findings)
                file_record["parse_status"] = "parser_error"
                file_record["unresolved_reasons"] = ["forbidden_content_scan_failed"]
                fatal_errors.extend(
                    f"{item['path']}:{item['line']}: forbidden-content rule {item['rule']}" for item in findings
                )
                continue
            exact_lines = _exact_source_lines(exact_text)
            if "".join(str(line["text"]) + str(line["terminator"]) for line in exact_lines).encode("utf-8") != data:
                file_record["parse_status"] = "parser_error"
                file_record["unresolved_reasons"] = ["source_text_round_trip_failed"]
                fatal_errors.append(f"{entry.path}: exact UTF-8 source round-trip failed")
                continue
            records["source_text"].append(
                {
                    "id": stable_id("source-text", entry.path, digest),
                    "file_id": file_id,
                    "path": entry.path,
                    "encoding": "utf-8",
                    "source_basis": file_record["content_source"],
                    "git_blob_oid": entry.blob_oid,
                    "byte_count": len(data),
                    "content_digest": digest,
                    "line_count": len(exact_lines),
                    "lines": exact_lines,
                }
            )
            file_record["line_count"] = len(text.splitlines())
            file_record["nonblank_line_count"] = sum(1 for line in text.splitlines() if line.strip())
            if "documentation" in classification["roles"]:
                status_name, reasons = documentation_status(entry.path, text.splitlines()[:80])
                file_record["documentation_status"] = status_name
                file_record["documentation_status_reasons"] = reasons
            if classification["language"] in TYPESCRIPT_LANGUAGES:
                ts_inputs.append({"path": entry.path, "file_id": file_id, "text": text})
                continue
            try:
                result = parse_by_language(entry.path, file_id, classification["language"], text)
                _accept_parse_result(records, file_record, result, text)
                if any(ord(char) < 32 and char not in "\n\r\t\f" for char in text):
                    file_record["unresolved_reasons"] = sorted(
                        set(file_record["unresolved_reasons"] + ["sparse_non_nul_control_characters_preserved"])
                    )
                parser_counts[result.parser] += 1
            except ParseFailure as exc:
                file_record["parse_status"] = "parser_error"
                file_record["unresolved_reasons"] = ["owned_parser_failed"]
                fatal_errors.append(str(exc))

        if ts_inputs:
            try:
                ts_version, ts_results = _typescript_results(ts_inputs)
                for item in ts_inputs:
                    file_record = next(row for row in file_records if row["path"] == item["path"])
                    result = ts_results[item["path"]]
                    file_record["parser_version"] = ts_version
                    _accept_parse_result(records, file_record, result, item["text"])
                    if any(ord(char) < 32 and char not in "\n\r\t\f" for char in item["text"]):
                        file_record["unresolved_reasons"] = sorted(
                            set(file_record["unresolved_reasons"] + ["sparse_non_nul_control_characters_preserved"])
                        )
                    parser_counts[result.parser] += 1
            except ParseFailure as exc:
                fatal_errors.append(str(exc))
                for item in ts_inputs:
                    file_record = next(row for row in file_records if row["path"] == item["path"])
                    file_record["parse_status"] = "parser_error"
                    file_record["unresolved_reasons"] = ["typescript_batch_parser_failed"]

        for file_record in file_records:
            if "documentation" in file_record["roles"]:
                first_heading = next(
                    (
                        item.get("text")
                        for item in records["markdown"]
                        if item.get("file_id") == file_record["id"] and item.get("kind") == "heading"
                    ),
                    None,
                )
                records["documents"].append(
                    {
                        "id": stable_id("document", file_record["path"]),
                        "file_id": file_record["id"],
                        "path": file_record["path"],
                        "title": first_heading,
                        "status": file_record["documentation_status"],
                        "status_reasons": file_record["documentation_status_reasons"],
                        "line_count": file_record["line_count"],
                    }
                )
            if "dataset" in file_record["roles"]:
                records["datasets"].append(
                    {
                        "id": stable_id("dataset", file_record["path"]),
                        "file_id": file_record["id"],
                        "path": file_record["path"],
                        "format": file_record["language"],
                        "size_bytes": file_record["size_bytes"],
                        "content_digest": file_record["content_digest"],
                        "structured_record_count": sum(
                            1 for row in records["structured"] if row.get("file_id") == file_record["id"]
                        ),
                    }
                )
            if "manifest" in file_record["roles"]:
                records["manifests"].append(
                    {
                        "id": stable_id("manifest", file_record["path"]),
                        "file_id": file_record["id"],
                        "path": file_record["path"],
                        "language": file_record["language"],
                        "dependency_count": sum(
                            1 for row in records["dependencies"] if row.get("file_id") == file_record["id"]
                        ),
                        "content_digest": file_record["content_digest"],
                    }
                )
            if _is_config(file_record):
                records["configs"].append(
                    {
                        "id": stable_id("config", file_record["path"]),
                        "file_id": file_record["id"],
                        "path": file_record["path"],
                        "language": file_record["language"],
                        "roles": file_record["roles"],
                        "content_digest": file_record["content_digest"],
                    }
                )

        records["files"] = file_records
        source_tree_digest = digest_object(
            [
                {
                    "path": row["path"],
                    "git_mode": row["git_mode"],
                    "digest": row["content_digest"] or f"git-object:{row['git_blob_oid']}",
                }
                for row in sorted(file_records, key=lambda item: item["path"])
            ]
        )

        architecture_path = "master-reference/governance/architecture.json"
        tracked_paths = [entry.path for entry in entries]
        if architecture_path in set(tracked_paths):
            architecture_contract = load_contract(root / architecture_path)
            architecture_conformance = build_architecture_conformance(
                paths=tracked_paths,
                file_languages={str(row["path"]): str(row["language"]) for row in file_records},
                imports=records["imports"],
                calls=records["calls"],
                contract=architecture_contract,
                source_commit=source_commit,
                source_tree_digest=source_tree_digest,
            )
            fatal_errors.extend(
                f"architecture conformance: {error}" for error in architecture_conformance.get("errors", [])
            )
        else:
            architecture_core = {
                "schema_version": SCHEMA_VERSION,
                "source_commit": source_commit,
                "source_tree_digest": source_tree_digest,
                "status": "not_declared",
                "evidence_class": "architecture_contract_not_present_in_tracked_tree",
                "runtime_observed": False,
                "errors": ["tracked_architecture_contract_missing"],
                "limitations": [
                    "No tracked architecture contract was available; static structure was not treated as runtime truth."
                ],
            }
            architecture_conformance = {
                **architecture_core,
                "receipt_digest": digest_object(architecture_core),
            }
        # Architecture conformance is a compiler-corpus receipt.  Its payload
        # contract therefore advances with the manifest/chunk contract even
        # though the tracked architecture declaration has its own schema.
        architecture_core = {
            **{key: value for key, value in architecture_conformance.items() if key != "receipt_digest"},
            "schema_version": SCHEMA_VERSION,
        }
        architecture_conformance = {
            **architecture_core,
            "receipt_digest": digest_object(architecture_core),
        }

        safe_files = {
            row["path"]: row["id"]
            for row in file_records
            if row["privacy_exposure"] == "full" and not row["classification_errors"]
        }
        try:
            graphify_metadata, graph_nodes, graph_edges = project_graphify(
                root,
                source_commit,
                source_tree_digest,
                safe_files,
            )
            if dirty and graphify_metadata.get("available"):
                graphify_metadata["stale"] = True
                graphify_metadata["status"] = "stale"
                graphify_metadata.setdefault("unresolved_reasons", []).append(GRAPHIFY_DIRTY_PREVIEW_REASON)
            validate_graphify_metadata(graphify_metadata, graph_nodes, graph_edges)
            records["graph_nodes"] = graph_nodes
            records["graph_edges"] = graph_edges
        except GraphifyFailure as exc:
            fatal_errors.append(str(exc))
            graphify_metadata = {
                "schema_version": SCHEMA_VERSION,
                "source_commit": source_commit,
                "source_tree_digest": source_tree_digest,
                "available": True,
                "status": "parser_error",
                "stale": None,
                "unresolved_reasons": ["graphify_projection_failed"],
            }

        for path, expected_digest in sorted(snapshot_digests.items()):
            entry = next(item for item in entries if item.path == path)
            try:
                current_data, _ = _read_regular(root, entry)
            except CompilationError as exc:
                fatal_errors.extend(exc.errors)
                continue
            if sha256_bytes(current_data) != expected_digest:
                fatal_errors.append(f"{path}: file changed after compilation snapshot")
        try:
            verify_graphify_snapshot(root, graphify_metadata)
        except GraphifyFailure as exc:
            fatal_errors.append(str(exc))
        status_after = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
        if status_after != status_before:
            fatal_errors.append("tracked Git status changed during compilation")
        source_commit_after = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
        head_tree_after = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
        entries_after = _git_census(root)
        commit_entries_after = _git_tree_census(root, source_commit_after)
        index_digest_after = digest_object(
            [
                {"mode": row.mode, "blob_oid": row.blob_oid, "stage": row.stage, "path": row.path}
                for row in entries_after
            ]
        )
        if source_commit_after != source_commit:
            fatal_errors.append("Git HEAD changed during compilation")
        if head_tree_after != head_tree_oid:
            fatal_errors.append("Git HEAD tree changed during compilation")
        if index_digest_after != index_digest:
            fatal_errors.append("Git index census changed during compilation")
        if not dirty and commit_entries_after != commit_entries:
            fatal_errors.append("selected commit tree census changed during compilation")

        files_by_id = {str(row["id"]): row for row in file_records}
        for record in records["markdown"]:
            owner_file = files_by_id.get(str(record.get("file_id")))
            status = owner_file.get("documentation_status") if owner_file else None
            record["documentation_status"] = status or "unresolved"
            record["authority_classification"] = {
                "current_owner": "current_authority",
                "current_declared": "current_explanatory",
                "accepted_decision": "accepted_decision",
                "historical": "historical_evidence",
                "repository_memory_cache": "historical_evidence",
                "superseded_decision": "superseded",
                "rejected_decision": "archived",
            }.get(str(status), "unresolved")

        _enrich_semantic_records(records, file_records, source_commit)
        duplicate_errors = _sort_and_validate(records)
        fatal_errors.extend(duplicate_errors)
        completeness_id = stable_id("completeness", source_commit, source_tree_digest)
        records["claims"] = _claims(
            source_commit,
            source_commit_time,
            source_tree_digest,
            file_records,
            len(records["lines"]),
            graphify_metadata,
            completeness_id,
            bool(dirty),
        )
        evidence_universe = {
            str(record["id"])
            for group in RECORD_GROUPS
            if group != "claims"
            for record in records[group]
            if isinstance(record.get("id"), str)
        }
        evidence_universe.add(completeness_id)
        fatal_errors.extend(
            f"claim_integrity:{violation}"
            for violation in validate_claims(
                records["claims"],
                known_evidence_ids=evidence_universe,
                expected_source_commit=source_commit,
            )
        )
        _assign_entity_types(records)
        fatal_errors.extend(_sort_and_validate(records))
    except CompilationError as exc:
        fatal_errors.extend(exc.errors)
    except Exception as exc:  # unexpected failures are disclosed, never silently downgraded
        fatal_errors.append(f"unexpected compiler failure: {_sanitize_error(exc, root, output)}")

    sanitized_errors = sorted(set(_sanitize_error(error, root, output) for error in fatal_errors))
    if graphify_metadata.get("schema_version") is None:
        graphify_metadata["schema_version"] = SCHEMA_VERSION
    if graphify_metadata.get("source_commit") is None:
        graphify_metadata["source_commit"] = source_commit
    if graphify_metadata.get("source_tree_digest") is None:
        graphify_metadata["source_tree_digest"] = source_tree_digest
    ledger = _ledger(
        source_commit=source_commit,
        head_tree_oid=head_tree_oid,
        index_digest=index_digest,
        source_tree_digest=source_tree_digest,
        status_digest=status_digest,
        dirty=dirty,
        file_records=file_records,
        records=records,
        parser_counts=parser_counts,
        fatal_errors=sanitized_errors,
        graphify=graphify_metadata,
        architecture_conformance=architecture_conformance,
        forbidden_content_findings=privacy_findings,
    )
    if sanitized_errors or not all(item["passed"] for item in ledger["invariants"]):
        if not sanitized_errors:
            ledger["fatal_errors"] = ["completeness invariant failed"]
            ledger["hard_failure"] = True
        _write_failure(output, ledger)
        raise CompilationError(ledger["fatal_errors"], output)
    return _write_success(output, records, ledger, chunk_size)


def _accept_parse_result(
    records: dict[str, list[dict[str, Any]]],
    file_record: dict[str, Any],
    result: ParseResult,
    text: str,
) -> None:
    lines = nonblank_line_records(
        file_record["path"],
        file_record["id"],
        file_record["language"],
        text,
        result.line_context,
    )
    expected = int(file_record["nonblank_line_count"])
    if len(lines) != expected:
        raise ParseFailure(
            f"{file_record['path']}: nonblank line accounting mismatch expected={expected} actual={len(lines)}"
        )
    records["lines"].extend(lines)
    records["structural_entities"].append(_structural_root_record(file_record, result, text))
    _merge_parse_result(records, result)
    file_record["parse_status"] = "parsed"
    file_record["parser"] = result.parser
    file_record["parser_mode"] = result.parser_mode
    file_record["unresolved_reasons"] = sorted(set(result.unresolved_reasons))
