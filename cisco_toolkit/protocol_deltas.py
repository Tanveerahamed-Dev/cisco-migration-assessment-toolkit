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

from .analyze import summarize_stp_consistency_baseline, validate_etherchannel_baseline
from .bgp_intent import validate_bgp_configured_peer_baseline
from .fhrp_intent import validate_fhrp_configured_group_baseline
from .fhrp_redundancy import validate_fhrp_redundancy_domain_baseline
from .ipv6_routing import validate_ipv6_routing_adjacency_baseline
from .protocol_assurance import ASSURANCE_LEVELS, CHANGE_VOCABULARY
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
        "reason": _text(view.get("reason")),
    }


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
    normalized = []
    for raw in changes:
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
    return {
        "schema": schema,
        "family": family,
        "owner": schema,
        "assurance_level": assurance_level,
        "owns_score": False,
        "owns_verdict": False,
        "comparable": bool(comparable) and not by_transition["not_comparable"],
        "assessed": bool(comparable) and not (
            by_transition["coverage_lost"] or by_transition["not_comparable"]
        ),
        "source_receipts": {
            "before": _receipt(before_view),
            "after": _receipt(after_view),
        },
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
    if before_view.get("valid") is True and after_view.get("valid") is True:
        return []
    after_present = after_view.get("present") is True
    # With no valid baseline denominator, even a valid after value cannot define survival.
    transition = (
        "coverage_lost"
        if before_view.get("valid") is True and not after_present
        else "not_comparable"
    )
    return [_change(
        f"{family}|owner_receipt",
        transition,
        "not_verified",
        {"valid": before_view.get("valid") is True,
         "reason": _text(before_view.get("reason"))},
        {"valid": after_view.get("valid") is True,
         "reason": _text(after_view.get("reason"))},
        (
            "The after owner receipt is missing, so the baseline subject denominator lost coverage."
            if transition == "coverage_lost" else
            "One or both owner receipts are malformed, missing at baseline, or semantically incompatible; "
            "their caller-controlled leaves were not compared."
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


def compute_ipv6_routing_adjacency_delta(before: Any, after: Any) -> dict:
    """Compare validated observed default/global OSPFv3 and BGPv6 adjacencies."""
    before_value = _owner_value(before, "ipv6_routing_adjacency_baseline")
    after_value = _owner_value(after, "ipv6_routing_adjacency_baseline")
    before_view = validate_ipv6_routing_adjacency_baseline(before_value)
    after_view = validate_ipv6_routing_adjacency_baseline(after_value)
    after_coverage = _coverage_index(
        after_view.get("baseline", {}), ("switch", "protocol"))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        return _change(name, "appeared", "review", {}, _state(row, ("status", "state")),
                       "A runtime adjacency not observed in the baseline is now present; no expected-peer intent was inferred.")

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


def compute_bgp_configured_peer_delta(before: Any, after: Any) -> dict:
    """Compare the validated direct-literal default/global configured BGP peer denominator."""
    before_view = validate_bgp_configured_peer_baseline(
        _owner_value(before, "bgp_configured_peer_baseline"))
    after_view = validate_bgp_configured_peer_baseline(
        _owner_value(after, "bgp_configured_peer_baseline"))
    after_coverage = _coverage_index(after_view.get("baseline", {}), ("switch",))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        return _change(name, "appeared", "review", {},
                       _state(row, ("status", "activation", "configured_remote_as", "runtime_state")),
                       "A new literal configured peer requires expected-change reconciliation.")

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
    return {
        "present": True, "valid": True,
        "reason": "recomputed_from_exact_existing_owner_sources",
        "source_bound": False, "rows": expected["rows"], "index": index,
        "baseline": expected,
    }


def compute_stp_consistency_delta(before: Any, after: Any) -> dict:
    """Compare the existing bounded state/inconsistent-port owner without parsing its prose."""
    before_view, after_view = _stp_consistency_view(before), _stp_consistency_view(after)

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


def _topology_view(snapshot: Any) -> dict:
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
    vlan_token = re.compile(r"^[0-9]+(?:-[0-9]+)?$")
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
            malformed = False
            for source_field, output_field in (
                ("stp_fwd_vlans", "forwarding"), ("stp_blk_vlans", "blocked"),
            ):
                raw = row.get(source_field)
                if raw in (None, ""):
                    values[output_field] = None
                    continue
                if not isinstance(raw, str):
                    malformed = True
                    break
                tokens = tuple(sorted({part.strip() for part in raw.split(",") if part.strip()}))
                if not tokens or any(not vlan_token.fullmatch(token) for token in tokens):
                    malformed = True
                    break
                values[output_field] = tokens
            if malformed:
                gaps.append(f"path:{host}:{interface}")
            elif values["forwarding"] is not None or values["blocked"] is not None:
                paths[(host, interface)] = values
    return {
        "present": present, "valid": True,
        "reason": "bounded_existing_root_and_interface_projection",
        "source_bound": False, "roots": roots, "paths": paths,
        "gaps": sorted(set(gaps)),
    }


def compute_stp_topology_delta(before: Any, after: Any) -> dict:
    """Compare evidenced roots/path sets and abstain on absent roles/change counters."""
    before_view, after_view = _topology_view(before), _topology_view(after)
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
            if old is None:
                changes.append(_change(subject, "appeared", "review", {}, new,
                                       "A new bounded forwarding/blocked path projection appeared."))
            elif new is None:
                changes.append(_change(subject, "coverage_lost", "not_verified", old, {},
                                       "Previously evidenced forwarding/blocked path state is no longer evidenced."))
            elif old == new:
                changes.append(_change(subject, "unchanged_healthy", "none", old, new,
                                       "The evidenced forwarding/blocked path sets are unchanged."))
            else:
                old_fwd, old_blk = set(old.get("forwarding") or ()), set(old.get("blocked") or ())
                new_fwd, new_blk = set(new.get("forwarding") or ()), set(new.get("blocked") or ())
                if old_fwd & new_blk:
                    transition, decision_effect = "regressed", "block"
                    note = "At least one previously forwarding instance is now evidenced as blocked."
                elif old_blk & new_fwd:
                    transition, decision_effect = "recovered", "none"
                    note = "At least one previously blocked instance is now evidenced as forwarding."
                else:
                    transition, decision_effect = "intent_changed", "review"
                    note = "The bounded forwarding/blocked instance sets changed and require topology intent reconciliation."
                changes.append(_change(subject, transition, decision_effect, old, new, note))
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


def _etherchannel_view(snapshot: Any) -> dict:
    root = _snapshot(snapshot)
    value = root.get("etherchannel_baseline")
    return validate_etherchannel_baseline(
        value,
        projection=root.get("etherchannel_projection"),
        protocol_assessability=root.get("protocol_assessability"),
        devices=root.get("devices"),
    )


def _etherchannel_groups(view: Mapping[str, Any]) -> Dict[Tuple[str, str], dict]:
    groups: Dict[Tuple[str, str], dict] = {}
    for host_row in view.get("rows", []):
        if not isinstance(host_row, dict):
            continue
        host = _text(host_row.get("switch"))
        associations: Dict[str, List[str]] = {}
        for item in host_row.get("associations", []):
            if isinstance(item, dict):
                associations.setdefault(_text(item.get("group")), []).append(_text(item.get("interface")))
        for group in host_row.get("groups", []):
            if not isinstance(group, dict):
                continue
            name = _text(group.get("group"))
            if not host or not name or (host, name) in groups:
                continue
            members = {
                _text(item.get("interface")): _text(item.get("state"))
                for item in group.get("members", []) if isinstance(item, dict) and _text(item.get("interface"))
            }
            forwarding = sorted(
                member for member, state in members.items()
                if state in {"forwarding_observed", "delay_lacp_up"}
            )
            groups[(host, name)] = {
                "status": _text(group.get("status")) or _text(host_row.get("status")),
                "protocol": _text(group.get("protocol")),
                "group_id": _text(group.get("group_id")),
                "operational_state": _text(group.get("operational_state")),
                "configured_members": sorted(set(associations.get(name, []))),
                "runtime_members": sorted(members),
                "member_states": members,
                "forwarding_members": forwarding,
                "forwarding_capacity_units": len(forwarding),
            }
    return groups


def compute_etherchannel_delta(before: Any, after: Any) -> dict:
    """Compare validated local group/member state and count-based capacity only."""
    before_view, after_view = _etherchannel_view(before), _etherchannel_view(after)
    changes = _invalid_owner_changes("etherchannel", before_view, after_view)
    if not changes:
        old_groups, new_groups = _etherchannel_groups(before_view), _etherchannel_groups(after_view)
        for key in sorted(set(old_groups) | set(new_groups)):
            subject = "|".join(key)
            old, new = old_groups.get(key), new_groups.get(key)
            if old is None:
                changes.append(_change(subject, "appeared", "review", {}, new,
                                       "A new local EtherChannel group appeared and requires configured-intent reconciliation."))
            elif new is None:
                changes.append(_change(subject, "coverage_lost", "not_verified", old, {},
                                       "The after local group/member receipt is no longer assessed; group disappearance is not asserted."))
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
            elif new["forwarding_capacity_units"] < old["forwarding_capacity_units"]:
                changes.append(_change(subject, "regressed", "block", old, new,
                                       "Observed forwarding-member capacity units decreased."))
            elif new["forwarding_capacity_units"] > old["forwarding_capacity_units"]:
                changes.append(_change(subject, "recovered", "none", old, new,
                                       "Observed forwarding-member capacity units increased."))
            elif old != new:
                changes.append(_change(subject, "intent_changed", "review", old, new,
                                       "Protocol, configured association, runtime member, or member-state detail changed."))
            else:
                changes.append(_change(subject, "unchanged_healthy", "none", old, new,
                                       "The validated local group/member projection and count-based capacity are unchanged."))
    return _result(
        schema=ETHERCHANNEL_DELTA_SCHEMA,
        family="etherchannel",
        assurance_level="observed_state_preservation",
        before_view=before_view,
        after_view=after_view,
        changes=changes,
        limitations=(
            "Only validated local configured associations, runtime members, flags, protocol, and count-based forwarding capacity are compared.",
            "LACP/PAgP partner identity, min-links, hashing behavior, counters, failure rehearsal, and multi-chassis state are not inferred.",
        ),
    )


def compute_vtp_safety_delta(before: Any, after: Any) -> dict:
    """Compare validated VTP mode/domain/version/revision with movement defaulting to review."""
    before_view = validate_vtp_safety_baseline(_owner_value(before, "vtp_safety_baseline"))
    after_view = validate_vtp_safety_baseline(_owner_value(after, "vtp_safety_baseline"))
    changes = _invalid_owner_changes("vtp_safety", before_view, after_view)
    represented: set[Tuple[str, ...]] = set()
    fields = (
        "status", "mode", "mode_present", "domain", "domain_present",
        "version", "version_present", "revision", "revision_present",
    )

    def high_revision(row: Mapping[str, Any]) -> bool:
        return any(
            isinstance(item, dict) and item.get("code") == "high_revision_server"
            for item in row.get("findings", [])
        )

    def evidenced(row: Mapping[str, Any]) -> bool:
        return _text(row.get("status")) == "assessed" or (
            _text(row.get("status")) == "review" and high_revision(row)
        )

    if not changes:
        before_index, after_index = before_view["index"], after_view["index"]
        after_coverage = _coverage_index(after_view["baseline"], ("switch",))
        for host in sorted(set(before_index) | set(after_index), key=lambda value: (value.casefold(), value)):
            represented.add((host,))
            old, new = before_index.get(host), after_index.get(host)
            if old is None:
                changes.append(_change(
                    host, "appeared", "review", {}, _state(new, fields),
                    "A new VTP subject appeared; reset/enablement intent is not inferred.",
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
            elif not evidenced(old) or not evidenced(new):
                changes.append(_change(
                    host, "coverage_lost", "not_verified", _state(old, fields), _state(new, fields),
                    "At least one VTP row is parser/custody review or not verified; no safe movement is asserted.",
                ))
            elif any(old.get(field) != new.get(field) for field in fields[1:]):
                changes.append(_change(
                    host, "intent_changed", "review", _state(old, fields), _state(new, fields),
                    "VTP mode, domain, version, or revision moved; reset/change intent must be reconciled.",
                ))
            elif high_revision(new):
                changes.append(_change(
                    host, "unchanged_degraded", "block", _state(old, fields), _state(new, fields),
                    "The high-revision Server safety blocker remains present; matching it is not acceptance.",
                ))
            else:
                changes.append(_change(
                    host, "unchanged_healthy", "none", _state(old, fields), _state(new, fields),
                    "The validated bounded VTP safety state is unchanged.",
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
            "Mode, domain, version, and revision movement requires review unless reconciled by the cutover intent owner.",
            "VLAN database/digest equality, pruning, authentication, advertisement behavior, and revision-reset safety are not proved.",
        ),
    )


def compute_fhrp_configured_group_delta(before: Any, after: Any) -> dict:
    """Compare the validated literal local configured-group denominator."""
    before_view = validate_fhrp_configured_group_baseline(
        _owner_value(before, "fhrp_configured_group_baseline"))
    after_view = validate_fhrp_configured_group_baseline(
        _owner_value(after, "fhrp_configured_group_baseline"))
    after_coverage = _coverage_index(
        after_view.get("baseline", {}), ("switch", "protocol"))

    def appeared(name: str, row: Mapping[str, Any]) -> dict:
        return _change(name, "appeared", "review", {},
                       _state(row, ("status", "activation", "configured_vip", "runtime_state")),
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


def compute_fhrp_redundancy_domain_delta(before: Any, after: Any) -> dict:
    """Compare validated domains; role movement is non-regressive while redundancy survives."""
    before_view = validate_fhrp_redundancy_domain_baseline(
        _owner_value(before, "fhrp_redundancy_domain_baseline"))
    after_view = validate_fhrp_redundancy_domain_baseline(
        _owner_value(after, "fhrp_redundancy_domain_baseline"))
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
                changes.append(_change(subject, "appeared", "review", {}, new,
                                       "A new observed FHRP redundancy domain requires intended-domain reconciliation."))
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
    "compute_ipv6_routing_adjacency_delta",
    "compute_bgp_configured_peer_delta",
    "compute_stp_consistency_delta",
    "compute_stp_topology_delta",
    "compute_etherchannel_delta",
    "compute_vtp_safety_delta",
    "compute_fhrp_configured_group_delta",
    "compute_fhrp_redundancy_domain_delta",
]
