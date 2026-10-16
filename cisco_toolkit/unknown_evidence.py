"""Governed, privacy-safe intake for evidence the assessment could not classify.

``parse_yield`` already records parser exceptions and content-in/zero-entities-out
observations, while ``coverage_matrix`` and ``architecture_coverage`` describe the
bounded evidence surfaces.  Those records are intentionally detailed and can carry
device/file attribution.  This module projects only aggregate, repository-owned
metadata into one deterministic queue.  It never copies a hostname, filename,
payload, exception message, unknown parser token, or unknown axis token.

The queue is evidence for human triage, not a support verdict.  Automatic
classifications are marked ``candidate`` and every emitted event remains
``needs_triage`` until a governed process resolves it as a defect, capability gap,
horizon signal, or deliberate exclusion.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from cisco_toolkit.cmdio import (
    MAY_BE_EMPTY_PARSERS,
    PARSER_CONTRACTS,
    PARSER_RETURN_SHAPE,
)
from cisco_toolkit.design_advisor import _ARCH_COVERAGE_REGISTRY


SCHEMA = "unknown_evidence/1"
EVENT_SCHEMA = "unknown_evidence_event/1"

CLASSIFICATIONS = frozenset({"defect", "capability_gap", "horizon", "out_of_scope"})
DISPOSITIONS = frozenset({"needs_triage", "accepted", "deferred", "rejected", "resolved"})

_OWNER_ROLE = "coverage governance lead"
_CAPABILITY_REFS = (
    "cap.architecture.unknown-signal-intake",
    "cap.ops.collection-completeness",
)
_GAP_REFS = ("gap.unknown-intake",)
_PRIVACY = {
    "mode": "aggregate_only",
    "raw_identifiers_included": False,
    "raw_payload_included": False,
}

_SOURCE_ORDER = ("parse_yield", "coverage_matrix", "architecture_coverage")
_SOURCE_STATES = frozenset({"observed", "observed_empty", "partial", "not_collected", "malformed"})
_COVERAGE_STATES = frozenset(
    {"covered", "not_collected", "partial", "unverified", "unparsed", "not_observed"}
)
_CORE_COVERAGE_AXES = frozenset({"collection", "capture", "parse"})
_COVERAGE_DIMENSIONS = _CORE_COVERAGE_AXES | {"architecture"}

_KIND_META = {
    "parser_exception": (
        "Parser exception on collected content",
        "defect",
        "parse_yield.per_parser",
    ),
    "suspicious_zero_yield": (
        "Collected content produced no parsed entities",
        "capability_gap",
        "parse_yield.per_parser",
    ),
    "unregistered_parser": (
        "Parser activity has no registered return-shape contract",
        "capability_gap",
        "parse_yield.per_parser",
    ),
    "unregistered_architecture_axis": (
        "Architecture coverage contains an unregistered axis",
        "capability_gap",
        "architecture_coverage.classes",
    ),
    "unregistered_coverage_axis": (
        "Coverage projection contains an unregistered axis",
        "capability_gap",
        "coverage_matrix.rows",
    ),
    "unsupported_source_shape": (
        "Unknown-evidence source has an unsupported or contradictory shape",
        "defect",
        "source",
    ),
}


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _known_parsers() -> frozenset[str]:
    """Read the live parser-shape owner; do not maintain a second parser roster."""
    return frozenset(str(name) for name in PARSER_RETURN_SHAPE)


def _commands_by_parser() -> Dict[str, List[str]]:
    """Invert the live SSH parser contract using only repository-owned command literals."""
    result: Dict[str, List[str]] = defaultdict(list)
    for command, parsers in PARSER_CONTRACTS.items():
        for parser in parsers:
            result[str(parser)].append(str(command))
    return {parser: sorted(set(commands)) for parser, commands in result.items()}


def _architecture_axes() -> frozenset[str]:
    """Read the live architecture-coverage owner; never restate its class denominator."""
    return frozenset(str(row[0]) for row in _ARCH_COVERAGE_REGISTRY)


def _stable_id(kind: str, source_section: str, subject: Mapping[str, Any]) -> str:
    # ``subject`` is assembled only from fixed strings and registered code identifiers.
    # Counts stay out of the identity so one signal keeps its stable link as occurrences grow.
    identity = json.dumps(
        {"kind": kind, "source_section": source_section, "subject": subject},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "urn:cisco-toolkit:unknown-evidence:" + sha256(identity).hexdigest()[:20]


def _event(
    kind: str,
    source_section: str,
    subject: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> Dict[str, Any]:
    title, classification, source_path = _KIND_META[kind]
    assert classification in CLASSIFICATIONS
    return {
        "schema": EVENT_SCHEMA,
        "id": _stable_id(kind, source_section, subject),
        "kind": kind,
        "title": title,
        "classification": classification,
        "classification_confidence": "candidate",
        "disposition": "needs_triage",
        "owner_role": _OWNER_ROLE,
        "source": {
            "section": source_section,
            "path": source_path if source_path != "source" else source_section,
        },
        "subject": dict(subject),
        "observations": dict(observations),
        "capability_refs": list(_CAPABILITY_REFS),
        "gap_refs": list(_GAP_REFS),
        "privacy": dict(_PRIVACY),
    }


def _retained_metrics(rows: Sequence[dict], occurrences: int, truncated: bool) -> Dict[str, Any]:
    """Aggregate event detail without retaining device/file/command values."""
    devices = {
        row.get("device")
        for row in rows
        if isinstance(row.get("device"), str)
        and row.get("device")
        and row.get("device") != "[unattributed]"
    }
    line_counts = [
        value
        for value in (row.get("lines_in") for row in rows)
        if _nonnegative_int(value) is not None
    ]
    return {
        "occurrences": occurrences,
        "retained_event_rows": len(rows),
        "affected_devices_lower_bound": len(devices),
        "input_lines_min": min(line_counts) if line_counts else None,
        "input_lines_max": max(line_counts) if line_counts else None,
        "detail_complete": not truncated and len(rows) >= occurrences,
    }


def _source_record(
    section: str,
    state: str,
    records_examined: int,
    *,
    detail_complete: bool,
    note: str,
    **extra: Any,
) -> Dict[str, Any]:
    assert state in _SOURCE_STATES
    result = {
        "section": section,
        "state": state,
        "records_examined": records_examined,
        "detail_complete": bool(detail_complete),
        "note": note,
    }
    result.update(extra)
    return result


def _parse_source(snap: Mapping[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if "parse_yield" not in snap:
        return [], _source_record(
            "parse_yield",
            "not_collected",
            0,
            detail_complete=False,
            note="Parser-yield evidence was not published; no absence-of-unknowns claim is possible.",
        )

    raw = snap.get("parse_yield")
    if not isinstance(raw, dict):
        event = _event(
            "unsupported_source_shape",
            "parse_yield",
            {"section": "parse_yield"},
            {"occurrences": 1, "detail_complete": False},
        )
        return [event], _source_record(
            "parse_yield",
            "malformed",
            0,
            detail_complete=False,
            note="Parser-yield evidence was present in an unsupported shape.",
        )

    issues = 0
    per_parser_raw = raw.get("per_parser")
    event_rows_raw = raw.get("events")
    summary_raw = raw.get("summary")
    if not isinstance(per_parser_raw, dict):
        per_parser_raw = {}
        issues += 1
    if not isinstance(event_rows_raw, list):
        event_rows_raw = []
        issues += 1
    if not isinstance(summary_raw, dict):
        summary_raw = {}
        issues += 1
    truncated = raw.get("events_truncated", False)
    if not isinstance(truncated, bool):
        truncated = True
        issues += 1

    known = _known_parsers()
    commands = _commands_by_parser()
    retained_by_parser: Dict[str, List[dict]] = defaultdict(list)
    unknown_retained_by_name: Dict[str, List[dict]] = defaultdict(list)
    for row in event_rows_raw:
        if not isinstance(row, dict):
            issues += 1
            continue
        parser = row.get("parser")
        if not isinstance(parser, str) or not parser:
            issues += 1
            continue
        if _nonnegative_int(row.get("lines_in")) is None:
            issues += 1
        if not isinstance(row.get("error"), bool):
            issues += 1
            # Preserve only the fact that an opaque, unregistered parser token was
            # present.  A malformed error flag cannot safely be interpreted as either
            # an exception or a zero-yield observation for a registered parser.
            if parser not in known:
                unknown_retained_by_name[parser].append(row)
            continue
        if parser in known:
            retained_by_parser[parser].append(row)
        else:
            # The raw token is used only as an in-memory grouping key; it never enters output or ID.
            unknown_retained_by_name[parser].append(row)

    stats_by_parser: Dict[str, Dict[str, int]] = {}
    unknown_stats_by_name: Dict[str, Dict[str, int]] = {}
    for parser, value in per_parser_raw.items():
        if not isinstance(parser, str) or not parser or not isinstance(value, dict):
            issues += 1
            continue
        parsed: Dict[str, int] = {}
        for field in ("calls", "with_content", "zero_yield", "errors"):
            count = _nonnegative_int(value.get(field))
            if count is None:
                issues += 1
                count = 0
            parsed[field] = count
        if parsed["with_content"] > parsed["calls"]:
            issues += 1
        if parsed["zero_yield"] + parsed["errors"] > parsed["with_content"]:
            issues += 1
        (stats_by_parser if parser in known else unknown_stats_by_name)[parser] = parsed

    events: List[Dict[str, Any]] = []
    for parser in sorted(set(stats_by_parser) | set(retained_by_parser)):
        rows = retained_by_parser.get(parser, [])
        stats = stats_by_parser.get(parser)
        row_errors = sum(1 for row in rows if row.get("error") is True)
        row_zero = sum(1 for row in rows if row.get("error") is not True)
        if stats is None:
            issues += 1
            errors, zero_yield = row_errors, row_zero
        else:
            errors, zero_yield = stats["errors"], stats["zero_yield"]
            if row_errors > errors or row_zero > zero_yield:
                issues += 1
            elif not truncated and (row_errors != errors or row_zero != zero_yield):
                issues += 1

        subject = {
            "parser": parser,
            "registered_show_commands": list(commands.get(parser, [])),
        }
        if errors:
            err_rows = [row for row in rows if row.get("error") is True]
            events.append(
                _event(
                    "parser_exception",
                    "parse_yield",
                    subject,
                    _retained_metrics(err_rows, errors, truncated),
                )
            )
        if zero_yield and parser not in MAY_BE_EMPTY_PARSERS:
            zero_rows = [row for row in rows if row.get("error") is not True]
            events.append(
                _event(
                    "suspicious_zero_yield",
                    "parse_yield",
                    subject,
                    _retained_metrics(zero_rows, zero_yield, truncated),
                )
            )

    # An unregistered parser is itself the signal, even if it happened to return entities.
    # Group all unknown names into one opaque event so neither the token nor a hash/linkable
    # derivative of the token leaves the raw snapshot.
    unknown_names = set(unknown_stats_by_name) | set(unknown_retained_by_name)
    if unknown_names:
        unknown_occurrences = 0
        unknown_rows: List[dict] = []
        for parser in sorted(unknown_names):
            rows = unknown_retained_by_name.get(parser, [])
            unknown_rows.extend(rows)
            stats = unknown_stats_by_name.get(parser)
            calls = stats.get("calls", 0) if stats is not None else 0
            row_errors = sum(1 for row in rows if row.get("error") is True)
            row_zero = sum(1 for row in rows if row.get("error") is False)
            if stats is None:
                issues += 1
            elif row_errors > stats["errors"] or row_zero > stats["zero_yield"]:
                issues += 1
            elif not truncated and (
                row_errors != stats["errors"] or row_zero != stats["zero_yield"]
            ):
                issues += 1
            unknown_occurrences += max(calls, len(rows), 1)
        metrics = _retained_metrics(unknown_rows, unknown_occurrences, truncated)
        metrics["distinct_unregistered_parsers"] = len(unknown_names)
        events.append(
            _event(
                "unregistered_parser",
                "parse_yield",
                {"parser": "[unregistered]", "registered_show_commands": []},
                metrics,
            )
        )

    # Reconcile the report summary to its detailed counters.  A contradiction is an
    # actionable shape/integrity signal, not an excuse to discard the useful events.
    all_stats = {**stats_by_parser, **unknown_stats_by_name}
    expected_summary = {
        "parsers_called": len(all_stats),
        "zero_yield_suspect": sum(
            values["zero_yield"]
            for parser, values in all_stats.items()
            if parser not in MAY_BE_EMPTY_PARSERS
        ),
        "zero_yield_expected": sum(
            values["zero_yield"]
            for parser, values in all_stats.items()
            if parser in MAY_BE_EMPTY_PARSERS
        ),
        "parse_errors": sum(values["errors"] for values in all_stats.values()),
    }
    for field, expected in expected_summary.items():
        published = _nonnegative_int(summary_raw.get(field))
        if published is None or published != expected:
            issues += 1

    if issues:
        events.append(
            _event(
                "unsupported_source_shape",
                "parse_yield",
                {"section": "parse_yield"},
                {"occurrences": issues, "detail_complete": False},
            )
        )

    state = "malformed" if issues else ("observed" if all_stats else "observed_empty")
    return events, _source_record(
        "parse_yield",
        state,
        len(all_stats),
        detail_complete=not truncated and not issues,
        note=(
            "Aggregate parser counters were examined; retained row detail is lower-bound only when capped."
            if all_stats
            else "The parser-yield block was present but no parser activity was observed."
        ),
        events_truncated=bool(truncated),
    )


def _architecture_source(snap: Mapping[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if "architecture_coverage" not in snap:
        return [], _source_record(
            "architecture_coverage",
            "not_collected",
            0,
            detail_complete=False,
            note="Architecture coverage was not published.",
        )
    raw = snap.get("architecture_coverage")
    if not isinstance(raw, dict) or not isinstance(raw.get("classes"), list) or not isinstance(raw.get("summary"), dict):
        return [
            _event(
                "unsupported_source_shape",
                "architecture_coverage",
                {"section": "architecture_coverage"},
                {"occurrences": 1, "detail_complete": False},
            )
        ], _source_record(
            "architecture_coverage",
            "malformed",
            0,
            detail_complete=False,
            note="Architecture coverage was present in an unsupported shape.",
        )

    registered = _architecture_axes()
    seen: set[str] = set()
    unknown_count = duplicate_count = malformed_count = 0
    for row in raw["classes"]:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row.get("key"):
            malformed_count += 1
            continue
        key = row["key"]
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        if key not in registered:
            unknown_count += 1

    events: List[Dict[str, Any]] = []
    if unknown_count:
        events.append(
            _event(
                "unregistered_architecture_axis",
                "architecture_coverage",
                {"axis": "[unregistered]"},
                {"occurrences": unknown_count, "detail_complete": malformed_count == 0},
            )
        )
    issues = malformed_count + duplicate_count
    published_n = _nonnegative_int(raw["summary"].get("n_classes"))
    if published_n is None or published_n != len(raw["classes"]):
        issues += 1
    if issues:
        events.append(
            _event(
                "unsupported_source_shape",
                "architecture_coverage",
                {"section": "architecture_coverage"},
                {"occurrences": issues, "detail_complete": False},
            )
        )

    observed_registered = len(seen & registered)
    missing_registered = len(registered - seen)
    if issues:
        state = "malformed"
    elif missing_registered:
        state = "partial"
    else:
        state = "observed" if raw["classes"] else "observed_empty"
    return events, _source_record(
        "architecture_coverage",
        state,
        len(raw["classes"]),
        detail_complete=not issues and not missing_registered,
        note="Class keys were reconciled to the live architecture-coverage registry; unknown keys remain opaque.",
        registered_expected=len(registered),
        registered_observed=observed_registered,
        registered_missing=missing_registered,
    )


def _coverage_source(snap: Mapping[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if "coverage_matrix" not in snap:
        return [], _source_record(
            "coverage_matrix",
            "not_collected",
            0,
            detail_complete=False,
            note="The composed coverage projection was not published.",
        )
    raw = snap.get("coverage_matrix")
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list) or not isinstance(raw.get("summary"), dict):
        return [
            _event(
                "unsupported_source_shape",
                "coverage_matrix",
                {"section": "coverage_matrix"},
                {"occurrences": 1, "detail_complete": False},
            )
        ], _source_record(
            "coverage_matrix",
            "malformed",
            0,
            detail_complete=False,
            note="The composed coverage projection was present in an unsupported shape.",
        )

    registered_arch = _architecture_axes()
    unregistered = malformed = 0
    observed_dimensions: set[str] = set()
    for row in raw["rows"]:
        if not isinstance(row, dict):
            malformed += 1
            continue
        dimension, axis, state = row.get("dimension"), row.get("axis"), row.get("state")
        if isinstance(dimension, str) and dimension in _COVERAGE_DIMENSIONS:
            observed_dimensions.add(dimension)
        if dimension in _CORE_COVERAGE_AXES:
            if axis != dimension:
                unregistered += 1
        elif dimension == "architecture":
            if not isinstance(axis, str) or axis not in registered_arch:
                unregistered += 1
        else:
            unregistered += 1
        if state not in _COVERAGE_STATES:
            malformed += 1

    events: List[Dict[str, Any]] = []
    if unregistered:
        events.append(
            _event(
                "unregistered_coverage_axis",
                "coverage_matrix",
                {"axis": "[unregistered]"},
                {"occurrences": unregistered, "detail_complete": malformed == 0},
            )
        )
    published_n = _nonnegative_int(raw["summary"].get("n_rows"))
    if published_n is None or published_n != len(raw["rows"]):
        malformed += 1
    if malformed:
        events.append(
            _event(
                "unsupported_source_shape",
                "coverage_matrix",
                {"section": "coverage_matrix"},
                {"occurrences": malformed, "detail_complete": False},
            )
        )

    missing_dimensions = len(_COVERAGE_DIMENSIONS - observed_dimensions)
    if malformed:
        state = "malformed"
    elif missing_dimensions:
        state = "partial"
    else:
        state = "observed" if raw["rows"] else "observed_empty"
    return events, _source_record(
        "coverage_matrix",
        state,
        len(raw["rows"]),
        detail_complete=not malformed and not missing_dimensions,
        note="Coverage rows were checked only for registered dimensions, axes, and verdict states; device values were discarded.",
        dimensions_expected=len(_COVERAGE_DIMENSIONS),
        dimensions_observed=len(observed_dimensions),
        dimensions_missing=missing_dimensions,
    )


def _assemble(events: Iterable[Dict[str, Any]], sources: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    event_rows = sorted(
        events,
        key=lambda row: (
            str(row.get("kind", "")),
            str(_d(row.get("subject")).get("parser", "")),
            str(row.get("id", "")),
        ),
    )
    source_by_name = {row["section"]: row for row in sources}
    source_rows = [source_by_name[name] for name in _SOURCE_ORDER]
    source_complete = all(
        row["state"] == "observed" and row["detail_complete"] for row in source_rows
    )
    unresolved = sum(1 for row in event_rows if row.get("disposition") == "needs_triage")
    if event_rows:
        state = "observed_with_unresolved" if source_complete else "incomplete_with_unresolved"
    else:
        state = "observed_no_unknowns" if source_complete else "incomplete"
    by_kind = dict(sorted(Counter(row["kind"] for row in event_rows).items()))
    by_classification = dict(sorted(Counter(row["classification"] for row in event_rows).items()))
    occurrences_by_kind = {
        kind: sum(
            int(_d(row.get("observations")).get("occurrences") or 0)
            for row in event_rows
            if row.get("kind") == kind
        )
        for kind in sorted(by_kind)
    }
    # ``n_occurrences`` is a signal-observation total; it is not a unique device/incident count.
    n_occurrences = sum(occurrences_by_kind.values())
    return {
        "schema": SCHEMA,
        "event_schema": EVENT_SCHEMA,
        "sources": source_rows,
        "events": event_rows,
        "summary": {
            "state": state,
            "n_events": len(event_rows),
            "n_occurrences": n_occurrences,
            "n_unresolved": unresolved,
            "event_records_by_kind": by_kind,
            "occurrences_by_kind": occurrences_by_kind,
            "event_records_by_classification": by_classification,
            "source_coverage_complete": source_complete,
            "raw_identifiers_included": False,
            "claim_scope": "bounded_observed_sources_only",
            "note": (
                "This aggregate includes only registered parser-yield, coverage-matrix, and architecture-coverage "
                "inputs. 'observed_no_unknowns' means none were observed in that bounded complete input; it is "
                "never a claim of universal protocol, platform, estate, or industry completeness. Events may "
                "share a causal incident and remain candidate classifications until human triage."
            ),
        },
    }


def unavailable_unknown_evidence() -> Dict[str, Any]:
    """Canonical fail-soft shape when the aggregate itself could not be computed."""
    sources = [
        _source_record(
            name,
            "not_collected",
            0,
            detail_complete=False,
            note="Unknown-evidence aggregation was unavailable; source state was not evaluated.",
        )
        for name in _SOURCE_ORDER
    ]
    result = _assemble([], sources)
    result["summary"]["state"] = "unavailable"
    result["summary"]["source_coverage_complete"] = False
    return result


def compute_unknown_evidence(snap: Mapping[str, Any] | Any) -> Dict[str, Any]:
    """Return the deterministic ``UnknownEvidenceEvent`` queue for one snapshot.

    The function is pure and total.  Missing sources remain explicit in ``sources`` and
    keep the summary ``incomplete``; an empty event list becomes
    ``observed_no_unknowns`` only when every declared source was observed completely.
    """
    snapshot: Mapping[str, Any] = snap if isinstance(snap, Mapping) else {}
    events: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    for collect in (_parse_source, _coverage_source, _architecture_source):
        new_events, source = collect(snapshot)
        events.extend(new_events)
        sources.append(source)
    return _assemble(events, sources)


__all__ = [
    "CLASSIFICATIONS",
    "DISPOSITIONS",
    "EVENT_SCHEMA",
    "SCHEMA",
    "compute_unknown_evidence",
    "unavailable_unknown_evidence",
]
