#!/usr/bin/env python3
"""Build or verify a non-authoritative Atlas Release 2 authority candidate package.

The package freezes one exact Git commit and tree for accountable consideration.  It never selects
that candidate, supplies external evidence, or records an approval.  All source custody is derived
from immutable Git objects; checkout bytes are used only to prove that tracked state is clean.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_MANIFEST = "package-manifest.json"
PACKAGE_MEMBERS = (
    "R2-AUTH-001.json",
    "R2-AUTH-002.json",
    "R2-AUTH-004.json",
    "README.md",
    "source-freeze.json",
    "source.tar",
)
PACKAGE_FILES = frozenset((*PACKAGE_MEMBERS, PACKAGE_MANIFEST))
PACKAGE_SCHEMA = "atlas.r2-authority-candidate-package/1"
SOURCE_FREEZE_SCHEMA = "atlas.r2-authority-candidate-source-freeze/1"
DECISION_PACKET_SCHEMA = "atlas.r2-authority-decision-packet/1"
DECISION_RECEIPT_SCHEMA = "atlas.r2-authority-decision-receipt/1"
MACHINE_OWNED_CANDIDATE_BINDINGS = (
    (
        "REFERENCE_RUNTIME_INVENTORY_V1",
        "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json",
    ),
    (
        "STRUCTURAL_TCB_CENSUS",
        "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
    ),
    (
        "PROTOTYPE_MEASUREMENTS",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
    ),
    (
        "TCB_BUDGET_PROPOSAL",
        "cisco_toolkit/data/atlas-r2-tcb-budget-proposal.v1.json",
    ),
    ("QCP_001", "cisco_toolkit/data/qcp-001.experimental.json"),
    (
        "DSL_SUPPORTED_EXECUTION_DENOMINATOR",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json",
    ),
    (
        "DSL_PROTOTYPE_INPUT",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json",
    ),
    (
        "DSL_PROTOTYPE_PROGRAM",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json",
    ),
    (
        "DSL_PROTOTYPE_PACK_MANIFEST",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json",
    ),
    (
        "DSL_PROTOTYPE_TCB_MANIFEST",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json",
    ),
)
BASE_DECISION_RECEIPT_FIELDS = (
    "accountable_principal",
    "accountable_principal_organization",
    "authority_basis_digest",
    "authority_id",
    "candidate_commit",
    "candidate_tree",
    "choice",
    "decision_id",
    "detached_signature",
    "issued_at",
    "package_manifest_sha256",
    "payload_digest",
    "policy_head_digest",
    "public_key_digest",
    "reason",
    "repository_namespace",
    "signature_algorithm",
    "signer_key_id",
    "source_freeze_sha256",
    "trusted_time_evidence_digest",
)
AUTH_002_STAGE_A_RECEIPT_FIELDS = (
    "adequacy_criteria_digest",
    "count_reconciliation_contract_digest",
    "cumulative_revocation_ledger_digest",
    "cumulative_revocation_ledger_high_water_mark",
    "current_policy_digest",
    "decision_rule_digest",
    "inclusion_exclusion_rules_digest",
    "population_definition_digest",
    "required_artifact_roles_digest",
    "receipt_valid_until",
    "reviewer_separation_decision_digest",
    "resource_and_correctness_thresholds_digest",
    "sampling_frame_digest",
    "selection_method_digest",
    "strata_and_weights_digest",
    "signer_key_custody_digest",
    "workload_evidence_plan_digest",
)
AUTH_002_STAGE_B_RECEIPT_FIELDS = (
    "adequacy_criteria_digest",
    "artifact_bytes_manifest_digest",
    "corpus_manifest_digest",
    "coverage_reconciliation_digest",
    "criteria_evaluation_digest",
    "cumulative_revocation_ledger_digest",
    "cumulative_revocation_ledger_high_water_mark",
    "current_policy_digest",
    "execution_receipt_set_digest",
    "known_gaps_digest",
    "outcome_reason_evidence_digest",
    "provenance_custody_digest",
    "receipt_valid_until",
    "reviewer_key_custody_digest",
    "reviewer_separation_decision_digest",
    "runtime_denominator_digest",
    "sampling_frame_digest",
    "stage_a_receipt_sha256",
    "stage_a_current_policy_revalidation_digest",
    "stage_a_revocation_status_digest",
    "stage_a_trusted_time_revalidation_digest",
    "strata_count_reconciliation_digest",
    "workload_denominator_digest",
    "workload_evidence_digest",
    "workload_input_set_digest",
)

_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_MODE = re.compile(r"[0-7]{6}\Z")


class CandidatePackageError(RuntimeError):
    """Fail-closed candidate-package error."""


@dataclass(frozen=True)
class GitSubject:
    repository: Path
    git_directory: Path
    object_format: str
    commit: str
    tree: str
    core_autocrlf: str
    core_eol: str
    core_safecrlf: str


@dataclass(frozen=True)
class GitSnapshot:
    subject: GitSubject
    blobs: tuple[dict[str, Any], ...]
    archive_raw: bytes


def canonical_json_bytes(value: Any) -> bytes:
    """Encode the package's closed canonical JSON representation."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidatePackageError("NON_CANONICAL_JSON_VALUE") from exc


def bytes_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fail(code: str, detail: str | None = None) -> None:
    raise CandidatePackageError(code if detail is None else f"{code}:{detail}")


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key in {
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "GIT_GRAFT_FILE",
            "GIT_INDEX_FILE",
            "GIT_NAMESPACE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_REPLACE_REF_BASE",
            "GIT_SHALLOW_FILE",
            "GIT_WORK_TREE",
        } or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(key, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _run_git(
    repository: Path,
    *arguments: str,
    input_raw: bytes | None = None,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            env=_git_environment(),
            input=input_raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise CandidatePackageError("GIT_EXECUTION_UNAVAILABLE") from exc
    if completed.returncode not in accepted_returncodes:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        _fail("GIT_COMMAND_FAILED", detail or "unknown")
    return completed


def _git_text(repository: Path, *arguments: str) -> str:
    try:
        return _run_git(repository, *arguments).stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise CandidatePackageError("GIT_TEXT_NOT_UTF8") from exc


def _required_git_config(repository: Path, key: str, *, boolean: bool = False) -> str:
    arguments = ["config"]
    if boolean:
        arguments.append("--type=bool")
    arguments.extend(("--get", key))
    completed = _run_git(repository, *arguments, accepted_returncodes=(0, 1))
    if completed.returncode != 0:
        _fail("LF_EXACT_GIT_CONFIG_MISSING", key)
    try:
        return completed.stdout.decode("utf-8", errors="strict").strip().lower()
    except UnicodeDecodeError as exc:
        raise CandidatePackageError(f"LF_EXACT_GIT_CONFIG_INVALID:{key}") from exc


def _resolved_directory(path: Path, code: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CandidatePackageError(code) from exc
    if not resolved.is_dir():
        _fail(code)
    return resolved


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _read_subject(repository: Path) -> GitSubject:
    repository = _resolved_directory(repository, "REPOSITORY_NOT_FOUND")
    top_level = Path(_git_text(repository, "rev-parse", "--show-toplevel"))
    if not _same_path(repository, top_level):
        _fail("REPOSITORY_ROOT_REQUIRED")
    git_directory = Path(_git_text(repository, "rev-parse", "--absolute-git-dir")).resolve(strict=True)
    common_directory = Path(_git_text(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(
        strict=True
    )
    if not _same_path(git_directory, common_directory):
        _fail("STANDALONE_GIT_DIRECTORY_REQUIRED")
    if _git_text(repository, "rev-parse", "--is-shallow-repository") != "false":
        _fail("FULL_GIT_HISTORY_REQUIRED")
    for relative, code in (
        (Path("info") / "grafts", "GIT_GRAFTS_REFUSED"),
        (Path("objects") / "info" / "alternates", "GIT_ALTERNATES_REFUSED"),
    ):
        candidate = git_directory / relative
        if candidate.is_file() and candidate.stat().st_size:
            _fail(code)
    object_format = _git_text(repository, "rev-parse", "--show-object-format")
    if object_format not in {"sha1", "sha256"}:
        _fail("UNSUPPORTED_GIT_OBJECT_FORMAT", object_format)
    commit = _git_text(repository, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git_text(repository, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if _OBJECT_ID.fullmatch(commit) is None or _OBJECT_ID.fullmatch(tree) is None:
        _fail("MALFORMED_GIT_SUBJECT")
    core_autocrlf = _required_git_config(repository, "core.autocrlf", boolean=True)
    core_eol = _required_git_config(repository, "core.eol")
    core_safecrlf = _required_git_config(repository, "core.safecrlf", boolean=True)
    if (core_autocrlf, core_eol, core_safecrlf) != ("false", "lf", "true"):
        _fail("LF_EXACT_GIT_CONFIG_REQUIRED")
    return GitSubject(
        repository,
        git_directory,
        object_format,
        commit,
        tree,
        core_autocrlf,
        core_eol,
        core_safecrlf,
    )


def _assert_expected_subject(
    subject: GitSubject,
    expected_commit: str,
    expected_tree: str,
) -> None:
    required_length = 40 if subject.object_format == "sha1" else 64
    if (
        _OBJECT_ID.fullmatch(expected_commit) is None
        or len(expected_commit) != required_length
        or expected_commit != subject.commit
    ):
        _fail("EXPECTED_COMMIT_MISMATCH")
    if (
        _OBJECT_ID.fullmatch(expected_tree) is None
        or len(expected_tree) != required_length
        or expected_tree != subject.tree
    ):
        _fail("EXPECTED_TREE_MISMATCH")


def _assert_tracked_worktree_clean(subject: GitSubject) -> None:
    completed = _run_git(
        subject.repository,
        "diff",
        "--no-ext-diff",
        "--quiet",
        "--ignore-submodules=none",
        "HEAD",
        "--",
        accepted_returncodes=(0, 1),
    )
    if completed.returncode == 1:
        _fail("TRACKED_WORKTREE_NOT_CLEAN")


def _parse_tree_rows(subject: GitSubject) -> list[tuple[str, str, str]]:
    raw = _run_git(
        subject.repository,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        subject.commit,
    ).stdout
    rows: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_raw = record.split(b"\t", 1)
            mode_raw, kind_raw, object_raw = metadata.split(b" ", 2)
            mode = mode_raw.decode("ascii")
            kind = kind_raw.decode("ascii")
            object_id = object_raw.decode("ascii")
            path = path_raw.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise CandidatePackageError("MALFORMED_GIT_TREE_ROW") from exc
        parsed_path = PurePosixPath(path)
        if (
            not path
            or parsed_path.is_absolute()
            or any(part in {"", ".", ".."} for part in parsed_path.parts)
            or "\\" in path
            or path in seen_paths
        ):
            _fail("UNSAFE_OR_DUPLICATE_GIT_PATH", path)
        if kind != "blob":
            _fail("NON_BLOB_GIT_TREE_ENTRY_UNSUPPORTED", path)
        if (
            _MODE.fullmatch(mode) is None
            or mode not in {"100644", "100755", "120000"}
            or _OBJECT_ID.fullmatch(object_id) is None
        ):
            _fail("MALFORMED_GIT_TREE_IDENTITY", path)
        seen_paths.add(path)
        rows.append((path, mode, object_id))
    if not rows:
        _fail("EMPTY_GIT_TREE_UNSUPPORTED")
    return sorted(rows, key=lambda row: row[0])


def _read_blob_batch(subject: GitSubject, object_ids: list[str]) -> list[bytes]:
    request = b"".join(object_id.encode("ascii") + b"\n" for object_id in object_ids)
    output = _run_git(subject.repository, "cat-file", "--batch", input_raw=request).stdout
    offset = 0
    blobs: list[bytes] = []
    for expected_object in object_ids:
        header_end = output.find(b"\n", offset)
        if header_end < 0:
            _fail("GIT_CAT_FILE_BATCH_TRUNCATED")
        try:
            object_raw, kind_raw, size_raw = output[offset:header_end].split(b" ", 2)
            actual_object = object_raw.decode("ascii")
            kind = kind_raw.decode("ascii")
            size = int(size_raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CandidatePackageError("GIT_CAT_FILE_BATCH_HEADER_INVALID") from exc
        start = header_end + 1
        end = start + size
        if (
            actual_object != expected_object
            or kind != "blob"
            or size < 0
            or end >= len(output)
            or output[end : end + 1] != b"\n"
        ):
            _fail("GIT_CAT_FILE_BATCH_IDENTITY_MISMATCH", expected_object)
        blobs.append(output[start:end])
        offset = end + 1
    if offset != len(output):
        _fail("GIT_CAT_FILE_BATCH_TRAILING_DATA")
    return blobs


def _exact_blob_archive(
    rows: list[tuple[str, str, str]],
    contents: list[bytes],
) -> bytes:
    """Build a deterministic tar from every Git blob, ignoring export-ignore attributes."""

    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for (path, mode, _object_id), raw in zip(rows, contents, strict=True):
            member = tarfile.TarInfo(f"source/{path}")
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mtime = 0
            if mode == "120000":
                try:
                    link_target = raw.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise CandidatePackageError("GIT_SYMLINK_TARGET_NOT_UTF8") from exc
                if not link_target or "\0" in link_target:
                    _fail("GIT_SYMLINK_TARGET_INVALID", path)
                member.type = tarfile.SYMTYPE
                member.mode = 0o777
                member.size = 0
                member.linkname = link_target
                archive.addfile(member)
            else:
                member.type = tarfile.REGTYPE
                member.mode = 0o755 if mode == "100755" else 0o644
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
    archive_raw = output.getvalue()
    if not archive_raw:
        _fail("EMPTY_EXACT_BLOB_ARCHIVE")
    return archive_raw


def _snapshot(repository: Path, expected_commit: str, expected_tree: str) -> GitSnapshot:
    subject = _read_subject(repository)
    _assert_expected_subject(subject, expected_commit, expected_tree)
    _assert_tracked_worktree_clean(subject)
    rows = _parse_tree_rows(subject)
    contents = _read_blob_batch(subject, [row[2] for row in rows])
    blobs = tuple(
        {
            "blob": object_id,
            "byte_count": len(raw),
            "mode": mode,
            "path": path,
            "sha256": bytes_digest(raw),
        }
        for (path, mode, object_id), raw in zip(rows, contents, strict=True)
    )
    archive_raw = _exact_blob_archive(rows, contents)
    final_subject = _read_subject(subject.repository)
    _assert_tracked_worktree_clean(final_subject)
    if final_subject != subject:
        _fail("GIT_SUBJECT_CHANGED_DURING_SNAPSHOT")
    return GitSnapshot(subject, blobs, archive_raw)


def _machine_owned_bindings(snapshot: GitSnapshot) -> list[dict[str, Any]]:
    by_path = {row["path"]: row for row in snapshot.blobs}
    bindings: list[dict[str, Any]] = []
    for role, path in MACHINE_OWNED_CANDIDATE_BINDINGS:
        row = by_path.get(path)
        if row is None:
            _fail("REQUIRED_MACHINE_OWNED_CANDIDATE_PATH_MISSING", path)
        bindings.append({"role": role, **row})
    raw_by_role = {
        row["role"]: raw
        for row, raw in zip(
            bindings,
            _read_blob_batch(
                snapshot.subject,
                [row["blob"] for row in bindings],
            ),
            strict=True,
        )
    }
    machine_objects: dict[str, dict[str, Any]] = {}
    for role in ("QCP_001", "REFERENCE_RUNTIME_INVENTORY_V1"):
        raw = raw_by_role[role]
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidatePackageError(f"MACHINE_OWNED_CANONICAL_JSON_INVALID:{role}") from exc
        if type(value) is not dict or canonical_json_bytes(value) != raw:
            _fail("MACHINE_OWNED_CANONICAL_JSON_INVALID", role)
        machine_objects[role] = value
    qcp = machine_objects["QCP_001"]
    if qcp.get("qualification_state") != "EXPERIMENTAL" or qcp.get("execution_state") != "CONTRACT_ONLY":
        _fail("QCP_001_RELEASE_BOUNDARY_MISMATCH")
    runtime = machine_objects["REFERENCE_RUNTIME_INVENTORY_V1"]
    closure = runtime.get("closure")
    if (
        type(closure) is not dict
        or closure.get("state") != "PARTIAL_NONPORTABLE_PROTOTYPE"
        or closure.get("complete_exact_runtime_closure") is not False
    ):
        _fail("RUNTIME_RELEASE_BOUNDARY_MISMATCH")
    return bindings


def _release_boundaries() -> dict[str, Any]:
    return {
        "candidate_selection": "PENDING_ACCOUNTABLE_SELECTION",
        "ga_decision": None,
        "promotion_decision": None,
        "publication_decision": None,
        "qcp_001": {
            "execution_state": "CONTRACT_ONLY",
            "qualification_state": "EXPERIMENTAL",
        },
        "qualification_decision": None,
        "release_3": "DISCOVERY_PLANNING_ONLY",
        "release_2": "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
        "runtime": "PARTIAL_NONPORTABLE_PROTOTYPE",
    }


def _empty_authority() -> dict[str, Any]:
    return {
        "accountable_owner": None,
        "approval": None,
        "approved_at": None,
        "authoritative": False,
        "decision": None,
        "independent_reviewer": None,
        "signature": None,
    }


def _source_freeze(snapshot: GitSnapshot) -> dict[str, Any]:
    subject = snapshot.subject
    machine_owned_bindings = _machine_owned_bindings(snapshot)
    return {
        "archive": {
            "byte_count": len(snapshot.archive_raw),
            "format": "EXACT_GIT_BLOB_TAR/1",
            "path": "source.tar",
            "prefix": "source/",
            "sha256": bytes_digest(snapshot.archive_raw),
        },
        "authority": _empty_authority(),
        "candidate_selection": {
            "accountable_owner": None,
            "approval": None,
            "decision": None,
            "selected_commit": None,
            "selected_tree": None,
            "state": "PENDING_ACCOUNTABLE_SELECTION",
        },
        "claim_boundary": (
            "Exact non-authoritative Git source custody for accountable candidate selection; this "
            "freeze supplies no selection, runtime closure, workload adequacy, trust-policy, budget, "
            "qualification, promotion, publication, GA, or Release 3 authority."
        ),
        "machine_owned_candidate_bindings": machine_owned_bindings,
        "release_boundaries": _release_boundaries(),
        "schema": SOURCE_FREEZE_SCHEMA,
        "source": {
            "blob_count": len(snapshot.blobs),
            "blobs": list(snapshot.blobs),
            "clean_tracked_worktree": True,
            "git_configuration": {
                "core.autocrlf": subject.core_autocrlf,
                "core.eol": subject.core_eol,
                "core.safecrlf": subject.core_safecrlf,
            },
            "object_format": subject.object_format,
            "proposed_candidate_commit": subject.commit,
            "proposed_candidate_tree": subject.tree,
        },
    }


def _decision_packet(
    snapshot: GitSnapshot,
    source_freeze_digest: str,
    authority_id: str,
    title: str,
    blockers: tuple[str, ...],
    required_evidence: tuple[str, ...],
    unresolved_inputs: Mapping[str, Any],
    choice_id: str,
    choice_prompt: str,
    choice_options: tuple[str, ...],
    additional_fields: Mapping[str, Any] | None = None,
    receipt_binding_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    if any(value is not None and value != "UNRESOLVED" for value in unresolved_inputs.values()):
        _fail("ACCOUNTABLE_INPUT_MUST_REMAIN_UNRESOLVED", authority_id)
    receipt_fields = tuple(sorted((*BASE_DECISION_RECEIPT_FIELDS, *receipt_binding_fields)))
    if len(receipt_fields) != len(set(receipt_fields)):
        _fail("DUPLICATE_DECISION_RECEIPT_FIELD", authority_id)
    packet = {
        "accountable_decision": _empty_authority(),
        "authority_id": authority_id,
        "authoritative": False,
        "blockers": list(blockers),
        "candidate_selection": {
            "approval": None,
            "decision": None,
            "selected_commit": None,
            "selected_tree": None,
            "state": "PENDING_ACCOUNTABLE_SELECTION",
        },
        "claim_boundary": (
            "Decision-template-ready non-authoritative packet only; every external or accountable "
            "field remains null or unresolved and no listed option is a recorded decision."
        ),
        "decision_consumption_state": "TEMPLATE_ONLY_NO_DECISION_RECEIPT_VERIFIER",
        "detached_decision_receipt_contract": {
            "allowed_choices": list(choice_options),
            "binding_rules": {
                "authority_id": "MUST_EQUAL_PACKET_AUTHORITY_ID",
                "candidate_commit": "MUST_EQUAL_PROPOSED_CANDIDATE_COMMIT",
                "candidate_tree": "MUST_EQUAL_PROPOSED_CANDIDATE_TREE",
                "decision_id": "MUST_EQUAL_SMALLEST_ACCOUNTABLE_CHOICE_ID",
                "package_manifest_sha256": "MUST_DIGEST_EXACT_PACKAGE_MANIFEST_BYTES",
                "source_freeze_sha256": "MUST_EQUAL_PROPOSED_CANDIDATE_SOURCE_FREEZE_SHA256",
            },
            "canonical_json_required": True,
            "package_mutation_forbidden": True,
            "receipt_schema": DECISION_RECEIPT_SCHEMA,
            "receipt_values": {field: None for field in receipt_fields},
            "required_receipt_fields": list(receipt_fields),
            "status": "DETACHED_RECEIPT_REQUIRED_NOT_SUPPLIED",
        },
        "packet_status": "DECISION_TEMPLATE_READY_WITH_UNRESOLVED_ACCOUNTABLE_INPUTS",
        "proposed_candidate": {
            "commit": snapshot.subject.commit,
            "machine_owned_candidate_bindings_sha256": bytes_digest(
                canonical_json_bytes(_machine_owned_bindings(snapshot))
            ),
            "source_freeze_sha256": source_freeze_digest,
            "tree": snapshot.subject.tree,
        },
        "release_boundaries": _release_boundaries(),
        "required_evidence": list(required_evidence),
        "schema": DECISION_PACKET_SCHEMA,
        "smallest_accountable_choice": {
            "choice_id": choice_id,
            "decision_id": choice_id,
            "options": list(choice_options),
            "prompt": choice_prompt,
            "recorded_choice": None,
        },
        "title": title,
        "unresolved_accountable_inputs": dict(unresolved_inputs),
    }
    if additional_fields:
        overlap = set(packet) & set(additional_fields)
        if overlap:
            _fail("DECISION_PACKET_ADDITIONAL_FIELD_COLLISION", sorted(overlap)[0])
        packet.update(additional_fields)
    return packet


def _authority_001(snapshot: GitSnapshot, source_freeze_digest: str) -> dict[str, Any]:
    return _decision_packet(
        snapshot,
        source_freeze_digest,
        "R2-AUTH-001",
        "Complete exact runtime and cryptographic dependency closure",
        (
            "CANDIDATE_SOURCE_ACCOUNTABLE_SELECTION_PENDING",
            "R2-AUTH-006_SELECTED_SOURCE_CEREMONY_AND_PROVENANCE_OPEN",
            "COMPLETE_EXACT_RUNTIME_CLOSURE_NOT_ESTABLISHED",
            "CLOSURE_CAPABLE_RUNTIME_PROFILE_AND_EXACT_EVIDENCE_NOT_VERIFIED",
            "CURRENT_RUNTIME_STATE_PARTIAL_NONPORTABLE_PROTOTYPE",
            "INDEPENDENT_RUNTIME_CLOSURE_REVIEW_NOT_SUPPLIED",
            "CURRENT_TRUST_POLICY_KEY_REVOCATION_AND_TIME_EVIDENCE_NOT_SUPPLIED",
            "FRESH_RUNTIME_CLOSURE_AUTHORITY_NOT_BOUND_TO_FINAL_FREEZE",
        ),
        (
            "ACCOUNTABLY_SELECTED_EXACT_COMMIT_AND_TREE",
            "COMPLETE_22_ROLE_RUNTIME_CLOSURE_EVIDENCE_BOUND_TO_SELECTED_SOURCE",
            "LOSSLESS_GLOBAL_EVENT_AND_START_END_RECONCILIATION",
            "DENY_BY_DEFAULT_CONTENT_ADDRESSED_EXECUTABLE_ALLOW_SET_EVIDENCE",
            "STATIC_LOADER_CRYPTO_PLATFORM_AND_COLLECTOR_TCB_CLOSURE_EVIDENCE",
            "INDEPENDENT_SIGNED_COMPLETE_REVIEW_WITH_CURRENT_TRUST_EVIDENCE",
        ),
        {
            "accountable_owner": None,
            "approval": None,
            "independent_reviewer": None,
            "key_custodian": None,
            "public_key_digest": None,
            "revocation_evidence_digest": None,
            "runtime_closure_evidence_digest": None,
            "runtime_closure_review_receipt_digest": None,
            "runtime_closure_review_signature_digest": None,
            "trust_policy_digest": None,
            "trusted_time_evidence_digest": None,
        },
        "R2-AUTH-001-PRECONDITION-D1",
        (
            "Select, reject, or hold the proposed exact commit and tree only as a precondition for "
            "R2-AUTH-001 evidence collection; selection does not close R2-AUTH-001 and leaves the "
            "R2-AUTH-006 source ceremony and provenance decision open."
        ),
        ("SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION", "REJECT_CANDIDATE", "HOLD"),
        receipt_binding_fields=(
            "independent_provenance_plan_digest",
            "source_selection_basis_digest",
        ),
    )


def _authority_002(snapshot: GitSnapshot, source_freeze_digest: str) -> dict[str, Any]:
    return _decision_packet(
        snapshot,
        source_freeze_digest,
        "R2-AUTH-002",
        "Representative-workload adequacy",
        (
            "CANDIDATE_SOURCE_ACCOUNTABLE_SELECTION_PENDING",
            "REPRESENTATIVE_WORKLOAD_CORPUS_NOT_SELECTED_OR_FROZEN",
            "WORKLOAD_ADEQUACY_THRESHOLDS_UNRESOLVED",
            "REPRESENTATIVE_WORKLOAD_EVIDENCE_NOT_SUPPLIED",
            "INDEPENDENT_WORKLOAD_ADEQUACY_REVIEW_NOT_SUPPLIED",
            "CURRENT_WORKLOAD_TRUST_POLICY_KEY_REVOCATION_AND_TIME_EVIDENCE_NOT_SUPPLIED",
        ),
        (
            "ACCOUNTABLY_SELECTED_EXACT_COMMIT_AND_TREE",
            "ACCOUNTABLE_WORKLOAD_OWNER_AND_INDEPENDENT_ADEQUACY_REVIEWER",
            "CONTENT_ADDRESSED_REPRESENTATIVE_WORKLOAD_CORPUS_AND_SAMPLING_FRAME",
            "TARGET_POPULATION_INCLUSION_EXCLUSION_SELECTION_STRATA_AND_WEIGHTS",
            "NONZERO_TARGET_ELIGIBLE_SELECTED_EXECUTED_VALID_AND_ASSESSED_COUNTS",
            "PREDECLARED_ADEQUACY_THRESHOLDS_AND_DECISION_RULE",
            "RAW_DENOMINATOR_CORPUS_INPUT_RECEIPT_COVERAGE_PROVENANCE_AND_GAP_BYTES",
            "MEASURED_RESULTS_BOUND_TO_EXACT_SOURCE_CORPUS_RUNTIME_AND_STAGE_A_RECEIPT",
            "INDEPENDENT_SIGNED_ADEQUACY_REVIEW_WITH_CURRENT_TRUST_EVIDENCE",
        ),
        {
            "accountable_owner": None,
            "adequacy_approval": None,
            "adequacy_thresholds": "UNRESOLVED",
            "corpus_digest": None,
            "corpus_owner": None,
            "inclusion_and_exclusion_rules": "UNRESOLVED",
            "independent_reviewer": None,
            "permitted_failures": "UNRESOLVED",
            "population": "UNRESOLVED",
            "sampling_frame": "UNRESOLVED",
            "selection_method_strata_and_weights": "UNRESOLVED",
            "trust_policy_digest": None,
            "workload_evidence_digest": None,
            "workload_review_receipt_digest": None,
            "workload_review_signature_digest": None,
        },
        "R2-AUTH-002-D1",
        (
            "Authorize, revise, or hold an exact content-addressed workload evidence plan binding "
            "the population, sampling frame, strata, thresholds, counts, roles, and decision rule."
        ),
        ("AUTHORIZE_WORKLOAD_EVIDENCE_PLAN", "REVISE", "HOLD"),
        {
            "two_stage_decision_contract": {
                "stage_a": {
                    "adequacy_effect": "NONE",
                    "current_authority_rule": (
                        "D1_AUTHORIZATION_MUST_BE_REVERIFIED_UNDER_CURRENT_POLICY_REVOCATION_"
                        "TRUSTED_TIME_CUSTODY_AND_SEPARATION_BEFORE_D2"
                    ),
                    "decision_id": "R2-AUTH-002-D1",
                    "detached_receipt_digest": None,
                    "options": ["AUTHORIZE_WORKLOAD_EVIDENCE_PLAN", "REVISE", "HOLD"],
                    "purpose": "AUTHORIZE_OR_REVISE_EVIDENCE_PLAN_ONLY",
                    "receipt_status": "DETACHED_RECEIPT_REQUIRED_NOT_SUPPLIED",
                },
                "stage_b": {
                    "adequate_acceptance_rule": (
                        "ADEQUATE_REQUIRES_EVERY_REQUIRED_RAW_ARTIFACT_AND_STRATUM_BOUND_ALL_"
                        "NONZERO_COUNTS_RECONCILED_ALL_CRITERIA_EVALUATED_ZERO_BLOCKING_GAPS_"
                        "AND_FRESH_CURRENT_AUTHORITY"
                    ),
                    "decision_id": "R2-AUTH-002-D2",
                    "options": ["ADEQUATE", "INADEQUATE", "ABSTAIN"],
                    "prerequisite_binding_rule": ("MUST_BIND_IMMUTABLE_R2_AUTH_002_D1_STAGE_A_RECEIPT_SHA256"),
                    "stage_a_current_authority_rule": (
                        "MUST_REVERIFY_D1_SIGNER_POLICY_REVOCATION_TRUSTED_TIME_CUSTODY_AND_"
                        "SEPARATION_AT_D2_CONSUMPTION"
                    ),
                    "receipt_schema": DECISION_RECEIPT_SCHEMA,
                    "receipt_status": "DETACHED_RECEIPT_REQUIRED_NOT_SUPPLIED",
                    "receipt_values": {
                        field: None
                        for field in sorted(
                            (
                                *BASE_DECISION_RECEIPT_FIELDS,
                                *AUTH_002_STAGE_B_RECEIPT_FIELDS,
                            )
                        )
                    },
                    "required_receipt_fields": sorted(
                        (
                            *BASE_DECISION_RECEIPT_FIELDS,
                            *AUTH_002_STAGE_B_RECEIPT_FIELDS,
                        )
                    ),
                },
            },
        },
        receipt_binding_fields=AUTH_002_STAGE_A_RECEIPT_FIELDS,
    )


def _authority_004(snapshot: GitSnapshot, source_freeze_digest: str) -> dict[str, Any]:
    return _decision_packet(
        snapshot,
        source_freeze_digest,
        "R2-AUTH-004",
        "Trust policy, key custody, revocation/time evidence, and reviewer separation",
        (
            "CANDIDATE_SOURCE_ACCOUNTABLE_SELECTION_PENDING",
            "TRUST_POLICY_ISSUER_AND_POLICY_DIGEST_UNRESOLVED",
            "KEY_IDENTITY_CUSTODY_AND_SUCCESSION_UNRESOLVED",
            "REVOCATION_COMPLETENESS_AND_TRUSTED_TIME_EVIDENCE_NOT_SUPPLIED",
            "REVIEWER_PRODUCER_COLLECTOR_BUILDER_SEPARATION_NOT_ACCOUNTABLY_ESTABLISHED",
            "GLOBAL_ANTI_ROLLBACK_CUSTODY_NOT_SUPPLIED",
        ),
        (
            "AUTHENTICATED_CURRENT_TRUST_POLICIES_FOR_EACH_AUTHORITY_LANE",
            "CONTENT_ADDRESSED_PUBLIC_KEYS_AND ACCOUNTABLE_KEY_CUSTODY",
            "KEY_VALIDITY_SUCCESSION_AND_GLOBAL_ANTI_ROLLBACK_RULES",
            "COMPLETE_REVOCATION_VIEW_AND_TRUSTED_EVALUATION_TIME",
            "ACCOUNTABLE_REVIEWER_SEPARATION_AND_IDENTITY_COLLISION_RULES",
        ),
        {
            "accountable_owner": None,
            "anti_rollback_custodian": None,
            "approval": None,
            "independent_reviewer": None,
            "key_custodian": None,
            "key_succession_policy": "UNRESOLVED",
            "public_key_digest": None,
            "reviewer_separation_policy": "UNRESOLVED",
            "revocation_evidence_digest": None,
            "trust_policy_digest": None,
            "trust_policy_issuer": None,
            "trusted_time_evidence_digest": None,
        },
        "R2-AUTH-004-D1",
        (
            "Approve the proposed P1 validation mechanics for implementation or hold them; this "
            "choice neither designates an operational authority nor closes R2-AUTH-004."
        ),
        ("APPROVE_PROFILE_P1_FOR_IMPLEMENTATION", "HOLD_R2_AUTH_004"),
        {
            "proposed_control_profile": {
                "actual_bindings": {
                    "authority_namespace": None,
                    "candidate_bindings_digest": None,
                    "cumulative_revocation_ledger_digest": None,
                    "cumulative_revocation_ledger_high_water_mark": None,
                    "custody_locations": None,
                    "genesis_root_authority_basis_digest": None,
                    "key_digests": None,
                    "policy_id": None,
                    "policy_ledger_digest": None,
                    "policy_sequence": None,
                    "policy_valid_from": None,
                    "policy_valid_until": None,
                    "predecessor_policy_digest": None,
                    "principals": None,
                    "review_receipt_valid_from": None,
                    "review_receipt_valid_until": None,
                    "review_receipt_digest": None,
                    "reviewer_separation_decision_digest": None,
                    "revocation_observation_sequence": None,
                    "selected_policy_digest": None,
                    "trusted_evaluated_at": None,
                    "trusted_time_evidence_digest": None,
                },
                "controls": [
                    "SEPARATE_SIGNING_KEYS_PER_AUTHORITY_LANE",
                    "TWO_PERSON_CONTROL_WITH_OFFLINE_OR_HARDWARE_BACKED_CUSTODY_AND_QUORUM_RECOVERY",
                    "AUTHORITY_SIGNED_PREDECESSOR_LINKED_MONOTONIC_POLICY_SELECTION_SUCCESSION_RECEIPT",
                    "CUMULATIVE_NON_REMOVABLE_KEY_AND_RECEIPT_REVOCATION_HISTORY",
                    "TRUSTED_TIMESTAMP_EVALUATION_TIME_AND_EXPLICIT_POLICY_RECEIPT_EXPIRY",
                    "SIGNED_EXTERNALLY_GROUNDED_IDENTITY_AND_ROLE_CONFLICT_SEPARATION_DECISION",
                ],
                "profile_id": "P1",
                "status": "PROPOSED_UNAPPROVED",
            },
        },
        receipt_binding_fields=("control_profile_digest",),
    )


def _readme(snapshot: GitSnapshot) -> bytes:
    return (
        "# Atlas Release 2 authority candidate package\n\n"
        "Status: `PENDING_ACCOUNTABLE_SELECTION` and non-authoritative.\n\n"
        f"Proposed exact commit: `{snapshot.subject.commit}`  \n"
        f"Proposed exact tree: `{snapshot.subject.tree}`\n\n"
        "This package freezes Git-object source custody and supplies decision-template-ready packets "
        "for "
        "R2-AUTH-001, R2-AUTH-002, and R2-AUTH-004. It records no external decision. All accountable "
        "owners, reviewers, policies, keys, signatures, corpora, thresholds, approvals, trusted time, "
        "and revocation evidence remain null or unresolved.\n\n"
        "Never edit this package to record a choice. An actual choice requires a separate canonical "
        "`atlas.r2-authority-decision-receipt/1` receipt bound to the exact package-manifest and "
        "source-freeze SHA-256 values, candidate commit/tree, authority and decision IDs, reason, "
        "accountable principal and organization, authority basis, issued time, signer key, public-key "
        "digest, signature algorithm, payload digest, and detached signature. This package contains "
        "only a receipt template, generates no key or signature, and provides no decision-receipt "
        "consumer or authority verifier.\n\n"
        "QCP-001 remains `EXPERIMENTAL` / `CONTRACT_ONLY`; runtime remains "
        "`PARTIAL_NONPORTABLE_PROTOTYPE`; Release 3 remains `DISCOVERY_PLANNING_ONLY`.\n\n"
        "`source-freeze.json` enumerates every Git blob in the proposed commit. `source.tar` is a "
        "deterministic tar of every listed Git blob and deliberately ignores export-ignore attributes. "
        "`package-manifest.json` closes the member "
        "set and binds every other package member by byte count and SHA-256. Verification regenerates "
        "all material from the current exact Git subject and rejects tracked drift or package tamper.\n"
    ).encode("utf-8")


def _member_rows(members: Mapping[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "byte_count": len(members[path]),
            "path": path,
            "sha256": bytes_digest(members[path]),
        }
        for path in PACKAGE_MEMBERS
    ]


def _manifest(snapshot: GitSnapshot, members: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "authority": _empty_authority(),
        "candidate_selection": {
            "approval": None,
            "decision": None,
            "state": "PENDING_ACCOUNTABLE_SELECTION",
        },
        "closed_member_set": list(PACKAGE_MEMBERS),
        "manifest_self_digest": None,
        "member_count": len(PACKAGE_MEMBERS),
        "members": _member_rows(members),
        "package_status": "DECISION_TEMPLATE_READY_NON_AUTHORITATIVE_CANDIDATE",
        "proposed_candidate_commit": snapshot.subject.commit,
        "proposed_candidate_tree": snapshot.subject.tree,
        "release_boundaries": _release_boundaries(),
        "schema": PACKAGE_SCHEMA,
    }


def _expected_package(snapshot: GitSnapshot) -> dict[str, bytes]:
    source_freeze_raw = canonical_json_bytes(_source_freeze(snapshot))
    source_freeze_digest = bytes_digest(source_freeze_raw)
    members = {
        "R2-AUTH-001.json": canonical_json_bytes(_authority_001(snapshot, source_freeze_digest)),
        "R2-AUTH-002.json": canonical_json_bytes(_authority_002(snapshot, source_freeze_digest)),
        "R2-AUTH-004.json": canonical_json_bytes(_authority_004(snapshot, source_freeze_digest)),
        "README.md": _readme(snapshot),
        "source-freeze.json": source_freeze_raw,
        "source.tar": snapshot.archive_raw,
    }
    if tuple(sorted(members)) != PACKAGE_MEMBERS:
        _fail("INTERNAL_PACKAGE_MEMBER_SET_INVALID")
    return {**members, PACKAGE_MANIFEST: canonical_json_bytes(_manifest(snapshot, members))}


def _parse_canonical_object(raw: bytes, path: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidatePackageError(f"PACKAGE_JSON_INVALID:{path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        _fail("PACKAGE_JSON_NOT_CANONICAL_OBJECT", path)
    return value


def _validate_actual_manifest(package: Path, raw: bytes) -> dict[str, Any]:
    manifest = _parse_canonical_object(raw, PACKAGE_MANIFEST)
    if (
        manifest.get("schema") != PACKAGE_SCHEMA
        or manifest.get("closed_member_set") != list(PACKAGE_MEMBERS)
        or manifest.get("member_count") != len(PACKAGE_MEMBERS)
        or manifest.get("manifest_self_digest") is not None
    ):
        _fail("PACKAGE_MANIFEST_BOUNDARY_INVALID")
    rows = manifest.get("members")
    if type(rows) is not list or [row.get("path") for row in rows if type(row) is dict] != list(PACKAGE_MEMBERS):
        _fail("PACKAGE_MANIFEST_MEMBER_SET_INVALID")
    for row in rows:
        if type(row) is not dict or set(row) != {"byte_count", "path", "sha256"}:
            _fail("PACKAGE_MANIFEST_MEMBER_ROW_INVALID")
        member_raw = (package / row["path"]).read_bytes()
        if row["byte_count"] != len(member_raw) or row["sha256"] != bytes_digest(member_raw):
            _fail("PACKAGE_MANIFEST_MEMBER_BINDING_MISMATCH", row["path"])
    return manifest


def _validate_directory(package: Path) -> None:
    actual: set[str] = set()
    for child in package.iterdir():
        if child.is_symlink() or not child.is_file():
            _fail("PACKAGE_NON_REGULAR_MEMBER", child.name)
        actual.add(child.name)
    if actual != PACKAGE_FILES:
        _fail("PACKAGE_CLOSED_MEMBER_SET_MISMATCH")


def _verify_expected_bytes(package: Path, expected: Mapping[str, bytes]) -> None:
    _validate_directory(package)
    _validate_actual_manifest(package, (package / PACKAGE_MANIFEST).read_bytes())
    for path in (*PACKAGE_MEMBERS, PACKAGE_MANIFEST):
        if (package / path).read_bytes() != expected[path]:
            _fail("PACKAGE_MEMBER_DRIFT", path)


def build_package(
    repository: Path,
    output: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> dict[str, Any]:
    """Build a new candidate package without changing Git or overwriting any path."""

    snapshot = _snapshot(repository, expected_commit, expected_tree)
    output = output.resolve(strict=False)
    if output.exists() or output.is_symlink():
        _fail("OUTPUT_PATH_ALREADY_EXISTS")
    if not output.parent.is_dir():
        _fail("OUTPUT_PARENT_NOT_FOUND")
    if _is_within(output, snapshot.subject.git_directory):
        _fail("OUTPUT_INSIDE_GIT_DIRECTORY_REFUSED")
    expected = _expected_package(snapshot)
    output.mkdir()
    for path in (*PACKAGE_MEMBERS, PACKAGE_MANIFEST):
        with (output / path).open("xb") as stream:
            stream.write(expected[path])
    final_subject = _read_subject(snapshot.subject.repository)
    _assert_tracked_worktree_clean(final_subject)
    if final_subject != snapshot.subject:
        _fail("GIT_SUBJECT_CHANGED_DURING_BUILD")
    _verify_expected_bytes(output, expected)
    return _parse_canonical_object(expected[PACKAGE_MANIFEST], PACKAGE_MANIFEST)


def verify_package(
    repository: Path,
    package: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> dict[str, Any]:
    """Verify a closed package against the repository's exact current clean HEAD."""

    package = _resolved_directory(package, "PACKAGE_DIRECTORY_NOT_FOUND")
    snapshot = _snapshot(repository, expected_commit, expected_tree)
    expected = _expected_package(snapshot)
    _verify_expected_bytes(package, expected)
    return _parse_canonical_object(expected[PACKAGE_MANIFEST], PACKAGE_MANIFEST)


def _command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    build = subparsers.add_parser("build", help="build a new candidate package")
    build.add_argument("--repository", type=Path, default=ROOT)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--expected-commit", required=True)
    build.add_argument("--expected-tree", required=True)
    verify = subparsers.add_parser("verify", help="verify an existing candidate package")
    verify.add_argument("--repository", type=Path, default=ROOT)
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--expected-commit", required=True)
    verify.add_argument("--expected-tree", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _command_parser().parse_args(argv)
    if args.mode == "build":
        manifest = build_package(
            args.repository,
            args.output,
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
        )
        target = args.output
    else:
        manifest = verify_package(
            args.repository,
            args.package,
            expected_commit=args.expected_commit,
            expected_tree=args.expected_tree,
        )
        target = args.package
    print(
        f"{args.mode} verified {target}: {manifest['proposed_candidate_commit']} {manifest['proposed_candidate_tree']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
