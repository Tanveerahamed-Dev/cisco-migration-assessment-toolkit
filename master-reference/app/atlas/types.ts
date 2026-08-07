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
  domain_ref: string;
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

export type HorizonModel = {
  schema_version: string;
  promise: string;
  watch_families: Array<{
    id: string;
    name: string;
    source_url: string;
    authority_scope: string;
    topics: string[];
    review_cadence: string;
    content_role: string;
    engine_ingestion: string;
  }>;
  signals: Array<{
    id: string;
    theme: string;
    title: string;
    maturity: string;
    disposition: string;
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
    content_role: string;
    support_claim: string;
  }>;
};
