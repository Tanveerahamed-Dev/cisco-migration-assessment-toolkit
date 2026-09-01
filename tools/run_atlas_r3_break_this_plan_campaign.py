"""Bounded multi-case QDP-001 "Break This Plan" synthetic campaign capsule.

The capsule composes the existing single-case discovery adapter without adding a second
network model.  It evaluates every canonical synthetic case, replays every emitted witness,
and reports complete candidate, abstention, and limitation accounting.  It never ranks or
selects a candidate, collects evidence, writes a file, or changes an authority state.
"""

from __future__ import annotations

import argparse
from collections import Counter
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_PATH = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "atlas-r3-break-this-plan"
    / "campaign.synthetic.json"
)
_INPUT_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "docs"
    / "schemas"
    / "atlas-r3-break-this-plan-campaign-input-v1.schema.json"
)
_RESULT_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "docs"
    / "schemas"
    / "atlas-r3-break-this-plan-campaign-result-v1.schema.json"
)
_DISCOVERY_INPUT_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "docs"
    / "schemas"
    / "atlas-r3-break-this-plan-discovery-input-v1.schema.json"
)
_DISCOVERY_RESULT_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "docs"
    / "schemas"
    / "atlas-r3-break-this-plan-discovery-result-v1.schema.json"
)
_DISCOVERY_SOURCE_PATHS = {
    "adapter": _REPOSITORY_ROOT / "tools" / "run_atlas_r3_break_this_plan_discovery.py",
    "cutover_sim": _REPOSITORY_ROOT / "cisco_toolkit" / "cutover_sim.py",
    "discovery_input_schema": _DISCOVERY_INPUT_SCHEMA_PATH,
    "discovery_result_schema": _DISCOVERY_RESULT_SCHEMA_PATH,
    "failover": _REPOSITORY_ROOT / "cisco_toolkit" / "failover.py",
    "fib": _REPOSITORY_ROOT / "cisco_toolkit" / "fib.py",
    "textutils": _REPOSITORY_ROOT / "cisco_toolkit" / "textutils.py",
    "transition_contract": _REPOSITORY_ROOT / "cisco_toolkit" / "transition_contract.py",
    "whatif": _REPOSITORY_ROOT / "cisco_toolkit" / "whatif.py",
}
sys.path.insert(0, str(_REPOSITORY_ROOT))

from cisco_toolkit.transition_contract import (  # noqa: E402
    TransitionContractError,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)
from tools import run_atlas_r3_break_this_plan_discovery as discovery  # noqa: E402


INPUT_SCHEMA = "atlas.r3-break-this-plan-campaign-input/1"
RESULT_SCHEMA = "atlas.r3-break-this-plan-campaign-result/1"
ERROR_SCHEMA = "atlas.r3-break-this-plan-campaign-error/1"

CAMPAIGN_BANNER = "R3 SYNTHETIC CAMPAIGN — NON-AUTHORITATIVE"
CAMPAIGN_MODE = "R3_DISCOVERY_SYNTHETIC_CAMPAIGN_ONLY"
DISCOVERY_BANNER = "R3 DISCOVERY PROTOTYPE — NON-AUTHORITATIVE"
SOURCE_CLASS = "SYNTHETIC_TEST_ONLY"
TRANSLATION_STATE = "TRANSLATION_NOT_ESTABLISHED"
PRODUCT_BOUNDARY = {
    "qcp_001": {
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
    },
    "release_2": "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
    "release_3": "DISCOVERY_PLANNING_ONLY",
    "runtime": "PARTIAL_NONPORTABLE_PROTOTYPE",
}
UNRESOLVED_DEPENDENCY_IDS = tuple(f"R3-DEP-{index:03d}" for index in range(1, 12))
AUTHORITY_IDS = ("R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004")
EXPECTED_DISCOVERY_LIMIT_PROFILE = {
    "max_assumptions_per_candidate": 32,
    "max_candidates": 4,
    "max_counterexamples": 128,
    "max_input_bytes": 1_048_576,
    "max_output_bytes": 1_048_576,
    "max_requirements": 32,
    "max_step_parameters": 8,
    "max_steps_per_candidate": 16,
    "max_witness_bytes": 65_536,
    "profile_id": "ATLAS_R3_QDP001_DISCOVERY_LIMITS/1",
}
EXPECTED_R2_CLOSURE_HANDOFFS = {
    "R2-AUTH-001": {
        "evidence_collection_started": False,
        "protocol_owner": "docs/atlas-release-2-authority-candidate-protocol-2026-08-29.md",
        "selection_receipt": None,
    },
    "R2-AUTH-002": {
        "protocol_owner": "docs/atlas-release-2-authority-candidate-protocol-2026-08-29.md",
        "stage_a_plan_receipt": None,
        "stage_b_adequacy_receipt": None,
        "workload_evidence_collection_started": False,
    },
    "R2-AUTH-004": {
        "implementation_approval_receipt": None,
        "operational_designation_receipt": None,
        "profile_state": "PROPOSED_UNAPPROVED",
        "protocol_owner": "docs/atlas-release-2-authority-candidate-protocol-2026-08-29.md",
        "real_keys_or_signatures_created": False,
    },
}
ABSTENTION_REASON_CODES = frozenset(
    {"ABSTAIN_EVIDENCE_INCOMPLETE", "MODEL_CONFLICT", "NOT_EVALUABLE"}
)
LIMITATION_CODES = frozenset(
    {
        "BASELINE_EVIDENCE_INCOMPLETE",
        "BASELINE_REQUIREMENT_CONFLICT",
        "BLOCKED_FLOW_OUTSIDE_REQUIREMENT_SET",
        "BLOCKED_FLOW_SHAPE_UNSUPPORTED",
        "BLOCKED_FLOW_WITHOUT_POSITIVE_OBSERVED_DISCARD",
        "ELECTION_PROJECTION_NOT_CONTINUITY_EVIDENCE",
        "HUMAN_REQUIREMENT_UNEVALUATED",
        "L2_CONTINUITY_NOT_ASSESSED",
        "NOOP_STEP_NOT_EVALUABLE",
        "NO_COUNTEREXAMPLE_OBSERVED_IS_NOT_SUPPORT",
        "NO_POSITIVE_SUPPORT_OR_COMPLETENESS_CERTIFICATE",
        "PATH_LOSS_IS_INCONCLUSIVE",
        "SIMULATION_NOT_EVALUABLE",
        "SIMULATOR_IGNORED_STEP_PARAMETERS",
        "SYNTHETIC_MODEL_ONLY",
        "UNRESOLVED_ASSUMPTION",
    }
)
LIMITATION_EXPLANATIONS = {
    "BASELINE_EVIDENCE_INCOMPLETE": "A required baseline flow was not positively computed as reached.",
    "BASELINE_REQUIREMENT_CONFLICT": "The synthetic baseline already conflicts with a declared requirement.",
    "BLOCKED_FLOW_OUTSIDE_REQUIREMENT_SET": "A blocked flow was not one of the declared requirements.",
    "BLOCKED_FLOW_SHAPE_UNSUPPORTED": "The observed loss did not match the closed witness shape.",
    "BLOCKED_FLOW_WITHOUT_POSITIVE_OBSERVED_DISCARD": "The loss lacked a positive observed-discard basis.",
    "ELECTION_PROJECTION_NOT_CONTINUITY_EVIDENCE": "An election projection does not prove continuity or survival.",
    "HUMAN_REQUIREMENT_UNEVALUATED": "A declared human-only requirement remains unresolved.",
    "L2_CONTINUITY_NOT_ASSESSED": "Layer-2 continuity was not assessed by this synthetic model.",
    "NOOP_STEP_NOT_EVALUABLE": "A declared step produced no modeled mutation and cannot support a conclusion.",
    "NO_COUNTEREXAMPLE_OBSERVED_IS_NOT_SUPPORT": "No observed counterexample is not evidence that the candidate works.",
    "NO_POSITIVE_SUPPORT_OR_COMPLETENESS_CERTIFICATE": "The result supplies neither candidate support nor search completeness.",
    "PATH_LOSS_IS_INCONCLUSIVE": "Path disappearance without a positive discard observation is inconclusive.",
    "SIMULATION_NOT_EVALUABLE": "The simulator could not evaluate the complete declared candidate.",
    "SIMULATOR_IGNORED_STEP_PARAMETERS": "At least one step parameter was not consumed by the simulator.",
    "SYNTHETIC_MODEL_ONLY": "The result is synthetic and is not field or workload evidence.",
    "UNRESOLVED_ASSUMPTION": "A candidate assumption remains explicitly unresolved.",
}
ABSTENTION_EXPLANATIONS = {
    "ABSTAIN_EVIDENCE_INCOMPLETE": "Required evidence or assumptions remain incomplete.",
    "MODEL_CONFLICT": "The synthetic baseline conflicts with the declared requirement.",
    "NOT_EVALUABLE": "The complete candidate could not be evaluated as declared.",
}
_FORBIDDEN_IDENTIFIER_TOKENS = frozenset(
    {
        "approval",
        "approved",
        "authoritative",
        "authority",
        "best",
        "eligible",
        "feasible",
        "gate",
        "go",
        "pass",
        "promote",
        "promotion",
        "qualification",
        "qualified",
        "rank",
        "readiness",
        "ready",
        "safe",
        "score",
        "select",
        "selected",
        "winner",
    }
)

MAX_CASES = 8
MAX_INPUT_BYTES = 9_437_184
MAX_OUTPUT_BYTES = 8_388_608
MAX_OPERATOR_REPORT_BYTES = 1_048_576
MAX_COUNTEREXAMPLES_PER_CASE = 128
MAX_COUNTEREXAMPLES_PER_CAMPAIGN = MAX_CASES * MAX_COUNTEREXAMPLES_PER_CASE
LIMIT_PROFILE = {
    "max_campaign_input_bytes": MAX_INPUT_BYTES,
    "max_campaign_output_bytes": MAX_OUTPUT_BYTES,
    "max_cases": MAX_CASES,
    "max_counterexamples_per_campaign": MAX_COUNTEREXAMPLES_PER_CAMPAIGN,
    "max_counterexamples_per_case": MAX_COUNTEREXAMPLES_PER_CASE,
    "max_operator_report_bytes": MAX_OPERATOR_REPORT_BYTES,
    "nested_discovery_limit_profile": EXPECTED_DISCOVERY_LIMIT_PROFILE,
    "profile_id": "ATLAS_R3_QDP001_SYNTHETIC_CAMPAIGN_LIMITS/1",
}

GLOBAL_LIMITATIONS = [
    "DISCOVERY_PLANNING_ONLY",
    "NO_CANDIDATE_RANKING_OR_SELECTION",
    "NO_EXTERNAL_OBSERVATION_AUTHORIZED",
    "NO_POSITIVE_FEASIBILITY_OR_COMPLETENESS_CERTIFICATE",
    "NO_QDP_TO_QCP_TRANSLATION",
    "SYNTHETIC_TEST_ONLY",
    "CAMPAIGN_AGGREGATION_DOES_NOT_ADD_EVIDENCE",
    "REPLAY_IS_SYNTHETIC_REPRODUCTION_ONLY",
]
OPERATOR_INTERPRETATION = {
    "abstention": "NO_SUPPORT_OR_SAFETY_INFERENCE",
    "campaign": "NO_RANKING_SELECTION_FEASIBILITY_OR_COMPLETENESS",
    "counterexample": "REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY",
    "limitations": "RETAIN_WITH_EACH_CANDIDATE",
}

_INPUT_KEYS = frozenset(
    {
        "schema",
        "campaign_id",
        "prototype_mode",
        "source_class",
        "product_boundary",
        "unresolved_dependency_ids",
        "authority_placeholders",
        "cases",
    }
)
_DISCOVERY_RESULT_KEYS = frozenset(
    {
        "authoritative",
        "authoritative_gate",
        "authority_placeholders",
        "banner",
        "baseline_projection_digest",
        "candidate_results",
        "candidate_set_digest",
        "case_id",
        "decision_effect",
        "feasibility_verdict",
        "global_limitations",
        "input_digest",
        "limit_profile",
        "next_evidence_requests",
        "next_observation",
        "preview_eligible",
        "product_boundary",
        "product_boundary_digest",
        "promotion_eligible",
        "qualification_state",
        "r2_closure_handoffs",
        "requirements_digest",
        "schema",
        "selected_candidate",
        "semantics_digest",
        "translation_checked",
        "translation_state",
        "unresolved_dependency_ids",
    }
)
_CANDIDATE_RESULT_KEYS = frozenset(
    {
        "candidate_digest",
        "candidate_id",
        "checked_flow_requirements",
        "checked_steps",
        "counterexamples",
        "limitations",
        "reason_code",
        "result_kind",
        "simulation_projection_digest",
    }
)
_WITNESS_KEYS = frozenset(
    {
        "candidate_digest",
        "candidate_id",
        "candidate_set_digest",
        "case_id",
        "input_digest",
        "observation_digest",
        "product_boundary_digest",
        "reason_code",
        "requirement_id",
        "requirements_digest",
        "schema",
        "semantics_digest",
        "step_id",
        "step_index",
        "witness_digest",
    }
)
_REPLAY_RECEIPT_KEYS = frozenset(
    {
        "authoritative",
        "candidate_digest",
        "decision_effect",
        "input_digest",
        "replayed",
        "schema",
        "semantics_digest",
        "witness_digest",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}$")
_CAMPAIGN_ID = re.compile(r"^qdp001-campaign:[a-z0-9][a-z0-9._:/+@-]{0,110}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class BreakThisPlanCampaignError(ValueError):
    """Stable, non-echoing campaign refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _CampaignArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        _reject("CLI_ARGUMENTS_INVALID")


def _reject(code: str) -> None:
    raise BreakThisPlanCampaignError(code)


def _exact_object(value: Any, keys: frozenset[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        _reject(code)
    return value


def _lexical_tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", expanded)
    return {part for part in re.split(r"[^a-z0-9]+", expanded.casefold()) if part}


def _identifier(value: Any, code: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        _reject(code)
    if _lexical_tokens(value) & _FORBIDDEN_IDENTIFIER_TOKENS:
        _reject(code)
    return value


def _namespaced_identifier(value: Any, prefix: str, code: str) -> str:
    checked = _identifier(value, code)
    if checked != checked.casefold() or not checked.startswith(prefix) or len(checked) == len(prefix):
        _reject(code)
    return checked


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        _reject(code)
    return value


def _validate_campaign_id(value: Any) -> str:
    if type(value) is not str or not _CAMPAIGN_ID.fullmatch(value):
        _reject("CAMPAIGN_ID_INVALID")
    return _identifier(value, "CAMPAIGN_ID_INVALID")


def _validate_input(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _INPUT_KEYS, "CAMPAIGN_INPUT_SCHEMA_INVALID")
    if obj["schema"] != INPUT_SCHEMA:
        _reject("CAMPAIGN_INPUT_SCHEMA_INVALID")
    if obj["prototype_mode"] != CAMPAIGN_MODE or obj["source_class"] != SOURCE_CLASS:
        _reject("SYNTHETIC_CAMPAIGN_BOUNDARY_REQUIRED")
    campaign_id = _validate_campaign_id(obj["campaign_id"])
    if obj["product_boundary"] != PRODUCT_BOUNDARY:
        _reject("PRODUCT_BOUNDARY_DRIFT")
    if obj["unresolved_dependency_ids"] != list(UNRESOLVED_DEPENDENCY_IDS):
        _reject("DEPENDENCY_BOUNDARY_INVALID")
    placeholders = obj["authority_placeholders"]
    if type(placeholders) is not dict or list(placeholders) != list(AUTHORITY_IDS):
        _reject("AUTHORITY_PLACEHOLDERS_INVALID")
    if any(placeholders[item] is not None for item in AUTHORITY_IDS):
        _reject("AUTHORITY_VALUES_FORBIDDEN")
    cases = obj["cases"]
    if type(cases) is not list or not cases or len(cases) > MAX_CASES:
        _reject("CAMPAIGN_CASES_INVALID")
    checked_cases: list[dict[str, Any]] = []
    case_ids: list[str] = []
    for case in cases:
        if type(case) is not dict:
            _reject("CAMPAIGN_CASE_INVALID")
        case_id = case.get("case_id")
        if type(case_id) is not str:
            _reject("CAMPAIGN_CASE_INVALID")
        _namespaced_identifier(case_id, "qdp001-fixture:", "CAMPAIGN_CASE_INVALID")
        checked_cases.append(case)
        case_ids.append(case_id)
    if case_ids != sorted(set(case_ids)):
        _reject("CAMPAIGN_CASES_NOT_SORTED_UNIQUE")
    return {
        "authority_placeholders": {item: None for item in AUTHORITY_IDS},
        "campaign_id": campaign_id,
        "cases": checked_cases,
        "product_boundary": PRODUCT_BOUNDARY,
        "prototype_mode": CAMPAIGN_MODE,
        "schema": INPUT_SCHEMA,
        "source_class": SOURCE_CLASS,
        "unresolved_dependency_ids": list(UNRESOLVED_DEPENDENCY_IDS),
    }


def _source_digest(path: Path, code: str) -> str:
    try:
        return bytes_digest(path.resolve().read_bytes())
    except OSError:
        _reject(code)


def _expected_discovery_semantics_digest() -> str:
    if (
        discovery.SOURCE_CLASS != SOURCE_CLASS
        or discovery.PROTOTYPE_BANNER != DISCOVERY_BANNER
        or discovery.TRANSLATION_STATE != TRANSLATION_STATE
        or discovery.PRODUCT_BOUNDARY != PRODUCT_BOUNDARY
        or tuple(discovery.UNRESOLVED_DEPENDENCY_IDS) != UNRESOLVED_DEPENDENCY_IDS
        or tuple(discovery.AUTHORITY_IDS) != AUTHORITY_IDS
        or discovery.LIMIT_PROFILE != EXPECTED_DISCOVERY_LIMIT_PROFILE
        or discovery.ABSTENTION_REASON_CODES != ABSTENTION_REASON_CODES
        or discovery.LIMITATION_CODES != LIMITATION_CODES
    ):
        _reject("DISCOVERY_CONTRACT_CONSTANT_DRIFT")
    source_digests = {
        source_id: _source_digest(path, "DISCOVERY_SEMANTIC_SOURCE_UNREADABLE")
        for source_id, path in _DISCOVERY_SOURCE_PATHS.items()
    }
    expected = canonical_digest(
        {
            "counterexample_projection": "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW/1",
            "limit_profile_digest": canonical_digest(EXPECTED_DISCOVERY_LIMIT_PROFILE),
            "python_implementation": platform.python_implementation().casefold(),
            "python_version": (
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            ),
            "semantic_dependency_profile": "ATLAS_R3_QDP001_DISCOVERY_SEMANTICS/2",
            "simulator_contract": "cutover_sim/1",
            "source_digests": source_digests,
        }
    )
    try:
        actual = discovery._semantics_digest()
    except (discovery.BreakThisPlanDiscoveryError, OSError, TypeError, ValueError):
        _reject("DISCOVERY_SEMANTICS_UNAVAILABLE")
    if actual != expected:
        _reject("DISCOVERY_SEMANTICS_IMPLEMENTATION_DRIFT")
    return expected


def _campaign_semantics_digest(discovery_semantics_digests: list[str]) -> str:
    return canonical_digest(
        {
            "campaign_input_schema_digest": _source_digest(
                _INPUT_SCHEMA_PATH, "CAMPAIGN_INPUT_SCHEMA_UNREADABLE"
            ),
            "campaign_output_schema_digest": _source_digest(
                _RESULT_SCHEMA_PATH, "CAMPAIGN_RESULT_SCHEMA_UNREADABLE"
            ),
            "campaign_source_digest": _source_digest(
                Path(__file__), "CAMPAIGN_SOURCE_UNREADABLE"
            ),
            "discovery_semantics_digests": discovery_semantics_digests,
            "limit_profile_digest": canonical_digest(LIMIT_PROFILE),
            "operator_projection": "COMPLETE_CANDIDATE_ABSTENTION_LIMITATION_REPLAY/1",
        }
    )


def _count_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"code": code, "count": counter[code]} for code in sorted(counter)]


def _validate_witness(
    witness: Any,
    *,
    candidate_result: dict[str, Any],
    input_candidate: dict[str, Any],
    case: dict[str, Any],
    result: dict[str, Any],
    expected_semantics: str,
) -> dict[str, Any]:
    obj = _exact_object(witness, _WITNESS_KEYS, "CAMPAIGN_WITNESS_INVALID")
    if (
        obj["schema"] != "atlas.r3-break-this-plan-counterexample/1"
        or obj["reason_code"] != "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
        or obj["candidate_id"] != input_candidate["candidate_id"]
        or obj["candidate_digest"] != candidate_result["candidate_digest"]
        or obj["candidate_set_digest"] != result["candidate_set_digest"]
        or obj["case_id"] != case["case_id"]
        or obj["input_digest"] != result["input_digest"]
        or obj["product_boundary_digest"] != result["product_boundary_digest"]
        or obj["requirements_digest"] != result["requirements_digest"]
        or obj["semantics_digest"] != expected_semantics
    ):
        _reject("CAMPAIGN_WITNESS_BINDING_INVALID")
    for key in (
        "candidate_digest",
        "candidate_set_digest",
        "input_digest",
        "observation_digest",
        "product_boundary_digest",
        "requirements_digest",
        "semantics_digest",
        "witness_digest",
    ):
        _digest(obj[key], "CAMPAIGN_WITNESS_DIGEST_INVALID")
    step_index = obj["step_index"]
    if (
        type(step_index) is not int
        or type(step_index) is bool
        or step_index < 0
        or step_index >= len(input_candidate["steps"])
        or obj["step_id"] != input_candidate["steps"][step_index]["step_id"]
    ):
        _reject("CAMPAIGN_WITNESS_STEP_INVALID")
    flow_requirement_ids = {
        item["requirement_id"]
        for item in case["requirements"]
        if item["kind"] == "PRESERVE_SYNTHETIC_FLOW"
    }
    if obj["requirement_id"] not in flow_requirement_ids:
        _reject("CAMPAIGN_WITNESS_REQUIREMENT_INVALID")
    body = {key: value for key, value in obj.items() if key != "witness_digest"}
    if obj["witness_digest"] != canonical_digest(body):
        _reject("CAMPAIGN_WITNESS_DIGEST_MISMATCH")
    return obj


def _validate_replay_receipt(
    replay: Any,
    *,
    witness: dict[str, Any],
    candidate_result: dict[str, Any],
    result: dict[str, Any],
    expected_semantics: str,
) -> dict[str, Any]:
    obj = _exact_object(replay, _REPLAY_RECEIPT_KEYS, "CAMPAIGN_REPLAY_RECEIPT_INVALID")
    if (
        obj["authoritative"] is not False
        or obj["decision_effect"] != "NONE"
        or obj["replayed"] is not True
        or obj["schema"] != "atlas.r3-break-this-plan-counterexample-replay/1"
        or obj["candidate_digest"] != candidate_result["candidate_digest"]
        or obj["input_digest"] != result["input_digest"]
        or obj["semantics_digest"] != expected_semantics
        or obj["witness_digest"] != witness["witness_digest"]
    ):
        _reject("CAMPAIGN_REPLAY_RECEIPT_BINDING_INVALID")
    for key in ("candidate_digest", "input_digest", "semantics_digest", "witness_digest"):
        _digest(obj[key], "CAMPAIGN_REPLAY_RECEIPT_DIGEST_INVALID")
    return obj


def _validate_child_result_boundary(
    result: Any,
    *,
    case: dict[str, Any],
    case_raw: bytes,
    expected_semantics: str,
) -> dict[str, Any]:
    obj = _exact_object(result, _DISCOVERY_RESULT_KEYS, "CAMPAIGN_CASE_RESULT_INVALID")
    fixed = {
        "authoritative": False,
        "authoritative_gate": None,
        "banner": DISCOVERY_BANNER,
        "decision_effect": "NONE",
        "feasibility_verdict": None,
        "limit_profile": EXPECTED_DISCOVERY_LIMIT_PROFILE,
        "next_observation": None,
        "preview_eligible": False,
        "promotion_eligible": False,
        "qualification_state": "EXPERIMENTAL",
        "schema": "atlas.r3-break-this-plan-discovery-result/1",
        "selected_candidate": None,
        "translation_checked": False,
        "translation_state": TRANSLATION_STATE,
    }
    if any(obj[key] != expected for key, expected in fixed.items()):
        _reject("CAMPAIGN_CASE_NONPROMOTION_BOUNDARY_DRIFT")
    if obj["case_id"] != case["case_id"] or obj["input_digest"] != bytes_digest(case_raw):
        _reject("CAMPAIGN_CASE_INPUT_BINDING_INVALID")
    if (
        obj["product_boundary"] != PRODUCT_BOUNDARY
        or obj["product_boundary_digest"] != canonical_digest(PRODUCT_BOUNDARY)
    ):
        _reject("CAMPAIGN_CASE_PRODUCT_BOUNDARY_DRIFT")
    if obj["authority_placeholders"] != {item: None for item in AUTHORITY_IDS}:
        _reject("CAMPAIGN_CASE_AUTHORITY_DRIFT")
    if obj["unresolved_dependency_ids"] != list(UNRESOLVED_DEPENDENCY_IDS):
        _reject("CAMPAIGN_CASE_DEPENDENCY_DRIFT")
    if obj["global_limitations"] != GLOBAL_LIMITATIONS[:6]:
        _reject("CAMPAIGN_CASE_LIMITATION_BOUNDARY_DRIFT")
    if obj["r2_closure_handoffs"] != EXPECTED_R2_CLOSURE_HANDOFFS:
        _reject("CAMPAIGN_CASE_HANDOFF_DRIFT")
    if obj["candidate_set_digest"] != canonical_digest(case["candidates"]):
        _reject("CAMPAIGN_CANDIDATE_SET_BINDING_INVALID")
    if obj["requirements_digest"] != canonical_digest(case["requirements"]):
        _reject("CAMPAIGN_REQUIREMENTS_BINDING_INVALID")
    if obj["semantics_digest"] != expected_semantics:
        _reject("CAMPAIGN_CASE_SEMANTICS_INVALID")
    for key in (
        "baseline_projection_digest",
        "candidate_set_digest",
        "input_digest",
        "product_boundary_digest",
        "requirements_digest",
        "semantics_digest",
    ):
        _digest(obj[key], "CAMPAIGN_CASE_DIGEST_INVALID")

    evidence_requests = obj["next_evidence_requests"]
    if (
        type(evidence_requests) is not list
        or evidence_requests != sorted(set(evidence_requests))
        or any(type(item) is not str for item in evidence_requests)
    ):
        _reject("CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")
    try:
        recomputed = discovery._analyze(  # noqa: SLF001
            case, input_digest=bytes_digest(case_raw)
        )
    except (
        discovery.BreakThisPlanDiscoveryError,
        OSError,
        TransitionContractError,
        KeyError,
        TypeError,
        ValueError,
    ):
        _reject("CAMPAIGN_CASE_RECOMPUTATION_FAILED")
    if type(recomputed) is not dict:
        _reject("CAMPAIGN_CASE_RECOMPUTATION_FAILED")
    for item in evidence_requests:
        _identifier(item, "CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")
    if evidence_requests != recomputed.get("next_evidence_requests"):
        _reject("CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")

    candidate_results = obj["candidate_results"]
    if type(candidate_results) is not list or len(candidate_results) != len(case["candidates"]):
        _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
    flow_requirement_count = sum(
        1 for item in case["requirements"] if item["kind"] == "PRESERVE_SYNTHETIC_FLOW"
    )
    expected_candidate_ids = [item["candidate_id"] for item in case["candidates"]]
    if [item.get("candidate_id") for item in candidate_results if type(item) is dict] != (
        expected_candidate_ids
    ):
        _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
    for row_value, input_candidate in zip(
        candidate_results, case["candidates"], strict=True
    ):
        row = _exact_object(
            row_value,
            _CANDIDATE_RESULT_KEYS,
            "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID",
        )
        _namespaced_identifier(
            row["candidate_id"], "candidate.", "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID"
        )
        if row["candidate_digest"] != canonical_digest(input_candidate):
            _reject("CAMPAIGN_CANDIDATE_BINDING_INVALID")
        for key in ("candidate_digest", "simulation_projection_digest"):
            _digest(row[key], "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
        if (
            type(row["checked_flow_requirements"]) is not int
            or type(row["checked_flow_requirements"]) is bool
            or row["checked_flow_requirements"] != flow_requirement_count
            or type(row["checked_steps"]) is not int
            or type(row["checked_steps"]) is bool
            or not 0 <= row["checked_steps"] <= len(input_candidate["steps"])
            or row["checked_steps"] > EXPECTED_DISCOVERY_LIMIT_PROFILE["max_steps_per_candidate"]
        ):
            _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
        limitations = row["limitations"]
        if (
            type(limitations) is not list
            or not 2 <= len(limitations) <= len(LIMITATION_CODES)
            or limitations != sorted(set(limitations))
            or any(item not in LIMITATION_CODES for item in limitations)
        ):
            _reject("CAMPAIGN_LIMITATION_ACCOUNTING_INVALID")
        mandatory_limitations = {
            "NO_POSITIVE_SUPPORT_OR_COMPLETENESS_CERTIFICATE",
            "SYNTHETIC_MODEL_ONLY",
        }
        if any(item["state"] == "UNRESOLVED" for item in input_candidate["assumptions"]):
            mandatory_limitations.add("UNRESOLVED_ASSUMPTION")
        if any(
            item["kind"] == "HUMAN_ONLY_UNEVALUATED"
            for item in case["requirements"]
        ):
            mandatory_limitations.add("HUMAN_REQUIREMENT_UNEVALUATED")
        if not mandatory_limitations <= set(limitations):
            _reject("CAMPAIGN_MANDATORY_LIMITATION_MISSING")
        witnesses = row["counterexamples"]
        if (
            type(witnesses) is not list
            or len(witnesses) > EXPECTED_DISCOVERY_LIMIT_PROFILE["max_counterexamples"]
        ):
            _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
        if row["result_kind"] == "COUNTEREXAMPLE":
            if (
                row["reason_code"] != "REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
                or not witnesses
            ):
                _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
        elif (
            row["result_kind"] != "ABSTENTION"
            or row["reason_code"] not in ABSTENTION_REASON_CODES
            or witnesses
        ):
            _reject("CAMPAIGN_ABSTENTION_ACCOUNTING_INVALID")
        checked_witnesses = [
            _validate_witness(
                witness,
                candidate_result=row,
                input_candidate=input_candidate,
                case=case,
                result=obj,
                expected_semantics=expected_semantics,
            )
            for witness in witnesses
        ]
        witness_digests = [item["witness_digest"] for item in checked_witnesses]
        if len(witness_digests) != len(set(witness_digests)):
            _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
    if obj != recomputed:
        _reject("CAMPAIGN_CASE_RECOMPUTATION_MISMATCH")
    return obj


def _analyze(value: dict[str, Any], *, input_digest: str) -> dict[str, Any]:
    expected_discovery_semantics = _expected_discovery_semantics_digest()
    case_reports: list[dict[str, Any]] = []
    case_bindings: list[dict[str, str]] = []
    limitation_counts: Counter[str] = Counter()
    abstention_reason_counts: Counter[str] = Counter()
    next_evidence_requests: set[str] = set()
    discovery_semantics: set[str] = set()
    candidate_count = 0
    abstention_candidate_count = 0
    counterexample_candidate_count = 0
    counterexample_count = 0
    replayed_counterexample_count = 0

    for case in value["cases"]:
        case_raw = canonical_json_bytes(case)
        try:
            result_raw = discovery.analyze_request_bytes(case_raw)
            result = _validate_child_result_boundary(
                parse_canonical_json_bytes(result_raw, require_canonical=True),
                case=case,
                case_raw=case_raw,
                expected_semantics=expected_discovery_semantics,
            )
        except BreakThisPlanCampaignError:
            raise
        except (
            discovery.BreakThisPlanDiscoveryError,
            TransitionContractError,
            TypeError,
            ValueError,
            KeyError,
        ):
            _reject("CAMPAIGN_CASE_REANALYSIS_FAILED")
        discovery_semantics.add(result["semantics_digest"])
        next_evidence_requests.update(result["next_evidence_requests"])

        replay_receipts: list[dict[str, Any]] = []
        case_candidate_count = 0
        case_abstentions = 0
        case_counterexample_candidates = 0
        case_counterexamples = 0
        case_replays = 0
        candidate_results = result.get("candidate_results")
        if type(candidate_results) is not list or not candidate_results:
            _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
        for candidate_result in candidate_results:
            case_candidate_count += 1
            candidate_count += 1
            kind = candidate_result.get("result_kind")
            reason = candidate_result.get("reason_code")
            if kind == "ABSTENTION":
                case_abstentions += 1
                abstention_candidate_count += 1
                if type(reason) is not str:
                    _reject("CAMPAIGN_ABSTENTION_ACCOUNTING_INVALID")
                abstention_reason_counts[reason] += 1
            elif kind == "COUNTEREXAMPLE":
                case_counterexample_candidates += 1
                counterexample_candidate_count += 1
            else:
                _reject("CAMPAIGN_RESULT_KIND_INVALID")
            limitations = candidate_result.get("limitations")
            if type(limitations) is not list:
                _reject("CAMPAIGN_LIMITATION_ACCOUNTING_INVALID")
            for limitation in limitations:
                if type(limitation) is not str:
                    _reject("CAMPAIGN_LIMITATION_ACCOUNTING_INVALID")
                limitation_counts[limitation] += 1
            witnesses = candidate_result.get("counterexamples")
            if type(witnesses) is not list:
                _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
            if case_counterexamples + len(witnesses) > MAX_COUNTEREXAMPLES_PER_CASE:
                _reject("CAMPAIGN_CASE_COUNTEREXAMPLE_BOUND_EXCEEDED")
            case_counterexamples += len(witnesses)
            counterexample_count += len(witnesses)
            if counterexample_count > MAX_COUNTEREXAMPLES_PER_CAMPAIGN:
                _reject("CAMPAIGN_COUNTEREXAMPLE_BOUND_EXCEEDED")
            for witness in witnesses:
                try:
                    witness_raw = canonical_json_bytes(witness)
                    replay_raw = discovery.replay_counterexample_bytes(case_raw, witness_raw)
                    replay = _validate_replay_receipt(
                        parse_canonical_json_bytes(replay_raw, require_canonical=True),
                        witness=witness,
                        candidate_result=candidate_result,
                        result=result,
                        expected_semantics=expected_discovery_semantics,
                    )
                except BreakThisPlanCampaignError:
                    raise
                except (
                    discovery.BreakThisPlanDiscoveryError,
                    TransitionContractError,
                    TypeError,
                    ValueError,
                    KeyError,
                ):
                    _reject("CAMPAIGN_COUNTEREXAMPLE_REPLAY_FAILED")
                replay_receipts.append(
                    {
                        "replay_receipt": replay,
                        "replay_receipt_digest": bytes_digest(replay_raw),
                    }
                )
                case_replays += 1
                replayed_counterexample_count += 1
        if case_counterexamples != case_replays:
            _reject("CAMPAIGN_REPLAY_ACCOUNTING_INVALID")

        case_summary = {
            "abstention_candidate_count": case_abstentions,
            "candidate_count": case_candidate_count,
            "counterexample_candidate_count": case_counterexample_candidates,
            "counterexample_count": case_counterexamples,
            "replayed_counterexample_count": case_replays,
        }
        report = {
            "case_id": result["case_id"],
            "case_summary": case_summary,
            "discovery_result": result,
            "discovery_result_digest": bytes_digest(result_raw),
            "input_digest": bytes_digest(case_raw),
            "replay_receipts": replay_receipts,
        }
        case_reports.append(report)
        case_bindings.append(
            {
                "case_id": result["case_id"],
                "discovery_result_digest": bytes_digest(result_raw),
                "input_digest": bytes_digest(case_raw),
            }
        )

    if replayed_counterexample_count != counterexample_count:
        _reject("CAMPAIGN_TOTAL_ACCOUNTING_INVALID")
    case_set_digest = canonical_digest(case_bindings)
    for case_report in case_reports:
        for replay_envelope in case_report["replay_receipts"]:
            replay_envelope["campaign_replay_binding_digest"] = canonical_digest(
                {
                    "campaign_id": value["campaign_id"],
                    "campaign_input_digest": input_digest,
                    "case_set_digest": case_set_digest,
                    "replay_receipt_digest": replay_envelope["replay_receipt_digest"],
                }
            )
    discovery_semantics_digests = sorted(discovery_semantics)
    if discovery_semantics_digests != [expected_discovery_semantics]:
        _reject("CAMPAIGN_DISCOVERY_SEMANTICS_DRIFT")
    summary = {
        "abstention_candidate_count": abstention_candidate_count,
        "candidate_count": candidate_count,
        "case_count": len(case_reports),
        "counterexample_candidate_count": counterexample_candidate_count,
        "counterexample_count": counterexample_count,
        "replay_failure_count": 0,
        "replayed_counterexample_count": replayed_counterexample_count,
    }
    return {
        "abstention_reason_counts": _count_rows(abstention_reason_counts),
        "authoritative": False,
        "authoritative_gate": None,
        "authority_placeholders": value["authority_placeholders"],
        "banner": CAMPAIGN_BANNER,
        "campaign_id": value["campaign_id"],
        "campaign_input_digest": input_digest,
        "campaign_semantics_digest": _campaign_semantics_digest(
            discovery_semantics_digests
        ),
        "case_reports": case_reports,
        "case_set_digest": case_set_digest,
        "decision_effect": "NONE",
        "discovery_semantics_digests": discovery_semantics_digests,
        "feasibility_verdict": None,
        "global_limitations": GLOBAL_LIMITATIONS,
        "limit_profile": LIMIT_PROFILE,
        "limitation_counts": _count_rows(limitation_counts),
        "next_evidence_requests": sorted(next_evidence_requests),
        "next_observation": None,
        "operator_interpretation": OPERATOR_INTERPRETATION,
        "preview_eligible": False,
        "product_boundary": value["product_boundary"],
        "promotion_eligible": False,
        "qualification_state": "EXPERIMENTAL",
        "r2_closure_handoffs": EXPECTED_R2_CLOSURE_HANDOFFS,
        "schema": RESULT_SCHEMA,
        "selected_candidate": None,
        "summary": summary,
        "translation_checked": False,
        "translation_state": TRANSLATION_STATE,
        "unresolved_dependency_ids": value["unresolved_dependency_ids"],
    }


def analyze_campaign_bytes(raw: bytes) -> bytes:
    """Validate one exact canonical campaign and return exact canonical result bytes."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_INPUT_BYTES:
        _reject("CAMPAIGN_INPUT_BYTE_LIMIT")
    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
    except (TransitionContractError, TypeError, ValueError):
        _reject("CAMPAIGN_INPUT_CANONICAL_INVALID")
    checked = _validate_input(value)
    result = _analyze(checked, input_digest=bytes_digest(raw))
    try:
        encoded = canonical_json_bytes(result)
    except (TransitionContractError, TypeError, ValueError):
        _reject("CAMPAIGN_RESULT_CANONICAL_INVALID")
    if len(encoded) > MAX_OUTPUT_BYTES:
        _reject("CAMPAIGN_OUTPUT_BYTE_LIMIT")
    return encoded


def render_operator_report_bytes(raw: bytes) -> bytes:
    """Render a deterministic human-readable projection from a freshly analyzed campaign."""

    result_raw = analyze_campaign_bytes(raw)
    try:
        result = parse_canonical_json_bytes(result_raw, require_canonical=True)
    except TransitionContractError:
        _reject("CAMPAIGN_RESULT_CANONICAL_INVALID")
    summary = result["summary"]
    boundary = result["product_boundary"]
    lines = [
        "# Atlas R3 Break This Plan — Synthetic Campaign Report",
        "",
        result["banner"],
        "",
        f"- Campaign: `{result['campaign_id']}`",
        f"- Release 2: `{boundary['release_2']}`",
        (
            "- QCP-001: "
            f"`{boundary['qcp_001']['qualification_state']}` / "
            f"`{boundary['qcp_001']['execution_state']}`"
        ),
        f"- Runtime: `{boundary['runtime']}`",
        f"- Release 3: `{boundary['release_3']}`",
        "- Decision effect: `NONE`; no candidate is ranked or selected.",
        "",
        "## Campaign accounting",
        "",
        f"- Cases analyzed: {summary['case_count']}",
        f"- Candidates accounted for: {summary['candidate_count']}",
        f"- Counterexample candidates: {summary['counterexample_candidate_count']}",
        f"- Abstention candidates: {summary['abstention_candidate_count']}",
        (
            "- Emitted/replayed counterexamples: "
            f"{summary['counterexample_count']}/{summary['replayed_counterexample_count']}"
        ),
        "",
        "A counterexample means only that the same synthetic observed-discard witness replayed. "
        "An abstention is never candidate support or a safety inference.",
        "",
        "## Case and candidate results",
        "",
    ]
    for case_report in result["case_reports"]:
        case_result = case_report["discovery_result"]
        witness_by_digest = {
            witness["witness_digest"]: witness
            for candidate in case_result["candidate_results"]
            for witness in candidate["counterexamples"]
        }
        replay_by_candidate = Counter(
            row["replay_receipt"]["candidate_digest"]
            for row in case_report["replay_receipts"]
        )
        lines.extend(
            [
                f"### `{case_report['case_id']}`",
                "",
                "| Candidate | Result | Reason | Steps | Replays | Limitations |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for candidate in case_result["candidate_results"]:
            limitations = "; ".join(candidate["limitations"])
            replay_count = replay_by_candidate[candidate["candidate_digest"]]
            lines.append(
                "| "
                f"`{candidate['candidate_id']}` | `{candidate['result_kind']}` | "
                f"`{candidate['reason_code']}` | {candidate['checked_steps']} | "
                f"{replay_count} | {limitations} |"
            )
        lines.extend(["", "**Next evidence requests**"])
        if case_result["next_evidence_requests"]:
            lines.append(
                ", ".join(
                    f"`{item}`" for item in case_result["next_evidence_requests"]
                )
            )
        else:
            lines.append("None emitted; this is not candidate support or evidence completeness.")
        lines.extend(["", "**Replayed witnesses**"])
        if case_report["replay_receipts"]:
            for envelope in case_report["replay_receipts"]:
                receipt = envelope["replay_receipt"]
                witness = witness_by_digest[receipt["witness_digest"]]
                lines.append(
                    "- Candidate "
                    f"`{witness['candidate_id']}` · step `{witness['step_id']}` · requirement "
                    f"`{witness['requirement_id']}` · witness `{witness['witness_digest']}` · "
                    "campaign replay binding "
                    f"`{envelope['campaign_replay_binding_digest']}`"
                )
        else:
            lines.append("None; no counterexample replay was accepted for this case.")
        lines.append("")

    lines.extend(["## Observed limitation frequency", ""])
    if result["limitation_counts"]:
        lines.extend(
            f"- `{row['code']}`: {row['count']} candidate(s) — "
            f"{LIMITATION_EXPLANATIONS[row['code']]}"
            for row in result["limitation_counts"]
        )
    else:
        lines.append("- No limitation code was emitted; this is not a positive certificate.")
    lines.extend(["", "## Abstention reason frequency", ""])
    if result["abstention_reason_counts"]:
        lines.extend(
            f"- `{row['code']}`: {row['count']} candidate(s) — "
            f"{ABSTENTION_EXPLANATIONS[row['code']]}"
            for row in result["abstention_reason_counts"]
        )
    else:
        lines.append("- No abstention was emitted; this is not candidate support.")

    handoffs = result["r2_closure_handoffs"]
    lines.extend(
        [
            "",
            "## Unresolved Release 2 handoffs",
            "",
            (
                "- `R2-AUTH-001`: selection receipt is `null`; evidence collection "
                f"started = `{str(handoffs['R2-AUTH-001']['evidence_collection_started']).lower()}`."
            ),
            (
                "- `R2-AUTH-002`: Stage A plan and Stage B adequacy receipts are `null`; "
                "workload collection started = "
                f"`{str(handoffs['R2-AUTH-002']['workload_evidence_collection_started']).lower()}`."
            ),
            (
                "- `R2-AUTH-004`: profile remains "
                f"`{handoffs['R2-AUTH-004']['profile_state']}`; implementation and operational "
                "receipts are `null`; real keys/signatures created = "
                f"`{str(handoffs['R2-AUTH-004']['real_keys_or_signatures_created']).lower()}`."
            ),
            "",
            "These placeholders require a future authenticated external update. This campaign "
            "does not fill them or authorize runtime/workload collection.",
            "",
        ]
    )
    encoded = "\n".join(lines).encode("utf-8")
    if len(encoded) > MAX_OPERATOR_REPORT_BYTES:
        _reject("OPERATOR_REPORT_BYTE_LIMIT")
    return encoded


def _error_bytes(code: str) -> bytes:
    return canonical_json_bytes(
        {
            "authoritative": False,
            "decision_effect": "NONE",
            "error": {"code": code},
            "schema": ERROR_SCHEMA,
        }
    )


def _is_reparse_or_symlink(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _bounded_fixture_bytes() -> bytes:
    """Read only the tracked campaign fixture through one bounded regular-file handle."""

    try:
        relative = _FIXTURE_PATH.relative_to(_REPOSITORY_ROOT)
        current = _REPOSITORY_ROOT
        for part in relative.parts:
            current = current / part
            if _is_reparse_or_symlink(os.lstat(current)):
                _reject("CAMPAIGN_FIXTURE_REPARSE_FORBIDDEN")
        with _FIXTURE_PATH.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                _reject("CAMPAIGN_FIXTURE_REGULAR_FILE_REQUIRED")
            chunks: list[bytes] = []
            remaining = MAX_INPUT_BYTES + 1
            while remaining:
                chunk = handle.read(remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_INPUT_BYTES or handle.read(1):
                _reject("CAMPAIGN_INPUT_BYTE_LIMIT")
            after = os.fstat(handle.fileno())
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after or len(raw) != after.st_size:
            _reject("CAMPAIGN_FIXTURE_CHANGED_DURING_READ")
        return raw
    except BreakThisPlanCampaignError:
        raise
    except (OSError, ValueError):
        _reject("CAMPAIGN_FIXTURE_READ_FAILED")


def _bounded_stdin_bytes() -> bytes:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        _reject("CAMPAIGN_INPUT_BYTE_LIMIT")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = _CampaignArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="run the one tracked synthetic campaign instead of bounded stdin",
    )
    parser.add_argument(
        "--operator-report",
        action="store_true",
        help="render deterministic Markdown instead of canonical result JSON",
    )
    try:
        args = parser.parse_args(argv)
        campaign_raw = _bounded_fixture_bytes() if args.fixture else _bounded_stdin_bytes()
        output = (
            render_operator_report_bytes(campaign_raw)
            if args.operator_report
            else analyze_campaign_bytes(campaign_raw)
        )
        sys.stdout.buffer.write(output)
        return 0
    except BreakThisPlanCampaignError as exc:
        sys.stderr.buffer.write(_error_bytes(exc.code))
        return 2
    except OSError:
        sys.stderr.buffer.write(_error_bytes("CAMPAIGN_INPUT_READ_FAILED"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
