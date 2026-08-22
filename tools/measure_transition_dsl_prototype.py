#!/usr/bin/env python3
"""Build or verify deterministic Atlas R2 DSL prototype measurements.

The committed artifact is reference evidence, not an approved resource budget. ``--update`` is the
only mode that captures three raw elapsed/tracemalloc observations for each executed boundary. The
default mode recomputes all semantic receipts, byte counts, and digests while reusing only those
committed performance observations and the recorded reference environment, so it is portable in
the same way as the structural TCB census.

No wall-clock value enters a DSL receipt. If an output boundary is preempted by the stricter
program-byte guard, it is reported as unreachable and a diagnostic relaxes only that dominating
guard. The tool detects this relationship from the shipped profile instead of assuming it.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import gc
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cisco_toolkit import transition_contract as contract  # noqa: E402
from cisco_toolkit import transition_dsl as dsl  # noqa: E402


SCHEMA = "atlas.dsl-prototype-measurements/1"
RESOURCE = "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json"
TOOL_PATH = "tools/measure_transition_dsl_prototype.py"
MEASUREMENT_ID = "atlas-r2-dsl-prototype-measurements.001"
BOUNDARY_LABELS = ("N_MINUS_1", "N", "N_PLUS_1")
SEMANTIC_REPEATS = 2
PERFORMANCE_REPEATS = 3
CANARY = "ATLAS-SECRET-CANARY-DO-NOT-ECHO"

TEST_OWNERS = {
    "max_program_bytes": (
        "tests/test_transition_dsl.py::"
        "test_program_byte_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_input_bytes": (
        "tests/test_transition_dsl.py::"
        "test_input_byte_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_output_bytes": (
        "tests/test_transition_dsl.py::"
        "test_output_byte_limit_has_n_minus_1_n_n_plus_1_behavior_and_no_partial_result"
    ),
    "max_rules": (
        "tests/test_transition_dsl.py::test_rule_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_expression_depth": (
        "tests/test_transition_dsl.py::"
        "test_expression_depth_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_expression_nodes": (
        "tests/test_transition_dsl.py::"
        "test_expression_node_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_operator_operands": (
        "tests/test_transition_dsl.py::"
        "test_operator_operand_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_path_segments": (
        "tests/test_transition_dsl.py::"
        "test_path_segment_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_string_bytes": (
        "tests/test_transition_dsl.py::"
        "test_string_byte_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_set_items": (
        "tests/test_transition_dsl.py::"
        "test_set_item_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_input_nodes": (
        "tests/test_transition_dsl.py::"
        "test_input_node_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
    "max_instruction_fuel": (
        "tests/test_transition_dsl.py::"
        "test_instruction_fuel_limit_has_n_minus_1_n_n_plus_1_behavior"
    ),
}


def _binding(kind: str, value: Any) -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_BINDING_SCHEMA,
        "kind": kind,
        "digest": contract.canonical_digest(value),
        "value": value,
    }


def _input(*, facts: dict[str, Any] | None = None, request_id: str = "measure-001") -> dict[str, Any]:
    identity = {"transition_id": "synthetic-transition"}
    scope = {"site_id": "synthetic-site"}
    time_value = {"observed_at": "2026-08-22T00:00:00.000000Z"}
    return {
        "schema": dsl.DECLARATIVE_INPUT_SCHEMA,
        "request_id": request_id,
        "identity": _binding("IDENTITY", identity),
        "scope": _binding("SCOPE", scope),
        "time": _binding("TIME", time_value),
        "facts": facts if facts is not None else {"enabled": True, "probe": -1},
    }


def _rule(
        rule_id: str,
        when: dict[str, Any],
        *,
        function: str = "evaluate",
        emit: Any = "matched") -> dict[str, Any]:
    return {"function": function, "rule_id": rule_id, "when": when, "emit": emit}


def _program(
        rules: list[dict[str, Any]] | None = None,
        *,
        program_id: str = "measure.001") -> dict[str, Any]:
    actual_rules = rules if rules is not None else [
        _rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]})
    ]
    return {
        "schema": dsl.DECLARATIVE_PROGRAM_SCHEMA,
        "program_id": program_id,
        "program_version": "0.1.0-experimental",
        "abi_version": contract.PACK_ABI_VERSION,
        "pack_id": "atlas-r2-measurement-fixture",
        "pack_version": "0.1.0-experimental",
        "rules": actual_rules,
    }


def _raw(value: Any) -> bytes:
    return contract.canonical_json_bytes(value)


def _asset(repository: Path, relative: str) -> tuple[bytes, dict[str, Any]]:
    raw = (repository / relative).read_bytes()
    return raw, {
        "path": relative,
        "raw_bytes": len(raw),
        "digest": contract.bytes_digest(raw),
    }


def _chunks_for_exact_size(
        target: int,
        build: Callable[[list[str]], bytes],
        max_string_bytes: int) -> list[str]:
    """Find deterministic ASCII string chunks whose canonical document has exactly target bytes."""

    for count in range(1, 1_024):
        empty_size = len(build([""] * count))
        characters = target - empty_size
        if 0 <= characters <= count * max_string_bytes:
            chunks: list[str] = []
            remaining = characters
            for _index in range(count):
                size = min(max_string_bytes, remaining)
                chunks.append("x" * size)
                remaining -= size
            raw = build(chunks)
            if remaining == 0 and len(raw) == target:
                return chunks
    raise RuntimeError(f"could not construct exact canonical size {target}")


def _program_with_exact_bytes(target: int) -> bytes:
    def build(chunks: list[str]) -> bytes:
        rules = [
            _rule(
                "rule.001",
                {"op": "EXISTS", "path": ["facts", "enabled"]},
                function="manifest",
                emit=chunks,
            )
        ]
        return _raw(_program(rules))

    chunks = _chunks_for_exact_size(
        target,
        build,
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_string_bytes,
    )
    return build(chunks)


def _input_with_exact_bytes(target: int) -> bytes:
    def build(chunks: list[str]) -> bytes:
        return _raw(_input(facts={"enabled": True, "padding": chunks}))

    chunks = _chunks_for_exact_size(
        target,
        build,
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_string_bytes,
    )
    return build(chunks)


def _result_size_for_emit(emit: Any) -> int:
    result = {
        "schema": dsl.DECLARATIVE_RESULT_SCHEMA,
        "entries": [{"rule_id": "rule.001", "truth": dsl.TRUTH_TRUE, "value": emit}],
    }
    return len(_raw(result))


def _program_with_exact_output_bytes(target: int) -> bytes:
    def build_result(chunks: list[str]) -> bytes:
        result = {
            "schema": dsl.DECLARATIVE_RESULT_SCHEMA,
            "entries": [{"rule_id": "rule.001", "truth": dsl.TRUTH_TRUE, "value": chunks}],
        }
        return _raw(result)

    chunks = _chunks_for_exact_size(
        target,
        build_result,
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_string_bytes,
    )
    if _result_size_for_emit(chunks) != target:
        raise RuntimeError("output-size construction drifted")
    return _raw(_program([
        _rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]}, emit=chunks)
    ]))


def _not_depth(depth: int) -> dict[str, Any]:
    expression: dict[str, Any] = {"op": "EXISTS", "path": ["facts", "enabled"]}
    for _index in range(depth - 1):
        expression = {"op": "NOT", "arg": expression}
    return expression


def _expression_with_nodes(total_nodes: int) -> dict[str, Any]:
    if total_nodes < 1:
        raise ValueError("expression node count must be positive")
    leaf = {"op": "EXISTS", "path": ["facts"]}
    if total_nodes == 1:
        return leaf
    remaining = total_nodes - 1
    children: list[dict[str, Any]] = []
    while remaining:
        subtree_size = min(257, remaining)
        if subtree_size == 1:
            child = leaf
        else:
            child = {"op": "ANY_OF", "args": [leaf for _index in range(subtree_size - 1)]}
        children.append(child)
        remaining -= subtree_size
    if len(children) > dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_operator_operands:
        raise RuntimeError("expression-node construction exceeded operand guard")
    return {"op": "ANY_OF", "args": children}


def _canonical_sorted_integers(count: int) -> list[int]:
    return sorted(range(count), key=lambda item: _raw(item))


def _in_set(count: int) -> dict[str, Any]:
    return {
        "op": "IN_SET",
        "path": ["facts", "probe"],
        "values": _canonical_sorted_integers(count),
    }


def _count_nodes(value: Any) -> int:
    count = 0
    stack = [value]
    while stack:
        item = stack.pop()
        count += 1
        if type(item) is list:
            stack.extend(item)
        elif type(item) is dict:
            stack.extend(item.values())
    return count


def _input_with_nodes(target: int) -> bytes:
    empty = _input(facts={"values": []})
    base = _count_nodes(empty)
    if target < base:
        raise RuntimeError("input-node target is smaller than structural input envelope")
    value = _input(facts={"values": [0] * (target - base)})
    if _count_nodes(value) != target:
        raise RuntimeError("input-node construction drifted")
    return _raw(value)


def _fuel_program(target: int) -> bytes:
    """Construct comparisons whose charged work reaches an exact default-profile fuel target."""

    per_full_rule = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_set_items + 3
    full_rules, remainder = divmod(target, per_full_rule)
    counts = [dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_set_items] * full_rules
    if remainder:
        if remainder < 4:
            if not counts:
                raise RuntimeError("fuel target cannot be represented")
            counts[-1] -= 4 - remainder
            remainder = 4
        counts.append(remainder - 3)
    rules = [
        _rule(f"rule.{index:04d}", _in_set(count))
        for index, count in enumerate(counts)
    ]
    return _raw(_program(rules))


def _case_raw(dimension: str, target: int) -> tuple[bytes, bytes]:
    input_raw = _raw(_input())
    if dimension == "max_program_bytes":
        return _program_with_exact_bytes(target), input_raw
    if dimension == "max_input_bytes":
        return _raw(_program()), _input_with_exact_bytes(target)
    if dimension == "max_output_bytes":
        return _program_with_exact_output_bytes(target), input_raw
    if dimension == "max_rules":
        rules = [
            _rule(f"rule.{index:04d}", {"op": "EXISTS", "path": ["facts", "enabled"]})
            for index in range(target)
        ]
        return _raw(_program(rules)), input_raw
    if dimension == "max_expression_depth":
        return _raw(_program([_rule("rule.001", _not_depth(target))])), input_raw
    if dimension == "max_expression_nodes":
        return _raw(_program([_rule("rule.001", _expression_with_nodes(target))])), input_raw
    if dimension == "max_operator_operands":
        expression = {
            "op": "ANY_OF",
            "args": [
                {"op": "EXISTS", "path": ["facts"]}
                for _index in range(target)
            ],
        }
        return _raw(_program([_rule("rule.001", expression)])), input_raw
    if dimension == "max_path_segments":
        expression = {"op": "EXISTS", "path": ["facts"] + ["nested"] * (target - 1)}
        return _raw(_program([_rule("rule.001", expression)])), input_raw
    if dimension == "max_string_bytes":
        return _raw(_program()), _raw(_input(facts={"payload": "x" * target}))
    if dimension == "max_set_items":
        return _raw(_program([_rule("rule.001", _in_set(target))])), input_raw
    if dimension == "max_input_nodes":
        return _raw(_program()), _input_with_nodes(target)
    if dimension == "max_instruction_fuel":
        return _fuel_program(target), input_raw
    raise RuntimeError(f"unknown limit dimension: {dimension}")


def _returned_result_bytes(receipt: Mapping[str, Any]) -> int:
    result = receipt["result"]
    return 0 if result is None else len(_raw(result))


def _authority(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "authoritative": receipt["authoritative"],
        "supplies_obligation_support": receipt["supplies_obligation_support"],
        "qualification_effect": receipt["qualification_effect"],
        "authoritative_gate": receipt["authoritative_gate"],
        "promotion_eligible": receipt["promotion_eligible"],
        "execution_state": receipt["execution_state"],
        "qualification_state": receipt["qualification_state"],
    }


def _run_twice(
        program_raw: bytes,
        input_raw: bytes,
        *,
        limits: dsl.DSLPrototypeLimits = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS,
        function: str = "evaluate") -> tuple[bytes, dict[str, Any], list[str]]:
    receipts = [dsl.run_pack_abi(function, program_raw, input_raw, limits=limits)
                for _index in range(SEMANTIC_REPEATS)]
    digests = [contract.bytes_digest(raw) for raw in receipts]
    if len(set(receipts)) != 1:
        raise RuntimeError("prototype receipt was not canonically repeatable")
    receipt = contract.parse_canonical_json_bytes(receipts[0], require_canonical=True)
    return receipts[0], receipt, digests


def _observe(call: Callable[[], bytes]) -> dict[str, int]:
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter_ns()
    raw = call()
    elapsed = time.perf_counter_ns() - start
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if type(raw) is not bytes:
        raise RuntimeError("measurement call did not return bytes")
    return {"elapsed_ns": elapsed, "tracemalloc_peak_bytes": peak}


def _reference_observations(
        reference: Mapping[str, Any],
        group: str,
        case_id: str,
        label: str | None = None) -> list[dict[str, int]]:
    rows = reference.get(group)
    if type(rows) is not list:
        raise RuntimeError("committed measurement performance evidence is missing")
    row = next((item for item in rows if item.get("dimension", item.get("case_id")) == case_id), None)
    if type(row) is not dict:
        raise RuntimeError("committed measurement performance case is missing")
    if label is None:
        observations = row.get("performance_reference")
    else:
        boundaries = row.get("boundaries")
        boundary = next(
            (item for item in boundaries or [] if item.get("label") == label),
            None,
        )
        observations = boundary.get("performance_reference") if type(boundary) is dict else None
    if (
            type(observations) is not list
            or len(observations) != PERFORMANCE_REPEATS
            or any(
                type(item) is not dict
                or set(item) != {"elapsed_ns", "tracemalloc_peak_bytes"}
                or type(item["elapsed_ns"]) is not int
                or item["elapsed_ns"] < 1
                or type(item["tracemalloc_peak_bytes"]) is not int
                or item["tracemalloc_peak_bytes"] < 0
                for item in observations
            )
    ):
        raise RuntimeError("committed measurement performance observations are invalid")
    return observations


def _performance(
        call: Callable[[], bytes],
        reference: Mapping[str, Any] | None,
        group: str,
        case_id: str,
        label: str | None = None) -> list[dict[str, int]]:
    if reference is not None:
        return _reference_observations(reference, group, case_id, label)
    return [_observe(call) for _index in range(PERFORMANCE_REPEATS)]


def _expected_error(dimension: str, label: str) -> str | None:
    if label != "N_PLUS_1":
        return None
    return {
        "max_program_bytes": "PROGRAM_BYTE_LIMIT",
        "max_input_bytes": "INPUT_BYTE_LIMIT",
        "max_output_bytes": "OUTPUT_BYTE_LIMIT",
        "max_rules": "RULE_LIMIT",
        "max_expression_depth": "EXPRESSION_DEPTH_LIMIT",
        "max_expression_nodes": "EXPRESSION_NODE_LIMIT",
        "max_operator_operands": "OPERATOR_OPERAND_LIMIT",
        "max_path_segments": "PATH_SEGMENT_LIMIT",
        "max_string_bytes": "STRING_BYTE_LIMIT",
        "max_set_items": "SET_ITEM_LIMIT",
        "max_input_nodes": "INPUT_NODE_LIMIT",
        "max_instruction_fuel": "INSTRUCTION_FUEL_LIMIT",
    }.get(dimension)


def _dominance_evidence(
        program_raw: bytes,
        input_raw: bytes,
        target: int) -> dict[str, Any]:
    default = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS
    diagnostic_limits = replace(default, max_program_bytes=len(program_raw))
    raw, receipt, repeats = _run_twice(program_raw, input_raw, limits=diagnostic_limits)
    if receipt["work_units"]["result_bytes"] != target:
        raise RuntimeError("relaxed program guard did not reach the requested output boundary")
    expected = "OUTPUT_BYTE_LIMIT" if target == default.max_output_bytes + 1 else None
    actual = receipt["error"]["code"] if receipt["error"] is not None else None
    if actual != expected:
        raise RuntimeError("output diagnostic did not have the expected boundary outcome")
    return {
        "relaxed_guard": "max_program_bytes",
        "relaxed_guard_value": len(program_raw),
        "shipped_guard_value": default.max_program_bytes,
        "target_output_bytes": target,
        "diagnostic_receipt_bytes": len(raw),
        "diagnostic_receipt_digest": contract.bytes_digest(raw),
        "diagnostic_repeat_receipt_digests": repeats,
        "diagnostic_outcome": receipt["outcome"],
        "diagnostic_error": receipt["error"],
        "diagnostic_measured_producer_result_bytes": receipt["work_units"]["result_bytes"],
        "diagnostic_returned_result_bytes": _returned_result_bytes(receipt),
        "diagnostic_result_is_null": receipt["result"] is None,
        "authority": _authority(receipt),
    }


def _boundary(
        dimension: str,
        label: str,
        target: int,
        reference: Mapping[str, Any] | None) -> dict[str, Any]:
    program_raw, input_raw = _case_raw(dimension, target)
    receipt_raw, receipt, repeat_digests = _run_twice(program_raw, input_raw)
    actual_error = receipt["error"]["code"] if receipt["error"] is not None else None
    dominance: dict[str, Any] | None = None
    output_preempted = (
        dimension == "max_output_bytes"
        and len(program_raw) > dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_program_bytes
    )
    if output_preempted:
        expected_error = "PROGRAM_BYTE_LIMIT"
        dominance = _dominance_evidence(program_raw, input_raw, target)
    else:
        expected_error = _expected_error(dimension, label)
    if actual_error != expected_error:
        raise RuntimeError(
            f"{dimension} {label} expected {expected_error!r}, got {actual_error!r}"
        )
    if label == "N_PLUS_1" and (
            receipt["result"] is not None or _returned_result_bytes(receipt) != 0):
        raise RuntimeError(f"{dimension} N+1 returned a producer result")
    if _authority(receipt) != {
            "authoritative": False,
            "supplies_obligation_support": False,
            "qualification_effect": "NONE",
            "authoritative_gate": None,
            "promotion_eligible": False,
            "execution_state": "CONTRACT_ONLY",
            "qualification_state": "EXPERIMENTAL",
    }:
        raise RuntimeError("measurement receipt crossed the non-authority boundary")
    return {
        "label": label,
        "target_dimension_value": target,
        "raw_program_bytes": len(program_raw),
        "program_digest": contract.bytes_digest(program_raw),
        "raw_input_bytes": len(input_raw),
        "input_digest": contract.bytes_digest(input_raw),
        "raw_receipt_bytes": len(receipt_raw),
        "receipt_digest": contract.bytes_digest(receipt_raw),
        "repeat_receipt_digests": repeat_digests,
        "outcome": receipt["outcome"],
        "error": receipt["error"],
        "result_digest": receipt["result_digest"],
        "result_is_null": receipt["result"] is None,
        "returned_result_bytes": _returned_result_bytes(receipt),
        "measured_producer_result_bytes": receipt["work_units"]["result_bytes"],
        "work_units": receipt["work_units"],
        "authority": _authority(receipt),
        "dominance_evidence": dominance,
        "performance_reference": _performance(
            lambda: dsl.run_pack_abi("evaluate", program_raw, input_raw),
            reference,
            "boundary_measurements",
            dimension,
            label,
        ),
    }


def _boundary_measurements(reference: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    default = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS
    rows: list[dict[str, Any]] = []
    for dimension in dsl.DSL_PROTOTYPE_LIMIT_FIELDS:
        limit = getattr(default, dimension)
        output_preempted = dimension == "max_output_bytes" and any(
            len(_case_raw(dimension, target)[0]) > default.max_program_bytes
            for target in (limit - 1, limit, limit + 1)
        )
        reachability = (
            "UNREACHABLE_UNDER_STRICTER_BOUND"
            if output_preempted
            else "REACHABLE_AT_SHIPPED_DEFAULT"
        )
        blocker = None
        if output_preempted:
            blocker = {
                "dominating_guard": "max_program_bytes",
                "reason": (
                    "The canonical program carrying an output at N-1, N, or N+1 exceeds the "
                    "shipped max_program_bytes guard, which refuses before result construction."
                ),
                "review_effect": "BLOCKS_RESOURCE_CEILING_APPROVAL",
            }
        rows.append({
            "dimension": dimension,
            "shipped_default_limit": limit,
            "reachability": reachability,
            "injected_boundary_test_owner": TEST_OWNERS[dimension],
            "review_blocker": blocker,
            "boundaries": [
                _boundary(dimension, label, target, reference)
                for label, target in zip(BOUNDARY_LABELS, (limit - 1, limit, limit + 1))
            ],
        })
    return rows


def _hostile_raw_cases() -> list[tuple[str, bytes, bytes, str]]:
    input_raw = _raw(_input())
    baseline = _raw(_program())
    duplicate = baseline.replace(
        b'{"abi_version":"ATLAS_PACK_ABI/1",',
        b'{"abi_version":"ATLAS_PACK_ABI/1","abi_version":"ATLAS_PACK_ABI/1",',
        1,
    )
    float_raw = baseline.replace(b'"emit":"matched"', b'"emit":1.5', 1)
    hostile_key = _program()
    hostile_key[CANARY] = "producer-secret"
    hostile_path = _program([
        _rule("rule.001", {"op": "EXISTS", "path": ["environment", CANARY]})
    ])
    return [
        ("DUPLICATE_KEY", duplicate, input_raw, "PROGRAM_CANONICAL_INVALID"),
        ("FLOAT_LITERAL", float_raw, input_raw, "PROGRAM_CANONICAL_INVALID"),
        ("HOSTILE_KEY_CANARY", _raw(hostile_key), input_raw, "PROGRAM_SCHEMA_INVALID"),
        ("HOSTILE_PATH_CANARY", _raw(hostile_path), input_raw, "PATH_ROOT_INVALID"),
    ]


def _hostile_measurements(reference: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, program_raw, input_raw, expected_error in _hostile_raw_cases():
        receipt_raw, receipt, repeats = _run_twice(program_raw, input_raw)
        actual_error = receipt["error"]["code"] if receipt["error"] is not None else None
        if actual_error != expected_error:
            raise RuntimeError(f"{case_id} expected {expected_error}, got {actual_error}")
        if CANARY.encode("ascii") in receipt_raw or b"$." in receipt_raw:
            raise RuntimeError(f"{case_id} echoed hostile producer material")
        if receipt["result"] is not None or _returned_result_bytes(receipt) != 0:
            raise RuntimeError(f"{case_id} returned a producer result")
        rows.append({
            "case_id": case_id,
            "raw_program_bytes": len(program_raw),
            "program_digest": contract.bytes_digest(program_raw),
            "raw_input_bytes": len(input_raw),
            "input_digest": contract.bytes_digest(input_raw),
            "raw_receipt_bytes": len(receipt_raw),
            "receipt_digest": contract.bytes_digest(receipt_raw),
            "repeat_receipt_digests": repeats,
            "outcome": receipt["outcome"],
            "error": receipt["error"],
            "result_digest": receipt["result_digest"],
            "result_is_null": receipt["result"] is None,
            "returned_result_bytes": _returned_result_bytes(receipt),
            "canary_digest": contract.bytes_digest(CANARY.encode("ascii")),
            "canary_echoed_in_receipt": False,
            "parser_path_echoed_in_receipt": False,
            "authority": _authority(receipt),
            "performance_reference": _performance(
                lambda p=program_raw, i=input_raw: dsl.run_pack_abi("evaluate", p, i),
                reference,
                "hostile_measurements",
                case_id,
            ),
        })
    return rows


def _baseline_execution(
        repository: Path,
        pack_raw: bytes,
        tcb_raw: bytes,
        program_raw: bytes,
        denominator_raw: bytes,
        input_raw: bytes) -> dict[str, Any]:
    tcb = contract.parse_canonical_json_bytes(tcb_raw, require_canonical=True)
    source_map = {
        item["path"]: (repository / item["path"]).read_bytes()
        for item in [*tcb["core_sources"], *tcb["pack_sources"]]
    }
    prototype = dsl.bind_packaged_dsl_prototype_bytes(
        pack_raw,
        tcb_raw,
        program_raw,
        denominator_raw,
        source_map,
    )
    receipts = [
        dsl.run_bound_pack_abi(prototype, "evaluate", input_raw)
        for _index in range(SEMANTIC_REPEATS)
    ]
    if len(set(receipts)) != 1:
        raise RuntimeError("bound packaged baseline was not repeatable")
    receipt = contract.parse_canonical_json_bytes(receipts[0], require_canonical=True)
    inner = receipt["inner_receipt"]
    return {
        "raw_receipt_bytes": len(receipts[0]),
        "receipt_digest": contract.bytes_digest(receipts[0]),
        "repeat_receipt_digests": [contract.bytes_digest(raw) for raw in receipts],
        "source_binding_state": receipt["source_binding_state"],
        "inner_outcome": inner["outcome"],
        "inner_result_digest": inner["result_digest"],
        "inner_work_units": inner["work_units"],
        "authority": {
            "authoritative": receipt["authoritative"],
            "supplies_obligation_support": receipt["supplies_obligation_support"],
            "qualification_effect": receipt["qualification_effect"],
            "authoritative_gate": receipt["authoritative_gate"],
            "promotion_eligible": receipt["promotion_eligible"],
        },
    }


def _reference_environment() -> dict[str, Any]:
    executable = Path(sys.executable).resolve().read_bytes()
    return {
        "runtime": {
            "implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "cache_tag": sys.implementation.cache_tag,
            "executable_path_kind": "REFERENCE_ABSOLUTE_PATH_REDACTED",
            "executable_raw_bytes": len(executable),
            "executable_digest": contract.bytes_digest(executable),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "performance_observation_method": {
            "elapsed": "time.perf_counter_ns/RAW_REFERENCE_OBSERVATION_ONLY",
            "peak_memory": "tracemalloc.get_traced_memory.peak/RAW_REFERENCE_OBSERVATION_ONLY",
            "repeats": PERFORMANCE_REPEATS,
            "semantic_effect": "NONE",
        },
    }


def _build(repository: Path, *, reference: Mapping[str, Any] | None = None) -> bytes:
    pack_raw, pack_binding = _asset(repository, dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH)
    tcb_raw, tcb_binding = _asset(repository, dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH)
    program_raw, program_binding = _asset(repository, dsl.DSL_PROTOTYPE_PROGRAM_PATH)
    input_raw, input_binding = _asset(repository, dsl.DSL_PROTOTYPE_INPUT_PATH)
    denominator_raw, denominator_binding = _asset(repository, dsl.DSL_PROTOTYPE_DENOMINATOR_PATH)
    interpreter_raw, interpreter_binding = _asset(repository, dsl.DSL_INTERPRETER_SOURCE_PATH)
    tool_raw, tool_binding = _asset(repository, TOOL_PATH)
    tcb = contract.parse_canonical_json_bytes(tcb_raw, require_canonical=True)
    pack = contract.parse_canonical_json_bytes(pack_raw, require_canonical=True)
    if tcb["dsl_interpreter"]["content_digest"] != interpreter_binding["digest"]:
        raise RuntimeError("TCB interpreter binding drifted")
    if pack["declarative_rules_digest"] != program_binding["digest"]:
        raise RuntimeError("pack program binding drifted")

    limit_profile = {
        field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
        for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
    }
    denominator = {
        "measurement_id": MEASUREMENT_ID,
        "profile": "DEFAULT_DSL_PROTOTYPE_LIMITS",
        "dimensions": list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS),
        "boundary_labels": list(BOUNDARY_LABELS),
        "semantic_receipt_repeats": SEMANTIC_REPEATS,
        "reference_performance_repeats": PERFORMANCE_REPEATS,
        "hostile_case_ids": [item[0] for item in _hostile_raw_cases()],
        "injected_boundary_test_owners": [TEST_OWNERS[field] for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS],
        "claim_scope": "REFERENCE_MEASUREMENT_ONLY_NO_BUDGET_OR_QUALIFICATION_EFFECT",
    }
    if reference is None:
        environment = _reference_environment()
    else:
        environment = reference.get("reference_environment")
        if type(environment) is not dict:
            raise RuntimeError("committed reference environment is missing")
    artifact = {
        "schema": SCHEMA,
        "evidence_id": MEASUREMENT_ID,
        "claim_boundary": (
            "Executable reference measurements for the synthetic R2.0 DSL prototype only; not an "
            "approved budget, independently reviewed ceiling, qualification, sandbox proof, or "
            "promotion signal."
        ),
        "authoritative": False,
        "approved_budget": None,
        "review_evidence": None,
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "wasm_execution_state": "UNIMPLEMENTED_UNREVIEWED",
        "bindings": {
            "pack_manifest": pack_binding,
            "tcb_manifest": tcb_binding,
            "prototype_program": program_binding,
            "prototype_input": input_binding,
            "supported_denominator": denominator_binding,
            "interpreter_source": interpreter_binding,
            "default_limit_profile": {
                "value": limit_profile,
                "digest": contract.canonical_digest(limit_profile),
            },
            "measurement_tool": tool_binding,
            "declared_toolchains": tcb["toolchains"],
            "pack_abi_version": pack["abi_version"],
        },
        "measurement_denominator": denominator,
        "measurement_denominator_digest": contract.canonical_digest(denominator),
        "design_corrections": [
            {
                "dimension": "max_output_bytes",
                "prior_provisional_value": 262_144,
                "corrected_provisional_value": 131_072,
                "prior_n_minus_1_n_n_plus_1_output_targets": [262_143, 262_144, 262_145],
                "prior_required_program_bytes": [262_297, 262_298, 262_299],
                "dominating_guard": "max_program_bytes",
                "dominating_guard_value": 262_144,
                "correction_reason": (
                    "The prior output ceiling was unreachable because its smallest boundary "
                    "program exceeded max_program_bytes; the corrected provisional value restores "
                    "actual shipped-profile N-1/N/N+1 execution."
                ),
                "authority_effect": "NONE_PENDING_INDEPENDENT_REVIEW",
            }
        ],
        "baseline_execution": _baseline_execution(
            repository,
            pack_raw,
            tcb_raw,
            program_raw,
            denominator_raw,
            input_raw,
        ),
        "boundary_measurements": _boundary_measurements(reference),
        "hostile_measurements": _hostile_measurements(reference),
        "reference_environment": environment,
        "review_state": {
            "state": "PENDING_INDEPENDENT_NUMERIC_REVIEW_AND_SIGNED_EVIDENCE",
            "blockers": [
                "APPROVED_BUDGET_ABSENT",
                "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
            ],
            "resource_ceiling_effect": "NONE",
            "qualification_effect": "NONE",
            "promotion_effect": "NONE",
        },
        "release3_included": False,
    }
    return contract.canonical_json_bytes(artifact)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="capture fresh reference observations and write the generated artifact",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / RESOURCE,
        help="explicit generated artifact target (defaults to the packaged evidence path)",
    )
    args = parser.parse_args(argv)
    target = args.output.resolve()
    if args.update:
        generated = _build(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(generated)
        return 0
    if not target.is_file():
        raise RuntimeError("Atlas R2 DSL prototype measurements are missing")
    try:
        reference = json.loads(target.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError, MemoryError):
        raise RuntimeError("Atlas R2 DSL prototype measurements are unreadable") from None
    if type(reference) is not dict:
        raise RuntimeError("Atlas R2 DSL prototype measurements are not an object")
    generated = _build(ROOT, reference=reference)
    if target.read_bytes() != generated:
        raise RuntimeError("Atlas R2 DSL prototype measurements drifted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
