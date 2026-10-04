/**
 * Fabric3D.tsx — the only place React and the three.js scene meet.
 *
 * The division of labour is the one `contract.ts` describes: React owns the DOM and the
 * investigation state, the scene owns the canvas, and this file translates between them with
 * imperative calls. Nothing here schedules React work per frame, and no pointer or key event is
 * routed through a reconciler before it reaches the scene — that is what keeps the INP budget and
 * the frame budget independent of each other.
 *
 * Three decisions in here are load-bearing and are explained where they are made:
 *   1. the canvas element is created imperatively, one per scene instance (StrictMode safety),
 *   2. store subscriptions are per-slice, so an evidence-pane change cannot re-render the stage,
 *   3. the keyboard contract is a first-class input path, not a fallback for the mouse.
 */
import { useCallback, useEffect, useId, useMemo, useReducer, useRef, useState, useSyncExternalStore } from "react";

import { DEFAULT_GRAPH_OPTIONS, failureImpact, linkFailureImpact, type Certainty, type ProjectionDelta } from "../analysis/blast";
import { cableCountPhrase, hostCableAccount } from "../analysis/port-claims";
import { presentBand } from "../core/band-qualification";
import { collectionSentence } from "../core/collection";
import { deviceById, fabric, findingsByHost, linkById, linksByHost } from "../core/data";
import { applyToDevices, parseQuery } from "../core/query";
import { useInvestigation, useReducedMotion } from "../core/store";
import { kindWords, recognisedSeverity, type Device, type Link, type Trace } from "../core/types";

import type { FabricScene, HighlightState, PickResult, QualityTier, SceneEvent } from "./contract";
import { FabricA11yTree, linkCutSentence } from "./FabricA11yTree";
import { createHoverChannel, FabricLabels, type HoverChannel } from "./FabricLabels";
import { publishSceneStats, releaseSceneStats } from "./telemetry";
import { traceEndOf, type TraceMarkKind } from "./traceEnd";
import { FabricLegend } from "./FabricLegend";
import { CANVAS_ARIA_KEYSHORTCUTS, viewKeyMove } from "./canvasKeys";
import { layoutJob, type FabricLayout, type LayoutJob } from "./layout";
import { exposeSceneForCapture } from "./devHandle";
import { createScene, type FabricSceneEx } from "./scene";
import { setStageOcclusion, type StageOcclusionPx } from "./camera";
import { prepareProceduralMaps, proceduralMapsReady } from "./materials";
import { ALL_CHASSIS_KINDS, chassisPrepared, prepareChassis, type ChassisBuildOptions } from "./geometry/chassis";
import { SCENE_DETAIL } from "./quality";
import { deferPastPresentation } from "../panels/deferPastPaint";
import { verdictStatement } from "../panels/ClaimCard";
import { releaseFocusFrom } from "../app/focus-return";

import "./Fabric3D.css";
import { own } from "../core/own";

/** The chassis tessellation every tier builds with (quality.ts SCENE_DETAIL), for prepareChassis. */
const SCENE_DETAIL_CHASSIS: ChassisBuildOptions = {
  bevelSegments: SCENE_DETAIL.chassisBevelSegments,
  fineDetail: SCENE_DETAIL.chassisFineDetail,
};

/**
 * Counted layout work (layout.ts :: LayoutJob — one unit per cable and per chassis measured against a
 * route) run per slice before the stage yields to the event loop.
 *
 * SCALE (2026-09-28). The layout used to run whole, inside a useMemo, in the render that mounted the
 * stage. After its route stage became index-driven it costs, LABORATORY figures on this 14-core host
 * under load from other agents (review/synth-fleet.mjs --measure): ~15 ms for the 26-device reference
 * sample, ~120-170 ms for a 300-node synthetic fleet and ~0.6-1.2 s for 1 000 (at 100 % load: 610 ms
 * and 4.2 s median) — the last two a stall no keystroke could get through. The owner's LABORATORY
 * budgets (≤ 300 ms at 300 devices, ≤ 2 s at 1 000) are measured IN A REAL BROWSER by
 * review/measure-scale.mjs, from the LAYOUT_MEASURE entry each run leaves below, and gated there on a
 * quiet host (host-env.mjs); the unit suite pins counted work only (vitest.config.ts: no wall clock).
 * MEASURED in Node at ~1.3-1.9 µs a unit, 4 000 units is a slice of
 * ~5-8 ms; in Chromium on the DEV build, under a CPU profiler, with the host at 100 % load, the 300
 * fleet ran as 16 slices of 16-28 ms, none of them a long task (before: one 6.8 s and one 3.5 s task —
 * the dev build's StrictMode lays out twice). Every indivisible step reports the work it did (pinned
 * step by step in scale.test.ts), and the largest one — an ordering pass or the embedding, charged N+E
 * units; a cable's detour ladder is smaller — is pinned below LAYOUT_SLICE_WORK at 300 and 1 000
 * nodes, so a slice there is at most twice its budget. Past N+E = 4 000 (~1 500 campus nodes) a single
 * ordering pass is longer than one slice.
 *
 * The first slice runs synchronously where the layout is requested: the reference sample needs ~1.3 k
 * units (2.3 k with the flattest tier pitch the tests use), so it is laid out before first paint
 * exactly as before, and only a fabric too large for one slice waits — shown as the stage's existing
 * "Building the 3-D fabric" state, since no scene exists until its layout does. Sliced by WORK, not by a
 * clock (the materials.ts precedent), so the layout is the same bytes however the slices fell.
 */
export const LAYOUT_SLICE_WORK = 4000;

/** Yield to the event loop between slices: `scheduler.yield()` where it exists, else a zero timeout
 *  (materials.ts :: prepareProceduralMaps states the difference between the two). */
const yieldToEventLoop = (): Promise<void> => {
  const sched = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  return typeof sched?.yield === "function"
    ? sched.yield()
    : new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });
};

/**
 * The user-timing measure every layout run the stage completes (or fails) leaves on the page's
 * performance timeline: from the run's creation to its last slice, with a `LayoutMeasureDetail`.
 * `review/measure-scale.mjs` reads it to time the layout in a real browser. Pinned in scale.test.ts, so
 * the harness cannot silently time nothing.
 */
export const LAYOUT_MEASURE = "atlas:layout";
/**
 * One measure per SLICE of a run, each with a `LayoutSliceDetail` naming its run: their durations summed
 * are the main-thread time the layout itself took (its compute, without the yields between slices), and
 * the longest is the longest the layout held the main thread at once.
 */
export const LAYOUT_SLICE_MEASURE = "atlas:layout-slice";

/** What one layout run reports on the performance timeline (see LAYOUT_MEASURE). */
export interface LayoutMeasureDetail {
  /** This run's number, which its LAYOUT_SLICE_MEASURE entries carry too. */
  run: number;
  devices: number;
  links: number;
  /** "done" — the layout finished; "failed" — a slice threw (the stage then shows its error boundary). */
  outcome: "done" | "failed";
  /** Counted units of work (layout.ts :: LayoutJob.work) and the slices they ran in. */
  work: number;
  slices: number;
  largestStep: number;
}

/** What one slice reports (see LAYOUT_SLICE_MEASURE). */
export interface LayoutSliceDetail {
  run: number;
  /** 1-based, in the order the slices ran. */
  slice: number;
}

/**
 * THE TIMING IS THE BROWSER'S, NOT THIS FILE'S. Every figure is taken by `performance.mark` and
 * `performance.measure` between named marks, so no clock value is ever read here, and nothing the stage
 * computes or draws can depend on one: the layout is paced by counted WORK (LAYOUT_SLICE_WORK). A UA
 * without user timing (or one that refuses a call) gets no entries, never a failed layout.
 */
const userTiming = (): Performance | null =>
  typeof performance !== "undefined" && typeof performance.mark === "function" && typeof performance.measure === "function"
    ? performance
    : null;
const timelineMark = (name: string): void => {
  try {
    userTiming()?.mark(name);
  } catch {
    /* no entry, no failure */
  }
};
const timelineMeasure = (name: string, start: string, end: string, detail: LayoutMeasureDetail | LayoutSliceDetail): void => {
  try {
    userTiming()?.measure(name, { start, end, detail });
  } catch {
    /* no entry, no failure */
  }
};
const clearTimelineMarks = (...names: string[]): void => {
  try {
    const t = userTiming();
    if (t !== null && typeof t.clearMarks === "function") for (const n of names) t.clearMarks(n);
  } catch {
    /* no entry, no failure */
  }
};

/**
 * THE LAYOUT FAILED — the error the stage throws in render so its error boundary ("The 3-D fabric")
 * reports it. The message says it was the LAYOUT, carries the cause verbatim and says how far the run
 * got, because the boundary prints the message as its detail. `cause` is the original error.
 */
function layoutFailedError(run: LayoutRun): Error {
  const error = run.failure?.error;
  const cause = error instanceof Error ? error.message : String(error);
  return new Error(
    `The layout of the 3-D fabric failed in slice ${run.slices} (${run.job.work} units of work done), so no fabric can be drawn from it: ${cause}`,
    { cause: error },
  );
}

/** Numbers each layout run for its timeline entries. A count, not a clock. */
let layoutRuns = 0;

/** One layout run as the stage drives it: the job, how far it got, and the error any slice threw. */
interface LayoutRun {
  readonly id: number;
  readonly job: LayoutJob;
  readonly devices: number;
  readonly links: number;
  /** Set by the FIRST slice that throws, whatever threw; the run is over from then on. */
  failure: { readonly error: unknown } | null;
  slices: number;
  ended: boolean;
  reported: boolean;
}

const runMark = (run: LayoutRun, what: "start" | "end" | "slice"): string => `${LAYOUT_MEASURE}:${what}#${run.id}`;

function startRun(job: LayoutJob, devices: number, links: number): LayoutRun {
  layoutRuns += 1;
  const run: LayoutRun = { id: layoutRuns, job, devices, links, failure: null, slices: 0, ended: false, reported: false };
  timelineMark(runMark(run, "start"));
  return run;
}

/**
 * One slice of `run`, catching ANY throw: a slice that throws ends the run with `failure` set and
 * returns null. The class is every slice — the synchronous first one in render and each later one in the
 * async loop — because both come through here (verifier V2-1: an uncaught throw in a later slice was an
 * unhandled rejection that left the stage "building" for good).
 */
function runSlice(run: LayoutRun): FabricLayout | null {
  if (run.failure !== null) return null;
  const sliceMark = runMark(run, "slice");
  timelineMark(sliceMark);
  try {
    return run.job.step(LAYOUT_SLICE_WORK);
  } catch (error) {
    run.failure = { error };
    return null;
  } finally {
    run.slices += 1;
    timelineMark(`${sliceMark}:end`);
    timelineMeasure(LAYOUT_SLICE_MEASURE, sliceMark, `${sliceMark}:end`, { run: run.id, slice: run.slices });
    clearTimelineMarks(sliceMark, `${sliceMark}:end`);
    if (run.failure !== null || run.job.done) {
      run.ended = true;
      timelineMark(runMark(run, "end"));
    }
  }
}

/** Leave the run's measure on the performance timeline, once. Never allowed to fail the stage. */
function reportRun(run: LayoutRun): void {
  if (run.reported || !run.ended) return;
  run.reported = true;
  timelineMeasure(LAYOUT_MEASURE, runMark(run, "start"), runMark(run, "end"), {
    run: run.id,
    devices: run.devices,
    links: run.links,
    outcome: run.failure === null ? "done" : "failed",
    work: run.job.work,
    slices: run.slices,
    largestStep: run.job.largestStep,
  });
  clearTimelineMarks(runMark(run, "start"), runMark(run, "end"));
}

/**
 * The layout for these inputs: the finished layout, or null while it is still being computed in
 * slices. A new set of inputs starts a new job; the old one is abandoned where it stands. A slice that
 * THROWS — any slice, the first synchronous one or a later one — is rethrown here, in render, wrapped
 * by `layoutFailedError`, so the stage's error boundary replaces the "Building the 3-D fabric" state
 * with a statement that the layout failed; progress is never shown for a layout that has stopped.
 * Exported so scale.test.ts can drive it without the rest of the stage.
 */
export function useSlicedLayout(
  devices: readonly Device[],
  links: readonly Link[],
  tiers: readonly (readonly string[])[],
): FabricLayout | null {
  const run = useMemo((): LayoutRun => {
    const r = startRun(layoutJob({ devices, links, tiers }), devices.length, links.length);
    runSlice(r);
    return r;
  }, [devices, links, tiers]);
  /* Only a re-render trigger: the layout itself is read from the job, never duplicated in state. */
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (run.job.done || run.failure !== null) {
      reportRun(run);
      return;
    }
    let live = true;
    void (async () => {
      while (live && runSlice(run) === null && run.failure === null) await yieldToEventLoop();
      if (!live) return;
      reportRun(run);
      rerender();
    })();
    return () => {
      live = false;
    };
  }, [run]);
  if (run.failure !== null) throw layoutFailedError(run);
  return run.job.result;
}

/** Pointer travel (CSS px) above which a press is an orbit drag, not a click on a node. */
const DRAG_SLOP = 4;

/** One wheel notch. The contract exposes no dolly verb, so keyboard zoom speaks the scene's
 *  own input language rather than inventing a camera API the scene does not implement. */
const KEY_ZOOM_DELTA = 120;
/** Minimum spacing between two drawing-buffer resizes while a size keeps changing (see the resize effect). */
const RESIZE_SETTLE_MS = 150;

/** Half-angle of the cone an arrow key searches, as a cosine. 60° keeps a diagonal neighbour
 *  reachable while refusing to call a node "to the right" when it is mostly above. */
const DIRECTION_COS_LIMIT = 0.5;

const DIRECTIONS: Readonly<Record<string, readonly [number, number]>> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  /** Screen Y grows downward, so "up" is negative. */
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/* The three endings and the rule that picks the hop they are drawn on live in ./traceEnd, which the
   canvas glyph (flow.ts) asks too: the chip and the glyph cannot mark different hops. */
export type { TraceMarkKind } from "./traceEnd";

interface TraceMark {
  host: string;
  /** The cable the stopped packet would have taken. Only ever resolved for a REFUTED hop. */
  link: string | null;
  kind: TraceMarkKind;
}

export interface Fabric3DProps {
  devices?: Device[];
  links?: Link[];
  tiers?: readonly (readonly string[])[];
  className?: string;
  /** Pin the render quality instead of letting the scene probe for one. */
  quality?: QualityTier;
}

/* ── theme, read live from the document so an explicit choice beats the OS ──── */

const readTheme = (): "dark" | "light" => {
  if (typeof document === "undefined") return "dark";
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "dark" || explicit === "light") return explicit;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
};

function useTheme(): "dark" | "light" {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : null;
    mq?.addEventListener("change", onChange);
    const obs =
      typeof MutationObserver !== "undefined"
        ? new MutationObserver(onChange)
        : null;
    obs?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq?.removeEventListener("change", onChange);
      obs?.disconnect();
    };
  }, []);
  return useSyncExternalStore(subscribe, readTheme, () => "dark");
}

/* ── keyboard traversal over projected screen positions ────────────────────── */

interface Projected {
  id: string;
  x: number;
  y: number;
}

function projectAll(scene: FabricScene, devices: readonly Device[]): Projected[] {
  const out: Projected[] = [];
  for (const d of devices) {
    const p = scene.project(d.id);
    if (p && p.visible) out.push({ id: d.id, x: p.x, y: p.y });
  }
  return out;
}

/**
 * The device nearest the centre of what is currently on screen. The centre is the centroid of the
 * projected nodes rather than the canvas midpoint, because `project()`'s coordinate space is the
 * scene's business and this must not assume it is canvas-local.
 */
function nearestToCentre(nodes: readonly Projected[]): string | null {
  if (nodes.length === 0) return null;
  let cx = 0;
  let cy = 0;
  for (const n of nodes) {
    cx += n.x;
    cy += n.y;
  }
  cx /= nodes.length;
  cy /= nodes.length;
  let best: Projected | null = null;
  let bestD = Infinity;
  for (const n of nodes) {
    const d = Math.hypot(n.x - cx, n.y - cy);
    // Ties break on id so two runs of the same capture select the same node (acceptance F6).
    if (d < bestD || (d === bestD && best !== null && n.id < best.id)) {
      best = n;
      bestD = d;
    }
  }
  return best ? best.id : null;
}

function nextInDirection(
  nodes: readonly Projected[],
  from: Projected,
  dir: readonly [number, number],
): string | null {
  let best: Projected | null = null;
  let bestScore = Infinity;
  for (const n of nodes) {
    if (n.id === from.id) continue;
    const vx = n.x - from.x;
    const vy = n.y - from.y;
    const dist = Math.hypot(vx, vy);
    if (dist < 1) continue;
    const along = vx * dir[0] + vy * dir[1];
    if (along <= 0) continue;
    const cos = along / dist;
    if (cos < DIRECTION_COS_LIMIT) continue;
    // Distance penalised by how far off-axis the candidate sits, so a node straight ahead beats a
    // slightly nearer one at the edge of the cone.
    const score = dist / cos;
    if (score < bestScore || (score === bestScore && best !== null && n.id < best.id)) {
      best = n;
      bestScore = score;
    }
  }
  return best ? best.id : null;
}

/**
 * The stage area an OPEN overlay panel covers, measured from the canvas edges.
 *
 * The rule is structural, not a list of panels: every panel that floats over the stage
 * (`[data-stage-overlay]`) and is actually on screen is measured, and one that spans most of the
 * stage's height is a band on the side it sits on (the Fabric list), while one that only occupies a
 * corner (the Legend) is left to the fixed chrome insets — shrinking the whole framing for a corner
 * would make every view smaller to clear a box that covers none of the fabric's middle.
 */
function measureStageOcclusion(canvas: HTMLCanvasElement): StageOcclusionPx | null {
  const stage = canvas.getBoundingClientRect();
  if (stage.width < 2 || stage.height < 2) return null;
  const host = canvas.closest(".fabric3d") ?? canvas.parentElement;
  if (host === null) return null;
  const out: StageOcclusionPx = { top: 0, bottom: 0, left: 0, right: 0 };
  let any = false;
  for (const el of host.querySelectorAll<HTMLElement>("[data-stage-overlay]")) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue; // visually hidden (the clipped list is 1x1)
    const left = Math.max(r.left, stage.left);
    const right = Math.min(r.right, stage.right);
    const top = Math.max(r.top, stage.top);
    const bottom = Math.min(r.bottom, stage.bottom);
    if (right <= left || bottom <= top) continue;
    const midX = stage.left + stage.width / 2;
    const midY = stage.top + stage.height / 2;
    if ((bottom - top) / stage.height > 0.5) {
      if ((left + right) / 2 < midX) out.left = Math.max(out.left, right - stage.left);
      else out.right = Math.max(out.right, stage.right - left);
      any = true;
    } else if ((right - left) / stage.width > 0.5) {
      if ((top + bottom) / 2 < midY) out.top = Math.max(out.top, bottom - stage.top);
      else out.bottom = Math.max(out.bottom, stage.bottom - top);
      any = true;
    }
  }
  return any ? out : null;
}

function syncStageOcclusion(canvas: HTMLCanvasElement | null): void {
  if (canvas === null) return;
  setStageOcclusion(canvas, measureStageOcclusion(canvas));
}

/** Fallback traversal for the window before the first frame, when nothing projects yet. Clamped
 *  rather than wrapping: a keyboard user in a spatial view should not teleport across the fabric. */
function stepByOrder(devices: readonly Device[], current: string | null, delta: 1 | -1): string | null {
  if (devices.length === 0) return null;
  const at = current === null ? -1 : devices.findIndex((d) => d.id === current);
  if (at < 0) return devices[delta === 1 ? 0 : devices.length - 1]?.id ?? null;
  const next = Math.min(devices.length - 1, Math.max(0, at + delta));
  return devices[next]?.id ?? null;
}

/* ── announcements: a canvas selection is invisible to assistive technology ── */

export function describeDevice(id: string): string {
  const d = deviceById.get(id);
  if (!d) return `Device ${id} selected. No device record in this snapshot.`;
  /* The cable count goes through the link pane's port-dispute detector: AP-floor1 is named on 17
     cable records that all claim its one port Gi0, so "17 links" would state 16 more than can exist. */
  const cables = cableCountPhrase(hostCableAccount(d.host, linksByHost.get(d.host) ?? linksByHost.get(d.id) ?? []));
  /* A finding tally for a device nobody assessed is a zero produced by never having looked, and
     this announcement is the ONLY channel a screen-reader user has here — there is no visible
     panel beside it to carry the qualification. DevicePane already refuses to state this number
     for an uncollected device ("finding counts: not observed ... a severity tally here would
     count an empty search rather than an assessed device"); two surfaces of one product must not
     disagree about whether a number may be stated at all. `?? 0` is kept only on the collected
     branch, where the zero is a real measurement. */
  const findingClause = d.collected
    ? (() => {
        const n = findingsByHost.get(d.host)?.length ?? 0;
        return `${n} ${n === 1 ? "finding" : "findings"}.`;
      })()
    : "Finding count not observed — this device was never collected, so a tally would count an empty search rather than an assessed device.";
  return [
    `${d.host} selected.`,
    `${kindWords(d.kind)}.`,
    /* The engine's collection state (core/collection.ts; acceptance B7): partial and not collected are said as such. */
    collectionSentence(d),
    /* The band as the ONE owner presents it: a favourable band on a host with unassessed scoring
       domains is announced as partial with the gaps named, exactly as DevicePane draws it (B1). */
    presentBand(d).sentence,
    `Role ${d.role ?? "not observed"}.`,
    `Tier ${d.tier === null ? "not observed" : d.tier}.`,
    `Operational state ${d.opStatus}.`,
    `${cables.charAt(0).toUpperCase()}${cables.slice(1)}.`,
    findingClause,
  ].join(" ");
}

function describeLink(id: string): string {
  const l = linkById.get(id);
  if (!l) return `Link ${id} selected. No link record in this snapshot.`;
  return [
    `Link ${l.id} selected.`,
    `${l.a} ${l.aPort ?? "port not observed"} to ${l.b} ${l.bPort ?? "port not observed"}.`,
    `Operational state ${l.opStatus}.`,
    l.speedMbps === null ? "Speed not observed." : `${l.speedMbps} megabit per second.`,
    /* From the same computation the Inspector reads, with its certainty — never the snapshot's
       bridge flag stated as fact (see linkCutSentence in FabricA11yTree.tsx for the measured disagreement on L7). */
    linkCutSentence(l),
  ].join(" ");
}

/* ── highlight derivation ──────────────────────────────────────────────────── */

interface Blocked {
  host: string | null;
  link: string | null;
}

interface BlastOverlay {
  stranded: readonly string[];
  host: string | null;
  link: string | null;
  certainty: Certainty | null;
  /** "" when observed; otherwise the parenthetical every surface of the overlay must carry. */
  qualifier: string;
  /** Set when the question was asked and NOT answered, so the canvas can say so instead of drawing
   *  nothing — a blank overlay reads the same as "this failure strands nothing". */
  undetermined: { subject: string; short: string; why: string } | null;
}

/** Reference-stable "no blast radius", so an unrelated re-render cannot invalidate the memo. */
const NO_BLAST: BlastOverlay = {
  stranded: [],
  host: null,
  link: null,
  certainty: null,
  qualifier: "",
  undetermined: null,
};

/**
 * The certainty clause a stranded count must travel with: empty for an observed radius, otherwise
 * "uncertain" plus every alternate projection whose count differs ("0 under the all-nodes
 * projection"). Built from the analysis result, never restated.
 */
export function blastQualifier(certainty: Certainty, count: number, alternates: readonly ProjectionDelta[]): string {
  if (certainty === "observed") return "";
  const others = alternates
    .filter((a) => a.differs && a.newlyStrandedCount !== count)
    .map((a) => `${a.newlyStrandedCount} under the ${a.options.transit === DEFAULT_GRAPH_OPTIONS.transit ? `unknown-status "${a.options.unknownStatus}"` : a.options.transit} projection`);
  return others.length === 0 ? certainty : `${certainty}; ${others.join(", ")}`;
}
const EMPTY_SET: ReadonlySet<string> = new Set<string>();
/** No blast-radius mark the label layer failed to draw (FabricLabels `onStrandedUnseen`). */
const NO_MARKS_UNSEEN: { outOfView: readonly string[]; covered: readonly string[] } = { outOfView: [], covered: [] };

const NO_BLOCK: Blocked = { host: null, link: null };

/**
 * Where the traced packet's story ends on the fabric, WHICH of the three endings it is, and — for a
 * REFUTED ending alone — the cable the stopped packet would have taken. The hop and the ending are
 * `traceEnd.ts :: traceEndOf`, the same rule the canvas glyph is placed by.
 */
export function traceMarkOf(trace: Trace | null): TraceMark | null {
  const end = traceEndOf(trace);
  if (end === null || trace === null) return null;
  /* The cable is resolved for the REFUTED case alone. It feeds the scene's alarm channel, and
     alarming the cable out of a hop the engine could not decide would restate the same overclaim
     one object further along. */
  let link: string | null = null;
  const stop = trace.hops[end.index];
  if (end.kind === "blocked" && stop !== undefined && stop.nextHost !== null) {
    const candidates = linksByHost.get(stop.host) ?? [];
    const match = candidates.find((l) => l.a === stop.nextHost || l.b === stop.nextHost);
    link = match ? match.id : null;
  }
  return { host: end.host, link, kind: end.kind };
}

/**
 * The verdict chip the label layer draws for a trace: on which host, which of the three endings, and
 * the BOUNDS it must carry (acceptance B2). The chip repeats the trace's verdict away from its claim
 * card — on the Evidence surface at 1000x800 the card is display:none and the fabric is what the reader
 * sees — so it travels with the claims owner's own sentence for the trace (ClaimCard
 * `verdictStatement(trace).sentence`: the word, the scope clause, the badge and the caveat count),
 * never a restatement. `src/app/verdict-scope.b2.test.tsx` holds every suggested flow's chip to that.
 */
export function fabricVerdictChipOf(trace: Trace | null): { id: string; kind: TraceMarkKind; bounds: string } | null {
  const mark = traceMarkOf(trace);
  if (mark === null || trace === null) return null;
  return { id: mark.host, kind: mark.kind, bounds: verdictStatement(trace).sentence };
}

/**
 * The scene's alarm channel, which is the CANVAS treatment (a red outline on the chassis).
 *
 * Only a REFUTED hop earns it. `blockedHost` is how a reader tells a stopped flow from one that
 * was not stopped, and the contract's own word for it is "the failing element" — an undecided hop
 * is not a failing element, and a delivered one certainly is not. The other two endings are
 * carried by the label layer's own marks, which say in words which of the three this is.
 */
const blockedOf = (mark: TraceMark | null): Blocked =>
  mark !== null && mark.kind === "blocked" ? { host: mark.host, link: mark.link } : NO_BLOCK;

/* ── component ─────────────────────────────────────────────────────────────── */

/* determinism: the `quality` prop is the tier a CALLER requests, not one measured from frames. */
export function Fabric3D({
  devices = fabric.devices,
  links = fabric.links,
  tiers = fabric.tiers,
  className,
  quality,
}: Fabric3DProps = {}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasSlotRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  /* `FabricSceneEx`, not `FabricScene`: the diagnostics the HUD reports (a standing draw-call
     breach among them) are declared on the widened handle scene.ts returns. Typed as the frozen
     contract, `overBudget` would be reachable only through a cast, which is how it stayed
     invisible while the product breached its ceiling on every traced frame. */
  const sceneRef = useRef<FabricSceneEx | null>(null);

  const helpId = useId();
  const legendId = useId();
  /** Describes the Fabric-list toggle: see the note beside that button. */
  const treeNoteId = useId();

  /* Narrow slices only. A change to the evidence tab, the palette or the finding list must not
     re-render the stage at all, let alone touch the scene. */
  const deviceId = useInvestigation((s) => s.deviceId);
  const deviceOrigin = useInvestigation((s) => s.deviceOrigin);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);
  const trace = useInvestigation((s) => s.trace);
  const hopIndex = useInvestigation((s) => s.hopIndex);
  const query = useInvestigation((s) => s.query);
  const severities = useInvestigation((s) => s.severities);
  const roles = useInvestigation((s) => s.roles);
  const onlyUncollected = useInvestigation((s) => s.onlyUncollected);

  const theme = useTheme();
  const reducedMotion = useReducedMotion();
  /* The scene reads the preference once at construction through this ref; a later toggle reaches the
     running scene through `setReducedMotion` (below), never by rebuilding it. */
  const reducedMotionRef = useRef(reducedMotion);
  reducedMotionRef.current = reducedMotion;

  const hover = useMemo<HoverChannel>(() => createHoverChannel(), []);
  /* null while a fabric too large for one slice is still being laid out (see LAYOUT_SLICE_WORK). */
  const layout = useSlicedLayout(devices, links, tiers);
  const layoutReady = layout !== null;

  const [sceneEpoch, setSceneEpoch] = useState(0);
  const [qualityTier, setQualityTier] = useState<QualityTier | null>(quality ?? null);
  const [treeVisible, setTreeVisible] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [sceneError, setSceneError] = useState<string | null>(null);
  /*
   * The procedural map bytes are generated in yielding slices BEFORE the scene is built, instead of
   * inside `createScene`, where they were one ~0.5-0.8 s synchronous block in the mount effect
   * (acceptance E5; see materials.ts :: generateProceduralPixels). Until they exist the stage has no
   * scene, which the stage already reports as "Building the 3-D fabric" (surfaces.tsx: a mounted
   * fabric with null stats counts as warming), so the wait is communicated, not frozen.
   */
  /* The chassis geometry follows the same rule (geometry/chassis.ts :: prepareChassis): it was ~a
     quarter of the one long createScene task a cold-load keystroke waited behind (E5). It is
     tier-independent, so it is prepared at the scene's own SCENE_DETAIL, one kind per slice. */
  const [mapsReady, setMapsReady] = useState(
    () => proceduralMapsReady() && chassisPrepared(ALL_CHASSIS_KINDS, SCENE_DETAIL_CHASSIS),
  );
  useEffect(() => {
    if (mapsReady) return;
    let live = true;
    /* Every kind, not only the ones on screen: readiness then cannot depend on the device list,
       and the one kind not in use costs one more short slice. */
    void prepareProceduralMaps()
      .then(() => prepareChassis(ALL_CHASSIS_KINDS, SCENE_DETAIL_CHASSIS))
      .then(() => {
        if (live) setMapsReady(true);
      });
    return () => {
      live = false;
    };
  }, [mapsReady]);
  /**
   * A STANDING draw-call breach, with the numbers that make it checkable.
   *
   * `null` is "no standing breach", which is the normal state. This is React state rather than a
   * dev-only console line because acceptance E4 says degradation is explicit and never silent, and
   * a `console.error` guarded by `import.meta.env.DEV` is absent from every shipped chunk — so the
   * only report of a live breach was one nobody running the product could ever see.
   */
  const [breach, setBreach] = useState<{ calls: number; budget: number; outlines: number } | null>(null);

  /* Latest values the construction path needs, so the create effect can depend on almost nothing
     and still build the scene from current data. */
  const optsRef = useRef({ devices, links, layout, theme, quality });
  optsRef.current = { devices, links, layout, theme, quality };
  const devicesRef = useRef(devices);
  devicesRef.current = devices;

  /* True while the stage holds a primary press on the canvas (set by the scene-lifetime effect's
     pointer handlers). One rule for BOTH hover paths: a held pointer is orbiting, not pointing. */
  const pressHeldRef = useRef(false);

  const onEvent = useCallback((e: SceneEvent) => {
    switch (e.type) {
      case "pick":
        /* NOT applied. The stage's own pointerup (below, in the scene-lifetime effect) is the ONE
           path a canvas click selects through; it carries the drag slop and the warm-up gate.
           RESPONSIVENESS FIX (acceptance E2/E3, journey 2): both used to apply the same click, so
           every canvas pick was two raycasts and two store writes. Worse, the first write's React
           commit ran in the microtask checkpoint BETWEEN the two pointerup listeners, and the second
           listener's hit-test then forced a layout of everything that commit had just changed —
           measured on the release build as a second `CANVAS.onpointerup` script with 5-45 ms of
           `forcedStyleAndLayoutDuration` on every device click. */
        break;
      case "hover":
        /* SCALE (2026-09-28). The scene flushes its own hover every frame, drag or not; the stage's
           own path already drops hover while a press is held ("hover during an orbit drag is
           noise"), and this one did not. Every change of the hovered device re-renders the label
           layer, which renders one element per device: MEASURED on the 300 fleet (dev build, CPU
           profile) that was ~3-3.7 s of every 6 s orbit drag, as the pointer swept across chassis.
           scale.test.ts pins it by React commits. */
        if (pressHeldRef.current) break;
        hover.set(
          e.result === null || !isDrawn(sceneRef.current)
            ? { deviceId: null, linkId: null }
            : e.result.kind === "device"
              ? { deviceId: e.result.id, linkId: null }
              : { deviceId: null, linkId: e.result.id },
        );
        break;
      case "stats": {
        /* The warm-up publishes its end on the frame it ends (scene.ts resets the throttle), so
           this is where a finished warm-up is latched even if no pointer asks in between. */
        notePresented(sceneRef.current);
        // Only the tier and a STANDING budget breach are surfaced, and only when they change: fps
        // is a per-frame value and rendering it would put React back on the frame path it was kept
        // off. The stats event fires at most twice a second, so this costs nothing per frame.
        /* determinism: the tier is picked from frame times and reaches the DOM as a word (the
           status text below). review/capture.mjs fails any capture whose tier is not "high", so a
           comparable capture always carries the same word. */
        setQualityTier((prev) => (prev === e.stats.quality ? prev : e.stats.quality));
        /* Read the WIDENED stats off the handle. `SceneEvent` is declared in the frozen contract
           and its payload is typed `SceneStats`, which does not name `overBudget`; the handle
           does. Reading it here rather than casting `e.stats` is what keeps this type-checked. */
        const ex = sceneRef.current?.stats();
        /* The whole reading, to the one channel the status bar subscribes to. Before this, every
           field except the tier died here and the bar said the subsystem had never reported a
           frame while it was reporting one twice a second. */
        publishSceneStats(ex ?? null);
        setBreach((prev) => {
          const next =
            ex === undefined || !ex.overBudget
              ? null
              : { calls: ex.drawCalls, budget: ex.drawCallBudget, outlines: ex.activeOutlines };
          if (prev === next) return prev;
          if (prev !== null && next !== null && prev.calls === next.calls && prev.budget === next.budget) {
            return prev;
          }
          return next;
        });
        break;
      }
      case "camera":
        break;
    }
  }, [hover]);

  /*
   * Scene lifetime. The canvas element is created here rather than rendered by React because a
   * disposed WebGL context cannot be re-acquired on the same canvas element: under StrictMode's
   * mount/unmount/mount the second scene would come up black on a React-owned canvas, and the
   * failure is silent. One canvas per scene instance makes the double-invoke safe by construction,
   * and removing it on cleanup is what proves no context leaked.
   *
   * `reducedMotion` is deliberately NOT a dependency: the scene is built with the preference current at
   * construction (read through `reducedMotionRef`), and a later toggle reaches the running scene through
   * its `setReducedMotion` (the effect after this one). Rebuilding the scene on a toggle would take a
   * running tier cross-fade down with the canvas in one frame (C5-R2-1).
   */
  useEffect(() => {
    const slot = canvasSlotRef.current;
    /* No scene before its layout: a scene built on no geometry would draw nothing and license picks. */
    if (!slot || !mapsReady || !layoutReady) return;
    /* determinism: `o.quality` is the CALLER's requested tier (a prop), not a measurement. */
    const o = optsRef.current;
    const builtLayout = o.layout;
    if (builtLayout === null) return;

    const canvas = slot.ownerDocument.createElement("canvas");
    canvas.className = "fabric3d__canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-label", "Network fabric, three-dimensional view");
    canvas.setAttribute("aria-describedby", helpId);
    canvas.setAttribute("aria-keyshortcuts", CANVAS_ARIA_KEYSHORTCUTS);
    canvas.dataset.testid = "fabric3d-canvas";
    canvas.dataset.hovering = "false";
    slot.appendChild(canvas);
    canvasRef.current = canvas;

    let scene: FabricSceneEx;
    try {
      scene = createScene(
        canvas,
        {
          devices: o.devices,
          links: o.links,
          layout: builtLayout,
          theme: o.theme,
          reducedMotion: reducedMotionRef.current,
          ...(o.quality ? { quality: o.quality } : {}),
        },
        { onEvent },
      );
    } catch (err) {
      // No WebGL, a lost context, or a driver that refuses the request. The fabric is still fully
      // available through the tree, and saying so is the honest answer; throwing here would take
      // the whole investigation down with the renderer. The canvas is a tab stop, so focus leaves it
      // through the owner before it goes (focus-return.ts, third door; a no-op when it is elsewhere).
      releaseFocusFrom(canvas, null);
      canvas.remove();
      canvasRef.current = null;
      setSceneError(err instanceof Error ? err.message : String(err));
      return;
    }
    setSceneError(null);
    sceneRef.current = scene;

    /* Publish the handle for the review harnesses (dev/test builds only; a no-op in production).
       `review/capture.mjs` waits on `stats().converged` before screenshotting, so a frame is taken
       at a DEFINED moment rather than after a fixed sleep — a sleep produces a different frame on a
       different machine and silently breaks the byte-identical-capture requirement (acceptance F6).
       `review/measure-inp.mjs` and `review/probe-fabric.mjs` read it too. */
    const releaseHandle = exposeSceneForCapture(scene);

    /* ── input, attached directly to the canvas ── */

    const press = { down: false, moved: false, x: 0, y: 0 };
    let hoverFrame = 0;
    let hoverAt: { x: number; y: number } | null = null;

    const pickAt = (x: number, y: number): PickResult | null => scene.pick(x, y);

    const runHover = () => {
      hoverFrame = 0;
      if (!hoverAt) return;
      const r = isDrawn(scene) ? pickAt(hoverAt.x, hoverAt.y) : null;
      hover.set(
        r === null
          ? { deviceId: null, linkId: null }
          : r.kind === "device"
            ? { deviceId: r.id, linkId: null }
            : { deviceId: null, linkId: r.id },
      );
      scene.setHover(r && r.kind === "device" ? r.id : null, r && r.kind === "link" ? r.id : null);
      canvas.dataset.hovering = r === null ? "false" : "true";
    };

    const onPointerDown = (e: PointerEvent) => {
      press.down = true;
      pressHeldRef.current = true;
      press.moved = false;
      press.x = e.clientX;
      press.y = e.clientY;
      // A canvas does not take focus from a press in every browser, and the keyboard contract is
      // useless if a click leaves focus behind on whatever was focused before.
      canvas.focus({ preventScroll: true });
    };

    const onPointerMove = (e: PointerEvent) => {
      if (press.down) {
        if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > DRAG_SLOP) press.moved = true;
        return; // hover during an orbit drag is noise
      }
      hoverAt = { x: e.clientX, y: e.clientY };
      // Coalesce to one hit-test per frame: pointermove fires far faster than the scene redraws.
      if (hoverFrame === 0) hoverFrame = requestAnimationFrame(runHover);
    };

    const endPress = () => {
      press.down = false;
      press.moved = false;
      pressHeldRef.current = false;
    };

    /* ── a canvas click: acknowledged on the canvas now, committed everywhere after it is shown ──
     *
     * RESPONSIVENESS FIX (acceptance E3, 2026-09-23). The click used to write the store inside its
     * own input task, and a `useSyncExternalStore` write is urgent: React rendered and committed
     * every surface subscribed to the selection — the label layer, the findings grid, the device
     * pane — before the handler returned, and the frame that presented the click then paid their
     * style, layout and paint. MEASURED on the release build, fresh browser per trial (Intel iGPU,
     * ANGLE D3D11): the first click on core2 put 51-100 ms on its own interaction path in every
     * trial — `CANVAS.onpointerup` 13-37 ms of script, then 30-56 ms of rendering in that frame.
     *
     * Design brief 8.3 rule 3, exactly as PriorityQueue applies it to a finding click: the surface
     * the reader acted on acknowledges from its own state inside the input task — here the scene's
     * selection treatment, drawn in the very next frame (`acknowledgeSelection`) — and the shared
     * write that re-aims every other surface runs in a task of its own once the browser reports that
     * acknowledgement PRESENTED (`deferPastPresentation`: the click's own Event Timing entry, with a
     * frame-count fallback). A fixed two-frame wait was measured too short on the reference iGPU,
     * which presented the click 56-80 ms on: no task over 50 ms touched the path, but the commit's
     * 52-72 ms frame overlapped the click's window in 21 of 21 fresh-browser trials. The one pending write is
     * superseded by the next canvas click, and cancelled by ANY other change to the selection made
     * before it lands (a key, a grid row, the palette), after which the canvas is put back in step
     * with the choice that won — a stale click must never overwrite a newer choice. */
    let pendingCommit: { cancel: () => void } | null = null;
    const cancelPendingCommit = (): void => {
      pendingCommit?.cancel();
      pendingCommit = null;
    };
    const commitCanvasPick = (r: PickResult | null, e: PointerEvent): void => {
      cancelPendingCommit();
      const ack = scene as Partial<Pick<FabricSceneEx, "acknowledgeSelection">>;
      const deviceSel = r !== null && r.kind === "device" ? r.id : null;
      const linkSel = r !== null && r.kind === "link" ? r.id : null;
      if (typeof ack.acknowledgeSelection === "function") ack.acknowledgeSelection(deviceSel, linkSel);
      else scene.setSelection(deviceSel, linkSel);
      const entry = { cancel: (): void => undefined };
      pendingCommit = entry;
      entry.cancel = deferPastPresentation(e.type, e.currentTarget, () => {
        if (pendingCommit === entry) pendingCommit = null;
        applyPick(r);
      });
    };
    const stopWatchingSelection = useInvestigation.subscribe((next, prev) => {
      if (pendingCommit === null) return;
      if (next.deviceId === prev.deviceId && next.linkId === prev.linkId) return;
      cancelPendingCommit();
      scene.setSelection(next.deviceId, next.linkId);
    });

    const onPointerUp = (e: PointerEvent) => {
      const wasClick = press.down && !press.moved;
      endPress();
      if (!wasClick || !isDrawn(scene)) return;
      commitCanvasPick(pickAt(e.clientX, e.clientY), e);
    };

    const onPointerLeave = () => {
      endPress();
      hoverAt = null;
      if (hoverFrame !== 0) {
        cancelAnimationFrame(hoverFrame);
        hoverFrame = 0;
      }
      hover.set({ deviceId: null, linkId: null });
      scene.setHover(null, null);
      canvas.dataset.hovering = "false";
    };

    const onDoubleClick = (e: MouseEvent) => {
      if (!isDrawn(scene)) return;
      const r = pickAt(e.clientX, e.clientY);
      if (r && r.kind === "device") {
        useInvestigation.getState().selectDevice(r.id, { surface: "fabric" });
        scene.focusDevice(r.id);
      }
    };

    const zoom = (direction: 1 | -1) => {
      if (typeof WheelEvent === "undefined") return;
      const rect = canvas.getBoundingClientRect();
      canvas.dispatchEvent(
        new WheelEvent("wheel", {
          deltaY: direction * KEY_ZOOM_DELTA,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
          bubbles: true,
          cancelable: true,
        }),
      );
    };

    const onKeyDown = (e: KeyboardEvent) => {
      /* VIEW KEYS FIRST (acceptance D1): Shift+arrows orbit and Alt+arrows pan, as a drag of a fixed
         fraction of the canvas height (canvasKeys.ts owns the scheme and the step). They go through
         the scene's orbitBy/panBy, which replay OrbitControls' own drag handlers — the pointer's
         camera path — so a key press and a drag of that many pixels land on the same pose, reduced
         motion included (camera.keyboard.test.ts). Checked before the modifier bail-out below,
         because Alt is one of their modifiers. */
      const view = viewKeyMove(e, canvas.clientHeight);
      if (view !== null) {
        e.preventDefault();
        const ex = scene as Partial<Pick<FabricSceneEx, "orbitBy" | "panBy">>;
        if (view.verb === "orbit") ex.orbitBy?.(view.dx, view.dy);
        else ex.panBy?.(view.dx, view.dy);
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const st = useInvestigation.getState();
      const dir = own(DIRECTIONS, e.key);
      if (dir) {
        e.preventDefault();
        const nodes = projectAll(scene, devicesRef.current);
        const current = st.deviceId;
        let next: string | null;
        if (nodes.length === 0) {
          next = stepByOrder(devicesRef.current, current, dir[0] + dir[1] > 0 ? 1 : -1);
        } else {
          const from = current === null ? null : (nodes.find((n) => n.id === current) ?? null);
          next = from === null ? nearestToCentre(nodes) : nextInDirection(nodes, from, dir);
        }
        if (next !== null) st.selectDevice(next, { surface: "fabric" });
        return;
      }
      switch (e.key) {
        case "Enter":
          e.preventDefault();
          if (st.deviceId !== null) scene.focusDevice(st.deviceId);
          break;
        case "Escape":
          // Only swallow Escape when there is a selection to clear, so an overlay above the stage
          // still receives it.
          if (st.deviceId !== null || st.linkId !== null) {
            e.preventDefault();
            st.selectDevice(null);
            st.selectLink(null);
          }
          break;
        case "Home":
          e.preventDefault();
          syncStageOcclusion(canvasRef.current);
          scene.resetCamera();
          break;
        case "+":
        case "=":
          e.preventDefault();
          zoom(-1);
          break;
        case "-":
        case "_":
          e.preventDefault();
          zoom(1);
          break;
        default:
          break;
      }
    };

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerLeave);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("dblclick", onDoubleClick);
    canvas.addEventListener("keydown", onKeyDown);

    setSceneEpoch((n) => n + 1);

    return () => {
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerLeave);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("dblclick", onDoubleClick);
      canvas.removeEventListener("keydown", onKeyDown);
      stopWatchingSelection();
      cancelPendingCommit();
      /* A scene released mid-press must not leave the next one believing a press is held. */
      pressHeldRef.current = false;
      if (hoverFrame !== 0) cancelAnimationFrame(hoverFrame);
      releaseHandle();
      /* "Not observed" has to mean it: a released scene must not leave its last reading on screen
         as though it were live. */
      releaseSceneStats();
      sceneRef.current = null;
      canvasRef.current = null;
      scene.dispose();
      /* A rebuild (new maps, a new hover channel) removes the focusable canvas the reader may be on: focus goes
         to the fabric's region first (focus-return.ts, third door), never to <body>. */
      releaseFocusFrom(canvas, null);
      canvas.remove();
    };
  }, [onEvent, hover, helpId, mapsReady, layoutReady]);

  /* A reduced-motion toggle reaches the running scene by exactly one route: its setter. */
  useEffect(() => {
    sceneRef.current?.setReducedMotion(reducedMotion);
  }, [reducedMotion]);

  /* ── data: replaced imperatively, never by rebuilding the scene — while the layout keeps up ──
 *
 * New inputs whose layout fits the first, synchronous slice (the reference sample, and any fabric of
 * that order) reach the running scene through setData below. New inputs too large for one slice make
 * `layoutReady` false for the commit that brings them: the scene-lifetime effect above then RELEASES
 * the scene (the stage reads as "Building the 3-D fabric", as on first mount) and builds a new one
 * from the new layout once it exists. Deliberately: an old scene left drawing would be handed the new
 * selection, trace and blast radius against the old fabric, and new devices with the old geometry
 * would be a picture of neither (scale.test.ts pins the swap). */

  const appliedRef = useRef<{
    scene: FabricScene | null;
    devices: Device[] | null;
    links: Link[] | null;
    layout: unknown;
  }>({ scene: null, devices: null, links: null, layout: null });

  useEffect(() => {
    const scene = sceneRef.current;
    /* No layout for these inputs yet: the scene-lifetime effect has released the scene and will build
       a new one from the layout when it exists (see the section note above), so there is nothing to
       update in place — and new devices with the old geometry would be a picture of neither. */
    if (!scene || layout === null) return;
    const prev = appliedRef.current;
    // A scene that was just constructed already holds this data; calling setData on it would throw
    // away GPU resources the contract asks to reuse.
    const isFresh = prev.scene !== scene;
    if (!isFresh && (prev.devices !== devices || prev.links !== links || prev.layout !== layout)) {
      scene.setData(devices, links, layout);
      /* A topology change rebuilds the graph and restarts the warm-up: the frame still on screen
         is a picture of the OLD topology and no longer licenses a pointer pick (see isDrawn). A
         same-topology update restarts nothing and keeps the latch. */
      if ((scene.stats().warmupStage ?? null) !== null) presented.delete(scene);
    }
    appliedRef.current = { scene, devices, links, layout };
  }, [sceneEpoch, devices, links, layout]);

  useEffect(() => {
    sceneRef.current?.setSelection(deviceId, linkId);
  }, [sceneEpoch, deviceId, linkId]);

  useEffect(() => {
    sceneRef.current?.setTrace(trace, hopIndex);
  }, [sceneEpoch, trace, hopIndex]);

  useEffect(() => {
    sceneRef.current?.setTheme(theme);
  }, [sceneEpoch, theme]);

  useEffect(() => {
    if (quality) sceneRef.current?.setQuality(quality);
  }, [sceneEpoch, quality]);

  /* ── blast radius, on the fabric ─────────────────────────────────────────────
   *
   * A6 asks that selecting a device or a link show what becomes unreachable. It was shown — in the
   * Inspector, as a list — and drawn nowhere. `HighlightState` was built from the query, the
   * severity and role filters and the selected finding, and from nothing else: selecting core1,
   * which this application itself says strands nine hosts, marked core1's label and left the nine
   * rendered exactly like every other node. Measured before this existed: core1 (9 stranded) vs
   * dist1 (no partition) differed by 1.29 % of the canvas, and two no-partition selections
   * differed from each other by 0.61 % — i.e. the partition case was indistinguishable from noise.
   *
   * It goes through `blockedHost` / `blockedLink` deliberately: the contract names that pair "the
   * failing element in a trace OR BLAST ANALYSIS, drawn with the alarm treatment", so this is the
   * channel it was designed for, not a filter-emphasis channel borrowed for a second purpose. The
   * stranded hosts join the emphasis set so they lift out of the dimmed field, and their labels
   * carry a `stranded` mark of their own (FabricLabels) so the class is legible without colour and
   * cannot be confused with a filter match.
   *
   * The same `failureImpact` / `linkFailureImpact` the Inspector reads, so the two surfaces cannot
   * tell different stories about one graph.
   */
  /* A5: ONE QUESTION PER PICTURE. A trace re-aims the selection to its active hop's host (App.tsx,
     acceptance A4), and that selection used to switch the blast radius on as a side effect: the
     trace's own source switch read "⊘ STRANDED" and core1 read "⚠ CUT POINT" beside
     "✓ DELIVERED HERE" — a failure hypothesis nobody asked, drawn over the packet's answer. While
     the selection IS the trace's hop, the question on screen is the trace, so no blast radius is
     drawn. Selecting any other device (or a link) is an explicit new question and draws it as
     before; the Inspector's text is unaffected either way.

     "IS the trace's hop" is WHO made the selection, not WHICH device it names (acceptance A6,
     overturned at 70bea72). It used to be `deviceId === the hop's host`, which the trace's own
     re-aim satisfies — and so do a palette selection of that host, a click on it, the fabric list and
     a restored `d=`: selecting core1 during a trace drew 0 of its 9 stranded hosts until a button was
     pressed. The shell now says which it was (store.ts SelectionOrigin, set "hop" only by App.tsx's
     re-aim; `selectDevice` defaults to explicit), and only the trace's own selection is quiet. */
  const activeHopHost = trace === null || hopIndex === null ? null : (trace.hops[hopIndex]?.host ?? null);
  const selectionIsTraceHop =
    activeHopHost !== null &&
    deviceOrigin === "hop" &&
    linkId === null &&
    deviceId !== null &&
    (deviceId === activeHopHost || deviceById.get(deviceId)?.host === activeHopHost);
  /* A6 over A5, reconciled rather than traded (2026-09-21). Suppressing the blast radius for the
     trace's hop meant that during any investigation the fabric's most important cut point — core1,
     which strands 9 hosts and which every flow in this snapshot crosses or neighbours — could not
     show its blast radius on the fabric at all; only the Inspector said it. The default stays A5's
     "one question per picture", but the other question is now ONE explicit press away, on the
     fabric itself, and the control only exists when the hop host really is a cut point. It resets
     whenever the hop changes, so a stale hypothesis is never left drawn over a new packet. */
  const [hopBlastShown, setHopBlastShown] = useState(false);
  useEffect(() => {
    setHopBlastShown(false);
  }, [activeHopHost, trace]);
  /* The hop's blast radius, WITH its certainty (2026-09-22 critic, B1). The button used to quote
     newlyStranded alone — "core1 strands 9" — while the same computation said `uncertain`: core1
     Gi1/0/40 is on two cables of which at most one is real, and the all-nodes projection strands 0.
     A count stated without the certainty the analysis attached to it is a stronger claim than the
     analysis makes, so the label, title and marks now carry it. */
  const hopBlast = useMemo(
    () => (selectionIsTraceHop && activeHopHost !== null ? failureImpact(activeHopHost) : null),
    [selectionIsTraceHop, activeHopHost],
  );
  const hopBlastCount = hopBlast?.newlyStranded.length ?? 0;
  const hopBlastQualifier = hopBlast === null ? "" : blastQualifier(hopBlast.certainty, hopBlastCount, hopBlast.alternateProjections);
  const blast = useMemo((): BlastOverlay => {
    if (selectionIsTraceHop && !hopBlastShown) return NO_BLAST;
    const pick = (
      r: { newlyStranded: string[]; certainty: Certainty; alternateProjections: ProjectionDelta[]; caveats: string[] },
      host: string | null,
      link: string | null,
      subject: string,
    ): BlastOverlay => {
      /* Not determinable is NOT "strands nothing": it is stated on the canvas, never drawn as blank. */
      if (r.certainty === "not-determinable") {
        const why = r.caveats[0] ?? "the analysis declined to compute it";
        const short = host !== null && deviceById.get(host)?.collected === false ? "device never collected" : "see the Inspector for why";
        return { ...NO_BLAST, undetermined: { subject, short, why } };
      }
      if (r.newlyStranded.length === 0) return NO_BLAST;
      return {
        stranded: r.newlyStranded,
        host,
        link,
        certainty: r.certainty,
        qualifier: blastQualifier(r.certainty, r.newlyStranded.length, r.alternateProjections),
        undetermined: null,
      };
    };
    if (linkId !== null) return pick(linkFailureImpact(linkId), null, linkId, linkId);
    if (deviceId !== null) {
      const host = deviceById.get(deviceId)?.host ?? deviceId;
      return pick(failureImpact(host), host, null, host);
    }
    return NO_BLAST;
  }, [deviceId, linkId, selectionIsTraceHop, hopBlastShown]);

  /** Stranded host NAMES resolved to device ids, which is what the highlight set is keyed on. */
  const strandedIds = useMemo((): ReadonlySet<string> => {
    if (blast.stranded.length === 0) return EMPTY_SET;
    const want = new Set(blast.stranded);
    const out = new Set<string>();
    for (const d of devices) if (want.has(d.host) || want.has(d.id)) out.add(d.id);
    return out;
  }, [blast, devices]);

  /* EVERY STRANDED HOST IS ACCOUNTED FOR ON THE FABRIC (acceptance A6, refuted at 70bea72). A
     selection never moves the camera (A4), so with the view framed on a trace, core2's blast radius
     marked 5 of its 8 stranded hosts and the other 3 projected off the canvas with no mark, no count
     and nothing saying so. The label layer reports which stranded hosts it could NOT draw this frame
     (off the canvas, behind a chassis, or dropped) — only when that set changes — and the stage
     states the count and names them.
     A mark DRAWN UNDER something is not shown either (A6 refuter, 390x844: access10's and access12's
     STRANDED? marks lay under other labels and core1's CUT POINT under the HUD while this note said
     "all 9 marked"). The layer reports those apart, and the note names them apart. */
  const [marksUnseen, setMarksUnseen] = useState<{ outOfView: readonly string[]; covered: readonly string[] }>(NO_MARKS_UNSEEN);
  const onStrandedUnseen = useCallback(
    (outOfView: readonly string[], covered: readonly string[]) => setMarksUnseen({ outOfView, covered }),
    [],
  );
  const hostsOf = useCallback(
    (ids: readonly string[]): string[] =>
      blast.stranded.length === 0 ? [] : ids.filter((id) => strandedIds.has(id)).map((id) => deviceById.get(id)?.host ?? id),
    [blast, strandedIds],
  );
  const unseenHosts = useMemo(() => hostsOf(marksUnseen.outOfView), [hostsOf, marksUnseen]);
  const coveredHosts = useMemo(() => hostsOf(marksUnseen.covered), [hostsOf, marksUnseen]);
  /** The cut point's own mark, when the layer could not draw it legibly: how, or null when it is shown. */
  const cutMarkUnseen = useMemo((): "out of view" | "under other labels" | null => {
    const cutId = blast.host === null ? null : (devices.find((d) => d.host === blast.host || d.id === blast.host)?.id ?? null);
    if (cutId === null) return null;
    if (marksUnseen.outOfView.includes(cutId)) return "out of view";
    if (marksUnseen.covered.includes(cutId)) return "under other labels";
    return null;
  }, [blast, devices, marksUnseen]);

  /** The traced packet's ending, decided once and shared by the canvas channel and the label layer
   *  so the two cannot tell different stories about one trace. */
  const traceMark = useMemo(() => traceMarkOf(trace), [trace]);

  const highlight = useMemo<HighlightState | null>(() => {
    /* The scene's alarm halo stays TRACE-ONLY, deliberately, even though the contract would let a
       blast analysis fill the same field. The halo is how a reader tells a denied flow from a
       delivered one, and the cut points of this fabric include the very hosts most traces pass
       through: routing the blast radius through it made a delivered trace and a denied one differ
       by the label alone again — the same defect, moved. A cut point is a hypothesis, a blocked
       hop is a fact about the packet in front of you; they get different channels. The blast
       radius is drawn by the stranded emphasis set and by the label marks below. */
    const blocked = blockedOf(traceMark);
    const filtered =
      query.trim().length > 0 || severities.size > 0 || roles.size > 0 || onlyUncollected;
    /* A4: a selected finding must re-aim the fabric, because the fabric is the surface that answers
       "where in the network is this?". Before this, findingId was not an input to this memo at all,
       so selecting a finding produced a BYTE-IDENTICAL canvas — the fabric could not locate a
       finding, which is the one thing it is there for.
       Emphasis only: the finding's hosts join the highlight set and everything else recedes. The
       camera is deliberately untouched — re-aiming is not a flight, and moving the camera on every
       queue click would lose the pose the reader is working in. */
    const finding =
      findingId === null ? null : (fabric.findings.find((f) => f.id === findingId) ?? null);
    if (!filtered && finding === null && strandedIds.size === 0) {
      return blocked.host === null && blocked.link === null
        ? null
        : { hosts: [], links: [], blockedHost: blocked.host, blockedLink: blocked.link };
    }

    /* The filter contributes matches only when a filter is actually set. With no filter and a
       finding selected, the emphasis set is the finding's devices alone. */
    let matched: Device[] = filtered ? applyToDevices(devices, parseQuery(query)).items : [];
    // A device whose role was never observed is not "not in the access role"; it is unknown. It
    // falls out of a role filter the same way, but it is dimmed rather than hidden, so the viewer
    // can still see that the fabric holds devices the filter could not decide about.
    if (roles.size > 0) matched = matched.filter((d) => d.role !== null && roles.has(d.role));
    if (onlyUncollected) matched = matched.filter((d) => !d.collected);
    if (severities.size > 0) {
      const hosts = new Set<string>();
      for (const f of fabric.findings) {
        /* The filter holds severities the vocabulary names; an unrecognised one is never among them. */
        if (!recognisedSeverity(f.severity) || !severities.has(f.severity)) continue;
        for (const h of f.devices) hosts.add(h);
      }
      matched = matched.filter((d) => hosts.has(d.host) || hosts.has(d.id));
    }

    const hostIds = new Set(matched.map((d) => d.id));
    const hostNames = new Set(matched.map((d) => d.host));
    /* The selected finding's devices are UNIONED in rather than intersected: the reader chose this
       finding explicitly, so it must be findable on the fabric even when an unrelated filter is
       also set. Both are emphasis, and emphasis dims rather than hides, so a union cannot conceal
       anything the filter was meant to reveal. Matched by host or id, the same way the severity
       filter above resolves `finding.devices`. */
    if (finding !== null) {
      const named = new Set(finding.devices);
      for (const d of devices) {
        if (named.has(d.host) || named.has(d.id)) {
          hostIds.add(d.id);
          hostNames.add(d.host);
        }
      }
    }
    /* The stranded set joins the same way, and for the same reason: what becomes unreachable is
       what the reader asked about, so it must lift out of the dimmed field even when an unrelated
       filter is set. The label layer distinguishes it from a filter match. */
    for (const id of strandedIds) {
      hostIds.add(id);
      const d = deviceById.get(id);
      if (d) hostNames.add(d.host);
    }
    const linkIds = links
      .filter((l) => (hostIds.has(l.a) || hostNames.has(l.a)) && (hostIds.has(l.b) || hostNames.has(l.b)))
      .map((l) => l.id);
    return {
      hosts: [...hostIds],
      links: linkIds,
      blockedHost: blocked.host,
      blockedLink: blocked.link,
    };
  }, [devices, links, query, severities, roles, onlyUncollected, traceMark, findingId, blast, strandedIds]);

  /* TWO CLAIMS, TWO CHANNELS — they are no longer allowed to displace each other.
     "This hop ended the traced packet's story, and how" is a FACT about the packet in front of the
     reader. "Removing this host would cut other hosts off the fabric" is a HYPOTHESIS about a
     failure that has not happened. They were competing for one `data-alarm` slot, which meant the
     winner silently erased the loser: a delivered flow over an articulation point could say only
     one of the two true things about that host. Each gets its own attribute on the label now, so
     neither statement can overwrite the other — the same reason `selected` and `stranded` are
     already separate channels. */
  const labelAlarm = useMemo(() => fabricVerdictChipOf(trace), [trace]);

  const cutPointId = blast.host;

  /** A4: the selected finding, for the label layer's own mark. Same lookup the highlight uses. */
  const labelFinding = useMemo(() => {
    if (findingId === null) return null;
    const f = fabric.findings.find((x) => x.id === findingId);
    /* The mark's ink is keyed by a MEMBER only: `String(severity).toLowerCase()` drew an unrecognised "critical" in the
       Critical outline and a missing one as "null". Anything off the graded scale gets a non-member token. */
    const severity = f === undefined ? "" : recognisedSeverity(f.severity) ? f.severity.toLowerCase() : f.severity === null ? "not-stated" : "unrecognised";
    return f === undefined ? null : { id: f.id, severity, hosts: new Set(f.devices) };
  }, [findingId]);

  useEffect(() => {
    sceneRef.current?.setHighlight(highlight);
  }, [sceneEpoch, highlight]);

  /* ── resize: one choke point, coalesced to a frame ───────────────────────── */

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let frame = 0;
    let settle: ReturnType<typeof setTimeout> | null = null;
    let pending: { w: number; h: number } | null = null;
    let applied: { w: number; h: number } | null = null;

    /* RESPONSIVENESS FIX, 2026-09-21 (acceptance E5: viewport resizes measured at 380-451 ms, one
       Fabric3D rAF alone 377 ms). A resize reallocates every render target of the post chain and
       repaints through all of them, and a dragged window edge or a rail resize delivers a new size
       on EVERY frame — so the fabric re-sized itself up to sixty times a second. It now follows the
       drag at most once per RESIZE_SETTLE_MS: the first size lands on the next frame, sizes in
       between are coalesced, and the last one always lands. Between two applied sizes the canvas
       is simply stretched by CSS (`inline-size: 100%`), which is the browser's own behaviour for a
       resized canvas and never a blank one. */
    const flush = () => {
      frame = 0;
      if (!pending) return;
      if (applied && applied.w === pending.w && applied.h === pending.h) return;
      applied = pending;
      sceneRef.current?.resize(pending.w, pending.h);
      settle = setTimeout(() => {
        settle = null;
        if (pending && frame === 0) frame = requestAnimationFrame(flush);
      }, RESIZE_SETTLE_MS);
    };
    const push = (w: number, h: number) => {
      // A zero-sized canvas is a division by zero in the projection matrix; clamp rather than
      // forwarding a collapsed layout to the renderer.
      pending = { w: Math.max(1, Math.round(w)), h: Math.max(1, Math.round(h)) };
      if (frame === 0 && settle === null) frame = requestAnimationFrame(flush);
    };

    const rect = host.getBoundingClientRect();
    push(rect.width, rect.height);

    // The cleanup is returned on every path, including the one where ResizeObserver is absent:
    // the initial push above has already armed a frame, and an unreturned cleanup leaks it.
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        for (const entry of entries) push(entry.contentRect.width, entry.contentRect.height);
      });
      ro.observe(host);
    }
    return () => {
      ro?.disconnect();
      if (frame !== 0) cancelAnimationFrame(frame);
      if (settle !== null) clearTimeout(settle);
    };
  }, [sceneEpoch]);

  /* ── announcements ───────────────────────────────────────────────────────── */

  const hadSelection = useRef(false);
  useEffect(() => {
    if (linkId !== null) {
      hadSelection.current = true;
      setAnnouncement(describeLink(linkId));
    } else if (deviceId !== null) {
      hadSelection.current = true;
      setAnnouncement(describeDevice(deviceId));
    } else if (hadSelection.current) {
      setAnnouncement("Fabric selection cleared.");
    }
  }, [deviceId, linkId]);

  /* An open Fabric list covers the left of the stage. The framing is told before any whole-fabric
     or device framing, and again whenever the list is shown or hidden, so Reset view frames the
     fabric in the stage the reader can SEE (camera.ts :: setStageOcclusion). */
  useEffect(() => {
    syncStageOcclusion(canvasRef.current);
  }, [treeVisible, sceneError]);

  const resetView = useCallback(() => {
    syncStageOcclusion(canvasRef.current);
    sceneRef.current?.resetCamera();
    canvasRef.current?.focus({ preventScroll: true });
  }, []);

  const focusDevice = useCallback((id: string) => {
    sceneRef.current?.focusDevice(id);
  }, []);

  /* The pointer layer's stated successor when a focused off-view pointer leaves the stage: the canvas,
     now framing the device the pointer named. Stated, not focused here: FabricLabels hands it to
     focus-return.ts's third door, which checks it really took focus and falls through otherwise. */
  const pointerSuccessors = useCallback((): readonly (HTMLElement | null)[] => [canvasRef.current], []);

  const tierLabel = qualityTier ?? "probing";
  /* A reduced tier and a standing budget breach are both "this frame is not what the design
     specifies", and the chip marks either. They are worded apart so the reader is never left
     guessing which one happened. */
  const degraded = (qualityTier !== null && qualityTier !== "high") || breach !== null;
  const qualityTitle =
    breach !== null
      ? `Over the draw-call budget: this frame costs ${breach.calls} calls against a ceiling of ` +
        `${breach.budget} for a frame with ${breach.outlines} outline effect(s) active. ` +
        `It has been over for at least two consecutive rendered frames, so it is a standing cost, ` +
        `not a one-off rebuild.` +
        (qualityTier === null ? "" : ` Render quality tier in force: ${qualityTier}.`)
      : qualityTier === null
        ? "The scene has not yet reported a render quality tier."
        : `Render quality tier in force: ${qualityTier}. Draw calls are within the frame's budget.`;

  return (
    /* `data-fabric-surface` marks what counts as input ON the fabric (canvas, labels, HUD): input
       anywhere else lets the scene hold an owed render until the burst pauses — see
       ./panelInput. */
    <div
      className={className === undefined ? "fabric3d" : `fabric3d ${className}`}
      ref={hostRef}
      data-fabric-surface=""
      /* "pending" while a fabric too large for one slice is still being laid out (no scene exists
         then), "ready" once its layout does. The stage's warm-up wording can say "laying out" rather
         than "starting the renderer" from this (verifier V2-3), and review/measure-scale.mjs waits on it. */
      data-layout={layoutReady ? "ready" : "pending"}
    >

      {/* React never puts children in this slot, so the imperatively-owned canvas cannot collide
          with reconciliation. */}
      <div className="fabric3d__canvas-host" ref={canvasSlotRef} />

      {/* scene.project() reports canvas-relative CSS pixels and this overlay is positioned against
          the canvas box, so the label loop must not subtract the container origin a second time. */}
      <FabricLabels
        devices={devices}
        sceneRef={sceneRef}
        epoch={sceneEpoch}
        hover={hover}
        selectedId={deviceId}
        /* The alarm treatment is drawn at the node ANCHOR, and the label box sits on that same
           anchor: measured, the halo survived only as thin slivers above and below the `core1`
           label, and a denied trace differed from a delivered one by an 18×23 px region. The
           label layer is told which host carries the trace's ending so it can move out of the way
           AND carry the state in words and a glyph, instead of leaving it to a colour behind a box.
           The KIND travels with it: the canvas has ONE alarm channel and the trace has THREE
           endings, so the word is decided here, where the verdict's band is still known. The cut
           point travels separately because it is a different claim about the same host. */
        alarm={labelAlarm}
        cutPointId={cutPointId}
        strandedIds={strandedIds}
        strandedQualifier={blast.qualifier}
        onStrandedUnseen={onStrandedUnseen}
        finding={labelFinding}
        coordinateSpace="canvas"
        /* An off-view pointer the reader activated leaves as its host comes into view; the focus it
           held goes to the canvas, which is now framing that host (acceptance D3: never to <body>). */
        onPointerFocusLost={pointerSuccessors}
      />

      <div className="fabric3d__hud" data-label-keepout="">
        <span
          className="fabric3d__quality"
          data-degraded={degraded ? "true" : "false"}
          data-over-budget={breach !== null ? "true" : "false"}
          title={qualityTitle}
        >
          <span className="fabric3d__quality-dot" aria-hidden="true" />
          Quality {tierLabel}
          {breach !== null && (
            <span className="fabric3d__quality-breach">
              {" · "}
              {breach.calls}/{breach.budget} draw calls
            </span>
          )}
        </span>
        <button
          type="button"
          className="fabric3d__btn"
          /* commands.ts activates the control the mouse would, so the palette and the `r` binding
             cannot drift into doing something different from this button. */
          data-atlas-command="fabric.resetCamera"
          onClick={resetView}
        >
          Reset view
        </button>
        {/* A11Y AUDIT FIX, 2026-09-21 (D6). This button is a SCREEN toggle, not an availability
            toggle, and the difference was not stated anywhere a reader could find it.
            Measured (review/_audit_a11y_d3b.mjs): with the panel closed it reports
            aria-pressed="false" while all 31 treeitems are still in the accessibility tree. That
            is deliberate and it is the whole D6 answer — the tree is the canvas's permanent DOM
            equivalent, so it must never be gated behind a control the reader has to find first
            (see FabricA11yTree.tsx and the clip rule in Fabric3D.css, which is the standard
            visually-hidden recipe rather than a 1px accident). But a reader who meets a full
            device tree while the control that names it says "not pressed" has been handed a
            contradiction, so the arrangement is now said out loud instead of inferred.

            A description rather than a renamed label: the accessible name stays exactly the
            visible words, which is what SC 2.5.3 is about and what lets the voice-control user
            say "Fabric list". */}
        {selectionIsTraceHop && hopBlastCount > 0 && activeHopHost !== null ? (
          <button
            type="button"
            className="fabric3d__btn"
            aria-pressed={hopBlastShown}
            data-hop-blast={hopBlastShown ? "shown" : "hidden"}
            data-certainty={hopBlast?.certainty ?? ""}
            title={`Removing ${activeHopHost} would strand ${hopBlastCount} host${hopBlastCount === 1 ? "" : "s"}${
              hopBlastQualifier === "" ? "" : ` — ${hopBlastQualifier}: ${(hopBlast?.caveats ?? []).join(" ").replace(/.s*$/, "")}`
            }. Drawn on request while a trace is shown, so the failure hypothesis never overwrites the packet's answer.`}
            onClick={() => setHopBlastShown((v) => !v)}
          >
            {`Blast radius: ${activeHopHost} strands ${hopBlastCount}${hopBlastQualifier === "" ? "" : ` (${hopBlastQualifier})`}`}
          </button>
        ) : null}
        {/* A blast question asked and NOT answered is said on the canvas. Without this an
            uncollected host drew no overlay at all, which looks the same as "strands nothing". */}
        {blast.undetermined !== null ? (
          <span className="fabric3d__quality" role="note" data-blast="not-determinable" title={blast.undetermined.why}>
            {`Blast radius not determinable: ${blast.undetermined.subject} ${blast.undetermined.short}`}
          </span>
        ) : blast.stranded.length > 0 ? (
          /* The count, on the fabric, whenever a blast radius is drawn — and every stranded host the
             label layer could not draw, named (A6). Marked + out of view = the whole set, so the
             stage always accounts for all of it. The certainty clause stays attached to the count it
             qualifies. */
          <span
            className="fabric3d__quality"
            role="note"
            data-blast={blast.certainty ?? ""}
            data-stranded-total={strandedIds.size}
            data-stranded-unseen={unseenHosts.length + coveredHosts.length}
            data-stranded-covered={coveredHosts.length}
            data-cut-mark={cutMarkUnseen === null ? "shown" : "not-shown"}
            title={[
              unseenHosts.length === 0 && coveredHosts.length === 0
                ? `Every host that ${blast.host ?? blast.link ?? "the selection"} strands carries a stranded mark on the fabric.`
                : "",
              unseenHosts.length === 0
                ? ""
                : `Not in view, so their stranded marks are not drawn: ${unseenHosts.join(", ")}. The camera is not moved by a selection; Reset view or the Fabric list reaches them.`,
              coveredHosts.length === 0
                ? ""
                : `No clear place on this stage for their stranded marks, which lie under other labels: ${coveredHosts.join(", ")}. A wider stage, a zoom or the Fabric list shows them.`,
              cutMarkUnseen === null ? "" : `${blast.host}'s own cut-point mark is ${cutMarkUnseen}.`,
            ]
              .filter((t) => t !== "")
              .join(" ")}
          >
            {`${blast.host ?? blast.link ?? "Selection"} strands ${strandedIds.size}${blast.qualifier === "" ? "" : ` (${blast.qualifier})`}`}
            {unseenHosts.length === 0 && coveredHosts.length === 0 ? ` · all ${strandedIds.size} marked` : ""}
            {unseenHosts.length === 0 ? "" : ` · ${unseenHosts.length} out of view: ${unseenHosts.join(", ")}`}
            {coveredHosts.length === 0 ? "" : ` · ${coveredHosts.length} under other labels: ${coveredHosts.join(", ")}`}
            {cutMarkUnseen === null ? "" : ` · cut-point mark ${cutMarkUnseen}`}
          </span>
        ) : null}
        <button
          type="button"
          className="fabric3d__btn"
          aria-pressed={treeVisible}
          aria-describedby={treeNoteId}
          data-atlas-command="fabric.toggleTree"
          onClick={() => setTreeVisible((v) => !v)}
        >
          Fabric list
        </button>
        <span className="visually-hidden" id={treeNoteId}>
          The fabric list is always readable by a screen reader, whether or not it is shown. This
          shows it on screen as well.
        </span>
      </div>

      {sceneError === null ? null : (
        <div className="fabric3d__fallback" role="alert" data-testid="fabric3d-fallback">
          <h2 className="fabric3d__fallback-title">3-D fabric unavailable</h2>
          <p>
            The renderer could not start: {sceneError}. The fabric list below holds the same
            devices, links and tiers, and every one of them is still selectable. Nothing about the
            network has been hidden — only the 3-D drawing of it is missing.
          </p>
        </div>
      )}

      <FabricLegend id={legendId} devices={devices} links={links} />

      <FabricA11yTree
        devices={devices}
        links={links}
        tiers={tiers}
        visible={treeVisible || sceneError !== null}
        onHide={() => setTreeVisible(false)}
        onFocusDevice={focusDevice}
      />

      <p id={helpId} className="fabric3d__sr-only">
        Three-dimensional fabric view. Arrow keys move the selection to the nearest device in that
        direction on screen. Enter frames the camera on the selected device. Escape clears the
        selection. Home frames the whole fabric. Plus and minus zoom. Shift with an arrow key orbits the
        camera and Alt (Option) with an arrow key pans it. The Fabric list button opens
        an equivalent tree of tiers, devices and links that does not require the canvas.
      </p>
      <div className="fabric3d__sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}

/**
 * Is there a picture of THIS geometry on screen? Every POINTER pick and hover passes through here.
 *
 * COLD LOAD. While the scene warms up for the first time the canvas is blank ("Building the 3-D
 * fabric — N of M shader programs linked"), but the geometry the picker ray-casts against already
 * exists. MEASURED: on `?d=access1` one click on the blank warming canvas hit empty ground, and the
 * empty pick CLEARED the URL-restored selection — the Inspector went to "Nothing is selected" with
 * nothing visible to explain why; a double-click on `?l=L26` did the same. A pointer pick is a
 * choice made by LOOKING at the fabric, so until it is drawn there is nothing to choose from: every
 * pointer pick — hit or empty — and every hover is ignored. The gate is on the pick itself rather
 * than only on the empty case, because selecting a device the reader cannot see is the same defect
 * in the other direction. Keyboard traversal is untouched: it walks the named device list.
 *
 * RE-WARM-UP (A4 audit fix, 2026-09-21). This gate used to be "no warm-up is running", and a
 * warm-up also runs AFTER the first paint — an adaptive tier step, a theme change. MEASURED by the
 * A4 critic: ~1.3 s after selecting dist2 a re-warm-up held `warmupStage !== null` for ~0.5 s, and
 * a click on core1 in that window was silently discarded while the canvas still showed the
 * complete previous frame (repro: `setQuality` then a device click — the URL stayed on the old
 * device for 2 of 3 clicks). That frame IS the fabric the reader is choosing from, and a tier or
 * theme change moves no geometry, so a pick against it is the pick they meant. The gate is now
 * "has this scene presented a frame of its current geometry": latched the first time the scene is
 * seen drawing, and cleared only when a data change rebuilds the graph (the frame on screen is then
 * of a different topology — see the setData effect). That covers the structural class rather than
 * a list of warm-up causes: any re-warm-up that keeps the geometry keeps the fabric clickable.
 */
const presented = new WeakMap<FabricSceneEx, true>();

function notePresented(scene: FabricSceneEx | null): void {
  if (scene !== null && (scene.stats().warmupStage ?? null) === null) presented.set(scene, true);
}

function isDrawn(scene: FabricSceneEx | null): boolean {
  if (scene === null) return false;
  notePresented(scene);
  return presented.get(scene) === true;
}

function applyPick(r: PickResult | null): void {
  const st = useInvestigation.getState();
  if (r === null) {
    // Clicking the ground is an explicit "nothing", and it clears both. It does not reset the
    // camera, the query or the trace: selection re-aims the investigation, it never restarts it.
    st.selectDevice(null);
    st.selectLink(null);
    return;
  }
  if (r.kind === "device") st.selectDevice(r.id, { surface: "fabric" });
  else st.selectLink(r.id);
}

export default Fabric3D;
