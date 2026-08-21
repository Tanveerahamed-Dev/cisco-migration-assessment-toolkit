"""Fail-closed census for a bounded subset of curated consequential claims.

The census is field-atomic: one candidate is one completely classified field,
including an array or object when the rule classifies that field as a whole.
It deliberately does not claim sentence-level or rendered-sink completeness.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


CONTRACT_PATH = "master-reference/governance/consequential-claim-contract.json"
CONTRACT_SCHEMA_VERSION = "bounded-curated-consequential-claims/2"
CONTRACT_KIND = "bounded_curated_content_claim_denominator"
CONTENT_PATHS = (
    "master-reference/content/atlas-core.json",
    "master-reference/content/capability-catalog.json",
    "master-reference/content/delivery-governance.json",
    "master-reference/content/open-horizon-register.json",
    "master-reference/content/output-contract.json",
)
EXPECTED_SOURCE_COUNTS = {
    "master-reference/content/atlas-core.json": 155,
    "master-reference/content/capability-catalog.json": 426,
    "master-reference/content/delivery-governance.json": 969,
    "master-reference/content/open-horizon-register.json": 315,
    "master-reference/content/output-contract.json": 275,
}
EXPECTED_TOTAL_CANDIDATES = 2_140
# These values bind every semantic rule except the selected-commit Git blob OID.
# They are filled from and independently checked against the reviewed v2 spec.
EXPECTED_SOURCE_SPEC_DIGESTS = {
    "master-reference/content/atlas-core.json": "88945e355209ff0d42376c1fc5273f23729a21d5d82021f7c1ae63d38f65402e",
    "master-reference/content/capability-catalog.json": "ae20a8f8e43d41ff3e752366a7f4d822f839ad91735bd16bcce9fd7b336f0450",
    "master-reference/content/delivery-governance.json": "62b113259ea0bc532a3c76faa63c8ee55f20746dd928e17a29b380ca45c15d38",
    "master-reference/content/open-horizon-register.json": "5739641632a20c199cb3b12f57efb18825879c45dc0c2d8be22da6079c9c6d27",
    "master-reference/content/output-contract.json": "417d637ca609aed5e37c62004cc279618655c0c214ef4f61dab1db3b829d9084",
}
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
MAX_REFERENCE_ITEMS = 1_000
MAX_REFERENCE_LENGTH = 1_024
MAX_JSON_NUMBER_TOKEN_LENGTH = 128
MAX_PORTABLE_INTEGER = 9_007_199_254_740_991
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RULE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SELECTOR_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?$")
_CLASSIFICATIONS = frozenset(
    {
        "candidate",
        "container",
        "governance_metadata",
        "identifier_metadata",
        "label_metadata",
        "registry_metadata",
        "relationship_metadata",
    }
)
_VALUE_TYPES = frozenset(
    {
        "array",
        "baseline_value",
        "boolean",
        "integer",
        "null",
        "object",
        "string",
        "string_array",
        "string_array_allow_empty",
        "string_or_null",
        "unique_string_array",
        "unique_string_array_allow_empty",
    }
)
_FIXED_PENDING_CODES = (
    "consequential_claim_independent_review_pending",
    "consequential_claim_rendered_sink_universe_incomplete",
)
_NOT_DECLARED_REASON_CODES = frozenset(
    {
        "consequential_claim_contract_absent",
        "consequential_claim_contract_invalid",
        "consequential_claim_dirty_preview_not_eligible",
    }
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

    if (
        (source_commit is None) != (source_tree_digest is None)
        or (
            source_commit is not None
            and (not isinstance(source_commit, str) or _SOURCE_COMMIT.fullmatch(source_commit) is None)
        )
        or (
            source_tree_digest is not None
            and (not isinstance(source_tree_digest, str) or _DIGEST.fullmatch(source_tree_digest) is None)
        )
    ):
        raise ConsequentialClaimContractError(["consequential_claim_source_binding_invalid"])
    if not isinstance(reason_code, str) or reason_code not in _NOT_DECLARED_REASON_CODES:
        raise ConsequentialClaimContractError(["consequential_claim_contract_invalid"])

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


def _reject_float(_value: str) -> None:
    # The reviewed v2 curated-content grammar has integer-valued fields only.
    # Rejecting float syntax preserves JSON numeric-token identity across the
    # Python producer and JavaScript consumer instead of normalizing 1.0 to 1.
    raise _NumberOutsidePortableDomain


def _validate_json_bounds(value: Any) -> None:
    def string_is_portable(item: str) -> bool:
        return len(item) <= MAX_JSON_STRING_LENGTH and all(
            not (ord(character) <= 0x001F or 0x007F <= ord(character) <= 0x009F or 0xD800 <= ord(character) <= 0xDFFF)
            for character in item
        )

    stack: list[tuple[Any, int]] = [(value, 1)]
    values = 0
    while stack:
        current, depth = stack.pop()
        values += 1
        if values > MAX_JSON_VALUES or depth > MAX_JSON_DEPTH:
            raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
        if isinstance(current, dict):
            if len(current) > MAX_JSON_CONTAINER_ITEMS or any(not string_is_portable(key) for key in current):
                raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if len(current) > MAX_JSON_CONTAINER_ITEMS:
                raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str) and not string_is_portable(current):
            raise ConsequentialClaimContractError(["consequential_claim_json_structure_exceeds_bound"])


def _load_object(raw: bytes, code: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ConsequentialClaimContractError([code])
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite,
            parse_int=_parse_portable_int,
            parse_float=_reject_float,
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
    if type(raw) is not bytes or not isinstance(expected_oid, str):
        return ""
    material = f"blob {len(raw)}\0".encode("ascii") + raw
    if len(expected_oid) == 40:
        return hashlib.sha1(material, usedforsecurity=False).hexdigest()
    if len(expected_oid) == 64:
        return hashlib.sha256(material).hexdigest()
    return ""


def _rfc6901(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _value_matches(value: Any, expected: str) -> bool:
    if expected == "array":
        return isinstance(value, list)
    if expected == "baseline_value":
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value)
        if isinstance(value, dict):
            return bool(value) and all(
                isinstance(key, str)
                and bool(key.strip())
                and (
                    (isinstance(item, str) and bool(item.strip()))
                    or (type(item) is int)
                    or (
                        isinstance(item, list)
                        and bool(item)
                        and all(isinstance(member, str) and bool(member.strip()) for member in item)
                    )
                )
                for key, item in value.items()
            )
        return False
    if expected == "boolean":
        return type(value) is bool
    if expected == "integer":
        return type(value) is int
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str) and bool(value.strip())
    if expected == "string_array":
        return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    if expected == "string_array_allow_empty":
        return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
    if expected == "unique_string_array":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value)
            and len(value) == len(set(value))
        )
    if expected == "unique_string_array_allow_empty":
        return (
            isinstance(value, list)
            and all(isinstance(item, str) and item.strip() for item in value)
            and len(value) == len(set(value))
        )
    if expected == "string_or_null":
        return value is None or (isinstance(value, str) and bool(value.strip()))
    return False


def _validate_references(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_REFERENCE_ITEMS
        or any(not isinstance(item, str) or not item.strip() or len(item) > MAX_REFERENCE_LENGTH for item in value)
        or len(value) != len(set(value))
    ):
        raise ConsequentialClaimContractError(["consequential_claim_grounding_reference_invalid"])
    return value


def _records_for_selector(
    document: Mapping[str, Any], selector: list[str]
) -> list[tuple[dict[str, Any], str, tuple[dict[str, Any], ...]]]:
    rows: list[tuple[Any, str, tuple[dict[str, Any], ...]]] = [(document, "", ())]
    for token in selector:
        is_collection = token.endswith("[]")
        field = token[:-2] if is_collection else token
        next_rows: list[tuple[Any, str]] = []
        for current, pointer, ancestors in rows:
            if not isinstance(current, dict) or field not in current:
                raise ConsequentialClaimContractError(["consequential_claim_selector_structure_invalid"])
            selected = current[field]
            field_pointer = f"{pointer}/{_rfc6901(field)}"
            if is_collection:
                if not isinstance(selected, list):
                    raise ConsequentialClaimContractError(["consequential_claim_selector_structure_invalid"])
                next_rows.extend(
                    (item, f"{field_pointer}/{index}", (*ancestors, current)) for index, item in enumerate(selected)
                )
            else:
                next_rows.append((selected, field_pointer, (*ancestors, current)))
        rows = next_rows
    if any(not isinstance(item, dict) for item, _pointer, _ancestors in rows):
        raise ConsequentialClaimContractError(["consequential_claim_selector_structure_invalid"])
    return [(item, pointer, ancestors) for item, pointer, ancestors in rows if isinstance(item, dict)]


def _nonempty_distinct_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
        and len(value) == len(set(value))
    )


def _constraint_contract_is_valid(constraint: Any, field_rules: Mapping[str, Mapping[str, Any]]) -> bool:
    if not isinstance(constraint, dict) or not isinstance(constraint.get("kind"), str):
        return False
    kind = constraint["kind"]
    if kind == "const":
        return set(constraint) == {"kind", "field", "value"} and constraint.get("field") in field_rules
    if kind == "enum":
        return (
            set(constraint) == {"kind", "field", "values"}
            and constraint.get("field") in field_rules
            and _nonempty_distinct_strings(constraint.get("values"))
        )
    if kind == "integer_range":
        return (
            set(constraint) == {"kind", "field", "minimum", "maximum"}
            and constraint.get("field") in field_rules
            and type(constraint.get("minimum")) is int
            and type(constraint.get("maximum")) is int
            and constraint["minimum"] <= constraint["maximum"]
            and field_rules[constraint["field"]].get("value_type") == "integer"
        )
    if kind == "unique_field":
        return (
            set(constraint) == {"kind", "field"}
            and constraint.get("field") in field_rules
            and field_rules[constraint["field"]].get("required") is True
        )
    if kind == "contains_reference":
        return (
            set(constraint) == {"kind", "field", "reference"}
            and constraint.get("field") in field_rules
            and field_rules[constraint["field"]].get("classification") == "relationship_metadata"
            and isinstance(constraint.get("reference"), str)
            and bool(constraint["reference"].strip())
        )
    if kind == "root_const":
        return (
            set(constraint) == {"kind", "field", "value"}
            and isinstance(constraint.get("field"), str)
            and bool(constraint["field"].strip())
        )
    if kind == "reference_by_state":
        expected_keys = {
            "kind",
            "state_field",
            "owner_values",
            "owner_field",
            "gap_exempt_values",
            "gap_field",
        }
        state_field = constraint.get("state_field")
        owner_field = constraint.get("owner_field")
        gap_field = constraint.get("gap_field")
        return (
            set(constraint) == expected_keys
            and state_field in field_rules
            and owner_field in field_rules
            and gap_field in field_rules
            and _nonempty_distinct_strings(constraint.get("owner_values"))
            and _nonempty_distinct_strings(constraint.get("gap_exempt_values"))
            and field_rules[owner_field].get("classification") == "relationship_metadata"
            and field_rules[gap_field].get("classification") == "relationship_metadata"
        )
    if kind == "emptiness_by_enum":
        enum_field = constraint.get("enum_field")
        value_field = constraint.get("value_field")
        return (
            set(constraint) == {"kind", "enum_field", "value_field", "empty_values"}
            and enum_field in field_rules
            and value_field in field_rules
            and _nonempty_distinct_strings(constraint.get("empty_values"))
            and field_rules[value_field].get("value_type")
            in {"string_array_allow_empty", "unique_string_array_allow_empty"}
        )
    if kind == "nullability_by_enum":
        if set(constraint) != {"kind", "field", "cases"} or constraint.get("field") not in field_rules:
            return False
        cases = constraint.get("cases")
        if not isinstance(cases, list) or not cases:
            return False
        values: list[str] = []
        for case in cases:
            if not isinstance(case, dict) or set(case) != {"value", "null_fields", "non_null_fields"}:
                return False
            value = case.get("value")
            null_fields = case.get("null_fields")
            non_null_fields = case.get("non_null_fields")
            if (
                not isinstance(value, str)
                or not value.strip()
                or value in values
                or not isinstance(null_fields, list)
                or not isinstance(non_null_fields, list)
                or any(
                    not isinstance(field, str) or field not in field_rules for field in [*null_fields, *non_null_fields]
                )
                or len(null_fields) != len(set(null_fields))
                or len(non_null_fields) != len(set(non_null_fields))
                or set(null_fields) & set(non_null_fields)
                or any(
                    field_rules[field].get("value_type") != "string_or_null"
                    for field in [*null_fields, *non_null_fields]
                )
            ):
                return False
            values.append(value)
        return True
    return False


def _validate_record_constraints(
    document: Mapping[str, Any], record: Mapping[str, Any], constraints: list[Mapping[str, Any]]
) -> None:
    for constraint in constraints:
        kind = constraint["kind"]
        if kind == "const":
            valid = _digest(record.get(constraint["field"])) == _digest(constraint["value"])
        elif kind == "enum":
            valid = record.get(constraint["field"]) in constraint["values"]
        elif kind == "integer_range":
            value = record.get(constraint["field"])
            valid = type(value) is int and constraint["minimum"] <= value <= constraint["maximum"]
        elif kind == "unique_field":
            continue
        elif kind == "contains_reference":
            value = record.get(constraint["field"])
            valid = isinstance(value, list) and constraint["reference"] in value
        elif kind == "root_const":
            valid = _digest(document.get(constraint["field"])) == _digest(constraint["value"])
        elif kind == "reference_by_state":
            state = record.get(constraint["state_field"])
            owner_refs = record.get(constraint["owner_field"])
            gap_refs = record.get(constraint["gap_field"])
            owner_valid = state not in constraint["owner_values"] or bool(owner_refs)
            gap_valid = not gap_refs if state in constraint["gap_exempt_values"] else bool(gap_refs)
            valid = owner_valid and gap_valid
        elif kind == "emptiness_by_enum":
            enum_value = record.get(constraint["enum_field"])
            value = record.get(constraint["value_field"])
            valid = not value if enum_value in constraint["empty_values"] else bool(value)
        else:
            state = record.get(constraint["field"])
            case = next((item for item in constraint["cases"] if item["value"] == state), None)
            valid = case is not None and all(record.get(field) is None for field in case["null_fields"])
            valid = valid and all(record.get(field) is not None for field in case["non_null_fields"])
        if not valid:
            raise ConsequentialClaimContractError(["consequential_claim_semantic_constraint_failed"])


def _validate_rule_set_constraints(
    rows: list[tuple[dict[str, Any], str, tuple[dict[str, Any], ...]]],
    constraints: list[Mapping[str, Any]],
) -> None:
    for constraint in constraints:
        if constraint["kind"] != "unique_field":
            continue
        values = [_digest(record.get(constraint["field"])) for record, _pointer, _ancestors in rows]
        if len(values) != len(set(values)):
            raise ConsequentialClaimContractError(["consequential_claim_semantic_constraint_failed"])


def _validate_contract(contract: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
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
    all_rule_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            "path",
            "git_blob_oid",
            "classification",
            "expected_records",
            "expected_candidates",
            "grounding",
            "object_rules",
        }:
            errors.append("consequential_claim_source_entry_invalid")
            continue
        path = source.get("path")
        if not isinstance(path, str) or not path or path in source_by_path:
            errors.append("consequential_claim_source_path_duplicate_or_invalid")
            continue
        source_by_path[path] = source
        if source.get("classification") != "candidate_census":
            errors.append("consequential_claim_source_classification_unknown")
        if not isinstance(source.get("git_blob_oid"), str) or _SOURCE_COMMIT.fullmatch(source["git_blob_oid"]) is None:
            errors.append("consequential_claim_source_blob_identity_invalid")
        if source.get("expected_candidates") != EXPECTED_SOURCE_COUNTS.get(path):
            errors.append("consequential_claim_source_expected_candidates_invalid")
        grounding = source.get("grounding")
        if (
            not isinstance(grounding, dict)
            or set(grounding)
            != {
                "relationships",
                "declared_owner_fields",
                "fallback_owner_ref",
                "require_nonempty",
            }
            or not isinstance(grounding.get("relationships"), list)
            or not isinstance(grounding.get("declared_owner_fields"), list)
            or any(not isinstance(field, str) or not field for field in grounding.get("declared_owner_fields", []))
            or len(grounding.get("declared_owner_fields", [])) != len(set(grounding.get("declared_owner_fields", [])))
            or not isinstance(grounding.get("fallback_owner_ref"), str)
            or not grounding.get("fallback_owner_ref")
            or grounding.get("require_nonempty") is not True
        ):
            errors.append("consequential_claim_grounding_contract_invalid")
        relationships = grounding.get("relationships", []) if isinstance(grounding, dict) else []
        relationship_names: list[str] = []
        if isinstance(relationships, list):
            for relationship in relationships:
                if not isinstance(relationship, dict) or set(relationship) != {"field", "mode", "registry"}:
                    errors.append("consequential_claim_grounding_relationship_contract_invalid")
                    continue
                field_name = relationship.get("field")
                mode = relationship.get("mode")
                registry = relationship.get("registry")
                if (
                    not isinstance(field_name, str)
                    or not field_name
                    or field_name in relationship_names
                    or mode not in {"reference_array", "reference_scalar", "relation_scalar"}
                    or (mode in {"reference_array", "reference_scalar"} and not isinstance(registry, str))
                    or (mode == "relation_scalar" and registry is not None)
                ):
                    errors.append("consequential_claim_grounding_relationship_contract_invalid")
                else:
                    relationship_names.append(field_name)
        rules = source.get("object_rules")
        if not isinstance(rules, list) or not rules:
            errors.append("consequential_claim_object_rules_empty")
            continue
        candidate_total = 0
        record_total = 0
        classified_relationship_fields: dict[str, set[str]] = {}
        classified_declared_owner_fields: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {
                "rule_id",
                "selector",
                "record_kind",
                "identity",
                "expected_records",
                "fields",
                "constraints",
            }:
                errors.append("consequential_claim_object_rule_invalid")
                continue
            rule_id = rule.get("rule_id")
            if not isinstance(rule_id, str) or _RULE_ID.fullmatch(rule_id) is None or rule_id in all_rule_ids:
                errors.append("consequential_claim_rule_id_duplicate_or_invalid")
            else:
                all_rule_ids.add(rule_id)
            selector = rule.get("selector")
            if not isinstance(selector, list) or any(
                not isinstance(token, str) or _SELECTOR_TOKEN.fullmatch(token) is None for token in selector
            ):
                errors.append("consequential_claim_selector_invalid")
            identity = rule.get("identity")
            if not isinstance(identity, dict) or identity.get("kind") not in {
                "composite",
                "field",
                "parent_field",
                "root",
            }:
                errors.append("consequential_claim_identity_contract_invalid")
            elif identity.get("kind") == "root":
                if set(identity) != {"kind"}:
                    errors.append("consequential_claim_identity_contract_invalid")
            elif identity.get("kind") in {"field", "parent_field"}:
                if set(identity) != {"kind", "field"} or not isinstance(identity.get("field"), str):
                    errors.append("consequential_claim_identity_contract_invalid")
            elif (
                set(identity) != {"kind", "fields"}
                or not isinstance(identity.get("fields"), list)
                or not identity["fields"]
                or any(not isinstance(field, str) or not field for field in identity["fields"])
                or len(identity["fields"]) != len(set(identity["fields"]))
            ):
                errors.append("consequential_claim_identity_contract_invalid")
            expected_records = rule.get("expected_records")
            if type(expected_records) is not int or expected_records < 1:
                errors.append("consequential_claim_expected_records_invalid")
                expected_records = 0
            record_total += expected_records
            fields = rule.get("fields")
            names: list[str] = []
            if not isinstance(fields, list) or not fields:
                errors.append("consequential_claim_field_rules_empty")
                fields = []
            for field in fields:
                if not isinstance(field, dict) or set(field) != {
                    "field",
                    "classification",
                    "value_type",
                    "required",
                    "claim_kind",
                }:
                    errors.append("consequential_claim_field_rule_invalid")
                    continue
                name = field.get("field")
                if not isinstance(name, str) or not name or name in names:
                    errors.append("consequential_claim_field_rule_duplicate_or_invalid")
                else:
                    names.append(name)
                if field.get("classification") not in _CLASSIFICATIONS or field.get("value_type") not in _VALUE_TYPES:
                    errors.append("consequential_claim_field_rule_classification_invalid")
                if field.get("classification") == "candidate" and field.get("value_type") in {"array", "object"}:
                    errors.append("consequential_claim_candidate_value_type_too_generic")
                if type(field.get("required")) is not bool:
                    errors.append("consequential_claim_field_rule_required_invalid")
                if field.get("classification") == "candidate":
                    if not isinstance(field.get("claim_kind"), str) or _RULE_ID.fullmatch(field["claim_kind"]) is None:
                        errors.append("consequential_claim_field_claim_kind_invalid")
                elif field.get("claim_kind") is not None:
                    errors.append("consequential_claim_field_claim_kind_invalid")
                if field.get("classification") == "relationship_metadata" and isinstance(name, str):
                    classified_relationship_fields.setdefault(name, set()).add(str(field.get("value_type")))
                if isinstance(name, str) and name in grounding.get("declared_owner_fields", []):
                    classified_declared_owner_fields.add(name)
                if field.get("classification") == "candidate":
                    candidate_total += expected_records
            constraints = rule.get("constraints")
            if not isinstance(constraints, list):
                errors.append("consequential_claim_rule_constraints_invalid")
                constraints = []
            for constraint in constraints:
                if not _constraint_contract_is_valid(
                    constraint,
                    {
                        field["field"]: field
                        for field in fields
                        if isinstance(field, dict) and isinstance(field.get("field"), str)
                    },
                ):
                    errors.append("consequential_claim_rule_constraint_invalid")
            if isinstance(identity, dict):
                identity_fields = (
                    [identity.get("field")]
                    if identity.get("kind") == "field"
                    else identity.get("fields", [])
                    if identity.get("kind") == "composite"
                    else []
                )
                if any(field not in names for field in identity_fields):
                    errors.append("consequential_claim_identity_field_unclassified")
        if set(classified_relationship_fields) != set(relationship_names):
            errors.append("consequential_claim_grounding_relationship_coverage_invalid")
        if classified_declared_owner_fields != set(grounding.get("declared_owner_fields", [])):
            errors.append("consequential_claim_declared_owner_field_coverage_invalid")
        relationship_by_name = {
            item.get("field"): item
            for item in relationships
            if isinstance(item, dict) and isinstance(item.get("field"), str)
        }
        for field_name, value_types in classified_relationship_fields.items():
            mode = relationship_by_name.get(field_name, {}).get("mode")
            if (
                (
                    mode == "reference_array"
                    and not value_types <= {"unique_string_array", "unique_string_array_allow_empty"}
                )
                or (mode == "reference_scalar" and not value_types <= {"string", "string_or_null"})
                or (mode == "relation_scalar" and not value_types <= {"string", "string_or_null"})
            ):
                errors.append("consequential_claim_grounding_relationship_type_invalid")
        if source.get("expected_records") != record_total:
            errors.append("consequential_claim_source_expected_records_invalid")
        if source.get("expected_candidates") != candidate_total:
            errors.append("consequential_claim_source_candidate_rule_total_invalid")
        semantic_spec = {key: value for key, value in source.items() if key != "git_blob_oid"}
        if _digest(semantic_spec) != EXPECTED_SOURCE_SPEC_DIGESTS.get(path):
            errors.append("consequential_claim_source_semantic_spec_mismatch")
    if set(source_by_path) != set(CONTENT_PATHS):
        errors.append("consequential_claim_source_universe_membership_invalid")
    if sum(EXPECTED_SOURCE_COUNTS.values()) != EXPECTED_TOTAL_CANDIDATES:
        errors.append("consequential_claim_expected_candidate_constant_invalid")

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


def _collect_source_candidates(
    *,
    source_contract: Mapping[str, Any],
    document: Mapping[str, Any],
    source_oid: str,
    reference_registries: Mapping[str, frozenset[str]],
) -> tuple[list[dict[str, Any]], str]:
    path = str(source_contract["path"])
    candidates: list[dict[str, Any]] = []
    covered_objects: set[int] = set()
    rule_set = source_contract["object_rules"]
    grounding_contract = source_contract["grounding"]
    relationships = {item["field"]: item for item in grounding_contract["relationships"]}
    declared_owner_fields = set(grounding_contract["declared_owner_fields"])
    for rule in rule_set:
        rows = _records_for_selector(document, rule["selector"])
        if len(rows) != rule["expected_records"]:
            raise ConsequentialClaimContractError(["consequential_claim_record_count_mismatch"])
        field_rules = {field["field"]: field for field in rule["fields"]}
        identities: set[str] = set()
        for record, pointer, ancestors in rows:
            if id(record) in covered_objects:
                raise ConsequentialClaimContractError(["consequential_claim_object_rule_overlap"])
            covered_objects.add(id(record))
            required_fields = {name for name, field in field_rules.items() if field["required"]}
            if not required_fields <= set(record) or not set(record) <= set(field_rules):
                raise ConsequentialClaimContractError(["consequential_claim_object_field_unclassified"])
            identity_contract = rule["identity"]
            if identity_contract["kind"] == "root":
                semantic_identity = "@root"
            elif identity_contract["kind"] == "field":
                identity_value = record.get(identity_contract["field"])
                if not isinstance(identity_value, str) or not identity_value.strip():
                    raise ConsequentialClaimContractError(["consequential_claim_record_identity_invalid"])
                semantic_identity = identity_value
            elif identity_contract["kind"] == "parent_field":
                parent_value: Any = None
                for ancestor in reversed(ancestors):
                    if identity_contract["field"] in ancestor:
                        parent_value = ancestor[identity_contract["field"]]
                        break
                if not isinstance(parent_value, str) or not parent_value.strip():
                    raise ConsequentialClaimContractError(["consequential_claim_record_identity_invalid"])
                semantic_identity = parent_value
            else:
                identity_values = [record.get(field) for field in identity_contract["fields"]]
                if any(not isinstance(value, str) or not value.strip() for value in identity_values):
                    raise ConsequentialClaimContractError(["consequential_claim_record_identity_invalid"])
                semantic_identity = _digest(identity_values)
            identity_key = f"{rule['record_kind']}:{semantic_identity}"
            if identity_key in identities:
                raise ConsequentialClaimContractError(["consequential_claim_record_identity_duplicate"])
            identities.add(identity_key)
            grounding: list[dict[str, str]] = []
            for field_name, field_rule in sorted(field_rules.items()):
                if field_name not in record:
                    continue
                value = record[field_name]
                if not _value_matches(value, field_rule["value_type"]):
                    raise ConsequentialClaimContractError(["consequential_claim_field_value_type_invalid"])
                if field_rule["classification"] == "relationship_metadata":
                    relationship = relationships.get(field_name)
                    if relationship is None:
                        raise ConsequentialClaimContractError(["consequential_claim_grounding_field_unregistered"])
                    if relationship["mode"] == "reference_array":
                        references = _validate_references(value)
                    elif value is None and field_rule["value_type"] == "string_or_null":
                        references = []
                    elif isinstance(value, str) and value.strip():
                        references = [value]
                    else:
                        raise ConsequentialClaimContractError(["consequential_claim_grounding_reference_invalid"])
                    registry_name = relationship["registry"]
                    if registry_name is not None:
                        registry = reference_registries.get(registry_name)
                        if registry is None or any(reference not in registry for reference in references):
                            raise ConsequentialClaimContractError(["consequential_claim_grounding_reference_orphan"])
                    for reference in references:
                        grounding.append({"field": field_name, "reference": reference})
                elif field_name in declared_owner_fields:
                    if not isinstance(value, str) or not value.strip():
                        raise ConsequentialClaimContractError(["consequential_claim_declared_owner_invalid"])
                    grounding.append({"field": field_name, "reference": value})
            _validate_record_constraints(document, record, rule["constraints"])
            fallback_owner = grounding_contract["fallback_owner_ref"]
            if fallback_owner not in reference_registries["owner_refs"]:
                raise ConsequentialClaimContractError(["consequential_claim_grounding_fallback_owner_orphan"])
            if not grounding:
                grounding.append({"field": "@source_owner", "reference": fallback_owner})
            if grounding_contract["require_nonempty"] is True and not grounding:
                raise ConsequentialClaimContractError(["consequential_claim_grounding_empty"])
            grounding.sort(key=lambda item: (item["field"], item["reference"]))
            grounding_digest = _digest(grounding)
            for field_name, field_rule in sorted(field_rules.items()):
                if field_rule["classification"] != "candidate" or field_name not in record:
                    continue
                facet_identity = {
                    "source_path": path,
                    "rule_id": rule["rule_id"],
                    "record_kind": rule["record_kind"],
                    "record_identity": semantic_identity,
                    "facet_path": field_name,
                }
                candidates.append(
                    {
                        "facet_id": "urn:atlas:claim-facet:" + _digest(facet_identity),
                        "source_path": path,
                        "source_blob_oid": source_oid,
                        "source_pointer": f"{pointer}/{_rfc6901(field_name)}",
                        "rule_id": rule["rule_id"],
                        "record_kind": rule["record_kind"],
                        "record_identity": semantic_identity,
                        "facet_path": field_name,
                        "classification": "consequential_claim_candidate",
                        "claim_kind": field_rule["claim_kind"],
                        "review_state": "pending_independent_review",
                        "grounding_digest": grounding_digest,
                        "value_digest": _digest(record[field_name]),
                    }
                )
                if len(candidates) > MAX_CANDIDATES:
                    raise ConsequentialClaimContractError(["consequential_claim_candidate_denominator_exceeds_bound"])
        _validate_rule_set_constraints(rows, rule["constraints"])

    declared_children: set[int] = {id(document)}
    for rule in rule_set:
        field_rules = {field["field"]: field for field in rule["fields"]}
        for record, _pointer, _ancestors in _records_for_selector(document, rule["selector"]):
            for field_name, field_rule in field_rules.items():
                if field_rule["classification"] != "container" or field_name not in record:
                    continue
                value = record[field_name]
                if isinstance(value, dict):
                    declared_children.add(id(value))
                elif isinstance(value, list):
                    declared_children.update(id(item) for item in value if isinstance(item, dict))
    if covered_objects != declared_children:
        raise ConsequentialClaimContractError(["consequential_claim_object_rule_unused_or_incomplete"])
    if len(candidates) != source_contract["expected_candidates"]:
        raise ConsequentialClaimContractError(["consequential_claim_source_candidate_count_mismatch"])
    candidates.sort(key=lambda item: item["facet_id"])
    return candidates, _digest(rule_set)


def evaluate_bounded_curated_claim_census(
    *,
    contract_raw: bytes,
    contract_git_blob_oid: str,
    source_blobs: Mapping[str, tuple[str, bytes]],
    source_commit: str,
    source_tree_digest: str,
    compiler_claim_predicates: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return the exact summary and immutable payload-omitting review subjects.

    The subject records are addressability metadata, not review evidence.  Their
    ``review_state`` is part of the candidate-set identity and must never be
    mutated to represent an external verdict; authenticated verdicts belong in
    a separate, exact-subject join.
    """

    if (
        not isinstance(source_commit, str)
        or _SOURCE_COMMIT.fullmatch(source_commit) is None
        or not isinstance(source_tree_digest, str)
        or _DIGEST.fullmatch(source_tree_digest) is None
    ):
        raise ConsequentialClaimContractError(["consequential_claim_source_binding_invalid"])
    if type(contract_raw) is not bytes:
        raise ConsequentialClaimContractError(["consequential_claim_contract_malformed"])
    if (
        not isinstance(contract_git_blob_oid, str)
        or _SOURCE_COMMIT.fullmatch(contract_git_blob_oid) is None
        or len(contract_git_blob_oid) != len(source_commit)
    ):
        raise ConsequentialClaimContractError(["consequential_claim_contract_blob_identity_mismatch"])
    contract = _load_object(contract_raw, "consequential_claim_contract_malformed")
    if _git_blob_oid(contract_raw, contract_git_blob_oid) != contract_git_blob_oid:
        raise ConsequentialClaimContractError(["consequential_claim_contract_blob_identity_mismatch"])
    try:
        source_by_path, integrity_predicates = _validate_contract(contract)
    except ConsequentialClaimContractError:
        raise
    except (AttributeError, KeyError, OverflowError, RecursionError, TypeError, ValueError):
        raise ConsequentialClaimContractError(["consequential_claim_contract_invalid"]) from None
    if any(len(str(source["git_blob_oid"])) != len(source_commit) for source in source_by_path.values()):
        raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_invalid"])
    if not isinstance(source_blobs, Mapping) or set(source_blobs) != set(CONTENT_PATHS):
        raise ConsequentialClaimContractError(["consequential_claim_source_universe_membership_invalid"])
    if not isinstance(compiler_claim_predicates, (list, tuple)) or any(
        not isinstance(predicate, str) for predicate in compiler_claim_predicates
    ):
        raise ConsequentialClaimContractError(["consequential_claim_integrity_claim_set_mismatch"])
    if set(compiler_claim_predicates) != set(integrity_predicates) or len(compiler_claim_predicates) != len(
        set(compiler_claim_predicates)
    ):
        raise ConsequentialClaimContractError(["consequential_claim_integrity_claim_set_mismatch"])

    parsed_sources: dict[str, dict[str, Any]] = {}
    source_material: dict[str, tuple[str, bytes]] = {}
    for path in CONTENT_PATHS:
        material = source_blobs[path]
        if type(material) is not tuple or len(material) != 2:
            raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_invalid"])
        oid, raw = material
        if (
            not isinstance(oid, str)
            or _SOURCE_COMMIT.fullmatch(oid) is None
            or len(oid) != len(source_commit)
            or type(raw) is not bytes
        ):
            raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_invalid"])
        if _git_blob_oid(raw, oid) != oid:
            raise ConsequentialClaimContractError(["consequential_claim_source_blob_identity_mismatch"])
        source_contract = source_by_path[path]
        if oid != source_contract.get("git_blob_oid"):
            raise ConsequentialClaimContractError(["consequential_claim_source_contract_stale"])
        parsed_sources[path] = _load_object(raw, "consequential_claim_source_malformed")
        source_material[path] = (oid, raw)

    core = parsed_sources["master-reference/content/atlas-core.json"]
    capability = parsed_sources["master-reference/content/capability-catalog.json"]
    delivery = parsed_sources["master-reference/content/delivery-governance.json"]
    horizon = parsed_sources["master-reference/content/open-horizon-register.json"]
    output = parsed_sources["master-reference/content/output-contract.json"]
    try:
        registry_rows = {
            "owner_refs": [item["id"] for item in core["owners"]],
            "gap_refs": [item["id"] for item in delivery["gaps"]],
            "traffic_plane_refs": [item["id"] for item in core["traffic_model"]["planes"]],
            "system_plane_refs": [item["id"] for item in core["system_architecture"]["planes"]],
            "source_refs": [item["id"] for item in horizon["watch_families"]],
            "affected_capability_refs": [item["id"] for domain in capability["domains"] for item in domain["entries"]],
            "cross_artifact_ids": [item["id"] for item in output["members"]],
        }
    except (KeyError, TypeError):
        raise ConsequentialClaimContractError(["consequential_claim_grounding_registry_invalid"]) from None
    if any(
        not rows
        or any(not isinstance(item, str) or not item.strip() or len(item) > MAX_REFERENCE_LENGTH for item in rows)
        or len(rows) != len(set(rows))
        for rows in registry_rows.values()
    ):
        raise ConsequentialClaimContractError(["consequential_claim_grounding_registry_invalid"])
    reference_registries = {name: frozenset(rows) for name, rows in registry_rows.items()}

    source_receipts: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    for path in CONTENT_PATHS:
        oid, raw = source_material[path]
        source_contract = source_by_path[path]
        candidates, rule_set_digest = _collect_source_candidates(
            source_contract=source_contract,
            document=parsed_sources[path],
            source_oid=oid,
            reference_registries=reference_registries,
        )
        candidate_digest = _digest(candidates)
        source_receipts.append(
            {
                "path": path,
                "git_blob_oid": oid,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "classification": "candidate_census",
                "rule_set_digest": rule_set_digest,
                "candidate_count": len(candidates),
                "candidate_digest": candidate_digest,
            }
        )
        all_candidates.extend(candidates)

    facet_ids = [candidate["facet_id"] for candidate in all_candidates]
    if len(facet_ids) != len(set(facet_ids)):
        raise ConsequentialClaimContractError(["consequential_claim_candidate_facet_id_duplicate"])
    all_candidates.sort(key=lambda item: item["facet_id"])
    if len(all_candidates) != EXPECTED_TOTAL_CANDIDATES:
        raise ConsequentialClaimContractError(["consequential_claim_candidate_denominator_mismatch"])
    summary = {
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
        "source_universe_registered": len(CONTENT_PATHS),
        "source_universe_unclassified": 0,
        "source_receipts": source_receipts,
        "source_receipts_digest": _digest(source_receipts),
        "expected_candidates": EXPECTED_TOTAL_CANDIDATES,
        "discovered_candidates": len(all_candidates),
        "classified_candidates": len(all_candidates),
        "independently_reviewed_candidates": 0,
        "unresolved_candidates": len(all_candidates),
        "candidate_set_digest": _digest(all_candidates),
        "compiler_integrity_claims_expected": len(COMPILER_INTEGRITY_PREDICATES),
        "compiler_integrity_claims_classified": len(integrity_predicates),
        "compiler_integrity_claims_consequential": 0,
        "error_codes": list(_FIXED_PENDING_CODES),
    }
    return {"summary": summary, "candidates": all_candidates}


def evaluate_bounded_curated_claims(
    *,
    contract_raw: bytes,
    contract_git_blob_oid: str,
    source_blobs: Mapping[str, tuple[str, bytes]],
    source_commit: str,
    source_tree_digest: str,
    compiler_claim_predicates: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return the compatibility summary for the bounded curated census."""

    return evaluate_bounded_curated_claim_census(
        contract_raw=contract_raw,
        contract_git_blob_oid=contract_git_blob_oid,
        source_blobs=source_blobs,
        source_commit=source_commit,
        source_tree_digest=source_tree_digest,
        compiler_claim_predicates=compiler_claim_predicates,
    )["summary"]
