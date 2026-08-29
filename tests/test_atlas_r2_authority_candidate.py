"""Exact-source and authority-boundary tests for the Atlas R2 candidate package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from typing import Any, Callable

import pytest

from tools import build_atlas_r2_authority_candidate as candidate


EXPECTED_BASE_RECEIPT_FIELDS = {
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
}
EXPECTED_AUTH_002_STAGE_A_FIELDS = {
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
}
EXPECTED_AUTH_002_STAGE_B_FIELDS = {
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
}

LEGACY_8C_COMMIT = "8c79277661f3728406409c95c664a9105050db81"
LEGACY_8C_TREE = "49b782307712750ea454d0e623f287c00cf2b587"
LEGACY_8C_PACKAGE_MANIFEST_SHA256 = "sha256:5589a57572fd8dae7e7f94d65eed816d63f527de8d1f7bc20f59428b6a85cf5f"
LEGACY_8C_SOURCE_FREEZE_SHA256 = "sha256:854a27a2b81fee7f92993e4f11122cb7d1219f9f344a3ecb8ee9437ce06120dd"
LEGACY_8C_SOURCE_TAR_SHA256 = "sha256:ce66e2ee8a76a1e9381270387acb350296b0205f0d22df99508d20c45473869c"


def _git(repository: Path, *arguments: str, environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


@pytest.fixture
def git_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "Atlas Test")
    _git(repository, "config", "user.email", "atlas-test@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "config", "core.eol", "lf")
    _git(repository, "config", "core.safecrlf", "true")
    (repository / ".gitattributes").write_bytes(b"* text eol=lf\n/src export-ignore\n")
    (repository / "README.md").write_bytes(b"# exact source\n")
    (repository / "src").mkdir()
    (repository / "src" / "main.py").write_bytes(b"print('atlas')\n")
    (repository / "script.sh").write_bytes(b"#!/bin/sh\nprintf 'atlas\\n'\n")
    consumer_path = repository / candidate.DECISION_CONSUMER_SOURCE_PATH
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_bytes(
        (Path(__file__).resolve().parents[1] / candidate.DECISION_CONSUMER_SOURCE_PATH).read_bytes()
    )
    for role, relative in candidate.MACHINE_OWNED_CANDIDATE_BINDINGS:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        value: dict[str, Any] = {"fixture_role": role}
        if role == "QCP_001":
            value.update(
                {
                    "execution_state": "CONTRACT_ONLY",
                    "qualification_state": "EXPERIMENTAL",
                }
            )
        elif role == "REFERENCE_RUNTIME_INVENTORY_V1":
            value["closure"] = {
                "complete_exact_runtime_closure": False,
                "state": "PARTIAL_NONPORTABLE_PROTOTYPE",
            }
        path.write_bytes(candidate.canonical_json_bytes(value))
    _git(repository, "add", ".")
    _git(repository, "update-index", "--chmod=+x", "script.sh")
    commit_environment = {
        **candidate._git_environment(),
        "GIT_AUTHOR_DATE": "2026-08-29T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-08-29T00:00:00+00:00",
    }
    _git(repository, "commit", "-q", "-m", "exact subject", environment=commit_environment)
    return repository


def _subject(repository: Path) -> tuple[str, str]:
    return (
        _git(repository, "rev-parse", "HEAD"),
        _git(repository, "rev-parse", "HEAD^{tree}"),
    )


def _commit_all(repository: Path, message: str) -> None:
    _git(repository, "add", ".")
    environment = {
        **candidate._git_environment(),
        "GIT_AUTHOR_DATE": "2026-08-29T00:01:00+00:00",
        "GIT_COMMITTER_DATE": "2026-08-29T00:01:00+00:00",
    }
    _git(repository, "commit", "-q", "-m", message, environment=environment)


def _build(repository: Path, output: Path) -> dict[str, Any]:
    commit, tree = _subject(repository)
    return candidate.build_package(
        repository,
        output,
        expected_commit=commit,
        expected_tree=tree,
    )


def _verify(repository: Path, package: Path) -> dict[str, Any]:
    commit, tree = _subject(repository)
    return candidate.verify_package(
        repository,
        package,
        expected_commit=commit,
        expected_tree=tree,
    )


def _object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    assert type(value) is dict
    assert raw == candidate.canonical_json_bytes(value)
    return value


def _rewrite_member_and_rechain(
    package: Path,
    member: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = _object(package / member)
    mutate(value)
    raw = candidate.canonical_json_bytes(value)
    (package / member).write_bytes(raw)
    manifest = _object(package / candidate.PACKAGE_MANIFEST)
    row = next(item for item in manifest["members"] if item["path"] == member)
    row["byte_count"] = len(raw)
    row["sha256"] = candidate.bytes_digest(raw)
    (package / candidate.PACKAGE_MANIFEST).write_bytes(candidate.canonical_json_bytes(manifest))


def _rechain_raw_member(package: Path, member: str, raw: bytes) -> None:
    (package / member).write_bytes(raw)
    manifest = _object(package / candidate.PACKAGE_MANIFEST)
    row = next(item for item in manifest["members"] if item["path"] == member)
    row["byte_count"] = len(raw)
    row["sha256"] = candidate.bytes_digest(raw)
    (package / candidate.PACKAGE_MANIFEST).write_bytes(candidate.canonical_json_bytes(manifest))


def test_build_and_verify_modes_are_deterministic_and_exact(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    first = tmp_path / "candidate-one"
    second = tmp_path / "candidate-two"
    commit, tree = _subject(git_repository)
    assert (
        candidate.main(
            [
                "build",
                "--repository",
                str(git_repository),
                "--output",
                str(first),
                "--expected-commit",
                commit,
                "--expected-tree",
                tree,
            ]
        )
        == 0
    )
    assert (
        candidate.main(
            [
                "build",
                "--repository",
                str(git_repository),
                "--output",
                str(second),
                "--expected-commit",
                commit,
                "--expected-tree",
                tree,
            ]
        )
        == 0
    )
    assert (
        candidate.main(
            [
                "verify",
                "--repository",
                str(git_repository),
                "--package",
                str(first),
                "--expected-commit",
                commit,
                "--expected-tree",
                tree,
            ]
        )
        == 0
    )

    assert {path.name for path in first.iterdir()} == candidate.PACKAGE_FILES
    for name in candidate.PACKAGE_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes()

    manifest = _object(first / candidate.PACKAGE_MANIFEST)
    assert manifest["schema"] == candidate.PACKAGE_SCHEMA
    assert manifest["package_status"] == (
        "DECISION_TEMPLATE_AND_STRUCTURAL_BINDER_SOURCE_BOUND_NON_AUTHORITATIVE_CANDIDATE"
    )
    assert manifest["closed_member_set"] == list(candidate.PACKAGE_MEMBERS)
    assert manifest["manifest_self_digest"] is None
    assert manifest["member_count"] == len(candidate.PACKAGE_MEMBERS)
    for row in manifest["members"]:
        raw = (first / row["path"]).read_bytes()
        assert row == {
            "byte_count": len(raw),
            "path": row["path"],
            "sha256": candidate.bytes_digest(raw),
        }

    freeze = _object(first / "source-freeze.json")
    assert freeze["source"]["proposed_candidate_commit"] == _git(git_repository, "rev-parse", "HEAD")
    assert freeze["source"]["proposed_candidate_tree"] == _git(git_repository, "rev-parse", "HEAD^{tree}")
    expected_paths = _git(git_repository, "ls-files").splitlines()
    assert freeze["source"]["blob_count"] == len(freeze["source"]["blobs"]) == len(expected_paths)
    assert [row["path"] for row in freeze["source"]["blobs"]] == sorted(expected_paths)
    assert freeze["source"]["git_configuration"] == {
        "core.autocrlf": "false",
        "core.eol": "lf",
        "core.safecrlf": "true",
    }
    assert [(row["role"], row["path"]) for row in freeze["machine_owned_candidate_bindings"]] == list(
        candidate.MACHINE_OWNED_CANDIDATE_BINDINGS
    )
    assert next(row for row in freeze["source"]["blobs"] if row["path"] == "script.sh")["mode"] == "100755"
    assert freeze["archive"]["format"] == "EXACT_GIT_BLOB_TAR/1"
    with tarfile.open(first / "source.tar", mode="r:") as archive:
        members = archive.getmembers()
        archived = {member.name for member in members}
        assert archived == {f"source/{path}" for path in expected_paths}
        assert "source/src/main.py" in archived  # `.gitattributes` marks `/src export-ignore`.
        for path in expected_paths:
            member = archive.getmember(f"source/{path}")
            stream = archive.extractfile(member)
            assert stream is not None
            assert stream.read() == _git_bytes(git_repository, "cat-file", "blob", f"HEAD:{path}")


def test_every_packet_preserves_incomplete_release_boundaries_and_null_authority(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    documents = [
        _object(package / "source-freeze.json"),
        _object(package / "R2-AUTH-001.json"),
        _object(package / "R2-AUTH-002.json"),
        _object(package / "R2-AUTH-004.json"),
        _object(package / candidate.PACKAGE_MANIFEST),
    ]
    freeze = documents[0]
    consumer_source = next(
        row for row in freeze["source"]["blobs"] if row["path"] == candidate.DECISION_CONSUMER_SOURCE_PATH
    )
    for value in documents:
        assert value["release_boundaries"] == {
            "candidate_selection": "PENDING_ACCOUNTABLE_SELECTION",
            "ga_decision": None,
            "promotion_decision": None,
            "publication_decision": None,
            "qcp_001": {
                "execution_state": "CONTRACT_ONLY",
                "qualification_state": "EXPERIMENTAL",
            },
            "qualification_decision": None,
            "release_2": "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
            "release_3": "DISCOVERY_PLANNING_ONLY",
            "runtime": "PARTIAL_NONPORTABLE_PROTOTYPE",
        }

    receipt_fields_by_packet = {
        "R2-AUTH-001.json": EXPECTED_BASE_RECEIPT_FIELDS
        | {
            "independent_provenance_plan_digest",
            "source_selection_basis_digest",
        },
        "R2-AUTH-002.json": EXPECTED_BASE_RECEIPT_FIELDS | EXPECTED_AUTH_002_STAGE_A_FIELDS,
        "R2-AUTH-004.json": EXPECTED_BASE_RECEIPT_FIELDS | {"control_profile_digest"},
    }
    for name in ("R2-AUTH-001.json", "R2-AUTH-002.json", "R2-AUTH-004.json"):
        packet = _object(package / name)
        assert packet["schema"] == candidate.DECISION_PACKET_SCHEMA
        assert packet["authoritative"] is False
        assert packet["packet_status"] == ("DECISION_TEMPLATE_READY_WITH_UNRESOLVED_ACCOUNTABLE_INPUTS")
        assert packet["decision_consumption_state"] == candidate.DECISION_CONSUMPTION_STATE
        assert packet["decision_consumer"] == {
            "binding_status": candidate.DECISION_CONSUMPTION_STATE,
            "consumer_source": consumer_source,
            "decision_effect": "NONE",
            "result_schema": candidate.DECISION_CONSUMER_RESULT_SCHEMA,
        }
        assert packet["accountable_decision"] == {
            "accountable_owner": None,
            "approval": None,
            "approved_at": None,
            "authoritative": False,
            "decision": None,
            "independent_reviewer": None,
            "signature": None,
        }
        assert packet["candidate_selection"] == {
            "approval": None,
            "decision": None,
            "selected_commit": None,
            "selected_tree": None,
            "state": "PENDING_ACCOUNTABLE_SELECTION",
        }
        assert packet["smallest_accountable_choice"]["recorded_choice"] is None
        receipt_contract = packet["detached_decision_receipt_contract"]
        assert receipt_contract["receipt_schema"] == candidate.DECISION_RECEIPT_SCHEMA
        assert receipt_contract["package_mutation_forbidden"] is True
        assert receipt_contract["status"] == "DETACHED_RECEIPT_REQUIRED_NOT_SUPPLIED"
        assert packet["structural_signing_contract"] == {
            "canonical_encoding": "ATLAS_CANONICAL_JSON/1",
            "detached_signature_field_semantics": ("SHA256_OF_EXACT_RAW_DETACHED_SIGNATURE_ARTIFACT"),
            "payload_digest_algorithm": "SHA-256",
            "payload_digest_scope": "CANONICAL_SIGNING_PAYLOAD_BYTES_ONLY",
            "self_binding_null_fields": ["detached_signature", "payload_digest"],
            "signature_artifact_encoding": "OPAQUE_EXACT_BYTES",
            "signing_domain_hex": candidate.DECISION_SIGNING_DOMAIN_HEX,
            "signing_material_construction": ("SIGNING_DOMAIN_BYTES_CONCAT_CANONICAL_SIGNING_PAYLOAD_BYTES"),
            "signing_payload_schema": candidate.DECISION_SIGNING_PAYLOAD_SCHEMA,
            "structural_verification_effect": "NONE",
        }
        assert receipt_contract["structural_signing_contract_ref"] == ("PACKET_STRUCTURAL_SIGNING_CONTRACT")
        assert receipt_contract["allowed_choices"] == packet["smallest_accountable_choice"]["options"]
        assert set(receipt_contract["required_receipt_fields"]) == receipt_fields_by_packet[name]
        assert set(receipt_contract["receipt_values"]) == receipt_fields_by_packet[name]
        assert all(value is None for value in receipt_contract["receipt_values"].values())
        assert packet["blockers"]
        assert packet["required_evidence"]
        assert all(value is None or value == "UNRESOLVED" for value in packet["unresolved_accountable_inputs"].values())

    assert set(_object(package / "R2-AUTH-001.json")["unresolved_accountable_inputs"]) == {
        "accountable_owner",
        "approval",
        "independent_reviewer",
        "key_custodian",
        "public_key_digest",
        "revocation_evidence_digest",
        "runtime_closure_evidence_digest",
        "runtime_closure_review_receipt_digest",
        "runtime_closure_review_signature_digest",
        "trust_policy_digest",
        "trusted_time_evidence_digest",
    }
    assert set(_object(package / "R2-AUTH-002.json")["unresolved_accountable_inputs"]) == {
        "accountable_owner",
        "adequacy_approval",
        "adequacy_thresholds",
        "corpus_digest",
        "corpus_owner",
        "inclusion_and_exclusion_rules",
        "independent_reviewer",
        "permitted_failures",
        "population",
        "sampling_frame",
        "selection_method_strata_and_weights",
        "trust_policy_digest",
        "workload_evidence_digest",
        "workload_review_receipt_digest",
        "workload_review_signature_digest",
    }
    assert set(_object(package / "R2-AUTH-004.json")["unresolved_accountable_inputs"]) == {
        "accountable_owner",
        "anti_rollback_custodian",
        "approval",
        "independent_reviewer",
        "key_custodian",
        "key_succession_policy",
        "public_key_digest",
        "reviewer_separation_policy",
        "revocation_evidence_digest",
        "trust_policy_digest",
        "trust_policy_issuer",
        "trusted_time_evidence_digest",
    }

    assert _object(package / "R2-AUTH-001.json")["smallest_accountable_choice"] == {
        "choice_id": "R2-AUTH-001-PRECONDITION-D1",
        "decision_id": "R2-AUTH-001-PRECONDITION-D1",
        "options": ["SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION", "REJECT_CANDIDATE", "HOLD"],
        "prompt": (
            "Select, reject, or hold the proposed exact commit and tree only as a precondition for "
            "R2-AUTH-001 evidence collection; selection does not close R2-AUTH-001 and leaves the "
            "R2-AUTH-006 source ceremony and provenance decision open."
        ),
        "recorded_choice": None,
    }
    authority_002 = _object(package / "R2-AUTH-002.json")
    assert authority_002["required_evidence"] == [
        "ACCOUNTABLY_SELECTED_EXACT_COMMIT_AND_TREE",
        "ACCOUNTABLE_WORKLOAD_OWNER_AND_INDEPENDENT_ADEQUACY_REVIEWER",
        "CONTENT_ADDRESSED_REPRESENTATIVE_WORKLOAD_CORPUS_AND_SAMPLING_FRAME",
        "TARGET_POPULATION_INCLUSION_EXCLUSION_SELECTION_STRATA_AND_WEIGHTS",
        "NONZERO_TARGET_ELIGIBLE_SELECTED_EXECUTED_VALID_AND_ASSESSED_COUNTS",
        "PREDECLARED_ADEQUACY_THRESHOLDS_AND_DECISION_RULE",
        "RAW_DENOMINATOR_CORPUS_INPUT_RECEIPT_COVERAGE_PROVENANCE_AND_GAP_BYTES",
        "MEASURED_RESULTS_BOUND_TO_EXACT_SOURCE_CORPUS_RUNTIME_AND_STAGE_A_RECEIPT",
        "INDEPENDENT_SIGNED_ADEQUACY_REVIEW_WITH_CURRENT_TRUST_EVIDENCE",
    ]
    assert authority_002["smallest_accountable_choice"]["options"] == [
        "AUTHORIZE_WORKLOAD_EVIDENCE_PLAN",
        "REVISE",
        "HOLD",
    ]
    assert authority_002["two_stage_decision_contract"]["stage_a"]["adequacy_effect"] == "NONE"
    assert authority_002["two_stage_decision_contract"]["stage_a"]["detached_receipt_digest"] is None
    stage_b = authority_002["two_stage_decision_contract"]["stage_b"]
    assert stage_b["decision_id"] == "R2-AUTH-002-D2"
    assert stage_b["options"] == ["ADEQUATE", "INADEQUATE", "ABSTAIN"]
    assert stage_b["prerequisite_binding_rule"] == ("MUST_BIND_IMMUTABLE_R2_AUTH_002_D1_STAGE_A_RECEIPT_SHA256")
    assert stage_b["structural_signing_contract_ref"] == "PACKET_STRUCTURAL_SIGNING_CONTRACT"
    assert set(stage_b["required_receipt_fields"]) == (EXPECTED_BASE_RECEIPT_FIELDS | EXPECTED_AUTH_002_STAGE_B_FIELDS)
    assert set(stage_b["receipt_values"]) == (EXPECTED_BASE_RECEIPT_FIELDS | EXPECTED_AUTH_002_STAGE_B_FIELDS)
    assert all(value is None for value in stage_b["receipt_values"].values())
    authority_004 = _object(package / "R2-AUTH-004.json")
    assert authority_004["smallest_accountable_choice"]["options"] == [
        "APPROVE_PROFILE_P1_FOR_IMPLEMENTATION",
        "HOLD_R2_AUTH_004",
    ]
    assert authority_004["proposed_control_profile"]["controls"] == [
        "SEPARATE_SIGNING_KEYS_PER_AUTHORITY_LANE",
        "TWO_PERSON_CONTROL_WITH_OFFLINE_OR_HARDWARE_BACKED_CUSTODY_AND_QUORUM_RECOVERY",
        "AUTHORITY_SIGNED_PREDECESSOR_LINKED_MONOTONIC_POLICY_SELECTION_SUCCESSION_RECEIPT",
        "CUMULATIVE_NON_REMOVABLE_KEY_AND_RECEIPT_REVOCATION_HISTORY",
        "TRUSTED_TIMESTAMP_EVALUATION_TIME_AND_EXPLICIT_POLICY_RECEIPT_EXPIRY",
        "SIGNED_EXTERNALLY_GROUNDED_IDENTITY_AND_ROLE_CONFLICT_SEPARATION_DECISION",
    ]
    assert authority_004["proposed_control_profile"]["status"] == "PROPOSED_UNAPPROVED"
    assert all(value is None for value in authority_004["proposed_control_profile"]["actual_bindings"].values())
    assert set(authority_004["proposed_control_profile"]["actual_bindings"]) == {
        "authority_namespace",
        "candidate_bindings_digest",
        "cumulative_revocation_ledger_digest",
        "cumulative_revocation_ledger_high_water_mark",
        "custody_locations",
        "genesis_root_authority_basis_digest",
        "key_digests",
        "policy_id",
        "policy_ledger_digest",
        "policy_sequence",
        "policy_valid_from",
        "policy_valid_until",
        "predecessor_policy_digest",
        "principals",
        "review_receipt_valid_from",
        "review_receipt_valid_until",
        "review_receipt_digest",
        "reviewer_separation_decision_digest",
        "revocation_observation_sequence",
        "selected_policy_digest",
        "trusted_evaluated_at",
        "trusted_time_evidence_digest",
    }


@pytest.mark.parametrize(
    "attack",
    ("commit", "tree", "path", "blob", "mode", "byte_count", "digest"),
)
def test_verify_rejects_rechained_source_identity_attacks(
    git_repository: Path,
    tmp_path: Path,
    attack: str,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)

    def mutate(value: dict[str, Any]) -> None:
        if attack == "commit":
            value["source"]["proposed_candidate_commit"] = "0" * 40
        elif attack == "tree":
            value["source"]["proposed_candidate_tree"] = "0" * 40
        elif attack == "path":
            value["source"]["blobs"][0]["path"] = "renamed"
        elif attack == "blob":
            value["source"]["blobs"][0]["blob"] = "0" * 40
        elif attack == "mode":
            value["source"]["blobs"][0]["mode"] = "100755"
        elif attack == "byte_count":
            value["source"]["blobs"][0]["byte_count"] += 1
        else:
            value["source"]["blobs"][0]["sha256"] = "sha256:" + "0" * 64

    _rewrite_member_and_rechain(package, "source-freeze.json", mutate)
    with pytest.raises(candidate.CandidatePackageError):
        _verify(git_repository, package)


@pytest.mark.parametrize("attack", ("archive", "packet", "member_digest"))
def test_verify_rejects_tamper_even_when_attacker_rechains_available_digests(
    git_repository: Path,
    tmp_path: Path,
    attack: str,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    if attack == "archive":
        _rechain_raw_member(package, "source.tar", (package / "source.tar").read_bytes() + b"tamper")
    elif attack == "packet":
        _rewrite_member_and_rechain(
            package,
            "R2-AUTH-001.json",
            lambda value: value.__setitem__("authoritative", True),
        )
    else:
        manifest = _object(package / candidate.PACKAGE_MANIFEST)
        manifest["members"][0]["sha256"] = "sha256:" + "0" * 64
        (package / candidate.PACKAGE_MANIFEST).write_bytes(candidate.canonical_json_bytes(manifest))
    with pytest.raises(candidate.CandidatePackageError):
        _verify(git_repository, package)


@pytest.mark.parametrize("attack", ("extra", "missing"))
def test_verify_enforces_the_closed_package_member_set(
    git_repository: Path,
    tmp_path: Path,
    attack: str,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    if attack == "extra":
        (package / "unexpected.txt").write_bytes(b"not allowed")
    else:
        (package / "README.md").unlink()
    with pytest.raises(candidate.CandidatePackageError):
        _verify(git_repository, package)


@pytest.mark.parametrize("state", ("unstaged", "staged"))
def test_build_and_verify_reject_dirty_tracked_files(
    git_repository: Path,
    tmp_path: Path,
    state: str,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    (git_repository / "src" / "main.py").write_bytes(b"print('drift')\n")
    if state == "staged":
        _git(git_repository, "add", "src/main.py")
    with pytest.raises(candidate.CandidatePackageError, match="TRACKED_WORKTREE_NOT_CLEAN"):
        _verify(git_repository, package)
    with pytest.raises(candidate.CandidatePackageError, match="TRACKED_WORKTREE_NOT_CLEAN"):
        _build(git_repository, tmp_path / "second")


def test_verify_rejects_a_package_after_repository_head_changes(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    package = tmp_path / "candidate"
    old_commit, old_tree = _subject(git_repository)
    candidate.build_package(
        git_repository,
        package,
        expected_commit=old_commit,
        expected_tree=old_tree,
    )
    (git_repository / "second.txt").write_bytes(b"new committed subject\n")
    _git(git_repository, "add", "second.txt")
    _git(git_repository, "commit", "-q", "-m", "different subject")
    with pytest.raises(candidate.CandidatePackageError, match="EXPECTED_COMMIT_MISMATCH"):
        candidate.verify_package(
            git_repository,
            package,
            expected_commit=old_commit,
            expected_tree=old_tree,
        )


def test_blob_digests_are_git_object_bytes_not_checkout_filter_bytes(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    freeze = _object(package / "source-freeze.json")
    for row in freeze["source"]["blobs"]:
        raw = subprocess.run(
            ["git", "cat-file", "blob", row["blob"]],
            cwd=git_repository,
            capture_output=True,
            check=True,
        ).stdout
        assert row["byte_count"] == len(raw)
        assert row["sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_git_replace_ref_cannot_relabel_replacement_bytes_as_original_subject(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    original_commit, original_tree = _subject(git_repository)
    (git_repository / "README.md").write_bytes(b"# replacement source\n")
    _commit_all(git_repository, "replacement subject")
    replacement_commit, _replacement_tree = _subject(git_repository)
    _git(git_repository, "replace", original_commit, replacement_commit)
    _git(
        git_repository,
        "--no-replace-objects",
        "checkout",
        "--detach",
        "-q",
        original_commit,
    )

    package = tmp_path / "candidate"
    candidate.build_package(
        git_repository,
        package,
        expected_commit=original_commit,
        expected_tree=original_tree,
    )
    freeze = _object(package / "source-freeze.json")
    assert freeze["source"]["proposed_candidate_commit"] == original_commit
    assert freeze["source"]["proposed_candidate_tree"] == original_tree
    with tarfile.open(package / "source.tar", mode="r:") as archive:
        stream = archive.extractfile("source/README.md")
        assert stream is not None
        assert stream.read() == b"# exact source\n"


@pytest.mark.parametrize("mismatch", ("commit", "tree"))
def test_build_and_verify_require_caller_pinned_exact_subject(
    git_repository: Path,
    tmp_path: Path,
    mismatch: str,
) -> None:
    commit, tree = _subject(git_repository)
    wrong_commit = "0" * len(commit) if mismatch == "commit" else commit
    wrong_tree = "0" * len(tree) if mismatch == "tree" else tree
    with pytest.raises(candidate.CandidatePackageError, match=f"EXPECTED_{mismatch.upper()}_MISMATCH"):
        candidate.build_package(
            git_repository,
            tmp_path / "refused",
            expected_commit=wrong_commit,
            expected_tree=wrong_tree,
        )

    package = tmp_path / "candidate"
    _build(git_repository, package)
    with pytest.raises(candidate.CandidatePackageError, match=f"EXPECTED_{mismatch.upper()}_MISMATCH"):
        candidate.verify_package(
            git_repository,
            package,
            expected_commit=wrong_commit,
            expected_tree=wrong_tree,
        )


@pytest.mark.parametrize(
    ("key", "bad_value"),
    (
        ("core.autocrlf", "true"),
        ("core.eol", "native"),
        ("core.safecrlf", "false"),
    ),
)
def test_build_and_verify_require_lf_exact_git_configuration(
    git_repository: Path,
    tmp_path: Path,
    key: str,
    bad_value: str,
) -> None:
    package = tmp_path / "candidate"
    _build(git_repository, package)
    commit, tree = _subject(git_repository)
    _git(git_repository, "config", key, bad_value)
    with pytest.raises(candidate.CandidatePackageError, match="LF_EXACT_GIT_CONFIG_REQUIRED"):
        candidate.verify_package(
            git_repository,
            package,
            expected_commit=commit,
            expected_tree=tree,
        )
    with pytest.raises(candidate.CandidatePackageError, match="LF_EXACT_GIT_CONFIG_REQUIRED"):
        candidate.build_package(
            git_repository,
            tmp_path / "refused",
            expected_commit=commit,
            expected_tree=tree,
        )


def test_required_machine_owned_candidate_path_cannot_be_omitted(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    missing = candidate.MACHINE_OWNED_CANDIDATE_BINDINGS[0][1]
    _git(git_repository, "rm", "--", missing)
    _git(git_repository, "commit", "-q", "-m", "remove required candidate fact")
    with pytest.raises(
        candidate.CandidatePackageError,
        match="REQUIRED_MACHINE_OWNED_CANDIDATE_PATH_MISSING",
    ):
        _build(git_repository, tmp_path / "refused")


def test_legacy_v1_package_without_structural_consumer_remains_verifiable(
    git_repository: Path,
    tmp_path: Path,
) -> None:
    _git(git_repository, "rm", "--", candidate.DECISION_CONSUMER_SOURCE_PATH)
    _git(git_repository, "commit", "-q", "-m", "legacy package without structural consumer")
    package = tmp_path / "legacy-v1"
    commit, tree = _subject(git_repository)
    with pytest.raises(
        candidate.CandidatePackageError,
        match="STRUCTURAL_DECISION_CONSUMER_REQUIRED_FOR_NEW_PACKAGE",
    ):
        candidate.build_package(
            git_repository,
            package,
            expected_commit=commit,
            expected_tree=tree,
        )
    snapshot = candidate._snapshot(git_repository, commit, tree)
    expected = candidate._expected_package(snapshot)
    package.mkdir()
    for name, raw in expected.items():
        (package / name).write_bytes(raw)
    manifest = _object(package / candidate.PACKAGE_MANIFEST)
    assert manifest["schema"] == candidate.PACKAGE_SCHEMA_V1
    assert manifest["package_status"] == "DECISION_TEMPLATE_READY_NON_AUTHORITATIVE_CANDIDATE"
    for name in ("R2-AUTH-001.json", "R2-AUTH-002.json", "R2-AUTH-004.json"):
        packet = _object(package / name)
        assert packet["schema"] == candidate.DECISION_PACKET_SCHEMA_V1
        assert packet["decision_consumption_state"] == candidate.LEGACY_DECISION_CONSUMPTION_STATE
        assert "decision_consumer" not in packet
        assert "structural_signing_contract" not in packet
        assert "structural_signing_contract_ref" not in packet["detached_decision_receipt_contract"]
    assert b"provides no decision-receipt consumer or authority verifier" in (package / "README.md").read_bytes()
    candidate.verify_package(
        git_repository,
        package,
        expected_commit=commit,
        expected_tree=tree,
    )


def test_known_8c_legacy_package_hashes_remain_stable(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    legacy_repository = tmp_path / "legacy-8c-repository"
    completed = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "clone",
            "-q",
            "--no-hardlinks",
            str(repository),
            str(legacy_repository),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _git(legacy_repository, "config", "core.autocrlf", "false")
    _git(legacy_repository, "config", "core.eol", "lf")
    _git(legacy_repository, "config", "core.safecrlf", "true")
    _git(legacy_repository, "checkout", "--detach", "-q", LEGACY_8C_COMMIT)
    snapshot = candidate._snapshot(legacy_repository, LEGACY_8C_COMMIT, LEGACY_8C_TREE)
    expected = candidate._expected_package(snapshot)
    assert candidate.bytes_digest(expected[candidate.PACKAGE_MANIFEST]) == (LEGACY_8C_PACKAGE_MANIFEST_SHA256)
    assert candidate.bytes_digest(expected["source-freeze.json"]) == LEGACY_8C_SOURCE_FREEZE_SHA256
    assert candidate.bytes_digest(expected["source.tar"]) == LEGACY_8C_SOURCE_TAR_SHA256
    assert json.loads(expected[candidate.PACKAGE_MANIFEST])["schema"] == candidate.PACKAGE_SCHEMA_V1


@pytest.mark.parametrize(
    ("role", "mutate", "error"),
    (
        (
            "QCP_001",
            lambda value: value.update({"qualification_state": "QUALIFIED"}),
            "QCP_001_RELEASE_BOUNDARY_MISMATCH",
        ),
        (
            "REFERENCE_RUNTIME_INVENTORY_V1",
            lambda value: value["closure"].update(
                {
                    "complete_exact_runtime_closure": True,
                    "state": "COMPLETE_EXACT_RUNTIME_CLOSURE",
                }
            ),
            "RUNTIME_RELEASE_BOUNDARY_MISMATCH",
        ),
    ),
)
def test_machine_owned_status_contradiction_is_refused(
    git_repository: Path,
    tmp_path: Path,
    role: str,
    mutate: Callable[[dict[str, Any]], None],
    error: str,
) -> None:
    relative = dict(candidate.MACHINE_OWNED_CANDIDATE_BINDINGS)[role]
    path = git_repository / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_bytes(candidate.canonical_json_bytes(value))
    _commit_all(git_repository, "contradict machine owner")
    with pytest.raises(candidate.CandidatePackageError, match=error):
        _build(git_repository, tmp_path / "candidate")


def test_ssot_registry_and_protocol_claim_boundaries_are_pinned() -> None:
    root = Path(__file__).resolve().parents[1]
    ssot = (root / "docs" / "ssot.md").read_text(encoding="utf-8")
    protocol = (root / "docs" / "atlas-release-2-authority-candidate-protocol-2026-08-29.md").read_text(
        encoding="utf-8"
    )
    assert "**Atlas Release 2 exact authority-candidate package**" in ssot
    assert "`tools/build_atlas_r2_authority_candidate.py`" in ssot
    assert "local Git object database" in ssot
    assert "do not prove remote origin" in ssot
    for boundary in (
        "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
        "EXPERIMENTAL` / `CONTRACT_ONLY",
        "PARTIAL_NONPORTABLE_PROTOTYPE",
        "DISCOVERY_PLANNING_ONLY",
        "decision-template-ready and structural-binder-source-bound",
        "atlas.r2-authority-candidate-package/2",
        "SHA256_OF_EXACT_RAW_DETACHED_SIGNATURE_ARTIFACT",
        "R2-AUTH-001-PRECONDITION-D1",
        "R2-AUTH-002-D1",
        "APPROVE_PROFILE_P1_FOR_IMPLEMENTATION",
        "regardless of\n  `export-ignore` attributes",
    ):
        assert boundary in protocol
