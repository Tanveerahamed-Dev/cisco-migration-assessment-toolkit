/**
 * store.ts — one investigation context, shared by every surface.
 *
 * The property this buys (the IP Fabric / Forward bar): selecting a finding in the queue, a node in
 * the 3-D fabric, or a hop in a path trace all write the SAME selection, so the other surfaces
 * re-aim rather than reset. Nothing ever drops the user back to a blank state mid-investigation.
 *
 * The URL is the serialization of that context (the Grafana Explore bar): every investigation is
 * reproducible from its link alone, so a finding can be handed to a colleague verbatim.
 */
import { useSyncExternalStore } from "react";
import { create } from "zustand";
import type { Flow, Severity, SurfaceId, Trace } from "./types";

export type BandFilter = "all" | "degraded";
export type EvidenceTab = "summary" | "ports" | "routing" | "acl" | "findings" | "raw";

export interface InvestigationState {
  /* ── selection: what the user is looking at ── */
  deviceId: string | null;
  linkId: string | null;
  findingId: string | null;
  hopIndex: number | null;

  /* ── scoping: which slice of the fleet is in play ── */
  query: string;
  severities: Set<Severity>;
  roles: Set<string>;
  onlyUncollected: boolean;

  /* ── path investigation ── */
  flow: Flow | null;
  trace: Trace | null;

  /* ── view state ── */
  surface: SurfaceId;
  evidenceTab: EvidenceTab;
  paletteOpen: boolean;
  inspectorOpen: boolean;
  /** Last element to own focus before a modal opened, so focus can be returned exactly. */
  focusReturn: HTMLElement | null;

  /* ── actions ── */
  selectDevice: (id: string | null, opts?: { surface?: SurfaceId }) => void;
  selectLink: (id: string | null) => void;
  selectFinding: (id: string | null) => void;
  selectHop: (i: number | null) => void;
  setQuery: (q: string) => void;
  toggleSeverity: (s: Severity) => void;
  toggleRole: (r: string) => void;
  setOnlyUncollected: (v: boolean) => void;
  setFlow: (f: Flow | null) => void;
  setTrace: (t: Trace | null) => void;
  setSurface: (s: SurfaceId) => void;
  setEvidenceTab: (t: EvidenceTab) => void;
  setPaletteOpen: (v: boolean, focusReturn?: HTMLElement | null) => void;
  setInspectorOpen: (v: boolean) => void;
  reset: () => void;
  hydrate: (patch: Partial<InvestigationState>) => void;
}

const EMPTY_SEV = new Set<Severity>();

export const useInvestigation = create<InvestigationState>((set) => ({
  deviceId: null,
  linkId: null,
  findingId: null,
  hopIndex: null,
  query: "",
  severities: EMPTY_SEV,
  roles: new Set<string>(),
  onlyUncollected: false,
  flow: null,
  trace: null,
  surface: "fabric",
  evidenceTab: "summary",
  paletteOpen: false,
  inspectorOpen: false,
  focusReturn: null,

  /* Selecting a device keeps the rest of the context: the finding that led here stays selected so
     the evidence pane can still show "you got here from F013". Only the link is cleared, because a
     link selection is strictly narrower than the device it now belongs to. */
  selectDevice: (id, opts) =>
    set((s) => ({ deviceId: id, linkId: null, surface: opts?.surface ?? s.surface })),
  selectLink: (id) => set({ linkId: id }),
  selectFinding: (id) => set({ findingId: id }),
  selectHop: (i) => set({ hopIndex: i }),
  setQuery: (q) => set({ query: q }),
  toggleSeverity: (sev) =>
    set((s) => {
      const next = new Set(s.severities);
      if (next.has(sev)) next.delete(sev);
      else next.add(sev);
      return { severities: next };
    }),
  toggleRole: (r) =>
    set((s) => {
      const next = new Set(s.roles);
      if (next.has(r)) next.delete(r);
      else next.add(r);
      return { roles: next };
    }),
  setOnlyUncollected: (v) => set({ onlyUncollected: v }),
  setFlow: (f) => set({ flow: f }),
  setTrace: (t) => set({ trace: t, hopIndex: t && t.hops.length > 0 ? 0 : null }),
  setSurface: (s) => set({ surface: s }),
  setEvidenceTab: (t) => set({ evidenceTab: t }),
  setPaletteOpen: (v, focusReturn) =>
    set((s) => ({ paletteOpen: v, focusReturn: v ? (focusReturn ?? null) : s.focusReturn })),
  setInspectorOpen: (v) => set({ inspectorOpen: v }),
  reset: () =>
    set({
      deviceId: null,
      linkId: null,
      findingId: null,
      hopIndex: null,
      query: "",
      severities: EMPTY_SEV,
      roles: new Set<string>(),
      onlyUncollected: false,
      flow: null,
      trace: null,
    }),
  hydrate: (patch) => set(patch),
}));

/* ── URL serialization: an investigation is its link ───────────────────────── */

const SEV_CODES: Record<string, Severity> = {
  C: "Critical",
  H: "High",
  M: "Medium",
  L: "Low",
  I: "Info",
};
const CODE_OF = Object.fromEntries(Object.entries(SEV_CODES).map(([k, v]) => [v, k]));

export function encodeInvestigation(s: InvestigationState): string {
  const p = new URLSearchParams();
  if (s.surface !== "fabric") p.set("s", s.surface);
  if (s.deviceId) p.set("d", s.deviceId);
  if (s.linkId) p.set("l", s.linkId);
  if (s.findingId) p.set("f", s.findingId);
  if (s.query) p.set("q", s.query);
  if (s.severities.size) p.set("sev", [...s.severities].map((x) => CODE_OF[x]).join(""));
  if (s.roles.size) p.set("role", [...s.roles].join(","));
  if (s.onlyUncollected) p.set("unc", "1");
  if (s.evidenceTab !== "summary") p.set("tab", s.evidenceTab);
  if (s.flow) {
    const f = s.flow;
    p.set("flow", [f.srcIp, f.dstIp, f.protocol, f.dstPort ?? ""].join(">"));
  }
  if (s.hopIndex !== null) p.set("hop", String(s.hopIndex));
  return p.toString();
}

export function decodeInvestigation(search: string): Partial<InvestigationState> {
  const p = new URLSearchParams(search);
  const out: Partial<InvestigationState> = {};
  const surface = p.get("s");
  if (surface === "fabric" || surface === "findings" || surface === "path" || surface === "evidence")
    out.surface = surface;
  if (p.has("d")) out.deviceId = p.get("d");
  if (p.has("l")) out.linkId = p.get("l");
  if (p.has("f")) out.findingId = p.get("f");
  if (p.has("q")) out.query = p.get("q") ?? "";
  if (p.has("sev")) {
    const set = new Set<Severity>();
    for (const ch of p.get("sev") ?? "") {
      const sev = SEV_CODES[ch];
      if (sev) set.add(sev);
    }
    out.severities = set;
  }
  if (p.has("role")) out.roles = new Set((p.get("role") ?? "").split(",").filter(Boolean));
  if (p.get("unc") === "1") out.onlyUncollected = true;
  const tab = p.get("tab");
  if (tab && ["summary", "ports", "routing", "acl", "findings", "raw"].includes(tab))
    out.evidenceTab = tab as EvidenceTab;
  const flow = p.get("flow");
  if (flow) {
    const [srcIp, dstIp, protocol, dstPort] = flow.split(">");
    if (srcIp && dstIp)
      out.flow = {
        srcIp,
        dstIp,
        protocol: (protocol as Flow["protocol"]) || "ip",
        dstPort: dstPort ? Number(dstPort) : null,
        srcPort: null,
      };
  }
  const hop = p.get("hop");
  if (hop !== null && hop !== "" && Number.isInteger(Number(hop))) out.hopIndex = Number(hop);
  return out;
}

/* ── reduced motion, read live so a mid-session OS change is honoured ─────── */

const motionQuery = (): MediaQueryList | null =>
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = motionQuery();
      mq?.addEventListener("change", cb);
      return () => mq?.removeEventListener("change", cb);
    },
    () => motionQuery()?.matches ?? false,
    () => false,
  );
}

export const prefersReducedMotion = (): boolean => motionQuery()?.matches ?? false;
