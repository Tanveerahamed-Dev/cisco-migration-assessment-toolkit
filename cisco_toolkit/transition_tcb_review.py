"""External review boundary for Atlas R2 TCB budgets.

This module verifies one exact, purpose-bound Ed25519 review receipt against a separately supplied
trust policy and PEM public key.  A verified review approves only the numeric TCB budgets and the
DSL-only resource profile named by that receipt.  It is not pack qualification, does not make a
pack executable or promotion-eligible, and has no bundled trust roots or signing path.  The closed
independence fields are assertions made by that external policy; Atlas validates and binds them but
cannot prove the reviewer's real-world organizational independence from bytes alone.
"""

from __future__ import annotations

import base64
import re
from enum import Enum
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
    parse_canonical_json_bytes,
)


TCB_BUDGET_REVIEW_PURPOSE = "ATLAS_R2_TCB_BUDGET_REVIEW"
TCB_BUDGET_REVIEW_RECEIPT_SCHEMA = "atlas.tcb-budget-review-receipt/1"
TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA = "atlas.tcb-budget-review-signature/1"
TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA = "atlas.tcb-budget-review-trust-policy/1"
TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA = "atlas.tcb-budget-review-trusted-key/1"
TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA = "atlas.tcb-budget-review-authorization/1"
TCB_BUDGET_REVIEW_BINDINGS_SCHEMA = "atlas.tcb-budget-review-bindings/1"
TCB_BUDGET_REVIEW_SUBJECT_SCHEMA = "atlas.tcb-budget-review-subject/1"
DSL_RESOURCE_PROFILE_SCHEMA = "atlas.dsl-only-resource-profile/1"
TCB_MANIFEST_V2_SCHEMA = "atlas.tcb-manifest/2"
TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM = "Ed25519"
TCB_BUDGET_REVIEW_POLICY_KIND = "EXTERNAL_INDEPENDENT_TCB_BUDGET_REVIEW_KEY_ALLOWLIST"
TCB_BUDGET_REVIEWER_KIND = "INDEPENDENT_REVIEWER"
TCB_BUDGET_REVIEWER_ROLE = "TCB_BUDGET_AND_RESOURCE_CEILING_REVIEWER"
TCB_BUDGET_REVIEW_SUBSTRATE = "DECLARATIVE_DSL_ONLY"

DSL_RESOURCE_PROFILE_FIELDS = (
    "max_program_bytes",
    "max_input_bytes",
    "max_output_bytes",
    "max_rules",
    "max_expression_depth",
    "max_expression_nodes",
    "max_operator_operands",
    "max_path_segments",
    "max_string_bytes",
    "max_set_items",
    "max_input_nodes",
    "max_instruction_fuel",
)

_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_SIGNATURE_DOMAIN = b"ATLAS-R2-TCB-BUDGET-REVIEW\x00v1\x00"
_MAX_PUBLIC_KEY_BYTES = 16 * 1024
_TRUST_POLICY_AUTHORITY = object()
_VERIFIED_REVIEW_AUTHORITY = object()


class TCBBudgetReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TCBBudgetReviewError(ValueError):
    """Fixed-code, non-echoing refusal at the external review boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BoundTCBBudgetReviewTrustPolicy(dict):
    """Exact trust-policy bytes supplied independently from the review receipt."""

    __slots__ = ("_bound_digest", "_bound_source_bytes")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _TRUST_POLICY_AUTHORITY:
            raise TypeError("BoundTCBBudgetReviewTrustPolicy requires exact external bytes")
        super().__init__(value)
        self._bound_digest = digest
        self._bound_source_bytes = source_bytes

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class VerifiedTCBBudgetReview:
    """Sealed result of signature, trust, time, subject, and candidate verification."""

    __slots__ = (
        "review_digest",
        "signature_digest",
        "policy_digest",
        "trusted_public_key_digest",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_subject_digest",
        "core_sloc_budget",
        "pack_sloc_budget",
        "_dsl_resource_profile_items",
        "wasm_review_state",
        "measurement_denominator_digest",
        "decision",
        "issued_at",
        "valid_from",
        "valid_until",
        "reviewer_key_id",
        "evaluated_at",
        "approved",
        "_integrity_digest",
        "_sealed",
    )

    def __init__(
            self,
            *,
            review_digest: str,
            signature_digest: str,
            policy_digest: str,
            trusted_public_key_digest: str,
            receipt: Mapping[str, Any],
            evaluated_at: str,
            _authority: object) -> None:
        if _authority is not _VERIFIED_REVIEW_AUTHORITY:
            raise TypeError("VerifiedTCBBudgetReview requires external evidence verification")
        object.__setattr__(self, "_sealed", False)
        self.review_digest = review_digest
        self.signature_digest = signature_digest
        self.policy_digest = policy_digest
        self.trusted_public_key_digest = trusted_public_key_digest
        self.selected_commit = receipt["selected_commit"]
        self.selected_tree = receipt["selected_tree"]
        self.structural_census_digest = receipt["structural_census_digest"]
        self.prototype_measurement_digest = receipt["prototype_measurement_digest"]
        self.dsl_interpreter_digest = receipt["dsl_interpreter_digest"]
        self.prototype_program_digest = receipt["prototype_program_digest"]
        self.prototype_pack_manifest_digest = receipt["prototype_pack_manifest_digest"]
        self.tcb_subject_digest = receipt["tcb_budget_subject_digest"]
        self.core_sloc_budget = receipt["approved_core_sloc_budget"]
        self.pack_sloc_budget = receipt["approved_pack_sloc_budget"]
        profile = receipt["approved_dsl_resource_profile"]
        self._dsl_resource_profile_items = tuple(
            (key, profile[key]) for key in ("schema", "substrate", *DSL_RESOURCE_PROFILE_FIELDS)
        )
        self.wasm_review_state = receipt["wasm_review_state"]
        self.measurement_denominator_digest = receipt["measurement_denominator_digest"]
        self.decision = receipt["decision"]
        self.issued_at = receipt["issued_at"]
        self.valid_from = receipt["valid_from"]
        self.valid_until = receipt["valid_until"]
        self.reviewer_key_id = receipt["reviewer_key_id"]
        self.evaluated_at = evaluated_at
        self.approved = self.decision == TCBBudgetReviewDecision.APPROVED.value
        object.__setattr__(self, "_integrity_digest", self._compute_integrity_digest())
        object.__setattr__(self, "_sealed", True)

    @property
    def dsl_resource_profile(self) -> dict[str, Any]:
        """Return an ordinary detached dict; callers cannot mutate the sealed review through it."""

        return dict(self._dsl_resource_profile_items)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("VerifiedTCBBudgetReview is immutable")
        object.__setattr__(self, name, value)

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "review_digest": self.review_digest,
            "signature_digest": self.signature_digest,
            "policy_digest": self.policy_digest,
            "trusted_public_key_digest": self.trusted_public_key_digest,
            "selected_commit": self.selected_commit,
            "selected_tree": self.selected_tree,
            "structural_census_digest": self.structural_census_digest,
            "prototype_measurement_digest": self.prototype_measurement_digest,
            "dsl_interpreter_digest": self.dsl_interpreter_digest,
            "prototype_program_digest": self.prototype_program_digest,
            "prototype_pack_manifest_digest": self.prototype_pack_manifest_digest,
            "tcb_subject_digest": self.tcb_subject_digest,
            "core_sloc_budget": self.core_sloc_budget,
            "pack_sloc_budget": self.pack_sloc_budget,
            "dsl_resource_profile": self.dsl_resource_profile,
            "wasm_review_state": self.wasm_review_state,
            "measurement_denominator_digest": self.measurement_denominator_digest,
            "decision": self.decision,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "reviewer_key_id": self.reviewer_key_id,
            "evaluated_at": self.evaluated_at,
            "approved": self.approved,
        })


def _reject(code: str) -> None:
    raise TCBBudgetReviewError(code)


def _git_object(value: Any, path: str) -> str:
    text = _text(value, path)
    if not _GIT_OBJECT_RE.fullmatch(text):
        raise TransitionContractError("GIT_OBJECT_ID_REQUIRED", path)
    return text


def _sorted_unique_git_objects(value: Any, path: str) -> list[str]:
    items = _array(value, path)
    checked = [_git_object(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if not checked or checked != sorted(set(checked)):
        raise TransitionContractError("SORTED_UNIQUE_GIT_OBJECTS_REQUIRED", path)
    return checked


def validate_dsl_resource_profile(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$.approved_dsl_resource_profile")
    keys = ("schema", "substrate", *DSL_RESOURCE_PROFILE_FIELDS)
    _exact_keys(obj, keys, "$.approved_dsl_resource_profile")
    _schema(obj, DSL_RESOURCE_PROFILE_SCHEMA, "$.approved_dsl_resource_profile")
    if obj["substrate"] != "DECLARATIVE_DSL_ONLY":
        raise TransitionContractError(
            "DSL_ONLY_RESOURCE_PROFILE_REQUIRED", "$.approved_dsl_resource_profile.substrate"
        )
    for key in DSL_RESOURCE_PROFILE_FIELDS:
        _integer(obj[key], f"$.approved_dsl_resource_profile.{key}", positive=True)
    return dict(obj)


def validate_tcb_budget_review_receipt(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "receipt_id",
        "purpose",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_budget_subject_digest",
        "approved_core_sloc_budget",
        "approved_pack_sloc_budget",
        "approved_dsl_resource_profile",
        "wasm_review_state",
        "measurement_denominator_digest",
        "decision",
        "issued_at",
        "valid_from",
        "valid_until",
        "reviewer_key_id",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_RECEIPT_SCHEMA, "$")
    _identifier(obj["receipt_id"], "$.receipt_id")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for key in (
            "structural_census_digest",
            "prototype_measurement_digest",
            "dsl_interpreter_digest",
            "prototype_program_digest",
            "prototype_pack_manifest_digest",
            "tcb_budget_subject_digest",
            "measurement_denominator_digest"):
        _digest(obj[key], f"$.{key}")
    _integer(obj["approved_core_sloc_budget"], "$.approved_core_sloc_budget", positive=True)
    _integer(obj["approved_pack_sloc_budget"], "$.approved_pack_sloc_budget", positive=True)
    validate_dsl_resource_profile(obj["approved_dsl_resource_profile"])
    if obj["wasm_review_state"] != "UNREVIEWED":
        raise TransitionContractError("WASM_REVIEW_MUST_REMAIN_UNREVIEWED", "$.wasm_review_state")
    try:
        TCBBudgetReviewDecision(obj["decision"])
    except (TypeError, ValueError):
        raise TransitionContractError("UNKNOWN_TCB_BUDGET_REVIEW_DECISION", "$.decision") from None
    issued_at = _timestamp(obj["issued_at"], "$.issued_at")
    valid_from = _timestamp(obj["valid_from"], "$.valid_from")
    valid_until = _timestamp(obj["valid_until"], "$.valid_until")
    if issued_at > valid_from or valid_from >= valid_until:
        raise TransitionContractError("TCB_BUDGET_REVIEW_TIME_RANGE_INVALID", "$")
    _identifier(obj["reviewer_key_id"], "$.reviewer_key_id")
    return dict(obj)


def validate_tcb_budget_review_signature(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "purpose",
        "payload_digest",
        "trust_policy_digest",
        "signer_key_id",
        "algorithm",
        "signature_base64",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA, "$")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _digest(obj["payload_digest"], "$.payload_digest")
    _digest(obj["trust_policy_digest"], "$.trust_policy_digest")
    _identifier(obj["signer_key_id"], "$.signer_key_id")
    if obj["algorithm"] != TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM:
        raise TransitionContractError("TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM", "$.algorithm")
    encoded = _text(obj["signature_base64"], "$.signature_base64")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        _reject("tcb_budget_review_signature_malformed")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
        _reject("tcb_budget_review_signature_malformed")
    return dict(obj)


def validate_tcb_budget_review_bindings(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_budget_subject_digest",
        "measurement_denominator_digest",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_BINDINGS_SCHEMA, "$")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for key in keys[3:]:
        _digest(obj[key], f"$.{key}")
    return dict(obj)


def validate_tcb_budget_review_trust_policy(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "policy_kind",
        "policy_id",
        "policy_version",
        "purpose",
        "evaluated_at",
        "trusted_keys",
        "revoked_receipt_digests",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA, "$")
    if obj["policy_kind"] != TCB_BUDGET_REVIEW_POLICY_KIND:
        raise TransitionContractError("TCB_BUDGET_REVIEW_POLICY_KIND_MISMATCH", "$.policy_kind")
    _identifier(obj["policy_id"], "$.policy_id")
    _identifier(obj["policy_version"], "$.policy_version")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _timestamp(obj["evaluated_at"], "$.evaluated_at")
    trusted_keys = _array(obj["trusted_keys"], "$.trusted_keys")
    if not trusted_keys:
        raise TransitionContractError("TCB_BUDGET_REVIEW_TRUST_KEY_REQUIRED", "$.trusted_keys")
    key_ids: list[str] = []
    for index, value_item in enumerate(trusted_keys):
        path = f"$.trusted_keys[{index}]"
        item = _mapping(value_item, path)
        _exact_keys(
            item,
            (
                "schema",
                "key_id",
                "public_key_digest",
                "reviewer_kind",
                "independent_from_budget_proposer",
                "independent_from_prototype_and_measurement_producer",
                "independent_from_release_builder",
                "authorizations",
                "allowed_selected_commits",
                "allowed_selected_trees",
                "allowed_tcb_subject_digests",
                "valid_from",
                "valid_until",
            ),
            path,
        )
        _schema(item, TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA, path)
        key_ids.append(_identifier(item["key_id"], f"{path}.key_id"))
        _digest(item["public_key_digest"], f"{path}.public_key_digest")
        if (
                item["reviewer_kind"] != TCB_BUDGET_REVIEWER_KIND
                or item["independent_from_budget_proposer"] is not True
                or item["independent_from_prototype_and_measurement_producer"] is not True
                or item["independent_from_release_builder"] is not True
        ):
            raise TransitionContractError(
                "TCB_BUDGET_REVIEWER_INDEPENDENCE_REQUIRED",
                path,
            )
        authorizations = _array(item["authorizations"], f"{path}.authorizations")
        expected_authorization = {
            "schema": TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA,
            "purpose": TCB_BUDGET_REVIEW_PURPOSE,
            "target_schema_version": TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
            "reviewer_role": TCB_BUDGET_REVIEWER_ROLE,
            "substrate": TCB_BUDGET_REVIEW_SUBSTRATE,
        }
        if authorizations != [expected_authorization]:
            raise TransitionContractError(
                "TCB_BUDGET_REVIEWER_AUTHORIZATION_REQUIRED",
                f"{path}.authorizations",
            )
        _sorted_unique_git_objects(item["allowed_selected_commits"], f"{path}.allowed_selected_commits")
        _sorted_unique_git_objects(item["allowed_selected_trees"], f"{path}.allowed_selected_trees")
        _sorted_unique_digests(item["allowed_tcb_subject_digests"], f"{path}.allowed_tcb_subject_digests")
        valid_from = _timestamp(item["valid_from"], f"{path}.valid_from")
        valid_until = _timestamp(item["valid_until"], f"{path}.valid_until")
        if valid_from >= valid_until:
            raise TransitionContractError("TCB_BUDGET_REVIEW_KEY_TIME_RANGE_INVALID", path)
    if key_ids != sorted(set(key_ids)):
        raise TransitionContractError("SORTED_UNIQUE_TCB_REVIEW_KEY_IDS_REQUIRED", "$.trusted_keys")
    _sorted_unique_digests(
        obj["revoked_receipt_digests"], "$.revoked_receipt_digests", allow_empty=True
    )
    return dict(obj)


def bind_external_tcb_budget_review_trust_policy_bytes(
        raw: bytes) -> BoundTCBBudgetReviewTrustPolicy:
    """Bind exact independently supplied trust-policy bytes."""

    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
        checked = validate_tcb_budget_review_trust_policy(value)
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_trust_policy_malformed")
    digest = canonical_digest(checked)
    if digest != bytes_digest(raw):
        _reject("tcb_budget_review_trust_policy_malformed")
    return BoundTCBBudgetReviewTrustPolicy(
        checked,
        digest=digest,
        source_bytes=len(raw),
        _authority=_TRUST_POLICY_AUTHORITY,
    )


def require_bound_tcb_budget_review_trust_policy(
        value: Any) -> BoundTCBBudgetReviewTrustPolicy:
    if type(value) is not BoundTCBBudgetReviewTrustPolicy:
        _reject("external_tcb_budget_review_trust_policy_required")
    try:
        checked = validate_tcb_budget_review_trust_policy(dict(value))
        intact = canonical_digest(checked) == value.digest
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        intact = False
    if not intact:
        _reject("bound_tcb_budget_review_trust_policy_mutated")
    return value


def _signed_material(receipt_raw: bytes, policy_digest: str) -> bytes:
    return (
        _SIGNATURE_DOMAIN
        + TCB_BUDGET_REVIEW_PURPOSE.encode("ascii")
        + b"\x00"
        + TCB_BUDGET_REVIEW_RECEIPT_SCHEMA.encode("ascii")
        + b"\x00"
        + policy_digest.encode("ascii")
        + b"\x00"
        + receipt_raw
    )


def tcb_budget_review_signing_material(receipt_raw: bytes, trust_policy_raw: bytes) -> bytes:
    """Return the exact domain-separated bytes an external reviewer signs."""

    try:
        receipt = validate_tcb_budget_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        policy = validate_tcb_budget_review_trust_policy(
            parse_canonical_json_bytes(trust_policy_raw, require_canonical=True)
        )
        if canonical_digest(receipt) != bytes_digest(receipt_raw):
            raise TransitionContractError("TCB_BUDGET_REVIEW_RECEIPT_DIGEST_MISMATCH", "$")
        if canonical_digest(policy) != bytes_digest(trust_policy_raw):
            raise TransitionContractError("TCB_BUDGET_REVIEW_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_signing_input_malformed")
    return _signed_material(receipt_raw, bytes_digest(trust_policy_raw))


def tcb_budget_review_subject_digest(tcb_mapping: Mapping[str, Any]) -> str:
    """Digest a TCB v2 basis with both detached-receipt slots normalized to null."""

    try:
        if type(tcb_mapping) is not dict or tcb_mapping.get("schema") != TCB_MANIFEST_V2_SCHEMA:
            raise TransitionContractError("TCB_V2_REQUIRED", "$")
        for slot in ("budget_review_receipt_digest", "qualification_receipt_digest"):
            if slot not in tcb_mapping:
                raise TransitionContractError("TCB_RECEIPT_SLOT_REQUIRED", "$")
            _digest(tcb_mapping[slot], f"$.{slot}", optional=True)
        basis = dict(tcb_mapping)
        basis["budget_review_receipt_digest"] = None
        basis["qualification_receipt_digest"] = None
        return canonical_digest({
            "schema": TCB_BUDGET_REVIEW_SUBJECT_SCHEMA,
            "purpose": TCB_BUDGET_REVIEW_PURPOSE,
            "tcb_manifest": basis,
        })
    except (TransitionContractError, TypeError):
        _reject("tcb_budget_review_subject_invalid")
    raise AssertionError("unreachable")


def verify_tcb_budget_review_evidence(
        receipt_raw: bytes,
        signature_raw: bytes,
        trust_policy: BoundTCBBudgetReviewTrustPolicy,
        trusted_public_key_raw: bytes,
        expected_bindings: Mapping[str, Any]) -> VerifiedTCBBudgetReview:
    """Verify exact review evidence and bind it to the caller's current candidate/evidence set."""

    try:
        receipt = validate_tcb_budget_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_evidence_malformed")
    try:
        signature = validate_tcb_budget_review_signature(
            parse_canonical_json_bytes(signature_raw, require_canonical=True)
        )
    except TCBBudgetReviewError:
        raise
    except (TransitionContractError, TypeError):
        _reject("tcb_budget_review_signature_malformed")
    policy = require_bound_tcb_budget_review_trust_policy(trust_policy)
    try:
        bindings = validate_tcb_budget_review_bindings(dict(expected_bindings))
    except (TransitionContractError, TypeError, ValueError):
        _reject("tcb_budget_review_expected_bindings_malformed")
    if (
            type(trusted_public_key_raw) is not bytes
            or not trusted_public_key_raw
            or len(trusted_public_key_raw) > _MAX_PUBLIC_KEY_BYTES
    ):
        _reject("tcb_budget_review_public_key_malformed")

    for key in (
            "selected_commit",
            "selected_tree",
            "structural_census_digest",
            "prototype_measurement_digest",
            "dsl_interpreter_digest",
            "prototype_program_digest",
            "prototype_pack_manifest_digest",
            "tcb_budget_subject_digest",
            "measurement_denominator_digest"):
        if receipt[key] != bindings[key]:
            _reject("tcb_budget_review_candidate_binding_mismatch")

    review_digest = bytes_digest(receipt_raw)
    if (
            signature["payload_digest"] != review_digest
            or signature["trust_policy_digest"] != policy.digest
            or signature["signer_key_id"] != receipt["reviewer_key_id"]
    ):
        _reject("tcb_budget_review_signature_binding_mismatch")

    trusted_key = next(
        (item for item in policy["trusted_keys"] if item["key_id"] == receipt["reviewer_key_id"]),
        None,
    )
    if trusted_key is None:
        _reject("tcb_budget_review_key_not_trusted")
    if trusted_key["public_key_digest"] != bytes_digest(trusted_public_key_raw):
        _reject("tcb_budget_review_key_not_trusted")
    if (
            receipt["selected_commit"] not in trusted_key["allowed_selected_commits"]
            or receipt["selected_tree"] not in trusted_key["allowed_selected_trees"]
            or receipt["tcb_budget_subject_digest"]
            not in trusted_key["allowed_tcb_subject_digests"]
    ):
        _reject("tcb_budget_review_subject_not_authorized")

    evaluated_at = _timestamp(policy["evaluated_at"], "$.evaluated_at")
    key_valid_from = _timestamp(trusted_key["valid_from"], "$.trusted_keys[].valid_from")
    key_valid_until = _timestamp(trusted_key["valid_until"], "$.trusted_keys[].valid_until")
    if not key_valid_from <= evaluated_at <= key_valid_until:
        _reject("tcb_budget_review_key_not_valid_at_policy_time")
    issued_at = _timestamp(receipt["issued_at"], "$.issued_at")
    if not key_valid_from <= issued_at <= key_valid_until:
        _reject("tcb_budget_review_key_not_valid_at_receipt_time")

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = serialization.load_pem_public_key(trusted_public_key_raw)
        if not isinstance(public_key, Ed25519PublicKey):
            _reject("tcb_budget_review_public_key_malformed")
        raw_signature = base64.b64decode(signature["signature_base64"], validate=True)
        public_key.verify(raw_signature, _signed_material(receipt_raw, policy.digest))
    except TCBBudgetReviewError:
        raise
    except ImportError:
        _reject("tcb_budget_review_crypto_runtime_unavailable")
    except Exception:
        _reject("tcb_budget_review_signature_invalid")

    if review_digest in policy["revoked_receipt_digests"]:
        _reject("tcb_budget_review_receipt_revoked")
    valid_from = _timestamp(receipt["valid_from"], "$.valid_from")
    valid_until = _timestamp(receipt["valid_until"], "$.valid_until")
    if not valid_from <= evaluated_at <= valid_until:
        _reject("tcb_budget_review_receipt_not_current")

    return VerifiedTCBBudgetReview(
        review_digest=review_digest,
        signature_digest=bytes_digest(signature_raw),
        policy_digest=policy.digest,
        trusted_public_key_digest=bytes_digest(trusted_public_key_raw),
        receipt=receipt,
        evaluated_at=policy["evaluated_at"],
        _authority=_VERIFIED_REVIEW_AUTHORITY,
    )


def require_verified_tcb_budget_review(value: Any) -> VerifiedTCBBudgetReview:
    """Require an intact object minted by :func:`verify_tcb_budget_review_evidence`."""

    if type(value) is not VerifiedTCBBudgetReview:
        _reject("detached_or_unverified_tcb_budget_review")
    try:
        intact = value._compute_integrity_digest() == value._integrity_digest
    except (TransitionContractError, TypeError, AttributeError):
        intact = False
    if not intact:
        _reject("verified_tcb_budget_review_mutated")
    return value


__all__ = [
    "DSL_RESOURCE_PROFILE_FIELDS",
    "DSL_RESOURCE_PROFILE_SCHEMA",
    "BoundTCBBudgetReviewTrustPolicy",
    "TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA",
    "TCB_BUDGET_REVIEW_BINDINGS_SCHEMA",
    "TCB_BUDGET_REVIEW_PURPOSE",
    "TCB_BUDGET_REVIEW_POLICY_KIND",
    "TCB_BUDGET_REVIEW_RECEIPT_SCHEMA",
    "TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM",
    "TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA",
    "TCB_BUDGET_REVIEW_SUBJECT_SCHEMA",
    "TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA",
    "TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA",
    "TCB_BUDGET_REVIEWER_KIND",
    "TCB_BUDGET_REVIEWER_ROLE",
    "TCB_BUDGET_REVIEW_SUBSTRATE",
    "TCBBudgetReviewDecision",
    "TCBBudgetReviewError",
    "VerifiedTCBBudgetReview",
    "bind_external_tcb_budget_review_trust_policy_bytes",
    "require_bound_tcb_budget_review_trust_policy",
    "require_verified_tcb_budget_review",
    "tcb_budget_review_signing_material",
    "tcb_budget_review_subject_digest",
    "validate_dsl_resource_profile",
    "validate_tcb_budget_review_bindings",
    "validate_tcb_budget_review_receipt",
    "validate_tcb_budget_review_signature",
    "validate_tcb_budget_review_trust_policy",
    "verify_tcb_budget_review_evidence",
]
