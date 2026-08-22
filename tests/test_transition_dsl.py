"""Executable and adversarial evidence for the bounded R2.0 declarative prototype."""

from __future__ import annotations

import builtins
from pathlib import Path
import random
import socket
import subprocess
import time
from dataclasses import replace
from typing import Any, Callable

import pytest

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as tp


ROOT = Path(__file__).resolve().parents[1]


def _binding(kind: str, value: Any) -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_BINDING_SCHEMA,
        "kind": kind,
        "digest": tc.canonical_digest(value),
        "value": value,
    }


def _input(
        *,
        facts: dict[str, Any] | None = None,
        request_id: str = "request-001",
        identity: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
        time_value: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_INPUT_SCHEMA,
        "request_id": request_id,
        "identity": _binding("IDENTITY", identity or {"device_id": "edge-001"}),
        "scope": _binding("SCOPE", scope or {"site_id": "site-a"}),
        "time": _binding("TIME", time_value or {"observed_at": "2026-08-22T00:00:00.000000Z"}),
        "facts": facts if facts is not None else {
            "enabled": True,
            "role": "edge",
            "site_id": "site-a",
        },
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
        program_id: str = "prototype.001") -> dict[str, Any]:
    return {
        "schema": dsl.DECLARATIVE_PROGRAM_SCHEMA,
        "program_id": program_id,
        "program_version": "0.1.0-experimental",
        "abi_version": tc.PACK_ABI_VERSION,
        "pack_id": "fixture-pack",
        "pack_version": "0.1.0-experimental",
        "rules": rules or [_rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]})],
    }


def _raw(value: Any) -> bytes:
    return tc.canonical_json_bytes(value)


def _packaged_prototype(
        *,
        manifest_raw: bytes | None = None,
        tcb_raw: bytes | None = None,
        program_raw: bytes | None = None) -> dsl.BoundPackagedDSLPrototype:
    actual_manifest = manifest_raw or (ROOT / dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH).read_bytes()
    actual_tcb = tcb_raw or (ROOT / dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH).read_bytes()
    actual_program = program_raw or (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes()
    denominator_raw = (ROOT / dsl.DSL_PROTOTYPE_DENOMINATOR_PATH).read_bytes()
    tcb = tc.parse_canonical_json_bytes(actual_tcb, require_canonical=True)
    source_map = {
        item["path"]: (ROOT / item["path"]).read_bytes()
        for item in [*tcb["core_sources"], *tcb["pack_sources"]]
    }
    source_map[dsl.DSL_PROTOTYPE_PROGRAM_PATH] = actual_program
    return dsl.bind_packaged_dsl_prototype_bytes(
        actual_manifest,
        actual_tcb,
        actual_program,
        denominator_raw,
        source_map,
    )


def _receipt(
        function: str = "evaluate",
        *,
        program: dict[str, Any] | None = None,
        input_value: dict[str, Any] | None = None,
        limits: dsl.DSLPrototypeLimits = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS) -> dict[str, Any]:
    raw = dsl.run_pack_abi(
        function,
        _raw(program or _program()),
        _raw(input_value or _input()),
        limits=limits,
    )
    return tc.parse_canonical_json_bytes(raw, require_canonical=True)


def _assert_success(receipt: dict[str, Any]) -> None:
    assert receipt["outcome"] == "EXECUTED_NONAUTHORITATIVE"
    assert receipt["error"] is None
    assert receipt["result"] is not None
    assert receipt["result_digest"] == tc.canonical_digest(receipt["result"])


def _assert_refusal(receipt: dict[str, Any], code: str) -> None:
    assert receipt["outcome"] == "REFUSED_NONAUTHORITATIVE"
    assert receipt["error"] == {"code": code}
    assert receipt["result"] is None
    assert receipt["result_digest"] is None


def _limits(**changes: int) -> dsl.DSLPrototypeLimits:
    return replace(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, **changes)


def _truth(receipt: dict[str, Any]) -> list[str]:
    return [entry["truth"] for entry in receipt["result"]["entries"]]


def test_all_closed_operators_execute_with_three_valued_results() -> None:
    expressions = [
        {"op": "ALL_OF", "args": [
            {"op": "EXISTS", "path": ["facts", "enabled"]},
            {"op": "EQUALS", "path": ["facts", "role"], "value": "edge"},
        ]},
        {"op": "ANY_OF", "args": [
            {"op": "EQUALS", "path": ["facts", "missing"], "value": "x"},
            {"op": "EXISTS", "path": ["facts", "enabled"]},
        ]},
        {"op": "EQUALS", "path": ["facts", "role"], "value": "edge"},
        {"op": "EXISTS", "path": ["facts", "enabled"]},
        {"op": "IN_SET", "path": ["facts", "role"], "values": ["core", "edge"]},
        {"op": "MATCH_SCOPE", "fact_path": ["facts", "site_id"], "scope_path": ["scope", "site_id"]},
        {"op": "NOT", "arg": {"op": "EXISTS", "path": ["facts", "absent"]}},
        {"op": "NOT_EQUALS", "path": ["facts", "role"], "value": "core"},
        {"op": "TEMPORAL_MONITOR", "profile_path": ["time", "observed_at"]},
    ]
    rules = [_rule(f"rule.{index:03d}", expression) for index, expression in enumerate(expressions, 1)]
    receipt = _receipt(program=_program(rules))

    _assert_success(receipt)
    assert _truth(receipt) == [dsl.TRUTH_TRUE] * 8 + [dsl.TRUTH_INCONCLUSIVE]
    assert receipt["result"]["entries"][-1]["value"] is None
    assert set(tp.DECLARATIVE_DSL_OPERATORS) == {expression["op"] for expression in expressions}


def test_pack_census_counts_rule_dispatch_emission_and_every_expression_operator() -> None:
    shallow = _program([_rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]})])
    nested = _program([_rule("rule.001", {
        "op": "ALL_OF",
        "args": [
            {"op": "EXISTS", "path": ["facts", "enabled"]},
            {"op": "NOT", "arg": {"op": "EXISTS", "path": ["facts", "forbidden"]}},
        ],
    })])
    op_shaped_literal = _program([_rule("rule.001", {
        "op": "EQUALS",
        "path": ["facts", "metadata"],
        "value": {"op": "EXISTS", "path": ["literal", "not", "grammar"]},
    })])

    assert dsl.declarative_program_semantic_statements(shallow) == 2
    assert dsl.declarative_program_semantic_statements(nested) == 5
    assert dsl.declarative_program_semantic_statements(op_shaped_literal) == 2


@pytest.mark.parametrize(
    ("expression", "expected"),
    (
        ({"op": "EQUALS", "path": ["facts", "missing"], "value": 1}, dsl.TRUTH_INCONCLUSIVE),
        ({"op": "NOT", "arg": {
            "op": "EQUALS", "path": ["facts", "missing"], "value": 1,
        }}, dsl.TRUTH_INCONCLUSIVE),
        ({"op": "ALL_OF", "args": [
            {"op": "EXISTS", "path": ["facts", "absent"]},
            {"op": "EQUALS", "path": ["facts", "missing"], "value": 1},
        ]}, dsl.TRUTH_FALSE),
        ({"op": "ANY_OF", "args": [
            {"op": "EXISTS", "path": ["facts", "enabled"]},
            {"op": "EQUALS", "path": ["facts", "missing"], "value": 1},
        ]}, dsl.TRUTH_TRUE),
    ),
)
def test_three_valued_logic_never_coerces_absence_to_positive(
        expression: dict[str, Any], expected: str) -> None:
    receipt = _receipt(program=_program([_rule("rule.001", expression)]))
    _assert_success(receipt)
    assert _truth(receipt) == [expected]


def test_exact_typed_bindings_reject_teleportation_and_change_receipt_digests() -> None:
    first = _input(identity={"device_id": "edge-001"})
    second = _input(identity={"device_id": "edge-002"})
    first_receipt = _receipt(input_value=first)
    second_receipt = _receipt(input_value=second)

    assert first_receipt["program_digest"] == second_receipt["program_digest"]
    assert first_receipt["input_digest"] != second_receipt["input_digest"]
    assert first_receipt["binding_digests"]["identity"] != second_receipt["binding_digests"]["identity"]
    assert first_receipt["binding_digests"]["scope"] == second_receipt["binding_digests"]["scope"]

    teleported = _input(identity={"device_id": "edge-002"})
    teleported["identity"]["digest"] = first["identity"]["digest"]
    _assert_refusal(_receipt(input_value=teleported), "INPUT_BINDING_DIGEST_MISMATCH")


def test_all_six_abi_calls_are_closed_and_replay_is_deterministically_unsupported() -> None:
    rules = [
        _rule(f"rule.{index:03d}", {"op": "EXISTS", "path": ["facts", "enabled"]}, function=function)
        for index, function in enumerate(tp.PACK_ABI_FUNCTIONS[:-1], 1)
    ]
    program = _program(rules)
    for function in tp.PACK_ABI_FUNCTIONS[:-1]:
        receipt = _receipt(function, program=program)
        _assert_success(receipt)
        assert receipt["function"] == function
        assert len(receipt["result"]["entries"]) == 1

    replay_a = _receipt("replay_witness", program=program)
    replay_b = _receipt("replay_witness", program=program)
    assert replay_a == replay_b
    _assert_refusal(replay_a, "REPLAY_WITNESS_UNSUPPORTED_R2_0")


def test_packaged_prototype_binds_exact_program_tcb_denominator_and_sources() -> None:
    prototype = _packaged_prototype()
    input_raw = (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes()

    first_raw = dsl.run_bound_pack_abi(prototype, "evaluate", input_raw)
    second_raw = dsl.run_bound_pack_abi(prototype, "evaluate", input_raw)
    assert first_raw == second_raw
    assert len(first_raw) <= dsl.dsl_receipt_container_ceiling(
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS
    )["bound_receipt_ceiling_bytes"]
    receipt = tc.parse_canonical_json_bytes(first_raw, require_canonical=True)
    assert receipt["schema"] == dsl.BOUND_DECLARATIVE_PROTOTYPE_RECEIPT_SCHEMA
    assert receipt["source_binding_state"] == "SAME_CHECKOUT_SELF_CHECK_ONLY"
    assert receipt["pack_id"] == dsl.DSL_PROTOTYPE_PACK_ID
    assert receipt["pack_manifest_digest"] == prototype.pack_manifest_digest
    assert receipt["tcb_manifest_digest"] == prototype.tcb_manifest_digest
    assert receipt["program_digest"] == prototype.program_digest
    assert receipt["supported_denominator_digest"] == prototype.denominator_digest
    assert receipt["interpreter_digest"] == prototype.interpreter_digest
    assert receipt["inner_receipt"]["outcome"] == "EXECUTED_NONAUTHORITATIVE"
    assert receipt["inner_receipt"]["result"]["entries"] == [
        {
            "rule_id": "prototype.evaluate-functional",
            "truth": "TRUE",
            "value": {"kind": "PROTOTYPE_EVALUATION", "value": "matched"},
        },
        {
            "rule_id": "prototype.evaluate-temporal",
            "truth": "INCONCLUSIVE",
            "value": None,
        },
    ]
    for field in (
            "authoritative",
            "supplies_obligation_support",
            "promotion_eligible"):
        assert receipt[field] is False
    assert receipt["authoritative_gate"] is None
    assert receipt["qualification_effect"] == "NONE"

    replay = tc.parse_canonical_json_bytes(
        dsl.run_bound_pack_abi(prototype, "replay_witness", input_raw),
        require_canonical=True,
    )
    assert replay["inner_receipt"]["error"] == {
        "code": "REPLAY_WITNESS_UNSUPPORTED_R2_0",
    }
    assert replay["authoritative"] is False

    with pytest.raises(TypeError):
        dsl.run_bound_pack_abi(
            prototype,
            "evaluate",
            input_raw,
            limits=_limits(max_rules=1),  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("result", "INNER_RECEIPT_RESULT_DIGEST_MISMATCH"),
        ("result_digest", "INNER_RECEIPT_RESULT_DIGEST_MISMATCH"),
        ("result_work", "INNER_RECEIPT_RESULT_WORK_MISMATCH"),
        ("limit_profile", "INNER_RECEIPT_LIMIT_PROFILE_DIGEST_MISMATCH"),
        ("limit_profile_digest", "INNER_RECEIPT_LIMIT_PROFILE_DIGEST_MISMATCH"),
        ("program_digest", "INNER_RECEIPT_PROGRAM_BINDING_MISMATCH"),
    ),
)
def test_inner_receipt_validator_recomputes_every_sibling_and_outer_join(
        mutation: str,
        expected_code: str) -> None:
    program_raw = _raw(_program())
    inner = _receipt(program=_program())
    expected_profile = dict(inner["limit_profile"])
    if mutation == "result":
        inner["result"]["entries"][0]["value"] = "substituted"
    elif mutation == "result_digest":
        inner["result_digest"] = tc.canonical_digest({"substituted": True})
    elif mutation == "result_work":
        inner["work_units"]["result_bytes"] += 1
    elif mutation == "limit_profile":
        inner["limit_profile"]["max_rules"] += 1
    elif mutation == "limit_profile_digest":
        inner["limit_profile_digest"] = tc.canonical_digest({"substituted": True})
    else:
        inner["program_digest"] = tc.canonical_digest({"substituted": True})

    with pytest.raises(dsl.DSLPrototypeError) as caught:
        dsl.validate_declarative_prototype_receipt(
            inner,
            expected_program_digest=tc.bytes_digest(program_raw),
            expected_limit_profile=expected_profile,
        )
    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    "mutation",
    (
        "result",
        "result_rechained",
        "profile",
        "program",
        "input",
        "bindings",
        "function",
        "work",
    ),
)
def test_bound_wrapper_rejects_rechained_tampered_inner_receipts(
        monkeypatch: pytest.MonkeyPatch,
        mutation: str) -> None:
    prototype = _packaged_prototype()
    input_raw = (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes()
    real_run = dsl.run_pack_abi

    def hostile_run(*args: Any, **kwargs: Any) -> bytes:
        receipt = tc.parse_canonical_json_bytes(real_run(*args, **kwargs), require_canonical=True)
        if mutation == "result":
            receipt["result"]["entries"][0]["value"] = "substituted"
        elif mutation == "result_rechained":
            receipt["result"]["entries"][0]["value"] = "substituted"
            result_raw = tc.canonical_json_bytes(receipt["result"])
            receipt["result_digest"] = tc.bytes_digest(result_raw)
            receipt["work_units"]["result_bytes"] = len(result_raw)
        elif mutation == "profile":
            receipt["limit_profile"]["max_rules"] += 1
            receipt["limit_profile_digest"] = tc.canonical_digest(receipt["limit_profile"])
        elif mutation == "program":
            receipt["program_digest"] = tc.canonical_digest({"substituted": True})
        elif mutation == "input":
            receipt["input_digest"] = tc.canonical_digest({"substituted": True})
        elif mutation == "bindings":
            receipt["binding_digests"] = {
                field: tc.canonical_digest({"substituted": field})
                for field in ("identity", "scope", "time")
            }
        elif mutation == "function":
            receipt["function"] = "manifest"
        else:
            for field in (
                    "program_bytes",
                    "input_bytes",
                    "input_nodes",
                    "rules",
                    "expression_nodes",
                    "fuel_consumed"):
                receipt["work_units"][field] = 0
        return tc.canonical_json_bytes(receipt)

    monkeypatch.setattr(dsl, "run_pack_abi", hostile_run)
    with pytest.raises(dsl.DSLPrototypeError) as caught:
        dsl.run_bound_pack_abi(prototype, "evaluate", input_raw)
    assert caught.value.code in {
        "INNER_RECEIPT_RESULT_DIGEST_MISMATCH",
        "INNER_RECEIPT_LIMIT_PROFILE_BINDING_MISMATCH",
        "INNER_RECEIPT_PROGRAM_BINDING_MISMATCH",
        "PROTOTYPE_INNER_RECEIPT_RECOMPUTATION_MISMATCH",
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    (("function", "fiction"), ("error", {"code": "1"}), ("error", {"code": "_"})),
)
def test_inner_receipt_validator_matches_schema_function_and_error_tokens(
        field: str,
        replacement: Any) -> None:
    receipt = _receipt("replay_witness")
    receipt[field] = replacement
    with pytest.raises(dsl.DSLPrototypeError):
        dsl.validate_declarative_prototype_receipt(receipt)


def test_packaged_prototype_rejects_detached_or_mutated_custody() -> None:
    prototype = _packaged_prototype()
    with pytest.raises(dsl.DSLPrototypeError) as detached:
        dsl.require_bound_packaged_dsl_prototype({})
    assert detached.value.code == "DETACHED_PROTOTYPE_CUSTODY"

    prototype._pack["claim_boundary"] = "forged authority"
    with pytest.raises(dsl.DSLPrototypeError) as mutated:
        dsl.require_bound_packaged_dsl_prototype(prototype)
    assert mutated.value.code == "BOUND_PROTOTYPE_CUSTODY_MUTATED"


def test_rechained_program_manifest_and_tcb_still_cannot_launder_authority() -> None:
    program = tc.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes(),
        require_canonical=True,
    )
    program["rules"][-2]["emit"] = {"kind": "PROTOTYPE_EVALUATION", "value": "changed"}
    program_raw = tc.canonical_json_bytes(program)
    tcb = tc.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH).read_bytes(),
        require_canonical=True,
    )
    program_source = next(
        item for item in tcb["pack_sources"]
        if item["path"] == dsl.DSL_PROTOTYPE_PROGRAM_PATH
    )
    program_source["bytes"] = len(program_raw)
    program_source["digest"] = tc.bytes_digest(program_raw)
    tcb_raw = tc.canonical_json_bytes(tcb)
    manifest = tc.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH).read_bytes(),
        require_canonical=True,
    )
    manifest["declarative_rules_digest"] = tc.bytes_digest(program_raw)
    manifest["semantic_bundle_digest"] = tc.bytes_digest(program_raw)
    manifest["tcb_manifest_digest"] = tc.bytes_digest(tcb_raw)
    manifest_raw = tc.canonical_json_bytes(manifest)

    prototype = _packaged_prototype(
        manifest_raw=manifest_raw,
        tcb_raw=tcb_raw,
        program_raw=program_raw,
    )
    receipt = tc.parse_canonical_json_bytes(
        dsl.run_bound_pack_abi(
            prototype,
            "evaluate",
            (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes(),
        ),
        require_canonical=True,
    )
    assert receipt["inner_receipt"]["result"]["entries"][0]["value"]["value"] == "changed"
    assert receipt["authoritative"] is False
    assert receipt["supplies_obligation_support"] is False
    assert receipt["authoritative_gate"] is None
    assert receipt["promotion_eligible"] is False


def test_receipts_are_hardcoded_non_authoritative_and_producer_authority_fields_fail_closed() -> None:
    receipt = _receipt()
    assert receipt["interpreter_semantics_version"] == dsl.DECLARATIVE_INTERPRETER_SEMANTICS_VERSION
    assert tuple(receipt["limit_profile"]) == tuple(sorted(dsl.DSL_PROTOTYPE_LIMIT_FIELDS))
    assert set(receipt["limit_profile"]) == set(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
    assert receipt["limit_profile_digest"] == tc.canonical_digest(receipt["limit_profile"])
    assert {
        "authoritative": receipt["authoritative"],
        "supplies_obligation_support": receipt["supplies_obligation_support"],
        "qualification_effect": receipt["qualification_effect"],
        "authoritative_gate": receipt["authoritative_gate"],
        "promotion_eligible": receipt["promotion_eligible"],
        "execution_state": receipt["execution_state"],
        "qualification_state": receipt["qualification_state"],
    } == {
        "authoritative": False,
        "supplies_obligation_support": False,
        "qualification_effect": "NONE",
        "authoritative_gate": None,
        "promotion_eligible": False,
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
    }

    for forbidden in ("gate", "device_status", "qualification_state", "promotionEligible"):
        program = _program([_rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]},
                                       emit={forbidden: "forged"})])
        _assert_refusal(_receipt(program=program), "PRODUCER_AUTHORITY_FIELD_FORBIDDEN")
    _assert_refusal(_receipt(input_value=_input(facts={"authoritativeGate": "forged"})),
                    "PRODUCER_AUTHORITY_FIELD_FORBIDDEN")


def test_fixed_refusals_do_not_echo_hostile_values_or_parser_paths() -> None:
    canary = "SECRET-CANARY-DO-NOT-ECHO"
    hostile_program = _program()
    hostile_program[canary] = {"status": canary}
    receipt_raw = dsl.run_pack_abi("evaluate", _raw(hostile_program), _raw(_input()))
    receipt = tc.parse_canonical_json_bytes(receipt_raw)
    _assert_refusal(receipt, "PRODUCER_AUTHORITY_FIELD_FORBIDDEN")
    assert canary.encode() not in receipt_raw
    assert b"$." not in receipt_raw

    unsupported_raw = dsl.run_pack_abi(canary, _raw(_program()), _raw(_input()))
    unsupported = tc.parse_canonical_json_bytes(unsupported_raw)
    _assert_refusal(unsupported, "ABI_FUNCTION_UNSUPPORTED")
    assert unsupported["function"] is None
    assert canary.encode() not in unsupported_raw

    noncanonical = _raw(_program()).replace(b'"abi_version":', b'"z":0, "abi_version":', 1)
    invalid_raw = dsl.run_pack_abi("evaluate", noncanonical, _raw(_input()))
    invalid = tc.parse_canonical_json_bytes(invalid_raw)
    _assert_refusal(invalid, "PROGRAM_CANONICAL_INVALID")
    assert b"$." not in invalid_raw


def test_repeated_and_insertion_permuted_inputs_have_identical_receipts() -> None:
    first_facts = {"enabled": True, "role": "edge", "site_id": "site-a"}
    second_facts = {"site_id": "site-a", "role": "edge", "enabled": True}
    first_raw = _raw(_input(facts=first_facts))
    second_raw = _raw(_input(facts=second_facts))
    assert first_raw == second_raw
    program_raw = _raw(_program())

    first = dsl.run_pack_abi("evaluate", program_raw, first_raw)
    repeated = dsl.run_pack_abi("evaluate", program_raw, first_raw)
    permuted = dsl.run_pack_abi("evaluate", program_raw, second_raw)
    assert first == repeated == permuted


def test_execution_uses_no_ambient_sink_or_dynamic_import(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("ambient capability used")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(builtins, "__import__", forbidden)

    receipt_raw = dsl.run_pack_abi("evaluate", _raw(_program()), _raw(_input()))
    receipt = tc.parse_canonical_json_bytes(receipt_raw)
    _assert_success(receipt)


def test_non_bytes_cannot_mint_an_exact_source_binding() -> None:
    with pytest.raises(dsl.DSLPrototypeError) as caught:
        dsl.run_pack_abi("evaluate", _program(), _raw(_input()))  # type: ignore[arg-type]
    assert caught.value.code == "CANONICAL_BYTES_REQUIRED"
    assert str(caught.value) == "CANONICAL_BYTES_REQUIRED"


def test_limit_profile_has_the_exact_closed_fields_and_is_immutable() -> None:
    assert dsl.DSL_PROTOTYPE_LIMIT_FIELDS == (
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
    with pytest.raises((AttributeError, TypeError)):
        dsl.DEFAULT_DSL_PROTOTYPE_LIMITS.max_rules = 2  # type: ignore[misc]
    with pytest.raises(dsl.DSLPrototypeError) as caught:
        replace(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, max_rules=0)
    assert caught.value.code == "LIMIT_PROFILE_INVALID"
    custom = _limits(max_rules=7)
    receipt = _receipt(limits=custom)
    assert receipt["limit_profile"]["max_rules"] == 7
    assert receipt["limit_profile_digest"] == tc.canonical_digest(receipt["limit_profile"])


def test_program_byte_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    programs = [_raw(_program(program_id="p" * size)) for size in (19, 20, 21)]
    assert [len(raw) for raw in programs] == list(range(len(programs[1]) - 1, len(programs[1]) + 2))
    limits = _limits(max_program_bytes=len(programs[1]))
    _assert_success(tc.parse_canonical_json_bytes(dsl.run_pack_abi("evaluate", programs[0], _raw(_input()), limits=limits)))
    _assert_success(tc.parse_canonical_json_bytes(dsl.run_pack_abi("evaluate", programs[1], _raw(_input()), limits=limits)))
    refused = tc.parse_canonical_json_bytes(
        dsl.run_pack_abi("evaluate", programs[2], _raw(_input()), limits=limits)
    )
    _assert_refusal(refused, "PROGRAM_BYTE_LIMIT")
    assert refused["program_digest"] is None
    assert refused["input_digest"] == tc.bytes_digest(_raw(_input()))


def test_input_byte_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    inputs = [_raw(_input(request_id="r" * size)) for size in (19, 20, 21)]
    assert [len(raw) for raw in inputs] == list(range(len(inputs[1]) - 1, len(inputs[1]) + 2))
    limits = _limits(max_input_bytes=len(inputs[1]))
    _assert_success(tc.parse_canonical_json_bytes(dsl.run_pack_abi("evaluate", _raw(_program()), inputs[0], limits=limits)))
    _assert_success(tc.parse_canonical_json_bytes(dsl.run_pack_abi("evaluate", _raw(_program()), inputs[1], limits=limits)))
    refused = tc.parse_canonical_json_bytes(
        dsl.run_pack_abi("evaluate", _raw(_program()), inputs[2], limits=limits)
    )
    _assert_refusal(refused, "INPUT_BYTE_LIMIT")
    assert refused["program_digest"] == tc.bytes_digest(_raw(_program()))
    assert refused["input_digest"] is None


@pytest.mark.parametrize("oversized_side", ("program", "input", "both"))
def test_oversized_untrusted_bytes_are_refused_before_digest_work(
        monkeypatch: pytest.MonkeyPatch,
        oversized_side: str) -> None:
    limits = _limits(max_program_bytes=64, max_input_bytes=64)
    program_raw = b"p" * (65 if oversized_side in ("program", "both") else 64)
    input_raw = b"i" * (65 if oversized_side in ("input", "both") else 64)
    actual_digest = dsl.bytes_digest
    digested_lengths: list[int] = []

    def guarded_digest(raw: bytes) -> str:
        assert len(raw) <= 64, "an oversized attacker-controlled object reached SHA-256"
        digested_lengths.append(len(raw))
        return actual_digest(raw)

    monkeypatch.setattr(dsl, "bytes_digest", guarded_digest)
    receipt = tc.parse_canonical_json_bytes(
        dsl.run_pack_abi("evaluate", program_raw, input_raw, limits=limits),
        require_canonical=True,
    )

    _assert_refusal(
        receipt,
        "PROGRAM_BYTE_LIMIT" if oversized_side in ("program", "both") else "INPUT_BYTE_LIMIT",
    )
    if oversized_side in ("program", "both"):
        assert receipt["program_digest"] is None
    else:
        assert receipt["program_digest"] is not None
    if oversized_side in ("input", "both"):
        assert receipt["input_digest"] is None
    else:
        assert receipt["input_digest"] is not None
    assert digested_lengths == ([64] if oversized_side in ("program", "input") else [])


def test_output_byte_limit_has_n_minus_1_n_n_plus_1_behavior_and_no_partial_result() -> None:
    programs = [_program([_rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]},
                                    emit="x" * size)]) for size in (19, 20, 21)]
    baseline = [_receipt(program=program) for program in programs]
    sizes = [receipt["work_units"]["result_bytes"] for receipt in baseline]
    assert sizes == list(range(sizes[1] - 1, sizes[1] + 2))
    limits = _limits(max_output_bytes=sizes[1])
    _assert_success(_receipt(program=programs[0], limits=limits))
    _assert_success(_receipt(program=programs[1], limits=limits))
    refused = _receipt(program=programs[2], limits=limits)
    _assert_refusal(refused, "OUTPUT_BYTE_LIMIT")
    assert refused["work_units"]["result_bytes"] == sizes[1] + 1
    assert refused["work_units"]["result_records"] == 1
    assert dsl.validate_declarative_prototype_receipt(
        refused,
        expected_program_digest=tc.bytes_digest(_raw(programs[2])),
        expected_limit_profile=refused["limit_profile"],
    ) == refused


def test_receipt_container_formula_bounds_near_max_success_and_refusal_shapes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    limits = dsl.DEFAULT_DSL_PROTOTYPE_LIMITS
    ceiling = dsl.dsl_receipt_container_ceiling(limits)
    seed = _program([
        _rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]}, emit=""),
        _rule("rule.002", {"op": "EXISTS", "path": ["facts", "enabled"]}, emit=""),
    ])
    seed_receipt = _receipt(program=seed, limits=limits)
    emit_bytes = limits.max_output_bytes - seed_receipt["work_units"]["result_bytes"]
    first_emit_bytes = min(limits.max_string_bytes, emit_bytes)
    near_max = _program([
        _rule(
            "rule.001",
            {"op": "EXISTS", "path": ["facts", "enabled"]},
            emit="x" * first_emit_bytes,
        ),
        _rule(
            "rule.002",
            {"op": "EXISTS", "path": ["facts", "enabled"]},
            emit="x" * (emit_bytes - first_emit_bytes),
        ),
    ])
    success_raw = dsl.run_pack_abi("evaluate", _raw(near_max), _raw(_input()), limits=limits)
    success = tc.parse_canonical_json_bytes(success_raw, require_canonical=True)
    assert success["work_units"]["result_bytes"] == limits.max_output_bytes
    assert len(success_raw) <= ceiling["inner_receipt_ceiling_bytes"]

    refusal_calls = (
        lambda: dsl.run_pack_abi("fiction", _raw(_program()), _raw(_input()), limits=limits),
        lambda: dsl.run_pack_abi("evaluate", b"x" * (limits.max_program_bytes + 1), _raw(_input()), limits=limits),
        lambda: dsl.run_pack_abi("evaluate", _raw(_program()), b"x" * (limits.max_input_bytes + 1), limits=limits),
        lambda: dsl.run_pack_abi("replay_witness", _raw(_program()), _raw(_input()), limits=limits),
        lambda: dsl.run_pack_abi(
            "evaluate",
            _raw(_program([_rule("rule.001", {"op": "EXISTS", "path": ["facts", "enabled"]}, emit="xx")])),
            _raw(_input()),
            limits=_limits(max_output_bytes=1),
        ),
    )
    for call in refusal_calls:
        raw = call()
        receipt = tc.parse_canonical_json_bytes(raw, require_canonical=True)
        assert receipt["outcome"] == "REFUSED_NONAUTHORITATIVE"
        profile_ceiling = dsl.dsl_receipt_container_ceiling(receipt["limit_profile"])
        assert len(raw) <= profile_ceiling["inner_receipt_ceiling_bytes"]

    original_compile = dsl._compile_program
    for registered_code in dsl._PRODUCER_RECEIPT_ERROR_CODES:
        def registered_refusal(
                *_args: Any,
                code: str = registered_code,
                **_kwargs: Any) -> Any:
            raise dsl.DSLPrototypeError(code)

        monkeypatch.setattr(dsl, "_compile_program", registered_refusal)
        raw = dsl.run_pack_abi("evaluate", _raw(_program()), _raw(_input()))
        receipt = tc.parse_canonical_json_bytes(raw, require_canonical=True)
        assert receipt["error"] == {"code": registered_code}
        assert len(raw) <= ceiling["inner_receipt_ceiling_bytes"]
    monkeypatch.setattr(dsl, "_compile_program", original_compile)

    with pytest.raises(dsl.DSLPrototypeError) as extra_profile:
        dsl.dsl_receipt_container_ceiling({
            **{field: getattr(limits, field) for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS},
            "fiction": 1,
        })
    assert extra_profile.value.code == "RECEIPT_CONTAINER_PROFILE_INVALID"

    def unregistered(*_args: Any, **_kwargs: Any) -> Any:
        raise dsl.DSLPrototypeError("UNREGISTERED_EXTREMELY_LONG_PRODUCER_REFUSAL_CODE")

    monkeypatch.setattr(dsl, "_compile_program", unregistered)
    with pytest.raises(dsl.DSLPrototypeError) as unregistered_refusal:
        dsl.run_pack_abi("evaluate", _raw(_program()), _raw(_input()))
    assert unregistered_refusal.value.code == "UNREGISTERED_PRODUCER_REFUSAL"


def test_rule_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_rules=2)
    for count in (1, 2):
        rules = [_rule(f"rule.{index:03d}", {"op": "EXISTS", "path": ["facts", "enabled"]})
                 for index in range(count)]
        receipt = _receipt(program=_program(rules), limits=limits)
        _assert_success(receipt)
        assert receipt["work_units"]["result_records"] == count
    rules = [_rule(f"rule.{index:03d}", {"op": "EXISTS", "path": ["facts", "enabled"]})
             for index in range(3)]
    _assert_refusal(_receipt(program=_program(rules), limits=limits), "RULE_LIMIT")


def _not_depth(depth: int) -> dict[str, Any]:
    expression: dict[str, Any] = {"op": "EXISTS", "path": ["facts", "enabled"]}
    for _ in range(depth - 1):
        expression = {"op": "NOT", "arg": expression}
    return expression


def test_expression_depth_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_expression_depth=3)
    for depth in (2, 3):
        _assert_success(_receipt(program=_program([_rule("rule.001", _not_depth(depth))]), limits=limits))
    _assert_refusal(
        _receipt(program=_program([_rule("rule.001", _not_depth(4))]), limits=limits),
        "EXPRESSION_DEPTH_LIMIT",
    )


def _any_nodes(total_nodes: int) -> dict[str, Any]:
    return {"op": "ANY_OF", "args": [
        {"op": "EXISTS", "path": ["facts", f"value{index}"]}
        for index in range(total_nodes - 1)
    ]}


def test_expression_node_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_expression_nodes=3)
    for nodes in (2, 3):
        _assert_success(_receipt(program=_program([_rule("rule.001", _any_nodes(nodes))]), limits=limits))
    _assert_refusal(
        _receipt(program=_program([_rule("rule.001", _any_nodes(4))]), limits=limits),
        "EXPRESSION_NODE_LIMIT",
    )


def _any_operands(count: int) -> dict[str, Any]:
    return {"op": "ANY_OF", "args": [
        {"op": "EXISTS", "path": ["facts", f"value{index}"]}
        for index in range(count)
    ]}


def test_operator_operand_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_operator_operands=2)
    for count in (1, 2):
        _assert_success(_receipt(program=_program([_rule("rule.001", _any_operands(count))]), limits=limits))
    _assert_refusal(
        _receipt(program=_program([_rule("rule.001", _any_operands(3))]), limits=limits),
        "OPERATOR_OPERAND_LIMIT",
    )


def _exists_path(length: int) -> dict[str, Any]:
    return {"op": "EXISTS", "path": ["facts"] + ["nested"] * (length - 1)}


def test_path_segment_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_path_segments=2)
    for length in (1, 2):
        _assert_success(_receipt(program=_program([_rule("rule.001", _exists_path(length))]), limits=limits))
    _assert_refusal(
        _receipt(program=_program([_rule("rule.001", _exists_path(3))]), limits=limits),
        "PATH_SEGMENT_LIMIT",
    )


def test_string_byte_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_string_bytes=80)
    for size in (79, 80):
        _assert_success(_receipt(input_value=_input(facts={"value": "x" * size}), limits=limits))
    _assert_refusal(
        _receipt(input_value=_input(facts={"value": "x" * 81}), limits=limits),
        "STRING_BYTE_LIMIT",
    )


def _in_set(count: int) -> dict[str, Any]:
    return {"op": "IN_SET", "path": ["facts", "role"], "values": list(range(count))}


def test_set_item_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_set_items=2)
    for count in (1, 2):
        _assert_success(_receipt(program=_program([_rule("rule.001", _in_set(count))]), limits=limits))
    _assert_refusal(
        _receipt(program=_program([_rule("rule.001", _in_set(3))]), limits=limits),
        "SET_ITEM_LIMIT",
    )


def _node_count(value: Any) -> int:
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


def test_input_node_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    inputs = [_input(facts={"values": list(range(count))}) for count in (0, 1, 2)]
    counts = [_node_count(value) for value in inputs]
    assert counts == list(range(counts[1] - 1, counts[1] + 2))
    limits = _limits(max_input_nodes=counts[1])
    _assert_success(_receipt(input_value=inputs[0], limits=limits))
    _assert_success(_receipt(input_value=inputs[1], limits=limits))
    _assert_refusal(_receipt(input_value=inputs[2], limits=limits), "INPUT_NODE_LIMIT")


def test_instruction_fuel_limit_has_n_minus_1_n_n_plus_1_behavior() -> None:
    limits = _limits(max_instruction_fuel=5)
    for candidates in (1, 2):
        receipt = _receipt(
            program=_program([_rule("rule.001", _in_set(candidates))]),
            limits=limits,
        )
        _assert_success(receipt)
        assert receipt["work_units"]["fuel_consumed"] == candidates + 3
    refused = _receipt(
        program=_program([_rule("rule.001", _in_set(3))]),
        limits=limits,
    )
    _assert_refusal(refused, "INSTRUCTION_FUEL_LIMIT")
    assert refused["work_units"]["fuel_consumed"] == 6


def test_fuel_charges_n_minus_1_n_n_plus_1_canonical_comparison_bytes() -> None:
    limits = _limits(max_instruction_fuel=4)
    input_value = _input(facts={"payload": "x" * 30})
    receipts = []
    for literal_size in (29, 30):
        expression = {"op": "EQUALS", "path": ["facts", "payload"], "value": "x" * literal_size}
        receipt = _receipt(
            program=_program([_rule("rule.001", expression)]),
            input_value=input_value,
            limits=limits,
        )
        _assert_success(receipt)
        receipts.append(receipt)
    assert [item["work_units"]["fuel_consumed"] for item in receipts] == [4, 4]

    expression = {"op": "EQUALS", "path": ["facts", "payload"], "value": "x" * 31}
    refused = _receipt(
        program=_program([_rule("rule.001", expression)]),
        input_value=input_value,
        limits=limits,
    )
    _assert_refusal(refused, "INSTRUCTION_FUEL_LIMIT")
    assert refused["work_units"]["fuel_consumed"] == 5


@pytest.mark.parametrize(
    ("mutate", "code"),
    (
        (lambda program: program["rules"][0]["when"].update({"op": "EVAL_PYTHON"}), "OPERATOR_UNSUPPORTED"),
        (lambda program: program["rules"][0].update({"function": "replay_witness"}), "RULE_FUNCTION_UNSUPPORTED"),
        (lambda program: program["rules"][0]["when"].update({"path": ["environment", "secret"]}),
         "PATH_ROOT_INVALID"),
        (lambda program: program.update({"program_id": ".not-ascii-alphanumeric-first"}),
         "PROGRAM_IDENTIFIER_INVALID"),
    ),
)
def test_open_ended_program_capabilities_are_fixed_refusals(
        mutate: Callable[[dict[str, Any]], None], code: str) -> None:
    program = _program()
    mutate(program)
    _assert_refusal(_receipt(program=program), code)
