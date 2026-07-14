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
  lifecycle: { past_eos?: number | string; near_eos?: number | string; past_ldos?: number | string };
  sections: Array<{ key: string; label: string; count: number }>;
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
}

export interface Meta {
  engine_schema: string;
  severity_order: string[];
  bands: string[];
  section_labels: Array<{ key: string; label: string }>;
  deliverables: Deliverable[];
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
  critical_crosslayer: Array<{ id: string; title: string; layers: string; recommendation: string }>;
  remediation: Array<{ device: string; title: string; category: string; severity: string; why: string }>;
  validation: Array<{ category: string; severity: string; check: string; command: string; expect: string }>;
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
  category: string;
  severity: string;
  check: string;
  command: string;
  expect: string;
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
  plan_summary: CutoverPlan["summary"];
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
}

export interface ExecutionMeta {
  id: number;
  snapshot_id: number;
  label: string;
  status: string;
  started_at: string;
  ended_at: string | null;
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
  };
  waves: CutoverWave[];
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
  replacement_bom: { replace_now: [string, number][]; refresh_soon: [string, number][]; n_replace: number; n_refresh: number; note: string };
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

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return (r.status === 204 ? (null as T) : await r.json()) as T;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<{ status: string; sample_available: boolean }>(r)),
  meta: () => fetch("/api/meta").then((r) => j<Meta>(r)),

  listCampaigns: () => fetch("/api/campaigns").then((r) => j<Campaign[]>(r)),
  getCampaign: (id: number) => fetch(`/api/campaigns/${id}`).then((r) => j<Campaign>(r)),
  createCampaign: (name: string, description = "") =>
    post<Campaign>("/api/campaigns", { name, description }),
  deleteCampaign: (id: number) => fetch(`/api/campaigns/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  trend: (id: number) => fetch(`/api/campaigns/${id}/trend`).then((r) => j<any>(r)),
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
  getSnapshot: (id: number) => fetch(`/api/snapshots/${id}`).then((r) => j<SnapshotMeta>(r)),
  section: (id: number, name: string) =>
    fetch(`/api/snapshots/${id}/section/${name}`).then((r) => j<{ section: string; data: any }>(r)),
  deleteSnapshot: (id: number) => fetch(`/api/snapshots/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  graph: (id: number) =>
    fetch(`/api/snapshots/${id}/graph`).then((r) => j<{ nodes: any[]; edges: any[] }>(r)),
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
  compare: (oldId: number, newId: number) => post<any>("/api/compare", { old_id: oldId, new_id: newId }),

  seedDemo: () => fetch("/api/demo/seed", { method: "POST" }).then((r) => j<{ campaign: Campaign; snapshot: SnapshotMeta }>(r)),

  // -- cutover execution runs (war room) --
  startExecution: (snapId: number, label = "", operator = "") =>
    post<ExecutionState>(`/api/snapshots/${snapId}/executions`, { label, operator }),
  listExecutions: (snapId: number) =>
    fetch(`/api/snapshots/${snapId}/executions`).then((r) => j<ExecutionMeta[]>(r)),
  getExecution: (id: number) => fetch(`/api/executions/${id}`).then((r) => j<ExecutionState>(r)),
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
