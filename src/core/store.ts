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
import { readFlow, type FlowProblem } from "../forwarding/ip";

export type BandFilter = "all" | "degraded";
/** Every Device-evidence tab, as a runtime value: the URL parser accepts exactly these and the
 *  composite-widget census visits each one, so neither can drift from the type into a hand list. */
export const EVIDENCE_TABS = ["summary", "ports", "routing", "acl", "findings", "raw"] as const;
export type EvidenceTab = (typeof EVIDENCE_TABS)[number];

/**
 * Who made the device selection (acceptance A6 over A5, 2026-09-24).
 *
 * `"hop"` — the trace put it there: the shell re-aims the selection to the active hop's host
 * (App.tsx), and that selection IS the trace's question, so the fabric draws no failure hypothesis
 * over the packet's answer (A5, one question per picture). `"explicit"` — anything else: the
 * palette, a fabric click, the fabric list, an evidence chip, a restored `d=`. The fabric used to
 * infer the difference from `deviceId === the hop's host`, which every one of those satisfies too,
 * so selecting core1 during a trace drew nothing (the A6 refutation at 70bea72).
 *
 * `selectDevice` DEFAULTS to explicit, so a caller cannot forget to say it; only the trace's own
 * re-aim says "hop".
 */
export type SelectionOrigin = "explicit" | "hop";

/**
 * A flow a shared link carried that is not a valid question. It is REFUSED, not repaired and not
 * dropped: the path panel says which fields are wrong, in words, and nothing is traced. Dropping it
 * silently would show the reader an empty form under a link that plainly names a flow; tracing it
 * answered `tcp>abc` with "a tcp/NaN flow … is delivered" (2026-09-23 acceptance report, B1).
 */
export interface RefusedFlow {
  /** The link's flow parameter, verbatim — re-encoded unchanged, so a reload shows the same refusal. */
  text: string;
  /** The fields as the link wrote them, for the form to show back. */
  fields: { srcIp: string; dstIp: string; protocol: string; dstPort: string };
  /** Every problem, each naming its field. Never empty. */
  problems: FlowProblem[];
}

export interface InvestigationState {
  /* ── selection: what the user is looking at ── */
  deviceId: string | null;
  /** Who made `deviceId` — see SelectionOrigin. Meaningless (and ignored) while there is no trace. */
  deviceOrigin: SelectionOrigin;
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
  /** Set only by a link whose flow failed validation; any real flow clears it. */
  flowRefused: RefusedFlow | null;

  /* ── view state ── */
  surface: SurfaceId;
  evidenceTab: EvidenceTab;
  paletteOpen: boolean;
  inspectorOpen: boolean;
  /** Last element to own focus before a modal opened, so focus can be returned exactly. */
  focusReturn: HTMLElement | null;

  /* ── actions ── */
  selectDevice: (id: string | null, opts?: { surface?: SurfaceId; origin?: SelectionOrigin }) => void;
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
  deviceOrigin: "explicit",
  linkId: null,
  findingId: null,
  hopIndex: null,
  query: "",
  severities: EMPTY_SEV,
  roles: new Set<string>(),
  onlyUncollected: false,
  flow: null,
  trace: null,
  flowRefused: null,
  surface: "fabric",
  evidenceTab: "summary",
  paletteOpen: false,
  inspectorOpen: false,
  focusReturn: null,

  /* Selecting a device keeps the rest of the context: the finding that led here stays selected so
     the evidence pane can still show "you got here from F013". Only the link is cleared, because a
     link selection is strictly narrower than the device it now belongs to. */
  selectDevice: (id, opts) =>
    set((s) => ({ deviceId: id, deviceOrigin: opts?.origin ?? "explicit", linkId: null, surface: opts?.surface ?? s.surface })),
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
  /* A flow set from anywhere supersedes whatever a link refused: the refusal described a question
     the reader has now replaced. */
  setFlow: (f) => set({ flow: f, flowRefused: null }),
  setTrace: (t) => set({ trace: t, hopIndex: t && t.hops.length > 0 ? 0 : null }),
  setSurface: (s) => set({ surface: s }),
  setEvidenceTab: (t) => set({ evidenceTab: t }),
  setPaletteOpen: (v, focusReturn) =>
    set((s) => ({ paletteOpen: v, focusReturn: v ? (focusReturn ?? null) : s.focusReturn })),
  setInspectorOpen: (v) => set({ inspectorOpen: v }),
  reset: () =>
    set({
      deviceId: null,
      deviceOrigin: "explicit",
      linkId: null,
      findingId: null,
      hopIndex: null,
      query: "",
      severities: EMPTY_SEV,
      roles: new Set<string>(),
      onlyUncollected: false,
      flow: null,
      trace: null,
      flowRefused: null,
    }),
  /* A restored `d=` is the reader's choice (A4: "the reader's device choice IS part of the
     investigation"), so a patch naming a device makes the selection explicit unless it says
     otherwise. A patch naming no device leaves the origin alone. */
  hydrate: (patch) => set("deviceId" in patch && patch.deviceOrigin === undefined ? { ...patch, deviceOrigin: "explicit" } : patch),
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
  /* The trace's own selection is written WITHOUT `d=`. The grammar already reads "a flow and no
     `d=`" as "select the hop's host" (A4), so this link restores the same picture — and a `d=` then
     always means a device the reader chose, which is how a restored link tells the two apart
     (SelectionOrigin; acceptance A6). Every link this grammar ever wrote still decodes as before. */
  const traceOwnsDevice =
    s.deviceOrigin === "hop" &&
    s.flow !== null &&
    s.trace !== null &&
    s.hopIndex !== null &&
    s.trace.hops[s.hopIndex]?.host === s.deviceId;
  if (s.deviceId && !traceOwnsDevice) p.set("d", s.deviceId);
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
  } else if (s.flowRefused) {
    p.set("flow", s.flowRefused.text);
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
  if (tab && (EVIDENCE_TABS as readonly string[]).includes(tab))
    out.evidenceTab = tab as EvidenceTab;
  const flow = p.get("flow");
  if (flow) {
    const read = readFlowParam(flow);
    if (read.flow !== null) out.flow = read.flow;
    else out.flowRefused = read.refused;
  }
  const hop = p.get("hop");
  /* A hop names a hop OF A TRACE. A refused flow has none, so no hop is restored against it. */
  if (out.flowRefused === undefined && hop !== null && hop !== "" && Number.isInteger(Number(hop))) out.hopIndex = Number(hop);
  return out;
}

/**
 * The link grammar for a flow: `src>dst>protocol>port`, the port possibly empty. The FIELDS are
 * judged by `readFlow` (src/forwarding/ip.ts) — the same validator the form uses — so a link can
 * restore exactly the flows the form could have produced and no others. Only the SHAPE is this
 * grammar's own: more than four fields is not a flow.
 */
function readFlowParam(text: string): { flow: Flow; refused: null } | { flow: null; refused: RefusedFlow } {
  const parts = text.split(">");
  const fields = { srcIp: parts[0] ?? "", dstIp: parts[1] ?? "", protocol: parts[2] ?? "", dstPort: parts[3] ?? "" };
  if (parts.length > 4) {
    return { flow: null, refused: { text, fields, problems: [{ field: "flow", kind: "malformed", value: text }] } };
  }
  const read = readFlow(fields);
  if (read.flow !== null) return { flow: read.flow, refused: null };
  return { flow: null, refused: { text, fields, problems: read.problems } };
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
