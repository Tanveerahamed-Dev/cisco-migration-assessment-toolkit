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

from governance.capability_sink_lineage import (  # noqa: E402
    CapabilitySinkLineageError,
    build_capability_sink_observation_receipt,
    evaluate_capability_sink_lineage,
    load_capability_sink_lineage_contract,
    unavailable_capability_sink_lineage,
)
from release.model import canonical_json, stable_id  # noqa: E402


CONTRACT_PATH = ROOT / "master-reference/governance/rendered-sink-lineage-capability-contract.json"
SCHEMA_PATH = ROOT / "master-reference/schema/rendered-sink-lineage-capability.schema.json"
SOURCE_PATH = ROOT / "master-reference/content/capability-catalog.json"


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _entries(capability: dict[str, object]):
    for domain_index, domain in enumerate(capability["domains"]):
        for entry_index, entry in enumerate(domain["entries"]):
            yield entry, f"/domains/{domain_index}/entries/{entry_index}"


def _candidate_records(
    contract: dict[str, object], capability: dict[str, object]
) -> list[dict[str, object]]:
    source = contract["source_scope"]
    records: list[dict[str, object]] = []
    for entry, pointer in _entries(capability):
        grounding: list[dict[str, str]] = []
        for field in ("gap_refs", "owner_refs", "traffic_plane_refs"):
            grounding.extend(
                {"field": field, "reference": reference}
                for reference in entry.get(field, [])
            )
        if not grounding:
            grounding = [{"field": "@source_owner", "reference": "owner.reference.contract"}]
        grounding.sort(key=lambda row: (row["field"], row["reference"]))
        for field, claim_kind in (("state", "support_state"), ("current_scope", "scope_boundary")):
            identity = {
                "source_path": source["path"],
                "rule_id": "capability.entry",
                "record_kind": "capability_entry",
                "record_identity": entry["id"],
                "facet_path": field,
            }
            facet_id = "urn:atlas:claim-facet:" + _digest(identity)
            records.append(
                {
                    "id": stable_id("claim-facet-record", facet_id),
                    "entity_type": "consequential_claim_facet",
                    "evidence_state": "payload_omitted_value_fingerprint_index_only",
                    "facet_id": facet_id,
                    "source_path": source["path"],
                    "source_blob_oid": source["git_blob_oid"],
                    "source_pointer": f"{pointer}/{field}",
                    "rule_id": "capability.entry",
                    "record_kind": "capability_entry",
                    "record_identity": entry["id"],
                    "facet_path": field,
                    "classification": "consequential_claim_candidate",
                    "claim_kind": claim_kind,
                    "review_state": "pending_independent_review",
                    "grounding_digest": _digest(grounding),
                    "value_digest": _digest(entry[field]),
                }
            )
    return sorted(records, key=lambda row: row["facet_id"])


def _observations(
    capability: dict[str, object], sink_id: str
) -> dict[str, list[dict[str, object]]]:
    if sink_id == "pdf.capability-catalog":
        rendered = {
            "state": ("rendered_labeled", "pdf.capability_heading_state/1"),
            "current_scope": ("rendered_labeled", "pdf.capability_scope_plain_text/1"),
        }
        prefix = "pdf.capabilities"
        safety_transform = {
            "capability.root": "pdf.capability_support_contract/1",
            "capability.entry_contract": "pdf.capability_support_contract/1",
            "capability.entry": "pdf.capability_entry_boundary/1",
        }
    else:
        assert sink_id == "web.capabilities.default"
        rendered = {
            "state": ("rendered_derived", "state-mark-label"),
            "current_scope": ("rendered_identity", "identity-text"),
        }
        prefix = "web.capabilities"
        safety_transform = {
            "capability.root": "visible-source-contract-text",
            "capability.entry_contract": "visible-source-contract-text",
            "capability.entry": "visible-source-contract-text",
        }
    rendered_rows: list[dict[str, object]] = []
    for entry, _pointer in _entries(capability):
        for field in ("state", "current_scope"):
            disposition, transform_id = rendered[field]
            rendered_rows.append(
                {
                    "rule_id": "capability.entry",
                    "record_identity": entry["id"],
                    "facet_path": field,
                    "disposition": disposition,
                    "slot_id": f"{prefix}.capability.entry.{entry['id']}.{field}",
                    "transform_id": transform_id,
                    "observed_value": entry[field],
                }
            )
    safety_rows: list[dict[str, object]] = [
        {
            "rule_id": "capability.root",
            "record_identity": "@root",
            "boundary_field": "denominator_rule",
            "observed_value": capability["denominator_rule"],
            "slot_id": f"{prefix}.capability.root.@root.denominator_rule",
            "transform_id": safety_transform["capability.root"],
        }
    ]
    for field in ("current", "partial", "incomplete", "catalog_presence"):
        safety_rows.append(
            {
                "rule_id": "capability.entry_contract",
                "record_identity": "@root",
                "boundary_field": field,
                "observed_value": capability["entry_contract"][field],
                "slot_id": f"{prefix}.capability.entry_contract.@root.{field}",
                "transform_id": safety_transform["capability.entry_contract"],
            }
        )
    training = next(entry for entry, _ in _entries(capability) if entry["id"] == "cap.engine.training-curriculum")
    for field in ("content_role", "mutates_assessment_truth"):
        safety_rows.append(
            {
                "rule_id": "capability.entry",
                "record_identity": training["id"],
                "boundary_field": field,
                "observed_value": training[field],
                "slot_id": f"{prefix}.capability.entry.{training['id']}.{field}",
                "transform_id": safety_transform["capability.entry"],
            }
        )
    return {"rendered_observations": rendered_rows, "safety_observations": safety_rows}


@pytest.fixture()
def live():
    contract = load_capability_sink_lineage_contract(CONTRACT_PATH.read_bytes())
    capability = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    return contract, capability, _candidate_records(contract, capability)


def _evaluate(live, sink_id="web.capabilities.default", observations=None):
    contract, capability, records = live
    return evaluate_capability_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        capability=capability,
        source_raw=SOURCE_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={sink_id: observations or _observations(capability, sink_id)},
    )


def test_contract_schema_exact_source_and_candidate_denominator(live) -> None:
    contract, capability, records = live
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(contract)) == []
    assert _digest(contract) == "59a2f835396156f801d22ab5c367e36d1426ece04af87de8436488fa3a84db34"
    assert hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest() == contract["source_scope"]["sha256"]
    assert len(capability["domains"]) == 12
    assert len(list(_entries(capability))) == 213
    assert len(records) == len({row["facet_id"] for row in records}) == 426
    assert _digest(sorted(row["facet_id"] for row in records)) == contract["source_scope"]["facet_id_set_digest"]
    payload_keys = {
        "facet_id", "source_path", "source_blob_oid", "source_pointer", "rule_id", "record_kind",
        "record_identity", "facet_path", "classification", "claim_kind", "review_state",
        "grounding_digest", "value_digest",
    }
    assert _digest([{key: row[key] for key in payload_keys} for row in records]) == contract["source_scope"]["candidate_digest"]


def test_both_sinks_map_every_facet_and_seven_boundaries_but_stay_blocked(live) -> None:
    contract, capability, records = live
    summary = evaluate_capability_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        capability=capability,
        source_raw=SOURCE_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={sink: _observations(capability, sink) for sink in ("pdf.capability-catalog", "web.capabilities.default")},
    )
    assert summary["closes_global_gate"] is False
    assert summary["global_denominator"] == {
        "expected_candidates": 2140,
        "in_scope_candidates": 426,
        "out_of_scope_candidates": 1714,
        "independently_reviewed": 0,
        "unresolved": 2140,
        "claim_contract_digest": "cf123369749c14ef140a9eb906b63f7183e93fd45a943a25087f5411a17399b6",
        "classification_digest": "594013cefc9f293cb6b224e6f869014e6015dd6f23a4ff708899afbb44c1f19c",
        "source_receipts_digest": "aad6fbb1305ccaddea2b5257cbfa5704ba1548a1855c97bcbaa144ed6d8ecb30",
        "candidate_set_digest": "ed4bb19838118841b5f5cc3a3d7348ee9763d11e8f4ad4f610c5e3853a1f0d31",
    }
    assert summary["observed_sink_count"] == 2
    for receipt in summary["sink_receipts"]:
        assert (receipt["mapped_exactly_once"], receipt["rendered"], receipt["explicitly_omitted"]) == (426, 426, 0)
        assert (receipt["unmapped"], receipt["multiply_mapped"], receipt["fallback_count"]) == (0, 0, 0)
        assert (receipt["safety_inputs_expected"], receipt["safety_inputs_bound"], receipt["safety_violations"]) == (7, 7, 0)
        assert (receipt["producer_verdict"], receipt["independent_verdict"]) == ("PASS", "BLOCK")


def test_reordered_observations_are_keyed_while_value_substitution_blocks(live) -> None:
    _, capability, _ = live
    observations = _observations(capability, "web.capabilities.default")
    observations["rendered_observations"].reverse()
    observations["safety_observations"].reverse()
    assert _evaluate(live, observations=observations)["sink_receipts"][1]["producer_verdict"] == "PASS"

    substituted = _observations(capability, "web.capabilities.default")
    substituted["rendered_observations"][0]["observed_value"], substituted["rendered_observations"][1]["observed_value"] = (
        substituted["rendered_observations"][1]["observed_value"],
        substituted["rendered_observations"][0]["observed_value"],
    )
    with pytest.raises(CapabilitySinkLineageError, match="observation_mismatch"):
        _evaluate(live, observations=substituted)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda rows: rows.pop(), "capability_sink_lineage_observation_count_mismatch"),
        (lambda rows: rows.append(copy.deepcopy(rows[0])), "capability_sink_lineage_observation_count_mismatch"),
        (lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])), "capability_sink_lineage_observation_duplicate_or_unknown"),
        (lambda rows: rows[0].__setitem__("record_identity", "SENSITIVE_CANARY"), "capability_sink_lineage_observation_duplicate_or_unknown"),
        (lambda rows: rows[0].__setitem__("observed_value", "SENSITIVE_CANARY"), "capability_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("rule_id", []), "capability_sink_lineage_observation_invalid"),
        (lambda rows: rows[0].__setitem__("observed_value", False), "capability_sink_lineage_observation_invalid"),
    ],
)
def test_missing_duplicate_unknown_value_and_type_fail_fixed_no_echo(live, mutation, code) -> None:
    _, capability, _ = live
    observations = _observations(capability, "web.capabilities.default")
    mutation(observations["rendered_observations"])
    with pytest.raises(CapabilitySinkLineageError) as failure:
        _evaluate(live, observations=observations)
    assert code in failure.value.codes
    assert "SENSITIVE_CANARY" not in str(failure.value)


def test_safety_missing_duplicate_value_type_and_exception_are_fail_closed(live) -> None:
    _, capability, _ = live
    for mutation, code in (
        (lambda rows: rows.pop(), "capability_sink_lineage_safety_observation_count_mismatch"),
        (lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])), "capability_sink_lineage_safety_observation_duplicate_or_unknown"),
        (lambda rows: rows[-1].__setitem__("observed_value", True), "capability_sink_lineage_safety_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("boundary_field", []), "capability_sink_lineage_safety_observation_invalid"),
    ):
        observations = _observations(capability, "web.capabilities.default")
        mutation(observations["safety_observations"])
        with pytest.raises(CapabilitySinkLineageError) as failure:
            _evaluate(live, observations=observations)
        assert code in failure.value.codes


def test_compiler_subject_missing_duplicate_digest_and_type_mutations_block(live) -> None:
    contract, capability, records = live
    variants = []
    variants.append(records[:-1])
    duplicate = copy.deepcopy(records)
    duplicate[1] = copy.deepcopy(duplicate[0])
    variants.append(duplicate)
    for field, value in (("value_digest", "0" * 64), ("grounding_digest", "0" * 64), ("review_state", []), ("source_blob_oid", "0" * 40)):
        mutated = copy.deepcopy(records)
        mutated[0][field] = value
        variants.append(mutated)
    for mutated in variants:
        with pytest.raises(CapabilitySinkLineageError, match="compiler_subject"):
            evaluate_capability_sink_lineage(
                contract=contract,
                claim_facet_records=mutated,
                capability=capability,
                source_raw=SOURCE_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={"web.capabilities.default": _observations(capability, "web.capabilities.default")},
            )

    class StringSubclass(str):
        pass

    subclassed = copy.deepcopy(records)
    subclassed[0]["facet_id"] = StringSubclass(subclassed[0]["facet_id"])
    with pytest.raises(CapabilitySinkLineageError, match="compiler_subject_invalid"):
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=subclassed,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )

    class ThrowingEquality:
        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    hostile_path = copy.deepcopy(records)
    hostile_path[0]["source_path"] = ThrowingEquality()
    with pytest.raises(CapabilitySinkLineageError, match="compiler_subject_invalid") as failure:
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=hostile_path,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)

    class EvilKey(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    hostile_key = copy.deepcopy(records)
    facet_id = hostile_key[0].pop("facet_id")
    hostile_key[0][EvilKey("facet_id")] = facet_id
    with pytest.raises(CapabilitySinkLineageError, match="compiler_subject_invalid") as failure:
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=hostile_key,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)

    hostile_subset = {EvilKey("web.capabilities.default"): _observations(capability, "web.capabilities.default")}
    with pytest.raises(CapabilitySinkLineageError, match="sink_subset_invalid") as failure:
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations=hostile_subset,
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)


def test_source_object_raw_blob_oid_and_contract_digest_are_exact(live) -> None:
    contract, capability, records = live
    changed = copy.deepcopy(capability)
    next(_entries(changed))[0]["current_scope"] = "SENSITIVE_CANARY"
    with pytest.raises(CapabilitySinkLineageError, match="source_object_mismatch"):
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            capability=changed,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    with pytest.raises(CapabilitySinkLineageError, match="source_blob_mismatch"):
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes() + b" ",
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    with pytest.raises(CapabilitySinkLineageError, match="source_blob_mismatch"):
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid="0" * 40,
            sink_observations={},
        )
    tampered = copy.deepcopy(contract)
    tampered["global_denominator"]["independently_reviewed"] = 426
    with pytest.raises(CapabilitySinkLineageError, match="contract_invalid"):
        evaluate_capability_sink_lineage(
            contract=tampered,
            claim_facet_records=records,
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )


def test_loader_and_schema_reject_nonportable_duplicate_and_gate_promotion(live) -> None:
    contract, capability, records = live
    with pytest.raises(CapabilitySinkLineageError, match="contract_invalid"):
        load_capability_sink_lineage_contract(b'{"id":"a","id":"b"}')
    with pytest.raises(CapabilitySinkLineageError, match="contract_invalid"):
        load_capability_sink_lineage_contract(b'{"x":1.5}')
    with pytest.raises(CapabilitySinkLineageError, match="structure_exceeds_bound"):
        load_capability_sink_lineage_contract(b'{"x":9007199254740992}')
    with pytest.raises(CapabilitySinkLineageError, match="compiler_subjects_invalid"):
        evaluate_capability_sink_lineage(
            contract=contract,
            claim_facet_records=tuple(records),
            capability=capability,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={},
        )
    tuple_observations = _observations(capability, "web.capabilities.default")
    tuple_observations["rendered_observations"] = tuple(tuple_observations["rendered_observations"])
    tuple_observations["safety_observations"] = tuple(tuple_observations["safety_observations"])
    assert _evaluate(live, observations=tuple_observations)["observed_sink_count"] == 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for path, value in (
        (("closes_global_gate",), True),
        (("global_denominator", "independently_reviewed"), 426),
        (("global_denominator", "unresolved"), 1714),
        (("sinks", 1, "locator"), "/capabilities?q=x"),
        (("sinks", 0, "expected_omitted"), 1),
        (("sinks", 1, "rendered_rules", 0, "fields", 0, "transform_id"), "identity-text"),
        (("source_scope", "candidate_rules", 3, "selector"), "domains"),
    ):
        mutated = copy.deepcopy(contract)
        cursor = mutated
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = value
        assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_unavailable_shape_never_promotes_global_or_sink_gate(live) -> None:
    contract, _, _ = live
    summary = unavailable_capability_sink_lineage(
        contract=contract,
        source_raw=SOURCE_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        reason_code="capability_sink_lineage_compiler_subjects_not_declared",
    )
    assert summary["closes_global_gate"] is False
    assert summary["global_denominator"]["independently_reviewed"] == 0
    assert summary["global_denominator"]["unresolved"] == 2140
    assert summary["observed_sink_count"] == 0
    assert all(row["producer_verdict"] == row["independent_verdict"] == "BLOCK" for row in summary["sink_receipts"])
    with pytest.raises(CapabilitySinkLineageError, match="unavailable_input_invalid"):
        unavailable_capability_sink_lineage(
            contract=contract,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            reason_code=[],
        )

    class ThrowingEquality:
        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    with pytest.raises(CapabilitySinkLineageError, match="unavailable_input_invalid") as failure:
        unavailable_capability_sink_lineage(
            contract=contract,
            source_raw=SOURCE_PATH.read_bytes(),
            source_blob_oid=ThrowingEquality(),
            reason_code="capability_sink_lineage_compiler_subjects_not_declared",
        )
    assert "SENSITIVE_CANARY" not in str(failure.value)
    with pytest.raises(CapabilitySinkLineageError, match="observation_envelope_invalid"):
        build_capability_sink_observation_receipt(
            contract=contract,
            sink_id=[],
            candidates=[],
            safety_inputs=[],
            observations={},
        )


def test_hostile_dictionary_key_subclasses_fail_fixed_no_echo(live) -> None:
    _, capability, _ = live

    class EvilKey(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            raise RuntimeError("SENSITIVE_CANARY")

    variants = []
    envelope = _observations(capability, "web.capabilities.default")
    rendered = envelope.pop("rendered_observations")
    envelope[EvilKey("rendered_observations")] = rendered
    variants.append(envelope)

    rendered_row = _observations(capability, "web.capabilities.default")
    rule_id = rendered_row["rendered_observations"][0].pop("rule_id")
    rendered_row["rendered_observations"][0][EvilKey("rule_id")] = rule_id
    variants.append(rendered_row)

    safety_row = _observations(capability, "web.capabilities.default")
    boundary_field = safety_row["safety_observations"][0].pop("boundary_field")
    safety_row["safety_observations"][0][EvilKey("boundary_field")] = boundary_field
    variants.append(safety_row)

    for observations in variants:
        with pytest.raises(CapabilitySinkLineageError) as failure:
            _evaluate(live, observations=observations)
        assert "SENSITIVE_CANARY" not in str(failure.value)
