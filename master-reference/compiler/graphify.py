"""Read-only, privacy-filtered projection of an optional local Graphify graph."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from .model import sha256_bytes, stable_id, text_preview


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


def project_graphify(
    repository_root: Path,
    source_commit: str,
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
    for raw_node in raw_nodes:
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
            continue
        file_id = safe_files.get(source_file)
        if file_id is None:
            excluded_untracked_or_private += 1
            continue
        node_id = stable_id("graph-node", built_commit or "unknown", raw_id)
        retained[raw_id] = node_id
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
                "community": raw_node.get("community") if isinstance(raw_node.get("community"), int) else None,
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
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise GraphifyFailure("graphify-out/graph.json: link must be an object")
        mode = _mode(raw_edge.get("confidence"))
        all_modes[mode] = all_modes.get(mode, 0) + 1
        source = str(raw_edge.get("source"))
        target = str(raw_edge.get("target"))
        if source not in retained or target not in retained:
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
    metadata = {
        "available": True,
        "status": "stale" if stale else "current",
        "source": "graphify-out/graph.json",
        "source_bytes": len(raw),
        "source_digest": sha256_bytes(raw),
        "report_available": report_path is not None,
        "built_at_commit": built_commit,
        "source_commit": source_commit,
        "stale": stale,
        "total_nodes": len(raw_nodes),
        "total_edges": len(raw_edges),
        "total_hyperedges": len(raw_hyperedges),
        "projected_nodes": len(nodes),
        "projected_edges": len(edges),
        "all_edge_modes": dict(sorted(all_modes.items())),
        "projected_edge_modes": dict(sorted(projected_modes.items())),
        "node_origins": dict(sorted(node_origins.items())),
        "excluded_nodes_unsafe_source": excluded_unsafe_source,
        "excluded_nodes_untracked_or_private": excluded_untracked_or_private,
        "projection_policy": "tracked_full_exposure_files_only",
        "unresolved_reasons": [
            "graphify_is_optional_secondary_projection",
            "graphify_hyperedges_not_projected" if raw_hyperedges else "graphify_has_no_hyperedges",
        ],
    }
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
