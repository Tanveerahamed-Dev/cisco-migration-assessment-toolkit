"""Fail-closed lineage accounting for the bounded Atlas Core sink slice.

The source-wide slice accounts for every Core candidate at two deliberately
narrow outcome sinks.  It supplies no semantic review, evidence promotion,
publication authority, or global rendered-claim closure.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "rendered-sink-lineage-core/1.0.0"
CONTRACT_SCHEMA_VERSION = "rendered-sink-lineage-core-contract/1.0.0"
CONTRACT_ID = "atlas.rendered-sink-lineage.core.v1"
EXPECTED_CONTRACT_DIGEST = "a9968d54eb1b52fdfd1a42fd6c800dbd9d979d3ad3ad9ece09c57d84ef74e3b0"
SOURCE_PATH = "master-reference/content/atlas-core.json"
GLOBAL_CANDIDATES = 2_136
IN_SCOPE_CANDIDATES = 155
OUT_OF_SCOPE_CANDIDATES = 1_981
EXPECTED_SAFETY_INPUTS = 0
EXPECTED_SEMANTIC_RECORDS = 135
EXPECTED_GROUNDING_FALLBACK_CANDIDATES = 62
CLAIM_CONTRACT_DIGEST = "4ebd7da5caa6aab63f3ba122d480fef638f46b866c665845087433074f436c8d"
CLASSIFICATION_DIGEST = "b5bc4783b8bd6461fc4669b39a555ae061081a278e36712cdb6f70a5e673d1df"
SOURCE_RECEIPTS_DIGEST = "863f93c7bc0599b1cfe7e5b42eb5b10c8087a704af9de194be18d9bf28008689"
CANDIDATE_SET_DIGEST = "a768b5a6c9a94390ada8e9c24627c8908f6a7b51e3f06d59b79ac8f1a5ffdd43"
MAX_CONTRACT_BYTES = 512 * 1024
MAX_STRING_LENGTH = 16_384
MAX_VALUES = 100_000
MAX_DEPTH = 64
MAX_ARRAY_ITEMS = 2_048
MAX_OBJECT_ITEMS = 512
MAX_PORTABLE_INTEGER = 9_007_199_254_740_991
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FACET_ID = re.compile(r"urn:atlas:claim-facet:[0-9a-f]{64}")
_DISPOSITIONS = frozenset({"rendered_identity", "rendered_labeled"})
_CANDIDATE_KEYS = frozenset(
    {
        "facet_id",
        "source_path",
        "source_blob_oid",
        "source_pointer",
        "rule_id",
        "record_kind",
        "record_identity",
        "facet_path",
        "classification",
        "claim_kind",
        "review_state",
        "grounding_digest",
        "value_digest",
    }
)
_FACET_RECORD_KEYS = _CANDIDATE_KEYS | frozenset({"id", "entity_type", "evidence_state"})
_RENDERED_OBSERVATION_KEYS = frozenset(
    {"rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id", "observed_value"}
)
_UNAVAILABLE_REASONS = frozenset(
    {
        "core_sink_lineage_compiler_subjects_not_declared",
        "core_sink_lineage_pdf_not_observed",
        "core_sink_lineage_external_pdf_unverified",
    }
)
_RULE_IDS = (
    "core.root",
    "core.truth_contract",
    "core.controlled_state",
    "core.owner",
    "core.current_baseline",
    "core.outcome",
    "core.maturity_model",
    "core.current_maturity",
    "core.non_goal",
    "core.lifecycle_stage",
    "core.digital_thread",
    "core.digital_thread_stage",
    "core.system_architecture",
    "core.system_plane",
    "core.system_flow",
    "core.traffic_model",
    "core.traffic_plane",
    "core.domain",
)


class CoreSinkLineageError(ValueError):
    """The Core lineage slice could not be proven."""

    def __init__(self, codes: Sequence[str]):
        self.codes = tuple(sorted(set(codes)))
        super().__init__(", ".join(self.codes))


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_number(_value: str) -> None:
    raise ValueError


def _canonical(value: Any) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise CoreSinkLineageError(["core_sink_lineage_canonicalization_failed"]) from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_record_id(facet_id: str) -> str:
    return f"urn:atlas:claim-facet-record:{hashlib.sha256(facet_id.encode('utf-8')).hexdigest()[:24]}"


def _git_blob_oid(raw: bytes, expected_oid: str) -> str:
    material = f"blob {len(raw)}\0".encode("ascii") + raw
    if len(expected_oid) == 40:
        return hashlib.sha1(material, usedforsecurity=False).hexdigest()
    if len(expected_oid) == 64:
        return hashlib.sha256(material).hexdigest()
    return ""


def _portable_string(value: str) -> bool:
    return len(value) <= MAX_STRING_LENGTH and all(
        not (ord(character) <= 0x1F or 0x7F <= ord(character) <= 0x9F or 0xD800 <= ord(character) <= 0xDFFF)
        for character in value
    )


def _has_exact_keys(value: Any, expected: frozenset[str] | set[str]) -> bool:
    """Compare keys only after proving every key is an exact built-in string."""

    if type(value) is not dict or len(value) != len(expected):
        return False
    keys = tuple(value)
    return all(type(key) is str for key in keys) and frozenset(keys) == frozenset(expected)


def _has_exact_key_subset(value: Any, expected: set[str]) -> bool:
    if type(value) is not dict:
        return False
    keys = tuple(value)
    return all(type(key) is str for key in keys) and frozenset(keys) <= frozenset(expected)


def _validate_json_tree(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    count = 0
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > MAX_VALUES or depth > MAX_DEPTH:
            raise CoreSinkLineageError(["core_sink_lineage_structure_exceeds_bound"])
        if type(current) is dict:
            if len(current) > MAX_OBJECT_ITEMS or any(
                type(key) is not str or not _portable_string(key) for key in current
            ):
                raise CoreSinkLineageError(["core_sink_lineage_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            if len(current) > MAX_ARRAY_ITEMS:
                raise CoreSinkLineageError(["core_sink_lineage_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current)
        elif type(current) is str:
            if not _portable_string(current):
                raise CoreSinkLineageError(["core_sink_lineage_structure_exceeds_bound"])
        elif current is None or type(current) is bool:
            continue
        elif type(current) is int:
            if not -MAX_PORTABLE_INTEGER <= current <= MAX_PORTABLE_INTEGER:
                raise CoreSinkLineageError(["core_sink_lineage_structure_exceeds_bound"])
        else:
            raise CoreSinkLineageError(["core_sink_lineage_nonportable_json"])


def _load_object(raw: bytes, code: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_CONTRACT_BYTES:
        raise CoreSinkLineageError([code])
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise CoreSinkLineageError([code]) from None
    if type(value) is not dict:
        raise CoreSinkLineageError([code])
    _validate_json_tree(value)
    return value


def load_core_sink_lineage_contract(raw: bytes) -> dict[str, Any]:
    """Decode the bounded Core contract without echoing hostile values."""

    return _load_object(raw, "core_sink_lineage_contract_invalid")


def _validate_contract(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if type(contract) is not dict:
        raise CoreSinkLineageError(["core_sink_lineage_contract_invalid"])
    _validate_json_tree(contract)
    try:
        if (
            _digest(contract) != EXPECTED_CONTRACT_DIGEST
            or contract["schema_version"] != CONTRACT_SCHEMA_VERSION
            or contract["id"] != CONTRACT_ID
            or contract["state"] != "declared_incomplete"
            or contract["closes_global_gate"] is not False
            or contract["global_denominator"]
            != {
                "kind": "bounded_curated_content_claim_denominator",
                "expected_candidates": GLOBAL_CANDIDATES,
                "in_scope_candidates": IN_SCOPE_CANDIDATES,
                "out_of_scope_candidates": OUT_OF_SCOPE_CANDIDATES,
                "independently_reviewed": 0,
                "unresolved": GLOBAL_CANDIDATES,
                "claim_contract_digest": CLAIM_CONTRACT_DIGEST,
                "classification_digest": CLASSIFICATION_DIGEST,
                "source_receipts_digest": SOURCE_RECEIPTS_DIGEST,
                "candidate_set_digest": CANDIDATE_SET_DIGEST,
            }
        ):
            raise KeyError
        source = contract["source_scope"]
        if (
            source["path"] != SOURCE_PATH
            or source["git_blob_oid"] != "27b7c166a78894d957bd3f35b5f64170dd11afb4"
            or source["sha256"] != "e6c53929bab88f27eb31f48afd4fe60a8dab80d04d06dd03759347924f110a26"
            or source["bytes"] != 40_781
            or source["expected_records"] != EXPECTED_SEMANTIC_RECORDS
            or source["expected_candidates"] != IN_SCOPE_CANDIDATES
            or source["expected_safety_inputs"] != EXPECTED_SAFETY_INPUTS
            or source["expected_grounding_fallback_candidates"] != EXPECTED_GROUNDING_FALLBACK_CANDIDATES
            or source["candidate_digest"]
            != "79253dc74d3c25a49179f38b57ea25c7ff603195eb03ee97c5eb38793d78d894"
            or source["facet_id_set_digest"]
            != "7bd48e7f5f587aa500136f7235e9c924ea56ef6d3e499258bfca6db257231119"
            or source["safety_rules"] != []
        ):
            raise KeyError
        rules = source["candidate_rules"]
        if (
            type(rules) is not list
            or len(rules) != len(_RULE_IDS)
            or tuple(rule["rule_id"] for rule in rules) != _RULE_IDS
            or sum(rule["expected_records"] for rule in rules) != EXPECTED_SEMANTIC_RECORDS
            or sum(rule["expected_records"] * len(rule["candidate_fields"]) for rule in rules)
            != IN_SCOPE_CANDIDATES
        ):
            raise KeyError
        universe = contract["sink_universe"]
        if universe["complete"] is not False or universe["declared_count"] != 2:
            raise KeyError
        sinks = contract["sinks"]
        sink_by_id = {sink["sink_id"]: sink for sink in sinks}
        if len(sinks) != 2 or set(sink_by_id) != {
            "pdf.product-purpose-and-outcomes",
            "web.product.core-outcomes",
        }:
            raise KeyError
        for sink in sinks:
            if (
                sink["expected_rendered"] != 9
                or sink["expected_omitted"] != 146
                or sum(row["expected_subjects"] for row in sink["rendered_rules"]) != 9
                or sum(row["expected_subjects"] for row in sink["omission_rules"]) != 146
                or sink["safety_mappings"] != []
            ):
                raise KeyError
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        raise CoreSinkLineageError(["core_sink_lineage_contract_invalid"]) from None
    return sink_by_id


def _records_for_selector(
    document: Mapping[str, Any], selector: Sequence[str]
) -> list[tuple[dict[str, Any], str, tuple[dict[str, Any], ...]]]:
    rows: list[tuple[Any, str, tuple[dict[str, Any], ...]]] = [(document, "", ())]
    for token in selector:
        if type(token) is not str or not token:
            raise CoreSinkLineageError(["core_sink_lineage_contract_invalid"])
        is_collection = token.endswith("[]")
        field = token[:-2] if is_collection else token
        next_rows: list[tuple[Any, str, tuple[dict[str, Any], ...]]] = []
        for current, pointer, ancestors in rows:
            if type(current) is not dict or field not in current:
                raise CoreSinkLineageError(["core_sink_lineage_source_shape_invalid"])
            selected = current[field]
            field_pointer = f"{pointer}/{field}"
            if is_collection:
                if type(selected) is not list:
                    raise CoreSinkLineageError(["core_sink_lineage_source_shape_invalid"])
                next_rows.extend(
                    (item, f"{field_pointer}/{index}", (*ancestors, current))
                    for index, item in enumerate(selected)
                )
            else:
                next_rows.append((selected, field_pointer, (*ancestors, current)))
        rows = next_rows
    if any(type(record) is not dict for record, _pointer, _ancestors in rows):
        raise CoreSinkLineageError(["core_sink_lineage_source_shape_invalid"])
    return [(record, pointer, ancestors) for record, pointer, ancestors in rows if type(record) is dict]


def _record_identity(record: Mapping[str, Any], identity: Mapping[str, Any]) -> str:
    kind = identity["kind"]
    if kind == "root":
        return "@root"
    if kind == "field":
        value = record.get(identity["field"])
        if type(value) is not str or not value.strip() or not _portable_string(value):
            raise CoreSinkLineageError(["core_sink_lineage_source_identity_invalid"])
        return value
    if kind == "composite":
        values = [record.get(field) for field in identity["fields"]]
        if any(type(value) is not str or not value.strip() or not _portable_string(value) for value in values):
            raise CoreSinkLineageError(["core_sink_lineage_source_identity_invalid"])
        return _digest(values)
    raise CoreSinkLineageError(["core_sink_lineage_contract_invalid"])


def _value_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return type(value) is str and bool(value.strip()) and _portable_string(value)
    if expected == "integer":
        return type(value) is int and -MAX_PORTABLE_INTEGER <= value <= MAX_PORTABLE_INTEGER
    if expected == "string_array":
        return (
            type(value) is list
            and bool(value)
            and len(value) <= MAX_ARRAY_ITEMS
            and all(type(item) is str and bool(item.strip()) and _portable_string(item) for item in value)
        )
    if expected == "baseline_value":
        if type(value) is str:
            return bool(value.strip()) and _portable_string(value)
        if type(value) is list:
            return bool(value) and all(
                type(item) is str and bool(item.strip()) and _portable_string(item) for item in value
            )
        if type(value) is dict:
            return bool(value) and all(
                type(key) is str
                and bool(key.strip())
                and _portable_string(key)
                and (
                    (type(item) is str and bool(item.strip()) and _portable_string(item))
                    or (type(item) is int and -MAX_PORTABLE_INTEGER <= item <= MAX_PORTABLE_INTEGER)
                    or (
                        type(item) is list
                        and bool(item)
                        and all(
                            type(member) is str and bool(member.strip()) and _portable_string(member)
                            for member in item
                        )
                    )
                )
                for key, item in value.items()
            )
    return False


def _grounding(record: Mapping[str, Any], grounding_contract: Mapping[str, Any]) -> tuple[list[dict[str, str]], bool]:
    rows: list[dict[str, str]] = []
    relationships = sorted(grounding_contract["relationships"], key=lambda item: item["field"])
    for relationship in relationships:
        field = relationship["field"]
        if field not in record:
            continue
        value = record[field]
        if relationship["mode"] == "reference_array":
            if (
                type(value) is not list
                or len(value) > MAX_ARRAY_ITEMS
                or any(type(item) is not str or not item.strip() or not _portable_string(item) for item in value)
                or len(value) != len(set(value))
            ):
                raise CoreSinkLineageError(["core_sink_lineage_source_grounding_invalid"])
            references = value
        elif value is None and relationship["mode"] == "relation_scalar":
            references = []
        elif type(value) is str and value.strip() and _portable_string(value):
            references = [value]
        else:
            raise CoreSinkLineageError(["core_sink_lineage_source_grounding_invalid"])
        rows.extend({"field": field, "reference": reference} for reference in references)
    used_fallback = not rows
    if used_fallback:
        rows.append({"field": "@source_owner", "reference": grounding_contract["fallback_owner_ref"]})
    rows.sort(key=lambda row: (row["field"], row["reference"]))
    return rows, used_fallback


def _source_candidates(
    contract: Mapping[str, Any], core: Mapping[str, Any], source_blob_oid: str
) -> tuple[list[dict[str, Any]], int]:
    source = contract["source_scope"]
    candidates: list[dict[str, Any]] = []
    semantic_records = 0
    fallback_candidates = 0
    for rule in source["candidate_rules"]:
        rows = _records_for_selector(core, rule["selector"])
        if len(rows) != rule["expected_records"]:
            raise CoreSinkLineageError(["core_sink_lineage_source_record_count_mismatch"])
        semantic_records += len(rows)
        identities: set[str] = set()
        for record, pointer, _ancestors in rows:
            identity = _record_identity(record, rule["identity"])
            if identity in identities:
                raise CoreSinkLineageError(["core_sink_lineage_source_identity_duplicate"])
            identities.add(identity)
            grounding, used_fallback = _grounding(record, source["grounding"])
            grounding_digest = _digest(grounding)
            for field in rule["candidate_fields"]:
                facet_path = field["facet_path"]
                if facet_path not in record or not _value_matches(record[facet_path], field["value_type"]):
                    raise CoreSinkLineageError(["core_sink_lineage_source_candidate_invalid"])
                facet_identity = {
                    "source_path": SOURCE_PATH,
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": identity,
                    "facet_path": facet_path,
                }
                candidates.append(
                    {
                        "facet_id": "urn:atlas:claim-facet:" + _digest(facet_identity),
                        "source_path": SOURCE_PATH,
                        "source_blob_oid": source_blob_oid,
                        "source_pointer": f"{pointer}/{facet_path}",
                        "rule_id": rule["rule_id"],
                        "record_kind": rule["record_kind"],
                        "record_identity": identity,
                        "facet_path": facet_path,
                        "classification": "consequential_claim_candidate",
                        "claim_kind": field["claim_kind"],
                        "review_state": "pending_independent_review",
                        "grounding_digest": grounding_digest,
                        "value_digest": _digest(record[facet_path]),
                    }
                )
                fallback_candidates += int(used_fallback)
    if semantic_records != EXPECTED_SEMANTIC_RECORDS:
        raise CoreSinkLineageError(["core_sink_lineage_source_record_count_mismatch"])
    if len(candidates) != IN_SCOPE_CANDIDATES:
        raise CoreSinkLineageError(["core_sink_lineage_source_candidate_count_mismatch"])
    if fallback_candidates != EXPECTED_GROUNDING_FALLBACK_CANDIDATES:
        raise CoreSinkLineageError(["core_sink_lineage_source_grounding_fallback_count_mismatch"])
    candidates.sort(key=lambda row: row["facet_id"])
    if _digest(candidates) != source["candidate_digest"]:
        raise CoreSinkLineageError(["core_sink_lineage_source_candidate_digest_mismatch"])
    facet_ids = [row["facet_id"] for row in candidates]
    if len(facet_ids) != len(set(facet_ids)) or _digest(facet_ids) != source["facet_id_set_digest"]:
        raise CoreSinkLineageError(["core_sink_lineage_source_facet_set_mismatch"])
    return candidates, fallback_candidates


def _compare_compiler_facets(
    candidates: Sequence[Mapping[str, Any]], claim_facet_records: Sequence[Mapping[str, Any]], source_blob_oid: str
) -> None:
    if type(claim_facet_records) is not list or len(claim_facet_records) > 10_000:
        raise CoreSinkLineageError(["core_sink_lineage_compiler_subjects_invalid"])
    actual: list[Mapping[str, Any]] = []
    for row in claim_facet_records:
        if not _has_exact_keys(row, _FACET_RECORD_KEYS):
            raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_invalid"])
        if any(type(row[key]) is not str or not _portable_string(row[key]) for key in _FACET_RECORD_KEYS):
            raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_invalid"])
        if row["source_path"] == SOURCE_PATH:
            actual.append(row)
    if len(actual) != IN_SCOPE_CANDIDATES:
        raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_count_mismatch"])
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in actual:
        facet_id = row["facet_id"]
        if facet_id in by_id:
            raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_invalid"])
        by_id[facet_id] = row
    for expected in candidates:
        row = by_id.get(expected["facet_id"])
        if row is None or any(row[field] != value for field, value in expected.items()):
            raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_mismatch"])
        if (
            row["id"] != _stable_record_id(expected["facet_id"])
            or row["entity_type"] != "consequential_claim_facet"
            or row["evidence_state"] != "payload_omitted_value_fingerprint_index_only"
            or row["review_state"] != "pending_independent_review"
            or row["classification"] != "consequential_claim_candidate"
            or row["source_blob_oid"] != source_blob_oid
            or _FACET_ID.fullmatch(row["facet_id"]) is None
            or _DIGEST.fullmatch(row["grounding_digest"]) is None
            or _DIGEST.fullmatch(row["value_digest"]) is None
        ):
            raise CoreSinkLineageError(["core_sink_lineage_compiler_subject_mismatch"])


def _expanded_sink_mapping(
    sink: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]]:
    rendered_specs: dict[tuple[str, str], Mapping[str, Any]] = {}
    rendered_counts: dict[str, int] = {}
    for rule in sink["rendered_rules"]:
        rendered_counts[rule["rule_id"]] = 0
        for field in rule["fields"]:
            key = (rule["rule_id"], field["facet_path"])
            if key in rendered_specs:
                raise CoreSinkLineageError(["core_sink_lineage_mapping_duplicate"])
            rendered_specs[key] = field
    omitted_specs: dict[tuple[str, str], Mapping[str, Any]] = {}
    omitted_counts: dict[str, int] = {}
    for rule in sink["omission_rules"]:
        omitted_counts[rule["rule_id"]] = 0
        for facet_path in rule["facet_paths"]:
            key = (rule["rule_id"], facet_path)
            if key in omitted_specs:
                raise CoreSinkLineageError(["core_sink_lineage_mapping_duplicate"])
            omitted_specs[key] = rule
    if set(rendered_specs) & set(omitted_specs):
        raise CoreSinkLineageError(["core_sink_lineage_mapping_overlap"])
    mapping: dict[tuple[str, str, str], dict[str, Any]] = {}
    omissions: list[dict[str, Any]] = []
    for candidate in candidates:
        facet_key = (candidate["rule_id"], candidate["facet_path"])
        rendered = rendered_specs.get(facet_key)
        omitted = omitted_specs.get(facet_key)
        if (rendered is None) == (omitted is None):
            raise CoreSinkLineageError(["core_sink_lineage_mapping_incomplete"])
        if rendered is not None:
            key = (candidate["rule_id"], candidate["record_identity"], candidate["facet_path"])
            mapping[key] = {
                "facet_id": candidate["facet_id"],
                "source_pointer": candidate["source_pointer"],
                "value_digest": candidate["value_digest"],
                "disposition": rendered["disposition"],
                "slot_id": rendered["slot_template"].replace("{record_identity}", candidate["record_identity"]),
                "transform_id": rendered["transform_id"],
            }
            rendered_counts[candidate["rule_id"]] += 1
        else:
            omissions.append(
                {
                    "facet_id": candidate["facet_id"],
                    "source_pointer": candidate["source_pointer"],
                    "value_digest": candidate["value_digest"],
                    "disposition": "explicitly_omitted",
                    "omission_reason_code": omitted["reason_code"],
                }
            )
            omitted_counts[candidate["rule_id"]] += 1
    if (
        len(mapping) != sink["expected_rendered"]
        or len(omissions) != sink["expected_omitted"]
        or any(rendered_counts[rule["rule_id"]] != rule["expected_subjects"] for rule in sink["rendered_rules"])
        or any(omitted_counts[rule["rule_id"]] != rule["expected_subjects"] for rule in sink["omission_rules"])
    ):
        raise CoreSinkLineageError(["core_sink_lineage_mapping_count_mismatch"])
    return mapping, sorted(omissions, key=lambda row: row["facet_id"])


def _validate_receipt_candidates(
    contract: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    """Prove the exact frozen candidate set before any receipt mapping access."""

    if type(candidates) is not list or len(candidates) != IN_SCOPE_CANDIDATES:
        raise CoreSinkLineageError(["core_sink_lineage_receipt_input_invalid"])
    validated: list[dict[str, str]] = []
    for row in candidates:
        if not _has_exact_keys(row, _CANDIDATE_KEYS):
            raise CoreSinkLineageError(["core_sink_lineage_receipt_input_invalid"])
        if any(
            type(row[field]) is not str
            or not row[field]
            or not _portable_string(row[field])
            for field in _CANDIDATE_KEYS
        ):
            raise CoreSinkLineageError(["core_sink_lineage_receipt_input_invalid"])
        validated.append(row)

    source = contract["source_scope"]
    facet_ids = [row["facet_id"] for row in validated]
    if (
        any(
            row["source_path"] != SOURCE_PATH
            or row["source_blob_oid"] != source["git_blob_oid"]
            or row["source_pointer"][0] != "/"
            or row["rule_id"] not in _RULE_IDS
            or row["classification"] != "consequential_claim_candidate"
            or row["review_state"] != "pending_independent_review"
            or _FACET_ID.fullmatch(row["facet_id"]) is None
            or _DIGEST.fullmatch(row["grounding_digest"]) is None
            or _DIGEST.fullmatch(row["value_digest"]) is None
            for row in validated
        )
        or len(facet_ids) != len(set(facet_ids))
        or _digest(validated) != source["candidate_digest"]
        or _digest(facet_ids) != source["facet_id_set_digest"]
    ):
        raise CoreSinkLineageError(["core_sink_lineage_receipt_input_invalid"])
    return validated


def _build_core_sink_observation_receipt(
    *,
    contract: Mapping[str, Any],
    sink_id: str,
    candidates: Sequence[Mapping[str, Any]],
    safety_inputs: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Implement the receipt after its public boundary has normalized inputs."""

    if type(sink_id) is not str:
        raise CoreSinkLineageError(["core_sink_lineage_observation_envelope_invalid"])
    sinks = _validate_contract(contract)
    validated_candidates = _validate_receipt_candidates(contract, candidates)
    sink = sinks.get(sink_id)
    if (
        sink is None
        or type(safety_inputs) not in {list, tuple}
        or len(safety_inputs) != 0
        or not _has_exact_keys(observations, {"rendered_observations", "safety_observations"})
        or type(observations["rendered_observations"]) not in {list, tuple}
        or type(observations["safety_observations"]) not in {list, tuple}
    ):
        raise CoreSinkLineageError(["core_sink_lineage_observation_envelope_invalid"])
    if len(observations["safety_observations"]) != 0:
        raise CoreSinkLineageError(["core_sink_lineage_safety_observation_count_mismatch"])
    expected_rendered, omissions = _expanded_sink_mapping(sink, validated_candidates)
    rendered_rows = observations["rendered_observations"]
    if len(rendered_rows) != len(expected_rendered):
        raise CoreSinkLineageError(["core_sink_lineage_observation_count_mismatch"])
    normalized_rendered: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rendered_rows:
        if not _has_exact_keys(row, _RENDERED_OBSERVATION_KEYS):
            raise CoreSinkLineageError(["core_sink_lineage_observation_invalid"])
        string_fields = ("rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id")
        if any(
            type(row[field]) is not str or not row[field].strip() or not _portable_string(row[field])
            for field in string_fields
        ) or not (
            type(row["observed_value"]) is str
            and bool(row["observed_value"].strip())
            and _portable_string(row["observed_value"])
        ):
            raise CoreSinkLineageError(["core_sink_lineage_observation_invalid"])
        key = (row["rule_id"], row["record_identity"], row["facet_path"])
        expected = expected_rendered.get(key)
        if key in seen or expected is None:
            raise CoreSinkLineageError(["core_sink_lineage_observation_duplicate_or_unknown"])
        seen.add(key)
        if (
            row["disposition"] not in _DISPOSITIONS
            or row["disposition"] != expected["disposition"]
            or row["slot_id"] != expected["slot_id"]
            or row["transform_id"] != expected["transform_id"]
            or _digest(row["observed_value"]) != expected["value_digest"]
        ):
            raise CoreSinkLineageError(["core_sink_lineage_observation_mismatch"])
        normalized_rendered.append(
            {
                "facet_id": expected["facet_id"],
                "source_pointer": expected["source_pointer"],
                "value_digest": expected["value_digest"],
                "disposition": expected["disposition"],
                "slot_id": expected["slot_id"],
                "transform_id": expected["transform_id"],
            }
        )
    normalized_rendered.sort(key=lambda row: row["facet_id"])
    all_rows = sorted([*normalized_rendered, *omissions], key=lambda row: row["facet_id"])
    return {
        "sink_id": sink_id,
        "state": "mapped_declared_incomplete_slice",
        "closes_global_gate": False,
        "expected": IN_SCOPE_CANDIDATES,
        "mapped_exactly_once": len(all_rows),
        "rendered": len(normalized_rendered),
        "explicitly_omitted": len(omissions),
        "unmapped": 0,
        "multiply_mapped": 0,
        "fallback_count": 0,
        "fixed_prose_counted_as_source": 0,
        "safety_inputs_expected": 0,
        "safety_inputs_bound": 0,
        "safety_violations": 0,
        "rendered_subject_digest": _digest(normalized_rendered),
        "omitted_subject_digest": _digest(omissions),
        "subject_set_digest": _digest(all_rows),
        "safety_input_digest": _digest([]),
        "producer_verdict": "PASS",
        "independent_verdict": "BLOCK",
        "error_codes": ["rendered_sink_universe_incomplete", "rendered_sink_independent_review_pending"],
    }


def build_core_sink_observation_receipt(
    *,
    contract: Mapping[str, Any],
    sink_id: str,
    candidates: Sequence[Mapping[str, Any]],
    safety_inputs: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one renderer envelope and return a payload-omitting receipt."""

    try:
        return _build_core_sink_observation_receipt(
            contract=contract,
            sink_id=sink_id,
            candidates=candidates,
            safety_inputs=safety_inputs,
            observations=observations,
        )
    except CoreSinkLineageError:
        raise
    except Exception:
        raise CoreSinkLineageError(["core_sink_lineage_receipt_input_invalid"]) from None


def _blocked_sink_receipt(sink_id: str) -> dict[str, Any]:
    return {
        "sink_id": sink_id,
        "state": "not_observed",
        "closes_global_gate": False,
        "expected": IN_SCOPE_CANDIDATES,
        "mapped_exactly_once": 0,
        "rendered": 0,
        "explicitly_omitted": 0,
        "unmapped": IN_SCOPE_CANDIDATES,
        "multiply_mapped": 0,
        "fallback_count": 0,
        "fixed_prose_counted_as_source": 0,
        "safety_inputs_expected": 0,
        "safety_inputs_bound": 0,
        "safety_violations": 0,
        "producer_verdict": "BLOCK",
        "independent_verdict": "BLOCK",
        "error_codes": ["rendered_sink_not_observed"],
    }


def _global_denominator() -> dict[str, Any]:
    return {
        "expected_candidates": GLOBAL_CANDIDATES,
        "in_scope_candidates": IN_SCOPE_CANDIDATES,
        "out_of_scope_candidates": OUT_OF_SCOPE_CANDIDATES,
        "independently_reviewed": 0,
        "unresolved": GLOBAL_CANDIDATES,
        "claim_contract_digest": CLAIM_CONTRACT_DIGEST,
        "classification_digest": CLASSIFICATION_DIGEST,
        "source_receipts_digest": SOURCE_RECEIPTS_DIGEST,
        "candidate_set_digest": CANDIDATE_SET_DIGEST,
    }


def _unavailable_core_sink_lineage(
    *, contract: Mapping[str, Any], source_raw: bytes, source_blob_oid: str, reason_code: str
) -> dict[str, Any]:
    """Build the fixed blocked shape after the public boundary is entered."""

    sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        type(reason_code) is not str
        or reason_code not in _UNAVAILABLE_REASONS
        or type(source_raw) is not bytes
        or type(source_blob_oid) is not str
        or source_blob_oid != source["git_blob_oid"]
        or len(source_raw) != source["bytes"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise CoreSinkLineageError(["core_sink_lineage_unavailable_input_invalid"])
    receipts = [_blocked_sink_receipt(sink_id) for sink_id in sorted(sinks)]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": CONTRACT_ID,
        "state": "not_declared",
        "closes_global_gate": False,
        "global_denominator": _global_denominator(),
        "source": {
            "path": SOURCE_PATH,
            "git_blob_oid": source_blob_oid,
            "candidate_count": 0,
            "candidate_digest": None,
            "facet_id_set_digest": source["facet_id_set_digest"],
            "safety_input_count": 0,
            "grounding_fallback_candidate_count": 0,
        },
        "contract_digest": _digest(contract),
        "sink_universe_complete": False,
        "declared_sink_count": len(sinks),
        "observed_sink_count": 0,
        "sink_receipts": receipts,
        "sink_receipts_digest": _digest(receipts),
        "independent_verdict": "BLOCK",
        "error_codes": [reason_code, "consequential_claim_rendered_sink_universe_incomplete"],
    }


def unavailable_core_sink_lineage(
    *, contract: Mapping[str, Any], source_raw: bytes, source_blob_oid: str, reason_code: str
) -> dict[str, Any]:
    """Return the fixed blocked shape when renderer subjects are unavailable."""

    try:
        return _unavailable_core_sink_lineage(
            contract=contract,
            source_raw=source_raw,
            source_blob_oid=source_blob_oid,
            reason_code=reason_code,
        )
    except CoreSinkLineageError:
        raise
    except Exception:
        raise CoreSinkLineageError(["core_sink_lineage_unavailable_input_invalid"]) from None


def _evaluate_core_sink_lineage(
    *,
    contract: Mapping[str, Any],
    claim_facet_records: Sequence[Mapping[str, Any]],
    core: Mapping[str, Any],
    source_raw: bytes,
    source_blob_oid: str,
    sink_observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate any subset of the two declared sinks without promoting gates."""

    if type(contract) is not dict or type(core) is not dict or type(source_raw) is not bytes:
        raise CoreSinkLineageError(["core_sink_lineage_input_invalid"])
    _validate_json_tree(contract)
    _validate_json_tree(core)
    sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        type(source_blob_oid) is not str
        or _OID.fullmatch(source_blob_oid) is None
        or source_blob_oid != source["git_blob_oid"]
        or len(source_raw) != source["bytes"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise CoreSinkLineageError(["core_sink_lineage_source_blob_mismatch"])
    parsed_source = _load_object(source_raw, "core_sink_lineage_source_blob_invalid")
    if _canonical(parsed_source) != _canonical(core):
        raise CoreSinkLineageError(["core_sink_lineage_source_object_mismatch"])
    candidates, fallback_candidates = _source_candidates(contract, core, source_blob_oid)
    _compare_compiler_facets(candidates, claim_facet_records, source_blob_oid)
    if not _has_exact_key_subset(sink_observations, set(sinks)):
        raise CoreSinkLineageError(["core_sink_lineage_sink_subset_invalid"])
    receipts: list[dict[str, Any]] = []
    for sink_id in sorted(sinks):
        if sink_id in sink_observations:
            receipts.append(
                build_core_sink_observation_receipt(
                    contract=contract,
                    sink_id=sink_id,
                    candidates=candidates,
                    safety_inputs=[],
                    observations=sink_observations[sink_id],
                )
            )
        else:
            receipts.append(_blocked_sink_receipt(sink_id))
    return {
        "schema_version": SCHEMA_VERSION,
        "id": CONTRACT_ID,
        "state": "declared_incomplete",
        "closes_global_gate": False,
        "global_denominator": _global_denominator(),
        "source": {
            "path": SOURCE_PATH,
            "git_blob_oid": source_blob_oid,
            "candidate_count": len(candidates),
            "candidate_digest": source["candidate_digest"],
            "facet_id_set_digest": source["facet_id_set_digest"],
            "safety_input_count": 0,
            "grounding_fallback_candidate_count": fallback_candidates,
        },
        "contract_digest": _digest(contract),
        "sink_universe_complete": False,
        "declared_sink_count": len(sinks),
        "observed_sink_count": len(sink_observations),
        "sink_receipts": receipts,
        "sink_receipts_digest": _digest(receipts),
        "independent_verdict": "BLOCK",
        "error_codes": [
            "consequential_claim_independent_review_pending",
            "consequential_claim_rendered_sink_universe_incomplete",
        ],
    }


def evaluate_core_sink_lineage(
    *,
    contract: Mapping[str, Any],
    claim_facet_records: Sequence[Mapping[str, Any]],
    core: Mapping[str, Any],
    source_raw: bytes,
    source_blob_oid: str,
    sink_observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate any subset of the two declared sinks without promoting gates."""

    try:
        return _evaluate_core_sink_lineage(
            contract=contract,
            claim_facet_records=claim_facet_records,
            core=core,
            source_raw=source_raw,
            source_blob_oid=source_blob_oid,
            sink_observations=sink_observations,
        )
    except CoreSinkLineageError:
        raise
    except Exception:
        raise CoreSinkLineageError(["core_sink_lineage_input_invalid"]) from None
