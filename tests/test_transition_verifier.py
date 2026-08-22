"""Red-team tests for the closed R2.0 verifier algebra and receipt boundary."""

from __future__ import annotations

from copy import deepcopy
from itertools import permutations, product
from typing import Any

import pytest

from cisco_toolkit import transition_contract as tc
from cisco_toolkit import transition_pack as tp
from cisco_toolkit import transition_verifier as tv
from tests.transition_fixtures import (
    EXPERIMENTAL_QCP_001_QUALIFICATION,
    minimal_transition_case,
)


_GATE_SEVERITY = {
    tc.AuthoritativeGate.ELIGIBLE_FOR_HUMAN_DECISION.value: 0,
    tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value: 1,
    tc.AuthoritativeGate.CONFLICT_REQUIRES_RESOLUTION.value: 2,
    tc.AuthoritativeGate.OBSERVED_BREACH.value: 3,
}


def _digest(label: str) -> str:
    return tc.canonical_digest({"fixture": label})


def _qcp_manifest(case: dict[str, Any], *, revision: str = "001") -> dict[str, Any]:
    pack_denominator = next(
        item for item in case["qualification_denominators"]
        if item["subject_kind"] == tp.QualificationSubjectKind.BEHAVIOR_PACK.value
    )
    return {
        "schema": tp.PACK_MANIFEST_SCHEMA,
        "pack_id": tp.QCP_001_ID,
        "pack_version": tp.QCP_001_DRAFT_VERSION,
        "abi_version": tc.PACK_ABI_VERSION,
        "behavior_kind": "BEHAVIOR_PACK",
        "qualification_state": tc.QualificationState.EXPERIMENTAL.value,
        "qualification_receipt_digest": None,
        "execution_state": tp.PackExecutionState.CONTRACT_ONLY.value,
        "substrate": tp.PackSubstrate.DECLARATIVE_DSL_ONLY.value,
        "semantic_bundle_digest": case["pack_binding"]["semantic_bundle_digest"],
        "declarative_rules_digest": _digest(f"qcp declarative rules {revision}"),
        "declarative_operators": list(tp.DECLARATIVE_DSL_OPERATORS),
        "supported_denominator_digest": tc.canonical_digest(pack_denominator),
        "applicability_profile_ids": [
            case["applicability"]["profile_id"] or "QCP-001.EXPERIMENTAL.contract-only"
        ],
        "functions": list(tp.PACK_ABI_FUNCTIONS),
        "wasm_modules": [],
        "tcb_manifest_digest": _digest(f"qcp tcb manifest {revision}"),
        "claim_boundary": tp.QCP_001_CLAIM_BOUNDARY,
    }


def _bind_qcp_fixture(
        *,
        case: dict[str, Any] | None = None,
        revision: str = "001",
        applicability_profile_ids: list[str] | None = None,
) -> tuple[tc.BoundTransitionCase, tp.BoundPackManifest, tuple[bytes, ...]]:
    value = deepcopy(case or minimal_transition_case())
    pack_denominator = next(
        item for item in value["qualification_denominators"]
        if item["subject_kind"] == tp.QualificationSubjectKind.BEHAVIOR_PACK.value
    )
    pack_denominator.update({
        "subject_id": tp.QCP_001_ID,
        "subject_version": tp.QCP_001_DRAFT_VERSION,
    })
    pack_denominator_digest = tc.canonical_digest(pack_denominator)
    for dependency in value["version_contract"]["dependency_digests"]:
        if (
                dependency["kind"] == "QUALIFICATION_DENOMINATOR"
                and dependency["identifier"] == pack_denominator["denominator_id"]
        ):
            dependency["digest"] = pack_denominator_digest
    manifest = _qcp_manifest(value, revision=revision)
    if applicability_profile_ids is not None:
        manifest["applicability_profile_ids"] = applicability_profile_ids
    manifest_raw = tc.canonical_json_bytes(manifest)
    bound_pack = tp.bind_pack_manifest_bytes(manifest_raw)

    value["pack_binding"]["pack_version"] = bound_pack["pack_version"]
    value["pack_binding"]["pack_manifest_digest"] = bound_pack.digest
    value["pack_binding"]["tcb_manifest_digest"] = bound_pack["tcb_manifest_digest"]
    value["pack_binding"]["pack_qualification_receipt_digest"] = (
        bound_pack["qualification_receipt_digest"]
    )
    for binding in value["replay_contract"]["object_bindings"]:
        if binding["role"] == "PACK_MANIFEST":
            binding["digest"] = bound_pack.digest
        elif binding["role"] == "TCB_MANIFEST":
            binding["digest"] = bound_pack["tcb_manifest_digest"]
    value["replay_contract"]["object_bindings"].sort(
        key=lambda item: (item["role"], item["digest"])
    )
    for dependency in value["version_contract"]["dependency_digests"]:
        if dependency["kind"] == "PACK":
            dependency["identifier"] = bound_pack["pack_id"]
            dependency["digest"] = bound_pack.digest
        elif dependency["kind"] == "TCB":
            dependency["identifier"] = bound_pack["pack_id"]
            dependency["digest"] = bound_pack["tcb_manifest_digest"]
    value["version_contract"]["dependency_digests"].sort(
        key=lambda item: (item["kind"], item["identifier"])
    )

    bound_case = tc.bind_transition_case_bytes(tc.canonical_json_bytes(value))
    content_objects = (
        tc.canonical_json_bytes({"fixture": "sampled-observation-bytes"}),
        tc.canonical_json_bytes({"fixture": "before-snapshot"}),
        tc.canonical_json_bytes({"fixture": "after-snapshot"}),
        tc.canonical_json_bytes({"fixture": "fhrp-single-owner-evidence-recipe"}),
        tc.canonical_json_bytes({"fixture": "gateway-handoff-compensation-plan"}),
        tc.canonical_json_bytes({"fixture": "decision-time-trust-policy-snapshot"}),
        tc.canonical_json_bytes({"fixture": "independently-obtained-verifier-bootstrap"}),
        tc.canonical_json_bytes({"fixture": "external-experimental-trust-policy"}),
        tc.canonical_json_bytes({"fixture": "qcp-001-experimental-replay-recipe"}),
        manifest_raw,
        tc.canonical_json_bytes({"fixture": f"qcp tcb manifest {revision}"}),
        tc.canonical_json_bytes({"fixture": "qcp-001-experimental-semantic-bundle"}),
        tc.canonical_json_bytes(EXPERIMENTAL_QCP_001_QUALIFICATION),
    )
    return bound_case, bound_pack, content_objects


@pytest.mark.parametrize(
    ("valid_support", "valid_counter", "expected"),
    (
        (False, False, tc.EvidenceStatus.UNKNOWN.value),
        (True, False, tc.EvidenceStatus.SUPPORTED.value),
        (False, True, tc.EvidenceStatus.REFUTED.value),
        (True, True, tc.EvidenceStatus.CONFLICTING.value),
    ),
)
def test_four_valued_evidence_algebra_is_exhaustive(
        valid_support: bool,
        valid_counter: bool,
        expected: str,
) -> None:
    assert tv.four_valued_evidence_status(valid_support, valid_counter) == expected


@pytest.mark.parametrize("invalid", (0, 1, None, "true", [], object()))
def test_four_valued_evidence_axes_require_exact_booleans(invalid: object) -> None:
    with pytest.raises(TypeError, match="evidence axes must be booleans"):
        tv.four_valued_evidence_status(invalid, False)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="evidence axes must be booleans"):
        tv.four_valued_evidence_status(False, invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", (0, 1, None, "false", [], object()))
def test_gate_completeness_axes_require_exact_booleans(invalid: object) -> None:
    with pytest.raises(TypeError, match="gate completeness axes must be booleans"):
        tv.map_authoritative_gate(
            applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
            qualification_state=tc.QualificationState.QUALIFIED.value,
            mandatory_evidence_statuses=[tc.EvidenceStatus.SUPPORTED.value],
            evaluator_complete=invalid,  # type: ignore[arg-type]
            certificates_complete=True,
        )
    with pytest.raises(TypeError, match="gate completeness axes must be booleans"):
        tv.map_authoritative_gate(
            applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
            qualification_state=tc.QualificationState.QUALIFIED.value,
            mandatory_evidence_statuses=[tc.EvidenceStatus.SUPPORTED.value],
            evaluator_complete=True,
            certificates_complete=invalid,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("evaluator_complete", "certificates_complete"),
    ((False, True), (True, False), (False, False)),
)
def test_either_incomplete_evaluator_axis_forces_evidence_incomplete(
        evaluator_complete: bool,
        certificates_complete: bool) -> None:
    assert tv.map_authoritative_gate(
        applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
        qualification_state=tc.QualificationState.QUALIFIED.value,
        mandatory_evidence_statuses=[tc.EvidenceStatus.SUPPORTED.value],
        evaluator_complete=evaluator_complete,
        certificates_complete=certificates_complete,
    ) == (
        tv.GateDisposition.AUTHORITATIVE_GATE.value,
        tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value,
    )


def _expected_qualified_gate(statuses: tuple[str, ...]) -> str:
    if tc.EvidenceStatus.REFUTED.value in statuses:
        return tc.AuthoritativeGate.OBSERVED_BREACH.value
    if tc.EvidenceStatus.CONFLICTING.value in statuses:
        return tc.AuthoritativeGate.CONFLICT_REQUIRES_RESOLUTION.value
    if not statuses or tc.EvidenceStatus.UNKNOWN.value in statuses:
        return tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    return tc.AuthoritativeGate.ELIGIBLE_FOR_HUMAN_DECISION.value


def test_gate_precedence_is_exhaustive_and_permutation_independent() -> None:
    statuses = tuple(item.value for item in tc.EvidenceStatus)
    for length in range(4):
        for sequence in product(statuses, repeat=length):
            expected = _expected_qualified_gate(sequence)
            observed = {
                tv.map_authoritative_gate(
                    applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
                    qualification_state=tc.QualificationState.QUALIFIED.value,
                    mandatory_evidence_statuses=ordering,
                    evaluator_complete=True,
                    certificates_complete=True,
                )
                for ordering in set(permutations(sequence))
            }
            assert observed == {(tv.GateDisposition.AUTHORITATIVE_GATE.value, expected)}


def test_adding_mandatory_evidence_cannot_improve_a_nonempty_gate() -> None:
    statuses = tuple(item.value for item in tc.EvidenceStatus)
    for length in range(1, 4):
        for sequence in product(statuses, repeat=length):
            _, before = tv.map_authoritative_gate(
                applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
                qualification_state=tc.QualificationState.QUALIFIED.value,
                mandatory_evidence_statuses=sequence,
                evaluator_complete=True,
                certificates_complete=True,
            )
            assert before is not None
            for added in statuses:
                _, after = tv.map_authoritative_gate(
                    applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
                    qualification_state=tc.QualificationState.QUALIFIED.value,
                    mandatory_evidence_statuses=(*sequence, added),
                    evaluator_complete=True,
                    certificates_complete=True,
                )
                assert after is not None
                assert _GATE_SEVERITY[after] >= _GATE_SEVERITY[before]


@pytest.mark.parametrize(
    ("applicability", "expected_disposition"),
    (
        (tc.ApplicabilityKind.NOT_APPLICABLE.value, tv.GateDisposition.NO_CASE.value),
        (
            tc.ApplicabilityKind.APPLICABILITY_EVIDENCE_REQUIRED.value,
            tv.GateDisposition.NO_AUTHORITATIVE_GATE.value,
        ),
    ),
)
def test_non_applicable_and_unresolved_applicability_have_no_gate(
        applicability: str,
        expected_disposition: str,
) -> None:
    assert tv.map_authoritative_gate(
        applicability_kind=applicability,
        qualification_state=tc.QualificationState.QUALIFIED.value,
        mandatory_evidence_statuses=[tc.EvidenceStatus.REFUTED.value],
        evaluator_complete=True,
        certificates_complete=True,
    ) == (expected_disposition, None)


def test_gate_and_evidence_vocabularies_admit_no_fifth_status() -> None:
    assert {item.value for item in tc.EvidenceStatus} == {
        "SUPPORTED",
        "REFUTED",
        "CONFLICTING",
        "UNKNOWN",
    }
    assert {item.value for item in tc.AuthoritativeGate} == set(_GATE_SEVERITY)
    with pytest.raises(tc.TransitionContractError) as caught:
        tv.map_authoritative_gate(
            applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
            qualification_state=tc.QualificationState.QUALIFIED.value,
            mandatory_evidence_statuses=["PASS_WITH_WARNING"],
            evaluator_complete=True,
            certificates_complete=True,
        )
    assert caught.value.code == "UNKNOWN_EVIDENCE_STATUS"

    with pytest.raises(tc.TransitionContractError) as qualification:
        tv.map_authoritative_gate(
            applicability_kind=tc.ApplicabilityKind.APPLICABLE.value,
            qualification_state="PROVISIONALLY_QUALIFIED",
            mandatory_evidence_statuses=[tc.EvidenceStatus.SUPPORTED.value],
            evaluator_complete=True,
            certificates_complete=True,
        )
    assert qualification.value.code == "UNKNOWN_QUALIFICATION_STATE"


def test_exact_content_bytes_cannot_be_replaced_by_a_forged_digest_string() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    artifact_digest = case["evidence_atoms"][0]["artifact_digest"]
    exact_content = tv.bind_content_objects(content_objects)
    forged_content = tv.bind_content_objects((*content_objects[1:], artifact_digest.encode("ascii")))

    assert exact_content.contains(artifact_digest)
    assert not forged_content.contains(artifact_digest)

    exact_receipt = tv.verify_transition_case(case, pack, content=exact_content)
    forged_receipt = tv.verify_transition_case(case, pack, content=forged_content)
    exact_reasons = exact_receipt["obligations"][0]["temporal_outcomes_and_reasons"]
    forged_reasons = forged_receipt["obligations"][0]["temporal_outcomes_and_reasons"]
    assert "EVIDENCE_BYTES_UNAVAILABLE" not in exact_reasons
    assert "EVIDENCE_BYTES_UNAVAILABLE" in forged_reasons
    assert forged_receipt["replay_status"] == tv.ReplayStatus.SEALED_CONTENT_INCOMPLETE.value


def test_verifier_receipt_is_deterministic_across_content_input_order() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    first = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )
    second = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(tuple(reversed(content_objects))),
    )

    assert first == second
    assert tv.verifier_receipt_bytes(first) == tv.verifier_receipt_bytes(second)
    assert tc.bytes_digest(tv.verifier_receipt_bytes(first)) == tc.canonical_digest(dict(first))


def test_verifier_bootstrap_is_an_independent_exact_byte_input() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    content = tv.bind_content_objects(content_objects)
    exact_bootstrap = tc.canonical_json_bytes({
        "fixture": "independently-obtained-verifier-bootstrap"
    })

    missing = tv.verify_transition_case(case, pack, content=content)
    exact = tv.verify_transition_case(
        case,
        pack,
        content=content,
        verifier_bootstrap_raw=exact_bootstrap,
    )
    mismatched = tv.verify_transition_case(
        case,
        pack,
        content=content,
        verifier_bootstrap_raw=b"case-supplied substitute",
    )

    assert "EXTERNAL_VERIFIER_BOOTSTRAP_REQUIRED" in missing["reason_codes"]
    assert "EXTERNAL_VERIFIER_BOOTSTRAP_REQUIRED" not in exact["reason_codes"]
    assert "EXTERNAL_VERIFIER_BOOTSTRAP_MISMATCH" not in exact["reason_codes"]
    assert "EXTERNAL_VERIFIER_BOOTSTRAP_MISMATCH" in mismatched["reason_codes"]
    assert exact["replay_authority_established"] is False


def test_only_unchanged_verifier_minted_receipts_can_be_serialized() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    receipt = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )

    with pytest.raises(tc.TransitionContractError) as detached:
        tv.verifier_receipt_bytes(dict(receipt))  # type: ignore[arg-type]
    assert detached.value.code == "DETACHED_VERIFIER_RECEIPT"

    with pytest.raises(TypeError):
        receipt["authoritative_gate"] = "GO"  # type: ignore[index]

    receipt._value["authoritative_gate"] = "GO"  # noqa: SLF001
    receipt._value["autonomous_go"] = True  # noqa: SLF001
    with pytest.raises(tc.TransitionContractError) as mutated:
        tv.verifier_receipt_bytes(receipt)
    assert mutated.value.code == "BOUND_VERIFIER_RECEIPT_MUTATED"


def test_bound_content_set_detects_post_bind_internal_mutation() -> None:
    content = tv.bind_content_objects([b"exact evidence"])
    forged_digest = tc.bytes_digest(b"different evidence")
    content._objects[forged_digest] = b"not the matching bytes"  # noqa: SLF001

    with pytest.raises(tc.TransitionContractError) as mutated:
        content.contains(forged_digest)
    assert mutated.value.code == "BOUND_CONTENT_SET_MUTATED"


def test_qcp_001_is_experimental_and_cannot_emit_a_promoting_gate() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    receipt = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )

    assert receipt["pack_qualification_state"] == tc.QualificationState.EXPERIMENTAL.value
    assert receipt["authoritative_gate"] == tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    assert "QCP_001_EXPERIMENTAL_UNTIL_R2_6" in receipt["reason_codes"]
    assert receipt["autonomous_go"] is False
    assert receipt["human_decision_required"] is True
    assert receipt["wording_policy_version"] == tc.WORDING_POLICY_VERSION
    assert receipt["wording_policy_digest"] == tc.wording_policy_digest()
    assert receipt["operator_wording"] == tc.gate_wording(
        receipt["disposition"],
        receipt["authoritative_gate"],
    )


def test_producer_carried_not_applicable_cannot_construct_a_case() -> None:
    value = minimal_transition_case()
    value["applicability"] = {
        "schema": tc.APPLICABILITY_SCHEMA,
        "kind": tc.ApplicabilityKind.NOT_APPLICABLE.value,
        "reason_codes": ["producer.claimed.out-of-scope"],
        "profile_id": None,
        "profile_digest": None,
        "supported_denominator_digest": None,
        "qualification_receipt_digest": None,
    }
    with pytest.raises(tc.TransitionContractError) as error:
        _bind_qcp_fixture(case=value)
    assert error.value.code == "NOT_APPLICABLE_CANNOT_CONSTRUCT_TRANSITION_CASE"


def test_pack_manifest_must_name_the_case_applicability_profile() -> None:
    case, pack, content_objects = _bind_qcp_fixture(
        applicability_profile_ids=["QCP-001.EXPERIMENTAL.other-applicability-profile"]
    )

    receipt = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )

    assert "PACK_BINDING_MISMATCH" in receipt["reason_codes"]
    assert receipt["authoritative_gate"] == tc.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    assert receipt["autonomous_go"] is False


def test_projection_case_cannot_mint_any_authoritative_gate() -> None:
    value = minimal_transition_case()
    value["case_mode"] = tc.CaseMode.PROJECTION_ONLY.value
    value["replay_contract"]["mode"] = tc.CaseMode.PROJECTION_ONLY.value
    for binding in value["replay_contract"]["object_bindings"]:
        binding["location"] = "PROJECTION"
        binding["resolver_id"] = None
    case, pack, content_objects = _bind_qcp_fixture(case=value)

    receipt = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )
    assert receipt["disposition"] == tv.GateDisposition.NO_AUTHORITATIVE_GATE.value
    assert receipt["authoritative_gate"] is None
    assert receipt["replay_status"] == tv.ReplayStatus.PROJECTION_ONLY_NON_AUTHORITATIVE.value
    assert "PROJECTION_CANNOT_MINT_AUTHORITY" in receipt["reason_codes"]


def test_dependency_digest_change_emits_deterministic_reference_only_invalidation() -> None:
    previous, _, _ = _bind_qcp_fixture(revision="previous")
    current, _, _ = _bind_qcp_fixture(revision="current")

    unchanged = tv.compute_invalidation_receipt(previous, previous)
    invalidated = tv.compute_invalidation_receipt(previous, current)
    assert unchanged["state"] == "UNCHANGED"
    assert unchanged["case_content_changed"] is False
    assert unchanged["changed_dependencies"] == []
    assert unchanged["invalidation_reasons"] == []
    assert invalidated["state"] == "INVALIDATED"
    assert invalidated["case_content_changed"] is True
    assert invalidated["invalidation_reasons"] == ["DECLARED_DEPENDENCY_DIGEST_CHANGED"]
    assert invalidated["changed_dependencies"] == [
        {
            "kind": "PACK",
            "identifier": tp.QCP_001_ID,
            "previous_digest": previous["pack_binding"]["pack_manifest_digest"],
            "current_digest": current["pack_binding"]["pack_manifest_digest"],
        },
        {
            "kind": "TCB",
            "identifier": tp.QCP_001_ID,
            "previous_digest": previous["pack_binding"]["tcb_manifest_digest"],
            "current_digest": current["pack_binding"]["tcb_manifest_digest"],
        },
    ]
    assert invalidated["migration_policy"] == "REFERENCE_NOT_REWRITE"
    assert invalidated["historical_case_rewritten"] is False
    assert invalidated["authoritative"] is False
    assert invalidated["promotion_effect"] == "NONE"
    assert invalidated["claim_boundary"] == tv.INVALIDATION_CLAIM_BOUNDARY
    assert tc.canonical_json_bytes(invalidated) == tc.canonical_json_bytes(
        tv.compute_invalidation_receipt(previous, current)
    )


def test_case_byte_change_without_dependency_delta_still_invalidates() -> None:
    previous, _, _ = _bind_qcp_fixture()
    value = dict(previous)
    value["created_at"] = "2026-08-22T00:00:07.000000Z"
    current = tc.bind_transition_case_bytes(tc.canonical_json_bytes(value))

    receipt = tv.compute_invalidation_receipt(previous, current)
    assert receipt["state"] == "INVALIDATED"
    assert receipt["case_content_changed"] is True
    assert receipt["changed_dependencies"] == []
    assert receipt["invalidation_reasons"] == [
        "CASE_CONTENT_CHANGED_WITHOUT_DEPENDENCY_DELTA"
    ]


def test_verifier_never_echoes_a_producer_positive_temporal_outcome() -> None:
    case, pack, content_objects = _bind_qcp_fixture()
    producer_outcome = case["derivations"][0]["temporal_outcome"]
    receipt = tv.verify_transition_case(
        case,
        pack,
        content=tv.bind_content_objects(content_objects),
    )
    diagnostics = receipt["obligations"][0]["temporal_outcomes_and_reasons"]

    assert producer_outcome not in diagnostics
    assert tc.TemporalOutcome.INCONCLUSIVE.value in diagnostics
    assert "PRODUCER_TEMPORAL_OUTCOME_NOT_RECOMPUTED_R2_0" in diagnostics
