"""Bounded, non-authoritative Atlas R2 declarative Pack ABI prototype.

This module is executable evidence for the R2.0 substrate review, not a qualified pack runtime.
It accepts only exact canonical JSON bytes, compiles a closed expression tree without recursion,
and evaluates it with deterministic fuel.  The provisional limits below are deliberately
injectable measurement guards; they are not independently approved TCB budgets or ceilings.

No result from this prototype supplies obligation support, an authoritative gate, qualification,
or promotion eligibility.  ``replay_witness`` is present in the closed ABI but always refuses
until an independently qualified replay contract exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .transition_contract import (
    PACK_ABI_VERSION,
    QualificationState,
    TransitionContractError,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    validate_qualification_denominator,
)
from .transition_pack import (
    DECLARATIVE_DSL_OPERATORS,
    PACK_ABI_FUNCTIONS,
    BoundPackManifest,
    BoundTCBManifest,
    PackContractError,
    PackExecutionState,
    PackSubstrate,
    bind_pack_manifest_bytes,
    bind_tcb_manifest_bytes,
    require_bound_pack_manifest,
    require_bound_tcb_manifest,
    validate_pack_tcb_pair,
)


DECLARATIVE_PROGRAM_SCHEMA = "atlas.declarative-program/1"
DECLARATIVE_INPUT_SCHEMA = "atlas.declarative-input/1"
DECLARATIVE_BINDING_SCHEMA = "atlas.declarative-binding/1"
DECLARATIVE_RESULT_SCHEMA = "atlas.declarative-result/1"
DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA = "atlas.declarative-prototype-receipt/1"
BOUND_DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA = "atlas.bound-declarative-prototype-receipt/1"

DSL_PROTOTYPE_PACK_ID = "ATLAS-R2-DSL-CONFORMANCE"
DSL_PROTOTYPE_PACK_VERSION = "0.1.0-experimental"
DSL_PROTOTYPE_CLAIM_BOUNDARY = (
    "Synthetic R2.0 executable conformance evidence only; not QCP-001, qualified, authoritative, "
    "portable, sandboxed, or promotion-eligible."
)
DSL_PROTOTYPE_PROGRAM_PATH = "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json"
DSL_PROTOTYPE_DENOMINATOR_PATH = (
    "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json"
)
DSL_PROTOTYPE_INPUT_PATH = "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json"
DSL_PROTOTYPE_PACK_MANIFEST_PATH = (
    "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json"
)
DSL_PROTOTYPE_TCB_MANIFEST_PATH = (
    "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json"
)
DSL_INTERPRETER_SOURCE_PATH = "cisco_toolkit/transition_dsl.py"
DSL_PROTOTYPE_SOURCE_BINDING_STATE = "SAME_CHECKOUT_SELF_CHECK_ONLY"
DECLARATIVE_INTERPRETER_SEMANTICS_VERSION = "ATLAS_DECLARATIVE_DSL_SEMANTICS/1"
FUEL_CANONICAL_BYTE_QUANTUM = 64

TRUTH_TRUE = "TRUE"
TRUTH_FALSE = "FALSE"
TRUTH_INCONCLUSIVE = "INCONCLUSIVE"
TRUTH_VALUES = (TRUTH_TRUE, TRUTH_FALSE, TRUTH_INCONCLUSIVE)

_EXECUTED = "EXECUTED_NONAUTHORITATIVE"
_REFUSED = "REFUSED_NONAUTHORITATIVE"
_MISSING = object()
_IDENTIFIER_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/@+-"
)
_ASCII_ALPHANUMERIC = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)
_AUTHORITY_TOKENS = frozenset(
    {"authority", "authoritative", "gate", "promotion", "qualification", "status"}
)
_AUTHORITY_FIELDS = frozenset(
    {
        "authoritative_gate",
        "execution_state",
        "promotion_eligible",
        "qualification_effect",
        "qualification_state",
        "supplies_obligation_support",
    }
)
_ROOTS = frozenset({"facts", "identity", "scope", "time"})
_RULE_FUNCTIONS = PACK_ABI_FUNCTIONS[:-1]
_BOUND_PROTOTYPE_AUTHORITY = object()
DSL_PROTOTYPE_LIMIT_FIELDS = (
    "max_program_bytes",
    "max_input_bytes",
    "max_output_bytes",
    "max_rules",
    "max_expression_depth",
    "max_expression_nodes",
    "max_operator_operands",
    "max_path_segments",
    "max_string_bytes",
    "max_set_items",
    "max_input_nodes",
    "max_instruction_fuel",
)


class DSLPrototypeError(ValueError):
    """Stable non-echoing prototype refusal.

    Only ``code`` crosses the boundary.  Hostile values, source paths, and canonical-parser paths
    are never included in the message or receipt.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DSLPrototypeLimits:
    """Immutable, provisional measurement guards (not reviewed TCB budgets)."""

    max_program_bytes: int = 262_144
    max_input_bytes: int = 1_048_576
    # Kept below the program guard so an emitted value can exercise the real N-1/N/N+1 output
    # boundary. The first executable measurement found that equal 262,144-byte guards made output
    # N structurally unreachable because its smallest carrier program was 154 bytes larger.
    max_output_bytes: int = 131_072
    max_rules: int = 1_024
    max_expression_depth: int = 32
    max_expression_nodes: int = 4_096
    max_operator_operands: int = 256
    max_path_segments: int = 32
    max_string_bytes: int = 65_536
    max_set_items: int = 1_024
    max_input_nodes: int = 16_384
    max_instruction_fuel: int = 32_768

    def __post_init__(self) -> None:
        for field_name in DSL_PROTOTYPE_LIMIT_FIELDS:
            value = getattr(self, field_name)
            if type(value) is not int or value < 1:
                raise DSLPrototypeError("LIMIT_PROFILE_INVALID")


DEFAULT_DSL_PROTOTYPE_LIMITS = DSLPrototypeLimits()


class BoundPackagedDSLPrototype:
    """Exact prototype assets and same-checkout source bytes joined without promotion authority."""

    __slots__ = (
        "_pack",
        "_tcb",
        "_program_raw",
        "_program_digest",
        "_denominator_digest",
        "_source_rows",
        "_integrity_digest",
        "_sealed",
    )

    def __init__(
            self,
            *,
            pack: BoundPackManifest,
            tcb: BoundTCBManifest,
            program_raw: bytes,
            denominator_digest: str,
            source_rows: tuple[tuple[str, int, str], ...],
            _authority: object) -> None:
        if _authority is not _BOUND_PROTOTYPE_AUTHORITY:
            raise TypeError("BoundPackagedDSLPrototype requires exact prototype bytes")
        object.__setattr__(self, "_sealed", False)
        self._pack = pack
        self._tcb = tcb
        self._program_raw = program_raw
        self._program_digest = bytes_digest(program_raw)
        self._denominator_digest = denominator_digest
        self._source_rows = source_rows
        self._integrity_digest = self._compute_integrity_digest()
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundPackagedDSLPrototype is immutable")
        object.__setattr__(self, name, value)

    @property
    def pack_manifest(self) -> dict[str, Any]:
        return dict(self._pack)

    @property
    def tcb_manifest(self) -> dict[str, Any]:
        return dict(self._tcb)

    @property
    def pack_manifest_digest(self) -> str:
        return self._pack.digest

    @property
    def tcb_manifest_digest(self) -> str:
        return self._tcb.digest

    @property
    def program_digest(self) -> str:
        return self._program_digest

    @property
    def denominator_digest(self) -> str:
        return self._denominator_digest

    @property
    def interpreter_digest(self) -> str:
        return self._tcb["dsl_interpreter"]["content_digest"]

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "pack_manifest_digest": self._pack.digest,
            "tcb_manifest_digest": self._tcb.digest,
            "program_digest": self._program_digest,
            "denominator_digest": self._denominator_digest,
            "source_rows": [
                {"path": path, "bytes": size, "digest": digest}
                for path, size, digest in self._source_rows
            ],
        })


@dataclass(frozen=True)
class _CompiledRule:
    function: str
    rule_id: str
    instructions: tuple[tuple[Any, ...], ...]
    emit: Any


@dataclass(frozen=True)
class _CompiledProgram:
    rules: tuple[_CompiledRule, ...]
    expression_nodes: int


@dataclass
class _Work:
    program_bytes: int = 0
    input_bytes: int = 0
    input_nodes: int = 0
    rules: int = 0
    expression_nodes: int = 0
    fuel_consumed: int = 0
    result_records: int = 0
    result_bytes: int = 0


def _fail(code: str) -> None:
    raise DSLPrototypeError(code)


def _exact_keys(value: Any, keys: tuple[str, ...], code: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != set(keys):
        _fail(code)
    return value


def _identifier(value: Any) -> str:
    if (
            type(value) is not str
            or not value
            or value[0] not in _ASCII_ALPHANUMERIC
            or any(char not in _IDENTIFIER_CHARS for char in value)
    ):
        _fail("PROGRAM_IDENTIFIER_INVALID")
    return value


def _authority_tokens(key: str) -> set[str]:
    tokens: list[str] = []
    current: list[str] = []
    previous_lower = False
    for char in key:
        if not char.isalnum():
            if current:
                tokens.append("".join(current).casefold())
                current = []
            previous_lower = False
        else:
            if char.isupper() and previous_lower and current:
                tokens.append("".join(current).casefold())
                current = []
            current.append(char)
            previous_lower = char.islower()
    if current:
        tokens.append("".join(current).casefold())
    return set(tokens)


def _walk_producer_value(
        value: Any,
        limits: DSLPrototypeLimits,
        *,
        input_document: bool) -> int:
    """Iteratively enforce producer string/authority limits and count canonical input nodes."""

    nodes = 0
    stack = [value]
    while stack:
        item = stack.pop()
        nodes += 1
        if input_document and nodes > limits.max_input_nodes:
            _fail("INPUT_NODE_LIMIT")
        if type(item) is str:
            if len(item.encode("utf-8")) > limits.max_string_bytes:
                _fail("STRING_BYTE_LIMIT")
        elif type(item) is list:
            stack.extend(reversed(item))
        elif type(item) is dict:
            for key in item:
                if type(key) is not str:
                    _fail("PRODUCER_KEY_INVALID")
                if len(key.encode("utf-8")) > limits.max_string_bytes:
                    _fail("STRING_BYTE_LIMIT")
                lowered = key.casefold()
                if lowered in _AUTHORITY_FIELDS or _authority_tokens(key) & _AUTHORITY_TOKENS:
                    _fail("PRODUCER_AUTHORITY_FIELD_FORBIDDEN")
            stack.extend(reversed(list(item.values())))
    return nodes


def _parse_document(raw: bytes, limit: int, *, program: bool) -> Any:
    if type(raw) is not bytes:
        _fail("CANONICAL_BYTES_REQUIRED")
    if not raw or len(raw) > limit:
        _fail("PROGRAM_BYTE_LIMIT" if program else "INPUT_BYTE_LIMIT")
    try:
        return parse_canonical_json_bytes(raw, require_canonical=True)
    except (TransitionContractError, TypeError, ValueError, MemoryError, RecursionError):
        _fail("PROGRAM_CANONICAL_INVALID" if program else "INPUT_CANONICAL_INVALID")
    raise AssertionError("unreachable")


def _binding(value: Any, kind: str) -> tuple[Any, str]:
    obj = _exact_keys(value, ("schema", "kind", "digest", "value"), "INPUT_BINDING_INVALID")
    if obj["schema"] != DECLARATIVE_BINDING_SCHEMA or obj["kind"] != kind:
        _fail("INPUT_BINDING_INVALID")
    if type(obj["digest"]) is not str:
        _fail("INPUT_BINDING_INVALID")
    try:
        digest = canonical_digest(obj["value"])
    except (TransitionContractError, TypeError, ValueError, MemoryError, RecursionError):
        _fail("INPUT_BINDING_INVALID")
    if obj["digest"] != digest:
        _fail("INPUT_BINDING_DIGEST_MISMATCH")
    return obj["value"], digest


def _validate_input(value: Any, limits: DSLPrototypeLimits) -> tuple[dict[str, Any], dict[str, str], int]:
    input_nodes = _walk_producer_value(value, limits, input_document=True)
    obj = _exact_keys(
        value,
        ("schema", "request_id", "identity", "scope", "time", "facts"),
        "INPUT_SCHEMA_INVALID",
    )
    if obj["schema"] != DECLARATIVE_INPUT_SCHEMA or type(obj["request_id"]) is not str:
        _fail("INPUT_SCHEMA_INVALID")
    if type(obj["facts"]) is not dict:
        _fail("INPUT_FACTS_INVALID")
    identity, identity_digest = _binding(obj["identity"], "IDENTITY")
    scope, scope_digest = _binding(obj["scope"], "SCOPE")
    time_value, time_digest = _binding(obj["time"], "TIME")
    roots = {"facts": obj["facts"], "identity": identity, "scope": scope, "time": time_value}
    digests = {
        "identity": identity_digest,
        "scope": scope_digest,
        "time": time_digest,
    }
    return roots, digests, input_nodes


def _path(value: Any, limits: DSLPrototypeLimits, *, scope_only: bool = False) -> tuple[str, ...]:
    if type(value) is not list or not value or len(value) > limits.max_path_segments:
        _fail("PATH_SEGMENT_LIMIT" if type(value) is list else "PATH_INVALID")
    if any(type(segment) is not str or not segment for segment in value):
        _fail("PATH_INVALID")
    if value[0] not in _ROOTS or (scope_only and value[0] != "scope"):
        _fail("PATH_ROOT_INVALID")
    return tuple(value)


def _canonical_operand(value: Any, limits: DSLPrototypeLimits) -> Any:
    try:
        canonical_json_bytes(value)
    except (TransitionContractError, TypeError, ValueError, MemoryError, RecursionError):
        _fail("OPERAND_CANONICAL_INVALID")
    return value


def _compile_expression(
        expression: Any,
        limits: DSLPrototypeLimits,
        node_counter: list[int]) -> tuple[tuple[Any, ...], ...]:
    """Validate and compile one expression iteratively into deterministic postfix instructions."""

    instructions: list[tuple[Any, ...]] = []
    stack: list[tuple[Any, int, bool]] = [(expression, 1, False)]
    while stack:
        node, depth, exiting = stack.pop()
        if type(node) is not dict:
            _fail("EXPRESSION_INVALID")
        op = node.get("op")
        if op not in DECLARATIVE_DSL_OPERATORS:
            _fail("OPERATOR_UNSUPPORTED")
        if not exiting:
            if depth > limits.max_expression_depth:
                _fail("EXPRESSION_DEPTH_LIMIT")
            node_counter[0] += 1
            if node_counter[0] > limits.max_expression_nodes:
                _fail("EXPRESSION_NODE_LIMIT")
            children: list[Any] = []
            if op in ("ALL_OF", "ANY_OF"):
                obj = _exact_keys(node, ("op", "args"), "EXPRESSION_SCHEMA_INVALID")
                args = obj["args"]
                if type(args) is not list or not args:
                    _fail("OPERATOR_OPERANDS_INVALID")
                if len(args) > limits.max_operator_operands:
                    _fail("OPERATOR_OPERAND_LIMIT")
                children = args
            elif op == "NOT":
                obj = _exact_keys(node, ("op", "arg"), "EXPRESSION_SCHEMA_INVALID")
                children = [obj["arg"]]
            elif op == "EXISTS":
                obj = _exact_keys(node, ("op", "path"), "EXPRESSION_SCHEMA_INVALID")
                _path(obj["path"], limits)
            elif op in ("EQUALS", "NOT_EQUALS"):
                obj = _exact_keys(node, ("op", "path", "value"), "EXPRESSION_SCHEMA_INVALID")
                _path(obj["path"], limits)
                _canonical_operand(obj["value"], limits)
            elif op == "IN_SET":
                obj = _exact_keys(node, ("op", "path", "values"), "EXPRESSION_SCHEMA_INVALID")
                _path(obj["path"], limits)
                values = obj["values"]
                if type(values) is not list or not values:
                    _fail("SET_INVALID")
                if len(values) > limits.max_set_items:
                    _fail("SET_ITEM_LIMIT")
                encoded = [canonical_json_bytes(_canonical_operand(item, limits)) for item in values]
                if encoded != sorted(set(encoded)):
                    _fail("SET_SORTED_UNIQUE_REQUIRED")
            elif op == "MATCH_SCOPE":
                obj = _exact_keys(
                    node,
                    ("op", "fact_path", "scope_path"),
                    "EXPRESSION_SCHEMA_INVALID",
                )
                _path(obj["fact_path"], limits)
                _path(obj["scope_path"], limits, scope_only=True)
            else:
                obj = _exact_keys(node, ("op", "profile_path"), "EXPRESSION_SCHEMA_INVALID")
                _path(obj["profile_path"], limits)
            stack.append((node, depth, True))
            for child in reversed(children):
                stack.append((child, depth + 1, False))
            continue

        if op in ("ALL_OF", "ANY_OF"):
            instructions.append((op, len(node["args"])))
        elif op == "NOT":
            instructions.append((op,))
        elif op == "EXISTS":
            instructions.append((op, tuple(node["path"])))
        elif op in ("EQUALS", "NOT_EQUALS"):
            instructions.append((op, tuple(node["path"]), node["value"]))
        elif op == "IN_SET":
            instructions.append((op, tuple(node["path"]), tuple(node["values"])))
        elif op == "MATCH_SCOPE":
            instructions.append((op, tuple(node["fact_path"]), tuple(node["scope_path"])))
        else:
            instructions.append((op, tuple(node["profile_path"])))
    return tuple(instructions)


def _compile_program(value: Any, limits: DSLPrototypeLimits) -> _CompiledProgram:
    _walk_producer_value(value, limits, input_document=False)
    obj = _exact_keys(
        value,
        ("schema", "program_id", "program_version", "abi_version", "pack_id", "pack_version", "rules"),
        "PROGRAM_SCHEMA_INVALID",
    )
    if obj["schema"] != DECLARATIVE_PROGRAM_SCHEMA or obj["abi_version"] != PACK_ABI_VERSION:
        _fail("PROGRAM_SCHEMA_INVALID")
    for key in ("program_id", "program_version", "pack_id", "pack_version"):
        _identifier(obj[key])
    rules = obj["rules"]
    if type(rules) is not list or not rules:
        _fail("PROGRAM_RULES_INVALID")
    if len(rules) > limits.max_rules:
        _fail("RULE_LIMIT")

    compiled: list[_CompiledRule] = []
    node_counter = [0]
    sort_keys: list[tuple[int, str]] = []
    for rule in rules:
        item = _exact_keys(rule, ("function", "rule_id", "when", "emit"), "RULE_SCHEMA_INVALID")
        function = item["function"]
        if function not in _RULE_FUNCTIONS:
            _fail("RULE_FUNCTION_UNSUPPORTED")
        rule_id = _identifier(item["rule_id"])
        emit = _canonical_operand(item["emit"], limits)
        instructions = _compile_expression(item["when"], limits, node_counter)
        compiled.append(_CompiledRule(function, rule_id, instructions, emit))
        sort_keys.append((PACK_ABI_FUNCTIONS.index(function), rule_id))
    if sort_keys != sorted(set(sort_keys)):
        _fail("RULE_SORTED_UNIQUE_REQUIRED")
    return _CompiledProgram(tuple(compiled), node_counter[0])


def _consume(work: _Work, amount: int, limits: DSLPrototypeLimits) -> None:
    work.fuel_consumed += amount
    if work.fuel_consumed > limits.max_instruction_fuel:
        _fail("INSTRUCTION_FUEL_LIMIT")


def _lookup(roots: Mapping[str, Any], path: tuple[str, ...], work: _Work, limits: DSLPrototypeLimits) -> Any:
    current: Any = roots
    for segment in path:
        _consume(work, 1, limits)
        if type(current) is not dict or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _same(
        left: Any,
        right: Any,
        work: _Work,
        limits: DSLPrototypeLimits) -> bool:
    try:
        left_raw = canonical_json_bytes(left)
        right_raw = canonical_json_bytes(right)
    except (TransitionContractError, TypeError, ValueError, MemoryError, RecursionError):
        _fail("OPERAND_CANONICAL_INVALID")
    byte_work = len(left_raw) + len(right_raw)
    _consume(
        work,
        max(1, (byte_work + FUEL_CANONICAL_BYTE_QUANTUM - 1) // FUEL_CANONICAL_BYTE_QUANTUM),
        limits,
    )
    return left_raw == right_raw


def _evaluate(
        instructions: tuple[tuple[Any, ...], ...],
        roots: Mapping[str, Any],
        work: _Work,
        limits: DSLPrototypeLimits) -> str:
    values: list[str] = []
    for instruction in instructions:
        _consume(work, 1, limits)
        op = instruction[0]
        if op in ("ALL_OF", "ANY_OF"):
            count = instruction[1]
            operands = values[-count:]
            del values[-count:]
            if op == "ALL_OF":
                result = (
                    TRUTH_FALSE if TRUTH_FALSE in operands
                    else TRUTH_INCONCLUSIVE if TRUTH_INCONCLUSIVE in operands
                    else TRUTH_TRUE
                )
            else:
                result = (
                    TRUTH_TRUE if TRUTH_TRUE in operands
                    else TRUTH_INCONCLUSIVE if TRUTH_INCONCLUSIVE in operands
                    else TRUTH_FALSE
                )
        elif op == "NOT":
            operand = values.pop()
            result = {
                TRUTH_TRUE: TRUTH_FALSE,
                TRUTH_FALSE: TRUTH_TRUE,
                TRUTH_INCONCLUSIVE: TRUTH_INCONCLUSIVE,
            }[operand]
        elif op == "EXISTS":
            result = TRUTH_FALSE if _lookup(roots, instruction[1], work, limits) is _MISSING else TRUTH_TRUE
        elif op in ("EQUALS", "NOT_EQUALS"):
            actual = _lookup(roots, instruction[1], work, limits)
            if actual is _MISSING:
                result = TRUTH_INCONCLUSIVE
            else:
                equal = _same(actual, instruction[2], work, limits)
                result = TRUTH_TRUE if equal == (op == "EQUALS") else TRUTH_FALSE
        elif op == "IN_SET":
            actual = _lookup(roots, instruction[1], work, limits)
            if actual is _MISSING:
                result = TRUTH_INCONCLUSIVE
            else:
                matched = False
                for item in instruction[2]:
                    if _same(actual, item, work, limits):
                        matched = True
                result = TRUTH_TRUE if matched else TRUTH_FALSE
        elif op == "MATCH_SCOPE":
            fact = _lookup(roots, instruction[1], work, limits)
            scope = _lookup(roots, instruction[2], work, limits)
            result = (
                TRUTH_INCONCLUSIVE
                if fact is _MISSING or scope is _MISSING
                else TRUTH_TRUE if _same(fact, scope, work, limits) else TRUTH_FALSE
            )
        else:
            _lookup(roots, instruction[1], work, limits)
            result = TRUTH_INCONCLUSIVE
        values.append(result)
    if len(values) != 1 or values[0] not in TRUTH_VALUES:
        _fail("EXPRESSION_EVALUATION_INVALID")
    return values[0]


def _authority_envelope(
        *,
        outcome: str,
        function: str | None,
        program_digest: str | None,
        input_digest: str | None,
        binding_digests: Mapping[str, str] | None,
        limits: DSLPrototypeLimits,
        work: _Work,
        result: Mapping[str, Any] | None,
        result_digest: str | None,
        error: str | None) -> dict[str, Any]:
    limit_profile = {field_name: getattr(limits, field_name) for field_name in DSL_PROTOTYPE_LIMIT_FIELDS}
    return {
        "schema": DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA,
        "interpreter_semantics_version": DECLARATIVE_INTERPRETER_SEMANTICS_VERSION,
        "limit_profile": limit_profile,
        "limit_profile_digest": canonical_digest(limit_profile),
        "outcome": outcome,
        "authoritative": False,
        "supplies_obligation_support": False,
        "qualification_effect": "NONE",
        "authoritative_gate": None,
        "promotion_eligible": False,
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
        "program_digest": program_digest,
        "input_digest": input_digest,
        "binding_digests": dict(binding_digests) if binding_digests is not None else None,
        "function": function,
        "work_units": {
            "program_bytes": work.program_bytes,
            "input_bytes": work.input_bytes,
            "input_nodes": work.input_nodes,
            "rules": work.rules,
            "expression_nodes": work.expression_nodes,
            "fuel_consumed": work.fuel_consumed,
            "result_bytes": work.result_bytes,
            "result_records": work.result_records,
        },
        "result": dict(result) if result is not None else None,
        "result_digest": result_digest,
        "error": {"code": error} if error is not None else None,
    }


def run_pack_abi(
        function: str,
        program_raw: bytes,
        input_raw: bytes,
        *,
        limits: DSLPrototypeLimits = DEFAULT_DSL_PROTOTYPE_LIMITS) -> bytes:
    """Execute one closed ABI call and return a deterministic, non-authoritative receipt.

    Known producer and resource failures are receipts, not partially returned results.  A non-bytes
    argument cannot carry an exact digest and therefore raises a fixed ``DSLPrototypeError`` before
    any receipt can be minted.  ``max_output_bytes`` meters the untrusted producer result; the small
    trusted refusal envelope remains available even when the producer exceeds that limit.
    """

    if type(limits) is not DSLPrototypeLimits:
        _fail("LIMIT_PROFILE_INVALID")
    if type(program_raw) is not bytes or type(input_raw) is not bytes:
        _fail("CANONICAL_BYTES_REQUIRED")
    # Refuse unbounded bytes before hashing them.  A digest over an attacker-controlled object is
    # itself linear work, so computing it before the byte guard would make that guard dishonest.
    # The unbound oversized side is explicitly null in the refusal receipt; bounded sides retain
    # their exact digest, and no partial producer result is returned.
    program_within_limit = bool(program_raw) and len(program_raw) <= limits.max_program_bytes
    input_within_limit = bool(input_raw) and len(input_raw) <= limits.max_input_bytes
    program_digest = bytes_digest(program_raw) if program_within_limit else None
    input_digest = bytes_digest(input_raw) if input_within_limit else None
    safe_function = function if type(function) is str and function in PACK_ABI_FUNCTIONS else None
    work = _Work(program_bytes=len(program_raw), input_bytes=len(input_raw))
    binding_digests: dict[str, str] | None = None
    try:
        if safe_function is None:
            _fail("ABI_FUNCTION_UNSUPPORTED")
        if not program_within_limit:
            _fail("PROGRAM_BYTE_LIMIT")
        if not input_within_limit:
            _fail("INPUT_BYTE_LIMIT")
        if safe_function == "replay_witness":
            _fail("REPLAY_WITNESS_UNSUPPORTED_R2_0")
        program_value = _parse_document(program_raw, limits.max_program_bytes, program=True)
        input_value = _parse_document(input_raw, limits.max_input_bytes, program=False)
        compiled = _compile_program(program_value, limits)
        roots, binding_digests, input_nodes = _validate_input(input_value, limits)
        work.rules = len(compiled.rules)
        work.expression_nodes = compiled.expression_nodes
        work.input_nodes = input_nodes
        entries: list[dict[str, Any]] = []
        for rule in compiled.rules:
            if rule.function != safe_function:
                continue
            truth = _evaluate(rule.instructions, roots, work, limits)
            entries.append(
                {"rule_id": rule.rule_id, "truth": truth, "value": rule.emit if truth == TRUTH_TRUE else None}
            )
            work.result_records += 1
            if work.result_records > limits.max_rules:
                _fail("RULE_LIMIT")
        result = {"schema": DECLARATIVE_RESULT_SCHEMA, "entries": entries}
        try:
            result_raw = canonical_json_bytes(result)
        except (TransitionContractError, TypeError, ValueError, MemoryError, RecursionError):
            _fail("RESULT_CANONICAL_INVALID")
        work.result_bytes = len(result_raw)
        if work.result_bytes > limits.max_output_bytes:
            _fail("OUTPUT_BYTE_LIMIT")
        receipt = _authority_envelope(
            outcome=_EXECUTED,
            function=safe_function,
            program_digest=program_digest,
            input_digest=input_digest,
            binding_digests=binding_digests,
            limits=limits,
            work=work,
            result=result,
            result_digest=bytes_digest(result_raw),
            error=None,
        )
    except DSLPrototypeError as exc:
        receipt = _authority_envelope(
            outcome=_REFUSED,
            function=safe_function,
            program_digest=program_digest,
            input_digest=input_digest,
            binding_digests=binding_digests,
            limits=limits,
            work=work,
            result=None,
            result_digest=None,
            error=exc.code,
        )
    return canonical_json_bytes(receipt)


def bind_packaged_dsl_prototype_bytes(
        pack_manifest_raw: bytes,
        tcb_manifest_raw: bytes,
        program_raw: bytes,
        denominator_raw: bytes,
        source_bytes_by_path: Mapping[str, bytes]) -> BoundPackagedDSLPrototype:
    """Join exact packaged assets to the TCB roster without treating self-checks as provenance.

    The caller supplies already-read bytes.  This binder performs no filesystem, environment,
    clock, or network access, and the evaluator never receives the source mapping.  Matching bytes
    establish only that one checkout/package is internally coherent; they are not an independent
    signature, selected-commit binding, qualification, or sandbox proof.
    """

    try:
        if any(
                type(raw) is not bytes
                for raw in (pack_manifest_raw, tcb_manifest_raw, program_raw, denominator_raw)
        ):
            _fail("PROTOTYPE_CUSTODY_BYTES_REQUIRED")
        if type(source_bytes_by_path) is not dict or any(
                type(path) is not str or type(raw) is not bytes
                for path, raw in source_bytes_by_path.items()
        ):
            _fail("PROTOTYPE_SOURCE_SET_INVALID")
        pack = bind_pack_manifest_bytes(pack_manifest_raw)
        tcb = bind_tcb_manifest_bytes(tcb_manifest_raw)
        validate_pack_tcb_pair(pack, tcb)
        if (
                pack["pack_id"] != DSL_PROTOTYPE_PACK_ID
                or pack["pack_version"] != DSL_PROTOTYPE_PACK_VERSION
                or pack["qualification_state"] != QualificationState.EXPERIMENTAL.value
                or pack["execution_state"] != PackExecutionState.CONTRACT_ONLY.value
                or pack["substrate"] != PackSubstrate.DECLARATIVE_DSL_ONLY.value
                or pack["wasm_modules"]
                or pack["claim_boundary"] != DSL_PROTOTYPE_CLAIM_BOUNDARY
        ):
            _fail("PROTOTYPE_PACK_BOUNDARY_INVALID")

        program_value = _parse_document(
            program_raw,
            DEFAULT_DSL_PROTOTYPE_LIMITS.max_program_bytes,
            program=True,
        )
        _compile_program(program_value, DEFAULT_DSL_PROTOTYPE_LIMITS)
        if (
                program_value["pack_id"] != pack["pack_id"]
                or program_value["pack_version"] != pack["pack_version"]
        ):
            _fail("PROTOTYPE_PROGRAM_IDENTITY_MISMATCH")
        program_digest = bytes_digest(program_raw)
        if (
                pack["declarative_rules_digest"] != program_digest
                or pack["semantic_bundle_digest"] != program_digest
        ):
            _fail("PROTOTYPE_PROGRAM_DIGEST_MISMATCH")

        denominator_value = parse_canonical_json_bytes(denominator_raw, require_canonical=True)
        denominator = validate_qualification_denominator(denominator_value, "$")
        denominator_digest = canonical_digest(denominator)
        if denominator_digest != bytes_digest(denominator_raw) or any(
                digest != denominator_digest
                for digest in (
                    pack["supported_denominator_digest"],
                    tcb["supported_denominator_digest"],
                )
        ):
            _fail("PROTOTYPE_DENOMINATOR_DIGEST_MISMATCH")

        roster = [*tcb["core_sources"], *tcb["pack_sources"]]
        expected_paths = {item["path"] for item in roster}
        if set(source_bytes_by_path) != expected_paths:
            _fail("PROTOTYPE_SOURCE_SET_MISMATCH")
        source_rows: list[tuple[str, int, str]] = []
        for item in roster:
            raw = source_bytes_by_path[item["path"]]
            digest = bytes_digest(raw)
            if len(raw) != item["bytes"] or digest != item["digest"]:
                _fail("PROTOTYPE_SOURCE_DIGEST_MISMATCH")
            source_rows.append((item["path"], len(raw), digest))
        source_rows.sort()
        if (
                DSL_INTERPRETER_SOURCE_PATH not in source_bytes_by_path
                or DSL_PROTOTYPE_PROGRAM_PATH not in source_bytes_by_path
                or DSL_PROTOTYPE_DENOMINATOR_PATH not in source_bytes_by_path
                or source_bytes_by_path[DSL_PROTOTYPE_PROGRAM_PATH] != program_raw
                or source_bytes_by_path[DSL_PROTOTYPE_DENOMINATOR_PATH] != denominator_raw
                or bytes_digest(source_bytes_by_path[DSL_INTERPRETER_SOURCE_PATH])
                != tcb["dsl_interpreter"]["content_digest"]
        ):
            _fail("PROTOTYPE_REQUIRED_SOURCE_BINDING_MISMATCH")
    except DSLPrototypeError:
        raise
    except (KeyError, PackContractError, TransitionContractError, TypeError, ValueError):
        _fail("PROTOTYPE_CUSTODY_INVALID")
    return BoundPackagedDSLPrototype(
        pack=pack,
        tcb=tcb,
        program_raw=program_raw,
        denominator_digest=denominator_digest,
        source_rows=tuple(source_rows),
        _authority=_BOUND_PROTOTYPE_AUTHORITY,
    )


def require_bound_packaged_dsl_prototype(value: Any) -> BoundPackagedDSLPrototype:
    if type(value) is not BoundPackagedDSLPrototype:
        _fail("DETACHED_PROTOTYPE_CUSTODY")
    try:
        require_bound_pack_manifest(value._pack)
        require_bound_tcb_manifest(value._tcb)
        intact = value._compute_integrity_digest() == value._integrity_digest
    except (AttributeError, PackContractError, TransitionContractError, TypeError, ValueError):
        intact = False
    if not intact:
        _fail("BOUND_PROTOTYPE_CUSTODY_MUTATED")
    return value


def run_bound_pack_abi(
        prototype: BoundPackagedDSLPrototype,
        function: str,
        input_raw: bytes,
        *,
        limits: DSLPrototypeLimits = DEFAULT_DSL_PROTOTYPE_LIMITS) -> bytes:
    """Run the pure interpreter and wrap its receipt in exact non-authoritative TCB custody."""

    bound = require_bound_packaged_dsl_prototype(prototype)
    inner_raw = run_pack_abi(function, bound._program_raw, input_raw, limits=limits)
    try:
        inner = parse_canonical_json_bytes(inner_raw, require_canonical=True)
    except (TransitionContractError, TypeError, ValueError):
        _fail("PROTOTYPE_INNER_RECEIPT_INVALID")
    outer = {
        "schema": BOUND_DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA,
        "source_binding_state": DSL_PROTOTYPE_SOURCE_BINDING_STATE,
        "pack_id": bound._pack["pack_id"],
        "pack_version": bound._pack["pack_version"],
        "pack_manifest_digest": bound._pack.digest,
        "tcb_manifest_digest": bound._tcb.digest,
        "program_digest": bound._program_digest,
        "supported_denominator_digest": bound._denominator_digest,
        "interpreter_digest": bound.interpreter_digest,
        "inner_receipt_digest": bytes_digest(inner_raw),
        "inner_receipt": inner,
        "authoritative": False,
        "supplies_obligation_support": False,
        "qualification_effect": "NONE",
        "authoritative_gate": None,
        "promotion_eligible": False,
    }
    return canonical_json_bytes(outer)


__all__ = [
    "BOUND_DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA",
    "DECLARATIVE_BINDING_SCHEMA",
    "DECLARATIVE_INPUT_SCHEMA",
    "DECLARATIVE_INTERPRETER_SEMANTICS_VERSION",
    "DECLARATIVE_PROGRAM_SCHEMA",
    "DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA",
    "DECLARATIVE_RESULT_SCHEMA",
    "DSL_INTERPRETER_SOURCE_PATH",
    "DSL_PROTOTYPE_CLAIM_BOUNDARY",
    "DSL_PROTOTYPE_DENOMINATOR_PATH",
    "DSL_PROTOTYPE_INPUT_PATH",
    "DSL_PROTOTYPE_PACK_MANIFEST_PATH",
    "DSL_PROTOTYPE_PACK_ID",
    "DSL_PROTOTYPE_PACK_VERSION",
    "DSL_PROTOTYPE_PROGRAM_PATH",
    "DSL_PROTOTYPE_SOURCE_BINDING_STATE",
    "DSL_PROTOTYPE_TCB_MANIFEST_PATH",
    "DEFAULT_DSL_PROTOTYPE_LIMITS",
    "DSL_PROTOTYPE_LIMIT_FIELDS",
    "DSLPrototypeError",
    "DSLPrototypeLimits",
    "BoundPackagedDSLPrototype",
    "FUEL_CANONICAL_BYTE_QUANTUM",
    "TRUTH_FALSE",
    "TRUTH_INCONCLUSIVE",
    "TRUTH_TRUE",
    "TRUTH_VALUES",
    "bind_packaged_dsl_prototype_bytes",
    "require_bound_packaged_dsl_prototype",
    "run_bound_pack_abi",
    "run_pack_abi",
]
