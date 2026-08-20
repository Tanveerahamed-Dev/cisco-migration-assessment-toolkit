// Typed client for the AssessHub backend. One origin in prod; Vite proxies /api -> :8000 in dev.

export interface Summary {
  version: string;
  n_switches: number;
  avg_health: number | string;
  bands: Record<string, number>;
  n_critical: number;
  punchlist: {
    total: number;
    by_severity: Record<string, number>;
    by_category: Record<string, number>;
    crit_high: number;
  };
  readiness: Record<"READY" | "CAUTION" | "NOT READY", number>;
  keystones: Array<Record<string, any>>;
  lifecycle: LifecycleSummary;
  verification?: SnapshotVerification;
  sections: Array<{ key: string; label: string; count: number }>;
}

/** Hardware-lifecycle (EoX) census as projected by webapp/backend/summary.py::_lifecycle.
 *
 *  COVERAGE-HONESTY CONTRACT (audit U1-1): `past_eos`/`near_eos`/`past_ldos` are the RISK rollups —
 *  all three being 0 does NOT mean the fleet is supported, it can equally mean nothing was assessed.
 *  `unknown` / `coverage_gap` are the other half of that fact and must be rendered wherever the
 *  rollups are: an all-Unknown fleet used to serialise byte-identically to an all-Active one.
 *  Every count may be `""` when the engine published no figure — treat "" as UNKNOWN, never as 0. */
export interface LifecycleSummary {
  past_eos?: number | string;
  near_eos?: number | string;
  past_ldos?: number | string;
  active?: number | string;
  /** Assets with no exact EoX row or incomplete retained source/date authority. A gap, never clean. */
  unknown?: number;
  n_devices?: number;
  assessed?: number;
  /** The FULL engine band census, so a band this client does not know by name still reaches the UI. */
  by_band?: Record<string, number>;
  /** Which census keys were classified as not-assessed buckets (e.g. ["Unknown"]). */
  not_assessed_bands?: string[];
  coverage_gap?: boolean;
}

export interface SnapshotVerification {
  contract_version: number;
  origin?: string;
  integrity_status: "verified" | "failed" | "unknown";
  status: "verified" | "partial" | "unverified";
  label: string;
  verified: boolean;
  coverage_honest: boolean;
  reasons: string[];
  failed_phases: string[];
  missing_authorities: string[];
  non_authoritative_authorities: string[];
  integrity_failed_authorities: string[];
  integrity_unknown_authorities: string[];
}

export interface SnapshotMeta {
  id: number;
  campaign_id: number;
  label: string;
  uploaded_at: string;
  script_version: string;
  n_devices: number;
  summary: Summary;
}

/** Coverage-honest projection returned by `/api/snapshots/{id}/graph`.
 *
 * `is_bridge: false` is a redundancy verdict only when `bridge_assessed` is true. Older snapshots
 * and partially computed projections can carry a perfectly drawable edge whose bridge status was
 * never measured, so consumers must preserve the third state instead of collapsing it to healthy.
 */
export interface TopologyNode {
  id: string;
  band: string;
  score: number | null;
  role: string;
  degree: number;
  keystone: boolean;
}

export interface TopologyEdge {
  source: string;
  target: string;
  bridge_assessed?: boolean;
  is_bridge: boolean;
  pairs_cut: number;
}

export interface TopologyGraphData {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  /** True when at least one link-centrality record was available; inspect each edge as well. */
  link_centrality_assessed?: boolean;
  /** Discovered CDP peers which were not present as collected switch nodes in this snapshot. */
  offscan_peers?: string[];
}

export interface Campaign {
  id: number;
  name: string;
  description: string;
  created_at: string;
  n_snapshots?: number;
  last_upload?: string | null;
  latest_summary?: Summary | null;
  snapshots?: SnapshotMeta[];
}

export interface Deliverable {
  key: string;
  label: string;
  ext: string;
  available: boolean;
  producer?: "engine-cli" | "assesshub-snapshot";
  engine_cli_member?: boolean;
  stage?: "pre-cutover";
}

export interface ArtifactFamilyMeta {
  pre_cutover: number;
  engine_cli: number;
  assesshub_only_pre_cutover: number;
  conditional_post_execution: number;
}

// ADR-0004 D1: served from the brand SSOT (cisco_toolkit/brand_tokens.py) — the SPA renders these,
// never hardcodes them, so a rename stays a one-line change in the owner module.
export interface AppIdentity {
  name: string;
  byline: string;
  title: string;
  release: string;
}

export interface Meta {
  engine_schema: string;
  severity_order: string[];
  bands: string[];
  section_labels: Array<{ key: string; label: string }>;
  deliverables: Deliverable[];
  artifact_family?: ArtifactFamilyMeta;
  app: AppIdentity;
}

export interface CurrentBaselineBlocker {
  device: string;
  wave: string;
  category: string;
  severity: string;
  check: string;
  command?: string;
  expect: string;
  why?: string;
  evidence_state: string;
  projection_custody: string;
  source_key: string;
  baseline_state?: string;
  baseline_blocker?: boolean;
}

export interface CurrentBaselineGate {
  schema: string;
  verdict: "BLOCKED" | "INDETERMINATE" | "CLEAR" | "NOT_ASSESSED" | string;
  assessed?: boolean;
  note: string;
  n_blockers?: number;
  fleet_n_blockers?: number;
  summary?: {
    n_items?: number;
    n_blockers?: number;
    n_blockers_returned?: number;
    blockers_capped?: boolean;
    by_state?: Partial<Record<"degraded" | "review" | "not_verified", number>>;
    by_wave?: Record<string, number>;
  };
  blockers?: CurrentBaselineBlocker[];
  integrity?: { valid?: boolean; failures?: string[] };
  limitations?: string[];
}

// -- source-bound before/after protocol assurance -------------------------
// These contracts are projections of the server-owned Release-1 receipts. Presentation code may
// cap rows, but must never derive an overall verdict from those rendered subsets: cutover_gate/1
// is the sole before/after decision owner.
export type SnapshotDeltaVerdict = "CLEAN" | "REVIEW" | "REGRESSED" | "INDETERMINATE";
export type CutoverGateVerdict = "PASS" | "CONDITIONAL" | "REVIEW" | "INDETERMINATE" | "FAIL" | "REGRESSED";
export type ProtocolComparisonStatus = "admitted" | "coverage_lost" | "not_comparable";
export type ProtocolChangeTransition =
  | "unchanged_healthy"
  | "unchanged_degraded"
  | "recovered"
  | "regressed"
  | "appeared"
  | "disappeared"
  | "intent_changed"
  | "coverage_lost"
  | "not_comparable";
export type ProtocolAssuranceLevel =
  | "intent_reconciled_survival"
  | "observed_state_preservation"
  | "local_safety_preservation"
  | "not_verified";

export interface ProtocolSourceBinding {
  source: string;
  sha256: string;
  bytes?: number;
  snapshot_id: number;
  campaign_id: number;
  engagement_id: string;
  label?: string;
  script_version?: string;
}

export interface ProtocolSupportProfile {
  schema: "protocol_support_profile/1";
  family: string;
  owner_schema: string;
  implementation_state: string;
  assurance_level: ProtocolAssuranceLevel;
  evidence_contracts?: string[];
  runtime_support_claim: string;
  scope?: Record<string, unknown>;
  variants?: Array<Record<string, unknown>>;
  limitations: string[];
}

export type ProtocolEvidenceStatus = "observed" | "partial" | "not_applicable" | "not_verified";

export interface ProtocolSingleSnapshotSubject {
  family: string;
  subject: string;
  kind: string;
  evidence_state: string;
  source_contract: string;
  detail: Record<string, unknown>;
}

export interface ProtocolSingleSnapshotFamily {
  family: string;
  owner_schema: string;
  assurance_level: ProtocolAssuranceLevel;
  evidence_contracts: string[];
  evidence_status: ProtocolEvidenceStatus;
  status_reason: string;
  source_custody: string;
  producer_summary: Record<string, unknown>;
  producer_state_counts: Record<string, number>;
  coverage_state_counts: Record<string, number>;
  subject_total: number;
  subjects: {
    total: number;
    rendered: number;
    omitted: number;
    rows: ProtocolSingleSnapshotSubject[];
  };
  limitations: string[];
}

export interface ProtocolSingleSnapshotReceipt {
  schema: "protocol_single_snapshot_receipt/1";
  owner_version: string;
  owns_score: false;
  owns_verdict: false;
  custody_status: "bound" | "not_verified";
  custody_failures: string[];
  source_binding: ProtocolSourceBinding & { bytes: number };
  script_owner: {
    source: string;
    snapshot_value: string;
    stored_value: string;
    status: "bound" | "not_verified";
  };
  support_profiles: ProtocolSupportProfile[];
  summary: {
    n_families: number;
    n_subjects_total: number;
    by_evidence_status: Record<ProtocolEvidenceStatus, number> | Record<string, number>;
  };
  families: ProtocolSingleSnapshotFamily[];
  render_cap: number;
  complete_export: {
    schema: "protocol_single_snapshot_export/1";
    sha256: string;
    media_type: "application/json";
  };
  custody_note: string;
  receipt_sha256: string;
}

export interface ProtocolAssuranceSection {
  section: "protocol_assurance";
  data: {
    receipt: ProtocolSingleSnapshotReceipt;
    complete_export: ProtocolSingleSnapshotReceipt["complete_export"] & { url: string };
  };
}

export interface ProtocolSubjectIdentitySet {
  schema: "protocol_subject_identity_set/1";
  identity_kind: string;
  n_subjects: number;
  subjects: string[];
  subjects_sha256: string;
  valid: boolean;
  failures: string[];
}

export interface ExpectedProtocolFamilyChange {
  family: string;
  transitions: ProtocolChangeTransition[];
  subjects: string[];
  reason: string;
}

export interface CutoverChangeIntent {
  schema: "cutover_change_intent/1";
  status: "invalid" | "reconciled" | "not_supplied";
  valid: boolean;
  note: string;
  binding: {
    engagement_id: string;
    campaign_id: number;
    before_snapshot_id: number;
    after_snapshot_id: number;
    before_sha256: string;
    after_sha256: string;
  };
  expected_changes: ExpectedProtocolFamilyChange[];
  expected_changes_sha256: string;
  failures: string[];
}

/** Input form accepted by /api/compare and the execution comparison endpoint. */
export interface CutoverChangeIntentInput {
  expected_changes?: Array<{
    family: string;
    transitions: ProtocolChangeTransition[];
    subjects?: string[];
    reason?: string;
  }>;
  note?: string;
}

export interface ProtocolComparisonAdmission {
  schema: "protocol_comparison_admission/1";
  status: ProtocolComparisonStatus;
  decision_eligible: boolean;
  assurance_level: ProtocolAssuranceLevel;
  engagement_id: string;
  campaign_id: number;
  source_binding: { before: ProtocolSourceBinding; after: ProtocolSourceBinding };
  subject_binding: { before: ProtocolSubjectIdentitySet; after: ProtocolSubjectIdentitySet };
  owner_versions: Record<string, string>;
  support_profiles: ProtocolSupportProfile[];
  failures: string[];
  coverage_gaps: string[];
}

export interface ProtocolFamilyChange {
  family: string;
  subject: string;
  /** Native subject identity class; multichassis keeps local/pair/leg/attachment distinct. */
  subject_kind?:
    | "local_observation"
    | "reciprocal_peer_pair"
    | "local_leg"
    | "reconciled_attachment"
    | string;
  transition: ProtocolChangeTransition;
  /** Producer-reconciled intent classification. UI code displays this value; it does not infer it. */
  expected: boolean;
  decision_effect: "block" | "review" | "none" | "not_verified";
  /** Family-native owners publish typed state objects; the IPv4 v1 adapter still publishes strings. */
  before_state: unknown;
  after_state: unknown;
  note: string;
}

export interface ProtocolFamilyChangeSummary {
  n_subject_changes: number;
  n_implicit_unchanged_healthy?: number;
  n_expected: number;
  n_unexpected: number;
  n_coverage_lost: number;
  n_blocking?: number;
  n_review?: number;
  n_not_verified?: number;
  by_transition: Record<ProtocolChangeTransition, number>;
  by_decision_effect?: Record<ProtocolFamilyChange["decision_effect"], number>;
}

export interface ProtocolFamilyChanges {
  family: string;
  owner_schema: string;
  assurance_level: ProtocolAssuranceLevel;
  support_profile: ProtocolSupportProfile;
  summary: ProtocolFamilyChangeSummary;
  changes: ProtocolFamilyChange[];
  source_receipt: ProtocolAdjacencyDelta | Record<string, unknown>;
  composition_failures?: string[];
}

export interface ProtocolFamilyChangeSet {
  schema: "protocol_family_change_set/1";
  owner: "reference_only_composition" | string;
  owns_score: false;
  owns_verdict: false;
  summary: {
    n_families: number;
    n_subject_changes: number;
    n_expected: number;
    n_unexpected: number;
    n_coverage_lost: number;
    n_blocking?: number;
    n_review?: number;
    n_not_verified?: number;
    by_transition?: Record<ProtocolChangeTransition, number>;
    by_decision_effect?: Record<ProtocolFamilyChange["decision_effect"], number>;
  };
  families: ProtocolFamilyChanges[];
}

export interface ProtocolAdjacencyDelta {
  schema?: "protocol_adjacency_delta/1" | string;
  gate?: "PASS" | "REVIEW" | "REGRESSED" | "NOT_ASSESSED" | string;
  assessed?: boolean;
  scope?: string;
  projection_custody?: string;
  summary?: Partial<Record<
    | "n_baseline_peers"
    | "n_scoped_cells"
    | "n_comparable_cells"
    | "n_preserved"
    | "n_state_regressed"
    | "n_recovered"
    | "n_no_longer_observed"
    | "n_added"
    | "n_metadata_changed"
    | "n_coverage_gaps",
    number
  >>;
  changes?: Array<Record<string, unknown>>;
  coverage_gaps?: Array<Record<string, unknown>>;
  note?: string;
  limitations?: string[];
}

export interface PrecertReceipt {
  schema: "precert/1";
  verdict: "PASS" | "CONDITIONAL" | "FAIL" | "INDETERMINATE";
  verdict_note: string;
  flows: Record<string, unknown> & {
    assessed?: boolean;
    capped?: boolean;
    subnets_tested?: number;
    subnets_total?: number;
    changed?: Array<Record<string, unknown>>;
    inconclusive?: Array<Record<string, unknown>>;
    ecmp_partial_drop?: Array<Record<string, unknown>>;
  };
  segmentation: Array<Record<string, unknown>>;
  intents: Array<Record<string, unknown>>;
  regressions: string[];
  gate_failures: string[];
  blind_spots: string[];
  stamps: Record<string, unknown>;
  integrity: { ok: boolean; failures: string[] };
  source_binding: { before?: ProtocolSourceBinding; after?: ProtocolSourceBinding } | Record<string, unknown>;
  schema_status: Record<string, unknown>;
}

export interface CutoverGate {
  schema: "cutover_gate/1";
  verdict: CutoverGateVerdict;
  /** Complete server-owned decision basis; presentation code must not replace or shorten it. */
  note: string;
  /** Operator-facing server-owned conclusion and action. */
  operator_note: string;
  delta_verdict: SnapshotDeltaVerdict;
  delta_display: string;
  delta_note: string;
  certificate_verdict: PrecertReceipt["verdict"];
  certificate_note: string;
  protocol_gate: string;
  protocol_baseline_peers: number;
  protocol_regressions: number;
  protocol_coverage_gaps: number;
  protocol_family_status?: "not_comparable" | "coverage_lost" | "regressed" | "review" | "clear";
  protocol_family_note?: string;
  protocol_family_rows?: number;
  protocol_family_blocking?: number;
  protocol_family_review?: number;
  protocol_family_not_verified?: number;
  comparison_admission_status?: ProtocolComparisonStatus;
  comparison_admission_note?: string;
  current_baseline_verdict?: CurrentBaselineGate["verdict"];
  current_baseline_note?: string;
  current_baseline_blockers?: number;
  current_baseline_degraded?: number;
  current_baseline_review?: number;
  current_baseline_not_verified?: number;
}

export interface ProtocolReceiptEnvelope {
  schema: "protocol_receipt_envelope/1";
  admission: ProtocolComparisonAdmission;
  source_binding: ProtocolComparisonAdmission["source_binding"];
  subject_binding: ProtocolComparisonAdmission["subject_binding"];
  owner_versions: Record<string, string>;
  support_profiles: ProtocolSupportProfile[];
  payload_sha256: string;
  receipt_sha256: string;
}

export type L2FailureRehearsalDisposition =
  | "simulation_only"
  | "projected_risk"
  | "current_fault"
  | "not_verified";

export interface L2FailureRehearsalScenario {
  family: "stp" | "etherchannel" | "multichassis_lag" | "service_path" | string;
  subject: string;
  failure_scenario: string;
  disposition: L2FailureRehearsalDisposition;
  assurance_level: "not_verified";
  source_owner: string;
  current_fault: boolean;
  evidence: Record<string, unknown>;
  note: string;
}

export interface L2FailureRehearsal {
  schema: "l2_failure_rehearsal/1";
  owner: "reference_only_composition" | string;
  owns_score: false;
  owns_verdict: false;
  status: "simulation_only" | "projected_risk" | "current_fault" | "not_verified";
  assurance_level: "not_verified";
  source_bound: boolean;
  summary: {
    n_scenarios: number;
    n_current_faults: number;
    n_projected_risks: number;
    n_not_verified: number;
    by_disposition: Record<L2FailureRehearsalDisposition, number>;
  };
  scenarios: L2FailureRehearsalScenario[];
  limitations: string[];
}

export interface CutoverOperatorEvidence {
  schema: "cutover_operator_evidence/1";
  owner: "reference_only_projection" | string;
  owns_verdict: false;
  current_baseline_blocker_export?: {
    schema: "current_baseline_blocker_export/1";
    owner: "reference_only_projection" | string;
    owns_verdict: false;
    status: "available" | "not_verified";
    source_owner: string;
    rows: CurrentBaselineBlocker[];
    summary: {
      n_blockers_total: number;
      n_rows_returned: number;
      omitted: number;
      complete: boolean;
      rows_sha256: string;
    };
    failures: string[];
    note: string;
  };
  rehearsal: {
    status: "simulation_only" | "projected_risk" | "current_fault" | "not_verified";
    assurance_level: "not_verified";
    source_owner: string;
    n_impacts_total: number;
    impacts: Array<Record<string, unknown>>;
    l2_failure_rehearsal?: L2FailureRehearsal;
    note: string;
  };
  rollback: {
    status: "planned" | "coverage_lost" | "not_verified";
    assurance_level: "not_verified";
    source_owner: string;
    n_groups_total: number;
    n_plans_total: number;
    plans: Array<{ group: string; recommended_scenario: string; rollback: string }>;
    note: string;
  };
}

/** Additive /api/compare response: all historical delta fields remain top-level. */
export interface CompareResponse {
  comparison_schema?: "source_bound_cutover_comparison/1";
  verdict: SnapshotDeltaVerdict;
  verdict_display?: string;
  verdict_note?: string;
  findings?: { n_opened?: number; n_opened_high?: number; n_resolved?: number } & Record<string, unknown>;
  health?: { n_regressed?: number; n_improved?: number } & Record<string, unknown>;
  cabling?: {
    assessed?: boolean;
    summary?: { n_added?: number; n_removed?: number; n_went_down?: number } & Record<string, unknown>;
  } & Record<string, unknown>;
  protocol_adjacencies?: ProtocolAdjacencyDelta;
  current_baseline?: CurrentBaselineGate;
  current_baseline_required?: boolean;
  provenance?: Record<string, unknown>;
  schema_compat?: Record<string, unknown>;
  comparison_admission?: ProtocolComparisonAdmission;
  change_intent?: CutoverChangeIntent;
  protocol_families?: ProtocolFamilyChangeSet;
  precert?: PrecertReceipt;
  cutover_gate?: CutoverGate;
  operator_evidence?: CutoverOperatorEvidence;
  comparison_receipt?: ProtocolReceiptEnvelope;
}

export type CampaignTrendVerdict =
  | "IMPROVING"
  | "REGRESSING"
  | "MIXED"
  | "FLAT"
  | "INSUFFICIENT"
  | "INDETERMINATE";

export interface CampaignTrendTrajectory {
  metric: string;
  first: number;
  last: number;
  delta: number;
  direction: "improving" | "worsening" | "flat" | string;
}

export interface CampaignAdjacentComparison {
  schema: "campaign_adjacent_comparison/1";
  index: number;
  from: string;
  to: string;
  before_snapshot_id: number;
  after_snapshot_id: number;
  before_label: string;
  after_label: string;
  /** Complete server-owned source_bound_cutover_comparison/1 document for this adjacent pair. */
  comparison: CompareResponse;
}

export interface CampaignAdjacentComparisonStatus {
  schema: "campaign_adjacent_comparison_set/1";
  status: "verified" | "not_verified" | "not_comparable";
  n_pairs_total: number;
  n_pairs_returned: number;
  complete: boolean;
  note: string;
}

/** GET /api/campaigns/{id}/trend. Direction-of-travel remains distinct from every canonical gate. */
export interface CampaignTrendResponse {
  verdict: CampaignTrendVerdict;
  verdict_note: string;
  trajectory: CampaignTrendTrajectory[];
  timeline?: Array<Record<string, unknown>>;
  steps?: Array<Record<string, unknown>>;
  not_comparable?: {
    lost: string[];
    never_measured: string[];
    disclosure_available?: boolean;
  };
  integrity?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  schema_compat?: Record<string, unknown>;
  protocol_adjacencies?: ProtocolAdjacencyDelta;
  current_baseline?: CurrentBaselineGate;
  adjacent_comparisons?: CampaignAdjacentComparison[];
  adjacent_comparison_status?: CampaignAdjacentComparisonStatus;
}

export interface ExecutionComparisonReceiptBody {
  schema: "execution_comparison_receipt/1";
  before_snapshot_id: number;
  after_snapshot_id: number;
  after_collected_at?: string;
  implementation_binding?: ExecutionLatestComparison["implementation_binding"];
  comparison: CompareResponse;
  receipt_sha256: string;
}

export interface StoredExecutionComparisonReceipt {
  id: number;
  execution_id: number;
  before_snapshot_id: number;
  after_snapshot_id: number;
  receipt_sha256: string;
  cutover_verdict: CutoverGateVerdict;
  created_at: string;
  receipt: ExecutionComparisonReceiptBody;
}

export interface ExecutionLatestComparison {
  schema: "execution_latest_comparison/1";
  receipt_id: number;
  receipt_sha256: string;
  before_snapshot_id: number;
  after_snapshot_id: number;
  after_collected_at?: string;
  implementation_binding?: {
    schema: "execution_implementation_binding/1";
    valid: boolean;
    n_steps: number;
    completed_at: string;
    steps_sha256: string;
    failures: string[];
  };
  cutover_gate: CutoverGate;
}

export interface ExecutionComparisonPolicy {
  schema: "execution_comparison_policy/1";
  canonical_gate_required: true;
  before_snapshot: ProtocolSourceBinding;
  /** Highest persisted snapshot id visible when this execution began. */
  snapshot_id_high_watermark?: number;
}

export interface ValidationCheck {
  device?: string;
  wave?: string;
  category: string;
  severity: string;
  check: string;
  command: string;
  expect: string;
  why?: string;
  evidence_state?: string;
  projection_custody?: string;
  source_key?: string;
  baseline_state?: string;
  baseline_blocker?: boolean;
}

export interface CutoverWave {
  group: string;
  order: number;
  readiness: string;
  gate: string;
  strategy: string;
  n_switches: number;
  switches: string[];
  make_before_break: string[];
  hard_cutover: string[];
  endpoints: number;
  hard_cutover_endpoints: number;
  est_window_minutes: number;
  est_window_label: string;
  sequence_note: string;
  gateways: string[];
  spanning_vlans: Array<[number, string, number]>;
  blast_radius: { host: string; severity: string; stranded: number; vlans_impacted: number; detail: string } | null;
  keystones: string[];
  n_fail: number;
  n_warn: number;
  blockers: Array<{ check: string; status: string; note: string; phase: string }>;
  current_baseline?: CurrentBaselineGate;
  baseline_blockers?: CurrentBaselineBlocker[];
  critical_crosslayer: Array<{ id: string; title: string; layers: string; recommendation: string }>;
  remediation: Array<{ device: string; title: string; category: string; severity: string; why: string }>;
  validation: ValidationCheck[];
  run_of_show: Array<{ phase: string; action: string }>;
}

export interface ExecStep {
  phase: string;
  action: string;
  status: "pending" | "done" | "skipped";
  at: string | null;
  by: string;
  note: string;
}

export interface ExecCheck {
  device?: string;
  wave?: string;
  category: string;
  severity: string;
  check: string;
  command: string;
  expect: string;
  why?: string;
  evidence_state?: string;
  projection_custody?: string;
  source_key?: string;
  baseline_state?: string;
  baseline_blocker?: boolean;
  result: "pending" | "pass" | "fail" | "na";
  observed: string;
  at: string | null;
  by: string;
}

export interface ExecWave {
  group: string;
  order: number;
  gate: string;
  strategy: string;
  n_switches: number;
  switches: string[];
  endpoints: number;
  hard_cutover_endpoints: number;
  est_window_minutes: number;
  est_window_label: string;
  blockers: Array<{ check: string; status: string; note: string; phase: string }>;
  current_baseline?: CurrentBaselineGate;
  baseline_blockers?: CurrentBaselineBlocker[];
  steps: ExecStep[];
  checks: ExecCheck[];
  closeout: { decision: string | null; at: string | null; by: string; note: string };
}

export interface ExecutionState {
  id: number;
  snapshot_id: number;
  label: string;
  operator: string;
  status: "in_progress" | "completed" | "aborted";
  outcome: string | null;
  started_at: string;
  ended_at: string | null;
  execution_schema?: "cutover_execution/2";
  comparison_policy?: ExecutionComparisonPolicy;
  latest_comparison?: ExecutionLatestComparison;
  comparison_receipts?: StoredExecutionComparisonReceipt[];
  plan_summary: CutoverPlan["summary"];
  /** Full start-snapshot blocker receipt frozen when the execution record is created. */
  baseline_blockers?: CurrentBaselineBlocker[];
  /** Explicit occurrence-preserving subset that could not be assigned to an execution wave. */
  unbound_baseline_blockers?: CurrentBaselineBlocker[];
  waves: ExecWave[];
  events: Array<{ at: string; kind: string; wave: string; text: string; by: string }>;
  progress: {
    n_steps: number;
    n_steps_done: number;
    n_steps_skipped: number;
    pct: number;
    checks: Record<"pending" | "pass" | "fail" | "na", number>;
    n_deviations: number;
    elapsed_seconds: number;
    planned_window_minutes: number;
    waves: Array<{ group: string; state: string; n_steps: number; n_actioned: number }>;
  };
}

export interface GateRecord {
  wave: string;
  gate: string;
  decision: string; // go | no-go | slipped (pending rows are not stored)
  signed_by: string;
  note: string;
  decided_at: string;
  // Coverage-honest disclosure (backend gates.annotate_out_of_order, PR #376): this sign-off was
  // recorded before an upstream cadence gate was itself GO. Disclosed, never blocked — the sign-off
  // still persists. `out_of_order_upstream` names the first unmet upstream gate key.
  out_of_order?: boolean;
  out_of_order_upstream?: string;
}

export interface GateBoardData {
  cadence: Array<{ key: string; label: string; when: string }>;
  waves: string[];
  records: GateRecord[];
}

export interface IngestReport {
  n_archive_files: number;
  n_device_dirs: number;
  devices: string[];
  skipped_dirs: string[];
  devices_json: "bundled" | "synthesized";
  engine_seconds: number;
  engine_log_tail: string;
  verification: SnapshotVerification;
}

export interface ExecutionMeta {
  id: number;
  snapshot_id: number;
  label: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  comparison_required?: boolean;
  latest_comparison?: ExecutionLatestComparison;
}

export interface CutoverPlan {
  summary: {
    verdict: string;
    n_waves: number;
    n_devices: number;
    n_endpoints: number;
    n_make_before_break: number;
    n_hard_cutover: number;
    hard_cutover_endpoints: number;
    est_window_minutes: number;
    est_window_label: string;
    gates: Record<string, number>;
    statement: string;
    methodology?: string[];
    current_baseline?: CurrentBaselineGate;
    n_baseline_blockers?: number;
    n_unbound_baseline_blockers?: number;
    baseline_blockers_capped?: boolean;
  };
  waves: CutoverWave[];
  baseline_blockers?: CurrentBaselineBlocker[];
}

// V3.23.163: the senior-engineer design review (engine compute_architecture_review — the same
// object behind the DOCX report, the workbook scorecard sheet and the explorer Review mode).
export type ArchVerdict = "conforms" | "advisory" | "deviation" | "critical" | "not-assessable";

export interface ArchCheck {
  id: string;
  domain: string;
  title: string;
  verdict: ArchVerdict;
  observed: string;
  implication: string;
  recommendation: string;
  reference: string;
  evidence: string[];
}

export interface ArchDomain {
  key: string;
  verdict: ArchVerdict;
  score_pct: number | null;
  checks: string[];
}

export interface ArchAction {
  rank: number;
  id: string;
  domain: string;
  verdict: ArchVerdict;
  action: string;
  evidence: string[];
}

export interface ArchReview {
  domains: ArchDomain[];
  checks: ArchCheck[];
  top_actions: ArchAction[];
  summary: {
    n_checks: number;
    n_assessable: number;
    n_conforms: number;
    n_advisory: number;
    n_deviation: number;
    n_critical: number;
    n_not_assessable: number;
    score_pct: number | null;
    grade: string;
    grade_label: string;
    statement: string;
  };
}

// The CCDE-grounded target-state DESIGN BLUEPRINT (engine compute_design_blueprint — the SAME object the
// HLD/LLD DOCX and the explorer ✎ Design mode carry). POST /design with a requirements register re-scores.
// Architecture-coverage SSOT (engine compute_architecture_coverage — the SAME map the explorer ✎ Design view
// renders): which architecture CLASSES were observed vs not, across both ingestion channels (ssh / json).
export interface ArchitectureCoverageClass {
  key: string; label: string; channel: string; detectors: string[];
  observed: boolean; n_hosts: number; hosts: string[]; status: string; findings: string[];
}
export interface ArchitectureCoverage {
  classes: ArchitectureCoverageClass[];
  summary: {
    n_classes: number; n_observed: number; n_with_findings: number; n_clean: number; n_not_observed: number;
    by_channel: { ssh: number; json: number };
  };
}

// Domain skill-packs (Phase-3 / D6) engaged for a snapshot — selected by the engine SSOT (select_packs)
// from the SAME architecture_coverage above. A pack loads IFF one of its classes was OBSERVED; the note
// states the coverage-honest empty case. Never re-derived in JS (the selection engine is authoritative).
export interface DomainPack {
  pack: string; title: string; doc: string; triggered_by: string[]; with_findings: string[];
}
export interface DomainPacks {
  selected: DomainPack[]; loaded: string[]; note: string;
}

export interface DesignDecision {
  id: string;
  title: string;
  domain: string;
  priority: string;
  status: string;
  confidence: string;
  driver: string;
  evidence: { summary: string; count: number; devices: string[]; fields: string[] };
  principle: { id: string; title: string; citation: string };
  recommended_action: string;
  alternatives: string;
  tradeoffs: string;
  axes: string[];
  requirements_needed: string[];
  effective_priority?: number;
}
export interface DesignAxisScore {
  axis: string;
  label: string;
  score: number | null;
  posture: string;
  evidence: string;
  target_weight?: number;
}
export interface DesignDimension {
  area: string; current: string; target: string; rationale: string; confidence: string;
  drivers?: string[]; requirement_needed?: string;
}
export interface DesignTargetState {
  dimensions: DesignDimension[];
  replacement_bom: {
    replace_now: [string, number][];
    refresh_soon: [string, number][];
    undetermined?: [string, number][];
    n_replace: number;
    n_refresh: number;
    n_near?: number;
    n_past_eos?: number;
    n_undetermined?: number;
    n_not_assessed?: number;
    note: string;
  };
  addressing_plan: {
    status: string; mode?: string; observed_vlans?: number; requirement_needed?: string; note: string;
    n_census_vlans?: number; n_unsizable?: number;
    supernet?: string; subnets?: { vlan: number; hosts: number; subnet: string; note?: string; zone?: string }[];
    zones?: { zone: string; summary: string; n_vlans: number }[]; n_allocated?: number; n_overflow?: number;
  };
  wave_plan: {
    waves: { wave: number; kind: string; n_switches: number; switches: string[]; source_groups: number[] }[];
    n_waves: number; wave_cap: number; n_move_groups: number; largest_group: number; n_subdivided_groups: number; note: string;
  };
  aci_move_groups?: {
    groups: { tenant: string; n_vrfs: number; n_bds: number; n_epgs: number; vrfs: string[]; epgs: string[]; unenforced_vrfs: string[]; segmentation_gap: boolean }[];
    n_tenants: number; n_epgs: number; n_segmentation_gaps: number; note: string;
  };
  segmentation_plan?: { observed: string; principle?: string; status: string; target: string;
    requirement_needed?: string; target_zones?: string[] };
  scope_note?: string;
}
export interface DesignBlueprint {
  decisions: DesignDecision[];
  tradeoff_scorecard: DesignAxisScore[];
  target_state?: DesignTargetState;
  requirements_model: {
    fields: { key: string; label: string; options?: string[]; example?: unknown; value: unknown }[];
    open_questions: { id: string; title: string; needs: string[] }[];
    provided: boolean;
    note: string;
  };
  methodology: string;
  axes: { key: string; label: string; intent: string }[];
  summary: {
    n_decisions: number;
    n_recommended: number;
    n_needs_requirement: number;
    n_critical: number;
    by_domain: Record<string, number>;
    requirements_provided: boolean;
    headline: string;
  };
  coverage: { inventory: number; collected: number; not_collected: number; caveat: string };
}

// Design-driven NRFU/ATP acceptance-test checklist (GET /api/snapshots/{id}/design/nrfu).
// One item per recommended design decision; traceable to the CCDE principle + affected devices.
export interface DesignNrfuItem {
  decision_id: string;
  title: string;
  priority: string;
  phase: "pre-cutover" | "post-cutover-functional" | "post-cutover-operational";
  description: string;
  pass_criteria: string;
  setup: string;
  devices: string[];
  principle_citation: string;
}
export interface DesignNrfu {
  items: DesignNrfuItem[];
  n_items: number;
  note: string;
}

// The unified CAUSAL FLOW model (engine compute_causal_flows — the SAME normalization the explorer's
// Causal Flow mode renders). GET /api/snapshots/{id}/causal_flows. Every finding family as one
// trigger -> mechanism -> impact -> mitigation story; cross-layer compounds carry shape "bowtie".
export interface CausalFlowItem {
  key: string;
  family: string;
  family_label: string;
  icon: string;
  title: string;
  severity: string;       // normalised: Critical | High | Medium | Low | Info
  sev_tok: string;        // crit | risk | watch | accent
  trigger: string;
  mechanism: string;
  impact: string;
  mitigation: string;
  hosts: string[];
  blast: number;          // magnitude -> Sankey connector width
  blast_unit: string;     // the unit actually matched (endpoints | devices | …) — coverage-honest
  shape: "linear" | "bowtie";
  evidence: {
    summary?: string; count?: number; devices?: string[]; fields?: string[];
    citation?: string; layers?: string; rank?: number; wave?: string;
    // W3-2 (NotebookLM): coverage-honest grounding, stamped by the engine SSOT (causal.evidence_precision /
    // evidence_grounding). precision = BLOCK | DEVICE | FLEET (never LINE without raw show-text); grounded=false
    // + dangling[] flag a citation whose snapshot path no longer resolves.
    precision?: "BLOCK" | "DEVICE" | "FLEET"; grounded?: boolean; dangling?: string[];
  };
  threats?: string[];     // bowtie: the contributing causes
  top_event?: string;
  consequence?: string;
  confidence?: string;    // design decisions
  alternatives?: string;
  tradeoffs?: string;
  axes?: string[];
}
export interface CausalFamily { key: string; label: string; icon: string; n: number; crit: number }
export interface CausalFlows {
  flows: CausalFlowItem[];
  families: CausalFamily[];
  summary: { n_flows: number; n_families: number; n_critical: number; by_severity: Record<string, number> };
}

// EDA-style physical CABLE MAP (engine compute_cable_map — the SAME node/port/cable SSOT the explorer's
// Cable Map mode renders). GET /api/snapshots/{id}/cable_map. Role-tiered lanes; cable op-status is
// DERIVED from interface state — 'unknown' is the coverage-honest [NOT OBSERVED] neutral (uncollected).
export type CableOp = "up" | "down" | "unknown";
export interface CableMapPort { name: string; peer: string; peer_port: string; op_status: CableOp; is_pc: boolean }
export interface CableMapNode {
  host: string; role: string; tier: number; order: number;
  collected: boolean; op_status: CableOp; badges: string[]; ports: CableMapPort[];
  kind: string;   // device | switch | router | firewall | ap | phone | endpoint | unknown (platform-evidence based)
}
export interface CableMapCable {
  a: string; a_port: string; b: string; b_port: string;
  is_pc: boolean; members: Array<{ a_port: string; b_port: string }>; op_status: CableOp; confirmation: string;
  speed: string;  // verbatim from `show interface status` (e.g. "1000", "a-1000", "10G")
}
export interface CableMap {
  nodes: CableMapNode[];
  cables: CableMapCable[];
  tiers: string[][];
  summary: { n_nodes: number; n_cables: number; n_tiers: number; op: Record<CableOp, number> };
}

/** A failed API call, carrying the HTTP status so a caller can tell the backend's guard responses
 *  apart instead of collapsing them all into one opaque string (audit FE-11). The hardened backend
 *  answers 403 (cross-site write / compute-heavy GET refused), 413 (declared body over the JSON
 *  ceiling), 422 (a per-field length cap), 409 (the run/wave is already closed) and 503 + Retry-After
 *  (the generation-concurrency cap shed the request) — a 503 shed is transient and worth retrying,
 *  a 404 is not, and nothing downstream could distinguish them from `new Error(detail)`.
 *  `.message` is unchanged for the plain-string `detail` case, which is every hand-written
 *  HTTPException in webapp/backend/app.py. */
export class ApiError extends Error {
  readonly status: number;
  readonly retryAfter: number | null;
  constructor(message: string, status: number, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
  /** The generation cap (503 + Retry-After) and a transient upstream — safe to offer a retry. */
  get retryable(): boolean {
    return this.status === 503 || this.status === 429;
  }
}

/** FastAPI's RequestValidationError body is `{"detail": [{loc, msg, type}, ...]}`, NOT a string —
 *  the per-field caps (_LEN_NOTE / _LEN_NAME / _LEN_TOKEN in app.py) all reject through it. Raw
 *  JSON.stringify put `[{"type":"string_too_long","loc":["body","note"],…}]` in the war-room toast,
 *  which tells an engineer nothing about which field to shorten. */
function detailToMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail || null;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d: any) => {
        if (typeof d === "string") return d;
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        const m = typeof d?.msg === "string" ? d.msg : "";
        return loc && m ? `${loc}: ${m}` : m || loc || null;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return null;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      const d = detailToMessage(b?.detail);
      if (d) msg = d;
    } catch {
      /* ignore */
    }
    const ra = Number(r.headers?.get?.("retry-after"));
    throw new ApiError(msg, r.status, Number.isFinite(ra) && ra > 0 ? ra : null);
  }
  return (r.status === 204 ? (null as T) : await r.json()) as T;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<{ status: string; sample_available: boolean }>(r)),
  authenticate: (token: string) =>
    fetch("/api/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).then((r) => j<null>(r)),
  logout: () => fetch("/api/session", { method: "DELETE" }).then((r) => j<null>(r)),
  meta: () => fetch("/api/meta").then((r) => j<Meta>(r)),

  listCampaigns: () => fetch("/api/campaigns").then((r) => j<Campaign[]>(r)),
  getCampaign: (id: number) => fetch(`/api/campaigns/${id}`).then((r) => j<Campaign>(r)),
  createCampaign: (name: string, description = "") =>
    post<Campaign>("/api/campaigns", { name, description }),
  deleteCampaign: (id: number) => fetch(`/api/campaigns/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  trend: (id: number) => fetch(`/api/campaigns/${id}/trend`).then((r) => j<CampaignTrendResponse>(r)),
  getGates: (id: number) => fetch(`/api/campaigns/${id}/gates`).then((r) => j<GateBoardData>(r)),
  setGate: (id: number, wave: string, gate: string, decision: string, signed_by = "", note = "") =>
    post<{ records: GateRecord[] }>(`/api/campaigns/${id}/gates`, { wave, gate, decision, signed_by, note }),

  uploadSnapshot: (campaignId: number, file: File, label: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("label", label);
    return fetch(`/api/campaigns/${campaignId}/snapshots`, { method: "POST", body: fd }).then((r) =>
      j<SnapshotMeta>(r),
    );
  },
  ingestCollection: (campaignId: number, file: File, label: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("label", label);
    return fetch(`/api/campaigns/${campaignId}/ingest`, { method: "POST", body: fd }).then((r) =>
      j<SnapshotMeta & { ingest: IngestReport }>(r),
    );
  },
  // Folder ingest (ADR-0004 P1): the path names a SERVER-local directory, so this is a plain JSON
  // POST — no file leaves the machine (the portable-app case: collection and app share a disk).
  ingestFolder: (campaignId: number, path: string, label: string) =>
    post<SnapshotMeta & { ingest: IngestReport }>(`/api/campaigns/${campaignId}/ingest-folder`, { path, label }),
  getSnapshot: (id: number) => fetch(`/api/snapshots/${id}`).then((r) => j<SnapshotMeta>(r)),
  section: (id: number, name: string) =>
    fetch(`/api/snapshots/${id}/section/${name}`).then((r) => j<{ section: string; data: any }>(r)),
  protocolAssurance: (id: number) =>
    fetch(`/api/snapshots/${id}/section/protocol_assurance`).then((r) => j<ProtocolAssuranceSection>(r)),
  protocolAssuranceExportUrl: (id: number) =>
    `/api/snapshots/${id}/protocol-assurance/export`,
  deleteSnapshot: (id: number) => fetch(`/api/snapshots/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  graph: (id: number) =>
    fetch(`/api/snapshots/${id}/graph`).then((r) => j<TopologyGraphData>(r)),
  cutover: (id: number) => fetch(`/api/snapshots/${id}/cutover`).then((r) => j<CutoverPlan>(r)),
  archreview: (id: number) => fetch(`/api/snapshots/${id}/archreview`).then((r) => j<ArchReview>(r)),
  design: (id: number) => fetch(`/api/snapshots/${id}/design`).then((r) => j<DesignBlueprint>(r)),
  architectureCoverage: (id: number) =>
    fetch(`/api/snapshots/${id}/architecture_coverage`).then((r) => j<ArchitectureCoverage>(r)),
  domainPacks: (id: number) =>
    fetch(`/api/snapshots/${id}/domain_packs`).then((r) => j<DomainPacks>(r)),
  designOverlay: (id: number, requirements: Record<string, unknown>) =>
    post<DesignBlueprint>(`/api/snapshots/${id}/design`, requirements),
  designNrfu: (id: number) => fetch(`/api/snapshots/${id}/design/nrfu`).then((r) => j<DesignNrfu>(r)),
  designNrfuOverlay: (id: number, requirements: Record<string, unknown>) =>
    post<DesignNrfu>(`/api/snapshots/${id}/design/nrfu`, requirements),
  causalFlows: (id: number) => fetch(`/api/snapshots/${id}/causal_flows`).then((r) => j<CausalFlows>(r)),
  cableMap: (id: number) => fetch(`/api/snapshots/${id}/cable_map`).then((r) => j<CableMap>(r)),
  explorerUrl: (id: number) => `/api/snapshots/${id}/explorer`,
  deliverableUrl: (id: number, kind: string) => `/api/snapshots/${id}/deliverable/${kind}`,
  compare: (oldId: number, newId: number, changeIntent?: CutoverChangeIntentInput) =>
    post<CompareResponse>("/api/compare", {
      old_id: oldId,
      new_id: newId,
      ...(changeIntent ? { change_intent: changeIntent } : {}),
    }),

  seedDemo: () => fetch("/api/demo/seed", { method: "POST" }).then((r) => j<{ campaign: Campaign; snapshot: SnapshotMeta }>(r)),

  // -- cutover execution runs (war room) --
  startExecution: (snapId: number, label = "", operator = "") =>
    post<ExecutionState>(`/api/snapshots/${snapId}/executions`, { label, operator }),
  listExecutions: (snapId: number) =>
    fetch(`/api/snapshots/${snapId}/executions`).then((r) => j<ExecutionMeta[]>(r)),
  getExecution: (id: number) => fetch(`/api/executions/${id}`).then((r) => j<ExecutionState>(r)),
  compareExecution: (id: number, afterSnapshotId: number, changeIntent?: CutoverChangeIntentInput) =>
    post<ExecutionState>(`/api/executions/${id}/compare`, {
      after_snapshot_id: afterSnapshotId,
      ...(changeIntent ? { change_intent: changeIntent } : {}),
    }),
  execStep: (id: number, wave: string, index: number, status: string, note = "", operator = "") =>
    post<ExecutionState>(`/api/executions/${id}/step`, { wave, index, status, note, operator }),
  execCheck: (id: number, wave: string, index: number, result: string, observed = "", operator = "") =>
    post<ExecutionState>(`/api/executions/${id}/check`, { wave, index, result, observed, operator }),
  execCloseout: (id: number, wave: string, decision: string, note = "", operator = "") =>
    post<ExecutionState>(`/api/executions/${id}/closeout`, { wave, decision, note, operator }),
  execEvent: (id: number, kind: string, text: string, wave = "", operator = "") =>
    post<ExecutionState>(`/api/executions/${id}/event`, { kind, text, wave, operator }),
  execFinish: (id: number, status: "completed" | "aborted", note = "", operator = "") =>
    post<ExecutionState>(`/api/executions/${id}/finish`, { status, note, operator }),
  executionReportUrl: (id: number) => `/api/executions/${id}/report`,
  deleteExecution: (id: number) => fetch(`/api/executions/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
};

function post<T>(url: string, body: unknown): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => j<T>(r));
}

// shared colour helpers (mirror the engine vocabulary -> CSS tokens)
export const sevColor = (s: string) => `var(--sev-${s.replace(/\s+/g, "")}, var(--text-faint))`;
export const sevSoft = (s: string) => `var(--sev-${s.replace(/\s+/g, "")}-soft, var(--surface-3))`;
export const bandColor = (b: string) => `var(--band-${b.replace(/\s+/g, "")}, var(--text-faint))`;
export const readyColor = (r: string) => `var(--ready-${r.replace(/\s+/g, "")}, var(--text-faint))`;
export const gateColor = (g: string) => `var(--gate-${g.replace(/[\s-]+/g, "")}, var(--text-faint))`;
