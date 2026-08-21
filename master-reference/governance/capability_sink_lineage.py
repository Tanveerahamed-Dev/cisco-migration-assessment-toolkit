"""Fail-closed lineage accounting for the bounded capability-catalog sink slice.

The slice binds the exact capability candidate facets to two declared default
renderers.  It supplies no semantic review, publication authority, or global
rendered-claim closure; those gates remain unconditionally false.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "rendered-sink-lineage-capability/1.0.0"
CONTRACT_SCHEMA_VERSION = "rendered-sink-lineage-capability-contract/1.0.0"
CONTRACT_ID = "atlas.rendered-sink-lineage.capability-catalog.v1"
EXPECTED_CONTRACT_DIGEST = "59a2f835396156f801d22ab5c367e36d1426ece04af87de8436488fa3a84db34"
SOURCE_PATH = "master-reference/content/capability-catalog.json"
GLOBAL_CANDIDATES = 2_140
IN_SCOPE_CANDIDATES = 426
OUT_OF_SCOPE_CANDIDATES = 1_714
EXPECTED_SAFETY_INPUTS = 7
EXPECTED_SEMANTIC_RECORDS = 227
EXPECTED_ENTRIES = 213
CLAIM_CONTRACT_DIGEST = "cf123369749c14ef140a9eb906b63f7183e93fd45a943a25087f5411a17399b6"
CLASSIFICATION_DIGEST = "594013cefc9f293cb6b224e6f869014e6015dd6f23a4ff708899afbb44c1f19c"
SOURCE_RECEIPTS_DIGEST = "aad6fbb1305ccaddea2b5257cbfa5704ba1548a1855c97bcbaa144ed6d8ecb30"
CANDIDATE_SET_DIGEST = "ed4bb19838118841b5f5cc3a3d7348ee9763d11e8f4ad4f610c5e3853a1f0d31"
MAX_CONTRACT_BYTES = 512 * 1024
MAX_STRING_LENGTH = 16_384
MAX_VALUES = 100_000
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FACET_ID = re.compile(r"urn:atlas:claim-facet:[0-9a-f]{64}")
_DISPOSITIONS = frozenset({"rendered_identity", "rendered_labeled", "rendered_derived"})
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
_SAFETY_OBSERVATION_KEYS = frozenset(
    {"rule_id", "record_identity", "boundary_field", "observed_value", "slot_id", "transform_id"}
)
_UNAVAILABLE_REASONS = frozenset(
    {
        "capability_sink_lineage_compiler_subjects_not_declared",
        "capability_sink_lineage_pdf_not_observed",
        "capability_sink_lineage_external_pdf_unverified",
    }
)


class CapabilitySinkLineageError(ValueError):
    """The capability lineage slice could not be proven."""

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


def _canonical(value: Any) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise CapabilitySinkLineageError(["capability_sink_lineage_canonicalization_failed"]) from None


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
    """Compare dictionary keys without invoking hostile subclass equality/hash."""

    if type(value) is not dict or len(value) != len(expected):
        return False
    keys = tuple(value)
    return all(type(key) is str for key in keys) and frozenset(keys) == frozenset(expected)


def _has_exact_key_subset(value: Any, expected: set[str]) -> bool:
    """Validate a plain-string dictionary key subset before hashing any key."""

    if type(value) is not dict:
        return False
    keys = tuple(value)
    return all(type(key) is str for key in keys) and frozenset(keys) <= frozenset(expected)


def _validate_json_tree(value: Any) -> None:
    stack = [value]
    count = 0
    while stack:
        current = stack.pop()
        count += 1
        if count > MAX_VALUES:
            raise CapabilitySinkLineageError(["capability_sink_lineage_structure_exceeds_bound"])
        if type(current) is dict:
            if len(current) > 512 or any(type(key) is not str or not _portable_string(key) for key in current):
                raise CapabilitySinkLineageError(["capability_sink_lineage_structure_exceeds_bound"])
            stack.extend(current.values())
        elif type(current) is list:
            if len(current) > 1_024:
                raise CapabilitySinkLineageError(["capability_sink_lineage_structure_exceeds_bound"])
            stack.extend(current)
        elif type(current) is str:
            if not _portable_string(current):
                raise CapabilitySinkLineageError(["capability_sink_lineage_structure_exceeds_bound"])
        elif current is None or type(current) in {bool, int}:
            if type(current) is int and not (-(2**53 - 1) <= current <= 2**53 - 1):
                raise CapabilitySinkLineageError(["capability_sink_lineage_structure_exceeds_bound"])
        else:
            raise CapabilitySinkLineageError(["capability_sink_lineage_nonportable_json"])


def load_capability_sink_lineage_contract(raw: bytes) -> dict[str, Any]:
    """Decode a portable bounded contract without echoing hostile values."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_CONTRACT_BYTES:
        raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"])
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            parse_float=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"]) from None
    if type(value) is not dict:
        raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"])
    _validate_json_tree(value)
    return value


def _validate_contract(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if type(contract) is not dict:
        raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"])
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
            or _OID.fullmatch(source["git_blob_oid"]) is None
            or _DIGEST.fullmatch(source["sha256"]) is None
            or source["expected_records"] != EXPECTED_SEMANTIC_RECORDS
            or source["expected_candidates"] != IN_SCOPE_CANDIDATES
            or source["expected_safety_inputs"] != EXPECTED_SAFETY_INPUTS
            or source["candidate_digest"] != "69c1b86c5ca41aca8b6f332e604448e024f3339a4f486b36a1ed4679025cd9ed"
            or source["facet_id_set_digest"]
            != "33488e2d456d874f0d80059e94fc196a0bb927e11deef58a7e274485f91d1f89"
        ):
            raise KeyError
        universe = contract["sink_universe"]
        if universe["complete"] is not False or universe["declared_count"] != 2:
            raise KeyError
        rules = source["candidate_rules"]
        if [rule["rule_id"] for rule in rules] != [
            "capability.root",
            "capability.entry_contract",
            "capability.domain",
            "capability.entry",
        ]:
            raise KeyError
        sinks = contract["sinks"]
        sink_by_id = {sink["sink_id"]: sink for sink in sinks}
        if len(sinks) != 2 or set(sink_by_id) != {"pdf.capability-catalog", "web.capabilities.default"}:
            raise KeyError
        for sink in sinks:
            if sink["expected_rendered"] != 426 or sink["expected_omitted"] != 0 or sink["omission_rules"] != []:
                raise KeyError
            if sum(row["expected_subjects"] for row in sink["rendered_rules"]) != 426:
                raise KeyError
            if sum(row["expected_inputs"] for row in sink["safety_mappings"]) != 7:
                raise KeyError
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"]) from None
    return sink_by_id


def _source_rows(capability: Mapping[str, Any], selector: str) -> list[tuple[Mapping[str, Any], str, str]]:
    if selector == "root":
        return [(capability, "@root", "")]
    if selector == "entry_contract":
        value = capability.get("entry_contract")
        if type(value) is not dict:
            raise CapabilitySinkLineageError(["capability_sink_lineage_source_shape_invalid"])
        return [(value, "@root", "/entry_contract")]
    domains = capability.get("domains")
    if type(domains) is not list or not domains or any(type(item) is not dict for item in domains):
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_shape_invalid"])
    if selector == "domains":
        return [(item, item.get("id"), f"/domains/{index}") for index, item in enumerate(domains)]
    if selector == "entries":
        rows: list[tuple[Mapping[str, Any], str, str]] = []
        for domain_index, domain in enumerate(domains):
            entries = domain.get("entries")
            if type(entries) is not list or not entries or any(type(item) is not dict for item in entries):
                raise CapabilitySinkLineageError(["capability_sink_lineage_source_shape_invalid"])
            rows.extend(
                (item, item.get("id"), f"/domains/{domain_index}/entries/{entry_index}")
                for entry_index, item in enumerate(entries)
            )
        return rows
    if selector == "training_entry":
        return [row for row in _source_rows(capability, "entries") if row[1] == "cap.engine.training-curriculum"]
    raise CapabilitySinkLineageError(["capability_sink_lineage_contract_invalid"])


def _identity_rows(
    rows: Sequence[tuple[Mapping[str, Any], Any, str]], expected: int
) -> list[tuple[Mapping[str, Any], str, str]]:
    if len(rows) != expected:
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_record_count_mismatch"])
    normalized: list[tuple[Mapping[str, Any], str, str]] = []
    seen: set[str] = set()
    for record, identity, pointer in rows:
        if (
            type(identity) is not str
            or not identity.strip()
            or not _portable_string(identity)
            or identity in seen
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_source_identity_invalid"])
        seen.add(identity)
        normalized.append((record, identity, pointer))
    return normalized


def _grounding(record: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for field in ("gap_refs", "owner_refs", "traffic_plane_refs"):
        if field not in record:
            continue
        value = record[field]
        if (
            type(value) is not list
            or any(type(item) is not str or not item.strip() or not _portable_string(item) for item in value)
            or len(value) != len(set(value))
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_grounding_invalid"])
        rows.extend({"field": field, "reference": item} for item in value)
    if not rows:
        rows.append({"field": "@source_owner", "reference": "owner.reference.contract"})
    return sorted(rows, key=lambda row: (row["field"], row["reference"]))


def _source_candidates(
    contract: Mapping[str, Any], capability: Mapping[str, Any], source_blob_oid: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = contract["source_scope"]
    semantic_records = 0
    candidates: list[dict[str, Any]] = []
    entries: list[tuple[Mapping[str, Any], str, str]] = []
    for rule in source["candidate_rules"]:
        rows = _source_rows(capability, rule["selector"])
        if rule["identity"] == "id":
            rows = _identity_rows(rows, rule["expected_records"])
        elif len(rows) != rule["expected_records"] or any(identity != "@root" for _, identity, _ in rows):
            raise CapabilitySinkLineageError(["capability_sink_lineage_source_record_count_mismatch"])
        semantic_records += len(rows)
        if rule["rule_id"] == "capability.entry":
            entries = list(rows)
        for record, identity, pointer in rows:
            grounding_digest = _digest(_grounding(record))
            for field in rule["candidate_fields"]:
                value = record.get(field)
                if type(value) is not str or not value.strip() or not _portable_string(value):
                    raise CapabilitySinkLineageError(["capability_sink_lineage_source_candidate_invalid"])
                facet_identity = {
                    "source_path": SOURCE_PATH,
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": identity,
                    "facet_path": field,
                }
                candidates.append(
                    {
                        "facet_id": "urn:atlas:claim-facet:" + _digest(facet_identity),
                        "source_path": SOURCE_PATH,
                        "source_blob_oid": source_blob_oid,
                        "source_pointer": f"{pointer}/{field}",
                        "rule_id": rule["rule_id"],
                        "record_kind": rule["record_kind"],
                        "record_identity": identity,
                        "facet_path": field,
                        "classification": "consequential_claim_candidate",
                        "claim_kind": "support_state" if field == "state" else "scope_boundary",
                        "review_state": "pending_independent_review",
                        "grounding_digest": grounding_digest,
                        "value_digest": _digest(value),
                    }
                )
    if semantic_records != EXPECTED_SEMANTIC_RECORDS or len(entries) != EXPECTED_ENTRIES:
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_record_count_mismatch"])
    if len(candidates) != IN_SCOPE_CANDIDATES:
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_candidate_count_mismatch"])
    candidates.sort(key=lambda row: row["facet_id"])
    if _digest(candidates) != source["candidate_digest"]:
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_candidate_digest_mismatch"])
    facet_ids = [row["facet_id"] for row in candidates]
    if len(facet_ids) != len(set(facet_ids)) or _digest(facet_ids) != source["facet_id_set_digest"]:
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_facet_set_mismatch"])

    boundary_entries = [
        (record, identity, pointer)
        for record, identity, pointer in entries
        if "content_role" in record or "mutates_assessment_truth" in record
    ]
    if len(boundary_entries) != 1 or boundary_entries[0][1] != "cap.engine.training-curriculum":
        raise CapabilitySinkLineageError(["capability_sink_lineage_safety_boundary_mismatch"])
    safety_inputs: list[dict[str, Any]] = []
    for rule in source["safety_rules"]:
        rows = _source_rows(capability, rule["selector"])
        if rule["identity"] == "id":
            rows = _identity_rows(rows, rule["expected_records"])
        elif len(rows) != rule["expected_records"]:
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_count_mismatch"])
        for record, identity, pointer in rows:
            for field in rule["fields"]:
                name = field["field"]
                expected = field["expected_value"]
                if name not in record or type(record[name]) is not type(expected) or record[name] != expected:
                    raise CapabilitySinkLineageError(["capability_sink_lineage_safety_boundary_mismatch"])
                safety_inputs.append(
                    {
                        "rule_id": rule["rule_id"],
                        "record_identity": identity,
                        "boundary_field": name,
                        "source_pointer": f"{pointer}/{name}",
                        "value_digest": _digest(record[name]),
                    }
                )
    if len(safety_inputs) != EXPECTED_SAFETY_INPUTS:
        raise CapabilitySinkLineageError(["capability_sink_lineage_safety_count_mismatch"])
    safety_inputs.sort(key=lambda row: (row["rule_id"], row["record_identity"], row["boundary_field"]))
    return candidates, safety_inputs


def _compare_compiler_facets(
    candidates: Sequence[Mapping[str, Any]], claim_facet_records: Sequence[Mapping[str, Any]], source_blob_oid: str
) -> None:
    if type(claim_facet_records) is not list or len(claim_facet_records) > 10_000:
        raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subjects_invalid"])
    actual: list[Mapping[str, Any]] = []
    for row in claim_facet_records:
        if not _has_exact_keys(row, _FACET_RECORD_KEYS):
            raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_invalid"])
        source_path = row.get("source_path")
        if type(source_path) is not str or not _portable_string(source_path):
            raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_invalid"])
        if source_path == SOURCE_PATH:
            actual.append(row)
    if len(actual) != IN_SCOPE_CANDIDATES:
        raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_count_mismatch"])
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in actual:
        facet_id = row.get("facet_id")
        if (
            any(type(row[key]) is not str for key in _FACET_RECORD_KEYS)
            or type(facet_id) is not str
            or facet_id in by_id
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_invalid"])
        by_id[facet_id] = row
    for expected in candidates:
        row = by_id.get(expected["facet_id"])
        if row is None or any(row.get(field) != value for field, value in expected.items()):
            raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_mismatch"])
        if (
            row.get("id") != _stable_record_id(expected["facet_id"])
            or row.get("entity_type") != "consequential_claim_facet"
            or row.get("evidence_state") != "payload_omitted_value_fingerprint_index_only"
            or row.get("review_state") != "pending_independent_review"
            or row.get("classification") != "consequential_claim_candidate"
            or row.get("source_blob_oid") != source_blob_oid
            or _FACET_ID.fullmatch(str(row.get("facet_id"))) is None
            or _DIGEST.fullmatch(str(row.get("grounding_digest"))) is None
            or _DIGEST.fullmatch(str(row.get("value_digest"))) is None
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_compiler_subject_mismatch"])


def _expanded_sink_mapping(
    sink: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], Mapping[str, Any]] = {}
    for rule in sink["rendered_rules"]:
        for field in rule["fields"]:
            key = (rule["rule_id"], field["facet_path"])
            if key in specs:
                raise CapabilitySinkLineageError(["capability_sink_lineage_mapping_duplicate"])
            specs[key] = field
    mapping: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        spec = specs.get((candidate["rule_id"], candidate["facet_path"]))
        if spec is None:
            raise CapabilitySinkLineageError(["capability_sink_lineage_mapping_incomplete"])
        key = (candidate["rule_id"], candidate["record_identity"], candidate["facet_path"])
        mapping[key] = {
            "facet_id": candidate["facet_id"],
            "source_pointer": candidate["source_pointer"],
            "value_digest": candidate["value_digest"],
            "disposition": spec["disposition"],
            "slot_id": spec["slot_template"].replace("{record_identity}", candidate["record_identity"]),
            "transform_id": spec["transform_id"],
        }
    if len(mapping) != sink["expected_rendered"]:
        raise CapabilitySinkLineageError(["capability_sink_lineage_mapping_count_mismatch"])
    return mapping


def _expected_safety_mapping(
    sink: Mapping[str, Any], safety_inputs: Sequence[Mapping[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    specs: dict[tuple[str, str], Mapping[str, Any]] = {}
    for rule in sink["safety_mappings"]:
        for field in rule["fields"]:
            key = (rule["rule_id"], field["field"])
            if key in specs:
                raise CapabilitySinkLineageError(["capability_sink_lineage_safety_mapping_duplicate"])
            specs[key] = field
    expected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in safety_inputs:
        spec = specs.get((item["rule_id"], item["boundary_field"]))
        if spec is None:
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_mapping_incomplete"])
        key = (item["rule_id"], item["record_identity"], item["boundary_field"])
        expected[key] = {
            "value_digest": item["value_digest"],
            "slot_id": spec["slot_template"].replace("{record_identity}", item["record_identity"]),
            "transform_id": spec["transform_id"],
        }
    if len(expected) != EXPECTED_SAFETY_INPUTS:
        raise CapabilitySinkLineageError(["capability_sink_lineage_safety_mapping_incomplete"])
    return expected


def build_capability_sink_observation_receipt(
    *,
    contract: Mapping[str, Any],
    sink_id: str,
    candidates: Sequence[Mapping[str, Any]],
    safety_inputs: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one renderer envelope and return a payload-omitting receipt."""

    sinks = _validate_contract(contract)
    if type(sink_id) is not str:
        raise CapabilitySinkLineageError(["capability_sink_lineage_observation_envelope_invalid"])
    sink = sinks.get(sink_id)
    if (
        sink is None
        or not _has_exact_keys(observations, {"rendered_observations", "safety_observations"})
        or type(observations["rendered_observations"]) not in {list, tuple}
        or type(observations["safety_observations"]) not in {list, tuple}
    ):
        raise CapabilitySinkLineageError(["capability_sink_lineage_observation_envelope_invalid"])
    expected_rendered = _expanded_sink_mapping(sink, candidates)
    rendered_rows = observations["rendered_observations"]
    if len(rendered_rows) != len(expected_rendered):
        raise CapabilitySinkLineageError(["capability_sink_lineage_observation_count_mismatch"])
    normalized_rendered: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rendered_rows:
        if not _has_exact_keys(row, _RENDERED_OBSERVATION_KEYS):
            raise CapabilitySinkLineageError(["capability_sink_lineage_observation_invalid"])
        string_fields = ("rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id")
        if any(
            type(row[field]) is not str or not row[field].strip() or not _portable_string(row[field])
            for field in string_fields
        ) or not (
            type(row["observed_value"]) is str
            and bool(row["observed_value"].strip())
            and _portable_string(row["observed_value"])
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_observation_invalid"])
        key = (row["rule_id"], row["record_identity"], row["facet_path"])
        expected = expected_rendered.get(key)
        if key in seen or expected is None:
            raise CapabilitySinkLineageError(["capability_sink_lineage_observation_duplicate_or_unknown"])
        seen.add(key)
        if (
            row["disposition"] not in _DISPOSITIONS
            or row["disposition"] != expected["disposition"]
            or row["slot_id"] != expected["slot_id"]
            or row["transform_id"] != expected["transform_id"]
            or _digest(row["observed_value"]) != expected["value_digest"]
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_observation_mismatch"])
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
    expected_safety = _expected_safety_mapping(sink, safety_inputs)
    safety_rows = observations["safety_observations"]
    if len(safety_rows) != len(expected_safety):
        raise CapabilitySinkLineageError(["capability_sink_lineage_safety_observation_count_mismatch"])
    normalized_safety: list[dict[str, Any]] = []
    seen_safety: set[tuple[str, str, str]] = set()
    for row in safety_rows:
        if not _has_exact_keys(row, _SAFETY_OBSERVATION_KEYS):
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_observation_invalid"])
        string_fields = ("rule_id", "record_identity", "boundary_field", "slot_id", "transform_id")
        value = row["observed_value"]
        if any(
            type(row[field]) is not str or not row[field].strip() or not _portable_string(row[field])
            for field in string_fields
        ) or not (
            type(value) is bool
            or (type(value) is str and bool(value.strip()) and _portable_string(value))
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_observation_invalid"])
        key = (row["rule_id"], row["record_identity"], row["boundary_field"])
        expected = expected_safety.get(key)
        if key in seen_safety or expected is None:
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_observation_duplicate_or_unknown"])
        seen_safety.add(key)
        if (
            _digest(value) != expected["value_digest"]
            or row["slot_id"] != expected["slot_id"]
            or row["transform_id"] != expected["transform_id"]
        ):
            raise CapabilitySinkLineageError(["capability_sink_lineage_safety_observation_mismatch"])
        normalized_safety.append(
            {
                "rule_id": key[0],
                "record_identity": key[1],
                "boundary_field": key[2],
                "value_digest": expected["value_digest"],
                "slot_id": expected["slot_id"],
                "transform_id": expected["transform_id"],
            }
        )
    normalized_rendered.sort(key=lambda row: row["facet_id"])
    normalized_safety.sort(key=lambda row: (row["rule_id"], row["record_identity"], row["boundary_field"]))
    return {
        "sink_id": sink_id,
        "state": "mapped_declared_incomplete_slice",
        "closes_global_gate": False,
        "expected": IN_SCOPE_CANDIDATES,
        "mapped_exactly_once": len(normalized_rendered),
        "rendered": len(normalized_rendered),
        "explicitly_omitted": 0,
        "unmapped": 0,
        "multiply_mapped": 0,
        "fallback_count": 0,
        "fixed_prose_counted_as_source": 0,
        "safety_inputs_expected": EXPECTED_SAFETY_INPUTS,
        "safety_inputs_bound": len(normalized_safety),
        "safety_violations": 0,
        "rendered_subject_digest": _digest(normalized_rendered),
        "omitted_subject_digest": _digest([]),
        "subject_set_digest": _digest(normalized_rendered),
        "safety_input_digest": _digest(normalized_safety),
        "producer_verdict": "PASS",
        "independent_verdict": "BLOCK",
        "error_codes": ["rendered_sink_universe_incomplete", "rendered_sink_independent_review_pending"],
    }


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
        "safety_inputs_expected": EXPECTED_SAFETY_INPUTS,
        "safety_inputs_bound": 0,
        "safety_violations": EXPECTED_SAFETY_INPUTS,
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


def unavailable_capability_sink_lineage(
    *, contract: Mapping[str, Any], source_raw: bytes, source_blob_oid: str, reason_code: str
) -> dict[str, Any]:
    """Return the fixed blocked shape when renderer subjects are unavailable."""

    sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        type(reason_code) is not str
        or reason_code not in _UNAVAILABLE_REASONS
        or type(source_raw) is not bytes
        or type(source_blob_oid) is not str
        or source_blob_oid != source["git_blob_oid"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise CapabilitySinkLineageError(["capability_sink_lineage_unavailable_input_invalid"])
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


def evaluate_capability_sink_lineage(
    *,
    contract: Mapping[str, Any],
    claim_facet_records: Sequence[Mapping[str, Any]],
    capability: Mapping[str, Any],
    source_raw: bytes,
    source_blob_oid: str,
    sink_observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate any subset of the two declared sinks without promoting gates."""

    if type(contract) is not dict or type(capability) is not dict or type(source_raw) is not bytes:
        raise CapabilitySinkLineageError(["capability_sink_lineage_input_invalid"])
    _validate_json_tree(contract)
    _validate_json_tree(capability)
    sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        type(source_blob_oid) is not str
        or _OID.fullmatch(source_blob_oid) is None
        or source_blob_oid != source["git_blob_oid"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_blob_mismatch"])
    try:
        parsed_source = json.loads(
            source_raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            parse_float=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_blob_invalid"]) from None
    if type(parsed_source) is not dict or _canonical(parsed_source) != _canonical(capability):
        raise CapabilitySinkLineageError(["capability_sink_lineage_source_object_mismatch"])
    candidates, safety_inputs = _source_candidates(contract, capability, source_blob_oid)
    _compare_compiler_facets(candidates, claim_facet_records, source_blob_oid)
    if not _has_exact_key_subset(sink_observations, set(sinks)):
        raise CapabilitySinkLineageError(["capability_sink_lineage_sink_subset_invalid"])
    receipts: list[dict[str, Any]] = []
    for sink_id in sorted(sinks):
        if sink_id in sink_observations:
            receipts.append(
                build_capability_sink_observation_receipt(
                    contract=contract,
                    sink_id=sink_id,
                    candidates=candidates,
                    safety_inputs=safety_inputs,
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
            "safety_input_count": len(safety_inputs),
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
