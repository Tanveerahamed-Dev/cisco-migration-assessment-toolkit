"""Strict reader for whole-repository compiler output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .model import ReleaseInputError, canonical_json, digest_object, read_bytes, safe_relative, sha256_bytes


COMPILER_SCHEMA_VERSION = "1.1.0"
REQUIRED_STRUCTURAL_INVARIANTS = frozenset(
    {
        "every_safe_parsed_source_has_one_structural_root",
        "every_safe_line_structurally_mapped",
        "every_gui_surface_has_standardized_evidence_honest_dossier",
    }
)
GUI_DOSSIER_FIELDS = frozenset(
    {
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
    }
)


REQUIRED_GROUPS = frozenset(
    {
        "files",
        "lines",
        "source_text",
        "symbols",
        "structural_entities",
        "routes",
        "components",
        "tests",
        "workflows",
        "datasets",
        "binaries",
        "dependencies",
        "claims",
    }
)


@dataclass(frozen=True)
class CompilerBundle:
    root: Path
    manifest: dict[str, Any]
    completeness: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    input_files: tuple[str, ...]

    @property
    def source_commit(self) -> str:
        return str(self.manifest["source_commit"])

    @property
    def source_tree_digest(self) -> str:
        return str(self.manifest["source_tree_digest"])


def _receipt_json(root: Path, receipt: dict[str, Any], label: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(receipt, dict):
        raise ReleaseInputError(f"compiler {label} receipt is not an object")
    relative = safe_relative(str(receipt.get("path", "")))
    value = read_bytes(root, relative)
    if receipt.get("bytes") != len(value) or receipt.get("sha256") != sha256_bytes(value):
        raise ReleaseInputError(f"compiler {label} receipt mismatch: {relative}")
    try:
        import json

        parsed = json.loads(value.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError(f"compiler {label} is invalid JSON: {relative}") from exc
    if not isinstance(parsed, dict):
        raise ReleaseInputError(f"compiler {label} is not an object: {relative}")
    if value != canonical_json(parsed):
        raise ReleaseInputError(f"compiler {label} is not canonical JSON: {relative}")
    return relative, parsed


def load_compiler_bundle(root: Path, *, retained_groups: Iterable[str] | None = None) -> CompilerBundle:
    root = root.resolve(strict=True)
    manifest_raw = read_bytes(root, "manifest.json")
    try:
        import json

        manifest = json.loads(manifest_raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseInputError("compiler manifest is invalid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise ReleaseInputError("compiler manifest is absent or not complete")
    if manifest_raw != canonical_json(manifest):
        raise ReleaseInputError("compiler manifest is not canonical JSON")
    if manifest.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError(f"unsupported compiler schema: {manifest.get('schema_version')!r}")
    commit = manifest.get("source_commit")
    tree = manifest.get("source_tree_digest")
    if not isinstance(commit, str) or len(commit) not in {40, 64} or any(char not in "0123456789abcdef" for char in commit):
        raise ReleaseInputError("compiler source_commit is not a lowercase Git object id")
    if not isinstance(tree, str) or len(tree) != 64 or any(char not in "0123456789abcdef" for char in tree):
        raise ReleaseInputError("compiler source_tree_digest is invalid")
    head_tree = manifest.get("head_tree_oid")
    index_digest = manifest.get("index_digest")
    if not isinstance(head_tree, str) or len(head_tree) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in head_tree
    ):
        raise ReleaseInputError("compiler head_tree_oid is invalid")
    if not isinstance(index_digest, str) or len(index_digest) != 64 or any(
        char not in "0123456789abcdef" for char in index_digest
    ):
        raise ReleaseInputError("compiler index_digest is invalid")
    if manifest.get("tracked_worktree_dirty") is not False:
        raise ReleaseInputError("release requires a compiler projection from an exact clean tracked worktree")
    if manifest.get("release_class") != "exact_commit":
        raise ReleaseInputError("release requires compiler release_class exact_commit")

    completeness_path, completeness = _receipt_json(root, manifest.get("completeness", {}), "completeness")
    graphify_path, graphify = _receipt_json(root, manifest.get("graphify_metadata", {}), "Graphify metadata")
    if "architecture_conformance" not in manifest:
        raise ReleaseInputError("compiler architecture conformance receipt missing")
    architecture_path, architecture = _receipt_json(
        root,
        manifest.get("architecture_conformance", {}),
        "architecture conformance",
    )
    if completeness.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError(
            f"unsupported compiler completeness schema: {completeness.get('schema_version')!r}"
        )
    if graphify.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError(
            f"unsupported compiler Graphify schema: {graphify.get('schema_version')!r}"
        )
    if (
        graphify.get("source_commit") != commit
        or graphify.get("source_tree_digest") != tree
    ):
        raise ReleaseInputError("compiler Graphify receipt is not bound to the compiler source")
    if architecture.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError(
            f"unsupported compiler architecture-conformance schema: {architecture.get('schema_version')!r}"
        )
    if completeness.get("source_commit") != commit or completeness.get("source_tree_digest") != tree:
        raise ReleaseInputError("completeness ledger is not bound to the compiler source")
    if completeness.get("hard_failure") is not False or completeness.get("fatal_errors"):
        raise ReleaseInputError("completeness ledger contains a hard failure")
    invariants = completeness.get("invariants")
    if (
        not isinstance(invariants, list)
        or not invariants
        or any(not isinstance(item, dict) or item.get("passed") is not True for item in invariants)
    ):
        raise ReleaseInputError("not every compiler completeness invariant passed")
    invariant_by_name: dict[str, dict[str, Any]] = {}
    for item in invariants:
        name = item.get("name")
        expected = item.get("expected")
        actual = item.get("actual")
        if (
            not isinstance(name, str)
            or not name
            or name in invariant_by_name
            or type(expected) is not int
            or type(actual) is not int
            or expected < 0
            or actual < 0
        ):
            raise ReleaseInputError("compiler completeness invariants have an invalid or duplicate name")
        invariant_by_name[name] = item
    missing_invariants = REQUIRED_STRUCTURAL_INVARIANTS - set(invariant_by_name)
    if missing_invariants:
        raise ReleaseInputError(
            "compiler structural line-mapping invariant or required GUI/root denominator is missing: "
            f"{sorted(missing_invariants)}"
        )
    structural_gate = invariant_by_name.get("every_safe_line_structurally_mapped")
    structural_root_gate = invariant_by_name.get(
        "every_safe_parsed_source_has_one_structural_root"
    )
    gui_gate = invariant_by_name.get(
        "every_gui_surface_has_standardized_evidence_honest_dossier"
    )
    semantic_accounting = completeness.get("semantic_accounting")
    if (
        structural_gate is None
        or structural_gate.get("expected") != structural_gate.get("actual")
        or structural_root_gate is None
        or structural_root_gate.get("expected") != structural_root_gate.get("actual")
        or gui_gate is None
        or gui_gate.get("expected") != gui_gate.get("actual")
        or not isinstance(semantic_accounting, dict)
        or semantic_accounting.get("structurally_mapped_lines") != structural_gate.get("actual")
        or semantic_accounting.get("safe_parsed_sources") != structural_root_gate.get("expected")
        or semantic_accounting.get("structural_root_entities") != structural_root_gate.get("actual")
        or semantic_accounting.get("gui_surface_records") != gui_gate.get("expected")
        or semantic_accounting.get("gui_dossiers") != gui_gate.get("actual")
    ):
        raise ReleaseInputError(
            "compiler structural line-mapping invariant or GUI/root denominator is absent or inconsistent"
        )
    acceptance_gates = completeness.get("acceptance_gates")
    if not isinstance(acceptance_gates, list) or not acceptance_gates:
        raise ReleaseInputError("completeness ledger contains no semantic acceptance gates")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not item.get("name")
        or not isinstance(item.get("passed"), bool)
        for item in acceptance_gates
    ):
        raise ReleaseInputError("completeness ledger semantic acceptance gates are malformed")
    if architecture != completeness.get("architecture_conformance"):
        raise ReleaseInputError("architecture conformance differs from the completeness ledger")
    if (
        architecture.get("source_commit") != commit
        or architecture.get("source_tree_digest") != tree
    ):
        raise ReleaseInputError("architecture conformance is not bound to the compiler source")
    if architecture.get("status") != "passed" or architecture.get("errors"):
        raise ReleaseInputError("architecture conformance did not pass")
    if architecture.get("runtime_observed") is not False:
        raise ReleaseInputError("architecture conformance mislabels static evidence as runtime observation")

    groups = manifest.get("groups")
    if not isinstance(groups, dict) or not REQUIRED_GROUPS.issubset(groups):
        missing = sorted(REQUIRED_GROUPS - set(groups or {}))
        raise ReleaseInputError(f"compiler manifest is missing required record groups: {missing}")
    if not isinstance(groups.get("lines"), dict) or groups["lines"].get("record_count") != structural_gate["expected"]:
        raise ReleaseInputError("compiler line-group denominator differs from structural mapping invariant")
    if (
        not isinstance(groups.get("structural_entities"), dict)
        or groups["structural_entities"].get("record_count")
        != structural_root_gate["expected"]
    ):
        raise ReleaseInputError(
            "compiler structural-entity group differs from the safe parsed-source denominator"
        )
    gui_group_denominator = sum(
        int(groups[name].get("record_count", -1))
        for name in ("routes", "components")
        if isinstance(groups.get(name), dict)
    )
    if gui_group_denominator != gui_gate["expected"]:
        raise ReleaseInputError("compiler GUI groups differ from the GUI dossier denominator")
    wanted = set(groups) if retained_groups is None else set(retained_groups)
    unknown_wanted = wanted - set(groups)
    if unknown_wanted:
        raise ReleaseInputError(f"requested compiler groups are absent: {sorted(unknown_wanted)}")
    validation_groups = {
        "files",
        "lines",
        "source_text",
        "symbols",
        "structural_entities",
        "routes",
        "components",
    }
    if not validation_groups.issubset(wanted):
        raise ReleaseInputError(
            "retained compiler groups omit records required for structural denominator validation"
        )

    records: dict[str, list[dict[str, Any]]] = {}
    input_files = {"manifest.json", completeness_path, graphify_path, architecture_path}
    for group_name in sorted(groups):
        group = groups[group_name]
        if not isinstance(group, dict) or not isinstance(group.get("chunks"), list):
            raise ReleaseInputError(f"compiler group is malformed: {group_name}")
        chunks = group["chunks"]
        if group.get("chunk_count") != len(chunks):
            raise ReleaseInputError(f"compiler chunk count mismatch: {group_name}")
        combined: list[dict[str, Any]] = []
        for expected_index, chunk_receipt in enumerate(chunks):
            relative, envelope = _receipt_json(root, chunk_receipt, f"{group_name} chunk")
            input_files.add(relative)
            if (
                envelope.get("schema_version") != COMPILER_SCHEMA_VERSION
                or envelope.get("record_type") != group_name
                or envelope.get("source_commit") != commit
                or envelope.get("source_tree_digest") != tree
                or envelope.get("chunk_index") != expected_index
                or envelope.get("chunk_count") != len(chunks)
            ):
                raise ReleaseInputError(f"compiler chunk envelope mismatch: {relative}")
            chunk_records = envelope.get("records")
            if not isinstance(chunk_records, list) or envelope.get("record_count") != len(chunk_records):
                raise ReleaseInputError(f"compiler chunk records malformed: {relative}")
            if envelope.get("records_digest") != digest_object(
                [str(item.get("id", "")) for item in chunk_records]
            ):
                raise ReleaseInputError(f"compiler chunk record digest mismatch: {relative}")
            if group_name in wanted:
                combined.extend(chunk_records)
        if group.get("record_count") != sum(int(item.get("record_count", -1)) for item in chunks):
            raise ReleaseInputError(f"compiler group receipt count mismatch: {group_name}")
        if group_name in wanted:
            if group.get("record_count") != len(combined) or group.get("records_digest") != digest_object(
                [str(item.get("id", "")) for item in combined]
            ):
                raise ReleaseInputError(f"compiler group aggregate mismatch: {group_name}")
            if any(not isinstance(item, dict) for item in combined):
                raise ReleaseInputError(f"compiler group contains a non-object record: {group_name}")
            records[group_name] = combined

    if graphify != completeness.get("graphify"):
        raise ReleaseInputError("Graphify metadata differs from the completeness ledger")
    if graphify.get("status") == "parser_error":
        raise ReleaseInputError("Graphify metadata reports a parser error")
    seen_ids: dict[str, str] = {}
    for group_name, group_records in sorted(records.items()):
        for item in group_records:
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ReleaseInputError(f"compiler {group_name} record lacks a stable id")
            if identifier in seen_ids:
                raise ReleaseInputError(
                    f"duplicate compiler stable id {identifier!r} in {seen_ids[identifier]} and {group_name}"
                )
            seen_ids[identifier] = group_name

    files = records.get("files")
    if files is not None:
        by_path: dict[str, dict[str, Any]] = {}
        for item in files:
            path = item.get("path")
            if not isinstance(path, str) or not path or path in by_path:
                raise ReleaseInputError("compiler file census contains an invalid or duplicate path")
            exposure = item.get("privacy_exposure")
            expected_source = (
                "selected_commit_git_blob" if exposure == "full" else "metadata_only_git_object"
            )
            if exposure not in {"full", "metadata_only"} or item.get("content_source") != expected_source:
                raise ReleaseInputError(f"compiler file has invalid exact-source custody: {path}")
            if exposure == "metadata_only" and item.get("content_digest") is not None:
                raise ReleaseInputError(f"metadata-only compiler file exposes a content digest: {path}")
            by_path[path] = item

        for item in records.get("source_text", []):
            path = item.get("path")
            file_record = by_path.get(str(path))
            if (
                file_record is None
                or file_record.get("privacy_exposure") != "full"
                or item.get("source_basis") != "selected_commit_git_blob"
                or item.get("git_blob_oid") != file_record.get("git_blob_oid")
                or item.get("content_digest") != file_record.get("content_digest")
                or item.get("byte_count") != file_record.get("size_bytes")
            ):
                raise ReleaseInputError(f"compiler source-text custody differs from file record: {path}")
    safe_parsed_files = {
        str(item["id"]): item
        for item in records["files"]
        if item.get("privacy_exposure") == "full"
        and item.get("language") != "binary"
        and item.get("parse_status") == "parsed"
    }
    roots_by_file: dict[str, list[dict[str, Any]]] = {}
    for item in records["structural_entities"]:
        roots_by_file.setdefault(str(item.get("file_id") or ""), []).append(item)
    if (
        set(roots_by_file) != set(safe_parsed_files)
        or len(records["structural_entities"]) != structural_root_gate["expected"]
    ):
        raise ReleaseInputError("compiler structural-root file denominator is not exact")
    structural_roots: dict[str, dict[str, Any]] = {}
    for file_id, file_record in safe_parsed_files.items():
        candidates = roots_by_file.get(file_id, [])
        if len(candidates) != 1:
            raise ReleaseInputError(f"compiler source lacks exactly one structural root: {file_record.get('path')}")
        root_record = candidates[0]
        location = root_record.get("range")
        line_count = file_record.get("line_count")
        exact_range = bool(
            isinstance(location, dict)
            and type(line_count) is int
            and (
                (
                    line_count == 0
                    and root_record.get("range_state") == "empty_source"
                    and all(
                        location.get(field) is None
                        for field in ("start_line", "start_column", "end_line", "end_column")
                    )
                )
                or (
                    line_count > 0
                    and root_record.get("range_state") == "exact_source_lines"
                    and location.get("start_line") == 1
                    and location.get("start_column") == 0
                    and location.get("end_line") == line_count
                    and type(location.get("end_column")) is int
                    and location["end_column"] >= 0
                )
            )
        )
        if (
            not exact_range
            or root_record.get("root_scope") != "parsed_source"
            or root_record.get("path") != file_record.get("path")
            or root_record.get("parser") != file_record.get("parser")
            or root_record.get("parser_mode") != file_record.get("parser_mode")
            or root_record.get("parser_version") != file_record.get("parser_version")
            or root_record.get("language") != file_record.get("language")
            or root_record.get("roles") != file_record.get("roles")
            or root_record.get("source_basis") != file_record.get("content_source")
            or root_record.get("git_blob_oid") != file_record.get("git_blob_oid")
            or root_record.get("content_digest") != file_record.get("content_digest")
            or root_record.get("line_count") != line_count
            or root_record.get("nonblank_line_count") != file_record.get("nonblank_line_count")
            or root_record.get("parser_owned") is not True
            or int(root_record.get("explanation_depth") or 0) < 1
        ):
            raise ReleaseInputError(
                f"compiler structural root is not bound to its parsed source: {file_record.get('path')}"
            )
        structural_roots[str(root_record.get("id") or "")] = root_record
    if len(structural_roots) != structural_root_gate["actual"]:
        raise ReleaseInputError("compiler structural-root records differ from their invariant")

    gui_surfaces = [*records["routes"], *records["components"]]
    valid_gui_dossiers = 0
    for surface in gui_surfaces:
        dossier = surface.get("gui_dossier")
        citation = dossier.get("source_citation") if isinstance(dossier, dict) else None
        if (
            not isinstance(dossier, dict)
            or dossier.get("surface_id") != surface.get("id")
            or dossier.get("source_commit") != commit
            or dossier.get("field_count") != len(GUI_DOSSIER_FIELDS)
            or not GUI_DOSSIER_FIELDS.issubset(dossier)
            or not isinstance(citation, dict)
            or citation.get("record_id") != surface.get("id")
            or citation.get("path") != surface.get("path")
            or any(not isinstance(dossier.get(field), dict) for field in GUI_DOSSIER_FIELDS)
        ):
            raise ReleaseInputError(f"compiler GUI dossier is absent or malformed: {surface.get('id')}")
        valid_gui_dossiers += 1
    if valid_gui_dossiers != gui_gate["actual"] or len(gui_surfaces) != gui_gate["expected"]:
        raise ReleaseInputError("compiler GUI dossier records differ from their invariant")

    symbols_by_id = {str(item["id"]): item for item in records["symbols"]}
    line_coordinates: set[tuple[str, int]] = set()
    mapped_lines = 0
    for item in records["lines"]:
        path = item.get("path")
        number = item.get("line")
        coordinate = (str(path or ""), number if type(number) is int else -1)
        if not isinstance(path, str) or type(number) is not int or number < 1 or coordinate in line_coordinates:
            raise ReleaseInputError("compiler line denominator has an invalid or duplicate coordinate")
        line_coordinates.add(coordinate)
        semantic_id = item.get("semantic_entity")
        symbol = symbols_by_id.get(str(semantic_id or ""))
        root_record = structural_roots.get(str(semantic_id or ""))
        if symbol is not None:
            location = symbol.get("range") or {}
            valid_mapping = bool(
                item.get("structural_mapping_basis") == "symbol_range"
                and symbol.get("file_id") == item.get("file_id")
                and symbol.get("path") == path
                and type(location.get("start_line")) is int
                and type(location.get("end_line")) is int
                and location["start_line"] <= number <= location["end_line"]
            )
        else:
            valid_mapping = bool(
                root_record is not None
                and item.get("structural_mapping_basis")
                in {"parser_context", "parser_structural_root"}
                and root_record.get("file_id") == item.get("file_id")
                and root_record.get("path") == path
                and number <= int(root_record.get("line_count") or 0)
            )
        if valid_mapping and int(item.get("explanation_depth") or 0) >= 1:
            mapped_lines += 1
    if mapped_lines != structural_gate["actual"] or len(records["lines"]) != structural_gate["expected"]:
        raise ReleaseInputError("compiler line records differ from the structural mapping invariant")
    return CompilerBundle(root, manifest, completeness, records, tuple(sorted(input_files)))
