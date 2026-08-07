"""Deterministic, citation-first enhancement packages over exact compiler data.

This module is deliberately read-only. It does not propose code, execute tests,
write artifacts, or infer runtime truth. It closes only relationships supported
by compiler records, bounded static candidates, and the exact architecture and
gap contracts captured by the compiler.
"""

from __future__ import annotations

import json
import posixpath
from collections import defaultdict
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from governance.architecture import path_dispositions, validate_contract

from .corpus import COMPILER_SCHEMA_VERSION, _validate_gate_contract
from .git_state import _git, _tree, observe_git_state
from .model import ContinuityInputError, digest_object, safe_relative, sha256_bytes


DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_RECORDS = 250
DEFAULT_MAX_EDGES = 2_000
MAX_DEPTH = 8
MAX_RECORDS = 2_000
MAX_EDGES = 10_000
MAX_SEED_VALUE_BYTES = 4 * 1024
MAX_SERIALIZED_SEED_BYTES = 256 * 1024
MAX_SERIALIZED_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_UNRESOLVED_SAMPLES = 20
ENHANCEMENT_SCHEMA_VERSION = "1.1.0"

ID_GROUPS = {
    "binary": "binaries",
    "call": "calls",
    "claim": "claims",
    "component": "components",
    "config": "configs",
    "dataset": "datasets",
    "dependency": "dependencies",
    "document": "documents",
    "file": "files",
    "graph-edge": "graph_edges",
    "graph-node": "graph_nodes",
    "heading": "markdown",
    "import": "imports",
    "line": "lines",
    "manifest": "manifests",
    "md-link": "markdown",
    "md-status": "markdown",
    "route": "routes",
    "source-text": "source_text",
    "structural-entity": "structural_entities",
    "structured": "structured",
    "symbol": "symbols",
    "test": "tests",
    "workflow": "workflows",
}

IMPACT_GROUPS = frozenset(
    {
        "binaries",
        "calls",
        "claims",
        "components",
        "configs",
        "datasets",
        "dependencies",
        "documents",
        "files",
        "graph_edges",
        "graph_nodes",
        "imports",
        "manifests",
        "routes",
        "structural_entities",
        "symbols",
        "tests",
        "workflows",
    }
)

REFERENCE_FIELDS = frozenset(
    {
        "GUI_or_artifact_consumers",
        "artifact_ids",
        "assertion_group_id",
        "callees",
        "callers",
        "callers_and_dependencies",
        "claims_influenced",
        "claims_produced_or_consumed",
        "conflicts_with",
        "data_dependencies",
        "derived_from",
        "downstream_surfaces",
        "evidence_ids",
        "file_id",
        "job_ids",
        "known_impact_if_changed",
        "owner",
        "permission_ids",
        "semantic_entity",
        "source",
        "step_ids",
        "target",
        "tests",
        "tests_covering_it",
    }
)

SURFACE_FIELDS = frozenset({"GUI_or_artifact_consumers", "downstream_surfaces"})
SURFACE_GROUPS = frozenset({"components", "documents", "routes", "workflows"})


@dataclass
class ScanLedger:
    """Bounded disclosure of corpus work; never stores scanned record bodies."""

    records_by_group: dict[str, int] = dataclass_field(default_factory=dict)
    passes_by_group: dict[str, int] = dataclass_field(default_factory=dict)

    def start(self, group: str) -> None:
        self.passes_by_group[group] = self.passes_by_group.get(group, 0) + 1

    def record(self, group: str) -> None:
        self.records_by_group[group] = self.records_by_group.get(group, 0) + 1

    def result(self, bundle: Any) -> dict[str, Any]:
        io = bundle.io_scan_counts() if hasattr(bundle, "io_scan_counts") else {
            "validated_chunk_reads": 0,
            "validated_chunk_bytes": 0,
            "validated_group_passes": {},
        }
        return {
            "record_scan_count": sum(self.records_by_group.values()),
            "record_scans_by_group": dict(sorted(self.records_by_group.items())),
            "record_group_passes": dict(sorted(self.passes_by_group.items())),
            **io,
        }


def _iter_group(bundle: Any, group: str, scans: ScanLedger) -> Iterator[dict[str, Any]]:
    scans.start(group)
    if hasattr(bundle, "iter_group"):
        values = bundle.iter_group(group)
    else:
        records = getattr(bundle, "records", None)
        if not isinstance(records, dict):
            raise ContinuityInputError("compiler record access is unavailable")
        raw = records.get(group)
        if not isinstance(raw, list):
            raise ContinuityInputError(f"compiler record group is not a list: {group}")
        values = iter(raw)
    for record in values:
        scans.record(group)
        if not isinstance(record, dict):
            raise ContinuityInputError(f"compiler record is not an object: {group}")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ContinuityInputError(f"compiler {group} record has an invalid stable id")
        yield record


def _id_group(identifier: str) -> str | None:
    parts = identifier.split(":", 3)
    if len(parts) != 4 or parts[0] != "urn" or parts[1] != "atlas" or not parts[3]:
        return None
    return ID_GROUPS.get(parts[2])


def _find_id(bundle: Any, identifier: str, scans: ScanLedger) -> tuple[str, dict[str, Any]] | None:
    group = _id_group(identifier)
    if group is None or group == "source_text":
        return None
    match: dict[str, Any] | None = None
    for record in _iter_group(bundle, group, scans):
        if record["id"] != identifier:
            continue
        if match is not None:
            raise ContinuityInputError(f"compiler bundle contains duplicate stable id: {identifier}")
        match = record
    return None if match is None else (group, match)


def _find_file(bundle: Any, path: str, scans: ScanLedger) -> dict[str, Any] | None:
    match: dict[str, Any] | None = None
    for record in _iter_group(bundle, "files", scans):
        if record.get("path") != path:
            continue
        if match is not None:
            raise ContinuityInputError(f"compiler bundle duplicates file path: {path}")
        match = record
    return match


def _validate_line_semantic_target(bundle: Any, line: Mapping[str, Any], scans: ScanLedger) -> None:
    basis = line.get("structural_mapping_basis")
    target_id = line.get("semantic_entity")
    if not isinstance(target_id, str) or not target_id:
        raise ContinuityInputError("compiler line record lacks a semantic Level-1 target")
    target_group = _id_group(target_id)
    if target_group == "files":
        raise ContinuityInputError("compiler file ownership may not qualify as a line semantic target")
    if basis == "symbol_range":
        required_group = "symbols"
    elif basis in {"parser_context", "parser_structural_root"}:
        required_group = "structural_entities"
    else:
        raise ContinuityInputError(f"compiler line has an unsupported structural mapping basis: {basis!r}")
    if target_group != required_group:
        raise ContinuityInputError("compiler line semantic target kind contradicts its mapping basis")
    target = _find_id(bundle, target_id, scans)
    if target is None or target[0] != required_group:
        raise ContinuityInputError("compiler line semantic target is absent")
    target_record = target[1]
    if target_record.get("file_id") != line.get("file_id") or target_record.get("path") != line.get("path"):
        raise ContinuityInputError("compiler line semantic target is not in the same tracked file")
    if required_group == "structural_entities" and (
        target_record.get("root_scope") != "parsed_source"
        or target_record.get("parser_owned") is not True
    ):
        raise ContinuityInputError("compiler non-symbol line target is not a parser-owned structural root")


def _path(record: Mapping[str, Any]) -> str | None:
    value = record.get("path") or record.get("source_file")
    if not isinstance(value, str) or not value:
        return None
    try:
        return safe_relative(value)
    except ContinuityInputError:
        return None


def _citation(bundle: Any, group: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "record_id": record.get("id"),
        "record_type": group,
        "path": _path(record),
        "range": record.get("range"),
    }


def _summary(bundle: Any, group: str, record: Mapping[str, Any], *, distance: int | None = None) -> dict[str, Any]:
    value = {
        "id": record.get("id"),
        "record_type": group,
        "path": _path(record),
        "name": (
            record.get("qualified_name")
            or record.get("name")
            or record.get("predicate")
            or record.get("label")
        ),
        "range": record.get("range"),
        "explanation_depth": record.get("explanation_depth"),
        "citation": _citation(bundle, group, record),
    }
    if distance is not None:
        value["distance"] = distance
    return value


def _binding(bundle: Any, repository_root: Path, scans: ScanLedger) -> dict[str, Any]:
    manifest = bundle.manifest
    if manifest.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ContinuityInputError(
            f"unsupported compiler schema: {manifest.get('schema_version')!r}; expected {COMPILER_SCHEMA_VERSION}"
        )
    if manifest.get("release_class") != "exact_commit":
        raise ContinuityInputError("enhancement packages require compiler release_class exact_commit")
    if manifest.get("tracked_worktree_dirty") is not False:
        raise ContinuityInputError("enhancement packages refuse dirty compiler projections")
    completeness = getattr(bundle, "completeness", None)
    if not isinstance(completeness, dict):
        raise ContinuityInputError("compiler completeness ledger is unavailable")
    _validate_gate_contract(manifest, completeness)

    root = repository_root.resolve(strict=True)
    observed = observe_git_state(root, str(bundle.source_commit))
    errors = list(observed["errors"])
    if observed["head_commit"] != bundle.source_commit:
        errors.append("compiler_source_commit_is_stale")
    if observed["head_tree"] != manifest.get("head_tree_oid"):
        errors.append("compiler_head_tree_is_stale")
    if observed["changed_paths"]:
        errors.append("repository_worktree_or_index_is_dirty")
    index_rows: list[dict[str, Any]] = []
    index_by_path: dict[str, tuple[str, str, int]] = {}
    for row in (item for item in _git(root, "ls-files", "--stage", "-z").split(b"\0") if item):
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, object_id, stage_text = metadata.decode("ascii", errors="strict").split(" ")
            path = safe_relative(raw_path.decode("utf-8", errors="strict"))
            stage = int(stage_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContinuityInputError("could not parse exact Git index census") from exc
        if path in index_by_path:
            errors.append(f"duplicate_or_unmerged_index_path:{path}")
        index_by_path[path] = (mode, object_id, stage)
        index_rows.append({"mode": mode, "blob_oid": object_id, "stage": stage, "path": path})
        if stage != 0:
            errors.append(f"unmerged_index_stage:{path}:{stage}")
    for row in (item for item in _git(root, "ls-files", "-v", "-z").split(b"\0") if item):
        if len(row) < 3 or row[1:2] != b" ":
            raise ContinuityInputError("could not parse Git index flags")
        try:
            tag = row[:1].decode("ascii", errors="strict")
            path = safe_relative(row[2:].decode("utf-8", errors="strict"))
        except UnicodeDecodeError as exc:
            raise ContinuityInputError("could not decode Git index flags") from exc
        if tag != "H":
            errors.append(f"nonstandard_index_flag:{path}:{tag}")
    commit_tree = _tree(root, str(bundle.source_commit))
    compiler_paths: set[str] = set()
    for record in _iter_group(bundle, "files", scans):
        if not isinstance(record.get("path"), str):
            errors.append("invalid_compiler_file_record")
            continue
        path = str(record["path"])
        if path in compiler_paths:
            errors.append(f"duplicate_compiler_file_path:{path}")
        compiler_paths.add(path)
        tree_item = commit_tree.get(path)
        index_item = index_by_path.get(path)
        if tree_item is None or index_item is None:
            continue
        index_mode, index_oid, index_stage = index_item
        if (
            record.get("git_mode") != tree_item["mode"]
            or record.get("git_blob_oid") != tree_item["object_id"]
            or record.get("git_stage") != 0
            or index_mode != tree_item["mode"]
            or index_oid != tree_item["object_id"]
            or index_stage != 0
        ):
            errors.append(f"compiler_index_commit_tree_metadata_mismatch:{path}")
    if compiler_paths != set(commit_tree) or set(index_by_path) != set(commit_tree):
        errors.append("compiler_index_commit_tree_census_mismatch")
    observed_index_digest = digest_object(index_rows)
    if observed_index_digest != manifest.get("index_digest"):
        errors.append("compiler_index_digest_mismatch")
    if errors:
        raise ContinuityInputError("exact source binding failed: " + ",".join(sorted(set(errors))))
    return {
        "source_commit": bundle.source_commit,
        "head_tree_oid": manifest.get("head_tree_oid"),
        "index_digest": manifest.get("index_digest"),
        "observed_index_digest": observed_index_digest,
        "source_tree_digest": bundle.source_tree_digest,
        "release_class": manifest.get("release_class"),
        "tracked_worktree_dirty": False,
        "observed_head_commit": observed["head_commit"],
        "observed_head_tree": observed["head_tree"],
        "observed_changed_paths": [],
        "observed_material_digest": observed["diff_digest"],
        "observed_tracked_status_digest": observed["tracked_status_digest"],
        "observed_tracked_status_clean": observed["tracked_status_clean"],
        "validation_basis": "exact_compiler_bundle_plus_clean_tracked_git_state",
    }


def _source_bytes(
    bundle: Any,
    repository_root: Path,
    relative: str,
    scans: ScanLedger,
) -> tuple[bytes, dict[str, Any]]:
    file_record = _find_file(bundle, relative, scans)
    if file_record is None:
        raise ContinuityInputError(f"compiler file record is absent: {relative}")
    if (
        file_record.get("privacy_exposure") != "full"
        or file_record.get("content_source") != "selected_commit_git_blob"
        or not isinstance(file_record.get("content_digest"), str)
    ):
        raise ContinuityInputError(f"compiler did not approve exact source bytes: {relative}")

    # The lazy production path reads the already-approved selected-commit blob
    # directly and never scans the potentially unbounded source_text group.
    sources = [] if hasattr(bundle, "iter_group") else [
        record
        for record in getattr(bundle, "records", {}).get("source_text", [])
        if isinstance(record, dict) and record.get("path") == relative
    ]
    source_id: str | None = None
    if len(sources) == 1:
        source = sources[0]
        if source.get("source_basis") != "selected_commit_git_blob":
            raise ContinuityInputError(f"compiler source-text basis is not exact: {relative}")
        lines = source.get("lines")
        if not isinstance(lines, list):
            raise ContinuityInputError(f"compiler source-text lines are unavailable: {relative}")
        pieces: list[str] = []
        for expected_number, line in enumerate(lines, start=1):
            if (
                not isinstance(line, dict)
                or line.get("number") != expected_number
                or not isinstance(line.get("text"), str)
                or line.get("terminator") not in {"", "\n", "\r", "\r\n"}
            ):
                raise ContinuityInputError(f"compiler source-text line is malformed: {relative}")
            pieces.append(str(line["text"]) + str(line["terminator"]))
        raw = "".join(pieces).encode("utf-8")
        source_id = str(source.get("id") or "") or None
        if (
            source.get("content_digest") != file_record.get("content_digest")
            or source.get("byte_count") != file_record.get("size_bytes")
            or source.get("git_blob_oid") != file_record.get("git_blob_oid")
        ):
            raise ContinuityInputError(f"compiler source-text/file custody differs: {relative}")
    elif len(sources) == 0:
        blob_oid = file_record.get("git_blob_oid")
        if not isinstance(blob_oid, str) or len(blob_oid) not in {40, 64}:
            raise ContinuityInputError(f"compiler Git blob identity is unavailable: {relative}")
        raw = _git(repository_root.resolve(strict=True), "cat-file", "blob", blob_oid)
    else:
        raise ContinuityInputError(f"compiler source-text record is duplicated: {relative}")
    if len(raw) != file_record.get("size_bytes") or sha256_bytes(raw) != file_record.get("content_digest"):
        raise ContinuityInputError(f"exact source bytes differ from compiler receipt: {relative}")
    return raw, {
        "path": relative,
        "file_id": file_record.get("id"),
        "source_text_id": source_id,
        "git_blob_oid": file_record.get("git_blob_oid"),
        "sha256": file_record.get("content_digest"),
        "bytes": file_record.get("size_bytes"),
        "source_basis": "compiler_source_text" if source_id else "compiler_approved_git_blob",
    }


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContinuityInputError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ContinuityInputError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuityInputError(f"invalid exact JSON source {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityInputError(f"exact JSON source is not an object: {label}")
    return value


def _architecture(
    bundle: Any,
    repository_root: Path,
    scans: ScanLedger,
) -> tuple[dict[str, Any], dict[str, Any]]:
    relative = "master-reference/governance/architecture.json"
    raw, citation = _source_bytes(bundle, repository_root, relative, scans)
    contract = _json_object(raw, relative)
    errors = validate_contract(contract)
    if errors:
        raise ContinuityInputError("exact architecture contract is invalid: " + ",".join(errors))
    return contract, citation


def _gap(
    bundle: Any,
    repository_root: Path,
    gap_id: str,
    scans: ScanLedger,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    relative = "master-reference/content/delivery-governance.json"
    raw, citation = _source_bytes(bundle, repository_root, relative, scans)
    governance = _json_object(raw, relative)
    gaps = governance.get("gaps")
    if not isinstance(gaps, list):
        raise ContinuityInputError("exact delivery governance has no gap list")
    matches = [item for item in gaps if isinstance(item, dict) and item.get("id") == gap_id]
    if len(matches) > 1:
        raise ContinuityInputError(f"exact delivery governance duplicates gap id: {gap_id}")
    return (matches[0] if matches else None), citation


def _reference_values(record: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = record.get(field)
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list):
        return tuple(sorted({item for item in value if isinstance(item, str) and item}))
    return ()


def _import_candidate_paths(record: Mapping[str, Any]) -> tuple[str, ...]:
    module = record.get("module")
    origin = _path(record)
    if not isinstance(module, str) or not module or origin is None:
        return ()
    candidates: list[str] = []
    if origin.endswith((".py", ".pyi")):
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            base = PurePosixPath(origin).parent
            for _ in range(max(0, dots - 1)):
                base = base.parent
            suffix = module[dots:].replace(".", "/")
            stem = (base / suffix).as_posix() if suffix else base.as_posix()
        else:
            stem = module.replace(".", "/")
        candidates.extend((f"{stem}.py", f"{stem}/__init__.py"))
    elif module.startswith("."):
        base = posixpath.normpath(posixpath.join(PurePosixPath(origin).parent.as_posix(), module))
        suffixes = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
        candidates.extend(base + suffix for suffix in suffixes)
        candidates.extend(f"{base}/index{suffix}" for suffix in suffixes[1:])
    return tuple(sorted(set(candidates)))


def _edge(
    source: str,
    target: str,
    relation: str,
    evidence_class: str,
    citation: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "source": source,
        "target": target,
        "relation": relation,
        "evidence_class": evidence_class,
        "citation": dict(citation),
    }
    return {"id": f"urn:atlas:continuity-edge:{digest_object(core)}", **core}


def _group_available(bundle: Any, group: str) -> bool:
    if hasattr(bundle, "groups"):
        return group in bundle.groups
    records = getattr(bundle, "records", None)
    return isinstance(records, dict) and group in records


def _edge_key(value: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    citation = value["citation"]
    return (
        str(value["source"]),
        str(value["target"]),
        str(value["relation"]),
        str(value["evidence_class"]),
        str(citation.get("record_id") or citation.get("path") or ""),
    )


def _symbol_candidates(
    bundle: Any,
    callee: str,
    scans: ScanLedger,
) -> tuple[int, list[dict[str, Any]]]:
    leaf = callee.rsplit(".", 1)[-1]
    qualified: list[dict[str, Any]] = []
    named: list[dict[str, Any]] = []
    qualified_count = 0
    named_count = 0
    for record in _iter_group(bundle, "symbols", scans):
        if record.get("qualified_name") == callee:
            qualified_count += 1
            if len(qualified) <= MAX_UNRESOLVED_SAMPLES:
                qualified.append(record)
        elif record.get("name") == leaf:
            named_count += 1
            if len(named) <= MAX_UNRESOLVED_SAMPLES:
                named.append(record)
    return (qualified_count, qualified) if qualified_count else (named_count, named)


def _bounded_impact_closure(
    bundle: Any,
    seed_group: str,
    seed_record: dict[str, Any],
    scans: ScanLedger,
    *,
    max_depth: int,
    max_records: int,
    max_edges: int,
) -> tuple[
    dict[str, tuple[str, dict[str, Any]]],
    dict[str, int],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Construct only the bounded seed closure while streaming corpus groups."""

    seed_id = str(seed_record["id"])
    retained: dict[str, tuple[str, dict[str, Any]]] = {seed_id: (seed_group, seed_record)}
    distances = {seed_id: 0}
    edges: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    unresolved_omitted = 0
    omitted_observations = 0
    omitted_samples: set[str] = set()
    depth_limit_hit = False
    record_limit_hit = False
    edge_limit_hit = False

    def unresolved_add(value: dict[str, Any]) -> None:
        nonlocal unresolved_omitted
        if len(unresolved) < max(max_records, MAX_UNRESOLVED_SAMPLES):
            unresolved.append(value)
        else:
            unresolved_omitted += 1

    def omit(identifier: str) -> None:
        nonlocal omitted_observations
        omitted_observations += 1
        if len(omitted_samples) < MAX_UNRESOLVED_SAMPLES:
            omitted_samples.add(identifier)

    def offer(
        group: str,
        record: dict[str, Any],
        value: dict[str, Any],
        *,
        next_distance: int,
        allow_new: bool,
        next_frontier: set[str],
    ) -> None:
        nonlocal depth_limit_hit, record_limit_hit, edge_limit_hit
        identifier = str(record["id"])
        key = _edge_key(value)
        if key in edges:
            return
        is_new = identifier not in retained
        if is_new and not allow_new:
            depth_limit_hit = True
            omit(identifier)
            return
        if is_new and len(retained) >= max_records:
            record_limit_hit = True
            omit(identifier)
            return
        if len(edges) >= max_edges:
            edge_limit_hit = True
            if is_new:
                omit(identifier)
            return
        if is_new:
            retained[identifier] = (group, record)
            distances[identifier] = next_distance
            next_frontier.add(identifier)
        if value["source"] in retained and value["target"] in retained:
            edges[key] = value

    frontier = {seed_id}
    for depth in range(max_depth + 1):
        if not frontier:
            break
        allow_new = depth < max_depth
        next_frontier: set[str] = set()

        # Outgoing exact stable-ID references from the bounded frontier.
        for identifier in sorted(frontier):
            group, record = retained[identifier]
            for reference_field in sorted(REFERENCE_FIELDS):
                for reference in _reference_values(record, reference_field):
                    if reference == identifier:
                        continue
                    target = retained.get(reference)
                    if target is None:
                        target = _find_id(bundle, reference, scans)
                    if target is None or target[0] not in IMPACT_GROUPS:
                        unresolved_add(
                            {
                                "category": "unresolved_compiler_reference",
                                "record_id": identifier,
                                "record_type": group,
                                "field": reference_field,
                                "reference": reference,
                            }
                        )
                        continue
                    target_group, target_record = target
                    evidence_class = (
                        f"graphify_{record.get('extraction_mode') or 'undisclosed'}"
                        if group == "graph_edges" and reference_field in {"source", "target"}
                        else "compiler_declared_reference"
                    )
                    offer(
                        target_group,
                        target_record,
                        _edge(
                            identifier,
                            reference,
                            reference_field,
                            evidence_class,
                            {**_citation(bundle, group, record), "field": reference_field},
                        ),
                        next_distance=depth + 1,
                        allow_new=allow_new,
                        next_frontier=next_frontier,
                    )

            if group == "imports":
                candidates: list[dict[str, Any]] = []
                for candidate_path in _import_candidate_paths(record):
                    candidate = _find_file(bundle, candidate_path, scans)
                    if candidate is not None:
                        candidates.append(candidate)
                if len(candidates) == 1:
                    offer(
                        "files",
                        candidates[0],
                        _edge(
                            identifier,
                            str(candidates[0]["id"]),
                            "statically_resolved_import_path",
                            "static_candidate_not_runtime_observation",
                            {**_citation(bundle, group, record), "field": "module", "module": record.get("module")},
                        ),
                        next_distance=depth + 1,
                        allow_new=allow_new,
                        next_frontier=next_frontier,
                    )
                elif len(candidates) > 1:
                    unresolved_add(
                        {
                            "category": "ambiguous_static_import_target",
                            "record_id": identifier,
                            "module": record.get("module"),
                            "candidate_paths": sorted(str(item.get("path")) for item in candidates),
                        }
                    )
                else:
                    unresolved_add(
                        {
                            "category": "unresolved_or_external_static_import",
                            "record_id": identifier,
                            "module": record.get("module"),
                        }
                    )

            if group == "calls":
                callee = record.get("callee")
                if isinstance(callee, str) and callee:
                    candidate_count, candidates = _symbol_candidates(bundle, callee, scans)
                    if candidate_count == 1:
                        offer(
                            "symbols",
                            candidates[0],
                            _edge(
                                identifier,
                                str(candidates[0]["id"]),
                                "static_callee_name_candidate",
                                "static_candidate_not_runtime_observation",
                                {**_citation(bundle, group, record), "field": "callee", "callee": callee},
                            ),
                            next_distance=depth + 1,
                            allow_new=allow_new,
                            next_frontier=next_frontier,
                        )
                    elif candidate_count > 1:
                        unresolved_add(
                            {
                                "category": "ambiguous_static_call_target",
                                "record_id": identifier,
                                "callee": callee,
                                "candidate_count": candidate_count,
                                "candidate_ids": sorted(str(item["id"]) for item in candidates)[
                                    :MAX_UNRESOLVED_SAMPLES
                                ],
                            }
                        )
                    else:
                        unresolved_add(
                            {
                                "category": "unresolved_or_external_static_call",
                                "record_id": identifier,
                                "callee": callee,
                            }
                        )

        # Incoming references are found by streaming one group at a time.  No
        # reverse index or repository-wide record graph is retained.
        for group in sorted(IMPACT_GROUPS):
            if not _group_available(bundle, group):
                continue
            for record in _iter_group(bundle, group, scans):
                identifier = str(record["id"])
                for reference_field in sorted(REFERENCE_FIELDS):
                    for reference in _reference_values(record, reference_field):
                        if reference not in frontier or identifier == reference:
                            continue
                        evidence_class = (
                            f"graphify_{record.get('extraction_mode') or 'undisclosed'}"
                            if group == "graph_edges" and reference_field in {"source", "target"}
                            else "compiler_declared_reference"
                        )
                        offer(
                            group,
                            record,
                            _edge(
                                identifier,
                                reference,
                                reference_field,
                                evidence_class,
                                {**_citation(bundle, group, record), "field": reference_field},
                            ),
                            next_distance=depth + 1,
                            allow_new=allow_new,
                            next_frontier=next_frontier,
                        )
        frontier = next_frontier

    if unresolved_omitted:
        unresolved.append(
            {
                "category": "unresolved_sample_budget_reached",
                "omitted_observation_count": unresolved_omitted,
            }
        )
    reasons = []
    if depth_limit_hit:
        reasons.append("max_depth_reached")
    if record_limit_hit:
        reasons.append("max_records_reached")
    if edge_limit_hit:
        reasons.append("max_edges_reached")
    traversal = {
        "max_depth": max_depth,
        "max_records": max_records,
        "max_edges": max_edges,
        "included_records": len(retained),
        "included_edges": len(edges),
        "truncated": bool(reasons),
        "truncation_reasons": reasons,
        "omitted_record_candidate_count": omitted_observations,
        "omitted_record_candidate_count_basis": "bounded_candidate_observations_may_repeat_across_depth_scans",
        "omitted_record_candidate_ids": sorted(omitted_samples),
    }
    return (
        retained,
        distances,
        sorted(edges.values(), key=lambda item: item["id"]),
        sorted(
            unresolved,
            key=lambda item: (
                str(item.get("category")),
                str(item.get("record_id")),
                str(item.get("reference") or item.get("module") or item.get("callee") or ""),
            ),
        ),
        traversal,
    )


def _affected_owners(
    records: Mapping[str, tuple[str, dict[str, Any]]],
    distances: Mapping[str, int],
    contract: Mapping[str, Any],
    contract_citation: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = sorted(
        {
            path
            for identifier in distances
            if (path := _path(records[identifier][1])) is not None
        }
    )
    definitions = {
        str(row.get("id")): (kind, row)
        for kind, collection in (
            ("component", contract.get("components", [])),
            ("exclusion", contract.get("exclusions", [])),
        )
        if isinstance(collection, list)
        for row in collection
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    owner_paths: dict[tuple[str, str], list[str]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    for path in paths:
        matches = path_dispositions(path, contract)
        if len(matches) != 1:
            unresolved.append(
                {
                    "category": "architecture_owner_unresolved",
                    "path": path,
                    "matches": list(matches),
                }
            )
            continue
        owner_paths[(matches[0]["kind"], matches[0]["id"])].append(path)
    owners: list[dict[str, Any]] = []
    for (kind, identifier), owned_paths in sorted(owner_paths.items()):
        definition = definitions.get(identifier, (kind, {}))[1]
        owners.append(
            {
                "id": identifier,
                "kind": kind,
                "layer": definition.get("layer"),
                "trust_zone": definition.get("trust_zone"),
                "affected_paths": owned_paths,
                "citation": {
                    **dict(contract_citation),
                    "architecture_disposition_id": identifier,
                },
            }
        )
    return owners, unresolved


def _surfaces(
    bundle: Any,
    closure_records: Mapping[str, tuple[str, dict[str, Any]]],
    distances: Mapping[str, int],
) -> list[dict[str, Any]]:
    values: dict[tuple[str, str, str], dict[str, Any]] = {}
    for identifier in sorted(distances):
        group, record = closure_records[identifier]
        if group in SURFACE_GROUPS:
            values[(group, identifier, "record")] = {
                "kind": group,
                "surface_id": identifier,
                "declared_by": identifier,
                "field": "record_type",
                "resolved": True,
                "in_closure": True,
                "surface": _summary(bundle, group, record, distance=distances[identifier]),
                "citation": _citation(bundle, group, record),
            }
        for field in sorted(SURFACE_FIELDS):
            for surface_id in _reference_values(record, field):
                target = closure_records.get(surface_id)
                key = (field, identifier, surface_id)
                values[key] = {
                    "kind": field,
                    "surface_id": surface_id,
                    "declared_by": identifier,
                    "field": field,
                    "resolved": target is not None,
                    "in_closure": surface_id in distances,
                    "surface": None if target is None else _summary(bundle, *target),
                    "citation": {**_citation(bundle, group, record), "field": field},
                }
    return sorted(values.values(), key=lambda item: (item["kind"], item["surface_id"], item["declared_by"]))


def _compiler_gates(bundle: Any) -> list[dict[str, Any]]:
    completeness = bundle.completeness
    citation = {
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "completeness_id": completeness.get("id"),
    }
    rows: list[dict[str, Any]] = []
    for gate_class, name in (("hard_invariant", "invariants"), ("semantic_acceptance", "acceptance_gates")):
        values = completeness.get(name)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            rows.append(
                {
                    "name": item["name"],
                    "gate_class": gate_class,
                    "current_passed": item.get("passed") is True,
                    "expected": item.get("expected"),
                    "actual": item.get("actual"),
                    "citation": citation,
                }
            )
    return sorted(rows, key=lambda item: (item["gate_class"], item["name"]))


def _unresolved_categories(
    bundle: Any,
    closure_records: Mapping[str, tuple[str, dict[str, Any]]],
    distances: Mapping[str, int],
    graph_unresolved: list[dict[str, Any]],
    owner_unresolved: list[dict[str, Any]],
    traversal: Mapping[str, Any],
    surfaces: list[dict[str, Any]],
    tests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in graph_unresolved:
        if item.get("record_id") in distances:
            buckets[str(item["category"])].append(item)
    for item in owner_unresolved:
        buckets[str(item["category"])].append(item)
    for identifier in sorted(distances):
        group, record = closure_records[identifier]
        reasons = record.get("unresolved_reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                if isinstance(reason, str) and reason:
                    buckets["compiler_record_uncertainty"].append(
                        {
                            "record_id": identifier,
                            "record_type": group,
                            "reason": reason,
                        }
                    )
    graphify = bundle.completeness.get("graphify", {})
    if (
        not isinstance(graphify, dict)
        or graphify.get("available") is not True
        or graphify.get("stale") is not False
        or graphify.get("status") != "current"
    ):
        buckets["graphify_not_current"].append(
            {
                "available": graphify.get("available") if isinstance(graphify, dict) else None,
                "stale": graphify.get("stale") if isinstance(graphify, dict) else None,
                "status": graphify.get("status") if isinstance(graphify, dict) else None,
            }
        )
    semantic = bundle.completeness.get("semantic_accounting", {})
    if not isinstance(semantic, dict) or semantic.get("runtime_trace_state") != "runtime_observed":
        buckets["runtime_impact_not_observed"].append(
            {"state": semantic.get("runtime_trace_state") if isinstance(semantic, dict) else None}
        )
    if not isinstance(semantic, dict) or semantic.get("coverage_evidence_state") not in {
        "executed_line_and_branch_coverage",
        "field_validated",
    }:
        buckets["executed_coverage_not_proven"].append(
            {"state": semantic.get("coverage_evidence_state") if isinstance(semantic, dict) else None}
        )
    if traversal.get("truncated"):
        buckets["bounded_closure_truncated"].append(
            {
                "reasons": traversal.get("truncation_reasons"),
                "omitted_record_candidate_count": traversal.get("omitted_record_candidate_count"),
                "omitted_record_candidate_ids": traversal.get("omitted_record_candidate_ids"),
            }
        )
    if not surfaces:
        buckets["no_gui_or_artifact_surface_linked"].append(
            {"basis": "bounded_compiler_closure_contains_no_surface record or reference"}
        )
    if not tests:
        buckets["no_test_record_linked"].append(
            {"basis": "bounded_compiler_closure_contains_no_test record"}
        )
    return [
        {
            "category": category,
            "count": len(items),
            "samples": sorted(items, key=lambda item: json.dumps(item, sort_keys=True))[:20],
            "sample_truncated": len(items) > 20,
        }
        for category, items in sorted(buckets.items())
    ]


def _current_behavior(group: str, record: Mapping[str, Any], citation: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "purpose",
        "responsibility",
        "problem",
        "current_scope",
        "state",
        "status",
        "disposition",
        "parse_status",
        "language",
        "roles",
    )
    result: list[dict[str, Any]] = []
    for field in fields:
        if field not in record:
            continue
        value = record[field]
        if value is None or value == "" or value == () or value == [] or value == {}:
            continue
        result.append(
            {"field": field, "value": value, "citation": {**dict(citation), "field": field}}
        )
    return result


def _validate_limits(max_depth: int, max_records: int, max_edges: int) -> None:
    if not isinstance(max_depth, int) or not 0 <= max_depth <= MAX_DEPTH:
        raise ContinuityInputError(f"max_depth must be between 0 and {MAX_DEPTH}")
    if not isinstance(max_records, int) or not 1 <= max_records <= MAX_RECORDS:
        raise ContinuityInputError(f"max_records must be between 1 and {MAX_RECORDS}")
    if not isinstance(max_edges, int) or not 1 <= max_edges <= MAX_EDGES:
        raise ContinuityInputError(f"max_edges must be between 1 and {MAX_EDGES}")


def _revalidate_after_traversal(
    bundle: Any,
    repository_root: Path,
    scans: ScanLedger,
    before: Mapping[str, Any],
) -> dict[str, Any]:
    after = _binding(bundle, repository_root, scans)
    if dict(before) != after:
        raise ContinuityInputError("exact tracked Git state changed during enhancement traversal")
    return {**after, "post_traversal_revalidated": True}


def _abstained(
    bundle: Any,
    repository_root: Path,
    scans: ScanLedger,
    binding: Mapping[str, Any],
    *,
    reason: str,
    seed: Mapping[str, Any],
    detail: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    final_binding = _revalidate_after_traversal(bundle, repository_root, scans, binding)
    result: dict[str, Any] = {
        "schema_version": ENHANCEMENT_SCHEMA_VERSION,
        "package_type": "atlas_enhancement_package",
        "status": "abstained",
        "reason": reason,
        "seed": dict(seed),
        "source_binding": final_binding,
        "corpus_scan": scans.result(bundle),
        "side_effects": "none",
    }
    if detail is not None:
        result["detail"] = detail
    if extra:
        result.update(extra)
    return 3, result


def build_enhancement_package(
    bundle: Any,
    repository_root: Path,
    *,
    seed_kind: str,
    seed_value: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> tuple[int, dict[str, Any]]:
    """Build one bounded enhancement scaffold without mutating any source."""

    _validate_limits(max_depth, max_records, max_edges)
    if seed_kind not in {"id", "file", "gap"}:
        raise ContinuityInputError("enhancement seed_kind must be id, file, or gap")
    if not isinstance(seed_value, str) or not seed_value.strip():
        raise ContinuityInputError("enhancement seed_value must be nonempty text")
    if len(seed_value.encode("utf-8")) > MAX_SEED_VALUE_BYTES:
        raise ContinuityInputError(f"enhancement seed_value exceeds {MAX_SEED_VALUE_BYTES} UTF-8 bytes")
    scans = ScanLedger()
    binding = _binding(bundle, repository_root, scans)

    seed_group: str
    seed_record: dict[str, Any]
    seed_source: dict[str, Any]
    if seed_kind == "id":
        routed_group = _id_group(seed_value)
        if routed_group == "source_text":
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="source_text_seed_is_unbounded_use_file_or_line_query",
                seed={"kind": seed_kind, "value": seed_value},
            )
        if routed_group is None:
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="stable_seed_kind_is_not_routable",
                seed={"kind": seed_kind, "value": seed_value},
            )
        target = _find_id(bundle, seed_value, scans)
        if target is None:
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="stable_seed_not_found_in_exact_bundle",
                seed={"kind": seed_kind, "value": seed_value},
            )
        seed_group, seed_record = target
        seed_source = _citation(bundle, seed_group, seed_record)
    elif seed_kind == "file":
        relative = safe_relative(seed_value)
        file_record = _find_file(bundle, relative, scans)
        if file_record is None:
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="file_seed_not_found_in_exact_bundle",
                seed={"kind": seed_kind, "value": relative},
            )
        seed_group, seed_record = "files", file_record
        seed_source = _citation(bundle, seed_group, seed_record)
    else:
        try:
            gap_record, gap_citation = _gap(bundle, repository_root, seed_value, scans)
        except ContinuityInputError as exc:
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="gap_governance_evidence_unavailable",
                detail=str(exc),
                seed={"kind": seed_kind, "value": seed_value},
            )
        if gap_record is None:
            return _abstained(
                bundle,
                repository_root,
                scans,
                binding,
                reason="gap_seed_not_found_in_exact_governance",
                seed={"kind": seed_kind, "value": seed_value},
                extra={"gap_source": gap_citation},
            )
        seed_group = "gaps"
        seed_record = {
            **gap_record,
            "path": gap_citation["path"],
            "file_id": gap_citation["file_id"],
            "unresolved_reasons": [
                "curated_gap_has_no_automatic_code_impact_link_unless_declared_elsewhere"
            ],
        }
        seed_source = {
            "source_commit": bundle.source_commit,
            "source_tree_digest": bundle.source_tree_digest,
            "record_id": gap_record["id"],
            "record_type": "gap",
            **gap_citation,
        }

    if seed_group == "lines":
        _validate_line_semantic_target(bundle, seed_record, scans)

    seed_bytes = len(json.dumps(seed_record, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if seed_bytes > MAX_SERIALIZED_SEED_BYTES:
        return _abstained(
            bundle,
            repository_root,
            scans,
            binding,
            reason="seed_record_exceeds_serialization_limit",
            seed={"kind": seed_kind, "value": seed_value},
            extra={"seed_record_bytes": seed_bytes, "seed_record_byte_limit": MAX_SERIALIZED_SEED_BYTES},
        )

    contract, contract_citation = _architecture(bundle, repository_root, scans)
    graph_records, distances, closure_edges, graph_unresolved, traversal = _bounded_impact_closure(
        bundle,
        seed_group,
        seed_record,
        scans,
        max_depth=max_depth,
        max_records=max_records,
        max_edges=max_edges,
    )
    seed_id = str(seed_record["id"])
    closure = [
        _summary(bundle, *graph_records[identifier], distance=distances[identifier])
        for identifier in sorted(distances, key=lambda item: (distances[item], item))
    ]
    owners, owner_unresolved = _affected_owners(
        graph_records,
        distances,
        contract,
        contract_citation,
    )
    surfaces = _surfaces(bundle, graph_records, distances)
    tests = [item for item in closure if item["record_type"] == "tests"]
    workflows = [item for item in closure if item["record_type"] == "workflows"]
    unresolved = _unresolved_categories(
        bundle,
        graph_records,
        distances,
        graph_unresolved,
        owner_unresolved,
        traversal,
        surfaces,
        tests,
    )
    affected_paths = sorted({item["path"] for item in closure if item["path"] is not None})
    blocking_categories = {
        "architecture_owner_unresolved",
        "bounded_closure_truncated",
        "no_gui_or_artifact_surface_linked",
        "no_test_record_linked",
    }
    blockers = sorted(
        item["category"] for item in unresolved if item["category"] in blocking_categories
    )
    current_citation = _citation(bundle, seed_group, seed_record) if seed_group != "gaps" else seed_source
    final_binding = _revalidate_after_traversal(bundle, repository_root, scans, binding)
    corpus_scan = scans.result(bundle)
    traversal = {
        **traversal,
        "corpus_scan": corpus_scan,
        "construction_model": "seed_directed_streaming_no_global_record_graph",
    }
    core = {
        "schema_version": ENHANCEMENT_SCHEMA_VERSION,
        "package_type": "atlas_enhancement_package",
        "status": "answered",
        "decision_state": "scaffold_only_not_authorized_for_implementation",
        "seed": {
            "kind": seed_kind,
            "requested_value": seed_value,
            "resolved_id": seed_id,
            "record_type": seed_group,
        },
        "source_binding": final_binding,
        "corpus_scan": corpus_scan,
        "current_record": {
            "record_type": seed_group,
            "record": seed_record,
            "citation": current_citation,
        },
        "current_behavior": _current_behavior(seed_group, seed_record, current_citation),
        "dependency_and_impact_closure": {
            "records": closure,
            "edges": closure_edges,
            "record_type_counts": dict(
                sorted(
                    {
                        group: sum(1 for item in closure if item["record_type"] == group)
                        for group in {item["record_type"] for item in closure}
                    }.items()
                )
            ),
            "traversal": traversal,
            "evidence_boundary": (
                "Explicit compiler references and bounded static candidates only; traversal is undirected "
                "for impact discovery and is not runtime blast-radius proof."
            ),
        },
        "affected_architecture_owners": owners,
        "known_gui_or_artifact_surfaces": surfaces,
        "unresolved_impact_categories": unresolved,
        "smallest_safe_vertical_slice": {
            "status": "blocked_pending_evidence" if blockers else "candidate_scaffold",
            "blocking_categories": blockers,
            "candidate_paths_from_cited_closure": affected_paths,
            "candidate_owner_ids": [item["id"] for item in owners],
            "selection_rule": (
                "After resolving blockers, choose the smallest connected subset of cited paths that reaches "
                "one intended observable surface and one executable proof; no path outside this closure is implied."
            ),
            "steps": [
                "Confirm the owner-supplied desired outcome and acceptance boundary for the cited seed.",
                "Resolve every blocking or truncated impact category before selecting implementation paths.",
                "Select one cited behavior-to-surface path and its cited proof records; leave unrelated paths untouched.",
                "Implement only after a human approves the exact paths, invariants, tests, rollback, and authority.",
            ],
            "implementation_authority": "absent_this_package_is_read_only",
        },
        "required_tests_and_gates": {
            "existing_test_records": tests,
            "existing_workflow_records": workflows,
            "compiler_gates": _compiler_gates(bundle),
            "test_placeholders_requiring_human_completion": [
                {
                    "id": "positive_and_counterexample_behavior",
                    "command": None,
                    "status": "unresolved_select_from_owned_test_surface",
                },
                {
                    "id": "dependency_and_surface_regression",
                    "command": None,
                    "status": "unresolved_select_from_cited_closure",
                },
                {
                    "id": "privacy_exact_source_and_protected_constraints",
                    "command": None,
                    "status": "unresolved_bind_to_applicable_invariants",
                },
            ],
        },
        "rollback_and_kill_conditions": {
            "status": "placeholders_require_owner_and_verifier_completion",
            "rollback_mechanism": None,
            "rollback_evidence": [],
            "kill_condition_placeholders": [
                "Exact source binding or cited evidence becomes stale.",
                "The bounded closure expands beyond an approved record, path, owner, or protected constraint.",
                "A required invariant, test, privacy gate, or architecture gate fails or becomes unverifiable.",
                "The selected surface cannot expose the intended outcome without unsupported behavior.",
            ],
        },
        "limits": [
            "No free-form AI, runtime execution, test execution, mutation, or publication occurs.",
            "Static call/import and Graphify edges are possible dependencies, never observed execution.",
            "Gap prose does not become code impact unless an exact compiler relationship supports it.",
            "Rollback commands, success thresholds, and implementation choices require human authority and evidence.",
            "Compiler groups are receipt-validated lazily; record/edge retention and serialized output are hard bounded.",
        ],
        "side_effects": "none",
    }
    result = {**core, "package_digest": digest_object(core)}
    output_bytes = len(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if output_bytes > MAX_SERIALIZED_OUTPUT_BYTES:
        return 3, {
            "schema_version": ENHANCEMENT_SCHEMA_VERSION,
            "package_type": "atlas_enhancement_package",
            "status": "abstained",
            "reason": "serialized_output_limit_exceeded",
            "seed": {"kind": seed_kind, "value": seed_value, "resolved_id": seed_id},
            "source_binding": final_binding,
            "corpus_scan": corpus_scan,
            "required_output_bytes": output_bytes,
            "output_byte_limit": MAX_SERIALIZED_OUTPUT_BYTES,
            "side_effects": "none",
        }
    return 0, result
