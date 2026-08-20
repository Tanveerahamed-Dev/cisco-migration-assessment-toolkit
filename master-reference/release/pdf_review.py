"""Authenticate detached PDF visual-review evidence without promotion.

The release family remains immutable and continues to own its pending/BLOCK
state.  This module verifies a separately supplied, purpose-bound Ed25519
review against the exact generated PDF family and emits only a detached
non-promoting receipt.  It deliberately has no key generation, trust
discovery, network, family-writing, gate-mutation, signing, or publication
behavior.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .model import canonical_json, sha256_bytes
from .schema_validation import validate_release_object


PDF_REVIEW_PURPOSE = "pdf_visual_review"
PDF_REVIEW_SCHEMA_VERSION = "pdf-review/1"
PDF_REVIEW_SIGNATURE_SCHEMA_VERSION = "pdf-review-signature/1"
PDF_REVIEW_POLICY_SCHEMA_VERSION = "pdf-reviewer-key-policy/1"
PDF_REVIEW_RESULT_SCHEMA_VERSION = "pdf-review-result/1"
PDF_REVIEWER_ROLE = "pdf_visual_verifier"

_PDF_REVIEW_SIGNATURE_DOMAIN = b"ATLAS-PDF-REVIEW\x00v1\x00"
_PDF_PATH = "master-reference.pdf"
_MANIFEST_NAME = "release-manifest.json"
_ATTESTATION_PATH = "family-attestation.json"
_PDF_GATE_PATH = "pdf-gate.json"
_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
_MAX_SIGNATURE_BYTES = 4 * 1024
_MAX_POLICY_BYTES = 64 * 1024
_MAX_PUBLIC_KEY_BYTES = 16 * 1024
_MAX_FAMILY_JSON_BYTES = 32 * 1024 * 1024
_MAX_PDF_BYTES = 64 * 1024 * 1024
_MAX_FAMILY_ARTIFACTS = 256
_MAX_FAMILY_ENTRIES = 512
_MAX_FAMILY_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
_MAX_FAMILY_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
_MAX_FAMILY_PATH_BYTES = 1024
_STREAM_CHUNK_BYTES = 1024 * 1024
_FINGERPRINT_RE = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")

PDF_REVIEW_ERROR_CODES = frozenset(
    {
        "pdf_review_binding_mismatch",
        "pdf_review_family_changed",
        "pdf_review_family_invalid",
        "pdf_review_input_changed",
        "pdf_review_input_incomplete",
        "pdf_review_input_invalid",
        "pdf_review_key_not_trusted",
        "pdf_review_payload_malformed",
        "pdf_review_payload_unavailable",
        "pdf_review_public_key_invalid",
        "pdf_review_public_key_unavailable",
        "pdf_review_result_invalid",
        "pdf_review_signature_invalid",
        "pdf_review_signature_malformed",
        "pdf_review_signature_unavailable",
        "pdf_review_subject_mismatch",
        "pdf_review_trust_policy_malformed",
        "pdf_review_trust_policy_unavailable",
        "pdf_review_unexpected",
        "pdf_review_verdict_inconsistent",
    }
)

_VERIFICATION_BOUNDARY = (
    "The signed full-document visual review is verified against one immutable generated PDF "
    "family. No current gate is promoted; owner-manifest signature, accessibility, binary "
    "privacy, global closure, recovery, and publication authority remain separate."
)

_REVIEW_EVIDENCE_FIELDS = (
    "release_manifest_sha256",
    "pdf_sha256",
    "pdf_page_count",
    "render_profile_digest",
    "page_reviews_digest",
    "rendered_page_count",
    "reviewed_page_count",
    "passed_page_count",
    "blocked_page_count",
    "checks_digest",
    "verdict",
    "accessibility_disposition",
    "binary_privacy_disposition",
)


class PdfReviewError(RuntimeError):
    """A fixed, non-echoing PDF-review failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PdfReviewEvidenceBytes:
    """The four exact external inputs needed to authenticate one review."""

    payload: bytes | None = None
    signature: bytes | None = None
    trust_policy: bytes | None = None
    trusted_public_key: bytes | None = None


@dataclass(frozen=True)
class PdfReviewSubject:
    """Digest-only identity of one verified immutable generated-PDF family."""

    manifest_path: Path
    source_commit: str
    head_tree_oid: str
    index_digest: str
    source_tree_digest: str
    release_manifest_sha256: str
    family_attestation_sha256: str
    pdf_gate_sha256: str
    pdf_path: str
    pdf_sha256: str
    pdf_bytes: int
    pdf_page_count: int
    pdf_input_digest: str
    release_status: str
    publication_status: str
    family_independent_verification_verdict: str
    pdf_gate_status: str
    pdf_gate_independent_verification_verdict: str


@dataclass(frozen=True)
class PdfReviewResult:
    """Detached receipt whose boundary flags cannot promote the release family."""

    schema_version: str
    status: str
    purpose: str
    signature_verified: bool
    family_integrity_verified: bool
    pdf_subject_verified: bool
    visual_review_complete: bool
    visual_review_passed: bool
    current_gate_promoted: bool
    global_gate_closed: bool
    release_family_mutated: bool
    owner_manifest_signature_verified: bool
    accessibility_review_established: bool
    binary_privacy_review_established: bool
    publication_authority_granted: bool
    source_commit: str
    head_tree_oid: str
    index_digest: str
    source_tree_digest: str
    release_manifest_sha256: str
    family_attestation_sha256: str
    pdf_gate_sha256: str
    pdf_path: str
    pdf_sha256: str
    pdf_bytes: int
    pdf_page_count: int
    pdf_input_digest: str
    release_status: str
    publication_status: str
    family_independent_verification_verdict: str
    pdf_gate_status: str
    pdf_gate_independent_verification_verdict: str
    payload_sha256: str
    trust_policy_sha256: str
    signer_key_fingerprint: str
    render_profile_digest: str
    page_reviews_digest: str
    rendered_page_count: int
    reviewed_page_count: int
    passed_page_count: int
    blocked_page_count: int
    checks_digest: str
    review_evidence_sha256: str
    verification_boundary: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _RegularSnapshot:
    bytes: int
    sha256: str
    metadata: tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True)
class _FamilySnapshot:
    root: Path
    files: tuple[str, ...]
    regular: tuple[tuple[str, _RegularSnapshot], ...]
    root_metadata: tuple[int, int, int, int, int, int, int]


def _failure(code: str) -> PdfReviewError:
    return PdfReviewError(code)


def normalize_pdf_review_error(exc: BaseException) -> str:
    """Return only a public fixed code; subclasses and unknown values collapse."""

    if type(exc) is PdfReviewError and exc.code in PDF_REVIEW_ERROR_CODES:
        return exc.code
    return "pdf_review_unexpected"


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


def _is_reparse(metadata: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & marker
    )


def _direct_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _read_external_regular(path: Path, *, maximum_bytes: int, failure_code: str) -> bytes:
    """Read one bounded regular file through a stable same-object handle."""

    try:
        supplied = _direct_absolute(path)
        supplied_before = supplied.lstat()
        if _is_reparse(supplied_before) or not stat.S_ISREG(supplied_before.st_mode):
            raise ValueError
        descriptor = os.open(
            supplied,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
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


def _stream_external_regular(
    path: Path,
    *,
    maximum_bytes: int,
    expected_bytes: int,
    failure_code: str,
) -> _RegularSnapshot:
    """Hash one bounded regular file without materializing it in memory."""

    try:
        supplied = _direct_absolute(path)
        supplied_before = supplied.lstat()
        if _is_reparse(supplied_before) or not stat.S_ISREG(supplied_before.st_mode):
            raise ValueError
        if supplied_before.st_size != expected_bytes or expected_bytes > maximum_bytes:
            raise ValueError
        descriptor = os.open(
            supplied,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            handle_before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(handle_before.st_mode)
                or _metadata_identity(supplied_before) != _metadata_identity(handle_before)
                or handle_before.st_size != expected_bytes
            ):
                raise ValueError
            digest = hashlib.sha256()
            consumed = 0
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while True:
                    chunk = stream.read(_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > maximum_bytes or consumed > expected_bytes:
                        raise ValueError
                    digest.update(chunk)
            handle_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        supplied_after = supplied.lstat()
        if (
            consumed != expected_bytes
            or consumed != handle_after.st_size
            or _metadata_snapshot(handle_before) != _metadata_snapshot(handle_after)
            or _metadata_snapshot(supplied_before) != _metadata_snapshot(supplied_after)
            or _metadata_identity(supplied_after) != _metadata_identity(handle_after)
        ):
            raise ValueError
        return _RegularSnapshot(
            bytes=consumed,
            sha256=digest.hexdigest(),
            metadata=_metadata_snapshot(supplied_after),
        )
    except Exception:
        raise _failure(failure_code) from None


def _safe_family_relative(value: Any) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > _MAX_FAMILY_PATH_BYTES:
        raise _failure("pdf_review_family_invalid")
    path = PurePosixPath(value)
    if (
        "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or path.as_posix() != value
        or len(path.parts) != 1
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise _failure("pdf_review_family_invalid")
    return value


def _family_census(root: Path) -> tuple[tuple[str, ...], tuple[int, int, int, int, int, int, int]]:
    try:
        root = _direct_absolute(root)
        root_before = root.lstat()
        if _is_reparse(root_before) or not stat.S_ISDIR(root_before.st_mode):
            raise ValueError
        files: list[str] = []
        casefolded: set[str] = set()
        entry_count = 0
        with os.scandir(root) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > _MAX_FAMILY_ENTRIES:
                    raise ValueError
                metadata = entry.stat(follow_symlinks=False)
                if _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
                    raise ValueError
                relative = _safe_family_relative(entry.name)
                folded = relative.casefold()
                if folded in casefolded:
                    raise ValueError
                casefolded.add(folded)
                files.append(relative)
        root_after = root.lstat()
        if _metadata_snapshot(root_before) != _metadata_snapshot(root_after):
            raise ValueError
        return tuple(sorted(files)), _metadata_snapshot(root_after)
    except PdfReviewError:
        raise
    except Exception:
        raise _failure("pdf_review_family_invalid") from None


def _assert_family_stable(snapshot: _FamilySnapshot) -> None:
    files, root_metadata = _family_census(snapshot.root)
    if files != snapshot.files or root_metadata != snapshot.root_metadata:
        raise _failure("pdf_review_family_changed")
    for relative, expected in snapshot.regular:
        try:
            metadata = (snapshot.root / relative).lstat()
            if (
                _is_reparse(metadata)
                or not stat.S_ISREG(metadata.st_mode)
                or _metadata_snapshot(metadata) != expected.metadata
            ):
                raise ValueError
        except Exception:
            raise _failure("pdf_review_family_changed") from None


def _verify_bounded_family(
    repo_root: Path,
    manifest_path: Path,
    manifest_raw: bytes,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], _FamilySnapshot]:
    """Verify the exact generated family with bounded streaming custody."""

    try:
        if type(manifest) is not dict:
            raise ValueError
        artifacts = manifest.get("artifacts")
        if (
            type(artifacts) is not list
            or not 1 <= len(artifacts) <= _MAX_FAMILY_ARTIFACTS
        ):
            raise ValueError
        normalized: list[dict[str, Any]] = []
        paths: set[str] = set()
        total_bytes = 0
        for row in artifacts:
            if type(row) is not dict:
                raise ValueError
            relative = _safe_family_relative(row.get("path"))
            size = row.get("bytes")
            digest = row.get("sha256")
            if (
                relative in paths
                or type(size) is not int
                or type(size) is bool
                or not 0 <= size <= _MAX_FAMILY_ARTIFACT_BYTES
                or type(digest) is not str
                or _DIGEST_RE.fullmatch(digest) is None
            ):
                raise ValueError
            paths.add(relative)
            total_bytes += size
            if total_bytes > _MAX_FAMILY_TOTAL_BYTES:
                raise ValueError
            normalized.append(row)
        if normalized != sorted(normalized, key=lambda row: row["path"]):
            raise ValueError
        validate_release_object(repo_root, "release-manifest", manifest)

        absolute_manifest = _direct_absolute(manifest_path)
        family_root = absolute_manifest.parent
        actual_files, root_metadata = _family_census(family_root)
        expected_files = tuple(sorted(paths | {_MANIFEST_NAME}))
        if actual_files != expected_files:
            raise ValueError
        signing = manifest.get("signing")
        if (
            type(signing) is not dict
            or signing.get("signature_target") != _MANIFEST_NAME
            or signing.get("signature_envelope") != "release-manifest.sig.json"
        ):
            raise ValueError

        snapshots: dict[str, _RegularSnapshot] = {}
        manifest_metadata = absolute_manifest.lstat()
        if _is_reparse(manifest_metadata) or not stat.S_ISREG(manifest_metadata.st_mode):
            raise ValueError
        snapshots[_MANIFEST_NAME] = _RegularSnapshot(
            bytes=len(manifest_raw),
            sha256=sha256_bytes(manifest_raw),
            metadata=_metadata_snapshot(manifest_metadata),
        )
        for row in normalized:
            relative = row["path"]
            current = _stream_external_regular(
                family_root / relative,
                maximum_bytes=_MAX_FAMILY_ARTIFACT_BYTES,
                expected_bytes=row["bytes"],
                failure_code="pdf_review_family_invalid",
            )
            if current.sha256 != row["sha256"]:
                raise ValueError
            snapshots[relative] = current

        inventory_raw = _read_external_regular(
            family_root / "artifact-inventory.json",
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        inventory = _canonical_object(
            inventory_raw,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        inventory_rows = inventory.get("artifacts")
        if type(inventory_rows) is not list or len(inventory_rows) > _MAX_FAMILY_ARTIFACTS:
            raise ValueError
        validate_release_object(repo_root, "artifact-inventory", inventory)
        binding = manifest.get("source_binding")
        if type(binding) is not dict:
            raise ValueError
        intended_inventory = [
            row for row in normalized if row["path"] != "artifact-inventory.json"
        ]
        if (
            inventory.get("source_commit") != binding.get("source_commit")
            or inventory.get("source_tree_digest") != binding.get("source_tree_digest")
            or inventory.get("status") != manifest.get("release_status")
            or inventory_rows != intended_inventory
            or inventory.get("self_exclusions")
            != ["artifact-inventory.json", _MANIFEST_NAME, "release-manifest.sig.json"]
        ):
            raise ValueError
        return (
            {
                "artifacts_verified": len(normalized),
                "source_commit": binding.get("source_commit"),
                "source_tree_digest": binding.get("source_tree_digest"),
                "release_status": manifest.get("release_status"),
            },
            _FamilySnapshot(
                root=family_root,
                files=actual_files,
                regular=tuple(sorted(snapshots.items())),
                root_metadata=root_metadata,
            ),
        )
    except PdfReviewError:
        raise
    except Exception:
        raise _failure("pdf_review_family_invalid") from None


def read_pdf_review_evidence_files(
    payload_path: Path,
    signature_path: Path,
    trust_policy_path: Path,
    trusted_public_key_path: Path,
    *,
    forbidden_root: Path | None = None,
) -> PdfReviewEvidenceBytes:
    """Read the four independently supplied inputs with bounded custody."""

    def read_one(path: Path, maximum_bytes: int, failure_code: str) -> bytes:
        try:
            if forbidden_root is not None:
                root = _direct_absolute(forbidden_root).resolve(strict=True)
                supplied = _direct_absolute(path).resolve(strict=True)
                if supplied == root or root in supplied.parents:
                    raise _failure(failure_code)
            value = _read_external_regular(
                path,
                maximum_bytes=maximum_bytes,
                failure_code=failure_code,
            )
            if forbidden_root is not None:
                root_after = _direct_absolute(forbidden_root).resolve(strict=True)
                supplied_after = _direct_absolute(path).resolve(strict=True)
                if root_after != root or supplied_after != supplied or root_after in supplied_after.parents:
                    raise _failure(failure_code)
            return value
        except PdfReviewError:
            raise
        except Exception:
            raise _failure(failure_code) from None

    return PdfReviewEvidenceBytes(
        payload=read_one(
            payload_path,
            _MAX_PAYLOAD_BYTES,
            "pdf_review_payload_unavailable",
        ),
        signature=read_one(
            signature_path,
            _MAX_SIGNATURE_BYTES,
            "pdf_review_signature_unavailable",
        ),
        trust_policy=read_one(
            trust_policy_path,
            _MAX_POLICY_BYTES,
            "pdf_review_trust_policy_unavailable",
        ),
        trusted_public_key=read_one(
            trusted_public_key_path,
            _MAX_PUBLIC_KEY_BYTES,
            "pdf_review_public_key_unavailable",
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


def _canonical_object(raw: bytes, *, maximum_bytes: int, failure_code: str) -> dict[str, Any]:
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
        return value
    except Exception:
        raise _failure(failure_code) from None


def _schema_object(
    repo_root: Path,
    raw: bytes,
    *,
    schema_name: str,
    maximum_bytes: int,
    failure_code: str,
    pdf_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = _canonical_object(raw, maximum_bytes=maximum_bytes, failure_code=failure_code)
    try:
        validate_release_object(
            repo_root,
            schema_name,
            value,
            pdf_provenance=pdf_provenance,
        )
    except Exception:
        raise _failure(failure_code) from None
    return value


def _load_ed25519_public_key(value: bytes) -> tuple[Any, bytes]:
    if type(value) is not bytes or not value or len(value) > _MAX_PUBLIC_KEY_BYTES:
        raise _failure("pdf_review_public_key_invalid")
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
    except PdfReviewError:
        raise
    except Exception:
        raise _failure("pdf_review_public_key_invalid") from None


def _signed_material(payload: bytes, policy_digest: str) -> bytes:
    return (
        _PDF_REVIEW_SIGNATURE_DOMAIN
        + PDF_REVIEW_PURPOSE.encode("ascii")
        + b"\x00"
        + PDF_REVIEW_SCHEMA_VERSION.encode("ascii")
        + b"\x00"
        + policy_digest.encode("ascii")
        + b"\x00"
        + payload
    )


def pdf_review_signing_material(repo_root: Path, payload: bytes, trust_policy: bytes) -> bytes:
    """Build the exact domain-separated bytes an external PDF reviewer signs."""

    if type(payload) is not bytes or type(trust_policy) is not bytes:
        raise _failure("pdf_review_input_invalid")
    _schema_object(
        repo_root,
        bytes(payload),
        schema_name="pdf-review",
        maximum_bytes=_MAX_PAYLOAD_BYTES,
        failure_code="pdf_review_payload_malformed",
    )
    _schema_object(
        repo_root,
        bytes(trust_policy),
        schema_name="pdf-reviewer-key-policy",
        maximum_bytes=_MAX_POLICY_BYTES,
        failure_code="pdf_review_trust_policy_malformed",
    )
    return _signed_material(bytes(payload), sha256_bytes(bytes(trust_policy)))


def pdf_review_evidence_sha256(payload: Mapping[str, Any]) -> str:
    """Digest the exact non-circular review summary owned by ``pdf-review/1``."""

    try:
        if type(payload) is not dict:
            raise ValueError
        material = {field: payload[field] for field in _REVIEW_EVIDENCE_FIELDS}
        return sha256_bytes(canonical_json(material))
    except Exception:
        raise _failure("pdf_review_input_invalid") from None


def _policy_authorizes(policy: Mapping[str, Any], *, fingerprint: str) -> bool:
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
        and authority.get("independent_from_pdf_producer") is True
        and authority.get("independent_from_release_builder") is True
        and (PDF_REVIEW_PURPOSE, PDF_REVIEW_SCHEMA_VERSION, PDF_REVIEWER_ROLE) in normalized
    )


def _verify_detached_signature(
    repo_root: Path,
    payload_raw: bytes,
    signature_raw: bytes,
    policy_raw: bytes,
    public_key_raw: bytes,
) -> tuple[dict[str, Any], str]:
    payload = _schema_object(
        repo_root,
        payload_raw,
        schema_name="pdf-review",
        maximum_bytes=_MAX_PAYLOAD_BYTES,
        failure_code="pdf_review_payload_malformed",
    )
    signature = _schema_object(
        repo_root,
        signature_raw,
        schema_name="pdf-review-signature",
        maximum_bytes=_MAX_SIGNATURE_BYTES,
        failure_code="pdf_review_signature_malformed",
    )
    policy = _schema_object(
        repo_root,
        policy_raw,
        schema_name="pdf-reviewer-key-policy",
        maximum_bytes=_MAX_POLICY_BYTES,
        failure_code="pdf_review_trust_policy_malformed",
    )
    payload_digest = sha256_bytes(payload_raw)
    policy_digest = sha256_bytes(policy_raw)
    if (
        signature.get("purpose") != PDF_REVIEW_PURPOSE
        or signature.get("target_schema_version") != PDF_REVIEW_SCHEMA_VERSION
        or signature.get("target_sha256") != payload_digest
        or signature.get("trust_policy_sha256") != policy_digest
    ):
        raise _failure("pdf_review_binding_mismatch")
    key, raw_key = _load_ed25519_public_key(public_key_raw)
    fingerprint = f"sha256:{sha256_bytes(raw_key)}"
    if (
        signature.get("signer_key_fingerprint") != fingerprint
        or not _FINGERPRINT_RE.fullmatch(fingerprint)
        or not _policy_authorizes(policy, fingerprint=fingerprint)
    ):
        raise _failure("pdf_review_key_not_trusted")
    try:
        encoded = signature.get("signature_base64")
        if type(encoded) is not str:
            raise ValueError
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != encoded:
            raise ValueError
        key.verify(decoded, _signed_material(payload_raw, policy_digest))
    except Exception:
        raise _failure("pdf_review_signature_invalid") from None
    return payload, fingerprint


def _one_receipt(rows: Any, path: str) -> Mapping[str, Any]:
    if type(rows) is not list:
        raise _failure("pdf_review_family_invalid")
    matches = [row for row in rows if type(row) is dict and row.get("path") == path]
    if len(matches) != 1:
        raise _failure("pdf_review_family_invalid")
    return matches[0]


def _receipt_matches(receipt: Mapping[str, Any], raw: bytes) -> bool:
    return receipt.get("bytes") == len(raw) and receipt.get("sha256") == sha256_bytes(raw)


def _inspect_source_bound_pdf(
    raw: bytes,
    *,
    path: Path,
    expected_commit: str,
    expected_tree_digest: str,
) -> Any:
    try:
        from .pdf_report import inspect_pdf_report_bytes

        inspection = inspect_pdf_report_bytes(
            raw,
            path=path,
            expected_commit=expected_commit,
            expected_tree_digest=expected_tree_digest,
        )
        if (
            inspection.sha256 != sha256_bytes(raw)
            or inspection.bytes != len(raw)
            or not inspection.source_commit_present
            or not inspection.source_tree_digest_present
        ):
            raise ValueError
        return inspection
    except Exception:
        raise _failure("pdf_review_family_invalid") from None


def load_pdf_review_subject(repo_root: Path, manifest_path: Path) -> PdfReviewSubject:
    """Verify and snapshot one immutable generated-PDF release family."""

    try:
        root = Path(repo_root).resolve(strict=True)
        absolute_manifest = _direct_absolute(Path(manifest_path))
        if absolute_manifest.name != _MANIFEST_NAME:
            raise _failure("pdf_review_family_invalid")
        manifest_raw = _read_external_regular(
            absolute_manifest,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        manifest = _canonical_object(
            manifest_raw,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        family_before, family_snapshot = _verify_bounded_family(
            root,
            absolute_manifest,
            manifest_raw,
            manifest,
        )
        family_root = absolute_manifest.parent
        attestation_raw = _read_external_regular(
            family_root / _ATTESTATION_PATH,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        gate_raw = _read_external_regular(
            family_root / _PDF_GATE_PATH,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        pdf_raw = _read_external_regular(
            family_root / _PDF_PATH,
            maximum_bytes=_MAX_PDF_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        attestation = _schema_object(
            root,
            attestation_raw,
            schema_name="family-attestation",
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        gate = _canonical_object(
            gate_raw,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        if gate.get("status") != "generated_visual_review_pending":
            raise _failure("pdf_review_family_invalid")
        provenance_fields = ("sha256", "bytes", "page_count", "input_digest", "renderer")
        try:
            provenance = {field: gate[field] for field in provenance_fields}
            validate_release_object(root, "pdf-gate", gate, pdf_provenance=provenance)
        except Exception:
            raise _failure("pdf_review_family_invalid") from None

        artifact_receipts = manifest.get("artifacts")
        attestation_receipt = _one_receipt(artifact_receipts, _ATTESTATION_PATH)
        gate_receipt = _one_receipt(artifact_receipts, _PDF_GATE_PATH)
        pdf_receipt = _one_receipt(artifact_receipts, _PDF_PATH)
        if not (
            _receipt_matches(attestation_receipt, attestation_raw)
            and _receipt_matches(gate_receipt, gate_raw)
            and _receipt_matches(pdf_receipt, pdf_raw)
            and _receipt_matches(_one_receipt(attestation.get("covered_receipts"), _PDF_PATH), pdf_raw)
        ):
            raise _failure("pdf_review_family_invalid")

        artifact_rows = manifest.get("artifacts")
        if type(artifact_rows) is not list:
            raise _failure("pdf_review_family_invalid")
        expected_members = sorted(
            [_MANIFEST_NAME, *(row["path"] for row in artifact_rows)]
        )
        expected_covered = [
            {"path": row["path"], "sha256": row["sha256"], "bytes": row["bytes"]}
            for row in artifact_rows
            if row["path"] not in {_ATTESTATION_PATH, "artifact-inventory.json"}
        ]
        output_contract = attestation.get("output_contract")
        if (
            type(output_contract) is not dict
            or output_contract.get("expected_members") != expected_members
            or attestation.get("covered_receipts") != expected_covered
            or attestation.get("self_exclusions")
            != [
                _ATTESTATION_PATH,
                "artifact-inventory.json",
                _MANIFEST_NAME,
                "release-manifest.sig.json",
            ]
        ):
            raise _failure("pdf_review_family_invalid")

        source = manifest.get("source_binding")
        if type(source) is not dict:
            raise _failure("pdf_review_family_invalid")
        source_commit = source.get("source_commit")
        head_tree_oid = source.get("head_tree_oid")
        index_digest = source.get("index_digest")
        source_tree_digest = source.get("source_tree_digest")
        if (
            type(source_commit) is not str
            or _GIT_OID_RE.fullmatch(source_commit) is None
            or type(head_tree_oid) is not str
            or _GIT_OID_RE.fullmatch(head_tree_oid) is None
            or type(index_digest) is not str
            or _DIGEST_RE.fullmatch(index_digest) is None
            or type(source_tree_digest) is not str
            or _DIGEST_RE.fullmatch(source_tree_digest) is None
            or source.get("repository_input_basis") != "raw_selected_commit_git_blobs"
            or source.get("tracked_worktree_dirty") is not False
            or source.get("before_build") != source.get("after_build")
        ):
            raise _failure("pdf_review_family_invalid")
        stable_source = source.get("before_build")
        if type(stable_source) is not dict or any(
            stable_source.get(field) != source.get(field)
            for field in (
                "source_commit",
                "head_tree_oid",
                "index_digest",
                "source_tree_digest",
                "repository_input_basis",
                "tracked_worktree_dirty",
            )
        ):
            raise _failure("pdf_review_family_invalid")
        if (
            attestation.get("source_commit") != source_commit
            or attestation.get("source_tree_digest") != source_tree_digest
            or family_before.get("source_commit") != source_commit
            or family_before.get("source_tree_digest") != source_tree_digest
            or family_before.get("release_status") != manifest.get("release_status")
            or manifest.get("release_status") != "unsigned_preview_incomplete"
            or manifest.get("publication_status") != "not_authorized"
            or manifest.get("independent_verification_verdict") != "BLOCK"
            or gate.get("independent_verification_verdict") != "BLOCK"
        ):
            raise _failure("pdf_review_family_invalid")
        gates = manifest.get("gates")
        if (
            type(gates) is not dict
            or gates.get("pdf") != gate.get("status")
            or gates.get("independent_visual_review") != "pending"
            or gates.get("ed25519_signature") != "pending_external_owner_key"
            or gates.get("binary_output_privacy_review")
            != "pending_contextual_and_container_review"
            or gates.get("public_publication_authority") != "absent"
        ):
            raise _failure("pdf_review_family_invalid")

        pdf_digest = sha256_bytes(pdf_raw)
        inspection = _inspect_source_bound_pdf(
            pdf_raw,
            path=family_root / _PDF_PATH,
            expected_commit=source_commit,
            expected_tree_digest=source_tree_digest,
        )
        page_count = inspection.page_count
        if (
            gate.get("sha256") != pdf_digest
            or gate.get("bytes") != len(pdf_raw)
            or gate.get("page_count") != page_count
            or type(gate.get("input_digest")) is not str
            or _DIGEST_RE.fullmatch(gate["input_digest"]) is None
        ):
            raise _failure("pdf_review_family_invalid")

        _assert_family_stable(family_snapshot)
        manifest_after = _read_external_regular(
            absolute_manifest,
            maximum_bytes=_MAX_FAMILY_JSON_BYTES,
            failure_code="pdf_review_family_invalid",
        )
        if manifest_raw != manifest_after:
            raise _failure("pdf_review_family_changed")
        return PdfReviewSubject(
            manifest_path=absolute_manifest,
            source_commit=source_commit,
            head_tree_oid=head_tree_oid,
            index_digest=index_digest,
            source_tree_digest=source_tree_digest,
            release_manifest_sha256=sha256_bytes(manifest_raw),
            family_attestation_sha256=sha256_bytes(attestation_raw),
            pdf_gate_sha256=sha256_bytes(gate_raw),
            pdf_path=_PDF_PATH,
            pdf_sha256=pdf_digest,
            pdf_bytes=len(pdf_raw),
            pdf_page_count=page_count,
            pdf_input_digest=gate["input_digest"],
            release_status=manifest["release_status"],
            publication_status=manifest["publication_status"],
            family_independent_verification_verdict=manifest["independent_verification_verdict"],
            pdf_gate_status=gate["status"],
            pdf_gate_independent_verification_verdict=gate["independent_verification_verdict"],
        )
    except PdfReviewError as exc:
        if exc.code == "pdf_review_family_changed":
            raise
        raise _failure("pdf_review_family_invalid") from None
    except Exception:
        raise _failure("pdf_review_family_invalid") from None


def _subject_binding(subject: PdfReviewSubject) -> dict[str, Any]:
    return {
        "source_commit": subject.source_commit,
        "head_tree_oid": subject.head_tree_oid,
        "index_digest": subject.index_digest,
        "source_tree_digest": subject.source_tree_digest,
        "release_manifest_sha256": subject.release_manifest_sha256,
        "family_attestation_sha256": subject.family_attestation_sha256,
        "pdf_gate_sha256": subject.pdf_gate_sha256,
        "pdf_path": subject.pdf_path,
        "pdf_sha256": subject.pdf_sha256,
        "pdf_bytes": subject.pdf_bytes,
        "pdf_page_count": subject.pdf_page_count,
        "pdf_input_digest": subject.pdf_input_digest,
    }


def _validate_review_payload(
    subject: PdfReviewSubject,
    payload: Mapping[str, Any],
) -> tuple[bool, bool]:
    if any(payload.get(field) != value for field, value in _subject_binding(subject).items()):
        raise _failure("pdf_review_binding_mismatch")
    render_profile = payload.get("render_profile")
    page_reviews = payload.get("page_reviews")
    checks = payload.get("checks")
    if type(render_profile) is not dict or type(page_reviews) is not list or type(checks) is not dict:
        raise _failure("pdf_review_subject_mismatch")
    if (
        payload.get("render_profile_digest") != sha256_bytes(canonical_json(render_profile))
        or payload.get("page_reviews_digest") != sha256_bytes(canonical_json(page_reviews))
        or payload.get("checks_digest") != sha256_bytes(canonical_json(checks))
    ):
        raise _failure("pdf_review_subject_mismatch")

    page_numbers = [row.get("page_number") for row in page_reviews if type(row) is dict]
    if (
        len(page_numbers) != len(page_reviews)
        or any(type(value) is not int for value in page_numbers)
        or page_numbers != list(range(1, subject.pdf_page_count + 1))
    ):
        raise _failure("pdf_review_subject_mismatch")
    verdicts = [row.get("review_verdict") for row in page_reviews]
    rendered = len(page_reviews)
    passed = verdicts.count("pass")
    blocked = verdicts.count("block")
    reviewed = passed + blocked
    if any(
        payload.get(field) != value
        for field, value in {
            "rendered_page_count": rendered,
            "reviewed_page_count": reviewed,
            "passed_page_count": passed,
            "blocked_page_count": blocked,
        }.items()
    ):
        raise _failure("pdf_review_verdict_inconsistent")
    complete = reviewed == subject.pdf_page_count
    if checks.get("all_pages_rendered") != "pass":
        raise _failure("pdf_review_verdict_inconsistent")
    if checks.get("all_pages_reviewed") != ("pass" if complete else "block"):
        raise _failure("pdf_review_verdict_inconsistent")
    passed_review = complete and passed == subject.pdf_page_count and all(
        value == "pass" for value in checks.values()
    )
    expected_verdict = "PASS" if passed_review else "BLOCK"
    if payload.get("verdict") != expected_verdict:
        raise _failure("pdf_review_verdict_inconsistent")
    try:
        expected_evidence_digest = pdf_review_evidence_sha256(payload)
    except PdfReviewError:
        raise _failure("pdf_review_subject_mismatch") from None
    if payload.get("review_evidence_sha256") != expected_evidence_digest:
        raise _failure("pdf_review_subject_mismatch")
    return complete, passed_review


def _validated_result(repo_root: Path, result: PdfReviewResult) -> PdfReviewResult:
    try:
        if result.visual_review_passed != (
            result.status == "verified_visual_pass_not_promoted"
        ):
            raise ValueError
        validate_release_object(repo_root, "pdf-review-result", result.as_dict())
    except Exception:
        raise _failure("pdf_review_result_invalid") from None
    return result


def _verify_pdf_review_subject(
    repo_root: Path,
    subject: PdfReviewSubject,
    evidence: PdfReviewEvidenceBytes,
) -> PdfReviewResult:
    """Join signed evidence to one subject already loaded by the public API."""

    try:
        if type(subject) is not PdfReviewSubject or type(evidence) is not PdfReviewEvidenceBytes:
            raise _failure("pdf_review_input_invalid")
        raw_parts = (
            evidence.payload,
            evidence.signature,
            evidence.trust_policy,
            evidence.trusted_public_key,
        )
        if any(part is not None and type(part) is not bytes for part in raw_parts):
            raise _failure("pdf_review_input_invalid")
        if any(part is None for part in raw_parts):
            raise _failure("pdf_review_input_incomplete")
        cloned = PdfReviewEvidenceBytes(
            payload=bytes(evidence.payload),  # type: ignore[arg-type]
            signature=bytes(evidence.signature),  # type: ignore[arg-type]
            trust_policy=bytes(evidence.trust_policy),  # type: ignore[arg-type]
            trusted_public_key=bytes(evidence.trusted_public_key),  # type: ignore[arg-type]
        )
        assert cloned.payload is not None
        assert cloned.signature is not None
        assert cloned.trust_policy is not None
        assert cloned.trusted_public_key is not None
        payload, fingerprint = _verify_detached_signature(
            repo_root,
            cloned.payload,
            cloned.signature,
            cloned.trust_policy,
            cloned.trusted_public_key,
        )
        complete, passed_review = _validate_review_payload(subject, payload)
        return _validated_result(
            repo_root,
            PdfReviewResult(
                schema_version=PDF_REVIEW_RESULT_SCHEMA_VERSION,
                status=(
                    "verified_visual_pass_not_promoted"
                    if passed_review
                    else "verified_visual_blocked_not_promoted"
                ),
                purpose=PDF_REVIEW_PURPOSE,
                signature_verified=True,
                family_integrity_verified=True,
                pdf_subject_verified=True,
                visual_review_complete=complete,
                visual_review_passed=passed_review,
                current_gate_promoted=False,
                global_gate_closed=False,
                release_family_mutated=False,
                owner_manifest_signature_verified=False,
                accessibility_review_established=False,
                binary_privacy_review_established=False,
                publication_authority_granted=False,
                **_subject_binding(subject),
                release_status=subject.release_status,
                publication_status=subject.publication_status,
                family_independent_verification_verdict=(
                    subject.family_independent_verification_verdict
                ),
                pdf_gate_status=subject.pdf_gate_status,
                pdf_gate_independent_verification_verdict=(
                    subject.pdf_gate_independent_verification_verdict
                ),
                payload_sha256=sha256_bytes(cloned.payload),
                trust_policy_sha256=sha256_bytes(cloned.trust_policy),
                signer_key_fingerprint=fingerprint,
                render_profile_digest=payload["render_profile_digest"],
                page_reviews_digest=payload["page_reviews_digest"],
                rendered_page_count=payload["rendered_page_count"],
                reviewed_page_count=payload["reviewed_page_count"],
                passed_page_count=payload["passed_page_count"],
                blocked_page_count=payload["blocked_page_count"],
                checks_digest=payload["checks_digest"],
                review_evidence_sha256=payload["review_evidence_sha256"],
                verification_boundary=_VERIFICATION_BOUNDARY,
            ),
        )
    except PdfReviewError as exc:
        raise _failure(normalize_pdf_review_error(exc)) from None
    except Exception:
        raise _failure("pdf_review_unexpected") from None


def verify_pdf_review(
    repo_root: Path,
    manifest_path: Path,
    evidence: PdfReviewEvidenceBytes,
) -> PdfReviewResult:
    """Verify signed evidence against a live immutable family without promotion."""

    try:
        if isinstance(manifest_path, PdfReviewSubject):
            raise _failure("pdf_review_input_invalid")
        subject_before = load_pdf_review_subject(repo_root, Path(manifest_path))
        result = _verify_pdf_review_subject(repo_root, subject_before, evidence)
        subject_after = load_pdf_review_subject(repo_root, Path(manifest_path))
        if subject_before != subject_after:
            raise _failure("pdf_review_family_changed")
        return result
    except PdfReviewError as exc:
        raise _failure(normalize_pdf_review_error(exc)) from None
    except Exception:
        raise _failure("pdf_review_unexpected") from None
