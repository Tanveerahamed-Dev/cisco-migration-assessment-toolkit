"""Adversarial contract tests for the bounded QDP-001 discovery adapter."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from cisco_toolkit.transition_contract import canonical_json_bytes, parse_canonical_json_bytes
from tools import run_atlas_r3_break_this_plan_discovery as discovery


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "atlas-r3-break-this-plan" / "unsafe-middle.synthetic.json"
INPUT_SCHEMA = ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-discovery-input-v1.schema.json"
RESULT_SCHEMA = ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-discovery-result-v1.schema.json"
TOOL = ROOT / "tools" / "run_atlas_r3_break_this_plan_discovery.py"


def _request() -> dict:
    return parse_canonical_json_bytes(FIXTURE.read_bytes(), require_canonical=True)


def _result(raw: bytes | None = None) -> tuple[bytes, dict]:
    encoded = discovery.analyze_request_bytes(FIXTURE.read_bytes() if raw is None else raw)
    return encoded, parse_canonical_json_bytes(encoded, require_canonical=True)


def _canonical(value: dict) -> bytes:
    return canonical_json_bytes(value)


def _error(code: str, call) -> None:
    with pytest.raises(discovery.BreakThisPlanDiscoveryError) as excinfo:
        call()
    assert excinfo.value.code == code
    assert str(excinfo.value) == code


def _candidate(result: dict, candidate_id: str) -> dict:
    return next(item for item in result["candidate_results"] if item["candidate_id"] == candidate_id)


def test_fixture_and_result_are_canonical_schema_valid_and_nonpromoting() -> None:
    request_raw = FIXTURE.read_bytes()
    assert canonical_json_bytes(json.loads(request_raw)) == request_raw

    input_schema = json.loads(INPUT_SCHEMA.read_text(encoding="utf-8"))
    result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(result_schema)
    Draft202012Validator(input_schema).validate(json.loads(request_raw))

    encoded, result = _result()
    assert canonical_json_bytes(result) == encoded
    Draft202012Validator(result_schema).validate(result)
    assert result["banner"] == "R3 DISCOVERY PROTOTYPE — NON-AUTHORITATIVE"
    assert result["qualification_state"] == "EXPERIMENTAL"
    assert result["promotion_eligible"] is False
    assert result["feasibility_verdict"] is None
    assert result["selected_candidate"] is None
    assert result["translation_checked"] is False
    assert result["translation_state"] == "TRANSLATION_NOT_ESTABLISHED"
    assert result["preview_eligible"] is False
    assert result["authoritative"] is False
    assert result["authoritative_gate"] is None
    assert result["decision_effect"] == "NONE"


def test_fixture_exposes_unsafe_middle_and_preserves_every_negative_result() -> None:
    _encoded, result = _result()
    assert [item["candidate_id"] for item in result["candidate_results"]] == [
        "candidate.incomplete",
        "candidate.invalid",
        "candidate.unsafe-middle",
    ]

    incomplete = _candidate(result, "candidate.incomplete")
    assert incomplete["result_kind"] == "ABSTENTION"
    assert incomplete["reason_code"] == "ABSTAIN_EVIDENCE_INCOMPLETE"
    assert incomplete["counterexamples"] == []
    assert "UNRESOLVED_ASSUMPTION" in incomplete["limitations"]
    assert "L2_CONTINUITY_NOT_ASSESSED" in incomplete["limitations"]

    invalid = _candidate(result, "candidate.invalid")
    assert invalid["result_kind"] == "ABSTENTION"
    assert invalid["reason_code"] == "NOT_EVALUABLE"
    assert invalid["counterexamples"] == []
    assert "SIMULATION_NOT_EVALUABLE" in invalid["limitations"]
    assert "NOOP_STEP_NOT_EVALUABLE" in invalid["limitations"]

    unsafe = _candidate(result, "candidate.unsafe-middle")
    assert unsafe["result_kind"] == "COUNTEREXAMPLE"
    assert unsafe["reason_code"] == "REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
    assert unsafe["checked_steps"] == 3
    assert unsafe["checked_flow_requirements"] == 1
    assert len(unsafe["counterexamples"]) == 1
    witness = unsafe["counterexamples"][0]
    assert witness["reason_code"] == "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
    assert witness["step_index"] == 1
    assert witness["step_id"] == "step.02-strand-service-flow"
    assert witness["requirement_id"] == "requirement.preserve-service-flow"
    assert result["next_observation"] is None
    assert result["next_evidence_requests"] == ["assumption.qcp-applicability"]


def test_determinism_input_immutability_and_complete_candidate_accounting() -> None:
    request_raw = FIXTURE.read_bytes()
    before = bytes(request_raw)
    first, result = _result(request_raw)
    second, second_result = _result(request_raw)
    assert first == second
    assert result == second_result
    assert request_raw == before
    request = _request()
    assert len(result["candidate_results"]) == len(request["candidates"])
    assert {item["candidate_id"] for item in result["candidate_results"]} == {
        item["candidate_id"] for item in request["candidates"]
    }
    assert len(first) <= discovery.MAX_OUTPUT_BYTES


def test_counterexample_replay_is_exact_and_rejects_teleportation() -> None:
    _encoded, result = _result()
    witness = _candidate(result, "candidate.unsafe-middle")["counterexamples"][0]
    witness_raw = canonical_json_bytes(witness)
    replay_raw = discovery.replay_counterexample_bytes(FIXTURE.read_bytes(), witness_raw)
    replay = parse_canonical_json_bytes(replay_raw, require_canonical=True)
    assert replay == {
        "authoritative": False,
        "candidate_digest": witness["candidate_digest"],
        "decision_effect": "NONE",
        "input_digest": witness["input_digest"],
        "replayed": True,
        "schema": discovery.REPLAY_SCHEMA,
        "semantics_digest": witness["semantics_digest"],
        "witness_digest": witness["witness_digest"],
    }

    changed_case = _request()
    changed_case["case_id"] = "qdp001-fixture:other-case"
    _error(
        "WITNESS_NOT_REPLAYED",
        lambda: discovery.replay_counterexample_bytes(_canonical(changed_case), witness_raw),
    )

    narrowed = _request()
    narrowed["candidates"] = [
        item for item in narrowed["candidates"] if item["candidate_id"] == "candidate.unsafe-middle"
    ]
    _error(
        "WITNESS_NOT_REPLAYED",
        lambda: discovery.replay_counterexample_bytes(_canonical(narrowed), witness_raw),
    )

    mutated_witness = deepcopy(witness)
    mutated_witness["step_index"] = 0
    _error(
        "WITNESS_DIGEST_MISMATCH",
        lambda: discovery.replay_counterexample_bytes(
            FIXTURE.read_bytes(), canonical_json_bytes(mutated_witness)
        ),
    )


def test_replay_semantics_bind_the_closed_repo_dependency_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_sources = {
        "adapter",
        "cutover_sim",
        "discovery_input_schema",
        "discovery_result_schema",
        "failover",
        "fib",
        "transition_contract",
        "whatif",
    }
    source_paths = discovery._semantic_source_paths()
    assert set(source_paths) == expected_sources
    for path, _error_code in source_paths.values():
        assert type(path) is str and Path(path).is_file()

    request_raw = FIXTURE.read_bytes()
    _old_raw, old_result = _result(request_raw)
    old_witness = _candidate(old_result, "candidate.unsafe-middle")["counterexamples"][0]
    old_witness_raw = _canonical(old_witness)

    changed_failover = tmp_path / "failover.py"
    changed_failover.write_bytes(Path(discovery.failover.__file__).read_bytes() + b"\n# semantic change\n")
    monkeypatch.setattr(discovery.failover, "__file__", str(changed_failover))
    _new_raw, new_result = _result(request_raw)
    assert new_result["semantics_digest"] != old_result["semantics_digest"]
    new_witness = _candidate(new_result, "candidate.unsafe-middle")["counterexamples"][0]
    assert new_witness["semantics_digest"] == new_result["semantics_digest"]
    assert new_witness["witness_digest"] != old_witness["witness_digest"]
    _error(
        "WITNESS_NOT_REPLAYED",
        lambda: discovery.replay_counterexample_bytes(request_raw, old_witness_raw),
    )

def test_cli_is_bounded_stdout_only_and_matches_library_bytes(tmp_path: Path) -> None:
    before = sorted(tmp_path.iterdir())
    completed = subprocess.run(
        [sys.executable, "-B", str(TOOL), "--fixture"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stderr == b""
    assert completed.stdout == discovery.analyze_request_bytes(FIXTURE.read_bytes())
    assert sorted(tmp_path.iterdir()) == before

    stdin_run = subprocess.run(
        [sys.executable, "-B", str(TOOL)],
        cwd=tmp_path,
        input=FIXTURE.read_bytes(),
        capture_output=True,
        check=False,
    )
    assert stdin_run.returncode == 0
    assert stdin_run.stderr == b""
    assert stdin_run.stdout == completed.stdout

    oversized = subprocess.run(
        [sys.executable, "-B", str(TOOL)],
        cwd=tmp_path,
        input=b" " * (discovery.MAX_INPUT_BYTES + 1),
        capture_output=True,
        check=False,
    )
    assert oversized.returncode == 2
    assert oversized.stdout == b""
    assert json.loads(oversized.stderr)["error"]["code"] == "INPUT_BYTE_LIMIT"
    assert sorted(tmp_path.iterdir()) == before

    arbitrary_path = subprocess.run(
        [sys.executable, "-B", str(TOOL), "PRIVATE_PATH_SENTINEL"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert arbitrary_path.returncode == 2
    assert arbitrary_path.stdout == b""
    assert b"PRIVATE_PATH_SENTINEL" not in arbitrary_path.stderr
    assert json.loads(arbitrary_path.stderr)["error"]["code"] == "CLI_ARGUMENTS_INVALID"
    assert sorted(tmp_path.iterdir()) == before


def test_fixed_fixture_reader_uses_one_bounded_regular_nonreparse_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    normal = tmp_path / "fixture.json"
    normal.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(discovery, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(discovery, "_FIXTURE_PATH", normal)
    assert discovery._bounded_fixture_bytes() == FIXTURE.read_bytes()

    normal.write_bytes(b" " * (discovery.MAX_INPUT_BYTES + 1))
    _error("INPUT_BYTE_LIMIT", discovery._bounded_fixture_bytes)

    reparse_flag = 0x400
    monkeypatch.setattr(
        discovery.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        reparse_flag,
        raising=False,
    )
    monkeypatch.setattr(
        discovery.os,
        "lstat",
        lambda _path: SimpleNamespace(
            st_file_attributes=reparse_flag,
            st_mode=discovery.stat.S_IFREG,
        ),
    )
    _error("FIXTURE_REPARSE_FORBIDDEN", discovery._bounded_fixture_bytes)


def test_noncanonical_duplicate_and_authority_inputs_fail_without_echo() -> None:
    _error(
        "INPUT_CANONICAL_INVALID",
        lambda: discovery.analyze_request_bytes(FIXTURE.read_bytes() + b"\n"),
    )
    duplicate = b'{"schema":"x","schema":"y"}'
    _error("INPUT_CANONICAL_INVALID", lambda: discovery.analyze_request_bytes(duplicate))

    supplied_authority = _request()
    supplied_authority["authority_placeholders"]["R2-AUTH-004"] = "PRIVATE_AUTHORITY_SENTINEL"
    _error(
        "AUTHORITY_VALUES_FORBIDDEN",
        lambda: discovery.analyze_request_bytes(_canonical(supplied_authority)),
    )

    hidden_authority = _request()
    hidden_authority["synthetic_snapshot"]["policy_receipt"] = "PRIVATE_AUTHORITY_SENTINEL"
    _error(
        "UNTRUSTED_AUTHORITY_SHAPED_KEY_FORBIDDEN",
        lambda: discovery.analyze_request_bytes(_canonical(hidden_authority)),
    )

    camel_case_authority = _request()
    camel_case_authority["synthetic_snapshot"]["policyReceipt"] = "PRIVATE_AUTHORITY_SENTINEL"
    _error(
        "UNTRUSTED_AUTHORITY_SHAPED_KEY_FORBIDDEN",
        lambda: discovery.analyze_request_bytes(_canonical(camel_case_authority)),
    )


def test_step_parameter_semantics_must_be_fully_consumed() -> None:
    extra = _request()
    unsafe = next(
        item for item in extra["candidates"] if item["candidate_id"] == "candidate.unsafe-middle"
    )
    unsafe["steps"][1]["parameters"]["rollback_host"] = "Y"
    _error(
        "STEP_PARAMETER_KEYS_INVALID",
        lambda: discovery.analyze_request_bytes(_canonical(extra)),
    )

    unsupported_payload = _request()
    unsupported = next(
        item
        for item in unsupported_payload["candidates"]
        if item["candidate_id"] == "candidate.invalid"
    )
    unsupported["steps"][0]["parameters"] = {"id": "PRIVATE_IGNORED_SENTINEL"}
    _error(
        "UNSUPPORTED_STEP_PARAMETERS_MUST_BE_EMPTY",
        lambda: discovery.analyze_request_bytes(_canonical(unsupported_payload)),
    )


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("assumption", "GO"),
        ("assumption", "assumption.PASS"),
        ("candidate", "candidate.SAFE"),
        ("requirement", "requirement.FEASIBLE"),
        ("step", "step.ELIGIBLE_FOR_HUMAN_DECISION"),
    ],
)
def test_echoed_identifiers_cannot_launder_gate_vocabulary(target: str, value: str) -> None:
    request = _request()
    if target == "assumption":
        request["candidates"][0]["assumptions"][0]["assumption_id"] = value
    elif target == "candidate":
        request["candidates"][0]["candidate_id"] = value
        request["candidates"] = sorted(request["candidates"], key=lambda item: item["candidate_id"])
    elif target == "requirement":
        request["requirements"][0]["requirement_id"] = value
    else:
        request["candidates"][0]["steps"][0]["step_id"] = value
    _error(
        "ECHOED_GATE_VOCABULARY_FORBIDDEN",
        lambda: discovery.analyze_request_bytes(_canonical(request)),
    )


def test_vacuity_and_n_minus_1_n_n_plus_1_candidate_bounds() -> None:
    no_candidates = _request()
    no_candidates["candidates"] = []
    _error("CANDIDATES_INVALID", lambda: discovery.analyze_request_bytes(_canonical(no_candidates)))

    no_requirements = _request()
    no_requirements["requirements"] = []
    _error("REQUIREMENTS_INVALID", lambda: discovery.analyze_request_bytes(_canonical(no_requirements)))

    no_flow = _request()
    no_flow["requirements"] = [
        {
            "dependency_ids": ["R3-DEP-001"],
            "dst": None,
            "kind": "HUMAN_ONLY_UNEVALUATED",
            "owner": "SYNTHETIC_TEST_OWNER",
            "requirement_id": "requirement.human-only",
            "src": None,
        }
    ]
    _error("FLOW_REQUIREMENT_REQUIRED", lambda: discovery.analyze_request_bytes(_canonical(no_flow)))

    base = deepcopy(_request()["candidates"][0])
    for count in (discovery.MAX_CANDIDATES - 1, discovery.MAX_CANDIDATES):
        bounded = _request()
        bounded["candidates"] = []
        for index in range(count):
            candidate = deepcopy(base)
            candidate["candidate_id"] = f"candidate.bound-{index:02d}"
            bounded["candidates"].append(candidate)
        result = parse_canonical_json_bytes(
            discovery.analyze_request_bytes(_canonical(bounded)), require_canonical=True
        )
        assert len(result["candidate_results"]) == count

    excessive = _request()
    excessive["candidates"] = []
    for index in range(discovery.MAX_CANDIDATES + 1):
        candidate = deepcopy(base)
        candidate["candidate_id"] = f"candidate.bound-{index:02d}"
        excessive["candidates"].append(candidate)
    _error("CANDIDATES_INVALID", lambda: discovery.analyze_request_bytes(_canonical(excessive)))


def test_step_and_byte_bounds_refuse_instead_of_truncating() -> None:
    for count in (
        discovery.MAX_STEPS_PER_CANDIDATE - 1,
        discovery.MAX_STEPS_PER_CANDIDATE,
    ):
        request = _request()
        candidate = request["candidates"][0]
        prototype_step = candidate["steps"][0]
        candidate["steps"] = []
        for index in range(count):
            step = deepcopy(prototype_step)
            step["step_id"] = f"step.bound-{index:02d}"
            candidate["steps"].append(step)
        request["candidates"] = [candidate]
        result = parse_canonical_json_bytes(
            discovery.analyze_request_bytes(_canonical(request)), require_canonical=True
        )
        assert result["candidate_results"][0]["checked_steps"] == count

    excessive_steps = _request()
    candidate = excessive_steps["candidates"][0]
    prototype_step = candidate["steps"][0]
    candidate["steps"] = []
    for index in range(discovery.MAX_STEPS_PER_CANDIDATE + 1):
        step = deepcopy(prototype_step)
        step["step_id"] = f"step.bound-{index:02d}"
        candidate["steps"].append(step)
    _error(
        "CANDIDATE_STEPS_INVALID",
        lambda: discovery.analyze_request_bytes(_canonical(excessive_steps)),
    )

    oversized = b" " * (discovery.MAX_INPUT_BYTES + 1)
    _error("INPUT_BYTE_LIMIT", lambda: discovery.analyze_request_bytes(oversized))


def test_output_witness_and_counterexample_bounds_refuse_instead_of_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _error(
        "WITNESS_BYTE_LIMIT",
        lambda: discovery.replay_counterexample_bytes(
            FIXTURE.read_bytes(), b" " * (discovery.MAX_WITNESS_BYTES + 1)
        ),
    )
    with monkeypatch.context() as patch:
        patch.setattr(discovery, "MAX_OUTPUT_BYTES", 1)
        _error("OUTPUT_BYTE_LIMIT", lambda: discovery.analyze_request_bytes(FIXTURE.read_bytes()))
    with monkeypatch.context() as patch:
        patch.setattr(discovery, "MAX_COUNTEREXAMPLES", 0)
        _error(
            "COUNTEREXAMPLE_BOUND_EXCEEDED",
            lambda: discovery.analyze_request_bytes(FIXTURE.read_bytes()),
        )


def test_path_loss_and_baseline_conflict_abstain_without_counterexample() -> None:
    path_loss = _request()
    path_loss["candidates"] = [
        {
            "assumptions": [],
            "candidate_id": "candidate.path-loss",
            "source_class": "SYNTHETIC_TEST_ONLY",
            "steps": [
                {
                    "action": "fail_node",
                    "parameters": {"id": "Y"},
                    "step_id": "step.01-remove-next-hop-owner",
                }
            ],
        }
    ]
    _encoded, result = _result(_canonical(path_loss))
    candidate = result["candidate_results"][0]
    assert candidate["result_kind"] == "ABSTENTION"
    assert candidate["reason_code"] == "ABSTAIN_EVIDENCE_INCOMPLETE"
    assert candidate["counterexamples"] == []
    assert "PATH_LOSS_IS_INCONCLUSIVE" in candidate["limitations"]

    conflict = _request()
    conflict["requirements"][0]["dst"] = "10.0.9.200"
    _encoded, result = _result(_canonical(conflict))
    for candidate in result["candidate_results"]:
        assert candidate["result_kind"] == "ABSTENTION"
        assert candidate["reason_code"] in {"MODEL_CONFLICT", "NOT_EVALUABLE"}
        assert candidate["counterexamples"] == []


def test_absence_derived_newly_blocked_result_abstains_without_counterexample() -> None:
    request = _request()
    request["synthetic_snapshot"]["routes"]["A"] = [
        row
        for row in request["synthetic_snapshot"]["routes"]["A"]
        if row.get("out_intf") != "Null0"
    ]
    request["candidates"] = [
        item for item in request["candidates"] if item["candidate_id"] == "candidate.unsafe-middle"
    ]
    _encoded, result = _result(_canonical(request))
    candidate = result["candidate_results"][0]
    assert candidate["result_kind"] == "ABSTENTION"
    assert candidate["reason_code"] == "ABSTAIN_EVIDENCE_INCOMPLETE"
    assert candidate["counterexamples"] == []
    assert "BLOCKED_FLOW_WITHOUT_POSITIVE_OBSERVED_DISCARD" in candidate["limitations"]


def test_baseline_exception_abstains_even_when_simulator_finds_a_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_baseline(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_BASELINE_ERROR_SENTINEL")

    monkeypatch.setattr(discovery.fib, "trace_fib_path", unavailable_baseline)
    encoded = discovery.analyze_request_bytes(FIXTURE.read_bytes())
    assert b"PRIVATE_BASELINE_ERROR_SENTINEL" not in encoded
    result = parse_canonical_json_bytes(encoded, require_canonical=True)
    unsafe = _candidate(result, "candidate.unsafe-middle")
    assert unsafe["result_kind"] == "ABSTENTION"
    assert unsafe["reason_code"] == "ABSTAIN_EVIDENCE_INCOMPLETE"
    assert unsafe["counterexamples"] == []
    assert "BASELINE_EVIDENCE_INCOMPLETE" in unsafe["limitations"]


def test_human_requirement_stays_unresolved_and_never_disappears() -> None:
    request = _request()
    request["requirements"].insert(
        0,
        {
            "dependency_ids": ["R3-DEP-005"],
            "dst": None,
            "kind": "HUMAN_ONLY_UNEVALUATED",
            "owner": "SYNTHETIC_TEST_OWNER",
            "requirement_id": "requirement.human-disposition",
            "src": None,
        },
    )
    _encoded, result = _result(_canonical(request))
    assert "requirement.human-disposition" in result["next_evidence_requests"]
    assert all(
        "HUMAN_REQUIREMENT_UNEVALUATED" in item["limitations"]
        for item in result["candidate_results"]
    )
    assert all(item["result_kind"] == "ABSTENTION" for item in result["candidate_results"])
    assert all(
        item["reason_code"] in {"ABSTAIN_EVIDENCE_INCOMPLETE", "NOT_EVALUABLE"}
        for item in result["candidate_results"]
    )
    assert all(item["counterexamples"] == [] for item in result["candidate_results"])


def test_unresolved_candidate_assumption_outranks_observed_discard() -> None:
    request = _request()
    unsafe = next(
        item for item in request["candidates"] if item["candidate_id"] == "candidate.unsafe-middle"
    )
    unsafe["assumptions"] = [
        {
            "assumption_id": "assumption.unresolved-path-semantics",
            "dependency_ids": ["R3-DEP-003"],
            "state": "UNRESOLVED",
        }
    ]
    _encoded, result = _result(_canonical(request))
    unsafe_result = _candidate(result, "candidate.unsafe-middle")
    assert unsafe_result["result_kind"] == "ABSTENTION"
    assert unsafe_result["reason_code"] == "ABSTAIN_EVIDENCE_INCOMPLETE"
    assert unsafe_result["counterexamples"] == []
    assert "UNRESOLVED_ASSUMPTION" in unsafe_result["limitations"]


def test_fixed_r2_handoffs_and_product_boundaries_reconcile_to_source_assets() -> None:
    _encoded, result = _result()
    qcp = json.loads((ROOT / "cisco_toolkit" / "data" / "qcp-001.experimental.json").read_text())
    runtime = json.loads(
        (ROOT / "cisco_toolkit" / "data" / "atlas-r2-runtime-inventory.reference.v1.json").read_text()
    )
    assert result["product_boundary"]["qcp_001"] == {
        "execution_state": qcp["execution_state"],
        "qualification_state": qcp["qualification_state"],
    }
    assert result["product_boundary"]["runtime"] == runtime["closure"]["state"]
    assert result["product_boundary"]["release_2"] == "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT"
    assert result["product_boundary"]["release_3"] == "DISCOVERY_PLANNING_ONLY"

    handoffs = result["r2_closure_handoffs"]
    assert handoffs["R2-AUTH-001"]["selection_receipt"] is None
    assert handoffs["R2-AUTH-001"]["evidence_collection_started"] is False
    assert handoffs["R2-AUTH-002"]["stage_a_plan_receipt"] is None
    assert handoffs["R2-AUTH-002"]["stage_b_adequacy_receipt"] is None
    assert handoffs["R2-AUTH-002"]["workload_evidence_collection_started"] is False
    assert handoffs["R2-AUTH-004"]["profile_state"] == "PROPOSED_UNAPPROVED"
    assert handoffs["R2-AUTH-004"]["implementation_approval_receipt"] is None
    assert handoffs["R2-AUTH-004"]["operational_designation_receipt"] is None
    assert handoffs["R2-AUTH-004"]["real_keys_or_signatures_created"] is False


def test_adapter_cannot_import_or_emit_authoritative_gate_surfaces() -> None:
    source = TOOL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    forbidden_imports = {
        "cisco_toolkit.transition_verifier",
        "cisco_toolkit.transition_pack",
        "cisco_toolkit.transition_dsl",
        "tools.bind_atlas_r2_authority_decision",
        "cisco_toolkit.transition_workload_review",
        "cisco_toolkit.transition_runtime_closure",
    }
    assert imported.isdisjoint(forbidden_imports)
    assert called.isdisjoint(
        {
            "map_authoritative_gate",
            "verify_transition_case",
            "run_reviewed_dsl_pack_abi",
            "bind_decision",
            "verify_transition_workload_review",
        }
    )
    assert source.index("sys.dont_write_bytecode = True") < source.index(
        "from cisco_toolkit import cutover_sim, fib"
    )

    encoded, _result_value = _result()
    text = encoded.decode("utf-8")
    for forbidden_token in (
        '"PASS"',
        '"GO"',
        '"SAFE"',
        '"FEASIBLE"',
        "ELIGIBLE_FOR_HUMAN_DECISION",
        "OBSERVED_BREACH",
        "CONFLICT_REQUIRES_RESOLUTION",
        '"EVIDENCE_INCOMPLETE"',
    ):
        assert forbidden_token not in text


def test_result_schema_rejects_laundered_limitations() -> None:
    _encoded, result = _result()
    schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    candidate_schema = schema["$defs"]["candidateResult"]
    assert set(candidate_schema["properties"]["limitations"]["items"]["enum"]) == set(
        discovery.LIMITATION_CODES
    )
    assert set(candidate_schema["properties"]["reason_code"]["enum"]) == (
        set(discovery.ABSTENTION_REASON_CODES)
        | {"REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW"}
    )
    laundered = deepcopy(result)
    laundered["candidate_results"][0]["limitations"] = ["GO", "PASS"]
    assert list(Draft202012Validator(schema).iter_errors(laundered))

    mutations = []
    case_id = deepcopy(result)
    case_id["case_id"] = "qdp001-fixture:go"
    mutations.append(case_id)
    candidate_id = deepcopy(result)
    candidate_id["candidate_results"][0]["candidate_id"] = "candidate.safe"
    mutations.append(candidate_id)
    evidence_request = deepcopy(result)
    evidence_request["next_evidence_requests"] = ["go"]
    mutations.append(evidence_request)
    witness_step = deepcopy(result)
    unsafe = next(
        item
        for item in witness_step["candidate_results"]
        if item["candidate_id"] == "candidate.unsafe-middle"
    )
    unsafe["counterexamples"][0]["step_id"] = "step.pass"
    mutations.append(witness_step)
    for mutation in mutations:
        assert list(Draft202012Validator(schema).iter_errors(mutation))


def test_input_schema_rejects_gate_shaped_namespaced_identifiers() -> None:
    schema = json.loads(INPUT_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    request = _request()
    request["case_id"] = "qdp001-fixture:go"
    assert list(validator.iter_errors(request))
    request = _request()
    request["candidates"][0]["candidate_id"] = "candidate.safe"
    assert list(validator.iter_errors(request))
