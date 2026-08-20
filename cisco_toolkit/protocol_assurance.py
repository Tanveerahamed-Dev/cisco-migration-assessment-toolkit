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
OFFLINE_FILE_SOURCE = "exact input snapshot file bytes"
_COMPARISON_SOURCE_OWNERS = (PERSISTED_SOURCE, OFFLINE_FILE_SOURCE)

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


_BOUND_SNAPSHOT_AUTHORITY = object()
_BOUND_FAMILY_SET_AUTHORITY = object()
_MAX_JSON_OBJECT_MEMBERS = 2_000_000


class BoundSnapshot(dict):
    """Process-local proof that one mapping was parsed from one exact JSON byte string.

    The marker is intentionally not serialized: ``dict(bound)`` and JSON output retain only the
    assessment payload.  A stored ``projection_custody`` string or a caller-provided digest can
    therefore never recreate this authority after a round trip.  Only
    :func:`bind_snapshot_json_bytes`, which parses and hashes the same bytes, can mint an instance.
    """

    __slots__ = (
        "_bound_source_sha256",
        "_bound_source_bytes",
        "_bound_payload_sha256",
    )

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            source_sha256: str,
            source_bytes: int,
            payload_sha256: str,
            _authority: object) -> None:
        if _authority is not _BOUND_SNAPSHOT_AUTHORITY:
            raise TypeError("BoundSnapshot can only be minted from exact JSON bytes")
        super().__init__(value)
        self._bound_source_sha256 = source_sha256
        self._bound_source_bytes = source_bytes
        self._bound_payload_sha256 = payload_sha256


class BoundProtocolFamilyChangeSet(dict):
    """Process-local authority over one complete, mutation-sensitive family composition.

    ``protocol_family_change_set/1`` is intentionally serializable as ordinary JSON for operator
    receipts, but detached JSON is evidence to render, not authority to make a fresh decision.  A
    caller that deletes an applicable family, rewrites producer custody, or rebuilds the unkeyed
    outer receipt must not be able to feed that edited mapping back into ``cutover_gate/1``.  The
    private canonical digest is minted only by the family composer and is deliberately absent from
    the wire contract; JSON round trips therefore lose decision authority.
    """

    __slots__ = ("_bound_payload_sha256",)

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            payload_sha256: str,
            _authority: object) -> None:
        if _authority is not _BOUND_FAMILY_SET_AUTHORITY:
            raise TypeError(
                "BoundProtocolFamilyChangeSet can only be minted by the canonical composer"
            )
        super().__init__(value)
        self._bound_payload_sha256 = payload_sha256


def validate_protocol_family_change_set_authority(value: Any) -> dict:
    """Validate the non-serializable authority and exact current bytes of a family set.

    Structural and row-level reconciliation remains in the sole gate owner.  This check closes the
    trust-boundary gap that structural validation alone cannot close: an internally coherent but
    detached subset has no proof that it is the complete family set produced for the source pair.
    """
    present = value is not None
    if not isinstance(value, BoundProtocolFamilyChangeSet):
        return {
            "present": present,
            "valid": False,
            "reason": (
                "protocol family change set is detached from the canonical in-process composer"
            ),
        }
    expected = getattr(value, "_bound_payload_sha256", None)
    try:
        actual = canonical_sha256(dict(value))
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError):
        actual = None
    if not isinstance(expected, str) or expected != actual:
        return {
            "present": True,
            "valid": False,
            "reason": "protocol family change set changed after canonical composition",
        }
    return {"present": True, "valid": True, "reason": "ok"}


def reject_duplicate_json_keys(pairs: List[tuple[str, Any]]) -> Dict[str, Any]:
    """Build one JSON object while refusing ambiguous duplicate member names."""
    if len(pairs) > _MAX_JSON_OBJECT_MEMBERS:
        raise ValueError("JSON object exceeds the structural member limit")
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            shown = key if len(key) <= 120 else key[:117] + "..."
            raise ValueError(f"duplicate JSON object key {shown!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(token: str) -> None:
    raise ValueError(f"non-finite JSON number: {token}")


def bind_snapshot_json_bytes(raw: Any) -> BoundSnapshot:
    """Parse finite JSON and bind the resulting snapshot to those exact bytes.

    Decoding and hashing share the byte object.  Callers that own database/file bytes use this
    instead of parsing first and then trusting a digest leaf supplied alongside a detached dict.
    """
    if isinstance(raw, memoryview):
        payload = raw.tobytes()
    elif isinstance(raw, bytearray):
        payload = bytes(raw)
    elif isinstance(raw, bytes):
        payload = raw
    else:
        raise TypeError("snapshot source must be bytes")
    value = json.loads(
        payload.decode("utf-8"),
        parse_constant=_reject_nonfinite_json,
        object_pairs_hook=reject_duplicate_json_keys,
    )
    if not isinstance(value, dict):
        raise ValueError("snapshot JSON root must be an object")
    return BoundSnapshot(
        value,
        source_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        source_bytes=len(payload),
        payload_sha256=canonical_sha256(value),
        _authority=_BOUND_SNAPSHOT_AUTHORITY,
    )


def bound_snapshot_source(value: Any) -> dict:
    """Return the non-serializable exact-byte marker as a normalized read-only receipt."""
    if (
        not isinstance(value, BoundSnapshot)
        or canonical_sha256(dict(value)) != value._bound_payload_sha256
    ):
        return {"source_bound": False, "sha256": "", "bytes": 0}
    return {
        "source_bound": True,
        "sha256": value._bound_source_sha256,
        "bytes": value._bound_source_bytes,
    }


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


def canonical_decision_owner_versions(
        *, before_snapshot_owner: Any, after_snapshot_owner: Any) -> dict:
    """Return the exact Release-1 decision-owner roster admitted by the canonical gate.

    The roster is derived from the executable support profiles, never the capability catalog.  Keeping
    this constructor beside the admission validator prevents a caller from substituting a plausible but
    incomplete set of owner strings while still labelling the receipt ``admitted``.
    """
    from cisco_toolkit import __version__ as engine_schema

    profiles = protocol_support_profiles()
    owners = {
        "snapshot_delta": "compute_snapshot_delta@v1",
        "precert": "precert/1",
        "cutover_gate": "cutover_gate/1",
        "protocol_family_change_set": FAMILY_CHANGE_SET_SCHEMA,
        "engine_schema": engine_schema,
        "before_snapshot_owner": _text(before_snapshot_owner),
        "after_snapshot_owner": _text(after_snapshot_owner),
    }
    owners.update({
        f"protocol:{profile['family']}": str(profile["owner_schema"])
        for profile in profiles
    })
    return owners


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

    snapshots = {"before": before, "after": after}
    for side, binding in (("before", before_binding), ("after", after_binding)):
        if binding.get("source") not in _COMPARISON_SOURCE_OWNERS:
            failures.append(f"{side} source owner is missing or unsupported")
        if not _is_sha256(binding.get("sha256")):
            failures.append(f"{side} exact-source SHA-256 binding is missing or malformed")
        byte_count = binding.get("bytes")
        if (not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0):
            failures.append(f"{side} exact-source byte count is missing or malformed")
        if not isinstance(binding.get("snapshot_id"), int):
            failures.append(f"{side} snapshot identity is missing or malformed")
        if not isinstance(binding.get("campaign_id"), int):
            failures.append(f"{side} campaign identity is missing or malformed")
        if not _text(binding.get("engagement_id")):
            failures.append(f"{side} engagement identity is missing or malformed")
        source_marker = bound_snapshot_source(snapshots[side])
        if source_marker.get("source_bound") is not True:
            failures.append(
                f"{side} parsed snapshot is detached, mutated, or not bound to exact source bytes"
            )
        elif (source_marker.get("sha256") != binding.get("sha256")
              or source_marker.get("bytes") != binding.get("bytes")):
            failures.append(
                f"{side} parsed snapshot byte marker does not match its source binding"
            )
        bound_owner = _text(binding.get("script_version"))
        snapshot_owner = _text(_dict(snapshots[side]).get("script_version"))
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

    try:
        profiles = [
            dict(profile) for profile in support_profiles
            if isinstance(profile, Mapping)
        ]
    except (TypeError, ValueError, RecursionError, MemoryError):
        profiles = []
    canonical_profiles = protocol_support_profiles()
    if profiles != canonical_profiles:
        failures.append("protocol support profiles do not match the exact canonical executable roster")

    owners = dict(owner_versions) if isinstance(owner_versions, Mapping) else {}
    expected_owners = canonical_decision_owner_versions(
        before_snapshot_owner=before_binding.get("script_version"),
        after_snapshot_owner=after_binding.get("script_version"),
    )
    if owners != expected_owners:
        failures.append("decision owner versions do not match the exact canonical owner roster")

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
        "owner_versions": owners,
        "support_profiles": profiles,
        "failures": list(dict.fromkeys(failures)),
        "coverage_gaps": list(dict.fromkeys(gaps)),
    }


def validate_comparison_admission(value: Any) -> dict:
    """Validate the complete closed ``protocol_comparison_admission/1`` contract.

    This validator is deliberately independent of the producer's ``status`` leaf.  A caller cannot
    retain the word ``admitted`` after deleting custody, subject, owner, or support-profile evidence.
    Canonical non-admitted receipts remain usable explanations, but only a complete and coherent
    admitted receipt can authorize the sole cutover gate.
    """
    present = value is not None
    validation_failures: List[str] = []

    def fail(reason: str) -> None:
        if reason not in validation_failures:
            validation_failures.append(reason)

    def string_list(raw: Any, label: str) -> List[str]:
        if (not isinstance(raw, list)
                or any(not isinstance(item, str) or not item.strip() for item in raw)
                or len(set(raw)) != len(raw)):
            fail(f"comparison admission {label} is missing or malformed")
            return []
        return list(raw)

    try:
        if not isinstance(value, dict):
            fail("comparison admission receipt is missing or has an unusable root shape")
            raise ValueError("invalid admission root")
        admission = value
        expected_top_keys = {
            "schema", "status", "decision_eligible", "assurance_level",
            "engagement_id", "campaign_id", "source_binding", "subject_binding",
            "owner_versions", "support_profiles", "failures", "coverage_gaps",
        }
        if set(admission) != expected_top_keys:
            fail("comparison admission receipt fields do not match protocol_comparison_admission/1")
        if admission.get("schema") != ADMISSION_SCHEMA:
            fail("comparison admission schema is missing or unsupported")

        failures = string_list(admission.get("failures"), "failures")
        gaps = string_list(admission.get("coverage_gaps"), "coverage gaps")
        # Empty lists are canonical and valid; ``string_list`` distinguishes them from malformed roots.
        if admission.get("failures") == []:
            failures = []
        if admission.get("coverage_gaps") == []:
            gaps = []

        status = admission.get("status")
        expected_status = (
            "not_comparable" if failures else "coverage_lost" if gaps else "admitted"
        )
        if status not in {"admitted", "coverage_lost", "not_comparable"}:
            fail("comparison admission status is missing or unsupported")
        elif status != expected_status:
            fail("comparison admission status does not reconcile to its failures and coverage gaps")
        if type(admission.get("decision_eligible")) is not bool \
                or admission.get("decision_eligible") is not (status == "admitted"):
            fail("comparison admission decision eligibility does not reconcile to its status")
        expected_assurance = (
            "observed_state_preservation" if status == "admitted" else "not_verified"
        )
        if admission.get("assurance_level") != expected_assurance:
            fail("comparison admission assurance level does not reconcile to its status")

        engagement_id = admission.get("engagement_id")
        campaign_id = admission.get("campaign_id")
        if not _text(engagement_id):
            fail("comparison admission top-level engagement identity is missing or malformed")
        if type(campaign_id) is not int:
            fail("comparison admission top-level campaign identity is missing or malformed")

        source_pair = admission.get("source_binding")
        if not isinstance(source_pair, dict) or set(source_pair) != {"before", "after"}:
            fail("comparison admission source pair is missing or malformed")
            source_pair = {}
        source_views: Dict[str, dict] = {}
        source_keys = {
            "source", "sha256", "bytes", "snapshot_id", "campaign_id",
            "engagement_id", "label", "script_version",
        }
        for side in ("before", "after"):
            binding = source_pair.get(side)
            if not isinstance(binding, dict) or set(binding) != source_keys:
                fail(f"{side} comparison source binding is missing or malformed")
                binding = {}
            source_views[side] = binding
            if binding.get("source") not in _COMPARISON_SOURCE_OWNERS:
                fail(f"{side} comparison source owner is missing or unsupported")
            if not _is_sha256(binding.get("sha256")):
                fail(f"{side} exact-source SHA-256 binding is missing or malformed")
            byte_count = binding.get("bytes")
            if type(byte_count) is not int or byte_count <= 0:
                fail(f"{side} exact-source byte count is missing or malformed")
            if type(binding.get("snapshot_id")) is not int:
                fail(f"{side} snapshot identity is missing or malformed")
            if type(binding.get("campaign_id")) is not int:
                fail(f"{side} campaign identity is missing or malformed")
            if not _text(binding.get("engagement_id")):
                fail(f"{side} engagement identity is missing or malformed")
            if not _text(binding.get("label")):
                fail(f"{side} snapshot label is missing or malformed")
            if not _text(binding.get("script_version")):
                fail(f"{side} snapshot owner version is missing or malformed")

        before_source = source_views["before"]
        after_source = source_views["after"]
        if before_source.get("snapshot_id") == after_source.get("snapshot_id"):
            fail("before and after comparison snapshot identities must be distinct")
        if (before_source.get("campaign_id") != campaign_id
                or after_source.get("campaign_id") != campaign_id):
            fail("comparison admission campaign identity does not reconcile to its source pair")
        if (before_source.get("engagement_id") != engagement_id
                or after_source.get("engagement_id") != engagement_id):
            fail("comparison admission engagement identity does not reconcile to its source pair")

        subject_pair = admission.get("subject_binding")
        if not isinstance(subject_pair, dict) or set(subject_pair) != {"before", "after"}:
            fail("comparison admission subject pair is missing or malformed")
            subject_pair = {}
        subject_keys = {
            "schema", "identity_kind", "n_subjects", "subjects",
            "subjects_sha256", "valid", "failures",
        }
        for side in ("before", "after"):
            subjects = subject_pair.get(side)
            if not isinstance(subjects, dict) or set(subjects) != subject_keys:
                fail(f"{side} comparison subject binding is missing or malformed")
                continue
            if subjects.get("schema") != SUBJECT_BINDING_SCHEMA \
                    or subjects.get("identity_kind") != "local_snapshot_device":
                fail(f"{side} comparison subject identity contract is missing or unsupported")
            rows = subjects.get("subjects")
            if (not isinstance(rows, list)
                    or any(not isinstance(item, str) or not item.strip() for item in rows)):
                fail(f"{side} comparison subject identities are missing or malformed")
                rows = []
            ordered = sorted(rows, key=lambda item: (item.casefold(), item))
            if rows != ordered or len({item.casefold() for item in rows}) != len(rows):
                fail(f"{side} comparison subject identities are not canonical and collision-free")
            if type(subjects.get("n_subjects")) is not int \
                    or subjects.get("n_subjects") != len(rows):
                fail(f"{side} comparison subject count does not reconcile to its identities")
            if subjects.get("subjects_sha256") != canonical_sha256({"subjects": rows}):
                fail(f"{side} comparison subject digest does not reconcile to its identities")
            nested_failures = string_list(
                subjects.get("failures"), f"{side} subject-binding failures")
            if subjects.get("failures") == []:
                nested_failures = []
            if type(subjects.get("valid")) is not bool \
                    or subjects.get("valid") is not (not nested_failures):
                fail(f"{side} comparison subject validity does not reconcile to its failures")
            for item in nested_failures:
                if f"{side}: {item}" not in failures:
                    fail(f"{side} subject-binding failure is not retained by comparison admission")
            empty_gap = f"{side} snapshot has no bound device subjects"
            if subjects.get("valid") is True and not rows and empty_gap not in gaps:
                fail(f"{side} empty subject scope is not retained as a comparison coverage gap")
            if rows and empty_gap in gaps:
                fail(f"{side} comparison coverage gap contradicts its non-empty subject scope")

        profiles = admission.get("support_profiles")
        canonical_profiles = protocol_support_profiles()
        if not isinstance(profiles, list) or profiles != canonical_profiles:
            fail("comparison support profiles do not match the exact canonical executable roster")

        owners = admission.get("owner_versions")
        expected_owners = canonical_decision_owner_versions(
            before_snapshot_owner=before_source.get("script_version"),
            after_snapshot_owner=after_source.get("script_version"),
        )
        if not isinstance(owners, dict) or owners != expected_owners:
            fail("comparison owner versions do not match the exact canonical owner roster")
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, MemoryError):
        if not validation_failures:
            fail("comparison admission validation failed")

    return {
        "present": present,
        "valid": not validation_failures,
        "reason": "ok" if not validation_failures else validation_failures[0],
        "failures": validation_failures,
    }


def _assessability_declares(
        snapshot: Mapping[str, Any], protocol: str, *, positive_subject_only: bool = False) -> bool:
    receipt = snapshot.get("protocol_assessability")
    field = "rows" if positive_subject_only else "families"
    families = receipt.get(field) if isinstance(receipt, dict) else None
    wanted = protocol.casefold()
    return isinstance(families, list) and any(
        isinstance(row, dict)
        and _text(row.get("protocol")).casefold() == wanted
        and (
            not positive_subject_only
            or row.get("health_row_emitted") is True
        )
        for row in families
    )


def _declares_any(snapshot: Mapping[str, Any], keys: Iterable[str]) -> bool:
    return any(key in snapshot for key in keys)


def _stp_positive_or_malformed(snapshot: Mapping[str, Any]) -> bool:
    """Recognize actual STP subjects/attempted malformed evidence, not the fixed family roster."""
    from cisco_toolkit import protocol_deltas

    health = snapshot.get("protocol_health")
    health_attempted = (
        "protocol_health" in snapshot and not isinstance(health, list)
    ) or (
        isinstance(health, list) and any(
            isinstance(row, dict) and _text(row.get("protocol")).casefold() == "stp"
            for row in health
        )
    )
    interfaces = snapshot.get("interfaces")
    interface_topology = isinstance(interfaces, dict) and any(
        isinstance(row, dict)
        and (
            "stp_fwd_vlans" in row
            or "stp_blk_vlans" in row
        )
        for device_rows in interfaces.values()
        if isinstance(device_rows, dict)
        for row in device_rows.values()
    )
    roots = snapshot.get("stp_roots")
    root_topology = "stp_roots" in snapshot and (
        not isinstance(roots, dict) or bool(roots)
    )
    topology_attempted = root_topology or interface_topology
    consistency_attempted = (
        "stp_consistency_baseline" in snapshot
        or health_attempted
        or topology_attempted
        or _assessability_declares(snapshot, "STP", positive_subject_only=True)
    )
    if not consistency_attempted and not topology_attempted:
        return False
    consistency = (
        protocol_deltas._stp_consistency_view(snapshot)
        if consistency_attempted else {"valid": True, "rows": []}
    )
    topology = (
        protocol_deltas._topology_view(snapshot)
        if topology_attempted else {"valid": True, "roots": {}, "paths": {}, "gaps": []}
    )
    return (
        consistency.get("valid") is not True
        or topology.get("valid") is not True
        or bool(consistency.get("rows"))
        or bool(topology.get("roots"))
        or bool(topology.get("paths"))
        or bool(topology.get("gaps"))
    )


def _etherchannel_positive_or_malformed(snapshot: Mapping[str, Any]) -> bool:
    """Recognize a local bundle subject without treating an emitted empty container as support."""
    from cisco_toolkit import protocol_deltas

    baseline = snapshot.get("etherchannel_baseline")
    projection = snapshot.get("etherchannel_projection")
    attempted = baseline is not None or projection is not None or _assessability_declares(
        snapshot, "EtherChannel", positive_subject_only=True
    )
    if not attempted:
        return False
    view = protocol_deltas._etherchannel_view(snapshot)
    return view.get("valid") is not True or bool(view.get("rows"))


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
         ("ipv6_routing_adjacency_baseline",), None, None),
        (protocol_deltas.compute_bgp_configured_peer_delta,
         ("bgp_configured_peer_baseline",), None, None),
        (protocol_deltas.compute_stp_consistency_delta,
         (), None, _stp_positive_or_malformed),
        (protocol_deltas.compute_stp_topology_delta,
         (), None, _stp_positive_or_malformed),
        (protocol_deltas.compute_etherchannel_delta,
         (), None, _etherchannel_positive_or_malformed),
        (protocol_deltas.compute_vtp_safety_delta,
         ("vtp_safety_baseline",), "VTP", None),
        (protocol_deltas.compute_fhrp_configured_group_delta,
         ("fhrp_configured_group_baseline",), "FHRP", None),
        (protocol_deltas.compute_fhrp_redundancy_domain_delta,
         ("fhrp_redundancy_domain_baseline",), None, None),
    )
    results: List[dict] = []
    comparison_source_binding = {
        "before": before_source,
        "after": after_source,
    }
    for computer, keys, assessability_family, predicate in specs:
        applicable = (
            predicate(old) or predicate(new)
            if predicate is not None
            else _declares_any(old, keys) or _declares_any(new, keys)
        )
        if assessability_family:
            applicable = applicable or _assessability_declares(
                old, assessability_family, positive_subject_only=True
            ) or _assessability_declares(
                new, assessability_family, positive_subject_only=True
            )
        if applicable:
            results.append(computer(
                old,
                new,
                comparison_source_binding=comparison_source_binding,
            ))

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
                reconciled = multichassis_lag.validate_multichassis_lag_snapshot_evidence(
                    stored,
                    snapshot.get("multichassis_lag_typed_observations"),
                    snapshot.get("devices"),
                )
                if reconciled.get("valid") is True:
                    return stored
                # A valid-but-empty baseline forces the existing native owner to emit a
                # not-comparable receipt. It cannot preserve any pair/attachment claim from an
                # unreconciled stored projection.
                return multichassis_lag.compute_multichassis_lag_domain_baseline(
                    {"observations": []})
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


_PROTOCOL_DELTA_NATIVE_SCHEMAS = frozenset({
    "ipv6_routing_adjacency_delta/1",
    "bgp_configured_peer_delta/1",
    "stp_consistency_delta/1",
    "stp_topology_delta/1",
    "etherchannel_delta/1",
    "vtp_safety_delta/1",
    "fhrp_configured_group_delta/1",
    "fhrp_redundancy_domain_delta/1",
})
_PROTOCOL_DELTA_SOURCE_RECEIPT_FIELDS = frozenset({
    "present", "valid", "source_bound", "owner_source_authority",
    "comparison_source_bound", "comparison_source_basis", "snapshot_sha256",
    "projection_sha256", "reason",
})
_MULTICHASSIS_LAG_DELTA_SCHEMA = "multichassis_lag_delta/1"
_MULTICHASSIS_SOURCE_BINDING_FIELDS = frozenset({
    "custody", "before_snapshot_sha256", "after_snapshot_sha256",
    "before_baseline_sha256", "after_baseline_sha256",
})


def _protocol_delta_source_custody(value: Mapping[str, Any]) -> tuple[dict, List[str]]:
    """Validate the native protocol-delta receipt pair without minting source authority.

    The comparison owner already decided whether a current-run owner marker or an exact-snapshot
    reconciliation authorizes each projection.  Composition verifies that closed receipt and its
    internal implications; it never upgrades a false custody bit from caller-provided hashes.
    """
    failures: List[str] = []
    bound = {"before": False, "after": False}
    pair = value.get("source_receipts")
    if not isinstance(pair, dict) or set(pair) != {"before", "after"}:
        return bound, ["native protocol source receipt pair is missing or malformed"]

    for side in ("before", "after"):
        receipt = pair.get(side)
        if (not isinstance(receipt, dict)
                or set(receipt) != _PROTOCOL_DELTA_SOURCE_RECEIPT_FIELDS):
            failures.append(f"{side} native protocol source receipt is missing or malformed")
            continue
        bool_fields = (
            "present", "valid", "source_bound", "owner_source_authority",
            "comparison_source_bound",
        )
        if any(type(receipt.get(field)) is not bool for field in bool_fields):
            failures.append(f"{side} native protocol source receipt flags are malformed")
            continue
        if any(not isinstance(receipt.get(field), str) for field in (
                "comparison_source_basis", "snapshot_sha256", "projection_sha256", "reason")):
            failures.append(f"{side} native protocol source receipt text leaves are malformed")
            continue

        present = receipt["present"]
        valid = receipt["valid"]
        owner_bound = receipt["source_bound"] and receipt["owner_source_authority"]
        comparison_bound = receipt["comparison_source_bound"]
        basis = receipt["comparison_source_basis"]
        snapshot_sha = receipt["snapshot_sha256"]
        projection_sha = receipt["projection_sha256"]
        coherent = True

        if valid and not present:
            failures.append(f"{side} native protocol valid receipt is not present")
            coherent = False
        if receipt["source_bound"] and (not present or not valid):
            failures.append(f"{side} native protocol owner custody contradicts receipt validity")
            coherent = False
        if snapshot_sha and not _is_sha256(snapshot_sha):
            failures.append(f"{side} native protocol snapshot digest is malformed")
            coherent = False
        if projection_sha and not _is_sha256(projection_sha):
            failures.append(f"{side} native protocol projection digest is malformed")
            coherent = False

        if comparison_bound:
            if not present or not valid or not _is_sha256(projection_sha):
                failures.append(
                    f"{side} native protocol comparison custody lacks a valid owner projection")
                coherent = False
            if basis == "current_run_owner_source":
                if not owner_bound:
                    failures.append(
                        f"{side} native protocol current-run custody lacks owner authority")
                    coherent = False
            elif basis == "exact_snapshot_bytes_and_validated_owner_projection":
                if owner_bound or not _is_sha256(snapshot_sha):
                    failures.append(
                        f"{side} native protocol exact-snapshot custody is incoherent")
                    coherent = False
            else:
                failures.append(f"{side} native protocol comparison custody basis is unsupported")
                coherent = False
        else:
            if basis != "not_source_bound" or owner_bound:
                failures.append(f"{side} native protocol unbound custody disposition is incoherent")
                coherent = False

        bound[side] = bool(comparison_bound and coherent)
    return bound, failures


def _multichassis_source_custody(value: Mapping[str, Any]) -> List[str]:
    """Validate the distinct multichassis comparison binding in its own v1 terms."""
    failures: List[str] = []
    if value.get("owner_version") != "1":
        failures.append("multichassis delta owner version is missing or unsupported")
    binding = value.get("source_binding")
    if (not isinstance(binding, dict)
            or set(binding) != _MULTICHASSIS_SOURCE_BINDING_FIELDS):
        return [*failures, "multichassis comparison source binding is missing or malformed"]
    if binding.get("custody") != "persisted_snapshot_bytes_bound":
        failures.append("multichassis comparison source custody is missing or unsupported")
    for leaf in (
            "before_snapshot_sha256", "after_snapshot_sha256",
            "before_baseline_sha256", "after_baseline_sha256"):
        if not _is_sha256(binding.get(leaf)):
            failures.append(f"multichassis {leaf.replace('_', ' ')} is missing or malformed")
    return failures


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
    is_protocol_delta = schema in _PROTOCOL_DELTA_NATIVE_SCHEMAS
    is_multichassis = schema == _MULTICHASSIS_LAG_DELTA_SCHEMA
    assurance = value.get("assurance_level")
    if assurance not in ASSURANCE_LEVELS:
        failures.append("native delta assurance level is missing or unsupported")
        assurance = "not_verified"
    raw_rows = value.get("changes")
    if not isinstance(raw_rows, list):
        failures.append("native delta changes are missing or malformed")
        raw_rows = []
    protocol_source_bound = {"before": False, "after": False}
    applicability = value.get("applicability")
    if is_protocol_delta:
        if value.get("owner") != schema:
            failures.append("native protocol delta owner does not match its schema")
        if applicability not in ("applicable", "not_applicable"):
            failures.append("native protocol delta applicability is missing or unsupported")
        elif applicability == "applicable" and not raw_rows:
            failures.append("applicable native protocol delta emitted no subject rows")
        elif applicability == "not_applicable" and raw_rows:
            failures.append("not-applicable native protocol delta emitted subject rows")
        protocol_source_bound, custody_failures = _protocol_delta_source_custody(value)
        failures.extend(custody_failures)
        if applicability == "not_applicable" and not all(protocol_source_bound.values()):
            failures.append(
                "not-applicable native protocol delta lacks source-bound receipts on both sides")
    elif is_multichassis:
        failures.extend(_multichassis_source_custody(value))

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
    observed_effects = {token: 0 for token in _DECISION_EFFECTS}
    multichassis_record_types = {
        "local_observation",
        "reciprocal_peer_pair",
        "local_leg",
        "reconciled_attachment",
    }
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
        record_type = raw.get("record_type")
        if is_multichassis and record_type not in multichassis_record_types:
            failures.append(
                f"native changes[{row_index}] is missing a closed multichassis record type"
            )
            continue
        expected = _expected(change_intent, family, transition, subject)
        normalized = {
            "family": family,
            "subject": subject,
            "transition": transition,
            "expected": expected,
            "decision_effect": _row_effect(transition, expected, producer_effect),
            "before_state": raw.get("before_state", {}),
            "after_state": raw.get("after_state", {}),
            "note": raw["note"],
        }
        if is_multichassis:
            normalized["subject_kind"] = record_type
        rows.append(normalized)
        observed_counts[transition] += 1
        observed_effects[producer_effect] += 1
    if by_transition != observed_counts:
        failures.append("native delta transition summary does not reconcile to its complete rows")
    if is_protocol_delta:
        by_effect = raw_summary.get("by_decision_effect") \
            if isinstance(raw_summary, dict) else None
        if (not isinstance(by_effect, dict)
                or tuple(by_effect) != _DECISION_EFFECTS
                or any(
                    not isinstance(by_effect.get(effect), int)
                    or isinstance(by_effect.get(effect), bool)
                    or by_effect.get(effect) < 0
                    for effect in _DECISION_EFFECTS
                )
                or by_effect != observed_effects):
            failures.append(
                "native protocol decision-effect summary does not reconcile to its complete rows")
        comparable_count = sum(
            count for transition, count in observed_counts.items()
            if transition not in {"coverage_lost", "not_comparable"}
        )
        if (not isinstance(raw_summary, dict)
                or type(raw_summary.get("n_subjects")) is not int
                or raw_summary.get("n_subjects") != len(rows)
                or type(raw_summary.get("n_comparable")) is not int
                or raw_summary.get("n_comparable") != comparable_count):
            failures.append("native protocol subject/comparable summary is malformed")
        expected_comparable = bool(comparable_count) and not observed_counts["not_comparable"]
        expected_assessed = bool(comparable_count) and not (
            observed_counts["coverage_lost"] or observed_counts["not_comparable"])
        if (type(value.get("comparable")) is not bool
                or value.get("comparable") is not expected_comparable
                or type(value.get("assessed")) is not bool
                or value.get("assessed") is not expected_assessed):
            failures.append("native protocol comparable/assessed flags do not reconcile to its rows")
        if applicability == "not_applicable" and rows:
            failures.append("not-applicable native protocol delta is not rowless")
        if applicability == "applicable" and not rows:
            failures.append("applicable native protocol delta has no valid materialized subject")
        if applicability == "applicable" and not all(protocol_source_bound.values()):
            expected_transition = (
                "coverage_lost" if protocol_source_bound["before"] else "not_comparable"
            )
            if (assurance != "not_verified" or not rows
                    or any(
                        row["transition"] != expected_transition
                        or row["decision_effect"] != "not_verified"
                        for row in rows
                    )):
                failures.append(
                    "unbound native protocol custody is not reconciled to an abstaining transition")
    elif is_multichassis:
        raw_comparison_failures = value.get("comparison_failures")
        if (not isinstance(raw_comparison_failures, list)
                or any(not _text(item) for item in raw_comparison_failures)
                or len(set(raw_comparison_failures)) != len(raw_comparison_failures)):
            failures.append("multichassis comparison failures are missing or malformed")
            raw_comparison_failures = []
        if not raw_comparison_failures and not rows:
            failures.append("source-bound multichassis delta emitted no subject rows")
        if isinstance(raw_summary, dict):
            n_changes = sum(
                count for transition, count in observed_counts.items()
                if transition not in {"unchanged_healthy", "unchanged_degraded"}
            )
            if (type(raw_summary.get("n_subjects")) is not int
                    or raw_summary.get("n_subjects") != len(rows)
                    or type(raw_summary.get("n_changes")) is not int
                    or raw_summary.get("n_changes") != n_changes):
                failures.append("multichassis delta summary does not reconcile to its rows")
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
    payload = {
        "schema": FAMILY_CHANGE_SET_SCHEMA,
        "owner": "reference_only_composition",
        "owns_score": False,
        "owns_verdict": False,
        "summary": summary,
        "families": families,
    }
    return BoundProtocolFamilyChangeSet(
        payload,
        payload_sha256=canonical_sha256(payload),
        _authority=_BOUND_FAMILY_SET_AUTHORITY,
    )


def current_baseline_blocker_export(snapshot: Any) -> dict:
    """Return the uncapped, non-decision projection behind ``current_baseline_gate/1``.

    The v1 gate deliberately retains its 50-row compatibility cap.  This additive owner first asks
    that unchanged gate to reconcile the complete validation plan, then projects every classified
    blocker for export.  It never supplies counts or rows back to decision code.
    """
    from cisco_toolkit.analyze import (
        classify_current_baseline_item,
        compute_current_baseline_gate,
    )

    snap = _dict(snapshot)
    plan = snap.get("validation_plan")
    gate = compute_current_baseline_gate(plan)
    integrity = _dict(gate.get("integrity"))
    summary = _dict(gate.get("summary"))
    failures: List[str] = []
    if integrity.get("valid") is not True:
        failures.extend(
            str(item) for item in _list(integrity.get("failures")) if str(item).strip()
        )
    items = plan.get("items") if isinstance(plan, dict) else None
    if not isinstance(items, list):
        failures.append("validation plan items are unavailable")

    def bounded(value: Any, limit: int) -> str:
        text = value.strip() if isinstance(value, str) else ""
        return text if len(text) <= limit else text[:max(0, limit - 3)] + "..."

    rows: List[dict] = []
    if not failures:
        for item in items:
            state = classify_current_baseline_item(item)
            if state in {"clear", "invalid"}:
                continue
            rows.append({
                "device": bounded(item.get("device"), 120),
                "wave": bounded(item.get("wave"), 120),
                "category": bounded(item.get("category"), 80),
                "severity": bounded(item.get("severity"), 20),
                "check": bounded(item.get("check"), 240),
                "evidence_state": state,
                "expect": bounded(item.get("expect"), 600),
                "projection_custody": bounded(item.get("projection_custody"), 120),
                "source_key": bounded(item.get("source_key"), 300),
            })
    declared_total = summary.get("n_blockers")
    if (not failures and (
            type(declared_total) is not int or declared_total != len(rows))):
        failures.append("uncapped blocker rows do not reconcile to current_baseline_gate/1")
        rows = []
    status = "available" if not failures else "not_verified"
    payload = {
        "schema": "current_baseline_blocker_export/1",
        "owner": "reference_only_projection",
        "owns_verdict": False,
        "status": status,
        "source_owner": "validation_plan reconciled by current_baseline_gate/1",
        "rows": rows,
        "summary": {
            "n_blockers_total": len(rows) if not failures else 0,
            "n_rows_returned": len(rows),
            "omitted": 0,
            "complete": not failures,
            "rows_sha256": canonical_sha256({"rows": rows}),
        },
        "failures": list(dict.fromkeys(failures))[:20],
        "note": (
            "Complete uncapped blocker export; this reference-only projection does not participate "
            "in the current-baseline or cutover verdict."
            if status == "available" else
            "Complete blocker export is not verified because the validation plan did not reconcile."
        ),
    }
    return payload


def cutover_operator_evidence(snapshot: Any) -> dict:
    """Project existing simulation and rollback owners without inventing rehearsal success.

    ``failure_impact`` is an existing bounded simulation projection, not proof that an operator
    rehearsed a failure.  The additive ``l2_failure_rehearsal/1`` receipt composes the existing
    failover/native-delta/traffic-assurance owners and remains reference-only.  ``migration_scenarios``
    owns rollback planning prose, not execution.  Keeping those distinctions explicit lets decision
    surfaces put the evidence in the right order while withholding a stronger field claim than the
    stored snapshot supports.
    """
    snap = _dict(snapshot)
    # Lazy import avoids a module cycle: the rehearsal composer reuses the native delta owners,
    # which in turn consume the shared contracts in this module.
    from cisco_toolkit.l2_rehearsal import compute_l2_failure_rehearsal

    l2_rehearsal = compute_l2_failure_rehearsal(snapshot)
    raw_impacts = snap.get("failure_impact")
    impacts = [dict(row) for row in raw_impacts
               if isinstance(row, dict)] if isinstance(raw_impacts, list) else []
    l2_status = l2_rehearsal.get("status")
    l2_has_projection = l2_status in {"simulation_only", "projected_risk", "current_fault"}
    rehearsal = {
        "status": (
            "current_fault" if l2_status == "current_fault" else
            "projected_risk" if l2_status == "projected_risk" else
            "simulation_only" if impacts or l2_has_projection else
            "not_verified"
        ),
        "assurance_level": "not_verified",
        "source_owner": "failure_impact projection",
        "n_impacts_total": len(impacts),
        "impacts": impacts,
        "l2_failure_rehearsal": l2_rehearsal,
        "note": (
            "Existing failure-impact and bounded L2 projections are retained as planning evidence; "
            "no source-bound operator rehearsal receipt is present, so rehearsal remains not verified."
            if impacts or l2_has_projection else
            "No supported source-bound failure projection or operator rehearsal receipt is present."
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
        "current_baseline_blocker_export": current_baseline_blocker_export(snapshot),
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
