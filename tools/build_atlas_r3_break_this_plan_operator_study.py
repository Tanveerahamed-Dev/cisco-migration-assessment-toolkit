"""Build and stage a bounded, offline QDP-001 operator comprehension study.

The builder recomputes the tracked synthetic campaign from the current exact clean source,
creates a researcher-only master kit, and enforces separate Phase A, Phase B, and debrief
deliveries.  A canonical response lock receipt is required before a later stage can be
released.  It does not run a participant, collect network evidence, fill authority
placeholders, authenticate custody, or change a release state.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

sys.dont_write_bytecode = True
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
from tools import atlas_r3_operator_study_scoring as scoring  # noqa: E402
from tools import run_atlas_r3_break_this_plan_campaign as campaign_runner  # noqa: E402

SCORER_SOURCE = REPOSITORY_ROOT / "tools" / "atlas_r3_operator_study_scoring.py"

STUDY_SCHEMA = "atlas.r3-qdp001-operator-study-kit/1"
BASE_CAMPAIGN_MERGE = "a6aae621d484cb762c1c6d21797516bd34a14b48"
CAMPAIGN_FIXTURE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "atlas-r3-break-this-plan"
    / "campaign.synthetic.json"
)
STUDY_ID = scoring.EXPECTED_STUDY_ID
EXPECTED_SOURCE: dict[str, Any] = {}
EXPECTED_FILE_DIGESTS: dict[str, str] = {}
EXPECTED_SUMMARY = {
    "abstention_candidate_count": 5,
    "candidate_count": 6,
    "case_count": 4,
    "counterexample_candidate_count": 1,
    "counterexample_count": 1,
    "replay_failure_count": 0,
    "replayed_counterexample_count": 1,
}
EXPECTED_BOUNDARY = {
    "qcp_001": {
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
    },
    "release_2": "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
    "release_3": "DISCOVERY_PLANNING_ONLY",
    "runtime": "PARTIAL_NONPORTABLE_PROTOTYPE",
}
EXPECTED_GLOBAL_LIMITATIONS = [
    "DISCOVERY_PLANNING_ONLY",
    "NO_CANDIDATE_RANKING_OR_SELECTION",
    "NO_EXTERNAL_OBSERVATION_AUTHORIZED",
    "NO_POSITIVE_FEASIBILITY_OR_COMPLETENESS_CERTIFICATE",
    "NO_QDP_TO_QCP_TRANSLATION",
    "SYNTHETIC_TEST_ONLY",
    "CAMPAIGN_AGGREGATION_DOES_NOT_ADD_EVIDENCE",
    "REPLAY_IS_SYNTHETIC_REPRODUCTION_ONLY",
]
GLOBAL_LIMITATION_MEANINGS = {
    "DISCOVERY_PLANNING_ONLY": "Release 3 remains discovery planning only.",
    "NO_CANDIDATE_RANKING_OR_SELECTION": "The campaign ranks and selects no candidate.",
    "NO_EXTERNAL_OBSERVATION_AUTHORIZED": "No runtime, workload, field, or device observation is authorized.",
    "NO_POSITIVE_FEASIBILITY_OR_COMPLETENESS_CERTIFICATE": "The campaign proves neither feasibility nor search completeness.",
    "NO_QDP_TO_QCP_TRANSLATION": "No QDP result is translated into QCP-001 execution or authority.",
    "SYNTHETIC_TEST_ONLY": "Every case is synthetic rather than field or representative-workload evidence.",
    "CAMPAIGN_AGGREGATION_DOES_NOT_ADD_EVIDENCE": "Combining cases does not increase their evidence authority.",
    "REPLAY_IS_SYNTHETIC_REPRODUCTION_ONLY": "Replay shows deterministic synthetic reproduction, not trust or custody.",
}
EXPECTED_OPERATOR_INTERPRETATION = {
    "abstention": "NO_SUPPORT_OR_SAFETY_INFERENCE",
    "campaign": "NO_RANKING_SELECTION_FEASIBILITY_OR_COMPLETENESS",
    "counterexample": "REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY",
    "limitations": "RETAIN_WITH_EACH_CANDIDATE",
}
REPLAY_NONCLAIMS = scoring.EXPECTED_REPLAY_NONCLAIMS
FORBIDDEN_CLAIM_KEYS = scoring.EXPECTED_FORBIDDEN_CLAIM_KEYS
MAX_SOURCE_FILE_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_RUN_CONFIG_BYTES = 64 * 1024
MAX_PACKAGE_FILES = 256
MAX_PACKAGE_DEPTH = 12
MAX_PACKAGE_TOTAL_BYTES = 64 * 1024 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}$")
RUN_CONFIG_SCHEMA = "atlas.r3-qdp001-operator-study-run-config/1"
STAGE_MANIFEST_SCHEMA = "atlas.r3-qdp001-operator-study-stage/1"
LOCK_RECEIPT_SCHEMA = "atlas.r3-qdp001-operator-study-response-lock/1"
RUN_CONFIG_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "participant_code",
        "participant_contact",
        "withdrawal_contact",
        "accessibility_contact",
        "purpose",
        "session_cap_minutes",
        "data_use",
        "data_storage",
        "data_access",
        "data_retention",
        "data_deletion",
        "recording_planned",
    }
)
STAGE_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "stage",
        "study_id",
        "authoritative",
        "decision_effect",
        "authentication",
        "custody_proved",
        "trusted_time",
        "run_id",
        "participant_code",
        "campaign_input_digest",
        "master_manifest_digest",
        "run_config_digest",
        "run_config",
        "predecessor_lock_digest",
        "files",
    }
)
PHASE_A_STAGE_MEMBERS = frozenset(
    {
        "index.html",
        "01-study-brief.html",
        "02-neutral-plan.html",
        "03-response.html",
        "PLAIN-TEXT.md",
        "RESPONSE-WORKSHEET.md",
        "PARTICIPANT-INFORMATION.md",
        "response.schema.json",
        "START.cmd",
    }
)
PHASE_B_STAGE_MEMBERS = frozenset(
    {
        "index.html",
        "05-response.html",
        "PLAIN-TEXT.md",
        "RESPONSE-WORKSHEET.md",
        "response.schema.json",
        "START.cmd",
    }
)
DEBRIEF_STAGE_MEMBERS = frozenset({"index.html", "START.cmd"})
SOURCE_BINDING_PATHS = (
    "cisco_toolkit/cutover_sim.py",
    "cisco_toolkit/failover.py",
    "cisco_toolkit/fib.py",
    "cisco_toolkit/textutils.py",
    "cisco_toolkit/transition_contract.py",
    "cisco_toolkit/whatif.py",
    "docs/atlas-release-3-break-this-plan-campaign-contract-2026-08-30.md",
    "docs/atlas-release-3-qdp001-operator-study-contract-2026-08-31.md",
    "docs/ssot.md",
    "docs/schemas/atlas-r3-break-this-plan-campaign-input-v1.schema.json",
    "docs/schemas/atlas-r3-break-this-plan-campaign-result-v1.schema.json",
    "docs/schemas/atlas-r3-break-this-plan-discovery-input-v1.schema.json",
    "docs/schemas/atlas-r3-break-this-plan-discovery-result-v1.schema.json",
    "tests/fixtures/atlas-r3-break-this-plan/campaign.synthetic.json",
    "tests/test_atlas_r3_break_this_plan_campaign.py",
    "tests/test_atlas_r3_break_this_plan_operator_study.py",
    "tools/atlas_r3_operator_study_scoring.py",
    "tools/build_atlas_r3_break_this_plan_operator_study.py",
    "tools/run_atlas_r3_break_this_plan_campaign.py",
    "tools/run_atlas_r3_break_this_plan_discovery.py",
)


class StudyBuildError(ValueError):
    """Stable, non-echoing build refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject(code: str) -> NoReturn:
    raise StudyBuildError(code)


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _reject("JSON_NOT_CANONICALIZABLE")


def _parse_json(raw: bytes, *, require_canonical: bool = True) -> Any:
    if not raw or len(raw) > MAX_SOURCE_FILE_BYTES:
        _reject("SOURCE_JSON_BYTE_LIMIT_OR_EMPTY")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_duplicate_guard,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                StudyBuildError("NONFINITE_JSON_NUMBER")
            ),
        )
    except StudyBuildError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _reject("SOURCE_JSON_INVALID")
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if depth > 64 or visited > 100_000:
            _reject("SOURCE_JSON_NESTING_OR_NODE_LIMIT")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
    if require_canonical and raw != _canonical_json(value):
        _reject("SOURCE_JSON_NOT_CANONICAL")
    return value


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_regular(path: Path, *, max_bytes: int = MAX_SOURCE_FILE_BYTES) -> bytes:
    try:
        path_info = path.lstat()
    except OSError:
        _reject("SOURCE_FILE_UNREADABLE")
    attributes = getattr(path_info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISREG(path_info.st_mode)
        or path.is_symlink()
        or bool(attributes & reparse)
        or path_info.st_size <= 0
        or path_info.st_size > max_bytes
        or path_info.st_nlink != 1
    ):
        _reject("SOURCE_FILE_NOT_BOUNDED_REGULAR")
    try:
        with path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > max_bytes
                or before.st_nlink != 1
            ):
                _reject("SOURCE_FILE_NOT_BOUNDED_REGULAR")
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = handle.read(min(1_048_576, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if handle.read(1):
                _reject("SOURCE_FILE_NOT_BOUNDED_REGULAR")
            after = os.fstat(handle.fileno())
        final_info = path.lstat()
    except OSError:
        _reject("SOURCE_FILE_UNREADABLE")
    raw = b"".join(chunks)
    identities = {
        (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
        )
        for item in (path_info, before, after, final_info)
    }
    if (
        len(identities) != 1
        or len(raw) != before.st_size
        or len(raw) > max_bytes
        or path.is_symlink()
        or bool(getattr(final_info, "st_file_attributes", 0) & reparse)
        or any(item.st_nlink != 1 for item in (before, after, final_info))
    ):
        _reject("SOURCE_FILE_CHANGED_DURING_READ")
    return raw


def _git_value(*args: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        _reject("GIT_IDENTITY_UNAVAILABLE")
    return run.stdout.strip()


def _git_bytes(*args: str) -> bytes:
    run = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *args],
        check=False,
        capture_output=True,
    )
    if run.returncode != 0:
        _reject("GIT_IDENTITY_UNAVAILABLE")
    return run.stdout


def _validate_source_identity(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "base_campaign_merge",
        "commit",
        "parents",
        "source_state",
        "tree",
    }:
        _reject("SOURCE_IDENTITY_INVALID")
    for key in ("base_campaign_merge", "commit", "tree"):
        if type(value[key]) is not str or re.fullmatch(r"[0-9a-f]{40}", value[key]) is None:
            _reject("SOURCE_IDENTITY_INVALID")
    if value["base_campaign_merge"] != BASE_CAMPAIGN_MERGE:
        _reject("SOURCE_IDENTITY_INVALID")
    if (
        type(value["parents"]) is not list
        or not 1 <= len(value["parents"]) <= 8
        or any(
            type(item) is not str or re.fullmatch(r"[0-9a-f]{40}", item) is None
            for item in value["parents"]
        )
        or value["source_state"] not in {"EXACT_CLEAN_COMMIT", "DIRTY_TEST_PREVIEW"}
    ):
        _reject("SOURCE_IDENTITY_INVALID")
    return deepcopy(value)


def _current_source_identity(*, allow_dirty_test_preview: bool = False) -> dict[str, Any]:
    if _git_value("rev-parse", "--is-shallow-repository") != "false":
        _reject("SHALLOW_SOURCE_FORBIDDEN")
    status = _git_value("status", "--porcelain=v1", "--untracked-files=all")
    if status and not allow_dirty_test_preview:
        _reject("TRACKED_OR_UNTRACKED_WORKTREE_NOT_CLEAN")
    commit = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    parent_line = _git_value("rev-list", "--parents", "-n", "1", "HEAD").split()
    value = {
        "base_campaign_merge": BASE_CAMPAIGN_MERGE,
        "commit": commit,
        "parents": parent_line[1:],
        "source_state": "DIRTY_TEST_PREVIEW" if status else "EXACT_CLEAN_COMMIT",
        "tree": tree,
    }
    return _validate_source_identity(value)


def _activate_source_identity(source: dict[str, Any]) -> None:
    global EXPECTED_FILE_DIGESTS, EXPECTED_SOURCE
    EXPECTED_SOURCE = deepcopy(source)
    EXPECTED_FILE_DIGESTS = {}


def _build_source_campaign(source_identity: dict[str, Any]) -> dict[str, Any]:
    source = _validate_source_identity(source_identity)
    _activate_source_identity(source)
    input_raw = _read_regular(CAMPAIGN_FIXTURE)
    try:
        result_raw = campaign_runner.analyze_campaign_bytes(input_raw)
        report_raw = campaign_runner.render_operator_report_bytes(input_raw)
    except campaign_runner.BreakThisPlanCampaignError:
        _reject("SOURCE_CAMPAIGN_RECOMPUTATION_FAILED")
    campaign_input = _parse_json(input_raw)
    campaign_result = _parse_json(result_raw)
    try:
        report_text = report_raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject("OPERATOR_REPORT_UTF8_INVALID")
    EXPECTED_FILE_DIGESTS.update(
        {
            "campaign-input.json": _digest(input_raw),
            "campaign-result.json": _digest(result_raw),
            "operator-report.md": _digest(report_raw),
        }
    )
    if (
        type(campaign_input) is not dict
        or campaign_input.get("schema") != "atlas.r3-break-this-plan-campaign-input/1"
        or campaign_input.get("source_class") != "SYNTHETIC_TEST_ONLY"
        or campaign_input.get("product_boundary") != EXPECTED_BOUNDARY
        or campaign_input.get("authority_placeholders")
        != {"R2-AUTH-001": None, "R2-AUTH-002": None, "R2-AUTH-004": None}
    ):
        _reject("CAMPAIGN_INPUT_BOUNDARY_INVALID")
    if (
        type(campaign_result) is not dict
        or campaign_result.get("schema") != "atlas.r3-break-this-plan-campaign-result/1"
        or campaign_result.get("summary") != EXPECTED_SUMMARY
        or campaign_result.get("authoritative") is not False
        or campaign_result.get("decision_effect") != "NONE"
        or campaign_result.get("selected_candidate") is not None
        or campaign_result.get("feasibility_verdict") is not None
        or campaign_result.get("promotion_eligible") is not False
        or campaign_result.get("preview_eligible") is not False
        or campaign_result.get("product_boundary") != EXPECTED_BOUNDARY
        or campaign_result.get("global_limitations") != EXPECTED_GLOBAL_LIMITATIONS
        or campaign_result.get("operator_interpretation") != EXPECTED_OPERATOR_INTERPRETATION
        or campaign_result.get("authority_placeholders")
        != {"R2-AUTH-001": None, "R2-AUTH-002": None, "R2-AUTH-004": None}
    ):
        _reject("CAMPAIGN_RESULT_BOUNDARY_INVALID")
    if report_text.count("R3 SYNTHETIC CAMPAIGN — NON-AUTHORITATIVE") != 1:
        _reject("OPERATOR_REPORT_BOUNDARY_INVALID")
    cases = campaign_input.get("cases")
    case_reports = campaign_result.get("case_reports")
    if (
        type(cases) is not list
        or type(case_reports) is not list
        or len(cases) != EXPECTED_SUMMARY["case_count"]
        or len(case_reports) != len(cases)
        or [item.get("case_id") for item in cases]
        != [item.get("case_id") for item in case_reports]
    ):
        _reject("CAMPAIGN_CASE_ACCOUNTING_INVALID")
    file_rows = {
        "campaign-input.json": {
            "bytes": len(input_raw),
            "digest": EXPECTED_FILE_DIGESTS["campaign-input.json"],
        },
        "campaign-result.json": {
            "bytes": len(result_raw),
            "digest": EXPECTED_FILE_DIGESTS["campaign-result.json"],
        },
        "operator-report.md": {
            "bytes": len(report_raw),
            "digest": EXPECTED_FILE_DIGESTS["operator-report.md"],
        },
    }
    manifest = {
        "schema": "atlas.r3-qdp001-source-campaign/1",
        "campaign": {"summary": EXPECTED_SUMMARY},
        "files": file_rows,
        "source": source,
        "verification": {
            "external_reviews_inherited": False,
            "hosted_checks_inherited": False,
            "same_process_recomputation_is_independent_trust": False,
        },
    }
    return {
        "input": campaign_input,
        "input_raw": input_raw,
        "result": campaign_result,
        "result_raw": result_raw,
        "report_raw": report_raw,
        "report_text": report_text,
        "manifest": manifest,
        "manifest_raw": _canonical_json(manifest),
    }


def _source_file_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    clean = source["source_state"] == "EXACT_CLEAN_COMMIT"
    if clean:
        if (
            _git_value("status", "--porcelain=v1", "--untracked-files=all")
            or _git_value("rev-parse", "HEAD") != source["commit"]
            or _git_value("rev-parse", "HEAD^{tree}") != source["tree"]
        ):
            _reject("SOURCE_CHANGED_DURING_BUILD")
        actual_parents = _git_value(
            "rev-list", "--parents", "-n", "1", source["commit"]
        ).split()[1:]
        if source["parents"] != actual_parents:
            _reject("SOURCE_PARENT_BINDING_INVALID")
        _git_value(
            "merge-base",
            "--is-ancestor",
            BASE_CAMPAIGN_MERGE,
            source["commit"],
        )
    for name in SOURCE_BINDING_PATHS:
        path = REPOSITORY_ROOT.joinpath(*PurePosixPath(name).parts)
        raw = _read_regular(path)
        if clean:
            entry = _git_value(
                "ls-tree", "-r", "--full-tree", source["commit"], "--", name
            )
            match = re.fullmatch(r"([0-7]{6}) blob ([0-9a-f]{40})\t(.+)", entry)
            if match is None or match.group(3) != name:
                _reject("SOURCE_BLOB_BINDING_INVALID")
            blob_raw = _git_bytes("show", f"{source['commit']}:{name}")
            if blob_raw != raw:
                _reject("SOURCE_BLOB_BINDING_INVALID")
            mode, oid = match.group(1), match.group(2)
        else:
            mode, oid = None, None
        rows.append(
            {
                "bytes": len(raw),
                "git_blob": oid,
                "git_mode": mode,
                "path": name,
                "sha256": _digest(raw),
            }
        )
    return rows


def _identifier(value: Any) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        _reject("CAMPAIGN_IDENTIFIER_INVALID")
    return value


def _aliases(campaign_input: dict[str, Any], campaign_result: dict[str, Any]) -> dict[str, Any]:
    report_by_case = {row["case_id"]: row for row in campaign_result["case_reports"]}
    cases: list[dict[str, Any]] = []
    contextual_aliases: dict[str, dict[str, str]] = {
        "cases": {},
        "requirements": {},
        "candidates": {},
        "steps": {},
    }
    for case_index, case in enumerate(campaign_input["cases"]):
        letter = chr(ord("A") + case_index)
        case_id = _identifier(case["case_id"])
        case_alias = f"Case {letter}"
        contextual_aliases["cases"][case_id] = case_alias
        requirements = []
        for requirement_index, requirement in enumerate(case["requirements"]):
            requirement_id = _identifier(requirement["requirement_id"])
            alias = f"Requirement {letter}-R{requirement_index + 1}"
            contextual_aliases["requirements"][f"{case_id}|{requirement_id}"] = alias
            requirements.append(
                {
                    "alias": alias,
                    "source_id": requirement_id,
                    "kind": requirement["kind"],
                    "src": requirement.get("src"),
                    "dst": requirement.get("dst"),
                }
            )
        result_rows = report_by_case[case_id]["discovery_result"]["candidate_results"]
        result_by_candidate = {row["candidate_id"]: row for row in result_rows}
        candidates = []
        for candidate_index, candidate in enumerate(case["candidates"]):
            candidate_id = _identifier(candidate["candidate_id"])
            alias = f"Plan {letter}{candidate_index + 1}"
            contextual_aliases["candidates"][f"{case_id}|{candidate_id}"] = alias
            steps = []
            for step_index, step in enumerate(candidate["steps"]):
                step_id = _identifier(step["step_id"])
                step_alias = f"Step {letter}{candidate_index + 1}.{step_index + 1}"
                contextual_aliases["steps"][
                    f"{case_id}|{candidate_id}|{step_id}"
                ] = step_alias
                steps.append(
                    {
                        "alias": step_alias,
                        "source_id": step_id,
                        "action": step["action"],
                        "parameters": step["parameters"],
                    }
                )
            result = result_by_candidate[candidate_id]
            candidates.append(
                {
                    "alias": alias,
                    "source_id": candidate_id,
                    "steps": steps,
                    "assumptions": candidate["assumptions"],
                    "result": result,
                    "neutral_observation": _neutral_observation(result, steps),
                }
            )
        cases.append(
            {
                "alias": case_alias,
                "source_id": case_id,
                "requirements": requirements,
                "candidates": candidates,
            }
        )
    return {"cases": cases, "contextual_aliases": contextual_aliases}


def _neutral_observation(result: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    witnesses = result["counterexamples"]
    if witnesses:
        witness = witnesses[0]
        matching = next(item for item in steps if item["source_id"] == witness["step_id"])
        return (
            f"At {matching['alias']}, a declared flow changed from computed reached to computed "
            "unreachable with positive observed-discard evidence; the exact synthetic witness "
            "replayed once."
        )
    limitations = set(result["limitations"])
    if "BASELINE_REQUIREMENT_CONFLICT" in limitations:
        return "A declared flow was not positively reached in the synthetic baseline."
    if "HUMAN_REQUIREMENT_UNEVALUATED" in limitations:
        return "A human-only requirement remained unresolved; no machine support conclusion exists."
    if "PATH_LOSS_IS_INCONCLUSIVE" in limitations:
        return "A path became unprovable, but no positive observed-discard evidence was present."
    if "SIMULATION_NOT_EVALUABLE" in limitations:
        return "At least one declared action had no supported modeled effect; the full plan was not evaluable."
    if "UNRESOLVED_ASSUMPTION" in limitations:
        return "A declared assumption remained unresolved; no support conclusion exists."
    return "No qualifying observed-discard witness was emitted; absence is not support."


def _action_text(action: str, parameters: dict[str, Any]) -> str:
    if action == "fail_node":
        return f"Take node {parameters.get('id', '?')} out of service."
    if action == "shut_link":
        return (
            f"Administratively shut interface {parameters.get('interface', '?')} on node "
            f"{parameters.get('host', '?')}."
        )
    return f"Request unsupported modeled action {action}; no supported effect is assumed."


def _requirement_text(requirement: dict[str, Any]) -> str:
    if requirement["kind"] == "PRESERVE_SYNTHETIC_FLOW":
        return f"Preserve the synthetic flow {requirement['src']} → {requirement['dst']}."
    return "Resolve a human-only requirement that the machine does not evaluate."


def _ground_truth(alias_data: dict[str, Any], campaign_result: dict[str, Any]) -> dict[str, Any]:
    witnesses = []
    for case_report in campaign_result["case_reports"]:
        for candidate in case_report["discovery_result"]["candidate_results"]:
            for witness in candidate["counterexamples"]:
                witnesses.append(witness)
    if len(witnesses) != 1:
        _reject("STUDY_WITNESS_DENOMINATOR_INVALID")
    witness = witnesses[0]
    mapping = alias_data["contextual_aliases"]
    case_input = next(
        case for case in alias_data["cases"] if case["source_id"] == witness["case_id"]
    )
    candidate = next(
        item
        for item in case_input["candidates"]
        if item["source_id"] == witness["candidate_id"]
    )
    step = next(item for item in candidate["steps"] if item["source_id"] == witness["step_id"])
    action = step["action"]
    parameters = step["parameters"]
    if action != "shut_link" or parameters != {"host": "A", "interface": "Gi0/1"}:
        _reject("STUDY_UNSAFE_ACTION_DRIFT")
    candidate_limitations = {
        candidate_row["candidate_id"]: candidate_row["limitations"]
        for case_report in campaign_result["case_reports"]
        for candidate_row in case_report["discovery_result"]["candidate_results"]
    }
    next_by_case = {
        row["case_id"]: (
            row["discovery_result"]["next_evidence_requests"]
            if row["discovery_result"]["next_evidence_requests"]
            else ["__NONE_EMITTED__"]
        )
        for row in campaign_result["case_reports"]
    }
    phase_a = {
        "unsafe_plan_alias": mapping["candidates"][
            f"{witness['case_id']}|{witness['candidate_id']}"
        ],
        "unsafe_step_alias": mapping["steps"][
            f"{witness['case_id']}|{witness['candidate_id']}|{witness['step_id']}"
        ],
        "affected_requirement_alias": mapping["requirements"][
            f"{witness['case_id']}|{witness['requirement_id']}"
        ],
    }
    phase_b = {
        "case_id": witness["case_id"],
        "candidate_id": witness["candidate_id"],
        "step_id": witness["step_id"],
        "action": "shut_link:A:Gi0/1",
        "requirement_id": witness["requirement_id"],
        "result_kind": "COUNTEREXAMPLE",
        "global_limitations": sorted(campaign_result["global_limitations"]),
        "candidate_limitations": {
            key: sorted(value) for key, value in candidate_limitations.items()
        },
        "next_evidence_by_case": next_by_case,
        "product_boundary": campaign_result["product_boundary"],
        "authority_placeholders": campaign_result["authority_placeholders"],
        "replay_meaning": "REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY",
        "abstention_meaning": "NO_SUPPORT_OR_SAFETY_INFERENCE",
        "authority_action": "LEAVE_NULL_AWAIT_AUTHENTICATED_EXTERNAL_UPDATE_NO_COLLECTION",
    }
    return {"phase_a": phase_a, "phase_b": phase_b, "witness": witness}


CSS = """
:root{color-scheme:light dark;font-family:Segoe UI,Arial,sans-serif;line-height:1.55}
*,*::before,*::after{box-sizing:border-box}
body{max-width:74rem;margin:auto;padding:1.25rem;background:#f8fafc;color:#172033;overflow-wrap:anywhere}
h1,h2,h3{line-height:1.2} .banner{border:.2rem solid #8b1e1e;padding:1rem;font-weight:700}
.card{border:.12rem solid #526277;border-radius:.45rem;padding:1rem;margin:1rem 0;background:#fff}
table{border-collapse:collapse;width:100%;margin:1rem 0} th,td{border:1px solid #667;padding:.55rem;text-align:left;vertical-align:top}
th{background:#e8eef7} code{overflow-wrap:anywhere} fieldset{margin:1rem 0;padding:1rem;min-width:0}
pre{overflow-wrap:anywhere;word-break:break-word}
label{display:block;margin:.55rem 0} input,select,textarea,button{font:inherit;padding:.45rem;max-width:100%}
input:not([type=checkbox]),select,textarea,button{width:100%} input[type=checkbox]{width:auto}
textarea{width:100%;min-height:7rem} :focus-visible{outline:.22rem solid #005fcc;outline-offset:.15rem}
.warning{border-left:.4rem solid #a33;padding:.7rem 1rem;background:#fff4f4}.muted{color:#46556b}
@media(max-width:40rem){body{padding:.65rem}table{display:block;overflow-x:auto}}
@media(prefers-color-scheme:dark){body{background:#111827;color:#f3f4f6}.card{background:#1f2937}th{background:#27364a}.warning{background:#391d1d}.muted{color:#cbd5e1}:focus-visible{outline-color:#8cc8ff}}
"""


def _page(title: str, body: str, script: str = "") -> str:
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<main>{body}</main>{script}</body></html>\n"
    )


def _js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _download_script(phase: str, payload_expression: str) -> str:
    semantic_helpers = (
        f"const NONCLAIMS={_js_json(REPLAY_NONCLAIMS)};\n"
        f"const CLAIM_KEYS={_js_json(FORBIDDEN_CLAIM_KEYS)};\n"
        "function values(name){return [...document.querySelectorAll(`[name=\"${name}\"]:checked`)].map(x=>x.value).sort();}\n"
        "function parseList(id){return document.getElementById(id).value.split(/[,;\\n\\r]+/).map(x=>x.trim()).filter(Boolean).sort();}\n"
        "function claims(){const out={}; for(const key of CLAIM_KEYS){out[key]=document.getElementById('claim-'+key).value==='YES';} return out;}\n"
        if phase == "B"
        else ""
    )
    return f"""
<script>
const STUDY_ID={_js_json(STUDY_ID)};
const CAMPAIGN_DIGEST={_js_json(EXPECTED_FILE_DIGESTS['campaign-input.json'])};
{semantic_helpers}
function downloadResponse(event){{event.preventDefault();const form=event.currentTarget;for(const field of form.querySelectorAll('textarea[data-narrative]')){{field.setCustomValidity(Array.from(field.value.trim()).length>=20?'':'Enter at least 20 non-space characters.');}}if(!form.reportValidity())return;const response={payload_expression};
const code=response.participant_code.replace(/[^A-Za-z0-9._-]/g,'_');const blob=new Blob([JSON.stringify(response,null,2)+'\\n'],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${{code}}-phase-{phase.lower()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById('saved').textContent='Download requested. Confirm the file exists with the moderator; if not, retry or use the worksheet. Do not revise after the next phase begins.';}}
</script>
"""


def _claims_fields() -> str:
    return (
        "<fieldset><legend>Answer every row: does the campaign establish this positive claim?</legend>"
        + "".join(
            f"<label><code>{escape(key)}</code> <select id=\"claim-{escape(key)}\" "
            "required><option value=\"\">Choose YES or NO</option>"
            "<option value=\"NO\">NO</option><option value=\"YES\">YES</option>"
            "</select></label>"
            for key in FORBIDDEN_CLAIM_KEYS
        )
        + "</fieldset>"
    )


def _nonclaim_fields() -> str:
    return "<fieldset><legend>Select every thing replay does not establish</legend>" + "".join(
        f"<label><input type=\"checkbox\" name=\"nonclaim\" value=\"{escape(item)}\"> <code>{escape(item)}</code></label>"
        for item in REPLAY_NONCLAIMS
    ) + "</fieldset>"


def _phase_a_plan(alias_data: dict[str, Any]) -> str:
    scenario = next(
        case for case in alias_data["cases"] if case["source_id"].endswith("unsafe-middle")
    )
    cards = []
    for case in [scenario]:
        requirements = "".join(
            f"<li><strong>{escape(item['alias'])}</strong>: {escape(_requirement_text(item))}</li>"
            for item in case["requirements"]
        )
        plans = []
        for candidate in case["candidates"]:
            steps = "".join(
                f"<li><strong>{escape(item['alias'])}</strong>: {escape(_action_text(item['action'], item['parameters']))}</li>"
                for item in candidate["steps"]
            )
            plans.append(
                f"<section class=\"card\"><h3>{escape(candidate['alias'])}</h3><ol>{steps}</ol></section>"
            )
        cards.append(
            f"<section><h2>{escape(case['alias'])}</h2><h3>Requirements</h3><ul>{requirements}</ul>{''.join(plans)}</section>"
        )
    body = f"""
<h1>Phase A — Neutral plan diagnosis</h1>
<p class="banner">SYNTHETIC STUDY STIMULUS — NON-AUTHORITATIVE — DECISION EFFECT: NONE</p>
<p>Find the plan and first step that breaks the declared requirement. Labels are neutral aliases. Do not open Phase B yet.</p>
<section class="card"><h2>Scenario context</h2><ul><li>Node A reaches the required destination network through next-hop owner Y over interface A/Gi0/1.</li><li>Node Z serves only an unrelated synthetic network.</li><li>The required flow starts from 10.0.1.1 and must continue to 10.0.5.50.</li></ul></section>
<p class="warning">Reason from the plan actions and the scenario. No model verdict, witness, exact semantic ID, or answer-bearing observation is shown in Phase A.</p>
{''.join(cards)}
<p><a href="03-response.html">Open the Phase A response form</a></p>
"""
    return _page("Phase A — Neutral plan diagnosis", body)


def _options(values: list[str]) -> str:
    return '<option value="">Choose</option>' + "".join(
        f'<option value="{escape(value)}">{escape(value)}</option>' for value in values
    )


def _phase_a_response(alias_data: dict[str, Any]) -> str:
    scenario = next(
        case for case in alias_data["cases"] if case["source_id"].endswith("unsafe-middle")
    )
    plans = [item["alias"] for item in scenario["candidates"]]
    steps = [step["alias"] for item in scenario["candidates"] for step in item["steps"]]
    body = f"""
<h1>Phase A response</h1><p>Complete this before Phase B. Download and lock the response.</p>
<p>Prompt codes: P0 no help; P1 navigation only; P2 conceptual hint; P3 answer disclosure. Confirm the code with the moderator.</p>
<noscript><p class="warning">JavaScript is unavailable. Use <a href="RESPONSE-WORKSHEET.md">the Phase A response worksheet</a>, preserve its original bytes, and lock it directly with the source tool. Do not transcribe or replace it.</p></noscript>
<form onsubmit="downloadResponse(event)">
<label>Participant code <input id="participant" required maxlength="32" pattern="[A-Za-z0-9][A-Za-z0-9._-]{{0,31}}"></label>
<label>Prior exposure <select id="exposure" required>{_options(['NO','YES','UNKNOWN'])}</select></label>
<label>Highest prompt received <select id="prompt" required>{_options(['P0','P1','P2','P3'])}</select></label>
<label><input id="consent" type="checkbox" required> I voluntarily consent to this formative study and understand I may stop without penalty.</label>
<label><input id="data-ack" type="checkbox" required> I have read and understood the participant information and data-handling terms.</label>
<label>Unsafe plan <select id="plan" required>{_options(plans)}</select></label>
<label>First demonstrated unsafe step <select id="step" required>{_options(steps)}</select></label>
<label>Affected requirement alias <input id="requirement" required maxlength="32" placeholder="Type the neutral requirement alias"></label>
<label>Explain the unsafe step and affected requirement <textarea id="explanation" data-narrative required minlength="20" maxlength="8192"></textarea></label>
<button type="submit">Download locked Phase A response</button><p id="saved" role="status"></p></form>
"""
    expression = """{
schema:'atlas.r3-qdp001-operator-study-response/1',study_id:STUDY_ID,phase:'A',participant_code:document.getElementById('participant').value,campaign_input_digest:CAMPAIGN_DIGEST,prompt_code:document.getElementById('prompt').value,prior_exposure:document.getElementById('exposure').value,voluntary_consent:document.getElementById('consent').checked,data_handling_acknowledged:document.getElementById('data-ack').checked,unsafe_plan_alias:document.getElementById('plan').value,unsafe_step_alias:document.getElementById('step').value,affected_requirement_alias:document.getElementById('requirement').value,explanation:document.getElementById('explanation').value}"""
    return _page("Phase A response", body, _download_script("A", expression))


def _phase_b_report(campaign: dict[str, Any]) -> str:
    result = campaign["result"]
    boundary = result["product_boundary"]
    handoffs = result["r2_closure_handoffs"]
    case_sections = []
    for case_report in result["case_reports"]:
        discovery_result = case_report["discovery_result"]
        replay_by_candidate: dict[str, int] = {}
        for envelope in case_report["replay_receipts"]:
            candidate_digest = envelope["replay_receipt"]["candidate_digest"]
            replay_by_candidate[candidate_digest] = (
                replay_by_candidate.get(candidate_digest, 0) + 1
            )
        rows = []
        for candidate in discovery_result["candidate_results"]:
            limitations = "".join(
                f"<li><code>{escape(item)}</code></li>"
                for item in candidate["limitations"]
            )
            rows.append(
                "<tr>"
                f"<th scope=\"row\"><code>{escape(candidate['candidate_id'])}</code></th>"
                f"<td><code>{escape(candidate['result_kind'])}</code></td>"
                f"<td><code>{escape(candidate['reason_code'])}</code></td>"
                f"<td>{candidate['checked_steps']}</td>"
                f"<td>{replay_by_candidate.get(candidate['candidate_digest'], 0)}</td>"
                f"<td><ul>{limitations}</ul></td></tr>"
            )
        requests = discovery_result["next_evidence_requests"]
        request_text = (
            ", ".join(f"<code>{escape(item)}</code>" for item in requests)
            if requests
            else "<strong>None emitted</strong>; this is not support or evidence completeness."
        )
        witnesses = []
        witness_by_digest = {
            witness["witness_digest"]: witness
            for candidate in discovery_result["candidate_results"]
            for witness in candidate["counterexamples"]
        }
        for envelope in case_report["replay_receipts"]:
            receipt = envelope["replay_receipt"]
            witness = witness_by_digest[receipt["witness_digest"]]
            witnesses.append(
                "<li>Candidate "
                f"<code>{escape(witness['candidate_id'])}</code>; step "
                f"<code>{escape(witness['step_id'])}</code>; requirement "
                f"<code>{escape(witness['requirement_id'])}</code>; witness "
                f"<code>{escape(witness['witness_digest'])}</code>; scoped replay binding "
                f"<code>{escape(envelope['campaign_replay_binding_digest'])}</code>.</li>"
            )
        witness_text = "".join(witnesses) or "<li>None accepted for this case.</li>"
        case_sections.append(
            f"<section><h3><code>{escape(case_report['case_id'])}</code></h3>"
            "<table><thead><tr><th scope=\"col\">Candidate</th><th scope=\"col\">Result</th>"
            "<th scope=\"col\">Reason</th><th scope=\"col\">Steps</th>"
            "<th scope=\"col\">Replays</th><th scope=\"col\">Limitations</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><p><strong>Next evidence:</strong> {request_text}</p>"
            f"<p><strong>Replayed witnesses:</strong></p><ul>{witness_text}</ul></section>"
        )
    global_rows = "".join(
        f"<li><code>{escape(item)}</code> — {escape(GLOBAL_LIMITATION_MEANINGS[item])}</li>"
        for item in result["global_limitations"]
    )
    report_explanations = {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"^- `([^`]+)`: \d+ candidate\(s\) — (.+)$",
            campaign["report_text"],
            flags=re.MULTILINE,
        )
    }
    limitation_rows = "".join(
        "<tr>"
        f"<th scope=\"row\"><code>{escape(row['code'])}</code></th>"
        f"<td>{row['count']}</td><td>{escape(report_explanations.get(row['code'], 'Meaning unavailable'))}</td></tr>"
        for row in result["limitation_counts"]
    )
    abstention_rows = "".join(
        "<tr>"
        f"<th scope=\"row\"><code>{escape(row['code'])}</code></th>"
        f"<td>{row['count']}</td><td>{escape(report_explanations.get(row['code'], 'Meaning unavailable'))}</td></tr>"
        for row in result["abstention_reason_counts"]
    )
    interpretation = "".join(
        f"<tr><th scope=\"row\">{escape(key)}</th><td><code>{escape(value)}</code></td></tr>"
        for key, value in result["operator_interpretation"].items()
    )
    body = f"""
<h1>Phase B — Exact operator report comprehension</h1>
<p class="banner">R3 SYNTHETIC CAMPAIGN — NON-AUTHORITATIVE — DECISION EFFECT: NONE</p>
<p>This view is bound to operator-report SHA-256 <code>{escape(EXPECTED_FILE_DIGESTS['operator-report.md'])}</code>. It adds the eight global limitations omitted from the original Markdown projection. Raw machine JSON is not needed.</p>
<h2>Accessible case and candidate results</h2>{''.join(case_sections)}
<h2>Campaign-global limitations — retain all eight</h2><ul>{global_rows}</ul>
<h2>Observed candidate limitation meanings</h2><table><thead><tr><th scope="col">Code</th><th scope="col">Count</th><th scope="col">Plain-language meaning</th></tr></thead><tbody>{limitation_rows}</tbody></table>
<h2>Abstention reason meanings</h2><table><thead><tr><th scope="col">Code</th><th scope="col">Count</th><th scope="col">Plain-language meaning</th></tr></thead><tbody>{abstention_rows}</tbody></table>
<h2>Operator interpretation</h2><table><tbody>{interpretation}</tbody></table>
<h2>Fixed product and decision boundary</h2><ul><li>Release 2: <code>{escape(boundary['release_2'])}</code></li><li>QCP-001: <code>{escape(boundary['qcp_001']['qualification_state'])} / {escape(boundary['qcp_001']['execution_state'])}</code></li><li>Runtime: <code>{escape(boundary['runtime'])}</code></li><li>Release 3: <code>{escape(boundary['release_3'])}</code></li><li>Decision effect: <code>NONE</code>; selected candidate and feasibility verdict remain <code>null</code>.</li></ul>
<h2>Unresolved authority handoffs</h2><ul><li><code>R2-AUTH-001</code>: selection receipt <code>null</code>; evidence collection started <code>{str(handoffs['R2-AUTH-001']['evidence_collection_started']).lower()}</code>.</li><li><code>R2-AUTH-002</code>: Stage A plan and Stage B adequacy receipts <code>null</code>; workload collection started <code>{str(handoffs['R2-AUTH-002']['workload_evidence_collection_started']).lower()}</code>.</li><li><code>R2-AUTH-004</code>: profile <code>{escape(handoffs['R2-AUTH-004']['profile_state'])}</code>; implementation and operational receipts <code>null</code>; real keys/signatures created <code>{str(handoffs['R2-AUTH-004']['real_keys_or_signatures_created']).lower()}</code>.</li></ul><p>Every accountable value requires a future authenticated external update. This study neither fills a value nor starts collection.</p>
<p class="warning">Synthetic cases are not R2-AUTH-002 representative-workload evidence. Digests and replay are not R2-AUTH-004 trust/custody evidence. “None emitted” is not “no evidence needed.”</p>
<details><summary>Exact bound Markdown operator report</summary><pre class="card" style="white-space:pre-wrap">{escape(campaign['report_text'])}</pre></details>
<p><a href="05-response.html">Open the Phase B response form</a></p>
"""
    return _page("Phase B — Exact report", body)


def _phase_b_response(campaign: dict[str, Any], ground_truth: dict[str, Any]) -> str:
    result = campaign["result"]
    cases = [row["case_id"] for row in result["case_reports"]]
    candidates = [row["candidate_id"] for case in result["case_reports"] for row in case["discovery_result"]["candidate_results"]]
    steps = [
        step["step_id"]
        for case in campaign["input"]["cases"]
        for candidate in case["candidates"]
        for step in candidate["steps"]
    ]
    requirements = [item["requirement_id"] for case in campaign["input"]["cases"] for item in case["requirements"]]
    candidate_fields = []
    candidate_input_ids: dict[str, str] = {}
    for index, candidate in enumerate(candidates):
        input_id = f"limits-{index}"
        candidate_input_ids[candidate] = input_id
        candidate_fields.append(
            f"<label><code>{escape(candidate)}</code> limitations — one code per line "
            f"<textarea id=\"{input_id}\" data-list required maxlength=\"8192\" "
            "placeholder=\"Copy every applicable code, one per line\"></textarea></label>"
        )
    global_fields = (
        '<label>All campaign-global limitations — one code per line '
        '<textarea id="global-limitations" data-list required maxlength="8192" '
        'placeholder="Copy all eight codes, one per line"></textarea></label>'
    )
    next_fields = []
    next_input_ids: dict[str, str] = {}
    for index, case in enumerate(cases):
        input_id = f"next-{index}"
        next_input_ids[case] = input_id
        next_fields.append(
            f"<label><code>{escape(case)}</code> next evidence — one ID per line; enter "
            f"<code>__NONE_EMITTED__</code> when the report emits none <textarea id=\"{input_id}\" "
            "data-list required maxlength=\"8192\"></textarea></label>"
        )
    authority_fields = "".join(
        f'<label>{item} <select id="authority-{item}" required>{_options(["participant-filled","null"])}</select></label>'
        for item in ("R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004")
    )
    body = f"""
<h1>Phase B response</h1><p>Reuse the exact participant code from Phase A.</p>
<p>Prompt codes: P0 no help; P1 navigation only; P2 conceptual hint; P3 answer disclosure. Confirm the code with the moderator.</p>
<noscript><p class="warning">JavaScript is unavailable. Use <a href="RESPONSE-WORKSHEET.md">the Phase B response worksheet</a>, preserve its original bytes, and lock it directly with the source tool. Do not transcribe or replace it.</p></noscript>
<form onsubmit="downloadResponse(event)">
<h2>1 of 5 — Session and finding identity</h2>
<label>Participant code <input id="participant" required maxlength="32" pattern="[A-Za-z0-9][A-Za-z0-9._-]{{0,31}}"></label>
<label>Highest prompt received <select id="prompt" required>{_options(['P0','P1','P2','P3'])}</select></label>
<label>Case <select id="case" required>{_options(cases)}</select></label>
<label>Candidate <select id="candidate" required>{_options(candidates)}</select></label>
<label>Step <select id="step" required>{_options(sorted(set(steps)))}</select></label>
<label>Action <select id="action" required>{_options(['path_lost','shut_link:A:Gi0/1','unsupported'])}</select></label>
<label>Requirement <select id="requirement" required>{_options(sorted(set(requirements)))}</select></label>
<label>Result <select id="result" required>{_options(['SUPPORT','ABSTENTION','COUNTEREXAMPLE'])}</select></label>
<h2>2 of 5 — Limitation and next-evidence retention</h2>
{global_fields}
{''.join(candidate_fields)}{''.join(next_fields)}
<h2>3 of 5 — Fixed product and authority boundaries</h2>
<fieldset><legend>Product boundaries</legend>
<label>Release 2 <select id="release2" required>{_options(['COMPLETE',str(EXPECTED_BOUNDARY['release_2'])])}</select></label>
<label>QCP-001 qualification <select id="qcpqual" required>{_options(['QUALIFIED','EXPERIMENTAL'])}</select></label>
<label>QCP-001 execution <select id="qcpexec" required>{_options(['EXECUTABLE','CONTRACT_ONLY'])}</select></label>
<label>Runtime <select id="runtime" required>{_options(['COMPLETE',str(EXPECTED_BOUNDARY['runtime'])])}</select></label>
<label>Release 3 <select id="release3" required>{_options(['PREVIEW',str(EXPECTED_BOUNDARY['release_3'])])}</select></label></fieldset>
<fieldset><legend>Authority placeholders</legend>{authority_fields}</fieldset>
<h2>4 of 5 — Counterexample, replay, and abstention meaning</h2>
<label>Replay meaning <select id="replay" required>{_options(['CANDIDATE_SUPPORT','REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY','TRUST_CUSTODY_PROOF'])}</select></label>
<label>Abstention meaning <select id="abstention" required>{_options(['FAILED_CANDIDATE','SAFE_TO_ADVANCE','NO_SUPPORT_OR_SAFETY_INFERENCE'])}</select></label>
<label>Authority action <select id="authority-action" required>{_options(['START_COLLECTION','LEAVE_NULL_AWAIT_AUTHENTICATED_EXTERNAL_UPDATE_NO_COLLECTION','FILL_FROM_OPERATOR_JUDGMENT'])}</select></label>
{_nonclaim_fields()}{_claims_fields()}
<h2>5 of 5 — Explanations and review</h2>
<label>Explain replay in your own words <textarea id="replay-explanation" data-narrative required minlength="20" maxlength="8192"></textarea></label>
<label>Explain why abstention is not support <textarea id="abstention-explanation" data-narrative required minlength="20" maxlength="8192"></textarea></label>
<label>Explain the decision consequence of retained limitations <textarea id="limitations-explanation" data-narrative required minlength="20" maxlength="8192"></textarea></label>
<label>Explain the next-evidence requests and “none emitted” <textarea id="next-explanation" data-narrative required minlength="20" maxlength="8192"></textarea></label>
<button type="submit">Download locked Phase B response</button><p id="saved" role="status"></p></form>
"""
    candidate_inputs = _js_json(candidate_input_ids)
    next_inputs = _js_json(next_input_ids)
    expression = f"""(()=>{{const candidateLimitations={{}};for(const [id,input] of Object.entries({candidate_inputs})){{candidateLimitations[id]=parseList(input);}}const next={{}};for(const [id,input] of Object.entries({next_inputs})){{next[id]=parseList(input);}}const placeholders={{}};for(const id of ['R2-AUTH-001','R2-AUTH-002','R2-AUTH-004']){{placeholders[id]=document.getElementById(`authority-${{id}}`).value==='null'?null:'participant-filled';}}return {{schema:'atlas.r3-qdp001-operator-study-response/1',study_id:STUDY_ID,phase:'B',participant_code:document.getElementById('participant').value,campaign_input_digest:CAMPAIGN_DIGEST,prompt_code:document.getElementById('prompt').value,case_id:document.getElementById('case').value,candidate_id:document.getElementById('candidate').value,step_id:document.getElementById('step').value,action:document.getElementById('action').value,requirement_id:document.getElementById('requirement').value,result_kind:document.getElementById('result').value,global_limitations:parseList('global-limitations'),candidate_limitations:candidateLimitations,next_evidence_by_case:next,product_boundary:{{qcp_001:{{execution_state:document.getElementById('qcpexec').value,qualification_state:document.getElementById('qcpqual').value}},release_2:document.getElementById('release2').value,release_3:document.getElementById('release3').value,runtime:document.getElementById('runtime').value}},authority_placeholders:placeholders,replay_meaning:document.getElementById('replay').value,abstention_meaning:document.getElementById('abstention').value,authority_action:document.getElementById('authority-action').value,replay_nonclaims:values('nonclaim'),forbidden_claims:claims(),replay_explanation:document.getElementById('replay-explanation').value,abstention_explanation:document.getElementById('abstention-explanation').value,limitations_explanation:document.getElementById('limitations-explanation').value,next_evidence_explanation:document.getElementById('next-explanation').value}};}})()"""
    return _page("Phase B response", body, _download_script("B", expression))


def _brief() -> str:
    body = """
<h1>Break This Plan — participant brief</h1>
<p class="banner">FORMATIVE SYNTHETIC COMPREHENSION STUDY — NOT ACCEPTANCE</p>
<p>You will complete two stages. Phase A tests neutral plan diagnosis. Lock that response before the moderator releases Phase B, which tests exact report comprehension.</p>
<ul><li>Use a pseudonymous participant code.</li><li>Do not use customer or device data.</li><li>Do not open raw JSON, the researcher capsule, or Phase B early.</li><li>No timer is forced; report accessibility accommodations to the moderator.</li></ul>
<p>Nothing in this study selects a candidate, authorizes evidence collection, updates authority, qualifies QCP-001, or promotes a release.</p>
<p><a href="02-neutral-plan.html">Begin Phase A</a></p>
"""
    return _page("Participant brief", body)


def _debrief(ground_truth: dict[str, Any], campaign: dict[str, Any]) -> str:
    phase_a = ground_truth["phase_a"]
    witness = ground_truth["witness"]
    global_rows = "".join(
        f"<li><code>{escape(item)}</code> — {escape(GLOBAL_LIMITATION_MEANINGS[item])}</li>"
        for item in campaign["result"]["global_limitations"]
    )
    next_rows = "".join(
        f"<li><code>{escape(case_id)}</code>: "
        + ", ".join(f"<code>{escape(item)}</code>" for item in requests)
        + "</li>"
        for case_id, requests in ground_truth["phase_b"]["next_evidence_by_case"].items()
    )
    body = f"""
<h1>Debrief</h1><p class="banner">STUDY COMPLETION HAS DECISION EFFECT: NONE</p>
<p>The demonstrated finding is one replayed synthetic observed-discard counterexample. Abstentions are unknown states, not support or safety. Every authority placeholder remains unresolved and must be supplied only by a future authenticated external update.</p>
<h2>Answer reconciliation</h2><ul><li>Neutral plan: <code>{escape(phase_a['unsafe_plan_alias'])}</code></li><li>First unsafe step: <code>{escape(phase_a['unsafe_step_alias'])}</code></li><li>Affected requirement: <code>{escape(phase_a['affected_requirement_alias'])}</code></li><li>Exact source mapping: <code>{escape(witness['candidate_id'])}</code> → <code>{escape(witness['step_id'])}</code> → <code>{escape(witness['requirement_id'])}</code>.</li></ul>
<h2>Campaign-global limitations</h2><ul>{global_rows}</ul>
<h2>Next-evidence mapping</h2><ul>{next_rows}</ul><p><code>__NONE_EMITTED__</code> means the machine emitted no identifier for that case; it never means that no further evidence is needed.</p>
<ul><li>Release 2: <code>{EXPECTED_BOUNDARY['release_2']}</code></li><li>QCP-001: <code>EXPERIMENTAL / CONTRACT_ONLY</code></li><li>Runtime: <code>{EXPECTED_BOUNDARY['runtime']}</code></li><li>Release 3: <code>{EXPECTED_BOUNDARY['release_3']}</code></li></ul>
<p>This session is not approval, representative-workload evidence, trust/custody evidence, qualification, promotion, publication, release acceptance, shipment, or GA.</p>
"""
    return _page("Study debrief", body)


def _markdown_phase_a(alias_data: dict[str, Any]) -> str:
    lines = ["# Phase A neutral plan stimulus", "", "Synthetic, non-authoritative. Decision effect: NONE.", ""]
    scenario = next(
        case for case in alias_data["cases"] if case["source_id"].endswith("unsafe-middle")
    )
    lines.extend(
        [
            "Scenario context:",
            "- Node A reaches the required destination network through next-hop owner Y over A/Gi0/1.",
            "- Node Z serves only an unrelated synthetic network.",
            "- The required flow starts at 10.0.1.1 and must continue to 10.0.5.50.",
            "- No model verdict, witness, exact semantic ID, or answer-bearing observation is shown.",
            "",
        ]
    )
    for case in [scenario]:
        lines.extend([f"## {case['alias']}", "", "Requirements:"])
        lines.extend(f"- {item['alias']}: {_requirement_text(item)}" for item in case["requirements"])
        for candidate in case["candidates"]:
            lines.extend(["", f"### {candidate['alias']}"])
            lines.extend(
                f"{index}. {item['alias']}: {_action_text(item['action'], item['parameters'])}"
                for index, item in enumerate(candidate["steps"], 1)
            )
    return "\n".join(lines) + "\n"


def _markdown_phase_b(campaign: dict[str, Any]) -> str:
    lines = [campaign["report_text"].rstrip(), "", "## Campaign-global limitations", ""]
    lines.extend(f"- `{item}`" for item in campaign["result"]["global_limitations"])
    lines.extend(["", "## Operator interpretation", ""])
    lines.extend(
        f"- `{key}`: `{value}`" for key, value in campaign["result"]["operator_interpretation"].items()
    )
    lines.extend(
        [
            "",
            "Synthetic cases are not R2-AUTH-002 representative-workload evidence. Replay digests are not R2-AUTH-004 trust/custody evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


WORKSHEET_FENCE = "```atlas-response-json"
WORKSHEET_PLACEHOLDER = "__REQUIRED_RESPONSE__"


def _blank_worksheet_response(phase: str, campaign: dict[str, Any]) -> dict[str, Any]:
    fixed = {
        "schema": scoring.RESPONSE_SCHEMA,
        "study_id": STUDY_ID,
        "phase": phase,
        "participant_code": WORKSHEET_PLACEHOLDER,
        "campaign_input_digest": EXPECTED_FILE_DIGESTS["campaign-input.json"],
        "prompt_code": WORKSHEET_PLACEHOLDER,
    }
    if phase == "A":
        return {
            **fixed,
            "prior_exposure": WORKSHEET_PLACEHOLDER,
            "voluntary_consent": WORKSHEET_PLACEHOLDER,
            "data_handling_acknowledged": WORKSHEET_PLACEHOLDER,
            "unsafe_plan_alias": WORKSHEET_PLACEHOLDER,
            "unsafe_step_alias": WORKSHEET_PLACEHOLDER,
            "affected_requirement_alias": WORKSHEET_PLACEHOLDER,
            "explanation": WORKSHEET_PLACEHOLDER,
        }
    if phase != "B":
        _reject("WORKSHEET_PHASE_INVALID")
    result = campaign["result"]
    candidate_ids = [
        row["candidate_id"]
        for case in result["case_reports"]
        for row in case["discovery_result"]["candidate_results"]
    ]
    case_ids = [case["case_id"] for case in result["case_reports"]]
    return {
        **fixed,
        "case_id": WORKSHEET_PLACEHOLDER,
        "candidate_id": WORKSHEET_PLACEHOLDER,
        "step_id": WORKSHEET_PLACEHOLDER,
        "action": WORKSHEET_PLACEHOLDER,
        "requirement_id": WORKSHEET_PLACEHOLDER,
        "result_kind": WORKSHEET_PLACEHOLDER,
        "global_limitations": [WORKSHEET_PLACEHOLDER],
        "candidate_limitations": {
            item: [WORKSHEET_PLACEHOLDER] for item in candidate_ids
        },
        "next_evidence_by_case": {
            item: [WORKSHEET_PLACEHOLDER] for item in case_ids
        },
        "product_boundary": {
            "qcp_001": {
                "execution_state": WORKSHEET_PLACEHOLDER,
                "qualification_state": WORKSHEET_PLACEHOLDER,
            },
            "release_2": WORKSHEET_PLACEHOLDER,
            "release_3": WORKSHEET_PLACEHOLDER,
            "runtime": WORKSHEET_PLACEHOLDER,
        },
        "authority_placeholders": {
            item: WORKSHEET_PLACEHOLDER
            for item in ("R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004")
        },
        "replay_meaning": WORKSHEET_PLACEHOLDER,
        "abstention_meaning": WORKSHEET_PLACEHOLDER,
        "authority_action": WORKSHEET_PLACEHOLDER,
        "replay_nonclaims": [WORKSHEET_PLACEHOLDER],
        "forbidden_claims": {
            item: WORKSHEET_PLACEHOLDER for item in FORBIDDEN_CLAIM_KEYS
        },
        "replay_explanation": WORKSHEET_PLACEHOLDER,
        "abstention_explanation": WORKSHEET_PLACEHOLDER,
        "limitations_explanation": WORKSHEET_PLACEHOLDER,
        "next_evidence_explanation": WORKSHEET_PLACEHOLDER,
    }


def response_to_worksheet_bytes(phase: str, response: dict[str, Any]) -> bytes:
    expected = scoring.PHASE_A_KEYS if phase == "A" else scoring.PHASE_B_KEYS
    if type(response) is not dict or set(response) != set(expected):
        _reject("WORKSHEET_RESPONSE_SHAPE_INVALID")
    body = json.dumps(
        response,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    guidance = (
        "Choose prompt_code from P0/P1/P2/P3, prior_exposure from NO/YES/UNKNOWN, "
        "and set both acknowledgement booleans to true only after reading and consenting."
        if phase == "A"
        else (
            "Copy exact report values. replay_nonclaims choices: "
            + ", ".join(REPLAY_NONCLAIMS)
            + ". Answer every forbidden_claims boolean independently. Use "
            "__NONE_EMITTED__ only for a case where the report emits no identifier."
        )
    )
    return (
        f"# Phase {phase} response worksheet — no JavaScript\n\n"
        "Edit every `__REQUIRED_RESPONSE__` value. Preserve this original file. "
        "The fenced response is parsed without transcription or field remapping.\n\n"
        f"{guidance}\n\n"
        f"{WORKSHEET_FENCE}\n{body}\n```\n"
    ).encode("utf-8")


def _contains_worksheet_placeholder(value: Any) -> bool:
    if value == WORKSHEET_PLACEHOLDER:
        return True
    if type(value) is list:
        return any(_contains_worksheet_placeholder(item) for item in value)
    if type(value) is dict:
        return any(_contains_worksheet_placeholder(item) for item in value.values())
    return False


def parse_worksheet_response_bytes(
    raw: bytes,
    *,
    expected_phase: str,
) -> tuple[bytes, dict[str, Any]]:
    if not raw or len(raw) > scoring.MAX_RESPONSE_BYTES:
        _reject("WORKSHEET_BYTE_LIMIT_OR_EMPTY")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject("WORKSHEET_UTF8_INVALID")
    marker = WORKSHEET_FENCE + "\n"
    if text.count(marker) != 1 or text.count("\n```\n") != 1:
        _reject("WORKSHEET_FENCE_INVALID")
    payload = text.split(marker, 1)[1].split("\n```", 1)[0].encode("utf-8")
    try:
        value = scoring.parse_json_bytes(payload)
    except scoring.StudyScoringError:
        _reject("WORKSHEET_RESPONSE_INVALID")
    expected_keys = (
        scoring.PHASE_A_KEYS if expected_phase == "A" else scoring.PHASE_B_KEYS
    )
    if (
        type(value) is not dict
        or set(value) != set(expected_keys)
        or value.get("phase") != expected_phase
        or value.get("schema") != scoring.RESPONSE_SCHEMA
        or value.get("study_id") != STUDY_ID
        or value.get("campaign_input_digest")
        != EXPECTED_FILE_DIGESTS["campaign-input.json"]
        or _contains_worksheet_placeholder(value)
    ):
        _reject("WORKSHEET_RESPONSE_INVALID")
    canonical = scoring.canonical_json_bytes(value)
    return canonical, value


def _phase_a_worksheet(campaign: dict[str, Any]) -> str:
    return response_to_worksheet_bytes(
        "A", _blank_worksheet_response("A", campaign)
    ).decode("utf-8")


def _phase_b_worksheet(campaign: dict[str, Any]) -> str:
    return response_to_worksheet_bytes(
        "B", _blank_worksheet_response("B", campaign)
    ).decode("utf-8")


def _response_schema(
    phase: str,
    campaign: dict[str, Any],
    alias_data: dict[str, Any],
) -> dict[str, Any]:
    keys = sorted(scoring.PHASE_A_KEYS if phase == "A" else scoring.PHASE_B_KEYS)
    common = {
        "schema": {"const": scoring.RESPONSE_SCHEMA},
        "study_id": {"const": STUDY_ID},
        "phase": {"const": phase},
        "participant_code": {
            "type": "string",
            "minLength": 1,
            "maxLength": 32,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$",
        },
        "campaign_input_digest": {
            "const": EXPECTED_FILE_DIGESTS["campaign-input.json"]
        },
        "prompt_code": {"enum": ["P0", "P1", "P2", "P3"]},
    }
    narrative = {"type": "string", "minLength": 20, "maxLength": 8192}
    if phase == "A":
        scenario = next(
            case for case in alias_data["cases"] if case["source_id"].endswith("unsafe-middle")
        )
        common.update(
            {
                "prior_exposure": {"enum": ["NO", "YES", "UNKNOWN"]},
                "voluntary_consent": {"const": True},
                "data_handling_acknowledged": {"const": True},
                "unsafe_plan_alias": {
                    "enum": [item["alias"] for item in scenario["candidates"]]
                },
                "unsafe_step_alias": {
                    "enum": [
                        step["alias"]
                        for item in scenario["candidates"]
                        for step in item["steps"]
                    ]
                },
                "affected_requirement_alias": {
                    "enum": [item["alias"] for item in scenario["requirements"]]
                },
                "explanation": narrative,
            }
        )
    else:
        result = campaign["result"]
        case_ids = [row["case_id"] for row in result["case_reports"]]
        candidate_ids = [
            row["candidate_id"]
            for case in result["case_reports"]
            for row in case["discovery_result"]["candidate_results"]
        ]
        step_ids = sorted(
            {
                step["step_id"]
                for case in campaign["input"]["cases"]
                for candidate in case["candidates"]
                for step in candidate["steps"]
            }
        )
        requirement_ids = sorted(
            {
                item["requirement_id"]
                for case in campaign["input"]["cases"]
                for item in case["requirements"]
            }
        )
        limitation_values = sorted(
            [row["code"] for row in result["limitation_counts"]]
            + ["UNSUPPORTED_EXTRA_LIMITATION"]
        )
        next_values = sorted(result["next_evidence_requests"]) + [
            "__NONE_EMITTED__",
            "R2-AUTH-004:invented",
        ]
        common.update(
            {
                "case_id": {"enum": case_ids},
                "candidate_id": {"enum": candidate_ids},
                "step_id": {"enum": step_ids},
                "action": {"enum": ["shut_link:A:Gi0/1", "path_lost", "unsupported"]},
                "requirement_id": {"enum": requirement_ids},
                "result_kind": {"enum": ["COUNTEREXAMPLE", "ABSTENTION", "SUPPORT"]},
                "replay_meaning": {
                    "enum": [
                        "REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY",
                        "CANDIDATE_SUPPORT",
                        "TRUST_CUSTODY_PROOF",
                    ]
                },
                "abstention_meaning": {
                    "enum": [
                        "NO_SUPPORT_OR_SAFETY_INFERENCE",
                        "SAFE_TO_ADVANCE",
                        "FAILED_CANDIDATE",
                    ]
                },
                "authority_action": {
                    "enum": [
                        "LEAVE_NULL_AWAIT_AUTHENTICATED_EXTERNAL_UPDATE_NO_COLLECTION",
                        "FILL_FROM_OPERATOR_JUDGMENT",
                        "START_COLLECTION",
                    ]
                },
                "replay_nonclaims": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": REPLAY_NONCLAIMS},
                },
                "forbidden_claims": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": FORBIDDEN_CLAIM_KEYS,
                    "properties": {
                        key: {"type": "boolean"} for key in FORBIDDEN_CLAIM_KEYS
                    },
                },
                "global_limitations": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {
                        "enum": result["global_limitations"] + ["REPLAY_PROVES_CUSTODY"]
                    },
                },
                "candidate_limitations": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": candidate_ids,
                    "properties": {
                        item: {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"enum": limitation_values},
                        }
                        for item in candidate_ids
                    },
                },
                "next_evidence_by_case": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": case_ids,
                    "properties": {
                        item: {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"enum": next_values},
                        }
                        for item in case_ids
                    },
                },
                "product_boundary": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["qcp_001", "release_2", "release_3", "runtime"],
                    "properties": {
                        "qcp_001": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["execution_state", "qualification_state"],
                            "properties": {
                                "execution_state": {"enum": ["CONTRACT_ONLY", "EXECUTABLE"]},
                                "qualification_state": {"enum": ["EXPERIMENTAL", "QUALIFIED"]},
                            },
                        },
                        "release_2": {"enum": [EXPECTED_BOUNDARY["release_2"], "COMPLETE"]},
                        "release_3": {"enum": [EXPECTED_BOUNDARY["release_3"], "PREVIEW"]},
                        "runtime": {"enum": [EXPECTED_BOUNDARY["runtime"], "COMPLETE"]},
                    },
                },
                "authority_placeholders": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004"],
                    "properties": {
                        item: {"enum": [None, "participant-filled"]}
                        for item in ("R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004")
                    },
                },
                "replay_explanation": narrative,
                "abstention_explanation": narrative,
                "limitations_explanation": narrative,
                "next_evidence_explanation": narrative,
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:atlas:r3:qdp001:operator-study:response:{phase.lower()}:1",
        "title": f"Atlas R3 QDP-001 operator study Phase {phase} response",
        "type": "object",
        "additionalProperties": False,
        "required": keys,
        "properties": common,
    }


def _answer_key(ground_truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "atlas.r3-qdp001-operator-study-answer-key/1",
        "study_id": STUDY_ID,
        "campaign_input_digest": EXPECTED_FILE_DIGESTS["campaign-input.json"],
        "phase_a": ground_truth["phase_a"],
        "phase_b": ground_truth["phase_b"],
        "replay_nonclaims": REPLAY_NONCLAIMS,
        "forbidden_claim_keys": FORBIDDEN_CLAIM_KEYS,
    }


def _base_response(answer: dict[str, Any], phase: str) -> dict[str, Any]:
    common: dict[str, Any] = {
        "schema": "atlas.r3-qdp001-operator-study-response/1",
        "study_id": STUDY_ID,
        "phase": phase,
        "participant_code": "SYNTHETIC-DRY-RUN",
        "campaign_input_digest": EXPECTED_FILE_DIGESTS["campaign-input.json"],
        "prompt_code": "P0",
    }
    if phase == "A":
        common.update(
            {
                "prior_exposure": "NO",
                "voluntary_consent": True,
                "data_handling_acknowledged": True,
                **answer["phase_a"],
                "explanation": "Step D3.2 shuts the required path interface and demonstrates the modeled violation.",
            }
        )
    else:
        common.update(
            {
                "replay_nonclaims": REPLAY_NONCLAIMS,
                "forbidden_claims": {
                    item: False for item in FORBIDDEN_CLAIM_KEYS
                },
                **deepcopy(answer["phase_b"]),
                "replay_explanation": "Replay reproduced only the same synthetic observed-discard witness under the bound case.",
                "abstention_explanation": "Abstention is unresolved evidence, not candidate support, safety, or permission to advance.",
                "limitations_explanation": "Every candidate and campaign limitation remains attached and prevents positive or promoting conclusions.",
                "next_evidence_explanation": "Use the exact emitted identifiers; none emitted still means evidence remains incomplete.",
            }
        )
    return common


VERIFY_SCRIPT = r'''"""Verify the closed operator-study package without network access."""
from __future__ import annotations
import hashlib, json, os, stat
from pathlib import Path, PurePosixPath
import sys

ROOT=Path(__file__).resolve().parent
def digest(raw): return "sha256:"+hashlib.sha256(raw).hexdigest()
def fail(code): print("FAIL",code); raise SystemExit(2)
def read(path,max_bytes=32*1024*1024):
    try:
        pi=path.lstat(); rp=getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0)
        if not stat.S_ISREG(pi.st_mode) or path.is_symlink() or bool(getattr(pi,"st_file_attributes",0)&rp) or not 0<pi.st_size<=max_bytes or pi.st_nlink!=1: fail("FILE_NOT_BOUNDED_REGULAR")
        with path.open("rb",buffering=0) as h:
            before=os.fstat(h.fileno()); chunks=[]; remaining=max_bytes+1
            while remaining:
                chunk=h.read(min(1048576,remaining))
                if not chunk: break
                chunks.append(chunk); remaining-=len(chunk)
            if h.read(1): fail("FILE_BYTE_LIMIT")
            after=os.fstat(h.fileno())
        fi=path.lstat(); raw=b"".join(chunks)
    except OSError: fail("FILE_UNREADABLE")
    ids={(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns) for x in (pi,before,after,fi)}
    if len(ids)!=1 or len(raw)!=before.st_size or path.is_symlink() or bool(getattr(fi,"st_file_attributes",0)&rp) or any(x.st_nlink!=1 for x in (before,after,fi)): fail("FILE_CHANGED_DURING_READ")
    return raw
def load(path):
    pairs=[]
    def hook(items):
        out={}
        for key,value in items:
            if key in out: fail("DUPLICATE_JSON_KEY")
            out[key]=value
        return out
    try: value=json.loads(read(path,4*1024*1024).decode("utf-8"),object_pairs_hook=hook)
    except (UnicodeError,json.JSONDecodeError,RecursionError): fail("JSON_UNREADABLE")
    stack=[(value,0)]; visited=0
    while stack:
        item,depth=stack.pop(); visited+=1
        if depth>64 or visited>100000: fail("JSON_NESTING_OR_NODE_LIMIT")
        if type(item) is dict: stack.extend((child,depth+1) for child in item.values())
        elif type(item) is list: stack.extend((child,depth+1) for child in item)
    return value
manifest=load(ROOT/"study-manifest.json")
if manifest.get("schema")!="atlas.r3-qdp001-operator-study-kit/1": fail("MANIFEST_SCHEMA")
files=manifest.get("files")
if not isinstance(files,dict): fail("MANIFEST_FILES")
expected=set(files)|{"study-manifest.json","SHA256SUMS.txt"}
actual=set(); member_count=0; total_bytes=0
for p in ROOT.rglob("*"):
    try: info=p.lstat()
    except OSError: fail("PACKAGE_MEMBER_UNREADABLE")
    if p.is_symlink() or bool(getattr(info,"st_file_attributes",0)&getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0)): fail("PACKAGE_REPARSE_FORBIDDEN")
    rel=p.relative_to(ROOT)
    if len(rel.parts)>12: fail("PACKAGE_TRAVERSAL_LIMIT")
    if stat.S_ISREG(info.st_mode):
        member_count+=1; total_bytes+=info.st_size
        if member_count>256 or total_bytes>64*1024*1024: fail("PACKAGE_TRAVERSAL_LIMIT")
        actual.add(rel.as_posix())
    elif not stat.S_ISDIR(info.st_mode): fail("PACKAGE_MEMBER_TYPE")
if actual!=expected: fail("PACKAGE_MEMBER_SET")
for name,row in files.items():
    part=PurePosixPath(name)
    if part.is_absolute() or ".." in part.parts: fail("PATH_ESCAPE")
    raw=read(ROOT/Path(*part.parts))
    if len(raw)!=row.get("bytes") or digest(raw)!=row.get("digest"): fail("FILE_BINDING")
lines=read(ROOT/"SHA256SUMS.txt").decode("ascii").splitlines()
expected_lines=[]
for name in sorted(set(files)|{"study-manifest.json"}):
    raw=read(ROOT/Path(*PurePosixPath(name).parts))
    expected_lines.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
if lines!=expected_lines: fail("SHA256SUMS")
participant_roots=[ROOT/"participant-phase-a",ROOT/"participant-phase-b",ROOT/"participant-debrief"]
if any(p.suffix.lower() in {".json",".csv"} for root in participant_roots for p in root.rglob("*")): fail("PARTICIPANT_MACHINE_DATA")
phase_a="\n".join(read(p).decode("utf-8",errors="ignore") for p in (ROOT/"participant-phase-a").rglob("*") if p.is_file())
for token in manifest.get("phase_a_forbidden_tokens",[]):
    if token in phase_a: fail("PHASE_A_ANSWER_CUE")
if manifest.get("authority_placeholders")!={"R2-AUTH-001":None,"R2-AUTH-002":None,"R2-AUTH-004":None}: fail("AUTHORITY_DRIFT")
print("PASS: package hashes, staged capsule boundary, null authority, and Phase A blinding verified")
'''


def _docs(campaign: dict[str, Any]) -> dict[str, bytes]:
    package_status = (
        "READY_TO_RUN_NO_PARTICIPANT_RESULT"
        if EXPECTED_SOURCE["source_state"] == "EXACT_CLEAN_COMMIT"
        else "DIRTY_TEST_PREVIEW_NOT_DELIVERABLE"
    )
    preview_warning = (
        ""
        if EXPECTED_SOURCE["source_state"] == "EXACT_CLEAN_COMMIT"
        else (
            "\n> **TEST PREVIEW ONLY:** source was dirty. This master cannot be used "
            "for a human run, participant delivery, or acceptance claim.\n"
        )
    )
    readme = f"""# Atlas R3 QDP-001 Break This Plan operator-study kit

Status: `{package_status}`
{preview_warning}

## Best next action

Complete the run-specific participant-information configuration, then use the staged CLI.
Release only its standalone Phase A delivery.  Preserve the exact response and create a
Phase A lock receipt before the CLI can emit Phase B.  Lock Phase B before releasing the
debrief.  Never give this researcher-only master kit to a participant.

This is an executable, offline formative comprehension study. No human participant has been run. The included N−1/N/N+1 and hostile fixtures are `SYNTHETIC_DRY_RUN` tooling checks only.

Run package verification:

```powershell
py -3.12 -B verify-study.py
```

Run every stage command from the frozen exact source checkout. Resolve master, stage,
response, lock, and output paths under an explicit run directory outside the source checkout
and outside every protected package/input tree:

```powershell
py -3.12 -B tools/build_atlas_r3_break_this_plan_operator_study.py release-phase-a --master <master-kit> --run-config <run-config.json> --output <phase-a>
py -3.12 -B tools/build_atlas_r3_break_this_plan_operator_study.py lock-phase-a --master <master-kit> --stage <phase-a> --response <original-phase-a-response> --output <phase-a-lock.json>
py -3.12 -B tools/build_atlas_r3_break_this_plan_operator_study.py release-phase-b --master <master-kit> --phase-a-stage <phase-a> --phase-a-response <original-phase-a-response> --phase-a-lock <phase-a-lock.json> --output <phase-b>
py -3.12 -B tools/build_atlas_r3_break_this_plan_operator_study.py lock-phase-b --master <master-kit> --stage <phase-b> --response <original-phase-b-response> --output <phase-b-lock.json>
py -3.12 -B tools/build_atlas_r3_break_this_plan_operator_study.py release-debrief --master <master-kit> --phase-b-stage <phase-b> --phase-b-response <original-phase-b-response> --phase-b-lock <phase-b-lock.json> --output <debrief>
```

From the master-kit directory, score only after Phase B has also been locked:

```powershell
py -3.12 -B researcher-capsule/score_response.py --master <master-kit> --phase-a <original-phase-a-response> --phase-a-stage <phase-a> --phase-a-lock <phase-a-lock.json> --phase-b <original-phase-b-response> --phase-b-stage <phase-b> --phase-b-lock <phase-b-lock.json>
```

The scorer never decides participant acceptance. It checks structured fields and leaves narrative meaning to independent human review.

## Evidence boundary

- Source slice: `{EXPECTED_SOURCE['commit']}` / tree `{EXPECTED_SOURCE['tree']}`.
- Base campaign integration: `{BASE_CAMPAIGN_MERGE}`. No review, check, PR, merge, or
  release state is inherited by this local source slice.
- Synthetic campaign cases are not R2-AUTH-002 representative-workload evidence.
- Replay digests are not R2-AUTH-004 trust/custody evidence.
- Same-process recomputation is consistency evidence only, never independent execution,
  provenance, memory integrity, authentication, or custody.

## Fixed non-promotion state

- Release 2: `{EXPECTED_BOUNDARY['release_2']}`
- QCP-001: `EXPERIMENTAL / CONTRACT_ONLY`
- Runtime: `{EXPECTED_BOUNDARY['runtime']}`
- Release 3: `{EXPECTED_BOUNDARY['release_3']}`

This kit is not approval, selection, collection authority, qualification, promotion, publication, release acceptance, shipment, or GA.
"""
    moderator = """# Moderator guide

1. Confirm the participant is not a QDP-001 contributor; otherwise mark prior exposure and exclude from the primary cohort.
2. Assign a pseudonymous code. Never collect customer, device, credential, or network data.
3. Provide the brief and Phase A only. Use the script verbatim; do not reveal semantic IDs.
4. Record prompt code: P0 none, P1 navigation only, P2 conceptual hint, P3 answer disclosure. Only P0 is unassisted.
5. Confirm voluntary consent and the run-specific data terms. A participant may stop without penalty.
6. Preserve the exact Phase A response bytes and require the canonical lock receipt before releasing Phase B.
7. Provide Phase B report and response. Do not show the researcher capsule.
8. Preserve original responses. Retrospective corrections go in the observer log and never overwrite them.
9. Require two independent narrative reviewers. Freeze both signed-off judgments before either reviewer sees the other; record evidence locations, disagreement, and adjudication.
10. Debrief with the fixed non-promotion and null-authority boundary only after the Phase B lock verifies.

If JavaScript or downloads are unavailable, use the phase `RESPONSE-WORKSHEET.md`.
Preserve and lock the participant's original worksheet bytes directly; the source parser and
scorer consume that fenced response without transcription. If the source tool is unavailable
or refuses the worksheet, stop the automated workflow and record scoring as not run. Never
create a moderator-authored substitute response.

Local timestamps are ordinary study metadata, not trusted time or custody evidence. Recording
is forbidden in this minimum P0 slice.
"""
    rubric = """# Scoring rubric

Critical gates are conjunctive; an average cannot hide a safety contradiction.

- Phase A: exact neutral plan, first unsafe step, and affected requirement.
- Phase B: exact case/candidate/step/action/requirement and `COUNTEREXAMPLE` result.
- Replay: reproduced synthetic observed discard only; at least three nonclaims explained.
- Abstention: explicitly neither support nor a safety inference.
- Limitations: all eight global codes and every candidate-specific set exact; N−1 and N+1 both fail.
- Next evidence: exact per-case identifiers; path-loss must be `__NONE_EMITTED__`, meaning not “no evidence needed.”
- Authority: all three values remain null; no collection starts.
- Fixed boundaries retained exactly.

Any claim of safety/support, selection, representative workload, trust/custody, collection authority, qualification, promotion, publication, acceptance, or GA is a critical failure.

The automated scorer checks structure and exact closed values. Two human reviewers must independently grade narrative explanations as correct/incorrect with evidence locations and freeze their judgments before reconciliation. `participant_pass` remains null until that review. One participant result is not operator acceptance or population validity.
"""
    contamination = """# Contamination checklist

- [ ] Participant did not contribute to QDP-001 and reports no prior exposure.
- [ ] Participant received no handoff, README, raw JSON, answer key, or alias map.
- [ ] Participant information, voluntary consent, and run-specific data terms were completed.
- [ ] Phase B was withheld until exact Phase A bytes and the source-bound lock receipt verified.
- [ ] Moderator prompt code was recorded accurately.
- [ ] Primary responses were not overwritten after retrospective probing.
- [ ] Any think-aloud, translation, or accessibility accommodation was disclosed.
- [ ] No recording occurred.
- [ ] Both narrative reviewers froze independent judgments before reconciliation.
- [ ] Researcher capsule remained inaccessible to the participant.
"""
    summary = """# Formative study summary template

Status: `NOT_RUN` | `SYNTHETIC_DRY_RUN` | `HUMAN_FORMATIVE_RUN`

- Participant denominator:
- P0 unassisted denominator:
- Prior-exposure exclusions:
- Accessibility accommodations:
- Automated critical-check passes / denominator:
- Independent narrative-review passes / denominator:
- Critical failures (preserve every one):
- Reviewer disagreements and adjudication:
- Navigation/findability observations:
- Residual limitations:

Decision effect: `NONE`. Do not label this operator acceptance, qualification, promotion, publication, or GA.
"""
    technical_evidence = f"""# Technical evidence and retained negatives

## Exact local source

- Commit: `{EXPECTED_SOURCE['commit']}`
- Tree: `{EXPECTED_SOURCE['tree']}`
- Parents: {", ".join(f"`{item}`" for item in EXPECTED_SOURCE['parents'])}
- Source state: `{EXPECTED_SOURCE['source_state']}`
- Base campaign merge: `{BASE_CAMPAIGN_MERGE}`
- Campaign input/result/report digests: `{EXPECTED_FILE_DIGESTS}`

The campaign was recomputed from the tracked canonical fixture at this source state.  The
source slice inherits no hosted checks, review, approval, merge, qualification, release, or
publication claim.  Same-process full-mapping agreement catches the confirmed public-return
suppression seams but is not independent execution, installed-code provenance, memory-image
integrity, authentication, trusted time, or custody.

## Retained boundaries

- No human participant result or operator acceptance exists.
- Phase A is only a qualitative single-item baseline and is weakly discriminating.
- Phase B is open book, high burden, and has no save/resume behavior.
- Browser/keyboard source checks are separate from NVDA, Narrator, and other assistive-
  technology execution, which remains run-environment evidence.
- Worst-case wall clock at the 1,024-replay ceiling remains uncharacterized.
- Package, stage, and response-lock digests are unkeyed self-consistency bindings.  A party
  able to rewrite the source and reseal every artifact can manufacture a coherent replacement.

These facts establish no authority, qualification, promotion, publication, release acceptance,
shipment, or GA.
"""
    developer_readme = """# Exact source snapshot

These files are copied from the source state named in `study-manifest.json` for offline review.
The final clean build binds their Git blob identities in the manifest.  A dirty preview is test
evidence only and must not be delivered.  This snapshot is not an installed API, hosted review,
merge, release, or external custody proof.
"""
    return {
        "README.md": readme.encode("utf-8"),
        "researcher-capsule/moderator-guide.md": moderator.encode("utf-8"),
        "researcher-capsule/rubric.md": rubric.encode("utf-8"),
        "researcher-capsule/contamination-checklist.md": contamination.encode("utf-8"),
        "researcher-capsule/study-summary-template.md": summary.encode("utf-8"),
        "researcher-capsule/technical-evidence.md": technical_evidence.encode("utf-8"),
        "developer-source/README.md": developer_readme.encode("utf-8"),
        "researcher-capsule/observer-log.csv": b"participant_code,prompt_code,phase,event,original_response_preserved,reviewer,disposition,notes\n",
    }


def _run_config_template() -> dict[str, Any]:
    required = "__REQUIRED_RUN_INPUT__"
    return {
        "schema": RUN_CONFIG_SCHEMA,
        "run_id": required,
        "participant_code": required,
        "participant_contact": required,
        "withdrawal_contact": required,
        "accessibility_contact": required,
        "purpose": required,
        "session_cap_minutes": 60,
        "data_use": required,
        "data_storage": required,
        "data_access": required,
        "data_retention": required,
        "data_deletion": required,
        "recording_planned": False,
    }


def _narrative_review_template() -> dict[str, Any]:
    required = "__REQUIRED_REVIEW_INPUT__"
    return {
        "schema": "atlas.r3-qdp001-operator-study-narrative-review/1",
        "study_id": STUDY_ID,
        "participant_code": required,
        "reviewer_id": required,
        "independent_before_reconciliation": required,
        "phase_a_response_digest": required,
        "phase_b_response_digest": required,
        "judgments": {
            item: {
                "disposition": required,
                "evidence_location": required,
                "reason": required,
            }
            for item in (
                "phase_a.explanation",
                "phase_b.replay_explanation",
                "phase_b.abstention_explanation",
                "phase_b.limitations_explanation",
                "phase_b.next_evidence_explanation",
                "cross_response_narrative_contradiction_review",
            )
        },
        "frozen_review_digest": None,
    }


def _payloads(campaign: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    alias_data = _aliases(campaign["input"], campaign["result"])
    ground_truth = _ground_truth(alias_data, campaign["result"])
    answer = _answer_key(ground_truth)
    n_a = _base_response(answer, "A")
    n_b = _base_response(answer, "B")
    n_minus_b = deepcopy(n_b)
    n_minus_b["global_limitations"] = n_minus_b["global_limitations"][:-1]
    n_plus_b = deepcopy(n_b)
    n_plus_b["global_limitations"] = sorted(
        n_plus_b["global_limitations"] + ["UNSUPPORTED_EXTRA_LIMITATION"]
    )
    hostile_a = deepcopy(n_a)
    hostile_a["participant_code"] = "../escape"
    hostile_a["unsafe_plan_alias"] = "Plan D1"
    payloads = {
        **_docs(campaign),
        "participant-phase-a/index.html": _brief().encode("utf-8"),
        "participant-phase-a/02-neutral-plan.html": _phase_a_plan(alias_data).encode("utf-8"),
        "participant-phase-a/03-response.html": _phase_a_response(alias_data).encode("utf-8"),
        "participant-phase-a/PLAIN-TEXT.md": _markdown_phase_a(alias_data).encode("utf-8"),
        "participant-phase-a/RESPONSE-WORKSHEET.md": _phase_a_worksheet(campaign).encode("utf-8"),
        "participant-phase-a/START.cmd": b'@start "" "%~dp0index.html"\r\n',
        "participant-phase-b/index.html": _phase_b_report(campaign).encode("utf-8"),
        "participant-phase-b/05-response.html": _phase_b_response(campaign, ground_truth).encode("utf-8"),
        "participant-phase-b/PLAIN-TEXT.md": _markdown_phase_b(campaign).encode("utf-8"),
        "participant-phase-b/RESPONSE-WORKSHEET.md": _phase_b_worksheet(campaign).encode("utf-8"),
        "participant-phase-b/START.cmd": b'@start "" "%~dp0index.html"\r\n',
        "participant-debrief/index.html": _debrief(ground_truth, campaign).encode("utf-8"),
        "participant-debrief/START.cmd": b'@start "" "%~dp0index.html"\r\n',
        "researcher-capsule/answer-key.json": _canonical_json(answer) + b"\n",
        "researcher-capsule/campaign-input.json": campaign["input_raw"],
        "researcher-capsule/campaign-result.json": campaign["result_raw"],
        "researcher-capsule/operator-report.md": campaign["report_raw"],
        "researcher-capsule/run-config.template.json": _canonical_json(
            _run_config_template()
        )
        + b"\n",
        "researcher-capsule/narrative-review.template.json": _canonical_json(
            _narrative_review_template()
        )
        + b"\n",
        "researcher-capsule/source-alias-map.json": _canonical_json(alias_data) + b"\n",
        "researcher-capsule/score_response.py": _read_regular(SCORER_SOURCE),
        "researcher-capsule/fixtures/response-n.phase-a.json": _canonical_json(n_a) + b"\n",
        "researcher-capsule/fixtures/response-n.phase-b.json": _canonical_json(n_b) + b"\n",
        "researcher-capsule/fixtures/response-n-minus-1.phase-b.json": _canonical_json(n_minus_b) + b"\n",
        "researcher-capsule/fixtures/response-n-plus-1.phase-b.json": _canonical_json(n_plus_b) + b"\n",
        "researcher-capsule/fixtures/response-hostile.phase-a.json": _canonical_json(hostile_a) + b"\n",
        "schemas/phase-a-response.schema.json": _canonical_json(
            _response_schema("A", campaign, alias_data)
        )
        + b"\n",
        "schemas/phase-b-response.schema.json": _canonical_json(
            _response_schema("B", campaign, alias_data)
        )
        + b"\n",
        "verify-study.py": VERIFY_SCRIPT.encode("utf-8"),
        "RUN-VERIFY.cmd": b'@py -3.12 -B "%~dp0verify-study.py"\r\n',
        "developer-source/tools/build_atlas_r3_break_this_plan_operator_study.py": _read_regular(
            Path(__file__)
        ),
        "developer-source/tools/atlas_r3_operator_study_scoring.py": _read_regular(
            SCORER_SOURCE
        ),
        "developer-source/tools/run_atlas_r3_break_this_plan_campaign.py": _read_regular(
            REPOSITORY_ROOT / "tools" / "run_atlas_r3_break_this_plan_campaign.py"
        ),
        "developer-source/tests/test_atlas_r3_break_this_plan_campaign.py": _read_regular(
            REPOSITORY_ROOT / "tests" / "test_atlas_r3_break_this_plan_campaign.py"
        ),
        "developer-source/tests/test_atlas_r3_break_this_plan_operator_study.py": _read_regular(
            REPOSITORY_ROOT / "tests" / "test_atlas_r3_break_this_plan_operator_study.py"
        ),
        "developer-source/docs/atlas-release-3-break-this-plan-campaign-contract-2026-08-30.md": _read_regular(
            REPOSITORY_ROOT
            / "docs"
            / "atlas-release-3-break-this-plan-campaign-contract-2026-08-30.md"
        ),
        "developer-source/docs/atlas-release-3-qdp001-operator-study-contract-2026-08-31.md": _read_regular(
            REPOSITORY_ROOT
            / "docs"
            / "atlas-release-3-qdp001-operator-study-contract-2026-08-31.md"
        ),
    }
    return payloads, alias_data, answer


def _safe_rel(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or any(not part for part in path.parts):
        _reject("OUTPUT_MEMBER_PATH_INVALID")
    return path


def _guard_output_separation(output: Path, *protected: Path) -> None:
    try:
        output_resolved = output.resolve(strict=False)
        protected_resolved = [path.resolve(strict=False) for path in protected]
    except OSError:
        _reject("OUTPUT_PATH_UNRESOLVABLE")
    for item in protected_resolved:
        if (
            output_resolved == item
            or output_resolved in item.parents
            or item in output_resolved.parents
        ):
            _reject("OUTPUT_PATH_OVERLAPS_PROTECTED_INPUT")


def _write_member(root: Path, name: str, raw: bytes) -> None:
    if not raw or len(raw) > MAX_OUTPUT_FILE_BYTES:
        _reject("OUTPUT_MEMBER_BYTE_LIMIT_OR_EMPTY")
    rel = _safe_rel(name)
    target = root.joinpath(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        _reject("OUTPUT_MEMBER_COLLISION")
    try:
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        _reject("OUTPUT_WRITE_FAILED")


def _master_payloads_and_manifest(
    campaign: dict[str, Any],
    source: dict[str, Any],
    source_files: list[dict[str, Any]],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    payloads, alias_data, _answer = _payloads(campaign)
    phase_a_forbidden = sorted(
        {
            case["source_id"] for case in alias_data["cases"]
        }
        | {
            candidate["source_id"]
            for case in alias_data["cases"]
            for candidate in case["candidates"]
        }
        | {
            step["source_id"]
            for case in alias_data["cases"]
            for candidate in case["candidates"]
            for step in candidate["steps"]
        }
        | {
            requirement["source_id"]
            for case in alias_data["cases"]
            for requirement in case["requirements"]
        }
        | {
            "unsafe-middle",
            "strand-service-flow",
            "preserve-service-flow",
            "COUNTEREXAMPLE",
            "REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW",
        }
    )
    file_rows = {
        name: {"bytes": len(raw), "digest": _digest(raw)}
        for name, raw in sorted(payloads.items())
    }
    manifest = {
        "schema": STUDY_SCHEMA,
        "study_id": STUDY_ID,
        "status": (
            "READY_TO_RUN_NO_PARTICIPANT_RESULT"
            if source["source_state"] == "EXACT_CLEAN_COMMIT"
            else "DIRTY_TEST_PREVIEW_NOT_DELIVERABLE"
        ),
        "deliverable": source["source_state"] == "EXACT_CLEAN_COMMIT",
        "authoritative": False,
        "decision_effect": "NONE",
        "human_participant_count": 0,
        "operator_acceptance": False,
        "qualification_effect": "NONE",
        "promotion_effect": "NONE",
        "source_campaign": {
            "base_campaign_merge": BASE_CAMPAIGN_MERGE,
            "recomputed_at_source": source,
            "file_digests": deepcopy(EXPECTED_FILE_DIGESTS),
            "subject": "TRACKED_FIXTURE_RECOMPUTED_AT_EXACT_SOURCE",
        },
        "source_files": source_files,
        "local_builder": {
            "state": source["source_state"],
            "builder_digest": _digest(_read_regular(Path(__file__))),
            "scorer_digest": _digest(_read_regular(SCORER_SOURCE)),
        },
        "product_boundary": EXPECTED_BOUNDARY,
        "authority_placeholders": {
            "R2-AUTH-001": None,
            "R2-AUTH-002": None,
            "R2-AUTH-004": None,
        },
        "collection_started": False,
        "global_limitations": EXPECTED_GLOBAL_LIMITATIONS,
        "operator_interpretation": EXPECTED_OPERATOR_INTERPRETATION,
        "participant_distribution": (
            "STANDALONE_PHASE_A_THEN_CANONICAL_LOCK_THEN_STANDALONE_PHASE_B;"
            "PHASE_B_LOCK_THEN_DEBRIEF;NEVER_RESEARCHER_MASTER_KIT"
        ),
        "participant_deliveries_exclude_campaign_result_answer_key_and_researcher_machine_data": True,
        "synthetic_dry_run_is_human_study": False,
        "phase_a_forbidden_tokens": phase_a_forbidden,
        "known_residuals": [
            "NO_HUMAN_PARTICIPANT_RESULT",
            "NO_OPERATOR_ACCEPTANCE",
            "SINGLE_FIXED_SYNTHETIC_CAMPAIGN",
            "PHASE_B_IS_OPEN_BOOK_REPORT_COMPREHENSION",
            "PHASE_A_SINGLE_ITEM_WEAKLY_DISCRIMINATING",
            "PHASE_B_HIGH_BURDEN_NO_SAVE_RESUME",
            "ACCESSIBILITY_WITH_ASSISTIVE_TECHNOLOGY_NOT_VERIFIED",
            "PACKAGE_VERIFIER_IS_UNKEYED_SELF_CONSISTENCY_NOT_AUTHENTICATED_CUSTODY",
            "SAME_PROCESS_RECOMPUTATION_IS_NOT_INDEPENDENT_TRUST_OR_PROVENANCE",
            "LOCAL_SOURCE_SLICE_NOT_PUSHED_REVIEWED_OR_MERGED",
        ],
        "files": file_rows,
    }
    return payloads, manifest


def build(
    output: Path,
    *,
    source_identity: dict[str, Any] | None = None,
    allow_dirty_test_preview: bool = False,
) -> dict[str, Any]:
    _guard_output_separation(output, REPOSITORY_ROOT)
    if output.exists() or output.is_symlink():
        _reject("OUTPUT_ALREADY_EXISTS")
    if not output.parent.exists() or not output.parent.is_dir():
        _reject("OUTPUT_PARENT_INVALID")
    source = (
        _validate_source_identity(source_identity)
        if source_identity is not None
        else _current_source_identity(
            allow_dirty_test_preview=allow_dirty_test_preview
        )
    )
    campaign = _build_source_campaign(source)
    source_files = _source_file_rows(source)
    payloads, manifest = _master_payloads_and_manifest(
        campaign, source, source_files
    )
    manifest_raw = _canonical_json(manifest) + b"\n"
    sums = []
    all_for_sums = {**payloads, "study-manifest.json": manifest_raw}
    for name, raw in sorted(all_for_sums.items()):
        sums.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    sums_raw = ("\n".join(sums) + "\n").encode("utf-8")

    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.partial-",
            dir=output.parent,
        ) as temp_name:
            temp_output = Path(temp_name)
            for name, raw in payloads.items():
                _write_member(temp_output, name, raw)
            _write_member(temp_output, "study-manifest.json", manifest_raw)
            _write_member(temp_output, "SHA256SUMS.txt", sums_raw)
            verify_master_kit(
                temp_output,
                allow_dirty_test_preview=source["source_state"]
                == "DIRTY_TEST_PREVIEW",
            )
            os.replace(temp_output, output)
    except StudyBuildError:
        raise
    except OSError:
        _reject("OUTPUT_CREATE_FAILED")
    return manifest


def _directory_files(root: Path) -> set[str]:
    try:
        root_info = root.lstat()
    except OSError:
        _reject("PACKAGE_DIRECTORY_UNREADABLE")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root.is_symlink()
        or bool(getattr(root_info, "st_file_attributes", 0) & reparse)
    ):
        _reject("PACKAGE_DIRECTORY_INVALID")
    files: set[str] = set()
    count = 0
    total_bytes = 0
    try:
        items = root.rglob("*")
        for item in items:
            try:
                info = item.lstat()
            except OSError:
                _reject("PACKAGE_DIRECTORY_UNREADABLE")
            relative = item.relative_to(root)
            if len(relative.parts) > MAX_PACKAGE_DEPTH:
                _reject("PACKAGE_TRAVERSAL_LIMIT")
            if item.is_symlink() or bool(
                getattr(info, "st_file_attributes", 0) & reparse
            ):
                _reject("PACKAGE_REPARSE_FORBIDDEN")
            if stat.S_ISREG(info.st_mode):
                count += 1
                total_bytes += info.st_size
                if (
                    count > MAX_PACKAGE_FILES
                    or total_bytes > MAX_PACKAGE_TOTAL_BYTES
                ):
                    _reject("PACKAGE_TRAVERSAL_LIMIT")
                name = relative.as_posix()
                _safe_rel(name)
                if name in files:
                    _reject("PACKAGE_MEMBER_COLLISION")
                files.add(name)
            elif not stat.S_ISDIR(info.st_mode):
                _reject("PACKAGE_MEMBER_TYPE_INVALID")
    except StudyBuildError:
        raise
    except OSError:
        _reject("PACKAGE_DIRECTORY_UNREADABLE")
    return files


def _load_canonical_document(
    path: Path,
    *,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular(path, max_bytes=max_bytes)
    body = raw[:-1] if raw.endswith(b"\n") else raw
    value = _parse_json(body)
    if type(value) is not dict or raw not in {body, body + b"\n"}:
        _reject("CANONICAL_DOCUMENT_INVALID")
    return raw, value


def _verify_checksum_list(
    root: Path,
    *,
    members: set[str],
    checksum_name: str = "SHA256SUMS.txt",
) -> None:
    try:
        actual = _read_regular(root / checksum_name).decode("ascii").splitlines()
    except UnicodeDecodeError:
        _reject("CHECKSUM_LIST_INVALID")
    expected = []
    for name in sorted(members):
        raw = _read_regular(root.joinpath(*PurePosixPath(name).parts))
        expected.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    if actual != expected:
        _reject("CHECKSUM_LIST_INVALID")


def verify_master_kit(
    root: Path,
    *,
    allow_dirty_test_preview: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    manifest_raw, manifest = _load_canonical_document(root / "study-manifest.json")
    expected_manifest_keys = {
        "schema",
        "study_id",
        "status",
        "deliverable",
        "authoritative",
        "decision_effect",
        "human_participant_count",
        "operator_acceptance",
        "qualification_effect",
        "promotion_effect",
        "source_campaign",
        "source_files",
        "local_builder",
        "product_boundary",
        "authority_placeholders",
        "collection_started",
        "global_limitations",
        "operator_interpretation",
        "participant_distribution",
        "participant_deliveries_exclude_campaign_result_answer_key_and_researcher_machine_data",
        "synthetic_dry_run_is_human_study",
        "phase_a_forbidden_tokens",
        "known_residuals",
        "files",
    }
    if (
        set(manifest) != expected_manifest_keys
        or manifest.get("schema") != STUDY_SCHEMA
        or manifest.get("study_id") != STUDY_ID
        or manifest.get("status")
        != (
            "READY_TO_RUN_NO_PARTICIPANT_RESULT"
            if manifest.get("deliverable") is True
            else "DIRTY_TEST_PREVIEW_NOT_DELIVERABLE"
        )
        or manifest.get("authoritative") is not False
        or manifest.get("decision_effect") != "NONE"
        or manifest.get("human_participant_count") != 0
        or manifest.get("operator_acceptance") is not False
        or manifest.get("qualification_effect") != "NONE"
        or manifest.get("promotion_effect") != "NONE"
        or manifest.get("collection_started") is not False
        or manifest.get("product_boundary") != EXPECTED_BOUNDARY
        or manifest.get("authority_placeholders")
        != {"R2-AUTH-001": None, "R2-AUTH-002": None, "R2-AUTH-004": None}
        or manifest.get("global_limitations") != EXPECTED_GLOBAL_LIMITATIONS
        or manifest.get("operator_interpretation")
        != EXPECTED_OPERATOR_INTERPRETATION
        or manifest.get("participant_distribution")
        != (
            "STANDALONE_PHASE_A_THEN_CANONICAL_LOCK_THEN_STANDALONE_PHASE_B;"
            "PHASE_B_LOCK_THEN_DEBRIEF;NEVER_RESEARCHER_MASTER_KIT"
        )
        or manifest.get(
            "participant_deliveries_exclude_campaign_result_answer_key_and_researcher_machine_data"
        )
        is not True
        or manifest.get("synthetic_dry_run_is_human_study") is not False
        or type(manifest.get("phase_a_forbidden_tokens")) is not list
        or type(manifest.get("known_residuals")) is not list
    ):
        _reject("MASTER_MANIFEST_INVALID")
    source_campaign = manifest.get("source_campaign")
    if (
        type(source_campaign) is not dict
        or set(source_campaign)
        != {"base_campaign_merge", "recomputed_at_source", "file_digests", "subject"}
        or source_campaign.get("base_campaign_merge") != BASE_CAMPAIGN_MERGE
        or source_campaign.get("subject")
        != "TRACKED_FIXTURE_RECOMPUTED_AT_EXACT_SOURCE"
    ):
        _reject("MASTER_MANIFEST_INVALID")
    source = _validate_source_identity(source_campaign.get("recomputed_at_source"))
    if (
        source["source_state"] != "EXACT_CLEAN_COMMIT"
        and not allow_dirty_test_preview
    ):
        _reject("DIRTY_PREVIEW_NOT_DELIVERABLE")
    _activate_source_identity(source)
    file_digests = source_campaign.get("file_digests")
    if (
        type(file_digests) is not dict
        or set(file_digests)
        != {"campaign-input.json", "campaign-result.json", "operator-report.md"}
        or file_digests.get("campaign-input.json")
        != scoring.EXPECTED_CAMPAIGN_INPUT_DIGEST
    ):
        _reject("MASTER_MANIFEST_INVALID")
    EXPECTED_FILE_DIGESTS.update(file_digests)
    local_builder = manifest.get("local_builder")
    if (
        type(local_builder) is not dict
        or set(local_builder) != {"state", "builder_digest", "scorer_digest"}
        or local_builder.get("state") != source["source_state"]
        or manifest.get("deliverable")
        != (source["source_state"] == "EXACT_CLEAN_COMMIT")
        or local_builder.get("builder_digest")
        != _digest(_read_regular(Path(__file__)))
        or local_builder.get("scorer_digest") != _digest(_read_regular(SCORER_SOURCE))
    ):
        _reject("MASTER_MANIFEST_INVALID")
    source_files = manifest.get("source_files")
    if (
        type(source_files) is not list
        or [row.get("path") for row in source_files if type(row) is dict]
        != list(SOURCE_BINDING_PATHS)
        or source_files != _source_file_rows(source)
    ):
        _reject("MASTER_SOURCE_BINDING_INVALID")
    expected_campaign = _build_source_campaign(source)
    expected_payloads, expected_manifest = _master_payloads_and_manifest(
        expected_campaign,
        source,
        source_files,
    )
    if manifest != expected_manifest:
        _reject("MASTER_SOURCE_REGENERATION_MISMATCH")
    rows = manifest.get("files")
    if type(rows) is not dict:
        _reject("MASTER_MANIFEST_INVALID")
    expected = set(rows) | {"study-manifest.json", "SHA256SUMS.txt"}
    if _directory_files(root) != expected:
        _reject("MASTER_MEMBER_SET_INVALID")
    for name, row in rows.items():
        if type(row) is not dict or set(row) != {"bytes", "digest"}:
            _reject("MASTER_FILE_BINDING_INVALID")
        raw = _read_regular(root.joinpath(*_safe_rel(name).parts))
        if raw != expected_payloads.get(name):
            _reject("MASTER_SOURCE_REGENERATION_MISMATCH")
        if row != {"bytes": len(raw), "digest": _digest(raw)}:
            _reject("MASTER_FILE_BINDING_INVALID")
    _verify_checksum_list(
        root,
        members=set(rows) | {"study-manifest.json"},
    )
    for name in ("campaign-input.json", "campaign-result.json", "operator-report.md"):
        raw = _read_regular(root / "researcher-capsule" / name)
        if _digest(raw) != file_digests[name]:
            _reject("MASTER_CAMPAIGN_BINDING_INVALID")
    answer_row = rows.get("researcher-capsule/answer-key.json")
    if (
        type(answer_row) is not dict
        or answer_row.get("digest") != scoring.EXPECTED_ANSWER_KEY_DIGEST
    ):
        _reject("ANSWER_KEY_SOURCE_ANCHOR_INVALID")
    return manifest_raw, manifest


def _validate_run_config(value: Any) -> dict[str, Any]:
    required_marker = "__REQUIRED_RUN_INPUT__"
    if type(value) is not dict or set(value) != set(RUN_CONFIG_KEYS):
        _reject("RUN_CONFIG_INVALID")
    if value.get("schema") != RUN_CONFIG_SCHEMA:
        _reject("RUN_CONFIG_INVALID")
    if (
        type(value.get("run_id")) is not str
        or IDENTIFIER.fullmatch(value["run_id"]) is None
        or type(value.get("participant_code")) is not str
        or scoring.PARTICIPANT_CODE.fullmatch(value["participant_code"]) is None
        or type(value.get("session_cap_minutes")) is not int
        or type(value.get("session_cap_minutes")) is bool
        or not 15 <= value["session_cap_minutes"] <= 180
        or type(value.get("recording_planned")) is not bool
        or value["recording_planned"] is not False
    ):
        _reject("RUN_CONFIG_INVALID")
    for key in RUN_CONFIG_KEYS - {
        "schema",
        "run_id",
        "participant_code",
        "session_cap_minutes",
        "recording_planned",
    }:
        item = value.get(key)
        lowered = item.lower() if type(item) is str else ""
        if (
            type(item) is not str
            or not 12 <= len(item.strip()) <= 1_024
            or item == required_marker
            or any(ord(char) < 32 and char not in "\n\r\t" for char in item)
            or any(
                token in lowered
                for token in ("http:", "https:", "www.", "mailto:")
            )
            or any(
                token in item
                for token in ("<", ">", "[", "]", "(", ")", "!", "`", "@", "\r", "\n")
            )
        ):
            _reject("RUN_CONFIG_INVALID")
    return deepcopy(value)


def _load_run_config(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular(path, max_bytes=MAX_RUN_CONFIG_BYTES)
    value = _parse_json(raw, require_canonical=False)
    config = _validate_run_config(value)
    return _canonical_json(config), config


def _reject_run_config_answer_cues(
    config: dict[str, Any],
    master_root: Path,
) -> None:
    _answer_raw, answer = _load_canonical_document(
        master_root / "researcher-capsule" / "answer-key.json"
    )
    phase_a = answer.get("phase_a") if type(answer) is dict else None
    if type(phase_a) is not dict:
        _reject("ANSWER_KEY_INVALID")

    def folded(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    cues = {
        folded(str(phase_a.get(key)))
        for key in (
            "unsafe_plan_alias",
            "unsafe_step_alias",
            "affected_requirement_alias",
        )
    } | {
        "correct answer",
        "unsafe answer",
        "choose plan",
        "choose step",
        "counterexample",
        "observed discard",
        "replayable",
        "phase b answer",
    }
    text = "\n".join(
        folded(value)
        for value in config.values()
        if type(value) is str
    )
    if any(cue and cue in text for cue in cues):
        _reject("RUN_CONFIG_ANSWER_CUE")


def _participant_information(config: dict[str, Any]) -> tuple[bytes, bytes]:
    recording = "No recording is planned or permitted in this minimum P0 slice."
    body = f"""
<h1>Participant information</h1>
<p class="banner">FORMATIVE SYNTHETIC STUDY — VOLUNTARY — NOT ACCEPTANCE</p>
<p><strong>Purpose:</strong> {escape(config['purpose'])}</p>
<p>Participation is voluntary. You may pause or stop at any time without penalty. Contact
{escape(config['withdrawal_contact'])} to withdraw or request the handling described below.</p>
<ul>
<li>Session cap: {config['session_cap_minutes']} minutes; no speed score is used.</li>
<li>Participant contact: {escape(config['participant_contact'])}</li>
<li>Accessibility contact: {escape(config['accessibility_contact'])}</li>
<li>Data use: {escape(config['data_use'])}</li>
<li>Storage: {escape(config['data_storage'])}</li>
<li>Access: {escape(config['data_access'])}</li>
<li>Retention: {escape(config['data_retention'])}</li>
<li>Deletion: {escape(config['data_deletion'])}</li>
</ul>
<p>{escape(recording)}</p>
<p>Do not include customer, device, credential, or network data. Nothing in this study
selects a candidate or authorizes collection, qualification, promotion, publication, or GA.</p>
<p><a href="01-study-brief.html">Continue to the study brief</a></p>
"""
    markdown = f"""# Participant information

Purpose: {config['purpose']}

Participation is voluntary. You may pause or stop at any time without penalty.

- Session cap: {config['session_cap_minutes']} minutes; no speed score is used.
- Participant contact: {config['participant_contact']}
- Withdrawal contact: {config['withdrawal_contact']}
- Accessibility contact: {config['accessibility_contact']}
- Data use: {config['data_use']}
- Storage: {config['data_storage']}
- Access: {config['data_access']}
- Retention: {config['data_retention']}
- Deletion: {config['data_deletion']}
- {recording}

Do not include customer, device, credential, or network data. This study has decision
effect NONE and is not acceptance, authority, qualification, promotion, publication, or GA.
"""
    return _page("Participant information", body).encode("utf-8"), markdown.encode(
        "utf-8"
    )


class _StageHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key.lower(): value for key, value in attrs}
        for key in ("href", "src", "action", "formaction", "poster"):
            value = values.get(key)
            if value is not None:
                self.targets.append(value)
        if (
            tag.lower() == "meta"
            and (values.get("http-equiv") or "").lower() == "refresh"
        ):
            self.targets.append(values.get("content") or "")
        if values.get("srcset"):
            self.targets.append(values["srcset"] or "")


def _validate_payload_links(payloads: dict[str, bytes]) -> None:
    members = set(payloads)
    for name, raw in payloads.items():
        if not name.lower().endswith(".html"):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            _reject("STAGE_HTML_UTF8_INVALID")
        lowered = text.casefold()
        if any(
            token in lowered
            for token in (
                "http://",
                "https://",
                "mailto:",
                "javascript:",
                "fetch(",
                "xmlhttprequest",
                "websocket",
                "sendbeacon",
            )
        ) or re.search(r"(?<![a-z0-9_-])url\s*\(", lowered):
            _reject("STAGE_LINK_BOUNDARY_INVALID")
        parser = _StageHtmlParser()
        try:
            parser.feed(text)
            parser.close()
        except (ValueError, TypeError):
            _reject("STAGE_HTML_INVALID")
        for target in parser.targets:
            if target.startswith("#"):
                continue
            if (
                not target
                or "url=" in target.casefold()
                or "," in target
                or target.startswith(("/", "\\", "//"))
                or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)
            ):
                _reject("STAGE_LINK_BOUNDARY_INVALID")
            path_text = target.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
            part = PurePosixPath(path_text)
            if (
                part.is_absolute()
                or ".." in part.parts
                or path_text not in members
            ):
                _reject("STAGE_LINK_BOUNDARY_INVALID")


def _closed_package(
    output: Path,
    *,
    payloads: dict[str, bytes],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        _reject("OUTPUT_ALREADY_EXISTS")
    if not output.parent.is_dir():
        _reject("OUTPUT_PARENT_INVALID")
    _validate_payload_links(payloads)
    rows = {
        name: {"bytes": len(raw), "digest": _digest(raw)}
        for name, raw in sorted(payloads.items())
    }
    manifest = {**manifest, "files": rows}
    manifest_raw = _canonical_json(manifest) + b"\n"
    sums = [
        f"{hashlib.sha256(raw).hexdigest()}  {name}"
        for name, raw in sorted({**payloads, "stage-manifest.json": manifest_raw}.items())
    ]
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.partial-",
            dir=output.parent,
        ) as temp_name:
            temp_output = Path(temp_name)
            for name, raw in payloads.items():
                _write_member(temp_output, name, raw)
            _write_member(temp_output, "stage-manifest.json", manifest_raw)
            _write_member(
                temp_output,
                "SHA256SUMS.txt",
                ("\n".join(sums) + "\n").encode("ascii"),
            )
            verify_stage(temp_output, expected_stage=manifest["stage"])
            os.replace(temp_output, output)
    except StudyBuildError:
        raise
    except OSError:
        _reject("OUTPUT_CREATE_FAILED")
    return manifest


def _base_stage_manifest(
    *,
    stage: str,
    master_raw: bytes,
    master: dict[str, Any],
    run_id: str,
    participant_code: str,
    run_config_digest: str,
    run_config: dict[str, Any],
    predecessor_lock_digest: str | None,
) -> dict[str, Any]:
    return {
        "schema": STAGE_MANIFEST_SCHEMA,
        "stage": stage,
        "study_id": STUDY_ID,
        "authoritative": False,
        "decision_effect": "NONE",
        "authentication": "none",
        "custody_proved": False,
        "trusted_time": False,
        "run_id": run_id,
        "participant_code": participant_code,
        "campaign_input_digest": scoring.EXPECTED_CAMPAIGN_INPUT_DIGEST,
        "master_manifest_digest": _digest(master_raw),
        "run_config_digest": run_config_digest,
        "run_config": deepcopy(run_config),
        "predecessor_lock_digest": predecessor_lock_digest,
    }


def _phase_a_stage_payloads(
    master_root: Path,
    master: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, bytes]:
    info_html, info_md = _participant_information(config)
    prefix = "participant-phase-a/"
    payloads: dict[str, bytes] = {}
    for name in master["files"]:
        if not name.startswith(prefix):
            continue
        short = name.removeprefix(prefix)
        if short == "index.html":
            short = "01-study-brief.html"
        elif short == "START.cmd":
            continue
        payloads[short] = _read_regular(
            master_root.joinpath(*PurePosixPath(name).parts)
        )
    payloads.update(
        {
            "index.html": info_html,
            "PARTICIPANT-INFORMATION.md": info_md,
            "response.schema.json": _read_regular(
                master_root / "schemas" / "phase-a-response.schema.json"
            ),
            "START.cmd": b'@start "" "%~dp0index.html"\r\n',
        }
    )
    phase_a_text = "\n".join(
        raw.decode("utf-8", errors="ignore") for raw in payloads.values()
    )
    for token in master.get("phase_a_forbidden_tokens", []):
        if token in phase_a_text:
            _reject("PHASE_A_ANSWER_CUE")
    if any(
        value in name.lower()
        for name in payloads
        for value in ("phase-b", "debrief", "answer-key", "researcher")
    ):
        _reject("PHASE_A_MEMBER_BOUNDARY_INVALID")
    return payloads


def _static_stage_payloads(
    master_root: Path,
    master: dict[str, Any],
    *,
    stage: str,
) -> dict[str, bytes]:
    prefix = {
        "PHASE_B": "participant-phase-b/",
        "DEBRIEF": "participant-debrief/",
    }.get(stage)
    if prefix is None:
        _reject("STAGE_MANIFEST_INVALID")
    payloads = {
        name.removeprefix(prefix): _read_regular(
            master_root.joinpath(*PurePosixPath(name).parts)
        )
        for name in master["files"]
        if name.startswith(prefix)
    }
    if stage == "PHASE_B":
        payloads["response.schema.json"] = _read_regular(
            master_root / "schemas" / "phase-b-response.schema.json"
        )
    return payloads


def release_phase_a(
    master_root: Path,
    run_config_path: Path,
    output: Path,
    *,
    allow_dirty_test_preview: bool = False,
) -> dict[str, Any]:
    _guard_output_separation(
        output,
        REPOSITORY_ROOT,
        master_root,
        run_config_path,
    )
    master_raw, master = verify_master_kit(
        master_root, allow_dirty_test_preview=allow_dirty_test_preview
    )
    config_raw, config = _load_run_config(run_config_path)
    _reject_run_config_answer_cues(config, master_root)
    payloads = _phase_a_stage_payloads(master_root, master, config)
    manifest = _base_stage_manifest(
        stage="PHASE_A",
        master_raw=master_raw,
        master=master,
        run_id=config["run_id"],
        participant_code=config["participant_code"],
        run_config_digest=_digest(config_raw),
        run_config=config,
        predecessor_lock_digest=None,
    )
    return _closed_package(output, payloads=payloads, manifest=manifest)


def verify_stage(
    root: Path,
    *,
    expected_stage: str,
) -> tuple[bytes, dict[str, Any]]:
    manifest_raw, manifest = _load_canonical_document(root / "stage-manifest.json")
    expected_members = {
        "PHASE_A": PHASE_A_STAGE_MEMBERS,
        "PHASE_B": PHASE_B_STAGE_MEMBERS,
        "DEBRIEF": DEBRIEF_STAGE_MEMBERS,
    }.get(expected_stage)
    if expected_members is None:
        _reject("STAGE_MANIFEST_INVALID")
    predecessor = manifest.get("predecessor_lock_digest")
    run_config = _validate_run_config(manifest.get("run_config"))
    if (
        set(manifest) != set(STAGE_MANIFEST_KEYS)
        or manifest.get("schema") != STAGE_MANIFEST_SCHEMA
        or manifest.get("stage") != expected_stage
        or manifest.get("study_id") != STUDY_ID
        or manifest.get("authoritative") is not False
        or manifest.get("decision_effect") != "NONE"
        or manifest.get("authentication") != "none"
        or manifest.get("custody_proved") is not False
        or manifest.get("trusted_time") is not False
        or manifest.get("campaign_input_digest")
        != scoring.EXPECTED_CAMPAIGN_INPUT_DIGEST
        or type(manifest.get("run_id")) is not str
        or IDENTIFIER.fullmatch(manifest["run_id"]) is None
        or type(manifest.get("participant_code")) is not str
        or scoring.PARTICIPANT_CODE.fullmatch(manifest["participant_code"]) is None
        or any(
            type(manifest.get(key)) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest[key]) is None
            for key in ("master_manifest_digest", "run_config_digest")
        )
        or manifest.get("run_config_digest") != _digest(_canonical_json(run_config))
        or manifest.get("run_id") != run_config["run_id"]
        or manifest.get("participant_code") != run_config["participant_code"]
        or (
            expected_stage == "PHASE_A"
            and predecessor is not None
        )
        or (
            expected_stage in {"PHASE_B", "DEBRIEF"}
            and (
                type(predecessor) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", predecessor) is None
            )
        )
    ):
        _reject("STAGE_MANIFEST_INVALID")
    rows = manifest.get("files")
    if type(rows) is not dict or set(rows) != set(expected_members):
        _reject("STAGE_MANIFEST_INVALID")
    if _directory_files(root) != set(rows) | {
        "stage-manifest.json",
        "SHA256SUMS.txt",
    }:
        _reject("STAGE_MEMBER_SET_INVALID")
    stage_payloads: dict[str, bytes] = {}
    for name, row in rows.items():
        raw = _read_regular(root.joinpath(*_safe_rel(name).parts))
        if row != {"bytes": len(raw), "digest": _digest(raw)}:
            _reject("STAGE_FILE_BINDING_INVALID")
        stage_payloads[name] = raw
    _validate_payload_links(stage_payloads)
    _verify_checksum_list(
        root, members=set(rows) | {"stage-manifest.json"}
    )
    return manifest_raw, manifest


def verify_stage_against_master(
    master_root: Path,
    stage_root: Path,
    *,
    expected_stage: str,
    allow_dirty_test_preview: bool = False,
) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any]]:
    master_raw, master = verify_master_kit(
        master_root, allow_dirty_test_preview=allow_dirty_test_preview
    )
    stage_raw, stage = verify_stage(stage_root, expected_stage=expected_stage)
    if stage["master_manifest_digest"] != _digest(master_raw):
        _reject("STAGE_MASTER_BINDING_INVALID")
    config = _validate_run_config(stage["run_config"])
    if expected_stage == "PHASE_A":
        _reject_run_config_answer_cues(config, master_root)
    expected_payloads = (
        _phase_a_stage_payloads(master_root, master, config)
        if expected_stage == "PHASE_A"
        else _static_stage_payloads(
            master_root,
            master,
            stage=expected_stage,
        )
    )
    expected_manifest = _base_stage_manifest(
        stage=expected_stage,
        master_raw=master_raw,
        master=master,
        run_id=config["run_id"],
        participant_code=config["participant_code"],
        run_config_digest=_digest(_canonical_json(config)),
        run_config=config,
        predecessor_lock_digest=stage["predecessor_lock_digest"],
    )
    expected_manifest["files"] = {
        name: {"bytes": len(raw), "digest": _digest(raw)}
        for name, raw in sorted(expected_payloads.items())
    }
    if stage != expected_manifest:
        _reject("STAGE_SOURCE_REGENERATION_MISMATCH")
    for name, expected_raw in expected_payloads.items():
        actual = _read_regular(stage_root.joinpath(*PurePosixPath(name).parts))
        if actual != expected_raw:
            _reject("STAGE_SOURCE_REGENERATION_MISMATCH")
    return master_raw, master, stage_raw, stage


def _parse_response(
    raw: bytes,
    *,
    expected_phase: str,
) -> tuple[str, bytes, dict[str, Any]]:
    if WORKSHEET_FENCE.encode("utf-8") in raw:
        canonical, value = parse_worksheet_response_bytes(
            raw, expected_phase=expected_phase
        )
        return "NO_JAVASCRIPT_WORKSHEET", canonical, value
    try:
        value = scoring.parse_json_bytes(raw)
    except scoring.StudyScoringError:
        _reject("RESPONSE_INVALID")
    if type(value) is not dict:
        _reject("RESPONSE_INVALID")
    return "BROWSER_JSON", scoring.canonical_json_bytes(value), value


def _validate_response_against_stage(
    stage_root: Path,
    stage: dict[str, Any],
    response_raw: bytes,
) -> tuple[str, bytes, dict[str, Any]]:
    phase = "A" if stage["stage"] == "PHASE_A" else "B"
    response_format, canonical, response = _parse_response(
        response_raw, expected_phase=phase
    )
    schema_raw = _read_regular(stage_root / "response.schema.json")
    schema = _parse_json(
        schema_raw[:-1] if schema_raw.endswith(b"\n") else schema_raw
    )
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(response))
    except (TypeError, ValueError):
        _reject("RESPONSE_SCHEMA_INVALID")
    if errors:
        _reject("RESPONSE_SCHEMA_REFUSED")
    if (
        response.get("participant_code") != stage.get("participant_code")
        or response.get("study_id") != stage.get("study_id")
        or response.get("campaign_input_digest")
        != stage.get("campaign_input_digest")
    ):
        _reject("RESPONSE_STAGE_BINDING_INVALID")
    if phase == "A" and (
        response.get("voluntary_consent") is not True
        or response.get("data_handling_acknowledged") is not True
    ):
        _reject("PARTICIPANT_CONSENT_NOT_ESTABLISHED")
    return response_format, canonical, response


def _write_receipt(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        _reject("RECEIPT_OUTPUT_INVALID")
    if path.name != PurePosixPath(path.name).name:
        _reject("RECEIPT_OUTPUT_INVALID")
    try:
        with path.open("xb", buffering=0) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        _reject("RECEIPT_WRITE_FAILED")


def lock_response(
    master_root: Path,
    stage_root: Path,
    response_path: Path,
    output_receipt: Path,
    *,
    expected_stage: str,
    recorded_at: str | None = None,
    allow_dirty_test_preview: bool = False,
) -> dict[str, Any]:
    _guard_output_separation(
        output_receipt,
        REPOSITORY_ROOT,
        master_root,
        stage_root,
        response_path,
    )
    _master_raw, _master, stage_raw, stage = verify_stage_against_master(
        master_root,
        stage_root,
        expected_stage=expected_stage,
        allow_dirty_test_preview=allow_dirty_test_preview,
    )
    response_raw = _read_regular(
        response_path, max_bytes=scoring.MAX_RESPONSE_BYTES
    )
    response_format, canonical, response = _validate_response_against_stage(
        stage_root, stage, response_raw
    )
    observed = recorded_at or datetime.now(timezone.utc).isoformat()
    try:
        parsed_time = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        _reject("RECEIPT_TIME_INVALID")
    if parsed_time.tzinfo is None:
        _reject("RECEIPT_TIME_INVALID")
    receipt = {
        "schema": LOCK_RECEIPT_SCHEMA,
        "phase": response["phase"],
        "stage": stage["stage"],
        "study_id": stage["study_id"],
        "run_id": stage["run_id"],
        "participant_code": stage["participant_code"],
        "prompt_code": response["prompt_code"],
        "prior_exposure": response.get("prior_exposure"),
        "campaign_input_digest": stage["campaign_input_digest"],
        "source_commit": _master["source_campaign"]["recomputed_at_source"]["commit"],
        "source_tree": _master["source_campaign"]["recomputed_at_source"]["tree"],
        "master_manifest_digest": stage["master_manifest_digest"],
        "stage_manifest_digest": _digest(stage_raw),
        "run_config_digest": stage["run_config_digest"],
        "predecessor_lock_digest": stage["predecessor_lock_digest"],
        "response_format": response_format,
        "response_bytes": len(response_raw),
        "response_raw_digest": _digest(response_raw),
        "response_canonical_digest": _digest(canonical),
        "recorded_at": observed,
        "recorded_at_trusted": False,
        "authentication": "none",
        "custody_proved": False,
        "authoritative": False,
        "decision_effect": "NONE",
    }
    raw = _canonical_json(receipt) + b"\n"
    _write_receipt(output_receipt, raw)
    return receipt


def verify_lock(
    master_root: Path,
    stage_root: Path,
    response_path: Path,
    receipt_path: Path,
    *,
    expected_stage: str,
    allow_dirty_test_preview: bool = False,
) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any]]:
    _master_raw, _master, stage_raw, stage = verify_stage_against_master(
        master_root,
        stage_root,
        expected_stage=expected_stage,
        allow_dirty_test_preview=allow_dirty_test_preview,
    )
    response_raw = _read_regular(
        response_path, max_bytes=scoring.MAX_RESPONSE_BYTES
    )
    response_format, canonical, response = _validate_response_against_stage(
        stage_root, stage, response_raw
    )
    receipt_raw, receipt = _load_canonical_document(receipt_path)
    expected = {
        "schema": LOCK_RECEIPT_SCHEMA,
        "phase": response["phase"],
        "stage": stage["stage"],
        "study_id": stage["study_id"],
        "run_id": stage["run_id"],
        "participant_code": stage["participant_code"],
        "prompt_code": response["prompt_code"],
        "prior_exposure": response.get("prior_exposure"),
        "campaign_input_digest": stage["campaign_input_digest"],
        "source_commit": _master["source_campaign"]["recomputed_at_source"]["commit"],
        "source_tree": _master["source_campaign"]["recomputed_at_source"]["tree"],
        "master_manifest_digest": stage["master_manifest_digest"],
        "stage_manifest_digest": _digest(stage_raw),
        "run_config_digest": stage["run_config_digest"],
        "predecessor_lock_digest": stage["predecessor_lock_digest"],
        "response_format": response_format,
        "response_bytes": len(response_raw),
        "response_raw_digest": _digest(response_raw),
        "response_canonical_digest": _digest(canonical),
        "recorded_at_trusted": False,
        "authentication": "none",
        "custody_proved": False,
        "authoritative": False,
        "decision_effect": "NONE",
    }
    if set(receipt) != set(expected) | {"recorded_at"} or any(
        receipt.get(key) != value for key, value in expected.items()
    ):
        _reject("LOCK_RECEIPT_BINDING_INVALID")
    try:
        observed = datetime.fromisoformat(
            receipt["recorded_at"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError):
        _reject("LOCK_RECEIPT_BINDING_INVALID")
    if observed.tzinfo is None:
        _reject("LOCK_RECEIPT_BINDING_INVALID")
    return receipt_raw, receipt, canonical, response


def release_phase_b(
    master_root: Path,
    phase_a_root: Path,
    phase_a_response: Path,
    phase_a_lock: Path,
    output: Path,
    *,
    allow_dirty_test_preview: bool = False,
) -> dict[str, Any]:
    _guard_output_separation(
        output,
        REPOSITORY_ROOT,
        master_root,
        phase_a_root,
        phase_a_response,
        phase_a_lock,
    )
    master_raw, master = verify_master_kit(
        master_root, allow_dirty_test_preview=allow_dirty_test_preview
    )
    _master_again, _master_value, _stage_raw, phase_a_stage = (
        verify_stage_against_master(
            master_root,
            phase_a_root,
            expected_stage="PHASE_A",
            allow_dirty_test_preview=allow_dirty_test_preview,
        )
    )
    lock_raw, lock, _canonical, _response = verify_lock(
        master_root,
        phase_a_root,
        phase_a_response,
        phase_a_lock,
        expected_stage="PHASE_A",
        allow_dirty_test_preview=allow_dirty_test_preview,
    )
    if (
        lock["master_manifest_digest"] != _digest(master_raw)
        or lock["source_commit"]
        != master["source_campaign"]["recomputed_at_source"]["commit"]
        or lock["source_tree"]
        != master["source_campaign"]["recomputed_at_source"]["tree"]
    ):
        _reject("LOCK_MASTER_BINDING_INVALID")
    payloads = _static_stage_payloads(
        master_root,
        master,
        stage="PHASE_B",
    )
    manifest = _base_stage_manifest(
        stage="PHASE_B",
        master_raw=master_raw,
        master=master,
        run_id=lock["run_id"],
        participant_code=lock["participant_code"],
        run_config_digest=lock["run_config_digest"],
        run_config=phase_a_stage["run_config"],
        predecessor_lock_digest=_digest(lock_raw),
    )
    return _closed_package(output, payloads=payloads, manifest=manifest)


def release_debrief(
    master_root: Path,
    phase_b_root: Path,
    phase_b_response: Path,
    phase_b_lock: Path,
    output: Path,
    *,
    allow_dirty_test_preview: bool = False,
) -> dict[str, Any]:
    _guard_output_separation(
        output,
        REPOSITORY_ROOT,
        master_root,
        phase_b_root,
        phase_b_response,
        phase_b_lock,
    )
    master_raw, master = verify_master_kit(
        master_root, allow_dirty_test_preview=allow_dirty_test_preview
    )
    _master_again, _master_value, _stage_raw, phase_b_stage = (
        verify_stage_against_master(
            master_root,
            phase_b_root,
            expected_stage="PHASE_B",
            allow_dirty_test_preview=allow_dirty_test_preview,
        )
    )
    lock_raw, lock, _canonical, _response = verify_lock(
        master_root,
        phase_b_root,
        phase_b_response,
        phase_b_lock,
        expected_stage="PHASE_B",
        allow_dirty_test_preview=allow_dirty_test_preview,
    )
    if (
        lock["master_manifest_digest"] != _digest(master_raw)
        or lock["source_commit"]
        != master["source_campaign"]["recomputed_at_source"]["commit"]
        or lock["source_tree"]
        != master["source_campaign"]["recomputed_at_source"]["tree"]
    ):
        _reject("LOCK_MASTER_BINDING_INVALID")
    payloads = _static_stage_payloads(
        master_root,
        master,
        stage="DEBRIEF",
    )
    manifest = _base_stage_manifest(
        stage="DEBRIEF",
        master_raw=master_raw,
        master=master,
        run_id=lock["run_id"],
        participant_code=lock["participant_code"],
        run_config_digest=lock["run_config_digest"],
        run_config=phase_b_stage["run_config"],
        predecessor_lock_digest=_digest(lock_raw),
    )
    return _closed_package(output, payloads=payloads, manifest=manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="build the researcher-only master kit")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--allow-dirty-test-preview", action="store_true")

    phase_a = sub.add_parser("release-phase-a", help="emit standalone Phase A")
    phase_a.add_argument("--master", type=Path, required=True)
    phase_a.add_argument("--run-config", type=Path, required=True)
    phase_a.add_argument("--output", type=Path, required=True)
    phase_a.add_argument("--allow-dirty-test-preview", action="store_true")

    lock_a = sub.add_parser("lock-phase-a", help="lock the preserved Phase A response")
    lock_a.add_argument("--master", type=Path, required=True)
    lock_a.add_argument("--stage", type=Path, required=True)
    lock_a.add_argument("--response", type=Path, required=True)
    lock_a.add_argument("--output", type=Path, required=True)
    lock_a.add_argument("--recorded-at")
    lock_a.add_argument("--allow-dirty-test-preview", action="store_true")

    phase_b = sub.add_parser(
        "release-phase-b", help="emit standalone Phase B after Phase A lock"
    )
    phase_b.add_argument("--master", type=Path, required=True)
    phase_b.add_argument("--phase-a-stage", type=Path, required=True)
    phase_b.add_argument("--phase-a-response", type=Path, required=True)
    phase_b.add_argument("--phase-a-lock", type=Path, required=True)
    phase_b.add_argument("--output", type=Path, required=True)
    phase_b.add_argument("--allow-dirty-test-preview", action="store_true")

    lock_b = sub.add_parser("lock-phase-b", help="lock the preserved Phase B response")
    lock_b.add_argument("--master", type=Path, required=True)
    lock_b.add_argument("--stage", type=Path, required=True)
    lock_b.add_argument("--response", type=Path, required=True)
    lock_b.add_argument("--output", type=Path, required=True)
    lock_b.add_argument("--recorded-at")
    lock_b.add_argument("--allow-dirty-test-preview", action="store_true")

    debrief = sub.add_parser(
        "release-debrief", help="emit debrief after Phase B lock"
    )
    debrief.add_argument("--master", type=Path, required=True)
    debrief.add_argument("--phase-b-stage", type=Path, required=True)
    debrief.add_argument("--phase-b-response", type=Path, required=True)
    debrief.add_argument("--phase-b-lock", type=Path, required=True)
    debrief.add_argument("--output", type=Path, required=True)
    debrief.add_argument("--allow-dirty-test-preview", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(
                args.output.resolve(),
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
        elif args.command == "release-phase-a":
            result = release_phase_a(
                args.master.resolve(),
                args.run_config.resolve(),
                args.output.resolve(),
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
        elif args.command == "lock-phase-a":
            result = lock_response(
                args.master.resolve(),
                args.stage.resolve(),
                args.response.resolve(),
                args.output.resolve(),
                expected_stage="PHASE_A",
                recorded_at=args.recorded_at,
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
        elif args.command == "release-phase-b":
            result = release_phase_b(
                args.master.resolve(),
                args.phase_a_stage.resolve(),
                args.phase_a_response.resolve(),
                args.phase_a_lock.resolve(),
                args.output.resolve(),
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
        elif args.command == "lock-phase-b":
            result = lock_response(
                args.master.resolve(),
                args.stage.resolve(),
                args.response.resolve(),
                args.output.resolve(),
                expected_stage="PHASE_B",
                recorded_at=args.recorded_at,
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
        else:
            result = release_debrief(
                args.master.resolve(),
                args.phase_b_stage.resolve(),
                args.phase_b_response.resolve(),
                args.phase_b_lock.resolve(),
                args.output.resolve(),
                allow_dirty_test_preview=args.allow_dirty_test_preview,
            )
    except StudyBuildError as exc:
        sys.stderr.write(f"STUDY_BUILD_REFUSED:{exc.code}\n")
        return 2
    sys.stdout.write(f"{args.command.upper()} {result['study_id']} {args.output.resolve()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
