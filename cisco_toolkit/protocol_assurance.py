"""Source-bound protocol comparison contracts for cutover decisions.

This module is deliberately compositional.  It does not own an overall score or verdict: the
existing :func:`cisco_toolkit.html.compute_cutover_gate` remains the sole owner of the operator's
before/after decision.  The contracts here bind the inputs and expose family-native changes so
API, execution, workbook, and portable surfaces can project one decision without reinterpreting
page-local arrays.

Release 1 starts with the already-shipped IPv4 routing-adjacency delta.  Additional native family
deltas are added to the same reference-only ``protocol_family_change_set/1`` without changing the
legacy ``protocol_adjacency_delta/1`` schema or the seven-family assessability denominator.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional


SUPPORT_PROFILE_SCHEMA = "protocol_support_profile/1"
RECEIPT_ENVELOPE_SCHEMA = "protocol_receipt_envelope/1"
CHANGE_INTENT_SCHEMA = "cutover_change_intent/1"
FAMILY_CHANGE_SET_SCHEMA = "protocol_family_change_set/1"
SUBJECT_BINDING_SCHEMA = "protocol_subject_identity_set/1"
ADMISSION_SCHEMA = "protocol_comparison_admission/1"
CUTOVER_OPERATOR_EVIDENCE_SCHEMA = "cutover_operator_evidence/1"
PERSISTED_SOURCE = "persisted snapshots.snapshot_json blob"

CHANGE_VOCABULARY = (
    "unchanged_healthy",
    "unchanged_degraded",
    "recovered",
    "regressed",
    "appeared",
    "disappeared",
    "intent_changed",
    "coverage_lost",
    "not_comparable",
)

ASSURANCE_LEVELS = (
    "intent_reconciled_survival",
    "observed_state_preservation",
    "local_safety_preservation",
    "not_verified",
)

_IPV4_FAMILY = "ipv4_routing_adjacency"
_IPV4_OWNER = "protocol_adjacency_delta/1"


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical JSON bytes used for non-circular receipt digests.

    Decision inputs loaded by AssessHub have already passed the finite-JSON parser.  The fallback
    keeps direct/library callers total without silently accepting NaN as a canonical JSON number.
    """
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        text = json.dumps(str(value), ensure_ascii=True, separators=(",", ":"))
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        return False
    digest = value[7:]
    return digest == digest.lower() and all(ch in "0123456789abcdef" for ch in digest)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def snapshot_subject_binding(snapshot: Any) -> dict:
    """Bind the exact local device identities without claiming that equal sets are required.

    A cutover can legitimately add or remove a device.  Admission therefore binds each side's
    subject set independently; family owners decide which transitions are comparable.  Empty
    device scope is a coverage loss, while malformed/colliding identities are an identity failure.
    """
    snap = _dict(snapshot)
    devices = snap.get("devices")
    failures: List[str] = []
    subjects: List[str] = []
    if not isinstance(devices, dict):
        failures.append("devices subject map is missing or malformed")
    else:
        folded: Dict[str, str] = {}
        for raw in devices:
            if not isinstance(raw, str) or not raw.strip():
                failures.append("device identity must be a non-empty string")
                continue
            subject = raw.strip()
            key = subject.casefold()
            prior = folded.get(key)
            if prior is not None and prior != subject:
                failures.append(
                    f"case-insensitive device identity collision: {prior!r} and {subject!r}"
                )
                continue
            folded[key] = subject
        subjects = sorted(folded.values(), key=lambda item: (item.casefold(), item))
    payload = {"subjects": subjects}
    return {
        "schema": SUBJECT_BINDING_SCHEMA,
        "identity_kind": "local_snapshot_device",
        "n_subjects": len(subjects),
        "subjects": subjects,
        "subjects_sha256": canonical_sha256(payload),
        "valid": not failures,
        "failures": list(dict.fromkeys(failures)),
    }


def protocol_support_profiles() -> List[dict]:
    """Closed implementation profiles, separate from catalog presence and runtime evidence.

    This is intentionally not a capability-catalog projection.  A profile states which executable
    owner can currently compare evidence; it never says that a particular snapshot contains that
    evidence or that every vendor/VRF/AFI/SAFI variant is supported.
    """
    specs = [
        (
            _IPV4_FAMILY,
            _IPV4_OWNER,
            "observed_state_preservation",
            ["protocol_assessability/1", "routing_neighbors projection"],
            {
                "protocols": ["OSPF", "BGP", "EIGRP"],
                "address_family": "IPv4",
                "subject_basis": "baseline_observed",
            },
            [
                "This profile does not establish an expected-neighbor denominator.",
                "Snapshot source hashes do not independently authenticate the embedded routing-neighbor projection.",
            ],
        ),
        (
            "ipv6_routing_adjacency",
            "ipv6_routing_adjacency_delta/1",
            "observed_state_preservation",
            ["ipv6_routing_adjacency_baseline/1"],
            {
                "protocols": ["OSPFv3", "BGP"],
                "address_family": "IPv6",
                "routing_instance": "default/global",
                "subject_basis": "baseline_observed",
            },
            [
                "Configured peers, VRFs, additional AFI/SAFI, route correctness, and convergence are outside this bounded owner.",
            ],
        ),
        (
            "bgp_configured_peer",
            "bgp_configured_peer_delta/1",
            "intent_reconciled_survival",
            ["bgp_configured_peer_baseline/1"],
            {
                "protocol": "BGP",
                "address_family": "IPv4 unicast",
                "routing_instance": "default/global",
                "peer_kind": "direct_static_literal",
            },
            [
                "Peer groups, templates, dynamic peers, VRFs, other AFI/SAFI, policy, and route correctness remain outside scope.",
            ],
        ),
        (
            "stp_consistency",
            "stp_consistency_delta/1",
            "local_safety_preservation",
            ["stp_consistency_baseline/1", "protocol_assessability/1"],
            {"protocol": "STP", "claim": "bounded local state and inconsistency"},
            [
                "Per-VLAN/PVST/MST topology, root intent, port roles, counters, and convergence are owned separately or remain not verified.",
            ],
        ),
        (
            "stp_topology",
            "stp_topology_delta/1",
            "not_verified",
            ["stp_roots projection", "interfaces STP state projection"],
            {"protocol": "STP", "claim": "observed root and forwarding/blocked path evidence"},
            [
                "Current parsed evidence does not preserve complete per-instance roles or topology-change counters; those leaves are explicitly not verified.",
            ],
        ),
        (
            "etherchannel",
            "etherchannel_delta/1",
            "observed_state_preservation",
            ["etherchannel_baseline/1", "etherchannel_projection/1"],
            {"protocol": "EtherChannel", "subject_basis": "single_chassis_local_group"},
            [
                "This is distinct from multichassis LAG and does not infer a peer pair or dual-homed attachment.",
                "Configured members, remote partner identity, min-links, hashing, counters, and failure rehearsal remain bounded by available evidence.",
            ],
        ),
        (
            "vtp_safety",
            "vtp_safety_delta/1",
            "local_safety_preservation",
            ["vtp_safety_baseline/1"],
            {"protocol": "VTP", "claim": "bounded local configuration/database safety"},
            [
                "Revision or domain movement defaults to review; propagation and reset execution are not inferred.",
            ],
        ),
        (
            "fhrp_configured_group",
            "fhrp_configured_group_delta/1",
            "intent_reconciled_survival",
            ["fhrp_configured_group_baseline/1"],
            {"protocols": ["HSRP", "VRRP", "GLBP"], "subject_basis": "configured_group"},
            [
                "The configured denominator is bounded to the existing owner and does not prove election simultaneity or failover convergence.",
            ],
        ),
        (
            "fhrp_redundancy_domain",
            "fhrp_redundancy_domain_delta/1",
            "observed_state_preservation",
            ["fhrp_redundancy_domain_baseline/1"],
            {"protocols": ["HSRP", "VRRP", "GLBP"], "subject_basis": "observed_redundancy_domain"},
            [
                "Sequential captures do not prove simultaneity, convergence, or intended off-scan member count.",
            ],
        ),
    ]
    profiles = [{
        "schema": SUPPORT_PROFILE_SCHEMA,
        "family": family,
        "owner_schema": owner,
        "implementation_state": "implemented",
        "assurance_level": assurance,
        "evidence_contracts": evidence,
        "runtime_support_claim": "declared_evidence_contract_and_receipt_required",
        "scope": scope,
        "limitations": [
            *limitations,
            "Catalog presence and parser availability are not runtime support evidence.",
        ],
    } for family, owner, assurance, evidence, scope, limitations in specs]

    # Imported lazily to avoid a module-import cycle: the multichassis owner consumes the shared
    # schema/vocabularies above and remains the sole owner of its vendor/mode support matrix.
    from cisco_toolkit.multichassis_lag import multichassis_lag_support_profile

    profiles.append(multichassis_lag_support_profile())
    return profiles


def normalize_change_intent(raw: Any, *, binding: Mapping[str, Any]) -> dict:
    """Return a server-bound expected-change contract; malformed intent is explicit and invalid."""
    failures: List[str] = []
    supplied = raw is not None
    obj = _dict(raw)
    if supplied and not isinstance(raw, dict):
        failures.append("change intent must be an object")
    rows = obj.get("expected_changes", []) if supplied else []
    if not isinstance(rows, list):
        failures.append("expected_changes must be a list")
        rows = []
    expected: List[dict] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            failures.append(f"expected_changes[{index}] must be an object")
            continue
        family = _text(item.get("family"))
        transitions = item.get("transitions", [])
        subjects = item.get("subjects", [])
        reason = _text(item.get("reason"))
        if not family:
            failures.append(f"expected_changes[{index}].family is required")
        if not isinstance(transitions, list) or not transitions:
            failures.append(f"expected_changes[{index}].transitions must be a non-empty list")
            transitions = []
        canonical_transitions: List[str] = []
        for transition in transitions:
            token = _text(transition)
            if token not in CHANGE_VOCABULARY:
                failures.append(
                    f"expected_changes[{index}] has unknown transition {token or transition!r}"
                )
            elif token in {"coverage_lost", "not_comparable"}:
                failures.append(
                    f"expected_changes[{index}] cannot authorize evidence loss or incompatibility"
                )
            elif token not in canonical_transitions:
                canonical_transitions.append(token)
        if not isinstance(subjects, list):
            failures.append(f"expected_changes[{index}].subjects must be a list")
            subjects = []
        canonical_subjects = sorted(
            {_text(value) for value in subjects if _text(value)},
            key=lambda value: (value.casefold(), value),
        )
        expected.append({
            "family": family,
            "transitions": canonical_transitions,
            "subjects": canonical_subjects,
            "reason": reason,
        })
    expected.sort(key=lambda row: (
        row["family"].casefold(), row["family"], tuple(row["transitions"]), tuple(row["subjects"])
    ))
    bound = {
        "engagement_id": binding.get("engagement_id"),
        "campaign_id": binding.get("campaign_id"),
        "before_snapshot_id": binding.get("before_snapshot_id"),
        "after_snapshot_id": binding.get("after_snapshot_id"),
        "before_sha256": binding.get("before_sha256"),
        "after_sha256": binding.get("after_sha256"),
    }
    return {
        "schema": CHANGE_INTENT_SCHEMA,
        "status": "invalid" if failures else ("reconciled" if supplied else "not_supplied"),
        "valid": not failures,
        "note": _text(obj.get("note")) if supplied else "No expected-change intent was supplied.",
        "binding": bound,
        "expected_changes": expected,
        "expected_changes_sha256": canonical_sha256(expected),
        "failures": list(dict.fromkeys(failures)),
    }


def comparison_admission(
        before: Any,
        after: Any,
        *,
        before_binding: Mapping[str, Any],
        after_binding: Mapping[str, Any],
        schema_status: Mapping[str, Any],
        change_intent: Mapping[str, Any],
        owner_versions: Mapping[str, Any],
        support_profiles: Iterable[Mapping[str, Any]]) -> dict:
    """Bind comparison semantics and classify admission without computing an overall verdict."""
    before_subjects = snapshot_subject_binding(before)
    after_subjects = snapshot_subject_binding(after)
    failures: List[str] = []
    gaps: List[str] = []

    snapshots = {"before": _dict(before), "after": _dict(after)}
    for side, binding in (("before", before_binding), ("after", after_binding)):
        if binding.get("source") != PERSISTED_SOURCE:
            failures.append(f"{side} source owner is missing or unsupported")
        if not _is_sha256(binding.get("sha256")):
            failures.append(f"{side} persisted-source SHA-256 binding is missing or malformed")
        byte_count = binding.get("bytes")
        if (not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0):
            failures.append(f"{side} persisted-source byte count is missing or malformed")
        if not isinstance(binding.get("snapshot_id"), int):
            failures.append(f"{side} snapshot identity is missing or malformed")
        if not isinstance(binding.get("campaign_id"), int):
            failures.append(f"{side} campaign identity is missing or malformed")
        if not _text(binding.get("engagement_id")):
            failures.append(f"{side} engagement identity is missing or malformed")
        bound_owner = _text(binding.get("script_version"))
        snapshot_owner = _text(snapshots[side].get("script_version"))
        if not bound_owner or not snapshot_owner or bound_owner != snapshot_owner:
            failures.append(
                f"{side} stored owner version does not match the parsed snapshot owner"
            )

    if before_binding.get("snapshot_id") == after_binding.get("snapshot_id"):
        failures.append("before and after snapshot identities must be distinct")
    if before_binding.get("campaign_id") != after_binding.get("campaign_id"):
        failures.append("before and after snapshots belong to different campaigns")
    if before_binding.get("engagement_id") != after_binding.get("engagement_id"):
        failures.append("before and after snapshots belong to different engagements")

    schema_token = _text(schema_status.get("status")).lower()
    if schema_token == "mismatch":
        failures.append("snapshot owner semantics are incompatible")
    elif schema_token != "ok":
        gaps.append("snapshot owner semantics could not be verified")

    for side, subjects in (("before", before_subjects), ("after", after_subjects)):
        if not subjects["valid"]:
            failures.extend(f"{side}: {item}" for item in subjects["failures"])
        elif subjects["n_subjects"] == 0:
            gaps.append(f"{side} snapshot has no bound device subjects")

    if change_intent.get("valid") is not True:
        failures.extend(
            f"change intent: {item}" for item in _list(change_intent.get("failures"))
        )
    intent_binding = _dict(change_intent.get("binding"))
    expected_intent_binding = {
        "engagement_id": before_binding.get("engagement_id"),
        "campaign_id": before_binding.get("campaign_id"),
        "before_snapshot_id": before_binding.get("snapshot_id"),
        "after_snapshot_id": after_binding.get("snapshot_id"),
        "before_sha256": before_binding.get("sha256"),
        "after_sha256": after_binding.get("sha256"),
    }
    if intent_binding != expected_intent_binding:
        failures.append("change intent is not bound to this exact comparison pair")

    profiles = [dict(profile) for profile in support_profiles if isinstance(profile, Mapping)]
    profile_families = [_text(profile.get("family")) for profile in profiles]
    if (not profiles
            or len(set(profile_families)) != len(profile_families)
            or any(
                profile.get("schema") != SUPPORT_PROFILE_SCHEMA
                or not _text(profile.get("family"))
                or not _text(profile.get("owner_schema"))
                or profile.get("assurance_level") not in ASSURANCE_LEVELS
                or profile.get("implementation_state") != "implemented"
                or not isinstance(profile.get("evidence_contracts"), list)
                or not profile.get("evidence_contracts")
                or any(not _text(item) for item in profile.get("evidence_contracts", []))
                or not isinstance(profile.get("scope"), dict)
                or not profile.get("scope")
                or not _text(profile.get("runtime_support_claim"))
                or not isinstance(profile.get("limitations"), list)
                or not profile.get("limitations")
                or any(not _text(item) for item in profile.get("limitations", []))
                for profile in profiles
            )):
        failures.append("protocol support profiles are missing or malformed")
    if (not owner_versions
            or any(not _text(key) or not _text(value)
                   for key, value in owner_versions.items())):
        failures.append("decision owner versions are missing")

    status = "not_comparable" if failures else ("coverage_lost" if gaps else "admitted")
    assurance = "not_verified" if status != "admitted" else "observed_state_preservation"
    return {
        "schema": ADMISSION_SCHEMA,
        "status": status,
        "decision_eligible": status == "admitted",
        "assurance_level": assurance,
        "engagement_id": before_binding.get("engagement_id"),
        "campaign_id": before_binding.get("campaign_id"),
        "source_binding": {
            "before": dict(before_binding),
            "after": dict(after_binding),
        },
        "subject_binding": {
            "before": before_subjects,
            "after": after_subjects,
        },
        "owner_versions": dict(owner_versions),
        "support_profiles": profiles,
        "failures": list(dict.fromkeys(failures)),
        "coverage_gaps": list(dict.fromkeys(gaps)),
    }


def _assessability_declares(snapshot: Mapping[str, Any], protocol: str) -> bool:
    receipt = snapshot.get("protocol_assessability")
    families = receipt.get("families") if isinstance(receipt, dict) else None
    wanted = protocol.casefold()
    return isinstance(families, list) and any(
        isinstance(row, dict)
        and _text(row.get("protocol")).casefold() == wanted
        for row in families
    )


def _declares_any(snapshot: Mapping[str, Any], keys: Iterable[str]) -> bool:
    return any(key in snapshot for key in keys)


def _normalized_source_binding(value: Any, snapshot: Mapping[str, Any]) -> dict:
    if isinstance(value, str):
        raw = {"sha256": value}
    else:
        raw = _dict(value)
    return {
        **raw,
        "sha256": raw.get("sha256"),
        "script_version": _text(raw.get("script_version")) or _text(snapshot.get("script_version")),
    }


def _legacy_multichassis_input(snapshot: Mapping[str, Any], binding: Mapping[str, Any]) -> dict:
    """Adapt existing parser output as local observation only, never pair/attachment proof."""
    from cisco_toolkit import multichassis_lag

    explicit = snapshot.get("multichassis_lag_typed_observations")
    if isinstance(explicit, dict):
        return explicit
    source_sha = binding.get("sha256")
    owner_version = _text(binding.get("script_version")) or "unknown"

    def receipt(command: str) -> dict:
        return {
            "schema": multichassis_lag.MULTICHASSIS_LAG_SOURCE_RECEIPT_SCHEMA,
            "capture_status": "ok",
            "projection_custody": "embedded_unverified",
            "source_sha256": source_sha,
            "owner_version": owner_version,
            "commands": [command],
        }

    observations: List[dict] = []
    vpc = snapshot.get("vpc")
    if isinstance(vpc, dict):
        for switch, raw in sorted(vpc.items(), key=lambda item: str(item[0]).casefold()):
            if not isinstance(switch, str) or not switch.strip() or not isinstance(raw, dict) or not raw:
                continue
            peer_link = _dict(raw.get("peer_link"))
            legs = []
            for leg in _list(raw.get("vpcs")):
                if not isinstance(leg, dict):
                    continue
                legs.append({
                    "attachment_id": leg.get("id"),
                    "local_port_channel": leg.get("port"),
                    "status": leg.get("status"),
                    "consistency": leg.get("consistency"),
                    "lacp_partner_system_id": "",
                    "lacp_partner_aggregation_id": "",
                })
            observations.append({
                "switch": switch,
                "vendor": "cisco",
                "platform": "nxos",
                "collection_mode": "offline",
                "peer_identity": "",  # Domain ID and role cannot supply this identity.
                "domain_id": raw.get("domain_id"),
                "domain_state": {
                    "peer_status": raw.get("peer_status"),
                    "keepalive_status": raw.get("keepalive_status"),
                    "consistency": raw.get("consistency"),
                    "peer_link_status": peer_link.get("status"),
                },
                "source": receipt("show vpc"),
                "legs": legs,
            })
    arista = snapshot.get("arista")
    if isinstance(arista, dict):
        for switch, raw in sorted(arista.items(), key=lambda item: str(item[0]).casefold()):
            if not isinstance(switch, str) or not switch.strip() or not isinstance(raw, dict):
                continue
            mlag = raw.get("mlag") if isinstance(raw.get("mlag"), dict) else raw
            if not isinstance(mlag, dict) or not mlag:
                continue
            observations.append({
                "switch": switch,
                "vendor": "arista",
                "platform": "eos",
                "collection_mode": "offline",
                "peer_identity": "",  # peer_address is not a reciprocal switch identity.
                "domain_id": mlag.get("domain_id"),
                "domain_state": {
                    "state": mlag.get("state"),
                    "neg_status": mlag.get("neg_status"),
                    "config_sanity": mlag.get("config_sanity"),
                    "peer_link_status": mlag.get("peer_link_status"),
                    "local_intf_status": mlag.get("local_intf_status"),
                },
                "source": receipt("show mlag detail | json"),
                "legs": [],
            })
    return {"observations": observations}


def compute_native_protocol_deltas(
        before: Any,
        after: Any,
        *,
        before_binding: Any = None,
        after_binding: Any = None) -> List[dict]:
    """Compute applicable native owners from one pair without turning support into evidence.

    Applicability is the union of declared evidence on both sides, so loss on the after side remains
    visible.  A family absent on both sides is not injected merely because its executable profile or
    catalog entry exists.  Legacy vPC/EOS parser projections contribute local observations only.
    """
    from cisco_toolkit import multichassis_lag, protocol_deltas

    old, new = _dict(before), _dict(after)
    before_source = _normalized_source_binding(before_binding, old)
    after_source = _normalized_source_binding(after_binding, new)
    specs = (
        (protocol_deltas.compute_ipv6_routing_adjacency_delta,
         ("ipv6_routing_adjacency_baseline",), None),
        (protocol_deltas.compute_bgp_configured_peer_delta,
         ("bgp_configured_peer_baseline",), None),
        (protocol_deltas.compute_stp_consistency_delta,
         ("stp_consistency_baseline",), "STP"),
        (protocol_deltas.compute_stp_topology_delta,
         ("stp_roots",), "STP"),
        (protocol_deltas.compute_etherchannel_delta,
         ("etherchannel_baseline", "etherchannel_projection"), "EtherChannel"),
        (protocol_deltas.compute_vtp_safety_delta,
         ("vtp_safety_baseline",), "VTP"),
        (protocol_deltas.compute_fhrp_configured_group_delta,
         ("fhrp_configured_group_baseline",), "FHRP"),
        (protocol_deltas.compute_fhrp_redundancy_domain_delta,
         ("fhrp_redundancy_domain_baseline",), None),
    )
    results: List[dict] = []
    for computer, keys, assessability_family in specs:
        applicable = _declares_any(old, keys) or _declares_any(new, keys)
        if assessability_family:
            applicable = applicable or _assessability_declares(
                old, assessability_family) or _assessability_declares(new, assessability_family)
        if applicable:
            results.append(computer(old, new))

    multichassis_keys = (
        "multichassis_lag_typed_observations", "multichassis_lag_domain_baseline",
    )
    multichassis_applicable = (
        _declares_any(old, multichassis_keys) or _declares_any(new, multichassis_keys)
        or bool(old.get("vpc")) or bool(old.get("arista"))
        or bool(new.get("vpc")) or bool(new.get("arista"))
    )
    if multichassis_applicable:
        def baseline(snapshot: Mapping[str, Any], binding: Mapping[str, Any]) -> dict:
            stored = snapshot.get("multichassis_lag_domain_baseline")
            if stored is not None:
                return stored
            return multichassis_lag.compute_multichassis_lag_domain_baseline(
                _legacy_multichassis_input(snapshot, binding))

        before_baseline = baseline(old, before_source)
        after_baseline = baseline(new, after_source)
        before_summary = _dict(_dict(before_baseline).get("summary"))
        after_summary = _dict(_dict(after_baseline).get("summary"))
        results.append(multichassis_lag.compute_multichassis_lag_delta(
            before_baseline,
            after_baseline,
            source_binding={
                "custody": "persisted_snapshot_bytes_bound",
                "before_snapshot_sha256": before_source.get("sha256"),
                "after_snapshot_sha256": after_source.get("sha256"),
                "before_baseline_sha256": before_summary.get("baseline_sha256"),
                "after_baseline_sha256": after_summary.get("baseline_sha256"),
            },
        ))
    return results


def _expected(intent: Mapping[str, Any], family: str, transition: str, subject: str) -> bool:
    if transition in {"coverage_lost", "not_comparable"}:
        return False
    for row in _list(intent.get("expected_changes")):
        if not isinstance(row, dict) or row.get("family") != family:
            continue
        if transition not in _list(row.get("transitions")):
            continue
        subjects = _list(row.get("subjects"))
        if not subjects or subject in subjects:
            return True
    return False


_DECISION_EFFECTS = ("block", "review", "none", "not_verified")
_UNEXPECTED_TRANSITIONS = {
    "unchanged_degraded", "regressed", "appeared", "disappeared", "intent_changed",
}


def _row_effect(transition: str, expected: bool, producer_effect: Optional[str] = None) -> str:
    """Reconcile intent without weakening a native owner's safety classification."""
    if producer_effect in _DECISION_EFFECTS:
        return "none" if expected and producer_effect == "review" else producer_effect
    if transition in {"regressed", "unchanged_degraded"}:
        return "block"
    if transition in {"coverage_lost", "not_comparable"}:
        return "not_verified"
    if transition in {"appeared", "disappeared", "intent_changed"}:
        return "none" if expected else "review"
    return "none"


def _family_summary(rows: List[dict], *, implicit_unchanged_healthy: int = 0) -> dict:
    counts = {token: 0 for token in CHANGE_VOCABULARY}
    effects = {token: 0 for token in _DECISION_EFFECTS}
    for row in rows:
        counts[row["transition"]] += 1
        effects[row["decision_effect"]] += 1
    counts["unchanged_healthy"] += implicit_unchanged_healthy
    return {
        "n_subject_changes": len(rows),
        "n_implicit_unchanged_healthy": implicit_unchanged_healthy,
        "n_expected": sum(row["expected"] for row in rows),
        "n_unexpected": sum(
            not row["expected"] and row["transition"] in _UNEXPECTED_TRANSITIONS
            for row in rows
        ),
        "n_coverage_lost": counts["coverage_lost"],
        "n_blocking": effects["block"],
        "n_review": effects["review"],
        "n_not_verified": effects["not_verified"],
        "by_transition": counts,
        "by_decision_effect": effects,
    }


def _not_comparable_row(family: str, note: str) -> dict:
    return {
        "family": family,
        "subject": f"{family}|owner_receipt",
        "transition": "not_comparable",
        "expected": False,
        "decision_effect": "not_verified",
        "before_state": {},
        "after_state": {},
        "note": note,
    }


def _ipv4_family(delta: Any, change_intent: Mapping[str, Any], profile: Mapping[str, Any]) -> dict:
    value = _dict(delta)
    summary = value.get("summary")
    changes = value.get("changes")
    gaps = value.get("coverage_gaps")
    failures: List[str] = []
    if value.get("schema") != _IPV4_OWNER:
        failures.append("IPv4 adjacency delta schema is missing or unsupported")
    if not isinstance(summary, dict):
        failures.append("IPv4 adjacency summary is missing or malformed")
        summary = {}
    preserved = summary.get("n_preserved")
    if not isinstance(preserved, int) or isinstance(preserved, bool) or preserved < 0:
        failures.append("IPv4 adjacency preserved count is missing or malformed")
        preserved = 0
    if not isinstance(changes, list):
        failures.append("IPv4 adjacency changes are missing or malformed")
        changes = []
    if not isinstance(gaps, list):
        failures.append("IPv4 adjacency coverage gaps are missing or malformed")
        gaps = []

    transition_map = {
        "state_degraded": "regressed",
        "recovered": "recovered",
        "added": "appeared",
        "no_longer_observed": "disappeared",
        "metadata_changed": "intent_changed",
        "state_changed": "intent_changed",
    }
    rows: List[dict] = []
    for index, raw in enumerate(changes):
        if not isinstance(raw, dict):
            failures.append(f"IPv4 adjacency changes[{index}] is malformed")
            continue
        result = _text(raw.get("result"))
        switch, protocol, peer = (
            _text(raw.get("switch")), _text(raw.get("protocol")), _text(raw.get("peer"))
        )
        if result not in transition_map or not switch or not protocol or not peer:
            failures.append(f"IPv4 adjacency changes[{index}] is missing a required identity/result")
            continue
        transition = transition_map[result]
        subject = "|".join((switch, protocol, peer))
        expected = _expected(change_intent, _IPV4_FAMILY, transition, subject)
        rows.append({
            "family": _IPV4_FAMILY,
            "subject": subject,
            "transition": transition,
            "expected": expected,
            "decision_effect": _row_effect(transition, expected),
            "before_state": _text(raw.get("before_state")),
            "after_state": _text(raw.get("after_state")),
            "note": _text(raw.get("note")) or "IPv4 adjacency transition reported by its v1 owner.",
        })
    for index, raw in enumerate(gaps):
        if not isinstance(raw, dict):
            failures.append(f"IPv4 adjacency coverage_gaps[{index}] is malformed")
            continue
        switch, protocol = _text(raw.get("switch")), _text(raw.get("protocol"))
        if not switch or not protocol:
            failures.append(f"IPv4 adjacency coverage_gaps[{index}] lacks a subject identity")
            continue
        subject = "|".join((switch, protocol, "*"))
        rows.append({
            "family": _IPV4_FAMILY,
            "subject": subject,
            "transition": "coverage_lost",
            "expected": False,
            "decision_effect": "not_verified",
            "before_state": _text(raw.get("before_state")),
            "after_state": _text(raw.get("after_state")),
            "note": _text(raw.get("reason")) or "IPv4 adjacency coverage was lost.",
        })
    if failures:
        rows = [_not_comparable_row(_IPV4_FAMILY, "; ".join(dict.fromkeys(failures)))]
        preserved = 0
    rows.sort(key=lambda row: (
        row["family"], row["subject"].casefold(), row["subject"], row["transition"]
    ))
    return {
        "family": _IPV4_FAMILY,
        "owner_schema": _IPV4_OWNER,
        "assurance_level": "not_verified" if failures else "observed_state_preservation",
        "support_profile": dict(profile),
        "summary": _family_summary(rows, implicit_unchanged_healthy=preserved),
        "changes": rows,
        "source_receipt": value,
        "composition_failures": failures,
    }


def _native_family(delta: Any, change_intent: Mapping[str, Any],
                   profiles: Mapping[str, Mapping[str, Any]], index: int) -> dict:
    value = _dict(delta)
    family = _text(value.get("family"))
    schema = _text(value.get("schema"))
    failures: List[str] = []
    profile = profiles.get(family)
    if profile is None:
        failures.append("native family is missing or not in the closed executable support set")
        family = family or f"unknown_native_{index}"
        profile = {
            "schema": SUPPORT_PROFILE_SCHEMA,
            "family": family,
            "owner_schema": schema or "not_verified",
            "implementation_state": "implemented",
            "assurance_level": "not_verified",
            "evidence_contracts": [],
            "runtime_support_claim": "not_verified",
            "scope": {},
            "limitations": ["The supplied native family is not a recognized executable owner."],
        }
    if schema != profile.get("owner_schema"):
        failures.append("native delta schema does not match its support profile owner")
    if value.get("owns_score") is not False or value.get("owns_verdict") is not False:
        failures.append("native delta must own neither score nor verdict")
    assurance = value.get("assurance_level")
    if assurance not in ASSURANCE_LEVELS:
        failures.append("native delta assurance level is missing or unsupported")
        assurance = "not_verified"
    raw_rows = value.get("changes")
    if not isinstance(raw_rows, list):
        failures.append("native delta changes are missing or malformed")
        raw_rows = []
    raw_summary = value.get("summary")
    by_transition = raw_summary.get("by_transition") if isinstance(raw_summary, dict) else None
    if (not isinstance(by_transition, dict)
            or tuple(by_transition) != CHANGE_VOCABULARY
            or any(
                not isinstance(by_transition.get(token), int)
                or isinstance(by_transition.get(token), bool)
                or by_transition.get(token) < 0
                for token in CHANGE_VOCABULARY
            )):
        failures.append("native delta transition summary is missing or malformed")
        by_transition = {token: 0 for token in CHANGE_VOCABULARY}
    if _list(value.get("comparison_failures")):
        failures.extend(
            f"native comparison: {_text(item) or 'unspecified failure'}"
            for item in value["comparison_failures"]
        )

    rows: List[dict] = []
    observed_counts = {token: 0 for token in CHANGE_VOCABULARY}
    for row_index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            failures.append(f"native changes[{row_index}] is malformed")
            continue
        transition = raw.get("transition")
        producer_effect = raw.get("decision_effect")
        subject = _text(raw.get("subject"))
        if (raw.get("family") != family or transition not in CHANGE_VOCABULARY
                or producer_effect not in _DECISION_EFFECTS or not subject
                or not _text(raw.get("note"))):
            failures.append(f"native changes[{row_index}] is missing a required semantic leaf")
            continue
        expected = _expected(change_intent, family, transition, subject)
        rows.append({
            "family": family,
            "subject": subject,
            "transition": transition,
            "expected": expected,
            "decision_effect": _row_effect(transition, expected, producer_effect),
            "before_state": raw.get("before_state", {}),
            "after_state": raw.get("after_state", {}),
            "note": raw["note"],
        })
        observed_counts[transition] += 1
    if by_transition != observed_counts:
        failures.append("native delta transition summary does not reconcile to its complete rows")
    if failures:
        rows = [_not_comparable_row(family, "; ".join(dict.fromkeys(failures)))]
        assurance = "not_verified"
    rows.sort(key=lambda row: (
        row["family"], row["subject"].casefold(), row["subject"], row["transition"]
    ))
    return {
        "family": family,
        "owner_schema": profile.get("owner_schema"),
        "assurance_level": assurance,
        "support_profile": dict(profile),
        "summary": _family_summary(rows),
        "changes": rows,
        "source_receipt": value,
        "composition_failures": failures,
    }


def protocol_family_change_set(
        ipv4_delta: Any,
        change_intent: Mapping[str, Any],
        native_deltas: Optional[Iterable[Any]] = None) -> dict:
    """Compose complete family-native deltas without owning the cutover verdict.

    The unchanged ``protocol_adjacency_delta/1`` remains the IPv4 owner.  Native owners retain
    transition semantics and producer effects; expected intent can clear only a producer ``review``
    effect, never a block or abstention.  Missing/malformed native receipts are materialized as an
    uncapped ``not_comparable`` subject so a presentation cap cannot hide the withheld assurance.
    """
    profile_list = protocol_support_profiles()
    profiles = {profile["family"]: profile for profile in profile_list}
    families = [_ipv4_family(ipv4_delta, change_intent, profiles[_IPV4_FAMILY])]
    for index, delta in enumerate(native_deltas or []):
        families.append(_native_family(delta, change_intent, profiles, index))
    families.sort(key=lambda family: (family["family"].casefold(), family["family"]))

    summary = {
        "n_families": len(families),
        "n_subject_changes": sum(family["summary"]["n_subject_changes"] for family in families),
        "n_expected": sum(family["summary"]["n_expected"] for family in families),
        "n_unexpected": sum(family["summary"]["n_unexpected"] for family in families),
        "n_coverage_lost": sum(family["summary"]["n_coverage_lost"] for family in families),
        "n_blocking": sum(family["summary"]["n_blocking"] for family in families),
        "n_review": sum(family["summary"]["n_review"] for family in families),
        "n_not_verified": sum(family["summary"]["n_not_verified"] for family in families),
        "by_transition": {
            token: sum(family["summary"]["by_transition"][token] for family in families)
            for token in CHANGE_VOCABULARY
        },
        "by_decision_effect": {
            token: sum(family["summary"]["by_decision_effect"][token] for family in families)
            for token in _DECISION_EFFECTS
        },
    }
    return {
        "schema": FAMILY_CHANGE_SET_SCHEMA,
        "owner": "reference_only_composition",
        "owns_score": False,
        "owns_verdict": False,
        "summary": summary,
        "families": families,
    }


def cutover_operator_evidence(snapshot: Any) -> dict:
    """Project existing simulation and rollback owners without inventing rehearsal success.

    ``failure_impact`` is an existing bounded simulation projection, not proof that an operator
    rehearsed a failure.  ``migration_scenarios`` owns rollback planning prose, not execution.
    Keeping those distinctions explicit lets decision surfaces put the evidence in the right order
    while withholding a stronger field claim than the stored snapshot supports.
    """
    snap = _dict(snapshot)
    raw_impacts = snap.get("failure_impact")
    impacts = [dict(row) for row in raw_impacts
               if isinstance(row, dict)] if isinstance(raw_impacts, list) else []
    rehearsal = {
        "status": "simulation_only" if impacts else "not_verified",
        "assurance_level": "not_verified",
        "source_owner": "failure_impact projection",
        "n_impacts_total": len(impacts),
        "impacts": impacts,
        "note": (
            "Existing failure-impact simulation is retained as planning evidence; no source-bound "
            "operator rehearsal receipt is present, so rehearsal remains not verified."
            if impacts else
            "No source-bound failure simulation or operator rehearsal receipt is present."
        ),
    }

    scenarios = _dict(snap.get("migration_scenarios"))
    raw_groups = scenarios.get("per_group")
    groups = raw_groups if isinstance(raw_groups, list) else []
    plans: List[dict] = []
    for raw in groups:
        row = _dict(raw)
        playbook = _dict(row.get("playbook"))
        rollback = _text(playbook.get("rollback"))
        if not rollback:
            continue
        plans.append({
            "group": _text(row.get("group")),
            "recommended_scenario": _text(row.get("recommended_scenario")),
            "rollback": rollback,
        })
    rollback_status = (
        "planned" if groups and len(plans) == len(groups)
        else "coverage_lost" if groups or plans
        else "not_verified"
    )
    rollback = {
        "status": rollback_status,
        "assurance_level": "not_verified",
        "source_owner": "migration_scenarios playbook.rollback",
        "n_groups_total": len(groups),
        "n_plans_total": len(plans),
        "plans": plans,
        "note": (
            "Every stored migration group carries a rollback plan. Plan presence is not proof that "
            "the rollback was rehearsed or executed."
            if rollback_status == "planned" else
            "Rollback planning coverage is incomplete or unavailable; do not infer a usable back-out path."
        ),
    }
    return {
        "schema": CUTOVER_OPERATOR_EVIDENCE_SCHEMA,
        "owner": "reference_only_projection",
        "owns_verdict": False,
        "rehearsal": rehearsal,
        "rollback": rollback,
    }


def receipt_envelope(
        *,
        admission: Mapping[str, Any],
        change_intent: Mapping[str, Any],
        protocol_families: Mapping[str, Any],
        delta: Mapping[str, Any],
        precert: Mapping[str, Any],
        cutover_gate: Mapping[str, Any],
        operator_evidence: Optional[Mapping[str, Any]] = None) -> dict:
    """Bind the complete uncapped comparison payload without circular self-hashing."""
    payload = {
        "admission": dict(admission),
        "change_intent": dict(change_intent),
        "protocol_families": dict(protocol_families),
        "delta": dict(delta),
        "precert": dict(precert),
        "cutover_gate": dict(cutover_gate),
    }
    if operator_evidence is not None:
        payload["operator_evidence"] = dict(operator_evidence)
    envelope = {
        "schema": RECEIPT_ENVELOPE_SCHEMA,
        "admission": dict(admission),
        "source_binding": dict(_dict(admission.get("source_binding"))),
        "subject_binding": dict(_dict(admission.get("subject_binding"))),
        "owner_versions": dict(_dict(admission.get("owner_versions"))),
        "support_profiles": list(_list(admission.get("support_profiles"))),
        "payload_sha256": canonical_sha256(payload),
    }
    envelope["receipt_sha256"] = canonical_sha256(envelope)
    return envelope


def verify_receipt_envelope(envelope: Any, payload: Mapping[str, Any]) -> bool:
    """Verify a detached envelope against the exact payload it claims to bind."""
    env = _dict(envelope)
    if env.get("schema") != RECEIPT_ENVELOPE_SCHEMA:
        return False
    claimed = env.get("receipt_sha256")
    unsigned = dict(env)
    unsigned.pop("receipt_sha256", None)
    return (
        _is_sha256(claimed)
        and claimed == canonical_sha256(unsigned)
        and env.get("payload_sha256") == canonical_sha256(dict(payload))
    )
