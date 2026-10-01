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


IDENTITY_DEPTH = "identity"
CENSUS_DEPTH_CLAIM = (
    "This path is censused at identity depth: its file record, static imports and a full-content privacy "
    "decision are projected. Its lines, symbols, calls, structured values, source text and dossiers are "
    "deferred, never covered; their absence from this bundle is not absence from the source."
)


def _census_receipt(bundle: Any) -> dict[str, Any] | None:
    completeness = getattr(bundle, "completeness", None)
    if not isinstance(completeness, dict) or "census_depth" not in completeness:
        return None
    receipt = completeness["census_depth"]
    if not isinstance(receipt, dict) or not isinstance(receipt.get("declarations"), list):
        raise ContinuityInputError("compiler census-depth receipt is malformed")
    return receipt


def census_depth_disclosure(
    bundle: Any,
    path: str | None,
    file_record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the census-depth disclosure for ``path``, or ``None`` at full depth.

    The declaration is read from the exact bundle's census-depth receipt (the
    compiler rejoined it to the one policy owner), never from current code, and
    it is the only place the BLOCK category lives.  A file record and the
    receipt that disagree about a path's depth is an inconsistent bundle.
    """

    if not isinstance(path, str) or not path:
        return None
    receipt = _census_receipt(bundle)
    declarations = receipt["declarations"] if receipt is not None else []
    matches = [
        row
        for row in declarations
        if isinstance(row, dict) and isinstance(row.get("prefix"), str) and path.startswith(row["prefix"])
    ]
    if len(matches) > 1:
        raise ContinuityInputError("compiler census-depth declarations overlap for one path")
    declared = matches[0] if matches else None
    recorded = file_record.get("census_depth") if file_record is not None else None
    if declared is None:
        if recorded not in (None, "full"):
            raise ContinuityInputError(
                "compiler file record is censused below full depth without a census-depth declaration"
            )
        return None
    if declared.get("census_depth") != IDENTITY_DEPTH:
        raise ContinuityInputError("compiler census-depth declaration names an unsupported depth")
    if file_record is not None and (
        recorded != declared.get("census_depth")
        or file_record.get("census_depth_reason") != declared.get("reason")
    ):
        raise ContinuityInputError("compiler file record census depth differs from its declaration")
    receipt = receipt or {}
    line_count = file_record.get("line_count") if file_record is not None else None
    return {
        "depth": IDENTITY_DEPTH,
        "reason": declared.get("reason"),
        "block_category": declared.get("block_category"),
        "declaration_prefix": declared.get("prefix"),
        "follow_up_owner": declared.get("follow_up_owner"),
        "policy_owner": receipt.get("policy_owner"),
        "retained_record_groups": list(receipt.get("retained_record_groups") or []),
        "deferred_record_groups": list(receipt.get("deferred_record_groups") or []),
        "line_count": line_count if type(line_count) is int else None,
        "claim": CENSUS_DEPTH_CLAIM,
    }


def _file_record_for(bundle: Any, path: str | None) -> dict[str, Any] | None:
    if not isinstance(path, str) or not path:
        return None
    return next((record for record in bundle.records.get("files", []) if record.get("path") == path), None)


def _with_disclosure(result: dict[str, Any], disclosure: dict[str, Any] | None) -> dict[str, Any]:
    if disclosure is not None:
        result["census_depth"] = disclosure
    return result


def _identity_depth_limits(bundle: Any) -> list[str]:
    receipt = _census_receipt(bundle)
    if receipt is None:
        return []
    return [
        (
            f"{row.get('tracked_files')} files under {row.get('prefix')} are censused at identity depth only "
            f"({row.get('reason')}; release BLOCK {row.get('block_category')}): they contribute file and import "
            "records but no call, symbol or line records, so references from them cannot appear here."
        )
        for row in receipt["declarations"]
        if isinstance(row, dict) and row.get("tracked_files")
    ]


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
    path = record.get("path") or record.get("source_path")
    disclosure = census_depth_disclosure(
        bundle, path, record if group == "files" else _file_record_for(bundle, path)
    )
    return 0, _with_disclosure(
        {**_base(bundle, "id"), "status": "answered", "record_type": group, "record": record}, disclosure
    )


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
    file_record = next((record for group, record in matches if group == "files"), None)
    disclosure = census_depth_disclosure(bundle, path, file_record)
    if line is None:
        summaries = sorted(
            (_summary(group, record) for group, record in matches), key=lambda row: (row["record_type"], str(row["id"]))
        )
        return 0, _with_disclosure(
            {
                **_base(bundle, "path"),
                "status": "answered",
                "query": {"path": path},
                "records": summaries,
            },
            disclosure,
        )
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
        if disclosure is not None:
            line_count = disclosure["line_count"]
            if line_count is not None and line > line_count:
                # The file record keeps the real physical line count, so a line
                # past the end is absent from the source, not merely deferred.
                return 3, _with_disclosure(
                    {
                        **_base(bundle, "path-line"),
                        "status": "abstained",
                        "reason": "line_not_present_in_exact_source",
                        "line_count": line_count,
                        "query": {"path": path, "line": line},
                    },
                    disclosure,
                )
            # Identity depth is deferred coverage, not a blank or absent line.
            return 3, _with_disclosure(
                {
                    **_base(bundle, "path-line"),
                    "status": "abstained",
                    "reason": "census_depth_identity_line_not_projected",
                    "census_depth_reason": disclosure["reason"],
                    "query": {"path": path, "line": line},
                },
                disclosure,
            )
        return 3, {
            **_base(bundle, "path-line"),
            "status": "abstained",
            "reason": "line_not_present_or_blank_in_exact_bundle",
            "query": {"path": path, "line": line},
        }
    return 0, _with_disclosure(
        {
            **_base(bundle, "path-line"),
            "status": "answered",
            "query": {"path": path, "line": line},
            "line_records": line_records,
            "source_lines": source_lines,
        },
        disclosure,
    )


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
    subject_path = record.get("path") or record.get("source_path")
    disclosure = census_depth_disclosure(
        bundle, subject_path, record if group == "files" else _file_record_for(bundle, subject_path)
    )
    outgoing_ids = sorted(_references(record))
    outgoing = [_summary(*by_id[reference]) for reference in outgoing_ids if reference in by_id]
    unresolved = [reference for reference in outgoing_ids if reference not in by_id]
    inbound = sorted(
        (_summary(incoming_group, incoming_record) for incoming_group, incoming_record in incoming.get(identifier, [])),
        key=lambda row: (row["record_type"], str(row["id"])),
    )
    return 0, _with_disclosure(
        {
            **_base(bundle, "impact"),
            "status": "answered",
            "subject": _summary(group, record),
            "incoming_references": inbound,
            "outgoing_references": sorted(outgoing, key=lambda row: (row["record_type"], str(row["id"]))),
            "unresolved_outgoing_reference_ids": unresolved,
            "limits": [
                "This is a one-hop compiler-reference traversal, not runtime blast-radius proof.",
                "Static call and import references remain possible dependencies, not observed execution.",
                *_identity_depth_limits(bundle),
            ],
        },
        disclosure,
    )
