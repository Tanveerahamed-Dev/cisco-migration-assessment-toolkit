"""Atlas Release 2 structural contracts and canonical TransitionCase boundary.

This module is additive to the Release 1 comparison/receipt implementation.  It deliberately
does not reinterpret ``cutover_gate/1`` or change any Release 1 canonical bytes.  Release 2 uses a
separate, closed encoding and process-local binding boundary so detached or non-canonical JSON
cannot acquire decision authority by convention.

R2.0 freezes structure only.  It does not claim that a case is qualified, independently replayable,
encrypted, or safely executable merely because the corresponding contract fields validate.
Those claims require the verifier, an external trust policy, and the later qualification gates.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Any, Iterable, Mapping


TRANSITION_CASE_SCHEMA = "atlas.transition-case/1"
TRANSITION_IDENTITY_SCHEMA = "atlas.transition-identity/1"
EVOLUTION_IR_SCHEMA = "atlas.evolution-ir/1"
OBLIGATION_SCHEMA = "atlas.transition-obligation/1"
OBSERVATION_PROFILE_SCHEMA = "atlas.observation-profile/1"
EVIDENCE_ATOM_SCHEMA = "atlas.evidence-atom/1"
COVERAGE_SCOPE_SCHEMA = "atlas.coverage-scope/1"
QUALIFICATION_DENOMINATOR_SCHEMA = "atlas.qualification-denominator/1"
TRANSFORM_STEP_SCHEMA = "atlas.evidence-transform/1"
APPLICABILITY_SCHEMA = "atlas.applicability/1"
PACK_BINDING_SCHEMA = "atlas.pack-binding/1"
DERIVATION_SCHEMA = "atlas.derivation/1"
REPLAY_CONTRACT_SCHEMA = "atlas.replay-contract/1"
OBJECT_BINDING_SCHEMA = "atlas.content-binding/1"
SECURITY_CONTRACT_SCHEMA = "atlas.security-contract/1"
VERSION_CONTRACT_SCHEMA = "atlas.version-contract/1"

CANONICAL_ENCODING = "ATLAS_CANONICAL_JSON/1"
TRANSITION_SEMANTICS_VERSION = "ATLAS_TRANSITION_SEMANTICS/1"
PACK_ABI_VERSION = "ATLAS_PACK_ABI/1"
WORDING_POLICY_VERSION = "ATLAS_ASSURANCE_WORDING/1"
CONTRACT_VERSION = "1.0.0"
EVOLUTION_IR_VERSION = "1.0.0"

# These are provisional parser safety guards for the first executable prototype, not the reviewed
# Pack/TCB resource budgets required for promotion.  R2.0 qualification remains blocked until the
# measured prototype census and an independent reviewer freeze those release-manifest budgets.
PROVISIONAL_MAX_CANONICAL_BYTES = 8 * 1024 * 1024
PROVISIONAL_MAX_CANONICAL_DEPTH = 64
PROVISIONAL_MAX_CANONICAL_NODES = 100_000
PROVISIONAL_MAX_STRING_BYTES = 1 * 1024 * 1024
PORTABLE_INTEGER_LIMIT = (1 << 53) - 1

_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,191}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_BOUND_TRANSITION_CASE_AUTHORITY = object()


class CaseMode(str, Enum):
    SEALED_PORTABLE = "SEALED_PORTABLE"
    REFERENCED = "REFERENCED"
    PROJECTION_ONLY = "PROJECTION_ONLY"


class EvidenceClass(str, Enum):
    OBSERVED = "observed"
    DECLARED = "declared"
    DERIVED = "derived"
    SIMULATED = "simulated"
    ASSUMED = "assumed"
    HUMAN_ACCEPTED = "human-accepted"


class ObservationMode(str, Enum):
    SAMPLED = "SAMPLED"
    EVENT_COMPLETE = "EVENT_COMPLETE"
    BOUNDED_MODEL = "BOUNDED_MODEL"


class TemporalOperator(str, Enum):
    AT_SAMPLE = "AT_SAMPLE"
    ALWAYS_DURING = "ALWAYS_DURING"
    NEVER_DURING = "NEVER_DURING"
    EVENTUALLY_WITHIN = "EVENTUALLY_WITHIN"
    SAMPLED_NO_VIOLATION_DURING = "SAMPLED_NO_VIOLATION_DURING"


class TemporalOutcome(str, Enum):
    SATISFIED_WITHIN_DECLARED_MODEL = "SATISFIED_WITHIN_DECLARED_MODEL"
    NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE = "NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE"
    VIOLATED = "VIOLATED"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class ApplicabilityKind(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    APPLICABILITY_EVIDENCE_REQUIRED = "APPLICABILITY_EVIDENCE_REQUIRED"
    APPLICABLE = "APPLICABLE"


class QualificationState(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthoritativeGate(str, Enum):
    OBSERVED_BREACH = "OBSERVED_BREACH"
    CONFLICT_REQUIRES_RESOLUTION = "CONFLICT_REQUIRES_RESOLUTION"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    ELIGIBLE_FOR_HUMAN_DECISION = "ELIGIBLE_FOR_HUMAN_DECISION"


class EvidenceEffect(str, Enum):
    SUPPORT = "SUPPORT"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"


class EvaluatorKind(str, Enum):
    STRUCTURAL_DECLARATIVE = "STRUCTURAL_DECLARATIVE"
    QUALIFIED_DECLARATIVE_PACK = "QUALIFIED_DECLARATIVE_PACK"
    CERTIFIED_WASM_PACK = "CERTIFIED_WASM_PACK"
    UNCERTIFIED_SEARCH_EXHAUSTED = "UNCERTIFIED_SEARCH_EXHAUSTED"


class RollbackDimension(str, Enum):
    INVERSE_PLANNED = "INVERSE_PLANNED"
    COMPENSATION_EXECUTABLE = "COMPENSATION_EXECUTABLE"
    CONFIGURATION_EQUIVALENCE_OBSERVED = "CONFIGURATION_EQUIVALENCE_OBSERVED"
    PROTOCOL_EQUIVALENCE_OBSERVED = "PROTOCOL_EQUIVALENCE_OBSERVED"
    SERVICE_EQUIVALENCE_OBSERVED = "SERVICE_EQUIVALENCE_OBSERVED"
    RESIDUAL_EFFECTS_PRESENT_OR_UNKNOWN = "RESIDUAL_EFFECTS_PRESENT_OR_UNKNOWN"


ROLLBACK_DIMENSIONS = tuple(item.value for item in RollbackDimension)


class TransitionContractError(ValueError):
    """A stable, non-echoing structural refusal.

    ``code`` and ``path`` are safe for deterministic verifier receipts.  The exception never
    includes hostile values or source paths in its message.
    """

    def __init__(self, code: str, path: str = "$") -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


class BoundTransitionCase(dict):
    """Process-local proof that one case came from exact canonical JSON bytes."""

    __slots__ = ("_bound_payload_digest", "_bound_source_digest", "_bound_source_bytes")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            payload_digest: str,
            source_digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _BOUND_TRANSITION_CASE_AUTHORITY:
            raise TypeError("BoundTransitionCase can only be minted from exact canonical bytes")
        super().__init__(value)
        self._bound_payload_digest = payload_digest
        self._bound_source_digest = source_digest
        self._bound_source_bytes = source_bytes

    @property
    def payload_digest(self) -> str:
        return self._bound_payload_digest

    @property
    def source_digest(self) -> str:
        return self._bound_source_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


def _reject(code: str, path: str = "$") -> None:
    raise TransitionContractError(code, path)


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def _validate_string(value: str, path: str) -> None:
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject("CANONICAL_INVALID_UNICODE", path)
    if len(encoded) > PROVISIONAL_MAX_STRING_BYTES:
        _reject("CANONICAL_STRING_LIMIT", path)
    if unicodedata.normalize("NFC", value) != value:
        _reject("CANONICAL_NON_NFC_STRING", path)


def _canonical_text(value: Any, path: str, depth: int, nodes: list[int]) -> str:
    if depth > PROVISIONAL_MAX_CANONICAL_DEPTH:
        _reject("CANONICAL_DEPTH_LIMIT", path)
    nodes[0] += 1
    if nodes[0] > PROVISIONAL_MAX_CANONICAL_NODES:
        _reject("CANONICAL_NODE_LIMIT", path)
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if not -PORTABLE_INTEGER_LIMIT <= value <= PORTABLE_INTEGER_LIMIT:
            _reject("CANONICAL_NON_PORTABLE_INTEGER", path)
        return str(value)
    if type(value) is str:
        _validate_string(value, path)
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if type(value) is list:
        return "[" + ",".join(
            _canonical_text(item, f"{path}[{index}]", depth + 1, nodes)
            for index, item in enumerate(value)
        ) + "]"
    if type(value) is dict:
        for key in value:
            if type(key) is not str:
                _reject("CANONICAL_NON_STRING_KEY", path)
            _validate_string(key, f"{path}.<key>")
        items = []
        for key in sorted(value, key=_utf16_sort_key):
            encoded_key = json.dumps(key, ensure_ascii=True, allow_nan=False)
            items.append(
                encoded_key + ":" + _canonical_text(value[key], f"{path}.{key}", depth + 1, nodes)
            )
        return "{" + ",".join(items) + "}"
    _reject("CANONICAL_UNSUPPORTED_TYPE", path)
    raise AssertionError("unreachable")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode the closed R2 JSON domain without fallback coercion or floating-point values."""

    text = _canonical_text(value, "$", 0, [0])
    raw = text.encode("ascii")
    if len(raw) > PROVISIONAL_MAX_CANONICAL_BYTES:
        _reject("CANONICAL_BYTE_LIMIT")
    return raw


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_digest(value: bytes) -> str:
    if type(value) is not bytes:
        raise TypeError("bytes_digest requires bytes")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _scan_json_nesting(raw: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > PROVISIONAL_MAX_CANONICAL_DEPTH:
                _reject("CANONICAL_DEPTH_LIMIT")
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _reject("CANONICAL_MALFORMED_JSON")
    if in_string or depth != 0:
        _reject("CANONICAL_MALFORMED_JSON")


def parse_canonical_json_bytes(raw: bytes, *, require_canonical: bool = True) -> Any:
    """Parse exact UTF-8 JSON while rejecting duplicates, floats, aliases, BOMs, and excess."""

    if type(raw) is not bytes:
        raise TypeError("canonical JSON source must be bytes")
    if not raw or len(raw) > PROVISIONAL_MAX_CANONICAL_BYTES:
        _reject("CANONICAL_BYTE_LIMIT")
    if raw.startswith(b"\xef\xbb\xbf"):
        _reject("CANONICAL_BOM_FORBIDDEN")
    _scan_json_nesting(raw)
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        _reject("CANONICAL_INVALID_UTF8")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _reject("CANONICAL_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_float(_: str) -> Any:
        _reject("CANONICAL_FLOAT_FORBIDDEN")

    def reject_constant(_: str) -> Any:
        _reject("CANONICAL_NONFINITE_FORBIDDEN")

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except TransitionContractError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, MemoryError):
        _reject("CANONICAL_MALFORMED_JSON")
    encoded = canonical_json_bytes(value)
    if require_canonical and encoded != raw:
        _reject("CANONICAL_BYTES_REQUIRED")
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        _reject("EXPECTED_OBJECT", path)
    return value


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], path: str) -> None:
    if set(value) != set(expected):
        _reject("CLOSED_SCHEMA_KEYS", path)


def _schema(value: Mapping[str, Any], expected: str, path: str) -> None:
    if value.get("schema") != expected:
        _reject("UNSUPPORTED_SCHEMA", f"{path}.schema")


def _text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _reject("EXPECTED_TEXT", path)
    _validate_string(value, path)
    return value


def _identifier(value: Any, path: str) -> str:
    text = _text(value, path)
    if not _IDENTIFIER_RE.fullmatch(text):
        _reject("INVALID_IDENTIFIER", path)
    return text


def _digest(value: Any, path: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, path)
    if not _DIGEST_RE.fullmatch(text):
        _reject("INVALID_SHA256_DIGEST", path)
    return text


def _enum(value: Any, enum_type: type[Enum], path: str) -> str:
    if type(value) is not str:
        _reject("UNKNOWN_ENUM_VALUE", path)
    try:
        enum_type(value)
    except ValueError:
        _reject("UNKNOWN_ENUM_VALUE", path)
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _reject("EXPECTED_BOOLEAN", path)
    return value


def _integer(value: Any, path: str, *, optional: bool = False, positive: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not -PORTABLE_INTEGER_LIMIT <= value <= PORTABLE_INTEGER_LIMIT:
        _reject("EXPECTED_PORTABLE_INTEGER", path)
    if positive and value <= 0:
        _reject("EXPECTED_POSITIVE_INTEGER", path)
    if not positive and value < 0:
        _reject("EXPECTED_NONNEGATIVE_INTEGER", path)
    return value


def _timestamp(value: Any, path: str) -> _datetime.datetime:
    text = _text(value, path)
    if not _TIMESTAMP_RE.fullmatch(text):
        _reject("TIMESTAMP_CANONICAL_UTC_REQUIRED", path)
    try:
        parsed = _datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        _reject("TIMESTAMP_INVALID", path)
    return parsed.replace(tzinfo=_datetime.timezone.utc)


def _array(value: Any, path: str) -> list[Any]:
    if type(value) is not list:
        _reject("EXPECTED_ARRAY", path)
    return value


def _sorted_unique_identifiers(value: Any, path: str, *, allow_empty: bool = False) -> list[str]:
    items = _array(value, path)
    if not allow_empty and not items:
        _reject("EMPTY_SET_FORBIDDEN", path)
    checked = [_identifier(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if checked != sorted(set(checked)):
        _reject("SORTED_UNIQUE_SET_REQUIRED", path)
    return checked


def _sorted_unique_digests(value: Any, path: str, *, allow_empty: bool = False) -> list[str]:
    items = _array(value, path)
    if not allow_empty and not items:
        _reject("EMPTY_SET_FORBIDDEN", path)
    checked = [_digest(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if checked != sorted(set(checked)):
        _reject("SORTED_UNIQUE_SET_REQUIRED", path)
    return [item for item in checked if item is not None]


def _time_interval(value: Any, path: str) -> tuple[_datetime.datetime, _datetime.datetime]:
    obj = _mapping(value, path)
    _exact_keys(obj, ("start_inclusive", "end_inclusive"), path)
    start = _timestamp(obj["start_inclusive"], f"{path}.start_inclusive")
    end = _timestamp(obj["end_inclusive"], f"{path}.end_inclusive")
    if start > end:
        _reject("TIME_INTERVAL_REVERSED", path)
    return start, end


_TRANSITION_IDENTITY_KEYS = (
    "schema",
    "engagement_id",
    "campaign_id",
    "pair_id",
    "before_snapshot_digest",
    "after_snapshot_digest",
    "protocol_id",
    "direction",
    "scenario_id",
    "wave_id",
    "transition_id",
    "trial_attempt_id",
)


def validate_transition_identity(value: Any, path: str = "$.transition_identity") -> dict[str, Any]:
    obj = _mapping(value, path)
    _exact_keys(obj, _TRANSITION_IDENTITY_KEYS, path)
    _schema(obj, TRANSITION_IDENTITY_SCHEMA, path)
    for key in (
        "engagement_id",
        "campaign_id",
        "pair_id",
        "protocol_id",
        "direction",
        "scenario_id",
        "wave_id",
        "transition_id",
        "trial_attempt_id",
    ):
        _identifier(obj[key], f"{path}.{key}")
    before = _digest(obj["before_snapshot_digest"], f"{path}.before_snapshot_digest")
    after = _digest(obj["after_snapshot_digest"], f"{path}.after_snapshot_digest")
    if before == after:
        _reject("PAIR_DIGESTS_MUST_DIFFER", path)
    return dict(obj)


def validate_obligation(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "obligation_id",
        "requirement_id",
        "predicate_id",
        "subject_ids",
        "state_ids",
        "temporal_operator",
        "mandatory",
        "window",
        "observation_profile_digest",
        "semantic_profile_digest",
        "accepted_evidence_classes",
        "rollback_dimension",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, OBLIGATION_SCHEMA, path)
    for key in ("obligation_id", "requirement_id", "predicate_id"):
        _identifier(obj[key], f"{path}.{key}")
    _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    _sorted_unique_identifiers(obj["state_ids"], f"{path}.state_ids")
    _enum(obj["temporal_operator"], TemporalOperator, f"{path}.temporal_operator")
    _boolean(obj["mandatory"], f"{path}.mandatory")
    _time_interval(obj["window"], f"{path}.window")
    _digest(obj["observation_profile_digest"], f"{path}.observation_profile_digest")
    _digest(obj["semantic_profile_digest"], f"{path}.semantic_profile_digest")
    evidence_classes = _array(obj["accepted_evidence_classes"], f"{path}.accepted_evidence_classes")
    if not evidence_classes:
        _reject("EMPTY_SET_FORBIDDEN", f"{path}.accepted_evidence_classes")
    checked_classes = [
        _enum(item, EvidenceClass, f"{path}.accepted_evidence_classes[{index}]")
        for index, item in enumerate(evidence_classes)
    ]
    if checked_classes != sorted(set(checked_classes)):
        _reject("SORTED_UNIQUE_SET_REQUIRED", f"{path}.accepted_evidence_classes")
    if obj["rollback_dimension"] is not None:
        _enum(obj["rollback_dimension"], RollbackDimension, f"{path}.rollback_dimension")
    return dict(obj)


def validate_evolution_ir(
        value: Any,
        transition_identity: Mapping[str, Any],
        path: str = "$.evolution_ir") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "ir_version",
        "transition_identity",
        "from_state_id",
        "to_state_id",
        "intermediate_state_ids",
        "subject_ids",
        "trigger_ids",
        "obligations",
        "rollback_dimensions",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, EVOLUTION_IR_SCHEMA, path)
    if obj["ir_version"] != EVOLUTION_IR_VERSION:
        _reject("UNSUPPORTED_EVOLUTION_IR_VERSION", f"{path}.ir_version")
    nested_identity = validate_transition_identity(obj["transition_identity"], f"{path}.transition_identity")
    if nested_identity != transition_identity:
        _reject("TRANSITION_IDENTITY_MISMATCH", f"{path}.transition_identity")
    from_state = _identifier(obj["from_state_id"], f"{path}.from_state_id")
    to_state = _identifier(obj["to_state_id"], f"{path}.to_state_id")
    if from_state == to_state:
        _reject("TRANSITION_STATES_MUST_DIFFER", path)
    intermediates = _sorted_unique_identifiers(
        obj["intermediate_state_ids"], f"{path}.intermediate_state_ids", allow_empty=True
    )
    if from_state in intermediates or to_state in intermediates:
        _reject("INTERMEDIATE_STATE_COLLISION", f"{path}.intermediate_state_ids")
    subjects = _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    _sorted_unique_identifiers(obj["trigger_ids"], f"{path}.trigger_ids", allow_empty=True)
    obligations = _array(obj["obligations"], f"{path}.obligations")
    if not obligations:
        _reject("OBLIGATIONS_REQUIRED", f"{path}.obligations")
    obligation_ids: list[str] = []
    requirement_ids: list[str] = []
    valid_states = {from_state, to_state, *intermediates}
    for index, obligation in enumerate(obligations):
        checked = validate_obligation(obligation, f"{path}.obligations[{index}]")
        obligation_ids.append(checked["obligation_id"])
        requirement_ids.append(checked["requirement_id"])
        if not set(checked["subject_ids"]).issubset(subjects):
            _reject("OBLIGATION_SUBJECT_SCOPE_MISMATCH", f"{path}.obligations[{index}].subject_ids")
        if not set(checked["state_ids"]).issubset(valid_states):
            _reject("OBLIGATION_STATE_SCOPE_MISMATCH", f"{path}.obligations[{index}].state_ids")
    if obligation_ids != sorted(set(obligation_ids)):
        _reject("SORTED_UNIQUE_OBLIGATION_IDS_REQUIRED", f"{path}.obligations")
    if len(requirement_ids) != len(set(requirement_ids)):
        _reject("DUPLICATE_REQUIREMENT_ID", f"{path}.obligations")
    rollback_dimensions = _array(obj["rollback_dimensions"], f"{path}.rollback_dimensions")
    if rollback_dimensions != list(ROLLBACK_DIMENSIONS):
        _reject("ROLLBACK_DIMENSIONS_CLOSED_SET_REQUIRED", f"{path}.rollback_dimensions")
    return dict(obj)


def validate_observation_profile(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "profile_id",
        "source_kind",
        "coverage_mode",
        "predicate_ids",
        "window",
        "planned_cadence_ms",
        "observed_maximum_gap_ms",
        "clock_error_bound_ms",
        "collection_completeness",
        "detection_latency_bound_ms",
        "cross_device_overlap_rule",
        "start_end_coverage",
        "missing_sample_policy",
        "qualification_denominator_digest",
        "qualification_receipt_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, OBSERVATION_PROFILE_SCHEMA, path)
    _identifier(obj["profile_id"], f"{path}.profile_id")
    _identifier(obj["source_kind"], f"{path}.source_kind")
    mode = _enum(obj["coverage_mode"], ObservationMode, f"{path}.coverage_mode")
    _sorted_unique_identifiers(obj["predicate_ids"], f"{path}.predicate_ids")
    _time_interval(obj["window"], f"{path}.window")
    cadence = _integer(obj["planned_cadence_ms"], f"{path}.planned_cadence_ms", optional=True, positive=True)
    max_gap = _integer(
        obj["observed_maximum_gap_ms"], f"{path}.observed_maximum_gap_ms", optional=True, positive=True
    )
    _integer(obj["clock_error_bound_ms"], f"{path}.clock_error_bound_ms")
    completeness = obj["collection_completeness"]
    if completeness not in ("COMPLETE", "INCOMPLETE", "UNKNOWN"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.collection_completeness")
    latency = _integer(
        obj["detection_latency_bound_ms"], f"{path}.detection_latency_bound_ms", optional=True
    )
    if obj["cross_device_overlap_rule"] not in (
            "NOT_APPLICABLE", "REQUIRE_OVERLAP_WITHIN_CLOCK_ERROR"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.cross_device_overlap_rule")
    if obj["start_end_coverage"] not in ("BOTH", "START_ONLY", "END_ONLY", "NEITHER"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.start_end_coverage")
    if obj["missing_sample_policy"] != "INCONCLUSIVE":
        _reject("MISSING_SAMPLE_MUST_BE_INCONCLUSIVE", f"{path}.missing_sample_policy")
    _digest(obj["qualification_denominator_digest"], f"{path}.qualification_denominator_digest")
    qualification_digest = _digest(
        obj["qualification_receipt_digest"], f"{path}.qualification_receipt_digest", optional=True
    )
    if mode == ObservationMode.SAMPLED.value:
        if cadence is None or max_gap is None:
            _reject("SAMPLED_PROFILE_CADENCE_REQUIRED", path)
    elif mode == ObservationMode.EVENT_COMPLETE.value:
        if completeness != "COMPLETE" or latency is None or obj["start_end_coverage"] != "BOTH":
            _reject("EVENT_COMPLETE_COVERAGE_REQUIRED", path)
        if qualification_digest is None:
            _reject("EVENT_COMPLETE_QUALIFICATION_REQUIRED", path)
    elif mode == ObservationMode.BOUNDED_MODEL.value:
        if cadence is not None or max_gap is not None:
            _reject("BOUNDED_MODEL_CADENCE_FORBIDDEN", path)
        if completeness != "COMPLETE" or obj["start_end_coverage"] != "BOTH":
            _reject("BOUNDED_MODEL_COVERAGE_REQUIRED", path)
        if qualification_digest is None:
            _reject("BOUNDED_MODEL_QUALIFICATION_REQUIRED", path)
    return dict(obj)


def validate_coverage_scope(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = ("schema", "denominator_kind", "subject_ids", "predicate_ids", "window", "complete")
    _exact_keys(obj, keys, path)
    _schema(obj, COVERAGE_SCOPE_SCHEMA, path)
    if obj["denominator_kind"] not in ("EXACT_SUBJECTS", "EXACT_EVENTS", "EXACT_MODEL_BOUND"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.denominator_kind")
    _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    _sorted_unique_identifiers(obj["predicate_ids"], f"{path}.predicate_ids")
    _time_interval(obj["window"], f"{path}.window")
    _boolean(obj["complete"], f"{path}.complete")
    return dict(obj)


def validate_qualification_denominator(value: Any, path: str) -> dict[str, Any]:
    """Validate an inspectable preimage for a qualification scope digest."""

    obj = _mapping(value, path)
    keys = (
        "schema",
        "denominator_id",
        "subject_kind",
        "subject_id",
        "subject_version",
        "denominator_kind",
        "subject_ids",
        "predicate_ids",
        "window",
        "platform_release_ids",
        "event_inventory_digest",
        "model_bound_digest",
        "assumption_set_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, QUALIFICATION_DENOMINATOR_SCHEMA, path)
    _identifier(obj["denominator_id"], f"{path}.denominator_id")
    subject_kind = obj["subject_kind"]
    if subject_kind not in (
            "APPLICABILITY_PROFILE", "BEHAVIOR_PACK", "OBSERVATION_PROFILE"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.subject_kind")
    _identifier(obj["subject_id"], f"{path}.subject_id")
    _identifier(obj["subject_version"], f"{path}.subject_version")
    denominator_kind = obj["denominator_kind"]
    allowed_kinds = {
        "APPLICABILITY_PROFILE": {"APPLICABILITY_SCOPE"},
        "BEHAVIOR_PACK": {"PACK_SUPPORTED_SCOPE"},
        "OBSERVATION_PROFILE": {"EXACT_SUBJECTS", "EXACT_EVENTS", "EXACT_MODEL_BOUND"},
    }
    if denominator_kind not in allowed_kinds[subject_kind]:
        _reject("DENOMINATOR_KIND_SUBJECT_MISMATCH", f"{path}.denominator_kind")
    subjects = _sorted_unique_identifiers(
        obj["subject_ids"], f"{path}.subject_ids", allow_empty=True
    )
    predicates = _sorted_unique_identifiers(
        obj["predicate_ids"], f"{path}.predicate_ids", allow_empty=True
    )
    window = obj["window"]
    if window is not None:
        _time_interval(window, f"{path}.window")
    platforms = _sorted_unique_identifiers(
        obj["platform_release_ids"], f"{path}.platform_release_ids", allow_empty=True
    )
    event_inventory = _digest(
        obj["event_inventory_digest"], f"{path}.event_inventory_digest", optional=True
    )
    model_bound = _digest(
        obj["model_bound_digest"], f"{path}.model_bound_digest", optional=True
    )
    assumption_set = _digest(
        obj["assumption_set_digest"], f"{path}.assumption_set_digest", optional=True
    )
    if subject_kind == "OBSERVATION_PROFILE" and (
            not subjects or not predicates or window is None):
        _reject("OBSERVATION_DENOMINATOR_SCOPE_REQUIRED", path)
    if subject_kind in ("APPLICABILITY_PROFILE", "BEHAVIOR_PACK") and not platforms:
        _reject("PLATFORM_RELEASE_DENOMINATOR_REQUIRED", path)
    if denominator_kind == "EXACT_EVENTS":
        if event_inventory is None or model_bound is not None or assumption_set is not None:
            _reject("EXACT_EVENTS_INVENTORY_REQUIRED", path)
    elif denominator_kind == "EXACT_MODEL_BOUND":
        if model_bound is None or assumption_set is None or event_inventory is not None:
            _reject("EXACT_MODEL_PREIMAGE_REQUIRED", path)
    elif any(item is not None for item in (event_inventory, model_bound, assumption_set)):
        _reject("DENOMINATOR_PREIMAGE_FIELD_FORBIDDEN", path)
    return dict(obj)


def validate_transform_step(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "input_digest",
        "output_digest",
        "transform_profile_digest",
        "transform_receipt_digest",
        "coverage_effect",
        "removed_predicate_ids",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, TRANSFORM_STEP_SCHEMA, path)
    input_digest = _digest(obj["input_digest"], f"{path}.input_digest")
    output_digest = _digest(obj["output_digest"], f"{path}.output_digest")
    _digest(obj["transform_profile_digest"], f"{path}.transform_profile_digest")
    _digest(obj["transform_receipt_digest"], f"{path}.transform_receipt_digest")
    if input_digest == output_digest:
        _reject("TRANSFORM_MUST_REMINT_BYTES", path)
    if obj["coverage_effect"] not in ("UNCHANGED", "NARROWED"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.coverage_effect")
    removed = _sorted_unique_identifiers(
        obj["removed_predicate_ids"], f"{path}.removed_predicate_ids", allow_empty=True
    )
    if obj["coverage_effect"] == "NARROWED" and not removed:
        _reject("NARROWED_COVERAGE_MUST_NAME_REMOVALS", path)
    if obj["coverage_effect"] == "UNCHANGED" and removed:
        _reject("UNCHANGED_COVERAGE_CANNOT_REMOVE_PREDICATES", path)
    return dict(obj)


def validate_evidence_atom(
        value: Any,
        transition_identity: Mapping[str, Any],
        valid_subjects: set[str],
        valid_states: set[str],
        profile_digests: Mapping[str, Mapping[str, Any]],
        path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "evidence_id",
        "artifact_digest",
        "transition_identity",
        "subject_id",
        "state_id",
        "predicate_id",
        "value",
        "observed_time_interval",
        "collected_at",
        "received_at",
        "sealed_at",
        "evidence_class",
        "acquisition_method",
        "observation_profile_digest",
        "semantic_profile_digest",
        "coverage_scope",
        "transform_chain",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, EVIDENCE_ATOM_SCHEMA, path)
    _identifier(obj["evidence_id"], f"{path}.evidence_id")
    artifact_digest = _digest(obj["artifact_digest"], f"{path}.artifact_digest")
    nested_identity = validate_transition_identity(obj["transition_identity"], f"{path}.transition_identity")
    if nested_identity != transition_identity:
        _reject("EVIDENCE_TELEPORTATION", f"{path}.transition_identity")
    subject = _identifier(obj["subject_id"], f"{path}.subject_id")
    state = _identifier(obj["state_id"], f"{path}.state_id")
    predicate = _identifier(obj["predicate_id"], f"{path}.predicate_id")
    if subject not in valid_subjects or state not in valid_states:
        _reject("EVIDENCE_SCOPE_MISMATCH", path)
    observed_start, observed_end = _time_interval(obj["observed_time_interval"], f"{path}.observed_time_interval")
    collected = _timestamp(obj["collected_at"], f"{path}.collected_at")
    received = _timestamp(obj["received_at"], f"{path}.received_at")
    sealed = _timestamp(obj["sealed_at"], f"{path}.sealed_at")
    if not observed_end <= collected <= received <= sealed:
        _reject("EVIDENCE_TIME_ORDER_INVALID", path)
    _enum(obj["evidence_class"], EvidenceClass, f"{path}.evidence_class")
    _identifier(obj["acquisition_method"], f"{path}.acquisition_method")
    profile_digest = _digest(obj["observation_profile_digest"], f"{path}.observation_profile_digest")
    _digest(obj["semantic_profile_digest"], f"{path}.semantic_profile_digest")
    if profile_digest not in profile_digests:
        _reject("UNKNOWN_OBSERVATION_PROFILE_DIGEST", f"{path}.observation_profile_digest")
    profile = profile_digests[profile_digest]
    profile_start, profile_end = _time_interval(profile["window"], "$.observation_profiles[].window")
    if observed_start < profile_start or observed_end > profile_end:
        _reject("EVIDENCE_OUTSIDE_OBSERVATION_WINDOW", f"{path}.observed_time_interval")
    if predicate not in profile["predicate_ids"]:
        _reject("EVIDENCE_PREDICATE_PROFILE_MISMATCH", f"{path}.predicate_id")
    scope = validate_coverage_scope(obj["coverage_scope"], f"{path}.coverage_scope")
    if subject not in scope["subject_ids"] or predicate not in scope["predicate_ids"]:
        _reject("EVIDENCE_COVERAGE_SCOPE_MISMATCH", f"{path}.coverage_scope")
    if scope["window"] != profile["window"]:
        _reject("EVIDENCE_COVERAGE_WINDOW_MISMATCH", f"{path}.coverage_scope.window")
    chain = _array(obj["transform_chain"], f"{path}.transform_chain")
    prior_output: str | None = None
    for index, step in enumerate(chain):
        checked = validate_transform_step(step, f"{path}.transform_chain[{index}]")
        if prior_output is not None and checked["input_digest"] != prior_output:
            _reject("TRANSFORM_CHAIN_DISCONNECTED", f"{path}.transform_chain[{index}]")
        prior_output = checked["output_digest"]
    if prior_output is not None and prior_output != artifact_digest:
        _reject("TRANSFORM_OUTPUT_ARTIFACT_MISMATCH", f"{path}.artifact_digest")
    # Validate that the opaque typed value itself is in the closed canonical domain.
    canonical_json_bytes(obj["value"])
    return dict(obj)


def validate_applicability(value: Any, path: str = "$.applicability") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "kind",
        "reason_codes",
        "profile_id",
        "profile_digest",
        "supported_denominator_digest",
        "qualification_receipt_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, APPLICABILITY_SCHEMA, path)
    kind = _enum(obj["kind"], ApplicabilityKind, f"{path}.kind")
    reasons = _sorted_unique_identifiers(obj["reason_codes"], f"{path}.reason_codes", allow_empty=True)
    if kind == ApplicabilityKind.APPLICABLE.value:
        if reasons:
            _reject("APPLICABLE_REASON_CODES_FORBIDDEN", f"{path}.reason_codes")
        _identifier(obj["profile_id"], f"{path}.profile_id")
        _digest(obj["profile_digest"], f"{path}.profile_digest")
        _digest(obj["supported_denominator_digest"], f"{path}.supported_denominator_digest")
        _digest(obj["qualification_receipt_digest"], f"{path}.qualification_receipt_digest")
    else:
        if not reasons:
            _reject("APPLICABILITY_REASON_REQUIRED", f"{path}.reason_codes")
        if any(obj[key] is not None for key in (
                "profile_id", "profile_digest", "supported_denominator_digest",
                "qualification_receipt_digest")):
            _reject("NON_APPLICABLE_PROFILE_FIELDS_FORBIDDEN", path)
    return dict(obj)


def validate_pack_binding(value: Any, path: str = "$.pack_binding") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "pack_id",
        "pack_version",
        "pack_manifest_digest",
        "tcb_manifest_digest",
        "semantic_bundle_digest",
        "pack_qualification_receipt_digest",
        "abi_version",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, PACK_BINDING_SCHEMA, path)
    _identifier(obj["pack_id"], f"{path}.pack_id")
    _identifier(obj["pack_version"], f"{path}.pack_version")
    for key in (
            "pack_manifest_digest",
            "tcb_manifest_digest",
            "semantic_bundle_digest",
            "pack_qualification_receipt_digest",
    ):
        _digest(
            obj[key],
            f"{path}.{key}",
            optional=(key == "pack_qualification_receipt_digest"),
        )
    if obj["abi_version"] != PACK_ABI_VERSION:
        _reject("UNSUPPORTED_PACK_ABI", f"{path}.abi_version")
    return dict(obj)


def validate_derivation(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "derivation_id",
        "obligation_id",
        "evidence_ids",
        "effect",
        "temporal_outcome",
        "evaluator_kind",
        "evaluator_digest",
        "certificate_digest",
        "reason_codes",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, DERIVATION_SCHEMA, path)
    _identifier(obj["derivation_id"], f"{path}.derivation_id")
    _identifier(obj["obligation_id"], f"{path}.obligation_id")
    _sorted_unique_identifiers(obj["evidence_ids"], f"{path}.evidence_ids")
    _enum(obj["effect"], EvidenceEffect, f"{path}.effect")
    _enum(obj["temporal_outcome"], TemporalOutcome, f"{path}.temporal_outcome")
    evaluator_kind = _enum(obj["evaluator_kind"], EvaluatorKind, f"{path}.evaluator_kind")
    _digest(obj["evaluator_digest"], f"{path}.evaluator_digest")
    certificate = _digest(obj["certificate_digest"], f"{path}.certificate_digest", optional=True)
    _sorted_unique_identifiers(obj["reason_codes"], f"{path}.reason_codes", allow_empty=True)
    if evaluator_kind in (
            EvaluatorKind.QUALIFIED_DECLARATIVE_PACK.value,
            EvaluatorKind.CERTIFIED_WASM_PACK.value,
    ) and certificate is None:
        _reject("EVALUATOR_CERTIFICATE_REQUIRED", f"{path}.certificate_digest")
    if evaluator_kind == EvaluatorKind.UNCERTIFIED_SEARCH_EXHAUSTED.value and certificate is not None:
        _reject("UNCERTIFIED_SEARCH_CERTIFICATE_FORBIDDEN", f"{path}.certificate_digest")
    return dict(obj)


def validate_replay_contract(value: Any, case_mode: str, path: str = "$.replay_contract") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "mode",
        "object_bindings",
        "verifier_bootstrap_digest",
        "trust_policy_digest",
        "replay_recipe_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, REPLAY_CONTRACT_SCHEMA, path)
    mode = _enum(obj["mode"], CaseMode, f"{path}.mode")
    if mode != case_mode:
        _reject("CASE_MODE_MISMATCH", f"{path}.mode")
    for key in ("verifier_bootstrap_digest", "trust_policy_digest", "replay_recipe_digest"):
        _digest(obj[key], f"{path}.{key}")
    bindings = _array(obj["object_bindings"], f"{path}.object_bindings")
    roles = {
        "EVIDENCE",
        "SEMANTIC_BUNDLE",
        "PACK_MANIFEST",
        "TCB_MANIFEST",
        "PARSER",
        "NORMALIZER",
        "RUNTIME_DEPENDENCY",
        "TRUST_SNAPSHOT",
        "QUALIFICATION_RECEIPT",
        "REPLAY_RECIPE",
        "STATE_SNAPSHOT",
        "VERIFIER_BOOTSTRAP",
        "VERIFIER_RECEIPT",
    }
    locations = {"EMBEDDED", "EXTERNAL", "PROJECTION"}
    binding_keys: list[tuple[str, str]] = []
    for index, binding in enumerate(bindings):
        item_path = f"{path}.object_bindings[{index}]"
        item = _mapping(binding, item_path)
        _exact_keys(item, ("schema", "role", "digest", "location", "resolver_id", "required"), item_path)
        _schema(item, OBJECT_BINDING_SCHEMA, item_path)
        if item["role"] not in roles:
            _reject("UNKNOWN_CONTENT_ROLE", f"{item_path}.role")
        digest = _digest(item["digest"], f"{item_path}.digest")
        if item["location"] not in locations:
            _reject("UNKNOWN_CONTENT_LOCATION", f"{item_path}.location")
        _boolean(item["required"], f"{item_path}.required")
        resolver = item["resolver_id"]
        if item["location"] == "EXTERNAL":
            _identifier(resolver, f"{item_path}.resolver_id")
        elif resolver is not None:
            _reject("RESOLVER_ONLY_FOR_EXTERNAL_CONTENT", f"{item_path}.resolver_id")
        if mode == CaseMode.SEALED_PORTABLE.value and item["required"] and item["location"] != "EMBEDDED":
            _reject("SEALED_REQUIRED_CONTENT_NOT_EMBEDDED", item_path)
        if mode == CaseMode.PROJECTION_ONLY.value and item["location"] != "PROJECTION":
            _reject("PROJECTION_CONTENT_LOCATION_REQUIRED", item_path)
        binding_keys.append((item["role"], digest or ""))
    if binding_keys != sorted(set(binding_keys)):
        _reject("SORTED_UNIQUE_CONTENT_BINDINGS_REQUIRED", f"{path}.object_bindings")
    return dict(obj)


def validate_security_contract(value: Any, path: str = "$.security_contract") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "classification",
        "evidence_protection",
        "recipient_policy_digest",
        "encryption_profile_digest",
        "redaction_profile_digest",
        "key_policy_digest",
        "retention_policy_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, SECURITY_CONTRACT_SCHEMA, path)
    if obj["classification"] not in ("PUBLIC", "INTERNAL", "RESTRICTED"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.classification")
    if obj["evidence_protection"] not in (
            "PLAINTEXT_POLICY_APPROVED", "AEAD_ENCRYPTED", "REDACTED_DERIVATIVE", "CONTRACT_ONLY"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.evidence_protection")
    recipient = _digest(obj["recipient_policy_digest"], f"{path}.recipient_policy_digest", optional=True)
    encryption = _digest(obj["encryption_profile_digest"], f"{path}.encryption_profile_digest", optional=True)
    redaction = _digest(obj["redaction_profile_digest"], f"{path}.redaction_profile_digest", optional=True)
    key_policy = _digest(obj["key_policy_digest"], f"{path}.key_policy_digest", optional=True)
    _digest(obj["retention_policy_digest"], f"{path}.retention_policy_digest")
    protection = obj["evidence_protection"]
    if protection == "AEAD_ENCRYPTED" and None in (recipient, encryption, key_policy):
        _reject("AEAD_POLICY_BINDINGS_REQUIRED", path)
    if protection == "REDACTED_DERIVATIVE" and redaction is None:
        _reject("REDACTION_PROFILE_REQUIRED", path)
    if obj["classification"] == "RESTRICTED" and protection not in (
            "AEAD_ENCRYPTED", "CONTRACT_ONLY"):
        _reject("RESTRICTED_EVIDENCE_PROTECTION_REQUIRED", path)
    return dict(obj)


def validate_version_contract(value: Any, path: str = "$.version_contract") -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "contract_version",
        "canonical_encoding",
        "semantic_version",
        "pack_abi_version",
        "wording_policy_version",
        "migration_policy",
        "invalidation_policy",
        "replay_policy",
        "qualification_policy",
        "legacy_semantics_digest",
        "dependency_digests",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, VERSION_CONTRACT_SCHEMA, path)
    expected = {
        "contract_version": CONTRACT_VERSION,
        "canonical_encoding": CANONICAL_ENCODING,
        "semantic_version": TRANSITION_SEMANTICS_VERSION,
        "pack_abi_version": PACK_ABI_VERSION,
        "wording_policy_version": WORDING_POLICY_VERSION,
        "migration_policy": "REFERENCE_NOT_REWRITE",
        "invalidation_policy": "DIGEST_CHANGE_INVALIDATES_DEPENDENTS",
        "replay_policy": "PINNED_SEMANTICS_EXACT_BYTES",
        "qualification_policy": "EXTERNAL_TRUST_POLICY_AT_EVALUATION_TIME",
    }
    for key, expected_value in expected.items():
        if obj[key] != expected_value:
            _reject("UNSUPPORTED_VERSION_CONTRACT", f"{path}.{key}")
    _digest(obj["legacy_semantics_digest"], f"{path}.legacy_semantics_digest", optional=True)
    dependencies = _array(obj["dependency_digests"], f"{path}.dependency_digests")
    kinds = {
        "CONTRACT",
        "SEMANTIC_PROFILE",
        "OBSERVATION_PROFILE",
        "PACK",
        "TCB",
        "PARSER",
        "NORMALIZER",
        "QUALIFICATION",
        "QUALIFICATION_DENOMINATOR",
        "TRUST_POLICY",
        "WORDING_POLICY",
        "LEGACY_SEMANTICS",
    }
    keys_seen: list[tuple[str, str]] = []
    for index, dependency in enumerate(dependencies):
        item_path = f"{path}.dependency_digests[{index}]"
        item = _mapping(dependency, item_path)
        _exact_keys(item, ("kind", "identifier", "digest"), item_path)
        if item["kind"] not in kinds:
            _reject("UNKNOWN_DEPENDENCY_KIND", f"{item_path}.kind")
        identifier = _identifier(item["identifier"], f"{item_path}.identifier")
        _digest(item["digest"], f"{item_path}.digest")
        keys_seen.append((item["kind"], identifier))
    if keys_seen != sorted(set(keys_seen)):
        _reject("SORTED_UNIQUE_DEPENDENCIES_REQUIRED", f"{path}.dependency_digests")
    return dict(obj)


_TRANSITION_CASE_KEYS = (
    "schema",
    "case_id",
    "case_mode",
    "created_at",
    "transition_identity",
    "evolution_ir",
    "qualification_denominators",
    "observation_profiles",
    "evidence_atoms",
    "applicability",
    "pack_binding",
    "derivations",
    "replay_contract",
    "security_contract",
    "version_contract",
)


def validate_transition_case(value: Any) -> dict[str, Any]:
    """Validate the closed R2.0 case and every cross-object identity/digest join."""

    # Run the canonical-domain walk even for an in-memory value so floats, aliases, and non-JSON
    # objects fail before any structural field is considered.
    canonical_json_bytes(value)
    obj = _mapping(value, "$")
    _exact_keys(obj, _TRANSITION_CASE_KEYS, "$")
    _schema(obj, TRANSITION_CASE_SCHEMA, "$")
    _identifier(obj["case_id"], "$.case_id")
    case_mode = _enum(obj["case_mode"], CaseMode, "$.case_mode")
    _timestamp(obj["created_at"], "$.created_at")
    identity = validate_transition_identity(obj["transition_identity"])
    ir = validate_evolution_ir(obj["evolution_ir"], identity)
    valid_subjects = set(ir["subject_ids"])
    valid_states = {ir["from_state_id"], ir["to_state_id"], *ir["intermediate_state_ids"]}

    denominators = _array(obj["qualification_denominators"], "$.qualification_denominators")
    denominator_ids: list[str] = []
    denominator_digests: dict[str, Mapping[str, Any]] = {}
    for index, denominator in enumerate(denominators):
        checked = validate_qualification_denominator(
            denominator, f"$.qualification_denominators[{index}]"
        )
        denominator_ids.append(checked["denominator_id"])
        digest = canonical_digest(checked)
        if digest in denominator_digests:
            _reject("DUPLICATE_QUALIFICATION_DENOMINATOR_DIGEST", "$.qualification_denominators")
        denominator_digests[digest] = checked
    if denominator_ids != sorted(set(denominator_ids)):
        _reject("SORTED_UNIQUE_DENOMINATOR_IDS_REQUIRED", "$.qualification_denominators")

    profiles = _array(obj["observation_profiles"], "$.observation_profiles")
    profile_ids: list[str] = []
    profile_digests: dict[str, Mapping[str, Any]] = {}
    for index, profile in enumerate(profiles):
        checked = validate_observation_profile(profile, f"$.observation_profiles[{index}]")
        profile_ids.append(checked["profile_id"])
        digest = canonical_digest(checked)
        if digest in profile_digests:
            _reject("DUPLICATE_OBSERVATION_PROFILE_DIGEST", "$.observation_profiles")
        profile_digests[digest] = checked
        denominator = denominator_digests.get(checked["qualification_denominator_digest"])
        if denominator is None:
            _reject(
                "OBSERVATION_QUALIFICATION_DENOMINATOR_MISSING",
                f"$.observation_profiles[{index}].qualification_denominator_digest",
            )
        expected_denominator_kind = {
            ObservationMode.SAMPLED.value: "EXACT_SUBJECTS",
            ObservationMode.EVENT_COMPLETE.value: "EXACT_EVENTS",
            ObservationMode.BOUNDED_MODEL.value: "EXACT_MODEL_BOUND",
        }[checked["coverage_mode"]]
        if (
                denominator["subject_kind"] != "OBSERVATION_PROFILE"
                or denominator["subject_id"] != checked["profile_id"]
                or denominator["subject_version"] != "1"
                or denominator["denominator_kind"] != expected_denominator_kind
                or denominator["predicate_ids"] != checked["predicate_ids"]
                or denominator["window"] != checked["window"]
        ):
            _reject("OBSERVATION_QUALIFICATION_DENOMINATOR_MISMATCH", f"$.observation_profiles[{index}]")
    if profile_ids != sorted(set(profile_ids)):
        _reject("SORTED_UNIQUE_PROFILE_IDS_REQUIRED", "$.observation_profiles")

    obligations = {item["obligation_id"]: item for item in ir["obligations"]}
    for obligation_id, obligation in obligations.items():
        if obligation["observation_profile_digest"] not in profile_digests:
            _reject("OBLIGATION_PROFILE_DIGEST_UNKNOWN", f"$.evolution_ir.obligations.{obligation_id}")
        profile = profile_digests[obligation["observation_profile_digest"]]
        if obligation["predicate_id"] not in profile["predicate_ids"]:
            _reject("OBLIGATION_PREDICATE_PROFILE_MISMATCH", f"$.evolution_ir.obligations.{obligation_id}")
        if obligation["window"] != profile["window"]:
            _reject("OBLIGATION_WINDOW_PROFILE_MISMATCH", f"$.evolution_ir.obligations.{obligation_id}")
        denominator = denominator_digests[profile["qualification_denominator_digest"]]
        if not set(obligation["subject_ids"]).issubset(denominator["subject_ids"]):
            _reject(
                "OBLIGATION_QUALIFICATION_DENOMINATOR_SCOPE_MISMATCH",
                f"$.evolution_ir.obligations.{obligation_id}.subject_ids",
            )

    atoms = _array(obj["evidence_atoms"], "$.evidence_atoms")
    evidence_ids: list[str] = []
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for index, atom in enumerate(atoms):
        checked = validate_evidence_atom(
            atom,
            identity,
            valid_subjects,
            valid_states,
            profile_digests,
            f"$.evidence_atoms[{index}]",
        )
        evidence_id = checked["evidence_id"]
        evidence_ids.append(evidence_id)
        evidence_by_id[evidence_id] = checked
        profile = profile_digests[checked["observation_profile_digest"]]
        denominator = denominator_digests[profile["qualification_denominator_digest"]]
        scope = checked["coverage_scope"]
        if (
                denominator["denominator_kind"] != scope["denominator_kind"]
                or denominator["subject_ids"] != scope["subject_ids"]
                or denominator["predicate_ids"] != scope["predicate_ids"]
                or denominator["window"] != scope["window"]
        ):
            _reject("EVIDENCE_QUALIFICATION_DENOMINATOR_MISMATCH", f"$.evidence_atoms[{index}]")
    if evidence_ids != sorted(set(evidence_ids)):
        _reject("SORTED_UNIQUE_EVIDENCE_IDS_REQUIRED", "$.evidence_atoms")

    applicability = validate_applicability(obj["applicability"])
    applicability_denominator: Mapping[str, Any] | None = None
    if applicability["kind"] == ApplicabilityKind.APPLICABLE.value:
        denominator = denominator_digests.get(applicability["supported_denominator_digest"])
        if (
                denominator is None
                or denominator["subject_kind"] != "APPLICABILITY_PROFILE"
                or denominator["subject_id"] != applicability["profile_id"]
                or denominator["subject_version"] != "1"
        ):
            _reject("APPLICABILITY_QUALIFICATION_DENOMINATOR_MISMATCH", "$.applicability")
        applicability_denominator = denominator
    pack_binding = validate_pack_binding(obj["pack_binding"])
    pack_denominators = [
        (digest, denominator)
        for digest, denominator in denominator_digests.items()
        if denominator["subject_kind"] == "BEHAVIOR_PACK"
        and denominator["subject_id"] == pack_binding["pack_id"]
        and denominator["subject_version"] == pack_binding["pack_version"]
    ]
    if len(pack_denominators) != 1:
        _reject("PACK_QUALIFICATION_DENOMINATOR_MISMATCH", "$.pack_binding")
    pack_denominator = pack_denominators[0][1]
    if (
            applicability_denominator is not None
            and applicability_denominator["platform_release_ids"]
            != pack_denominator["platform_release_ids"]
    ):
        _reject("PACK_APPLICABILITY_PLATFORM_DENOMINATOR_MISMATCH", "$.pack_binding")

    derivations = _array(obj["derivations"], "$.derivations")
    derivation_ids: list[str] = []
    for index, derivation in enumerate(derivations):
        checked = validate_derivation(derivation, f"$.derivations[{index}]")
        derivation_ids.append(checked["derivation_id"])
        obligation = obligations.get(checked["obligation_id"])
        if obligation is None:
            _reject("DERIVATION_OBLIGATION_UNKNOWN", f"$.derivations[{index}].obligation_id")
        observation_profile = profile_digests[obligation["observation_profile_digest"]]
        if (
                observation_profile["coverage_mode"] == ObservationMode.SAMPLED.value
                and checked["temporal_outcome"] == TemporalOutcome.SATISFIED_WITHIN_DECLARED_MODEL.value
        ):
            _reject("SAMPLED_PROFILE_CANNOT_SATISFY_DECLARED_MODEL", f"$.derivations[{index}]")
        if (
                checked["temporal_outcome"]
                == TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value
                and observation_profile["coverage_mode"] != ObservationMode.SAMPLED.value
        ):
            _reject("SAMPLED_TRACE_OUTCOME_REQUIRES_SAMPLED_PROFILE", f"$.derivations[{index}]")
        if not set(checked["evidence_ids"]).issubset(evidence_by_id):
            _reject("DERIVATION_EVIDENCE_UNKNOWN", f"$.derivations[{index}].evidence_ids")
        for evidence_id in checked["evidence_ids"]:
            atom = evidence_by_id[evidence_id]
            if atom["subject_id"] not in obligation["subject_ids"]:
                _reject("DERIVATION_EVIDENCE_SUBJECT_MISMATCH", f"$.derivations[{index}]")
            if atom["state_id"] not in obligation["state_ids"]:
                _reject("DERIVATION_EVIDENCE_STATE_MISMATCH", f"$.derivations[{index}]")
            if atom["predicate_id"] != obligation["predicate_id"]:
                _reject("DERIVATION_EVIDENCE_PREDICATE_MISMATCH", f"$.derivations[{index}]")
            if atom["semantic_profile_digest"] != obligation["semantic_profile_digest"]:
                _reject("DERIVATION_SEMANTIC_PROFILE_MISMATCH", f"$.derivations[{index}]")
            if atom["evidence_class"] not in obligation["accepted_evidence_classes"]:
                _reject("DERIVATION_EVIDENCE_CLASS_NOT_ACCEPTED", f"$.derivations[{index}]")
        if checked["evaluator_digest"] != pack_binding["semantic_bundle_digest"]:
            _reject("DERIVATION_EVALUATOR_BINDING_MISMATCH", f"$.derivations[{index}]")
    if derivation_ids != sorted(set(derivation_ids)):
        _reject("SORTED_UNIQUE_DERIVATION_IDS_REQUIRED", "$.derivations")

    replay = validate_replay_contract(obj["replay_contract"], case_mode)
    validate_security_contract(obj["security_contract"])
    version = validate_version_contract(obj["version_contract"])

    content_bindings = {
        (item["role"], item["digest"]): item
        for item in replay["object_bindings"]
    }

    def require_authority_binding(role: str, digest: str | None, code: str) -> None:
        if digest is None:
            return
        binding = content_bindings.get((role, digest))
        if binding is None or binding["required"] is not True:
            _reject(code, "$.replay_contract.object_bindings")

    for atom in atoms:
        require_authority_binding(
            "EVIDENCE",
            atom["artifact_digest"],
            "EVIDENCE_CONTENT_BINDING_MISSING",
        )
    required_pack_bindings = {
        ("PACK_MANIFEST", pack_binding["pack_manifest_digest"]),
        ("TCB_MANIFEST", pack_binding["tcb_manifest_digest"]),
        ("SEMANTIC_BUNDLE", pack_binding["semantic_bundle_digest"]),
        ("QUALIFICATION_RECEIPT", pack_binding["pack_qualification_receipt_digest"]),
        ("QUALIFICATION_RECEIPT", applicability["qualification_receipt_digest"]),
    }
    for role, digest in required_pack_bindings:
        require_authority_binding(role, digest, "AUTHORITY_CONTENT_BINDING_MISSING")
    for profile in profiles:
        require_authority_binding(
            "QUALIFICATION_RECEIPT",
            profile["qualification_receipt_digest"],
            "OBSERVATION_QUALIFICATION_CONTENT_BINDING_MISSING",
        )
    require_authority_binding(
        "STATE_SNAPSHOT",
        identity["before_snapshot_digest"],
        "STATE_SNAPSHOT_CONTENT_BINDING_MISSING",
    )
    require_authority_binding(
        "STATE_SNAPSHOT",
        identity["after_snapshot_digest"],
        "STATE_SNAPSHOT_CONTENT_BINDING_MISSING",
    )
    require_authority_binding(
        "VERIFIER_BOOTSTRAP",
        replay["verifier_bootstrap_digest"],
        "VERIFIER_BOOTSTRAP_CONTENT_BINDING_MISSING",
    )
    require_authority_binding(
        "TRUST_SNAPSHOT",
        replay["trust_policy_digest"],
        "TRUST_POLICY_CONTENT_BINDING_MISSING",
    )
    require_authority_binding(
        "REPLAY_RECIPE",
        replay["replay_recipe_digest"],
        "REPLAY_RECIPE_CONTENT_BINDING_MISSING",
    )

    for obligation in ir["obligations"]:
        if obligation["semantic_profile_digest"] != pack_binding["semantic_bundle_digest"]:
            _reject(
                "OBLIGATION_SEMANTIC_PROFILE_PACK_MISMATCH",
                "$.evolution_ir.obligations",
            )

    dependency_values = {(item["kind"], item["identifier"], item["digest"])
                         for item in version["dependency_digests"]}
    mandatory_dependencies = {
        ("PACK", pack_binding["pack_id"], pack_binding["pack_manifest_digest"]),
        ("TCB", pack_binding["pack_id"], pack_binding["tcb_manifest_digest"]),
        ("SEMANTIC_PROFILE", pack_binding["pack_id"], pack_binding["semantic_bundle_digest"]),
        ("WORDING_POLICY", WORDING_POLICY_VERSION, wording_policy_digest()),
        *(
            ("QUALIFICATION_DENOMINATOR", item["denominator_id"], digest)
            for digest, item in denominator_digests.items()
        ),
    }
    if not mandatory_dependencies.issubset(dependency_values):
        _reject("MANDATORY_INVALIDATION_DEPENDENCY_MISSING", "$.version_contract.dependency_digests")
    return dict(obj)


def bind_transition_case_bytes(raw: bytes) -> BoundTransitionCase:
    """Validate and bind one exact canonical TransitionCase byte string."""

    value = parse_canonical_json_bytes(raw, require_canonical=True)
    checked = validate_transition_case(value)
    payload_digest = canonical_digest(checked)
    source_digest = bytes_digest(raw)
    if payload_digest != source_digest:
        # Canonical source and canonical payload are the same bytes; keep this as an executable
        # invariant so future decoder changes cannot silently split them.
        _reject("CANONICAL_SOURCE_PAYLOAD_DIVERGED")
    return BoundTransitionCase(
        checked,
        payload_digest=payload_digest,
        source_digest=source_digest,
        source_bytes=len(raw),
        _authority=_BOUND_TRANSITION_CASE_AUTHORITY,
    )


def require_bound_transition_case(value: Any) -> BoundTransitionCase:
    """Require an unchanged case minted by :func:`bind_transition_case_bytes`."""

    if not isinstance(value, BoundTransitionCase):
        _reject("DETACHED_TRANSITION_CASE")
    checked = validate_transition_case(dict(value))
    if canonical_digest(checked) != value.payload_digest:
        _reject("BOUND_TRANSITION_CASE_MUTATED")
    return value


def assurance_wording_policy() -> dict[str, Any]:
    """Return the closed, canonical R2.0 operator-wording policy.

    The policy is data rather than scattered UI prose so every future projection can consume the
    same bounded claims.  The structural verifier still owns which row applies; callers cannot
    select a more favorable sentence independently of a bound verifier receipt.
    """

    return {
        "schema": "atlas.assurance-wording-policy/1",
        "version": WORDING_POLICY_VERSION,
        "human_decision_required": True,
        "autonomous_go": False,
        "gate_statements": [
            {
                "disposition": "AUTHORITATIVE_GATE",
                "authoritative_gate": AuthoritativeGate.CONFLICT_REQUIRES_RESOLUTION.value,
                "headline": "Conflict requires resolution",
                "statement": (
                    "Qualified support and counter-evidence conflict within the declared identity, "
                    "scope, time, and semantic bounds. Human resolution is required."
                ),
            },
            {
                "disposition": "AUTHORITATIVE_GATE",
                "authoritative_gate": AuthoritativeGate.ELIGIBLE_FOR_HUMAN_DECISION.value,
                "headline": "Eligible for human decision",
                "statement": (
                    "Every mandatory obligation is supported within the declared bounds and no "
                    "undefeated counter-evidence remains. This is not approval or autonomous GO."
                ),
            },
            {
                "disposition": "AUTHORITATIVE_GATE",
                "authoritative_gate": AuthoritativeGate.EVIDENCE_INCOMPLETE.value,
                "headline": "Evidence incomplete",
                "statement": (
                    "One or more mandatory evidence, applicability, qualification, replay, "
                    "security, evaluator, or certificate requirements remain unresolved."
                ),
            },
            {
                "disposition": "AUTHORITATIVE_GATE",
                "authoritative_gate": AuthoritativeGate.OBSERVED_BREACH.value,
                "headline": "Observed breach",
                "statement": (
                    "A qualified observation refutes one or more mandatory obligations within the "
                    "declared identity, scope, time, and semantic bounds."
                ),
            },
            {
                "disposition": "NO_AUTHORITATIVE_GATE",
                "authoritative_gate": None,
                "headline": "No authoritative gate",
                "statement": (
                    "Applicability or required authority remains unresolved. Acquire the named "
                    "evidence or stop; no gate verdict exists."
                ),
            },
            {
                "disposition": "NO_CASE",
                "authoritative_gate": None,
                "headline": "No Transition Case",
                "statement": (
                    "Qualified applicability recomputation found the declared pattern outside its "
                    "denominator. No Transition Case or gate verdict exists."
                ),
            },
        ],
        "claim_replacements": [
            {
                "prohibited": "The network is proven safe.",
                "required": (
                    "No counterexample was found within these models, profiles, assumptions, and "
                    "bounds."
                ),
            },
            {
                "prohibited": "Nothing else changed.",
                "required": (
                    "No out-of-contract change was observed within this coverage denominator."
                ),
            },
            {
                "prohibited": "Rollback restored the network.",
                "required": (
                    "These configuration, protocol, and service equivalence obligations were "
                    "re-observed; the receipt names what remains unknown."
                ),
            },
            {
                "prohibited": "The evidence is authentic.",
                "required": (
                    "These exact bytes were signed by the named identity under the named trust "
                    "policy."
                ),
            },
            {
                "prohibited": "The monitor proves eventual recovery.",
                "required": "Recovery was observed within the declared bounded interval, or INCONCLUSIVE.",
            },
        ],
    }


def wording_policy_digest() -> str:
    """Digest of every exact phrase and boundary in the frozen R2.0 wording policy."""

    return canonical_digest(assurance_wording_policy())


def gate_wording(disposition: str, authoritative_gate: str | None) -> dict[str, Any]:
    """Select exact operator wording for one closed disposition/gate pair."""

    for row in assurance_wording_policy()["gate_statements"]:
        if (
                row["disposition"] == disposition
                and row["authoritative_gate"] == authoritative_gate
        ):
            return {
                "policy_version": WORDING_POLICY_VERSION,
                "policy_digest": wording_policy_digest(),
                "headline": row["headline"],
                "statement": row["statement"],
            }
    _reject("WORDING_GATE_PAIR_INVALID")


__all__ = [
    "APPLICABILITY_SCHEMA",
    "ApplicabilityKind",
    "AuthoritativeGate",
    "BoundTransitionCase",
    "CANONICAL_ENCODING",
    "CONTRACT_VERSION",
    "CaseMode",
    "DERIVATION_SCHEMA",
    "EVIDENCE_ATOM_SCHEMA",
    "EVOLUTION_IR_SCHEMA",
    "EvidenceClass",
    "EvidenceEffect",
    "EvidenceStatus",
    "EvaluatorKind",
    "OBJECT_BINDING_SCHEMA",
    "OBSERVATION_PROFILE_SCHEMA",
    "ObservationMode",
    "PACK_ABI_VERSION",
    "QUALIFICATION_DENOMINATOR_SCHEMA",
    "QualificationState",
    "REPLAY_CONTRACT_SCHEMA",
    "ROLLBACK_DIMENSIONS",
    "RollbackDimension",
    "SECURITY_CONTRACT_SCHEMA",
    "TRANSITION_CASE_SCHEMA",
    "TRANSITION_SEMANTICS_VERSION",
    "TemporalOperator",
    "TemporalOutcome",
    "TransitionContractError",
    "VERSION_CONTRACT_SCHEMA",
    "WORDING_POLICY_VERSION",
    "assurance_wording_policy",
    "bind_transition_case_bytes",
    "bytes_digest",
    "canonical_digest",
    "canonical_json_bytes",
    "gate_wording",
    "parse_canonical_json_bytes",
    "require_bound_transition_case",
    "validate_applicability",
    "validate_evolution_ir",
    "validate_observation_profile",
    "validate_qualification_denominator",
    "validate_transition_case",
    "wording_policy_digest",
]
