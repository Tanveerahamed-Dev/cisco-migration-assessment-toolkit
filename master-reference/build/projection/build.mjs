#!/usr/bin/env node
/**
 * Deterministically projects the Atlas compiler corpus into browser-loadable
 * ES modules. The metadata index never contains source text; each safe text
 * file is isolated behind one static lazy import in index.mjs.
 */
import { createHash } from "node:crypto";
import {
  access,
  lstat,
  mkdtemp,
  mkdir,
  open,
  realpath,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const GENERATED_MARKER = ".atlas-projection-generated";
const COMPILER_SCHEMA_VERSION = "1.2.0";
const PROJECTION_SCHEMA_VERSION = "2.0.0";
const REQUIRED_COMPILER_GROUPS = Object.freeze([
  "binaries",
  "calls",
  "claims",
  "consequential_claim_facets",
  "components",
  "configs",
  "datasets",
  "dependencies",
  "documents",
  "files",
  "graph_edges",
  "graph_nodes",
  "imports",
  "lines",
  "manifests",
  "markdown",
  "routes",
  "source_text",
  "structural_entities",
  "structured",
  "symbols",
  "tests",
  "workflows",
]);
const REQUIRED_INVARIANTS = Object.freeze([
  "every_safe_line_structurally_mapped",
  "every_safe_parsed_source_has_one_structural_root",
  "every_gui_surface_has_standardized_evidence_honest_dossier",
  "graphify_receipt_exact_source_bound",
]);
const REQUIRED_ACCEPTANCE_GATES = Object.freeze([
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
]);
const CONSEQUENTIAL_CLAIM_SCHEMA_VERSION = "bounded-curated-consequential-claims/2";
const CONSEQUENTIAL_CLAIM_KIND = "bounded_curated_content_claim_denominator";
const CONSEQUENTIAL_CLAIM_CONTRACT_PATH =
  "master-reference/governance/consequential-claim-contract.json";
const CONSEQUENTIAL_CLAIM_CONTENT_PATHS = Object.freeze([
  "master-reference/content/atlas-core.json",
  "master-reference/content/capability-catalog.json",
  "master-reference/content/delivery-governance.json",
  "master-reference/content/open-horizon-register.json",
  "master-reference/content/output-contract.json",
]);
const CONSEQUENTIAL_CLAIM_PATHS = new Set([
  CONSEQUENTIAL_CLAIM_CONTRACT_PATH,
  ...CONSEQUENTIAL_CLAIM_CONTENT_PATHS,
]);
const CONSEQUENTIAL_INTEGRITY_PREDICATES = Object.freeze([
  "repository.full_exposure_file_count",
  "repository.graphify_status",
  "repository.nonblank_line_record_count",
  "repository.source_commit",
  "repository.source_tree_digest",
  "repository.tracked_file_count",
]);
const CONSEQUENTIAL_SOURCE_COUNTS = Object.freeze({
  "master-reference/content/atlas-core.json": 155,
  "master-reference/content/capability-catalog.json": 426,
  "master-reference/content/delivery-governance.json": 969,
  "master-reference/content/open-horizon-register.json": 315,
  "master-reference/content/output-contract.json": 275,
});
const CONSEQUENTIAL_SOURCE_SPEC_DIGESTS = Object.freeze({
  "master-reference/content/atlas-core.json":
    "88945e355209ff0d42376c1fc5273f23729a21d5d82021f7c1ae63d38f65402e",
  "master-reference/content/capability-catalog.json":
    "ae20a8f8e43d41ff3e752366a7f4d822f839ad91735bd16bcce9fd7b336f0450",
  "master-reference/content/delivery-governance.json":
    "62b113259ea0bc532a3c76faa63c8ee55f20746dd928e17a29b380ca45c15d38",
  "master-reference/content/open-horizon-register.json":
    "5739641632a20c199cb3b12f57efb18825879c45dc0c2d8be22da6079c9c6d27",
  "master-reference/content/output-contract.json":
    "417d637ca609aed5e37c62004cc279618655c0c214ef4f61dab1db3b829d9084",
});
const CONSEQUENTIAL_EXPECTED_CANDIDATES = 2_140;
const CONSEQUENTIAL_MAX_CANDIDATES = 100_000;
const CONSEQUENTIAL_MAX_REFERENCES = 1_000;
const CONSEQUENTIAL_MAX_REFERENCE_LENGTH = 1_024;
const CONSEQUENTIAL_NOT_DECLARED_REASONS = new Set([
  "consequential_claim_contract_absent",
  "consequential_claim_contract_invalid",
  "consequential_claim_dirty_preview_not_eligible",
]);
const CONSEQUENTIAL_CLASSIFICATIONS = new Set([
  "candidate",
  "container",
  "governance_metadata",
  "identifier_metadata",
  "label_metadata",
  "registry_metadata",
  "relationship_metadata",
]);
const CONSEQUENTIAL_VALUE_TYPES = new Set([
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
]);
const CONSEQUENTIAL_RULE_ID_PATTERN = /^[a-z][a-z0-9_.-]{0,127}$/;
const CONSEQUENTIAL_SELECTOR_TOKEN_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?$/;
const CONSEQUENTIAL_JSON_MAX_BYTES = 8 * 1024 * 1024;
const CONSEQUENTIAL_JSON_MAX_DEPTH = 64;
const CONSEQUENTIAL_JSON_MAX_VALUES = 1_000_000;
const CONSEQUENTIAL_JSON_MAX_CONTAINER_ITEMS = 100_000;
const CONSEQUENTIAL_JSON_MAX_STRING_LENGTH = 1_048_576;
const GUI_DOSSIER_FIELDS = Object.freeze([
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
]);
const GUI_EVIDENCE_STATES = new Set(["explicitly_linked", "structural_only", "not_evidenced"]);
const STRUCTURAL_MAPPING_BASES = new Set(["symbol_range", "parser_context", "parser_structural_root"]);
// Source text and per-line records have dedicated, privacy-gated per-file
// modules below. Every other compiler group is metadata and must remain in the
// exact-tree denominator. Deriving this list from the signed compiler manifest
// means a newly added metadata adapter cannot silently disappear from Atlas.
const NON_METADATA_GROUPS = new Set(["lines", "source_text"]);
const DOSSIER_GROUPS = {
  data: ["datasets", "routes", "components"],
  test: ["tests"],
  workflow: ["workflows"],
  claim: ["claims"],
};
const METADATA_CHUNK_SIZE = 2_000;
const LAZY_MODULE_MAX_BYTES = 256 * 1024;
const IDENTITY_MODULE_MAX_BYTES = 8 * 1024;
const RECORD_FRAGMENT_TEXT_BYTES = 96 * 1024;
const DOSSIER_BASE_PREFIX_LENGTH = 2;
const SEARCH_GROUPS = [
  "files",
  "symbols",
  "tests",
  "workflows",
  "datasets",
  "routes",
  "components",
  "claims",
  "imports",
  "calls",
  "dependencies",
];
const SEARCH_POSTING_LIMIT = 64;
const SEARCH_QUERY_TOKEN_LIMIT = 8;
const SEARCH_SHARD_MAX_BYTES = 256 * 1024;
const SEARCH_DOCUMENT_SHARD_MAX_BYTES = 256 * 1024;
const SEARCH_INDEX_MAX_BYTES = 512 * 1024;
const SOURCE_CHUNK_MAX_BYTES = 256 * 1024;
// The exact-source route index is metadata-only but scales with every safe tracked
// file and source chunk.  The 1,091-file QDP-001 integration crossed the original
// 2 MiB ceiling; 3 MiB preserves a small explicit bound without changing source
// chunk, search-shard, compressed-family, or expanded-deployment budgets.
const SOURCE_INDEX_MAX_BYTES = 3 * 1024 * 1024;
const SOURCE_FRAGMENT_TEXT_BYTES = 64 * 1024;
const SOURCE_DIGEST_POLICY = Object.freeze({
  schemaVersion: "source-digest-projection/1",
  fileContentDigest: "retained_sha256_exact_file_bytes",
  lineDigest: "retained_sha256_exact_line_text_plus_terminator",
  textDigest: "verified_pre_projection_omitted_derivable_from_exact_emitted_text",
  fragmentDigest: "retained_sha256_fragment_text_only_when_fragment_count_gt_1",
});
const GRAPH_SHARD_MAX_BYTES = 256 * 1024;
const GRAPH_INDEX_MAX_BYTES = 512 * 1024;
const GRAPH_SHARD_RECORDS = 400;
const GRAPH_SAMPLE_NODES = 48;
const GRAPH_SAMPLE_EDGES = 400;
const COMPILER_JSON_MAX_BYTES = 32 * 1024 * 1024;
const COMPILER_JSON_MAX_DEPTH = 128;
const COMPILER_JSON_MAX_VALUES = 2_000_000;
const COMPILER_JSON_MAX_STRING_BYTES = 8 * 1024 * 1024;
const COMPILER_FLOAT_TOKEN_PATHS = new WeakMap();
const ATLAS_STABLE_ID_PATTERN = /^urn:atlas:[a-z-]+:[0-9a-f]{24}$/;
const CONSEQUENTIAL_CLAIM_FACET_RECORD_KEYS = Object.freeze(
  "classification claim_kind entity_type evidence_state facet_id facet_path grounding_digest id record_identity record_kind review_state rule_id source_blob_oid source_path source_pointer value_digest".split(" "),
);
export const COMPILER_RECORD_KEYS_BY_GROUP = Object.freeze(Object.fromEntries(
  Object.entries({
    binaries: "content_digest entity_type file_id git_blob_oid id inspection_mode media_type path privacy_exposure size_bytes unresolved_reasons",
    calls: "callee containing_symbol entity_type extraction_disposition file_id id path range resolved statement_digest tests unresolved_reasons",
    claims: "basis confidence conflicts_with current_view denominator derived_from effective_time entity_type evidence_class evidence_ids extraction_mode freshness id lineage origin owner predicate recorded_time revocation_reason revoked_by satisfies_evidence_requirement scope source_commit status subject temporal_basis transformation unit unresolved_reasons value verdict",
    consequential_claim_facets: CONSEQUENTIAL_CLAIM_FACET_RECORD_KEYS.join(" "),
    components: "attribute_names attributes_digest component_role detection entity_type exported extraction_disposition file_id framework gui_dossier handler id kind method name path range route self_closing tag_name unresolved_reasons",
    configs: "content_digest entity_type file_id id language path roles",
    datasets: "content_digest entity_type file_id format id path size_bytes structured_record_count",
    dependencies: "constraint ecosystem entity_type file_id id name path resolved_version scope",
    documents: "entity_type file_id id line_count path status status_reasons title",
    files: "classification_errors content_digest content_source documentation_status documentation_status_reasons entity_type git_blob_oid git_mode git_stage id language line_count media_type nonblank_line_count parse_status parser parser_mode parser_version path privacy_exposure privacy_reasons roles size_bytes unresolved_reasons",
    graph_edges: "confidence coordinate_occurrence entity_type extraction_mode id relation source source_file source_location target unresolved_reasons",
    graph_nodes: "community coordinate_occurrence entity_type extraction_mode file_id file_type graphify_id id kind label language origin source_file source_location unresolved_reasons",
    imports: "alias containing_symbol entity_type file_id id kind module names path range unresolved_reasons",
    lines: "GUI_or_artifact_consumers behavior_group callers_and_dependencies claims_influenced containing_symbol current_or_historical depth entity_type explanation_depth file_id id inputs_and_outputs language line line_digest line_number owner path runtime_trace_state security_and_privacy_effect semantic_entity source_commit structural_mapping_basis syntax_depth syntax_kind test_coverage_state tests_covering_it text_bytes text_digest text_preview unresolved_reasons",
    manifests: "content_digest dependency_count entity_type file_id id kind language path",
    markdown: "authority_classification containing_heading documentation_status entity_type file_id heading id kind level line path target text",
    routes: "attribute_names entity_type file_id framework gui_dossier handler id kind method name path range route unresolved_reasons",
    source_text: "byte_count content_digest encoding entity_type file_id git_blob_oid id line_count lines path source_basis",
    structural_entities: "content_digest entity_type explanation_depth extraction_disposition file_id generation_provenance git_blob_oid id kind language line_count name nonblank_line_count parser parser_mode parser_owned parser_version path range range_state roles root_scope source_basis uncertainty unresolved_reasons",
    structured: "cell_count data_row_count depth entity_type extraction_disposition file_id id key name path pointer range row_accounting_state row_count_including_header row_index unresolved_reasons value_digest value_preview value_type",
    symbols: "abstention_behavior callees caller_resolution callers claims_produced_or_consumed constant_basis constant_candidate criticality data_dependencies declaration_kind decorators depth digest documentation downstream_surfaces entity_type explanation_depth exported external_effects extraction_disposition failure_and_exception_behavior file_id framework_candidate history id kind known_impact_if_changed language limitations name parameters parameters_and_types path path_and_range performance_characteristics purpose purpose_basis qualified_name range responsibility return_annotation return_or_output review_state runtime_trace_evidence runtime_trace_state security_boundary stable_urn state_read state_written target test_linkage tests unresolved_reasons",
    tests: "assertion_count assertion_group_id assertions entity_type extraction_disposition file_id framework id name path range unresolved_reasons",
    workflows: "access action artifact_ids artifacts declared_path direction entity_type extraction_disposition file_id id job job_ids jobs name parser_mode path permission_ids permissions range run_declared scope source_digest step_id step_ids step_index steps triggers unresolved_reasons uses",
  }).map(([group, keys]) => [group, new Set(keys.split(" "))]),
));

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function digestObject(value) {
  return sha256(Buffer.from(`${stableJson(value)}\n`, "utf8"));
}

function parseStrictSourceJson(bytes) {
  if (
    !Buffer.isBuffer(bytes) ||
    bytes.byteLength === 0 ||
    bytes.byteLength > CONSEQUENTIAL_JSON_MAX_BYTES
  ) {
    throw new Error("compiler consequential-claim source JSON is invalid");
  }
  let source;
  try {
    source = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Error("compiler consequential-claim source JSON is invalid");
  }
  let index = 0;
  let values = 0;
  const numberPattern = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
  const fail = () => {
    throw new Error("compiler consequential-claim source JSON is invalid");
  };
  const whitespace = () => {
    while (
      index < source.length &&
      [0x09, 0x0A, 0x0D, 0x20].includes(source.charCodeAt(index))
    ) {
      index += 1;
    }
  };
  const stringValue = () => {
    const start = index;
    index += 1;
    let escaped = false;
    while (index < source.length) {
      const code = source.charCodeAt(index);
      if (!escaped && code === 0x22) {
        index += 1;
        const token = source.slice(start, index);
        let parsed;
        try {
          parsed = JSON.parse(token);
        } catch {
          fail();
        }
        let characters = 0;
        for (let offset = 0; offset < parsed.length; offset += 1) {
          const unit = parsed.charCodeAt(offset);
          if (unit <= 0x001F || (unit >= 0x007F && unit <= 0x009F)) {
            fail();
          } else if (unit >= 0xD800 && unit <= 0xDBFF) {
            const next = parsed.charCodeAt(offset + 1);
            if (!(next >= 0xDC00 && next <= 0xDFFF)) fail();
            offset += 1;
          } else if (unit >= 0xDC00 && unit <= 0xDFFF) {
            fail();
          }
          characters += 1;
          if (characters > CONSEQUENTIAL_JSON_MAX_STRING_LENGTH) fail();
        }
        return parsed;
      }
      if (!escaped && code < 0x20) fail();
      if (!escaped && code === 0x5c) {
        escaped = true;
      } else {
        escaped = false;
      }
      index += 1;
    }
    fail();
  };
  const value = (depth) => {
    values += 1;
    if (depth > CONSEQUENTIAL_JSON_MAX_DEPTH || values > CONSEQUENTIAL_JSON_MAX_VALUES) fail();
    whitespace();
    const token = source[index];
    if (token === "{") {
      index += 1;
      whitespace();
      const keys = new Set();
      if (source[index] === "}") {
        index += 1;
        return;
      }
      let items = 0;
      while (index < source.length) {
        if (source[index] !== '"') fail();
        const key = stringValue();
        if (keys.has(key)) fail();
        keys.add(key);
        whitespace();
        if (source[index] !== ":") fail();
        index += 1;
        value(depth + 1);
        items += 1;
        if (items > CONSEQUENTIAL_JSON_MAX_CONTAINER_ITEMS) fail();
        whitespace();
        if (source[index] === "}") {
          index += 1;
          return;
        }
        if (source[index] !== ",") fail();
        index += 1;
        whitespace();
      }
      fail();
    }
    if (token === "[") {
      index += 1;
      whitespace();
      if (source[index] === "]") {
        index += 1;
        return;
      }
      let items = 0;
      while (index < source.length) {
        value(depth + 1);
        items += 1;
        if (items > CONSEQUENTIAL_JSON_MAX_CONTAINER_ITEMS) fail();
        whitespace();
        if (source[index] === "]") {
          index += 1;
          return;
        }
        if (source[index] !== ",") fail();
        index += 1;
        whitespace();
      }
      fail();
    }
    if (token === '"') {
      stringValue();
      return;
    }
    for (const literal of ["true", "false", "null"]) {
      if (source.startsWith(literal, index)) {
        index += literal.length;
        return;
      }
    }
    numberPattern.lastIndex = index;
    const match = numberPattern.exec(source);
    if (!match || match[0].length > 128 || match[0].includes(".") || /[eE]/.test(match[0])) fail();
    try {
      if (BigInt(match[0]) > BigInt(Number.MAX_SAFE_INTEGER) || BigInt(match[0]) < BigInt(Number.MIN_SAFE_INTEGER)) {
        fail();
      }
    } catch {
      fail();
    }
    index += match[0].length;
  };
  value(1);
  whitespace();
  if (index !== source.length) fail();
  try {
    const parsed = JSON.parse(source);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) fail();
    return parsed;
  } catch {
    fail();
  }
}

function gitBlobOid(bytes, expected) {
  if (typeof expected !== "string" || !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(expected)) {
    return null;
  }
  const algorithm = expected.length === 40 ? "sha1" : "sha256";
  return createHash(algorithm)
    .update(Buffer.from(`blob ${bytes.byteLength}\0`, "ascii"))
    .update(bytes)
    .digest("hex");
}

function unavailableConsequentialClaimSummary(
  sourceCommit,
  sourceTreeDigest,
  reasonCode = "consequential_claim_contract_absent",
) {
  const unbound = sourceCommit === null && sourceTreeDigest === null;
  const bound = typeof sourceCommit === "string" &&
    /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(sourceCommit) &&
    typeof sourceTreeDigest === "string" && /^[0-9a-f]{64}$/.test(sourceTreeDigest);
  if ((!unbound && !bound) || !CONSEQUENTIAL_NOT_DECLARED_REASONS.has(reasonCode)) {
    throw new Error("compiler consequential-claim census is inconsistent");
  }
  return {
    schema_version: CONSEQUENTIAL_CLAIM_SCHEMA_VERSION,
    denominator_kind: CONSEQUENTIAL_CLAIM_KIND,
    state: "not_declared",
    closed: false,
    source_commit: sourceCommit,
    source_tree_digest: sourceTreeDigest,
    source_basis: "selected_commit_raw_git_blobs",
    contract_path: CONSEQUENTIAL_CLAIM_CONTRACT_PATH,
    contract_git_blob_oid: null,
    contract_digest: null,
    classification_digest: null,
    source_universe_expected: 5,
    source_universe_registered: 0,
    source_universe_unclassified: 5,
    source_receipts: [],
    source_receipts_digest: null,
    expected_candidates: 0,
    discovered_candidates: 0,
    classified_candidates: 0,
    independently_reviewed_candidates: 0,
    unresolved_candidates: 0,
    candidate_set_digest: null,
    compiler_integrity_claims_expected: 6,
    compiler_integrity_claims_classified: 0,
    compiler_integrity_claims_consequential: 0,
    error_codes: [
      reasonCode,
      "consequential_claim_source_universe_incomplete",
    ].sort(compareUnicodeCodePoints),
  };
}

function exactStringMembership(value, expected) {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === "string") &&
    new Set(value).size === value.length &&
    stableJson([...value].sort(compareUnicodeCodePoints)) ===
      stableJson([...expected].sort(compareUnicodeCodePoints))
  );
}

export function isPythonStripEmpty(value) {
  if (typeof value !== "string") return false;
  for (const character of value) {
    const point = character.codePointAt(0);
    const pythonWhitespace =
      (point >= 0x0009 && point <= 0x000D) ||
      (point >= 0x001C && point <= 0x0020) ||
      point === 0x0085 ||
      point === 0x00A0 ||
      point === 0x1680 ||
      (point >= 0x2000 && point <= 0x200A) ||
      point === 0x2028 ||
      point === 0x2029 ||
      point === 0x202F ||
      point === 0x205F ||
      point === 0x3000;
    if (!pythonWhitespace) return false;
  }
  return true;
}

function consequentialCanonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map(consequentialCanonicalJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort(compareUnicodeCodePoints)
      .map((key) => `${JSON.stringify(key)}:${consequentialCanonicalJson(value[key])}`)
      .join(",")}}`;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("compiler consequential-claim census is inconsistent");
    }
    if (Number.isInteger(value)) return String(value);
    const token = pythonFloatToken(value);
    if (token === null) {
      throw new Error("compiler consequential-claim census is inconsistent");
    }
    return token;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) {
    throw new Error("compiler consequential-claim census is inconsistent");
  }
  return encoded;
}

function consequentialDigest(value) {
  return sha256(Buffer.from(`${consequentialCanonicalJson(value)}\n`, "utf8"));
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, expected) {
  return (
    isObject(value) &&
    consequentialCanonicalJson(Object.keys(value).sort(compareUnicodeCodePoints)) ===
      consequentialCanonicalJson([...expected].sort(compareUnicodeCodePoints))
  );
}

function isNonblankString(value) {
  return typeof value === "string" && !isPythonStripEmpty(value);
}

function nonemptyDistinctStrings(value) {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(isNonblankString) &&
    new Set(value).size === value.length
  );
}

function valueMatchesConsequentialType(value, expected) {
  const stringArray = (allowEmpty, unique) =>
    Array.isArray(value) &&
    (allowEmpty || value.length > 0) &&
    value.every(isNonblankString) &&
    (!unique || new Set(value).size === value.length);
  if (expected === "array") return Array.isArray(value);
  if (expected === "baseline_value") {
    if (isNonblankString(value)) return true;
    if (Array.isArray(value)) return value.length > 0 && value.every(isNonblankString);
    if (!isObject(value) || Object.keys(value).length === 0) return false;
    return Object.entries(value).every(([key, item]) =>
      isNonblankString(key) && (
        isNonblankString(item) ||
        Number.isSafeInteger(item) ||
        (Array.isArray(item) && item.length > 0 && item.every(isNonblankString))
      ));
  }
  if (expected === "boolean") return typeof value === "boolean";
  if (expected === "integer") return Number.isSafeInteger(value);
  if (expected === "null") return value === null;
  if (expected === "object") return isObject(value);
  if (expected === "string") return isNonblankString(value);
  if (expected === "string_array") return stringArray(false, false);
  if (expected === "string_array_allow_empty") return stringArray(true, false);
  if (expected === "unique_string_array") return stringArray(false, true);
  if (expected === "unique_string_array_allow_empty") return stringArray(true, true);
  if (expected === "string_or_null") return value === null || isNonblankString(value);
  return false;
}

function validateConstraintContract(constraint, fieldRules) {
  if (!isObject(constraint) || typeof constraint.kind !== "string") return false;
  const kind = constraint.kind;
  if (kind === "const") {
    return hasExactKeys(constraint, ["kind", "field", "value"]) && fieldRules.has(constraint.field);
  }
  if (kind === "enum") {
    return hasExactKeys(constraint, ["kind", "field", "values"]) &&
      fieldRules.has(constraint.field) && nonemptyDistinctStrings(constraint.values);
  }
  if (kind === "integer_range") {
    return hasExactKeys(constraint, ["kind", "field", "minimum", "maximum"]) &&
      fieldRules.has(constraint.field) &&
      Number.isSafeInteger(constraint.minimum) &&
      Number.isSafeInteger(constraint.maximum) &&
      constraint.minimum <= constraint.maximum &&
      fieldRules.get(constraint.field).value_type === "integer";
  }
  if (kind === "unique_field") {
    return hasExactKeys(constraint, ["kind", "field"]) &&
      fieldRules.has(constraint.field) && fieldRules.get(constraint.field).required === true;
  }
  if (kind === "contains_reference") {
    return hasExactKeys(constraint, ["kind", "field", "reference"]) &&
      fieldRules.has(constraint.field) &&
      fieldRules.get(constraint.field).classification === "relationship_metadata" &&
      isNonblankString(constraint.reference);
  }
  if (kind === "root_const") {
    return hasExactKeys(constraint, ["kind", "field", "value"]) &&
      isNonblankString(constraint.field);
  }
  if (kind === "reference_by_state") {
    const keys = [
      "kind",
      "state_field",
      "owner_values",
      "owner_field",
      "gap_exempt_values",
      "gap_field",
    ];
    return hasExactKeys(constraint, keys) &&
      fieldRules.has(constraint.state_field) &&
      fieldRules.has(constraint.owner_field) &&
      fieldRules.has(constraint.gap_field) &&
      nonemptyDistinctStrings(constraint.owner_values) &&
      nonemptyDistinctStrings(constraint.gap_exempt_values) &&
      fieldRules.get(constraint.owner_field).classification === "relationship_metadata" &&
      fieldRules.get(constraint.gap_field).classification === "relationship_metadata";
  }
  if (kind === "emptiness_by_enum") {
    return hasExactKeys(constraint, ["kind", "enum_field", "value_field", "empty_values"]) &&
      fieldRules.has(constraint.enum_field) && fieldRules.has(constraint.value_field) &&
      nonemptyDistinctStrings(constraint.empty_values) &&
      ["string_array_allow_empty", "unique_string_array_allow_empty"].includes(
        fieldRules.get(constraint.value_field).value_type,
      );
  }
  if (kind !== "nullability_by_enum" ||
      !hasExactKeys(constraint, ["kind", "field", "cases"]) ||
      !fieldRules.has(constraint.field) ||
      !Array.isArray(constraint.cases) ||
      constraint.cases.length === 0) {
    return false;
  }
  const values = new Set();
  for (const item of constraint.cases) {
    if (!hasExactKeys(item, ["value", "null_fields", "non_null_fields"]) ||
        !isNonblankString(item.value) || values.has(item.value) ||
        !Array.isArray(item.null_fields) || !Array.isArray(item.non_null_fields) ||
        new Set(item.null_fields).size !== item.null_fields.length ||
        new Set(item.non_null_fields).size !== item.non_null_fields.length) {
      return false;
    }
    const allFields = [...item.null_fields, ...item.non_null_fields];
    if (allFields.some((field) => typeof field !== "string" || !fieldRules.has(field)) ||
        item.null_fields.some((field) => item.non_null_fields.includes(field)) ||
        allFields.some((field) => fieldRules.get(field).value_type !== "string_or_null")) {
      return false;
    }
    values.add(item.value);
  }
  return true;
}

function validateSourceRuleContract(source, allRuleIds, fail) {
  if (!hasExactKeys(source.grounding, [
    "relationships",
    "declared_owner_fields",
    "fallback_owner_ref",
    "require_nonempty",
  ])) fail();
  const grounding = source.grounding;
  if (!Array.isArray(grounding.relationships) ||
      !Array.isArray(grounding.declared_owner_fields) ||
      grounding.declared_owner_fields.some((field) => !isNonblankString(field)) ||
      new Set(grounding.declared_owner_fields).size !== grounding.declared_owner_fields.length ||
      !isNonblankString(grounding.fallback_owner_ref) || grounding.require_nonempty !== true) {
    fail();
  }
  const relationships = new Map();
  for (const relationship of grounding.relationships) {
    if (!hasExactKeys(relationship, ["field", "mode", "registry"]) ||
        !isNonblankString(relationship.field) || relationships.has(relationship.field) ||
        !["reference_array", "reference_scalar", "relation_scalar"].includes(relationship.mode) ||
        (["reference_array", "reference_scalar"].includes(relationship.mode) &&
          !isNonblankString(relationship.registry)) ||
        (relationship.mode === "relation_scalar" && relationship.registry !== null)) {
      fail();
    }
    relationships.set(relationship.field, relationship);
  }
  if (!Array.isArray(source.object_rules) || source.object_rules.length === 0) fail();
  let recordTotal = 0;
  let candidateTotal = 0;
  const classifiedRelationships = new Map();
  const classifiedFields = new Set();
  for (const rule of source.object_rules) {
    if (!hasExactKeys(rule, [
      "rule_id",
      "selector",
      "record_kind",
      "identity",
      "expected_records",
      "fields",
      "constraints",
    ]) ||
        typeof rule.rule_id !== "string" || !CONSEQUENTIAL_RULE_ID_PATTERN.test(rule.rule_id) ||
        allRuleIds.has(rule.rule_id) ||
        !Array.isArray(rule.selector) ||
        rule.selector.some((token) => typeof token !== "string" || !CONSEQUENTIAL_SELECTOR_TOKEN_PATTERN.test(token)) ||
        !isNonblankString(rule.record_kind) ||
        !Number.isSafeInteger(rule.expected_records) || rule.expected_records < 1 ||
        !Array.isArray(rule.fields) || rule.fields.length === 0 ||
        !Array.isArray(rule.constraints)) {
      fail();
    }
    allRuleIds.add(rule.rule_id);
    const identity = rule.identity;
    if (!isObject(identity) || !["root", "field", "parent_field", "composite"].includes(identity.kind)) {
      fail();
    }
    if ((identity.kind === "root" && !hasExactKeys(identity, ["kind"])) ||
        (["field", "parent_field"].includes(identity.kind) &&
          (!hasExactKeys(identity, ["kind", "field"]) || !isNonblankString(identity.field))) ||
        (identity.kind === "composite" &&
          (!hasExactKeys(identity, ["kind", "fields"]) || !nonemptyDistinctStrings(identity.fields)))) {
      fail();
    }
    const fieldRules = new Map();
    for (const field of rule.fields) {
      if (!hasExactKeys(field, ["field", "classification", "value_type", "required", "claim_kind"]) ||
          !isNonblankString(field.field) || fieldRules.has(field.field) ||
          !CONSEQUENTIAL_CLASSIFICATIONS.has(field.classification) ||
          !CONSEQUENTIAL_VALUE_TYPES.has(field.value_type) ||
          (field.classification === "candidate" && ["array", "object"].includes(field.value_type)) ||
          typeof field.required !== "boolean" ||
          (field.classification === "candidate"
            ? typeof field.claim_kind !== "string" || !CONSEQUENTIAL_RULE_ID_PATTERN.test(field.claim_kind)
            : field.claim_kind !== null)) {
        fail();
      }
      fieldRules.set(field.field, field);
      classifiedFields.add(field.field);
      if (field.classification === "relationship_metadata") {
        if (!classifiedRelationships.has(field.field)) classifiedRelationships.set(field.field, new Set());
        classifiedRelationships.get(field.field).add(field.value_type);
      }
      if (field.classification === "candidate") candidateTotal += rule.expected_records;
    }
    const identityFields = identity.kind === "field" ? [identity.field]
      : identity.kind === "composite" ? identity.fields : [];
    if (identityFields.some((field) => !fieldRules.has(field))) fail();
    if (rule.constraints.some((constraint) => !validateConstraintContract(constraint, fieldRules))) fail();
    recordTotal += rule.expected_records;
  }
  if (classifiedRelationships.size !== relationships.size ||
      [...classifiedRelationships.keys()].some((field) => !relationships.has(field))) {
    fail();
  }
  if (grounding.declared_owner_fields.some((field) => !classifiedFields.has(field))) fail();
  for (const [field, valueTypes] of classifiedRelationships) {
    const mode = relationships.get(field).mode;
    const allowed = mode === "reference_array"
      ? new Set(["unique_string_array", "unique_string_array_allow_empty"])
      : new Set(["string", "string_or_null"]);
    if ([...valueTypes].some((valueType) => !allowed.has(valueType))) fail();
  }
  if (source.expected_records !== recordTotal || source.expected_candidates !== candidateTotal) fail();
}

function recordsForConsequentialSelector(document, selector, fail) {
  let rows = [{ record: document, pointer: "", ancestors: [] }];
  for (const token of selector) {
    const collection = token.endsWith("[]");
    const field = collection ? token.slice(0, -2) : token;
    const next = [];
    for (const row of rows) {
      if (!isObject(row.record) || !Object.hasOwn(row.record, field)) fail();
      const selected = row.record[field];
      const pointer = `${row.pointer}/${field.replaceAll("~", "~0").replaceAll("/", "~1")}`;
      if (collection) {
        if (!Array.isArray(selected)) fail();
        selected.forEach((record, index) => next.push({
          record,
          pointer: `${pointer}/${index}`,
          ancestors: [...row.ancestors, row.record],
        }));
      } else {
        next.push({ record: selected, pointer, ancestors: [...row.ancestors, row.record] });
      }
    }
    rows = next;
  }
  if (rows.some((row) => !isObject(row.record))) fail();
  return rows;
}

function validateConsequentialReferences(value, fail) {
  if (!Array.isArray(value) || value.length > CONSEQUENTIAL_MAX_REFERENCES ||
      value.some((item) => !isNonblankString(item) || [...item].length > CONSEQUENTIAL_MAX_REFERENCE_LENGTH) ||
      new Set(value).size !== value.length) {
    fail();
  }
  return value;
}

function pythonTruthy(value) {
  if (Array.isArray(value) || typeof value === "string") return value.length > 0;
  if (isObject(value)) return Object.keys(value).length > 0;
  return Boolean(value);
}

function validateConsequentialConstraints(document, record, constraints, fail) {
  const get = (object, field) => Object.hasOwn(object, field) ? object[field] : null;
  for (const constraint of constraints) {
    if (constraint.kind === "unique_field") continue;
    let valid;
    if (constraint.kind === "const") {
      valid = consequentialDigest(get(record, constraint.field)) === consequentialDigest(constraint.value);
    } else if (constraint.kind === "enum") {
      valid = constraint.values.includes(get(record, constraint.field));
    } else if (constraint.kind === "integer_range") {
      const value = get(record, constraint.field);
      valid = Number.isSafeInteger(value) && value >= constraint.minimum && value <= constraint.maximum;
    } else if (constraint.kind === "contains_reference") {
      const value = get(record, constraint.field);
      valid = Array.isArray(value) && value.includes(constraint.reference);
    } else if (constraint.kind === "root_const") {
      valid = consequentialDigest(get(document, constraint.field)) === consequentialDigest(constraint.value);
    } else if (constraint.kind === "reference_by_state") {
      const state = get(record, constraint.state_field);
      const ownerValid = !constraint.owner_values.includes(state) ||
        pythonTruthy(get(record, constraint.owner_field));
      const gapExempt = constraint.gap_exempt_values.includes(state);
      const hasGaps = pythonTruthy(get(record, constraint.gap_field));
      const gapValid = gapExempt ? !hasGaps : hasGaps;
      valid = ownerValid && gapValid;
    } else if (constraint.kind === "emptiness_by_enum") {
      const enumValue = get(record, constraint.enum_field);
      const value = get(record, constraint.value_field);
      valid = constraint.empty_values.includes(enumValue) ? !pythonTruthy(value) : pythonTruthy(value);
    } else {
      const state = get(record, constraint.field);
      const item = constraint.cases.find((candidate) => candidate.value === state);
      valid = Boolean(item) && item.null_fields.every((field) => get(record, field) === null) &&
        item.non_null_fields.every((field) => get(record, field) !== null);
    }
    if (!valid) fail();
  }
}

function validateConsequentialRuleSetConstraints(rows, constraints, fail) {
  for (const constraint of constraints) {
    if (constraint.kind !== "unique_field") continue;
    const values = rows.map(({ record }) => consequentialDigest(record[constraint.field]));
    if (new Set(values).size !== values.length) fail();
  }
}

function registryIds(rows, fail) {
  if (!Array.isArray(rows)) fail();
  const ids = new Set();
  for (const row of rows) {
    if (!isObject(row) || !isNonblankString(row.id) ||
        [...row.id].length > CONSEQUENTIAL_MAX_REFERENCE_LENGTH || ids.has(row.id)) {
      fail();
    }
    ids.add(row.id);
  }
  if (ids.size === 0) fail();
  return ids;
}

function buildConsequentialRegistries(parsedByPath, fail) {
  const core = parsedByPath.get("master-reference/content/atlas-core.json");
  const capability = parsedByPath.get("master-reference/content/capability-catalog.json");
  const delivery = parsedByPath.get("master-reference/content/delivery-governance.json");
  const horizon = parsedByPath.get("master-reference/content/open-horizon-register.json");
  const output = parsedByPath.get("master-reference/content/output-contract.json");
  if (!isObject(core?.traffic_model) || !isObject(core?.system_architecture) ||
      !Array.isArray(capability?.domains) ||
      capability.domains.some((domain) => !isObject(domain) || !Array.isArray(domain.entries))) {
    fail();
  }
  return new Map([
    ["owner_refs", registryIds(core.owners, fail)],
    ["gap_refs", registryIds(delivery?.gaps, fail)],
    ["traffic_plane_refs", registryIds(core.traffic_model.planes, fail)],
    ["system_plane_refs", registryIds(core.system_architecture.planes, fail)],
    ["source_refs", registryIds(horizon?.watch_families, fail)],
    ["affected_capability_refs", registryIds(capability.domains.flatMap((domain) => domain.entries), fail)],
    ["cross_artifact_ids", registryIds(output?.members, fail)],
  ]);
}

function collectConsequentialCandidates(sourceContract, document, sourceOid, registries, fail) {
  const candidates = [];
  const coveredObjects = new Set();
  const groundingContract = sourceContract.grounding;
  const relationships = new Map(
    groundingContract.relationships.map((relationship) => [relationship.field, relationship]),
  );
  const declaredOwnerFields = new Set(groundingContract.declared_owner_fields);
  for (const rule of sourceContract.object_rules) {
    const rows = recordsForConsequentialSelector(document, rule.selector, fail);
    if (rows.length !== rule.expected_records) fail();
    const fieldRules = new Map(rule.fields.map((field) => [field.field, field]));
    const identities = new Set();
    for (const { record, pointer, ancestors } of rows) {
      if (coveredObjects.has(record)) fail();
      coveredObjects.add(record);
      const required = rule.fields.filter((field) => field.required).map((field) => field.field);
      if (required.some((field) => !Object.hasOwn(record, field)) ||
          Object.keys(record).some((field) => !fieldRules.has(field))) {
        fail();
      }
      const identity = rule.identity;
      let semanticIdentity;
      if (identity.kind === "root") {
        semanticIdentity = "@root";
      } else if (identity.kind === "field") {
        semanticIdentity = record[identity.field];
        if (!isNonblankString(semanticIdentity)) fail();
      } else if (identity.kind === "parent_field") {
        semanticIdentity = null;
        for (let index = ancestors.length - 1; index >= 0; index -= 1) {
          if (Object.hasOwn(ancestors[index], identity.field)) {
            semanticIdentity = ancestors[index][identity.field];
            break;
          }
        }
        if (!isNonblankString(semanticIdentity)) fail();
      } else {
        const values = identity.fields.map((field) => record[field]);
        if (values.some((value) => !isNonblankString(value))) fail();
        semanticIdentity = consequentialDigest(values);
      }
      const identityKey = `${rule.record_kind}:${semanticIdentity}`;
      if (identities.has(identityKey)) fail();
      identities.add(identityKey);

      const grounding = [];
      for (const [fieldName, fieldRule] of [...fieldRules.entries()].sort(
        ([left], [right]) => compareUnicodeCodePoints(left, right),
      )) {
        if (!Object.hasOwn(record, fieldName)) continue;
        const value = record[fieldName];
        if (!valueMatchesConsequentialType(value, fieldRule.value_type)) fail();
        if (fieldRule.classification === "relationship_metadata") {
          const relationship = relationships.get(fieldName);
          if (!relationship) fail();
          let references;
          if (relationship.mode === "reference_array") {
            references = validateConsequentialReferences(value, fail);
          } else if (value === null && fieldRule.value_type === "string_or_null") {
            references = [];
          } else if (isNonblankString(value)) {
            references = [value];
          } else {
            fail();
          }
          if (relationship.registry !== null) {
            const registry = registries.get(relationship.registry);
            if (!registry || references.some((reference) => !registry.has(reference))) fail();
          }
          references.forEach((reference) => grounding.push({ field: fieldName, reference }));
        } else if (declaredOwnerFields.has(fieldName)) {
          if (!isNonblankString(value)) fail();
          grounding.push({ field: fieldName, reference: value });
        }
      }
      validateConsequentialConstraints(document, record, rule.constraints, fail);
      const fallback = groundingContract.fallback_owner_ref;
      if (!registries.get("owner_refs")?.has(fallback)) fail();
      if (grounding.length === 0) {
        grounding.push({ field: "@source_owner", reference: fallback });
      }
      if (groundingContract.require_nonempty === true && grounding.length === 0) fail();
      grounding.sort((left, right) =>
        compareUnicodeCodePoints(left.field, right.field) ||
        compareUnicodeCodePoints(left.reference, right.reference));
      const groundingDigest = consequentialDigest(grounding);
      for (const [fieldName, fieldRule] of [...fieldRules.entries()].sort(
        ([left], [right]) => compareUnicodeCodePoints(left, right),
      )) {
        if (fieldRule.classification !== "candidate" || !Object.hasOwn(record, fieldName)) continue;
        const facetIdentity = {
          source_path: sourceContract.path,
          rule_id: rule.rule_id,
          record_kind: rule.record_kind,
          record_identity: semanticIdentity,
          facet_path: fieldName,
        };
        candidates.push({
          facet_id: `urn:atlas:claim-facet:${consequentialDigest(facetIdentity)}`,
          source_path: sourceContract.path,
          source_blob_oid: sourceOid,
          source_pointer: `${pointer}/${fieldName.replaceAll("~", "~0").replaceAll("/", "~1")}`,
          rule_id: rule.rule_id,
          record_kind: rule.record_kind,
          record_identity: semanticIdentity,
          facet_path: fieldName,
          classification: "consequential_claim_candidate",
          claim_kind: fieldRule.claim_kind,
          review_state: "pending_independent_review",
          grounding_digest: groundingDigest,
          value_digest: consequentialDigest(record[fieldName]),
        });
        if (candidates.length > CONSEQUENTIAL_MAX_CANDIDATES) fail();
      }
    }
    validateConsequentialRuleSetConstraints(rows, rule.constraints, fail);
  }
  const declaredChildren = new Set([document]);
  for (const rule of sourceContract.object_rules) {
    const fieldRules = new Map(rule.fields.map((field) => [field.field, field]));
    for (const { record } of recordsForConsequentialSelector(document, rule.selector, fail)) {
      for (const [fieldName, fieldRule] of fieldRules) {
        if (fieldRule.classification !== "container" || !Object.hasOwn(record, fieldName)) continue;
        const value = record[fieldName];
        if (isObject(value)) declaredChildren.add(value);
        if (Array.isArray(value)) value.filter(isObject).forEach((item) => declaredChildren.add(item));
      }
    }
  }
  if (coveredObjects.size !== declaredChildren.size ||
      [...coveredObjects].some((record) => !declaredChildren.has(record)) ||
      candidates.length !== sourceContract.expected_candidates) {
    fail();
  }
  candidates.sort((left, right) => compareUnicodeCodePoints(left.facet_id, right.facet_id));
  return { candidates, ruleSetDigest: consequentialDigest(sourceContract.object_rules) };
}

function validateConsequentialIntegerTokenTypes(completeness, summary, fail) {
  const floatTokenPaths = COMPILER_FLOAT_TOKEN_PATHS.get(completeness);
  const prefix = "/consequential_claim_denominator";
  const integerFields = [
    "source_universe_expected",
    "source_universe_registered",
    "source_universe_unclassified",
    "expected_candidates",
    "discovered_candidates",
    "classified_candidates",
    "independently_reviewed_candidates",
    "unresolved_candidates",
    "compiler_integrity_claims_expected",
    "compiler_integrity_claims_classified",
    "compiler_integrity_claims_consequential",
  ];
  for (const field of integerFields) {
    if (!Number.isSafeInteger(summary[field]) || floatTokenPaths?.has(`${prefix}/${field}`)) {
      fail();
    }
  }
  if (!Array.isArray(summary.source_receipts)) fail();
  for (const [index, receipt] of summary.source_receipts.entries()) {
    if (!isObject(receipt)) fail();
    for (const field of ["bytes", "candidate_count"]) {
      if (
        !Number.isSafeInteger(receipt[field]) ||
        floatTokenPaths?.has(`${prefix}/source_receipts/${index}/${field}`)
      ) {
        fail();
      }
    }
  }
}

export function reconstructConsequentialClaimFacetRecords({
  completeness,
  rawSources,
  claimPredicates,
  unavailableReason = "consequential_claim_contract_absent",
}) {
  const fail = () => {
    throw new Error("compiler consequential-claim census is inconsistent");
  };
  if (!(rawSources instanceof Map)) fail();
  try {
  const summary = completeness?.consequential_claim_denominator;
  const gate = completeness?.acceptance_gates?.find(
    (item) => item?.name === "consequential_claim_denominator_closed",
  );
  const expectedGate = {
    name: "consequential_claim_denominator_closed",
    passed: false,
    expected: true,
    actual: false,
  };
  if (
    !summary ||
    typeof summary !== "object" ||
    Array.isArray(summary) ||
    consequentialCanonicalJson(gate) !== consequentialCanonicalJson(expectedGate) ||
    completeness?.semantic_accounting?.consequential_claim_denominator_state !== summary.state
  ) {
    fail();
  }
  if (!exactStringMembership(claimPredicates, CONSEQUENTIAL_INTEGRITY_PREDICATES)) {
    fail();
  }
  validateConsequentialIntegerTokenTypes(completeness, summary, fail);
  if (summary.state === "not_declared") {
    if (
      consequentialCanonicalJson(summary) !==
        consequentialCanonicalJson(
          unavailableConsequentialClaimSummary(
            completeness.source_commit,
            completeness.source_tree_digest,
            unavailableReason,
          ),
        ) ||
      (unavailableReason === "consequential_claim_contract_absent" &&
        rawSources.has(CONSEQUENTIAL_CLAIM_CONTRACT_PATH))
    ) {
      fail();
    }
    return [];
  }
  if (summary.state !== "declared_incomplete" || rawSources.size !== CONSEQUENTIAL_CLAIM_PATHS.size) {
    fail();
  }

  const parsedByPath = new Map();
  for (const path of CONSEQUENTIAL_CLAIM_PATHS) {
    const source = rawSources.get(path);
    if (
      !source ||
      !Buffer.isBuffer(source.raw) ||
      gitBlobOid(source.raw, source.gitBlobOid) !== source.gitBlobOid
    ) {
      fail();
    }
    parsedByPath.set(path, parseStrictSourceJson(source.raw));
  }
  const contractSource = rawSources.get(CONSEQUENTIAL_CLAIM_CONTRACT_PATH);
  const contract = parsedByPath.get(CONSEQUENTIAL_CLAIM_CONTRACT_PATH);
  if (
    !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(completeness.source_commit) ||
    !/^[0-9a-f]{64}$/.test(completeness.source_tree_digest) ||
    [...rawSources.values()].some(
      (source) => source.gitBlobOid.length !== completeness.source_commit.length,
    ) ||
    !hasExactKeys(contract, ["compiler_integrity_claims", "contract_kind", "schema_version", "source_universe"]) ||
    contract.schema_version !== CONSEQUENTIAL_CLAIM_SCHEMA_VERSION ||
    contract.contract_kind !== CONSEQUENTIAL_CLAIM_KIND ||
    !Array.isArray(contract.source_universe) ||
    contract.source_universe.length !== CONSEQUENTIAL_CLAIM_CONTENT_PATHS.length ||
    !Array.isArray(contract.compiler_integrity_claims) ||
    contract.compiler_integrity_claims.length !== CONSEQUENTIAL_INTEGRITY_PREDICATES.length
  ) {
    fail();
  }

  const integrityPredicates = [];
  for (const item of contract.compiler_integrity_claims) {
    if (
      !item ||
      typeof item !== "object" ||
      Array.isArray(item) ||
      !hasExactKeys(item, ["classification", "consequential", "predicate"]) ||
      typeof item.predicate !== "string" ||
      !item.predicate ||
      integrityPredicates.includes(item.predicate) ||
      item.classification !== "integrity_metadata" ||
      item.consequential !== false
    ) {
      fail();
    }
    integrityPredicates.push(item.predicate);
  }
  if (
    !exactStringMembership(integrityPredicates, CONSEQUENTIAL_INTEGRITY_PREDICATES)
  ) {
    fail();
  }

  const sourceByPath = new Map();
  const allRuleIds = new Set();
  for (const row of contract.source_universe) {
    if (
      !hasExactKeys(row, [
        "path",
        "git_blob_oid",
        "classification",
        "expected_records",
        "expected_candidates",
        "grounding",
        "object_rules",
      ]) ||
      !CONSEQUENTIAL_CLAIM_CONTENT_PATHS.includes(row.path)
    ) {
      fail();
    }
    if (sourceByPath.has(row.path)) fail();
    sourceByPath.set(row.path, row);
    const source = rawSources.get(row.path);
    const { git_blob_oid: _gitBlobOid, ...semanticSpec } = row;
    if (!source || row.git_blob_oid !== source.gitBlobOid ||
        row.classification !== "candidate_census" ||
        row.expected_candidates !== CONSEQUENTIAL_SOURCE_COUNTS[row.path] ||
        consequentialDigest(semanticSpec) !== CONSEQUENTIAL_SOURCE_SPEC_DIGESTS[row.path]) {
      fail();
    }
    validateSourceRuleContract(row, allRuleIds, fail);
  }
  if (sourceByPath.size !== CONSEQUENTIAL_CLAIM_CONTENT_PATHS.length ||
      allRuleIds.size !== 45 ||
      Object.values(CONSEQUENTIAL_SOURCE_COUNTS).reduce((sum, count) => sum + count, 0) !==
        CONSEQUENTIAL_EXPECTED_CANDIDATES) {
    fail();
  }

  const registries = buildConsequentialRegistries(parsedByPath, fail);
  const sourceReceipts = [];
  const allCandidates = [];
  for (const path of CONSEQUENTIAL_CLAIM_CONTENT_PATHS) {
    const source = rawSources.get(path);
    const sourceContract = sourceByPath.get(path);
    const { candidates, ruleSetDigest } = collectConsequentialCandidates(
      sourceContract,
      parsedByPath.get(path),
      source.gitBlobOid,
      registries,
      fail,
    );
    sourceReceipts.push({
      path,
      git_blob_oid: source.gitBlobOid,
      sha256: sha256(source.raw),
      bytes: source.raw.byteLength,
      classification: sourceContract.classification,
      rule_set_digest: ruleSetDigest,
      candidate_count: candidates.length,
      candidate_digest: consequentialDigest(candidates),
    });
    allCandidates.push(...candidates);
  }
  const facetIds = allCandidates.map((candidate) => candidate.facet_id);
  if (new Set(facetIds).size !== facetIds.length ||
      allCandidates.length !== CONSEQUENTIAL_EXPECTED_CANDIDATES) {
    fail();
  }
  allCandidates.sort((left, right) => compareUnicodeCodePoints(left.facet_id, right.facet_id));
  const expected = {
    schema_version: CONSEQUENTIAL_CLAIM_SCHEMA_VERSION,
    denominator_kind: CONSEQUENTIAL_CLAIM_KIND,
    state: "declared_incomplete",
    closed: false,
    source_commit: completeness.source_commit,
    source_tree_digest: completeness.source_tree_digest,
    source_basis: "selected_commit_raw_git_blobs",
    contract_path: CONSEQUENTIAL_CLAIM_CONTRACT_PATH,
    contract_git_blob_oid: contractSource.gitBlobOid,
    contract_digest: sha256(contractSource.raw),
    classification_digest: consequentialDigest({
      source_universe: contract.source_universe,
      compiler_integrity_claims: contract.compiler_integrity_claims,
    }),
    source_universe_expected: 5,
    source_universe_registered: 5,
    source_universe_unclassified: 0,
    source_receipts: sourceReceipts,
    source_receipts_digest: consequentialDigest(sourceReceipts),
    expected_candidates: CONSEQUENTIAL_EXPECTED_CANDIDATES,
    discovered_candidates: CONSEQUENTIAL_EXPECTED_CANDIDATES,
    classified_candidates: CONSEQUENTIAL_EXPECTED_CANDIDATES,
    independently_reviewed_candidates: 0,
    unresolved_candidates: CONSEQUENTIAL_EXPECTED_CANDIDATES,
    candidate_set_digest: consequentialDigest(allCandidates),
    compiler_integrity_claims_expected: 6,
    compiler_integrity_claims_classified: 6,
    compiler_integrity_claims_consequential: 0,
    error_codes: [
      "consequential_claim_independent_review_pending",
      "consequential_claim_rendered_sink_universe_incomplete",
    ],
  };
  if (consequentialCanonicalJson(summary) !== consequentialCanonicalJson(expected)) fail();
  return allCandidates.map((candidate) => ({
    id: stableId("claim-facet-record", candidate.facet_id),
    entity_type: "consequential_claim_facet",
    evidence_state: "payload_omitted_value_fingerprint_index_only",
    ...candidate,
  })).sort((left, right) => compareUnicodeCodePoints(left.id, right.id));
  } catch {
    fail();
  }
}

export function validateConsequentialClaimCensus({
  completeness,
  rawSources,
  claimPredicates,
  facetRecords,
  unavailableReason = "consequential_claim_contract_absent",
}) {
  const fail = () => {
    throw new Error("compiler consequential-claim census is inconsistent");
  };
  try {
    if (!Array.isArray(facetRecords)) fail();
    const expectedRecords = reconstructConsequentialClaimFacetRecords({
      completeness,
      rawSources,
      claimPredicates,
      unavailableReason,
    });
    if (facetRecords.length !== expectedRecords.length) fail();
    const seenFacetIds = new Set();
    const subjects = [];
    let previousId = null;
    for (const record of facetRecords) {
      if (
        !hasExactKeys(record, CONSEQUENTIAL_CLAIM_FACET_RECORD_KEYS) ||
        record.entity_type !== "consequential_claim_facet" ||
        record.evidence_state !== "payload_omitted_value_fingerprint_index_only" ||
        record.id !== stableId("claim-facet-record", record.facet_id) ||
        seenFacetIds.has(record.facet_id) ||
        (previousId !== null && compareUnicodeCodePoints(previousId, record.id) >= 0)
      ) {
        fail();
      }
      seenFacetIds.add(record.facet_id);
      previousId = record.id;
      const { id: _id, entity_type: _entityType, evidence_state: _evidenceState, ...subject } = record;
      subjects.push(subject);
    }
    subjects.sort((left, right) => compareUnicodeCodePoints(left.facet_id, right.facet_id));
    const expectedSubjects = expectedRecords.map(
      ({ id: _id, entity_type: _entityType, evidence_state: _evidenceState, ...subject }) => subject,
    ).sort((left, right) => compareUnicodeCodePoints(left.facet_id, right.facet_id));
    if (
      consequentialCanonicalJson(subjects) !== consequentialCanonicalJson(expectedSubjects) ||
      (subjects.length > 0 &&
        consequentialDigest(subjects) !== completeness?.consequential_claim_denominator?.candidate_set_digest)
    ) {
      fail();
    }
  } catch {
    fail();
  }
}

function compareUnicodeCodePoints(left, right) {
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    const leftPoint = left.codePointAt(leftIndex);
    const rightPoint = right.codePointAt(rightIndex);
    if (leftPoint !== rightPoint) return leftPoint < rightPoint ? -1 : 1;
    leftIndex += leftPoint > 0xFFFF ? 2 : 1;
    rightIndex += rightPoint > 0xFFFF ? 2 : 1;
  }
  return Math.sign((left.length - leftIndex) - (right.length - rightIndex));
}

function pythonFloatToken(value) {
  if (!Number.isFinite(value)) return null;
  if (Object.is(value, -0)) return "-0.0";
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  if (absolute === 0) return "0.0";
  const javascript = absolute.toString().toLowerCase();
  let digits;
  let exponent;
  if (javascript.includes("e")) {
    const [mantissa, rawExponent] = javascript.split("e");
    const dot = mantissa.indexOf(".");
    const integerDigits = dot === -1 ? mantissa.length : dot;
    digits = mantissa.replace(".", "");
    exponent = Number(rawExponent) + integerDigits - 1;
  } else {
    const dot = javascript.indexOf(".");
    const integerDigits = dot === -1 ? javascript.length : dot;
    const unscaled = javascript.replace(".", "");
    const firstNonzero = unscaled.search(/[1-9]/);
    digits = unscaled.slice(firstNonzero);
    exponent = integerDigits - firstNonzero - 1;
  }
  while (digits.length > 1 && digits.endsWith("0")) digits = digits.slice(0, -1);
  if (exponent < -4 || exponent >= 16) {
    const coefficient = digits.length === 1 ? digits : `${digits[0]}.${digits.slice(1)}`;
    const exponentSign = exponent >= 0 ? "+" : "-";
    return `${sign}${coefficient}e${exponentSign}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  let fixed;
  if (exponent < 0) {
    fixed = `0.${"0".repeat(-exponent - 1)}${digits}`;
  } else if (digits.length <= exponent + 1) {
    fixed = `${digits}${"0".repeat(exponent + 1 - digits.length)}.0`;
  } else {
    fixed = `${digits.slice(0, exponent + 1)}.${digits.slice(exponent + 1)}`;
  }
  return `${sign}${fixed}`;
}

function parseCanonicalCompilerJson(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.byteLength === 0 || bytes.byteLength > COMPILER_JSON_MAX_BYTES) {
    throw new Error("compiler JSON exceeds its canonical byte contract");
  }
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Error("compiler JSON is not canonical UTF-8");
  }
  if (!text.endsWith("\n")) throw new Error("compiler JSON is not newline terminated");
  const source = text.slice(0, -1);
  let index = 0;
  let values = 0;
  const numberPattern = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;

  const fail = () => {
    throw new Error("compiler JSON is not canonical");
  };
  const stringValue = () => {
    const start = index;
    index += 1;
    let escaped = false;
    while (index < source.length) {
      const code = source.charCodeAt(index);
      if (!escaped && code === 0x22) {
        index += 1;
        const token = source.slice(start, index);
        if (Buffer.byteLength(token, "utf8") > COMPILER_JSON_MAX_STRING_BYTES) fail();
        let parsed;
        try {
          parsed = JSON.parse(token);
        } catch {
          fail();
        }
        for (let offset = 0; offset < parsed.length; offset += 1) {
          const unit = parsed.charCodeAt(offset);
          if (unit >= 0xD800 && unit <= 0xDBFF) {
            const next = parsed.charCodeAt(offset + 1);
            if (!(next >= 0xDC00 && next <= 0xDFFF)) fail();
            offset += 1;
          } else if (unit >= 0xDC00 && unit <= 0xDFFF) {
            fail();
          }
        }
        if (JSON.stringify(parsed) !== token) fail();
        return parsed;
      }
      if (!escaped && (code < 0x20 || code === 0x5C)) {
        if (code < 0x20) fail();
        escaped = true;
        index += 1;
        continue;
      }
      escaped = false;
      index += 1;
    }
    fail();
  };
  const floatTokenPaths = new Set();
  const value = (depth, pointer) => {
    values += 1;
    if (depth > COMPILER_JSON_MAX_DEPTH || values > COMPILER_JSON_MAX_VALUES) fail();
    const token = source[index];
    if (token === "{") {
      index += 1;
      let previousKey = null;
      if (source[index] === "}") {
        index += 1;
        return;
      }
      while (index < source.length) {
        if (source[index] !== "\"") fail();
        const key = stringValue();
        if (previousKey !== null && compareUnicodeCodePoints(previousKey, key) >= 0) fail();
        previousKey = key;
        if (source[index] !== ":") fail();
        index += 1;
        value(depth + 1, `${pointer}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`);
        if (source[index] === "}") {
          index += 1;
          return;
        }
        if (source[index] !== ",") fail();
        index += 1;
      }
      fail();
    }
    if (token === "[") {
      index += 1;
      if (source[index] === "]") {
        index += 1;
        return;
      }
      let itemIndex = 0;
      while (index < source.length) {
        value(depth + 1, `${pointer}/${itemIndex}`);
        itemIndex += 1;
        if (source[index] === "]") {
          index += 1;
          return;
        }
        if (source[index] !== ",") fail();
        index += 1;
      }
      fail();
    }
    if (token === "\"") {
      stringValue();
      return;
    }
    for (const literal of ["true", "false", "null"]) {
      if (source.startsWith(literal, index)) {
        index += literal.length;
        return;
      }
    }
    numberPattern.lastIndex = index;
    const match = numberPattern.exec(source);
    if (!match) fail();
    const numberToken = match[0];
    if (numberToken.length > 128) fail();
    if (numberToken.includes(".") || /[eE]/.test(numberToken)) {
      if (pythonFloatToken(Number(numberToken)) !== numberToken) fail();
      floatTokenPaths.add(pointer);
    } else {
      let canonicalInteger;
      try {
        canonicalInteger = BigInt(numberToken).toString();
      } catch {
        fail();
      }
      if (canonicalInteger !== numberToken) fail();
    }
    index += numberToken.length;
  };

  value(0, "");
  if (index !== source.length) fail();
  let parsed;
  try {
    parsed = JSON.parse(source);
  } catch {
    fail();
  }
  if (parsed && typeof parsed === "object") {
    COMPILER_FLOAT_TOKEN_PATHS.set(parsed, floatTokenPaths);
  }
  return parsed;
}

function stableId(kind, ...parts) {
  const identity = parts.map(String).join("\u001f");
  return `urn:atlas:${kind}:${sha256(Buffer.from(identity, "utf8")).slice(0, 24)}`;
}

function graphConfidenceIdentity(value) {
  if (value === null) return "none";
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error("Graphify edge confidence must be null or a finite number from zero to one");
  }
  if (Number.isInteger(value)) return `integer:${value}`;
  const bytes = Buffer.allocUnsafe(8);
  bytes.writeDoubleBE(value, 0);
  return `float64:${bytes.toString("hex")}`;
}

function compactRecord(group, record) {
  if (group === "files") {
    return {
      id: record.id,
      path: record.path,
      language: record.language ?? "unknown",
      mediaType: record.media_type ?? "application/octet-stream",
      roles: record.roles ?? [],
      sizeBytes: record.size_bytes ?? 0,
      lineCount: record.line_count ?? 0,
      nonblankLineCount: record.nonblank_line_count ?? 0,
      contentDigest: record.content_digest ?? null,
      gitBlobOid: record.git_blob_oid ?? null,
      contentSource: record.content_source ?? null,
      privacyExposure: record.privacy_exposure ?? "metadata_only",
      privacyReasons: record.privacy_reasons ?? [],
      parseStatus: record.parse_status ?? "unknown",
      parser: record.parser ?? null,
      parserMode: record.parser_mode ?? null,
      parserVersion: record.parser_version ?? null,
      documentationStatus: record.documentation_status ?? null,
      documentationStatusReasons: record.documentation_status_reasons ?? [],
      classificationErrors: record.classification_errors ?? [],
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "symbols") {
    return {
      id: record.id,
      fileId: record.file_id,
      path: record.path,
      name: record.name,
      qualifiedName: record.qualified_name,
      kind: record.kind,
      language: record.language,
      range: record.range,
      exported: Boolean(record.exported),
      digest: record.digest ?? null,
      decorators: record.decorators ?? [],
      syntaxDepth: record.depth ?? null,
      stableUrn: record.stable_urn ?? record.id,
      pathAndRange: record.path_and_range ?? { path: record.path, range: record.range },
      purpose: record.purpose ?? "",
      purposeBasis: record.purpose_basis ?? "not_emitted",
      responsibility: record.responsibility ?? "",
      parametersAndTypes: record.parameters_and_types ?? [],
      returnOrOutput: record.return_or_output ?? null,
      stateRead: record.state_read ?? [],
      stateWritten: record.state_written ?? [],
      externalEffects: record.external_effects ?? [],
      failureAndExceptionBehavior: record.failure_and_exception_behavior ?? "not_emitted",
      abstentionBehavior: record.abstention_behavior ?? "not_emitted",
      callers: record.callers ?? [],
      callerResolution: record.caller_resolution ?? "not_emitted",
      callees: record.callees ?? [],
      dataDependencies: record.data_dependencies ?? [],
      claimsProducedOrConsumed: record.claims_produced_or_consumed ?? [],
      tests: record.tests ?? [],
      testLinkage: record.test_linkage ?? "not_emitted",
      runtimeTraceEvidence: record.runtime_trace_evidence ?? [],
      runtimeTraceState: record.runtime_trace_state ?? "not_emitted",
      performanceCharacteristics: record.performance_characteristics ?? "not_emitted",
      securityBoundary: record.security_boundary ?? "not_emitted",
      downstreamSurfaces: record.downstream_surfaces ?? [],
      limitations: record.limitations ?? [],
      knownImpactIfChanged: record.known_impact_if_changed ?? [],
      history: record.history ?? [],
      criticality: record.criticality ?? "internal",
      explanationDepth: record.explanation_depth ?? 0,
      reviewState: record.review_state ?? "not_emitted",
      derivation:
        record.review_state === "independently_reviewed"
          ? "independently_reviewed"
          : "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "datasets") {
    return {
      id: record.id,
      fileId: record.file_id,
      path: record.path,
      format: record.format ?? "unknown",
      sizeBytes: record.size_bytes ?? 0,
      contentDigest: record.content_digest ?? null,
      structuredRecordCount: record.structured_record_count ?? null,
      derivation: "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "routes" || group === "components") {
    return {
      id: record.id,
      fileId: record.file_id,
      path: record.path,
      name: record.name ?? null,
      route: record.route ?? null,
      method: record.method ?? null,
      handler: record.handler ?? null,
      framework: record.framework ?? null,
      kind: record.kind ?? null,
      entityType: record.entity_type ?? (group === "routes" ? "route" : "component"),
      range: record.range ?? null,
      attributeNames: record.attribute_names ?? [],
      gui_dossier: record.gui_dossier,
      derivation: "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "tests") {
    return {
      id: record.id,
      fileId: record.file_id,
      path: record.path,
      name: record.name,
      framework: record.framework ?? "unknown",
      range: record.range ?? null,
      entityType: record.entity_type ?? "test_case",
      assertionGroupId: record.assertion_group_id ?? null,
      assertionCount: record.assertion_count ?? null,
      assertions: record.assertions ?? [],
      extractionDisposition: record.extraction_disposition ?? "not_emitted",
      derivation: "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "workflows") {
    return {
      id: record.id,
      fileId: record.file_id,
      path: record.path,
      name: record.name ?? record.path,
      entityType: record.entity_type ?? "workflow",
      jobs: record.jobs ?? [],
      triggers: record.triggers ?? [],
      jobIds: record.job_ids ?? [],
      stepIds: record.step_ids ?? [],
      permissionIds: record.permission_ids ?? [],
      artifactIds: record.artifact_ids ?? [],
      steps: record.steps ?? [],
      permissions: record.permissions ?? [],
      artifacts: record.artifacts ?? [],
      job: record.job ?? null,
      stepIndex: record.step_index ?? null,
      uses: record.uses ?? null,
      runDeclared: record.run_declared ?? null,
      sourceDigest: record.source_digest ?? null,
      scope: record.scope ?? null,
      access: record.access ?? null,
      stepId: record.step_id ?? null,
      direction: record.direction ?? null,
      declaredPath: record.declared_path ?? null,
      action: record.action ?? null,
      range: record.range ?? null,
      parserMode: record.parser_mode ?? "structural",
      extractionDisposition: record.extraction_disposition ?? "not_emitted",
      derivation: "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "claims") {
    return {
      id: record.id,
      subject: record.subject,
      predicate: record.predicate,
      value: record.value,
      unit: record.unit ?? null,
      basis: record.basis,
      scope: record.scope ?? {},
      effectiveTime: record.effective_time ?? null,
      recordedTime: record.recorded_time ?? null,
      temporalBasis: record.temporal_basis ?? "not_emitted",
      owner: record.owner,
      evidenceIds: record.evidence_ids ?? [],
      evidenceClass: record.evidence_class ?? "not_emitted",
      transformation: record.transformation ?? null,
      denominator: record.denominator ?? null,
      verdict: record.verdict ?? "indeterminate",
      freshness: record.freshness ?? "unknown",
      lineage: record.lineage ?? [],
      derivedFrom: record.derived_from ?? [],
      origin: record.origin ?? "not_emitted",
      extractionMode: record.extraction_mode ?? "not_emitted",
      confidence: record.confidence ?? null,
      status: record.status ?? "unknown",
      revokedBy: record.revoked_by ?? null,
      revocationReason: record.revocation_reason ?? null,
      conflictsWith: record.conflicts_with ?? [],
      currentView: Boolean(record.current_view),
      satisfiesEvidenceRequirement: Boolean(record.satisfies_evidence_requirement),
      sourceCommit: record.source_commit ?? null,
      derivation: "compiler_structural",
      unresolvedReasons: record.unresolved_reasons ?? [],
    };
  }
  if (group === "consequential_claim_facets") {
    return {
      ...record,
      derivation: "payload_omitted_value_fingerprint_index_only",
    };
  }
  if (group === "graph_nodes") {
    return {
      id: record.id,
      graphify_id: record.graphify_id,
      coordinate_occurrence: record.coordinate_occurrence,
      file_id: record.file_id,
      source_file: record.source_file,
      source_location: record.source_location,
      label: record.label,
      file_type: record.file_type,
      language: record.language,
      kind: record.kind,
      community: record.community,
      origin: record.origin,
      extraction_mode: record.extraction_mode,
      entity_type: record.entity_type,
      unresolved_reasons: record.unresolved_reasons,
    };
  }
  if (group === "graph_edges") {
    return {
      id: record.id,
      source: record.source,
      target: record.target,
      relation: record.relation,
      coordinate_occurrence: record.coordinate_occurrence,
      source_file: record.source_file,
      source_location: record.source_location,
      extraction_mode: record.extraction_mode,
      confidence: record.confidence,
      entity_type: record.entity_type,
      unresolved_reasons: record.unresolved_reasons,
    };
  }
  const safeMetadata = Object.fromEntries(
    Object.entries(record).filter(([key]) => key !== "text_preview"),
  );
  return {
    ...safeMetadata,
    derivation: "compiler_structural",
  };
}

function safeRelative(value) {
  if (
    typeof value !== "string" ||
    !value ||
    value.length > 4096 ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value)
  ) {
    throw new Error("compiler input path is unsafe");
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error("compiler input path is unsafe");
  }
  return parts;
}

async function safeInputPath(input, relative) {
  const parts = safeRelative(relative);
  let current = input;
  for (const [index, part] of parts.entries()) {
    current = join(current, part);
    let info;
    try {
      info = await lstat(current);
    } catch {
      throw new Error("compiler input path metadata read failed");
    }
    if (info.isSymbolicLink()) throw new Error("symlink compiler input refused");
    if (index < parts.length - 1 && !info.isDirectory()) {
      throw new Error("compiler input path parent is not a directory");
    }
  }
  const absolute = resolve(current);
  let finalInfo;
  try {
    finalInfo = await lstat(absolute);
  } catch {
    throw new Error("compiler input path metadata read failed");
  }
  if (!absolute.startsWith(`${input}${sep}`) || !finalInfo.isFile()) {
    throw new Error("compiler input is not a contained regular file");
  }
  return absolute;
}

async function readBoundedCompilerJson(path) {
  let before;
  let handle;
  try {
    before = await lstat(path);
    if (!before.isFile() || before.size < 1 || before.size > COMPILER_JSON_MAX_BYTES) {
      throw new Error("bounded compiler JSON metadata is invalid");
    }
    handle = await open(path, "r");
    const buffer = Buffer.allocUnsafe(Math.min(before.size + 1, COMPILER_JSON_MAX_BYTES + 1));
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(buffer, offset, buffer.length - offset, offset);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    const after = await handle.stat();
    if (
      !after.isFile() ||
      after.size !== before.size ||
      after.mtimeMs !== before.mtimeMs ||
      offset !== after.size
    ) {
      throw new Error("bounded compiler JSON changed during read");
    }
    return buffer.subarray(0, offset);
  } catch {
    throw new Error("bounded compiler JSON read failed");
  } finally {
    try {
      await handle?.close();
    } catch {
      // The caller receives only the fixed bounded-read disposition.
    }
  }
}

async function readCanonicalJson(input, relative) {
  const path = await safeInputPath(input, relative);
  let bytes;
  try {
    bytes = await readBoundedCompilerJson(path);
  } catch {
    throw new Error("compiler JSON read failed");
  }
  try {
    return { bytes, parsed: parseCanonicalCompilerJson(bytes) };
  } catch {
    throw new Error("compiler JSON is not canonical");
  }
}

async function readVerified(input, descriptor, expectedPath) {
  if (
    !descriptor ||
    typeof descriptor !== "object" ||
    descriptor.path !== expectedPath ||
    typeof descriptor.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(descriptor.sha256) ||
    !Number.isSafeInteger(descriptor.bytes) ||
    descriptor.bytes < 1 ||
    descriptor.bytes > COMPILER_JSON_MAX_BYTES
  ) {
    throw new Error("compiler receipt is malformed");
  }
  const path = await safeInputPath(input, descriptor.path);
  let bytes;
  try {
    bytes = await readBoundedCompilerJson(path);
  } catch {
    throw new Error("compiler receipt read failed");
  }
  const actualDigest = sha256(bytes);
  if (actualDigest !== descriptor.sha256) {
    throw new Error("compiler receipt digest mismatch");
  }
  if (bytes.byteLength !== descriptor.bytes) {
    throw new Error("compiler receipt byte-count mismatch");
  }
  let parsed;
  try {
    parsed = parseCanonicalCompilerJson(bytes);
  } catch {
    throw new Error("compiler receipt is not canonical JSON");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("compiler receipt is not a JSON object");
  }
  return parsed;
}

async function loadGroup(
  input,
  manifest,
  group,
  { retain = true, seenIds = null, onRecord = null } = {},
) {
  const descriptor = manifest.groups?.[group];
  if (!descriptor) throw new Error(`compiler manifest is missing required group: ${group}`);
  const records = [];
  const effectiveChunkSize = group === "source_text" ? 1 : manifest.chunk_size;
  const expectedChunkCount =
    Number.isSafeInteger(descriptor?.record_count) &&
    Number.isSafeInteger(effectiveChunkSize) &&
    effectiveChunkSize > 0
      ? Math.ceil(descriptor.record_count / effectiveChunkSize)
      : -1;
  if (
    !Number.isSafeInteger(descriptor.record_count) ||
    descriptor.record_count < 0 ||
    !Number.isSafeInteger(descriptor.chunk_count) ||
    descriptor.chunk_count < 0 ||
    !Array.isArray(descriptor.chunks) ||
    descriptor.chunk_count !== descriptor.chunks?.length ||
    descriptor.chunk_count !== expectedChunkCount ||
    typeof descriptor.records_digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(descriptor.records_digest)
  ) {
    throw new Error(`compiler group descriptor is malformed: ${group}`);
  }
  const recordIds = [];
  const groupIds = new Set();
  for (const [chunkIndex, chunk] of descriptor.chunks.entries()) {
    const expectedChunkRecords = Math.min(
      effectiveChunkSize,
      descriptor.record_count - chunkIndex * effectiveChunkSize,
    );
    if (
      !Number.isSafeInteger(chunk?.record_count) ||
      chunk.record_count !== expectedChunkRecords
    ) {
      throw new Error(`compiler chunk descriptor is malformed: ${group}:${chunkIndex}`);
    }
    const parsed = await readVerified(
      input,
      chunk,
      `chunks/${group}/${String(chunkIndex).padStart(5, "0")}.json`,
    );
    if (
      !hasExactObjectKeys(parsed, [
        "schema_version", "record_type", "source_commit", "source_tree_digest", "chunk_index",
        "chunk_count", "record_count", "records_digest", "records",
      ]) ||
      parsed.schema_version !== COMPILER_SCHEMA_VERSION ||
      parsed.record_type !== group ||
      parsed.source_commit !== manifest.source_commit ||
      parsed.source_tree_digest !== manifest.source_tree_digest ||
      parsed.chunk_index !== chunkIndex ||
      parsed.chunk_count !== descriptor.chunk_count ||
      !Array.isArray(parsed.records) ||
      parsed.record_count !== parsed.records.length
    ) {
      throw new Error("compiler chunk envelope mismatch");
    }
    if (parsed.records.length !== chunk.record_count) {
      throw new Error("compiler chunk record-count mismatch");
    }
    const chunkRecordIds = [];
    for (const record of parsed.records) {
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        throw new Error("compiler chunk contains a non-object record");
      }
      const allowedRecordKeys = COMPILER_RECORD_KEYS_BY_GROUP[group];
      if (
        !(allowedRecordKeys instanceof Set) ||
        Object.keys(record).some((key) => !allowedRecordKeys.has(key))
      ) {
        throw new Error("compiler record contains an undeclared field");
      }
      if (
        group === "graph_nodes" &&
        !hasExactObjectKeys(record, [
          "id", "graphify_id", "coordinate_occurrence", "file_id", "source_file",
          "source_location", "label", "file_type", "language", "kind", "community",
          "origin", "extraction_mode", "entity_type", "unresolved_reasons",
        ])
      ) {
        throw new Error("compiler graph node record shape is malformed");
      }
      if (
        group === "graph_edges" &&
        !hasExactObjectKeys(record, [
          "id", "source", "target", "relation", "coordinate_occurrence", "source_file",
          "source_location", "extraction_mode", "confidence", "entity_type",
          "unresolved_reasons",
        ])
      ) {
        throw new Error("compiler graph edge record shape is malformed");
      }
      if (
        group === "consequential_claim_facets" &&
        !hasExactObjectKeys(record, CONSEQUENTIAL_CLAIM_FACET_RECORD_KEYS)
      ) {
        throw new Error("compiler consequential-claim facet record shape is malformed");
      }
      const id = record.id;
      if (typeof id !== "string" || id.length > 128 || !ATLAS_STABLE_ID_PATTERN.test(id)) {
        throw new Error("compiler record lacks a stable ID");
      }
      if (groupIds.has(id)) {
        throw new Error("duplicate stable record ID in compiler group");
      }
      if (recordIds.length > 0 && id <= recordIds.at(-1)) {
        throw new Error("compiler group stable IDs are not in canonical ascending order");
      }
      const previousGroup = seenIds?.get(id);
      if (previousGroup) {
        throw new Error("duplicate stable record ID across compiler groups");
      }
      groupIds.add(id);
      seenIds?.set(id, group);
      recordIds.push(id);
      chunkRecordIds.push(id);
      if (retain) records.push(record);
      if (onRecord) await onRecord(record);
    }
    if (parsed.records_digest !== digestObject(chunkRecordIds)) {
      throw new Error("compiler chunk record identity digest mismatch");
    }
  }
  if (
    recordIds.length !== descriptor.record_count ||
    digestObject(recordIds) !== descriptor.records_digest
  ) {
    throw new Error(`record-count mismatch for ${group}`);
  }
  return records;
}

function validateClaimEvidenceSubjectSeparation(claimRecords, seenIds) {
  for (const claim of claimRecords) {
    if (
      claim.evidence_ids.some(
        (evidenceId) => seenIds.get(evidenceId) === "consequential_claim_facets",
      )
    ) {
      throw new Error("compiler claim evidence references a consequential-claim facet subject");
    }
  }
}

function requireCount(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative safe integer`);
  }
  return value;
}

function sortedUniqueStrings(value, label, { nonempty = false } = {}) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item)) {
    throw new Error(`${label} must be an array of nonempty strings`);
  }
  if (nonempty && value.length === 0) throw new Error(`${label} must not be empty`);
  const canonical = [...new Set(value)].sort();
  if (stableJson(value) !== stableJson(canonical)) {
    throw new Error(`${label} must be sorted and duplicate-free`);
  }
  return canonical;
}

function validateCompilerContract(manifest, completeness, graphify) {
  if (manifest.schema_version !== COMPILER_SCHEMA_VERSION) {
    throw new Error("unsupported compiler manifest schema_version");
  }
  if (completeness.schema_version !== COMPILER_SCHEMA_VERSION) {
    throw new Error("unsupported compiler completeness schema_version");
  }
  if (graphify.schema_version !== COMPILER_SCHEMA_VERSION) {
    throw new Error("unsupported compiler Graphify schema_version");
  }
  if (!manifest.groups || typeof manifest.groups !== "object" || Array.isArray(manifest.groups)) {
    throw new Error("compiler manifest groups are absent or malformed");
  }
  if (!Number.isSafeInteger(manifest.chunk_size) || manifest.chunk_size < 1 || manifest.chunk_size > 100_000) {
    throw new Error("compiler manifest chunk_size is malformed");
  }
  const missingGroups = REQUIRED_COMPILER_GROUPS.filter((group) => !manifest.groups[group]);
  if (missingGroups.length) {
    throw new Error(`compiler manifest is missing required group(s): ${missingGroups.join(", ")}`);
  }
  const declaredGroups = Object.keys(manifest.groups).sort();
  const contractGroups = [...REQUIRED_COMPILER_GROUPS].sort();
  if (stableJson(declaredGroups) !== stableJson(contractGroups)) {
    throw new Error("compiler manifest record groups do not exactly match schema 1.2.0");
  }
  if (!completeness.record_counts || typeof completeness.record_counts !== "object") {
    throw new Error("compiler completeness record_counts are absent or malformed");
  }
  for (const [group, descriptor] of Object.entries(manifest.groups)) {
    const manifestCount = requireCount(descriptor?.record_count, `manifest ${group} record_count`);
    const completenessCount = requireCount(
      completeness.record_counts[group],
      `completeness ${group} record_count`,
    );
    if (manifestCount !== completenessCount) {
      throw new Error(`manifest/completeness record denominator differs for ${group}`);
    }
  }
  const invariants = completeness.invariants;
  if (!Array.isArray(invariants) || invariants.length === 0) {
    throw new Error("compiler completeness invariants are absent");
  }
  const invariantByName = new Map();
  for (const invariant of invariants) {
    const name = invariant?.name;
    if (typeof name !== "string" || !name || invariantByName.has(name)) {
      throw new Error("compiler completeness invariant names are invalid or duplicated");
    }
    if (invariant.passed !== true) {
      throw new Error("compiler completeness invariant did not pass");
    }
    invariantByName.set(name, invariant);
  }
  for (const name of REQUIRED_INVARIANTS) {
    const invariant = invariantByName.get(name);
    if (!invariant) throw new Error(`required compiler invariant is absent: ${name}`);
    const expected = requireCount(invariant.expected, `${name} expected`);
    const actual = requireCount(invariant.actual, `${name} actual`);
    if (expected !== actual) throw new Error(`required compiler invariant denominator differs: ${name}`);
  }
  const acceptanceGates = completeness.acceptance_gates;
  if (!Array.isArray(acceptanceGates)) {
    throw new Error("compiler semantic acceptance gates are absent");
  }
  const acceptanceNames = [];
  const seenAcceptanceNames = new Set();
  for (const gate of acceptanceGates) {
    const name = gate?.name;
    if (
      typeof name !== "string" ||
      !name ||
      seenAcceptanceNames.has(name) ||
      typeof gate.passed !== "boolean" ||
      !(typeof gate.expected === "boolean" || Number.isSafeInteger(gate.expected) || gate.expected === null) ||
      !(typeof gate.actual === "boolean" || Number.isSafeInteger(gate.actual) || gate.actual === null)
    ) {
      throw new Error("compiler semantic acceptance gates are malformed or duplicated");
    }
    seenAcceptanceNames.add(name);
    acceptanceNames.push(name);
  }
  if (
    stableJson(acceptanceNames.sort()) !==
    stableJson([...REQUIRED_ACCEPTANCE_GATES].sort())
  ) {
    throw new Error("compiler semantic acceptance gate registry differs from schema 1.2.0");
  }
  return invariantByName;
}

function validateGuiCitation(citation, label) {
  if (
    !citation ||
    typeof citation !== "object" ||
    Array.isArray(citation) ||
    typeof citation.record_id !== "string" ||
    !citation.record_id ||
    typeof citation.path !== "string" ||
    !citation.path ||
    typeof citation.evidence_role !== "string" ||
    !citation.evidence_role ||
    !["source_range", "source_line_not_resolved", "not_applicable_binary"].includes(citation.line_state)
  ) {
    throw new Error(`${label} is malformed`);
  }
  if (citation.line_state === "source_range") {
    if (
      !Number.isSafeInteger(citation.start_line) ||
      citation.start_line < 1 ||
      !Number.isSafeInteger(citation.end_line) ||
      citation.end_line < citation.start_line
    ) {
      throw new Error(`${label} has an invalid source range`);
    }
  } else if (citation.start_line !== null || citation.end_line !== null) {
    throw new Error(`${label} has line numbers without source-range evidence`);
  }
}

function validateGuiDossier(record, group, manifest, dossierIds) {
  const dossier = record.gui_dossier;
  const surfaceKind = group === "routes" ? "route" : "component";
  if (
    !dossier ||
    typeof dossier !== "object" ||
    Array.isArray(dossier) ||
    typeof dossier.id !== "string" ||
    !dossier.id ||
    dossierIds.has(dossier.id) ||
    dossier.surface_id !== record.id ||
    dossier.surface_kind !== surfaceKind ||
    dossier.source_commit !== manifest.source_commit ||
    dossier.derivation !== "compiler_structural_evidence_only" ||
    dossier.field_count !== GUI_DOSSIER_FIELDS.length ||
    !GUI_EVIDENCE_STATES.has(dossier.evidence_state)
  ) {
    throw new Error(`stale or malformed GUI dossier for ${group}:${String(record.id)}`);
  }
  dossierIds.add(dossier.id);
  validateGuiCitation(dossier.source_citation, `GUI dossier source citation ${record.id}`);
  if (
    dossier.source_citation.record_id !== record.id ||
    dossier.source_citation.path !== record.path ||
    dossier.source_citation.line_state !== "source_range"
  ) {
    throw new Error(`GUI dossier source citation is not bound to its surface: ${record.id}`);
  }
  const fieldGapIds = new Set();
  const fieldReasons = new Set();
  let aggregateState = "not_evidenced";
  for (const name of GUI_DOSSIER_FIELDS) {
    const field = dossier[name];
    if (
      !field ||
      typeof field !== "object" ||
      Array.isArray(field) ||
      !Object.hasOwn(field, "value") ||
      !GUI_EVIDENCE_STATES.has(field.state) ||
      !Array.isArray(field.citations)
    ) {
      throw new Error(`GUI dossier field is absent or malformed: ${record.id}:${name}`);
    }
    const reasons = sortedUniqueStrings(
      field.unresolved_reasons,
      `GUI dossier unresolved_reasons ${record.id}:${name}`,
      { nonempty: true },
    );
    const gapIds = sortedUniqueStrings(
      field.gap_ids,
      `GUI dossier gap_ids ${record.id}:${name}`,
      { nonempty: true },
    );
    if (field.state !== "not_evidenced" && field.citations.length === 0) {
      throw new Error(`GUI dossier evidence state lacks a citation: ${record.id}:${name}`);
    }
    for (const [index, citation] of field.citations.entries()) {
      validateGuiCitation(citation, `GUI dossier citation ${record.id}:${name}:${index}`);
    }
    for (const reason of reasons) fieldReasons.add(reason);
    for (const gapId of gapIds) fieldGapIds.add(gapId);
    if (field.state === "explicitly_linked") aggregateState = "explicitly_linked";
    else if (field.state === "structural_only" && aggregateState === "not_evidenced") {
      aggregateState = "structural_only";
    }
  }
  const dossierReasons = sortedUniqueStrings(
    dossier.unresolved_reasons,
    `GUI dossier unresolved_reasons ${record.id}`,
    { nonempty: true },
  );
  const dossierGapIds = sortedUniqueStrings(
    dossier.gap_ids,
    `GUI dossier gap_ids ${record.id}`,
    { nonempty: true },
  );
  if (
    dossier.evidence_state !== aggregateState ||
    stableJson(dossierReasons) !== stableJson([...fieldReasons].sort()) ||
    stableJson(dossierGapIds) !== stableJson([...fieldGapIds].sort())
  ) {
    throw new Error(`GUI dossier aggregate state or disposition is stale: ${record.id}`);
  }
}

function assertSafeDestination(output) {
  const absolute = resolve(output);
  const root = resolve(absolute, sep);
  if (absolute === root || basename(absolute) === "public") {
    throw new Error(`refusing broad projection destination: ${absolute}`);
  }
  return absolute;
}

async function replaceGeneratedDirectory(staging, output) {
  try {
    await access(output);
    const marker = join(output, GENERATED_MARKER);
    await access(marker);
    const info = await stat(output);
    if (!info.isDirectory()) throw new Error(`${output} is not a directory`);
    await rm(output, { recursive: true, force: false });
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  await rename(staging, output);
}

function moduleText(name, value) {
  return `export const ${name} = ${stableJson(value)};\nexport default ${name};\n`;
}

function upperBoundIndex(upperBounds, id) {
  if (!Array.isArray(upperBounds) || typeof id !== "string") return -1;
  let low = 0;
  let high = upperBounds.length;
  while (low < high) {
    const midpoint = low + Math.floor((high - low) / 2);
    if (upperBounds[midpoint] < id) low = midpoint + 1;
    else high = midpoint;
  }
  return low < upperBounds.length ? low : -1;
}

export function validateSymbolMetadataRoute(
  route,
  metadataEntries,
  moduleRecordIds,
  expected,
) {
  const fail = () => {
    throw new Error("symbol metadata route is absent or inconsistent");
  };
  if (
    !hasExactObjectKeys(route, [
      "entries",
      "entriesDigest",
      "group",
      "kind",
      "moduleCount",
      "orderedIdsDigest",
      "recordCount",
      "upperBoundsDigest",
    ]) ||
    !hasExactObjectKeys(expected, ["recordCount", "recordsDigest"]) ||
    route.group !== "symbols" ||
    route.kind !== "metadata_module_upper_bound_route_v1" ||
    !Array.isArray(route.entries) ||
    !Array.isArray(metadataEntries) ||
    !Array.isArray(moduleRecordIds) ||
    !Number.isSafeInteger(expected.recordCount) ||
    expected.recordCount < 0 ||
    typeof expected.recordsDigest !== "string" ||
    !/^[0-9a-f]{64}$/.test(expected.recordsDigest) ||
    route.moduleCount !== metadataEntries.length ||
    route.moduleCount !== moduleRecordIds.length ||
    route.entries.length !== route.moduleCount ||
    route.recordCount !== expected.recordCount ||
    route.orderedIdsDigest !== expected.recordsDigest
  ) {
    fail();
  }

  const orderedIds = [];
  const upperBounds = [];
  let previousId = null;
  for (let index = 0; index < route.entries.length; index += 1) {
    const receipt = route.entries[index];
    const metadata = metadataEntries[index];
    const ids = moduleRecordIds[index];
    if (
      !hasExactObjectKeys(receipt, [
        "bytes",
        "lowerId",
        "module",
        "moduleOrdinal",
        "recordCount",
        "sha256",
        "upperId",
      ]) ||
      !metadata ||
      metadata.group !== "symbols" ||
      typeof metadata.module !== "string" ||
      !metadata.module.startsWith("metadata/symbols/") ||
      typeof metadata.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(metadata.sha256) ||
      !Number.isSafeInteger(metadata.bytes) ||
      metadata.bytes < 0 ||
      !Array.isArray(ids) ||
      ids.length === 0 ||
      receipt.moduleOrdinal !== index ||
      receipt.module !== metadata.module ||
      receipt.sha256 !== metadata.sha256 ||
      receipt.bytes !== metadata.bytes ||
      receipt.recordCount !== ids.length ||
      receipt.recordCount !== metadata.recordCount ||
      receipt.lowerId !== ids[0] ||
      receipt.upperId !== ids.at(-1)
    ) {
      fail();
    }
    for (const id of ids) {
      if (
        typeof id !== "string" ||
        !/^urn:atlas:symbol:[0-9a-f]{24}$/.test(id) ||
        (previousId !== null && id <= previousId)
      ) {
        fail();
      }
      previousId = id;
      orderedIds.push(id);
    }
    upperBounds.push(receipt.upperId);
  }
  if (
    orderedIds.length !== expected.recordCount ||
    digestObject(orderedIds) !== expected.recordsDigest ||
    route.entriesDigest !== digestObject(route.entries) ||
    route.upperBoundsDigest !== digestObject(upperBounds) ||
    upperBounds.some((bound, index) => index > 0 && bound <= upperBounds[index - 1])
  ) {
    fail();
  }
  for (let moduleIndex = 0; moduleIndex < moduleRecordIds.length; moduleIndex += 1) {
    for (const id of moduleRecordIds[moduleIndex]) {
      if (upperBoundIndex(upperBounds, id) !== moduleIndex) fail();
    }
  }
  return route;
}

function buildSymbolMetadataRoute(metadataEntries, moduleRecordIds, expected) {
  const entries = moduleRecordIds.map((ids, moduleOrdinal) => ({
    moduleOrdinal,
    module: metadataEntries[moduleOrdinal]?.module ?? null,
    bytes: metadataEntries[moduleOrdinal]?.bytes ?? null,
    sha256: metadataEntries[moduleOrdinal]?.sha256 ?? null,
    lowerId: ids[0] ?? null,
    upperId: ids.at(-1) ?? null,
    recordCount: ids.length,
  }));
  const route = {
    kind: "metadata_module_upper_bound_route_v1",
    group: "symbols",
    moduleCount: entries.length,
    recordCount: expected.recordCount,
    orderedIdsDigest: expected.recordsDigest,
    entriesDigest: digestObject(entries),
    upperBoundsDigest: digestObject(entries.map((entry) => entry.upperId)),
    entries,
  };
  return validateSymbolMetadataRoute(
    route,
    metadataEntries,
    moduleRecordIds,
    expected,
  );
}

function getRecordFragmentPlan(record, registry) {
  const id = String(record?.id ?? "");
  if (!id) throw new Error("cannot fragment a record without a stable ID");
  const serialized = stableJson(record);
  const serializedDigest = sha256(Buffer.from(serialized, "utf8"));
  const existing = registry.get(id);
  if (existing) {
    if (existing.serializedDigest !== serializedDigest) {
      throw new Error(`stable record ID resolves to different projected content: ${id}`);
    }
    return existing;
  }
  const fragments = splitUtf8(serialized, RECORD_FRAGMENT_TEXT_BYTES).map((text, index) => {
    const bytes = Buffer.from(moduleText("recordFragment", text), "utf8");
    if (bytes.byteLength > LAZY_MODULE_MAX_BYTES) {
      throw new Error(`record fragment ${id}:${index} exceeds ${LAZY_MODULE_MAX_BYTES} bytes`);
    }
    const digest = sha256(bytes);
    return {
      index,
      module: `fragments/${sha256(id).slice(0, 24)}-${serializedDigest.slice(0, 16)}/${String(index).padStart(5, "0")}-${digest.slice(0, 16)}.mjs`,
      bytes: bytes.byteLength,
      textBytes: Buffer.byteLength(text, "utf8"),
      sha256: digest,
      value: bytes,
    };
  });
  const plan = {
    id,
    serializedBytes: Buffer.byteLength(serialized, "utf8"),
    serializedDigest,
    fragments,
  };
  registry.set(id, plan);
  return plan;
}

function fragmentedRecordIndexText(plan, { dossier = false } = {}) {
  const loaderText = plan.fragments
    .map((fragment) => `() => import(${JSON.stringify(`../../${fragment.module}`)})`)
    .join(",");
  return (
    "export const records = Object.freeze([]);\n" +
    `const expectedId = ${JSON.stringify(plan.id)};\n` +
    `const expectedFragmentCount = ${plan.fragments.length};\n` +
    `const fragmentLoaders = Object.freeze([${loaderText}]);\n` +
    "export async function loadRecords() {\n" +
    "  const modules = await Promise.all(fragmentLoaders.map((loader) => loader()));\n" +
    "  if (modules.length !== expectedFragmentCount) throw new Error(`fragment denominator differs for ${expectedId}`);\n" +
    "  const serialized = modules.map((module) => module.recordFragment ?? module.default).join(\"\");\n" +
    "  const record = JSON.parse(serialized);\n" +
    "  if (!record || record.id !== expectedId) throw new Error(`fragmented record identity differs for ${expectedId}`);\n" +
    "  return [record];\n" +
    "}\n" +
    (dossier
      ? "export async function loadFragmentedRecord(id) { return id === expectedId ? (await loadRecords())[0] : null; }\n"
      : "")
  );
}

function fnv1a(value) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function lexicalValue(value) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(lexicalValue).join(" ");
  return "";
}

function lexicalWords(value) {
  return [...new Set(value.toLowerCase().match(/[a-z0-9_.:/-]{2,}/g) ?? [])];
}

function encodedSourceHref(path, line) {
  const encoded = String(path).split("/").map(encodeURIComponent).join("/");
  return `/source/${encoded}${line ? `#L${line}` : ""}`;
}

function searchDocument(group, record) {
  const id = lexicalValue(record.id).trim();
  if (!id) return null;
  const path = lexicalValue(record.path).trim();
  const title = [
    record.qualifiedName,
    record.name,
    record.predicate,
    record.callee,
    record.module,
    record.route,
    path,
    id,
  ].map(lexicalValue).find((value) => value.trim()) ?? id;
  const dossierKind = group === "datasets" || group === "routes" || group === "components"
    ? "data"
    : group === "claims"
      ? "claim"
      : group.endsWith("s")
        ? group.slice(0, -1)
        : group;
  const hasDossier = ["symbol", "data", "test", "workflow", "claim"].includes(dossierKind);
  const startLine = typeof record.range?.start_line === "number" ? record.range.start_line : null;
  const detail = [
    path,
    record.kind,
    record.language,
    record.verdict,
    record.freshness,
    record.ecosystem,
    record.scope,
    record.runtimeTraceState,
  ].map(lexicalValue).filter(Boolean).join(" · ");
  const searchable = [
    id,
    path,
    record.name,
    record.qualifiedName,
    record.route,
    record.kind,
    record.language,
    record.purpose,
    record.predicate,
    record.subject,
    record.module,
    record.names,
    record.alias,
    record.callee,
    record.containing_symbol,
    record.ecosystem,
    record.scope,
    record.constraint,
    record.resolved_version,
    record.runtimeTraceState,
    record.tests,
    record.evidenceIds,
    record.unresolvedReasons,
    record.unresolved_reasons,
  ].map(lexicalValue).join(" ");
  return {
    document: {
      id,
      kind: group,
      title,
      detail,
      href: hasDossier
        ? `/${dossierKind}/${encodeURIComponent(id)}`
        : path
          ? encodedSourceHref(path, startLine)
          : `/ask?q=${encodeURIComponent(id)}`,
    },
    terms: lexicalWords(searchable),
  };
}

function splitSearchBucket(entries, prefix, splitPrefixes, shards) {
  const value = Object.fromEntries(entries.map(([term, posting]) => [term, posting]));
  const bytes = Buffer.from(moduleText("terms", value), "utf8");
  if (bytes.byteLength <= SEARCH_SHARD_MAX_BYTES) {
    shards.push({ prefix, value, bytes });
    return;
  }
  if (prefix.length >= 8) {
    throw new Error(`search shard ${prefix} exceeds ${SEARCH_SHARD_MAX_BYTES} bytes`);
  }
  splitPrefixes.add(prefix);
  const children = Map.groupBy(entries, ([term]) => fnv1a(term).slice(0, prefix.length + 1));
  for (const [child, childEntries] of [...children.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    splitSearchBucket(childEntries, child, splitPrefixes, shards);
  }
}

async function writeSearchProjection(staging, groups) {
  const postings = new Map();
  const documentsByKey = new Map();
  const groupRecordCounts = {};
  const indexedRecordCounts = {};
  for (const group of SEARCH_GROUPS) {
    const records = groups[group] ?? [];
    groupRecordCounts[group] = records.length;
    let indexed = 0;
    for (const record of records) {
      const projected = searchDocument(group, record);
      if (!projected) continue;
      indexed += 1;
      const documentKey = `${group}:${projected.document.id}`;
      const priorDocument = documentsByKey.get(documentKey);
      if (priorDocument && stableJson(priorDocument) !== stableJson(projected.document)) {
        throw new Error(`search document key resolves to different projected content: ${documentKey}`);
      }
      documentsByKey.set(documentKey, projected.document);
      // The stable ID is always indexed even when an adapter emits no other
      // lexical field. This is the lossless reachability denominator.
      const terms = new Set([...projected.terms, projected.document.id.toLowerCase()]);
      for (const term of terms) {
        const byDocument = postings.get(term) ?? new Map();
        byDocument.set(documentKey, projected.document);
        postings.set(term, byDocument);
      }
    }
    indexedRecordCounts[group] = indexed;
    if (indexed !== records.length) {
      throw new Error(`search denominator lost ${records.length - indexed} ${group} record(s) without a stable ID`);
    }
  }

  const entries = [...postings.entries()].sort(([left], [right]) => left.localeCompare(right)).map(
    ([term, byDocument]) => {
      const all = [...byDocument.values()].sort((left, right) => left.id.localeCompare(right.id) || left.kind.localeCompare(right.kind));
      const exact = all.filter((record) => record.id.toLowerCase() === term);
      if (exact.length > SEARCH_POSTING_LIMIT) {
        throw new Error(`search stable-ID posting ${term} exceeds the posting ceiling`);
      }
      const records = [...exact, ...all.filter((record) => record.id.toLowerCase() !== term)]
        .slice(0, SEARCH_POSTING_LIMIT);
      return [term, { totalMatches: all.length, records }];
    },
  );
  const reachableExactIds = new Map(SEARCH_GROUPS.map((group) => [group, new Set()]));
  for (const [term, posting] of entries) {
    for (const record of posting.records) {
      if (record.id.toLowerCase() === term) reachableExactIds.get(record.kind)?.add(record.id);
    }
  }
  for (const group of SEARCH_GROUPS) {
    if (reachableExactIds.get(group)?.size !== indexedRecordCounts[group]) {
      throw new Error(`search stable-ID reachability lost ${indexedRecordCounts[group] - (reachableExactIds.get(group)?.size ?? 0)} ${group} record(s)`);
    }
  }
  const expectedDocumentCount = Object.values(indexedRecordCounts).reduce(
    (total, count) => total + count,
    0,
  );
  const orderedDocuments = [...documentsByKey.entries()]
    .sort(([left], [right]) => left.localeCompare(right));
  const orderedDocumentKeys = orderedDocuments.map(([key]) => key);
  if (orderedDocuments.length !== expectedDocumentCount) {
    throw new Error(
      `search document denominator lost ${expectedDocumentCount - orderedDocuments.length} record(s)`,
    );
  }
  const documentOrdinalByKey = new Map(
    orderedDocuments.map(([key], ordinal) => [key, ordinal]),
  );
  const compactEntries = entries.map(([term, posting]) => [
    term,
    {
      totalMatches: posting.totalMatches,
      records: posting.records.map((record) => {
        const ordinal = documentOrdinalByKey.get(`${record.kind}:${record.id}`);
        if (!Number.isSafeInteger(ordinal)) {
          throw new Error(`search posting lacks a normalized document: ${record.kind}:${record.id}`);
        }
        return ordinal;
      }),
    },
  ]);
  const baseBuckets = Map.groupBy(compactEntries, ([term]) => fnv1a(term).slice(0, 3));
  const splitPrefixes = new Set();
  const shards = [];
  for (const [prefix, bucketEntries] of [...baseBuckets.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    splitSearchBucket(bucketEntries, prefix, splitPrefixes, shards);
  }

  await mkdir(join(staging, "search", "shards"), { recursive: true });
  await mkdir(join(staging, "search", "documents"), { recursive: true });
  const shardEntries = [];
  for (const shard of shards.sort((left, right) => left.prefix.localeCompare(right.prefix))) {
    const digest = sha256(shard.bytes);
    const modulePath = `search/shards/${shard.prefix}-${digest.slice(0, 16)}.mjs`;
    await writeFile(join(staging, ...modulePath.split("/")), shard.bytes);
    shardEntries.push({
      prefix: shard.prefix,
      module: modulePath,
      bytes: shard.bytes.byteLength,
      sha256: digest,
      termCount: Object.keys(shard.value).length,
    });
  }

  const documentPieces = [];
  const emptyDocumentModuleBytes = Buffer.byteLength(moduleText("documents", []), "utf8");
  let pendingDocuments = [];
  let pendingDocumentBytes = emptyDocumentModuleBytes;
  for (const [, document] of orderedDocuments) {
    const serializedBytes = Buffer.byteLength(stableJson(document), "utf8");
    const increment = serializedBytes + (pendingDocuments.length ? 1 : 0);
    if (
      pendingDocumentBytes + increment > SEARCH_DOCUMENT_SHARD_MAX_BYTES &&
      pendingDocuments.length
    ) {
      const bytes = Buffer.from(moduleText("documents", pendingDocuments), "utf8");
      if (bytes.byteLength > SEARCH_DOCUMENT_SHARD_MAX_BYTES) {
        throw new Error("search document shard accounting exceeded byte ceiling");
      }
      documentPieces.push({ documents: pendingDocuments, bytes });
      pendingDocuments = [];
      pendingDocumentBytes = emptyDocumentModuleBytes;
    }
    if (pendingDocumentBytes + serializedBytes > SEARCH_DOCUMENT_SHARD_MAX_BYTES) {
      throw new Error(`search document exceeds ${SEARCH_DOCUMENT_SHARD_MAX_BYTES} bytes`);
    }
    pendingDocumentBytes += serializedBytes + (pendingDocuments.length ? 1 : 0);
    pendingDocuments.push(document);
  }
  if (pendingDocuments.length) {
    documentPieces.push({
      documents: pendingDocuments,
      bytes: Buffer.from(moduleText("documents", pendingDocuments), "utf8"),
    });
  }
  const documentShardEntries = [];
  let startOrdinal = 0;
  for (const [index, piece] of documentPieces.entries()) {
    if (piece.bytes.byteLength > SEARCH_DOCUMENT_SHARD_MAX_BYTES) {
      throw new Error("search document shard accounting exceeded byte ceiling");
    }
    const digest = sha256(piece.bytes);
    const modulePath = `search/documents/${String(index).padStart(5, "0")}-${digest.slice(0, 16)}.mjs`;
    await writeFile(join(staging, ...modulePath.split("/")), piece.bytes);
    const endOrdinal = startOrdinal + piece.documents.length - 1;
    documentShardEntries.push({
      startOrdinal,
      endOrdinal,
      module: modulePath,
      bytes: piece.bytes.byteLength,
      sha256: digest,
      recordCount: piece.documents.length,
    });
    startOrdinal = endOrdinal + 1;
  }
  if (startOrdinal !== orderedDocuments.length) {
    throw new Error("search document shard denominator is inconsistent");
  }

  const loaderLines = shardEntries.map(
    (entry) => `  ${JSON.stringify(entry.prefix)}: () => import(${JSON.stringify(`./${entry.module.replace("search/", "")}`)}),`,
  ).join("\n");
  const documentLoaderLines = documentShardEntries.map(
    (entry) => `  () => import(${JSON.stringify(`./${entry.module.replace("search/", "")}`)}),`,
  ).join("\n");
  const compactDocumentRoutes = documentShardEntries.map(
    ({ startOrdinal: start, endOrdinal: end, recordCount }) => ({
      startOrdinal: start,
      endOrdinal: end,
      recordCount,
    }),
  );
  const searchIndexBytes = Buffer.from(
    `export const searchManifest = ${stableJson({
      documentCount: orderedDocuments.length,
      documentKeysDigest: digestObject(orderedDocumentKeys),
      documentShardCount: documentShardEntries.length,
      groupRecordCounts,
      indexedRecordCounts,
      postingLimit: SEARCH_POSTING_LIMIT,
      queryTokenLimit: SEARCH_QUERY_TOKEN_LIMIT,
      shardMaxBytes: SEARCH_SHARD_MAX_BYTES,
      termCount: entries.length,
      shardCount: shardEntries.length,
    })};\n` +
      `const splitPrefixes = new Set(${stableJson([...splitPrefixes].sort())});\n` +
      `const shardLoaders = Object.freeze({\n${loaderLines}\n});\n` +
      `const documentShardRoutes = Object.freeze(${stableJson(compactDocumentRoutes)});\n` +
      `const documentLoaders = Object.freeze([\n${documentLoaderLines}\n]);\n` +
      "if (documentShardRoutes.length !== searchManifest.documentShardCount || documentLoaders.length !== documentShardRoutes.length || documentShardRoutes.some((route, index) => !Number.isSafeInteger(route.startOrdinal) || !Number.isSafeInteger(route.endOrdinal) || !Number.isSafeInteger(route.recordCount) || route.recordCount < 1 || route.endOrdinal !== route.startOrdinal + route.recordCount - 1 || route.startOrdinal !== (index === 0 ? 0 : documentShardRoutes[index - 1].endOrdinal + 1)) || (documentShardRoutes.at(-1)?.endOrdinal ?? -1) !== searchManifest.documentCount - 1) throw new Error(\"search document shard route is absent or inconsistent\");\n" +
      `${fnv1a.toString()}\n` +
      "function bucketFor(term) {\n" +
      "  const hash = fnv1a(term);\n" +
      "  let prefix = hash.slice(0, 3);\n" +
      "  while (splitPrefixes.has(prefix)) prefix = hash.slice(0, prefix.length + 1);\n" +
      "  return prefix;\n" +
      "}\n" +
      "function documentShardFor(ordinal) {\n" +
      "  if (!Number.isSafeInteger(ordinal) || ordinal < 0 || ordinal >= searchManifest.documentCount) return -1;\n" +
      "  let low = 0;\n" +
      "  let high = documentShardRoutes.length;\n" +
      "  while (low < high) { const midpoint = low + Math.floor((high - low) / 2); if (documentShardRoutes[midpoint].endOrdinal < ordinal) low = midpoint + 1; else high = midpoint; }\n" +
      "  return low < documentShardRoutes.length && documentShardRoutes[low].startOrdinal <= ordinal ? low : -1;\n" +
      "}\n" +
      "async function loadDocuments(ordinals) {\n" +
      "  const shardIndexes = [...new Set(ordinals.map(documentShardFor))];\n" +
      "  if (shardIndexes.some((index) => index < 0)) throw new Error(\"search posting references an invalid document ordinal\");\n" +
      "  const loaded = new Map(await Promise.all(shardIndexes.map(async (index) => { const module = await documentLoaders[index](); const documents = module.documents ?? module.default; if (!Array.isArray(documents) || documents.length !== documentShardRoutes[index].recordCount) throw new Error(\"search document shard is malformed\"); return [index, documents]; })));\n" +
      "  return new Map(ordinals.map((ordinal) => { const shardIndex = documentShardFor(ordinal); const route = documentShardRoutes[shardIndex]; const document = loaded.get(shardIndex)?.[ordinal - route.startOrdinal]; if (!document || typeof document.id !== \"string\" || typeof document.kind !== \"string\") throw new Error(\"search document ordinal is unresolved\"); return [ordinal, document]; }));\n" +
      "}\n" +
      "export async function searchTerms(tokens) {\n" +
      `  const allTokens = [...new Set(tokens.map((token) => String(token).trim().toLowerCase()).filter(Boolean))];\n  const normalized = allTokens.slice(0, ${SEARCH_QUERY_TOKEN_LIMIT});\n` +
      "  const buckets = [...new Set(normalized.map(bucketFor))];\n" +
      "  const modules = new Map();\n" +
      "  await Promise.all(buckets.map(async (bucket) => { const loader = shardLoaders[bucket]; if (loader) modules.set(bucket, await loader()); }));\n" +
      "  const scores = new Map();\n" +
      "  const truncatedTerms = [];\n" +
      "  for (const token of normalized) {\n" +
      "    const posting = modules.get(bucketFor(token))?.terms?.[token];\n" +
      "    if (!posting) continue;\n" +
      "    if (posting.totalMatches > posting.records.length) truncatedTerms.push({ term: token, totalMatches: posting.totalMatches, returned: posting.records.length });\n" +
      "    for (const ordinal of posting.records) { if (!Number.isSafeInteger(ordinal)) throw new Error(\"search posting contains a malformed document ordinal\"); scores.set(ordinal, (scores.get(ordinal) ?? 0) + 2); }\n" +
      "  }\n" +
      `  if (scores.size > ${SEARCH_QUERY_TOKEN_LIMIT * SEARCH_POSTING_LIMIT}) throw new Error("search result amplification exceeds the bounded query denominator");\n` +
      "  const documents = await loadDocuments([...scores.keys()]);\n" +
      "  const records = [...scores.entries()].map(([ordinal, score]) => ({ ...documents.get(ordinal), score })).sort((left, right) => right.score - left.score || left.id.localeCompare(right.id)).slice(0, 64);\n" +
      "  return { records, truncatedTerms, ignoredTokenCount: Math.max(0, allTokens.length - normalized.length) };\n" +
      "}\n",
    "utf8",
  );
  const indexDigest = sha256(searchIndexBytes);
  if (searchIndexBytes.byteLength > SEARCH_INDEX_MAX_BYTES) {
    throw new Error(`search index exceeds ${SEARCH_INDEX_MAX_BYTES} bytes`);
  }
  const indexModule = `search/index-${indexDigest.slice(0, 16)}.mjs`;
  await writeFile(join(staging, ...indexModule.split("/")), searchIndexBytes);
  return {
    index: { module: indexModule, bytes: searchIndexBytes.byteLength, sha256: indexDigest },
    shards: shardEntries,
    documentShards: documentShardEntries,
    documentCount: orderedDocuments.length,
    documentKeysDigest: digestObject(orderedDocumentKeys),
    groupRecordCounts,
    indexedRecordCounts,
    postingLimit: SEARCH_POSTING_LIMIT,
    queryTokenLimit: SEARCH_QUERY_TOKEN_LIMIT,
    termCount: entries.length,
    maxShardBytes: Math.max(0, ...shardEntries.map((entry) => entry.bytes)),
    maxDocumentShardBytes: Math.max(0, ...documentShardEntries.map((entry) => entry.bytes)),
  };
}

function splitUtf8(value, maximumBytes) {
  if (Buffer.byteLength(value, "utf8") <= maximumBytes) return [value];
  const parts = [];
  let current = "";
  let bytes = 0;
  for (const character of value) {
    const size = Buffer.byteLength(character, "utf8");
    if (current && bytes + size > maximumBytes) {
      parts.push(current);
      current = "";
      bytes = 0;
    }
    current += character;
    bytes += size;
  }
  if (current || !parts.length) parts.push(current);
  return parts;
}

function sourceChunkBytes(header, segments) {
  return Buffer.from(moduleText("sourceChunk", { ...header, segments }), "utf8");
}

function packSourceSegments(header, segments) {
  const chunks = [];
  let current = [];
  const emptyBytes = sourceChunkBytes(header, []).byteLength;
  let currentBytes = emptyBytes;
  for (const segment of segments) {
    const segmentBytes = Buffer.byteLength(stableJson(segment), "utf8");
    const increment = segmentBytes + (current.length ? 1 : 0);
    if (currentBytes + increment > SOURCE_CHUNK_MAX_BYTES && current.length) {
      const bytes = sourceChunkBytes(header, current);
      if (bytes.byteLength > SOURCE_CHUNK_MAX_BYTES) throw new Error("source chunk accounting exceeded byte ceiling");
      chunks.push({ segments: current, bytes });
      current = [];
      currentBytes = emptyBytes;
    }
    if (currentBytes + segmentBytes > SOURCE_CHUNK_MAX_BYTES) {
      throw new Error(`source segment ${header.path}:${segment.number} exceeds ${SOURCE_CHUNK_MAX_BYTES} bytes`);
    }
    currentBytes += segmentBytes + (current.length ? 1 : 0);
    current.push(segment);
  }
  if (current.length) chunks.push({ segments: current, bytes: sourceChunkBytes(header, current) });
  return chunks;
}

function splitRecordsToBudget(
  name,
  records,
  maximumBytes,
  label = name,
  fragmentRegistry = null,
) {
  if (!records.length) return [];
  const bytes = Buffer.from(moduleText(name, records), "utf8");
  if (bytes.byteLength <= maximumBytes) return [{ records, bytes }];
  if (records.length === 1) {
    if (!fragmentRegistry) throw new Error(`${label} record exceeds ${maximumBytes} bytes`);
    const fragmentPlan = getRecordFragmentPlan(records[0], fragmentRegistry);
    const fragmentIndexBytes = Buffer.from(fragmentedRecordIndexText(fragmentPlan), "utf8");
    if (fragmentIndexBytes.byteLength > maximumBytes) {
      throw new Error(`${label} fragment index exceeds ${maximumBytes} bytes`);
    }
    return [{
      records: [],
      bytes: fragmentIndexBytes,
      recordCount: 1,
      fragmentPlan,
    }];
  }
  const midpoint = Math.ceil(records.length / 2);
  return [
    ...splitRecordsToBudget(
      name,
      records.slice(0, midpoint),
      maximumBytes,
      label,
      fragmentRegistry,
    ),
    ...splitRecordsToBudget(
      name,
      records.slice(midpoint),
      maximumBytes,
      label,
      fragmentRegistry,
    ),
  ];
}

function dossierPrefixFor(id, splitPrefixes) {
  const hash = fnv1a(String(id));
  let prefix = hash.slice(0, DOSSIER_BASE_PREFIX_LENGTH);
  while (splitPrefixes.has(prefix)) {
    if (prefix.length >= hash.length) {
      throw new Error(`dossier hash collision cannot be routed within ${hash.length} hexadecimal digits`);
    }
    prefix = hash.slice(0, prefix.length + 1);
  }
  return prefix;
}

function splitDossierBucket(kind, records, prefix, splitPrefixes, leaves, fragmentRegistry) {
  const bytes = Buffer.from(moduleText("records", records), "utf8");
  if (bytes.byteLength <= LAZY_MODULE_MAX_BYTES) {
    leaves.push({ prefix, records, bytes });
    return;
  }
  if (records.length === 1) {
    const fragmentPlan = getRecordFragmentPlan(records[0], fragmentRegistry);
    const fragmentIndexBytes = Buffer.from(
      fragmentedRecordIndexText(fragmentPlan, { dossier: true }),
      "utf8",
    );
    if (fragmentIndexBytes.byteLength > LAZY_MODULE_MAX_BYTES) {
      throw new Error(
        `dossier ${kind} fragment index ${records[0].id} exceeds ${LAZY_MODULE_MAX_BYTES} bytes`,
      );
    }
    leaves.push({
      prefix,
      records: [],
      bytes: fragmentIndexBytes,
      recordCount: 1,
      fragmentPlan,
    });
    return;
  }
  if (prefix.length >= 8) {
    throw new Error(`dossier ${kind} hash bucket ${prefix} exceeds ${LAZY_MODULE_MAX_BYTES} bytes`);
  }
  splitPrefixes.add(prefix);
  const children = Map.groupBy(
    records,
    (record) => fnv1a(String(record.id)).slice(0, prefix.length + 1),
  );
  for (const [childPrefix, childRecords] of [...children.entries()].sort(([left], [right]) =>
    left.localeCompare(right))) {
    splitDossierBucket(
      kind,
      childRecords,
      childPrefix,
      splitPrefixes,
      leaves,
      fragmentRegistry,
    );
  }
}

async function writeSourceProjection({
  staging,
  inputRoot,
  manifest,
  filesByPath,
  symbolsByPath,
  lineMetadataByPath,
  seenIds,
  completeness,
  claimPredicates,
  claimFacetRecords,
  claimUnavailableReason,
}) {
  await mkdir(join(staging, "source", "chunks"), { recursive: true });
  const sourceFiles = Object.create(null);
  const sourceModules = [];
  const expectedSourcePaths = new Set(
    [...filesByPath.values()]
      .filter((file) =>
        file.privacyExposure === "full" &&
        file.language !== "binary" &&
        typeof file.contentDigest === "string" &&
        file.classificationErrors.length === 0)
      .map((file) => file.path),
  );
  const loadedSourcePaths = new Set();
  const consequentialClaimSources = new Map();
  let physicalLineCount = 0;
  let nonblankLineCount = 0;
  await loadGroup(inputRoot, manifest, "source_text", {
    retain: false,
    seenIds,
    onRecord: async (record) => {
      if (typeof record.path !== "string" || loadedSourcePaths.has(record.path)) {
        throw new Error(`duplicate or invalid source-text path: ${String(record.path)}`);
      }
      loadedSourcePaths.add(record.path);
      const file = filesByPath.get(record.path);
      if (!file || file.privacyExposure !== "full") {
        throw new Error(`source text violates privacy exposure for ${record.path}`);
      }
      if (
        record.file_id !== file.id ||
        record.encoding !== "utf-8" ||
        record.source_basis !== "selected_commit_git_blob" ||
        record.source_basis !== file.contentSource ||
        record.git_blob_oid !== file.gitBlobOid ||
        !Array.isArray(record.lines)
      ) {
        throw new Error(`source text custody or file identity disagrees for ${record.path}`);
      }
      const sourceLineNumbers = new Set();
      for (const [lineIndex, line] of record.lines.entries()) {
        if (
          !line ||
          typeof line !== "object" ||
          !Number.isSafeInteger(line.number) ||
          line.number !== lineIndex + 1 ||
          sourceLineNumbers.has(line.number) ||
          typeof line.text !== "string" ||
          !["", "\n", "\r", "\r\n"].includes(line.terminator) ||
          !/^[0-9a-f]{64}$/.test(String(line.text_digest ?? "")) ||
          !/^[0-9a-f]{64}$/.test(String(line.line_digest ?? ""))
        ) {
          throw new Error(`source text contains an invalid line record for ${record.path}`);
        }
        sourceLineNumbers.add(line.number);
      }
      const reconstructed = Buffer.from(
        (record.lines ?? []).map((line) => `${line.text}${line.terminator}`).join(""),
        "utf8",
      );
      if (reconstructed.byteLength !== record.byte_count || sha256(reconstructed) !== record.content_digest) {
        throw new Error(`source text does not round-trip for ${record.path}`);
      }
      if (CONSEQUENTIAL_CLAIM_PATHS.has(record.path)) {
        consequentialClaimSources.set(record.path, {
          raw: reconstructed,
          gitBlobOid: record.git_blob_oid,
        });
      }
      if (
        record.content_digest !== file.contentDigest ||
        record.byte_count !== file.sizeBytes ||
        record.line_count !== file.lineCount ||
        record.lines.length !== record.line_count
      ) {
        throw new Error(`source text metadata disagrees with file census for ${record.path}`);
      }
      const lineMetadata = lineMetadataByPath.get(record.path) ?? new Map();
      const nonblankNumbers = new Set(
        record.lines.filter((line) => line.text.trim()).map((line) => line.number),
      );
      if (
        nonblankNumbers.size !== file.nonblankLineCount ||
        lineMetadata.size !== nonblankNumbers.size ||
        [...nonblankNumbers].some((line) => !lineMetadata.has(line)) ||
        [...lineMetadata].some(([line]) => !nonblankNumbers.has(line))
      ) {
        throw new Error(`source/nonblank/line-record denominator differs for ${record.path}`);
      }
      physicalLineCount += record.lines.length;
      nonblankLineCount += nonblankNumbers.size;
      const symbolLookup = new Map();
      for (const symbol of symbolsByPath.get(record.path) ?? []) {
        symbolLookup.set(symbol.qualifiedName, symbol.id);
        if (!symbolLookup.has(symbol.name)) symbolLookup.set(symbol.name, symbol.id);
      }
      const segments = [];
      for (const line of record.lines ?? []) {
        if (sha256(Buffer.from(line.text, "utf8")) !== line.text_digest) {
          throw new Error(`source text digest mismatch for ${record.path}:${line.number}`);
        }
        if (sha256(Buffer.from(`${line.text}${line.terminator}`, "utf8")) !== line.line_digest) {
          throw new Error(`source line digest mismatch for ${record.path}:${line.number}`);
        }
        const structural = lineMetadata.get(line.number);
        if (
          line.text.trim() &&
          (!structural ||
            structural.textDigest !== line.text_digest ||
            structural.lineDigest !== line.line_digest)
        ) {
          throw new Error(`source and semantic line records disagree for ${record.path}:${line.number}`);
        }
        const fragments = splitUtf8(line.text, SOURCE_FRAGMENT_TEXT_BYTES);
        for (const [fragmentIndex, text] of fragments.entries()) {
          segments.push({
            number: line.number,
            text,
            terminator: fragmentIndex === fragments.length - 1 ? line.terminator : "",
            fragmentIndex,
            fragmentCount: fragments.length,
            ...(fragments.length > 1
              ? { fragmentDigest: sha256(Buffer.from(text, "utf8")) }
              : {}),
            lineDigest: line.line_digest,
            recordId: structural?.id ?? null,
            syntaxKind: structural?.syntaxKind ?? null,
            structuralMappingBasis: structural?.structuralMappingBasis ?? null,
            containingSymbol: structural?.containingSymbol ?? null,
            containingSymbolId: structural?.containingSymbol
              ? symbolLookup.get(structural.containingSymbol) ?? null
              : null,
            syntaxDepth: structural?.syntaxDepth ?? null,
            explanationDepth: structural?.explanationDepth ?? 0,
            semanticEntity: structural?.semanticEntity ?? null,
            owner: structural?.owner ?? null,
            behaviorGroup: structural?.behaviorGroup ?? [],
            inputsAndOutputs: structural?.inputsAndOutputs ?? null,
            claimsInfluenced: structural?.claimsInfluenced ?? [],
            callersAndDependencies: structural?.callersAndDependencies ?? [],
            testsCoveringIt: structural?.testsCoveringIt ?? [],
            testCoverageState: structural?.testCoverageState ?? "not_applicable_blank_line",
            runtimeTraceState: structural?.runtimeTraceState ?? "not_applicable_blank_line",
            guiOrArtifactConsumers: structural?.guiOrArtifactConsumers ?? [],
            securityAndPrivacyEffect: structural?.securityAndPrivacyEffect ?? null,
            currentOrHistorical: structural?.currentOrHistorical ?? file.documentationStatus ?? null,
            unresolvedReasons:
              structural?.unresolvedReasons ?? ["blank_line_not_in_nonblank_semantic_denominator"],
          });
        }
      }
      const header = {
        id: record.id,
        fileId: record.file_id,
        path: record.path,
        encoding: record.encoding,
        byteCount: record.byte_count,
        contentDigest: record.content_digest,
        lineCount: record.line_count,
        derivation: "compiler_structural",
        verification: {
          sourceIntegrity: "digest_bound_exact_text_split_into_ordered_chunks",
          semanticDepth: "preserved_from_source_line_record",
          testCoverage: "preserved_from_source_line_record",
          runtimeTrace: "preserved_from_source_line_record",
          humanReview: "preserved_from_symbol_dossier",
        },
      };
      const packed = packSourceSegments(header, segments);
      const descriptors = [];
      for (const [chunkIndex, packedChunk] of packed.entries()) {
        const digest = sha256(packedChunk.bytes);
        const modulePath = `source/chunks/${digest.slice(0, 24)}-${sha256(record.path).slice(0, 8)}-${String(chunkIndex).padStart(5, "0")}.mjs`;
        await writeFile(join(staging, ...modulePath.split("/")), packedChunk.bytes);
        const first = packedChunk.segments[0];
        const last = packedChunk.segments.at(-1);
        const descriptor = {
          path: record.path,
          fileId: record.file_id,
          chunkIndex,
          module: modulePath,
          sha256: digest,
          bytes: packedChunk.bytes.byteLength,
          startLine: first.number,
          endLine: last.number,
          startFragment: first.fragmentIndex,
          endFragment: last.fragmentIndex,
          segmentCount: packedChunk.segments.length,
        };
        descriptors.push(descriptor);
        sourceModules.push(descriptor);
      }
      sourceFiles[record.path] = {
        ...header,
        segmentCount: segments.length,
        chunkCount: descriptors.length,
        chunks: descriptors.map(({ module, sha256: digest, bytes, chunkIndex, startLine, endLine, startFragment, endFragment, segmentCount }) => ({
          module,
          sha256: digest,
          bytes,
          chunkIndex,
          startLine,
          endLine,
          startFragment,
          endFragment,
          segmentCount,
        })),
      };
    },
  });
  const expectedPaths = [...expectedSourcePaths].sort();
  const actualPaths = [...loadedSourcePaths].sort();
  if (stableJson(expectedPaths) !== stableJson(actualPaths)) {
    throw new Error("safe full-exposure file/source-text path denominator differs");
  }
  for (const [path, lines] of lineMetadataByPath) {
    if (!loadedSourcePaths.has(path) && lines.size) {
      throw new Error(`line records exist without exact source text: ${path}`);
    }
  }
  try {
    validateConsequentialClaimCensus({
      completeness,
      rawSources: consequentialClaimSources,
      claimPredicates,
      facetRecords: claimFacetRecords,
      unavailableReason: claimUnavailableReason,
    });
  } catch {
    throw new Error("compiler consequential-claim census is inconsistent");
  }

  const sourceFileEntries = Object.entries(Object.fromEntries(
    Object.entries(sourceFiles).sort(([left], [right]) => left.localeCompare(right)),
  ));
  const loaderLines = sourceFileEntries.map(([, descriptor]) =>
    `Object.freeze([${descriptor.chunks.map((entry) => `() => import(${JSON.stringify(`./${entry.module.replace("source/", "")}`)})`).join(",")}]),`,
  ).join("");
  const sourceIndexBytes = Buffer.from(
    `export const sourceFiles = Object.freeze(Object.fromEntries(${stableJson(sourceFileEntries)}));\n` +
      "const sourceFilePaths = Object.freeze(Object.keys(sourceFiles));\n" +
      `const sourceChunkLoaders = Object.freeze([\n${loaderLines}\n]);\n` +
      "if (sourceChunkLoaders.length !== sourceFilePaths.length || sourceChunkLoaders.some((loaders, index) => { const descriptor = sourceFiles[sourceFilePaths[index]]; return descriptor?.path !== sourceFilePaths[index] || !Number.isSafeInteger(descriptor.chunkCount) || descriptor.chunkCount !== descriptor.chunks.length || loaders.length !== descriptor.chunks.length || loaders.some((loader) => typeof loader !== \"function\") || descriptor.chunks.some((chunk, chunkIndex) => chunk.chunkIndex !== chunkIndex); })) throw new Error(\"source chunk loader route is absent or inconsistent\");\n" +
      "const sourceFileOrdinals = new Map(sourceFilePaths.map((path, index) => [path, index]));\n" +
      "export function getSourceFile(path) { return Object.hasOwn(sourceFiles, path) ? sourceFiles[path] : null; }\n" +
      "export async function loadSourceChunk(path, chunkIndex) {\n" +
      "  const ordinal = typeof path === \"string\" ? sourceFileOrdinals.get(path) : undefined;\n" +
      "  const loader = ordinal === undefined || !Number.isSafeInteger(chunkIndex) || chunkIndex < 0 ? null : sourceChunkLoaders[ordinal]?.[chunkIndex];\n" +
      "  if (!loader) return null;\n" +
      "  const module = await loader();\n" +
      "  return module.sourceChunk ?? module.default;\n" +
      "}\n" +
      "export async function loadSourceWindow(path, line) {\n" +
      "  const descriptor = getSourceFile(path);\n" +
      "  if (!descriptor) return null;\n" +
      "  const target = Number.isInteger(line) && line > 0 ? line : 1;\n" +
      "  const index = descriptor.chunks.findIndex((chunk) => chunk.startLine <= target && chunk.endLine >= target);\n" +
      "  return index < 0 ? null : loadSourceChunk(path, index);\n" +
      "}\n",
    "utf8",
  );
  const sourceIndexDigest = sha256(sourceIndexBytes);
  if (sourceIndexBytes.byteLength > SOURCE_INDEX_MAX_BYTES) {
    throw new Error(`source index exceeds ${SOURCE_INDEX_MAX_BYTES} bytes`);
  }
  const sourceIndexModule = `source/index-${sourceIndexDigest.slice(0, 16)}.mjs`;
  await writeFile(join(staging, ...sourceIndexModule.split("/")), sourceIndexBytes);
  return {
    index: { module: sourceIndexModule, bytes: sourceIndexBytes.byteLength, sha256: sourceIndexDigest },
    files: Object.values(sourceFiles).length,
    physicalLines: physicalLineCount,
    nonblankLines: nonblankLineCount,
    modules: sourceModules.sort((left, right) => left.path.localeCompare(right.path) || left.chunkIndex - right.chunkIndex),
    maxChunkBytes: Math.max(0, ...sourceModules.map((entry) => entry.bytes)),
  };
}

const GRAPH_IDENTIFIER_POLICY =
  "raw_identifiers_withheld_repository_relative_retained_source_index_excluded";
const GRAPH_FILE_TYPES = new Set(["", "code", "document", "rationale"]);
const GRAPH_LANGUAGES = new Set([
  "", "bash", "c", "cpp", "csharp", "css", "go", "html", "java", "javascript", "json",
  "jsx", "markdown", "php", "python", "ruby", "rust", "shell", "sql", "text", "tsx",
  "typescript", "yaml",
]);
const GRAPH_KINDS = new Set([
  "", "bash_entrypoint", "bash_function", "class", "code", "file", "function", "method",
  "module", "symbol",
]);
const GRAPH_RELATIONS = new Set([
  "calls", "contains", "defines", "imports", "imports_from", "indirect_call", "inherits",
  "method", "rationale_for", "related_to", "re_exports", "references", "uses",
]);
const GRAPH_ABSENT_METADATA_KEYS = Object.freeze([
  "schema_version", "source_commit", "source_tree_digest", "available", "status", "source",
  "report_available", "stale", "unresolved_reasons",
]);
const GRAPH_AVAILABLE_METADATA_KEYS = Object.freeze([
  "schema_version", "available", "status", "source", "source_bytes", "source_digest",
  "report_available", "built_at_commit", "source_commit", "source_tree_digest", "stale",
  "total_nodes", "total_edges", "total_hyperedges", "projected_nodes", "projected_edges",
  "excluded_nodes", "excluded_edges", "excluded_node_dispositions",
  "excluded_edge_dispositions", "excluded_edge_endpoint_dispositions", "all_edge_modes",
  "projected_edge_modes", "node_origins", "excluded_nodes_unsafe_source",
  "excluded_nodes_untracked_or_private", "node_disposition_counts",
  "identifier_projection_policy", "node_identifier_disposition_counts", "total_communities",
  "projected_communities", "excluded_communities", "all_community_ids",
  "projected_community_ids", "excluded_community_ids", "partial_community_ids",
  "community_status_counts", "community_dispositions", "projection_policy",
  "unresolved_reasons",
]);
const GRAPH_BASE_UNRESOLVED_REASONS = Object.freeze([
  "graphify_is_optional_secondary_projection",
  "graphify_incremental_rebuild_may_evict_cross_file_edges_until_full_rebuild",
  "graphify_raw_identifiers_are_withheld_and_exclusion_dispositions_use_source_index_only",
  "graphify_producer_labels_are_replaced_by_repository_relative_coordinate_labels_and_descriptors_use_controlled_vocabularies",
]);
const GRAPH_DIRTY_PREVIEW_REASON = "tracked_worktree_changes_are_newer_than_commit_bound_graph";
const GRAPH_NODE_REASONS = new Set([
  "graphify_node_label_derived_from_repository_relative_coordinate",
  "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction",
  "graphify_node_community_outside_js_safe_nonnegative_integer_domain",
  "graphify_node_source_location_outside_bounded_coordinate_domain",
  "graphify_node_nonvocabulary_descriptor_withheld",
]);
const GRAPH_EDGE_REASONS = new Set([
  "graphify_confidence_mode_undisclosed_or_ambiguous",
  "graphify_relation_not_in_controlled_vocabulary_shape",
  "graphify_edge_source_location_outside_bounded_coordinate_domain",
]);

function graphSourceLocationIsValid(value) {
  return Boolean(
    typeof value === "string" &&
      value.length <= 64 &&
      /^(?:L?[1-9]\d*(?::[1-9]\d*)?(?:-L?[1-9]\d*(?::[1-9]\d*)?)?)?$/.test(value) &&
      [...value.matchAll(/\d+/g)].every((match) => {
        const component = Number(match[0]);
        return Number.isSafeInteger(component) && component > 0;
      }),
  );
}

function hasExactObjectKeys(value, expectedKeys) {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      stableJson(Object.keys(value).sort()) === stableJson([...expectedKeys].sort()),
  );
}

function validateGraphifyMetadataStructure(graphify) {
  const digestPattern = /^[0-9a-f]{64}$/;
  const commitPattern = /^[0-9a-f]{40}(?:[0-9a-f]{24})?$/;
  if (!graphify || typeof graphify !== "object" || Array.isArray(graphify)) {
    throw new Error("Graphify metadata receipt is malformed");
  }
  if (graphify.available === false) {
    if (
      !hasExactObjectKeys(graphify, GRAPH_ABSENT_METADATA_KEYS) ||
      graphify.schema_version !== COMPILER_SCHEMA_VERSION ||
      graphify.status !== "absent" ||
      graphify.stale !== null ||
      graphify.source !== "graphify-out/graph.json" ||
      typeof graphify.report_available !== "boolean" ||
      !commitPattern.test(graphify.source_commit) ||
      !digestPattern.test(graphify.source_tree_digest) ||
      stableJson(graphify.unresolved_reasons) !==
        stableJson(["optional_graphify_projection_not_present"])
    ) {
      throw new Error("absent Graphify metadata receipt is malformed");
    }
    return;
  }
  if (
    graphify.available !== true ||
    !hasExactObjectKeys(graphify, GRAPH_AVAILABLE_METADATA_KEYS) ||
    graphify.schema_version !== COMPILER_SCHEMA_VERSION ||
    graphify.source !== "graphify-out/graph.json" ||
    graphify.projection_policy !== "tracked_full_exposure_files_only" ||
    typeof graphify.report_available !== "boolean" ||
    !commitPattern.test(graphify.source_commit) ||
    !digestPattern.test(graphify.source_tree_digest) ||
    !digestPattern.test(graphify.source_digest) ||
    requireCount(graphify.source_bytes, "Graphify source byte count") === 0
  ) {
    throw new Error("available Graphify metadata receipt is malformed");
  }
  const totalHyperedges = requireCount(graphify.total_hyperedges, "Graphify hyperedge count");
  const expectedReasons = [
    GRAPH_BASE_UNRESOLVED_REASONS[0],
    totalHyperedges > 0 ? "graphify_hyperedges_not_projected" : "graphify_has_no_hyperedges",
    ...GRAPH_BASE_UNRESOLVED_REASONS.slice(1),
    ...(graphify.built_at_commit === null
      ? ["graphify_built_at_commit_missing_or_malformed_and_withheld"]
      : []),
    ...(graphify.status === "stale" && graphify.built_at_commit === graphify.source_commit
      ? [GRAPH_DIRTY_PREVIEW_REASON]
      : []),
  ];
  if (stableJson(graphify.unresolved_reasons) !== stableJson(expectedReasons)) {
    throw new Error("Graphify unresolved reason ledger is malformed");
  }

  const validateCountMap = (value, allowedKeys, expectedTotal, label) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`${label} is malformed`);
    }
    let total = 0;
    for (const [key, count] of Object.entries(value)) {
      if (!allowedKeys.has(key) || !Number.isSafeInteger(count) || count <= 0) {
        throw new Error(`${label} is malformed`);
      }
      total += count;
    }
    if (!Number.isSafeInteger(total) || total !== expectedTotal) {
      throw new Error(`${label} does not reconcile`);
    }
    return value;
  };
  const totalEdges = requireCount(graphify.total_edges, "Graphify total edge count");
  const projectedEdges = requireCount(graphify.projected_edges, "Graphify projected edge count");
  const edgeModes = new Set(["extracted", "inferred", "ambiguous", "undisclosed"]);
  const allModes = validateCountMap(graphify.all_edge_modes, edgeModes, totalEdges, "Graphify edge modes");
  const projectedModes = validateCountMap(
    graphify.projected_edge_modes,
    edgeModes,
    projectedEdges,
    "Graphify projected edge modes",
  );
  if (Object.entries(projectedModes).some(([mode, count]) => count > (allModes[mode] ?? 0))) {
    throw new Error("Graphify projected edge modes exceed the source census");
  }
  validateCountMap(
    graphify.node_origins,
    new Set(["ast", "curated", "undisclosed"]),
    requireCount(graphify.total_nodes, "Graphify total node count"),
    "Graphify node origins",
  );
  if (
    !hasExactObjectKeys(graphify.node_disposition_counts, [
      "retained", "excluded_unsafe_source", "excluded_untracked_or_private",
    ]) ||
    requireCount(
      graphify.node_disposition_counts.retained,
      "Graphify retained node disposition count",
    ) !== graphify.projected_nodes ||
    requireCount(
      graphify.node_disposition_counts.excluded_unsafe_source,
      "Graphify unsafe-source node disposition count",
    ) !== graphify.excluded_nodes_unsafe_source ||
    requireCount(
      graphify.node_disposition_counts.excluded_untracked_or_private,
      "Graphify private node disposition count",
    ) !== graphify.excluded_nodes_untracked_or_private ||
    graphify.excluded_nodes_unsafe_source + graphify.excluded_nodes_untracked_or_private !==
      graphify.excluded_nodes ||
    !hasExactObjectKeys(graphify.node_identifier_disposition_counts, [
      "total", "projected_repository_relative", "excluded_opaque", "raw_published",
    ])
  ) {
    throw new Error("Graphify node disposition denominator does not reconcile");
  }

  const communityIds = (value, label) => {
    if (
      !Array.isArray(value) ||
      value.some((item) => !Number.isSafeInteger(item) || item < 0) ||
      value.some((item, index) => index > 0 && value[index - 1] >= item)
    ) {
      throw new Error(`${label} is malformed`);
    }
    return value;
  };
  const allCommunityIds = communityIds(graphify.all_community_ids, "Graphify community census");
  const projectedCommunityIds = communityIds(
    graphify.projected_community_ids,
    "Graphify projected community census",
  );
  const excludedCommunityIds = communityIds(
    graphify.excluded_community_ids,
    "Graphify excluded community census",
  );
  const partialCommunityIds = communityIds(
    graphify.partial_community_ids,
    "Graphify partial community census",
  );
  const allCommunitySet = new Set(allCommunityIds);
  const projectedCommunitySet = new Set(projectedCommunityIds);
  const excludedCommunitySet = new Set(excludedCommunityIds);
  if (
    requireCount(graphify.total_communities, "Graphify total community count") !==
      allCommunityIds.length ||
    requireCount(graphify.projected_communities, "Graphify projected community count") !==
      projectedCommunityIds.length ||
    requireCount(graphify.excluded_communities, "Graphify excluded community count") !==
      excludedCommunityIds.length ||
    projectedCommunityIds.some((id) => !allCommunitySet.has(id) || excludedCommunitySet.has(id)) ||
    excludedCommunityIds.some((id) => !allCommunitySet.has(id)) ||
    projectedCommunityIds.length + excludedCommunityIds.length !== allCommunityIds.length ||
    partialCommunityIds.some((id) => !projectedCommunitySet.has(id))
  ) {
    throw new Error("Graphify community denominator does not reconcile");
  }
  const statusKeys = ["projected_complete", "projected_partial", "excluded"];
  if (
    !hasExactObjectKeys(graphify.community_status_counts, statusKeys) ||
    statusKeys.some(
      (status) =>
        !Number.isSafeInteger(graphify.community_status_counts[status]) ||
        graphify.community_status_counts[status] < 0,
    ) ||
    !Array.isArray(graphify.community_dispositions)
  ) {
    throw new Error("Graphify community disposition ledger is malformed");
  }
  const actualStatusCounts = Object.fromEntries(statusKeys.map((status) => [status, 0]));
  const dispositionCommunityIds = [];
  const derivedPartialIds = [];
  for (const disposition of graphify.community_dispositions) {
    if (
      !hasExactObjectKeys(disposition, [
        "community", "status", "total_nodes", "retained_nodes", "excluded_nodes",
      ]) ||
      !Number.isSafeInteger(disposition.community) ||
      disposition.community < 0 ||
      !Number.isSafeInteger(disposition.total_nodes) ||
      disposition.total_nodes <= 0 ||
      !Number.isSafeInteger(disposition.retained_nodes) ||
      disposition.retained_nodes < 0 ||
      !Number.isSafeInteger(disposition.excluded_nodes) ||
      disposition.excluded_nodes < 0 ||
      disposition.retained_nodes + disposition.excluded_nodes !== disposition.total_nodes
    ) {
      throw new Error("Graphify community disposition ledger is malformed");
    }
    const expectedStatus =
      disposition.retained_nodes === 0
        ? "excluded"
        : disposition.retained_nodes === disposition.total_nodes
          ? "projected_complete"
          : "projected_partial";
    if (disposition.status !== expectedStatus) {
      throw new Error("Graphify community disposition status is inconsistent");
    }
    dispositionCommunityIds.push(disposition.community);
    actualStatusCounts[expectedStatus] += 1;
    if (expectedStatus === "projected_partial") derivedPartialIds.push(disposition.community);
  }
  if (
    stableJson(dispositionCommunityIds) !== stableJson(allCommunityIds) ||
    stableJson(actualStatusCounts) !== stableJson(graphify.community_status_counts) ||
    stableJson(derivedPartialIds) !== stableJson(partialCommunityIds)
  ) {
    throw new Error("Graphify community disposition ledger does not reconcile");
  }
}

function validateGraphExclusionLedger(graphify, retainedNodeIds) {
  const nodeDispositionIdPattern = /^urn:atlas:graph-node-disposition:[0-9a-f]{24}$/;
  const edgeDispositionIdPattern = /^urn:atlas:graph-edge-disposition:[0-9a-f]{24}$/;
  const nodeKeys = ["id", "disposition", "raw_index", "reason"];
  const edgeKeys = [
    "id", "disposition", "raw_index", "reason", "source_endpoint", "target_endpoint",
  ];
  const endpointKeys = ["state", "record_id", "anonymous_slot"];
  const nodeReasons = new Set(["excluded_unsafe_source", "excluded_untracked_or_private"]);
  const endpointStates = new Set([
    "retained", "excluded_unsafe_source", "excluded_untracked_or_private", "missing_node",
  ]);
  const nodeDispositionIds = new Set();
  const nodeRawIndices = new Set();
  const nodeDispositionsById = new Map();
  const actualNodeReasons = {
    excluded_unsafe_source: 0,
    excluded_untracked_or_private: 0,
  };
  for (const record of graphify.excluded_node_dispositions) {
    if (
      !hasExactObjectKeys(record, nodeKeys) ||
      record.disposition !== "excluded" ||
      typeof record.id !== "string" ||
      !nodeDispositionIdPattern.test(record.id) ||
      nodeDispositionIds.has(record.id) ||
      !Number.isSafeInteger(record.raw_index) ||
      record.raw_index < 0 ||
      record.raw_index >= graphify.total_nodes ||
      nodeRawIndices.has(record.raw_index) ||
      record.id !== stableId(
        "graph-node-disposition", graphify.source_digest, record.raw_index,
      ) ||
      !nodeReasons.has(record.reason)
    ) {
      throw new Error("Graphify excluded node disposition ledger is malformed");
    }
    nodeDispositionIds.add(record.id);
    nodeRawIndices.add(record.raw_index);
    nodeDispositionsById.set(record.id, record);
    actualNodeReasons[record.reason] += 1;
  }
  if (
    actualNodeReasons.excluded_unsafe_source !==
      graphify.node_disposition_counts.excluded_unsafe_source ||
    actualNodeReasons.excluded_untracked_or_private !==
      graphify.node_disposition_counts.excluded_untracked_or_private
  ) {
    throw new Error("Graphify excluded node disposition ledger does not reconcile");
  }

  const edgeDispositionIds = new Set();
  const edgeRawIndices = new Set();
  const validatedEdges = [];
  const actualEndpointCounts = Object.create(null);
  const seenAnonymousSlots = new Set();
  const validateEndpoint = (endpoint) => {
    if (
      !hasExactObjectKeys(endpoint, endpointKeys) ||
      !endpointStates.has(endpoint.state)
    ) {
      throw new Error("Graphify excluded edge endpoint ledger is malformed");
    }
    if (endpoint.state === "missing_node") {
      if (
        endpoint.record_id !== null ||
        !Number.isSafeInteger(endpoint.anonymous_slot) ||
        endpoint.anonymous_slot < 0
      ) {
        throw new Error("Graphify missing edge endpoint slot is malformed");
      }
      if (!seenAnonymousSlots.has(endpoint.anonymous_slot)) {
        if (endpoint.anonymous_slot !== seenAnonymousSlots.size) {
          throw new Error("Graphify missing edge endpoint slots are not first-seen contiguous");
        }
        seenAnonymousSlots.add(endpoint.anonymous_slot);
      }
      return;
    }
    if (typeof endpoint.record_id !== "string" || endpoint.anonymous_slot !== null) {
      throw new Error("Graphify known edge endpoint lacks a record identity");
    }
    if (endpoint.state === "retained") {
      if (!retainedNodeIds.has(endpoint.record_id)) {
        throw new Error("Graphify retained edge endpoint does not resolve");
      }
      return;
    }
    const disposition = nodeDispositionsById.get(endpoint.record_id);
    if (
      !disposition ||
      disposition.reason !== endpoint.state
    ) {
      throw new Error("Graphify excluded edge endpoint does not traverse to its node disposition");
    }
  };
  for (const record of graphify.excluded_edge_dispositions) {
    if (
      !hasExactObjectKeys(record, edgeKeys) ||
      record.disposition !== "excluded" ||
      typeof record.id !== "string" ||
      !edgeDispositionIdPattern.test(record.id) ||
      edgeDispositionIds.has(record.id) ||
      !Number.isSafeInteger(record.raw_index) ||
      record.raw_index < 0 ||
      record.raw_index >= graphify.total_edges ||
      edgeRawIndices.has(record.raw_index) ||
      record.id !== stableId(
        "graph-edge-disposition", graphify.source_digest, record.raw_index,
      ) ||
      record.reason !== "endpoint_not_projected"
    ) {
      throw new Error("Graphify excluded edge disposition ledger is malformed");
    }
    edgeDispositionIds.add(record.id);
    edgeRawIndices.add(record.raw_index);
    validatedEdges.push(record);
  }
  validatedEdges.sort((left, right) => left.raw_index - right.raw_index);
  for (const record of validatedEdges) {
    validateEndpoint(record.source_endpoint);
    validateEndpoint(record.target_endpoint);
    const endpointDisposition =
      `source_${record.source_endpoint.state}__target_${record.target_endpoint.state}`;
    actualEndpointCounts[endpointDisposition] =
      (actualEndpointCounts[endpointDisposition] ?? 0) + 1;
  }
  if (stableJson(actualEndpointCounts) !== stableJson(graphify.excluded_edge_endpoint_dispositions)) {
    throw new Error("Graphify excluded edge endpoint ledger does not reconcile");
  }
}

function validateGraphProjectionContract(manifest, graphify, nodes, edges, filesByPath) {
  validateGraphifyMetadataStructure(graphify);
  if (graphify.available !== true) {
    if (nodes.length || edges.length) {
      throw new Error("unavailable Graphify receipt cannot carry projected node or edge records");
    }
    return;
  }
  const counts = graphify.node_identifier_disposition_counts;
  const nodeDispositionCounts = graphify.node_disposition_counts;
  const excludedNodeDispositions = Array.isArray(graphify.excluded_node_dispositions)
    ? graphify.excluded_node_dispositions
    : null;
  const excludedEdgeDispositions = Array.isArray(graphify.excluded_edge_dispositions)
    ? graphify.excluded_edge_dispositions
    : null;
  const endpointDispositionCounts = graphify.excluded_edge_endpoint_dispositions;
  const endpointDispositionValues =
    endpointDispositionCounts &&
    typeof endpointDispositionCounts === "object" &&
    !Array.isArray(endpointDispositionCounts)
      ? Object.values(endpointDispositionCounts)
      : null;
  const dirtyGraphReasonIsPresent =
    Array.isArray(graphify.unresolved_reasons) &&
    graphify.unresolved_reasons.includes(
      "tracked_worktree_changes_are_newer_than_commit_bound_graph",
    );
  const graphStateIsBound =
    graphify.built_at_commit === manifest.source_commit &&
    ((manifest.release_class === "exact_commit" &&
      manifest.tracked_worktree_dirty === false &&
      graphify.status === "current" &&
      graphify.stale === false &&
      !dirtyGraphReasonIsPresent) ||
      (manifest.release_class === "dirty_preview" &&
        manifest.tracked_worktree_dirty === true &&
        graphify.status === "stale" &&
        graphify.stale === true &&
        dirtyGraphReasonIsPresent));
  if (
    !Object.hasOwn(graphify, "built_at_commit") ||
    (graphify.built_at_commit !== null &&
      (typeof graphify.built_at_commit !== "string" ||
        !/^[0-9a-f]{40}(?:[0-9a-f]{24})?$/.test(graphify.built_at_commit))) ||
    !graphStateIsBound ||
    graphify.identifier_projection_policy !== GRAPH_IDENTIFIER_POLICY ||
    !counts ||
    typeof counts !== "object" ||
    Array.isArray(counts) ||
    requireCount(counts.total, "Graphify total identifier count") !==
      requireCount(graphify.total_nodes, "Graphify total node count") ||
    requireCount(graphify.total_nodes, "Graphify total node count") !==
      requireCount(graphify.projected_nodes, "Graphify projected node count") +
        requireCount(graphify.excluded_nodes, "Graphify excluded node count") ||
    requireCount(graphify.total_edges, "Graphify total edge count") !==
      requireCount(graphify.projected_edges, "Graphify projected edge count") +
        requireCount(graphify.excluded_edges, "Graphify excluded edge count") ||
    requireCount(counts.projected_repository_relative, "Graphify projected identifier count") !== nodes.length ||
    requireCount(counts.excluded_opaque, "Graphify excluded identifier count") !==
      requireCount(graphify.excluded_nodes, "Graphify excluded node count") ||
    counts.raw_published !== 0 ||
    counts.projected_repository_relative + counts.excluded_opaque !== counts.total ||
    requireCount(graphify.projected_nodes, "Graphify projected node count") !== nodes.length ||
    requireCount(graphify.projected_edges, "Graphify projected edge count") !== edges.length ||
    !nodeDispositionCounts ||
    typeof nodeDispositionCounts !== "object" ||
    Array.isArray(nodeDispositionCounts) ||
    requireCount(nodeDispositionCounts.retained, "Graphify retained node disposition count") !==
      nodes.length ||
    requireCount(
      nodeDispositionCounts.excluded_unsafe_source,
      "Graphify unsafe-source node disposition count",
    ) +
      requireCount(
        nodeDispositionCounts.excluded_untracked_or_private,
        "Graphify private node disposition count",
      ) !==
      requireCount(graphify.excluded_nodes, "Graphify excluded node count") ||
    excludedNodeDispositions === null ||
    excludedNodeDispositions.length !== graphify.excluded_nodes ||
    excludedEdgeDispositions === null ||
    excludedEdgeDispositions.length !== graphify.excluded_edges ||
    endpointDispositionValues === null ||
    endpointDispositionValues.some(
      (value) => !Number.isSafeInteger(value) || value <= 0,
    ) ||
    endpointDispositionValues.reduce((total, value) => total + value, 0) !==
      graphify.excluded_edges
  ) {
    throw new Error("Graphify identifier disposition receipt is absent or inconsistent");
  }
  const nodeIds = new Set();
  const projectedIdentifiers = new Set();
  const nodeOccurrences = new Map();
  for (const node of nodes) {
    const file = typeof node?.source_file === "string" ? filesByPath.get(node.source_file) : null;
    const fileIsSafe =
      file?.privacyExposure === "full" &&
      Array.isArray(file.classificationErrors) &&
      file.classificationErrors.length === 0;
    const coordinateOccurrence = node?.coordinate_occurrence;
    const sourceLocation = node?.source_location;
    const expectedGraphifyId =
      fileIsSafe &&
      file.id === node?.file_id &&
      graphSourceLocationIsValid(sourceLocation) &&
      Number.isSafeInteger(coordinateOccurrence) &&
      coordinateOccurrence >= 0
        ? digestObject([
            "repository-relative-graph-node",
            node.source_file,
            sourceLocation,
            String(coordinateOccurrence),
          ])
        : null;
    const expectedNodeId = expectedGraphifyId
      ? stableId("graph-node", manifest.source_commit, expectedGraphifyId)
      : null;
    const expectedNodeLabel = expectedGraphifyId
      ? `${node.source_file}:${sourceLocation || "source"}#${coordinateOccurrence + 1}`
      : null;
    const expectedExtractionMode =
      node?.origin === "ast"
        ? "extracted"
        : node?.origin === "curated"
          ? "curated"
          : node?.origin === "undisclosed"
            ? "undisclosed"
            : null;
    const expectedEntityType = GRAPH_KINDS.has(node?.kind)
      ? `graph_node${node.kind ? `_${node.kind}` : ""}`
      : null;
    const nodeReasons = node?.unresolved_reasons;
    const nodeReasonsAreControlled =
      Array.isArray(nodeReasons) &&
      nodeReasons.length > 0 &&
      nodeReasons[0] === "graphify_node_label_derived_from_repository_relative_coordinate" &&
      nodeReasons.every((reason) => GRAPH_NODE_REASONS.has(reason)) &&
      new Set(nodeReasons).size === nodeReasons.length &&
      stableJson(nodeReasons) ===
        stableJson([...GRAPH_NODE_REASONS].filter((reason) => nodeReasons.includes(reason))) &&
      nodeReasons.includes(
        "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction",
      ) === (node?.origin !== "ast") &&
      (!nodeReasons.includes(
        "graphify_node_community_outside_js_safe_nonnegative_integer_domain",
      ) || node?.community === null) &&
      (!nodeReasons.includes("graphify_node_nonvocabulary_descriptor_withheld") ||
        [node?.file_type, node?.language, node?.kind].some((value) => value === "")) &&
      (!nodeReasons.includes(
        "graphify_node_source_location_outside_bounded_coordinate_domain",
      ) || sourceLocation === "");
    if (
      !node ||
      typeof node !== "object" ||
      !hasExactObjectKeys(node, [
        "id", "graphify_id", "coordinate_occurrence", "file_id", "source_file",
        "source_location", "label", "file_type", "language", "kind", "community",
        "origin", "extraction_mode", "entity_type", "unresolved_reasons",
      ]) ||
      typeof node.id !== "string" ||
      node.id !== expectedNodeId ||
      nodeIds.has(node.id) ||
      typeof node.graphify_id !== "string" ||
      node.graphify_id !== expectedGraphifyId ||
      projectedIdentifiers.has(node.graphify_id) ||
      !file ||
      !fileIsSafe ||
      node.file_id !== file.id ||
      node.label !== expectedNodeLabel ||
      !GRAPH_FILE_TYPES.has(node.file_type) ||
      !GRAPH_LANGUAGES.has(node.language) ||
      !GRAPH_KINDS.has(node.kind) ||
      !(node.community === null ||
        (Number.isSafeInteger(node.community) && node.community >= 0)) ||
      !["ast", "curated", "undisclosed"].includes(node.origin) ||
      node.extraction_mode !== expectedExtractionMode ||
      node.entity_type !== expectedEntityType ||
      !nodeReasonsAreControlled
    ) {
      throw new Error(
        "Graphify node lacks a unique recomputable full-exposure repository-relative identity",
      );
    }
    nodeIds.add(node.id);
    projectedIdentifiers.add(node.graphify_id);
    const coordinate = stableJson([node.source_file, sourceLocation]);
    const occurrences = nodeOccurrences.get(coordinate) ?? [];
    occurrences.push(coordinateOccurrence);
    nodeOccurrences.set(coordinate, occurrences);
  }
  for (const occurrences of nodeOccurrences.values()) {
    occurrences.sort((left, right) => left - right);
    if (occurrences.some((occurrence, index) => occurrence !== index)) {
      throw new Error("Graphify node coordinate occurrences are not contiguous and one-to-one");
    }
  }
  validateGraphExclusionLedger(graphify, nodeIds);
  const edgeIds = new Set();
  const edgeOccurrences = new Map();
  for (const edge of edges) {
    const edgeSourceFile = edge?.source_file;
    const edgeFile = typeof edgeSourceFile === "string" ? filesByPath.get(edgeSourceFile) : null;
    const edgeFileIsSafe =
      edgeFile?.privacyExposure === "full" &&
      Array.isArray(edgeFile.classificationErrors) &&
      edgeFile.classificationErrors.length === 0;
    const edgeLocation = edge?.source_location;
    const edgeOccurrence = edge?.coordinate_occurrence;
    const mode = edge?.extraction_mode;
    const relation = edge?.relation;
    const confidenceIdentity = graphConfidenceIdentity(edge?.confidence);
    const edgeReasons = edge?.unresolved_reasons;
    const edgeReasonsAreControlled =
      Array.isArray(edgeReasons) &&
      edgeReasons.every((reason) => GRAPH_EDGE_REASONS.has(reason)) &&
      new Set(edgeReasons).size === edgeReasons.length &&
      stableJson(edgeReasons) ===
        stableJson([...GRAPH_EDGE_REASONS].filter((reason) => edgeReasons.includes(reason))) &&
      edgeReasons.includes("graphify_confidence_mode_undisclosed_or_ambiguous") ===
        ["ambiguous", "undisclosed"].includes(mode) &&
      (!edgeReasons.includes("graphify_relation_not_in_controlled_vocabulary_shape") ||
        relation === "related_to") &&
      (!edgeReasons.includes(
        "graphify_edge_source_location_outside_bounded_coordinate_domain",
      ) || edgeLocation === "");
    const publicCoordinateIsValid =
      typeof edge?.source === "string" &&
      typeof edge?.target === "string" &&
      nodeIds.has(edge.source) &&
      nodeIds.has(edge.target) &&
      typeof relation === "string" &&
      GRAPH_RELATIONS.has(relation) &&
      (edgeSourceFile === null ||
        (typeof edgeSourceFile === "string" &&
          edgeFileIsSafe)) &&
      graphSourceLocationIsValid(edgeLocation) &&
      ["extracted", "inferred", "ambiguous", "undisclosed"].includes(mode) &&
      edge?.entity_type === "graph_edge" &&
      edgeReasonsAreControlled &&
      Number.isSafeInteger(edgeOccurrence) &&
      edgeOccurrence >= 0;
    const publicCoordinate = publicCoordinateIsValid
      ? [
          edge.source,
          edge.target,
          relation,
          edgeSourceFile ?? "",
          edgeLocation,
          mode,
          confidenceIdentity,
        ]
      : null;
    const expectedEdgeId = publicCoordinate
      ? stableId("graph-edge", manifest.source_commit, ...publicCoordinate, edgeOccurrence)
      : null;
    if (
      !edge ||
      typeof edge !== "object" ||
      !hasExactObjectKeys(edge, [
        "id", "source", "target", "relation", "coordinate_occurrence", "source_file",
        "source_location", "extraction_mode", "confidence", "entity_type",
        "unresolved_reasons",
      ]) ||
      typeof edge.id !== "string" ||
      edge.id !== expectedEdgeId ||
      edgeIds.has(edge.id) ||
      !publicCoordinateIsValid
    ) {
      throw new Error("Graphify edge endpoint, coordinate, or stable identity is inconsistent");
    }
    edgeIds.add(edge.id);
    const coordinate = stableJson(publicCoordinate);
    const occurrences = edgeOccurrences.get(coordinate) ?? [];
    occurrences.push(edgeOccurrence);
    edgeOccurrences.set(coordinate, occurrences);
  }
  for (const occurrences of edgeOccurrences.values()) {
    occurrences.sort((left, right) => left - right);
    if (occurrences.some((occurrence, index) => occurrence !== index)) {
      throw new Error("Graphify edge coordinate occurrences are not contiguous and one-to-one");
    }
  }
  const projectedCommunityNodeCounts = new Map();
  for (const node of nodes) {
    if (node.community !== null) {
      projectedCommunityNodeCounts.set(
        node.community,
        (projectedCommunityNodeCounts.get(node.community) ?? 0) + 1,
      );
    }
  }
  const projectedCommunityIds = [...projectedCommunityNodeCounts.keys()].sort(
    (left, right) => left - right,
  );
  const communityDispositionsById = new Map(
    graphify.community_dispositions.map((disposition) => [disposition.community, disposition]),
  );
  if (
    stableJson(projectedCommunityIds) !== stableJson(graphify.projected_community_ids) ||
    [...projectedCommunityNodeCounts].some(
      ([community, count]) =>
        communityDispositionsById.get(community)?.retained_nodes !== count,
    )
  ) {
    throw new Error("Graphify projected community census differs from graph nodes");
  }
  const projectedEdgeModes = Object.create(null);
  for (const edge of edges) {
    projectedEdgeModes[edge.extraction_mode] =
      (projectedEdgeModes[edge.extraction_mode] ?? 0) + 1;
  }
  if (stableJson(projectedEdgeModes) !== stableJson(graphify.projected_edge_modes)) {
    throw new Error("Graphify projected edge mode census differs from graph edges");
  }
}

async function writeGraphProjection(staging, nodes, edges) {
  await mkdir(join(staging, "graph", "shards"), { recursive: true });
  const nodeCommunity = new Map(nodes.map((node) => [node.id, node.community == null ? "unassigned" : String(node.community)]));
  const nodesByCommunity = Map.groupBy(nodes, (node) => nodeCommunity.get(node.id) ?? "unassigned");
  const edgesByCommunity = Map.groupBy(edges, (edge) => nodeCommunity.get(edge.source) ?? nodeCommunity.get(edge.target) ?? "unassigned");
  const communities = [...new Set([...nodesByCommunity.keys(), ...edgesByCommunity.keys()])].sort((left, right) => {
    if (left === "unassigned") return 1;
    if (right === "unassigned") return -1;
    return Number(left) - Number(right) || left.localeCompare(right);
  });
  const shardEntries = {};
  const allShards = [];
  for (const community of communities) {
    shardEntries[community] = { nodes: [], edges: [] };
    for (const [kind, records] of [
      ["nodes", nodesByCommunity.get(community) ?? []],
      ["edges", edgesByCommunity.get(community) ?? []],
    ]) {
      const pieces = [];
      for (let start = 0; start < records.length; start += GRAPH_SHARD_RECORDS) {
        pieces.push(...splitRecordsToBudget("records", records.slice(start, start + GRAPH_SHARD_RECORDS), GRAPH_SHARD_MAX_BYTES));
      }
      for (const [index, piece] of pieces.entries()) {
        const digest = sha256(piece.bytes);
        const communityKey = sha256(community).slice(0, 8);
        const modulePath = `graph/shards/${communityKey}-${kind}-${String(index).padStart(5, "0")}-${digest.slice(0, 16)}.mjs`;
        await writeFile(join(staging, ...modulePath.split("/")), piece.bytes);
        const descriptor = { community, kind, index, module: modulePath, bytes: piece.bytes.byteLength, sha256: digest, recordCount: piece.records.length };
        shardEntries[community][kind].push(descriptor);
        allShards.push(descriptor);
      }
    }
  }

  const orderedCommunities = communities.map((community) => ({
    id: community,
    nodeCount: (nodesByCommunity.get(community) ?? []).length,
    edgeCount: (edgesByCommunity.get(community) ?? []).length,
    nodeShards: shardEntries[community].nodes.length,
    edgeShards: shardEntries[community].edges.length,
  }));
  const sampleNodes = [];
  let sampleOffset = 0;
  while (sampleNodes.length < Math.min(GRAPH_SAMPLE_NODES, nodes.length)) {
    let added = false;
    for (const community of communities) {
      const candidate = (nodesByCommunity.get(community) ?? [])[sampleOffset];
      if (candidate) {
        sampleNodes.push(candidate);
        added = true;
        if (sampleNodes.length >= GRAPH_SAMPLE_NODES) break;
      }
    }
    if (!added) break;
    sampleOffset += 1;
  }
  const sampleIds = new Set(sampleNodes.map((node) => node.id));
  const sampleEdges = edges.filter((edge) => sampleIds.has(edge.source) && sampleIds.has(edge.target)).slice(0, GRAPH_SAMPLE_EDGES);
  const summary = {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    communities: orderedCommunities,
    sampleNodes,
    sampleEdges,
    disclosure: "bounded_deterministic_overview_select_a_community_for_complete_records",
  };
  const summaryBytes = Buffer.from(moduleText("summary", summary), "utf8");
  if (summaryBytes.byteLength > GRAPH_SHARD_MAX_BYTES) throw new Error("graph summary exceeds graph byte budget");
  const summaryDigest = sha256(summaryBytes);
  const summaryModule = `graph/summary-${summaryDigest.slice(0, 16)}.mjs`;
  await writeFile(join(staging, ...summaryModule.split("/")), summaryBytes);

  const loaderLines = Object.entries(shardEntries).map(([community, kinds]) =>
    `  ${JSON.stringify(community)}: Object.freeze({ nodes: Object.freeze([${kinds.nodes.map((entry) => `() => import(${JSON.stringify(`./${entry.module.replace("graph/", "")}`)})`).join(",")}]), edges: Object.freeze([${kinds.edges.map((entry) => `() => import(${JSON.stringify(`./${entry.module.replace("graph/", "")}`)})`).join(",")}]) }),`,
  ).join("\n");
  const graphIndexBytes = Buffer.from(
    `export const graphManifest = ${stableJson({ nodeCount: nodes.length, edgeCount: edges.length, communities: orderedCommunities, shardMaxBytes: GRAPH_SHARD_MAX_BYTES })};\n` +
      `const communityLoaders = Object.freeze({\n${loaderLines}\n});\n` +
      `export async function loadSummary() { const module = await import(${JSON.stringify(`./${summaryModule.replace("graph/", "")}`)}); return module.summary ?? module.default; }\n` +
      "export async function loadCommunity(community) {\n" +
      "  const loaders = communityLoaders[String(community)];\n" +
      "  if (!loaders) return null;\n" +
      "  const [nodeModules, edgeModules] = await Promise.all([Promise.all(loaders.nodes.map((loader) => loader())), Promise.all(loaders.edges.map((loader) => loader()))]);\n" +
      "  return { community: String(community), nodes: nodeModules.flatMap((module) => module.records ?? module.default ?? []), edges: edgeModules.flatMap((module) => module.records ?? module.default ?? []) };\n" +
      "}\n",
    "utf8",
  );
  const graphIndexDigest = sha256(graphIndexBytes);
  if (graphIndexBytes.byteLength > GRAPH_INDEX_MAX_BYTES) {
    throw new Error(`graph index exceeds ${GRAPH_INDEX_MAX_BYTES} bytes`);
  }
  const graphIndexModule = `graph/index-${graphIndexDigest.slice(0, 16)}.mjs`;
  await writeFile(join(staging, ...graphIndexModule.split("/")), graphIndexBytes);
  return {
    index: { module: graphIndexModule, bytes: graphIndexBytes.byteLength, sha256: graphIndexDigest },
    summary: { module: summaryModule, bytes: summaryBytes.byteLength, sha256: summaryDigest },
    shards: allShards,
    communities: orderedCommunities,
    nodeCount: nodes.length,
    edgeCount: edges.length,
    maxShardBytes: Math.max(0, ...allShards.map((entry) => entry.bytes)),
  };
}

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--input" || value === "--output") result[value.slice(2)] = argv[++index];
    if (value === "--allow-preview") result.allowPreview = true;
  }
  if (!result.input || !result.output) {
    throw new Error("usage: node build.mjs --input <compiler-output> --output <public-projection-dir>");
  }
  return result;
}

async function buildProjectionUnsafe({ input, output, allowPreview = false }, lifecycle) {
  const inputRoot = await realpath(resolve(input));
  const outputRoot = assertSafeDestination(output);
  const { parsed: manifest } = await readCanonicalJson(inputRoot, "manifest.json");
  if (manifest.architecture_conformance?.path !== "architecture-conformance.json") {
    throw new Error("compiler architecture receipt owner path is malformed");
  }
  const completeness = await readVerified(inputRoot, manifest.completeness, "completeness.json");
  const graphify = await readVerified(
    inputRoot,
    manifest.graphify_metadata,
    "graphify-metadata.json",
  );
  const invariantByName = validateCompilerContract(manifest, completeness, graphify);
  if (manifest.status !== "complete" || completeness.hard_failure) {
    throw new Error("compiler output is not complete and publishable");
  }
  if ((completeness.fatal_errors ?? []).length) {
    throw new Error("compiler output contains fatal errors");
  }
  if (
    completeness.source_commit !== manifest.source_commit ||
    completeness.source_tree_digest !== manifest.source_tree_digest ||
    stableJson(completeness.graphify) !== stableJson(graphify) ||
    graphify.source_commit !== manifest.source_commit ||
    graphify.source_tree_digest !== manifest.source_tree_digest
  ) {
    throw new Error("compiler completeness ledger is not bound or structurally complete");
  }
  const isExactRelease =
    manifest.release_class === "exact_commit" && manifest.tracked_worktree_dirty === false;
  const isDirtyPreview =
    manifest.release_class === "dirty_preview" && manifest.tracked_worktree_dirty === true;
  if (
    (!isExactRelease && !isDirtyPreview) ||
    completeness.tracked_worktree_dirty !== manifest.tracked_worktree_dirty
  ) {
    throw new Error("compiler release class and tracked-worktree state are inconsistent");
  }
  if (completeness.privacy?.forbidden_content_scan?.status !== "passed") {
    throw new Error("compiler privacy scan is absent or failed");
  }
  if (
    !allowPreview && !isExactRelease
  ) {
    throw new Error(
      "publishable projection requires release_class exact_commit and a clean tracked worktree; use --allow-preview only for an explicitly labelled local preview",
    );
  }

  const metadataGroupNames = Object.keys(manifest.groups)
    .filter((name) => !NON_METADATA_GROUPS.has(name))
    .sort();
  const seenIds = new Map();
  const dossierIds = new Set();
  let claimRecords = [];
  let consequentialClaimFacetRecords = [];
  const groups = Object.fromEntries(metadataGroupNames.map((name) => [name, []]));
  for (const name of metadataGroupNames) {
    const rawRecords = await loadGroup(inputRoot, manifest, name, { seenIds });
    if (name === "claims") claimRecords = rawRecords;
    if (name === "consequential_claim_facets") consequentialClaimFacetRecords = rawRecords;
    if (name === "routes" || name === "components") {
      for (const record of rawRecords) validateGuiDossier(record, name, manifest, dossierIds);
    }
    groups[name] = rawRecords.map((record) => compactRecord(name, record));
  }
  validateClaimEvidenceSubjectSeparation(claimRecords, seenIds);

  const filesByPath = new Map();
  for (const file of groups.files) {
    let pathIsSafe = false;
    try {
      pathIsSafe = safeRelative(file?.path).join("/") === file.path;
    } catch {
      pathIsSafe = false;
    }
    if (!pathIsSafe || filesByPath.has(file.path)) {
      throw new Error("duplicate or invalid tracked file path");
    }
    filesByPath.set(file.path, file);
  }
  validateGraphProjectionContract(
    manifest,
    graphify,
    groups.graph_nodes ?? [],
    groups.graph_edges ?? [],
    filesByPath,
  );
  if (
    requireCount(completeness.census?.tracked_files, "completeness tracked_files") !== filesByPath.size ||
    requireCount(completeness.census?.classified_files, "completeness classified_files") !== filesByPath.size
  ) {
    throw new Error("tracked/classified file denominator differs from the compiler file group");
  }
  const safeParsedFiles = [...filesByPath.values()].filter((file) =>
    file.privacyExposure === "full" &&
    file.parseStatus === "parsed" &&
    typeof file.contentDigest === "string" &&
    file.classificationErrors.length === 0);
  const safeParsedFileIds = new Set(safeParsedFiles.map((file) => file.id));
  const structuralRootPaths = new Set();
  for (const root of groups.structural_entities) {
    const file = filesByPath.get(root.path);
    if (
      !file ||
      !safeParsedFileIds.has(file.id) ||
      structuralRootPaths.has(root.path) ||
      root.file_id !== file.id ||
      root.root_scope !== "parsed_source" ||
      root.parser_owned !== true ||
      root.source_basis !== file.contentSource ||
      root.git_blob_oid !== file.gitBlobOid ||
      root.content_digest !== file.contentDigest ||
      root.line_count !== file.lineCount ||
      root.nonblank_line_count !== file.nonblankLineCount ||
      !Number.isSafeInteger(root.explanation_depth) ||
      root.explanation_depth < 1
    ) {
      throw new Error(`structural root is stale, duplicated, or not file-bound: ${String(root.id)}`);
    }
    structuralRootPaths.add(root.path);
  }
  const structuralRootInvariant = invariantByName.get(
    "every_safe_parsed_source_has_one_structural_root",
  );
  if (
    structuralRootPaths.size !== safeParsedFiles.length ||
    groups.structural_entities.length !== safeParsedFiles.length ||
    safeParsedFiles.some((file) => !structuralRootPaths.has(file.path)) ||
    structuralRootInvariant.expected !== safeParsedFiles.length ||
    structuralRootInvariant.actual !== groups.structural_entities.length ||
    requireCount(
      completeness.semantic_accounting?.safe_parsed_sources,
      "completeness safe_parsed_sources",
    ) !== safeParsedFiles.length ||
    requireCount(
      completeness.semantic_accounting?.structural_root_entities,
      "completeness structural_root_entities",
    ) !== groups.structural_entities.length
  ) {
    throw new Error("safe parsed source/structural root denominator differs");
  }
  const symbolsByPath = Map.groupBy(groups.symbols, (record) => record.path);
  const lineMetadataByPath = new Map();
  let loadedLineCount = 0;
  await loadGroup(inputRoot, manifest, "lines", {
    retain: false,
    seenIds,
    onRecord: (record) => {
      const file = filesByPath.get(record.path);
      if (
        !file ||
        file.privacyExposure !== "full" ||
        record.file_id !== file.id ||
        !Number.isSafeInteger(record.line) ||
        record.line < 1 ||
        record.line > file.lineCount ||
        record.line_number !== record.line ||
        record.source_commit !== manifest.source_commit ||
        !/^[0-9a-f]{64}$/.test(String(record.text_digest ?? "")) ||
        !/^[0-9a-f]{64}$/.test(String(record.line_digest ?? "")) ||
        !STRUCTURAL_MAPPING_BASES.has(record.structural_mapping_basis) ||
        !Number.isSafeInteger(record.explanation_depth) ||
        record.explanation_depth < 1 ||
        typeof record.semantic_entity !== "string" ||
        !record.semantic_entity.trim()
      ) {
        throw new Error(`line record is not exact, mapped, or file-bound: ${String(record.id)}`);
      }
      let lines = lineMetadataByPath.get(record.path);
      if (!lines) {
        lines = new Map();
        lineMetadataByPath.set(record.path, lines);
      }
      if (lines.has(record.line)) {
        throw new Error(`duplicate source line record: ${record.path}:${record.line}`);
      }
      lines.set(record.line, {
        id: record.id,
        fileId: record.file_id,
        textDigest: record.text_digest,
        lineDigest: record.line_digest,
        syntaxKind: record.syntax_kind,
        structuralMappingBasis: record.structural_mapping_basis ?? null,
        containingSymbol: record.containing_symbol ?? null,
        syntaxDepth: record.depth ?? 0,
        language: record.language ?? filesByPath.get(record.path)?.language ?? "unknown",
        semanticEntity: record.semantic_entity ?? null,
        owner: record.owner ?? null,
        behaviorGroup: record.behavior_group ?? [],
        inputsAndOutputs: record.inputs_and_outputs ?? null,
        claimsInfluenced: record.claims_influenced ?? [],
        callersAndDependencies: record.callers_and_dependencies ?? [],
        testsCoveringIt: record.tests_covering_it ?? [],
        testCoverageState: record.test_coverage_state ?? "not_emitted",
        runtimeTraceState: record.runtime_trace_state ?? "not_emitted",
        guiOrArtifactConsumers: record.GUI_or_artifact_consumers ?? [],
        securityAndPrivacyEffect: record.security_and_privacy_effect ?? null,
        currentOrHistorical: record.current_or_historical ?? null,
        explanationDepth: record.explanation_depth ?? 0,
        unresolvedReasons: record.unresolved_reasons ?? [],
      });
      loadedLineCount += 1;
    },
  });
  const expectedNonblankLines = groups.files.reduce(
    (total, file) => total + requireCount(file.nonblankLineCount, `file nonblank_line_count ${file.path}`),
    0,
  );
  const lineInvariant = invariantByName.get("every_safe_line_structurally_mapped");
  if (
    loadedLineCount !== manifest.groups.lines.record_count ||
    loadedLineCount !== completeness.record_counts.lines ||
    loadedLineCount !== requireCount(completeness.parsing?.line_records, "completeness line_records") ||
    expectedNonblankLines !== requireCount(
      completeness.parsing?.expected_nonblank_lines,
      "completeness expected_nonblank_lines",
    ) ||
    loadedLineCount !== expectedNonblankLines ||
    lineInvariant.expected !== expectedNonblankLines ||
    lineInvariant.actual !== loadedLineCount ||
    requireCount(
      completeness.semantic_accounting?.structurally_mapped_lines,
      "completeness structurally_mapped_lines",
    ) !== loadedLineCount
  ) {
    throw new Error("file/nonblank/line/completeness denominator differs");
  }
  const guiSurfaceCount = groups.routes.length + groups.components.length;
  const guiInvariant = invariantByName.get(
    "every_gui_surface_has_standardized_evidence_honest_dossier",
  );
  if (
    dossierIds.size !== guiSurfaceCount ||
    guiInvariant.expected !== guiSurfaceCount ||
    guiInvariant.actual !== dossierIds.size ||
    requireCount(
      completeness.semantic_accounting?.gui_surface_records,
      "completeness gui_surface_records",
    ) !== guiSurfaceCount ||
    requireCount(
      completeness.semantic_accounting?.gui_dossiers,
      "completeness gui_dossiers",
    ) !== dossierIds.size
  ) {
    throw new Error("GUI surface/dossier/completeness denominator differs");
  }

  const parent = dirname(outputRoot);
  const stagingPrefix = `.${basename(outputRoot)}.staging-${process.pid}-`;
  await mkdir(parent, { recursive: true });
  const staging = await mkdtemp(join(parent, stagingPrefix));
  const stagingInfo = await lstat(staging);
  lifecycle.staging = {
    path: staging,
    parent,
    prefix: stagingPrefix,
    dev: stagingInfo.dev,
    ino: stagingInfo.ino,
  };
  await writeFile(join(staging, GENERATED_MARKER), "atlas-projection-v2.0\n", "utf8");
  await mkdir(join(staging, "source"), { recursive: true });
  await mkdir(join(staging, "metadata"), { recursive: true });
  await mkdir(join(staging, "records"), { recursive: true });

  const sourceProjection = await writeSourceProjection({
    staging,
    inputRoot,
    manifest,
    filesByPath,
    symbolsByPath,
    lineMetadataByPath,
    seenIds,
    completeness,
    claimPredicates: groups.claims.map((record) => record.predicate),
    claimFacetRecords: consequentialClaimFacetRecords,
    claimUnavailableReason:
      manifest.release_class === "dirty_preview" && manifest.tracked_worktree_dirty === true
        ? "consequential_claim_dirty_preview_not_eligible"
        : "consequential_claim_contract_absent",
  });
  const expectedSourceFiles = [...filesByPath.values()].filter((file) =>
    file.privacyExposure === "full" &&
    file.language !== "binary" &&
    typeof file.contentDigest === "string" &&
    file.classificationErrors.length === 0);
  const expectedPhysicalLines = expectedSourceFiles.reduce(
    (total, file) => total + requireCount(file.lineCount, `file line_count ${file.path}`),
    0,
  );
  if (
    sourceProjection.files !== expectedSourceFiles.length ||
    sourceProjection.files !== manifest.groups.source_text.record_count ||
    sourceProjection.files !== completeness.record_counts.source_text ||
    sourceProjection.physicalLines !== expectedPhysicalLines ||
    sourceProjection.nonblankLines !== loadedLineCount
  ) {
    throw new Error("file/source-text/physical-line/nonblank denominator differs");
  }
  const sourceEntries = sourceProjection.modules;

  const recordFragmentPlans = new Map();
  const metadataModules = [];
  const metadataLoaderEntries = {};
  const symbolMetadataModuleRecordIds = [];
  for (const [group, groupRecords] of Object.entries(groups)) {
    metadataLoaderEntries[group] = [];
    await mkdir(join(staging, "metadata", group), { recursive: true });
    const pieces = [];
    if (groupRecords.length === 0) {
      // An empty symbol group has no routable dossier. Keep its loader list empty
      // instead of publishing an unaddressable physical module. Other metadata
      // groups retain their historical explicit empty module representation.
      if (group !== "symbols") {
        pieces.push({ records: [], bytes: Buffer.from(moduleText("records", []), "utf8") });
      }
    } else {
      for (let start = 0; start < groupRecords.length; start += METADATA_CHUNK_SIZE) {
        pieces.push(...splitRecordsToBudget(
          "records",
          groupRecords.slice(start, start + METADATA_CHUNK_SIZE),
          LAZY_MODULE_MAX_BYTES,
          `metadata ${group}`,
          recordFragmentPlans,
        ));
      }
    }
    for (const [moduleIndex, piece] of pieces.entries()) {
      const { records: chunk, bytes } = piece;
      if (bytes.byteLength > LAZY_MODULE_MAX_BYTES) {
        throw new Error(`metadata ${group} module exceeds ${LAZY_MODULE_MAX_BYTES} bytes`);
      }
      const digest = sha256(bytes);
      const modulePath = `metadata/${group}/${String(moduleIndex).padStart(5, "0")}-${digest.slice(0, 16)}.mjs`;
      await writeFile(join(staging, ...modulePath.split("/")), bytes);
      const entry = {
        group,
        module: modulePath,
        recordCount: piece.recordCount ?? chunk.length,
        bytes: bytes.byteLength,
        sha256: digest,
        ...(piece.fragmentPlan
          ? {
              fragmentedRecordId: piece.fragmentPlan.id,
              fragmentCount: piece.fragmentPlan.fragments.length,
              serializedBytes: piece.fragmentPlan.serializedBytes,
              serializedDigest: piece.fragmentPlan.serializedDigest,
            }
          : {}),
      };
      metadataModules.push(entry);
      metadataLoaderEntries[group].push(entry);
      if (group === "symbols") {
        symbolMetadataModuleRecordIds.push(
          piece.fragmentPlan
            ? [piece.fragmentPlan.id]
            : chunk.map((record) => record.id),
        );
      }
    }
    if (
      metadataLoaderEntries[group].reduce((total, entry) => total + entry.recordCount, 0) !==
      groupRecords.length
    ) {
      throw new Error(`metadata module denominator differs for ${group}`);
    }
  }

  const symbolMetadataRoute = buildSymbolMetadataRoute(
    metadataLoaderEntries.symbols,
    symbolMetadataModuleRecordIds,
    {
      recordCount: manifest.groups.symbols.record_count,
      recordsDigest: manifest.groups.symbols.records_digest,
    },
  );
  const recordRoutes = { symbol: symbolMetadataRoute };

  const recordBucketEntries = {};
  const recordBucketSplitPrefixes = {};
  for (const [kind, groupNames] of Object.entries(DOSSIER_GROUPS)) {
    const records = groupNames.flatMap((group) => groups[group] ?? [])
      .sort((left, right) => left.id.localeCompare(right.id));
    const buckets = Map.groupBy(
      records,
      (record) => fnv1a(String(record.id)).slice(0, DOSSIER_BASE_PREFIX_LENGTH),
    );
    const splitPrefixes = new Set();
    const leaves = [];
    for (const [prefix, bucketRecords] of [...buckets.entries()].sort(([left], [right]) =>
      left.localeCompare(right))) {
      splitDossierBucket(
        kind,
        bucketRecords,
        prefix,
        splitPrefixes,
        leaves,
        recordFragmentPlans,
      );
    }
    recordBucketEntries[kind] = [];
    recordBucketSplitPrefixes[kind] = [...splitPrefixes].sort();
    await mkdir(join(staging, "records", kind), { recursive: true });
    const leafByPrefix = new Map(leaves.map((leaf) => [leaf.prefix, leaf]));
    for (const record of records) {
      const routedPrefix = dossierPrefixFor(record.id, splitPrefixes);
      const routedLeaf = leafByPrefix.get(routedPrefix);
      if (
        !routedLeaf ||
        (!routedLeaf.records.some((candidate) => candidate.id === record.id) &&
          routedLeaf.fragmentPlan?.id !== record.id)
      ) {
        throw new Error(`dossier prefix routing lost ${kind}:${record.id}`);
      }
    }
    for (const leaf of leaves.sort((left, right) => left.prefix.localeCompare(right.prefix))) {
      const { prefix, records: leafRecords, bytes } = leaf;
      if (bytes.byteLength > LAZY_MODULE_MAX_BYTES) {
        throw new Error(`dossier ${kind} module exceeds ${LAZY_MODULE_MAX_BYTES} bytes`);
      }
      const modulePath = `records/${kind}/${prefix}-${sha256(bytes).slice(0, 16)}.mjs`;
      await writeFile(join(staging, ...modulePath.split("/")), bytes);
      recordBucketEntries[kind].push({
        prefix,
        module: modulePath,
        recordCount: leaf.recordCount ?? leafRecords.length,
        bytes: bytes.byteLength,
        sha256: sha256(bytes),
        ...(leaf.fragmentPlan
          ? {
              fragmentedRecordId: leaf.fragmentPlan.id,
              fragmentCount: leaf.fragmentPlan.fragments.length,
              serializedBytes: leaf.fragmentPlan.serializedBytes,
              serializedDigest: leaf.fragmentPlan.serializedDigest,
            }
          : {}),
      });
    }
    if (
      recordBucketEntries[kind].reduce((total, entry) => total + entry.recordCount, 0) !==
      records.length
    ) {
      throw new Error(`dossier module denominator differs for ${kind}`);
    }
  }

  const recordFragments = [];
  const writtenFragmentPaths = new Map();
  for (const plan of [...recordFragmentPlans.values()].sort((left, right) =>
    left.id.localeCompare(right.id))) {
    for (const fragment of plan.fragments) {
      const priorDigest = writtenFragmentPaths.get(fragment.module);
      if (priorDigest && priorDigest !== fragment.sha256) {
        throw new Error(`record fragment module collision: ${fragment.module}`);
      }
      if (!priorDigest) {
        await mkdir(dirname(join(staging, ...fragment.module.split("/"))), { recursive: true });
        await writeFile(join(staging, ...fragment.module.split("/")), fragment.value);
        writtenFragmentPaths.set(fragment.module, fragment.sha256);
      }
      recordFragments.push({
        recordId: plan.id,
        serializedDigest: plan.serializedDigest,
        fragmentIndex: fragment.index,
        fragmentCount: plan.fragments.length,
        module: fragment.module,
        bytes: fragment.bytes,
        textBytes: fragment.textBytes,
        sha256: fragment.sha256,
      });
    }
  }

  const searchProjection = await writeSearchProjection(staging, groups);
  const graphProjection = await writeGraphProjection(
    staging,
    groups.graph_nodes ?? [],
    groups.graph_edges ?? [],
  );

  const projection = {
    schemaVersion: PROJECTION_SCHEMA_VERSION,
    status: "complete",
    releaseClass: manifest.release_class,
    sourceCommit: manifest.source_commit,
    sourceTreeDigest: manifest.source_tree_digest,
    headTreeOid: manifest.head_tree_oid,
    compilerIndexDigest: manifest.index_digest,
    trackedWorktreeDirty: Boolean(manifest.tracked_worktree_dirty),
    previewAllowed: Boolean(allowPreview),
    completeness,
    groupCounts: Object.fromEntries(
      Object.entries(groups).map(([name, records]) => [name, records.length]),
    ),
    sourceFileCount: sourceProjection.files,
    sourceModuleCount: sourceEntries.length,
    sourceDigestPolicy: SOURCE_DIGEST_POLICY,
    disclosure: {
      metadataDerivation: "compiler_structural",
      metadataCoverage: "every_manifest_group_except_lines_and_source_text",
      searchLoading: "query_token_hash_selective_bounded_shards_with_normalized_document_table",
      sourceLoading: "per_file_bounded_line_and_byte_chunks",
      graphLoading: "bounded_summary_then_selected_community_shards",
      oversizedRecordLoading: "lossless_content_hashed_utf8_fragments_reassembled_on_demand",
      restrictedContent: "metadata_only_never_embedded",
      semanticLimit: "structural mapping is not behavioral or verified understanding",
    },
  };
  const identity = {
    schemaVersion: projection.schemaVersion,
    status: projection.status,
    releaseClass: projection.releaseClass,
    sourceCommit: projection.sourceCommit,
    sourceTreeDigest: projection.sourceTreeDigest,
    trackedWorktreeDirty: projection.trackedWorktreeDirty,
    failedAcceptanceGates: projection.completeness.acceptance_gates
      .filter((gate) => !gate.passed)
      .map((gate) => ({ name: gate.name })),
  };
  const identityBytes = Buffer.from(
    `export const identity = ${stableJson(identity)};\nexport default identity;\n`,
    "utf8",
  );
  if (identityBytes.byteLength > IDENTITY_MODULE_MAX_BYTES) {
    throw new Error(
      `projection identity module exceeds ${IDENTITY_MODULE_MAX_BYTES} bytes: ${identityBytes.byteLength}`,
    );
  }
  await writeFile(join(staging, "identity.mjs"), identityBytes);
  const bucketLoaderLines = Object.entries(recordBucketEntries)
    .map(
      ([kind, entries]) =>
        `  ${JSON.stringify(kind)}: Object.freeze({\n${entries
          .map(
            (entry) =>
              `    ${JSON.stringify(entry.prefix)}: () => import(${JSON.stringify(`./${entry.module}`)}),`,
          )
          .join("\n")}\n  }),`,
    )
    .join("\n");
  const compactSymbolMetadataRoute = {
    group: symbolMetadataRoute.group,
    kind: symbolMetadataRoute.kind,
    moduleCount: symbolMetadataRoute.moduleCount,
    recordCount: symbolMetadataRoute.recordCount,
    orderedIdsDigest: symbolMetadataRoute.orderedIdsDigest,
    entriesDigest: symbolMetadataRoute.entriesDigest,
    upperBoundsDigest: symbolMetadataRoute.upperBoundsDigest,
    upperBounds: symbolMetadataRoute.entries.map((entry) => entry.upperId),
  };
  const indexBytes = Buffer.from(
    `export const projection = ${stableJson(projection)};\n` +
      `export const metadataLoaders = Object.freeze({\n${Object.entries(metadataLoaderEntries)
        .map(
          ([group, entries]) =>
            `  ${JSON.stringify(group)}: Object.freeze([${entries
              .map((entry) => `() => import(${JSON.stringify(`./${entry.module}`)})`)
              .join(",")}]),`,
        )
        .join("\n")}\n});\n` +
      `const symbolMetadataRoute = Object.freeze(${stableJson(compactSymbolMetadataRoute)});\n` +
      "const symbolMetadataUpperBounds = Object.freeze([...symbolMetadataRoute.upperBounds]);\n" +
      "if (symbolMetadataRoute.group !== \"symbols\" || symbolMetadataRoute.kind !== \"metadata_module_upper_bound_route_v1\" || symbolMetadataRoute.moduleCount !== metadataLoaders.symbols.length || symbolMetadataRoute.recordCount !== projection.groupCounts.symbols || symbolMetadataUpperBounds.length !== symbolMetadataRoute.moduleCount || symbolMetadataUpperBounds.some((bound, index) => typeof bound !== \"string\" || !/^urn:atlas:symbol:[0-9a-f]{24}$/.test(bound) || (index > 0 && bound <= symbolMetadataUpperBounds[index - 1]))) throw new Error(\"symbol metadata route is absent or inconsistent\");\n" +
      `export const recordBucketLoaders = Object.freeze({\n${bucketLoaderLines}\n});\n` +
      `export const recordBucketSplitPrefixes = Object.freeze(${stableJson(recordBucketSplitPrefixes)});\n` +
      "const recordBucketSplitPrefixSets = Object.fromEntries(Object.entries(recordBucketSplitPrefixes).map(([kind, prefixes]) => [kind, new Set(prefixes)]));\n" +
      `${fnv1a.toString()}\n` +
      "function bucketFor(kind, id) {\n" +
      "  const hash = fnv1a(String(id));\n" +
      `  let prefix = hash.slice(0, ${DOSSIER_BASE_PREFIX_LENGTH});\n` +
      "  const splitPrefixes = recordBucketSplitPrefixSets[kind];\n" +
      "  while (splitPrefixes?.has(prefix)) prefix = hash.slice(0, prefix.length + 1);\n" +
      "  return prefix;\n" +
      "}\n" +
      `${upperBoundIndex.toString()}\n` +
      "export async function loadMetadata(group) {\n" +
      "  const loaders = metadataLoaders[group];\n" +
      "  if (!loaders) return [];\n" +
      "  const modules = await Promise.all(loaders.map((loader) => loader()));\n" +
      "  const batches = await Promise.all(modules.map((module) => typeof module.loadRecords === \"function\" ? module.loadRecords() : (module.records ?? module.default ?? [])));\n" +
      "  return batches.flat();\n" +
      "}\n" +
      "export async function loadRecord(kind, id) {\n" +
      "  if (kind === \"symbol\") {\n" +
      "    if (typeof id !== \"string\" || !/^urn:atlas:symbol:[0-9a-f]{24}$/.test(id)) return null;\n" +
      "    const moduleIndex = upperBoundIndex(symbolMetadataUpperBounds, id);\n" +
      "    if (moduleIndex < 0) return null;\n" +
      "    const loader = metadataLoaders.symbols[moduleIndex];\n" +
      "    if (typeof loader !== \"function\") throw new Error(\"symbol metadata route is absent or inconsistent\");\n" +
      "    const module = await loader();\n" +
      "    const records = typeof module.loadRecords === \"function\" ? await module.loadRecords() : (module.records ?? module.default ?? []);\n" +
      "    if (!Array.isArray(records)) throw new Error(\"symbol metadata module is malformed\");\n" +
      "    const matches = records.filter((record) => record?.id === id);\n" +
      "    if (matches.length > 1) throw new Error(\"symbol metadata route resolved duplicate records\");\n" +
      "    return matches[0] ?? null;\n" +
      "  }\n" +
      "  const loader = recordBucketLoaders[kind]?.[bucketFor(kind, id)];\n" +
      "  if (!loader) return null;\n" +
      "  const module = await loader();\n" +
      "  const direct = (module.records ?? module.default ?? []).find((record) => record.id === id);\n" +
      "  if (direct) return direct;\n" +
      "  return typeof module.loadFragmentedRecord === \"function\" ? module.loadFragmentedRecord(id) : null;\n" +
      "}\n" +
      `async function sourceProjection() { return import(${JSON.stringify(`./${sourceProjection.index.module}`)}); }\n` +
      "export async function loadSource(path) { const module = await sourceProjection(); return module.getSourceFile(path); }\n" +
      "export async function loadSourceChunk(path, chunkIndex) { const module = await sourceProjection(); return module.loadSourceChunk(path, chunkIndex); }\n" +
      "export async function loadSourceWindow(path, line) { const module = await sourceProjection(); return module.loadSourceWindow(path, line); }\n" +
      `async function searchProjection() { return import(${JSON.stringify(`./${searchProjection.index.module}`)}); }\n` +
      "export async function searchRecords(tokens) { const module = await searchProjection(); return module.searchTerms(tokens); }\n" +
      `async function graphProjection() { return import(${JSON.stringify(`./${graphProjection.index.module}`)}); }\n` +
      "export async function loadGraphSummary() { const module = await graphProjection(); return module.loadSummary(); }\n" +
      "export async function loadGraphCommunity(community) { const module = await graphProjection(); return module.loadCommunity(community); }\n" +
      "export default projection;\n",
    "utf8",
  );
  await writeFile(join(staging, "index.mjs"), indexBytes);

  const outputManifest = {
    schemaVersion: PROJECTION_SCHEMA_VERSION,
    sourceCommit: manifest.source_commit,
    sourceTreeDigest: manifest.source_tree_digest,
    releaseClass: manifest.release_class,
    compilerIndexDigest: manifest.index_digest,
    groupCounts: projection.groupCounts,
    identity: {
      path: "identity.mjs",
      bytes: identityBytes.byteLength,
      sha256: sha256(identityBytes),
    },
    index: { path: "index.mjs", bytes: indexBytes.byteLength, sha256: sha256(indexBytes) },
    metadataModules,
    recordFragments,
    recordRoutes,
    recordBuckets: recordBucketEntries,
    recordBucketSplitPrefixes,
    search: searchProjection,
    graph: graphProjection,
    sourceIndex: sourceProjection.index,
    sourceFileCount: sourceProjection.files,
    sourceModules: sourceEntries,
    sourceDigestPolicy: SOURCE_DIGEST_POLICY,
    budgets: {
      identityModuleMaxBytes: IDENTITY_MODULE_MAX_BYTES,
      searchShardMaxBytes: SEARCH_SHARD_MAX_BYTES,
      searchDocumentShardMaxBytes: SEARCH_DOCUMENT_SHARD_MAX_BYTES,
      searchIndexMaxBytes: SEARCH_INDEX_MAX_BYTES,
      sourceChunkMaxBytes: SOURCE_CHUNK_MAX_BYTES,
      sourceIndexMaxBytes: SOURCE_INDEX_MAX_BYTES,
      graphShardMaxBytes: GRAPH_SHARD_MAX_BYTES,
      graphIndexMaxBytes: GRAPH_INDEX_MAX_BYTES,
      metadataModuleMaxBytes: LAZY_MODULE_MAX_BYTES,
      dossierModuleMaxBytes: LAZY_MODULE_MAX_BYTES,
      recordFragmentModuleMaxBytes: LAZY_MODULE_MAX_BYTES,
    },
  };
  await writeFile(
    join(staging, "projection-manifest.json"),
    `${stableJson(outputManifest)}\n`,
    "utf8",
  );
  await replaceGeneratedDirectory(staging, outputRoot);
  lifecycle.staging = null;
  return outputManifest;
}

async function cleanupOwnedProjectionStaging(owner) {
  if (!owner) return;
  const absolute = resolve(owner.path);
  const parent = resolve(owner.parent);
  if (dirname(absolute) !== parent || !basename(absolute).startsWith(owner.prefix)) {
    throw new Error("projection staging cleanup ownership check failed");
  }
  let info;
  try {
    info = await lstat(absolute);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw new Error("projection staging cleanup ownership check failed");
  }
  if (!info.isDirectory() || info.dev !== owner.dev || info.ino !== owner.ino) {
    throw new Error("projection staging cleanup ownership check failed");
  }
  await rm(absolute, { recursive: true, force: false });
}

export async function buildProjection(options) {
  const lifecycle = { staging: null };
  try {
    return await buildProjectionUnsafe(options, lifecycle);
  } catch (error) {
    try {
      await cleanupOwnedProjectionStaging(lifecycle.staging);
    } catch {
      throw new Error("projection staging cleanup failed");
    }
    throw error;
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const result = await buildProjection(args);
    process.stdout.write(
      `${JSON.stringify({ output: resolve(args.output), sourceModules: result.sourceModules.length })}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
