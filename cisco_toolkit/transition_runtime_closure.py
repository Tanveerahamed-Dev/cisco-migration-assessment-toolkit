"""R2.0 exact-runtime-closure evidence and independent review protocol.

Runtime inventory v1 remains a partial, non-portable observation and can never satisfy this
protocol.  A v2 producer may assemble exact raw evidence for one selected R2.0 runtime profile,
but the envelope is always non-authoritative and never declares itself complete.  Only a
detached Ed25519 review, verified relative to separately supplied current trust-policy bytes and
an externally selected exact policy digest, can mint an opaque
``COMPLETE_EXACT_RUNTIME_CLOSURE`` result.  Every later use must supply and recheck the current
policy and its external digest selection so successor revocation cannot be bypassed by replaying
the token's retained historical policy.

The positive decision is deliberately narrow: it covers one exact supported-execution/ABI
denominator under an immutable content-addressed executable allow-set and deny-by-default
execution policy.  It does not prove representative workload adequacy, universal all-input
behavior, portability, semantic equivalence, budget approval, qualification, promotion, or
Release 3 readiness.  This module ships no closure evidence, collector, policy, key, signature,
or positive decision.  A caller-supplied policy digest makes the trust anchor explicit but cannot
    prove that the caller selected it independently.  Policy issuer, namespace, succession and
    custody; reviewer-key identity and custody; trusted time; freshness; anti-rollback; and
    real-world independence remain external responsibilities.  Exact byte binding also does not
    establish the semantic truth or real-world capture completeness of an artifact.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator, Mapping as MappingABC
from typing import Any, Mapping

from .transition_contract import (
    TransitionContractError,
    _array,
    _boolean,
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


TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA = "atlas.transition-runtime-closure-evidence/2"
RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA = "atlas.transition-runtime-closure-review-receipt/1"
RUNTIME_CLOSURE_REVIEW_SIGNATURE_SCHEMA = "atlas.transition-runtime-closure-review-signature/1"
RUNTIME_CLOSURE_REVIEW_TRUST_POLICY_SCHEMA = (
    "atlas.transition-runtime-closure-review-trust-policy/1"
)
RUNTIME_CLOSURE_REVIEW_TRUSTED_KEY_SCHEMA = (
    "atlas.transition-runtime-closure-review-trusted-key/1"
)
RUNTIME_CLOSURE_REVIEW_AUTHORIZATION_SCHEMA = (
    "atlas.transition-runtime-closure-review-authorization/1"
)
RUNTIME_CLOSURE_REVIEW_BINDINGS_SCHEMA = "atlas.transition-runtime-closure-review-bindings/1"

RUNTIME_CLOSURE_REVIEW_PURPOSE = "ATLAS_R2_EXACT_RUNTIME_CLOSURE_REVIEW"
RUNTIME_CLOSURE_REVIEW_POLICY_KIND = (
    "EXTERNAL_INDEPENDENT_RUNTIME_CLOSURE_REVIEW_KEY_ALLOWLIST"
)
RUNTIME_CLOSURE_REVIEW_REVIEWER_KIND = "INDEPENDENT_REVIEWER"
RUNTIME_CLOSURE_REVIEW_REVIEWER_ROLE = "EXACT_RUNTIME_CLOSURE_REVIEWER"
RUNTIME_CLOSURE_REVIEW_SUBSTRATE = "DECLARATIVE_DSL_ONLY"
RUNTIME_CLOSURE_REVIEW_SIGNATURE_ALGORITHM = "Ed25519"
RUNTIME_CLOSURE_SCOPE_KIND = "EXACT_SELECTED_R2_0_RUNTIME_PROFILE"

RUNTIME_CLOSURE_EVIDENCE_ABSENT = "ABSENT"
RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE = "COLLECTED_INCOMPLETE"
RUNTIME_CLOSURE_EVIDENCE_READY = "READY_FOR_EXTERNAL_REVIEW"
RUNTIME_CLOSURE_COVERAGE_ABSENT = "NOT_MEASURED"
RUNTIME_CLOSURE_COVERAGE_INCOMPLETE = "MEASURED_INCOMPLETE"
RUNTIME_CLOSURE_COVERAGE_READY = "MEASURED_CANDIDATE_COMPLETE"
RUNTIME_CLOSURE_REVIEW_COMPLETE = "COMPLETE_EXACT_RUNTIME_CLOSURE"
RUNTIME_CLOSURE_REVIEW_INCOMPLETE = "INCOMPLETE_RUNTIME_CLOSURE"

RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY = (
    "Exact non-authoritative evidence for external review of one selected R2.0 supported-"
    "execution and ABI denominator under an immutable content-addressed executable allow-set "
    "and deny-by-default execution policy; the envelope cannot establish closure, representative "
    "workload adequacy, universal all-input behavior, portability, semantic equivalence, approve "
    "budgets, qualify a pack, authorize execution, enable promotion, or include Release 3."
)

RUNTIME_CLOSURE_DIGEST_ROLE_MAP = {
    "reference_runtime_inventory_v1_digest": "REFERENCE_RUNTIME_INVENTORY_V1",
    "structural_census_digest": "STRUCTURAL_TCB_CENSUS",
    "prototype_measurement_digest": "PROTOTYPE_MEASUREMENTS",
    "dsl_interpreter_digest": "DSL_INTERPRETER_SOURCE",
    "prototype_program_digest": "PROTOTYPE_PROGRAM",
    "prototype_pack_manifest_digest": "PROTOTYPE_PACK_MANIFEST",
    "prototype_tcb_manifest_digest": "PROTOTYPE_TCB_MANIFEST",
    "supported_execution_denominator_digest": "SUPPORTED_EXECUTION_DENOMINATOR",
    "installed_distribution_digest": "INSTALLED_DISTRIBUTION",
    "exact_runtime_profile_digest": "EXACT_RUNTIME_PROFILE",
    "executable_allow_set_digest": "CONTENT_ADDRESSED_EXECUTABLE_ALLOW_SET",
    "enforcement_policy_digest": "DENY_BY_DEFAULT_EXECUTION_POLICY",
    "collector_tcb_digest": "COLLECTOR_AND_VERIFIER_TCB",
    "execution_environment_manifest_digest": "EXECUTION_ENVIRONMENT_MANIFEST",
}
RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS = tuple(RUNTIME_CLOSURE_DIGEST_ROLE_MAP)
RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES = (
    *RUNTIME_CLOSURE_DIGEST_ROLE_MAP.values(),
    "STATIC_TRANSITIVE_DEPENDENCY_CLOSURE",
    "PROCESS_TREE_LIFETIME_TRACE",
    "EXECUTABLE_MAPPING_LOAD_UNLOAD_TRACE",
    "FILE_IDENTITY_AND_HANDLE_TRACE",
    "LOADER_RESOLUTION_TRACE",
    "CRYPTO_PROVIDER_TRACE",
    "PLATFORM_BOOT_ATTESTATION",
    "COLLECTOR_LOSS_AND_RECONCILIATION",
)

RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS = (
    "supported_execution_denominator_closed",
    "executable_allow_set_closed",
    "deny_by_default_execution_enforced",
    "static_transitive_dependency_closure_complete",
    "process_tree_captured_before_first_instruction_through_final_descendant",
    "executable_mapping_load_unload_history_complete",
    "persistent_file_identity_and_loaded_bytes_bound",
    "loader_configuration_and_resolution_bound",
    "crypto_provider_configuration_and_native_bytes_bound",
    "execution_environment_argv_cwd_and_inputs_bound",
    "platform_components_and_boot_state_attested",
    "collector_and_verifier_tcb_bound",
    "event_stream_contiguous",
    "start_end_snapshot_reconciled",
)
RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS = (
    "supported_execution_case_count",
    "allowed_executable_count",
    "observed_process_count",
    "observed_executable_mapping_count",
    "observed_load_event_count",
)
RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS = (
    "collector_loss_count",
    "sequence_gap_count",
    "unresolved_dependency_count",
    "ambiguous_resolution_count",
    "unmatched_runtime_event_count",
    "unbound_file_identity_count",
    "unexpected_process_count",
    "unexpected_executable_mapping_count",
    "unexpected_network_access_count",
    "policy_violation_count",
    "anonymous_executable_mapping_count",
    "manual_mapping_count",
    "breakaway_process_count",
    "unscanned_executable_count",
    "malformed_executable_count",
)
# Short aliases keep fixture/building code readable while the prefixed names remain canonical.
COVERAGE_BOOLEAN_FIELDS = RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
POSITIVE_COUNTER_FIELDS = RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS
ZERO_COUNTER_FIELDS = RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS

_SIGNATURE_DOMAIN = b"ATLAS-R2-RUNTIME-CLOSURE-REVIEW\x00v1\x00"
_ED25519_PUBLIC_KEY_BYTES = 32
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_ROLE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_EVIDENCE_AUTHORITY = object()
_POLICY_AUTHORITY = object()
_VERIFIED_AUTHORITY = object()


class RuntimeClosureReviewError(RuntimeError):
    """Stable, non-echoing runtime-closure evidence/review refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject(code: str) -> None:
    raise RuntimeClosureReviewError(code)


def _git_object(value: Any, path: str) -> str:
    checked = _text(value, path)
    if not _GIT_OBJECT_RE.fullmatch(checked):
        raise TransitionContractError("GIT_OBJECT_REQUIRED", path)
    return checked


def _validate_artifacts(value: Any, path: str) -> list[dict[str, Any]]:
    rows = _array(value, path)
    checked: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    roles: list[str] = []
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
        checked.append({
            "artifact_id": artifact_id,
            "role": role,
            "digest": digest,
            "raw_bytes": raw_bytes,
        })
        artifact_ids.append(artifact_id)
        roles.append(role)
    if checked != sorted(
            checked,
            key=lambda item: (item["artifact_id"], item["role"], item["digest"])):
        raise TransitionContractError("SORTED_RUNTIME_CLOSURE_ARTIFACTS_REQUIRED", path)
    if artifact_ids != sorted(set(artifact_ids)):
        raise TransitionContractError("UNIQUE_RUNTIME_CLOSURE_ARTIFACT_IDS_REQUIRED", path)
    if len(roles) != len(set(roles)):
        raise TransitionContractError("UNIQUE_RUNTIME_CLOSURE_ARTIFACT_ROLES_REQUIRED", path)
    unknown_roles = set(roles) - set(RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES)
    if unknown_roles:
        raise TransitionContractError("UNKNOWN_RUNTIME_CLOSURE_ARTIFACT_ROLE", path)
    return checked


def _validate_scope(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    _exact_keys(
        obj,
        (
            "scope_kind",
            "substrate",
            "universal_all_input_behavior",
            "portable_across_hosts",
            "semantic_equivalence",
            "continuous_capture_required",
            "deny_by_default_execution_required",
        ),
        path,
    )
    if (
            obj["scope_kind"] != RUNTIME_CLOSURE_SCOPE_KIND
            or obj["substrate"] != RUNTIME_CLOSURE_REVIEW_SUBSTRATE
            or obj["universal_all_input_behavior"] is not False
            or obj["portable_across_hosts"] is not False
            or obj["semantic_equivalence"] is not False
            or obj["continuous_capture_required"] is not True
            or obj["deny_by_default_execution_required"] is not True
    ):
        raise TransitionContractError("RUNTIME_CLOSURE_SCOPE_INVALID", path)
    return dict(obj)


def _validate_coverage(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    _exact_keys(
        obj,
        (
            "state",
            *RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS,
            *RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS,
            *RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS,
        ),
        path,
    )
    if obj["state"] not in {
            RUNTIME_CLOSURE_COVERAGE_ABSENT,
            RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
            RUNTIME_CLOSURE_COVERAGE_READY,
    }:
        raise TransitionContractError("RUNTIME_CLOSURE_COVERAGE_STATE_INVALID", f"{path}.state")
    for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS:
        _boolean(obj[field], f"{path}.{field}")
    for field in (
            *RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS,
            *RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS,
    ):
        _integer(obj[field], f"{path}.{field}", optional=True)
    return dict(obj)


def _gap_token(prefix: str, field: str) -> str:
    return f"{prefix}_{field.upper()}"


def expected_runtime_closure_gaps(value: Mapping[str, Any]) -> list[str]:
    """Derive the exact fail-closed gap set from artifacts and measured coverage."""

    roles = {
        item["role"]
        for item in _validate_artifacts(value.get("artifacts"), "$.artifacts")
    }
    coverage = _validate_coverage(value.get("coverage"), "$.coverage")
    gaps = [
        _gap_token("MISSING_ARTIFACT_ROLE", role)
        for role in RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES
        if role not in roles
    ]
    gaps.extend(
        _gap_token("COVERAGE_NOT_ESTABLISHED", field)
        for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
        if coverage[field] is not True
    )
    for field in RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS:
        if coverage[field] is None:
            gaps.append(_gap_token("COUNTER_NOT_RECORDED", field))
        elif coverage[field] <= 0:
            gaps.append(_gap_token("COUNTER_NOT_POSITIVE", field))
    for field in RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS:
        if coverage[field] is None:
            gaps.append(_gap_token("COUNTER_NOT_RECORDED", field))
        elif coverage[field] != 0:
            gaps.append(_gap_token("COUNTER_NONZERO", field))
    return sorted(gaps)


def _validate_authority(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    _exact_keys(
        obj,
        (
            "authoritative",
            "closure_decision",
            "complete_exact_runtime_closure",
            "approved_budget",
            "qualification_effect",
            "promotion_eligible",
            "release3_included",
        ),
        path,
    )
    if (
            obj["authoritative"] is not False
            or obj["closure_decision"] is not None
            or obj["complete_exact_runtime_closure"] is not False
            or obj["approved_budget"] is not None
            or obj["qualification_effect"] != "NONE"
            or obj["promotion_eligible"] is not False
            or obj["release3_included"] is not False
    ):
        raise TransitionContractError("RUNTIME_CLOSURE_EVIDENCE_AUTHORITY_LAUNDERING", path)
    return dict(obj)


def validate_transition_runtime_closure_evidence(value: Any) -> dict[str, Any]:
    """Validate a closed v2 producer envelope without minting closure authority."""

    obj = _mapping(value, "$")
    keys = (
        "schema",
        "evidence_id",
        "purpose",
        "state",
        "producer_id",
        "runtime_collector_id",
        "structural_tcb_producer_id",
        "pack_producer_id",
        "budget_proposer_id",
        "release_builder_id",
        "selected_commit",
        "selected_tree",
        *RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS,
        "scope",
        "coverage",
        "artifacts",
        "known_gaps",
        "claim_boundary",
        "authority",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA, "$")
    _identifier(obj["evidence_id"], "$.evidence_id")
    if obj["purpose"] != RUNTIME_CLOSURE_REVIEW_PURPOSE:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    if obj["state"] not in {
            RUNTIME_CLOSURE_EVIDENCE_ABSENT,
            RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
            RUNTIME_CLOSURE_EVIDENCE_READY,
    }:
        raise TransitionContractError("RUNTIME_CLOSURE_EVIDENCE_STATE_INVALID", "$.state")
    for field in (
            "producer_id",
            "runtime_collector_id",
            "structural_tcb_producer_id",
            "pack_producer_id",
            "budget_proposer_id",
            "release_builder_id",
    ):
        _identifier(obj[field], f"$.{field}")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS:
        _digest(obj[field], f"$.{field}", optional=True)
    _validate_scope(obj["scope"], "$.scope")
    coverage = _validate_coverage(obj["coverage"], "$.coverage")
    artifacts = _validate_artifacts(obj["artifacts"], "$.artifacts")
    gaps = _array(obj["known_gaps"], "$.known_gaps")
    checked_gaps = [
        _identifier(item, f"$.known_gaps[{index}]")
        for index, item in enumerate(gaps)
    ]
    if checked_gaps != sorted(set(checked_gaps)):
        raise TransitionContractError("SORTED_UNIQUE_RUNTIME_CLOSURE_GAPS_REQUIRED", "$.known_gaps")
    expected_gaps = expected_runtime_closure_gaps(obj)
    if checked_gaps != expected_gaps:
        raise TransitionContractError("EXACT_RUNTIME_CLOSURE_GAP_SET_REQUIRED", "$.known_gaps")

    state = obj["state"]
    if state == RUNTIME_CLOSURE_EVIDENCE_ABSENT:
        if (
                artifacts
                or coverage["state"] != RUNTIME_CLOSURE_COVERAGE_ABSENT
                or any(coverage[field] is not False
                       for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS)
                or any(coverage[field] is not None for field in (
                    *RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS,
                    *RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS,
                ))
        ):
            raise TransitionContractError("ABSENT_RUNTIME_CLOSURE_EVIDENCE_INVALID", "$")
    elif state == RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE:
        measured = (
            bool(artifacts)
            or any(coverage[field] is True
                   for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS)
            or any(coverage[field] is not None for field in (
                *RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS,
                *RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS,
            ))
        )
        if (
                coverage["state"] != RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
                or not measured
                or not expected_gaps
        ):
            raise TransitionContractError("INCOMPLETE_RUNTIME_CLOSURE_EVIDENCE_INVALID", "$")
    elif (
            coverage["state"] != RUNTIME_CLOSURE_COVERAGE_READY
            or expected_gaps
            or set(item["role"] for item in artifacts)
            != set(RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES)
    ):
        raise TransitionContractError("READY_RUNTIME_CLOSURE_EVIDENCE_INVALID", "$")
    if obj["claim_boundary"] != RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY_INVALID",
            "$.claim_boundary",
        )
    _validate_authority(obj["authority"], "$.authority")

    artifact_by_role = {item["role"]: item for item in artifacts}
    for field, role in RUNTIME_CLOSURE_DIGEST_ROLE_MAP.items():
        row = artifact_by_role.get(role)
        if (row is None and obj[field] is not None) or (
                row is not None and row["digest"] != obj[field]
        ):
            raise TransitionContractError("RUNTIME_CLOSURE_DIGEST_ROLE_JOIN_MISMATCH", f"$.{field}")
    return dict(obj)


class BoundTransitionRuntimeClosureEvidence(MappingABC[str, Any]):
    """Immutable canonical envelope plus the exact raw artifact bytes it indexes."""

    __slots__ = (
        "_artifact_raw_by_id",
        "_bound_digest",
        "_bound_raw",
        "_bound_source_bytes",
        "_sealed",
    )

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            raw: bytes,
            artifact_raw_by_id: Mapping[str, bytes],
            _authority: object) -> None:
        if _authority is not _EVIDENCE_AUTHORITY:
            raise TypeError("BoundTransitionRuntimeClosureEvidence requires exact evidence bytes")
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", raw)
        object.__setattr__(self, "_bound_digest", canonical_digest(dict(value)))
        object.__setattr__(
            self,
            "_artifact_raw_by_id",
            tuple(sorted(artifact_raw_by_id.items())),
        )
        object.__setattr__(
            self,
            "_bound_source_bytes",
            len(raw) + sum(len(item) for item in artifact_raw_by_id.values()),
        )
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound runtime closure evidence is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundTransitionRuntimeClosureEvidence is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


def bind_transition_runtime_closure_evidence_bytes(
        raw: bytes,
        artifact_raw_by_id: Mapping[str, bytes]) -> BoundTransitionRuntimeClosureEvidence:
    """Bind canonical envelope bytes to every exact raw artifact row."""

    try:
        if type(raw) is not bytes or type(artifact_raw_by_id) is not dict:
            raise TypeError("exact byte inputs required")
        checked = validate_transition_runtime_closure_evidence(
            parse_canonical_json_bytes(raw, require_canonical=True)
        )
        if canonical_digest(checked) != bytes_digest(raw):
            raise TransitionContractError("RUNTIME_CLOSURE_EVIDENCE_DIGEST_MISMATCH", "$")
        artifact_rows = {item["artifact_id"]: item for item in checked["artifacts"]}
        if set(artifact_raw_by_id) != set(artifact_rows):
            raise TransitionContractError("RUNTIME_CLOSURE_ARTIFACT_SET_MISMATCH", "$.artifacts")
        for artifact_id, artifact_raw in artifact_raw_by_id.items():
            if type(artifact_raw) is not bytes or not artifact_raw:
                raise TransitionContractError("RUNTIME_CLOSURE_ARTIFACT_BYTES_INVALID", "$.artifacts")
            row = artifact_rows[artifact_id]
            if row["raw_bytes"] != len(artifact_raw) or row["digest"] != bytes_digest(artifact_raw):
                raise TransitionContractError("RUNTIME_CLOSURE_ARTIFACT_BINDING_MISMATCH", "$.artifacts")
    except (TransitionContractError, TypeError, ValueError):
        _reject("transition_runtime_closure_evidence_malformed")
    return BoundTransitionRuntimeClosureEvidence(
        checked,
        raw=raw,
        artifact_raw_by_id=artifact_raw_by_id,
        _authority=_EVIDENCE_AUTHORITY,
    )


def require_bound_transition_runtime_closure_evidence(
        value: Any) -> BoundTransitionRuntimeClosureEvidence:
    if type(value) is not BoundTransitionRuntimeClosureEvidence:
        _reject("bound_transition_runtime_closure_evidence_required")
    try:
        artifact_raw_by_id = dict(value._artifact_raw_by_id)
        rebound = bind_transition_runtime_closure_evidence_bytes(
            value._bound_raw,
            artifact_raw_by_id,
        )
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
            and rebound._artifact_raw_by_id == value._artifact_raw_by_id
        )
    except (
            AttributeError,
            TransitionContractError,
            TypeError,
            ValueError,
            RuntimeClosureReviewError,
    ):
        intact = False
    if not intact:
        _reject("bound_transition_runtime_closure_evidence_mutated")
    return value


def _validate_bindings(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "selected_commit",
        "selected_tree",
        *RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS,
        "runtime_closure_evidence_digest",
        "runtime_closure_evidence_state",
        "runtime_closure_coverage_state",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, RUNTIME_CLOSURE_REVIEW_BINDINGS_SCHEMA, "$")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS:
        _digest(obj[field], f"$.{field}", optional=True)
    _digest(obj["runtime_closure_evidence_digest"], "$.runtime_closure_evidence_digest")
    if obj["runtime_closure_evidence_state"] not in {
            RUNTIME_CLOSURE_EVIDENCE_ABSENT,
            RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
            RUNTIME_CLOSURE_EVIDENCE_READY,
    }:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_EVIDENCE_STATE_INVALID",
            "$.runtime_closure_evidence_state",
        )
    if obj["runtime_closure_coverage_state"] not in {
            RUNTIME_CLOSURE_COVERAGE_ABSENT,
            RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
            RUNTIME_CLOSURE_COVERAGE_READY,
    }:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_COVERAGE_STATE_INVALID",
            "$.runtime_closure_coverage_state",
        )
    return dict(obj)


def validate_runtime_closure_review_bindings(value: Any) -> dict[str, Any]:
    return _validate_bindings(value)


def validate_runtime_closure_review_receipt(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "receipt_id",
        "purpose",
        "selected_commit",
        "selected_tree",
        *RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS,
        "runtime_closure_evidence_digest",
        "runtime_closure_evidence_state",
        "runtime_closure_coverage_state",
        "decision",
        "issued_at",
        "valid_from",
        "valid_until",
        "reviewer_key_id",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA, "$")
    _identifier(obj["receipt_id"], "$.receipt_id")
    if obj["purpose"] != RUNTIME_CLOSURE_REVIEW_PURPOSE:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS:
        _digest(obj[field], f"$.{field}", optional=True)
    _digest(obj["runtime_closure_evidence_digest"], "$.runtime_closure_evidence_digest")
    if obj["runtime_closure_evidence_state"] not in {
            RUNTIME_CLOSURE_EVIDENCE_ABSENT,
            RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
            RUNTIME_CLOSURE_EVIDENCE_READY,
    }:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_EVIDENCE_STATE_INVALID",
            "$.runtime_closure_evidence_state",
        )
    if obj["runtime_closure_coverage_state"] not in {
            RUNTIME_CLOSURE_COVERAGE_ABSENT,
            RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
            RUNTIME_CLOSURE_COVERAGE_READY,
    }:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_COVERAGE_STATE_INVALID",
            "$.runtime_closure_coverage_state",
        )
    if obj["decision"] not in {
            RUNTIME_CLOSURE_REVIEW_COMPLETE,
            RUNTIME_CLOSURE_REVIEW_INCOMPLETE,
    }:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_DECISION_INVALID", "$.decision")
    issued_at = _timestamp(obj["issued_at"], "$.issued_at")
    valid_from = _timestamp(obj["valid_from"], "$.valid_from")
    valid_until = _timestamp(obj["valid_until"], "$.valid_until")
    if issued_at > valid_from or valid_from >= valid_until:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_TIME_RANGE_INVALID", "$")
    _identifier(obj["reviewer_key_id"], "$.reviewer_key_id")
    return dict(obj)


def validate_runtime_closure_review_signature(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    _exact_keys(
        obj,
        (
            "schema",
            "purpose",
            "payload_digest",
            "signer_key_id",
            "algorithm",
            "signature_base64",
        ),
        "$",
    )
    _schema(obj, RUNTIME_CLOSURE_REVIEW_SIGNATURE_SCHEMA, "$")
    if obj["purpose"] != RUNTIME_CLOSURE_REVIEW_PURPOSE:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _digest(obj["payload_digest"], "$.payload_digest")
    _identifier(obj["signer_key_id"], "$.signer_key_id")
    if obj["algorithm"] != RUNTIME_CLOSURE_REVIEW_SIGNATURE_ALGORITHM:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_REVIEW_SIGNATURE_ALGORITHM_INVALID",
            "$.algorithm",
        )
    encoded = _text(obj["signature_base64"], "$.signature_base64")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise TransitionContractError(
            "RUNTIME_CLOSURE_REVIEW_SIGNATURE_INVALID",
            "$.signature_base64",
        ) from None
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
        raise TransitionContractError(
            "RUNTIME_CLOSURE_REVIEW_SIGNATURE_INVALID",
            "$.signature_base64",
        )
    return dict(obj)


def validate_runtime_closure_review_trust_policy(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    _exact_keys(
        obj,
        (
            "schema",
            "policy_kind",
            "policy_id",
            "policy_version",
            "purpose",
            "evaluated_at",
            "trusted_keys",
            "revoked_receipt_digests",
        ),
        "$",
    )
    _schema(obj, RUNTIME_CLOSURE_REVIEW_TRUST_POLICY_SCHEMA, "$")
    if obj["policy_kind"] != RUNTIME_CLOSURE_REVIEW_POLICY_KIND:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_POLICY_KIND_MISMATCH", "$.policy_kind")
    _identifier(obj["policy_id"], "$.policy_id")
    _identifier(obj["policy_version"], "$.policy_version")
    if obj["purpose"] != RUNTIME_CLOSURE_REVIEW_PURPOSE:
        raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _timestamp(obj["evaluated_at"], "$.evaluated_at")
    trusted_keys = _array(obj["trusted_keys"], "$.trusted_keys")
    key_ids: list[str] = []
    for index, item_value in enumerate(trusted_keys):
        path = f"$.trusted_keys[{index}]"
        item = _mapping(item_value, path)
        _exact_keys(
            item,
            (
                "schema",
                "key_id",
                "public_key_digest",
                "reviewer_kind",
                "independent_from_evidence_producer",
                "independent_from_runtime_collector",
                "independent_from_structural_tcb_producer",
                "independent_from_pack_producer",
                "independent_from_budget_proposer",
                "independent_from_release_builder",
                "authorizations",
                "allowed_subjects",
                "valid_from",
                "valid_until",
            ),
            path,
        )
        _schema(item, RUNTIME_CLOSURE_REVIEW_TRUSTED_KEY_SCHEMA, path)
        key_ids.append(_identifier(item["key_id"], f"{path}.key_id"))
        _digest(item["public_key_digest"], f"{path}.public_key_digest")
        if (
                item["reviewer_kind"] != RUNTIME_CLOSURE_REVIEW_REVIEWER_KIND
                or item["independent_from_evidence_producer"] is not True
                or item["independent_from_runtime_collector"] is not True
                or item["independent_from_structural_tcb_producer"] is not True
                or item["independent_from_pack_producer"] is not True
                or item["independent_from_budget_proposer"] is not True
                or item["independent_from_release_builder"] is not True
        ):
            raise TransitionContractError("RUNTIME_CLOSURE_REVIEWER_INDEPENDENCE_REQUIRED", path)
        expected_authorization = {
            "schema": RUNTIME_CLOSURE_REVIEW_AUTHORIZATION_SCHEMA,
            "purpose": RUNTIME_CLOSURE_REVIEW_PURPOSE,
            "target_schema_version": RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA,
            "reviewer_role": RUNTIME_CLOSURE_REVIEW_REVIEWER_ROLE,
            "substrate": RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
        }
        if _array(item["authorizations"], f"{path}.authorizations") != [expected_authorization]:
            raise TransitionContractError(
                "RUNTIME_CLOSURE_REVIEWER_AUTHORIZATION_REQUIRED",
                f"{path}.authorizations",
            )
        allowed = _array(item["allowed_subjects"], f"{path}.allowed_subjects")
        checked_subjects: list[tuple[str, str, str]] = []
        for subject_index, subject_value in enumerate(allowed):
            subject_path = f"{path}.allowed_subjects[{subject_index}]"
            subject = _mapping(subject_value, subject_path)
            _exact_keys(
                subject,
                ("selected_commit", "selected_tree", "runtime_closure_evidence_digest"),
                subject_path,
            )
            checked_subjects.append((
                _git_object(subject["selected_commit"], f"{subject_path}.selected_commit"),
                _git_object(subject["selected_tree"], f"{subject_path}.selected_tree"),
                _digest(
                    subject["runtime_closure_evidence_digest"],
                    f"{subject_path}.runtime_closure_evidence_digest",
                ),
            ))
        if not checked_subjects or checked_subjects != sorted(set(checked_subjects)):
            raise TransitionContractError(
                "SORTED_UNIQUE_RUNTIME_CLOSURE_SUBJECTS_REQUIRED",
                f"{path}.allowed_subjects",
            )
        valid_from = _timestamp(item["valid_from"], f"{path}.valid_from")
        valid_until = _timestamp(item["valid_until"], f"{path}.valid_until")
        if valid_from >= valid_until:
            raise TransitionContractError("RUNTIME_CLOSURE_REVIEW_KEY_TIME_RANGE_INVALID", path)
    if key_ids != sorted(set(key_ids)):
        raise TransitionContractError(
            "SORTED_UNIQUE_RUNTIME_CLOSURE_REVIEW_KEYS_REQUIRED",
            "$.trusted_keys",
        )
    _sorted_unique_digests(
        obj["revoked_receipt_digests"],
        "$.revoked_receipt_digests",
        allow_empty=True,
    )
    return dict(obj)


class BoundExternalRuntimeClosureReviewTrustPolicy(MappingABC[str, Any]):
    """Immutable exact external runtime-closure trust-policy bytes."""

    __slots__ = ("_bound_digest", "_bound_raw", "_bound_source_bytes", "_sealed")

    def __init__(self, value: Mapping[str, Any], *, raw: bytes, _authority: object) -> None:
        if _authority is not _POLICY_AUTHORITY:
            raise TypeError(
                "BoundExternalRuntimeClosureReviewTrustPolicy requires exact policy bytes"
            )
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", raw)
        object.__setattr__(self, "_bound_digest", canonical_digest(dict(value)))
        object.__setattr__(self, "_bound_source_bytes", len(raw))
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound runtime closure policy is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundExternalRuntimeClosureReviewTrustPolicy is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


def bind_external_runtime_closure_review_trust_policy_bytes(
        raw: bytes) -> BoundExternalRuntimeClosureReviewTrustPolicy:
    try:
        checked = validate_runtime_closure_review_trust_policy(
            parse_canonical_json_bytes(raw, require_canonical=True)
        )
        if canonical_digest(checked) != bytes_digest(raw):
            raise TransitionContractError("RUNTIME_CLOSURE_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TypeError, ValueError):
        _reject("runtime_closure_review_trust_policy_malformed")
    return BoundExternalRuntimeClosureReviewTrustPolicy(
        checked,
        raw=raw,
        _authority=_POLICY_AUTHORITY,
    )


def require_bound_runtime_closure_review_trust_policy(
        value: Any) -> BoundExternalRuntimeClosureReviewTrustPolicy:
    if type(value) is not BoundExternalRuntimeClosureReviewTrustPolicy:
        _reject("external_runtime_closure_review_trust_policy_required")
    try:
        rebound = bind_external_runtime_closure_review_trust_policy_bytes(value._bound_raw)
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
        )
    except (
            AttributeError,
            TransitionContractError,
            TypeError,
            ValueError,
            RuntimeClosureReviewError,
    ):
        intact = False
    if not intact:
        _reject("bound_runtime_closure_review_trust_policy_mutated")
    return value


def _signed_material(receipt_raw: bytes) -> bytes:
    return (
        _SIGNATURE_DOMAIN
        + RUNTIME_CLOSURE_REVIEW_PURPOSE.encode("ascii")
        + b"\x00"
        + RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA.encode("ascii")
        + b"\x00"
        + receipt_raw
    )


def runtime_closure_review_signing_material(
        receipt_raw: bytes,
        trust_policy_raw: bytes) -> bytes:
    """Return receipt-only signing material after validating both supplied documents.

    The policy is deliberately not part of the signature.  It is a replaceable external
    authorization and revocation input which every verifier use must select, pin by exact
    digest, and re-evaluate.  Parsing it here rejects malformed signing inputs; it does not
    make the signer authoritative for policy selection or preserve historical policy as
    current authority.
    """

    try:
        receipt = validate_runtime_closure_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        policy = validate_runtime_closure_review_trust_policy(
            parse_canonical_json_bytes(trust_policy_raw, require_canonical=True)
        )
        if canonical_digest(receipt) != bytes_digest(receipt_raw):
            raise TransitionContractError("RUNTIME_CLOSURE_RECEIPT_DIGEST_MISMATCH", "$")
        if canonical_digest(policy) != bytes_digest(trust_policy_raw):
            raise TransitionContractError("RUNTIME_CLOSURE_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TypeError, ValueError):
        _reject("runtime_closure_review_signing_input_malformed")
    return _signed_material(receipt_raw)


class VerifiedTransitionRuntimeClosureReview:
    """Opaque immutable result of one exact policy evaluation.

    Before using the result as authority, a consumer must pass it through
    ``require_verified_transition_runtime_closure_review`` with the externally obtained
    current policy and exact digest, then compare and bind the fresh result's policy digest,
    evaluation time, and ``bindings_digest`` to the gate's independently selected subject.
    A retained ``complete`` property is historical state, not authority.
    """

    __slots__ = (
        "review_digest",
        "signature_digest",
        "policy_digest",
        "externally_selected_trust_policy_digest",
        "trusted_public_key_digest",
        "bindings_digest",
        "evidence_digest",
        "evidence_state",
        "coverage_state",
        "selected_commit",
        "selected_tree",
        "decision",
        "reviewer_key_id",
        "issued_at",
        "valid_from",
        "valid_until",
        "evaluated_at",
        "complete_exact_runtime_closure",
        "_evidence_raw",
        "_artifact_raw_by_id",
        "_receipt_raw",
        "_signature_raw",
        "_trust_policy_raw",
        "_trusted_public_key_raw",
        "_expected_bindings_raw",
        "_integrity_digest",
        "_sealed",
    )

    def __init__(
            self,
            *,
            evidence: BoundTransitionRuntimeClosureEvidence,
            receipt: Mapping[str, Any],
            receipt_raw: bytes,
            signature_raw: bytes,
            policy: BoundExternalRuntimeClosureReviewTrustPolicy,
            public_key_raw: bytes,
            expected_bindings: Mapping[str, Any],
            externally_selected_trust_policy_digest: str,
            _authority: object) -> None:
        if _authority is not _VERIFIED_AUTHORITY:
            raise TypeError(
                "VerifiedTransitionRuntimeClosureReview requires external verification"
            )
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
        self.coverage_state = evidence["coverage"]["state"]
        self.selected_commit = receipt["selected_commit"]
        self.selected_tree = receipt["selected_tree"]
        self.decision = receipt["decision"]
        self.reviewer_key_id = receipt["reviewer_key_id"]
        self.issued_at = receipt["issued_at"]
        self.valid_from = receipt["valid_from"]
        self.valid_until = receipt["valid_until"]
        self.evaluated_at = policy["evaluated_at"]
        self.complete_exact_runtime_closure = (
            self.decision == RUNTIME_CLOSURE_REVIEW_COMPLETE
        )
        object.__setattr__(self, "_evidence_raw", evidence._bound_raw)
        object.__setattr__(self, "_artifact_raw_by_id", evidence._artifact_raw_by_id)
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
            raise AttributeError("VerifiedTransitionRuntimeClosureReview is immutable")
        object.__setattr__(self, name, value)

    @property
    def complete(self) -> bool:
        """Narrow closure decision; never implies workload adequacy or qualification."""

        return self.complete_exact_runtime_closure

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
            "coverage_state": self.coverage_state,
            "selected_commit": self.selected_commit,
            "selected_tree": self.selected_tree,
            "decision": self.decision,
            "reviewer_key_id": self.reviewer_key_id,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "evaluated_at": self.evaluated_at,
            "complete_exact_runtime_closure": self.complete_exact_runtime_closure,
        })


def verify_transition_runtime_closure_review(
        evidence: BoundTransitionRuntimeClosureEvidence,
        receipt_raw: bytes,
        signature_raw: bytes,
        trust_policy: BoundExternalRuntimeClosureReviewTrustPolicy,
        trusted_public_key_raw: bytes,
        expected_bindings: Mapping[str, Any],
        externally_selected_trust_policy_digest: str,
        ) -> VerifiedTransitionRuntimeClosureReview:
    """Verify relative to exact artifacts and an externally selected current policy digest."""

    try:
        bound_evidence = require_bound_transition_runtime_closure_evidence(evidence)
        receipt = validate_runtime_closure_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        signature = validate_runtime_closure_review_signature(
            parse_canonical_json_bytes(signature_raw, require_canonical=True)
        )
    except RuntimeClosureReviewError:
        raise
    except (TransitionContractError, TypeError, ValueError):
        _reject("runtime_closure_review_evidence_malformed")
    policy = require_bound_runtime_closure_review_trust_policy(trust_policy)
    try:
        bindings = validate_runtime_closure_review_bindings(dict(expected_bindings))
    except (TransitionContractError, TypeError, ValueError):
        _reject("runtime_closure_review_expected_bindings_malformed")
    try:
        selected_policy_digest = _digest(
            externally_selected_trust_policy_digest,
            "$.externally_selected_trust_policy_digest",
        )
    except (TransitionContractError, TypeError, ValueError):
        _reject("runtime_closure_review_policy_pin_malformed")
    if selected_policy_digest != policy.digest:
        _reject("runtime_closure_review_policy_pin_mismatch")
    if (
            type(trusted_public_key_raw) is not bytes
            or len(trusted_public_key_raw) != _ED25519_PUBLIC_KEY_BYTES
    ):
        _reject("runtime_closure_review_public_key_malformed")

    evidence_bindings = {
        "selected_commit": bound_evidence["selected_commit"],
        "selected_tree": bound_evidence["selected_tree"],
        **{
            field: bound_evidence[field]
            for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS
        },
        "runtime_closure_evidence_digest": bound_evidence.digest,
        "runtime_closure_evidence_state": bound_evidence["state"],
        "runtime_closure_coverage_state": bound_evidence["coverage"]["state"],
    }
    for field, expected in evidence_bindings.items():
        if receipt[field] != expected or bindings[field] != expected:
            _reject("runtime_closure_review_candidate_binding_mismatch")
    if receipt["reviewer_key_id"] in {
            bound_evidence["producer_id"],
            bound_evidence["runtime_collector_id"],
            bound_evidence["structural_tcb_producer_id"],
            bound_evidence["pack_producer_id"],
            bound_evidence["budget_proposer_id"],
            bound_evidence["release_builder_id"],
    }:
        _reject("runtime_closure_reviewer_producer_identity_conflict")
    if (
            receipt["decision"] == RUNTIME_CLOSURE_REVIEW_COMPLETE
            and (
                bound_evidence["state"] != RUNTIME_CLOSURE_EVIDENCE_READY
                or bound_evidence["coverage"]["state"] != RUNTIME_CLOSURE_COVERAGE_READY
            )
    ):
        _reject("runtime_closure_complete_requires_ready_evidence")

    review_digest = bytes_digest(receipt_raw)
    if (
            signature["payload_digest"] != review_digest
            or signature["signer_key_id"] != receipt["reviewer_key_id"]
    ):
        _reject("runtime_closure_review_signature_binding_mismatch")
    trusted_key = next(
        (
            item
            for item in policy["trusted_keys"]
            if item["key_id"] == receipt["reviewer_key_id"]
        ),
        None,
    )
    if (
            trusted_key is None
            or trusted_key["public_key_digest"] != bytes_digest(trusted_public_key_raw)
    ):
        _reject("runtime_closure_review_key_not_trusted")
    subject = {
        "selected_commit": receipt["selected_commit"],
        "selected_tree": receipt["selected_tree"],
        "runtime_closure_evidence_digest": receipt["runtime_closure_evidence_digest"],
    }
    if subject not in trusted_key["allowed_subjects"]:
        _reject("runtime_closure_review_subject_not_authorized")

    evaluated_at = _timestamp(policy["evaluated_at"], "$.evaluated_at")
    key_valid_from = _timestamp(trusted_key["valid_from"], "$.trusted_keys[].valid_from")
    key_valid_until = _timestamp(trusted_key["valid_until"], "$.trusted_keys[].valid_until")
    issued_at = _timestamp(receipt["issued_at"], "$.issued_at")
    if not key_valid_from <= evaluated_at <= key_valid_until:
        _reject("runtime_closure_review_key_not_valid_at_policy_time")
    if not key_valid_from <= issued_at <= key_valid_until:
        _reject("runtime_closure_review_key_not_valid_at_receipt_time")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        signature_bytes = base64.b64decode(signature["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(trusted_public_key_raw).verify(
            signature_bytes,
            _signed_material(receipt_raw),
        )
    except ImportError:
        _reject("runtime_closure_review_crypto_runtime_unavailable")
    except Exception:
        _reject("runtime_closure_review_signature_invalid")
    if review_digest in policy["revoked_receipt_digests"]:
        _reject("runtime_closure_review_receipt_revoked")
    valid_from = _timestamp(receipt["valid_from"], "$.valid_from")
    valid_until = _timestamp(receipt["valid_until"], "$.valid_until")
    if not valid_from <= evaluated_at <= valid_until:
        _reject("runtime_closure_review_receipt_not_current")

    return VerifiedTransitionRuntimeClosureReview(
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


def require_verified_transition_runtime_closure_review(
        value: Any,
        current_trust_policy: BoundExternalRuntimeClosureReviewTrustPolicy,
        externally_selected_current_trust_policy_digest: str,
        ) -> VerifiedTransitionRuntimeClosureReview:
    """Reverify retained bytes under the caller-selected current policy and return fresh authority.

    The selected digest is an explicit application trust-anchor input, not local proof of policy
    authenticity or organizational independence.  Every authority consumer must obtain the
    current policy and digest from authenticated external custody and call this function again,
    then compare the fresh result's ``bindings_digest`` to its independently selected candidate
    subject before binding any decision.
    """

    if type(value) is not VerifiedTransitionRuntimeClosureReview:
        _reject("detached_or_unverified_transition_runtime_closure_review")
    try:
        historical = verify_transition_runtime_closure_review(
            bind_transition_runtime_closure_evidence_bytes(
                value._evidence_raw,
                dict(value._artifact_raw_by_id),
            ),
            value._receipt_raw,
            value._signature_raw,
            bind_external_runtime_closure_review_trust_policy_bytes(
                value._trust_policy_raw
            ),
            value._trusted_public_key_raw,
            parse_canonical_json_bytes(value._expected_bindings_raw, require_canonical=True),
            value.externally_selected_trust_policy_digest,
        )
        intact = (
            historical._compute_integrity_digest() == value._compute_integrity_digest()
            and historical._integrity_digest == value._integrity_digest
            and historical._evidence_raw == value._evidence_raw
            and historical._artifact_raw_by_id == value._artifact_raw_by_id
            and historical._receipt_raw == value._receipt_raw
            and historical._signature_raw == value._signature_raw
            and historical._trust_policy_raw == value._trust_policy_raw
            and historical._trusted_public_key_raw == value._trusted_public_key_raw
            and historical._expected_bindings_raw == value._expected_bindings_raw
        )
    except (
            AttributeError,
            TransitionContractError,
            TypeError,
            ValueError,
            RuntimeClosureReviewError,
    ):
        intact = False
    if not intact:
        _reject("verified_transition_runtime_closure_review_mutated")
    current_policy = require_bound_runtime_closure_review_trust_policy(current_trust_policy)
    current_evaluated_at = _timestamp(current_policy["evaluated_at"], "$.evaluated_at")
    historical_evaluated_at = _timestamp(value.evaluated_at, "$.historical_evaluated_at")
    if current_evaluated_at < historical_evaluated_at:
        _reject("runtime_closure_review_policy_rollback")
    return verify_transition_runtime_closure_review(
        bind_transition_runtime_closure_evidence_bytes(
            value._evidence_raw,
            dict(value._artifact_raw_by_id),
        ),
        value._receipt_raw,
        value._signature_raw,
        current_policy,
        value._trusted_public_key_raw,
        parse_canonical_json_bytes(value._expected_bindings_raw, require_canonical=True),
        externally_selected_current_trust_policy_digest,
    )


__all__ = [
    "COVERAGE_BOOLEAN_FIELDS",
    "POSITIVE_COUNTER_FIELDS",
    "TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA",
    "RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS",
    "RUNTIME_CLOSURE_COVERAGE_ABSENT",
    "RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS",
    "RUNTIME_CLOSURE_COVERAGE_INCOMPLETE",
    "RUNTIME_CLOSURE_COVERAGE_READY",
    "RUNTIME_CLOSURE_DIGEST_ROLE_MAP",
    "RUNTIME_CLOSURE_EVIDENCE_ABSENT",
    "RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY",
    "RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE",
    "RUNTIME_CLOSURE_EVIDENCE_READY",
    "RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS",
    "RUNTIME_CLOSURE_REQUIRED_ARTIFACT_ROLES",
    "RUNTIME_CLOSURE_REVIEW_AUTHORIZATION_SCHEMA",
    "RUNTIME_CLOSURE_REVIEW_BINDINGS_SCHEMA",
    "RUNTIME_CLOSURE_REVIEW_COMPLETE",
    "RUNTIME_CLOSURE_REVIEW_INCOMPLETE",
    "RUNTIME_CLOSURE_REVIEW_POLICY_KIND",
    "RUNTIME_CLOSURE_REVIEW_PURPOSE",
    "RUNTIME_CLOSURE_REVIEW_RECEIPT_SCHEMA",
    "RUNTIME_CLOSURE_REVIEW_REVIEWER_KIND",
    "RUNTIME_CLOSURE_REVIEW_REVIEWER_ROLE",
    "RUNTIME_CLOSURE_REVIEW_SIGNATURE_ALGORITHM",
    "RUNTIME_CLOSURE_REVIEW_SIGNATURE_SCHEMA",
    "RUNTIME_CLOSURE_REVIEW_SUBSTRATE",
    "RUNTIME_CLOSURE_REVIEW_TRUST_POLICY_SCHEMA",
    "RUNTIME_CLOSURE_REVIEW_TRUSTED_KEY_SCHEMA",
    "RUNTIME_CLOSURE_SCOPE_KIND",
    "RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS",
    "BoundExternalRuntimeClosureReviewTrustPolicy",
    "BoundTransitionRuntimeClosureEvidence",
    "RuntimeClosureReviewError",
    "VerifiedTransitionRuntimeClosureReview",
    "ZERO_COUNTER_FIELDS",
    "bind_external_runtime_closure_review_trust_policy_bytes",
    "bind_transition_runtime_closure_evidence_bytes",
    "expected_runtime_closure_gaps",
    "require_bound_runtime_closure_review_trust_policy",
    "require_bound_transition_runtime_closure_evidence",
    "require_verified_transition_runtime_closure_review",
    "runtime_closure_review_signing_material",
    "validate_runtime_closure_review_bindings",
    "validate_runtime_closure_review_receipt",
    "validate_runtime_closure_review_signature",
    "validate_runtime_closure_review_trust_policy",
    "validate_transition_runtime_closure_evidence",
    "verify_transition_runtime_closure_review",
]
