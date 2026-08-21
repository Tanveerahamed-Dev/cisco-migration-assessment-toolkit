from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "master-reference"))

from governance.core_sink_lineage import (  # noqa: E402
    CoreSinkLineageError,
    build_core_sink_observation_receipt,
    evaluate_core_sink_lineage,
    load_core_sink_lineage_contract,
    unavailable_core_sink_lineage,
)
import governance.core_sink_lineage as core_sink_lineage  # noqa: E402
from release.model import canonical_json, stable_id  # noqa: E402


CONTRACT_PATH = ROOT / "master-reference/governance/rendered-sink-lineage-core-contract.json"
SCHEMA_PATH = ROOT / "master-reference/schema/rendered-sink-lineage-core.schema.json"
SOURCE_PATH = ROOT / "master-reference/content/atlas-core.json"
CLAIM_CONTRACT_PATH = ROOT / "master-reference/governance/consequential-claim-contract.json"


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _git_blob_oid(raw: bytes) -> str:
    material = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(material, usedforsecurity=False).hexdigest()


def _rows(document: dict[str, object], selector: list[str]):
    rows = [(document, "")]
    for token in selector:
        collection = token.endswith("[]")
        field = token[:-2] if collection else token
        next_rows = []
        for record, pointer in rows:
            value = record[field]
            if collection:
                next_rows.extend((item, f"{pointer}/{field}/{index}") for index, item in enumerate(value))
            else:
                next_rows.append((value, f"{pointer}/{field}"))
        rows = next_rows
    return rows


def _identity(record: dict[str, object], identity: dict[str, object]) -> str:
    if identity["kind"] == "root":
        return "@root"
    if identity["kind"] == "field":
        return record[identity["field"]]
    return _digest([record[field] for field in identity["fields"]])


def _candidate_records(contract: dict[str, object], core: dict[str, object]) -> list[dict[str, object]]:
    source = contract["source_scope"]
    claim_contract = json.loads(CLAIM_CONTRACT_PATH.read_text(encoding="utf-8"))
    core_owner = next(row for row in claim_contract["source_universe"] if row["path"] == source["path"])
    owner_rules = {rule["rule_id"]: rule for rule in core_owner["object_rules"]}
    relationships = {row["field"]: row for row in core_owner["grounding"]["relationships"]}
    records: list[dict[str, object]] = []
    for rule in source["candidate_rules"]:
        owner_rule = owner_rules[rule["rule_id"]]
        field_rules = {field["field"]: field for field in owner_rule["fields"]}
        for record, pointer in _rows(core, rule["selector"]):
            record_identity = _identity(record, rule["identity"])
            grounding: list[dict[str, str]] = []
            for field_name, field_rule in sorted(field_rules.items()):
                if field_name not in record or field_rule["classification"] != "relationship_metadata":
                    continue
                relationship = relationships[field_name]
                value = record[field_name]
                if relationship["mode"] == "reference_array":
                    references = value
                elif value is None:
                    references = []
                else:
                    references = [value]
                grounding.extend({"field": field_name, "reference": reference} for reference in references)
            if not grounding:
                grounding.append(
                    {"field": "@source_owner", "reference": core_owner["grounding"]["fallback_owner_ref"]}
                )
            grounding.sort(key=lambda row: (row["field"], row["reference"]))
            for field in rule["candidate_fields"]:
                facet_path = field["facet_path"]
                identity_payload = {
                    "source_path": source["path"],
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": record_identity,
                    "facet_path": facet_path,
                }
                facet_id = "urn:atlas:claim-facet:" + _digest(identity_payload)
                records.append(
                    {
                        "id": stable_id("claim-facet-record", facet_id),
                        "entity_type": "consequential_claim_facet",
                        "evidence_state": "payload_omitted_value_fingerprint_index_only",
                        "facet_id": facet_id,
                        "source_path": source["path"],
                        "source_blob_oid": source["git_blob_oid"],
                        "source_pointer": f"{pointer}/{facet_path}",
                        "rule_id": rule["rule_id"],
                        "record_kind": rule["record_kind"],
                        "record_identity": record_identity,
                        "facet_path": facet_path,
                        "classification": "consequential_claim_candidate",
                        "claim_kind": field["claim_kind"],
                        "review_state": "pending_independent_review",
                        "grounding_digest": _digest(grounding),
                        "value_digest": _digest(record[facet_path]),
                    }
                )
    return sorted(records, key=lambda row: row["facet_id"])


def _observations(core: dict[str, object], sink_id: str) -> dict[str, list[dict[str, object]]]:
    if sink_id == "pdf.product-purpose-and-outcomes":
        prefix = "pdf.product-purpose-and-outcomes"
        disposition = "rendered_labeled"
        transform = "pdf.core_outcome_success_signal_plain_text/1"
    else:
        assert sink_id == "web.product.core-outcomes"
        prefix = "web.product"
        disposition = "rendered_identity"
        transform = "identity-text"
    rendered = [
        {
            "rule_id": "core.outcome",
            "record_identity": outcome["id"],
            "facet_path": "success_signal",
            "disposition": disposition,
            "slot_id": f"{prefix}.core.outcome.{outcome['id']}.success_signal",
            "transform_id": transform,
            "observed_value": outcome["success_signal"],
        }
        for outcome in core["outcomes"]
    ]
    return {"rendered_observations": rendered, "safety_observations": []}


@pytest.fixture()
def live():
    contract = load_core_sink_lineage_contract(CONTRACT_PATH.read_bytes())
    core = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    return contract, core, _candidate_records(contract, core)


def _evaluate(live, sink_id="web.product.core-outcomes", observations=None):
    contract, core, records = live
    return evaluate_core_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        core=core,
        source_raw=SOURCE_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={sink_id: observations or _observations(core, sink_id)},
    )


def test_contract_schema_exact_source_rule_grammar_and_denominator(live) -> None:
    contract, core, records = live
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(contract)) == []
    assert _digest(contract) == "5b1fbe15fd30bd6e77af69d169f08cbc3cbb639e2df2e85f41f31bfc0c3e53dd"
    raw = SOURCE_PATH.read_bytes()
    assert (len(raw), hashlib.sha256(raw).hexdigest(), _git_blob_oid(raw)) == (
        40_793,
        "3084a31bf02c6e44d41b189e7449e5a4265d18ed9c95765a1526d5d3b29ab6c0",
        "3d2c841f8855596007e45a5e165e2f462a95e260",
    )

    claim_contract = json.loads(CLAIM_CONTRACT_PATH.read_text(encoding="utf-8"))
    owner = next(row for row in claim_contract["source_universe"] if row["path"] == contract["source_scope"]["path"])
    expected_rules = []
    for rule in owner["object_rules"]:
        expected_rules.append(
            {
                "rule_id": rule["rule_id"],
                "record_kind": rule["record_kind"],
                "selector": rule["selector"],
                "identity": rule["identity"],
                "expected_records": rule["expected_records"],
                "candidate_fields": [
                    {
                        "facet_path": field["field"],
                        "claim_kind": field["claim_kind"],
                        "value_type": field["value_type"],
                    }
                    for field in rule["fields"]
                    if field["classification"] == "candidate"
                ],
            }
        )
    assert contract["source_scope"]["candidate_rules"] == expected_rules
    assert sum(row["expected_records"] for row in expected_rules) == 135
    assert [row["rule_id"] for row in expected_rules if not row["candidate_fields"]] == [
        "core.lifecycle_stage",
        "core.system_architecture",
        "core.domain",
    ]
    assert next(row for row in expected_rules if row["rule_id"] == "core.system_flow")["identity"] == {
        "kind": "composite",
        "fields": ["from", "to"],
    }
    assert len(records) == len({row["facet_id"] for row in records}) == 155
    payload_keys = {
        "facet_id", "source_path", "source_blob_oid", "source_pointer", "rule_id", "record_kind",
        "record_identity", "facet_path", "classification", "claim_kind", "review_state",
        "grounding_digest", "value_digest",
    }
    assert _digest([{key: row[key] for key in payload_keys} for row in records]) == contract["source_scope"]["candidate_digest"]
    assert _digest([row["facet_id"] for row in records]) == contract["source_scope"]["facet_id_set_digest"]
    assert len(core["outcomes"]) == 9


def test_both_sinks_account_155_as_nine_rendered_and_146_omitted_without_promotion(live) -> None:
    contract, core, records = live
    summary = evaluate_core_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        core=core,
        source_raw=SOURCE_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={sink: _observations(core, sink) for sink in (
            "pdf.product-purpose-and-outcomes", "web.product.core-outcomes"
        )},
    )
    assert summary["schema_version"] == "rendered-sink-lineage-core/1.0.0"
    assert summary["closes_global_gate"] is False
    assert summary["global_denominator"] == {
        "expected_candidates": 2140,
        "in_scope_candidates": 155,
        "out_of_scope_candidates": 1985,
        "independently_reviewed": 0,
        "unresolved": 2140,
        "claim_contract_digest": "cf123369749c14ef140a9eb906b63f7183e93fd45a943a25087f5411a17399b6",
        "classification_digest": "594013cefc9f293cb6b224e6f869014e6015dd6f23a4ff708899afbb44c1f19c",
        "source_receipts_digest": "aad6fbb1305ccaddea2b5257cbfa5704ba1548a1855c97bcbaa144ed6d8ecb30",
        "candidate_set_digest": "ed4bb19838118841b5f5cc3a3d7348ee9763d11e8f4ad4f610c5e3853a1f0d31",
    }
    assert summary["source"]["grounding_fallback_candidate_count"] == 62
    assert summary["source"]["safety_input_count"] == 0
    assert summary["observed_sink_count"] == 2
    for receipt in summary["sink_receipts"]:
        assert (receipt["mapped_exactly_once"], receipt["rendered"], receipt["explicitly_omitted"]) == (155, 9, 146)
        assert (receipt["unmapped"], receipt["multiply_mapped"], receipt["fallback_count"]) == (0, 0, 0)
        assert (receipt["safety_inputs_expected"], receipt["safety_inputs_bound"], receipt["safety_violations"]) == (0, 0, 0)
        assert (receipt["producer_verdict"], receipt["independent_verdict"]) == ("PASS", "BLOCK")


def test_reordered_observations_are_keyed_and_unobserved_sink_blocks(live) -> None:
    _, core, _ = live
    observations = _observations(core, "web.product.core-outcomes")
    observations["rendered_observations"].reverse()
    summary = _evaluate(live, observations=observations)
    by_sink = {row["sink_id"]: row for row in summary["sink_receipts"]}
    assert by_sink["web.product.core-outcomes"]["producer_verdict"] == "PASS"
    assert by_sink["pdf.product-purpose-and-outcomes"]["producer_verdict"] == "BLOCK"
    assert by_sink["pdf.product-purpose-and-outcomes"]["unmapped"] == 155


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda rows: rows.pop(), "core_sink_lineage_observation_count_mismatch"),
        (lambda rows: rows.append(copy.deepcopy(rows[0])), "core_sink_lineage_observation_count_mismatch"),
        (lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])), "core_sink_lineage_observation_duplicate_or_unknown"),
        (lambda rows: rows[0].__setitem__("record_identity", "SENSITIVE_CANARY"), "core_sink_lineage_observation_duplicate_or_unknown"),
        (lambda rows: rows[0].__setitem__("observed_value", "SENSITIVE_CANARY"), "core_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("slot_id", "SENSITIVE_CANARY"), "core_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("transform_id", "identity-text-v2"), "core_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("disposition", "rendered_labeled"), "core_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("rule_id", []), "core_sink_lineage_observation_invalid"),
        (lambda rows: rows[0].__setitem__("observed_value", "   "), "core_sink_lineage_observation_invalid"),
        (lambda rows: rows[0].__setitem__("observed_value", "bad\u0085value"), "core_sink_lineage_observation_invalid"),
    ],
)
def test_missing_duplicate_value_slot_transform_type_and_unicode_fail_fixed_no_echo(live, mutation, code) -> None:
    _, core, _ = live
    observations = _observations(core, "web.product.core-outcomes")
    mutation(observations["rendered_observations"])
    with pytest.raises(CoreSinkLineageError) as failure:
        _evaluate(live, observations=observations)
    assert code in failure.value.codes
    assert "SENSITIVE_CANARY" not in str(failure.value)


def test_compiler_count_duplicate_grounding_value_source_and_type_mutations_block(live) -> None:
    contract, core, records = live
    variants = [records[:-1]]
    duplicate = copy.deepcopy(records)
    duplicate[1] = copy.deepcopy(duplicate[0])
    variants.append(duplicate)
    for field, value in (
        ("grounding_digest", "0" * 64),
        ("value_digest", "0" * 64),
        ("source_blob_oid", "0" * 40),
        ("review_state", []),
    ):
        mutated = copy.deepcopy(records)
        mutated[0][field] = value
        variants.append(mutated)
    for mutated in variants:
        with pytest.raises(CoreSinkLineageError, match="compiler_subject"):
            evaluate_core_sink_lineage(
                contract=contract,
                claim_facet_records=mutated,
                core=core,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={},
            )
    with pytest.raises(CoreSinkLineageError, match="compiler_subjects_invalid"):
        evaluate_core_sink_lineage(
            contract=contract,
            claim_facet_records=tuple(records),
            core=core,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )


def test_source_object_raw_blob_oid_contract_omission_and_global_gate_are_exact(live) -> None:
    contract, core, records = live
    changed = copy.deepcopy(core)
    changed["outcomes"][0]["success_signal"] = "SENSITIVE_CANARY"
    with pytest.raises(CoreSinkLineageError, match="source_object_mismatch"):
        evaluate_core_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            core=changed,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    for raw, oid in (
        (SOURCE_PATH.read_bytes() + b" ", contract["source_scope"]["git_blob_oid"]),
        (SOURCE_PATH.read_bytes(), "0" * 40),
    ):
        with pytest.raises(CoreSinkLineageError, match="source_blob_mismatch"):
            evaluate_core_sink_lineage(
                contract=contract,
                claim_facet_records=records,
                core=core,
                source_raw=raw,
                source_blob_oid=oid,
                sink_observations={},
            )
    for mutation in (
        lambda value: value["global_denominator"].__setitem__("independently_reviewed", 155),
        lambda value: value.__setitem__("closes_global_gate", True),
        lambda value: value["sinks"][0]["omission_rules"].pop(),
        lambda value: value["sinks"][1]["omission_rules"][0].__setitem__("reason_code", "renderer_fallback"),
        lambda value: value["source_scope"]["candidate_rules"][14].__setitem__("identity", {"kind": "root"}),
    ):
        tampered = copy.deepcopy(contract)
        mutation(tampered)
        with pytest.raises(CoreSinkLineageError, match="contract_invalid"):
            evaluate_core_sink_lineage(
                contract=tampered,
                claim_facet_records=records,
                core=core,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={},
            )


def test_schema_rejects_mapping_omission_source_and_gate_promotion(live) -> None:
    contract, _, _ = live
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for path, value in (
        (("closes_global_gate",), True),
        (("global_denominator", "independently_reviewed"), 155),
        (("global_denominator", "unresolved"), 1985),
        (("source_scope", "expected_grounding_fallback_candidates"), 0),
        (("source_scope", "candidate_rules", 9, "candidate_fields"), [{"facet_path": "question", "claim_kind": "x", "value_type": "string"}]),
        (("source_scope", "candidate_rules", 14, "identity", "kind"), "root"),
        (("sinks", 0, "expected_omitted"), 145),
        (("sinks", 0, "rendered_rules", 0, "fields", 0, "transform_id"), "identity-text"),
        (("sinks", 1, "locator"), "/product"),
        (("sinks", 1, "omission_rules", 0, "reason_code"), "renderer_fallback"),
    ):
        mutated = copy.deepcopy(contract)
        cursor = mutated
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = value
        assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_zero_safety_denominator_is_exact_and_nonempty_safety_observation_fails(live) -> None:
    _, core, _ = live
    observations = _observations(core, "web.product.core-outcomes")
    observations["safety_observations"] = [
        {
            "rule_id": "core.root",
            "record_identity": "@root",
            "boundary_field": "scope",
            "observed_value": core["scope"],
            "slot_id": "web.product.fixed-prose",
            "transform_id": "identity-text",
        }
    ]
    with pytest.raises(CoreSinkLineageError, match="safety_observation_count_mismatch"):
        _evaluate(live, observations=observations)


def test_loader_bounds_duplicate_float_unicode_and_gate_promotion_fail(live) -> None:
    contract, core, records = live
    for raw, code in (
        (b'{"id":"a","id":"b"}', "contract_invalid"),
        (b'{"x":1.5}', "contract_invalid"),
        (b'{"x":9007199254740992}', "structure_exceeds_bound"),
        (b'{"x":"\\u0085"}', "structure_exceeds_bound"),
    ):
        with pytest.raises(CoreSinkLineageError, match=code):
            load_core_sink_lineage_contract(raw)
    tuple_observations = _observations(core, "web.product.core-outcomes")
    tuple_observations["rendered_observations"] = tuple(tuple_observations["rendered_observations"])
    tuple_observations["safety_observations"] = tuple(tuple_observations["safety_observations"])
    assert _evaluate(live, observations=tuple_observations)["observed_sink_count"] == 1
    assert all(row["review_state"] == "pending_independent_review" for row in records)
    assert contract["closes_global_gate"] is False


def test_unavailable_fixed_branches_never_promote_and_reject_hostile_types(live) -> None:
    contract, _, _ = live
    for reason in (
        "core_sink_lineage_compiler_subjects_not_declared",
        "core_sink_lineage_pdf_not_observed",
        "core_sink_lineage_external_pdf_unverified",
    ):
        summary = unavailable_core_sink_lineage(
            contract=contract,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            reason_code=reason,
        )
        assert summary["state"] == "not_declared"
        assert summary["closes_global_gate"] is False
        assert summary["source"]["grounding_fallback_candidate_count"] == 0
        assert summary["global_denominator"]["independently_reviewed"] == 0
        assert summary["global_denominator"]["unresolved"] == 2140
        assert all(row["producer_verdict"] == row["independent_verdict"] == "BLOCK" for row in summary["sink_receipts"])
    with pytest.raises(CoreSinkLineageError, match="unavailable_input_invalid"):
        unavailable_core_sink_lineage(
            contract=contract,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            reason_code=[],
        )

    class ThrowingEquality:
        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    with pytest.raises(CoreSinkLineageError, match="unavailable_input_invalid") as failure:
        unavailable_core_sink_lineage(
            contract=contract,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=ThrowingEquality(),
            reason_code="core_sink_lineage_pdf_not_observed",
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)
    with pytest.raises(CoreSinkLineageError, match="observation_envelope_invalid"):
        build_core_sink_observation_receipt(
            contract=contract,
            sink_id=[],
            candidates=[],
            safety_inputs=[],
            observations={},
        )


def test_evil_key_and_string_subclasses_fail_fixed_no_echo(live) -> None:
    contract, core, records = live

    class EvilKey(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    class StringSubclass(str):
        pass

    hostile_records = copy.deepcopy(records)
    facet_id = hostile_records[0].pop("facet_id")
    hostile_records[0][EvilKey("facet_id")] = facet_id
    hostile_path = copy.deepcopy(records)
    hostile_path[0]["source_path"] = StringSubclass(hostile_path[0]["source_path"])
    for variant in (hostile_records, hostile_path):
        with pytest.raises(CoreSinkLineageError, match="compiler_subject_invalid") as failure:
            evaluate_core_sink_lineage(
                contract=contract,
                claim_facet_records=variant,
                core=core,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={},
            )
        assert "SENSITIVE_CANARY" not in str(failure.value)

    envelope = _observations(core, "web.product.core-outcomes")
    rendered = envelope.pop("rendered_observations")
    envelope[EvilKey("rendered_observations")] = rendered
    rendered_row = _observations(core, "web.product.core-outcomes")
    rule_id = rendered_row["rendered_observations"][0].pop("rule_id")
    rendered_row["rendered_observations"][0][EvilKey("rule_id")] = rule_id
    for observations in (envelope, rendered_row):
        with pytest.raises(CoreSinkLineageError) as failure:
            _evaluate(live, observations=observations)
        assert "SENSITIVE_CANARY" not in str(failure.value)

    hostile_subset = {EvilKey("web.product.core-outcomes"): _observations(core, "web.product.core-outcomes")}
    with pytest.raises(CoreSinkLineageError, match="sink_subset_invalid") as failure:
        evaluate_core_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            core=core,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations=hostile_subset,
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)


def test_receipt_candidate_boundary_rejects_hostile_rows_types_and_bounds_without_echo(live) -> None:
    contract, core, records = live
    observations = _observations(core, "web.product.core-outcomes")
    canary = "SENSITIVE-RECEIPT-CANDIDATE-CANARY"

    class EvilDict(dict):
        def __getitem__(self, _key):
            raise RuntimeError(canary)

        def __iter__(self):
            raise RuntimeError(canary)

    class EvilList(list):
        def __iter__(self):
            raise RuntimeError(canary)

    class EvilKey(str):
        __hash__ = str.__hash__
        armed = False

        def __eq__(self, other):
            if type(self).armed:
                raise RuntimeError(canary)
            return str.__eq__(self, other)

    class StringSubclass(str):
        pass

    evil_key_rows = copy.deepcopy(records)
    facet_id = evil_key_rows[0].pop("facet_id")
    evil_key_rows[0][EvilKey("facet_id")] = facet_id
    variants: list[object] = [
        EvilList(records),
        tuple(records),
        7,
        [*copy.deepcopy(records[:-1]), EvilDict(records[-1])],
        [*copy.deepcopy(records[:-1]), None],
        evil_key_rows,
    ]
    string_subclass = copy.deepcopy(records)
    string_subclass[0]["facet_id"] = StringSubclass(string_subclass[0]["facet_id"])
    variants.append(string_subclass)
    oversized = copy.deepcopy(records)
    oversized[0]["record_kind"] = "x" * 16_385
    variants.append(oversized)
    reordered = copy.deepcopy(records)
    reordered.reverse()
    variants.append(reordered)

    EvilKey.armed = True
    try:
        for candidates in variants:
            with pytest.raises(CoreSinkLineageError) as failure:
                build_core_sink_observation_receipt(
                    contract=contract,
                    sink_id="web.product.core-outcomes",
                    candidates=candidates,  # type: ignore[arg-type]
                    safety_inputs=[],
                    observations=observations,
                )
            assert failure.value.codes == ("core_sink_lineage_receipt_input_invalid",)
            assert canary not in str(failure.value)
    finally:
        EvilKey.armed = False


def test_receipt_boundary_normalizes_unexpected_exceptions_without_echo(live, monkeypatch) -> None:
    contract, core, records = live
    canary = "SENSITIVE-RECEIPT-UNEXPECTED-CANARY"

    def explode(_sink, _candidates):
        raise RuntimeError(canary)

    monkeypatch.setattr(core_sink_lineage, "_expanded_sink_mapping", explode)
    with pytest.raises(CoreSinkLineageError) as failure:
        build_core_sink_observation_receipt(
            contract=contract,
            sink_id="web.product.core-outcomes",
            candidates=records,
            safety_inputs=[],
            observations=_observations(core, "web.product.core-outcomes"),
        )
    assert failure.value.codes == ("core_sink_lineage_receipt_input_invalid",)
    assert canary not in str(failure.value)


@pytest.mark.parametrize(
    "entrypoint,expected_code",
    [
        ("evaluate", "core_sink_lineage_input_invalid"),
        ("unavailable", "core_sink_lineage_unavailable_input_invalid"),
    ],
)
def test_public_lineage_boundaries_normalize_unexpected_exceptions_without_echo(
    live,
    monkeypatch,
    entrypoint,
    expected_code,
) -> None:
    contract, core, records = live
    canary = "SENSITIVE-LINEAGE-UNEXPECTED-CANARY"

    def explode(_contract):
        raise RuntimeError(canary)

    monkeypatch.setattr(core_sink_lineage, "_validate_contract", explode)
    with pytest.raises(CoreSinkLineageError) as failure:
        if entrypoint == "evaluate":
            evaluate_core_sink_lineage(
                contract=contract,
                claim_facet_records=records,
                core=core,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={},
            )
        else:
            unavailable_core_sink_lineage(
                contract=contract,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                reason_code="core_sink_lineage_pdf_not_observed",
            )
    assert failure.value.codes == (expected_code,)
    assert canary not in str(failure.value)


def test_composite_flow_identity_and_contract_owned_omissions_are_exact(live) -> None:
    contract, core, records = live
    flow_records = [row for row in records if row["rule_id"] == "core.system_flow"]
    expected_identities = {
        _digest([flow["from"], flow["to"]]) for flow in core["system_architecture"]["flow"]
    }
    assert {row["record_identity"] for row in flow_records} == expected_identities
    assert not {"core.lifecycle_stage", "core.system_architecture", "core.domain"} & {
        row["rule_id"] for row in records
    }
    for sink in contract["sinks"]:
        rendered = sum(row["expected_subjects"] for row in sink["rendered_rules"])
        omitted = sum(row["expected_subjects"] for row in sink["omission_rules"])
        assert (rendered, omitted, rendered + omitted) == (9, 146, 155)
