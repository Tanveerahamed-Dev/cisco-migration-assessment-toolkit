"""Pure release-state and claim-honesty policy.

The evaluator deliberately has no filesystem, network, signing, or publishing
side effects.  Callers supply independently produced receipts; this module
only decides whether the requested semantic transition is admissible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping


STATES = frozenset(
    {
        "DRAFT",
        "CANDIDATE",
        "VERIFIED",
        "PUBLISHED",
        "REJECTED",
        "SUPERSEDED",
        "ARCHIVED",
        "REVOKED",
    }
)

ALLOWED_TRANSITIONS = frozenset(
    {
        ("DRAFT", "CANDIDATE"),
        ("CANDIDATE", "VERIFIED"),
        ("CANDIDATE", "REJECTED"),
        ("VERIFIED", "PUBLISHED"),
        ("VERIFIED", "REVOKED"),
        ("PUBLISHED", "SUPERSEDED"),
        ("PUBLISHED", "REVOKED"),
        ("SUPERSEDED", "ARCHIVED"),
    }
)

PROTECTED_CONSTRAINTS = frozenset(
    {
        "no_device_writes",
        "no_raw_vault",
        "no_client_evidence",
        "no_analysis_egress",
        "proposer_differs_from_verifier",
        "no_human_gate_bypass",
        "no_publication_without_authority",
    }
)

BASE_VERIFICATION_RECEIPTS = frozenset(
    {
        "census",
        "line_map",
        "symbol_map",
        "claim_integrity",
        "architecture_conformance",
        "privacy",
        "deterministic_build",
        "accessibility",
        "performance",
        "export_reconciliation",
        "independent_review",
    }
)


@dataclass(frozen=True)
class Evaluation:
    allowed: bool
    reasons: tuple[str, ...]
    current_state: str
    requested_state: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "current_state": self.current_state,
            "requested_state": self.requested_state,
        }


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _receipt_ids(receipts: object) -> set[str]:
    if not isinstance(receipts, list):
        return set()
    result: set[str] = set()
    for receipt in receipts:
        if isinstance(receipt, Mapping):
            identifier = receipt.get("kind")
            verdict = receipt.get("verdict")
            if isinstance(identifier, str) and verdict == "pass":
                result.add(identifier)
    return result


def evaluate_transition(
    request: Mapping[str, Any], *, now: datetime | None = None
) -> Evaluation:
    """Evaluate one lifecycle transition and enumerate every refusal reason."""

    current = str(request.get("current_state", ""))
    requested = str(request.get("requested_state", ""))
    reasons: list[str] = []
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if current not in STATES:
        reasons.append("unknown_current_state")
    if requested not in STATES:
        reasons.append("unknown_requested_state")
    if (current, requested) not in ALLOWED_TRANSITIONS:
        reasons.append("transition_not_allowed")

    waivers = request.get("waived_constraints", [])
    waived = {str(item) for item in waivers} if isinstance(waivers, list) else set()
    protected_waivers = sorted(waived & PROTECTED_CONSTRAINTS)
    if protected_waivers:
        reasons.extend(f"protected_constraint_unwaivable:{item}" for item in protected_waivers)

    exceptions = request.get("exceptions", [])
    if not isinstance(exceptions, list):
        reasons.append("exceptions_malformed")
    else:
        for index, exception in enumerate(exceptions):
            if not isinstance(exception, Mapping):
                reasons.append(f"exception_malformed:{index}")
                continue
            expiry = _parse_utc(exception.get("expires_at"))
            if expiry is None:
                reasons.append(f"exception_expiry_invalid:{index}")
            elif expiry <= moment:
                reasons.append(f"exception_expired:{index}")
            if exception.get("constraint_id") in PROTECTED_CONSTRAINTS:
                reasons.append(f"protected_constraint_exception:{index}")

    if requested in {"VERIFIED", "PUBLISHED"}:
        author = request.get("author_identity")
        verifier = request.get("verifier_identity")
        if not isinstance(author, str) or not author.strip():
            reasons.append("author_identity_missing")
        if not isinstance(verifier, str) or not verifier.strip():
            reasons.append("verifier_identity_missing")
        if author and verifier and author == verifier:
            reasons.append("author_is_verifier")

        receipts = _receipt_ids(request.get("receipts"))
        required = set(BASE_VERIFICATION_RECEIPTS)
        requested_receipts = request.get("required_receipts", [])
        if isinstance(requested_receipts, list):
            required.update(str(item) for item in requested_receipts)
        else:
            reasons.append("required_receipts_malformed")
        for missing in sorted(required - receipts):
            reasons.append(f"missing_receipt:{missing}")

        if request.get("source_clean") is not True:
            reasons.append("source_not_clean")
        if request.get("exact_source_bound") is not True:
            reasons.append("exact_source_not_bound")
        if request.get("owner_approved") is not True:
            reasons.append("owner_approval_missing")

    if requested == "PUBLISHED":
        if request.get("release_signature_verified") is not True:
            reasons.append("release_signature_missing_or_invalid")
        access = request.get("publication_access")
        if access not in {"owner_only", "shared", "public"}:
            reasons.append("publication_access_unknown")
        if access == "public" and request.get("public_authority") is not True:
            reasons.append("public_authority_missing")

    return Evaluation(not reasons, tuple(dict.fromkeys(reasons)), current, requested)


CLAIM_REQUIRED_FIELDS = frozenset(
    {
        "subject",
        "predicate",
        "value",
        "unit",
        "basis",
        "scope",
        "effective_time",
        "recorded_time",
        "owner",
        "evidence_ids",
        "evidence_class",
        "transformation",
        "denominator",
        "verdict",
        "freshness",
        "lineage",
        "derived_from",
        "status",
        "revoked_by",
        "revocation_reason",
        "conflicts_with",
        "current_view",
        "satisfies_evidence_requirement",
        "source_commit",
        "unresolved_reasons",
    }
)

CLAIM_EVIDENCE_CLASSES = frozenset({"observed", "derived", "inferred", "advisory", "decided"})
CLAIM_VERDICTS = frozenset({"proven", "refuted", "not_observed", "indeterminate", "conflicting"})
CLAIM_FRESHNESS = frozenset({"current", "stale", "unknown", "revoked"})
CLAIM_STATUSES = frozenset({"candidate", "current", "historical", "superseded", "revoked"})
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _claim_identifier(claim: Mapping[str, Any], index: int) -> str:
    identifier = claim.get("id", claim.get("claim_id"))
    return identifier if isinstance(identifier, str) and identifier else f"index:{index}"


def _string_list(
    claim_id: str,
    field: str,
    value: object,
    violations: list[str],
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        violations.append(f"{claim_id}:{field}_malformed")
        return []
    if len(value) != len(set(value)):
        violations.append(f"{claim_id}:{field}_duplicate")
    return list(value)


def _claim_cycles(claims_by_id: Mapping[str, Mapping[str, Any]]) -> set[tuple[str, ...]]:
    """Return canonical directed cycles in the claim-to-claim derivation graph."""

    state: dict[str, int] = {}
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(identifier: str) -> None:
        state[identifier] = 1
        stack.append(identifier)
        raw_derived = claims_by_id[identifier].get("derived_from")
        raw_evidence = claims_by_id[identifier].get("evidence_ids")
        targets = [
            *([] if not isinstance(raw_derived, list) else raw_derived),
            *([] if not isinstance(raw_evidence, list) else raw_evidence),
        ]
        for target in sorted(item for item in targets if isinstance(item, str) and item in claims_by_id):
            target_state = state.get(target, 0)
            if target_state == 0:
                visit(target)
            elif target_state == 1:
                start = stack.index(target)
                members = stack[start:]
                # The lexicographically smallest rotation gives one stable
                # representation regardless of the DFS entry point.
                rotations = [tuple(members[offset:] + members[:offset]) for offset in range(len(members))]
                cycles.add(min(rotations))
        stack.pop()
        state[identifier] = 2

    for identifier in sorted(claims_by_id):
        if state.get(identifier, 0) == 0:
            visit(identifier)
    return cycles


def validate_claims(
    claims: Iterable[Mapping[str, Any]],
    *,
    known_evidence_ids: Iterable[str] | None = None,
    expected_source_commit: str | None = None,
) -> tuple[str, ...]:
    """Return deterministic, whole-set claim-algebra violations.

    Validation covers required semantic fields, temporal/source binding,
    evidence references, self-validation, derived-claim graph acyclicity,
    conflict disclosure, absence/unknown honesty, and revocation lifecycle
    semantics. ``known_evidence_ids`` is required at a publication boundary so
    every direct evidence reference can be resolved against that build.
    """

    claim_rows = list(claims)
    violations: list[str] = []
    claims_by_id: dict[str, Mapping[str, Any]] = {}
    identifiers: list[str] = []
    for index, claim in enumerate(claim_rows):
        claim_id = _claim_identifier(claim, index)
        identifiers.append(claim_id)
        if claim_id in claims_by_id:
            violations.append(f"{claim_id}:claim_id_duplicate")
        else:
            claims_by_id[claim_id] = claim

    evidence_universe = None if known_evidence_ids is None else set(known_evidence_ids) | set(claims_by_id)

    for index, claim in enumerate(claim_rows):
        claim_id = identifiers[index]
        for field in sorted(CLAIM_REQUIRED_FIELDS - claim.keys()):
            violations.append(f"{claim_id}:required_field_missing:{field}")

        subject = claim.get("subject")
        predicate = claim.get("predicate")
        basis = claim.get("basis")
        scope = claim.get("scope")
        owner = claim.get("owner")
        unit = claim.get("unit")
        source_commit = claim.get("source_commit")
        evidence_class = claim.get("evidence_class")
        verdict = claim.get("verdict")
        freshness = claim.get("freshness")
        status = claim.get("status")
        unresolved = _string_list(claim_id, "unresolved_reasons", claim.get("unresolved_reasons"), violations)
        evidence_ids = _string_list(claim_id, "evidence_ids", claim.get("evidence_ids"), violations)
        derived_from = _string_list(claim_id, "derived_from", claim.get("derived_from"), violations)
        lineage = _string_list(claim_id, "lineage", claim.get("lineage"), violations)
        conflicts_with = _string_list(claim_id, "conflicts_with", claim.get("conflicts_with"), violations)

        if not isinstance(subject, str) or not subject:
            violations.append(f"{claim_id}:subject_invalid")
        if not isinstance(predicate, str) or not predicate:
            violations.append(f"{claim_id}:predicate_invalid")
        if not isinstance(basis, str) or not basis:
            violations.append(f"{claim_id}:basis_invalid")
        if not isinstance(scope, Mapping) or not scope:
            violations.append(f"{claim_id}:scope_invalid")
        if not isinstance(owner, str) or not owner:
            violations.append(f"{claim_id}:owner_invalid")
        if unit is not None and (not isinstance(unit, str) or not unit):
            violations.append(f"{claim_id}:unit_invalid")
        if not isinstance(source_commit, str) or _SOURCE_COMMIT.fullmatch(source_commit) is None:
            violations.append(f"{claim_id}:source_commit_invalid")
        elif expected_source_commit is not None and source_commit != expected_source_commit:
            violations.append(f"{claim_id}:source_commit_mismatch")
        if isinstance(scope, Mapping) and scope.get("source_commit") != source_commit:
            violations.append(f"{claim_id}:scope_source_commit_mismatch")

        for field in ("effective_time", "recorded_time"):
            value = claim.get(field)
            if value != "unknown" and _parse_utc(value) is None:
                violations.append(f"{claim_id}:{field}_invalid")
            if value == "unknown" and "temporal_value_unknown" not in unresolved:
                violations.append(f"{claim_id}:{field}_unknown_without_reason")

        if evidence_class not in CLAIM_EVIDENCE_CLASSES:
            violations.append(f"{claim_id}:evidence_class_invalid")
        if verdict not in CLAIM_VERDICTS:
            violations.append(f"{claim_id}:verdict_invalid")
        if freshness not in CLAIM_FRESHNESS:
            violations.append(f"{claim_id}:freshness_invalid")
        if status not in CLAIM_STATUSES:
            violations.append(f"{claim_id}:status_invalid")

        transformation = claim.get("transformation")
        if not isinstance(transformation, Mapping):
            violations.append(f"{claim_id}:transformation_malformed")
        elif not isinstance(transformation.get("id"), str) or not transformation.get("id") or not isinstance(
            transformation.get("version"), str
        ) or not transformation.get("version"):
            violations.append(f"{claim_id}:transformation_identity_missing")

        denominator = claim.get("denominator")
        denominator_status = None
        denominator_value: object = None
        if not isinstance(denominator, Mapping):
            violations.append(f"{claim_id}:denominator_malformed")
        else:
            required_denominator_fields = {"value", "unit", "basis", "status"}
            if not required_denominator_fields.issubset(denominator):
                violations.append(f"{claim_id}:denominator_fields_missing")
            denominator_status = denominator.get("status")
            denominator_value = denominator.get("value")
            if denominator_status not in {"known", "unknown", "not_applicable"}:
                violations.append(f"{claim_id}:denominator_status_invalid")
            if denominator_status == "known" and (
                not isinstance(denominator_value, (int, float))
                or isinstance(denominator_value, bool)
                or denominator_value <= 0
            ):
                violations.append(f"{claim_id}:denominator_known_nonpositive")
            if denominator_status != "known" and denominator_value is not None:
                violations.append(f"{claim_id}:denominator_unknown_has_value")
            if not isinstance(denominator.get("unit"), str) or not denominator.get("unit"):
                violations.append(f"{claim_id}:denominator_unit_invalid")
            if not isinstance(denominator.get("basis"), str) or not denominator.get("basis"):
                violations.append(f"{claim_id}:denominator_basis_invalid")
            if denominator_status == "unknown" and not unresolved:
                violations.append(f"{claim_id}:denominator_unknown_without_reason")

        if claim_id in evidence_ids:
            violations.append(f"{claim_id}:self_validation")
        if claim_id in derived_from:
            violations.append(f"{claim_id}:self_derivation")
        if claim_id in conflicts_with:
            violations.append(f"{claim_id}:self_conflict")
        if evidence_universe is not None:
            for reference in sorted(set(evidence_ids) - evidence_universe):
                violations.append(f"{claim_id}:evidence_reference_unknown:{reference}")
            lineage_only = set(lineage) - set(evidence_ids) - set(derived_from)
            for reference in sorted(lineage_only - evidence_universe):
                violations.append(f"{claim_id}:lineage_reference_unknown:{reference}")
        for reference in sorted(set(derived_from) - set(claims_by_id)):
            violations.append(f"{claim_id}:derived_claim_unknown:{reference}")
        for reference in sorted(set(conflicts_with) - set(claims_by_id)):
            violations.append(f"{claim_id}:conflict_claim_unknown:{reference}")
        for reference in sorted(set(evidence_ids + derived_from) - set(lineage)):
            violations.append(f"{claim_id}:lineage_omits_reference:{reference}")

        if verdict in {"proven", "refuted"}:
            if not evidence_ids and not derived_from:
                violations.append(f"{claim_id}:verdict_evidence_missing")
            if denominator_status != "known":
                violations.append(f"{claim_id}:verdict_denominator_not_known")
        if evidence_class == "observed" and verdict == "proven" and not evidence_ids:
            violations.append(f"{claim_id}:observed_evidence_missing")
        if evidence_class == "derived" and not evidence_ids and not derived_from:
            violations.append(f"{claim_id}:derived_evidence_missing")
        if evidence_class in {"advisory", "inferred", "decided"} and claim.get(
            "satisfies_evidence_requirement"
        ) is True:
            violations.append(f"{claim_id}:nonobserved_class_cannot_satisfy_evidence")

        if verdict == "not_observed" and claim.get("value") in {0, False, "healthy", "clean"}:
            violations.append(f"{claim_id}:absence_coerced_to_health")
        if verdict == "not_observed":
            if not unresolved:
                violations.append(f"{claim_id}:not_observed_without_reason")
            if claim.get("satisfies_evidence_requirement") is True:
                violations.append(f"{claim_id}:not_observed_cannot_satisfy_evidence")
        if verdict == "indeterminate":
            if not unresolved:
                violations.append(f"{claim_id}:indeterminate_without_reason")
            if claim.get("satisfies_evidence_requirement") is True:
                violations.append(f"{claim_id}:indeterminate_cannot_satisfy_evidence")
        if verdict == "conflicting":
            if not conflicts_with:
                violations.append(f"{claim_id}:conflict_targets_missing")
            if claim.get("satisfies_evidence_requirement") is True:
                violations.append(f"{claim_id}:conflict_cannot_satisfy_evidence")
        elif conflicts_with:
            violations.append(f"{claim_id}:conflict_targets_without_conflicting_verdict")
        if freshness in {"stale", "unknown"} and not unresolved:
            violations.append(f"{claim_id}:{freshness}_without_reason")

        current_view = claim.get("current_view")
        satisfies = claim.get("satisfies_evidence_requirement")
        if not isinstance(current_view, bool):
            violations.append(f"{claim_id}:current_view_malformed")
        if not isinstance(satisfies, bool):
            violations.append(f"{claim_id}:satisfies_evidence_requirement_malformed")
        if status in {"candidate", "historical", "superseded", "revoked"} and current_view is True:
            violations.append(f"{claim_id}:noncurrent_status_in_current_view")

        revoked_by = claim.get("revoked_by")
        revocation_reason = claim.get("revocation_reason")
        if status == "revoked" or freshness == "revoked":
            if status != "revoked" or freshness != "revoked":
                violations.append(f"{claim_id}:revocation_state_inconsistent")
            if not isinstance(revoked_by, str) or not revoked_by:
                violations.append(f"{claim_id}:revoker_missing")
            elif revoked_by == claim_id:
                violations.append(f"{claim_id}:self_revocation")
            elif evidence_universe is not None and revoked_by not in evidence_universe:
                violations.append(f"{claim_id}:revoker_reference_unknown:{revoked_by}")
            if not isinstance(revocation_reason, str) or not revocation_reason:
                violations.append(f"{claim_id}:revocation_reason_missing")
            if current_view is True:
                violations.append(f"{claim_id}:revoked_claim_in_current_view")
            if satisfies is True:
                violations.append(f"{claim_id}:revoked_claim_cannot_satisfy_evidence")
        elif revoked_by is not None or revocation_reason is not None:
            violations.append(f"{claim_id}:revocation_metadata_without_revocation")

    for claim_id, claim in sorted(claims_by_id.items()):
        raw_conflicts = claim.get("conflicts_with")
        conflicts = raw_conflicts if isinstance(raw_conflicts, list) else []
        for target in sorted(item for item in conflicts if isinstance(item, str) and item in claims_by_id):
            reverse = claims_by_id[target].get("conflicts_with")
            if not isinstance(reverse, list) or claim_id not in reverse:
                violations.append(f"{claim_id}:conflict_not_reciprocal:{target}")

    for cycle in sorted(_claim_cycles(claims_by_id)):
        violations.append(f"claim_graph:derived_lineage_cycle:{'->'.join(cycle)}")

    return tuple(sorted(set(violations)))
