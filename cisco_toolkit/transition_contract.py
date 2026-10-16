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
QUALIFICATION_EVIDENCE_BINDING_SCHEMA = "atlas.qualification-evidence-binding/1"
TRANSFORM_STEP_SCHEMA = "atlas.evidence-transform/1"
APPLICABILITY_SCHEMA = "atlas.applicability/1"
PACK_BINDING_SCHEMA = "atlas.pack-binding/1"
DERIVATION_SCHEMA = "atlas.derivation/1"
REPLAY_CONTRACT_SCHEMA = "atlas.replay-contract/1"
OBJECT_BINDING_SCHEMA = "atlas.content-binding/1"
SECURITY_CONTRACT_SCHEMA = "atlas.security-contract/1"
VERSION_CONTRACT_SCHEMA = "atlas.version-contract/1"
PREDECESSOR_EDGE_SCHEMA = "atlas.predecessor-edge/1"
FRAME_DOMAIN_SCHEMA = "atlas.covered-frame-domain/1"
COMPENSATION_PLAN_SCHEMA = "atlas.compensation-plan/1"
ROLLBACK_HORIZON_SCHEMA = "atlas.rollback-horizon/1"
IRREVERSIBILITY_CONDITION_SCHEMA = "atlas.irreversibility-condition/1"
TRANSITION_EXCEPTION_SCHEMA = "atlas.transition-exception/1"
DECISION_RECEIPT_SCHEMA = "atlas.transition-decision-receipt/1"
DECISION_SUBJECT_SCHEMA = "atlas.transition-decision-subject/1"

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
    ON_REQUIRE_WITHIN = "ON_REQUIRE_WITHIN"
    HOLD = "HOLD"
    UNTIL = "UNTIL"
    SAMPLED_NO_VIOLATION_DURING = "SAMPLED_NO_VIOLATION_DURING"


class TransitionKind(str, Enum):
    FORWARD = "FORWARD"
    ROLLBACK = "ROLLBACK"
    RETRY = "RETRY"
    SUPERSESSION = "SUPERSESSION"
    COMPENSATION = "COMPENSATION"


class PredecessorRelation(str, Enum):
    PREDECESSOR = "PREDECESSOR"
    ROLLBACK_OF = "ROLLBACK_OF"
    RETRY_OF = "RETRY_OF"
    SUPERSEDES = "SUPERSEDES"
    COMPENSATES = "COMPENSATES"


class ObligationKind(str, Enum):
    PRECONDITION = "PRECONDITION"
    REQUIRED_CHANGE = "REQUIRED_CHANGE"
    PERMITTED_CHANGE = "PERMITTED_CHANGE"
    FRAME_CONDITION = "FRAME_CONDITION"
    INVARIANT = "INVARIANT"
    POSTCONDITION = "POSTCONDITION"
    TEMPORAL_OBLIGATION = "TEMPORAL_OBLIGATION"
    ROLLBACK_OBLIGATION = "ROLLBACK_OBLIGATION"


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
    NO_EFFECT = "NO_EFFECT"


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

OBJECT_BINDING_ROLES = frozenset({
    "APPLICABILITY_PROFILE",
    "ASSUMPTION_SET",
    "COMPENSATION_PLAN",
    "DECISION_RECEIPT",
    "DECISION_SIGNATURE",
    "ENCRYPTION_PROFILE",
    "EVALUATOR_CERTIFICATE",
    "EVENT_INVENTORY",
    "EVIDENCE",
    "EVIDENCE_RECIPE",
    "EXCEPTION_RATIONALE",
    "KEY_POLICY",
    "LEGACY_SEMANTICS",
    "MODEL_BOUND",
    "NORMALIZER",
    "PACK_MANIFEST",
    "PARSER",
    "PREDECESSOR_CASE",
    "QUALIFICATION_PUBLIC_KEY",
    "QUALIFICATION_RECEIPT",
    "QUALIFICATION_SIGNATURE",
    "RECIPIENT_POLICY",
    "REDACTION_PROFILE",
    "REPLAY_RECIPE",
    "RETENTION_POLICY",
    "RUNTIME_DEPENDENCY",
    "SEMANTIC_BUNDLE",
    "STATE_SNAPSHOT",
    "TCB_MANIFEST",
    "TRANSFORM_PROFILE",
    "TRANSFORM_RECEIPT",
    "TRUST_SNAPSHOT",
    "VERIFIER_RECEIPT",
})


class DecisionSubjectKind(str, Enum):
    TRANSITION = "TRANSITION"
    TRANSITION_EXCEPTION = "TRANSITION_EXCEPTION"
    ROLLBACK_HORIZON = "ROLLBACK_HORIZON"


class DecisionAction(str, Enum):
    CONTINUE = "CONTINUE"
    HOLD = "HOLD"
    ROLLBACK = "ROLLBACK"
    COMMIT = "COMMIT"
    REJECT = "REJECT"
    ACCEPT_EXCEPTION = "ACCEPT_EXCEPTION"
    REJECT_EXCEPTION = "REJECT_EXCEPTION"
    REVOKE_EXCEPTION = "REVOKE_EXCEPTION"
    CLOSE_ROLLBACK_HORIZON = "CLOSE_ROLLBACK_HORIZON"


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


def decision_subject_digest(
        transition_identity: Mapping[str, Any],
        subject_kind: str,
        subject_id: str,
        subject: Mapping[str, Any]) -> str:
    """Digest an exact decision target without creating a receipt/hash cycle.

    Exception and rollback-horizon callers pass the canonical subject with its receipt-digest
    slot set to ``None``.  The envelope also carries the full TransitionIdentity, so an otherwise
    identical decision target cannot move between campaigns, pairs, scenarios, or attempts.
    """

    identity = validate_transition_identity(transition_identity, "$.decision_subject.transition_identity")
    checked_kind = _enum(subject_kind, DecisionSubjectKind, "$.decision_subject.subject_kind")
    checked_id = _identifier(subject_id, "$.decision_subject.subject_id")
    checked_subject = _mapping(subject, "$.decision_subject.subject")
    canonical_json_bytes(checked_subject)
    return canonical_digest({
        "schema": DECISION_SUBJECT_SCHEMA,
        "transition_identity": identity,
        "subject_kind": checked_kind,
        "subject_id": checked_id,
        "subject": dict(checked_subject),
    })


def validate_predecessor_edge(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "edge_id", "relation", "predecessor_transition_id",
        "predecessor_case_digest", "source_state_id", "target_state_id",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, PREDECESSOR_EDGE_SCHEMA, path)
    for key in ("edge_id", "predecessor_transition_id", "source_state_id", "target_state_id"):
        _identifier(obj[key], f"{path}.{key}")
    _enum(obj["relation"], PredecessorRelation, f"{path}.relation")
    _digest(obj["predecessor_case_digest"], f"{path}.predecessor_case_digest")
    return dict(obj)


def validate_covered_frame_domain(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "claim", "subject_ids", "predicate_ids", "window",
        "observation_profile_digests", "qualification_denominator_digests",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, FRAME_DOMAIN_SCHEMA, path)
    if obj["claim"] != "NO_OUT_OF_CONTRACT_CHANGE_OBSERVED_WITHIN_DECLARED_COVERAGE_DENOMINATOR":
        _reject("FRAME_CLAIM_WORDING_REQUIRED", f"{path}.claim")
    _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    _sorted_unique_identifiers(obj["predicate_ids"], f"{path}.predicate_ids")
    _time_interval(obj["window"], f"{path}.window")
    _sorted_unique_digests(
        obj["observation_profile_digests"], f"{path}.observation_profile_digests"
    )
    _sorted_unique_digests(
        obj["qualification_denominator_digests"],
        f"{path}.qualification_denominator_digests",
    )
    return dict(obj)


def validate_compensation_plan(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "plan_id", "owner_id", "step_ids", "plan_digest",
        "executable_state", "qualification_effect",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, COMPENSATION_PLAN_SCHEMA, path)
    _identifier(obj["plan_id"], f"{path}.plan_id")
    _identifier(obj["owner_id"], f"{path}.owner_id")
    _sorted_unique_identifiers(obj["step_ids"], f"{path}.step_ids")
    _digest(obj["plan_digest"], f"{path}.plan_digest")
    if obj["executable_state"] not in (
            "DECLARED_NOT_VERIFIED", "EXECUTABLE", "PARTIALLY_EXECUTABLE",
            "NOT_EXECUTABLE", "EXECUTED"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.executable_state")
    if obj["qualification_effect"] != "NONE":
        _reject("COMPENSATION_PLAN_CANNOT_QUALIFY", f"{path}.qualification_effect")
    return dict(obj)


def validate_rollback_horizon(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "state", "opened_at", "closes_when_condition_ids", "closed_at",
        "closure_decision_receipt_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, ROLLBACK_HORIZON_SCHEMA, path)
    if obj["state"] not in ("OPEN", "CLOSED", "UNKNOWN"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.state")
    opened = _timestamp(obj["opened_at"], f"{path}.opened_at")
    _sorted_unique_identifiers(
        obj["closes_when_condition_ids"], f"{path}.closes_when_condition_ids"
    )
    closed = None if obj["closed_at"] is None else _timestamp(obj["closed_at"], f"{path}.closed_at")
    receipt = _digest(
        obj["closure_decision_receipt_digest"],
        f"{path}.closure_decision_receipt_digest",
        optional=True,
    )
    if obj["state"] == "CLOSED":
        if closed is None or receipt is None or closed < opened:
            _reject("CLOSED_ROLLBACK_HORIZON_EVIDENCE_REQUIRED", path)
    elif closed is not None or receipt is not None:
        _reject("OPEN_ROLLBACK_HORIZON_CLOSURE_FORBIDDEN", path)
    return dict(obj)


def validate_irreversibility_condition(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = ("schema", "condition_id", "predicate_id", "subject_ids", "effect")
    _exact_keys(obj, keys, path)
    _schema(obj, IRREVERSIBILITY_CONDITION_SCHEMA, path)
    _identifier(obj["condition_id"], f"{path}.condition_id")
    _identifier(obj["predicate_id"], f"{path}.predicate_id")
    _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    if obj["effect"] not in ("CLOSES_ROLLBACK_HORIZON", "NARROWS_COMPENSATION"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.effect")
    return dict(obj)


def validate_transition_exception(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "exception_id", "obligation_ids", "state", "owner_id",
        "rationale_digest", "decision_receipt_digest", "expires_at",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, TRANSITION_EXCEPTION_SCHEMA, path)
    _identifier(obj["exception_id"], f"{path}.exception_id")
    _sorted_unique_identifiers(obj["obligation_ids"], f"{path}.obligation_ids")
    if obj["state"] not in ("PROPOSED", "ACCEPTED", "REJECTED", "EXPIRED", "REVOKED"):
        _reject("UNKNOWN_ENUM_VALUE", f"{path}.state")
    _identifier(obj["owner_id"], f"{path}.owner_id")
    _digest(obj["rationale_digest"], f"{path}.rationale_digest")
    receipt = _digest(
        obj["decision_receipt_digest"], f"{path}.decision_receipt_digest", optional=True
    )
    _timestamp(obj["expires_at"], f"{path}.expires_at")
    if obj["state"] in ("ACCEPTED", "REJECTED", "REVOKED") and receipt is None:
        _reject("EXCEPTION_DECISION_RECEIPT_REQUIRED", f"{path}.decision_receipt_digest")
    if obj["state"] in ("PROPOSED", "EXPIRED") and receipt is not None:
        _reject("EXCEPTION_DECISION_RECEIPT_FORBIDDEN", f"{path}.decision_receipt_digest")
    return dict(obj)


def validate_decision_receipt(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema", "receipt_id", "decision", "decided_at", "decider_id",
        "subject_kind", "subject_id", "subject_digest", "signature_digest",
        "supersedes_receipt_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, DECISION_RECEIPT_SCHEMA, path)
    _identifier(obj["receipt_id"], f"{path}.receipt_id")
    decision = _enum(obj["decision"], DecisionAction, f"{path}.decision")
    _timestamp(obj["decided_at"], f"{path}.decided_at")
    _identifier(obj["decider_id"], f"{path}.decider_id")
    subject_kind = _enum(obj["subject_kind"], DecisionSubjectKind, f"{path}.subject_kind")
    _identifier(obj["subject_id"], f"{path}.subject_id")
    _digest(obj["subject_digest"], f"{path}.subject_digest")
    _digest(obj["signature_digest"], f"{path}.signature_digest")
    _digest(
        obj["supersedes_receipt_digest"], f"{path}.supersedes_receipt_digest", optional=True
    )
    allowed_actions = {
        DecisionSubjectKind.TRANSITION.value: {
            DecisionAction.CONTINUE.value,
            DecisionAction.HOLD.value,
            DecisionAction.ROLLBACK.value,
            DecisionAction.COMMIT.value,
            DecisionAction.REJECT.value,
        },
        DecisionSubjectKind.TRANSITION_EXCEPTION.value: {
            DecisionAction.ACCEPT_EXCEPTION.value,
            DecisionAction.REJECT_EXCEPTION.value,
            DecisionAction.REVOKE_EXCEPTION.value,
        },
        DecisionSubjectKind.ROLLBACK_HORIZON.value: {
            DecisionAction.CLOSE_ROLLBACK_HORIZON.value,
        },
    }
    if decision not in allowed_actions[subject_kind]:
        _reject("DECISION_ACTION_SUBJECT_KIND_MISMATCH", f"{path}.decision")
    return dict(obj)


def validate_obligation(value: Any, path: str) -> dict[str, Any]:
    obj = _mapping(value, path)
    keys = (
        "schema",
        "obligation_id",
        "obligation_kind",
        "requirement_id",
        "predicate_id",
        "subject_ids",
        "state_ids",
        "temporal_operator",
        "trigger_id",
        "minimum_delay_ms",
        "maximum_delay_ms",
        "stable_duration_ms",
        "commit_event_id",
        "rollback_condition_id",
        "mandatory",
        "owner_id",
        "evidence_recipe_digest",
        "expires_at",
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
    kind = _enum(obj["obligation_kind"], ObligationKind, f"{path}.obligation_kind")
    _sorted_unique_identifiers(obj["subject_ids"], f"{path}.subject_ids")
    _sorted_unique_identifiers(obj["state_ids"], f"{path}.state_ids")
    operator = _enum(obj["temporal_operator"], TemporalOperator, f"{path}.temporal_operator")
    trigger = obj["trigger_id"]
    if trigger is not None:
        _identifier(trigger, f"{path}.trigger_id")
    minimum = _integer(obj["minimum_delay_ms"], f"{path}.minimum_delay_ms", optional=True)
    maximum = _integer(obj["maximum_delay_ms"], f"{path}.maximum_delay_ms", optional=True)
    stable = _integer(
        obj["stable_duration_ms"], f"{path}.stable_duration_ms", optional=True, positive=True
    )
    commit_event = obj["commit_event_id"]
    if commit_event is not None:
        _identifier(commit_event, f"{path}.commit_event_id")
    rollback_condition = obj["rollback_condition_id"]
    if rollback_condition is not None:
        _identifier(rollback_condition, f"{path}.rollback_condition_id")
    mandatory = _boolean(obj["mandatory"], f"{path}.mandatory")
    _identifier(obj["owner_id"], f"{path}.owner_id")
    _digest(obj["evidence_recipe_digest"], f"{path}.evidence_recipe_digest")
    _timestamp(obj["expires_at"], f"{path}.expires_at")
    _window_start, window_end = _time_interval(obj["window"], f"{path}.window")
    if _timestamp(obj["expires_at"], f"{path}.expires_at") < window_end:
        _reject("OBLIGATION_EXPIRES_BEFORE_WINDOW_END", f"{path}.expires_at")
    if kind == ObligationKind.PERMITTED_CHANGE.value and mandatory:
        _reject("PERMITTED_CHANGE_CANNOT_BE_MANDATORY", f"{path}.mandatory")
    if operator in (
            TemporalOperator.EVENTUALLY_WITHIN.value,
            TemporalOperator.ON_REQUIRE_WITHIN.value,
    ):
        if trigger is None or minimum is None or maximum is None or minimum > maximum:
            _reject("TRIGGERED_WITHIN_BOUNDS_REQUIRED", path)
        if any(item is not None for item in (stable, commit_event, rollback_condition)):
            _reject("TEMPORAL_OPERATOR_PARAMETERS_FORBIDDEN", path)
    elif operator == TemporalOperator.HOLD.value:
        if stable is None or any(
                item is not None
                for item in (trigger, minimum, maximum, commit_event, rollback_condition)
        ):
            _reject("HOLD_STABLE_DURATION_REQUIRED", path)
    elif operator == TemporalOperator.UNTIL.value:
        if commit_event is None or rollback_condition is None or any(
                item is not None for item in (trigger, minimum, maximum, stable)
        ):
            _reject("UNTIL_EVENT_AND_ROLLBACK_CONDITION_REQUIRED", path)
    elif any(
            item is not None
            for item in (trigger, minimum, maximum, stable, commit_event, rollback_condition)
    ):
        _reject("TEMPORAL_OPERATOR_PARAMETERS_FORBIDDEN", path)
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
        "predecessor_edges",
        "transition_kind",
        "from_state_id",
        "to_state_id",
        "intermediate_state_ids",
        "subject_ids",
        "trigger_ids",
        "obligations",
        "precondition_obligation_ids",
        "required_change_obligation_ids",
        "permitted_change_obligation_ids",
        "invariant_obligation_ids",
        "postcondition_obligation_ids",
        "temporal_obligation_ids",
        "covered_frame_domain",
        "compensation_plan",
        "rollback_horizon",
        "irreversibility_conditions",
        "exceptions",
        "decision_receipts",
        "rollback_dimensions",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, EVOLUTION_IR_SCHEMA, path)
    if obj["ir_version"] != EVOLUTION_IR_VERSION:
        _reject("UNSUPPORTED_EVOLUTION_IR_VERSION", f"{path}.ir_version")
    nested_identity = validate_transition_identity(obj["transition_identity"], f"{path}.transition_identity")
    if nested_identity != transition_identity:
        _reject("TRANSITION_IDENTITY_MISMATCH", f"{path}.transition_identity")
    transition_kind = _enum(obj["transition_kind"], TransitionKind, f"{path}.transition_kind")
    predecessor_edges = _array(obj["predecessor_edges"], f"{path}.predecessor_edges")
    predecessor_ids: list[str] = []
    predecessor_relations: list[str] = []
    for index, edge in enumerate(predecessor_edges):
        checked_edge = validate_predecessor_edge(edge, f"{path}.predecessor_edges[{index}]")
        predecessor_ids.append(checked_edge["edge_id"])
        predecessor_relations.append(checked_edge["relation"])
        if checked_edge["predecessor_transition_id"] == transition_identity["transition_id"]:
            _reject("SELF_PREDECESSOR_FORBIDDEN", f"{path}.predecessor_edges[{index}]")
    if predecessor_ids != sorted(set(predecessor_ids)):
        _reject("SORTED_UNIQUE_PREDECESSOR_EDGES_REQUIRED", f"{path}.predecessor_edges")
    required_relation = {
        TransitionKind.FORWARD.value: None,
        TransitionKind.ROLLBACK.value: PredecessorRelation.ROLLBACK_OF.value,
        TransitionKind.RETRY.value: PredecessorRelation.RETRY_OF.value,
        TransitionKind.SUPERSESSION.value: PredecessorRelation.SUPERSEDES.value,
        TransitionKind.COMPENSATION.value: PredecessorRelation.COMPENSATES.value,
    }[transition_kind]
    if required_relation is not None and required_relation not in predecessor_relations:
        _reject("TRANSITION_KIND_PREDECESSOR_RELATION_REQUIRED", f"{path}.predecessor_edges")
    allowed_relations = {PredecessorRelation.PREDECESSOR.value}
    if required_relation is not None:
        allowed_relations.add(required_relation)
    if not set(predecessor_relations).issubset(allowed_relations):
        _reject("TRANSITION_KIND_PREDECESSOR_RELATION_FORBIDDEN", f"{path}.predecessor_edges")
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
        if checked["trigger_id"] is not None and checked["trigger_id"] not in obj["trigger_ids"]:
            _reject("OBLIGATION_TRIGGER_UNKNOWN", f"{path}.obligations[{index}].trigger_id")
        if checked["commit_event_id"] is not None and checked["commit_event_id"] not in obj["trigger_ids"]:
            _reject("OBLIGATION_COMMIT_EVENT_UNKNOWN", f"{path}.obligations[{index}].commit_event_id")
    if obligation_ids != sorted(set(obligation_ids)):
        _reject("SORTED_UNIQUE_OBLIGATION_IDS_REQUIRED", f"{path}.obligations")
    if len(requirement_ids) != len(set(requirement_ids)):
        _reject("DUPLICATE_REQUIREMENT_ID", f"{path}.obligations")
    obligation_by_id = {item["obligation_id"]: item for item in obligations}
    partition_fields = {
        "precondition_obligation_ids": ObligationKind.PRECONDITION.value,
        "required_change_obligation_ids": ObligationKind.REQUIRED_CHANGE.value,
        "permitted_change_obligation_ids": ObligationKind.PERMITTED_CHANGE.value,
        "invariant_obligation_ids": ObligationKind.INVARIANT.value,
        "postcondition_obligation_ids": ObligationKind.POSTCONDITION.value,
        "temporal_obligation_ids": None,
    }
    partition_ids: list[str] = []
    for field, expected_kind in partition_fields.items():
        values = _sorted_unique_identifiers(
            obj[field], f"{path}.{field}", allow_empty=True
        )
        partition_ids.extend(values)
        for obligation_id in values:
            obligation = obligation_by_id.get(obligation_id)
            if obligation is None:
                _reject("CONTRACT_INDEX_OBLIGATION_UNKNOWN", f"{path}.{field}")
            actual_kind = obligation["obligation_kind"]
            if expected_kind is None:
                if actual_kind not in (
                        ObligationKind.TEMPORAL_OBLIGATION.value,
                        ObligationKind.FRAME_CONDITION.value,
                        ObligationKind.ROLLBACK_OBLIGATION.value,
                ):
                    _reject("CONTRACT_INDEX_KIND_MISMATCH", f"{path}.{field}")
            elif actual_kind != expected_kind:
                _reject("CONTRACT_INDEX_KIND_MISMATCH", f"{path}.{field}")
    if sorted(partition_ids) != sorted(obligation_ids) or len(partition_ids) != len(set(partition_ids)):
        _reject("CONTRACT_INDEX_MUST_PARTITION_OBLIGATIONS", path)

    frame = validate_covered_frame_domain(obj["covered_frame_domain"], f"{path}.covered_frame_domain")
    if not set(frame["subject_ids"]).issubset(subjects):
        _reject("FRAME_DOMAIN_SUBJECT_SCOPE_MISMATCH", f"{path}.covered_frame_domain.subject_ids")
    if not set(frame["predicate_ids"]).issubset(
            {item["predicate_id"] for item in obligations}
    ):
        _reject("FRAME_DOMAIN_PREDICATE_SCOPE_MISMATCH", f"{path}.covered_frame_domain.predicate_ids")

    validate_compensation_plan(obj["compensation_plan"], f"{path}.compensation_plan")
    horizon = validate_rollback_horizon(obj["rollback_horizon"], f"{path}.rollback_horizon")
    conditions = _array(obj["irreversibility_conditions"], f"{path}.irreversibility_conditions")
    condition_ids: list[str] = []
    horizon_closing_condition_ids: list[str] = []
    for index, condition in enumerate(conditions):
        checked = validate_irreversibility_condition(
            condition, f"{path}.irreversibility_conditions[{index}]"
        )
        condition_ids.append(checked["condition_id"])
        if checked["effect"] == "CLOSES_ROLLBACK_HORIZON":
            horizon_closing_condition_ids.append(checked["condition_id"])
        if not set(checked["subject_ids"]).issubset(subjects):
            _reject(
                "IRREVERSIBILITY_SUBJECT_SCOPE_MISMATCH",
                f"{path}.irreversibility_conditions[{index}].subject_ids",
            )
    if condition_ids != sorted(set(condition_ids)):
        _reject(
            "SORTED_UNIQUE_IRREVERSIBILITY_CONDITIONS_REQUIRED",
            f"{path}.irreversibility_conditions",
        )
    if set(horizon["closes_when_condition_ids"]) != set(horizon_closing_condition_ids):
        _reject("ROLLBACK_HORIZON_CONDITION_SET_MISMATCH", f"{path}.rollback_horizon")
    for index, obligation in enumerate(obligations):
        rollback_condition_id = obligation["rollback_condition_id"]
        if rollback_condition_id is not None and rollback_condition_id not in condition_ids:
            _reject(
                "OBLIGATION_ROLLBACK_CONDITION_UNKNOWN",
                f"{path}.obligations[{index}].rollback_condition_id",
            )

    decision_receipts = _array(obj["decision_receipts"], f"{path}.decision_receipts")
    decision_ids: list[str] = []
    decision_by_digest: dict[str, Mapping[str, Any]] = {}
    for index, receipt in enumerate(decision_receipts):
        checked = validate_decision_receipt(receipt, f"{path}.decision_receipts[{index}]")
        decision_ids.append(checked["receipt_id"])
        decision_by_digest[canonical_digest(checked)] = checked
    if decision_ids != sorted(set(decision_ids)):
        _reject("SORTED_UNIQUE_DECISION_RECEIPTS_REQUIRED", f"{path}.decision_receipts")
    transition_subject = decision_subject_digest(
        transition_identity,
        DecisionSubjectKind.TRANSITION.value,
        transition_identity["transition_id"],
        transition_identity,
    )
    for digest, receipt in decision_by_digest.items():
        supersedes = receipt["supersedes_receipt_digest"]
        if supersedes is not None:
            prior = decision_by_digest.get(supersedes)
            if prior is None or supersedes == digest:
                _reject("DECISION_SUPERSESSION_RECEIPT_UNKNOWN", f"{path}.decision_receipts")
            if (
                    prior["subject_kind"] != receipt["subject_kind"]
                    or prior["subject_id"] != receipt["subject_id"]
                    or _timestamp(prior["decided_at"], f"{path}.decision_receipts")
                    >= _timestamp(receipt["decided_at"], f"{path}.decision_receipts")
            ):
                _reject("DECISION_SUPERSESSION_SUBJECT_OR_TIME_MISMATCH", f"{path}.decision_receipts")
            if (
                    prior["subject_digest"] != receipt["subject_digest"]
                    and not (
                        receipt["subject_kind"]
                        == DecisionSubjectKind.TRANSITION_EXCEPTION.value
                        and receipt["decision"] == DecisionAction.REVOKE_EXCEPTION.value
                    )
            ):
                _reject("DECISION_SUPERSESSION_SUBJECT_OR_TIME_MISMATCH", f"{path}.decision_receipts")
        if receipt["subject_kind"] == DecisionSubjectKind.TRANSITION.value and (
                receipt["subject_id"] != transition_identity["transition_id"]
                or receipt["subject_digest"] != transition_subject
        ):
            _reject("TRANSITION_DECISION_SUBJECT_MISMATCH", f"{path}.decision_receipts")

    referenced_special_decisions: set[str] = set()
    if horizon["state"] == "CLOSED":
        horizon_receipt_digest = horizon["closure_decision_receipt_digest"]
        horizon_receipt = decision_by_digest.get(horizon_receipt_digest)
        if horizon_receipt is None:
            _reject("ROLLBACK_HORIZON_DECISION_RECEIPT_UNKNOWN", f"{path}.rollback_horizon")
        horizon_subject_value = dict(horizon)
        horizon_subject_value["closure_decision_receipt_digest"] = None
        expected_horizon_subject = decision_subject_digest(
            transition_identity,
            DecisionSubjectKind.ROLLBACK_HORIZON.value,
            transition_identity["transition_id"],
            horizon_subject_value,
        )
        if (
                horizon_receipt["subject_kind"]
                != DecisionSubjectKind.ROLLBACK_HORIZON.value
                or horizon_receipt["subject_id"] != transition_identity["transition_id"]
                or horizon_receipt["subject_digest"] != expected_horizon_subject
                or horizon_receipt["decision"]
                != DecisionAction.CLOSE_ROLLBACK_HORIZON.value
        ):
            _reject("ROLLBACK_HORIZON_DECISION_SUBJECT_MISMATCH", f"{path}.rollback_horizon")
        if _timestamp(
                horizon_receipt["decided_at"], f"{path}.decision_receipts"
        ) < _timestamp(horizon["closed_at"], f"{path}.rollback_horizon.closed_at"):
            _reject("ROLLBACK_HORIZON_DECISION_TIME_MISMATCH", f"{path}.rollback_horizon")
        referenced_special_decisions.add(horizon_receipt_digest)
    exceptions = _array(obj["exceptions"], f"{path}.exceptions")
    exception_ids: list[str] = []
    for index, exception in enumerate(exceptions):
        checked = validate_transition_exception(exception, f"{path}.exceptions[{index}]")
        exception_ids.append(checked["exception_id"])
        if not set(checked["obligation_ids"]).issubset(obligation_by_id):
            _reject("EXCEPTION_OBLIGATION_UNKNOWN", f"{path}.exceptions[{index}].obligation_ids")
        receipt_digest = checked["decision_receipt_digest"]
        if receipt_digest is not None:
            receipt = decision_by_digest.get(receipt_digest)
            if receipt is None:
                _reject("EXCEPTION_DECISION_RECEIPT_UNKNOWN", f"{path}.exceptions[{index}]")
            subject_value = dict(checked)
            subject_value["decision_receipt_digest"] = None
            expected_subject = decision_subject_digest(
                transition_identity,
                DecisionSubjectKind.TRANSITION_EXCEPTION.value,
                checked["exception_id"],
                subject_value,
            )
            expected_action = {
                "ACCEPTED": DecisionAction.ACCEPT_EXCEPTION.value,
                "REJECTED": DecisionAction.REJECT_EXCEPTION.value,
                "REVOKED": DecisionAction.REVOKE_EXCEPTION.value,
            }[checked["state"]]
            if (
                    receipt["subject_kind"]
                    != DecisionSubjectKind.TRANSITION_EXCEPTION.value
                    or receipt["subject_id"] != checked["exception_id"]
                    or receipt["subject_digest"] != expected_subject
                    or receipt["decision"] != expected_action
            ):
                _reject("EXCEPTION_DECISION_SUBJECT_MISMATCH", f"{path}.exceptions[{index}]")
            if _timestamp(receipt["decided_at"], f"{path}.decision_receipts") > _timestamp(
                    checked["expires_at"], f"{path}.exceptions[{index}].expires_at"
            ):
                _reject("EXCEPTION_DECISION_AFTER_EXPIRY", f"{path}.exceptions[{index}]")
            supersedes = receipt["supersedes_receipt_digest"]
            if checked["state"] == "REVOKED":
                prior = decision_by_digest.get(supersedes)
                accepted_subject_value = dict(checked)
                accepted_subject_value["state"] = "ACCEPTED"
                accepted_subject_value["decision_receipt_digest"] = None
                expected_accepted_subject = decision_subject_digest(
                    transition_identity,
                    DecisionSubjectKind.TRANSITION_EXCEPTION.value,
                    checked["exception_id"],
                    accepted_subject_value,
                )
                if (
                        supersedes is None
                        or prior is None
                        or prior["subject_kind"]
                        != DecisionSubjectKind.TRANSITION_EXCEPTION.value
                        or prior["subject_id"] != checked["exception_id"]
                        or prior["subject_digest"] != expected_accepted_subject
                        or prior["decision"] != DecisionAction.ACCEPT_EXCEPTION.value
                ):
                    _reject(
                        "EXCEPTION_REVOKE_ACCEPT_LINEAGE_REQUIRED",
                        f"{path}.exceptions[{index}]",
                    )
                referenced_special_decisions.add(supersedes)
            elif supersedes is not None:
                _reject(
                    "EXCEPTION_DECISION_SUPERSESSION_FORBIDDEN",
                    f"{path}.exceptions[{index}]",
                )
            referenced_special_decisions.add(receipt_digest)
    if exception_ids != sorted(set(exception_ids)):
        _reject("SORTED_UNIQUE_EXCEPTIONS_REQUIRED", f"{path}.exceptions")
    for digest, receipt in decision_by_digest.items():
        if (
                receipt["subject_kind"] != DecisionSubjectKind.TRANSITION.value
                and digest not in referenced_special_decisions
        ):
            _reject("ORPHAN_SPECIAL_DECISION_RECEIPT", f"{path}.decision_receipts")

    for edge in predecessor_edges:
        if edge["target_state_id"] != from_state:
            _reject("PREDECESSOR_TARGET_MUST_MATCH_BEFORE_STATE", f"{path}.predecessor_edges")
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


def validate_qualification_evidence_binding(value: Any, path: str) -> dict[str, Any]:
    """Bind one qualification receipt to the exact signature and public-key bytes used."""

    obj = _mapping(value, path)
    keys = ("schema", "receipt_digest", "signature_digest", "public_key_digest")
    _exact_keys(obj, keys, path)
    _schema(obj, QUALIFICATION_EVIDENCE_BINDING_SCHEMA, path)
    for key in keys[1:]:
        _digest(obj[key], f"{path}.{key}")
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
    expected_complete = profile["coverage_mode"] != ObservationMode.SAMPLED.value
    if scope["complete"] is not expected_complete:
        _reject("EVIDENCE_COVERAGE_COMPLETENESS_PROFILE_MISMATCH", f"{path}.coverage_scope.complete")
    chain = _array(obj["transform_chain"], f"{path}.transform_chain")
    prior_output: str | None = None
    removed_predicates: set[str] = set()
    for index, step in enumerate(chain):
        checked = validate_transform_step(step, f"{path}.transform_chain[{index}]")
        if prior_output is not None and checked["input_digest"] != prior_output:
            _reject("TRANSFORM_CHAIN_DISCONNECTED", f"{path}.transform_chain[{index}]")
        prior_output = checked["output_digest"]
        removed_predicates.update(checked["removed_predicate_ids"])
    if prior_output is not None and prior_output != artifact_digest:
        _reject("TRANSFORM_OUTPUT_ARTIFACT_MISMATCH", f"{path}.artifact_digest")
    if removed_predicates.intersection(scope["predicate_ids"]):
        _reject("TRANSFORM_REMOVED_PREDICATE_STILL_CLAIMED", f"{path}.coverage_scope")
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
    effect = _enum(obj["effect"], EvidenceEffect, f"{path}.effect")
    temporal_outcome = _enum(
        obj["temporal_outcome"], TemporalOutcome, f"{path}.temporal_outcome"
    )
    allowed_outcomes = {
        EvidenceEffect.SUPPORT.value: {
            TemporalOutcome.SATISFIED_WITHIN_DECLARED_MODEL.value,
            TemporalOutcome.NO_VIOLATION_OBSERVED_ON_DECLARED_TRACE.value,
        },
        EvidenceEffect.COUNTER_EVIDENCE.value: {
            TemporalOutcome.VIOLATED.value,
        },
        EvidenceEffect.NO_EFFECT.value: {
            TemporalOutcome.INCONCLUSIVE.value,
        },
    }
    if temporal_outcome not in allowed_outcomes[effect]:
        _reject("DERIVATION_EFFECT_TEMPORAL_OUTCOME_MISMATCH", path)
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
        "historical_trust_snapshot_digest",
        "trust_policy_digest",
        "replay_recipe_digest",
    )
    _exact_keys(obj, keys, path)
    _schema(obj, REPLAY_CONTRACT_SCHEMA, path)
    mode = _enum(obj["mode"], CaseMode, f"{path}.mode")
    if mode != case_mode:
        _reject("CASE_MODE_MISMATCH", f"{path}.mode")
    for key in (
            "verifier_bootstrap_digest",
            "historical_trust_snapshot_digest",
            "trust_policy_digest",
            "replay_recipe_digest",
    ):
        _digest(obj[key], f"{path}.{key}")
    bindings = _array(obj["object_bindings"], f"{path}.object_bindings")
    locations = {"EMBEDDED", "EXTERNAL", "PROJECTION"}
    binding_keys: list[tuple[str, str]] = []
    for index, binding in enumerate(bindings):
        item_path = f"{path}.object_bindings[{index}]"
        item = _mapping(binding, item_path)
        _exact_keys(item, ("schema", "role", "digest", "location", "resolver_id", "required"), item_path)
        _schema(item, OBJECT_BINDING_SCHEMA, item_path)
        if item["role"] not in OBJECT_BINDING_ROLES:
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
        if mode == CaseMode.REFERENCED.value and item["required"] and item["location"] == "PROJECTION":
            _reject("REFERENCED_REQUIRED_CONTENT_CANNOT_BE_PROJECTION", item_path)
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
    "qualification_evidence_bindings",
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
    created_at = _timestamp(obj["created_at"], "$.created_at")
    identity = validate_transition_identity(obj["transition_identity"])
    ir = validate_evolution_ir(obj["evolution_ir"], identity)
    for index, obligation in enumerate(ir["obligations"]):
        if _timestamp(
                obligation["expires_at"], f"$.evolution_ir.obligations[{index}].expires_at"
        ) < created_at:
            _reject(
                "OBLIGATION_EXPIRED_BEFORE_CASE_CREATION",
                f"$.evolution_ir.obligations[{index}].expires_at",
            )
    horizon = ir["rollback_horizon"]
    if _timestamp(horizon["opened_at"], "$.evolution_ir.rollback_horizon.opened_at") > created_at:
        _reject("ROLLBACK_HORIZON_AFTER_CASE_CREATION", "$.evolution_ir.rollback_horizon")
    if (
            horizon["closed_at"] is not None
            and _timestamp(horizon["closed_at"], "$.evolution_ir.rollback_horizon.closed_at")
            > created_at
    ):
        _reject("ROLLBACK_HORIZON_AFTER_CASE_CREATION", "$.evolution_ir.rollback_horizon")
    for index, receipt in enumerate(ir["decision_receipts"]):
        if _timestamp(
                receipt["decided_at"], f"$.evolution_ir.decision_receipts[{index}].decided_at"
        ) > created_at:
            _reject(
                "DECISION_AFTER_CASE_CREATION",
                f"$.evolution_ir.decision_receipts[{index}].decided_at",
            )
    for index, exception in enumerate(ir["exceptions"]):
        expires_at = _timestamp(
            exception["expires_at"], f"$.evolution_ir.exceptions[{index}].expires_at"
        )
        if (
                exception["state"] in {"PROPOSED", "ACCEPTED"}
                and expires_at < created_at
        ) or (exception["state"] == "EXPIRED" and expires_at > created_at):
            _reject(
                "EXCEPTION_STATE_TIME_MISMATCH",
                f"$.evolution_ir.exceptions[{index}]",
            )
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

    frame = ir["covered_frame_domain"]
    if not set(frame["observation_profile_digests"]).issubset(profile_digests):
        _reject(
            "FRAME_DOMAIN_OBSERVATION_PROFILE_UNKNOWN",
            "$.evolution_ir.covered_frame_domain.observation_profile_digests",
        )
    selected_profiles = [
        profile_digests[digest]
        for digest in frame["observation_profile_digests"]
    ]
    expected_frame_denominators = {
        profile["qualification_denominator_digest"]
        for profile in selected_profiles
    }
    if set(frame["qualification_denominator_digests"]) != expected_frame_denominators:
        _reject(
            "FRAME_DOMAIN_QUALIFICATION_DENOMINATOR_MISMATCH",
            "$.evolution_ir.covered_frame_domain.qualification_denominator_digests",
        )
    for profile in selected_profiles:
        if profile["window"] != frame["window"]:
            _reject(
                "FRAME_DOMAIN_WINDOW_PROFILE_MISMATCH",
                "$.evolution_ir.covered_frame_domain.window",
            )
    selected_denominators = [
        denominator_digests[profile["qualification_denominator_digest"]]
        for profile in selected_profiles
    ]
    for subject_id in frame["subject_ids"]:
        for predicate_id in frame["predicate_ids"]:
            if not any(
                    subject_id in denominator["subject_ids"]
                    and predicate_id in denominator["predicate_ids"]
                    for denominator in selected_denominators
            ):
                _reject(
                    "FRAME_DOMAIN_SCOPE_DENOMINATOR_MISMATCH",
                    "$.evolution_ir.covered_frame_domain",
                )

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
        if _timestamp(checked["sealed_at"], f"$.evidence_atoms[{index}].sealed_at") > created_at:
            _reject("EVIDENCE_SEALED_AFTER_CASE_CREATION", f"$.evidence_atoms[{index}]")
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
    if applicability["kind"] == ApplicabilityKind.NOT_APPLICABLE.value:
        _reject("NOT_APPLICABLE_CANNOT_CONSTRUCT_TRANSITION_CASE", "$.applicability")
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

    qualification_evidence = _array(
        obj["qualification_evidence_bindings"], "$.qualification_evidence_bindings"
    )
    qualification_evidence_by_receipt: dict[str, Mapping[str, Any]] = {}
    receipt_keys: list[str] = []
    signature_digests: list[str] = []
    for index, binding in enumerate(qualification_evidence):
        checked = validate_qualification_evidence_binding(
            binding, f"$.qualification_evidence_bindings[{index}]"
        )
        receipt_digest = checked["receipt_digest"]
        receipt_keys.append(receipt_digest)
        signature_digests.append(checked["signature_digest"])
        qualification_evidence_by_receipt[receipt_digest] = checked
    if receipt_keys != sorted(set(receipt_keys)):
        _reject(
            "SORTED_UNIQUE_QUALIFICATION_EVIDENCE_REQUIRED",
            "$.qualification_evidence_bindings",
        )
    if len(signature_digests) != len(set(signature_digests)):
        _reject(
            "QUALIFICATION_SIGNATURE_REUSE_FORBIDDEN",
            "$.qualification_evidence_bindings",
        )
    expected_qualification_receipts = {
        digest
        for digest in (
            applicability["qualification_receipt_digest"],
            pack_binding["pack_qualification_receipt_digest"],
            *(profile["qualification_receipt_digest"] for profile in profiles),
        )
        if digest is not None
    }
    if set(qualification_evidence_by_receipt) != expected_qualification_receipts:
        _reject(
            "QUALIFICATION_EVIDENCE_RECEIPT_SET_MISMATCH",
            "$.qualification_evidence_bindings",
        )

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
            if atom["observation_profile_digest"] != obligation["observation_profile_digest"]:
                _reject("DERIVATION_OBSERVATION_PROFILE_MISMATCH", f"$.derivations[{index}]")
            if atom["semantic_profile_digest"] != obligation["semantic_profile_digest"]:
                _reject("DERIVATION_SEMANTIC_PROFILE_MISMATCH", f"$.derivations[{index}]")
            if atom["evidence_class"] not in obligation["accepted_evidence_classes"]:
                _reject("DERIVATION_EVIDENCE_CLASS_NOT_ACCEPTED", f"$.derivations[{index}]")
        if checked["evaluator_digest"] != pack_binding["semantic_bundle_digest"]:
            _reject("DERIVATION_EVALUATOR_BINDING_MISMATCH", f"$.derivations[{index}]")
    if derivation_ids != sorted(set(derivation_ids)):
        _reject("SORTED_UNIQUE_DERIVATION_IDS_REQUIRED", "$.derivations")

    replay = validate_replay_contract(obj["replay_contract"], case_mode)
    security = validate_security_contract(obj["security_contract"])
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
        for step in atom["transform_chain"]:
            for digest in (step["input_digest"], step["output_digest"]):
                require_authority_binding(
                    "EVIDENCE",
                    digest,
                    "TRANSFORM_EVIDENCE_CONTENT_BINDING_MISSING",
                )
            require_authority_binding(
                "TRANSFORM_PROFILE",
                step["transform_profile_digest"],
                "TRANSFORM_PROFILE_CONTENT_BINDING_MISSING",
            )
            require_authority_binding(
                "TRANSFORM_RECEIPT",
                step["transform_receipt_digest"],
                "TRANSFORM_RECEIPT_CONTENT_BINDING_MISSING",
            )
    for edge in ir["predecessor_edges"]:
        require_authority_binding(
            "PREDECESSOR_CASE",
            edge["predecessor_case_digest"],
            "PREDECESSOR_CASE_CONTENT_BINDING_MISSING",
        )
    require_authority_binding(
        "COMPENSATION_PLAN",
        ir["compensation_plan"]["plan_digest"],
        "COMPENSATION_PLAN_CONTENT_BINDING_MISSING",
    )
    for receipt in ir["decision_receipts"]:
        require_authority_binding(
            "DECISION_RECEIPT",
            canonical_digest(receipt),
            "DECISION_RECEIPT_CONTENT_BINDING_MISSING",
        )
        require_authority_binding(
            "DECISION_SIGNATURE",
            receipt["signature_digest"],
            "DECISION_SIGNATURE_CONTENT_BINDING_MISSING",
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
    for binding in qualification_evidence_by_receipt.values():
        require_authority_binding(
            "QUALIFICATION_SIGNATURE",
            binding["signature_digest"],
            "QUALIFICATION_SIGNATURE_CONTENT_BINDING_MISSING",
        )
        require_authority_binding(
            "QUALIFICATION_PUBLIC_KEY",
            binding["public_key_digest"],
            "QUALIFICATION_PUBLIC_KEY_CONTENT_BINDING_MISSING",
        )
    for denominator in denominators:
        require_authority_binding(
            "EVENT_INVENTORY",
            denominator["event_inventory_digest"],
            "EVENT_INVENTORY_CONTENT_BINDING_MISSING",
        )
        require_authority_binding(
            "MODEL_BOUND",
            denominator["model_bound_digest"],
            "MODEL_BOUND_CONTENT_BINDING_MISSING",
        )
        require_authority_binding(
            "ASSUMPTION_SET",
            denominator["assumption_set_digest"],
            "ASSUMPTION_SET_CONTENT_BINDING_MISSING",
        )
    require_authority_binding(
        "APPLICABILITY_PROFILE",
        applicability["profile_digest"],
        "APPLICABILITY_PROFILE_CONTENT_BINDING_MISSING",
    )
    for exception in ir["exceptions"]:
        require_authority_binding(
            "EXCEPTION_RATIONALE",
            exception["rationale_digest"],
            "EXCEPTION_RATIONALE_CONTENT_BINDING_MISSING",
        )
    for field, role, code in (
        ("recipient_policy_digest", "RECIPIENT_POLICY", "RECIPIENT_POLICY_CONTENT_BINDING_MISSING"),
        ("encryption_profile_digest", "ENCRYPTION_PROFILE", "ENCRYPTION_PROFILE_CONTENT_BINDING_MISSING"),
        ("redaction_profile_digest", "REDACTION_PROFILE", "REDACTION_PROFILE_CONTENT_BINDING_MISSING"),
        ("key_policy_digest", "KEY_POLICY", "KEY_POLICY_CONTENT_BINDING_MISSING"),
        ("retention_policy_digest", "RETENTION_POLICY", "RETENTION_POLICY_CONTENT_BINDING_MISSING"),
    ):
        require_authority_binding(role, security[field], code)
    for derivation in derivations:
        require_authority_binding(
            "EVALUATOR_CERTIFICATE",
            derivation["certificate_digest"],
            "EVALUATOR_CERTIFICATE_CONTENT_BINDING_MISSING",
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
        "TRUST_SNAPSHOT",
        replay["historical_trust_snapshot_digest"],
        "HISTORICAL_TRUST_SNAPSHOT_CONTENT_BINDING_MISSING",
    )
    require_authority_binding(
        "REPLAY_RECIPE",
        replay["replay_recipe_digest"],
        "REPLAY_RECIPE_CONTENT_BINDING_MISSING",
    )

    for obligation in ir["obligations"]:
        require_authority_binding(
            "EVIDENCE_RECIPE",
            obligation["evidence_recipe_digest"],
            "EVIDENCE_RECIPE_CONTENT_BINDING_MISSING",
        )
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
    legacy_semantics_digest = version["legacy_semantics_digest"]
    legacy_dependencies = {
        item["digest"]
        for item in version["dependency_digests"]
        if item["kind"] == "LEGACY_SEMANTICS"
    }
    if legacy_semantics_digest is None:
        if legacy_dependencies:
            _reject("LEGACY_SEMANTICS_DEPENDENCY_FORBIDDEN", "$.version_contract")
    elif legacy_dependencies != {legacy_semantics_digest}:
        _reject("LEGACY_SEMANTICS_DEPENDENCY_MISSING", "$.version_contract")
    else:
        require_authority_binding(
            "LEGACY_SEMANTICS",
            legacy_semantics_digest,
            "LEGACY_SEMANTICS_CONTENT_BINDING_MISSING",
        )
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
    "COMPENSATION_PLAN_SCHEMA",
    "CONTRACT_VERSION",
    "CaseMode",
    "DERIVATION_SCHEMA",
    "DECISION_RECEIPT_SCHEMA",
    "DECISION_SUBJECT_SCHEMA",
    "DecisionAction",
    "DecisionSubjectKind",
    "EVIDENCE_ATOM_SCHEMA",
    "EVOLUTION_IR_SCHEMA",
    "EvidenceClass",
    "EvidenceEffect",
    "EvidenceStatus",
    "EvaluatorKind",
    "FRAME_DOMAIN_SCHEMA",
    "IRREVERSIBILITY_CONDITION_SCHEMA",
    "ObligationKind",
    "OBJECT_BINDING_SCHEMA",
    "OBJECT_BINDING_ROLES",
    "OBSERVATION_PROFILE_SCHEMA",
    "ObservationMode",
    "PACK_ABI_VERSION",
    "QUALIFICATION_DENOMINATOR_SCHEMA",
    "QUALIFICATION_EVIDENCE_BINDING_SCHEMA",
    "PREDECESSOR_EDGE_SCHEMA",
    "PredecessorRelation",
    "QualificationState",
    "REPLAY_CONTRACT_SCHEMA",
    "ROLLBACK_HORIZON_SCHEMA",
    "ROLLBACK_DIMENSIONS",
    "RollbackDimension",
    "SECURITY_CONTRACT_SCHEMA",
    "TRANSITION_CASE_SCHEMA",
    "TRANSITION_SEMANTICS_VERSION",
    "TemporalOperator",
    "TemporalOutcome",
    "TransitionContractError",
    "TransitionKind",
    "TRANSITION_EXCEPTION_SCHEMA",
    "VERSION_CONTRACT_SCHEMA",
    "WORDING_POLICY_VERSION",
    "assurance_wording_policy",
    "bind_transition_case_bytes",
    "bytes_digest",
    "canonical_digest",
    "canonical_json_bytes",
    "decision_subject_digest",
    "gate_wording",
    "parse_canonical_json_bytes",
    "require_bound_transition_case",
    "validate_applicability",
    "validate_compensation_plan",
    "validate_covered_frame_domain",
    "validate_decision_receipt",
    "validate_evolution_ir",
    "validate_irreversibility_condition",
    "validate_observation_profile",
    "validate_predecessor_edge",
    "validate_qualification_denominator",
    "validate_qualification_evidence_binding",
    "validate_rollback_horizon",
    "validate_transition_case",
    "validate_transition_exception",
    "wording_policy_digest",
]
