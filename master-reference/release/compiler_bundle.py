"""Strict reader for whole-repository compiler output."""

from __future__ import annotations

import math
import re
import struct
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from compiler.graphify import (
    CONTROLLED_GRAPH_FILE_TYPES,
    CONTROLLED_GRAPH_KINDS,
    CONTROLLED_GRAPH_LANGUAGES,
    CONTROLLED_GRAPH_RELATIONS,
    GRAPH_EDGE_UNRESOLVED_REASON_ORDER,
    GRAPH_EDGE_UNRESOLVED_REASONS,
    GRAPH_NODE_UNRESOLVED_REASON_ORDER,
    GRAPH_NODE_UNRESOLVED_REASONS,
    MAX_GRAPH_SOURCE_LOCATION_LENGTH,
    GraphifyFailure,
    OPAQUE_IDENTIFIER_POLICY,
    validate_graphify_metadata,
)
from compiler.compiler import RECORD_GROUPS

from .model import (
    ReleaseInputError,
    canonical_json,
    digest_object,
    safe_input,
    safe_relative,
    sha256_bytes,
    stable_id,
)


COMPILER_SCHEMA_VERSION = "1.1.0"
REQUIRED_STRUCTURAL_INVARIANTS = frozenset(
    {
        "every_safe_parsed_source_has_one_structural_root",
        "every_safe_line_structurally_mapped",
        "every_gui_surface_has_standardized_evidence_honest_dossier",
    }
)
REQUIRED_ACCEPTANCE_GATES = frozenset(
    {
        "architecture_contract_declared_and_conformant",
        "runtime_architecture_edges_observed_and_reconciled",
        "every_symbol_has_dossier_fields",
        "every_gui_surface_has_standardized_evidence_honest_dossier",
        "every_safe_line_behaviorally_explained",
        "every_critical_or_public_symbol_level_four_reviewed",
        "exact_clean_commit_binding",
        "every_binary_has_format_aware_privacy_review",
        "runtime_trace_evidence_joined_to_source_records",
        "consequential_claim_denominator_closed",
        "bitemporal_event_ledger_populated_and_replayable",
        "release_lifecycle_transitions_integrated_and_receipted",
    }
)
GUI_DOSSIER_FIELDS = frozenset(
    {
        "persona_journey",
        "data_snapshot_sources",
        "props_contract",
        "state_model",
        "loading_empty_error_unknown_stale_states",
        "user_actions",
        "accessibility",
        "responsive_behavior",
        "design_tokens",
        "white_label_inputs",
        "design_sync_receipt",
        "visual_baseline",
        "tests",
        "downstream_consumers",
        "known_gaps",
    }
)
GRAPH_IDENTIFIER_POLICY = OPAQUE_IDENTIFIER_POLICY
_GRAPH_FILE_TYPES = CONTROLLED_GRAPH_FILE_TYPES | {""}
_GRAPH_LANGUAGES = CONTROLLED_GRAPH_LANGUAGES | {""}
_GRAPH_KINDS = CONTROLLED_GRAPH_KINDS | {""}
_GRAPH_DIGEST = re.compile(r"[0-9a-f]{64}")
_GRAPH_GIT_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_GRAPH_LOCATION = re.compile(r"(?:L?\d+(?::\d+)?(?:-L?\d+(?::\d+)?)?)?")
_LOCAL_SCAN_MAX_STRING_BYTES = 8 * 1024 * 1024
_LOCAL_SCAN_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_LOCAL_SCAN_MAX_VALUES = 5_000_000
_MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_COMPILER_JSON_BYTES = 32 * 1024 * 1024
_MAX_COMPILER_CHUNK_BYTES = 2 * 1024 * 1024 * 1024
_GENERIC_AUTOMATION_USERS = frozenset({"actions", "agent", "build", "builder", "codex", "github", "root", "runner"})
_GENERIC_WINDOWS_USER_HOME = re.compile(
    r"(?:^|[^a-z0-9])(?:[a-z]:|[\\/]{2,}[^\\/\r\n]+)[\\/]+users[\\/]+[^\\/\x00-\x1f<>:\"|?*']{1,128}(?=[\\/]|$|[\"'])"
)
_GENERIC_POSIX_USER_HOME = re.compile(r"(?:^|[^a-z0-9])/(?:home|users)/[^/\x00-\x1f\"']{1,128}(?=/|$|[\"'])")
_GENERIC_COLLAPSED_USER_HOME = re.compile(
    r"(?:^|_)(?:[a-z]_users|home|users)_[a-z0-9][a-z0-9_]{0,127}_"
    r"(?:appdata|build|cache|checkout|checkouts|code|config|desktop|documents|downloads|git|onedrive|project|projects|repo|repos|source|src|work|workspace)(?:_|$)"
)


REQUIRED_GROUPS = frozenset(RECORD_GROUPS)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "release_class",
        "source_commit",
        "head_tree_oid",
        "index_digest",
        "source_tree_digest",
        "tracked_worktree_dirty",
        "chunk_size",
        "groups",
        "completeness",
        "graphify_metadata",
        "architecture_conformance",
    }
)
_FILE_RECEIPT_KEYS = frozenset({"path", "sha256", "bytes"})
_GROUP_RECEIPT_KEYS = frozenset({"record_count", "chunk_count", "records_digest", "chunks"})
_CHUNK_RECEIPT_KEYS = frozenset({"path", "record_count", "sha256", "bytes"})
_CHUNK_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "source_commit",
        "source_tree_digest",
        "chunk_index",
        "chunk_count",
        "record_count",
        "records_digest",
        "records",
    }
)
_MAX_RECORD_ID_LENGTH = 4_096
_GRAPH_NODE_KEYS = frozenset(
    {
        "id",
        "graphify_id",
        "coordinate_occurrence",
        "file_id",
        "source_file",
        "source_location",
        "label",
        "file_type",
        "language",
        "kind",
        "community",
        "origin",
        "extraction_mode",
        "entity_type",
        "unresolved_reasons",
    }
)
_GRAPH_EDGE_KEYS = frozenset(
    {
        "id",
        "source",
        "target",
        "relation",
        "coordinate_occurrence",
        "source_file",
        "source_location",
        "extraction_mode",
        "confidence",
        "entity_type",
        "unresolved_reasons",
    }
)
_RECORD_KEY_TEXT_BY_GROUP = {
    "binaries": "content_digest entity_type file_id git_blob_oid id inspection_mode media_type path privacy_exposure size_bytes unresolved_reasons",
    "calls": "callee containing_symbol entity_type extraction_disposition file_id id path range resolved statement_digest tests unresolved_reasons",
    "claims": "basis confidence conflicts_with current_view denominator derived_from effective_time entity_type evidence_class evidence_ids extraction_mode freshness id lineage origin owner predicate recorded_time revocation_reason revoked_by satisfies_evidence_requirement scope source_commit status subject temporal_basis transformation unit unresolved_reasons value verdict",
    "components": "attribute_names attributes_digest component_role detection entity_type exported extraction_disposition file_id framework gui_dossier handler id kind method name path range route self_closing tag_name unresolved_reasons",
    "configs": "content_digest entity_type file_id id language path roles",
    "datasets": "content_digest entity_type file_id format id path size_bytes structured_record_count",
    "dependencies": "constraint ecosystem entity_type file_id id name path resolved_version scope",
    "documents": "entity_type file_id id line_count path status status_reasons title",
    "files": "classification_errors content_digest content_source documentation_status documentation_status_reasons entity_type git_blob_oid git_mode git_stage id language line_count media_type nonblank_line_count parse_status parser parser_mode parser_version path privacy_exposure privacy_reasons roles size_bytes unresolved_reasons",
    "graph_edges": "confidence coordinate_occurrence entity_type extraction_mode id relation source source_file source_location target unresolved_reasons",
    "graph_nodes": "community coordinate_occurrence entity_type extraction_mode file_id file_type graphify_id id kind label language origin source_file source_location unresolved_reasons",
    "imports": "alias containing_symbol entity_type file_id id kind module names path range unresolved_reasons",
    "lines": "GUI_or_artifact_consumers behavior_group callers_and_dependencies claims_influenced containing_symbol current_or_historical depth entity_type explanation_depth file_id id inputs_and_outputs language line line_digest line_number owner path runtime_trace_state security_and_privacy_effect semantic_entity source_commit structural_mapping_basis syntax_depth syntax_kind test_coverage_state tests_covering_it text_bytes text_digest text_preview unresolved_reasons",
    "manifests": "content_digest dependency_count entity_type file_id id kind language path",
    "markdown": "authority_classification containing_heading documentation_status entity_type file_id heading id kind level line path target text",
    "routes": "attribute_names entity_type file_id framework gui_dossier handler id kind method name path range route unresolved_reasons",
    "source_text": "byte_count content_digest encoding entity_type file_id git_blob_oid id line_count lines path source_basis",
    "structural_entities": "content_digest entity_type explanation_depth extraction_disposition file_id generation_provenance git_blob_oid id kind language line_count name nonblank_line_count parser parser_mode parser_owned parser_version path range range_state roles root_scope source_basis uncertainty unresolved_reasons",
    "structured": "cell_count data_row_count depth entity_type extraction_disposition file_id id key name path pointer range row_accounting_state row_count_including_header row_index unresolved_reasons value_digest value_preview value_type",
    "symbols": "abstention_behavior callees caller_resolution callers claims_produced_or_consumed constant_basis constant_candidate criticality data_dependencies declaration_kind decorators depth digest documentation downstream_surfaces entity_type explanation_depth exported external_effects extraction_disposition failure_and_exception_behavior file_id framework_candidate history id kind known_impact_if_changed language limitations name parameters parameters_and_types path path_and_range performance_characteristics purpose purpose_basis qualified_name range responsibility return_annotation return_or_output review_state runtime_trace_evidence runtime_trace_state security_boundary stable_urn state_read state_written target test_linkage tests unresolved_reasons",
    "tests": "assertion_count assertion_group_id assertions entity_type extraction_disposition file_id framework id name path range unresolved_reasons",
    "workflows": "access action artifact_ids artifacts declared_path direction entity_type extraction_disposition file_id id job job_ids jobs name parser_mode path permission_ids permissions range run_declared scope source_digest step_id step_ids step_index steps triggers unresolved_reasons uses",
}
_RECORD_KEYS_BY_GROUP = {group: frozenset(keys.split()) for group, keys in _RECORD_KEY_TEXT_BY_GROUP.items()}
if set(_RECORD_KEYS_BY_GROUP) != REQUIRED_GROUPS:
    raise RuntimeError("compiler record-field registry is stale")


@lru_cache(maxsize=1)
def _compiler_record_validator() -> Any:
    import json

    from jsonschema import Draft202012Validator

    schema_path = Path(__file__).resolve().parent.parent / "schema" / "atlas-records.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8", errors="strict"))
    schema_registry: dict[str, frozenset[str]] = {}
    for condition in schema.get("allOf", []):
        group = condition.get("if", {}).get("properties", {}).get("record_type", {}).get("const")
        reference = condition.get("then", {}).get("properties", {}).get("records", {}).get("items", {}).get("$ref")
        if not isinstance(group, str) or not isinstance(reference, str) or not reference.endswith("RecordKeyFence"):
            continue
        definition_name = reference.rsplit("/", maxsplit=1)[-1]
        allowed = schema.get("$defs", {}).get(definition_name, {}).get("propertyNames", {}).get("enum")
        if isinstance(allowed, list) and all(isinstance(item, str) for item in allowed):
            schema_registry[group] = frozenset(allowed)
    if schema_registry != _RECORD_KEYS_BY_GROUP:
        raise RuntimeError("compiler record-field registry differs from tracked schema")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_chunk_against_tracked_schema(
    envelope: dict[str, Any],
    group_name: str,
    chunk_index: int,
) -> None:
    try:
        _compiler_record_validator().validate(envelope)
    except Exception:
        raise ReleaseInputError(
            f"compiler chunk differs from tracked record schema: group={group_name}; index={chunk_index}"
        ) from None


def _valid_graph_location(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) <= MAX_GRAPH_SOURCE_LOCATION_LENGTH
        and (
            value == ""
            or (
                _GRAPH_LOCATION.fullmatch(value) is not None
                and all(1 <= int(component) <= _MAX_JS_SAFE_INTEGER for component in re.findall(r"\d+", value))
            )
        )
    )


def _collapsed_ascii_identity(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def _local_identity_contract(repository_root: Path) -> dict[str, tuple[str, ...]]:
    root = repository_root.resolve(strict=True)
    native_root = str(root)
    slash_root = native_root.replace("\\", "/")
    path_parts = [part for part in slash_root.split("/") if part]
    home_end: int | None = None
    for index, part in enumerate(path_parts[:-1]):
        if part.casefold() in {"home", "users"}:
            home_end = index + 2
            break
    home_path = "/".join(path_parts[:home_end]) if home_end is not None else ""
    user = path_parts[home_end - 1] if home_end is not None else ""

    def exact_variants(value: str) -> tuple[str, ...]:
        if not value:
            return ()
        folded = unicodedata.normalize("NFKC", value).casefold()
        return tuple(
            sorted(
                {
                    folded,
                    folded.replace("\\", "/"),
                    folded.replace("/", "\\"),
                }
            )
        )

    def collapsed_variants(value: str) -> tuple[str, ...]:
        collapsed = _collapsed_ascii_identity(value)
        return (collapsed,) if len(collapsed) >= 8 else ()

    user_folded = unicodedata.normalize("NFKC", user).casefold()
    users = (user_folded,) if len(user_folded) >= 3 and user_folded not in _GENERIC_AUTOMATION_USERS else ()
    return {
        "repository_exact": exact_variants(native_root),
        "repository_collapsed": collapsed_variants(native_root),
        "home_exact": exact_variants(home_path),
        "home_collapsed": collapsed_variants(home_path),
        "users": users,
    }


def _current_local_identity_rule(value: str, contract: dict[str, tuple[str, ...]]) -> str | None:
    folded = unicodedata.normalize("NFKC", value).casefold()
    if any(marker in folded for marker in contract["repository_exact"]):
        return "local_repository_path"
    if any(marker in folded for marker in contract["home_exact"]):
        return "local_home_path"
    collapsed = _collapsed_ascii_identity(folded)
    if any(marker in collapsed for marker in contract["repository_collapsed"]):
        return "local_repository_collapsed_path"
    if any(marker in collapsed for marker in contract["home_collapsed"]):
        return "local_home_collapsed_path"
    for user in contract["users"]:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])", folded):
            return "local_user_identity_component"
    return None


def _generic_home_identity_rule(value: str) -> str | None:
    folded = unicodedata.normalize("NFKC", value).casefold()
    collapsed = _collapsed_ascii_identity(folded)
    if _GENERIC_WINDOWS_USER_HOME.search(folded):
        return "generic_windows_user_home_path"
    if _GENERIC_POSIX_USER_HOME.search(folded):
        return "generic_posix_user_home_path"
    if _GENERIC_COLLAPSED_USER_HOME.search(collapsed):
        return "generic_collapsed_user_home_path"
    return None


def _local_identity_rule(value: str, contract: dict[str, tuple[str, ...]]) -> str | None:
    return _current_local_identity_rule(value, contract) or _generic_home_identity_rule(value)


def _scan_generated_local_identities(
    graphify: dict[str, Any],
    completeness: dict[str, Any],
    architecture: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    repository_root: Path,
) -> None:
    contract = _local_identity_contract(repository_root)
    scanned_values = 0
    scanned_bytes = 0
    roots: tuple[tuple[str, Any, bool], ...] = (
        ("graphify-metadata", graphify, True),
        ("completeness", completeness, True),
        ("architecture-conformance", architecture, True),
        *(
            (f"{group_name}[{index}]", record, True)
            for group_name in ("graph_nodes", "graph_edges")
            for index, record in enumerate(records.get(group_name, []))
        ),
    )
    for location, root_value, scan_generic in roots:
        pending = [root_value]
        while pending:
            value = pending.pop()
            scanned_values += 1
            if scanned_values > _LOCAL_SCAN_MAX_VALUES:
                raise ReleaseInputError(f"compiler Graphify local-identity scan value budget exceeded: path={location}")
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
                continue
            if isinstance(value, (list, tuple)):
                pending.extend(value)
                continue
            if not isinstance(value, str):
                continue
            try:
                encoded_bytes = len(value.encode("utf-8", errors="strict"))
                rule = _current_local_identity_rule(value, contract)
                if rule is None and scan_generic:
                    rule = _generic_home_identity_rule(value)
            except (UnicodeError, ValueError):
                raise ReleaseInputError(
                    f"compiler Graphify local-identity scan found an invalid string: path={location}"
                ) from None
            if encoded_bytes > _LOCAL_SCAN_MAX_STRING_BYTES:
                raise ReleaseInputError(
                    f"compiler Graphify local-identity scan string budget exceeded: path={location}"
                )
            scanned_bytes += encoded_bytes
            if scanned_bytes > _LOCAL_SCAN_MAX_TOTAL_BYTES:
                raise ReleaseInputError(f"compiler Graphify local-identity scan byte budget exceeded: path={location}")
            if rule is not None:
                raise ReleaseInputError(f"compiler Graphify local-identity scan failed: rule={rule}; path={location}")


def _validate_graph_projection(
    graphify: dict[str, Any],
    records: dict[str, list[dict[str, Any]]],
    source_commit: str,
) -> None:
    nodes = records.get("graph_nodes", [])
    edges = records.get("graph_edges", [])
    if graphify.get("available") is not True:
        try:
            validate_graphify_metadata(graphify, nodes, edges)
        except (AttributeError, GraphifyFailure, OverflowError, RecursionError, TypeError, ValueError):
            raise ReleaseInputError("compiler Graphify metadata receipt is inconsistent") from None
        if nodes or edges:
            raise ReleaseInputError("unavailable compiler Graphify receipt carries projected records")
        return
    built_at_commit = graphify.get("built_at_commit")
    if (
        "built_at_commit" not in graphify
        or (built_at_commit is not None and not isinstance(built_at_commit, str))
        or (isinstance(built_at_commit, str) and _GRAPH_GIT_OID.fullmatch(built_at_commit) is None)
        or built_at_commit != source_commit
        or graphify.get("stale") is not False
        or graphify.get("status") != "current"
    ):
        raise ReleaseInputError("compiler Graphify built commit disposition is absent or inconsistent")
    try:
        validate_graphify_metadata(graphify, nodes, edges)
    except (AttributeError, GraphifyFailure, OverflowError, RecursionError, TypeError, ValueError):
        raise ReleaseInputError("compiler Graphify exclusion disposition ledger is inconsistent") from None
    counts = graphify.get("node_identifier_disposition_counts")
    expected_keys = {
        "total",
        "projected_repository_relative",
        "excluded_opaque",
        "raw_published",
    }
    if (
        graphify.get("identifier_projection_policy") != GRAPH_IDENTIFIER_POLICY
        or not isinstance(counts, dict)
        or set(counts) != expected_keys
        or any(type(counts.get(key)) is not int or counts[key] < 0 for key in expected_keys)
        or type(graphify.get("total_nodes")) is not int
        or type(graphify.get("projected_nodes")) is not int
        or type(graphify.get("excluded_nodes")) is not int
        or type(graphify.get("total_edges")) is not int
        or type(graphify.get("projected_edges")) is not int
        or type(graphify.get("excluded_edges")) is not int
        or graphify["total_nodes"] < 0
        or graphify["projected_nodes"] < 0
        or graphify["excluded_nodes"] < 0
        or graphify["total_edges"] < 0
        or graphify["projected_edges"] < 0
        or graphify["excluded_edges"] < 0
        or counts["total"] != graphify["total_nodes"]
        or counts["projected_repository_relative"] != len(nodes)
        or counts["projected_repository_relative"] != graphify["projected_nodes"]
        or counts["excluded_opaque"] != graphify["excluded_nodes"]
        or counts["raw_published"] != 0
        or counts["projected_repository_relative"] + counts["excluded_opaque"] != counts["total"]
        or graphify["projected_edges"] != len(edges)
        or graphify["projected_nodes"] + graphify["excluded_nodes"] != graphify["total_nodes"]
        or graphify["projected_edges"] + graphify["excluded_edges"] != graphify["total_edges"]
    ):
        raise ReleaseInputError("compiler Graphify identifier disposition receipt is absent or inconsistent")
    files_by_path = {item.get("path"): item for item in records.get("files", []) if isinstance(item.get("path"), str)}
    node_ids: set[str] = set()
    projected_identifiers: set[str] = set()
    node_coordinate_occurrences: dict[tuple[str, str], set[int]] = {}
    projected_community_node_counts: dict[int, int] = {}
    for node in nodes:
        if set(node) != _GRAPH_NODE_KEYS:
            raise ReleaseInputError("compiler Graphify node shape is not canonical")
        identifier = node.get("id")
        projected = node.get("graphify_id")
        source_file = node.get("source_file")
        file_record = files_by_path.get(source_file)
        source_location = node.get("source_location")
        coordinate_occurrence = node.get("coordinate_occurrence")
        kind = node.get("kind")
        origin = node.get("origin")
        kind_is_controlled = isinstance(kind, str) and kind in _GRAPH_KINDS
        origin_is_controlled = isinstance(origin, str) and origin in {
            "ast",
            "curated",
            "undisclosed",
        }
        expected_label = (
            f"{source_file}:{source_location or 'source'}#{coordinate_occurrence + 1}"
            if isinstance(source_file, str) and isinstance(source_location, str) and type(coordinate_occurrence) is int
            else None
        )
        expected_extraction_mode = (
            {
                "ast": "extracted",
                "curated": "curated",
                "undisclosed": "undisclosed",
            }.get(origin)
            if origin_is_controlled
            else None
        )
        expected_entity_type = f"graph_node{f'_{kind}' if kind else ''}" if kind_is_controlled else None
        unresolved_reasons = node.get("unresolved_reasons")
        if (
            not isinstance(identifier, str)
            or not isinstance(projected, str)
            or _GRAPH_DIGEST.fullmatch(projected) is None
            or identifier in node_ids
            or projected in projected_identifiers
            or not isinstance(source_file, str)
            or not isinstance(file_record, dict)
            or file_record.get("privacy_exposure") != "full"
            or file_record.get("classification_errors") != []
            or node.get("file_id") != file_record.get("id")
            or not _valid_graph_location(source_location)
            or type(coordinate_occurrence) is not int
            or coordinate_occurrence < 0
            or node.get("label") != expected_label
            or not isinstance(node.get("file_type"), str)
            or node.get("file_type") not in _GRAPH_FILE_TYPES
            or not isinstance(node.get("language"), str)
            or node.get("language") not in _GRAPH_LANGUAGES
            or not kind_is_controlled
            or not origin_is_controlled
            or node.get("extraction_mode") != expected_extraction_mode
            or node.get("entity_type") != expected_entity_type
            or not (
                node.get("community") is None
                or (type(node.get("community")) is int and 0 <= node["community"] <= _MAX_JS_SAFE_INTEGER)
            )
            or not isinstance(unresolved_reasons, list)
            or any(not isinstance(reason, str) or not reason for reason in unresolved_reasons)
            or len(unresolved_reasons) != len(set(unresolved_reasons))
            or not set(unresolved_reasons) <= GRAPH_NODE_UNRESOLVED_REASONS
            or unresolved_reasons
            != [reason for reason in GRAPH_NODE_UNRESOLVED_REASON_ORDER if reason in unresolved_reasons]
            or "graphify_node_label_derived_from_repository_relative_coordinate" not in unresolved_reasons
            or (
                (origin != "ast")
                != ("graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction" in unresolved_reasons)
            )
            or (
                "graphify_node_community_outside_js_safe_nonnegative_integer_domain" in unresolved_reasons
                and node.get("community") is not None
            )
            or (
                "graphify_node_source_location_outside_bounded_coordinate_domain" in unresolved_reasons
                and source_location != ""
            )
            or (
                "graphify_node_nonvocabulary_descriptor_withheld" in unresolved_reasons
                and all(node.get(name) != "" for name in ("file_type", "language", "kind"))
            )
            or projected
            != digest_object(
                [
                    "repository-relative-graph-node",
                    source_file,
                    source_location,
                    str(coordinate_occurrence),
                ]
            )
            or identifier != stable_id("graph-node", source_commit, projected)
        ):
            raise ReleaseInputError("compiler Graphify node lacks a unique privacy-safe repository-relative identity")
        node_ids.add(identifier)
        projected_identifiers.add(projected)
        node_coordinate_occurrences.setdefault((source_file, source_location), set()).add(coordinate_occurrence)
        if type(node.get("community")) is int:
            community = node["community"]
            projected_community_node_counts[community] = projected_community_node_counts.get(community, 0) + 1
    for occurrences in node_coordinate_occurrences.values():
        if occurrences != set(range(len(occurrences))):
            raise ReleaseInputError("compiler Graphify node coordinate occurrences are not contiguous")
    projected_community_ids = sorted(projected_community_node_counts)
    community_dispositions = graphify.get("community_dispositions")
    dispositions_by_community = (
        {
            item.get("community"): item
            for item in community_dispositions
            if isinstance(item, dict) and type(item.get("community")) is int
        }
        if isinstance(community_dispositions, list)
        else {}
    )
    derived_partial_ids: list[int] = []
    if (
        graphify.get("projected_community_ids") != projected_community_ids
        or graphify.get("projected_communities") != len(projected_community_ids)
        or len(dispositions_by_community) != len(community_dispositions or [])
    ):
        raise ReleaseInputError("compiler Graphify projected community denominator is inconsistent")
    for community, retained_count in projected_community_node_counts.items():
        disposition = dispositions_by_community.get(community)
        if not isinstance(disposition, dict) or disposition.get("retained_nodes") != retained_count:
            raise ReleaseInputError("compiler Graphify projected community denominator is inconsistent")
        if disposition.get("status") == "projected_partial":
            derived_partial_ids.append(community)
        elif disposition.get("status") != "projected_complete":
            raise ReleaseInputError("compiler Graphify projected community disposition is inconsistent")
    if graphify.get("partial_community_ids") != sorted(derived_partial_ids):
        raise ReleaseInputError("compiler Graphify projected community disposition is inconsistent")
    for disposition in graphify.get("excluded_edge_dispositions", []):
        for endpoint_name in ("source_endpoint", "target_endpoint"):
            endpoint = disposition.get(endpoint_name)
            if endpoint.get("state") == "retained" and endpoint.get("record_id") not in node_ids:
                raise ReleaseInputError(
                    "compiler Graphify excluded edge retained endpoint does not traverse to a projected node"
                )
    edge_ids: set[str] = set()
    edge_coordinates: dict[tuple[object, ...], set[int]] = {}
    projected_edge_modes: dict[str, int] = {}
    for edge in edges:
        if set(edge) != _GRAPH_EDGE_KEYS:
            raise ReleaseInputError("compiler Graphify edge shape is not canonical")
        identifier = edge.get("id")
        source_file = edge.get("source_file")
        if source_file is not None:
            file_record = files_by_path.get(source_file)
            valid_source_file = bool(
                isinstance(file_record, dict)
                and file_record.get("privacy_exposure") == "full"
                and file_record.get("classification_errors") == []
            )
        else:
            valid_source_file = True
        relation = edge.get("relation")
        source_location = edge.get("source_location")
        extraction_mode = edge.get("extraction_mode")
        confidence = edge.get("confidence")
        coordinate_occurrence = edge.get("coordinate_occurrence")
        unresolved_reasons = edge.get("unresolved_reasons")
        confidence_is_valid = bool(
            confidence is None
            or (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and math.isfinite(float(confidence))
                and 0 <= float(confidence) <= 1
            )
        )
        if confidence is None:
            confidence_identity = "none"
        elif confidence_is_valid and float(confidence).is_integer():
            confidence_identity = f"integer:{int(float(confidence))}"
        elif confidence_is_valid:
            confidence_identity = f"float64:{struct.pack('>d', float(confidence)).hex()}"
        else:
            confidence_identity = "invalid"
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"urn:atlas:graph-edge:[0-9a-f]{24}", identifier) is None
            or identifier in edge_ids
            or edge.get("source") not in node_ids
            or edge.get("target") not in node_ids
            or not valid_source_file
            or not isinstance(relation, str)
            or relation not in CONTROLLED_GRAPH_RELATIONS
            or not _valid_graph_location(source_location)
            or extraction_mode not in {"ambiguous", "extracted", "inferred", "undisclosed"}
            or not confidence_is_valid
            or type(coordinate_occurrence) is not int
            or coordinate_occurrence < 0
            or edge.get("entity_type") != "graph_edge"
            or not isinstance(unresolved_reasons, list)
            or any(not isinstance(reason, str) or not reason for reason in unresolved_reasons)
            or len(unresolved_reasons) != len(set(unresolved_reasons))
            or not set(unresolved_reasons) <= GRAPH_EDGE_UNRESOLVED_REASONS
            or unresolved_reasons
            != [reason for reason in GRAPH_EDGE_UNRESOLVED_REASON_ORDER if reason in unresolved_reasons]
            or (
                (extraction_mode not in {"extracted", "inferred"})
                != ("graphify_confidence_mode_undisclosed_or_ambiguous" in unresolved_reasons)
            )
            or (
                "graphify_relation_not_in_controlled_vocabulary_shape" in unresolved_reasons
                and relation != "related_to"
            )
            or (
                "graphify_edge_source_location_outside_bounded_coordinate_domain" in unresolved_reasons
                and source_location != ""
            )
        ):
            raise ReleaseInputError("compiler Graphify edge endpoint or stable identity is inconsistent")
        edge_ids.add(identifier)
        coordinate: tuple[object, ...] = (
            edge["source"],
            edge["target"],
            relation,
            source_file or "",
            source_location,
            extraction_mode,
            confidence_identity,
        )
        expected_identifier = stable_id("graph-edge", source_commit, *coordinate, coordinate_occurrence)
        if identifier != expected_identifier:
            raise ReleaseInputError("compiler Graphify edge stable identity is not derived from its public coordinate")
        edge_coordinates.setdefault(coordinate, set()).add(coordinate_occurrence)
        projected_edge_modes[extraction_mode] = projected_edge_modes.get(extraction_mode, 0) + 1
    for occurrences in edge_coordinates.values():
        if occurrences != set(range(len(occurrences))):
            raise ReleaseInputError("compiler Graphify edge coordinate occurrences are not contiguous")
    if graphify.get("projected_edge_modes") != projected_edge_modes:
        raise ReleaseInputError("compiler Graphify projected edge-mode denominator is inconsistent")


@dataclass(frozen=True)
class CompilerBundle:
    root: Path
    manifest: dict[str, Any]
    completeness: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    input_files: tuple[str, ...]

    @property
    def source_commit(self) -> str:
        return str(self.manifest["source_commit"])

    @property
    def source_tree_digest(self) -> str:
        return str(self.manifest["source_tree_digest"])


def _read_bounded_owner_bytes(
    root: Path,
    relative: str,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    try:
        path = safe_input(root, relative)
        before = path.stat(follow_symlinks=False)
    except (OSError, ReleaseInputError):
        raise ReleaseInputError(f"compiler {label} could not be read from its fixed owner path") from None
    if before.st_size > maximum_bytes:
        raise ReleaseInputError(f"compiler {label} exceeds its bounded byte limit")
    try:
        with path.open("rb") as stream:
            value = stream.read(maximum_bytes + 1)
        after = path.stat(follow_symlinks=False)
    except OSError:
        raise ReleaseInputError(f"compiler {label} could not be read from its fixed owner path") from None
    if len(value) > maximum_bytes:
        raise ReleaseInputError(f"compiler {label} exceeds its bounded byte limit")
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or len(value) != after.st_size:
        raise ReleaseInputError(f"compiler {label} changed during its bounded read")
    return value


def _receipt_json(
    root: Path,
    receipt: object,
    label: str,
    *,
    expected_path: str,
    expected_keys: frozenset[str] = _FILE_RECEIPT_KEYS,
    maximum_bytes: int = _MAX_COMPILER_JSON_BYTES,
) -> tuple[str, dict[str, Any], bytes]:
    if (
        not isinstance(receipt, dict)
        or set(receipt) != expected_keys
        or receipt.get("path") != expected_path
        or type(receipt.get("bytes")) is not int
        or not 0 <= receipt["bytes"] <= maximum_bytes
        or not isinstance(receipt.get("sha256"), str)
        or _GRAPH_DIGEST.fullmatch(receipt["sha256"]) is None
    ):
        raise ReleaseInputError(f"compiler {label} owner path is not canonical")
    relative = safe_relative(expected_path)
    value = _read_bounded_owner_bytes(
        root,
        relative,
        label=label,
        maximum_bytes=maximum_bytes,
    )
    if receipt.get("bytes") != len(value) or receipt.get("sha256") != sha256_bytes(value):
        raise ReleaseInputError(f"compiler {label} receipt mismatch: {relative}")
    try:
        import json

        parsed = json.loads(value.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, RecursionError, ValueError):
        raise ReleaseInputError(f"compiler {label} is invalid JSON: {relative}") from None
    if not isinstance(parsed, dict):
        raise ReleaseInputError(f"compiler {label} is not an object: {relative}")
    try:
        canonical = canonical_json(parsed)
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        raise ReleaseInputError(f"compiler {label} is not canonical JSON: {relative}") from None
    if value != canonical:
        raise ReleaseInputError(f"compiler {label} is not canonical JSON: {relative}")
    return relative, parsed, value


def load_compiler_bundle(
    root: Path,
    *,
    retained_groups: Iterable[str] | None = None,
    repository_root: Path | None = None,
) -> CompilerBundle:
    root = root.resolve(strict=True)
    manifest_raw = _read_bounded_owner_bytes(
        root,
        "manifest.json",
        label="manifest",
        maximum_bytes=_MAX_COMPILER_JSON_BYTES,
    )
    try:
        import json

        manifest = json.loads(manifest_raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, RecursionError, ValueError):
        raise ReleaseInputError("compiler manifest is invalid UTF-8 JSON") from None
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ReleaseInputError("compiler manifest shape is not canonical")
    if manifest.get("status") != "complete":
        raise ReleaseInputError("compiler manifest is absent or not complete")
    try:
        canonical_manifest = canonical_json(manifest)
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        raise ReleaseInputError("compiler manifest is not canonical JSON") from None
    if manifest_raw != canonical_manifest:
        raise ReleaseInputError("compiler manifest is not canonical JSON")
    if manifest.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError("unsupported compiler schema")
    commit = manifest.get("source_commit")
    tree = manifest.get("source_tree_digest")
    if (
        not isinstance(commit, str)
        or len(commit) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        raise ReleaseInputError("compiler source_commit is not a lowercase Git object id")
    if not isinstance(tree, str) or len(tree) != 64 or any(char not in "0123456789abcdef" for char in tree):
        raise ReleaseInputError("compiler source_tree_digest is invalid")
    head_tree = manifest.get("head_tree_oid")
    index_digest = manifest.get("index_digest")
    if (
        not isinstance(head_tree, str)
        or len(head_tree) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in head_tree)
    ):
        raise ReleaseInputError("compiler head_tree_oid is invalid")
    if (
        not isinstance(index_digest, str)
        or len(index_digest) != 64
        or any(char not in "0123456789abcdef" for char in index_digest)
    ):
        raise ReleaseInputError("compiler index_digest is invalid")
    if manifest.get("tracked_worktree_dirty") is not False:
        raise ReleaseInputError("release requires a compiler projection from an exact clean tracked worktree")
    if manifest.get("release_class") != "exact_commit":
        raise ReleaseInputError("release requires compiler release_class exact_commit")
    chunk_size = manifest.get("chunk_size")
    if type(chunk_size) is not int or not 1 <= chunk_size <= 100_000:
        raise ReleaseInputError("compiler manifest chunk-size denominator is malformed")

    completeness_path, completeness, _completeness_raw = _receipt_json(
        root,
        manifest.get("completeness", {}),
        "completeness",
        expected_path="completeness.json",
    )
    graphify_path, graphify, _graphify_raw = _receipt_json(
        root,
        manifest.get("graphify_metadata", {}),
        "Graphify metadata",
        expected_path="graphify-metadata.json",
    )
    if "architecture_conformance" not in manifest:
        raise ReleaseInputError("compiler architecture conformance receipt missing")
    architecture_path, architecture, _architecture_raw = _receipt_json(
        root,
        manifest.get("architecture_conformance", {}),
        "architecture conformance",
        expected_path="architecture-conformance.json",
    )
    if completeness.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError("unsupported compiler completeness schema")
    if graphify.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError("unsupported compiler Graphify schema")
    if graphify.get("source_commit") != commit or graphify.get("source_tree_digest") != tree:
        raise ReleaseInputError("compiler Graphify receipt is not bound to the compiler source")
    if architecture.get("schema_version") != COMPILER_SCHEMA_VERSION:
        raise ReleaseInputError("unsupported compiler architecture-conformance schema")
    if completeness.get("source_commit") != commit or completeness.get("source_tree_digest") != tree:
        raise ReleaseInputError("completeness ledger is not bound to the compiler source")
    if completeness.get("hard_failure") is not False or completeness.get("fatal_errors"):
        raise ReleaseInputError("completeness ledger contains a hard failure")
    invariants = completeness.get("invariants")
    if (
        not isinstance(invariants, list)
        or not invariants
        or any(not isinstance(item, dict) or item.get("passed") is not True for item in invariants)
    ):
        raise ReleaseInputError("not every compiler completeness invariant passed")
    invariant_by_name: dict[str, dict[str, Any]] = {}
    for item in invariants:
        name = item.get("name")
        expected = item.get("expected")
        actual = item.get("actual")
        if (
            not isinstance(name, str)
            or not name
            or name in invariant_by_name
            or type(expected) is not int
            or type(actual) is not int
            or expected < 0
            or actual < 0
        ):
            raise ReleaseInputError("compiler completeness invariants have an invalid or duplicate name")
        invariant_by_name[name] = item
    missing_invariants = REQUIRED_STRUCTURAL_INVARIANTS - set(invariant_by_name)
    if missing_invariants:
        raise ReleaseInputError(
            "compiler structural line-mapping invariant or required GUI/root denominator is missing: "
            f"{sorted(missing_invariants)}"
        )
    structural_gate = invariant_by_name.get("every_safe_line_structurally_mapped")
    structural_root_gate = invariant_by_name.get("every_safe_parsed_source_has_one_structural_root")
    gui_gate = invariant_by_name.get("every_gui_surface_has_standardized_evidence_honest_dossier")
    semantic_accounting = completeness.get("semantic_accounting")
    if (
        structural_gate is None
        or structural_gate.get("expected") != structural_gate.get("actual")
        or structural_root_gate is None
        or structural_root_gate.get("expected") != structural_root_gate.get("actual")
        or gui_gate is None
        or gui_gate.get("expected") != gui_gate.get("actual")
        or not isinstance(semantic_accounting, dict)
        or semantic_accounting.get("structurally_mapped_lines") != structural_gate.get("actual")
        or semantic_accounting.get("safe_parsed_sources") != structural_root_gate.get("expected")
        or semantic_accounting.get("structural_root_entities") != structural_root_gate.get("actual")
        or semantic_accounting.get("gui_surface_records") != gui_gate.get("expected")
        or semantic_accounting.get("gui_dossiers") != gui_gate.get("actual")
    ):
        raise ReleaseInputError(
            "compiler structural line-mapping invariant or GUI/root denominator is absent or inconsistent"
        )
    acceptance_gates = completeness.get("acceptance_gates")
    if not isinstance(acceptance_gates, list) or not acceptance_gates:
        raise ReleaseInputError("completeness ledger contains no semantic acceptance gates")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not item.get("name")
        or not isinstance(item.get("passed"), bool)
        for item in acceptance_gates
    ):
        raise ReleaseInputError("completeness ledger semantic acceptance gates are malformed")
    acceptance_names = [str(item["name"]) for item in acceptance_gates]
    if len(acceptance_names) != len(set(acceptance_names)):
        raise ReleaseInputError("completeness ledger semantic acceptance gates are duplicated")
    if set(acceptance_names) != REQUIRED_ACCEPTANCE_GATES:
        raise ReleaseInputError("completeness ledger semantic acceptance gate registry is incomplete or stale")
    if architecture != completeness.get("architecture_conformance"):
        raise ReleaseInputError("architecture conformance differs from the completeness ledger")
    if architecture.get("source_commit") != commit or architecture.get("source_tree_digest") != tree:
        raise ReleaseInputError("architecture conformance is not bound to the compiler source")
    if architecture.get("status") != "passed" or architecture.get("errors"):
        raise ReleaseInputError("architecture conformance did not pass")
    if architecture.get("runtime_observed") is not False:
        raise ReleaseInputError("architecture conformance mislabels static evidence as runtime observation")

    groups = manifest.get("groups")
    if not isinstance(groups, dict) or set(groups) != REQUIRED_GROUPS:
        raise ReleaseInputError("compiler manifest record-group inventory is not canonical")
    if not isinstance(groups.get("lines"), dict) or groups["lines"].get("record_count") != structural_gate["expected"]:
        raise ReleaseInputError("compiler line-group denominator differs from structural mapping invariant")
    if (
        not isinstance(groups.get("structural_entities"), dict)
        or groups["structural_entities"].get("record_count") != structural_root_gate["expected"]
    ):
        raise ReleaseInputError("compiler structural-entity group differs from the safe parsed-source denominator")
    gui_group_denominator = sum(
        int(groups[name].get("record_count", -1))
        for name in ("routes", "components")
        if isinstance(groups.get(name), dict)
    )
    if gui_group_denominator != gui_gate["expected"]:
        raise ReleaseInputError("compiler GUI groups differ from the GUI dossier denominator")
    wanted = set(groups) if retained_groups is None else set(retained_groups)
    unknown_wanted = wanted - set(groups)
    if unknown_wanted:
        raise ReleaseInputError(f"requested compiler groups are absent: {sorted(unknown_wanted)}")
    validation_groups = {
        "files",
        "lines",
        "source_text",
        "symbols",
        "structural_entities",
        "routes",
        "components",
    }
    if not validation_groups.issubset(wanted):
        raise ReleaseInputError("retained compiler groups omit records required for structural denominator validation")

    records: dict[str, list[dict[str, Any]]] = {}
    input_files = {"manifest.json", completeness_path, graphify_path, architecture_path}
    current_identity_contract = _local_identity_contract(repository_root) if repository_root is not None else None
    scanned_chunk_bytes = 0
    for group_name in sorted(groups):
        group = groups[group_name]
        if (
            not isinstance(group, dict)
            or set(group) != _GROUP_RECEIPT_KEYS
            or not isinstance(group.get("chunks"), list)
            or type(group.get("record_count")) is not int
            or group["record_count"] < 0
            or type(group.get("chunk_count")) is not int
            or group["chunk_count"] < 0
            or not isinstance(group.get("records_digest"), str)
            or _GRAPH_DIGEST.fullmatch(group["records_digest"]) is None
        ):
            raise ReleaseInputError(f"compiler group is malformed: {group_name}")
        chunks = group["chunks"]
        effective_chunk_size = 1 if group_name == "source_text" else chunk_size
        full_chunks, final_chunk_size = divmod(group["record_count"], effective_chunk_size)
        expected_chunk_count = full_chunks + (1 if final_chunk_size else 0)
        if group["chunk_count"] != len(chunks) or len(chunks) != expected_chunk_count:
            raise ReleaseInputError(f"compiler chunk packing is not canonical: {group_name}")
        combined: list[dict[str, Any]] = []
        combined_ids: list[str] = []
        for expected_index, chunk_receipt in enumerate(chunks):
            expected_relative = f"chunks/{group_name}/{expected_index:05d}.json"
            if (
                not isinstance(chunk_receipt, dict)
                or set(chunk_receipt) != _CHUNK_RECEIPT_KEYS
                or chunk_receipt.get("path") != expected_relative
                or type(chunk_receipt.get("record_count")) is not int
                or chunk_receipt["record_count"] < 1
            ):
                raise ReleaseInputError(
                    f"compiler chunk owner path is not canonical: group={group_name}; index={expected_index}"
                )
            expected_record_count = (
                effective_chunk_size
                if expected_index + 1 < expected_chunk_count
                else group["record_count"] - (effective_chunk_size * (expected_chunk_count - 1))
            )
            if chunk_receipt["record_count"] != expected_record_count:
                raise ReleaseInputError(f"compiler chunk packing is not canonical: {group_name}")
            relative, envelope, chunk_raw = _receipt_json(
                root,
                chunk_receipt,
                f"{group_name} chunk",
                expected_path=expected_relative,
                expected_keys=_CHUNK_RECEIPT_KEYS,
            )
            input_files.add(relative)
            scanned_chunk_bytes += len(chunk_raw)
            if scanned_chunk_bytes > _MAX_COMPILER_CHUNK_BYTES:
                raise ReleaseInputError("compiler chunk byte census exceeds its bounded privacy-scan limit")
            if current_identity_contract is not None:
                try:
                    chunk_text = chunk_raw.decode("utf-8", errors="strict")
                    current_rule = _current_local_identity_rule(
                        chunk_text,
                        current_identity_contract,
                    )
                except (UnicodeError, ValueError):
                    raise ReleaseInputError(
                        f"compiler chunk privacy scan found invalid text: group={group_name}; index={expected_index}"
                    ) from None
                if current_rule is not None:
                    raise ReleaseInputError(
                        f"compiler chunk privacy scan failed: rule={current_rule}; group={group_name}; index={expected_index}"
                    )
            if (
                set(envelope) != _CHUNK_ENVELOPE_KEYS
                or envelope.get("schema_version") != COMPILER_SCHEMA_VERSION
                or envelope.get("record_type") != group_name
                or envelope.get("source_commit") != commit
                or envelope.get("source_tree_digest") != tree
                or envelope.get("chunk_index") != expected_index
                or envelope.get("chunk_count") != len(chunks)
            ):
                raise ReleaseInputError(f"compiler chunk envelope mismatch: {relative}")
            chunk_records = envelope.get("records")
            if not isinstance(chunk_records, list) or envelope.get("record_count") != len(chunk_records):
                raise ReleaseInputError(f"compiler chunk records malformed: {relative}")
            if any(not isinstance(item, dict) for item in chunk_records):
                raise ReleaseInputError(f"compiler group contains a non-object record: {group_name}")
            allowed_record_keys = _RECORD_KEYS_BY_GROUP[group_name]
            if any(not set(item) <= allowed_record_keys for item in chunk_records):
                raise ReleaseInputError(
                    f"compiler record contains an undeclared field: group={group_name}; index={expected_index}"
                )
            _validate_chunk_against_tracked_schema(envelope, group_name, expected_index)
            record_ids = [item.get("id") for item in chunk_records]
            if any(
                not isinstance(identifier, str) or not identifier or len(identifier) > _MAX_RECORD_ID_LENGTH
                for identifier in record_ids
            ):
                raise ReleaseInputError(f"compiler {group_name} chunk contains an invalid stable id")
            try:
                encoded_record_ids = [identifier.encode("utf-8", errors="strict") for identifier in record_ids]
            except UnicodeError:
                raise ReleaseInputError(f"compiler {group_name} chunk contains an invalid stable id") from None
            if any(len(identifier) > _MAX_RECORD_ID_LENGTH * 4 for identifier in encoded_record_ids):
                raise ReleaseInputError(f"compiler {group_name} chunk contains an invalid stable id")
            if envelope.get("records_digest") != digest_object(record_ids):
                raise ReleaseInputError(f"compiler chunk record digest mismatch: {relative}")
            combined_ids.extend(record_ids)
            if group_name in wanted:
                combined.extend(chunk_records)
        if group["record_count"] != sum(item["record_count"] for item in chunks):
            raise ReleaseInputError(f"compiler group receipt count mismatch: {group_name}")
        if group["record_count"] != len(combined_ids) or group["records_digest"] != digest_object(combined_ids):
            raise ReleaseInputError(f"compiler group aggregate mismatch: {group_name}")
        if any(left >= right for left, right in zip(combined_ids, combined_ids[1:], strict=False)):
            raise ReleaseInputError(f"compiler record order is not canonical: {group_name}")
        if group_name in wanted:
            if group["record_count"] != len(combined):
                raise ReleaseInputError(f"compiler group aggregate mismatch: {group_name}")
            records[group_name] = combined

    if graphify != completeness.get("graphify"):
        raise ReleaseInputError("Graphify metadata differs from the completeness ledger")
    if graphify.get("status") == "parser_error":
        raise ReleaseInputError("Graphify metadata reports a parser error")
    _validate_graph_projection(graphify, records, commit)
    if repository_root is not None:
        _scan_generated_local_identities(
            graphify,
            completeness,
            architecture,
            records,
            repository_root,
        )
    seen_ids: dict[str, str] = {}
    for group_name, group_records in sorted(records.items()):
        for item in group_records:
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ReleaseInputError(f"compiler {group_name} record lacks a stable id")
            if identifier in seen_ids:
                raise ReleaseInputError("compiler stable IDs are not unique across record groups")
            seen_ids[identifier] = group_name

    files = records.get("files")
    if files is not None:
        by_path: dict[str, dict[str, Any]] = {}
        for item in files:
            path = item.get("path")
            if not isinstance(path, str) or not path or path in by_path:
                raise ReleaseInputError("compiler file census contains an invalid or duplicate path")
            try:
                safe_relative(path)
            except ReleaseInputError:
                raise ReleaseInputError("compiler file census contains an unsafe repository path") from None
            exposure = item.get("privacy_exposure")
            expected_source = "selected_commit_git_blob" if exposure == "full" else "metadata_only_git_object"
            if exposure not in {"full", "metadata_only"} or item.get("content_source") != expected_source:
                raise ReleaseInputError("compiler file has invalid exact-source custody")
            if exposure == "metadata_only" and item.get("content_digest") is not None:
                raise ReleaseInputError("metadata-only compiler file exposes a content digest")
            by_path[path] = item

        for item in records.get("source_text", []):
            path = item.get("path")
            file_record = by_path.get(str(path))
            if (
                file_record is None
                or file_record.get("privacy_exposure") != "full"
                or item.get("source_basis") != "selected_commit_git_blob"
                or item.get("git_blob_oid") != file_record.get("git_blob_oid")
                or item.get("content_digest") != file_record.get("content_digest")
                or item.get("byte_count") != file_record.get("size_bytes")
            ):
                raise ReleaseInputError("compiler source-text custody differs from file record")
    safe_parsed_files = {
        str(item["id"]): item
        for item in records["files"]
        if item.get("privacy_exposure") == "full"
        and item.get("language") != "binary"
        and item.get("parse_status") == "parsed"
    }
    roots_by_file: dict[str, list[dict[str, Any]]] = {}
    for item in records["structural_entities"]:
        roots_by_file.setdefault(str(item.get("file_id") or ""), []).append(item)
    if (
        set(roots_by_file) != set(safe_parsed_files)
        or len(records["structural_entities"]) != structural_root_gate["expected"]
    ):
        raise ReleaseInputError("compiler structural-root file denominator is not exact")
    structural_roots: dict[str, dict[str, Any]] = {}
    for file_id, file_record in safe_parsed_files.items():
        candidates = roots_by_file.get(file_id, [])
        if len(candidates) != 1:
            raise ReleaseInputError("compiler source lacks exactly one structural root")
        root_record = candidates[0]
        location = root_record.get("range")
        line_count = file_record.get("line_count")
        exact_range = bool(
            isinstance(location, dict)
            and type(line_count) is int
            and (
                (
                    line_count == 0
                    and root_record.get("range_state") == "empty_source"
                    and all(
                        location.get(field) is None
                        for field in ("start_line", "start_column", "end_line", "end_column")
                    )
                )
                or (
                    line_count > 0
                    and root_record.get("range_state") == "exact_source_lines"
                    and location.get("start_line") == 1
                    and location.get("start_column") == 0
                    and location.get("end_line") == line_count
                    and type(location.get("end_column")) is int
                    and location["end_column"] >= 0
                )
            )
        )
        if (
            not exact_range
            or root_record.get("root_scope") != "parsed_source"
            or root_record.get("path") != file_record.get("path")
            or root_record.get("parser") != file_record.get("parser")
            or root_record.get("parser_mode") != file_record.get("parser_mode")
            or root_record.get("parser_version") != file_record.get("parser_version")
            or root_record.get("language") != file_record.get("language")
            or root_record.get("roles") != file_record.get("roles")
            or root_record.get("source_basis") != file_record.get("content_source")
            or root_record.get("git_blob_oid") != file_record.get("git_blob_oid")
            or root_record.get("content_digest") != file_record.get("content_digest")
            or root_record.get("line_count") != line_count
            or root_record.get("nonblank_line_count") != file_record.get("nonblank_line_count")
            or root_record.get("parser_owned") is not True
            or int(root_record.get("explanation_depth") or 0) < 1
        ):
            raise ReleaseInputError("compiler structural root is not bound to its parsed source")
        structural_roots[str(root_record.get("id") or "")] = root_record
    if len(structural_roots) != structural_root_gate["actual"]:
        raise ReleaseInputError("compiler structural-root records differ from their invariant")

    gui_surfaces = [*records["routes"], *records["components"]]
    valid_gui_dossiers = 0
    for surface in gui_surfaces:
        dossier = surface.get("gui_dossier")
        citation = dossier.get("source_citation") if isinstance(dossier, dict) else None
        if (
            not isinstance(dossier, dict)
            or dossier.get("surface_id") != surface.get("id")
            or dossier.get("source_commit") != commit
            or dossier.get("field_count") != len(GUI_DOSSIER_FIELDS)
            or not GUI_DOSSIER_FIELDS.issubset(dossier)
            or not isinstance(citation, dict)
            or citation.get("record_id") != surface.get("id")
            or citation.get("path") != surface.get("path")
            or any(not isinstance(dossier.get(field), dict) for field in GUI_DOSSIER_FIELDS)
        ):
            raise ReleaseInputError("compiler GUI dossier is absent or malformed")
        valid_gui_dossiers += 1
    if valid_gui_dossiers != gui_gate["actual"] or len(gui_surfaces) != gui_gate["expected"]:
        raise ReleaseInputError("compiler GUI dossier records differ from their invariant")

    symbols_by_id = {str(item["id"]): item for item in records["symbols"]}
    line_coordinates: set[tuple[str, int]] = set()
    mapped_lines = 0
    for item in records["lines"]:
        path = item.get("path")
        number = item.get("line")
        coordinate = (str(path or ""), number if type(number) is int else -1)
        if not isinstance(path, str) or type(number) is not int or number < 1 or coordinate in line_coordinates:
            raise ReleaseInputError("compiler line denominator has an invalid or duplicate coordinate")
        line_coordinates.add(coordinate)
        semantic_id = item.get("semantic_entity")
        symbol = symbols_by_id.get(str(semantic_id or ""))
        root_record = structural_roots.get(str(semantic_id or ""))
        if symbol is not None:
            location = symbol.get("range") or {}
            valid_mapping = bool(
                item.get("structural_mapping_basis") == "symbol_range"
                and symbol.get("file_id") == item.get("file_id")
                and symbol.get("path") == path
                and type(location.get("start_line")) is int
                and type(location.get("end_line")) is int
                and location["start_line"] <= number <= location["end_line"]
            )
        else:
            valid_mapping = bool(
                root_record is not None
                and item.get("structural_mapping_basis") in {"parser_context", "parser_structural_root"}
                and root_record.get("file_id") == item.get("file_id")
                and root_record.get("path") == path
                and number <= int(root_record.get("line_count") or 0)
            )
        if valid_mapping and int(item.get("explanation_depth") or 0) >= 1:
            mapped_lines += 1
    if mapped_lines != structural_gate["actual"] or len(records["lines"]) != structural_gate["expected"]:
        raise ReleaseInputError("compiler line records differ from the structural mapping invariant")
    return CompilerBundle(root, manifest, completeness, records, tuple(sorted(input_files)))
