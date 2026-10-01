/**
 * telemetry.ts — the one channel the 3-D subsystem publishes its live readings on.
 *
 * WHY THIS EXISTS. `StatusBar` has always carried an fps / quality-tier / convergence readout, and
 * it was rendered as `<StatusBar onOpenCite={…} />` — with `stats` defaulting to `null`. The branch
 * that draws the tier was therefore unreachable in the shipped product, and the bar permanently
 * said "scene telemetry: not observed — the 3-D subsystem has not reported a frame yet" while the
 * scene was rendering at 60 fps. A default that renders a plausible absence is exactly the shape
 * this repository's doctrine names: absence presented as a settled state, with nothing to
 * contradict it. So the wiring gets a named channel rather than another prop threaded through the
 * shell, and a test that fails when the readout goes quiet again.
 *
 * WHY IT IS NOT REACT STATE IN THE SHELL. The scene emits at most twice a second, which is cheap —
 * but `App` re-rendering twice a second is not: it would put the whole investigation tree on a
 * timer. An external store lets exactly one component subscribe (`useSceneStats`), so a frame
 * report re-renders the status bar and nothing else. Identical reasoning, and identical shape, to
 * `FabricLabels :: createHoverChannel`.
 *
 * The value is `null` until the subsystem reports, and returns to `null` when the scene is
 * released — "not observed" then means it, and the status bar's honest branch is reached for a
 * real reason instead of a missing prop.
 */
import { useSyncExternalStore } from "react";
import type { SceneStatsEx } from "./scene";

let current: SceneStatsEx | null = null;
const listeners = new Set<() => void>();

/**
 * Minimum interval between NOTIFICATIONS, in milliseconds.
 *
 * MEASURED, and the reason this throttle exists at all. The scene emits at most twice a second, and
 * passing every emit through to React cost 6-7 fps of the fabric's own frame rate: measured on the
 * release build with a hardware renderer, the same sustained-camera-motion sample was 48.7-49.9 fps
 * with 77-84 frames under the 55 fps bar when every emit re-rendered the status bar, against
 * 55.95 fps and 31 under-bar frames with the publish disabled. A status line is not worth 2-3
 * dropped frames twice a second, so it updates once a second and only when what it DRAWS changes.
 */
const NOTIFY_INTERVAL_MS = 1000;

let lastKey = "";
/** Non-null while a throttle window is open. The window IS the timer; nothing reads a clock. */
let window_: ReturnType<typeof setTimeout> | null = null;
/** A drawn value changed during the open window and still has to reach the screen. */
let pending = false;

/**
 * What the status bar can draw, as a string.
 *
 * Everything else in the reading — frame cost, draw calls, triangles, the quality reasons — is
 * diagnostic and no subscriber renders it, so a change in one of those must not cost a render.
 * (The warm-up counters USED to be in that category and no longer are: see the note in the body.)
 *
 * `fps` stays in this key even though the PERMANENT line no longer draws it (acceptance F6 — see
 * `app/StatusBar.tsx`). It is drawn inside the renderer disclosure, and a readout that froze at
 * whatever the reading happened to be when the panel opened would be a stale number presented as a
 * live one. It is rounded here because it is rounded there: a panel reading "60 fps" should not
 * re-render for 60.03. While the panel is closed this costs a React render of one component whose
 * output is unchanged — which is what `status-telemetry.test.tsx` measures as zero DOM mutations.
 * `frameMs` and `drawCalls` are deliberately NOT in the key: they change every emit, and pinning
 * the panel to the second is the honest trade against putting the fabric back on React's frame path.
 */
function renderedKey(s: SceneStatsEx | null): string {
  if (s === null) return "none";
  /* `warmupStage` and `programsLinked` joined this key when `app/surfaces.tsx :: StageWarmup`
     started drawing them (acceptance E5: the cold-load warm-up is the one piece of work in this
     product that is allowed to take seconds, and it had no affordance on screen at all). They cost
     nothing in steady state — once the scene is drawing, `warmupStage` is permanently null and
     `programsLinked` never moves again, so neither can change this key. They only produce
     notifications during the warm-up itself, which is exactly when something is drawing them. */
  return (
    `${Math.round(s.fps)}|${s.quality}|${s.converged ? 1 : 0}|${s.qualityAuto ? 1 : 0}` +
    `|${s.warmupStage ?? "-"}|${s.programsLinked}/${s.programsTotal}` +
    /* The E4 bar flag is DRAWN on the permanent line (app/StatusBar.tsx), so its change must reach it. */
    `|${s.frameRateBelowBar ? 1 : 0}`
  );
}

function notify(): void {
  lastKey = renderedKey(current);
  for (const l of listeners) l();
}

/**
 * Open a throttle window. On its trailing edge, publish whatever the newest reading now says.
 *
 * A timer rather than a timestamp comparison, deliberately: a clock read here would be one more
 * justified entry in a source tree whose determinism gate caps that population at eight, and it
 * would buy nothing — the only question this throttle asks is "has a window elapsed", which is
 * exactly what a timer answers.
 */
function openWindow(): void {
  window_ = setTimeout(() => {
    window_ = null;
    if (!pending) return;
    pending = false;
    if (renderedKey(current) === lastKey) return;
    notify();
    openWindow();
  }, NOTIFY_INTERVAL_MS);
}

/** Publish a reading. Called from the scene's `stats` event. */
export function publishSceneStats(next: SceneStatsEx | null): void {
  if (current === next) return;
  /* The stored value is ALWAYS current: a reader that asks between notifications gets the latest
     reading, never a stale one. Only the notification is throttled. */
  const previous = current;
  current = next;
  if (renderedKey(next) === lastKey) return;
  /* A warm-up STARTING or ENDING is published at once, throttle or not. The stage draws "Building
     the 3-D fabric" off this reading, so a throttled end left that sentence on screen for up to a
     second over a fabric that was already drawn (seen in a theme round trip, which now warms up
     rather than stalling the click), and a throttled start left a busy stage unexplained. Only the
     edges bypass the window; progress WITHIN a warm-up is still throttled. */
  const warmingBefore = previous !== null && previous.warmupStage !== null;
  const warmingNow = next !== null && next.warmupStage !== null;
  if (warmingBefore !== warmingNow) {
    if (window_ !== null) clearTimeout(window_);
    pending = false;
    notify();
    openWindow();
    return;
  }
  if (window_ !== null) {
    /* Trailing edge: the last reading of a throttled window must still reach the screen, or a tier
       step-down could sit unreported for as long as the scene kept emitting. */
    pending = true;
    return;
  }
  notify();
  openWindow();
}

/**
 * Publish a reading and notify immediately, throttle or not.
 *
 * For the release of a scene: "not observed" must appear the moment the scene goes, not up to a
 * second later, because until it does the bar is reporting a renderer that no longer exists.
 */
export function releaseSceneStats(): void {
  current = null;
  pending = false;
  if (window_ !== null) {
    clearTimeout(window_);
    window_ = null;
  }
  if (lastKey !== "none") notify();
}

/** The latest reading, or `null` when the subsystem has not reported one. */
export function readSceneStats(): SceneStatsEx | null {
  return current;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

/**
 * Subscribe a component to the live readings.
 *
 * The server snapshot is the same getter: this app has no server renderer, and returning a
 * different value there would make the first client render disagree with the markup it hydrates.
 */
export function useSceneStats(): SceneStatsEx | null {
  return useSyncExternalStore(subscribe, readSceneStats, readSceneStats);
}
