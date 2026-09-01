"""Deterministic technical scorer for the bounded QDP-001 operator study.

The scorer checks exact structured responses and preserves human interpretation as a
separate manual review.  It never emits operator acceptance, qualification, or promotion.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any


SCORE_SCHEMA = "atlas.r3-qdp001-operator-study-score/1"
RESPONSE_SCHEMA = "atlas.r3-qdp001-operator-study-response/1"
EXPECTED_STUDY_ID = "qdp001-operator-study:break-this-plan:synthetic:v2"
EXPECTED_CAMPAIGN_INPUT_DIGEST = "sha256:c3b1de269c2bc2f9622268b10909316b8c4cf30527836799312c98ad3f73a7d7"
# Filled from the source-derived answer key. This is an exact-source consistency
# anchor, not authentication against an actor able to rewrite the source itself.
EXPECTED_ANSWER_KEY_DIGEST = "sha256:c71b39d7f77686204cb30116b9ec9eec45f195198f5ee347c2b4ec372ff0cb2d"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
STUDY_MANIFEST_SCHEMA = "atlas.r3-qdp001-operator-study-kit/1"
STAGE_MANIFEST_SCHEMA = "atlas.r3-qdp001-operator-study-stage/1"
LOCK_RECEIPT_SCHEMA = "atlas.r3-qdp001-operator-study-response-lock/1"
WORKSHEET_FENCE = "```atlas-response-json"
MAX_RESPONSE_BYTES = 262_144
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_FILES = 256
MAX_PACKAGE_DEPTH = 12
MAX_PACKAGE_TOTAL_BYTES = 64 * 1024 * 1024
RUN_CLASS_HUMAN = "HUMAN_FORMATIVE_RUN"
RUN_CLASS_SYNTHETIC = "SYNTHETIC_DRY_RUN_TOOLING_ONLY"
RUN_CLASSES = frozenset({RUN_CLASS_HUMAN, RUN_CLASS_SYNTHETIC})
SYNTHETIC_PARTICIPANT_CODE = "SYNTHETIC-DRY-RUN"
PARTICIPANT_CODE = re.compile(r"^(?:SYNTHETIC-DRY-RUN|p\.[0-9a-f]{12})$")
HUMAN_PARTICIPANT_CODE = re.compile(r"^p\.[0-9a-f]{12}$")
RUN_ID = re.compile(r"^run\.[0-9a-f]{16}$")
CONTACT_REFERENCE = re.compile(r"^contact\.[0-9a-f]{12}$")
POLICY_REFERENCE = re.compile(r"^policy\.[0-9a-f]{12}$")
PURPOSE_PROFILE = "SYNTHETIC_PLAN_REASONING"
DATA_USE_PROFILE = "FORMATIVE_STUDY_EVALUATION_ONLY"
STORAGE_PROFILE = "ENCRYPTED_INTERNAL_STUDY_WORKSPACE"
ACCESS_PROFILE = "MODERATOR_AND_TWO_ASSIGNED_NARRATIVE_REVIEWERS"
DELETION_PROFILE = "DELETE_AFTER_RETENTION_OR_EARLIER_VALID_WITHDRAWAL"
EXPECTED_REPLAY_NONCLAIMS = sorted(
    [
        "CANDIDATE_SELECTION",
        "FEASIBILITY",
        "FIELD_BEHAVIOR",
        "PROMOTION_PUBLICATION_OR_GA",
        "QDP_TO_QCP_TRANSLATION_OR_QUALIFICATION",
        "REPRESENTATIVE_WORKLOAD_ADEQUACY",
        "SEARCH_COMPLETENESS",
        "TRUST_CUSTODY_OR_AUTHORITY",
    ]
)
EXPECTED_FORBIDDEN_CLAIM_KEYS = sorted(
    [
        "candidate_safety",
        "candidate_selection",
        "candidate_support",
        "collection_authorized",
        "publication_or_ga",
        "qualification_or_promotion",
        "trust_or_custody",
        "workload_representativeness",
    ]
)
PHASE_A_ANSWER_KEYS = frozenset(
    {
        "unsafe_plan_alias",
        "unsafe_step_alias",
        "affected_requirement_alias",
    }
)
PHASE_B_ANSWER_KEYS = frozenset(
    {
        "case_id",
        "candidate_id",
        "step_id",
        "action",
        "requirement_id",
        "result_kind",
        "global_limitations",
        "candidate_limitations",
        "next_evidence_by_case",
        "product_boundary",
        "authority_placeholders",
        "replay_meaning",
        "abstention_meaning",
        "authority_action",
    }
)

PHASE_A_KEYS = frozenset(
    {
        "schema",
        "study_id",
        "phase",
        "participant_code",
        "campaign_input_digest",
        "prompt_code",
        "prior_exposure",
        "voluntary_consent",
        "data_handling_acknowledged",
        "unsafe_plan_alias",
        "unsafe_step_alias",
        "affected_requirement_alias",
        "explanation",
    }
)
PHASE_B_KEYS = frozenset(
    {
        "schema",
        "study_id",
        "phase",
        "participant_code",
        "campaign_input_digest",
        "prompt_code",
        "case_id",
        "candidate_id",
        "step_id",
        "action",
        "requirement_id",
        "result_kind",
        "global_limitations",
        "candidate_limitations",
        "next_evidence_by_case",
        "product_boundary",
        "authority_placeholders",
        "replay_meaning",
        "abstention_meaning",
        "authority_action",
        "replay_nonclaims",
        "forbidden_claims",
        "replay_explanation",
        "abstention_explanation",
        "limitations_explanation",
        "next_evidence_explanation",
    }
)


class StudyScoringError(ValueError):
    """Stable scoring refusal without echoing untrusted response content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StudyScoringError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON with one trailing newline."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StudyScoringError("JSON_NOT_CANONICALIZABLE") from exc
    return encoded + b"\n"


def parse_json_bytes(raw: bytes, *, max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """Parse bounded UTF-8 JSON and reject duplicate keys and non-finite values."""

    if not raw or len(raw) > max_bytes:
        raise StudyScoringError("JSON_BYTE_LIMIT_OR_EMPTY")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(StudyScoringError("NONFINITE_JSON_NUMBER")),
        )
    except StudyScoringError:
        raise
    except RecursionError as exc:
        raise StudyScoringError("JSON_NESTING_OR_NODE_LIMIT") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudyScoringError("JSON_INVALID") from exc
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if depth > 64 or visited > 100_000:
            raise StudyScoringError("JSON_NESTING_OR_NODE_LIMIT")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
    return value


def normalize_response_set_order(value: Any) -> Any:
    """Canonicalize order-only response differences without hiding invalid members.

    The response schema gives these arrays set semantics through ``uniqueItems``.  Browser
    controls sort them before download, while a no-JavaScript participant may faithfully
    copy the visible report order.  Sorting string-only arrays preserves duplicates and
    unsupported members so schema and N-1/N+1 checks still fail.
    """

    if type(value) is not dict or value.get("phase") != "B":
        return deepcopy(value)
    normalized = deepcopy(value)

    def sorted_strings(item: Any) -> Any:
        return sorted(item) if type(item) is list and all(type(row) is str for row in item) else item

    for key in ("global_limitations", "replay_nonclaims"):
        normalized[key] = sorted_strings(normalized.get(key))
    for key in ("candidate_limitations", "next_evidence_by_case"):
        mapping = normalized.get(key)
        if type(mapping) is dict:
            normalized[key] = {name: sorted_strings(rows) for name, rows in mapping.items()}
    return normalized


def _bounded_file_bytes(path: Path, *, max_bytes: int) -> bytes:
    try:
        path_info = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(path_info.st_mode)
            or path.is_symlink()
            or bool(getattr(path_info, "st_file_attributes", 0) & reparse)
            or not 0 < path_info.st_size <= max_bytes
            or path_info.st_nlink != 1
        ):
            raise StudyScoringError("JSON_FILE_NOT_BOUNDED_REGULAR")
        with path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = handle.read(min(1_048_576, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if handle.read(1):
                raise StudyScoringError("JSON_BYTE_LIMIT_OR_EMPTY")
            after = os.fstat(handle.fileno())
        final_info = path.lstat()
    except OSError as exc:
        raise StudyScoringError("JSON_FILE_UNREADABLE") from exc
    raw = b"".join(chunks)
    identities = {
        (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns) for item in (path_info, before, after, final_info)
    }
    if (
        len(identities) != 1
        or len(raw) != before.st_size
        or path.is_symlink()
        or bool(getattr(final_info, "st_file_attributes", 0) & reparse)
        or any(item.st_nlink != 1 for item in (before, after, final_info))
    ):
        raise StudyScoringError("JSON_FILE_CHANGED_DURING_READ")
    return raw


def load_json_file(path: Path, *, max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[bytes, Any]:
    raw = _bounded_file_bytes(path, max_bytes=max_bytes)
    return raw, parse_json_bytes(raw, max_bytes=max_bytes)


def load_response_file(path: Path) -> tuple[bytes, Any]:
    raw = _bounded_file_bytes(path, max_bytes=MAX_RESPONSE_BYTES)
    if WORKSHEET_FENCE.encode("utf-8") not in raw:
        return raw, normalize_response_set_order(parse_json_bytes(raw))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StudyScoringError("WORKSHEET_INVALID") from exc
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise StudyScoringError("WORKSHEET_INVALID")
    marker = WORKSHEET_FENCE + "\n"
    if text.count(marker) != 1 or text.count("\n```\n") != 1:
        raise StudyScoringError("WORKSHEET_INVALID")
    payload = text.split(marker, 1)[1].split("\n```", 1)[0].encode("utf-8")
    value = normalize_response_set_order(parse_json_bytes(payload))
    if "__REQUIRED_RESPONSE__" in payload.decode("utf-8", errors="ignore"):
        raise StudyScoringError("WORKSHEET_PLACEHOLDER")
    return raw, value


def _safe_member(name: str) -> PurePosixPath:
    part = PurePosixPath(name)
    if part.is_absolute() or not part.parts or ".." in part.parts:
        raise StudyScoringError("PACKAGE_MEMBER_PATH_INVALID")
    return part


def _directory_files(root: Path) -> set[str]:
    try:
        root_info = root.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root.is_symlink()
            or bool(getattr(root_info, "st_file_attributes", 0) & reparse)
        ):
            raise StudyScoringError("PACKAGE_DIRECTORY_INVALID")
        items = root.rglob("*")
    except OSError as exc:
        raise StudyScoringError("PACKAGE_DIRECTORY_UNREADABLE") from exc
    files: set[str] = set()
    count = 0
    total_bytes = 0
    try:
        for item in items:
            info = item.lstat()
            relative = item.relative_to(root)
            if len(relative.parts) > MAX_PACKAGE_DEPTH:
                raise StudyScoringError("PACKAGE_TRAVERSAL_LIMIT")
            if item.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse):
                raise StudyScoringError("PACKAGE_REPARSE_FORBIDDEN")
            if stat.S_ISREG(info.st_mode):
                count += 1
                total_bytes += info.st_size
                if count > MAX_PACKAGE_FILES or total_bytes > MAX_PACKAGE_TOTAL_BYTES:
                    raise StudyScoringError("PACKAGE_TRAVERSAL_LIMIT")
                name = relative.as_posix()
                _safe_member(name)
                files.add(name)
            elif not stat.S_ISDIR(info.st_mode):
                raise StudyScoringError("PACKAGE_MEMBER_TYPE_INVALID")
    except StudyScoringError:
        raise
    except OSError as exc:
        raise StudyScoringError("PACKAGE_DIRECTORY_UNREADABLE") from exc
    return files


def verify_master_package(
    root: Path,
    *,
    allow_dirty_test_preview: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    manifest_raw, manifest = load_json_file(root / "study-manifest.json", max_bytes=MAX_DOCUMENT_BYTES)
    source_state = (
        manifest.get("source_campaign", {}).get("recomputed_at_source", {}).get("source_state")
        if type(manifest) is dict
        else None
    )
    if (
        type(manifest) is not dict
        or manifest.get("schema") != STUDY_MANIFEST_SCHEMA
        or manifest.get("study_id") != EXPECTED_STUDY_ID
        or manifest.get("status")
        != (
            "MASTER_KIT_VERIFIED_RUN_CONFIGURATION_AND_TARGET_PREFLIGHT_REQUIRED_NO_PARTICIPANT_RESULT"
            if source_state == "EXACT_CLEAN_COMMIT"
            else "DIRTY_TEST_PREVIEW_NOT_DELIVERABLE"
        )
        or manifest.get("deliverable") != (source_state == "EXACT_CLEAN_COMMIT")
        or manifest.get("authoritative") is not False
        or manifest.get("decision_effect") != "NONE"
        or manifest.get("human_participant_count") != 0
        or manifest.get("operator_acceptance") is not False
        or manifest.get("qualification_effect") != "NONE"
        or manifest.get("promotion_effect") != "NONE"
        or manifest.get("collection_started") is not False
        or manifest.get("authority_placeholders") != {"R2-AUTH-001": None, "R2-AUTH-002": None, "R2-AUTH-004": None}
        or manifest.get("synthetic_dry_run_is_human_study") is not False
        or type(manifest.get("phase_a_forbidden_cue_patterns")) is not list
        or type(manifest.get("known_residuals")) is not list
        or manifest.get("participant_deliveries_exclude_campaign_result_answer_key_and_researcher_machine_data")
        is not True
        or manifest.get("source_campaign", {}).get("file_digests", {}).get("campaign-input.json")
        != EXPECTED_CAMPAIGN_INPUT_DIGEST
        or manifest.get("source_campaign", {}).get("subject") != "TRACKED_FIXTURE_RECOMPUTED_AT_EXACT_SOURCE"
        or source_state not in {"EXACT_CLEAN_COMMIT", "DIRTY_TEST_PREVIEW"}
        or (source_state != "EXACT_CLEAN_COMMIT" and not allow_dirty_test_preview)
    ):
        raise StudyScoringError("STUDY_MANIFEST_INVALID")
    rows = manifest.get("files")
    if type(rows) is not dict:
        raise StudyScoringError("STUDY_MANIFEST_INVALID")
    if _directory_files(root) != set(rows) | {
        "study-manifest.json",
        "SHA256SUMS.txt",
    }:
        raise StudyScoringError("PACKAGE_MEMBER_SET_INVALID")
    for name, row in rows.items():
        raw = _bounded_file_bytes(
            root.joinpath(*_safe_member(name).parts),
            max_bytes=32 * 1024 * 1024,
        )
        if row != {"bytes": len(raw), "digest": _sha256(raw)}:
            raise StudyScoringError("PACKAGE_FILE_BINDING_INVALID")
    sums_raw = _bounded_file_bytes(root / "SHA256SUMS.txt", max_bytes=MAX_RESPONSE_BYTES)
    try:
        actual = sums_raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise StudyScoringError("PACKAGE_CHECKSUM_LIST_INVALID") from exc
    expected = []
    for name in sorted(set(rows) | {"study-manifest.json"}):
        raw = _bounded_file_bytes(
            root.joinpath(*_safe_member(name).parts),
            max_bytes=32 * 1024 * 1024,
        )
        expected.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    if actual != expected:
        raise StudyScoringError("PACKAGE_CHECKSUM_LIST_INVALID")
    answer = rows.get("researcher-capsule/answer-key.json")
    if type(answer) is not dict or answer.get("digest") != EXPECTED_ANSWER_KEY_DIGEST:
        raise StudyScoringError("ANSWER_KEY_SOURCE_ANCHOR_INVALID")
    return manifest_raw, manifest


def _check(
    rows: list[dict[str, Any]],
    check_id: str,
    actual: Any,
    expected: Any,
    *,
    critical: bool = True,
) -> None:
    rows.append(
        {
            "check_id": check_id,
            "critical": critical,
            "passed": actual == expected,
        }
    )


def _all_false(value: Any, expected_keys: list[str]) -> bool:
    return (
        type(value) is dict and set(value) == set(expected_keys) and all(value[key] is False for key in expected_keys)
    )


def _nonempty_text(value: Any) -> bool:
    return type(value) is str and len(value.strip()) >= 20 and len(value) <= 8_192


def score_responses(
    phase_a: Any,
    phase_b: Any,
    answer_key: Any,
    *,
    answer_key_digest: str,
    expected_answer_key_digest: str,
    phase_a_digest: str | None = None,
    phase_b_digest: str | None = None,
    phase_a_lock_verified: bool = False,
    phase_b_lock_verified: bool = False,
    source_state: str = "EXACT_CLEAN_COMMIT",
    run_class: str | None = None,
    evidence_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score structured fields and leave semantic narratives for human review."""

    if type(phase_a) is not dict or type(phase_b) is not dict or type(answer_key) is not dict:
        raise StudyScoringError("SCORING_INPUT_SHAPE_INVALID")
    phase_a = normalize_response_set_order(phase_a)
    phase_b = normalize_response_set_order(phase_b)
    required_key_fields = {
        "schema",
        "study_id",
        "campaign_input_digest",
        "phase_a",
        "phase_b",
        "replay_nonclaims",
        "forbidden_claim_keys",
    }
    if (
        type(answer_key_digest) is not str
        or type(expected_answer_key_digest) is not str
        or answer_key_digest != expected_answer_key_digest
        or DIGEST_PATTERN.fullmatch(expected_answer_key_digest) is None
        or set(answer_key) != required_key_fields
        or answer_key.get("schema") != ("atlas.r3-qdp001-operator-study-answer-key/1")
        or type(answer_key.get("study_id")) is not str
        or answer_key["study_id"] != EXPECTED_STUDY_ID
        or type(answer_key.get("campaign_input_digest")) is not str
        or answer_key["campaign_input_digest"] != EXPECTED_CAMPAIGN_INPUT_DIGEST
        or answer_key_digest != EXPECTED_ANSWER_KEY_DIGEST
    ):
        raise StudyScoringError("ANSWER_KEY_INVALID")

    rows: list[dict[str, Any]] = []
    study_id = answer_key["study_id"]
    campaign_digest = answer_key["campaign_input_digest"]
    forbidden_claim_keys = answer_key["forbidden_claim_keys"]
    replay_nonclaims = answer_key["replay_nonclaims"]
    if (
        forbidden_claim_keys != EXPECTED_FORBIDDEN_CLAIM_KEYS
        or replay_nonclaims != EXPECTED_REPLAY_NONCLAIMS
        or type(answer_key["phase_a"]) is not dict
        or type(answer_key["phase_b"]) is not dict
        or set(answer_key["phase_a"]) != PHASE_A_ANSWER_KEYS
        or set(answer_key["phase_b"]) != PHASE_B_ANSWER_KEYS
    ):
        raise StudyScoringError("ANSWER_KEY_INVALID")

    _check(rows, "phase_a_exact_shape", set(phase_a), set(PHASE_A_KEYS))
    _check(rows, "phase_b_exact_shape", set(phase_b), set(PHASE_B_KEYS))
    _check(
        rows,
        "structural_phase_a_lock_chain_verified",
        phase_a_lock_verified,
        True,
    )
    _check(
        rows,
        "structural_phase_b_lock_chain_verified",
        phase_b_lock_verified,
        True,
    )
    _check(
        rows,
        "exact_source_structurally_bound",
        source_state,
        "EXACT_CLEAN_COMMIT",
    )
    for phase_name, response, expected_phase in (
        ("phase_a", phase_a, "A"),
        ("phase_b", phase_b, "B"),
    ):
        _check(rows, f"{phase_name}_schema", response.get("schema"), RESPONSE_SCHEMA)
        _check(rows, f"{phase_name}_study_id", response.get("study_id"), study_id)
        _check(rows, f"{phase_name}_phase", response.get("phase"), expected_phase)
        _check(
            rows,
            f"{phase_name}_campaign_binding",
            response.get("campaign_input_digest"),
            campaign_digest,
        )
        if phase_name == "phase_b":
            _check(
                rows,
                "phase_b_forbidden_claims_absent",
                _all_false(response.get("forbidden_claims"), forbidden_claim_keys),
                True,
            )
            _check(
                rows,
                "phase_b_replay_nonclaims_exact",
                response.get("replay_nonclaims"),
                replay_nonclaims,
            )

    participant_code = phase_a.get("participant_code")
    participant_code_valid = type(participant_code) is str and PARTICIPANT_CODE.fullmatch(participant_code) is not None
    _check(
        rows,
        "participant_code_safe",
        participant_code_valid,
        True,
    )
    _check(rows, "participant_code_same", phase_b.get("participant_code"), participant_code)
    run_class_valid = run_class in RUN_CLASSES
    synthetic_identity = participant_code == SYNTHETIC_PARTICIPANT_CODE
    run_class_identity_valid = (run_class == RUN_CLASS_SYNTHETIC and synthetic_identity) or (
        run_class == RUN_CLASS_HUMAN and participant_code_valid and not synthetic_identity
    )
    _check(rows, "run_class_domain", run_class_valid, True)
    _check(rows, "run_class_participant_identity_consistent", run_class_identity_valid, True)
    _check(
        rows,
        "phase_a_prompt_code_domain",
        type(phase_a.get("prompt_code")) is str and phase_a.get("prompt_code") in {"P0", "P1", "P2", "P3"},
        True,
        critical=False,
    )
    _check(
        rows,
        "phase_b_prompt_code_domain",
        type(phase_b.get("prompt_code")) is str and phase_b.get("prompt_code") in {"P0", "P1", "P2", "P3"},
        True,
        critical=False,
    )
    _check(
        rows,
        "phase_a_prior_exposure_domain",
        type(phase_a.get("prior_exposure")) is str and phase_a.get("prior_exposure") in {"NO", "YES", "UNKNOWN"},
        True,
        critical=False,
    )
    _check(
        rows,
        "phase_a_voluntary_consent",
        phase_a.get("voluntary_consent"),
        True,
    )
    _check(
        rows,
        "phase_a_data_handling_acknowledged",
        phase_a.get("data_handling_acknowledged"),
        True,
    )
    primary_cohort_structural_conditions_met = (
        source_state == "EXACT_CLEAN_COMMIT"
        and phase_a_lock_verified
        and phase_b_lock_verified
        and participant_code_valid
        and phase_b.get("participant_code") == participant_code
        and phase_a.get("voluntary_consent") is True
        and phase_a.get("data_handling_acknowledged") is True
        and phase_a.get("prompt_code") == "P0"
        and phase_b.get("prompt_code") == "P0"
        and phase_a.get("prior_exposure") == "NO"
    )
    declared_primary_cohort_conditions_met = (
        run_class == RUN_CLASS_HUMAN and run_class_identity_valid and primary_cohort_structural_conditions_met
    )

    for field, expected in answer_key["phase_a"].items():
        _check(rows, f"phase_a_{field}", phase_a.get(field), expected)
    for field, expected in answer_key["phase_b"].items():
        _check(rows, f"phase_b_{field}", phase_b.get(field), expected)

    manual_fields = [
        ("phase_a.explanation", phase_a.get("explanation")),
        ("phase_b.replay_explanation", phase_b.get("replay_explanation")),
        ("phase_b.abstention_explanation", phase_b.get("abstention_explanation")),
        ("phase_b.limitations_explanation", phase_b.get("limitations_explanation")),
        ("phase_b.next_evidence_explanation", phase_b.get("next_evidence_explanation")),
    ]
    for field, value in manual_fields:
        _check(rows, f"manual_text_present:{field}", _nonempty_text(value), True, critical=False)

    critical_pass = all(row["passed"] for row in rows if row["critical"])
    technical_pass = all(row["passed"] for row in rows)
    passed_count = sum(row["passed"] for row in rows)
    return {
        "schema": SCORE_SCHEMA,
        "authoritative": False,
        "decision_effect": "NONE",
        "study_id": study_id,
        "participant_code": (
            participant_code
            if type(participant_code) is str and PARTICIPANT_CODE.fullmatch(participant_code) is not None
            else None
        ),
        "response_digests": {
            "phase_a": phase_a_digest,
            "phase_b": phase_b_digest,
        },
        "evidence_bindings": deepcopy(evidence_bindings),
        "automated_checks": rows,
        "automated_check_count": len(rows),
        "automated_passed_count": passed_count,
        "automated_critical_checks_pass": critical_pass,
        "automated_technical_checks_pass": technical_pass,
        "run_class": run_class,
        "synthetic_dry_run_tooling_only": run_class == RUN_CLASS_SYNTHETIC,
        "primary_cohort_structural_conditions_met": primary_cohort_structural_conditions_met,
        "declared_primary_cohort_conditions_met": declared_primary_cohort_conditions_met,
        "primary_cohort_eligible": None,
        "human_participant_established": None,
        "source_state": source_state,
        "manual_review_required": [field for field, _value in manual_fields]
        + [
            "human_origin_and_uncontaminated_sequence_review",
            "cross_response_narrative_contradiction_review",
        ],
        "participant_pass": None,
        "operator_acceptance": False,
        "qualification_effect": "NONE",
        "promotion_effect": "NONE",
        "disposition": (
            "SYNTHETIC_DRY_RUN_TOOLING_ONLY"
            if run_class == RUN_CLASS_SYNTHETIC
            else "TEST_PREVIEW_NOT_PRIMARY_COHORT"
            if source_state != "EXACT_CLEAN_COMMIT"
            else "RUN_CLASS_UNVERIFIED_NOT_PRIMARY_COHORT"
            if not run_class_valid or not run_class_identity_valid
            else "DECLARED_PRIMARY_COHORT_CONDITIONS_NOT_MET"
            if not declared_primary_cohort_conditions_met
            else (
                "AUTOMATED_CHECKS_PASS_HUMAN_ORIGIN_AND_MANUAL_REVIEW_UNVERIFIED"
                if technical_pass
                else "AUTOMATED_CHECKS_FAIL"
            )
        ),
    }


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


_STAGE_KEYS = frozenset(
    {
        "schema",
        "stage",
        "study_id",
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
_POST_REVEAL_STAGE_KEYS = _STAGE_KEYS | {
    "authoritative",
    "decision_effect",
    "authentication",
    "custody_proved",
    "trusted_time",
}
_LOCK_KEYS = frozenset(
    {
        "schema",
        "phase",
        "stage",
        "study_id",
        "run_id",
        "participant_code",
        "prompt_code",
        "prior_exposure",
        "campaign_input_digest",
        "source_commit",
        "source_tree",
        "master_manifest_digest",
        "stage_manifest_digest",
        "run_config_digest",
        "predecessor_lock_digest",
        "response_format",
        "response_bytes",
        "response_raw_digest",
        "response_canonical_digest",
        "recorded_at",
        "recorded_at_trusted",
        "authentication",
        "custody_proved",
        "authoritative",
        "decision_effect",
    }
)
_RUN_CONFIG_KEYS = frozenset(
    {
        "schema",
        "run_class",
        "run_id",
        "participant_code",
        "participant_contact_ref",
        "withdrawal_contact_ref",
        "accessibility_contact_ref",
        "purpose_profile",
        "session_cap_minutes",
        "data_use_profile",
        "storage_profile",
        "access_profile",
        "retention_days",
        "deletion_profile",
        "data_policy_ref",
        "recording_planned",
    }
)
_PHASE_A_MEMBERS = frozenset(
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
_PHASE_B_MEMBERS = frozenset(
    {
        "index.html",
        "05-response.html",
        "PLAIN-TEXT.md",
        "RESPONSE-WORKSHEET.md",
        "response.schema.json",
        "START.cmd",
    }
)


def _verify_stage_package(
    root: Path,
    *,
    expected_stage: str,
) -> tuple[bytes, dict[str, Any]]:
    manifest_raw, manifest = load_json_file(root / "stage-manifest.json", max_bytes=MAX_DOCUMENT_BYTES)
    expected_members = _PHASE_A_MEMBERS if expected_stage == "PHASE_A" else _PHASE_B_MEMBERS
    predecessor = manifest.get("predecessor_lock_digest") if type(manifest) is dict else None
    run_config = manifest.get("run_config") if type(manifest) is dict else None
    try:
        run_config_raw = json.dumps(
            run_config,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        run_config_raw = b""
    if (
        type(manifest) is not dict
        or set(manifest) != set(_STAGE_KEYS if expected_stage == "PHASE_A" else _POST_REVEAL_STAGE_KEYS)
        or manifest.get("schema") != STAGE_MANIFEST_SCHEMA
        or manifest.get("stage") != expected_stage
        or manifest.get("study_id") != EXPECTED_STUDY_ID
        or manifest.get("campaign_input_digest") != EXPECTED_CAMPAIGN_INPUT_DIGEST
        or (
            expected_stage != "PHASE_A"
            and (
                manifest.get("authoritative") is not False
                or manifest.get("decision_effect") != "NONE"
                or manifest.get("authentication") != "none"
                or manifest.get("custody_proved") is not False
                or manifest.get("trusted_time") is not False
            )
        )
        or type(run_config) is not dict
        or set(run_config) != set(_RUN_CONFIG_KEYS)
        or run_config.get("schema") != "atlas.r3-qdp001-operator-study-run-config/1"
        or run_config.get("recording_planned") is not False
        or run_config.get("run_class") not in RUN_CLASSES
        or type(run_config.get("run_id")) is not str
        or RUN_ID.fullmatch(run_config["run_id"]) is None
        or type(run_config.get("participant_code")) is not str
        or PARTICIPANT_CODE.fullmatch(run_config["participant_code"]) is None
        or any(
            type(run_config.get(key)) is not str or CONTACT_REFERENCE.fullmatch(run_config[key]) is None
            for key in (
                "participant_contact_ref",
                "withdrawal_contact_ref",
                "accessibility_contact_ref",
            )
        )
        or type(run_config.get("data_policy_ref")) is not str
        or POLICY_REFERENCE.fullmatch(run_config["data_policy_ref"]) is None
        or run_config.get("purpose_profile") != PURPOSE_PROFILE
        or run_config.get("data_use_profile") != DATA_USE_PROFILE
        or run_config.get("storage_profile") != STORAGE_PROFILE
        or run_config.get("access_profile") != ACCESS_PROFILE
        or run_config.get("deletion_profile") != DELETION_PROFILE
        or type(run_config.get("session_cap_minutes")) is not int
        or type(run_config.get("session_cap_minutes")) is bool
        or not 15 <= run_config["session_cap_minutes"] <= 180
        or type(run_config.get("retention_days")) is not int
        or type(run_config.get("retention_days")) is bool
        or not 1 <= run_config["retention_days"] <= 3_650
        or (
            run_config.get("run_class") == RUN_CLASS_SYNTHETIC
            and run_config.get("participant_code") != SYNTHETIC_PARTICIPANT_CODE
        )
        or (
            run_config.get("run_class") == RUN_CLASS_HUMAN
            and HUMAN_PARTICIPANT_CODE.fullmatch(run_config["participant_code"]) is None
        )
        or manifest.get("run_id") != run_config.get("run_id")
        or manifest.get("participant_code") != run_config.get("participant_code")
        or manifest.get("run_config_digest") != _sha256(run_config_raw)
        or (expected_stage == "PHASE_A" and predecessor is not None)
        or (
            expected_stage == "PHASE_B"
            and (type(predecessor) is not str or DIGEST_PATTERN.fullmatch(predecessor) is None)
        )
        or any(
            type(manifest.get(key)) is not str or DIGEST_PATTERN.fullmatch(manifest[key]) is None
            for key in (
                "master_manifest_digest",
                "run_config_digest",
            )
        )
        or set(manifest.get("files", {})) != set(expected_members)
    ):
        raise StudyScoringError("STAGE_MANIFEST_INVALID")
    rows = manifest["files"]
    if _directory_files(root) != set(rows) | {
        "stage-manifest.json",
        "SHA256SUMS.txt",
    }:
        raise StudyScoringError("STAGE_MEMBER_SET_INVALID")
    for name, row in rows.items():
        raw = _bounded_file_bytes(
            root.joinpath(*_safe_member(name).parts),
            max_bytes=32 * 1024 * 1024,
        )
        if row != {"bytes": len(raw), "digest": _sha256(raw)}:
            raise StudyScoringError("STAGE_FILE_BINDING_INVALID")
    sums = _bounded_file_bytes(root / "SHA256SUMS.txt", max_bytes=MAX_RESPONSE_BYTES).decode("ascii").splitlines()
    expected_sums = []
    for name in sorted(set(rows) | {"stage-manifest.json"}):
        raw = _bounded_file_bytes(
            root.joinpath(*_safe_member(name).parts),
            max_bytes=32 * 1024 * 1024,
        )
        expected_sums.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    if sums != expected_sums:
        raise StudyScoringError("STAGE_CHECKSUM_LIST_INVALID")
    return manifest_raw, manifest


def verify_response_lock(
    stage_root: Path,
    response_path: Path,
    receipt_path: Path,
    *,
    expected_stage: str,
    expected_master_manifest_digest: str,
    expected_source_commit: str,
    expected_source_tree: str,
) -> tuple[bytes, Any]:
    stage_raw, stage = _verify_stage_package(stage_root, expected_stage=expected_stage)
    response_raw, response = load_response_file(response_path)
    receipt_raw, receipt = load_json_file(receipt_path, max_bytes=MAX_RESPONSE_BYTES)
    phase = "A" if expected_stage == "PHASE_A" else "B"
    response_format = "NO_JAVASCRIPT_WORKSHEET" if WORKSHEET_FENCE.encode("utf-8") in response_raw else "BROWSER_JSON"
    recorded_at = receipt.get("recorded_at") if type(receipt) is dict else None
    try:
        parsed_time = datetime.fromisoformat(recorded_at.replace("Z", "+00:00")) if type(recorded_at) is str else None
    except ValueError:
        parsed_time = None
    if (
        type(receipt) is not dict
        or set(receipt) != set(_LOCK_KEYS)
        or receipt.get("schema") != LOCK_RECEIPT_SCHEMA
        or receipt.get("phase") != phase
        or receipt.get("stage") != expected_stage
        or receipt.get("study_id") != EXPECTED_STUDY_ID
        or receipt.get("run_id") != stage.get("run_id")
        or receipt.get("participant_code") != response.get("participant_code")
        or receipt.get("participant_code") != stage.get("participant_code")
        or receipt.get("prompt_code") != response.get("prompt_code")
        or receipt.get("prior_exposure") != response.get("prior_exposure")
        or receipt.get("campaign_input_digest") != EXPECTED_CAMPAIGN_INPUT_DIGEST
        or receipt.get("source_commit") != expected_source_commit
        or receipt.get("source_tree") != expected_source_tree
        or receipt.get("master_manifest_digest") != expected_master_manifest_digest
        or receipt.get("master_manifest_digest") != stage.get("master_manifest_digest")
        or receipt.get("stage_manifest_digest") != _sha256(stage_raw)
        or receipt.get("run_config_digest") != stage.get("run_config_digest")
        or receipt.get("predecessor_lock_digest") != stage.get("predecessor_lock_digest")
        or receipt.get("response_format") != response_format
        or receipt.get("response_bytes") != len(response_raw)
        or receipt.get("response_raw_digest") != _sha256(response_raw)
        or receipt.get("response_canonical_digest") != _sha256(canonical_json_bytes(response))
        or parsed_time is None
        or parsed_time.tzinfo is None
        or receipt.get("recorded_at_trusted") is not False
        or receipt.get("authentication") != "none"
        or receipt.get("custody_proved") is not False
        or receipt.get("authoritative") is not False
        or receipt.get("decision_effect") != "NONE"
    ):
        raise StudyScoringError("LOCK_RECEIPT_BINDING_INVALID")
    return receipt_raw, response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--phase-a", type=Path, required=True)
    parser.add_argument("--phase-a-stage", type=Path, required=True)
    parser.add_argument("--phase-a-lock", type=Path, required=True)
    parser.add_argument("--phase-b", type=Path, required=True)
    parser.add_argument("--phase-b-stage", type=Path, required=True)
    parser.add_argument("--phase-b-lock", type=Path, required=True)
    parser.add_argument("--allow-dirty-test-preview", action="store_true")
    args = parser.parse_args(argv)
    try:
        master = args.master.resolve()
        manifest_raw, manifest = verify_master_package(
            master,
            allow_dirty_test_preview=args.allow_dirty_test_preview,
        )
        source = manifest["source_campaign"]["recomputed_at_source"]
        answer_path = master / "researcher-capsule" / "answer-key.json"
        answer_raw, answer_key = load_json_file(answer_path)
        phase_a_raw, phase_a = load_response_file(args.phase_a.resolve())
        phase_b_raw, phase_b = load_response_file(args.phase_b.resolve())
        phase_a_lock_raw, locked_a = verify_response_lock(
            args.phase_a_stage.resolve(),
            args.phase_a.resolve(),
            args.phase_a_lock.resolve(),
            expected_stage="PHASE_A",
            expected_master_manifest_digest=_sha256(manifest_raw),
            expected_source_commit=source["commit"],
            expected_source_tree=source["tree"],
        )
        phase_b_lock_raw, locked_b = verify_response_lock(
            args.phase_b_stage.resolve(),
            args.phase_b.resolve(),
            args.phase_b_lock.resolve(),
            expected_stage="PHASE_B",
            expected_master_manifest_digest=_sha256(manifest_raw),
            expected_source_commit=source["commit"],
            expected_source_tree=source["tree"],
        )
        phase_a_stage_raw, phase_a_stage = _verify_stage_package(args.phase_a_stage.resolve(), expected_stage="PHASE_A")
        phase_b_stage_raw, phase_b_stage = _verify_stage_package(args.phase_b_stage.resolve(), expected_stage="PHASE_B")
        if (
            locked_a != phase_a
            or locked_b != phase_b
            or phase_b_stage["predecessor_lock_digest"] != _sha256(phase_a_lock_raw)
            or phase_b_stage["run_id"] != phase_a_stage["run_id"]
            or phase_b_stage["participant_code"] != phase_a_stage["participant_code"]
            or phase_b_stage["run_config_digest"] != phase_a_stage["run_config_digest"]
            or phase_b_stage["master_manifest_digest"] != phase_a_stage["master_manifest_digest"]
            or _sha256(phase_a_stage_raw) != parse_json_bytes(phase_a_lock_raw)["stage_manifest_digest"]
        ):
            raise StudyScoringError("STAGE_LOCK_CHAIN_INVALID")
        answer_row = manifest.get("files", {}).get("researcher-capsule/answer-key.json")
        if type(answer_row) is not dict or answer_row.get("digest") != EXPECTED_ANSWER_KEY_DIGEST:
            raise StudyScoringError("STUDY_MANIFEST_INVALID")
        result = score_responses(
            phase_a,
            phase_b,
            answer_key,
            answer_key_digest=_sha256(answer_raw),
            expected_answer_key_digest=EXPECTED_ANSWER_KEY_DIGEST,
            phase_a_digest=_sha256(phase_a_raw),
            phase_b_digest=_sha256(phase_b_raw),
            phase_a_lock_verified=True,
            phase_b_lock_verified=True,
            source_state=source["source_state"],
            run_class=phase_a_stage["run_config"]["run_class"],
            evidence_bindings={
                "schema": "atlas.r3-qdp001-operator-study-score-evidence/1",
                "authentication": "none",
                "custody_proved": False,
                "run_id": phase_a_stage["run_id"],
                "participant_code": phase_a_stage["participant_code"],
                "run_class": phase_a_stage["run_config"]["run_class"],
                "source_commit": source["commit"],
                "source_tree": source["tree"],
                "source_state": source["source_state"],
                "master_manifest_digest": _sha256(manifest_raw),
                "phase_a_stage_manifest_digest": _sha256(phase_a_stage_raw),
                "phase_a_lock_receipt_digest": _sha256(phase_a_lock_raw),
                "phase_b_stage_manifest_digest": _sha256(phase_b_stage_raw),
                "phase_b_lock_receipt_digest": _sha256(phase_b_lock_raw),
                "run_config_digest": phase_a_stage["run_config_digest"],
            },
        )
    except StudyScoringError as exc:
        sys.stderr.buffer.write(
            canonical_json_bytes(
                {
                    "schema": "atlas.r3-qdp001-operator-study-score-error/1",
                    "error": exc.code,
                }
            )
        )
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
