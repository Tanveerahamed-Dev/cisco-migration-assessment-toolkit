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
  mkdir,
  readFile,
  realpath,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const GENERATED_MARKER = ".atlas-projection-generated";
// Source text and per-line records have dedicated, privacy-gated per-file
// modules below. Every other compiler group is metadata and must remain in the
// exact-tree denominator. Deriving this list from the signed compiler manifest
// means a newly added metadata adapter cannot silently disappear from Atlas.
const NON_METADATA_GROUPS = new Set(["lines", "source_text"]);
const DOSSIER_GROUPS = {
  symbol: "symbols",
  data: "datasets",
  test: "tests",
  workflow: "workflows",
  claim: "claims",
};
const METADATA_CHUNK_SIZE = 2_000;

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
  const safeMetadata = Object.fromEntries(
    Object.entries(record).filter(([key]) => key !== "text_preview"),
  );
  return {
    ...safeMetadata,
    derivation: record.derivation ?? "compiler_structural",
  };
}

function safeRelative(value) {
  if (
    typeof value !== "string" ||
    !value ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value)
  ) {
    throw new Error(`unsafe compiler input path: ${String(value)}`);
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`unsafe compiler input path: ${value}`);
  }
  return parts;
}

async function safeInputPath(input, relative) {
  const parts = safeRelative(relative);
  let current = input;
  for (const [index, part] of parts.entries()) {
    current = join(current, part);
    const info = await lstat(current);
    if (info.isSymbolicLink()) throw new Error(`symlink compiler input refused: ${relative}`);
    if (index < parts.length - 1 && !info.isDirectory()) {
      throw new Error(`compiler input parent is not a directory: ${relative}`);
    }
  }
  const absolute = resolve(current);
  if (!absolute.startsWith(`${input}${sep}`) || !(await lstat(absolute)).isFile()) {
    throw new Error(`compiler input is not a contained regular file: ${relative}`);
  }
  return absolute;
}

async function readCanonicalJson(input, relative) {
  const path = await safeInputPath(input, relative);
  const bytes = await readFile(path);
  const parsed = JSON.parse(bytes.toString("utf8"));
  const canonical = Buffer.from(`${stableJson(parsed)}\n`, "utf8");
  if (!bytes.equals(canonical)) throw new Error(`compiler JSON is not canonical: ${relative}`);
  return { bytes, parsed };
}

async function readVerified(input, descriptor) {
  if (
    !descriptor ||
    typeof descriptor !== "object" ||
    !/^[0-9a-f]{64}$/.test(String(descriptor.sha256 ?? "")) ||
    !Number.isSafeInteger(descriptor.bytes) ||
    descriptor.bytes < 0
  ) {
    throw new Error("compiler receipt is malformed");
  }
  const path = await safeInputPath(input, descriptor.path);
  const bytes = await readFile(path);
  const actualDigest = sha256(bytes);
  if (actualDigest !== descriptor.sha256) {
    throw new Error(`digest mismatch for ${descriptor.path}`);
  }
  if (bytes.byteLength !== descriptor.bytes) {
    throw new Error(`byte-count mismatch for ${descriptor.path}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new Error(`compiler receipt is not valid UTF-8 JSON: ${descriptor.path}`, { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`compiler receipt is not a JSON object: ${descriptor.path}`);
  }
  return parsed;
}

async function loadGroup(input, manifest, group) {
  const descriptor = manifest.groups?.[group];
  if (!descriptor) return [];
  const records = [];
  if (
    !Number.isSafeInteger(descriptor.record_count) ||
    !Number.isSafeInteger(descriptor.chunk_count) ||
    descriptor.chunk_count !== descriptor.chunks?.length ||
    !/^[0-9a-f]{64}$/.test(String(descriptor.records_digest ?? ""))
  ) {
    throw new Error(`compiler group descriptor is malformed: ${group}`);
  }
  for (const [chunkIndex, chunk] of descriptor.chunks.entries()) {
    const parsed = await readVerified(input, chunk);
    if (
      parsed.schema_version !== manifest.schema_version ||
      parsed.record_type !== group ||
      parsed.source_commit !== manifest.source_commit ||
      parsed.source_tree_digest !== manifest.source_tree_digest ||
      parsed.chunk_index !== chunkIndex ||
      parsed.chunk_count !== descriptor.chunk_count ||
      !Array.isArray(parsed.records) ||
      parsed.record_count !== parsed.records.length ||
      parsed.records_digest !== digestObject(parsed.records.map((record) => String(record?.id ?? "")))
    ) {
      throw new Error(`compiler chunk envelope mismatch for ${chunk.path}`);
    }
    if (parsed.records.length !== chunk.record_count) {
      throw new Error(`record-count mismatch for ${chunk.path}`);
    }
    records.push(...parsed.records);
  }
  if (
    records.length !== descriptor.record_count ||
    digestObject(records.map((record) => String(record?.id ?? ""))) !== descriptor.records_digest
  ) {
    throw new Error(`record-count mismatch for ${group}`);
  }
  return records;
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

function recordBucket(id) {
  const tail = String(id).split(":").at(-1) ?? "";
  return tail.toLowerCase().replace(/[^a-z0-9]/g, "_").slice(0, 2).padEnd(2, "_");
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

export async function buildProjection({ input, output, allowPreview = false }) {
  const inputRoot = await realpath(resolve(input));
  const outputRoot = assertSafeDestination(output);
  const { parsed: manifest } = await readCanonicalJson(inputRoot, "manifest.json");
  const completeness = await readVerified(inputRoot, manifest.completeness);
  const graphify = await readVerified(inputRoot, manifest.graphify_metadata);
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
    !Array.isArray(completeness.invariants) ||
    completeness.invariants.some((item) => item?.passed !== true)
  ) {
    throw new Error("compiler completeness ledger is not bound or structurally complete");
  }
  if (completeness.privacy?.forbidden_content_scan?.status !== "passed") {
    throw new Error("compiler privacy scan is absent or failed");
  }
  if (
    !allowPreview &&
    (manifest.release_class !== "exact_commit" || manifest.tracked_worktree_dirty !== false)
  ) {
    throw new Error(
      "publishable projection requires release_class exact_commit and a clean tracked worktree; use --allow-preview only for an explicitly labelled local preview",
    );
  }

  const metadataGroupNames = Object.keys(manifest.groups ?? {})
    .filter((name) => !NON_METADATA_GROUPS.has(name))
    .sort();
  if (!metadataGroupNames.includes("files")) {
    throw new Error("compiler manifest does not contain the tracked-file denominator");
  }
  const groups = Object.fromEntries(metadataGroupNames.map((name) => [name, []]));
  for (const name of metadataGroupNames) {
    groups[name] = (await loadGroup(inputRoot, manifest, name)).map((record) =>
      compactRecord(name, record),
    );
  }

  const filesByPath = new Map(groups.files.map((record) => [record.path, record]));
  const symbolsByPath = Map.groupBy(groups.symbols, (record) => record.path);
  const testsByPath = Map.groupBy(groups.tests, (record) => record.path);
  const lineMetadataByPath = new Map();
  const lineDescriptor = manifest.groups?.lines;
  for (const chunk of lineDescriptor?.chunks ?? []) {
    const parsed = await readVerified(inputRoot, chunk);
    for (const record of parsed.records ?? []) {
      let lines = lineMetadataByPath.get(record.path);
      if (!lines) {
        lines = new Map();
        lineMetadataByPath.set(record.path, lines);
      }
      lines.set(record.line, {
        id: record.id,
        syntaxKind: record.syntax_kind,
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
    }
  }

  const parent = dirname(outputRoot);
  const staging = join(parent, `.${basename(outputRoot)}.staging-${process.pid}`);
  await rm(staging, { recursive: true, force: true });
  await mkdir(join(staging, "source"), { recursive: true });
  await mkdir(join(staging, "metadata"), { recursive: true });
  await mkdir(join(staging, "records"), { recursive: true });
  await writeFile(join(staging, GENERATED_MARKER), "atlas-projection-v1\n", "utf8");

  const metadataModules = [];
  const metadataLoaderEntries = {};
  for (const [group, groupRecords] of Object.entries(groups)) {
    metadataLoaderEntries[group] = [];
    await mkdir(join(staging, "metadata", group), { recursive: true });
    for (let start = 0; start < groupRecords.length || start === 0; start += METADATA_CHUNK_SIZE) {
      const chunk = groupRecords.slice(start, start + METADATA_CHUNK_SIZE);
      const bytes = Buffer.from(moduleText("records", chunk), "utf8");
      const digest = sha256(bytes);
      const modulePath = `metadata/${group}/${String(start / METADATA_CHUNK_SIZE).padStart(5, "0")}-${digest.slice(0, 16)}.mjs`;
      await writeFile(join(staging, ...modulePath.split("/")), bytes);
      const entry = {
        group,
        module: modulePath,
        recordCount: chunk.length,
        bytes: bytes.byteLength,
        sha256: digest,
      };
      metadataModules.push(entry);
      metadataLoaderEntries[group].push(entry);
      if (groupRecords.length === 0) break;
    }
  }

  const recordBucketEntries = {};
  for (const [kind, group] of Object.entries(DOSSIER_GROUPS)) {
    const buckets = new Map();
    for (const record of groups[group]) {
      const bucket = recordBucket(record.id);
      const current = buckets.get(bucket) ?? [];
      current.push(record);
      buckets.set(bucket, current);
    }
    recordBucketEntries[kind] = [];
    await mkdir(join(staging, "records", kind), { recursive: true });
    for (const [bucket, records] of [...buckets.entries()].sort(([left], [right]) => left.localeCompare(right))) {
      records.sort((left, right) => left.id.localeCompare(right.id));
      const bytes = Buffer.from(moduleText("records", records), "utf8");
      const modulePath = `records/${kind}/${bucket}-${sha256(bytes).slice(0, 16)}.mjs`;
      await writeFile(join(staging, ...modulePath.split("/")), bytes);
      recordBucketEntries[kind].push({
        bucket,
        module: modulePath,
        recordCount: records.length,
        bytes: bytes.byteLength,
        sha256: sha256(bytes),
      });
    }
  }

  const sourceEntries = [];
  const sourceDescriptor = manifest.groups?.source_text;
  for (const chunk of sourceDescriptor?.chunks ?? []) {
    const parsed = await readVerified(inputRoot, chunk);
    for (const record of parsed.records ?? []) {
      const file = filesByPath.get(record.path);
      if (!file || file.privacyExposure !== "full") {
        throw new Error(`source text violates privacy exposure for ${record.path}`);
      }
      const reconstructed = Buffer.from(
        (record.lines ?? []).map((line) => `${line.text}${line.terminator}`).join(""),
        "utf8",
      );
      if (reconstructed.byteLength !== record.byte_count || sha256(reconstructed) !== record.content_digest) {
        throw new Error(`source text does not round-trip for ${record.path}`);
      }
      if (record.content_digest !== file.contentDigest || (record.lines ?? []).length !== record.line_count) {
        throw new Error(`source text metadata disagrees with file census for ${record.path}`);
      }
      for (const line of record.lines ?? []) {
        if (sha256(Buffer.from(line.text, "utf8")) !== line.text_digest) {
          throw new Error(`source text digest mismatch for ${record.path}:${line.number}`);
        }
        if (sha256(Buffer.from(`${line.text}${line.terminator}`, "utf8")) !== line.line_digest) {
          throw new Error(`source line digest mismatch for ${record.path}:${line.number}`);
        }
      }
      const lineMetadata = lineMetadataByPath.get(record.path) ?? new Map();
      const symbolLookup = new Map();
      for (const symbol of symbolsByPath.get(record.path) ?? []) {
        symbolLookup.set(symbol.qualifiedName, symbol.id);
        if (!symbolLookup.has(symbol.name)) symbolLookup.set(symbol.name, symbol.id);
      }
      const payload = {
        id: record.id,
        fileId: record.file_id,
        path: record.path,
        encoding: record.encoding,
        byteCount: record.byte_count,
        contentDigest: record.content_digest,
        lineCount: record.line_count,
        derivation: "compiler_structural",
        verification: {
          sourceIntegrity: "digest_bound_exact_text",
          semanticDepth: "preserved_from_source_line_record",
          testCoverage: "preserved_from_source_line_record",
          runtimeTrace: "preserved_from_source_line_record",
          humanReview: "preserved_from_symbol_dossier",
        },
        symbols: symbolsByPath.get(record.path) ?? [],
        declaredTests: testsByPath.get(record.path) ?? [],
        lines: (record.lines ?? []).map((line) => {
          const structural = lineMetadata.get(line.number);
          return {
            number: line.number,
            text: line.text,
            terminator: line.terminator,
            textDigest: line.text_digest,
            lineDigest: line.line_digest,
            recordId: structural?.id ?? null,
            syntaxKind: structural?.syntaxKind ?? null,
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
            currentOrHistorical:
              structural?.currentOrHistorical ?? file.documentationStatus ?? null,
            unresolvedReasons:
              structural?.unresolvedReasons ?? ["blank_line_not_in_nonblank_semantic_denominator"],
          };
        }),
      };
      const name = `${record.content_digest.slice(0, 24)}-${sha256(record.path).slice(0, 8)}.mjs`;
      const bytes = Buffer.from(moduleText("source", payload), "utf8");
      await writeFile(join(staging, "source", name), bytes);
      sourceEntries.push({
        path: record.path,
        fileId: record.file_id,
        module: `source/${name}`,
        sha256: sha256(bytes),
        bytes: bytes.byteLength,
        contentDigest: record.content_digest,
      });
    }
  }
  sourceEntries.sort((left, right) => left.path.localeCompare(right.path));

  const projection = {
    schemaVersion: "1.0.0",
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
    sourceModuleCount: sourceEntries.length,
    disclosure: {
      metadataDerivation: "compiler_structural",
      metadataCoverage: "every_manifest_group_except_lines_and_source_text",
      sourceLoading: "per_file_static_lazy_import",
      restrictedContent: "metadata_only_never_embedded",
      semanticLimit: "structural mapping is not behavioral or verified understanding",
    },
  };
  const loaderLines = sourceEntries
    .map((entry) => `  ${JSON.stringify(entry.path)}: () => import(${JSON.stringify(`./${entry.module}`)}),`)
    .join("\n");
  const bucketLoaderLines = Object.entries(recordBucketEntries)
    .map(
      ([kind, entries]) =>
        `  ${JSON.stringify(kind)}: Object.freeze({\n${entries
          .map(
            (entry) =>
              `    ${JSON.stringify(entry.bucket)}: () => import(${JSON.stringify(`./${entry.module}`)}),`,
          )
          .join("\n")}\n  }),`,
    )
    .join("\n");
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
      `export const sourceLoaders = Object.freeze({\n${loaderLines}\n});\n` +
      `export const recordBucketLoaders = Object.freeze({\n${bucketLoaderLines}\n});\n` +
      "function bucketFor(id) {\n" +
      "  const tail = String(id).split(\":\").at(-1) ?? \"\";\n" +
      "  return tail.toLowerCase().replace(/[^a-z0-9]/g, \"_\").slice(0, 2).padEnd(2, \"_\");\n" +
      "}\n" +
      "export async function loadMetadata(group) {\n" +
      "  const loaders = metadataLoaders[group];\n" +
      "  if (!loaders) return [];\n" +
      "  const modules = await Promise.all(loaders.map((loader) => loader()));\n" +
      "  return modules.flatMap((module) => module.records ?? module.default ?? []);\n" +
      "}\n" +
      "export async function loadRecord(kind, id) {\n" +
      "  const loader = recordBucketLoaders[kind]?.[bucketFor(id)];\n" +
      "  if (!loader) return null;\n" +
      "  const module = await loader();\n" +
      "  return (module.records ?? module.default ?? []).find((record) => record.id === id) ?? null;\n" +
      "}\n" +
      "export async function loadSource(path) {\n" +
      "  const loader = sourceLoaders[path];\n" +
      "  if (!loader) return null;\n" +
      "  const module = await loader();\n" +
      "  return module.source ?? module.default;\n" +
      "}\n" +
      "export default projection;\n",
    "utf8",
  );
  await writeFile(join(staging, "index.mjs"), indexBytes);

  const outputManifest = {
    schemaVersion: "1.0.0",
    sourceCommit: manifest.source_commit,
    sourceTreeDigest: manifest.source_tree_digest,
    releaseClass: manifest.release_class,
    compilerIndexDigest: manifest.index_digest,
    groupCounts: projection.groupCounts,
    index: { path: "index.mjs", bytes: indexBytes.byteLength, sha256: sha256(indexBytes) },
    metadataModules,
    recordBuckets: recordBucketEntries,
    sourceModules: sourceEntries,
  };
  await writeFile(
    join(staging, "projection-manifest.json"),
    `${stableJson(outputManifest)}\n`,
    "utf8",
  );
  await replaceGeneratedDirectory(staging, outputRoot);
  return outputManifest;
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
