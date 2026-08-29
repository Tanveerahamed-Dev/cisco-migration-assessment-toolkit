#!/usr/bin/env python3
"""Structurally bind an Atlas R2 detached authority-decision receipt with zero effect.

This consumer is deliberately non-authoritative. It verifies canonical receipt bytes, the exact
candidate/package subject, every declared digest artifact, and a non-circular signing payload.
It does not decide whether a signature algorithm, key, policy, principal, time source, custody
arrangement, revocation view, or separation claim is trustworthy. Its result therefore has no
decision effect and cannot authorize evidence collection or approve Profile P1.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, InitVar
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Mapping


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name}_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_candidate_builder() -> ModuleType:
    return _load_module(
        "atlas_r2_authority_candidate_builder",
        Path(__file__).with_name("build_atlas_r2_authority_candidate.py"),
    )


def _load_transition_contract() -> ModuleType:
    return _load_module(
        "atlas_r2_transition_contract",
        Path(__file__).resolve().parents[1] / "cisco_toolkit" / "transition_contract.py",
    )


candidate = _load_candidate_builder()
transition_contract = _load_transition_contract()

DECISION_RECEIPT_SCHEMA = "atlas.r2-authority-decision-receipt/1"
SIGNING_PAYLOAD_SCHEMA = "atlas.r2-authority-decision-signing-payload/1"
DECISION_SUBJECT_SCHEMA = "atlas.r2-authority-decision-subject/1"
STRUCTURAL_BINDING_SCHEMA = "atlas.r2-authority-decision-structural-binding/1"
SIGNING_DOMAIN = b"ATLAS-R2-AUTHORITY-DECISION-SIGNING\x00v1\x00"
SIGNING_CONTRACT_REFERENCE = "PACKET_STRUCTURAL_SIGNING_CONTRACT"

AUTHORITY_PACKET_FILES = {
    "R2-AUTH-001": "R2-AUTH-001.json",
    "R2-AUTH-002": "R2-AUTH-002.json",
    "R2-AUTH-004": "R2-AUTH-004.json",
}

_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,191}\Z")
_REPOSITORY_NAMESPACE_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})\Z")
_GIT_OBJECT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

_MAX_RECEIPT_BYTES = 8 * 1024 * 1024
_MAX_SIGNATURE_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_PUBLIC_KEY_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_EXTERNAL_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_EXTERNAL_ARTIFACT_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_MEMBER_BYTES = 512 * 1024 * 1024

_INTERNALLY_BOUND_DIGEST_FIELDS = frozenset(
    {
        "detached_signature",
        "package_manifest_sha256",
        "payload_digest",
        "public_key_digest",
        "source_freeze_sha256",
    }
)
_BOUND_RECEIPT_AUTHORITY = object()


class AuthorityDecisionReceiptError(RuntimeError):
    """Stable, non-echoing refusal for untrusted decision inputs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject(code: str) -> None:
    raise AuthorityDecisionReceiptError(code)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return transition_contract.canonical_json_bytes(value)
    except (transition_contract.TransitionContractError, TypeError, ValueError):
        _reject("non_canonical_json_value")


def bytes_digest(raw: bytes) -> str:
    if type(raw) is not bytes:
        _reject("exact_bytes_required")
    return transition_contract.bytes_digest(raw)


def _parse_canonical_object(raw: bytes, error: str) -> dict[str, Any]:
    try:
        value = transition_contract.parse_canonical_json_bytes(raw, require_canonical=True)
    except (transition_contract.TransitionContractError, TypeError, ValueError):
        _reject(error)
    if type(value) is not dict:
        _reject(error)
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], error: str) -> None:
    if type(value) is not dict or set(value) != expected:
        _reject(error)


def _text(value: Any, error: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        _reject(error)
    return value


def _identifier(value: Any, error: str) -> str:
    text = _text(value, error, maximum=192)
    if _IDENTIFIER_RE.fullmatch(text) is None:
        _reject(error)
    return text


def _repository_namespace(value: Any, error: str) -> str:
    text = _text(value, error, maximum=201)
    if _REPOSITORY_NAMESPACE_RE.fullmatch(text) is None:
        _reject(error)
    return text


def _git_object(value: Any, error: str) -> str:
    if type(value) is not str or _GIT_OBJECT_RE.fullmatch(value) is None:
        _reject(error)
    return value


def _digest(value: Any, error: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        _reject(error)
    return value


def _timestamp(value: Any, error: str) -> datetime:
    if type(value) is not str or _TIMESTAMP_RE.fullmatch(value) is None:
        _reject(error)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        _reject(error)
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _reject(error)
    return parsed


def _non_negative_integer(value: Any, error: str) -> int:
    if type(value) is not int or value < 0:
        _reject(error)
    return value


def _metadata_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _metadata_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (*_metadata_identity(metadata), metadata.st_ctime_ns)


def _read_external_regular(path: Path, *, maximum_bytes: int, error: str) -> bytes:
    """Read one bounded, single-link regular file from one stable open handle."""

    try:
        supplied = Path(path)
        supplied_before = supplied.lstat()
        if (
            stat.S_ISLNK(supplied_before.st_mode)
            or not stat.S_ISREG(supplied_before.st_mode)
            or supplied_before.st_nlink != 1
            or supplied_before.st_size > maximum_bytes
        ):
            raise ValueError
        absolute = supplied.resolve(strict=True)
        descriptor = os.open(absolute, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            handle_before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(handle_before.st_mode)
                or handle_before.st_nlink != 1
                or _metadata_identity(handle_before) != _metadata_identity(supplied_before)
            ):
                raise ValueError
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(maximum_bytes + 1)
            handle_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        supplied_after = supplied.lstat()
        if (
            len(raw) > maximum_bytes
            or len(raw) != handle_after.st_size
            or _metadata_snapshot(handle_before) != _metadata_snapshot(handle_after)
            or _metadata_snapshot(supplied_before) != _metadata_snapshot(supplied_after)
            or _metadata_identity(supplied_after) != _metadata_identity(handle_after)
        ):
            raise ValueError
        return bytes(raw)
    except Exception:
        _reject(error)


def _package_snapshot(package: Path) -> dict[str, tuple[int, int, int, int, int, int, int]]:
    try:
        names = {item.name for item in package.iterdir()}
        if names != set(candidate.PACKAGE_FILES):
            raise ValueError
        snapshot: dict[str, tuple[int, int, int, int, int, int, int]] = {}
        for name in sorted(candidate.PACKAGE_FILES):
            metadata = (package / name).lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > _MAX_PACKAGE_MEMBER_BYTES
            ):
                raise ValueError
            snapshot[name] = _metadata_snapshot(metadata)
        return snapshot
    except Exception:
        _reject("candidate_package_custody_invalid")


def _require_pinned_manifest_member(
    manifest: Mapping[str, Any],
    *,
    name: str,
    raw: bytes,
) -> None:
    """Join a post-verification member read back to the externally pinned manifest."""

    members = manifest.get("members")
    if type(members) is not list:
        _reject("candidate_package_manifest_invalid")
    matches = [row for row in members if type(row) is dict and row.get("path") == name]
    if len(matches) != 1:
        _reject("candidate_package_manifest_member_invalid")
    row = matches[0]
    if (
        set(row) != {"byte_count", "path", "sha256"}
        or type(row.get("byte_count")) is not int
        or row["byte_count"] != len(raw)
        or row.get("sha256") != bytes_digest(raw)
    ):
        _reject("candidate_package_manifest_member_binding_mismatch")


def _contract_for_decision(
    packet: Mapping[str, Any], decision_id: str
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    smallest = packet.get("smallest_accountable_choice")
    direct = packet.get("detached_decision_receipt_contract")
    if type(smallest) is dict and smallest.get("decision_id") == decision_id and type(direct) is dict:
        required = direct.get("required_receipt_fields")
        allowed = direct.get("allowed_choices")
        if type(required) is list and type(allowed) is list:
            return dict(direct), tuple(required), tuple(allowed)

    two_stage = packet.get("two_stage_decision_contract")
    stage_b = two_stage.get("stage_b") if type(two_stage) is dict else None
    if type(stage_b) is dict and stage_b.get("decision_id") == decision_id:
        required = stage_b.get("required_receipt_fields")
        allowed = stage_b.get("options")
        if type(required) is list and type(allowed) is list:
            return dict(stage_b), tuple(required), tuple(allowed)
    _reject("decision_contract_not_found")


def _require_structural_signing_contract(
    packet: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    if packet.get("structural_signing_contract") != structural_signing_contract():
        _reject("structural_signing_contract_invalid")
    if contract.get("structural_signing_contract_ref") != SIGNING_CONTRACT_REFERENCE:
        _reject("decision_contract_signing_reference_invalid")


def _validate_receipt_shape(
    value: Mapping[str, Any],
    *,
    required_fields: tuple[str, ...],
    allowed_choices: tuple[str, ...],
) -> dict[str, Any]:
    receipt = dict(value)
    _exact_keys(receipt, {"schema", *required_fields}, "decision_receipt_field_set_invalid")
    if receipt["schema"] != DECISION_RECEIPT_SCHEMA:
        _reject("decision_receipt_schema_invalid")
    if any(receipt[field] is None for field in required_fields):
        _reject("decision_receipt_null_field")

    _text(receipt["accountable_principal"], "accountable_principal_invalid", maximum=512)
    _text(
        receipt["accountable_principal_organization"],
        "accountable_principal_organization_invalid",
        maximum=512,
    )
    _identifier(receipt["authority_id"], "authority_id_invalid")
    _identifier(receipt["decision_id"], "decision_id_invalid")
    _git_object(receipt["candidate_commit"], "candidate_commit_invalid")
    _git_object(receipt["candidate_tree"], "candidate_tree_invalid")
    _repository_namespace(receipt["repository_namespace"], "repository_namespace_invalid")
    _identifier(receipt["signer_key_id"], "signer_key_id_invalid")
    _identifier(receipt["signature_algorithm"], "signature_algorithm_invalid")
    _text(receipt["reason"], "reason_invalid", maximum=8192)
    _timestamp(receipt["issued_at"], "issued_at_invalid")
    if receipt["choice"] not in allowed_choices:
        _reject("decision_choice_not_allowed")

    for field, item in receipt.items():
        if field.endswith("_digest") or field.endswith("_sha256") or field == "detached_signature":
            _digest(item, "decision_receipt_digest_invalid")
        elif field.endswith("_high_water_mark"):
            _non_negative_integer(item, "decision_receipt_high_water_mark_invalid")
        elif field.endswith("_valid_until"):
            _timestamp(item, "decision_receipt_valid_until_invalid")

    if "receipt_valid_until" in receipt and _timestamp(receipt["issued_at"], "issued_at_invalid") >= _timestamp(
        receipt["receipt_valid_until"], "decision_receipt_valid_until_invalid"
    ):
        _reject("decision_receipt_time_range_invalid")
    return receipt


def normalized_decision_payload_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return a closed, non-circular canonical signing payload for the flat /1 receipt."""

    value = dict(receipt)
    if "payload_digest" not in value or "detached_signature" not in value:
        _reject("decision_receipt_self_binding_fields_missing")
    value["payload_digest"] = None
    value["detached_signature"] = None
    return canonical_json_bytes(
        {
            "receipt": value,
            "receipt_schema": DECISION_RECEIPT_SCHEMA,
            "schema": SIGNING_PAYLOAD_SCHEMA,
        }
    )


def decision_signing_material(signing_payload_raw: bytes) -> bytes:
    if type(signing_payload_raw) is not bytes:
        _reject("decision_payload_bytes_required")
    return SIGNING_DOMAIN + signing_payload_raw


def structural_signing_contract() -> dict[str, Any]:
    return {
        "canonical_encoding": "ATLAS_CANONICAL_JSON/1",
        "detached_signature_field_semantics": ("SHA256_OF_EXACT_RAW_DETACHED_SIGNATURE_ARTIFACT"),
        "payload_digest_algorithm": "SHA-256",
        "payload_digest_scope": "CANONICAL_SIGNING_PAYLOAD_BYTES_ONLY",
        "self_binding_null_fields": ["detached_signature", "payload_digest"],
        "signature_artifact_encoding": "OPAQUE_EXACT_BYTES",
        "signing_domain_hex": SIGNING_DOMAIN.hex(),
        "signing_material_construction": ("SIGNING_DOMAIN_BYTES_CONCAT_CANONICAL_SIGNING_PAYLOAD_BYTES"),
        "signing_payload_schema": SIGNING_PAYLOAD_SCHEMA,
        "structural_verification_effect": "NONE",
    }


def _external_artifact_fields(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            field
            for field in receipt
            if (field.endswith("_digest") or field.endswith("_sha256")) and field not in _INTERNALLY_BOUND_DIGEST_FIELDS
        )
    )


@dataclass(frozen=True, slots=True)
class BoundUnverifiedR2AuthorityDecisionReceipt:
    """Process-local structural binding that carries no decision authority."""

    authority_id: str
    decision_id: str
    declared_choice: str
    declared_signature_algorithm: str
    repository_namespace: str
    candidate_commit: str
    candidate_tree: str
    package_manifest_sha256: str
    source_freeze_sha256: str
    receipt_digest: str
    receipt_byte_count: int
    signing_payload_digest: str
    signing_material_digest: str
    subject_binding_digest: str
    signature_artifact_digest: str
    public_key_artifact_digest: str
    artifact_bindings_digest: str
    _artifact_bindings_raw: bytes
    _release_boundaries_raw: bytes
    _mint_authority: InitVar[object]

    def __post_init__(self, _mint_authority: object) -> None:
        if _mint_authority is not _BOUND_RECEIPT_AUTHORITY:
            raise TypeError(
                "BoundUnverifiedR2AuthorityDecisionReceipt requires the module construction "
                "token; class identity is not validation evidence"
            )
        if type(self._release_boundaries_raw) is not bytes:
            raise TypeError("release boundaries must remain exact canonical bytes")
        if type(self._artifact_bindings_raw) is not bytes:
            raise TypeError("artifact bindings must remain exact canonical bytes")

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_bindings": _parse_canonical_object(
                self._artifact_bindings_raw,
                "bound_artifact_bindings_invalid",
            ),
            "artifact_bindings_digest": self.artifact_bindings_digest,
            "authority_id": self.authority_id,
            "binding_evidence_scope": (
                "Recomputable content-binding output only; class identity and emitted JSON are "
                "not unforgeable proof that validation ran."
            ),
            "binding_status": "STRUCTURALLY_BOUND_EXTERNAL_AUTHORITY_UNVERIFIED",
            "candidate_commit": self.candidate_commit,
            "candidate_tree": self.candidate_tree,
            "claim_boundary": (
                "Exact canonical structure, candidate/package bytes, declared digest artifacts, "
                "and signing payload construction are bound. Signature validity and all external "
                "authority, policy, custody, revocation, trusted-time, separation, approval, "
                "selection, adequacy, runtime-closure, qualification, promotion, publication, "
                "GA, and Release 3 claims remain unevaluated."
            ),
            "decision_effect": "NONE",
            "declared_choice": self.declared_choice,
            "declared_signature_algorithm": self.declared_signature_algorithm,
            "decision_id": self.decision_id,
            "package_manifest_sha256": self.package_manifest_sha256,
            "public_key_artifact_digest": self.public_key_artifact_digest,
            "receipt_byte_count": self.receipt_byte_count,
            "receipt_digest": self.receipt_digest,
            "release_boundaries": _parse_canonical_object(
                self._release_boundaries_raw,
                "bound_release_boundaries_invalid",
            ),
            "repository_namespace": self.repository_namespace,
            "r2_auth_004_profile_status": "PROPOSED_UNAPPROVED",
            "schema": STRUCTURAL_BINDING_SCHEMA,
            "signature_artifact_digest": self.signature_artifact_digest,
            "signing_material_digest": self.signing_material_digest,
            "signing_payload_digest": self.signing_payload_digest,
            "source_freeze_sha256": self.source_freeze_sha256,
            "subject_binding_digest": self.subject_binding_digest,
            "unevaluated_external_domains": [
                "ACCOUNTABLE_PRINCIPAL_AND_ORGANIZATIONAL_AUTHORITY",
                "GOVERNING_POLICY_SELECTION_AND_CURRENTNESS",
                "SIGNATURE_ALGORITHM_KEY_AUTHORIZATION_AND_CRYPTOGRAPHIC_VALIDITY",
                "REVOCATION_STATUS_AND_HISTORY",
                "ISSUED_TIME_RECEIPT_LIFETIME_AND_TRUSTED_TIME",
                "KEY_CUSTODY_AND_REVIEWER_ORGANIZATIONAL_SEPARATION",
                "EFFECTIVE_RECEIPT_SELECTION_AND_CONFLICT_RESOLUTION",
            ],
            "filesystem_custody_scope": (
                "Cryptographic content identity at stable reads; continuous custody of the "
                "supplied filesystem path is not established."
            ),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())


def bind_unverified_r2_authority_decision_receipt_bytes(
    *,
    repository: Path,
    package: Path,
    expected_commit: str,
    expected_tree: str,
    expected_repository_namespace: str,
    expected_package_manifest_sha256: str,
    expected_source_freeze_sha256: str,
    authority_id: str,
    decision_id: str,
    receipt_raw: bytes,
    signature_artifact_raw: bytes,
    public_key_artifact_raw: bytes,
    artifact_raw_by_field: Mapping[str, bytes],
) -> BoundUnverifiedR2AuthorityDecisionReceipt:
    """Bind exact receipt inputs without evaluating or granting external authority."""

    expected_namespace = _repository_namespace(expected_repository_namespace, "expected_repository_namespace_invalid")
    authority = _identifier(authority_id, "expected_authority_id_invalid")
    decision = _identifier(decision_id, "expected_decision_id_invalid")
    expected_commit = _git_object(expected_commit, "expected_commit_invalid")
    expected_tree = _git_object(expected_tree, "expected_tree_invalid")
    expected_manifest_digest = _digest(expected_package_manifest_sha256, "expected_package_manifest_digest_invalid")
    expected_freeze_digest = _digest(expected_source_freeze_sha256, "expected_source_freeze_digest_invalid")

    if type(receipt_raw) is not bytes or not receipt_raw or len(receipt_raw) > _MAX_RECEIPT_BYTES:
        _reject("decision_receipt_bytes_invalid")
    if (
        type(signature_artifact_raw) is not bytes
        or not signature_artifact_raw
        or len(signature_artifact_raw) > _MAX_SIGNATURE_ARTIFACT_BYTES
    ):
        _reject("decision_signature_artifact_invalid")
    if (
        type(public_key_artifact_raw) is not bytes
        or not public_key_artifact_raw
        or len(public_key_artifact_raw) > _MAX_PUBLIC_KEY_ARTIFACT_BYTES
    ):
        _reject("decision_public_key_artifact_invalid")
    if type(artifact_raw_by_field) is not dict or any(
        type(raw) is not bytes or not raw or len(raw) > _MAX_EXTERNAL_ARTIFACT_BYTES
        for raw in artifact_raw_by_field.values()
    ):
        _reject("decision_artifact_bytes_invalid")
    if sum(len(raw) for raw in artifact_raw_by_field.values()) > _MAX_TOTAL_EXTERNAL_ARTIFACT_BYTES:
        _reject("decision_artifact_set_too_large")

    before = _package_snapshot(package)
    try:
        candidate.verify_package(
            repository,
            package,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
        )
    except (candidate.CandidatePackageError, OSError, ValueError):
        _reject("candidate_package_invalid")
    if _package_snapshot(package) != before:
        _reject("candidate_package_custody_invalid")

    packet_name = AUTHORITY_PACKET_FILES.get(authority)
    if packet_name is None:
        _reject("authority_packet_not_supported")
    package_manifest_raw = _read_external_regular(
        package / candidate.PACKAGE_MANIFEST,
        maximum_bytes=_MAX_PACKAGE_MEMBER_BYTES,
        error="candidate_package_custody_invalid",
    )
    source_freeze_raw = _read_external_regular(
        package / "source-freeze.json",
        maximum_bytes=_MAX_PACKAGE_MEMBER_BYTES,
        error="candidate_package_custody_invalid",
    )
    packet_raw = _read_external_regular(
        package / packet_name,
        maximum_bytes=_MAX_PACKAGE_MEMBER_BYTES,
        error="candidate_package_custody_invalid",
    )
    if _package_snapshot(package) != before:
        _reject("candidate_package_custody_invalid")

    package_manifest_digest = bytes_digest(package_manifest_raw)
    source_freeze_digest = bytes_digest(source_freeze_raw)
    if package_manifest_digest != expected_manifest_digest:
        _reject("candidate_package_manifest_pin_mismatch")
    if source_freeze_digest != expected_freeze_digest:
        _reject("candidate_source_freeze_pin_mismatch")

    package_manifest = _parse_canonical_object(
        package_manifest_raw,
        "candidate_package_manifest_invalid",
    )
    if package_manifest.get("schema") != candidate.PACKAGE_SCHEMA:
        _reject("candidate_package_v2_required")
    _require_pinned_manifest_member(
        package_manifest,
        name="source-freeze.json",
        raw=source_freeze_raw,
    )
    _require_pinned_manifest_member(
        package_manifest,
        name=packet_name,
        raw=packet_raw,
    )

    source_freeze = _parse_canonical_object(source_freeze_raw, "candidate_source_freeze_invalid")
    source = source_freeze.get("source")
    blobs = source.get("blobs") if type(source) is dict else None
    consumer_rows = (
        [row for row in blobs if type(row) is dict and row.get("path") == candidate.DECISION_CONSUMER_SOURCE_PATH]
        if type(blobs) is list
        else []
    )
    if len(consumer_rows) != 1:
        _reject("decision_consumer_source_binding_invalid")

    packet = _parse_canonical_object(packet_raw, "authority_packet_invalid")
    if packet.get("schema") != candidate.DECISION_PACKET_SCHEMA:
        _reject("authority_packet_v2_required")
    if packet.get("authority_id") != authority:
        _reject("authority_packet_id_mismatch")
    if packet.get("decision_consumption_state") != candidate.DECISION_CONSUMPTION_STATE:
        _reject("decision_consumption_state_invalid")
    if packet.get("decision_consumer") != {
        "binding_status": candidate.DECISION_CONSUMPTION_STATE,
        "consumer_source": consumer_rows[0],
        "decision_effect": "NONE",
        "result_schema": STRUCTURAL_BINDING_SCHEMA,
    }:
        _reject("decision_consumer_binding_invalid")
    contract, required_fields, allowed_choices = _contract_for_decision(packet, decision)
    if contract.get("receipt_schema") != DECISION_RECEIPT_SCHEMA:
        _reject("decision_contract_schema_invalid")
    _require_structural_signing_contract(packet, contract)
    if (
        not required_fields
        or len(required_fields) != len(set(required_fields))
        or any(type(field) is not str for field in required_fields)
    ):
        _reject("decision_contract_required_fields_invalid")
    if (
        not allowed_choices
        or len(allowed_choices) != len(set(allowed_choices))
        or any(type(choice) is not str for choice in allowed_choices)
    ):
        _reject("decision_contract_choices_invalid")

    receipt = _validate_receipt_shape(
        _parse_canonical_object(receipt_raw, "decision_receipt_not_canonical"),
        required_fields=required_fields,
        allowed_choices=allowed_choices,
    )
    if receipt["authority_id"] != authority or receipt["decision_id"] != decision:
        _reject("decision_receipt_id_binding_mismatch")
    if receipt["repository_namespace"] != expected_namespace:
        _reject("decision_receipt_repository_binding_mismatch")

    proposed = packet.get("proposed_candidate")
    if type(proposed) is not dict:
        _reject("authority_packet_candidate_binding_invalid")
    if (
        proposed.get("commit") != expected_commit
        or proposed.get("tree") != expected_tree
        or proposed.get("source_freeze_sha256") != expected_freeze_digest
    ):
        _reject("authority_packet_candidate_binding_invalid")
    expected_bindings = {
        "candidate_commit": expected_commit,
        "candidate_tree": expected_tree,
        "package_manifest_sha256": expected_manifest_digest,
        "source_freeze_sha256": expected_freeze_digest,
    }
    for field, expected in expected_bindings.items():
        if receipt[field] != expected:
            _reject("decision_receipt_candidate_binding_mismatch")

    signing_payload_raw = normalized_decision_payload_bytes(receipt)
    signing_payload_digest = bytes_digest(signing_payload_raw)
    if receipt["payload_digest"] != signing_payload_digest:
        _reject("decision_receipt_payload_digest_mismatch")

    if type(signature_artifact_raw) is not bytes or not signature_artifact_raw:
        _reject("decision_signature_artifact_invalid")
    if receipt["detached_signature"] != bytes_digest(signature_artifact_raw):
        _reject("decision_signature_artifact_binding_mismatch")
    if type(public_key_artifact_raw) is not bytes or not public_key_artifact_raw:
        _reject("decision_public_key_artifact_invalid")
    if receipt["public_key_digest"] != bytes_digest(public_key_artifact_raw):
        _reject("decision_public_key_artifact_binding_mismatch")

    required_artifacts = _external_artifact_fields(receipt)
    if type(artifact_raw_by_field) is not dict or set(artifact_raw_by_field) != set(required_artifacts):
        _reject("decision_artifact_field_set_invalid")
    artifact_bindings: dict[str, dict[str, Any]] = {
        "detached_signature": {
            "byte_count": len(signature_artifact_raw),
            "sha256": bytes_digest(signature_artifact_raw),
        },
        "public_key_digest": {
            "byte_count": len(public_key_artifact_raw),
            "sha256": bytes_digest(public_key_artifact_raw),
        },
    }
    for field in required_artifacts:
        raw = artifact_raw_by_field[field]
        if type(raw) is not bytes or not raw:
            _reject("decision_artifact_bytes_invalid")
        digest = bytes_digest(raw)
        if receipt[field] != digest:
            _reject("decision_artifact_digest_mismatch")
        artifact_bindings[field] = {
            "byte_count": len(raw),
            "sha256": digest,
        }

    if authority == "R2-AUTH-004" and decision == "R2-AUTH-004-D1":
        proposed_profile = packet.get("proposed_control_profile")
        if type(proposed_profile) is not dict:
            _reject("r2_auth_004_control_profile_invalid")
        expected_profile_raw = canonical_json_bytes(proposed_profile)
        if artifact_raw_by_field.get("control_profile_digest") != expected_profile_raw:
            _reject("r2_auth_004_control_profile_binding_mismatch")

    subject = {
        "authority_id": authority,
        "candidate_commit": expected_commit,
        "candidate_tree": expected_tree,
        "decision_id": decision,
        "package_manifest_sha256": expected_manifest_digest,
        "repository_namespace": expected_namespace,
        "schema": DECISION_SUBJECT_SCHEMA,
        "source_freeze_sha256": expected_freeze_digest,
    }
    signing_material = decision_signing_material(signing_payload_raw)
    artifact_bindings_raw = canonical_json_bytes(artifact_bindings)
    return BoundUnverifiedR2AuthorityDecisionReceipt(
        authority_id=authority,
        decision_id=decision,
        declared_choice=receipt["choice"],
        declared_signature_algorithm=receipt["signature_algorithm"],
        repository_namespace=expected_namespace,
        candidate_commit=expected_commit,
        candidate_tree=expected_tree,
        package_manifest_sha256=expected_manifest_digest,
        source_freeze_sha256=expected_freeze_digest,
        receipt_digest=bytes_digest(receipt_raw),
        receipt_byte_count=len(receipt_raw),
        signing_payload_digest=signing_payload_digest,
        signing_material_digest=bytes_digest(signing_material),
        subject_binding_digest=bytes_digest(canonical_json_bytes(subject)),
        signature_artifact_digest=bytes_digest(signature_artifact_raw),
        public_key_artifact_digest=bytes_digest(public_key_artifact_raw),
        artifact_bindings_digest=bytes_digest(artifact_bindings_raw),
        _artifact_bindings_raw=artifact_bindings_raw,
        _release_boundaries_raw=canonical_json_bytes(packet["release_boundaries"]),
        _mint_authority=_BOUND_RECEIPT_AUTHORITY,
    )


def _artifact_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            _reject("artifact_argument_invalid")
        field, raw_path = value.split("=", 1)
        if not field or field in result or not raw_path:
            _reject("artifact_argument_invalid")
        result[field] = Path(raw_path)
    return result


class _NonEchoingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        _reject("command_arguments_invalid")


def _command_parser() -> argparse.ArgumentParser:
    parser = _NonEchoingArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--repository-namespace", required=True)
    parser.add_argument("--package-manifest-sha256", required=True)
    parser.add_argument("--source-freeze-sha256", required=True)
    parser.add_argument("--authority-id", choices=tuple(AUTHORITY_PACKET_FILES), required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--signature-artifact", type=Path, required=True)
    parser.add_argument("--public-key-artifact", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="FIELD=PATH",
        help="exact raw bytes for every other externally referenced receipt digest field",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _command_parser().parse_args(argv)
        artifact_paths = _artifact_arguments(args.artifact)
        result = bind_unverified_r2_authority_decision_receipt_bytes(
            repository=args.repository,
            package=args.package,
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
            expected_repository_namespace=args.repository_namespace,
            expected_package_manifest_sha256=args.package_manifest_sha256,
            expected_source_freeze_sha256=args.source_freeze_sha256,
            authority_id=args.authority_id,
            decision_id=args.decision_id,
            receipt_raw=_read_external_regular(
                args.receipt,
                maximum_bytes=_MAX_RECEIPT_BYTES,
                error="decision_receipt_unavailable",
            ),
            signature_artifact_raw=_read_external_regular(
                args.signature_artifact,
                maximum_bytes=_MAX_SIGNATURE_ARTIFACT_BYTES,
                error="decision_signature_artifact_unavailable",
            ),
            public_key_artifact_raw=_read_external_regular(
                args.public_key_artifact,
                maximum_bytes=_MAX_PUBLIC_KEY_ARTIFACT_BYTES,
                error="decision_public_key_artifact_unavailable",
            ),
            artifact_raw_by_field={
                field: _read_external_regular(
                    path,
                    maximum_bytes=_MAX_EXTERNAL_ARTIFACT_BYTES,
                    error="decision_artifact_unavailable",
                )
                for field, path in artifact_paths.items()
            },
        )
    except AuthorityDecisionReceiptError as exc:
        print(f"REFUSED:{exc.code}", file=sys.stderr)
        return 2
    except OSError:
        print("REFUSED:decision_input_unavailable", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(result.canonical_bytes() + b"\n")
    return 0


__all__ = [
    "AUTHORITY_PACKET_FILES",
    "AuthorityDecisionReceiptError",
    "BoundUnverifiedR2AuthorityDecisionReceipt",
    "DECISION_RECEIPT_SCHEMA",
    "DECISION_SUBJECT_SCHEMA",
    "SIGNING_DOMAIN",
    "SIGNING_CONTRACT_REFERENCE",
    "SIGNING_PAYLOAD_SCHEMA",
    "STRUCTURAL_BINDING_SCHEMA",
    "bind_unverified_r2_authority_decision_receipt_bytes",
    "bytes_digest",
    "canonical_json_bytes",
    "decision_signing_material",
    "normalized_decision_payload_bytes",
    "structural_signing_contract",
]


if __name__ == "__main__":
    raise SystemExit(main())
