"""Read-only, privacy-filtered projection of an optional local Graphify graph."""

from __future__ import annotations

import json
import math
import re
import stat
import struct
from pathlib import Path, PurePosixPath
from typing import Any

from .model import SCHEMA_VERSION, canonical_json, sha256_bytes, stable_id


MAX_GRAPH_BYTES = 256 * 1024 * 1024
MAX_GRAPH_NODES = 500_000
MAX_GRAPH_EDGES = 2_000_000
MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991
MAX_GRAPH_IDENTIFIER_LENGTH = 4_096
MAX_GRAPH_SOURCE_PATH_LENGTH = 4_096
MAX_GRAPH_TOKEN_LENGTH = 128
MAX_GRAPH_SOURCE_LOCATION_LENGTH = 64
OPAQUE_IDENTIFIER_POLICY = "raw_identifiers_withheld_repository_relative_retained_source_index_excluded"
CONTROLLED_GRAPH_FILE_TYPES = frozenset({"code", "document", "rationale"})
CONTROLLED_GRAPH_LANGUAGES = frozenset(
    {
        "bash",
        "c",
        "cpp",
        "csharp",
        "css",
        "go",
        "html",
        "java",
        "javascript",
        "json",
        "jsx",
        "markdown",
        "php",
        "python",
        "ruby",
        "rust",
        "shell",
        "sql",
        "text",
        "tsx",
        "typescript",
        "yaml",
    }
)
CONTROLLED_GRAPH_KINDS = frozenset(
    {
        "bash_entrypoint",
        "bash_function",
        "class",
        "code",
        "file",
        "function",
        "method",
        "module",
        "symbol",
    }
)
CONTROLLED_GRAPH_RELATIONS = frozenset(
    {
        "calls",
        "contains",
        "defines",
        "imports",
        "imports_from",
        "indirect_call",
        "inherits",
        "method",
        "rationale_for",
        "related_to",
        "re_exports",
        "references",
        "uses",
    }
)
GRAPHIFY_ABSENT_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "source_commit",
        "source_tree_digest",
        "available",
        "status",
        "source",
        "report_available",
        "stale",
        "unresolved_reasons",
    }
)
GRAPHIFY_AVAILABLE_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "available",
        "status",
        "source",
        "source_bytes",
        "source_digest",
        "report_available",
        "built_at_commit",
        "source_commit",
        "source_tree_digest",
        "stale",
        "total_nodes",
        "total_edges",
        "total_hyperedges",
        "projected_nodes",
        "projected_edges",
        "excluded_nodes",
        "excluded_edges",
        "excluded_node_dispositions",
        "excluded_edge_dispositions",
        "excluded_edge_endpoint_dispositions",
        "all_edge_modes",
        "projected_edge_modes",
        "node_origins",
        "excluded_nodes_unsafe_source",
        "excluded_nodes_untracked_or_private",
        "node_disposition_counts",
        "identifier_projection_policy",
        "node_identifier_disposition_counts",
        "total_communities",
        "projected_communities",
        "excluded_communities",
        "all_community_ids",
        "projected_community_ids",
        "excluded_community_ids",
        "partial_community_ids",
        "community_status_counts",
        "community_dispositions",
        "projection_policy",
        "unresolved_reasons",
    }
)
GRAPHIFY_BASE_UNRESOLVED_REASONS = (
    "graphify_is_optional_secondary_projection",
    "graphify_incremental_rebuild_may_evict_cross_file_edges_until_full_rebuild",
    "graphify_raw_identifiers_are_withheld_and_exclusion_dispositions_use_source_index_only",
    "graphify_producer_labels_are_replaced_by_repository_relative_coordinate_labels_and_descriptors_use_controlled_vocabularies",
)
GRAPHIFY_HYPEREDGE_REASON_PRESENT = "graphify_hyperedges_not_projected"
GRAPHIFY_HYPEREDGE_REASON_ABSENT = "graphify_has_no_hyperedges"
GRAPHIFY_MALFORMED_BUILD_REASON = "graphify_built_at_commit_missing_or_malformed_and_withheld"
GRAPHIFY_DIRTY_PREVIEW_REASON = "tracked_worktree_changes_are_newer_than_commit_bound_graph"
GRAPHIFY_ABSENT_REASON = "optional_graphify_projection_not_present"
GRAPH_NODE_UNRESOLVED_REASON_ORDER = (
    "graphify_node_label_derived_from_repository_relative_coordinate",
    "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction",
    "graphify_node_community_outside_js_safe_nonnegative_integer_domain",
    "graphify_node_source_location_outside_bounded_coordinate_domain",
    "graphify_node_nonvocabulary_descriptor_withheld",
)
GRAPH_NODE_UNRESOLVED_REASONS = frozenset(GRAPH_NODE_UNRESOLVED_REASON_ORDER)
GRAPH_EDGE_UNRESOLVED_REASON_ORDER = (
    "graphify_confidence_mode_undisclosed_or_ambiguous",
    "graphify_relation_not_in_controlled_vocabulary_shape",
    "graphify_edge_source_location_outside_bounded_coordinate_domain",
)
GRAPH_EDGE_UNRESOLVED_REASONS = frozenset(GRAPH_EDGE_UNRESOLVED_REASON_ORDER)


class GraphifyFailure(RuntimeError):
    """An available Graphify artifact was malformed or unsafe to read."""


def _fixed_regular_file(root: Path, relative: str) -> Path | None:
    path = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        path = path / part
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise GraphifyFailure(f"{relative}: metadata read failed") from None
        final = index == len(parts) - 1
        if stat.S_ISLNK(metadata.st_mode):
            raise GraphifyFailure(f"{relative}: symlink traversal refused")
        if not final and not stat.S_ISDIR(metadata.st_mode):
            raise GraphifyFailure(f"{relative}: parent component is not a directory")
        if final and not stat.S_ISREG(metadata.st_mode):
            raise GraphifyFailure(f"{relative}: expected a non-symlink regular file")
    if metadata.st_size > MAX_GRAPH_BYTES:
        raise GraphifyFailure(f"{relative}: exceeds {MAX_GRAPH_BYTES} bytes")
    return path


def _utf8_text(value: Any, *, max_length: int | None = None) -> str | None:
    """Return producer text only when it is a valid Unicode scalar string."""

    if not isinstance(value, str):
        return None
    if max_length is not None and len(value) > max_length:
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    return value


def _graph_identifier(value: Any, *, record_type: str) -> str:
    """Normalize an in-memory join key without stringifying containers."""

    text = _utf8_text(value, max_length=MAX_GRAPH_IDENTIFIER_LENGTH)
    if text:
        return text
    if isinstance(value, int) and not isinstance(value, bool) and -MAX_JS_SAFE_INTEGER <= value <= MAX_JS_SAFE_INTEGER:
        return str(value)
    raise GraphifyFailure(f"graphify-out/graph.json: {record_type} id must be nonempty text or a safe integer")


def _safe_source_path(value: Any) -> str | None:
    text = _utf8_text(value, max_length=MAX_GRAPH_SOURCE_PATH_LENGTH)
    if not text:
        return None
    path = text.replace("\\", "/")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        return None
    if len(candidate.parts[0]) == 2 and candidate.parts[0][1] == ":":
        return None
    return candidate.as_posix()


def _mode(value: Any) -> str:
    text = _utf8_text(value, max_length=MAX_GRAPH_TOKEN_LENGTH)
    confidence = text.strip().lower() if text is not None else ""
    if confidence == "inferred":
        return "inferred"
    if confidence == "ambiguous":
        return "ambiguous"
    if confidence == "extracted":
        return "extracted"
    return "undisclosed"


def _safe_source_location(value: Any) -> str:
    """Retain line/column coordinates, never an arbitrary path or snippet."""

    text = _utf8_text(value, max_length=MAX_GRAPH_SOURCE_LOCATION_LENGTH)
    if text is not None:
        location = text.strip()
    elif isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_JS_SAFE_INTEGER:
        location = str(value)
    else:
        return ""
    if re.fullmatch(r"L?\d+(?::\d+)?(?:-L?\d+(?::\d+)?)?", location) and all(
        1 <= int(component) <= MAX_JS_SAFE_INTEGER for component in re.findall(r"\d+", location)
    ):
        return location
    return ""


def _controlled_public_token(
    value: Any,
    *,
    vocabulary: frozenset[str],
    fallback: str,
) -> tuple[str, bool]:
    """Return only a member of a finite, compiler-owned public vocabulary."""

    text = _utf8_text(value, max_length=MAX_GRAPH_TOKEN_LENGTH)
    candidate = text.strip().lower() if text is not None else ""
    safe = candidate in vocabulary
    return (candidate if safe else fallback), safe


def _safe_relation(value: Any) -> tuple[str, bool]:
    """Project only the controlled Graphify relation token shape.

    Arbitrary relation text is not needed for endpoint identity and can carry
    the same producer-controlled local data as a raw node id.  A malformed or
    non-vocabulary value is represented honestly as the controlled fallback.
    """

    text = _utf8_text(value, max_length=MAX_GRAPH_TOKEN_LENGTH)
    relation = text.strip().lower() if text is not None else ""
    safe = relation in CONTROLLED_GRAPH_RELATIONS
    return (relation if safe else "related_to"), safe


def _confidence_identity(value: Any) -> tuple[float | None, str]:
    """Return a bounded score and a cross-runtime IEEE-754 identity token."""

    if value is None:
        return None, "none"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphifyFailure(
            "graphify-out/graph.json: edge confidence_score must be null or a finite number from zero to one"
        )
    try:
        score = float(value)
    except OverflowError:
        raise GraphifyFailure(
            "graphify-out/graph.json: edge confidence_score must be null or a finite number from zero to one"
        ) from None
    if not math.isfinite(score) or score < 0 or score > 1:
        raise GraphifyFailure(
            "graphify-out/graph.json: edge confidence_score must be null or a finite number from zero to one"
        )
    if score.is_integer():
        return score, f"integer:{int(score)}"
    return score, f"float64:{struct.pack('>d', score).hex()}"


def _opaque_hash(*parts: object) -> str:
    """Hash bounded public identity coordinates without stringifying containers."""

    normalized: list[str] = []
    for part in parts:
        text = _utf8_text(part)
        if text is not None:
            normalized.append(text)
        elif isinstance(part, int) and not isinstance(part, bool):
            normalized.append(str(part))
        else:
            raise GraphifyFailure("Graphify opaque identity coordinate is malformed")
    return sha256_bytes(canonical_json(normalized))


def _excluded_disposition_id(kind: str, source_digest: str, raw_index: int) -> str:
    """Identify one excluded source row using public artifact coordinates only."""

    return stable_id(kind, source_digest, raw_index)


def _projected_identifier_hash(
    source_file: str,
    source_location: str,
    coordinate_occurrence: int,
) -> str:
    """Build a positive repository-relative identity for a retained node.

    The occurrence is counted among retained nodes with the same safe file and
    source coordinate in producer order.  Distinct nodes remain distinct while
    the raw Graphify identifier cannot influence any published node or edge id.
    """

    return _opaque_hash(
        "repository-relative-graph-node",
        source_file,
        source_location,
        coordinate_occurrence,
    )


def _excluded_node_record(
    *,
    source_digest: str,
    raw_index: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": _excluded_disposition_id("graph-node-disposition", source_digest, raw_index),
        "disposition": "excluded",
        "raw_index": raw_index,
        "reason": reason,
    }


def _edge_endpoint_record(
    *,
    raw_id: str,
    state: str,
    retained: dict[str, str],
    excluded_node_refs: dict[str, str],
    anonymous_missing_slots: dict[str, int],
) -> dict[str, Any]:
    record_id = retained.get(raw_id) or excluded_node_refs.get(raw_id)
    anonymous_slot = None
    if state == "missing_node":
        anonymous_slot = anonymous_missing_slots.setdefault(raw_id, len(anonymous_missing_slots))
    return {
        "state": state,
        "record_id": record_id,
        "anonymous_slot": anonymous_slot,
    }


def _excluded_edge_record(
    *,
    source_digest: str,
    raw_index: int,
    source: str,
    target: str,
    node_dispositions: dict[str, str],
    retained: dict[str, str],
    excluded_node_refs: dict[str, str],
    anonymous_missing_slots: dict[str, int],
) -> dict[str, Any]:
    source_state = node_dispositions.get(source, "missing_node")
    target_state = node_dispositions.get(target, "missing_node")
    return {
        "id": _excluded_disposition_id("graph-edge-disposition", source_digest, raw_index),
        "disposition": "excluded",
        "raw_index": raw_index,
        "reason": "endpoint_not_projected",
        "source_endpoint": _edge_endpoint_record(
            raw_id=source,
            state=source_state,
            retained=retained,
            excluded_node_refs=excluded_node_refs,
            anonymous_missing_slots=anonymous_missing_slots,
        ),
        "target_endpoint": _edge_endpoint_record(
            raw_id=target,
            state=target_state,
            retained=retained,
            excluded_node_refs=excluded_node_refs,
            anonymous_missing_slots=anonymous_missing_slots,
        ),
    }


def _validate_exclusion_dispositions(
    *,
    source_digest: str,
    raw_node_count: int,
    projected_node_count: int,
    expected_node_indices: set[int],
    node_records: list[dict[str, Any]],
    expected_node_reason_counts: dict[str, int],
    raw_edge_count: int,
    projected_edge_count: int,
    expected_edge_indices: set[int],
    edge_records: list[dict[str, Any]],
    expected_edge_endpoint_counts: dict[str, int],
) -> None:
    """Fail closed unless every excluded raw record has one opaque ledger row."""

    errors: list[str] = []

    def validate_common(
        label: str,
        records: list[dict[str, Any]],
        expected_indices: set[int],
        expected_count: int,
        raw_count: int,
        expected_keys: frozenset[str],
        identifier_kind: str,
    ) -> None:
        if len(records) != expected_count:
            errors.append(f"{label} count expected {expected_count}, found {len(records)}")
        if any(set(record) != expected_keys for record in records):
            errors.append(f"{label} record shape is malformed")
        if any(record.get("disposition") != "excluded" for record in records):
            errors.append(f"{label} disposition is malformed")
        indices = [record.get("raw_index") for record in records]
        if any(
            not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= raw_count
            for index in indices
        ):
            errors.append(f"{label} raw index is outside the source census")
        if len(indices) != len(set(indices)):
            errors.append(f"{label} raw indexes are not one-to-one")
        if set(indices) != expected_indices:
            errors.append(f"{label} raw index census differs from excluded source records")
        identifiers = [record.get("id") for record in records]
        if len(identifiers) != len(set(identifiers)):
            errors.append(f"{label} stable ids are not unique")
        if any(
            not isinstance(identifier, str)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or identifier != _excluded_disposition_id(identifier_kind, source_digest, index)
            for identifier, index in zip(identifiers, indices)
        ):
            errors.append(f"{label} stable id does not bind its public source index")

    expected_excluded_nodes = raw_node_count - projected_node_count
    validate_common(
        "excluded node dispositions",
        node_records,
        expected_node_indices,
        expected_excluded_nodes,
        raw_node_count,
        frozenset(
            {
                "id",
                "disposition",
                "raw_index",
                "reason",
            }
        ),
        "graph-node-disposition",
    )
    actual_node_reasons: dict[str, int] = {reason: 0 for reason in expected_node_reason_counts}
    node_records_by_id: dict[str, dict[str, Any]] = {}
    for record in node_records:
        reason_value = record.get("reason")
        reason = reason_value if isinstance(reason_value, str) else ""
        actual_node_reasons[reason] = actual_node_reasons.get(reason, 0) + 1
        if isinstance(record.get("id"), str):
            node_records_by_id[record["id"]] = record
    if actual_node_reasons != expected_node_reason_counts:
        errors.append("excluded node reason counts do not reconcile")

    expected_excluded_edges = raw_edge_count - projected_edge_count
    validate_common(
        "excluded edge dispositions",
        edge_records,
        expected_edge_indices,
        expected_excluded_edges,
        raw_edge_count,
        frozenset(
            {
                "id",
                "disposition",
                "raw_index",
                "reason",
                "source_endpoint",
                "target_endpoint",
            }
        ),
        "graph-edge-disposition",
    )
    actual_endpoint_counts: dict[str, int] = {}
    allowed_endpoint_states = {
        "retained",
        "excluded_unsafe_source",
        "excluded_untracked_or_private",
        "missing_node",
    }
    seen_anonymous_slots: set[int] = set()
    sorted_edge_records = sorted(
        edge_records,
        key=lambda record: record.get("raw_index") if isinstance(record.get("raw_index"), int) else -1,
    )
    for record in sorted_edge_records:
        source_endpoint = record.get("source_endpoint")
        target_endpoint = record.get("target_endpoint")
        if not isinstance(source_endpoint, dict) or not isinstance(target_endpoint, dict):
            errors.append("excluded edge endpoint disposition is malformed")
            continue
        if set(source_endpoint) != {"state", "record_id", "anonymous_slot"} or set(target_endpoint) != {
            "state",
            "record_id",
            "anonymous_slot",
        }:
            errors.append("excluded edge endpoint disposition shape is malformed")
        source_state_value = source_endpoint.get("state")
        target_state_value = target_endpoint.get("state")
        source_state = source_state_value if isinstance(source_state_value, str) else ""
        target_state = target_state_value if isinstance(target_state_value, str) else ""
        if source_state not in allowed_endpoint_states or target_state not in allowed_endpoint_states:
            errors.append("excluded edge endpoint state is unknown")
        disposition = f"source_{source_state}__target_{target_state}"
        actual_endpoint_counts[disposition] = actual_endpoint_counts.get(disposition, 0) + 1
        for endpoint in (source_endpoint, target_endpoint):
            anonymous_slot = endpoint.get("anonymous_slot")
            if endpoint.get("state") == "missing_node":
                if endpoint.get("record_id") is not None:
                    errors.append("missing excluded edge endpoint unexpectedly resolves to a record")
                if (
                    not isinstance(anonymous_slot, int)
                    or isinstance(anonymous_slot, bool)
                    or anonymous_slot < 0
                    or anonymous_slot > MAX_JS_SAFE_INTEGER
                ):
                    errors.append("missing excluded edge endpoint slot is malformed")
                elif anonymous_slot not in seen_anonymous_slots:
                    if anonymous_slot != len(seen_anonymous_slots):
                        errors.append("missing excluded edge endpoint slots are not first-seen contiguous")
                    seen_anonymous_slots.add(anonymous_slot)
            elif not endpoint.get("record_id") or anonymous_slot is not None:
                errors.append("known excluded edge endpoint does not carry one record identity")
            if endpoint.get("state") in {
                "excluded_unsafe_source",
                "excluded_untracked_or_private",
            }:
                endpoint_record_id = endpoint.get("record_id")
                node_record = (
                    node_records_by_id.get(endpoint_record_id) if isinstance(endpoint_record_id, str) else None
                )
                if node_record is None:
                    errors.append("excluded edge endpoint does not traverse to its node disposition")
                elif endpoint.get("state") != node_record.get("reason"):
                    errors.append("excluded edge endpoint state differs from its node disposition")
    if actual_endpoint_counts != expected_edge_endpoint_counts:
        errors.append("excluded edge endpoint counts do not reconcile")
    if any(record.get("reason") != "endpoint_not_projected" for record in edge_records):
        errors.append("excluded edge reason is not controlled")

    if errors:
        raise GraphifyFailure(
            "graphify-out/graph.json: exclusion disposition reconciliation failed: " + "; ".join(sorted(set(errors)))
        )


def validate_graphify_metadata(
    metadata: dict[str, Any],
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> None:
    """Reconcile a persisted metadata ledger without re-reading unsafe input."""

    if not isinstance(metadata, dict):
        raise GraphifyFailure("graphify metadata: receipt is malformed")
    if metadata.get("available") is False:
        if (
            set(metadata) != GRAPHIFY_ABSENT_METADATA_KEYS
            or metadata.get("schema_version") != SCHEMA_VERSION
            or metadata.get("status") != "absent"
            or metadata.get("stale") is not None
            or metadata.get("source") != "graphify-out/graph.json"
            or not isinstance(metadata.get("report_available"), bool)
            or not isinstance(metadata.get("source_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", metadata["source_commit"]) is None
            or not isinstance(metadata.get("source_tree_digest"), str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata["source_tree_digest"]) is None
            or metadata.get("unresolved_reasons") != [GRAPHIFY_ABSENT_REASON]
        ):
            raise GraphifyFailure("graphify metadata: absent receipt is malformed")
        if (nodes is not None and nodes) or (edges is not None and edges):
            raise GraphifyFailure("graphify metadata: absent receipt carries graph records")
        return
    if (nodes is None) != (edges is None):
        raise GraphifyFailure("graphify metadata: projected record census is incomplete")
    if metadata.get("available") is not True or set(metadata) != GRAPHIFY_AVAILABLE_METADATA_KEYS:
        raise GraphifyFailure("graphify metadata: available receipt is malformed")
    if (
        metadata.get("schema_version") != SCHEMA_VERSION
        or metadata.get("source") != "graphify-out/graph.json"
        or metadata.get("projection_policy") != "tracked_full_exposure_files_only"
        or not isinstance(metadata.get("report_available"), bool)
        or not isinstance(metadata.get("source_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", metadata["source_commit"]) is None
        or not isinstance(metadata.get("source_tree_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", metadata["source_tree_digest"]) is None
        or not isinstance(metadata.get("source_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", metadata["source_digest"]) is None
    ):
        raise GraphifyFailure("graphify metadata: source binding is malformed")
    built_commit = metadata.get("built_at_commit")
    if "built_at_commit" not in metadata or (
        built_commit is not None
        and (not isinstance(built_commit, str) or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", built_commit) is None)
    ):
        raise GraphifyFailure("graphify metadata: built commit disposition is absent or malformed")
    if (metadata.get("status"), metadata.get("stale")) not in {
        ("current", False),
        ("stale", True),
    }:
        raise GraphifyFailure("graphify metadata: status and freshness disposition are inconsistent")
    source_commit = metadata.get("source_commit")
    unresolved_reasons = metadata.get("unresolved_reasons")
    if not isinstance(unresolved_reasons, list):
        raise GraphifyFailure("graphify metadata: unresolved reason ledger is malformed")
    expected_unresolved_reasons = [
        GRAPHIFY_BASE_UNRESOLVED_REASONS[0],
        (
            GRAPHIFY_HYPEREDGE_REASON_PRESENT
            if isinstance(metadata.get("total_hyperedges"), int)
            and not isinstance(metadata.get("total_hyperedges"), bool)
            and metadata["total_hyperedges"] > 0
            else GRAPHIFY_HYPEREDGE_REASON_ABSENT
        ),
        *GRAPHIFY_BASE_UNRESOLVED_REASONS[1:],
        *([GRAPHIFY_MALFORMED_BUILD_REASON] if built_commit is None else []),
    ]
    dirty_preview_staleness = metadata.get("status") == "stale" and built_commit == metadata.get("source_commit")
    if dirty_preview_staleness:
        expected_unresolved_reasons.append(GRAPHIFY_DIRTY_PREVIEW_REASON)
    if unresolved_reasons != expected_unresolved_reasons:
        raise GraphifyFailure("graphify metadata: unresolved reason ledger is malformed")
    if (metadata.get("status") == "current" and (built_commit != source_commit or dirty_preview_staleness)) or (
        metadata.get("status") == "stale" and built_commit == source_commit and not dirty_preview_staleness
    ):
        raise GraphifyFailure("graphify metadata: built commit and source freshness are inconsistent")
    numeric_names = (
        "source_bytes",
        "total_nodes",
        "projected_nodes",
        "excluded_nodes",
        "total_edges",
        "projected_edges",
        "excluded_edges",
        "total_hyperedges",
        "excluded_nodes_unsafe_source",
        "excluded_nodes_untracked_or_private",
        "total_communities",
        "projected_communities",
        "excluded_communities",
    )
    if any(
        not isinstance(metadata.get(name), int)
        or isinstance(metadata.get(name), bool)
        or metadata[name] < 0
        or metadata[name] > MAX_JS_SAFE_INTEGER
        for name in numeric_names
    ):
        raise GraphifyFailure("graphify metadata: exclusion disposition reconciliation failed: malformed count")
    if metadata["source_bytes"] == 0:
        raise GraphifyFailure("graphify metadata: source byte receipt is malformed")

    def validate_controlled_count_map(
        value: Any,
        *,
        allowed_keys: frozenset[str],
        expected_total: int,
        label: str,
    ) -> dict[str, int]:
        if not isinstance(value, dict) or any(
            not isinstance(key, str)
            or key not in allowed_keys
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
            or count > MAX_JS_SAFE_INTEGER
            for key, count in value.items()
        ):
            raise GraphifyFailure(f"graphify metadata: {label} is malformed")
        if sum(value.values()) != expected_total:
            raise GraphifyFailure(f"graphify metadata: {label} does not reconcile")
        return value

    all_edge_modes = validate_controlled_count_map(
        metadata.get("all_edge_modes"),
        allowed_keys=frozenset({"extracted", "inferred", "ambiguous", "undisclosed"}),
        expected_total=metadata["total_edges"],
        label="edge mode census",
    )
    projected_edge_modes = validate_controlled_count_map(
        metadata.get("projected_edge_modes"),
        allowed_keys=frozenset({"extracted", "inferred", "ambiguous", "undisclosed"}),
        expected_total=metadata["projected_edges"],
        label="projected edge mode census",
    )
    if any(count > all_edge_modes.get(mode, 0) for mode, count in projected_edge_modes.items()):
        raise GraphifyFailure("graphify metadata: projected edge mode census exceeds source census")
    validate_controlled_count_map(
        metadata.get("node_origins"),
        allowed_keys=frozenset({"ast", "curated", "undisclosed"}),
        expected_total=metadata["total_nodes"],
        label="node origin census",
    )
    node_records = metadata.get("excluded_node_dispositions")
    edge_records = metadata.get("excluded_edge_dispositions")
    node_counts = metadata.get("node_disposition_counts")
    identifier_counts = metadata.get("node_identifier_disposition_counts")
    edge_counts = metadata.get("excluded_edge_endpoint_dispositions")
    if (
        not isinstance(node_records, list)
        or not isinstance(edge_records, list)
        or any(not isinstance(record, dict) for record in node_records)
        or any(not isinstance(record, dict) for record in edge_records)
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: disposition array missing"
        )
    if (
        not isinstance(node_counts, dict)
        or not isinstance(identifier_counts, dict)
        or not isinstance(edge_counts, dict)
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: aggregate counts missing"
        )
    if set(node_counts) != {
        "retained",
        "excluded_unsafe_source",
        "excluded_untracked_or_private",
    }:
        raise GraphifyFailure("graphify metadata: exclusion disposition reconciliation failed: node count keys differ")
    expected_identifier_count_names = {
        "total",
        "projected_repository_relative",
        "excluded_opaque",
        "raw_published",
    }
    if (
        metadata.get("identifier_projection_policy") != OPAQUE_IDENTIFIER_POLICY
        or set(identifier_counts) != expected_identifier_count_names
        or any(
            not isinstance(identifier_counts.get(name), int)
            or isinstance(identifier_counts.get(name), bool)
            or identifier_counts[name] < 0
            or identifier_counts[name] > MAX_JS_SAFE_INTEGER
            for name in expected_identifier_count_names
        )
        or identifier_counts["total"] != metadata["total_nodes"]
        or identifier_counts["projected_repository_relative"] != metadata["projected_nodes"]
        or identifier_counts["excluded_opaque"] != metadata["excluded_nodes"]
        or identifier_counts["raw_published"] != 0
        or identifier_counts["projected_repository_relative"] + identifier_counts["excluded_opaque"]
        != identifier_counts["total"]
    ):
        raise GraphifyFailure("graphify metadata: identifier disposition reconciliation failed")
    if metadata["excluded_nodes"] != metadata["total_nodes"] - metadata["projected_nodes"]:
        raise GraphifyFailure("graphify metadata: exclusion disposition reconciliation failed: node total differs")
    if metadata["excluded_edges"] != metadata["total_edges"] - metadata["projected_edges"]:
        raise GraphifyFailure("graphify metadata: exclusion disposition reconciliation failed: edge total differs")
    expected_node_reason_counts = {
        reason: node_counts.get(reason, -1)
        for reason in (
            "excluded_unsafe_source",
            "excluded_untracked_or_private",
        )
    }
    if (
        any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_JS_SAFE_INTEGER
            for value in node_counts.values()
        )
        or node_counts.get("retained", -1) != metadata["projected_nodes"]
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: retained node count differs"
        )
    if (
        metadata["excluded_nodes_unsafe_source"] != node_counts["excluded_unsafe_source"]
        or metadata["excluded_nodes_untracked_or_private"] != node_counts["excluded_untracked_or_private"]
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: node disposition scalar differs"
        )
    if sum(expected_node_reason_counts.values()) != metadata["excluded_nodes"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: excluded node aggregate differs"
        )
    endpoint_state_pattern = (
        r"source_(?:retained|excluded_unsafe_source|excluded_untracked_or_private|missing_node)"
        r"__target_(?:retained|excluded_unsafe_source|excluded_untracked_or_private|missing_node)"
    )
    if any(
        not isinstance(key, str)
        or re.fullmatch(endpoint_state_pattern, key) is None
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > MAX_JS_SAFE_INTEGER
        for key, value in edge_counts.items()
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: endpoint count map malformed"
        )
    expected_edge_endpoint_counts = dict(edge_counts)
    if sum(expected_edge_endpoint_counts.values()) != metadata["excluded_edges"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: excluded edge aggregate differs"
        )

    def validate_community_ids(value: Any, label: str) -> list[int]:
        if (
            not isinstance(value, list)
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item < 0 or item > MAX_JS_SAFE_INTEGER
                for item in value
            )
            or value != sorted(set(value))
        ):
            raise GraphifyFailure(f"graphify metadata: {label} is malformed")
        return value

    all_community_ids = validate_community_ids(metadata.get("all_community_ids"), "community census")
    projected_community_ids = validate_community_ids(
        metadata.get("projected_community_ids"), "projected community census"
    )
    excluded_community_ids = validate_community_ids(metadata.get("excluded_community_ids"), "excluded community census")
    partial_community_ids = validate_community_ids(metadata.get("partial_community_ids"), "partial community census")
    all_community_set = set(all_community_ids)
    projected_community_set = set(projected_community_ids)
    excluded_community_set = set(excluded_community_ids)
    if (
        metadata["total_communities"] != len(all_community_ids)
        or metadata["projected_communities"] != len(projected_community_ids)
        or metadata["excluded_communities"] != len(excluded_community_ids)
        or projected_community_set & excluded_community_set
        or projected_community_set | excluded_community_set != all_community_set
        or not set(partial_community_ids) <= projected_community_set
    ):
        raise GraphifyFailure("graphify metadata: community denominator does not reconcile")
    community_dispositions = metadata.get("community_dispositions")
    community_status_counts = metadata.get("community_status_counts")
    allowed_community_statuses = {"projected_complete", "projected_partial", "excluded"}
    if (
        not isinstance(community_dispositions, list)
        or not isinstance(community_status_counts, dict)
        or set(community_status_counts) != allowed_community_statuses
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > MAX_JS_SAFE_INTEGER
            for count in community_status_counts.values()
        )
    ):
        raise GraphifyFailure("graphify metadata: community disposition ledger is malformed")
    actual_community_status_counts = {status: 0 for status in allowed_community_statuses}
    disposition_ids: list[int] = []
    derived_partial_ids: list[int] = []
    for disposition in community_dispositions:
        if not isinstance(disposition, dict) or set(disposition) != {
            "community",
            "status",
            "total_nodes",
            "retained_nodes",
            "excluded_nodes",
        }:
            raise GraphifyFailure("graphify metadata: community disposition ledger is malformed")
        community = disposition.get("community")
        total_nodes = disposition.get("total_nodes")
        retained_nodes = disposition.get("retained_nodes")
        excluded_nodes = disposition.get("excluded_nodes")
        status = disposition.get("status")
        if (
            not isinstance(community, int)
            or isinstance(community, bool)
            or community < 0
            or community > MAX_JS_SAFE_INTEGER
            or any(
                not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > MAX_JS_SAFE_INTEGER
                for count in (total_nodes, retained_nodes, excluded_nodes)
            )
            or total_nodes <= 0
            or retained_nodes + excluded_nodes != total_nodes
        ):
            raise GraphifyFailure("graphify metadata: community disposition ledger is malformed")
        expected_status = (
            "excluded"
            if retained_nodes == 0
            else ("projected_complete" if retained_nodes == total_nodes else "projected_partial")
        )
        if status != expected_status:
            raise GraphifyFailure("graphify metadata: community disposition status is inconsistent")
        disposition_ids.append(community)
        actual_community_status_counts[status] += 1
        if status == "projected_partial":
            derived_partial_ids.append(community)
    if (
        disposition_ids != all_community_ids
        or actual_community_status_counts != community_status_counts
        or derived_partial_ids != partial_community_ids
    ):
        raise GraphifyFailure("graphify metadata: community disposition ledger does not reconcile")
    if nodes is not None and edges is not None:
        if (
            any(not isinstance(node, dict) for node in nodes)
            or any(not isinstance(edge, dict) for edge in edges)
            or len(nodes) != metadata["projected_nodes"]
            or len(edges) != metadata["projected_edges"]
        ):
            raise GraphifyFailure("graphify metadata: projected record denominator does not reconcile")
        projected_community_node_counts: dict[int, int] = {}
        for node in nodes:
            community = node.get("community")
            if community is None:
                continue
            if (
                not isinstance(community, int)
                or isinstance(community, bool)
                or community < 0
                or community > MAX_JS_SAFE_INTEGER
            ):
                raise GraphifyFailure("graphify metadata: projected node community is malformed")
            projected_community_node_counts[community] = projected_community_node_counts.get(community, 0) + 1
        if sorted(projected_community_node_counts) != projected_community_ids:
            raise GraphifyFailure("graphify metadata: projected community census differs from graph nodes")
        dispositions_by_community = {disposition["community"]: disposition for disposition in community_dispositions}
        if any(
            dispositions_by_community[community]["retained_nodes"] != retained_count
            for community, retained_count in projected_community_node_counts.items()
        ):
            raise GraphifyFailure("graphify metadata: community retained-node census differs from graph nodes")
        projected_mode_counts: dict[str, int] = {}
        for edge in edges:
            mode = edge.get("extraction_mode")
            if mode not in {"extracted", "inferred", "ambiguous", "undisclosed"}:
                raise GraphifyFailure("graphify metadata: projected edge mode is malformed")
            projected_mode_counts[mode] = projected_mode_counts.get(mode, 0) + 1
        if projected_mode_counts != projected_edge_modes:
            raise GraphifyFailure("graphify metadata: projected edge mode census differs from graph edges")
    _validate_exclusion_dispositions(
        source_digest=metadata["source_digest"],
        raw_node_count=metadata["total_nodes"],
        projected_node_count=metadata["projected_nodes"],
        expected_node_indices={
            index
            for record in node_records
            if isinstance((index := record.get("raw_index")), int) and not isinstance(index, bool)
        },
        node_records=node_records,
        expected_node_reason_counts=expected_node_reason_counts,
        raw_edge_count=metadata["total_edges"],
        projected_edge_count=metadata["projected_edges"],
        expected_edge_indices={
            index
            for record in edge_records
            if isinstance((index := record.get("raw_index")), int) and not isinstance(index, bool)
        },
        edge_records=edge_records,
        expected_edge_endpoint_counts=expected_edge_endpoint_counts,
    )


def project_graphify(
    repository_root: Path,
    source_commit: str,
    source_tree_digest: str,
    safe_files: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Project only nodes grounded in fully readable tracked repository files.

    The optional source is the fixed ``graphify-out/graph.json`` path. No
    directory discovery, Vault access, or client-state access occurs.
    """

    graph_path = _fixed_regular_file(repository_root, "graphify-out/graph.json")
    report_path = _fixed_regular_file(repository_root, "graphify-out/GRAPH_REPORT.md")
    if graph_path is None:
        absent_metadata = {
            "schema_version": SCHEMA_VERSION,
            "source_commit": source_commit,
            "source_tree_digest": source_tree_digest,
            "available": False,
            "status": "absent",
            "source": "graphify-out/graph.json",
            "report_available": report_path is not None,
            "stale": None,
            "unresolved_reasons": [GRAPHIFY_ABSENT_REASON],
        }
        validate_graphify_metadata(absent_metadata)
        return absent_metadata, [], []

    try:
        metadata_before = graph_path.stat(follow_symlinks=False)
        raw = graph_path.read_bytes()
        metadata_after = graph_path.stat(follow_symlinks=False)
        if (
            metadata_before.st_size != metadata_after.st_size
            or metadata_before.st_mtime_ns != metadata_after.st_mtime_ns
            or len(raw) != metadata_after.st_size
        ):
            raise GraphifyFailure("graphify-out/graph.json: changed while it was being read")
        text = raw.decode("utf-8-sig", errors="strict")
        payload = json.loads(text)
    except OSError:
        raise GraphifyFailure("graphify-out/graph.json: read failed") from None
    except UnicodeDecodeError:
        raise GraphifyFailure("graphify-out/graph.json: input is not valid UTF-8") from None
    except RecursionError:
        raise GraphifyFailure("graphify-out/graph.json: JSON nesting exceeds the parser limit") from None
    except json.JSONDecodeError as exc:
        raise GraphifyFailure(
            f"graphify-out/graph.json: invalid JSON at line {exc.lineno} column {exc.colno}"
        ) from None
    except ValueError:
        raise GraphifyFailure("graphify-out/graph.json: parse failed") from None
    if not isinstance(payload, dict):
        raise GraphifyFailure("graphify-out/graph.json: top level must be an object")
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("links")
    raw_hyperedges = payload.get("hyperedges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise GraphifyFailure("graphify-out/graph.json: nodes and links must be arrays")
    if not isinstance(raw_hyperedges, list):
        raise GraphifyFailure("graphify-out/graph.json: hyperedges must be an array")
    if len(raw_nodes) > MAX_GRAPH_NODES or len(raw_edges) > MAX_GRAPH_EDGES:
        raise GraphifyFailure("graphify-out/graph.json: graph record cap exceeded")

    source_digest = sha256_bytes(raw)
    declared_built_commit = payload.get("built_at_commit")
    declared_built_commit_text = _utf8_text(declared_built_commit, max_length=64)
    built_commit = (
        declared_built_commit_text
        if declared_built_commit_text is not None
        and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", declared_built_commit_text)
        else None
    )
    stale = built_commit != source_commit
    retained: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    excluded_unsafe_source = 0
    excluded_untracked_or_private = 0
    duplicate_raw_ids: set[str] = set()
    seen_raw_ids: set[str] = set()
    node_origins: dict[str, int] = {}
    node_dispositions: dict[str, str] = {}
    excluded_node_refs: dict[str, str] = {}
    excluded_node_indices: set[int] = set()
    excluded_node_disposition_records: list[dict[str, Any]] = []
    raw_community_ids: set[int] = set()
    projected_community_ids: set[int] = set()
    raw_community_node_counts: dict[int, int] = {}
    projected_community_node_counts: dict[int, int] = {}
    projected_identifier_hashes: set[str] = set()
    coordinate_occurrences: dict[tuple[str, str], int] = {}
    for raw_index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise GraphifyFailure("graphify-out/graph.json: node must be an object")
        raw_id = _graph_identifier(raw_node.get("id"), record_type="node")
        if raw_id in seen_raw_ids:
            duplicate_raw_ids.add(raw_id)
            continue
        seen_raw_ids.add(raw_id)
        declared_community = raw_node.get("community")
        community = (
            declared_community
            if isinstance(declared_community, int)
            and not isinstance(declared_community, bool)
            and 0 <= declared_community <= MAX_JS_SAFE_INTEGER
            else None
        )
        if community is not None:
            raw_community_ids.add(community)
            raw_community_node_counts[community] = raw_community_node_counts.get(community, 0) + 1
        declared_origin_text = _utf8_text(raw_node.get("_origin"), max_length=MAX_GRAPH_TOKEN_LENGTH)
        declared_origin = declared_origin_text.strip().lower() if declared_origin_text is not None else ""
        if any(token in declared_origin for token in ("llm", "semantic", "openai", "anthropic")):
            raise GraphifyFailure("graphify-out/graph.json: forbidden non-AST model-derived node origin")
        origin = (
            "ast"
            if declared_origin == "ast"
            else ("curated" if declared_origin in {"curated", "manual", "human"} else "undisclosed")
        )
        node_origins[origin] = node_origins.get(origin, 0) + 1
        source_file = _safe_source_path(raw_node.get("source_file"))
        if source_file is None:
            excluded_unsafe_source += 1
            node_dispositions[raw_id] = "excluded_unsafe_source"
            excluded_node_indices.add(raw_index)
            disposition = _excluded_node_record(
                source_digest=source_digest,
                raw_index=raw_index,
                reason="excluded_unsafe_source",
            )
            excluded_node_refs[raw_id] = disposition["id"]
            excluded_node_disposition_records.append(disposition)
            continue
        file_id = safe_files.get(source_file)
        if file_id is None:
            excluded_untracked_or_private += 1
            node_dispositions[raw_id] = "excluded_untracked_or_private"
            excluded_node_indices.add(raw_index)
            disposition = _excluded_node_record(
                source_digest=source_digest,
                raw_index=raw_index,
                reason="excluded_untracked_or_private",
            )
            excluded_node_refs[raw_id] = disposition["id"]
            excluded_node_disposition_records.append(disposition)
            continue
        declared_source_location = raw_node.get("source_location")
        source_location = _safe_source_location(declared_source_location)
        coordinate = (source_file, source_location)
        coordinate_occurrence = coordinate_occurrences.get(coordinate, 0)
        coordinate_occurrences[coordinate] = coordinate_occurrence + 1
        projected_identifier_hash = _projected_identifier_hash(
            source_file,
            source_location,
            coordinate_occurrence,
        )
        if projected_identifier_hash in projected_identifier_hashes:
            raise GraphifyFailure(
                "graphify-out/graph.json: projected repository-relative node identifiers are not one-to-one"
            )
        projected_identifier_hashes.add(projected_identifier_hash)
        node_id = stable_id("graph-node", source_commit, projected_identifier_hash)
        retained[raw_id] = node_id
        node_dispositions[raw_id] = "retained"
        if community is not None:
            projected_community_ids.add(community)
            projected_community_node_counts[community] = projected_community_node_counts.get(community, 0) + 1
        metadata = raw_node.get("metadata") if isinstance(raw_node.get("metadata"), dict) else {}
        extraction_mode = "extracted" if origin == "ast" else origin
        label = f"{source_file}:{source_location or 'source'}#{coordinate_occurrence + 1}"
        file_type, file_type_is_safe = _controlled_public_token(
            raw_node.get("file_type"),
            vocabulary=CONTROLLED_GRAPH_FILE_TYPES,
            fallback="",
        )
        language, language_is_safe = _controlled_public_token(
            metadata.get("language"),
            vocabulary=CONTROLLED_GRAPH_LANGUAGES,
            fallback="",
        )
        kind, kind_is_safe = _controlled_public_token(
            metadata.get("kind"),
            vocabulary=CONTROLLED_GRAPH_KINDS,
            fallback="",
        )
        node_unresolved_reasons = ["graphify_node_label_derived_from_repository_relative_coordinate"]
        if origin != "ast":
            node_unresolved_reasons.append("graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction")
        if declared_community is not None and community is None:
            node_unresolved_reasons.append("graphify_node_community_outside_js_safe_nonnegative_integer_domain")
        if declared_source_location is not None and declared_source_location != "" and not source_location:
            node_unresolved_reasons.append("graphify_node_source_location_outside_bounded_coordinate_domain")
        producer_descriptor_values = (
            raw_node.get("file_type"),
            metadata.get("language"),
            metadata.get("kind"),
        )
        descriptor_safety = (file_type_is_safe, language_is_safe, kind_is_safe)
        if any(
            (value is not None and value != "") and not safe
            for value, safe in zip(producer_descriptor_values, descriptor_safety)
        ):
            node_unresolved_reasons.append("graphify_node_nonvocabulary_descriptor_withheld")
        nodes.append(
            {
                "id": node_id,
                "graphify_id": projected_identifier_hash,
                "coordinate_occurrence": coordinate_occurrence,
                "file_id": file_id,
                "source_file": source_file,
                "source_location": source_location,
                "label": label,
                "file_type": file_type,
                "language": language,
                "kind": kind,
                "community": community,
                "origin": origin,
                "extraction_mode": extraction_mode,
                "unresolved_reasons": node_unresolved_reasons,
            }
        )
    if duplicate_raw_ids:
        raise GraphifyFailure(
            f"graphify-out/graph.json: duplicate node ids: {len(duplicate_raw_ids)} duplicate value(s)"
        )

    edges: list[dict[str, Any]] = []
    all_modes: dict[str, int] = {}
    projected_modes: dict[str, int] = {}
    excluded_edge_endpoint_dispositions: dict[str, int] = {}
    excluded_edge_indices: set[int] = set()
    excluded_edge_disposition_records: list[dict[str, Any]] = []
    anonymous_missing_slots: dict[str, int] = {}
    retained_edge_occurrences: dict[tuple[object, ...], int] = {}
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise GraphifyFailure("graphify-out/graph.json: link must be an object")
        mode = _mode(raw_edge.get("confidence"))
        all_modes[mode] = all_modes.get(mode, 0) + 1
        source = _graph_identifier(raw_edge.get("source"), record_type="link source")
        target = _graph_identifier(raw_edge.get("target"), record_type="link target")
        if source not in retained or target not in retained:
            disposition = (
                f"source_{node_dispositions.get(source, 'missing_node')}__"
                f"target_{node_dispositions.get(target, 'missing_node')}"
            )
            excluded_edge_endpoint_dispositions[disposition] = (
                excluded_edge_endpoint_dispositions.get(disposition, 0) + 1
            )
            excluded_edge_indices.add(index)
            excluded_edge_disposition_records.append(
                _excluded_edge_record(
                    source_digest=source_digest,
                    raw_index=index,
                    source=source,
                    target=target,
                    node_dispositions=node_dispositions,
                    retained=retained,
                    excluded_node_refs=excluded_node_refs,
                    anonymous_missing_slots=anonymous_missing_slots,
                )
            )
            continue
        edge_source_file = _safe_source_path(raw_edge.get("source_file"))
        declared_edge_source_file = raw_edge.get("source_file")
        if (
            declared_edge_source_file is not None
            and declared_edge_source_file != ""
            and edge_source_file not in safe_files
        ):
            raise GraphifyFailure(
                "graphify-out/graph.json: retained edge carries an untracked, private, or unsafe source_file"
            )
        projected_modes[mode] = projected_modes.get(mode, 0) + 1
        relation, relation_is_safe = _safe_relation(raw_edge.get("relation"))
        score, score_identity = _confidence_identity(raw_edge.get("confidence_score"))
        declared_edge_source_location = raw_edge.get("source_location")
        source_location = _safe_source_location(declared_edge_source_location)
        public_edge_coordinate: tuple[object, ...] = (
            retained[source],
            retained[target],
            relation,
            edge_source_file or "",
            source_location,
            mode,
            score_identity,
        )
        edge_occurrence = retained_edge_occurrences.get(public_edge_coordinate, 0)
        retained_edge_occurrences[public_edge_coordinate] = edge_occurrence + 1
        edge_id = stable_id(
            "graph-edge",
            source_commit,
            *public_edge_coordinate,
            edge_occurrence,
        )
        edge_unresolved_reasons = []
        if mode not in {"extracted", "inferred"}:
            edge_unresolved_reasons.append("graphify_confidence_mode_undisclosed_or_ambiguous")
        if not relation_is_safe:
            edge_unresolved_reasons.append("graphify_relation_not_in_controlled_vocabulary_shape")
        if declared_edge_source_location is not None and declared_edge_source_location != "" and not source_location:
            edge_unresolved_reasons.append("graphify_edge_source_location_outside_bounded_coordinate_domain")
        edges.append(
            {
                "id": edge_id,
                "source": retained[source],
                "target": retained[target],
                "relation": relation,
                "coordinate_occurrence": edge_occurrence,
                "source_file": edge_source_file,
                "source_location": source_location,
                "extraction_mode": mode,
                "confidence": score,
                "unresolved_reasons": edge_unresolved_reasons,
            }
        )

    nodes.sort(key=lambda row: row["id"])
    edges.sort(key=lambda row: row["id"])
    excluded_node_disposition_records.sort(key=lambda row: row["id"])
    excluded_edge_disposition_records.sort(key=lambda row: row["id"])
    node_reason_counts = {
        "excluded_unsafe_source": excluded_unsafe_source,
        "excluded_untracked_or_private": excluded_untracked_or_private,
    }
    _validate_exclusion_dispositions(
        source_digest=source_digest,
        raw_node_count=len(raw_nodes),
        projected_node_count=len(nodes),
        expected_node_indices=excluded_node_indices,
        node_records=excluded_node_disposition_records,
        expected_node_reason_counts=node_reason_counts,
        raw_edge_count=len(raw_edges),
        projected_edge_count=len(edges),
        expected_edge_indices=excluded_edge_indices,
        edge_records=excluded_edge_disposition_records,
        expected_edge_endpoint_counts=excluded_edge_endpoint_dispositions,
    )
    community_dispositions = []
    for community in sorted(raw_community_ids):
        total_nodes = raw_community_node_counts[community]
        retained_nodes = projected_community_node_counts.get(community, 0)
        status = (
            "excluded"
            if retained_nodes == 0
            else ("projected_complete" if retained_nodes == total_nodes else "projected_partial")
        )
        community_dispositions.append(
            {
                "community": community,
                "status": status,
                "total_nodes": total_nodes,
                "retained_nodes": retained_nodes,
                "excluded_nodes": total_nodes - retained_nodes,
            }
        )
    community_status_counts = {
        status: sum(1 for item in community_dispositions if item["status"] == status)
        for status in ("projected_complete", "projected_partial", "excluded")
    }
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "status": "stale" if stale else "current",
        "source": "graphify-out/graph.json",
        "source_bytes": len(raw),
        "source_digest": source_digest,
        "report_available": report_path is not None,
        "built_at_commit": built_commit,
        "source_commit": source_commit,
        "source_tree_digest": source_tree_digest,
        "stale": stale,
        "total_nodes": len(raw_nodes),
        "total_edges": len(raw_edges),
        "total_hyperedges": len(raw_hyperedges),
        "projected_nodes": len(nodes),
        "projected_edges": len(edges),
        "excluded_nodes": len(raw_nodes) - len(nodes),
        "excluded_edges": len(raw_edges) - len(edges),
        "excluded_node_dispositions": excluded_node_disposition_records,
        "excluded_edge_dispositions": excluded_edge_disposition_records,
        "excluded_edge_endpoint_dispositions": dict(sorted(excluded_edge_endpoint_dispositions.items())),
        "all_edge_modes": dict(sorted(all_modes.items())),
        "projected_edge_modes": dict(sorted(projected_modes.items())),
        "node_origins": dict(sorted(node_origins.items())),
        "excluded_nodes_unsafe_source": excluded_unsafe_source,
        "excluded_nodes_untracked_or_private": excluded_untracked_or_private,
        "node_disposition_counts": {
            "retained": len(nodes),
            "excluded_unsafe_source": excluded_unsafe_source,
            "excluded_untracked_or_private": excluded_untracked_or_private,
        },
        "identifier_projection_policy": OPAQUE_IDENTIFIER_POLICY,
        "node_identifier_disposition_counts": {
            "total": len(raw_nodes),
            "projected_repository_relative": len(nodes),
            "excluded_opaque": len(raw_nodes) - len(nodes),
            "raw_published": 0,
        },
        "total_communities": len(raw_community_ids),
        "projected_communities": len(projected_community_ids),
        "excluded_communities": len(raw_community_ids - projected_community_ids),
        "all_community_ids": sorted(raw_community_ids),
        "projected_community_ids": sorted(projected_community_ids),
        "excluded_community_ids": sorted(raw_community_ids - projected_community_ids),
        "partial_community_ids": [
            item["community"] for item in community_dispositions if item["status"] == "projected_partial"
        ],
        "community_status_counts": community_status_counts,
        "community_dispositions": community_dispositions,
        "projection_policy": "tracked_full_exposure_files_only",
        "unresolved_reasons": [
            GRAPHIFY_BASE_UNRESOLVED_REASONS[0],
            GRAPHIFY_HYPEREDGE_REASON_PRESENT if raw_hyperedges else GRAPHIFY_HYPEREDGE_REASON_ABSENT,
            *GRAPHIFY_BASE_UNRESOLVED_REASONS[1:],
            *([GRAPHIFY_MALFORMED_BUILD_REASON] if built_commit is None else []),
        ],
    }
    validate_graphify_metadata(metadata, nodes, edges)
    return metadata, nodes, edges


def verify_graphify_snapshot(repository_root: Path, metadata: dict[str, Any]) -> None:
    """Fail if an available Graphify source changed after projection."""

    if not metadata.get("available") or not metadata.get("source_digest"):
        return
    graph_path = _fixed_regular_file(repository_root, "graphify-out/graph.json")
    if graph_path is None:
        raise GraphifyFailure("graphify-out/graph.json: disappeared after projection")
    try:
        raw = graph_path.read_bytes()
    except OSError:
        raise GraphifyFailure("graphify-out/graph.json: verification read failed") from None
    if sha256_bytes(raw) != metadata["source_digest"]:
        raise GraphifyFailure("graphify-out/graph.json: changed after projection")
