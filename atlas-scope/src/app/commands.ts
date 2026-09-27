/**
 * commands.ts — every verb the application exposes, in one registry.
 *
 * The palette, the help sheet and the global keyboard model all read this list. That is the point:
 * a verb defined once cannot appear on one surface and be missing from another, and the shortcut
 * printed next to a command is the shortcut that is actually registered, because both come from
 * the same record.
 *
 * Three rules this file holds to:
 *
 *  1. DATA-DERIVED, NEVER HARDCODED. The severity filters, the traceable flows and the grammar
 *     examples are computed from `fabric` and from the forwarding engine at first use. A list of
 *     example queries typed into this file would keep offering `severity:Info` long after the
 *     snapshot stopped containing one — the product would be teaching a grammar its own data
 *     cannot answer.
 *  2. A COMMAND THAT CANNOT ACT SAYS SO. Some verbs need a surface that may not be mounted (the
 *     3-D scene's camera, the legend, Rail B). Those declare a capability; if nothing has
 *     registered it, the command still appears and carries the reason it cannot run. Hiding it
 *     would make the palette's list a claim about the product that is quietly false, and silently
 *     doing nothing would be worse.
 *  3. NO CLOCK, NO RANDOMNESS. Nothing here puts a clock reading or a random value on a path that
 *     affects what is rendered (acceptance F6). This was NOT true until an audit read it: `runFlow`
 *     announced `trace.elapsedMs`, a `performance.now()` delta, into the live region on every
 *     trace. The rule is now enforced over the whole source tree by
 *     `src/core/determinism.test.ts`, against the CLASS of clock and randomness sources rather
 *     than against two literal names.
 */
import { fabric, findingById } from "../core/data";
import { useInvestigation, encodeInvestigation } from "../core/store";
import { valueDomain } from "../core/query";
import { SEVERITY_ORDER, type Flow, type Severity, type SurfaceId } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { verdictStatement, type VerdictStatement } from "../panels/ClaimCard";
import { withoutCitations } from "../panels/cited-text";
import { parseIpv4 } from "../forwarding/ip";
import {
  characterKeyShortcutsEnabled,
  isHelpOpen,
  registerShortcuts,
  setCharacterKeyShortcuts,
  setHelpOpen,
  type Shortcut,
} from "./keyboard";
import { useEffect, useSyncExternalStore } from "react";
import { flushSync } from "react-dom";
import { applyTheme, writeThemePreference } from "./theme-preference";

/* ══ capabilities: verbs that need a surface to be mounted ═════════════════ */

export type Capability =
  | "fabric.resetCamera"
  | "fabric.toggleLegend"
  | "fabric.toggleTree"
  | "evidence.toggle"
  | "query.focus"
  | "config.open";

/**
 * Every member of `Capability` MUST have a registrar (`registerCommandTarget`) or a DOM owner
 * (`data-atlas-command`) somewhere in `src/`. A capability with neither is not an unavailable
 * action — it is an action that does not exist, and `capabilityReason()` explains its absence as
 * a layout condition, which is false on every screen. `commands.capability-owners.test.ts` asserts
 * the invariant over the source, so an orphan fails the build.
 */
const CAPABILITY_OWNER: Readonly<Record<Capability, string>> = {
  "fabric.resetCamera": "the 3-D fabric",
  "fabric.toggleLegend": "the fabric legend",
  "fabric.toggleTree": "the fabric list",
  "evidence.toggle": "the evidence rail",
  "query.focus": "the query bar",
  "config.open": "the configuration-evidence overlay",
};

/**
 * A DOM control that publishes itself as the owner of a capability. Surfaces opt in by putting
 * `data-atlas-command="fabric.resetCamera"` on the button they already render, which keeps one
 * behaviour behind one control: the palette activates the same button the mouse would, so the two
 * routes cannot drift into doing different things.
 */
const domOwner = (cap: Capability): HTMLElement | null =>
  typeof document === "undefined"
    ? null
    : document.querySelector<HTMLElement>(`[data-atlas-command="${cap}"]`);

const targets = new Map<Capability, () => void>();

/** Register an imperative owner for a capability. Returns the un-registration. */
export function registerCommandTarget(cap: Capability, run: () => void): () => void {
  targets.set(cap, run);
  notifyTargets();
  return () => {
    if (targets.get(cap) === run) {
      targets.delete(cap);
      notifyTargets();
    }
  };
}

const targetListeners = new Set<() => void>();
let targetEpoch = 0;
const notifyTargets = (): void => {
  targetEpoch += 1;
  for (const l of targetListeners) l();
};

/** Re-render when the set of mounted capability owners changes, so availability stays truthful. */
export function useCommandTargets(): number {
  return useSyncExternalStore(
    (cb) => {
      targetListeners.add(cb);
      return () => targetListeners.delete(cb);
    },
    () => targetEpoch,
    () => 0,
  );
}

const capabilityAvailable = (cap: Capability): boolean =>
  targets.has(cap) || domOwner(cap) !== null;

const capabilityReason = (cap: Capability): string =>
  `${CAPABILITY_OWNER[cap]} is not on screen in this layout, so this action has nothing to act on.`;

function runCapability(cap: Capability): boolean {
  const fn = targets.get(cap);
  if (fn) {
    fn();
    return true;
  }
  const el = domOwner(cap);
  if (el) {
    el.click();
    return true;
  }
  announce(capabilityReason(cap));
  return false;
}

/* ══ announcements ═════════════════════════════════════════════════════════
   A command run from the keyboard produces no visible change often enough (a copied link, a
   refused action) that an unannounced result reads as a dead key. `#sr-status` in App.tsx is the
   SINGLE live region that carries it — one owner, like `sr-alert` and `sr-log` — and this is the
   one way to write to it. A second component subscribing to `useCommandAnnouncement()` and
   rendering it into a region of its own is a double announcement, not a redundancy; the count of
   subscribers is pinned in src/app/announcement-single-owner.test.tsx. */

let announcement = "";
let announceSeq = 0;
const announceListeners = new Set<() => void>();

export function announce(message: string): void {
  announceSeq += 1;
  // A live region does not re-announce identical text. The alternating zero-width space makes a
  // repeated message a textual change without changing what a sighted reader would see.
  announcement = announceSeq % 2 === 0 ? `${message}​` : message;
  for (const l of announceListeners) l();
}

export function useCommandAnnouncement(): string {
  return useSyncExternalStore(
    (cb) => {
      announceListeners.add(cb);
      return () => announceListeners.delete(cb);
    },
    () => announcement,
    () => "",
  );
}

/* ══ palette seed: a command that hands the palette a starting query ═══════ */

let paletteSeed: string | null = null;

export const setPaletteSeed = (text: string): void => {
  paletteSeed = text;
};

/** Read-once: a seed that survived its opening would re-apply on the next, unrelated open. */
export function consumePaletteSeed(): string | null {
  const v = paletteSeed;
  paletteSeed = null;
  return v;
}

export function openPalette(focusReturn?: HTMLElement | null): void {
  const el = focusReturn ?? (typeof document === "undefined" ? null : (document.activeElement as HTMLElement | null));
  useInvestigation.getState().setPaletteOpen(true, el);
}

/* ══ theme ═════════════════════════════════════════════════════════════════ */

export type Theme = "dark" | "light";

/** The theme in force: an explicit choice wins, otherwise the OS preference decides. */
export function effectiveTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "dark" || explicit === "light") return explicit;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function setTheme(theme: Theme): void {
  applyTheme(theme);
  // The key and the refused-write policy belong to theme-preference.ts. A refused write (a private
  // window, blocked site data) is a convenience lost: the reader clicks once more next session.
  writeThemePreference(theme);
  // The 3-D scene reads the attribute through a MutationObserver; a header toggle listens for
  // this event so the two controls cannot disagree about which theme is showing.
  window.dispatchEvent(new CustomEvent("atlas-scope:theme", { detail: theme }));
}

/* ══ surfaces ══════════════════════════════════════════════════════════════ */

const REGION_SELECTOR: Readonly<Record<SurfaceId, string>> = {
  fabric: "#stage",
  findings: "#rail-queue",
  path: "#rail-path",
  evidence: "#rail-evidence",
};

const SURFACE_LABEL: Readonly<Record<SurfaceId, string>> = {
  fabric: "the 3-D fabric",
  findings: "the priority queue",
  path: "the path panel",
  evidence: "the evidence rail",
};

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * What a surface needs, beyond the store write, to be ON SCREEN before focus can land in it — owned
 * by the frame, which alone knows the layout rung. At the drawer rung the evidence rail is an overlay
 * that is closed by default; "go to the evidence rail" there must open it first (App.tsx registers
 * that). `opener` is what held focus when the move was asked for.
 */
type SurfaceReveal = (surface: SurfaceId, opener: HTMLElement | null) => void;
let surfaceReveal: SurfaceReveal | null = null;

/** Register the frame's reveal. Returns the un-registration. */
export function registerSurfaceReveal(fn: SurfaceReveal): () => void {
  surfaceReveal = fn;
  return () => {
    if (surfaceReveal === fn) surfaceReveal = null;
  };
}

/**
 * Navigate. The store write is the navigation; moving focus is what makes it a keyboard
 * navigation rather than a state change the keyboard user cannot follow.
 *
 * `#rail-path` is absent from the DOM whenever no flow exists (design brief 2.2), so "go to path"
 * with no trace running has nowhere to land — it says so instead of pretending to move.
 *
 * THE MOVE IS ANNOUNCED ONLY IF IT HAPPENED (acceptance D3 discovery, 2026-09-26). This used to call
 * `landing.focus()` and announce "Moved to the evidence rail." unconditionally. MEASURED at 1100 px
 * with the drawer closed: the landing sat inside a `visibility: hidden` rail, `focus()` did nothing,
 * focus stayed on the grid cell — and the live region said it had moved. The same was true at the
 * single-column rung, where the store write that unhides the rail had not been committed yet when
 * `focus()` ran. So the write (and the frame's reveal, which opens the drawer) is committed first,
 * synchronously, and the announcement is made from where focus actually is.
 */
export function goToSurface(surface: SurfaceId): void {
  const from = typeof document === "undefined" ? null : document.activeElement;
  const opener = from instanceof HTMLElement && from !== document.body ? from : null;
  flushSync(() => {
    useInvestigation.getState().setSurface(surface);
    surfaceReveal?.(surface, opener);
  });
  const region = document.querySelector<HTMLElement>(REGION_SELECTOR[surface]);
  if (!region) {
    announce(
      surface === "path"
        ? "No path is being investigated, so the path panel is not on screen. Run a trace first."
        : `${SURFACE_LABEL[surface]} is not on screen in this layout.`,
    );
    return;
  }
  const landing =
    region.matches(FOCUSABLE) || region.hasAttribute("tabindex")
      ? region
      : region.querySelector<HTMLElement>(FOCUSABLE);
  if (landing === null) {
    // The surface exists but offers nowhere to land. Saying "moved" would be a lie the keyboard
    // user can feel: focus is still where it was, and the next key acts on the old surface.
    announce(`${SURFACE_LABEL[surface]} is showing, but it has no focusable content yet.`);
    return;
  }
  landing.focus();
  if (document.activeElement !== landing && !region.contains(document.activeElement)) {
    announce(`${SURFACE_LABEL[surface]} could not take focus in this layout, so focus stayed where it was.`);
    return;
  }
  announce(`Moved to ${SURFACE_LABEL[surface]}.`);
}

/* ══ flow-shaped queries ═══════════════════════════════════════════════════ */

export interface FlowQuery {
  flow: Flow;
  /** One line naming every value the grammar supplied rather than the user. Never silent. */
  assumptions: string[];
}

const PROTOCOLS: readonly Flow["protocol"][] = ["tcp", "udp", "icmp", "ip"];

const FLOW_SHAPE =
  /^\s*(?:from\s+)?(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?\s*(?:->|→|=>|to)\s*(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?\s*(tcp|udp|icmp|ip)?\s*$/i;

/**
 * Recognise `10.0.10.50 -> 10.0.30.10:443`, `from A to B`, `A -> B:443 udp`.
 *
 * The protocol is the interesting case: a port without a protocol has to become something, and
 * silently becoming TCP is an unstated assumption inside a forwarding verdict. It is stated in
 * `assumptions` and the palette prints it on the row, so the user sees what the engine will
 * actually be asked before they ask it.
 */
export function parseFlowQuery(text: string): FlowQuery | null {
  const m = FLOW_SHAPE.exec(text);
  if (!m) return null;
  const [, srcRaw, srcPortRaw, dstRaw, dstPortRaw, protoRaw] = m;
  if (srcRaw === undefined || dstRaw === undefined) return null;
  if (parseIpv4(srcRaw) === null || parseIpv4(dstRaw) === null) return null;

  const port = (raw: string | undefined): number | null => {
    if (raw === undefined) return null;
    const n = Number(raw);
    return Number.isInteger(n) && n >= 0 && n <= 65535 ? n : null;
  };
  const dstPort = port(dstPortRaw);
  const srcPort = port(srcPortRaw);
  if (dstPortRaw !== undefined && dstPort === null) return null;
  if (srcPortRaw !== undefined && srcPort === null) return null;

  const assumptions: string[] = [];
  const declared = protoRaw?.toLowerCase();
  const protocol: Flow["protocol"] =
    declared && (PROTOCOLS as readonly string[]).includes(declared)
      ? (declared as Flow["protocol"])
      : dstPort !== null
        ? "tcp"
        : "ip";
  if (!declared) {
    assumptions.push(
      dstPort === null
        ? "No protocol and no port given — traced as plain IP, so no ACL port match is evaluated."
        : "No protocol given — traced as TCP because a destination port was supplied.",
    );
  }
  if (srcPort === null) assumptions.push("No source port given — traced as unspecified.");

  return { flow: { srcIp: srcRaw, dstIp: dstRaw, protocol, dstPort, srcPort }, assumptions };
}

export const formatFlow = (f: Flow): string =>
  `${f.srcIp} → ${f.dstIp}${f.dstPort === null ? "" : `:${f.dstPort}`} ${f.protocol.toUpperCase()}`;

/** Run a trace and put the result in the shared investigation context. */
export function runFlow(flow: Flow): void {
  const st = useInvestigation.getState();
  const trace = traceFlow(flow);
  st.setFlow(flow);
  st.setTrace(trace);
  st.setSurface("path");
  /* No `trace.elapsedMs` here. It used to be announced — "…, 2.3 ms." — and it was the one
     wall-clock value in the product that reached the DOM: a `performance.now()` delta, rendered
     into `#sr-status`, on every trace. It made rule 3 above false, it made the announcement differ
     between two runs of the same investigation, and it told a screen-reader user nothing they
     could act on. How long the search took is a MEASUREMENT of this machine, not part of the
     verdict; `review/measure-inp.mjs` is where that belongs. */
  /* The verdict is spoken with its bounds, in the card's own words (B2): "Trace …: denied, 2 hops."
     told a screen-reader user a decided refusal over a trace whose card says "not decided", with no
     scope and no caveat. */
  announce(
    `Trace ${formatFlow(flow)}: ${verdictStatement(trace).sentence} ${trace.hops.length} hop${trace.hops.length === 1 ? "" : "s"}.`,
  );
}

/* ══ grammar examples, generated from this snapshot ════════════════════════ */

export interface GrammarExample {
  /** The literal text to put in the search box. */
  query: string;
  /** What it does, and the count it will return — measured, not promised. */
  detail: string;
  /** Present when the detail states a forwarding verdict: the bounds it carries (ClaimCard `verdictStatement`). */
  verdict?: VerdictStatement;
}

const memo = <T>(fn: () => T): (() => T) => {
  let cached: { v: T } | null = null;
  return () => (cached ??= { v: fn() }).v;
};

const findingsBySeverity = memo((): Map<Severity, number> => {
  const counts = new Map<Severity, number>();
  for (const f of fabric.findings) counts.set(f.severity, (counts.get(f.severity) ?? 0) + 1);
  return counts;
});

const busiestHost = memo((): { host: string; count: number } | null => {
  const counts = new Map<string, number>();
  for (const f of fabric.findings) for (const d of f.devices) counts.set(d, (counts.get(d) ?? 0) + 1);
  let best: { host: string; count: number } | null = null;
  // Ties break on the hostname so the palette's teaching examples are identical between runs.
  for (const [host, count] of [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    best = { host, count };
    break;
  }
  return best;
});

/**
 * The empty-palette state teaches the grammar with queries drawn from the data in front of the
 * user. Every example carries the number of rows it returns, so an example that would return
 * nothing is never offered — a search box that teaches a query returning zero rows teaches the
 * user that the search box is broken.
 */
export const grammarExamples = memo((): GrammarExample[] => {
  const out: GrammarExample[] = [];

  const sev = SEVERITY_ORDER.find((s) => (findingsBySeverity().get(s) ?? 0) > 0);
  if (sev) out.push({ query: `severity:${sev}`, detail: `${findingsBySeverity().get(sev)} findings at ${sev}` });

  const host = busiestHost();
  if (host) out.push({ query: `host:${host.host}`, detail: `${host.count} findings naming ${host.host}` });

  // Taken from the grammar's own `is:` domain rather than written out here: if the engine ever
  // drops the predicate, this example changes with it instead of teaching a query that fails.
  const predicates = valueDomain("is") ?? [];
  const uncollected =
    predicates.find((p) => p.value === "uncollected" && (p.count ?? 0) > 0) ??
    predicates.find((p) => (p.count ?? 0) > 0);
  if (uncollected)
    out.push({
      query: `is:${uncollected.value}`,
      detail: `${uncollected.count} ${uncollected.source} — ${uncollected.detail ?? "observed in this snapshot"}`,
    });

  const roles = valueDomain("role") ?? [];
  const role = roles[0];
  if (role) out.push({ query: `role:${role.value}`, detail: `${role.count ?? 0} devices with role ${role.value}` });

  /* The example names a flow and states what ITS trace says, bounded as the trace bounds it. It used
     to read "trace a path — this one ends denied" over a denial whose own claim says "That denial is
     not decided" (acceptance B2): the outcome enum, re-worded here, with no scope and no caveat. */
  const flow = suggestedFlows()[0];
  if (flow) {
    const verdict = verdictStatement(traceFlow(flow.flow));
    out.push({
      query: `${flow.flow.srcIp} -> ${flow.flow.dstIp}${flow.flow.dstPort === null ? "" : `:${flow.flow.dstPort}`}`,
      detail: `trace a path — its trace reads: ${verdict.sentence}`,
      verdict,
    });
  }

  return out;
});

/* ══ the command registry ══════════════════════════════════════════════════ */

export type CommandGroup = "Go to" | "Path" | "Selection" | "Filter" | "View" | "Investigation";

export const GROUP_ORDER: readonly CommandGroup[] = [
  "Go to",
  "Path",
  "Selection",
  "Filter",
  "View",
  "Investigation",
];

export interface Availability {
  ok: boolean;
  /** Non-null exactly when `ok` is false: the sentence the palette prints on the row. */
  reason: string | null;
}

const OK: Availability = { ok: true, reason: null };
const no = (reason: string): Availability => ({ ok: false, reason });

export interface Command {
  id: string;
  title: string;
  /** Extra words this command should be findable by; never shown as the title. */
  keywords: string[];
  /** A key spec from keyboard.ts. Present here means it is registered there too. */
  shortcut?: string;
  group: CommandGroup;
  /** Secondary line: what it will do, or the evidence it rests on. */
  detail?: string | null;
  run: () => void;
  /** Evaluated at render time, so a stale availability is impossible. */
  availability?: () => Availability;
  /**
   * Present exactly when `detail` states a forwarding verdict: the bounds it was stated with
   * (ClaimCard `verdictStatement`). The palette draws such a detail whole — a verdict clipped after
   * its word and before its scope is the unbounded verdict again, one CSS rule later.
   */
  verdict?: VerdictStatement;
}

const st = () => useInvestigation.getState();

const capabilityCommand = (
  id: string,
  cap: Capability,
  title: string,
  group: CommandGroup,
  keywords: string[],
  shortcut?: string,
): Command => ({
  id,
  title,
  keywords,
  group,
  ...(shortcut === undefined ? {} : { shortcut }),
  run: () => void runCapability(cap),
  availability: () => (capabilityAvailable(cap) ? OK : no(capabilityReason(cap))),
});

/** Copy the investigation link. Reports the failure it can have rather than swallowing it. */
function copyInvestigationLink(): void {
  const query = encodeInvestigation(st());
  const url = `${window.location.origin}${window.location.pathname}${query === "" ? "" : `?${query}`}`;
  const clipboard = navigator.clipboard;
  if (!clipboard?.writeText) {
    announce("This browser did not offer a clipboard (it needs a secure context). The link is in the address bar.");
    return;
  }
  void clipboard.writeText(url).then(
    () => announce(`Investigation link copied: ${url}`),
    (err: unknown) =>
      announce(`The link could not be copied: ${err instanceof Error ? err.message : String(err)}`),
  );
}

function selectFindingsPrimaryDevice(): void {
  const s = st();
  if (s.findingId === null) {
    announce("No finding is selected, so there is no device to select.");
    return;
  }
  // Three outcomes, three different sentences. "Nothing happened" would collapse an unresolvable
  // id and a finding that genuinely names no device into one indistinguishable non-event.
  const finding = findingById.get(s.findingId);
  if (finding === undefined) {
    announce(`${s.findingId} is not a finding in this snapshot, so it names no device.`);
    return;
  }
  const host = finding.devices[0];
  if (host === undefined) {
    announce(`${finding.id} names no device — the record does not say which device it applies to.`);
    return;
  }
  s.selectDevice(host, { surface: "fabric" });
  announce(`Selected ${host}, the first device named by ${finding.id}.`);
}

function stepHop(delta: number): void {
  const s = st();
  const hops = s.trace?.hops.length ?? 0;
  if (hops === 0) {
    announce("No trace is running, so there are no hops to step through.");
    return;
  }
  const next = Math.min(hops - 1, Math.max(0, (s.hopIndex ?? 0) + delta));
  s.selectHop(next);
  announce(`Hop ${next + 1} of ${hops}.`);
}

const staticCommands = memo((): Command[] => [
  {
    id: "goto.fabric",
    title: "Go to the 3-D fabric",
    keywords: ["stage", "topology", "canvas", "map", "navigate"],
    shortcut: "g f",
    group: "Go to",
    run: () => goToSurface("fabric"),
  },
  {
    id: "goto.queue",
    title: "Go to the priority queue",
    keywords: ["findings", "grid", "list", "navigate"],
    shortcut: "g q",
    group: "Go to",
    run: () => goToSurface("findings"),
  },
  {
    id: "goto.path",
    title: "Go to the path panel",
    keywords: ["trace", "hops", "forwarding", "navigate"],
    shortcut: "g p",
    group: "Go to",
    run: () => goToSurface("path"),
    availability: () =>
      st().flow === null ? no("No flow is being investigated yet, so the path panel is not on screen.") : OK,
  },
  {
    id: "goto.evidence",
    title: "Go to the evidence rail",
    keywords: ["rail", "raw", "records", "navigate"],
    shortcut: "g e",
    group: "Go to",
    run: () => goToSurface("evidence"),
  },
  capabilityCommand("query.focus", "query.focus", "Focus the query bar", "Go to", ["search", "filter", "slash"], "/"),

  {
    id: "path.rerun",
    title: "Re-run the current trace",
    keywords: ["retrace", "forwarding", "path", "again"],
    shortcut: "t",
    group: "Path",
    run: () => {
      const flow = st().flow;
      if (flow === null) {
        announce("No flow is set, so there is nothing to re-trace. Pick a suggested flow first.");
        return;
      }
      runFlow(flow);
    },
    availability: () => (st().flow === null ? no("No flow has been posed yet.") : OK),
  },
  {
    id: "path.nextHop",
    title: "Next hop",
    keywords: ["hop", "forward", "step"],
    shortcut: "]",
    group: "Path",
    run: () => stepHop(1),
    availability: () => ((st().trace?.hops.length ?? 0) === 0 ? no("No trace is running.") : OK),
  },
  {
    id: "path.prevHop",
    title: "Previous hop",
    keywords: ["hop", "back", "step"],
    shortcut: "[",
    group: "Path",
    run: () => stepHop(-1),
    availability: () => ((st().trace?.hops.length ?? 0) === 0 ? no("No trace is running.") : OK),
  },
  /* REMOVED: `path.counterfactual` / capability `acl.toggleCounterfactual`.
     Nothing in src/ ever registered a target or published a DOM owner for it, so
     `capabilityAvailable()` was permanently false and the palette rendered the row as merely
     UNAVAILABLE — "the path panel is not on screen in this layout" — while the path panel was on
     screen. An unbuilt feature announced with a shortcut and a false reason is worse than an
     absent one: the reader concludes their layout is wrong. Design-brief §5.2 step 6 still
     specifies this feature; it is tracked as unbuilt in docs/open-issues.md rather than
     advertised here. The `every capability has an owner` test below makes a future orphan a
     build failure instead of a misleading palette row. */

  {
    id: "select.device",
    title: "Select a device by name…",
    keywords: ["host", "switch", "router", "find", "jump"],
    group: "Selection",
    detail: `${fabric.devices.length} devices in this snapshot`,
    run: () => {
      setPaletteSeed("host:");
      openPalette();
    },
  },
  {
    id: "select.findingDevice",
    title: "Select the finding's primary device",
    keywords: ["device", "finding", "host"],
    shortcut: "d",
    group: "Selection",
    run: selectFindingsPrimaryDevice,
    availability: () => (st().findingId === null ? no("No finding is selected.") : OK),
  },
  {
    id: "select.clear",
    title: "Clear the current selection",
    keywords: ["deselect", "none", "escape"],
    group: "Selection",
    run: () => {
      const s = st();
      s.selectDevice(null);
      s.selectLink(null);
      s.selectFinding(null);
      announce("Selection cleared. The query, the filters and the trace are untouched.");
    },
    availability: () => {
      const s = st();
      return s.deviceId === null && s.linkId === null && s.findingId === null
        ? no("Nothing is selected.")
        : OK;
    },
  },
  capabilityCommand(
    "select.config",
    "config.open",
    "Open the configuration evidence for this selection",
    "Selection",
    ["config", "running-config", "evidence", "raw"],
    "v",
  ),

  {
    id: "view.inspector",
    title: "Toggle the inspector",
    keywords: ["raw", "data", "query", "error", "grafana"],
    shortcut: "i",
    group: "View",
    run: () => {
      const s = st();
      const next = !s.inspectorOpen;
      s.setInspectorOpen(next);
      announce(next ? "Inspector opened." : "Inspector closed.");
    },
  },
  capabilityCommand("view.evidence", "evidence.toggle", "Toggle the evidence rail", "View", ["rail", "panel"], "e"),
  capabilityCommand("view.legend", "fabric.toggleLegend", "Toggle the fabric legend", "View", ["key", "encoding", "swatch"]),
  capabilityCommand("view.tree", "fabric.toggleTree", "Toggle the fabric list (accessible tree)", "View", ["a11y", "table", "tree", "screen reader"]),
  capabilityCommand("view.resetCamera", "fabric.resetCamera", "Reset the camera", "View", ["fit", "frame", "zoom", "home"], "r"),
  {
    id: "view.theme",
    title: "Toggle light and dark theme",
    keywords: ["dark", "light", "appearance", "contrast"],
    shortcut: "mod+\\",
    group: "View",
    run: () => {
      const next: Theme = effectiveTheme() === "dark" ? "light" : "dark";
      setTheme(next);
      announce(`${next === "dark" ? "Dark" : "Light"} theme.`);
    },
  },

  {
    id: "view.characterKeys",
    title: "Turn single-character shortcuts on or off",
    keywords: ["keyboard", "shortcuts", "speech", "accessibility", "disable", "wcag", "character"],
    group: "View",
    detail: "Keys such as D, T, [ and the G sequences. Modifier shortcuts and Escape are unaffected.",
    run: () => {
      const next = !characterKeyShortcutsEnabled();
      setCharacterKeyShortcuts(next);
      announce(
        next
          ? "Single-character shortcuts are on."
          : "Single-character shortcuts are off. Every action is still in this command palette.",
      );
    },
  },
  {
    id: "investigation.copyLink",
    title: "Copy the investigation link",
    keywords: ["url", "share", "permalink", "clipboard"],
    group: "Investigation",
    detail: "The whole investigation — selection, query, filters and flow — is in the URL",
    run: copyInvestigationLink,
  },
  {
    id: "investigation.reset",
    title: "Reset the investigation",
    keywords: ["clear", "start over", "empty"],
    group: "Investigation",
    detail: "Clears selection, query, filters and the trace. The snapshot and the camera stay.",
    run: () => {
      st().reset();
      announce("Investigation reset. The snapshot is unchanged.");
    },
  },
]);

/** One command per severity the snapshot actually contains, carrying its own denominator. */
const severityCommands = memo((): Command[] =>
  SEVERITY_ORDER.filter((s) => (findingsBySeverity().get(s) ?? 0) > 0).map((severity) => ({
    id: `filter.severity.${severity}`,
    title: `Filter: severity ${severity}`,
    keywords: ["severity", "filter", severity.toLowerCase(), "queue"],
    group: "Filter" as const,
    detail: `${findingsBySeverity().get(severity)} of ${fabric.findings.length} findings`,
    run: () => {
      st().toggleSeverity(severity);
      const on = st().severities.has(severity);
      announce(`${severity} ${on ? "added to" : "removed from"} the severity filter.`);
    },
  })),
);

/**
 * One command per flow the engine could actually trace, stating the outcome its trace produced in the
 * claims owner's words and with the trace's own scope clause and caveat count (ClaimCard
 * `verdictStatement`). The detail used to be `${formatFlow} — ${expectedOutcome}. ${rationale}`:
 * the bare enum ("denied") beside a rationale that called the same undecided denial "the
 * blocking-hop answer with its exact configuration line" — no scope, no caveat (acceptance B2).
 *
 * The detail carries no citation (acceptance B6): the palette row is one role=option whose activation
 * RUNS the flow, so a record named in it would be named where choosing it opens nothing, and an option
 * may not contain a control. The trace the flow opens cites every hop.
 */
const flowCommands = memo((): Command[] =>
  suggestedFlows().map((s) => {
    const verdict = verdictStatement(traceFlow(s.flow));
    return {
      id: `path.flow.${s.id}`,
      title: `Trace ${s.title}`,
      keywords: ["trace", "path", "flow", s.flow.srcIp, s.flow.dstIp, s.expectedOutcome],
      group: "Path" as const,
      detail: withoutCitations(`${formatFlow(s.flow)} — ${verdict.sentence} ${s.rationale}`),
      verdict,
      run: () => runFlow(s.flow),
    };
  }),
);

const uncollectedCommand = memo((): Command[] => {
  const n = fabric.devices.filter((d) => !d.collected).length;
  if (n === 0) return [];
  return [
    {
      id: "filter.uncollected",
      title: "Filter: only devices the collector never reached",
      keywords: ["uncollected", "not observed", "coverage", "absent", "filter"],
      group: "Filter",
      detail: `${n} of ${fabric.devices.length} devices are topology-only — no evidence was collected from them`,
      run: () => {
        const next = !st().onlyUncollected;
        st().setOnlyUncollected(next);
        announce(next ? `Showing only the ${n} uncollected devices.` : "Uncollected-only filter removed.");
      },
    },
  ];
});

/**
 * Every command, in display order. Memoised: the list is derived from the snapshot, which does
 * not change within a session, so the palette pays for it once rather than on every keystroke.
 */
export const allCommands = memo((): readonly Command[] => [
  ...staticCommands(),
  ...flowCommands(),
  ...severityCommands(),
  ...uncollectedCommand(),
]);

export const commandById = memo((): ReadonlyMap<string, Command> =>
  new Map(allCommands().map((c) => [c.id, c])),
);

export const commandAvailability = (c: Command): Availability => c.availability?.() ?? OK;

/* ══ shortcut registration ═════════════════════════════════════════════════
   Every command carrying a `shortcut` becomes a binding, so the key printed in the palette and
   on the help sheet is the key that is registered. The three bindings that are not commands —
   the palette itself, the help sheet, and Escape — are declared here beside them. */

function commandShortcuts(): Shortcut[] {
  return allCommands()
    .filter((c): c is Command & { shortcut: string } => typeof c.shortcut === "string")
    .map((c) => ({
      id: c.id,
      keys: c.shortcut,
      scope: "global" as const,
      label: c.title,
      group: c.group,
      run: () => {
        const a = commandAvailability(c);
        if (!a.ok) {
          // The key is real and the user pressed it: say why nothing happened rather than
          // leaving them to conclude the shortcut is broken.
          announce(a.reason ?? "That action is not available right now.");
          return;
        }
        c.run();
      },
    }));
}

let installedCommands = 0;
let releaseCommands: (() => void) | null = null;

/**
 * Register the application's bindings. Ref-counted so the App shell and the palette may both ask
 * without double-registering — a duplicate registration would fire every command twice, which
 * presents as a toggle that never changes state.
 */
export function installAppCommands(): () => void {
  installedCommands += 1;
  if (installedCommands === 1) {
    releaseCommands = registerShortcuts([
      ...commandShortcuts(),
      {
        id: "palette.open",
        keys: "mod+k",
        scope: "global",
        label: "Open the command palette",
        group: "Go to",
        allowInInput: true,
        run: () => {
          const s = st();
          if (s.paletteOpen) s.setPaletteOpen(false);
          else openPalette();
        },
      },
      {
        id: "help.open",
        keys: "?",
        scope: "global",
        label: "Keyboard shortcuts",
        group: "View",
        run: () => setHelpOpen(!isHelpOpen()),
      },
      {
        id: "transient.close",
        keys: "escape",
        scope: "global",
        label: "Close the topmost overlay",
        group: "View",
        allowInInput: true,
        // Escape must not be swallowed when there is nothing to close: the grid clears its
        // selection with it, and a preventDefault here would take that away.
        preventDefault: false,
        /* The topmost layer that holds focus closes first. An inner layer inside the drawer (a
           popover, the configuration overlay, a grid's cell mode) handles Escape itself and cancels
           or stops the key, so the manager never sees it: the drawer closes on the NEXT Escape.
           The evidence drawer closes only while focus is inside it (owner decision on design brief
           7.1, 2026-09-26: at the drawer rung Rail B is a transient overlay; the persistent rail of
           the reference layout is never collapsed by Escape). Focus then returns to the control
           that opened it — the frame's release on hide (App.tsx, focus-return.ts third door). */
        run: (e) => {
          const s = st();
          if (s.paletteOpen) {
            s.setPaletteOpen(false);
            return;
          }
          const drawer = typeof document === "undefined" ? null : document.getElementById("rail-evidence");
          if (s.evidenceDrawerOpen && drawer !== null && drawer.contains(document.activeElement)) {
            e.preventDefault();
            s.setEvidenceDrawerOpen(false);
            announce("Evidence drawer closed.");
            return;
          }
          if (s.inspectorOpen) {
            s.setInspectorOpen(false);
            announce("Inspector closed.");
          }
        },
      },
    ]);
  }
  return () => {
    installedCommands -= 1;
    if (installedCommands === 0) {
      releaseCommands?.();
      releaseCommands = null;
    }
  };
}

export function useAppCommands(): void {
  useEffect(() => installAppCommands(), []);
}
