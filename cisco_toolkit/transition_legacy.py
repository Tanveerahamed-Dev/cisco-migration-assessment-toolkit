"""Pinned, non-promoting Release 1 receipt compatibility for Atlas Release 2.

Release 1 receipts retain their original schemas, six-state cutover vocabulary, canonicalization,
and owner roster.  This module verifies and replays those semantics without rewriting them into an
R2 gate.  The approved source bundle is byte-pinned below, but accountable approval of that
one-time legacy semantic anchor is still required before legacy material may contribute authority;
therefore every adapter receipt is ``AUDIT_ONLY`` with a null R2 gate.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from importlib import metadata, resources
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .transition_contract import (
    TransitionContractError,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)


LEGACY_R1_ADAPTER_SCHEMA = "atlas.release1-adapter-receipt/1"
LEGACY_R1_REPLAY_SCHEMA = "atlas.release1-replay-receipt/1"
LEGACY_R1_SEMANTIC_BUNDLE_SCHEMA = "atlas.release1-semantic-bundle/1"
LEGACY_R1_ADAPTER_VERSION = "ATLAS_R1_REFERENCE_ADAPTER/1"
LEGACY_R1_APPROVED_HEAD = "08f745ff7e12ff14ec84dee500b016292870aaa5"
LEGACY_R1_MAIN_MERGE = "6d52c90e"
LEGACY_R1_SEMANTIC_BUNDLE_DIGEST = "sha256:a72fb7bd52e767f446237d21f50d6b36daba84c6f1befaf7f307a88632403489"
LEGACY_R1_AUTHORITY_STATE = "ACCOUNTABLE_OWNER_APPROVAL_REQUIRED"
LEGACY_R1_EXECUTABLE_BUNDLE_SCHEMA = "atlas.release1-executable-bundle/1"
LEGACY_R1_SOURCE_BUNDLE_SCHEMA = "atlas.release1-source-bundle/1"
LEGACY_R1_EXECUTABLE_BUNDLE_RESOURCE = "atlas-r1-source-bundle.json"
LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_RESOURCE = "atlas-r1-executable-bundle.json"
LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_DIGEST = (
    "sha256:e6affd27239740a87db3643a6b8a1574c474703bb5273149a9ac5a4a205c1010"
)
LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_BYTES = 2_340
LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST = (
    "sha256:0e1708c20eaef9e8b19d512db116c737288dd571db0bd72175e72ed55abd4f0f"
)
LEGACY_R1_EXECUTABLE_BUNDLE_BYTES = 7_130_074
LEGACY_R1_EXECUTABLE_BUNDLE_ENTRIES = 47
LEGACY_R1_SOURCE_PATH_SET_DIGEST = (
    "sha256:532e0a048fe0949ff7c570834d78a828c2f2a3e5984329f75f4f8624e2845383"
)
LEGACY_R1_EXECUTION_TIMEOUT_SECONDS = 60
LEGACY_R1_RETROSPECTIVE_BEFORE_RESOURCE = "atlas-r1-retrospective-before.json"
LEGACY_R1_RETROSPECTIVE_BEFORE_DIGEST = (
    "sha256:2850e395c181f5d0a905cf1a2d78ca30392387b3094180bddff1fe484019c43b"
)
LEGACY_R1_RETROSPECTIVE_BEFORE_BYTES = 97
LEGACY_R1_RETROSPECTIVE_AFTER_RESOURCE = "atlas-r1-retrospective-after.json"
LEGACY_R1_RETROSPECTIVE_AFTER_DIGEST = (
    "sha256:65d7cf26707792d897ae68341d0114df488f19e9789da69eadcd095c41d1c8fa"
)
LEGACY_R1_RETROSPECTIVE_AFTER_BYTES = 97
LEGACY_R1_RETROSPECTIVE_COMPARISON_RESOURCE = "atlas-r1-retrospective-comparison.json"
LEGACY_R1_RETROSPECTIVE_COMPARISON_DIGEST = (
    "sha256:e92dbe997b92b3c6d1e3017408ac1a32e7364e14f61edd9202a67d9710a87c70"
)
LEGACY_R1_RETROSPECTIVE_COMPARISON_BYTES = 51_678

LEGACY_R1_SOURCE_MANIFEST = (
    {
        "path": "cisco_toolkit/comparison.py",
        "sha256": "sha256:1cbc83cf63cece72f236ea5f11c88b238d44612e1e4d7b6c48397c825aab1be2",
        "bytes": 11994,
    },
    {
        "path": "cisco_toolkit/protocol_assurance.py",
        "sha256": "sha256:adb398c8c4828ea43c8e3a0776f0f075caf1f278f112b925b7029d2ac5a636fd",
        "bytes": 107512,
    },
    {
        "path": "cisco_toolkit/html.py",
        "sha256": "sha256:ca291e2fe64908ddfe2b19f1edcc1be37fc7b920c3e1e28a821329621b33be19",
        "bytes": 241055,
    },
    {
        "path": "cisco_toolkit/precert.py",
        "sha256": "sha256:6d5bc39d21bf65e2f39ccdbff9fa1828e0c0f4437a0b2cc0a9935aa6262c4735",
        "bytes": 40762,
    },
    {
        "path": "cisco_toolkit/l2_rehearsal.py",
        "sha256": "sha256:68fd7ac440d51814031038604dbd3fac6abfeb5e6570ac640420a131c5cc174f",
        "bytes": 148960,
    },
    {
        "path": "cisco_toolkit/protocol_deltas.py",
        "sha256": "sha256:7638abfd4ee403846ed941897fc64f8afbd840ad977813d84f1062a4797376a4",
        "bytes": 105158,
    },
    {
        "path": "cisco_toolkit/traffic_assurance.py",
        "sha256": "sha256:bd916e06f8b40f7a8b89aeb5246e0956af011859482863767c6d72d663eb7dd3",
        "bytes": 120129,
    },
    {
        "path": "webapp/backend/storage.py",
        "sha256": "sha256:cdea2af34dcc3c6ced4e7c927f4cca0c212cace4e5f4ea20cf45da415bcbf0e5",
        "bytes": 159750,
    },
    {
        "path": "webapp/backend/execution.py",
        "sha256": "sha256:3069eb3ac19b2e13dade019d59dd663b1deacdc613f6f187c15cdc34a31aecdb",
        "bytes": 22676,
    },
    {
        "path": "webapp/backend/engine.py",
        "sha256": "sha256:92432b0d42d5dabbe683d7db6c1553b10316e1181a76385c5628c40105b6d9e3",
        "bytes": 15356,
    },
    {
        "path": "webapp/frontend/src/api.ts",
        "sha256": "sha256:2d313060e57eac121d628ffd787d600e17c2948a9e730905527ce84a3cf5ae26",
        "bytes": 52951,
    },
)

_VERIFIED_LEGACY_BUNDLE_AUTHORITY = object()
_MAX_LEGACY_JSON_BYTES = 64 * 1024 * 1024
_MAX_PINNED_DRIVER_REQUEST_BYTES = 192 * 1024 * 1024
_MAX_SOURCE_BUNDLE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_BUNDLE_FILES = 128
_MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024


_PINNED_RELEASE1_DRIVER = r'''\
import base64
import hashlib
import json
import sys

sys.path.insert(0, sys.argv[1])

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit.comparison import compare_bound_pair

ADDITIVE = frozenset({
    "comparison_schema",
    "comparison_admission",
    "change_intent",
    "protocol_families",
    "precert",
    "cutover_gate",
    "operator_evidence",
    "comparison_receipt",
})
GATES = frozenset({"PASS", "REVIEW", "INDETERMINATE", "FAIL", "CONDITIONAL", "REGRESSED"})


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def refuse(code):
    emit({"ok": False, "code": code})
    raise SystemExit(0)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def decode(value, code):
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        refuse(code)


def validate_comparison(raw):
    try:
        comparison = json.loads(raw.decode("utf-8", "strict"))
    except Exception:
        refuse("legacy_receipt_source_invalid")
    if not isinstance(comparison, dict):
        refuse("legacy_receipt_root_invalid")
    if comparison.get("comparison_schema") != "source_bound_cutover_comparison/1":
        refuse("legacy_comparison_schema_unsupported")
    admission = comparison.get("comparison_admission")
    try:
        validation = pa.validate_comparison_admission(admission)
    except Exception:
        refuse("legacy_comparison_admission_invalid")
    if not validation.get("valid"):
        refuse("legacy_comparison_admission_invalid")
    envelope = comparison.get("comparison_receipt")
    delta = {key: item for key, item in comparison.items() if key not in ADDITIVE}
    payload = {
        "admission": admission,
        "change_intent": comparison.get("change_intent"),
        "protocol_families": comparison.get("protocol_families"),
        "delta": delta,
        "precert": comparison.get("precert"),
        "cutover_gate": comparison.get("cutover_gate"),
        "operator_evidence": comparison.get("operator_evidence"),
    }
    try:
        envelope_valid = pa.verify_receipt_envelope(envelope, payload)
    except Exception:
        envelope_valid = False
    if not envelope_valid or not isinstance(envelope, dict):
        refuse("legacy_comparison_envelope_invalid")
    if (
        envelope.get("admission") != admission
        or envelope.get("source_binding") != admission.get("source_binding")
        or envelope.get("subject_binding") != admission.get("subject_binding")
        or envelope.get("owner_versions") != admission.get("owner_versions")
        or envelope.get("support_profiles") != admission.get("support_profiles")
    ):
        refuse("legacy_comparison_envelope_binding_mismatch")
    gate = comparison.get("cutover_gate")
    if (
        not isinstance(gate, dict)
        or gate.get("schema") != "cutover_gate/1"
        or gate.get("verdict") not in GATES
    ):
        refuse("legacy_cutover_gate_invalid")
    canonical = pa.canonical_json_bytes(comparison)
    return comparison, {
        "canonical_payload_digest": digest(canonical),
        "canonical_payload_bytes": len(canonical),
        "legacy_receipt_sha256": envelope.get("receipt_sha256"),
        "legacy_cutover_verdict": gate.get("verdict"),
    }


try:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8", "strict"))
    operation = request.get("operation")
    comparison_raw = decode(request.get("comparison_base64"), "legacy_receipt_source_invalid")
    comparison, summary = validate_comparison(comparison_raw)
    if operation == "validate":
        emit({"ok": True, "summary": summary})
    elif operation == "replay":
        before_raw = decode(request.get("before_base64"), "legacy_snapshot_source_invalid")
        after_raw = decode(request.get("after_base64"), "legacy_snapshot_source_invalid")
        source_pair = comparison["comparison_admission"]["source_binding"]
        for side, raw in (("before", before_raw), ("after", after_raw)):
            binding = source_pair[side]
            if binding.get("sha256") != digest(raw) or binding.get("bytes") != len(raw):
                refuse("legacy_snapshot_source_binding_mismatch")
        try:
            replayed = compare_bound_pair(
                pa.bind_snapshot_json_bytes(before_raw),
                pa.bind_snapshot_json_bytes(after_raw),
                before_binding=dict(source_pair["before"]),
                after_binding=dict(source_pair["after"]),
                change_intent=request.get("change_intent"),
                path_intents=request.get("path_intents"),
                l2_failure_trial=request.get("l2_failure_trial"),
            )
            replayed_raw = pa.canonical_json_bytes(dict(replayed))
            expected_raw = pa.canonical_json_bytes(comparison)
        except Exception:
            refuse("legacy_replay_failed_closed")
        if expected_raw != replayed_raw:
            refuse("legacy_replay_semantic_payload_mismatch")
        emit({
            "ok": True,
            "summary": summary,
            "replayed_payload_digest": digest(replayed_raw),
            "replayed_payload_bytes": len(replayed_raw),
        })
    else:
        refuse("legacy_replay_operation_invalid")
except SystemExit:
    raise
except Exception:
    refuse("legacy_pinned_runtime_failed_closed")
'''


class LegacyCompatibilityError(ValueError):
    """Fixed-code legacy compatibility refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VerifiedLegacySemanticBundle:
    """Process-local proof of the immutable, executable Release 1 compatibility capsule."""

    __slots__ = (
        "_bundle_bytes",
        "_integrity_digest",
        "_sealed",
        "approved_head",
        "digest",
        "executable_bundle_digest",
        "file_count",
        "historical_source_roster_verified",
        "runtime_matches_reference",
        "runtime_profile_digest",
    )

    def __init__(
            self,
            *,
            digest: str,
            file_count: int,
            source_bundle_bytes: bytes,
            runtime_profile_digest: str,
            runtime_matches_reference: bool,
            historical_source_roster_verified: bool,
            _authority: object) -> None:
        if _authority is not _VERIFIED_LEGACY_BUNDLE_AUTHORITY:
            raise TypeError("legacy semantic bundle must be verified from exact owner bytes")
        object.__setattr__(self, "_sealed", False)
        self.digest = digest
        self.approved_head = LEGACY_R1_APPROVED_HEAD
        self.file_count = file_count
        self.historical_source_roster_verified = historical_source_roster_verified
        self.executable_bundle_digest = bytes_digest(source_bundle_bytes)
        self.runtime_profile_digest = runtime_profile_digest
        self.runtime_matches_reference = runtime_matches_reference
        object.__setattr__(self, "_bundle_bytes", bytes(source_bundle_bytes))
        object.__setattr__(self, "_integrity_digest", self._compute_integrity_digest())
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("VerifiedLegacySemanticBundle is immutable")
        object.__setattr__(self, name, value)

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "approved_head": self.approved_head,
            "digest": self.digest,
            "executable_bundle_digest": bytes_digest(self._bundle_bytes),
            "file_count": self.file_count,
            "historical_source_roster_verified": self.historical_source_roster_verified,
            "runtime_matches_reference": self.runtime_matches_reference,
            "runtime_profile_digest": self.runtime_profile_digest,
        })


def _legacy_reject(code: str) -> None:
    raise LegacyCompatibilityError(code)


def legacy_semantic_bundle_manifest() -> dict[str, Any]:
    manifest = {
        "schema": LEGACY_R1_SEMANTIC_BUNDLE_SCHEMA,
        "approved_head": LEGACY_R1_APPROVED_HEAD,
        "files": [dict(item) for item in LEGACY_R1_SOURCE_MANIFEST],
    }
    if canonical_digest(manifest) != LEGACY_R1_SEMANTIC_BUNDLE_DIGEST:
        _legacy_reject("legacy_semantic_manifest_constant_mismatch")
    return manifest


def _actual_runtime_profile(reference: Mapping[str, Any]) -> dict[str, Any]:
    distributions: list[dict[str, Any]] = []
    for item in reference["external_distributions"]:
        try:
            version = metadata.version(item["name"])
        except metadata.PackageNotFoundError:
            version = None
        distributions.append({"name": item["name"], "version": version})
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "external_distributions": distributions,
    }


def _parse_source_bundle(raw: bytes) -> dict[str, bytes]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_SOURCE_BUNDLE_BYTES:
        _legacy_reject("legacy_executable_bundle_digest_mismatch")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _legacy_reject("legacy_executable_bundle_inventory_mismatch")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda _value: _legacy_reject(
                "legacy_executable_bundle_inventory_mismatch"
            ),
        )
        recoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except LegacyCompatibilityError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, MemoryError):
        _legacy_reject("legacy_executable_bundle_inventory_mismatch")
    if recoded != raw or type(value) is not dict or set(value) != {
            "approved_head", "chunk_encoding", "files", "schema"}:
        _legacy_reject("legacy_executable_bundle_inventory_mismatch")
    if (
            value["schema"] != LEGACY_R1_SOURCE_BUNDLE_SCHEMA
            or value["approved_head"] != LEGACY_R1_APPROVED_HEAD
            or value["chunk_encoding"] != "BASE64_RFC4648_512_KIB_RAW_CHUNKS"
            or type(value["files"]) is not list
            or len(value["files"]) != LEGACY_R1_EXECUTABLE_BUNDLE_ENTRIES
            or len(value["files"]) > _MAX_SOURCE_BUNDLE_FILES
    ):
        _legacy_reject("legacy_executable_bundle_inventory_mismatch")
    files: dict[str, bytes] = {}
    for entry in value["files"]:
        if type(entry) is not dict or set(entry) != {
                "bytes", "content_base64_chunks", "path", "sha256"}:
            _legacy_reject("legacy_executable_bundle_inventory_mismatch")
        path = entry["path"]
        chunks = entry["content_base64_chunks"]
        if (
                type(path) is not str
                or not path.startswith("cisco_toolkit/")
                or path.startswith(("/", "\\"))
                or "\\" in path
                or ".." in path.split("/")
                or type(chunks) is not list
                or not chunks
                or any(type(chunk) is not str for chunk in chunks)
        ):
            _legacy_reject("legacy_executable_bundle_inventory_mismatch")
        try:
            content = b"".join(
                base64.b64decode(chunk, validate=True)
                for chunk in chunks
            )
        except (ValueError, TypeError):
            _legacy_reject("legacy_executable_bundle_inventory_mismatch")
        if (
                len(content) > _MAX_SOURCE_FILE_BYTES
                or type(entry["bytes"]) is not int
                or entry["bytes"] != len(content)
                or entry["sha256"] != bytes_digest(content)
                or path in files
        ):
            _legacy_reject("legacy_executable_bundle_inventory_mismatch")
        files[path] = content
    paths = sorted(files)
    required = {
        "cisco_toolkit/__init__.py",
        "cisco_toolkit/comparison.py",
        "cisco_toolkit/protocol_assurance.py",
    }
    if (
            list(files) != paths
            or not required.issubset(files)
            or canonical_digest(paths) != LEGACY_R1_SOURCE_PATH_SET_DIGEST
    ):
        _legacy_reject("legacy_executable_bundle_inventory_mismatch")
    return files


def _load_packaged_executable_bundle() -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    try:
        package_root = resources.files("cisco_toolkit")
        manifest_raw = package_root.joinpath(
            "data", LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_RESOURCE
        ).read_bytes()
        bundle_raw = package_root.joinpath(
            "data", LEGACY_R1_EXECUTABLE_BUNDLE_RESOURCE
        ).read_bytes()
        before_raw = package_root.joinpath(
            "data", LEGACY_R1_RETROSPECTIVE_BEFORE_RESOURCE
        ).read_bytes()
        after_raw = package_root.joinpath(
            "data", LEGACY_R1_RETROSPECTIVE_AFTER_RESOURCE
        ).read_bytes()
        comparison_raw = package_root.joinpath(
            "data", LEGACY_R1_RETROSPECTIVE_COMPARISON_RESOURCE
        ).read_bytes()
        manifest = parse_canonical_json_bytes(manifest_raw, require_canonical=True)
    except (FileNotFoundError, OSError, TypeError, TransitionContractError):
        _legacy_reject("legacy_executable_bundle_unavailable")
    if not isinstance(manifest, dict):
        _legacy_reject("legacy_executable_bundle_manifest_invalid")
    if (
            len(manifest_raw) != LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_BYTES
            or bytes_digest(manifest_raw) != LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_DIGEST
    ):
        _legacy_reject("legacy_executable_bundle_manifest_digest_mismatch")
    expected_manifest_values = {
        "schema": LEGACY_R1_EXECUTABLE_BUNDLE_SCHEMA,
        "approved_head": LEGACY_R1_APPROVED_HEAD,
        "source_bundle_resource": LEGACY_R1_EXECUTABLE_BUNDLE_RESOURCE,
        "source_bundle_sha256": LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST,
        "source_bundle_bytes": LEGACY_R1_EXECUTABLE_BUNDLE_BYTES,
        "source_bundle_file_count": LEGACY_R1_EXECUTABLE_BUNDLE_ENTRIES,
        "adapter_authority": "AUDIT_ONLY",
        "r2_promotion_eligible": False,
    }
    if any(manifest.get(key) != value for key, value in expected_manifest_values.items()):
        _legacy_reject("legacy_executable_bundle_manifest_invalid")
    if (
            type(bundle_raw) is not bytes
            or len(bundle_raw) != LEGACY_R1_EXECUTABLE_BUNDLE_BYTES
            or bytes_digest(bundle_raw) != LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST
    ):
        _legacy_reject("legacy_executable_bundle_digest_mismatch")
    retrospective = manifest.get("retrospective_conformance_vector")
    expected_retrospective = {
        "after_resource": LEGACY_R1_RETROSPECTIVE_AFTER_RESOURCE,
        "after_source_bytes": LEGACY_R1_RETROSPECTIVE_AFTER_BYTES,
        "after_source_sha256": LEGACY_R1_RETROSPECTIVE_AFTER_DIGEST,
        "before_resource": LEGACY_R1_RETROSPECTIVE_BEFORE_RESOURCE,
        "before_source_bytes": LEGACY_R1_RETROSPECTIVE_BEFORE_BYTES,
        "before_source_sha256": LEGACY_R1_RETROSPECTIVE_BEFORE_DIGEST,
        "canonical_comparison_bytes": LEGACY_R1_RETROSPECTIVE_COMPARISON_BYTES,
        "canonical_comparison_resource": LEGACY_R1_RETROSPECTIVE_COMPARISON_RESOURCE,
        "canonical_comparison_sha256": LEGACY_R1_RETROSPECTIVE_COMPARISON_DIGEST,
        "historical_receipt": False,
    }
    if retrospective != expected_retrospective:
        _legacy_reject("legacy_retrospective_vector_manifest_invalid")
    for raw, expected_bytes, expected_digest in (
        (
            before_raw,
            LEGACY_R1_RETROSPECTIVE_BEFORE_BYTES,
            LEGACY_R1_RETROSPECTIVE_BEFORE_DIGEST,
        ),
        (
            after_raw,
            LEGACY_R1_RETROSPECTIVE_AFTER_BYTES,
            LEGACY_R1_RETROSPECTIVE_AFTER_DIGEST,
        ),
        (
            comparison_raw,
            LEGACY_R1_RETROSPECTIVE_COMPARISON_BYTES,
            LEGACY_R1_RETROSPECTIVE_COMPARISON_DIGEST,
        ),
    ):
        if type(raw) is not bytes or len(raw) != expected_bytes or bytes_digest(raw) != expected_digest:
            _legacy_reject("legacy_retrospective_vector_digest_mismatch")
    _parse_source_bundle(bundle_raw)
    closure = manifest.get("source_closure")
    if (
            type(closure) is not dict
            or closure.get("path_set_sha256") != LEGACY_R1_SOURCE_PATH_SET_DIGEST
            or closure.get("python_source_file_count") != 41
            or closure.get("package_data_file_count") != 6
    ):
        _legacy_reject("legacy_executable_bundle_manifest_invalid")
    reference_runtime = manifest.get("runtime_profile")
    if not isinstance(reference_runtime, dict):
        _legacy_reject("legacy_executable_bundle_manifest_invalid")
    actual_runtime = _actual_runtime_profile(reference_runtime)
    return manifest, bundle_raw, actual_runtime


def legacy_executable_bundle_manifest() -> dict[str, Any]:
    """Return a defensive copy of the verified packaged executable-capsule manifest."""

    manifest, _archive, _runtime = _load_packaged_executable_bundle()
    return deepcopy(manifest)


def legacy_retrospective_vector_bytes() -> tuple[bytes, bytes, bytes]:
    """Return the exact packaged before, after, and comparison conformance-vector bytes."""

    _load_packaged_executable_bundle()
    package_root = resources.files("cisco_toolkit").joinpath("data")
    return (
        package_root.joinpath(LEGACY_R1_RETROSPECTIVE_BEFORE_RESOURCE).read_bytes(),
        package_root.joinpath(LEGACY_R1_RETROSPECTIVE_AFTER_RESOURCE).read_bytes(),
        package_root.joinpath(LEGACY_R1_RETROSPECTIVE_COMPARISON_RESOURCE).read_bytes(),
    )


def _require_verified_bundle(value: Any) -> VerifiedLegacySemanticBundle:
    if not isinstance(value, VerifiedLegacySemanticBundle):
        _legacy_reject("legacy_semantic_bundle_not_verified")
    if (
            value.digest != LEGACY_R1_SEMANTIC_BUNDLE_DIGEST
            or value.approved_head != LEGACY_R1_APPROVED_HEAD
            or value.file_count != len(LEGACY_R1_SOURCE_MANIFEST)
            or value.executable_bundle_digest != LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST
            or bytes_digest(value._bundle_bytes) != LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST
            or value._compute_integrity_digest() != value._integrity_digest
    ):
        _legacy_reject("legacy_semantic_bundle_not_verified")
    return value


def _run_pinned_release1_driver(
        bundle: VerifiedLegacySemanticBundle,
        request: Mapping[str, Any]) -> dict[str, Any]:
    verified = _require_verified_bundle(bundle)
    try:
        request_raw = json.dumps(
            dict(request),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, MemoryError):
        _legacy_reject("legacy_replay_optional_input_invalid")
    if len(request_raw) > _MAX_PINNED_DRIVER_REQUEST_BYTES:
        _legacy_reject("legacy_replay_request_too_large")
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-r1-replay-") as temporary:
            root = Path(temporary)
            for relative, raw in _parse_source_bundle(verified._bundle_bytes).items():
                source = root.joinpath(*relative.split("/"))
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(raw)
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _PINNED_RELEASE1_DRIVER, str(root)],
                input=request_raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=root,
                timeout=LEGACY_R1_EXECUTION_TIMEOUT_SECONDS,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except (OSError, subprocess.SubprocessError):
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    if completed.returncode != 0 or not completed.stdout or len(completed.stdout) > 4 * 1024 * 1024:
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    try:
        response = json.loads(completed.stdout.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError, RecursionError, MemoryError):
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    if response["ok"] is not True:
        code = response.get("code")
        if type(code) is not str or not code.startswith("legacy_"):
            _legacy_reject("legacy_pinned_runtime_failed_closed")
        _legacy_reject(code)
    return response


def _read_stable_regular(path: Path) -> bytes:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            _legacy_reject("legacy_semantic_source_not_regular")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            handle_before = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            handle_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except LegacyCompatibilityError:
        raise
    except OSError:
        _legacy_reject("legacy_semantic_source_unavailable")
    identity_before = (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns)
    identity_handle_before = (
        handle_before.st_dev,
        handle_before.st_ino,
        handle_before.st_mode,
        handle_before.st_size,
        handle_before.st_mtime_ns,
    )
    identity_handle_after = (
        handle_after.st_dev,
        handle_after.st_ino,
        handle_after.st_mode,
        handle_after.st_size,
        handle_after.st_mtime_ns,
    )
    identity_after = (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
    if not identity_before == identity_handle_before == identity_handle_after == identity_after:
        _legacy_reject("legacy_semantic_source_changed_during_read")
    raw = b"".join(chunks)
    if len(raw) != handle_after.st_size:
        _legacy_reject("legacy_semantic_source_changed_during_read")
    return raw


def verify_release1_semantic_bundle(
        repo_root: str | os.PathLike[str] | None = None) -> VerifiedLegacySemanticBundle:
    """Verify the packaged runtime and, when supplied, the historical checkout audit roster."""

    historical_source_roster_verified = repo_root is not None
    if historical_source_roster_verified:
        try:
            root = Path(repo_root).resolve(strict=True)
        except OSError:
            _legacy_reject("legacy_repository_root_unavailable")
        if not root.is_dir():
            _legacy_reject("legacy_repository_root_unavailable")
        for expected in LEGACY_R1_SOURCE_MANIFEST:
            try:
                candidate = (root / expected["path"]).resolve(strict=True)
            except OSError:
                _legacy_reject("legacy_semantic_source_unavailable")
            try:
                candidate.relative_to(root)
            except ValueError:
                _legacy_reject("legacy_semantic_source_escaped_root")
            raw = _read_stable_regular(candidate)
            if len(raw) != expected["bytes"] or bytes_digest(raw) != expected["sha256"]:
                _legacy_reject("legacy_semantic_source_digest_mismatch")
    manifest, source_bundle_raw, actual_runtime = _load_packaged_executable_bundle()
    legacy_semantic_bundle_manifest()
    return VerifiedLegacySemanticBundle(
        digest=LEGACY_R1_SEMANTIC_BUNDLE_DIGEST,
        file_count=len(LEGACY_R1_SOURCE_MANIFEST),
        source_bundle_bytes=source_bundle_raw,
        runtime_profile_digest=canonical_digest(actual_runtime),
        runtime_matches_reference=actual_runtime == manifest["runtime_profile"],
        historical_source_roster_verified=historical_source_roster_verified,
        _authority=_VERIFIED_LEGACY_BUNDLE_AUTHORITY,
    )


def _strict_release1_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_LEGACY_JSON_BYTES:
        _legacy_reject("legacy_receipt_source_invalid")
    if raw.startswith(b"\xef\xbb\xbf"):
        _legacy_reject("legacy_receipt_source_invalid")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _legacy_reject("legacy_receipt_duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_: str) -> Any:
        _legacy_reject("legacy_receipt_nonfinite_number")

    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except LegacyCompatibilityError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, MemoryError):
        _legacy_reject("legacy_receipt_source_invalid")
    if not isinstance(value, dict):
        _legacy_reject("legacy_receipt_root_invalid")
    return value


def _validate_release1_comparison(
        raw: bytes,
        bundle: VerifiedLegacySemanticBundle) -> tuple[dict[str, Any], dict[str, Any]]:
    comparison = _strict_release1_json(raw)
    response = _run_pinned_release1_driver(bundle, {
        "operation": "validate",
        "comparison_base64": base64.b64encode(raw).decode("ascii"),
    })
    summary = response.get("summary")
    if not isinstance(summary, dict):
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    return comparison, summary


def _adapter_receipt(
        raw: bytes,
        comparison: Mapping[str, Any],
        summary: Mapping[str, Any],
        executable_bundle: VerifiedLegacySemanticBundle,
        *,
        semantic_bundle_bytes_verified: bool) -> dict[str, Any]:
    envelope = comparison["comparison_receipt"]
    admission = comparison["comparison_admission"]
    receipt = {
        "schema": LEGACY_R1_ADAPTER_SCHEMA,
        "adapter_version": LEGACY_R1_ADAPTER_VERSION,
        "legacy_schema": comparison["comparison_schema"],
        "legacy_source_digest": bytes_digest(raw),
        "legacy_canonical_payload_digest": summary["canonical_payload_digest"],
        "legacy_canonical_payload_bytes": summary["canonical_payload_bytes"],
        "legacy_receipt_sha256": envelope["receipt_sha256"],
        "legacy_cutover_verdict": comparison["cutover_gate"]["verdict"],
        "legacy_owner_versions_digest": canonical_digest(admission["owner_versions"]),
        "approved_head": LEGACY_R1_APPROVED_HEAD,
        "semantic_bundle_digest": LEGACY_R1_SEMANTIC_BUNDLE_DIGEST,
        "semantic_bundle_bytes_verified": semantic_bundle_bytes_verified,
        "historical_source_roster_verified": executable_bundle.historical_source_roster_verified,
        "executable_bundle_digest": executable_bundle.executable_bundle_digest,
        "executable_bundle_bytes_verified": True,
        "runtime_profile_digest": executable_bundle.runtime_profile_digest,
        "runtime_matches_reference": executable_bundle.runtime_matches_reference,
        "historical_fixture_state": (
            "NO_AUTHENTICATED_R1_COMPARISON_AND_SOURCE_PAIR_FOUND_IN_REPOSITORY"
        ),
        "semantic_anchor_authority_state": LEGACY_R1_AUTHORITY_STATE,
        "migration_policy": "REFERENCE_NOT_REWRITE",
        "adapter_authority": "AUDIT_ONLY",
        "r2_authoritative_gate": None,
        "r2_promotion_eligible": False,
        "reason_codes": [
            "LEGACY_R1_VOCABULARY_PRESERVED",
            "LEGACY_SEMANTIC_ANCHOR_OWNER_APPROVAL_REQUIRED",
            "LEGACY_RECEIPT_CANNOT_PROMOTE_R2",
        ],
    }
    canonical_json_bytes(receipt)
    return receipt


def adapt_release1_comparison_bytes(
        raw: bytes,
        semantic_bundle: VerifiedLegacySemanticBundle | None = None) -> dict[str, Any]:
    """Verify one detached R1 comparison and bind it as non-promoting audit evidence."""

    if type(raw) is not bytes:
        _legacy_reject("legacy_receipt_source_invalid")
    if isinstance(semantic_bundle, VerifiedLegacySemanticBundle):
        executable_bundle = _require_verified_bundle(semantic_bundle)
        bundle_verified = executable_bundle.historical_source_roster_verified
    else:
        executable_bundle = verify_release1_semantic_bundle()
        bundle_verified = False
    comparison, summary = _validate_release1_comparison(raw, executable_bundle)
    return _adapter_receipt(
        raw,
        comparison,
        summary,
        executable_bundle,
        semantic_bundle_bytes_verified=bundle_verified,
    )


def replay_release1_comparison_bytes(
        comparison_raw: bytes,
        before_snapshot_raw: bytes,
        after_snapshot_raw: bytes,
        semantic_bundle: VerifiedLegacySemanticBundle,
        *,
        change_intent: Mapping[str, Any] | None = None,
        path_intents: Sequence[Mapping[str, Any]] | None = None,
        l2_failure_trial: Any = None) -> dict[str, Any]:
    """Recompute a pinned R1 pair and require canonical semantic-payload identity.

    Exact source JSON bytes and any non-snapshot decision inputs are explicit.  The adapter does not
    infer them from rendered output and never translates the resulting R1 gate into R2 authority.
    """

    verified_bundle = _require_verified_bundle(semantic_bundle)
    comparison = _strict_release1_json(comparison_raw)
    if type(before_snapshot_raw) is not bytes or type(after_snapshot_raw) is not bytes:
        _legacy_reject("legacy_snapshot_source_invalid")
    response = _run_pinned_release1_driver(verified_bundle, {
        "operation": "replay",
        "comparison_base64": base64.b64encode(comparison_raw).decode("ascii"),
        "before_base64": base64.b64encode(before_snapshot_raw).decode("ascii"),
        "after_base64": base64.b64encode(after_snapshot_raw).decode("ascii"),
        "change_intent": None if change_intent is None else dict(change_intent),
        "path_intents": (
            None if path_intents is None else [dict(item) for item in path_intents]
        ),
        "l2_failure_trial": l2_failure_trial,
    })
    summary = response.get("summary")
    if not isinstance(summary, dict):
        _legacy_reject("legacy_pinned_runtime_failed_closed")
    adapter = _adapter_receipt(
        comparison_raw,
        comparison,
        summary,
        verified_bundle,
        semantic_bundle_bytes_verified=verified_bundle.historical_source_roster_verified,
    )
    receipt = {
        "schema": LEGACY_R1_REPLAY_SCHEMA,
        "adapter_receipt_digest": canonical_digest(adapter),
        "legacy_source_digest": bytes_digest(comparison_raw),
        "before_source_digest": bytes_digest(before_snapshot_raw),
        "after_source_digest": bytes_digest(after_snapshot_raw),
        "semantic_bundle_digest": verified_bundle.digest,
        "executable_bundle_digest": verified_bundle.executable_bundle_digest,
        "runtime_profile_digest": verified_bundle.runtime_profile_digest,
        "runtime_matches_reference": verified_bundle.runtime_matches_reference,
        "replayed_payload_digest": response["replayed_payload_digest"],
        "replayed_payload_bytes": response["replayed_payload_bytes"],
        "replay_state": "CANONICAL_SEMANTIC_PAYLOAD_IDENTICAL",
        "historical_semantics_rewritten": False,
        "legacy_cutover_verdict": comparison["cutover_gate"]["verdict"],
        "r2_authoritative_gate": None,
        "r2_promotion_eligible": False,
        "migration_policy": "REFERENCE_NOT_REWRITE",
    }
    canonical_json_bytes(receipt)
    return receipt


__all__ = [
    "LEGACY_R1_ADAPTER_SCHEMA",
    "LEGACY_R1_ADAPTER_VERSION",
    "LEGACY_R1_APPROVED_HEAD",
    "LEGACY_R1_AUTHORITY_STATE",
    "LEGACY_R1_EXECUTABLE_BUNDLE_BYTES",
    "LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST",
    "LEGACY_R1_EXECUTABLE_BUNDLE_ENTRIES",
    "LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_BYTES",
    "LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_DIGEST",
    "LEGACY_R1_EXECUTABLE_BUNDLE_MANIFEST_RESOURCE",
    "LEGACY_R1_EXECUTABLE_BUNDLE_RESOURCE",
    "LEGACY_R1_EXECUTABLE_BUNDLE_SCHEMA",
    "LEGACY_R1_RETROSPECTIVE_AFTER_BYTES",
    "LEGACY_R1_RETROSPECTIVE_AFTER_DIGEST",
    "LEGACY_R1_RETROSPECTIVE_AFTER_RESOURCE",
    "LEGACY_R1_RETROSPECTIVE_BEFORE_BYTES",
    "LEGACY_R1_RETROSPECTIVE_BEFORE_DIGEST",
    "LEGACY_R1_RETROSPECTIVE_BEFORE_RESOURCE",
    "LEGACY_R1_RETROSPECTIVE_COMPARISON_BYTES",
    "LEGACY_R1_RETROSPECTIVE_COMPARISON_DIGEST",
    "LEGACY_R1_RETROSPECTIVE_COMPARISON_RESOURCE",
    "LEGACY_R1_SEMANTIC_BUNDLE_DIGEST",
    "LEGACY_R1_SOURCE_MANIFEST",
    "LegacyCompatibilityError",
    "VerifiedLegacySemanticBundle",
    "adapt_release1_comparison_bytes",
    "legacy_executable_bundle_manifest",
    "legacy_retrospective_vector_bytes",
    "legacy_semantic_bundle_manifest",
    "replay_release1_comparison_bytes",
    "verify_release1_semantic_bundle",
]
