export type SourceRange = {
  start_line: number;
  start_column?: number;
  end_line: number;
  end_column?: number;
};

export type SourceFileRecord = {
  id: string;
  path: string;
  language: string;
  mediaType: string;
  roles: string[];
  sizeBytes: number;
  lineCount: number;
  nonblankLineCount: number;
  contentDigest: string | null;
  gitBlobOid: string | null;
  contentSource: string | null;
  privacyExposure: string;
  privacyReasons: string[];
  parseStatus: string;
  parser: string | null;
  parserMode: string | null;
  parserVersion: string | null;
  documentationStatus: string | null;
  documentationStatusReasons: string[];
  classificationErrors: string[];
  unresolvedReasons: string[];
};

export type SymbolRecord = {
  id: string;
  fileId: string;
  path: string;
  name: string;
  qualifiedName: string;
  kind: string;
  language: string;
  range: SourceRange;
  exported: boolean;
  digest: string | null;
  decorators: string[];
  syntaxDepth: number | null;
  stableUrn: string;
  pathAndRange: { path: string; range: SourceRange };
  purpose: string;
  purposeBasis: string;
  responsibility: string;
  parametersAndTypes: unknown[];
  returnOrOutput: unknown;
  stateRead: unknown[];
  stateWritten: unknown[];
  externalEffects: unknown[];
  failureAndExceptionBehavior: string;
  abstentionBehavior: string;
  callers: string[];
  callerResolution: string;
  callees: string[];
  dataDependencies: string[];
  claimsProducedOrConsumed: string[];
  tests: string[];
  testLinkage: string;
  runtimeTraceEvidence: unknown[];
  runtimeTraceState: string;
  performanceCharacteristics: string;
  securityBoundary: string;
  downstreamSurfaces: string[];
  limitations: string[];
  knownImpactIfChanged: string[];
  history: unknown[];
  criticality: string;
  explanationDepth: number;
  reviewState: string;
  derivation: string;
  unresolvedReasons: string[];
};

export type DatasetRecord = {
  id: string;
  fileId: string;
  path: string;
  format: string;
  sizeBytes: number;
  contentDigest: string | null;
  structuredRecordCount: number | null;
  derivation: string;
  unresolvedReasons: string[];
};

export type GuiDossierCitation = {
  record_id: string;
  path: string;
  start_line: number | null;
  end_line: number | null;
  line_state: "source_range" | "source_line_not_resolved" | "not_applicable_binary";
  evidence_role: string;
};

export type GuiDossierField = {
  state: "explicitly_linked" | "structural_only" | "not_evidenced";
  value: unknown;
  citations: GuiDossierCitation[];
  unresolved_reasons: string[];
  gap_ids: string[];
};

export type GuiDossier = {
  id: string;
  surface_id: string;
  surface_kind: "route" | "component";
  source_commit: string;
  source_citation: GuiDossierCitation;
  evidence_state: "explicitly_linked" | "structural_only" | "not_evidenced";
  derivation: "compiler_structural_evidence_only";
  field_count: number;
  persona_journey: GuiDossierField;
  data_snapshot_sources: GuiDossierField;
  props_contract: GuiDossierField;
  state_model: GuiDossierField;
  loading_empty_error_unknown_stale_states: GuiDossierField;
  user_actions: GuiDossierField;
  accessibility: GuiDossierField;
  responsive_behavior: GuiDossierField;
  design_tokens: GuiDossierField;
  white_label_inputs: GuiDossierField;
  design_sync_receipt: GuiDossierField;
  visual_baseline: GuiDossierField;
  tests: GuiDossierField;
  downstream_consumers: GuiDossierField;
  known_gaps: GuiDossierField;
  unresolved_reasons: string[];
  gap_ids: string[];
};

export type GuiSurfaceRecord = {
  id: string;
  fileId: string;
  path: string;
  name: string | null;
  route: string | null;
  method: string | null;
  handler: string | null;
  framework: string | null;
  kind: string | null;
  entityType: string;
  range: SourceRange | null;
  attributeNames: string[];
  gui_dossier: GuiDossier;
  derivation: string;
  unresolvedReasons: string[];
};

export type TestRecord = {
  id: string;
  fileId: string;
  path: string;
  name: string;
  framework: string;
  range: SourceRange | null;
  entityType: "test_case" | "test_assertion_group" | string;
  assertionGroupId: string | null;
  assertionCount: number | null;
  assertions: Array<{
    kind: string;
    range: SourceRange | null;
    digest: string;
  }>;
  extractionDisposition: string;
  derivation: string;
  unresolvedReasons: string[];
};

export type WorkflowRecord = {
  id: string;
  fileId: string;
  path: string;
  name: string;
  entityType:
    | "workflow"
    | "workflow_job"
    | "workflow_step"
    | "workflow_permission"
    | "workflow_artifact"
    | string;
  jobs: string[];
  triggers: string[];
  jobIds: string[];
  stepIds: string[];
  permissionIds: string[];
  artifactIds: string[];
  steps: string[];
  permissions: string[];
  artifacts: string[];
  job: string | null;
  stepIndex: number | null;
  uses: string | null;
  runDeclared: boolean | null;
  sourceDigest: string | null;
  scope: string | null;
  access: string | null;
  stepId: string | null;
  direction: string | null;
  declaredPath: string | null;
  action: string | null;
  range: SourceRange | null;
  parserMode: string;
  extractionDisposition: string;
  derivation: string;
  unresolvedReasons: string[];
};

export type ClaimRecord = {
  id: string;
  subject: string;
  predicate: string;
  value: unknown;
  unit: string | null;
  basis: string;
  scope: Record<string, unknown>;
  effectiveTime: string | null;
  recordedTime: string | null;
  temporalBasis: string;
  owner: string;
  evidenceIds: string[];
  evidenceClass: string;
  transformation: Record<string, unknown> | null;
  denominator: Record<string, unknown> | null;
  verdict: string;
  freshness: string;
  lineage: string[];
  derivedFrom: string[];
  origin: string;
  extractionMode: string;
  confidence: number | null;
  status: string;
  revokedBy: string | null;
  revocationReason: string | null;
  conflictsWith: string[];
  currentView: boolean;
  satisfiesEvidenceRequirement: boolean;
  sourceCommit: string | null;
  derivation: string;
  unresolvedReasons: string[];
};

export type GenericRecord = Record<string, unknown> & {
  id?: string;
  file_id?: string;
  path?: string;
  derivation?: string;
  unresolved_reasons?: string[];
};

export type CompletenessInvariant = {
  name: string;
  expected: number | boolean | null;
  actual: number | boolean | null;
  passed: boolean;
};

export type ProjectionIndex = {
  schemaVersion: string;
  status: string;
  releaseClass: string;
  sourceCommit: string;
  sourceTreeDigest: string;
  headTreeOid: string;
  compilerIndexDigest: string;
  trackedWorktreeDirty: boolean;
  previewAllowed: boolean;
  completeness: {
    hard_failure: boolean;
    fatal_errors: string[];
    census: Record<string, number>;
    parsing: Record<string, unknown>;
    privacy: Record<string, unknown>;
    record_counts: Record<string, number>;
    invariants: CompletenessInvariant[];
    acceptance_gates?: CompletenessInvariant[];
    semantic_accounting?: Record<string, unknown>;
    graphify?: Record<string, unknown>;
  };
  groupCounts: Record<string, number>;
  sourceFileCount: number;
  sourceModuleCount: number;
  disclosure: Record<string, string>;
};

export type ProjectionIdentity = {
  schemaVersion: string;
  status: string;
  releaseClass: string;
  sourceCommit: string;
  sourceTreeDigest: string;
  trackedWorktreeDirty: boolean;
  failedAcceptanceGates: Array<{ name: string }>;
};

export type ProjectionIdentityModule = {
  identity: ProjectionIdentity;
  default?: ProjectionIdentity;
};

export type SourceLine = {
  number: number;
  text: string;
  terminator: "" | "\n" | "\r" | "\r\n";
  fragmentIndex: number;
  fragmentCount: number;
  fragmentDigest: string;
  textDigest: string;
  lineDigest: string;
  recordId: string | null;
  syntaxKind: string | null;
  structuralMappingBasis: string | null;
  containingSymbol: string | null;
  containingSymbolId: string | null;
  syntaxDepth: number | null;
  explanationDepth: number;
  semanticEntity: string | null;
  owner: string | null;
  behaviorGroup: string[];
  inputsAndOutputs: Record<string, unknown> | null;
  claimsInfluenced: string[];
  callersAndDependencies: string[];
  testsCoveringIt: string[];
  testCoverageState: string;
  runtimeTraceState: string;
  guiOrArtifactConsumers: string[];
  securityAndPrivacyEffect: Record<string, unknown> | null;
  currentOrHistorical: string | null;
  unresolvedReasons: string[];
};

export type SourceChunkDescriptor = {
  module: string;
  sha256: string;
  bytes: number;
  chunkIndex: number;
  startLine: number;
  endLine: number;
  startFragment: number;
  endFragment: number;
  segmentCount: number;
};

export type SourceFilePayload = {
  id: string;
  fileId: string;
  path: string;
  encoding: "utf-8";
  byteCount: number;
  contentDigest: string;
  lineCount: number;
  segmentCount: number;
  chunkCount: number;
  derivation: string;
  verification: Record<string, string>;
  chunks: SourceChunkDescriptor[];
};

export type SourceChunkPayload = Omit<SourceFilePayload, "segmentCount" | "chunkCount" | "chunks"> & {
  segments: SourceLine[];
};

export type SearchProjectionRecord = {
  id: string;
  kind: string;
  title: string;
  detail: string;
  href: string;
  score: number;
};

export type SearchProjectionResult = {
  records: SearchProjectionRecord[];
  truncatedTerms: Array<{ term: string; totalMatches: number; returned: number }>;
  ignoredTokenCount: number;
};

export type ProjectionModule = {
  projection: ProjectionIndex;
  metadataLoaders: Record<
    string,
    ReadonlyArray<() => Promise<{ records?: unknown[]; default?: unknown[] }>>
  >;
  recordBucketLoaders: Record<string, Record<string, () => Promise<{ records?: DossierRecord[]; default?: DossierRecord[] }>>>;
  loadMetadata: (group: string) => Promise<unknown[]>;
  loadRecord: (kind: string, id: string) => Promise<DossierRecord | null>;
  loadSource: (path: string) => Promise<SourceFilePayload | null>;
  loadSourceChunk: (path: string, chunkIndex: number) => Promise<SourceChunkPayload | null>;
  loadSourceWindow: (path: string, line: number) => Promise<SourceChunkPayload | null>;
  searchRecords: (tokens: string[]) => Promise<SearchProjectionResult>;
  loadGraphSummary: () => Promise<unknown>;
  loadGraphCommunity: (community: string) => Promise<unknown>;
  default: ProjectionIndex;
};

export type DossierRecord = SymbolRecord | DatasetRecord | GuiSurfaceRecord | TestRecord | WorkflowRecord | ClaimRecord;

export type ProjectionLoadState =
  | { state: "loading" }
  | { state: "missing"; message: string }
  | { state: "ready"; module: ProjectionModule; files: SourceFileRecord[] };
