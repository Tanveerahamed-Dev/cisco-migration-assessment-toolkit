"""Non-authoritative R2.0 workload evidence and independent adequacy review.

The evidence envelope can say only that an exact workload-evidence manifest is absent or ready
for an external reviewer. It cannot call itself representative or adequate. Adequacy is a
detached, purpose-bound Ed25519 decision verified relative to separately supplied current
trust-policy bytes and an externally selected exact policy digest. Every authority use must
re-evaluate the retained evidence and receipt under caller-supplied current policy; a retained
historical result is not current authority.

This module ships no evidence corpus, trust root, policy, key, signature, qualification, or
promotion path. The selected digest makes the trust-anchor input explicit but cannot authenticate
policy selection, succession, custody, or time. The policy's independence fields are assertions
that Atlas binds; bytes cannot prove real-world organizational independence.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator, Mapping as MappingABC
from typing import Any, Mapping

from .transition_contract import (
    TransitionContractError,
    _array,
    _digest,
    _exact_keys,
    _identifier,
    _integer,
    _mapping,
    _schema,
    _sorted_unique_digests,
    _text,
    _timestamp,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)


TRANSITION_WORKLOAD_EVIDENCE_SCHEMA = "atlas.transition-workload-evidence/1"
WORKLOAD_REVIEW_RECEIPT_SCHEMA = "atlas.transition-workload-review-receipt/1"
WORKLOAD_REVIEW_SIGNATURE_SCHEMA = "atlas.transition-workload-review-signature/1"
WORKLOAD_REVIEW_TRUST_POLICY_SCHEMA = "atlas.transition-workload-review-trust-policy/1"
WORKLOAD_REVIEW_TRUSTED_KEY_SCHEMA = "atlas.transition-workload-review-trusted-key/1"
WORKLOAD_REVIEW_AUTHORIZATION_SCHEMA = "atlas.transition-workload-review-authorization/1"
WORKLOAD_REVIEW_BINDINGS_SCHEMA = "atlas.transition-workload-review-bindings/1"
WORKLOAD_REVIEW_PURPOSE = "ATLAS_R2_REPRESENTATIVE_WORKLOAD_ADEQUACY_REVIEW"
WORKLOAD_REVIEW_POLICY_KIND = "EXTERNAL_INDEPENDENT_WORKLOAD_REVIEW_KEY_ALLOWLIST"
WORKLOAD_REVIEW_REVIEWER_KIND = "INDEPENDENT_REVIEWER"
WORKLOAD_REVIEW_REVIEWER_ROLE = "REPRESENTATIVE_WORKLOAD_ADEQUACY_REVIEWER"
WORKLOAD_REVIEW_SUBSTRATE = "DECLARATIVE_DSL_ONLY"
WORKLOAD_REVIEW_SIGNATURE_ALGORITHM = "Ed25519"
WORKLOAD_EVIDENCE_ABSENT = "ABSENT"
WORKLOAD_EVIDENCE_READY = "READY_FOR_EXTERNAL_REVIEW"
WORKLOAD_REVIEW_ADEQUATE = "ADEQUATE"
WORKLOAD_REVIEW_INADEQUATE = "INADEQUATE"
WORKLOAD_EVIDENCE_CLAIM_BOUNDARY = (
    "Exact non-authoritative workload material for external R2.0 adequacy review only; "
    "the envelope cannot establish representativeness, approve budgets, qualify a pack, "
    "authorize execution, enable promotion, or include Release 3."
)

WORKLOAD_BINDING_DIGEST_FIELDS = (
    "structural_census_digest",
    "prototype_measurement_digest",
    "runtime_inventory_digest",
    "dsl_interpreter_digest",
    "prototype_program_digest",
    "prototype_input_digest",
    "measurement_denominator_digest",
)

_SIGNATURE_DOMAIN = b"ATLAS-R2-WORKLOAD-REVIEW\x00v1\x00"
_ED25519_PUBLIC_KEY_BYTES = 32
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_ROLE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_EVIDENCE_AUTHORITY = object()
_POLICY_AUTHORITY = object()
_VERIFIED_AUTHORITY = object()


class WorkloadReviewError(RuntimeError):
    """Stable, non-echoing workload evidence/review refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject(code: str) -> None:
    raise WorkloadReviewError(code)


def _git_object(value: Any, path: str) -> str:
    checked = _text(value, path)
    if not _GIT_OBJECT_RE.fullmatch(checked):
        raise TransitionContractError("GIT_OBJECT_REQUIRED", path)
    return checked


def _validate_artifacts(value: Any, path: str) -> list[dict[str, Any]]:
    rows = _array(value, path)
    checked: list[dict[str, Any]] = []
    identities: list[tuple[str, str, str]] = []
    for index, row_value in enumerate(rows):
        row_path = f"{path}[{index}]"
        row = _mapping(row_value, row_path)
        _exact_keys(row, ("artifact_id", "role", "digest", "raw_bytes"), row_path)
        artifact_id = _identifier(row["artifact_id"], f"{row_path}.artifact_id")
        role = _text(row["role"], f"{row_path}.role")
        if not _ROLE_RE.fullmatch(role):
            raise TransitionContractError("UPPER_TOKEN_REQUIRED", f"{row_path}.role")
        digest = _digest(row["digest"], f"{row_path}.digest")
        raw_bytes = _integer(row["raw_bytes"], f"{row_path}.raw_bytes", positive=True)
        checked_row = {
            "artifact_id": artifact_id,
            "role": role,
            "digest": digest,
            "raw_bytes": raw_bytes,
        }
        checked.append(checked_row)
        identities.append((artifact_id, role, digest))
    if checked != sorted(
            checked,
            key=lambda row: (row["artifact_id"], row["role"], row["digest"])):
        raise TransitionContractError("SORTED_WORKLOAD_EVIDENCE_REQUIRED", path)
    if len(identities) != len(set(identities)):
        raise TransitionContractError("UNIQUE_WORKLOAD_EVIDENCE_REQUIRED", path)
    return checked


def _validate_bindings(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "selected_commit",
        "selected_tree",
        *WORKLOAD_BINDING_DIGEST_FIELDS,
        "workload_evidence_digest",
        "workload_evidence_state",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, WORKLOAD_REVIEW_BINDINGS_SCHEMA, "$")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in (*WORKLOAD_BINDING_DIGEST_FIELDS, "workload_evidence_digest"):
        _digest(obj[field], f"$.{field}")
    if obj["workload_evidence_state"] not in {
            WORKLOAD_EVIDENCE_ABSENT, WORKLOAD_EVIDENCE_READY}:
        raise TransitionContractError(
            "WORKLOAD_EVIDENCE_STATE_INVALID", "$.workload_evidence_state"
        )
    return dict(obj)


def validate_transition_workload_evidence(value: Any) -> dict[str, Any]:
    """Validate a closed evidence envelope without minting adequacy authority."""

    obj = _mapping(value, "$")
    keys = (
        "schema",
        "evidence_id",
        "purpose",
        "state",
        "producer_id",
        "selected_commit",
        "selected_tree",
        *WORKLOAD_BINDING_DIGEST_FIELDS,
        "artifacts",
        "known_gaps",
        "claim_boundary",
        "authority",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TRANSITION_WORKLOAD_EVIDENCE_SCHEMA, "$")
    _identifier(obj["evidence_id"], "$.evidence_id")
    if obj["purpose"] != WORKLOAD_REVIEW_PURPOSE:
        raise TransitionContractError("WORKLOAD_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    if obj["state"] not in {WORKLOAD_EVIDENCE_ABSENT, WORKLOAD_EVIDENCE_READY}:
        raise TransitionContractError("WORKLOAD_EVIDENCE_STATE_INVALID", "$.state")
    _identifier(obj["producer_id"], "$.producer_id")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in WORKLOAD_BINDING_DIGEST_FIELDS:
        _digest(obj[field], f"$.{field}")
    artifacts = _validate_artifacts(obj["artifacts"], "$.artifacts")
    gaps = _array(obj["known_gaps"], "$.known_gaps")
    checked_gaps = [
        _identifier(item, f"$.known_gaps[{index}]")
        for index, item in enumerate(gaps)
    ]
    if checked_gaps != sorted(set(checked_gaps)):
        raise TransitionContractError("SORTED_UNIQUE_WORKLOAD_GAPS_REQUIRED", "$.known_gaps")
    if obj["state"] == WORKLOAD_EVIDENCE_ABSENT:
        if artifacts or not checked_gaps:
            raise TransitionContractError("ABSENT_WORKLOAD_EVIDENCE_MUST_DISCLOSE_GAP", "$")
    elif not artifacts:
        raise TransitionContractError("READY_WORKLOAD_EVIDENCE_REQUIRED", "$.artifacts")
    if obj["claim_boundary"] != WORKLOAD_EVIDENCE_CLAIM_BOUNDARY:
        raise TransitionContractError(
            "WORKLOAD_EVIDENCE_CLAIM_BOUNDARY_INVALID", "$.claim_boundary"
        )
    authority = _mapping(obj["authority"], "$.authority")
    _exact_keys(
        authority,
        (
            "authoritative",
            "adequacy_decision",
            "approved_budget",
            "qualification_effect",
            "promotion_eligible",
            "release3_included",
        ),
        "$.authority",
    )
    if (
            authority["authoritative"] is not False
            or authority["adequacy_decision"] is not None
            or authority["approved_budget"] is not None
            or authority["qualification_effect"] != "NONE"
            or authority["promotion_eligible"] is not False
            or authority["release3_included"] is not False
    ):
        raise TransitionContractError("WORKLOAD_EVIDENCE_AUTHORITY_LAUNDERING", "$.authority")
    return dict(obj)


class BoundTransitionWorkloadEvidence(MappingABC[str, Any]):
    """Immutable exact canonical workload evidence bytes."""

    __slots__ = ("_bound_digest", "_bound_raw", "_bound_source_bytes", "_sealed")

    def __init__(self, value: Mapping[str, Any], *, raw: bytes, _authority: object) -> None:
        if _authority is not _EVIDENCE_AUTHORITY:
            raise TypeError("BoundTransitionWorkloadEvidence requires exact evidence bytes")
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", raw)
        object.__setattr__(self, "_bound_digest", canonical_digest(dict(value)))
        object.__setattr__(self, "_bound_source_bytes", len(raw))
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound workload evidence is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundTransitionWorkloadEvidence is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


def bind_transition_workload_evidence_bytes(raw: bytes) -> BoundTransitionWorkloadEvidence:
    try:
        checked = validate_transition_workload_evidence(
            parse_canonical_json_bytes(raw, require_canonical=True)
        )
        if canonical_digest(checked) != bytes_digest(raw):
            raise TransitionContractError("WORKLOAD_EVIDENCE_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TypeError, ValueError):
        _reject("transition_workload_evidence_malformed")
    return BoundTransitionWorkloadEvidence(checked, raw=raw, _authority=_EVIDENCE_AUTHORITY)


def require_bound_transition_workload_evidence(value: Any) -> BoundTransitionWorkloadEvidence:
    if type(value) is not BoundTransitionWorkloadEvidence:
        _reject("bound_transition_workload_evidence_required")
    try:
        rebound = bind_transition_workload_evidence_bytes(value._bound_raw)
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
        )
    except (AttributeError, TransitionContractError, TypeError, WorkloadReviewError):
        intact = False
    if not intact:
        _reject("bound_transition_workload_evidence_mutated")
    return value


def validate_workload_review_receipt(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema", "receipt_id", "purpose", "selected_commit", "selected_tree",
        *WORKLOAD_BINDING_DIGEST_FIELDS, "workload_evidence_digest",
        "workload_evidence_state", "decision", "issued_at", "valid_from", "valid_until",
        "reviewer_key_id",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, WORKLOAD_REVIEW_RECEIPT_SCHEMA, "$")
    _identifier(obj["receipt_id"], "$.receipt_id")
    if obj["purpose"] != WORKLOAD_REVIEW_PURPOSE:
        raise TransitionContractError("WORKLOAD_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in (*WORKLOAD_BINDING_DIGEST_FIELDS, "workload_evidence_digest"):
        _digest(obj[field], f"$.{field}")
    if obj["workload_evidence_state"] not in {
            WORKLOAD_EVIDENCE_ABSENT, WORKLOAD_EVIDENCE_READY}:
        raise TransitionContractError("WORKLOAD_EVIDENCE_STATE_INVALID", "$.workload_evidence_state")
    if obj["decision"] not in {WORKLOAD_REVIEW_ADEQUATE, WORKLOAD_REVIEW_INADEQUATE}:
        raise TransitionContractError("WORKLOAD_REVIEW_DECISION_INVALID", "$.decision")
    issued_at = _timestamp(obj["issued_at"], "$.issued_at")
    valid_from = _timestamp(obj["valid_from"], "$.valid_from")
    valid_until = _timestamp(obj["valid_until"], "$.valid_until")
    if issued_at > valid_from or valid_from >= valid_until:
        raise TransitionContractError("WORKLOAD_REVIEW_TIME_RANGE_INVALID", "$")
    _identifier(obj["reviewer_key_id"], "$.reviewer_key_id")
    return dict(obj)


def validate_workload_review_signature(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    _exact_keys(
        obj,
        ("schema", "purpose", "payload_digest", "signer_key_id", "algorithm", "signature_base64"),
        "$",
    )
    _schema(obj, WORKLOAD_REVIEW_SIGNATURE_SCHEMA, "$")
    if obj["purpose"] != WORKLOAD_REVIEW_PURPOSE:
        raise TransitionContractError("WORKLOAD_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _digest(obj["payload_digest"], "$.payload_digest")
    _identifier(obj["signer_key_id"], "$.signer_key_id")
    if obj["algorithm"] != WORKLOAD_REVIEW_SIGNATURE_ALGORITHM:
        raise TransitionContractError(
            "WORKLOAD_REVIEW_SIGNATURE_ALGORITHM_INVALID", "$.algorithm"
        )
    encoded = _text(obj["signature_base64"], "$.signature_base64")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise TransitionContractError(
            "WORKLOAD_REVIEW_SIGNATURE_INVALID", "$.signature_base64"
        ) from None
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
        raise TransitionContractError("WORKLOAD_REVIEW_SIGNATURE_INVALID", "$.signature_base64")
    return dict(obj)


def validate_workload_review_bindings(value: Any) -> dict[str, Any]:
    return _validate_bindings(value)


def validate_workload_review_trust_policy(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema", "policy_kind", "policy_id", "policy_version", "purpose", "evaluated_at",
        "trusted_keys", "revoked_receipt_digests",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, WORKLOAD_REVIEW_TRUST_POLICY_SCHEMA, "$")
    if obj["policy_kind"] != WORKLOAD_REVIEW_POLICY_KIND:
        raise TransitionContractError("WORKLOAD_REVIEW_POLICY_KIND_MISMATCH", "$.policy_kind")
    _identifier(obj["policy_id"], "$.policy_id")
    _identifier(obj["policy_version"], "$.policy_version")
    if obj["purpose"] != WORKLOAD_REVIEW_PURPOSE:
        raise TransitionContractError("WORKLOAD_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _timestamp(obj["evaluated_at"], "$.evaluated_at")
    trusted_keys = _array(obj["trusted_keys"], "$.trusted_keys")
    key_ids: list[str] = []
    for index, item_value in enumerate(trusted_keys):
        path = f"$.trusted_keys[{index}]"
        item = _mapping(item_value, path)
        _exact_keys(
            item,
            (
                "schema", "key_id", "public_key_digest", "reviewer_kind",
                "independent_from_workload_producer", "independent_from_measurement_producer",
                "independent_from_budget_proposer", "independent_from_release_builder",
                "authorizations", "allowed_subjects", "valid_from", "valid_until",
            ),
            path,
        )
        _schema(item, WORKLOAD_REVIEW_TRUSTED_KEY_SCHEMA, path)
        key_ids.append(_identifier(item["key_id"], f"{path}.key_id"))
        _digest(item["public_key_digest"], f"{path}.public_key_digest")
        if (
                item["reviewer_kind"] != WORKLOAD_REVIEW_REVIEWER_KIND
                or item["independent_from_workload_producer"] is not True
                or item["independent_from_measurement_producer"] is not True
                or item["independent_from_budget_proposer"] is not True
                or item["independent_from_release_builder"] is not True
        ):
            raise TransitionContractError("WORKLOAD_REVIEWER_INDEPENDENCE_REQUIRED", path)
        expected_authorization = {
            "schema": WORKLOAD_REVIEW_AUTHORIZATION_SCHEMA,
            "purpose": WORKLOAD_REVIEW_PURPOSE,
            "target_schema_version": WORKLOAD_REVIEW_RECEIPT_SCHEMA,
            "reviewer_role": WORKLOAD_REVIEW_REVIEWER_ROLE,
            "substrate": WORKLOAD_REVIEW_SUBSTRATE,
        }
        if _array(item["authorizations"], f"{path}.authorizations") != [expected_authorization]:
            raise TransitionContractError(
                "WORKLOAD_REVIEWER_AUTHORIZATION_REQUIRED", f"{path}.authorizations"
            )
        allowed = _array(item["allowed_subjects"], f"{path}.allowed_subjects")
        checked_subjects: list[tuple[str, str, str]] = []
        for subject_index, subject_value in enumerate(allowed):
            subject_path = f"{path}.allowed_subjects[{subject_index}]"
            subject = _mapping(subject_value, subject_path)
            _exact_keys(
                subject,
                ("selected_commit", "selected_tree", "workload_evidence_digest"),
                subject_path,
            )
            checked_subjects.append((
                _git_object(subject["selected_commit"], f"{subject_path}.selected_commit"),
                _git_object(subject["selected_tree"], f"{subject_path}.selected_tree"),
                _digest(
                    subject["workload_evidence_digest"],
                    f"{subject_path}.workload_evidence_digest",
                ),
            ))
        if not checked_subjects or checked_subjects != sorted(set(checked_subjects)):
            raise TransitionContractError(
                "SORTED_UNIQUE_WORKLOAD_SUBJECTS_REQUIRED", f"{path}.allowed_subjects"
            )
        valid_from = _timestamp(item["valid_from"], f"{path}.valid_from")
        valid_until = _timestamp(item["valid_until"], f"{path}.valid_until")
        if valid_from >= valid_until:
            raise TransitionContractError("WORKLOAD_REVIEW_KEY_TIME_RANGE_INVALID", path)
    if key_ids != sorted(set(key_ids)):
        raise TransitionContractError(
            "SORTED_UNIQUE_WORKLOAD_REVIEW_KEYS_REQUIRED", "$.trusted_keys"
        )
    _sorted_unique_digests(
        obj["revoked_receipt_digests"], "$.revoked_receipt_digests", allow_empty=True
    )
    return dict(obj)


class BoundExternalWorkloadReviewTrustPolicy(MappingABC[str, Any]):
    """Immutable exact external trust-policy bytes."""

    __slots__ = ("_bound_digest", "_bound_raw", "_bound_source_bytes", "_sealed")

    def __init__(self, value: Mapping[str, Any], *, raw: bytes, _authority: object) -> None:
        if _authority is not _POLICY_AUTHORITY:
            raise TypeError("BoundExternalWorkloadReviewTrustPolicy requires exact policy bytes")
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", raw)
        object.__setattr__(self, "_bound_digest", canonical_digest(dict(value)))
        object.__setattr__(self, "_bound_source_bytes", len(raw))
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound workload policy is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundExternalWorkloadReviewTrustPolicy is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


def bind_external_workload_review_trust_policy_bytes(
        raw: bytes) -> BoundExternalWorkloadReviewTrustPolicy:
    try:
        checked = validate_workload_review_trust_policy(
            parse_canonical_json_bytes(raw, require_canonical=True)
        )
        if canonical_digest(checked) != bytes_digest(raw):
            raise TransitionContractError("WORKLOAD_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TypeError, ValueError):
        _reject("workload_review_trust_policy_malformed")
    return BoundExternalWorkloadReviewTrustPolicy(
        checked, raw=raw, _authority=_POLICY_AUTHORITY
    )


def require_bound_workload_review_trust_policy(
        value: Any) -> BoundExternalWorkloadReviewTrustPolicy:
    if type(value) is not BoundExternalWorkloadReviewTrustPolicy:
        _reject("external_workload_review_trust_policy_required")
    try:
        rebound = bind_external_workload_review_trust_policy_bytes(value._bound_raw)
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
        )
    except (AttributeError, TransitionContractError, TypeError, WorkloadReviewError):
        intact = False
    if not intact:
        _reject("bound_workload_review_trust_policy_mutated")
    return value


def _signed_material(receipt_raw: bytes) -> bytes:
    return (
        _SIGNATURE_DOMAIN
        + WORKLOAD_REVIEW_PURPOSE.encode("ascii")
        + b"\x00"
        + WORKLOAD_REVIEW_RECEIPT_SCHEMA.encode("ascii")
        + b"\x00"
        + receipt_raw
    )


def workload_review_signing_material(receipt_raw: bytes, trust_policy_raw: bytes) -> bytes:
    """Return receipt-only signing material after validating both supplied documents.

    Policy is a replaceable external authorization and revocation input. It is deliberately
    excluded from the signature so every verifier use can select, exactly pin, and re-evaluate
    current policy without asking the reviewer to re-sign an unchanged receipt.
    """

    try:
        receipt = validate_workload_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        policy = validate_workload_review_trust_policy(
            parse_canonical_json_bytes(trust_policy_raw, require_canonical=True)
        )
        if canonical_digest(receipt) != bytes_digest(receipt_raw):
            raise TransitionContractError("WORKLOAD_RECEIPT_DIGEST_MISMATCH", "$")
        if canonical_digest(policy) != bytes_digest(trust_policy_raw):
            raise TransitionContractError("WORKLOAD_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TypeError, ValueError):
        _reject("workload_review_signing_input_malformed")
    return _signed_material(receipt_raw)


class VerifiedTransitionWorkloadReview:
    """Opaque immutable result of one exact workload-policy evaluation.

    Before using the result as authority, a consumer must call
    ``require_verified_transition_workload_review`` with externally obtained current policy and
    its exact selected digest, then independently compare and bind the fresh result's
    ``bindings_digest``, policy digest, and evaluation time to the gate's selected subject. A
    retained ``adequate`` property is historical state, not current authority.
    """

    __slots__ = (
        "review_digest", "signature_digest", "policy_digest",
        "externally_selected_trust_policy_digest", "trusted_public_key_digest",
        "bindings_digest", "evidence_digest", "evidence_state", "selected_commit",
        "selected_tree", "decision", "reviewer_key_id", "issued_at", "valid_from",
        "valid_until", "evaluated_at", "adequate",
        "_evidence_raw", "_receipt_raw", "_signature_raw", "_trust_policy_raw",
        "_trusted_public_key_raw", "_expected_bindings_raw", "_integrity_digest", "_sealed",
    )

    def __init__(
            self,
            *,
            evidence: BoundTransitionWorkloadEvidence,
            receipt: Mapping[str, Any],
            receipt_raw: bytes,
            signature_raw: bytes,
            policy: BoundExternalWorkloadReviewTrustPolicy,
            public_key_raw: bytes,
            expected_bindings: Mapping[str, Any],
            externally_selected_trust_policy_digest: str,
            _authority: object) -> None:
        if _authority is not _VERIFIED_AUTHORITY:
            raise TypeError("VerifiedTransitionWorkloadReview requires external verification")
        object.__setattr__(self, "_sealed", False)
        self.review_digest = bytes_digest(receipt_raw)
        self.signature_digest = bytes_digest(signature_raw)
        self.policy_digest = policy.digest
        self.externally_selected_trust_policy_digest = (
            externally_selected_trust_policy_digest
        )
        self.trusted_public_key_digest = bytes_digest(public_key_raw)
        self.bindings_digest = canonical_digest(dict(expected_bindings))
        self.evidence_digest = evidence.digest
        self.evidence_state = evidence["state"]
        self.selected_commit = receipt["selected_commit"]
        self.selected_tree = receipt["selected_tree"]
        self.decision = receipt["decision"]
        self.reviewer_key_id = receipt["reviewer_key_id"]
        self.issued_at = receipt["issued_at"]
        self.valid_from = receipt["valid_from"]
        self.valid_until = receipt["valid_until"]
        self.evaluated_at = policy["evaluated_at"]
        self.adequate = self.decision == WORKLOAD_REVIEW_ADEQUATE
        object.__setattr__(self, "_evidence_raw", evidence._bound_raw)
        object.__setattr__(self, "_receipt_raw", receipt_raw)
        object.__setattr__(self, "_signature_raw", signature_raw)
        object.__setattr__(self, "_trust_policy_raw", policy._bound_raw)
        object.__setattr__(self, "_trusted_public_key_raw", public_key_raw)
        object.__setattr__(
            self,
            "_expected_bindings_raw",
            canonical_json_bytes(dict(expected_bindings)),
        )
        object.__setattr__(self, "_integrity_digest", self._compute_integrity_digest())
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("VerifiedTransitionWorkloadReview is immutable")
        object.__setattr__(self, name, value)

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "review_digest": self.review_digest,
            "signature_digest": self.signature_digest,
            "policy_digest": self.policy_digest,
            "externally_selected_trust_policy_digest": (
                self.externally_selected_trust_policy_digest
            ),
            "trusted_public_key_digest": self.trusted_public_key_digest,
            "bindings_digest": self.bindings_digest,
            "evidence_digest": self.evidence_digest,
            "evidence_state": self.evidence_state,
            "selected_commit": self.selected_commit,
            "selected_tree": self.selected_tree,
            "decision": self.decision,
            "reviewer_key_id": self.reviewer_key_id,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "evaluated_at": self.evaluated_at,
            "adequate": self.adequate,
        })


def verify_transition_workload_review(
        evidence: BoundTransitionWorkloadEvidence,
        receipt_raw: bytes,
        signature_raw: bytes,
        trust_policy: BoundExternalWorkloadReviewTrustPolicy,
        trusted_public_key_raw: bytes,
        expected_bindings: Mapping[str, Any],
        externally_selected_trust_policy_digest: str,
        ) -> VerifiedTransitionWorkloadReview:
    """Verify exact evidence and receipt bytes against an externally selected policy digest."""

    try:
        bound_evidence = require_bound_transition_workload_evidence(evidence)
        receipt = validate_workload_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        signature = validate_workload_review_signature(
            parse_canonical_json_bytes(signature_raw, require_canonical=True)
        )
    except WorkloadReviewError:
        raise
    except (TransitionContractError, TypeError, ValueError):
        _reject("workload_review_evidence_malformed")
    policy = require_bound_workload_review_trust_policy(trust_policy)
    try:
        bindings = validate_workload_review_bindings(dict(expected_bindings))
    except (TransitionContractError, TypeError, ValueError):
        _reject("workload_review_expected_bindings_malformed")
    try:
        selected_policy_digest = _digest(
            externally_selected_trust_policy_digest,
            "$.externally_selected_trust_policy_digest",
        )
    except (TransitionContractError, TypeError, ValueError):
        _reject("workload_review_policy_pin_malformed")
    if selected_policy_digest != policy.digest:
        _reject("workload_review_policy_pin_mismatch")
    if (
            type(trusted_public_key_raw) is not bytes
            or len(trusted_public_key_raw) != _ED25519_PUBLIC_KEY_BYTES
    ):
        _reject("workload_review_public_key_malformed")

    evidence_bindings = {
        "selected_commit": bound_evidence["selected_commit"],
        "selected_tree": bound_evidence["selected_tree"],
        **{field: bound_evidence[field] for field in WORKLOAD_BINDING_DIGEST_FIELDS},
        "workload_evidence_digest": bound_evidence.digest,
        "workload_evidence_state": bound_evidence["state"],
    }
    for field, expected in evidence_bindings.items():
        if receipt[field] != expected or bindings[field] != expected:
            _reject("workload_review_candidate_binding_mismatch")
    if receipt["reviewer_key_id"] == bound_evidence["producer_id"]:
        _reject("workload_reviewer_producer_identity_conflict")
    if (
            receipt["decision"] == WORKLOAD_REVIEW_ADEQUATE
            and bound_evidence["state"] != WORKLOAD_EVIDENCE_READY
    ):
        _reject("workload_review_adequate_requires_ready_evidence")

    review_digest = bytes_digest(receipt_raw)
    if (
            signature["payload_digest"] != review_digest
            or signature["signer_key_id"] != receipt["reviewer_key_id"]
    ):
        _reject("workload_review_signature_binding_mismatch")
    trusted_key = next(
        (
            item for item in policy["trusted_keys"]
            if item["key_id"] == receipt["reviewer_key_id"]
        ),
        None,
    )
    if (
            trusted_key is None
            or trusted_key["public_key_digest"] != bytes_digest(trusted_public_key_raw)
    ):
        _reject("workload_review_key_not_trusted")
    subject = {
        "selected_commit": receipt["selected_commit"],
        "selected_tree": receipt["selected_tree"],
        "workload_evidence_digest": receipt["workload_evidence_digest"],
    }
    if subject not in trusted_key["allowed_subjects"]:
        _reject("workload_review_subject_not_authorized")

    evaluated_at = _timestamp(policy["evaluated_at"], "$.evaluated_at")
    key_valid_from = _timestamp(trusted_key["valid_from"], "$.trusted_keys[].valid_from")
    key_valid_until = _timestamp(trusted_key["valid_until"], "$.trusted_keys[].valid_until")
    issued_at = _timestamp(receipt["issued_at"], "$.issued_at")
    if not key_valid_from <= evaluated_at <= key_valid_until:
        _reject("workload_review_key_not_valid_at_policy_time")
    if not key_valid_from <= issued_at <= key_valid_until:
        _reject("workload_review_key_not_valid_at_receipt_time")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        signature_bytes = base64.b64decode(signature["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(trusted_public_key_raw).verify(
            signature_bytes,
            _signed_material(receipt_raw),
        )
    except ImportError:
        _reject("workload_review_crypto_runtime_unavailable")
    except Exception:
        _reject("workload_review_signature_invalid")
    if review_digest in policy["revoked_receipt_digests"]:
        _reject("workload_review_receipt_revoked")
    valid_from = _timestamp(receipt["valid_from"], "$.valid_from")
    valid_until = _timestamp(receipt["valid_until"], "$.valid_until")
    if not valid_from <= evaluated_at <= valid_until:
        _reject("workload_review_receipt_not_current")

    return VerifiedTransitionWorkloadReview(
        evidence=bound_evidence,
        receipt=receipt,
        receipt_raw=receipt_raw,
        signature_raw=signature_raw,
        policy=policy,
        public_key_raw=trusted_public_key_raw,
        expected_bindings=bindings,
        externally_selected_trust_policy_digest=selected_policy_digest,
        _authority=_VERIFIED_AUTHORITY,
    )


def require_verified_transition_workload_review(
        value: Any,
        current_trust_policy: BoundExternalWorkloadReviewTrustPolicy,
        externally_selected_current_trust_policy_digest: str,
        ) -> VerifiedTransitionWorkloadReview:
    """Reverify retained bytes under caller-selected current policy and return fresh authority.

    The selected digest is an explicit application trust-anchor input, not proof of policy
    authenticity, succession, or organizational independence. Every authority consumer must
    obtain current policy and its digest from authenticated external custody and compare the
    returned token's ``bindings_digest`` to its independently selected candidate subject.
    """

    if type(value) is not VerifiedTransitionWorkloadReview:
        _reject("detached_or_unverified_transition_workload_review")
    try:
        historical = verify_transition_workload_review(
            bind_transition_workload_evidence_bytes(value._evidence_raw),
            value._receipt_raw,
            value._signature_raw,
            bind_external_workload_review_trust_policy_bytes(value._trust_policy_raw),
            value._trusted_public_key_raw,
            parse_canonical_json_bytes(value._expected_bindings_raw, require_canonical=True),
            value.externally_selected_trust_policy_digest,
        )
        intact = (
            historical._compute_integrity_digest() == value._compute_integrity_digest()
            and historical._integrity_digest == value._integrity_digest
            and historical._evidence_raw == value._evidence_raw
            and historical._receipt_raw == value._receipt_raw
            and historical._signature_raw == value._signature_raw
            and historical._trust_policy_raw == value._trust_policy_raw
            and historical._trusted_public_key_raw == value._trusted_public_key_raw
            and historical._expected_bindings_raw == value._expected_bindings_raw
        )
    except (AttributeError, TransitionContractError, TypeError, ValueError, WorkloadReviewError):
        intact = False
    if not intact:
        _reject("verified_transition_workload_review_mutated")
    current_policy = require_bound_workload_review_trust_policy(current_trust_policy)
    current_evaluated_at = _timestamp(current_policy["evaluated_at"], "$.evaluated_at")
    historical_evaluated_at = _timestamp(value.evaluated_at, "$.historical_evaluated_at")
    if current_evaluated_at < historical_evaluated_at:
        _reject("workload_review_policy_rollback")
    return verify_transition_workload_review(
        bind_transition_workload_evidence_bytes(value._evidence_raw),
        value._receipt_raw,
        value._signature_raw,
        current_policy,
        value._trusted_public_key_raw,
        parse_canonical_json_bytes(value._expected_bindings_raw, require_canonical=True),
        externally_selected_current_trust_policy_digest,
    )


__all__ = [
    "TRANSITION_WORKLOAD_EVIDENCE_SCHEMA",
    "WORKLOAD_REVIEW_ADEQUATE",
    "WORKLOAD_REVIEW_AUTHORIZATION_SCHEMA",
    "WORKLOAD_REVIEW_BINDINGS_SCHEMA",
    "WORKLOAD_REVIEW_INADEQUATE",
    "WORKLOAD_REVIEW_POLICY_KIND",
    "WORKLOAD_REVIEW_PURPOSE",
    "WORKLOAD_REVIEW_RECEIPT_SCHEMA",
    "WORKLOAD_REVIEW_REVIEWER_KIND",
    "WORKLOAD_REVIEW_REVIEWER_ROLE",
    "WORKLOAD_REVIEW_SIGNATURE_ALGORITHM",
    "WORKLOAD_REVIEW_SIGNATURE_SCHEMA",
    "WORKLOAD_REVIEW_SUBSTRATE",
    "WORKLOAD_REVIEW_TRUST_POLICY_SCHEMA",
    "WORKLOAD_REVIEW_TRUSTED_KEY_SCHEMA",
    "WORKLOAD_EVIDENCE_ABSENT",
    "WORKLOAD_EVIDENCE_CLAIM_BOUNDARY",
    "WORKLOAD_EVIDENCE_READY",
    "WORKLOAD_BINDING_DIGEST_FIELDS",
    "BoundExternalWorkloadReviewTrustPolicy",
    "BoundTransitionWorkloadEvidence",
    "VerifiedTransitionWorkloadReview",
    "WorkloadReviewError",
    "bind_external_workload_review_trust_policy_bytes",
    "bind_transition_workload_evidence_bytes",
    "require_bound_transition_workload_evidence",
    "require_bound_workload_review_trust_policy",
    "require_verified_transition_workload_review",
    "validate_transition_workload_evidence",
    "validate_workload_review_bindings",
    "validate_workload_review_receipt",
    "validate_workload_review_signature",
    "validate_workload_review_trust_policy",
    "verify_transition_workload_review",
    "workload_review_signing_material",
]
