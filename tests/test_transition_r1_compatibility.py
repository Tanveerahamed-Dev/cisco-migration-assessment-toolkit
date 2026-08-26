"""Pinned, non-promoting Release 1 compatibility tests for Atlas R2.0."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

import pytest

from cisco_toolkit import protocol_assurance as pa
from cisco_toolkit import transition_legacy as legacy
from cisco_toolkit.transition_contract import bytes_digest, canonical_digest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

BEFORE_SNAPSHOT_RAW, AFTER_SNAPSHOT_RAW, RETROSPECTIVE_COMPARISON_RAW = (
    legacy.legacy_retrospective_vector_bytes()
)

# Generated once from the approved, byte-pinned Release 1 semantic bundle.  This literal is the
# compatibility oracle; tests must never replace it with a digest computed from the code under test.
EXPECTED_R1_CANONICAL_COMPARISON_DIGEST = (
    "sha256:e92dbe997b92b3c6d1e3017408ac1a32e7364e14f61edd9202a67d9710a87c70"
)

_R1_ADDITIVE_FIELDS = {
    "comparison_schema",
    "comparison_admission",
    "change_intent",
    "protocol_families",
    "precert",
    "cutover_gate",
    "operator_evidence",
    "comparison_receipt",
}


def _comparison() -> dict[str, Any]:
    return json.loads(RETROSPECTIVE_COMPARISON_RAW)


def _comparison_raw(comparison: dict[str, Any] | None = None) -> bytes:
    if comparison is None:
        return RETROSPECTIVE_COMPARISON_RAW
    return pa.canonical_json_bytes(comparison)


def _reseal_envelope(comparison: dict[str, Any]) -> None:
    delta = {
        key: value
        for key, value in comparison.items()
        if key not in _R1_ADDITIVE_FIELDS
    }
    comparison["comparison_receipt"] = pa.receipt_envelope(
        admission=comparison["comparison_admission"],
        change_intent=comparison["change_intent"],
        protocol_families=comparison["protocol_families"],
        delta=delta,
        precert=comparison["precert"],
        cutover_gate=comparison["cutover_gate"],
        operator_evidence=comparison["operator_evidence"],
    )


def _assert_legacy_refusal(callable_value: Any, code: str) -> legacy.LegacyCompatibilityError:
    with pytest.raises(legacy.LegacyCompatibilityError) as caught:
        callable_value()
    assert caught.value.code == code
    return caught.value


@pytest.fixture(scope="module")
def verified_bundle() -> legacy.VerifiedLegacySemanticBundle:
    return legacy.verify_release1_semantic_bundle()


def test_approved_owner_source_bundle_is_exact_and_closed(
        verified_bundle: legacy.VerifiedLegacySemanticBundle) -> None:
    manifest = legacy.legacy_semantic_bundle_manifest()
    assert canonical_digest(manifest) == (
        "sha256:a72fb7bd52e767f446237d21f50d6b36daba84c6f1befaf7f307a88632403489"
    )
    assert manifest["approved_head"] == "08f745ff7e12ff14ec84dee500b016292870aaa5"
    assert tuple(item["path"] for item in manifest["files"]) == (
        "cisco_toolkit/comparison.py",
        "cisco_toolkit/protocol_assurance.py",
        "cisco_toolkit/html.py",
        "cisco_toolkit/precert.py",
        "cisco_toolkit/l2_rehearsal.py",
        "cisco_toolkit/protocol_deltas.py",
        "cisco_toolkit/traffic_assurance.py",
        "webapp/backend/storage.py",
        "webapp/backend/execution.py",
        "webapp/backend/engine.py",
        "webapp/frontend/src/api.ts",
    )
    assert verified_bundle.digest == legacy.LEGACY_R1_SEMANTIC_BUNDLE_DIGEST
    assert verified_bundle.approved_head == legacy.LEGACY_R1_APPROVED_HEAD
    assert verified_bundle.file_count == 11
    assert verified_bundle.historical_source_roster_verified is False
    executable = legacy.legacy_executable_bundle_manifest()
    assert executable["retrospective_conformance_vector"]["historical_receipt"] is False
    assert verified_bundle.executable_bundle_digest == legacy.LEGACY_R1_EXECUTABLE_BUNDLE_DIGEST


def test_retrospective_vector_is_packaged_exactly_and_not_regenerated_by_current_code() -> None:
    assert bytes_digest(BEFORE_SNAPSHOT_RAW) == legacy.LEGACY_R1_RETROSPECTIVE_BEFORE_DIGEST
    assert bytes_digest(AFTER_SNAPSHOT_RAW) == legacy.LEGACY_R1_RETROSPECTIVE_AFTER_DIGEST
    assert bytes_digest(RETROSPECTIVE_COMPARISON_RAW) == (
        legacy.LEGACY_R1_RETROSPECTIVE_COMPARISON_DIGEST
    )
    assert len(RETROSPECTIVE_COMPARISON_RAW) == legacy.LEGACY_R1_RETROSPECTIVE_COMPARISON_BYTES


def test_any_owner_source_byte_mutation_invalidates_the_pinned_bundle(tmp_path: Path) -> None:
    for item in legacy.LEGACY_R1_SOURCE_MANIFEST:
        source = REPOSITORY_ROOT / item["path"]
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    assert legacy.verify_release1_semantic_bundle(tmp_path).digest == (
        legacy.LEGACY_R1_SEMANTIC_BUNDLE_DIGEST
    )
    mutated = tmp_path / legacy.LEGACY_R1_SOURCE_MANIFEST[0]["path"]
    mutated.write_bytes(mutated.read_bytes() + b"\n")

    _assert_legacy_refusal(
        lambda: legacy.verify_release1_semantic_bundle(tmp_path),
        "legacy_semantic_source_digest_mismatch",
    )


def test_literal_r1_comparison_digest_and_optional_inputs_are_pinned() -> None:
    comparison = _comparison()
    raw = _comparison_raw(comparison)

    assert bytes_digest(raw) == EXPECTED_R1_CANONICAL_COMPARISON_DIGEST
    assert comparison["comparison_schema"] == "source_bound_cutover_comparison/1"
    assert comparison["comparison_admission"]["status"] == "admitted"
    assert comparison["change_intent"]["status"] == "not_supplied"
    assert comparison["cutover_gate"]["schema"] == "cutover_gate/1"
    assert comparison["cutover_gate"]["verdict"] == "INDETERMINATE"


def test_release1_replay_is_deterministic_and_never_rewrites_history(
        verified_bundle: legacy.VerifiedLegacySemanticBundle) -> None:
    comparison_raw = _comparison_raw()
    first = legacy.replay_release1_comparison_bytes(
        comparison_raw,
        BEFORE_SNAPSHOT_RAW,
        AFTER_SNAPSHOT_RAW,
        verified_bundle,
        change_intent=None,
        path_intents=None,
        l2_failure_trial=None,
    )
    second = legacy.replay_release1_comparison_bytes(
        comparison_raw,
        BEFORE_SNAPSHOT_RAW,
        AFTER_SNAPSHOT_RAW,
        verified_bundle,
        change_intent=None,
        path_intents=None,
        l2_failure_trial=None,
    )

    assert first == second
    assert first["replay_state"] == "CANONICAL_SEMANTIC_PAYLOAD_IDENTICAL"
    assert first["historical_semantics_rewritten"] is False
    assert first["migration_policy"] == "REFERENCE_NOT_REWRITE"
    assert first["legacy_cutover_verdict"] == "INDETERMINATE"
    assert first["r2_authoritative_gate"] is None
    assert first["r2_promotion_eligible"] is False
    assert first["before_source_digest"] == bytes_digest(BEFORE_SNAPSHOT_RAW)
    assert first["after_source_digest"] == bytes_digest(AFTER_SNAPSHOT_RAW)


@pytest.mark.parametrize("side", ("before", "after"))
def test_semantically_equivalent_snapshot_source_byte_mutation_fails_exact_binding(
        verified_bundle: legacy.VerifiedLegacySemanticBundle, side: str) -> None:
    before_raw = BEFORE_SNAPSHOT_RAW + (b" " if side == "before" else b"")
    after_raw = AFTER_SNAPSHOT_RAW + (b" " if side == "after" else b"")

    _assert_legacy_refusal(
        lambda: legacy.replay_release1_comparison_bytes(
            _comparison_raw(),
            before_raw,
            after_raw,
            verified_bundle,
            change_intent=None,
            path_intents=None,
            l2_failure_trial=None,
        ),
        "legacy_snapshot_source_binding_mismatch",
    )


def test_explicit_change_intent_must_match_the_original_optional_input(
        verified_bundle: legacy.VerifiedLegacySemanticBundle) -> None:
    _assert_legacy_refusal(
        lambda: legacy.replay_release1_comparison_bytes(
            _comparison_raw(),
            BEFORE_SNAPSHOT_RAW,
            AFTER_SNAPSHOT_RAW,
            verified_bundle,
            change_intent={"expected_changes": [], "note": "not the original absent intent"},
            path_intents=None,
            l2_failure_trial=None,
        ),
        "legacy_replay_semantic_payload_mismatch",
    )


@pytest.mark.parametrize("mutation", ("envelope", "owner", "gate"))
def test_envelope_owner_and_gate_mutations_fail_closed(mutation: str) -> None:
    comparison = _comparison()
    if mutation == "envelope":
        comparison["comparison_receipt"]["receipt_sha256"] = _digest_for_test("forged envelope")
        expected = "legacy_comparison_envelope_invalid"
    elif mutation == "owner":
        comparison["comparison_admission"]["owner_versions"]["cutover_gate"] = "cutover_gate/999"
        expected = "legacy_comparison_admission_invalid"
    else:
        comparison["cutover_gate"]["verdict"] = "FAIL"
        expected = "legacy_comparison_envelope_invalid"

    _assert_legacy_refusal(
        lambda: legacy.adapt_release1_comparison_bytes(_comparison_raw(comparison)),
        expected,
    )


def _digest_for_test(label: str) -> str:
    return bytes_digest(label.encode("utf-8"))


def test_reenveloped_unknown_gate_still_cannot_add_a_seventh_r1_status() -> None:
    comparison = _comparison()
    comparison["cutover_gate"]["verdict"] = "ELIGIBLE_FOR_HUMAN_DECISION"
    _reseal_envelope(comparison)

    _assert_legacy_refusal(
        lambda: legacy.adapt_release1_comparison_bytes(_comparison_raw(comparison)),
        "legacy_cutover_gate_invalid",
    )


@pytest.mark.parametrize("legacy_verdict", ("PASS", "FAIL"))
def test_r1_pass_or_fail_is_preserved_but_never_translated_to_an_r2_gate(
        legacy_verdict: str) -> None:
    comparison = _comparison()
    comparison["cutover_gate"]["verdict"] = legacy_verdict
    _reseal_envelope(comparison)

    adapter = legacy.adapt_release1_comparison_bytes(_comparison_raw(comparison))
    assert adapter["legacy_cutover_verdict"] == legacy_verdict
    assert adapter["adapter_authority"] == "AUDIT_ONLY"
    assert adapter["migration_policy"] == "REFERENCE_NOT_REWRITE"
    assert adapter["r2_authoritative_gate"] is None
    assert adapter["r2_promotion_eligible"] is False


@pytest.mark.parametrize(
    ("raw", "code"),
    (
        (b'{"comparison_schema":"first","comparison_schema":"second"}',
         "legacy_receipt_duplicate_json_key"),
        (b'{"value":NaN}', "legacy_receipt_nonfinite_number"),
        (b'{"value":Infinity}', "legacy_receipt_nonfinite_number"),
        (b'{"value":-Infinity}', "legacy_receipt_nonfinite_number"),
    ),
)
def test_duplicate_and_nonfinite_legacy_json_is_rejected(raw: bytes, code: str) -> None:
    refusal = _assert_legacy_refusal(
        lambda: legacy.adapt_release1_comparison_bytes(raw),
        code,
    )
    assert raw.decode("ascii") not in str(refusal)


def test_adapter_remains_audit_only_even_after_exact_bundle_verification(
        verified_bundle: legacy.VerifiedLegacySemanticBundle) -> None:
    adapter = legacy.adapt_release1_comparison_bytes(_comparison_raw(), verified_bundle)

    assert adapter["executable_bundle_bytes_verified"] is True
    assert adapter["semantic_bundle_bytes_verified"] is False
    assert adapter["historical_source_roster_verified"] is False
    assert adapter["semantic_anchor_authority_state"] == "ACCOUNTABLE_OWNER_APPROVAL_REQUIRED"
    assert adapter["adapter_authority"] == "AUDIT_ONLY"
    assert adapter["migration_policy"] == "REFERENCE_NOT_REWRITE"
    assert adapter["r2_authoritative_gate"] is None
    assert adapter["r2_promotion_eligible"] is False
    assert adapter["reason_codes"] == [
        "LEGACY_R1_VOCABULARY_PRESERVED",
        "LEGACY_SEMANTIC_ANCHOR_OWNER_APPROVAL_REQUIRED",
        "LEGACY_RECEIPT_CANNOT_PROMOTE_R2",
    ]


def test_optional_historical_source_roster_audit_is_disclosed_separately() -> None:
    roster_verified = legacy.verify_release1_semantic_bundle(REPOSITORY_ROOT)
    adapter = legacy.adapt_release1_comparison_bytes(_comparison_raw(), roster_verified)

    assert roster_verified.historical_source_roster_verified is True
    assert adapter["executable_bundle_bytes_verified"] is True
    assert adapter["semantic_bundle_bytes_verified"] is True
    assert adapter["historical_source_roster_verified"] is True
    assert adapter["adapter_authority"] == "AUDIT_ONLY"
    assert adapter["r2_authoritative_gate"] is None


def test_detached_or_fake_semantic_bundle_cannot_acquire_replay_authority() -> None:
    fake = SimpleNamespace(
        digest=legacy.LEGACY_R1_SEMANTIC_BUNDLE_DIGEST,
        approved_head=legacy.LEGACY_R1_APPROVED_HEAD,
        file_count=len(legacy.LEGACY_R1_SOURCE_MANIFEST),
    )
    adapter = legacy.adapt_release1_comparison_bytes(_comparison_raw(), fake)
    assert adapter["semantic_bundle_bytes_verified"] is False
    assert adapter["adapter_authority"] == "AUDIT_ONLY"

    _assert_legacy_refusal(
        lambda: legacy.replay_release1_comparison_bytes(
            _comparison_raw(),
            BEFORE_SNAPSHOT_RAW,
            AFTER_SNAPSHOT_RAW,
            fake,
            change_intent=None,
            path_intents=None,
            l2_failure_trial=None,
        ),
        "legacy_semantic_bundle_not_verified",
    )
    with pytest.raises(TypeError):
        legacy.VerifiedLegacySemanticBundle(
            digest=legacy.LEGACY_R1_SEMANTIC_BUNDLE_DIGEST,
            file_count=len(legacy.LEGACY_R1_SOURCE_MANIFEST),
            _authority=object(),
        )
