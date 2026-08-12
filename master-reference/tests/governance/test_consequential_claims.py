from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MASTER_REFERENCE.parent
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from governance.consequential_claims import (  # noqa: E402
    COMPILER_INTEGRITY_PREDICATES,
    CONTENT_PATHS,
    CONTRACT_PATH,
    ConsequentialClaimContractError,
    evaluate_bounded_curated_claims,
    unavailable_bounded_curated_claim_summary,
)
from release.content_bundle import CONTENT_FILES  # noqa: E402


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _git_blob_oid(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def _read_json(path: str) -> dict[str, Any]:
    value = json.loads((REPOSITORY_ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _fixture() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    contract = _read_json(CONTRACT_PATH)
    sources = {path: _read_json(path) for path in CONTENT_PATHS}
    return contract, sources


def _evaluate(
    contract: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    *,
    refresh_pins: bool = True,
    source_tuple_overrides: dict[str, tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    source_blobs: dict[str, tuple[str, bytes]] = {}
    for path in CONTENT_PATHS:
        raw = _canonical(sources[path])
        oid = _git_blob_oid(raw)
        source_blobs[path] = (oid, raw)
        if refresh_pins:
            next(item for item in contract["source_universe"] if item["path"] == path)["git_blob_oid"] = oid
    source_blobs.update(source_tuple_overrides or {})
    contract_raw = _canonical(contract)
    return evaluate_bounded_curated_claims(
        contract_raw=contract_raw,
        contract_git_blob_oid=_git_blob_oid(contract_raw),
        source_blobs=source_blobs,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
        compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
    )


def _evaluate_tracked() -> dict[str, Any]:
    contract_raw = (REPOSITORY_ROOT / CONTRACT_PATH).read_bytes()
    source_blobs: dict[str, tuple[str, bytes]] = {}
    for path in CONTENT_PATHS:
        raw = (REPOSITORY_ROOT / path).read_bytes()
        source_blobs[path] = (_git_blob_oid(raw), raw)
    return evaluate_bounded_curated_claims(
        contract_raw=contract_raw,
        contract_git_blob_oid=_git_blob_oid(contract_raw),
        source_blobs=source_blobs,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
        compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
    )


def _catalog(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return sources["master-reference/content/capability-catalog.json"]


def _first_entry(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _catalog(sources)["domains"][0]["entries"][0]


def _assert_code(expected: str, callback: Any) -> None:
    with pytest.raises(ConsequentialClaimContractError) as raised:
        callback()
    assert expected in raised.value.codes


def test_claim_source_universe_matches_curated_content_owner() -> None:
    assert CONTENT_PATHS == tuple(f"master-reference/content/{name}" for name in CONTENT_FILES)


def test_tracked_contract_schema_and_bounded_summary_are_nonvacuous() -> None:
    contract, sources = _fixture()
    schema = _read_json("master-reference/schema/consequential-claim-contract.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(contract)

    summary = _evaluate_tracked()

    assert summary["denominator_kind"] == "bounded_curated_content_claim_denominator"
    assert summary["state"] == "declared_incomplete"
    assert summary["closed"] is False
    assert summary["source_basis"] == "selected_commit_raw_git_blobs"
    assert summary["source_universe_expected"] == 5
    assert summary["source_universe_registered"] == 1
    assert summary["source_universe_unclassified"] == 4
    assert len(summary["source_receipts"]) == 5
    assert summary["expected_candidates"] > 0
    assert summary["expected_candidates"] == summary["discovered_candidates"]
    assert summary["classified_candidates"] == summary["discovered_candidates"]
    assert summary["unresolved_candidates"] == summary["discovered_candidates"]
    assert summary["compiler_integrity_claims_expected"] == 6
    assert summary["compiler_integrity_claims_classified"] == 6
    assert summary["compiler_integrity_claims_consequential"] == 0
    assert summary["error_codes"] == [
        "consequential_claim_independent_review_pending",
        "consequential_claim_source_universe_incomplete",
    ]
    for digest_field in (
        "contract_digest",
        "classification_digest",
        "source_receipts_digest",
        "candidate_set_digest",
    ):
        assert len(summary[digest_field]) == 64


@pytest.mark.parametrize(
    "reason_code",
    [
        "consequential_claim_contract_absent",
        "consequential_claim_contract_invalid",
        "consequential_claim_dirty_preview_not_eligible",
    ],
)
def test_not_declared_summary_is_exact_and_schema_valid(reason_code: str) -> None:
    summary = unavailable_bounded_curated_claim_summary(
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
        reason_code=reason_code,
    )
    assert summary["state"] == "not_declared"
    assert summary["closed"] is False
    assert summary["contract_git_blob_oid"] is None
    assert summary["contract_digest"] is None
    assert summary["classification_digest"] is None
    assert summary["source_universe_registered"] == 0
    assert summary["source_universe_unclassified"] == 5
    assert summary["source_receipts"] == []
    assert summary["source_receipts_digest"] is None
    assert summary["expected_candidates"] == 0
    assert summary["discovered_candidates"] == 0
    assert summary["classified_candidates"] == 0
    assert summary["independently_reviewed_candidates"] == 0
    assert summary["unresolved_candidates"] == 0
    assert summary["candidate_set_digest"] is None
    assert summary["compiler_integrity_claims_classified"] == 0
    assert summary["error_codes"] == sorted({reason_code, "consequential_claim_source_universe_incomplete"})

    ledger_schema = _read_json("master-reference/schema/completeness-ledger.schema.json")
    Draft202012Validator.check_schema(ledger_schema)
    focused_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": ledger_schema["$defs"],
        "$ref": "#/$defs/consequentialClaimDenominator",
    }
    Draft202012Validator(focused_schema).validate(summary)


def test_empty_duplicate_orphan_stale_unknown_and_unregistered_mutations_fail_closed() -> None:
    contract, sources = _fixture()
    _catalog(sources)["domains"] = []
    _assert_code("consequential_claim_candidate_collection_empty", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    entries = _catalog(sources)["domains"][0]["entries"]
    entries.append(copy.deepcopy(entries[0]))
    _assert_code("consequential_claim_candidate_id_duplicate_or_invalid", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    _first_entry(sources)["owner_refs"] = []
    _first_entry(sources)["gap_refs"] = []
    _assert_code("consequential_claim_candidate_owner_orphan", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    raw = _canonical(_catalog(sources)) + b" "
    path = "master-reference/content/capability-catalog.json"
    stale_override = {path: (_git_blob_oid(raw), raw)}
    _assert_code(
        "consequential_claim_source_contract_stale",
        lambda: _evaluate(contract, sources, source_tuple_overrides=stale_override),
    )

    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census["facets"][0]["classification"] = "unknown"
    _assert_code("consequential_claim_facet_classification_unknown", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    _first_entry(sources)["SENSITIVE_CANARY"] = "do-not-echo"
    with pytest.raises(ConsequentialClaimContractError) as raised:
        _evaluate(contract, sources)
    assert raised.value.codes == ("consequential_claim_candidate_field_unregistered",)
    assert "SENSITIVE_CANARY" not in str(raised.value)
    assert "do-not-echo" not in str(raised.value)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("root", "consequential_claim_catalog_root_field_unregistered"),
        ("domain", "consequential_claim_candidate_collection_malformed"),
    ],
)
def test_root_and_domain_selector_surfaces_are_exactly_registered(location: str, expected: str) -> None:
    contract, sources = _fixture()
    target = _catalog(sources) if location == "root" else _catalog(sources)["domains"][0]
    target["new_surface"] = "opaque"
    _assert_code(expected, lambda: _evaluate(contract, sources))


@pytest.mark.parametrize(
    "invalid_references",
    [
        "not-a-list",
        [""],
        ["\u001c"],
        [7],
        ["duplicate", "duplicate"],
        ["x" * 1_025],
        [f"owner-{index}" for index in range(1_001)],
    ],
)
def test_present_owner_reference_lists_are_strict_and_bounded(invalid_references: Any) -> None:
    contract, sources = _fixture()
    _first_entry(sources)["owner_refs"] = invalid_references
    _assert_code("consequential_claim_candidate_owner_reference_invalid", lambda: _evaluate(contract, sources))


@pytest.mark.parametrize("invalid_value", [None, True, 7, "", "   ", "\u001c"])
def test_candidate_facets_are_nonblank_strings(invalid_value: Any) -> None:
    contract, sources = _fixture()
    _first_entry(sources)["current_scope"] = invalid_value
    _assert_code("consequential_claim_candidate_value_invalid", lambda: _evaluate(contract, sources))


def test_owner_reference_field_registry_matches_schema_bounds() -> None:
    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census["owner_reference_fields"] = [f"owner_{index}" for index in range(9)]
    _assert_code("consequential_claim_owner_reference_fields_invalid", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census["owner_reference_fields"] = ["x" * 129]
    _assert_code("consequential_claim_owner_reference_fields_invalid", lambda: _evaluate(contract, sources))


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("root_fields", "consequential_claim_root_fields_classification_mismatch"),
        ("domain_fields", "consequential_claim_domain_fields_classification_mismatch"),
        ("excluded_fields", "consequential_claim_excluded_fields_classification_mismatch"),
    ],
)
def test_field_classification_contract_is_exact(key: str, expected: str) -> None:
    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census[key][0]["classification"] = "identifier_metadata"
    _assert_code(expected, lambda: _evaluate(contract, sources))


def test_owner_fields_and_facets_are_exact_contract_memberships() -> None:
    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census["owner_reference_fields"] = ["owner_refs"]
    _assert_code("consequential_claim_owner_reference_fields_mismatch", lambda: _evaluate(contract, sources))

    contract, sources = _fixture()
    census = next(item for item in contract["source_universe"] if item["classification"] == "candidate_census")
    census["facets"][0]["field"] = "renamed_state"
    _assert_code("consequential_claim_facets_mismatch", lambda: _evaluate(contract, sources))


def test_raw_blob_identity_duplicate_keys_and_nesting_are_checked() -> None:
    contract, sources = _fixture()
    path = "master-reference/content/capability-catalog.json"
    raw = _canonical(_catalog(sources)) + b" "
    original_oid = _git_blob_oid(_canonical(_catalog(sources)))
    _assert_code(
        "consequential_claim_source_blob_identity_mismatch",
        lambda: _evaluate(
            contract,
            sources,
            source_tuple_overrides={path: (original_oid, raw)},
        ),
    )

    duplicate_raw = b'{"schema_version":"one","schema_version":"two"}'
    with pytest.raises(ConsequentialClaimContractError) as duplicate:
        evaluate_bounded_curated_claims(
            contract_raw=duplicate_raw,
            contract_git_blob_oid=_git_blob_oid(duplicate_raw),
            source_blobs={},
            source_commit="a" * 40,
            source_tree_digest="b" * 64,
            compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
        )
    assert duplicate.value.codes == ("consequential_claim_json_duplicate_key",)

    deep_raw = b'{"x":' * 70 + b"0" + b"}" * 70
    with pytest.raises(ConsequentialClaimContractError) as deep:
        evaluate_bounded_curated_claims(
            contract_raw=deep_raw,
            contract_git_blob_oid=_git_blob_oid(deep_raw),
            source_blobs={},
            source_commit="a" * 40,
            source_tree_digest="b" * 64,
            compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
        )
    assert deep.value.codes == ("consequential_claim_json_structure_exceeds_bound",)

    unsafe_integer_raw = b'{"x":9007199254740992}'
    with pytest.raises(ConsequentialClaimContractError) as unsafe_integer:
        evaluate_bounded_curated_claims(
            contract_raw=unsafe_integer_raw,
            contract_git_blob_oid=_git_blob_oid(unsafe_integer_raw),
            source_blobs={},
            source_commit="a" * 40,
            source_tree_digest="b" * 64,
            compiler_claim_predicates=sorted(COMPILER_INTEGRITY_PREDICATES),
        )
    assert unsafe_integer.value.codes == ("consequential_claim_json_number_outside_portable_domain",)
