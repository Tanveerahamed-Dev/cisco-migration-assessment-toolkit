export type CapabilityState =
  | "current"
  | "partial"
  | "missing"
  | "gated"
  | "excluded"
  | "unknown";

export type OwnerRef = {
  id: string;
  path: string;
  symbol?: string;
  kind: string;
  claim_scope: string;
};

export type CoreOutcome = {
  id: string;
  title: string;
  success_signal: string;
};

export type CoreBaselineValue =
  | string
  | string[]
  | Record<string, string | number | string[]>;

export type Capability = {
  id: string;
  title: string;
  state: CapabilityState;
  current_scope: string;
  owner_refs?: string[];
  gap_refs?: string[];
  traffic_plane_refs?: string[];
  content_role?: "advisory";
  mutates_assessment_truth?: false;
};

export type CapabilityDomain = {
  id: string;
  entity_role: "reference";
  entries: Capability[];
};

export type CapabilityEntryContract = {
  current: string;
  partial: string;
  incomplete: string;
  catalog_presence: string;
};

export type CapabilityCatalog = {
  schema_version: "1.0.0";
  id: string;
  catalog_version: string;
  kind: "closed-world-capability-catalog";
  denominator_rule: string;
  entry_contract: CapabilityEntryContract;
  domains: CapabilityDomain[];
};

export type ProtocolDepthState = "covered" | "partial" | "missing";

export type ProtocolDepthStageId =
  | "collection"
  | "parsing"
  | "normalization"
  | "assessment"
  | "design-advice"
  | "simulation"
  | "validation"
  | "output";

export type ProtocolDepthCell = {
  state: ProtocolDepthState;
  prerequisite: string;
  boundary: string;
  witness_refs: string[];
};

export type ProtocolDepthStage = {
  id: ProtocolDepthStageId;
  order: number;
  label: string;
  question: string;
  non_proof: string;
};

export type ProtocolDepthWitness = {
  id: string;
  path: string;
  symbols: string[];
  proves: string;
  test_refs: string[];
};

export type ProtocolDepthFamily = {
  id: string;
  label: string;
  health_label: string;
  capability_ref: string;
  evidence_inputs: Array<{
    command: string;
    platforms: Array<"IOS" | "NX-OS">;
  }>;
  assessable_when: string;
  advice_states: string[];
  validation_scope: string;
  cells: Record<ProtocolDepthStageId, ProtocolDepthCell>;
  limitations: string[];
  gap_refs: string[];
};

export type ProtocolDepthModel = {
  schema_version: "1.0.0";
  id: "protocol-depth.eight-family-runtime";
  kind: "source-bound-derived-view";
  authority: string;
  denominator: {
    baseline_ref: "baseline.protocol.health";
    catalog_domain_ref: "domain.protocols";
    catalog_cell_count: number;
    health_family_count: 7;
    family_count: 8;
    stage_count: 8;
    cell_count: 64;
    scope_rule: string;
  };
  state_contract: Record<ProtocolDepthState, string>;
  stages: ProtocolDepthStage[];
  witnesses: ProtocolDepthWitness[];
  families: ProtocolDepthFamily[];
};

export type Gap = {
  id: string;
  title: string;
  problem: string;
  disposition: string;
  priority: string;
  next_actions: string[];
  acceptance_evidence: string[];
  owner_role: string;
};

export type Opportunity = {
  id: string;
  title: string;
  gap_refs: string[];
  horizon: string;
  axes: Record<string, number>;
  axis_notes: string;
};

export type Decision = {
  id: string;
  title: string;
  status: string;
  authority: string;
  options: string[];
  current_recommendation: string;
  evidence_needed: string[];
  gap_refs: string[];
};

export type Invariant = {
  id: string;
  statement: string;
  owner_refs: string[];
  formal_rule: string;
  scope: string[];
  enforcement_points: string[];
  supporting_tests: string[];
  counterexample_test: string;
  exceptions_allowed: string[];
  residual_risk: string;
  independent_verifier: string;
};

export type LabDefinition = {
  execution_state: "definition_only";
  deterministic_inputs: string[];
  expected_observations: string[];
  reset_rule: string;
  source_binding: string;
};

export type Lab = {
  id: string;
  number: number;
  title: string;
  content_role: string;
  mutates_assessment_truth: boolean;
  underlying_support_state: CapabilityState;
  objective: string;
  interaction: string;
  data_policy: string;
  proves: string;
  does_not_prove: string;
  owner_refs: string[];
  gap_refs: string[];
  deterministic_definition: LabDefinition;
};

export type DeliveryGovernance = {
  schema_version: string;
  gaps: Gap[];
  opportunity_axes: Array<{ id: string; range: string; five_means: string }>;
  opportunity_portfolio: { ranking_rule: string; items: Opportunity[] };
  decision_queue: Decision[];
  invariants: Invariant[];
  quality_scenarios: Array<Record<string, unknown>>;
  labs: Lab[];
};

export type CoreModel = {
  schema_version: "1.0.0";
  id: string;
  catalog_version: string;
  title: string;
  as_of: string;
  scope: string;
  truth_contract: {
    declared_scope_promise: string;
    open_world_promise: string;
    support_rule: string;
    partial_rule: string;
    training_rule: string;
    client_data_rule: string;
  };
  controlled_states: Array<{
    id: string;
    value: CapabilityState;
    meaning: string;
  }>;
  owners: OwnerRef[];
  current_baseline: Array<{
    id: string;
    statement: string;
    value: CoreBaselineValue;
    owner_refs: string[];
  }>;
  outcomes: CoreOutcome[];
  maturity_model: Array<{
    id: string;
    level: number;
    label: string;
    exit_criteria: string;
  }>;
  current_maturity: Array<{
    id: string;
    dimension: string;
    level: number;
    state: CapabilityState;
    basis: string;
    owner_refs: string[];
    gap_refs?: string[];
  }>;
  non_goals: Array<{ id: string; statement: string; owner_refs?: string[] }>;
  lifecycle_stages: Array<{
    id: string;
    order: number;
    label: string;
    question: string;
  }>;
  digital_thread: {
    id: string;
    abstention_rule: string;
    stages: Array<{
      id: string;
      order: number;
      label: string;
      entity_type: string;
      question: string;
      owner_refs: string[];
      abstention: string;
      relation_to_next: string | null;
    }>;
  };
  system_architecture: {
    id: string;
    planes: Array<{
      id: string;
      order: number;
      title: string;
      purpose: string;
      inputs: string[];
      outputs: string[];
      owner_refs: string[];
    }>;
    flow: Array<{ from: string; to: string; contract: string }>;
  };
  traffic_model: {
    id: string;
    warning: string;
    planes: Array<{
      id: string;
      order: number;
      title: string;
      questions: string[];
      state: CapabilityState;
      current_scope: string;
      owner_refs?: string[];
      gap_refs?: string[];
    }>;
  };
  domain_registry: Array<{ id: string; title: string }>;
};

export type HorizonMaturity =
  | "research"
  | "draft"
  | "standardized"
  | "shipping"
  | "observed-in-estate"
  | "mainstream"
  | "unknown";

export type HorizonDisposition =
  | "adopt-candidate"
  | "watch"
  | "defer"
  | "reject"
  | "out-of-scope"
  | "unknown";

export type HorizonIntakeStep = {
  id: string;
  order: number;
  action: string;
};

export type HorizonReviewTrigger = {
  id: string;
  event: string;
};

export type HorizonCadence = {
  scheduled: string;
  event_driven: string;
  staleness_rule: string;
  independent_challenge: string;
};

export type HorizonMetric = {
  id: string;
  definition: string;
  target: string;
  warning: string;
};

export type HorizonView = {
  id: string;
  label: string;
  shows: string;
};

export type HorizonWatchFamily = {
  id: string;
  name: string;
  source_url: string;
  additional_urls?: string[];
  authority_scope: string;
  topics: string[];
  review_cadence: string;
  content_role: "advisory";
  engine_ingestion: string;
};

export type HorizonSignal = {
  id: string;
  theme: string;
  title: string;
  first_seen: string;
  last_reviewed: string;
  maturity: HorizonMaturity;
  disposition: HorizonDisposition;
  source_refs: string[];
  adoption_evidence: string;
  affected_capability_refs: string[];
  business_relevance: string;
  risk_opportunity: string;
  current_coverage: string;
  uncertainty: string;
  rationale: string;
  owner_role: string;
  next_review_rule: string;
  promotion_criteria: string[];
  privacy_trust_implications: string;
  content_role: "advisory";
  support_claim: "none";
};

export type HorizonModel = {
  schema_version: "1.0.0";
  id: string;
  catalog_version: string;
  kind: "open-world-horizon-register";
  content_role: "advisory";
  support_claim: "none";
  mutates_assessment_truth: false;
  promise: string;
  separation_contract: string[];
  maturity_levels: HorizonMaturity[];
  dispositions: HorizonDisposition[];
  intake_pipeline: HorizonIntakeStep[];
  review_triggers: HorizonReviewTrigger[];
  cadence: HorizonCadence;
  metrics: HorizonMetric[];
  ui_views: HorizonView[];
  watch_families: HorizonWatchFamily[];
  signals: HorizonSignal[];
};
