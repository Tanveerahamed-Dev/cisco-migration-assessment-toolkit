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
SOURCE_CLASS = discovery.SOURCE_CLASS

MAX_CASES = 8
MAX_INPUT_BYTES = 9_437_184
MAX_OUTPUT_BYTES = 8_388_608
MAX_OPERATOR_REPORT_BYTES = 1_048_576
LIMIT_PROFILE = {
    "max_campaign_input_bytes": MAX_INPUT_BYTES,
    "max_campaign_output_bytes": MAX_OUTPUT_BYTES,
    "max_cases": MAX_CASES,
    "max_operator_report_bytes": MAX_OPERATOR_REPORT_BYTES,
    "nested_discovery_limit_profile": discovery.LIMIT_PROFILE,
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


def _validate_campaign_id(value: Any) -> str:
    if type(value) is not str or not _CAMPAIGN_ID.fullmatch(value):
        _reject("CAMPAIGN_ID_INVALID")
    try:
        discovery._identifier(value, "CAMPAIGN_ID_INVALID")
    except discovery.BreakThisPlanDiscoveryError:
        _reject("CAMPAIGN_ID_INVALID")
    return value


def _validate_input(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _INPUT_KEYS, "CAMPAIGN_INPUT_SCHEMA_INVALID")
    if obj["schema"] != INPUT_SCHEMA:
        _reject("CAMPAIGN_INPUT_SCHEMA_INVALID")
    if obj["prototype_mode"] != CAMPAIGN_MODE or obj["source_class"] != SOURCE_CLASS:
        _reject("SYNTHETIC_CAMPAIGN_BOUNDARY_REQUIRED")
    campaign_id = _validate_campaign_id(obj["campaign_id"])
    if obj["product_boundary"] != discovery.PRODUCT_BOUNDARY:
        _reject("PRODUCT_BOUNDARY_DRIFT")
    if obj["unresolved_dependency_ids"] != list(discovery.UNRESOLVED_DEPENDENCY_IDS):
        _reject("DEPENDENCY_BOUNDARY_INVALID")
    placeholders = obj["authority_placeholders"]
    if type(placeholders) is not dict or list(placeholders) != list(discovery.AUTHORITY_IDS):
        _reject("AUTHORITY_PLACEHOLDERS_INVALID")
    if any(placeholders[item] is not None for item in discovery.AUTHORITY_IDS):
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
        try:
            discovery._namespaced_identifier(
                case_id, "qdp001-fixture:", "CAMPAIGN_CASE_INVALID"
            )
        except discovery.BreakThisPlanDiscoveryError:
            _reject("CAMPAIGN_CASE_INVALID")
        checked_cases.append(case)
        case_ids.append(case_id)
    if case_ids != sorted(set(case_ids)):
        _reject("CAMPAIGN_CASES_NOT_SORTED_UNIQUE")
    return {
        "authority_placeholders": {item: None for item in discovery.AUTHORITY_IDS},
        "campaign_id": campaign_id,
        "cases": checked_cases,
        "product_boundary": discovery.PRODUCT_BOUNDARY,
        "prototype_mode": CAMPAIGN_MODE,
        "schema": INPUT_SCHEMA,
        "source_class": SOURCE_CLASS,
        "unresolved_dependency_ids": list(discovery.UNRESOLVED_DEPENDENCY_IDS),
    }


def _source_digest(path: Path, code: str) -> str:
    try:
        return bytes_digest(path.resolve().read_bytes())
    except OSError:
        _reject(code)


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


def _validate_child_result_boundary(result: Any) -> dict[str, Any]:
    obj = _exact_object(result, _DISCOVERY_RESULT_KEYS, "CAMPAIGN_CASE_RESULT_INVALID")
    fixed = {
        "authoritative": False,
        "authoritative_gate": None,
        "banner": discovery.PROTOTYPE_BANNER,
        "decision_effect": "NONE",
        "feasibility_verdict": None,
        "limit_profile": discovery.LIMIT_PROFILE,
        "next_observation": None,
        "preview_eligible": False,
        "promotion_eligible": False,
        "qualification_state": "EXPERIMENTAL",
        "schema": discovery.RESULT_SCHEMA,
        "selected_candidate": None,
        "translation_checked": False,
        "translation_state": discovery.TRANSLATION_STATE,
    }
    if any(obj[key] != expected for key, expected in fixed.items()):
        _reject("CAMPAIGN_CASE_NONPROMOTION_BOUNDARY_DRIFT")
    if obj["global_limitations"] != GLOBAL_LIMITATIONS[:6]:
        _reject("CAMPAIGN_CASE_LIMITATION_BOUNDARY_DRIFT")
    if obj["r2_closure_handoffs"] != discovery._closure_handoffs():
        _reject("CAMPAIGN_CASE_HANDOFF_DRIFT")
    for key in (
        "baseline_projection_digest",
        "candidate_set_digest",
        "input_digest",
        "product_boundary_digest",
        "requirements_digest",
        "semantics_digest",
    ):
        if type(obj[key]) is not str or not _DIGEST.fullmatch(obj[key]):
            _reject("CAMPAIGN_CASE_DIGEST_INVALID")
    evidence_requests = obj["next_evidence_requests"]
    if (
        type(evidence_requests) is not list
        or evidence_requests != sorted(set(evidence_requests))
        or any(type(item) is not str for item in evidence_requests)
    ):
        _reject("CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")
    try:
        for item in evidence_requests:
            discovery._identifier(item, "CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")
    except discovery.BreakThisPlanDiscoveryError:
        _reject("CAMPAIGN_CASE_EVIDENCE_REQUESTS_INVALID")
    candidate_results = obj["candidate_results"]
    if type(candidate_results) is not list or not candidate_results:
        _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
    for candidate_result in candidate_results:
        row = _exact_object(
            candidate_result,
            _CANDIDATE_RESULT_KEYS,
            "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID",
        )
        if row["result_kind"] not in {"ABSTENTION", "COUNTEREXAMPLE"}:
            _reject("CAMPAIGN_RESULT_KIND_INVALID")
        try:
            discovery._namespaced_identifier(
                row["candidate_id"], "candidate.", "CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID"
            )
        except discovery.BreakThisPlanDiscoveryError:
            _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
        for key in (
            "candidate_digest",
            "simulation_projection_digest",
        ):
            if type(row[key]) is not str or not _DIGEST.fullmatch(row[key]):
                _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
        limitations = row["limitations"]
        if (
            type(limitations) is not list
            or limitations != sorted(set(limitations))
            or any(type(item) is not str for item in limitations)
            or any(item not in discovery.LIMITATION_CODES for item in limitations)
        ):
            _reject("CAMPAIGN_LIMITATION_ACCOUNTING_INVALID")
        witnesses = row["counterexamples"]
        if type(witnesses) is not list:
            _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
        if row["result_kind"] == "COUNTEREXAMPLE":
            if (
                row["reason_code"]
                != "REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
                or not witnesses
            ):
                _reject("CAMPAIGN_COUNTEREXAMPLE_ACCOUNTING_INVALID")
        elif (
            row["reason_code"]
            not in discovery.ABSTENTION_REASON_CODES
            or witnesses
        ):
            _reject("CAMPAIGN_ABSTENTION_ACCOUNTING_INVALID")
        for key in ("checked_flow_requirements", "checked_steps"):
            if type(row[key]) is not int or type(row[key]) is bool or row[key] < 0:
                _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
    return obj


def _analyze(value: dict[str, Any], *, input_digest: str) -> dict[str, Any]:
    case_reports: list[dict[str, Any]] = []
    case_bindings: list[dict[str, str]] = []
    limitation_counts: Counter[str] = Counter()
    abstention_reason_counts: Counter[str] = Counter()
    next_evidence_requests: set[str] = set()
    discovery_semantics: set[str] = set()
    closure_handoffs: dict[str, Any] | None = None
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
                parse_canonical_json_bytes(result_raw, require_canonical=True)
            )
        except BreakThisPlanCampaignError:
            raise
        except (
            discovery.BreakThisPlanDiscoveryError,
            TransitionContractError,
            TypeError,
            ValueError,
        ):
            _reject("CAMPAIGN_CASE_REANALYSIS_FAILED")
        if type(result) is not dict or result.get("case_id") != case["case_id"]:
            _reject("CAMPAIGN_CASE_RESULT_INVALID")
        if result["input_digest"] != bytes_digest(case_raw):
            _reject("CAMPAIGN_CASE_INPUT_BINDING_INVALID")
        if result.get("product_boundary") != value["product_boundary"]:
            _reject("CAMPAIGN_CASE_PRODUCT_BOUNDARY_DRIFT")
        if result.get("authority_placeholders") != value["authority_placeholders"]:
            _reject("CAMPAIGN_CASE_AUTHORITY_DRIFT")
        if result.get("unresolved_dependency_ids") != value["unresolved_dependency_ids"]:
            _reject("CAMPAIGN_CASE_DEPENDENCY_DRIFT")
        current_handoffs = result.get("r2_closure_handoffs")
        if type(current_handoffs) is not dict:
            _reject("CAMPAIGN_CASE_HANDOFF_INVALID")
        if closure_handoffs is None:
            closure_handoffs = current_handoffs
        elif current_handoffs != closure_handoffs:
            _reject("CAMPAIGN_CASE_HANDOFF_DRIFT")

        semantics_digest = result.get("semantics_digest")
        if type(semantics_digest) is not str:
            _reject("CAMPAIGN_CASE_SEMANTICS_INVALID")
        discovery_semantics.add(semantics_digest)
        next_evidence_requests.update(result.get("next_evidence_requests", []))

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
            if type(candidate_result) is not dict:
                _reject("CAMPAIGN_CANDIDATE_ACCOUNTING_INVALID")
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
            case_counterexamples += len(witnesses)
            counterexample_count += len(witnesses)
            for witness in witnesses:
                try:
                    witness_raw = canonical_json_bytes(witness)
                    replay_raw = discovery.replay_counterexample_bytes(case_raw, witness_raw)
                    replay = parse_canonical_json_bytes(replay_raw, require_canonical=True)
                except (
                    discovery.BreakThisPlanDiscoveryError,
                    TransitionContractError,
                    TypeError,
                    ValueError,
                ):
                    _reject("CAMPAIGN_COUNTEREXAMPLE_REPLAY_FAILED")
                if (
                    type(replay) is not dict
                    or replay.get("replayed") is not True
                    or replay.get("witness_digest") != witness.get("witness_digest")
                    or replay.get("input_digest") != result.get("input_digest")
                ):
                    _reject("CAMPAIGN_COUNTEREXAMPLE_REPLAY_INVALID")
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

    if closure_handoffs is None or replayed_counterexample_count != counterexample_count:
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
    if len(discovery_semantics_digests) != 1:
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
        "r2_closure_handoffs": closure_handoffs,
        "schema": RESULT_SCHEMA,
        "selected_candidate": None,
        "summary": summary,
        "translation_checked": False,
        "translation_state": discovery.TRANSLATION_STATE,
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
        lines.append("")

    lines.extend(["## Observed limitation frequency", ""])
    if result["limitation_counts"]:
        lines.extend(
            f"- `{row['code']}`: {row['count']} candidate(s)"
            for row in result["limitation_counts"]
        )
    else:
        lines.append("- No limitation code was emitted; this is not a positive certificate.")
    lines.extend(["", "## Abstention reason frequency", ""])
    if result["abstention_reason_counts"]:
        lines.extend(
            f"- `{row['code']}`: {row['count']} candidate(s)"
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
