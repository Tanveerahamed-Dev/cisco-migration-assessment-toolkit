"""Canonical source-bound before/after comparison composition.

This module is the shared, presentation-independent owner of the comparison document consumed by
AssessHub and portable callers.  It composes existing v1 owners without replacing any of them:
``compute_snapshot_delta`` retains the legacy top-level fields, ``precert/1`` retains certificate
semantics, and ``cutover_gate/1`` remains the sole overall verdict owner.

Callers must supply snapshots already bound to the exact bytes they own, plus the corresponding
source-binding receipts.  This layer neither reads storage nor invents source custody.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import html as _html
from . import protocol_assurance as _protocol_assurance
from .precert import compute_precert, schema_compat_status


_BOUND_COMPARISON_AUTHORITY = object()
_BOUND_DECISION_INPUT_AUTHORITY = object()


class _BoundCutoverDecisionInputs:
    """Process-local proof that one canonical composer produced every gate input.

    The public receipts remain ordinary JSON.  This private authority closes a source-bound seam
    where individually well-shaped (or even independently valid) delta, precert, admission, and
    family receipts from different comparison pairs could otherwise be mixed and rehashed.
    """

    __slots__ = ("_bound_payload_sha256",)

    def __init__(self, *, payload_sha256: str, _authority: object) -> None:
        if _authority is not _BOUND_DECISION_INPUT_AUTHORITY:
            raise TypeError(
                "cutover decision input authority can only be minted by compare_bound_pair"
            )
        self._bound_payload_sha256 = payload_sha256


def _decision_input_payload(*, delta: Any, certificate: Any, admission: Any,
                            protocol_families: Any,
                            operator_evidence: Any) -> Dict[str, Any]:
    family_authority = _protocol_assurance.validate_protocol_family_change_set_authority(
        protocol_families
    )
    return {
        "delta": delta,
        "precert": certificate,
        "comparison_admission": admission,
        "protocol_families": protocol_families,
        "operator_evidence": operator_evidence,
        # The family-set source pair is deliberately process-local metadata, not wire schema.
        # Include it in the bundle digest so two JSON-identical family projections minted for
        # different snapshot pairs cannot be interchanged.
        "protocol_family_authority": {
            "valid": family_authority.get("valid") is True,
            "source_binding": family_authority.get("source_binding"),
        },
    }


def _mint_cutover_decision_input_authority(*, delta: Any, certificate: Any,
                                           admission: Any,
                                           protocol_families: Any,
                                           operator_evidence: Any) -> Any:
    payload = _decision_input_payload(
        delta=delta,
        certificate=certificate,
        admission=admission,
        protocol_families=protocol_families,
        operator_evidence=operator_evidence,
    )
    return _BoundCutoverDecisionInputs(
        payload_sha256=_protocol_assurance.canonical_sha256(payload),
        _authority=_BOUND_DECISION_INPUT_AUTHORITY,
    )


def validate_cutover_decision_input_authority(
        value: Any, *, delta: Any, certificate: Any, admission: Any,
        protocol_families: Any, operator_evidence: Any) -> Dict[str, Any]:
    """Require the unchanged canonical gate-input bundle minted by ``compare_bound_pair``."""
    if not isinstance(value, _BoundCutoverDecisionInputs):
        return {
            "present": value is not None,
            "valid": False,
            "reason": (
                "source-bound cutover decision inputs are detached from the canonical composer"
            ),
        }
    expected = getattr(value, "_bound_payload_sha256", None)
    try:
        actual = _protocol_assurance.canonical_sha256(_decision_input_payload(
            delta=delta,
            certificate=certificate,
            admission=admission,
            protocol_families=protocol_families,
            operator_evidence=operator_evidence,
        ))
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError):
        actual = None
    if not isinstance(expected, str) or expected != actual:
        return {
            "present": True,
            "valid": False,
            "reason": (
                "source-bound cutover decision inputs changed or belong to different comparisons"
            ),
        }
    return {"present": True, "valid": True, "reason": "ok"}


class BoundComparison(dict):
    """Process-local authority over one complete source/context-bound comparison document.

    Wire receipts remain plain JSON for portability, but an artifact writer cannot rediscover
    engagement/campaign/snapshot identities from snapshot payload bytes alone.  The private digest
    prevents a caller from rewriting those external identities, regenerating the unkeyed envelope,
    and asking a workbook to render the edited context as admitted evidence.
    """

    __slots__ = ("_bound_payload_sha256", "_bound_decision_input_authority")

    def __init__(self, value: Dict[str, Any], *, payload_sha256: str,
                 decision_input_authority: Any, _authority: object) -> None:
        if _authority is not _BOUND_COMPARISON_AUTHORITY:
            raise TypeError("BoundComparison can only be minted by compare_bound_pair")
        super().__init__(value)
        self._bound_payload_sha256 = payload_sha256
        self._bound_decision_input_authority = decision_input_authority


def validate_bound_comparison_authority(value: Any) -> Dict[str, Any]:
    """Require an unchanged comparison minted by the canonical in-process source owner."""
    if not isinstance(value, BoundComparison):
        return {
            "present": value is not None,
            "valid": False,
            "reason": "comparison is detached from the canonical in-process composer",
        }
    expected = getattr(value, "_bound_payload_sha256", None)
    try:
        actual = _protocol_assurance.canonical_sha256(dict(value))
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError):
        actual = None
    if not isinstance(expected, str) or expected != actual:
        return {
            "present": True,
            "valid": False,
            "reason": "comparison changed after canonical source/context composition",
        }
    return {"present": True, "valid": True, "reason": "ok"}


def bound_comparison_decision_input_authority(value: Any) -> Any:
    """Return a canonical comparison's private gate-input authority for exact reprojection."""
    validation = validate_bound_comparison_authority(value)
    if validation.get("valid") is not True:
        return None
    return getattr(value, "_bound_decision_input_authority", None)


def _schema_compat(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute the non-overridable pair schema verdict once for every downstream owner."""
    status, message = schema_compat_status(list(snaps or []))
    return {"status": status, "message": message, "override": False}


def _with_schema_compat(result: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Expose the exact compatibility verdict already consumed by a comparison owner."""
    if isinstance(result, dict):
        result["schema_compat"] = {
            "status": schema["status"],
            "message": schema["message"],
        }
    return result


def compare_bound_pair(
        old: Dict[str, Any], new: Dict[str, Any], *,
        before_binding: Dict[str, Any], after_binding: Dict[str, Any],
        change_intent: Optional[Dict[str, Any]] = None,
        path_intents: Optional[List[Dict[str, Any]]] = None,
        l2_failure_trial: Any = None) -> Dict[str, Any]:
    """Compose one canonical source-bound cutover comparison.

    The returned mapping deliberately keeps every legacy snapshot-delta field at the top level.
    Admission, expected-change reconciliation, native protocol-family changes, precertification,
    the sole cutover gate, operator evidence, and the detached receipt envelope are additive.
    """
    schema = _schema_compat([old, new])
    source_binding = {
        "before": dict(before_binding),
        "after": dict(after_binding),
    }
    profiles = _protocol_assurance.protocol_support_profiles()
    owner_versions = _protocol_assurance.canonical_decision_owner_versions(
        before_snapshot_owner=old.get("script_version"),
        after_snapshot_owner=new.get("script_version"),
    )
    intent_binding = {
        "engagement_id": before_binding.get("engagement_id"),
        "campaign_id": before_binding.get("campaign_id"),
        "before_snapshot_id": before_binding.get("snapshot_id"),
        "after_snapshot_id": after_binding.get("snapshot_id"),
        "before_sha256": before_binding.get("sha256"),
        "after_sha256": after_binding.get("sha256"),
    }
    intent = _protocol_assurance.normalize_change_intent(
        change_intent, binding=intent_binding)
    admission = _protocol_assurance.comparison_admission(
        old,
        new,
        before_binding=before_binding,
        after_binding=after_binding,
        schema_status=schema,
        change_intent=intent,
        owner_versions=owner_versions,
        support_profiles=profiles,
    )
    delta = _html.compute_snapshot_delta(
        old, new, source_binding=source_binding, schema_status=schema)
    delta = _with_schema_compat(delta, schema)
    certificate = compute_precert(
        old,
        new,
        path_intents=path_intents,
        source_hashes=source_binding,
        schema_status=schema,
    )
    native_deltas = _protocol_assurance.compute_native_protocol_deltas(
        old,
        new,
        before_binding=before_binding,
        after_binding=after_binding,
    )
    protocol_families = _protocol_assurance.protocol_family_change_set(
        delta.get("protocol_adjacencies"), intent, native_deltas=native_deltas)
    operator_evidence = _protocol_assurance.cutover_operator_evidence(
        new,
        observed_l2_failure_evidence=l2_failure_trial,
        expected_recovery_binding=after_binding,
        prior_snapshot=old,
        expected_predecessor_collected_at=old.get("collected_at"),
        expected_predecessor_binding=before_binding,
    )
    decision_input_authority = _mint_cutover_decision_input_authority(
        delta=delta,
        certificate=certificate,
        admission=admission,
        protocol_families=protocol_families,
        operator_evidence=operator_evidence,
    )
    cutover_gate = _html.compute_cutover_gate(
        delta,
        certificate,
        comparison_admission=admission,
        protocol_family_changes=protocol_families,
        operator_evidence=operator_evidence,
        decision_input_authority=decision_input_authority,
    )
    envelope = _protocol_assurance.receipt_envelope(
        admission=admission,
        change_intent=intent,
        protocol_families=protocol_families,
        delta=delta,
        precert=certificate,
        cutover_gate=cutover_gate,
        operator_evidence=operator_evidence,
    )
    payload = {
        **delta,
        "comparison_schema": "source_bound_cutover_comparison/1",
        "comparison_admission": admission,
        "change_intent": intent,
        "protocol_families": protocol_families,
        "precert": certificate,
        "cutover_gate": cutover_gate,
        "operator_evidence": operator_evidence,
        "comparison_receipt": envelope,
    }
    return BoundComparison(
        payload,
        payload_sha256=_protocol_assurance.canonical_sha256(payload),
        decision_input_authority=decision_input_authority,
        _authority=_BOUND_COMPARISON_AUTHORITY,
    )
