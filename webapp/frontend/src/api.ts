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

export interface Meta {
  engine_schema: string;
  severity_order: string[];
  bands: string[];
  section_labels: Array<{ key: string; label: string }>;
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
    fetch("/api/campaigns", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, description }),
    }).then((r) => j<Campaign>(r)),
  deleteCampaign: (id: number) => fetch(`/api/campaigns/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  trend: (id: number) => fetch(`/api/campaigns/${id}/trend`).then((r) => j<any>(r)),

  uploadSnapshot: (campaignId: number, file: File, label: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("label", label);
    return fetch(`/api/campaigns/${campaignId}/snapshots`, { method: "POST", body: fd }).then((r) =>
      j<SnapshotMeta>(r),
    );
  },
  getSnapshot: (id: number) => fetch(`/api/snapshots/${id}`).then((r) => j<SnapshotMeta>(r)),
  section: (id: number, name: string) =>
    fetch(`/api/snapshots/${id}/section/${name}`).then((r) => j<{ section: string; data: any }>(r)),
  deleteSnapshot: (id: number) => fetch(`/api/snapshots/${id}`, { method: "DELETE" }).then((r) => j<null>(r)),
  explorerUrl: (id: number) => `/api/snapshots/${id}/explorer`,
  compare: (oldId: number, newId: number) =>
    fetch("/api/compare", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ old_id: oldId, new_id: newId }),
    }).then((r) => j<any>(r)),

  seedDemo: () => fetch("/api/demo/seed", { method: "POST" }).then((r) => j<{ campaign: Campaign; snapshot: SnapshotMeta }>(r)),
};

// shared colour helpers (mirror the engine vocabulary -> CSS tokens)
export const sevColor = (s: string) => `var(--sev-${s.replace(/\s+/g, "")}, var(--text-faint))`;
export const sevSoft = (s: string) => `var(--sev-${s.replace(/\s+/g, "")}-soft, var(--surface-3))`;
export const bandColor = (b: string) => `var(--band-${b.replace(/\s+/g, "")}, var(--text-faint))`;
export const readyColor = (r: string) => `var(--ready-${r.replace(/\s+/g, "")}, var(--text-faint))`;
