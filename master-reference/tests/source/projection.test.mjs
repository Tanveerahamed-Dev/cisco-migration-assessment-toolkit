import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import {
  beginCommunitySelection,
  rejectCommunitySelection,
  resolveCommunitySelection,
} from "../../app/atlas/GraphSelection.mjs";
import {
  buildProjection,
  COMPILER_RECORD_KEYS_BY_GROUP,
  isPythonStripEmpty,
  reconstructConsequentialClaimFacetRecords,
  validateConsequentialClaimCensus,
  validateSymbolMetadataRoute,
} from "../../build/projection/build.mjs";

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const gitBlobOid = (value) => createHash("sha1")
  .update(Buffer.from(`blob ${value.byteLength}\0`, "ascii"))
  .update(value)
  .digest("hex");
const gitBlobOid64 = (value) => createHash("sha256")
  .update(Buffer.from(`blob ${value.byteLength}\0`, "ascii"))
  .update(value)
  .digest("hex");
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
};
const digestObject = (value) => sha256(Buffer.from(`${stableJson(value)}\n`, "utf8"));
const stableId = (kind, ...parts) =>
  `urn:atlas:${kind}:${sha256(Buffer.from(parts.map(String).join("\u001f"), "utf8")).slice(0, 24)}`;
const ATLAS_STABLE_ID_PATTERN = /^urn:atlas:[a-z-]+:[0-9a-f]{24}$/;
const fixtureStableId = (value) => {
  if (ATLAS_STABLE_ID_PATTERN.test(value)) return value;
  const kind = /^urn:atlas:([a-z-]+):/.exec(value)?.[1] ?? "fixture";
  return stableId(kind, value);
};
const normalizeFixtureUrns = (value) => {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      value[index] = normalizeFixtureUrns(value[index]);
    }
    return value;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) value[key] = normalizeFixtureUrns(item);
    return value;
  }
  return typeof value === "string" && value.startsWith("urn:atlas:")
    ? fixtureStableId(value)
    : value;
};
const graphConfidenceIdentity = (value) => {
  if (value === null) return "none";
  if (Number.isInteger(value)) return `integer:${value}`;
  const bytes = Buffer.allocUnsafe(8);
  bytes.writeDoubleBE(value, 0);
  return `float64:${bytes.toString("hex")}`;
};

const GUI_DOSSIER_FIELD_NAMES = [
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
];
const REQUIRED_ACCEPTANCE_GATE_NAMES = [
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
];
const CONSEQUENTIAL_CLAIM_PATHS = [
  "master-reference/content/atlas-core.json",
  "master-reference/content/capability-catalog.json",
  "master-reference/content/delivery-governance.json",
  "master-reference/content/open-horizon-register.json",
  "master-reference/content/output-contract.json",
];
const CONSEQUENTIAL_CLAIM_CONTRACT_PATH =
  "master-reference/governance/consequential-claim-contract.json";
const CONSEQUENTIAL_INTEGRITY_PREDICATES = [
  "repository.full_exposure_file_count",
  "repository.graphify_status",
  "repository.nonblank_line_record_count",
  "repository.source_commit",
  "repository.source_tree_digest",
  "repository.tracked_file_count",
];

function unavailableConsequentialClaimSummary(
  sourceCommit,
  sourceTreeDigest,
  reasonCode = "consequential_claim_contract_absent",
) {
  return {
    schema_version: "bounded-curated-consequential-claims/2",
    denominator_kind: "bounded_curated_content_claim_denominator",
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
    error_codes: [reasonCode, "consequential_claim_source_universe_incomplete"],
  };
}

function guiDossier(surfaceId, surfaceKind) {
  const citation = {
    record_id: surfaceId,
    path: "app/example.py",
    start_line: 1,
    end_line: 2,
    line_state: "source_range",
    evidence_role: "gui_surface_declaration",
  };
  const fields = Object.fromEntries(GUI_DOSSIER_FIELD_NAMES.map((name) => [name, {
    state: name === "props_contract" ? "explicitly_linked" : "not_evidenced",
    value: name === "props_contract" ? { sentinel: `${surfaceKind}-props-preserved-verbatim` } : null,
    citations: name === "props_contract" ? [citation] : [],
    unresolved_reasons: name === "props_contract"
      ? ["fixture_explicit_link_is_not_runtime_validation"]
      : [`${name}_not_evidenced_in_fixture`],
    gap_ids: [name.includes("white_label") ? "gap.white-label" : "gap.accessibility-performance"],
  }]));
  const unresolvedReasons = [...new Set(Object.values(fields).flatMap((field) => field.unresolved_reasons))].sort();
  const gapIds = [...new Set(Object.values(fields).flatMap((field) => field.gap_ids))].sort();
  return {
    id: `urn:atlas:gui-dossier:${surfaceKind}:${surfaceId.split(":").at(-1)}`,
    surface_id: surfaceId,
    surface_kind: surfaceKind,
    source_commit: "d".repeat(40),
    source_citation: citation,
    evidence_state: "explicitly_linked",
    derivation: "compiler_structural_evidence_only",
    field_count: GUI_DOSSIER_FIELD_NAMES.length,
    ...fields,
    unresolved_reasons: unresolvedReasons,
    gap_ids: gapIds,
  };
}

async function writeDescriptor(root, relativePath, value) {
  const bytes = Buffer.from(`${stableJson(value)}\n`, "utf8");
  const path = join(root, ...relativePath.split("/"));
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
  return { path: relativePath, bytes: bytes.byteLength, sha256: sha256(bytes) };
}

async function writeVerifiedValue(input, descriptor, value) {
  const bytes = Buffer.from(`${stableJson(value)}\n`, "utf8");
  await writeFile(join(input, ...descriptor.path.split("/")), bytes);
  return { ...descriptor, bytes: bytes.byteLength, sha256: sha256(bytes) };
}

async function mutateCompilerGroup(input, group, mutate, { reconcileCount = true } = {}) {
  const manifestPath = join(input, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const groupDescriptor = manifest.groups[group];
  const envelopes = await Promise.all(groupDescriptor.chunks.map(async (chunkDescriptor) =>
    JSON.parse(await readFile(join(input, ...chunkDescriptor.path.split("/")), "utf8"))));
  assert.ok(envelopes.length > 0, "fixture mutation helper expects a nonempty compiler group");
  const envelope = {
    ...envelopes[0],
    chunk_index: 0,
    chunk_count: 1,
    records: envelopes.flatMap((item) => item.records),
  };
  await mutate(envelope);
  if (envelope.records.every((record) => typeof record?.id === "string")) {
    envelope.records.sort((left, right) => left.id.localeCompare(right.id));
  }
  envelope.record_count = envelope.records.length;
  envelope.records_digest = digestObject(envelope.records.map((record) => record.id));
  const partitions = group === "source_text"
    ? envelope.records.map((record) => [record])
    : [envelope.records];
  const chunks = [];
  for (const [index, partition] of partitions.entries()) {
    const chunkEnvelope = {
      ...envelope,
      chunk_index: index,
      chunk_count: partitions.length,
      record_count: partition.length,
      records_digest: digestObject(partition.map((record) => record.id)),
      records: partition,
    };
    chunks.push({
      ...await writeDescriptor(
        input,
        `chunks/${group}/${String(index).padStart(5, "0")}.json`,
        chunkEnvelope,
      ),
      record_count: partition.length,
    });
  }
  manifest.groups[group] = {
    ...groupDescriptor,
    record_count: envelope.records.length,
    records_digest: envelope.records_digest,
    chunk_count: chunks.length,
    chunks,
  };
  if (reconcileCount) {
    const completeness = JSON.parse(
      await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
    );
    completeness.record_counts[group] = envelope.records.length;
    manifest.completeness = await writeVerifiedValue(input, manifest.completeness, completeness);
  }
  await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
  return envelope.records;
}

async function rewriteCompilerPacking(input, chunkSize, targetGroup, mutatePartitions) {
  const manifestPath = join(input, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.chunk_size = chunkSize;
  for (const [group, descriptor] of Object.entries(manifest.groups)) {
    const records = [];
    for (const chunk of descriptor.chunks) {
      const envelope = JSON.parse(await readFile(join(input, ...chunk.path.split("/")), "utf8"));
      records.push(...envelope.records);
    }
    const effectiveChunkSize = group === "source_text" ? 1 : chunkSize;
    let partitions = [];
    for (let index = 0; index < records.length; index += effectiveChunkSize) {
      partitions.push(records.slice(index, index + effectiveChunkSize));
    }
    if (group === targetGroup) partitions = mutatePartitions(partitions);
    const orderedRecords = partitions.flat();
    const chunks = [];
    for (const [index, partition] of partitions.entries()) {
      const envelope = {
        schema_version: "1.2.0",
        record_type: group,
        source_commit: manifest.source_commit,
        source_tree_digest: manifest.source_tree_digest,
        chunk_index: index,
        chunk_count: partitions.length,
        record_count: partition.length,
        records_digest: digestObject(partition.map((record) => record.id)),
        records: partition,
      };
      chunks.push({
        ...await writeDescriptor(input, `chunks/${group}/${String(index).padStart(5, "0")}.json`, envelope),
        record_count: partition.length,
      });
    }
    manifest.groups[group] = {
      record_count: orderedRecords.length,
      chunk_count: partitions.length,
      records_digest: digestObject(orderedRecords.map((record) => record.id)),
      chunks,
    };
  }
  await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
}

async function mutateGraphifyReceipt(input, mutate) {
  const manifestPath = join(input, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const graphify = JSON.parse(
    await readFile(join(input, ...manifest.graphify_metadata.path.split("/")), "utf8"),
  );
  await mutate(graphify);
  manifest.graphify_metadata = await writeVerifiedValue(
    input,
    manifest.graphify_metadata,
    graphify,
  );
  const completeness = JSON.parse(
    await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
  );
  completeness.graphify = graphify;
  manifest.completeness = await writeVerifiedValue(input, manifest.completeness, completeness);
  await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
}

async function seedGraphifyExclusionLedger(input) {
  await mutateGraphifyReceipt(input, (graphify) => {
    graphify.total_nodes += 1;
    graphify.excluded_nodes = 1;
    graphify.excluded_nodes_untracked_or_private = 1;
    graphify.node_disposition_counts.excluded_untracked_or_private = 1;
    graphify.node_identifier_disposition_counts.total += 1;
    graphify.node_identifier_disposition_counts.excluded_opaque = 1;
    graphify.node_origins.undisclosed = (graphify.node_origins.undisclosed ?? 0) + 1;
    const nodeRawIndex = graphify.total_nodes - 1;
    const nodeDispositionId = stableId(
      "graph-node-disposition", graphify.source_digest, nodeRawIndex,
    );
    graphify.excluded_node_dispositions = [{
      id: nodeDispositionId,
      disposition: "excluded",
      raw_index: nodeRawIndex,
      reason: "excluded_untracked_or_private",
    }];
    graphify.total_edges += 1;
    graphify.excluded_edges = 1;
    graphify.all_edge_modes.undisclosed = (graphify.all_edge_modes.undisclosed ?? 0) + 1;
    graphify.excluded_edge_endpoint_dispositions = {
      source_excluded_untracked_or_private__target_missing_node: 1,
    };
    const edgeRawIndex = graphify.total_edges - 1;
    graphify.excluded_edge_dispositions = [{
      id: stableId("graph-edge-disposition", graphify.source_digest, edgeRawIndex),
      disposition: "excluded",
      raw_index: edgeRawIndex,
      reason: "endpoint_not_projected",
      source_endpoint: {
        state: "excluded_untracked_or_private",
        record_id: nodeDispositionId,
        anonymous_slot: null,
      },
      target_endpoint: {
        state: "missing_node",
        record_id: null,
        anonymous_slot: 0,
      },
    }];
  });
}

function fnv1a(value) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

async function makeCompilerFixture(root) {
  const input = join(root, "compiler");
  await mkdir(input, { recursive: true });
  const denseTail = "x".repeat(300_000);
  const exact = Buffer.from(`def hello():\r\n    return "Atlas"${denseTail}\r\n`, "utf8");
  const secondExact = Buffer.from("\n", "utf8");
  const lines = [
    { number: 1, text: "def hello():", terminator: "\r\n" },
    { number: 2, text: `    return "Atlas"${denseTail}`, terminator: "\r\n" },
  ].map((line) => ({
    ...line,
    text_digest: sha256(Buffer.from(line.text, "utf8")),
    line_digest: sha256(Buffer.from(`${line.text}${line.terminator}`, "utf8")),
  }));
  const safeId = fixtureStableId("urn:atlas:file:safe");
  const privateId = fixtureStableId("urn:atlas:file:private");
  const secondId = fixtureStableId("urn:atlas:file:second");
  const sourceCommit = "d".repeat(40);
  const fixtureClaimPredicates = [
    "repository.source_commit",
    ...CONSEQUENTIAL_INTEGRITY_PREDICATES.filter(
      (predicate) => predicate !== "repository.source_commit",
    ),
  ];
  const projectedGraphId = (sourceFile, sourceLocation, occurrence) =>
    digestObject([
      "repository-relative-graph-node",
      sourceFile,
      sourceLocation,
      String(occurrence),
    ]);
  const helloGraphifyId = projectedGraphId("app/example.py", "1", 0);
  const callerGraphifyId = projectedGraphId("app/example.py", "2", 0);
  const externalGraphifyId = projectedGraphId("app/example.py", "2", 1);
  const helloGraphNodeId = stableId("graph-node", sourceCommit, helloGraphifyId);
  const callerGraphNodeId = stableId("graph-node", sourceCommit, callerGraphifyId);
  const externalGraphNodeId = stableId("graph-node", sourceCommit, externalGraphifyId);
  const graphEdgeId = (source, target, relation, mode, confidence, occurrence) => stableId(
    "graph-edge",
    sourceCommit,
    source,
    target,
    relation,
    "app/example.py",
    "2",
    mode,
    graphConfidenceIdentity(confidence),
    occurrence,
  );
  const records = {
    files: [
      {
        id: safeId,
        path: "app/example.py",
        language: "python",
        media_type: "text/x-python",
        roles: ["source"],
        size_bytes: exact.byteLength,
        line_count: 2,
        nonblank_line_count: 2,
        content_digest: sha256(exact),
        git_blob_oid: "a".repeat(40),
        content_source: "selected_commit_git_blob",
        privacy_exposure: "full",
        privacy_reasons: [],
        parse_status: "parsed",
        parser: "python_ast",
        parser_mode: "semantic",
        unresolved_reasons: [],
      },
      {
        id: privateId,
        path: "assets/private.bin",
        language: "binary",
        media_type: "application/octet-stream",
        roles: ["binary"],
        size_bytes: 4,
        line_count: 0,
        nonblank_line_count: 0,
        content_digest: sha256(Buffer.from([0, 1, 2, 3])),
        git_blob_oid: "b".repeat(40),
        content_source: "metadata_only_git_object",
        privacy_exposure: "metadata_only",
        privacy_reasons: ["binary_content_opaque"],
        parse_status: "binary_inventory",
        parser: "binary_metadata",
        parser_mode: "metadata",
        unresolved_reasons: [],
      },
      {
        id: secondId,
        path: "0-second.txt",
        language: "text",
        media_type: "text/plain",
        roles: ["source"],
        size_bytes: secondExact.byteLength,
        line_count: 1,
        nonblank_line_count: 0,
        content_digest: sha256(secondExact),
        git_blob_oid: "f".repeat(40),
        content_source: "selected_commit_git_blob",
        privacy_exposure: "full",
        privacy_reasons: [],
        parse_status: "not_parsed",
        parser: "none",
        parser_mode: "metadata",
        unresolved_reasons: ["blank_fixture_has_no_structural_parse"],
      },
    ],
    lines: lines.map((line, index) => ({
      id: `urn:atlas:line:${index + 1}`,
      file_id: safeId,
      path: "app/example.py",
      line: index + 1,
      language: "python",
      syntax_kind: index ? "Return" : "FunctionDef",
      structural_mapping_basis: "symbol_range",
      containing_symbol: "hello",
      depth: index,
      text_digest: line.text_digest,
      line_digest: line.line_digest,
      text_bytes: Buffer.byteLength(line.text),
      source_commit: "d".repeat(40),
      line_number: index + 1,
      syntax_depth: index,
      semantic_entity: "urn:atlas:symbol:hello",
      owner: safeId,
      behavior_group: ["source"],
      inputs_and_outputs: { parameters: [], return_or_output: "str" },
      claims_influenced: ["urn:atlas:claim:greeting"],
      callers_and_dependencies: ["urn:atlas:symbol:caller"],
      tests_covering_it: ["urn:atlas:test:hello"],
      test_coverage_state: "direct_line_coverage",
      runtime_trace_state: "synthetic_trace",
      GUI_or_artifact_consumers: ["urn:atlas:component:greeting"],
      security_and_privacy_effect: { source_exposure: "full", semantic_effect: "none" },
      current_or_historical: "current_source",
      explanation_depth: index ? 2 : 3,
      unresolved_reasons: ["field_fixture_uncertainty"],
    })),
    source_text: [
      {
        id: "urn:atlas:source-text:safe",
        file_id: safeId,
        path: "app/example.py",
        encoding: "utf-8",
        byte_count: exact.byteLength,
        content_digest: sha256(exact),
        source_basis: "selected_commit_git_blob",
        git_blob_oid: "a".repeat(40),
        line_count: 2,
        lines,
      },
      {
        id: "urn:atlas:source-text:second",
        file_id: secondId,
        path: "0-second.txt",
        encoding: "utf-8",
        byte_count: secondExact.byteLength,
        content_digest: sha256(secondExact),
        source_basis: "selected_commit_git_blob",
        git_blob_oid: "f".repeat(40),
        line_count: 1,
        lines: [{
          number: 1,
          text: "",
          terminator: "\n",
          text_digest: sha256(Buffer.from("", "utf8")),
          line_digest: sha256(secondExact),
        }],
      },
    ],
    symbols: [
      {
        id: "urn:atlas:symbol:hello",
        file_id: safeId,
        path: "app/example.py",
        name: "hello",
        qualified_name: "hello",
        kind: "function",
        language: "python",
        range: { start_line: 1, start_column: 0, end_line: 2, end_column: 18 },
        exported: true,
        digest: "c".repeat(64),
        depth: 0,
        purpose: "Return the Atlas greeting.",
        purpose_basis: "owned_docstring",
        responsibility: "Own the deterministic greeting.",
        parameters_and_types: [],
        return_or_output: "str",
        state_read: [],
        state_written: [],
        external_effects: [],
        failure_and_exception_behavior: "none_declared",
        abstention_behavior: "not_applicable",
        callers: ["urn:atlas:symbol:caller"],
        caller_resolution: "static_name_inference",
        callees: [],
        data_dependencies: [],
        claims_produced_or_consumed: ["urn:atlas:claim:greeting"],
        tests: ["urn:atlas:test:hello"],
        test_linkage: "direct",
        runtime_trace_evidence: ["urn:atlas:trace:hello"],
        runtime_trace_state: "synthetic_trace",
        performance_characteristics: "constant_time",
        security_boundary: "none",
        downstream_surfaces: ["urn:atlas:component:greeting"],
        limitations: ["fixture_only"],
        known_impact_if_changed: ["urn:atlas:component:greeting"],
        history: [{ source_commit: "d".repeat(40), event: "reviewed" }],
        criticality: "review_required",
        explanation_depth: 4,
        review_state: "independently_reviewed",
        stable_urn: "urn:atlas:symbol:hello",
        path_and_range: { path: "app/example.py", range: { start_line: 1, end_line: 2 } },
        unresolved_reasons: ["fixture_only"],
      },
    ],
    structural_entities: [{
      id: "urn:atlas:structural-root:safe",
      file_id: safeId,
      path: "app/example.py",
      name: "app/example.py",
      kind: "python_module",
      entity_type: "structural_root_python_module",
      root_scope: "parsed_source",
      range: { start_line: 1, start_column: 0, end_line: 2, end_column: 0 },
      range_state: "exact_source_lines",
      line_count: 2,
      nonblank_line_count: 2,
      parser: "python_ast",
      parser_mode: "semantic",
      parser_version: "fixture",
      parser_owned: true,
      language: "python",
      roles: ["source"],
      source_basis: "selected_commit_git_blob",
      git_blob_oid: "a".repeat(40),
      content_digest: sha256(exact),
      generation_provenance: {
        state: "not_declared",
        basis: "no_generated_role_or_generator_declaration",
        generator_record_ids: [],
      },
      extraction_disposition: "parser_structural_root",
      explanation_depth: 1,
      uncertainty: ["structural_root_does_not_establish_behavior_or_execution"],
      unresolved_reasons: ["structural_root_does_not_establish_behavior_or_execution"],
    }],
    imports: [{
      id: "urn:atlas:import:json",
      file_id: safeId,
      path: "app/example.py",
      module: "json",
      names: [],
      alias: null,
      kind: "import",
      containing_symbol: null,
      range: { start_line: 1, start_column: 0, end_line: 1, end_column: 11 },
    }],
    calls: [{
      id: "urn:atlas:call:hello",
      file_id: safeId,
      path: "app/example.py",
      callee: "hello",
      containing_symbol: "caller",
      range: { start_line: 2, start_column: 4, end_line: 2, end_column: 11 },
      resolved: false,
      unresolved_reasons: ["static_name_only_no_binding_resolution"],
    }, ...Array.from({ length: 70 }, (_, index) => ({
      id: `urn:atlas:call:test-backlink-${String(index).padStart(2, "0")}`,
      file_id: safeId,
      path: "app/example.py",
      callee: `backlink_${index}`,
      containing_symbol: "caller",
      range: { start_line: 2, start_column: 4, end_line: 2, end_column: 11 },
      resolved: false,
      tests: ["urn:atlas:test:hello"],
      unresolved_reasons: ["search_posting_cap_fixture"],
    }))],
    markdown: [{ id: "urn:atlas:markdown:heading", file_id: safeId, path: "app/example.py", heading: "Fixture", level: 1 }],
    structured: [{ id: "urn:atlas:structured:key", file_id: safeId, path: "app/example.py", key: "fixture", value_type: "string" }],
    datasets: [],
    tests: [
      {
        id: "urn:atlas:test:hello",
        file_id: safeId,
        path: "app/example.py",
        name: "test_hello",
        framework: "pytest",
        range: { start_line: 1, start_column: 0, end_line: 2, end_column: 18 },
        entity_type: "test_case",
        assertion_group_id: "urn:atlas:test:hello:assertions",
        assertion_count: 1,
        extraction_disposition: "structurally_extracted",
        unresolved_reasons: [],
      },
      {
        id: "urn:atlas:test:hello:assertions",
        file_id: safeId,
        path: "app/example.py",
        name: "test_hello::assertions",
        framework: "python_ast",
        range: { start_line: 1, start_column: 0, end_line: 2, end_column: 18 },
        entity_type: "test_assertion_group",
        assertion_count: 1,
        assertions: [{
          kind: "assert_statement",
          range: { start_line: 2, start_column: 4, end_line: 2, end_column: 18 },
          digest: "1".repeat(64),
        }],
        extraction_disposition: "structurally_extracted",
        unresolved_reasons: [],
      },
    ],
    workflows: [
      {
        id: "urn:atlas:workflow:ci",
        file_id: safeId,
        path: "app/example.py",
        name: "Fixture CI",
        entity_type: "workflow",
        triggers: ["push"],
        jobs: ["verify"],
        job_ids: ["urn:atlas:workflow:ci:job"],
        step_ids: ["urn:atlas:workflow:ci:step"],
        permission_ids: ["urn:atlas:workflow:ci:permission"],
        artifact_ids: ["urn:atlas:workflow:ci:artifact"],
        parser_mode: "structural",
        extraction_disposition: "structurally_extracted_with_explicit_limits",
        unresolved_reasons: ["yaml_semantics_not_resolved"],
      },
      {
        id: "urn:atlas:workflow:ci:job",
        file_id: safeId,
        path: "app/example.py",
        name: "verify",
        entity_type: "workflow_job",
        steps: ["urn:atlas:workflow:ci:step"],
        permissions: ["urn:atlas:workflow:ci:permission"],
        artifacts: ["urn:atlas:workflow:ci:artifact"],
        parser_mode: "structural",
        extraction_disposition: "structurally_extracted",
        unresolved_reasons: ["job_matrix_needs_and_conditions_not_evaluated"],
      },
      {
        id: "urn:atlas:workflow:ci:step",
        file_id: safeId,
        path: "app/example.py",
        name: "Upload proof",
        entity_type: "workflow_step",
        job: "verify",
        step_index: 0,
        uses: "actions/upload-artifact@v4",
        run_declared: false,
        source_digest: "2".repeat(64),
        range: { start_line: 1, start_column: 0, end_line: 2, end_column: null },
        parser_mode: "structural",
        extraction_disposition: "structurally_extracted",
        unresolved_reasons: ["yaml_semantics_and_expressions_not_resolved"],
      },
      {
        id: "urn:atlas:workflow:ci:permission",
        file_id: safeId,
        path: "app/example.py",
        name: "contents",
        entity_type: "workflow_permission",
        scope: "job:verify",
        access: "read",
        parser_mode: "structural",
        extraction_disposition: "structurally_extracted",
        unresolved_reasons: [],
      },
      {
        id: "urn:atlas:workflow:ci:artifact",
        file_id: safeId,
        path: "app/example.py",
        name: "proof",
        entity_type: "workflow_artifact",
        job: "verify",
        step_id: "urn:atlas:workflow:ci:step",
        direction: "produced",
        declared_path: "proof.json",
        action: "actions/upload-artifact@v4",
        parser_mode: "structural",
        extraction_disposition: "explicit_artifact_action",
        unresolved_reasons: ["artifact_name_or_path_expression_not_evaluated"],
      },
    ],
    binaries: [{ id: "urn:atlas:binary:private", file_id: privateId, path: "assets/private.bin" }],
    components: [{
      id: "urn:atlas:component:greeting",
      file_id: safeId,
      path: "app/example.py",
      name: "GreetingCard",
      framework: "tsx",
      entity_type: "jsx_component_symbol",
      range: { start_line: 1, start_column: 0, end_line: 2, end_column: 18 },
      attribute_names: ["aria-label", "onClick"],
      gui_dossier: guiDossier("urn:atlas:component:greeting", "component"),
      unresolved_reasons: ["gui_dossier_behavior_and_runtime_not_verified"],
    }],
    configs: [],
    documents: [],
    routes: [{
      id: "urn:atlas:route:greeting",
      file_id: safeId,
      path: "app/example.py",
      name: "greeting_route",
      route: "/greeting",
      method: "GET",
      handler: "hello",
      framework: "fixture",
      entity_type: "api_route",
      range: { start_line: 1, start_column: 0, end_line: 2, end_column: 18 },
      gui_dossier: guiDossier("urn:atlas:route:greeting", "route"),
      unresolved_reasons: ["gui_dossier_behavior_and_runtime_not_verified"],
    }],
    manifests: [{ id: "urn:atlas:manifest:fixture", file_id: safeId, path: "app/example.py", kind: "fixture" }],
    dependencies: [{
      id: "urn:atlas:dependency:pytest",
      file_id: safeId,
      path: "app/example.py",
      ecosystem: "python",
      scope: "test",
      name: "pytest",
      constraint: "pytest==9.1.1",
      resolved_version: "9.1.1",
    }],
    graph_nodes: [
      { id: helloGraphNodeId, graphify_id: helloGraphifyId, coordinate_occurrence: 0, file_id: safeId, source_file: "app/example.py", source_location: "1", label: "app/example.py:1#1", file_type: "code", language: "python", kind: "function", community: 1, origin: "ast", extraction_mode: "extracted", entity_type: "graph_node_function", unresolved_reasons: ["graphify_node_label_derived_from_repository_relative_coordinate"] },
      { id: callerGraphNodeId, graphify_id: callerGraphifyId, coordinate_occurrence: 0, file_id: safeId, source_file: "app/example.py", source_location: "2", label: "app/example.py:2#1", file_type: "code", language: "python", kind: "function", community: 1, origin: "ast", extraction_mode: "extracted", entity_type: "graph_node_function", unresolved_reasons: ["graphify_node_label_derived_from_repository_relative_coordinate"] },
      { id: externalGraphNodeId, graphify_id: externalGraphifyId, coordinate_occurrence: 1, file_id: safeId, source_file: "app/example.py", source_location: "2", label: "app/example.py:2#2", file_type: "code", language: "python", kind: "symbol", community: null, origin: "undisclosed", extraction_mode: "undisclosed", entity_type: "graph_node_symbol", unresolved_reasons: ["graphify_node_label_derived_from_repository_relative_coordinate", "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction"] },
    ],
    graph_edges: [
      { id: graphEdgeId(helloGraphNodeId, callerGraphNodeId, "calls", "extracted", 1, 0), source: helloGraphNodeId, target: callerGraphNodeId, relation: "calls", coordinate_occurrence: 0, source_file: "app/example.py", source_location: "2", extraction_mode: "extracted", confidence: 1, entity_type: "graph_edge", unresolved_reasons: [] },
      { id: graphEdgeId(callerGraphNodeId, externalGraphNodeId, "references", "inferred", 0.5, 0), source: callerGraphNodeId, target: externalGraphNodeId, relation: "references", coordinate_occurrence: 0, source_file: "app/example.py", source_location: "2", extraction_mode: "inferred", confidence: 0.5, entity_type: "graph_edge", unresolved_reasons: [] },
    ],
    claims: fixtureClaimPredicates.map((predicate, index) => ({
      id: index === 0 ? "urn:atlas:claim:greeting" : `urn:atlas:claim:integrity-${index}`,
      subject: "urn:atlas:source-state:fixture",
      predicate,
      value: index === 0 ? "d".repeat(40) : index,
      unit: null,
      basis: "deterministic_structural_derivation_from_exact_git_tree",
      scope: { source_commit: "d".repeat(40), universe: "git_tracked_tree" },
      effective_time: "2026-08-07T00:00:00Z",
      recorded_time: "2026-08-07T00:00:00Z",
      temporal_basis: "git_commit_committer_time",
      owner: "urn:atlas:owner:compiler",
      evidence_ids: ["urn:atlas:completeness:fixture"],
      evidence_class: "derived",
      transformation: { id: `urn:atlas:transformation:integrity-${index}`, version: "1.0.0" },
      denominator: { value: 1, unit: "git_tracked_tree", basis: "compiler_source_snapshot", status: "known" },
      verdict: "proven",
      freshness: "current",
      lineage: ["urn:atlas:completeness:fixture"],
      derived_from: [],
      origin: "atlas_repository_compiler",
      extraction_mode: "structural",
      confidence: 1,
      status: "current",
      revoked_by: null,
      revocation_reason: null,
      conflicts_with: [],
      current_view: true,
      satisfies_evidence_requirement: true,
      source_commit: "d".repeat(40),
      unresolved_reasons: [],
    })),
    consequential_claim_facets: [],
  };
  normalizeFixtureUrns(records);

  const groups = {};
  for (const [group, groupRecords] of Object.entries(records)) {
    if (groupRecords.length === 0) {
      groups[group] = {
        record_count: 0,
        chunk_count: 0,
        records_digest: digestObject([]),
        chunks: [],
      };
      continue;
    }
    const canonicalGroupRecords = [...groupRecords].sort((left, right) => left.id.localeCompare(right.id));
    const partitions = group === "source_text"
      ? canonicalGroupRecords.map((record) => [record])
      : [canonicalGroupRecords];
    const chunks = [];
    for (const [index, partition] of partitions.entries()) {
      const envelope = {
        schema_version: "1.2.0",
        record_type: group,
        source_commit: "d".repeat(40),
        source_tree_digest: "e".repeat(64),
        chunk_index: index,
        chunk_count: partitions.length,
        record_count: partition.length,
        records_digest: digestObject(partition.map((record) => record.id)),
        records: partition,
      };
      chunks.push({
        ...await writeDescriptor(
          input,
          `chunks/${group}/${String(index).padStart(5, "0")}.json`,
          envelope,
        ),
        record_count: partition.length,
      });
    }
    groups[group] = {
      record_count: canonicalGroupRecords.length,
      chunk_count: chunks.length,
      records_digest: digestObject(canonicalGroupRecords.map((record) => record.id)),
      chunks,
    };
  }
  const graphifyValue = {
    schema_version: "1.2.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    available: true,
    status: "current",
    source: "graphify-out/graph.json",
    source_bytes: 4096,
    report_available: true,
    stale: false,
    built_at_commit: sourceCommit,
    source_digest: "9".repeat(64),
    total_nodes: records.graph_nodes.length,
    total_hyperedges: 0,
    projected_nodes: records.graph_nodes.length,
    excluded_nodes: 0,
    excluded_node_dispositions: [],
    node_disposition_counts: {
      retained: records.graph_nodes.length,
      excluded_unsafe_source: 0,
      excluded_untracked_or_private: 0,
    },
    total_edges: records.graph_edges.length,
    projected_edges: records.graph_edges.length,
    excluded_edges: 0,
    excluded_edge_dispositions: [],
    excluded_edge_endpoint_dispositions: {},
    all_edge_modes: { extracted: 1, inferred: 1 },
    projected_edge_modes: { extracted: 1, inferred: 1 },
    node_origins: { ast: 2, undisclosed: 1 },
    excluded_nodes_unsafe_source: 0,
    excluded_nodes_untracked_or_private: 0,
    identifier_projection_policy: "raw_identifiers_withheld_repository_relative_retained_source_index_excluded",
    node_identifier_disposition_counts: {
      total: records.graph_nodes.length,
      projected_repository_relative: records.graph_nodes.length,
      excluded_opaque: 0,
      raw_published: 0,
    },
    total_communities: 1,
    projected_communities: 1,
    excluded_communities: 0,
    all_community_ids: [1],
    projected_community_ids: [1],
    excluded_community_ids: [],
    partial_community_ids: [],
    community_status_counts: { projected_complete: 1, projected_partial: 0, excluded: 0 },
    community_dispositions: [
      { community: 1, status: "projected_complete", total_nodes: 2, retained_nodes: 2, excluded_nodes: 0 },
    ],
    projection_policy: "tracked_full_exposure_files_only",
    unresolved_reasons: [
      "graphify_is_optional_secondary_projection",
      "graphify_has_no_hyperedges",
      "graphify_incremental_rebuild_may_evict_cross_file_edges_until_full_rebuild",
      "graphify_raw_identifiers_are_withheld_and_exclusion_dispositions_use_source_index_only",
      "graphify_producer_labels_are_replaced_by_repository_relative_coordinate_labels_and_descriptors_use_controlled_vocabularies",
    ],
  };
  const completenessValue = {
    id: fixtureStableId("urn:atlas:completeness:fixture"),
    schema_version: "1.2.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    tracked_worktree_dirty: false,
    hard_failure: false,
    fatal_errors: [],
    census: { tracked_files: 3, classified_files: 3, full_exposure_files: 2, metadata_only_files: 1 },
    parsing: { expected_nonblank_lines: 2, line_records: 2 },
    semantic_accounting: {
      safe_parsed_sources: 1,
      structural_root_entities: 1,
      structurally_mapped_lines: 2,
      gui_surface_records: 2,
      gui_dossiers: 2,
      consequential_claim_denominator_state: "not_declared",
    },
    consequential_claim_denominator: unavailableConsequentialClaimSummary(
      "d".repeat(40),
      "e".repeat(64),
    ),
    graphify: graphifyValue,
    privacy: {
      primary_corpus: "git_ls_files_only",
      forbidden_content_scan: { status: "passed", findings_count: 0 },
    },
    record_counts: Object.fromEntries(Object.entries(records).map(([name, value]) => [name, value.length])),
    invariants: [
      { name: "every_tracked_file_classified", expected: 3, actual: 3, passed: true },
      { name: "every_safe_text_file_has_exact_source_record", expected: 2, actual: 2, passed: true },
      { name: "every_safe_line_structurally_mapped", expected: 2, actual: 2, passed: true },
      { name: "every_safe_parsed_source_has_one_structural_root", expected: 1, actual: 1, passed: true },
      { name: "every_gui_surface_has_standardized_evidence_honest_dossier", expected: 2, actual: 2, passed: true },
      { name: "graphify_receipt_exact_source_bound", expected: 1, actual: 1, passed: true },
    ],
    acceptance_gates: REQUIRED_ACCEPTANCE_GATE_NAMES.map((name) => ({
      name,
      expected: true,
      actual: ![
        "runtime_trace_evidence_joined_to_source_records",
        "consequential_claim_denominator_closed",
      ].includes(name),
      passed: ![
        "runtime_trace_evidence_joined_to_source_records",
        "consequential_claim_denominator_closed",
      ].includes(name),
    })),
  };
  const completeness = await writeDescriptor(input, "completeness.json", completenessValue);
  const graphify = await writeDescriptor(input, "graphify-metadata.json", graphifyValue);
  const architecture = await writeDescriptor(input, "architecture-conformance.json", {
    schema_version: "1.2.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
  });
  const manifest = {
    schema_version: "1.2.0",
    status: "complete",
    release_class: "exact_commit",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    head_tree_oid: "f".repeat(40),
    index_digest: "0".repeat(64),
    tracked_worktree_dirty: false,
    chunk_size: 2000,
    completeness,
    graphify_metadata: graphify,
    architecture_conformance: architecture,
    groups,
  };
  await writeFile(join(input, "manifest.json"), `${stableJson(manifest)}\n`, "utf8");
  return { input, exact, secondExact, records };
}

async function trackedConsequentialClaimFixture() {
  const goldenReceipts = new Map([
    ["master-reference/content/atlas-core.json", {
      git_blob_oid: "3d2c841f8855596007e45a5e165e2f462a95e260",
      sha256: "3084a31bf02c6e44d41b189e7449e5a4265d18ed9c95765a1526d5d3b29ab6c0",
      bytes: 40793,
      rule_set_digest: "04ab89206d463fced49716ebef233b71f9e5f5e77e922f7b752dc6cb6c3a4f34",
      candidate_count: 155,
      candidate_digest: "11ed8db087e05999e6401b53d251421aec4777c42fa99cf2a617e7cad54d9ad1",
    }],
    ["master-reference/content/capability-catalog.json", {
      git_blob_oid: "bbd5fc3f6ff524299a580bce0925e27b85597f0f",
      sha256: "b62290c58b7427dd96a38206715bef4cd65a4847c7442112ddd678c573c8774e",
      bytes: 93635,
      rule_set_digest: "7a15fc6cbfdd0881845a399a4b1d3e014e3d991d38c2b0bc5542fd784b2472e6",
      candidate_count: 426,
      candidate_digest: "69c1b86c5ca41aca8b6f332e604448e024f3339a4f486b36a1ed4679025cd9ed",
    }],
    ["master-reference/content/delivery-governance.json", {
      git_blob_oid: "4db11fe882cc5c498c85e4b71c34979ae35e1b8b",
      sha256: "08d93874d6a611ee1661cc19705a9f0bb52a5b4240df7305d6ec7f6565afe787",
      bytes: 105687,
      rule_set_digest: "98bdb41437f666511812d40535906835082885e2b51b86f57bc4732865c9b622",
      candidate_count: 969,
      candidate_digest: "623c12f3371523a93aa326169a83ab9eb554a35d2cfcf31668f2618af4774f76",
    }],
    ["master-reference/content/open-horizon-register.json", {
      git_blob_oid: "ed375f35a60b7eb4cc5719223b5c349fd2bddba2",
      sha256: "428024fe0b19cc39a67d497e73f466dd1a3c7908c013a4bb0be11f4cd196116f",
      bytes: 44570,
      rule_set_digest: "e546770f88f1e941de2b2e98582c1aab90a0f0aaf5c581e593b6ef073905656b",
      candidate_count: 315,
      candidate_digest: "0629c2857218a5b6a63a4e6979644ebbbd55753ddba248bde293478f142b35af",
    }],
    ["master-reference/content/output-contract.json", {
      git_blob_oid: "e791ddf8e424de69e950b706fd18538cb90b4cd8",
      sha256: "2d5821c3597c911098bbbefd06f2d4edcd6c46a9707219ecbccf919670a3df7d",
      bytes: 32430,
      rule_set_digest: "8a87328023c97c137ca946d01a24d38c2230c22f1b48a51bd3ef1a7d2a49cc6f",
      candidate_count: 275,
      candidate_digest: "3a7fdc2ab75413ec3993a5287edacc97a2fdb7f14f33bd25f47b5575670068d1",
    }],
  ]);
  const rawSources = new Map();
  const contractRaw = await readFile(
    new URL(`../../../${CONSEQUENTIAL_CLAIM_CONTRACT_PATH}`, import.meta.url),
  );
  const contract = JSON.parse(contractRaw.toString("utf8"));
  assert.equal(
    sha256(contractRaw),
    "cf123369749c14ef140a9eb906b63f7183e93fd45a943a25087f5411a17399b6",
  );
  rawSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: contractRaw,
    gitBlobOid: gitBlobOid(contractRaw),
  });
  const contractByPath = new Map(contract.source_universe.map((row) => [row.path, row]));
  for (const path of CONSEQUENTIAL_CLAIM_PATHS) {
    const raw = await readFile(new URL(`../../../${path}`, import.meta.url));
    const oid = gitBlobOid(raw);
    assert.equal(contractByPath.get(path).git_blob_oid, oid);
    assert.deepEqual(
      { git_blob_oid: oid, sha256: sha256(raw), bytes: raw.byteLength },
      (({ git_blob_oid, sha256, bytes }) => ({ git_blob_oid, sha256, bytes }))(
        goldenReceipts.get(path),
      ),
    );
    rawSources.set(path, { raw, gitBlobOid: oid });
  }
  const sourceReceipts = CONSEQUENTIAL_CLAIM_PATHS.map((path) => ({
    path,
    git_blob_oid: goldenReceipts.get(path).git_blob_oid,
    sha256: goldenReceipts.get(path).sha256,
    bytes: goldenReceipts.get(path).bytes,
    classification: "candidate_census",
    rule_set_digest: goldenReceipts.get(path).rule_set_digest,
    candidate_count: goldenReceipts.get(path).candidate_count,
    candidate_digest: goldenReceipts.get(path).candidate_digest,
  }));
  const summary = {
    schema_version: "bounded-curated-consequential-claims/2",
    denominator_kind: "bounded_curated_content_claim_denominator",
    state: "declared_incomplete",
    closed: false,
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    source_basis: "selected_commit_raw_git_blobs",
    contract_path: CONSEQUENTIAL_CLAIM_CONTRACT_PATH,
    contract_git_blob_oid: gitBlobOid(contractRaw),
    contract_digest: sha256(contractRaw),
    classification_digest: "594013cefc9f293cb6b224e6f869014e6015dd6f23a4ff708899afbb44c1f19c",
    source_universe_expected: 5,
    source_universe_registered: 5,
    source_universe_unclassified: 0,
    source_receipts: sourceReceipts,
    source_receipts_digest: "aad6fbb1305ccaddea2b5257cbfa5704ba1548a1855c97bcbaa144ed6d8ecb30",
    expected_candidates: 2140,
    discovered_candidates: 2140,
    classified_candidates: 2140,
    independently_reviewed_candidates: 0,
    unresolved_candidates: 2140,
    candidate_set_digest: "ed4bb19838118841b5f5cc3a3d7348ee9763d11e8f4ad4f610c5e3853a1f0d31",
    compiler_integrity_claims_expected: 6,
    compiler_integrity_claims_classified: 6,
    compiler_integrity_claims_consequential: 0,
    error_codes: [
      "consequential_claim_independent_review_pending",
      "consequential_claim_rendered_sink_universe_incomplete",
    ],
  };
  const completeness = {
    source_commit: summary.source_commit,
    source_tree_digest: summary.source_tree_digest,
    semantic_accounting: {
      consequential_claim_denominator_state: "declared_incomplete",
    },
    consequential_claim_denominator: summary,
    acceptance_gates: [
      {
        name: "consequential_claim_denominator_closed",
        passed: false,
        expected: true,
        actual: false,
      },
    ],
  };
  const facetRecords = reconstructConsequentialClaimFacetRecords({
    completeness,
    rawSources,
    claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
  });
  return { completeness, contract, facetRecords, rawSources };
}

test("projection independently recomputes the bounded claim census and rejects self-receipted drift", async () => {
  assert.equal(isPythonStripEmpty("\u001c"), true);
  assert.equal(isPythonStripEmpty("\u3000"), true);
  assert.equal(isPythonStripEmpty("\u00a0\u2007\u202f"), true);
  assert.equal(isPythonStripEmpty("\ufeff"), false);
  assert.equal(isPythonStripEmpty("\u180e"), false);
  assert.equal(isPythonStripEmpty("\ud83d\ude80"), false);
  assert.equal(isPythonStripEmpty("not-blank"), false);
  const fixture = await trackedConsequentialClaimFixture();
  validateConsequentialClaimCensus({
    completeness: fixture.completeness,
    rawSources: fixture.rawSources,
    claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
    facetRecords: fixture.facetRecords,
  });

  const bomContractRaw = Buffer.concat([
    Buffer.from([0xEF, 0xBB, 0xBF]),
    fixture.rawSources.get(CONSEQUENTIAL_CLAIM_CONTRACT_PATH).raw,
  ]);
  const bomSources = new Map(fixture.rawSources);
  bomSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: bomContractRaw,
    gitBlobOid: gitBlobOid(bomContractRaw),
  });
  const bomCompleteness = structuredClone(fixture.completeness);
  Object.assign(bomCompleteness.consequential_claim_denominator, {
    contract_git_blob_oid: gitBlobOid(bomContractRaw),
    contract_digest: sha256(bomContractRaw),
  });
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: bomCompleteness,
      rawSources: bomSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const floatPath = "master-reference/content/atlas-core.json";
  const floatSourceText = fixture.rawSources.get(floatPath).raw.toString("utf8");
  assert.equal(floatSourceText.includes('"level": 0'), true);
  const floatRaw = Buffer.from(floatSourceText.replace('"level": 0', '"level": 0.0'), "utf8");
  const floatSources = new Map(fixture.rawSources);
  floatSources.set(floatPath, { raw: floatRaw, gitBlobOid: gitBlobOid(floatRaw) });
  const floatContract = structuredClone(fixture.contract);
  floatContract.source_universe.find((source) => source.path === floatPath).git_blob_oid =
    gitBlobOid(floatRaw);
  const floatContractRaw = Buffer.from(`${stableJson(floatContract)}\n`, "utf8");
  floatSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: floatContractRaw,
    gitBlobOid: gitBlobOid(floatContractRaw),
  });
  const floatCompleteness = structuredClone(fixture.completeness);
  Object.assign(floatCompleteness.consequential_claim_denominator, {
    contract_git_blob_oid: gitBlobOid(floatContractRaw),
    contract_digest: sha256(floatContractRaw),
    classification_digest: digestObject({
      source_universe: floatContract.source_universe,
      compiler_integrity_claims: floatContract.compiler_integrity_claims,
    }),
  });
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: floatCompleteness,
      rawSources: floatSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const mixedPath = CONSEQUENTIAL_CLAIM_PATHS[0];
  const mixedRaw = fixture.rawSources.get(mixedPath).raw;
  const mixedSources = new Map(fixture.rawSources);
  mixedSources.set(mixedPath, { raw: mixedRaw, gitBlobOid: gitBlobOid64(mixedRaw) });
  const mixedContract = structuredClone(fixture.contract);
  mixedContract.source_universe.find((source) => source.path === mixedPath).git_blob_oid =
    gitBlobOid64(mixedRaw);
  const mixedContractRaw = Buffer.from(`${stableJson(mixedContract)}\n`, "utf8");
  mixedSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: mixedContractRaw,
    gitBlobOid: gitBlobOid(mixedContractRaw),
  });
  const mixedCompleteness = structuredClone(fixture.completeness);
  Object.assign(mixedCompleteness.consequential_claim_denominator, {
    contract_git_blob_oid: gitBlobOid(mixedContractRaw),
    contract_digest: sha256(mixedContractRaw),
    classification_digest: digestObject({
      source_universe: mixedContract.source_universe,
      compiler_integrity_claims: mixedContract.compiler_integrity_claims,
    }),
  });
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: mixedCompleteness,
      rawSources: mixedSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const unavailable = {
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    semantic_accounting: { consequential_claim_denominator_state: "not_declared" },
    consequential_claim_denominator: unavailableConsequentialClaimSummary(
      "d".repeat(40),
      "e".repeat(64),
    ),
    acceptance_gates: [{
      name: "consequential_claim_denominator_closed",
      passed: false,
      expected: true,
      actual: false,
    }],
  };
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: unavailable,
      rawSources: new Map(),
      claimPredicates: ["repository.attacker_supplied"],
      facetRecords: [],
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );
  const unavailableMarker = "private-unavailable-reason";
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: unavailable,
      rawSources: new Map(),
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: [],
      unavailableReason: unavailableMarker,
    }),
    (error) => {
      assert.equal(error.message, "compiler consequential-claim census is inconsistent");
      assert.equal(String(error.stack).includes(unavailableMarker), false);
      return true;
    },
  );
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: null,
      rawSources: null,
      claimPredicates: null,
      facetRecords: null,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );
  const halfBound = structuredClone(unavailable);
  halfBound.consequential_claim_denominator.source_tree_digest = null;
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: halfBound,
      rawSources: new Map(),
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: [],
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const reorderedContract = structuredClone(fixture.contract);
  reorderedContract.source_universe.reverse();
  reorderedContract.compiler_integrity_claims.reverse();
  const reorderedRaw = Buffer.from(`${stableJson(reorderedContract)}\n`, "utf8");
  const reorderedSources = new Map(fixture.rawSources);
  reorderedSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: reorderedRaw,
    gitBlobOid: gitBlobOid(reorderedRaw),
  });
  const reorderedCompleteness = structuredClone(fixture.completeness);
  Object.assign(reorderedCompleteness.consequential_claim_denominator, {
    contract_git_blob_oid: gitBlobOid(reorderedRaw),
    contract_digest: sha256(reorderedRaw),
    classification_digest: digestObject({
      source_universe: reorderedContract.source_universe,
      compiler_integrity_claims: reorderedContract.compiler_integrity_claims,
    }),
  });
  validateConsequentialClaimCensus({
    completeness: reorderedCompleteness,
    rawSources: reorderedSources,
    claimPredicates: [...CONSEQUENTIAL_INTEGRITY_PREDICATES].reverse(),
    facetRecords: fixture.facetRecords,
  });

  const tamperedSummary = structuredClone(fixture.completeness);
  tamperedSummary.consequential_claim_denominator.candidate_set_digest = "0".repeat(64);
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: tamperedSummary,
      rawSources: fixture.rawSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const receiptMismatch = structuredClone(fixture.completeness);
  receiptMismatch.consequential_claim_denominator.source_receipts[0].rule_set_digest =
    "1".repeat(64);
  receiptMismatch.consequential_claim_denominator.source_receipts_digest = digestObject(
    receiptMismatch.consequential_claim_denominator.source_receipts,
  );
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: receiptMismatch,
      rawSources: fixture.rawSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const swappedReceipts = structuredClone(fixture.completeness);
  const firstDigest = swappedReceipts.consequential_claim_denominator.source_receipts[0].candidate_digest;
  swappedReceipts.consequential_claim_denominator.source_receipts[0].candidate_digest =
    swappedReceipts.consequential_claim_denominator.source_receipts[1].candidate_digest;
  swappedReceipts.consequential_claim_denominator.source_receipts[1].candidate_digest = firstDigest;
  swappedReceipts.consequential_claim_denominator.source_receipts_digest = digestObject(
    swappedReceipts.consequential_claim_denominator.source_receipts,
  );
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: swappedReceipts,
      rawSources: fixture.rawSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const downgraded = structuredClone(fixture.completeness);
  downgraded.semantic_accounting.consequential_claim_denominator_state = "not_declared";
  downgraded.consequential_claim_denominator = unavailableConsequentialClaimSummary(
    downgraded.source_commit,
    downgraded.source_tree_digest,
  );
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: downgraded,
      rawSources: fixture.rawSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    /^Error: compiler consequential-claim census is inconsistent$/,
  );

  const contractMutations = {
    "v1 downgrade": (contract) => {
      contract.schema_version = "bounded-curated-consequential-claims/1";
    },
    "selector drift": (contract) => {
      contract.source_universe[0].object_rules[0].selector.push("attacker[]");
    },
    "field type drift": (contract) => {
      const field = contract.source_universe[0].object_rules[0].fields[0];
      field.value_type = field.value_type === "any" ? "string" : "any";
    },
    "generic candidate collection": (contract) => {
      const field = contract.source_universe
        .flatMap((source) => source.object_rules)
        .flatMap((rule) => rule.fields)
        .find((item) => item.classification === "candidate");
      field.value_type = "array";
    },
    "identity drift": (contract) => {
      const rule = contract.source_universe
        .flatMap((source) => source.object_rules)
        .find((item) => item.identity.kind !== "root");
      rule.identity = { kind: "root" };
    },
    "grounding drift": (contract) => {
      contract.source_universe[0].grounding.fallback_owner_ref = "owner.projection-attacker";
    },
    "source count drift": (contract) => {
      contract.source_universe[0].expected_candidates += 1;
    },
    "equal-count field-class swap": (contract) => {
      const rule = contract.source_universe
        .flatMap((source) => source.object_rules)
        .find((item) =>
          item.fields.some((field) => field.classification === "candidate") &&
          item.fields.some((field) => field.classification !== "candidate"));
      const candidate = rule.fields.find((field) => field.classification === "candidate");
      const excluded = rule.fields.find((field) => field.classification !== "candidate");
      const claimKind = candidate.claim_kind;
      candidate.classification = excluded.classification;
      candidate.claim_kind = null;
      excluded.classification = "candidate";
      excluded.claim_kind = claimKind;
    },
  };
  for (const [label, mutate] of Object.entries(contractMutations)) {
    const changed = structuredClone(fixture.contract);
    mutate(changed);
    const raw = Buffer.from(`${stableJson(changed)}\n`, "utf8");
    const sources = new Map(fixture.rawSources);
    sources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, { raw, gitBlobOid: gitBlobOid(raw) });
    const completeness = structuredClone(fixture.completeness);
    Object.assign(completeness.consequential_claim_denominator, {
      contract_git_blob_oid: gitBlobOid(raw),
      contract_digest: sha256(raw),
      classification_digest: digestObject({
        source_universe: changed.source_universe,
        compiler_integrity_claims: changed.compiler_integrity_claims,
      }),
    });
    assert.throws(
      () => validateConsequentialClaimCensus({
        completeness,
        rawSources: sources,
        claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
        facetRecords: fixture.facetRecords,
      }),
      /^Error: compiler consequential-claim census is inconsistent$/,
      label,
    );
  }

  const sourceMutations = {
    "candidate field type": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.domains[0].entries[0].current_scope = true;
      return [path, value];
    },
    "record identity": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      const entries = value.domains.flatMap((domain) => domain.entries);
      entries[1].id = entries[0].id;
      return [path, value];
    },
    "inflated owner registry": (sources) => {
      const path = "master-reference/content/atlas-core.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      const template = value.owners[0];
      value.owners.push(...Array.from({ length: 5_000 }, (_item, index) => ({
        ...structuredClone(template),
        id: `owner.load-probe.${index}`,
      })));
      return [path, value];
    },
    "orphan grounding": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      const entry = value.domains.flatMap((domain) => domain.entries)
        .find((item) => Array.isArray(item.owner_refs) && item.owner_refs.length > 0);
      entry.owner_refs = ["owner.projection-attacker"];
      return [path, value];
    },
    "gap on exempt state": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      const delivery = JSON.parse(
        sources.get("master-reference/content/delivery-governance.json").raw.toString("utf8"),
      );
      const entry = value.domains.flatMap((domain) => domain.entries)
        .find((item) => item.state === "current" && item.owner_refs.length > 0);
      entry.gap_refs = [delivery.gaps[0].id];
      return [path, value];
    },
    "candidate value swap": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      const entry = value.domains[0].entries[0];
      [entry.state, entry.current_scope] = [entry.current_scope, entry.state];
      return [path, value];
    },
    "decoded C0 control": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.domains[0].entries[0].current_scope = "private\u0000candidate";
      return [path, value];
    },
    "decoded C1 control": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.domains[0].entries[0].current_scope = "private\u0085candidate";
      return [path, value];
    },
    "decoded unpaired surrogate": (sources) => {
      const path = "master-reference/content/capability-catalog.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.domains[0].entries[0].current_scope = "private\ud800candidate";
      return [path, value];
    },
    "rule-set uniqueness": (sources) => {
      const path = "master-reference/content/atlas-core.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.controlled_states[1].value = value.controlled_states[0].value;
      return [path, value];
    },
    "known horizon signal without source refs": (sources) => {
      const path = "master-reference/content/open-horizon-register.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.signals.find((signal) => signal.id !== "horizon.unknown").source_refs = [];
      return [path, value];
    },
    "unknown horizon signal with source refs": (sources) => {
      const path = "master-reference/content/open-horizon-register.json";
      const value = JSON.parse(sources.get(path).raw.toString("utf8"));
      value.signals.find((signal) => signal.id === "horizon.unknown").source_refs = [
        value.watch_families[0].id,
      ];
      return [path, value];
    },
  };
  for (const [label, mutate] of Object.entries(sourceMutations)) {
    const sources = new Map(fixture.rawSources);
    const [path, value] = mutate(sources);
    const raw = Buffer.from(`${stableJson(value)}\n`, "utf8");
    sources.set(path, { raw, gitBlobOid: gitBlobOid(raw) });
    const contract = structuredClone(fixture.contract);
    contract.source_universe.find((source) => source.path === path).git_blob_oid = gitBlobOid(raw);
    const contractRaw = Buffer.from(`${stableJson(contract)}\n`, "utf8");
    sources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
      raw: contractRaw,
      gitBlobOid: gitBlobOid(contractRaw),
    });
    const completeness = structuredClone(fixture.completeness);
    Object.assign(completeness.consequential_claim_denominator, {
      contract_git_blob_oid: gitBlobOid(contractRaw),
      contract_digest: sha256(contractRaw),
      classification_digest: digestObject({
        source_universe: contract.source_universe,
        compiler_integrity_claims: contract.compiler_integrity_claims,
      }),
    });
    assert.throws(
      () => validateConsequentialClaimCensus({
        completeness,
        rawSources: sources,
        claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
        facetRecords: fixture.facetRecords,
      }),
      /^Error: compiler consequential-claim census is inconsistent$/,
      label,
    );
  }

  const marker = "private-census-marker";
  const hostileContract = structuredClone(fixture.contract);
  hostileContract.source_universe[0].object_rules[0].fields[0].unexpected = marker;
  const hostileRaw = Buffer.from(`${stableJson(hostileContract)}\n`, "utf8");
  const hostileSources = new Map(fixture.rawSources);
  hostileSources.set(CONSEQUENTIAL_CLAIM_CONTRACT_PATH, {
    raw: hostileRaw,
    gitBlobOid: gitBlobOid(hostileRaw),
  });
  const hostileCompleteness = structuredClone(fixture.completeness);
  Object.assign(hostileCompleteness.consequential_claim_denominator, {
    contract_git_blob_oid: gitBlobOid(hostileRaw),
    contract_digest: sha256(hostileRaw),
    classification_digest: digestObject({
      source_universe: hostileContract.source_universe,
      compiler_integrity_claims: hostileContract.compiler_integrity_claims,
    }),
  });
  assert.throws(
    () => validateConsequentialClaimCensus({
      completeness: hostileCompleteness,
      rawSources: hostileSources,
      claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
      facetRecords: fixture.facetRecords,
    }),
    (error) => {
      assert.equal(error.message, "compiler consequential-claim census is inconsistent");
      assert.equal(String(error.stack).includes(marker), false);
      return true;
    },
  );
});

test("projection binds every consequential-claim facet subject without accepting review promotion", async () => {
  const fixture = await trackedConsequentialClaimFixture();
  assert.equal(fixture.facetRecords.length, 2_140);
  assert.equal(
    digestObject(fixture.facetRecords.map(
      ({ id: _id, entity_type: _entityType, evidence_state: _evidenceState, ...subject }) => subject,
    ).sort((left, right) => left.facet_id.localeCompare(right.facet_id))),
    fixture.completeness.consequential_claim_denominator.candidate_set_digest,
  );
  assert.ok(fixture.facetRecords.every((record) => (
    record.id === stableId("claim-facet-record", record.facet_id) &&
    record.entity_type === "consequential_claim_facet" &&
    record.evidence_state === "payload_omitted_value_fingerprint_index_only" &&
    record.review_state === "pending_independent_review" &&
    !Object.hasOwn(record, "value")
  )));

  const rejectMutation = (label, mutate, { preserveOrder = false } = {}) => {
    const facetRecords = structuredClone(fixture.facetRecords);
    mutate(facetRecords);
    if (!preserveOrder) facetRecords.sort((left, right) => left.id.localeCompare(right.id));
    assert.throws(
      () => validateConsequentialClaimCensus({
        completeness: fixture.completeness,
        rawSources: fixture.rawSources,
        claimPredicates: CONSEQUENTIAL_INTEGRITY_PREDICATES,
        facetRecords,
      }),
      /^Error: compiler consequential-claim census is inconsistent$/,
      label,
    );
  };
  rejectMutation("missing", (records) => records.pop());
  rejectMutation("duplicate", (records) => records.push(structuredClone(records[0])));
  rejectMutation("substitution", (records) => {
    records[0].facet_id = `urn:atlas:claim-facet:${"0".repeat(64)}`;
    records[0].id = stableId("claim-facet-record", records[0].facet_id);
  });
  rejectMutation("reorder", (records) => records.reverse(), { preserveOrder: true });
  rejectMutation("value digest", (records) => {
    records[0].value_digest = "0".repeat(64);
  });
  rejectMutation("review state", (records) => {
    records[0].review_state = "independently_reviewed";
  });
  rejectMutation("evidence state", (records) => {
    records[0].evidence_state = "authenticated_review_evidence";
  });
});

test("projection refuses consequential-claim facet subjects as claim evidence", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-claim-evidence-separation-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const facetId = `urn:atlas:claim-facet:${"a".repeat(64)}`;
    const facetRecord = {
      id: stableId("claim-facet-record", facetId),
      entity_type: "consequential_claim_facet",
      evidence_state: "payload_omitted_value_fingerprint_index_only",
      facet_id: facetId,
      source_path: "master-reference/content/atlas-core.json",
      source_blob_oid: "a".repeat(40),
      source_pointer: "/owners/0/current_scope",
      rule_id: "fixture_claim_field",
      record_kind: "owners",
      record_identity: "owner.fixture",
      facet_path: "current_scope",
      classification: "consequential_claim_candidate",
      claim_kind: "catalog_assertion",
      review_state: "pending_independent_review",
      grounding_digest: "b".repeat(64),
      value_digest: "c".repeat(64),
    };
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    const recordsDigest = digestObject([facetRecord.id]);
    const facetEnvelope = {
      schema_version: "1.2.0",
      record_type: "consequential_claim_facets",
      source_commit: manifest.source_commit,
      source_tree_digest: manifest.source_tree_digest,
      chunk_index: 0,
      chunk_count: 1,
      record_count: 1,
      records_digest: recordsDigest,
      records: [facetRecord],
    };
    const facetChunk = await writeDescriptor(
      input,
      "chunks/consequential_claim_facets/00000.json",
      facetEnvelope,
    );
    manifest.groups.consequential_claim_facets = {
      record_count: 1,
      chunk_count: 1,
      records_digest: recordsDigest,
      chunks: [{ ...facetChunk, record_count: 1 }],
    };
    const completeness = JSON.parse(
      await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
    );
    completeness.record_counts.consequential_claim_facets = 1;
    manifest.completeness = await writeVerifiedValue(input, manifest.completeness, completeness);
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
    await mutateCompilerGroup(input, "claims", (claimEnvelope) => {
      claimEnvelope.records[0].evidence_ids = [facetRecord.id];
    });

    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /^Error: compiler claim evidence references a consequential-claim facet subject$/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection removes staging when the bounded claim ledger is rechained", async (context) => {
  const mutations = {
    "absent-summary denominator": {
      mutate: (completeness) => {
        completeness.consequential_claim_denominator.expected_candidates = 1;
      },
    },
    "global gate": {
      mutate: (completeness) => {
        const gate = completeness.acceptance_gates.find(
          (item) => item.name === "consequential_claim_denominator_closed",
        );
        gate.expected = false;
      },
    },
    "float-typed candidate count": {
      mutate: () => {},
      rewrite: (text) => text.replace('"expected_candidates":0,', '"expected_candidates":0.0,'),
    },
  };
  for (const [label, { mutate, rewrite }] of Object.entries(mutations)) {
    await context.test(label, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-claim-rechain-"));
      try {
        const unrelated = join(scratch, `.projection.staging-${process.pid}`);
        await mkdir(unrelated);
        await writeFile(join(unrelated, "sentinel.txt"), "unrelated\n", "utf8");
        const { input } = await makeCompilerFixture(scratch);
        const manifestPath = join(input, "manifest.json");
        const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
        const completeness = JSON.parse(
          await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
        );
        mutate(completeness);
        if (rewrite) {
          const canonical = `${stableJson(completeness)}\n`;
          const rewritten = rewrite(canonical);
          assert.notEqual(rewritten, canonical);
          const bytes = Buffer.from(rewritten, "utf8");
          await writeFile(join(input, ...manifest.completeness.path.split("/")), bytes);
          manifest.completeness = {
            ...manifest.completeness,
            bytes: bytes.byteLength,
            sha256: sha256(bytes),
          };
        } else {
          manifest.completeness = await writeVerifiedValue(
            input,
            manifest.completeness,
            completeness,
          );
        }
        await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
        const output = join(scratch, "projection");
        await assert.rejects(
          buildProjection({ input, output }),
          /^Error: compiler consequential-claim census is inconsistent$/,
        );
        await assert.rejects(readFile(join(output, "projection-manifest.json")));
        assert.equal(await readFile(join(unrelated, "sentinel.txt"), "utf8"), "unrelated\n");
        assert.deepEqual(
          (await readdir(scratch)).filter((name) =>
            name.startsWith(`.projection.staging-${process.pid}-`)),
          [],
        );
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("symbol metadata routes reject self-receipted binding, count, order, digest, and reachability drift", () => {
  const ids = ["alpha", "beta", "gamma"].map((value) => stableId("symbol", value)).sort();
  const moduleRecordIds = [ids.slice(0, 2), ids.slice(2)];
  const metadataEntries = moduleRecordIds.map((moduleIds, moduleOrdinal) => ({
    group: "symbols",
    module: `metadata/symbols/${String(moduleOrdinal).padStart(5, "0")}-${String(moduleOrdinal).repeat(16)}.mjs`,
    recordCount: moduleIds.length,
    bytes: 100 + moduleOrdinal,
    sha256: String(moduleOrdinal).repeat(64),
  }));
  const makeEntries = (recordIds = moduleRecordIds) => recordIds.map((moduleIds, moduleOrdinal) => ({
    moduleOrdinal,
    module: metadataEntries[moduleOrdinal].module,
    bytes: metadataEntries[moduleOrdinal].bytes,
    sha256: metadataEntries[moduleOrdinal].sha256,
    lowerId: moduleIds[0],
    upperId: moduleIds.at(-1),
    recordCount: moduleIds.length,
  }));
  const makeRoute = (entries = makeEntries()) => ({
    kind: "metadata_module_upper_bound_route_v1",
    group: "symbols",
    moduleCount: entries.length,
    recordCount: ids.length,
    orderedIdsDigest: digestObject(ids),
    entriesDigest: digestObject(entries),
    upperBoundsDigest: digestObject(entries.map((entry) => entry.upperId)),
    entries,
  });
  const expected = { recordCount: ids.length, recordsDigest: digestObject(ids) };
  const rejection = /^Error: symbol metadata route is absent or inconsistent$/;

  assert.doesNotThrow(() =>
    validateSymbolMetadataRoute(makeRoute(), metadataEntries, moduleRecordIds, expected));

  const ordinalDrift = makeRoute();
  ordinalDrift.entries[0].moduleOrdinal = 1;
  ordinalDrift.entriesDigest = digestObject(ordinalDrift.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(ordinalDrift, metadataEntries, moduleRecordIds, expected),
    rejection,
  );

  const pathDrift = makeRoute();
  pathDrift.entries[0].module = "metadata/symbols/00000-receipted-drift.mjs";
  pathDrift.entriesDigest = digestObject(pathDrift.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(pathDrift, metadataEntries, moduleRecordIds, expected),
    rejection,
  );

  const bytesDrift = makeRoute();
  bytesDrift.entries[0].bytes += 1;
  bytesDrift.entriesDigest = digestObject(bytesDrift.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(bytesDrift, metadataEntries, moduleRecordIds, expected),
    rejection,
  );

  const moduleDigestDrift = makeRoute();
  moduleDigestDrift.entries[0].sha256 = "e".repeat(64);
  moduleDigestDrift.entriesDigest = digestObject(moduleDigestDrift.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(
      moduleDigestDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const countDrift = makeRoute();
  countDrift.entries[0].recordCount += 1;
  countDrift.entriesDigest = digestObject(countDrift.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(countDrift, metadataEntries, moduleRecordIds, expected),
    rejection,
  );

  const denominatorDrift = makeRoute();
  denominatorDrift.recordCount += 1;
  assert.throws(
    () => validateSymbolMetadataRoute(
      denominatorDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const moduleDenominatorDrift = makeRoute();
  moduleDenominatorDrift.moduleCount += 1;
  assert.throws(
    () => validateSymbolMetadataRoute(
      moduleDenominatorDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const reorderedIds = [[moduleRecordIds[0][1], moduleRecordIds[0][0]], moduleRecordIds[1]];
  const orderDrift = makeRoute(makeEntries(reorderedIds));
  assert.throws(
    () => validateSymbolMetadataRoute(orderDrift, metadataEntries, reorderedIds, expected),
    rejection,
  );

  const entriesDigestDrift = makeRoute();
  entriesDigestDrift.entriesDigest = "d".repeat(64);
  assert.throws(
    () => validateSymbolMetadataRoute(
      entriesDigestDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const upperBoundsDigestDrift = makeRoute();
  upperBoundsDigestDrift.upperBoundsDigest = "c".repeat(64);
  assert.throws(
    () => validateSymbolMetadataRoute(
      upperBoundsDigestDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const digestDrift = makeRoute();
  digestDrift.orderedIdsDigest = "f".repeat(64);
  assert.throws(
    () => validateSymbolMetadataRoute(digestDrift, metadataEntries, moduleRecordIds, expected),
    rejection,
  );

  const duplicateBoundDrift = makeRoute();
  duplicateBoundDrift.entries[0].upperId = duplicateBoundDrift.entries[1].upperId;
  duplicateBoundDrift.entriesDigest = digestObject(duplicateBoundDrift.entries);
  duplicateBoundDrift.upperBoundsDigest = digestObject(
    duplicateBoundDrift.entries.map((entry) => entry.upperId),
  );
  assert.throws(
    () => validateSymbolMetadataRoute(
      duplicateBoundDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const nonmonotoneBoundDrift = makeRoute();
  nonmonotoneBoundDrift.entries[0].upperId = `urn:atlas:symbol:${"f".repeat(24)}`;
  nonmonotoneBoundDrift.entriesDigest = digestObject(nonmonotoneBoundDrift.entries);
  nonmonotoneBoundDrift.upperBoundsDigest = digestObject(
    nonmonotoneBoundDrift.entries.map((entry) => entry.upperId),
  );
  assert.throws(
    () => validateSymbolMetadataRoute(
      nonmonotoneBoundDrift,
      metadataEntries,
      moduleRecordIds,
      expected,
    ),
    rejection,
  );

  const malformed = makeRoute();
  malformed.entries[0].unreceipted = true;
  malformed.entriesDigest = digestObject(malformed.entries);
  assert.throws(
    () => validateSymbolMetadataRoute(malformed, metadataEntries, moduleRecordIds, expected),
    rejection,
  );
});

test("projection is deterministic, lazy, privacy-gated, and exact-source preserving", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-test-"));
  try {
    const { input, exact, secondExact, records } = await makeCompilerFixture(scratch);
    const outputA = join(scratch, "projection-a");
    const outputB = join(scratch, "projection-b");
    const manifestA = await buildProjection({ input, output: outputA });
    const manifestB = await buildProjection({ input, output: outputB });
    assert.equal(
      await readFile(join(outputA, ".atlas-projection-generated"), "utf8"),
      "atlas-projection-v1.2\n",
    );

    const indexA = await readFile(join(outputA, "index.mjs"), "utf8");
    const indexB = await readFile(join(outputB, "index.mjs"), "utf8");
    const identityA = await readFile(join(outputA, "identity.mjs"), "utf8");
    const identityB = await readFile(join(outputB, "identity.mjs"), "utf8");
    const sourceIndexPathA = join(outputA, ...manifestA.sourceIndex.module.split("/"));
    const sourceIndexPathB = join(outputB, ...manifestB.sourceIndex.module.split("/"));
    const sourceIndexA = await readFile(sourceIndexPathA, "utf8");
    const sourceIndexB = await readFile(sourceIndexPathB, "utf8");
    assert.equal(indexA, indexB, "same compiler corpus must produce byte-identical index modules");
    assert.equal(identityA, identityB, "same compiler corpus must produce byte-identical identity modules");
    assert.equal(
      sourceIndexA,
      sourceIndexB,
      "same compiler corpus must produce byte-identical source indexes",
    );
    assert.equal(manifestA.index.sha256, manifestB.index.sha256);
    assert.equal(manifestA.identity.sha256, manifestB.identity.sha256);
    assert.equal(manifestA.sourceIndex.sha256, sha256(Buffer.from(sourceIndexA, "utf8")));
    const tamperedSourceIndex = sourceIndexB.replace(
      "const sourceChunkLoaders = Object.freeze([\n",
      "const sourceChunkLoaders = Object.freeze([\nObject.freeze([]),",
    );
    assert.notEqual(tamperedSourceIndex, sourceIndexB);
    await writeFile(sourceIndexPathB, tamperedSourceIndex, "utf8");
    await assert.rejects(
      import(`${pathToFileURL(sourceIndexPathB).href}?route-drift=1`),
      /source chunk loader route is absent or inconsistent/,
    );
    assert.equal(manifestA.identity.bytes, Buffer.byteLength(identityA));
    assert.ok(
      manifestA.identity.bytes <= manifestA.budgets.identityModuleMaxBytes,
      "the landing identity receipt must remain independently bounded",
    );
    assert.equal(indexA.includes('return "Atlas"'), false, "source text must not enter metadata index");
    assert.equal(indexA.includes("repository.source_commit"), false, "claim records must remain lazy");
    assert.equal(indexA.includes("actions/upload-artifact@v4"), false, "workflow entities must remain lazy");
    assert.equal(indexA.includes("pytest==9.1.1"), false, "dependency records must remain lazy");
    assert.equal(
      indexA.includes("./records/symbol/"),
      false,
      "symbol dossiers must route to the canonical metadata store instead of a duplicate module family",
    );
    assert.equal(manifestA.sourceFileCount, 2, "metadata-only file must have no source descriptor");
    assert.ok(manifestA.sourceModules.length > 1, "dense source must be split into multiple bounded chunks");
    const expectedMetadataCounts = Object.fromEntries(
      Object.entries(records)
        .filter(([group]) => !["lines", "source_text"].includes(group))
        .map(([group, values]) => [group, values.length])
        .sort(([left], [right]) => left.localeCompare(right)),
    );
    assert.deepEqual(manifestA.groupCounts, expectedMetadataCounts);
    assert.match(manifestA.sourceModules[0].module, new RegExp(manifestA.sourceModules[0].sha256.slice(0, 24)));
    assert.ok(
      manifestA.metadataModules.every((entry) => /-[0-9a-f]{16}\.mjs$/.test(entry.module)),
      "every lazy metadata module URL must carry a content digest",
    );
    assert.ok(
      Object.values(manifestA.recordBuckets).flat().every((entry) => /-[0-9a-f]{16}\.mjs$/.test(entry.module)),
      "every dossier bucket URL must carry a content digest",
    );
    assert.ok(
      manifestA.metadataModules.every((entry) => entry.bytes <= manifestA.budgets.metadataModuleMaxBytes),
      "every metadata module must obey the recursive raw-byte ceiling",
    );
    assert.ok(
      Object.values(manifestA.recordBuckets).flat().every((entry) => entry.bytes <= manifestA.budgets.dossierModuleMaxBytes),
      "every dossier module must obey the recursive raw-byte ceiling",
    );
    assert.ok(
      manifestA.recordFragments.every((entry) => entry.bytes <= manifestA.budgets.recordFragmentModuleMaxBytes),
      "every lossless record fragment must obey the raw-byte ceiling",
    );
    assert.equal(Object.hasOwn(manifestA.recordBuckets, "symbol"), false);
    assert.equal(Object.hasOwn(manifestA.recordBucketSplitPrefixes, "symbol"), false);
    await assert.rejects(readdir(join(outputA, "records", "symbol")), /ENOENT/);
    assert.deepEqual(manifestA.recordRoutes, manifestB.recordRoutes);
    const symbolMetadataEntries = manifestA.metadataModules.filter((entry) => entry.group === "symbols");
    const symbolRoute = manifestA.recordRoutes.symbol;
    assert.equal(symbolRoute.group, "symbols");
    assert.equal(symbolRoute.kind, "metadata_module_upper_bound_route_v1");
    assert.equal(symbolRoute.moduleCount, symbolMetadataEntries.length);
    assert.equal(symbolRoute.recordCount, records.symbols.length);
    assert.equal(symbolRoute.orderedIdsDigest, digestObject(records.symbols.map((record) => record.id)));
    assert.equal(symbolRoute.entriesDigest, digestObject(symbolRoute.entries));
    assert.equal(
      symbolRoute.upperBoundsDigest,
      digestObject(symbolRoute.entries.map((entry) => entry.upperId)),
    );
    assert.deepEqual(
      symbolRoute.entries.map((entry) => ({
        module: entry.module,
        bytes: entry.bytes,
        sha256: entry.sha256,
      })),
      symbolMetadataEntries.map((entry) => ({
        module: entry.module,
        bytes: entry.bytes,
        sha256: entry.sha256,
      })),
      "every compact route ordinal must bind the exact metadata module path, byte count, and digest",
    );

    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?test=1`);
    const loadedIdentity = await import(`${pathToFileURL(join(outputA, "identity.mjs")).href}?test=1`);
    assert.equal(loadedIdentity.identity.sourceCommit, loaded.projection.sourceCommit);
    assert.equal(loadedIdentity.identity.sourceTreeDigest, loaded.projection.sourceTreeDigest);
    assert.deepEqual(
      loadedIdentity.identity.failedAcceptanceGates,
      loaded.projection.completeness.acceptance_gates
        .filter((gate) => !gate.passed)
        .map((gate) => ({ name: gate.name })),
    );
    assert.deepEqual(loaded.projection.groupCounts, expectedMetadataCounts);
    assert.deepEqual(Object.keys(loaded.metadataLoaders).sort(), Object.keys(expectedMetadataCounts));
    for (const [group, expected] of Object.entries(expectedMetadataCounts)) {
      assert.equal((await loaded.loadMetadata(group)).length, expected, `${group} projection denominator drifted`);
    }
    const source = await loaded.loadSource("app/example.py");
    const secondSource = await loaded.loadSource("0-second.txt");
    assert.equal(
      source.chunkCount + secondSource.chunkCount,
      manifestA.sourceModules.length,
    );
    const chunks = await Promise.all(source.chunks.map((chunk) => loaded.loadSourceChunk(source.path, chunk.chunkIndex)));
    assert.equal(await loaded.loadSourceChunk("missing.py", 0), null);
    assert.equal(await loaded.loadSourceChunk(source.path, -1), null);
    assert.equal(await loaded.loadSourceChunk(source.path, 0.5), null);
    for (const inheritedKey of ["toString", "constructor", "__proto__", "valueOf"]) {
      assert.equal(await loaded.loadSource(inheritedKey), null);
      assert.equal(await loaded.loadSourceChunk(inheritedKey, 0), null);
      assert.equal(await loaded.loadSourceWindow(inheritedKey, 1), null);
    }
    const segments = chunks.flatMap((chunk) => chunk.segments);
    assert.equal(segments.map((line) => `${line.text}${line.terminator}`).join(""), exact.toString("utf8"));
    const secondChunks = await Promise.all(secondSource.chunks.map(
      (chunk) => loaded.loadSourceChunk(secondSource.path, chunk.chunkIndex),
    ));
    assert.equal(
      secondChunks.flatMap((chunk) => chunk.segments)
        .map((line) => `${line.text}${line.terminator}`).join(""),
      secondExact.toString("utf8"),
    );
    assert.equal(segments[0].containingSymbolId, fixtureStableId("urn:atlas:symbol:hello"));
    assert.equal(segments[0].structuralMappingBasis, "symbol_range");
    assert.equal(segments[0].explanationDepth, 3);
    assert.equal(segments[0].runtimeTraceState, "synthetic_trace");
    assert.equal(segments[0].testCoverageState, "direct_line_coverage");
    assert.deepEqual(segments[0].testsCoveringIt, [fixtureStableId("urn:atlas:test:hello")]);
    assert.deepEqual(segments[0].securityAndPrivacyEffect, { semantic_effect: "none", source_exposure: "full" });
    const lineWindow = await loaded.loadSourceWindow("app/example.py", 2);
    assert.ok(lineWindow.segments.some((line) => line.number === 2));
    const secondWindow = await loaded.loadSourceWindow("0-second.txt", 1);
    assert.ok(secondWindow.segments.some((line) => line.number === 1));
    const symbol = await loaded.loadRecord("symbol", fixtureStableId("urn:atlas:symbol:hello"));
    assert.equal(symbol.purpose, "Return the Atlas greeting.");
    assert.equal(symbol.explanationDepth, 4);
    assert.equal(await loaded.loadRecord("symbol", stableId("symbol", "unknown")), null);
    assert.equal(await loaded.loadRecord("symbol", fixtureStableId("urn:atlas:test:hello")), null);
    assert.equal(await loaded.loadRecord("symbol", "not-a-stable-id"), null);
    const testCase = await loaded.loadRecord("test", fixtureStableId("urn:atlas:test:hello"));
    assert.equal(testCase.entityType, "test_case");
    assert.equal(testCase.assertionGroupId, fixtureStableId("urn:atlas:test:hello:assertions"));
    assert.equal(testCase.assertionCount, 1);
    const assertionGroup = await loaded.loadRecord("test", fixtureStableId("urn:atlas:test:hello:assertions"));
    assert.equal(assertionGroup.entityType, "test_assertion_group");
    assert.equal(assertionGroup.assertions[0].kind, "assert_statement");
    const workflow = await loaded.loadRecord("workflow", fixtureStableId("urn:atlas:workflow:ci"));
    assert.deepEqual(workflow.jobIds, [fixtureStableId("urn:atlas:workflow:ci:job")]);
    assert.deepEqual(workflow.stepIds, [fixtureStableId("urn:atlas:workflow:ci:step")]);
    assert.deepEqual(workflow.permissionIds, [fixtureStableId("urn:atlas:workflow:ci:permission")]);
    assert.deepEqual(workflow.artifactIds, [fixtureStableId("urn:atlas:workflow:ci:artifact")]);
    const workflowJob = await loaded.loadRecord("workflow", fixtureStableId("urn:atlas:workflow:ci:job"));
    assert.deepEqual(workflowJob.steps, [fixtureStableId("urn:atlas:workflow:ci:step")]);
    assert.deepEqual(workflowJob.permissions, [fixtureStableId("urn:atlas:workflow:ci:permission")]);
    assert.deepEqual(workflowJob.artifacts, [fixtureStableId("urn:atlas:workflow:ci:artifact")]);
    const workflowStep = await loaded.loadRecord("workflow", fixtureStableId("urn:atlas:workflow:ci:step"));
    assert.equal(workflowStep.uses, "actions/upload-artifact@v4");
    assert.equal(workflowStep.runDeclared, false);
    const workflowPermission = await loaded.loadRecord("workflow", fixtureStableId("urn:atlas:workflow:ci:permission"));
    assert.equal(workflowPermission.scope, "job:verify");
    assert.equal(workflowPermission.access, "read");
    const workflowArtifact = await loaded.loadRecord("workflow", fixtureStableId("urn:atlas:workflow:ci:artifact"));
    assert.equal(workflowArtifact.direction, "produced");
    assert.equal(workflowArtifact.declaredPath, "proof.json");
    const claim = await loaded.loadRecord("claim", fixtureStableId("urn:atlas:claim:greeting"));
    assert.equal(claim.predicate, "repository.source_commit");
    assert.equal(claim.verdict, "proven");
    assert.deepEqual(claim.denominator, { basis: "compiler_source_snapshot", status: "known", unit: "git_tracked_tree", value: 1 });
    assert.deepEqual(claim.evidenceIds, [fixtureStableId("urn:atlas:completeness:fixture")]);
    const component = await loaded.loadRecord("data", fixtureStableId("urn:atlas:component:greeting"));
    assert.equal(component.entityType, "jsx_component_symbol");
    assert.deepEqual(
      component.gui_dossier,
      records.components[0].gui_dossier,
      "projection must preserve the compiler GUI dossier and every field citation verbatim",
    );
    const route = await loaded.loadRecord("data", fixtureStableId("urn:atlas:route:greeting"));
    assert.equal(route.route, "/greeting");
    assert.deepEqual(route.gui_dossier, records.routes[0].gui_dossier);
    assert.equal(
      manifestA.recordBuckets.data.reduce((total, entry) => total + entry.recordCount, 0),
      records.datasets.length + records.routes.length + records.components.length,
      "the data dossier denominator must include datasets, routes, and components",
    );
    const dossiersByKind = {
      symbol: records.symbols,
      data: [...records.datasets, ...records.routes, ...records.components],
      test: records.tests,
      workflow: records.workflows,
      claim: records.claims,
    };
    for (const [kind, dossierRecords] of Object.entries(dossiersByKind)) {
      for (const record of dossierRecords) {
        assert.equal(
          (await loaded.loadRecord(kind, record.id))?.id,
          record.id,
          `${kind}:${record.id} is not reachable through its deterministic prefix route`,
        );
      }
    }
    const componentSearch = await loaded.searchRecords([records.components[0].id]);
    assert.ok(componentSearch.records.some((result) =>
      result.id === records.components[0].id
      && result.href === `/data/${encodeURIComponent(records.components[0].id)}`
    ), "component dossiers must be directly addressable through the existing data route");
    const routeSearch = await loaded.searchRecords([records.routes[0].id]);
    assert.ok(routeSearch.records.some((result) =>
      result.id === records.routes[0].id
      && result.href === `/data/${encodeURIComponent(records.routes[0].id)}`
    ), "route dossiers must be directly addressable through the existing data route");
    for (const group of ["files", "symbols", "tests", "workflows", "datasets", "routes", "components", "claims", "imports", "calls", "dependencies"]) {
      for (const record of records[group]) {
        const result = await loaded.searchRecords([record.id]);
        assert.ok(result.records.some((candidate) => candidate.id === record.id && candidate.kind === group), `${group}:${record.id} is not reachable through exact-ID search`);
      }
      assert.equal(manifestA.search.indexedRecordCounts[group], records[group].length);
    }
    const expectedSearchDocumentCount = Object.values(manifestA.search.indexedRecordCounts)
      .reduce((total, count) => total + count, 0);
    assert.equal(manifestA.search.documentCount, expectedSearchDocumentCount);
    assert.match(manifestA.search.documentKeysDigest, /^[0-9a-f]{64}$/);
    assert.equal(
      manifestA.search.documentShards.reduce((total, entry) => total + entry.recordCount, 0),
      expectedSearchDocumentCount,
      "the normalized search document table must retain the exact indexed-record denominator",
    );
    assert.deepEqual(
      manifestA.search.documentShards.map((entry) => [entry.startOrdinal, entry.endOrdinal]),
      manifestA.search.documentShards.map((entry, index) => [
        index === 0 ? 0 : manifestA.search.documentShards[index - 1].endOrdinal + 1,
        entry.startOrdinal + entry.recordCount - 1,
      ]),
      "normalized search document ordinals must be gapless and uniquely routed",
    );
    const searchTermModule = await import(
      `${pathToFileURL(join(outputA, ...manifestA.search.shards[0].module.split("/"))).href}?search-terms=1`,
    );
    assert.ok(
      Object.values(searchTermModule.terms).every((posting) =>
        posting.records.every((ordinal) => Number.isSafeInteger(ordinal) && ordinal >= 0)
      ),
      "search term shards must carry only normalized document ordinals",
    );
    const searchDocumentModule = await import(
      `${pathToFileURL(join(outputA, ...manifestA.search.documentShards[0].module.split("/"))).href}?search-documents=1`,
    );
    assert.equal(
      searchDocumentModule.documents.length,
      manifestA.search.documentShards[0].recordCount,
    );
    assert.ok(searchDocumentModule.documents.every((document) =>
      typeof document.id === "string" && typeof document.kind === "string"
    ));
    assert.equal(
      Object.hasOwn(manifestA.search.groupRecordCounts, "consequential_claim_facets"),
      false,
      "payload-omitting claim subjects must not become search documents",
    );
    assert.equal(
      Object.hasOwn(manifestA.recordBuckets, "consequential_claim_facets"),
      false,
      "claim subjects must not be routed through reviewed-evidence dossiers",
    );
    const lexical = await loaded.searchRecords(["repository.source_commit"]);
    assert.equal(lexical.records[0].id, fixtureStableId("urn:atlas:claim:greeting"));
    const backlinkCapped = await loaded.searchRecords([fixtureStableId("urn:atlas:test:hello")]);
    assert.ok(backlinkCapped.truncatedTerms.length > 0, "fixture must exercise a capped posting");
    assert.ok(backlinkCapped.records.some((record) => record.id === fixtureStableId("urn:atlas:test:hello")), "a capped backlink posting must retain its own stable-ID record");
    const graphSummary = await loaded.loadGraphSummary();
    assert.equal(graphSummary.nodeCount, records.graph_nodes.length);
    assert.equal(graphSummary.edgeCount, records.graph_edges.length);
    const reachedNodes = [];
    const reachedEdges = [];
    for (const community of graphSummary.communities) {
      const full = await loaded.loadGraphCommunity(community.id);
      reachedNodes.push(...full.nodes);
      reachedEdges.push(...full.edges);
    }
    assert.deepEqual(reachedNodes.map((record) => record.id).sort(), records.graph_nodes.map((record) => record.id).sort());
    assert.deepEqual(reachedEdges.map((record) => record.id).sort(), records.graph_edges.map((record) => record.id).sort());
    assert.ok(manifestA.search.shards.every((entry) => entry.bytes <= manifestA.budgets.searchShardMaxBytes));
    assert.ok(manifestA.search.documentShards.every((entry) =>
      entry.bytes <= manifestA.budgets.searchDocumentShardMaxBytes
    ));
    assert.ok(manifestA.search.index.bytes <= manifestA.budgets.searchIndexMaxBytes);
    assert.ok(manifestA.sourceModules.every((entry) => entry.bytes <= manifestA.budgets.sourceChunkMaxBytes));
    assert.equal(
      manifestA.budgets.sourceIndexMaxBytes,
      3 * 1024 * 1024,
      "the reviewed exact-source route-index capacity must remain explicit",
    );
    assert.ok(manifestA.sourceIndex.bytes <= manifestA.budgets.sourceIndexMaxBytes);
    assert.ok(manifestA.graph.shards.every((entry) => entry.bytes <= manifestA.budgets.graphShardMaxBytes));
    assert.ok(manifestA.graph.summary.bytes <= manifestA.budgets.graphShardMaxBytes);
    assert.ok(manifestA.graph.index.bytes <= manifestA.budgets.graphIndexMaxBytes);
    const files = await loaded.loadMetadata("files");
    assert.equal(files.length, 3);
    assert.equal(loaded.projection.releaseClass, "exact_commit");
    assert.equal(await loaded.loadSource("assets/private.bin"), null);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("dirty compiler output is preview-only and requires an explicit override", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-preview-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await mutateGraphifyReceipt(input, (graphify) => {
      graphify.status = "stale";
      graphify.stale = true;
      graphify.unresolved_reasons.push(
        "tracked_worktree_changes_are_newer_than_commit_bound_graph",
      );
    });
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.release_class = "dirty_preview";
    manifest.tracked_worktree_dirty = true;
    const completeness = JSON.parse(
      await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
    );
    completeness.tracked_worktree_dirty = true;
    completeness.consequential_claim_denominator = unavailableConsequentialClaimSummary(
      completeness.source_commit,
      completeness.source_tree_digest,
      "consequential_claim_dirty_preview_not_eligible",
    );
    manifest.completeness = await writeVerifiedValue(
      input,
      manifest.completeness,
      completeness,
    );
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "blocked") }),
      /publishable projection requires release_class exact_commit/,
    );
    await buildProjection({ input, output: join(scratch, "preview"), allowPreview: true });
    const loaded = await import(`${pathToFileURL(join(scratch, "preview", "index.mjs")).href}?preview=1`);
    assert.equal(loaded.projection.releaseClass, "dirty_preview");
    assert.equal(loaded.projection.trackedWorktreeDirty, true);
    assert.equal(loaded.projection.previewAllowed, true);
    await mutateGraphifyReceipt(input, (graphify) => {
      graphify.unresolved_reasons = graphify.unresolved_reasons.filter(
        (reason) => reason !== "tracked_worktree_changes_are_newer_than_commit_bound_graph",
      );
    });
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "preview-without-disposition"), allowPreview: true }),
      /Graphify unresolved reason ledger is malformed/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("preview override cannot authorize an invalid release-class or dirty-state pair", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-release-class-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.release_class = "invented_preview";
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "invented"), allowPreview: true }),
      /^Error: compiler release class and tracked-worktree state are inconsistent$/,
    );

    manifest.release_class = "dirty_preview";
    manifest.tracked_worktree_dirty = true;
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "mismatched"), allowPreview: true }),
      /^Error: compiler release class and tracked-worktree state are inconsistent$/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection fails closed when a compiler chunk digest changes", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-tamper-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await writeFile(join(input, "chunks", "files", "00000.json"), '{"records":[]}\n', "utf8");
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /compiler receipt digest mismatch/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection refuses raw Graphify identifiers and inconsistent edge endpoints before module emission", async (context) => {
  await context.test("raw local-derived identifier", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-id-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      const rawIdentifier = "c_users_fixture_desktop_checkout_app_example";
      await mutateCompilerGroup(input, "graph_nodes", (envelope) => {
        envelope.records[0].graphify_id = rawIdentifier;
      });
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /unique recomputable full-exposure repository-relative identity/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });

  await context.test("dangling retained edge endpoint", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-edge-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "graph_edges", (envelope) => {
        envelope.records[0].target = stableId("graph-node", "missing");
      });
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /edge endpoint, coordinate, or stable identity is inconsistent/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("projection recomputes Graphify identities and enforces full-exposure file joins", async (context) => {
  const rejectsGraphMutation = async (label, group, mutate, pattern) => {
    await context.test(label, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-contract-"));
      try {
        const { input } = await makeCompilerFixture(scratch);
        await mutateCompilerGroup(input, group, mutate);
        const output = join(scratch, "projection");
        await assert.rejects(buildProjection({ input, output }), pattern);
        await assert.rejects(readFile(join(output, "projection-manifest.json")));
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  };

  await rejectsGraphMutation(
    "node file_id differs from its source_file",
    "graph_nodes",
    (envelope) => {
      envelope.records[0].file_id = fixtureStableId("urn:atlas:file:private");
    },
    /unique recomputable full-exposure repository-relative identity/,
  );
  await rejectsGraphMutation(
    "node joins a metadata-only file even with recomputed identities",
    "graph_nodes",
    (envelope) => {
      const node = envelope.records[0];
      node.file_id = fixtureStableId("urn:atlas:file:private");
      node.source_file = "assets/private.bin";
      node.source_location = "1";
      node.coordinate_occurrence = 0;
      node.graphify_id = digestObject([
        "repository-relative-graph-node",
        node.source_file,
        node.source_location,
        "0",
      ]);
      node.id = stableId("graph-node", "d".repeat(40), node.graphify_id);
      node.label = "assets/private.bin:1#1";
    },
    /unique recomputable full-exposure repository-relative identity/,
  );
  await context.test("node rejects a full-exposure file with classification errors", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-node-classification-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "files", (envelope) => {
        const file = envelope.records.find((record) => record.path === "app/example.py");
        file.classification_errors = ["unclassified_source"];
      });
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /unique recomputable full-exposure repository-relative identity/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
  await rejectsGraphMutation(
    "node stable ID is not the canonical public ID",
    "graph_nodes",
    (envelope) => {
      envelope.records[0].id = `urn:atlas:graph-node:${"f".repeat(24)}`;
    },
    /unique recomputable full-exposure repository-relative identity/,
  );
  await rejectsGraphMutation(
    "node community exceeds the JavaScript safe-integer domain",
    "graph_nodes",
    (envelope) => {
      envelope.records[0].community = Number.MAX_SAFE_INTEGER + 1;
    },
    /unique recomputable full-exposure repository-relative identity/,
  );
  await rejectsGraphMutation(
    "node coordinate occurrences have a gap",
    "graph_nodes",
    (envelope) => {
      const node = envelope.records[2];
      node.coordinate_occurrence = 2;
      node.graphify_id = digestObject([
        "repository-relative-graph-node",
        node.source_file,
        node.source_location,
        "2",
      ]);
      node.id = stableId("graph-node", "d".repeat(40), node.graphify_id);
      node.label = "app/example.py:2#3";
    },
    /node coordinate occurrences are not contiguous and one-to-one/,
  );
  await rejectsGraphMutation(
    "edge stable ID is not the canonical public ID",
    "graph_edges",
    (envelope) => {
      envelope.records[0].id = `urn:atlas:graph-edge:${"f".repeat(24)}`;
    },
    /edge endpoint, coordinate, or stable identity is inconsistent/,
  );
  await rejectsGraphMutation(
    "edge confidence is outside the canonical coordinate domain",
    "graph_edges",
    (envelope) => {
      envelope.records[0].confidence = 2;
    },
    /edge confidence must be null or a finite number from zero to one/,
  );
  await context.test("edge rejects a full-exposure file with classification errors", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-edge-classification-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "files", (envelope) => {
        const file = envelope.records.find((record) => record.path === "assets/private.bin");
        file.privacy_exposure = "full";
        file.classification_errors = ["unclassified_source"];
      });
      await mutateCompilerGroup(input, "graph_edges", (envelope) => {
        const edge = envelope.records[0];
        edge.source_file = "assets/private.bin";
        edge.source_location = "1";
        edge.id = stableId(
          "graph-edge",
          "d".repeat(40),
          edge.source,
          edge.target,
          edge.relation,
          edge.source_file,
          edge.source_location,
          edge.extraction_mode,
          graphConfidenceIdentity(edge.confidence),
          edge.coordinate_occurrence,
        );
      });
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /edge endpoint, coordinate, or stable identity is inconsistent/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("projection withholds malformed Graphify producer commit metadata without echoing it", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-commit-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const localMarker = "c_users_foreign_owner_desktop_checkout";
    await mutateGraphifyReceipt(input, (graphify) => {
      graphify.built_at_commit = localMarker;
    });
    const output = join(scratch, "projection");
    await assert.rejects(
      buildProjection({ input, output }),
      (error) => {
        assert.match(error.message, /identifier disposition receipt is absent or inconsistent/);
        assert.equal(error.message.includes(localMarker), false);
        return true;
      },
    );
    await assert.rejects(readFile(join(output, "projection-manifest.json")));
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("exact projection rejects a valid but foreign Graphify producer commit", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-stale-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await mutateGraphifyReceipt(input, (graphify) => {
      graphify.built_at_commit = "a".repeat(40);
      graphify.status = "stale";
      graphify.stale = true;
    });
    const output = join(scratch, "projection");
    await assert.rejects(
      buildProjection({ input, output }),
      /identifier disposition receipt is absent or inconsistent/,
    );
    await assert.rejects(readFile(join(output, "projection-manifest.json")));
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection rejects contradictory or stale Graphify freshness states", async () => {
  for (const [status, stale, addDirtyReason = false] of [
    ["current", true, false],
    ["stale", false, false],
    ["stale", true, false],
    ["current", false, true],
  ]) {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-state-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateGraphifyReceipt(input, (graphify) => {
        graphify.status = status;
        graphify.stale = stale;
        if (addDirtyReason) {
          graphify.unresolved_reasons.push(
            "tracked_worktree_changes_are_newer_than_commit_bound_graph",
          );
        }
      });
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /Graphify unresolved reason ledger is malformed|Graphify identifier disposition receipt is absent or inconsistent/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection reconciles Graphify exclusion ledgers before module emission", async () => {
  for (const mutate of [
    (graphify) => {
      graphify.total_edges += 1;
    },
    (graphify) => {
      graphify.total_edges += 1;
      graphify.excluded_edges = 1;
      graphify.excluded_edge_endpoint_dispositions = {
        source_retained__target_missing_node: 1,
      };
    },
  ]) {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-graph-ledger-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateGraphifyReceipt(input, mutate);
      const output = join(scratch, "projection");
      await assert.rejects(
        buildProjection({ input, output }),
        /Graphify edge modes does not reconcile|Graphify identifier disposition receipt is absent or inconsistent/,
      );
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection validates every Graphify exclusion disposition and traversal field", async () => {
  const marker = "benign-private-token-7f3a";
  const mutations = {
    "non-object node row": (graphify) => {
      graphify.excluded_node_dispositions[0] = marker;
    },
    "undeclared node field": (graphify) => {
      graphify.excluded_node_dispositions[0].producer_note = marker;
    },
    "legacy node raw commitment field": (graphify) => {
      graphify.excluded_node_dispositions[0].raw_record_digest = "a".repeat(64);
    },
    "duplicate node raw index": (graphify) => {
      graphify.total_nodes += 1;
      graphify.excluded_nodes += 1;
      graphify.excluded_nodes_untracked_or_private += 1;
      graphify.node_disposition_counts.excluded_untracked_or_private += 1;
      graphify.node_identifier_disposition_counts.total += 1;
      graphify.node_identifier_disposition_counts.excluded_opaque += 1;
      graphify.node_origins.undisclosed += 1;
      graphify.excluded_node_dispositions.push({
        ...structuredClone(graphify.excluded_node_dispositions[0]),
        id: stableId(
          "graph-node-disposition",
          graphify.source_digest,
          graphify.total_nodes - 1,
        ),
      });
    },
    "uncontrolled node reason": (graphify) => {
      graphify.excluded_node_dispositions[0].reason = marker;
    },
    "non-object edge row": (graphify) => {
      graphify.excluded_edge_dispositions[0] = marker;
    },
    "legacy endpoint raw commitment field": (graphify) => {
      graphify.excluded_edge_dispositions[0].target_endpoint.opaque_identifier_hash =
        "a".repeat(64);
    },
    "endpoint traversal mismatch": (graphify) => {
      graphify.excluded_edge_dispositions[0].source_endpoint.record_id =
        stableId("graph-node-disposition", marker);
    },
    "known endpoint carries anonymous slot": (graphify) => {
      graphify.excluded_edge_dispositions[0].source_endpoint.anonymous_slot = 0;
    },
    "missing endpoint slot gap": (graphify) => {
      graphify.excluded_edge_dispositions[0].target_endpoint.anonymous_slot = 1;
    },
    "endpoint aggregate mismatch": (graphify) => {
      graphify.excluded_edge_endpoint_dispositions = {
        source_missing_node__target_missing_node: 1,
      };
    },
  };
  for (const [label, mutate] of Object.entries(mutations)) {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-exclusion-row-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await seedGraphifyExclusionLedger(input);
      await mutateGraphifyReceipt(input, mutate);
      const output = join(scratch, "projection");
      await assert.rejects(buildProjection({ input, output }), (error) => {
        assert.equal(String(error.stack).includes(marker), false, label);
        return true;
      });
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection preserves repeated anonymous missing-endpoint topology", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-anonymous-endpoint-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await seedGraphifyExclusionLedger(input);
    let repeatedSlots = [];
    await mutateGraphifyReceipt(input, (graphify) => {
      graphify.total_edges += 1;
      graphify.excluded_edges += 1;
      graphify.all_edge_modes.undisclosed += 1;
      graphify.excluded_edge_endpoint_dispositions = {
        source_excluded_untracked_or_private__target_missing_node: 2,
      };
      const rawIndex = graphify.total_edges - 1;
      graphify.excluded_edge_dispositions.push({
        ...structuredClone(graphify.excluded_edge_dispositions[0]),
        id: stableId("graph-edge-disposition", graphify.source_digest, rawIndex),
        raw_index: rawIndex,
      });
      repeatedSlots = graphify.excluded_edge_dispositions
        .flatMap((record) => [record.source_endpoint, record.target_endpoint])
        .filter((endpoint) => endpoint.state === "missing_node")
        .map((endpoint) => endpoint.anonymous_slot);
    });
    const output = join(scratch, "projection");
    const manifest = await buildProjection({ input, output });
    assert.equal(manifest.schemaVersion, "1.2.0");
    assert.deepEqual(repeatedSlots, [0, 0]);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection closes Graphify metadata and retained-row string channels", async () => {
  const marker = "benign-private-token-7f3a";
  const metadataMutations = {
    "top-level key": (graphify) => {
      graphify.producer_note = marker;
    },
    "top-level reason": (graphify) => {
      graphify.unresolved_reasons.push(marker);
    },
    "origin-map key": (graphify) => {
      graphify.node_origins[marker] = 0;
    },
    "community status": (graphify) => {
      graphify.community_dispositions[0].status = marker;
    },
    "scalar disposition mismatch": (graphify) => {
      graphify.excluded_nodes_unsafe_source = 1;
    },
    "projected community mismatch": (graphify) => {
      graphify.projected_community_ids = [];
      graphify.projected_communities = 0;
      graphify.excluded_community_ids = [1];
      graphify.excluded_communities = 1;
      graphify.community_dispositions[0] = {
        community: 1,
        status: "excluded",
        total_nodes: 2,
        retained_nodes: 0,
        excluded_nodes: 2,
      };
      graphify.community_status_counts = {
        projected_complete: 0,
        projected_partial: 0,
        excluded: 1,
      };
    },
    "projected edge-mode mismatch": (graphify) => {
      graphify.projected_edge_modes = { extracted: 2 };
    },
  };
  for (const [label, mutate] of Object.entries(metadataMutations)) {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-metadata-shape-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateGraphifyReceipt(input, mutate);
      const output = join(scratch, "projection");
      await assert.rejects(buildProjection({ input, output }), (error) => {
        assert.equal(String(error.stack).includes(marker), false, label);
        return true;
      });
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }

  for (const group of ["graph_nodes", "graph_edges", "imports"]) {
    for (const key of ["producer_note", "derivation"]) {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-record-shape-"));
      try {
        const { input } = await makeCompilerFixture(scratch);
        await mutateCompilerGroup(input, group, (envelope) => {
          envelope.records[0][key] = marker;
        });
        const output = join(scratch, "projection");
        await assert.rejects(buildProjection({ input, output }), (error) => {
          assert.match(error.message, /undeclared field|graph (?:node|edge) record shape/);
          assert.equal(String(error.stack).includes(marker), false);
          return true;
        });
        await assert.rejects(readFile(join(output, "projection-manifest.json")));
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    }
  }
});

test("projection bounds Graphify coordinates and accepts combined controlled reason order", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-coordinate-bound-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const hugeLocation = "9".repeat(60);
    await mutateCompilerGroup(input, "graph_nodes", (envelope) => {
      const node = envelope.records[0];
      node.source_location = hugeLocation;
      node.graphify_id = digestObject([
        "repository-relative-graph-node",
        node.source_file,
        hugeLocation,
        "0",
      ]);
      node.id = stableId("graph-node", "d".repeat(40), node.graphify_id);
      node.label = `${node.source_file}:${hugeLocation}#1`;
    });
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "blocked") }),
      /unique recomputable full-exposure repository-relative identity/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }

  const combined = await mkdtemp(join(os.tmpdir(), "atlas-projection-reason-order-"));
  try {
    const { input } = await makeCompilerFixture(combined);
    let priorId;
    let replacementId;
    await mutateCompilerGroup(input, "graph_nodes", (envelope) => {
      const node = envelope.records.find((record) => record.origin === "undisclosed");
      priorId = node.id;
      node.source_location = "";
      node.coordinate_occurrence = 0;
      node.graphify_id = digestObject([
        "repository-relative-graph-node",
        node.source_file,
        "",
        "0",
      ]);
      node.id = stableId("graph-node", "d".repeat(40), node.graphify_id);
      replacementId = node.id;
      node.label = `${node.source_file}:source#1`;
      node.file_type = "";
      node.language = "";
      node.kind = "";
      node.entity_type = "graph_node";
      node.unresolved_reasons = [
        "graphify_node_label_derived_from_repository_relative_coordinate",
        "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction",
        "graphify_node_source_location_outside_bounded_coordinate_domain",
        "graphify_node_nonvocabulary_descriptor_withheld",
      ];
    });
    await mutateCompilerGroup(input, "graph_edges", (envelope) => {
      for (const edge of envelope.records) {
        if (edge.source === priorId) edge.source = replacementId;
        if (edge.target === priorId) edge.target = replacementId;
        edge.id = stableId(
          "graph-edge",
          "d".repeat(40),
          edge.source,
          edge.target,
          edge.relation,
          edge.source_file,
          edge.source_location,
          edge.extraction_mode,
          graphConfidenceIdentity(edge.confidence),
          edge.coordinate_occurrence,
        );
      }
      assert.notEqual(priorId, replacementId);
    });
    await buildProjection({ input, output: join(combined, "projection") });
  } finally {
    await rm(combined, { recursive: true, force: true });
  }
});

test("projection binds receipt owners, schema errors, and record IDs without echoing input", async () => {
  const marker = "c_users_foreign_owner_desktop_checkout";
  const mutations = {
    "completeness owner path": async (input) => {
      const path = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(path, "utf8"));
      manifest.completeness.path = `chunks/${marker}.json`;
      await writeFile(path, `${stableJson(manifest)}\n`, "utf8");
    },
    "chunk owner path": async (input) => {
      const path = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(path, "utf8"));
      manifest.groups.files.chunks[0].path = `chunks/files/${marker}.json`;
      await writeFile(path, `${stableJson(manifest)}\n`, "utf8");
    },
    "manifest schema version": async (input) => {
      const path = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(path, "utf8"));
      manifest.schema_version = marker;
      await writeFile(path, `${stableJson(manifest)}\n`, "utf8");
    },
    "failed invariant name": async (input) => {
      const path = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(path, "utf8"));
      const completeness = JSON.parse(
        await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
      );
      completeness.invariants[0].name = marker;
      completeness.invariants[0].passed = false;
      manifest.completeness = await writeVerifiedValue(input, manifest.completeness, completeness);
      await writeFile(path, `${stableJson(manifest)}\n`, "utf8");
    },
    "container record id": async (input) => {
      await mutateCompilerGroup(input, "imports", (envelope) => {
        envelope.records[0].id = [[marker]];
      });
    },
  };
  for (const [label, mutate] of Object.entries(mutations)) {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-fixed-error-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutate(input);
      const output = join(scratch, "projection");
      await assert.rejects(buildProjection({ input, output }), (error) => {
        assert.equal(String(error.stack).includes(marker), false, label);
        return true;
      });
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection refuses compiler receipt traversal outside the input root", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-traversal-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const outsideValue = { records: [] };
    const outsideBytes = Buffer.from(`${stableJson(outsideValue)}\n`, "utf8");
    await writeFile(join(scratch, "outside.json"), outsideBytes);
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.groups.files.chunks[0] = {
      path: "../outside.json",
      bytes: outsideBytes.byteLength,
      sha256: sha256(outsideBytes),
      record_count: manifest.groups.files.record_count,
    };
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");

    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /compiler receipt is malformed/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection rejects a missing semantic acceptance gate before rendering identity", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-gate-missing-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    const completeness = JSON.parse(
      await readFile(join(input, ...manifest.completeness.path.split("/")), "utf8"),
    );
    completeness.acceptance_gates = completeness.acceptance_gates.slice(1);
    manifest.completeness = await writeVerifiedValue(
      input,
      manifest.completeness,
      completeness,
    );
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");

    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /semantic acceptance gate registry differs from schema 1\.2\.0/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection rejects missing and stale standardized GUI dossier shapes", async (context) => {
  await context.test("missing required field", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-gui-missing-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "components", (envelope) => {
        delete envelope.records[0].gui_dossier.accessibility;
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /GUI dossier field is absent or malformed/,
      );
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });

  await context.test("stale source binding", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-gui-stale-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "routes", (envelope) => {
        envelope.records[0].gui_dossier.source_commit = "9".repeat(40);
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /stale or malformed GUI dossier/,
      );
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("line and source groups pass through the same strict chunk-envelope validator", async () => {
  for (const group of ["lines", "source_text"]) {
    const scratch = await mkdtemp(join(os.tmpdir(), `atlas-projection-${group}-envelope-`));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, group, (envelope) => {
        envelope.schema_version = "1.0.0";
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /compiler chunk envelope mismatch/,
      );
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection rejects declared empty chunks instead of treating them as empty groups", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-empty-chunk-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await mutateCompilerGroup(input, "imports", (envelope) => {
      envelope.records = [];
    });
    const output = join(scratch, "projection");
    await assert.rejects(
      buildProjection({ input, output }),
      /compiler group descriptor is malformed/,
    );
    await assert.rejects(readFile(join(output, "projection-manifest.json")));
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection enforces canonical compiler chunk packing and stable-ID order", async () => {
  for (const [label, mutatePartitions, pattern] of [
    [
      "noncanonical repartition",
      (partitions) => [[partitions[0][0]], [partitions[0][1], ...partitions[1]]],
      /compiler chunk descriptor is malformed/,
    ],
    [
      "cross-chunk record reorder",
      (partitions) => [
        [partitions[0][1], partitions[0][0]],
        partitions[1],
      ],
      /stable IDs are not in canonical ascending order/,
    ],
  ]) {
    const scratch = await mkdtemp(join(os.tmpdir(), `atlas-projection-packing-${label.replaceAll(" ", "-")}-`));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await rewriteCompilerPacking(input, 2, "graph_nodes", mutatePartitions);
      const output = join(scratch, "projection");
      await assert.rejects(buildProjection({ input, output }), pattern);
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection rejects self-receipted noncanonical compiler JSON", async () => {
  const marker = "c_users_foreign_owner_desktop_checkout";
  const cases = [
    ["whitespace", "chunk", (parsed) => `${JSON.stringify(parsed, null, 2)}\n`],
    ["key-order", "owner", (parsed) => `${JSON.stringify(Object.fromEntries(Object.entries(parsed).reverse()))}\n`],
    [
      "duplicate-key",
      "chunk",
      (parsed) => `${stableJson(parsed).replace(
        '"schema_version":"1.2.0"',
        `"schema_version":"${marker}","schema_version":"1.2.0"`,
      )}\n`,
    ],
    [
      "deep-nesting",
      "owner",
      (parsed) => {
        let nested = marker;
        for (let depth = 0; depth < 140; depth += 1) nested = [nested];
        return `${stableJson({ ...parsed, producer_note: nested })}\n`;
      },
    ],
  ];
  for (const [label, target, serialize] of cases) {
    const scratch = await mkdtemp(join(os.tmpdir(), `atlas-projection-noncanonical-${label}-`));
    try {
      const { input } = await makeCompilerFixture(scratch);
      const manifestPath = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      const descriptor = target === "chunk"
        ? manifest.groups.imports.chunks[0]
        : manifest.graphify_metadata;
      const path = join(input, ...descriptor.path.split("/"));
      const parsed = JSON.parse(await readFile(path, "utf8"));
      const bytes = Buffer.from(serialize(parsed), "utf8");
      await writeFile(path, bytes);
      descriptor.bytes = bytes.byteLength;
      descriptor.sha256 = sha256(bytes);
      await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
      const output = join(scratch, "projection");
      await assert.rejects(buildProjection({ input, output }), (error) => {
        assert.match(error.message, /compiler receipt is not canonical JSON/);
        assert.equal(error.stack.includes(marker), false);
        return true;
      });
      await assert.rejects(readFile(join(output, "projection-manifest.json")));
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection accepts Python canonical float spellings in compiler chunks", async () => {
  for (const spelling of ["integral", "exponent"]) {
    const scratch = await mkdtemp(join(os.tmpdir(), `atlas-projection-python-float-${spelling}-`));
    try {
      const { input } = await makeCompilerFixture(scratch);
      if (spelling === "exponent") {
        await mutateCompilerGroup(input, "graph_edges", (envelope) => {
          const edge = envelope.records[0];
          edge.confidence = 0.00001;
          edge.id = stableId(
            "graph-edge",
            "d".repeat(40),
            edge.source,
            edge.target,
            edge.relation,
            edge.source_file,
            edge.source_location,
            edge.extraction_mode,
            graphConfidenceIdentity(edge.confidence),
            edge.coordinate_occurrence,
          );
          envelope.records.sort((left, right) => left.id.localeCompare(right.id));
        });
      }
      const manifestPath = join(input, "manifest.json");
      const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      const descriptor = manifest.groups.graph_edges.chunks[0];
      const path = join(input, ...descriptor.path.split("/"));
      const canonical = await readFile(path, "utf8");
      const rewritten = spelling === "integral"
        ? canonical.replace('"confidence":1,', '"confidence":1.0,')
        : canonical.replace('"confidence":0.00001,', '"confidence":1e-05,');
      assert.notEqual(rewritten, canonical);
      const bytes = Buffer.from(rewritten, "utf8");
      await writeFile(path, bytes);
      descriptor.bytes = bytes.byteLength;
      descriptor.sha256 = sha256(bytes);
      await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");
      await buildProjection({ input, output: join(scratch, "projection") });
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  }
});

test("projection rejects duplicate source paths and duplicate path-line coordinates", async (context) => {
  await context.test("duplicate source path", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-source-duplicate-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "source_text", (envelope) => {
        envelope.records.push({
          ...structuredClone(envelope.records[0]),
          id: stableId("source-text", "duplicate-path"),
        });
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /duplicate or invalid source-text path/,
      );
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });

  await context.test("duplicate path-line", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-line-duplicate-"));
    try {
      const { input } = await makeCompilerFixture(scratch);
      await mutateCompilerGroup(input, "lines", (envelope) => {
        envelope.records[1].line = 1;
        envelope.records[1].line_number = 1;
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /duplicate source line record: app\/example\.py:1/,
      );
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("projection reconciles file, source, nonblank, and semantic-line denominators", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-denominator-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await mutateCompilerGroup(input, "files", (envelope) => {
      const file = envelope.records.find((record) => record.path === "app/example.py");
      file.nonblank_line_count = 1;
    });
    await mutateCompilerGroup(input, "structural_entities", (envelope) => {
      envelope.records[0].nonblank_line_count = 1;
    });
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /file\/nonblank\/line\/completeness denominator differs/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("metadata modules split recursively and symbol routes remain deterministic and ID-reachable", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-recursive-split-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const targetPrefix = "a7";
    const ids = [];
    for (let candidate = 0; ids.length < 64; candidate += 1) {
      const id = stableId("symbol", `recursive-${candidate}`);
      if (fnv1a(id).slice(0, 2) === targetPrefix) ids.push(id);
    }
    await mutateCompilerGroup(input, "symbols", (envelope) => {
      const template = envelope.records[0];
      envelope.records.push(...ids.map((id, index) => ({
        ...structuredClone(template),
        id,
        stable_urn: id,
        name: `recursive_${index}`,
        qualified_name: `recursive_${index}`,
        purpose: "x ".repeat(3_500),
      })));
    });
    const outputA = join(scratch, "projection-a");
    const outputB = join(scratch, "projection-b");
    const manifestA = await buildProjection({ input, output: outputA });
    const manifestB = await buildProjection({ input, output: outputB });
    assert.deepEqual(manifestA.metadataModules, manifestB.metadataModules);
    assert.deepEqual(manifestA.recordRoutes.symbol, manifestB.recordRoutes.symbol);
    assert.equal(Object.hasOwn(manifestA.recordBuckets, "symbol"), false);
    assert.equal(Object.hasOwn(manifestA.recordBucketSplitPrefixes, "symbol"), false);
    await assert.rejects(readdir(join(outputA, "records", "symbol")), /ENOENT/);
    assert.ok(manifestA.metadataModules.every((entry) => entry.bytes <= 256 * 1024));
    const symbolMetadataEntries = manifestA.metadataModules.filter((entry) => entry.group === "symbols");
    assert.ok(symbolMetadataEntries.length > 1);
    assert.equal(manifestA.recordRoutes.symbol.moduleCount, symbolMetadataEntries.length);
    assert.equal(
      manifestA.recordRoutes.symbol.entries.reduce((total, entry) => total + entry.recordCount, 0),
      manifestA.groupCounts.symbols,
    );
    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?recursive=1`);
    for (const id of ids) assert.equal((await loaded.loadRecord("symbol", id))?.id, id);
    assert.equal(await loaded.loadRecord("symbol", stableId("symbol", "recursive-unknown")), null);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("a single oversized lazy record is losslessly fragmented below the raw-byte ceiling", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-single-record-cap-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const oversizedPurpose = "x ".repeat(140_000);
    await mutateCompilerGroup(input, "symbols", (envelope) => {
      envelope.records = [{
        ...structuredClone(envelope.records[0]),
        id: stableId("symbol", "oversized"),
        stable_urn: stableId("symbol", "oversized"),
        purpose: oversizedPurpose,
      }];
    });
    const outputA = join(scratch, "projection-a");
    const outputB = join(scratch, "projection-b");
    const manifestA = await buildProjection({ input, output: outputA });
    const manifestB = await buildProjection({ input, output: outputB });
    assert.deepEqual(manifestA.recordFragments, manifestB.recordFragments);
    assert.ok(manifestA.recordFragments.length > 1);
    assert.ok(
      manifestA.recordFragments.every((entry) =>
        entry.bytes <= manifestA.budgets.recordFragmentModuleMaxBytes),
    );
    assert.equal(
      new Set(manifestA.recordFragments.map((entry) => entry.module)).size,
      manifestA.recordFragments.length,
      "the canonical symbol metadata store must publish one fragment set",
    );
    const symbolMetadataEntry = manifestA.metadataModules.find(
      (entry) => entry.group === "symbols" && entry.fragmentedRecordId,
    );
    assert.equal(symbolMetadataEntry?.recordCount, 1);
    assert.equal(Object.hasOwn(manifestA.recordBuckets, "symbol"), false);
    assert.equal(Object.hasOwn(manifestA.recordBucketSplitPrefixes, "symbol"), false);
    await assert.rejects(readdir(join(outputA, "records", "symbol")), /ENOENT/);
    assert.equal(manifestA.recordRoutes.symbol.recordCount, 1);
    assert.equal(manifestA.recordRoutes.symbol.moduleCount, 1);
    assert.deepEqual(
      manifestA.recordRoutes.symbol.entries[0],
      {
        moduleOrdinal: 0,
        module: symbolMetadataEntry.module,
        bytes: symbolMetadataEntry.bytes,
        sha256: symbolMetadataEntry.sha256,
        lowerId: stableId("symbol", "oversized"),
        upperId: stableId("symbol", "oversized"),
        recordCount: 1,
      },
    );
    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?oversized=1`);
    const metadata = await loaded.loadMetadata("symbols");
    assert.equal(metadata.length, 1);
    assert.equal(metadata[0].id, stableId("symbol", "oversized"));
    assert.equal(metadata[0].purpose, oversizedPurpose);
    const dossier = await loaded.loadRecord("symbol", stableId("symbol", "oversized"));
    assert.deepEqual(dossier, metadata[0]);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("community selection clears stale records for invalid, null, mismatched, and rejected loads", () => {
  const prior = { nodes: [{ id: "prior-node" }], edges: [{ id: "prior-edge" }] };
  const invalid = beginCommunitySelection("999", ["1", "2"]);
  assert.equal(invalid.state, "abstained");
  assert.deepEqual(invalid.nodes, []);
  assert.deepEqual(invalid.edges, []);

  const loading = beginCommunitySelection("1", ["1", "2"]);
  assert.equal(loading.state, "loading");
  assert.deepEqual(loading.nodes, []);
  assert.deepEqual(loading.edges, []);

  for (const result of [
    resolveCommunitySelection("1", null),
    resolveCommunitySelection("1", { community: "2", ...prior }),
    resolveCommunitySelection("1", { community: "1", nodes: prior.nodes }),
    rejectCommunitySelection("1"),
  ]) {
    assert.equal(result.state, "abstained");
    assert.deepEqual(result.nodes, []);
    assert.deepEqual(result.edges, []);
    assert.ok(result.message.includes("Community 1"));
  }

  const ready = resolveCommunitySelection("1", { community: "1", ...prior });
  assert.equal(ready.state, "ready");
  assert.equal(ready.loadedCommunity, "1");
  assert.deepEqual(ready.nodes, prior.nodes);
  assert.deepEqual(ready.edges, prior.edges);
  assert.notEqual(ready.nodes, prior.nodes, "selection state must not retain the loader payload array");
});

test("browser workspaces consume bounded search, source, and graph APIs", async () => {
  const atlasRoot = new URL("../../app/atlas/", import.meta.url);
  const repositoryQuery = await readFile(new URL("RepositoryQuery.tsx", atlasRoot), "utf8");
  const sourceFileView = await readFile(new URL("SourceFileView.tsx", atlasRoot), "utf8");
  const graphExplorer = await readFile(new URL("GraphExplorer.tsx", atlasRoot), "utf8");

  assert.match(repositoryQuery, /searchRecords/);
  assert.doesNotMatch(repositoryQuery, /Promise\.all\(groups\.map/);
  assert.doesNotMatch(repositoryQuery, /loadMetadata\(/);
  assert.match(sourceFileView, /loadSourceChunk/);
  assert.doesNotMatch(sourceFileView, /source\.lines\.slice/);
  assert.match(graphExplorer, /loadGraphSummary/);
  assert.match(graphExplorer, /loadGraphCommunity/);
  assert.match(graphExplorer, /communitySelection/);
  assert.match(graphExplorer, /Community view abstained/);
  assert.doesNotMatch(graphExplorer, /loadingCommunity/);
  assert.doesNotMatch(graphExplorer, /loadMetadata\("graph_(?:nodes|edges)"\)/);
});

test("projection record-key registry is identical to the strict atlas-record schema owner", async () => {
  const schema = JSON.parse(
    await readFile(new URL("../../schema/atlas-records.schema.json", import.meta.url), "utf8"),
  );
  const fenceByGroup = {
    files: "filesRecordKeyFence",
    lines: "linesRecordKeyFence",
    source_text: "sourceTextRecordKeyFence",
    symbols: "symbolsRecordKeyFence",
    structural_entities: "structuralEntitiesRecordKeyFence",
    imports: "importsRecordKeyFence",
    calls: "callsRecordKeyFence",
    markdown: "markdownRecordKeyFence",
    structured: "structuredRecordKeyFence",
    documents: "documentsRecordKeyFence",
    routes: "routesRecordKeyFence",
    components: "componentsRecordKeyFence",
    tests: "testsRecordKeyFence",
    workflows: "workflowsRecordKeyFence",
    datasets: "datasetsRecordKeyFence",
    binaries: "binariesRecordKeyFence",
    manifests: "manifestsRecordKeyFence",
    configs: "configsRecordKeyFence",
    dependencies: "dependenciesRecordKeyFence",
    graph_nodes: "graphNodesRecordKeyFence",
    graph_edges: "graphEdgesRecordKeyFence",
    claims: "claimsRecordKeyFence",
    consequential_claim_facets: "consequentialClaimFacetsRecordKeyFence",
  };
  assert.deepEqual(Object.keys(COMPILER_RECORD_KEYS_BY_GROUP).sort(), Object.keys(fenceByGroup).sort());
  for (const [group, fenceName] of Object.entries(fenceByGroup)) {
    assert.deepEqual(
      [...COMPILER_RECORD_KEYS_BY_GROUP[group]].sort(),
      [...schema.$defs[fenceName].propertyNames.enum].sort(),
      `${group} projection keys must match the schema SSOT`,
    );
  }
});
