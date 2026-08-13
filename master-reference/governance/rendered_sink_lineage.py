"""Exact, fail-closed accounting for the bounded Open Horizon sink slice.

This module does not establish semantic acceptance or global rendered-claim
closure.  It joins the existing immutable claim-facet subjects to two declared
presentation sinks, expands contract-owned omissions, and emits payload-
omitting receipts while the global consequential-claim gate remains false.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "rendered-sink-lineage/1.0.0"
CONTRACT_SCHEMA_VERSION = "rendered-sink-lineage-contract/1.0.0"
CONTRACT_ID = "atlas.rendered-sink-lineage.open-horizon.v1"
EXPECTED_CONTRACT_DIGEST = "50cabd365f01e2a3da30a09d61b34fafc88e83b95aba4ae51f3d82f39ec78451"
SOURCE_PATH = "master-reference/content/open-horizon-register.json"
GLOBAL_CANDIDATES = 2136
IN_SCOPE_CANDIDATES = 315
OUT_OF_SCOPE_CANDIDATES = 1821
EXPECTED_SAFETY_INPUTS = 53
EXPECTED_SEMANTIC_RECORDS = 65
CLAIM_CONTRACT_DIGEST = "4ebd7da5caa6aab63f3ba122d480fef638f46b866c665845087433074f436c8d"
CLASSIFICATION_DIGEST = "b5bc4783b8bd6461fc4669b39a555ae061081a278e36712cdb6f70a5e673d1df"
SOURCE_RECEIPTS_DIGEST = "863f93c7bc0599b1cfe7e5b42eb5b10c8087a704af9de194be18d9bf28008689"
CANDIDATE_SET_DIGEST = "a768b5a6c9a94390ada8e9c24627c8908f6a7b51e3f06d59b79ac8f1a5ffdd43"
MAX_CONTRACT_BYTES = 512 * 1024
MAX_STRING_LENGTH = 16_384
MAX_VALUES = 20_000
_DIGEST = re.compile(r"[0-9a-f]{64}")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FACET_ID = re.compile(r"urn:atlas:claim-facet:[0-9a-f]{64}")
_DISPOSITIONS = frozenset(
    {
        "rendered_identity",
        "rendered_labeled",
        "rendered_ordered_array",
        "rendered_derived",
        "explicitly_omitted",
    }
)
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
        "rendered_sink_lineage_compiler_subjects_not_declared",
        "rendered_sink_lineage_pdf_not_observed",
        "rendered_sink_lineage_external_pdf_unverified",
    }
)


class RenderedSinkLineageError(ValueError):
    """The declared lineage slice could not be proven."""

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
        raise RenderedSinkLineageError(["rendered_sink_lineage_canonicalization_failed"]) from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_record_id(facet_id: str) -> str:
    # ``release.model.stable_id(kind, *parts)`` hashes only the joined parts;
    # the kind is the URN namespace, not part of the digest material.
    material = facet_id.encode("utf-8")
    return f"urn:atlas:claim-facet-record:{hashlib.sha256(material).hexdigest()[:24]}"


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


def _validate_bounds(value: Any) -> None:
    stack = [value]
    count = 0
    while stack:
        current = stack.pop()
        count += 1
        if count > MAX_VALUES:
            raise RenderedSinkLineageError(["rendered_sink_lineage_structure_exceeds_bound"])
        if isinstance(current, dict):
            if len(current) > 512 or any(not isinstance(key, str) or not _portable_string(key) for key in current):
                raise RenderedSinkLineageError(["rendered_sink_lineage_structure_exceeds_bound"])
            stack.extend(current.values())
        elif isinstance(current, list):
            if len(current) > 512:
                raise RenderedSinkLineageError(["rendered_sink_lineage_structure_exceeds_bound"])
            stack.extend(current)
        elif isinstance(current, str) and not _portable_string(current):
            raise RenderedSinkLineageError(["rendered_sink_lineage_structure_exceeds_bound"])


def load_rendered_sink_lineage_contract(raw: bytes) -> dict[str, Any]:
    """Decode the bounded contract without echoing hostile caller values."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_CONTRACT_BYTES:
        raise RenderedSinkLineageError(["rendered_sink_lineage_contract_invalid"])
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            parse_float=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise RenderedSinkLineageError(["rendered_sink_lineage_contract_invalid"]) from None
    if not isinstance(value, dict):
        raise RenderedSinkLineageError(["rendered_sink_lineage_contract_invalid"])
    _validate_bounds(value)
    return value


def _rows_for_selector(
    horizon: Mapping[str, Any], selector: str, identity: str
) -> list[tuple[Mapping[str, Any], str, str]]:
    if selector == "root":
        return [(horizon, "@root", "")]
    value = horizon.get(selector)
    if selector == "cadence":
        if not isinstance(value, dict):
            raise RenderedSinkLineageError(["rendered_sink_lineage_source_shape_invalid"])
        return [(value, "@root", "/cadence")]
    if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_shape_invalid"])
    rows: list[tuple[Mapping[str, Any], str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        record_identity = item.get(identity)
        if not isinstance(record_identity, str) or not record_identity.strip() or record_identity in seen:
            raise RenderedSinkLineageError(["rendered_sink_lineage_source_identity_invalid"])
        seen.add(record_identity)
        rows.append((item, record_identity, f"/{selector}/{index}"))
    return rows


def _validate_contract(contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        if (
            _digest(contract) != EXPECTED_CONTRACT_DIGEST
            or set(contract)
            != {
                "schema_version",
                "id",
                "state",
                "closes_global_gate",
                "global_denominator",
                "source_scope",
                "sink_universe",
                "sinks",
                "limitations",
            }
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
            or _DIGEST.fullmatch(source["candidate_digest"]) is None
            or _DIGEST.fullmatch(source["facet_id_set_digest"]) is None
        ):
            raise KeyError
        universe = contract["sink_universe"]
        if universe["complete"] is not False or universe["declared_count"] != 2:
            raise KeyError
        candidate_rules = source["candidate_rules"]
        safety_rules = source["safety_rules"]
        sinks = contract["sinks"]
        if len(candidate_rules) != 8 or len(safety_rules) != 3 or len(sinks) != 2:
            raise KeyError
        candidate_by_id = {rule["rule_id"]: rule for rule in candidate_rules}
        sink_by_id = {sink["sink_id"]: sink for sink in sinks}
        if len(candidate_by_id) != 8 or set(sink_by_id) != {"pdf.open-horizon", "web.gaps.open-horizon"}:
            raise KeyError
        for sink in sinks:
            if sink["expected_rendered"] != 167 or sink["expected_omitted"] != 148:
                raise KeyError
            if sum(rule["expected_subjects"] for rule in sink["rendered_rules"]) != 167:
                raise KeyError
            if sum(rule["expected_subjects"] for rule in sink["omission_rules"]) != 148:
                raise KeyError
            if sum(rule["expected_inputs"] for rule in sink["safety_mappings"]) != 53:
                raise KeyError
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        raise RenderedSinkLineageError(["rendered_sink_lineage_contract_invalid"]) from None
    return candidate_by_id, sink_by_id


def _source_candidates(
    contract: Mapping[str, Any], horizon: Mapping[str, Any], source_blob_oid: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = contract["source_scope"]
    candidates: list[dict[str, Any]] = []
    safety_inputs: list[dict[str, Any]] = []
    semantic_records = 0
    signal_identities: set[str] = set()
    for rule in source["candidate_rules"]:
        rows = _rows_for_selector(horizon, rule["selector"], rule["identity"])
        if len(rows) != rule["expected_records"]:
            raise RenderedSinkLineageError(["rendered_sink_lineage_source_record_count_mismatch"])
        semantic_records += len(rows)
        if rule["rule_id"] == "horizon.signal":
            signal_identities = {identity for _record, identity, _pointer in rows}
        for record, identity, pointer in rows:
            for field in rule["candidate_fields"]:
                if field not in record:
                    raise RenderedSinkLineageError(["rendered_sink_lineage_source_candidate_missing"])
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
                        "value_digest": _digest(record[field]),
                    }
                )
    if semantic_records != EXPECTED_SEMANTIC_RECORDS or len(candidates) != IN_SCOPE_CANDIDATES:
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_candidate_count_mismatch"])
    if "horizon.unknown" not in signal_identities:
        raise RenderedSinkLineageError(["rendered_sink_lineage_unknown_signal_missing"])
    facet_ids = sorted(row["facet_id"] for row in candidates)
    if len(facet_ids) != len(set(facet_ids)) or _digest(facet_ids) != source["facet_id_set_digest"]:
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_facet_set_mismatch"])
    for rule in source["safety_rules"]:
        rows = _rows_for_selector(horizon, rule["selector"], rule["identity"])
        if len(rows) != rule["expected_records"]:
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_count_mismatch"])
        for record, identity, pointer in rows:
            for field in rule["fields"]:
                name = field["field"]
                if (
                    name not in record
                    or type(record[name]) is not type(field["expected_value"])
                    or record[name] != field["expected_value"]
                ):
                    raise RenderedSinkLineageError(["rendered_sink_lineage_safety_boundary_mismatch"])
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
        raise RenderedSinkLineageError(["rendered_sink_lineage_safety_count_mismatch"])
    return sorted(candidates, key=lambda row: row["facet_id"]), sorted(
        safety_inputs, key=lambda row: (row["rule_id"], row["record_identity"], row["boundary_field"])
    )


def _compare_compiler_facets(
    candidates: Sequence[Mapping[str, Any]],
    claim_facet_records: Sequence[Mapping[str, Any]],
    source_blob_oid: str,
    expected_candidate_digest: str,
) -> None:
    if not isinstance(claim_facet_records, (list, tuple)) or len(claim_facet_records) > 10_000:
        raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subjects_invalid"])
    actual = [row for row in claim_facet_records if isinstance(row, Mapping) and row.get("source_path") == SOURCE_PATH]
    if len(actual) != IN_SCOPE_CANDIDATES:
        raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subject_count_mismatch"])
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in actual:
        if set(row) != _FACET_RECORD_KEYS or not isinstance(row.get("facet_id"), str) or row["facet_id"] in by_id:
            raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subject_invalid"])
        by_id[row["facet_id"]] = row
    candidate_payloads: list[dict[str, Any]] = []
    for expected in candidates:
        row = by_id.get(expected["facet_id"])
        if row is None or any(row.get(field) != value for field, value in expected.items()):
            raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subject_mismatch"])
        if (
            row.get("id") != _stable_record_id(expected["facet_id"])
            or row.get("entity_type") != "consequential_claim_facet"
            or row.get("evidence_state") != "payload_omitted_value_fingerprint_index_only"
            or row.get("review_state") != "pending_independent_review"
            or row.get("classification") != "consequential_claim_candidate"
            or row.get("source_blob_oid") != source_blob_oid
            or _FACET_ID.fullmatch(str(row.get("facet_id"))) is None
            or _DIGEST.fullmatch(str(row.get("grounding_digest"))) is None
        ):
            raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subject_mismatch"])
        candidate_payloads.append({key: row[key] for key in _CANDIDATE_KEYS})
    candidate_payloads.sort(key=lambda row: row["facet_id"])
    if _digest(candidate_payloads) != expected_candidate_digest:
        raise RenderedSinkLineageError(["rendered_sink_lineage_compiler_subject_mismatch"])


def _expanded_sink_mapping(
    sink: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]]:
    mapping: dict[tuple[str, str, str], dict[str, Any]] = {}
    omissions: list[dict[str, Any]] = []
    rendered_specs = {
        (rule["rule_id"], field["facet_path"]): field for rule in sink["rendered_rules"] for field in rule["fields"]
    }
    omitted_specs = {
        (rule["rule_id"], facet_path): rule for rule in sink["omission_rules"] for facet_path in rule["facet_paths"]
    }
    if set(rendered_specs) & set(omitted_specs):
        raise RenderedSinkLineageError(["rendered_sink_lineage_mapping_overlap"])
    for candidate in candidates:
        key = (candidate["rule_id"], candidate["record_identity"], candidate["facet_path"])
        rendered_spec = rendered_specs.get((candidate["rule_id"], candidate["facet_path"]))
        omitted_spec = omitted_specs.get((candidate["rule_id"], candidate["facet_path"]))
        if (rendered_spec is None) == (omitted_spec is None):
            raise RenderedSinkLineageError(["rendered_sink_lineage_mapping_incomplete"])
        if rendered_spec is not None:
            mapping[key] = {
                "facet_id": candidate["facet_id"],
                "source_pointer": candidate["source_pointer"],
                "value_digest": candidate["value_digest"],
                "disposition": rendered_spec["disposition"],
                "slot_id": rendered_spec["slot_template"].replace("{record_identity}", candidate["record_identity"]),
                "transform_id": rendered_spec["transform_id"],
            }
        else:
            omissions.append(
                {
                    "facet_id": candidate["facet_id"],
                    "source_pointer": candidate["source_pointer"],
                    "value_digest": candidate["value_digest"],
                    "disposition": "explicitly_omitted",
                    "omission_reason_code": omitted_spec["reason_code"],
                }
            )
    if len(mapping) != sink["expected_rendered"] or len(omissions) != sink["expected_omitted"]:
        raise RenderedSinkLineageError(["rendered_sink_lineage_mapping_count_mismatch"])
    return mapping, sorted(omissions, key=lambda row: row["facet_id"])


def _expected_safety_mapping(
    sink: Mapping[str, Any], safety_inputs: Sequence[Mapping[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    specs = {(rule["rule_id"], field["field"]): field for rule in sink["safety_mappings"] for field in rule["fields"]}
    expected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in safety_inputs:
        spec = specs.get((item["rule_id"], item["boundary_field"]))
        if spec is None:
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_mapping_incomplete"])
        key = (item["rule_id"], item["record_identity"], item["boundary_field"])
        expected[key] = {
            "value_digest": item["value_digest"],
            "slot_id": spec["slot_template"].replace("{record_identity}", item["record_identity"]),
            "transform_id": spec["transform_id"],
        }
    return expected


def build_sink_observation_receipt(
    *,
    contract: Mapping[str, Any],
    sink_id: str,
    candidates: Sequence[Mapping[str, Any]],
    safety_inputs: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one actual renderer envelope and return a digest-only receipt."""

    _candidate_by_id, sinks = _validate_contract(contract)
    sink = sinks.get(sink_id)
    if (
        sink is None
        or type(observations) is not dict
        or set(observations)
        != {
            "rendered_observations",
            "safety_observations",
        }
    ):
        raise RenderedSinkLineageError(["rendered_sink_lineage_observation_envelope_invalid"])
    rendered_rows = observations["rendered_observations"]
    safety_rows = observations["safety_observations"]
    if not isinstance(rendered_rows, (list, tuple)) or not isinstance(safety_rows, (list, tuple)):
        raise RenderedSinkLineageError(["rendered_sink_lineage_observation_envelope_invalid"])
    expected_rendered, omissions = _expanded_sink_mapping(sink, candidates)
    if len(rendered_rows) != len(expected_rendered):
        raise RenderedSinkLineageError(["rendered_sink_lineage_observation_count_mismatch"])
    normalized_rendered: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rendered_rows:
        if type(row) is not dict or set(row) != _RENDERED_OBSERVATION_KEYS:
            raise RenderedSinkLineageError(["rendered_sink_lineage_observation_invalid"])
        string_fields = ("rule_id", "record_identity", "facet_path", "disposition", "slot_id", "transform_id")
        if any(
            not isinstance(row[field], str) or not row[field].strip() or not _portable_string(row[field])
            for field in string_fields
        ):
            raise RenderedSinkLineageError(["rendered_sink_lineage_observation_invalid"])
        observed_value = row["observed_value"]
        if isinstance(observed_value, str):
            value_valid = bool(observed_value.strip()) and _portable_string(observed_value)
        elif type(observed_value) is list:
            value_valid = 0 < len(observed_value) <= 64 and all(
                isinstance(item, str) and bool(item.strip()) and _portable_string(item) for item in observed_value
            )
        else:
            value_valid = False
        if not value_valid:
            raise RenderedSinkLineageError(["rendered_sink_lineage_observation_invalid"])
        key = (row["rule_id"], row["record_identity"], row["facet_path"])
        expected = expected_rendered.get(key)
        if key in seen or expected is None:
            raise RenderedSinkLineageError(["rendered_sink_lineage_observation_duplicate_or_unknown"])
        seen.add(key)
        if (
            row["disposition"] not in _DISPOSITIONS
            or row["disposition"] != expected["disposition"]
            or row["slot_id"] != expected["slot_id"]
            or row["transform_id"] != expected["transform_id"]
            or _digest(row["observed_value"]) != expected["value_digest"]
        ):
            raise RenderedSinkLineageError(["rendered_sink_lineage_observation_mismatch"])
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
    if len(safety_rows) != len(expected_safety):
        raise RenderedSinkLineageError(["rendered_sink_lineage_safety_observation_count_mismatch"])
    normalized_safety: list[dict[str, Any]] = []
    seen_safety: set[tuple[str, str, str]] = set()
    for row in safety_rows:
        if type(row) is not dict or set(row) != _SAFETY_OBSERVATION_KEYS:
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_observation_invalid"])
        string_fields = ("rule_id", "record_identity", "boundary_field", "slot_id", "transform_id")
        if any(
            not isinstance(row[field], str) or not row[field].strip() or not _portable_string(row[field])
            for field in string_fields
        ) or not (
            type(row["observed_value"]) is bool
            or (
                isinstance(row["observed_value"], str)
                and bool(row["observed_value"].strip())
                and _portable_string(row["observed_value"])
            )
        ):
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_observation_invalid"])
        key = (row["rule_id"], row["record_identity"], row["boundary_field"])
        expected = expected_safety.get(key)
        if key in seen_safety or expected is None:
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_observation_duplicate_or_unknown"])
        seen_safety.add(key)
        if (
            _digest(row["observed_value"]) != expected["value_digest"]
            or row["slot_id"] != expected["slot_id"]
            or row["transform_id"] != expected["transform_id"]
        ):
            raise RenderedSinkLineageError(["rendered_sink_lineage_safety_observation_mismatch"])
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
        "safety_inputs_expected": EXPECTED_SAFETY_INPUTS,
        "safety_inputs_bound": len(normalized_safety),
        "safety_violations": 0,
        "rendered_subject_digest": _digest(sorted(normalized_rendered, key=lambda row: row["facet_id"])),
        "omitted_subject_digest": _digest(omissions),
        "subject_set_digest": _digest(all_rows),
        "safety_input_digest": _digest(
            sorted(normalized_safety, key=lambda row: (row["rule_id"], row["record_identity"], row["boundary_field"]))
        ),
        "producer_verdict": "PASS",
        "independent_verdict": "BLOCK",
        "error_codes": ["rendered_sink_universe_incomplete", "rendered_sink_independent_review_pending"],
    }


def unavailable_rendered_sink_lineage(
    *,
    contract: Mapping[str, Any],
    source_raw: bytes,
    source_blob_oid: str,
    reason_code: str,
) -> dict[str, Any]:
    """Return the fixed blocked shape when compiler subjects are unavailable."""

    _candidate_by_id, sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        reason_code not in _UNAVAILABLE_REASONS
        or type(source_raw) is not bytes
        or source_blob_oid != source["git_blob_oid"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise RenderedSinkLineageError(["rendered_sink_lineage_unavailable_input_invalid"])
    receipts = [
        {
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
        for sink_id in sorted(sinks)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": CONTRACT_ID,
        "state": "not_declared",
        "closes_global_gate": False,
        "global_denominator": {
            "expected_candidates": GLOBAL_CANDIDATES,
            "in_scope_candidates": IN_SCOPE_CANDIDATES,
            "out_of_scope_candidates": OUT_OF_SCOPE_CANDIDATES,
            "independently_reviewed": 0,
            "unresolved": GLOBAL_CANDIDATES,
            "claim_contract_digest": CLAIM_CONTRACT_DIGEST,
            "classification_digest": CLASSIFICATION_DIGEST,
            "source_receipts_digest": SOURCE_RECEIPTS_DIGEST,
            "candidate_set_digest": CANDIDATE_SET_DIGEST,
        },
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


def evaluate_rendered_sink_lineage(
    *,
    contract: Mapping[str, Any],
    claim_facet_records: Sequence[Mapping[str, Any]],
    horizon: Mapping[str, Any],
    source_raw: bytes,
    source_blob_oid: str,
    sink_observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate any nonempty subset of the two declared sinks.

    Absent declared sinks remain explicitly ``not_observed``.  A per-sink
    mechanical PASS never promotes the global consequential-claim gate.
    """

    if not isinstance(contract, Mapping) or not isinstance(horizon, Mapping) or type(source_raw) is not bytes:
        raise RenderedSinkLineageError(["rendered_sink_lineage_input_invalid"])
    _validate_bounds(contract)
    _validate_bounds(horizon)
    _candidate_by_id, sinks = _validate_contract(contract)
    source = contract["source_scope"]
    if (
        not isinstance(source_blob_oid, str)
        or _OID.fullmatch(source_blob_oid) is None
        or source_blob_oid != source["git_blob_oid"]
        or hashlib.sha256(source_raw).hexdigest() != source["sha256"]
        or _git_blob_oid(source_raw, source_blob_oid) != source_blob_oid
    ):
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_blob_mismatch"])
    try:
        parsed_source = json.loads(
            source_raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            parse_float=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError, RecursionError):
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_blob_invalid"]) from None
    if type(parsed_source) is not dict or _canonical(parsed_source) != _canonical(horizon):
        raise RenderedSinkLineageError(["rendered_sink_lineage_source_object_mismatch"])
    candidates, safety_inputs = _source_candidates(contract, horizon, source_blob_oid)
    _compare_compiler_facets(candidates, claim_facet_records, source_blob_oid, source["candidate_digest"])
    if not isinstance(sink_observations, Mapping) or not set(sink_observations) <= set(sinks):
        raise RenderedSinkLineageError(["rendered_sink_lineage_sink_subset_invalid"])
    receipts: list[dict[str, Any]] = []
    for sink_id in sorted(sinks):
        if sink_id in sink_observations:
            receipts.append(
                build_sink_observation_receipt(
                    contract=contract,
                    sink_id=sink_id,
                    candidates=candidates,
                    safety_inputs=safety_inputs,
                    observations=sink_observations[sink_id],
                )
            )
        else:
            receipts.append(
                {
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
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "id": CONTRACT_ID,
        "state": "declared_incomplete",
        "closes_global_gate": False,
        "global_denominator": {
            "expected_candidates": GLOBAL_CANDIDATES,
            "in_scope_candidates": IN_SCOPE_CANDIDATES,
            "out_of_scope_candidates": OUT_OF_SCOPE_CANDIDATES,
            "independently_reviewed": 0,
            "unresolved": GLOBAL_CANDIDATES,
            "claim_contract_digest": CLAIM_CONTRACT_DIGEST,
            "classification_digest": CLASSIFICATION_DIGEST,
            "source_receipts_digest": SOURCE_RECEIPTS_DIGEST,
            "candidate_set_digest": CANDIDATE_SET_DIGEST,
        },
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
