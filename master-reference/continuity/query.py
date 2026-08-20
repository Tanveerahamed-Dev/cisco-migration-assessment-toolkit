"""Deterministic, citation-first queries over an exact compiler bundle."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .model import ContinuityInputError, safe_relative


REFERENCE_FIELDS = frozenset(
    {
        "GUI_or_artifact_consumers",
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
        "known_impact_if_changed",
        "owner",
        "semantic_entity",
        "tests",
    }
)


def _records(bundle: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    for group in sorted(bundle.records):
        for record in bundle.records[group]:
            yield group, record


def _references(record: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for field in REFERENCE_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value:
            result.add(value)
        elif isinstance(value, list):
            result.update(str(item) for item in value if isinstance(item, str) and item)
    return result


def _summary(group: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "record_type": group,
        "path": record.get("path") or record.get("source_path"),
        "name": record.get("qualified_name")
        or record.get("name")
        or record.get("predicate")
        or record.get("claim_kind"),
        "range": record.get("range"),
    }


def _base(bundle: Any, mode: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "mode": mode,
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "release_class": bundle.manifest.get("release_class"),
    }


def query_by_id(bundle: Any, identifier: str) -> tuple[int, dict[str, Any]]:
    matches = [(group, record) for group, record in _records(bundle) if record.get("id") == identifier]
    if not matches:
        return 3, {
            **_base(bundle, "id"),
            "status": "abstained",
            "reason": "stable_id_not_found_in_exact_bundle",
            "query": identifier,
        }
    if len(matches) != 1:
        raise ContinuityInputError("compiler bundle contains a duplicate stable id")
    group, record = matches[0]
    return 0, {**_base(bundle, "id"), "status": "answered", "record_type": group, "record": record}


def query_by_path(bundle: Any, path: str, line: int | None = None) -> tuple[int, dict[str, Any]]:
    path = safe_relative(path)
    if line is not None and line <= 0:
        raise ContinuityInputError("line must be a positive integer")
    matches = [
        (group, record)
        for group, record in _records(bundle)
        if (record.get("path") or record.get("source_path")) == path
    ]
    if not matches:
        return 3, {
            **_base(bundle, "path"),
            "status": "abstained",
            "reason": "path_not_found_in_exact_bundle",
            "query": {"path": path, "line": line},
        }
    if line is None:
        summaries = sorted(
            (_summary(group, record) for group, record in matches), key=lambda row: (row["record_type"], str(row["id"]))
        )
        return 0, {
            **_base(bundle, "path"),
            "status": "answered",
            "query": {"path": path},
            "records": summaries,
        }
    line_records = [
        record
        for group, record in matches
        if group == "lines" and int(record.get("line_number") or record.get("line") or 0) == line
    ]
    source_lines: list[dict[str, Any]] = []
    for group, record in matches:
        if group != "source_text":
            continue
        source_lines.extend(
            item for item in record.get("lines", []) if isinstance(item, dict) and item.get("number") == line
        )
    if not line_records and not source_lines:
        return 3, {
            **_base(bundle, "path-line"),
            "status": "abstained",
            "reason": "line_not_present_or_blank_in_exact_bundle",
            "query": {"path": path, "line": line},
        }
    return 0, {
        **_base(bundle, "path-line"),
        "status": "answered",
        "query": {"path": path, "line": line},
        "line_records": line_records,
        "source_lines": source_lines,
    }


def query_impact(bundle: Any, identifier: str) -> tuple[int, dict[str, Any]]:
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    incoming: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for group, record in _records(bundle):
        record_id = record.get("id")
        if isinstance(record_id, str):
            by_id[record_id] = (group, record)
        for reference in _references(record):
            incoming[reference].append((group, record))
    target = by_id.get(identifier)
    if target is None:
        return 3, {
            **_base(bundle, "impact"),
            "status": "abstained",
            "reason": "impact_subject_not_found_in_exact_bundle",
            "query": identifier,
        }
    group, record = target
    outgoing_ids = sorted(_references(record))
    outgoing = [_summary(*by_id[reference]) for reference in outgoing_ids if reference in by_id]
    unresolved = [reference for reference in outgoing_ids if reference not in by_id]
    inbound = sorted(
        (_summary(incoming_group, incoming_record) for incoming_group, incoming_record in incoming.get(identifier, [])),
        key=lambda row: (row["record_type"], str(row["id"])),
    )
    return 0, {
        **_base(bundle, "impact"),
        "status": "answered",
        "subject": _summary(group, record),
        "incoming_references": inbound,
        "outgoing_references": sorted(outgoing, key=lambda row: (row["record_type"], str(row["id"]))),
        "unresolved_outgoing_reference_ids": unresolved,
        "limits": [
            "This is a one-hop compiler-reference traversal, not runtime blast-radius proof.",
            "Static call and import references remain possible dependencies, not observed execution.",
        ],
    }
