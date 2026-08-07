import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import {
  beginCommunitySelection,
  rejectCommunitySelection,
  resolveCommunitySelection,
} from "../../app/atlas/GraphSelection.mjs";
import { buildProjection } from "../../build/projection/build.mjs";

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
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
  assert.equal(groupDescriptor.chunks.length, 1, "fixture mutation helper expects one compiler chunk");
  const chunkDescriptor = groupDescriptor.chunks[0];
  const envelope = JSON.parse(await readFile(join(input, ...chunkDescriptor.path.split("/")), "utf8"));
  await mutate(envelope);
  envelope.record_count = envelope.records.length;
  envelope.records_digest = digestObject(envelope.records.map((record) => record.id));
  manifest.groups[group] = {
    ...groupDescriptor,
    record_count: envelope.records.length,
    records_digest: envelope.records_digest,
    chunks: [{
      ...await writeVerifiedValue(input, chunkDescriptor, envelope),
      record_count: envelope.records.length,
    }],
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
  const lines = [
    { number: 1, text: "def hello():", terminator: "\r\n" },
    { number: 2, text: `    return "Atlas"${denseTail}`, terminator: "\r\n" },
  ].map((line) => ({
    ...line,
    text_digest: sha256(Buffer.from(line.text, "utf8")),
    line_digest: sha256(Buffer.from(`${line.text}${line.terminator}`, "utf8")),
  }));
  const safeId = "urn:atlas:file:safe";
  const privateId = "urn:atlas:file:private";
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
      { id: "urn:atlas:graph-node:hello", graphify_id: "hello", file_id: safeId, source_file: "app/example.py", source_location: "1", label: "hello", language: "python", kind: "function", community: 1, origin: "extracted", extraction_mode: "ast", unresolved_reasons: [] },
      { id: "urn:atlas:graph-node:caller", graphify_id: "caller", file_id: safeId, source_file: "app/example.py", source_location: "2", label: "caller", language: "python", kind: "function", community: 1, origin: "extracted", extraction_mode: "ast", unresolved_reasons: [] },
      { id: "urn:atlas:graph-node:external", graphify_id: "external", file_id: safeId, source_file: "app/example.py", source_location: "2", label: "external", language: "python", kind: "symbol", community: null, origin: "inferred", extraction_mode: "lexical", unresolved_reasons: ["runtime_not_observed"] },
    ],
    graph_edges: [
      { id: "urn:atlas:graph-edge:hello-caller", source: "urn:atlas:graph-node:hello", target: "urn:atlas:graph-node:caller", relation: "calls", source_file: "app/example.py", source_location: "2", extraction_mode: "ast", confidence: 1, unresolved_reasons: [] },
      { id: "urn:atlas:graph-edge:caller-external", source: "urn:atlas:graph-node:caller", target: "urn:atlas:graph-node:external", relation: "references", source_file: "app/example.py", source_location: "2", extraction_mode: "lexical", confidence: 0.5, unresolved_reasons: ["runtime_not_observed"] },
    ],
    claims: [{
      id: "urn:atlas:claim:greeting",
      subject: "urn:atlas:source-state:fixture",
      predicate: "repository.greeting",
      value: "Atlas",
      unit: null,
      basis: "deterministic_structural_derivation_from_exact_git_tree",
      scope: { source_commit: "d".repeat(40), universe: "git_tracked_tree" },
      effective_time: "2026-08-07T00:00:00Z",
      recorded_time: "2026-08-07T00:00:00Z",
      temporal_basis: "git_commit_committer_time",
      owner: "urn:atlas:owner:compiler",
      evidence_ids: ["urn:atlas:completeness:fixture"],
      evidence_class: "derived",
      transformation: { id: "urn:atlas:transformation:greeting", version: "1.0.0" },
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
    }],
  };

  const groups = {};
  for (const [group, groupRecords] of Object.entries(records)) {
    const envelope = {
      schema_version: "1.1.0",
      record_type: group,
      source_commit: "d".repeat(40),
      source_tree_digest: "e".repeat(64),
      chunk_index: 0,
      chunk_count: 1,
      record_count: groupRecords.length,
      records_digest: digestObject(groupRecords.map((record) => record.id)),
      records: groupRecords,
    };
    const descriptor = await writeDescriptor(input, `chunks/${group}/00000.json`, envelope);
    groups[group] = {
      record_count: groupRecords.length,
      chunk_count: 1,
      records_digest: digestObject(groupRecords.map((record) => record.id)),
      chunks: [{ ...descriptor, record_count: groupRecords.length }],
    };
  }
  const graphifyValue = {
    schema_version: "1.1.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    available: false,
    status: "missing",
    stale: null,
    unresolved_reasons: ["fixture_has_no_graph"],
  };
  const completenessValue = {
    id: "urn:atlas:completeness:fixture",
    schema_version: "1.1.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    hard_failure: false,
    fatal_errors: [],
    census: { tracked_files: 2, classified_files: 2, full_exposure_files: 1, metadata_only_files: 1 },
    parsing: { expected_nonblank_lines: 2, line_records: 2 },
    semantic_accounting: {
      safe_parsed_sources: 1,
      structural_root_entities: 1,
      structurally_mapped_lines: 2,
      gui_surface_records: 2,
      gui_dossiers: 2,
    },
    graphify: graphifyValue,
    privacy: {
      primary_corpus: "git_ls_files_only",
      forbidden_content_scan: { status: "passed", findings_count: 0 },
    },
    record_counts: Object.fromEntries(Object.entries(records).map(([name, value]) => [name, value.length])),
    invariants: [
      { name: "every_tracked_file_classified", expected: 2, actual: 2, passed: true },
      { name: "every_safe_text_file_has_exact_source_record", expected: 1, actual: 1, passed: true },
      { name: "every_safe_line_structurally_mapped", expected: 2, actual: 2, passed: true },
      { name: "every_safe_parsed_source_has_one_structural_root", expected: 1, actual: 1, passed: true },
      { name: "every_gui_surface_has_standardized_evidence_honest_dossier", expected: 2, actual: 2, passed: true },
      { name: "graphify_receipt_exact_source_bound", expected: 1, actual: 1, passed: true },
    ],
    acceptance_gates: [
      { name: "fixture_semantic_depth", expected: 2, actual: 2, passed: true },
    ],
  };
  const completeness = await writeDescriptor(input, "completeness.json", completenessValue);
  const graphify = await writeDescriptor(input, "graphify-metadata.json", graphifyValue);
  const manifest = {
    schema_version: "1.1.0",
    status: "complete",
    release_class: "exact_commit",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    head_tree_oid: "f".repeat(40),
    index_digest: "0".repeat(64),
    tracked_worktree_dirty: false,
    completeness,
    graphify_metadata: graphify,
    groups,
  };
  await writeFile(join(input, "manifest.json"), `${stableJson(manifest)}\n`, "utf8");
  return { input, exact, records };
}

test("projection is deterministic, lazy, privacy-gated, and exact-source preserving", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-test-"));
  try {
    const { input, exact, records } = await makeCompilerFixture(scratch);
    const outputA = join(scratch, "projection-a");
    const outputB = join(scratch, "projection-b");
    const manifestA = await buildProjection({ input, output: outputA });
    const manifestB = await buildProjection({ input, output: outputB });

    const indexA = await readFile(join(outputA, "index.mjs"), "utf8");
    const indexB = await readFile(join(outputB, "index.mjs"), "utf8");
    assert.equal(indexA, indexB, "same compiler corpus must produce byte-identical index modules");
    assert.equal(manifestA.index.sha256, manifestB.index.sha256);
    assert.equal(indexA.includes('return "Atlas"'), false, "source text must not enter metadata index");
    assert.equal(indexA.includes("repository.greeting"), false, "claim records must remain lazy");
    assert.equal(indexA.includes("actions/upload-artifact@v4"), false, "workflow entities must remain lazy");
    assert.equal(indexA.includes("pytest==9.1.1"), false, "dependency records must remain lazy");
    assert.equal(manifestA.sourceFileCount, 1, "metadata-only file must have no source descriptor");
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

    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?test=1`);
    assert.deepEqual(loaded.projection.groupCounts, expectedMetadataCounts);
    assert.deepEqual(Object.keys(loaded.metadataLoaders).sort(), Object.keys(expectedMetadataCounts));
    for (const [group, expected] of Object.entries(expectedMetadataCounts)) {
      assert.equal((await loaded.loadMetadata(group)).length, expected, `${group} projection denominator drifted`);
    }
    const source = await loaded.loadSource("app/example.py");
    assert.equal(source.chunkCount, manifestA.sourceModules.length);
    const chunks = await Promise.all(source.chunks.map((chunk) => loaded.loadSourceChunk(source.path, chunk.chunkIndex)));
    const segments = chunks.flatMap((chunk) => chunk.segments);
    assert.equal(segments.map((line) => `${line.text}${line.terminator}`).join(""), exact.toString("utf8"));
    assert.equal(segments[0].containingSymbolId, "urn:atlas:symbol:hello");
    assert.equal(segments[0].structuralMappingBasis, "symbol_range");
    assert.equal(segments[0].explanationDepth, 3);
    assert.equal(segments[0].runtimeTraceState, "synthetic_trace");
    assert.equal(segments[0].testCoverageState, "direct_line_coverage");
    assert.deepEqual(segments[0].testsCoveringIt, ["urn:atlas:test:hello"]);
    assert.deepEqual(segments[0].securityAndPrivacyEffect, { semantic_effect: "none", source_exposure: "full" });
    const lineWindow = await loaded.loadSourceWindow("app/example.py", 2);
    assert.ok(lineWindow.segments.some((line) => line.number === 2));
    const symbol = await loaded.loadRecord("symbol", "urn:atlas:symbol:hello");
    assert.equal(symbol.purpose, "Return the Atlas greeting.");
    assert.equal(symbol.explanationDepth, 4);
    const testCase = await loaded.loadRecord("test", "urn:atlas:test:hello");
    assert.equal(testCase.entityType, "test_case");
    assert.equal(testCase.assertionGroupId, "urn:atlas:test:hello:assertions");
    assert.equal(testCase.assertionCount, 1);
    const assertionGroup = await loaded.loadRecord("test", "urn:atlas:test:hello:assertions");
    assert.equal(assertionGroup.entityType, "test_assertion_group");
    assert.equal(assertionGroup.assertions[0].kind, "assert_statement");
    const workflow = await loaded.loadRecord("workflow", "urn:atlas:workflow:ci");
    assert.deepEqual(workflow.jobIds, ["urn:atlas:workflow:ci:job"]);
    assert.deepEqual(workflow.stepIds, ["urn:atlas:workflow:ci:step"]);
    assert.deepEqual(workflow.permissionIds, ["urn:atlas:workflow:ci:permission"]);
    assert.deepEqual(workflow.artifactIds, ["urn:atlas:workflow:ci:artifact"]);
    const workflowJob = await loaded.loadRecord("workflow", "urn:atlas:workflow:ci:job");
    assert.deepEqual(workflowJob.steps, ["urn:atlas:workflow:ci:step"]);
    assert.deepEqual(workflowJob.permissions, ["urn:atlas:workflow:ci:permission"]);
    assert.deepEqual(workflowJob.artifacts, ["urn:atlas:workflow:ci:artifact"]);
    const workflowStep = await loaded.loadRecord("workflow", "urn:atlas:workflow:ci:step");
    assert.equal(workflowStep.uses, "actions/upload-artifact@v4");
    assert.equal(workflowStep.runDeclared, false);
    const workflowPermission = await loaded.loadRecord("workflow", "urn:atlas:workflow:ci:permission");
    assert.equal(workflowPermission.scope, "job:verify");
    assert.equal(workflowPermission.access, "read");
    const workflowArtifact = await loaded.loadRecord("workflow", "urn:atlas:workflow:ci:artifact");
    assert.equal(workflowArtifact.direction, "produced");
    assert.equal(workflowArtifact.declaredPath, "proof.json");
    const claim = await loaded.loadRecord("claim", "urn:atlas:claim:greeting");
    assert.equal(claim.predicate, "repository.greeting");
    assert.equal(claim.verdict, "proven");
    assert.deepEqual(claim.denominator, { basis: "compiler_source_snapshot", status: "known", unit: "git_tracked_tree", value: 1 });
    assert.deepEqual(claim.evidenceIds, ["urn:atlas:completeness:fixture"]);
    const component = await loaded.loadRecord("data", "urn:atlas:component:greeting");
    assert.equal(component.entityType, "jsx_component_symbol");
    assert.deepEqual(
      component.gui_dossier,
      records.components[0].gui_dossier,
      "projection must preserve the compiler GUI dossier and every field citation verbatim",
    );
    const route = await loaded.loadRecord("data", "urn:atlas:route:greeting");
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
    const lexical = await loaded.searchRecords(["repository.greeting"]);
    assert.equal(lexical.records[0].id, "urn:atlas:claim:greeting");
    const backlinkCapped = await loaded.searchRecords(["urn:atlas:test:hello"]);
    assert.ok(backlinkCapped.truncatedTerms.length > 0, "fixture must exercise a capped posting");
    assert.ok(backlinkCapped.records.some((record) => record.id === "urn:atlas:test:hello"), "a capped backlink posting must retain its own stable-ID record");
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
    assert.ok(manifestA.search.index.bytes <= manifestA.budgets.searchIndexMaxBytes);
    assert.ok(manifestA.sourceModules.every((entry) => entry.bytes <= manifestA.budgets.sourceChunkMaxBytes));
    assert.ok(manifestA.sourceIndex.bytes <= manifestA.budgets.sourceIndexMaxBytes);
    assert.ok(manifestA.graph.shards.every((entry) => entry.bytes <= manifestA.budgets.graphShardMaxBytes));
    assert.ok(manifestA.graph.summary.bytes <= manifestA.budgets.graphShardMaxBytes);
    assert.ok(manifestA.graph.index.bytes <= manifestA.budgets.graphIndexMaxBytes);
    const files = await loaded.loadMetadata("files");
    assert.equal(files.length, 2);
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
    const manifestPath = join(input, "manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.release_class = "dirty_preview";
    manifest.tracked_worktree_dirty = true;
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
      /digest mismatch for chunks\/files\/00000\.json/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
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
      record_count: 0,
    };
    await writeFile(manifestPath, `${stableJson(manifest)}\n`, "utf8");

    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /unsafe compiler input path/,
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
        new RegExp(`compiler chunk envelope mismatch for chunks/${group}/00000\\.json`),
      );
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
          id: "urn:atlas:source-text:duplicate-path",
        });
      });
      await assert.rejects(
        buildProjection({ input, output: join(scratch, "projection") }),
        /duplicate or invalid source-text path: app\/example\.py/,
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
      envelope.records[0].nonblank_line_count = 1;
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

test("metadata and dossier modules split recursively, deterministically, and remain ID-reachable", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-recursive-split-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    const targetPrefix = "a7";
    const ids = [];
    for (let candidate = 0; ids.length < 64; candidate += 1) {
      const id = `urn:atlas:symbol:recursive-${candidate}`;
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
    assert.deepEqual(manifestA.recordBuckets.symbol, manifestB.recordBuckets.symbol);
    assert.ok(manifestA.recordBucketSplitPrefixes.symbol.includes(targetPrefix));
    assert.ok(manifestA.metadataModules.every((entry) => entry.bytes <= 256 * 1024));
    assert.ok(manifestA.recordBuckets.symbol.every((entry) => entry.bytes <= 256 * 1024));
    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?recursive=1`);
    for (const id of ids) assert.equal((await loaded.loadRecord("symbol", id))?.id, id);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("a single oversized lazy record fails instead of exceeding the raw-byte ceiling", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-projection-single-record-cap-"));
  try {
    const { input } = await makeCompilerFixture(scratch);
    await mutateCompilerGroup(input, "symbols", (envelope) => {
      envelope.records = [{
        ...structuredClone(envelope.records[0]),
        id: "urn:atlas:symbol:oversized",
        stable_urn: "urn:atlas:symbol:oversized",
        purpose: "x ".repeat(140_000),
      }];
    });
    await assert.rejects(
      buildProjection({ input, output: join(scratch, "projection") }),
      /metadata symbols record exceeds 262144 bytes/,
    );
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
