"""Deterministic R2.0 structural verifier and closed machine-eligibility mapping.

The verifier consumes only process-bound canonical cases, exact content bytes, bound pack
manifests, and signature-verified qualification objects.  UI/API strings cannot mint any of those
authorities.  The current R2.0 executable slice intentionally keeps pack execution, package
confidentiality enforcement, and sealed replay conformance unavailable; those missing authorities
map to ``EVIDENCE_INCOMPLETE`` rather than being papered over by convention.
"""

from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from copy import deepcopy
from enum import Enum
from typing import Any, Mapping, Sequence

from .transition_contract import (
    TRANSITION_SEMANTICS_VERSION,
    WORDING_POLICY_VERSION,
    ApplicabilityKind,
    AuthoritativeGate,
    BoundTransitionCase,
    CaseMode,
    EvidenceStatus,
    ObservationMode,
    QualificationState,
    TemporalOperator,
    TemporalOutcome,
    TransitionContractError,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    gate_wording,
    require_bound_transition_case,
    wording_policy_digest,
)
from .transition_pack import (
    BoundTrustPolicy,
    PackExecutionState,
    QualificationSubjectKind,
    VerifiedQualification,
    pack_qualification_subject_digest,
    qualification_subject_digest,
    require_bound_pack_manifest,
    require_bound_tcb_manifest,
    require_bound_trust_policy,
    require_verified_qualification,
    validate_pack_tcb_pair,
)
from .transition_tcb_review import require_bound_r2_tcb_budget_freeze


VERIFIER_RECEIPT_SCHEMA = "atlas.transition-verifier-receipt/1"
INVALIDATION_RECEIPT_SCHEMA = "atlas.transition-invalidation-receipt/1"
TEMPORAL_MONITOR_RESULT_SCHEMA = "atlas.temporal-monitor-result/1"
VERIFIER_VERSION = "ATLAS_STRUCTURAL_VERIFIER/1"
VERIFIER_CLAIM_BOUNDARY = (
    "Machine eligibility is not human approval. Atlas never emits autonomous GO. R2.0 does not "
    "establish qualified pack execution, sealed-portable replay, or confidentiality enforcement."
)
INVALIDATION_CLAIM_BOUNDARY = (
    "Reference-only deterministic dependency comparison; not an authoritative verifier receipt, "
    "qualification decision, or promotion signal."
)

# First-prototype safety limits, not independently reviewed qualification budgets.
PROVISIONAL_MAX_CONTENT_OBJECTS = 10_000
PROVISIONAL_MAX_SINGLE_CONTENT_BYTES = 64 * 1024 * 1024
PROVISIONAL_MAX_TOTAL_CONTENT_BYTES = 256 * 1024 * 1024

_BOUND_CONTENT_AUTHORITY = object()
_VERIFIER_RECEIPT_AUTHORITY = object()


class GateDisposition(str, Enum):
    NO_CASE = "NO_CASE"
    NO_AUTHORITATIVE_GATE = "NO_AUTHORITATIVE_GATE"
    AUTHORITATIVE_GATE = "AUTHORITATIVE_GATE"


class ReplayStatus(str, Enum):
    PROJECTION_ONLY_NON_AUTHORITATIVE = "PROJECTION_ONLY_NON_AUTHORITATIVE"
    EXTERNAL_EVIDENCE_REQUIRED = "EXTERNAL_EVIDENCE_REQUIRED"
    REFERENCED_CONTENT_AVAILABLE_PORTABILITY_NOT_ESTABLISHED = (
        "REFERENCED_CONTENT_AVAILABLE_PORTABILITY_NOT_ESTABLISHED"
    )
    SEALED_CONTENT_INCOMPLETE = "SEALED_CONTENT_INCOMPLETE"
    SEALED_BYTES_PRESENT_INDEPENDENT_REPLAY_NOT_ESTABLISHED = (
        "SEALED_BYTES_PRESENT_INDEPENDENT_REPLAY_NOT_ESTABLISHED"
    )


class SecurityStatus(str, Enum):
    SECURITY_CONTRACT_NOT_ENFORCED = "SECURITY_CONTRACT_NOT_ENFORCED"
    SECURITY_EVIDENCE_NOT_VERIFIED = "SECURITY_EVIDENCE_NOT_VERIFIED"


class BoundContentSet:
    """Exact content bytes indexed only by hashes computed by this process."""

    __slots__ = ("_objects", "_total_bytes", "_integrity_digest")

    def __init__(self, objects: Mapping[str, bytes], *, total_bytes: int, _authority: object) -> None:
        if _authority is not _BOUND_CONTENT_AUTHORITY:
            raise TypeError("BoundContentSet can only be minted from exact bytes")
        self._objects = dict(objects)
        self._total_bytes = total_bytes
        self._integrity_digest = self._compute_integrity_digest()

    def _compute_integrity_digest(self) -> str:
        checked: list[dict[str, Any]] = []
        total = 0
        for digest, raw in sorted(self._objects.items()):
            if type(digest) is not str or type(raw) is not bytes or bytes_digest(raw) != digest:
                raise TransitionContractError("BOUND_CONTENT_SET_MUTATED")
            total += len(raw)
            checked.append({"digest": digest, "size": len(raw)})
        if total != self._total_bytes:
            raise TransitionContractError("BOUND_CONTENT_SET_MUTATED")
        return canonical_digest({"objects": checked, "total_bytes": total})

    def _require_integrity(self) -> None:
        if self._compute_integrity_digest() != self._integrity_digest:
            raise TransitionContractError("BOUND_CONTENT_SET_MUTATED")

    @property
    def digests(self) -> tuple[str, ...]:
        self._require_integrity()
        return tuple(sorted(self._objects))

    @property
    def total_bytes(self) -> int:
        self._require_integrity()
        return self._total_bytes

    def contains(self, digest: str) -> bool:
        self._require_integrity()
        return digest in self._objects

    def bytes_for(self, digest: str) -> bytes | None:
        self._require_integrity()
        value = self._objects.get(digest)
        return None if value is None else bytes(value)


class BoundVerifierReceipt(ABCMapping[str, Any]):
    """Process-local authority over an unchanged verifier-minted receipt."""

    __slots__ = ("_bound_digest", "_value")

    def __init__(self, value: Mapping[str, Any], *, digest: str, _authority: object) -> None:
        if _authority is not _VERIFIER_RECEIPT_AUTHORITY:
            raise TypeError("BoundVerifierReceipt can only be minted by the transition verifier")
        self._value = deepcopy(dict(value))
        self._bound_digest = digest

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._value[key])

    def __iter__(self):
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    @property
    def digest(self) -> str:
        return self._bound_digest


def bind_content_objects(objects: Sequence[bytes]) -> BoundContentSet:
    """Hash exact bytes; caller-provided digest labels are never accepted."""

    if type(objects) not in (list, tuple):
        raise TypeError("content objects must be a list or tuple of bytes")
    if len(objects) > PROVISIONAL_MAX_CONTENT_OBJECTS:
        raise TransitionContractError("PROVISIONAL_CONTENT_OBJECT_LIMIT")
    bound: dict[str, bytes] = {}
    total = 0
    for index, raw in enumerate(objects):
        if type(raw) is not bytes:
            raise TransitionContractError("CONTENT_OBJECT_MUST_BE_BYTES", f"$[{index}]")
        if len(raw) > PROVISIONAL_MAX_SINGLE_CONTENT_BYTES:
            raise TransitionContractError("PROVISIONAL_SINGLE_CONTENT_LIMIT", f"$[{index}]")
        total += len(raw)
        if total > PROVISIONAL_MAX_TOTAL_CONTENT_BYTES:
            raise TransitionContractError("PROVISIONAL_TOTAL_CONTENT_LIMIT")
        digest = bytes_digest(raw)
        if digest in bound:
            raise TransitionContractError("DUPLICATE_CONTENT_DIGEST", f"$[{index}]")
        bound[digest] = bytes(raw)
    return BoundContentSet(bound, total_bytes=total, _authority=_BOUND_CONTENT_AUTHORITY)


def _empty_content_set() -> BoundContentSet:
    return BoundContentSet({}, total_bytes=0, _authority=_BOUND_CONTENT_AUTHORITY)


def require_bound_content_set(value: Any) -> BoundContentSet:
    if not isinstance(value, BoundContentSet):
        raise TransitionContractError("DETACHED_CONTENT_SET")
    if value._compute_integrity_digest() != value._integrity_digest:
        raise TransitionContractError("BOUND_CONTENT_SET_MUTATED")
    return value


def four_valued_evidence_status(valid_support: bool, valid_counter_evidence: bool) -> str:
    """The closed, orthogonal support/counter-evidence truth table."""

    if type(valid_support) is not bool or type(valid_counter_evidence) is not bool:
        raise TypeError("evidence axes must be booleans")
    if valid_support and valid_counter_evidence:
        return EvidenceStatus.CONFLICTING.value
    if valid_support:
        return EvidenceStatus.SUPPORTED.value
    if valid_counter_evidence:
        return EvidenceStatus.REFUTED.value
    return EvidenceStatus.UNKNOWN.value


def map_authoritative_gate(
        *,
        applicability_kind: str,
        qualification_state: str | None,
        mandatory_evidence_statuses: Sequence[str],
        evaluator_complete: bool,
        certificates_complete: bool) -> tuple[str, str | None]:
    """Map closed upstream semantics to no-case/no-gate or exactly one of four gate states.

    Mixed-obligation severity is deterministic and permutation-independent:
    breach > conflict > incomplete > eligible.  This is a safety precedence, never a score.
    """

    if type(evaluator_complete) is not bool or type(certificates_complete) is not bool:
        raise TypeError("gate completeness axes must be booleans")
    try:
        applicability = ApplicabilityKind(applicability_kind)
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_APPLICABILITY_KIND") from None
    statuses: list[EvidenceStatus] = []
    for item in mandatory_evidence_statuses:
        try:
            statuses.append(EvidenceStatus(item))
        except (ValueError, TypeError):
            raise TransitionContractError("UNKNOWN_EVIDENCE_STATUS") from None
    if applicability is ApplicabilityKind.NOT_APPLICABLE:
        return GateDisposition.NO_CASE.value, None
    if applicability is ApplicabilityKind.APPLICABILITY_EVIDENCE_REQUIRED:
        return GateDisposition.NO_AUTHORITATIVE_GATE.value, None
    if qualification_state is None:
        qualification = None
    else:
        try:
            qualification = QualificationState(qualification_state)
        except (ValueError, TypeError):
            raise TransitionContractError("UNKNOWN_QUALIFICATION_STATE") from None
    if qualification is not QualificationState.QUALIFIED:
        return GateDisposition.AUTHORITATIVE_GATE.value, AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    if any(item is EvidenceStatus.REFUTED for item in statuses):
        return GateDisposition.AUTHORITATIVE_GATE.value, AuthoritativeGate.OBSERVED_BREACH.value
    if any(item is EvidenceStatus.CONFLICTING for item in statuses):
        return (
            GateDisposition.AUTHORITATIVE_GATE.value,
            AuthoritativeGate.CONFLICT_REQUIRES_RESOLUTION.value,
        )
    if (
            not statuses
            or any(item is EvidenceStatus.UNKNOWN for item in statuses)
            or not evaluator_complete
            or not certificates_complete
    ):
        return GateDisposition.AUTHORITATIVE_GATE.value, AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    return GateDisposition.AUTHORITATIVE_GATE.value, AuthoritativeGate.ELIGIBLE_FOR_HUMAN_DECISION.value


def _qualification_for(
        value: VerifiedQualification | None,
        *,
        receipt_digest: str,
        signature_digest: str,
        public_key_digest: str,
        subject_kind: str,
        subject_id: str,
        subject_version: str,
        subject_digest: str,
        denominator_digest: str,
        trust_policy_digest: str | None) -> tuple[str | None, list[str]]:
    if trust_policy_digest is None:
        return None, ["EXTERNAL_TRUST_POLICY_REQUIRED"]
    if not isinstance(value, VerifiedQualification):
        return None, ["QUALIFICATION_RECEIPT_NOT_VERIFIED"]
    try:
        require_verified_qualification(value)
    except ValueError:
        return None, ["QUALIFICATION_RECEIPT_NOT_VERIFIED"]
    reasons: list[str] = []
    expected = (
        (value.receipt_digest, receipt_digest, "QUALIFICATION_RECEIPT_DIGEST_MISMATCH"),
        (value.signature_digest, signature_digest, "QUALIFICATION_SIGNATURE_DIGEST_MISMATCH"),
        (value.public_key_digest, public_key_digest, "QUALIFICATION_PUBLIC_KEY_DIGEST_MISMATCH"),
        (value.subject_kind, subject_kind, "QUALIFICATION_SUBJECT_KIND_MISMATCH"),
        (value.subject_id, subject_id, "QUALIFICATION_SUBJECT_ID_MISMATCH"),
        (value.subject_version, subject_version, "QUALIFICATION_SUBJECT_VERSION_MISMATCH"),
        (value.subject_digest, subject_digest, "QUALIFICATION_SUBJECT_DIGEST_MISMATCH"),
        (value.denominator_digest, denominator_digest, "QUALIFICATION_DENOMINATOR_MISMATCH"),
        (value.policy_digest, trust_policy_digest, "QUALIFICATION_TRUST_POLICY_MISMATCH"),
    )
    for actual, wanted, code in expected:
        if actual != wanted:
            reasons.append(code)
    if value.policy_evaluated_state == QualificationState.REVOKED.value:
        reasons.append("QUALIFICATION_RECEIPT_REVOKED")
    elif value.policy_evaluated_state == QualificationState.EXPIRED.value:
        reasons.append("QUALIFICATION_RECEIPT_EXPIRED")
    elif value.policy_evaluated_state != QualificationState.QUALIFIED.value:
        reasons.append("QUALIFICATION_STATE_NOT_QUALIFIED")
    if not value.policy_approved or value.state is None:
        reasons.append("QUALIFICATION_POLICY_NOT_APPROVED_R2_0")
        return None, sorted(set(reasons))
    return (value.state if not reasons else None), sorted(set(reasons))


def _replay_status(case: Mapping[str, Any], content: BoundContentSet) -> tuple[str, list[str]]:
    mode = CaseMode(case["case_mode"])
    required = [
        item for item in case["replay_contract"]["object_bindings"] if item["required"]
    ]
    missing = [item["digest"] for item in required if not content.contains(item["digest"])]
    if mode is CaseMode.PROJECTION_ONLY:
        return ReplayStatus.PROJECTION_ONLY_NON_AUTHORITATIVE.value, ["PROJECTION_CANNOT_MINT_AUTHORITY"]
    if mode is CaseMode.REFERENCED:
        if missing:
            return ReplayStatus.EXTERNAL_EVIDENCE_REQUIRED.value, ["EXTERNAL_EVIDENCE_REQUIRED"]
        return (
            ReplayStatus.REFERENCED_CONTENT_AVAILABLE_PORTABILITY_NOT_ESTABLISHED.value,
            ["REFERENCED_CASE_NOT_PORTABLE"],
        )
    if missing:
        return ReplayStatus.SEALED_CONTENT_INCOMPLETE.value, ["SEALED_REQUIRED_CONTENT_MISSING"]
    return (
        ReplayStatus.SEALED_BYTES_PRESENT_INDEPENDENT_REPLAY_NOT_ESTABLISHED.value,
        ["SEALED_REPLAY_CONFORMANCE_NOT_QUALIFIED"],
    )


def _security_status(case: Mapping[str, Any]) -> tuple[str, list[str]]:
    protection = case["security_contract"]["evidence_protection"]
    if protection == "CONTRACT_ONLY":
        return SecurityStatus.SECURITY_CONTRACT_NOT_ENFORCED.value, ["SECURITY_CONTRACT_ONLY"]
    return SecurityStatus.SECURITY_EVIDENCE_NOT_VERIFIED.value, ["SECURITY_CONTROL_RECEIPT_NOT_VERIFIED"]


def _profile_qualification(
        profile: Mapping[str, Any],
        profile_digest: str,
        value: VerifiedQualification | None,
        trust_policy_digest: str | None,
        qualification_evidence_by_receipt: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, list[str]]:
    receipt_digest = profile["qualification_receipt_digest"]
    if receipt_digest is None:
        return None, ["OBSERVATION_PROFILE_UNQUALIFIED"]
    evidence_binding = qualification_evidence_by_receipt[receipt_digest]
    return _qualification_for(
        value,
        receipt_digest=receipt_digest,
        signature_digest=evidence_binding["signature_digest"],
        public_key_digest=evidence_binding["public_key_digest"],
        subject_kind=QualificationSubjectKind.OBSERVATION_PROFILE.value,
        subject_id=profile["profile_id"],
        subject_version="1",
        subject_digest=qualification_subject_digest(
            QualificationSubjectKind.OBSERVATION_PROFILE.value,
            profile,
        ),
        denominator_digest=profile["qualification_denominator_digest"],
        trust_policy_digest=trust_policy_digest,
    )


def monitor_temporal_obligation(
        case: BoundTransitionCase,
        obligation_id: str,
        profile_qualification: VerifiedQualification | None,
        *,
        trust_policy: BoundTrustPolicy | None = None,
        content: BoundContentSet | None = None) -> dict[str, Any]:
    """Return a fail-closed R2.0 temporal diagnostic, never a latent truth result.

    R2.0 freezes the profile, operator, evidence, denominator, and qualification boundaries.  The
    executable temporal truth table belongs to R2.2 and is intentionally not activated here: an
    incomplete dormant evaluator is a future privilege-escalation path even when today's policy
    registry has no approved qualifications.  Structural diagnostics remain useful, but every
    operator/mode pair is therefore ``INCONCLUSIVE`` and supplies no obligation support.
    """

    bound = require_bound_transition_case(case)
    value = dict(bound)
    obligation = next(
        (item for item in value["evolution_ir"]["obligations"]
         if item["obligation_id"] == obligation_id),
        None,
    )
    if obligation is None:
        raise TransitionContractError("TEMPORAL_OBLIGATION_UNKNOWN")
    profile_digest = obligation["observation_profile_digest"]
    profiles = {canonical_digest(item): item for item in value["observation_profiles"]}
    profile = profiles[profile_digest]
    qualification_evidence_by_receipt = {
        item["receipt_digest"]: item
        for item in value["qualification_evidence_bindings"]
    }
    exact_content = _empty_content_set() if content is None else require_bound_content_set(content)
    external_policy_digest: str | None = None
    qualification_reasons: list[str] = []
    if trust_policy is None:
        qualification_reasons.append("EXTERNAL_TRUST_POLICY_REQUIRED")
    else:
        external_policy = require_bound_trust_policy(trust_policy)
        if external_policy.digest != value["replay_contract"]["trust_policy_digest"]:
            qualification_reasons.append("QUALIFICATION_TRUST_POLICY_MISMATCH")
        else:
            external_policy_digest = external_policy.digest
    profile_state, profile_qualification_reasons = _profile_qualification(
        profile,
        profile_digest,
        profile_qualification,
        external_policy_digest,
        qualification_evidence_by_receipt,
    )
    qualification_reasons.extend(profile_qualification_reasons)
    atoms = [
        item for item in value["evidence_atoms"]
        if item["predicate_id"] == obligation["predicate_id"]
        and item["subject_id"] in obligation["subject_ids"]
        and item["state_id"] in obligation["state_ids"]
        and item["observation_profile_digest"] == profile_digest
        and item["semantic_profile_digest"] == obligation["semantic_profile_digest"]
    ]
    reasons = set(qualification_reasons)
    evidence_ids = sorted(item["evidence_id"] for item in atoms)
    if profile_state != QualificationState.QUALIFIED.value:
        reasons.add("OBSERVATION_PROFILE_NOT_QUALIFIED")
    if not atoms:
        reasons.add("TEMPORAL_TRACE_EMPTY")
    if any(type(item["value"]) is not bool for item in atoms):
        reasons.add("TEMPORAL_PREDICATE_VALUE_NOT_BOOLEAN")
    if not set(obligation["subject_ids"]).issubset({item["subject_id"] for item in atoms}):
        reasons.add("TEMPORAL_SUBJECT_COVERAGE_MISSING")
    if any(
            item["evidence_class"] not in obligation["accepted_evidence_classes"]
            for item in atoms
    ):
        reasons.add("TEMPORAL_EVIDENCE_CLASS_NOT_ACCEPTED")
    if any(not exact_content.contains(item["artifact_digest"]) for item in atoms):
        reasons.add("EVIDENCE_BYTES_UNAVAILABLE")
    if profile["collection_completeness"] != "COMPLETE":
        reasons.add("TEMPORAL_COLLECTION_INCOMPLETE")
    if profile["start_end_coverage"] != "BOTH":
        reasons.add("TEMPORAL_TERMINAL_COVERAGE_MISSING")
    operator = TemporalOperator(obligation["temporal_operator"])
    if profile["coverage_mode"] == ObservationMode.SAMPLED.value:
        reasons.add("TEMPORAL_SAMPLED_TRACE_ONLY_R2_0")
        if operator in (
                TemporalOperator.ALWAYS_DURING,
                TemporalOperator.NEVER_DURING,
                TemporalOperator.HOLD,
                TemporalOperator.UNTIL,
        ):
            reasons.add("SAMPLED_EVIDENCE_OFFERED_FOR_CONTINUOUS_CLAIM")
        elif operator in (
                TemporalOperator.EVENTUALLY_WITHIN,
                TemporalOperator.ON_REQUIRE_WITHIN,
        ):
            reasons.add("SAMPLED_EVENTUAL_INTERVAL_RECEIPT_REQUIRED")
        elif operator is TemporalOperator.AT_SAMPLE:
            reasons.add("AT_SAMPLE_TARGET_SELECTOR_REQUIRED")
    else:
        reasons.add("TEMPORAL_COMPLETE_OR_MODEL_TRUTH_NOT_ACTIVATED_R2_0")
        if operator is TemporalOperator.SAMPLED_NO_VIOLATION_DURING:
            reasons.add("TEMPORAL_OPERATOR_PROFILE_MODE_MISMATCH")
        if operator is TemporalOperator.AT_SAMPLE:
            reasons.add("AT_SAMPLE_TARGET_SELECTOR_REQUIRED")
    reasons.add("TEMPORAL_MONITOR_NOT_ACTIVATED_R2_0")
    reasons.add("TEMPORAL_MONITOR_NONAUTHORITATIVE_R2_0")
    result = {
        "schema": TEMPORAL_MONITOR_RESULT_SCHEMA,
        "obligation_id": obligation["obligation_id"],
        "observation_profile_digest": profile_digest,
        "coverage_mode": profile["coverage_mode"],
        "temporal_operator": obligation["temporal_operator"],
        "temporal_outcome": TemporalOutcome.INCONCLUSIVE.value,
        "evidence_ids": evidence_ids,
        "reason_codes": sorted(reasons),
        "supplies_obligation_support": False,
        "authoritative": False,
    }
    canonical_json_bytes(result)
    return result


def _derivation_axes(
        derivations: Sequence[Mapping[str, Any]],
        *,
        obligation: Mapping[str, Any],
        profile: Mapping[str, Any],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        content: BoundContentSet,
        ) -> tuple[bool, bool, bool, bool, list[str], list[str], list[str]]:
    valid_support_ids: list[str] = []
    valid_counter_ids: list[str] = []
    reasons: set[str] = set()
    evaluator_complete = True
    certificates_complete = True
    for derivation in derivations:
        reasons.add("PRODUCER_TEMPORAL_OUTCOME_NOT_RECOMPUTED_R2_0")
        if any(
                not content.contains(evidence_by_id[evidence_id]["artifact_digest"])
                for evidence_id in derivation["evidence_ids"]):
            reasons.add("EVIDENCE_BYTES_UNAVAILABLE")
        if (
                profile["coverage_mode"] == ObservationMode.SAMPLED.value
                and derivation["temporal_outcome"]
                == TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value
        ):
            if obligation["temporal_operator"] in (
                    TemporalOperator.EVENTUALLY_WITHIN.value,
                    TemporalOperator.ON_REQUIRE_WITHIN.value,
            ):
                reasons.add("SAMPLED_EVENTUAL_INTERVAL_RECEIPT_REQUIRED")
            elif obligation["temporal_operator"] in (
                    TemporalOperator.ALWAYS_DURING.value,
                    TemporalOperator.NEVER_DURING.value,
                    TemporalOperator.HOLD.value,
                    TemporalOperator.UNTIL.value,
            ):
                reasons.add("SAMPLED_EVIDENCE_OFFERED_FOR_CONTINUOUS_CLAIM")
        if (
                derivation["effect"] == "SUPPORT"
                and derivation["evaluator_kind"] == "UNCERTIFIED_SEARCH_EXHAUSTED"
        ):
            reasons.add("UNCERTIFIED_POSITIVE_SEARCH_CANNOT_PROMOTE")
        # R2.0 has frozen the ABI but has no activated qualified DSL/Wasm execution substrate.
        # Derivations carried by an untrusted case are projections until the verifier itself
        # recomputes them.  A caller-provided certificate digest is only an identifier and can
        # never stand in for verified certificate bytes/policy authority.
        reasons.add("PACK_DERIVATION_NOT_RECOMPUTED_R2_0")
        evaluator_complete = False
        if derivation["certificate_digest"] is not None:
            certificates_complete = False
            reasons.add("EVALUATOR_CERTIFICATE_NOT_VERIFIED")
    return (
        bool(valid_support_ids),
        bool(valid_counter_ids),
        evaluator_complete,
        certificates_complete,
        sorted(valid_support_ids),
        sorted(valid_counter_ids),
        [TemporalOutcome.INCONCLUSIVE.value, *sorted(reasons)],
    )


def verify_transition_case(
        case: BoundTransitionCase,
        pack_manifest: Any,
        *,
        content: BoundContentSet | None = None,
        tcb_manifest: Any = None,
        tcb_budget_review: Any = None,
        tcb_budget_freeze: Any = None,
        applicability_qualification: VerifiedQualification | None = None,
        pack_qualification: VerifiedQualification | None = None,
        observation_profile_qualifications: Mapping[str, VerifiedQualification] | None = None,
        trust_policy: BoundTrustPolicy | None = None,
        verifier_bootstrap_raw: bytes | None = None) -> BoundVerifierReceipt:
    """Recompute the structural R2 receipt without trusting a producer or projection."""

    bound_case = require_bound_transition_case(case)
    bound_pack = require_bound_pack_manifest(pack_manifest)
    exact_content = _empty_content_set() if content is None else require_bound_content_set(content)
    profile_qualifications = dict(observation_profile_qualifications or {})

    value = dict(bound_case)
    qualification_evidence_by_receipt = {
        item["receipt_digest"]: item
        for item in value["qualification_evidence_bindings"]
    }
    reasons: set[str] = set()
    if verifier_bootstrap_raw is None:
        reasons.add("EXTERNAL_VERIFIER_BOOTSTRAP_REQUIRED")
    elif type(verifier_bootstrap_raw) is not bytes:
        reasons.add("EXTERNAL_VERIFIER_BOOTSTRAP_BYTES_REQUIRED")
    elif bytes_digest(verifier_bootstrap_raw) != value["replay_contract"][
        "verifier_bootstrap_digest"
    ]:
        reasons.add("EXTERNAL_VERIFIER_BOOTSTRAP_MISMATCH")
    pack_binding = value["pack_binding"]
    pack_denominator = next(
        item for item in value["qualification_denominators"]
        if item["subject_kind"] == QualificationSubjectKind.BEHAVIOR_PACK.value
        and item["subject_id"] == pack_binding["pack_id"]
        and item["subject_version"] == pack_binding["pack_version"]
    )
    pack_matches = (
        bound_pack.digest == pack_binding["pack_manifest_digest"]
        and bound_pack["tcb_manifest_digest"] == pack_binding["tcb_manifest_digest"]
        and bound_pack["pack_id"] == pack_binding["pack_id"]
        and bound_pack["pack_version"] == pack_binding["pack_version"]
        and bound_pack["abi_version"] == pack_binding["abi_version"]
        and bound_pack["semantic_bundle_digest"] == pack_binding["semantic_bundle_digest"]
        and bound_pack["supported_denominator_digest"] == canonical_digest(pack_denominator)
        and (
            value["applicability"]["kind"] != ApplicabilityKind.APPLICABLE.value
            or value["applicability"]["profile_id"]
            in bound_pack["applicability_profile_ids"]
        )
        and bound_pack["qualification_receipt_digest"]
        == pack_binding["pack_qualification_receipt_digest"]
    )
    if not pack_matches:
        reasons.add("PACK_BINDING_MISMATCH")

    trust_policy_digest: str | None = None
    if trust_policy is None:
        reasons.add("EXTERNAL_TRUST_POLICY_REQUIRED")
    else:
        external_policy = require_bound_trust_policy(trust_policy)
        if external_policy.digest != value["replay_contract"]["trust_policy_digest"]:
            reasons.add("QUALIFICATION_TRUST_POLICY_MISMATCH")
        else:
            trust_policy_digest = external_policy.digest
    applicability = value["applicability"]
    applicability_state: str | None = None
    if applicability["kind"] == ApplicabilityKind.APPLICABLE.value:
        applicability_evidence = qualification_evidence_by_receipt[
            applicability["qualification_receipt_digest"]
        ]
        applicability_state, qualification_reasons = _qualification_for(
            applicability_qualification,
            receipt_digest=applicability["qualification_receipt_digest"],
            signature_digest=applicability_evidence["signature_digest"],
            public_key_digest=applicability_evidence["public_key_digest"],
            subject_kind=QualificationSubjectKind.APPLICABILITY_PROFILE.value,
            subject_id=applicability["profile_id"],
            subject_version="1",
            subject_digest=applicability["profile_digest"],
            denominator_digest=applicability["supported_denominator_digest"],
            trust_policy_digest=trust_policy_digest,
        )
        reasons.update(qualification_reasons)

    bound_tcb = None
    tcb_pair_verified = False
    if tcb_budget_review is not None:
        reasons.add("DIRECT_TCB_BUDGET_REVIEW_CANNOT_ACTIVATE")
    if tcb_manifest is not None:
        try:
            bound_tcb = require_bound_tcb_manifest(tcb_manifest)
            if tcb_budget_freeze is None:
                raise ValueError("bound final TCB budget freeze required")
            budget_freeze = require_bound_r2_tcb_budget_freeze(tcb_budget_freeze)
            if (
                    budget_freeze["final_pack_manifest_digest"] != bound_pack.digest
                    or budget_freeze["final_tcb_manifest_digest"] != bound_tcb.digest
            ):
                raise ValueError("final pack or TCB does not match budget freeze")
            validate_pack_tcb_pair(bound_pack, bound_tcb, budget_review=budget_freeze.budget_review)
            tcb_pair_verified = True
        except (TypeError, ValueError):
            reasons.add("PACK_TCB_NOT_VERIFIED")
            if tcb_budget_freeze is None:
                reasons.add("PACK_TCB_FREEZE_REQUIRED")

    pack_state = bound_pack["qualification_state"]
    if pack_state == QualificationState.QUALIFIED.value and tcb_pair_verified:
        assert bound_tcb is not None
        pack_evidence = qualification_evidence_by_receipt[
            pack_binding["pack_qualification_receipt_digest"]
        ]
        verified_pack_state, qualification_reasons = _qualification_for(
            pack_qualification,
            receipt_digest=pack_binding["pack_qualification_receipt_digest"],
            signature_digest=pack_evidence["signature_digest"],
            public_key_digest=pack_evidence["public_key_digest"],
            subject_kind=QualificationSubjectKind.BEHAVIOR_PACK.value,
            subject_id=pack_binding["pack_id"],
            subject_version=pack_binding["pack_version"],
            subject_digest=pack_qualification_subject_digest(
                dict(bound_pack),
                dict(bound_tcb),
            ),
            denominator_digest=bound_pack["supported_denominator_digest"],
            trust_policy_digest=trust_policy_digest,
        )
        reasons.update(qualification_reasons)
        pack_state = verified_pack_state or QualificationState.EXPERIMENTAL.value
    elif pack_state == QualificationState.QUALIFIED.value:
        reasons.add("PACK_QUALIFICATION_TCB_REQUIRED")
        pack_state = QualificationState.EXPERIMENTAL.value
    else:
        reasons.add("PACK_NOT_QUALIFIED")
    if bound_pack["pack_id"] == "QCP-001":
        pack_state = QualificationState.EXPERIMENTAL.value
        reasons.add("QCP_001_EXPERIMENTAL_UNTIL_R2_6")
    if bound_pack["execution_state"] != PackExecutionState.ACTIVATABLE.value:
        reasons.add("PACK_EXECUTION_SUBSTRATE_NOT_AVAILABLE")
    elif not tcb_pair_verified:
        reasons.add("PACK_TCB_NOT_VERIFIED")

    replay_status, replay_reasons = _replay_status(value, exact_content)
    reasons.update(replay_reasons)
    security_status, security_reasons = _security_status(value)
    reasons.update(security_reasons)

    profiles = {canonical_digest(item): item for item in value["observation_profiles"]}
    profile_states: dict[str, str | None] = {}
    for digest, profile in profiles.items():
        profile_state, profile_reasons = _profile_qualification(
            profile,
            digest,
            profile_qualifications.get(digest),
            trust_policy_digest,
            qualification_evidence_by_receipt,
        )
        profile_states[digest] = profile_state
        reasons.update(profile_reasons)

    derivations_by_obligation: dict[str, list[Mapping[str, Any]]] = {}
    for derivation in value["derivations"]:
        derivations_by_obligation.setdefault(derivation["obligation_id"], []).append(derivation)

    evidence_by_id = {item["evidence_id"]: item for item in value["evidence_atoms"]}
    obligation_results: list[dict[str, Any]] = []
    mandatory_statuses: list[str] = []
    evaluator_complete = True
    certificates_complete = True
    for obligation in value["evolution_ir"]["obligations"]:
        axes = _derivation_axes(
            derivations_by_obligation.get(obligation["obligation_id"], []),
            obligation=obligation,
            profile=profiles[obligation["observation_profile_digest"]],
            evidence_by_id=evidence_by_id,
            content=exact_content,
        )
        support, counter, obligation_eval_complete, obligation_certs_complete = axes[:4]
        status = four_valued_evidence_status(support, counter)
        if obligation["mandatory"]:
            mandatory_statuses.append(status)
        evaluator_complete = evaluator_complete and obligation_eval_complete
        certificates_complete = certificates_complete and obligation_certs_complete
        obligation_results.append({
            "obligation_id": obligation["obligation_id"],
            "requirement_id": obligation["requirement_id"],
            "mandatory": obligation["mandatory"],
            "evidence_status": status,
            "valid_support_derivation_ids": axes[4],
            "valid_counter_evidence_derivation_ids": axes[5],
            "temporal_outcomes_and_reasons": axes[6],
        })

    effective_qualification = applicability_state
    if pack_state != QualificationState.QUALIFIED.value:
        effective_qualification = pack_state
    elif any(state != QualificationState.QUALIFIED.value for state in profile_states.values()):
        effective_qualification = None
        reasons.add("OBSERVATION_PROFILE_QUALIFICATION_REQUIRED")
    effective_applicability_kind = applicability["kind"]
    if effective_applicability_kind == ApplicabilityKind.NOT_APPLICABLE.value:
        # A producer-carried reason list is a projection.  Only recomputation by the activated
        # qualified pack may suppress case construction as an authoritative no-case result.
        effective_applicability_kind = ApplicabilityKind.APPLICABILITY_EVIDENCE_REQUIRED.value
        reasons.add("NOT_APPLICABLE_RESULT_NOT_RECOMPUTED_R2_0")
    replay_authority_established = False
    security_authority_established = False
    structural_complete = (
        pack_matches
        and tcb_pair_verified
        and bound_pack["execution_state"] == PackExecutionState.ACTIVATABLE.value
        and replay_authority_established
        and security_authority_established
    )
    disposition, gate = map_authoritative_gate(
        applicability_kind=effective_applicability_kind,
        qualification_state=effective_qualification,
        mandatory_evidence_statuses=mandatory_statuses,
        evaluator_complete=evaluator_complete and structural_complete,
        certificates_complete=certificates_complete,
    )
    # PROJECTION_ONLY is always non-authoritative, independently of the applicability payload.
    if value["case_mode"] == CaseMode.PROJECTION_ONLY.value:
        disposition, gate = GateDisposition.NO_AUTHORITATIVE_GATE.value, None

    receipt = {
        "schema": VERIFIER_RECEIPT_SCHEMA,
        "verifier_version": VERIFIER_VERSION,
        "semantic_version": TRANSITION_SEMANTICS_VERSION,
        "case_id": value["case_id"],
        "case_digest": bound_case.payload_digest,
        "case_mode": value["case_mode"],
        "pack_manifest_digest": bound_pack.digest,
        "applicability_kind": applicability["kind"],
        "effective_applicability_kind": effective_applicability_kind,
        "applicability_qualification_state": applicability_state,
        "pack_qualification_state": pack_state,
        "disposition": disposition,
        "authoritative_gate": gate,
        "obligations": obligation_results,
        "replay_status": replay_status,
        "security_status": security_status,
        "tcb_pair_verified": tcb_pair_verified,
        "replay_authority_established": replay_authority_established,
        "security_authority_established": security_authority_established,
        "reason_codes": sorted(reasons),
        "human_decision_required": True,
        "autonomous_go": False,
        "wording_policy_version": WORDING_POLICY_VERSION,
        "wording_policy_digest": wording_policy_digest(),
        "operator_wording": gate_wording(disposition, gate),
        "claim_boundary": VERIFIER_CLAIM_BOUNDARY,
    }
    raw = canonical_json_bytes(receipt)
    return BoundVerifierReceipt(
        receipt,
        digest=bytes_digest(raw),
        _authority=_VERIFIER_RECEIPT_AUTHORITY,
    )


def require_bound_verifier_receipt(value: Any) -> BoundVerifierReceipt:
    """Reject producer-created or mutated mappings that imitate a verifier receipt."""

    if not isinstance(value, BoundVerifierReceipt):
        raise TransitionContractError("DETACHED_VERIFIER_RECEIPT")
    raw = canonical_json_bytes(dict(value))
    if bytes_digest(raw) != value.digest:
        raise TransitionContractError("BOUND_VERIFIER_RECEIPT_MUTATED")
    if (
            value.get("schema") != VERIFIER_RECEIPT_SCHEMA
            or value.get("autonomous_go") is not False
            or value.get("human_decision_required") is not True
            or value.get("wording_policy_version") != WORDING_POLICY_VERSION
            or value.get("wording_policy_digest") != wording_policy_digest()
            or value.get("operator_wording")
            != gate_wording(value.get("disposition"), value.get("authoritative_gate"))
            or value.get("authoritative_gate")
            not in {None, *(item.value for item in AuthoritativeGate)}
    ):
        raise TransitionContractError("VERIFIER_RECEIPT_INVARIANT_VIOLATION")
    return value


def verifier_receipt_bytes(receipt: BoundVerifierReceipt) -> bytes:
    """Serialize only unchanged verifier-minted receipts, never producer mappings."""

    return canonical_json_bytes(dict(require_bound_verifier_receipt(receipt)))


def compute_invalidation_receipt(
        previous_case: BoundTransitionCase,
        current_case: BoundTransitionCase) -> dict[str, Any]:
    """Compare dependency identities without rewriting either historical case."""

    previous = require_bound_transition_case(previous_case)
    current = require_bound_transition_case(current_case)
    if previous["case_id"] != current["case_id"]:
        raise TransitionContractError("INVALIDATION_CASE_ID_MISMATCH")
    if previous["transition_identity"] != current["transition_identity"]:
        raise TransitionContractError("INVALIDATION_TRANSITION_IDENTITY_MISMATCH")
    previous_dependencies = {
        (item["kind"], item["identifier"]): item["digest"]
        for item in previous["version_contract"]["dependency_digests"]
    }
    current_dependencies = {
        (item["kind"], item["identifier"]): item["digest"]
        for item in current["version_contract"]["dependency_digests"]
    }
    changed = []
    for key in sorted(set(previous_dependencies) | set(current_dependencies)):
        before = previous_dependencies.get(key)
        after = current_dependencies.get(key)
        if before != after:
            changed.append({
                "kind": key[0],
                "identifier": key[1],
                "previous_digest": before,
                "current_digest": after,
            })
    case_content_changed = previous.payload_digest != current.payload_digest
    invalidation_reasons = []
    if changed:
        invalidation_reasons.append("DECLARED_DEPENDENCY_DIGEST_CHANGED")
    if case_content_changed and not changed:
        invalidation_reasons.append("CASE_CONTENT_CHANGED_WITHOUT_DEPENDENCY_DELTA")
    receipt = {
        "schema": INVALIDATION_RECEIPT_SCHEMA,
        "case_id": previous["case_id"],
        "previous_case_digest": previous.payload_digest,
        "current_case_digest": current.payload_digest,
        "state": "INVALIDATED" if changed or case_content_changed else "UNCHANGED",
        "case_content_changed": case_content_changed,
        "changed_dependencies": changed,
        "invalidation_reasons": invalidation_reasons,
        "migration_policy": "REFERENCE_NOT_REWRITE",
        "historical_case_rewritten": False,
        "authoritative": False,
        "promotion_effect": "NONE",
        "claim_boundary": INVALIDATION_CLAIM_BOUNDARY,
    }
    canonical_json_bytes(receipt)
    return receipt


__all__ = [
    "BoundContentSet",
    "BoundVerifierReceipt",
    "GateDisposition",
    "INVALIDATION_CLAIM_BOUNDARY",
    "INVALIDATION_RECEIPT_SCHEMA",
    "ReplayStatus",
    "SecurityStatus",
    "TEMPORAL_MONITOR_RESULT_SCHEMA",
    "VERIFIER_CLAIM_BOUNDARY",
    "VERIFIER_RECEIPT_SCHEMA",
    "VERIFIER_VERSION",
    "bind_content_objects",
    "compute_invalidation_receipt",
    "four_valued_evidence_status",
    "map_authoritative_gate",
    "monitor_temporal_obligation",
    "require_bound_content_set",
    "require_bound_verifier_receipt",
    "verifier_receipt_bytes",
    "verify_transition_case",
]
