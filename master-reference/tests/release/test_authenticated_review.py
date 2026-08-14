from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import traceback
from pathlib import Path

import pytest


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from cli import atlas_release  # noqa: E402
import release.authenticated_review as authenticated_review_module  # noqa: E402
from release.authenticated_review import (  # noqa: E402
    AuthenticatedReviewError,
    AuthenticatedReviewResult,
    CLAIM_SCHEMA_VERSION,
    POLICY_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    SIGNATURE_SCHEMA_VERSION,
    ReviewEvidenceBytes,
    consequential_claim_review_signing_material,
    read_review_evidence_files,
    verify_consequential_claim_review,
)
from release.compiler_bundle import CompilerBundle  # noqa: E402
from release.model import canonical_json, sha256_bytes  # noqa: E402


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _candidate(label: str) -> dict[str, object]:
    return {
        "claim_kind": "governance_disposition",
        "classification": "consequential_claim_candidate",
        "entity_type": "consequential_claim_facet",
        "evidence_state": "payload_omitted_value_fingerprint_index_only",
        "facet_id": f"urn:atlas:claim-facet:{_digest(f'facet:{label}')}",
        "facet_path": "disposition",
        "grounding_digest": _digest(f"grounding:{label}"),
        "id": f"urn:atlas:claim-facet-record:{_digest(f'id:{label}')[:24]}",
        "record_identity": f"gap.{label}",
        "record_kind": "gap",
        "review_state": "pending_independent_review",
        "rule_id": "delivery.gap",
        "source_blob_oid": _digest(f"blob:{label}")[:40],
        "source_path": "master-reference/content/delivery-governance.json",
        "source_pointer": f"/gaps/{label}/disposition",
        "value_digest": _digest(f"value:{label}"),
    }


def _bundle() -> CompilerBundle:
    candidates = sorted((_candidate("alpha"), _candidate("beta")), key=lambda item: item["facet_id"])
    candidates[0]["id"] = "urn:atlas:claim-facet-record:ffffffffffffffffffffffff"
    candidates[1]["id"] = "urn:atlas:claim-facet-record:000000000000000000000000"
    candidates.sort(key=lambda item: item["id"])
    assert [item["facet_id"] for item in candidates] != sorted(item["facet_id"] for item in candidates)
    summary = {
        "schema_version": "bounded-curated-consequential-claims/2",
        "contract_path": "master-reference/governance/consequential-claim-contract.json",
        "contract_git_blob_oid": "1" * 40,
        "contract_digest": "2" * 64,
        "classification_digest": "3" * 64,
        "source_receipts_digest": "4" * 64,
        "candidate_set_digest": sha256_bytes(canonical_json(candidates)),
    }
    return CompilerBundle(
        root=Path("compiler-fixture"),
        manifest={"source_commit": "5" * 40, "source_tree_digest": "6" * 64},
        records={"consequential_claim_facets": candidates},
        completeness={"consequential_claim_denominator": summary},
        input_files=(),
    )


def _payload(bundle: CompilerBundle, verdicts: tuple[str, ...] = ("pass", "pass")) -> dict[str, object]:
    candidates = sorted(bundle.records["consequential_claim_facets"], key=lambda item: item["facet_id"])
    summary = bundle.completeness["consequential_claim_denominator"]
    records = [
        {
            "facet_id": candidate["facet_id"],
            "subject_digest": sha256_bytes(canonical_json(candidate)),
            "value_digest": candidate["value_digest"],
            "grounding_digest": candidate["grounding_digest"],
            "verdict": verdict,
            "review_evidence_digest": _digest(f"evidence:{candidate['facet_id']}"),
        }
        for candidate, verdict in zip(candidates, verdicts, strict=True)
    ]
    return {
        "schema_version": "consequential-claim-review/1",
        "review_kind": "bounded_curated_consequential_claim_review",
        "purpose": "consequential_claim_review",
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "contract_path": summary["contract_path"],
        "subject_contract_version": summary["schema_version"],
        "contract_git_blob_oid": summary["contract_git_blob_oid"],
        "contract_digest": summary["contract_digest"],
        "classification_digest": summary["classification_digest"],
        "source_receipts_digest": summary["source_receipts_digest"],
        "candidate_set_digest": summary["candidate_set_digest"],
        "candidate_count": len(candidates),
        "records_digest": sha256_bytes(canonical_json(records)),
        "records": records,
    }


def _evidence(payload: dict[str, object]) -> ReviewEvidenceBytes:
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    asymmetric = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = asymmetric.Ed25519PrivateKey.generate()
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = f"sha256:{sha256_bytes(public_raw)}"
    policy = {
        "schema_version": "reviewer-key-policy/1",
        "policy_kind": "external_ed25519_review_key_allowlist",
        "policy_revision": 1,
        "keys": [
            {
                "public_key_fingerprint": fingerprint,
                "reviewer_kind": "independent_agent",
                "independent_from_proposer": True,
                "authorizations": [
                    {
                        "purpose": "consequential_claim_review",
                        "target_schema_version": "consequential-claim-review/1",
                        "reviewer_role": "consequential_claim_verifier",
                    }
                ],
            }
        ],
    }
    payload_raw = canonical_json(payload)
    policy_raw = canonical_json(policy)
    policy_digest = sha256_bytes(policy_raw)
    material = consequential_claim_review_signing_material(
        MASTER_REFERENCE.parent,
        payload_raw,
        policy_raw,
    )
    signature = {
        "schema_version": "authenticated-review-signature/1",
        "signature_kind": "detached_ed25519_exact_bytes",
        "purpose": "consequential_claim_review",
        "algorithm": "Ed25519",
        "target_schema_version": "consequential-claim-review/1",
        "target_sha256": sha256_bytes(payload_raw),
        "trust_policy_sha256": policy_digest,
        "signer_key_fingerprint": fingerprint,
        "signature_base64": base64.b64encode(key.sign(material)).decode("ascii"),
    }
    return ReviewEvidenceBytes(
        payload=payload_raw,
        signature=canonical_json(signature),
        trust_policy=policy_raw,
        trusted_public_key=public_pem,
    )


def _formatted(failure: pytest.ExceptionInfo[BaseException]) -> str:
    return "".join(traceback.format_exception(failure.type, failure.value, failure.tb))


def test_absent_review_is_deterministic_and_nonpromoting() -> None:
    bundle = _bundle()
    result = verify_consequential_claim_review(
        MASTER_REFERENCE.parent,
        bundle,
        ReviewEvidenceBytes(),
    )

    assert result.status == "absent"
    assert result.candidate_count == 2
    assert result.passed_count == 0
    assert result.unresolved_count == 2
    assert result.signature_verified is False
    assert result.bounded_review_complete is False
    assert result.current_gate_promoted is False
    assert result.global_gate_closed is False


def test_external_review_signature_and_exact_subject_join_pass_without_promotion() -> None:
    bundle = _bundle()
    original_records = copy.deepcopy(bundle.records)
    evidence = _evidence(_payload(bundle))

    result = verify_consequential_claim_review(MASTER_REFERENCE.parent, bundle, evidence)

    assert result.status == "verified_complete_not_promoted"
    assert result.signature_verified is True
    assert result.bounded_review_complete is True
    assert result.candidate_count == result.passed_count == 2
    assert result.blocked_count == result.unresolved_count == 0
    assert result.current_gate_promoted is False
    assert result.global_gate_closed is False
    assert bundle.records == original_records


def test_review_contract_versions_are_owned_by_registered_schemas() -> None:
    schema_root = MASTER_REFERENCE / "release" / "schemas"
    signature_schema = json.loads(
        (schema_root / "authenticated-review-signature.schema.json").read_text(encoding="utf-8")
    )
    policy_schema = json.loads((schema_root / "reviewer-key-policy.schema.json").read_text(encoding="utf-8"))
    result_schema = json.loads(
        (schema_root / "authenticated-review-result.schema.json").read_text(encoding="utf-8")
    )
    assert signature_schema["properties"]["schema_version"]["const"] == SIGNATURE_SCHEMA_VERSION
    assert policy_schema["properties"]["schema_version"]["const"] == POLICY_SCHEMA_VERSION
    assert result_schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert (
        signature_schema["properties"]["target_schema_version"]["const"]
        == CLAIM_SCHEMA_VERSION
    )


def test_public_signing_material_is_domain_and_policy_bound() -> None:
    bundle = _bundle()
    evidence = _evidence(_payload(bundle))
    material = consequential_claim_review_signing_material(
        MASTER_REFERENCE.parent,
        evidence.payload,
        evidence.trust_policy,
    )
    assert material.startswith(
        b"ATLAS-AUTHENTICATED-REVIEW\x00v1\x00"
        b"consequential_claim_review\x00consequential-claim-review/1\x00"
    )
    policy = json.loads(evidence.trust_policy.decode("utf-8"))
    policy["policy_revision"] = 2
    changed = consequential_claim_review_signing_material(
        MASTER_REFERENCE.parent,
        evidence.payload,
        canonical_json(policy),
    )
    assert changed != material


def test_schema_valid_signature_bit_flip_reaches_fixed_crypto_failure() -> None:
    bundle = _bundle()
    evidence = _evidence(_payload(bundle))
    envelope = json.loads(evidence.signature.decode("utf-8"))
    signature = bytearray(base64.b64decode(envelope["signature_base64"], validate=True))
    signature[0] ^= 0x01
    envelope["signature_base64"] = base64.b64encode(signature).decode("ascii")
    with pytest.raises(AuthenticatedReviewError) as failure:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            bundle,
            ReviewEvidenceBytes(
                payload=evidence.payload,
                signature=canonical_json(envelope),
                trust_policy=evidence.trust_policy,
                trusted_public_key=evidence.trusted_public_key,
            ),
        )
    assert failure.value.code == "authenticated_review_signature_invalid"


def test_signed_block_is_valid_evidence_but_cannot_complete_or_promote() -> None:
    bundle = _bundle()
    result = verify_consequential_claim_review(
        MASTER_REFERENCE.parent,
        bundle,
        _evidence(_payload(bundle, ("pass", "block"))),
    )

    assert result.status == "verified_blocked_not_promoted"
    assert result.signature_verified is True
    assert result.passed_count == 1
    assert result.blocked_count == 1
    assert result.bounded_review_complete is False
    assert result.current_gate_promoted is False
    assert result.global_gate_closed is False


def test_partial_inputs_and_signed_subject_drift_fail_with_fixed_codes() -> None:
    bundle = _bundle()
    evidence = _evidence(_payload(bundle))
    with pytest.raises(AuthenticatedReviewError) as partial:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            bundle,
            ReviewEvidenceBytes(payload=evidence.payload),
        )
    assert partial.value.code == "authenticated_review_input_incomplete"

    hostile = _payload(bundle)
    hostile["records"][0]["subject_digest"] = "7" * 64
    hostile["records_digest"] = sha256_bytes(canonical_json(hostile["records"]))
    with pytest.raises(AuthenticatedReviewError) as mismatch:
        verify_consequential_claim_review(MASTER_REFERENCE.parent, bundle, _evidence(hostile))
    assert mismatch.value.code == "authenticated_review_subject_set_mismatch"

    reordered = _payload(bundle)
    reordered["records"].reverse()
    reordered["records_digest"] = sha256_bytes(canonical_json(reordered["records"]))
    with pytest.raises(AuthenticatedReviewError) as order_failure:
        verify_consequential_claim_review(MASTER_REFERENCE.parent, bundle, _evidence(reordered))
    assert order_failure.value.code == "authenticated_review_subject_set_mismatch"


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("source_commit", "7" * 40, "authenticated_review_binding_mismatch"),
        ("source_tree_digest", "7" * 64, "authenticated_review_binding_mismatch"),
        ("contract_digest", "7" * 64, "authenticated_review_binding_mismatch"),
        ("classification_digest", "7" * 64, "authenticated_review_binding_mismatch"),
        ("source_receipts_digest", "7" * 64, "authenticated_review_binding_mismatch"),
        ("candidate_set_digest", "7" * 64, "authenticated_review_binding_mismatch"),
        ("records_digest", "7" * 64, "authenticated_review_subject_set_mismatch"),
    ],
)
def test_signed_top_level_binding_mutations_fail_closed(
    field: str,
    replacement: str,
    expected_code: str,
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    payload[field] = replacement
    with pytest.raises(AuthenticatedReviewError) as failure:
        verify_consequential_claim_review(MASTER_REFERENCE.parent, bundle, _evidence(payload))
    assert failure.value.code == expected_code


@pytest.mark.parametrize("field", ["subject_digest", "value_digest", "grounding_digest"])
def test_signed_subject_field_mutations_fail_closed(field: str) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    payload["records"][0][field] = "7" * 64
    payload["records_digest"] = sha256_bytes(canonical_json(payload["records"]))
    with pytest.raises(AuthenticatedReviewError) as failure:
        verify_consequential_claim_review(MASTER_REFERENCE.parent, bundle, _evidence(payload))
    assert failure.value.code == "authenticated_review_subject_set_mismatch"


def test_in_memory_subject_mutation_is_rejected_at_terminal_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _bundle()
    original_verify = authenticated_review_module._verify_detached_signature

    def mutate_after_signature(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        original.records["consequential_claim_facets"][0]["value_digest"] = "a" * 64
        return result

    monkeypatch.setattr(authenticated_review_module, "_verify_detached_signature", mutate_after_signature)

    with pytest.raises(AuthenticatedReviewError) as failure:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            original,
            _evidence(_payload(original)),
        )
    assert failure.value.code == "authenticated_review_source_changed"


def test_partial_evidence_fails_before_bundle_access() -> None:
    class PrivateBundleCanary:
        @property
        def records(self):
            raise RuntimeError("PRIVATE-BUNDLE-CANARY")

    with pytest.raises(AuthenticatedReviewError) as failure:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            PrivateBundleCanary(),  # type: ignore[arg-type]
            ReviewEvidenceBytes(payload=b"{}\n"),
        )
    assert failure.value.code == "authenticated_review_input_incomplete"


def test_hostile_evidence_types_cannot_inject_public_error_text() -> None:
    canary = "PRIVATE-EVIDENCE-CANARY"

    class HostileBytes:
        def __bytes__(self):
            raise AuthenticatedReviewError(canary)

    class HostileEvidence(ReviewEvidenceBytes):
        def cloned(self):
            raise AuthenticatedReviewError(canary)

    cases = (
        ReviewEvidenceBytes(payload=HostileBytes()),  # type: ignore[arg-type]
        HostileEvidence(),
    )
    for evidence in cases:
        with pytest.raises(AuthenticatedReviewError) as failure:
            verify_consequential_claim_review(MASTER_REFERENCE.parent, _bundle(), evidence)
        assert failure.value.code == "authenticated_review_input_invalid"
        assert canary not in _formatted(failure)


def test_malformed_and_untrusted_inputs_never_echo_payload_or_key_material() -> None:
    bundle = _bundle()
    canary = "AUTHENTICATED-REVIEW-CANARY-MUST-NOT-ECHO"
    malformed_payload = canonical_json({**_payload(bundle), canary: canary})
    valid = _evidence(_payload(bundle))
    with pytest.raises(AuthenticatedReviewError) as malformed:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            bundle,
            ReviewEvidenceBytes(
                payload=malformed_payload,
                signature=valid.signature,
                trust_policy=valid.trust_policy,
                trusted_public_key=valid.trusted_public_key,
            ),
        )
    assert malformed.value.code == "authenticated_review_payload_malformed"
    assert canary not in _formatted(malformed)

    policy = json.loads(valid.trust_policy.decode("utf-8"))
    policy["keys"][0]["public_key_fingerprint"] = f"sha256:{'8' * 64}"
    policy_raw = canonical_json(policy)
    signature = json.loads(valid.signature.decode("utf-8"))
    signature["trust_policy_sha256"] = sha256_bytes(policy_raw)
    # The old signature no longer covers the changed policy digest, but trust
    # rejection occurs first and remains categorical.
    with pytest.raises(AuthenticatedReviewError) as untrusted:
        verify_consequential_claim_review(
            MASTER_REFERENCE.parent,
            bundle,
            ReviewEvidenceBytes(
                payload=valid.payload,
                signature=canonical_json(signature),
                trust_policy=policy_raw,
                trusted_public_key=valid.trusted_public_key,
            ),
        )
    assert untrusted.value.code == "authenticated_review_key_not_trusted"
    assert canary not in _formatted(untrusted)


def test_noncanonical_and_duplicate_json_are_rejected_before_signature_work() -> None:
    bundle = _bundle()
    valid = _evidence(_payload(bundle))
    duplicate = valid.payload.replace(
        b'{"candidate_count":2,',
        b'{"candidate_count":2,"candidate_count":2,',
        1,
    )
    assert duplicate != valid.payload
    for payload in (valid.payload.rstrip(b"\n"), duplicate):
        with pytest.raises(AuthenticatedReviewError) as failure:
            verify_consequential_claim_review(
                MASTER_REFERENCE.parent,
                bundle,
                ReviewEvidenceBytes(
                    payload=payload,
                    signature=valid.signature,
                    trust_policy=valid.trust_policy,
                    trusted_public_key=valid.trusted_public_key,
                ),
            )
        assert failure.value.code == "authenticated_review_payload_malformed"


def test_external_file_reader_rejects_growth_oversize_and_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = {
        "payload": tmp_path / "payload.json",
        "signature": tmp_path / "signature.json",
        "policy": tmp_path / "policy.json",
        "key": tmp_path / "reviewer.pub",
    }
    for path in paths.values():
        path.write_bytes(b"bounded\n")
    baseline = read_review_evidence_files(
        paths["payload"],
        paths["signature"],
        paths["policy"],
        paths["key"],
    )
    assert baseline.payload == b"bounded\n"

    paths["signature"].write_bytes(b"x" * 4097)
    with pytest.raises(AuthenticatedReviewError) as oversized:
        read_review_evidence_files(
            paths["payload"],
            paths["signature"],
            paths["policy"],
            paths["key"],
        )
    assert oversized.value.code == "authenticated_review_signature_unavailable"
    paths["signature"].write_bytes(b"bounded\n")

    original_fstat = authenticated_review_module.os.fstat
    mutated = False

    def grow_during_read(descriptor: int):
        nonlocal mutated
        metadata = original_fstat(descriptor)
        if not mutated:
            mutated = True
            with paths["payload"].open("ab") as stream:
                stream.write(b"changed")
        return metadata

    monkeypatch.setattr(authenticated_review_module.os, "fstat", grow_during_read)
    with pytest.raises(AuthenticatedReviewError) as changed:
        read_review_evidence_files(
            paths["payload"],
            paths["signature"],
            paths["policy"],
            paths["key"],
        )
    assert changed.value.code == "authenticated_review_payload_unavailable"
    monkeypatch.setattr(authenticated_review_module.os, "fstat", original_fstat)

    target = tmp_path / "target.json"
    link = tmp_path / "link.json"
    target.write_bytes(b"bounded\n")
    try:
        link.symlink_to(target)
    except OSError:
        return
    with pytest.raises(AuthenticatedReviewError) as symlinked:
        read_review_evidence_files(link, paths["signature"], paths["policy"], paths["key"])
    assert symlinked.value.code == "authenticated_review_payload_unavailable"


def test_cli_dispatches_claim_review_explicitly_and_preserves_fixed_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _bundle()
    evidence = _evidence(_payload(bundle))
    review = AuthenticatedReviewResult(
        schema_version="authenticated-review-result/1",
        status="verified_complete_not_promoted",
        purpose="consequential_claim_review",
        signature_verified=True,
        bounded_review_complete=True,
        current_gate_promoted=False,
        global_gate_closed=False,
        candidate_count=2,
        passed_count=2,
        blocked_count=0,
        unresolved_count=0,
        payload_sha256=sha256_bytes(evidence.payload),
        trust_policy_sha256=sha256_bytes(evidence.trust_policy),
        signer_key_fingerprint="sha256:" + "9" * 64,
        claim_boundary="bounded",
    )
    monkeypatch.setattr(atlas_release, "load_compiler_bundle", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(atlas_release, "validate_exact_source", lambda *_args, **_kwargs: {"stable": True})
    monkeypatch.setattr(atlas_release, "read_review_evidence_files", lambda *_args, **_kwargs: evidence)
    monkeypatch.setattr(atlas_release, "verify_consequential_claim_review", lambda *_args: review)
    monkeypatch.setattr(
        atlas_release,
        "verify_artifact_family",
        lambda *_args: (_ for _ in ()).throw(AssertionError("wrong dispatch")),
    )

    arguments = [
        "verify-claim-review",
        "--repo-root",
        str(MASTER_REFERENCE.parent),
        "--compiler-output",
        str(tmp_path / "compiler"),
        "--payload",
        str(tmp_path / "review.json"),
        "--signature",
        str(tmp_path / "review.sig.json"),
        "--trust-policy",
        str(tmp_path / "policy.json"),
        "--public-key",
        str(tmp_path / "reviewer.pub"),
    ]
    assert atlas_release.main(arguments) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == review.as_dict()
    atlas_release.validate_release_object(
        MASTER_REFERENCE.parent,
        "authenticated-review-result",
        output,
    )
    assert output["status"] == "verified_complete_not_promoted"
    assert output["current_gate_promoted"] is False
    assert output["global_gate_closed"] is False

    changed_evidence = ReviewEvidenceBytes(
        payload=evidence.payload,
        signature=evidence.signature,
        trust_policy=evidence.trust_policy,
        trusted_public_key=evidence.trusted_public_key + b"\n",
    )
    reads = iter((evidence, changed_evidence))
    monkeypatch.setattr(atlas_release, "read_review_evidence_files", lambda *_args, **_kwargs: next(reads))
    assert atlas_release.main(arguments) == 2
    changed_failure = capsys.readouterr().err
    assert json.loads(changed_failure) == {"error": "authenticated_review_input_changed", "ok": False}

    monkeypatch.setattr(atlas_release, "read_review_evidence_files", lambda *_args, **_kwargs: evidence)
    source_snapshots = iter(({"stable": True}, {"stable": False}))
    monkeypatch.setattr(atlas_release, "validate_exact_source", lambda *_args, **_kwargs: next(source_snapshots))
    assert atlas_release.main(arguments) == 2
    source_changed = capsys.readouterr().err
    assert json.loads(source_changed) == {"error": "authenticated_review_source_changed", "ok": False}

    canary = "PRIVATE-SOURCE-PATH-CANARY"
    monkeypatch.setattr(
        atlas_release,
        "load_compiler_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(canary)),
    )
    assert atlas_release.main(arguments) == 2
    failure = capsys.readouterr().err
    assert json.loads(failure) == {"error": "authenticated_review_source_invalid", "ok": False}
    assert canary not in failure
