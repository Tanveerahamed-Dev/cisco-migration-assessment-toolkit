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
export interface DesignBlueprint {
  decisions: DesignDecision[];
  tradeoff_scorecard: DesignAxisScore[];
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
  designOverlay: (id: number, requirements: Record<string, unknown>) =>
    post<DesignBlueprint>(`/api/snapshots/${id}/design`, requirements),
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
