"""Read-only, privacy-filtered projection of an optional local Graphify graph."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from .model import SCHEMA_VERSION, canonical_json, sha256_bytes, stable_id, text_preview


MAX_GRAPH_BYTES = 256 * 1024 * 1024
MAX_GRAPH_NODES = 500_000
MAX_GRAPH_EDGES = 2_000_000


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
        except OSError as exc:
            raise GraphifyFailure(f"{relative}: metadata read failed: {exc}") from exc
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


def _safe_source_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = value.replace("\\", "/")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        return None
    if len(candidate.parts[0]) == 2 and candidate.parts[0][1] == ":":
        return None
    return candidate.as_posix()


def _mode(value: Any) -> str:
    confidence = str(value or "").strip().lower()
    if confidence == "inferred":
        return "inferred"
    if confidence == "ambiguous":
        return "ambiguous"
    if confidence == "extracted":
        return "extracted"
    return "undisclosed"


def _safe_source_location(value: Any) -> str:
    """Retain line/column coordinates, never an arbitrary path or snippet."""

    location = str(value or "").strip()
    if re.fullmatch(r"L?\d+(?::\d+)?(?:-L?\d+(?::\d+)?)?", location):
        return location
    return ""


def _opaque_hash(*parts: object) -> str:
    """Hash a Graphify identity without publishing its raw value.

    The graph source digest is included by each caller, so the token is stable
    for an exact Graphify artifact while remaining an opaque, source-bound
    traversal key.  Raw identifiers, paths, labels, relations, and snippets
    never enter an exclusion disposition record.
    """

    return sha256_bytes(canonical_json([str(part) for part in parts]))


def _excluded_node_record(
    *,
    source_digest: str,
    raw_index: int,
    raw_id: str,
    raw_node: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    raw_record_digest = sha256_bytes(canonical_json(raw_node))
    opaque_identifier_hash = _opaque_hash(source_digest, "node-identifier", raw_id)
    opaque_record_hash = _opaque_hash(
        source_digest,
        "excluded-node-record",
        raw_index,
        raw_record_digest,
    )
    return {
        "id": stable_id("graph-node-disposition", opaque_record_hash),
        "disposition": "excluded",
        "raw_index": raw_index,
        "opaque_record_hash": opaque_record_hash,
        "opaque_identifier_hash": opaque_identifier_hash,
        "raw_record_digest": raw_record_digest,
        "reason": reason,
    }


def _edge_endpoint_record(
    *,
    source_digest: str,
    raw_id: str,
    state: str,
    retained: dict[str, str],
    excluded_node_refs: dict[str, str],
) -> dict[str, Any]:
    return {
        "state": state,
        "record_id": retained.get(raw_id) or excluded_node_refs.get(raw_id),
        "opaque_identifier_hash": _opaque_hash(
            source_digest,
            "node-identifier",
            raw_id,
        ),
    }


def _excluded_edge_record(
    *,
    source_digest: str,
    raw_index: int,
    raw_edge: dict[str, Any],
    source: str,
    target: str,
    node_dispositions: dict[str, str],
    retained: dict[str, str],
    excluded_node_refs: dict[str, str],
) -> dict[str, Any]:
    raw_record_digest = sha256_bytes(canonical_json(raw_edge))
    opaque_record_hash = _opaque_hash(
        source_digest,
        "excluded-edge-record",
        raw_index,
        raw_record_digest,
    )
    source_state = node_dispositions.get(source, "missing_node")
    target_state = node_dispositions.get(target, "missing_node")
    return {
        "id": stable_id("graph-edge-disposition", opaque_record_hash),
        "disposition": "excluded",
        "raw_index": raw_index,
        "opaque_record_hash": opaque_record_hash,
        "raw_record_digest": raw_record_digest,
        "reason": "endpoint_not_projected",
        "source_endpoint": _edge_endpoint_record(
            source_digest=source_digest,
            raw_id=source,
            state=source_state,
            retained=retained,
            excluded_node_refs=excluded_node_refs,
        ),
        "target_endpoint": _edge_endpoint_record(
            source_digest=source_digest,
            raw_id=target,
            state=target_state,
            retained=retained,
            excluded_node_refs=excluded_node_refs,
        ),
    }


def _validate_exclusion_dispositions(
    *,
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
    ) -> None:
        if len(records) != expected_count:
            errors.append(f"{label} count expected {expected_count}, found {len(records)}")
        indices = [record.get("raw_index") for record in records]
        if any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= raw_count
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
        opaque_hashes = [record.get("opaque_record_hash") for record in records]
        if len(opaque_hashes) != len(set(opaque_hashes)):
            errors.append(f"{label} opaque record hashes are not unique")
        if any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in opaque_hashes
        ):
            errors.append(f"{label} opaque record hash is malformed")
        if any(
            not isinstance(record.get("raw_record_digest"), str)
            or re.fullmatch(r"[0-9a-f]{64}", record["raw_record_digest"]) is None
            for record in records
        ):
            errors.append(f"{label} raw record digest is malformed")

    expected_excluded_nodes = raw_node_count - projected_node_count
    validate_common(
        "excluded node dispositions",
        node_records,
        expected_node_indices,
        expected_excluded_nodes,
        raw_node_count,
    )
    actual_node_reasons: dict[str, int] = {
        reason: 0 for reason in expected_node_reason_counts
    }
    node_identifier_hashes: list[str] = []
    node_records_by_id: dict[str, dict[str, Any]] = {}
    for record in node_records:
        reason = str(record.get("reason") or "")
        actual_node_reasons[reason] = actual_node_reasons.get(reason, 0) + 1
        node_identifier_hashes.append(str(record.get("opaque_identifier_hash") or ""))
        if isinstance(record.get("id"), str):
            node_records_by_id[record["id"]] = record
    if actual_node_reasons != expected_node_reason_counts:
        errors.append("excluded node reason counts do not reconcile")
    if len(node_identifier_hashes) != len(set(node_identifier_hashes)):
        errors.append("excluded node identifier hashes are not one-to-one")
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in node_identifier_hashes):
        errors.append("excluded node identifier hash is malformed")

    expected_excluded_edges = raw_edge_count - projected_edge_count
    validate_common(
        "excluded edge dispositions",
        edge_records,
        expected_edge_indices,
        expected_excluded_edges,
        raw_edge_count,
    )
    actual_endpoint_counts: dict[str, int] = {}
    allowed_endpoint_states = {
        "retained",
        "excluded_unsafe_source",
        "excluded_untracked_or_private",
        "missing_node",
    }
    for record in edge_records:
        source_endpoint = record.get("source_endpoint")
        target_endpoint = record.get("target_endpoint")
        if not isinstance(source_endpoint, dict) or not isinstance(target_endpoint, dict):
            errors.append("excluded edge endpoint disposition is malformed")
            continue
        source_state = str(source_endpoint.get("state") or "")
        target_state = str(target_endpoint.get("state") or "")
        if source_state not in allowed_endpoint_states or target_state not in allowed_endpoint_states:
            errors.append("excluded edge endpoint state is unknown")
        disposition = f"source_{source_state}__target_{target_state}"
        actual_endpoint_counts[disposition] = actual_endpoint_counts.get(disposition, 0) + 1
        for endpoint in (source_endpoint, target_endpoint):
            opaque_hash = endpoint.get("opaque_identifier_hash")
            if not isinstance(opaque_hash, str) or re.fullmatch(r"[0-9a-f]{64}", opaque_hash) is None:
                errors.append("excluded edge endpoint identifier hash is malformed")
            if endpoint.get("state") == "missing_node" and endpoint.get("record_id") is not None:
                errors.append("missing excluded edge endpoint unexpectedly resolves to a record")
            if endpoint.get("state") != "missing_node" and not endpoint.get("record_id"):
                errors.append("known excluded edge endpoint does not resolve to a record")
            if endpoint.get("state") in {
                "excluded_unsafe_source",
                "excluded_untracked_or_private",
            }:
                node_record = node_records_by_id.get(str(endpoint.get("record_id") or ""))
                if node_record is None:
                    errors.append("excluded edge endpoint does not traverse to its node disposition")
                elif endpoint.get("opaque_identifier_hash") != node_record.get("opaque_identifier_hash"):
                    errors.append("excluded edge endpoint hash differs from its node disposition")
    if actual_endpoint_counts != expected_edge_endpoint_counts:
        errors.append("excluded edge endpoint counts do not reconcile")
    if any(record.get("reason") != "endpoint_not_projected" for record in edge_records):
        errors.append("excluded edge reason is not controlled")

    if errors:
        raise GraphifyFailure(
            "graphify-out/graph.json: exclusion disposition reconciliation failed: "
            + "; ".join(sorted(set(errors)))
        )


def validate_graphify_metadata(metadata: dict[str, Any]) -> None:
    """Reconcile a persisted metadata ledger without re-reading unsafe input."""

    if not metadata.get("available"):
        return
    numeric_names = (
        "total_nodes",
        "projected_nodes",
        "excluded_nodes",
        "total_edges",
        "projected_edges",
        "excluded_edges",
    )
    if any(
        not isinstance(metadata.get(name), int)
        or isinstance(metadata.get(name), bool)
        or int(metadata[name]) < 0
        for name in numeric_names
    ):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: malformed count"
        )
    node_records = metadata.get("excluded_node_dispositions")
    edge_records = metadata.get("excluded_edge_dispositions")
    node_counts = metadata.get("node_disposition_counts")
    edge_counts = metadata.get("excluded_edge_endpoint_dispositions")
    if not isinstance(node_records, list) or not isinstance(edge_records, list):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: disposition array missing"
        )
    if not isinstance(node_counts, dict) or not isinstance(edge_counts, dict):
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: aggregate counts missing"
        )
    if metadata["excluded_nodes"] != metadata["total_nodes"] - metadata["projected_nodes"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: node total differs"
        )
    if metadata["excluded_edges"] != metadata["total_edges"] - metadata["projected_edges"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: edge total differs"
        )
    expected_node_reason_counts = {
        reason: int(node_counts.get(reason, -1))
        for reason in (
            "excluded_unsafe_source",
            "excluded_untracked_or_private",
        )
    }
    if int(node_counts.get("retained", -1)) != metadata["projected_nodes"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: retained node count differs"
        )
    if sum(expected_node_reason_counts.values()) != metadata["excluded_nodes"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: excluded node aggregate differs"
        )
    expected_edge_endpoint_counts = {
        str(key): int(value) for key, value in edge_counts.items()
    }
    if sum(expected_edge_endpoint_counts.values()) != metadata["excluded_edges"]:
        raise GraphifyFailure(
            "graphify metadata: exclusion disposition reconciliation failed: excluded edge aggregate differs"
        )
    _validate_exclusion_dispositions(
        raw_node_count=metadata["total_nodes"],
        projected_node_count=metadata["projected_nodes"],
        expected_node_indices={record.get("raw_index") for record in node_records},
        node_records=node_records,
        expected_node_reason_counts=expected_node_reason_counts,
        raw_edge_count=metadata["total_edges"],
        projected_edge_count=metadata["projected_edges"],
        expected_edge_indices={record.get("raw_index") for record in edge_records},
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
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "source_commit": source_commit,
                "source_tree_digest": source_tree_digest,
                "available": False,
                "status": "absent",
                "source": "graphify-out/graph.json",
                "report_available": report_path is not None,
                "stale": None,
                "unresolved_reasons": ["optional_graphify_projection_not_present"],
            },
            [],
            [],
        )

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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GraphifyFailure(f"graphify-out/graph.json: parse failed: {exc}") from exc
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
    built_commit = payload.get("built_at_commit")
    built_commit = built_commit if isinstance(built_commit, str) else None
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
    for raw_index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise GraphifyFailure("graphify-out/graph.json: node must be an object")
        raw_id = raw_node.get("id")
        if not isinstance(raw_id, (str, int)):
            raise GraphifyFailure("graphify-out/graph.json: node id must be text or integer")
        raw_id = str(raw_id)
        if raw_id in seen_raw_ids:
            duplicate_raw_ids.add(raw_id)
            continue
        seen_raw_ids.add(raw_id)
        community = raw_node.get("community")
        if isinstance(community, int):
            raw_community_ids.add(community)
            raw_community_node_counts[community] = raw_community_node_counts.get(community, 0) + 1
        declared_origin = raw_node.get("_origin")
        origin = (
            str(declared_origin).lower() if declared_origin is not None and declared_origin != "" else "undisclosed"
        )
        node_origins[origin] = node_origins.get(origin, 0) + 1
        if any(token in origin for token in ("llm", "semantic", "openai", "anthropic")):
            raise GraphifyFailure(f"graphify-out/graph.json: forbidden non-AST model-derived node origin {origin!r}")
        source_file = _safe_source_path(raw_node.get("source_file"))
        if source_file is None:
            excluded_unsafe_source += 1
            node_dispositions[raw_id] = "excluded_unsafe_source"
            excluded_node_indices.add(raw_index)
            disposition = _excluded_node_record(
                source_digest=source_digest,
                raw_index=raw_index,
                raw_id=raw_id,
                raw_node=raw_node,
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
                raw_id=raw_id,
                raw_node=raw_node,
                reason="excluded_untracked_or_private",
            )
            excluded_node_refs[raw_id] = disposition["id"]
            excluded_node_disposition_records.append(disposition)
            continue
        node_id = stable_id("graph-node", built_commit or "unknown", raw_id)
        retained[raw_id] = node_id
        node_dispositions[raw_id] = "retained"
        if isinstance(community, int):
            projected_community_ids.add(community)
            projected_community_node_counts[community] = (
                projected_community_node_counts.get(community, 0) + 1
            )
        metadata = raw_node.get("metadata") if isinstance(raw_node.get("metadata"), dict) else {}
        extraction_mode = (
            "extracted"
            if origin == "ast"
            else ("curated" if origin in {"curated", "manual", "human"} else "undisclosed")
        )
        nodes.append(
            {
                "id": node_id,
                "graphify_id": raw_id,
                "file_id": file_id,
                "source_file": source_file,
                "source_location": _safe_source_location(raw_node.get("source_location")),
                "label": text_preview(str(raw_node.get("label") or raw_id)),
                "file_type": text_preview(str(raw_node.get("file_type") or "")),
                "language": text_preview(str(metadata.get("language") or "")),
                "kind": text_preview(str(metadata.get("kind") or "")),
                "community": community if isinstance(community, int) else None,
                "origin": origin,
                "extraction_mode": extraction_mode,
                "unresolved_reasons": []
                if origin == "ast"
                else ["graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction"],
            }
        )
    if duplicate_raw_ids:
        sample = ", ".join(sorted(duplicate_raw_ids)[:5])
        raise GraphifyFailure(f"graphify-out/graph.json: duplicate node ids: {sample}")

    edges: list[dict[str, Any]] = []
    all_modes: dict[str, int] = {}
    projected_modes: dict[str, int] = {}
    excluded_edge_endpoint_dispositions: dict[str, int] = {}
    excluded_edge_indices: set[int] = set()
    excluded_edge_disposition_records: list[dict[str, Any]] = []
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise GraphifyFailure("graphify-out/graph.json: link must be an object")
        mode = _mode(raw_edge.get("confidence"))
        all_modes[mode] = all_modes.get(mode, 0) + 1
        source = str(raw_edge.get("source"))
        target = str(raw_edge.get("target"))
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
                    raw_edge=raw_edge,
                    source=source,
                    target=target,
                    node_dispositions=node_dispositions,
                    retained=retained,
                    excluded_node_refs=excluded_node_refs,
                )
            )
            continue
        edge_source_file = _safe_source_path(raw_edge.get("source_file"))
        if raw_edge.get("source_file") not in {None, ""} and edge_source_file not in safe_files:
            raise GraphifyFailure(
                "graphify-out/graph.json: retained edge carries an untracked, private, or unsafe source_file"
            )
        projected_modes[mode] = projected_modes.get(mode, 0) + 1
        relation = text_preview(str(raw_edge.get("relation") or "related_to"))
        score = raw_edge.get("confidence_score")
        score = float(score) if isinstance(score, (int, float)) else None
        edge_id = stable_id("graph-edge", built_commit or "unknown", source, target, relation, index)
        edges.append(
            {
                "id": edge_id,
                "source": retained[source],
                "target": retained[target],
                "relation": relation,
                "source_file": edge_source_file,
                "source_location": _safe_source_location(raw_edge.get("source_location")),
                "extraction_mode": mode,
                "confidence": score,
                "unresolved_reasons": []
                if mode in {"extracted", "inferred"}
                else ["graphify_confidence_mode_undisclosed_or_ambiguous"],
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
        "excluded_edge_endpoint_dispositions": dict(
            sorted(excluded_edge_endpoint_dispositions.items())
        ),
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
        "total_communities": len(raw_community_ids),
        "projected_communities": len(projected_community_ids),
        "excluded_communities": len(raw_community_ids - projected_community_ids),
        "all_community_ids": sorted(raw_community_ids),
        "projected_community_ids": sorted(projected_community_ids),
        "excluded_community_ids": sorted(raw_community_ids - projected_community_ids),
        "partial_community_ids": [
            item["community"]
            for item in community_dispositions
            if item["status"] == "projected_partial"
        ],
        "community_status_counts": community_status_counts,
        "community_dispositions": community_dispositions,
        "projection_policy": "tracked_full_exposure_files_only",
        "unresolved_reasons": [
            "graphify_is_optional_secondary_projection",
            "graphify_hyperedges_not_projected" if raw_hyperedges else "graphify_has_no_hyperedges",
        ],
    }
    validate_graphify_metadata(metadata)
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
    except OSError as exc:
        raise GraphifyFailure(f"graphify-out/graph.json: verification read failed: {exc}") from exc
    if sha256_bytes(raw) != metadata["source_digest"]:
        raise GraphifyFailure("graphify-out/graph.json: changed after projection")
