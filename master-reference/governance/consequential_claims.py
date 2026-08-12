"""Fail-closed census for a bounded subset of curated consequential claims.

This module does not assert that the curated-content subset is the global
consequential-claim universe.  It inventories one explicitly registered
source and reports the other curated content owners as unclassified.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping


CONTRACT_PATH = "master-reference/governance/consequential-claim-contract.json"
CONTRACT_SCHEMA_VERSION = "bounded-curated-consequential-claims/1"
CONTRACT_KIND = "bounded_curated_content_claim_denominator"
CONTENT_PATHS = (
    "master-reference/content/atlas-core.json",
    "master-reference/content/capability-catalog.json",
    "master-reference/content/delivery-governance.json",
    "master-reference/content/open-horizon-register.json",
    "master-reference/content/output-contract.json",
)
COMPILER_INTEGRITY_PREDICATES = frozenset(
    {
        "repository.full_exposure_file_count",
        "repository.graphify_status",
        "repository.nonblank_line_record_count",
        "repository.source_commit",
        "repository.source_tree_digest",
        "repository.tracked_file_count",
    }
)
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CANDIDATES = 100_000
MAX_JSON_DEPTH = 64
MAX_JSON_VALUES = 1_000_000
MAX_JSON_CONTAINER_ITEMS = 100_000
MAX_JSON_STRING_LENGTH = 1_048_576
MAX_OWNER_REFERENCE_ITEMS = 1_000
MAX_OWNER_REFERENCE_LENGTH = 1_024
MAX_JSON_NUMBER_TOKEN_LENGTH = 128
MAX_PORTABLE_INTEGER = 9_007_199_254_740_991
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SOURCE_CLASSIFICATIONS = frozenset({"candidate_census", "unclassified_source"})
_ALLOWED_EXCLUDED_CLASSIFICATIONS = frozenset(
    {"governance_metadata", "identifier_metadata", "label_metadata", "relationship_metadata"}
)
_ALLOWED_CONTAINER_CLASSIFICATIONS = frozenset(
    {"collection_container", "governance_metadata", "identifier_metadata", "registry_metadata"}
)
_EXPECTED_ROOT_FIELD_CLASSIFICATIONS = {
    "catalog_version": "registry_metadata",
    "denominator_rule": "governance_metadata",
    "domains": "collection_container",
    "entry_contract": "governance_metadata",
    "id": "identifier_metadata",
    "kind": "registry_metadata",
    "schema_version": "registry_metadata",
}
_EXPECTED_DOMAIN_FIELD_CLASSIFICATIONS = {
    "entity_role": "governance_metadata",
    "entries": "collection_container",
    "id": "identifier_metadata",
}
_EXPECTED_EXCLUDED_FIELD_CLASSIFICATIONS = {
    "content_role": "governance_metadata",
    "gap_refs": "relationship_metadata",
    "id": "identifier_metadata",
    "mutates_assessment_truth": "governance_metadata",
    "owner_refs": "relationship_metadata",
    "title": "label_metadata",
    "traffic_plane_refs": "relationship_metadata",
}
_EXPECTED_OWNER_REFERENCE_FIELDS = frozenset({"owner_refs", "gap_refs"})
_EXPECTED_FACETS = {
    "state": ("consequential_claim_candidate", "pending_independent_review"),
    "current_scope": ("consequential_claim_candidate", "pending_independent_review"),
}
_FIXED_PENDING_CODES = (
    "consequential_claim_independent_review_pending",
    "consequential_claim_source_universe_incomplete",
)


class ConsequentialClaimContractError(ValueError):
    """The bounded claim contract or selected-commit source set is invalid."""

    def __init__(self, codes: list[str] | tuple[str, ...]):
        self.codes = tuple(sorted(set(codes)))
        super().__init__(", ".join(self.codes))


class _DuplicateKey(ValueError):
    pass


class _NonFiniteNumber(ValueError):
    pass


class _NumberOutsidePortableDomain(ValueError):
    pass


def unavailable_bounded_curated_claim_summary(
    *,
    source_commit: str | None = None,
    source_tree_digest: str | None = None,
    reason_code: str = "consequential_claim_contract_absent",
) -> dict[str, Any]:
    """Return the non-vacuous blocked shape used before/without evaluation."""

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "denominator_kind": CONTRACT_KIND,
        "state": "not_declared",
        "closed": False,
        "source_commit": source_commit,
        "source_tree_digest": source_tree_digest,
        "source_basis": "selected_commit_raw_git_blobs",
        "contract_path": CONTRACT_PATH,
        "contract_git_blob_oid": None,
        "contract_digest": None,
        "classification_digest": None,
        "source_universe_expected": len(CONTENT_PATHS),
        "source_universe_registered": 0,
        "source_universe_unclassified": len(CONTENT_PATHS),
        "source_receipts": [],
        "source_receipts_digest": None,
        "expected_candidates": 0,
        "discovered_candidates": 0,
        "classified_candidates": 0,
        "independently_reviewed_candidates": 0,
        "unresolved_candidates": 0,
        "candidate_set_digest": None,
        "compiler_integrity_claims_expected": len(COMPILER_INTEGRITY_PREDICATES),
        "compiler_integrity_claims_classified": 0,
        "compiler_integrity_claims_consequential": 0,
        "error_codes": sorted({reason_code, "consequential_claim_source_universe_incomplete"}),
    }


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    try:
        return hashlib.sha256(_canonical(value)).hexdigest()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ConsequentialClaimContractError(["consequential_claim_canonicalization_failed"]) from exc


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise _NonFiniteNumber


def _parse_portable_int(value: str) -> int:
    if len(value) > MAX_JSON_NUMBER_TOKEN_LENGTH:
        raise _NumberOutsidePortableDomain
    parsed = int(value)
    if not -MAX_PORTABLE_INTEGER <= parsed <= MAX_PORTABLE_INTEGER:
        raise _NumberOutsidePortableDomain
    return parsed


def _parse_portable_float(value: str) -> float:
    if len(value) > MAX_JSON_NUMBER_TOKEN_LENGTH:
        raise _NumberOutsidePortableDomain
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NumberOutsidePortableDomain
    return parsed


def _validate_json_bounds(value: Any) -> None:
    def string_is_portable(item: str) -> bool:
        return len(item) <= MAX_JSON_STRING_LENGTH and all(not 0xD800 <= ord(character) <= 0xDFFF for character in item)

    stack: list[tuple[Any, int]] = [(value, 1)]
    values = 0
    while stack:
        current, depth = stack.pop()
        values += 1
        if values > MAX_JSON_VALUES or depth > MAX_JSON_DEPTH:
            raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
        if isinstance(current, dict):
            if len(current) > MAX_JSON_CONTAINER_ITEMS:
                raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
            if any(not string_is_portable(key) for key in current):
                raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if len(current) > MAX_JSON_CONTAINER_ITEMS:
                raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str) and not string_is_portable(current):
            raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])


def _load_object(raw: bytes, code: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ConsequentialClaimContractError([code])
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite,
            parse_int=_parse_portable_int,
            parse_float=_parse_portable_float,
        )
    except _DuplicateKey as exc:
        raise ConsequentialClaimContractError(["consequential_claim_json_duplicate_key"]) from exc
    except _NonFiniteNumber as exc:
        raise ConsequentialClaimContractError(["consequential_claim_json_nonfinite_number"]) from exc
    except _NumberOutsidePortableDomain as exc:
        raise ConsequentialClaimContractError(["consequential_claim_json_number_outside_portable_domain"]) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ConsequentialClaimContractError([code]) from exc
    if not isinstance(value, dict):
        raise ConsequentialClaimContractError([code])
    _validate_json_bounds(value)
    return value


def _git_blob_oid(raw: bytes, expected_oid: str) -> str:
    material = f"blob {len(raw)}\0".encode("ascii") + raw
    if len(expected_oid) == 40:
        return hashlib.sha1(material, usedforsecurity=False).hexdigest()
    if len(expected_oid) == 64:
        return hashlib.sha256(material).hexdigest()
    return ""


def _rfc6901(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _classified_field_names(
    source: Mapping[str, Any],
    key: str,
    allowed: frozenset[str],
    errors: list[str],
) -> list[str]:
    rows = source.get(key)
    fields: list[str] = []
    if not isinstance(rows, list) or not rows:
        errors.append(f"consequential_claim_{key}_contract_empty")
        return fields
    for item in rows:
        if not isinstance(item, dict) or set(item) != {"field", "classification"}:
            errors.append(f"consequential_claim_{key}_contract_invalid")
            continue
        field = item.get("field")
        if not isinstance(field, str) or not field or field in fields:
            errors.append(f"consequential_claim_{key}_duplicate_or_invalid")
        else:
            fields.append(field)
        if item.get("classification") not in allowed:
            errors.append(f"consequential_claim_{key}_classification_unknown")
    return fields


def _classified_field_mapping(source: Mapping[str, Any], key: str) -> dict[str, str]:
    rows = source.get(key)
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, dict) or set(item) != {"field", "classification"}:
            continue
        field = item.get("field")
        classification = item.get("classification")
        if isinstance(field, str) and isinstance(classification, str):
            mapping[field] = classification
    return mapping


def _validate_contract(contract: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    errors: list[str] = []
    if set(contract) != {"schema_version", "contract_kind", "source_universe", "compiler_integrity_claims"}:
        errors.append("consequential_claim_contract_keys_invalid")
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION or contract.get("contract_kind") != CONTRACT_KIND:
        errors.append("consequential_claim_contract_version_invalid")

    sources = contract.get("source_universe")
    source_by_path: dict[str, dict[str, Any]] = {}
    if not isinstance(sources, list) or len(sources) != len(CONTENT_PATHS):
        errors.append("consequential_claim_source_universe_membership_invalid")
        sources = []
    for source in sources:
        if not isinstance(source, dict):
            errors.append("consequential_claim_source_entry_invalid")
            continue
        path = source.get("path")
        classification = source.get("classification")
        if not isinstance(path, str) or not path or path in source_by_path:
            errors.append("consequential_claim_source_path_duplicate_or_invalid")
            continue
        if (
            not isinstance(source.get("git_blob_oid"), str)
            or _SOURCE_COMMIT.fullmatch(str(source.get("git_blob_oid"))) is None
        ):
            errors.append("consequential_claim_source_blob_identity_invalid")
        if classification not in _ALLOWED_SOURCE_CLASSIFICATIONS:
            errors.append("consequential_claim_source_classification_unknown")
        source_by_path[path] = source
    if set(source_by_path) != set(CONTENT_PATHS):
        errors.append("consequential_claim_source_universe_membership_invalid")
    census_sources = [row for row in source_by_path.values() if row.get("classification") == "candidate_census"]
    if len(census_sources) != 1 or census_sources[0].get("path") != "master-reference/content/capability-catalog.json":
        errors.append("consequential_claim_candidate_census_source_invalid")
    for source in source_by_path.values():
        if source.get("classification") == "unclassified_source":
            if (
                set(source) != {"path", "git_blob_oid", "classification", "reason_code"}
                or source.get("reason_code") != "consequential_claim_source_not_classified"
            ):
                errors.append("consequential_claim_unclassified_source_invalid")
            continue
        expected_keys = {
            "path",
            "git_blob_oid",
            "classification",
            "semantic_collection_selector",
            "id_field",
            "owner_reference_fields",
            "root_fields",
            "domain_fields",
            "facets",
            "excluded_fields",
        }
        if set(source) != expected_keys or source.get("semantic_collection_selector") != "domains[].entries[]":
            errors.append("consequential_claim_candidate_selector_invalid")
        if source.get("id_field") != "id":
            errors.append("consequential_claim_candidate_id_field_invalid")
        owner_fields = source.get("owner_reference_fields")
        if (
            not isinstance(owner_fields, list)
            or not 1 <= len(owner_fields) <= 8
            or any(not isinstance(item, str) or not item or len(item) > 128 for item in owner_fields)
            or len(owner_fields) != len(set(owner_fields))
        ):
            errors.append("consequential_claim_owner_reference_fields_invalid")
        elif set(owner_fields) != _EXPECTED_OWNER_REFERENCE_FIELDS:
            errors.append("consequential_claim_owner_reference_fields_mismatch")
        _classified_field_names(source, "root_fields", _ALLOWED_CONTAINER_CLASSIFICATIONS, errors)
        _classified_field_names(source, "domain_fields", _ALLOWED_CONTAINER_CLASSIFICATIONS, errors)
        if _classified_field_mapping(source, "root_fields") != _EXPECTED_ROOT_FIELD_CLASSIFICATIONS:
            errors.append("consequential_claim_root_fields_classification_mismatch")
        if _classified_field_mapping(source, "domain_fields") != _EXPECTED_DOMAIN_FIELD_CLASSIFICATIONS:
            errors.append("consequential_claim_domain_fields_classification_mismatch")
        facets = source.get("facets")
        facet_fields: list[str] = []
        if not isinstance(facets, list) or not facets:
            errors.append("consequential_claim_facet_contract_empty")
            facets = []
        for facet in facets:
            if not isinstance(facet, dict) or set(facet) != {"field", "classification", "review_state"}:
                errors.append("consequential_claim_facet_contract_invalid")
                continue
            field = facet.get("field")
            if not isinstance(field, str) or not field or field in facet_fields:
                errors.append("consequential_claim_facet_duplicate_or_invalid")
            else:
                facet_fields.append(field)
            if facet.get("classification") != "consequential_claim_candidate":
                errors.append("consequential_claim_facet_classification_unknown")
            if facet.get("review_state") != "pending_independent_review":
                errors.append("consequential_claim_facet_review_state_invalid")
        actual_facets = {
            str(item.get("field")): (item.get("classification"), item.get("review_state"))
            for item in facets
            if isinstance(item, dict)
        }
        if actual_facets != _EXPECTED_FACETS:
            errors.append("consequential_claim_facets_mismatch")
        excluded = source.get("excluded_fields")
        excluded_fields: list[str] = []
        if not isinstance(excluded, list) or not excluded:
            errors.append("consequential_claim_excluded_field_contract_empty")
            excluded = []
        for item in excluded:
            if not isinstance(item, dict) or set(item) != {"field", "classification"}:
                errors.append("consequential_claim_excluded_field_contract_invalid")
                continue
            field = item.get("field")
            if not isinstance(field, str) or not field or field in excluded_fields:
                errors.append("consequential_claim_excluded_field_duplicate_or_invalid")
            else:
                excluded_fields.append(field)
            if item.get("classification") not in _ALLOWED_EXCLUDED_CLASSIFICATIONS:
                errors.append("consequential_claim_excluded_field_classification_unknown")
        if _classified_field_mapping(source, "excluded_fields") != _EXPECTED_EXCLUDED_FIELD_CLASSIFICATIONS:
            errors.append("consequential_claim_excluded_fields_classification_mismatch")
        if set(facet_fields) & set(excluded_fields):
            errors.append("consequential_claim_field_classification_overlap")

    integrity = contract.get("compiler_integrity_claims")
    predicates: list[str] = []
    if not isinstance(integrity, list) or not integrity:
        errors.append("consequential_claim_integrity_registry_empty")
        integrity = []
    for item in integrity:
        if not isinstance(item, dict) or set(item) != {"predicate", "classification", "consequential"}:
            errors.append("consequential_claim_integrity_registry_entry_invalid")
            continue
        predicate = item.get("predicate")
        if not isinstance(predicate, str) or not predicate or predicate in predicates:
            errors.append("consequential_claim_integrity_predicate_duplicate_or_invalid")
        else:
            predicates.append(predicate)
        if item.get("classification") != "integrity_metadata" or item.get("consequential") is not False:
            errors.append("consequential_claim_integrity_classification_invalid")
    if set(predicates) != COMPILER_INTEGRITY_PREDICATES:
        errors.append("consequential_claim_integrity_registry_incomplete")
    if errors:
        raise ConsequentialClaimContractError(errors)
    return source_by_path, tuple(predicates)


def evaluate_bounded_curated_claims(
    *,
    contract_raw: bytes,
    contract_git_blob_oid: str,
    source_blobs: Mapping[str, tuple[str, bytes]],
    source_commit: str,
    source_tree_digest: str,
    compiler_claim_predicates: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return an exact-source, value-redacted, deliberately incomplete census."""

    if _SOURCE_COMMIT.fullmatch(source_commit) is None or _DIGEST.fullmatch(source_tree_digest) is None:
        raise ConsequentialClaimContractError(["consequential_claim_source_binding_invalid"])
    contract = _load_object(contract_raw, "consequential_claim_contract_malformed")
    if _git_blob_oid(contract_raw, contract_git_blob_oid) != contract_git_blob_oid:
        raise ConsequentialClaimContractError(["consequential_claim_contract_blob_identity_mismatch"])
    source_by_path, integrity_predicates = _validate_contract(contract)
    if len(source_blobs) != len(CONTENT_PATHS) or set(source_blobs) != set(CONTENT_PATHS):
        raise ConsequentialClaimContractError(["consequential_claim_source_universe_membership_invalid"])
    if set(compiler_claim_predicates) != set(integrity_predicates) or len(compiler_claim_predicates) != len(
        set(compiler_claim_predicates)
    ):
        raise ConsequentialClaimContractError(["consequential_claim_integrity_claim_set_mismatch"])

    source_receipts: list[dict[str, Any]] = []
    parsed_sources: dict[str, dict[str, Any]] = {}
    for path in CONTENT_PATHS:
        oid, raw = source_blobs[path]
        if not isinstance(oid, str) or _SOURCE_COMMIT.fullmatch(oid) is None:
            raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_invalid"])
        if _git_blob_oid(raw, oid) != oid:
            raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_mismatch"])
        if oid != source_by_path[path].get("git_blob_oid"):
            raise ConsequentialClaimContractError(["consequential_claim_source_contract_stale"])
        parsed_sources[path] = _load_object(raw, "consequential_claim_source_malformed")
        source_receipts.append(
            {
                "path": path,
                "git_blob_oid": oid,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "classification": source_by_path[path]["classification"],
            }
        )

    census_contract = source_by_path["master-reference/content/capability-catalog.json"]
    catalog = parsed_sources[census_contract["path"]]
    domains = catalog.get("domains")
    if not isinstance(domains, list) or not domains:
        raise ConsequentialClaimContractError(["consequential_claim_candidate_collection_empty"])
    facets = {str(item["field"]): item for item in census_contract["facets"]}
    root_fields = set(_classified_field_names(census_contract, "root_fields", _ALLOWED_CONTAINER_CLASSIFICATIONS, []))
    domain_fields = set(
        _classified_field_names(census_contract, "domain_fields", _ALLOWED_CONTAINER_CLASSIFICATIONS, [])
    )
    if set(catalog) != root_fields:
        raise ConsequentialClaimContractError(["consequential_claim_catalog_root_field_unregistered"])
    excluded_fields = {str(item["field"]) for item in census_contract["excluded_fields"]}
    owner_fields = tuple(str(item) for item in census_contract["owner_reference_fields"])
    candidates: list[dict[str, Any]] = []
    seen_entry_ids: set[str] = set()
    seen_domain_ids: set[str] = set()
    source_oid = str(census_contract["git_blob_oid"])
    for domain_index, domain in enumerate(domains):
        if not isinstance(domain, dict) or set(domain) != domain_fields or not isinstance(domain.get("entries"), list):
            raise ConsequentialClaimContractError(["consequential_claim_candidate_collection_malformed"])
        domain_id = domain.get("id")
        if not isinstance(domain_id, str) or not domain_id or domain_id in seen_domain_ids:
            raise ConsequentialClaimContractError(["consequential_claim_domain_id_duplicate_or_invalid"])
        seen_domain_ids.add(domain_id)
        for entry_index, entry in enumerate(domain["entries"]):
            if not isinstance(entry, dict):
                raise ConsequentialClaimContractError(["consequential_claim_candidate_entry_malformed"])
            entry_id = entry.get(str(census_contract["id_field"]))
            if not isinstance(entry_id, str) or not entry_id or entry_id in seen_entry_ids:
                raise ConsequentialClaimContractError(["consequential_claim_candidate_id_duplicate_or_invalid"])
            seen_entry_ids.add(entry_id)
            unregistered = set(entry) - set(facets) - excluded_fields
            if unregistered:
                raise ConsequentialClaimContractError(["consequential_claim_candidate_field_unregistered"])
            owner_references: list[dict[str, str]] = []
            for owner_field in owner_fields:
                if owner_field not in entry:
                    continue
                references = entry[owner_field]
                if not isinstance(references, list) or len(references) > MAX_OWNER_REFERENCE_ITEMS:
                    raise ConsequentialClaimContractError(["consequential_claim_candidate_owner_reference_invalid"])
                if any(
                    not isinstance(item, str) or not item.strip() or len(item) > MAX_OWNER_REFERENCE_LENGTH
                    for item in references
                ) or len(references) != len(set(references)):
                    raise ConsequentialClaimContractError(["consequential_claim_candidate_owner_reference_invalid"])
                owner_references.extend({"field": owner_field, "reference": item} for item in references)
            owner_references.sort(key=lambda item: (item["field"], item["reference"]))
            if not owner_references:
                raise ConsequentialClaimContractError(["consequential_claim_candidate_owner_orphan"])
            for field, facet in sorted(facets.items()):
                value = entry.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ConsequentialClaimContractError(["consequential_claim_candidate_value_invalid"])
                pointer = f"/domains/{domain_index}/entries/{entry_index}/{_rfc6901(field)}"
                facet_identity = {
                    "source_path": census_contract["path"],
                    "source_blob_oid": source_oid,
                    "domain_id": domain_id,
                    "entry_id": entry_id,
                    "field": field,
                }
                candidates.append(
                    {
                        "facet_id": "urn:atlas:claim-facet:" + _digest(facet_identity)[:24],
                        "source_path": census_contract["path"],
                        "source_blob_oid": source_oid,
                        "source_pointer": pointer,
                        "domain_id": domain_id,
                        "entry_id": entry_id,
                        "field": field,
                        "classification": facet["classification"],
                        "review_state": facet["review_state"],
                        "owner_reference_digest": _digest(owner_references),
                        "value_digest": _digest(value),
                    }
                )
                if len(candidates) > MAX_CANDIDATES:
                    raise ConsequentialClaimContractError(["consequential_claim_candidate_denominator_exceeds_bound"])
    if not candidates:
        raise ConsequentialClaimContractError(["consequential_claim_candidate_denominator_empty"])
    candidate_ids = [str(item["facet_id"]) for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ConsequentialClaimContractError(["consequential_claim_candidate_facet_id_duplicate"])
    candidates.sort(key=lambda item: str(item["facet_id"]))
    registered_sources = sum(1 for row in source_receipts if row["classification"] == "candidate_census")
    unclassified_sources = len(source_receipts) - registered_sources
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "denominator_kind": CONTRACT_KIND,
        "state": "declared_incomplete",
        "closed": False,
        "source_commit": source_commit,
        "source_tree_digest": source_tree_digest,
        "source_basis": "selected_commit_raw_git_blobs",
        "contract_path": CONTRACT_PATH,
        "contract_git_blob_oid": contract_git_blob_oid,
        "contract_digest": hashlib.sha256(contract_raw).hexdigest(),
        "classification_digest": _digest(
            {
                "source_universe": contract["source_universe"],
                "compiler_integrity_claims": contract["compiler_integrity_claims"],
            }
        ),
        "source_universe_expected": len(CONTENT_PATHS),
        "source_universe_registered": registered_sources,
        "source_universe_unclassified": unclassified_sources,
        "source_receipts": source_receipts,
        "source_receipts_digest": _digest(source_receipts),
        "expected_candidates": len(candidates),
        "discovered_candidates": len(candidates),
        "classified_candidates": len(candidates),
        "independently_reviewed_candidates": 0,
        "unresolved_candidates": len(candidates),
        "candidate_set_digest": _digest(candidates),
        "compiler_integrity_claims_expected": len(COMPILER_INTEGRITY_PREDICATES),
        "compiler_integrity_claims_classified": len(integrity_predicates),
        "compiler_integrity_claims_consequential": 0,
        "error_codes": list(_FIXED_PENDING_CODES),
    }
