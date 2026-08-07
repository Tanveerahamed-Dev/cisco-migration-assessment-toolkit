"""Strict reader for whole-repository compiler output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .model import ReleaseInputError, canonical_json, digest_object, read_bytes, safe_relative, sha256_bytes


REQUIRED_GROUPS = frozenset(
    {
        "files",
        "lines",
        "source_text",
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
    if manifest.get("schema_version") != "1.0.0":
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
    if completeness.get("source_commit") != commit or completeness.get("source_tree_digest") != tree:
        raise ReleaseInputError("completeness ledger is not bound to the compiler source")
    if completeness.get("hard_failure") is not False or completeness.get("fatal_errors"):
        raise ReleaseInputError("completeness ledger contains a hard failure")
    invariants = completeness.get("invariants")
    if not isinstance(invariants, list) or not invariants or any(item.get("passed") is not True for item in invariants):
        raise ReleaseInputError("not every compiler completeness invariant passed")
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
    wanted = set(groups) if retained_groups is None else set(retained_groups)
    unknown_wanted = wanted - set(groups)
    if unknown_wanted:
        raise ReleaseInputError(f"requested compiler groups are absent: {sorted(unknown_wanted)}")

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
                envelope.get("record_type") != group_name
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
    return CompilerBundle(root, manifest, completeness, records, tuple(sorted(input_files)))
