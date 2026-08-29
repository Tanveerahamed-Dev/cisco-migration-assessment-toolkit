"""Adversarial tests for the non-authoritative Atlas R2 receipt binder."""

from __future__ import annotations

from dataclasses import fields, FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from tools import build_atlas_r2_authority_candidate as candidate
from tools import bind_atlas_r2_authority_decision as decision


REPOSITORY_NAMESPACE = "Tanveerahamed-Dev/cisco-migration-assessment-toolkit"
ZERO_DIGEST = "sha256:" + "0" * 64


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


@pytest.fixture(scope="module")
def exact_candidate(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp("authority-decision-subject")
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
    consumer_path = repository / candidate.DECISION_CONSUMER_SOURCE_PATH
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_bytes(Path(decision.__file__).read_bytes())
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
    _git(repository, "update-index", "--chmod=+x", "README.md")
    environment = {
        **candidate._git_environment(),
        "GIT_AUTHOR_DATE": "2026-08-29T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-08-29T00:00:00+00:00",
    }
    _git(repository, "commit", "-q", "-m", "exact subject", environment=environment)
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    package = tmp_path / "candidate"
    candidate.build_package(
        repository,
        package,
        expected_commit=commit,
        expected_tree=tree,
    )
    return {
        "commit": commit,
        "manifest_digest": decision.bytes_digest((package / candidate.PACKAGE_MANIFEST).read_bytes()),
        "package": package,
        "repository": repository,
        "source_freeze_digest": decision.bytes_digest((package / "source-freeze.json").read_bytes()),
        "tree": tree,
    }


def _object(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _contract(packet: dict[str, Any], decision_id: str) -> dict[str, Any]:
    if packet["smallest_accountable_choice"]["decision_id"] == decision_id:
        return packet["detached_decision_receipt_contract"]
    stage_b = packet["two_stage_decision_contract"]["stage_b"]
    assert stage_b["decision_id"] == decision_id
    return {
        "allowed_choices": stage_b["options"],
        "required_receipt_fields": stage_b["required_receipt_fields"],
    }


def _material(
    subject: dict[str, Any],
    authority_id: str,
    decision_id: str,
    choice: str,
) -> dict[str, Any]:
    package: Path = subject["package"]
    packet = _object(package / decision.AUTHORITY_PACKET_FILES[authority_id])
    contract = _contract(packet, decision_id)
    signature_artifact = b"TEST-ONLY OPAQUE DETACHED SIGNATURE ARTIFACT\n"
    public_key_artifact = b"TEST-ONLY OPAQUE PUBLIC KEY ARTIFACT\n"
    artifact_raw: dict[str, bytes] = {}
    receipt: dict[str, Any] = {"schema": decision.DECISION_RECEIPT_SCHEMA}
    special: dict[str, Any] = {
        "accountable_principal": "SYNTHETIC TEST PRINCIPAL",
        "accountable_principal_organization": "SYNTHETIC TEST ORGANIZATION",
        "authority_id": authority_id,
        "candidate_commit": subject["commit"],
        "candidate_tree": subject["tree"],
        "choice": choice,
        "decision_id": decision_id,
        "detached_signature": decision.bytes_digest(signature_artifact),
        "issued_at": "2026-08-29T01:00:00Z",
        "package_manifest_sha256": subject["manifest_digest"],
        "payload_digest": ZERO_DIGEST,
        "public_key_digest": decision.bytes_digest(public_key_artifact),
        "reason": "Synthetic test fixture; not an accountable decision.",
        "repository_namespace": REPOSITORY_NAMESPACE,
        "signature_algorithm": "TEST_ONLY_OPAQUE_ALGORITHM",
        "signer_key_id": "SYNTHETIC-TEST-KEY",
        "source_freeze_sha256": subject["source_freeze_digest"],
    }
    for field in contract["required_receipt_fields"]:
        if field in special:
            receipt[field] = special[field]
        elif field.endswith("_high_water_mark"):
            receipt[field] = 7
        elif field.endswith("_valid_until"):
            receipt[field] = "2026-08-30T01:00:00Z"
        elif field.endswith("_digest") or field.endswith("_sha256"):
            if field == "control_profile_digest":
                raw = decision.canonical_json_bytes(packet["proposed_control_profile"])
            else:
                raw = f"SYNTHETIC TEST ARTIFACT FOR {field}\n".encode("ascii")
            artifact_raw[field] = raw
            receipt[field] = decision.bytes_digest(raw)
        else:
            raise AssertionError(f"test fixture has no value rule for {field}")
    receipt["payload_digest"] = decision.bytes_digest(decision.normalized_decision_payload_bytes(receipt))
    return {
        "artifacts": artifact_raw,
        "packet": packet,
        "public_key": public_key_artifact,
        "receipt": receipt,
        "receipt_raw": decision.canonical_json_bytes(receipt),
        "signature": signature_artifact,
    }


def _bind(
    subject: dict[str, Any],
    material: dict[str, Any],
    *,
    authority_id: str,
    decision_id: str,
    **overrides: Any,
) -> decision.BoundUnverifiedR2AuthorityDecisionReceipt:
    arguments: dict[str, Any] = {
        "repository": subject["repository"],
        "package": subject["package"],
        "expected_commit": subject["commit"],
        "expected_tree": subject["tree"],
        "expected_repository_namespace": REPOSITORY_NAMESPACE,
        "expected_package_manifest_sha256": subject["manifest_digest"],
        "expected_source_freeze_sha256": subject["source_freeze_digest"],
        "authority_id": authority_id,
        "decision_id": decision_id,
        "receipt_raw": material["receipt_raw"],
        "signature_artifact_raw": material["signature"],
        "public_key_artifact_raw": material["public_key"],
        "artifact_raw_by_field": material["artifacts"],
    }
    arguments.update(overrides)
    return decision.bind_unverified_r2_authority_decision_receipt_bytes(**arguments)


def _rechain(material: dict[str, Any], **changes: Any) -> bytes:
    receipt = dict(material["receipt"])
    receipt.update(changes)
    receipt["payload_digest"] = ZERO_DIGEST
    receipt["payload_digest"] = decision.bytes_digest(decision.normalized_decision_payload_bytes(receipt))
    return decision.canonical_json_bytes(receipt)


def test_successor_package_binds_and_exercises_this_exact_binder_source(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    package = tmp_path / "successor-package"
    candidate.build_package(
        repository,
        package,
        expected_commit=commit,
        expected_tree=tree,
    )
    subject = {
        "commit": commit,
        "manifest_digest": decision.bytes_digest((package / candidate.PACKAGE_MANIFEST).read_bytes()),
        "package": package,
        "repository": repository,
        "source_freeze_digest": decision.bytes_digest((package / "source-freeze.json").read_bytes()),
        "tree": tree,
    }
    packet = _object(package / "R2-AUTH-001.json")
    binder_raw = Path(decision.__file__).read_bytes()
    assert packet["decision_consumer"]["consumer_source"] == {
        "blob": _git(repository, "rev-parse", f"HEAD:{candidate.DECISION_CONSUMER_SOURCE_PATH}"),
        "byte_count": len(binder_raw),
        "mode": "100644",
        "path": candidate.DECISION_CONSUMER_SOURCE_PATH,
        "sha256": decision.bytes_digest(binder_raw),
    }
    material = _material(subject, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    bound = _bind(
        subject,
        material,
        authority_id="R2-AUTH-001",
        decision_id="R2-AUTH-001-PRECONDITION-D1",
    )
    assert bound.as_dict()["decision_effect"] == "NONE"


def test_legacy_v1_package_verifies_but_cannot_mint_a_structural_binding(
    exact_candidate: dict[str, Any],
    tmp_path: Path,
) -> None:
    legacy_repository = tmp_path / "legacy-repository"
    completed = subprocess.run(
        ["git", "clone", "-q", str(exact_candidate["repository"]), str(legacy_repository)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _git(legacy_repository, "config", "user.name", "Atlas Test")
    _git(legacy_repository, "config", "user.email", "atlas-test@example.invalid")
    _git(legacy_repository, "config", "core.autocrlf", "false")
    _git(legacy_repository, "config", "core.eol", "lf")
    _git(legacy_repository, "config", "core.safecrlf", "true")
    _git(legacy_repository, "rm", "--", candidate.DECISION_CONSUMER_SOURCE_PATH)
    _git(legacy_repository, "commit", "-q", "-m", "legacy source without structural binder")
    commit = _git(legacy_repository, "rev-parse", "HEAD")
    tree = _git(legacy_repository, "rev-parse", "HEAD^{tree}")
    snapshot = candidate._snapshot(legacy_repository, commit, tree)
    expected = candidate._expected_package(snapshot)
    package = tmp_path / "legacy-package"
    package.mkdir()
    for name, raw in expected.items():
        (package / name).write_bytes(raw)
    candidate.verify_package(
        legacy_repository,
        package,
        expected_commit=commit,
        expected_tree=tree,
    )
    subject = {
        "commit": commit,
        "manifest_digest": decision.bytes_digest((package / candidate.PACKAGE_MANIFEST).read_bytes()),
        "package": package,
        "repository": legacy_repository,
        "source_freeze_digest": decision.bytes_digest((package / "source-freeze.json").read_bytes()),
        "tree": tree,
    }
    material = _material(subject, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="candidate_package_v2_required",
    ):
        _bind(
            subject,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
        )


@pytest.mark.parametrize(
    ("authority_id", "decision_id", "choice"),
    (
        ("R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD"),
        ("R2-AUTH-002", "R2-AUTH-002-D1", "AUTHORIZE_WORKLOAD_EVIDENCE_PLAN"),
        ("R2-AUTH-002", "R2-AUTH-002-D1", "REVISE"),
        ("R2-AUTH-002", "R2-AUTH-002-D1", "HOLD"),
        ("R2-AUTH-002", "R2-AUTH-002-D2", "ADEQUATE"),
        ("R2-AUTH-002", "R2-AUTH-002-D2", "INADEQUATE"),
        ("R2-AUTH-002", "R2-AUTH-002-D2", "ABSTAIN"),
        ("R2-AUTH-004", "R2-AUTH-004-D1", "APPROVE_PROFILE_P1_FOR_IMPLEMENTATION"),
        ("R2-AUTH-004", "R2-AUTH-004-D1", "HOLD_R2_AUTH_004"),
    ),
)
def test_all_current_decision_contracts_bind_with_zero_effect(
    exact_candidate: dict[str, Any],
    authority_id: str,
    decision_id: str,
    choice: str,
) -> None:
    material = _material(exact_candidate, authority_id, decision_id, choice)
    bound = _bind(
        exact_candidate,
        material,
        authority_id=authority_id,
        decision_id=decision_id,
    )
    result = bound.as_dict()
    assert result["schema"] == decision.STRUCTURAL_BINDING_SCHEMA
    assert result["authority_id"] == authority_id
    assert result["binding_status"] == "STRUCTURALLY_BOUND_EXTERNAL_AUTHORITY_UNVERIFIED"
    assert result["decision_effect"] == "NONE"
    assert result["declared_choice"] == choice
    assert result["binding_evidence_scope"] == (
        "Recomputable content-binding output only; class identity and emitted JSON are not "
        "unforgeable proof that validation ran."
    )
    assert result["r2_auth_004_profile_status"] == "PROPOSED_UNAPPROVED"
    assert result["unevaluated_external_domains"] == [
        "ACCOUNTABLE_PRINCIPAL_AND_ORGANIZATIONAL_AUTHORITY",
        "GOVERNING_POLICY_SELECTION_AND_CURRENTNESS",
        "SIGNATURE_ALGORITHM_KEY_AUTHORIZATION_AND_CRYPTOGRAPHIC_VALIDITY",
        "REVOCATION_STATUS_AND_HISTORY",
        "ISSUED_TIME_RECEIPT_LIFETIME_AND_TRUSTED_TIME",
        "KEY_CUSTODY_AND_REVIEWER_ORGANIZATIONAL_SEPARATION",
        "EFFECTIVE_RECEIPT_SELECTION_AND_CONFLICT_RESOLUTION",
    ]
    assert result["receipt_byte_count"] == len(material["receipt_raw"])
    expected_artifacts = {
        "detached_signature": material["signature"],
        "public_key_digest": material["public_key"],
        **material["artifacts"],
    }
    assert set(result["artifact_bindings"]) == set(expected_artifacts)
    for field, raw in expected_artifacts.items():
        assert result["artifact_bindings"][field] == {
            "byte_count": len(raw),
            "sha256": decision.bytes_digest(raw),
        }
    assert result["artifact_bindings_digest"] == decision.bytes_digest(
        decision.canonical_json_bytes(result["artifact_bindings"])
    )
    assert result["release_boundaries"]["release_2"] == ("CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT")
    assert result["release_boundaries"]["runtime"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
    assert result["release_boundaries"]["release_3"] == "DISCOVERY_PLANNING_ONLY"
    assert "selection_effective" not in result
    assert "evidence_collection_authorized" not in result
    assert "authority_effective" not in result


@pytest.mark.parametrize(
    "choice",
    ("SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION", "REJECT_CANDIDATE", "HOLD"),
)
def test_source_choices_are_declarations_with_no_effect(exact_candidate: dict[str, Any], choice: str) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, choice)
    bound = _bind(
        exact_candidate,
        material,
        authority_id=authority_id,
        decision_id=decision_id,
    )
    assert bound.declared_choice == choice
    assert bound.as_dict()["decision_effect"] == "NONE"
    for unsafe_attribute in (
        "selected",
        "approved",
        "valid",
        "authority_effective",
        "adequate",
        "profile_approved",
        "runtime_complete",
    ):
        assert not hasattr(bound, unsafe_attribute)
    assert not hasattr(bound, "__dict__")
    with pytest.raises(FrozenInstanceError):
        bound.declared_choice = "SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION"  # type: ignore[misc]


def test_returned_nested_state_cannot_be_laundered(
    exact_candidate: dict[str, Any],
) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    bound = _bind(
        exact_candidate,
        material,
        authority_id="R2-AUTH-001",
        decision_id="R2-AUTH-001-PRECONDITION-D1",
    )
    exposed = bound.as_dict()
    exposed["release_boundaries"]["runtime"] = "COMPLETE_EXACT_RUNTIME_CLOSURE"
    exposed["release_boundaries"]["qcp_001"]["qualification_state"] = "QUALIFIED"
    exposed["artifact_bindings"]["authority_basis_digest"]["sha256"] = ZERO_DIGEST
    fresh = bound.as_dict()
    assert fresh["release_boundaries"]["runtime"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
    assert fresh["release_boundaries"]["qcp_001"] == {
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
    }
    assert fresh["artifact_bindings"]["authority_basis_digest"]["sha256"] != ZERO_DIGEST


def test_bound_type_rejects_an_unrelated_mint_token(exact_candidate: dict[str, Any]) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    bound = _bind(
        exact_candidate,
        material,
        authority_id="R2-AUTH-001",
        decision_id="R2-AUTH-001-PRECONDITION-D1",
    )
    constructor_values = {field.name: getattr(bound, field.name) for field in fields(bound)}
    with pytest.raises(
        TypeError,
        match="requires the module construction token",
    ):
        decision.BoundUnverifiedR2AuthorityDecisionReceipt(
            **constructor_values,
            _mint_authority=object(),
        )


def test_signing_payload_has_closed_wrapper_and_two_null_slots(
    exact_candidate: dict[str, Any],
) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    signing_contract = material["packet"]["structural_signing_contract"]
    assert (
        _contract(
            material["packet"],
            "R2-AUTH-001-PRECONDITION-D1",
        )["structural_signing_contract_ref"]
        == decision.SIGNING_CONTRACT_REFERENCE
    )
    assert signing_contract == decision.structural_signing_contract()
    assert signing_contract["signing_domain_hex"] == decision.SIGNING_DOMAIN.hex()
    assert signing_contract["signing_payload_schema"] == decision.SIGNING_PAYLOAD_SCHEMA
    assert signing_contract["detached_signature_field_semantics"] == ("SHA256_OF_EXACT_RAW_DETACHED_SIGNATURE_ARTIFACT")
    assert signing_contract["payload_digest_scope"] == "CANONICAL_SIGNING_PAYLOAD_BYTES_ONLY"
    payload_raw = decision.normalized_decision_payload_bytes(material["receipt"])
    payload = json.loads(payload_raw)
    assert set(payload) == {"receipt", "receipt_schema", "schema"}
    assert payload["schema"] == decision.SIGNING_PAYLOAD_SCHEMA
    assert payload["receipt"]["payload_digest"] is None
    assert payload["receipt"]["detached_signature"] is None
    assert decision.decision_signing_material(payload_raw) == (
        bytes.fromhex(signing_contract["signing_domain_hex"]) + payload_raw
    )
    changed_slots = dict(material["receipt"])
    changed_slots["payload_digest"] = "sha256:" + "1" * 64
    changed_slots["detached_signature"] = "sha256:" + "2" * 64
    assert decision.normalized_decision_payload_bytes(changed_slots) == payload_raw
    changed_reason = dict(material["receipt"])
    changed_reason["reason"] = "different signed reason"
    assert decision.normalized_decision_payload_bytes(changed_reason) != payload_raw


@pytest.mark.parametrize("field", tuple(decision.structural_signing_contract()))
def test_every_machine_signing_contract_field_is_enforced(
    exact_candidate: dict[str, Any],
    field: str,
) -> None:
    material = _material(
        exact_candidate,
        "R2-AUTH-001",
        "R2-AUTH-001-PRECONDITION-D1",
        "HOLD",
    )
    hostile = json.loads(json.dumps(material["packet"]))
    value = hostile["structural_signing_contract"][field]
    hostile["structural_signing_contract"][field] = list(reversed(value)) if type(value) is list else f"{value}-TAMPER"
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="structural_signing_contract_invalid",
    ):
        decision._require_structural_signing_contract(
            hostile,
            _contract(hostile, "R2-AUTH-001-PRECONDITION-D1"),
        )


def test_stage_b_machine_signing_contract_reference_is_enforced(
    exact_candidate: dict[str, Any],
) -> None:
    material = _material(exact_candidate, "R2-AUTH-002", "R2-AUTH-002-D2", "ABSTAIN")
    contract = dict(_contract(material["packet"], "R2-AUTH-002-D2"))
    contract["structural_signing_contract_ref"] = "SUBSTITUTE"
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="decision_contract_signing_reference_invalid",
    ):
        decision._require_structural_signing_contract(material["packet"], contract)


@pytest.mark.parametrize("attack", ("whitespace", "bom", "duplicate", "float", "non_nfc"))
def test_noncanonical_receipt_bytes_are_refused(exact_candidate: dict[str, Any], attack: str) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    raw = material["receipt_raw"]
    if attack == "whitespace":
        hostile = raw + b"\n"
    elif attack == "bom":
        hostile = b"\xef\xbb\xbf" + raw
    elif attack == "duplicate":
        hostile = b'{"schema":"duplicate",' + raw[1:]
    elif attack == "float":
        hostile = raw.replace(b'"choice":"HOLD"', b'"choice":1.0')
    else:
        value = dict(material["receipt"])
        value["reason"] = "e\u0301"
        hostile = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "ascii"
        )
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="decision_receipt_not_canonical",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
            receipt_raw=hostile,
        )


@pytest.mark.parametrize("attack", ("missing", "extra"))
def test_receipt_field_census_is_closed(exact_candidate: dict[str, Any], attack: str) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    value = dict(material["receipt"])
    if attack == "missing":
        del value["reason"]
    else:
        value["unexpected"] = "field"
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="decision_receipt_field_set_invalid",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
            receipt_raw=decision.canonical_json_bytes(value),
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("candidate_commit", "0" * 40, "decision_receipt_candidate_binding_mismatch"),
        ("candidate_tree", "0" * 40, "decision_receipt_candidate_binding_mismatch"),
        ("repository_namespace", "attacker/substitute", "decision_receipt_repository_binding_mismatch"),
        ("authority_id", "R2-AUTH-004", "decision_receipt_id_binding_mismatch"),
        ("decision_id", "R2-AUTH-001-OTHER", "decision_receipt_id_binding_mismatch"),
        ("package_manifest_sha256", "sha256:" + "1" * 64, "decision_receipt_candidate_binding_mismatch"),
        ("source_freeze_sha256", "sha256:" + "2" * 64, "decision_receipt_candidate_binding_mismatch"),
        ("choice", "APPROVE", "decision_choice_not_allowed"),
    ),
)
def test_subject_and_choice_substitution_is_refused_even_when_payload_is_rechained(
    exact_candidate: dict[str, Any], field: str, value: str, error: str
) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    with pytest.raises(decision.AuthorityDecisionReceiptError, match=error):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
            receipt_raw=_rechain(material, **{field: value}),
        )


@pytest.mark.parametrize(
    ("argument", "error"),
    (
        ("expected_package_manifest_sha256", "candidate_package_manifest_pin_mismatch"),
        ("expected_source_freeze_sha256", "candidate_source_freeze_pin_mismatch"),
    ),
)
def test_external_package_pins_are_mandatory(exact_candidate: dict[str, Any], argument: str, error: str) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    with pytest.raises(decision.AuthorityDecisionReceiptError, match=error):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
            **{argument: "sha256:" + "f" * 64},
        )


def test_post_verification_packet_read_must_rejoin_the_pinned_manifest(
    exact_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    substituted_packet = dict(material["packet"])
    substituted_packet["release_boundaries"] = dict(substituted_packet["release_boundaries"])
    substituted_packet["release_boundaries"]["runtime"] = "COMPLETE_EXACT_RUNTIME_CLOSURE"
    substituted_raw = decision.canonical_json_bytes(substituted_packet)
    owner_read = decision._read_external_regular

    def substitute_after_verification(
        path: Path,
        *,
        maximum_bytes: int,
        error: str,
    ) -> bytes:
        if Path(path).name == "R2-AUTH-001.json":
            return substituted_raw
        return owner_read(path, maximum_bytes=maximum_bytes, error=error)

    monkeypatch.setattr(decision, "_read_external_regular", substitute_after_verification)
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="candidate_package_manifest_member_binding_mismatch",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
        )


def test_post_verification_source_freeze_substitution_must_fail_the_external_pin(
    exact_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    source_freeze = _object(exact_candidate["package"] / "source-freeze.json")
    source_freeze["substituted_after_verification"] = True
    substituted_raw = decision.canonical_json_bytes(source_freeze)
    owner_read = decision._read_external_regular

    def substitute_after_verification(
        path: Path,
        *,
        maximum_bytes: int,
        error: str,
    ) -> bytes:
        if Path(path).name == "source-freeze.json":
            return substituted_raw
        return owner_read(path, maximum_bytes=maximum_bytes, error=error)

    monkeypatch.setattr(decision, "_read_external_regular", substitute_after_verification)
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="candidate_source_freeze_pin_mismatch",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
        )


@pytest.mark.parametrize("attack", ("missing", "extra", "bytes"))
def test_every_external_digest_requires_exact_artifact_bytes(exact_candidate: dict[str, Any], attack: str) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    artifacts = dict(material["artifacts"])
    field = sorted(artifacts)[0]
    if attack == "missing":
        del artifacts[field]
        error = "decision_artifact_field_set_invalid"
    elif attack == "extra":
        artifacts["unexpected_digest"] = b"extra"
        error = "decision_artifact_field_set_invalid"
    else:
        artifacts[field] += b"tamper"
        error = "decision_artifact_digest_mismatch"
    with pytest.raises(decision.AuthorityDecisionReceiptError, match=error):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
            artifact_raw_by_field=artifacts,
        )


@pytest.mark.parametrize(
    ("argument", "error"),
    (
        ("signature_artifact_raw", "decision_signature_artifact_binding_mismatch"),
        ("public_key_artifact_raw", "decision_public_key_artifact_binding_mismatch"),
    ),
)
def test_signature_and_public_key_artifact_substitution_is_refused(
    exact_candidate: dict[str, Any], argument: str, error: str
) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    with pytest.raises(decision.AuthorityDecisionReceiptError, match=error):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
            **{argument: b"substitute artifact"},
        )


def test_payload_digest_mutation_is_refused(exact_candidate: dict[str, Any]) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    value = dict(material["receipt"])
    value["payload_digest"] = "sha256:" + "a" * 64
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="decision_receipt_payload_digest_mismatch",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
            receipt_raw=decision.canonical_json_bytes(value),
        )


def test_cross_lane_replay_is_refused(exact_candidate: dict[str, Any]) -> None:
    material = _material(exact_candidate, "R2-AUTH-002", "R2-AUTH-002-D1", "HOLD")
    with pytest.raises(decision.AuthorityDecisionReceiptError):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
        )


def test_r2_auth_004_receipt_must_bind_the_exact_packet_profile(
    exact_candidate: dict[str, Any],
) -> None:
    authority_id = "R2-AUTH-004"
    decision_id = "R2-AUTH-004-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD_R2_AUTH_004")
    substitute = decision.canonical_json_bytes({"profile_id": "P1", "status": "PROPOSED_UNAPPROVED", "controls": []})
    artifacts = dict(material["artifacts"])
    artifacts["control_profile_digest"] = substitute
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="r2_auth_004_control_profile_binding_mismatch",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id=authority_id,
            decision_id=decision_id,
            artifact_raw_by_field=artifacts,
            receipt_raw=_rechain(
                material,
                control_profile_digest=decision.bytes_digest(substitute),
            ),
        )


def test_stage_b_hash_binding_is_explicitly_not_adequacy(
    exact_candidate: dict[str, Any],
) -> None:
    material = _material(exact_candidate, "R2-AUTH-002", "R2-AUTH-002-D2", "ADEQUATE")
    bound = _bind(
        exact_candidate,
        material,
        authority_id="R2-AUTH-002",
        decision_id="R2-AUTH-002-D2",
    )
    result = bound.as_dict()
    assert result["declared_choice"] == "ADEQUATE"
    assert result["decision_effect"] == "NONE"
    assert "adequacy_effective" not in result


def test_expiry_range_is_structurally_fail_closed(exact_candidate: dict[str, Any]) -> None:
    material = _material(exact_candidate, "R2-AUTH-002", "R2-AUTH-002-D1", "HOLD")
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="decision_receipt_time_range_invalid",
    ):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-002",
            decision_id="R2-AUTH-002-D1",
            receipt_raw=_rechain(material, receipt_valid_until="2026-08-29T00:00:00Z"),
        )


@pytest.mark.parametrize(
    ("constant", "error"),
    (
        ("_MAX_RECEIPT_BYTES", "decision_receipt_bytes_invalid"),
        ("_MAX_SIGNATURE_ARTIFACT_BYTES", "decision_signature_artifact_invalid"),
        ("_MAX_PUBLIC_KEY_ARTIFACT_BYTES", "decision_public_key_artifact_invalid"),
        ("_MAX_EXTERNAL_ARTIFACT_BYTES", "decision_artifact_bytes_invalid"),
        ("_MAX_TOTAL_EXTERNAL_ARTIFACT_BYTES", "decision_artifact_set_too_large"),
    ),
)
def test_exported_api_enforces_every_input_ceiling(
    exact_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    error: str,
) -> None:
    material = _material(exact_candidate, "R2-AUTH-001", "R2-AUTH-001-PRECONDITION-D1", "HOLD")
    monkeypatch.setattr(decision, constant, 1)
    with pytest.raises(decision.AuthorityDecisionReceiptError, match=error):
        _bind(
            exact_candidate,
            material,
            authority_id="R2-AUTH-001",
            decision_id="R2-AUTH-001-PRECONDITION-D1",
        )


def test_cli_success_round_trip_emits_the_exact_canonical_binding(
    exact_candidate: dict[str, Any],
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    authority_id = "R2-AUTH-001"
    decision_id = "R2-AUTH-001-PRECONDITION-D1"
    material = _material(exact_candidate, authority_id, decision_id, "HOLD")
    receipt_path = tmp_path / "receipt.json"
    signature_path = tmp_path / "signature.bin"
    public_key_path = tmp_path / "public-key.bin"
    receipt_path.write_bytes(material["receipt_raw"])
    signature_path.write_bytes(material["signature"])
    public_key_path.write_bytes(material["public_key"])
    arguments = [
        "--repository",
        str(exact_candidate["repository"]),
        "--package",
        str(exact_candidate["package"]),
        "--expected-commit",
        exact_candidate["commit"],
        "--expected-tree",
        exact_candidate["tree"],
        "--repository-namespace",
        REPOSITORY_NAMESPACE,
        "--package-manifest-sha256",
        exact_candidate["manifest_digest"],
        "--source-freeze-sha256",
        exact_candidate["source_freeze_digest"],
        "--authority-id",
        authority_id,
        "--decision-id",
        decision_id,
        "--receipt",
        str(receipt_path),
        "--signature-artifact",
        str(signature_path),
        "--public-key-artifact",
        str(public_key_path),
    ]
    for field, raw in sorted(material["artifacts"].items()):
        path = tmp_path / f"{field}.bin"
        path.write_bytes(raw)
        arguments.extend(("--artifact", f"{field}={path}"))

    assert decision.main(arguments) == 0
    captured = capfd.readouterr()
    expected = _bind(
        exact_candidate,
        material,
        authority_id=authority_id,
        decision_id=decision_id,
    ).as_dict()
    assert captured.err == ""
    assert captured.out.encode("ascii") == decision.canonical_json_bytes(expected) + b"\n"


def test_cli_argument_refusal_is_fixed_and_does_not_echo_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SENSITIVE-UNTRUSTED-CLI-VALUE"
    assert decision.main(["--authority-id", secret]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "REFUSED:command_arguments_invalid\n"
    assert secret not in captured.err


def test_external_reads_reject_hardlinks_and_oversize(tmp_path: Path) -> None:
    original = tmp_path / "original"
    alias = tmp_path / "alias"
    original.write_bytes(b"exact bytes")
    os.link(original, alias)
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="test_input_unavailable",
    ):
        decision._read_external_regular(
            original,
            maximum_bytes=1024,
            error="test_input_unavailable",
        )
    standalone = tmp_path / "standalone"
    standalone.write_bytes(b"12345")
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="test_input_unavailable",
    ):
        decision._read_external_regular(
            standalone,
            maximum_bytes=4,
            error="test_input_unavailable",
        )


def test_external_reads_reject_symlinks_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.write_bytes(b"exact bytes")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    with pytest.raises(
        decision.AuthorityDecisionReceiptError,
        match="test_input_unavailable",
    ):
        decision._read_external_regular(
            link,
            maximum_bytes=1024,
            error="test_input_unavailable",
        )
