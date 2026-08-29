#!/usr/bin/env python3
"""Bounded, non-echoing integrity audit for Graphify's generated report.

``graphify-out/graph.json`` is the repository's structural owner and compiler
input.  ``GRAPH_REPORT.md`` is an external-tool derivative.  The guarded
Graphifyy 0.9.51 producer corrects an upstream summary formula that otherwise
counts structural-only communities as displayed.  This verifier prevents that
defect from recurring and binds saved community labels to the producer's
membership-signature sidecar.

The compatibility predicate below deliberately mirrors Graphifyy 0.9.51
``graphify.analyze._is_file_node`` behavior.  It is local code,
not a runtime import from mutable site-packages.  A producer upgrade must
reconcile this contract explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "graph-report-audit/1"
PRODUCER_COMPATIBILITY = "graphifyy/0.9.51"

MAX_GRAPH_BYTES = 64 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_LABELS_BYTES = 4 * 1024 * 1024
MAX_LABEL_SIGNATURE_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_VALUES = 2_000_000
MAX_JSON_STRING_CHARS = 8 * 1024 * 1024
MAX_JSON_NUMBER_BYTES = 128
MAX_NODES = 1_000_000
MAX_LINKS = 4_000_000
MAX_IDENTIFIER_CHARS = 4096
MAX_REPORT_LINES = 2_000_000
MAX_COMMUNITY_ID = (1 << 53) - 1

KNOWN_EXTERNAL_REPORT_RESIDUALS = frozenset()

_SUMMARY_RE = re.compile(
    r"^- ([0-9]+) nodes · ([0-9]+) edges · ([0-9]+) communities"
    r"(?: \(([0-9]+) shown, ([0-9]+) thin omitted\))?$"
)
_COMMUNITIES_RE = re.compile(r"^## Communities \(([0-9]+) total, ([0-9]+) thin omitted\)$")
_COMMUNITY_HEADING_RE = re.compile(r'^### Community ([0-9]+) - "([^\r\n]*)"$')
_THIN_RE = re.compile(
    r"^- \*\*([0-9]+) thin communities \(<([0-9]+) nodes\) omitted from report\*\* "
    r"— run `graphify query` to explore isolated nodes\.$"
)
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
_SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_RAW_HTML_HEADING_RE = re.compile(r"<\s*/?\s*h[1-6]\b", re.IGNORECASE)
_RAW_HTML_BLOCK_RE = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|pre|script|search|section|style|summary|table|tbody|td|textarea|tfoot|th|thead|title|tr|track|ul)(?:[ \t/>]|$)",
    re.IGNORECASE,
)
_RAW_HTML_TAG_START_RE = re.compile(r"^ {0,3}</?[A-Za-z]")
_CONTAINER_START_RE = re.compile(r"^ {0,3}(?:>|(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)")
_NESTED_ATX_RE = re.compile(r"#{1,6}[ \t]+")
_EXACT_H2_HEADINGS = frozenset(
    {
        "## Corpus Check",
        "## Summary",
        "## Graph Freshness",
        "## Community Hubs (Navigation)",
        "## God Nodes (most connected - your core abstractions)",
        "## Surprising Connections (you probably didn't know these)",
        "## Import Cycles",
        "## Hyperedges (group relationships)",
        "## Ambiguous Edges - Review These",
        "## Knowledge Gaps",
        "## Work-memory lessons",
        "## Suggested Questions",
    }
)
_H2_ORDER = {
    heading: index
    for index, heading in enumerate(
        (
            "## Corpus Check",
            "## Summary",
            "## Graph Freshness",
            "## Community Hubs (Navigation)",
            "## God Nodes (most connected - your core abstractions)",
            "## Surprising Connections (you probably didn't know these)",
            "## Import Cycles",
            "## Hyperedges (group relationships)",
            "## Communities",
            "## Ambiguous Edges - Review These",
            "## Knowledge Gaps",
            "## Work-memory lessons",
            "## Suggested Questions",
        )
    )
}
_TITLE_RE = re.compile(r"^# Graph Report - .+  \([0-9]{4}-[0-9]{2}-[0-9]{2}\)$")


class _AuditFailure(Exception):
    """An internal fixed-code refusal; its text is safe to serialize."""


@dataclass(frozen=True)
class GraphPartition:
    total_ids: frozenset[int]
    shown_ids: frozenset[int]
    thin_ids: frozenset[int]
    structural_only_ids: frozenset[int]
    community_order: tuple[int, ...]
    membership_signatures: dict[int, str]
    has_code: bool
    node_count: int
    link_count: int


@dataclass(frozen=True)
class AuditResult:
    status: str
    error_codes: tuple[str, ...]
    counts: dict[str, int]

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "producer_compatibility": PRODUCER_COMPATIBILITY,
            "status": self.status,
            "error_codes": list(self.error_codes),
            "counts": dict(sorted(self.counts.items())),
        }


def _fail(code: str) -> None:
    raise _AuditFailure(code)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
    )


def _read_stable_group(specs: tuple[tuple[Path, int], ...]) -> tuple[bytes, ...]:
    """Read one stable snapshot of all inputs, refusing mixed-generation pairs."""
    handles = []
    try:
        before = []
        for path, maximum in specs:
            initial = path.lstat()
            if not stat.S_ISREG(initial.st_mode) or initial.st_size > maximum:
                _fail("graph_report_input_invalid")
            handle = path.open("rb")
            handles.append(handle)
            opened_stat = os.fstat(handle.fileno())
            if not _same_file(initial, opened_stat):
                _fail("graph_report_input_unstable")
            before.append(initial)
        payloads = tuple(handle.read(maximum + 1) for handle, (_path, maximum) in zip(handles, specs, strict=True))
        if any(len(payload) > maximum for payload, (_path, maximum) in zip(payloads, specs, strict=True)):
            _fail("graph_report_input_invalid")
        # A second read through the still-open handles catches same-inode rewrites
        # even when an actor restores size and timestamps.
        for handle, payload, (_path, maximum) in zip(handles, payloads, specs, strict=True):
            handle.seek(0)
            digest = hashlib.sha256()
            reread_bytes = 0
            while reread_bytes <= maximum and (chunk := handle.read(min(1024 * 1024, maximum + 1 - reread_bytes))):
                digest.update(chunk)
                reread_bytes += len(chunk)
            if (
                reread_bytes > maximum
                or reread_bytes != len(payload)
                or digest.digest() != hashlib.sha256(payload).digest()
            ):
                _fail("graph_report_input_unstable")
        after_handle = [os.fstat(handle.fileno()) for handle in handles]
        after_path = [path.lstat() for path, _maximum in specs]
    except _AuditFailure:
        raise
    except (OSError, ValueError):
        _fail("graph_report_input_invalid")
    finally:
        for handle in handles:
            try:
                handle.close()
            except OSError:
                pass
    if any(
        not _same_file(initial, final_handle) or not _same_file(initial, final_path)
        for initial, final_handle, final_path in zip(before, after_handle, after_path, strict=True)
    ):
        _fail("graph_report_input_unstable")
    return payloads


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("graph_report_graph_invalid")
        result[key] = value
    return result


def _preflight_json_bytes(payload: bytes, *, failure_code: str) -> None:
    """Bound decoder amplification before ``json.loads`` materializes objects.

    Object keys are deliberately counted as lexical values. This validates
    enough token grammar to prove that the decoder cannot create more values,
    deeper containers, longer string tokens, or larger numeric tokens than the
    preflight observed. Full grammar and duplicate-key checks remain with the
    standard decoder.
    """

    stack: list[int] = []
    values = 0
    index = 0
    length = len(payload)
    whitespace = b" \t\r\n"
    delimiters = b" \t\r\n,]}:"
    simple_escapes = b'"\\/bfnrt'
    hexadecimal = b"0123456789abcdefABCDEF"

    def count_value() -> None:
        nonlocal values
        values += 1
        if values > MAX_JSON_VALUES or len(stack) + 1 > MAX_JSON_DEPTH:
            _fail(failure_code)

    while index < length:
        byte = payload[index]
        if byte in whitespace or byte in b",:":
            index += 1
            continue
        if byte in (ord("{"), ord("[")):
            count_value()
            stack.append(byte)
            index += 1
            continue
        if byte in (ord("}"), ord("]")):
            if (
                not stack
                or (byte == ord("}") and stack[-1] != ord("{"))
                or (byte == ord("]") and stack[-1] != ord("["))
            ):
                _fail(failure_code)
            stack.pop()
            index += 1
            continue
        if byte == ord('"'):
            count_value()
            token_start = index
            index += 1
            while index < length:
                byte = payload[index]
                if byte == ord('"'):
                    index += 1
                    break
                if byte < 0x20:
                    _fail(failure_code)
                if byte == ord("\\"):
                    index += 1
                    if index >= length:
                        _fail(failure_code)
                    escape = payload[index]
                    if escape == ord("u"):
                        if index + 4 >= length or any(
                            digit not in hexadecimal for digit in payload[index + 1 : index + 5]
                        ):
                            _fail(failure_code)
                        index += 5
                    elif escape in simple_escapes:
                        index += 1
                    else:
                        _fail(failure_code)
                else:
                    index += 1
                if index - token_start - 1 > MAX_JSON_STRING_CHARS:
                    _fail(failure_code)
            else:
                _fail(failure_code)
            if index - token_start - 2 > MAX_JSON_STRING_CHARS:
                _fail(failure_code)
            continue
        if byte in b"-0123456789":
            count_value()
            token_start = index
            if payload[index] == ord("-"):
                index += 1
                if index >= length:
                    _fail(failure_code)
            if payload[index] == ord("0"):
                index += 1
                if index < length and payload[index] in b"0123456789":
                    _fail(failure_code)
            elif payload[index] in b"123456789":
                index += 1
                while index < length and payload[index] in b"0123456789":
                    index += 1
            else:
                _fail(failure_code)
            if index < length and payload[index] == ord("."):
                index += 1
                if index >= length or payload[index] not in b"0123456789":
                    _fail(failure_code)
                while index < length and payload[index] in b"0123456789":
                    index += 1
            if index < length and payload[index] in b"eE":
                index += 1
                if index < length and payload[index] in b"+-":
                    index += 1
                if index >= length or payload[index] not in b"0123456789":
                    _fail(failure_code)
                while index < length and payload[index] in b"0123456789":
                    index += 1
            if index - token_start > MAX_JSON_NUMBER_BYTES:
                _fail(failure_code)
            if index < length and payload[index] not in delimiters:
                _fail(failure_code)
            continue
        matched_literal = False
        for literal in (b"true", b"false", b"null"):
            if payload.startswith(literal, index):
                count_value()
                index += len(literal)
                if index < length and payload[index] not in delimiters:
                    _fail(failure_code)
                matched_literal = True
                break
        if matched_literal:
            continue
        _fail(failure_code)
    if stack or values == 0:
        _fail(failure_code)


def _validate_json_bounds(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    seen = 0
    while stack:
        item, depth = stack.pop()
        seen += 1
        if seen > MAX_JSON_VALUES or depth > MAX_JSON_DEPTH:
            _fail("graph_report_graph_invalid")
        if isinstance(item, dict):
            if len(item) > MAX_JSON_VALUES - seen - len(stack):
                _fail("graph_report_graph_invalid")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > MAX_JSON_STRING_CHARS:
                    _fail("graph_report_graph_invalid")
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            if len(item) > MAX_JSON_VALUES - seen - len(stack):
                _fail("graph_report_graph_invalid")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > MAX_JSON_STRING_CHARS:
                _fail("graph_report_graph_invalid")
        elif isinstance(item, bool) or item is None:
            continue
        elif isinstance(item, int):
            if abs(item) > MAX_COMMUNITY_ID:
                _fail("graph_report_graph_invalid")
        elif isinstance(item, float):
            if not math.isfinite(item):
                _fail("graph_report_graph_invalid")
        else:
            _fail("graph_report_graph_invalid")


def _parse_graph(payload: bytes) -> dict[str, Any]:
    try:
        _preflight_json_bytes(payload, failure_code="graph_report_graph_invalid")
        text = payload.decode("utf-8", "strict")
        graph = json.loads(
            text,
            object_pairs_hook=_object_no_duplicates,
            parse_constant=lambda _value: _fail("graph_report_graph_invalid"),
        )
    except _AuditFailure:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, MemoryError, OverflowError):
        _fail("graph_report_graph_invalid")
    _validate_json_bounds(graph)
    if not isinstance(graph, dict):
        _fail("graph_report_graph_invalid")
    return graph


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_CHARS:
        _fail("graph_report_graph_invalid")
    return value


def _community_id(value: Any) -> int:
    if type(value) is not int or value < 0 or value > MAX_COMMUNITY_ID:
        _fail("graph_report_graph_invalid")
    return value


def _is_producer_file_node_label(label: str, source_file: str) -> bool:
    """Mirror Graphifyy 0.9.51's basename-or-qualified-suffix predicate."""
    normalized_source = source_file.replace("\\", "/")
    if label == normalized_source.rsplit("/", 1)[-1]:
        return True
    return "/" in label and (
        normalized_source == label or normalized_source.endswith("/" + label)
    )


def _is_file_node(attrs: dict[str, Any], degree: int) -> bool:
    """Mirror graphifyy 0.9.51 ``analyze._is_file_node`` exactly."""
    label = attrs.get("label", "")
    if not isinstance(label, str):
        _fail("graph_report_graph_invalid")
    if not label:
        return False
    source_file = attrs.get("source_file", "")
    if not isinstance(source_file, str):
        _fail("graph_report_graph_invalid")
    if source_file and _is_producer_file_node_label(label, source_file):
        return True
    if label.startswith(".") and label.endswith("()"):
        return True
    return label.endswith("()") and degree <= 1


def partition_graph(graph: dict[str, Any], *, min_community_size: int = 3) -> GraphPartition:
    """Validate the simple graph and derive the producer's report partition."""
    if type(min_community_size) is not int or not 2 <= min_community_size <= 1000:
        _fail("graph_report_graph_invalid")
    if graph.get("directed") is not False or graph.get("multigraph") is not False:
        _fail("graph_report_graph_invalid")
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        _fail("graph_report_graph_invalid")
    if len(nodes) > MAX_NODES or len(links) > MAX_LINKS:
        _fail("graph_report_graph_invalid")

    attrs_by_id: dict[str, dict[str, Any]] = {}
    community_by_id: dict[str, int] = {}
    degree: dict[str, int] = {}
    community_order: list[int] = []
    seen_communities: set[int] = set()
    members_by_community: dict[int, list[str]] = {}
    has_code = False
    for node in nodes:
        if not isinstance(node, dict):
            _fail("graph_report_graph_invalid")
        node_id = _identifier(node.get("id"))
        if node_id in attrs_by_id:
            _fail("graph_report_graph_invalid")
        community = _community_id(node.get("community"))
        attrs_by_id[node_id] = node
        community_by_id[node_id] = community
        degree[node_id] = 0
        members_by_community.setdefault(community, []).append(node_id)
        has_code = has_code or node.get("file_type") == "code"
        if community not in seen_communities:
            seen_communities.add(community)
            community_order.append(community)

    edge_keys: set[tuple[str, str]] = set()
    for link in links:
        if not isinstance(link, dict):
            _fail("graph_report_graph_invalid")
        source = _identifier(link.get("source"))
        target = _identifier(link.get("target"))
        if source not in attrs_by_id or target not in attrs_by_id:
            _fail("graph_report_graph_invalid")
        key = (source, target) if source <= target else (target, source)
        if key in edge_keys:
            _fail("graph_report_graph_invalid")
        edge_keys.add(key)
        has_code = has_code or link.get("relation") in ("imports", "imports_from")
        if source == target:
            degree[source] += 2
        else:
            degree[source] += 1
            degree[target] += 1

    real_counts = {community: 0 for community in community_order}
    for node_id, attrs in attrs_by_id.items():
        if not _is_file_node(attrs, degree[node_id]):
            real_counts[community_by_id[node_id]] += 1
    shown = frozenset(community for community, count in real_counts.items() if count >= min_community_size)
    thin = frozenset(community for community, count in real_counts.items() if 0 < count < min_community_size)
    structural = frozenset(community for community, count in real_counts.items() if count == 0)
    total = frozenset(real_counts)
    if total != shown | thin | structural or (shown & thin) or (shown & structural) or (thin & structural):
        _fail("graph_report_graph_invalid")
    membership_signatures: dict[int, str] = {}
    for community, members in members_by_community.items():
        digest = hashlib.sha256()
        for node_id in sorted(members):
            digest.update(node_id.encode("utf-8", "replace"))
            digest.update(b"\x00")
        membership_signatures[community] = digest.hexdigest()[:16]
    return GraphPartition(
        total_ids=total,
        shown_ids=shown,
        thin_ids=thin,
        structural_only_ids=structural,
        community_order=tuple(community_order),
        membership_signatures=membership_signatures,
        has_code=has_code,
        node_count=len(nodes),
        link_count=len(links),
    )


def _parse_count(value: str) -> int:
    if not isinstance(value, str) or not value or not value.isascii() or not value.isdecimal():
        _fail("graph_report_format_invalid")
    try:
        parsed = int(value)
    except ValueError:
        _fail("graph_report_format_invalid")
    if parsed < 0 or parsed > MAX_COMMUNITY_ID or value != str(parsed):
        _fail("graph_report_format_invalid")
    return parsed


def _unique_heading(lines: list[str], heading: str) -> int:
    positions = [index for index, line in enumerate(lines) if line == heading]
    if len(positions) != 1:
        _fail("graph_report_format_invalid")
    return positions[0]


def _section(lines: list[str], start: int) -> list[str]:
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start + 1 : end]


def _parse_labels(payload: bytes, expected_ids: frozenset[int]) -> dict[int, str]:
    try:
        _preflight_json_bytes(payload, failure_code="graph_report_labels_invalid")
        text = payload.decode("utf-8", "strict")

        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    _fail("graph_report_labels_invalid")
                value[key] = item
            return value

        raw = json.loads(text, object_pairs_hook=no_duplicates)
    except _AuditFailure:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, MemoryError, OverflowError):
        _fail("graph_report_labels_invalid")
    if not isinstance(raw, dict) or len(raw) != len(expected_ids):
        _fail("graph_report_labels_invalid")
    labels: dict[int, str] = {}
    for key, label in raw.items():
        if not isinstance(key, str) or not key or len(key) > 16 or not key.isascii() or not key.isdecimal():
            _fail("graph_report_labels_invalid")
        try:
            community = int(key)
        except ValueError:
            _fail("graph_report_labels_invalid")
        if key != str(community) or community not in expected_ids or community in labels:
            _fail("graph_report_labels_invalid")
        labels[community] = label
    _validate_labels_mapping(labels, expected_ids)
    return labels


def _validate_labels_mapping(labels: Any, expected_ids: frozenset[int]) -> None:
    if not isinstance(labels, dict) or frozenset(labels) != expected_ids:
        _fail("graph_report_labels_invalid")
    for community, label in labels.items():
        if (
            type(community) is not int
            or community < 0
            or community > MAX_COMMUNITY_ID
            or not isinstance(label, str)
            or not label
            or len(label) > MAX_IDENTIFIER_CHARS
            or any(ord(char) < 32 for char in label)
        ):
            _fail("graph_report_labels_invalid")
        try:
            label.encode("utf-8", "strict")
        except UnicodeEncodeError:
            _fail("graph_report_labels_invalid")


def _parse_membership_signatures(
    payload: bytes,
    expected_ids: frozenset[int],
) -> dict[int, str]:
    failure_code = "graph_report_label_membership_signature_invalid"
    try:
        _preflight_json_bytes(payload, failure_code=failure_code)
        text = payload.decode("utf-8", "strict")

        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    _fail(failure_code)
                value[key] = item
            return value

        raw = json.loads(text, object_pairs_hook=no_duplicates)
    except _AuditFailure:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, MemoryError, OverflowError):
        _fail(failure_code)
    if not isinstance(raw, dict) or len(raw) != len(expected_ids):
        _fail(failure_code)
    signatures: dict[int, str] = {}
    for key, signature in raw.items():
        if not isinstance(key, str) or not key or len(key) > 16 or not key.isascii() or not key.isdecimal():
            _fail(failure_code)
        try:
            community = int(key)
        except ValueError:
            _fail(failure_code)
        if key != str(community) or community not in expected_ids or community in signatures:
            _fail(failure_code)
        signatures[community] = signature
    _validate_membership_signatures_mapping(signatures, expected_ids)
    return signatures


def _validate_membership_signatures_mapping(signatures: Any, expected_ids: frozenset[int]) -> None:
    failure_code = "graph_report_label_membership_signature_invalid"
    if not isinstance(signatures, dict) or frozenset(signatures) != expected_ids:
        _fail(failure_code)
    for community, signature in signatures.items():
        if (
            type(community) is not int
            or community < 0
            or community > MAX_COMMUNITY_ID
            or not isinstance(signature, str)
            or re.fullmatch(r"[0-9a-f]{16}", signature) is None
        ):
            _fail(failure_code)


def _parse_report(
    report_text: str,
    partition: GraphPartition,
    labels: dict[int, str],
    *,
    min_community_size: int,
) -> AuditResult:
    if (
        "\x00" in report_text
        or "\r" in report_text.replace("\r\n", "")
        or any(
            separator in report_text
            for separator in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
        )
    ):
        _fail("graph_report_format_invalid")
    normalized_report = report_text.replace("\r\n", "\n")
    if normalized_report.count("\n") + 1 > MAX_REPORT_LINES:
        _fail("graph_report_format_invalid")
    lines = normalized_report.split("\n")
    if _RAW_HTML_HEADING_RE.search(report_text):
        _fail("graph_report_format_invalid")
    for line in lines:
        # Source-derived prose can legitimately contain a stray closing token;
        # only an opener can hide subsequent owned Markdown structure.
        if "<!--" in line:
            _fail("graph_report_format_invalid")
    if any(
        re.match(r"^ {0,3}(?:`{3,}|~{3,})", line)
        or _RAW_HTML_BLOCK_RE.match(line)
        or _RAW_HTML_TAG_START_RE.match(line)
        or re.match(r"^ {0,3}(?:<\?|<![A-Z]|<!\[CDATA\[)", line)
        for line in lines
    ):
        _fail("graph_report_format_invalid")
    if any(_CONTAINER_START_RE.match(line) and _NESTED_ATX_RE.search(line) for line in lines):
        _fail("graph_report_format_invalid")

    # Graphify 0.9.51 emits a closed ATX-heading vocabulary. Reject every other
    # rendered heading instead of trying to interpret arbitrary inline Markdown.
    h1_rows: list[tuple[int, str]] = []
    h2_rows: list[tuple[int, str]] = []
    for row, line in enumerate(lines):
        match = _ATX_HEADING_RE.fullmatch(line)
        if match is None:
            continue
        exact_owned = (
            (match.group(1) == "#" and line.startswith("# Graph Report - "))
            or line in _EXACT_H2_HEADINGS
            or _COMMUNITIES_RE.fullmatch(line) is not None
            or _COMMUNITY_HEADING_RE.fullmatch(line) is not None
        )
        if not exact_owned:
            _fail("graph_report_format_invalid")
        if match.group(1) == "#":
            h1_rows.append((row, line))
        elif match.group(1) == "##":
            h2_rows.append((row, line))
    if any(_SETEXT_RE.fullmatch(line) for line in lines):
        _fail("graph_report_format_invalid")
    if len(h1_rows) != 1 or h1_rows[0][0] != 0 or _TITLE_RE.fullmatch(h1_rows[0][1]) is None:
        _fail("graph_report_format_invalid")
    normalized_h2: list[str] = []
    for _row, heading in h2_rows:
        normalized_h2.append("## Communities" if _COMMUNITIES_RE.fullmatch(heading) else heading)
    if len(normalized_h2) != len(set(normalized_h2)):
        _fail("graph_report_format_invalid")
    try:
        h2_ordinals = [_H2_ORDER[heading] for heading in normalized_h2]
    except KeyError:
        _fail("graph_report_format_invalid")
    if h2_ordinals != sorted(h2_ordinals):
        _fail("graph_report_format_invalid")
    required_h2 = {
        "## Corpus Check",
        "## Summary",
        "## God Nodes (most connected - your core abstractions)",
        "## Surprising Connections (you probably didn't know these)",
        "## Communities",
    }
    normalized_h2_set = set(normalized_h2)
    if partition.has_code:
        required_h2.add("## Import Cycles")
    if (
        not required_h2 <= normalized_h2_set
        or ("## Import Cycles" in normalized_h2_set) != partition.has_code
    ):
        _fail("graph_report_format_invalid")

    if any(line.startswith("## Summary") and line != "## Summary" for line in lines):
        _fail("graph_report_format_invalid")
    summary_start = _unique_heading(lines, "## Summary")
    nav_heading = "## Community Hubs (Navigation)"
    if any(line.startswith(nav_heading) and line != nav_heading for line in lines):
        _fail("graph_report_format_invalid")
    nav_positions = [index for index, line in enumerate(lines) if line == nav_heading]
    # The labels artifact is emitted from the producer's community mapping and
    # preserves that insertion order.  Node order in graph.json is independent.
    report_order = tuple(labels)
    expected_nav_ids = tuple(community for community in report_order if community not in partition.structural_only_ids)
    if expected_nav_ids:
        if len(nav_positions) != 1:
            _fail("graph_report_format_invalid")
        nav_start = nav_positions[0]
    else:
        if nav_positions:
            _fail("graph_report_format_invalid")
        nav_start = None
    community_headers = [
        (index, _COMMUNITIES_RE.fullmatch(line))
        for index, line in enumerate(lines)
        if line.startswith("## Communities")
    ]
    if len(community_headers) != 1 or community_headers[0][1] is None:
        _fail("graph_report_format_invalid")
    communities_start, communities_match = community_headers[0]
    assert communities_match is not None
    if nav_start is not None:
        if not summary_start < nav_start < communities_start:
            _fail("graph_report_format_invalid")
    elif not summary_start < communities_start:
        _fail("graph_report_format_invalid")

    summary_section = _section(lines, summary_start)
    summary_candidates = [line for line in lines if " nodes " in line and " edges " in line and " communities" in line]
    if (
        len(summary_candidates) != 1
        or summary_candidates[0] not in summary_section
        or (summary := _SUMMARY_RE.fullmatch(summary_candidates[0])) is None
    ):
        _fail("graph_report_format_invalid")
    if partition.thin_ids:
        if summary.group(4) is None or summary.group(5) is None:
            _fail("graph_report_format_invalid")
    elif summary.group(4) is not None or summary.group(5) is not None:
        _fail("graph_report_format_invalid")

    errors: set[str] = set()
    if (
        _parse_count(summary.group(1)) != partition.node_count
        or _parse_count(summary.group(2)) != partition.link_count
        or _parse_count(summary.group(3)) != len(partition.total_ids)
    ):
        errors.add("graph_report_summary_count_mismatch")
    if partition.thin_ids:
        reported_shown = _parse_count(summary.group(4))
        reported_thin = _parse_count(summary.group(5))
        if reported_thin != len(partition.thin_ids):
            errors.add("graph_report_summary_partition_corrupt")
        if reported_shown != len(partition.shown_ids):
            known_external_formula = len(partition.total_ids) - len(partition.thin_ids)
            if partition.structural_only_ids and reported_shown == known_external_formula:
                errors.add("graph_report_summary_partition_mismatch")
            else:
                errors.add("graph_report_summary_partition_corrupt")

    if _parse_count(communities_match.group(1)) != len(partition.total_ids) or _parse_count(
        communities_match.group(2)
    ) != len(partition.thin_ids):
        errors.add("graph_report_communities_header_mismatch")

    community_lines = _section(lines, communities_start)
    all_section_candidates = [line for line in lines if line.startswith("### Community")]
    section_candidates = [line for line in community_lines if line.startswith("### Community")]
    if all_section_candidates != section_candidates:
        _fail("graph_report_format_invalid")
    section_rows: list[tuple[int, str]] = []
    for line in community_lines:
        if line.startswith("### "):
            match = _COMMUNITY_HEADING_RE.fullmatch(line)
            if match is None:
                _fail("graph_report_format_invalid")
            section_rows.append((_parse_count(match.group(1)), match.group(2)))
    expected_section_rows = [
        (community, labels[community]) for community in report_order if community in partition.shown_ids
    ]
    if section_rows != expected_section_rows:
        errors.add("graph_report_community_section_content_mismatch")

    # Graphifyy 0.9.51 emits this reconciliation under ``## Knowledge Gaps``,
    # not inside the Communities section.  Require exactly one owned statement
    # anywhere rather than accidentally accepting a section-local lookalike.
    thin_candidates = [line for line in lines if "thin communities" in line]
    thin_matches = [match for line in thin_candidates if (match := _THIN_RE.fullmatch(line))]
    if partition.thin_ids:
        if len(thin_candidates) != 1 or len(thin_matches) != 1:
            _fail("graph_report_format_invalid")
        if (
            _parse_count(thin_matches[0].group(1)) != len(partition.thin_ids)
            or _parse_count(thin_matches[0].group(2)) != min_community_size
        ):
            errors.add("graph_report_thin_omission_mismatch")
    elif thin_candidates:
        _fail("graph_report_format_invalid")

    nav_lines = _section(lines, nav_start) if nav_start is not None else []
    nav_lines = [line for line in nav_lines if line.strip()]
    expected_nav_lines = [f"- {labels[community]}" for community in expected_nav_ids]
    if nav_lines != expected_nav_lines:
        errors.add("graph_report_navigation_content_corrupt")

    counts = {
        "communities_total": len(partition.total_ids),
        "communities_shown": len(partition.shown_ids),
        "communities_thin": len(partition.thin_ids),
        "communities_structural_only": len(partition.structural_only_ids),
        "community_sections": len(section_rows),
        "navigation_entries": len(nav_lines),
        "graph_nodes": partition.node_count,
        "graph_links": partition.link_count,
    }
    return AuditResult(
        status="pass" if not errors else "block",
        error_codes=tuple(sorted(errors)),
        counts=counts,
    )


def audit_graph_report_data(
    graph: dict[str, Any],
    report_text: str,
    labels: dict[int, str],
    *,
    membership_signatures: dict[int, str] | None = None,
    min_community_size: int = 3,
) -> AuditResult:
    """Audit already-decoded inputs.  Intended for tests and trusted callers."""
    try:
        _validate_json_bounds(graph)
        partition = partition_graph(graph, min_community_size=min_community_size)
        _validate_labels_mapping(labels, partition.total_ids)
        if membership_signatures is None:
            _fail("graph_report_label_membership_signature_missing")
        _validate_membership_signatures_mapping(membership_signatures, partition.total_ids)
        if membership_signatures != partition.membership_signatures:
            _fail("graph_report_label_membership_signature_mismatch")
        return _parse_report(
            report_text,
            partition,
            labels,
            min_community_size=min_community_size,
        )
    except _AuditFailure as exc:
        return AuditResult(status="block", error_codes=(str(exc),), counts={})


def audit_graph_report(
    graph_path: str | Path,
    report_path: str | Path,
    *,
    labels_path: str | Path | None = None,
    labels_signature_path: str | Path | None = None,
    min_community_size: int = 3,
) -> AuditResult:
    """Read and audit one stable graph/report/labels/signature generation."""
    try:
        graph_path = Path(graph_path)
        report_path = Path(report_path)
        labels_path = Path(labels_path) if labels_path is not None else graph_path.with_name(".graphify_labels.json")
        labels_signature_path = (
            Path(labels_signature_path)
            if labels_signature_path is not None
            else Path(str(labels_path) + ".sig")
        )
        if not all(path.exists() for path in (graph_path, report_path, labels_path)):
            _fail("graph_report_input_invalid")
        if not labels_signature_path.exists():
            _fail("graph_report_label_membership_signature_missing")
        graph_payload, report_payload, labels_payload, labels_signature_payload = _read_stable_group(
            (
                (graph_path, MAX_GRAPH_BYTES),
                (report_path, MAX_REPORT_BYTES),
                (labels_path, MAX_LABELS_BYTES),
                (labels_signature_path, MAX_LABEL_SIGNATURE_BYTES),
            )
        )
        graph = _parse_graph(graph_payload)
        partition = partition_graph(graph, min_community_size=min_community_size)
        labels = _parse_labels(labels_payload, partition.total_ids)
        membership_signatures = _parse_membership_signatures(
            labels_signature_payload,
            partition.total_ids,
        )
        try:
            report_text = report_payload.decode("utf-8", "strict")
        except UnicodeDecodeError:
            _fail("graph_report_format_invalid")
        return audit_graph_report_data(
            graph,
            report_text,
            labels,
            membership_signatures=membership_signatures,
            min_community_size=min_community_size,
        )
    except _AuditFailure as exc:
        return AuditResult(status="block", error_codes=(str(exc),), counts={})
    except (OSError, TypeError, ValueError, MemoryError, RecursionError):
        return AuditResult(status="block", error_codes=("graph_report_input_invalid",), counts={})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Graphify graph/report integrity")
    parser.add_argument("graph_json")
    parser.add_argument("graph_report")
    parser.add_argument("--labels")
    parser.add_argument("--labels-signature")
    parser.add_argument("--min-community-size", type=int, default=3)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = audit_graph_report(
        args.graph_json,
        args.graph_report,
        labels_path=args.labels,
        labels_signature_path=args.labels_signature,
        min_community_size=args.min_community_size,
    )
    print(json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")))
    if result.passed:
        return 0
    if result.error_codes and result.error_codes[0] in {
        "graph_report_input_invalid",
        "graph_report_input_unstable",
        "graph_report_graph_invalid",
        "graph_report_labels_invalid",
        "graph_report_label_membership_signature_missing",
        "graph_report_label_membership_signature_invalid",
        "graph_report_label_membership_signature_mismatch",
        "graph_report_format_invalid",
    }:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
