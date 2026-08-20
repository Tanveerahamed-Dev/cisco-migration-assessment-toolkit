"""Family-native, verdict-free before/after protocol deltas.

The owners in this module compare existing, validated baseline contracts.  They do not
reconstruct protocol truth from prose, raw captures, or the capability catalog, and they do
not own the overall cutover decision.  Each result uses the shared transition vocabulary and
publishes a family-local decision effect so the canonical cutover gate can compose it later.

Public functions accept complete assessment snapshots.  This is required for EtherChannel
and STP, whose existing owners authorize a baseline by recomputing it from the exact source
projections rather than trusting a detached baseline object.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from .analyze import (
    _validate_etherchannel_projection,
    _validate_protocol_assessability_receipt,
    summarize_stp_consistency_baseline,
    validate_etherchannel_baseline,
)
from .bgp_intent import validate_bgp_configured_peer_baseline
from .fhrp_intent import validate_fhrp_configured_group_baseline
from .fhrp_redundancy import validate_fhrp_redundancy_domain_baseline
from .etherchannel import validate_etherchannel_operational_evidence
from .ipv6_routing import validate_ipv6_routing_adjacency_baseline
from .protocol_assurance import (
    ASSURANCE_LEVELS,
    CHANGE_VOCABULARY,
    bound_snapshot_source,
    canonical_sha256,
)
from .stp_topology import validate_stp_topology_baseline
from .vtp_extended import validate_vtp_extended_evidence
from .vtp_safety import validate_vtp_safety_baseline


IPV6_ROUTING_ADJACENCY_DELTA_SCHEMA = "ipv6_routing_adjacency_delta/1"
BGP_CONFIGURED_PEER_DELTA_SCHEMA = "bgp_configured_peer_delta/1"
STP_CONSISTENCY_DELTA_SCHEMA = "stp_consistency_delta/1"
STP_TOPOLOGY_DELTA_SCHEMA = "stp_topology_delta/1"
ETHERCHANNEL_DELTA_SCHEMA = "etherchannel_delta/1"
VTP_SAFETY_DELTA_SCHEMA = "vtp_safety_delta/1"
FHRP_CONFIGURED_GROUP_DELTA_SCHEMA = "fhrp_configured_group_delta/1"
FHRP_REDUNDANCY_DOMAIN_DELTA_SCHEMA = "fhrp_redundancy_domain_delta/1"

_DECISION_EFFECTS = ("block", "review", "none", "not_verified")
_UNAVAILABLE_STATUSES = {"review", "not_verified"}
_DEGRADED_STATUSES = {"degraded"}
_HEALTHY_STATUSES = {"assessed", "administratively_disabled"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _snapshot(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _owner_value(value: Any, key: str) -> Any:
    root = _snapshot(value)
    return root.get(key)


def _receipt(view: Mapping[str, Any]) -> dict:
    return {
        "present": view.get("present") is True,
        "valid": view.get("valid") is True,
        "source_bound": view.get("source_bound") is True,
        "owner_source_authority": view.get("owner_source_authority") is True,
        "comparison_source_bound": view.get("comparison_source_bound") is True,
        "comparison_source_basis": _text(view.get("comparison_source_basis")),
        "snapshot_sha256": _text(view.get("comparison_snapshot_sha256")),
        "projection_sha256": _text(view.get("projection_sha256")),
        "reason": _text(view.get("reason")),
    }


def _binding_sha256(value: Any) -> str:
    """Return one exact-byte SHA-256 binding, never a caller custody assertion.

    The source-owning composers pass either the CLI file hash or AssessHub's richer persisted-byte
    binding.  A baseline's serialized ``projection_custody`` string is deliberately ignored: it is
    not authority to promote a detached projection back to current-run evidence.
    """
    digest = value if isinstance(value, str) else (
        value.get("sha256") if isinstance(value, Mapping) else None
    )
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return ""
    return digest


def _comparison_view(
    view: Mapping[str, Any],
    snapshot: Any,
    binding: Any,
    *,
    exact_snapshot_reconciliation: bool,
) -> dict:
    """Normalize process-local and exact-snapshot custody into one comparison receipt.

    Current-run owner objects retain a process-local marker that is intentionally erased when a
    snapshot is serialized.  A source-owning comparison may restore *comparison* custody—not
    current-run custody—only when the exact snapshot bytes are hashed and this module has already
    validated or deterministically recomputed the owner projection.  Callers cannot promote a
    projection by editing its embedded custody/hash leaves.
    """
    normalized = dict(view)
    owner_bound = bool(
        normalized.get("source_bound") is True
        and normalized.get("owner_source_authority") is True
    )
    snapshot_sha256 = _binding_sha256(binding)
    bound_source = bound_snapshot_source(snapshot)
    projection_sha256 = _text(normalized.get("projection_sha256"))
    if not projection_sha256:
        baseline = normalized.get("baseline")
        summary = baseline.get("summary") if isinstance(baseline, Mapping) else None
        raw_digest = summary.get("baseline_sha256") if isinstance(summary, Mapping) else None
        if isinstance(raw_digest, str) and re.fullmatch(r"[0-9a-f]{64}", raw_digest):
            projection_sha256 = "sha256:" + raw_digest
    normalized["projection_sha256"] = projection_sha256
    outer_bound = bool(
        exact_snapshot_reconciliation
        and normalized.get("valid") is True
        and normalized.get("comparison_reconcilable") is True
        and snapshot_sha256
        and projection_sha256
        and bound_source.get("source_bound") is True
        and bound_source.get("sha256") == snapshot_sha256
    )
    normalized["comparison_source_bound"] = owner_bound or outer_bound
    normalized["comparison_snapshot_sha256"] = snapshot_sha256
    normalized["comparison_source_basis"] = (
        "current_run_owner_source"
        if owner_bound else
        "exact_snapshot_bytes_and_validated_owner_projection"
        if outer_bound else
        "not_source_bound"
    )
    return normalized


def _reconcilable(
        view: Mapping[str, Any], eligible: bool = True, *,
        owner_source_authority: bool = True) -> dict:
    normalized = dict(view)
    normalized["comparison_reconcilable"] = bool(
        eligible and normalized.get("valid") is True
    )
    normalized["owner_source_authority"] = bool(owner_source_authority)
    return normalized


def _snapshot_device_roster(snapshot: Any) -> tuple[set[str] | None, str]:
    """Return the exact admitted local-device spellings when a roster is published.

    Native protocol owners do not infer vendor support from an inventory platform label.  Their
    positive and explicit-negative claims are instead bounded by the owner coverage rows that were
    actually published for each local snapshot device.  A missing ``devices`` key is retained for
    legacy/direct owner unit calls; canonical comparison admission requires the key separately.
    """
    root = _snapshot(snapshot)
    if "devices" not in root:
        return None, ""
    devices = root.get("devices")
    if not isinstance(devices, dict):
        return set(), "snapshot devices subject map is malformed"
    spellings: Dict[str, str] = {}
    for raw in devices:
        if not isinstance(raw, str) or not raw or raw != raw.strip():
            return set(), "snapshot devices contain a malformed local subject identity"
        folded = raw.casefold()
        if folded in spellings and spellings[folded] != raw:
            return set(), "snapshot devices contain a case-insensitive identity collision"
        spellings[folded] = raw
    return set(spellings.values()), ""


def _invalidate_subject_roster(view: Mapping[str, Any], reason: str) -> dict:
    """Erase caller-controlled subjects when an owner denominator misses the snapshot roster."""
    normalized = dict(view)
    normalized.update({
        "valid": False,
        "reason": reason,
        "source_bound": False,
        "comparison_reconcilable": False,
        "subject_roster_failure": True,
        "rows": [],
        "index": {},
        "domain_index": {},
        "baseline": {},
        "roots": {},
        "paths": {},
        "gaps": [],
    })
    return normalized


def _invalidate_owner_evidence(view: Mapping[str, Any], reason: str) -> dict:
    """Withhold subjects for a missing co-published source without relabelling it identity drift."""
    normalized = dict(view)
    normalized.update({
        "valid": False,
        "reason": reason,
        "source_bound": False,
        "comparison_reconcilable": False,
        "rows": [],
        "index": {},
        "domain_index": {},
        "baseline": {},
        "roots": {},
        "paths": {},
        "gaps": [],
    })
    return normalized


def reconcile_native_owner_subject_roster(
        view: Mapping[str, Any], snapshot: Any, *, family: str,
        coverage_hosts: Any, subject_hosts: Any = ()) -> dict:
    """Bind one structurally valid owner denominator to the exact local device roster.

    ``coverage_hosts`` is the owner's explicit coverage denominator (one or more cells per host).
    ``subject_hosts`` are positive rows/domains derived from it.  Both use exact snapshot identity
    spellings: a structurally valid baseline computed for an empty or different estate cannot be
    grafted into a source-bound snapshot and authorize protocol absence or health.
    """
    normalized = dict(view)
    if normalized.get("valid") is not True:
        return normalized
    expected, roster_error = _snapshot_device_roster(snapshot)
    if expected is None:
        return normalized
    if roster_error:
        return _invalidate_subject_roster(
            normalized, f"{family} subject roster is not comparable: {roster_error}")
    if not isinstance(coverage_hosts, (list, tuple, set, frozenset)):
        return _invalidate_subject_roster(
            normalized,
            f"{family} owner coverage denominator is missing or malformed",
        )

    actual: set[str] = set()
    folded: Dict[str, str] = {}
    for raw in coverage_hosts:
        if not isinstance(raw, str) or not raw or raw != raw.strip():
            return _invalidate_subject_roster(
                normalized,
                f"{family} owner coverage denominator contains a malformed identity",
            )
        identity = raw.casefold()
        prior = folded.get(identity)
        if prior is not None and prior != raw:
            return _invalidate_subject_roster(
                normalized,
                f"{family} owner coverage denominator contains an identity collision",
            )
        folded[identity] = raw
        actual.add(raw)
    if actual != expected:
        return _invalidate_subject_roster(
            normalized,
            f"{family} owner coverage denominator does not exactly reconcile to snapshot devices",
        )

    if not isinstance(subject_hosts, (list, tuple, set, frozenset)):
        return _invalidate_subject_roster(
            normalized, f"{family} owner subject identities are malformed")
    positive: set[str] = set()
    for raw in subject_hosts:
        if not isinstance(raw, str) or not raw or raw != raw.strip():
            return _invalidate_subject_roster(
                normalized, f"{family} owner subject identities are malformed")
        positive.add(raw)
    if not positive <= expected:
        return _invalidate_subject_roster(
            normalized,
            f"{family} owner contains a subject outside snapshot devices",
        )
    normalized["subject_roster_reconciled"] = True
    return normalized


def _reconcile_baseline_coverage_roster(
        view: Mapping[str, Any], snapshot: Any, *, family: str) -> dict:
    """Apply the shared roster join to owners with a public ``baseline.coverage`` array."""
    if view.get("valid") is not True:
        return dict(view)
    baseline = view.get("baseline")
    coverage = baseline.get("coverage") if isinstance(baseline, Mapping) else None
    rows = view.get("rows")
    if not isinstance(coverage, list) or not isinstance(rows, list):
        return _invalidate_subject_roster(
            view, f"{family} owner coverage denominator is missing or malformed")
    coverage_hosts = [
        cell.get("switch") if isinstance(cell, Mapping) else None
        for cell in coverage
    ]
    subject_hosts = [
        row.get("switch") if isinstance(row, Mapping) else None
        for row in rows
    ]
    return reconcile_native_owner_subject_roster(
        view,
        snapshot,
        family=family,
        coverage_hosts=coverage_hosts,
        subject_hosts=subject_hosts,
    )


def _pair_views(
    before_view: Mapping[str, Any],
    after_view: Mapping[str, Any],
    before_snapshot: Any,
    after_snapshot: Any,
    comparison_source_binding: Any,
    *,
    exact_snapshot_reconciliation: bool = True,
) -> tuple[dict, dict]:
    pair = comparison_source_binding if isinstance(comparison_source_binding, Mapping) else {}
    return (
        _comparison_view(
            before_view,
            before_snapshot,
            pair.get("before"),
            exact_snapshot_reconciliation=exact_snapshot_reconciliation,
        ),
        _comparison_view(
            after_view,
            after_snapshot,
            pair.get("after"),
            exact_snapshot_reconciliation=exact_snapshot_reconciliation,
        ),
    )


def _state(value: Mapping[str, Any] | None, fields: Sequence[str]) -> dict:
    if not isinstance(value, Mapping):
        return {}
    return {field: deepcopy(value.get(field)) for field in fields}


def _change(
    subject: str,
    transition: str,
    decision_effect: str,
    before_state: Mapping[str, Any] | None,
    after_state: Mapping[str, Any] | None,
    note: str,
) -> dict:
    if transition not in CHANGE_VOCABULARY:
        raise ValueError(f"unsupported protocol transition: {transition}")
    if decision_effect not in _DECISION_EFFECTS:
        raise ValueError(f"unsupported family decision effect: {decision_effect}")
    return {
        "subject": subject,
        "transition": transition,
        "decision_effect": decision_effect,
        "before_state": dict(before_state or {}),
        "after_state": dict(after_state or {}),
        "note": note,
    }


def _sort_changes(changes: Iterable[dict]) -> List[dict]:
    return sorted(
        changes,
        key=lambda item: (
            item["subject"].casefold(), item["subject"],
            CHANGE_VOCABULARY.index(item["transition"]),
        ),
    )


def _result(
    *,
    schema: str,
    family: str,
    assurance_level: str,
    before_view: Mapping[str, Any],
    after_view: Mapping[str, Any],
    changes: Iterable[dict],
    limitations: Sequence[str],
) -> dict:
    if assurance_level not in ASSURANCE_LEVELS:
        raise ValueError(f"unsupported assurance level: {assurance_level}")
    materialized = list(changes)

    def explicit_not_applicable(view: Mapping[str, Any]) -> bool:
        baseline = view.get("baseline")
        return bool(
            view.get("valid") is True
            and view.get("comparison_source_bound") is True
            and isinstance(baseline, Mapping)
            and baseline.get("verdict") == "NOT_APPLICABLE"
        )

    applicability = (
        "not_applicable"
        if not materialized
        and explicit_not_applicable(before_view)
        and explicit_not_applicable(after_view)
        else "applicable"
    )
    if not materialized and applicability == "applicable":
        materialized = [_change(
            f"{family}|owner_receipt",
            "not_comparable",
            "not_verified",
            {},
            {},
            "The applicable owner emitted no materialized subject or custody disposition; "
            "an empty array is not evidence of unchanged health.",
        )]
        assurance_level = "not_verified"
    normalized = []
    for raw in materialized:
        row = dict(raw)
        row["family"] = family
        normalized.append(row)
    ordered = _sort_changes(normalized)
    by_transition = {name: 0 for name in CHANGE_VOCABULARY}
    by_decision_effect = {name: 0 for name in _DECISION_EFFECTS}
    for row in ordered:
        by_transition[row["transition"]] += 1
        by_decision_effect[row["decision_effect"]] += 1
    comparable = sum(
        count for name, count in by_transition.items()
        if name not in {"coverage_lost", "not_comparable"}
    )
    receipts = {
        "before": _receipt(before_view),
        "after": _receipt(after_view),
    }
    if not all(receipt["comparison_source_bound"] for receipt in receipts.values()):
        assurance_level = "not_verified"
    return {
        "schema": schema,
        "family": family,
        "owner": schema,
        "assurance_level": assurance_level,
        "owns_score": False,
        "owns_verdict": False,
        "applicability": applicability,
        "comparable": bool(comparable) and not by_transition["not_comparable"],
        "assessed": bool(comparable) and not (
            by_transition["coverage_lost"] or by_transition["not_comparable"]
        ),
        "source_receipts": receipts,
        "summary": {
            "n_subjects": len(ordered),
            "n_comparable": comparable,
            "by_transition": by_transition,
            "by_decision_effect": by_decision_effect,
        },
        "changes": ordered,
        "limitations": list(limitations),
    }


def _invalid_owner_changes(
    family: str,
    before_view: Mapping[str, Any],
    after_view: Mapping[str, Any],
) -> List[dict]:
    before_authorized = bool(
        before_view.get("valid") is True
        and before_view.get("comparison_source_bound") is True
    )
    after_authorized = bool(
        after_view.get("valid") is True
        and after_view.get("comparison_source_bound") is True
    )
    if before_authorized and after_authorized:
        return []
    # A source-bound baseline denominator can lose after evidence.  Without that baseline custody,
    # however, no survival claim can be made regardless of how complete the after projection looks.
    identity_failure = bool(
        before_view.get("subject_roster_failure") is True
        or after_view.get("subject_roster_failure") is True
    )
    transition = (
        "not_comparable"
        if identity_failure or not before_authorized
        else "coverage_lost"
    )

    def receipt_state(view: Mapping[str, Any]) -> dict:
        return {
            "present": view.get("present") is True,
            "valid": view.get("valid") is True,
            "owner_source_bound": view.get("source_bound") is True,
            "owner_source_authority": view.get("owner_source_authority") is True,
            "comparison_source_bound": view.get("comparison_source_bound") is True,
            "reason": _text(view.get("reason")),
        }

    return [_change(
        f"{family}|owner_receipt",
        transition,
        "not_verified",
        receipt_state(before_view),
        receipt_state(after_view),
        (
            "The owner coverage/subject identities do not reconcile to the exact snapshot device "
            "roster; no absence, survival, or regression transition is asserted."
            if identity_failure else
            "The source-bound baseline denominator lost valid, source-bound after evidence; no "
            "survival or regression transition is asserted."
            if transition == "coverage_lost" else
            "The baseline owner receipt is malformed, missing, semantically incompatible, or not "
            "bound to an authorized comparison source; its caller-controlled leaves were not compared."
        ),
    )]


def _status_transition(
    subject: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    state_fields: Sequence[str],
    semantic_equal: bool,
    change_note: str,
) -> dict:
    before_status = _text(before.get("status"))
    after_status = _text(after.get("status"))
    before_state = _state(before, ("status", *state_fields))
    after_state = _state(after, ("status", *state_fields))
    if before_status in _UNAVAILABLE_STATUSES or after_status in _UNAVAILABLE_STATUSES:
        return _change(
            subject, "coverage_lost", "not_verified", before_state, after_state,
            "At least one validated baseline row is review/not-verified, so no healthy transition is asserted.",
        )
    if before_status in _DEGRADED_STATUSES and after_status in _DEGRADED_STATUSES:
        return _change(
            subject, "unchanged_degraded", "block", before_state, after_state,
            "The current degradation remains present; a clean delta does not make it acceptable.",
        )
    if before_status in _HEALTHY_STATUSES and after_status in _DEGRADED_STATUSES:
        return _change(
            subject, "regressed", "block", before_state, after_state,
            "A previously healthy validated subject is now degraded.",
        )
    if before_status in _DEGRADED_STATUSES and after_status in _HEALTHY_STATUSES:
        return _change(
            subject, "recovered", "none", before_state, after_state,
            "A previously degraded validated subject is now healthy.",
        )
    if before_status not in _HEALTHY_STATUSES or after_status not in _HEALTHY_STATUSES:
        return _change(
            subject, "not_comparable", "not_verified", before_state, after_state,
            "The owner emitted a status outside the family delta contract.",
        )
    if not semantic_equal:
        return _change(
            subject, "intent_changed", "review", before_state, after_state, change_note,
        )
    return _change(
        subject, "unchanged_healthy", "none", before_state, after_state,
        "The validated family subject and its bounded state are unchanged and healthy.",
    )


def _coverage_change(
    family: str,
    scope: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict:
    return _change(
        f"{family}|coverage|{scope}",
        "coverage_lost",
        "not_verified",
        {"status": _text((before or {}).get("status"))},
        {"status": _text((after or {}).get("status"))},
        "Required capture/parser evidence is unavailable on at least one side; absence is not health.",
    )


def _coverage_index(baseline: Mapping[str, Any], fields: Sequence[str]) -> Dict[Tuple[str, ...], dict]:
    result: Dict[Tuple[str, ...], dict] = {}
    rows = baseline.get("coverage")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = tuple(_text(row.get(field)) for field in fields)
        if all(key) and key not in result:
            result[key] = row
    return result


def _cell_neutral(family: str, cell: Mapping[str, Any] | None) -> bool:
    if not isinstance(cell, Mapping):
        return False
    status = _text(cell.get("status"))
    if status in {"assessed", "degraded"}:
        return True
    if status != "not_applicable":
        return False
    if family == "vtp_safety":
        return cell.get("explicit_no_subject") is True
    if family in {"bgp_configured_peer", "fhrp_configured_group"}:
        return (
            _text(cell.get("config_capture_status")) in {"ok", "complete"}
            and _text(cell.get("config_parser_status")) == "complete"
        )
    if family == "ipv6_routing_adjacency":
        protocol = _text(cell.get("protocol"))
        if cell.get("subject") is not False or cell.get("active_route_count") != 0:
            return False
        if protocol == "IPv6":
            return (
                _text(cell.get("capture_status")) == "ok"
                and _text(cell.get("parser_status")) == "complete"
                and cell.get("candidate_count") == 1
                and cell.get("parsed_count") == 1
                and cell.get("rejected_count") == 0
            )
        if protocol in {"OSPFv3", "BGPv6"}:
            return (
                _text(cell.get("capture_status")) != "ok"
                and _text(cell.get("parser_status")) == "not_verified"
                and cell.get("candidate_count") == 0
                and cell.get("parsed_count") == 0
                and cell.get("rejected_count") == 0
            )
    return False


def _append_coverage_gaps(
    changes: List[dict],
    *,
    family: str,
    before_baseline: Mapping[str, Any],
    after_baseline: Mapping[str, Any],
    key_fields: Sequence[str],
    represented: set[Tuple[str, ...]],
) -> None:
    before_cells = _coverage_index(before_baseline, key_fields)
    after_cells = _coverage_index(after_baseline, key_fields)
    for key in sorted(set(before_cells) | set(after_cells)):
        if key in represented:
            continue
        before_cell, after_cell = before_cells.get(key), after_cells.get(key)
        if _cell_neutral(family, before_cell) and _cell_neutral(family, after_cell):
            continue
        changes.append(_coverage_change(
            family, "|".join(key), before_cell, after_cell,
        ))


def _compare_indexed(
    *,
    family: str,
    before_view: Mapping[str, Any],
    after_view: Mapping[str, Any],
    subject: Callable[[Any, Mapping[str, Any]], str],
    state_fields: Sequence[str],
    semantic_fields: Sequence[str],
    missing_before: Callable[[str, Mapping[str, Any]], dict],
    missing_after: Callable[[str, Mapping[str, Any]], dict],
) -> tuple[List[dict], set[Tuple[str, ...]]]:
    invalid = _invalid_owner_changes(family, before_view, after_view)
    if invalid:
        return invalid, set()
    before_index = before_view.get("index", {})
    after_index = after_view.get("index", {})
    if not isinstance(before_index, dict) or not isinstance(after_index, dict):
        return [_change(
            f"{family}|owner_index", "not_comparable", "not_verified", {}, {},
            "The validated owner did not expose its canonical subject index.",
        )], set()
    changes: List[dict] = []
    represented: set[Tuple[str, ...]] = set()
    for key in sorted(set(before_index) | set(after_index), key=lambda value: str(value).casefold()):
        before = before_index.get(key)
        after = after_index.get(key)
        reference = before if isinstance(before, Mapping) else after
        if not isinstance(reference, Mapping):
            continue
        name = subject(key, reference)
        if isinstance(key, tuple):
            represented.add(tuple(str(item) for item in key[:2]))
        else:
            represented.add((str(key),))
        if not isinstance(before, Mapping):
            changes.append(missing_before(name, after))
            continue
        if not isinstance(after, Mapping):
            changes.append(missing_after(name, before))
            continue
        semantic_equal = all(before.get(field) == after.get(field) for field in semantic_fields)
        changes.append(_status_transition(
            name, before, after, state_fields=state_fields,
            semantic_equal=semantic_equal,
            change_note="A bounded identity/configuration attribute changed and requires intent reconciliation.",
        ))
    return changes, represented


def compute_ipv6_routing_adjacency_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare validated observed default/global OSPFv3 and BGPv6 adjacencies."""
    before_value = _owner_value(before, "ipv6_routing_adjacency_baseline")
    after_value = _owner_value(after, "ipv6_routing_adjacency_baseline")
    before_view, after_view = _pair_views(
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_ipv6_routing_adjacency_baseline(before_value),
            before,
            family="ipv6_routing_adjacency",
        )),
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_ipv6_routing_adjacency_baseline(after_value),
            after,
            family="ipv6_routing_adjacency",
        )),
        before,
        after,
        comparison_source_binding,
    )
    after_coverage = _coverage_index(
        after_view.get("baseline", {}), ("switch", "protocol"))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        status = _text(row.get("status"))
        state = _state(row, ("status", "state"))
        if status in _UNAVAILABLE_STATUSES:
            return _change(
                name, "coverage_lost", "not_verified", {}, state,
                "The newly observed IPv6 adjacency lacks verified current-state evidence.",
            )
        return _change(
            name, "appeared", "block" if status in _DEGRADED_STATUSES else "review",
            {}, state,
            "A newly observed IPv6 adjacency is already degraded; expected intent cannot clear a current fault."
            if status in _DEGRADED_STATUSES else
            "A runtime adjacency not observed in the baseline is now present; no expected-peer intent was inferred.",
        )

    def disappeared(name: str, row: Mapping[str, Any]) -> dict:
        cell = after_coverage.get((_text(row.get("switch")), _text(row.get("protocol"))))
        if not _cell_neutral("ipv6_routing_adjacency", cell):
            return _change(
                name, "coverage_lost", "not_verified", _state(row, ("status", "state")), {},
                "The after protocol-family capture/parser coverage cannot establish whether the baseline adjacency survived.",
            )
        return _change(name, "disappeared", "review", _state(row, ("status", "state")), {},
                       "A baseline-observed adjacency is no longer present; this is not proof that a configured peer is down.")

    changes, represented = _compare_indexed(
        family="ipv6_routing_adjacency",
        before_view=before_view,
        after_view=after_view,
        subject=lambda _key, row: "|".join((
            _text(row.get("switch")), _text(row.get("protocol")), _text(row.get("peer_key")),
        )),
        state_fields=("state", "state_raw", "interface", "remote_as", "role"),
        semantic_fields=("state", "interface", "remote_as", "role"),
        missing_before=appeared,
        missing_after=disappeared,
    )
    if before_view.get("valid") and after_view.get("valid"):
        _append_coverage_gaps(
            changes,
            family="ipv6_routing_adjacency",
            before_baseline=before_view["baseline"],
            after_baseline=after_view["baseline"],
            key_fields=("switch", "protocol"),
            represented=represented,
        )
    return _result(
        schema=IPV6_ROUTING_ADJACENCY_DELTA_SCHEMA,
        family="ipv6_routing_adjacency",
        assurance_level="observed_state_preservation",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "The denominator is validated observed default/global OSPFv3 and BGPv6 runtime adjacency only.",
            "Configured peers, VRFs, other AFI/SAFI, route correctness, convergence, and simultaneity are not proved.",
            "BGP prefix counts are informational and are not compared as adjacency state.",
        ),
    )


def compute_bgp_configured_peer_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare the validated direct-literal default/global configured BGP peer denominator."""
    before_view, after_view = _pair_views(
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_bgp_configured_peer_baseline(
                _owner_value(before, "bgp_configured_peer_baseline")),
            before,
            family="bgp_configured_peer",
        )),
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_bgp_configured_peer_baseline(
                _owner_value(after, "bgp_configured_peer_baseline")),
            after,
            family="bgp_configured_peer",
        )),
        before,
        after,
        comparison_source_binding,
    )
    after_coverage = _coverage_index(after_view.get("baseline", {}), ("switch",))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        status = _text(row.get("status"))
        state = _state(
            row, ("status", "activation", "configured_remote_as", "runtime_state"))
        if status in _UNAVAILABLE_STATUSES:
            return _change(
                name, "coverage_lost", "not_verified", {}, state,
                "The new configured BGP peer lacks verified configuration/runtime evidence.",
            )
        if status in _DEGRADED_STATUSES and _text(row.get("activation")) == "active":
            return _change(
                name, "appeared", "block", {}, state,
                "A new configured-active BGP peer is already degraded; expected intent cannot clear a current fault.",
            )
        return _change(
            name, "appeared", "review", {}, state,
            "A new literal configured peer requires expected-change reconciliation.",
        )

    def disappeared(name: str, row: Mapping[str, Any]) -> dict:
        active = _text(row.get("activation")) == "active"
        cell = after_coverage.get((_text(row.get("switch")),))
        if not _cell_neutral("bgp_configured_peer", cell):
            return _change(
                name, "coverage_lost", "not_verified",
                _state(row, ("status", "activation", "configured_remote_as", "runtime_state")), {},
                "The after configuration/runtime capture is not verified, so configured-peer disappearance is not asserted.",
            )
        return _change(
            name, "disappeared", "block" if active else "review",
            _state(row, ("status", "activation", "configured_remote_as", "runtime_state")), {},
            "A configured-active BGP peer disappeared from a validated configured denominator."
            if active else "An administratively disabled configured peer was removed; reconcile the intent change.",
        )

    changes, represented = _compare_indexed(
        family="bgp_configured_peer",
        before_view=before_view,
        after_view=after_view,
        subject=lambda _key, row: "|".join((_text(row.get("switch")), _text(row.get("peer_key")))),
        state_fields=("activation", "configured_remote_as", "runtime_observed", "runtime_state"),
        semantic_fields=("activation", "configured_remote_as", "local_as", "runtime_state"),
        missing_before=appeared,
        missing_after=disappeared,
    )
    if before_view.get("valid") and after_view.get("valid"):
        represented_hosts = {(key[0],) for key in represented if key}
        _append_coverage_gaps(
            changes,
            family="bgp_configured_peer",
            before_baseline=before_view["baseline"],
            after_baseline=after_view["baseline"],
            key_fields=("switch",),
            represented=represented_hosts,
        )
    return _result(
        schema=BGP_CONFIGURED_PEER_DELTA_SCHEMA,
        family="bgp_configured_peer",
        assurance_level="intent_reconciled_survival",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Scope is direct, static, literal default/global IPv4-unicast peers only.",
            "Peer groups, templates, dynamic peers, VRFs, other address families, policy, and route correctness remain outside scope.",
        ),
    )


def _stp_consistency_view(snapshot: Any) -> dict:
    present = isinstance(snapshot, dict) and any(
        key in snapshot for key in (
            "stp_consistency_baseline", "protocol_health", "protocol_assessability",
            "interfaces", "stp_roots",
        )
    )

    def invalid(reason: str) -> dict:
        return {
            "present": present, "valid": False, "reason": reason,
            "source_bound": False, "rows": [], "index": {}, "baseline": {},
        }

    if not isinstance(snapshot, dict):
        return invalid("STP source snapshot is missing or malformed")
    if not present:
        return invalid("STP consistency owner sources are missing")
    try:
        expected = summarize_stp_consistency_baseline(
            snapshot.get("protocol_health"), snapshot.get("protocol_assessability"),
            all_interfaces=snapshot.get("interfaces"), stp_roots=snapshot.get("stp_roots"),
        )
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        return invalid("STP consistency owner recomputation failed")
    published = snapshot.get("stp_consistency_baseline")
    if published is not None and published != expected:
        return invalid("Published STP consistency baseline does not reconcile to its exact owner sources")
    if expected.get("schema") != "stp_consistency_baseline/1" or not isinstance(expected.get("rows"), list):
        return invalid("STP consistency owner returned an incompatible schema")
    index: Dict[str, dict] = {}
    for row in expected["rows"]:
        host = _text(row.get("switch")) if isinstance(row, dict) else ""
        if not host or host in index:
            return invalid("STP consistency owner returned an invalid or duplicate subject")
        index[host] = row
    view = {
        "present": True, "valid": True,
        "reason": "recomputed_from_exact_existing_owner_sources",
        "source_bound": False, "rows": expected["rows"], "index": index,
        "baseline": expected,
        "projection_sha256": canonical_sha256(expected),
        "comparison_reconcilable": True,
    }
    if "devices" not in snapshot:
        return view
    receipt = _validate_protocol_assessability_receipt(
        snapshot.get("protocol_assessability"))
    if receipt.get("valid") is not True:
        return _invalidate_subject_roster(
            view,
            "stp_consistency protocol receipt denominator is missing or malformed for "
            "snapshot devices",
        )
    receipt_hosts = {
        key[0]
        for key in receipt.get("index", {})
        if isinstance(key, tuple) and len(key) == 2 and key[1] == "STP"
    }
    return reconcile_native_owner_subject_roster(
        view,
        snapshot,
        family="stp_consistency",
        coverage_hosts=receipt_hosts,
        subject_hosts=list(index),
    )


def compute_stp_consistency_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare the existing bounded state/inconsistent-port owner without parsing its prose."""
    before_view, after_view = _pair_views(
        _stp_consistency_view(before),
        _stp_consistency_view(after),
        before,
        after,
        comparison_source_binding,
    )

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        if _text(row.get("status")) in _UNAVAILABLE_STATUSES:
            return _change(name, "coverage_lost", "not_verified", {}, _state(row, ("status",)),
                           "A new positive STP subject lacks comparable consistency evidence.")
        return _change(name, "appeared", "review", {}, _state(row, ("status",)),
                       "A new positive STP consistency subject requires topology intent reconciliation.")

    def disappeared(name: str, row: Mapping[str, Any]) -> dict:
        return _change(name, "disappeared", "review", _state(row, ("status",)), {},
                       "A baseline STP consistency subject disappeared; configured STP applicability is not inferred.")

    changes, _represented = _compare_indexed(
        family="stp_consistency",
        before_view=before_view,
        after_view=after_view,
        subject=lambda key, _row: str(key),
        state_fields=("health_severity", "blocked_ports_state", "topology_changes_state"),
        semantic_fields=("health_severity",),
        missing_before=appeared,
        missing_after=disappeared,
    )
    return _result(
        schema=STP_CONSISTENCY_DELTA_SCHEMA,
        family="stp_consistency",
        assurance_level="local_safety_preservation",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "This preserves the existing bounded state and inconsistent-port claim only.",
            "Blocked-port and topology-change captures remain availability disclosures, not inferred zero counts.",
            "Root placement, roles, timers, convergence, and intended topology are not proved.",
        ),
    )


_STP_PATH_MIN_INSTANCE = 0  # MST instance 0 shares this legacy path projection with VLAN IDs.
_STP_PATH_MAX_INSTANCE = 4094
_STP_PATH_MAX_TOKENS = _STP_PATH_MAX_INSTANCE - _STP_PATH_MIN_INSTANCE + 1
_STP_PATH_MAX_TEXT = 32_768
_STP_PATH_MAX_DIGITS = len(str(_STP_PATH_MAX_INSTANCE))
_STP_PATH_TOKEN = re.compile(r"^([0-9]+)(?:-([0-9]+))?$")


def _stp_path_instances(raw: str) -> tuple[tuple[str, ...], frozenset[int]] | None:
    """Return a bounded canonical range display and exact instance set, or abstain.

    The existing interface projection does not distinguish PVST VLAN IDs from MST instance IDs,
    so zero remains admissible for MST0 while the upper bound stays at the VLAN ceiling.  Bounds
    are checked before ``range`` construction so hostile numeric endpoints cannot cause an
    unbounded expansion.  Empty components, reversed ranges, and excessive token lists fail
    closed instead of being partially interpreted.
    """
    if not raw or len(raw) > _STP_PATH_MAX_TEXT \
            or raw.count(",") >= _STP_PATH_MAX_TOKENS:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if not parts or len(parts) > _STP_PATH_MAX_TOKENS or any(not part for part in parts):
        return None

    def endpoint(value: str) -> int | None:
        if len(value) > _STP_PATH_MAX_DIGITS:
            return None
        parsed = int(value)
        return parsed if _STP_PATH_MIN_INSTANCE <= parsed <= _STP_PATH_MAX_INSTANCE else None

    instances: set[int] = set()
    for token in parts:
        match = _STP_PATH_TOKEN.fullmatch(token)
        if match is None:
            return None
        start = endpoint(match.group(1))
        end = endpoint(match.group(2) or match.group(1))
        if start is None or end is None or start > end:
            return None
        instances.update(range(start, end + 1))

    ordered = sorted(instances)
    canonical_ranges: List[str] = []
    start = end = ordered[0]
    for instance in ordered[1:]:
        if instance == end + 1:
            end = instance
            continue
        canonical_ranges.append(str(start) if start == end else f"{start}-{end}")
        start = end = instance
    canonical_ranges.append(str(start) if start == end else f"{start}-{end}")
    return tuple(canonical_ranges), frozenset(instances)


def _legacy_topology_view(snapshot: Any) -> dict:
    present = isinstance(snapshot, dict) and (
        "stp_roots" in snapshot or "interfaces" in snapshot)
    if not isinstance(snapshot, dict):
        return {"present": False, "valid": False, "reason": "STP topology sources are missing",
                "source_bound": False, "roots": {}, "paths": {}, "gaps": []}
    roots_raw, interfaces_raw = snapshot.get("stp_roots"), snapshot.get("interfaces")
    if not isinstance(roots_raw, dict) or not isinstance(interfaces_raw, dict):
        return {"present": present, "valid": False,
                "reason": "STP root or interface projection has an unusable root shape",
                "source_bound": False, "roots": {}, "paths": {}, "gaps": []}
    roots: Dict[Tuple[str, str, str], dict] = {}
    paths: Dict[Tuple[str, str], dict] = {}
    gaps: List[str] = []
    for host_value, instances in roots_raw.items():
        host = _text(host_value)
        if not host or not isinstance(instances, dict):
            gaps.append(f"root:{host or 'unknown'}")
            continue
        for instance_value, row in instances.items():
            instance = _text(instance_value)
            if not instance or not isinstance(row, dict) or type(row.get("is_mst")) is not bool \
                    or type(row.get("is_root")) is not bool:
                gaps.append(f"root:{host}:{instance or 'unknown'}")
                continue
            namespace = "mst_instance" if row["is_mst"] else "vlan_instance"
            root_address = _text(row.get("root_address"))
            root_priority = row.get("root_priority")
            bridge_priority = row.get("bridge_priority")
            if not root_address and row["is_root"] is not True:
                gaps.append(f"root:{host}:{namespace}:{instance}")
                continue
            if root_priority is not None and type(root_priority) is not int:
                gaps.append(f"root:{host}:{namespace}:{instance}")
                continue
            if bridge_priority is not None and type(bridge_priority) is not int:
                gaps.append(f"root:{host}:{namespace}:{instance}")
                continue
            roots[(host, namespace, instance)] = {
                "root_address": root_address,
                "root_priority": root_priority,
                "bridge_priority": bridge_priority,
                "is_root": row["is_root"],
            }
    for host_value, interfaces in interfaces_raw.items():
        host = _text(host_value)
        if not host or not isinstance(interfaces, dict):
            gaps.append(f"path:{host or 'unknown'}")
            continue
        for interface_value, row in interfaces.items():
            interface = _text(interface_value)
            if not interface or not isinstance(row, dict):
                continue
            values: dict[str, tuple[str, ...] | None] = {}
            instance_sets: dict[str, frozenset[int] | None] = {}
            malformed = False
            for source_field, output_field in (
                ("stp_fwd_vlans", "forwarding"), ("stp_blk_vlans", "blocked"),
            ):
                raw = row.get(source_field)
                if raw in (None, ""):
                    values[output_field] = None
                    instance_sets[output_field] = None
                    continue
                if not isinstance(raw, str):
                    malformed = True
                    break
                normalized = _stp_path_instances(raw)
                if normalized is None:
                    malformed = True
                    break
                values[output_field], instance_sets[output_field] = normalized
            if malformed:
                gaps.append(f"path:{host}:{interface}")
            elif values["forwarding"] is not None or values["blocked"] is not None:
                paths[(host, interface)] = {
                    **values,
                    "_instance_sets": instance_sets,
                }
    projection_payload = {
        "roots": [
            {"subject": list(key), "state": roots[key]}
            for key in sorted(roots)
        ],
        "paths": [
            {
                "subject": list(key),
                "forwarding": paths[key].get("forwarding"),
                "blocked": paths[key].get("blocked"),
            }
            for key in sorted(paths)
        ],
        "gaps": sorted(set(gaps)),
    }
    view = {
        "present": present, "valid": True,
        "reason": "bounded_existing_root_and_interface_projection",
        "source_bound": False, "roots": roots, "paths": paths,
        "gaps": sorted(set(gaps)),
        "projection_sha256": canonical_sha256(projection_payload),
        "comparison_reconcilable": True,
    }
    subject_hosts = {
        key[0] for key in roots
    } | {
        key[0] for key in paths
    }
    return reconcile_native_owner_subject_roster(
        view,
        snapshot,
        family="stp_topology",
        coverage_hosts=list(interfaces_raw),
        subject_hosts=subject_hosts,
    )


def _typed_topology_view(snapshot: Any) -> dict:
    root = _snapshot(snapshot)
    baseline_value = root.get("stp_topology_baseline")
    observations = root.get("stp_topology_observations")
    present = "stp_topology_baseline" in root or "stp_topology_observations" in root
    required_keys = {
        "stp_topology_baseline", "stp_topology_observations", "stp_roots", "devices",
    }
    if not required_keys <= set(root) or not isinstance(root.get("devices"), (dict, list)) \
            or not isinstance(root.get("stp_roots"), dict):
        return {
            "present": present,
            "valid": False,
            "reason": (
                "Typed STP topology baseline, observations, legacy roots, and explicit device "
                "denominator must be co-published"
            ),
            "source_bound": False,
            "comparison_reconcilable": False,
            "owner_source_authority": False,
            "baseline": {},
            "rows": [],
            "index": {},
            "roots": {},
            "paths": {},
            "gaps": ["typed_owner_receipt"],
            "typed": True,
        }
    view = validate_stp_topology_baseline(
        baseline_value,
        observations=observations,
        legacy_roots=root.get("stp_roots"),
        devices=root.get("devices"),
    )
    view = _reconcilable(view, owner_source_authority=False)
    if view.get("valid") is True:
        coverage = view.get("coverage")
        rows = view.get("rows")
        view = reconcile_native_owner_subject_roster(
            view,
            snapshot,
            family="stp_topology",
            coverage_hosts=[
                cell.get("switch") if isinstance(cell, Mapping) else None
                for cell in coverage
            ] if isinstance(coverage, list) else None,
            subject_hosts=[
                row.get("switch") if isinstance(row, Mapping) else None
                for row in rows
            ] if isinstance(rows, list) else None,
        )
    rows = view.get("rows") if view.get("valid") is True else []
    row_list = rows if isinstance(rows, list) else []
    view["roots"] = {
        (row["switch"], row["namespace"], row["instance"]): row
        for row in row_list if isinstance(row, Mapping)
    }
    view["paths"] = {
        (row["switch"], row["namespace"], row["instance"], port["interface"]): port
        for row in row_list if isinstance(row, Mapping)
        for port in row.get("port_roles", []) if isinstance(port, Mapping)
    }
    view["gaps"] = [
        _text(cell.get("switch"))
        for cell in view.get("coverage", []) if isinstance(cell, Mapping)
        and _text(cell.get("status")) == "not_verified"
    ]
    view["typed"] = True
    return view


def _topology_view(snapshot: Any) -> dict:
    root = _snapshot(snapshot)
    if "stp_topology_baseline" in root or "stp_topology_observations" in root:
        return _typed_topology_view(snapshot)
    view = _legacy_topology_view(snapshot)
    view["typed"] = False
    return view


def _typed_stp_coverage_index(view: Mapping[str, Any]) -> Dict[str, dict]:
    baseline = view.get("baseline")
    cells = baseline.get("coverage") if isinstance(baseline, Mapping) else None
    return {
        _text(cell.get("switch")): cell
        for cell in cells if isinstance(cell, Mapping) and _text(cell.get("switch"))
    } if isinstance(cells, list) else {}


def _typed_stp_port_index(row: Mapping[str, Any]) -> Dict[str, dict]:
    roles = row.get("port_roles")
    return {
        _text(port.get("interface")): dict(port)
        for port in roles if isinstance(port, Mapping) and _text(port.get("interface"))
    } if isinstance(roles, list) else {}


def _typed_stp_topology_changes(
        before_view: Mapping[str, Any], after_view: Mapping[str, Any]) -> List[dict]:
    invalid = _invalid_owner_changes("stp_topology", before_view, after_view)
    if invalid:
        return invalid
    before_index = before_view.get("index")
    after_index = after_view.get("index")
    if not isinstance(before_index, dict) or not isinstance(after_index, dict):
        return [_change(
            "stp_topology|owner_index", "not_comparable", "not_verified", {}, {},
            "The validated STP topology baseline did not expose its canonical instance index.",
        )]
    before_coverage = _typed_stp_coverage_index(before_view)
    after_coverage = _typed_stp_coverage_index(after_view)
    changes: List[dict] = []

    def cell_comparable(cell: Mapping[str, Any] | None) -> bool:
        return isinstance(cell, Mapping) and _text(cell.get("status")) in {
            "assessed", "degraded",
        }

    for host in sorted(set(before_coverage) | set(after_coverage), key=str.casefold):
        old_cell, new_cell = before_coverage.get(host), after_coverage.get(host)
        old_status = _text((old_cell or {}).get("status"))
        new_status = _text((new_cell or {}).get("status"))
        if old_status == new_status == "not_applicable":
            continue
        if not cell_comparable(old_cell) or not cell_comparable(new_cell):
            changes.append(_change(
                f"stp_topology|coverage|{host}",
                "coverage_lost",
                "not_verified",
                _state(old_cell, (
                    "status", "state_capture_state", "detail_capture_state",
                    "state_instance_count", "role_parsed_count", "counter_parsed_count",
                    "finding_codes",
                )),
                _state(new_cell, (
                    "status", "state_capture_state", "detail_capture_state",
                    "state_instance_count", "role_parsed_count", "counter_parsed_count",
                    "finding_codes",
                )),
                "Required paired STP state/detail coverage is unavailable on at least one side; "
                "missing roles or counters are not interpreted as healthy absence.",
            ))

    for key in sorted(set(before_index) | set(after_index)):
        old = before_index.get(key)
        new = after_index.get(key)
        host, namespace, instance = key
        identity = "|".join((host, namespace, instance))
        old_cell, new_cell = before_coverage.get(host), after_coverage.get(host)
        if not isinstance(old, Mapping):
            if not cell_comparable(new_cell):
                continue
            degraded = _text(new.get("status")) == "degraded"
            changes.append(_change(
                f"instance|{identity}", "appeared", "block" if degraded else "review", {},
                _state(new, ("status", "root_address", "is_root", "finding_codes")),
                "A newly observed STP instance is currently degraded; appearance cannot neutralize the fault."
                if degraded else
                "A new fully identified PVST/MST instance appeared and requires topology-intent reconciliation.",
            ))
            continue
        if not isinstance(new, Mapping):
            transition, effect, note = (
                ("disappeared", "review",
                 "A previously evidenced PVST/MST instance disappeared from complete after coverage; reconcile planned topology intent.")
                if cell_comparable(new_cell) else
                ("coverage_lost", "not_verified",
                 "The after capture is incomplete, so disappearance of the STP instance is not asserted.")
            )
            changes.append(_change(
                f"instance|{identity}", transition, effect,
                _state(old, ("status", "root_address", "is_root", "finding_codes")), {}, note,
            ))
            continue

        changes.append(_status_transition(
            f"health|{identity}",
            old,
            new,
            state_fields=("finding_codes", "forwarding_paths", "blocked_paths"),
            semantic_equal=True,
            change_note="The bounded STP instance health changed.",
        ))

        old_root = _state(old, (
            "root_address", "root_priority", "bridge_priority", "is_root",
        ))
        new_root = _state(new, (
            "root_address", "root_priority", "bridge_priority", "is_root",
        ))
        changes.append(_change(
            f"root|{identity}",
            "unchanged_healthy" if old_root == new_root else "intent_changed",
            "none" if old_root == new_root else "review",
            old_root,
            new_root,
            "The observed per-instance root identity and placement are unchanged."
            if old_root == new_root else
            "Observed root identity/placement changed; planned root movement may be expected but must be reconciled.",
        ))

        old_ports, new_ports = _typed_stp_port_index(old), _typed_stp_port_index(new)
        for interface in sorted(set(old_ports) | set(new_ports), key=str.casefold):
            old_port, new_port = old_ports.get(interface), new_ports.get(interface)
            subject = f"path|{identity}|{interface}"
            if old_port is None:
                changes.append(_change(
                    subject, "appeared", "review", {}, new_port,
                    "A new per-instance STP port role/path appeared; reconcile the planned topology movement.",
                ))
                continue
            if new_port is None:
                changes.append(_change(
                    subject, "disappeared", "review", old_port, {},
                    "A per-instance STP port role/path disappeared under complete after coverage; reconcile intent.",
                ))
                continue
            if old_port == new_port:
                transition, effect = "unchanged_healthy", "none"
                note = "The observed per-instance STP port role and state are unchanged."
            elif old_port.get("state") == "forwarding" and new_port.get("state") == "blocked":
                transition, effect = "regressed", "block"
                note = "A previously forwarding per-instance STP path is now blocked."
            elif new_port.get("state") in {"learning", "listening"}:
                transition, effect = "regressed", "block"
                note = "The after STP path is in a transitional state and is not stable forwarding evidence."
            elif old_port.get("role") != new_port.get("role"):
                transition, effect = "intent_changed", "review"
                note = "The per-instance STP role moved; planned role movement must be reconciled."
            elif old_port.get("state") == "blocked" and new_port.get("state") == "forwarding":
                transition, effect = "recovered", "none"
                note = "A previously blocked per-instance STP path is now forwarding without a role change."
            else:
                transition, effect = "intent_changed", "review"
                note = "The per-instance STP state moved and requires topology-intent reconciliation."
            changes.append(_change(subject, transition, effect, old_port, new_port, note))

        old_count, new_count = old.get("topology_change_count"), new.get("topology_change_count")
        before_counter = {
            "count": old_count,
            "last_change": old.get("topology_change_last_change"),
        }
        after_counter = {
            "count": new_count,
            "last_change": new.get("topology_change_last_change"),
        }
        if type(old_count) is not int or type(new_count) is not int:
            transition, effect = "coverage_lost", "not_verified"
            note = "A required per-instance topology-change counter is missing or malformed."
        elif new_count > old_count:
            transition, effect = "regressed", "block"
            note = "The per-instance topology-change counter increased after the change."
        elif new_count < old_count:
            transition, effect = "intent_changed", "review"
            note = "The topology-change counter decreased (reset, reload, or wrap); reconcile the evidence timeline."
        else:
            transition, effect = "unchanged_healthy", "none"
            note = "The per-instance topology-change counter did not increase."
        changes.append(_change(
            f"counter|{identity}", transition, effect,
            before_counter, after_counter, note,
        ))
    return changes


def compute_stp_topology_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare typed STP topology evidence, retaining a fail-closed legacy fallback."""
    before_view, after_view = _pair_views(
        _topology_view(before),
        _topology_view(after),
        before,
        after,
        comparison_source_binding,
    )
    before_typed = before_view.get("typed") is True
    after_typed = after_view.get("typed") is True
    if before_typed != after_typed:
        return _result(
            schema=STP_TOPOLOGY_DELTA_SCHEMA,
            family="stp_topology",
            assurance_level="not_verified",
            before_view=before_view,
            after_view=after_view,
            changes=[_change(
                "stp_topology|owner_semantics",
                "not_comparable",
                "not_verified",
                {"owner": "stp_topology_baseline/1" if before_typed else "legacy_projection"},
                {"owner": "stp_topology_baseline/1" if after_typed else "legacy_projection"},
                "Typed and legacy STP topology projections have incompatible subject semantics; "
                "legacy evidence is not backfilled or reinterpreted.",
            )],
            limitations=(
                "Legacy snapshots remain fail-closed and are never reinterpreted as typed role/counter evidence.",
                "Recollect both sides with stp_topology_baseline/1 for a comparable typed decision.",
            ),
        )
    if before_typed and after_typed:
        return _result(
            schema=STP_TOPOLOGY_DELTA_SCHEMA,
            family="stp_topology",
            assurance_level="local_safety_preservation",
            before_view=before_view,
            after_view=after_view,
            changes=_typed_stp_topology_changes(before_view, after_view),
            limitations=(
                "Scope is observed local PVST VLAN or MST instance root, role/state, and topology-change-counter preservation.",
                "Root/role movement defaults to review; it is accepted only through explicit expected-change reconciliation by the canonical gate.",
                "Loop freedom, timers, convergence, simultaneous multi-device state, and service survival are not proved.",
            ),
        )
    changes = _invalid_owner_changes("stp_topology", before_view, after_view)
    if not changes:
        for key in sorted(set(before_view["roots"]) | set(after_view["roots"])):
            subject = "root|" + "|".join(key)
            old, new = before_view["roots"].get(key), after_view["roots"].get(key)
            if old is None:
                changes.append(_change(subject, "appeared", "review", {}, new,
                                       "A newly observed STP root subject requires intended-root reconciliation."))
            elif new is None:
                changes.append(_change(subject, "disappeared", "review", old, {},
                                       "A previously evidenced STP root subject is no longer present."))
            elif old == new:
                changes.append(_change(subject, "unchanged_healthy", "none", old, new,
                                       "The bounded observed STP root projection is unchanged."))
            else:
                changes.append(_change(subject, "intent_changed", "review", old, new,
                                       "Observed STP root identity/placement changed; intended placement is not inferred."))
        for key in sorted(set(before_view["paths"]) | set(after_view["paths"])):
            subject = "path|" + "|".join(key)
            old, new = before_view["paths"].get(key), after_view["paths"].get(key)
            old_state = _state(old, ("forwarding", "blocked"))
            new_state = _state(new, ("forwarding", "blocked"))
            if old is None:
                changes.append(_change(subject, "appeared", "review", {}, new_state,
                                       "A new bounded forwarding/blocked path projection appeared."))
            elif new is None:
                changes.append(_change(subject, "coverage_lost", "not_verified", old_state, {},
                                       "Previously evidenced forwarding/blocked path state is no longer evidenced."))
            elif old == new:
                changes.append(_change(subject, "unchanged_healthy", "none", old_state, new_state,
                                       "The evidenced forwarding/blocked path sets are unchanged."))
            else:
                old_sets = old["_instance_sets"]
                new_sets = new["_instance_sets"]
                old_fwd = old_sets.get("forwarding") or frozenset()
                old_blk = old_sets.get("blocked") or frozenset()
                new_fwd = new_sets.get("forwarding") or frozenset()
                new_blk = new_sets.get("blocked") or frozenset()
                if old_fwd & new_blk:
                    transition, decision_effect = "regressed", "block"
                    note = "At least one previously forwarding instance is now evidenced as blocked."
                elif old_blk & new_fwd:
                    transition, decision_effect = "recovered", "none"
                    note = "At least one previously blocked instance is now evidenced as forwarding."
                else:
                    transition, decision_effect = "intent_changed", "review"
                    note = "The bounded forwarding/blocked instance sets changed and require topology intent reconciliation."
                changes.append(_change(
                    subject, transition, decision_effect, old_state, new_state, note))
        for gap in sorted(set(before_view["gaps"]) | set(after_view["gaps"])):
            changes.append(_change(
                f"stp_topology|coverage|{gap}", "coverage_lost", "not_verified", {}, {},
                "A malformed or incomplete STP topology leaf was withheld from comparison.",
            ))
        # The current baselines do not own per-port roles or topology-change counters.
        for dimension in ("port_roles", "topology_change_counters"):
            changes.append(_change(
                f"stp_topology|coverage|{dimension}", "coverage_lost", "not_verified", {}, {},
                f"The current typed baselines do not authorize {dimension.replace('_', ' ')} comparison.",
            ))
    return _result(
        schema=STP_TOPOLOGY_DELTA_SCHEMA,
        family="stp_topology",
        assurance_level="not_verified",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Root comparison is bounded to the existing per-instance root projection.",
            "Forwarding/blocked comparison is bounded to explicitly evidenced interface instance ranges.",
            "Per-port roles, complete PVST/MST namespace/configuration, topology-change counters, timers, and failure rehearsal are not verified.",
        ),
    )


def _legacy_etherchannel_view(snapshot: Any) -> dict:
    root = _snapshot(snapshot)
    value = root.get("etherchannel_baseline")
    view = _reconcilable(
        validate_etherchannel_baseline(
            value,
            projection=root.get("etherchannel_projection"),
            protocol_assessability=root.get("protocol_assessability"),
            devices=root.get("devices"),
        ),
        owner_source_authority=False,
    )
    if view.get("valid") is True and "devices" in root:
        projection_view = _validate_etherchannel_projection(
            root.get("etherchannel_projection"))
        receipt_view = _validate_protocol_assessability_receipt(
            root.get("protocol_assessability"))
        if projection_view.get("valid") is not True \
                or receipt_view.get("valid") is not True:
            view = _invalidate_subject_roster(
                view,
                "etherchannel source denominator is missing or malformed for snapshot devices",
            )
        else:
            subject_hosts = [
                row.get("switch") if isinstance(row, Mapping) else None
                for row in view.get("rows", [])
            ]
            view = reconcile_native_owner_subject_roster(
                view,
                snapshot,
                family="etherchannel projection",
                coverage_hosts=list(projection_view.get("index", {})),
                subject_hosts=subject_hosts,
            )
            if view.get("valid") is True:
                receipt_hosts = {
                    key[0]
                    for key in receipt_view.get("index", {})
                    if (isinstance(key, tuple) and len(key) == 2
                        and key[1] == "EtherChannel")
                }
                view = reconcile_native_owner_subject_roster(
                    view,
                    snapshot,
                    family="etherchannel receipt",
                    coverage_hosts=receipt_hosts,
                    subject_hosts=subject_hosts,
                )
    if view.get("valid") is True:
        view["projection_sha256"] = canonical_sha256({
            "baseline": value,
            "projection": root.get("etherchannel_projection"),
            "protocol_assessability": root.get("protocol_assessability"),
            "devices": root.get("devices"),
        })
    return view


def _etherchannel_view(snapshot: Any) -> dict:
    """Join the protected v1 owners to the additive typed decision-depth owner."""
    root = _snapshot(snapshot)
    legacy = _legacy_etherchannel_view(snapshot)
    typed = _reconcilable(
        _reconcile_baseline_coverage_roster(
            validate_etherchannel_operational_evidence(
                root.get("etherchannel_operational_evidence")),
            snapshot,
            family="etherchannel operational evidence",
        ),
        owner_source_authority=False,
    )
    if legacy.get("valid") is not True:
        return legacy
    if typed.get("valid") is not True:
        return _reconcilable(_invalidate_owner_evidence(
            typed,
            "The additive etherchannel_operational_evidence/1 owner is missing, malformed, "
            "or does not reconcile to the snapshot device roster.",
        ), owner_source_authority=False)

    typed_index = typed.get("index") if isinstance(typed.get("index"), dict) else {}
    # Every runtime group asserted by the protected v1 projection must reconcile exactly to
    # the typed owner's protocol and member states.  Typed configured-only groups are allowed:
    # that is decision depth the summary owner intentionally could not represent.
    for host_row in legacy.get("rows", []):
        if not isinstance(host_row, Mapping):
            continue
        host = _text(host_row.get("switch"))
        for legacy_group in host_row.get("groups", []):
            if not isinstance(legacy_group, Mapping):
                continue
            group = _text(legacy_group.get("group"))
            typed_row = typed_index.get((host, group))
            if not isinstance(typed_row, Mapping):
                return _reconcilable(_invalidate_owner_evidence(
                    typed,
                    "Typed EtherChannel evidence omits a runtime group asserted by the protected "
                    "etherchannel_projection/1 owner.",
                ), owner_source_authority=False)
            legacy_members = {
                _text(member.get("interface")): _text(member.get("state"))
                for member in legacy_group.get("members", [])
                if isinstance(member, Mapping) and _text(member.get("interface"))
            }
            typed_members = {
                _text(member.get("interface")): _text(member.get("state"))
                for member in typed_row.get("runtime_members", [])
                if isinstance(member, Mapping) and _text(member.get("interface"))
            }
            legacy_protocol = _text(legacy_group.get("protocol")).casefold()
            if legacy_members != typed_members or (
                    legacy_protocol and legacy_protocol != "unknown"
                    and legacy_protocol != _text(typed_row.get("protocol")).casefold()):
                return _reconcilable(_invalidate_owner_evidence(
                    typed,
                    "Typed EtherChannel runtime state does not exactly reconcile to the protected "
                    "etherchannel_projection/1 owner.",
                ), owner_source_authority=False)
            if (_text(legacy_group.get("status")) == "degraded"
                    and _text(typed_row.get("status")) != "degraded"):
                return _reconcilable(_invalidate_owner_evidence(
                    typed,
                    "Typed EtherChannel evidence attempted to clear degradation owned by the "
                    "protected etherchannel_projection/1 owner.",
                ), owner_source_authority=False)

    typed["projection_sha256"] = canonical_sha256({
        "etherchannel_baseline": root.get("etherchannel_baseline"),
        "etherchannel_projection": root.get("etherchannel_projection"),
        "protocol_assessability": root.get("protocol_assessability"),
        "etherchannel_operational_evidence": root.get(
            "etherchannel_operational_evidence"),
        "devices": root.get("devices"),
    })
    typed["legacy_baseline"] = legacy.get("baseline")
    return typed


def _etherchannel_groups(view: Mapping[str, Any]) -> Dict[Tuple[str, str], dict]:
    groups: Dict[Tuple[str, str], dict] = {}
    for row in view.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        host, name = _text(row.get("switch")), _text(row.get("group"))
        if not host or not name or (host, name) in groups:
            continue
        runtime = row.get("runtime_members") if isinstance(
            row.get("runtime_members"), list) else []
        forwarding = sorted(
            _text(member.get("interface")) for member in runtime
            if isinstance(member, Mapping) and member.get("forwarding") is True
        )
        findings = row.get("findings") if isinstance(row.get("findings"), list) else []
        groups[(host, name)] = {
            "status": _text(row.get("status")),
            "protocol": _text(row.get("protocol")),
            "group_id": _text(row.get("group_id")),
            "configured_members": deepcopy(row.get("configured_members")),
            "runtime_members": deepcopy(runtime),
            "forwarding_members": forwarding,
            "partner": deepcopy(row.get("partner")),
            "min_links": deepcopy(row.get("min_links")),
            "capacity": deepcopy(row.get("capacity")),
            "hashing": deepcopy(row.get("hashing")),
            "counter_evidence": deepcopy(row.get("counter_evidence")),
            "member_failure_rehearsal": deepcopy(row.get("member_failure_rehearsal")),
            "finding_codes": sorted(
                _text(finding.get("code")) for finding in findings
                if isinstance(finding, Mapping) and _text(finding.get("code"))
            ),
        }
    return groups


def compute_etherchannel_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare strict configured/runtime, capacity, counter, and local-failure evidence."""
    before_view, after_view = _pair_views(
        _etherchannel_view(before),
        _etherchannel_view(after),
        before,
        after,
        comparison_source_binding,
    )
    changes = _invalid_owner_changes("etherchannel", before_view, after_view)
    if not changes:
        old_groups, new_groups = _etherchannel_groups(before_view), _etherchannel_groups(after_view)
        after_coverage = _coverage_index(after_view.get("baseline", {}), ("switch",))
        for key in sorted(set(old_groups) | set(new_groups)):
            subject = "|".join(key)
            old, new = old_groups.get(key), new_groups.get(key)
            if old is None:
                status = _text(new.get("status"))
                if status == "degraded":
                    changes.append(_change(
                        subject, "appeared", "block", {}, new,
                        "A new local EtherChannel group appeared already degraded; expected intent "
                        "cannot clear a current min-links, counter, partner, member, or rehearsal fault.",
                    ))
                elif status in _UNAVAILABLE_STATUSES:
                    changes.append(_change(
                        subject, "coverage_lost", "not_verified", {}, new,
                        "A new configured/runtime group lacks complete typed operational evidence.",
                    ))
                else:
                    changes.append(_change(
                        subject, "appeared", "review", {}, new,
                        "A new healthy local EtherChannel group requires configured-intent reconciliation.",
                    ))
            elif new is None:
                coverage_cell = after_coverage.get((key[0],))
                if isinstance(coverage_cell, Mapping) and coverage_cell.get("status") in {
                        "assessed", "not_applicable"}:
                    changes.append(_change(
                        subject, "disappeared", "review", old, {},
                        "A validated configured/runtime group disappeared and requires expected-change reconciliation.",
                    ))
                else:
                    changes.append(_change(
                        subject, "coverage_lost", "not_verified", old, {},
                        "The after typed owner cannot verify group absence.",
                    ))
            elif old["status"] in _UNAVAILABLE_STATUSES or new["status"] in _UNAVAILABLE_STATUSES:
                changes.append(_change(subject, "coverage_lost", "not_verified", old, new,
                                       "Local group/member evidence is review or not verified on at least one side."))
            elif old["status"] == "degraded" and new["status"] == "degraded":
                changes.append(_change(subject, "unchanged_degraded", "block", old, new,
                                       "The local EtherChannel degradation remains present."))
            elif old["status"] != "degraded" and new["status"] == "degraded":
                changes.append(_change(subject, "regressed", "block", old, new,
                                       "A previously acceptable local group/member state is degraded."))
            elif old["status"] == "degraded" and new["status"] != "degraded":
                changes.append(_change(subject, "recovered", "none", old, new,
                                       "The previously degraded local group/member state recovered."))
            elif (new["capacity"]["forwarding_member_count"]
                  < old["capacity"]["forwarding_member_count"]):
                changes.append(_change(subject, "regressed", "block", old, new,
                                       "Observed forwarding-member count decreased."))
            elif (type(new["capacity"].get("forwarding_bandwidth_mbps")) is int
                  and type(old["capacity"].get("forwarding_bandwidth_mbps")) is int
                  and new["capacity"]["forwarding_bandwidth_mbps"]
                  < old["capacity"]["forwarding_bandwidth_mbps"]):
                changes.append(_change(subject, "regressed", "block", old, new,
                                       "Observed forwarding bandwidth decreased."))
            elif (new["capacity"]["forwarding_member_count"]
                  > old["capacity"]["forwarding_member_count"]):
                changes.append(_change(subject, "recovered", "none", old, new,
                                       "Observed forwarding-member count increased."))
            elif old != new:
                changes.append(_change(subject, "intent_changed", "review", old, new,
                                       "Protocol, configured association, runtime member, or member-state detail changed."))
            else:
                changes.append(_change(subject, "unchanged_healthy", "none", old, new,
                                       "The validated local group/member projection and count-based capacity are unchanged."))
    return _result(
        schema=ETHERCHANNEL_DELTA_SCHEMA,
        family="etherchannel",
        assurance_level="intent_reconciled_survival",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Configured member modes, runtime members, explicit LACP partner identity, min-links, count/bandwidth capacity, hashing, bounded counters, and local member-loss eligibility are compared for declared IOS/NX-OS variants.",
            "The local member-loss rehearsal does not prove convergence, hashing distribution, remote forwarding, traffic continuity, or service-path survival.",
            "Single-chassis EtherChannel remains distinct from multichassis LAG pair and attachment identity.",
        ),
    )


def _vtp_evidence_view(snapshot: Any) -> dict:
    """Require the additive owner and reconcile its protected-v1 core projection."""
    extended = _reconcile_baseline_coverage_roster(
        validate_vtp_extended_evidence(_owner_value(snapshot, "vtp_extended_evidence")),
        snapshot,
        family="vtp_safety extended evidence",
    )
    legacy = _reconcile_baseline_coverage_roster(
        validate_vtp_safety_baseline(_owner_value(snapshot, "vtp_safety_baseline")),
        snapshot,
        family="vtp_safety protected v1 evidence",
    )
    if extended.get("valid") is not True:
        return _reconcilable(extended)
    if legacy.get("valid") is not True:
        return _reconcilable(_invalidate_owner_evidence(
            extended,
            "The protected vtp_safety_baseline/1 co-owner is missing, malformed, or does not "
            "reconcile to the snapshot device roster.",
        ))

    legacy_index = legacy.get("index") if isinstance(legacy.get("index"), dict) else {}
    extended_index = extended.get("index") if isinstance(extended.get("index"), dict) else {}
    legacy_coverage = _coverage_index(legacy.get("baseline", {}), ("switch",))
    core_fields = (
        "mode", "mode_present", "domain", "domain_present", "version",
        "version_present", "revision", "revision_present",
    )
    for host, row in extended_index.items():
        protected = legacy_index.get(host)
        if protected is None:
            cell = legacy_coverage.get((host,))
            explicit_disabled = bool(
                isinstance(cell, Mapping)
                and cell.get("explicit_no_subject") is True
                and cell.get("parser_status") == "explicit_no_subject"
                and row.get("mode") == "off"
            )
            co_owned_abstention = bool(
                isinstance(cell, Mapping)
                and cell.get("subject") is False
                and row.get("status") == "not_verified"
            )
            if not explicit_disabled and not co_owned_abstention:
                return _reconcilable(_invalidate_owner_evidence(
                    extended,
                    "The additive VTP row does not reconcile to protected v1 subject evidence.",
                ))
        elif any(row.get(field) != protected.get(field) for field in core_fields):
            return _reconcilable(_invalidate_owner_evidence(
                extended,
                "The additive VTP mode/domain/version/revision leaves contradict protected v1.",
            ))
    if set(legacy_index) - set(extended_index):
        return _reconcilable(_invalidate_owner_evidence(
            extended,
            "The protected v1 VTP owner contains a subject absent from additive evidence.",
        ))
    normalized = dict(extended)
    normalized["source_bound"] = bool(
        extended.get("source_bound") is True and legacy.get("source_bound") is True
    )
    return _reconcilable(normalized)


def compute_vtp_safety_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare complete VTP/VLAN safety evidence with movement defaulting to review."""
    before_view, after_view = _pair_views(
        _vtp_evidence_view(before),
        _vtp_evidence_view(after),
        before,
        after,
        comparison_source_binding,
    )
    changes = _invalid_owner_changes("vtp_safety", before_view, after_view)
    represented: set[Tuple[str, ...]] = set()
    fields = (
        "status", "mode", "mode_present", "domain", "domain_present",
        "version", "version_present", "revision", "revision_present",
        "database_identity", "vlan_database_digest", "vlan_count",
        "pruning_state", "authentication_configured",
    )

    def revision_decreased(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
        return bool(
            old.get("revision_present") is True and new.get("revision_present") is True
            and type(old.get("revision")) is int and type(new.get("revision")) is int
            and new["revision"] < old["revision"]
        )

    def pure_revision_decrease(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
        invariant_fields = (
            "mode", "mode_present", "domain", "domain_present", "version",
            "version_present", "revision_present", "database_identity",
            "vlan_database_digest", "vlan_count", "pruning_state",
            "authentication_configured",
        )
        return revision_decreased(old, new) and all(
            old.get(field) == new.get(field) for field in invariant_fields
        )

    def with_change_kind(change: dict, old: Mapping[str, Any], new: Mapping[str, Any]) -> dict:
        change["change_kind"] = (
            "revision_decrease_observed" if pure_revision_decrease(old, new)
            else "configuration_movement"
        )
        return change

    if not changes:
        before_index, after_index = before_view["index"], after_view["index"]
        after_coverage = _coverage_index(after_view["baseline"], ("switch",))
        for host in sorted(set(before_index) | set(after_index), key=lambda value: (value.casefold(), value)):
            represented.add((host,))
            old, new = before_index.get(host), after_index.get(host)
            if old is None:
                changes.append(_change(
                    host, "appeared", "block" if new.get("status") == "unsafe" else "review",
                    {}, _state(new, fields),
                    "A new VTP subject appeared; current unsafe evidence blocks and reset/enablement intent is not inferred.",
                ))
            elif new is None:
                cell = after_coverage.get((host,))
                if not _cell_neutral("vtp_safety", cell):
                    changes.append(_change(
                        host, "coverage_lost", "not_verified", _state(old, fields), {},
                        "The after VTP capture/parser coverage cannot establish an explicit disablement or reset.",
                    ))
                else:
                    changes.append(_change(
                        host, "disappeared", "review", _state(old, fields), {},
                        "A VTP subject disappeared; explicit disablement/reset intent must be reconciled.",
                    ))
            elif old.get("status") == "not_verified" or new.get("status") == "not_verified":
                changes.append(_change(
                    host, "coverage_lost", "not_verified", _state(old, fields), _state(new, fields),
                    "At least one complete three-command VTP/VLAN row is not verified; no safe movement is asserted.",
                ))
            elif old.get("status") == "unsafe" and new.get("status") == "unsafe":
                changes.append(_change(
                    host, "unchanged_degraded", "block", _state(old, fields), _state(new, fields),
                    "Current high-revision, authentication, or VLAN-digest unsafety remains; changed details do not make it acceptable.",
                ))
            elif new.get("status") == "unsafe":
                changes.append(_change(
                    host, "regressed", "block", _state(old, fields), _state(new, fields),
                    "The current VTP/VLAN evidence is unsafe; expected movement cannot clear this blocker.",
                ))
            elif old.get("status") == "unsafe":
                changes.append(with_change_kind(_change(
                    host, "recovered", "review", _state(old, fields), _state(new, fields),
                    "The prior VTP/VLAN safety fault cleared through observed movement that still requires explicit intent reconciliation.",
                ), old, new))
            elif any(old.get(field) != new.get(field) for field in fields[1:]):
                changes.append(with_change_kind(_change(
                    host, "intent_changed", "review", _state(old, fields), _state(new, fields),
                    "VTP mode/domain/version/revision, VLAN digest, pruning, or authentication-presence moved; change intent must be reconciled.",
                ), old, new))
            else:
                changes.append(_change(
                    host, "unchanged_healthy", "none", _state(old, fields), _state(new, fields),
                    "The validated complete VTP/VLAN safety projection is unchanged and currently healthy.",
                ))
    if before_view.get("valid") and after_view.get("valid"):
        _append_coverage_gaps(
            changes,
            family="vtp_safety",
            before_baseline=before_view["baseline"],
            after_baseline=after_view["baseline"],
            key_fields=("switch",),
            represented=represented,
        )
    return _result(
        schema=VTP_SAFETY_DELTA_SCHEMA,
        family="vtp_safety",
        assurance_level="local_safety_preservation",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "All mode/domain/version/revision, VLAN-digest, pruning, and authentication-presence movement requires review unless reconciled by cutover_change_intent/1.",
            "A revision decrease is labelled only as an observed decrease; it can be reconciled as a reset only by exact-subject revision_reset intent in cutover_change_intent/1.",
            "Advertisement reachability, convergence, per-port VLAN membership, and authentication secrets remain outside this owner.",
        ),
    )


def compute_fhrp_configured_group_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare the validated literal local configured-group denominator."""
    before_view, after_view = _pair_views(
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_fhrp_configured_group_baseline(
                _owner_value(before, "fhrp_configured_group_baseline")),
            before,
            family="fhrp_configured_group",
        )),
        _reconcilable(_reconcile_baseline_coverage_roster(
            validate_fhrp_configured_group_baseline(
                _owner_value(after, "fhrp_configured_group_baseline")),
            after,
            family="fhrp_configured_group",
        )),
        before,
        after,
        comparison_source_binding,
    )
    after_coverage = _coverage_index(
        after_view.get("baseline", {}), ("switch", "protocol"))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        status = _text(row.get("status"))
        state = _state(
            row, ("status", "activation", "configured_vip", "runtime_state"))
        if status in _UNAVAILABLE_STATUSES:
            return _change(
                name, "coverage_lost", "not_verified", {}, state,
                "The new local FHRP group lacks verified configuration/runtime evidence, so its state is not asserted.",
            )
        if status == "degraded" and _text(row.get("activation")) == "active":
            return _change(
                name, "appeared", "block", {}, state,
                "A new configured-active local FHRP group is already degraded; expected intent cannot clear a current fault.",
            )
        return _change(name, "appeared", "review", {},
                       state,
                       "A new literal local FHRP group requires intent reconciliation.")

    def disappeared(name: str, row: Mapping[str, Any]) -> dict:
        active = _text(row.get("activation")) == "active"
        cell = after_coverage.get((_text(row.get("switch")), _text(row.get("protocol"))))
        if not _cell_neutral("fhrp_configured_group", cell):
            return _change(
                name, "coverage_lost", "not_verified",
                _state(row, ("status", "activation", "configured_vip", "runtime_state")), {},
                "The after configuration/runtime capture is not verified, so local-group disappearance is not asserted.",
            )
        return _change(name, "disappeared", "block" if active else "review",
                       _state(row, ("status", "activation", "configured_vip", "runtime_state")), {},
                       "A configured-active local FHRP group disappeared from the validated denominator."
                       if active else "A disabled local group was removed; reconcile the intent change.")

    changes, represented = _compare_indexed(
        family="fhrp_configured_group",
        before_view=before_view,
        after_view=after_view,
        subject=lambda _key, row: "|".join((
            _text(row.get("switch")), _text(row.get("protocol")),
            _text(row.get("interface")), _text(row.get("group")),
        )),
        state_fields=("activation", "configured_vip", "runtime_observed", "runtime_state", "runtime_vip"),
        semantic_fields=("activation", "configured_vip", "runtime_state", "runtime_vip"),
        missing_before=appeared,
        missing_after=disappeared,
    )
    if before_view.get("valid") and after_view.get("valid"):
        _append_coverage_gaps(
            changes,
            family="fhrp_configured_group",
            before_baseline=before_view["baseline"],
            after_baseline=after_view["baseline"],
            key_fields=("switch", "protocol"),
            represented=represented,
        )
    return _result(
        schema=FHRP_CONFIGURED_GROUP_DELTA_SCHEMA,
        family="fhrp_configured_group",
        assurance_level="intent_reconciled_survival",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Scope is direct-literal local default/global IPv4 HSRP, VRRP, and GLBP groups.",
            "A local role change is reviewable intent movement; domain redundancy is decided only by the redundancy-domain delta.",
            "Timers, authentication, tracking, failover, convergence, and simultaneous election are not proved.",
        ),
    )


def _domain_state(domain: Mapping[str, Any]) -> dict:
    members = []
    for member in domain.get("members", []):
        if isinstance(member, dict):
            members.append({
                "switch": _text(member.get("switch")),
                "interface": _text(member.get("interface")),
                "participation": _text(member.get("participation")),
                "role": _text(member.get("role")),
                "local_status": _text(member.get("local_status")),
            })
    return {
        "status": _text(domain.get("status")),
        "leader_count": domain.get("leader_count"),
        "backup_count": domain.get("backup_count"),
        "participant_count": domain.get("participant_count"),
        "member_count": domain.get("member_count"),
        "members": sorted(members, key=lambda row: (row["switch"].casefold(), row["interface"])),
    }


def _domain_healthy(state: Mapping[str, Any]) -> bool:
    return (
        state.get("status") == "assessed"
        and state.get("leader_count") == 1
        and isinstance(state.get("backup_count"), int) and state["backup_count"] >= 1
        and isinstance(state.get("participant_count"), int) and state["participant_count"] >= 2
    )


def compute_fhrp_redundancy_domain_delta(
        before: Any, after: Any, *, comparison_source_binding: Any = None) -> dict:
    """Compare validated domains; role movement is non-regressive while redundancy survives."""
    def domain_view(snapshot: Any) -> dict:
        view = validate_fhrp_redundancy_domain_baseline(
            _owner_value(snapshot, "fhrp_redundancy_domain_baseline"))
        baseline = view.get("baseline") if isinstance(view, Mapping) else None
        source = baseline.get("source_receipt") if isinstance(baseline, Mapping) else None
        normalized = _reconcilable(
            view,
            eligible=isinstance(source, Mapping) and source.get("valid") is True,
        )
        if normalized.get("valid") is not True or "devices" not in _snapshot(snapshot):
            return normalized

        upstream = validate_fhrp_configured_group_baseline(
            _owner_value(snapshot, "fhrp_configured_group_baseline"))
        upstream = _reconcile_baseline_coverage_roster(
            upstream,
            snapshot,
            family="fhrp_redundancy_domain",
        )
        if upstream.get("valid") is not True:
            if upstream.get("subject_roster_failure") is True:
                return _invalidate_subject_roster(
                    normalized,
                    "fhrp_redundancy_domain configured-group source roster does not "
                    "reconcile to snapshot devices",
                )
            return _invalidate_owner_evidence(
                normalized,
                "fhrp_redundancy_domain requires its co-published configured-group source",
            )

        upstream_baseline = upstream.get("baseline")
        upstream_summary = (
            upstream_baseline.get("summary")
            if isinstance(upstream_baseline, Mapping) else None
        )
        expected_digest = (
            upstream_summary.get("baseline_sha256")
            if isinstance(upstream_summary, Mapping) else None
        )
        if not isinstance(source, Mapping) or source.get(
                "configured_baseline_sha256") != expected_digest:
            return _invalidate_subject_roster(
                normalized,
                "fhrp_redundancy_domain source receipt does not reconcile to the "
                "co-published configured-group baseline",
            )

        coverage = upstream_baseline.get("coverage") \
            if isinstance(upstream_baseline, Mapping) else None
        coverage_hosts = [
            cell.get("switch") if isinstance(cell, Mapping) else None
            for cell in coverage
        ] if isinstance(coverage, list) else None
        subject_hosts = [
            row.get("switch") if isinstance(row, Mapping) else None
            for row in normalized.get("rows", [])
        ]
        return reconcile_native_owner_subject_roster(
            normalized,
            snapshot,
            family="fhrp_redundancy_domain",
            coverage_hosts=coverage_hosts,
            subject_hosts=subject_hosts,
        )

    before_view, after_view = _pair_views(
        domain_view(before),
        domain_view(after),
        before,
        after,
        comparison_source_binding,
    )
    changes = _invalid_owner_changes("fhrp_redundancy_domain", before_view, after_view)
    if not changes:
        old_domains = before_view.get("domain_index", {})
        new_domains = after_view.get("domain_index", {})
        for key in sorted(set(old_domains) | set(new_domains), key=lambda item: (item.casefold(), item)):
            subject = key
            old_raw, new_raw = old_domains.get(key), new_domains.get(key)
            old = _domain_state(old_raw) if isinstance(old_raw, Mapping) else None
            new = _domain_state(new_raw) if isinstance(new_raw, Mapping) else None
            if old is None:
                if not isinstance(new, Mapping) or new.get("status") == "not_verified":
                    changes.append(_change(
                        subject, "coverage_lost", "not_verified", {}, new or {},
                        "The new FHRP redundancy domain is not source-verified, so no healthy domain is asserted.",
                    ))
                elif _domain_healthy(new):
                    changes.append(_change(
                        subject, "appeared", "review", {}, new,
                        "A new healthy observed FHRP redundancy domain requires intended-domain reconciliation.",
                    ))
                else:
                    changes.append(_change(
                        subject, "appeared", "block", {}, new,
                        "A new FHRP redundancy domain already has zero/multiple leaders or insufficient observed redundancy; expected intent cannot clear a current fault.",
                    ))
                continue
            if new is None:
                changes.append(_change(subject, "disappeared", "block", old, {},
                                       "A validated baseline FHRP redundancy domain disappeared."))
                continue
            if old["status"] == "not_verified" or new["status"] == "not_verified":
                changes.append(_change(subject, "coverage_lost", "not_verified", old, new,
                                       "At least one domain composition is not source-verified; no role/redundancy transition is asserted."))
                continue
            old_healthy, new_healthy = _domain_healthy(old), _domain_healthy(new)
            if old_healthy and not new_healthy:
                changes.append(_change(subject, "regressed", "block", old, new,
                                       "The domain lost exactly-one-leader or observed backup/member redundancy."))
            elif not old_healthy and new_healthy:
                changes.append(_change(subject, "recovered", "none", old, new,
                                       "The domain now has exactly one leader and observed backup/member redundancy."))
            elif not old_healthy and not new_healthy:
                changes.append(_change(subject, "unchanged_degraded", "block", old, new,
                                       "Zero/multiple leaders or redundancy loss remains present; a clean delta is not acceptance."))
            elif old != new:
                changes.append(_change(subject, "intent_changed", "review", old, new,
                                       "Member roles or composition moved while exactly one leader and redundancy survived; this is not a regression but needs planned-role reconciliation."))
            else:
                changes.append(_change(subject, "unchanged_healthy", "none", old, new,
                                       "Exactly one leader and observed backup/member redundancy remain unchanged."))
    return _result(
        schema=FHRP_REDUNDANCY_DOMAIN_DELTA_SCHEMA,
        family="fhrp_redundancy_domain",
        assurance_level="observed_state_preservation",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Domain identity is exact VLAN, normalized VRF, and observed IPv4 subnet; candidates remain protocol/group/VIP scoped.",
            "Role movement is not a regression when exactly one leader and observed redundancy survive.",
            "Sequential captures do not prove simultaneity, failover, convergence, or intended/off-scan member count.",
        ),
    )


__all__ = [
    "IPV6_ROUTING_ADJACENCY_DELTA_SCHEMA",
    "BGP_CONFIGURED_PEER_DELTA_SCHEMA",
    "STP_CONSISTENCY_DELTA_SCHEMA",
    "STP_TOPOLOGY_DELTA_SCHEMA",
    "ETHERCHANNEL_DELTA_SCHEMA",
    "VTP_SAFETY_DELTA_SCHEMA",
    "FHRP_CONFIGURED_GROUP_DELTA_SCHEMA",
    "FHRP_REDUNDANCY_DOMAIN_DELTA_SCHEMA",
    "reconcile_native_owner_subject_roster",
    "compute_ipv6_routing_adjacency_delta",
    "compute_bgp_configured_peer_delta",
    "compute_stp_consistency_delta",
    "compute_stp_topology_delta",
    "compute_etherchannel_delta",
    "compute_vtp_safety_delta",
    "compute_fhrp_configured_group_delta",
    "compute_fhrp_redundancy_domain_delta",
]
