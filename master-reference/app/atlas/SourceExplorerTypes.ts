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
  sourceModuleCount: number;
  disclosure: Record<string, string>;
};

export type SourceLine = {
  number: number;
  text: string;
  terminator: "" | "\n" | "\r" | "\r\n";
  textDigest: string;
  lineDigest: string;
  recordId: string | null;
  syntaxKind: string | null;
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

export type SourceFilePayload = {
  id: string;
  fileId: string;
  path: string;
  encoding: "utf-8";
  byteCount: number;
  contentDigest: string;
  lineCount: number;
  derivation: string;
  verification: Record<string, string>;
  symbols: SymbolRecord[];
  declaredTests: TestRecord[];
  lines: SourceLine[];
};

export type ProjectionModule = {
  projection: ProjectionIndex;
  metadataLoaders: Record<
    string,
    ReadonlyArray<() => Promise<{ records?: unknown[]; default?: unknown[] }>>
  >;
  sourceLoaders: Record<string, () => Promise<{ source?: SourceFilePayload; default?: SourceFilePayload }>>;
  recordBucketLoaders: Record<string, Record<string, () => Promise<{ records?: DossierRecord[]; default?: DossierRecord[] }>>>;
  loadMetadata: (group: string) => Promise<unknown[]>;
  loadRecord: (kind: string, id: string) => Promise<DossierRecord | null>;
  loadSource: (path: string) => Promise<SourceFilePayload | null>;
  default: ProjectionIndex;
};

export type DossierRecord = SymbolRecord | DatasetRecord | TestRecord | WorkflowRecord | ClaimRecord;

export type ProjectionLoadState =
  | { state: "loading" }
  | { state: "missing"; message: string }
  | { state: "ready"; module: ProjectionModule; files: SourceFileRecord[] };
