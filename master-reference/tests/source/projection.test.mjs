import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
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

async function writeDescriptor(root, relativePath, value) {
  const bytes = Buffer.from(`${stableJson(value)}\n`, "utf8");
  const path = join(root, ...relativePath.split("/"));
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
  return { path: relativePath, bytes: bytes.byteLength, sha256: sha256(bytes) };
}

async function makeCompilerFixture(root) {
  const input = join(root, "compiler");
  await mkdir(input, { recursive: true });
  const exact = Buffer.from('def hello():\r\n    return "Atlas"\r\n', "utf8");
  const lines = [
    { number: 1, text: "def hello():", terminator: "\r\n" },
    { number: 2, text: '    return "Atlas"', terminator: "\r\n" },
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
    }],
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
    components: [],
    configs: [],
    documents: [],
    routes: [],
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
    graph_nodes: [],
    graph_edges: [],
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
      schema_version: "1.0.0",
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
    available: false,
    status: "missing",
    stale: null,
    unresolved_reasons: ["fixture_has_no_graph"],
  };
  const completenessValue = {
    id: "urn:atlas:completeness:fixture",
    schema_version: "1.0.0",
    source_commit: "d".repeat(40),
    source_tree_digest: "e".repeat(64),
    hard_failure: false,
    fatal_errors: [],
    census: { tracked_files: 2, classified_files: 2, full_exposure_files: 1, metadata_only_files: 1 },
    parsing: { expected_nonblank_lines: 2, line_records: 2 },
    graphify: graphifyValue,
    privacy: {
      primary_corpus: "git_ls_files_only",
      forbidden_content_scan: { status: "passed", findings_count: 0 },
    },
    record_counts: Object.fromEntries(Object.entries(records).map(([name, value]) => [name, value.length])),
    invariants: [
      { name: "every_tracked_file_classified", expected: 2, actual: 2, passed: true },
      { name: "every_safe_text_file_has_exact_source_record", expected: 1, actual: 1, passed: true },
    ],
    acceptance_gates: [
      { name: "fixture_semantic_depth", expected: 2, actual: 2, passed: true },
    ],
  };
  const completeness = await writeDescriptor(input, "completeness.json", completenessValue);
  const graphify = await writeDescriptor(input, "graphify-metadata.json", graphifyValue);
  const manifest = {
    schema_version: "1.0.0",
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
    assert.equal(manifestA.sourceModules.length, 1, "metadata-only file must have no source module");
    const expectedMetadataCounts = Object.fromEntries(
      Object.entries(records)
        .filter(([group]) => !["lines", "source_text"].includes(group))
        .map(([group, values]) => [group, values.length])
        .sort(([left], [right]) => left.localeCompare(right)),
    );
    assert.deepEqual(manifestA.groupCounts, expectedMetadataCounts);
    assert.match(manifestA.sourceModules[0].module, new RegExp(sha256(exact).slice(0, 24)));
    assert.ok(
      manifestA.metadataModules.every((entry) => /-[0-9a-f]{16}\.mjs$/.test(entry.module)),
      "every lazy metadata module URL must carry a content digest",
    );
    assert.ok(
      Object.values(manifestA.recordBuckets).flat().every((entry) => /-[0-9a-f]{16}\.mjs$/.test(entry.module)),
      "every dossier bucket URL must carry a content digest",
    );

    const loaded = await import(`${pathToFileURL(join(outputA, "index.mjs")).href}?test=1`);
    assert.deepEqual(loaded.projection.groupCounts, expectedMetadataCounts);
    assert.deepEqual(Object.keys(loaded.metadataLoaders).sort(), Object.keys(expectedMetadataCounts));
    for (const [group, expected] of Object.entries(expectedMetadataCounts)) {
      assert.equal((await loaded.loadMetadata(group)).length, expected, `${group} projection denominator drifted`);
    }
    assert.deepEqual(Object.keys(loaded.sourceLoaders), ["app/example.py"]);
    const source = await loaded.loadSource("app/example.py");
    assert.equal(source.lines.map((line) => `${line.text}${line.terminator}`).join(""), exact.toString("utf8"));
    assert.equal(source.lines[0].containingSymbolId, "urn:atlas:symbol:hello");
    assert.equal(source.lines[0].explanationDepth, 3);
    assert.equal(source.lines[0].runtimeTraceState, "synthetic_trace");
    assert.equal(source.lines[0].testCoverageState, "direct_line_coverage");
    assert.deepEqual(source.lines[0].testsCoveringIt, ["urn:atlas:test:hello"]);
    assert.deepEqual(source.lines[0].securityAndPrivacyEffect, { semantic_effect: "none", source_exposure: "full" });
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
