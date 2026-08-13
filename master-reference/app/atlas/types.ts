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

export type Capability = {
  id: string;
  title: string;
  state: CapabilityState;
  current_scope: string;
  owner_refs?: string[];
  gap_refs?: string[];
};

export type CapabilityDomain = {
  id: string;
  entries: Capability[];
};

export type CapabilityCatalog = {
  schema_version: string;
  id: string;
  catalog_version: string;
  denominator_rule: string;
  domains: CapabilityDomain[];
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
  schema_version: string;
  id: string;
  catalog_version: string;
  title: string;
  as_of: string;
  scope: string;
  truth_contract: Record<string, string>;
  owners: OwnerRef[];
  current_baseline: Array<{
    id: string;
    statement: string;
    value: unknown;
    owner_refs: string[];
  }>;
  outcomes: Array<{ id: string; title: string; success_signal: string }>;
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
