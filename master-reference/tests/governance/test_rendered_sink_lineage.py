from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[3]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "master-reference"))

from governance.rendered_sink_lineage import (  # noqa: E402
    RenderedSinkLineageError,
    evaluate_rendered_sink_lineage,
    load_rendered_sink_lineage_contract,
)
from release.model import canonical_json, stable_id  # noqa: E402
from release.pdf_report import pdf_horizon_sink_observations  # noqa: E402


CONTRACT_PATH = ROOT / "master-reference" / "governance" / "rendered-sink-lineage-contract.json"
SCHEMA_PATH = ROOT / "master-reference" / "schema" / "rendered-sink-lineage.schema.json"
HORIZON_PATH = ROOT / "master-reference" / "content" / "open-horizon-register.json"
CLAIM_CONTRACT_PATH = ROOT / "master-reference" / "governance" / "consequential-claim-contract.json"


def _digest(value: object) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(value)).hexdigest()


def _candidate_records(contract: dict[str, object], horizon: dict[str, object]) -> list[dict[str, object]]:
    source = contract["source_scope"]
    assert isinstance(source, dict)
    claim_contract = json.loads(CLAIM_CONTRACT_PATH.read_text(encoding="utf-8"))
    horizon_contract = next(row for row in claim_contract["source_universe"] if row["path"] == source["path"])
    rule_contracts = {row["rule_id"]: row for row in horizon_contract["object_rules"]}
    records: list[dict[str, object]] = []
    for rule in source["candidate_rules"]:
        if rule["selector"] == "root":
            rows = [(horizon, "@root", "")]
        elif rule["selector"] == "cadence":
            rows = [(horizon["cadence"], "@root", "/cadence")]
        else:
            rows = [
                (item, item["id"], f"/{rule['selector']}/{index}")
                for index, item in enumerate(horizon[rule["selector"]])
            ]
        owner = rule_contracts[rule["rule_id"]]
        field_rules = {row["field"]: row for row in owner["fields"]}
        relationships = {row["field"]: row for row in horizon_contract["grounding"]["relationships"]}
        declared_owner_fields = set(horizon_contract["grounding"]["declared_owner_fields"])
        for item, identity, pointer in rows:
            grounding: list[dict[str, str]] = []
            for field_name, field_rule in sorted(field_rules.items()):
                if field_name not in item:
                    continue
                value = item[field_name]
                if field_rule["classification"] == "relationship_metadata":
                    relationship = relationships[field_name]
                    references = value if relationship["mode"] == "reference_array" else [value]
                    grounding.extend({"field": field_name, "reference": reference} for reference in references)
                elif field_name in declared_owner_fields:
                    grounding.append({"field": field_name, "reference": value})
            if not grounding:
                grounding.append(
                    {
                        "field": "@source_owner",
                        "reference": horizon_contract["grounding"]["fallback_owner_ref"],
                    }
                )
            grounding.sort(key=lambda row: (row["field"], row["reference"]))
            for field in rule["candidate_fields"]:
                identity_payload = {
                    "source_path": source["path"],
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": identity,
                    "facet_path": field,
                }
                facet_id = "urn:atlas:claim-facet:" + _digest(identity_payload)
                candidate = {
                    "facet_id": facet_id,
                    "source_path": source["path"],
                    "source_blob_oid": source["git_blob_oid"],
                    "source_pointer": f"{pointer}/{field}",
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": identity,
                    "facet_path": field,
                    "classification": "consequential_claim_candidate",
                    "claim_kind": field_rules[field]["claim_kind"],
                    "review_state": "pending_independent_review",
                    "grounding_digest": _digest(grounding),
                    "value_digest": _digest(item[field]),
                }
                records.append(
                    {
                        "id": stable_id("claim-facet-record", facet_id),
                        "entity_type": "consequential_claim_facet",
                        "evidence_state": "payload_omitted_value_fingerprint_index_only",
                        **candidate,
                    }
                )
    return sorted(records, key=lambda row: row["id"])


def _web_observations(horizon: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    rendered: list[dict[str, object]] = [
        {
            "rule_id": "horizon.root",
            "record_identity": "@root",
            "facet_path": "promise",
            "disposition": "rendered_identity",
            "slot_id": "web.gaps.horizon.heading.promise",
            "transform_id": "identity-text",
            "observed_value": horizon["promise"],
        }
    ]
    for watch in horizon["watch_families"]:
        for field, suffix, disposition, transform in (
            ("authority_scope", "authority-scope", "rendered_identity", "identity-text"),
            ("review_cadence", "review-cadence", "rendered_labeled", "labeled-text"),
            ("engine_ingestion", "engine-ingestion", "rendered_labeled", "labeled-text"),
        ):
            rendered.append(
                {
                    "rule_id": "horizon.watch_family",
                    "record_identity": watch["id"],
                    "facet_path": field,
                    "disposition": disposition,
                    "slot_id": f"web.gaps.horizon.watch.{watch['id']}.{suffix}",
                    "transform_id": transform,
                    "observed_value": watch[field],
                }
            )
    for signal in horizon["signals"]:
        for field, suffix, disposition, transform in (
            ("maturity", "maturity", "rendered_identity", "identity-text"),
            ("disposition", "disposition", "rendered_derived", "state-mark-label"),
            ("business_relevance", "business-relevance", "rendered_labeled", "labeled-text"),
            ("current_coverage", "current-coverage", "rendered_identity", "identity-text"),
            ("uncertainty", "uncertainty", "rendered_labeled", "labeled-text"),
            ("next_review_rule", "next-review-rule", "rendered_labeled", "labeled-text"),
            ("promotion_criteria", "promotion-criteria", "rendered_ordered_array", "ordered-list-items"),
        ):
            rendered.append(
                {
                    "rule_id": "horizon.signal",
                    "record_identity": signal["id"],
                    "facet_path": field,
                    "disposition": disposition,
                    "slot_id": f"web.gaps.horizon.signal.{signal['id']}.{suffix}",
                    "transform_id": transform,
                    "observed_value": signal[field],
                }
            )
    safety: list[dict[str, object]] = [
        {
            "rule_id": "horizon.root",
            "record_identity": "@root",
            "boundary_field": "content_role",
            "observed_value": horizon["content_role"],
            "slot_id": "web.gaps.horizon.safety.content-role",
            "transform_id": "validated-uniform-boundary-summary",
        },
        {
            "rule_id": "horizon.root",
            "record_identity": "@root",
            "boundary_field": "support_claim",
            "observed_value": horizon["support_claim"],
            "slot_id": "web.gaps.horizon.safety.support-claim",
            "transform_id": "validated-uniform-boundary-summary",
        },
        {
            "rule_id": "horizon.root",
            "record_identity": "@root",
            "boundary_field": "mutates_assessment_truth",
            "observed_value": horizon["mutates_assessment_truth"],
            "slot_id": "web.gaps.horizon.safety.truth-mutation",
            "transform_id": "validated-uniform-boundary-summary",
        },
    ]
    safety.extend(
        {
            "rule_id": "horizon.watch_family",
            "record_identity": watch["id"],
            "boundary_field": "content_role",
            "observed_value": watch["content_role"],
            "slot_id": "web.gaps.horizon.safety.content-role",
            "transform_id": "validated-uniform-boundary-summary",
        }
        for watch in horizon["watch_families"]
    )
    for signal in horizon["signals"]:
        for field, slot in (("content_role", "content-role"), ("support_claim", "support-claim")):
            safety.append(
                {
                    "rule_id": "horizon.signal",
                    "record_identity": signal["id"],
                    "boundary_field": field,
                    "observed_value": signal[field],
                    "slot_id": f"web.gaps.horizon.safety.{slot}",
                    "transform_id": "validated-uniform-boundary-summary",
                }
            )
    return {"rendered_observations": rendered, "safety_observations": safety}


@pytest.fixture()
def live() -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    contract = load_rendered_sink_lineage_contract(CONTRACT_PATH.read_bytes())
    horizon = json.loads(HORIZON_PATH.read_text(encoding="utf-8"))
    return contract, horizon, _candidate_records(contract, horizon)


def test_tracked_contract_schema_and_exact_denominator(live) -> None:
    contract, horizon, records = live
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(contract)) == []
    assert _digest(contract) == "a10b406151c5bd4dc4769f34dac34b570584ebec6c43d6402f8cb2a786953ebf"
    assert len(records) == 315
    assert len({row["facet_id"] for row in records}) == 315
    assert contract["global_denominator"] == {
        "kind": "bounded_curated_content_claim_denominator",
        "expected_candidates": 2138,
        "in_scope_candidates": 315,
        "out_of_scope_candidates": 1823,
        "independently_reviewed": 0,
        "unresolved": 2138,
        "claim_contract_digest": "bed99adaf4dea5ec8f6293993ecb981c1258354563ddf00cf35f2e837eef75de",
        "classification_digest": "1319f15e0439eb85277982ab8d36086770156161e11328c82a17209ef22cf6f1",
        "source_receipts_digest": "dbf82e7d86db36468af02bcc475a6d7b8da54d794560e0c66005a6978317f100",
        "candidate_set_digest": "0500bab20bb6e4e1220d9a1d83ab566206f539cfbdc30077b2e50a16755f3f6b",
    }
    assert len(horizon["signals"]) == 16


def test_both_sinks_map_315_once_but_global_gate_stays_false(live) -> None:
    contract, horizon, records = live
    summary = evaluate_rendered_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        horizon=horizon,
        source_raw=HORIZON_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={
            "pdf.open-horizon": pdf_horizon_sink_observations(horizon),
            "web.gaps.open-horizon": _web_observations(horizon),
        },
    )
    assert summary["closes_global_gate"] is False
    assert summary["observed_sink_count"] == 2
    assert summary["global_denominator"]["independently_reviewed"] == 0
    assert summary["global_denominator"]["unresolved"] == 2138
    for receipt in summary["sink_receipts"]:
        assert (receipt["mapped_exactly_once"], receipt["rendered"], receipt["explicitly_omitted"]) == (315, 167, 148)
        assert (receipt["unmapped"], receipt["multiply_mapped"], receipt["fallback_count"]) == (0, 0, 0)
        assert (receipt["safety_inputs_bound"], receipt["safety_violations"]) == (53, 0)
        assert receipt["independent_verdict"] == "BLOCK"


def test_sink_subset_marks_other_not_observed(live) -> None:
    contract, horizon, records = live
    summary = evaluate_rendered_sink_lineage(
        contract=contract,
        claim_facet_records=records,
        horizon=horizon,
        source_raw=HORIZON_PATH.read_bytes(),
        source_blob_oid=contract["source_scope"]["git_blob_oid"],
        sink_observations={"pdf.open-horizon": pdf_horizon_sink_observations(horizon)},
    )
    by_sink = {row["sink_id"]: row for row in summary["sink_receipts"]}
    assert by_sink["pdf.open-horizon"]["producer_verdict"] == "PASS"
    assert by_sink["web.gaps.open-horizon"]["state"] == "not_observed"
    assert by_sink["web.gaps.open-horizon"]["unmapped"] == 315


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda rows: rows.pop(), "rendered_sink_lineage_observation_count_mismatch"),
        (lambda rows: rows.append(copy.deepcopy(rows[0])), "rendered_sink_lineage_observation_count_mismatch"),
        (
            lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
            "rendered_sink_lineage_observation_duplicate_or_unknown",
        ),
        (
            lambda rows: rows[0].__setitem__("observed_value", "SENSITIVE_CANARY"),
            "rendered_sink_lineage_observation_mismatch",
        ),
        (lambda rows: rows[0].__setitem__("slot_id", "SENSITIVE_CANARY"), "rendered_sink_lineage_observation_mismatch"),
        (lambda rows: rows[0].__setitem__("rule_id", []), "rendered_sink_lineage_observation_invalid"),
        (lambda rows: rows[0].__setitem__("record_identity", {}), "rendered_sink_lineage_observation_invalid"),
        (
            lambda rows: rows[0].__setitem__("observed_value", "x" * 16_385),
            "rendered_sink_lineage_observation_invalid",
        ),
    ],
)
def test_hostile_rendered_observations_fail_fixed_no_echo(live, mutation, code) -> None:
    contract, horizon, records = live
    observations = _web_observations(horizon)
    mutation(observations["rendered_observations"])
    with pytest.raises(RenderedSinkLineageError) as failure:
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=horizon,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={"web.gaps.open-horizon": observations},
        )
    assert code in failure.value.codes
    assert "SENSITIVE_CANARY" not in str(failure.value)


def test_ordered_array_reorder_and_safety_mutation_block(live) -> None:
    contract, horizon, records = live
    observations = _web_observations(horizon)
    criteria = next(row for row in observations["rendered_observations"] if row["facet_path"] == "promotion_criteria")
    criteria["observed_value"] = list(reversed(criteria["observed_value"]))
    with pytest.raises(RenderedSinkLineageError, match="observation_mismatch"):
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=horizon,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={"web.gaps.open-horizon": observations},
        )
    unsafe_observations = _web_observations(horizon)
    unsafe_observations["safety_observations"][-1]["observed_value"] = "current"
    with pytest.raises(RenderedSinkLineageError, match="safety_observation_mismatch"):
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=horizon,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={"web.gaps.open-horizon": unsafe_observations},
        )
    malformed_safety = _web_observations(horizon)
    malformed_safety["safety_observations"][0]["boundary_field"] = []
    with pytest.raises(RenderedSinkLineageError, match="safety_observation_invalid"):
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=horizon,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={"web.gaps.open-horizon": malformed_safety},
        )


def test_stale_compiler_subject_missing_unknown_and_blob_block(live) -> None:
    contract, horizon, records = live
    for field, value in (
        ("value_digest", "0" * 64),
        ("grounding_digest", "0" * 64),
        ("claim_kind", "hostile_remap"),
    ):
        stale = copy.deepcopy(records)
        stale[0][field] = value
        with pytest.raises(RenderedSinkLineageError, match="compiler_subject_mismatch"):
            evaluate_rendered_sink_lineage(
                contract=contract,
                claim_facet_records=stale,
                horizon=horizon,
                source_raw=HORIZON_PATH.read_bytes(),
                source_blob_oid=contract["source_scope"]["git_blob_oid"],
                sink_observations={"web.gaps.open-horizon": _web_observations(horizon)},
            )
    missing_unknown = copy.deepcopy(horizon)
    missing_unknown["signals"] = [row for row in missing_unknown["signals"] if row["id"] != "horizon.unknown"]
    with pytest.raises(RenderedSinkLineageError, match="source_object_mismatch"):
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=missing_unknown,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid=contract["source_scope"]["git_blob_oid"],
            sink_observations={"web.gaps.open-horizon": _web_observations(missing_unknown)},
        )
    with pytest.raises(RenderedSinkLineageError, match="source_blob_mismatch"):
        evaluate_rendered_sink_lineage(
            contract=contract,
            claim_facet_records=records,
            horizon=horizon,
            source_raw=HORIZON_PATH.read_bytes(),
            source_blob_oid="0" * 40,
            sink_observations={"web.gaps.open-horizon": _web_observations(horizon)},
        )


def test_contract_declares_exact_mapping_and_schema_rejects_promotion(live) -> None:
    contract, _horizon, _records = live
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    promoted = copy.deepcopy(contract)
    promoted["closes_global_gate"] = True
    assert list(Draft202012Validator(schema).iter_errors(promoted))
    remapped = copy.deepcopy(contract)
    remapped["sinks"][0]["rendered_rules"][0]["fields"][0]["disposition"] = "explicitly_omitted"
    assert list(Draft202012Validator(schema).iter_errors(remapped))
