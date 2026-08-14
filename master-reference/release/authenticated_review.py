"""Authenticate an external review without mutating compiler or release facts.

The compiler owns immutable candidate subjects.  This module accepts exact
external bytes, verifies a purpose-bound detached Ed25519 signature against a
separately supplied trust policy and public key, and joins every signed row to
the current compiler bundle.  It deliberately has no key generation, network,
output-writing, gate-mutation, publication, or trust-discovery behavior.
"""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compiler_bundle import CompilerBundle
from .model import canonical_json, sha256_bytes
from .schema_validation import validate_release_object


CLAIM_PURPOSE = "consequential_claim_review"
CLAIM_SCHEMA_VERSION = "consequential-claim-review/1"
SIGNATURE_SCHEMA_VERSION = "authenticated-review-signature/1"
POLICY_SCHEMA_VERSION = "reviewer-key-policy/1"
RESULT_SCHEMA_VERSION = "authenticated-review-result/1"
CLAIM_REVIEWER_ROLE = "consequential_claim_verifier"

_SIGNATURE_DOMAIN = b"ATLAS-AUTHENTICATED-REVIEW\x00v1\x00"
_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
_MAX_SIGNATURE_BYTES = 4 * 1024
_MAX_POLICY_BYTES = 64 * 1024
_MAX_PUBLIC_KEY_BYTES = 16 * 1024
_FINGERPRINT_RE = re.compile(r"sha256:[0-9a-f]{64}")
_FIXED_ERROR_CODES = frozenset(
    {
        "authenticated_review_binding_mismatch",
        "authenticated_review_input_incomplete",
        "authenticated_review_input_invalid",
        "authenticated_review_key_not_trusted",
        "authenticated_review_payload_malformed",
        "authenticated_review_public_key_invalid",
        "authenticated_review_signature_invalid",
        "authenticated_review_signature_malformed",
        "authenticated_review_source_changed",
        "authenticated_review_subject_set_mismatch",
        "authenticated_review_trust_policy_malformed",
        "authenticated_review_verdict_incomplete",
    }
)


class AuthenticatedReviewError(RuntimeError):
    """A fixed, non-echoing authenticated-review failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReviewEvidenceBytes:
    """Exact external evidence bytes; ``None`` means the entire set is absent."""

    payload: bytes | None = None
    signature: bytes | None = None
    trust_policy: bytes | None = None
    trusted_public_key: bytes | None = None


@dataclass(frozen=True)
class AuthenticatedReviewResult:
    """Read-only receipt; verified review never promotes a compiler/release gate."""

    schema_version: str
    status: str
    purpose: str
    signature_verified: bool
    bounded_review_complete: bool
    current_gate_promoted: bool
    global_gate_closed: bool
    candidate_count: int
    passed_count: int
    blocked_count: int
    unresolved_count: int
    payload_sha256: str | None
    trust_policy_sha256: str | None
    signer_key_fingerprint: str | None
    claim_boundary: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _failure(code: str) -> AuthenticatedReviewError:
    return AuthenticatedReviewError(code)


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


def _read_external_regular(path: Path, *, maximum_bytes: int, failure_code: str) -> bytes:
    """Bound one external regular file to the same open handle and stable path."""

    try:
        supplied = Path(path)
        supplied_before = supplied.lstat()
        if stat.S_ISLNK(supplied_before.st_mode) or not stat.S_ISREG(supplied_before.st_mode):
            raise ValueError
        absolute = supplied.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        descriptor = os.open(absolute, flags)
        try:
            handle_before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(handle_before.st_mode)
                or _metadata_identity(supplied_before) != _metadata_identity(handle_before)
                or handle_before.st_size > maximum_bytes
            ):
                raise ValueError
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                value = stream.read(maximum_bytes + 1)
            handle_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        supplied_after = supplied.lstat()
        if (
            len(value) > maximum_bytes
            or len(value) != handle_after.st_size
            or _metadata_snapshot(handle_before) != _metadata_snapshot(handle_after)
            or _metadata_snapshot(supplied_before) != _metadata_snapshot(supplied_after)
            or _metadata_identity(supplied_after) != _metadata_identity(handle_after)
        ):
            raise ValueError
        return bytes(value)
    except Exception:
        raise _failure(failure_code) from None


def read_review_evidence_files(
    payload_path: Path,
    signature_path: Path,
    trust_policy_path: Path,
    trusted_public_key_path: Path,
) -> ReviewEvidenceBytes:
    """Read the four separately supplied inputs with bounded same-handle custody."""

    return ReviewEvidenceBytes(
        payload=_read_external_regular(
            payload_path,
            maximum_bytes=_MAX_PAYLOAD_BYTES,
            failure_code="authenticated_review_payload_unavailable",
        ),
        signature=_read_external_regular(
            signature_path,
            maximum_bytes=_MAX_SIGNATURE_BYTES,
            failure_code="authenticated_review_signature_unavailable",
        ),
        trust_policy=_read_external_regular(
            trust_policy_path,
            maximum_bytes=_MAX_POLICY_BYTES,
            failure_code="authenticated_review_trust_policy_unavailable",
        ),
        trusted_public_key=_read_external_regular(
            trusted_public_key_path,
            maximum_bytes=_MAX_PUBLIC_KEY_BYTES,
            failure_code="authenticated_review_public_key_unavailable",
        ),
    )


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_number(_value: str) -> None:
    raise ValueError


def _canonical_object(
    repo_root: Path,
    raw: bytes,
    *,
    schema_name: str,
    maximum_bytes: int,
    failure_code: str,
) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        raise _failure(failure_code)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
        if type(value) is not dict or raw != canonical_json(value):
            raise ValueError
        validate_release_object(repo_root, schema_name, value)
    except Exception:
        raise _failure(failure_code) from None
    return value


def _load_ed25519_public_key(value: bytes) -> tuple[Any, bytes]:
    if type(value) is not bytes or not value or len(value) > _MAX_PUBLIC_KEY_BYTES:
        raise _failure("authenticated_review_public_key_invalid")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        key = None
        for loader in (serialization.load_pem_public_key, serialization.load_ssh_public_key):
            try:
                candidate = loader(value)
            except (TypeError, ValueError):
                continue
            if isinstance(candidate, Ed25519PublicKey):
                key = candidate
                break
        if key is None:
            raise ValueError
        raw = key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        if len(raw) != 32:
            raise ValueError
        return key, raw
    except AuthenticatedReviewError:
        raise
    except Exception:
        raise _failure("authenticated_review_public_key_invalid") from None


def _signed_material(payload: bytes, policy_digest: str) -> bytes:
    return (
        _SIGNATURE_DOMAIN
        + CLAIM_PURPOSE.encode("ascii")
        + b"\x00"
        + CLAIM_SCHEMA_VERSION.encode("ascii")
        + b"\x00"
        + policy_digest.encode("ascii")
        + b"\x00"
        + payload
    )


def consequential_claim_review_signing_material(
    repo_root: Path,
    payload: bytes,
    trust_policy: bytes,
) -> bytes:
    """Build the exact domain-separated bytes an external reviewer signs."""

    if type(payload) is not bytes or type(trust_policy) is not bytes:
        raise _failure("authenticated_review_input_invalid")
    _canonical_object(
        repo_root,
        bytes(payload),
        schema_name="consequential-claim-review",
        maximum_bytes=_MAX_PAYLOAD_BYTES,
        failure_code="authenticated_review_payload_malformed",
    )
    _canonical_object(
        repo_root,
        bytes(trust_policy),
        schema_name="reviewer-key-policy",
        maximum_bytes=_MAX_POLICY_BYTES,
        failure_code="authenticated_review_trust_policy_malformed",
    )
    return _signed_material(bytes(payload), sha256_bytes(bytes(trust_policy)))


def _policy_authorizes(
    policy: Mapping[str, Any],
    *,
    fingerprint: str,
) -> bool:
    keys = policy.get("keys")
    if type(keys) is not list:
        return False
    fingerprints = [item.get("public_key_fingerprint") for item in keys if type(item) is dict]
    if len(fingerprints) != len(keys) or len(fingerprints) != len(set(fingerprints)):
        return False
    matches = [item for item in keys if item.get("public_key_fingerprint") == fingerprint]
    if len(matches) != 1:
        return False
    authority = matches[0]
    authorizations = authority.get("authorizations")
    if type(authorizations) is not list:
        return False
    normalized = [
        (item.get("purpose"), item.get("target_schema_version"), item.get("reviewer_role"))
        for item in authorizations
        if type(item) is dict
    ]
    if len(normalized) != len(authorizations) or len(normalized) != len(set(normalized)):
        return False
    return bool(
        authority.get("reviewer_kind") == "independent_agent"
        and authority.get("independent_from_proposer") is True
        and (CLAIM_PURPOSE, CLAIM_SCHEMA_VERSION, CLAIM_REVIEWER_ROLE) in normalized
    )


def _verify_detached_signature(
    repo_root: Path,
    payload_raw: bytes,
    signature_raw: bytes,
    policy_raw: bytes,
    public_key_raw: bytes,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    payload = _canonical_object(
        repo_root,
        payload_raw,
        schema_name="consequential-claim-review",
        maximum_bytes=_MAX_PAYLOAD_BYTES,
        failure_code="authenticated_review_payload_malformed",
    )
    signature = _canonical_object(
        repo_root,
        signature_raw,
        schema_name="authenticated-review-signature",
        maximum_bytes=_MAX_SIGNATURE_BYTES,
        failure_code="authenticated_review_signature_malformed",
    )
    policy = _canonical_object(
        repo_root,
        policy_raw,
        schema_name="reviewer-key-policy",
        maximum_bytes=_MAX_POLICY_BYTES,
        failure_code="authenticated_review_trust_policy_malformed",
    )
    payload_digest = sha256_bytes(payload_raw)
    policy_digest = sha256_bytes(policy_raw)
    if (
        signature.get("purpose") != CLAIM_PURPOSE
        or signature.get("target_schema_version") != CLAIM_SCHEMA_VERSION
        or signature.get("target_sha256") != payload_digest
        or signature.get("trust_policy_sha256") != policy_digest
    ):
        raise _failure("authenticated_review_binding_mismatch")
    key, raw_key = _load_ed25519_public_key(public_key_raw)
    fingerprint = f"sha256:{sha256_bytes(raw_key)}"
    if (
        signature.get("signer_key_fingerprint") != fingerprint
        or not _FINGERPRINT_RE.fullmatch(fingerprint)
        or not _policy_authorizes(policy, fingerprint=fingerprint)
    ):
        raise _failure("authenticated_review_key_not_trusted")
    try:
        encoded = signature.get("signature_base64")
        if type(encoded) is not str:
            raise ValueError
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != encoded:
            raise ValueError
        key.verify(decoded, _signed_material(payload_raw, policy_digest))
    except Exception:
        raise _failure("authenticated_review_signature_invalid") from None
    return payload, policy, fingerprint


def _candidate_rows(
    bundle: CompilerBundle,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str, str]:
    source_commit = bundle.source_commit
    source_tree_digest = bundle.source_tree_digest
    candidates = bundle.records.get("consequential_claim_facets")
    summary = bundle.completeness.get("consequential_claim_denominator")
    if type(candidates) is not list or type(summary) is not dict or not candidates:
        raise _failure("authenticated_review_subject_set_mismatch")
    try:
        snapshot_raw = canonical_json(
            {
                "source_commit": source_commit,
                "source_tree_digest": source_tree_digest,
                "summary": summary,
                "candidates": candidates,
            }
        )
        snapshot = json.loads(snapshot_raw.decode("utf-8", errors="strict"))
        cloned = snapshot["candidates"]
        cloned_summary = snapshot["summary"]
    except Exception:
        raise _failure("authenticated_review_subject_set_mismatch") from None
    facet_ids = [candidate.get("facet_id") for candidate in cloned]
    if any(type(item) is not str for item in facet_ids):
        raise _failure("authenticated_review_subject_set_mismatch")
    if len(facet_ids) != len(set(facet_ids)):
        raise _failure("authenticated_review_subject_set_mismatch")
    cloned.sort(key=lambda candidate: candidate["facet_id"])
    return cloned, cloned_summary, source_commit, source_tree_digest, sha256_bytes(snapshot_raw)


def _validated_result(
    repo_root: Path,
    result: AuthenticatedReviewResult,
) -> AuthenticatedReviewResult:
    try:
        if result.passed_count + result.blocked_count + result.unresolved_count != result.candidate_count:
            raise ValueError
        if result.status == "absent" and result.unresolved_count != result.candidate_count:
            raise ValueError
        if result.status == "verified_complete_not_promoted" and result.passed_count != result.candidate_count:
            raise ValueError
        if result.status == "verified_blocked_not_promoted" and not (
            result.blocked_count or result.unresolved_count
        ):
            raise ValueError
        validate_release_object(repo_root, "authenticated-review-result", result.as_dict())
    except Exception:
        raise _failure("authenticated_review_unexpected") from None
    return result


def _validate_claim_join(
    candidates: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    source_commit: str,
    source_tree_digest: str,
    payload: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    records = payload.get("records")
    if type(records) is not list or len(records) != len(candidates):
        raise _failure("authenticated_review_subject_set_mismatch")
    expected_binding = {
        "source_commit": source_commit,
        "source_tree_digest": source_tree_digest,
        "contract_path": summary.get("contract_path"),
        "subject_contract_version": summary.get("schema_version"),
        "contract_git_blob_oid": summary.get("contract_git_blob_oid"),
        "contract_digest": summary.get("contract_digest"),
        "classification_digest": summary.get("classification_digest"),
        "source_receipts_digest": summary.get("source_receipts_digest"),
        "candidate_set_digest": summary.get("candidate_set_digest"),
    }
    if any(payload.get(key) != value for key, value in expected_binding.items()):
        raise _failure("authenticated_review_binding_mismatch")
    if payload.get("candidate_count") != len(candidates):
        raise _failure("authenticated_review_subject_set_mismatch")
    expected_rows = []
    for candidate, record in zip(candidates, records, strict=True):
        if type(record) is not dict:
            raise _failure("authenticated_review_subject_set_mismatch")
        expected_rows.append(
            {
                "facet_id": candidate.get("facet_id"),
                "subject_digest": sha256_bytes(canonical_json(candidate)),
                "value_digest": candidate.get("value_digest"),
                "grounding_digest": candidate.get("grounding_digest"),
            }
        )
    actual_identity = [
        {
            "facet_id": record.get("facet_id"),
            "subject_digest": record.get("subject_digest"),
            "value_digest": record.get("value_digest"),
            "grounding_digest": record.get("grounding_digest"),
        }
        for record in records
        if type(record) is dict
    ]
    if actual_identity != expected_rows:
        raise _failure("authenticated_review_subject_set_mismatch")
    if payload.get("records_digest") != sha256_bytes(canonical_json(records)):
        raise _failure("authenticated_review_subject_set_mismatch")
    verdicts = [record.get("verdict") for record in records]
    passed = verdicts.count("pass")
    blocked = verdicts.count("block")
    unresolved = verdicts.count("abstain")
    if passed + blocked + unresolved != len(records):
        raise _failure("authenticated_review_verdict_incomplete")
    return len(candidates), passed, blocked, unresolved


def verify_consequential_claim_review(
    repo_root: Path,
    bundle: CompilerBundle,
    evidence: ReviewEvidenceBytes,
) -> AuthenticatedReviewResult:
    """Verify exact external review evidence without promoting any current gate."""

    try:
        if type(evidence) is not ReviewEvidenceBytes:
            raise _failure("authenticated_review_input_invalid")
        raw_parts = (
            evidence.payload,
            evidence.signature,
            evidence.trust_policy,
            evidence.trusted_public_key,
        )
        if any(part is not None and type(part) is not bytes for part in raw_parts):
            raise _failure("authenticated_review_input_invalid")
        cloned = ReviewEvidenceBytes(
            payload=None if evidence.payload is None else bytes(evidence.payload),
            signature=None if evidence.signature is None else bytes(evidence.signature),
            trust_policy=None if evidence.trust_policy is None else bytes(evidence.trust_policy),
            trusted_public_key=(
                None if evidence.trusted_public_key is None else bytes(evidence.trusted_public_key)
            ),
        )
        parts = (
            cloned.payload,
            cloned.signature,
            cloned.trust_policy,
            cloned.trusted_public_key,
        )
        all_absent = all(part is None for part in parts)
        if not all_absent and any(part is None for part in parts):
            raise _failure("authenticated_review_input_incomplete")
        if type(bundle) is not CompilerBundle:
            raise _failure("authenticated_review_input_invalid")
        candidates, summary, source_commit, source_tree_digest, snapshot_digest = _candidate_rows(bundle)
        if all_absent:
            return _validated_result(repo_root, AuthenticatedReviewResult(
                schema_version=RESULT_SCHEMA_VERSION,
                status="absent",
                purpose=CLAIM_PURPOSE,
                signature_verified=False,
                bounded_review_complete=False,
                current_gate_promoted=False,
                global_gate_closed=False,
                candidate_count=len(candidates),
                passed_count=0,
                blocked_count=0,
                unresolved_count=len(candidates),
                payload_sha256=None,
                trust_policy_sha256=None,
                signer_key_fingerprint=None,
                claim_boundary=(
                    "External evidence is absent; immutable compiler counts and every global, sink, "
                    "signature, recovery, and publication gate remain unchanged."
                ),
            ))
        assert cloned.payload is not None
        assert cloned.signature is not None
        assert cloned.trust_policy is not None
        assert cloned.trusted_public_key is not None
        payload, _policy, fingerprint = _verify_detached_signature(
            repo_root,
            cloned.payload,
            cloned.signature,
            cloned.trust_policy,
            cloned.trusted_public_key,
        )
        candidate_count, passed, blocked, unresolved = _validate_claim_join(
            candidates,
            summary,
            source_commit,
            source_tree_digest,
            payload,
        )
        if _candidate_rows(bundle)[-1] != snapshot_digest:
            raise _failure("authenticated_review_source_changed")
        complete = passed == candidate_count and blocked == 0 and unresolved == 0
        return _validated_result(repo_root, AuthenticatedReviewResult(
            schema_version=RESULT_SCHEMA_VERSION,
            status="verified_complete_not_promoted" if complete else "verified_blocked_not_promoted",
            purpose=CLAIM_PURPOSE,
            signature_verified=True,
            bounded_review_complete=complete,
            current_gate_promoted=False,
            global_gate_closed=False,
            candidate_count=candidate_count,
            passed_count=passed,
            blocked_count=blocked,
            unresolved_count=unresolved,
            payload_sha256=sha256_bytes(cloned.payload),
            trust_policy_sha256=sha256_bytes(cloned.trust_policy),
            signer_key_fingerprint=fingerprint,
            claim_boundary=(
                "Signature and exact bounded-subject joins verified. Compiler facts are immutable; "
                "rendered-sink, global-universe, release, recovery, and publication gates remain separate."
            ),
        ))
    except AuthenticatedReviewError as exc:
        raw_code = exc.code if type(exc) is AuthenticatedReviewError else None
        code = (
            raw_code
            if type(raw_code) is str and raw_code in _FIXED_ERROR_CODES
            else "authenticated_review_unexpected"
        )
        raise _failure(code) from None
    except Exception:
        raise _failure("authenticated_review_unexpected") from None
