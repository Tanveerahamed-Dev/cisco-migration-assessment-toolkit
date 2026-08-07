"""Deterministic whole-repository intelligence compiler.

The tracked Git index is the only primary corpus. Current worktree bytes are
hashed and parsed so an uncommitted but tracked edit cannot be mistaken for
HEAD. Optional Graphify data is a secondary, privacy-filtered projection and is
never used to fill gaps in the primary census.
"""

from __future__ import annotations

import json
import os
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

from .graphify import GraphifyFailure, project_graphify, verify_graphify_snapshot
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


def _metadata_size(root: Path, entry: GitEntry) -> int | None:
    if entry.mode == "160000":
        return None
    path = _tracked_path(root, entry.path, allow_final_symlink=True)
    return path.lstat().st_size


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

    for group in RECORD_GROUPS:
        singular = group[:-1] if group.endswith("s") else group
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
    graph_freshness = "unknown" if dirty or graphify.get("stale") is None else (
        "stale" if graphify.get("stale") is True else "current"
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
            source_line_digests[(str(source["path"]), int(source_line["number"]))] = str(
                source_line["line_digest"]
            )
    tests_by_path: dict[str, list[dict[str, Any]]] = {}
    for test in records["tests"]:
        tests_by_path.setdefault(str(test["path"]), []).append(test)

    symbols_by_id = {str(row["id"]): row for row in records["symbols"]}
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

    for line in records["lines"]:
        path = str(line["path"])
        line_number = int(line["line"])
        file_record = files_by_path[path]
        symbol_id = symbol_by_position.get((path, line_number))
        symbol = symbols_by_id.get(symbol_id or "")
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
        if int(line.get("depth") or 0) < 1 and not line.get("containing_symbol") and symbol is None:
            explanation_depth = 0
            unresolved.add("line_not_attached_to_semantic_symbol")
        else:
            explanation_depth = 1
            unresolved.add("behavioral_semantics_not_verified")
        line.update(
            {
                "source_commit": source_commit,
                "line_number": line_number,
                "line_digest": source_line_digests[(path, line_number)],
                "syntax_depth": int(line.get("depth") or 0),
                "semantic_entity": symbol_id or str(file_record["id"]),
                "owner": str(file_record["id"]),
                "behavior_group": list(file_record.get("roles") or []),
                "inputs_and_outputs": {
                    "parameters": [] if symbol is None else list(symbol.get("parameters_and_types") or []),
                    "return_or_output": None if symbol is None else symbol.get("return_or_output"),
                    "derivation": "containing_symbol_structure" if symbol is not None else "not_available",
                },
                "claims_influenced": [],
                "callers_and_dependencies": sorted(
                    set(
                        calls_by_line.get((path, line_number), [])
                        + imports_by_line.get((path, line_number), [])
                    )
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
        if isinstance(row.get("extraction_disposition"), str)
        and bool(str(row["extraction_disposition"]).strip())
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
    invariants = [
        {
            "name": "every_tracked_file_classified",
            "passed": classified == len(file_records),
            "expected": len(file_records),
            "actual": classified,
        },
        {
            "name": "every_nonblank_text_line_has_one_record",
            "passed": expected_lines == actual_lines,
            "expected": expected_lines,
            "actual": actual_lines,
        },
        {
            "name": "no_silent_parser_failure",
            "passed": parse_status.get("parser_error", 0) == 0,
            "expected": 0,
            "actual": parse_status.get("parser_error", 0),
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
            "line_explanation_depth_counts": {str(key): value for key, value in sorted(line_depths.items())},
            "symbol_explanation_depth_counts": {str(key): value for key, value in sorted(symbol_depths.items())},
            "critical_or_public_symbols": len(critical_symbols),
            "critical_level_four_reviews": len(level_four_symbols),
            "runtime_trace_state": "not_collected",
            "coverage_evidence_state": "structural_links_only",
        },
        "record_counts": {
            **{group: len(records[group]) for group in RECORD_GROUPS},
            **{f"entity_type::{key}": value for key, value in sorted(entity_type_counts.items())},
            **{
                f"entity_disposition::{key}": value
                for key, value in sorted(entity_disposition_counts.items())
            },
        },
        "graphify": graphify,
        "architecture_conformance": architecture_conformance,
        "privacy": {
            "primary_corpus": "git_ls_files_only",
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
                "name": "every_safe_line_behaviorally_explained",
                "passed": len(records["lines"]) > 0 and all(int(row.get("explanation_depth") or 0) >= 2 for row in records["lines"]),
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
                "actual": sum(
                    1 for row in records["lines"] if row.get("runtime_trace_state") == "runtime_observed"
                ),
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
        entries = _git_census(root)
        source_commit = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip()
        source_commit_time = _commit_time(root, source_commit)
        head_tree_oid = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii", errors="strict").strip()
        status_before = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
        status_digest = sha256_bytes(status_before)
        dirty = bool(status_before)
        if dirty and not allow_dirty_preview:
            fatal_errors.append(
                "tracked worktree is dirty; exact-commit compilation requires a clean tracked tree"
            )
        index_digest = digest_object(
            [{"mode": row.mode, "blob_oid": row.blob_oid, "stage": row.stage, "path": row.path} for row in entries]
        )

        classifications: dict[str, dict[str, Any]] = {}
        for entry in entries:
            classification = classify_file(entry.path, entry.mode)
            classifications[entry.path] = classification
            for error in classification["classification_errors"]:
                fatal_errors.append(f"{entry.path}: classification: {error}")

        for entry in entries:
            classification = classifications[entry.path]
            file_id = stable_id("file", entry.path)
            file_record: dict[str, Any] = {
                "id": file_id,
                "path": entry.path,
                "git_mode": entry.mode,
                "git_blob_oid": entry.blob_oid,
                "git_stage": entry.stage,
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
                    file_record["unresolved_reasons"] = [
                        "binary_payload_requires_format_aware_privacy_review"
                    ]
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
                            "unresolved_reasons": [
                                "decoded_binary_content_privacy_review_not_performed"
                            ],
                        }
                    )
                continue
            try:
                data, size = _read_regular(root, entry)
            except CompilationError as exc:
                file_record["parse_status"] = "parser_error"
                fatal_errors.extend(exc.errors)
                continue
            digest = sha256_bytes(data)
            snapshot_digests[entry.path] = digest
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
                    f"{item['path']}:{item['line']}: forbidden-content rule {item['rule']}"
                    for item in findings
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
                f"architecture conformance: {error}"
                for error in architecture_conformance.get("errors", [])
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

        safe_files = {
            row["path"]: row["id"]
            for row in file_records
            if row["privacy_exposure"] == "full" and not row["classification_errors"]
        }
        try:
            graphify_metadata, graph_nodes, graph_edges = project_graphify(root, source_commit, safe_files)
            if dirty and graphify_metadata.get("available"):
                graphify_metadata["stale"] = True
                graphify_metadata["status"] = "stale"
                graphify_metadata.setdefault("unresolved_reasons", []).append(
                    "tracked_worktree_changes_are_newer_than_commit_bound_graph"
                )
            records["graph_nodes"] = graph_nodes
            records["graph_edges"] = graph_edges
        except GraphifyFailure as exc:
            fatal_errors.append(str(exc))
            graphify_metadata = {
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
    _merge_parse_result(records, result)
    file_record["parse_status"] = "parsed"
    file_record["parser"] = result.parser
    file_record["parser_mode"] = result.parser_mode
    file_record["unresolved_reasons"] = sorted(set(result.unresolved_reasons))
