from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator, ValidationError


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MASTER_REFERENCE.parent
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from governance.consequential_claims import (  # noqa: E402
    COMPILER_INTEGRITY_PREDICATES,
    CONTENT_PATHS,
    CONTRACT_PATH,
    EXPECTED_SOURCE_COUNTS,
    EXPECTED_SOURCE_SPEC_DIGESTS,
    ConsequentialClaimContractError,
    _collect_source_candidates,
    evaluate_bounded_curated_claims,
    unavailable_bounded_curated_claim_summary,
)
from release.content_bundle import CONTENT_FILES  # noqa: E402


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def oid(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def oid64(raw: bytes) -> str:
    return hashlib.sha256(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def load(path: str) -> dict[str, Any]:
    value = json.loads((REPOSITORY_ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def fixture() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    return load(CONTRACT_PATH), {path: load(path) for path in CONTENT_PATHS}


def evaluate(contract: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    blobs: dict[str, tuple[str, bytes]] = {}
    for path in CONTENT_PATHS:
        raw = canonical(sources[path])
        blobs[path] = (oid(raw), raw)
        next(item for item in contract["source_universe"] if item["path"] == path)["git_blob_oid"] = oid(raw)
    raw = canonical(contract)
    return evaluate_bounded_curated_claims(
        contract_raw=raw,
        contract_git_blob_oid=oid(raw),
        source_blobs=blobs,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
        compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
    )


def tracked() -> dict[str, Any]:
    raw = (REPOSITORY_ROOT / CONTRACT_PATH).read_bytes()
    blobs = {
        path: (oid((REPOSITORY_ROOT / path).read_bytes()), (REPOSITORY_ROOT / path).read_bytes())
        for path in CONTENT_PATHS
    }
    return evaluate_bounded_curated_claims(
        contract_raw=raw,
        contract_git_blob_oid=oid(raw),
        source_blobs=blobs,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
        compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
    )


def fails(code: str, callback: Callable[[], Any]) -> None:
    with pytest.raises(ConsequentialClaimContractError) as raised:
        callback()
    assert code in raised.value.codes


def rule(contract: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(r for source in contract["source_universe"] for r in source["object_rules"] if r["rule_id"] == rule_id)


def registries(sources: dict[str, dict[str, Any]]) -> dict[str, frozenset[str]]:
    core = sources[CONTENT_PATHS[0]]
    capability = sources[CONTENT_PATHS[1]]
    delivery = sources[CONTENT_PATHS[2]]
    horizon = sources[CONTENT_PATHS[3]]
    output = sources[CONTENT_PATHS[4]]
    return {
        "owner_refs": frozenset(row["id"] for row in core["owners"]),
        "gap_refs": frozenset(row["id"] for row in delivery["gaps"]),
        "traffic_plane_refs": frozenset(row["id"] for row in core["traffic_model"]["planes"]),
        "system_plane_refs": frozenset(row["id"] for row in core["system_architecture"]["planes"]),
        "source_refs": frozenset(row["id"] for row in horizon["watch_families"]),
        "affected_capability_refs": frozenset(
            row["id"] for domain in capability["domains"] for row in domain["entries"]
        ),
        "cross_artifact_ids": frozenset(row["id"] for row in output["members"]),
    }


def candidates(contract: dict[str, Any], sources: dict[str, dict[str, Any]], path: str) -> list[dict[str, Any]]:
    source_contract = next(item for item in contract["source_universe"] if item["path"] == path)
    result, _digest = _collect_source_candidates(
        source_contract=source_contract,
        document=sources[path],
        source_oid="a" * 40,
        reference_registries=registries(sources),
    )
    return result


def test_tracked_contract_schemas_exact_totals_and_fixed_gate() -> None:
    contract_schema = load("master-reference/schema/consequential-claim-contract.schema.json")
    ledger_schema = load("master-reference/schema/completeness-ledger.schema.json")
    Draft202012Validator.check_schema(contract_schema)
    Draft202012Validator.check_schema(ledger_schema)
    Draft202012Validator(contract_schema).validate(load(CONTRACT_PATH))
    summary = tracked()
    focused = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": ledger_schema["$defs"],
        "$ref": "#/$defs/consequentialClaimDenominator",
    }
    Draft202012Validator(focused).validate(summary)
    assert CONTENT_PATHS == tuple(f"master-reference/content/{name}" for name in CONTENT_FILES)
    assert {row["path"]: row["candidate_count"] for row in summary["source_receipts"]} == EXPECTED_SOURCE_COUNTS
    assert (summary["source_universe_registered"], summary["source_universe_unclassified"]) == (5, 0)
    assert (summary["expected_candidates"], summary["discovered_candidates"], summary["classified_candidates"]) == (
        2140,
        2140,
        2140,
    )
    assert (summary["independently_reviewed_candidates"], summary["unresolved_candidates"]) == (0, 2140)
    assert summary["closed"] is False
    assert summary["error_codes"] == [
        "consequential_claim_independent_review_pending",
        "consequential_claim_rendered_sink_universe_incomplete",
    ]
    assert all(len(row["rule_set_digest"]) == len(row["candidate_digest"]) == 64 for row in summary["source_receipts"])
    assert len(summary["candidate_set_digest"]) == 64
    rendered_summary = json.dumps(summary, ensure_ascii=False)
    candidate_canary = load(CONTENT_PATHS[0])["current_baseline"][0]["statement"]
    assert candidate_canary not in rendered_summary


def test_reviewed_source_semantic_specs_have_independent_digest_pins() -> None:
    assert EXPECTED_SOURCE_SPEC_DIGESTS == {
        "master-reference/content/atlas-core.json": (
            "88945e355209ff0d42376c1fc5273f23729a21d5d82021f7c1ae63d38f65402e"
        ),
        "master-reference/content/capability-catalog.json": (
            "ae20a8f8e43d41ff3e752366a7f4d822f839ad91735bd16bcce9fd7b336f0450"
        ),
        "master-reference/content/delivery-governance.json": (
            "62b113259ea0bc532a3c76faa63c8ee55f20746dd928e17a29b380ca45c15d38"
        ),
        "master-reference/content/open-horizon-register.json": (
            "5739641632a20c199cb3b12f57efb18825879c45dc0c2d8be22da6079c9c6d27"
        ),
        "master-reference/content/output-contract.json": (
            "417d637ca609aed5e37c62004cc279618655c0c214ef4f61dab1db3b829d9084"
        ),
    }


@pytest.mark.parametrize(
    "reason",
    [
        "consequential_claim_contract_absent",
        "consequential_claim_contract_invalid",
        "consequential_claim_dirty_preview_not_eligible",
    ],
)
def test_not_declared_shape_retains_source_universe_residual(reason: str) -> None:
    summary = unavailable_bounded_curated_claim_summary(reason_code=reason)
    assert summary["error_codes"] == sorted([reason, "consequential_claim_source_universe_incomplete"])
    assert summary["closed"] is False and summary["source_universe_unclassified"] == 5
    ledger_schema = load("master-reference/schema/completeness-ledger.schema.json")
    focused = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": ledger_schema["$defs"],
        "$ref": "#/$defs/consequentialClaimDenominator",
    }
    Draft202012Validator(focused).validate(summary)
    for commit, tree in (("a" * 40, None), (None, "b" * 64)):
        invalid = copy.deepcopy(summary)
        invalid["source_commit"] = commit
        invalid["source_tree_digest"] = tree
        with pytest.raises(ValidationError):
            Draft202012Validator(focused).validate(invalid)


@pytest.mark.parametrize("reason", ["SENSITIVE_CANARY", None, 7])
def test_not_declared_reason_is_fixed_and_never_echoed(reason: Any) -> None:
    with pytest.raises(ConsequentialClaimContractError) as raised:
        unavailable_bounded_curated_claim_summary(reason_code=reason)
    assert raised.value.codes == ("consequential_claim_contract_invalid",)
    assert "SENSITIVE_CANARY" not in str(raised.value)


@pytest.mark.parametrize("shape", ["rule", "field", "identity", "constraint", "grounding", "relationship"])
def test_unknown_contract_fields_fail_all_rule_shapes_without_echo(shape: str) -> None:
    contract, sources = fixture()
    target: dict[str, Any] = {
        "rule": rule(contract, "core.root"),
        "field": rule(contract, "core.root")["fields"][0],
        "identity": rule(contract, "core.root")["identity"],
        "constraint": rule(contract, "core.controlled_state")["constraints"][0],
        "grounding": contract["source_universe"][0]["grounding"],
        "relationship": contract["source_universe"][0]["grounding"]["relationships"][0],
    }[shape]
    target["SENSITIVE_CANARY"] = "do-not-echo"
    with pytest.raises(ConsequentialClaimContractError) as raised:
        evaluate(contract, sources)
    assert "SENSITIVE_CANARY" not in str(raised.value) and "do-not-echo" not in str(raised.value)


def test_semantic_spec_rejects_equal_count_reclassification_and_other_remaps() -> None:
    for mutate in (
        lambda c: (
            rule(c, "core.root")["fields"][3].update(classification="candidate", claim_kind="claim"),
            rule(c, "core.root")["fields"][5].update(classification="label_metadata", claim_kind=None),
        ),
        lambda c: rule(c, "core.root").update(record_kind="weakened"),
        lambda c: rule(c, "core.current_baseline")["fields"][2].update(value_type="any"),
        lambda c: c["source_universe"][0]["grounding"].update(fallback_owner_ref="owner.brand"),
    ):
        contract, sources = fixture()
        mutate(contract)
        fails("consequential_claim_source_semantic_spec_mismatch", lambda: evaluate(contract, sources))


@pytest.mark.parametrize("value_type", ["any", "array", "object"])
def test_candidate_fields_cannot_use_unbounded_generic_value_types(value_type: str) -> None:
    contract, sources = fixture()
    rule(contract, "core.current_baseline")["fields"][1]["value_type"] = value_type
    expected = (
        "consequential_claim_field_rule_classification_invalid"
        if value_type == "any"
        else "consequential_claim_candidate_value_type_too_generic"
    )
    fails(expected, lambda: evaluate(contract, sources))


def test_count_shrink_growth_unknown_and_overlap_fail_closed() -> None:
    contract, sources = fixture()
    sources[CONTENT_PATHS[1]]["domains"][0]["entries"].pop()
    fails("consequential_claim_record_count_mismatch", lambda: evaluate(contract, sources))
    contract, sources = fixture()
    added = copy.deepcopy(sources[CONTENT_PATHS[1]]["domains"][0]["entries"][0])
    added["id"] = "cap.fixture-growth"
    sources[CONTENT_PATHS[1]]["domains"][0]["entries"].append(added)
    fails("consequential_claim_record_count_mismatch", lambda: evaluate(contract, sources))
    contract, sources = fixture()
    sources[CONTENT_PATHS[2]]["gaps"][0]["SENSITIVE_CANARY"] = "do-not-echo"
    with pytest.raises(ConsequentialClaimContractError) as raised:
        evaluate(contract, sources)
    assert raised.value.codes == ("consequential_claim_object_field_unclassified",)
    assert "do-not-echo" not in str(raised.value)


@pytest.mark.parametrize("value", [None, False, "", [], {}, {"x": False}, {"x": []}])
def test_baseline_value_rejects_null_bool_and_empty_domains(value: Any) -> None:
    contract, sources = fixture()
    sources[CONTENT_PATHS[0]]["current_baseline"][0]["value"] = value
    fails("consequential_claim_field_value_type_invalid", lambda: evaluate(contract, sources))


def test_false_and_explicit_empty_candidate_values_are_preserved() -> None:
    contract, sources = fixture()
    # Both values are real tracked candidates: lab truth mutation is false; invariant exceptions may be empty.
    assert sources[CONTENT_PATHS[2]]["labs"][0]["mutates_assessment_truth"] is False
    assert any(row["exceptions_allowed"] == [] for row in sources[CONTENT_PATHS[2]]["invariants"])
    summary = evaluate(contract, sources)
    assert summary["discovered_candidates"] == 2140


def test_reference_registry_and_reference_values_are_exact_and_nonblank() -> None:
    contract, sources = fixture()
    sources[CONTENT_PATHS[0]]["owners"][1]["id"] = sources[CONTENT_PATHS[0]]["owners"][0]["id"]
    fails("consequential_claim_grounding_registry_invalid", lambda: evaluate(contract, sources))
    for bad in ([" "], ["owner.reference.contract", "owner.reference.contract"]):
        contract, sources = fixture()
        sources[CONTENT_PATHS[0]]["current_baseline"][0]["owner_refs"] = bad
        fails("consequential_claim_field_value_type_invalid", lambda: evaluate(contract, sources))


@pytest.mark.parametrize("control", ["\x00", "\x1f", "\x7f", "\x85"])
def test_decoded_control_characters_are_outside_the_portable_string_domain(control: str) -> None:
    contract, sources = fixture()
    sources[CONTENT_PATHS[1]]["domains"][0]["entries"][0]["current_scope"] = f"scope{control}marker"
    fails("consequential_claim_json_structure_exceeds_bound", lambda: evaluate(contract, sources))


@pytest.mark.parametrize("value", ["\ufeff", "\u180e"])
def test_python_nonblank_unicode_scalars_are_valid_in_schema_and_evaluator(value: str) -> None:
    schema = load("master-reference/schema/consequential-claim-contract.schema.json")
    focused = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/nonblankString"}
    Draft202012Validator(focused).validate(value)
    contract, sources = fixture()
    sources[CONTENT_PATHS[1]]["domains"][0]["entries"][0]["current_scope"] = value
    assert evaluate(contract, sources)["discovered_candidates"] == 2_140


@pytest.mark.parametrize("value", ["\u00a0", "\u2007", "\u202f"])
def test_python_blank_unicode_strings_are_invalid_in_schema_and_evaluator(value: str) -> None:
    schema = load("master-reference/schema/consequential-claim-contract.schema.json")
    focused = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/nonblankString"}
    with pytest.raises(ValidationError):
        Draft202012Validator(focused).validate(value)
    contract, sources = fixture()
    sources[CONTENT_PATHS[1]]["domains"][0]["entries"][0]["current_scope"] = value
    fails("consequential_claim_field_value_type_invalid", lambda: evaluate(contract, sources))


def test_nullable_relationship_registry_uses_the_same_portable_string_domain() -> None:
    schema = load("master-reference/schema/consequential-claim-contract.schema.json")
    focused = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/relationship"}
    for registry in (None, "owner_refs", "\ufeff", "\u180e"):
        Draft202012Validator(focused).validate({"field": "owner_refs", "mode": "reference_array", "registry": registry})
    for registry in ("\u00a0", "\u2007", "\u202f"):
        with pytest.raises(ValidationError):
            Draft202012Validator(focused).validate(
                {"field": "owner_refs", "mode": "reference_array", "registry": registry}
            )


def test_declared_owner_fields_must_be_used_by_a_classified_rule() -> None:
    contract, sources = fixture()
    contract["source_universe"][0]["grounding"]["declared_owner_fields"] = ["authority"]
    fails("consequential_claim_declared_owner_field_coverage_invalid", lambda: evaluate(contract, sources))


def test_public_evaluator_rejects_malformed_argument_types_with_fixed_codes() -> None:
    contract_raw = (REPOSITORY_ROOT / CONTRACT_PATH).read_bytes()
    source_blobs = {
        path: (oid((REPOSITORY_ROOT / path).read_bytes()), (REPOSITORY_ROOT / path).read_bytes())
        for path in CONTENT_PATHS
    }
    valid = {
        "contract_raw": contract_raw,
        "contract_git_blob_oid": oid(contract_raw),
        "source_blobs": source_blobs,
        "source_commit": "a" * 40,
        "source_tree_digest": "b" * 64,
        "compiler_claim_predicates": sorted(COMPILER_INTEGRITY_PREDICATES),
    }
    mutations = [
        ("consequential_claim_contract_malformed", {"contract_raw": None}),
        ("consequential_claim_contract_blob_identity_mismatch", {"contract_git_blob_oid": None}),
        ("consequential_claim_source_binding_invalid", {"source_commit": None}),
        ("consequential_claim_source_binding_invalid", {"source_tree_digest": None}),
        ("consequential_claim_source_universe_membership_invalid", {"source_blobs": None}),
        (
            "consequential_claim_source_blob_identity_invalid",
            {"source_blobs": {**source_blobs, CONTENT_PATHS[0]: ["a" * 40, b"raw"]}},
        ),
        ("consequential_claim_integrity_claim_set_mismatch", {"compiler_claim_predicates": None}),
    ]
    for code, mutation in mutations:
        arguments = {**valid, **mutation}
        fails(code, lambda arguments=arguments: evaluate_bounded_curated_claims(**arguments))


def test_every_claim_blob_uses_the_selected_commit_object_format() -> None:
    contract, sources = fixture()
    blobs = {path: (oid(canonical(sources[path])), canonical(sources[path])) for path in CONTENT_PATHS}
    contract_raw = canonical(contract)
    fails(
        "consequential_claim_contract_blob_identity_mismatch",
        lambda: evaluate_bounded_curated_claims(
            contract_raw=contract_raw,
            contract_git_blob_oid=oid64(contract_raw),
            source_blobs=blobs,
            source_commit="a" * 40,
            source_tree_digest="b" * 64,
            compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
        ),
    )

    path = CONTENT_PATHS[0]
    source_raw = blobs[path][1]
    mixed_oid = oid64(source_raw)
    blobs[path] = (mixed_oid, source_raw)
    next(item for item in contract["source_universe"] if item["path"] == path)["git_blob_oid"] = mixed_oid
    contract_raw = canonical(contract)
    fails(
        "consequential_claim_source_blob_identity_invalid",
        lambda: evaluate_bounded_curated_claims(
            contract_raw=contract_raw,
            contract_git_blob_oid=oid(contract_raw),
            source_blobs=blobs,
            source_commit="a" * 40,
            source_tree_digest="b" * 64,
            compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
        ),
    )


def test_claim_schemas_require_one_git_object_format() -> None:
    contract_schema = load("master-reference/schema/consequential-claim-contract.schema.json")
    contract_validator = Draft202012Validator(contract_schema)
    contract = load(CONTRACT_PATH)
    contract_validator.validate(contract)

    mixed_contract = copy.deepcopy(contract)
    mixed_contract["source_universe"][0]["git_blob_oid"] = "a" * 64
    with pytest.raises(ValidationError):
        contract_validator.validate(mixed_contract)

    sha256_contract = copy.deepcopy(contract)
    for source in sha256_contract["source_universe"]:
        source["git_blob_oid"] = "a" * 64
    contract_validator.validate(sha256_contract)

    ledger_schema = load("master-reference/schema/completeness-ledger.schema.json")
    focused = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": ledger_schema["$defs"],
        "$ref": "#/$defs/consequentialClaimDenominator",
    }
    ledger_validator = Draft202012Validator(focused)
    summary = tracked()
    ledger_validator.validate(summary)

    for mutate in (
        lambda value: value.update(source_commit="a" * 64),
        lambda value: value.update(contract_git_blob_oid="b" * 64),
        lambda value: value["source_receipts"][0].update(git_blob_oid="c" * 64),
    ):
        mixed_summary = copy.deepcopy(summary)
        mutate(mixed_summary)
        with pytest.raises(ValidationError):
            ledger_validator.validate(mixed_summary)

    sha256_summary = copy.deepcopy(summary)
    sha256_summary["source_commit"] = "a" * 64
    sha256_summary["contract_git_blob_oid"] = "b" * 64
    for receipt in sha256_summary["source_receipts"]:
        receipt["git_blob_oid"] = "c" * 64
    ledger_validator.validate(sha256_summary)


def test_domain_semantic_constraints_reject_representative_downgrades() -> None:
    mutations = [
        (CONTENT_PATHS[1], lambda s: s["domains"][0]["entries"][0].update(state="invented")),
        (CONTENT_PATHS[2], lambda s: s["labs"][0].update(content_role="authoritative")),
        (CONTENT_PATHS[2], lambda s: s["labs"][1]["gap_refs"].remove("gap.training-labs")),
        (CONTENT_PATHS[2], lambda s: s["opportunity_portfolio"]["items"][0]["axes"].update(user_value=6)),
        (CONTENT_PATHS[3], lambda s: s.update(mutates_assessment_truth=True)),
        (CONTENT_PATHS[4], lambda s: s["members"][0]["dossier"]["producing_writer"].update(path="unexpected")),
    ]
    for path, mutate in mutations:
        contract, sources = fixture()
        mutate(sources[path])
        fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))


def test_controlled_state_and_maturity_vocabularies_are_closed_across_records() -> None:
    mutations = [
        lambda core: core["controlled_states"][0].update(value="partial"),
        lambda core: core["maturity_model"][0].update(level=1),
        lambda core: core["current_maturity"][0].update(level=999),
    ]
    for mutate in mutations:
        contract, sources = fixture()
        mutate(sources[CONTENT_PATHS[0]])
        fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))

    contract, sources = fixture()
    del sources[CONTENT_PATHS[0]]["controlled_states"][0]["value"]
    fails("consequential_claim_object_field_unclassified", lambda: evaluate(contract, sources))


def test_current_state_forbids_gap_refs_while_every_other_state_requires_them() -> None:
    contract, sources = fixture()
    current = next(
        entry
        for domain in sources[CONTENT_PATHS[1]]["domains"]
        for entry in domain["entries"]
        if entry["state"] == "current"
    )
    current["gap_refs"] = [sources[CONTENT_PATHS[2]]["gaps"][0]["id"]]
    fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))


def test_horizon_unknown_is_the_only_signal_allowed_without_source_refs() -> None:
    contract, sources = fixture()
    substantive = next(signal for signal in sources[CONTENT_PATHS[3]]["signals"] if signal["id"] != "horizon.unknown")
    substantive["source_refs"] = []
    fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))

    contract, sources = fixture()
    unknown = next(signal for signal in sources[CONTENT_PATHS[3]]["signals"] if signal["id"] == "horizon.unknown")
    unknown["source_refs"] = [sources[CONTENT_PATHS[3]]["watch_families"][0]["id"]]
    fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))

    contract, sources = fixture()
    noncurrent = next(
        entry
        for domain in sources[CONTENT_PATHS[1]]["domains"]
        for entry in domain["entries"]
        if entry["state"] != "current"
    )
    noncurrent["gap_refs"] = []
    fails("consequential_claim_semantic_constraint_failed", lambda: evaluate(contract, sources))


def test_facet_ids_ignore_value_blob_and_record_order_but_pointers_are_concrete() -> None:
    contract, sources = fixture()
    path = CONTENT_PATHS[1]
    before = candidates(contract, sources, path)
    target = sources[path]["domains"][0]["entries"][0]
    target["current_scope"] += " changed"
    changed = candidates(contract, sources, path)
    facet = next(
        row for row in before if row["record_identity"] == target["id"] and row["facet_path"] == "current_scope"
    )
    changed_facet = next(row for row in changed if row["facet_id"] == facet["facet_id"])
    assert changed_facet["value_digest"] != facet["value_digest"]
    # Source OID is carried in records, but never in the facet identity.
    source_contract = next(item for item in contract["source_universe"] if item["path"] == path)
    blob_changed, _ = _collect_source_candidates(
        source_contract=source_contract,
        document=sources[path],
        source_oid="b" * 40,
        reference_registries=registries(sources),
    )
    assert {row["facet_id"] for row in blob_changed} == {row["facet_id"] for row in changed}
    sources[path]["domains"][0]["entries"].reverse()
    reordered = candidates(contract, sources, path)
    after = next(row for row in reordered if row["facet_id"] == facet["facet_id"])
    assert {row["facet_id"] for row in reordered} == {row["facet_id"] for row in changed}
    assert after["source_pointer"] != changed_facet["source_pointer"]
    assert facet["facet_id"].startswith("urn:atlas:claim-facet:") and len(facet["facet_id"].split(":")[-1]) == 64


def test_grounding_mutation_changes_grounding_digest_not_facet_id() -> None:
    contract, sources = fixture()
    path = CONTENT_PATHS[1]
    target = sources[path]["domains"][0]["entries"][0]
    before = next(row for row in candidates(contract, sources, path) if row["record_identity"] == target["id"])
    target["owner_refs"] = ["owner.reference.contract"]
    after = next(row for row in candidates(contract, sources, path) if row["facet_id"] == before["facet_id"])
    assert after["grounding_digest"] != before["grounding_digest"]


def test_grounding_uses_explicit_references_or_fallback_but_never_both() -> None:
    contract, sources = fixture()
    core_candidates = candidates(contract, sources, CONTENT_PATHS[0])
    explicitly_grounded = next(
        row
        for row in core_candidates
        if row["record_identity"] == "baseline.product.scope" and row["facet_path"] == "statement"
    )
    expected_explicit = [
        {"field": "owner_refs", "reference": "owner.operating.doctrine"},
    ]
    assert explicitly_grounded["grounding_digest"] == hashlib.sha256(canonical(expected_explicit)).hexdigest()

    fallback_grounded = next(
        row
        for row in core_candidates
        if row["record_kind"] == "truth_contract" and row["facet_path"] == "declared_scope_promise"
    )
    expected_fallback = [
        {"field": "@source_owner", "reference": "owner.reference.contract"},
    ]
    assert fallback_grounded["grounding_digest"] == hashlib.sha256(canonical(expected_fallback)).hexdigest()


def test_ledger_receipt_source_split_rejects_duplicate_or_missing_rows() -> None:
    schema = load("master-reference/schema/completeness-ledger.schema.json")
    focused = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        "$ref": "#/$defs/consequentialClaimDenominator",
    }
    summary = tracked()
    for rows in ([summary["source_receipts"][0]] * 5, summary["source_receipts"][:-1]):
        mutated = copy.deepcopy(summary)
        mutated["source_receipts"] = rows
        with pytest.raises(ValidationError):
            Draft202012Validator(focused).validate(mutated)


def test_raw_blob_duplicate_keys_portable_numbers_and_binding_fail() -> None:
    for raw, code in (
        (b'{"x":1,"x":2}', "consequential_claim_json_duplicate_key"),
        (b'{"x":9007199254740992}', "consequential_claim_json_number_outside_portable_domain"),
        (b'{"x":1.0}', "consequential_claim_json_number_outside_portable_domain"),
        (b'{"x":1e0}', "consequential_claim_json_number_outside_portable_domain"),
        (b'{"x":"\\ud800"}', "consequential_claim_json_structure_exceeds_bound"),
    ):
        with pytest.raises(ConsequentialClaimContractError) as raised:
            evaluate_bounded_curated_claims(
                contract_raw=raw,
                contract_git_blob_oid=oid(raw),
                source_blobs={},
                source_commit="a" * 40,
                source_tree_digest="b" * 64,
                compiler_claim_predicates=[],
            )
        assert raised.value.codes == (code,)
