"""Lazy, receipt-validated access to an exact compiler corpus for ``enhance``.

The release reader deliberately materializes every retained group because a
release must reproduce the complete family.  Enhancement traversal has a
different contract: validate only the chunks it scans and retain only the
bounded seed closure.  This module keeps those concerns separate without
weakening exact-source custody.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .model import ContinuityInputError, canonical_json, digest_object, safe_relative, sha256_bytes


COMPILER_SCHEMA_VERSION = "1.1.0"
MAX_VALIDATED_RECEIPT_READS = 512
MAX_VALIDATED_RECEIPT_BYTES = 1024 * 1024 * 1024
MAX_VALIDATED_CHUNK_CACHE_BYTES = 512 * 1024 * 1024
CACHEABLE_ENHANCEMENT_GROUPS = frozenset(
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
REQUIRED_INVARIANTS = (
    "every_safe_line_structurally_mapped",
    "every_gui_surface_has_standardized_evidence_honest_dossier",
    "every_safe_parsed_source_has_one_structural_root",
)
REQUIRED_GROUPS = frozenset(
    {
        "files",
        "lines",
        "source_text",
        "structural_entities",
        "symbols",
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


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise ContinuityInputError(f"duplicate JSON key in compiler corpus: {key}")
        result[key] = value
    return result


def _canonical_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ContinuityInputError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuityInputError(f"compiler {label} is invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityInputError(f"compiler {label} is not an object")
    if raw != canonical_json(value):
        raise ContinuityInputError(f"compiler {label} is not canonical JSON")
    return value


def _object_id(value: object, label: str, lengths: set[int]) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in lengths
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContinuityInputError(f"compiler {label} is invalid")
    return value


def _streaming_id_digest_start() -> hashlib._Hash:  # type: ignore[name-defined]
    digest = hashlib.sha256()
    digest.update(b"[")
    return digest


def _streaming_id_digest_add(digest: Any, identifier: str, first: bool) -> None:
    if not first:
        digest.update(b",")
    digest.update(json.dumps(identifier, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _streaming_id_digest_finish(digest: Any) -> str:
    digest.update(b"]\n")
    return digest.hexdigest()


def _validate_gate_contract(manifest: dict[str, Any], completeness: dict[str, Any]) -> None:
    if completeness.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ContinuityInputError(
            f"unsupported compiler completeness schema: {completeness.get('schema_version')!r}"
        )
    if completeness.get("hard_failure") is not False or completeness.get("fatal_errors"):
        raise ContinuityInputError("compiler completeness ledger contains a hard failure")
    invariants = completeness.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        raise ContinuityInputError("compiler structural invariants are absent")
    by_name: dict[str, dict[str, Any]] = {}
    for item in invariants:
        if not isinstance(item, dict):
            raise ContinuityInputError("compiler completeness invariant is not an object")
        name = item.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise ContinuityInputError("compiler completeness invariants have an invalid or duplicate name")
        expected, actual = item.get("expected"), item.get("actual")
        if (
            item.get("passed") is not True
            or type(expected) is not int
            or type(actual) is not int
            or expected < 0
            or actual < 0
            or actual != expected
        ):
            raise ContinuityInputError(f"compiler completeness invariant is failed or inexact: {name}")
        by_name[name] = item
    missing = [name for name in REQUIRED_INVARIANTS if name not in by_name]
    if missing:
        raise ContinuityInputError(f"compiler required exact-denominator invariants are absent: {missing}")

    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        raise ContinuityInputError("compiler record-group manifest is absent")
    line_count = groups.get("lines", {}).get("record_count") if isinstance(groups.get("lines"), dict) else None
    gui_count = sum(
        groups.get(name, {}).get("record_count", -1)
        for name in ("routes", "components")
        if isinstance(groups.get(name), dict)
    )
    if line_count != by_name[REQUIRED_INVARIANTS[0]]["expected"]:
        raise ContinuityInputError("compiler line denominator differs from its exact invariant")
    if gui_count != by_name[REQUIRED_INVARIANTS[1]]["expected"]:
        raise ContinuityInputError("compiler GUI dossier denominator differs from its exact invariant")
    structural_count = (
        groups.get("structural_entities", {}).get("record_count")
        if isinstance(groups.get("structural_entities"), dict)
        else None
    )
    if structural_count != by_name[REQUIRED_INVARIANTS[2]]["expected"]:
        raise ContinuityInputError("compiler structural-root denominator differs from its exact invariant")

    acceptance = completeness.get("acceptance_gates")
    if not isinstance(acceptance, list) or not acceptance:
        raise ContinuityInputError("compiler semantic acceptance gates are absent")
    acceptance_names: set[str] = set()
    for item in acceptance:
        if not isinstance(item, dict):
            raise ContinuityInputError("compiler semantic acceptance gate is not an object")
        name = item.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name in acceptance_names
            or not isinstance(item.get("passed"), bool)
        ):
            raise ContinuityInputError("compiler semantic acceptance gates are malformed or duplicated")
        acceptance_names.add(name)


@dataclass
class LazyCompilerCorpus:
    """Compiler identity plus lazy, validated record-group iteration."""

    root: Path
    manifest: dict[str, Any]
    completeness: dict[str, Any]
    graphify: dict[str, Any]
    architecture_conformance: dict[str, Any]
    _chunk_reads: int = 0
    _chunk_bytes: int = 0
    _group_passes: dict[str, int] = field(default_factory=dict)
    _validated_raw_chunk_cache: dict[tuple[str, int, str], bytes] = field(default_factory=dict)
    _chunk_cache_hits: int = 0
    _chunk_cache_bytes: int = 0

    @property
    def source_commit(self) -> str:
        return str(self.manifest["source_commit"])

    @property
    def source_tree_digest(self) -> str:
        return str(self.manifest["source_tree_digest"])

    @property
    def groups(self) -> dict[str, Any]:
        return self.manifest["groups"]

    def _path(self, relative: str) -> Path:
        safe = safe_relative(relative)
        path = self.root.joinpath(*safe.split("/")).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ContinuityInputError(f"compiler receipt escapes corpus root: {relative}")
        return path

    def _receipt(
        self,
        receipt: object,
        label: str,
        *,
        cache_validated_raw: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(receipt, dict):
            raise ContinuityInputError(f"compiler {label} receipt is not an object")
        relative = safe_relative(receipt.get("path"))
        expected_bytes = receipt.get("bytes")
        expected_digest = receipt.get("sha256")
        if (
            type(expected_bytes) is not int
            or expected_bytes < 0
            or not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
        ):
            raise ContinuityInputError(f"compiler {label} receipt metadata is invalid: {relative}")
        cache_key = (relative, expected_bytes, expected_digest)
        raw = self._validated_raw_chunk_cache.get(cache_key) if cache_validated_raw else None
        if raw is not None:
            self._chunk_cache_hits += 1
            return relative, _canonical_object(raw, f"{label} {relative}")
        if self._chunk_reads + 1 > MAX_VALIDATED_RECEIPT_READS:
            raise ContinuityInputError("compiler request exceeds the validated receipt-read budget")
        if self._chunk_bytes + expected_bytes > MAX_VALIDATED_RECEIPT_BYTES:
            raise ContinuityInputError("compiler request exceeds the validated receipt-byte budget")
        if (
            cache_validated_raw
            and self._chunk_cache_bytes + expected_bytes > MAX_VALIDATED_CHUNK_CACHE_BYTES
        ):
            raise ContinuityInputError("compiler request exceeds the validated raw-chunk cache budget")
        path = self._path(relative)
        with path.open("rb") as handle:
            raw = handle.read(expected_bytes + 1)
        self._chunk_reads += 1
        self._chunk_bytes += len(raw)
        if expected_bytes != len(raw) or expected_digest != sha256_bytes(raw):
            raise ContinuityInputError(f"compiler {label} receipt mismatch: {relative}")
        value = _canonical_object(raw, f"{label} {relative}")
        if cache_validated_raw:
            self._validated_raw_chunk_cache[cache_key] = raw
            self._chunk_cache_bytes += len(raw)
        return relative, value

    def iter_group(self, group_name: str) -> Iterator[dict[str, Any]]:
        group = self.groups.get(group_name)
        if not isinstance(group, dict):
            raise ContinuityInputError(f"compiler record group is absent: {group_name}")
        chunks = group.get("chunks")
        if not isinstance(chunks, list) or group.get("chunk_count") != len(chunks):
            raise ContinuityInputError(f"compiler record group is malformed: {group_name}")
        self._group_passes[group_name] = self._group_passes.get(group_name, 0) + 1
        aggregate = _streaming_id_digest_start()
        first = True
        count = 0
        receipt_count = 0
        for expected_index, receipt in enumerate(chunks):
            _relative, envelope = self._receipt(
                receipt,
                f"{group_name} chunk",
                cache_validated_raw=group_name in CACHEABLE_ENHANCEMENT_GROUPS,
            )
            if (
                envelope.get("schema_version") != COMPILER_SCHEMA_VERSION
                or envelope.get("record_type") != group_name
                or envelope.get("source_commit") != self.source_commit
                or envelope.get("source_tree_digest") != self.source_tree_digest
                or envelope.get("chunk_index") != expected_index
                or envelope.get("chunk_count") != len(chunks)
            ):
                raise ContinuityInputError(f"compiler chunk envelope mismatch: {group_name}:{expected_index}")
            records = envelope.get("records")
            if not isinstance(records, list) or envelope.get("record_count") != len(records):
                raise ContinuityInputError(f"compiler chunk records are malformed: {group_name}:{expected_index}")
            identifiers: list[str] = []
            for record in records:
                if not isinstance(record, dict):
                    raise ContinuityInputError(f"compiler {group_name} contains a non-object record")
                identifier = record.get("id")
                if not isinstance(identifier, str) or not identifier:
                    raise ContinuityInputError(f"compiler {group_name} contains an invalid stable id")
                identifiers.append(identifier)
            if len(identifiers) != len(set(identifiers)):
                raise ContinuityInputError(f"compiler {group_name} chunk contains a duplicate stable id")
            if envelope.get("records_digest") != digest_object(identifiers):
                raise ContinuityInputError(f"compiler chunk record digest mismatch: {group_name}:{expected_index}")
            receipt_count += len(records)
            for record, identifier in zip(records, identifiers, strict=True):
                _streaming_id_digest_add(aggregate, identifier, first)
                first = False
                count += 1
                yield record
        if group.get("record_count") != receipt_count or group.get("record_count") != count:
            raise ContinuityInputError(f"compiler group receipt count mismatch: {group_name}")
        if group.get("records_digest") != _streaming_id_digest_finish(aggregate):
            raise ContinuityInputError(f"compiler group aggregate digest mismatch: {group_name}")

    def io_scan_counts(self) -> dict[str, Any]:
        return {
            "validated_chunk_reads": self._chunk_reads,
            "validated_chunk_bytes": self._chunk_bytes,
            "validated_group_passes": dict(sorted(self._group_passes.items())),
            "validated_unique_chunk_reads": self._chunk_reads,
            "validated_chunk_cache_hits": self._chunk_cache_hits,
            "validated_chunk_cache_bytes": self._chunk_cache_bytes,
            "validated_receipt_read_limit": MAX_VALIDATED_RECEIPT_READS,
            "validated_receipt_reads_remaining": MAX_VALIDATED_RECEIPT_READS - self._chunk_reads,
            "validated_receipt_byte_limit": MAX_VALIDATED_RECEIPT_BYTES,
            "validated_receipt_bytes_remaining": MAX_VALIDATED_RECEIPT_BYTES - self._chunk_bytes,
            "validated_chunk_cache_byte_limit": MAX_VALIDATED_CHUNK_CACHE_BYTES,
            "validated_chunk_cache_bytes_remaining": (
                MAX_VALIDATED_CHUNK_CACHE_BYTES - self._chunk_cache_bytes
            ),
            "request_snapshot": True,
        }


def load_enhancement_corpus(root: Path) -> LazyCompilerCorpus:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ContinuityInputError("compiler output root is not a directory")
    manifest_raw = root.joinpath("manifest.json").read_bytes()
    manifest = _canonical_object(manifest_raw, "manifest")
    if manifest.get("status") != "complete":
        raise ContinuityInputError("compiler manifest is not complete")
    if manifest.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ContinuityInputError(f"unsupported compiler schema: {manifest.get('schema_version')!r}")
    _object_id(manifest.get("source_commit"), "source_commit", {40, 64})
    _object_id(manifest.get("source_tree_digest"), "source_tree_digest", {64})
    _object_id(manifest.get("head_tree_oid"), "head_tree_oid", {40, 64})
    _object_id(manifest.get("index_digest"), "index_digest", {64})
    if manifest.get("release_class") != "exact_commit" or manifest.get("tracked_worktree_dirty") is not False:
        raise ContinuityInputError("enhancement corpus must be an exact clean-commit compiler output")
    groups = manifest.get("groups")
    if not isinstance(groups, dict) or not REQUIRED_GROUPS.issubset(groups):
        missing = sorted(REQUIRED_GROUPS - set(groups or {}))
        raise ContinuityInputError(f"compiler manifest is missing required record groups: {missing}")

    placeholder = LazyCompilerCorpus(root, manifest, {}, {}, {})
    _completeness_path, completeness = placeholder._receipt(manifest.get("completeness"), "completeness")
    _graphify_path, graphify = placeholder._receipt(manifest.get("graphify_metadata"), "Graphify metadata")
    _architecture_path, architecture = placeholder._receipt(
        manifest.get("architecture_conformance"), "architecture conformance"
    )
    if (
        completeness.get("source_commit") != manifest["source_commit"]
        or completeness.get("source_tree_digest") != manifest["source_tree_digest"]
    ):
        raise ContinuityInputError("compiler completeness ledger is not source bound")
    _validate_gate_contract(manifest, completeness)
    if graphify != completeness.get("graphify"):
        raise ContinuityInputError("compiler Graphify receipt differs from completeness")
    if architecture != completeness.get("architecture_conformance"):
        raise ContinuityInputError("compiler architecture receipt differs from completeness")
    if graphify.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ContinuityInputError("compiler Graphify metadata schema is stale")
    if (
        architecture.get("schema_version") != COMPILER_SCHEMA_VERSION
        or
        architecture.get("source_commit") != manifest["source_commit"]
        or architecture.get("source_tree_digest") != manifest["source_tree_digest"]
        or architecture.get("status") != "passed"
        or architecture.get("errors")
        or architecture.get("runtime_observed") is not False
    ):
        raise ContinuityInputError("compiler architecture conformance is not exact, static, and passed")
    placeholder.completeness = completeness
    placeholder.graphify = graphify
    placeholder.architecture_conformance = architecture
    return placeholder
