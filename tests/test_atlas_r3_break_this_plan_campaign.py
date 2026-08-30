"""Adversarial tests for the bounded QDP-001 synthetic campaign capsule."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

from cisco_toolkit.transition_contract import (
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)
from tools import run_atlas_r3_break_this_plan_campaign as campaign
from tools import run_atlas_r3_break_this_plan_discovery as discovery


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "atlas-r3-break-this-plan" / "campaign.synthetic.json"
INPUT_SCHEMA = (
    ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-campaign-input-v1.schema.json"
)
RESULT_SCHEMA = (
    ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-campaign-result-v1.schema.json"
)
DISCOVERY_INPUT_SCHEMA = (
    ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-discovery-input-v1.schema.json"
)
DISCOVERY_RESULT_SCHEMA = (
    ROOT / "docs" / "schemas" / "atlas-r3-break-this-plan-discovery-result-v1.schema.json"
)
SCRIPT = ROOT / "tools" / "run_atlas_r3_break_this_plan_campaign.py"


def _campaign() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _canonical(value: dict) -> bytes:
    return canonical_json_bytes(value)


def _result(value: dict | None = None) -> tuple[bytes, dict]:
    raw = campaign.analyze_campaign_bytes(_canonical(value or _campaign()))
    return raw, parse_canonical_json_bytes(raw, require_canonical=True)


def _schemas() -> tuple[Draft202012Validator, Draft202012Validator]:
    discovery_input = json.loads(DISCOVERY_INPUT_SCHEMA.read_text(encoding="utf-8"))
    discovery_result = json.loads(DISCOVERY_RESULT_SCHEMA.read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [
            (
                "urn:atlas:r3:break-this-plan:discovery-input:1",
                Resource.from_contents(discovery_input),
            ),
            (
                "urn:atlas:r3:break-this-plan:discovery-result:1",
                Resource.from_contents(discovery_result),
            ),
        ]
    )
    input_schema = json.loads(INPUT_SCHEMA.read_text(encoding="utf-8"))
    result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(result_schema)
    return (
        Draft202012Validator(input_schema, registry=registry),
        Draft202012Validator(result_schema, registry=registry),
    )


def _error(code: str, call) -> None:
    with pytest.raises(campaign.BreakThisPlanCampaignError) as exc:
        call()
    assert exc.value.code == code
    assert code in campaign._error_bytes(exc.value.code).decode("ascii")


def _campaign_with_cases(cases: list[dict]) -> dict:
    value = _campaign()
    value["cases"] = sorted(deepcopy(cases), key=lambda item: item["case_id"])
    return value


def test_fixture_and_result_are_canonical_schema_valid_and_nonpromoting() -> None:
    fixture_raw = FIXTURE.read_bytes()
    value = _campaign()
    assert fixture_raw == _canonical(value)
    input_validator, result_validator = _schemas()
    input_validator.validate(value)

    result_raw, result = _result(value)
    assert result_raw == _canonical(result)
    result_validator.validate(result)
    assert result["summary"] == {
        "abstention_candidate_count": 5,
        "candidate_count": 6,
        "case_count": 4,
        "counterexample_candidate_count": 1,
        "counterexample_count": 1,
        "replay_failure_count": 0,
        "replayed_counterexample_count": 1,
    }
    assert result["authoritative"] is False
    assert result["authoritative_gate"] is None
    assert result["decision_effect"] == "NONE"
    assert result["selected_candidate"] is None
    assert result["feasibility_verdict"] is None
    assert result["translation_checked"] is False
    assert result["preview_eligible"] is False
    assert result["promotion_eligible"] is False
    assert result["product_boundary"] == discovery.PRODUCT_BOUNDARY
    assert result["authority_placeholders"] == {item: None for item in discovery.AUTHORITY_IDS}
    assert result["unresolved_dependency_ids"] == list(discovery.UNRESOLVED_DEPENDENCY_IDS)

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


def test_complete_case_candidate_limitation_and_replay_accounting_reconciles() -> None:
    value = _campaign()
    result_raw, result = _result(value)
    assert result["campaign_input_digest"] == bytes_digest(_canonical(value))
    assert len(result["case_reports"]) == len(value["cases"])

    expected_bindings = []
    limitations: Counter[str] = Counter()
    abstentions: Counter[str] = Counter()
    candidate_count = counterexample_count = replay_count = 0
    for request, case_report in zip(value["cases"], result["case_reports"], strict=True):
        request_raw = _canonical(request)
        expected_result_raw = discovery.analyze_request_bytes(request_raw)
        expected_result = parse_canonical_json_bytes(
            expected_result_raw, require_canonical=True
        )
        assert case_report["case_id"] == request["case_id"]
        assert case_report["input_digest"] == bytes_digest(request_raw)
        assert case_report["discovery_result"] == expected_result
        assert case_report["discovery_result_digest"] == bytes_digest(expected_result_raw)
        expected_bindings.append(
            {
                "case_id": request["case_id"],
                "discovery_result_digest": bytes_digest(expected_result_raw),
                "input_digest": bytes_digest(request_raw),
            }
        )
        emitted = [
            witness
            for candidate_result in expected_result["candidate_results"]
            for witness in candidate_result["counterexamples"]
        ]
        assert len(case_report["replay_receipts"]) == len(emitted)
        for witness, envelope in zip(emitted, case_report["replay_receipts"], strict=True):
            replay_raw = discovery.replay_counterexample_bytes(
                request_raw, _canonical(witness)
            )
            replay = parse_canonical_json_bytes(replay_raw, require_canonical=True)
            assert envelope["replay_receipt"] == replay
            assert envelope["replay_receipt_digest"] == bytes_digest(replay_raw)
            assert envelope["campaign_replay_binding_digest"] == canonical_digest(
                {
                    "campaign_id": result["campaign_id"],
                    "campaign_input_digest": result["campaign_input_digest"],
                    "case_set_digest": result["case_set_digest"],
                    "replay_receipt_digest": bytes_digest(replay_raw),
                }
            )
        candidate_count += len(expected_result["candidate_results"])
        counterexample_count += len(emitted)
        replay_count += len(case_report["replay_receipts"])
        for candidate_result in expected_result["candidate_results"]:
            limitations.update(candidate_result["limitations"])
            if candidate_result["result_kind"] == "ABSTENTION":
                abstentions[candidate_result["reason_code"]] += 1
    assert result["case_set_digest"] == canonical_digest(expected_bindings)
    assert result["summary"]["candidate_count"] == candidate_count
    assert result["summary"]["counterexample_count"] == counterexample_count
    assert result["summary"]["replayed_counterexample_count"] == replay_count
    assert result["limitation_counts"] == campaign._count_rows(limitations)
    assert result["abstention_reason_counts"] == campaign._count_rows(abstentions)
    assert bytes_digest(result_raw).startswith("sha256:")


def test_campaign_binding_changes_when_a_case_is_narrowed_but_child_witness_does_not() -> None:
    full_value = _campaign()
    _, full = _result(full_value)
    unsafe = next(row for row in full["case_reports"] if row["case_id"].endswith("unsafe-middle"))
    full_witness = unsafe["discovery_result"]["candidate_results"][2]["counterexamples"][0]
    full_binding = unsafe["replay_receipts"][0]["campaign_replay_binding_digest"]

    narrowed_value = _campaign_with_cases([full_value["cases"][-1]])
    _, narrowed = _result(narrowed_value)
    narrowed_case = narrowed["case_reports"][0]
    narrowed_witness = narrowed_case["discovery_result"]["candidate_results"][2][
        "counterexamples"
    ][0]
    assert narrowed_witness == full_witness
    assert narrowed["case_set_digest"] != full["case_set_digest"]
    assert narrowed_case["replay_receipts"][0]["campaign_replay_binding_digest"] != full_binding


def test_campaign_replay_binding_covers_full_child_result_and_limitations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _campaign_with_cases([_campaign()["cases"][-1]])
    _, before = _result(value)
    before_case = before["case_reports"][0]
    before_candidate = before_case["discovery_result"]["candidate_results"][2]
    before_witness = before_candidate["counterexamples"][0]
    before_binding = before_case["replay_receipts"][0]["campaign_replay_binding_digest"]
    original = discovery.cutover_sim.failover.compute_failover_twin

    def add_election_projection(snapshot, failures):
        changed = deepcopy(original(snapshot, failures))
        changed["stp"] = list(changed.get("stp", [])) + [
            {"indeterminate": False, "new_root": "synthetic-root"}
        ]
        return changed

    monkeypatch.setattr(
        discovery.cutover_sim.failover,
        "compute_failover_twin",
        add_election_projection,
    )
    _, after = _result(value)
    after_case = after["case_reports"][0]
    after_candidate = after_case["discovery_result"]["candidate_results"][2]
    after_witness = after_candidate["counterexamples"][0]
    assert after_case["discovery_result"]["semantics_digest"] == before_case[
        "discovery_result"
    ]["semantics_digest"]
    assert after_witness["witness_digest"] == before_witness["witness_digest"]
    assert "ELECTION_PROJECTION_NOT_CONTINUITY_EVIDENCE" in after_candidate["limitations"]
    assert after_case["discovery_result_digest"] != before_case["discovery_result_digest"]
    assert after["case_set_digest"] != before["case_set_digest"]
    assert (
        after_case["replay_receipts"][0]["campaign_replay_binding_digest"]
        != before_binding
    )


def test_operator_report_is_complete_readable_and_never_launders_abstention() -> None:
    value = _campaign()
    report_raw = campaign.render_operator_report_bytes(_canonical(value))
    report = report_raw.decode("utf-8")
    assert report_raw == campaign.render_operator_report_bytes(_canonical(value))
    assert report.startswith("# Atlas R3 Break This Plan — Synthetic Campaign Report\n")
    assert "R3 SYNTHETIC CAMPAIGN — NON-AUTHORITATIVE" in report
    assert "no candidate is ranked or selected" in report
    assert "An abstention is never candidate support or a safety inference" in report
    assert "Emitted/replayed counterexamples: 1/1" in report
    for case in value["cases"]:
        assert f"`{case['case_id']}`" in report
        for candidate_value in case["candidates"]:
            assert f"`{candidate_value['candidate_id']}`" in report
    _, result = _result(value)
    for row in result["limitation_counts"]:
        assert f"`{row['code']}`: {row['count']} candidate(s)" in report
    assert "R2-AUTH-002" in report and "Stage A plan and Stage B adequacy receipts are `null`" in report
    assert "R2-AUTH-004" in report and "real keys/signatures created = `false`" in report
    for forbidden_raw_projection in (
        "newly_lost_flows",
        "split_brain_risks",
        "stp_reroots",
        "fhrp_takeovers",
        "narrative",
    ):
        assert forbidden_raw_projection not in report

    all_abstention = _campaign_with_cases(value["cases"][:3])
    all_abstention_report = campaign.render_operator_report_bytes(
        _canonical(all_abstention)
    ).decode("utf-8")
    assert "Counterexample candidates: 0" in all_abstention_report
    assert "Abstention candidates: 3" in all_abstention_report
    assert "Emitted/replayed counterexamples: 0/0" in all_abstention_report
    assert "never candidate support" in all_abstention_report


def test_determinism_input_immutability_and_case_bounds() -> None:
    value = _campaign()
    before = deepcopy(value)
    raw = _canonical(value)
    assert campaign.analyze_campaign_bytes(raw) == campaign.analyze_campaign_bytes(raw)
    assert value == before

    base = value["cases"][0]
    for count in (campaign.MAX_CASES - 1, campaign.MAX_CASES):
        cases = []
        for index in range(count):
            item = deepcopy(base)
            item["case_id"] = f"qdp001-fixture:bound-{index:02d}"
            cases.append(item)
        _, result = _result(_campaign_with_cases(cases))
        assert result["summary"]["case_count"] == count
        assert result["summary"]["candidate_count"] == count
    too_many = []
    for index in range(campaign.MAX_CASES + 1):
        item = deepcopy(base)
        item["case_id"] = f"qdp001-fixture:bound-{index:02d}"
        too_many.append(item)
    _error(
        "CAMPAIGN_CASES_INVALID",
        lambda: campaign.analyze_campaign_bytes(_canonical(_campaign_with_cases(too_many))),
    )


def test_noncanonical_duplicate_authority_boundary_and_case_inputs_fail_closed() -> None:
    value = _campaign()
    raw = _canonical(value)
    _error(
        "CAMPAIGN_INPUT_CANONICAL_INVALID",
        lambda: campaign.analyze_campaign_bytes(b" " + raw),
    )
    duplicate = b'{"campaign_id":"qdp001-campaign:duplicate",' + raw[1:]
    _error(
        "CAMPAIGN_INPUT_CANONICAL_INVALID",
        lambda: campaign.analyze_campaign_bytes(duplicate),
    )

    empty = deepcopy(value)
    empty["cases"] = []
    _error(
        "CAMPAIGN_CASES_INVALID",
        lambda: campaign.analyze_campaign_bytes(_canonical(empty)),
    )
    reversed_cases = deepcopy(value)
    reversed_cases["cases"].reverse()
    _error(
        "CAMPAIGN_CASES_NOT_SORTED_UNIQUE",
        lambda: campaign.analyze_campaign_bytes(_canonical(reversed_cases)),
    )
    duplicate_case = deepcopy(value)
    duplicate_case["cases"] = [deepcopy(value["cases"][0]), deepcopy(value["cases"][0])]
    _error(
        "CAMPAIGN_CASES_NOT_SORTED_UNIQUE",
        lambda: campaign.analyze_campaign_bytes(_canonical(duplicate_case)),
    )

    authority = deepcopy(value)
    authority["authority_placeholders"]["R2-AUTH-002"] = {"approved": True}
    _error(
        "AUTHORITY_VALUES_FORBIDDEN",
        lambda: campaign.analyze_campaign_bytes(_canonical(authority)),
    )
    product = deepcopy(value)
    product["product_boundary"]["release_3"] = "QUALIFIED"
    _error(
        "PRODUCT_BOUNDARY_DRIFT",
        lambda: campaign.analyze_campaign_bytes(_canonical(product)),
    )
    nested = deepcopy(value)
    nested["cases"][0]["synthetic_snapshot"]["trustPolicy"] = "do-not-echo"
    _error(
        "CAMPAIGN_CASE_REANALYSIS_FAILED",
        lambda: campaign.analyze_campaign_bytes(_canonical(nested)),
    )
    with pytest.raises(campaign.BreakThisPlanCampaignError) as exc:
        campaign.analyze_campaign_bytes(_canonical(nested))
    assert "do-not-echo" not in str(exc.value)


def test_byte_output_report_and_replay_bounds_refuse_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _error(
        "CAMPAIGN_INPUT_BYTE_LIMIT",
        lambda: campaign.analyze_campaign_bytes(b"x" * (campaign.MAX_INPUT_BYTES + 1)),
    )
    raw = _canonical(_campaign())
    monkeypatch.setattr(campaign, "MAX_OUTPUT_BYTES", 1)
    _error("CAMPAIGN_OUTPUT_BYTE_LIMIT", lambda: campaign.analyze_campaign_bytes(raw))
    monkeypatch.setattr(campaign, "MAX_OUTPUT_BYTES", 8_388_608)
    monkeypatch.setattr(campaign, "MAX_OPERATOR_REPORT_BYTES", 1)
    _error("OPERATOR_REPORT_BYTE_LIMIT", lambda: campaign.render_operator_report_bytes(raw))


def test_replay_failure_and_mixed_discovery_semantics_refuse_whole_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _canonical(_campaign())

    def fail_replay(_request: bytes, _witness: bytes) -> bytes:
        raise discovery.BreakThisPlanDiscoveryError("INJECTED_REPLAY_FAILURE")

    monkeypatch.setattr(discovery, "replay_counterexample_bytes", fail_replay)
    _error("CAMPAIGN_COUNTEREXAMPLE_REPLAY_FAILED", lambda: campaign.analyze_campaign_bytes(raw))

    monkeypatch.undo()
    original_analyze = discovery.analyze_request_bytes

    def mixed_semantics(request_raw: bytes) -> bytes:
        result = parse_canonical_json_bytes(
            original_analyze(request_raw), require_canonical=True
        )
        result["semantics_digest"] = (
            "sha256:" + ("a" if result["case_id"].endswith("baseline-conflict") else "b") * 64
        )
        return canonical_json_bytes(result)

    monkeypatch.setattr(discovery, "analyze_request_bytes", mixed_semantics)
    all_abstention = _campaign_with_cases(_campaign()["cases"][:3])
    _error(
        "CAMPAIGN_CASE_SEMANTICS_INVALID",
        lambda: campaign.analyze_campaign_bytes(_canonical(all_abstention)),
    )


def test_child_result_authority_handoff_limitation_and_binding_drift_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _campaign_with_cases([_campaign()["cases"][0]])
    raw = _canonical(value)
    original = discovery.analyze_request_bytes

    def expect_mutation(code: str, mutate) -> None:
        def forged(request_raw: bytes) -> bytes:
            result = parse_canonical_json_bytes(
                original(request_raw), require_canonical=True
            )
            mutate(result)
            return canonical_json_bytes(result)

        monkeypatch.setattr(discovery, "analyze_request_bytes", forged)
        _error(code, lambda: campaign.analyze_campaign_bytes(raw))

    expect_mutation(
        "CAMPAIGN_CASE_NONPROMOTION_BOUNDARY_DRIFT",
        lambda result: result.__setitem__("authoritative", True),
    )
    expect_mutation(
        "CAMPAIGN_CASE_HANDOFF_DRIFT",
        lambda result: result["r2_closure_handoffs"]["R2-AUTH-002"].__setitem__(
            "stage_a_plan_receipt", "synthetic"
        ),
    )

    def add_unknown_limitation(result: dict) -> None:
        limitations = result["candidate_results"][0]["limitations"]
        limitations.append("UNREVIEWED_LIMIT")
        limitations.sort()

    expect_mutation("CAMPAIGN_LIMITATION_ACCOUNTING_INVALID", add_unknown_limitation)
    expect_mutation(
        "CAMPAIGN_CASE_INPUT_BINDING_INVALID",
        lambda result: result.__setitem__("input_digest", "sha256:" + "0" * 64),
    )
    expect_mutation(
        "CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID",
        lambda result: result.__setitem__("next_evidence_requests", ["selected"]),
    )
    expect_mutation(
        "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID",
        lambda result: result.__setitem__("candidate_results", []),
    )
    expect_mutation(
        "CAMPAIGN_LIMITATION_ACCOUNTING_INVALID",
        lambda result: result["candidate_results"][0].__setitem__("limitations", []),
    )
    expect_mutation(
        "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID",
        lambda result: result["candidate_results"][0].__setitem__("checked_steps", 999),
    )
    expect_mutation(
        "CAMPAIGN_CASE_SEMANTICS_INVALID",
        lambda result: result.__setitem__("semantics_digest", "sha256:" + "0" * 64),
    )


def test_lockstep_child_handoff_and_forged_replay_authority_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _canonical(_campaign())
    forged_handoffs = deepcopy(campaign.EXPECTED_R2_CLOSURE_HANDOFFS)
    forged_handoffs["R2-AUTH-002"]["stage_a_plan_receipt"] = "synthetic"
    monkeypatch.setattr(discovery, "_closure_handoffs", lambda: deepcopy(forged_handoffs))
    _error("CAMPAIGN_CASE_HANDOFF_DRIFT", lambda: campaign.analyze_campaign_bytes(raw))

    monkeypatch.undo()
    original_replay = discovery.replay_counterexample_bytes

    def authority_laundered_replay(request_raw: bytes, witness_raw: bytes) -> bytes:
        replay = parse_canonical_json_bytes(
            original_replay(request_raw, witness_raw), require_canonical=True
        )
        replay["authoritative"] = True
        replay["decision_effect"] = "SELECT"
        return canonical_json_bytes(replay)

    monkeypatch.setattr(
        discovery,
        "replay_counterexample_bytes",
        authority_laundered_replay,
    )
    _error(
        "CAMPAIGN_REPLAY_RECEIPT_BINDING_INVALID",
        lambda: campaign.analyze_campaign_bytes(raw),
    )


def test_partial_child_candidate_omission_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _campaign_with_cases([_campaign()["cases"][-1]])
    raw = _canonical(value)
    original = discovery.analyze_request_bytes

    def omitted_candidate(request_raw: bytes) -> bytes:
        result = parse_canonical_json_bytes(
            original(request_raw), require_canonical=True
        )
        result["candidate_results"].pop(0)
        return canonical_json_bytes(result)

    monkeypatch.setattr(discovery, "analyze_request_bytes", omitted_candidate)
    _error(
        "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID",
        lambda: campaign.analyze_campaign_bytes(raw),
    )


def test_per_case_counterexample_aggregate_n_and_n_plus_one_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _campaign_with_cases([_campaign()["cases"][-1]])
    case = value["cases"][0]
    unsafe = deepcopy(case["candidates"][-1])
    unsafe["assumptions"] = []
    case["candidates"] = []
    for suffix in ("alpha", "beta", "gamma"):
        candidate_value = deepcopy(unsafe)
        candidate_value["candidate_id"] = f"candidate.{suffix}"
        case["candidates"].append(candidate_value)
    raw = _canonical(value)
    original_analyze = discovery.analyze_request_bytes
    counts = [43, 43, 42]

    def expanded_analyze(request_raw: bytes) -> bytes:
        result = parse_canonical_json_bytes(
            original_analyze(request_raw), require_canonical=True
        )
        for candidate_result, count in zip(
            result["candidate_results"], counts, strict=True
        ):
            template = candidate_result["counterexamples"][0]
            witnesses = []
            for index in range(count):
                witness = deepcopy(template)
                witness["observation_digest"] = bytes_digest(
                    f"{candidate_result['candidate_id']}:{index}".encode("ascii")
                )
                body = {
                    key: item
                    for key, item in witness.items()
                    if key != "witness_digest"
                }
                witness["witness_digest"] = canonical_digest(body)
                witnesses.append(witness)
            candidate_result["counterexamples"] = witnesses
        return canonical_json_bytes(result)

    def closed_replay(_request_raw: bytes, witness_raw: bytes) -> bytes:
        witness = parse_canonical_json_bytes(witness_raw, require_canonical=True)
        return canonical_json_bytes(
            {
                "authoritative": False,
                "candidate_digest": witness["candidate_digest"],
                "decision_effect": "NONE",
                "input_digest": witness["input_digest"],
                "replayed": True,
                "schema": "atlas.r3-break-this-plan-counterexample-replay/1",
                "semantics_digest": witness["semantics_digest"],
                "witness_digest": witness["witness_digest"],
            }
        )

    monkeypatch.setattr(discovery, "analyze_request_bytes", expanded_analyze)
    monkeypatch.setattr(discovery, "replay_counterexample_bytes", closed_replay)
    result_raw = campaign.analyze_campaign_bytes(raw)
    result = parse_canonical_json_bytes(result_raw, require_canonical=True)
    assert result["summary"]["counterexample_count"] == 128
    assert result["summary"]["replayed_counterexample_count"] == 128
    assert len(result["case_reports"][0]["replay_receipts"]) == 128
    _input_validator, result_validator = _schemas()
    result_validator.validate(result)

    counts[:] = [43, 43, 43]
    _error(
        "CAMPAIGN_CASE_COUNTEREXAMPLE_BOUND_EXCEEDED",
        lambda: campaign.analyze_campaign_bytes(raw),
    )


def test_cli_is_stdout_only_from_an_arbitrary_directory(tmp_path: Path) -> None:
    json_run = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--fixture"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    )
    assert json_run.returncode == 0 and json_run.stderr == b""
    assert json_run.stdout == campaign.analyze_campaign_bytes(FIXTURE.read_bytes())
    report_run = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--fixture", "--operator-report"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    )
    assert report_run.returncode == 0 and report_run.stderr == b""
    assert report_run.stdout == campaign.render_operator_report_bytes(FIXTURE.read_bytes())
    assert list(tmp_path.iterdir()) == []


def test_campaign_source_does_not_add_a_network_model_or_authority_consumer() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from cisco_toolkit import cutover_sim" not in source
    assert "from cisco_toolkit import fib" not in source
    for forbidden in (
        "transition_verifier",
        "transition_runtime_discovery",
        "transition_workload_review",
        "transition_tcb_review",
        "SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION",
        "import requests",
        "from requests",
        "urllib",
        "socket",
        "subprocess",
    ):
        assert forbidden not in source
    assert "discovery.analyze_request_bytes" in source
    assert "discovery.replay_counterexample_bytes" in source
