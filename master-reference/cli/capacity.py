"""Measure every master-reference capacity wall on one hosted run (W64-0).

A capacity wall is a hard bound that refuses the build once it is crossed: the
release intake's chunk census ceiling, the per-file compiler JSON bounds, the
projection's expanded and compressed aggregates and its receipts, and the
runner's memory and disk.  Each limit is read on every run from its one code
owner (an AST read of a Python module constant, or a top-level ``const`` of an
ES module); the runner walls read ``/proc/meminfo`` and the file system.  This
module never restates a limit.

For every wall it reports value, limit and utilisation.  It warns at 85 % and
fails at 95 % with a message that names the wall, the value, the limit, the
owning constant and the remedy.  It also emits a per-field byte census of every
compiler record group.  The census is computed after the fact from the
canonical chunks and reconciles exactly with every chunk's byte size, so no
compiler artifact, receipt or digest changes.

The module is observation only.  It reads the compiler output, the projection
and deployment receipts, GNU ``time -v`` reports, ``/proc/meminfo`` and the
file system, and writes one ``capacity.json`` plus a Markdown job summary.  An
absent or malformed measurement input fails closed (exit 2): an unmeasured wall
is never reported as headroom.  The trend baseline is advisory.  An absent
baseline (a fork, the first run, an expired artifact) is reported as "no
baseline", and a malformed one is refused and reported; neither fails the run.

Record: ``docs/w64-capacity-guard-2026-10-10.md``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Sequence

SCHEMA = "atlas-capacity/1"
WARN_AT = Fraction(85, 100)
FAIL_AT = Fraction(95, 100)
HISTORY_LIMIT = 30
# A growth rate fitted over less than six hours of history is noise, not trend.
MINIMUM_TREND_SPAN_DAYS = 0.25
EXIT_OK = 0
EXIT_WALL = 1
EXIT_INPUT = 2
REFERENCE_ROOT = Path(__file__).resolve().parents[1]
# A malformed gzip receipt must not exhaust the runner: expansion stops at this
# multiple of the receipt's own owner limit, which still measures any overrun.
_GZIP_SAFETY_MULTIPLE = 8
_BASELINE_MAX_BYTES = 16 * 1024 * 1024
_LABEL = re.compile(r"[a-z][a-z0-9_]{0,63}")


class CapacityInputError(ValueError):
    """A measurement input is absent or malformed; the wall stays unmeasured."""


@dataclass(frozen=True)
class Owner:
    """One limit's code owner: a module path under ``master-reference/`` and a constant."""

    path: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.path}::{self.name}"


RELEASE_CENSUS = Owner("release/compiler_bundle.py", "_MAX_COMPILER_CHUNK_BYTES")
RELEASE_JSON_BYTES = Owner("release/compiler_bundle.py", "_MAX_COMPILER_JSON_BYTES")
RELEASE_SCAN_VALUES = Owner("release/compiler_bundle.py", "_LOCAL_SCAN_MAX_VALUES")
RELEASE_SCAN_BYTES = Owner("release/compiler_bundle.py", "_LOCAL_SCAN_MAX_TOTAL_BYTES")
PROJECTION_JSON_BYTES = Owner("build/projection/build.mjs", "COMPILER_JSON_MAX_BYTES")
PROJECTION_JSON_VALUES = Owner("build/projection/build.mjs", "COMPILER_JSON_MAX_VALUES")
PROJECTION_JSON_STRING_BYTES = Owner("build/projection/build.mjs", "COMPILER_JSON_MAX_STRING_BYTES")
EXPANDED_PROJECTION = Owner("build/deployment-manifest.mjs", "MAX_EXPANDED_PROJECTION_BYTES")
COMPRESSED_PROJECTION = Owner("build/deployment-manifest.mjs", "MAX_COMPRESSED_PROJECTION_BYTES")
EXPANDED_MODULE = Owner("build/deployment-manifest.mjs", "MAX_EXPANDED_MODULE_BYTES")
COMPRESSED_MODULE = Owner("build/deployment-manifest.mjs", "MAX_COMPRESSED_MODULE_BYTES")
RECEIPT_BYTES = Owner("build/deployment-manifest.mjs", "MAX_JSON_RECEIPT_BYTES")
RECEIPT_VALUES = Owner("build/deployment-manifest.mjs", "MAX_JSON_STRUCTURE_VALUES")
DEPLOYMENT_MEMBER_BYTES = Owner("build/deployment-manifest.mjs", "MAX_DEPLOYMENT_MEMBER_BYTES")
OWNERS = (
    RELEASE_CENSUS,
    RELEASE_JSON_BYTES,
    RELEASE_SCAN_VALUES,
    RELEASE_SCAN_BYTES,
    PROJECTION_JSON_BYTES,
    PROJECTION_JSON_VALUES,
    PROJECTION_JSON_STRING_BYTES,
    EXPANDED_PROJECTION,
    COMPRESSED_PROJECTION,
    EXPANDED_MODULE,
    COMPRESSED_MODULE,
    RECEIPT_BYTES,
    RECEIPT_VALUES,
    DEPLOYMENT_MEMBER_BYTES,
)

# ``release/compiler_bundle.py :: _scan_generated_local_identities`` scans the
# manifest's owner documents plus every record of these groups against
# ``_LOCAL_SCAN_MAX_VALUES`` and ``_LOCAL_SCAN_MAX_TOTAL_BYTES``.  A test pins
# this tuple to that function's source so it cannot drift silently.
RELEASE_SCAN_GROUPS = ("graph_nodes", "graph_edges")
# Receipt locations owned by ``build/deployment-manifest.mjs`` (PROJECTION_DIRECTORY,
# MANIFEST_NAME) and ``build/compress-projection.mjs`` (RECEIPT_NAME,
# PROJECTION_MANIFEST_REPRESENTATION_NAME); a test pins them to those sources.
PROJECTION_DIRECTORY = "client/atlas-projection"
COMPRESSION_RECEIPT = "compression-manifest.json.gz"
PROJECTION_RECEIPT = "projection-manifest.json.gz"
DEPLOYMENT_RECEIPT = "deployment-manifest.json.gz"

_REMEDY_CENSUS = (
    "cut compiler output bytes (W64b record compaction) or lower `cli build` peak memory (W64a streaming "
    "intake), then re-derive the ceiling from a measured peak RSS; never raise it blind "
    "(docs/w63-compiler-census-headroom-2026-10-09.md)"
)
_REMEDY_CHUNK = (
    "lower the group's records per chunk (source_text already uses one record per chunk) or compact its "
    "records (W64b)"
)
_REMEDY_OWNER_JSON = "split or compact the named compiler owner document"
_REMEDY_JSON_VALUES = "lower records per chunk or flatten the records of the named compiler file"
_REMEDY_JSON_STRING = "split the oversized string value of the named compiler file"
_REMEDY_RELEASE_SCAN = (
    "reduce the Graphify metadata and graph records the release intake scans, or re-derive the scan "
    "budget from a measured run"
)
_REMEDY_PROJECTION = (
    "trim projection bytes first (W64b's projection-only part: the source-chunk header lift and a trimmed "
    "compactRecord), then compact compiler records; do not raise the bound blind"
)
_REMEDY_MODULE = "lower the projection's per-module target in build/projection/build.mjs"
_REMEDY_RECEIPT = "reduce the receipt's module or member count, or split the receipt"
_REMEDY_MEMBER = "split the oversized deployment member"
_REMEDY_RSS = (
    "lower the step's retained memory before the census grows further (W64a streaming intake for "
    "`cli build`)"
)
_REMEDY_DISK = "delete intermediate outputs earlier in the job or move them to a larger volume"

_TIME_MAX_RSS = re.compile(r"^[ \t]*Maximum resident set size \(kbytes\):[ \t]*([0-9]+)[ \t]*\r?$", re.MULTILINE)
_TIME_ELAPSED = re.compile(
    r"^[ \t]*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):[ \t]*([0-9:.]+)[ \t]*\r?$", re.MULTILINE
)
_TIME_EXIT = re.compile(r"^[ \t]*Exit status:[ \t]*([0-9]+)[ \t]*\r?$", re.MULTILINE)
_TIME_SIGNAL = re.compile(r"^[ \t]*Command terminated by signal ([0-9]+)[ \t]*\r?$", re.MULTILINE)
_MEMTOTAL = re.compile(r"^MemTotal:[ \t]+([0-9]+)[ \t]+kB[ \t]*\r?$", re.MULTILINE)
_CENSUS_REFUSAL = re.compile(r"census exceeds [^\"]*?scanned_bytes=([0-9]+); limit=([0-9]+)")
_JS_INTEGER_PRODUCT = re.compile(r"[0-9](?:_?[0-9])*(?:[ \t]*\*[ \t]*[0-9](?:_?[0-9])*)*")
_ENCODER = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
_HISTORY_ROW_KEYS = frozenset({"at", "sha", "run_id", "event", "values"})


# --------------------------------------------------------------------------- owners


def read_owner_constant(owner: Owner, reference_root: Path = REFERENCE_ROOT) -> int:
    """Read one limit from its code owner; anything but one integer literal product fails closed."""

    path = reference_root.joinpath(*owner.path.split("/"))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CapacityInputError(f"owner source is unreadable: {owner.path}") from None
    if owner.path.endswith(".py"):
        value = python_owner_constant(text, owner)
    elif owner.path.endswith(".mjs"):
        value = javascript_owner_constant(text, owner)
    else:
        raise CapacityInputError(f"owner source kind is unsupported: {owner.path}")
    if value <= 0:
        raise CapacityInputError(f"owner constant is not a positive integer: {owner.label}")
    return value


def python_owner_constant(text: str, owner: Owner) -> int:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise CapacityInputError(f"owner source does not parse: {owner.path}") from None
    bindings: list[ast.expr | None] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == owner.name for target in node.targets):
                bindings.append(node.value if len(node.targets) == 1 else None)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == owner.name:
                bindings.append(node.value)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == owner.name:
                bindings.append(None)
    if len(bindings) != 1 or bindings[0] is None:
        raise CapacityInputError(f"owner constant must be bound exactly once at module level: {owner.label}")
    return _integer_product(bindings[0], owner)


def _integer_product(node: ast.expr, owner: Owner) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _integer_product(node.left, owner) * _integer_product(node.right, owner)
    raise CapacityInputError(f"owner constant is not a product of integer literals: {owner.label}")


def javascript_owner_constant(text: str, owner: Owner) -> int:
    declaration = re.compile(
        rf"^(?:export[ \t]+)?(?:const|let|var)[ \t]+{re.escape(owner.name)}[ \t]*=[ \t]*([^;\r\n]*?)[ \t]*;?[ \t]*\r?$",
        re.MULTILINE,
    )
    matches = declaration.findall(text)
    if len(matches) != 1:
        raise CapacityInputError(f"owner constant must be declared exactly once at top level: {owner.label}")
    expression = matches[0]
    if _JS_INTEGER_PRODUCT.fullmatch(expression) is None:
        raise CapacityInputError(f"owner constant is not a product of integer literals: {owner.label}")
    product = 1
    for factor in expression.split("*"):
        product *= int(factor.strip().replace("_", ""))
    return product


class OwnerTable:
    """Resolve each owner constant once per run and remember what was read."""

    def __init__(self, reference_root: Path = REFERENCE_ROOT) -> None:
        self._root = reference_root
        self._values: dict[Owner, int] = {}

    def value(self, owner: Owner) -> int:
        if owner not in self._values:
            self._values[owner] = read_owner_constant(owner, self._root)
        return self._values[owner]

    def binding(self, first: Owner, second: Owner) -> tuple[int, str]:
        """The stricter of two owners that enforce the same bound on the same bytes."""

        left = self.value(first)
        right = self.value(second)
        if left == right:
            return left, f"{first.label} = {second.label}"
        if left < right:
            return left, f"{first.label} (binding; {second.label} is {right:,})"
        return right, f"{second.label} (binding; {first.label} is {left:,})"

    def resolved(self) -> dict[str, int]:
        return {owner.label: value for owner, value in sorted(self._values.items(), key=lambda item: item[0].label)}


# --------------------------------------------------------------------------- walls


def classify(value: int, limit: int) -> str:
    """Exact rational thresholds: below 85 % ok, 85 % to below 95 % warn, 95 % and above fail."""

    if type(value) is not int or type(limit) is not int or value < 0 or limit <= 0:
        raise CapacityInputError("a capacity measurement needs a non-negative integer value and a positive limit")
    ratio = Fraction(value, limit)
    if ratio >= FAIL_AT:
        return "fail"
    if ratio >= WARN_AT:
        return "warn"
    return "ok"


def percent_hundredths(value: int, limit: int) -> int:
    """Utilisation in hundredths of a percent, truncated so a display never rounds up across a threshold."""

    return value * 10_000 // limit


def format_percent(hundredths: int) -> str:
    return f"{hundredths // 100}.{hundredths % 100:02d}"


@dataclass
class Wall:
    id: str
    title: str
    unit: str
    owner: str
    remedy: str
    value: int | None = None
    limit: int | None = None
    basis: str = ""
    detail: str = ""
    error: str | None = None

    def measure(self, value: int, limit: int, *, basis: str, detail: str = "", owner: str | None = None) -> None:
        classify(value, limit)
        self.value = value
        self.limit = limit
        self.basis = basis
        self.detail = detail
        self.error = None
        if owner is not None:
            self.owner = owner

    def unmeasured(self, reason: str) -> None:
        self.value = None
        self.limit = None
        self.error = reason

    @property
    def status(self) -> str:
        if self.value is None or self.limit is None:
            return "unmeasured"
        return classify(self.value, self.limit)

    @property
    def hundredths(self) -> int | None:
        if self.value is None or self.limit is None:
            return None
        return percent_hundredths(self.value, self.limit)

    def as_dict(self) -> dict[str, Any]:
        hundredths = self.hundredths
        return {
            "id": self.id,
            "title": self.title,
            "unit": self.unit,
            "value": self.value,
            "limit": self.limit,
            "percent": None if hundredths is None else hundredths / 100,
            "status": self.status,
            "owner": self.owner,
            "basis": self.basis,
            "detail": self.detail,
            "error": self.error,
            "remedy": self.remedy,
        }


def _attempt(walls: Sequence[Wall], measure: Callable[[], None]) -> None:
    """Run one measurement; an input error leaves every wall it feeds unmeasured with the reason."""

    try:
        measure()
    except CapacityInputError as exc:
        for wall in walls:
            if wall.value is None:
                wall.unmeasured(str(exc))


def wall_message(wall: Wall) -> str:
    status = wall.status
    if status == "unmeasured":
        return (
            f"{wall.title} [{wall.id}] was not measured: {wall.error or 'no input'}. Limit owner: {wall.owner}. "
            "The guard fails closed on an unmeasured wall."
        )
    assert wall.value is not None and wall.limit is not None
    threshold = {"ok": "below the 85% warning", "warn": "warn at 85%", "fail": "fail at 95%"}[status]
    return (
        f"{wall.title} [{wall.id}] is at {format_percent(percent_hundredths(wall.value, wall.limit))}% of its "
        f"limit ({threshold}): value={wall.value:,} {wall.unit}; limit={wall.limit:,} {wall.unit}, owned by "
        f"{wall.owner}. Remedy: {wall.remedy}."
    )


def _command_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _command_property(text: str) -> str:
    return _command_data(text).replace(":", "%3A").replace(",", "%2C")


def annotations(walls: Sequence[Wall], input_errors: Sequence[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for wall in walls:
        status = wall.status
        if status == "warn":
            lines.append(f"::warning title={_command_property('Capacity warning ' + wall.id)}::{_command_data(wall_message(wall))}")
        elif status == "fail":
            lines.append(f"::error title={_command_property('Capacity wall ' + wall.id)}::{_command_data(wall_message(wall))}")
        elif status == "unmeasured":
            lines.append(f"::error title={_command_property('Capacity input ' + wall.id)}::{_command_data(wall_message(wall))}")
    for error in input_errors:
        message = f"{error['source']}: {error['error']}. The guard fails closed on a malformed input."
        lines.append(f"::error title={_command_property('Capacity input ' + error['source'])}::{_command_data(message)}")
    return lines


# --------------------------------------------------------------------------- readers


def _read_bytes(path: Path | None, label: str) -> bytes:
    if path is None:
        raise CapacityInputError(f"{label} was not supplied")
    try:
        if not path.is_file():
            raise CapacityInputError(f"{label} is absent")
        return path.read_bytes()
    except OSError:
        raise CapacityInputError(f"{label} is unreadable") from None


def _read_text(path: Path | None, label: str) -> str:
    raw = _read_bytes(path, label)
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise CapacityInputError(f"{label} is not UTF-8") from None


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON number: {token}")


def _json_value(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, RecursionError, ValueError):
        raise CapacityInputError(f"{label} is not valid UTF-8 JSON") from None


def _read_gzip(path: Path | None, label: str, cap: int) -> tuple[int, bytes]:
    raw = _read_bytes(path, label)
    decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
    try:
        expanded = decompressor.decompress(raw, cap + 1)
    except zlib.error:
        raise CapacityInputError(f"{label} is not a valid gzip stream") from None
    if len(expanded) > cap or decompressor.unconsumed_tail:
        raise CapacityInputError(f"{label} expands beyond the guard's safety cap of {cap:,} B")
    if not decompressor.eof or decompressor.unused_data:
        raise CapacityInputError(f"{label} is a truncated or multi-member gzip stream")
    return len(raw), expanded


def _member_path(root: Path, relative: object, label: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
        or ":" in relative
    ):
        raise CapacityInputError(f"{label} path is not a safe relative path")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CapacityInputError(f"{label} path is not a safe relative path")
    return root.joinpath(*parts)


def _receipt_size(receipt: object, label: str) -> tuple[str, int]:
    if not isinstance(receipt, dict):
        raise CapacityInputError(f"{label} receipt is malformed")
    path = receipt.get("path")
    size = receipt.get("bytes")
    if not isinstance(path, str) or type(size) is not int or size < 0:
        raise CapacityInputError(f"{label} receipt is malformed")
    return path, size


def _is_file_receipt(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {"path", "bytes", "sha256"}


def _encoded_size(value: Any) -> int:
    """Byte length of ``value`` in the compiler's canonical JSON (``compiler.model.canonical_json``)."""

    kind = type(value)
    if kind is int:
        return len(int.__repr__(value))
    if value is None:
        return 4
    if kind is bool:
        return 4 if value else 5
    try:
        text = _ENCODER.encode(value)
        return len(text) if text.isascii() else len(text.encode("utf-8", errors="strict"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise CapacityInputError("a compiler value is not canonical JSON") from None


class JsonShape:
    """Count JSON values the way the bounded readers do, and track the longest string token.

    ``build/projection/build.mjs :: parseCanonicalCompilerJson`` and
    ``build/deployment-manifest.mjs :: assertBoundedJsonStructure`` count every
    value (objects, arrays and scalars, never object keys).  The projection
    reader bounds each string token's canonical byte length, quotes and escapes
    included, and object keys are tokens too.  A canonical token is at most six
    bytes per character plus its quotes, so a string that cannot beat the
    current maximum is skipped without encoding it.
    """

    def __init__(self) -> None:
        self.max_string_bytes = 0
        self.max_string_where = ""

    def measure(self, value: Any, where: str) -> int:
        count = 0
        threshold = (self.max_string_bytes - 2) // 6
        stack = [value]
        while stack:
            item = stack.pop()
            count += 1
            kind = type(item)
            if kind is dict:
                for key in item:
                    if len(key) > threshold:
                        threshold = self._observe(key, where)
                stack.extend(item.values())
            elif kind is list:
                stack.extend(item)
            elif kind is str and len(item) > threshold:
                threshold = self._observe(item, where)
        return count

    def _observe(self, text: str, where: str) -> int:
        size = _encoded_size(text)
        if size > self.max_string_bytes:
            self.max_string_bytes = size
            self.max_string_where = where
        return (self.max_string_bytes - 2) // 6


def release_scan_census(value: Any) -> tuple[int, int]:
    """Mirror ``release/compiler_bundle.py :: _scan_generated_local_identities`` counting.

    Every popped item counts as one value, object keys included; every string,
    key or value, adds its strict UTF-8 byte length.
    """

    values = 0
    total = 0
    pending = [value]
    while pending:
        item = pending.pop()
        values += 1
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
            continue
        if isinstance(item, (list, tuple)):
            pending.extend(item)
            continue
        if isinstance(item, str):
            try:
                total += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                raise CapacityInputError("a scanned compiler string is not strict UTF-8") from None
    return values, total


# --------------------------------------------------------------------------- field census


@dataclass
class GroupCensus:
    chunks: int = 0
    records: int = 0
    chunk_bytes: int = 0
    record_bytes: int = 0
    record_structure_bytes: int = 0
    fields: dict[str, list[int]] = field(default_factory=dict)

    def as_dict(self, name: str) -> dict[str, Any]:
        rows = []
        for key, (present, size) in sorted(self.fields.items(), key=lambda item: (-item[1][1], item[0])):
            rows.append(
                {
                    "field": key,
                    "records": present,
                    "bytes": size,
                    "share_of_record_bytes_percent": round(100 * size / self.record_bytes, 2) if self.record_bytes else 0.0,
                    "average_bytes_per_record": round(size / self.records, 1) if self.records else 0.0,
                }
            )
        return {
            "group": name,
            "chunks": self.chunks,
            "records": self.records,
            "chunk_bytes": self.chunk_bytes,
            "record_bytes": self.record_bytes,
            "record_structure_bytes": self.record_structure_bytes,
            "envelope_bytes": self.chunk_bytes - self.record_bytes,
            "average_record_bytes": round(self.record_bytes / self.records, 1) if self.records else 0.0,
            "fields": rows,
        }


def census_chunk(envelope: dict[str, Any], chunk_bytes: int, census: GroupCensus, key_sizes: dict[str, int]) -> None:
    """Attribute every byte of one canonical chunk to a record field, record structure or the envelope.

    A field's bytes are ``"key":value`` in canonical JSON.  A record adds its
    braces and separating commas.  The reconstruction must equal the chunk's
    exact byte size, so the census is exact or the run fails closed.
    """

    records = envelope.get("records")
    if not isinstance(records, list):
        raise CapacityInputError("chunk envelope carries no records list")
    fields = census.fields
    record_total = 0
    structure_total = 0
    for record in records:
        if type(record) is not dict:
            raise CapacityInputError("chunk record is not an object")
        size = 0
        for key, value in record.items():
            key_size = key_sizes.get(key)
            if key_size is None:
                key_size = _encoded_size(key)
                key_sizes[key] = key_size
            field_size = key_size + 1 + _encoded_size(value)
            entry = fields.get(key)
            if entry is None:
                fields[key] = [1, field_size]
            else:
                entry[0] += 1
                entry[1] += field_size
            size += field_size
        structure = 2 + max(len(record) - 1, 0)
        structure_total += structure
        record_total += size + structure
    array_size = 2 + record_total + max(len(records) - 1, 0)
    envelope_size = 3 + max(len(envelope) - 1, 0)
    for key, value in envelope.items():
        key_size = key_sizes.get(key)
        if key_size is None:
            key_size = _encoded_size(key)
            key_sizes[key] = key_size
        envelope_size += key_size + 1 + (array_size if key == "records" else _encoded_size(value))
    if envelope_size != chunk_bytes:
        raise CapacityInputError(
            f"field census does not reconcile with the chunk's bytes: reconstructed={envelope_size:,}; "
            f"actual={chunk_bytes:,}"
        )
    census.chunks += 1
    census.records += len(records)
    census.chunk_bytes += chunk_bytes
    census.record_bytes += record_total
    census.record_structure_bytes += structure_total


# --------------------------------------------------------------------------- collectors


def _read_cli_build_census(stdout_path: Path | None, stderr_path: Path | None) -> dict[str, Any]:
    stdout = _read_text(stdout_path, "cli build stdout") if stdout_path is not None and stdout_path.is_file() else ""
    if stdout.strip():
        document = _last_json_object(stdout, "cli build stdout")
        census = document.get("compiler_chunk_census") if document.get("ok") is True else None
        if not isinstance(census, dict):
            raise CapacityInputError("cli build stdout carries no compiler_chunk_census")
        keys = ("scanned_bytes", "limit_bytes", "chunk_bytes", "identity_depth_source_bytes", "chunk_count")
        if any(type(census.get(key)) is not int or census[key] < 0 for key in keys):
            raise CapacityInputError("cli build compiler_chunk_census is malformed")
        if census["scanned_bytes"] != census["chunk_bytes"] + census["identity_depth_source_bytes"]:
            raise CapacityInputError("cli build compiler_chunk_census does not add up")
        return {
            "scanned_bytes": census["scanned_bytes"],
            "limit_bytes": census["limit_bytes"],
            "basis": "`python -m cli build` success JSON (exact census)",
            "detail": (
                f"{census['chunk_count']:,} chunks, {census['chunk_bytes']:,} B; identity-depth sources "
                f"{census['identity_depth_source_bytes']:,} B; local-identity scan performed: "
                f"{census.get('local_identity_scan_performed')}"
            ),
        }
    stderr = _read_text(stderr_path, "cli build stderr") if stderr_path is not None and stderr_path.is_file() else ""
    refusals = _CENSUS_REFUSAL.findall(stderr)
    if len(refusals) == 1:
        scanned, limit = (int(item) for item in refusals[0])
        return {
            "scanned_bytes": scanned,
            "limit_bytes": limit,
            "basis": "`python -m cli build` census refusal (the scan stops at the crossing: a lower bound)",
            "detail": "the release intake refused the census",
        }
    raise CapacityInputError("cli build reported no census (the step was skipped or failed before the intake)")


def _last_json_object(text: str, label: str) -> dict[str, Any]:
    candidates = [text]
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == "{"]
    if starts:
        candidates.append("".join(lines[starts[-1]:]))
    for candidate in candidates:
        try:
            value = json.loads(candidate, parse_constant=_reject_constant)
        except (RecursionError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    raise CapacityInputError(f"{label} carries no JSON object")


def census_wall(owners: OwnerTable, stdout_path: Path | None, stderr_path: Path | None) -> Wall:
    wall = Wall(
        id="release.census_bytes",
        title="Release intake chunk census",
        unit="B",
        owner=RELEASE_CENSUS.label,
        remedy=_REMEDY_CENSUS,
    )

    def measure() -> None:
        limit = owners.value(RELEASE_CENSUS)
        census = _read_cli_build_census(stdout_path, stderr_path)
        if census["limit_bytes"] != limit:
            raise CapacityInputError(
                f"cli build census limit {census['limit_bytes']:,} differs from {RELEASE_CENSUS.label} = {limit:,}"
            )
        wall.measure(census["scanned_bytes"], limit, basis=census["basis"], detail=census["detail"])

    _attempt([wall], measure)
    return wall


@dataclass
class CompilerScan:
    groups: dict[str, dict[str, Any]]
    owner_documents: dict[str, int]
    max_values: tuple[int, str]
    max_string: tuple[int, str]
    release_scan_values: int
    release_scan_bytes: int
    census: dict[str, GroupCensus]
    census_error: str | None


def scan_compiler_output(root: Path) -> CompilerScan:
    """Read every compiler JSON file once, one at a time, and measure it."""

    manifest_raw = _read_bytes(root / "manifest.json", "compiler manifest.json")
    manifest = _json_value(manifest_raw, "compiler manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("groups"), dict) or not manifest["groups"]:
        raise CapacityInputError("compiler manifest.json carries no record groups")
    shape = JsonShape()
    max_values = (shape.measure(manifest, "manifest.json"), "manifest.json")
    owner_documents = {"manifest.json": len(manifest_raw)}
    release_values = 0
    release_bytes = 0
    for key in sorted(manifest):
        receipt = manifest[key]
        if not _is_file_receipt(receipt):
            continue
        relative, size = _receipt_size(receipt, f"compiler {key}")
        raw = _read_bytes(_member_path(root, relative, f"compiler {key}"), f"compiler {relative}")
        if len(raw) != size:
            raise CapacityInputError(f"compiler {relative} differs from its manifest byte receipt")
        document = _json_value(raw, f"compiler {relative}")
        owner_documents[relative] = len(raw)
        values = shape.measure(document, relative)
        if values > max_values[0]:
            max_values = (values, relative)
        scanned_values, scanned_bytes = release_scan_census(document)
        release_values += scanned_values
        release_bytes += scanned_bytes
    groups: dict[str, dict[str, Any]] = {}
    census: dict[str, GroupCensus] = {}
    census_error: str | None = None
    key_sizes: dict[str, int] = {}
    for name in sorted(manifest["groups"]):
        descriptor = manifest["groups"][name]
        chunks = descriptor.get("chunks") if isinstance(descriptor, dict) else None
        record_count = descriptor.get("record_count") if isinstance(descriptor, dict) else None
        if not isinstance(chunks, list) or type(record_count) is not int or len(chunks) != descriptor.get("chunk_count"):
            raise CapacityInputError(f"compiler group descriptor is malformed: {name}")
        summary = {"chunks": len(chunks), "records": 0, "bytes": 0, "max_chunk_bytes": 0, "max_chunk": ""}
        group_census = census.setdefault(name, GroupCensus())
        for receipt in chunks:
            relative, size = _receipt_size(receipt, f"compiler {name} chunk")
            raw = _read_bytes(_member_path(root, relative, f"compiler {name} chunk"), f"compiler {relative}")
            if len(raw) != size:
                raise CapacityInputError(f"compiler {relative} differs from its manifest byte receipt")
            envelope = _json_value(raw, f"compiler {relative}")
            del raw
            if not isinstance(envelope, dict) or not isinstance(envelope.get("records"), list):
                raise CapacityInputError(f"compiler {relative} is not a record chunk")
            summary["records"] += len(envelope["records"])
            summary["bytes"] += size
            if size > summary["max_chunk_bytes"]:
                summary["max_chunk_bytes"] = size
                summary["max_chunk"] = relative
            values = shape.measure(envelope, relative)
            if values > max_values[0]:
                max_values = (values, relative)
            if name in RELEASE_SCAN_GROUPS:
                for record in envelope["records"]:
                    scanned_values, scanned_bytes = release_scan_census(record)
                    release_values += scanned_values
                    release_bytes += scanned_bytes
            if census_error is None:
                try:
                    census_chunk(envelope, size, group_census, key_sizes)
                except CapacityInputError as exc:
                    census_error = f"{relative}: {exc}"
        if summary["records"] != record_count:
            raise CapacityInputError(f"compiler group {name} chunks hold a different record count than its manifest")
        groups[name] = summary
    return CompilerScan(
        groups=groups,
        owner_documents=owner_documents,
        max_values=max_values,
        max_string=(shape.max_string_bytes, shape.max_string_where),
        release_scan_values=release_values,
        release_scan_bytes=release_bytes,
        census=census,
        census_error=census_error,
    )


def compiler_walls(owners: OwnerTable, root: Path | None) -> tuple[list[Wall], dict[str, Any] | None, str | None]:
    owner_json = Wall(
        id="compiler.owner_json_bytes",
        title="Largest compiler owner document",
        unit="B",
        owner=f"{RELEASE_JSON_BYTES.label} / {PROJECTION_JSON_BYTES.label}",
        remedy=_REMEDY_OWNER_JSON,
    )
    json_values = Wall(
        id="compiler.json_values",
        title="Most JSON values in one compiler file",
        unit="values",
        owner=PROJECTION_JSON_VALUES.label,
        remedy=_REMEDY_JSON_VALUES,
    )
    json_string = Wall(
        id="compiler.json_string_bytes",
        title="Longest compiler JSON string token",
        unit="B",
        owner=PROJECTION_JSON_STRING_BYTES.label,
        remedy=_REMEDY_JSON_STRING,
    )
    scan_values = Wall(
        id="release.graph_scan_values",
        title="Release Graphify local-identity scan values",
        unit="values",
        owner=RELEASE_SCAN_VALUES.label,
        remedy=_REMEDY_RELEASE_SCAN,
    )
    scan_bytes = Wall(
        id="release.graph_scan_bytes",
        title="Release Graphify local-identity scan bytes",
        unit="B",
        owner=RELEASE_SCAN_BYTES.label,
        remedy=_REMEDY_RELEASE_SCAN,
    )
    placeholder = Wall(
        id="chunk_bytes",
        title="Largest compiler chunk per group",
        unit="B",
        owner=f"{RELEASE_JSON_BYTES.label} / {PROJECTION_JSON_BYTES.label}",
        remedy=_REMEDY_CHUNK,
    )
    fixed = [owner_json, json_values, json_string, scan_values, scan_bytes]
    if root is None:
        for wall in [placeholder, *fixed]:
            wall.unmeasured("compiler output was not supplied")
        return [placeholder, *fixed], None, None
    try:
        scan = scan_compiler_output(root)
    except CapacityInputError as exc:
        for wall in [placeholder, *fixed]:
            wall.unmeasured(str(exc))
        return [placeholder, *fixed], None, None
    group_walls: list[Wall] = []
    for name, summary in scan.groups.items():
        wall = Wall(
            id=f"chunk_bytes.{name}",
            title=f"Largest {name} chunk",
            unit="B",
            owner=placeholder.owner,
            remedy=_REMEDY_CHUNK,
        )

        def measure_group(wall: Wall = wall, summary: dict[str, Any] = summary) -> None:
            limit, owner = owners.binding(RELEASE_JSON_BYTES, PROJECTION_JSON_BYTES)
            wall.measure(
                summary["max_chunk_bytes"],
                limit,
                basis="compiler manifest chunk receipts, each checked against the chunk file",
                detail=(
                    f"largest {summary['max_chunk'] or 'none'}; {summary['chunks']:,} chunks, "
                    f"{summary['records']:,} records, {summary['bytes']:,} B in the group"
                ),
                owner=owner,
            )

        _attempt([wall], measure_group)
        group_walls.append(wall)

    def measure_owner_json() -> None:
        limit, owner = owners.binding(RELEASE_JSON_BYTES, PROJECTION_JSON_BYTES)
        name, size = max(scan.owner_documents.items(), key=lambda item: (item[1], item[0]))
        owner_json.measure(size, limit, basis="compiler owner documents", detail=f"largest {name}", owner=owner)

    def measure_values() -> None:
        count, where = scan.max_values
        json_values.measure(
            count,
            owners.value(PROJECTION_JSON_VALUES),
            basis="every compiler JSON file, counted as parseCanonicalCompilerJson counts",
            detail=f"most values in {where}",
        )

    def measure_string() -> None:
        size, where = scan.max_string
        json_string.measure(
            size,
            owners.value(PROJECTION_JSON_STRING_BYTES),
            basis="every compiler JSON string token, keys included, quotes and escapes counted",
            detail=f"longest token in {where or 'none'}",
        )

    def measure_scan_values() -> None:
        scan_values.measure(
            scan.release_scan_values,
            owners.value(RELEASE_SCAN_VALUES),
            basis=f"owner documents plus every {' and '.join(RELEASE_SCAN_GROUPS)} record, keys included",
        )

    def measure_scan_bytes() -> None:
        scan_bytes.measure(
            scan.release_scan_bytes,
            owners.value(RELEASE_SCAN_BYTES),
            basis=f"owner documents plus every {' and '.join(RELEASE_SCAN_GROUPS)} record, keys included",
        )

    for wall, measure in (
        (owner_json, measure_owner_json),
        (json_values, measure_values),
        (json_string, measure_string),
        (scan_values, measure_scan_values),
        (scan_bytes, measure_scan_bytes),
    ):
        _attempt([wall], measure)
    census: dict[str, Any] | None = None
    if scan.census_error is None:
        census = {
            "basis": (
                "computed after the fact from the canonical compiler chunks; each chunk's reconstruction equals its "
                "exact byte size, so every byte is attributed to a field, record structure or the envelope"
            ),
            "groups": [scan.census[name].as_dict(name) for name in sorted(scan.census)],
        }
    return [*group_walls, *fixed], census, scan.census_error


def projection_walls(owners: OwnerTable, dist: Path | None, projection_dir: Path | None) -> list[Wall]:
    expanded = Wall(
        id="projection.expanded_bytes",
        title="Projection expanded bytes",
        unit="B",
        owner=EXPANDED_PROJECTION.label,
        remedy=_REMEDY_PROJECTION,
    )
    compressed = Wall(
        id="projection.compressed_bytes",
        title="Projection compressed bytes",
        unit="B",
        owner=COMPRESSED_PROJECTION.label,
        remedy=_REMEDY_PROJECTION,
    )
    module_expanded = Wall(
        id="projection.module_max_expanded_bytes",
        title="Largest projection module, expanded",
        unit="B",
        owner=EXPANDED_MODULE.label,
        remedy=_REMEDY_MODULE,
    )
    module_compressed = Wall(
        id="projection.module_max_compressed_bytes",
        title="Largest projection module, compressed",
        unit="B",
        owner=COMPRESSED_MODULE.label,
        remedy=_REMEDY_MODULE,
    )
    member = Wall(
        id="deployment.member_max_bytes",
        title="Largest direct deployment member",
        unit="B",
        owner=DEPLOYMENT_MEMBER_BYTES.label,
        remedy=_REMEDY_MEMBER,
    )
    receipts: dict[str, tuple[Wall, Wall, str]] = {}
    for key, relative in (
        ("compression", f"{PROJECTION_DIRECTORY}/{COMPRESSION_RECEIPT}"),
        ("projection", f"{PROJECTION_DIRECTORY}/{PROJECTION_RECEIPT}"),
        ("deployment", DEPLOYMENT_RECEIPT),
    ):
        receipts[key] = (
            Wall(
                id=f"receipt.{key}.bytes",
                title=f"{key.capitalize()} receipt, expanded",
                unit="B",
                owner=RECEIPT_BYTES.label,
                remedy=_REMEDY_RECEIPT,
            ),
            Wall(
                id=f"receipt.{key}.values",
                title=f"{key.capitalize()} receipt JSON values",
                unit="values",
                owner=RECEIPT_VALUES.label,
                remedy=_REMEDY_RECEIPT,
            ),
            relative,
        )
    parsed: dict[str, Any] = {}
    for key, (bytes_wall, values_wall, relative) in receipts.items():

        def measure_receipt(
            key: str = key, bytes_wall: Wall = bytes_wall, values_wall: Wall = values_wall, relative: str = relative
        ) -> None:
            if dist is None:
                raise CapacityInputError("the deployment directory was not supplied")
            limit = owners.value(RECEIPT_BYTES)
            gzip_bytes, expanded_bytes = _read_gzip(
                _member_path(dist, relative, f"{key} receipt"), f"{key} receipt", limit * _GZIP_SAFETY_MULTIPLE
            )
            value = _json_value(expanded_bytes, f"{key} receipt")
            if not isinstance(value, dict):
                raise CapacityInputError(f"{key} receipt is not a JSON object")
            parsed[key] = value
            bytes_wall.measure(
                len(expanded_bytes),
                limit,
                basis=f"dist/{relative}, gunzipped",
                detail=f"{gzip_bytes:,} B as gzip",
            )
            values_wall.measure(
                JsonShape().measure(value, relative),
                owners.value(RECEIPT_VALUES),
                basis=f"dist/{relative}, counted as assertBoundedJsonStructure counts",
            )

        _attempt([bytes_wall, values_wall], measure_receipt)

    def measure_projection() -> None:
        receipt = parsed.get("compression")
        if receipt is None:
            raise CapacityInputError(
                receipts["compression"][0].error or "compression receipt is absent"
            )
        original = receipt.get("originalBytes")
        packed = receipt.get("compressedBytes")
        modules = receipt.get("modules")
        if type(original) is not int or type(packed) is not int or not isinstance(modules, list) or not modules:
            raise CapacityInputError("compression receipt aggregates are malformed")
        sizes: list[tuple[int, int, str]] = []
        for module in modules:
            if (
                not isinstance(module, dict)
                or type(module.get("originalBytes")) is not int
                or type(module.get("compressedBytes")) is not int
                or not isinstance(module.get("path"), str)
            ):
                raise CapacityInputError("compression receipt module is malformed")
            sizes.append((module["originalBytes"], module["compressedBytes"], module["path"]))
        if sum(item[0] for item in sizes) != original or sum(item[1] for item in sizes) != packed:
            raise CapacityInputError("compression receipt aggregates differ from its module sums")
        detail = f"{len(sizes):,} modules"
        expanded.measure(original, owners.value(EXPANDED_PROJECTION), basis="compression receipt", detail=detail)
        compressed.measure(packed, owners.value(COMPRESSED_PROJECTION), basis="compression receipt", detail=detail)
        largest = max(sizes, key=lambda item: (item[0], item[2]))
        module_expanded.measure(
            largest[0], owners.value(EXPANDED_MODULE), basis="compression receipt", detail=f"largest {largest[2]}"
        )
        largest = max(sizes, key=lambda item: (item[1], item[2]))
        module_compressed.measure(
            largest[1], owners.value(COMPRESSED_MODULE), basis="compression receipt", detail=f"largest {largest[2]}"
        )

    _attempt([expanded, compressed, module_expanded, module_compressed], measure_projection)

    def measure_projection_tree() -> None:
        # Without a compression receipt (the Node build failed before its
        # postbuild), the expanded aggregate is still measurable from the
        # projection builder's own output tree.
        if projection_dir is None or not projection_dir.is_dir():
            raise CapacityInputError(expanded.error or "projection tree is absent")
        total = 0
        count = 0
        for path in sorted(projection_dir.rglob("*.mjs")):
            if path.is_symlink() or not path.is_file():
                raise CapacityInputError("projection tree holds a non-regular module")
            total += path.stat().st_size
            count += 1
        if count == 0:
            raise CapacityInputError("projection tree holds no modules")
        expanded.measure(
            total,
            owners.value(EXPANDED_PROJECTION),
            basis="build.mjs output tree (the compression receipt is absent)",
            detail=f"{count:,} modules",
        )

    if expanded.value is None:
        _attempt([expanded], measure_projection_tree)

    def measure_member() -> None:
        receipt = parsed.get("deployment")
        if receipt is None:
            raise CapacityInputError(receipts["deployment"][0].error or "deployment receipt is absent")
        members = receipt.get("members")
        if not isinstance(members, list) or not members:
            raise CapacityInputError("deployment receipt members are malformed")
        largest = (-1, "")
        for item in members:
            if not isinstance(item, dict) or type(item.get("bytes")) is not int or not isinstance(item.get("path"), str):
                raise CapacityInputError("deployment receipt member is malformed")
            largest = max(largest, (item["bytes"], item["path"]))
        member.measure(
            largest[0],
            owners.value(DEPLOYMENT_MEMBER_BYTES),
            basis="deployment receipt",
            detail=f"largest {largest[1]}; {len(members):,} direct members",
        )

    _attempt([member], measure_member)
    receipt_walls = [wall for bytes_wall, values_wall, _ in receipts.values() for wall in (bytes_wall, values_wall)]
    return [expanded, compressed, module_expanded, module_compressed, member, *receipt_walls]


def parse_gnu_time(text: str, label: str) -> dict[str, Any]:
    rss = _TIME_MAX_RSS.findall(text)
    if len(rss) != 1:
        raise CapacityInputError(f"{label} GNU time report must carry exactly one maximum-RSS line")
    elapsed = _TIME_ELAPSED.findall(text)
    exits = _TIME_EXIT.findall(text)
    signals = _TIME_SIGNAL.findall(text)
    return {
        "max_rss_kib": int(rss[0]),
        "elapsed": elapsed[0] if len(elapsed) == 1 else None,
        "exit_status": int(exits[0]) if len(exits) == 1 else None,
        "signal": int(signals[0]) if len(signals) == 1 else None,
    }


def parse_memtotal(text: str) -> int:
    matches = _MEMTOTAL.findall(text)
    if len(matches) != 1 or int(matches[0]) <= 0:
        raise CapacityInputError("/proc/meminfo must carry exactly one positive MemTotal line")
    return int(matches[0])


def rss_walls(reports: Sequence[tuple[str, Path]], meminfo: Path | None) -> list[Wall]:
    walls: list[Wall] = []
    memory: int | None = None
    memory_error = ""
    try:
        memory = parse_memtotal(_read_text(meminfo, "/proc/meminfo"))
    except CapacityInputError as exc:
        memory_error = str(exc)
    for label, path in reports:
        wall = Wall(
            id=f"peak_rss.{label}",
            title=f"Peak RSS of {label}",
            unit="KiB",
            owner="runner MemTotal (/proc/meminfo)",
            remedy=_REMEDY_RSS,
        )

        def measure(wall: Wall = wall, label: str = label, path: Path = path) -> None:
            report = parse_gnu_time(_read_text(path, f"{label} time report"), label)
            if memory is None:
                raise CapacityInputError(memory_error)
            ending = f"exit status {report['exit_status']}"
            if report["signal"] is not None:
                ending = f"terminated by signal {report['signal']}"
            wall.measure(
                report["max_rss_kib"],
                memory,
                basis="GNU time -v maximum resident set size",
                detail=f"wall time {report['elapsed'] or 'unreported'}; {ending}",
            )

        _attempt([wall], measure)
        walls.append(wall)
    return walls


def _device(path: Path) -> int:
    return path.stat().st_dev


def disk_walls(
    disks: Sequence[tuple[str, Path]],
    usage: Callable[[Path], Any] = shutil.disk_usage,
    device: Callable[[Path], int] = _device,
) -> list[Wall]:
    walls: list[Wall] = []
    by_device: dict[int, Wall] = {}
    for label, path in disks:
        wall = Wall(
            id=f"disk.{label}",
            title=f"Disk used where {label} lives",
            unit="B",
            owner="runner file system capacity (statvfs)",
            remedy=_REMEDY_DISK,
        )
        try:
            identity = device(path)
        except OSError:
            wall.unmeasured(f"{label} path is unavailable")
            walls.append(wall)
            continue
        if identity in by_device:
            shared = by_device[identity]
            shared.detail += f"; also holds {label}"
            continue

        def measure(wall: Wall = wall, label: str = label, path: Path = path) -> None:
            try:
                total, used, free = usage(path)
            except (OSError, TypeError, ValueError):
                raise CapacityInputError(f"{label} file system usage is unreadable") from None
            if type(used) is not int or type(free) is not int or used < 0 or free < 0 or used + free <= 0:
                raise CapacityInputError(f"{label} file system usage is malformed")
            wall.measure(
                used,
                used + free,
                basis="statvfs at guard time (end of job); limit = used + available to unprivileged writers",
                detail=f"{free:,} B available; {total:,} B raw size; holds {label}",
            )

        _attempt([wall], measure)
        by_device[identity] = wall
        walls.append(wall)
    return walls


# --------------------------------------------------------------------------- trend


def _parse_moment(text: object, label: str) -> datetime:
    if not isinstance(text, str):
        raise CapacityInputError(f"{label} is not an ISO-8601 time")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise CapacityInputError(f"{label} is not an ISO-8601 time") from None
    if moment.tzinfo is None:
        raise CapacityInputError(f"{label} carries no time zone")
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_history(document: object) -> list[dict[str, Any]]:
    """Accept a baseline's history only when every row is well formed; otherwise refuse all of it."""

    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise CapacityInputError(f"baseline schema is not {SCHEMA}")
    history = document.get("history")
    if not isinstance(history, list) or not history:
        raise CapacityInputError("baseline carries no history rows")
    if len(history) > HISTORY_LIMIT:
        raise CapacityInputError(f"baseline carries more than {HISTORY_LIMIT} history rows")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(history):
        label = f"baseline history row {index}"
        if not isinstance(row, dict) or set(row) != _HISTORY_ROW_KEYS:
            raise CapacityInputError(f"{label} has an unexpected shape")
        _parse_moment(row["at"], f"{label} time")
        if not all(isinstance(row[key], str) for key in ("sha", "run_id", "event")):
            raise CapacityInputError(f"{label} identity is malformed")
        values = row["values"]
        if not isinstance(values, dict):
            raise CapacityInputError(f"{label} values are malformed")
        for wall_id, measurement in values.items():
            if (
                not isinstance(wall_id, str)
                or not isinstance(measurement, dict)
                or set(measurement) != {"value", "limit"}
                or type(measurement["value"]) is not int
                or type(measurement["limit"]) is not int
                or measurement["value"] < 0
                or measurement["limit"] <= 0
            ):
                raise CapacityInputError(f"{label} measurement {wall_id!r} is malformed")
        rows.append(row)
    rows.sort(key=lambda item: _parse_moment(item["at"], "baseline time"))
    return rows


def load_baseline(path: Path | None) -> tuple[list[dict[str, Any]], str, str]:
    """Return (rows, state, note).  Never raises: the trend is advisory."""

    if path is None or not path.is_file():
        return [], "none", "no baseline (no readable main capacity artifact: a fork, the first run or an expired artifact)"
    try:
        raw = path.read_bytes()
        if len(raw) > _BASELINE_MAX_BYTES:
            raise CapacityInputError("baseline is larger than the guard reads")
        rows = validate_history(_json_value(raw, "baseline"))
    except (OSError, CapacityInputError) as exc:
        return [], "refused", f"baseline refused and not used ({exc})"
    latest = rows[-1]
    return rows, "loaded", f"main run {latest['run_id']} ({latest['sha'][:12]}) at {latest['at']}"


def history_row(walls: Sequence[Wall], moment: datetime, run: dict[str, str]) -> dict[str, Any]:
    values = {
        wall.id: {"value": wall.value, "limit": wall.limit}
        for wall in walls
        if wall.value is not None and wall.limit is not None
    }
    return {"at": _iso(moment), "sha": run["sha"], "run_id": run["run_id"], "event": run["event"], "values": values}


def merge_history(baseline_rows: Sequence[dict[str, Any]], current: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in baseline_rows if row["run_id"] != current["run_id"]]
    rows.append(current)
    rows.sort(key=lambda item: _parse_moment(item["at"], "history time"))
    return rows[-HISTORY_LIMIT:]


def growth_per_day(points: Sequence[tuple[datetime, int]]) -> float | None:
    """Least-squares growth per day, or None without two points spanning the minimum trend span."""

    if len(points) < 2:
        return None
    origin = min(moment for moment, _ in points)
    xs = [(moment - origin).total_seconds() / 86_400 for moment, _ in points]
    if max(xs) - min(xs) < MINIMUM_TREND_SPAN_DAYS:
        return None
    ys = [float(value) for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


def days_until(value: int, limit: int, ratio: Fraction, slope: float | None) -> float | None:
    """Days until ``value`` reaches ``ratio`` of ``limit`` at ``slope``; 0.0 once reached; None if not approaching."""

    target = Fraction(limit) * ratio
    if Fraction(value) >= target:
        return 0.0
    if slope is None or slope <= 0:
        return None
    return float(target - value) / slope


def wall_trend(wall: Wall, history: Sequence[dict[str, Any]], baseline_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    trend: dict[str, Any] = {
        "baseline_value": None,
        "delta": None,
        "growth_per_day": None,
        "days_to_warn": None,
        "days_to_limit": None,
        "points": 0,
    }
    if wall.value is None or wall.limit is None:
        return trend
    if baseline_rows:
        previous = baseline_rows[-1]["values"].get(wall.id)
        if previous is not None:
            trend["baseline_value"] = previous["value"]
            trend["delta"] = wall.value - previous["value"]
    points = [
        (_parse_moment(row["at"], "history time"), row["values"][wall.id]["value"])
        for row in history
        if wall.id in row["values"]
    ]
    trend["points"] = len(points)
    slope = growth_per_day(points)
    trend["growth_per_day"] = None if slope is None else round(slope, 3)
    trend["days_to_warn"] = days_until(wall.value, wall.limit, WARN_AT, slope)
    trend["days_to_limit"] = days_until(wall.value, wall.limit, Fraction(1), slope)
    return trend


# --------------------------------------------------------------------------- report


@dataclass
class Report:
    generated_at: str
    run: dict[str, str]
    walls: list[Wall]
    input_errors: list[dict[str, str]]
    field_census: dict[str, Any] | None
    owner_constants: dict[str, int]
    baseline_state: str
    baseline_note: str
    history: list[dict[str, Any]]
    trends: dict[str, dict[str, Any]]

    @property
    def exit_code(self) -> int:
        statuses = {wall.status for wall in self.walls}
        if "fail" in statuses:
            return EXIT_WALL
        if "unmeasured" in statuses or self.input_errors:
            return EXIT_INPUT
        return EXIT_OK

    @property
    def result(self) -> str:
        statuses = {wall.status for wall in self.walls}
        if "fail" in statuses:
            return "FAIL"
        if "unmeasured" in statuses or self.input_errors:
            return "FAIL (unmeasured input)"
        if "warn" in statuses:
            return "WARN"
        return "OK"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "generated_at": self.generated_at,
            "run": self.run,
            "thresholds": {"warn_percent": 85, "fail_percent": 95},
            "result": self.result,
            "exit_code": self.exit_code,
            "walls": [
                {**wall.as_dict(), "trend": self.trends.get(wall.id)} for wall in sorted(self.walls, key=lambda w: w.id)
            ],
            "input_errors": self.input_errors,
            "owner_constants": self.owner_constants,
            "field_census": self.field_census,
            "trend_baseline": {"state": self.baseline_state, "note": self.baseline_note},
            "history": self.history,
        }


def build_report(
    *,
    reference_root: Path,
    compiler_output: Path | None,
    cli_build_stdout: Path | None,
    cli_build_stderr: Path | None,
    dist: Path | None,
    projection_dir: Path | None,
    rss: Sequence[tuple[str, Path]],
    meminfo: Path | None,
    disks: Sequence[tuple[str, Path]],
    baseline: Path | None,
    run: dict[str, str],
    now: datetime,
) -> Report:
    owners = OwnerTable(reference_root)
    walls: list[Wall] = [census_wall(owners, cli_build_stdout, cli_build_stderr)]
    chunk_walls, census, census_error = compiler_walls(owners, compiler_output)
    walls.extend(chunk_walls)
    walls.extend(projection_walls(owners, dist, projection_dir))
    walls.extend(rss_walls(rss, meminfo))
    walls.extend(disk_walls(disks))
    input_errors = [] if census_error is None else [{"source": "field census", "error": census_error}]
    baseline_rows, state, note = load_baseline(baseline)
    history = merge_history(baseline_rows, history_row(walls, now, run))
    trends = {wall.id: wall_trend(wall, history, baseline_rows) for wall in walls}
    return Report(
        generated_at=_iso(now),
        run=run,
        walls=walls,
        input_errors=input_errors,
        field_census=census,
        owner_constants=owners.resolved(),
        baseline_state=state,
        baseline_note=note,
        history=history,
        trends=trends,
    )


def _human(value: int, unit: str) -> str:
    if unit == "values":
        return f"{value:,}"
    size = value * 1024 if unit == "KiB" else value
    for suffix, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if abs(size) >= scale:
            return f"{value:,} {unit} ({size / scale:.2f} {suffix})"
    return f"{value:,} {unit}"


def _days(days: float | None) -> str:
    if days is None:
        return "–"
    if days == 0:
        return "reached"
    return f"{days:.1f}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


_STATUS_ORDER = {"fail": 0, "unmeasured": 1, "warn": 2, "ok": 3}
_STATUS_LABEL = {"fail": "**FAIL**", "unmeasured": "**UNMEASURED**", "warn": "**WARN**", "ok": "ok"}


def render_summary(report: Report) -> str:
    counts = Counter(wall.status for wall in report.walls)
    lines = [
        "## Master-reference capacity walls (W64-0)",
        "",
        (
            f"**Result: {report.result}.** {counts['fail']} at or above 95 %, {counts['warn']} from 85 % to below "
            f"95 %, {counts['ok']} below 85 %, {counts['unmeasured']} unmeasured (an unmeasured wall fails closed)."
        ),
        "",
        f"Trend baseline: {report.baseline_note}. History rows kept: {len(report.history)} of {HISTORY_LIMIT}.",
        "",
        "| Wall | Value | Limit | Use | Status | Δ since main | Days to 85 % | Days to 100 % |",
        "|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    ordered = sorted(
        report.walls,
        key=lambda wall: (_STATUS_ORDER[wall.status], -(wall.hundredths or 0), wall.id),
    )
    for wall in ordered:
        trend = report.trends.get(wall.id) or {}
        delta = trend.get("delta")
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(f"{wall.title} (`{wall.id}`)"),
                    "–" if wall.value is None else _human(wall.value, wall.unit),
                    "–" if wall.limit is None else _human(wall.limit, wall.unit),
                    "–" if wall.hundredths is None else f"{format_percent(wall.hundredths)} %",
                    _STATUS_LABEL[wall.status],
                    "–" if delta is None else f"{delta:+,} {wall.unit}",
                    _days(trend.get("days_to_warn")),
                    _days(trend.get("days_to_limit")),
                ]
            )
            + " |"
        )
    for error in report.input_errors:
        lines.extend(["", f"**Input error** ({_cell(error['source'])}): {_cell(error['error'])}"])
    lines.extend(
        [
            "",
            "<details><summary>Owners, bases and remedies</summary>",
            "",
            "| Wall | Limit owner | Basis | Detail | Remedy |",
            "|---|---|---|---|---|",
        ]
    )
    for wall in ordered:
        detail = wall.detail if wall.error is None else f"not measured: {wall.error}"
        lines.append(
            "| "
            + " | ".join(_cell(item) for item in (f"`{wall.id}`", wall.owner, wall.basis or "–", detail or "–", wall.remedy))
            + " |"
        )
    lines.extend(["", "</details>"])
    if report.field_census is not None:
        groups = sorted(report.field_census["groups"], key=lambda item: (-item["chunk_bytes"], item["group"]))
        for group in groups[:4]:
            lines.extend(
                [
                    "",
                    (
                        f"<details><summary>Per-field byte census: {group['group']} ({group['records']:,} records, "
                        f"{group['chunk_bytes']:,} B, {group['average_record_bytes']:,} B per record)</summary>"
                    ),
                    "",
                    "| Field | Records | Bytes | Share of record bytes | Average B per record |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for row in group["fields"]:
                lines.append(
                    f"| `{_cell(row['field'])}` | {row['records']:,} | {row['bytes']:,} | "
                    f"{row['share_of_record_bytes_percent']} % | {row['average_bytes_per_record']:,} |"
                )
            lines.append(
                f"| _record structure_ | {group['records']:,} | {group['record_structure_bytes']:,} | | |"
            )
            lines.append(f"| _chunk envelopes_ | | {group['envelope_bytes']:,} | | |")
            lines.extend(["", "</details>"])
        lines.extend(["", "The complete per-field census of every group is in `capacity.json`."])
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- command line


def _labelled_path(text: str) -> tuple[str, Path]:
    label, separator, path = text.partition("=")
    if not separator or _LABEL.fullmatch(label) is None or not path:
        raise argparse.ArgumentTypeError("expected LABEL=PATH with a lower-case label")
    return label, Path(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.capacity",
        description="Measure every master-reference capacity wall; warn at 85 %, fail at 95 %.",
    )
    parser.add_argument("--compiler-output", type=Path)
    parser.add_argument("--cli-build-stdout", type=Path)
    parser.add_argument("--cli-build-stderr", type=Path)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--projection-dir", type=Path)
    parser.add_argument("--rss", type=_labelled_path, action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument("--disk", type=_labelled_path, action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--reference-root", type=Path, default=REFERENCE_ROOT)
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--now", help="ISO-8601 time of this run (default: now)")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        now = _parse_moment(args.now, "--now") if args.now else datetime.now(timezone.utc)
    except CapacityInputError as exc:
        print(f"capacity guard: {exc}", file=sys.stderr)
        return EXIT_INPUT
    report = build_report(
        reference_root=args.reference_root,
        compiler_output=args.compiler_output,
        cli_build_stdout=args.cli_build_stdout,
        cli_build_stderr=args.cli_build_stderr,
        dist=args.dist,
        projection_dir=args.projection_dir,
        rss=args.rss,
        meminfo=args.meminfo,
        disks=args.disk,
        baseline=args.baseline,
        run={"sha": args.sha, "run_id": args.run_id, "ref": args.ref, "event": args.event},
        now=now,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.as_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = render_summary(report)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(summary)
    sys.stdout.write(summary)
    for line in annotations(report.walls, report.input_errors):
        sys.stdout.write(line + "\n")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
